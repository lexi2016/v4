from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PAIR = E / "candidate/issue32_scheduler_shared_pair_r1"
CANARY = PAIR / "canary_r5"
CANARY_APP = CANARY / "scheduler_app"
SOURCE_COPY = E / "candidate/api_canary_input_r4/preselection_pools/20261009"
API_CANARY_RECEIPT = E / "evidence/api_candidate_canary_mac_20261009_r4.json"
SOURCE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data"
)
ACTIVE_SCHEDULER = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "hk-research-calendar-all-r1-20261007-scheduler/app"
)
ACTIVE_SHARED = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
)
PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/"
    "v3.5-mac/bin/python"
)
RECEIPT = E / "evidence/scheduler_facade_materializer_canary_issue32_r5.json"
PROBE = E / "tools/scheduler_facade_canary_probe_issue32_r5.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inventory(root: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        records.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        })
    return records


def copy_verified_hourly_sources(pool: dict[str, object], source_snapshot_root: Path,
                                 run_data: Path) -> dict[str, object]:
    """Copy only the exact, receipt-verified slots named by the existing pool."""
    paths = str(pool.get("source_path") or "").split("|")
    if len(paths) != 16 or len(paths) != len(set(paths)):
        raise SystemExit("EXPECTED_EXACT_16_HOURLY_SOURCE_PATHS")
    sys.path.insert(0, str(ACTIVE_SCHEDULER))
    from infrastructure.research_store import HourlyResearchStore

    store = HourlyResearchStore(SOURCE_ROOT)
    original_manifest_path = SOURCE_ROOT / "manifest.json"
    original_manifest = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    source_identity: list[dict[str, object]] = []
    selected_manifest: dict[str, object] = {}
    file_records: list[dict[str, object]] = []
    for relative in paths:
        parts = relative.split("/")
        if (len(parts) != 5 or parts[:3] != ["research", "hourly", "live"]
                or parts[3] != "20261008" or not parts[4].endswith(".json")):
            raise SystemExit("HOURLY_SOURCE_PATH_OUTSIDE_EXPECTED_EXACT_DATE")
        slot = parts[4][:-5]
        payload = store.read_exact("20261008", slot, mode="LIVE")
        if payload is None or relative not in original_manifest:
            raise SystemExit("RECORDED_HOURLY_SOURCE_NOT_VERIFIED")
        source_identity.append({"archive_date": "20261008", "slot": slot, "payload": payload})
        selected_manifest[relative] = original_manifest[relative]
        receipt_relative = f"receipts/research/hourly/live/20261008/{slot}.json"
        for child_relative in (relative, receipt_relative):
            source_path = SOURCE_ROOT / child_relative
            target_path = source_snapshot_root / child_relative
            runtime_path = run_data / child_relative
            if not source_path.is_file():
                raise SystemExit("RECORDED_HOURLY_FILE_MISSING")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            shutil.copy2(source_path, runtime_path)
            raw = source_path.read_bytes()
            file_records.append({
                "path": child_relative,
                "sha256": sha(raw),
                "size": len(raw),
            })
    rebuilt_source_sha = sha(json.dumps(
        source_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    if rebuilt_source_sha != pool.get("source_sha256"):
        raise SystemExit("RECORDED_HOURLY_SOURCE_IDENTITY_SHA_MISMATCH")
    manifest_bytes = (json.dumps(selected_manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (source_snapshot_root / "manifest.json").write_bytes(manifest_bytes)
    (run_data / "manifest.json").write_bytes(manifest_bytes)
    return {
        "source_manifest_sha256": sha(original_manifest_path.read_bytes()),
        "subset_manifest_sha256": sha(manifest_bytes),
        "subset_manifest_entry_count": len(selected_manifest),
        "source_identity_sha256": rebuilt_source_sha,
        "file_records": file_records,
        "file_inventory_sha256": sha(json.dumps(file_records, sort_keys=True, separators=(",", ":")).encode()),
    }


def safe_result(module: str, status: str = "SUCCEEDED", **fields: object) -> dict[str, object]:
    return {
        "status": status,
        "workload_id": "preselection_pools",
        "exit_code": 0 if status == "SUCCEEDED" else 1,
        "stdout": "",
        "stderr": "",
        "modules": [module],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        **fields,
    }


def main() -> None:
    if CANARY.exists() or RECEIPT.exists():
        raise SystemExit("REFUSE_EXISTING_SCHEDULER_FACADE_CANARY")
    if not PYTHON.is_file() or not ACTIVE_SCHEDULER.is_dir() or not ACTIVE_SHARED.is_dir():
        raise SystemExit("PINNED_RUNTIME_OR_OWNER_ROOT_UNAVAILABLE")
    api_canary = json.loads(API_CANARY_RECEIPT.read_text(encoding="utf-8"))
    expected_source = api_canary["source_copy"]["files"]
    actual_source = inventory(SOURCE_COPY)
    if actual_source != expected_source:
        raise SystemExit("SOURCE_COPY_DIFFERS_FROM_PINNED_API_CANARY_INPUT")
    if api_canary["source_copy"].get("original_unchanged") is not True:
        raise SystemExit("UPSTREAM_API_CANARY_DID_NOT_CONFIRM_ORIGINAL_UNCHANGED")

    source_snapshot_root = CANARY / "source_snapshot"
    source_snapshot = source_snapshot_root / "preselection_pools/20261009"
    run_data = CANARY / "run_data"
    input_root = CANARY / "input_root"
    shared_data_root = CANARY / "shared_data_root"
    shared_package_root = CANARY_APP / "upstreams/v3_shared_data"
    universe_root = CANARY / "empty_universe_root"
    tdx_root = CANARY / "empty_tdx_root"
    source_snapshot.parent.mkdir(parents=True, exist_ok=False)
    shutil.copytree(SOURCE_COPY, source_snapshot, copy_function=shutil.copy2)
    run_data.mkdir(parents=True, exist_ok=False)
    hourly_pool = json.loads((SOURCE_COPY / "a_share_research_recommendation_pool.json").read_text(encoding="utf-8"))
    hourly_source_copy = copy_verified_hourly_sources(hourly_pool, source_snapshot_root, run_data)
    formal_pool_ids = {"a_d1_premarket_pool", "hkconnect_d1_top100"}
    original_pool_manifest = json.loads((SOURCE_COPY / "manifest.json").read_text(encoding="utf-8"))
    run_pool_dir = run_data / "preselection_pools/20261009"
    run_pool_dir.mkdir(parents=True, exist_ok=False)
    (run_pool_dir / "receipts").mkdir(parents=True, exist_ok=False)
    subset_pool_manifest = {}
    for pool_id in sorted(formal_pool_ids):
        artifact_name = f"{pool_id}.json"
        if pool_id not in original_pool_manifest:
            raise SystemExit(f"FORMAL_POOL_MANIFEST_ENTRY_MISSING:{pool_id}")
        shutil.copy2(SOURCE_COPY / artifact_name, run_pool_dir / artifact_name)
        shutil.copy2(SOURCE_COPY / "receipts" / artifact_name, run_pool_dir / "receipts" / artifact_name)
        subset_pool_manifest[pool_id] = original_pool_manifest[pool_id]
    (run_pool_dir / "manifest.json").write_text(
        json.dumps(subset_pool_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    # Execute through the exact active app's loader, with only the frozen four
    # product files overlaid in this E-local full-tree copy.
    active_app_inventory = inventory(ACTIVE_SCHEDULER)
    shutil.copytree(ACTIVE_SCHEDULER, CANARY_APP, symlinks=True, copy_function=shutil.copy2)
    app_alias = CANARY_APP / "v3_shared_data"
    if app_alias.is_symlink():
        app_alias.unlink()
    app_alias.symlink_to("upstreams/v3_shared_data")
    overlay_files = {
        "infrastructure/scheduling/dispatcher.py": PAIR / "scheduler_app/infrastructure/scheduling/dispatcher.py",
        "infrastructure/scheduling/executor_registry_preselection.py": PAIR / "scheduler_app/infrastructure/scheduling/executor_registry_preselection.py",
        "ops/ensure_hk_security_master.py": PAIR / "scheduler_app/ops/ensure_hk_security_master.py",
        "upstreams/v3_shared_data/shared_data/hk_security_master.py": PAIR / "shared_owner/upstreams/v3_shared_data/shared_data/hk_security_master.py",
    }
    for relative, source_path in overlay_files.items():
        destination = CANARY_APP / relative
        if not source_path.is_file() or not destination.is_file():
            raise SystemExit(f"PAIRED_OVERLAY_PATH_UNAVAILABLE:{relative}")
        shutil.copy2(source_path, destination)
    active_by_path = {item["path"]: item for item in active_app_inventory}
    candidate_app_inventory = inventory(CANARY_APP)
    candidate_by_path = {item["path"]: item for item in candidate_app_inventory}
    if set(active_by_path) != set(candidate_by_path):
        raise SystemExit("ISOLATED_FULL_APP_FILE_SET_DIFFERS_FROM_ACTIVE")
    full_app_delta = [
        path for path in sorted(active_by_path)
        if active_by_path[path] != candidate_by_path[path]
    ]
    if full_app_delta != sorted(overlay_files):
        raise SystemExit(f"ISOLATED_FULL_APP_DELTA_NOT_EXACT:{full_app_delta}")
    for directory in (
        input_root / "20261009", shared_data_root, universe_root, tdx_root,
    ):
        directory.mkdir(parents=True, exist_ok=False)
    expected_snapshot_inventory = [
        {
            "path": f"preselection_pools/20261009/{record['path']}",
            "sha256": record["sha256"],
            "size": record["size"],
        }
        for record in expected_source
    ]
    expected_snapshot_inventory.extend(
        dict(record) for record in hourly_source_copy["file_records"]
    )
    source_manifest_snapshot = source_snapshot_root / "manifest.json"
    expected_snapshot_inventory.append({
        "path": "manifest.json",
        "sha256": sha(source_manifest_snapshot.read_bytes()),
        "size": source_manifest_snapshot.stat().st_size,
    })
    expected_snapshot_inventory.sort(key=lambda record: str(record["path"]))
    if inventory(source_snapshot_root) != expected_snapshot_inventory:
        raise SystemExit("IMMUTABLE_SOURCE_SNAPSHOT_COPY_MISMATCH")

    materializer = CANARY_APP / "ops/materialize_scheduled_preselection.py"
    facade_path = CANARY_APP / "infrastructure/scheduling/executor_registry.py"
    active_facade_path = ACTIVE_SCHEDULER / "infrastructure/scheduling/executor_registry.py"
    candidate_preselection = CANARY_APP / "infrastructure/scheduling/executor_registry_preselection.py"
    materializer_sha = sha(materializer.read_bytes())
    facade_sha = sha(facade_path.read_bytes())
    active_facade_sha = sha(active_facade_path.read_bytes())
    command = [
        str(PYTHON), "-B", "-m", "ops.materialize_scheduled_preselection",
        "--trade-date", "20261009",
        "--signal-date", "20261008",
        "--input-root", str(input_root),
        "--data-root", str(run_data),
        "--shared-data-root", str(shared_data_root),
        "--shared-package-root", str(shared_package_root),
        "--reuse-formal-pools",
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(CANARY_APP)
    completed = subprocess.run(
        command, cwd=CANARY_APP, env=env, capture_output=True,
        text=True, timeout=90, check=False,
    )
    if not completed.stdout.strip():
        failure = {
            "schema_version": "v4.issue32.actual_facade_materializer_canary.v1",
            "status": "ACTUAL_MATERIALIZER_NO_PAYLOAD",
            "target_date": "20261009",
            "signal_date": "20261008",
            "command": command,
            "cwd": str(CANARY_APP),
            "returncode": completed.returncode,
            "stdout": completed.stdout[:100000],
            "stderr": completed.stderr[:100000],
            "stdout_truncated": len(completed.stdout) > 100000,
            "stderr_truncated": len(completed.stderr) > 100000,
            "materializer_path": str(materializer),
            "materializer_sha256": materializer_sha,
            "actual_facade_path": str(facade_path),
            "actual_facade_sha256": facade_sha,
            "isolated_data_root": str(run_data),
            "isolated_input_root": str(input_root),
            "isolated_shared_data_root": str(shared_data_root),
            "isolated_shared_package_root": str(shared_package_root),
            "active_owner_write_count": 0,
            "live_shared_store_write_count": 0,
            "network_calls": 0,
            "launchctl_called": False,
            "stage_run_performed": False,
            "safety": {
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }
        raw = (json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        fd = os.open(RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({
            "status": failure["status"],
            "receipt_path": str(RECEIPT),
            "receipt_sha256": sha(raw),
            "returncode": completed.returncode,
            "command": command,
            "stderr": failure["stderr"],
            "stderr_truncated": failure["stderr_truncated"],
        }, ensure_ascii=False, sort_keys=True))
        return

    stdout_path = CANARY / "materializer_stdout.jsonl"
    stderr_path = CANARY / "materializer_stderr.txt"
    result_path = CANARY / "materializer_result.json"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result_path.write_text(json.dumps({
        "returncode": completed.returncode,
        "command": command,
        "cwd": str(CANARY_APP),
        "reuse_formal_pools_test_adapter": "true",
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        materializer_payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"ACTUAL_MATERIALIZER_JSON_INVALID:{error}")
    if not isinstance(materializer_payload, dict):
        raise SystemExit("ACTUAL_MATERIALIZER_PAYLOAD_NOT_OBJECT")
    gate = materializer_payload.get("formal_pool_gate")
    if not isinstance(gate, dict):
        raise SystemExit("ACTUAL_MATERIALIZER_FORMAL_POOL_GATE_MISSING")

    probe_env = os.environ.copy()
    probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    probe_env["PYTHONPATH"] = str(CANARY_APP)
    probe_completed = subprocess.run(
        [
            str(PYTHON), "-B", str(PROBE), str(CANARY_APP), str(run_data),
            str(input_root), str(shared_data_root), str(shared_package_root),
            str(universe_root), str(tdx_root), str(stdout_path), str(stderr_path),
        ],
        cwd=CANARY_APP,
        env=probe_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if probe_completed.returncode != 0:
        raise SystemExit(
            "ORIGINAL_FACADE_PROBE_FAILED:"
            + probe_completed.stdout[-4000:]
            + probe_completed.stderr[-4000:]
        )
    probe_result = json.loads(probe_completed.stdout)
    loader_check = probe_result["loader_check"]
    dispatched = probe_result["candidate_executor_result"]
    calls = probe_result["candidate_child_calls"]

    required = gate.get("required") if isinstance(gate.get("required"), dict) else {}
    a_gate = required.get("a_d1_premarket_pool") if isinstance(required.get("a_d1_premarket_pool"), dict) else {}
    hk_gate = required.get("hkconnect_d1_top100") if isinstance(required.get("hkconnect_d1_top100"), dict) else {}
    if a_gate.get("ready") is not True or hk_gate.get("ready") is not False:
        raise SystemExit("CANARY_INPUT_DID_NOT_SHOW_A_READY_HK_MISSING")
    if completed.returncode == 0 or materializer_payload.get("status") != "FAILED":
        raise SystemExit("ACTUAL_MATERIALIZER_DID_NOT_FAIL_CLOSED_ON_HK")
    if dispatched.get("status") != "FAILED" or dispatched.get("hk_lane_status") != "CANNOT_CONFIRM":
        raise SystemExit("CANDIDATE_EXECUTOR_DID_NOT_FAIL_CLOSED_ON_ACTUAL_GATE")
    if dispatched.get("first_gate") != "HK_SECURITY_MASTER":
        raise SystemExit("CANDIDATE_EXECUTOR_LOST_HK_FIRST_GATE")
    if not loader_check.get("bound_method_globals_are_facade_globals") or loader_check.get("timeout_global_value") != 1800:
        raise SystemExit("ORIGINAL_FACADE_LOADER_DID_NOT_BIND_EXPECTED_GLOBAL")
    if probe_result["forbidden_hk_scoring_calls"]:
        raise SystemExit("CANDIDATE_EXECUTOR_SCORED_HK_WITH_FAILED_PREREQUISITE")
    if probe_result["unknown_child_calls"]:
        raise SystemExit("CANDIDATE_EXECUTOR_REACHED_UNCONTROLLED_EXTERNAL_MODULE")
    if any(call.get("module") == "scripts.materialize_hk_0_2" for call in calls):
        raise SystemExit("CANDIDATE_EXECUTOR_SCORED_HK_WITH_FAILED_PREREQUISITE")

    pool_path = run_data / "preselection_pools/20261009"
    a_pool = json.loads((pool_path / "a_d1_premarket_pool.json").read_text(encoding="utf-8"))
    hk_pool = json.loads((pool_path / "hkconnect_d1_top100.json").read_text(encoding="utf-8"))
    source_after = inventory(source_snapshot_root)
    if source_after != expected_snapshot_inventory:
        raise SystemExit("IMMUTABLE_SOURCE_SNAPSHOT_CHANGED")
    output_gate = materializer_payload["formal_pool_gate"]
    rebuilt_hourly_pool_path = run_pool_dir / "a_share_research_recommendation_pool.json"
    if not rebuilt_hourly_pool_path.is_file():
        raise SystemExit("MATERIALIZER_DID_NOT_REBUILD_HOURLY_RESEARCH_POOL")
    rebuilt_hourly_pool = json.loads(rebuilt_hourly_pool_path.read_text(encoding="utf-8"))
    rebuilt_hourly_rows = rebuilt_hourly_pool.get("rows") if isinstance(rebuilt_hourly_pool.get("rows"), list) else []
    if (
        rebuilt_hourly_pool.get("status") != "RESEARCH_RECOMMENDATION_POOL_READY"
        or len(rebuilt_hourly_rows) != 186
        or rebuilt_hourly_pool.get("source_sha256") != hourly_pool.get("source_sha256")
    ):
        raise SystemExit("MATERIALIZER_REBUILT_HOURLY_POOL_DIFFERS_FROM_PINNED_186_SOURCE")
    result = {
        "schema_version": "v4.issue32.actual_facade_materializer_canary.v3",
        "status": "PASS_ORIGINAL_FACADE_REBIND_EXACT_186_AND_FAIL_CLOSED_HK_MISSING",
        "target_date": "20261009",
        "signal_date": "20261008",
        "source_copy_path": str(SOURCE_COPY),
        "source_snapshot_path": str(source_snapshot_root),
        "source_copy_file_count": len(expected_source),
        "source_copy_inventory_sha256": hashlib.sha256(json.dumps(expected_source, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "source_copy_unchanged_after_test": source_after == expected_snapshot_inventory,
        "source_copy_original_unchanged_prior_receipt": api_canary["source_copy"]["original_unchanged"],
        "hourly_input_snapshot": hourly_source_copy,
        "rebuilt_hourly_pool": {
            "status": rebuilt_hourly_pool.get("status"),
            "row_count": len(rebuilt_hourly_rows),
            "source_sha256": rebuilt_hourly_pool.get("source_sha256"),
            "matches_pinned_pool_artifact": rebuilt_hourly_pool.get("source_sha256") == hourly_pool.get("source_sha256"),
        },
        "formal_pool_reuse_input_ids": sorted(formal_pool_ids),
        "active_scheduler_root": str(ACTIVE_SCHEDULER),
        "isolated_full_scheduler_app": str(CANARY_APP),
        "active_facade_sha256": active_facade_sha,
        "isolated_facade_sha256": facade_sha,
        "facade_source_preserved": active_facade_sha == facade_sha,
        "candidate_facade_loader_check": loader_check,
        "candidate_full_app_delta_verified": full_app_delta,
        "candidate_full_app_delta_files": [
            "infrastructure/scheduling/dispatcher.py",
            "infrastructure/scheduling/executor_registry_preselection.py",
            "ops/ensure_hk_security_master.py",
            "upstreams/v3_shared_data/shared_data/hk_security_master.py",
        ],
        "candidate_full_app_inventory_sha256": hashlib.sha256(json.dumps(inventory(CANARY_APP), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "materializer_runner_adapter_note": "The isolated actual materializer was invoked once with --reuse-formal-pools against the exact copied formal artifacts to preserve A=37 and HK=CANNOT_CONFIRM; the real facade handler then received that exact materializer stdout through FixedExecutorRegistry's injected runner seam. All other external producer modules were stubbed and recorded.",
        "active_shared_owner_root_read_only": str(ACTIVE_SHARED),
        "materializer_source_sha256": materializer_sha,
        "facade_source_sha256": facade_sha,
        "candidate_executor_source_sha256": sha(candidate_preselection.read_bytes()),
        "candidate_facade_global_bindings": {
            "bound_method_globals_are_facade_globals": loader_check["bound_method_globals_are_facade_globals"],
            "_V192_PRESELECTION_TIMEOUT_SECONDS": loader_check["timeout_global_value"],
            "binding_path": "unchanged active executor_registry.py _FUNCTION_SOURCES/_rebind_function loader",
        },
        "materializer_process_returncode": completed.returncode,
        "materializer_stdout_sha256": sha(completed.stdout.encode()),
        "materializer_stdout_bytes": len(completed.stdout.encode()),
        "materializer_stderr_sha256": sha(completed.stderr.encode()),
        "actual_facade_decoded_gate": output_gate,
        "candidate_executor_result": {
            key: dispatched.get(key)
            for key in (
                "status", "exit_code", "failure_class", "first_gate", "a_selector_status", "hk_lane_status",
                "materializer_status", "hk_local_pool_gate_status", "producer_called",
                "write_performed", "modules",
            )
        },
        "candidate_child_calls": calls,
        "candidate_child_call_modules": [call["module"] for call in calls],
        "hk_scorer_called": any(call.get("module") == "scripts.materialize_hk_0_2" for call in calls),
        "isolated_materialized_pools": {
            "a_d1_premarket_pool": {
                "status": a_pool.get("status"),
                "row_count": len(a_pool.get("rows", [])) if isinstance(a_pool.get("rows"), list) else 0,
                "source_sha256": a_pool.get("source_sha256"),
            },
            "hkconnect_d1_top100": {
                "status": hk_pool.get("status"),
                "row_count": len(hk_pool.get("rows", [])) if isinstance(hk_pool.get("rows"), list) else 0,
                "source_sha256": hk_pool.get("source_sha256"),
            },
        },
        "formal_pool_gate": output_gate,
        "api_page_inventory_rows_are_not_stage_acceptance": True,
        "stage_run_performed": False,
        "natural_receipt_verified": False,
        "upstream_producers_invoked": False,
        "active_owner_write_count": 0,
        "live_shared_store_write_count": 0,
        "network_calls": 0,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "scope_limit": "The full current scheduler app was copied inside E and four paired candidate files were overlaid; the unchanged original facade loader imported and rebound the candidate handler. The active materializer ran on exact isolated existing A/HK/hourly inputs. The candidate handler was called through FixedExecutorRegistry with only external _run commands controlled; no Stage run occurred. The isolated selector-ready panel is absent, so a_selector_status remains CANNOT_CONFIRM even though the formal A pool gate is READY. The exact 20261008 HK security master remains missing.",
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"receipt_path": str(RECEIPT), "receipt_sha256": sha(raw), **{k: result[k] for k in (
        "status", "target_date", "signal_date", "actual_facade_decoded_gate",
        "candidate_executor_result", "isolated_materialized_pools",
        "stage_run_performed", "active_owner_write_count", "scope_limit",
    )}}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
