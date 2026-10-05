"""Issue23: both real wrappers against frozen R1 helper bodies, without I/O.

Set ISSUE23_R1_HELPER_ROOT to the preserved candidate's
app/stage_center/_runner_parts. This suite never patches the helper files.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import stage_center.runner as runner
from stage_center._runner_parts import _namespace, slot_execution, tick_planning

R1_SHA = {
    "slot_execution": "278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a",
    "tick_planning": "c27cb9717ec2940364d1e1186529e6df1b37b07aae0c56f65334f6f9bf06dd15",
}
DATE, STAGE = "20261002", "STAGE_0930_0935"
NOW = datetime(2026, 10, 2, 9, 35)


def _forbidden(*args, **kwargs):
    raise AssertionError("No input/provider/collection/publication is allowed in this test")


class Probe:
    def __init__(self, decisions=()):
        self.decisions = decisions
        self.calls = []
        self.config = object()

    def _prepare_hk_active_snapshots(self, trade_date, evaluated_at, **kwargs):
        self.calls.append(("prepare", trade_date, evaluated_at, kwargs))
        return []

    def due_decisions(self, trade_date, evaluated_at, **kwargs):
        self.calls.append(("due", trade_date, evaluated_at, kwargs))
        return self.decisions

    def tick(self, *args, **kwargs):
        return runner.StageCenterRunner.tick(self, *args, **kwargs)

    def _run_one(self, *args, **kwargs):
        return runner.StageCenterRunner._run_one(self, *args, **kwargs)

    _write_receipt = _backfill_runner = _forbidden


@pytest.fixture
def r1_helpers(monkeypatch):
    value = os.environ.get("ISSUE23_R1_HELPER_ROOT")
    if not value:
        pytest.fail("ISSUE23_R1_HELPER_ROOT must name the frozen R1 helper directory")
    root = Path(value).expanduser().resolve(strict=True)
    package = ModuleType("_issue23_r1_helpers")
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.setitem(sys.modules, package.__name__ + "._namespace", _namespace)
    loaded = {}
    for name, expected in R1_SHA.items():
        path = root / (name + ".py")
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, f"R1 helper drift: {path}"
        spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        # Execute the exact whole verified file, not a signature-only stand-in.
        exec(compile(raw, str(path), "exec"), module.__dict__)
        loaded[name] = module
    monkeypatch.setattr(slot_execution, "_StageCenterRunner__run_one_body",
                        loaded["slot_execution"]._StageCenterRunner__run_one_body)
    monkeypatch.setattr(tick_planning, "_StageCenterRunner_tick_body",
                        loaded["tick_planning"]._StageCenterRunner_tick_body)
    monkeypatch.setattr(runner, "_stage_markets_for_date", lambda *_: ())
    monkeypatch.setattr(runner, "read_candidate_input", _forbidden)
    return loaded


def call_wrapper(entry, receiver, **kwargs):
    if entry == "_run_one":
        decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="DUE")
        return runner.StageCenterRunner._run_one(receiver, decision, **kwargs)
    return runner.StageCenterRunner.tick(receiver, DATE, NOW, **kwargs)


@pytest.mark.parametrize("entry", ["_run_one", "tick"])
@pytest.mark.parametrize("kwargs", [{}, {"historical_markets": None}])
def test_issue23_r3_r1_default_reaches_real_helper(r1_helpers, entry, kwargs):
    probe = Probe()
    if entry == "_run_one":
        with pytest.raises(runner.RunnerError, match="no securities market is open"):
            call_wrapper(entry, probe, **kwargs)
    else:
        result = call_wrapper(entry, probe, **kwargs)
        assert result == {"status": "CANNOT_CONFIRM", "trade_date": DATE,
                          "stages": [], "pre_captures": [], **runner.SAFETY_FLAGS}
        assert [call[0] for call in probe.calls] == ["prepare", "due"]
        assert probe.calls[1][3] == {"historical_backfill": False}


@pytest.mark.parametrize("entry", ["_run_one", "tick"])
@pytest.mark.parametrize("markets", [("HK_CONNECT",), (), []])
def test_issue23_r3_r1_explicit_request_rejected_before_body(r1_helpers, entry, markets):
    probe = Probe()
    with pytest.raises(TypeError, match="unexpected keyword argument 'historical_markets'"):
        call_wrapper(entry, probe, historical_backfill=True, historical_markets=markets)
    assert probe.calls == []


@pytest.mark.parametrize("entry", ["_run_one", "tick"])
def test_issue23_r3_r1_legacy_backfill_flags_are_preserved(r1_helpers, entry):
    probe = Probe()
    if entry == "_run_one":
        # An existing backfill id avoids creating a backfill runner. Dropping
        # this argument would call Probe._backfill_runner and fail the test.
        with pytest.raises(runner.RunnerError, match="no securities market is open"):
            call_wrapper(entry, probe, historical_backfill=True, backfill_run_id="synthetic-existing")
    else:
        result = call_wrapper(entry, probe, historical_backfill=True, _skip_precapture=True)
        assert result["status"] == "CANNOT_CONFIRM"
        assert probe.calls == [("due", DATE, NOW, {"historical_backfill": True})]


def test_issue23_r3_real_r1_tick_recursion_enters_real_slot_and_releases_lock(r1_helpers, monkeypatch):
    events = []
    class Lock:
        def __init__(self, path):
            assert path == "synthetic-lock"
        def acquire(self):
            events.append("acquire")
            return True
        def release(self):
            events.append("release")
    monkeypatch.setattr(runner, "SlotLock", Lock)
    monkeypatch.setattr(runner, "_slot_lock_path", lambda *_: "synthetic-lock")
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="DUE")
    probe = Probe((decision,))
    with pytest.raises(runner.RunnerError, match="no securities market is open"):
        probe.tick(DATE, NOW)
    assert [call[0] for call in probe.calls] == ["prepare", "due", "due"]
    assert events == ["acquire", "release"]


@pytest.mark.parametrize("entry", ["_run_one", "tick"])
@pytest.mark.parametrize("markets", [None, ("HK_CONNECT",), (), []])
def test_issue23_r3_required_keyword_signature_keeps_exact_value(monkeypatch, entry, markets):
    calls = []
    def slot(scope, receiver, decision, *, historical_backfill, backfill_run_id, historical_markets):
        calls.append((historical_backfill, backfill_run_id, historical_markets))
        return historical_markets
    def tick(scope, receiver, date, at, *, stage_id, historical_backfill, historical_markets, _skip_precapture):
        calls.append((stage_id, historical_backfill, historical_markets, _skip_precapture))
        return historical_markets
    # These explicitly required keyword signatures match the frozen canonical
    # helpers. The compatibility branch must not break canonical default None.
    monkeypatch.setattr(slot_execution, "_StageCenterRunner__run_one_body", slot)
    monkeypatch.setattr(tick_planning, "_StageCenterRunner_tick_body", tick)
    kwargs = {"historical_backfill": True, "historical_markets": markets}
    kwargs.update({"backfill_run_id": "synthetic-id"} if entry == "_run_one"
                  else {"stage_id": STAGE, "_skip_precapture": True})
    assert call_wrapper(entry, Probe(), **kwargs) is markets
    assert calls == ([(True, "synthetic-id", markets)] if entry == "_run_one"
                     else [(STAGE, True, markets, True)])


@pytest.mark.parametrize("entry", ["_run_one", "tick"])
def test_issue23_r3_internal_typeerror_not_retried_or_swallowed(monkeypatch, entry):
    calls = []
    def slot(scope, receiver, decision, *, historical_backfill, backfill_run_id):
        calls.append("slot")
        raise TypeError("sentinel inside helper")
    def tick(scope, receiver, date, at, *, stage_id, historical_backfill, _skip_precapture):
        calls.append("tick")
        raise TypeError("sentinel inside helper")
    monkeypatch.setattr(slot_execution, "_StageCenterRunner__run_one_body", slot)
    monkeypatch.setattr(tick_planning, "_StageCenterRunner_tick_body", tick)
    with pytest.raises(TypeError, match="^sentinel inside helper$"):
        call_wrapper(entry, Probe())
    assert len(calls) == 1
