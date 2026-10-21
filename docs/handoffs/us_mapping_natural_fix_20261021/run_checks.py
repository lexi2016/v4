"""Run the frozen, bounded tests against a specified real code root."""
import argparse
import os
from pathlib import Path
import sys

p=argparse.ArgumentParser()
p.add_argument('--code-root',type=Path,required=True)
p.add_argument('--baseline',action='store_true')
p.add_argument('--review-fixes',action='store_true')
p.add_argument('--exclude-known-baseline',action='store_true')
p.add_argument('--basetemp',required=True)
a=p.parse_args()
os.environ['PYTHONDONTWRITEBYTECODE']='1'
root=a.code_root.resolve()
sys.path[:0]=[str(root),str(root/'upstreams')]
from v4.manager_workbench import service
assert Path(service.__file__).resolve().is_relative_to(root), 'WRONG_IMPORT_ROOT'
print('ACTUAL_SERVICE_SOURCE',service.__file__,flush=True)
import pytest
if a.review_fixes:
    targets=[
        'tests/manager_workbench/engines/test_us_factor.py::test_explicit_malformed_industry_pin_never_falls_through_to_template',
        'tests/manager_workbench/engines/test_us_factor.py::test_absent_nested_industry_key_can_use_fixed_template',
        'tests/manager_workbench/engines/test_us_factor.py::test_explicit_observed_override_wins_and_invalid_override_never_uses_template',
        'tests/manager_workbench/engines/test_us_factor.py::test_fixed_observed_template_spans_consecutive_sessions_and_keeps_original_source',
        'tests/manager_workbench/engines/test_us_factor.py::test_latest_observed_owner_pin_checks_artifact_receipt_manifest_and_capture',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_optional_reason_metadata_cannot_crash_or_change_gate',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_executed_but_all_filtered_is_partial_with_source_and_exact_gaps',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_valid_subset_and_inclusive_cutoff_preserve_gate',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_no_prior_or_only_late_run_is_not_run']
elif a.baseline:
    targets=[
        'tests/manager_workbench/engines/test_us_factor.py::test_fixed_observed_template_spans_consecutive_sessions_and_keeps_original_source',
        'tests/manager_workbench/engines/test_us_factor.py::test_explicit_observed_override_wins_and_invalid_override_never_uses_template',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_executed_but_all_filtered_is_partial_with_source_and_exact_gaps']
else:
    targets=[
        'tests/manager_workbench/runtime/test_us_mapping_wiring.py',
        'tests/manager_workbench/runtime/test_strict_us_selection.py',
        'tests/manager_workbench/engines/test_us_factor.py',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_frozen_before_and_after_cutoff',
        'tests/manager_workbench/runtime/test_runtime.py::test_old_version_unaffected_by_late_preopen_candidate',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_executed_but_all_filtered_is_partial_with_source_and_exact_gaps',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_valid_subset_and_inclusive_cutoff_preserve_gate',
        'tests/manager_workbench/runtime/test_runtime.py::test_preopen_no_prior_or_only_late_run_is_not_run',
        'tests/manager_workbench/runtime/test_native_pipeline.py::test_preopen_keeps_completed_rows_from_partial_lane_and_never_changes']
known=[]
if a.exclude_known_baseline:
    known=['--deselect=tests/manager_workbench/runtime/test_strict_us_selection.py::test_single_day_uses_calendar_bound_sessions_for_ordinary_and_post_holiday_targets',
        '--deselect=tests/manager_workbench/runtime/test_native_pipeline.py::test_preopen_keeps_completed_rows_from_partial_lane_and_never_changes']
raise SystemExit(pytest.main([*targets,*known,'-q','--basetemp='+a.basetemp]))
