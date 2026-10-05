from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import ops.run_stage_center_nodes as nodes
from stage_center import runner as runner_module
from stage_center.scheduler import DueDecision


TRADE_DATE = "20260930"
STAGE_ID = "STAGE_1300_1315"
SHANGHAI = timezone(timedelta(hours=8))
HK_CUTOFF_ERROR = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"


def _formal_receipt_shape(*, attempt_count: int = 2, trade_date: str = TRADE_DATE) -> dict:
    # Synthetic formal-shape receipt for a same-day 20260930 cutoff replay.
    # The test never reads or writes the user's state root.
    return {
        "trade_date": trade_date,
        "stage_id": STAGE_ID,
        "node_id": STAGE_ID,
        "dispatch_mode": "RECOVERY",
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": attempt_count,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "markets": {
            "A_SHARE": {
                "selection_status": "PARTIAL_WITH_ROWS",
                "selected_rows": 10,
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "source_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "cannot_confirm": [HK_CUTOFF_ERROR],
                "write_performed": False,
            },
        },
    }


class _NoopDeadline:
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


class _NoopLock:
    def __init__(self, _path):
        pass

    def acquire(self):
        return True

    def release(self):
        pass


class _Runner:
    def __init__(self, receipt_path: Path, *, due_status: str = "LATE_CATCHUP_REPLAY"):
        self.config = SimpleNamespace()
        self.receipt_path = receipt_path
        self.due_status = due_status
        self.run_calls = []
        self.persisted = []

    def due_decisions(self, trade_date, evaluated_at, *, historical_backfill):
        assert historical_backfill is False
        scheduled_day = datetime.strptime(trade_date, "%Y%m%d")
        return (
            DueDecision(
                stage_id=STAGE_ID,
                trade_date=trade_date,
                status=self.due_status,
                scheduled_at=scheduled_day.replace(hour=13, minute=15, tzinfo=SHANGHAI),
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
        self.persisted.append(deepcopy(payload))
        return payload


def _dispatch(monkeypatch, tmp_path, receipt, *, mode="RECOVERY", trade_date=TRADE_DATE,
              evaluated_at=None, due_status="LATE_CATCHUP_REPLAY"):
    if evaluated_at is None:
        evaluated_at = datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI)
    receipt_path = tmp_path / "receipts" / trade_date / STAGE_ID / "receipt.json"
    runner = _Runner(receipt_path, due_status=due_status)
    config = {
        "receipt_root": str(tmp_path / "receipts"),
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
    }
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *_args, **_kwargs: {"status": "ELIGIBLE"})
    monkeypatch.setattr(nodes, "_read_receipt", lambda *_args: receipt)
    monkeypatch.setattr(nodes, "_deadline", _NoopDeadline())
    monkeypatch.setattr(runner_module, "SlotLock", _NoopLock)
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
    return result, runner, receipt_path


@pytest.mark.parametrize(("previous_attempt_count", "expected_attempt_count"), ((1, 2), (2, 3)))
def test_actual_dispatch_retries_an_unexhausted_exact_hk_cutoff_attempt(
    monkeypatch, tmp_path, previous_attempt_count, expected_attempt_count
):
    receipt = _formal_receipt_shape(attempt_count=previous_attempt_count)
    receipt_path = tmp_path / "receipts" / TRADE_DATE / STAGE_ID / "receipt.json"
    history = (
        receipt_path.parent
        / "attempt_evidence"
        / f"existing-attempt-{previous_attempt_count}"
        / "001_START.json"
    )
    history.parent.mkdir(parents=True)
    history.write_text(f'{{"attempt_number": {previous_attempt_count}}}\n', encoding="utf-8")

    result, runner, _receipt_path = _dispatch(monkeypatch, tmp_path, receipt)

    assert len(runner.run_calls) == 1
    assert runner.run_calls[0].same_day_late_observation_recovery is True
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["node_outcome"] == "SETTLED_PARTIAL"
    assert result["node_attempt_count"] == expected_attempt_count
    assert result["retry_exhausted"] is False
    assert result["attempt_diagnostic"]["authorizes_selection"] is False
    assert receipt["node_attempt_count"] == previous_attempt_count
    assert history.read_text(encoding="utf-8") == f'{{"attempt_number": {previous_attempt_count}}}\n'


@pytest.mark.parametrize(
    ("case", "expected_mode", "expected_trade_date", "evaluated_at", "due_status"),
    (
        ("normal_settled", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("natural", "NATURAL", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("wrong_current_date", "RECOVERY", TRADE_DATE, datetime(2026, 10, 1, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("at_cutoff", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 13, 15, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("not_late_decision", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "DUE"),
        ("historical_mode", "HISTORICAL_BACKFILL", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("zero_attempt_count", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("attempt_budget_exhausted", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("other_hk_error", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("hk_rows_exist", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("previous_dispatch_not_recovery", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("wrong_stage_shape", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
        ("wrong_receipt_date", "RECOVERY", TRADE_DATE, datetime(2026, 9, 30, 14, 8, 52, tzinfo=SHANGHAI), "LATE_CATCHUP_REPLAY"),
    ),
)
def test_settled_retry_rejects_nonmatching_receipts_and_modes(
    monkeypatch, tmp_path, case, expected_mode, expected_trade_date, evaluated_at, due_status
):
    receipt = _formal_receipt_shape(attempt_count=1)
    if case == "normal_settled":
        receipt.update(status="READY", node_outcome="SETTLED")
        receipt["markets"]["HK_CONNECT"].update(
            status="READY", selection_status="READY", selected_rows=1, cannot_confirm=[]
        )
    elif case == "zero_attempt_count":
        receipt["node_attempt_count"] = 0
    elif case == "attempt_budget_exhausted":
        receipt["node_attempt_count"] = 3
    elif case == "other_hk_error":
        receipt["markets"]["HK_CONNECT"]["cannot_confirm"] = ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
    elif case == "hk_rows_exist":
        receipt["markets"]["HK_CONNECT"].update(selected_rows=1, write_performed=True)
    elif case == "previous_dispatch_not_recovery":
        receipt["dispatch_mode"] = "NATURAL"
    elif case == "wrong_stage_shape":
        receipt["stage_id"] = "STAGE_1315_1330"
    elif case == "wrong_receipt_date":
        receipt["trade_date"] = "20260929"

    result, runner, _receipt_path = _dispatch(
        monkeypatch,
        tmp_path,
        receipt,
        mode=expected_mode,
        trade_date=expected_trade_date,
        evaluated_at=evaluated_at,
        due_status=due_status,
    )

    assert runner.run_calls == []
    assert result["status"] == "SKIPPED_ALREADY_SETTLED"
    assert result["node_attempt_count"] == receipt["node_attempt_count"]
    assert result["write_performed"] is False
