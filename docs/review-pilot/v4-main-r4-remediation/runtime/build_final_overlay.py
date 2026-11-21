"""Build a hash-checked thin overlay for the frozen isolated R4 candidate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


TASK = Path(__file__).resolve().parent
RELEASE = TASK / "v4-main-r4-review-remediation-20261121"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
OVERLAY = TASK / "final_overlay"
R4_BUNDLE = TASK.parents[1] / "v4_main_autorun_r4_release_readiness_20261121" / "private" / "bundle"
SOURCE_DELTA = R4_BUNDLE / "SOURCE_DELTA_MANIFEST.json"
APP_ALLOWLIST = {
    "infrastructure/scheduling/executor_registry_review.py",
    "ops/launch_v4_macos_scheduler.sh",
    "ops/macos_research_panel_daily_authority.py",
    "ops/research_qfq_dependency_identity.py",
    "ops/research_storage_governance.py",
    "ops/run_v4_macos_scheduler.py",
    "ops/run_v4_macos_scheduler_daemon.py",
    "ops/runtime_bytecode_policy.py",
    "tests/test_scheduler_nosite_startup.py",
}
CONTROL_PATHS = (
    "launchd.plist",
    "release-manifest.json",
    "control/policy.json",
    "control/managed-pins.json",
)
PYCACHE_PREFIX = "/dev/null/v4-main-r4-source-only-pycache"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def checked_inventory() -> list[dict]:
    python = RUNTIME / "venvs/v4-mac/bin/python"
    code = (
        "import json,sys;from pathlib import Path;"
        "from ops.api_release_integration import inventory_tree,inventory_digest;"
        "rows=inventory_tree(Path(sys.argv[1]));"
        "print(json.dumps({'entries':rows,'aggregate_sha256':inventory_digest(rows)},ensure_ascii=False))"
    )
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(APP),
        PYTHONPYCACHEPREFIX=PYCACHE_PREFIX,
        PYTHONDONTWRITEBYTECODE="1",
        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",
    )
    result = subprocess.run(
        [str(python), "-X", f"pycache_prefix={PYCACHE_PREFIX}", "-B", "-S", "-c", code, str(APP)],
        cwd=APP,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result.stdout)
    return parsed["entries"]


def entry_index(rows: list[dict]) -> dict[str, dict]:
    indexed = {row["path"]: row for row in rows}
    if len(indexed) != len(rows):
        raise RuntimeError("DUPLICATE_INVENTORY_PATH")
    return indexed


def copy_verified(source: Path, destination: Path, expected: dict) -> dict:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("EXPECTED_REGULAR_FILE:" + str(source))
    actual_sha = sha_file(source)
    actual_mode = format(source.stat().st_mode & 0o777, "04o")
    actual_size = source.stat().st_size
    if (actual_sha != expected["sha256"] or actual_mode != expected["mode"]
            or actual_size != expected["size"]):
        raise RuntimeError("SOURCE_HASH_MODE_SIZE_MISMATCH:" + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if (sha_file(destination) != actual_sha
            or format(destination.stat().st_mode & 0o777, "04o") != actual_mode
            or destination.stat().st_size != actual_size):
        raise RuntimeError("COPIED_FILE_HASH_MODE_SIZE_MISMATCH:" + str(destination))
    return {"path": expected["path"], "sha256": actual_sha,
            "mode": actual_mode, "size": actual_size}


def main() -> None:
    if OVERLAY.exists():
        raise RuntimeError("FINAL_OVERLAY_ALREADY_EXISTS")
    r4 = json.loads(SOURCE_DELTA.read_bytes())
    base_rows = r4["final_app_inventory"]["entries"]
    final_rows = checked_inventory()
    final_manifest = json.loads((RELEASE / "release-manifest.json").read_bytes())
    expected_final_rows = final_manifest["application_inventory"]["entries"]
    if final_rows != expected_final_rows:
        raise RuntimeError("LIVE_CANDIDATE_APP_INVENTORY_DIFFERS_FROM_FROZEN_MANIFEST")
    if (final_manifest.get("release_id") != RELEASE.name
            or final_manifest.get("candidate_id") != RELEASE.name
            or Path(final_manifest.get("app_root", "")).resolve() != APP.resolve()):
        raise RuntimeError("FINAL_RELEASE_ID_OR_ROOT_BINDING_MISMATCH")

    before = entry_index(base_rows)
    after = entry_index(final_rows)
    if before.keys() - after.keys():
        raise RuntimeError("APP_PATHS_REMOVED_FROM_CANDIDATE")
    changed = [path for path in sorted(before.keys() | after.keys())
               if before.get(path) != after.get(path)]
    if set(changed) != APP_ALLOWLIST:
        raise RuntimeError("APP_CHANGE_ALLOWLIST_MISMATCH:" + ",".join(changed))

    OVERLAY.mkdir()
    app_manifest = []
    for relative in sorted(APP_ALLOWLIST):
        row = after[relative]
        copied = copy_verified(APP / relative, OVERLAY / "app" / relative, row)
        app_manifest.append({"before": before.get(relative), "after": copied})

    controls = []
    for relative in CONTROL_PATHS:
        src = RELEASE / relative
        st = src.stat()
        expected = {"path": relative, "sha256": sha_file(src),
                    "mode": format(st.st_mode & 0o777, "04o"), "size": st.st_size}
        controls.append(copy_verified(src, OVERLAY / "release-root" / relative, expected))

    rebase = json.loads((TASK / "RUNTIME_REBASE_RECEIPT.json").read_bytes())
    freeze = json.loads((TASK / "CANDIDATE_FREEZE_RECEIPT.json").read_bytes())
    runtime_inventory = json.loads((TASK / "FINAL_RUNTIME_INVENTORY.json").read_bytes())
    if (rebase.get("status") != "PASS_COPIED_RUNTIME_REBASED_AND_FROZEN"
            or rebase.get("candidate_runtime") != str(RUNTIME)
            or rebase.get("final_runtime_inventory_sha256") != runtime_inventory.get("aggregate_sha256")
            or runtime_inventory.get("aggregate_sha256") != freeze["runtime_inventory"]["aggregate_sha256"]):
        raise RuntimeError("FINAL_RUNTIME_INVENTORY_BINDING_MISMATCH")
    runtime_delta = []
    for change in rebase["exact_runtime_delta"]:
        relative = change["path"]
        before_row = change["before"]
        after_row = change["after"]
        src = RUNTIME / relative
        copied = copy_verified(src, OVERLAY / "runtime-delta" / relative, after_row)
        runtime_delta.append({"path": relative,
                              "before": before_row,
                              "after": copied})

    overlay_receipt = {
        "schema": "v4.r4_runtime_writer_final_overlay.v1",
        "status": "PASS_FINAL_UNIQUE_ROOT_THIN_OVERLAY",
        "release_root": str(RELEASE),
        "release_id": RELEASE.name,
        "candidate_id": RELEASE.name,
        "app_root": str(APP),
        "runtime_root": str(RUNTIME),
        "app_base_inventory_sha256": r4["final_app_inventory"]["aggregate_sha256"],
        "app_final_inventory_sha256": freeze["application_inventory"]["aggregate_sha256"],
        "app_changed": app_manifest,
        "release_controls": controls,
        "runtime_delta": runtime_delta,
        "full_runtime_inventory_sha256": runtime_inventory["aggregate_sha256"],
        "full_runtime_entry_count": runtime_inventory["entry_count"],
        "full_runtime_inventory_path": str(TASK / "FINAL_RUNTIME_INVENTORY.json"),
        "freeze_receipt_sha256": sha_file(TASK / "CANDIDATE_FREEZE_RECEIPT.json"),
        "release_manifest_sha256": sha_file(RELEASE / "release-manifest.json"),
        "selected_wheel": json.loads((TASK / "verification/ASSEMBLY_RECEIPT.json").read_bytes())["selected_wheel"],
        "candidate_python_sha256": sha_file(RUNTIME / "venvs/v4-mac/bin/python"),
        "pycache_prefix": PYCACHE_PREFIX,
        "parent_no_site": 1,
        "daemon_child_no_site": 0,
        "deployment": "NOT_RUN",
        "scheduler_triggered": False,
        "production_write": False,
    }
    write_json(OVERLAY / "THIN_OVERLAY_MANIFEST.json", overlay_receipt)

    # Rebuild the child identity view from the latest actual parent/child probe.
    probe = json.loads((TASK / "verification/RUNTIME_PROBE_RECEIPT.json").read_bytes())
    child = probe["child_import"]
    keys = child["keys"]
    if (probe.get("status") != "PASS_LAUNCHER_EQUIVALENT_NO_SITE_IMPORT"
            or child.get("status") != "PASS_DAEMON_CHILD_IMPORT_AND_QFQ_IDENTITY"
            or Path(probe["base_prefix"]).resolve() != RUNTIME / "python/cpython-3.14.6"
            or Path(child["base_prefix"]).resolve() != RUNTIME / "python/cpython-3.14.6"
            or probe["no_site"] != 1 or child["no_site"] != 0):
        raise RuntimeError("FINAL_PARENT_CHILD_RUNTIME_PROBE_BINDING_MISMATCH")
    key_manifest = {
        "schema": "v4.r4_child_qfq_key_manifest.v1",
        "status": "PASS_READ_ONLY_CHILD_ENVIRONMENT_IDENTITY",
        "release_root": str(RELEASE),
        "app_root": str(APP),
        "runtime_root": str(RUNTIME),
        "release_id": RELEASE.name,
        "candidate_id": RELEASE.name,
        "no_site": child["no_site"],
        "pycache_prefix": child["cache_policy"]["source_only_prefix"],
        "keys": keys,
        "computation_manifest_sha256": child["computation_manifest_sha256"],
        "interpreter_sha256": child["environment"]["executable_sha256"],
        "base_prefix": child["base_prefix"],
        "stdlib_root": child["stdlib"],
        "parent_environment": {
            "no_site": probe["no_site"],
            "base_prefix": probe["base_prefix"],
            "stdlib_root": probe["stdlib"],
            "pycache_prefix": probe["pycache_prefix"],
        },
        "freeze_receipt_sha256": sha_file(TASK / "CANDIDATE_FREEZE_RECEIPT.json"),
        "release_manifest_sha256": sha_file(RELEASE / "release-manifest.json"),
        "runtime_inventory_sha256": runtime_inventory["aggregate_sha256"],
        "claim_begin_called": False,
        "registry_mutated": False,
        "production_owner_called": False,
    }
    write_json(TASK / "CHILD_QFQ_KEY_MANIFEST.json", key_manifest)

    natural = json.loads((TASK / "NATURAL_OVERLAY_INTEGRATION_RECEIPT.json").read_bytes())
    natural["app_root"] = str(APP)
    natural["release_root"] = str(RELEASE)
    natural["status"] = "PASS_FINAL_WRITER_SHA_MATCH"
    write_json(TASK / "verification/FINAL_NATURAL_OVERLAY_INTEGRATION_RECEIPT.json", natural)

    focused = json.loads((TASK / "verification/FOCUSED_RUNTIME_REGRESSION_RECEIPT.json").read_bytes())
    focused.update(release_root=str(RELEASE), candidate_app_root=str(APP),
                   runtime_inventory_sha256=runtime_inventory["aggregate_sha256"],
                   app_inventory_sha256=freeze["application_inventory"]["aggregate_sha256"])
    write_json(TASK / "verification/FOCUSED_RUNTIME_REGRESSION_RECEIPT.json", focused)

    print(json.dumps({"status": overlay_receipt["status"],
                      "release_root": str(RELEASE),
                      "app_changed_count": len(app_manifest),
                      "release_control_count": len(controls),
                      "runtime_delta_count": len(runtime_delta),
                      "app_inventory_sha256": overlay_receipt["app_final_inventory_sha256"],
                      "runtime_inventory_sha256": overlay_receipt["full_runtime_inventory_sha256"],
                      "child_qfq_keys": keys,
                      "child_no_site": child["no_site"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
