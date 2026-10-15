"""Prepare (but never activate) the mapping700 runtime candidate from live identity.

This script copies the plist-selected API release, applies only the frozen
mapping700 source delta and required manager-selection bundle, and binds a
fresh release/config/plist receipt. It never calls launchctl or mutates the
active release, config, or plist.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import tempfile

from ops.api_release_integration import (
    _base_binding,
    _diff_proof,
    api_release_lock_path,
    build_integrated_app,
    inventory_digest,
    inventory_tree,
    read_active_release,
    sha256_bytes,
    verify_api_release_candidate,
)
from ops.prepare_api_only_cutover import rewrite_api_only_plist


ROOT = Path(__file__).resolve().parents[3]
HANDOFF = Path(__file__).resolve().parent
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
ACTIVE_CONFIG = BASE / "config/oversold-nextday-recovery-20261015-r1.json"
CANDIDATE = BASE / "releases/us-hk-mapping700-20261016-r1"
NEW_CONFIG = BASE / "config/us-hk-mapping700-20261016-r1.json"
ACTIVE_RELEASE_ID = "us-hk-mapping-finish-20261015-r2"
ACTIVE_PLIST_SHA256 = "45ec4e5fa94d3f4237983c1ccd841fc57e1cdbe6c62dbb05acb66078833dc653"
ACTIVE_MANIFEST_SHA256 = "5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684"
ACTIVE_INVENTORY_SHA256 = "56a7807a98793b837b61e2c40c7d581ba366115a6e91578869f1dfa966d02845"
ACTIVE_CONFIG_SHA256 = "f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158"
SOURCE_PATCH_SHA256 = "64f4011b2fc7f15f16646139ebf953154465f62f17f7bf54242bc3bc4d7971aa"
OVERLAY_SHA256 = "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"
CATALOG_MODULE_SHA256 = "b7ec08a65a9bb6e2ee419caf303c5ec60b809a44b7a2bef42883ea0fed4023ad"
SOURCE_PATCH = HANDOFF / "source_test_ui.patch"
OVERLAY_SOURCE = ROOT / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
WEB_NODE_MODULES = ROOT / "apps/web/node_modules"
RUNTIME_PATCH_PATHS = {
    "v4/manager_workbench/us_mapping_catalog.py",
    "apps/web/src/manager-workbench/Workbench.vue",
    "apps/web/src/manager-workbench/types.ts",
}
EXPECTED_BUILD_PATHS = {
    "manager-selection/index.html",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def patch_sections(raw: str) -> tuple[str, set[str]]:
    sections: list[tuple[str, list[str]]] = []
    path = None
    lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("--- a/"):
            if path is not None:
                sections.append((path, lines))
            path = line[len("--- a/"):].strip()
            lines = [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        sections.append((path, lines))
    selected = [(path, lines) for path, lines in sections if path in RUNTIME_PATCH_PATHS]
    paths = {path for path, _ in selected}
    if paths != RUNTIME_PATCH_PATHS:
        raise RuntimeError("RUNTIME_SOURCE_PATCH_PATHS_INVALID")
    return "".join("".join(lines) for _, lines in selected), paths


def run_build(web_root: Path, output: Path, *, typecheck: bool) -> dict[str, object]:
    modules = web_root / "node_modules"
    if modules.exists() or modules.is_symlink():
        raise RuntimeError("TEMP_NODE_MODULES_PATH_ALREADY_PRESENT")
    modules.symlink_to(WEB_NODE_MODULES, target_is_directory=True)
    commands = []
    try:
        build_cmd = [str(modules / ".bin/vite"), "build", "--outDir", str(output), "--emptyOutDir"]
        build = subprocess.run(build_cmd, cwd=web_root, capture_output=True, text=True, timeout=300)
        commands.append({"argv": ["node_modules/.bin/vite", "build", "--outDir", "<temporary>", "--emptyOutDir"],
                         "exit_code": build.returncode})
        if build.returncode:
            raise RuntimeError("VITE_BUILD_FAILED:" + build.stderr[-4000:])
        if typecheck:
            type_cmd = [str(modules / ".bin/vue-tsc"), "--noEmit", "--strict", "--skipLibCheck",
                        "--target", "ES2022", "--module", "ESNext", "--moduleResolution", "Bundler",
                        "--types", "vitest/globals", "src/manager-workbench/Workbench.vue",
                        "src/manager-workbench/useWorkbench.ts"]
            check = subprocess.run(type_cmd, cwd=web_root, capture_output=True, text=True, timeout=300)
            commands.append({"argv": ["node_modules/.bin/vue-tsc", "--noEmit", "--strict", "--skipLibCheck",
                                       "--target", "ES2022", "--module", "ESNext", "--moduleResolution",
                                       "Bundler", "--types", "vitest/globals", "src/manager-workbench/Workbench.vue",
                                       "src/manager-workbench/useWorkbench.ts"], "exit_code": check.returncode})
            if check.returncode:
                raise RuntimeError("VUE_TSC_FAILED:" + check.stdout[-4000:] + check.stderr[-4000:])
    finally:
        modules.unlink()
    return {"commands": commands, "vite_stdout_tail": build.stdout[-3000:],
            "vue_tsc_stdout_tail": check.stdout[-3000:] if typecheck else None}


def main() -> None:
    if CANDIDATE.exists() or NEW_CONFIG.exists():
        raise RuntimeError("TARGET_ALREADY_EXISTS_REFUSE_OVERWRITE")
    for artifact in (HANDOFF / "runtime-delta-receipt.json", HANDOFF / "candidate-preparation-receipt.json"):
        if artifact.exists():
            raise RuntimeError("HANDOFF_RECEIPT_ALREADY_EXISTS_REFUSE_OVERWRITE:" + artifact.name)
    if sha(SOURCE_PATCH.read_bytes()) != SOURCE_PATCH_SHA256:
        raise RuntimeError("SOURCE_PATCH_SHA_CHANGED")
    if file_sha(OVERLAY_SOURCE) != OVERLAY_SHA256:
        raise RuntimeError("OVERLAY_SHA_CHANGED")
    if file_sha(ROOT / "v4/manager_workbench/us_mapping_catalog.py") != CATALOG_MODULE_SHA256:
        raise RuntimeError("CATALOG_MODULE_SHA_CHANGED")
    if not WEB_NODE_MODULES.is_dir():
        raise RuntimeError("WORKSPACE_NODE_MODULES_UNAVAILABLE")

    original_plist_raw = PLIST.read_bytes()
    if sha(original_plist_raw) != ACTIVE_PLIST_SHA256:
        raise RuntimeError("ACTIVE_PLIST_CHANGED_REBASE_REQUIRED")
    active = read_active_release(PLIST, role="gateway")
    if (active["release_id"] != ACTIVE_RELEASE_ID
            or active["release_manifest_sha256"] != ACTIVE_MANIFEST_SHA256
            or active["application_inventory_sha256"] != ACTIVE_INVENTORY_SHA256):
        raise RuntimeError("ACTIVE_RELEASE_CHANGED_REBASE_REQUIRED")
    active_config_raw = ACTIVE_CONFIG.read_bytes()
    if sha(active_config_raw) != ACTIVE_CONFIG_SHA256:
        raise RuntimeError("ACTIVE_CONFIG_CHANGED_REBASE_REQUIRED")
    active_config = json.loads(active_config_raw)
    if active_config.get("relation_root") != str(Path(active["app_root"])):
        raise RuntimeError("ACTIVE_RELATION_ROOT_IDENTITY_MISMATCH")
    active_config_mode = stat.S_IMODE(ACTIVE_CONFIG.stat().st_mode)
    plist_mode = stat.S_IMODE(PLIST.stat().st_mode)

    active_web = Path(active["app_root"]) / "apps/web"
    for name in ("package.json", "package-lock.json", "vite.config.ts"):
        if file_sha(active_web / name) != file_sha(ROOT / "apps/web" / name):
            raise RuntimeError("WEB_BUILD_INPUT_MISMATCH:" + name)

    with tempfile.TemporaryDirectory(prefix="mapping700_runtime_candidate_", dir="/private/tmp") as temp_dir:
        temp = Path(temp_dir)
        seed_app = temp / "seed-app"
        shutil.copytree(active["app_root"], seed_app, symlinks=True)
        if inventory_tree(seed_app) != active["inventory"]:
            raise RuntimeError("ACTIVE_BASE_TEMP_COPY_DRIFT")
        active_dist = seed_app / "apps/web/dist"
        baseline_dist = temp / "baseline-dist"
        baseline_build = run_build(seed_app / "apps/web", baseline_dist, typecheck=False)
        for output in sorted(path for path in baseline_dist.rglob("*") if path.is_file()):
            rel = output.relative_to(baseline_dist).as_posix()
            active_output = active_dist / rel
            if not active_output.is_file() or file_sha(output) != file_sha(active_output):
                raise RuntimeError("ACTIVE_DIST_BASELINE_BUILD_MISMATCH:" + rel)

        patch_text, patch_paths = patch_sections(SOURCE_PATCH.read_text(encoding="utf-8"))
        patched = subprocess.run(["git", "apply", "-"],
                                 cwd=seed_app, input=patch_text, capture_output=True, text=True)
        if patched.returncode:
            raise RuntimeError("ACTIVE_SOURCE_DELTA_PATCH_FAILED:" + patched.stdout + patched.stderr)
        if file_sha(seed_app / "v4/manager_workbench/us_mapping_catalog.py") != CATALOG_MODULE_SHA256:
            raise RuntimeError("PATCHED_CATALOG_MODULE_SHA_MISMATCH")
        shutil.copy2(OVERLAY_SOURCE,
                     seed_app / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json")
        if file_sha(seed_app / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json") != OVERLAY_SHA256:
            raise RuntimeError("PATCHED_OVERLAY_SHA_MISMATCH")

        patched_dist = temp / "patched-dist"
        build_result = run_build(seed_app / "apps/web", patched_dist, typecheck=True)
        build_delta_paths = []
        for output in sorted(path for path in patched_dist.rglob("*") if path.is_file()):
            rel = output.relative_to(patched_dist).as_posix()
            if rel in EXPECTED_BUILD_PATHS or (rel.startswith("assets/managerSelection-") and rel.endswith(".js")):
                target = active_dist / rel
                if not target.is_file() or file_sha(output) != file_sha(target):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(output, target)
                    build_delta_paths.append("apps/web/dist/" + rel)
            elif (active_dist / rel).is_file() and file_sha(output) == file_sha(active_dist / rel):
                continue
            else:
                raise RuntimeError("UNEXPECTED_MANAGER_BUILD_DELTA:" + rel)
        if not build_delta_paths:
            raise RuntimeError("MANAGER_SELECTION_BUILD_DELTA_MISSING")

        candidate_inventory = inventory_tree(seed_app)
        before_by = {str(row["path"]): row for row in active["inventory"]}
        after_by = {str(row["path"]): row for row in candidate_inventory}
        removed = sorted(set(before_by) - set(after_by))
        if removed:
            raise RuntimeError("ACTIVE_ASSET_REMOVED:" + ",".join(removed[:8]))
        changed = sorted(path for path in set(before_by) | set(after_by)
                         if before_by.get(path) != after_by.get(path))
        expected = RUNTIME_PATCH_PATHS | {
            "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
        } | set(build_delta_paths)
        if set(changed) != expected:
            raise RuntimeError("RUNTIME_DELTA_SCOPE_MISMATCH:" + json.dumps(
                {"changed": changed, "expected": sorted(expected)}, ensure_ascii=False))

        entries = []
        for relative in changed:
            old_path = Path(active["app_root"]) / relative
            new_path = seed_app / relative
            old_sha = file_sha(old_path) if old_path.is_file() else None
            new_sha = file_sha(new_path)
            row = {"path": relative, "before_sha256": old_sha, "after_sha256": new_sha}
            if old_sha is not None:
                proof_sha, hunk_count = _diff_proof(old_path.read_bytes(), new_path.read_bytes())
                row.update(unified_diff_sha256=proof_sha, unified_diff_hunk_count=hunk_count)
            entries.append(row)
        delta_receipt = {"schema_version": "v4.api_release_delta_receipt.v1",
                         "base": _base_binding(active), "entries": entries}
        delta_path = HANDOFF / "runtime-delta-receipt.json"
        write_json_exclusive(delta_path, delta_receipt)
        # Verify active API identity again before building the immutable candidate.
        if sha(PLIST.read_bytes()) != ACTIVE_PLIST_SHA256 or sha(ACTIVE_CONFIG.read_bytes()) != ACTIVE_CONFIG_SHA256:
            raise RuntimeError("ACTIVE_POINTER_OR_CONFIG_CHANGED_DURING_PREPARATION")
        CANDIDATE.mkdir(mode=0o755, exist_ok=False)
        integration = build_integrated_app(active_api_plist_path=PLIST, source_root=seed_app,
            candidate_root=CANDIDATE, delta_receipt_path=delta_path,
            explicit_untracked_paths=[entry["path"] for entry in entries if entry["before_sha256"] is None],
            role="gateway", base_role="gateway")

    final_inventory = inventory_tree(CANDIDATE / "app")
    if final_inventory != candidate_inventory:
        raise RuntimeError("INTEGRATED_CANDIDATE_DIFFERS_FROM_SEALED_SEED")
    manifest = deepcopy(active["manifest"])
    manifest.update(generated_at=datetime.now(timezone.utc).isoformat(),
        candidate_status="PREPARED_NOT_ACTIVATED", activation_status="NOT_ACTIVATED",
        deployment_status="CANNOT_CONFIRM", api_integration=integration)
    manifest["candidate"].update(root=str(CANDIDATE), app_root=str(CANDIDATE / "app"),
        release_id=CANDIDATE.name, module_role="gateway", module_contract_sha256=None,
        data_copy_performed=False, runtime_venv_copied=False, ignored_runtime_data_copied=False)
    manifest["application_inventory"] = {"entry_count": len(final_inventory),
        "aggregate_sha256": inventory_digest(final_inventory), "entries": final_inventory}
    manifest["source"] = {"active_role_plist": str(PLIST), "active_release_bytes_copied": True,
        "source_workspace_full_tree_copied": False, "api_integration_delta_receipt": str(delta_path)}
    manifest["verification_gaps"] = ["Independent post-P2 candidate review pending",
        "Candidate is not activated; live API/UI and natural-slot behavior are unverified",
        "Research-only limits remain: independent facts NOT_RUN, prediction UNTESTED, historical PIT NOT_VALIDATED"]
    manifest_path = CANDIDATE / "release-manifest.json"
    write_json_exclusive(manifest_path, manifest)
    manifest_sha = file_sha(manifest_path)
    candidate_check = verify_api_release_candidate(candidate_root=CANDIDATE,
        active_api_plist_path=PLIST, expected_manifest_sha256=manifest_sha,
        active_pointer="base", role="gateway", base_role="gateway")

    new_config = deepcopy(active_config)
    new_config["relation_root"] = str(CANDIDATE / "app")
    if {key: value for key, value in new_config.items() if key != "relation_root"} != {
            key: value for key, value in active_config.items() if key != "relation_root"}:
        raise RuntimeError("CONFIG_NON_RELATION_SEMANTICS_CHANGED")
    with NEW_CONFIG.open("x", encoding="utf-8") as handle:
        json.dump(new_config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(NEW_CONFIG, active_config_mode)
    new_config_sha = file_sha(NEW_CONFIG)

    staged = rewrite_api_only_plist(plistlib.loads(original_plist_raw),
        candidate_app_root=CANDIDATE / "app", release_id=CANDIDATE.name,
        manifest_path=manifest_path, manifest_sha256=manifest_sha, candidate_manager_state_root=None)
    staged_env = staged.setdefault("EnvironmentVariables", {})
    staged_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"] = str(NEW_CONFIG)
    staged["ProgramArguments"] = [
        "V4_MANAGER_WORKBENCH_CONFIG_PATH=" + str(NEW_CONFIG)
        if isinstance(arg, str) and arg.startswith("V4_MANAGER_WORKBENCH_CONFIG_PATH=") else arg
        for arg in staged["ProgramArguments"]]
    candidate_config_dir = CANDIDATE / "config"
    candidate_config_dir.mkdir(mode=0o700)
    staged_plist = candidate_config_dir / "com.lexi.v35.api-only.plist"
    with staged_plist.open("xb") as handle:
        plistlib.dump(staged, handle, fmt=plistlib.FMT_XML, sort_keys=True)
    os.chmod(staged_plist, plist_mode)
    rollback_plist = candidate_config_dir / "active-api-plist.preimage"
    with rollback_plist.open("xb") as handle:
        handle.write(original_plist_raw)
    os.chmod(rollback_plist, 0o600)
    plan = {
        "status": "PREPARED_NOT_ACTIVATED", "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
        "active_plist_path": str(PLIST), "active_plist_sha256": ACTIVE_PLIST_SHA256,
        "active_plist_bytes": len(original_plist_raw), "active_plist_mode": oct(plist_mode),
        "active_release_id": active["release_id"], "active_release_root": active["release_root"],
        "active_manifest_sha256": active["release_manifest_sha256"],
        "active_application_inventory_sha256": active["application_inventory_sha256"],
        "active_config_path": str(ACTIVE_CONFIG), "active_config_sha256": ACTIVE_CONFIG_SHA256,
        "active_relation_root": active_config["relation_root"],
        "new_config_path": str(NEW_CONFIG), "new_config_sha256": new_config_sha,
        "new_relation_root": new_config["relation_root"], "new_config_mode": oct(active_config_mode),
        "candidate_root": str(CANDIDATE), "candidate_app_root": str(CANDIDATE / "app"),
        "candidate_release_id": CANDIDATE.name, "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": manifest_sha,
        "staged_plist_path": str(staged_plist), "staged_plist_sha256": file_sha(staged_plist),
        "rollback_plist_path": str(rollback_plist), "rollback_plist_sha256": file_sha(rollback_plist),
        "shared_release_lock_path": str(api_release_lock_path(PLIST, role="gateway")),
        "candidate_verification": candidate_check,
        "delta_paths": changed, "non_delta_entry_count": integration["non_delta_entry_count"],
        "non_delta_inventory_sha256": integration["non_delta_inventory_sha256"],
        "baseline_build": baseline_build, "candidate_build": build_result,
        "activation_gate": "Requires a separate explicit root authorization and a different-identity REVIEWED=PASS plus BEHAVIOR_VERIFIED=PASS receipt bound to this candidate manifest SHA.",
        "activation_command": "PYTHONPATH=. .venv/bin/python docs/handoffs/us_hk_700_supplement_20261016/activate_runtime_candidate.py --review-receipt <review-receipt> --activate",
        "rollback_commands": [
            "Under the shared API release lock, boot out gui/$(id -u)/com.lexi.v35.api-only.",
            "Restore active-api-plist.preimage only if its SHA256 equals rollback_plist_sha256 and active plist still matches the staged candidate identity.",
            "Bootstrap gui/$(id -u) /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist.",
            "Fresh-read the plist and verify it returns to active_plist_sha256 and active_release_id.",
        ],
    }
    write_json_exclusive(candidate_config_dir / "cutover-plan.json", plan)
    write_json_exclusive(HANDOFF / "candidate-preparation-receipt.json", plan)
    if sha(PLIST.read_bytes()) != ACTIVE_PLIST_SHA256 or sha(ACTIVE_CONFIG.read_bytes()) != ACTIVE_CONFIG_SHA256:
        raise RuntimeError("ACTIVE_POINTER_OR_CONFIG_CHANGED_AFTER_PREPARATION")
    print(json.dumps({"status": plan["status"], "candidate_root": str(CANDIDATE),
        "manifest_sha256": manifest_sha, "delta_paths": changed,
        "non_delta_entry_count": integration["non_delta_entry_count"],
        "active_plist_sha256": ACTIVE_PLIST_SHA256, "new_config_sha256": new_config_sha}, indent=2))


if __name__ == "__main__":
    main()
