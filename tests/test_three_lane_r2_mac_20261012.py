"""Focused contracts for the 2026-10-12 R2 manager repair."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from v4.manager_research import workspace as workspace_module
from v4.manager_research import workspace_daily_channels as daily_channels
from v4.manager_research import workspace_history
from v4.manager_research import workspace_plan_autorun
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS


DATE = "20261012"
PLAN_OWNER = "ManagerResearchJobService.refresh_workspace_plan"


def test_hk_stage_readback_uses_original_consumer_with_backfill_disabled() -> None:
    calls = []
    response = {
        "schema_version": "stage_center.selection_consumer.v1",
        "response_source": "SHARED_STAGE_CENTER",
        "trade_date": DATE,
        "stage_id": "STAGE_0925",
        "markets": {"HK_CONNECT": {"trade_date": DATE, "stage_id": "STAGE_0925"}},
        "execution_evidence": {"source": "existing-owner"},
        "write_performed": False,
        **FLAGS,
    }

    class SelectionConsumer:
        def get(self, *args, **kwargs):
            calls.append((args, kwargs))
            return response

    service = SimpleNamespace(_workspace_stage_selection_reader=SelectionConsumer())
    result = daily_channels.read_original_stage_selection(service, DATE)

    assert calls == [((DATE, "STAGE_0925"), {"markets": ("HK_CONNECT",), "allow_backfill": False})]
    assert result["trade_date"] == DATE
    assert result["markets"]["HK_CONNECT"] == response["markets"]["HK_CONNECT"]
    assert result["write_performed"] is False


def test_unbound_or_failing_stage_consumer_stays_unknown_and_hides_exception_text() -> None:
    unbound = daily_channels.read_original_stage_selection(SimpleNamespace(), DATE)
    assert unbound == {
        "markets": {},
        "readback_error": "HK_STAGE_SELECTION_CONSUMER_NOT_BOUND",
    }
    unbound_channel = daily_channels._hk_connect(
        {"stage_selection_readback": unbound, "selection_diagnostics": {"membership": {}}},
        {"plan_date": DATE},
    )
    assert unbound_channel["candidate_count"] is None
    assert unbound_channel["gaps"] == ["HK_STAGE_SELECTION_CONSUMER_NOT_BOUND"]

    class FailingConsumer:
        def get(self, *args, **kwargs):
            raise RuntimeError("private/path must not escape")

    failed = daily_channels.read_original_stage_selection(
        SimpleNamespace(_workspace_stage_selection_reader=FailingConsumer()), DATE
    )
    failed_channel = daily_channels._hk_connect(
        {"stage_selection_readback": failed, "selection_diagnostics": {"membership": {}}},
        {"plan_date": DATE},
    )
    assert failed_channel["gaps"] == ["HK_STAGE_SELECTION_OWNER_READ_FAILED:RuntimeError"]
    assert "private/path" not in repr(failed_channel)
    assert failed_channel["candidate_count"] is None


def test_service_keeps_us_reader_when_formal_selection_consumer_is_injected(tmp_path) -> None:
    us_reader = object()
    selection_consumer = object()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager"),
        None,
        None,
        workspace_us_market_reader=us_reader,
        workspace_stage_selection_reader=selection_consumer,
    )
    try:
        assert service._workspace_us_market_reader is us_reader
        assert service._workspace_stage_selection_reader is selection_consumer
    finally:
        service.close()


def _owner_value() -> dict:
    run_id = "a" * 32
    generated = "2026-10-12T01:01:00+00:00"
    attempt = workspace_module.seal_attempt(
        {
            "schema_version": workspace_module.ATTEMPT_SCHEMA,
            "target_trade_date": DATE,
            "run_id": run_id,
            "owner": PLAN_OWNER,
            "state": "SUCCEEDED",
            "execution_kind": "MANUAL_REFRESH",
            "input_identity": "c" * 64,
            "started_at": "2026-10-12T01:00:00+00:00",
            "finished_at": "2026-10-12T01:02:00+00:00",
            "failure_reasons": [],
            **FLAGS,
        }
    )
    return {
        "target_trade_date": DATE,
        "input_identity": "c" * 64,
        "plan_product": {
            "status": "CURRENT",
            "consumed": True,
            "run_id": run_id,
            "sha256": "b" * 64,
            "generated_at": generated,
            "execution_kind": "MANUAL_REFRESH",
            "original_owner": PLAN_OWNER,
        },
        "workspace_plan_attempt": attempt,
    }


def test_canonical_owner_plan_readback_accepts_only_same_run_owner_attempt() -> None:
    result = workspace_plan_autorun.owner_plan_readback(
        _owner_value(), DATE, expected_kind="MANUAL_REFRESH"
    )
    assert result["status"] == "MATERIALIZED"
    assert result["owner"] == PLAN_OWNER
    assert result["run_id"] == "a" * 32
    assert result["input_identity"] == "c" * 64
    assert result["owner_attempt_state"] == "SUCCEEDED"

    changed = deepcopy(_owner_value())
    changed["plan_product"]["run_id"] = "d" * 32
    with pytest.raises(ValueError, match="PLAN_OWNER_PRODUCT_ATTEMPT_READBACK_MISMATCH"):
        workspace_plan_autorun.owner_plan_readback(
            changed, DATE, expected_kind="MANUAL_REFRESH"
        )


def test_history_failure_code_keeps_only_a_bounded_stable_owner_code() -> None:
    owner_error = ValueError("ORIGINAL_OWNER_ARTIFACT_UNAVAILABLE")
    wrapped = ValueError("HISTORY_SOURCE_VALIDATION_FAILED")
    wrapped.__cause__ = owner_error
    assert workspace_history._safe_history_failure_code(wrapped) == (
        "ORIGINAL_OWNER_ARTIFACT_UNAVAILABLE"
    )
    assert workspace_history._safe_history_failure_code(ValueError("/private/path")) is None
