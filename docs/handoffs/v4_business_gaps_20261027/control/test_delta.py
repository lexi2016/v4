"""Direct new control boundaries only; no live subprocess/service/lock calls."""
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace

import pytest

HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
import prepare
import controller
spec=importlib.util.spec_from_file_location('business_operator',HERE/'publication_operator.py');operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    monkeypatch.setattr(controller.subprocess,'run',lambda *a,**k:pytest.fail('no live subprocess allowed in fixtures'))


def stage_plist(key):
    label=prepare.LABELS[key]
    return plistlib.loads((Path.home()/'Library/LaunchAgents'/(label+'.plist')).read_bytes())


@pytest.mark.parametrize('key',['stage','a_precapture'])
def test_actual_stage_plist_rewrite_keeps_every_original_schedule_and_actual_launcher(key):
    before=stage_plist(key);old=before['WorkingDirectory'];new='/candidate/business-stage/app'
    after=prepare.rewrite_owner(before,old,new,'a'*64)
    prepare.validate_stage_plist(before,after,old,new,key)
    assert before['StartCalendarInterval']==after['StartCalendarInterval']
    assert after['ProgramArguments'][2]==new+'/ops/run_stage_center_nodes.py'
    assert after['ProgramArguments'][4]==new+'/stage_center_tick_config.json'
    assert '--node' in after['ProgramArguments'] if key=='a_precapture' else '--node' not in after['ProgramArguments']


@pytest.mark.parametrize('defect',['launcher','config','schedule','node'])
def test_stage_wrong_actual_binding_or_schedule_is_rejected(defect):
    before=stage_plist('a_precapture');old=before['WorkingDirectory'];new='/candidate/stage/app'
    after=prepare.rewrite_owner(before,old,new,'a'*64)
    if defect=='launcher':after['ProgramArguments'][2]=old+'/ops/run_stage_center_nodes.py'
    elif defect=='config':after['ProgramArguments'][4]=old+'/stage_center_tick_config.json'
    elif defect=='schedule':after['StartCalendarInterval'][0]['Minute']=25
    else:after['ProgramArguments'][-1]='STAGE_0925'
    with pytest.raises(ValueError):prepare.validate_stage_plist(before,after,old,new,'a_precapture')


def plan_scope():
    return dict(scope=prepare.SCOPE,operations=[dict(component=k,label=v,plist=str(Path.home()/'Library/LaunchAgents'/(v+'.plist'))) for k,v in prepare.LABELS.items()],production_allowed=False,buy_gate_updated=False,orders_sent=False)


def test_only_exact_five_services_and_no_deadline_action():
    p=plan_scope();controller.require_scope(p)
    bad=deepcopy(p);bad['operations'][-1]['label']='com.lexi.stage-center.hk-deadline'
    with pytest.raises(ValueError):controller.require_scope(bad)
    bad=deepcopy(p);bad['operations'].pop()
    with pytest.raises(ValueError):controller.require_scope(bad)


@pytest.mark.parametrize('pid',[0,42])
def test_stage_existing_child_is_never_stopped_or_signaled(pid):
    obj=object.__new__(controller.Controller);obj.p={'base':{'stage':{'app_root':'/old/app'}},'components':{'stage':{'release_root':'/new'}}}
    obj.row=lambda key:{'label':key};obj.op=SimpleNamespace(label_state=lambda label:pid);obj.g=SimpleNamespace(processes=lambda:{})
    if pid:
        with pytest.raises(RuntimeError,match='PENDING_ORIGINAL_STAGE_ACTIVE'):obj.stage_idle()
    else:obj.stage_idle()


def observed_case(tmp_path):
    now=datetime.now(timezone.utc);config={'main':{'app_root':'/main/app'},'native_reader_roots':{'pdf_data_root':'/exact/pdf'}}
    for key in ('graph_root','ledger_root','opening_root','stage_selection_root','stage_receipt_root','daily_receipt_root'):config[key]='/exact/'+key
    config_path=tmp_path/'config.json';config_path.write_text(json.dumps(config));manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'app_files':[{'path':'domains/runtime_graph_evidence.py','sha256':'a'*64}]}))
    p={'operations':[{'component':'main','after_sha256':'m'},{'component':'api','after_sha256':'p'}],
       'components':{'api':{'path':str(manifest),'release_root':'/api','sha256':'i'}},'config_path':str(config_path),'config_sha256':'c'}
    proof={'schema_version':'v4.runtime_graph_authority.v1','business_date':now.astimezone(operator.ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'),
       'observed_at':now.isoformat(),'proof_runtime':{'pid':1,'module_file':'/api/app/domains/runtime_graph_evidence.py','module_sha256':'a'*64},
       'runtime_binding':{'status':'VERIFIED','current_runtime_verified':True,'pid':2,'launcher':'/main/app/ops/launch_v35_macos_scheduler.sh'},
       'authority_identity':config['main'],'config_sha256':'c','reader_bindings':{k:v for k,v in config.items() if k!='main'},
       'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    return p,dict(proof=proof,api_pid=1,main_pid=2,api_plist_sha256='p',main_plist_sha256='m',api_manifest_sha256='i',config_sha256='c'),now


@pytest.mark.parametrize('defect',[None,'missing','wrong','extra'])
def test_native_reader_roots_extend_exact_original_operator_binding(tmp_path,defect):
    plan,observed,now=observed_case(tmp_path)
    if defect=='missing':observed['proof']['reader_bindings'].pop('native_reader_roots')
    elif defect=='wrong':observed['proof']['reader_bindings']['native_reader_roots']['pdf_data_root']='/wrong'
    elif defect=='extra':observed['proof']['reader_bindings']['native_reader_roots']['invented']='/wrong'
    if defect is None:assert operator.validate_api_observation(plan,observed,now=now)
    else:
        with pytest.raises(ValueError,match='API_READER_ROOT_DRIFT'):operator.validate_api_observation(plan,observed,now=now)


def test_missing_fresh_handoff_refuses_before_candidate_or_subprocess(tmp_path):
    path=tmp_path/'handoff.json';path.write_text(json.dumps({'status':'PENDING'}))
    with pytest.raises(RuntimeError,match='PENDING_EXPLICIT_LATEST_OWNER_HANDOFF'):
        prepare.prepare(tmp_path/'candidate',handoff_path=path,handoff_sha=prepare.sha(path))
    assert not (tmp_path/'candidate').exists()


def test_real_main_legacy_index_adds_only_three_authorized_missing_modules(tmp_path):
    case=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027')
    root=case/'testing/main_closure_r2/app'
    if not root.is_dir():pytest.skip('local full-current-parent fixture excluded from source capsule')
    notes=json.loads((case/'controller/PUBLICATION_REUSE_NOTES.json').read_bytes())
    helper=prepare.module('manifest_direct_original_helper',notes['helpers']['integration']['path'])
    baseline=json.loads(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/ui-pdf-publication-20261027-r2-main/release-manifest.json').read_bytes())
    added={r['path'] for r in json.loads((case/'baseline/US_MAPPING_THREE_WAY_R1.json').read_bytes()) if r['before_sha256'] is None}
    assert len(added)==3
    result=prepare.manifest(helper,root,tmp_path/'target',baseline,component='main',new_paths=added)
    assert set(result['files'])==set(baseline['files'])|{'app/'+path for path in added}
    assert result['files']=={'app/'+row['path']:row['sha256'] for row in result['app_files']}
    assert result['schema_version']==baseline['schema_version']
    with pytest.raises(ValueError,match='MAIN_LEGACY_INDEX_UNAUTHORIZED_KEY_SET_DRIFT'):
        prepare.manifest(helper,root,tmp_path/'target',baseline,component='main')


def test_standard_api_identity_scope_keeps_original_verifier_and_rejects_legacy(tmp_path):
    contract=tmp_path/'contract';contract.write_text('contract')
    manifest=tmp_path/'manifest';manifest.write_text(json.dumps({'schema_version':'v4.release_candidate.v1'}))
    original=object();helper=SimpleNamespace(MODULE_CONTRACT_PATH=contract,_release_identity=original)
    base={'manifest':str(manifest),'manifest_sha256':prepare.sha(manifest)};pin={'path':str(contract),'sha256':prepare.sha(contract)}
    with prepare.api_identity_scope(helper,base,pin):assert helper._release_identity is original
    manifest.write_text(json.dumps({'schema_version':'legacy'}));base['manifest_sha256']=prepare.sha(manifest)
    with pytest.raises(ValueError,match='STANDARD_CURRENT_API_REQUIRED'):
        with prepare.api_identity_scope(helper,base,pin):pytest.fail('legacy falsely promoted')


def test_explicit_parent_execution_hold_stops_before_window_or_guard(tmp_path,monkeypatch):
    plan=tmp_path/'PLAN.json';plan.write_text('{}');review=tmp_path/'review.json'
    obj=object.__new__(controller.Controller);obj.path=plan
    obj.p={'prepare_sha256':'p','frozen_inputs':{'source_freeze':{'sha256':'s'}},'handoff':{'path':'not-read','sha256':'h'}}
    review.write_text(json.dumps({'verdict':'PASS','deployment_plan_sha256':prepare.sha(plan),'controller_sha256':prepare.sha(controller.__file__),'prepare_sha256':'p','source_freeze_sha256':'s'}))
    monkeypatch.setattr(prepare,'handoff_ready',lambda *a:{'deployment_executable':False})
    obj.window=lambda:pytest.fail('explicit hold reached execution window')
    with pytest.raises(RuntimeError,match='PENDING_PARENT_EXECUTION_AUTHORITY'):
        obj._execute(review,prepare.sha(review))


def test_operator_copy_has_no_standalone_action_entry():
    import runpy
    with pytest.raises(SystemExit,match='HELPER_ONLY_USE_REVIEWED_CONTROLLER'):
        runpy.run_path(str(HERE/'publication_operator.py'),run_name='__main__')
