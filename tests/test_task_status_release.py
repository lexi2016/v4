"""API-only release adapter: private trees and mocked service/process transport."""
from contextlib import nullcontext
import copy
import importlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
from types import SimpleNamespace

import pytest
from ops import api_release_integration as inventory
from ops import activate_stage_four_repairs as fixed_module

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs/handoffs/unified-release-20261102/task_status_release.py"
REF = "a" * 40
PATCH = ("domains/task_status.py", "tests/test_task_status_dates.py")
REAL_LOADED = fixed_module.loaded


@pytest.fixture
def release(monkeypatch):
    assert TOOL.is_file(), "The bounded API-only release adapter is not implemented"
    spec = importlib.util.spec_from_file_location("task_status_release_test_subject", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    importlib.reload(fixed_module)
    # Accidental process/service calls fail even if a test forgets its mocks.
    monkeypatch.setattr(tool.fixed, "lc", lambda *a: pytest.fail("real launchctl forbidden"))
    monkeypatch.setattr(tool.fixed.subprocess, "run", lambda *a, **k: pytest.fail("real process forbidden"))
    yield tool
    importlib.reload(fixed_module)


@pytest.fixture
def batch(tmp_path, monkeypatch, release):
    t = release
    local = tmp_path / "local"
    base = local / "candidates/r7/r7-api"
    candidate = local / "candidates/v4-task-status-date-20261102-r9-api"
    app = base / "app"
    source = tmp_path / "source"
    evidence_root = tmp_path / "evidence"
    launch = tmp_path / "LaunchAgents"
    for path in (app, source, launch, evidence_root):
        path.mkdir(parents=True)
    def put(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    put(app / PATCH[0], b"old task status\n")
    put(app / "untouched.py", b"preserved\n")
    put(app / "__pycache__/tracked.cpython-313.pyc", b"registered cache")
    put(app / "__pycache__/ignored.cpython-314.pyc", b"unregistered cache")
    for relative in ("ops/api_release_integration.py", "infrastructure/interprocess_lock.py", "infrastructure/owned_io.py"):
        put(app / relative, (ROOT / relative).read_bytes())
    frozen = {PATCH[0]: b"new task status\n", PATCH[1]: b"new tests\n"}
    for relative, raw in frozen.items():
        put(source / relative, raw)
    stage = base.parent / "r7-stage/app"
    put(stage / "stage_center_tick_config.json", b'{"research_owner_binding":{"release_id":"r7-main"}}')
    put(stage.parent / "release-manifest.json", b'{"release_id":"r7-stage"}')
    manual = app / "config/api-v4_manual_collection_stage_config.json"
    put(manual, json.dumps({"stage_owner_root": str(stage), "raw_root": "/preserved/raw"}).encode())
    panel = tmp_path / "panel"
    put(panel / "workbench-host/bootstrap.mjs", b"unchanged workbench asset")
    assets = tmp_path / "panel-assets.json"
    assets.write_text(json.dumps({"files": [{"path": "workbench-host/bootstrap.mjs", "sha256": t.fixed.sha((panel / "workbench-host/bootstrap.mjs").read_bytes())}]}))
    binding = tmp_path / "binding.json"
    binding.write_text('{"production_allowed":false}')
    config = tmp_path / "workbench.json"
    config.write_text('{"state_root":"/preserved/workbench"}')
    entries = inventory.inventory_tree(app)
    manifest = {"schema_version": "v4.release_candidate.v1", "candidate": {"root": str(base), "app_root": str(app), "release_id": base.name, "module_role": "api"},
        "app_root": str(app), "release_id": base.name,
        "application_inventory": {"entries": entries, "entry_count": len(entries), "aggregate_sha256": inventory.inventory_digest(entries)},
        "app_files": entries, "research_panel": {"root": str(panel)},
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    manifest_path = base / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    env = dict(zip(t.fixed.IDENTITY, (str(app), base.name, str(manifest_path), t.fixed.sha(manifest_path.read_bytes()))))
    env.update(PYTHONPATH="/older/fallback/app/upstreams:/older/fallback/app", V4_MANUAL_COLLECTION_STAGE_CONFIG=str(manual),
        V4_RESEARCH_PANEL_ROOT=str(panel), V4_RESEARCH_PANEL_ASSET_MANIFEST=str(assets), V4_WORKBENCH_HOST_BINDING=str(binding),
        V4_WORKBENCH_HOST_BINDING_SHA256=t.fixed.sha(binding.read_bytes()), V4_MANAGER_WORKBENCH_CONFIG_PATH=str(config),
        V4_TASK_STATUS_LEDGER_ROOT="/preserved/dispatcher", RESEARCH_ONLY="1", PRODUCTION_ALLOWED="false", BUY_GATE_UPDATED="false", ORDERS_SENT="false")
    payload = {"Label": "com.lexi.v4.api", "ProgramArguments": [str(t.fixed.PYTHON), "-B", "-m", "apps.api.v4_api.run"],
        "WorkingDirectory": str(app), "EnvironmentVariables": env, "KeepAlive": True}
    plist = launch / "com.lexi.v4.api.plist"
    plist.write_bytes(plistlib.dumps(payload))
    protected = launch / "com.lexi.v4.scheduler.plist"
    protected.write_bytes(b"unchanged Main plist")
    raw = plist.read_bytes()
    job = {"pid": 101, "state": "running", "plist_sha256": t.fixed.sha(raw), "loaded_definition_sha256": "loaded", "release_id": base.name}
    for name, value in {"BASE": base, "CANDIDATE": candidate, "STAGE_APP": stage, "ARTIFACT_ROOT": evidence_root,
        "BASE_PLIST_SHA": t.fixed.sha(raw), "BASE_MANIFEST_SHA": env["V4_RELEASE_MANIFEST_SHA256"],
        "TASK_PREIMAGE_SHA": t.fixed.sha((app / PATCH[0]).read_bytes())}.items():
        monkeypatch.setattr(t, name, value)
    monkeypatch.setattr(t.fixed, "LOCAL", local)
    monkeypatch.setattr(t.fixed, "LA", launch)
    monkeypatch.setattr(t.fixed, "guards", nullcontext)
    monkeypatch.setattr(t.fixed, "loaded", lambda *a, **k: dict(job))
    monkeypatch.setattr(t.fixed, "assert_idle", lambda pid: {"idle": True})
    monkeypatch.setattr(t.fixed, "live_api", lambda raw: {"job": dict(job), "runtime_identity": {"status": "MANIFEST_EXECUTION_FILES_VERIFIED"}})
    status = {"business_date": "20261102", "scheduler_observation": {"status": "RECEIPT_DATE_MISMATCH", "receipt_count": 1},
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    monkeypatch.setattr(t.fixed, "api_get", lambda route: copy.deepcopy(status))
    monkeypatch.setattr(t, "probe_receipts", lambda *a: {"receipt_count": 1, "date_valid_count": 1, "chain_valid": True, "rows": [{"status": "FAILED"}]})
    def git(argv, **kwargs):
        if "rev-parse" in argv:
            return (REF + "\n").encode()
        if "show" in argv:
            return frozen[argv[-1].split(":", 1)[1]]
        if "ls-tree" in argv:
            return b"".join(("100644 blob " + "b" * 40 + "\t" + p).encode() + b"\0" for p in PATCH)
        pytest.fail("unexpected external command: " + repr(argv))
    monkeypatch.setattr(t.subprocess, "check_output", git)
    return SimpleNamespace(t=t, base=base, app=app, source=source, candidate=candidate, evidence=evidence_root,
        plist=plist, raw=raw, payload=payload, job=job, protected=protected, frozen=frozen, status=status)


def built(f):
    path = f.evidence / "build"
    f.t.build(source=f.source, source_ref=REF, evidence=path)
    plan = path / "plan.json"
    return plan, f.t.fixed.sha(plan.read_bytes())


def prepared(f):
    plan, digest = built(f)
    evidence = f.evidence / "prepared"
    f.t.prepare(plan_path=plan, plan_sha=digest, evidence=evidence)
    return plan, evidence, f.t.fixed.sha((evidence / "preparation.json").read_bytes())


def test_build_changes_exact_patch_and_preserves_registered_cache_and_manual_binding(batch):
    f = batch
    before = f.t.fixed.sha((f.base / "release-manifest.json").read_bytes())
    plan_path, _ = built(f)
    plan = json.loads(plan_path.read_bytes())
    after = json.loads((f.candidate / "release-manifest.json").read_bytes())
    assert [r["path"] for r in plan["delta"]] == list(PATCH)
    assert after["task_status_date_patch"]["source_ref"] == REF
    assert after["research_panel"] == {"root": f.payload["EnvironmentVariables"]["V4_RESEARCH_PANEL_ROOT"]}
    assert (f.candidate / "app/untouched.py").read_bytes() == b"preserved\n"
    assert (f.candidate / "app/__pycache__/tracked.cpython-313.pyc").read_bytes() == b"registered cache"
    assert not (f.candidate / "app/__pycache__/ignored.cpython-314.pyc").exists()
    assert (f.candidate / "app/config/api-v4_manual_collection_stage_config.json").read_bytes() == (f.app / "config/api-v4_manual_collection_stage_config.json").read_bytes()
    assert f.t.fixed.sha((f.base / "release-manifest.json").read_bytes()) == before
    assert f.plist.read_bytes() == f.raw
    assert f.t.fixed.TARGETS.keys() == {"api"}
    with pytest.raises(ValueError, match="CANDIDATE_MUST_BE_NEW"):
        f.t.build(source=f.source, source_ref=REF, evidence=f.evidence / "second")


@pytest.mark.parametrize("failure", ["source", "preimage", "plist", "manifest", "inventory"])
def test_build_rejects_unfrozen_or_wrong_baseline_before_copy(batch, failure):
    f = batch
    if failure == "source":
        (f.source / PATCH[0]).write_bytes(b"not committed")
    elif failure == "preimage":
        f.t.TASK_PREIMAGE_SHA = "0" * 64
    elif failure == "plist":
        f.plist.write_bytes(f.raw + b"\n")
    elif failure == "manifest":
        (f.base / "release-manifest.json").write_bytes(b"{}")
    else:
        (f.app / "untouched.py").write_bytes(b"foreign")
    with pytest.raises(ValueError):
        f.t.build(source=f.source, source_ref=REF, evidence=f.evidence / "build")
    assert not f.candidate.exists()


def test_build_pins_registered_inventory_helper_before_loading_its_code(batch):
    f = batch
    (f.app / "ops/api_release_integration.py").write_text("raise AssertionError('unverified helper executed')")
    with pytest.raises(ValueError):
        f.t.build(source=f.source, source_ref=REF, evidence=f.evidence / "build")
    assert not f.candidate.exists()


def test_delta_rejects_unowned_change_removal_or_wrong_frozen_bytes(batch):
    f = batch
    plan, _ = built(f)
    record = json.loads(plan.read_bytes())
    before, after = record["inventories"]["before"], record["inventories"]["after"]
    for mutation in ("change", "remove", "patch"):
        bad = copy.deepcopy(after)
        row = next(v for v in bad["entries"] if v["path"] == (PATCH[0] if mutation == "patch" else "untouched.py"))
        if mutation == "remove":
            bad["entries"].remove(row)
        else:
            row["sha256"] = "f" * 64
        with pytest.raises(ValueError):
            f.t.check_delta(before, bad, record["frozen"])


def test_plist_preserves_fallback_pythonpath_and_old_manual_config(batch):
    f = batch
    proposed = f.t.proposed_plist(f.raw, f.candidate, "c" * 64)
    after = plistlib.loads(proposed)
    assert after["EnvironmentVariables"]["PYTHONPATH"] == "/older/fallback/app/upstreams:/older/fallback/app"
    assert after["EnvironmentVariables"]["V4_MANUAL_COLLECTION_STAGE_CONFIG"] == f.payload["EnvironmentVariables"]["V4_MANUAL_COLLECTION_STAGE_CONFIG"]
    assert after["ProgramArguments"] == f.payload["ProgramArguments"]
    assert after["WorkingDirectory"] == str(f.candidate / "app")
    for field in ("KeepAlive", "ProgramArguments", "EnvironmentVariables"):
        bad = copy.deepcopy(after)
        if field == "KeepAlive": bad[field] = False
        elif field == "ProgramArguments": bad[field].append("--new-feature")
        else: bad[field]["V4_MANUAL_COLLECTION_STAGE_CONFIG"] = str(f.candidate / "app/config/manual.json")
        with pytest.raises(ValueError, match="UNOWNED_PLIST_DELTA"):
            f.t.validate_proposal(f.raw, plistlib.dumps(bad), f.candidate, "c" * 64)


def test_plist_rewrites_only_real_old_api_app_path_occurrences(batch):
    f = batch
    p = copy.deepcopy(f.payload)
    old = str(f.app)
    p["ProgramArguments"].append("--script=" + old + "/ops/run.py")
    p["EnvironmentVariables"]["PYTHONPATH"] = old + "/upstreams:" + old + "-other:/older/app"
    result = plistlib.loads(f.t.proposed_plist(plistlib.dumps(p), f.candidate, "c" * 64))
    assert result["ProgramArguments"][-1] == "--script=" + str(f.candidate / "app/ops/run.py")
    assert result["EnvironmentVariables"]["PYTHONPATH"] == str(f.candidate / "app/upstreams") + ":" + old + "-other:/older/app"


def test_protected_legacy_plist_symlink_pins_link_and_target_bytes(batch):
    f = batch
    target = f.evidence / "legacy-runtime.plist"
    target.write_bytes(b"preserved legacy definition")
    link = f.protected.parent / "com.codex.v3.macos.scheduler.plist"
    link.symlink_to(target)
    first = f.t.protection(f.raw, inventory)
    record = next(r for r in first["non_api_plists"] if r["path"] == str(link))
    assert record["kind"] == "symlink"
    assert record["target"] == str(target)
    assert record["sha256"] == f.t.fixed.sha(b"preserved legacy definition")
    assert link.is_symlink() and target.read_bytes() == b"preserved legacy definition"
    target.write_bytes(b"external definition changed")
    assert f.t.protection(f.raw, inventory) != first
    target.write_bytes(b"preserved legacy definition")
    replacement = f.evidence / "another-runtime.plist"
    replacement.write_bytes(b"preserved legacy definition")
    link.unlink(); link.symlink_to(replacement)
    assert f.t.protection(f.raw, inventory) != first


@pytest.mark.parametrize("change", ["broken", "target_during_read", "link_during_read"])
def test_protected_symlink_rejects_broken_or_changing_definition(batch, monkeypatch, change):
    f = batch
    target = f.evidence / "legacy.plist"
    target.write_bytes(b"legacy definition")
    link = f.protected.parent / "legacy.plist"
    link.symlink_to(target)
    if change == "broken":
        target.unlink()
    else:
        real_read = Path.read_bytes
        def read(path):
            raw = real_read(path)
            if path == target:
                if change == "target_during_read":
                    target.write_bytes(b"new external definition")
                else:
                    link.unlink(); link.symlink_to(f.evidence / "missing.plist")
            return raw
        monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(ValueError, match="PROTECTED_LINK"):
        f.t.protected_plist(link)


def test_preparation_pins_plan_inventory_scripts_and_exact_backups(batch):
    f = batch
    plan, evidence, digest = prepared(f)
    receipt = json.loads((evidence / "preparation.json").read_bytes())
    assert receipt["plan_path"] == str(plan.resolve())
    assert receipt["plan_sha256"] == f.t.fixed.sha(plan.read_bytes())
    assert receipt["records"].keys() == {"api"}
    assert receipt["script_pins"][str(TOOL)] == f.t.fixed.sha(TOOL.read_bytes())
    assert (evidence / "api.original.plist").read_bytes() == f.raw
    assert f.plist.read_bytes() == f.raw
    assert receipt["protection"]["non_api_plists"][0]["path"] == str(f.protected)
    assert f.t.read_prepared(plan, evidence, digest)[0]["plan_sha256"] == receipt["plan_sha256"]


@pytest.mark.parametrize("mutation", ["plan_path", "plan_bytes", "preparation", "script", "backup"])
def test_switch_rejects_later_plan_or_changed_pins_before_unload(batch, monkeypatch, mutation):
    f = batch
    plan, evidence, digest = prepared(f)
    unloads = []
    monkeypatch.setattr(f.t.fixed, "unload", lambda *a: unloads.append(a))
    if mutation == "plan_path":
        other = f.evidence / "other.json"; other.write_bytes(plan.read_bytes()); plan = other
    elif mutation == "plan_bytes": plan.write_bytes(plan.read_bytes() + b"\n")
    elif mutation == "preparation":
        p = evidence / "preparation.json"; p.write_bytes(p.read_bytes() + b"\n")
    elif mutation == "script": (f.app / "infrastructure/interprocess_lock.py").write_bytes(b"changed")
    else: (evidence / "api.staged.plist").write_bytes(b"changed")
    with pytest.raises(ValueError):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert not unloads
    assert f.plist.read_bytes() == f.raw


@pytest.mark.parametrize("failure", ["busy", "guard", "cas", "mode", "candidate", "protected", "loaded"])
def test_admission_failure_is_before_any_unload(batch, monkeypatch, failure):
    f = batch
    plan, evidence, digest = prepared(f)
    unloads = []
    monkeypatch.setattr(f.t.fixed, "unload", lambda *a: unloads.append(a))
    def busy(*args): raise ValueError("fixture busy")
    if failure == "busy": monkeypatch.setattr(f.t.fixed, "assert_idle", busy)
    elif failure == "guard": monkeypatch.setattr(f.t.fixed, "guards", busy)
    elif failure == "cas": f.plist.write_bytes(b"foreign plist")
    elif failure == "mode": f.plist.chmod(0o600)
    elif failure == "candidate": (f.candidate / "app/untouched.py").write_bytes(b"drift")
    elif failure == "protected": f.protected.write_bytes(b"Main drift")
    else: f.job["pid"] = 999
    with pytest.raises(ValueError):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert not unloads


def test_switch_requires_authorization_and_preparation_sha(batch, monkeypatch):
    f = batch
    plan, evidence, digest = prepared(f)
    monkeypatch.setattr(f.t.fixed, "unload", lambda *a: pytest.fail("must not unload"))
    for auth, sha in ((False, digest), (True, None)):
        with pytest.raises(ValueError):
            f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=sha, authorized=auth)


@pytest.mark.parametrize("failure", ["unload_after_touch", "bootstrap", "postcheck", "foreign_cas", "foreign_pid"])
def test_failed_cutover_restores_only_owned_touched_api(batch, monkeypatch, failure):
    f = batch
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    running = {"raw": f.raw, "job": dict(f.job)}
    calls = []
    def loaded(label, raw, missing=False):
        assert label == "com.lexi.v4.api"
        if running["job"] is None:
            assert missing
            return None
        if raw != running["raw"]:
            raise ValueError("LOADED_DEFINITION_CHANGED")
        return dict(running["job"])
    def unload(role, raw, owned):
        assert role == "api" and (running["job"] is None or owned["pid"] == running["job"]["pid"])
        calls.append(("unload", role)); running["job"] = None
        if failure == "unload_after_touch" and len(calls) == 1:
            raise RuntimeError("fixture cutover failure")
    def start(role, raw, ownership):
        assert role == "api"
        calls.append(("start", raw))
        job = {**f.job, "pid": 202 if raw == desired else 303}
        running.update(raw=raw, job=job); ownership[role] = dict(job)
        if raw == desired and failure in {"bootstrap", "foreign_cas", "foreign_pid"}:
            if failure == "foreign_cas": f.plist.write_bytes(b"foreign owner")
            if failure == "foreign_pid": running["job"]["pid"] = 999
            raise RuntimeError("fixture cutover failure")
        return {"job": job}
    monkeypatch.setattr(f.t.fixed, "loaded", loaded)
    monkeypatch.setattr(f.t.fixed, "unload", unload)
    monkeypatch.setattr(f.t.fixed, "start", start)
    def postcheck(*args, **kwargs): raise RuntimeError("fixture cutover failure")
    monkeypatch.setattr(f.t, "verify_result", postcheck)
    with pytest.raises(RuntimeError):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.protected.read_bytes() == b"unchanged Main plist"
    if failure == "foreign_cas":
        assert f.plist.read_bytes() == b"foreign owner"
        assert len(calls) == 2
    elif failure == "foreign_pid":
        assert running["job"]["pid"] == 999
        assert f.plist.read_bytes() == desired
        assert len(calls) == 2
    else:
        assert f.plist.read_bytes() == f.raw
        assert running["raw"] == f.raw
        assert calls[-1] == ("start", f.raw)


def test_activate_then_rollback_uses_same_plan_and_never_changes_main_or_stage(batch, monkeypatch):
    f = batch
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    running = {"raw": f.raw, "job": dict(f.job)}
    calls = []
    def loaded(label, raw, missing=False):
        assert label == "com.lexi.v4.api"
        if running["job"] is None:
            assert missing
            return None
        assert raw == running["raw"]
        return dict(running["job"])
    def unload(role, raw, owned):
        assert role == "api" and owned["pid"] == running["job"]["pid"]
        calls.append(("unload", role))
        running["job"] = None
    def start(role, raw, ownership):
        assert role == "api" and f.plist.read_bytes() == raw
        calls.append(("start", role))
        job = {**f.job, "pid": 202 if raw == desired else 303}
        running.update(raw=raw, job=job)
        ownership[role] = dict(job)
        f.status["scheduler_observation"]["status"] = "RECEIPT_CHAIN_VERIFIED" if raw == desired else "RECEIPT_DATE_MISMATCH"
        return {"job": job}
    monkeypatch.setattr(f.t.fixed, "loaded", loaded)
    monkeypatch.setattr(f.t.fixed, "unload", unload)
    monkeypatch.setattr(f.t.fixed, "start", start)
    forward = f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.plist.read_bytes() == desired
    assert forward["task_status"]["scheduler_observation"]["status"] == "RECEIPT_CHAIN_VERIFIED"
    rollback = f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True, rollback=True)
    assert f.plist.read_bytes() == f.raw
    assert rollback["restored_r7_projection_defect"] is True
    assert calls == [("unload", "api"), ("start", "api"), ("unload", "api"), ("start", "api")]
    assert f.protected.read_bytes() == b"unchanged Main plist"
    assert (evidence / "preparation.json").is_file()


def test_receipt_probe_checks_actual_namespace_without_writing_or_relabeling(tmp_path, release, monkeypatch):
    # Exercise the embedded program directly; even an invalid business_date file
    # omitted by list_receipts must make the actual namespace proof fail.
    import contextlib
    import io
    import sys
    from infrastructure.scheduling.execution_ledger import _ledger_digest
    root = tmp_path / "dispatcher"
    folder = root / "receipts/live/20261102/1800"
    folder.mkdir(parents=True)
    payload = {"business_date": "20261102", "scheduled_date": "20261102", "target_date": "20261103", "slot": "1800", "mode": "LIVE",
        "run_id": "one", "selected_workload_ids": ["hourly_research"], "status": "FAILED", "prev_ledger_sha256": "",
        "finished_at": "2026-11-02T18:01:00+08:00", "workload_results": [{"workload_id": "hourly_research", "status": "FAILED"}]}
    payload["ledger_sha256"] = _ledger_digest(payload)
    path = folder / "one.dispatch-receipt.json"
    path.write_text(json.dumps(payload))
    old_path = list(sys.path)
    def run():
        output = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["-c", str(ROOT), json.dumps({"V4_TASK_STATUS_LEDGER_ROOT": str(root)}), "20261102"])
        try:
            with contextlib.redirect_stdout(output):
                exec(release.PROBE_CODE, {})
        finally:
            sys.path[:] = old_path
        return json.loads(output.getvalue())
    before = path.read_bytes()
    result = run()
    assert result["date_valid_count"] == result["receipt_count"] == 1
    assert result["chain_valid"] is True
    assert result["rows"][0]["status"] == "FAILED"
    assert path.read_bytes() == before
    payload["business_date"] = "20261103"
    payload["ledger_sha256"] = _ledger_digest(payload)
    path.write_text(json.dumps(payload))
    invalid = run()
    assert invalid["receipt_count"] == 1 and invalid["date_valid_count"] == 0
    assert invalid["chain_valid"] is False


@pytest.fixture
def lifecycle(batch, monkeypatch):
    """Real loaded/start/unload/CAS/restore helpers; only launchd/socket/health mocked."""
    f = batch
    t = f.t
    state = {"raw": f.raw, "pid": 101, "mode": "healthy", "mutate": None}
    calls, events = [], []
    clock = {"now": 0}
    def monotonic():
        clock["now"] += 20
        return clock["now"]
    def lc(*args):
        if args[0] == "print":
            assert args == ("print", t.fixed.DOMAIN + "/com.lexi.v4.api")
            if state["raw"] is None:
                return SimpleNamespace(returncode=1, stderr="Could not find service", stdout="")
            payload = plistlib.loads(state["raw"])
            text = ("path = " + str(f.plist) + "\nprogram = " + payload["ProgramArguments"][0]
                    + "\nworking directory = " + payload["WorkingDirectory"]
                    + "\n\targuments = {\n" + "".join("\t\t" + arg + "\n" for arg in payload["ProgramArguments"])
                    + "\t}\n\tenvironment = {\n" + "".join("\t\t" + key + " => " + str(value) + "\n"
                      for key, value in payload["EnvironmentVariables"].items()) + "\t}\n\tstate = "
                    + ("running" if state["pid"] is not None else "throttled") + "\n")
            if state["pid"] is not None:
                text += "pid = " + str(state["pid"]) + "\n"
            return SimpleNamespace(returncode=0, stderr="", stdout=text)
        if args[0] == "bootout":
            assert args == ("bootout", t.fixed.DOMAIN + "/com.lexi.v4.api")
            calls.append(("bootout", state["pid"]))
            state.update(raw=None, pid=None)
            return SimpleNamespace(returncode=0, stderr="")
        assert args == ("bootstrap", t.fixed.DOMAIN, str(f.plist))
        raw = f.plist.read_bytes()
        candidate = raw != f.raw
        calls.append(("bootstrap", "candidate" if candidate else "baseline"))
        if candidate and state["mode"] == "bootstrap_failure":
            return SimpleNamespace(returncode=1, stderr="fixture bootstrap rejected")
        state.update(raw=raw, pid=(None if state["mode"] == "pidless" else 202) if candidate else 303)
        if candidate and state["mode"] == "bootstrap_timeout":
            raise t.fixed.subprocess.TimeoutExpired(["mock_launchctl", "bootstrap"], 12)
        return SimpleNamespace(returncode=0, stderr="")
    class NoListener:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect_ex(self, address):
            assert address == ("127.0.0.1", 8873)
            return 1
    def health(raw):
        job = t.fixed.loaded("com.lexi.v4.api", raw)
        t.fixed.require(job["pid"] is not None, "API_PID_ABSENT")
        if raw != f.raw and state["mode"] == "unavailable":
            raise ValueError("fixture unhealthy candidate")
        return {"job": job, "runtime_identity": {"status": "MANIFEST_EXECUTION_FILES_VERIFIED"}}
    real_write = t.fixed.write_json
    def write(path, obj):
        if obj.get("event"):
            events.append(obj["event"])
            if obj["event"] == "CUTOVER_FAILED" and state["mutate"]:
                state["mutate"]()
        return real_write(path, obj)
    monkeypatch.setattr(t.fixed, "loaded", REAL_LOADED)
    monkeypatch.setattr(t.fixed, "lc", lc)
    monkeypatch.setattr(t.fixed, "live_api", health)
    monkeypatch.setattr(t.fixed, "pid_alive", lambda pid: False)
    monkeypatch.setattr(t.fixed.socket, "socket", lambda *a, **k: NoListener())
    monkeypatch.setattr(t.fixed.time, "monotonic", monotonic)
    monkeypatch.setattr(t.fixed.time, "sleep", lambda _: None)
    monkeypatch.setattr(t.fixed, "write_json", write)
    f.job.update(t.fixed.loaded("com.lexi.v4.api", f.raw))
    f.state, f.calls, f.events = state, calls, events
    return f


@pytest.mark.parametrize("conflict", [None, "foreign_cas", "foreign_pid"])
def test_audit_sink_failure_never_prevents_owned_recovery(lifecycle, monkeypatch, conflict):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    real_write = f.t.fixed.write_json
    failed_events = []
    def write(path, obj):
        name = obj.get("event")
        if name and name != "ADMISSION_PASS":
            failed_events.append(name)
            if name == "API_STARTED":
                if conflict == "foreign_cas": f.plist.write_bytes(b"foreign owner")
                if conflict == "foreign_pid": f.state["pid"] = 999
            raise OSError("MOCK_EVIDENCE_STORAGE_UNWRITABLE:" + name)
        return real_write(path, obj)
    monkeypatch.setattr(f.t.fixed, "write_json", write)
    with pytest.raises((OSError, RuntimeError), match="MOCK_EVIDENCE_STORAGE_UNWRITABLE:API_STARTED") as failure:
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert failed_events[:2] == ["API_STARTED", "CUTOVER_FAILED"]
    assert f.protected.read_bytes() == b"unchanged Main plist"
    if conflict:
        assert f.calls == [("bootout", 101), ("bootstrap", "candidate")]
        assert f.plist.read_bytes() == (b"foreign owner" if conflict == "foreign_cas" else desired)
        assert f.state["pid"] == (999 if conflict == "foreign_pid" else 202)
        assert "RECOVERY_FAILED" in str(failure.value)
    else:
        assert f.plist.read_bytes() == f.raw
        assert f.state["raw"] == f.raw and f.state["pid"] == 303
        assert f.calls == [("bootout", 101), ("bootstrap", "candidate"), ("bootout", 202), ("bootstrap", "baseline")]
        assert "AUTOMATIC_ROLLBACK_VERIFIED" in failed_events
        assert type(failure.value) is OSError  # Logging did not replace the primary error.
    assert not list(evidence.glob("event-*.json")) or all(
        json.loads(path.read_bytes())["event"] == "ADMISSION_PASS" for path in evidence.glob("event-*.json"))


def test_admission_audit_failure_is_before_any_live_mutation(lifecycle, monkeypatch):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    def unwritable(*args): raise OSError("fixture admission audit failure")
    monkeypatch.setattr(f.t.fixed, "write_json", unwritable)
    with pytest.raises(OSError, match="fixture admission audit failure"):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.plist.read_bytes() == f.raw and f.state["pid"] == 101
    assert f.calls == []


@pytest.mark.parametrize("mode", ["pidless", "bootstrap_failure"])
def test_failed_bootstrap_or_pidless_timeout_restores_previous_api(lifecycle, mode):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    f.state["mode"] = mode
    with pytest.raises((ValueError, RuntimeError), match="START_READINESS_TIMEOUT|BOOTSTRAP_FAILED"):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.plist.read_bytes() == f.raw
    assert f.state["raw"] == f.raw and f.state["pid"] == 303
    assert f.calls == ([("bootout", 101), ("bootstrap", "candidate")]
                       + ([("bootout", None)] if mode == "pidless" else []) + [("bootstrap", "baseline")])
    assert "AUTOMATIC_ROLLBACK_VERIFIED" in f.events
    assert f.protected.read_bytes() == b"unchanged Main plist"


@pytest.mark.parametrize("state", ["pidless", "unavailable", "missing"])
def test_explicit_same_plan_rollback_does_not_require_candidate_health(lifecycle, state):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    f.plist.write_bytes(desired)
    f.state.update(raw=None if state == "missing" else desired,
                   pid=202 if state == "unavailable" else None, mode=state)
    result = f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True, rollback=True)
    assert f.plist.read_bytes() == f.raw
    assert f.state["raw"] == f.raw and f.state["pid"] == 303
    assert result["restored_r7_projection_defect"] is True
    assert f.calls == ([] if state == "missing" else [("bootout", 202 if state == "unavailable" else None)]) + [("bootstrap", "baseline")]
    assert f.protected.read_bytes() == b"unchanged Main plist"


@pytest.mark.parametrize("conflict", ["pid", "argv", "cwd", "env", "cas"])
def test_pidless_timeout_never_recovers_over_foreign_identity(lifecycle, conflict):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    def mutate():
        if conflict == "pid": f.state["pid"] = 999
        elif conflict == "cas": f.plist.write_bytes(b"foreign owner")
        else:
            payload = plistlib.loads(desired)
            if conflict == "argv": payload["ProgramArguments"].append("--foreign")
            elif conflict == "cwd": payload["WorkingDirectory"] += "-foreign"
            else: payload["EnvironmentVariables"]["V4_RELEASE_ID"] = "foreign"
            f.state["raw"] = plistlib.dumps(payload)
    f.state.update(mode="pidless", mutate=mutate)
    with pytest.raises(RuntimeError, match="RECOVERY_FAILED"):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.calls == [("bootout", 101), ("bootstrap", "candidate")]
    assert f.plist.read_bytes() == (b"foreign owner" if conflict == "cas" else desired)
    assert f.state["pid"] == (999 if conflict == "pid" else None)
    assert "AUTOMATIC_ROLLBACK_VERIFIED" not in f.events


@pytest.mark.parametrize("conflict", ["argv", "cwd", "env", "cas"])
def test_explicit_rollback_rejects_foreign_candidate_definition(lifecycle, conflict):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    payload = plistlib.loads(desired)
    if conflict == "argv": payload["ProgramArguments"].append("--foreign")
    elif conflict == "cwd": payload["WorkingDirectory"] += "-foreign"
    elif conflict == "env": payload["EnvironmentVariables"]["V4_RELEASE_ID"] = "foreign"
    f.state.update(raw=plistlib.dumps(payload), pid=None)
    f.plist.write_bytes(b"foreign owner" if conflict == "cas" else desired)
    with pytest.raises(ValueError):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True, rollback=True)
    assert f.calls == []
    assert f.plist.read_bytes() == (b"foreign owner" if conflict == "cas" else desired)


def test_bootstrap_timeout_with_unconfirmed_pid_never_adopts_external_process(lifecycle):
    f = lifecycle
    plan, evidence, digest = prepared(f)
    desired = (evidence / "api.staged.plist").read_bytes()
    f.state["mode"] = "bootstrap_timeout"
    with pytest.raises(RuntimeError, match="RECOVERY_FAILED"):
        f.t.switch(plan_path=plan, evidence=evidence, preparation_sha=digest, authorized=True)
    assert f.plist.read_bytes() == desired and f.state["pid"] == 202
    assert f.calls == [("bootout", 101), ("bootstrap", "candidate")]


def test_result_requires_real_date_valid_chain_without_relabeling_business_failures(batch, monkeypatch):
    f = batch
    f.status["scheduler_observation"]["status"] = "RECEIPT_CHAIN_VERIFIED"
    result = f.t.verify_result(f.raw, f.candidate, rollback=False)
    assert result["actual_receipts"]["rows"][0]["status"] == "FAILED"
    f.status["scheduler_observation"]["status"] = "RECEIPT_DATE_MISMATCH"
    with pytest.raises(ValueError, match="TASK_STATUS_DATE_CONTRACT"):
        f.t.verify_result(f.raw, f.candidate, rollback=False)
    restored = f.t.verify_result(f.raw, f.candidate, rollback=True)
    assert restored["task_status"]["scheduler_observation"]["status"] == "RECEIPT_DATE_MISMATCH"
    monkeypatch.setattr(f.t, "probe_receipts", lambda *a: {"receipt_count": 1, "date_valid_count": 0, "chain_valid": True})
    with pytest.raises(ValueError, match="ACTUAL_RECEIPT_DATE_OR_CHAIN_INVALID"):
        f.t.verify_result(f.raw, f.candidate, rollback=False)
