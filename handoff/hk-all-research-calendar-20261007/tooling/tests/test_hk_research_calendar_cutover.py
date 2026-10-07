from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).with_name("hk_research_calendar_cutover.py")
SPEC = importlib.util.spec_from_file_location("hk_research_calendar_cutover_test", SCRIPT)
assert SPEC and SPEC.loader
cutover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover)


def test_api_candidate_plist_preserves_host_port_and_stage_selection_args(tmp_path: Path) -> None:
    old_app = tmp_path / "old-api" / "app"
    new_root = tmp_path / "new-api"
    original = {
        "Label": "com.lexi.v35.api-only",
        "WorkingDirectory": str(old_app),
        "ProgramArguments": [
            "/usr/bin/env",
            f"V35_APP_ROOT={old_app}",
            "V35_RELEASE_ID=old-api",
            f"PYTHONPATH={old_app / 'upstreams'}:{old_app}",
            f"V35_RELEASE_MANIFEST_PATH={old_app.parent / 'release-manifest.json'}",
            "V35_RELEASE_MANIFEST_SHA256=old-sha",
            "/runtime/python",
            "-B",
            "-m",
            "apps.api.v35_api.run",
            "--host",
            "127.0.0.1",
            "--port",
            "8873",
            "--stage-selection-root",
            "/state/stage/selection",
        ],
        "KeepAlive": True,
        "RunAtLoad": True,
    }
    updated = cutover._replace_plist_paths("api", original, old_app=old_app, new_root=new_root, manifest_sha="candidate-sha")
    assert updated["Label"] == original["Label"]
    assert updated["KeepAlive"] is True
    assert updated["RunAtLoad"] is True
    assert updated["WorkingDirectory"] == str(new_root / "app")
    assert updated["ProgramArguments"][10:] == original["ProgramArguments"][10:]
    assert updated["ProgramArguments"][3] == f"PYTHONPATH={new_root / 'app' / 'upstreams'}:{new_root / 'app'}"
    assert cutover.env_from_plist(updated)["V35_RELEASE_MANIFEST_SHA256"] == "candidate-sha"


def test_scheduler_candidate_plist_preserves_scheduler_environment_and_launcher(tmp_path: Path) -> None:
    old_app = tmp_path / "old-scheduler" / "app"
    new_root = tmp_path / "new-scheduler"
    original = {
        "Label": "com.lexi.v35.scheduler",
        "WorkingDirectory": str(old_app),
        "ProgramArguments": ["/bin/bash", str(old_app / "ops/launch_v35_macos_scheduler.sh")],
        "EnvironmentVariables": {
            "V35_APP_ROOT": str(old_app),
            "V35_RELEASE_ID": "old-scheduler",
            "V35_RELEASE_MANIFEST_PATH": str(old_app.parent / "release-manifest.json"),
            "V35_RELEASE_MANIFEST_SHA256": "old-sha",
            "V35_STAGE_CENTER_SELECTION_ROOT": "/state/stage/selection",
            "production_allowed": "false",
            "buy_gate_updated": "false",
            "orders_sent": "false",
        },
        "KeepAlive": {"SuccessfulExit": False},
    }
    updated = cutover._replace_plist_paths("scheduler", original, old_app=old_app, new_root=new_root, manifest_sha="candidate-sha")
    assert updated["Label"] == original["Label"]
    assert updated["ProgramArguments"][0] == "/bin/bash"
    assert updated["ProgramArguments"][1] == str(new_root / "app/ops/launch_v35_macos_scheduler.sh")
    assert updated["EnvironmentVariables"]["V35_STAGE_CENTER_SELECTION_ROOT"] == "/state/stage/selection"
    assert updated["EnvironmentVariables"]["production_allowed"] == "false"
    assert updated["KeepAlive"] == original["KeepAlive"]
    assert updated["EnvironmentVariables"]["V35_RELEASE_MANIFEST_SHA256"] == "candidate-sha"
    assert plistlib.loads(plistlib.dumps(updated)) == updated


def test_batch_apply_failure_rolls_attempted_services_back_in_reverse_order(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []

    class FakeBackend:
        GateError = RuntimeError
        CONFIRMATIONS = {"api": "api-confirm", "scheduler": "scheduler-confirm"}

        def verify_candidate(self, service: str) -> None:
            events.append(("verify_candidate", service))

        def verify_reviewer_receipt(self, service: str) -> None:
            events.append(("verify_review", service))

        def verify_frozen_active(self, service: str) -> None:
            events.append(("verify_active", service))

        def cmd_apply(self, args: SimpleNamespace) -> int:
            events.append(("apply", args.service))
            if args.service == "scheduler":
                raise RuntimeError("simulated scheduler startup failure")
            return 0

    def restore(_backend, service: str):
        events.append(("restore", service))
        return {"service": service, "state": "ROLLED_BACK_TO_FROZEN_BASELINE", "pid": 123, "service_action_performed": True}

    def receipt(_backend, **kwargs):
        events.append(("receipt", kwargs["status"]))
        return Path("/tmp/fake-batch-receipt.json")

    monkeypatch.setattr(cutover, "_restore_one_service", restore)
    monkeypatch.setattr(cutover, "_write_batch_receipt", receipt)
    with pytest.raises(RuntimeError, match="FAILED_ALL_BASELINES_RESTORED"):
        cutover.apply_batch(FakeBackend(), cutover.BATCH_APPLY_CONFIRMATION)
    assert [event for event in events if event[0] == "apply"] == [("apply", "api"), ("apply", "scheduler")]
    assert [event for event in events if event[0] == "restore"] == [("restore", "scheduler"), ("restore", "api")]
    assert events[-1] == ("receipt", "FAILED_ALL_BASELINES_RESTORED")


def test_batch_apply_requires_exact_confirmation_before_any_service_checks() -> None:
    class FakeBackend:
        GateError = RuntimeError

    with pytest.raises(RuntimeError, match="batch-specific activation confirmation"):
        cutover.apply_batch(FakeBackend(), "")


class _BatchBackend:
    GateError = RuntimeError
    CONFIRMATIONS = {"api": "api-confirm", "scheduler": "scheduler-confirm"}
    ROLLBACK_CONFIRMATIONS = {"api": "api-rollback", "scheduler": "scheduler-rollback"}

    def __init__(self, tmp_path: Path, states: dict[str, str]) -> None:
        self.states = states
        self.events: list[tuple[str, str]] = []
        self.receipts: list[dict[str, object]] = []
        self.tmp_path = tmp_path

    def verify_candidate(self, service: str) -> None:
        self.events.append(("verify_candidate", service))

    def verify_reviewer_receipt(self, service: str) -> None:
        self.events.append(("verify_review", service))

    def verify_frozen_active(self, service: str) -> tuple[dict[str, str], int]:
        self.events.append(("verify_active", service))
        assert self.states[service] == "baseline"
        return ({"state": "baseline"}, 100 + (service == "scheduler"))

    def service_identity(self, service: str) -> dict[str, str]:
        return {"base_active_plist_path": str(self.tmp_path / f"{service}.plist")}

    def operation_path(self, service: str, action: str) -> Path:
        return self.tmp_path / f"{service}_{action.lower()}.json"


def _install_fake_batch_helpers(monkeypatch: pytest.MonkeyPatch, backend: _BatchBackend) -> None:
    def active_state(_backend: _BatchBackend, service: str) -> tuple[str, int]:
        backend.events.append(("probe", service))
        return backend.states[service], 100 + (service == "scheduler")

    def restore(_backend: _BatchBackend, service: str) -> dict[str, object]:
        backend.events.append(("restore", service))
        was_candidate = backend.states[service] == "candidate"
        backend.states[service] = "baseline"
        return {
            "service": service,
            "state": "ROLLED_BACK_TO_FROZEN_BASELINE" if was_candidate else "BASELINE_PRESENT",
            "pid": 100 + (service == "scheduler"),
            "service_action_performed": was_candidate,
        }

    def write_receipt(_backend: _BatchBackend, **kwargs: object) -> Path:
        backend.events.append(("receipt", str(kwargs["status"])))
        backend.receipts.append(kwargs)
        return backend.tmp_path / "batch-receipt.json"

    monkeypatch.setattr(cutover, "_active_release_state", active_state)
    monkeypatch.setattr(cutover, "_restore_one_service", restore)
    monkeypatch.setattr(cutover, "_write_batch_receipt", write_receipt)


def test_batch_apply_api_success_scheduler_keyboard_interrupt_restores_both_and_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = _BatchBackend(tmp_path, {"api": "baseline", "scheduler": "baseline"})
    _install_fake_batch_helpers(monkeypatch, backend)

    def cmd_apply(args: SimpleNamespace) -> int:
        backend.events.append(("apply", args.service))
        if args.service == "api":
            backend.states["api"] = "candidate"
            return 0
        raise KeyboardInterrupt("simulated interrupt between services")

    backend.cmd_apply = cmd_apply  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="INTERRUPTED_ALL_BASELINES_RESTORED"):
        cutover.apply_batch(backend, cutover.BATCH_APPLY_CONFIRMATION)

    assert backend.states == {"api": "baseline", "scheduler": "baseline"}
    assert [event for event in backend.events if event[0] == "restore"] == [
        ("restore", "scheduler"), ("restore", "api")
    ]
    assert backend.receipts[0]["status"] == "INTERRUPTED_ALL_BASELINES_RESTORED"
    assert backend.receipts[0]["interrupted"] is True
    assert "KeyboardInterrupt" in str(backend.receipts[0]["error"])


def test_batch_apply_single_touched_service_system_exit_is_recovered_and_receipted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = _BatchBackend(tmp_path, {"api": "baseline", "scheduler": "baseline"})
    _install_fake_batch_helpers(monkeypatch, backend)

    def cmd_apply(args: SimpleNamespace) -> int:
        backend.events.append(("apply", args.service))
        backend.states[args.service] = "candidate"
        raise SystemExit(0)

    backend.cmd_apply = cmd_apply  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="INTERRUPTED_ALL_BASELINES_RESTORED"):
        cutover.apply_batch(backend, cutover.BATCH_APPLY_CONFIRMATION)

    assert backend.states == {"api": "baseline", "scheduler": "baseline"}
    assert [event for event in backend.events if event[0] == "restore"] == [("restore", "api")]
    assert backend.receipts[0]["attempted"] == ["api"]
    assert backend.receipts[0]["failure_type"] == "SystemExit"


def test_batch_apply_pre_touch_keyboard_interrupt_does_not_restore_or_write_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = _BatchBackend(tmp_path, {"api": "baseline", "scheduler": "baseline"})
    _install_fake_batch_helpers(monkeypatch, backend)

    def cmd_apply(_args: SimpleNamespace) -> int:
        raise KeyboardInterrupt("before service touch")

    backend.cmd_apply = cmd_apply  # type: ignore[attr-defined]
    with pytest.raises(KeyboardInterrupt, match="before service touch"):
        cutover.apply_batch(backend, cutover.BATCH_APPLY_CONFIRMATION)

    assert not [event for event in backend.events if event[0] == "restore"]
    assert not backend.receipts


def test_batch_rollback_interrupt_continues_other_service_retries_and_records_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = _BatchBackend(tmp_path, {"api": "candidate", "scheduler": "candidate"})
    _install_fake_batch_helpers(monkeypatch, backend)
    attempts = {"api": 0, "scheduler": 0}

    def restore(_backend: _BatchBackend, service: str) -> dict[str, object]:
        attempts[service] += 1
        backend.events.append(("restore", service))
        if service == "scheduler" and attempts[service] == 1:
            raise KeyboardInterrupt("simulated scheduler rollback interrupt")
        backend.states[service] = "baseline"
        return {
            "service": service,
            "state": "ROLLED_BACK_TO_FROZEN_BASELINE",
            "pid": 100 + (service == "scheduler"),
            "service_action_performed": True,
        }

    monkeypatch.setattr(cutover, "_restore_one_service", restore)
    with pytest.raises(RuntimeError, match="INTERRUPTED_ALL_BASELINES_RESTORED"):
        cutover.rollback_batch(backend, cutover.BATCH_ROLLBACK_CONFIRMATION)

    assert backend.states == {"api": "baseline", "scheduler": "baseline"}
    assert [event for event in backend.events if event[0] == "restore"] == [
        ("restore", "scheduler"), ("restore", "api"), ("restore", "scheduler")
    ]
    assert backend.receipts[0]["status"] == "INTERRUPTED_ALL_BASELINES_RESTORED"
    assert backend.receipts[0]["error"]
    assert "KeyboardInterrupt" in str(backend.receipts[0]["error"])


def test_restore_one_service_recovers_baseline_plist_when_launchd_label_is_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class LabelAbsent(Exception):
        pass

    base_bytes = b"frozen-baseline-plist\n"
    active_plist = tmp_path / "active.plist"
    active_plist.write_bytes(base_bytes)

    class FakeBackend:
        LaunchdLabelAbsent = LabelAbsent

        def __init__(self) -> None:
            self.rollback_calls: list[tuple[str, bool]] = []

        def service_identity(self, _service: str) -> dict[str, str]:
            return {
                "base_active_plist_path": str(active_plist),
                "base_active_plist_sha256": cutover.sha256(base_bytes),
                "candidate_plist_sha256": "candidate-sha",
                "base_active_pid": 77,
            }

        def launchctl_status(self, _service: str) -> tuple[str, int]:
            raise LabelAbsent("label is down")

        def rollback(self, service: str, *, reviewer: object, pid_before: int, automatic: bool) -> None:
            self.rollback_calls.append((service, automatic))
            assert reviewer is None
            assert pid_before == 77
            assert automatic is True

        def verify_frozen_active(self, _service: str) -> tuple[dict[str, str], int]:
            return ({"state": "baseline"}, 78)

    backend = FakeBackend()
    restored = cutover._restore_one_service(backend, "api")
    assert backend.rollback_calls == [("api", True)]
    assert restored["state"] == "ROLLED_BACK_TO_FROZEN_BASELINE"
    assert restored["service_action_performed"] is True


def test_restore_one_service_recovers_real_atomic_claim_after_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_bytes = b"frozen baseline plist bytes"
    candidate_bytes = b"candidate plist bytes"
    active_plist = tmp_path / "api.plist"
    active_plist.write_bytes(baseline_bytes)
    helper = cutover.load_backend()
    original_link = helper.os.link
    link_attempts: list[tuple[str, str]] = []

    def interrupt_install(source, destination, *args, **kwargs) -> None:
        link_attempts.append((str(source), str(destination)))
        if Path(source).suffix == ".tmp" and Path(destination) == active_plist:
            raise KeyboardInterrupt("injected after target rename and before install link")
        original_link(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(helper.os, "link", interrupt_install)
        with pytest.raises(KeyboardInterrupt, match="after target rename"):
            helper.atomic_write_no_clobber(
                "api",
                active_plist,
                candidate_bytes,
                expected_current_sha256=cutover.sha256(baseline_bytes),
                phase="TEST_APPLY_INSTALL",
            )

    assert not active_plist.exists()
    assert len(link_attempts) == 1
    claim_dirs = list(tmp_path.glob(f".{active_plist.name}.claim-*"))
    assert len(claim_dirs) == 1
    claim_path = claim_dirs[0] / "before.plist"
    assert claim_path.read_bytes() == baseline_bytes
    assert not list(tmp_path.glob(f".{active_plist.name}.*.tmp"))

    class LabelAbsent(Exception):
        pass

    class FakeBackend:
        GateError = RuntimeError
        RuntimeIdentityDrift = RuntimeError
        LaunchdLabelAbsent = LabelAbsent

        def __init__(self) -> None:
            self.rollback_calls: list[tuple[str, bool]] = []
            self.status_calls = 0

        def service_identity(self, _service: str) -> dict[str, str]:
            return {
                "base_active_plist_path": str(active_plist),
                "base_active_plist_sha256": cutover.sha256(baseline_bytes),
                "candidate_plist_sha256": cutover.sha256(candidate_bytes),
                "base_active_pid": 77,
            }

        def launchctl_status(self, _service: str) -> tuple[str, int]:
            self.status_calls += 1
            raise LabelAbsent("label is down after interrupted install")

        def rollback(self, service: str, *, reviewer: object, pid_before: int, automatic: bool) -> None:
            self.rollback_calls.append((service, automatic))
            assert reviewer is None
            assert pid_before == 77
            assert automatic is True
            assert active_plist.read_bytes() == baseline_bytes

        def verify_frozen_active(self, _service: str) -> tuple[dict[str, str], int]:
            assert active_plist.read_bytes() == baseline_bytes
            return ({"state": "baseline"}, 78)

    backend = FakeBackend()
    restored = cutover._restore_one_service(backend, "api")
    assert active_plist.read_bytes() == baseline_bytes
    assert backend.rollback_calls == [("api", True)]
    assert backend.status_calls == 1
    assert restored["recovery_path"] == "automatic_restore_after_launchd_label_absent"
    assert restored["state"] == "ROLLED_BACK_TO_FROZEN_BASELINE"
    assert claim_path.read_bytes() == baseline_bytes


def test_restore_one_service_rejects_existing_active_plist_with_unknown_sha(tmp_path: Path) -> None:
    baseline_bytes = b"frozen baseline plist bytes"
    candidate_bytes = b"candidate plist bytes"
    parallel_bytes = b"unexpected concurrent plist"
    active_plist = tmp_path / "api.plist"
    active_plist.write_bytes(parallel_bytes)

    class FakeBackend:
        GateError = RuntimeError
        RuntimeIdentityDrift = RuntimeError

        def __init__(self) -> None:
            self.rollback_calls = 0
            self.status_calls = 0

        def service_identity(self, _service: str) -> dict[str, str]:
            return {
                "base_active_plist_path": str(active_plist),
                "base_active_plist_sha256": cutover.sha256(baseline_bytes),
                "candidate_plist_sha256": cutover.sha256(candidate_bytes),
                "base_active_pid": 77,
            }

        def launchctl_status(self, _service: str) -> tuple[str, int]:
            self.status_calls += 1
            return ("unexpected", 1)

        def rollback(self, *_args, **_kwargs) -> None:
            self.rollback_calls += 1

    backend = FakeBackend()
    with pytest.raises(RuntimeError, match="active plist SHA is neither frozen baseline nor candidate"):
        cutover._restore_one_service(backend, "api")
    assert active_plist.read_bytes() == parallel_bytes
    assert backend.status_calls == 0
    assert backend.rollback_calls == 0


def test_restore_one_service_rejects_unknown_claim_without_recreating_target(tmp_path: Path) -> None:
    baseline_bytes = b"frozen baseline plist bytes"
    candidate_bytes = b"candidate plist bytes"
    unknown_bytes = b"unknown claim bytes"
    active_plist = tmp_path / "api.plist"
    claim_dir = tmp_path / f".{active_plist.name}.claim-{'a' * 32}"
    claim_dir.mkdir()
    claim_path = claim_dir / "before.plist"
    claim_path.write_bytes(unknown_bytes)

    class FakeBackend:
        GateError = RuntimeError
        RuntimeIdentityDrift = RuntimeError

        def service_identity(self, _service: str) -> dict[str, str]:
            return {
                "base_active_plist_path": str(active_plist),
                "base_active_plist_sha256": cutover.sha256(baseline_bytes),
                "candidate_plist_sha256": cutover.sha256(candidate_bytes),
            }

        def launchctl_status(self, _service: str) -> tuple[str, int]:
            raise AssertionError("unknown claim must fail before launchd inspection")

        def rollback(self, *_args, **_kwargs) -> None:
            raise AssertionError("unknown claim must not invoke rollback")

    with pytest.raises(RuntimeError, match="claim bytes do not match the frozen baseline or candidate"):
        cutover._restore_one_service(FakeBackend(), "api")
    assert not active_plist.exists()
    assert claim_path.read_bytes() == unknown_bytes


def test_restore_one_service_preserves_concurrently_created_active_plist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline_bytes = b"frozen baseline plist bytes"
    candidate_bytes = b"candidate plist bytes"
    parallel_bytes = b"parallel writer bytes"
    active_plist = tmp_path / "api.plist"
    claim_dir = tmp_path / f".{active_plist.name}.claim-{'b' * 32}"
    claim_dir.mkdir()
    claim_path = claim_dir / "before.plist"
    claim_path.write_bytes(baseline_bytes)

    class FakeBackend:
        GateError = RuntimeError
        RuntimeIdentityDrift = RuntimeError

        def service_identity(self, _service: str) -> dict[str, str]:
            return {
                "base_active_plist_path": str(active_plist),
                "base_active_plist_sha256": cutover.sha256(baseline_bytes),
                "candidate_plist_sha256": cutover.sha256(candidate_bytes),
            }

        def launchctl_status(self, _service: str) -> tuple[str, int]:
            raise AssertionError("concurrent claim conflict must fail before launchd inspection")

        def rollback(self, *_args, **_kwargs) -> None:
            raise AssertionError("concurrent claim conflict must not invoke rollback")

    def concurrent_create(_source, destination, *_args, **_kwargs) -> None:
        Path(destination).write_bytes(parallel_bytes)
        raise FileExistsError("simulated concurrent target creation")

    monkeypatch.setattr(cutover.os, "link", concurrent_create)
    with pytest.raises(RuntimeError, match="active plist appeared during claim recovery"):
        cutover._restore_one_service(FakeBackend(), "api")
    assert active_plist.read_bytes() == parallel_bytes
    assert claim_path.read_bytes() == baseline_bytes
