"""Build next-day D-1 review lanes from shared immutable public evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa

from domains.d1_review_lane_producer import ensure_preopen_lane_artifacts
from domains.d1_review_source_producer import materialize_d1_review_sources
from infrastructure.formula_generation import read_selector_source_binding
from infrastructure.isolated_package_loader import load_isolated_package_module
from ops.research_panel_logical import parquet
from stage_center.consumer import StageSelectionConsumer
from stage_center.raw_store import RawStore, canonical_sha


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_shared_reader(shared_package_root: Path):
    module = load_isolated_package_module(
        Path(shared_package_root),
        package_directory="shared_data",
        module_leaf="public_fupan",
        namespace_prefix="v35_shared_data",
    )
    return module.read_public_fupan


def _selector_rows(selector: Path, trade_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    binding = read_selector_source_binding(selector, expected_signal_date=trade_date)
    schema = parquet.ParquetFile(selector).schema_arrow
    date_type = schema.field("trade_date").type
    exact_date: Any = int(trade_date) if pa.types.is_integer(date_type) else trade_date
    table = parquet.read_table(
        selector,
        columns=["trade_date", "ts_code", "name", "pct_chg", "amount"],
        filters=[("trade_date", "=", exact_date)],
    )
    if table.num_rows <= 0:
        raise ValueError(f"selector panel has no exact-date close rows: {trade_date}")
    rows = table.to_pylist()
    if any(str(row.get("trade_date") or "").replace("-", "") != trade_date for row in rows):
        raise ValueError(f"selector reader returned a non-exact date row: {trade_date}")
    if _sha256(selector) != binding.get("sha256"):
        raise ValueError("SELECTOR_SOURCE_SHA_CHANGED_DURING_READ")
    return rows, binding


def _safe_child(root: Path, *parts: str) -> Path | None:
    if root.is_symlink():
        return None
    candidate = root
    for part in parts:
        if part in {"", ".", ".."}:
            return None
        candidate = candidate / part
        if candidate.is_symlink():
            return None
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def _stage7_observation_witness(
    selection: dict[str, Any],
    trade_date: str,
    stage_selection_root: Path | None,
) -> dict[str, Any]:
    """Bind Stage7 rows to a natural owner receipt and safe exact-cutoff raw run."""
    reasons: list[str] = []
    selection_markets = selection.get("markets", {}) if isinstance(selection, dict) else {}
    if not isinstance(selection_markets, dict):
        reasons.append("STAGE7_SELECTION_MARKETS_SHAPE_INVALID")
        selection_markets = {}
    a_market = selection_markets.get("A_SHARE", {})
    if not isinstance(a_market, dict):
        reasons.append("STAGE7_SELECTION_A_SHARE_SHAPE_INVALID")
        a_market = {}
    if stage_selection_root is None:
        reasons.append("STAGE7_SELECTION_ROOT_MISSING")
        return {"status": "CANNOT_CONFIRM", "eligible": False, "cannot_confirm": reasons}

    selection_root = Path(stage_selection_root)
    receipt_root = selection_root.parent / "receipts"
    raw_root = selection_root.parent / "raw"
    receipt_path = _safe_child(receipt_root, trade_date, "STAGE_1445_1500", "receipt.json")
    owner_receipt: dict[str, Any] = {}
    history_payload: dict[str, Any] = {}
    owner_receipt_sha = None
    owner_history_sha = None
    try:
        if receipt_path is None or not receipt_path.is_file():
            raise ValueError("STAGE7_OWNER_RECEIPT_MISSING")
        receipt_bytes = receipt_path.read_bytes()
        owner_receipt = json.loads(receipt_bytes)
        if not isinstance(owner_receipt, dict):
            raise ValueError("STAGE7_OWNER_RECEIPT_ROOT_INVALID")
        owner_receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        history = owner_receipt.get("receipt_history")
        if (not isinstance(history, dict)
                or history.get("schema_version") != "stage_center.runner.history_ref.v1"
                or not isinstance(history.get("relative_path"), str)
                or not isinstance(history.get("sha256"), str)):
            raise ValueError("STAGE7_OWNER_HISTORY_RECEIPT_MISSING")
        history_parts = Path(history["relative_path"]).parts
        history_path = _safe_child(receipt_root, *history_parts)
        if history_path is None or not history_path.is_file():
            raise ValueError("STAGE7_OWNER_HISTORY_RECEIPT_UNSAFE")
        history_bytes = history_path.read_bytes()
        owner_history_sha = hashlib.sha256(history_bytes).hexdigest()
        if owner_history_sha != history["sha256"]:
            raise ValueError("STAGE7_OWNER_HISTORY_RECEIPT_SHA_MISMATCH")
        history_payload = json.loads(history_bytes)
        if not isinstance(history_payload, dict):
            raise ValueError("STAGE7_OWNER_HISTORY_RECEIPT_ROOT_INVALID")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        reasons.append(str(error) or "STAGE7_OWNER_RECEIPT_CANNOT_CONFIRM")
        owner_receipt = {}
        history_payload = {}
    if not owner_receipt or history_payload != {key: value for key, value in owner_receipt.items() if key != "receipt_history"}:
        reasons.append("STAGE7_OWNER_HISTORY_RECEIPT_PAYLOAD_MISMATCH")

    owner_markets = owner_receipt.get("markets", {})
    if not isinstance(owner_markets, dict):
        reasons.append("STAGE7_OWNER_MARKETS_SHAPE_INVALID")
        owner_markets = {}
    history_markets = history_payload.get("markets", {})
    if not isinstance(history_markets, dict):
        reasons.append("STAGE7_OWNER_HISTORY_MARKETS_SHAPE_INVALID")
        history_markets = {}
    owner_selection_artifacts = owner_receipt.get("selection_artifacts", {})
    if not isinstance(owner_selection_artifacts, dict):
        reasons.append("STAGE7_OWNER_SELECTION_ARTIFACTS_SHAPE_INVALID")
        owner_selection_artifacts = {}
    history_selection_artifacts = history_payload.get("selection_artifacts", {})
    if not isinstance(history_selection_artifacts, dict):
        reasons.append("STAGE7_OWNER_HISTORY_SELECTION_ARTIFACTS_SHAPE_INVALID")
        history_selection_artifacts = {}
    stage_receipt_market = owner_markets.get("A_SHARE", {})
    if not isinstance(stage_receipt_market, dict):
        reasons.append("STAGE7_OWNER_A_SHARE_MARKET_SHAPE_INVALID")
        stage_receipt_market = {}
    history_stage_market = history_markets.get("A_SHARE", {})
    if not isinstance(history_stage_market, dict):
        reasons.append("STAGE7_OWNER_HISTORY_A_SHARE_MARKET_SHAPE_INVALID")
        history_stage_market = {}
    selection_binding = owner_selection_artifacts.get("A_SHARE", {})
    if not isinstance(selection_binding, dict):
        reasons.append("STAGE7_OWNER_A_SHARE_SELECTION_BINDING_SHAPE_INVALID")
        selection_binding = {}
    history_selection_binding = history_selection_artifacts.get("A_SHARE", {})
    if not isinstance(history_selection_binding, dict):
        reasons.append("STAGE7_OWNER_HISTORY_A_SHARE_SELECTION_BINDING_SHAPE_INVALID")
        history_selection_binding = {}
    if stage_receipt_market != history_stage_market or selection_binding != history_selection_binding:
        reasons.append("STAGE7_OWNER_HISTORY_NESTED_BINDING_MISMATCH")

    raw_latest: dict[str, Any] = {}
    raw_verified: dict[str, Any] = {}
    raw_manifest: dict[str, Any] = {}
    try:
        raw_result = RawStore(raw_root).verify_latest(trade_date, "STAGE_1445_1500", "A_SHARE")
        if not isinstance(raw_result, dict):
            raise ValueError("STAGE7_RAW_VERIFICATION_ROOT_INVALID")
        raw_latest = raw_result.get("latest", {})
        raw_verified = raw_result.get("verified", {})
        if not isinstance(raw_latest, dict) or not isinstance(raw_verified, dict):
            raise ValueError("STAGE7_RAW_VERIFICATION_SHAPE_INVALID")
        manifest_relative = Path(str(raw_verified.get("manifest_relative") or ""))
        manifest_path = _safe_child(raw_root, *manifest_relative.parts)
        if manifest_path is None or not manifest_path.is_file():
            raise ValueError("STAGE7_RAW_MANIFEST_MISSING_OR_UNSAFE")
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, dict):
            raise ValueError("STAGE7_RAW_MANIFEST_ROOT_INVALID")
        if canonical_sha(raw_manifest) != raw_verified.get("manifest_sha256"):
            raise ValueError("STAGE7_RAW_MANIFEST_SHA_MISMATCH")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        reasons.append(f"STAGE7_RAW_CANNOT_CONFIRM:{error}")
        raw_manifest = {}

    # A verified PARTIAL_WITH_ROWS selection can still be used when its only
    # gaps are optional research fields. These two reasons invalidate the
    # actual stage observation or its A-share universe.
    selection_reasons = [str(item) for item in (a_market.get("cannot_confirm") or [])]
    raw_reasons = [str(item) for item in (raw_verified.get("cannot_confirm") or [])]
    selection_mode = str(a_market.get("selection_mode") or "").upper()
    owner_dispatch_mode = str(owner_receipt.get("dispatch_mode") or "").upper()
    history_dispatch_mode = str(history_payload.get("dispatch_mode") or "").upper()
    if selection_mode == "BACKFILL" or owner_dispatch_mode == "BACKFILL" or history_dispatch_mode == "BACKFILL":
        reasons.append("STAGE7_BACKFILL_NOT_NATURAL")
    if any(item == "RESEARCH_STAGE_EVIDENCE_MISSING" for item in selection_reasons):
        reasons.append("RESEARCH_STAGE_EVIDENCE_MISSING")
    if any(item.startswith("A_MEMBERSHIP_") for item in (*selection_reasons, *raw_reasons)):
        reasons.append("A_MEMBERSHIP_AUTHORITY_UNKNOWN")

    status = str(a_market.get("status") or a_market.get("selection_status") or "")
    selected_rows = a_market.get("selected_rows")
    rows = a_market.get("rows") if isinstance(a_market.get("rows"), list) else []
    selection_identity_ok = (
        a_market.get("trade_date") == trade_date
        and a_market.get("stage_id") == "STAGE_1445_1500"
        and status in {"READY", "PARTIAL_WITH_ROWS"}
        and bool(rows)
        and type(selected_rows) is int
        and selected_rows == len(rows)
        and a_market.get("selection_manifest_receipt_verified") is True
        and selection_binding.get("schema_version") == "stage_center.runner.selection_binding.v1"
        and selection_binding.get("trade_date") == trade_date
        and selection_binding.get("stage_id") == "STAGE_1445_1500"
        and selection_binding.get("market") == "A_SHARE"
        and selection_binding.get("artifact_id") == a_market.get("artifact_id")
        and selection_binding.get("run_id") == a_market.get("run_id")
        and selection_binding.get("raw_artifact_sha256") == a_market.get("raw_artifact_sha256")
        and selection_binding.get("manifest_canonical_sha256") == a_market.get("selection_manifest_sha256")
        and selection_binding.get("receipt_canonical_sha256") == a_market.get("selection_receipt_sha256")
        and selection_binding.get("artifact_bytes_sha256") == a_market.get("selection_artifact_sha256")
        and selection_binding.get("selected_rows") == selected_rows
    )
    if not selection_identity_ok:
        reasons.append("STAGE7_SELECTION_BINDING_CANNOT_CONFIRM")

    natural_receipt_ok = (
        owner_receipt.get("schema_version") == "stage_center.runner.receipt.v1"
        and owner_receipt.get("runner") == "stage_center"
        and owner_receipt.get("trade_date") == trade_date
        and owner_receipt.get("stage_id") == "STAGE_1445_1500"
        and owner_receipt.get("node_id") == "STAGE_1445_1500"
        and owner_receipt.get("dispatch_mode") == "NATURAL"
        and owner_receipt.get("due_status") == "DUE"
        and owner_receipt.get("node_outcome") in {"SETTLED", "SETTLED_PARTIAL"}
        and owner_receipt.get("write_performed") is True
        and owner_receipt.get("record_time_source") == "OWNER_WRITE_CLOCK_UTC"
        and owner_receipt.get("status") in {"READY", "PARTIAL_WITH_ROWS"}
        and all(owner_receipt.get(flag) is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        and stage_receipt_market.get("trade_date") == trade_date
        and stage_receipt_market.get("stage_id") == "STAGE_1445_1500"
        and stage_receipt_market.get("selection_status") == status
        and stage_receipt_market.get("artifact_id") == a_market.get("artifact_id")
        and stage_receipt_market.get("run_id") == a_market.get("run_id")
        and stage_receipt_market.get("algorithm_sha256") == a_market.get("algorithm_sha256")
        and stage_receipt_market.get("raw_artifact_sha256") == a_market.get("raw_artifact_sha256")
        and stage_receipt_market.get("selected_rows") == selected_rows
        and history_payload.get("trade_date") == trade_date
        and history_payload.get("stage_id") == "STAGE_1445_1500"
        and history_payload.get("dispatch_mode") == "NATURAL"
        and history_payload.get("selection_artifacts") == owner_receipt.get("selection_artifacts")
        and history_payload == {key: value for key, value in owner_receipt.items() if key != "receipt_history"}
    )
    if not natural_receipt_ok:
        reasons.append("STAGE7_NATURAL_OWNER_RECEIPT_CANNOT_CONFIRM")

    raw_status = str(raw_verified.get("status") or "")
    raw_sha = raw_verified.get("artifact_sha256")
    raw_ready_ok = (
        raw_status == "READY"
        and raw_manifest.get("status") == "READY"
        and raw_manifest.get("trade_date") == trade_date
        and raw_manifest.get("stage_id") == "STAGE_1445_1500"
        and raw_manifest.get("market") == "A_SHARE"
        and raw_manifest.get("temporal_cutoff_safe") is True
        and int(raw_verified.get("row_count") or 0) > 0
        and raw_verified.get("window") == "14:45-15:00"
        and raw_verified.get("cutoff_at") == "15:00:00"
        and raw_latest.get("status") == "READY"
        and raw_latest.get("artifact_sha256") == raw_sha
        and raw_sha == a_market.get("raw_artifact_sha256")
        and raw_sha == stage_receipt_market.get("raw_artifact_sha256")
        and raw_sha == selection_binding.get("raw_artifact_sha256")
    )
    if not raw_ready_ok:
        reasons.append("STAGE7_RAW_NOT_READY_OR_UNSAFE")

    reasons = list(dict.fromkeys(reasons))
    eligible = not reasons
    return {
        "status": "VERIFIED_NATURAL_STAGE7_OBSERVATION" if eligible else "CANNOT_CONFIRM",
        "eligible": eligible,
        "trade_date": trade_date,
        "stage_id": "STAGE_1445_1500",
        "selection_status": status,
        "selected_rows": selected_rows if type(selected_rows) is int else None,
        "selection_artifact_id": a_market.get("artifact_id"),
        "selection_run_id": a_market.get("run_id"),
        "selection_algorithm_sha256": a_market.get("algorithm_sha256"),
        "selection_manifest_sha256": a_market.get("selection_manifest_sha256"),
        "selection_receipt_sha256": a_market.get("selection_receipt_sha256"),
        "selection_artifact_sha256": a_market.get("selection_artifact_sha256"),
        "raw_status": raw_status or "CANNOT_CONFIRM",
        "raw_run_id": raw_verified.get("run_id"),
        "raw_artifact_sha256": raw_sha,
        "raw_manifest_sha256": raw_verified.get("manifest_sha256"),
        "raw_receipt_sha256": raw_verified.get("receipt_sha256"),
        "raw_row_count": raw_verified.get("row_count"),
        "raw_window": raw_verified.get("window"),
        "raw_cutoff_at": raw_verified.get("cutoff_at"),
        "raw_temporal_cutoff_safe": raw_manifest.get("temporal_cutoff_safe"),
        "owner_receipt_sha256": owner_receipt_sha,
        "owner_history_receipt_sha256": owner_history_sha,
        "cannot_confirm": reasons,
    }


def _safe_stage7_observation_witness(
    selection: dict[str, Any],
    trade_date: str,
    stage_selection_root: Path | None,
) -> dict[str, Any]:
    """Keep a malformed Stage7 witness from aborting the independent fupan lane."""
    try:
        return _stage7_observation_witness(selection, trade_date, stage_selection_root)
    except Exception as error:
        return {
            "status": "CANNOT_CONFIRM",
            "eligible": False,
            "trade_date": trade_date,
            "stage_id": "STAGE_1445_1500",
            "cannot_confirm": [f"STAGE7_WITNESS_ERROR:{type(error).__name__}"],
        }


def _stage_selection_payload(selection: dict[str, Any], trade_date: str, stage_id: str) -> dict[str, Any]:
    markets = selection.get("markets") if isinstance(selection.get("markets"), dict) else {}
    a_market = markets.get("A_SHARE") if isinstance(markets.get("A_SHARE"), dict) else {}
    hk_market = markets.get("HK_CONNECT") if isinstance(markets.get("HK_CONNECT"), dict) else {}
    a_rows = list(a_market.get("rows") or [])
    market_cannot_confirm = [
        str(item)
        for item in (a_market.get("cannot_confirm") or [])
        if str(item).strip()
    ]
    top_level_cannot_confirm = [
        str(item)
        for item in (selection.get("cannot_confirm") or [])
        if str(item).strip()
    ]
    cannot_confirm = list(dict.fromkeys((*top_level_cannot_confirm, *market_cannot_confirm)))
    requested_rows = a_market.get("requested_rows", len(a_rows))
    source_rows = a_market.get("source_rows", len(a_rows))
    selected_rows = a_market.get("selected_rows", len(a_rows))
    coverage_ratio = a_market.get("coverage_ratio", 0.0)
    source_summary = {
        "quote_coverage": {
            "A_SHARE": {
                "coverage_ratio": coverage_ratio,
                "missing_symbols": list(a_market.get("missing_symbols") or []),
                "requested_rows": requested_rows,
                "selected_rows": selected_rows,
                "source_rows": source_rows,
            }
        },
        "cannot_confirm": list(cannot_confirm),
    }
    market_status = {
        "A_SHARE": str(
            a_market.get("status")
            or a_market.get("selection_status")
            or selection.get("status")
            or "CANNOT_CONFIRM"
        )
    }
    return {
        "schema_version": "v3_5.stage_input_from_stage_center.v1",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "selection_status": selection.get("status", "CANNOT_CONFIRM"),
        "artifact_id": a_market.get("artifact_id") or selection.get("artifact_id"),
        "bundle_artifact_id": selection.get("bundle_artifact_id"),
        "run_id": a_market.get("run_id") or selection.get("run_id"),
        "algorithm_sha256": a_market.get("algorithm_sha256"),
        "raw_artifact_sha256": a_market.get("raw_artifact_sha256"),
        "selection_manifest_sha256": a_market.get("selection_manifest_sha256"),
        "selection_receipt_sha256": a_market.get("selection_receipt_sha256"),
        "selection_artifact_sha256": a_market.get("selection_artifact_sha256"),
        "selection_manifest_receipt_verified": a_market.get("selection_manifest_receipt_verified") is True,
        "rows": {"A": a_rows, "HK": list(hk_market.get("rows") or [])},
        "source_summary": source_summary,
        "market_status": market_status,
        "cannot_confirm": cannot_confirm,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _native_stage_input_is_valid(
    payload: Any, trade_date: str, stage_id: str
) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id:
        return False
    if any(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    rows = payload.get("rows")
    return isinstance(rows, dict) and isinstance(rows.get("A"), list) and bool(rows["A"])


def _stage_inputs(
    data_root: Path,
    trade_date: str,
    *,
    stage_selection_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    root = data_root / "stage_inputs" / trade_date
    result: dict[str, dict[str, Any]] = {}
    for stage_id in ("STAGE_0940_0945", "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500"):
        if stage_id == "STAGE_1445_1500":
            selection = (
                StageSelectionConsumer(stage_selection_root).get(
                    trade_date, stage_id, markets=("A_SHARE",)
                )
                if stage_selection_root is not None
                else {"status": "CANNOT_CONFIRM", "trade_date": trade_date, "stage_id": stage_id,
                      "cannot_confirm": ["STAGE7_SELECTION_ROOT_MISSING"], "markets": {}}
            )
            payload = _stage_selection_payload(selection, trade_date, stage_id)
            witness = _safe_stage7_observation_witness(selection, trade_date, stage_selection_root)
            payload["stage7_observation_witness"] = witness
            payload.setdefault("source_summary", {})["stage7_observation_witness"] = witness
            if witness.get("eligible") is not True:
                reasons = list(dict.fromkeys([*(payload.get("cannot_confirm") or []), *(witness.get("cannot_confirm") or [])]))
                payload["cannot_confirm"] = reasons
                payload["selection_status"] = "CANNOT_CONFIRM"
                payload["status"] = "CANNOT_CONFIRM"
                payload["source_status"] = "CANNOT_CONFIRM"
                payload["selected_rows"] = 0
                payload["source_rows"] = 0
                payload["rows"] = {"A": [], "HK": []}
                payload["source_summary"]["cannot_confirm"] = reasons
                payload["source_summary"]["quote_coverage"] = {
                    "A_SHARE": {"coverage_ratio": 0.0, "missing_symbols": [],
                                "requested_rows": 0, "selected_rows": 0, "source_rows": 0}
                }
                payload["market_status"] = {"A_SHARE": "CANNOT_CONFIRM"}
            result[stage_id] = payload
            continue
        path = root / f"{stage_id}.json"
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if _native_stage_input_is_valid(payload, trade_date, stage_id):
                result[stage_id] = payload
        if stage_id not in result and stage_selection_root is not None:
            selection = StageSelectionConsumer(stage_selection_root).get(
                trade_date, stage_id, markets=("A_SHARE",)
            )
            result[stage_id] = _stage_selection_payload(selection, trade_date, stage_id)
    return result


def materialize_daily_d1_lanes(
    *,
    trade_date: str,
    target_date: str,
    data_root: Path,
    preselection_input_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    selector: Path,
    stage_selection_root: Path | None = None,
) -> dict[str, Any]:
    shared = _load_shared_reader(shared_package_root)(shared_data_root, trade_date)
    manifest = shared["manifest"]
    public_manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_dir = data_root / "d1_review_sources" / trade_date / "native"
    selector_rows, selector_binding = _selector_rows(selector, trade_date)
    stage_inputs = _stage_inputs(
        data_root, trade_date, stage_selection_root=stage_selection_root
    )
    stage7_witness = stage_inputs["STAGE_1445_1500"]["stage7_observation_witness"]
    fupan_only = stage7_witness.get("eligible") is not True
    if fupan_only:
        for payload in stage_inputs.values():
            payload["rows"] = {"A": [], "HK": []}
    source_receipt = materialize_d1_review_sources(
        trade_date=trade_date,
        public_files=shared["files"],
        public_manifest_sha256=public_manifest_sha256,
        selector_rows=selector_rows,
        selector_sha256=str(selector_binding["sha256"]),
        selector_binding=selector_binding,
        stage_inputs=stage_inputs,
        output_dir=source_dir,
        fupan_only=fupan_only,
    )
    lane_result = ensure_preopen_lane_artifacts(
        target_date,
        signal_date=trade_date,
        source_dir=source_dir,
        output_dir=preselection_input_root / target_date,
        fupan_only=fupan_only,
    )
    if lane_result.get("ok") is not True:
        raise ValueError(str(lane_result.get("status") or "D-1 lane materialization failed"))
    return {
        "status": "PARTIAL" if fupan_only else "READY",
        "trade_date": trade_date,
        "target_date": target_date,
        "shared_public_run_id": shared["receipt"]["run_id"],
        "source_receipt": source_receipt,
        "lane_result": lane_result,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--preselection-input-root", type=Path, required=True)
    parser.add_argument("--shared-data-root", type=Path, required=True)
    parser.add_argument("--shared-package-root", type=Path, required=True)
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--stage-selection-root", type=Path)
    args = parser.parse_args()
    try:
        result = materialize_daily_d1_lanes(
            trade_date=args.trade_date,
            target_date=args.target_date,
            data_root=args.data_root,
            preselection_input_root=args.preselection_input_root,
            shared_data_root=args.shared_data_root,
            shared_package_root=args.shared_package_root,
            selector=args.selector,
            stage_selection_root=args.stage_selection_root,
        )
    except (OSError, ValueError, ImportError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
