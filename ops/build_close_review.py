"""Build and publish the V3.5-native HK Connect close review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from domains.close_review import _REVIEW_STAGE_IDS, build_native_close_review
from infrastructure.data_store import _sha256
from infrastructure.hkconnect_close_store import (
    CloseSnapshotStore,
    futu_close_capture_time_gap,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from stage_center.consumer import StageSelectionConsumer


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
) -> tuple[dict[str, list[dict[str, Any]] | None], dict[str, dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]] | None] = {}
    evidence: dict[str, dict[str, Any]] = {}
    if stage_selection_root is None:
        return ({stage_id: None for stage_id in _REVIEW_STAGE_IDS}, evidence)
    consumer = StageSelectionConsumer(stage_selection_root)
    for stage_id in _REVIEW_STAGE_IDS:
        try:
            response = consumer.get(
                trade_date,
                stage_id,
                markets=("HK_CONNECT",),
            )
            market = response.get("markets", {}).get("HK_CONNECT")
            market_details = market if isinstance(market, dict) else {}
            status = str(
                market.get("status") or market.get("selection_status") or ""
            ) if isinstance(market, dict) else ""
            response_reasons = list(response.get("cannot_confirm") or ())
            market_reasons = list(market_details.get("cannot_confirm") or ())
            reasons = list(dict.fromkeys(response_reasons + market_reasons))
            evidence[stage_id] = {
                "status": status or "CANNOT_CONFIRM",
                "run_id": response.get("run_id") or market_details.get("run_id"),
                "artifact_id": market_details.get("artifact_id"),
                "selection_mode": market_details.get("selection_mode"),
                "backfill_run_id": market_details.get("backfill_run_id"),
                "backfill_run_ids": list(market_details.get("backfill_run_ids") or ()),
                "source_evidence": list(market_details.get("source_evidence") or ()),
                "cannot_confirm": reasons,
            }
            response_safe = all(
                response.get(flag) is False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
            exact_identity = (
                response.get("trade_date") == trade_date
                and response.get("stage_id") == stage_id
            )
            integrity_gap = "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID" in reasons
            if not exact_identity:
                reasons.append("STAGE_RESPONSE_IDENTITY_MISMATCH")
            if not response_safe:
                reasons.append("STAGE_RESPONSE_SAFETY_FLAGS_INVALID")
            if evidence[stage_id]["cannot_confirm"] != reasons:
                evidence[stage_id]["cannot_confirm"] = list(dict.fromkeys(reasons))
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
            evidence[stage_id] = {
                "status": "CANNOT_CONFIRM",
                "cannot_confirm": ["STAGE_SELECTION_READ_FAILED"],
            }
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
        evidence[stage_id]["row_count"] = len(projected_rows)
    return result, evidence


def build_close_review(
    data_root: Path,
    trade_date: str,
    *,
    stage_selection_root: Path | str | None = None,
) -> dict[str, Any]:
    data_root = Path(data_root)
    snapshot, snapshot_sha = CloseSnapshotStore(data_root).read_snapshot(trade_date)
    capture_gap = futu_close_capture_time_gap(snapshot, trade_date)
    if capture_gap is not None:
        raise ValueError(capture_gap)
    try:
        preselection = PreselectionPoolStore(data_root).read_pool(
            trade_date,
            "hkconnect_d1_top100",
        )
    except FileNotFoundError as error:
        # Only the store's exact missing-artifact sentinel is a model-source
        # gap. Missing manifests/receipts and parse or contract failures must
        # remain visible to the caller instead of looking like an empty pool.
        if error.filename is not None or error.args != ("hkconnect_d1_top100",):
            raise
        preselection = {}
    stage_rows, stage_evidence = _stage_rows_with_evidence(
        stage_selection_root,
        trade_date,
    )
    review = build_native_close_review(
        trade_date,
        close_rows=snapshot["rows"],
        model_rows=_model_rows(preselection, trade_date),
        stage_rows=stage_rows,
        close_source_sha256=snapshot_sha,
        stage_evidence=stage_evidence,
        close_source_evidence={
            "source_mode": snapshot.get("source_mode"),
            "source_input_sha256": snapshot.get("source_input_sha256"),
            "source_capture": snapshot.get("source_capture"),
        },
        model_source_evidence={
            "pool_id": preselection.get("pool_id", "hkconnect_d1_top100")
            if isinstance(preselection, dict)
            else "hkconnect_d1_top100",
            "trade_date": preselection.get("trade_date", trade_date)
            if isinstance(preselection, dict)
            else trade_date,
            "source_role": preselection.get("source_role")
            if isinstance(preselection, dict)
            else None,
            "source_sha256": preselection.get("source_sha256")
            if isinstance(preselection, dict)
            else None,
            "source_manifest_sha256": preselection.get("source_manifest_sha256")
            if isinstance(preselection, dict)
            else None,
            "source_receipt_sha256": preselection.get("source_receipt_sha256")
            if isinstance(preselection, dict)
            else None,
        },
    )
    # Verified local pool storage does not prove upstream source/PIT availability.
    if isinstance(preselection, dict) and (
        "historical_provenance" in preselection
        or not all(
            preselection.get(field)
            for field in ("source_manifest_sha256", "source_receipt_sha256")
        )
    ):
        reason = "HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM"
        if reason not in review["cannot_confirm"]:
            review["cannot_confirm"].append(reason)
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
    args = parser.parse_args()
    print(json.dumps(
        build_close_review(
            args.data_root,
            args.date,
            stage_selection_root=args.stage_selection_root,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
