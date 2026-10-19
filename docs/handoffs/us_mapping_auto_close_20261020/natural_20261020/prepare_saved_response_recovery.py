"""Prepare a processing recovery locally. No network, POST or owner write."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WT = HERE.parents[3]
sys.path.insert(0, str(WT))
LOCAL = HERE / "local_only"
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
RAW_SHA = "9a2de44927e53cb8cc12d81f9ebf1e87a4bd18504299ca75c61f048e6e7b5457"
OLD_SHA = "a3de0bc966c1a2422ce38e10dc1484d1cf64410765f0a552502e836e81d15ef3"
FAILED_RAW_SHA = "e6e220d39998c46ebaecaed22f5d569218206a03642352a40a6cda7f0aa52df1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    from infrastructure.data_store import _sha256
    from infrastructure.research_peripheral_store import (
        ResearchPeripheralStore, validate_research_peripheral, _validate_us_session_captures)
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from infrastructure.scheduling._executor_registry_parts.us_digest import parse_us_market_result
    from ops.us_market_digest import (build_us_market_snapshot, us_capture_window,
        us_post_close_recovery_window, LATE_POST_CLOSE_CAPTURE_MODE, LATE_POST_CLOSE_CAPTURE_REASON)
    from v4.manager_workbench.inputs.us_mapping_close_scope import digest, bind_scheduled_scope

    destination = LOCAL / "wire-recovery-payload.json"
    receipt_path = HERE / "WIRE_RECOVERY_PREPARED.json"
    assert not destination.exists() and not receipt_path.exists(), "recovery already prepared; do not overwrite"
    candidate = json.loads((HERE / "WIRE_CANDIDATE.json").read_text())
    for path, expected in candidate["source_test_sha256"].items():
        assert sha(WT / path) == expected
    raw_path = LOCAL / f"us-quote-wire-20261019-{RAW_SHA}.bin"
    assert sha(raw_path) == RAW_SHA
    diagnostic = json.loads(raw_path.with_suffix(".json").read_text())
    assert diagnostic["source_response_sha256"] == RAW_SHA
    assert diagnostic["us_session_date"] == "20261019"
    failed_path = BASE / "state/dispatcher/receipts/live/20261020/0515/2f16d9f8bc6e4d7088dea33a05d1035e.dispatch-receipt.json"
    assert sha(failed_path) == FAILED_RAW_SHA
    failed = json.loads(failed_path.read_text())
    ledger = ExecutionLedger(BASE / "state/dispatcher")
    assert ledger.verify_receipt_chain("20261020", mode="LIVE")[0]
    assert failed["status"] == "FAILED" and failed["slot"] == "0515"
    assert failed["release_manifest_sha256"] == candidate["parent_manifest_sha256"]
    result = failed["workload_results"][0]
    assert result["reason"] == "US_MARKET_CAPTURE_FAILED" and result["exit_code"] == 2
    terminal = parse_us_market_result(result["stdout"])
    assert terminal["status"] == "CANNOT_CONFIRM"
    assert terminal["reason"] == "ValueError:market_snapshot provider session times mismatch"
    assert terminal["source_session_date"] == "20261019"
    assert terminal["target_trade_date"] == "20261020"
    assert terminal["recovery_mode"] == "LATE_POST_CLOSE_CAPTURE"
    observed = datetime.fromisoformat(terminal["recovery_executed_at"])
    finished = datetime.fromisoformat(failed["finished_at"].replace("Z", "+00:00"))
    assert observed.timestamp() <= raw_path.stat().st_mtime <= finished.timestamp()
    captured = observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    processed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert observed < datetime.fromisoformat(processed.replace("Z", "+00:00"))
    store = ResearchPeripheralStore(BASE / "state/data")
    old = store.read_exact("20261020", "external_finance")
    assert _sha256(old) == OLD_SHA
    os.environ["V4_US_MAPPING_CLOSE_SCOPE_PATH"] = str(HERE.parent / "quote_scope.json")
    os.environ.pop("V4_US_MAPPING_WIRE_DIAGNOSTIC_DIR", None)
    raw = raw_path.read_bytes()
    snapshot = build_us_market_snapshot("20261019", capture_phase="POST_CLOSE", captured_at=captured,
        universe_contract=old["market_snapshot"]["universe_contract"], fetch_quotes=lambda *_: raw)
    assert snapshot["status"] == "READY" and snapshot["available_symbol_count"] == 48
    assert snapshot["scheduled_quote_scope"]["available_symbol_count"] == 488
    # Board/RSS observations unavailable from05:15 are retained from04:15,
    # never passed off as newly fetched or reconstructed news/board facts.
    snapshot["futu_board_snapshot"] = deepcopy(old["market_snapshot"]["futu_board_snapshot"])
    recovery_id = "SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY:" + RAW_SHA[:24]
    run_id = recovery_id + ":processed=" + processed
    natural_start, natural_end = us_capture_window("20261019", "POST_CLOSE")
    allowed_start, allowed_end = us_post_close_recovery_window("20261019")
    capture = dict(us_session_date="20261019", capture_phase="POST_CLOSE", session_timezone="America/New_York",
        capture_window_start=natural_start.isoformat(), capture_window_end=natural_end.isoformat(),
        capture_id=recovery_id, run_id=run_id, captured_at=captured,
        capture_origin="ORIGINAL_TIME_CAPTURE", original_time_capture=True,
        late=True, capture_mode=LATE_POST_CLOSE_CAPTURE_MODE, reason=LATE_POST_CLOSE_CAPTURE_REASON,
        capture_reason=LATE_POST_CLOSE_CAPTURE_REASON, natural_capture_window_start=natural_start.isoformat(),
        natural_capture_window_end=natural_end.isoformat(), allowed_recovery_window_start=allowed_start.isoformat(),
        allowed_recovery_window_end=allowed_end.isoformat(), quote_capture_status="ATTEMPTED",
        raw_item_count=0, item_count=0, rss_status="NOT_REPLAYED_RETAINED_FROM_0415",
        rss_item_count=0, rss_raw_item_count=0)
    # Read-time metadata validation, never a fresh-capture call with a fake now.
    _validate_us_session_captures([capture])
    provenance = dict(schema_version="v4.us_mapping.saved_response_processing_recovery.v1",
        identity="SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY", captured_at=captured, processing_at=processed,
        source_session="20261019", actual_capture_target="20261020", ledger_target=failed["target_date"],
        ledger_target_note="Inactive-slot wrapper next-HK date; collector explicitly targetsHK20. Original ledger unchanged.",
        raw_response_sha256=RAW_SHA, raw_response_bytes=len(raw), diagnostic_metadata_sha256=sha(raw_path.with_suffix(".json")),
        failed_dispatch_run_id=failed["run_id"], failed_dispatch_raw_sha256=FAILED_RAW_SHA,
        failed_dispatch_ledger_digest=failed["ledger_sha256"], failed_dispatch_finished_at=failed["finished_at"],
        source_runtime_manifest_sha256=failed["release_manifest_sha256"],
        processing_candidate_manifest_sha256=candidate["manifest_sha256"], previous_owner_payload_sha256=OLD_SHA,
        source_capture_outcome="FAILED_RETAINED", processing_outcome="DERIVED_FROM_SAVED_RESPONSE",
        retained_rss=dict(source_payload_sha256=OLD_SHA, captured_at=old["fetched_at"], newly_fetched=False),
        retained_board_snapshot=dict(source_payload_sha256=OLD_SHA,
            source_response_sha256=old["market_snapshot"]["source_response_sha256"], newly_fetched=False),
        provider_calls=0, business_posts=0, natural_verification="FAIL_RETAINED")
    capture["processing_recovery"] = provenance
    for field in ("late", "capture_mode", "reason", "capture_reason", "natural_capture_window_start",
                  "natural_capture_window_end", "allowed_recovery_window_start", "allowed_recovery_window_end"):
        snapshot[field] = capture[field]
    snapshot.update(capture_id=recovery_id, run_id=run_id, generated_at=processed, processing_recovery=provenance)
    supplemental = snapshot["scheduled_quote_scope"]
    supplemental["processing_recovery"] = provenance
    supplemental.pop("record_sha256")
    supplemental["record_sha256"] = digest(supplemental)
    payload = deepcopy(old)
    payload.update(fetched_at=captured, source_date_semantics="SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY",
        market_snapshot=snapshot, market_snapshot_status="READY")
    payload["us_session_captures"].append(capture)
    for field in ("late", "capture_mode", "reason", "capture_reason", "natural_capture_window_start",
                  "natural_capture_window_end", "allowed_recovery_window_start", "allowed_recovery_window_end"):
        payload[field] = capture[field]
    assert payload["details"] == old["details"] and payload["feed_receipts"] == old["feed_receipts"]
    assert payload["overview"] == old["overview"] and payload["items"] == old["items"]
    assert payload["us_session_captures"][:-1] == old["us_session_captures"]
    validate_research_peripheral(payload, expected_trade_date="20261020", expected_source="external_finance")
    expected_receipt = store._receipt(payload, _sha256(payload))
    bound = bind_scheduled_scope(snapshot, payload, source_session="20261019", cutoff=processed,
        payload_relative=store._relative("20261020", "external_finance"), payload_sha256=_sha256(payload),
        receipt_relative=store._receipt_relative("20261020", "external_finance"), receipt_sha256=_sha256(expected_receipt),
        manifest_sha256=sha(BASE / "state/data/research/peripherals/manifest.json"))
    assert bound["available_symbol_count"] == 488 and bound["late"] is True
    destination.write_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    assert sha(destination) == _sha256(payload)
    result = dict(state="RECOVERY_PREPARED_NOT_PUBLISHED", payload_relative=str(destination.relative_to(HERE)),
        payload_sha256=sha(destination), expected_old_cas_sha256=OLD_SHA,
        predicted_receipt_sha256=_sha256(expected_receipt), provenance=provenance,
        full_existing_validation="PASS", existing_scheduled_binding="PASS_PARTIAL488_OF547",
        original_rss_and_capture_rows_preserved=True, authoritative_data_writes=0,
        ledger_writes=0, provider_calls=0, business_posts=0,
        publish_command="Controller continuation only: existing ResearchPeripheralStore.replace(exact prepared payload, expected_sha256=old SHA, reason=SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY); no reprepare/no fake clock.")
    receipt_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "provenance"}, indent=2))


if __name__ == "__main__":
    main()
