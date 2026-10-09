"""Pinned original helper bodies; clocks/calendar/dispatch are explicit boundaries.

These tests do not load a current Mac application or collect real quotes.
"""
from __future__ import annotations
import ast
import builtins
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import os
import runpy
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY, STAGE = "20261009", "STAGE_0940_0945"
STAGE_SPECS = runpy.run_path(str(ROOT/"test_support/contracts.py"))["STAGE_BY_ID"]
CUTOFF = datetime.strptime(f"{DAY} {STAGE_SPECS[STAGE].cutoff}", "%Y%m%d %H:%M:%S").replace(tzinfo=SHANGHAI)
NODE_TIME = CUTOFF.replace(second=0)
VARIANT = os.environ.get("STAGE_CLOCK_VARIANT", "after")

def load_nodes(path, names, scope):
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    assert {node.name for node in selected} == set(names)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), scope)
    return scope

@pytest.fixture(params=["actual_stage", "canonical"])
def runtime(request):
    scope = {"__builtins__": builtins, "datetime": datetime, "SHANGHAI": SHANGHAI,
             "MAX_CALENDAR_WAIT_SECONDS": 5.0}
    namespace = load_nodes(ROOT/"test_support/namespace.py", ["read_global"], {"builtins": builtins})
    scope["_v4_global"] = namespace["read_global"]
    load_nodes(ROOT/"test_support/run_stage_center_nodes.py", ["_as_shanghai", "_node_mode"], scope)
    source = ROOT/VARIANT/request.param/"ops/_run_stage_center_nodes_parts"
    load_nodes(source/"deadline_supervision.py", ["__bounded_wait_until_body"], scope)
    load_nodes(source/"node_entry.py", ["_run_nodes_body"], scope)
    events = []
    scope["_deadline"] = SimpleNamespace(event=lambda name, **kw: events.append((name,kw)), checkpoint=lambda name: events.append((name,{})))
    scope["_bounded_wait_until"] = lambda target, now, *, sleep: scope["__bounded_wait_until_body"](scope,target,now,sleep=sleep,max_wait_seconds=5.0)
    return scope, events

def clock(scope, wake):
    class RealWake(datetime):
        @classmethod
        def now(cls, tz=None):
            return wake.astimezone(tz) if tz else wake.replace(tzinfo=None)
    scope["datetime"] = RealWake

@pytest.mark.parametrize("lag", [0.25, 4.75, 8.0, -2.0])
def test_wait_returns_actual_wake_not_planned_cutoff(runtime, lag):
    scope,events = runtime
    wake = CUTOFF + timedelta(seconds=lag)
    clock(scope,wake)
    sleeps=[]
    observed,waited=scope["_bounded_wait_until"](CUTOFF,CUTOFF-timedelta(seconds=2),sleep=sleeps.append)
    assert observed == wake
    assert waited == 2.0 and sleeps == [2.0]
    assert [name for name,_ in events] == ["CALENDAR_WAIT_START","CALENDAR_WAIT_END"]

@pytest.mark.parametrize("delta,max_wait", [(6,1000),(3,1),(0,5),(-1,5),(1,-1)])
def test_non_wait_keeps_evaluation_and_never_reads_clock(runtime,delta,max_wait):
    scope,events=runtime
    class NoClock(datetime):
        @classmethod
        def now(cls,tz=None):
            raise AssertionError("clock should not be read when no wait happens")
    scope["datetime"]=NoClock
    current=CUTOFF-timedelta(seconds=delta)
    result=scope["__bounded_wait_until_body"](scope,CUTOFF,current,sleep=lambda _: pytest.fail("sleep forbidden"),max_wait_seconds=max_wait)
    assert result == (current,0.0) and events == []

def original_due():
    class State(Enum):
        TRADING_DAY="TRADING_DAY"
        NON_TRADING_DAY="NON_TRADING_DAY"
        UNKNOWN="UNKNOWN"
    scope={"datetime":datetime,"sha256":hashlib.sha256,"TradingDayState":State,
           "EIGHT_STAGES":list(STAGE_SPECS.values()),
           "resolve_market_states":lambda _: {name:State.TRADING_DAY for name in ("a_share","hk_securities","hk_connect")},
           "calendar_provenance":lambda: {"scope":"explicit test calendar"}}
    load_nodes(ROOT/"test_support/scheduler.py",["DueDecision","_idempotency_key","evaluate_due"],scope)
    return scope["evaluate_due"]

@pytest.mark.parametrize("lag,mode,due", [(0.0,"NATURAL","DUE"),(0.25,"RECOVERY","LATE_CATCHUP_REPLAY"),(8,"RECOVERY","LATE_CATCHUP_REPLAY"),(-2,"NATURAL","NOT_DUE"),(-6,"RECOVERY","NOT_DUE")])
def test_original_node_dispatch_uses_wake_and_original_mode_policy(runtime,lag,mode,due):
    scope,events=runtime
    wake=CUTOFF+timedelta(seconds=lag)
    clock(scope,wake)
    node=SimpleNamespace(is_prep=False,stage_id=STAGE,node_id=STAGE,scheduled_at=lambda _:NODE_TIME)
    calls=[]
    evaluate_due=original_due()
    def dispatch(config,date,stage,evaluated,**kwargs):
        decision=evaluate_due(stage,date,evaluated)
        calls.append((date,stage,evaluated,kwargs,decision))
        return {"status":"READY","dispatch_mode":kwargs["mode"],"stage_id":stage}
    scope.update(_valid_trade_date=lambda day:day==DAY,
                 _node_candidates=lambda *args,**kwargs:(node,),
                 STAGE_BY_ID=STAGE_SPECS,
                 _dispatch_stage=dispatch,TRANSIENT_STATUSES={"CANNOT_CONFIRM"},
                 SCHEMA_VERSION="stage_center.nodes.v1",NODE_SCHEDULE_VERSION="original-test-boundary",
                 _safe_flags=lambda:dict(production_allowed=False,buy_gate_updated=False,orders_sent=False))
    value=scope["_run_nodes_body"](scope,{},trade_date=DAY,evaluated_at=CUTOFF-timedelta(seconds=2),explicit_node=STAGE,materializer=None,runner=object(),sleep=lambda _:None)
    assert len(calls)==1
    date,stage,evaluated,kwargs,decision=calls[0]
    assert (date,stage,evaluated,kwargs["mode"])==(DAY,STAGE,wake,mode)
    assert decision.status==due
    assert decision.scheduled_at==CUTOFF  # quote cutoff is still the original cutoff
    assert value["evaluated_at"]==wake.isoformat()
    assert value["recovery"] is (mode=="RECOVERY")
    assert all(value[key] is False for key in ("production_allowed","buy_gate_updated","orders_sent"))

def test_only_two_wait_statements_changed_per_variant():
    if VARIANT=="before":
        pytest.skip("postimage-only preservation check")
    for variant in ("actual_stage","canonical"):
        for filename in ("deadline_supervision.py","node_entry.py"):
            rel=Path(variant)/"ops/_run_stage_center_nodes_parts"/filename
            before=(ROOT/"before"/rel).read_text()
            after=(ROOT/"after"/rel).read_text()
            if filename=="deadline_supervision.py":
                expected=before.replace("return cutoff, delta", "return _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'SHANGHAI'))), delta")
            else:
                expected=before.replace('            mode = "NATURAL"\n', "            mode = _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated)\n")
            assert after==expected
            compile(after,str(rel),"exec")
