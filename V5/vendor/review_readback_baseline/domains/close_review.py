"""Read-only close-review production and response projection."""
from __future__ import annotations

import math
import re
from typing import Any

from infrastructure.review_store import ReviewStore


_HK_CODE = re.compile(r"^HK\.(\d{1,5})$")
_MODEL_KEY = "0.2_prob_active"
_REVIEW_STAGE_IDS = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
)


def _code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.endswith(".HK"):
        text = f"HK.{text[:-3]}"
    elif not text.startswith("HK."):
        digits = "".join(character for character in text if character.isdigit())
        text = f"HK.{digits}" if digits else ""
    match = _HK_CODE.fullmatch(text)
    return f"HK.{int(match.group(1)):05d}" if match else ""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric(selected_codes: list[str], truth_codes: set[str]) -> dict[str, Any]:
    hit_codes = [code for code in selected_codes if code in truth_codes]
    selected_count = len(selected_codes)
    hit_count = len(hit_codes)
    return {
        "evidence_status": "READY",
        "selected_count": selected_count,
        "selected_codes": selected_codes,
        "hit_count": hit_count,
        "hit_codes": hit_codes,
        "coverage": hit_count / 20,
        "precision": hit_count / selected_count if selected_count else 0.0,
        "coverage_pct": round(hit_count / 20 * 100.0, 6),
        "precision_pct": round(hit_count / selected_count * 100.0, 6)
        if selected_count
        else 0.0,
    }


def _missing_metric() -> dict[str, Any]:
    return {
        "evidence_status": "MISSING",
        "selected_count": None,
        "selected_codes": [],
        "hit_count": None,
        "hit_codes": [],
        "coverage": None,
        "precision": None,
        "coverage_pct": None,
        "precision_pct": None,
    }


def build_native_close_review(
    trade_date: str,
    *,
    close_rows: list[dict[str, Any]],
    model_rows: list[dict[str, Any]],
    stage_rows: dict[str, list[dict[str, Any]] | None],
    close_source_sha256: str,
) -> dict[str, Any]:
    """Calculate the frozen close-Top20 review from V3.5-owned inputs."""
    prepared_close: list[dict[str, Any]] = []
    seen_close: set[str] = set()
    for source in close_rows:
        code = _code(source.get("code") or source.get("code_norm") or source.get("symbol"))
        close = _number(source.get("close"))
        pre_close = _number(source.get("pre_close") or source.get("prev_close"))
        amount = _number(source.get("amount")) or 0.0
        row_date = str(source.get("trade_date") or source.get("trade_date_compact") or "")
        if row_date != trade_date or not code or code in seen_close or close is None or pre_close in (None, 0.0):
            continue
        seen_close.add(code)
        pct_chg = (close / pre_close - 1.0) * 100.0
        prepared_close.append(
            {
                "code": code,
                "name": str(source.get("name") or source.get("stock_name") or "").strip(),
                "pct_chg": pct_chg,
                "pct_chg_close": pct_chg,
                "close": close,
                "pre_close": pre_close,
                "amount": amount,
                "trade_date": trade_date,
            }
        )
    prepared_close.sort(key=lambda row: (-row["pct_chg_close"], -row["amount"], row["code"]))
    close_top20 = [{**row, "rank": rank} for rank, row in enumerate(prepared_close[:20], start=1)]
    truth_codes = {row["code"] for row in close_top20}

    prepared_model: list[dict[str, Any]] = []
    seen_model: set[str] = set()
    ordered_model = sorted(
        model_rows,
        key=lambda row: (_number(row.get("pool_rank") or row.get("rank")) or 1e12, _code(row.get("symbol") or row.get("code"))),
    )
    for source in ordered_model:
        if str(source.get("target_date") or source.get("trade_date") or "") != trade_date:
            continue
        if str(source.get("market") or "").upper() not in {"HK", "HKCONNECT"}:
            continue
        code = _code(source.get("symbol") or source.get("code"))
        if not code or code in seen_model:
            continue
        seen_model.add(code)
        prepared_model.append(
            {
                "rank": len(prepared_model) + 1,
                "code": code,
                "name": str(source.get("stock_name") or source.get("name") or "").strip(),
                "strategy": "prob_active",
                "pool_version": "0.2",
                "trade_date": trade_date,
                "hit_top20": code in truth_codes,
            }
        )
        if len(prepared_model) == 100:
            break
    model_codes = [row["code"] for row in prepared_model]
    model_complete = len(prepared_model) == 100
    model_metric = _metric(model_codes, truth_codes) if model_complete else _missing_metric()

    all_stage_rows: list[dict[str, Any]] = []
    stage_metrics: dict[str, dict[str, Any]] = {}
    missing_stages: list[str] = []
    code_to_stages: dict[str, list[str]] = {}
    for stage_id in _REVIEW_STAGE_IDS:
        sources = stage_rows.get(stage_id)
        if sources is None:
            missing_stages.append(stage_id)
            stage_metrics[stage_id] = _missing_metric()
            continue
        selected_codes: list[str] = []
        seen_stage: set[str] = set()
        for source in sources:
            if str(source.get("market") or "").upper() not in {"HK", "HKCONNECT"}:
                continue
            code = _code(source.get("code") or source.get("symbol"))
            if not code or code in seen_stage:
                continue
            seen_stage.add(code)
            selected_codes.append(code)
            code_to_stages.setdefault(code, []).append(stage_id)
            all_stage_rows.append(
                {
                    "stage_id": stage_id,
                    "stage_rank": len(selected_codes),
                    "code": code,
                    "name": str(source.get("name") or source.get("stock_name") or "").strip(),
                    "trade_date": trade_date,
                    "hit_top20": code in truth_codes,
                }
            )
        stage_metrics[stage_id] = _metric(selected_codes, truth_codes)

    union_codes: list[str] = []
    seen_union: set[str] = set()
    for row in all_stage_rows:
        if row["code"] not in seen_union:
            seen_union.add(row["code"])
            union_codes.append(row["code"])
    stage_union = _metric(union_codes, truth_codes) if not missing_stages else _missing_metric()

    model_set = set(model_codes) if model_complete else set()
    stage_set = set(union_codes) if not missing_stages else set()
    attribution: list[dict[str, Any]] = []
    for row in close_top20:
        in_model = row["code"] in model_set
        in_stage = row["code"] in stage_set
        classification = (
            "shared" if in_model and in_stage
            else "model_only" if in_model
            else "stage_only" if in_stage
            else "missed"
        )
        stages = code_to_stages.get(row["code"], [])
        attribution.append(
            {
                **row,
                "model_0_2_hit": in_model,
                "stage_union_hit": in_stage,
                "first_stage": stages[0] if stages else None,
                "all_stages": stages,
                "classification": classification,
            }
        )

    cannot_confirm: list[str] = []
    if len(close_top20) < 20:
        cannot_confirm.append(f"FULL_CLOSE_TOP20_NOT_READY:{len(close_top20)}/20")
    if not model_complete:
        cannot_confirm.append(f"MODEL_0_2_TOP100_NOT_READY:{len(prepared_model)}/100")
    cannot_confirm.extend(f"MISSING_STAGE:{stage_id}" for stage_id in missing_stages)
    status = (
        "PENDING_CLOSE_TOP20" if len(close_top20) < 20
        else "MODEL_0_2_SOURCE_MISSING" if not model_complete
        else "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE" if missing_stages
        else "MODEL_REVIEW_READY"
    )
    model_hits = model_metric["hit_count"]
    stage_hits = stage_union["hit_count"]
    return {
        "schema_version": "v3_5.close_review.v1",
        "trade_date": trade_date,
        "status": status,
        "primary_kpi": "全港股通收盘涨幅Top20覆盖率",
        "models": {_MODEL_KEY: model_metric},
        "stages": stage_metrics,
        "stage_union": stage_union,
        "kpi": {
            "model_0_2_close_top20_hits": model_hits,
            "stage_union_close_top20_hits": stage_hits,
        },
        "row_counts": {
            "hkconnect_universe": len(prepared_close),
            "close_top20": len(close_top20),
            "model_0_2": len(prepared_model),
            "stage_rows": len(all_stage_rows),
        },
        "close_top20": close_top20,
        "model_rows": prepared_model,
        "stage_rows": all_stage_rows,
        "top20_attribution": attribution,
        "missing_stages": missing_stages,
        "cannot_confirm": cannot_confirm,
        "close_source_sha256": close_source_sha256,
        "evidence_mode": "V3_5_NATIVE_PRODUCTION",
        "reference_snapshot": False,
        "write_policy": "review_only_read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def close_review(store: ReviewStore, trade_date: str) -> dict[str, Any]:
    reference = store.read_reference(trade_date)
    if reference is None:
        reference = {
            "schema_version": "v3_5.close_review_reference.v1",
            "trade_date": trade_date,
            "status": "REFERENCE_NOT_IMPORTED",
            "primary_kpi": "全港股通收盘涨幅Top20覆盖率",
            "models": {},
            "stages": {},
            "stage_union": {},
            "kpi": {},
            "row_counts": {},
            "close_top20": [],
            "model_rows": [],
            "stage_rows": [],
            "top20_attribution": [],
            "missing_stages": [],
            "cannot_confirm": ["CLOSE_REVIEW_REFERENCE_NOT_IMPORTED"],
            "reference_snapshot": False,
            "write_policy": "review_only_read_only",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    return {
        "schema_version": "v3_5.close_review_response.v1",
        "trade_date": trade_date,
        "reference_snapshot": bool(reference.get("reference_snapshot")),
        "market_reviews": {
            "HK": {
                "market": "HK",
                "display_name": "港股通复盘",
                "model_selection_review": reference,
            }
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
