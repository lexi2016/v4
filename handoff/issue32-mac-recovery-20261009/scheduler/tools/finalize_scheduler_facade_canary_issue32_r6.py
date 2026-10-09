from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PAIR = E / "candidate/issue32_scheduler_shared_pair_r1"
CANARY = PAIR / "canary_r5"
CANARY_APP = CANARY / "scheduler_app"
ACTIVE_SCHEDULER = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "hk-research-calendar-all-r1-20261007-scheduler/app"
)
API_CANARY_RECEIPT = E / "evidence/api_candidate_canary_mac_20261009_r4.json"
PAIR_RECEIPT = E / "writer/scheduler_shared_pair_candidate_r1.json"
PROBE = E / "tools/scheduler_facade_canary_probe_issue32_r6.py"
PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/"
    "v3.5-mac/bin/python"
)
RECEIPT = E / "evidence/scheduler_facade_materializer_canary_issue32_r6.json"
PROBE_STDOUT = E / "evidence/scheduler_facade_materializer_canary_issue32_r6_probe_stdout.json"
PROBE_STDERR = E / "evidence/scheduler_facade_materializer_canary_issue32_r6_probe_stderr.txt"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]


def write_exclusive(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return sha(raw)


def main() -> None:
    if any(path.exists() for path in (RECEIPT, PROBE_STDOUT, PROBE_STDERR)):
        raise SystemExit("REFUSE_EXISTING_R6_FINAL_RECEIPT")
    if not PYTHON.is_file() or not PROBE.is_file() or not CANARY_APP.is_dir():
        raise SystemExit("R6_PROBE_RUNTIME_OR_CANDIDATE_MISSING")

    api_canary = json.loads(API_CANARY_RECEIPT.read_text(encoding="utf-8"))
    pair_receipt = json.loads(PAIR_RECEIPT.read_text(encoding="utf-8"))
    source_artifact = CANARY / "source_snapshot/preselection_pools/20261009"
    run_data = CANARY / "run_data"
    input_root = CANARY / "input_root"
    shared_data_root = CANARY / "shared_data_root"
    shared_package_root = CANARY_APP / "upstreams/v3_shared_data"
    universe_root = CANARY / "empty_universe_root"
    tdx_root = CANARY / "empty_tdx_root"
    stdout_path = CANARY / "materializer_stdout.jsonl"
    stderr_path = CANARY / "materializer_stderr.txt"
    materializer_result_path = CANARY / "materializer_result.json"

    if api_canary.get("source_copy", {}).get("original_unchanged") is not True:
        raise SystemExit("API_CANARY_SOURCE_ORIGINAL_NOT_CONFIRMED_UNCHANGED")
    expected_source_files = api_canary["source_copy"]["files"]
    source_copy = E / "candidate/api_canary_input_r4/preselection_pools/20261009"
    actual_source_files = inventory(source_copy)
    if expected_source_files != actual_source_files:
        raise SystemExit("PINNED_API_CANARY_INPUT_CHANGED")

    materializer_stdout = stdout_path.read_text(encoding="utf-8")
    materializer_stderr = stderr_path.read_text(encoding="utf-8")
    materializer_payload = json.loads(materializer_stdout)
    materializer_result = json.loads(materializer_result_path.read_text(encoding="utf-8"))
    if materializer_result.get("returncode") != 1 or materializer_payload.get("status") != "FAILED":
        raise SystemExit("PINNED_MATERIALIZER_RESULT_NOT_FAIL_CLOSED")
    gate = materializer_payload.get("formal_pool_gate")
    required = gate.get("required") if isinstance(gate, dict) else None
    if not isinstance(required, dict):
        raise SystemExit("PINNED_FORMAL_GATE_MISSING")
    a_gate = required.get("a_d1_premarket_pool")
    hk_gate = required.get("hkconnect_d1_top100")
    if not (isinstance(a_gate, dict) and a_gate.get("ready") is True and a_gate.get("row_count") == 37):
        raise SystemExit("PINNED_A_POOL_GATE_NOT_READY_37")
    if not (isinstance(hk_gate, dict) and hk_gate.get("ready") is False and hk_gate.get("row_count") == 0):
        raise SystemExit("PINNED_HK_POOL_GATE_NOT_MISSING")

    pool_dir = run_data / "preselection_pools/20261009"
    a_pool = json.loads((pool_dir / "a_d1_premarket_pool.json").read_text(encoding="utf-8"))
    hk_pool = json.loads((pool_dir / "hkconnect_d1_top100.json").read_text(encoding="utf-8"))
    hourly_pool = json.loads((pool_dir / "a_share_research_recommendation_pool.json").read_text(encoding="utf-8"))
    if (a_pool.get("status"), len(a_pool.get("rows", []))) != ("V192_CANDIDATE_READY", 37):
        raise SystemExit("ISOLATED_A_FORMAL_POOL_CHANGED")
    if (hk_pool.get("status"), len(hk_pool.get("rows", []))) != ("CANNOT_CONFIRM", 0):
        raise SystemExit("ISOLATED_HK_FORMAL_POOL_CHANGED")
    if (
        hourly_pool.get("status") != "RESEARCH_RECOMMENDATION_POOL_READY"
        or len(hourly_pool.get("rows", [])) != 186
        or hourly_pool.get("source_sha256") != "f1c9c64d5d1c470bbfd82c2d70461cd64e411a77cffd206e870c6221c31a32ea"
    ):
        raise SystemExit("PINNED_186_HOURLY_POOL_CHANGED")

    # Verify the isolated hourly store contains exactly the source paths pinned
    # by the already-read research pool; no live source root is passed to probe.
    hourly_paths = hourly_pool.get("source_path", "").split("|")
    subset_manifest = json.loads((CANARY / "source_snapshot/manifest.json").read_text(encoding="utf-8"))
    if len(hourly_paths) != 16 or set(hourly_paths) != set(subset_manifest):
        raise SystemExit("EXACT_16_HOURLY_PATHS_NOT_PINNED_IN_SNAPSHOT")
    source_files = inventory(CANARY / "source_snapshot")
    expected_snapshot_count = 1 + 2 * len(hourly_paths) + len(expected_source_files)
    if len(source_files) != expected_snapshot_count:
        raise SystemExit("ISOLATED_SOURCE_SNAPSHOT_FILE_COUNT_CHANGED")

    active_inventory = inventory(ACTIVE_SCHEDULER)
    candidate_inventory = inventory(CANARY_APP)
    active_by_path = {item["path"]: item for item in active_inventory}
    candidate_by_path = {item["path"]: item for item in candidate_inventory}
    if set(active_by_path) != set(candidate_by_path):
        raise SystemExit("CANDIDATE_FULL_APP_PATH_SET_DIFFERS_FROM_ACTIVE")
    app_delta = [path for path in sorted(active_by_path) if active_by_path[path] != candidate_by_path[path]]
    expected_delta = sorted(
        ("upstreams/v3_shared_data/" + item["product_path"])
        if item.get("owner") == "actual_shared_owner"
        else item["product_path"]
        for item in pair_receipt["files"]
    )
    if app_delta != expected_delta:
        raise SystemExit("CANDIDATE_FULL_APP_DELTA_DIFFERS_FROM_FROZEN_PAIR")
    if pair_receipt.get("candidate_after_identities_match") is not True or pair_receipt.get("active_before_identities_match") is not True:
        raise SystemExit("FROZEN_PAIR_IDENTITY_RECEIPT_NOT_READY")

    command = [
        str(PYTHON), "-B", str(PROBE), str(CANARY_APP), str(run_data), str(input_root),
        str(shared_data_root), str(shared_package_root), str(universe_root), str(tdx_root),
        str(stdout_path), str(stderr_path),
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(CANARY_APP)
    env.pop("V35_HK_0_2_PYTHON", None)
    completed = subprocess.run(
        command, cwd=CANARY_APP, env=env, capture_output=True, text=True, timeout=60, check=False
    )
    PROBE_STDOUT.write_text(completed.stdout, encoding="utf-8")
    PROBE_STDERR.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise SystemExit("R6_ACTUAL_FACADE_PROBE_FAILED:" + completed.stderr[-4000:] + completed.stdout[-4000:])
    probe = json.loads(completed.stdout)
    loader = probe["loader_check"]
    result = probe["candidate_executor_result"]
    calls = probe["candidate_child_calls"]
    if not (
        loader.get("bound_method_code_resolves_to_candidate_handler") is True
        and loader.get("bound_method_globals_are_facade_globals") is True
        and loader.get("timeout_global_value") == 1800
    ):
        raise SystemExit("ACTUAL_FACADE_LOADER_BINDING_PROOF_FAILED")
    if not (
        result.get("status") == "FAILED"
        and result.get("a_selector_status") == "CANNOT_CONFIRM"
        and result.get("hk_lane_status") == "CANNOT_CONFIRM"
        and result.get("first_gate") == "HK_SECURITY_MASTER"
        and result.get("hk_local_pool_gate_status") == "CANNOT_CONFIRM"
    ):
        raise SystemExit("ACTUAL_FACADE_HANDLER_DID_NOT_REPORT_PRECISE_HK_BLOCKER")
    if probe.get("forbidden_hk_scoring_calls") or probe.get("unknown_child_calls"):
        raise SystemExit("UNCONTROLLED_OR_FORBIDDEN_CHILD_CALL_RECORDED")
    if not any(call.get("module") == "ops.materialize_scheduled_preselection" for call in calls):
        raise SystemExit("ACTUAL_FACADE_HANDLER_MATERIALIZER_PATH_NOT_INVOKED")

    result_receipt = {
        "schema_version": "v4.issue32.actual_facade_materializer_canary.v4",
        "status": "PASS_ACTUAL_FACADE_BINDING_AND_HK_MASTER_FAIL_CLOSED",
        "target_date": "20261009",
        "signal_date": "20261008",
        "candidate_full_app": str(CANARY_APP),
        "active_scheduler_root": str(ACTIVE_SCHEDULER),
        "candidate_full_app_delta": app_delta,
        "candidate_full_app_delta_sha256": sha(json.dumps(
            [{"path": item, "sha256": candidate_by_path[item]["sha256"]} for item in app_delta],
            sort_keys=True, separators=(",", ":"),
        ).encode()),
        "paired_candidate_manifest_sha256": pair_receipt["candidate_manifest_sha256"],
        "actual_facade_loader_check": loader,
        "actual_facade_handler_result": result,
        "actual_facade_child_calls": calls,
        "actual_facade_child_call_modules": [call.get("module") for call in calls],
        "hk_scorer_called": any(call.get("module") == "scripts.materialize_hk_0_2" for call in calls),
        "external_runner_controlled": probe.get("safe_external_runner_stubbed") is True,
        "materializer_reexecuted_for_r6": False,
        "reused_actual_materializer": {
            "path": str(materializer_result_path),
            "returncode": materializer_result["returncode"],
            "stdout_sha256": sha(materializer_stdout.encode()),
            "stderr_sha256": sha(materializer_stderr.encode()),
            "formal_pool_gate": gate,
        },
        "isolated_formal_pools": {
            "a_d1_premarket_pool": {
                "status": a_pool.get("status"),
                "row_count": len(a_pool.get("rows", [])),
                "source_sha256": a_pool.get("source_sha256"),
            },
            "hkconnect_d1_top100": {
                "status": hk_pool.get("status"),
                "row_count": len(hk_pool.get("rows", [])),
                "source_sha256": hk_pool.get("source_sha256"),
            },
            "a_share_research_recommendation_pool": {
                "status": hourly_pool.get("status"),
                "row_count": len(hourly_pool.get("rows", [])),
                "source_sha256": hourly_pool.get("source_sha256"),
            },
        },
        "hourly_source_snapshot": {
            "root": str(CANARY / "source_snapshot"),
            "exact_source_path_count": len(hourly_paths),
            "source_identity_sha256": hourly_pool.get("source_sha256"),
            "subset_manifest_sha256": sha((CANARY / "source_snapshot/manifest.json").read_bytes()),
            "file_count": len(source_files),
            "inventory_sha256": sha(json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode()),
            "no_live_source_root_passed_to_handler": True,
        },
        "input_snapshot": {
            "source_copy_root": str(source_copy),
            "source_copy_file_count": len(actual_source_files),
            "source_copy_inventory_sha256": sha(json.dumps(actual_source_files, sort_keys=True, separators=(",", ":")).encode()),
            "original_unchanged_from_api_canary_receipt": api_canary["source_copy"]["original_unchanged"],
        },
        "probe": {
            "path": str(PROBE),
            "sha256": sha(PROBE.read_bytes()),
            "command": command,
            "returncode": completed.returncode,
            "stdout_path": str(PROBE_STDOUT),
            "stdout_sha256": sha(completed.stdout.encode()),
            "stderr_path": str(PROBE_STDERR),
            "stderr_sha256": sha(completed.stderr.encode()),
        },
        "a_selector_status": result.get("a_selector_status"),
        "scope_limit": "The formal A premarket pool is verified ready with 37 rows, but the isolated selector-ready panel was absent, so the facade reports a_selector_status=CANNOT_CONFIRM. The exact-date HK security-master input is unavailable, so the actual facade handler returns FAILED/UPSTREAM_NOT_READY at first_gate=HK_SECURITY_MASTER and does not call HK scoring. This proves the bounded facade binding and failure path; it does not prove a Stage run, A Stage acceptance, live scheduler behavior, deployment, or a natural receipt.",
        "stage_run_performed": False,
        "natural_receipt_verified": False,
        "active_owner_write_count": 0,
        "live_shared_store_write_count": 0,
        "network_calls": 0,
        "launchctl_called": False,
        "scheduler_mutated": False,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "harness_iterations": [
            "First r6 invocation omitted PYTHONPATH and failed import before loading the candidate app.",
            "Next invocation supplied the pinned package path but an explicit Python 3.14 HK runtime made the unrelated HK_RUNTIME gate win.",
            "Final invocation used the runner seam without an explicit HK runtime and reached the exact missing-master gate; no materializer was rerun.",
        ],
    }
    receipt_sha = write_exclusive(RECEIPT, result_receipt)
    print(json.dumps({"receipt_path": str(RECEIPT), "receipt_sha256": receipt_sha,
                      "status": result_receipt["status"], "first_gate": result.get("first_gate"),
                      "a_selector_status": result.get("a_selector_status"),
                      "hk_lane_status": result.get("hk_lane_status"),
                      "candidate_full_app_delta": app_delta}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
