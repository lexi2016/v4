"""Build next-day D-1 review lanes from shared immutable public evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


from domains.d1_review_lane_producer import ensure_preopen_lane_artifacts
from domains.d1_review_source_producer import materialize_d1_review_sources
from infrastructure.isolated_package_loader import load_isolated_package_module
from stage_center.consumer import StageSelectionConsumer


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


def _selector_rows(selector: Path, trade_date: str) -> list[dict[str, Any]]:
    import pyarrow.dataset as ds
    table = ds.dataset(str(selector), format="parquet").to_table(
        columns=["trade_date", "ts_code", "name", "pct_chg", "amount"],
        filter=ds.field("trade_date") == trade_date,
    )
    if table.num_rows <= 0:
        raise ValueError(f"selector panel has no exact-date close rows: {trade_date}")
    return table.to_pylist()


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
    stage7 = result.get("STAGE_1445_1500")
    if not isinstance(stage7, dict) or stage7.get("trade_date") != trade_date:
        raise ValueError(f"native Stage7 input is missing for {trade_date}")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if stage7.get(key) is not False:
            raise ValueError(f"native Stage7 safety flag {key} must be false")
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
    source_receipt = materialize_d1_review_sources(
        trade_date=trade_date,
        public_files=shared["files"],
        public_manifest_sha256=public_manifest_sha256,
        selector_rows=_selector_rows(selector, trade_date),
        selector_sha256=_sha256(selector),
        stage_inputs=_stage_inputs(
            data_root, trade_date, stage_selection_root=stage_selection_root
        ),
        output_dir=source_dir,
    )
    lane_result = ensure_preopen_lane_artifacts(
        target_date,
        signal_date=trade_date,
        source_dir=source_dir,
        output_dir=preselection_input_root / target_date,
    )
    if lane_result.get("ok") is not True:
        raise ValueError(str(lane_result.get("status") or "D-1 lane materialization failed"))
    return {
        "status": "PARTIAL_WITH_ROWS" if (
            source_receipt.get("cannot_confirm") or lane_result.get("cannot_confirm")
            or "PARTIAL" in str(source_receipt.get("status"))
            or "PARTIAL" in str(lane_result.get("status"))
        ) else "READY",
        "trade_date": trade_date,
        "target_date": target_date,
        "shared_public_run_id": shared["receipt"]["run_id"],
        "source_receipt": source_receipt,
        "lane_result": lane_result,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }




def recover_stage7_original(*, source_dir: Path, data_root: Path,
                            review_core_package_root: Path, review_core_store_root: Path,
                            signal_date: str, target_date: str, expected_sha256: str,
                            expected_original_sha256: dict[str, str] | None = None) -> dict[str, Any]:
    """Exact recovery through StageStore -> ReviewCore -> bridge -> native D1 owner."""
    from domains.d1_review_lane_producer import materialize_recovered_stage7_lane
    from infrastructure.historical_pool_sources import (
        FLAGS, check_dates, coverage, import_stage7_original, native_stage7_payload,
        preflight_stage7_original, require_external_original_sha,
    )
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from infrastructure.review_core_stage7_pool_source import _project
    check_dates(signal_date, target_date)
    require_external_original_sha("stage7", signal_date, target_date, expected_original_sha256)
    preflight_stage7_original(data_root, source_dir, expected_sha256, signal_date=signal_date, target_date=target_date)
    imported = import_stage7_original(data_root, source_dir, signal_date=signal_date, target_date=target_date)
    module = load_isolated_package_module(review_core_package_root, package_directory="review_core",
                                         module_leaf="stage7_pool", namespace_prefix="v35_review_core")
    module.publish_stage7_replay_pool(review_core_store_root, signal_date, target_date,
                                     stage_input_root=data_root)
    verified = module.read_stage7_replay_pool(target_date, review_core_store_root)
    bridge = _project(target_date, review_core_store_root, verified)
    c = coverage(signal_date, target_date)
    if bridge["status"] != "PARTIAL" or len(bridge["rows"]) != c["source_rows"] or bridge["coverage_evidence"] != c:
        raise ValueError("Stage7 recovery bridge did not preserve partial original coverage")
    lane = materialize_recovered_stage7_lane(data_root, signal_date=signal_date, target_date=target_date)
    payload = native_stage7_payload(data_root, Path(lane["lane_dir"]), signal_date, target_date)
    pool = PreselectionPoolStore(data_root)
    recovered = pool._recover_0918_original(payload, expected_sha256)
    snapshot = pool.read_pool_snapshot(target_date, payload["pool_id"])
    return {"status": "PARTIAL_WITH_ROWS", "signal_date": signal_date, "target_date": target_date,
            "stage_input_sha256": imported["sha256"], "review_core_readback": verified,
            "bridge_readback": bridge, "lane": lane, "pool_recovery": recovered,
            "pool_readback": snapshot, "coverage_evidence": c,
            "cannot_confirm": list(payload["cannot_confirm"]), "RESEARCH_ONLY": True, **FLAGS}

def _recovery_main(argv) -> int:
    parser = argparse.ArgumentParser(description="Bounded Stage7 original-source recovery, no deployment")
    parser.add_argument("--recover-stage7-original", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--review-core-package-root", type=Path, required=True)
    parser.add_argument("--review-core-store-root", type=Path, required=True)
    parser.add_argument("--expected-pool-sha256", required=True)
    for name in ("artifact", "manifest", "receipt"):
        parser.add_argument(f"--expected-original-{name}-sha256")
    args = parser.parse_args(argv)
    from infrastructure.historical_pool_sources import original_sha_arguments
    try:
        result = recover_stage7_original(source_dir=args.recover_stage7_original,
            data_root=args.data_root, review_core_package_root=args.review_core_package_root,
            review_core_store_root=args.review_core_store_root, signal_date=args.trade_date,
            target_date=args.target_date, expected_sha256=args.expected_pool_sha256,
            expected_original_sha256=original_sha_arguments(args))
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}:{error}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def main() -> int:
    import sys
    if "--recover-stage7-original" in sys.argv[1:]:
        return _recovery_main(sys.argv[1:])
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
