"""Prepare a source-bound US-HK v2r1 runtime candidate without activating it."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile

from ops.api_release_integration import (
    DELTA_RECEIPT_NAME,
    _base_binding,
    _diff_proof,
    api_release_lock_path,
    build_integrated_app,
    inventory_digest,
    inventory_tree,
    read_active_release,
    verify_api_release_candidate,
)
from ops.prepare_api_only_cutover import rewrite_api_only_plist


ROOT = Path(__file__).resolve().parents[4]
HANDOFF = Path(__file__).resolve().parents[1]
RUNTIME = HANDOFF / "runtime"
RECEIPTS = RUNTIME / "receipts"
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
ACTIVE_CONFIG_EXPECTED = BASE / "config/us-hk-mapping700-20261016-r2.json"
CANDIDATE = BASE / "releases/us-hk-recovery-v2r1-20261016-r1"
NEW_CONFIG = BASE / "config/us-hk-recovery-v2r1-20261016-r1.json"
DELTA_PATH = RECEIPTS / "RUNTIME_DELTA_RECEIPT.json"
PREP_PATH = RECEIPTS / "RUNTIME_PREPARATION_RECEIPT.json"
REPORT_PATH = RECEIPTS / "RUNTIME_PREPARED.md"
API_CHECKER = RUNTIME / "check_candidate_api.py"
SOURCE_PATCH_PATH = HANDOFF / "diff/SOURCE_DIFF.patch"
SOURCE_REVIEW_PATH = HANDOFF / "receipts/INDEPENDENT_SOURCE_REVIEW_20261016.md"
OVERLAY_SOURCE = ROOT / "v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json"
WEB_NODE_MODULES = ROOT / "apps/web/node_modules"

EXPECTED_ACTIVE_PLIST_SHA256 = "d601d017cbf1f893949c44a5e321458c7e5a3c81216601cfb4133c4781f44e1a"
EXPECTED_ACTIVE_RELEASE_ID = "futu-industry-api-20261016-r1"
EXPECTED_ACTIVE_MANIFEST_SHA256 = "052fa77f4afd8e9abf36bf6c74f02e90a1dbccf0c033d5a585a8ac998ab1ecc3"
EXPECTED_ACTIVE_INVENTORY_SHA256 = "e7c6a91b79be0414918688cbdf1df5c3090595292f58d9eeca9f099e63f89d04"
EXPECTED_ACTIVE_CONFIG_SHA256 = "7a6d9689df73f832e15efd53923ab69d03ebc4f0357635bb8d9e67d6342e35b5"
EXPECTED_ACTIVE_RELATION_ROOT = str(BASE / "releases/us-hk-mapping700-20261016-r2/app")
EXPECTED_SOURCE_PATCH_SHA256 = "31700c81e81e92b0e53d263a20ce6c65691de2ec29979710ee5d4ea6cbff15d5"
EXPECTED_MAPPING_PATCH_SHA256 = "38a6552b49bdfbdff291492b3df3750322a5fbb5b5671e62d6ced2eb838618ff"
EXPECTED_CATALOG_MODULE_SHA256 = "ec327cb99e72b9dd982f1238e459b79b657697501f02ac66a598752a94245031"
EXPECTED_WORKBENCH_SHA256 = "7e77b6602400ecec58865dfc19b7a7bc7ae3c234c65bf28f93ec3a258ab96478"
EXPECTED_TYPES_SHA256 = "93d29e1dde2686f85f4f17159e5edc023cf6d59a5d9bf8473eab45f5f4626939"
EXPECTED_OVERLAY_SHA256 = "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c"
EXPECTED_SOURCE_REVIEW_SHA256 = "cf796bb7da55547c84cea24c9ab63096398fd56f01c39b5e8f3690988f31ce7a"
BASE_CATALOG_RELATIVE = "v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json"
LEGACY_OVERLAY_RELATIVE = "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
NEW_OVERLAY_RELATIVE = "v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json"
SOURCE_PATCH_PATHS = {
    "v4/manager_workbench/us_mapping_catalog.py",
    "apps/web/src/manager-workbench/Workbench.vue",
    "apps/web/src/manager-workbench/types.ts",
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


def mapping_patch() -> tuple[str, set[str]]:
    raw = SOURCE_PATCH_PATH.read_text(encoding="utf-8")
    if sha(raw.encode("utf-8")) != EXPECTED_SOURCE_PATCH_SHA256:
        raise RuntimeError("FROZEN_SOURCE_DIFF_SHA_CHANGED")
    sections: list[tuple[str, list[str]]] = []
    path: str | None = None
    lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.startswith("--- a/") or line.startswith("--- /dev/null"):
            if path is not None:
                sections.append((path, lines))
            path = line[len("--- a/"):].strip() if line.startswith("--- a/") else None
            lines = [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        sections.append((path, lines))
    selected = [(path, body) for path, body in sections if path in SOURCE_PATCH_PATHS]
    paths = {path for path, _body in selected}
    patch = "".join("".join(body) for _path, body in selected)
    if paths != SOURCE_PATCH_PATHS or sha(patch.encode("utf-8")) != EXPECTED_MAPPING_PATCH_SHA256:
        raise RuntimeError("FROZEN_MAPPING_PATCH_INVALID")
    return patch, paths


def launch_agent_snapshot() -> dict[str, object]:
    uid = str(os.getuid())
    label = "com.lexi.v35.api-only"
    result = subprocess.run(["/bin/launchctl", "print", f"gui/{uid}/{label}"],
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError("API_ONLY_LAUNCH_AGENT_NOT_READABLE")
    lines = result.stdout.splitlines()
    state = next((line.strip().split("=", 1)[1].strip() for line in lines
                  if line.strip().startswith("state =")), None)
    pid_raw = next((line.strip().split("=", 1)[1].strip() for line in lines
                    if line.strip().startswith("pid =")), None)
    selectors = {}
    for key in ("V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256", "V35_API_PORT",
                "V4_MANAGER_WORKBENCH_CONFIG_PATH"):
        prefix = f"{key} =>"
        selectors[key] = next((line.split("=>", 1)[1].strip() for line in lines
                               if line.strip().startswith(prefix)), None)
    if state != "running" or pid_raw is None or not pid_raw.isdecimal():
        raise RuntimeError("API_ONLY_LAUNCH_AGENT_NOT_RUNNING")
    if (selectors["V35_RELEASE_ID"] != EXPECTED_ACTIVE_RELEASE_ID
            or selectors["V35_RELEASE_MANIFEST_SHA256"] != EXPECTED_ACTIVE_MANIFEST_SHA256
            or selectors["V35_API_PORT"] != "8873"):
        raise RuntimeError("LAUNCH_AGENT_RELEASE_BINDING_CHANGED")
    return {"read_only_command": ["launchctl", "print", f"gui/{uid}/{label}"],
            "state": state, "pid": int(pid_raw), "observed_selectors": selectors}


def ensure_active_identity() -> tuple[dict[str, object], bytes, Path, bytes, dict[str, object], dict[str, object]]:
    plist_raw = PLIST.read_bytes()
    if sha(plist_raw) != EXPECTED_ACTIVE_PLIST_SHA256:
        raise RuntimeError("ACTIVE_PLIST_CHANGED_REBASE_REQUIRED")
    plist = plistlib.loads(plist_raw)
    env = plist.get("EnvironmentVariables", {})
    config_path = Path(env.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", ""))
    if config_path != ACTIVE_CONFIG_EXPECTED:
        raise RuntimeError("ACTIVE_CONFIG_PATH_CHANGED_REBASE_REQUIRED")
    config_raw = config_path.read_bytes()
    if sha(config_raw) != EXPECTED_ACTIVE_CONFIG_SHA256:
        raise RuntimeError("ACTIVE_CONFIG_CHANGED_REBASE_REQUIRED")
    config = json.loads(config_raw)
    if config.get("relation_root") != EXPECTED_ACTIVE_RELATION_ROOT:
        raise RuntimeError("ACTIVE_RELATION_ROOT_CHANGED_REBASE_REQUIRED")
    active = read_active_release(PLIST, role="gateway")
    if (active["release_id"] != EXPECTED_ACTIVE_RELEASE_ID
            or active["release_manifest_sha256"] != EXPECTED_ACTIVE_MANIFEST_SHA256
            or active["application_inventory_sha256"] != EXPECTED_ACTIVE_INVENTORY_SHA256):
        raise RuntimeError("ACTIVE_RELEASE_CHANGED_REBASE_REQUIRED")
    selectors = {key: env.get(key) for key in (
        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
        "V35_RELEASE_MANIFEST_SHA256", "V35_API_PORT", "V4_MANAGER_WORKBENCH_CONFIG_PATH",
    )}
    if (selectors["V35_APP_ROOT"] != active["app_root"]
            or selectors["V35_RELEASE_MANIFEST_PATH"] != active["release_manifest_path"]
            or selectors["V35_RELEASE_MANIFEST_SHA256"] != EXPECTED_ACTIVE_MANIFEST_SHA256
            or selectors["V35_API_PORT"] != "8873"):
        raise RuntimeError("ACTIVE_PLIST_SELECTOR_BINDING_CHANGED")
    return active, plist_raw, config_path, config_raw, config, launch_agent_snapshot()


def validate_staged_plist(original: dict[str, object], staged: dict[str, object], *,
                          app_root: Path, manifest_path: Path, manifest_sha: str,
                          config_path: Path) -> dict[str, object]:
    allowed_selectors = {"V35_APP_ROOT", "V35_RELEASE_ID", "PYTHONPATH",
                         "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256",
                         "V4_MANAGER_WORKBENCH_CONFIG_PATH"}
    changed_top = {key for key in original.keys() | staged.keys()
                   if original.get(key) != staged.get(key)}
    if changed_top - {"WorkingDirectory", "EnvironmentVariables", "ProgramArguments"}:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_TOP_LEVEL_CHANGE")
    if staged.get("WorkingDirectory") != str(app_root):
        raise RuntimeError("STAGED_PLIST_WORKING_DIRECTORY_MISMATCH")
    old_env, new_env = original.get("EnvironmentVariables", {}), staged.get("EnvironmentVariables", {})
    if not isinstance(old_env, dict) or not isinstance(new_env, dict):
        raise RuntimeError("STAGED_PLIST_ENVIRONMENT_INVALID")
    changed_env = {key for key in old_env.keys() | new_env.keys()
                   if old_env.get(key) != new_env.get(key)}
    if changed_env - allowed_selectors:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_ENVIRONMENT_CHANGE")
    required = {"V35_APP_ROOT": str(app_root), "V35_RELEASE_ID": CANDIDATE.name,
                "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
                "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
                "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path)}
    if any(new_env.get(key) != value for key, value in required.items()):
        raise RuntimeError("STAGED_PLIST_SELECTOR_TARGET_MISMATCH")
    if new_env.get("V35_API_PORT") != old_env.get("V35_API_PORT"):
        raise RuntimeError("STAGED_PLIST_API_PORT_CHANGED")
    old_args, new_args = original.get("ProgramArguments", []), staged.get("ProgramArguments", [])
    if not isinstance(old_args, list) or not isinstance(new_args, list):
        raise RuntimeError("STAGED_PLIST_ARGUMENTS_INVALID")
    def assignments(args: list[object]) -> dict[str, str]:
        return {item.split("=", 1)[0]: item.split("=", 1)[1]
                for item in args if isinstance(item, str) and "=" in item}
    old_map, new_map = assignments(old_args), assignments(new_args)
    changed_args = {key for key in old_map.keys() | new_map.keys()
                    if old_map.get(key) != new_map.get(key)}
    if changed_args - allowed_selectors:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_ARGUMENT_CHANGE")
    old_literals = [v for v in old_args if not isinstance(v, str) or "=" not in v]
    new_literals = [v for v in new_args if not isinstance(v, str) or "=" not in v]
    if old_literals != new_literals:
        raise RuntimeError("STAGED_PLIST_NON_SELECTOR_ARGUMENT_CHANGED")
    if "V4_MANAGER_WORKBENCH_CONFIG_PATH" in old_map and new_map.get(
            "V4_MANAGER_WORKBENCH_CONFIG_PATH") != str(config_path):
        raise RuntimeError("STAGED_PLIST_CONFIG_ARGUMENT_MISMATCH")
    for key in ("Label", "KeepAlive", "RunAtLoad"):
        if staged.get(key) != original.get(key):
            raise RuntimeError("STAGED_PLIST_LAUNCH_SETTING_CHANGED:" + key)
    return {"changed_top_level_keys": sorted(changed_top),
            "changed_environment_keys": sorted(changed_env),
            "changed_program_assignment_keys": sorted(changed_args),
            "port_unchanged": True, "label_keepalive_runatload_unchanged": True}


def install_test_copy(web_root: Path, test_source: Path) -> dict[str, object]:
    test_path = web_root / "src/manager-workbench/__tests__/us_mapping_catalog.spec.ts"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    prior = test_path.read_bytes() if test_path.exists() else None
    prior_mode = stat.S_IMODE(test_path.stat().st_mode) if test_path.exists() else None
    test_path.write_bytes(test_source.read_bytes())
    try:
        result = subprocess.run([str(web_root / "node_modules/.bin/vitest"), "run",
                                 "src/manager-workbench/__tests__/us_mapping_catalog.spec.ts"],
                                cwd=web_root, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError("ISOLATED_MANAGER_UI_TEST_FAILED:" + result.stdout[-3000:] + result.stderr[-3000:])
        return {"status": "PASS", "argv": ["node_modules/.bin/vitest", "run",
                "src/manager-workbench/__tests__/us_mapping_catalog.spec.ts"],
                "exit_code": 0, "stdout_tail": result.stdout[-3000:], "stderr_tail": result.stderr[-1000:]}
    finally:
        if prior is None:
            test_path.unlink(missing_ok=True)
        else:
            test_path.write_bytes(prior)
            os.chmod(test_path, prior_mode)


def run_vite_build(web_root: Path, output: Path, *, typecheck: bool) -> dict[str, object]:
    vite = web_root / "node_modules/.bin/vite"
    build = subprocess.run([str(vite), "build", "--outDir", str(output), "--emptyOutDir"],
                           cwd=web_root, capture_output=True, text=True, timeout=300)
    if build.returncode:
        raise RuntimeError("ISOLATED_MANAGER_VITE_BUILD_FAILED:" + build.stdout[-3000:] + build.stderr[-3000:])
    commands = [{"argv": ["node_modules/.bin/vite", "build", "--outDir", "<temporary>", "--emptyOutDir"],
                 "exit_code": build.returncode}]
    type_result = None
    if typecheck:
        cmd = [str(web_root / "node_modules/.bin/vue-tsc"), "--noEmit", "--strict", "--skipLibCheck",
               "--target", "ES2022", "--module", "ESNext", "--moduleResolution", "Bundler",
               "--types", "vitest/globals", "src/manager-workbench/Workbench.vue",
               "src/manager-workbench/useWorkbench.ts"]
        type_result = subprocess.run(cmd, cwd=web_root, capture_output=True, text=True, timeout=300)
        commands.append({"argv": ["node_modules/.bin/vue-tsc", "--noEmit", "--strict", "--skipLibCheck",
                           "--target", "ES2022", "--module", "ESNext", "--moduleResolution", "Bundler",
                           "--types", "vitest/globals", "src/manager-workbench/Workbench.vue",
                           "src/manager-workbench/useWorkbench.ts"], "exit_code": type_result.returncode})
        if type_result.returncode:
            raise RuntimeError("ISOLATED_MANAGER_VUE_TSC_FAILED:" + type_result.stdout[-3000:] + type_result.stderr[-3000:])
    return {"status": "PASS", "commands": commands,
            "vite_stdout_tail": build.stdout[-3000:], "vite_stderr_tail": build.stderr[-1000:],
            "vue_tsc_stdout_tail": type_result.stdout[-3000:] if type_result else None,
            "vue_tsc_stderr_tail": type_result.stderr[-1000:] if type_result else None}


def map_files(root: Path) -> dict[str, dict[str, object]]:
    return {path.relative_to(root).as_posix(): {"sha256": file_sha(path), "bytes": path.stat().st_size,
            "mode": stat.S_IMODE(path.stat().st_mode)}
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def make_new_config(active_raw: bytes, old_relation_root: str, new_relation_root: str) -> bytes:
    text = active_raw.decode("utf-8")
    old_literal = json.dumps(old_relation_root, ensure_ascii=False)
    new_literal = json.dumps(new_relation_root, ensure_ascii=False)
    pattern = re.compile(r'("relation_root"\s*:\s*)' + re.escape(old_literal))
    updated, count = pattern.subn(lambda match: match.group(1) + new_literal, text, count=1)
    if count != 1:
        raise RuntimeError("ACTIVE_CONFIG_RELATION_ROOT_TEXT_NOT_UNIQUE")
    new_value = json.loads(updated)
    old_value = json.loads(active_raw)
    if ({key: value for key, value in new_value.items() if key != "relation_root"}
            != {key: value for key, value in old_value.items() if key != "relation_root"}):
        raise RuntimeError("CONFIG_NON_RELATION_FIELDS_CHANGED")
    return updated.encode("utf-8")


def run_api_check(candidate_app: Path, config_path: Path, python: Path) -> dict[str, object]:
    env = os.environ.copy()
    python_path = os.pathsep.join((str(candidate_app / "upstreams"), str(candidate_app),
                                   str(ROOT), str(RUNTIME)))
    env.update({"PYTHONPATH": python_path, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
                "V4_MAPPING_RECOVERY_CANDIDATE_APP_ROOT": str(candidate_app),
                "V4_MAPPING_RECOVERY_CONFIG_PATH": str(config_path)})
    result = subprocess.run([str(python), "-B", str(API_CHECKER)], cwd=candidate_app,
                            env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("CANDIDATE_INPROCESS_API_CHECK_FAILED:" + result.stdout[-3000:] + result.stderr[-3000:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        summary = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("CANDIDATE_API_CHECK_OUTPUT_INVALID") from exc
    if summary.get("status") != "PASS":
        raise RuntimeError("CANDIDATE_API_CHECK_NOT_PASS")
    return {"status": "PASS", "argv": [str(python), "-B", str(API_CHECKER)],
            "working_directory": str(candidate_app),
            "environment": {"PYTHONPATH": python_path, "PYTHONDONTWRITEBYTECODE": "1",
                            "PYTHONNOUSERSITE": "1", "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path)},
            "summary": summary, "stdout_tail": result.stdout[-3000:], "stderr_tail": result.stderr[-1000:]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-partial-candidate", action="store_true")
    args = parser.parse_args()
    for target in (PREP_PATH, REPORT_PATH, CANDIDATE / "config/cutover-plan.json"):
        if target.exists() or target.is_symlink():
            raise RuntimeError("PREPARE_RECEIPT_ALREADY_EXISTS_REFUSE_OVERWRITE:" + str(target))
    partial_paths = (CANDIDATE, NEW_CONFIG, DELTA_PATH)
    partial_present = [target.exists() or target.is_symlink() for target in partial_paths]
    if args.resume_partial_candidate:
        required_partial = (CANDIDATE / "app", CANDIDATE / "release-manifest.json",
                            CANDIDATE / "config/com.lexi.v35.api-only.plist",
                            CANDIDATE / "config/active-api-plist.preimage", NEW_CONFIG, DELTA_PATH)
        if not all(target.is_file() if target.suffix in {".json", ".plist", ".preimage"} else target.is_dir()
                   for target in required_partial):
            raise RuntimeError("PARTIAL_CANDIDATE_RESUME_INPUTS_INCOMPLETE")
    elif any(partial_present):
        raise RuntimeError("PREPARE_TARGET_ALREADY_EXISTS_REFUSE_OVERWRITE")
    if not WEB_NODE_MODULES.is_dir():
        raise RuntimeError("WEB_NODE_MODULES_UNAVAILABLE")
    if file_sha(OVERLAY_SOURCE) != EXPECTED_OVERLAY_SHA256:
        raise RuntimeError("FROZEN_RECOVERY_OVERLAY_SHA_CHANGED")
    if file_sha(ROOT / "v4/manager_workbench/us_mapping_catalog.py") != EXPECTED_CATALOG_MODULE_SHA256:
        raise RuntimeError("FROZEN_CATALOG_MODULE_SHA_CHANGED")
    if file_sha(ROOT / "apps/web/src/manager-workbench/Workbench.vue") != EXPECTED_WORKBENCH_SHA256:
        raise RuntimeError("FROZEN_WORKBENCH_SHA_CHANGED")
    if file_sha(ROOT / "apps/web/src/manager-workbench/types.ts") != EXPECTED_TYPES_SHA256:
        raise RuntimeError("FROZEN_TYPES_SHA_CHANGED")
    source_review_raw = SOURCE_REVIEW_PATH.read_bytes()
    if (sha(source_review_raw) != EXPECTED_SOURCE_REVIEW_SHA256
            or b"REVIEWED=PASS" not in source_review_raw
            or b"BEHAVIOR_VERIFIED=PASS" not in source_review_raw):
        raise RuntimeError("INDEPENDENT_SOURCE_REVIEW_RECEIPT_CHANGED_OR_NOT_PASS")
    patch, patch_paths = mapping_patch()

    active, active_plist_raw, active_config_path, active_config_raw, active_config, launch_before = ensure_active_identity()
    active_config_mode = stat.S_IMODE(active_config_path.stat().st_mode)
    plist_mode = stat.S_IMODE(PLIST.stat().st_mode)
    interpreter = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
    if not interpreter.is_file():
        raise RuntimeError("ACTIVE_API_PYTHON_UNAVAILABLE")
    plist = plistlib.loads(active_plist_raw)
    active_app = Path(active["app_root"])
    if (file_sha(active_app / BASE_CATALOG_RELATIVE) != "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
            or file_sha(active_app / LEGACY_OVERLAY_RELATIVE) != "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"):
        raise RuntimeError("ACTIVE_ORIGINAL_CATALOG_OR_700_HISTORY_CHANGED")
    if file_sha(active_app / "v4/manager_workbench/us_mapping_catalog.py") != "b7ec08a65a9bb6e2ee419caf303c5ec60b809a44b7a2bef42883ea0fed4023ad":
        raise RuntimeError("ACTIVE_MAPPING_MODULE_PREIMAGE_CHANGED")
    active_web = active_app / "apps/web"
    for relative in ("package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"):
        if file_sha(active_web / relative) != file_sha(ROOT / "apps/web" / relative):
            raise RuntimeError("WEB_BUILD_INPUT_MISMATCH:" + relative)

    runtime_source_before = {relative: file_sha(active_app / relative)
        for relative in sorted(SOURCE_PATCH_PATHS)}
    with tempfile.TemporaryDirectory(prefix="us_hk_recovery_v2r1_runtime_prepare_", dir="/private/tmp") as temp_dir:
        temp = Path(temp_dir)
        seed_app = temp / "seed-app"
        shutil.copytree(active["app_root"], seed_app, symlinks=True)
        if inventory_tree(seed_app) != active["inventory"]:
            raise RuntimeError("ACTIVE_BASE_TEMP_COPY_DRIFT")

        web_root = seed_app / "apps/web"
        node_modules = web_root / "node_modules"
        if node_modules.exists() or node_modules.is_symlink():
            raise RuntimeError("TEMP_WEB_NODE_MODULES_ALREADY_PRESENT")
        def ignore_recursive_node_modules_link(directory: str, names: list[str]) -> set[str]:
            if Path(directory) == WEB_NODE_MODULES and "node_modules" in names:
                recursive = WEB_NODE_MODULES / "node_modules"
                if recursive.is_symlink() and recursive.resolve(strict=False) == WEB_NODE_MODULES.resolve():
                    return {"node_modules"}
            return set()

        shutil.copytree(WEB_NODE_MODULES, node_modules, symlinks=True,
                        ignore=ignore_recursive_node_modules_link)
        try:
            baseline_dist = temp / "baseline-dist"
            baseline_build = run_vite_build(web_root, baseline_dist, typecheck=False)
            active_dist = web_root / "dist"
            baseline_files = map_files(baseline_dist)
            active_dist_files = map_files(active_dist)
            baseline_mismatch = sorted(path for path, row in baseline_files.items()
                if active_dist_files.get(path, {}).get("sha256") != row["sha256"])
            if baseline_mismatch:
                raise RuntimeError("ACTIVE_WEB_DIST_BASELINE_BUILD_MISMATCH:" + ",".join(baseline_mismatch[:12]))

            checked = subprocess.run(["git", "apply", "--check", "-"], cwd=seed_app,
                                     input=patch, capture_output=True, text=True)
            if checked.returncode:
                raise RuntimeError("RUNTIME_MAPPING_HUNKS_DO_NOT_APPLY:" + checked.stderr[-3000:])
            applied = subprocess.run(["git", "apply", "-"], cwd=seed_app,
                                     input=patch, capture_output=True, text=True)
            if applied.returncode:
                raise RuntimeError("RUNTIME_MAPPING_HUNKS_APPLY_FAILED:" + applied.stderr[-3000:])
            if file_sha(seed_app / "v4/manager_workbench/us_mapping_catalog.py") != EXPECTED_CATALOG_MODULE_SHA256:
                raise RuntimeError("RUNTIME_CATALOG_MODULE_AFTER_SHA_MISMATCH")
            shutil.copy2(OVERLAY_SOURCE, seed_app / NEW_OVERLAY_RELATIVE)
            if file_sha(seed_app / NEW_OVERLAY_RELATIVE) != EXPECTED_OVERLAY_SHA256:
                raise RuntimeError("RUNTIME_RECOVERY_OVERLAY_SHA_MISMATCH")

            ui_test = install_test_copy(web_root, ROOT / "apps/web/src/manager-workbench/__tests__/us_mapping_catalog.spec.ts")

            candidate_dist = temp / "candidate-dist"
            candidate_build = run_vite_build(web_root, candidate_dist, typecheck=True)
            candidate_files = map_files(candidate_dist)
            build_delta = []
            for relative, row in sorted(candidate_files.items()):
                previous = active_dist_files.get(relative)
                if previous is not None and previous["sha256"] == row["sha256"]:
                    continue
                manager_bundle = re.fullmatch(r"assets/managerSelection-[A-Za-z0-9_-]+\.js", relative)
                if relative != "manager-selection/index.html" and manager_bundle is None:
                    raise RuntimeError("UNEXPECTED_MANAGER_BUILD_OUTPUT:" + relative)
                target = active_dist / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate_dist / relative, target)
                build_delta.append("apps/web/dist/" + relative)
            if "apps/web/dist/manager-selection/index.html" not in build_delta:
                raise RuntimeError("MANAGER_SELECTION_HTML_ENTRY_NOT_UPDATED")
            if not any(re.fullmatch(r"apps/web/dist/assets/managerSelection-[A-Za-z0-9_-]+\.js", path)
                       for path in build_delta):
                raise RuntimeError("MANAGER_SELECTION_WORKBENCH_JS_BUNDLE_NOT_UPDATED")
            old_entry = (active_dist / "manager-selection/index.html").read_text(encoding="utf-8")
            new_entry = (candidate_dist / "manager-selection/index.html").read_text(encoding="utf-8")
            normalize_entry = lambda value: re.sub(
                r"(/assets/managerSelection-)[A-Za-z0-9_-]+(\.js)", r"\1<HASH>\2", value)
            if (normalize_entry(old_entry) != normalize_entry(new_entry)
                    or normalize_entry(new_entry) == new_entry):
                raise RuntimeError("MANAGER_SELECTION_ENTRY_HAS_NON_BUNDLE_CHANGE")
        finally:
            shutil.rmtree(node_modules)

        candidate_inventory = inventory_tree(seed_app)
        base_by = {str(row["path"]): row for row in active["inventory"]}
        after_by = {str(row["path"]): row for row in candidate_inventory}
        removed = sorted(set(base_by) - set(after_by))
        if removed:
            raise RuntimeError("ACTIVE_APP_PATHS_REMOVED:" + ",".join(removed[:12]))
        changed = sorted(path for path in base_by.keys() | after_by.keys()
                         if base_by.get(path) != after_by.get(path))
        expected_delta = set(SOURCE_PATCH_PATHS) | {NEW_OVERLAY_RELATIVE} | set(build_delta)
        if set(changed) != expected_delta:
            raise RuntimeError("RUNTIME_DELTA_SCOPE_MISMATCH:" + json.dumps(
                {"changed": changed, "expected": sorted(expected_delta)}, ensure_ascii=False))

        entries = []
        for relative in changed:
            old_path = active_app / relative
            new_path = seed_app / relative
            old_sha = file_sha(old_path) if old_path.is_file() else None
            new_sha = file_sha(new_path)
            row: dict[str, object] = {"path": relative, "before_sha256": old_sha,
                                      "after_sha256": new_sha,
                                      "before_bytes": old_path.stat().st_size if old_sha else None,
                                      "after_bytes": new_path.stat().st_size,
                                      "before_mode": stat.S_IMODE(old_path.stat().st_mode) if old_sha else None,
                                      "after_mode": stat.S_IMODE(new_path.stat().st_mode)}
            if old_sha is not None:
                proof, hunk_count = _diff_proof(old_path.read_bytes(), new_path.read_bytes())
                row.update(unified_diff_sha256=proof, unified_diff_hunk_count=hunk_count)
            entries.append(row)
        delta_receipt = {"schema_version": "v4.api_release_delta_receipt.v1",
                         "base": _base_binding(active), "entries": entries,
                         "source_review_receipt_sha256": EXPECTED_SOURCE_REVIEW_SHA256,
                         "mapping_hunks_sha256": EXPECTED_MAPPING_PATCH_SHA256}
        explicit_untracked = [entry["path"] for entry in entries if entry["before_sha256"] is None]
        if DELTA_PATH.exists():
            if not args.resume_partial_candidate or json.loads(DELTA_PATH.read_text(encoding="utf-8")) != delta_receipt:
                raise RuntimeError("EXISTING_DELTA_RECEIPT_MISMATCH_REFUSE_OVERWRITE")
        else:
            write_json_exclusive(DELTA_PATH, delta_receipt)

        # CAS recheck before sealing; PREPARE performs no active-path writes.
        active_again, plist_again, config_path_again, config_again, _cfg, launch_middle = ensure_active_identity()
        if (_base_binding(active_again) != _base_binding(active)
                or plist_again != active_plist_raw or config_path_again != active_config_path
                or config_again != active_config_raw):
            raise RuntimeError("ACTIVE_BASE_OR_CONFIG_CHANGED_DURING_PREPARATION")
        if args.resume_partial_candidate:
            candidate_app = CANDIDATE / "app"
            existing_manifest = json.loads((CANDIDATE / "release-manifest.json").read_text(encoding="utf-8"))
            if inventory_tree(candidate_app) != candidate_inventory:
                raise RuntimeError("PARTIAL_CANDIDATE_APP_DIFFERS_FROM_REBUILT_SEED")
            integration = existing_manifest.get("api_integration")
            if (not isinstance(integration, dict)
                    or integration.get("base") != _base_binding(active)
                    or existing_manifest.get("application_inventory", {}).get("entries") != candidate_inventory
                    or existing_manifest.get("candidate", {}).get("release_id") != CANDIDATE.name
                    or (CANDIDATE / DELTA_RECEIPT_NAME).read_bytes() != DELTA_PATH.read_bytes()):
                raise RuntimeError("PARTIAL_CANDIDATE_MANIFEST_OR_DELTA_MISMATCH")
        else:
            CANDIDATE.mkdir(mode=0o755, exist_ok=False)
            integration = build_integrated_app(active_api_plist_path=PLIST, source_root=seed_app,
                candidate_root=CANDIDATE, delta_receipt_path=DELTA_PATH,
                explicit_untracked_paths=explicit_untracked, role="gateway", base_role="gateway")

    candidate_app = CANDIDATE / "app"
    final_inventory = inventory_tree(candidate_app)
    if final_inventory != candidate_inventory:
        raise RuntimeError("INTEGRATED_CANDIDATE_DIFFERS_FROM_SEALED_SEED")
    manifest_path = CANDIDATE / "release-manifest.json"
    if args.resume_partial_candidate:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("candidate_status") != "PREPARED_NOT_ACTIVATED"
                or manifest.get("activation_status") != "NOT_ACTIVATED"
                or manifest.get("deployment_status") != "CANNOT_CONFIRM"
                or manifest.get("api_integration") != integration
                or manifest.get("application_inventory", {}).get("entries") != final_inventory
                or manifest.get("source", {}).get("source_candidate_review_receipt_sha256")
                    != EXPECTED_SOURCE_REVIEW_SHA256):
            raise RuntimeError("PARTIAL_CANDIDATE_MANIFEST_BINDING_INVALID")
    else:
        manifest = deepcopy(active["manifest"])
        manifest.update(generated_at=datetime.now(timezone.utc).isoformat(),
            candidate_status="PREPARED_NOT_ACTIVATED", activation_status="NOT_ACTIVATED",
            deployment_status="CANNOT_CONFIRM", api_integration=integration)
        manifest["candidate"].update(root=str(CANDIDATE), app_root=str(candidate_app),
            release_id=CANDIDATE.name, module_role="gateway", module_contract_sha256=None,
            data_copy_performed=False, runtime_venv_copied=False, ignored_runtime_data_copied=False)
        manifest["application_inventory"] = {"entry_count": len(final_inventory),
            "aggregate_sha256": inventory_digest(final_inventory), "entries": final_inventory}
        manifest["source"] = {"active_role_plist": str(PLIST), "active_release_bytes_copied": True,
            "source_workspace_full_tree_copied": False, "api_integration_delta_receipt": str(DELTA_PATH),
            "source_candidate_review_receipt": str(SOURCE_REVIEW_PATH),
            "source_candidate_review_receipt_sha256": EXPECTED_SOURCE_REVIEW_SHA256,
            "mapping_hunks_sha256": EXPECTED_MAPPING_PATCH_SHA256}
        manifest["verification_gaps"] = [
            "Independent runtime candidate review pending",
            "Candidate is not activated; live API/UI and natural-slot behavior are unverified",
            "Fact acceptance remains 0; prediction UNTESTED; historical PIT NOT_VALIDATED; event/data tests NOT_RUN",
        ]
        write_json_exclusive(manifest_path, manifest)
    manifest_sha = file_sha(manifest_path)

    new_config_raw = make_new_config(active_config_raw, active_config["relation_root"], str(candidate_app))
    if NEW_CONFIG.exists():
        if not args.resume_partial_candidate or NEW_CONFIG.read_bytes() != new_config_raw:
            raise RuntimeError("NEW_CONFIG_ALREADY_EXISTS_REFUSE_OVERWRITE")
        if stat.S_IMODE(NEW_CONFIG.stat().st_mode) != active_config_mode:
            raise RuntimeError("EXISTING_NEW_CONFIG_MODE_MISMATCH")
    else:
        with NEW_CONFIG.open("xb") as handle:
            handle.write(new_config_raw)
        os.chmod(NEW_CONFIG, active_config_mode)
    new_config_sha = file_sha(NEW_CONFIG)

    original_plist = plistlib.loads(active_plist_raw)
    staged = rewrite_api_only_plist(original_plist, candidate_app_root=candidate_app,
        release_id=CANDIDATE.name, manifest_path=manifest_path, manifest_sha256=manifest_sha,
        candidate_manager_state_root=None)
    staged_env = staged.setdefault("EnvironmentVariables", {})
    staged_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"] = str(NEW_CONFIG)
    staged["ProgramArguments"] = [
        "V4_MANAGER_WORKBENCH_CONFIG_PATH=" + str(NEW_CONFIG)
        if isinstance(arg, str) and arg.startswith("V4_MANAGER_WORKBENCH_CONFIG_PATH=") else arg
        for arg in staged["ProgramArguments"]]
    plist_validation = validate_staged_plist(original_plist, staged, app_root=candidate_app,
        manifest_path=manifest_path, manifest_sha=manifest_sha, config_path=NEW_CONFIG)
    candidate_config_dir = CANDIDATE / "config"
    if candidate_config_dir.exists():
        if not args.resume_partial_candidate or stat.S_IMODE(candidate_config_dir.stat().st_mode) != 0o700:
            raise RuntimeError("CANDIDATE_CONFIG_DIR_ALREADY_EXISTS_OR_MODE_INVALID")
    else:
        candidate_config_dir.mkdir(mode=0o700)
    staged_plist = candidate_config_dir / "com.lexi.v35.api-only.plist"
    staged_plist_raw = plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True)
    if staged_plist.exists():
        if not args.resume_partial_candidate or staged_plist.read_bytes() != staged_plist_raw:
            raise RuntimeError("STAGED_PLIST_ALREADY_EXISTS_OR_CONTENT_MISMATCH")
        if stat.S_IMODE(staged_plist.stat().st_mode) != plist_mode:
            raise RuntimeError("STAGED_PLIST_MODE_MISMATCH")
    else:
        with staged_plist.open("xb") as handle:
            handle.write(staged_plist_raw)
        os.chmod(staged_plist, plist_mode)
    rollback_plist = candidate_config_dir / "active-api-plist.preimage"
    if rollback_plist.exists():
        if not args.resume_partial_candidate or rollback_plist.read_bytes() != active_plist_raw:
            raise RuntimeError("ROLLBACK_PLIST_ALREADY_EXISTS_OR_CONTENT_MISMATCH")
        if stat.S_IMODE(rollback_plist.stat().st_mode) != 0o600:
            raise RuntimeError("ROLLBACK_PLIST_MODE_MISMATCH")
    else:
        with rollback_plist.open("xb") as handle:
            handle.write(active_plist_raw)
        os.chmod(rollback_plist, 0o600)
    if (file_sha(rollback_plist) != EXPECTED_ACTIVE_PLIST_SHA256
            or rollback_plist.read_bytes() != active_plist_raw):
        raise RuntimeError("ROLLBACK_PREIMAGE_NOT_BYTE_IDENTICAL")

    api_test = run_api_check(candidate_app, NEW_CONFIG, interpreter)
    candidate_verification = verify_api_release_candidate(candidate_root=CANDIDATE,
        active_api_plist_path=PLIST, expected_manifest_sha256=manifest_sha,
        active_pointer="base", role="gateway", base_role="gateway")
    active_after, final_plist, final_config_path, final_config, _cfg_after, launch_after = ensure_active_identity()
    if (_base_binding(active_after) != _base_binding(active)
            or final_plist != active_plist_raw or final_config_path != active_config_path
            or final_config != active_config_raw):
        raise RuntimeError("ACTIVE_BASE_OR_CONFIG_CHANGED_AFTER_PREPARATION")

    plan: dict[str, object] = {
        "schema_version": "v4.us_hk_recovery_v2r1_runtime_preparation.v1",
        "status": "PREPARED_NOT_ACTIVATED", "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False, "launchctl_read_only_query_called": True,
        "prepare_command": "PYTHONPATH=. .venv/bin/python -B docs/handoffs/us_hk_recovery_v2r1_20261016/runtime/prepare_runtime_candidate.py --resume-partial-candidate",
        "resumed_incomplete_prepare_after_api_assertion_fix": bool(args.resume_partial_candidate),
        "source_review": {"path": str(SOURCE_REVIEW_PATH), "sha256": EXPECTED_SOURCE_REVIEW_SHA256,
                           "status": "REVIEWED_PASS_AND_BEHAVIOR_VERIFIED_PASS"},
        "active_plist_path": str(PLIST), "active_plist_sha256": EXPECTED_ACTIVE_PLIST_SHA256,
        "active_plist_bytes": len(active_plist_raw), "active_plist_mode": oct(plist_mode),
        "active_release_id": active["release_id"], "active_release_root": active["release_root"],
        "active_app_root": active["app_root"], "active_manifest_sha256": active["release_manifest_sha256"],
        "active_application_inventory_sha256": active["application_inventory_sha256"],
        "active_application_inventory_entry_count": len(active["inventory"]),
        "active_config_path": str(active_config_path), "active_config_sha256": EXPECTED_ACTIVE_CONFIG_SHA256,
        "active_relation_root": active_config["relation_root"],
        "new_config_path": str(NEW_CONFIG), "new_config_sha256": new_config_sha,
        "new_relation_root": str(candidate_app), "config_changed_keys": ["relation_root"],
        "config_other_values_byte_preserved": True, "active_config_mode": oct(active_config_mode),
        "candidate_root": str(CANDIDATE), "candidate_app_root": str(candidate_app),
        "candidate_release_id": CANDIDATE.name, "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": manifest_sha,
        "staged_plist_path": str(staged_plist), "staged_plist_sha256": file_sha(staged_plist),
        "rollback_plist_path": str(rollback_plist), "rollback_plist_sha256": file_sha(rollback_plist),
        "shared_release_lock_path": str(api_release_lock_path(PLIST, role="gateway")),
        "runtime_delta_receipt_path": str(DELTA_PATH), "runtime_delta_receipt_sha256": file_sha(DELTA_PATH),
        "delta_paths": changed, "build_delta_paths": build_delta,
        "non_delta_entry_count": integration["non_delta_entry_count"],
        "non_delta_inventory_sha256": integration["non_delta_inventory_sha256"],
        "runtime_source_before_sha256": runtime_source_before,
        "runtime_source_after_sha256": {relative: file_sha(candidate_app / relative)
                                         for relative in sorted(SOURCE_PATCH_PATHS)},
        "new_overlay_sha256": file_sha(candidate_app / NEW_OVERLAY_RELATIVE),
        "base_catalog_sha256": file_sha(candidate_app / BASE_CATALOG_RELATIVE),
        "legacy_700_overlay_sha256": file_sha(candidate_app / LEGACY_OVERLAY_RELATIVE),
        "api_only_service_before": launch_before, "api_only_service_mid": launch_middle,
        "api_only_service_after": launch_after,
        "baseline_build": baseline_build, "candidate_build": candidate_build,
        "candidate_ui_test": ui_test, "candidate_inprocess_api_test": api_test,
        "candidate_verification": candidate_verification,
        "staged_plist_validation": plist_validation,
        "rollback_plan": [
            "Under the shared API release lock, recheck the exact active plist and active config SHA256 values recorded here.",
            "Verify the independent runtime review receipt is bound to this candidate manifest SHA256 and reports REVIEWED=PASS and BEHAVIOR_VERIFIED=PASS.",
            "Verify the saved rollback plist is byte-identical to the active plist preimage and the staged plist/config/release hashes still match this receipt.",
            "Only after separate explicit root authorization, use the new activate_runtime_candidate.py helper; on readback failure it restores the exact saved plist preimage and bootstraps the prior API-only service.",
        ],
        "activation_gate": "NOT_EXECUTED: PREPARE only; independent runtime review and separate explicit authorization required.",
        "runtime_acceptance": {"candidate_inprocess_api": "PASS", "isolated_manager_ui_test": "PASS",
                               "isolated_manager_build": "PASS", "runtime_reviewer": "PENDING",
                               "live_api": "NOT_RUN", "live_ui": "NOT_RUN", "deployment": "NOT_RUN",
                               "natural_slot": "NOT_RUN"},
        "CANNOT_CONFIRM": ["Independent runtime candidate review", "Live API/UI under candidate",
                           "Deployment, natural-slot behavior, semantic mapping validity, PIT and prediction validity"],
    }
    write_json_exclusive(PREP_PATH, plan)
    write_json_exclusive(CANDIDATE / "config/cutover-plan.json", plan)
    report = f"""# US-HK recovery v2r1 runtime candidate PREPARED

Status: PREPARED_NOT_ACTIVATED. No service, plist, active config, scheduled task, trading permission, or BUY gate was changed. Only a new immutable release and a new versioned config were created.

Fresh API-only baseline: plist {plan['active_plist_sha256']}; release {plan['active_release_id']} manifest {plan['active_manifest_sha256']}; application inventory {plan['active_application_inventory_sha256']} ({plan['active_application_inventory_entry_count']} entries); active config {plan['active_config_path']} SHA256 {plan['active_config_sha256']}. Existing relation_root: {plan['active_relation_root']}.

Candidate: {plan['candidate_root']} manifest SHA256 {plan['candidate_manifest_sha256']}. New config {plan['new_config_path']} SHA256 {plan['new_config_sha256']}; its only key-value change is relation_root to {plan['new_relation_root']}. Rollback preimage is byte-identical to the current API-only plist.

The source review passed independently at {SOURCE_REVIEW_PATH} (SHA256 {EXPECTED_SOURCE_REVIEW_SHA256}). Candidate delta paths: {', '.join(changed)}. All other {integration['non_delta_entry_count']} app inventory entries were preserved byte-for-byte (inventory SHA256 {integration['non_delta_inventory_sha256']}). The mapping overlay is a new sibling file; original catalog and old 700-relation history hashes remain unchanged.

Verification: baseline build reproduced the active static output; isolated mapping UI test passed; isolated Vite build and targeted Vue typecheck passed; in-process API check passed for 667/1003 counts, 757/25/221 closure totals, exact-RID FULL records, prior 700 history, and safety flags. Candidate verifier returned {candidate_verification['status']} against the base pointer. No live API/UI, activation, or natural-slot verification was performed.

Activation remains gated on a separate independent runtime candidate review bound to this manifest SHA and a later explicit root authorization. See RUNTIME_PREPARATION_RECEIPT.json for exact inventories, commands, hashes, readbacks, and rollback plan.
"""
    with REPORT_PATH.open("x", encoding="utf-8") as handle:
        handle.write(report)
    print(json.dumps({"status": plan["status"], "candidate_root": str(CANDIDATE),
        "candidate_manifest_sha256": manifest_sha, "active_plist_sha256": EXPECTED_ACTIVE_PLIST_SHA256,
        "active_release_id": active["release_id"], "delta_paths": changed,
        "non_delta_entry_count": integration["non_delta_entry_count"],
        "config_path": str(NEW_CONFIG), "config_sha256": new_config_sha,
        "inprocess_api": api_test["summary"], "activation_status": "NOT_ACTIVATED"},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
