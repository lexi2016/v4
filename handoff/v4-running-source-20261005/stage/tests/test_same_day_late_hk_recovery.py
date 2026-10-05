from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import ops.run_stage_center_nodes as nodes
import stage_center.runner as runner_module
from ops._run_stage_center_nodes_parts.stage_dispatch import _same_day_late_observation_recovery
from stage_center import live_collectors
from stage_center._live_collectors_parts import hk_minute
from stage_center.acquisition import SourceResult, build_plan
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import STAGE_BY_ID
from stage_center.raw_store import RAW_FIELDS
from stage_center.scheduler import DueDecision


TRADE_DATE = "20260929"
STAGE_ID = "STAGE_1300_1315"
SHANGHAI = timezone(timedelta(hours=8))
EXHQ_SHA = "a" * 64
FUTU_SHA = "b" * 64


def _decision(*, status="LATE_CATCHUP_REPLAY", trade_date=TRADE_DATE, scheduled_at="13:15:00"):
    return DueDecision(
        stage_id=STAGE_ID,
        trade_date=trade_date,
        status=status,
        scheduled_at=datetime.strptime(
            f"{TRADE_DATE} {scheduled_at}", "%Y%m%d %H:%M:%S"
        ).replace(tzinfo=SHANGHAI),
        idempotency_key="fixture",
        calendar={},
    )


@pytest.mark.parametrize(
    ("mode", "trade_date", "evaluated_at", "status", "cutoff", "expected"),
    (
        ("RECOVERY", TRADE_DATE, "14:08:52", "LATE_CATCHUP_REPLAY", "13:15:00", True),
        ("NATURAL", TRADE_DATE, "14:08:52", "LATE_CATCHUP_REPLAY", "13:15:00", False),
        ("RECOVERY", "20260928", "14:08:52", "LATE_CATCHUP_REPLAY", "13:15:00", False),
        ("RECOVERY", TRADE_DATE, "14:08:52", "DUE", "13:15:00", False),
        ("RECOVERY", TRADE_DATE, "14:08:52", "LATE_CATCHUP_REPLAY", "15:00:00", False),
    ),
)
def test_same_day_recovery_flag_requires_real_late_current_day_dispatch(
    mode, trade_date, evaluated_at, status, cutoff, expected
):
    decision = _decision(status=status, scheduled_at=cutoff)
    now = datetime.strptime(
        f"{TRADE_DATE} {evaluated_at}", "%Y%m%d %H:%M:%S"
    ).replace(tzinfo=SHANGHAI)

    assert (
        _same_day_late_observation_recovery(
            {"_as_shanghai": lambda value: value.astimezone(SHANGHAI)},
            mode=mode,
            trade_date=trade_date,
            evaluated_at=now,
            decision=decision,
        )
        is expected
    )


def test_same_day_recovery_flag_rejects_decision_for_another_trade_date():
    decision = _decision(trade_date="20260928")
    now = datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI)

    assert not _same_day_late_observation_recovery(
        {"_as_shanghai": lambda value: value.astimezone(SHANGHAI)},
        mode="RECOVERY",
        trade_date=TRADE_DATE,
        evaluated_at=now,
        decision=decision,
    )


def _candidate() -> CandidateInput:
    return CandidateInput(
        root=Path("/fixture/candidate"),
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256="c" * 64,
        run_id="candidate-run",
        codes=("A.000001",),
        artifact_sha256="d" * 64,
        manifest_sha256="e" * 64,
        receipt_sha256="f" * 64,
        source_projection_sha256="g" * 64,
        source_evidence=("fixture=candidate",),
    )


def test_plan_keeps_late_recovery_separate_from_historical_backfill(tmp_path):
    plan = build_plan(
        tmp_path,
        TRADE_DATE,
        STAGE_ID,
        candidate=_candidate(),
        same_day_late_observation_recovery=True,
    )
    assert plan.same_day_late_observation_recovery is True
    assert plan.historical_backfill is False

    with pytest.raises(ValueError, match="separate execution modes"):
        build_plan(
            tmp_path,
            TRADE_DATE,
            STAGE_ID,
            candidate=_candidate(),
            historical_backfill=True,
            same_day_late_observation_recovery=True,
        )


def _minute_source(*, rows=None, status="READY"):
    if rows is None:
        rows = (
            dict.fromkeys(RAW_FIELDS, ""),
        )
        row = dict(rows[0])
        row.update(
            {
                "batch_index": 1,
                "code": "HK.00001",
                "name": "Fixture HK",
                "update_time": "2026-09-29 13:14:00",
                "window_start": "2026-09-29 13:01:00",
                "window_end": "2026-09-29 13:14:00",
                "bar_count": 14,
                "temporal_cutoff_safe": True,
                "open_price": 10.0,
                "high_price": 10.5,
                "low_price": 9.8,
                "last_price": 10.4,
                "prev_close_price": 10.0,
                "turnover": 31_000_000.0,
                "volume": 3_000_000,
            }
        )
        rows = (row,)
    return SourceResult(
        "pytdx_exhq",
        status,
        rows=tuple(rows),
        requested_rows=1,
        source_evidence=(
            "route=shared_pytdx_exhq_hk_exact_d1_top100",
            f"exhq_artifact_sha256={EXHQ_SHA}",
            "exhq_observed_update_time=2026-09-29 13:14:00",
        ),
    )


def _collect(plan, source, *, futu_errors=("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",)):
    calls = []

    class SharedModule:
        @staticmethod
        def collect_pytdx_exhq_minute(*args, **kwargs):
            calls.append(("exhq", args, kwargs))
            return object()

    def futu_snapshot(*args, **kwargs):
        calls.append(("futu", args, kwargs))
        return (
            {"HK.00001": {"volume_ratio": 99.0}},
            (
                f"active_snapshot_sha256={FUTU_SHA}",
                "active_snapshot_update_time=2026-09-29T14:08:52+08:00",
                "active_snapshot_temporal_cutoff_safe=false",
            ),
            futu_errors,
        )

    scope = {
        "_shared_scripts_root": lambda value: value,
        "_load_shared_module": lambda *_args: SharedModule,
        "_scoped_process_runner": lambda _root, process_runner: process_runner,
        "_to_source": lambda *_args, **_kwargs: source,
        "_futu_hkconnect_active_snapshot": futu_snapshot,
        "_canonical_hk_code": lambda value: value,
        "_refresh_hk_active_lanes_body": hk_minute._refresh_hk_active_lanes_body,
        "STAGE_BY_ID": STAGE_BY_ID,
        "replace": replace,
    }
    scope["refresh_hk_active_lanes"] = lambda current, **kwargs: hk_minute._refresh_hk_active_lanes_body(
        scope,
        current,
        **kwargs,
    )
    result = hk_minute._collect_hk_minute_body(
        scope,
        plan,
        codes=("HK.00001",),
        python_path="/fixture/python",
        shared_root="/fixture/shared",
        process_runner=object(),
        replay_provider=None,
    )
    return result, calls


def test_late_recovery_keeps_exact_exhq_observation_and_selection_evidence():
    source = _minute_source()
    plan = build_plan(
        Path("/fixture/input"),
        TRADE_DATE,
        STAGE_ID,
        candidate=_candidate(),
        same_day_late_observation_recovery=True,
    )

    recovered, calls = _collect(plan, source)

    assert recovered.status == "PARTIAL_WITH_ROWS"
    assert recovered.rows == source.rows
    assert recovered.rows[0]["update_time"] == "2026-09-29 13:14:00"
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in recovered.cannot_confirm
    assert f"active_snapshot_sha256={FUTU_SHA}" in recovered.source_evidence
    assert f"exhq_artifact_sha256={EXHQ_SHA}" in recovered.source_evidence
    assert "same_day_late_observation_recovery=true" in recovered.source_evidence
    assert "active_snapshot_degraded_to_pytdx_observation=true" in recovered.source_evidence
    assert "LIVE_HKCONNECT_GAINER" not in str(recovered.rows)
    assert [name for name, *_rest in calls] == ["exhq", "futu"]

    selection = live_collectors.production_selection_builders(STAGE_ID)["HK_CONNECT"](
        recovered,
        plan,
        {
            "artifact_sha256": "1" * 64,
            "status": recovered.status,
            "requested_rows": recovered.requested_rows,
            "missing_symbols": (),
            "cannot_confirm": recovered.cannot_confirm,
            "source_evidence": recovered.source_evidence,
            "cutoff_at": STAGE_BY_ID[STAGE_ID].cutoff,
        },
    )
    assert selection["selection_status"] == "PARTIAL_WITH_ROWS"
    assert selection["selected_rows"] == 1
    assert selection["rows"][0]["source_last_bar_time"] == "2026-09-29 13:14:00"
    assert f"exhq_artifact_sha256={EXHQ_SHA}" in selection["source_evidence"]
    assert "active_snapshot_degraded_to_pytdx_observation=true" in selection["source_evidence"]
    assert "LIVE_HKCONNECT_GAINER" not in str(selection["rows"])


def test_missing_exhq_minute_rows_do_not_probe_or_publish_recovery():
    source = _minute_source(rows=(), status="CANNOT_CONFIRM")
    plan = build_plan(
        Path("/fixture/input"),
        TRADE_DATE,
        STAGE_ID,
        candidate=_candidate(),
        same_day_late_observation_recovery=True,
    )

    recovered, calls = _collect(plan, source)

    assert recovered is source
    assert recovered.status == "CANNOT_CONFIRM"
    assert recovered.rows == ()
    assert [name for name, *_rest in calls] == ["exhq"]
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in recovered.source_evidence


def test_natural_unsafe_active_snapshot_still_fails_closed():
    source = _minute_source()
    plan = build_plan(Path("/fixture/input"), TRADE_DATE, STAGE_ID, candidate=_candidate())

    recovered, _calls = _collect(plan, source)

    assert recovered.status == "CANNOT_CONFIRM"
    assert recovered.rows == ()
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in recovered.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in recovered.source_evidence


def test_runner_publishes_late_recovery_to_normal_selection_store(monkeypatch, tmp_path):
    import ops.run_stage_center_nodes as nodes
    import stage_center.runner as runner_module
    from stage_center.runner import RunnerConfig, StageCenterRunner
    from stage_center.selection import SelectionStore, select_a_live_stage

    source = _minute_source()
    candidate = _candidate()
    plan_seen = []

    def collector(plan, _market):
        plan_seen.append(plan)
        result, _calls = _collect(plan, source)
        return result

    def a_builder(current, plan, raw):
        return select_a_live_stage(
            current.rows,
            plan.trade_date,
            plan.stage_id,
            raw["artifact_sha256"],
            source_status=current.status,
            requested_rows=current.requested_rows,
            missing_symbols=current.missing_symbols,
            cannot_confirm=current.cannot_confirm,
            source_evidence=current.source_evidence,
        )

    monkeypatch.setattr(runner_module, "_stage_markets_for_date", lambda *_args: ("A_SHARE", "HK_CONNECT"))
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        runner_module,
        "_validate_exact_selection_inputs",
        lambda *_args, **_kwargs: ("hk_exact_inputs=fixture",),
    )
    monkeypatch.setattr(runner_module, "_attach_hk_authority", lambda current, **_kwargs: current)

    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        selection_builders={
            "A_SHARE": a_builder,
            "HK_CONNECT": live_collectors.production_selection_builders(STAGE_ID)["HK_CONNECT"],
        },
    )
    runner = StageCenterRunner(
        config,
        collectors={
            "A_SHARE": lambda *_args: SourceResult(
                "A_SHARE", "CANNOT_CONFIRM", cannot_confirm=("fixture A input blocked",), requested_rows=1
            ),
            "HK_CONNECT": collector,
        },
    )
    monkeypatch.setattr(runner, "_validate_hk_auction_root_binding", lambda *_args: None)
    monkeypatch.setattr(runner, "_existing_slot", lambda *_args, **_kwargs: ("MISSING", None))
    decision = _decision()

    class NoopDeadline:
        class DeadlineExceeded(Exception):
            pass

        def checkpoint(self, *_args, **_kwargs):
            pass

        def due(self, *_args, **_kwargs):
            pass

        def event(self, *_args, **_kwargs):
            pass

        def complete_receipt(self, _path, receipt, *, rewrite):
            return receipt

    class NoopLock:
        def __init__(self, _path):
            pass

        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(runner, "due_decisions", lambda *_args, **_kwargs: (decision,))
    monkeypatch.setattr(runner_module, "SlotLock", NoopLock)
    monkeypatch.setattr(runner_module, "_slot_lock_path", lambda *_args: tmp_path / "slot.lock")
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *_args, **_kwargs: {"status": "ELIGIBLE"})
    monkeypatch.setattr(nodes, "_config_int", lambda config, key, default: config.get(key, default))
    monkeypatch.setattr(nodes, "_config_float", lambda config, key, default: config.get(key, default))
    monkeypatch.setattr(nodes, "_read_receipt", lambda *_args: None)
    monkeypatch.setattr(nodes, "_node_attempt_count", lambda _receipt: 0)
    monkeypatch.setattr(nodes, "_stage_settled", lambda _receipt: False)
    monkeypatch.setattr(nodes, "_retry_is_due", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(nodes, "_exact_hk_d1_dependency_rearm", lambda *_args: None)
    monkeypatch.setattr(nodes, "_deadline", NoopDeadline())

    result = nodes._dispatch_stage(
        {
            "node_max_attempts": 3,
            "node_retry_backoff_seconds": 60,
            "receipt_root": str(tmp_path / "node-receipts"),
        },
        TRADE_DATE,
        STAGE_ID,
        datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI),
        mode="RECOVERY",
        runner=runner,
    )

    assert decision.same_day_late_observation_recovery is True
    assert len(plan_seen) == 1
    assert plan_seen[0].same_day_late_observation_recovery is True
    assert plan_seen[0].historical_backfill is False
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
    assert result["markets"]["HK_CONNECT"]["rows"][0]["status"] == "NO_TRADE"
    assert result["markets"]["HK_CONNECT"]["rows"][0]["formal_eligible"] is False
    assert result["markets"]["HK_CONNECT"]["rows"][0]["action_level"] == "NO_BUY"
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False

    verified = SelectionStore(config.selection_root).read_verified(
        TRADE_DATE, STAGE_ID, "HK_CONNECT"
    )
    assert verified["selection_status"] == "PARTIAL_WITH_ROWS"
    assert verified["rows"][0]["source_last_bar_time"] == "2026-09-29 13:14:00"
    assert verified["rows"][0]["volume_ratio"] is None
    assert f"exhq_artifact_sha256={EXHQ_SHA}" in verified["source_evidence"]
    assert "active_snapshot_degraded_to_pytdx_observation=true" in verified["source_evidence"]
    assert "LIVE_HKCONNECT_GAINER" not in str(verified["rows"])


def _formal_dispatch_receipt() -> dict:
    # Minimal shape copied from the read-only 20260929/13:00 receipt.
    return {
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "node_id": STAGE_ID,
        "dispatch_mode": "RECOVERY",
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 2,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "markets": {
            "A_SHARE": {"selection_status": "PARTIAL_WITH_ROWS", "selected_rows": 10},
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "source_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "cannot_confirm": ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"],
                "write_performed": False,
            },
        },
    }


class _DispatchNoopDeadline:
    class DeadlineExceeded(Exception):
        pass

    def checkpoint(self, *_args, **_kwargs):
        pass

    def due(self, *_args, **_kwargs):
        pass

    def event(self, *_args, **_kwargs):
        pass

    def complete_receipt(self, _path, receipt, *, rewrite):
        return receipt


class _DispatchNoopLock:
    def __init__(self, _path):
        pass

    def acquire(self):
        return True

    def release(self):
        pass


class _DispatchRunner:
    def __init__(self, receipt_path: Path, *, due_status="LATE_CATCHUP_REPLAY"):
        self.config = SimpleNamespace()
        self.receipt_path = receipt_path
        self.due_status = due_status
        self.run_calls = []
        self.persisted = []

    def due_decisions(self, trade_date, _evaluated_at, *, historical_backfill):
        assert historical_backfill is False
        return (
            DueDecision(
                stage_id=STAGE_ID,
                trade_date=trade_date,
                status=self.due_status,
                scheduled_at=datetime(2026, 9, 29, 13, 15, tzinfo=SHANGHAI),
                idempotency_key="fixture",
                calendar={},
            ),
        )

    def _run_one(self, decision):
        self.run_calls.append(decision)
        return {
            "status": "PARTIAL_WITH_ROWS",
            "write_performed": True,
            "markets": {
                "HK_CONNECT": {
                    "status": "PARTIAL_WITH_ROWS",
                    "selection_status": "PARTIAL_WITH_ROWS",
                    "selected_rows": 1,
                }
            },
        }

    def _receipt_path(self, _trade_date, _stage_id):
        return self.receipt_path

    def _write_receipt(self, payload, _trade_date, _stage_id):
        self.persisted.append(payload)
        return payload


def _dispatch_formal_receipt(
    monkeypatch,
    tmp_path,
    receipt,
    *,
    mode="RECOVERY",
    trade_date=TRADE_DATE,
    evaluated_at=None,
    due_status="LATE_CATCHUP_REPLAY",
):
    if evaluated_at is None:
        evaluated_at = datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI)
    receipt_path = tmp_path / "receipts" / trade_date / STAGE_ID / "receipt.json"
    runner = _DispatchRunner(receipt_path, due_status=due_status)
    config = {
        "receipt_root": str(tmp_path / "receipts"),
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
    }
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *_args, **_kwargs: {"status": "ELIGIBLE"})
    monkeypatch.setattr(nodes, "_read_receipt", lambda *_args: receipt)
    monkeypatch.setattr(nodes, "_deadline", _DispatchNoopDeadline())
    monkeypatch.setattr(runner_module, "SlotLock", _DispatchNoopLock)
    monkeypatch.setattr(runner_module, "_slot_lock_path", lambda *_args: tmp_path / "slot.lock")
    result = nodes._dispatch_stage(
        config,
        trade_date,
        STAGE_ID,
        evaluated_at,
        mode=mode,
        runner=runner,
        precaptures=None,
    )
    return result, runner


def test_actual_dispatch_retries_only_last_exact_hk_cutoff_attempt(monkeypatch, tmp_path):
    receipt = _formal_dispatch_receipt()
    history = (
        tmp_path
        / "receipts"
        / TRADE_DATE
        / STAGE_ID
        / "attempt_evidence"
        / "existing-attempt-2"
        / "001_START.json"
    )
    history.parent.mkdir(parents=True)
    history.write_text('{"attempt_number": 2}\n', encoding="utf-8")

    result, runner = _dispatch_formal_receipt(monkeypatch, tmp_path, receipt)

    assert len(runner.run_calls) == 1
    assert runner.run_calls[0].same_day_late_observation_recovery is True
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["node_outcome"] == "SETTLED_PARTIAL"
    assert result["node_attempt_count"] == 3
    assert result["retry_exhausted"] is False
    assert result["attempt_diagnostic"]["authorizes_selection"] is False
    assert receipt["node_attempt_count"] == 2
    assert history.read_text(encoding="utf-8") == '{"attempt_number": 2}\n'


@pytest.mark.parametrize(
    ("case", "mode", "evaluated_at", "due_status"),
    (
        ("ordinary_settled", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("natural", "NATURAL", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("wrong_current_date", "RECOVERY", datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("at_cutoff", "RECOVERY", datetime(2026, 9, 29, 13, 15, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("not_late_decision", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "DUE"),
        ("historical_mode", "HISTORICAL_BACKFILL", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("attempt_budget_exhausted", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("other_hk_error", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("additional_hk_error", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("malformed_attempt_count", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("hk_rows_exist", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("previous_dispatch_not_recovery", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("receipt_date_mismatch", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("receipt_stage_mismatch", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("receipt_node_mismatch", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("safety_flag_mismatch", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("no_hk_selection", "RECOVERY", datetime(2026, 9, 29, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
    ),
)
def test_settled_dispatch_rejects_nonmatching_receipts_and_modes(
    monkeypatch, tmp_path, case, mode, evaluated_at, due_status
):
    receipt = _formal_dispatch_receipt()
    if case == "ordinary_settled":
        receipt.update(status="READY", node_outcome="SETTLED")
        receipt["markets"]["HK_CONNECT"].update(
            status="READY", selection_status="READY", selected_rows=1, cannot_confirm=[]
        )
    elif case == "attempt_budget_exhausted":
        receipt["node_attempt_count"] = 3
    elif case == "other_hk_error":
        receipt["markets"]["HK_CONNECT"]["cannot_confirm"] = ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
    elif case == "additional_hk_error":
        receipt["markets"]["HK_CONNECT"]["cannot_confirm"].append("HK_ACTIVE_SNAPSHOT_UNAVAILABLE")
    elif case == "malformed_attempt_count":
        receipt["node_attempt_count"] = "2"
    elif case == "hk_rows_exist":
        receipt["markets"]["HK_CONNECT"].update(selected_rows=1, write_performed=True)
    elif case == "previous_dispatch_not_recovery":
        receipt["dispatch_mode"] = "NATURAL"
    elif case == "receipt_date_mismatch":
        receipt["trade_date"] = "20260928"
    elif case == "receipt_stage_mismatch":
        receipt["stage_id"] = "STAGE_1315_1330"
    elif case == "receipt_node_mismatch":
        receipt["node_id"] = "STAGE_1315_1330"
    elif case == "safety_flag_mismatch":
        receipt["production_allowed"] = True
    elif case == "no_hk_selection":
        receipt["markets"]["HK_CONNECT"]["selection_status"] = "PARTIAL_WITH_ROWS"

    result, runner = _dispatch_formal_receipt(
        monkeypatch,
        tmp_path,
        receipt,
        mode=mode,
        evaluated_at=evaluated_at,
        due_status=due_status,
    )

    assert runner.run_calls == []
    assert result["status"] == "SKIPPED_ALREADY_SETTLED"
    expected_attempt_count = 2 if case == "malformed_attempt_count" else receipt["node_attempt_count"]
    assert result["node_attempt_count"] == expected_attempt_count
    assert result["write_performed"] is False
