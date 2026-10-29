#!/usr/bin/env python3
"""Build and verify the one nonactive API release for the numeric-283 panel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import sys
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/INTEGRATION_CONTRACT.json")
CONTRACT_ROOT = CONTRACT_PATH.parent
WORKTREE = Path("/Users/lexi/Desktop/学习/因子工厂/research/daily_numeric283_panel_integration_20261029_r1/worktree")
HANDOFF = WORKTREE / "docs/handoffs/daily_numeric283_20261029"
PREPARED = CONTRACT_ROOT / "prepared/daily_numeric283_20261029_r2"
CONTROL = CONTRACT_ROOT / "control/r2"
RELEASE_ID = "v4-daily-numeric283-20261029-r2-api"
RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases") / RELEASE_ID
EXPECTED_CONTRACT_SHA = "be5a3e6dd28661c2c27622e7d96d0012fb280bbb49cb753578cb72e5336f9839"
EXPECTED_API_MANIFEST_SHA = "73bacffcb0ee2d11b63c7661ae51f0130573d717bae88de5362385f457b0ed78"
EXPECTED_API_PLIST_SHA = "52bd9a958a4b24bc423e296cde0e23d09edf0ce2dbcad12d86818f71310e35e4"
EXPECTED_INTEGRATION_HELPER_SHA = "35ac1a9b6f3ea885b2788a9476dbc2f4dc21f42f43a359b63a0c22265c1fd154"
EXPECTED_CUTOVER_HELPER_SHA = "d7c0891357c34e5e43b1c6d6584f5210d3a1ede41b600a20fce6c798b183da87"
EXPECTED_BASE_STATIC_SHA = "73410703548f29fdfad2d7a3d1fd7bde21b79f3c44d6933def01d5b1836cc516"
EXPECTED_EXTERNAL_CONTRACT_SHA = "a785856ccacb0fb238d780a1bc0f1ceacfaf9b477f7661d86c7d5d4e3898e048"
BUILDER_RELATIVE_PATH = "ops/prepare_daily_numeric283_static.py"
EXPECTED_MANIFEST_FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
EXPECTED_PLIST_FLAGS = {
    "RESEARCH_ONLY": "1",
    "PRODUCTION_ALLOWED": "false",
    "BUY_GATE_UPDATED": "false",
    "ORDERS_SENT": "false",
}
PLIST_ENV_CHANGES = {
    "V4_APP_ROOT",
    "V4_RELEASE_ID",
    "V4_RELEASE_MANIFEST_PATH",
    "V4_RELEASE_MANIFEST_SHA256",
    "PYTHONPATH",
    "V4_RESEARCH_PANEL_ROOT",
    "V4_RESEARCH_PANEL_ASSET_MANIFEST",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def must_pin(path: Path, expected: str, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label}: expected regular file at {path}")
    raw = path.read_bytes()
    actual = sha(raw)
    if actual != expected:
        raise RuntimeError(f"{label}: SHA drift expected={expected} actual={actual}")
    return raw


def write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def save_json_exclusive(path: Path, value: Any) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_exclusive(path, raw)
    return raw


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guard_contract_roles(contract: dict[str, Any]) -> tuple[Path, dict[str, Any], bytes]:
    if contract.get("schema") != "V4_ORIGINAL_DAILY_NUMERIC283_INTEGRATION_V1_R3":
        raise RuntimeError("contract schema is not R3")
    if contract.get("candidate_identity") != RELEASE_ID:
        raise RuntimeError("nonactive candidate identity changed")
    packaging = contract.get("packaging_compatibility", {})
    if (
        packaging.get("new_app_entry_count") != 1343
        or packaging.get("old_app_entries_preserved") != 1342
        or packaging.get("new_app_entry") != BUILDER_RELATIVE_PATH
    ):
        raise RuntimeError("R3 one-real-builder packaging exception changed")
    for role in contract["role_bindings"]:
        plist_path = Path(role["plist"])
        manifest_path = Path(role["manifest"])
        must_pin(plist_path, role["plist_sha256"], f"role plist {role['label']}")
        must_pin(manifest_path, role["manifest_sha256"], f"role manifest {role['label']}")

    api_role = next(role for role in contract["role_bindings"] if role["label"] == "com.lexi.v4.api")
    api_root = Path(contract["live_api_root"])
    if api_root != RELEASE_ROOT.parent / "v4-a-share-empty-state-20261029-r1-api":
        raise RuntimeError("frozen live API root changed")
    if api_role["plist_sha256"] != EXPECTED_API_PLIST_SHA or api_role["manifest_sha256"] != EXPECTED_API_MANIFEST_SHA:
        raise RuntimeError("R3 API identity pins changed")
    api_manifest_raw = must_pin(api_root / "release-manifest.json", EXPECTED_API_MANIFEST_SHA, "active API manifest")
    api_manifest = json.loads(api_manifest_raw)
    if api_manifest.get("schema_version") != "v4.release_candidate.v1":
        raise RuntimeError("active API release manifest schema changed")
    if api_manifest.get("candidate", {}).get("release_id") != api_root.name:
        raise RuntimeError("active API release id changed")
    if api_manifest.get("application_inventory", {}).get("entry_count") != 1342:
        raise RuntimeError("active API app entry count is not 1342")
    if {key: api_manifest.get(key) for key in EXPECTED_MANIFEST_FLAGS} != EXPECTED_MANIFEST_FLAGS:
        raise RuntimeError("active API manifest safety flags changed")

    external = api_manifest.get("external_module_contract")
    if not isinstance(external, dict) or external.get("sha256") != EXPECTED_EXTERNAL_CONTRACT_SHA:
        raise RuntimeError("active external module contract binding changed")
    external_path = Path(external["path"])
    if external_path != api_root / "api_module_contracts.current-v4.json":
        raise RuntimeError("active external module contract path changed")
    external_raw = must_pin(external_path, EXPECTED_EXTERNAL_CONTRACT_SHA, "external API module contract")
    external_value = json.loads(external_raw)
    if external_value.get("schema_version") != "v4.api_module_contracts.v1":
        raise RuntimeError("external module contract schema changed")
    if external_value.get("roles", {}).get("gateway", {}).get("label") != "com.lexi.v4.api":
        raise RuntimeError("external gateway role binding changed")

    helper_path = api_root / "app/ops/api_release_integration.py"
    cutover_path = api_root / "app/ops/prepare_api_only_cutover.py"
    must_pin(helper_path, EXPECTED_INTEGRATION_HELPER_SHA, "active API integration helper")
    must_pin(cutover_path, EXPECTED_CUTOVER_HELPER_SHA, "active API cutover helper")
    api_plist_path = Path(api_role["plist"])
    plist_raw = must_pin(api_plist_path, EXPECTED_API_PLIST_SHA, "active API plist")
    plist_value = plistlib.loads(plist_raw)
    if plist_value.get("Label") != "com.lexi.v4.api" or plist_value.get("WorkingDirectory") != str(api_root / "app"):
        raise RuntimeError("active API plist identity changed")
    env = plist_value.get("EnvironmentVariables")
    if not isinstance(env, dict) or {key: env.get(key) for key in EXPECTED_PLIST_FLAGS} != EXPECTED_PLIST_FLAGS:
        raise RuntimeError("active API plist safety flags changed")
    if env.get("V4_APP_ROOT") != str(api_root / "app") or env.get("V4_RELEASE_ID") != api_root.name:
        raise RuntimeError("active API plist app identity changed")
    if env.get("V4_RELEASE_MANIFEST_PATH") != str(api_root / "release-manifest.json") or env.get("V4_RELEASE_MANIFEST_SHA256") != EXPECTED_API_MANIFEST_SHA:
        raise RuntimeError("active API plist manifest binding changed")
    if env.get("V4_RESEARCH_PANEL_ROOT") != contract["static_root"] or env.get("V4_RESEARCH_PANEL_ASSET_MANIFEST") != contract["static_manifest"]:
        raise RuntimeError("active API static-root binding changed")

    static_manifest_raw = must_pin(Path(contract["static_manifest"]), EXPECTED_BASE_STATIC_SHA, "base static manifest")
    if contract.get("static_asset_count") != 452:
        raise RuntimeError("base static asset count changed")
    return api_root, api_manifest, external_raw


def load_static_preparation(contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    receipt_path = PREPARED / "STATIC_CANDIDATE_RECEIPT.json"
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    if receipt.get("status") != "PREPARED_STATIC_DELTA" or receipt.get("task_scope_contract_sha256") != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("static preparation receipt is missing or stale")
    if receipt.get("output_dir") != str(PREPARED):
        raise RuntimeError("static preparation output path changed")
    if receipt.get("base_static_manifest_sha256") != EXPECTED_BASE_STATIC_SHA or receipt.get("candidate_asset_count") != 454:
        raise RuntimeError("static delta identity changed")
    if receipt.get("unchanged_existing_asset_count") != 451 or receipt.get("changed_existing_assets") != ["daily.html"]:
        raise RuntimeError("static preservation scope changed")
    if receipt.get("added_assets") != ["numeric283-panel.js", "numeric283-candidates.json"]:
        raise RuntimeError("static additions changed")
    static_manifest_path = PREPARED / "research-panel-assets.numeric283.json"
    static_manifest_raw = must_pin(static_manifest_path, receipt["candidate_static_manifest_sha256"], "prepared static manifest")
    static_manifest = json.loads(static_manifest_raw)
    if len(static_manifest.get("files", [])) != 454:
        raise RuntimeError("prepared static manifest count mismatch")
    must_pin(PREPARED / "daily.html.prepared", receipt["daily_html_after_sha256"], "prepared daily.html")
    must_pin(HANDOFF / "numeric283-panel.js", receipt["js_sha256"], "panel JS source")
    must_pin(PREPARED / "numeric283-candidates.json", receipt["json_sha256"], "prepared candidate JSON")
    builder_path = WORKTREE / BUILDER_RELATIVE_PATH
    must_pin(builder_path, receipt["static_builder_source_sha256"], "static builder source")
    return receipt, static_manifest, static_manifest_raw


def copy_static_assets(contract: dict[str, Any], static_manifest: dict[str, Any], static_manifest_raw: bytes, receipt: dict[str, Any]) -> None:
    source_root = Path(contract["static_root"])
    target_root = RELEASE_ROOT / "research-panel"
    target_root.mkdir(parents=True, exist_ok=False)
    for entry in static_manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe static asset path: {relative}")
        if str(relative) == "daily.html":
            source = PREPARED / "daily.html.prepared"
            expected = receipt["daily_html_after_sha256"]
        elif str(relative) == "numeric283-panel.js":
            source = HANDOFF / "numeric283-panel.js"
            expected = receipt["js_sha256"]
        elif str(relative) == "numeric283-candidates.json":
            source = PREPARED / "numeric283-candidates.json"
            expected = receipt["json_sha256"]
        else:
            source = source_root / relative
            expected = entry["sha256"]
        if sha(source.read_bytes()) != expected or entry["sha256"] != expected:
            raise RuntimeError(f"static source drift: {relative}")
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for entry in static_manifest["files"]:
        target = target_root / entry["path"]
        if not target.is_file() or target.is_symlink() or sha(target.read_bytes()) != entry["sha256"]:
            raise RuntimeError(f"static candidate asset verification failed: {entry['path']}")
    if sum(1 for item in target_root.rglob("*") if item.is_file()) != 454:
        raise RuntimeError("static candidate file count is not 454")
    write_exclusive(RELEASE_ROOT / "research-panel-assets.json", static_manifest_raw)


def prepare_api_plists(
    *, api_plist_path: Path,
    before_raw: bytes,
    candidate_manifest_sha: str,
    shared_lock_path: Path,
    preparer: Any,
) -> tuple[bytes, dict[str, Any]]:
    before = plistlib.loads(before_raw)
    if preparer.extract_environment(before).get("RESEARCH_ONLY") != "1":
        raise RuntimeError("cutover helper did not identify research-only environment")
    before_env = before.get("EnvironmentVariables")
    if not isinstance(before_env, dict) or not PLIST_ENV_CHANGES <= before_env.keys():
        raise RuntimeError("current plist does not contain all seven known identity/static keys")
    new_env = dict(before_env)
    app_root = RELEASE_ROOT / "app"
    new_env.update({
        "V4_APP_ROOT": str(app_root),
        "V4_RELEASE_ID": RELEASE_ID,
        "V4_RELEASE_MANIFEST_PATH": str(RELEASE_ROOT / "release-manifest.json"),
        "V4_RELEASE_MANIFEST_SHA256": candidate_manifest_sha,
        "PYTHONPATH": f"{app_root / 'upstreams'}:{app_root}",
        "V4_RESEARCH_PANEL_ROOT": str(RELEASE_ROOT / "research-panel"),
        "V4_RESEARCH_PANEL_ASSET_MANIFEST": str(RELEASE_ROOT / "research-panel-assets.json"),
    })
    after = dict(before)
    after["EnvironmentVariables"] = new_env
    after["WorkingDirectory"] = str(app_root)
    changed_top_level = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    changed_env = sorted(key for key in set(before_env) | set(new_env) if before_env.get(key) != new_env.get(key))
    if changed_top_level != ["EnvironmentVariables", "WorkingDirectory"] or set(changed_env) != PLIST_ENV_CHANGES:
        raise RuntimeError(f"unexpected staged plist delta: top={changed_top_level}, env={changed_env}")
    if after.get("ProgramArguments") != before.get("ProgramArguments"):
        raise RuntimeError("ProgramArguments must remain byte-semantically unchanged")
    if {key: new_env.get(key) for key in EXPECTED_PLIST_FLAGS} != EXPECTED_PLIST_FLAGS:
        raise RuntimeError("staged plist safety flags changed")
    after_raw = plistlib.dumps(after, fmt=plistlib.FMT_XML, sort_keys=True)
    parsed_after = plistlib.loads(after_raw)
    if parsed_after != after:
        raise RuntimeError("staged API plist failed parse/readback")
    receipt = {
        "status": "PREPARED_NOT_ACTIVATED",
        "source_plist_path": str(api_plist_path),
        "source_plist_sha256": sha(before_raw),
        "candidate_plist_path": str(CONTROL / "api.after.plist"),
        "candidate_plist_sha256": sha(after_raw),
        "changed_top_level_keys": changed_top_level,
        "changed_environment_keys": changed_env,
        "ProgramArguments_unchanged": True,
        "safety_flags": {key: new_env.get(key) for key in EXPECTED_PLIST_FLAGS},
        "active_plist_changed": False,
        "launchctl_called": False,
        "shared_release_lock_acquired": False,
        "shared_release_lock_path": str(shared_lock_path),
    }
    return after_raw, receipt


def build_candidate(contract: dict[str, Any], api_root: Path, api_manifest: dict[str, Any], external_raw: bytes) -> dict[str, Any]:
    api_role = next(role for role in contract["role_bindings"] if role["label"] == "com.lexi.v4.api")
    api_plist_path = Path(api_role["plist"])
    integration_path = api_root / "app/ops/api_release_integration.py"
    cutover_path = api_root / "app/ops/prepare_api_only_cutover.py"
    preparer = load_module(cutover_path, "daily283_current_cutover_prepare")
    preparer.assert_safe_candidate_path(RELEASE_ROOT, source_root=WORKTREE)
    integration = load_module(integration_path, "daily283_current_api_integration")
    external_path = Path(api_manifest["external_module_contract"]["path"])
    integration.MODULE_CONTRACT_PATH = external_path

    active = integration.read_active_release(api_plist_path, role="gateway")
    if active["release_root"] != str(api_root) or active["release_manifest_sha256"] != EXPECTED_API_MANIFEST_SHA:
        raise RuntimeError("current API owner/release drift before candidate creation")
    if active["application_inventory_entry_count"] != 1342:
        raise RuntimeError("current API helper does not see 1342 active entries")

    static_receipt, static_manifest, static_manifest_raw = load_static_preparation(contract)
    if RELEASE_ROOT.exists():
        raise FileExistsError(f"refusing existing release candidate: {RELEASE_ROOT}")
    control_files = [CONTROL / "api.before.plist", CONTROL / "api.after.plist", CONTROL / "API_CUTOVER_PREPARATION.json"]
    existing_controls = [str(path) for path in control_files if path.exists() or path.is_symlink()]
    if existing_controls:
        raise FileExistsError("refusing existing control outputs: " + ", ".join(existing_controls))

    delta_source = WORKTREE / BUILDER_RELATIVE_PATH
    delta_raw = must_pin(delta_source, static_receipt["static_builder_source_sha256"], "used static builder app delta")
    delta_sha = sha(delta_raw)
    delta_receipt = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(active),
        "entries": [{
            "path": BUILDER_RELATIVE_PATH,
            "before_sha256": None,
            "after_sha256": delta_sha,
            "unified_diff_sha256": None,
            "unified_diff_hunk_count": None,
        }],
    }
    delta_receipt_path = PREPARED / "API_DELTA_RECEIPT.json"
    write_exclusive(delta_receipt_path, (json.dumps(delta_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    RELEASE_ROOT.mkdir(parents=True, exist_ok=False)
    api_integration = integration.build_integrated_app(
        active_api_plist_path=api_plist_path,
        source_root=WORKTREE,
        candidate_root=RELEASE_ROOT,
        delta_receipt_path=delta_receipt_path,
        explicit_untracked_paths=[BUILDER_RELATIVE_PATH],
        role="gateway",
        base_role="gateway",
        bootstrap_transition=False,
    )
    if api_integration["non_delta_entry_count"] != 1342 or api_integration["delta_entries"][0]["path"] != BUILDER_RELATIVE_PATH:
        raise RuntimeError("API helper did not preserve 1342 prior entries with one builder delta")

    contract_copy = RELEASE_ROOT / "api_module_contracts.current-v4.json"
    write_exclusive(contract_copy, external_raw)
    copy_static_assets(contract, static_manifest, static_manifest_raw, static_receipt)

    candidate_app = RELEASE_ROOT / "app"
    inventory = integration.inventory_tree(candidate_app)
    if len(inventory) != 1343:
        raise RuntimeError(f"candidate API inventory count is {len(inventory)}, expected 1343")
    inventory_sha = integration.inventory_digest(inventory)
    active_external = api_manifest["external_module_contract"]
    candidate_external = dict(active_external)
    candidate_external["path"] = str(contract_copy)
    candidate_manifest = dict(api_manifest)
    candidate_manifest["candidate"] = {
        **api_manifest["candidate"],
        "root": str(RELEASE_ROOT),
        "app_root": str(candidate_app),
        "release_id": RELEASE_ID,
        "module_role": "gateway",
    }
    candidate_manifest["application_inventory"] = {
        "entries": inventory,
        "aggregate_sha256": inventory_sha,
        "entry_count": len(inventory),
    }
    candidate_manifest["app_files"] = [entry for entry in inventory if entry.get("kind") == "file"]
    candidate_manifest["symlinks"] = [entry for entry in inventory if entry.get("kind") == "symlink"]
    candidate_manifest["api_integration"] = api_integration
    candidate_manifest["external_module_contract"] = candidate_external
    candidate_manifest["research_panel"] = {
        "root": str(RELEASE_ROOT / "research-panel"),
        "asset_manifest": str(RELEASE_ROOT / "research-panel-assets.json"),
        "asset_manifest_sha256": sha(static_manifest_raw),
        "asset_count": 454,
        "base_asset_manifest_sha256": EXPECTED_BASE_STATIC_SHA,
        "non_delta_asset_count": 451,
        "non_delta_bytes_preserved": True,
        "numeric283_data_date": static_receipt["data_date"],
        "numeric283_observation_date": static_receipt["observation_date"],
        "numeric283_source_generation": static_receipt["source_generation"],
        "numeric283_scope_count": static_receipt["unique_count"],
    }
    release_manifest_raw = (json.dumps(candidate_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_exclusive(RELEASE_ROOT / "release-manifest.json", release_manifest_raw)
    manifest_sha = sha(release_manifest_raw)
    verification = integration.verify_api_release_candidate(
        candidate_root=RELEASE_ROOT,
        active_api_plist_path=api_plist_path,
        expected_manifest_sha256=manifest_sha,
    )
    candidate_identity = verification["candidate"]
    if verification.get("status") != "PASS" or candidate_identity.get("application_inventory_entry_count") != 1343:
        raise RuntimeError("real API release candidate verification failed")
    if verification.get("non_delta_entry_count") != 1342 or verification.get("delta_paths") != [BUILDER_RELATIVE_PATH]:
        raise RuntimeError("real API release verifier reported unexpected app delta")

    current_plist_raw = must_pin(api_plist_path, EXPECTED_API_PLIST_SHA, "active API plist immediately before staged plist")
    shared_lock_path = integration.api_release_lock_path(api_plist_path, role="gateway")
    after_plist_raw, cutover_receipt = prepare_api_plists(
        api_plist_path=api_plist_path,
        before_raw=current_plist_raw,
        candidate_manifest_sha=manifest_sha,
        shared_lock_path=shared_lock_path,
        preparer=preparer,
    )
    write_exclusive(CONTROL / "api.before.plist", current_plist_raw)
    write_exclusive(CONTROL / "api.after.plist", after_plist_raw)
    cutover_receipt.update({
        "candidate_release_root": str(RELEASE_ROOT),
        "candidate_release_manifest_sha256": manifest_sha,
        "candidate_api_verification_status": verification["status"],
        "candidate_application_inventory_entry_count": candidate_identity["application_inventory_entry_count"],
        "api_delta_paths": verification["delta_paths"],
        "non_delta_api_entries_preserved": verification["non_delta_entry_count"],
        "active_api_pid_or_service_state_verified": False,
        "activation_authorized_to_writer": False,
    })
    save_json_exclusive(CONTROL / "API_CUTOVER_PREPARATION.json", cutover_receipt)

    final_receipt = {
        "status": "PREPARED_NONACTIVE_RELEASE_VERIFIED",
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "candidate_builder_source_path": str(Path(__file__).resolve()),
        "candidate_builder_source_sha256": sha(Path(__file__).read_bytes()),
        "candidate_root": str(RELEASE_ROOT),
        "candidate_release_manifest_sha256": manifest_sha,
        "active_base_release": api_integration["base"],
        "active_base_manifest_sha256": EXPECTED_API_MANIFEST_SHA,
        "active_base_plist_sha256": EXPECTED_API_PLIST_SHA,
        "external_module_contract_sha256": EXPECTED_EXTERNAL_CONTRACT_SHA,
        "api_application_inventory_entry_count": candidate_identity["application_inventory_entry_count"],
        "old_api_entries_preserved": verification["non_delta_entry_count"],
        "api_delta_paths": verification["delta_paths"],
        "api_verification": verification,
        "static_asset_manifest_sha256": sha(static_manifest_raw),
        "static_asset_count": 454,
        "old_static_assets_preserved": 451,
        "static_delta": ["daily.html", "numeric283-panel.js", "numeric283-candidates.json"],
        "static_receipt_sha256": sha((PREPARED / "STATIC_CANDIDATE_RECEIPT.json").read_bytes()),
        "before_plist_sha256": sha(current_plist_raw),
        "after_plist_sha256": sha(after_plist_raw),
        "changed_plist_environment_keys": cutover_receipt["changed_environment_keys"],
        "ProgramArguments_unchanged": True,
        "safety_flags_preserved": True,
        "active_plist_changed": False,
        "launchctl_called": False,
        "live_http_or_browser_checked": False,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    save_json_exclusive(PREPARED / "API_RELEASE_PREPARATION_RECEIPT.json", final_receipt)
    return final_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not sys.dont_write_bytecode or not sys.flags.no_user_site:
        raise RuntimeError("run with the configured interpreter using -I -B")
    if args.output_dir.expanduser().resolve(strict=False) != RELEASE_ROOT.resolve(strict=False):
        raise RuntimeError("candidate output path differs from the frozen nonactive release root")
    contract_raw = must_pin(CONTRACT_PATH, EXPECTED_CONTRACT_SHA, "R3 integration contract")
    contract = json.loads(contract_raw)
    api_root, api_manifest, external_raw = guard_contract_roles(contract)
    if api_root != Path(contract["live_api_root"]):
        raise RuntimeError("current API root changed during the guard")
    receipt = build_candidate(contract, api_root, api_manifest, external_raw)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
