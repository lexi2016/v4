"""Independent real-contract timing probes with full candidate helper imports.

The original Node, mode function and scheduler decision are executed. Only
their clocks, calendar and final dispatcher are explicit synthetic boundaries.
No current Mac CLI, collector, provider, HK observation lane or service runs.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import importlib.util
import math
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

import pytest


WORK = Path(__file__).resolve().parents[3]
SOURCE = WORK / "entrypoint_clock"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DATE = "20261009"
PINNED_SUPPORT = {
    "contracts.py": "6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d",
    "namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "run_stage_center_nodes.py": "8e9ca56aca8a21950590abe83ef305e46a022490eb61f48e0c5d19c2493e1772",
    "scheduler.py": "db110aba2fe504213591330000120b660cff04292728b5325711e2fa6799e7b0",
}


def load_module(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def declarations(path, names, scope):
    selected = []
    for node in ast.parse(path.read_text()).body:
        name = node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name in names:
            selected.append(node)
    assert len(selected) == len(names)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), scope)


@pytest.fixture(params=["actual_stage", "canonical"])
def rt(request, monkeypatch):
    for filename, expected in PINNED_SUPPORT.items():
        assert hashlib.sha256((SOURCE / "test_support" / filename).read_bytes()).hexdigest() == expected
    contracts = runpy.run_path(str(SOURCE / "test_support/contracts.py"))
    package_name = "independent_clock_" + uuid.uuid4().hex
    package = ModuleType(package_name)
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package_name, package)
    load_module(package_name + "._namespace", SOURCE / "test_support/namespace.py", monkeypatch)
    owner = SOURCE / "after" / request.param / "ops/_run_stage_center_nodes_parts"
    wait = load_module(package_name + ".deadline_supervision", owner / "deadline_supervision.py", monkeypatch)
    entry = load_module(package_name + ".node_entry", owner / "node_entry.py", monkeypatch)
    facade = ModuleType(package_name + ".original_facade")
    monkeypatch.setitem(sys.modules, facade.__name__, facade)
    scope = facade.__dict__
    scope.update(dataclass=dataclass, datetime=datetime, timedelta=timedelta,
                 ZoneInfo=ZoneInfo, EIGHT_STAGES=contracts["EIGHT_STAGES"])
    declarations(SOURCE / "test_support/run_stage_center_nodes.py", {
        "SHANGHAI", "MAX_CALENDAR_WAIT_SECONDS", "SCHEMA_VERSION", "NODE_SCHEDULE_VERSION",
        "PREP_NODE_ID", "PRECAPTURE_NODE_ID", "PREP_NODE_IDS", "NODE_MINUTES", "Node",
        "_as_shanghai", "_node_mode", "_valid_trade_date", "TRANSIENT_STATUSES",
    }, scope)
    class State(Enum):
        TRADING_DAY = "TRADING_DAY"
        NON_TRADING_DAY = "NON_TRADING_DAY"
        UNKNOWN = "UNKNOWN"
    scheduler = {"datetime": datetime, "sha256": hashlib.sha256,
        "TradingDayState": State, "EIGHT_STAGES": contracts["EIGHT_STAGES"],
        "calendar_provenance": lambda: {"scope": "explicit synthetic calendar boundary"},
        # This calendar seam does not authorize an HK Connect observation lane.
        "resolve_market_states": lambda _: {"a_share": State.TRADING_DAY,
            "hk_securities": State.TRADING_DAY, "hk_connect": State.NON_TRADING_DAY}}
    declarations(SOURCE / "test_support/scheduler.py", {"DueDecision", "_idempotency_key", "evaluate_due"}, scheduler)
    events = []
    scope["_deadline"] = SimpleNamespace(event=lambda name, **kw: events.append((name, kw)),
                                         checkpoint=lambda name: events.append((name, {})))
    scope["_bounded_wait_until"] = lambda target, now, *, sleep: wait.__bounded_wait_until_body(
        scope, target, now, sleep=sleep, max_wait_seconds=scope["MAX_CALENDAR_WAIT_SECONDS"])
    scope["STAGE_BY_ID"] = contracts["STAGE_BY_ID"]
    scope["_safe_flags"] = lambda: dict(contracts["SAFETY_FLAGS"])
    return SimpleNamespace(scope=scope, wait=wait, entry=entry,
        contracts=contracts, evaluate_due=scheduler["evaluate_due"], events=events)


def cutoff(rt, stage):
    return datetime.strptime(DATE + " " + rt.contracts["STAGE_BY_ID"][stage].cutoff,
                             "%Y%m%d %H:%M:%S").replace(tzinfo=SHANGHAI)


def clock_after_sleep(rt, wake):
    calls = []
    class Wake(datetime):
        @classmethod
        def now(cls, tz=None):
            assert calls and calls[0][0] == "sleep"
            calls.append(("wall_clock", tz))
            return wake.astimezone(tz) if tz else wake.replace(tzinfo=None)
    rt.scope["datetime"] = Wake
    def sleep(seconds):
        calls.append(("sleep", seconds))
    return sleep, calls


def run_stage(rt, stage, initial, wake):
    hour, minute = rt.scope["NODE_MINUTES"][stage]
    node = rt.scope["Node"](node_id=stage, hour=hour, minute=minute, stage_id=stage)
    rt.scope["_node_candidates"] = lambda *args, **kwargs: (node,)
    sleep, calls = clock_after_sleep(rt, wake)
    decisions = []
    def dispatch(config, date, key, evaluated, **kwargs):
        decision = rt.evaluate_due(key, date, evaluated)
        decisions.append((evaluated, kwargs["mode"], decision))
        return {"status": decision.status, "dispatch_mode": kwargs["mode"], "stage_id": key}
    rt.scope["_dispatch_stage"] = dispatch
    result = rt.entry._run_nodes_body(rt.scope, {}, trade_date=DATE,
        evaluated_at=initial, explicit_node=stage, materializer=None,
        runner=object(), sleep=sleep)
    assert len(decisions) == 1
    return result, decisions[0], calls


@pytest.mark.parametrize("stage,late,expected_mode", [
    ("STAGE_0940_0945", 0.000001, "RECOVERY"),
    ("STAGE_0945_1030", 0.25, "NATURAL"),
    ("STAGE_0945_1030", 5.000001, "RECOVERY"),
])
def test_real_node_window_and_stage_cutoff_are_distinct(rt, stage, late, expected_mode):
    target = cutoff(rt, stage)
    wake = target + timedelta(seconds=late)
    result, (observed, mode, decision), calls = run_stage(rt, stage, target - timedelta(seconds=2), wake)
    assert observed == wake
    assert mode == expected_mode
    assert decision.status == "LATE_CATCHUP_REPLAY"
    assert decision.scheduled_at == target
    assert calls == [("sleep", 2.0), ("wall_clock", SHANGHAI)]
    assert result["evaluated_at"] == wake.isoformat()
    assert result["recovery"] is (expected_mode == "RECOVERY")
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))


@pytest.mark.parametrize("shift,mode,status", [
    (-0.5, "NATURAL", "NOT_DUE"),
    (-6.0, "RECOVERY", "NOT_DUE"),
    (86_400.0, "RECOVERY", "CANNOT_CONFIRM"),
])
def test_wall_clock_jumps_are_visible_to_original_due_decision(rt, shift, mode, status):
    stage = "STAGE_0940_0945"
    target = cutoff(rt, stage)
    wake = target + timedelta(seconds=shift)
    result, (observed, actual_mode, decision), calls = run_stage(rt, stage, target - timedelta(seconds=2), wake)
    assert observed == wake and actual_mode == mode and decision.status == status
    assert decision.scheduled_at == target
    assert result["evaluated_at"] == wake.isoformat()


@pytest.mark.parametrize("delta,will_sleep", [(5.0, True), (5.000001, False)])
def test_requested_sleep_never_extends_original_five_second_cap(rt, delta, will_sleep):
    target = cutoff(rt, "STAGE_0940_0945")
    initial = target - timedelta(seconds=delta)
    wake = target + timedelta(seconds=8)
    sleep, calls = clock_after_sleep(rt, wake)
    observed, waited = rt.wait.__bounded_wait_until_body(rt.scope, target, initial,
        sleep=sleep, max_wait_seconds=math.inf)
    if will_sleep:
        assert calls == [("sleep", 5.0), ("wall_clock", SHANGHAI)]
        assert observed == wake and waited == 5.0
    else:
        assert calls == [] and observed == initial and waited == 0


def test_interrupted_sleep_cannot_publish_a_planned_cutoff_as_observed(rt):
    target = cutoff(rt, "STAGE_0940_0945")
    _, calls = clock_after_sleep(rt, target)
    def interrupted(seconds):
        raise InterruptedError("synthetic wait interrupted")
    with pytest.raises(InterruptedError, match="wait interrupted"):
        rt.wait.__bounded_wait_until_body(rt.scope, target, target - timedelta(seconds=1),
            sleep=interrupted, max_wait_seconds=5)
    assert calls == []
    assert [name for name, _ in rt.events] == ["CALENDAR_WAIT_START"]


def test_original_deadline_checkpoint_failure_still_stops_wait_return(rt):
    target = cutoff(rt, "STAGE_0940_0945")
    sleep, calls = clock_after_sleep(rt, target)
    def exhausted(name):
        raise TimeoutError("synthetic deadline checkpoint")
    rt.scope["_deadline"].checkpoint = exhausted
    with pytest.raises(TimeoutError, match="deadline checkpoint"):
        rt.wait.__bounded_wait_until_body(rt.scope, target, target - timedelta(seconds=1),
            sleep=sleep, max_wait_seconds=5)
    assert calls == [("sleep", 1.0)]


def test_timezone_conversion_keeps_instant_and_wake_reads_shanghai_clock(rt):
    target = cutoff(rt, "STAGE_0940_0945")
    wake_utc = (target + timedelta(seconds=0.25)).astimezone(timezone.utc)
    sleep, calls = clock_after_sleep(rt, wake_utc)
    observed, waited = rt.wait.__bounded_wait_until_body(rt.scope,
        target.astimezone(timezone.utc), (target - timedelta(seconds=2)).replace(tzinfo=None),
        sleep=sleep, max_wait_seconds=5)
    assert observed == wake_utc and observed.tzinfo == SHANGHAI and waited == 2.0
    assert calls[-1] == ("wall_clock", SHANGHAI)
