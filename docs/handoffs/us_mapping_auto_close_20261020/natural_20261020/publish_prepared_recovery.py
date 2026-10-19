"""Check frozen recovery; publish only after controller authorizes --publish."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import sys

HERE = Path(__file__).resolve().parent
WT = HERE.parents[3]
sys.path.insert(0, str(WT))
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-prepared-sha", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    path = HERE / "WIRE_REPAIR_PREPARED.json"
    frozen = path.read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == args.expected_prepared_sha
    prepared = json.loads(frozen)
    for relative, digest in prepared["source_test_sha256"].items():
        assert sha(WT / relative) == digest
    assert sha(__file__) == prepared["publish_helper_sha256"]
    candidate_raw = (HERE / "WIRE_CANDIDATE.json").read_bytes()
    assert hashlib.sha256(candidate_raw).hexdigest() == prepared["candidate_receipt_sha256"]
    candidate = json.loads(candidate_raw)
    assert candidate["candidate"] == prepared["candidate"]
    assert candidate["manifest_sha256"] == prepared["candidate_manifest_sha256"]
    assert candidate["original_plist_sha256"] == prepared["original_plist_sha256"]
    assert candidate["proposed_plist_sha256"] == prepared["proposed_plist_sha256"]
    for relative, digest in candidate["source_test_sha256"].items():
        if not relative.startswith("tests/"):
            assert digest == prepared["source_test_sha256"][relative]
    assert sha(Path(candidate["candidate"]) / "release-manifest.json") == candidate["manifest_sha256"]
    recovery_raw = (HERE / "WIRE_RECOVERY_PREPARED.json").read_bytes()
    assert hashlib.sha256(recovery_raw).hexdigest() == prepared["recovery_receipt_sha256"]
    recovery = json.loads(recovery_raw)
    assert recovery["expected_old_cas_sha256"] == prepared["expected_old_cas_sha256"]
    assert recovery["payload_sha256"] == prepared["recovery_payload_sha256"]
    assert recovery["predicted_receipt_sha256"] == prepared["predicted_receipt_sha256"]
    source = HERE / recovery["payload_relative"]
    assert sha(source) == prepared["recovery_payload_sha256"] == recovery["payload_sha256"]
    payload = json.loads(source.read_text())
    from infrastructure.data_store import _sha256
    from infrastructure.research_peripheral_store import ResearchPeripheralStore, validate_research_peripheral
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from infrastructure.interprocess_lock import owned_interprocess_lock

    validate_research_peripheral(payload, expected_trade_date="20261020", expected_source="external_finance")
    provenance = recovery["provenance"]
    assert provenance["identity"] == "SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY"
    assert provenance["captured_at"] == payload["market_snapshot"]["captured_at"]
    assert datetime.fromisoformat(provenance["processing_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    failed_paths = {
        "0415": BASE / "state/dispatcher/receipts/live/20261020/0415/b69405c9b5214af7a24529ff6e6a9c36.dispatch-receipt.json",
        "0515": BASE / "state/dispatcher/receipts/live/20261020/0515/2f16d9f8bc6e4d7088dea33a05d1035e.dispatch-receipt.json",
    }
    failed_before = {slot: sha(p) for slot, p in failed_paths.items()}
    assert failed_before == prepared["failed_receipts_raw_sha256"]
    assert ExecutionLedger(BASE / "state/dispatcher").verify_receipt_chain("20261020", mode="LIVE")[0]
    store = ResearchPeripheralStore(BASE / "state/data")
    current = store.read_exact("20261020", "external_finance")
    current_sha = _sha256(current)
    expected_old = recovery["expected_old_cas_sha256"]
    expected_new = recovery["payload_sha256"]
    assert current_sha in {expected_old, expected_new}, "owner drift; do not overwrite"
    if not args.publish:
        print(json.dumps(dict(state="CHECKED_NOT_PUBLISHED", current_payload_sha256=current_sha,
            expected_old_sha256=expected_old, prepared_payload_sha256=expected_new)))
        return
    plist = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v4.us-market-digest.plist")
    assert sha(plist) == candidate["proposed_plist_sha256"], "approved producer not bound"
    assert plistlib.loads(plist.read_bytes())["WorkingDirectory"] == candidate["candidate"] + "/app"
    with owned_interprocess_lock(BASE / "state/data/.locks/us-market-20261020.lock",
                                 timeout_seconds=30, timeout_message="US_CAPTURE_OWNER_BUSY"):
        # Existing CAS and owner lock preserve history and parallel manifest entries.
        current_sha = _sha256(store.read_exact("20261020", "external_finance"))
        if current_sha == expected_new:
            result = dict(replaced=False, payload_sha256=expected_new, state="ALREADY_APPLIED")
        else:
            assert current_sha == expected_old, "owner drift under lock"
            result = store.replace(payload, expected_sha256=expected_old,
                reason="SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY; original0415/0515 FAILED retained")
        after = store.read_exact("20261020", "external_finance")
        assert _sha256(after) == expected_new
        receipt = BASE / "state/data/receipts/research/peripherals/20261020/external_finance.json"
        assert sha(receipt) == recovery["predicted_receipt_sha256"]
        assert {slot: sha(p) for slot, p in failed_paths.items()} == failed_before
    record = dict(state="PROCESSING_RECOVERY_PUBLISHED", executed_at=datetime.now(timezone.utc).isoformat(),
        result=result, payload_sha256=expected_new, previous_payload_sha256=expected_old,
        receipt_sha256=sha(receipt), captured_at=provenance["captured_at"],
        processing_at=provenance["processing_at"], failed_receipts_unchanged=True,
        provider_calls=0, business_posts=0, natural0415="FAIL_RETAINED", natural0515="FAIL_RETAINED",
        behavior_verification="PENDING_EXISTING_SCHEDULER_API_UI_AND_INDEPENDENT_REVIEW")
    output = HERE / "WIRE_RECOVERY_PUBLICATION.json"
    if not output.exists():
        output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
