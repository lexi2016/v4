"""Promotion plist preservation and controller-only lifecycle failure paths."""
from contextlib import nullcontext
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace

import pytest

from ops import activate_tech_debt_candidate as activate


def _payload(root: Path):
    return {"Label": "com.lexi.v4.api", "WorkingDirectory": str(root / "app"),
            "ProgramArguments": ["/project/python", "-m", "api"],
            "KeepAlive": True, "StandardOutPath": "/preserved/log",
            "EnvironmentVariables": {"V4_APP_ROOT": str(root / "app"), "V4_RELEASE_ID": root.name,
                "V4_RELEASE_MANIFEST_PATH": str(root / "release-manifest.json"),
                "V4_RELEASE_MANIFEST_SHA256": "a" * 64,
                "WECHAT_ARCHIVE_ROOT": "/latest/confirmed/wechat", "OTHER": "unchanged"}}


def test_staged_plist_changes_only_five_identity_fields(tmp_path):
    original = _payload(tmp_path / "old")
    staged = activate.staged_payload(original, tmp_path / "new", "b" * 64)
    activate.assert_plist_delta(original, staged, tmp_path / "new", "b" * 64)
    assert original["EnvironmentVariables"]["V4_RELEASE_MANIFEST_SHA256"] == "a" * 64
    assert staged["EnvironmentVariables"]["WECHAT_ARCHIVE_ROOT"] == "/latest/confirmed/wechat"
    assert staged["ProgramArguments"] == original["ProgramArguments"]
    assert staged["KeepAlive"] is True
    assert staged["StandardOutPath"] == original["StandardOutPath"]
    staged["EnvironmentVariables"]["WECHAT_ARCHIVE_ROOT"] = "/obsolete/wechat"
    with pytest.raises(ValueError, match="NON_IDENTITY_CHANGE"):
        activate.assert_plist_delta(original, staged, tmp_path / "new", "b" * 64)


def _deployment():
    instance = activate.Deployment.__new__(activate.Deployment)
    instance.started_job = None
    instance.legacy = SimpleNamespace(JOB="gui/501/com.lexi.v4.api")
    return instance


def test_unload_waits_for_job_socket_and_old_pid(monkeypatch):
    instance = _deployment()
    job = {"pid": 42, "plist_sha256": "old"}
    jobs = iter([job, job, None, None, None])
    sockets = iter([True, False, False])
    alive = iter([True, False])
    calls = []
    instance.job = lambda *a, **kw: next(jobs)
    instance.legacy.launchctl = lambda *args: calls.append(args) or SimpleNamespace(returncode=0)
    instance.legacy.listener_present = lambda: next(sockets)
    monkeypatch.setattr(activate, "pid_alive", lambda pid: next(alive))
    monkeypatch.setattr(activate.time, "sleep", lambda _: None)
    instance.unload(job, b"old")
    assert calls == [("bootout", instance.legacy.JOB)]


def test_unload_timeout_never_bootstraps(monkeypatch):
    instance = _deployment()
    job = {"pid": 42, "plist_sha256": "old"}
    instance.job = lambda *a, **kw: job
    calls = []
    instance.legacy.launchctl = lambda *args: calls.append(args) or SimpleNamespace(returncode=0)
    clock = iter([0, 0, 21])
    monkeypatch.setattr(activate.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(activate.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="no bootstrap attempted"):
        instance.unload(job, b"old")
    assert calls == [("bootout", instance.legacy.JOB)]


def test_job_snapshot_rejects_wrong_environment_and_pid_missing(tmp_path, monkeypatch):
    plist = tmp_path / "api.plist"
    monkeypatch.setattr(activate, "PLIST", plist)
    payload = _payload(tmp_path / "old")
    raw = plistlib.dumps(payload)
    lines = [f"path = {plist}", "program = /project/python", f"working directory = {payload['WorkingDirectory']}", "pid = 42"]
    lines += [f"{name} => {payload['EnvironmentVariables'][name]}" for name in activate.PIN_NAMES]
    instance = _deployment()
    state = {"text": "\n".join(lines)}
    instance.legacy.launchctl = lambda *args: SimpleNamespace(returncode=0, stdout=state["text"], stderr="")
    assert instance.job(raw) == {"pid": 42, "plist_sha256": activate.sha(raw)}
    state["text"] = state["text"].replace("V4_RELEASE_ID => old", "V4_RELEASE_ID => external")
    with pytest.raises(ValueError, match="ENVIRONMENT_MISMATCH"):
        instance.job(raw)
    state["text"] = "\n".join(line for line in lines if not line.startswith("pid ="))
    with pytest.raises(ValueError, match="JOB_PID_MISSING"):
        instance.job(raw)
    assert instance.job(raw, allow_no_pid=True) == {"pid": None, "plist_sha256": activate.sha(raw)}


@pytest.fixture
def switch_fixture(tmp_path, monkeypatch):
    target = tmp_path / "target"
    (target / "evidence").mkdir(parents=True)
    plist = tmp_path / "api.plist"
    old, new = plistlib.dumps(_payload(tmp_path / "old")), plistlib.dumps(_payload(target))
    plist.write_bytes(old)
    plist.chmod(0o640)
    monkeypatch.setattr(activate, "PLIST", plist)
    original_job = {"pid": 42, "plist_sha256": activate.sha(old)}
    receipt = {"base": str(tmp_path / "old"), "base_job": original_job, "plist_mode": 0o640}
    (target / "preparation.json").write_text(json.dumps(receipt))
    receipt_sha = activate.sha((target / "preparation.json").read_bytes())
    monkeypatch.setattr(activate, "load_prepared", lambda *a: (receipt, old, new))
    deployment = _deployment()
    deployment.legacy.release_lock = lambda: nullcontext()
    state = {"job": original_job}
    events = []
    deployment.job = lambda *a, **kw: state["job"]

    def unload(expected, raw):
        events.append("unload")
        state["job"] = None

    def atomic(raw):
        events.append("plist-new" if raw == new else "plist-old")
        plist.write_bytes(raw)

    def start(raw):
        events.append("start-new" if raw == new else "start-old")
        job = {"pid": 43 if raw == new else 44, "plist_sha256": activate.sha(raw)}
        deployment.started_job = state["job"] = job
        return job

    deployment.unload = unload
    deployment.legacy.atomic_plist = atomic
    deployment.start_and_validate = start
    monkeypatch.setattr(activate, "Deployment", lambda *a: deployment)
    return SimpleNamespace(target=target, plist=plist, old=old, new=new, receipt_sha=receipt_sha,
                           deployment=deployment, events=events, state=state, start=start)


def test_external_plist_cas_change_causes_no_service_action(switch_fixture):
    f = switch_fixture
    f.plist.write_bytes(b"external owner")
    with pytest.raises(ValueError, match="PLIST_CAS_CHANGED"):
        activate.switch(f.target, f.receipt_sha)
    assert f.events == []


def test_external_job_change_causes_no_service_action(switch_fixture):
    f = switch_fixture
    f.state["job"] = {"pid": 99, "plist_sha256": activate.sha(f.old)}
    with pytest.raises(ValueError, match="JOB_CAS_CHANGED"):
        activate.switch(f.target, f.receipt_sha)
    assert f.events == []


def test_failed_cutover_restores_original_bytes_mode_and_verifies_old_identity(switch_fixture):
    f = switch_fixture

    def start(raw):
        job = f.start(raw)
        if raw == f.new:
            raise RuntimeError("new readiness failed")
        return job

    f.deployment.start_and_validate = start
    with pytest.raises(RuntimeError, match="AUTOMATIC_ROLLBACK_VERIFIED"):
        activate.switch(f.target, f.receipt_sha)
    assert f.events == ["unload", "plist-new", "start-new", "unload", "plist-old", "start-old"]
    assert f.plist.read_bytes() == f.old
    assert f.plist.stat().st_mode & 0o777 == 0o640
    failures = list((f.target / "evidence").glob("activation-failure-*.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())["recovery"]["status"] == "AUTOMATIC_ROLLBACK_VERIFIED"


def test_external_change_during_failure_prevents_further_service_action(switch_fixture):
    f = switch_fixture

    def start(raw):
        f.start(raw)
        f.plist.write_bytes(b"external owner")
        raise RuntimeError("failed while external owner changed pointer")

    f.deployment.start_and_validate = start
    with pytest.raises(RuntimeError, match="AUTOMATIC_ROLLBACK_FAILED"):
        activate.switch(f.target, f.receipt_sha)
    assert f.events == ["unload", "plist-new", "start-new"]
    assert f.plist.read_bytes() == b"external owner"


def test_activation_and_manual_rollback_pin_the_exact_started_job(switch_fixture):
    f = switch_fixture
    activated = activate.switch(f.target, f.receipt_sha)
    assert activated["status"] == "ACTIVATED_VERIFIED"
    rolled_back = activate.switch(f.target, f.receipt_sha, rollback=True, activation_sha=activated["result_sha256"])
    assert rolled_back["status"] == "ROLLBACK_VERIFIED"
    assert f.plist.read_bytes() == f.old
    assert f.events == ["unload", "plist-new", "start-new", "unload", "plist-old", "start-old"]


def test_manual_rollback_refuses_external_replacement_job(switch_fixture):
    f = switch_fixture
    activated = activate.switch(f.target, f.receipt_sha)
    f.events.clear()
    f.state["job"] = {"pid": 99, "plist_sha256": activate.sha(f.new)}
    with pytest.raises(ValueError, match="JOB_CAS_CHANGED"):
        activate.switch(f.target, f.receipt_sha, rollback=True, activation_sha=activated["result_sha256"])
    assert f.events == []


@pytest.mark.parametrize("scenario", ["never_pid", "pid_then_exit", "foreign_pid"])
def test_real_lifecycle_recovers_owned_loaded_job_without_pid(tmp_path, monkeypatch, scenario):
    """Keep switch/job/unload/start real; simulate only OS and HTTP boundaries."""
    target = tmp_path / "target"
    (target / "evidence").mkdir(parents=True)
    plist = tmp_path / "api.plist"
    old, new = plistlib.dumps(_payload(tmp_path / "old")), plistlib.dumps(_payload(target))
    plist.write_bytes(old)
    plist.chmod(0o640)
    monkeypatch.setattr(activate, "PLIST", plist)
    expected = {"pid": 42, "plist_sha256": activate.sha(old)}
    receipt = {"base": str(tmp_path / "old"), "base_job": expected, "plist_mode": 0o640}
    path = target / "preparation.json"
    path.write_text(json.dumps(receipt))
    receipt_sha = activate.sha(path.read_bytes())
    monkeypatch.setattr(activate, "load_prepared", lambda *a: (receipt, old, new))
    instance = _deployment()
    instance.legacy.DOMAIN = "gui/501"
    instance.legacy.release_lock = lambda: nullcontext()
    state = {"loaded": True, "raw": old, "pid": 42, "new_prints": 0, "clock": 0.0}
    events, checked = [], []

    def launchctl(*args):
        if args[0] == "print":
            if not state["loaded"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="Could not find service")
            if state["raw"] == new:
                state["new_prints"] += 1
                if scenario != "never_pid":
                    state["pid"] = 100 if state["new_prints"] == 1 else (999 if scenario == "foreign_pid" else None)
            payload = plistlib.loads(state["raw"])
            lines = [f"path = {plist}", "program = /project/python", f"working directory = {payload['WorkingDirectory']}"]
            lines += [f"{name} => {payload['EnvironmentVariables'][name]}" for name in activate.PIN_NAMES]
            if state["pid"] is not None:
                lines.append(f"pid = {state['pid']}")
            return SimpleNamespace(returncode=0, stdout="\n".join(lines), stderr="")
        events.append(args[0])
        if args[0] == "bootout":
            state["loaded"], state["pid"] = False, None
        elif args[0] == "bootstrap":
            state["loaded"], state["raw"] = True, plist.read_bytes()
            state["pid"] = None if state["raw"] == new else 44
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def atomic(raw):
        events.append("replace-new" if raw == new else "replace-old")
        plist.write_bytes(raw)

    def live(expected_id, manifest_sha, *, frontend):
        checked.append(expected_id)
        if state["raw"] == new:
            raise ValueError("new health endpoint not ready")
        assert expected_id == "old" and manifest_sha == "a" * 64

    instance.legacy.launchctl = launchctl
    instance.legacy.atomic_plist = atomic
    instance.legacy.assert_live = live
    instance.legacy.listener_present = lambda: False
    monkeypatch.setattr(activate, "Deployment", lambda *a: instance)
    monkeypatch.setattr(activate, "pid_alive", lambda pid: state["loaded"] and state["pid"] == pid)
    monkeypatch.setattr(activate.time, "monotonic", lambda: state["clock"])
    monkeypatch.setattr(activate.time, "sleep", lambda duration: state.update(clock=state["clock"] + duration))
    expected_failure = "AUTOMATIC_ROLLBACK_FAILED" if scenario == "foreign_pid" else "AUTOMATIC_ROLLBACK_VERIFIED"
    with pytest.raises(RuntimeError, match=expected_failure):
        activate.switch(target, receipt_sha)
    if scenario == "foreign_pid":
        assert events == ["bootout", "replace-new", "bootstrap"]
        assert plist.read_bytes() == new and state["pid"] == 999
    else:
        assert events == ["bootout", "replace-new", "bootstrap", "bootout", "replace-old", "bootstrap"]
        assert plist.read_bytes() == old and plist.stat().st_mode & 0o777 == 0o640
        assert checked[-1] == "old"
        assert state["loaded"] and state["pid"] == 44


def test_nonactive_preparation_revision_preserves_old_metadata(switch_fixture, monkeypatch):
    f = switch_fixture
    path = f.target / "preparation.json"
    receipt = json.loads(path.read_text())
    receipt.update(status="PREPARED_NOT_ACTIVATED", activation_tool_sha256="old-tool",
                   manifest_sha256="unchanged-manifest")
    path.write_text(json.dumps(receipt))
    raw = path.read_bytes()
    old_sha = activate.sha(raw)
    (f.target / "config").mkdir()
    artifacts = {"release-manifest.json": b"frozen manifest", "config/staged-api.plist": f.new,
                 "config/original-api.plist": f.old}
    for name, content in artifacts.items():
        (f.target / name).write_bytes(content)
    monkeypatch.setattr(activate, "load_prepared", lambda *a, **kw: (receipt, f.old, f.new))
    result = activate.revise_preparation(f.target, old_sha)
    revised = json.loads(path.read_text())
    assert revised["activation_tool_sha256"] == activate.sha(Path(activate.__file__).read_bytes())
    assert revised["metadata_revision"]["previous_preparation_sha256"] == old_sha
    backup = Path(result["backup_root"])
    assert (backup / "preparation.json").read_bytes() == raw
    for name, content in artifacts.items():
        assert (f.target / name).read_bytes() == content
        assert (backup / Path(name).name).read_bytes() == content
    assert f.plist.read_bytes() == f.old
    assert result["preparation_sha256"] != old_sha
