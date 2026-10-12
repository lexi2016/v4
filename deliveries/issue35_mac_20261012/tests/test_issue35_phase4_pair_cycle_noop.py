from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1")
ADAPTER_PATH = TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r3_noop.py"
spec = importlib.util.spec_from_file_location("issue35_phase4_pair_publication_adapter_r3_noop_test", ADAPTER_PATH)
assert spec is not None and spec.loader is not None
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


CANDIDATE_CYCLE_SHA = "a" * 64
OTHER_CYCLE_SHA = "b" * 64


def _before(cycle_sha: str = CANDIDATE_CYCLE_SHA) -> dict[str, str]:
    return {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/live/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/live/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle_sha,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "old-canary",
    }


def _staged(cycle_sha: str = CANDIDATE_CYCLE_SHA) -> dict[str, str]:
    return {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/candidate/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/candidate/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle_sha,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "new-canary",
    }


def test_unchanged_candidate_cycle_sha_is_a_permitted_exact_noop():
    before = _before()
    staged = _staged()
    delta = adapter.validate_scheduler_env_delta(before, staged, CANDIDATE_CYCLE_SHA)
    assert delta == adapter.EXPECTED_SCHEDULER_NOOP_DELTA


def test_unchanged_wrong_cycle_sha_is_rejected():
    with pytest.raises(ValueError, match="UNCHANGED_STAGED_CYCLE_SHA_MISMATCH"):
        adapter.validate_scheduler_env_delta(_before(OTHER_CYCLE_SHA), _staged(OTHER_CYCLE_SHA), CANDIDATE_CYCLE_SHA)


def test_missing_required_other_delta_is_rejected():
    before = _before()
    staged = _staged()
    staged["V4_MANAGER_ANNOUNCEMENT_BINDING"] = before["V4_MANAGER_ANNOUNCEMENT_BINDING"]
    with pytest.raises(ValueError, match="STAGED_ENV_DELTA_OUT_OF_SCOPE"):
        adapter.validate_scheduler_env_delta(before, staged, CANDIDATE_CYCLE_SHA)


def test_added_forbidden_delta_is_rejected():
    before = _before()
    staged = _staged()
    before["UNRELATED_ENV"] = "before"
    staged["UNRELATED_ENV"] = "after"
    with pytest.raises(ValueError, match="STAGED_ENV_DELTA_OUT_OF_SCOPE"):
        adapter.validate_scheduler_env_delta(before, staged, CANDIDATE_CYCLE_SHA)


def test_changed_cycle_sha_is_supported_only_when_set_to_candidate():
    before = _before(OTHER_CYCLE_SHA)
    staged = _staged(CANDIDATE_CYCLE_SHA)
    delta = adapter.validate_scheduler_env_delta(before, staged, CANDIDATE_CYCLE_SHA)
    assert delta == adapter.EXPECTED_SCHEDULER_ENV_DELTA


def test_changed_cycle_sha_to_wrong_candidate_is_rejected():
    before = _before(OTHER_CYCLE_SHA)
    staged = _staged("c" * 64)
    with pytest.raises(ValueError, match="STAGED_CYCLE_SHA_MISMATCH"):
        adapter.validate_scheduler_env_delta(before, staged, CANDIDATE_CYCLE_SHA)
