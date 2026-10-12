from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


ADAPTER_PATH = Path(__file__).with_name("issue35_phase6_r6_publication_adapter_r2.py")
SPEC = importlib.util.spec_from_file_location("issue35_r6_publication_adapter_r2_under_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def test_exact_final_pin_document_is_accepted() -> None:
    pins = ADAPTER._expected_final_publication_pin_document()
    assert ADAPTER.validate_final_publication_pin_document(pins)["status"] == "READY_FOR_EXACT_R6_PAIR_PREPARATION"


def test_current_final_pin_artifacts_match_the_immutable_document() -> None:
    pins = ADAPTER.verify_r6_transport_pins()
    assert len(pins["artifact_pins"]) == 30


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("candidate", "manifest_sha256"), "0" * 64),
        (("source_files", "supervisor", "sha256"), "0" * 64),
        (("accepted_current13", "canary_sha256"), "0" * 64),
        (("accepted_current13", "completion_sha256"), "0" * 64),
        (("accepted_current13", "run_id"), "0" * 32),
        (("preserved_history", "d8_execution01", "run_id"), "1" * 32),
        (("preserved_history", "357_execution02", "product_sha256"), "0" * 64),
        (("enabled_stage", "files", "api"), "0" * 64),
        (("live_preimages", "api", "sha256"), "0" * 64),
        (("live_preimages", "api_binding", "sha256"), "0" * 64),
        (("environment_contract", "scheduler_changed_keys"), ["V4_MANAGER_ANNOUNCEMENT_APP_ROOT"]),
        (("research_boundary", "full_research_and_pit_completeness"), "PASS"),
    ],
)
def test_final_pin_document_rejects_identity_drift(path: tuple[str, ...], value: object) -> None:
    pins = copy.deepcopy(ADAPTER._expected_final_publication_pin_document())
    target = pins
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="R6_FINAL_PUBLICATION_PIN_MISMATCH"):
        ADAPTER.validate_final_publication_pin_document(pins)


def test_final_pin_document_rejects_unlisted_fields() -> None:
    pins = copy.deepcopy(ADAPTER._expected_final_publication_pin_document())
    pins["unexpected_identity"] = "must not be silently accepted"
    with pytest.raises(ValueError, match="R6_FINAL_PUBLICATION_PIN_FIELDS_MISMATCH"):
        ADAPTER.validate_final_publication_pin_document(pins)


def test_exact_same_cycle_scheduler_noop_delta_is_accepted() -> None:
    cycle = ADAPTER.R6_CYCLE_SHA256
    before = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/old/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/old/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "old-canary",
    }
    staged = {
        **before,
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/r6/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/r6/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": ADAPTER.EXISTING_CANARY_SHA256,
    }
    assert ADAPTER.validate_scheduler_env_delta(before, staged, cycle) == ADAPTER.EXPECTED_SCHEDULER_NOOP_DELTA


def test_same_cycle_noop_rejects_changed_cycle_identity() -> None:
    before = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/old/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/old/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": "wrong-cycle",
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "old-canary",
    }
    staged = {
        **before,
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/r6/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/r6/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": ADAPTER.EXISTING_CANARY_SHA256,
    }
    with pytest.raises(ValueError, match="UNCHANGED_STAGED_CYCLE_SHA_MISMATCH"):
        ADAPTER.validate_scheduler_env_delta(before, staged, ADAPTER.R6_CYCLE_SHA256)


def test_changed_cycle_delta_still_requires_exact_candidate_cycle() -> None:
    before = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/old/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/old/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": "old-cycle",
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "old-canary",
    }
    staged = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/r6/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/r6/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": ADAPTER.R6_CYCLE_SHA256,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": ADAPTER.EXISTING_CANARY_SHA256,
    }
    assert ADAPTER.validate_scheduler_env_delta(before, staged, ADAPTER.R6_CYCLE_SHA256) == ADAPTER.EXPECTED_SCHEDULER_ENV_DELTA


def test_scheduler_delta_rejects_any_additional_environment_change() -> None:
    cycle = ADAPTER.R6_CYCLE_SHA256
    before = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/old/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/old/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "old-canary",
        "V35_APP_ROOT": "/fixed/hk/root",
    }
    staged = {
        **before,
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": "/r6/app",
        "V4_MANAGER_ANNOUNCEMENT_BINDING": "/r6/binding.json",
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": ADAPTER.EXISTING_CANARY_SHA256,
        "V35_APP_ROOT": "/changed/hk/root",
    }
    with pytest.raises(ValueError, match="STAGED_ENV_DELTA_OUT_OF_SCOPE"):
        ADAPTER.validate_scheduler_env_delta(before, staged, cycle)
