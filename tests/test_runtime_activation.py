"""Exact two-role runtime activation with no real launchctl mutations."""
from contextlib import nullcontext
import importlib
import json
from pathlib import Path
import plistlib
import pytest
from ops import activate_runtime_two_roles as activation

@pytest.fixture
def fixed():
    module = importlib.reload(activation.fixed)
    yield module
    importlib.reload(module)

def test_exact_two_role_proposals_reject_other_roles_and_unowned_environment(tmp_path, monkeypatch, fixed):
    monkeypatch.setattr(fixed, "LOCAL", tmp_path)
    roles = {}
    for role, label in activation.LABELS.items():
        old = tmp_path / "old" / role; new = tmp_path / "candidates" / role
        (old / "app/ops").mkdir(parents=True); (new / "app").mkdir(parents=True)
        (old / "app/ops/api_release_integration.py").write_text("# inventory")
        env = dict(zip(fixed.IDENTITY, (str(old / "app"), old.name, str(old / "release-manifest.json"), "a" * 64)))
        env.update(PYTHONPATH=str(old / "app"), STAGE_CENTER_CONFIG=str(old / "app/stage_center_tick_config.json"), PRESERVE="yes")
        before = {"Label": label, "EnvironmentVariables": env, "ProgramArguments": ["python", str(old / "app/ops/run.py")] if role == "stage" else ["python", "-m", "api"], "WorkingDirectory": str(old / "app"), "StartCalendarInterval": {"Hour": 15}}
        after = json.loads(json.dumps(before)); after["WorkingDirectory"] = str(new / "app")
        after["EnvironmentVariables"].update(dict(zip(fixed.IDENTITY, (str(new / "app"), new.name, str(new / "release-manifest.json"), "b" * 64))))
        if role == "stage":
            after["ProgramArguments"] = [v.replace(str(old / "app"), str(new / "app")) for v in before["ProgramArguments"]]
            after["EnvironmentVariables"].update(PYTHONPATH=str(new / "app"), STAGE_CENTER_CONFIG=str(new / "app/stage_center_tick_config.json"))
        else: after["EnvironmentVariables"]["V4_MANUAL_COLLECTION_STAGE_CONFIG"] = str(new / "app/config/api-v4_manual_collection_stage_config.json")
        original = tmp_path / (role + ".old.plist"); proposed = tmp_path / (role + ".new.plist")
        original.write_bytes(plistlib.dumps(before)); proposed.write_bytes(plistlib.dumps(after))
        roles[role] = {"label": label, "preimage": {k: env[k] for k in fixed.IDENTITY}, "candidate": {"app_root": str(new / "app"), "manifest_sha256": "b" * 64}, "original_plist": str(original), "proposed_plist": str(proposed), "original_plist_sha256": fixed.sha(original.read_bytes()), "proposed_plist_sha256": fixed.sha(proposed.read_bytes())}
    plan = {"roles": roles, "forward_order": ["stage", "api"], "rollback_order": ["api", "stage"], "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    activation.configure(path, tmp_path / "evidence")
    assert tuple(fixed.TARGETS) == ("stage", "api")
    proposed = Path(roles["api"]["proposed_plist"])
    payload = plistlib.loads(proposed.read_bytes()); payload["EnvironmentVariables"]["PRESERVE"] = "overwritten"
    proposed.write_bytes(plistlib.dumps(payload)); roles["api"]["proposed_plist_sha256"] = fixed.sha(proposed.read_bytes()); path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="UNOWNED_ENVIRONMENT_DELTA"): activation.configure(path, tmp_path / "evidence")
    roles["pre"] = roles["stage"]; path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="TWO_OWNED_ROLES"): activation.configure(path, tmp_path / "evidence")

@pytest.mark.parametrize("failure_role,expected", [("stage", ["stage"]), ("api", ["api", "stage"])])
def test_owned_switch_failure_restores_only_touched_roles_reverse(tmp_path, monkeypatch, fixed, failure_role, expected):
    evidence = tmp_path / "evidence"; evidence.mkdir(); records = {}; targets = {}
    for role in ("stage", "api"):
        path = tmp_path / (role + ".plist"); old, new = role.encode() + b"old", role.encode() + b"new"; path.write_bytes(old)
        (evidence / (role + ".original.plist")).write_bytes(old); (evidence / (role + ".staged.plist")).write_bytes(new)
        records[role] = {"path": str(path), "label": role, "mode": path.stat().st_mode & 0o777, "original_sha256": fixed.sha(old), "staged_sha256": fixed.sha(new), "loaded": {"pid": None, "state": "not running"}}
        targets[role] = (role, tmp_path, "old", tmp_path, "new")
    protected = tmp_path / "main.plist"; protected.write_bytes(b"protected")
    (evidence / "preparation.json").write_text(json.dumps({"records": records, "script_sha256": "fixture", "protection": {}, "data_protection": {}}))
    monkeypatch.setattr(fixed, "EVIDENCE", evidence); monkeypatch.setattr(fixed, "TARGETS", targets)
    for name, value in {"pinned": lambda *a: None, "guards": nullcontext, "loaded": lambda *a: {"pid": None, "state": "not running"}, "assert_idle": lambda *a: None, "external_protection": lambda: {}, "data_protection": lambda: {}, "tools": lambda: None, "verify_release": lambda *a: None, "verify_forward": lambda: {}}.items(): monkeypatch.setattr(fixed, name, value)
    unloads = []; starts = []; failed = False
    monkeypatch.setattr(fixed, "unload", lambda role, *a: unloads.append(role))
    def start(role, raw, ownership):
        nonlocal failed
        starts.append((role, raw))
        if role == failure_role and not failed:
            failed = True; raise RuntimeError("fixture bootstrap failure")
        ownership[role] = {"pid": None, "state": "not running"}; return ownership[role]
    monkeypatch.setattr(fixed, "start", start)
    with pytest.raises(RuntimeError, match="fixture bootstrap failure"): fixed.switch("fixture")
    assert [role for role, raw in starts if raw.endswith(b"old")] == expected
    assert all(Path(row["path"]).read_bytes() == role.encode() + b"old" for role, row in records.items())
    assert protected.read_bytes() == b"protected"

def test_rollback_conflict_never_overwrites_foreign_bytes(tmp_path, fixed):
    path = tmp_path / "api.plist"; path.write_bytes(b"someone else")
    records = {"api": {"path": str(path)}}
    restored, failures = fixed.restore_touched(["api"], records, {"api": (b"old", b"new")}, {}, lambda *a, **k: None)
    assert not restored and "ROLLBACK_EXTERNAL_CAS_CONFLICT" in failures[0]["error"]
    assert path.read_bytes() == b"someone else"


def test_stage_unload_polls_until_exact_job_is_absent(monkeypatch, fixed):
    monkeypatch.setattr(fixed, "TARGETS", {"stage": ("com.lexi.stage-center.scheduler",)})
    job = {"pid": None, "state": "not running"}
    states = iter((job, job, None)); calls = []
    monkeypatch.setattr(fixed, "loaded", lambda *a, **k: next(states))
    monkeypatch.setattr(fixed, "lc", lambda *a: calls.append(a) or type("R", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(fixed.time, "sleep", lambda *a: None)
    fixed.unload("stage", b"fixture", job)
    assert calls == [("bootout", fixed.DOMAIN + "/com.lexi.stage-center.scheduler")]

