"""Build and publish the V3.5-native HK Connect close review."""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
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
from stage_center.consumer import StageSelectionConsumer, _verified_selection_provenance


_HK_MODEL_SOURCE_ROLES = frozenset(
    {"SHARED_VERIFIED_HK_0_2", "VERIFIED_HK_0_2_STANDARD"}
)


def _auction_review_input(evidence: dict[str, Any], rows: list[dict[str, Any]], trade_date: str) -> None:
    """Resolve the legacy Top100 denominator against its existing Top20 receipt."""
    if (evidence.get("status") != "PARTIAL_WITH_ROWS"
            or evidence.get("source_status") != "READY"
            or evidence.get("cannot_confirm")
            or evidence.get("selection_mode") == "BACKFILL"):
        return
    markers = dict(item.split("=", 1) for item in evidence.get("source_evidence", []) if "=" in item)
    if markers.get("selection_mode") == "BACKFILL" or markers.get("due_status") == "HISTORICAL_BACKFILL":
        return
    if markers.get("route") != "hk_connect_0915_0920_auction_second_filter":
        return
    path = markers.get("second_filter_csv")
    if not path:
        return
    from stage_center.runner import _validate_hk_second_filter
    try:
        csv_path, acceptance_path, digest = _validate_hk_second_filter(Path(path), trade_date)
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            source = list(csv.DictReader(stream))
        codes = [str(row.get("code") or row.get("ts_code") or "") for row in source]
        if not (
            digest == markers.get("second_filter_csv_sha256")
            and acceptance.get("required_row_count") == 20
            and acceptance.get("temporal_cutoff_safe") is True
            and len(source) == len(set(codes)) == 20
            and evidence.get("source_rows") == 20
            and evidence.get("requested_rows") == 100
            and len(rows) == 10
            and [row.get("code") for row in rows] == codes[:10]
        ):
            return
    except (OSError, ValueError, TypeError):
        return
    # Only the review's input assessment is corrected; stage history is immutable.
    evidence.update(
        review_evidence_status="READY", input_scope="HK_0920_SECOND_FILTER_TOP20",
        review_expected_rows=20, review_source_rows=20,
        input_count_correction="SECOND_FILTER_TOP20_NOT_D1_TOP100",
        second_filter_csv_sha256=digest,
    )


def _model_rows(
    preselection: dict[str, Any], trade_date: str, *, verified_pool: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(preselection, dict):
        return []
    # READY is the canonical producer's other success spelling.  Admit it only
    # after the store has verified the exact-date pool/manifest/receipt trio.
    canonical_ready = (
        verified_pool is True
        and preselection.get("status") == "READY"
        and preselection.get("schema_version") == "v3_5.preselection_pool.v1"
        and preselection.get("market") == "HK"
        and preselection.get("producer_id") == "v3_shared_hk_0_2_consumer_v1"
        and preselection.get("source_role") == "SHARED_VERIFIED_HK_0_2"
        and preselection.get("target_date") == trade_date
        and preselection.get("stage_selection_eligible") is True
        and preselection.get("source_artifact_sha256") == preselection.get("source_sha256")
        and all(isinstance(preselection.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", preselection[key])
                for key in ("source_sha256", "source_manifest_sha256", "source_receipt_sha256"))
    )
    if (
        preselection.get("pool_id") != "hkconnect_d1_top100"
        or preselection.get("trade_date") != trade_date
        or (preselection.get("status") != "STRICT_0_2_READY" and not canonical_ready)
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
                allow_backfill=True,
            )
            market = response.get("markets", {}).get("HK_CONNECT")
            market_details = market if isinstance(market, dict) else {}
            # Older deployed consumers omit provenance that is present in the
            # verified selection envelope. Reuse that envelope, not a new source.
            if "source_evidence" not in market_details and market_details.get("run_id"):
                envelope = consumer.store.read_verified(trade_date, stage_id, "HK_CONNECT")
                if envelope.get("run_id") != market_details["run_id"]:
                    raise ValueError("stage changed while reading review evidence")
                market_details = {**market_details, "source_evidence": list(envelope.get("source_evidence") or ())}
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
                "selection_manifest_receipt_verified": market_details.get("selection_manifest_receipt_verified"),
                "selection_manifest_sha256": market_details.get("selection_manifest_sha256"),
                "selection_receipt_sha256": market_details.get("selection_receipt_sha256"),
                "selection_artifact_sha256": market_details.get("selection_artifact_sha256"),
                "runner_receipt_verified": market_details.get("runner_receipt_verified"),
                "runner_receipt_sha256": market_details.get("runner_receipt_sha256"),
                "recovery_provenance": market_details.get("recovery_provenance"),
                "source_status": market_details.get("source_status"),
                "source_rows": market_details.get("source_rows"),
                "requested_rows": market_details.get("requested_rows"),
                "missing_symbols": list(market_details.get("missing_symbols") or ()),
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
            if market_details.get("selection_mode") == "BACKFILL":
                # The display consumer can expose unverified/ambiguous wrappers.
                # A review only admits the existing exact, uniquely bound trio.
                backfill_verified = (
                    market_details.get("market") == "HK_CONNECT"
                    and market_details.get("trade_date") == trade_date
                    and market_details.get("stage_id") == stage_id
                    and market_details.get("selection_manifest_receipt_verified") is True
                    and market_details.get("runner_receipt_verified") is True
                    and isinstance(market_details.get("backfill_run_id"), str)
                    and bool(market_details["backfill_run_id"])
                    and market_details.get("backfill_run_ids") == [market_details["backfill_run_id"]]
                    and "BACKFILL_NAMESPACE_CONFLICT" not in reasons
                    and all(isinstance(market_details.get(key), str)
                            and re.fullmatch(r"[0-9a-f]{64}", market_details[key])
                            for key in ("selection_manifest_sha256", "selection_receipt_sha256",
                                        "selection_artifact_sha256", "runner_receipt_sha256"))
                )
                if backfill_verified:
                    # Rebind reported hashes to the immutable run, not merely
                    # well-formed hashes copied from its latest pointer.
                    bound = _verified_selection_provenance(
                        type(consumer.store)(consumer.store.root / "backfill" / market_details["backfill_run_id"]),
                        trade_date=trade_date, stage_id=stage_id, market="HK_CONNECT",
                        run_id=market_details["run_id"],
                    )
                    backfill_verified = all(market_details.get(key) == bound.get(key) for key in (
                        "selection_manifest_sha256", "selection_receipt_sha256", "selection_artifact_sha256",
                    ))
                if not backfill_verified:
                    integrity_gap = True
                    reasons.append("BACKFILL_REVIEW_PROVENANCE_CANNOT_CONFIRM")
            if market_details.get("selection_mode") == "BACKFILL" and not integrity_gap:
                reasons.append(f"HISTORICAL_BACKFILL_OBSERVATION:{market_details['backfill_run_id']}")
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
        if stage_id == "STAGE_0925":
            _auction_review_input(evidence[stage_id], projected_rows, trade_date)
    return result, evidence


def _manual_recovery_context(context: dict[str, Any], trade_date: str) -> dict[str, Any]:
    """Bind an operator recovery to the archived original; never a natural run."""
    sha_fields = ("original_close_sha256", "original_import_receipt_sha256",
                  "original_dispatcher_receipt_sha256", "archive_inventory_sha256")
    fields = {"mode", "trade_date", "original_natural_run_id", *sha_fields}
    if (not isinstance(context, dict) or set(context) != fields
            or context.get("mode") != "MANUAL_HISTORICAL_RECOVERY"
            or context.get("trade_date") != trade_date
            or not isinstance(context.get("original_natural_run_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", context["original_natural_run_id"])
            or any(not isinstance(context.get(key), str)
                   or not re.fullmatch(r"[0-9a-f]{64}", context[key]) for key in sha_fields)):
        raise ValueError("manual recovery context invalid")
    return {**context, "recovered_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}


def build_close_review(
    data_root: Path,
    trade_date: str,
    *,
    stage_selection_root: Path | str | None = None,
    manual_recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recovery = _manual_recovery_context(manual_recovery, trade_date) if manual_recovery is not None else None
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
        model_rows=_model_rows(preselection, trade_date, verified_pool=True),
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
    if recovery is not None:
        if expected_sha != recovery["original_close_sha256"]:
            raise ValueError("manual recovery original close SHA changed")
        review["recovery_provenance"] = recovery
        marker = (f"MANUAL_HISTORICAL_RECOVERY:{recovery['recovered_at']}:"
                  f"source_natural_run={recovery['original_natural_run_id']}")
        review["cannot_confirm"].append(marker)
        for evidence in review["stage_input_evidence"].values():
            if evidence.get("selection_mode") == "BACKFILL":
                evidence["cannot_confirm"].append(marker)
    publication = review_store.publish_native(review, expected_sha256=expected_sha)
    return {"review": review, "publication": publication}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the V3.5-native HK Connect close review")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument("--manual-recovery-context", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        build_close_review(
            args.data_root,
            args.date,
            stage_selection_root=args.stage_selection_root,
            manual_recovery=json.loads(args.manual_recovery_context.read_text(encoding="utf-8"))
            if args.manual_recovery_context is not None else None,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
