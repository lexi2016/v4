"""Frozen first-batch regressions. All writes stay under pytest's owned base."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

CASE = Path(__file__).resolve().parent
SCOPE = json.loads((CASE / "BATCH1_SCOPE.json").read_text())
CORE = Path(SCOPE["allowed_source_files"][0]).parents[5]
API = CORE / "api/app"
GRAPH = CORE / "graph/app"
DAILY = CORE / "daily/app"
STAGE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/stage-failure-snapshots-20261023-r1/app")
sys.path.insert(0, str(API))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _wrapper():
    return _load(DAILY / "ops/run_review_core_bound.py", "batch1_daily_wrapper")


def test_runatload_before_2025_does_no_probe_exec_or_file_read(monkeypatch, capsys):
    wrapper = _wrapper()
    clock = datetime(2026, 10, 26, 20, 24, 59, tzinfo=timezone(timedelta(hours=8)))
    original = wrapper._natural_wait
    monkeypatch.setattr(wrapper, "_natural_wait", lambda args: original(args, now=clock))
    def forbidden(*args, **kwargs):
        raise AssertionError("outside-window heavy path executed")
    monkeypatch.setattr(wrapper, "_directory", forbidden)
    monkeypatch.setattr(wrapper.subprocess, "run", forbidden)
    monkeypatch.setattr(wrapper.os, "execve", forbidden)
    code = wrapper.main(["--python", "/unused/python", "--release-root", "/unused/release",
                         "--shared-package-root", "/unused/shared", "--working-directory", "/unused/cwd",
                         "--mode", "run", "--", "--origin", "natural_scheduler", "--allow-network"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "WAITING_NOT_BEFORE_2025"
    assert payload["receipt_published"] is False
    assert payload["runtime_probe_executed"] is False


@pytest.mark.parametrize("hour,minute", [(20, 25), (20, 40), (21, 5)])
def test_calendar_compensation_enters_original_bound_import_and_exec(tmp_path, monkeypatch, hour, minute):
    wrapper = _wrapper()
    root = tmp_path / "release"
    source = root / "app/review_core"
    source.mkdir(parents=True)
    for name in ["__init__.py", "macos_daily.py"]:
        (source / name).write_text("")
    shared = tmp_path / "shared"
    (shared / "shared_data").mkdir(parents=True)
    for name in ["__init__.py", "public_fupan.py"]:
        (shared / "shared_data" / name).write_text("")
    original = wrapper._natural_wait
    monkeypatch.setattr(wrapper, "_natural_wait", lambda args: original(args, now=datetime(2026,10,26,hour,minute)))
    calls = []
    monkeypatch.setattr(wrapper.subprocess, "run", lambda command, **kwargs: calls.append(("probe", command, kwargs)) or SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr(wrapper.os, "chdir", lambda path: None)
    class ExecReached(Exception):
        pass
    def execute(python, command, environment):
        calls.append(("exec", command, environment))
        raise ExecReached
    monkeypatch.setattr(wrapper.os, "execve", execute)
    with pytest.raises(ExecReached):
        wrapper.main(["--python", sys.executable, "--release-root", str(root), "--shared-package-root", str(shared),
                      "--working-directory", str(tmp_path), "--mode", "run", "--", "--origin", "natural_scheduler", "--allow-network"])
    assert [x[0] for x in calls] == ["probe", "exec"]
    assert "review_core.macos_daily" in calls[-1][1]
    assert "--allow-network" in calls[-1][1]


@pytest.mark.parametrize("business", [["--date", "20261023"], ["--date=20261023"], ["--dat", "20261023"], ["--origin", "manual"], ["--ori", "manual"], ["--help"]])
def test_manual_and_explicit_requests_keep_existing_validation(business):
    assert _wrapper()._natural_wait(business, now=datetime(2026,10,26,10)) is None


def test_bound_root_override_is_still_rejected():
    with pytest.raises(ValueError, match="BOUND_ARGUMENT_OVERRIDE"):
        _wrapper()._business_args(["--source-r", "/other"])


def test_cheap_weekend_gate_keeps_noop_semantics():
    result = _wrapper()._natural_wait(["--origin", "natural_scheduler"], now=datetime(2026,10,25,10))
    assert result["status"] == "NOOP_SKIP"
    assert result["reason"] == "NON_TRADING_DAY"
    assert result["trade_date"] == "20261025"
    assert result["receipt_published"] is False


def test_graph_reader_root_is_separate_from_api_store(monkeypatch, tmp_path):
    from apps.api.v35_api import runtime_graph_router as router
    seen = []
    monkeypatch.setattr(router, "RuntimeGraphService", lambda root: seen.append(root) or SimpleNamespace())
    api_root, graph_root = tmp_path / "v4-data", tmp_path / "v35-data"
    monkeypatch.setenv("V35_RUNTIME_GRAPH_DATA_ROOT", str(graph_root))
    router.create_runtime_graph_router(api_root)
    assert seen == [graph_root]
    assert api_root == tmp_path / "v4-data"
    monkeypatch.delenv("V35_RUNTIME_GRAPH_DATA_ROOT")
    router.create_runtime_graph_router(api_root)
    assert seen[-1] == api_root
    monkeypatch.setenv("V35_RUNTIME_GRAPH_DATA_ROOT", "relative/data")
    with pytest.raises(ValueError, match="MUST_BE_ABSOLUTE"):
        router.create_runtime_graph_router(api_root)


def _child(code: str, app: Path, *args):
    env = dict(os.environ, PYTHONPATH=str(app), PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    result = subprocess.run([sys.executable, "-B", "-P", "-c", code, *map(str,args)], env=env,
                            cwd=CASE, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_graph_producer_consumer_same_bytes_and_360_second_expiry(tmp_path):
    """Actual service collect; HTTP transport is fixture-only; no heartbeat writes."""
    producer = _child('''
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,sys,hashlib
from infrastructure.runtime_graph.service import RuntimeGraphService
root=Path(sys.argv[1]); now=datetime(2026,10,26,18,0,tzinfo=timezone(timedelta(hours=8)))
s=RuntimeGraphService(root,now_provider=lambda:now)
kwargs=dict(http_get=lambda path:{},read_text=lambda path:'{}',path_exists=lambda path:False,path_lstat=lambda path:None)
a=s.collect('20261026',now=now,**kwargs)
b=s.collect('20261026',now=now+timedelta(seconds=300),**kwargs)
p=root/'runtime_graph/snapshots/current.json'
print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'second_events':b.event_count,'second_published':b.snapshot_published,'generated_at':b.state.payload['generated_at'],'freshness':s.contract['freshness_seconds']}))
''', GRAPH, tmp_path / "data")
    assert producer["second_published"] is True
    assert producer["second_events"] == 0
    consumer = _child('''
from datetime import datetime,timedelta
from pathlib import Path
import json,sys,hashlib
from infrastructure.runtime_graph.service import RuntimeGraphService
root=Path(sys.argv[1]); p=root/'runtime_graph/snapshots/current.json'; before=p.read_bytes()
base=datetime.fromisoformat(json.loads(before)['generated_at'])
at360=RuntimeGraphService(root,now_provider=lambda:base+timedelta(seconds=360)).snapshot()
at361=RuntimeGraphService(root,now_provider=lambda:base+timedelta(seconds=361)).snapshot()
assert p.read_bytes()==before
print(json.dumps({'at360':at360.get('snapshot_identity'),'at361':at361,'sha256':hashlib.sha256(before).hexdigest()}))
''', API, tmp_path / "data")
    assert consumer["at360"]["snapshot_sha256"] == producer["sha256"]
    assert consumer["sha256"] == producer["sha256"]
    assert consumer["at361"]["reason"] == "SNAPSHOT_STALE"
    assert producer["freshness"]["runtime_snapshot"] == 360
    assert producer["freshness"]["page_receipt"] == 900


def test_hk_deadline_current_algorithm_and_no_producer(tmp_path):
    result = _child('''
import json,sys,contextlib,io
from pathlib import Path
from ops import run_stage_center_nodes as m
from stage_center import selection
active=Path(sys.argv[1]); out=Path(sys.argv[2]); conf=m._load_config(active/'stage_center_tick_config.json')
assert selection.HK_FULL_POOL_ALGORITHM_SHA256 in selection.ALGORITHM_SHA_ALLOWLIST
def forbidden(*a,**kw): raise AssertionError('producer invoked in deadline-only')
m._build_runner=forbidden; m.run_nodes=forbidden
import ops.run_stage_center_tick as tick
calls=[]
tick.deadline_chain_check=lambda raw,selection_root,date,stage: calls.append((str(raw),str(selection_root),date,stage)) or {'status':'DEADLINE_CHAIN_READY','provider_invocations':0,'business_writes':0}
m._calendar_gate=lambda *a,**kw:{'status':'ELIGIBLE'}
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
 code=m.main(['--config',str(active/'stage_center_tick_config.json'),'--deadline-only','--trade-date','20261026','--evaluated-at','2026-10-26T15:56:00+08:00'])
print(json.dumps({'code':code,'calls':calls,'algorithm_sha256':selection.HK_FULL_POOL_ALGORITHM_SHA256,'raw_root':conf['raw_root'],'selection_root':conf['selection_root']}))
''', STAGE, STAGE, tmp_path)
    assert result["code"] == 0
    assert result["calls"] == [[result["raw_root"], result["selection_root"], "20261026", "STAGE_1545_1555"]]
    assert result["algorithm_sha256"] == "f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e"


def test_prepared_bindings_keep_dates_roots_and_scoped_cadence():
    import plistlib
    directory = CASE / "integration/proposed"
    daily = plistlib.loads((directory / "com.lexi.review-core.daily.plist").read_bytes())
    assert "StartInterval" not in daily
    assert daily["RunAtLoad"] is True
    assert daily["StartCalendarInterval"] == [{"Hour":20,"Minute":25},{"Hour":20,"Minute":40},{"Hour":21,"Minute":5}]
    graph = plistlib.loads((directory / "com.lexi.v35.runtime-graph.plist").read_bytes())
    assert graph["StartInterval"] == 300
    assert "com.lexi.v35.local/state/data" in graph["ProgramArguments"][-1]
    api = plistlib.loads((directory / "com.lexi.v35.api-only.plist").read_bytes())
    assert api["EnvironmentVariables"]["V35_RUNTIME_GRAPH_DATA_ROOT"].endswith("com.lexi.v35.local/state/data")
    assert api["EnvironmentVariables"]["V4_TASK_STATUS_LEDGER_ROOT"].endswith("com.lexi.v35.local/state/dispatcher")
    assert api["EnvironmentVariables"]["V4_TASK_STATUS_EVIDENCE_ROOT"].endswith("com.lexi.v35.local/state/data")
    assert any(arg.endswith("com.lexi.v4.local/state/data") and arg.startswith("V35_DATA_ROOT=") for arg in api["ProgramArguments"])
    deadline = plistlib.loads((directory / "com.lexi.stage-center.hk-deadline.plist").read_bytes())
    original = plistlib.loads((CASE / "integration/baseline/com.lexi.stage-center.hk-deadline.plist").read_bytes())
    assert deadline["StartCalendarInterval"] == original["StartCalendarInterval"]
    assert deadline["ProgramArguments"][-1] == "--deadline-only"
    assert deadline["WorkingDirectory"] == str(STAGE)
    assert deadline["EnvironmentVariables"]["STAGE_CENTER_CONFIG"] == str(STAGE / "stage_center_tick_config.json")


def test_cas_exact_backup_rollback_and_drift_refusal(tmp_path):
    sys.path.insert(0, str(CASE))
    from integrate_batch1 import cas_replace
    target = tmp_path / "fixture.plist"
    before, after = b"baseline", b"candidate"
    target.write_bytes(before)
    cas_replace(target, hashlib.sha256(before).hexdigest(), after, tmp_path / "backup")
    assert target.read_bytes() == after
    assert (tmp_path / "backup").read_bytes() == before
    cas_replace(target, hashlib.sha256(after).hexdigest(), before, tmp_path / "rollback-backup")
    assert target.read_bytes() == before
    with pytest.raises(ValueError, match="CAS_SHA_MISMATCH"):
        cas_replace(target, "0" * 64, after, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_integration_wait_never_kills_running_job():
    sys.path.insert(0, str(CASE))
    from integrate_batch1 import wait_natural_exit
    commands = []
    def running(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="state = running\n\tpid = 12345\n", stderr="")
    with pytest.raises(RuntimeError, match="HEALTHY_PROCESS_STILL_RUNNING"):
        wait_natural_exit("fixture.job", 0, run=running)
    assert len(commands) == 1
    assert commands[0][1] == "print"


def test_integration_requires_independent_hash_bound_pass():
    sys.path.insert(0, str(CASE))
    from integrate_batch1 import reviewed_inputs
    receipt = {"verdict":"PASS", "writer":"fixture-writer", "reviewer":"fixture-reviewer"}
    for key, relative in [("scope_sha256","BATCH1_SCOPE.json"), ("binding_plan_sha256","integration/BINDING_PLAN.json"),
                          ("source_diff_manifest_sha256","SOURCE_DIFF_MANIFEST.json")]:
        receipt[key] = hashlib.sha256((CASE / relative).read_bytes()).hexdigest()
    plan = reviewed_inputs(receipt)
    assert plan["main_scheduler_reload"] is False
    assert next(op for op in plan["operations"] if op["role"] == "api")["source_only"] is True
    with pytest.raises(ValueError, match="INDEPENDENT_PASS_REQUIRED"):
        reviewed_inputs({**receipt, "reviewer":"fixture-writer"})
    with pytest.raises(ValueError, match="REVIEWED_INPUT_DRIFT"):
        reviewed_inputs({**receipt, "binding_plan_sha256":"0"*64})


def test_partial_binding_rollback_restores_only_applied_members(tmp_path):
    sys.path.insert(0, str(CASE))
    from integrate_batch1 import switch_bindings
    operations = []
    for index in range(2):
        before, after = b"original", b"proposed"
        baseline, proposed, target = [tmp_path / f"{name}-{index}" for name in ("before", "after", "target")]
        baseline.write_bytes(before)
        proposed.write_bytes(after)
        target.write_bytes(after if index == 0 else before)
        operations.append({"label":str(index), "target":str(target), "baseline":str(baseline), "proposed":str(proposed),
                           "expected_sha256":hashlib.sha256(before).hexdigest(), "proposed_sha256":hashlib.sha256(after).hexdigest(),
                           "wait_for_natural_exit":False})
    result = switch_bindings({"operations":operations}, rollback=True, wait_seconds=0, journal_root=tmp_path)
    assert [op["label"] for op in result["operations"]] == ["0"]
    assert all(Path(op["target"]).read_bytes() == b"original" for op in operations)
    assert result["service_actions"] == 0


def _activation_fixture(tmp_path):
    import plistlib
    operations=[]
    for role in ["daily","graph","deadline"]:
        target=tmp_path/(role+'.plist')
        payload={'WorkingDirectory':str(tmp_path/role),'ProgramArguments':['python','-B',str(tmp_path/role/'wrapper.py')]}
        raw=plistlib.dumps(payload);target.write_bytes(raw)
        operations.append({'role':role,'label':'fixture.'+role,'target':str(target),'proposed':str(target),
                           'baseline':str(target),'proposed_sha256':hashlib.sha256(raw).hexdigest(),
                           'expected_sha256':hashlib.sha256(raw).hexdigest()})
    return {'operations':operations}


def test_activation_disables_then_drains_before_bootout_and_reads_loaded_binding(tmp_path):
    sys.path.insert(0, str(CASE))
    from activate_one_shots import activate
    plan=_activation_fixture(tmp_path); commands=[];loaded={op['label']:True for op in plan['operations']}
    def run(command,**kwargs):
        args=command[1:];commands.append(args);verb=args[0]
        if verb=='print-disabled': return SimpleNamespace(returncode=0,stdout='{}',stderr='')
        label=args[1].split('/')[-1]
        if verb=='print':
            if not loaded[label]:return SimpleNamespace(returncode=113,stdout='',stderr='Could not find service')
            role=label.split('.')[-1]
            interval='run interval = 300 seconds\n' if role=='graph' else ''
            return SimpleNamespace(returncode=0,stdout='state = waiting\n'+interval+str(tmp_path/role)+'\n'+str(tmp_path/role/'wrapper.py'),stderr='')
        if verb=='bootout': loaded[label]=False
        if verb=='bootstrap': loaded['fixture.'+Path(args[2]).stem]=True
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    result=activate(plan,rollback=False,wait_seconds=0,run=run,journal_root=tmp_path,
                    api_receipt={'fixture':True},api_validator=lambda receipt,plan,run:{'fixture_gate':'validated'})
    assert result['status']=='LOADED_ONE_SHOT_BINDINGS_VERIFIED_NATURAL_SLOT_UNVERIFIED'
    first_bootout=next(i for i,c in enumerate(commands) if c[0]=='bootout')
    assert sum(c[0]=='disable' for c in commands[:first_bootout])==3
    assert len(result['waits'])==3
    assert result['signals_sent']==0
    assert result['main_scheduler_actions']==0 and result['api_actions']==0


def test_activation_timeout_restores_enabling_and_never_bootouts(tmp_path):
    sys.path.insert(0, str(CASE))
    from activate_one_shots import activate
    plan=_activation_fixture(tmp_path);commands=[]
    def running(command,**kwargs):
        args=command[1:];commands.append(args)
        text='{}' if args[0]=='print-disabled' else 'state = running\n pid = 12345\n'
        return SimpleNamespace(returncode=0,stdout=text,stderr='')
    with pytest.raises(RuntimeError,match='HEALTHY_PROCESS_STILL_RUNNING'):
        activate(plan,rollback=False,wait_seconds=0,run=running,journal_root=tmp_path,
                 api_receipt={'fixture':True},api_validator=lambda receipt,plan,run:{'fixture_gate':'validated'})
    assert sum(c[0]=='disable' for c in commands)==3
    assert sum(c[0]=='enable' for c in commands)==3
    assert not any(c[0] in ('bootout','bootstrap','kickstart') for c in commands)


def test_first_batch_cli_excludes_source_only_api_from_live_actions():
    sys.path.insert(0, str(CASE))
    from integrate_batch1 import one_shot_plan
    plan=json.loads((CASE/'integration/BINDING_PLAN.json').read_text())
    limited=one_shot_plan(plan)
    assert {r['component'] for r in limited['releases']} == {'graph','daily'}
    assert {r['role'] for r in limited['operations']} == {'graph','daily','deadline'}
