from __future__ import annotations

from pathlib import Path
import sys


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))
import activate_runtime_candidate as activation  # noqa: E402


def test_detach_confirmation_failure_still_restores_preimage_and_skips_bootstrap() -> None:
    original = b"original plist bytes"
    candidate = b"candidate plist bytes"
    current = {"value": candidate}
    events: list[str] = []

    def detach() -> None:
        events.append("detach")
        raise RuntimeError("SERVICE_DETACH_NOT_CONFIRMED")

    def install(raw: bytes, mode: int) -> None:
        assert mode == 0o600
        events.append("restore")
        current["value"] = raw

    def probe() -> dict[str, object]:
        events.append("probe")
        return {"status": "UNKNOWN", "reason": "label and listener identity not confirmed"}

    def bootstrap(_target: str) -> None:
        events.append("bootstrap")
        raise AssertionError("must not bootstrap when process identity is unknown")

    result = activation.rollback_after_failure(
        original=original, mode=0o600, target="gui/501", label="com.lexi.v35.api-only",
        candidate_selected=True, prior_service_detached=False, detach=detach,
        install=install, bootstrap=bootstrap, probe=probe,
        read_plist=lambda: current["value"],
    )

    assert events == ["detach", "restore", "probe"]
    assert current["value"] == original
    assert result["detach"]["status"] == "FAIL"
    assert "SERVICE_DETACH_NOT_CONFIRMED" in result["detach"]["error"]
    assert result["original_plist_restore"]["status"] == "PASS"
    assert result["process_identity_after_detach"]["status"] == "UNKNOWN"
    assert result["prior_service_bootstrap"]["status"] == "SKIPPED_PROCESS_IDENTITY_UNCONFIRMED"
    assert result["status"] == "ORIGINAL_PLIST_RESTORED_SERVICE_IDENTITY_UNKNOWN"
    assert result["status"] != "PASS"


def test_successful_rollback_restores_then_bootstraps_once_after_detach_proof() -> None:
    original = b"original plist bytes"
    candidate = b"candidate plist bytes"
    current = {"value": candidate}
    events: list[str] = []

    def detach() -> dict[str, object]:
        events.append("detach")
        return {"old_pids_exited": True, "label_absent": True}

    def install(raw: bytes, mode: int) -> None:
        assert mode == 0o600
        events.append("restore")
        current["value"] = raw

    def probe() -> dict[str, object]:
        events.append("probe")
        return {"status": "KNOWN", "label_present": False,
                "launchd_pid": None, "port_listener_pids": []}

    def bootstrap(target: str) -> dict[str, object]:
        assert target == "gui/501"
        events.append("bootstrap")
        return {"exit_code": 0}

    result = activation.rollback_after_failure(
        original=original, mode=0o600, target="gui/501", label="com.lexi.v35.api-only",
        candidate_selected=True, prior_service_detached=False, detach=detach,
        install=install, bootstrap=bootstrap, probe=probe,
        read_plist=lambda: current["value"],
    )

    assert events == ["detach", "restore", "probe", "bootstrap"]
    assert current["value"] == original
    assert result["original_plist_restore"]["status"] == "PASS"
    assert result["prior_service_bootstrap"]["status"] == "PASS"
    assert result["status"] == "ROLLED_BACK_PRIOR_SERVICE_RESTARTED"


def test_restore_failure_never_bootstraps_prior_service() -> None:
    original = b"original plist bytes"
    events: list[str] = []

    def detach() -> dict[str, object]:
        events.append("detach")
        return {"old_pids_exited": True, "label_absent": True}

    def install(_raw: bytes, _mode: int) -> None:
        events.append("restore")
        raise OSError("atomic restore failed")

    def probe() -> dict[str, object]:
        events.append("probe")
        return {"status": "KNOWN", "label_present": False,
                "launchd_pid": None, "port_listener_pids": []}

    def bootstrap(_target: str) -> None:
        events.append("bootstrap")
        raise AssertionError("must not start with an unverified active plist")

    result = activation.rollback_after_failure(
        original=original, mode=0o600, target="gui/501", label="com.lexi.v35.api-only",
        candidate_selected=True, prior_service_detached=False, detach=detach,
        install=install, bootstrap=bootstrap, probe=probe,
        read_plist=lambda: b"candidate plist bytes",
    )

    assert events == ["detach", "restore", "probe"]
    assert result["original_plist_restore"]["status"] == "FAIL"
    assert "atomic restore failed" in result["original_plist_restore"]["error"]
    assert result["prior_service_bootstrap"]["status"] == "SKIPPED_PLIST_RESTORE_FAILED"
    assert result["status"] == "ROLLBACK_INCOMPLETE"
