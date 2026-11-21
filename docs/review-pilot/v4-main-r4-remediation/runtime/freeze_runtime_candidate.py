"""Freeze isolated Main controls around the runtime remediation candidate."""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent / "v4-main-r4-review-remediation-20261121"
APP = ROOT / "app"
RUNTIME = ROOT / "runtime"
CANDIDATE_ID = "v4-main-r4-review-remediation-20261121"
RELEASE_ID = ROOT.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def inventory_candidate_app() -> dict:
    python = RUNTIME / "venvs/v4-mac/bin/python"
    command = [
        str(python), "-X", "pycache_prefix=/dev/null/v4-main-r4-source-only-pycache", "-B", "-S", "-c",
        "import json,sys;from pathlib import Path;from ops.api_release_integration import inventory_tree,inventory_digest;"
        "rows=inventory_tree(Path(sys.argv[1]));"
        "print(json.dumps({'entries':rows,'aggregate_sha256':inventory_digest(rows)},ensure_ascii=False))",
        str(APP),
    ]
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(APP),
        PYTHONPYCACHEPREFIX="/dev/null/v4-main-r4-source-only-pycache",
        PYTHONDONTWRITEBYTECODE="1",
        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",
    )
    result = subprocess.run(command, cwd=APP, env=env, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    if not isinstance(value.get("entries"), list) or not value["entries"]:
        raise RuntimeError("CANDIDATE_APP_INVENTORY_EMPTY")
    return value


def main() -> None:
    pins_path = ROOT / "control/managed-pins.json"
    policy_path = ROOT / "control/policy.json"
    manifest_path = ROOT / "release-manifest.json"
    launchd_path = ROOT / "launchd.plist"
    runtime_receipt_path = Path(__file__).resolve().parent / "RUNTIME_REBASE_RECEIPT.json"
    runtime_inventory_path = Path(__file__).resolve().parent / "FINAL_RUNTIME_INVENTORY.json"
    runtime_receipt = json.loads(runtime_receipt_path.read_bytes())
    runtime_inventory = json.loads(runtime_inventory_path.read_bytes())
    if (runtime_receipt.get("status") != "PASS_COPIED_RUNTIME_REBASED_AND_FROZEN"
            or runtime_receipt.get("candidate_runtime") != str(RUNTIME)
            or runtime_receipt.get("final_runtime_inventory_sha256") != runtime_inventory.get("aggregate_sha256")):
        raise RuntimeError("FINAL_CANDIDATE_RUNTIME_NOT_FROZEN")

    pins = json.loads(pins_path.read_bytes())
    pins["expected_main_app_root"] = str(APP)
    write_json(pins_path, pins)

    policy = json.loads(policy_path.read_bytes())
    policy["managed_pin_inventory"] = {"path": str(pins_path), "sha256": digest(pins_path)}
    write_json(policy_path, policy)

    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(app_root=str(APP), release_id=RELEASE_ID, candidate_id=CANDIDATE_ID,
                    candidate_status="ISOLATED_REMEDIATION_REVIEW",
                    activation_status="NOT_ACTIVATED", deployment_status="NOT_RUN")
    inventory = inventory_candidate_app()
    manifest["application_inventory"] = {
        "entries": inventory["entries"],
        "entry_count": len(inventory["entries"]),
        "aggregate_sha256": inventory["aggregate_sha256"],
    }
    manifest["app_files"] = [
        {"path": row["path"], "sha256": row["sha256"], "size": row["size"]}
        for row in inventory["entries"]
    ]
    manifest["main_storage_binding"] = {
        "schema_version": "v4.main_storage_binding.v1",
        "app_root": str(APP),
        "policy_path": str(policy_path),
        "policy_sha256": digest(policy_path),
        "managed_pin_inventory_path": str(pins_path),
        "managed_pin_inventory_sha256": digest(pins_path),
    }
    readiness = manifest.setdefault("r4_release_readiness", {})
    readiness.update(
        candidate_runtime=str(RUNTIME),
        final_runtime_inventory_sha256=runtime_inventory["aggregate_sha256"],
        runtime_rebase_receipt_sha256=digest(runtime_receipt_path),
        activation="NOT_RUN",
        natural_schedule="NOT_RUN",
    )
    write_json(manifest_path, manifest)
    manifest_sha = digest(manifest_path)

    launchd = plistlib.loads(launchd_path.read_bytes())
    launchd["WorkingDirectory"] = str(APP)
    launchd["ProgramArguments"] = ["/bin/bash", str(APP / "ops/launch_v4_macos_scheduler.sh")]
    env = launchd["EnvironmentVariables"]
    env.update(
        V4_APP_ROOT=str(APP),
        V4_RUNTIME_ROOT=str(RUNTIME),
        V4_RELEASE_ID=RELEASE_ID,
        V4_RELEASE_MANIFEST_PATH=str(manifest_path),
        V4_RELEASE_MANIFEST_SHA256=manifest_sha,
        V4_RESEARCH_RETENTION_POLICY=str(policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=digest(policy_path),
    )
    launchd["EnvironmentVariables"] = env
    launchd_path.write_bytes(plistlib.dumps(launchd, sort_keys=True))

    receipt = {
        "schema": "v4.r4_remediation_candidate_freeze.v1",
        "status": "PASS_ISOLATED_CANDIDATE_CONTROLS",
        "release_root": str(ROOT),
        "app_root": str(APP),
        "runtime_root": str(RUNTIME),
        "release_id": RELEASE_ID,
        "candidate_id": CANDIDATE_ID,
        "no_site_parent": True,
        "daemon_child_no_site": 0,
        "controls": {
            "launchd_plist_sha256": digest(launchd_path),
            "release_manifest_sha256": manifest_sha,
            "retention_policy_sha256": digest(policy_path),
            "managed_pin_inventory_sha256": digest(pins_path),
        },
        "startup": {
            "launcher_sha256": digest(APP / "ops/launch_v4_macos_scheduler.sh"),
            "daemon_sha256": digest(APP / "ops/run_v4_macos_scheduler_daemon.py"),
            "scheduler_sha256": digest(APP / "ops/run_v4_macos_scheduler.py"),
            "cache_policy_sha256": digest(APP / "ops/runtime_bytecode_policy.py"),
            "qfq_identity_sha256": digest(APP / "ops/research_qfq_dependency_identity.py"),
            "pycache_prefix": "/dev/null/v4-main-r4-source-only-pycache",
        },
        "application_inventory": {
            "entry_count": len(inventory["entries"]),
            "aggregate_sha256": inventory["aggregate_sha256"],
        },
        "runtime_inventory": {
            "entry_count": runtime_inventory["entry_count"],
            "aggregate_sha256": runtime_inventory["aggregate_sha256"],
            "rebase_receipt_sha256": digest(runtime_receipt_path),
        },
        "deployment": "NOT_RUN",
        "scheduler_triggered": False,
        "production_write": False,
    }
    write_json(Path(__file__).resolve().parent / "CANDIDATE_FREEZE_RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
