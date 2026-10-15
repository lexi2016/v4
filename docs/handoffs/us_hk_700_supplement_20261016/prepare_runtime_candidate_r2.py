"""Prepare the second mapping700 candidate from the freshly selected API release.

This batch-local helper preserves the r1 evidence, copies the current plist-bound
base, and reuses only the already-reviewed mapping delta and manager-selection
build outputs whose exact source and byte hashes still match. It never calls
launchctl or modifies the active release, config, or plist.
"""
from __future__ import annotations

from contextlib import contextmanager
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

import ops.api_release_integration as release_api
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

from prepare_runtime_candidate import (
    CATALOG_MODULE_SHA256,
    OVERLAY_SHA256,
    OVERLAY_SOURCE,
    ROOT,
    RUNTIME_PATCH_PATHS,
    SOURCE_PATCH,
    SOURCE_PATCH_SHA256,
    patch_sections,
    write_json_exclusive,
)


HANDOFF = Path(__file__).resolve().parent
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CANDIDATE = BASE / "releases/us-hk-mapping700-20261016-r2"
NEW_CONFIG = BASE / "config/us-hk-mapping700-20261016-r2.json"
R2_DELTA_PATH = HANDOFF / "runtime-delta-receipt-r2.json"
R2_PREP_PATH = HANDOFF / "candidate-preparation-receipt-r2.json"
R2_REPORT_PATH = HANDOFF / "RUNTIME_PREPARED_RECEIPT_R2.md"
API_CHECKER = HANDOFF / "check_runtime_candidate_api.py"

EXPECTED_ACTIVE_PLIST_SHA256 = "33df4ecc0cfaa8e574e99a73acdb14dd6c6587fe5deb9f2b15035746517293ce"
EXPECTED_ACTIVE_CONFIG_PATH = BASE / "config/oversold-nextday-recovery-20261015-r1.json"
EXPECTED_ACTIVE_CONFIG_SHA256 = "f4bc5c37fb08d57766bf3cd596f9fe4abdc6c32a327e09bc99c5f555822c7158"
EXPECTED_ACTIVE_RELEASE_ID = "zsxq-pdf-ocr-api-20261016-r1"
EXPECTED_ACTIVE_MANIFEST_SHA256 = "3838f2784ee1b8fa197e8022be505e803f0d322b4788e9c209c1dc30d99f69e3"
EXPECTED_ACTIVE_INVENTORY_SHA256 = "0f6636b790a92b6c5ceaba2482a60ca00f57700c2da21ca0a76c5dceaab678ee"

R1_ROOT = BASE / "releases/us-hk-mapping700-20261016-r1"
R1_APP = R1_ROOT / "app"
R1_DELTA_PATH = HANDOFF / "runtime-delta-receipt.json"
R1_PREP_PATH = HANDOFF / "candidate-preparation-receipt.json"
R1_REVIEW_PATH = HANDOFF / "RUNTIME_INDEPENDENT_REVIEW.md"
R1_MANIFEST_SHA256 = "105a17529f35595a34b52a7589df23e6bafb1099de3e6072aeaddab1508094ba"
R1_DELTA_SHA256 = "4ca811585ee43d8d60fe4913b69eae5908fecf4a1706cb1b79a6e2f9737800e8"
R1_BASE_MANIFEST_SHA256 = "5c6e18640443c65d647e5072ce82472de2f813ef35d245065006ba44a1fe8684"
R1_OVERLAY_BEFORE_SHA256 = "72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384"
R1_OVERLAY_AFTER_SHA256 = "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"

REUSED_WEB_DIFF_PATHS = {
    "apps/web/dist/assets/main-CLH3RZcq.js",
    "apps/web/dist/assets/main-D2BN7hIb.css",
    "apps/web/dist/index.html",
    "apps/web/src/api/research_lane.ts",
    "apps/web/src/components/research/ResearchFeedCard.vue",
    "apps/web/src/composables/useResearchLane.ts",
    "apps/web/src/styles/v3-research-lane.css",
}
BUILD_INPUT_PATHS = {
    "apps/web/package.json",
    "apps/web/package-lock.json",
    "apps/web/vite.config.ts",
    "apps/web/tsconfig.json",
}
OVERLAY_RELATIVE = "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json"
EXPECTED_R1_REUSE_PATHS = {
    "apps/web/dist/assets/managerSelection-CnQlnjWW.js",
    "apps/web/dist/manager-selection/index.html",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def ensure_active_identity() -> tuple[dict[str, object], bytes, Path, bytes, dict[str, object]]:
    plist_raw = PLIST.read_bytes()
    if sha(plist_raw) != EXPECTED_ACTIVE_PLIST_SHA256:
        raise RuntimeError("ACTIVE_PLIST_CHANGED_REBASE_REQUIRED")
    plist_value = plistlib.loads(plist_raw)
    config_path = Path(plist_value["EnvironmentVariables"]["V4_MANAGER_WORKBENCH_CONFIG_PATH"])
    if config_path != EXPECTED_ACTIVE_CONFIG_PATH:
        raise RuntimeError("ACTIVE_CONFIG_PATH_CHANGED_REBASE_REQUIRED")
    config_raw = config_path.read_bytes()
    if sha(config_raw) != EXPECTED_ACTIVE_CONFIG_SHA256:
        raise RuntimeError("ACTIVE_CONFIG_CHANGED_REBASE_REQUIRED")
    active = read_active_release(PLIST, role="gateway")
    if (active["release_id"] != EXPECTED_ACTIVE_RELEASE_ID
            or active["release_manifest_sha256"] != EXPECTED_ACTIVE_MANIFEST_SHA256
            or active["application_inventory_sha256"] != EXPECTED_ACTIVE_INVENTORY_SHA256):
        raise RuntimeError("ACTIVE_RELEASE_CHANGED_REBASE_REQUIRED")
    config = json.loads(config_raw)
    return active, plist_raw, config_path, config_raw, config


def assignments(args: list[object]) -> dict[str, str]:
    return {item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in args if isinstance(item, str) and "=" in item}


def validate_staged_plist(original: dict[str, object], staged: dict[str, object],
                          *, app_root: Path, manifest_path: Path, manifest_sha: str,
                          config_path: Path) -> dict[str, object]:
    allowed_selectors = {
        "V35_APP_ROOT", "V35_RELEASE_ID", "PYTHONPATH", "V35_RELEASE_MANIFEST_PATH",
        "V35_RELEASE_MANIFEST_SHA256", "V4_MANAGER_WORKBENCH_CONFIG_PATH",
    }
    changed_top_level = {key for key in original.keys() | staged.keys()
                         if original.get(key) != staged.get(key)}
    if changed_top_level - {"WorkingDirectory", "EnvironmentVariables", "ProgramArguments"}:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_TOP_LEVEL_CHANGE")
    if staged.get("WorkingDirectory") != str(app_root):
        raise RuntimeError("STAGED_PLIST_WORKING_DIRECTORY_MISMATCH")

    old_env = original.get("EnvironmentVariables", {})
    new_env = staged.get("EnvironmentVariables", {})
    if not isinstance(old_env, dict) or not isinstance(new_env, dict):
        raise RuntimeError("STAGED_PLIST_ENVIRONMENT_INVALID")
    env_changes = {key for key in old_env.keys() | new_env.keys()
                   if old_env.get(key) != new_env.get(key)}
    if env_changes - allowed_selectors:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_ENVIRONMENT_CHANGE")
    if (new_env.get("V35_APP_ROOT") != str(app_root)
            or new_env.get("V35_RELEASE_ID") != CANDIDATE.name
            or new_env.get("V35_RELEASE_MANIFEST_PATH") != str(manifest_path)
            or new_env.get("V35_RELEASE_MANIFEST_SHA256") != manifest_sha
            or new_env.get("V4_MANAGER_WORKBENCH_CONFIG_PATH") != str(config_path)):
        raise RuntimeError("STAGED_PLIST_SELECTOR_TARGET_MISMATCH")
    if new_env.get("V35_API_PORT") != old_env.get("V35_API_PORT"):
        raise RuntimeError("STAGED_PLIST_PORT_CHANGED")

    old_args = original.get("ProgramArguments", [])
    new_args = staged.get("ProgramArguments", [])
    if not isinstance(old_args, list) or not isinstance(new_args, list):
        raise RuntimeError("STAGED_PLIST_ARGUMENTS_INVALID")
    old_assignments = assignments(old_args)
    new_assignments = assignments(new_args)
    changed_assignments = {key for key in old_assignments.keys() | new_assignments.keys()
                           if old_assignments.get(key) != new_assignments.get(key)}
    if changed_assignments - allowed_selectors:
        raise RuntimeError("STAGED_PLIST_UNEXPECTED_ARGUMENT_CHANGE")
    old_literals = [item for item in old_args if not isinstance(item, str) or "=" not in item]
    new_literals = [item for item in new_args if not isinstance(item, str) or "=" not in item]
    if old_literals != new_literals:
        raise RuntimeError("STAGED_PLIST_NON_SELECTOR_ARGUMENT_CHANGED")
    if "V4_MANAGER_WORKBENCH_CONFIG_PATH" in old_assignments and (
            new_assignments.get("V4_MANAGER_WORKBENCH_CONFIG_PATH") != str(config_path)):
        raise RuntimeError("STAGED_PLIST_CONFIG_ARGUMENT_MISMATCH")
    for key in ("Label", "KeepAlive", "RunAtLoad"):
        if staged.get(key) != original.get(key):
            raise RuntimeError("STAGED_PLIST_LAUNCH_SETTING_CHANGED:" + key)
    return {"changed_top_level_keys": sorted(changed_top_level),
            "changed_environment_keys": sorted(env_changes),
            "changed_program_assignment_keys": sorted(changed_assignments),
            "port_unchanged": True, "label_keepalive_runatload_unchanged": True}


def verify_r1_reuse(active: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    delta_raw = R1_DELTA_PATH.read_bytes()
    if sha(delta_raw) != R1_DELTA_SHA256:
        raise RuntimeError("R1_DELTA_RECEIPT_CHANGED")
    delta = json.loads(delta_raw)
    prep = json.loads(R1_PREP_PATH.read_text(encoding="utf-8"))
    if prep.get("candidate_manifest_sha256") != R1_MANIFEST_SHA256:
        raise RuntimeError("R1_PREPARATION_RECEIPT_MANIFEST_MISMATCH")
    r1_manifest_raw = (R1_ROOT / "release-manifest.json").read_bytes()
    if sha(r1_manifest_raw) != R1_MANIFEST_SHA256:
        raise RuntimeError("R1_CANDIDATE_MANIFEST_CHANGED")
    r1_manifest = json.loads(r1_manifest_raw)
    if r1_manifest["api_integration"].get("delta_receipt_sha256") != R1_DELTA_SHA256:
        raise RuntimeError("R1_CANDIDATE_DELTA_RECEIPT_MISMATCH")
    if delta.get("base", {}).get("release_manifest_sha256") != R1_BASE_MANIFEST_SHA256:
        raise RuntimeError("R1_DELTA_BASE_IDENTITY_MISMATCH")
    old_base = Path(delta["base"]["app_root"])
    old_base_manifest = json.loads(Path(delta["base"]["release_manifest_path"]).read_text(encoding="utf-8"))
    old_base_inventory = inventory_tree(old_base)
    if (sha(Path(delta["base"]["release_manifest_path"]).read_bytes()) != R1_BASE_MANIFEST_SHA256
            or inventory_digest(old_base_inventory) != delta["base"]["application_inventory_sha256"]
            or len(old_base_inventory) != delta["base"]["application_inventory_entry_count"]
            or old_base_inventory != old_base_manifest["application_inventory"]["entries"]):
        raise RuntimeError("R1_BASE_INVENTORY_CHANGED")
    review_text = R1_REVIEW_PATH.read_text(encoding="utf-8")
    if (f"Candidate manifest SHA256: `{R1_MANIFEST_SHA256}`" not in review_text
            or "BEHAVIOR_VERIFIED=PASS" not in review_text
            or "HELPER_REVIEW_PASS=PASS" not in review_text):
        raise RuntimeError("R1_INDEPENDENT_CONTENT_REVIEW_MISSING")
    review_binding = {"path": str(R1_REVIEW_PATH), "sha256": file_sha(R1_REVIEW_PATH),
                      "candidate_manifest_sha256": R1_MANIFEST_SHA256,
                      "candidate_behavior_reviewed": True,
                      "activation_precondition_status": "STALE_ACTIVE_PLIST_CAS"}

    current_inv = {str(row["path"]): row for row in active["inventory"]}
    old_inv = {str(row["path"]): row for row in old_base_inventory}
    changed_paths = sorted(path for path in current_inv.keys() | old_inv.keys()
                           if current_inv.get(path) != old_inv.get(path))
    web_changed = {path for path in changed_paths if path.startswith("apps/web/")}
    if web_changed != REUSED_WEB_DIFF_PATHS:
        raise RuntimeError("MANAGER_SELECTION_BUILD_BASELINE_CHANGED:" + json.dumps(sorted(web_changed)))
    for relative in BUILD_INPUT_PATHS:
        if current_inv.get(relative) != old_inv.get(relative):
            raise RuntimeError("MANAGER_SELECTION_BUILD_INPUT_CHANGED:" + relative)

    r1_entries = {str(entry["path"]): entry for entry in delta["entries"]}
    if OVERLAY_RELATIVE not in r1_entries:
        raise RuntimeError("R1_OVERLAY_DELTA_MISSING")
    overlay_entry = r1_entries[OVERLAY_RELATIVE]
    if (overlay_entry.get("before_sha256") != R1_OVERLAY_BEFORE_SHA256
            or overlay_entry.get("after_sha256") != R1_OVERLAY_AFTER_SHA256
            or not isinstance(overlay_entry.get("unified_diff_sha256"), str)
            or not isinstance(overlay_entry.get("unified_diff_hunk_count"), int)):
        raise RuntimeError("R1_OVERLAY_DIFF_PROOF_INVALID")
    current_overlay_sha = file_sha(Path(active["app_root"]) / OVERLAY_RELATIVE)
    if current_overlay_sha != R1_OVERLAY_BEFORE_SHA256:
        raise RuntimeError("R2_ACTIVE_OVERLAY_PREIMAGE_MISMATCH")

    if set(r1_entries) - EXPECTED_R1_REUSE_PATHS - RUNTIME_PATCH_PATHS - {OVERLAY_RELATIVE}:
        raise RuntimeError("R1_REUSE_DELTA_PATHS_UNEXPECTED")
    if EXPECTED_R1_REUSE_PATHS - set(r1_entries):
        raise RuntimeError("R1_MANAGER_BUILD_OUTPUT_MISSING")
    for relative in RUNTIME_PATCH_PATHS:
        entry = r1_entries[relative]
        if file_sha(Path(active["app_root"]) / relative) != entry["before_sha256"]:
            raise RuntimeError("R2_SOURCE_DELTA_PREIMAGE_MISMATCH:" + relative)
    for relative in ("apps/web/dist/manager-selection/index.html",):
        if file_sha(Path(active["app_root"]) / relative) != r1_entries[relative]["before_sha256"]:
            raise RuntimeError("R2_MANAGER_HTML_PREIMAGE_MISMATCH")
    for relative in EXPECTED_R1_REUSE_PATHS:
        target = R1_APP / relative
        if file_sha(target) != r1_entries[relative]["after_sha256"]:
            raise RuntimeError("R1_REUSED_BUILD_OUTPUT_SHA_MISMATCH:" + relative)
    if prep.get("baseline_build", {}).get("commands", [{}])[0].get("exit_code") != 0:
        raise RuntimeError("R1_BASELINE_BUILD_NOT_PASS")
    candidate_commands = prep.get("candidate_build", {}).get("commands", [])
    if (not candidate_commands or any(row.get("exit_code") != 0 for row in candidate_commands)
            or prep.get("candidate_build", {}).get("vue_tsc_stdout_tail") is None):
        raise RuntimeError("R1_CANDIDATE_BUILD_OR_TYPECHECK_NOT_PASS")
    return delta, r1_entries, {"r1_review": review_binding, "r1_delta_receipt_sha256": R1_DELTA_SHA256,
        "r1_candidate_manifest_sha256": R1_MANIFEST_SHA256, "r1_base_manifest_sha256": R1_BASE_MANIFEST_SHA256,
        "manager_selection_build_reused": True, "web_tree_changes_vs_r1_base": sorted(web_changed),
        "build_input_sha256_matches_r1_base": True,
        "reused_build_outputs": {path: r1_entries[path]["after_sha256"] for path in sorted(EXPECTED_R1_REUSE_PATHS)},
        "r1_build_and_vue_tsc_pass": True}


@contextmanager
def reuse_exact_overlay_diff_proof(before_sha: str, after_sha: str,
                                   proof_sha: str, hunk_count: int):
    original = release_api._diff_proof

    def fast_diff(before: bytes, after: bytes):
        if sha(before) == before_sha and sha(after) == after_sha:
            return proof_sha, hunk_count
        return original(before, after)

    release_api._diff_proof = fast_diff
    try:
        yield
    finally:
        release_api._diff_proof = original


def create_delta_receipt(active: dict[str, object], seed_app: Path,
                         r1_entries: dict[str, dict[str, object]],
                         reuse_record: dict[str, object]) -> tuple[dict[str, object], set[str]]:
    changed = sorted(set(RUNTIME_PATCH_PATHS) | {OVERLAY_RELATIVE} | EXPECTED_R1_REUSE_PATHS)
    entries: list[dict[str, object]] = []
    for relative in changed:
        old_path = Path(active["app_root"]) / relative
        new_path = seed_app / relative
        old_sha = file_sha(old_path) if old_path.is_file() else None
        new_sha = file_sha(new_path)
        prior = r1_entries[relative]
        if old_sha != prior.get("before_sha256") or new_sha != prior.get("after_sha256"):
            raise RuntimeError("R2_DELTA_SHA_NOT_IDENTICAL_TO_REVIEWED_R1:" + relative)
        row: dict[str, object] = {"path": relative, "before_sha256": old_sha, "after_sha256": new_sha}
        if old_sha is not None:
            if relative == OVERLAY_RELATIVE:
                row["unified_diff_sha256"] = prior["unified_diff_sha256"]
                row["unified_diff_hunk_count"] = prior["unified_diff_hunk_count"]
                row["diff_proof_reused_from"] = {
                    "receipt_path": str(R1_DELTA_PATH),
                    "receipt_sha256": reuse_record["r1_delta_receipt_sha256"],
                    "candidate_manifest_sha256": reuse_record["r1_candidate_manifest_sha256"],
                }
            else:
                diff_sha, hunk_count = _diff_proof(old_path.read_bytes(), new_path.read_bytes())
                if diff_sha != prior.get("unified_diff_sha256") or hunk_count != prior.get("unified_diff_hunk_count"):
                    raise RuntimeError("R2_SMALL_DELTA_DIFF_PROOF_MISMATCH:" + relative)
                row["unified_diff_sha256"] = diff_sha
                row["unified_diff_hunk_count"] = hunk_count
        entries.append(row)
    receipt: dict[str, object] = {
        "schema_version": "v4.api_release_delta_receipt.v1",
        "base": _base_binding(active),
        "entries": entries,
        "r1_delta_proof_reuse": {
            "r1_delta_receipt_path": str(R1_DELTA_PATH),
            "r1_delta_receipt_sha256": reuse_record["r1_delta_receipt_sha256"],
            "r1_candidate_manifest_sha256": reuse_record["r1_candidate_manifest_sha256"],
            "overlay_before_sha256": R1_OVERLAY_BEFORE_SHA256,
            "overlay_after_sha256": R1_OVERLAY_AFTER_SHA256,
            "overlay_unified_diff_sha256": r1_entries[OVERLAY_RELATIVE]["unified_diff_sha256"],
            "overlay_unified_diff_hunk_count": r1_entries[OVERLAY_RELATIVE]["unified_diff_hunk_count"],
            "reuse_rule": "Reuse only if exact before/after overlay SHA256 pair matches; full candidate and base inventories are still recomputed.",
        },
    }
    added_paths = {str(entry["path"]) for entry in entries if entry["before_sha256"] is None}
    return receipt, added_paths


def run_candidate_api_check(candidate_app: Path, config_path: Path) -> dict[str, object]:
    env = os.environ.copy()
    python_path = os.pathsep.join((str(candidate_app / "upstreams"), str(candidate_app), str(ROOT), str(HANDOFF)))
    env.update({
        "PYTHONPATH": python_path,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
        "V4_MAPPING700_CANDIDATE_APP_ROOT": str(candidate_app),
        "V4_MAPPING700_CONFIG_PATH": str(config_path),
    })
    command = [str(ROOT / ".venv/bin/python"), str(API_CHECKER)]
    result = subprocess.run(command, cwd=candidate_app, env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("CANDIDATE_API_CHECK_FAILED:" + result.stdout[-3000:] + result.stderr[-3000:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        summary = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("CANDIDATE_API_CHECK_OUTPUT_INVALID") from exc
    if summary.get("status") != "PASS":
        raise RuntimeError("CANDIDATE_API_CHECK_NOT_PASS")
    return {
        "status": "PASS", "command": " ".join(command),
        "working_directory": str(candidate_app), "environment": {
            "PYTHONPATH": python_path, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
            "V4_MAPPING700_CANDIDATE_APP_ROOT": str(candidate_app),
            "V4_MAPPING700_CONFIG_PATH": str(config_path),
        },
        "summary": summary,
        "stdout_tail": result.stdout[-3000:], "stderr_tail": result.stderr[-2000:],
    }


def main() -> None:
    if (CANDIDATE.exists() or NEW_CONFIG.exists() or R2_DELTA_PATH.exists()
            or R2_PREP_PATH.exists() or R2_REPORT_PATH.exists()):
        raise RuntimeError("R2_TARGET_OR_RECEIPT_ALREADY_EXISTS_REFUSE_OVERWRITE")
    if sha(SOURCE_PATCH.read_bytes()) != SOURCE_PATCH_SHA256:
        raise RuntimeError("SOURCE_PATCH_SHA_CHANGED")
    if file_sha(OVERLAY_SOURCE) != OVERLAY_SHA256:
        raise RuntimeError("OVERLAY_SHA_CHANGED")
    if file_sha(ROOT / "v4/manager_workbench/us_mapping_catalog.py") != CATALOG_MODULE_SHA256:
        raise RuntimeError("CATALOG_MODULE_SHA_CHANGED")

    active, original_plist_raw, active_config_path, active_config_raw, active_config = ensure_active_identity()
    reuse_delta, r1_entries, reuse_record = verify_r1_reuse(active)
    active_config_mode = stat.S_IMODE(active_config_path.stat().st_mode)
    plist_mode = stat.S_IMODE(PLIST.stat().st_mode)
    active_web = Path(active["app_root"]) / "apps/web"
    for relative in BUILD_INPUT_PATHS:
        workspace_relative = relative.removeprefix("apps/web/")
        if file_sha(active_web / workspace_relative) != file_sha(ROOT / relative):
            raise RuntimeError("WEB_BUILD_INPUT_MISMATCH:" + relative)

    with tempfile.TemporaryDirectory(prefix="mapping700_runtime_candidate_r2_", dir="/private/tmp") as temp_dir:
        temp = Path(temp_dir)
        seed_app = temp / "seed-app"
        shutil.copytree(active["app_root"], seed_app, symlinks=True)
        if inventory_tree(seed_app) != active["inventory"]:
            raise RuntimeError("ACTIVE_BASE_TEMP_COPY_DRIFT")
        patch_text, patch_paths = patch_sections(SOURCE_PATCH.read_text(encoding="utf-8"))
        if patch_paths != RUNTIME_PATCH_PATHS:
            raise RuntimeError("RUNTIME_SOURCE_PATCH_PATHS_INVALID")
        checked = subprocess.run(["git", "apply", "--check", "-"], cwd=seed_app,
                                 input=patch_text, capture_output=True, text=True)
        if checked.returncode:
            raise RuntimeError("ACTIVE_SOURCE_DELTA_PATCH_CHECK_FAILED:" + checked.stderr[-3000:])
        patched = subprocess.run(["git", "apply", "-"], cwd=seed_app,
                                 input=patch_text, capture_output=True, text=True)
        if patched.returncode:
            raise RuntimeError("ACTIVE_SOURCE_DELTA_PATCH_FAILED:" + patched.stderr[-3000:])
        for relative in RUNTIME_PATCH_PATHS:
            if file_sha(seed_app / relative) != r1_entries[relative]["after_sha256"]:
                raise RuntimeError("R2_PATCHED_SOURCE_SHA_MISMATCH:" + relative)
        shutil.copy2(OVERLAY_SOURCE, seed_app / OVERLAY_RELATIVE)
        if file_sha(seed_app / OVERLAY_RELATIVE) != R1_OVERLAY_AFTER_SHA256:
            raise RuntimeError("R2_OVERLAY_SHA_MISMATCH")
        for relative in sorted(EXPECTED_R1_REUSE_PATHS):
            shutil.copy2(R1_APP / relative, seed_app / relative)
        for relative in EXPECTED_R1_REUSE_PATHS:
            if file_sha(seed_app / relative) != r1_entries[relative]["after_sha256"]:
                raise RuntimeError("R2_REUSED_BUILD_OUTPUT_SHA_MISMATCH:" + relative)

        candidate_inventory = inventory_tree(seed_app)
        base_by = {str(row["path"]): row for row in active["inventory"]}
        after_by = {str(row["path"]): row for row in candidate_inventory}
        removed = sorted(set(base_by) - set(after_by))
        if removed:
            raise RuntimeError("ACTIVE_ASSET_REMOVED:" + ",".join(removed[:8]))
        changed = sorted(path for path in base_by.keys() | after_by.keys()
                         if base_by.get(path) != after_by.get(path))
        expected_paths = set(RUNTIME_PATCH_PATHS) | {OVERLAY_RELATIVE} | EXPECTED_R1_REUSE_PATHS
        if set(changed) != expected_paths:
            raise RuntimeError("R2_RUNTIME_DELTA_SCOPE_MISMATCH:" + json.dumps(
                {"changed": changed, "expected": sorted(expected_paths)}, ensure_ascii=False))
        delta_receipt, explicit_untracked = create_delta_receipt(active, seed_app, r1_entries, reuse_record)
        write_json_exclusive(R2_DELTA_PATH, delta_receipt)

        # Recheck the current pointer before sealing. The standard integration
        # validator still hashes the full inventories and all delta bytes; only
        # the known, exact 66 MB overlay diff rendering is reused from r1.
        active_again, plist_again, config_path_again, config_raw_again, _ = ensure_active_identity()
        if (_base_binding(active_again) != _base_binding(active)
                or plist_again != original_plist_raw or config_path_again != active_config_path
                or config_raw_again != active_config_raw):
            raise RuntimeError("ACTIVE_POINTER_OR_CONFIG_CHANGED_DURING_PREPARATION")
        CANDIDATE.mkdir(mode=0o755, exist_ok=False)
        with reuse_exact_overlay_diff_proof(
            R1_OVERLAY_BEFORE_SHA256, R1_OVERLAY_AFTER_SHA256,
            str(r1_entries[OVERLAY_RELATIVE]["unified_diff_sha256"]),
            int(r1_entries[OVERLAY_RELATIVE]["unified_diff_hunk_count"]),
        ):
            integration = build_integrated_app(
                active_api_plist_path=PLIST, source_root=seed_app,
                candidate_root=CANDIDATE, delta_receipt_path=R2_DELTA_PATH,
                explicit_untracked_paths=sorted(explicit_untracked), role="gateway", base_role="gateway")

    candidate_app = CANDIDATE / "app"
    final_inventory = inventory_tree(candidate_app)
    if final_inventory != candidate_inventory:
        raise RuntimeError("INTEGRATED_CANDIDATE_DIFFERS_FROM_SEALED_SEED")
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
        "source_workspace_full_tree_copied": False, "api_integration_delta_receipt": str(R2_DELTA_PATH),
        "r1_reused_build_receipt_sha256": reuse_record["r1_delta_receipt_sha256"]}
    manifest["verification_gaps"] = [
        "Independent fresh-base r2 review pending",
        "Candidate is not activated; live API/UI and natural-slot behavior are unverified",
        "Research-only limits remain: independent facts NOT_RUN, prediction UNTESTED, historical PIT NOT_VALIDATED",
    ]
    manifest_path = CANDIDATE / "release-manifest.json"
    write_json_exclusive(manifest_path, manifest)
    manifest_sha = file_sha(manifest_path)

    new_config = deepcopy(active_config)
    new_config["relation_root"] = str(candidate_app)
    if {key: value for key, value in new_config.items() if key != "relation_root"} != {
            key: value for key, value in active_config.items() if key != "relation_root"}:
        raise RuntimeError("CONFIG_NON_RELATION_SEMANTICS_CHANGED")
    write_json_exclusive(NEW_CONFIG, new_config)
    os.chmod(NEW_CONFIG, active_config_mode)
    new_config_sha = file_sha(NEW_CONFIG)

    original_plist = plistlib.loads(original_plist_raw)
    staged = rewrite_api_only_plist(original_plist,
        candidate_app_root=candidate_app, release_id=CANDIDATE.name,
        manifest_path=manifest_path, manifest_sha256=manifest_sha, candidate_manager_state_root=None)
    staged_env = staged.setdefault("EnvironmentVariables", {})
    staged_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"] = str(NEW_CONFIG)
    staged["ProgramArguments"] = [
        "V4_MANAGER_WORKBENCH_CONFIG_PATH=" + str(NEW_CONFIG)
        if isinstance(arg, str) and arg.startswith("V4_MANAGER_WORKBENCH_CONFIG_PATH=") else arg
        for arg in staged["ProgramArguments"]]
    plist_validation = validate_staged_plist(original_plist, staged, app_root=candidate_app,
        manifest_path=manifest_path, manifest_sha=manifest_sha, config_path=NEW_CONFIG)

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
    if file_sha(rollback_plist) != EXPECTED_ACTIVE_PLIST_SHA256 or rollback_plist.read_bytes() != original_plist_raw:
        raise RuntimeError("R2_ROLLBACK_PREIMAGE_MISMATCH")

    active_config_parsed = json.loads(active_config_raw)
    if {key: value for key, value in json.loads(NEW_CONFIG.read_text()).items() if key != "relation_root"} != {
            key: value for key, value in active_config_parsed.items() if key != "relation_root"}:
        raise RuntimeError("R2_CONFIG_NON_RELATION_FIELDS_CHANGED")
    api_test = run_candidate_api_check(candidate_app, NEW_CONFIG)
    with reuse_exact_overlay_diff_proof(
        R1_OVERLAY_BEFORE_SHA256, R1_OVERLAY_AFTER_SHA256,
        str(r1_entries[OVERLAY_RELATIVE]["unified_diff_sha256"]),
        int(r1_entries[OVERLAY_RELATIVE]["unified_diff_hunk_count"]),
    ):
        candidate_verification = verify_api_release_candidate(
            candidate_root=CANDIDATE, active_api_plist_path=PLIST,
            expected_manifest_sha256=manifest_sha, active_pointer="base", role="gateway", base_role="gateway")

    final_active, final_plist_raw, final_config_path, final_config_raw, _ = ensure_active_identity()
    if (_base_binding(final_active) != _base_binding(active)
            or final_plist_raw != original_plist_raw
            or final_config_path != active_config_path
            or final_config_raw != active_config_raw):
        raise RuntimeError("ACTIVE_POINTER_OR_CONFIG_CHANGED_AFTER_PREPARATION")

    plan: dict[str, object] = {
        "schema_version": "v4.mapping700_runtime_preparation_receipt.r2",
        "status": "PREPARED_NOT_ACTIVATED", "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False, "prepare_command": "PYTHONPATH=. .venv/bin/python docs/handoffs/us_hk_700_supplement_20261016/prepare_runtime_candidate_r2.py",
        "active_plist_path": str(PLIST), "active_plist_sha256": EXPECTED_ACTIVE_PLIST_SHA256,
        "active_plist_bytes": len(original_plist_raw), "active_plist_mode": oct(plist_mode),
        "active_release_id": final_active["release_id"], "active_release_root": final_active["release_root"],
        "active_manifest_sha256": final_active["release_manifest_sha256"],
        "active_application_inventory_sha256": final_active["application_inventory_sha256"],
        "active_application_inventory_entry_count": len(final_active["inventory"]),
        "active_config_path": str(active_config_path), "active_config_sha256": EXPECTED_ACTIVE_CONFIG_SHA256,
        "active_relation_root": active_config["relation_root"],
        "new_config_path": str(NEW_CONFIG), "new_config_sha256": new_config_sha,
        "new_relation_root": str(candidate_app), "new_config_mode": oct(active_config_mode),
        "candidate_root": str(CANDIDATE), "candidate_app_root": str(candidate_app),
        "candidate_release_id": CANDIDATE.name, "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": manifest_sha,
        "staged_plist_path": str(staged_plist), "staged_plist_sha256": file_sha(staged_plist),
        "rollback_plist_path": str(rollback_plist), "rollback_plist_sha256": file_sha(rollback_plist),
        "shared_release_lock_path": str(api_release_lock_path(PLIST, role="gateway")),
        "runtime_delta_receipt_path": str(R2_DELTA_PATH),
        "runtime_delta_receipt_sha256": file_sha(R2_DELTA_PATH),
        "candidate_verification": candidate_verification,
        "candidate_api_test": api_test,
        "delta_paths": changed, "non_delta_entry_count": integration["non_delta_entry_count"],
        "non_delta_inventory_sha256": integration["non_delta_inventory_sha256"],
        "r1_reuse_evidence": reuse_record,
        "staged_plist_validation": plist_validation,
        "r1_prior_candidate_root": str(R1_ROOT), "r1_prior_candidate_manifest_sha256": R1_MANIFEST_SHA256,
        "r1_preserved": True,
        "activation_gate": "NOT_EXECUTED: no activation authorization in this PREPARE_R2 task; any later activation needs a fresh R2-bound independent review and explicit root authorization.",
        "rollback_preimage_identity": {"path": str(rollback_plist), "sha256": file_sha(rollback_plist),
                                        "byte_identical_to_active_plist": rollback_plist.read_bytes() == original_plist_raw},
        "baseline_build": {"status": "REUSED_R1_REVIEWED_BUILD", "baseline_rebuilt": False,
                           "reason": "Manager-selection source/build inputs and base outputs match R1 exactly; current web differences are limited to the recorded research-lane/main entrypoints."},
    }
    write_json_exclusive(candidate_config_dir / "cutover-plan.json", plan)
    write_json_exclusive(R2_PREP_PATH, plan)
    report = render_report(plan, delta_receipt, reuse_record, plist_validation, final_active)
    with R2_REPORT_PATH.open("x", encoding="utf-8") as handle:
        handle.write(report)
    print(json.dumps({"status": plan["status"], "candidate_root": str(CANDIDATE),
        "candidate_manifest_sha256": manifest_sha, "new_config_sha256": new_config_sha,
        "delta_paths": changed, "non_delta_entry_count": integration["non_delta_entry_count"],
        "active_plist_sha256": EXPECTED_ACTIVE_PLIST_SHA256,
        "api_test_status": api_test["status"]}, ensure_ascii=False, indent=2))


def render_report(plan: dict[str, object], delta: dict[str, object],
                  reuse: dict[str, object], plist_validation: dict[str, object],
                  active: dict[str, object]) -> str:
    manifest_rows = []
    active_inv = {str(row["path"]): row for row in active["inventory"]}
    candidate_inv = {str(row["path"]): row for row in inventory_tree(CANDIDATE / "app")}
    for entry in delta["entries"]:
        rel = str(entry["path"])
        before = active_inv.get(rel)
        after = candidate_inv[rel]
        before_sha = str(entry["before_sha256"] or "ADDED")
        mode_before = f"{int(before['mode']):04o}" if before else "—"
        manifest_rows.append(
            f"| `{rel}` | `{before_sha}` | `{entry['after_sha256']}` | "
            f"{before['size'] if before else '—'} → {after['size']} | {mode_before} → {int(after['mode']):04o} |"
        )
    api_summary = plan["candidate_api_test"]["summary"]
    base_root = plan["active_release_root"]
    return f"""# Runtime candidate R2 preparation receipt

Status: **PREPARED_NOT_ACTIVATED**. The R2 candidate was prepared from the fresh plist-selected ZSXQ release and remains separate from the preserved R1 candidate. The active plist, active config, active release, services, scheduled tasks, and production permissions were not changed. No `launchctl` command ran.

## Fresh active identity and configuration

- Active plist: `{plan['active_plist_path']}`, SHA256 `{plan['active_plist_sha256']}` ({plan['active_plist_bytes']} bytes, mode {plan['active_plist_mode']}).
- Active release: `{plan['active_release_id']}` at `{base_root}`, manifest SHA256 `{plan['active_manifest_sha256']}`; full application inventory SHA256 `{plan['active_application_inventory_sha256']}` with {plan['active_application_inventory_entry_count']} entries.
- Active config: `{plan['active_config_path']}`, SHA256 `{plan['active_config_sha256']}`. Its existing `relation_root` is `{plan['active_relation_root']}`; the new config changes only `relation_root` to the R2 app root.
- R2 candidate: `{plan['candidate_root']}`, manifest SHA256 `{plan['candidate_manifest_sha256']}`.
- R1 evidence remains at `{plan['r1_prior_candidate_root']}` with candidate manifest SHA256 `{plan['r1_prior_candidate_manifest_sha256']}`.

## Exact runtime delta

The R2 integration contains six declared paths. Each before/after hash, size, and mode is shown below. The other {plan['non_delta_entry_count']} active app entries were verified byte-identical; their inventory SHA256 is `{plan['non_delta_inventory_sha256']}`.

| Path | Active SHA256 | R2 SHA256 | Size bytes | Mode |
|---|---|---|---:|---|
{chr(10).join(manifest_rows)}

## Reused R1 source/build evidence

- R1 delta receipt SHA256: `{reuse['r1_delta_receipt_sha256']}`; R1 candidate manifest SHA256: `{reuse['r1_candidate_manifest_sha256']}`; R1 independent review file SHA256: `{reuse['r1_review']['sha256']}`.
- R2 active module, Workbench, types, overlay, and manager-selection HTML preimages match the R1 base SHA256 values exactly. `git apply --check` passed against the actual R2 base.
- The manager-selection build inputs (`package.json`, lockfile, Vite config, TypeScript config) and baseline manager-selection entry/assets match R1. The only web-tree differences are the seven separately preserved research-lane/main paths recorded in the R2 preparation receipt, so R1's reviewed manager-selection JS/index outputs were reused by exact SHA256. No Vite or Vue typecheck was rerun.
- The 66,687,594-byte overlay's R1 unified-diff proof was reused only after exact before/after content SHA256 checks. The R2 base and candidate inventories, each changed file's before/after SHA256, and all non-delta entries were freshly recomputed. The standard API-release candidate verifier passed with a local fast path that reused this one exact prior proof; the general release helper was not modified.
- Targeted candidate API check: {api_summary['status']}; {api_summary['membership_count']} stocks / {api_summary['relation_count']} relations; {api_summary['source_reviewed_relations']} source-reviewed / {api_summary['unprocessed_relations']} unprocessed / {api_summary['independently_verified_relations']} independently verified; `{api_summary['exact_reviewed_rid']}` and `{api_summary['exact_unprocessed_rid']}`. The test used the R2 app as import root and the R2 config path.

## Staged config and rollback identity

- New config: `{plan['new_config_path']}`, SHA256 `{plan['new_config_sha256']}`, mode `{plan['new_config_mode']}`. All values except `relation_root` match the active config.
- Staged plist: `{plan['staged_plist_path']}`, SHA256 `{plan['staged_plist_sha256']}`. It changes only release/config selectors and working directory; launch label, port, KeepAlive, RunAtLoad, other environment entries, and non-selector arguments remain unchanged. Verified changed selector keys: `{', '.join(plist_validation['changed_environment_keys'])}`.
- Rollback preimage: `{plan['rollback_plist_path']}`, SHA256 `{plan['rollback_plist_sha256']}`, byte-identical to the current active plist.
- Fresh pointer/config checks passed before candidate integration and after candidate verification. The new candidate is not activated.

## Commands and verification

- Prepare: `PYTHONPATH=. .venv/bin/python docs/handoffs/us_hk_700_supplement_20261016/prepare_runtime_candidate_r2.py`.
- Candidate API checker: `{plan['candidate_api_test']['command']}`; working directory `{plan['candidate_api_test']['working_directory']}`.
- Candidate verification: `verify_api_release_candidate` returned `PASS` with exact R2 base identity, six deltas, and full non-delta inventory proof; the large overlay unified-diff calculation was reused only for the matching content SHA pair.
- No activation, API switch, commit, or push was performed.

`CANNOT_CONFIRM`: live API/UI behavior under the R2 candidate, natural-time results, independent semantic facts, prediction, historical PIT, and a future R2 activation/rollback. A fresh independent R2 review is pending.
"""


if __name__ == "__main__":
    main()
