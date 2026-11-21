"""Freeze the serially integrated isolated runtime candidate and four controls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess


TASK = Path(__file__).resolve().parent
BASE_TASK = TASK.parents[1] / "v4_main_r4_review_remediation_20261121" / "runtime"
BASE = BASE_TASK / "v4-main-r4-review-remediation-20261121"
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
REVIEW = TASK.parent / "private" / "ISOLATED_API_PIN_SOURCE_REVIEW.json"
LIVE_MAIN_PLIST = TASK.parent / "private" / "current_preimage" / "main.plist"
OLD_API = TASK.parents[1] / "v4_main_autorun_r4_release_readiness_20261121" / "private" / "bundle" / "preimages" / "api-current.plist"
PYCACHE = "/dev/null/v4-main-r4-source-only-pycache"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_mode(path: Path) -> str:
    return format(path.stat().st_mode & 0o777, "04o")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def candidate_python() -> Path:
    return RUNTIME / "venvs/v4-mac/bin/python"


def candidate_call(code: str, *args: str) -> str:
    env = dict(os.environ)
    env.update(PYTHONPATH=str(APP), PYTHONPYCACHEPREFIX=PYCACHE,
               PYTHONDONTWRITEBYTECODE="1", V4_SOURCE_ONLY_PYCACHE_REQUIRED="1")
    command = [str(candidate_python()), "-X", f"pycache_prefix={PYCACHE}", "-B", "-S", "-c", code,
               *(str(arg) for arg in args)]
    result = subprocess.run(command, cwd=APP, env=env, capture_output=True,
                            text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError("CANDIDATE_PYTHON_COMMAND_FAILED:" + str(result.returncode) + ":" + result.stderr[-2000:])
    return result.stdout


def effective_external_bindings(plist: dict) -> dict:
    live = plistlib.loads(LIVE_MAIN_PLIST.read_bytes())
    live_env = live.get("EnvironmentVariables", {})
    env = plist.get("EnvironmentVariables", {})
    replacements = {}
    for name in ("V4_QFQ_CONVENTION_ACCEPTANCE_PATH", "V4_RESEARCH_PANEL_A_SYNC_SCRIPT"):
        old_path, new_path = env.get(name), live_env.get(name)
        if not isinstance(old_path, str) or not isinstance(new_path, str):
            raise RuntimeError("EFFECTIVE_EXTERNAL_BINDING_MISSING:" + name)
        old_file, new_file = Path(old_path), Path(new_path)
        old_hash, new_hash = sha(old_file), sha(new_file)
        if old_hash != new_hash:
            raise RuntimeError("EFFECTIVE_EXTERNAL_BINDING_BYTES_DRIFT:" + name)
        replacements[name] = {"old_path": old_path, "old_sha256": old_hash,
                              "effective_path": new_path, "effective_sha256": new_hash,
                              "path_changed": old_path != new_path}
        env[name] = new_path
    qfq_sha = live_env.get("V4_QFQ_CONVENTION_ACCEPTANCE_SHA256")
    if qfq_sha != replacements["V4_QFQ_CONVENTION_ACCEPTANCE_PATH"]["effective_sha256"]:
        raise RuntimeError("QFQ_CONVENTION_ENV_SHA_MISMATCH")
    plist["EnvironmentVariables"] = env
    return replacements


def validate_api_pin_and_all_sources(pins: dict) -> dict:
    code = r'''import json,sys
from ops.prepare_main_root_binding_candidate import _validate_source_binding_review,_verify_all_source_bindings
pins=json.loads(sys.argv[1])
review=sys.argv[2]
replacements,record=_validate_source_binding_review(pins,review)
rows=_verify_all_source_bindings(pins,replacements)
print(json.dumps({"replacement_count":len(replacements),"review_record":record,"verified_count":len(rows),"replacements":replacements},ensure_ascii=False,sort_keys=True))
'''
    result = json.loads(candidate_call(code, json.dumps(pins, ensure_ascii=False, separators=(",", ":")), str(REVIEW)))
    if result.get("replacement_count") != 1 or result.get("verified_count") != 95:
        raise RuntimeError("SOURCE_BINDING_REVIEW_OR_95_COUNT_MISMATCH")
    return result


def candidate_inventory() -> dict:
    code = r'''import json,sys
from pathlib import Path
from ops.api_release_integration import inventory_tree,inventory_digest
rows=inventory_tree(Path(sys.argv[1]))
print(json.dumps({"entries":rows,"entry_count":len(rows),"aggregate_sha256":inventory_digest(rows)},ensure_ascii=False,sort_keys=True))
'''
    value = json.loads(candidate_call(code, str(APP)))
    if not value.get("entries") or value["entry_count"] != len(value["entries"]):
        raise RuntimeError("CANDIDATE_APP_INVENTORY_INVALID")
    write_json(TASK / "CANDIDATE_APP_INVENTORY.json", value)
    return value


def main() -> None:
    if RELEASE.name != "v4-main-r4-incremental-closure-20261122":
        raise RuntimeError("RELEASE_ID_ROOT_BASENAME_MISMATCH")
    base_freeze = json.loads((BASE_TASK / "CANDIDATE_FREEZE_RECEIPT.json").read_bytes())
    rebase = json.loads((TASK / "RUNTIME_REBASE_RECEIPT.json").read_bytes())
    if (base_freeze.get("status") != "PASS_ISOLATED_CANDIDATE_CONTROLS"
            or rebase.get("status") != "PASS_COPIED_RUNTIME_REBASED_AND_FROZEN"
            or rebase.get("candidate_runtime") != str(RUNTIME)):
        raise RuntimeError("FROZEN_BASE_OR_REBASED_RUNTIME_REQUIRED")

    pins_path = RELEASE / "control/managed-pins.json"
    policy_path = RELEASE / "control/policy.json"
    manifest_path = RELEASE / "release-manifest.json"
    plist_path = RELEASE / "launchd.plist"
    # Always reassemble from the frozen R4 control preimage. A failed prior
    # attempt may have left a partial candidate control, never an input.
    pins = json.loads((BASE / "control/managed-pins.json").read_bytes())
    policy = json.loads((BASE / "control/policy.json").read_bytes())
    manifest = json.loads((BASE / "release-manifest.json").read_bytes())
    plist = plistlib.loads((BASE / "launchd.plist").read_bytes())

    reviewed = validate_api_pin_and_all_sources(pins)
    replacements = reviewed["replacements"]
    for row in pins.get("source_bindings", []):
        replacement = replacements.get(row.get("path"))
        if replacement:
            row["path"] = replacement["path"]
            row["sha256"] = replacement["sha256"]
    pins["expected_main_app_root"] = str(APP)
    if len(pins.get("source_bindings", [])) != 95:
        raise RuntimeError("SOURCE_BINDING_COUNT_NOT_95")
    # Validate all 95 rows in memory after the reviewed API replacement.
    post_code = r'''import json,sys
from ops.prepare_main_root_binding_candidate import _verify_all_source_bindings
pins=json.loads(sys.argv[1])
rows=_verify_all_source_bindings(pins,{})
print(json.dumps({"verified_count":len(rows),"rows":rows},ensure_ascii=False,sort_keys=True))
'''
    post = json.loads(candidate_call(post_code, json.dumps(pins, ensure_ascii=False, separators=(",", ":"))))
    if post.get("verified_count") != 95:
        raise RuntimeError("POST_REPLACEMENT_SOURCE_BINDINGS_NOT_95_95")

    active_env = effective_external_bindings(plist)
    app_inventory = candidate_inventory()
    write_json(pins_path, pins)
    policy["managed_pin_inventory"] = {"path": str(pins_path), "sha256": sha(pins_path)}
    write_json(policy_path, policy)

    old_release_id = manifest.get("release_id")
    manifest.update(app_root=str(APP), release_id=RELEASE.name, candidate_id=RELEASE.name,
                    candidate_status="ISOLATED_INCREMENTAL_CLOSURE_REVIEW",
                    activation_status="NOT_ACTIVATED", deployment_status="NOT_RUN")
    manifest["app_files"] = [{"path": row["path"], "sha256": row["sha256"], "size": row["size"]}
                             for row in app_inventory["entries"]]
    manifest["application_inventory"] = {
        "entries": app_inventory["entries"], "entry_count": app_inventory["entry_count"],
        "aggregate_sha256": app_inventory["aggregate_sha256"]}
    manifest["main_storage_binding"] = {
        "schema_version": "v4.main_storage_binding.v1", "app_root": str(APP),
        "policy_path": str(policy_path), "policy_sha256": sha(policy_path),
        "managed_pin_inventory_path": str(pins_path), "managed_pin_inventory_sha256": sha(pins_path)}
    readiness = manifest.setdefault("r4_release_readiness", {})
    readiness.update(candidate_runtime=str(RUNTIME),
                     final_runtime_inventory_sha256=rebase["final_runtime_inventory_sha256"],
                     runtime_rebase_receipt_sha256=sha(TASK / "RUNTIME_REBASE_RECEIPT.json"),
                     activation="NOT_RUN", natural_schedule="NOT_RUN")
    readiness["incremental_closure_source_binding_review_sha256"] = sha(REVIEW)
    readiness["incremental_closure_95_95_verified"] = True
    write_json(manifest_path, manifest)
    manifest_sha = sha(manifest_path)

    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments:
        raise RuntimeError("CANDIDATE_LAUNCHD_ARGUMENTS_INVALID")
    for index, item in enumerate(arguments):
        if isinstance(item, str) and item.endswith("/ops/launch_v4_macos_scheduler.sh"):
            arguments[index] = str(APP / "ops/launch_v4_macos_scheduler.sh")
            break
    else:
        raise RuntimeError("CANDIDATE_LAUNCHER_NOT_FOUND")
    plist["WorkingDirectory"] = str(APP)
    env = plist.setdefault("EnvironmentVariables", {})
    env.update(V4_APP_ROOT=str(APP), V4_RUNTIME_ROOT=str(RUNTIME), V4_RELEASE_ID=RELEASE.name,
               V4_RELEASE_MANIFEST_PATH=str(manifest_path), V4_RELEASE_MANIFEST_SHA256=manifest_sha,
               V4_RESEARCH_RETENTION_POLICY=str(policy_path),
               V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    plist["EnvironmentVariables"] = env
    plist_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True))

    binding_validation = json.loads(candidate_call(r'''import json,sys
from pathlib import Path
from ops.prepare_main_root_binding_candidate import validate_candidate_payload
print(json.dumps(validate_candidate_payload(config_dir=Path(sys.argv[1]),app_root=Path(sys.argv[2]),release_root=Path(sys.argv[3])),ensure_ascii=False,sort_keys=True))
''', str(RELEASE), str(APP), str(RELEASE)))
    if (binding_validation.get("status") != "PASS_MAIN_ROOT_BINDING_CHAIN"
            or binding_validation.get("app_inventory_sha256") != app_inventory["aggregate_sha256"]):
        raise RuntimeError("FINAL_MAIN_ROOT_BINDING_VALIDATION_FAILED")

    source_review = reviewed["review_record"]
    receipt = {
        "schema": "v4.r4_incremental_final_candidate_freeze.v1",
        "status": "PASS_ISOLATED_FINAL_CANDIDATE_FROZEN",
        "release_id": RELEASE.name, "release_root": str(RELEASE), "app_root": str(APP),
        "runtime_root": str(RUNTIME), "source_release_id": old_release_id,
        "base_release_manifest_sha256": sha(BASE / "release-manifest.json"),
        "source_binding_review": source_review,
        "source_bindings_verified_before_replacement": reviewed["verified_count"],
        "source_bindings_verified_after_replacement": post["verified_count"],
        "source_binding_replacements": [{"path": item["old_path"], "old_sha256": item["old_sha256"],
                                          "new_sha256": item["new_sha256"], "scope_id": item["scope_id"]}
                                         for item in source_review and json.loads(REVIEW.read_bytes())["replacements"]],
        "active_compatible_external_bindings": active_env,
        "application_inventory_sha256": app_inventory["aggregate_sha256"],
        "application_entry_count": app_inventory["entry_count"],
        "runtime_inventory_sha256": rebase["final_runtime_inventory_sha256"],
        "main_root_binding_validation": binding_validation,
        "controls": {"launchd_plist_sha256": sha(plist_path),
                     "release_manifest_sha256": manifest_sha,
                     "policy_sha256": sha(policy_path), "pins_sha256": sha(pins_path)},
        "deployment": "NOT_RUN", "scheduler_triggered": False,
        "production_write": False, "registry_or_CURRENT_mutated": False,
        "old_reservations_changed": False}
    write_json(TASK / "FINAL_CANDIDATE_FREEZE_RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
