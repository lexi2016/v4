"""Reproduce the independent H/O review without editing candidate sources.

Use a Python environment with pandas and pyarrow. All source paths are explicit.
The two source-owner probes use original code with synthetic fixtures, not live
market data or a running Mac service. Temporary stores clean up automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--candidate", required=True, type=Path)
parser.add_argument("--execution-source", required=True, type=Path)
parser.add_argument("--reference-sidecar", required=True, type=Path)
parser.add_argument("--output-dir", required=True, type=Path)
args = parser.parse_args()
candidate = args.candidate.resolve()
execution = args.execution_source.resolve()
reference = args.reference_sidecar.resolve()
output = args.output_dir.resolve()
scripts = Path(__file__).resolve().parent
if output == candidate or output.is_relative_to(candidate):
    raise ValueError("REVIEW_OUTPUT_MUST_BE_OUTSIDE_CANDIDATE")
output.mkdir(parents=True, exist_ok=True)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
source_relatives = [
    "v4/manager_research/workspace_plan.py",
    "v4/manager_research/workspace_daily_channels.py",
    "v4/manager_research/workspace.py",
    "v4/manager_research/workspace_projection.py",
    "v4/manager_research/workspace_identity.py",
    "v4/manager_research/research_attention.py",
    "v4/manager_research/connect_selection.py",
    "stage_center/__init__.py", "stage_center/consumer.py",
    "stage_center/selection.py", "stage_center/contracts.py",
    "stage_center/calendar.py", "stage_center/acquisition.py",
    "infrastructure/owned_io.py", "infrastructure/interprocess_lock.py",
    "infrastructure/preselection_pool_store.py",
    "v3_shared_data/shared_data/hk_daily_supplement.py",
    "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
    "v3_shared_data/shared_data/paths.py",
    "contracts/trading_calendar.py", "contracts/market_calendar_2026.json",
]
source_paths = [candidate / path for path in source_relatives] + [execution, reference]
source_before = {str(path): sha(path) for path in source_paths}
script_paths = [scripts / name for name in (
    "run_independent_hk_o_r2_review.py", "repro_rebound_volume.py",
    "repro_owner_archive_binding.py", "repro_daily_channels.py",
    "repro_sidecar_owner_gates_r2.py", "repro_full_stage_consumer_r2.py")]
script_before = {str(path): sha(path) for path in script_paths}
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
commands = []
documents = {}


def run(label, script, arguments):
    command = [sys.executable, str(scripts / script), *map(str, arguments)]
    completed = subprocess.run(command, cwd=output, env=environment,
        capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(json.dumps(dict(probe=label, command=command,
            exit_code=completed.returncode, stdout=completed.stdout,
            stderr=completed.stderr), ensure_ascii=False))
    value = json.loads(completed.stdout)
    destination = output / (label + ".json")
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commands.append(dict(probe=label, command=command, exit_code=completed.returncode,
        stderr=completed.stderr, result_file=str(destination), result_sha256=sha(destination)))
    documents[label] = value
    return value


volume = run("volume_results_r2", "repro_rebound_volume.py", [candidate])
assert len(volume["cases"]) == 3
for case in volume["cases"][:2]:
    assert case["supplement_read_count"] == 1
    assert (case["strict_count"], case["pending_count"]) == (1, 0)
invalid = volume["cases"][2]
assert (invalid["strict_count"], invalid["pending_count"]) == (0, 1)
assert invalid["diagnostic_rows"][0]["invalid_prior60_high_dates"] == ["20260927"]

archive = run("archive_binding_results_r2", "repro_owner_archive_binding.py", [candidate, candidate])
assert len(archive["cases"]) == 2
for case in archive["cases"]:
    assert case["plan_status"] == "CURRENT" and case["consumed"] is True
    assert case["exact_run_readback"]["status"] == "VERIFIED"
    assert case["channel_status"] == "READY_EMPTY" and case["channel_count"] == 0
    assert case["channel_run_id"] == "a" * 32
    assert case["channel_product_sha256"] == archive["unchanged_product_sha256"]
assert archive["cases"][1]["displayed_latest_attempt_run"] == "b" * 32

projection = run("daily_projection_results_r2", "repro_daily_channels.py", [candidate, candidate])
expected_projection = {
    "baseline_with_no_owner_archive": ("PARTIAL", 1),
    "screen_target_mismatch": ("CANNOT_CONFIRM", None),
    "missing_original_source_refs": ("PARTIAL", None),
    "strict_row_rule_contradiction": ("PARTIAL", None),
    "duplicate_symbol": ("PARTIAL", None),
    "future_market_session": ("CANNOT_CONFIRM", None),
    "all_excluded_without_owner_archive": ("PARTIAL", None),
}
for case in projection["cases"]:
    if case["case"] in expected_projection:
        assert (case["daily_status"], case["daily_selected_count"]) == expected_projection[case["case"]]
assert set(expected_projection).issubset({case["case"] for case in projection["cases"]})

sidecar = run("sidecar_owner_gate_results_r2", "repro_sidecar_owner_gates_r2.py",
    [candidate, "--reference-sidecar", reference, "--output-dir", output])
assert sidecar["assertion_result"] == "PASS" and sidecar["case_count"] == 14
assert (sidecar["complete_ready_case_count"], sidecar["invalid_rejection_case_count"],
    sidecar["legitimate_partial_case_count"]) == (1, 12, 1)
assert sidecar["temporary_fixtures_cleaned"] and sidecar["reviewed_sources_stable"]

stage = run("full_stage_consumer_results_r2", "repro_full_stage_consumer_r2.py",
    [candidate, "--execution-source", execution, "--output-dir", output])
assert stage["passed"] == 9 and stage["failed"] == 0
assert stage["temporary_fixtures_cleaned"] and stage["reviewed_sources_stable"]
assert stage["natural_run_verified"] is False

source_after = {str(path): sha(path) for path in source_paths}
script_after = {str(path): sha(path) for path in script_paths}
assert source_before == source_after, "Reviewed sources changed during the matrix; rerun"
assert script_before == script_after, "Review scripts changed during the matrix; rerun"
result = dict(schema="independent_hk_o_r2_review.v1", assertion_result="PASS",
    observed_at_utc=datetime.now(timezone.utc).isoformat(), python=sys.version,
    python_executable=sys.executable, candidate_source_root=str(candidate),
    candidate_modified_by_reviewer=False, source_stable_during_review=True,
    current_candidate_execution_dependency_present=(candidate / "stage_center/execution_evidence.py").is_file(),
    external_original_dependency_used_for_stage=True,
    real_market_inputs_verified=False, mac_owner_executed=False, natural_run_verified=False,
    probe_summary=dict(volume_regressions=3, archive_binding_regressions=2,
        oversold_projection_regressions=7,
        additional_incomplete_hk_fixture_observation=1,
        sidecar=dict(total=14, complete_ready=1, invalid_rejected=12, legitimate_partial=1),
        full_stage=dict(passed=9, failed=0)),
    full_source_sha256=source_after, review_script_sha256=script_after, commands=commands)
destination = output / "independent_hk_o_r2_results.json"
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
