from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import plistlib
import sys

import pytest

CASE=Path(__file__).resolve().parent
R4=CASE.parent/'R4'
sys.path.insert(0,str(R4))
import api_activation_gate as gate
import activate_one_shots as lifecycle
sys.path.insert(0,str(CASE))
from invoke_graph_full_context import invoke_full_plan

spec=importlib.util.spec_from_file_location('existing_gate_fixture',CASE.parent/'test_api_activation_gate_r3.py')
fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)


def test_filtered_plan_fails_without_actions_then_complete_plan_keeps_both_real_gates(tmp_path,monkeypatch):
    assert Path(gate.__file__).parent==R4 and Path(lifecycle.__file__).parent==R4
    ctx=fixture_module.context.__wrapped__(tmp_path,monkeypatch)
    graph_plist=ctx.root/'graph.plist';graph_root=str(ctx.root/'graph-app')
    graph_plist.write_bytes(plistlib.dumps({'WorkingDirectory':graph_root}))
    ctx.plan['operations'] += [
        {'role':'graph','label':'com.lexi.v35.runtime-graph','target':str(graph_plist),'proposed':str(graph_plist),
         'proposed_sha256':gate.digest(graph_plist.read_bytes()),'expected_sha256':'0'*64},
        {'role':'daily','label':'com.lexi.review-core.daily'},
        {'role':'deadline','label':'com.lexi.stage-center.hk-deadline'}]
    plan_path=ctx.root/'integration/BINDING_PLAN.json';plan_path.write_text(json.dumps(ctx.plan))
    ctx.receipt['binding_plan_sha256']=gate.digest(plan_path.read_bytes())
    base_run=ctx.run;state={'loaded':True,'interval':60};checked=[]
    def run(command,**kwargs):
        if command[0]!='/bin/launchctl' or command[1]=='print-disabled' or (command[1]=='print' and command[2].endswith('/'+gate.API_LABEL)):
            return base_run(command,**kwargs)
        ctx.calls.append(command);verb=command[1]
        if verb=='print':
            if not state['loaded']:return SimpleNamespace(returncode=113,stdout='',stderr='Could not find service')
            return SimpleNamespace(returncode=0,stdout=f"state = waiting\nrun interval = {state['interval']} seconds\n{graph_root}\n",stderr='')
        if verb=='bootout':state['loaded']=False
        if verb=='bootstrap':state.update(loaded=True,interval=300)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    def actual_gate(receipt,plan,run):
        result=gate.verify_api_ready(receipt,plan,run=run,http_read=ctx.http,now=fixture_module.NOW)
        checked.append(result)
        return result
    filtered={**ctx.plan,'operations':[op for op in ctx.plan['operations'] if op['role']=='graph']}
    with pytest.raises(ValueError,match='API_GATE_FINAL_DEPLOYMENT_CONTRACT_DRIFT'):
        lifecycle.activate(filtered,rollback=False,wait_seconds=45,run=run,journal_root=ctx.root,
                           api_receipt=ctx.receipt,api_validator=actual_gate)
    mutating={'disable','enable','bootout','bootstrap','kickstart'}
    assert not any(c[0]=='/bin/launchctl' and c[1] in mutating for c in ctx.calls)
    assert checked==[] and state=={'loaded':True,'interval':60}
    ctx.calls.clear();ctx.api_prints=0
    result=invoke_full_plan(ctx.plan,ctx.receipt,run=run,journal_root=ctx.root,api_validator=actual_gate)
    assert len(checked)==2
    assert result['api_gate_before_disable']['api_pid']==12345
    assert result['api_gate_after_drain']['api_pid']==12345
    assert result['status']=='LOADED_ONE_SHOT_BINDINGS_VERIFIED_NATURAL_SLOT_UNVERIFIED'
    assert state=={'loaded':True,'interval':300}
    changed=[c for c in ctx.calls if c[0]=='/bin/launchctl' and c[1] in mutating]
    assert [c[1] for c in changed]==['disable','bootout','enable','bootstrap']
    assert all(('com.lexi.v35.runtime-graph' in c[2]) or (c[1]=='bootstrap' and c[3]==str(graph_plist)) for c in changed)
    assert not any('review-core.daily' in ' '.join(c) or 'hk-deadline' in ' '.join(c) for c in changed)
