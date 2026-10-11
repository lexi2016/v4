#!/usr/bin/env python3
"""Replay the scheduled 09:30 node against isolated 2026-09-24 store roots.

Reads immutable active raw and receipt inputs, copies only the verified HK
09:25 auction and/or 09:30 minute run files into E7 candidate fixtures, then
calls the candidate's public ``run_nodes`` entry with an injected clock.  The
stage dispatch is replaced by the already-settled 09:30 receipt so this replay
does not call a collector or touch any active store.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


E7_ROOT = Path(__file__).resolve().parents[1]
STAGE_APP = E7_ROOT / "candidate/stage_owner/app"
if str(STAGE_APP) not in sys.path:
    sys.path.insert(0, str(STAGE_APP))

import ops.run_stage_center_nodes as node_runner  # noqa: E402
from stage_center.raw_store import RawStore  # noqa: E402
from stage_center.runner import _build_hk_stage_binding  # noqa: E402
from stage_center.selection import ALGORITHM_SHA256, SelectionStore, _selection_envelope  # noqa: E402


TRADE_DATE = "20260924"
SHANGHAI = ZoneInfo("Asia/Shanghai")
EVALUATED_AT = datetime(2026, 9, 24, 9, 35, 5, tzinfo=SHANGHAI)
SOURCE_STAGE = "STAGE_0930_0935"
TARGET_STAGE = "STAGE_0925"
HK = "HK_CONNECT"
EXPECTED_RAW_SHA = "9653a5c70d329d1e7da4dd788d7c04e10cc891e8cf09252356842f9f05d70629"
EXPECTED_MANIFEST_SHA = "b3fb209c3e43f6a70384c5505f6707d455334c9c9f3113f935e9c72cb3391068"
EXPECTED_RECEIPT_SHA = "6c48e061b980c66910ce13d2b6bc0ffd8a098df9e927b2661458fb1c12f2b12d"
EXPECTED_D1_SHA = "50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _seed_raw_fixture(active_raw: Path, output_raw: Path, *, stages: tuple[str, ...]) -> dict[str, dict]:
    if output_raw.exists():
        raise FileExistsError(f"refusing to overwrite replay fixture: {output_raw}")
    active_latest = json.loads((active_raw / "latest.json").read_text(encoding="utf-8"))
    active_entries = active_latest.get("entries")
    if not isinstance(active_entries, dict):
        raise ValueError("active raw latest entries are unreadable")
    entries: dict[str, dict] = {}
    active_store = RawStore(active_raw)
    for stage_id in stages:
        key = f"{TRADE_DATE}/{stage_id}/{HK}"
        entry = active_entries.get(key)
        if not isinstance(entry, dict):
            raise ValueError(f"active raw is missing verified run pointer for {key}")
        verified = active_store.verify_run(TRADE_DATE, stage_id, HK, str(entry.get("run_id") or ""))
        run_relative = Path(str(verified["artifact_relative"])).parent
        source_run = active_raw / run_relative
        target_run = output_raw / run_relative
        target_run.mkdir(parents=True, exist_ok=False)
        for filename in ("artifact.csv", "manifest.json", "receipt.json"):
            source_file = source_run / filename
            if source_file.is_symlink() or not source_file.is_file():
                raise ValueError(f"expected regular immutable run file: {source_file}")
            shutil.copyfile(source_file, target_run / filename)
        entries[key] = dict(entry)

    latest = {key: value for key, value in active_latest.items() if key != "entries"}
    latest["entries"] = entries
    _write_json(output_raw / "latest.json", latest)
    return entries


def _run_node(config: dict, settled_stage_receipt: dict) -> dict:
    original_dispatch = node_runner._dispatch_stage
    seen: list[tuple[str, str]] = []

    def replay_dispatch(_config, trade_date, stage_id, _evaluated_at, **_kwargs):
        seen.append((trade_date, stage_id))
        if trade_date != TRADE_DATE or stage_id != SOURCE_STAGE:
            raise AssertionError(f"unexpected replay dispatch: {trade_date}/{stage_id}")
        return dict(settled_stage_receipt)

    node_runner._dispatch_stage = replay_dispatch
    try:
        outcome = node_runner.run_nodes(
            config,
            trade_date=TRADE_DATE,
            evaluated_at=EVALUATED_AT,
            explicit_node=SOURCE_STAGE,
            sleep=lambda _seconds: None,
        )
    finally:
        node_runner._dispatch_stage = original_dispatch
    if seen != [(TRADE_DATE, SOURCE_STAGE)]:
        raise AssertionError(f"scheduled node did not dispatch exactly once: {seen!r}")
    nodes = outcome.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 1:
        raise AssertionError(f"unexpected automatic entry result: {outcome!r}")
    return nodes[0]


def _scenario_config(config: dict, root: Path) -> dict:
    cloned = dict(config)
    cloned["raw_root"] = str(root / "raw")
    cloned["selection_root"] = str(root / "selection")
    cloned["receipt_root"] = str(root / "receipts")
    return cloned


def _assert_missing_target_raw(raw_root: Path) -> None:
    raw_latest = raw_root / "latest.json"
    target_key = f"{TRADE_DATE}/{TARGET_STAGE}/{HK}"
    if raw_latest.exists():
        entries = json.loads(raw_latest.read_text(encoding="utf-8")).get("entries", {})
        if target_key in entries:
            raise AssertionError("replay must start with missing 09:25 auction raw")


def _assert_no_target_selection_or_receipt(selection_root: Path, receipt_root: Path) -> None:
    selection_latest = selection_root / "selection_latest.json"
    if selection_latest.exists():
        entries = json.loads(selection_latest.read_text(encoding="utf-8")).get("entries", {})
        if SelectionStore._key(TRADE_DATE, TARGET_STAGE, HK) in entries:
            raise AssertionError("replay must start with missing 09:25 selection")
    if (receipt_root / TRADE_DATE / TARGET_STAGE / "receipt.json").exists():
        raise AssertionError("replay must start with missing 09:25 owner receipt")


def _seed_failed_target_slot(selection_root: Path, receipt_root: Path) -> dict:
    failure_identity = {
        "fixture": "synthetic_missing_0925_auction_failure_slot",
        "trade_date": TRADE_DATE,
        "stage_id": TARGET_STAGE,
        "market": HK,
        "source_raw_present": False,
    }
    failure_identity_sha = hashlib.sha256(
        json.dumps(failure_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    envelope = _selection_envelope(
        trade_date=TRADE_DATE,
        stage_id=TARGET_STAGE,
        market=HK,
        raw_artifact_sha256=failure_identity_sha,
        source_status="CANNOT_CONFIRM",
        input_rows=0,
        rows=[],
        requested_rows=100,
        missing_symbols=(),
        cannot_confirm=("HK_0920_AUCTION_RAW_MISSING",),
        source_evidence=(
            "replay_fixture=synthetic_failed_empty_slot_not_market_data",
            "auction_capture_status=CANNOT_CONFIRM",
            f"replay_failure_identity_sha256={failure_identity_sha}",
        ),
        algorithm_sha256=ALGORITHM_SHA256,
    )
    failed_selection = SelectionStore(selection_root).publish(envelope, market=HK)
    receipt_path = receipt_root / TRADE_DATE / TARGET_STAGE / "receipt.json"
    _write_json(receipt_path, {
        "trade_date": TRADE_DATE,
        "stage_id": TARGET_STAGE,
        "market": HK,
        "status": "CANNOT_CONFIRM",
        "retry_exhausted": True,
        "replay_fixture": "synthetic_failed_empty_slot_not_market_data",
    })
    return {
        "selection_run_id": failed_selection["run_id"],
        "selection_status": failed_selection["selection_status"],
        "selected_rows": failed_selection["selected_rows"],
        "failure_identity_sha256": failure_identity_sha,
        "receipt_status": "CANNOT_CONFIRM",
        "retry_exhausted": True,
    }


def _assert_failed_target_state(raw_root: Path, selection_root: Path, receipt_root: Path, seeded: dict) -> None:
    _assert_missing_target_raw(raw_root)
    failed_selection = SelectionStore(selection_root).read_verified(TRADE_DATE, TARGET_STAGE, HK)
    if (failed_selection.get("run_id") != seeded["selection_run_id"]
            or failed_selection.get("selection_status") != "CANNOT_CONFIRM"
            or failed_selection.get("rows") != []
            or failed_selection.get("selected_rows") != 0):
        raise AssertionError("replay must start with a verified zero-row CANNOT_CONFIRM selection")
    receipt_path = receipt_root / TRADE_DATE / TARGET_STAGE / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("trade_date") != TRADE_DATE or receipt.get("stage_id") != TARGET_STAGE
            or receipt.get("status") != "CANNOT_CONFIRM" or receipt.get("retry_exhausted") is not True):
        raise AssertionError("replay must start with a same-date retry-exhausted failed receipt")


def main() -> int:
    baseline_path = E7_ROOT / "integration/BASELINE.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    active_stage_app = Path(baseline["com.lexi.stage-center.scheduler"]["app"])
    active_config_path = active_stage_app / "stage_center_tick_config.json"
    config = json.loads(active_config_path.read_text(encoding="utf-8"))
    active_raw = Path(config["raw_root"])
    active_receipts = Path(config["receipt_root"])

    active_raw_store = RawStore(active_raw)
    minute_entry = active_raw_store.verify_latest(TRADE_DATE, SOURCE_STAGE, HK)["verified"]
    auction_entry = active_raw_store.verify_latest(TRADE_DATE, TARGET_STAGE, HK)["verified"]
    if (minute_entry.get("artifact_sha256") != EXPECTED_RAW_SHA
            or minute_entry.get("manifest_sha256") != EXPECTED_MANIFEST_SHA
            or minute_entry.get("receipt_sha256") != EXPECTED_RECEIPT_SHA):
        raise AssertionError("active 09:30 raw identity changed from the reviewed replay input")
    if auction_entry.get("status") != "READY":
        raise AssertionError("the auction-priority scenario requires a verified READY 09:25 raw run")

    binding = _build_hk_stage_binding(
        Path(config["hk_d1_root"]),
        TRADE_DATE,
        preselection_source_root=config.get("preselection_source_root"),
    )
    if (binding.status != "READY" or binding.role != "HK_CONNECT_D1_TOP100"
            or binding.trade_date != TRADE_DATE or len(set(binding.codes)) != 100
            or binding.sha256 != EXPECTED_D1_SHA):
        raise AssertionError("active exact same-date HK D-1 Top100 binding differs from the reviewed input")

    settled_receipt_path = active_receipts / TRADE_DATE / SOURCE_STAGE / "receipt.json"
    settled_stage_receipt = json.loads(settled_receipt_path.read_text(encoding="utf-8"))
    if (settled_stage_receipt.get("trade_date") != TRADE_DATE
            or settled_stage_receipt.get("stage_id") != SOURCE_STAGE
            or settled_stage_receipt.get("status") not in {"READY", "PARTIAL_WITH_ROWS"}):
        raise AssertionError("the source stage receipt is not settled for the replay date")

    replay_root = E7_ROOT / "candidate/replay/e7-hk-0925-auto-entry-20260924-r3"
    if replay_root.exists():
        raise FileExistsError(f"refusing to overwrite completed replay: {replay_root}")
    positive_root = replay_root / "missing-target-minute-available"
    auction_root = replay_root / "auction-present"
    missing_minute_root = replay_root / "missing-target-minute-missing"
    positive_root.mkdir(parents=True)
    auction_root.mkdir(parents=True)
    missing_minute_root.mkdir(parents=True)

    positive_entries = _seed_raw_fixture(active_raw, positive_root / "raw", stages=(SOURCE_STAGE,))
    auction_entries = _seed_raw_fixture(active_raw, auction_root / "raw", stages=(TARGET_STAGE, SOURCE_STAGE))
    (missing_minute_root / "raw").mkdir()
    failed_target_start = _seed_failed_target_slot(positive_root / "selection", positive_root / "receipts")

    positive_config = _scenario_config(config, positive_root)
    _assert_failed_target_state(positive_root / "raw", positive_root / "selection", positive_root / "receipts", failed_target_start)
    before_positive_raw_sha = _sha(positive_root / "raw/latest.json")
    first_node = _run_node(positive_config, settled_stage_receipt)
    automatic = first_node.get("hk_0925_automatic_substitute")
    if not isinstance(automatic, dict) or automatic.get("status") != "PARTIAL_WITH_ROWS" or automatic.get("write_performed") is not True:
        raise AssertionError(f"missing-target replay did not publish a partial research substitute: {automatic!r}")
    if automatic.get("missing_symbols") != ["HK.02632", "HK.03355"]:
        raise AssertionError(f"partial source missing-code list changed: {automatic.get('missing_symbols')!r}")
    if _sha(positive_root / "raw/latest.json") != before_positive_raw_sha:
        raise AssertionError("automatic substitute changed the immutable candidate raw latest pointer")

    selection_store = SelectionStore(positive_root / "selection")
    selected = selection_store.read_verified(TRADE_DATE, TARGET_STAGE, HK)
    archived_failed = selection_store._verify_run(TRADE_DATE, TARGET_STAGE, HK, failed_target_start["selection_run_id"])["envelope"]
    if (archived_failed.get("selection_status") != "CANNOT_CONFIRM" or archived_failed.get("rows") != []
            or selected.get("run_id") == failed_target_start["selection_run_id"]):
        raise AssertionError("failed source selection was not preserved as an immutable prior run")
    selected_evidence = set(selected.get("source_evidence") or ())
    rows = selected.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AssertionError("original 09:30 selector produced no target-stage rows")
    required_evidence = {
        f"substitute_kind=HK_0930_0935_FOR_HK_0925",
        f"source_stage_id={SOURCE_STAGE}",
        f"source_trade_date={TRADE_DATE}",
        f"source_raw_run_id={minute_entry['run_id']}",
        f"source_raw_artifact_sha256={EXPECTED_RAW_SHA}",
        f"source_manifest_sha256={EXPECTED_MANIFEST_SHA}",
        f"source_receipt_sha256={EXPECTED_RECEIPT_SHA}",
        f"source_last_bar_time=2026-09-24 09:35:00",
        "source_manifest_temporal_cutoff_safe=false",
        "target_stage_temporal_cutoff_safe=false",
        f"d1_pool_role=HK_CONNECT_D1_TOP100",
        f"d1_pool_sha256={EXPECTED_D1_SHA}",
        "d1_pool_count=100",
        "selection_mode=BACKFILL",
    }
    if not required_evidence.issubset(selected_evidence):
        raise AssertionError(f"selection is missing required source lineage: {required_evidence - selected_evidence}")
    if (f"prior_0925_selection_run_id={failed_target_start['selection_run_id']}" not in selected_evidence
            or "prior_0925_selection_selection_status=CANNOT_CONFIRM" not in selected_evidence):
        raise AssertionError("substitute did not retain the failed 09:25 slot provenance")
    if selected.get("trade_date") != TRADE_DATE or selected.get("stage_id") != TARGET_STAGE or selected.get("selection_status") != "PARTIAL_WITH_ROWS":
        raise AssertionError("selected envelope date/stage/partial status does not match the contract")
    if selected.get("requested_rows") != 100 or selected.get("source_rows") != 98 or selected.get("missing_symbols") != ["HK.02632", "HK.03355"]:
        raise AssertionError("selected envelope did not preserve the 98/100 source coverage")
    if any(row.get("trade_date") != TRADE_DATE or row.get("stage_id") != TARGET_STAGE
           or row.get("formal_eligible") is not False or row.get("action_level") != "NO_BUY"
           or row.get("source_temporal_cutoff_safe") is not False
           or row.get("target_stage_temporal_cutoff_safe") is not False
           or row.get("d1_pool_sha256") != EXPECTED_D1_SHA
           for row in rows):
        raise AssertionError("one or more substituted rows changed date, D-1, cutoff, or research-only status")

    selection_latest_path = positive_root / "selection/selection_latest.json"
    selection_latest_sha = _sha(selection_latest_path)
    first_selection_run = selected.get("run_id")
    second_node = _run_node(positive_config, settled_stage_receipt)
    repeat = second_node.get("hk_0925_automatic_substitute")
    selected_after_repeat = selection_store.read_verified(TRADE_DATE, TARGET_STAGE, HK)
    if (not isinstance(repeat, dict) or repeat.get("status") != "NOOP_ALREADY_VERIFIED"
            or repeat.get("write_performed") is not False
            or selected_after_repeat.get("run_id") != first_selection_run
            or _sha(selection_latest_path) != selection_latest_sha):
        raise AssertionError(f"repeat automatic trigger was not idempotent: {repeat!r}")

    auction_config = _scenario_config(config, auction_root)
    _assert_no_target_selection_or_receipt(auction_root / "selection", auction_root / "receipts")
    auction_raw_latest = auction_root / "raw/latest.json"
    before_auction_raw_sha = _sha(auction_raw_latest)
    auction_node = _run_node(auction_config, settled_stage_receipt)
    auction_outcome = auction_node.get("hk_0925_automatic_substitute")
    if (not isinstance(auction_outcome, dict)
            or auction_outcome.get("status") != "SKIPPED_AUCTION_PRESENT"
            or auction_outcome.get("source_raw_run_id") != auction_entry.get("run_id")
            or _sha(auction_raw_latest) != before_auction_raw_sha
            or (auction_root / "selection/selection_latest.json").exists()):
        raise AssertionError(f"verified auction input did not win without mutation: {auction_outcome!r}")

    missing_config = _scenario_config(config, missing_minute_root)
    _assert_missing_target_raw(missing_minute_root / "raw")
    _assert_no_target_selection_or_receipt(missing_minute_root / "selection", missing_minute_root / "receipts")
    missing_node = _run_node(missing_config, settled_stage_receipt)
    missing_outcome = missing_node.get("hk_0925_automatic_substitute")
    if (not isinstance(missing_outcome, dict)
            or missing_outcome.get("status") != "WAITING_MINUTE_DATA"
            or missing_outcome.get("first_failed_layer") != "HK_0930_0935_MINUTE_RAW_MISSING"
            or missing_outcome.get("write_performed") is not False):
        raise AssertionError(f"missing minute source did not wait specifically: {missing_outcome!r}")

    output = {
        "schema_version": "e7.hk_0925_automatic_entry_replay.v1",
        "result": "PASS",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": TRADE_DATE,
        "entry": {
            "function": "ops.run_stage_center_nodes.run_nodes",
            "explicit_node": SOURCE_STAGE,
            "evaluated_at": EVALUATED_AT.isoformat(),
            "source_stage_dispatch": "replayed settled same-date receipt; collector suppressed",
            "integration_hook": "ops._run_stage_center_nodes_parts.node_entry._run_nodes_body post-dispatch 0930 branch",
            "source_receipt_path": str(settled_receipt_path),
            "source_receipt_status": settled_stage_receipt.get("status"),
        },
        "isolated_fixture": {
            "root": str(replay_root),
            "target_start_state": "positive path has a synthetic verified zero-row CANNOT_CONFIRM selection plus same-date retry-exhausted receipt and no 0925 raw; negative paths omit the target selection/receipt",
            "synthetic_failed_slot_fixture": failed_target_start,
            "no_active_store_writes": True,
            "stage_dispatch_is_mocked": True,
        },
        "verified_active_inputs": {
            "raw_root_read_only": str(active_raw),
            "minute": {
                "run_id": minute_entry["run_id"],
                "status": minute_entry["status"],
                "artifact_sha256": minute_entry["artifact_sha256"],
                "manifest_sha256": minute_entry["manifest_sha256"],
                "receipt_sha256": minute_entry["receipt_sha256"],
                "requested_rows": minute_entry["requested_rows"],
                "row_count": minute_entry["row_count"],
                "missing_symbols": minute_entry["missing_symbols"],
                "window": minute_entry["window"],
                "cutoff_at": minute_entry["cutoff_at"],
                "captured_at_evidence": [item for item in minute_entry.get("source_evidence", []) if item.startswith(("active_snapshot_captured_at=", "active_snapshot_temporal_cutoff_safe=", "active_snapshot_execution_status="))],
            },
            "d1_pool": {
                "status": binding.status,
                "role": binding.role,
                "trade_date": binding.trade_date,
                "count": len(set(binding.codes)),
                "sha256": binding.sha256,
            },
            "auction": {
                "run_id": auction_entry["run_id"],
                "status": auction_entry["status"],
                "artifact_sha256": auction_entry["artifact_sha256"],
            },
        },
        "scenarios": {
            "missing_0925_with_minute_available": {
                "initial_failed_selection_run_id": failed_target_start["selection_run_id"],
                "automatic_status": automatic["status"],
                "write_performed": automatic["write_performed"],
                "selection_status": selected["selection_status"],
                "selection_run_id": selected["run_id"],
                "selected_rows": len(rows),
                "requested_rows": selected["requested_rows"],
                "source_rows": selected["source_rows"],
                "missing_symbols": selected["missing_symbols"],
                "source_last_bar_time": "2026-09-24 09:35:00",
                "source_cutoff_safe": False,
                "target_cutoff_safe": False,
                "formal_eligible": False,
                "action_level": "NO_BUY",
                "repeat_status": repeat["status"],
                "selection_latest_unchanged_on_repeat": _sha(selection_latest_path) == selection_latest_sha,
                "raw_latest_unchanged": _sha(positive_root / "raw/latest.json") == before_positive_raw_sha,
                "prior_failed_selection_archived_and_verified": archived_failed.get("run_id") == failed_target_start["selection_run_id"],
            },
            "verified_0925_auction_present": {
                "automatic_status": auction_outcome["status"],
                "auction_run_id": auction_outcome["source_raw_run_id"],
                "raw_latest_unchanged": _sha(auction_raw_latest) == before_auction_raw_sha,
                "selection_write_absent": not (auction_root / "selection/latest.json").exists(),
            },
            "minute_source_missing": {
                "automatic_status": missing_outcome["status"],
                "first_failed_layer": missing_outcome["first_failed_layer"],
                "write_performed": missing_outcome["write_performed"],
            },
        },
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "fixture_raw_latest_entries": {
            "missing_target_with_minute": sorted(positive_entries),
            "auction_present": sorted(auction_entries),
        },
    }
    receipt_path = E7_ROOT / "receipts/E7_AUTO_ENTRY_REPLAY_R3_20261011.json"
    if receipt_path.exists():
        raise FileExistsError(f"refusing to overwrite replay receipt: {receipt_path}")
    _write_json(receipt_path, output)
    print(json.dumps({"receipt": str(receipt_path), "result": output["result"], "scenarios": output["scenarios"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
