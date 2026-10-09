"""A required local HK gate is decisive even after successful upstream work."""
import json

import pytest

from scheduler_slice_harness import ProcessBoundary, load_preselection, request


OWNERS = ("actual_pool_scheduler", "canonical_reference")
INVALID_GATES = (
    None,
    [],
    {},
    {"required": []},
    {"required": {}},
    {"required": {"hkconnect_d1_top100": None}},
    {"required": {"hkconnect_d1_top100": {}}},
    {"required": {"hkconnect_d1_top100": {"ready": False}}},
    {"required": {"hkconnect_d1_top100": {"ready": 1}}},
    {"required": {"hkconnect_d1_top100": {"ready": "true"}}},
)


def local_payload(boundary, payload, *, include_authoritative=True):
    run = boundary._run

    def with_payload(module, arguments, **kwargs):
        result = run(module, arguments, **kwargs)
        if module == "ops.materialize_scheduled_preselection":
            result["stdout"] = json.dumps(payload)
            result.pop("_authoritative_payload", None)
            if include_authoritative:
                result["_authoritative_payload"] = payload
        return result

    boundary._run = with_payload


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("gate", INVALID_GATES)
def test_present_invalid_hk_local_gate_cannot_settle_success(monkeypatch, tmp_path, owner, gate):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path)
    local_payload(boundary, {"formal_pool_gate": gate})
    result = handler(boundary, request())
    assert boundary.scored.exists()
    assert boundary.local_materialized.exists()
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["first_gate"] == "HK_LOCAL_POOL"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["materializer_status"] == "SUCCEEDED"


@pytest.mark.parametrize("owner", OWNERS)
def test_absent_local_hk_contract_keeps_a_materialization_but_fails_closed(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path)
    local_payload(boundary, {})
    result = handler(boundary, request())
    assert boundary.local_materialized.exists()
    assert result["status"] == "FAILED"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    expected = "HK_LOCAL_POOL_CONTRACT_UNAVAILABLE" if owner == "actual_pool_scheduler" else "HK_LOCAL_POOL"
    assert result["first_gate"] == expected
    assert result["materializer_status"] == "SUCCEEDED"


def test_actual_stdout_alone_cannot_invent_missing_authoritative_parser(monkeypatch, tmp_path):
    _, handler = load_preselection(monkeypatch, "actual_pool_scheduler")
    boundary = ProcessBoundary(tmp_path)
    local_payload(boundary, {"formal_pool_gate": {"required": {"hkconnect_d1_top100": {"ready": True}}}}, include_authoritative=False)
    result = handler(boundary, request())
    assert result["status"] == "FAILED"
    assert result["first_gate"] == "HK_LOCAL_POOL_CONTRACT_UNAVAILABLE"


@pytest.mark.parametrize("owner", OWNERS)
def test_literal_ready_local_gate_preserves_verified_success_after_refresh_failure(monkeypatch, tmp_path, owner):
    _, handler = load_preselection(monkeypatch, owner)
    boundary = ProcessBoundary(tmp_path, failing_module="ops.ensure_hk_security_master")
    local_payload(boundary, {"formal_pool_gate": {"required": {
        "a_d1_premarket_pool": {"ready": True}, "hkconnect_d1_top100": {"ready": True},
    }}})
    result = handler(boundary, request())
    assert result["status"] == "SUCCEEDED"
    assert result["hk_lane_status"] in {"READY", "SUCCEEDED"}
    assert not boundary.scored.exists()


@pytest.mark.parametrize("explicit_rejection", (False, True))
def test_actual_verified_formal_pair_is_only_absence_exception(monkeypatch, tmp_path, explicit_rejection):
    _, handler = load_preselection(monkeypatch, "actual_pool_scheduler")
    boundary = ProcessBoundary(tmp_path)
    boundary._verified_formal_pool_reuse = lambda day: {"formal_pool_reuse": {"unit_verified_pair": True}}
    payload = {"formal_pool_gate": {"required": {"hkconnect_d1_top100": {"ready": False}}}} if explicit_rejection else {}
    local_payload(boundary, payload)
    result = handler(boundary, request())
    assert result["status"] == ("FAILED" if explicit_rejection else "SUCCEEDED")
    assert result["hk_lane_status"] == ("CANNOT_CONFIRM" if explicit_rejection else "READY")
    assert not boundary.scored.exists()


def test_canonical_noneligible_hk_lane_does_not_require_hk_gate(monkeypatch, tmp_path):
    module, handler = load_preselection(monkeypatch, "canonical_reference")
    monkeypatch.setattr(module, "_preselection_market_lane_states", lambda day: ("FULL_TRADING_DAY", "NON_TRADING_DAY"))
    boundary = ProcessBoundary(tmp_path)
    local_payload(boundary, {"formal_pool_gate": {"required": {"a_d1_premarket_pool": {"ready": True}}}})
    result = handler(boundary, request())
    assert result["status"] == "SUCCEEDED"
    assert result["hk_lane_status"] == "NOT_APPLICABLE"
    assert boundary.local_materialized.exists()
