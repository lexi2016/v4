"""Build and publish the V3.5-native HK Connect close review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from domains.close_review import _REVIEW_STAGE_IDS, build_native_close_review
from infrastructure.data_store import _sha256
from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from stage_center.consumer import StageSelectionConsumer
from stage_center.research_read_binding import ApprovedResearchReadBinding


_HK_MODEL_SOURCE_ROLES = frozenset(
    {"SHARED_VERIFIED_HK_0_2", "VERIFIED_HK_0_2_STANDARD"}
)


def _model_rows(preselection: dict[str, Any], trade_date: str) -> list[dict[str, Any]]:
    if not isinstance(preselection, dict):
        return []
    if (
        preselection.get("pool_id") != "hkconnect_d1_top100"
        or preselection.get("trade_date") != trade_date
        or preselection.get("status") != "STRICT_0_2_READY"
        or preselection.get("source_role") not in _HK_MODEL_SOURCE_ROLES
        or any(preselection.get(flag) is not False for flag in (
            "production_allowed", "buy_gate_updated", "orders_sent",
        ))
    ):
        return []
    source_rows = preselection.get("rows")
    if not isinstance(source_rows, list) or len(source_rows) != 100:
        return []
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in source_rows:
        if not isinstance(row, dict):
            return []
        code = str(row.get("symbol") or row.get("code") or "").strip().upper()
        if (
            str(row.get("market") or "").upper() not in {"HK", "HKCONNECT"}
            or str(row.get("target_date") or row.get("trade_date") or "") != trade_date
            or not code
            or code in seen_codes
        ):
            return []
        seen_codes.add(code)
        rows.append(row)
    return rows if len(seen_codes) == 100 else []


def _stage_rows(
    stage_selection_root: Path | str | None,
    trade_date: str,
) -> dict[str, list[dict[str, Any]] | None]:
    return _stage_rows_with_evidence(stage_selection_root, trade_date)[0]


def _stage_rows_with_evidence(
    stage_selection_root: Path | str | None,
    trade_date: str,
    *,
    allow_backfill: bool = False,
) -> tuple[dict[str, list[dict[str, Any]] | None], dict[str, dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]] | None] = {}
    evidence: dict[str, dict[str, Any]] = {}
    if stage_selection_root is None:
        return ({stage_id: None for stage_id in _REVIEW_STAGE_IDS}, evidence)
    consumer = StageSelectionConsumer(stage_selection_root)
    app_root = Path(__file__).resolve().parents[1]
    binding_path = app_root / "stage_center" / "approved_research_read.json"
    research_reader_path = app_root / "stage_center" / "research_read_binding.py"
    approved_reader: ApprovedResearchReadBinding | None = None
    if allow_backfill and trade_date == "20261009" and binding_path.is_file():
        approved_reader = ApprovedResearchReadBinding(
            binding_path=binding_path,
            history_root=stage_selection_root,
            api_root=app_root,
            expected_reader_sha256=hashlib.sha256(research_reader_path.read_bytes()).hexdigest(),
            expected_binding_sha256=hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        )
    for stage_id in _REVIEW_STAGE_IDS:
        try:
            approved_stage = (
                allow_backfill
                and trade_date == "20261009"
                and stage_id == "STAGE_0930_0935"
                and approved_reader is not None
            )
            if approved_stage:
                response = approved_reader.get(
                    trade_date,
                    stage_id,
                    markets=("HK_CONNECT",),
                )
                if response is None:
                    result[stage_id] = None
                    evidence[stage_id] = {
                        "selection_mode": "BACKFILL",
                        "cannot_confirm": ["APPROVED_RESEARCH_BINDING_UNAVAILABLE"],
                    }
                    continue
            else:
                if allow_backfill:
                    response = consumer.get(
                        trade_date,
                        stage_id,
                        markets=("HK_CONNECT",),
                        allow_backfill=True,
                    )
                else:
                    response = consumer.get(
                        trade_date,
                        stage_id,
                        markets=("HK_CONNECT",),
                    )
            market = response.get("markets", {}).get("HK_CONNECT")
            status = str(
                market.get("status") or market.get("selection_status") or ""
            ) if isinstance(market, dict) else ""
            market_reasons = list(market.get("cannot_confirm") or ()) if isinstance(market, dict) else []
            response_reasons = list(response.get("cannot_confirm") or ()) if isinstance(response, dict) else []
            evidence[stage_id] = {
                "status": status,
                "selection_mode": (
                    "BACKFILL" if approved_stage else
                    market.get("selection_mode") if isinstance(market, dict) else None
                ),
                "backfill_run_id": market.get("backfill_run_id") if isinstance(market, dict) else None,
                "backfill_run_ids": list(market.get("backfill_run_ids") or ()) if isinstance(market, dict) else [],
                "runner_receipt_status": market.get("runner_receipt_status") if isinstance(market, dict) else None,
                "research_read_binding": response.get("research_read_binding") if approved_stage else None,
                "cannot_confirm": list(dict.fromkeys(response_reasons + market_reasons)),
                "source_evidence": list(market.get("source_evidence") or ()) if isinstance(market, dict) else [],
            }
            response_safe = all(
                response.get(flag) is False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
            exact_identity = (
                response.get("trade_date") == trade_date
                and response.get("stage_id") == stage_id
            )
            integrity_gap = (
                list(response.get("cannot_confirm") or ())
                == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
                or list(market.get("cannot_confirm") or ())
                == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
                if isinstance(market, dict)
                else True
            )
            rows = (
                market.get("rows")
                if isinstance(market, dict)
                and status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}
                and response_safe
                and exact_identity
                and not integrity_gap
                else None
            )
        except (OSError, TypeError, ValueError):
            rows = None
            evidence.setdefault(stage_id, {"cannot_confirm": ["STAGE_SELECTION_READ_FAILED"]})
        if not isinstance(rows, list):
            result[stage_id] = None
            continue
        projected_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            market = str(row.get("market") or "HK").upper()
            if market not in {"HK", "HKCONNECT"}:
                continue
            projected = dict(row)
            projected.setdefault("market", "HK")
            projected_rows.append(projected)
        result[stage_id] = projected_rows
    return result, evidence


def _observed_model_candidate(
    rows_path: Path | str | None,
    receipt_path: Path | str | None,
    trade_date: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if rows_path is None and receipt_path is None:
        return [], None
    if rows_path is None or receipt_path is None:
        raise ValueError("both observed model rows and candidate receipt are required")
    rows_file, receipt_file = Path(rows_path), Path(receipt_path)
    rows_bytes, receipt_bytes = rows_file.read_bytes(), receipt_file.read_bytes()
    rows = json.loads(rows_bytes)
    receipt = json.loads(receipt_bytes)
    rows_sha = hashlib.sha256(rows_bytes).hexdigest()
    if (
        not isinstance(rows, list)
        or not isinstance(receipt, dict)
        or receipt.get("schema_version") != "v4.hk_0_2_score_candidate_receipt.v1"
        or receipt.get("status") != "CANDIDATE_ONLY_CANNOT_CONFIRM"
        or receipt.get("producer_function") != "upstreams/v3_shared_data/shared_data/hk_0_2.py::score_frozen_hk_0_2"
        or receipt.get("target_date") != trade_date
        or receipt.get("row_output_sha256") != rows_sha
        or receipt.get("score_rows") != 100
        or receipt.get("unique_score_codes") != 100
        or receipt.get("RESEARCH_ONLY") is not True
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or len(rows) != 100
    ):
        raise ValueError("observed model candidate receipt or row identity is invalid")
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError("observed model candidate contains a non-object row")
        code = str(row.get("code") or row.get("code_norm") or "").strip().upper()
        if (
            not code
            or code in seen
            or row.get("target_date") != trade_date
            or row.get("signal_date") != receipt.get("signal_date")
            or row.get("selected_strategy") != "prob_active"
            or row.get("rank") != index
        ):
            raise ValueError("observed model candidate row identity is invalid")
        seen.add(code)
        observed.append(row)
    cannot_confirm = receipt.get("cannot_confirm")
    if not isinstance(cannot_confirm, list) or not cannot_confirm:
        raise ValueError("observed model candidate must retain its uncertainty reasons")
    return observed, {
        "source_path": str(rows_file.resolve()),
        "source_sha256": rows_sha,
        "receipt_path": str(receipt_file.resolve()),
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "producer_function": receipt["producer_function"],
        "target_date": trade_date,
        "signal_date": receipt.get("signal_date"),
        "score_rows": receipt["score_rows"],
        "unique_score_codes": receipt["unique_score_codes"],
        "candidate_status": receipt.get("status"),
        "cannot_confirm": [str(item) for item in cannot_confirm],
    }


def build_close_review(
    data_root: Path,
    trade_date: str,
    *,
    stage_selection_root: Path | str | None = None,
    allow_backfill: bool = False,
    observed_model_rows_path: Path | str | None = None,
    observed_model_receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    data_root = Path(data_root)
    snapshot, snapshot_sha = CloseSnapshotStore(data_root).read_snapshot(trade_date)
    try:
        preselection = PreselectionPoolStore(data_root).read_pool(
            trade_date,
            "hkconnect_d1_top100",
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        # The verified pool is exact-date input.  A missing or invalid pool is
        # represented as a model-source gap; never substitute the legacy
        # NativeDataStore payload or another date.
        preselection = {}
    observed_model_rows, observed_model_evidence = _observed_model_candidate(
        observed_model_rows_path,
        observed_model_receipt_path,
        trade_date,
    )
    stage_rows, stage_evidence = _stage_rows_with_evidence(
        stage_selection_root,
        trade_date,
        allow_backfill=allow_backfill,
    )
    review = build_native_close_review(
        trade_date,
        close_rows=snapshot["rows"],
        model_rows=_model_rows(preselection, trade_date),
        stage_rows=stage_rows,
        stage_evidence=stage_evidence,
        observed_model_rows=observed_model_rows,
        observed_model_evidence=observed_model_evidence,
        close_source_sha256=snapshot_sha,
    )
    review_store = ReviewStore(data_root)
    current = review_store.read_reference(trade_date)
    expected_sha = _sha256(current) if current is not None else None
    publication = review_store.publish_native(review, expected_sha256=expected_sha)
    return {"review": review, "publication": publication}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the V3.5-native HK Connect close review")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument("--allow-backfill", action="store_true")
    parser.add_argument("--observed-model-rows", type=Path)
    parser.add_argument("--observed-model-receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        build_close_review(
            args.data_root,
            args.date,
            stage_selection_root=args.stage_selection_root,
            allow_backfill=args.allow_backfill,
            observed_model_rows_path=args.observed_model_rows,
            observed_model_receipt_path=args.observed_model_receipt,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
