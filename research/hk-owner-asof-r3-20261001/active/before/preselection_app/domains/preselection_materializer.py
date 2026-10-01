"""Graph-bound V3 preselection producers, without final-API imports."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.preselection_pool_store import PreselectionPoolStore

HK_0_2_FROZEN_MODEL_SHA256 = "3b0d5d5239342439cabf25b30012365a64d78839bc3cd4d90bad7be6ff4aaa07"
SHARED_V192_ROLE = "A_SHARE_V192_PREMARKET_POOL_V3"
SHARED_V192_FORMULA_SOURCE = "computed_main_chart_formula_20260515"
SHARED_V192_RANK_BOUNDARY = "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY"
SHARED_V192_ENTRY_FIELDS = (
    "gold_brick_context", "brick_resonance_context", "brick_buy",
    "brick_buy1_low_absorb", "brick_buy2_attack", "primary_buy_signal",
    "secondary_buy_signal", "brick_resonance1", "brick_resonance2",
    "brick_resonance", "formula_source",
)

_A_POOL_SOURCE_CONTRACT = {
    "a_d1_premarket_pool": ("V192_SELECTOR", "（选）", "selector_lane"),
    "a_d1_fupan_watchlist_pool": ("D1_FUPAN", "（复）", "fupan_lane"),
    "a_d1_stage7_fenshi_review_pool": ("D1_STAGE7", "（分）", "stage7_lane"),
}

_RESEARCH_SECTIONS = ("high_priority_candidates", "research_views_pending_review", "source_updates")
_RESEARCH_SOURCE_TOKENS = ("小牛研报纪要", "研报", "研究")
_RESEARCH_TITLE_TOKENS = ("研报", "纪要", "调研", "观点更新", "交流反馈")


@lru_cache(maxsize=32)
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(
    *, trade_date: str, pool_id: str, display_name: str, market: str,
    status: str, producer_id: str, source_role: str, source_path: str,
    source_sha256: str, rows: list[dict[str, Any]], cannot_confirm: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": display_name,
        "market": market,
        "status": status,
        "producer_id": producer_id,
        "source_role": source_role,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "rows": rows,
        "cannot_confirm": list(cannot_confirm or []),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _a_symbol(value: Any) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?", str(value or ""), re.I)
    return f"A.{match.group(1)}" if match else ""


def _a_symbol_from_row(raw: Mapping[str, Any]) -> str:
    candidates = {
        symbol
        for key in ("ts_code", "stock_code", "code")
        if (symbol := _a_symbol(raw.get(key)))
    }
    return candidates.pop() if len(candidates) == 1 else ""


def _row_number(value: Any, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _row_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _normalize_a_csv_rows(path: Path, pool_id: str, trade_date: str) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
        raw_rows = list(csv.DictReader(source))
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        symbol = _a_symbol_from_row(raw)
        if not symbol:
            continue
        row = dict(raw)
        row.update({
            "symbol": symbol,
            "market": "A",
            "pool_id": pool_id,
            "pool_rank": _row_number(raw.get("pool_rank") or raw.get("rank"), index),
            "stock_name": str(raw.get("stock_name") or raw.get("name") or symbol),
            "pool_score": _row_float(raw.get("pool_score") or raw.get("stage7_next_day_pool_score")),
            "signal_date": str(raw.get("signal_date") or ""),
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "formal_pool_write": False,
            "buy_gate_write": False,
        })
        source_tag, source_suffix, source_lane = _A_POOL_SOURCE_CONTRACT.get(
            pool_id, ("", "", "")
        )
        if source_suffix:
            row["display_name"] = row.get("display_name") or f"{row['stock_name']}{source_suffix}"
            row["source_tag"] = row.get("source_tag") or source_tag
            row["source_tags"] = row.get("source_tags") or source_suffix
            row["source_lanes"] = row.get("source_lanes") or source_lane
        rows.append(row)
    return rows


def _parquet_trade_dates(parquet: Any) -> list[str]:
    index = parquet.schema.names.index("trade_date")
    dates: set[str] = set()
    for row_group in range(parquet.num_row_groups):
        column = parquet.metadata.row_group(row_group).column(index)
        statistics = column.statistics
        if statistics is not None and statistics.min is not None and statistics.max is not None:
            minimum, maximum = str(statistics.min), str(statistics.max)
            if minimum == maximum and len(minimum) == 8 and minimum.isdigit():
                dates.add(minimum)
                continue
        for value in parquet.read_row_group(row_group, columns=["trade_date"]).column("trade_date").to_pylist():
            text = str(value or "")
            if len(text) == 8 and text.isdigit():
                dates.add(text)
    return sorted(dates)


def build_selector_premarket_pool(selector_path: Path, trade_date: str) -> dict[str, Any]:
    """Fail closed: the old B-label observation pool is not v1.9.2."""
    selector_path = Path(selector_path)
    return _artifact(
        trade_date=trade_date,
        pool_id="a_d1_premarket_pool",
        display_name="A股 D-1 主预选池",
        market="A",
        status="CANNOT_CONFIRM",
        producer_id="legacy_observation_pool_blocker_v1",
        source_role="LEGACY_OBSERVATION_DISABLED",
        source_path=str(selector_path),
        source_sha256=_sha256(selector_path) if selector_path.is_file() else hashlib.sha256(b"").hexdigest(),
        rows=[],
        cannot_confirm=["LEGACY_OBSERVATION_POOL_DISABLED"],
    )


def build_legacy_selector_observation_pool(selector_path: Path, trade_date: str) -> dict[str, Any]:
    """Retained diagnostic-only B-label view; never used by scheduled pools."""
    import pandas as pd
    import pyarrow.parquet as pq

    selector_path = Path(selector_path)
    parquet = pq.ParquetFile(selector_path)
    signal_dates = [value for value in _parquet_trade_dates(parquet) if value < trade_date]
    if not signal_dates:
        return _artifact(
            trade_date=trade_date, pool_id="a_d1_premarket_pool", display_name="A股 D-1 主预选池",
            market="A", status="CANNOT_CONFIRM", producer_id="v3_selector_premarket_v1",
            source_role="RAW_SOURCE", source_path=str(selector_path), source_sha256=_sha256(selector_path),
            rows=[], cannot_confirm=["D1_SELECTOR_SIGNAL_DATE_UNRESOLVED"],
        )
    signal_date = signal_dates[-1]
    wanted = [
        "trade_date", "ts_code", "name", "primary_buy_signal", "secondary_buy_signal",
        "ref_hold_score", "B1", "B2", "B3", "BG", "pct_chg", "amount",
        "route_context", "gold_brick_context", "brick_context",
    ]
    available = [field for field in wanted if field in parquet.schema.names]
    table = pq.read_table(selector_path, columns=available, filters=[("trade_date", "==", signal_date)])
    frame = table.to_pandas()
    frame = frame[frame["ts_code"].astype(str).str.endswith((".SH", ".SZ"), na=False)].copy()
    if "name" in frame.columns:
        frame = frame[~frame["name"].astype(str).str.contains("ST", case=False, na=False)].copy()
    else:
        frame["name"] = ""
    had_primary = "primary_buy_signal" in frame.columns
    had_secondary = "secondary_buy_signal" in frame.columns
    numeric = ["primary_buy_signal", "secondary_buy_signal", "ref_hold_score", "B1", "B2", "B3", "BG", "amount", "pct_chg"]
    for field in numeric:
        frame[field] = pd.to_numeric(frame[field], errors="coerce").fillna(0) if field in frame else 0
    if not had_primary:
        frame["primary_buy_signal"] = ((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0)).astype(int)
    if not had_secondary:
        frame["secondary_buy_signal"] = ((frame["BG"] > 0) & (frame["primary_buy_signal"] <= 0)).astype(int)
    if int(((frame["primary_buy_signal"] > 0) | (frame["secondary_buy_signal"] > 0)).sum()) == 0 and int(((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0) | (frame["BG"] > 0)).sum()) > 0:
        frame["primary_buy_signal"] = ((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0)).astype(int)
        frame["secondary_buy_signal"] = ((frame["BG"] > 0) & (frame["primary_buy_signal"] <= 0)).astype(int)
    frame = frame[(frame["primary_buy_signal"] > 0) | (frame["secondary_buy_signal"] > 0)].copy()
    frame["pool_score"] = (
        frame["primary_buy_signal"] * 100 + frame["secondary_buy_signal"] * 70
        + frame["B1"] * 8 + frame["B2"] * 12 + frame["B3"] * 5 + frame["BG"] * 5
        + frame["ref_hold_score"] * 3 + (frame["amount"] / 100_000_000).clip(upper=5)
    )
    frame = frame.sort_values(["primary_buy_signal", "pool_score", "amount"], ascending=[False, False, False]).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(frame.to_dict(orient="records"), start=1):
        symbol = _a_symbol(raw.get("ts_code"))
        rows.append({
            **raw, "symbol": symbol, "market": "A", "pool_id": "a_d1_premarket_pool",
            "pool_rank": index, "stock_name": str(raw.get("name") or symbol),
            "signal_date": signal_date, "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        })
    return _artifact(
        trade_date=trade_date, pool_id="a_d1_premarket_pool", display_name="A股 D-1 主预选池",
        market="A", status="FORMAL_INCOMPLETE" if rows else "CANNOT_CONFIRM",
        producer_id="v3_selector_premarket_v1", source_role="RAW_SOURCE",
        source_path=str(selector_path), source_sha256=_sha256(selector_path), rows=rows,
        cannot_confirm=["OBSERVATION_POOL_NOT_FORMAL_BUY_POOL"],
    )


def _load_isolated_shared_module(shared_package_root: Path, leaf: str):
    return load_isolated_package_module(
        Path(shared_package_root),
        package_directory="shared_data",
        module_leaf=leaf,
        namespace_prefix="v35_shared_data",
    )


def _shared_v192_reader(shared_package_root: Path):
    module = _load_isolated_shared_module(shared_package_root, "v192_selector")
    return module.read_verified_v192_pool


def _validate_shared_v192_projection(pool: Any, verification: Mapping[str, Any], *, trade_date: str, signal_date: str) -> list[dict[str, Any]]:
    run_id = str(verification.get("run_id") or "").strip()
    artifact_relative = str(verification.get("artifact_relative") or "")
    expected_artifact = f"runs/{trade_date}/{SHARED_V192_ROLE}/{run_id}/artifact.csv"
    if not run_id or artifact_relative != expected_artifact:
        raise ValueError("shared v1.9.2 role/run provenance mismatch")
    artifact_sha = str(verification.get("artifact_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha):
        raise ValueError("shared v1.9.2 artifact SHA is invalid")
    try:
        expected_count = int(verification.get("row_count"))
    except (TypeError, ValueError):
        raise ValueError("shared v1.9.2 row count is invalid")
    source_rows = [dict(row) for row in pool.rows]
    if expected_count != len(source_rows):
        raise ValueError("shared v1.9.2 row count drift")
    seen: set[str] = set()
    for index, row in enumerate(source_rows, start=1):
        symbol = _a_symbol(row.get("ts_code"))
        if not symbol or symbol in seen or _row_number(row.get("review_rank_v19"), 0) != index:
            raise ValueError("shared v1.9.2 candidate codes/order drift")
        if str(row.get("signal_date") or "") != signal_date or str(row.get("target_date") or "") != trade_date:
            raise ValueError("shared v1.9.2 row date drift")
        if str(row.get("rank_usage_boundary") or "") != SHARED_V192_RANK_BOUNDARY:
            raise ValueError("shared v1.9.2 rank boundary drift")
        if str(row.get("formal_recommendation_allowed") or "").lower() not in {"false", "0"}:
            raise ValueError("shared v1.9.2 recommendation gate drift")
        missing = [field for field in SHARED_V192_ENTRY_FIELDS if row.get(field) in (None, "")]
        if missing:
            raise ValueError("shared v1.9.2 contract missing:" + ",".join(missing))
        if str(row.get("formula_source") or "") != SHARED_V192_FORMULA_SOURCE:
            raise ValueError("shared v1.9.2 formula_source drift")
        if str(row.get("gold_brick_context") or "") not in {"none", "old_gold_candidate"}:
            raise ValueError("shared v1.9.2 gold context drift")
        seen.add(symbol)
    return source_rows


def build_shared_v192_premarket_pool(
    shared_data_root: Path,
    *,
    trade_date: str,
    signal_date: str,
    shared_package_root: Path | None = None,
    reader=None,
) -> dict[str, Any]:
    """Map one verified shared v1.9.2 run into the V3.5 pool contract."""
    if reader is None:
        if shared_package_root is None:
            raise ValueError("shared_package_root is required for v1.9.2 verification")
        reader = _shared_v192_reader(shared_package_root)
    pool = reader(
        Path(shared_data_root),
        target_date=trade_date,
        expected_signal_date=signal_date,
    )
    verification = pool.run.verification
    receipt = pool.run.receipt
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if receipt.get(key) is not False:
            raise ValueError(f"shared v1.9.2 safety flag {key} must be false")
    source_rows = _validate_shared_v192_projection(
        pool,
        verification,
        trade_date=trade_date,
        signal_date=signal_date,
    )
    rows: list[dict[str, Any]] = []
    missing_premarket_score_codes: list[str] = []
    for raw in source_rows:
        symbol = _a_symbol(raw.get("ts_code"))
        if not symbol:
            raise ValueError("shared v1.9.2 row has invalid A-share symbol")
        raw_premarket_score = raw.get("premarket_pool_score")
        has_premarket_score = raw_premarket_score not in (None, "")
        if has_premarket_score:
            try:
                premarket_score = float(str(raw_premarket_score))
            except (TypeError, ValueError):
                raise ValueError("shared v1.9.2 premarket score drift")
        else:
            premarket_score = None
        if premarket_score is None:
            missing_premarket_score_codes.append(symbol)
        rows.append({
            **dict(raw),
            "symbol": symbol,
            "market": "A",
            "pool_id": "a_d1_premarket_pool",
            "pool_rank": _row_number(raw.get("review_rank_v19"), len(rows) + 1),
            # ``final_score`` is the v1.9.2 selector score, not the legacy
            # V3 premarket-pool score.  Only the explicitly materialized
            # shared score is allowed to drive V3.5 stage scoring.
            "pool_score": premarket_score,
            "premarket_score_status": "READY" if premarket_score is not None else "CANNOT_CONFIRM",
            "stock_name": str(raw.get("stock_name") or symbol),
            "signal_date": signal_date,
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "formal_pool_write": False,
            "buy_gate_write": False,
            "display_name": f"{str(raw.get('stock_name') or symbol)}（选）",
            "source_tag": "V192_SELECTOR",
            "source_tags": "（选）",
            "source_lanes": "selector_lane",
            "source_trace": str(raw.get("source_trace") or verification["artifact_relative"]),
        })
    artifact = _artifact(
        trade_date=trade_date,
        pool_id="a_d1_premarket_pool",
        display_name="A股 D-1 v1.9.2候选池",
        market="A",
        status="V192_CANDIDATE_READY" if rows else "V192_CANDIDATE_READY_EMPTY",
        producer_id="v3_shared_v192_consumer_v1",
        source_role="SHARED_VERIFIED_V192",
        source_path=str(verification["artifact_relative"]),
        source_sha256=str(verification["artifact_sha256"]),
        rows=rows,
        cannot_confirm=[
            "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY",
            *(
                [
                    "V3_PREMARKET_POOL_SCORE_MISSING:" + ",".join(missing_premarket_score_codes)
                ]
                if missing_premarket_score_codes
                else []
            ),
        ],
    )
    artifact["source_run_id"] = str(verification["run_id"])
    artifact["source_row_count"] = int(verification["row_count"])
    # Keep the formal shared V3 identity explicit at the artifact boundary.
    # Consumers must not infer a V2/V3 version from the producer name or path.
    artifact.update(
        artifact_role=SHARED_V192_ROLE,
        artifact_version="V3",
        source_artifact_sha256=str(verification["artifact_sha256"]),
        signal_date=signal_date,
        target_date=trade_date,
        source_merge_role="MAIN_STAGE_INPUT",
        stage_selection_eligible=True,
    )
    return artifact


def _shared_hk_0_2_reader(shared_package_root: Path):
    module = _load_isolated_shared_module(shared_package_root, "hk_0_2")
    return module.read_verified_hk_0_2_pool


def build_shared_hk_0_2_pool(
    shared_data_root: Path,
    *,
    trade_date: str,
    signal_date: str,
    shared_package_root: Path | None = None,
    reader=None,
) -> dict[str, Any]:
    """Map the verified shared HK 0.2 Top100 into the V3.5 pool contract."""
    if reader is None:
        if shared_package_root is None:
            raise ValueError("shared_package_root is required for HK 0.2 verification")
        reader = _shared_hk_0_2_reader(shared_package_root)
    pool = reader(
        Path(shared_data_root),
        target_date=trade_date,
        expected_signal_date=signal_date,
    )
    verification = pool.run.verification
    receipt = pool.run.receipt
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if receipt.get(key) is not False:
            raise ValueError(f"shared HK 0.2 safety flag {key} must be false")
    rows: list[dict[str, Any]] = []
    previous_score: float | None = None
    for index, raw_value in enumerate(pool.rows, start=1):
        raw = dict(raw_value)
        code = str(raw.get("code_norm") or raw.get("code") or "").strip().upper().removeprefix("HK.")
        rank = _row_number(raw.get("rank"), index)
        score = _row_float(raw.get("score_prob_active"))
        if not re.fullmatch(r"\d{5}", code) or rank != index:
            raise ValueError("shared HK 0.2 identity/rank mismatch")
        if previous_score is not None and score > previous_score:
            raise ValueError("shared HK 0.2 score order mismatch")
        if str(raw.get("signal_date") or "") != signal_date or str(raw.get("target_date") or "") != trade_date:
            raise ValueError("shared HK 0.2 row date mismatch")
        if str(raw.get("d1_freshness_status") or "") != "PASS" or str(raw.get("selected_strategy") or "") != "prob_active":
            raise ValueError("shared HK 0.2 semantic contract mismatch")
        rows.append({
            **raw,
            "symbol": f"HK.{code}",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "stock_name": str(raw.get("name") or f"HK.{code}"),
            "pool_score": score,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
        previous_score = score
    if len(rows) != 100 or len({row["symbol"] for row in rows}) != 100:
        raise ValueError("shared HK 0.2 Top100 count mismatch")
    artifact = _artifact(
        trade_date=trade_date,
        pool_id="hkconnect_d1_top100",
        display_name="港股通 0.2 D-1 Top100",
        market="HK",
        status="STRICT_0_2_READY",
        producer_id="v3_shared_hk_0_2_consumer_v1",
        source_role="SHARED_VERIFIED_HK_0_2",
        source_path=str(verification["artifact_relative"]),
        source_sha256=str(verification["artifact_sha256"]),
        rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NOT_BUY_GATE"],
    )
    artifact["source_run_id"] = str(verification["run_id"])
    artifact["source_row_count"] = int(verification["row_count"])
    return artifact


def build_upstream_csv_pool(
    path: Path, trade_date: str, *, pool_id: str, display_name: str, market: str,
    status: str, producer_id: str,
) -> dict[str, Any]:
    if pool_id == "hkconnect_d1_top100" or status == "STRICT_0_2_READY":
        raise ValueError(
            "strict HK 0.2 requires its standard manifest, frozen model proof, and D-1 freshness proof"
        )
    path = Path(path)
    if market == "A":
        rows = _normalize_a_csv_rows(path, pool_id, trade_date)
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            raw_rows = list(csv.DictReader(source))
        rows = []
        for index, raw in enumerate(raw_rows, start=1):
            code = str(raw.get("code_norm") or raw.get("code") or "").upper()
            match = re.search(r"(\d{5})", code)
            if not match:
                continue
            symbol = f"HK.{match.group(1)}"
            rows.append({
                **raw, "symbol": symbol, "market": "HK", "pool_id": pool_id,
                "pool_rank": _row_number(raw.get("rank"), index),
                "stock_name": str(raw.get("name") or symbol),
                "pool_score": _row_float(raw.get("score_prob_active") or raw.get("hybrid_score")),
                "recommendation_status": "WATCH_ONLY", "target_date": trade_date,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            })
    actual_status = status if rows else ("MISSING" if pool_id == "a_d1_fupan_watchlist_pool" else "CANNOT_CONFIRM")
    return _artifact(
        trade_date=trade_date, pool_id=pool_id, display_name=display_name, market=market,
        status=actual_status, producer_id=producer_id, source_role="UPSTREAM_PRODUCER_ARTIFACT",
        source_path=str(path), source_sha256=_sha256(path), rows=rows,
        cannot_confirm=[] if rows else [f"{pool_id.upper()}_NO_ROWS"],
    )


def build_hkconnect_strict_0_2_pool(
    pool_path: Path,
    standard_manifest_path: Path,
    model_manifest_path: Path,
    model_bundle_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    """Verify the frozen V3 0.2 contract before projecting its Top100.

    A CSV is never sufficient evidence for ``STRICT_0_2_READY``. The source
    must carry the standard result manifest, the frozen model manifest and the
    model bundle whose SHA is pinned by the V3 oracle.
    """
    paths = tuple(
        Path(path)
        for path in (
            pool_path,
            standard_manifest_path,
            model_manifest_path,
            model_bundle_path,
        )
    )
    if any(not path.is_file() for path in paths):
        raise ValueError("strict HK 0.2 evidence file missing")
    pool_path, standard_manifest_path, model_manifest_path, model_bundle_path = paths
    standard = json.loads(standard_manifest_path.read_text(encoding="utf-8-sig"))
    model = json.loads(model_manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(standard, Mapping) or not isinstance(model, Mapping):
        raise ValueError("strict HK 0.2 manifest is invalid")
    if (
        standard.get("schema_version") != "hkconnect_0_2_d1_top100_standard_manifest.v1"
        or standard.get("status") != "STRICT_0_2_READY"
        or standard.get("strict_exact_0_2_ready") is not True
        or standard.get("source") != "tdx_vipdoc_71_day"
    ):
        raise ValueError("strict HK 0.2 requires the canonical TDX VIPDOC source")
    if (
        str(standard.get("target_date") or "") != trade_date
        or str(standard.get("signal_date") or "") != signal_date
    ):
        raise ValueError("strict HK 0.2 date contract mismatch")
    if (
        standard.get("d1_freshness_status") != "PASS"
        or standard.get("d1_freshness_ok") is not True
        or standard.get("research_only") is not True
        or standard.get("production_allowed") is not False
        or standard.get("buy_gate_changed") is not False
        or standard.get("orders_sent") is not False
        or str(standard.get("primary_strategy") or standard.get("strategy") or "") != "prob_active"
    ):
        raise ValueError("strict HK 0.2 standard manifest boundary mismatch")
    feature_columns = model.get("feature_columns")
    if (
        model.get("schema_version") != "hkconnect_d1_model_bundle.v1"
        or model.get("primary_strategy") != "prob_active"
        or model.get("research_only") is not True
        or model.get("production_allowed") is not False
        or not isinstance(feature_columns, list)
        or model.get("feature_count") != len(feature_columns)
        or str(model.get("trained_through") or "") > signal_date
    ):
        raise ValueError("strict HK 0.2 frozen model manifest mismatch")
    bundle_sha = _sha256(model_bundle_path)
    if (
        bundle_sha != HK_0_2_FROZEN_MODEL_SHA256
        or str(model.get("bundle_sha256") or "") != bundle_sha
        or str(model.get("bundle_file") or "") != model_bundle_path.name
    ):
        raise ValueError("strict HK 0.2 frozen model SHA mismatch")
    leakage_prefixes = ("target_", "label_", "future_")
    if any(str(field).lower().startswith(leakage_prefixes) for field in feature_columns):
        raise ValueError("strict HK 0.2 model feature leakage")

    with pool_path.open("r", encoding="utf-8-sig", newline="") as source:
        raw_rows = list(csv.DictReader(source))
    expected_count = int(standard.get("row_count") or standard.get("pool_size") or 0)
    if expected_count != 100 or len(raw_rows) != 100:
        raise ValueError("strict HK 0.2 Top100 row count mismatch")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous_score: float | None = None
    for index, raw in enumerate(raw_rows, start=1):
        code = str(raw.get("code_norm") or raw.get("code") or "").strip().upper().removeprefix("HK.")
        if not re.fullmatch(r"\d{5}", code) or code in seen:
            raise ValueError("strict HK 0.2 code identity mismatch")
        rank = _row_number(raw.get("rank"), index)
        score = _row_float(raw.get("score_prob_active"))
        if rank != index or (previous_score is not None and score > previous_score):
            raise ValueError("strict HK 0.2 rank order mismatch")
        row_signal = str(raw.get("signal_date") or signal_date)
        row_target = str(raw.get("target_date") or trade_date)
        if row_signal != signal_date or row_target != trade_date:
            raise ValueError("strict HK 0.2 row date mismatch")
        seen.add(code)
        previous_score = score
        rows.append({
            **raw,
            "symbol": f"HK.{code}",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "stock_name": str(raw.get("name") or f"HK.{code}"),
            "pool_score": score,
            "signal_date": signal_date,
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    source_sha = hashlib.sha256(
        "".join(_sha256(path) for path in paths).encode("ascii")
    ).hexdigest()
    return _artifact(
        trade_date=trade_date,
        pool_id="hkconnect_d1_top100",
        display_name="港股通 0.2 D-1 Top100",
        market="HK",
        status="STRICT_0_2_READY",
        producer_id="v3_hkconnect_0_2_verified_v1",
        source_role="VERIFIED_HK_0_2_STANDARD",
        source_path="|".join(str(path) for path in paths),
        source_sha256=source_sha,
        rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NOT_BUY_GATE"],
    )


def _manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid upstream manifest: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid upstream manifest: {path}")
    return dict(payload)


def _combined_sha256(paths: Iterable[Path]) -> str:
    return hashlib.sha256(
        "".join(_sha256(Path(path)) for path in paths).encode("ascii")
    ).hexdigest()


def build_fupan_watchlist_pool(
    pool_path: Path,
    manifest_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    manifest = _manifest(manifest_path)
    if not str(manifest.get("status") or "").startswith("FUPAN_WATCHLIST_POOL_READY"):
        raise ValueError("invalid D-1 fupan pool status")
    if manifest.get("fupan_pool_rule") != "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW":
        raise ValueError("invalid D-1 fupan pool rule")
    if manifest.get("target_date") != trade_date or manifest.get("signal_date") != signal_date:
        raise ValueError("D-1 fupan pool date mismatch")
    if not isinstance(manifest.get("source_paths"), list) or not manifest["source_paths"]:
        raise ValueError("D-1 fupan source evidence is missing")
    artifact = build_upstream_csv_pool(
        pool_path,
        trade_date,
        pool_id="a_d1_fupan_watchlist_pool",
        display_name="A股 D-1 复盘继续观察池",
        market="A",
        status=str(manifest["status"]),
        producer_id="v3_fupan_watchlist_contract_v1",
    )
    if manifest.get("row_count") != len(artifact["rows"]):
        raise ValueError("D-1 fupan manifest row-count mismatch")
    if any(str(row.get("signal_date") or "") != signal_date for row in artifact["rows"]):
        raise ValueError("D-1 fupan row signal-date mismatch")
    artifact.update(
        source_role="VERIFIED_D1_FUPAN_REVIEW",
        source_path=f"{manifest_path}|{pool_path}",
        source_sha256=_combined_sha256((manifest_path, pool_path)),
        cannot_confirm=[str(item) for item in manifest.get("cannot_confirm") or []],
    )
    return artifact


def build_stage7_review_pool(
    pool_path: Path,
    manifest_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    manifest = _manifest(manifest_path)
    if not str(manifest.get("status") or "").startswith("STAGE7_TAIL_POOL_READY"):
        raise ValueError("invalid D-1 Stage7 pool status")
    if manifest.get("target_date") != trade_date or manifest.get("signal_date") != signal_date:
        raise ValueError("D-1 Stage7 pool date mismatch")
    if manifest.get("source_role") != "real_d1_stage7_tail_replay":
        raise ValueError("D-1 Stage7 strict pool requires real tail replay")
    upstream = manifest.get("upstream_manifest")
    if not isinstance(upstream, Mapping):
        raise ValueError("D-1 Stage7 upstream manifest is missing")
    if upstream.get("trade_date") != signal_date or upstream.get("stage_id") != "STAGE_1445_1500":
        raise ValueError("D-1 Stage7 upstream identity mismatch")
    if any(upstream.get(key) is not False for key in (
        "production_allowed", "buy_gate_updated", "orders_sent"
    )):
        raise ValueError("D-1 Stage7 upstream safety contract mismatch")
    artifact = build_upstream_csv_pool(
        pool_path,
        trade_date,
        pool_id="a_d1_stage7_fenshi_review_pool",
        display_name="A股 D-1 Stage7/分时复盘池",
        market="A",
        status=str(manifest["status"]),
        producer_id="v3_stage7_tail_replay_contract_v1",
    )
    if manifest.get("row_count") != len(artifact["rows"]):
        raise ValueError("D-1 Stage7 manifest row-count mismatch")
    if any(str(row.get("signal_date") or "") != signal_date for row in artifact["rows"]):
        raise ValueError("D-1 Stage7 row signal-date mismatch")
    artifact.update(
        source_role="VERIFIED_D1_STAGE7_REPLAY",
        source_path=f"{manifest_path}|{pool_path}",
        source_sha256=_combined_sha256((manifest_path, pool_path)),
        cannot_confirm=[str(item) for item in manifest.get("cannot_confirm") or []],
    )
    return artifact


def _normalize_name(value: Any) -> str:
    text = re.sub(r"[\(（]\s*代码待核\s*[\)）]", "", str(value or "").strip())
    return re.sub(r"\s+", "", text).strip("：:，,。；;#【】[]“”\"' ")


def _selector_name_map(selector_path: Path) -> dict[str, str]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(selector_path)
    latest = _parquet_trade_dates(parquet)[-1]
    table = pq.read_table(selector_path, columns=["ts_code", "name"], filters=[("trade_date", "==", latest)])
    grouped: dict[str, set[str]] = defaultdict(set)
    for raw_code, raw_name in zip(table.column("ts_code").to_pylist(), table.column("name").to_pylist()):
        symbol = _a_symbol(raw_code)
        name = _normalize_name(raw_name)
        if symbol and name:
            grouped[name].add(symbol)
    return {name: next(iter(symbols)) for name, symbols in grouped.items() if len(symbols) == 1}


def _research_window(trade_date: str) -> tuple[datetime, datetime]:
    from contracts.trading_calendar import load_market_calendar, previous_session
    from infrastructure.market_time import as_shanghai

    target = as_shanghai(datetime.strptime(trade_date, "%Y%m%d"))
    prior = as_shanghai(
        datetime.strptime(
            previous_session(
                load_market_calendar(),
                trade_date,
                market="a_share",
            ),
            "%Y%m%d",
        )
    )
    if (target.date() - prior.date()).days > 1:
        return prior.replace(hour=0), target.replace(hour=9)
    return prior.replace(hour=8, minute=30), target.replace(hour=8, minute=30)


def _parse_dt(value: Any) -> datetime | None:
    from infrastructure.market_time import parse_shanghai

    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_shanghai(text)
    except ValueError:
        return None


def _target_symbols(item: Mapping[str, Any], names: Mapping[str, str]) -> Iterable[tuple[str, str]]:
    for field in ("symbols", "stock_focus", "verified_stock_focus"):
        values = item.get(field) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            symbol = _a_symbol(value)
            name = _normalize_name(value)
            if symbol:
                yield symbol, field
            elif name in names:
                yield names[name], f"{field}_exact_name"


def build_research_preview_pool(preview_path: Path, selector_path: Path, trade_date: str) -> dict[str, Any]:
    preview_path, selector_path = Path(preview_path), Path(selector_path)
    payload = json.loads(preview_path.read_text(encoding="utf-8-sig"))
    names = _selector_name_map(selector_path)
    start, end = _research_window(trade_date)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for section in _RESEARCH_SECTIONS:
        for item in payload.get(section) or []:
            if not isinstance(item, Mapping):
                continue
            targets = list(_target_symbols(item, names))
            source_name, title = str(item.get("source_name") or ""), str(item.get("title") or "")
            is_research = bool(targets) and (
                (str(item.get("source_type") or "").upper() == "ZSXQ" and any(token in source_name for token in _RESEARCH_SOURCE_TOKENS))
                or any(token in title for token in _RESEARCH_TITLE_TOKENS)
            )
            source_dt = _parse_dt(item.get("published_at")) or _parse_dt(item.get("fetched_at"))
            if not is_research or source_dt is None or not (start <= source_dt < end):
                continue
            source_id = str(item.get("id") or item.get("topic_id") or title)
            for symbol, field in targets:
                grouped[symbol].append({"source_id": source_id, "field": field, "source_dt": source_dt.isoformat(), "title": title})
    rows: list[dict[str, Any]] = []
    for symbol, items in grouped.items():
        items.sort(key=lambda item: (item["source_dt"], item["source_id"]))
        first = items[0]
        rows.append({
            "symbol": symbol, "code": symbol.removeprefix("A."), "market": "A",
            "pool_id": "a_share_research_recommendation_pool", "stock_name": symbol,
            "pool_score": len({item["source_id"] for item in items}), "signal_date": "",
            "target_date": trade_date, "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE", "first_source_dt": first["source_dt"],
            "research_title": first["title"], "entity_resolution_source": first["field"],
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        })
    rows.sort(key=lambda row: (-int(row["pool_score"]), row["first_source_dt"], row["code"]))
    for index, row in enumerate(rows, start=1):
        row["pool_rank"] = index
    combined_sha = hashlib.sha256((_sha256(preview_path) + _sha256(selector_path)).encode("ascii")).hexdigest()
    return _artifact(
        trade_date=trade_date, pool_id="a_share_research_recommendation_pool",
        display_name="A股研报推荐股票池", market="A",
        status="RESEARCH_RECOMMENDATION_POOL_READY" if rows else "CANNOT_CONFIRM",
        producer_id="v3_research_preview_v1", source_role="RAW_SOURCE",
        source_path=f"{preview_path}|{selector_path}", source_sha256=combined_sha, rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NO_BUY_GATE"],
    )


def build_hourly_research_pool(
    data_root: Path,
    trade_date: str,
    *,
    store: Any | None = None,
) -> dict[str, Any]:
    """Build the V3 research pool from verified V3.5 hourly archives.

    The time window is the frozen V3 window: D-1 08:30 to D 08:30 on a
    normal day and Friday 00:00 to Monday 09:00 for a Monday target.  Hourly
    archives are cumulative, so article identity is deduplicated before the
    per-stock recommendation count is calculated.
    """
    if store is None:
        from infrastructure.research_store import HourlyResearchStore

        store = HourlyResearchStore(Path(data_root))
    start, end = _research_window(trade_date)
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    payloads: list[tuple[str, str, Mapping[str, Any]]] = []
    while cursor.date() <= end.date():
        archive_date = cursor.strftime("%Y%m%d")
        for slot in store.list_slots(archive_date, mode="LIVE"):
            payload = store.read_exact(archive_date, slot, mode="LIVE")
            if payload is None:
                raise ValueError("hourly research manifest points to missing payload")
            if str(payload.get("archive_date") or "") != archive_date:
                raise ValueError("hourly research archive-date mismatch")
            payloads.append((archive_date, slot, payload))
        cursor += timedelta(days=1)
    if not payloads:
        raise FileNotFoundError(f"hourly research window has no verified slots: {trade_date}")

    articles: dict[str, dict[str, Any]] = {}
    cannot_confirm: set[str] = {"RESEARCH_ONLY_NO_BUY_GATE"}
    for _archive_date, _slot, payload in payloads:
        for reason in payload.get("cannot_confirm") or []:
            if str(reason).strip():
                cannot_confirm.add(str(reason).strip())
        source_rows = payload.get("articles")
        if not isinstance(source_rows, list):
            raise ValueError("hourly research articles are invalid")
        for raw in source_rows:
            if not isinstance(raw, Mapping):
                raise ValueError("hourly research article is invalid")
            published_at = _parse_dt(raw.get("published_at"))
            if published_at is None or not (start <= published_at < end):
                continue
            symbol = _a_symbol(raw.get("stock_code"))
            if not symbol:
                continue
            article_id = str(raw.get("article_id") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9._:-]+", article_id):
                raise ValueError("hourly research article identity is invalid")
            normalized = dict(raw)
            normalized["symbol"] = symbol
            normalized["published_at_normalized"] = published_at.isoformat()
            articles.setdefault(article_id, normalized)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article_id, article in articles.items():
        grouped[str(article["symbol"])].append({**article, "article_id": article_id})
    rows: list[dict[str, Any]] = []
    for symbol, stock_articles in grouped.items():
        stock_articles.sort(
            key=lambda item: (
                str(item["published_at_normalized"]),
                str(item["article_id"]),
            )
        )
        first = stock_articles[0]
        rows.append({
            "symbol": symbol,
            "code": symbol.removeprefix("A."),
            "market": "A",
            "pool_id": "a_share_research_recommendation_pool",
            "stock_name": str(first.get("stock_name") or symbol),
            "pool_score": len(stock_articles),
            "article_count": len(stock_articles),
            "signal_date": start.strftime("%Y%m%d"),
            "target_date": trade_date,
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "first_source_dt": str(first["published_at_normalized"]),
            "research_title": str(first.get("source_title") or ""),
            "entity_resolution_source": "hourly_research_stock_code",
            "source_article_ids": [
                str(item["article_id"]) for item in stock_articles
            ],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    rows.sort(
        key=lambda row: (
            -int(row["pool_score"]),
            str(row["first_source_dt"]),
            str(row["code"]),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["pool_rank"] = index

    source_identity = [
        {
            "archive_date": archive_date,
            "slot": slot,
            "payload": payload,
        }
        for archive_date, slot, payload in payloads
    ]
    source_sha256 = hashlib.sha256(
        json.dumps(
            source_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    source_paths = "|".join(
        f"research/hourly/live/{archive_date}/{slot}.json"
        for archive_date, slot, _payload in payloads
    )
    return _artifact(
        trade_date=trade_date,
        pool_id="a_share_research_recommendation_pool",
        display_name="A股研报推荐股票池",
        market="A",
        status=(
            "RESEARCH_RECOMMENDATION_POOL_READY"
            if rows
            else "CANNOT_CONFIRM"
        ),
        producer_id="v3_5_hourly_research_window_v1",
        source_role="VERIFIED_HOURLY_RESEARCH",
        source_path=source_paths,
        source_sha256=source_sha256,
        rows=rows,
        cannot_confirm=sorted(cannot_confirm),
    )


def build_expected_missing_pool(trade_date: str, *, pool_id: str, display_name: str, market: str, reason: str) -> dict[str, Any]:
    return _artifact(
        trade_date=trade_date, pool_id=pool_id, display_name=display_name, market=market,
        status="CANNOT_CONFIRM", producer_id="graph_expected_missing_v1", source_role="EXPECTED_MISSING",
        source_path="", source_sha256=hashlib.sha256(b"").hexdigest(), rows=[], cannot_confirm=[reason],
    )


def build_baimao_pool(path: Path | None, trade_date: str) -> dict[str, Any]:
    if path is None or not Path(path).is_file():
        return build_expected_missing_pool(
            trade_date, pool_id="a_share_baimao_research_map",
            display_name="白毛卡点研究池", market="A", reason="BAIMAO_RESEARCH_MAP_NOT_FOUND",
        )
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    reason = ""
    if not isinstance(payload, Mapping):
        reason = "BAIMAO_RESEARCH_MAP_INVALID_JSON"
    elif str(payload.get("trade_date") or "") != trade_date:
        reason = "TRADE_DATE_MISMATCH"
    elif (
        not re.fullmatch(r"\d{8}", str(payload.get("research_date") or ""))
        or not str(payload.get("event_id") or "").startswith(
            f"research:{payload.get('research_date')}:"
        )
    ):
        reason = "RESEARCH_EVENT_BINDING_INVALID"
    elif payload.get("opens_buy_gate") is not False or payload.get("write_policy") != "RESEARCH_ONLY":
        reason = "BAIMAO_RESEARCH_ONLY_CONTRACT_INVALID"
    elif not isinstance(payload.get("candidates"), list):
        reason = "BAIMAO_CANDIDATES_INVALID"
    rows: list[dict[str, Any]] = []
    if not reason:
        for index, candidate in enumerate(payload["candidates"], start=1):
            if not isinstance(candidate, Mapping) or candidate.get("state") != "RESEARCH_MAP":
                continue
            symbol = _a_symbol(candidate.get("code") or candidate.get("ts_code"))
            if not symbol:
                continue
            rows.append({
                **dict(candidate), "symbol": symbol, "market": "A",
                "pool_id": "a_share_baimao_research_map",
                "pool_rank": _row_number(candidate.get("rank"), index),
                "stock_name": str(candidate.get("name") or symbol),
                "pool_score": _row_float(candidate.get("score")),
                "target_date": trade_date, "recommendation_status": "RESEARCH_ONLY",
                "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                "formal_pool_write": False, "buy_gate_write": False,
            })
    return _artifact(
        trade_date=trade_date, pool_id="a_share_baimao_research_map",
        display_name="白毛卡点研究池", market="A",
        status="BAIMAO_RESEARCH_MAP_READY" if rows else "CANNOT_CONFIRM",
        producer_id="v3_baimao_research_map_v1", source_role="RAW_SOURCE",
        source_path=str(path), source_sha256=_sha256(path), rows=rows,
        cannot_confirm=[reason or "RESEARCH_ONLY_NO_BUY_GATE"],
    )


def build_wechat_pool(manifest_path: Path, rows_path: Path, trade_date: str) -> dict[str, Any]:
    manifest_path, rows_path = Path(manifest_path), Path(rows_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, Mapping) or manifest.get("status") != "WECHAT_V3_PRESELECT_READY":
        raise ValueError("invalid WeChat upstream manifest")
    if manifest.get("effective_trade_date") != trade_date:
        raise ValueError("WeChat upstream effective trade-date mismatch")
    target_validation = manifest.get("target_validation")
    if not isinstance(target_validation, Mapping) or target_validation.get("status") != "TARGET_DATE_CHECK_PASS":
        raise ValueError("WeChat upstream target-date evidence is missing")
    boundary = manifest.get("boundary")
    if not isinstance(boundary, Mapping) or boundary.get("formal_pool_write") is not False or boundary.get("buy_gate_write") is not False:
        raise ValueError("WeChat upstream research-only boundary mismatch")
    if manifest.get("score_scope") != "wechat_pool_ts_codes_only":
        raise ValueError("WeChat upstream score scope mismatch")
    artifact = build_upstream_csv_pool(
        rows_path, trade_date, pool_id="wechat_public_account_v3_preselect",
        display_name="公众号股票池", market="A", status="WECHAT_V3_PRESELECT_READY",
        producer_id="v3_wechat_preselect_upstream_v1",
    )
    expected = manifest.get("counts", {}).get("v3_matched_codes")
    if isinstance(expected, int) and len(artifact["rows"]) != expected:
        raise ValueError("WeChat upstream manifest row-count mismatch")
    signal_date = str(manifest.get("signal_date") or manifest.get("article_publish_date") or "")
    article_publish_date = str(manifest.get("article_publish_date") or signal_date)
    if not re.fullmatch(r"\d{8}", signal_date) or not re.fullmatch(r"\d{8}", article_publish_date):
        raise ValueError("WeChat upstream article signal-date evidence is missing")
    for index, row in enumerate(artifact["rows"], start=1):
        row.update(
            pool_rank=_row_number(row.get("wechat_v3_preselect_rank"), index),
            pool_score=_row_float(row.get("candidate_score")),
            recommendation_status="RESEARCH_ONLY",
            trade_status_contract="RESEARCH_ONLY_NO_BUY_GATE",
            signal_date=signal_date,
            effective_trade_date=trade_date,
            article_publish_date=article_publish_date,
            article_url=str(row.get("wechat_source_ref") or manifest.get("article_url") or ""),
        )
    artifact["source_path"] = f"{manifest_path}|{rows_path}"
    artifact["source_sha256"] = hashlib.sha256(
        (_sha256(manifest_path) + _sha256(rows_path)).encode("ascii")
    ).hexdigest()
    artifact["source_role"] = "VERIFIED_WECHAT_RESEARCH"
    artifact["cannot_confirm"] = ["RESEARCH_ONLY_NO_BUY_GATE"]
    return artifact


def materialize_preselection_date(store: PreselectionPoolStore, artifacts: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Materialize already-produced graph-bound pool artifacts independently."""
    results = []
    for artifact in artifacts:
        results.append(store.materialize(artifact))
    return results
