#!/usr/bin/env python3
"""Isolated probes of the frozen R2 cutover reference; never operate services."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import tempfile
import types
import uuid


WORK = Path(__file__).resolve().parent
INPUT = WORK.parents[1] / "input/baseline"
SCRIPT = INPUT / "source/actual_cutover_reference/api_only_cutover_r2_ready.py"
SCRIPT_SHA = "ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a"
INTEGRATION = INPUT / "source/unreviewed_draft/ops/api_release_integration.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def blocked(*args, **kwargs):
    raise AssertionError("REAL_RUNTIME_OR_HTTP_OPERATION_FORBIDDEN_IN_PROBE")


def load_source(path: Path, name: str):
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), mod.__dict__)
    return mod


def cutover():
    assert sha(SCRIPT.read_bytes()) == SCRIPT_SHA
    mod = load_source(SCRIPT, "_cutover_probe_" + uuid.uuid4().hex)
    mod._launchctl_action = blocked
    mod._launchctl_print = blocked
    mod._http_get = blocked
    return mod


def write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def write_json(path: Path, value) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    write(path, raw)
    return sha(raw)


def probe_task_private_locks(root: Path):
    a, b = cutover(), cutover()
    a.EVIDENCE_ROOT = root / "task-a"
    b.EVIDENCE_ROOT = root / "task-b"
    pointer = root / "LaunchAgents/com.lexi.v35.api-only.plist"
    a.ACTIVE_API_PLIST = b.ACTIVE_API_PLIST = pointer
    with a._switch_lock():
        same_task_rejected = False
        try:
            with a._switch_lock():
                pass
        except BlockingIOError:
            same_task_rejected = True
        with b._switch_lock():
            different_task_acquired_simultaneously = True
    assert same_task_rejected and different_task_acquired_simultaneously
    return {
        "same_active_pointer": True,
        "same_task_second_lock_rejected": same_task_rejected,
        "different_task_second_lock_acquired_while_first_held": different_task_acquired_simultaneously,
        "finding": "TASK_PRIVATE_LOCK_DOES_NOT_SERIALIZE_API_PUBLISHERS",
    }


def probe_stale_package_preflight(root: Path, module=None):
    m = module if module is not None else cutover()
    inventory = load_source(INTEGRATION, "_inventory_probe")
    m.TASK_ROOT = root / "task"
    m.EVIDENCE_ROOT = m.TASK_ROOT / "evidence"
    m.STAGED_API_PLIST_PATH = m.EVIDENCE_ROOT / "staged/api.plist"
    m.STAGED_API_PLIST_DIFF_PATH = m.EVIDENCE_ROOT / "staged/api.diff.json"
    m.API_INVENTORY_RECEIPT_PATH = m.EVIDENCE_ROOT / "inventory.json"
    m.RELEASE_STAGE_RECEIPT_PATH = m.EVIDENCE_ROOT / "stage.json"
    m.DISABLED_BINDING_PATH = root / "disabled-binding.json"
    write_json(m.DISABLED_BINDING_PATH, {"enabled": False})

    source = m.TASK_ROOT / "candidate/api/app"
    m.INVENTORY_BACKEND_PATH = source / "ops/build_release_candidate.py"
    write(m.INVENTORY_BACKEND_PATH, INTEGRATION.read_bytes())
    write(source / "manager.py", b"manager_generation = 'old_snapshot'\n")
    write(source / "apps/web/dist/manager-selection/index.html", b'<script src="/assets/probe.js"></script>')
    write(source / "apps/web/dist/assets/probe.js", b"/* synthetic byte fixture */\n")
    release = root / "releases/candidate-r2"
    shutil.copytree(source, release / "app")
    entries = inventory.inventory_tree(release / "app")
    digest = inventory.inventory_digest(entries)
    m.EXPECTED_API_INVENTORY_SHA256 = digest
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "activation_status": "NOT_ACTIVATED",
        "candidate": {"root": str(release), "app_root": str(release / "app"), "release_id": release.name},
        "application_inventory": {"aggregate_sha256": digest, "entries": entries, "entry_count": len(entries)},
    }
    manifest_sha = write_json(release / "release-manifest.json", manifest)
    m.API_INVENTORY_RECEIPT_SHA256 = write_json(m.API_INVENTORY_RECEIPT_PATH, {"aggregate_sha256": digest})
    m.P2_DELTA_RECEIPT_SHA256 = write_json(m.TASK_ROOT / "receipts/p2_delta_receipt.json", {
        "dist_sync": {"same_paths_and_bytes": True,
                      "source_tree_sha256": m.EXPECTED_DIST_TREE_SHA256,
                      "target_tree_sha256": m.EXPECTED_DIST_TREE_SHA256},
    })
    stage_unsigned = {
        "status": "STAGED_AND_VERIFIED_NOT_DEPLOYED", "release_root": str(release),
        "release_manifest_sha256": manifest_sha, "application_inventory_sha256": digest,
        "application_inventory_entries": len(entries),
    }
    stage_sha = write_json(m.RELEASE_STAGE_RECEIPT_PATH,
                           {**stage_unsigned, "receipt_sha256": m._canonical_sha(stage_unsigned)})

    active = root / "releases/current-integrated"
    write(active / "app/manager.py", b"manager_generation = 'current_with_accepted_fix'\n")
    write(active / "app/preselection.py", b"accepted_preselection_fix = True\n")
    active_entries = inventory.inventory_tree(active / "app")
    active_manifest_sha = write_json(active / "release-manifest.json", {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"root": str(active), "app_root": str(active / "app"), "release_id": active.name},
        "application_inventory": {"aggregate_sha256": inventory.inventory_digest(active_entries),
                                  "entries": active_entries, "entry_count": len(active_entries)},
    })
    env = {
        "V35_APP_ROOT": str(active / "app"), "V35_RELEASE_ID": active.name,
        "V35_RELEASE_MANIFEST_PATH": str(active / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": active_manifest_sha,
        "PYTHONPATH": str(active / "app"),
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(m.DISABLED_BINDING_PATH),
        "V4_MANAGER_SCREEN_AUTHORITY_ROOT": str(m.SCREEN_AUTHORITY_ROOT),
        **m.SAFETY_EXPECTED,
    }
    active_raw = plistlib.dumps({
        "Label": m.LABEL, "KeepAlive": True, "RunAtLoad": False,
        "WorkingDirectory": env["V35_APP_ROOT"],
        "ProgramArguments": ["/usr/bin/env", *[f"{k}={v}" for k, v in env.items()],
                             str(m.PINNED_PYTHON), "-m", "synthetic_api"],
    })
    m.ACTIVE_API_PLIST = root / "LaunchAgents/com.lexi.v35.api-only.plist"
    write(m.ACTIVE_API_PLIST, active_raw)
    before_identity = {"state": "running", "pid": "4242", **m._identity_from_plist(active_raw)}
    plan = {
        "target": {"release_root": str(release), "app_root": str(release / "app"),
                   "release_id": release.name, "release_manifest_sha256": manifest_sha,
                   "application_inventory_sha256": digest},
        "source": {"inventory_backend_path": str(m.INVENTORY_BACKEND_PATH),
                   "inventory_backend_sha256": sha(m.INVENTORY_BACKEND_PATH.read_bytes()),
                   "source_candidate_app_root": str(source), "release_stage_receipt_sha256": stage_sha},
        "before": {"active_api_plist_sha256": sha(active_raw), "loaded_identity": before_identity},
    }
    candidate = m._load_candidate_release(plan)
    staged_raw = m._candidate_plist_bytes(active_raw, plan, candidate)
    write(m.STAGED_API_PLIST_PATH, staged_raw)
    plan["target"]["staged_api_plist_sha256"] = sha(staged_raw)
    plan["target"]["staged_api_plist_diff_sha256"] = write_json(
        m.STAGED_API_PLIST_DIFF_PATH, m._staged_plist_diff(active_raw, staged_raw, candidate))
    m._validate_p2_review = lambda _plan: {"fixture": "review outside probe scope"}
    m._validate_business_fix_review = lambda _plan: {"fixture": "review outside probe scope"}
    m._load_disabled_binding = lambda _plan: {"sha256": sha(m.DISABLED_BINDING_PATH.read_bytes())}
    m._verify_readonly_guards = lambda _plan: {"fixture": "scheduler guard outside probe scope"}
    m._launchctl_print = lambda: "\n".join([
        "state = running", "pid = 4242",
        *[f"{k}={v}" for k, v in m._identity_from_plist(active_raw).items()],
    ])
    m._verify_historical_product_readback = lambda: {"fixture": "HTTP unavailable and deliberately not invoked"}
    observed = m._preflight(plan)
    assert observed["status"] == "READY_API_ONLY_R2_CUTOVER"
    assert "api_integration" not in manifest
    assert not (release / "app/preselection.py").exists()
    assert (release / "app/manager.py").read_bytes() != (active / "app/manager.py").read_bytes()
    return {
        "status": observed["status"], "candidate_has_api_integration": False,
        "candidate_omits_accepted_active_file": "preselection.py",
        "candidate_manager_bytes_differ_from_current_active": True,
        "candidate_inventory_and_staged_plist_validation": "ACTUAL_UNMODIFIED_FUNCTIONS",
        "runtime_review_scheduler_and_http": "SYNTHETIC_STUBS_NO_SERVICE_CALLS",
        "finding": "CURRENT_ACTIVE_CONTENT_PRESERVATION_NOT_CHECKED_BY_ACTUAL_PREFLIGHT",
    }


def probe_inventory_backend_reopen(root: Path):
    m = cutover()
    backend = root / "inventory_backend.py"
    trusted = b"MARKER = 'sha_checked_bytes'\ndef inventory_tree(root): return []\ndef inventory_digest(entries): return 'empty'\n"
    replaced = trusted.replace(b"sha_checked_bytes", b"different_bytes_executed")
    write(backend, trusted)
    m.INVENTORY_BACKEND_PATH = backend
    original_spec = importlib.util.spec_from_file_location

    def replace_after_hash(name, location, *args, **kwargs):
        if Path(location) == backend:
            write(backend, replaced)
        return original_spec(name, location, *args, **kwargs)

    importlib.util.spec_from_file_location = replace_after_hash
    try:
        loaded = m._load_inventory_backend({"source": {
            "inventory_backend_path": str(backend), "inventory_backend_sha256": sha(trusted),
        }})
    finally:
        importlib.util.spec_from_file_location = original_spec
    assert loaded.MARKER == "different_bytes_executed"
    return {"sha_checked": sha(trusted), "executed_file_sha": sha(replaced),
            "executed_marker": loaded.MARKER,
            "finding": "PINNED_FILE_IS_REOPENED_AFTER_SHA_CHECK"}


def probe_last_check_replace_race(root: Path):
    m = cutover()
    pointer = root / "com.lexi.v35.api-only.plist"
    before, ours, theirs = b"before\n", b"publisher-a\n", b"publisher-b\n"
    write(pointer, before)
    rival = root / "rival.tmp"
    write(rival, theirs)
    original_replace = os.replace
    injected = False

    def rival_before_replace(src, dst, *args, **kwargs):
        nonlocal injected
        if Path(dst) == pointer and not injected:
            injected = True
            original_replace(rival, pointer)
        return original_replace(src, dst, *args, **kwargs)

    os.replace = rival_before_replace
    try:
        m._atomic_replace_bytes(pointer, ours, pointer, expected_current_sha=sha(before))
    finally:
        os.replace = original_replace
    assert injected and pointer.read_bytes() == ours
    return {"rival_replacement_injected_after_final_cas_check": injected,
            "function_returned_success": True, "rival_pointer_was_overwritten": True,
            "finding": "SHA_CHECK_PLUS_RENAME_IS_NOT_CAS_AGAINST_NONCOOPERATING_PUBLISHER"}


def probe_missing_pointer_recovery(root: Path):
    m = cutover()
    m.EVIDENCE_ROOT = root / "evidence"
    m.ACTIVE_API_PLIST = root / "LaunchAgents/com.lexi.v35.api-only.plist"
    m.ACTIVE_API_PLIST.parent.mkdir(parents=True)
    m.ACTIVE_SCHEDULER_PLIST = root / "scheduler.plist"
    m.STAGE_CENTER_SCHEDULER_PLIST = root / "stage.plist"
    write(m.ACTIVE_SCHEDULER_PLIST, b"synthetic scheduler\n")
    write(m.STAGE_CENTER_SCHEDULER_PLIST, b"synthetic stage\n")
    original = b"synthetic exact preimage plist\n"
    backup = root / "operation/backup.plist"
    write(backup, original)
    old_identity = {"state": "running", "V35_APP_ROOT": "/synthetic/base/app",
                    "V35_RELEASE_ID": "base", "V35_RELEASE_MANIFEST_SHA256": "0" * 64}
    plan = {"before": {"active_api_plist_sha256": sha(original), "loaded_identity": old_identity},
            "target": {"release_id": "candidate", "app_root": "/synthetic/candidate/app",
                       "release_manifest_sha256": "1" * 64}}
    observations = iter([{"state": "NOT_LOADED", "identity": None},
                         {"state": "LOADED", "identity": old_identity}])
    simulated_actions = []
    m._observe_loaded = lambda: next(observations)
    m._launchctl_action = lambda action: simulated_actions.append(action)
    m._verify_openapi = lambda **kwargs: {"fixture": "no HTTP called"}
    m._verify_historical_product_readback = lambda: {"fixture": "no HTTP called"}
    operation = m._new_operation_dir("-recovery-probe")
    result = m._restore_after_failure(plan, backup, original, "2" * 64, operation,
                                      "SYNTHETIC_FAILURE", m._file_metadata(backup))
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m.ACTIVE_API_PLIST.read_bytes() == original
    assert simulated_actions == ["bootstrap"]
    return {"status": result["status"], "missing_active_pointer_restored_exactly": True,
            "simulated_actions": simulated_actions, "real_service_calls": 0,
            "finding": "R2_AUTO_RECOVERY_ALREADY_SUPPORTS_MISSING_ACTIVE_PATH_KEEP_THIS_SEMANTIC"}


def main():
    probes = [probe_task_private_locks, probe_stale_package_preflight,
              probe_inventory_backend_reopen, probe_last_check_replace_race,
              probe_missing_pointer_recovery]
    results = {}
    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=WORK) as base:
        for probe in probes:
            root = Path(base) / probe.__name__
            root.mkdir()
            results[probe.__name__] = probe(root)
    output = {"source_path": str(SCRIPT), "source_sha256": SCRIPT_SHA,
              "scope": "OFFLINE_SYNTHETIC_SOURCE_BOUNDARY_PROBES_ONLY",
              "launchctl_called": False, "http_called": False,
              "business_data_accessed": False, "deployment_performed": False,
              "probes_passed": len(results), "results": results}
    write_json(WORK / "probe_results.json", output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
