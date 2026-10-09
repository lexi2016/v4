from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path


ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PUBLISHER = ROOT / "tools/api_only_cutover_issue32_r4.py"
RECEIPT = Path(os.environ.get(
    "ISSUE32_TRANSITION_RECEIPT_PATH",
    str(ROOT / "evidence/api_launchctl_transition_regression_issue32_r1.json"),
))


def load_module():
    spec = importlib.util.spec_from_file_location("issue32_cutover_transition_test", PUBLISHER)
    if spec is None or spec.loader is None:
        raise AssertionError("PUBLISHER_MODULE_UNLOADABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_raises(fn, marker: str) -> None:
    try:
        fn()
    except ValueError as error:
        if marker not in str(error):
            raise AssertionError(f"EXPECTED_{marker}_GOT_{error}") from error
    else:
        raise AssertionError(f"EXPECTED_FAILURE:{marker}")


def main() -> None:
    if RECEIPT.exists():
        raise SystemExit("REFUSE_EXISTING_TRANSITION_TEST_RECEIPT")
    module = load_module()
    old_identity = {
        "state": "running", "pid": "101",
        "V35_APP_ROOT": "/old/app", "V35_RELEASE_ID": "old-release",
        "V35_RELEASE_MANIFEST_SHA256": "a" * 64,
    }
    candidate_identity = {
        "state": "running", "pid": "202",
        "V35_APP_ROOT": "/candidate/app", "V35_RELEASE_ID": "candidate-release",
        "V35_RELEASE_MANIFEST_SHA256": "b" * 64,
    }
    results: list[dict[str, object]] = []

    sequence = iter([
        {"state": "LOADED_UNVERIFIED", "identity": None, "error": "API_ONLY_LAUNCH_AGENT_NOT_RUNNING"},
        {"state": "NOT_LOADED", "identity": None},
    ])
    module._observe_loaded = lambda: next(sequence)
    module.time.sleep = lambda _seconds: None
    unloaded = module._wait_for_unloaded([old_identity], timeout_s=2)
    assert unloaded["wait_status"] == "ABSENT_CONFIRMED" and unloaded["poll_count"] == 2
    results.append({"case": "bootout_async_unverified_to_absent", "status": "PASS", "poll_count": unloaded["poll_count"]})

    for label, expected_identity in (("preimage", old_identity), ("candidate", candidate_identity)):
        sequence = iter([
            {"state": "LOADED", "identity": expected_identity},
            {"state": "NOT_LOADED", "identity": None},
        ])
        module._observe_loaded = lambda: next(sequence)
        unloaded = module._wait_for_unloaded([expected_identity], timeout_s=2)
        assert unloaded["wait_status"] == "ABSENT_CONFIRMED" and unloaded["poll_count"] == 2
        results.append({
            "case": f"bootout_known_{label}_identity_continues_until_absent",
            "status": "PASS",
            "poll_count": unloaded["poll_count"],
        })

    sequence = iter([
        {"state": "LOADED_UNVERIFIED", "identity": None},
        {"state": "LOADED", "identity": old_identity},
    ])
    module._observe_loaded = lambda: next(sequence)
    observed, role = module._wait_for_recovery_transition({
        "before": {"loaded_identity": old_identity},
        "target": {
            "app_root": candidate_identity["V35_APP_ROOT"],
            "release_id": candidate_identity["V35_RELEASE_ID"],
            "release_manifest_sha256": candidate_identity["V35_RELEASE_MANIFEST_SHA256"],
        },
    }, timeout_s=2)
    assert observed["identity"] == old_identity and role == "original"
    results.append({"case": "transition_resolves_to_recorded_preimage", "status": "PASS", "resolved_role": role})

    module._observe_loaded = lambda: {"state": "LOADED", "identity": {
        **candidate_identity, "V35_RELEASE_ID": "unrelated-release",
    }}
    assert_raises(lambda: module._wait_for_unloaded([old_identity], timeout_s=2),
                  "API_ONLY_BOOTOUT_REFUSES_UNKNOWN_LOADED_IDENTITY")
    results.append({"case": "unknown_loaded_identity_rejected", "status": "PASS"})

    module._observe_loaded = lambda: {"state": "UNKNOWN", "identity": None, "error": "print failed"}
    assert_raises(lambda: module._wait_for_unloaded([old_identity], timeout_s=2),
                  "API_ONLY_BOOTOUT_STATE_UNVERIFIED")
    results.append({"case": "unknown_launchctl_state_rejected", "status": "PASS"})

    tick = [0.0]

    def monotonic():
        tick[0] += 0.25
        return tick[0]

    module.time.monotonic = monotonic
    module._observe_loaded = lambda: {
        "state": "LOADED_UNVERIFIED", "identity": None,
        "error": "API_ONLY_LAUNCH_AGENT_NOT_RUNNING",
    }
    assert_raises(lambda: module._wait_for_unloaded([old_identity], timeout_s=1),
                  "API_ONLY_BOOTOUT_ABSENCE_TIMEOUT")
    results.append({"case": "persistent_transition_times_out_closed", "status": "PASS"})

    with tempfile.TemporaryDirectory(prefix=".issue32-api-transition-", dir=ROOT) as tmp:
        active_plist = Path(tmp) / "active.plist"
        active_plist.write_bytes(b"recorded-preimage")
        module.ACTIVE_API_PLIST = active_plist
        before_sha = hashlib.sha256(active_plist.read_bytes()).hexdigest()
        plan = {
            "before": {
                "active_api_plist_sha256": before_sha,
                "loaded_identity": old_identity,
            },
            "target": {
                "app_root": candidate_identity["V35_APP_ROOT"],
                "release_id": candidate_identity["V35_RELEASE_ID"],
                "release_manifest_sha256": candidate_identity["V35_RELEASE_MANIFEST_SHA256"],
            },
        }
        sequence = iter([
            {"state": "LOADED_UNVERIFIED", "identity": None},
            {"state": "NOT_LOADED", "identity": None},
        ])
        module._observe_loaded = lambda: next(sequence)
        current_sha, observed, role = module._recovery_state(
            plan, "c" * 64, expected_current_sha=before_sha, wait_for_transition=True,
        )
        assert current_sha == before_sha and role == "unloaded"
        assert observed["transition_wait_status"] == "ABSENT_CONFIRMED"
        results.append({"case": "receipt_recovery_waits_for_absence_and_rechecks_pointer_cas", "status": "PASS", "resolved_role": role})

        active_plist.write_bytes(b"recorded-preimage")

        drift_observations = [0]

        def drift_during_observation():
            drift_observations[0] += 1
            if drift_observations[0] == 1:
                return {"state": "LOADED_UNVERIFIED", "identity": None}
            active_plist.write_bytes(b"unexpected-pointer-drift")
            return {"state": "NOT_LOADED", "identity": None}

        module._observe_loaded = drift_during_observation
        assert_raises(lambda: module._recovery_state(
            plan, "c" * 64, expected_current_sha=before_sha, wait_for_transition=True,
        ), "API_ONLY_ROLLBACK_ACTIVE_PLIST_CHANGED_DURING_RUNTIME_WAIT")
        results.append({"case": "pointer_drift_during_wait_refused", "status": "PASS"})

    result = {
        "schema_version": "v4.issue32.api_launchctl_transition_regression.v1",
        "status": "PASS_BOUNDED_BOOTOUT_TRANSITION_AND_FAIL_CLOSED_RECOVERY",
        "publisher_path": str(PUBLISHER),
        "publisher_sha256": hashlib.sha256(PUBLISHER.read_bytes()).hexdigest(),
        "test_script_path": str(Path(__file__).resolve()),
        "test_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "case_count": len(results),
        "cases": results,
        "live_active_api_plist_read_or_written": False,
        "isolated_temp_pointer_used": True,
        "launchctl_called": False,
        "service_started_or_stopped": False,
        "pointer_or_scheduler_mutation": False,
    }
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with RECEIPT.open("xb") as handle:
        handle.write(raw)
        handle.flush()
    result["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
