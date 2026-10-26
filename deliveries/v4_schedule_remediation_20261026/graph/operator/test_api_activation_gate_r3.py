from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import os
import plistlib
import sys

import pytest

CASE=Path(__file__).resolve().parent
sys.path.insert(0,str(CASE))
import api_activation_gate as gate
import activate_one_shots as lifecycle

NOW=datetime(2026,10,26,12,0,tzinfo=timezone.utc)


@pytest.fixture
def context(tmp_path,monkeypatch):
    root=tmp_path/'gate-case';root.mkdir();(root/'integration').mkdir()
    releases=root/'releases';app=releases/'combined-fixture-r3/app';app.mkdir(parents=True)
    hashes={}
    for module,relative in {**gate.MODULES,'contract':gate.CONTRACT}.items():
        path=app/relative;path.parent.mkdir(parents=True,exist_ok=True)
        raw=json.dumps({'freshness_seconds':{'runtime_snapshot':360}}).encode() if module=='contract' else ('reviewed '+module).encode()
        path.write_bytes(raw);hashes[relative]=gate.digest(raw)
    manifest={'release_id':app.parent.name,'app_files':[{'path':p,'sha256':sha} for p,sha in hashes.items()]}
    manifest_path=app.parent/'release-manifest.json';manifest_path.write_text(json.dumps(manifest))
    expected=root/'api-expected-release-manifest.json';expected.write_bytes(manifest_path.read_bytes())
    plist=root/'api.plist';graph_root=str(root/'v35-data')
    env={'V35_APP_ROOT':str(app),'V35_RELEASE_ID':app.parent.name,'V35_RELEASE_MANIFEST_PATH':str(manifest_path),
         'V35_RELEASE_MANIFEST_SHA256':gate.digest(manifest_path.read_bytes()),'V35_RUNTIME_GRAPH_DATA_ROOT':graph_root}
    plist.write_bytes(plistlib.dumps({'Label':gate.API_LABEL,'EnvironmentVariables':env,
                                     'ProgramArguments':['/usr/bin/env',*[k+'='+v for k,v in env.items()],'/fixture/python']}))
    plan={'graph_data_root':graph_root,'releases':[{'component':'api','manifest':str(expected),'manifest_sha256':gate.digest(expected.read_bytes()),'destination':str(app.parent)}],
          'operations':[{'role':'api','proposed_sha256':gate.digest(plist.read_bytes())}]}
    (root/'integration/BINDING_PLAN.json').write_text(json.dumps(plan))
    (root/'SOURCE_DIFF_MANIFEST.json').write_text(json.dumps({'changed_files':[{'component':'api','relative_path':p,'after_sha256':sha} for p,sha in hashes.items()]}))
    body={'status':'FAIL','reason':'SEMANTIC_CONTRADICTION','runtime_identity':{
        'status':'CANNOT_CONFIRM','pid':12345,'app_root':str(app),'declared_app_root':str(app),'release_id':app.parent.name,
        'release_manifest_path':str(manifest_path),'release_manifest_sha256':gate.digest(manifest_path.read_bytes()),
        'plist_path':str(plist),'plist_sha256':gate.digest(plist.read_bytes()),
        'selected_imported_modules':[{'module':m,'path':str(app/r),'sha256':hashes[r]} for m,r in gate.MODULES.items()]}}
    ctx=SimpleNamespace(root=root,app=app,plist=plist,manifest=manifest_path,plan=plan,body=body,pid=12345,
                        env=dict(env),calls=[],second_pid=None,api_prints=0)
    def run(command,**kwargs):
        ctx.calls.append(command)
        if command[0]=='/usr/sbin/lsof':return SimpleNamespace(returncode=0,stdout=f'p{ctx.pid}\n',stderr='')
        verb=command[1]
        if verb=='print-disabled':return SimpleNamespace(returncode=0,stdout='{}',stderr='')
        if verb=='print' and command[2].endswith('/'+gate.API_LABEL):
            ctx.api_prints+=1
            pid=ctx.second_pid if ctx.second_pid is not None and ctx.api_prints>=2 else ctx.pid
            return SimpleNamespace(returncode=0,stdout=f'state = running\n pid = {pid}\n'+'\n'.join(k+'='+v for k,v in ctx.env.items()),stderr='')
        return SimpleNamespace(returncode=0,stdout='state = waiting\n',stderr='')
    ctx.run=run;ctx.http=lambda:copy.deepcopy(ctx.body)
    monkeypatch.setattr(gate,'CASE',root);monkeypatch.setattr(gate,'API_PLIST',plist);monkeypatch.setattr(gate,'RELEASE_ROOT',releases)
    observation=gate.observe_current(plan,run=run,http_read=ctx.http)
    ctx.receipt={'schema_version':gate.SCHEMA,'status':'API_VERIFIED','observed_at':NOW.isoformat(),
                 'binding_plan_sha256':gate.digest((root/'integration/BINDING_PLAN.json').read_bytes()),**observation}
    ctx.calls.clear();ctx.api_prints=0
    return ctx


def verify(ctx,receipt=None):
    return gate.verify_api_ready(receipt or ctx.receipt,ctx.plan,run=ctx.run,http_read=ctx.http,now=NOW)


def test_valid_current_binding_accepts_general_cannot_confirm_and_business_fail(context):
    result=verify(context)
    assert result['api_pid']==12345
    assert result['runtime_identity_status']=='CANNOT_CONFIRM'
    assert result['business_status']=='FAIL'
    assert {c[1] for c in context.calls if c[0]=='/bin/launchctl'}=={'print'}


def test_three_self_declared_fields_cannot_enter_gate(context):
    with pytest.raises(ValueError,match='RECEIPT_SCHEMA_INVALID'):
        verify(context,{'status':'API_VERIFIED','runtime_graph_data_root':context.plan['graph_data_root'],'runtime_snapshot_freshness_seconds':360})
    assert context.calls==[]


@pytest.mark.parametrize('missing',['observed_at','api_pid','api_service_target','api_plist_sha256','api_release_manifest_sha256','loaded_modules','runtime_graph_contract_sha256'])
def test_missing_required_fields_rejected_before_observation(context,missing):
    receipt=copy.deepcopy(context.receipt);receipt.pop(missing)
    with pytest.raises(ValueError,match='API_GATE_RECEIPT_'):
        verify(context,receipt)
    assert context.calls==[]


@pytest.mark.parametrize('offset',[-121,6])
def test_stale_or_future_receipt_rejected_before_observation(context,offset):
    receipt={**context.receipt,'observed_at':(NOW+timedelta(seconds=offset)).isoformat()}
    with pytest.raises(ValueError,match='STALE_OR_FUTURE'):verify(context,receipt)
    assert context.calls==[]


def test_naive_observation_time_rejected(context):
    with pytest.raises(ValueError,match='TIME_INVALID'):verify(context,{**context.receipt,'observed_at':'2026-10-26T12:00:00'})


def test_receipt_expiring_during_current_readback_rejected(context,monkeypatch):
    ticks=[]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            ticks.append(True)
            return NOW if len(ticks)==1 else NOW+timedelta(seconds=121)
    monkeypatch.setattr(gate,'datetime',Clock)
    with pytest.raises(ValueError,match='EXPIRED_DURING_OBSERVATION'):
        gate.verify_api_ready(context.receipt,context.plan,run=context.run,http_read=context.http)


@pytest.mark.parametrize('drift',['pid','plist','manifest','loaded_root','loaded_module','contract','listener','identity_missing','during_read'])
def test_current_drift_is_rejected(context,drift):
    if drift=='pid':context.pid=12346
    elif drift=='plist':context.plist.write_bytes(context.plist.read_bytes()+b'\n')
    elif drift=='manifest':context.manifest.write_bytes(context.manifest.read_bytes()+b'\n')
    elif drift=='loaded_root':context.env['V35_RUNTIME_GRAPH_DATA_ROOT']+='/wrong'
    elif drift=='loaded_module':context.body['runtime_identity']['selected_imported_modules'][-1]['sha256']='0'*64
    elif drift=='contract':(context.app/gate.CONTRACT).write_text('{"freshness_seconds":{"runtime_snapshot":90}}')
    elif drift=='listener':
        old=context.run
        context.run=lambda command,**kwargs:SimpleNamespace(returncode=0,stdout='p999\n',stderr='') if command[0]=='/usr/sbin/lsof' else old(command,**kwargs)
    elif drift=='identity_missing':context.body.pop('runtime_identity')
    else:context.second_pid=12346
    with pytest.raises(ValueError,match='API_GATE_'):verify(context)
    assert not any(c[0]=='/bin/launchctl' and c[1] in ['disable','bootout','bootstrap','enable'] for c in context.calls)


def add_one_shots(ctx):
    for role in ['graph','daily','deadline']:
        target=ctx.root/(role+'.plist');target.write_bytes(b'fixture')
        ctx.plan['operations'].append({'role':role,'label':'fixture.'+role,'target':str(target),
                                       'proposed_sha256':gate.digest(b'fixture'),'expected_sha256':gate.digest(b'fixture')})
    return ctx.plan


def test_activation_stale_receipt_has_zero_service_actions(context):
    plan=add_one_shots(context)
    receipt={**context.receipt,'observed_at':(NOW-timedelta(seconds=121)).isoformat()}
    validator=lambda receipt,plan,run:gate.verify_api_ready(receipt,plan,run=run,http_read=context.http,now=NOW)
    with pytest.raises(ValueError,match='STALE_OR_FUTURE'):
        lifecycle.activate(plan,rollback=False,wait_seconds=0,run=context.run,journal_root=context.root,
                           api_receipt=receipt,api_validator=validator)
    assert not any(c[0]=='/bin/launchctl' and c[1] in ['disable','bootout','bootstrap','enable'] for c in context.calls)


def test_api_drift_after_healthy_drain_prevents_bootout_and_restores_enabling(context):
    plan=add_one_shots(context);checks=[]
    def validator(receipt,plan,run):
        checks.append(True)
        if len(checks)==2:raise ValueError('API_GATE_RECEIPT_CURRENT_DRIFT:api_pid')
        return {'api_pid':12345}
    with pytest.raises(ValueError,match='CURRENT_DRIFT'):
        lifecycle.activate(plan,rollback=False,wait_seconds=0,run=context.run,journal_root=context.root,
                           api_receipt=context.receipt,api_validator=validator)
    verbs=[c[1] for c in context.calls if c[0]=='/bin/launchctl']
    assert len(checks)==2 and verbs.count('disable')==3 and verbs.count('enable')==3
    assert 'bootout' not in verbs and 'bootstrap' not in verbs


def test_prepare_final_composition_only_writes_metadata(tmp_path):
    import prepare_integration as prepare
    approved=Path(json.loads((CASE/'R3_SCOPE.json').read_text())['metadata_api_candidate_allowed'])
    output=tmp_path/'final-composition-metadata'
    prepare.main(['--api-candidate-root',str(approved),'--output-directory',str(output)])
    plan=json.loads((output/'BINDING_PLAN.json').read_text())
    api=next(r for r in plan['releases'] if r['component']=='api')
    assert api['source_app']==str(approved)
    manifest=json.loads(Path(api['manifest']).read_text())
    assert manifest['candidate_app_root']==str(approved)
    assert gate.digest(Path(api['manifest']).read_bytes())==api['manifest_sha256']
    rows={r['path']:r for r in manifest['app_files']}
    assert 'domains/task_status.py' in rows and 'apps/api/v35_api/a_share_lifecycle_notes.json' in rows
    proposed=plistlib.loads((output/'proposed/com.lexi.v35.api-only.plist').read_bytes())
    env=gate.effective_environment(proposed)
    assert env['V35_RELEASE_MANIFEST_SHA256']==api['manifest_sha256']
    assert env['V35_RUNTIME_GRAPH_DATA_ROOT']==plan['graph_data_root']
    assert plan['prepared_only'] is True
