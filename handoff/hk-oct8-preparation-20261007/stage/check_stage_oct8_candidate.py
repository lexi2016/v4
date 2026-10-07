#!/usr/bin/env python3
"""Read-only pin verifier and --check runner for the Oct 8 Stage candidate."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import os.path
import pathlib
import plistlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PIN_PATH = HERE / "stage_oct8_candidate_pin_20261007.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory_digest(entries: list[dict]) -> str:
    data = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def actual_app_paths(app: pathlib.Path) -> set[str]:
    found: set[str] = set()
    for base, dirs, files in os.walk(app, followlinks=False):
        base_path = pathlib.Path(base)
        for name in list(dirs):
            candidate = base_path / name
            if candidate.is_symlink():
                found.add(candidate.relative_to(app).as_posix())
                dirs.remove(name)
        for name in files:
            found.add((base_path / name).relative_to(app).as_posix())
    return found


def verify_candidate() -> dict:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    candidate = pin["candidate"]
    root = pathlib.Path(candidate["release_root"])
    app = pathlib.Path(candidate["app_root"])
    manifest_path = root / "release-manifest.json"
    config_path = app / "stage_center_tick_config.json"
    plist_path = root / "config/com.lexi.stage-center.scheduler.plist"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    plist = plistlib.loads(plist_path.read_bytes())
    env = plist.get("EnvironmentVariables", {})
    old_r3_root = pathlib.Path(pin["old_r3_preimage"]["release_root"])
    old_r3_manifest_path = old_r3_root / "release-manifest.json"
    old_r3_manifest = json.loads(old_r3_manifest_path.read_text(encoding="utf-8"))
    live_stage = pin["current_live_stage_preimage"]
    live_plist_path = pathlib.Path(live_stage["plist_path"])
    live_plist = plistlib.loads(live_plist_path.read_bytes())
    live_env = live_plist.get("EnvironmentVariables", {})

    assert sha256(manifest_path) == pin["release_manifest"]["sha256"]
    assert sha256(config_path) == pin["config"]["sha256"]
    assert sha256(plist_path) == pin["packaged_plist"]["sha256"]
    assert sha256(old_r3_manifest_path) == pin["old_r3_preimage"]["release_manifest_sha256"]
    assert old_r3_manifest["application_inventory"]["aggregate_sha256"] == pin["old_r3_preimage"]["application_inventory_sha256"]
    assert sha256(live_plist_path) == live_stage["plist_sha256"]
    assert live_plist["Label"] == live_stage["label"]
    assert live_env.get("V35_RELEASE_ID") == live_stage["release_id"]
    assert live_env.get("V35_RELEASE_MANIFEST_SHA256") == live_stage["release_manifest_sha256"]
    assert live_env.get("V35_RELEASE_MANIFEST_PATH") == str(old_r3_manifest_path)
    assert manifest["candidate"]["release_id"] == candidate["release_id"]
    assert manifest["candidate"]["release_root"] == str(root)
    assert manifest["candidate"]["app_root"] == str(app)
    assert manifest["candidate"]["service_activated"] is False
    assert manifest["activation_status"] == "NOT_ACTIVATED"
    assert manifest["deployment_status"] == "NOT_DEPLOYED"
    assert config["release_id"] == candidate["release_id"]
    assert config["shared_data_root"] == pin["config"]["shared_data_root"]
    assert config["safety"] == {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    assert manifest["stage_service"]["current_source_config_identity"]["release_id"] == config["release_id"]
    assert manifest["stage_service"]["current_source_config_identity"]["shared_data_root"] == config["shared_data_root"]

    entries = manifest["application_inventory"]["entries"]
    inventory = pin["application_inventory"]
    assert len(entries) == inventory["entry_count"] == 918
    assert sum(item.get("kind") == "symlink" for item in entries) == inventory["symlink_count"] == 2
    assert inventory_digest(entries) == inventory["aggregate_sha256"] == pin["application_inventory"]["aggregate_sha256"]
    expected_paths = {item["path"] for item in entries}
    assert actual_app_paths(app) == expected_paths
    for item in entries:
        path = app / item["path"]
        if item.get("kind") == "symlink":
            assert path.is_symlink() and os.readlink(path) == item["target"], item["path"]
        else:
            assert path.is_file() and not path.is_symlink(), item["path"]
            assert path.stat().st_size == item["size"], item["path"]
            assert format(path.stat().st_mode & 0o7777, "04o") == item["mode"], item["path"]
            assert sha256(path) == item["sha256"], item["path"]

    closure = manifest["stage_runtime_dependency_closure"]
    assert len(closure) == len(pin["runtime_dependency_closure"]) == 18
    active_root = old_r3_root / "app"
    closure_by_path = {item["path"]: item for item in closure}
    for row in pin["runtime_dependency_closure"]:
        path = row["path"]
        assert path in closure_by_path
        assert sha256(app / path) == row["candidate_after_sha256"]
        assert closure_by_path[path]["candidate_sha256"] == row["candidate_after_sha256"]
        assert sha256(active_root / path) == row["old_r3_preimage_sha256"]
        assert closure_by_path[path]["active_r3_sha256"] == row["old_r3_preimage_sha256"]

    config_entry = next(item for item in entries if item["path"] == "stage_center_tick_config.json")
    config_closure = next(item for item in closure if item["path"] == "stage_center_tick_config.json")
    overlay_config = next(item for item in manifest["source"]["stage_overlay"]["entries"] if item["path"] == "stage_center_tick_config.json")
    assert config_entry["sha256"] == pin["config"]["sha256"] == config_closure["candidate_sha256"] == overlay_config["candidate_sha256"]

    expected_args = [config["python_path"], "-B", str(app / "ops/run_stage_center_nodes.py"), "--config", str(config_path)]
    assert plist["ProgramArguments"] == expected_args
    assert plist["WorkingDirectory"] == str(app)
    assert plist.get("RunAtLoad") is False
    assert plist["Label"] == pin["packaged_plist"]["label"]
    assert env.get("V35_RELEASE_ID") == candidate["release_id"]
    assert env.get("V35_RELEASE_MANIFEST_PATH") == str(manifest_path)
    assert env.get("V35_RELEASE_MANIFEST_SHA256") == sha256(manifest_path)
    assert env.get("STAGE_CENTER_CONFIG") == str(config_path)
    assert env.get("PYTHONPATH") == os.pathsep.join((str(app / "upstreams"), str(app)))
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert str(env.get(key, "")).lower() == "false", key

    assert pin["input_gate"]["state"] == "CANNOT_CONFIRM"
    assert pin["input_gate"]["artifact_present"] is True
    assert pin["input_gate"]["fallback_allowed"] is False
    assert pin["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "provider_invoked": False,
        "stage_nodes_executed": False,
        "service_activated": False,
    }
    return {
        "status": "PIN_CHECK_OK",
        "release_id": candidate["release_id"],
        "release_manifest_sha256": sha256(manifest_path),
        "config_sha256": sha256(config_path),
        "packaged_plist_sha256": sha256(plist_path),
        "application_inventory_count": len(entries),
        "application_inventory_sha256": inventory_digest(entries),
        "runtime_dependency_closure_count": len(closure),
        "symlink_count": inventory["symlink_count"],
        "target_input_state": pin["input_gate"]["state"],
        "fallback_allowed": pin["input_gate"]["fallback_allowed"],
        "safety": pin["safety"],
    }


def run_read_only_check(summary: dict) -> dict:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    app = pathlib.Path(pin["candidate"]["app_root"])
    config = app / "stage_center_tick_config.json"
    python = pathlib.Path(pin["runtime_python"]["executable"])
    command = [str(python), "-B", str(app / "ops/run_stage_center_nodes.py"), "--config", str(config), "--check"]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(app / "upstreams"), str(app)))
    for key in ("V4_STAGE_TRACE_PATH", "V4_STAGE_CANARY_ROOT", "V4_STAGE_PARENT_START_NS"):
        env.pop(key, None)
    completed = subprocess.run(command, cwd=app, env=env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"candidate --check failed ({completed.returncode}): {completed.stderr[-1200:]}")
    result = json.loads(completed.stdout)
    if result.get("status") != "CHECK_OK":
        raise RuntimeError(f"candidate --check returned {result.get('status')!r}")
    if any(result.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise RuntimeError("candidate --check safety flags changed")
    if result.get("config") != str(config):
        raise RuntimeError("candidate --check loaded a different config path")
    if result.get("end_to_end_deadline", {}).get("business_write_may_have_occurred") is not False:
        raise RuntimeError("candidate --check did not prove no business write")
    return {
        **summary,
        "check_status": result["status"],
        "node_count": len(result.get("node_ids", [])),
        "node_ids": result.get("node_ids", []),
        "production_allowed": result.get("production_allowed"),
        "buy_gate_updated": result.get("buy_gate_updated"),
        "orders_sent": result.get("orders_sent"),
        "natural_verified": result.get("end_to_end_deadline", {}).get("natural_verified"),
        "business_write_may_have_occurred": result.get("end_to_end_deadline", {}).get("business_write_may_have_occurred"),
        "command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify pins and invoke the candidate's read-only --check")
    parser.add_argument("--verify-only", action="store_true", help="verify pins without invoking the candidate")
    args = parser.parse_args()
    if args.check and args.verify_only:
        parser.error("choose --check or --verify-only")
    summary = verify_candidate()
    if args.check:
        summary = run_read_only_check(summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "PIN_CHECK_FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
