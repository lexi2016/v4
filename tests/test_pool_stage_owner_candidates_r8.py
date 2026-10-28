from __future__ import annotations

import hashlib
import json
import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import build_release_candidate as core
from ops import build_release_candidate_stage as stage_builder
from ops import prepare_pool_stage_owner_candidates as owner_candidate_builder
from ops import stage_service_overlay_contract as overlay_contract


stage_builder.bind_core(core)


def test_scheduler_rebase_resolves_only_the_pinned_reviewed_runtime_closure() -> None:
    payloads, origins = owner_candidate_builder._scheduler_rebase_source_payloads()

    expected_paths = {
        *owner_candidate_builder.SCHEDULER_REBASE_RUNTIME_OVERLAY_PATHS,
        *owner_candidate_builder.SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256,
        *owner_candidate_builder.SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256,
        *owner_candidate_builder.SCHEDULER_REBASE_OWNED_IO_SHA256,
    }
    assert set(payloads) == expected_paths
    assert set(origins) == expected_paths
    assert len(owner_candidate_builder.SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256) == 9
    assert not any(path.startswith("tests/") for path in payloads)
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_PHASE6A_RUNTIME_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_PHASE6B_RUNTIME_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_PRESELECTION_MODULE_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_LOCK_HELPER_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
        assert origins[path]["owner_before_sha256"] == owner_candidate_builder.SCHEDULER_REBASE_LOCK_HELPER_OWNER_BEFORE_SHA256
        assert origins[path]["independent_review_required"] is True
        assert origins[path]["source_kind"] == "EXACT_PINNED_EXISTING_SCHEDULER_LOCK_HELPER_CANDIDATE_ONLY"
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_MISSING_IMPORT_CLOSURE_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
        assert origins[path]["source_kind"] == "EXACT_PINNED_STAGE_IMPORT_CLOSURE_CANDIDATE_ONLY"
        assert origins[path]["owner_path_absent"] is True
        assert origins[path]["independent_review_required"] is True
        assert origins[path]["imported_by_chains"]
        assert origins[path]["import_closure_report_sha256"] == (
            owner_candidate_builder.SCHEDULER_REBASE_IMPORT_CLOSURE_REPORT_SHA256
        )
    for path, expected_sha in owner_candidate_builder.SCHEDULER_REBASE_OWNED_IO_SHA256.items():
        assert hashlib.sha256(payloads[path]).hexdigest() == expected_sha
        assert origins[path]["source_kind"] == (
            "EXACT_PINNED_EXISTING_STAGE_API_SAFEROOT_PAIR_CANDIDATE_ONLY"
        )
        assert origins[path]["owner_before_sha256"] == (
            owner_candidate_builder.SCHEDULER_REBASE_OWNED_IO_OWNER_BEFORE_SHA256
        )
        assert origins[path]["kernel_lock_yields_owned_fd"] is True
        assert origins[path]["independent_review_required"] is True
    assert origins["domains/_preselection_parts/date_catalog.py"]["additional_reviewed_origins"]
    assert origins["domains/_preselection_parts/source_validation.py"]["source_kind"] == (
        "FROZEN_PHASE6B_PRESELECTION_CANDIDATE_ADDITION_PENDING_OWNER_REVIEW"
    )


def test_scheduler_lock_helper_enforces_live_lease_identity_and_safe_release(tmp_path: Path) -> None:
    candidate_app = Path(os.environ.get(
        "R8_SCHEDULER_CANDIDATE_APP", str(owner_candidate_builder.REPO_ROOT)
    )).resolve()
    runtime_python = os.environ.get("R8_SCHEDULER_CANDIDATE_PYTHON")
    command = [runtime_python or sys.executable]
    if runtime_python:
        command.append("-S")
    command.extend(("-c", '''
import dataclasses, json, os, pathlib, sys
app = pathlib.Path(sys.argv[1]).resolve()
scratch = pathlib.Path(sys.argv[2]).resolve()
scratch.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(app))
from infrastructure import interprocess_lock as locks
module_path = pathlib.Path(locks.__file__).resolve()
if not module_path.is_relative_to(app):
    raise AssertionError(f"lock helper imported outside candidate app: {module_path}")
lock_path = scratch / "lease.lock"
lease = None
successor = None
with locks.owned_interprocess_lock(lock_path, timeout_seconds=2, timeout_message="timeout") as active:
    lease = active
    locks.assert_owned_interprocess_lock(active, lock_path)
    try:
        locks.assert_owned_interprocess_lock(active, scratch / "other.lock")
    except ValueError as exc:
        wrong_path = str(exc)
    else:
        raise AssertionError("wrong lock path was accepted")
    forged = dataclasses.replace(active)
    try:
        locks.assert_owned_interprocess_lock(forged, lock_path)
    except ValueError as exc:
        forged_lease = str(exc)
    else:
        raise AssertionError("copied lock lease was accepted")
    lock_path.unlink()
    successor = locks._owner_bytes(os.getpid() + 1, "successor")
    lock_path.write_bytes(successor)
    try:
        locks.assert_owned_interprocess_lock(active, lock_path)
    except ValueError as exc:
        changed_owner = str(exc)
    else:
        raise AssertionError("changed owner identity was accepted")
if lock_path.read_bytes() != successor:
    raise AssertionError("release deleted a successor owner record")
try:
    locks.assert_owned_interprocess_lock(lease, lock_path)
except ValueError as exc:
    expired_lease = str(exc)
else:
    raise AssertionError("expired lock lease was accepted")
print(json.dumps({
    "status": "PASS", "module_path": str(module_path),
    "wrong_path": wrong_path, "forged_lease": forged_lease,
    "changed_owner": changed_owner, "expired_lease": expired_lease,
    "successor_preserved": True,
}, sort_keys=True))
''', str(candidate_app), str(tmp_path)))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(candidate_app)
    completed = subprocess.run(command, capture_output=True, text=True, check=False, env=environment)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert Path(result["module_path"]).is_relative_to(candidate_app)
    assert result["wrong_path"] == "OWNER_LOCK_LEASE_PATH_MISMATCH"
    assert result["forged_lease"] == "OWNER_LOCK_LEASE_NOT_ACTIVE"
    assert result["changed_owner"] == "OWNER_LOCK_LEASE_IDENTITY_CHANGED"
    assert result["expired_lease"] == "OWNER_LOCK_LEASE_NOT_ACTIVE"
    assert result["successor_preserved"] is True


def test_scheduler_candidate_safroot_scope_gate_and_store_callers(
    tmp_path: Path,
) -> None:
    candidate_app = Path(os.environ.get(
        "R8_SCHEDULER_CANDIDATE_APP", str(owner_candidate_builder.REPO_ROOT)
    )).resolve()
    runtime_python = os.environ.get("R8_SCHEDULER_CANDIDATE_PYTHON")
    probe = '''
import hashlib, json, os, pathlib, stat, sys
app = pathlib.Path(sys.argv[1]).resolve()
scratch = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(app))
from infrastructure import owned_io, interprocess_lock, preselection_pool_store, scope_gate
for module in (owned_io, interprocess_lock, preselection_pool_store, scope_gate):
    origin = pathlib.Path(module.__file__).resolve()
    if not origin.is_relative_to(app):
        raise AssertionError(f"module escaped candidate app: {module.__name__}: {origin}")
safe_root = owned_io.SafeRoot(scratch / "safe-root")
safe_root.ensure_directory()
try:
    safe_root.read_bytes("../outside")
except owned_io.OwnedIOError as exc:
    unsafe_path = str(exc)
else:
    raise AssertionError("SafeRoot accepted parent traversal")
with safe_root.kernel_lock("descriptor-probe.mutex") as descriptor:
    if not isinstance(descriptor, int) or not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise AssertionError("SafeRoot kernel_lock did not yield its held regular-file descriptor")

data_root = scratch / "scoped-data"
control_dir = scratch / "control"
source_root = scratch / "source"
for path in (data_root, control_dir, source_root):
    path.mkdir(parents=True)
keys = [{"business_key":"candidate-scope-fixture", "trade_date":"20260918",
         "pool_id":"a_share_research_recommendation_pool"}]
permit = {
    "schema_version": scope_gate.PERMIT_SCHEMA,
    "decision_id":"candidate-scope-fixture",
    "owner_id":"candidate-test-owner",
    "source_release_sha256":"c" * 64,
    "target_release_sha256":"b" * 64,
    "source_root":str(source_root),
    "target_root":str(data_root),
    "keys":keys,
    "business_key_set_sha256":hashlib.sha256(scope_gate.canonical_bytes(keys)).hexdigest(),
}
permit_bytes = scope_gate.canonical_bytes(permit)
(control_dir / "permit.json").write_bytes(permit_bytes)
context = scope_gate.StoreGateContext(
    control_dir=control_dir,
    expected_permit_sha256=hashlib.sha256(permit_bytes).hexdigest(),
    expected_owner_id="candidate-test-owner",
    expected_release_sha256="b" * 64,
    expected_root=data_root,
)
store = preselection_pool_store.PreselectionPoolStore(
    data_root, write_gate_context=context, require_write_gate_context=True,
)
fenced = store.set_write_gate(expected_revision=0, state="FENCED")
if fenced.get("revision") != 1 or fenced.get("state") != "FENCED":
    raise AssertionError(f"scope-gated store transition mismatch: {fenced}")
wrong_root = scratch / "wrong-root"
wrong_store = preselection_pool_store.PreselectionPoolStore(
    wrong_root, write_gate_context=context, require_write_gate_context=True,
)
try:
    wrong_store.set_write_gate(expected_revision=0, state="FENCED")
except scope_gate.GateConfigurationError as exc:
    root_rejected = str(exc)
else:
    raise AssertionError("scope gate accepted a store at an unpermitted root")
if wrong_root.exists():
    raise AssertionError("wrong-root scope failure created a data root")
print(json.dumps({
    "status":"PASS",
    "module_origins":{m.__name__:str(pathlib.Path(m.__file__).resolve()) for m in
                       (owned_io,interprocess_lock,preselection_pool_store,scope_gate)},
    "unsafe_path_rejected":unsafe_path,
    "kernel_lock_descriptor":True,
    "scope_fenced_revision":fenced["revision"],
    "wrong_root_rejected":root_rejected,
    "wrong_root_created":False,
},sort_keys=True))
'''
    command = [runtime_python or sys.executable]
    if runtime_python:
        command.append("-S")
    command.extend(("-c", probe, str(candidate_app), str(tmp_path)))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(candidate_app)
    completed = subprocess.run(command, capture_output=True, text=True, check=False, env=environment)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["unsafe_path_rejected"] == "OWNED_PATH_UNSAFE"
    assert result["kernel_lock_descriptor"] is True
    assert result["scope_fenced_revision"] == 1
    assert "configured root does not match store root" in result["wrong_root_rejected"]
    assert result["wrong_root_created"] is False
    assert all(Path(path).is_relative_to(candidate_app) for path in result["module_origins"].values())


def test_scheduler_import_canary_uses_owner_bound_python_and_candidate_only_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "candidate-output"
    (output_root / "scheduler").mkdir(parents=True)
    candidate_app = tmp_path / "candidate-release" / "app"
    module_path = candidate_app / "example" / "module.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    (candidate_app / "upstreams").mkdir()
    runtime_root = tmp_path / "runtime"
    python_executable = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_text("synthetic runtime interpreter\n", encoding="utf-8")
    python_executable.chmod(0o755)
    site_packages = runtime_root / "venvs" / "v3.5-mac" / "lib" / "python3.14" / "site-packages"
    site_packages.mkdir(parents=True)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        calls.append((command, env))
        if "-c" in command:
            return subprocess.CompletedProcess(command, 0, stdout="3.14\n", stderr="")
        modules = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        rows = [{
            "module": name,
            "origin": str(candidate_app / Path(*name.split(".")).with_suffix(".py")),
        } for name in modules]
        return subprocess.CompletedProcess(
            command, 0,
            stdout=json.dumps({"status": "PASS", "candidate_app": str(candidate_app), "module_origins": rows}),
            stderr="",
        )

    monkeypatch.setattr(owner_candidate_builder.subprocess, "run", run)
    inventory = core.inventory_tree(candidate_app)
    result = owner_candidate_builder._run_scheduler_candidate_import_canary(
        root=output_root,
        candidate_app=candidate_app,
        module_paths=["example/module.py"],
        expected_inventory=inventory,
        runtime_root=runtime_root,
    )

    expected_pythonpath = os.pathsep.join((
        str(candidate_app), str(site_packages), str(candidate_app / "upstreams"), str(candidate_app),
    ))
    assert result["status"] == "PASS"
    assert result["runtime_python"] == str(python_executable)
    assert result["runtime_python_version"] == "3.14"
    assert len(calls) == 2
    assert calls[0][0][:2] == [str(python_executable), "-S"]
    assert calls[1][0][:2] == [str(python_executable), "-S"]
    assert calls[1][1]["PYTHONPATH"] == expected_pythonpath
    assert calls[1][1]["PYTHONDONTWRITEBYTECODE"] == "1"


def _scheduler_identity_fixture(tmp_path: Path) -> tuple[dict[str, object], Path, Path, Path]:
    owner_app = tmp_path / "owner" / "app"
    owner_launcher = owner_app / "ops" / "launch_v35_macos_scheduler.sh"
    owner_launcher.parent.mkdir(parents=True)
    owner_launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    (owner_app / "upstreams").mkdir()
    candidate_root = tmp_path / "candidate-release"
    candidate_app = candidate_root / "app"
    candidate_launcher = candidate_app / "ops" / "launch_v35_macos_scheduler.sh"
    candidate_launcher.parent.mkdir(parents=True)
    candidate_launcher.write_text("#!/bin/bash\n", encoding="utf-8")
    (candidate_app / "upstreams").mkdir()
    manifest_path = candidate_root / "release-manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    source_plist = {
        "Label": "com.lexi.v35.scheduler",
        "ProgramArguments": ["/bin/bash", str(owner_launcher)],
        "WorkingDirectory": str(owner_app),
        "EnvironmentVariables": {
            "V35_APP_ROOT": str(owner_app),
            "V35_RELEASE_ID": "scheduler-owner-r2",
            "V35_RELEASE_MANIFEST_PATH": str(owner_app.parent / "release-manifest.json"),
            "V35_RELEASE_MANIFEST_SHA256": "b" * 64,
            "PYTHONPATH": str(owner_app / "upstreams") + os.pathsep + str(owner_app),
            "V35_DATA_ROOT": str(tmp_path / "external-data"),
            "V35_PRESELECTION_INPUT_ROOT": str(tmp_path / "external-inputs"),
            "V35_SHARED_DATA_ROOT": str(tmp_path / "external-shared"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "external-stage"),
            "V35_REVIEW_CORE_CLOSE_ROOT": str(tmp_path / "external-close"),
            "V35_DAEMON_MODE": "persistent-minute",
            "production_allowed": "false",
            "buy_gate_updated": "false",
            "orders_sent": "false",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        },
        "StartInterval": 60,
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    source_path = tmp_path / "owner.plist"
    source_path.write_bytes(plistlib.dumps(source_plist, fmt=plistlib.FMT_XML, sort_keys=True))
    return source_plist, source_path, owner_app, candidate_root


def test_scheduler_identity_render_replaces_only_candidate_code_roots(tmp_path: Path) -> None:
    source_plist, source_path, owner_app, candidate_root = _scheduler_identity_fixture(tmp_path)
    candidate_id = "scheduler-candidate"
    manifest_path = candidate_root / "release-manifest.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    rendered = core._stage_scheduler_identity(
        source_plist=source_path,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
    )
    candidate_plist = plistlib.loads(Path(str(rendered["path"])).read_bytes())
    proof = owner_candidate_builder._verify_scheduler_identity_render(
        source_plist=source_plist,
        candidate_plist=candidate_plist,
        owner_app=owner_app,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
    )

    candidate_app = candidate_root / "app"
    assert proof["status"] == "PASS"
    assert proof["candidate_pythonpath"] == str(candidate_app / "upstreams") + os.pathsep + str(candidate_app)
    assert candidate_plist["EnvironmentVariables"]["V35_DATA_ROOT"] == source_plist["EnvironmentVariables"]["V35_DATA_ROOT"]
    assert candidate_plist["EnvironmentVariables"]["V35_DAEMON_MODE"] == "persistent-minute"
    assert candidate_plist["StartInterval"] == source_plist["StartInterval"]
    assert candidate_plist["RunAtLoad"] is True
    assert candidate_plist["KeepAlive"] is True


def test_scheduler_identity_render_rejects_external_root_or_schedule_drift(tmp_path: Path) -> None:
    source_plist, source_path, owner_app, candidate_root = _scheduler_identity_fixture(tmp_path)
    candidate_id = "scheduler-candidate"
    manifest_path = candidate_root / "release-manifest.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    rendered = core._stage_scheduler_identity(
        source_plist=source_path,
        candidate_root=candidate_root,
        release_id=candidate_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
    )
    candidate_plist = plistlib.loads(Path(str(rendered["path"])).read_bytes())
    candidate_plist["EnvironmentVariables"]["V35_DATA_ROOT"] = str(tmp_path / "wrong-root")

    with pytest.raises(ValueError, match="environment changed outside the exact owner-root identity render"):
        owner_candidate_builder._verify_scheduler_identity_render(
            source_plist=source_plist,
            candidate_plist=candidate_plist,
            owner_app=owner_app,
            candidate_root=candidate_root,
            release_id=candidate_id,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
        )


def test_generated_stage_consumer_compat_adds_only_source_evidence_from_exact_owner() -> None:
    owner = Path(
        "/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/"
        "candidate_source_closure_frozen_owner/stage_center/consumer.py"
    ).read_bytes()
    generated, receipt = stage_builder.generate_stage_consumer_source_evidence_compat(owner)

    assert hashlib.sha256(owner).hexdigest() == stage_builder.STAGE_CONSUMER_COMPAT_OWNER_SHA256
    assert receipt["classification"] == "GENERATED_COMPAT_SOURCE_CANDIDATE_ONLY"
    assert receipt["added_line_count"] == 1
    assert receipt["removed_line_count"] == 0
    assert receipt["unified_diff_hunk_count"] == 1
    assert hashlib.sha256(generated).hexdigest() == receipt["candidate_after_sha256"]
    assert generated.count(stage_builder.STAGE_CONSUMER_SOURCE_EVIDENCE_LINE) == 1
    assert b'"source_evidence"' not in owner
    assert generated.replace(stage_builder.STAGE_CONSUMER_SOURCE_EVIDENCE_LINE, b"", 1) == owner


def test_generated_stage_consumer_compat_rejects_unknown_owner_and_pattern_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Path(
        "/Users/lexi/Desktop/学习/agents调试/V4_POOL_STAGE_HK_IMPLEMENTATION_20261012_R8/"
        "candidate_source_closure_frozen_owner/stage_center/consumer.py"
    ).read_bytes()
    with pytest.raises(ValueError, match="unknown owner SHA"):
        stage_builder.generate_stage_consumer_source_evidence_compat(owner + b"# unknown\n")

    changed_pattern = owner.replace(
        b'        "cannot_confirm": list(envelope.get("cannot_confirm") or []),',
        b'        "cannot_confirm": list(envelope.get("cannot_confirm") or []), # drift',
        1,
    )
    monkeypatch.setattr(
        stage_builder,
        "STAGE_CONSUMER_COMPAT_OWNER_SHA256",
        hashlib.sha256(changed_pattern).hexdigest(),
    )
    with pytest.raises(ValueError, match="one-field compatibility grammar"):
        stage_builder.generate_stage_consumer_source_evidence_compat(changed_pattern)


def _entry(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    info = path.stat()
    return {
        "path": relative,
        "kind": "file",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "size": info.st_size,
    }


def test_stage_inventory_verifier_rejects_noncanonical_and_duplicate_paths(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "a.txt").write_text("bound bytes", encoding="utf-8")
    actual = core.inventory_tree(app)

    with pytest.raises(ValueError, match="duplicate path"):
        stage_builder._verify_stage_release_inventory(
            app_root=app,
            stored_entries=[actual[0], actual[0]],
            actual_entries=actual,
            allow_pinned_cache_exclusions=False,
        )

    noncanonical = {**actual[0], "path": "./a.txt"}
    with pytest.raises(ValueError, match="not canonical"):
        stage_builder._verify_stage_release_inventory(
            app_root=app,
            stored_entries=[noncanonical],
            actual_entries=actual,
            allow_pinned_cache_exclusions=False,
        )


def test_stage_inventory_verifier_checks_each_pinned_generated_cache_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = tmp_path / "app"
    cache = app / "pkg" / "__pycache__" / "module.cpython-314.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"one pinned generated bytecode entry")
    expected = _entry(app, "pkg/__pycache__/module.cpython-314.pyc")
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_CACHE_ENTRY_COUNT", 1)
    monkeypatch.setattr(
        stage_builder,
        "PINNED_LEGACY_STAGE_CACHE_INVENTORY_SHA256",
        core.inventory_digest([expected]),
    )

    missing = stage_builder._verify_stage_release_inventory(
        app_root=app,
        stored_entries=[expected],
        actual_entries=[],
        allow_pinned_cache_exclusions=True,
    )
    assert missing["excluded_cache_entries"] == [expected]
    assert missing["entry_sha256_validation"]["entry_count"] == 1
    assert missing["entry_sha256_validation"]["all_entries_actual_sha256_verified"] is True

    cache.write_bytes(b"changed generated bytecode entry")
    with pytest.raises(ValueError, match="file SHA-256 mismatch"):
        stage_builder._verify_stage_release_inventory(
            app_root=app,
            stored_entries=[expected],
            actual_entries=[],
            allow_pinned_cache_exclusions=True,
        )


def test_stage_overlay_source_override_uses_only_exact_pinned_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = "infrastructure/_stage_acquisition_universe_commit_parts/artifact_validation.py"
    source_root = tmp_path / "source"
    canonical = source_root / relative
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"different canonical bytes")
    frozen = tmp_path / "frozen-artifact-validation.py"
    frozen.write_bytes(b"exact pinned source bytes")
    expected_sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
    monkeypatch.setattr(
        overlay_contract,
        "STAGE_SERVICE_RELEASE_CLOSURE_SHA256",
        {relative: expected_sha},
    )

    overrides = {relative: frozen}
    overlay_contract.require_stage_overlay_source_hashes(
        source_root=source_root,
        overlay_paths=(relative,),
        source_overrides=overrides,
    )
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline_file = baseline / relative
    baseline_file.parent.mkdir(parents=True)
    baseline_file.write_bytes(b"baseline bytes")
    candidate.mkdir()
    records, changed = stage_builder._copy_stage_overlay(
        source_root=source_root,
        candidate_app=candidate,
        baseline_app=baseline,
        overlay_paths=(relative,),
        active_config={},
        source_overrides=overrides,
    )

    assert (candidate / relative).read_bytes() == frozen.read_bytes()
    assert records[0]["source_workspace_sha256"] == expected_sha
    assert records[0]["source_provenance"] == "PINNED_SOURCE_OVERRIDE"
    assert relative in changed

    frozen.write_bytes(b"drifted frozen source bytes")
    with pytest.raises(ValueError, match="Stage overlay closure source SHA-256 mismatch"):
        overlay_contract.require_stage_overlay_source_hashes(
            source_root=source_root,
            overlay_paths=(relative,),
            source_overrides=overrides,
        )


def test_nonstrict_r4_overlay_uses_existing_nodes_entry_and_strict_still_fails_closed(
    tmp_path: Path,
) -> None:
    worker = "ops/run_stage_center_worker.py"
    commit_store = "stage_center/commit_store.py"
    assert worker not in overlay_contract.STAGE_SERVICE_BASE_OVERLAY_PATHS
    assert worker not in overlay_contract.STAGE_SERVICE_OVERLAY_PATHS
    assert commit_store not in overlay_contract.STAGE_SERVICE_BASE_OVERLAY_PATHS
    assert commit_store not in overlay_contract.STAGE_SERVICE_OVERLAY_PATHS
    assert worker in overlay_contract.STRICT_STAGE_SERVICE_OVERLAY_PATHS
    assert commit_store in overlay_contract.STRICT_STAGE_SERVICE_OVERLAY_PATHS

    source_root = tmp_path / "source"
    source_root.mkdir()
    with pytest.raises(ValueError, match="strict Stage overlay requires"):
        overlay_contract.require_complete_strict_stage_overlay(
            source_root=source_root,
            overlay_paths=overlay_contract.STAGE_SERVICE_OVERLAY_PATHS,
            effective_config={"publication_mode": "strict_commit_required"},
        )

def _write_pinned_inventory_mismatch_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object], str, str]:
    release_root = tmp_path / "pinned-stage-r4"
    app = release_root / "app"
    script = app / "ops" / "run_stage_center_nodes.py"
    config = app / "stage_center_tick_config.json"
    script.parent.mkdir(parents=True)
    script.write_text("# inert test entrypoint\n", encoding="utf-8")
    config.write_text(
        json.dumps({
            "release_id": "pinned-stage-r1-config",
            "preselection_source_root": str(tmp_path / "source"),
        }, sort_keys=True),
        encoding="utf-8",
    )
    preserved = app / "infrastructure" / "_stage_acquisition_universe_contracts_parts" / "snapshot_provenance.py"
    preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"# exact synthetic owner-base closure bytes\n")
    entries = core.inventory_tree(app)
    recomputed_sha = core.inventory_digest(entries)
    manifest = {
        "schema_version": "v4.legacy-release.v1",
        "release_id": "pinned-stage-r4",
        "release_root": str(release_root),
        "app_root": str(app),
        "application_inventory": {
            "entries": entries,
            "aggregate_sha256": "0" * 64,
        },
    }
    manifest_path = release_root / "release-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    plist_path = tmp_path / "stage.plist"
    plist_payload = {
        "Label": "com.lexi.stage-center.scheduler",
        "ProgramArguments": ["/usr/bin/python3", "-u", str(script), "--config", str(config)],
        "EnvironmentVariables": {},
    }
    plist_path.write_bytes(plistlib.dumps(plist_payload))
    return plist_path, manifest_path, manifest, manifest_sha, config_sha


def test_stage_legacy_aggregate_mismatch_is_pinned_to_exact_byte_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plist_path, manifest_path, manifest, manifest_sha, config_sha = (
        _write_pinned_inventory_mismatch_fixture(tmp_path)
    )
    preserved_path = (
        manifest_path.parent / "app" / "infrastructure" /
        "_stage_acquisition_universe_contracts_parts" / "snapshot_provenance.py"
    )
    preserved_sha = hashlib.sha256(preserved_path.read_bytes()).hexdigest()
    preserved_pins = {
        "infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_provenance.py": preserved_sha,
    }
    monkeypatch.setattr(overlay_contract, "STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS", preserved_pins)
    monkeypatch.setattr(stage_builder, "STAGE_SERVICE_BASE_PRESERVED_SOURCE_PATHS", preserved_pins)
    declared_sha = str(manifest["application_inventory"]["aggregate_sha256"])
    recomputed_sha = core.inventory_digest(manifest["application_inventory"]["entries"])
    monkeypatch.setattr(overlay_contract, "PINNED_LEGACY_STAGE_RELEASE_ID", "pinned-stage-r4")
    monkeypatch.setattr(
        overlay_contract, "PINNED_LEGACY_STAGE_CONFIG_RELEASE_ID", "pinned-stage-r1-config"
    )
    monkeypatch.setattr(overlay_contract, "PINNED_LEGACY_STAGE_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(overlay_contract, "PINNED_LEGACY_STAGE_CONFIG_SHA256", config_sha)
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_RELEASE_ID", "pinned-stage-r4")
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_CONFIG_RELEASE_ID", "pinned-stage-r1-config")
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_CONFIG_SHA256", config_sha)
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_DECLARED_INVENTORY_SHA256", declared_sha)
    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_RECOMPUTED_INVENTORY_SHA256", recomputed_sha)

    active = stage_builder._active_stage_release(plist_path)
    assert active["inventory_digest_compatibility"] == {
        "status": "EXACT_PINNED_LEGACY_METADATA_MISMATCH",
        "manifest_sha256": manifest_sha,
        "config_sha256": config_sha,
        "declared_inventory_sha256": declared_sha,
        "recomputed_inventory_sha256": recomputed_sha,
        "validation_after_exception": "all manifest rows compared against the app; only the 100 separately pinned generated bytecode rows may be excluded from generic inventory",
    }

    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_DECLARED_INVENTORY_SHA256", "f" * 64)
    with pytest.raises(ValueError, match="inventory manifest digest mismatch"):
        stage_builder._active_stage_release(plist_path)

    monkeypatch.setattr(stage_builder, "PINNED_LEGACY_STAGE_DECLARED_INVENTORY_SHA256", declared_sha)
    monkeypatch.setattr(overlay_contract, "PINNED_LEGACY_STAGE_CONFIG_SHA256", "f" * 64)
    with pytest.raises(ValueError, match="config.release_id"):
        stage_builder._active_stage_release(plist_path)


def test_phase_b_api_source_delta_is_exact_frozen_phase_a_triplet() -> None:
    source_bytes, categories = owner_candidate_builder._phase_b_api_client_source_bytes()

    assert set(source_bytes) == set(owner_candidate_builder.PHASE_A_CLIENT_SOURCE_SHA256)
    assert set(categories.values()) == {"REVIEWED_PHASE_A_CLIENT_SOURCE"}
    for relative, expected_sha in owner_candidate_builder.PHASE_A_CLIENT_SOURCE_SHA256.items():
        assert hashlib.sha256(source_bytes[relative]).hexdigest() == expected_sha
    assert owner_candidate_builder.API_STAGE_CLIENT_REBASE_OUTPUT_ROOT != (
        owner_candidate_builder.CURRENT_API_OWNER_ROOT
    )
    assert owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID != (
        owner_candidate_builder.CURRENT_API_OWNER_RELEASE_ID
    )


def test_phase_b_api_owner_receipt_rejects_changed_v24_identity_pin() -> None:
    identity = owner_candidate_builder._read_json(
        owner_candidate_builder.CURRENT_API_OWNER_FOR_STAGE_CLIENT_REPAIR
    )
    owner_candidate_builder._validate_current_api_owner_receipt(identity)

    changed = dict(identity)
    changed["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="manifest_sha256"):
        owner_candidate_builder._validate_current_api_owner_receipt(changed)


def test_phase_b_staged_api_plist_preserves_roots_and_schedule(tmp_path: Path) -> None:
    candidate_root = tmp_path / owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID
    candidate_app = candidate_root / "app"
    manifest_path = candidate_root / "release-manifest.json"
    manifest_sha = "d" * 64
    source = {
        "Label": "com.lexi.v35.api-only",
        "ProgramArguments": [
            "/usr/bin/env",
            "V35_APP_ROOT=/active/app",
            "PYTHONPATH=/active/app/upstreams:/active/app",
            "V35_RELEASE_ID=active-api",
            "V35_RELEASE_MANIFEST_PATH=/active/release-manifest.json",
            "V35_RELEASE_MANIFEST_SHA256=" + "a" * 64,
            "V35_API_ROLE=gateway",
            "V35_API_PORT=8873",
            "-m", "apps.api.v35_api.run", "--host", "127.0.0.1", "--port", "8873",
        ],
        "WorkingDirectory": "/active/app",
        "EnvironmentVariables": {
            "V35_APP_ROOT": "/active/app",
            "PYTHONPATH": "/active/app/upstreams:/active/app",
            "V35_RELEASE_ID": "active-api",
            "V35_RELEASE_MANIFEST_PATH": "/active/release-manifest.json",
            "V35_RELEASE_MANIFEST_SHA256": "a" * 64,
            "V35_API_ROLE": "gateway",
            "V35_API_PORT": "8873",
            "V35_DATA_ROOT": "/research/data",
            "V35_SHARED_DATA_ROOT": "/research/shared",
            "RESEARCH_ONLY": "true",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StartCalendarInterval": [{"Hour": 9, "Minute": 30}],
        "ProcessType": "Background",
    }
    staged = dict(source)
    staged["ProgramArguments"] = [
        "/usr/bin/env",
        f"V35_APP_ROOT={candidate_app}",
        f"PYTHONPATH={candidate_app / 'upstreams'}:{candidate_app}",
        f"V35_RELEASE_ID={owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID}",
        f"V35_RELEASE_MANIFEST_PATH={manifest_path}",
        "V35_RELEASE_MANIFEST_SHA256=" + manifest_sha,
        "V35_API_ROLE=gateway",
        "V35_API_PORT=8873",
        "-m", "apps.api.v35_api.run", "--host", "127.0.0.1", "--port", "8873",
    ]
    staged["WorkingDirectory"] = str(candidate_app)
    staged["EnvironmentVariables"] = {
        **source["EnvironmentVariables"],
        "V35_APP_ROOT": str(candidate_app),
        "PYTHONPATH": f"{candidate_app / 'upstreams'}:{candidate_app}",
        "V35_RELEASE_ID": owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
    }
    staged_path = tmp_path / "staged-api.plist"
    staged_path.write_bytes(plistlib.dumps(staged))

    class ApiReleaseStub:
        @staticmethod
        def module_role_contract() -> dict[str, object]:
            return {"roles": {"gateway": {"port": 8873}}}

        @staticmethod
        def read_active_release(path: Path, *, role: str) -> dict[str, str]:
            assert path == staged_path
            assert role == "gateway"
            return {
                "release_root": str(candidate_root),
                "app_root": str(candidate_app),
                "release_id": owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID,
                "release_manifest_sha256": manifest_sha,
                "release_manifest_path": str(manifest_path),
            }

    proof = owner_candidate_builder._verify_stage_client_candidate_plist(
        source_plist_path=_write_test_plist(tmp_path / "source-api.plist", source),
        staged_record={"path": str(staged_path), "sha256": hashlib.sha256(staged_path.read_bytes()).hexdigest()},
        candidate_root=candidate_root,
        candidate_release_id=owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID,
        manifest_sha256=manifest_sha,
        api_release=ApiReleaseStub,
    )
    assert proof["status"] == "PASS"
    assert proof["external_environment_values_preserved"] is True

    changed = plistlib.loads(staged_path.read_bytes())
    changed["EnvironmentVariables"]["V35_DATA_ROOT"] = "/wrong/data"
    staged_path.write_bytes(plistlib.dumps(changed))
    with pytest.raises(ValueError, match="external LaunchAgent environment value"):
        owner_candidate_builder._verify_stage_client_candidate_plist(
            source_plist_path=tmp_path / "source-api.plist",
            staged_record={"path": str(staged_path), "sha256": hashlib.sha256(staged_path.read_bytes()).hexdigest()},
            candidate_root=candidate_root,
            candidate_release_id=owner_candidate_builder.API_STAGE_CLIENT_CANDIDATE_ID,
            manifest_sha256=manifest_sha,
            api_release=ApiReleaseStub,
        )


def _write_test_plist(path: Path, payload: dict[str, object]) -> Path:
    path.write_bytes(plistlib.dumps(payload))
    return path
