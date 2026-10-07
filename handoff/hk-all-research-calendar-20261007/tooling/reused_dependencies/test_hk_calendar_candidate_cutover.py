"""Isolated dual-service guard tests; subprocesses are blocked throughout."""

from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest


SCRIPT = Path(__file__).with_name("hk_calendar_candidate_cutover.py")
SPEC = importlib.util.spec_from_file_location("hk_calendar_candidate_cutover_under_test", SCRIPT)
assert SPEC and SPEC.loader
cutover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover)
REAL_LAUNCHCTL_STATUS = cutover.launchctl_status


@pytest.fixture(autouse=True)
def block_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("launchd/process subprocess is forbidden in isolated wrapper tests")

    monkeypatch.setattr(cutover.subprocess, "run", forbidden)


def _write_inventory_manifest(root: Path, *, candidate: bool, service: str, release_id: str) -> tuple[Path, str, list[dict[str, Any]]]:
    app = root / "app"
    (app / "pkg" / "__pycache__").mkdir(parents=True)
    (app / "pkg" / "module.py").write_text("VALUE = 2\n" if candidate else "VALUE = 1\n", encoding="utf-8")
    (app / "pkg" / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"candidate-pyc" if candidate else b"active-pyc")
    entries = cutover.inventory(app)
    source_entries, _cache = cutover.split_runtime_cache(entries)
    candidate_record: dict[str, Any] = {"root": str(root), "app_root": str(app), "release_id": release_id}
    if service == "scheduler" and candidate:
        candidate_record = {
            "root": str(root.parent / "base-scheduler"),
            "app_root": str(app),
            "release_id": "base-scheduler",
            "target_root": str(root),
        }
    manifest = {
        "schema_version": "test",
        "candidate": candidate_record,
        "release_id": release_id,
        "activation_status": "NOT_ACTIVATED" if candidate else "BASELINE",
        "application_inventory": {
            "entries": entries if candidate else source_entries,
            "aggregate_sha256": cutover.inventory_sha256(entries if candidate else source_entries),
            "entry_count": len(entries if candidate else source_entries),
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if candidate:
        manifest_path = root / "release-manifest.json"
    else:
        manifest_path = root / "release-manifest.json"
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(raw)
    return manifest_path, cutover.sha256_bytes(raw), entries


def _make_plist(service: str, *, app_root: str, release_id: str, manifest_sha: str, candidate: bool) -> bytes:
    label = "com.lexi.v35.api-only" if service == "api" else "com.lexi.v35.scheduler"
    env = {
        "V35_APP_ROOT": app_root,
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
    }
    if service == "api":
        arguments = [
            f"V35_APP_ROOT={app_root}",
            f"V35_RELEASE_ID={release_id}",
            f"V35_RELEASE_MANIFEST_SHA256={manifest_sha}",
            "/runtime/bin/python",
            "-B",
            "-m",
            "apps.api.v35_api.run",
        ]
        payload = {"Label": label, "ProgramArguments": arguments, "WorkingDirectory": app_root}
    else:
        script = f"{app_root}/ops/launch_v35_macos_scheduler.sh"
        payload = {
            "Label": label,
            "ProgramArguments": ["/bin/bash", script],
            "EnvironmentVariables": env,
            "WorkingDirectory": app_root,
        }
    if not candidate:
        payload["RunAtLoad"] = True
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    identity: dict[str, Any] = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    runtime: dict[str, Any] = {"active_plists": {}, "candidate_plists": {}, "items": {}, "baseline_hashes": {}}
    for service in ("api", "scheduler"):
        base_release_id = f"base-{service}"
        candidate_release_id = f"candidate-{service}"
        base_root = tmp_path / f"base-{service}"
        candidate_root = tmp_path / f"candidate-{service}"
        base_manifest_path, base_manifest_sha, base_entries = _write_inventory_manifest(
            base_root, candidate=False, service=service, release_id=base_release_id
        )
        candidate_manifest_path, candidate_manifest_sha, candidate_entries = _write_inventory_manifest(
            candidate_root, candidate=True, service=service, release_id=candidate_release_id
        )
        candidate_app = candidate_root / "app"
        base_app = base_root / "app"
        base_plist = evidence / f"{service}-active.plist"
        candidate_plist = evidence / f"{service}-candidate.plist"
        base_plist_bytes = _make_plist(
            service,
            app_root=str(base_app),
            release_id=base_release_id,
            manifest_sha=base_manifest_sha,
            candidate=False,
        )
        candidate_plist_bytes = _make_plist(
            service,
            app_root=str(candidate_app),
            release_id=candidate_release_id,
            manifest_sha=candidate_manifest_sha,
            candidate=True,
        )
        base_plist.write_bytes(base_plist_bytes)
        candidate_plist.write_bytes(candidate_plist_bytes)
        _base_source, base_cache = cutover.split_runtime_cache(base_entries)
        baseline_inventory_path = evidence / ("api_baseline_application_inventory_20261007.json" if service == "api" else "scheduler_baseline_application_inventory_20261007.json")
        baseline_inventory_path.write_text(json.dumps({
            "actual_app_aggregate_sha256": cutover.inventory_sha256(base_entries),
            "actual_app_entry_count": len(base_entries),
            "runtime_generated_unmanifested_entries": base_cache,
        }), encoding="utf-8")
        runtime["baseline_hashes"][service] = cutover.sha256_file(baseline_inventory_path)
        label = "com.lexi.v35.api-only" if service == "api" else "com.lexi.v35.scheduler"
        identity[service] = {
            "base_active_label": label,
            "base_active_pid": 1137 if service == "api" else 1149,
            "base_active_plist_path": str(base_plist),
            "base_active_plist_sha256": cutover.sha256_bytes(base_plist_bytes),
            "base_app_inventory_sha256": cutover.inventory_sha256(base_entries),
            "base_release_manifest_sha256": base_manifest_sha,
            "base_release_root": str(base_root),
            "candidate_app_inventory_entry_count": len(candidate_entries),
            "candidate_app_inventory_sha256": cutover.inventory_sha256(candidate_entries),
            "candidate_app_root": str(candidate_app),
            "candidate_manifest_path": str(candidate_manifest_path),
            "candidate_manifest_sha256": candidate_manifest_sha,
            "candidate_plist_path": str(candidate_plist),
            "candidate_plist_sha256": cutover.sha256_bytes(candidate_plist_bytes),
            "candidate_release_id": candidate_release_id,
            "candidate_root": str(candidate_root),
        }
        runtime["active_plists"][service] = (base_plist, base_plist_bytes)
        runtime["candidate_plists"][service] = candidate_plist_bytes
        runtime["items"][service] = identity[service]

    identity_path = evidence / "candidate_identity.json"
    identity_raw = (json.dumps(identity, sort_keys=True) + "\n").encode()
    identity_path.write_bytes(identity_raw)
    readback = evidence / "readback.json"
    readback.write_text("{}\n", encoding="utf-8")
    reviewer = evidence / "review.json"
    reviewer.write_text(json.dumps({
        "candidate_identity_sha256": cutover.sha256_bytes(identity_raw),
        "verdict": "PASS",
        "behavior_verified": "PASS",
        "actual_diff_inspected": True,
        "independent_reviewer": "/root/hk_close_daily_review",
        "api_manifest_sha256": identity["api"]["candidate_manifest_sha256"],
        "api_inventory_sha256": identity["api"]["candidate_app_inventory_sha256"],
        "scheduler_manifest_sha256": identity["scheduler"]["candidate_manifest_sha256"],
        "scheduler_inventory_sha256": identity["scheduler"]["candidate_app_inventory_sha256"],
        "api_readback_sha256": cutover.sha256_file(readback),
        "reviewed_services": ["api", "scheduler"],
    }), encoding="utf-8")
    monkeypatch.setattr(cutover, "EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(cutover, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(cutover, "EXPECTED_IDENTITY_SHA256", cutover.sha256_bytes(identity_raw))
    monkeypatch.setattr(cutover, "READBACK_PATH", readback)
    monkeypatch.setattr(cutover, "REVIEW_RECEIPT", reviewer)
    monkeypatch.setattr(cutover, "BASELINE_INVENTORY_SHA256", runtime["baseline_hashes"])

    def status(service: str) -> tuple[str, int]:
        item = identity[service]
        active, _base_bytes = runtime["active_plists"][service]
        if active.read_bytes() == runtime["candidate_plists"][service]:
            output = f"pid = 2233\n{item['candidate_app_root']} {item['candidate_release_id']} {item['candidate_manifest_sha256']}"
            return output, 2233
        base_plist = plistlib.loads(active.read_bytes())
        env = cutover.plist_environment(base_plist)
        output = f"pid = {item['base_active_pid']}\n{item['base_release_root']}/app {env['V35_RELEASE_ID']} {env['V35_RELEASE_MANIFEST_SHA256']}"
        return output, item["base_active_pid"]

    monkeypatch.setattr(cutover, "launchctl_status", status)
    runtime["reviewer"] = json.loads(reviewer.read_text())
    runtime["identity"] = identity
    return runtime


def fake_poll_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    clock: dict[str, Any] = {"now": 0.0, "sleeps": []}

    def monotonic_now() -> float:
        return float(clock["now"])

    def sleep_for_poll(seconds: float) -> None:
        clock["sleeps"].append(seconds)
        clock["now"] = float(clock["now"]) + seconds

    monkeypatch.setattr(cutover, "_monotonic_now", monotonic_now)
    monkeypatch.setattr(cutover, "_sleep_for_poll", sleep_for_poll)
    return clock


def test_wait_for_loaded_candidate_accepts_delayed_ready_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["api"]
    Path(item["base_active_plist_path"]).write_bytes(runtime["candidate_plists"]["api"])
    ready = f"state = running\npid = 2233\n{item['candidate_app_root']} {item['candidate_release_id']} {item['candidate_manifest_sha256']}"
    outputs = iter((("state = waiting\npid = 0", 0), ("state = waiting\npid = 0", 0), (ready, 2233)))
    calls: list[str] = []

    def status(service: str) -> tuple[str, int]:
        calls.append(service)
        return next(outputs)

    fake_poll_clock(monkeypatch)
    monkeypatch.setattr(cutover, "launchctl_status", status)
    result = cutover.wait_for_loaded_candidate("api", timeout_seconds=1, poll_interval_seconds=0.25)

    assert result["pid"] == 2233
    assert result["app_root"] == item["candidate_app_root"]
    assert calls == ["api", "api", "api"]


def test_wait_for_active_baseline_accepts_delayed_ready_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["scheduler"]
    ready = f"state = running\npid = {item['base_active_pid']}\n{item['base_release_root']}/app base-scheduler {item['base_release_manifest_sha256']}"
    outputs = iter((("state = waiting\npid = 0", 0), (ready, item["base_active_pid"])))
    calls: list[str] = []

    def status(service: str) -> tuple[str, int]:
        calls.append(service)
        return next(outputs)

    fake_poll_clock(monkeypatch)
    monkeypatch.setattr(cutover, "launchctl_status", status)
    result = cutover.wait_for_active_baseline("scheduler", timeout_seconds=1, poll_interval_seconds=0.25)

    assert result["pid"] == item["base_active_pid"]
    assert result["app_root"] == f"{item['base_release_root']}/app"
    assert calls == ["scheduler", "scheduler"]


@pytest.mark.parametrize("service", ["api", "scheduler"])
def test_wait_for_loaded_candidate_times_out_and_records_pending_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"][service]
    Path(item["base_active_plist_path"]).write_bytes(runtime["candidate_plists"][service])
    calls: list[str] = []

    def status(current_service: str) -> tuple[str, int]:
        calls.append(current_service)
        return "state = waiting\npid = 0", 0

    fake_poll_clock(monkeypatch)
    monkeypatch.setattr(cutover, "launchctl_status", status)
    with pytest.raises(cutover.GateError, match="candidate remained in launchd waiting/pid=0"):
        cutover.wait_for_loaded_candidate(service, timeout_seconds=0.5, poll_interval_seconds=0.25)

    assert calls == [service, service, service]
    receipt = json.loads(next(cutover.EVIDENCE_ROOT.glob(f"cutover-drift-{service}-*.json")).read_text())
    assert receipt["phase"] == "VERIFY_LOADED_PROCESS_TIMEOUT"
    assert receipt["details"]["state"] == "waiting"
    assert receipt["details"]["pid"] == 0


@pytest.mark.parametrize("service", ["api", "scheduler"])
def test_wait_for_active_baseline_times_out_and_records_pending_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, service: str) -> None:
    runtime = setup(tmp_path, monkeypatch)
    calls: list[str] = []

    def status(current_service: str) -> tuple[str, int]:
        calls.append(current_service)
        return "state = waiting\npid = 0", 0

    fake_poll_clock(monkeypatch)
    monkeypatch.setattr(cutover, "launchctl_status", status)
    with pytest.raises(cutover.GateError, match="baseline remained in launchd waiting/pid=0"):
        cutover.wait_for_active_baseline(service, timeout_seconds=0.5, poll_interval_seconds=0.25)

    assert calls == [service, service, service]
    receipt = json.loads(next(cutover.EVIDENCE_ROOT.glob(f"cutover-drift-{service}-*.json")).read_text())
    assert receipt["phase"] == "VERIFY_LOADED_BASELINE_TIMEOUT"
    assert receipt["details"]["state"] == "waiting"
    assert receipt["details"]["pid"] == 0


def test_wait_for_loaded_candidate_stops_immediately_on_positive_pid_identity_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["api"]
    Path(item["base_active_plist_path"]).write_bytes(runtime["candidate_plists"]["api"])
    calls: list[str] = []

    def status(service: str) -> tuple[str, int]:
        calls.append(service)
        return f"state = running\npid = 4421\n/wrong/root {item['candidate_release_id']} {item['candidate_manifest_sha256']}", 4421

    fake_poll_clock(monkeypatch)
    monkeypatch.setattr(cutover, "launchctl_status", status)
    with pytest.raises(cutover.RuntimeIdentityDrift, match="cannot prove candidate root"):
        cutover.wait_for_loaded_candidate("api", timeout_seconds=1, poll_interval_seconds=0.25)

    assert calls == ["api"]
    receipt = json.loads(next(cutover.EVIDENCE_ROOT.glob("cutover-drift-api-*.json")).read_text())
    assert receipt["phase"] == "VERIFY_LOADED_PROCESS_IDENTITY"
    assert receipt["details"]["missing_tokens"] == [item["candidate_app_root"]]


def test_candidate_and_active_source_pins_ignore_only_frozen_pycache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    for service in ("api", "scheduler"):
        manifest, _plist = cutover.verify_candidate(service)
        active, pid = cutover.verify_frozen_active(service)
        assert pid == runtime["identity"][service]["base_active_pid"]
        assert active["_runtime_cache_observed"]["frozen_actual_inventory_entry_count"] == 2
        assert manifest["_runtime_cache_observed"]["changed"] is False


def test_post_start_cache_change_is_recorded_but_source_change_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["scheduler"]
    pyc = Path(item["candidate_app_root"]) / "pkg/__pycache__/module.cpython-314.pyc"
    pyc.write_bytes(b"regenerated-by-scheduler-startup")
    with pytest.raises(cutover.GateError, match="pre-start candidate inventory differs"):
        cutover.verify_candidate("scheduler")
    manifest, _plist = cutover.verify_candidate("scheduler", allow_runtime_bytecode_delta=True)
    assert manifest["_runtime_cache_observed"]["changed"] is True
    assert manifest["_runtime_cache_observed"]["source_inventory_entry_count"] == 1
    source = Path(item["candidate_app_root"]) / "pkg/module.py"
    source.write_text("VALUE = 9\n", encoding="utf-8")
    with pytest.raises(cutover.GateError, match="candidate source inventory differs"):
        cutover.verify_candidate("scheduler", allow_runtime_bytecode_delta=True)


def test_active_pycache_delta_is_reported_without_weakening_source_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["api"]
    pyc = Path(item["base_release_root"]) / "app/pkg/__pycache__/module.cpython-314.pyc"
    pyc.write_bytes(b"active-runtime-cache-update")
    active, _pid = cutover.verify_frozen_active("api")
    assert active["_runtime_cache_observed"]["current_runtime_cache_matches_frozen_snapshot"] is False
    source = Path(item["base_release_root"]) / "app/pkg/module.py"
    source.write_text("SOURCE_DRIFT = True\n", encoding="utf-8")
    with pytest.raises(cutover.GateError, match="active source inventory differs"):
        cutover.verify_frozen_active("api")


def test_api_apply_uses_only_its_label_and_writes_loaded_identity_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    actions: list[str] = []
    monkeypatch.setattr(cutover, "run_launchctl", lambda service, action: actions.append(f"{service}:{action}"))
    monkeypatch.setattr(cutover, "wait_for_service_down", lambda service, timeout_seconds=15: None)
    monkeypatch.setattr(cutover, "verify_api_semantics", lambda timeout_seconds=30: {"20260911": {"status": "MODEL_REVIEW_READY"}})
    args = type("Args", (), {"service": "api", "confirm": cutover.CONFIRMATIONS["api"]})()
    assert cutover.cmd_apply(args) == 0
    item = runtime["identity"]["api"]
    active = Path(item["base_active_plist_path"])
    assert active.read_bytes() == runtime["candidate_plists"]["api"]
    backup = cutover.EVIDENCE_ROOT / "api_before_hk_calendar_cutover.plist"
    assert backup.read_bytes() != active.read_bytes()
    assert actions == ["api:bootout", "api:bootstrap"]
    receipt = json.loads(cutover.operation_path("api", "APPLIED").read_text())
    assert receipt["result"]["loaded_identity"]["release_id"] == item["candidate_release_id"]
    assert receipt["result"]["api_semantic_results"]["20260911"]["status"] == "MODEL_REVIEW_READY"
    assert receipt["other_service_touched"] is False


def test_apply_parallel_plist_edit_after_bootout_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["api"]
    active = Path(item["base_active_plist_path"])
    edit = b"parallel plist edit after bootout\n"
    actions: list[str] = []

    def launchctl(service: str, action: str) -> None:
        actions.append(f"{service}:{action}")
        if action == "bootout":
            active.write_bytes(edit)

    monkeypatch.setattr(cutover, "run_launchctl", launchctl)
    monkeypatch.setattr(cutover, "wait_for_service_down", lambda service, timeout_seconds=15: None)
    args = type("Args", (), {"service": "api", "confirm": cutover.CONFIRMATIONS["api"]})()
    with pytest.raises(cutover.GateError, match="automatic rollback also failed"):
        cutover.cmd_apply(args)
    assert active.read_bytes() == edit
    assert actions == ["api:bootout"]
    phases = [
        json.loads(path.read_text())["phase"]
        for path in cutover.EVIDENCE_ROOT.glob("cutover-drift-api-*.json")
    ]
    assert "APPLY_POSTBOOTOUT" in phases
    assert "AUTO_ROLLBACK_PREBOOTOUT" in phases


def test_no_clobber_install_preserves_target_created_at_final_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["items"]["api"]
    active = Path(item["base_active_plist_path"])
    original = active.read_bytes()
    external = b"parallel target created at final install boundary\n"
    real_link = cutover.os.link
    injected = False

    def link_with_external_target(source: object, destination: object, *_args: object, **_kwargs: object) -> None:
        nonlocal injected
        if Path(destination) == active and ".claim-" not in str(source) and not injected:
            injected = True
            active.write_bytes(external)
        real_link(source, destination)

    monkeypatch.setattr(cutover.os, "link", link_with_external_target)
    with pytest.raises(cutover.GateError, match="parallel target preserved"):
        cutover.atomic_write_no_clobber(
            "api",
            active,
            runtime["candidate_plists"]["api"],
            expected_current_sha256=cutover.sha256_bytes(original),
            phase="TEST_FINAL_LINK",
        )
    assert injected
    assert active.read_bytes() == external
    claim = next(active.parent.glob(f".{active.name}.claim-*/before.plist"))
    assert claim.read_bytes() == original
    receipt = json.loads(next(cutover.EVIDENCE_ROOT.glob("cutover-drift-api-*.json")).read_text())
    assert receipt["phase"] == "TEST_FINAL_LINK_NO_CLOBBER_CONFLICT"


def test_edit_before_atomic_claim_is_restored_without_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["items"]["scheduler"]
    active = Path(item["base_active_plist_path"])
    original = active.read_bytes()
    external = b"parallel edit before atomic claim\n"
    real_mkstemp = cutover.tempfile.mkstemp

    def mkstemp_then_edit(*args: object, **kwargs: object) -> tuple[int, str]:
        result = real_mkstemp(*args, **kwargs)
        active.write_bytes(external)
        return result

    monkeypatch.setattr(cutover.tempfile, "mkstemp", mkstemp_then_edit)
    with pytest.raises(cutover.GateError, match="drifted target restored without overwrite"):
        cutover.atomic_write_no_clobber(
            "scheduler",
            active,
            runtime["candidate_plists"]["scheduler"],
            expected_current_sha256=cutover.sha256_bytes(original),
            phase="TEST_PRECLAIM",
        )
    assert active.read_bytes() == external
    claim = next(active.parent.glob(f".{active.name}.claim-*/before.plist"))
    assert claim.read_bytes() == external
    receipt = json.loads(next(cutover.EVIDENCE_ROOT.glob("cutover-drift-scheduler-*.json")).read_text())
    assert receipt["phase"] == "TEST_PRECLAIM_CLAIM_MISMATCH"


def test_scheduler_apply_failure_rolls_back_only_when_candidate_plist_is_still_owned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["scheduler"]
    active = Path(item["base_active_plist_path"])
    actions: list[str] = []
    monkeypatch.setattr(cutover, "run_launchctl", lambda service, action: actions.append(f"{service}:{action}"))
    monkeypatch.setattr(cutover, "wait_for_service_down", lambda service, timeout_seconds=15: None)
    # Launch verification fails after bootstrap; the automatic path restores
    # only the exact batch-owned candidate bytes and leaves the other label alone.
    original = cutover.wait_for_loaded_candidate
    monkeypatch.setattr(cutover, "wait_for_loaded_candidate", lambda service: (_ for _ in ()).throw(cutover.GateError("injected loaded-identity failure")))
    args = type("Args", (), {"service": "scheduler", "confirm": cutover.CONFIRMATIONS["scheduler"]})()
    with pytest.raises(cutover.GateError, match="exact frozen baseline bytes were restored"):
        cutover.cmd_apply(args)
    assert active.read_bytes() != runtime["candidate_plists"]["scheduler"]
    assert [action for action in actions if action.startswith("scheduler:")] == [
        "scheduler:bootout", "scheduler:bootstrap", "scheduler:bootout", "scheduler:bootstrap"
    ]
    assert cutover.operation_path("scheduler", "AUTO_ROLLED_BACK").is_file()
    assert cutover.operation_path("api", "APPLIED").exists() is False
    assert original is not None


def test_manual_rollback_rejects_drift_before_bootout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["items"]["scheduler"]
    active = Path(item["base_active_plist_path"])
    active.write_bytes(b"parallel scheduler plist edit\n")
    backup = cutover.EVIDENCE_ROOT / "scheduler_before_hk_calendar_cutover.plist"
    backup.write_bytes(runtime["active_plists"]["scheduler"][1])
    monkeypatch.setattr(cutover, "run_launchctl", lambda *_args: pytest.fail("bootout must not run on drift"))
    with pytest.raises(cutover.GateError, match="frozen file SHA changed"):
        cutover.rollback("scheduler", reviewer=runtime["reviewer"], pid_before=2233)


def test_manual_rollback_restores_exact_backup_even_if_candidate_source_has_drifted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["items"]["scheduler"]
    active = Path(item["base_active_plist_path"])
    backup = cutover.EVIDENCE_ROOT / "scheduler_before_hk_calendar_cutover.plist"
    backup.write_bytes(runtime["active_plists"]["scheduler"][1])
    active.write_bytes(runtime["candidate_plists"]["scheduler"])
    # Rollback does not need the candidate code to be healthy; exact candidate
    # plist ownership and the exact pre-apply backup are the relevant gates.
    (Path(item["candidate_app_root"]) / "pkg/module.py").write_text("candidate source now drifted\n", encoding="utf-8")
    actions: list[str] = []
    monkeypatch.setattr(cutover, "run_launchctl", lambda service, action: actions.append(f"{service}:{action}"))
    monkeypatch.setattr(cutover, "wait_for_service_down", lambda service, timeout_seconds=15: None)
    args = type("Args", (), {"service": "scheduler", "confirm": cutover.ROLLBACK_CONFIRMATIONS["scheduler"]})()
    assert cutover.cmd_rollback(args) == 0
    assert active.read_bytes() == runtime["active_plists"]["scheduler"][1]
    assert actions == ["scheduler:bootout", "scheduler:bootstrap"]
    receipt = json.loads(cutover.operation_path("scheduler", "ROLLED_BACK").read_text())
    assert receipt["review_verdict"] is None
    assert receipt["other_service_touched"] is False


def test_service_specific_confirmation_is_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup(tmp_path, monkeypatch)
    args = type("Args", (), {"service": "scheduler", "confirm": cutover.CONFIRMATIONS["api"]})()
    with pytest.raises(cutover.GateError, match="service-specific explicit activation confirmation"):
        cutover.cmd_apply(args)


def test_bootstrap_uses_only_the_active_plist_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cutover.subprocess, "run", fake_run)
    cutover.run_launchctl("scheduler", "bootstrap")
    cutover.run_launchctl("scheduler", "bootout")
    item = runtime["identity"]["scheduler"]
    assert commands == [[
        "/bin/launchctl",
        "bootstrap",
        f"gui/{cutover.os.getuid()}",
        item["base_active_plist_path"],
    ], [
        "/bin/launchctl",
        "bootout",
        f"gui/{cutover.os.getuid()}/{item['base_active_label']}",
    ]]


def test_apply_bootstrap_failure_with_absent_label_restores_exact_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = setup(tmp_path, monkeypatch)
    item = runtime["identity"]["api"]
    active = Path(item["base_active_plist_path"])
    base_bytes = runtime["active_plists"]["api"][1]
    candidate_bytes = runtime["candidate_plists"]["api"]
    label = item["base_active_label"]
    domain = f"gui/{cutover.os.getuid()}"
    service_target = f"{domain}/{label}"
    state: dict[str, Any] = {"label_present": True, "bootstrap_calls": 0}
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        action = command[1]
        if action == "print":
            assert command == ["/bin/launchctl", "print", service_target]
            if not state["label_present"]:
                return subprocess.CompletedProcess(command, 113, "", f'Could not find service "{label}" in domain for user gui: {cutover.os.getuid()}')
            assert active.read_bytes() == base_bytes
            base_env = cutover.plist_environment(plistlib.loads(base_bytes))
            output = f"state = running\npid = {item['base_active_pid']}\n{item['base_release_root']}/app {base_env['V35_RELEASE_ID']} {item['base_release_manifest_sha256']}"
            return subprocess.CompletedProcess(command, 0, output, "")
        if action == "bootout":
            assert command == ["/bin/launchctl", "bootout", service_target]
            if state["label_present"]:
                state["label_present"] = False
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 113, "", f'Could not find service "{label}" in domain for user gui: {cutover.os.getuid()}')
        if action == "bootstrap":
            assert command[:3] == ["/bin/launchctl", "bootstrap", domain]
            assert command[3] == item["base_active_plist_path"]
            state["bootstrap_calls"] += 1
            if state["bootstrap_calls"] == 1:
                assert active.read_bytes() == candidate_bytes
                return subprocess.CompletedProcess(command, 5, "", "injected candidate bootstrap failure")
            assert active.read_bytes() == base_bytes
            state["label_present"] = True
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected launchctl action: {action}")

    monkeypatch.setattr(cutover, "launchctl_status", REAL_LAUNCHCTL_STATUS)
    monkeypatch.setattr(cutover.subprocess, "run", fake_run)
    args = type("Args", (), {"service": "api", "confirm": cutover.CONFIRMATIONS["api"]})()
    with pytest.raises(cutover.GateError, match="candidate failed; exact frozen baseline bytes were restored"):
        cutover.cmd_apply(args)

    assert active.read_bytes() == base_bytes
    assert state == {"label_present": True, "bootstrap_calls": 2}
    receipt = json.loads(cutover.operation_path("api", "AUTO_ROLLED_BACK").read_text())
    assert receipt["result"]["candidate_label_was_absent_before_restore"] is True
    bootstraps = [command for command in commands if command[1] == "bootstrap"]
    assert bootstraps == [
        ["/bin/launchctl", "bootstrap", domain, item["base_active_plist_path"]],
        ["/bin/launchctl", "bootstrap", domain, item["base_active_plist_path"]],
    ]
    assert [command for command in commands if command[1] == "bootout"] == [
        ["/bin/launchctl", "bootout", service_target],
        ["/bin/launchctl", "bootout", service_target],
    ]
