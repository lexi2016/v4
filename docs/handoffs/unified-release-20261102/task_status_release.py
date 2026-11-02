"""Frozen r7 -> r8 task-status patch, API only; never call legacy release CLIs.

build copies only the verified live API app. prepare captures fresh evidence.
activate/rollback require the same preparation SHA and explicit authorization.
Main/Stage and the r7 manual-collection binding are deliberately not switched.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[3]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
from ops import activate_stage_four_repairs as fixed

BASE = fixed.LOCAL / "candidates/v4-unified-release-20261102-r7/v4-unified-release-20261102-r7-api"
CANDIDATE = fixed.LOCAL / "candidates/v4-task-status-date-20261102-r8-api"
STAGE_APP = BASE.parent / "v4-unified-release-20261102-r7-stage/app"
ARTIFACT_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/v4_unified_recovery_20261102_terra/task-status-closeout")
BASE_PLIST_SHA = "d24718c96d862beac226e937faca43bbebc019fdfe41810ae7bc2d3a015e7086"
BASE_MANIFEST_SHA = "bfa7e559a0dc52ee25671125d4ab8e66687f71b4fbf0a7885fb269f735efb073"
TASK_PREIMAGE_SHA = "60951684afadda539f34c94eb1bfa5f2d75092a22e9a5013ce89dbf658e028f0"
PATCH = ("domains/task_status.py", "tests/test_task_status_dates.py")
LABEL = "com.lexi.v4.api"
DATE = "20261102"
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
SCHEMA = "v4.task_status_api_patch.20261102.v1"


def interpreter():
    fixed.require(sys.executable == str(fixed.PYTHON) and sys.dont_write_bytecode, "PINNED_PYTHON_AND_NO_BYTECODE_REQUIRED")


def safety(value):
    fixed.require(all(value.get(k) is v for k, v in SAFETY.items()), "UNSAFE_RELEASE_OR_PLAN")


def safe_environment(env):
    fixed.require(str(env.get("RESEARCH_ONLY")).lower() in {"1", "true"}, "RESEARCH_ONLY_REQUIRED")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        fixed.require(str(env.get(key.upper())).lower() in {"0", "false"}, "UNSAFE_ENVIRONMENT")
        if key in env:
            fixed.require(str(env[key]).lower() in {"0", "false"}, "UNSAFE_ENVIRONMENT")


def artifact_path(path):
    path = Path(path).absolute()
    fixed.require(path == path.resolve() and path.is_relative_to(ARTIFACT_ROOT) and path != ARTIFACT_ROOT,
                  "EVIDENCE_OUTSIDE_BATCH_OR_ALIASED")
    return path


def pin_file(path):
    path = Path(path)
    fixed.require(path == path.resolve() and path.is_file() and not path.is_symlink(), "PIN_NOT_EXACT_FILE:" + str(path))
    return {"path": str(path), "sha256": fixed.sha(path.read_bytes()), "mode": stat.S_IMODE(path.stat().st_mode)}


def check_pin(row):
    fixed.pinned(Path(row["path"]), row["sha256"])
    fixed.require(pin_file(Path(row["path"])) == row, "PIN_MODE_OR_PATH_CHANGED:" + row["path"])


def script_pins():
    # Candidate/baseline manifests additionally pin every imported application
    # module. These are the adapter and the fixed guard's direct code dependencies.
    paths = [Path(__file__).resolve(), Path(fixed.__file__).resolve(),
             BASE / "app/ops/api_release_integration.py", BASE / "app/infrastructure/interprocess_lock.py",
             BASE / "app/infrastructure/owned_io.py", fixed.PYTHON.resolve()]
    return {str(path): pin_file(path)["sha256"] for path in paths}


def bind(plan=None):
    """Bind only API identities, never override/relax a fixed helper function."""
    fixed.BASE_API = BASE
    fixed.API = CANDIDATE
    fixed.pinned(BASE / "release-manifest.json", BASE_MANIFEST_SHA)
    manifest = json.loads((BASE / "release-manifest.json").read_bytes())
    registered = {row["path"]: row for row in manifest["application_inventory"]["entries"]}
    fixed.TOOLS_PIN = registered["ops/api_release_integration.py"]["sha256"]
    if plan:
        fixed.require(plan["script_pins"][str(BASE / "app/ops/api_release_integration.py")] == fixed.TOOLS_PIN,
                      "INVENTORY_HELPER_NOT_REGISTERED_BASELINE_BYTES")
    fixed.TARGETS = {"api": (LABEL, BASE, BASE_MANIFEST_SHA, CANDIDATE,
                             plan["candidate"]["manifest_sha256"] if plan else "NOT_BUILT")}


def frozen_patch(source, source_ref):
    fixed.require(isinstance(source_ref, str) and re.fullmatch(r"[0-9a-f]{40}", source_ref), "EXACT_FROZEN_COMMIT_REQUIRED")
    source = Path(source)
    resolved = subprocess.check_output(["git", "-C", str(source), "rev-parse", source_ref + "^{commit}"]).decode().strip()
    fixed.require(resolved == source_ref, "EXACT_FROZEN_COMMIT_REQUIRED")
    tree = subprocess.check_output(["git", "-C", str(source), "ls-tree", "-rz", source_ref, "--", *PATCH])
    modes = {}
    for entry in tree.split(b"\0"):
        if entry:
            info, relative = entry.decode().split("\t", 1)
            mode, kind, _oid = info.split()
            fixed.require(kind == "blob" and mode in {"100644", "100755"}, "FROZEN_PATCH_NOT_REGULAR")
            modes[relative] = int(mode[-3:], 8)
    fixed.require(set(modes) == set(PATCH), "FROZEN_PATCH_PATHS_MISSING")
    result = {}
    for relative in PATCH:
        path = source / relative
        raw = subprocess.check_output(["git", "-C", str(source), "show", source_ref + ":" + relative])
        fixed.require(path == path.resolve() and path.is_file() and path.read_bytes() == raw, "SOURCE_NOT_FROZEN:" + relative)
        result[relative] = {"raw": raw, "sha256": fixed.sha(raw), "mode": modes[relative]}
    return result


def inventory_record(inv, app):
    entries = inv.inventory_tree(app)
    return {"entries": entries, "entry_count": len(entries), "aggregate_sha256": inv.inventory_digest(entries)}


def check_delta(before, after, frozen):
    old = {r["path"]: r for r in before["entries"]}
    new = {r["path"]: r for r in after["entries"]}
    delta = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))
    fixed.require(set(frozen) == set(PATCH) and set(delta) == set(PATCH), "UNOWNED_OR_MISSING_PATCH_DELTA")
    fixed.require(old[PATCH[0]]["sha256"] == TASK_PREIMAGE_SHA, "R7_TASK_STATUS_PREIMAGE_CHANGED")
    rows = []
    for path in delta:
        fixed.require(new.get(path, {}).get("kind") == "file" and new[path]["sha256"] == frozen[path]["sha256"], "FROZEN_DELTA_BYTES_CHANGED")
        fixed.require(path not in old or old[path]["kind"] == "file", "PATCH_PREIMAGE_NOT_REGULAR")
        expected_mode = old[path]["mode"] if path in old else f'{frozen[path]["mode"]:04o}'
        fixed.require(new[path]["mode"] == expected_mode, "PATCH_MODE_CHANGED")
        rows.append({"path": path, "before_sha256": old.get(path, {}).get("sha256"), "after_sha256": new[path]["sha256"],
                     "before": old.get(path), "after": new[path]})
    return rows


def proposed_plist(original, candidate, digest):
    payload = copy.deepcopy(plistlib.loads(original))
    old_app, new_app = str(BASE / "app"), str(candidate / "app")
    payload["WorkingDirectory"] = new_app
    payload["ProgramArguments"] = [re.sub(re.escape(old_app) + r"(?=$|/|:)", lambda _: new_app, arg)
                                   for arg in payload["ProgramArguments"]]
    env = payload["EnvironmentVariables"]
    env.update(dict(zip(fixed.IDENTITY, (new_app, candidate.name, str(candidate / "release-manifest.json"), digest))))
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = ":".join(new_app + p[len(old_app):] if p == old_app or p.startswith(old_app + "/") else p
                                    for p in env["PYTHONPATH"].split(":"))
    # In particular, never re-point V4_MANUAL_COLLECTION_STAGE_CONFIG into r8.
    return plistlib.dumps(payload, sort_keys=True)


def validate_proposal(original, proposed, candidate, digest):
    before, after = plistlib.loads(original), plistlib.loads(proposed)
    fixed.require(before["Label"] == after["Label"] == LABEL, "API_LABEL_CHANGED")
    fixed.require(after == plistlib.loads(proposed_plist(original, candidate, digest)), "UNOWNED_PLIST_DELTA")
    fixed.require(before["ProgramArguments"][0] == after["ProgramArguments"][0] == str(fixed.PYTHON), "API_INTERPRETER_CHANGED")
    safe_environment(before["EnvironmentVariables"])
    safe_environment(after["EnvironmentVariables"])


def baseline():
    path = fixed.LA / (LABEL + ".plist")
    fixed.pinned(path, BASE_PLIST_SHA)
    raw = path.read_bytes()
    payload = plistlib.loads(raw)
    env = payload["EnvironmentVariables"]
    fixed.require(payload["Label"] == LABEL and payload["WorkingDirectory"] == str(BASE / "app"), "WRONG_LIVE_API_BASELINE")
    fixed.require(tuple(env[k] for k in fixed.IDENTITY) == (str(BASE / "app"), BASE.name, str(BASE / "release-manifest.json"), BASE_MANIFEST_SHA), "WRONG_LIVE_R7_IDENTITY")
    fixed.require(payload["ProgramArguments"][0] == str(fixed.PYTHON), "API_INTERPRETER_CHANGED")
    safe_environment(env)
    health = fixed.live_api(raw)
    record = {"label": LABEL, "path": str(path), "mode": pin_file(path)["mode"],
              "original_sha256": fixed.sha(raw), "loaded": health["job"]}
    fixed.require(type(record["loaded"]["pid"]) is int and record["loaded"]["pid"] > 0, "LIVE_API_PID_REQUIRED")
    return raw, record, health


def new_manifest(before, candidate, source, source_ref, delta):
    result = copy.deepcopy(before)
    result.update(app_root=str(candidate / "app"), release_id=candidate.name,
                  activation_status="PREPARED_NOT_ACTIVATED", deployment_status="NOT_DEPLOYED",
                  source_root=str(source), source_commit=source_ref)
    result["candidate"].update(root=str(candidate), app_root=str(candidate / "app"), release_id=candidate.name)
    result["task_status_date_patch"] = {"source_ref": source_ref, "baseline_release_id": BASE.name,
        "baseline_manifest_sha256": BASE_MANIFEST_SHA, "delta": delta,
        "manual_stage_binding": "PRESERVED_R7", "Main_Stage_switched": False}
    return result


def build(*, source, source_ref, evidence):
    interpreter()
    source = Path(source).resolve()
    evidence = artifact_path(evidence)
    fixed.require(not evidence.exists(), "BUILD_EVIDENCE_MUST_BE_NEW")
    fixed.require(not CANDIDATE.exists() and not CANDIDATE.is_symlink(), "CANDIDATE_MUST_BE_NEW")
    fixed.require(CANDIDATE == CANDIDATE.resolve() and CANDIDATE.is_relative_to(fixed.LOCAL / "candidates") and CANDIDATE != BASE, "WRONG_CANDIDATE_PATH")
    patch = frozen_patch(source, source_ref)
    frozen = {p: {k: v for k, v in row.items() if k != "raw"} for p, row in patch.items()}
    bind()
    inv = fixed.tools()
    with fixed.guards():
        raw, record, health = baseline()
        fixed.verify_release(BASE, BASE_MANIFEST_SHA, inv)
        before = json.loads((BASE / "release-manifest.json").read_bytes())
        safety(before)
        entries = before["application_inventory"]
        fixed.require(next(r for r in entries["entries"] if r["path"] == PATCH[0])["sha256"] == TASK_PREIMAGE_SHA, "R7_TASK_STATUS_PREIMAGE_CHANGED")
        _, caches = inv._inventory_tree_with_generated_cache(BASE / "app")
        registered = {r["path"] for r in entries["entries"]}
        excluded = {r["path"] for r in caches} - registered
        # Check space before the sole app copy; no raw data or external UI copy.
        needed = sum(r.get("size", 0) for r in entries["entries"])
        fixed.require(shutil.disk_usage(CANDIDATE.parent).free > needed * 2 + 64 * 1024 * 1024, "INSUFFICIENT_CANDIDATE_SPACE")
        evidence.mkdir(parents=True, mode=0o700)
        def ignore(directory, names):
            return [n for n in names if (Path(directory) / n).relative_to(BASE / "app").as_posix() in excluded]
        shutil.copytree(BASE / "app", CANDIDATE / "app", symlinks=True, ignore=ignore)
        fixed.require(inventory_record(inv, CANDIDATE / "app") == entries, "BASE_COPY_DRIFT")
        fixed.require(not inv._inventory_tree_with_generated_cache(CANDIDATE / "app")[1], "UNREGISTERED_CANDIDATE_CACHE")
        for relative, row in patch.items():
            with inv._candidate_parent_writable(CANDIDATE / "app", relative) as target:
                mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else row["mode"]
                if target.exists(): target.chmod(mode | stat.S_IWUSR)
                target.write_bytes(row["raw"])
                target.chmod(mode)
        after = inventory_record(inv, CANDIDATE / "app")
        delta = check_delta(entries, after, frozen)
        manifest = new_manifest(before, CANDIDATE, source, source_ref, delta)
        manifest.update(application_inventory=after, app_files=after["entries"])
        fixed.write_json(CANDIDATE / "release-manifest.json", manifest)
        digest = fixed.sha((CANDIDATE / "release-manifest.json").read_bytes())
        fixed.verify_release(CANDIDATE, digest, inv)
        proposed = proposed_plist(raw, CANDIDATE, digest)
        validate_proposal(raw, proposed, CANDIDATE, digest)
        record["staged_sha256"] = fixed.sha(proposed)
        backups = {}
        for suffix, content in (("original", raw), ("staged", proposed)):
            path = evidence / ("api." + suffix + ".plist")
            path.write_bytes(content); path.chmod(record["mode"])
            backups[suffix] = pin_file(path)
        plan = {"schema_version": SCHEMA, "roles": ["api"], "status": "BUILT_NOT_ACTIVATED", **SAFETY,
            "source": str(source), "source_ref": source_ref, "frozen": frozen, "delta": delta,
            "baseline": {"root": str(BASE), "manifest_sha256": BASE_MANIFEST_SHA, "environment": plistlib.loads(raw)["EnvironmentVariables"], "record": record, "health": health},
            "candidate": {"root": str(CANDIDATE), "app_root": str(CANDIDATE / "app"), "release_id": CANDIDATE.name, "manifest_sha256": digest},
            "inventories": {"before": entries, "after": after}, "ignored_unregistered_caches": caches,
            "backups": backups, "script_pins": script_pins(), "NATURAL_VERIFIED": "NOT_RUN"}
        fixed.cas(record, raw)
        fixed.require(fixed.loaded(LABEL, raw) == record["loaded"], "LIVE_API_CHANGED_DURING_BUILD")
        fixed.verify_release(BASE, BASE_MANIFEST_SHA, inv)
        fixed.write_json(evidence / "plan.json", plan)
    bind(plan)
    return {"status": plan["status"], "plan": str(evidence / "plan.json"), "plan_sha256": fixed.sha((evidence / "plan.json").read_bytes()), "candidate": plan["candidate"]}


def read_plan(path, digest):
    path = artifact_path(path)
    fixed.pinned(path, digest)
    plan = json.loads(path.read_bytes())
    safety(plan)
    fixed.require(plan["schema_version"] == SCHEMA and plan["roles"] == ["api"], "EXACT_API_ONLY_PLAN_REQUIRED")
    fixed.require(plan["baseline"]["root"] == str(BASE) and plan["baseline"]["manifest_sha256"] == BASE_MANIFEST_SHA,
                  "WRONG_PLAN_BASELINE")
    fixed.require(plan["candidate"]["root"] == str(CANDIDATE) and plan["candidate"]["app_root"] == str(CANDIDATE / "app") and plan["candidate"]["release_id"] == CANDIDATE.name, "WRONG_PLAN_CANDIDATE")
    fixed.require(plan["baseline"]["record"]["path"] == str(fixed.LA / (LABEL + ".plist")) and plan["baseline"]["record"]["original_sha256"] == BASE_PLIST_SHA, "WRONG_PLAN_API_PREIMAGE")
    fixed.require(plan["script_pins"] == script_pins(), "SCRIPT_DEPENDENCIES_CHANGED")
    for filename, sha in plan["script_pins"].items(): fixed.pinned(Path(filename), sha)
    for row in plan["backups"].values():
        artifact_path(row["path"]); check_pin(row)
    patch = frozen_patch(Path(plan["source"]), plan["source_ref"])
    fixed.require({p: {k: v for k, v in r.items() if k != "raw"} for p, r in patch.items()} == plan["frozen"], "FROZEN_SOURCE_CHANGED")
    original = Path(plan["backups"]["original"]["path"]).read_bytes()
    proposed = Path(plan["backups"]["staged"]["path"]).read_bytes()
    fixed.require(fixed.sha(original) == BASE_PLIST_SHA and fixed.sha(proposed) == plan["baseline"]["record"]["staged_sha256"], "PLAN_BACKUP_DRIFT")
    fixed.require(plistlib.loads(original)["EnvironmentVariables"] == plan["baseline"]["environment"], "PLAN_BASELINE_ENVIRONMENT_CHANGED")
    validate_proposal(original, proposed, CANDIDATE, plan["candidate"]["manifest_sha256"])
    bind(plan)
    inv = fixed.tools()
    for key, root, sha in (("before", BASE, BASE_MANIFEST_SHA), ("after", CANDIDATE, plan["candidate"]["manifest_sha256"])):
        fixed.verify_release(root, sha, inv)
        fixed.require(json.loads((root / "release-manifest.json").read_bytes())["application_inventory"] == plan["inventories"][key], "PLAN_INVENTORY_CHANGED")
    fixed.require(check_delta(plan["inventories"]["before"], plan["inventories"]["after"], plan["frozen"]) == plan["delta"], "PLAN_DELTA_CHANGED")
    before = json.loads((BASE / "release-manifest.json").read_bytes())
    expected = new_manifest(before, CANDIDATE, Path(plan["source"]), plan["source_ref"], plan["delta"])
    expected.update(application_inventory=plan["inventories"]["after"], app_files=plan["inventories"]["after"]["entries"])
    fixed.require(json.loads((CANDIDATE / "release-manifest.json").read_bytes()) == expected, "UNOWNED_MANIFEST_DELTA")
    return plan, original, proposed


def protected_plist(path):
    """Read-only pin of an existing legacy link AND its resolved definition.

    The owned API plist still goes through pin_file/fixed.cas, which reject
    symlinks. Only protected, never-mutated non-API definitions use this lens.
    """
    path = Path(path)
    if not path.is_symlink():
        return pin_file(path)
    def identity(info):
        return {"kind": "symlink" if stat.S_ISLNK(info.st_mode) else "file",
                "mode": stat.S_IMODE(info.st_mode), "device": info.st_dev,
                "inode": info.st_ino, "size": info.st_size,
                "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    before = identity(path.lstat())
    text = os.readlink(path)
    try:
        target = path.resolve(strict=True)
        target_before = identity(target.lstat())
        fixed.require(target_before["kind"] == "file" and target.is_file(), "PROTECTED_LINK_TARGET_NOT_FILE")
        target_pin = pin_file(target)
        fixed.require(identity(target.lstat()) == target_before, "PROTECTED_LINK_TARGET_CHANGED_DURING_READ")
        fixed.require(identity(path.lstat()) == before and os.readlink(path) == text and path.resolve(strict=True) == target,
                      "PROTECTED_LINK_CHANGED_DURING_READ")
    except OSError as error:
        raise ValueError("PROTECTED_LINK_BROKEN_OR_CHANGED:" + str(path)) from error
    return {"path": str(path), "kind": "symlink", "lstat": before, "target": text,
            "resolved_target": str(target), "target_identity": target_before,
            "sha256": target_pin["sha256"], "target_mode": target_pin["mode"]}


def protection(original, inv):
    env = plistlib.loads(original)["EnvironmentVariables"]
    files = []
    for key in ("V4_RESEARCH_PANEL_ASSET_MANIFEST", "V4_WORKBENCH_HOST_BINDING", "V4_MANAGER_WORKBENCH_CONFIG_PATH", "V4_MANUAL_COLLECTION_STAGE_CONFIG"):
        files.append(pin_file(Path(env[key])))
    fixed.require(files[1]["sha256"] == env["V4_WORKBENCH_HOST_BINDING_SHA256"], "WORKBENCH_BINDING_PIN_CHANGED")
    manual = json.loads(Path(env["V4_MANUAL_COLLECTION_STAGE_CONFIG"]).read_bytes())
    fixed.require(manual["stage_owner_root"] == str(STAGE_APP), "MANUAL_R7_STAGE_BINDING_CHANGED")
    files.extend(pin_file(path) for path in (STAGE_APP / "stage_center_tick_config.json", STAGE_APP.parent / "release-manifest.json"))
    stage_bindings = json.loads((STAGE_APP / "stage_center_tick_config.json").read_bytes())
    panel = Path(env["V4_RESEARCH_PANEL_ROOT"])
    assets = json.loads(Path(env["V4_RESEARCH_PANEL_ASSET_MANIFEST"]).read_bytes())["files"]
    for row in assets:
        path = inv._safe_child(panel, row["path"], allow_missing=False)
        fixed.pinned(path, row["sha256"])
    entries = inv.inventory_tree(panel)
    return {"external_files": files, "panel_root": str(panel), "panel_inventory": {"entry_count": len(entries), "aggregate_sha256": inv.inventory_digest(entries)},
        "asset_count": len(assets), "manual_stage_bindings": manual, "stage_bindings": stage_bindings,
        "non_api_plists": [protected_plist(path) for path in sorted(fixed.LA.glob("*.plist")) if path.name != LABEL + ".plist"]}


# Separate fresh interpreter avoids import-cache mixing between r7, r8 and the
# source checkout. Only existing ledger read APIs and the actual matcher run.
PROBE_CODE = r'''
import hashlib, json, pathlib, sys
app, env, date = pathlib.Path(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]
sys.path[:0] = [str(app)] + [p for p in env.get("PYTHONPATH", "").split(":") if p]
from domains.task_status import _receipt_matches_business_date
from infrastructure.scheduling.execution_ledger import ExecutionLedger
ledger = ExecutionLedger(pathlib.Path(env["V4_TASK_STATUS_LEDGER_ROOT"]))
root = ledger.root / "receipts/live" / date
rows = []
for path in sorted(root.glob("*/*.dispatch-receipt.json")):
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("RECEIPT_PATH_ALIASED")
    raw = path.read_bytes()
    r = json.loads(raw)
    workload = "hourly_research" if "hourly_research" in (r.get("selected_workload_ids") or []) else None
    valid = str(r.get("mode", "")).upper() == "LIVE" and _receipt_matches_business_date(r, date, workload)
    rows.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "date_valid": valid,
        **{k: r.get(k) for k in ("run_id", "business_date", "scheduled_date", "target_date", "slot", "status")},
        "workload_statuses": [{"workload_id": w.get("workload_id"), "status": w.get("status")} for w in (r.get("workload_results") or [])]})
chain, errors = ledger.verify_receipt_chain(date, mode="LIVE")
listed = ledger.list_receipts(date, mode="LIVE")
print(json.dumps({"namespace": str(root), "receipt_count": len(rows), "date_valid_count": sum(r["date_valid"] for r in rows),
    "chain_valid": chain and len(listed) == len(rows), "chain_errors": errors, "rows": rows}, ensure_ascii=False))
'''


def probe_receipts(app, env, date):
    raw = subprocess.check_output([str(fixed.PYTHON), "-I", "-B", "-c", PROBE_CODE, str(app), json.dumps(env), date],
                                  cwd="/", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
    return json.loads(raw)


def verify_result(raw, candidate, *, rollback):
    health = fixed.live_api(raw)
    env = plistlib.loads(raw)["EnvironmentVariables"]
    proof = probe_receipts(candidate / "app", env, DATE)
    fixed.require(proof["receipt_count"] > 0 and proof["date_valid_count"] == proof["receipt_count"] and proof["chain_valid"] is True,
                  "ACTUAL_RECEIPT_DATE_OR_CHAIN_INVALID")
    status = fixed.api_get("/api/v4/tasks/status?date=" + DATE)
    fixed.require(status["business_date"] == DATE and all(status.get(k) is False for k in SAFETY if k != "RESEARCH_ONLY"), "TASK_STATUS_IDENTITY_OR_SAFETY")
    observation = status["scheduler_observation"]
    fixed.require(observation["receipt_count"] == proof["receipt_count"], "TASK_STATUS_RECEIPT_SET_CHANGED")
    if not rollback:
        fixed.require(observation["status"] == "RECEIPT_CHAIN_VERIFIED" and "RECEIPT_DATE_MISMATCH" not in json.dumps(status), "TASK_STATUS_DATE_CONTRACT")
    # Restoring r7 intentionally restores its known projection bug. Preserve the
    # raw response, never relabel it as a successful repaired date projection.
    return {"API": health, "task_status": status, "actual_receipts": proof,
            "restored_r7_projection_defect": rollback and observation["status"] == "RECEIPT_DATE_MISMATCH",
            "UI_VERIFIED": "NOT_RUN", "NATURAL_VERIFIED": "NOT_RUN"}


def prepare(*, plan_path, plan_sha, evidence):
    interpreter()
    evidence = artifact_path(evidence)
    fixed.require(not evidence.exists(), "PREPARATION_MUST_BE_NEW")
    plan, original, proposed = read_plan(plan_path, plan_sha)
    with fixed.guards():
        plan, original, proposed = read_plan(plan_path, plan_sha)
        record = plan["baseline"]["record"]
        fixed.cas(record, original)
        job = fixed.loaded(LABEL, original)
        fixed.require(job == record["loaded"], "LOADED_API_CHANGED_REBUILD_REQUIRED")
        idle = fixed.assert_idle(job["pid"])
        health = fixed.live_api(original)
        protected = protection(original, fixed.tools())
        status = fixed.api_get("/api/v4/tasks/status?date=" + DATE)
        proof = probe_receipts(CANDIDATE / "app", plan["baseline"]["environment"], DATE)
        fixed.require(proof["receipt_count"] > 0 and proof["date_valid_count"] == proof["receipt_count"] and proof["chain_valid"] is True, "ACTUAL_RECEIPT_DATE_OR_CHAIN_INVALID")
        fixed.cas(record, original)
        fixed.require(fixed.loaded(LABEL, original) == job, "LOADED_API_CHANGED_DURING_PREPARE")
        evidence.mkdir(parents=True, mode=0o700)
        backups = {}
        for suffix, content in (("original", original), ("staged", proposed)):
            path = evidence / ("api." + suffix + ".plist")
            path.write_bytes(content); path.chmod(record["mode"])
            backups[suffix] = pin_file(path)
        receipt = {"status": "PREPARED_NOT_ACTIVATED", "schema_version": SCHEMA, **SAFETY,
            "plan_path": str(Path(plan_path).resolve()), "plan_sha256": plan_sha, "script_pins": plan["script_pins"],
            "records": {"api": record}, "backups": backups, "idle": idle, "health": health,
            "protection": protected, "task_status_before": status, "actual_receipts": proof,
            "release_manifests": [pin_file(root / "release-manifest.json") for root in (BASE, CANDIDATE)],
            "inventories": {k: {field: v[field] for field in ("entry_count", "aggregate_sha256")} for k, v in plan["inventories"].items()},
            "guards": "fixed.guards: API release + manual claim/execution + announcement submit/activity; held through admission",
            "NATURAL_VERIFIED": "NOT_RUN"}
        fixed.write_json(evidence / "preparation.json", receipt)
    return {"status": receipt["status"], "preparation": str(evidence / "preparation.json"), "preparation_sha256": fixed.sha((evidence / "preparation.json").read_bytes())}


def read_prepared(plan_path, evidence, preparation_sha):
    evidence = artifact_path(evidence)
    fixed.pinned(evidence / "preparation.json", preparation_sha)
    prepared = json.loads((evidence / "preparation.json").read_bytes())
    safety(prepared)
    fixed.require(Path(plan_path).absolute() == Path(prepared["plan_path"]) and Path(plan_path).resolve() == Path(prepared["plan_path"]), "ACTIVATION_PLAN_NOT_THE_PREPARED_PLAN")
    plan, original, proposed = read_plan(plan_path, prepared["plan_sha256"])
    fixed.require(prepared["schema_version"] == SCHEMA and prepared["records"] == {"api": plan["baseline"]["record"]}
                  and prepared["script_pins"] == plan["script_pins"], "PREPARATION_BINDING_CHANGED")
    for row in prepared["release_manifests"]: check_pin(row)
    for suffix, content in (("original", original), ("staged", proposed)):
        row = prepared["backups"][suffix]
        fixed.require(Path(row["path"]) == evidence / ("api." + suffix + ".plist"), "PREPARED_BACKUP_PATH_CHANGED")
        check_pin(row)
        fixed.require(Path(row["path"]).read_bytes() == content, "PREPARED_BACKUP_BYTES_CHANGED")
    return prepared, plan, original, proposed


def switch(*, plan_path, evidence, preparation_sha, authorized, rollback=False):
    interpreter()
    fixed.require(authorized and bool(preparation_sha), "EXPLICIT_AUTHORIZATION_AND_PREPARATION_SHA_REQUIRED")
    prepared, plan, old, new = read_prepared(plan_path, evidence, preparation_sha)
    evidence = artifact_path(evidence)
    def event(name, **fields):
        fixed.write_json(evidence / ("event-" + str(time.time_ns()) + ".json"), {"event": name, **fields})
    with fixed.guards():
        prepared, plan, old, new = read_prepared(plan_path, evidence, preparation_sha)
        record = prepared["records"]["api"]
        previous, desired = (new, old) if rollback else (old, new)
        fixed.cas(record, previous)
        job = fixed.loaded(LABEL, previous)
        if not rollback:
            fixed.require(job == record["loaded"], "LOADED_API_CHANGED_SINCE_PREPARATION")
        fixed.assert_idle(job["pid"])
        fixed.live_api(previous)
        protected = protection(old, fixed.tools())
        fixed.require(protected == prepared["protection"], "PROTECTED_BASELINE_CHANGED")
        ownership = {"api": job}
        event("ADMISSION_PASS", rollback=rollback)
        touched = []
        try:
            # Track before bootout, including a bootout that succeeds but times
            # out waiting for the old process/socket. No other role is owned.
            fixed.cas(record, previous)
            fixed.assert_idle(ownership["api"]["pid"])
            touched.append("api")
            fixed.unload("api", previous, ownership["api"])
            fixed.replace(record, previous, desired)
            result = fixed.start("api", desired, ownership)
            event("API_STARTED", rollback=rollback, result=result)
            verified = verify_result(desired, CANDIDATE, rollback=rollback)
            fixed.cas(record, desired)
            fixed.require(protection(old, fixed.tools()) == protected, "PROTECTED_POSTCHECK_CHANGED")
            # Never mutate old or new release manifests with activation status.
            read_prepared(plan_path, evidence, preparation_sha)
            event("ROLLBACK_VERIFIED" if rollback else "ACTIVATED_API_VERIFIED", verification=verified)
            return verified
        except BaseException as primary:
            event("CUTOVER_FAILED", error=repr(primary), touched=touched)
            try:
                current = Path(record["path"]).read_bytes()
                fixed.require(current in (previous, desired), "ROLLBACK_EXTERNAL_CAS_CONFLICT")
                fixed.cas(record, current)
                running = fixed.loaded(LABEL, current, missing=True)
                if running is not None:
                    owned = ownership.get("api", {})
                    fixed.require(type(owned.get("pid")) is int and running["pid"] == owned["pid"], "ROLLBACK_EXTERNAL_PID_CONFLICT")
                # No successful bootout/replacement: do not restart a pristine API.
                if current == previous and running == job:
                    event("NO_LIVE_CHANGE_TO_RESTORE")
                else:
                    restored, failures = fixed.restore_touched(touched, {"api": record}, {"api": (old, new)}, ownership, event, rollback=rollback)
                    fixed.require(not failures, "RECOVERY_FAILURES:" + json.dumps(failures))
                    verification = verify_result(previous, CANDIDATE, rollback=not rollback)
                    fixed.require(protection(old, fixed.tools()) == protected, "RECOVERY_PROTECTION_CHANGED")
                    event("AUTOMATIC_ROLLBACK_VERIFIED", restored=restored, verification=verification)
            except BaseException as recovery:
                event("AUTOMATIC_ROLLBACK_FAILED", primary_error=repr(primary), recovery_error=repr(recovery))
                raise RuntimeError("CUTOVER_FAILED:" + repr(primary) + "; RECOVERY_FAILED:" + repr(recovery)) from primary
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "prepare", "activate", "rollback"))
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--source-ref")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha")
    parser.add_argument("--preparation-sha")
    parser.add_argument("--authorize-live-role-switch", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "build":
        result = build(source=SOURCE, source_ref=args.source_ref, evidence=args.evidence)
    else:
        fixed.require(args.plan is not None, "PLAN_PATH_REQUIRED")
        if args.action == "prepare":
            fixed.require(bool(args.plan_sha), "BUILD_PLAN_SHA_REQUIRED")
            result = prepare(plan_path=args.plan, plan_sha=args.plan_sha, evidence=args.evidence)
        else:
            result = switch(plan_path=args.plan, evidence=args.evidence, preparation_sha=args.preparation_sha,
                            authorized=args.authorize_live_role_switch, rollback=args.action == "rollback")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
