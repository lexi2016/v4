from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "remaining-stages-recovery-20261012-r1/app"
)
REAL_RECEIPT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/"
    "receipts/20261012/STAGE_1300_1315/receipt.json"
)
CANDIDATE_SOURCE = Path(__file__).parents[1] / "overlay/ops/_run_stage_center_nodes_parts/stage_dispatch.py"
REAL_RECEIPT_SHA256 = "cc093fc5875bd18fa07beb9f37b57f35414101cb4e01d86a1e06bdafaf5ff216"
DATE = "20261012"
STAGE = "STAGE_1300_1315"
SHANGHAI = timezone(timedelta(hours=8))

sys.path.insert(0, str(APP_ROOT))
import ops.run_stage_center_nodes as nodes  # noqa: E402
import stage_center.runner as runner_module  # noqa: E402
from stage_center.scheduler import DueDecision  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "ops._run_stage_center_nodes_parts.stage_dispatch_candidate", CANDIDATE_SOURCE
)
assert _SPEC is not None and _SPEC.loader is not None
candidate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = candidate
_SPEC.loader.exec_module(candidate)


def _actual_receipt() -> dict:
    raw = REAL_RECEIPT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REAL_RECEIPT_SHA256
    return json.loads(raw)


def _decision(stage_id: str, scheduled_at: str) -> DueDecision:
    return DueDecision(
        stage_id=stage_id,
        trade_date=DATE,
        status="LATE_CATCHUP_REPLAY",
        scheduled_at=datetime.strptime(f"{DATE} {scheduled_at}", "%Y%m%d %H:%M:%S").replace(
            tzinfo=SHANGHAI
        ),
        idempotency_key="candidate-test",
        calendar={},
    )


@pytest.mark.parametrize(
    ("stage_id", "scheduled_at", "evaluated_at", "expected"),
    (
        ("STAGE_1300_1315", "13:15:00", "13:15:01", True),
        ("STAGE_1445_1500", "15:00:00", "15:00:01", True),
        ("STAGE_1545_1555", "15:55:00", "15:55:01", False),
        ("STAGE_1300_1315", "13:15:00", "13:15:00", False),
    ),
)
def test_natural_late_observation_flag_is_limited_to_today_afternoon_stages(
    stage_id, scheduled_at, evaluated_at, expected
):
    decision = _decision(stage_id, scheduled_at)
    now = datetime.strptime(f"{DATE} {evaluated_at}", "%Y%m%d %H:%M:%S").replace(
        tzinfo=SHANGHAI
    )
    assert candidate._same_day_late_observation_recovery(
        {"_as_shanghai": lambda value: value.astimezone(SHANGHAI)},
        mode="NATURAL",
        trade_date=DATE,
        evaluated_at=now,
        decision=decision,
        stage_id=stage_id,
    ) is expected


def test_recovery_shape_matches_real_receipt_and_rejects_widened_cases():
    receipt = _actual_receipt()
    args = dict(
        mode="RECOVERY", trade_date=DATE, stage_id=STAGE,
        attempt_count=1, max_attempts=3,
    )
    assert candidate._same_day_hk_1300_1315_cutoff_recovery_shape(receipt, **args)

    for mutate, changed_args in (
        (lambda value: value.update(dispatch_mode="RECOVERY"), {}),
        (lambda value: value["markets"]["HK_CONNECT"].update(cannot_confirm=["OTHER"]), {}),
        (lambda value: value["markets"]["A_SHARE"].update(run_id="other"), {}),
        (lambda value: value.update(production_allowed=True), {}),
        (lambda value: None, {"trade_date": "20261013"}),
        (lambda value: None, {"stage_id": "STAGE_1545_1555"}),
        (lambda value: None, {"attempt_count": 3}),
    ):
        altered = copy.deepcopy(receipt)
        mutate(altered)
        assert not candidate._same_day_hk_1300_1315_cutoff_recovery_shape(
            altered, **(args | changed_args)
        )


def test_hk_only_continuation_stays_on_same_date_stage_and_original_budget():
    receipt = {
        "trade_date": DATE,
        "stage_id": STAGE,
        "node_id": STAGE,
        "dispatch_mode": "RECOVERY",
        "status": "CANNOT_CONFIRM",
        "node_outcome": "TRANSIENT",
        "node_attempt_count": 2,
        "execution_origin": "HK_ORIGINAL_BUDGET_RECOVERY",
        "execution_markets": ["HK_CONNECT"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    args = dict(mode="RECOVERY", trade_date=DATE, stage_id=STAGE, max_attempts=3)
    assert candidate._same_day_hk_1300_1315_recovery(
        receipt, attempt_count=2, **args
    )
    assert not candidate._same_day_hk_1300_1315_recovery(
        receipt, attempt_count=3, **args
    )
    assert not candidate._same_day_hk_1300_1315_recovery(
        receipt, attempt_count=2, **(args | {"trade_date": "20261013"})
    )
    assert not candidate._same_day_hk_1300_1315_recovery(
        receipt, attempt_count=2, **(args | {"stage_id": "STAGE_1445_1500"})
    )


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


class _IsolatedRunner:
    def __init__(self, path: Path, initial: dict):
        self.receipt_path = path
        self.config = SimpleNamespace()
        self.initial = initial
        self.run_calls = []
        self.persisted = []

    def due_decisions(self, trade_date, _evaluated_at, *, historical_backfill):
        assert historical_backfill is False
        return (_decision(STAGE, "13:15:00"),)

    def _receipt_path(self, _trade_date, _stage_id):
        return self.receipt_path

    def _run_one(self, decision):
        self.run_calls.append((decision, self._execution_scope.markets))
        assert self._execution_scope.markets == ("HK_CONNECT",)
        return {
            "status": "PARTIAL_WITH_ROWS",
            "write_performed": True,
            "markets": {
                "HK_CONNECT": {
                    "market": "HK_CONNECT",
                    "status": "PARTIAL_WITH_ROWS",
                    "source_status": "READY",
                    "selection_status": "PARTIAL_WITH_ROWS",
                    "selected_rows": 1,
                    "write_performed": True,
                    "evidence_status": "OBSERVATION_UNVERIFIED",
                    "buy_status": "NO_BUY",
                    "temporal_cutoff_safe": False,
                }
            },
        }

    def _write_receipt(self, payload, trade_date, stage_id):
        scope = getattr(self, "_execution_scope", None)
        if scope is not None:
            payload = scope.merge(payload, trade_date, stage_id)
        self.persisted.append(payload)
        self.receipt_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        return payload


def test_actual_dispatch_reopens_only_hk_and_preserves_original_a_pointer(monkeypatch, tmp_path):
    original = _actual_receipt()
    a_share_before = copy.deepcopy(original["markets"]["A_SHARE"])
    candidate_pointer_before = {
        key: original.get(key) for key in ("candidate_run_id", "candidate_current_sha256")
    }
    receipt_path = tmp_path / "receipts" / DATE / STAGE / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(REAL_RECEIPT.read_bytes())
    runner = _IsolatedRunner(receipt_path, original)
    config = {
        "receipt_root": str(receipt_path.parents[2]),
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    evaluated_at = datetime(2026, 10, 12, 14, 0, tzinfo=SHANGHAI)
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *_args, **_kwargs: {"status": "ELIGIBLE"})
    monkeypatch.setattr(nodes, "_read_receipt", lambda *_args: original)
    monkeypatch.setattr(nodes, "_receipt_path", lambda *_args: receipt_path)
    monkeypatch.setattr(nodes, "_deadline", _NoopDeadline())
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: evaluated_at + timedelta(seconds=1))
    monkeypatch.setattr(runner_module, "SlotLock", _NoopLock)
    monkeypatch.setattr(runner_module, "_slot_lock_path", lambda *_args: tmp_path / "slot.lock")

    result = candidate.__dispatch_stage_body(
        vars(nodes), config, DATE, STAGE, evaluated_at,
        mode="RECOVERY", runner=runner, precaptures=None,
    )

    assert len(runner.run_calls) == 1
    decision, markets = runner.run_calls[0]
    assert markets == ("HK_CONNECT",)
    assert decision.same_day_late_observation_recovery is True
    assert result["node_attempt_count"] == 2
    assert result["markets"]["A_SHARE"] == a_share_before
    assert {key: result.get(key) for key in candidate_pointer_before} == candidate_pointer_before
    assert result["markets"]["HK_CONNECT"]["evidence_status"] == "OBSERVATION_UNVERIFIED"
    assert result["markets"]["HK_CONNECT"]["buy_status"] == "NO_BUY"
    assert result["markets"]["HK_CONNECT"]["temporal_cutoff_safe"] is False
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    archived = next(receipt_path.parent.glob("attempt_evidence/preserved-*/PRIOR_RECEIPT.json"))
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == REAL_RECEIPT_SHA256
