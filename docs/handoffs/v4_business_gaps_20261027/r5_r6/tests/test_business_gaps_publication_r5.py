import hashlib
import importlib
import sys
from pathlib import Path

import pytest

ROOT=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027/operations/two_pool_upstream_r5/fupan_candidate_pool_r3')
FLAGS={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}

@pytest.fixture
def store_module():
    for k in list(sys.modules):
        if k=='review_core' or k.startswith('review_core.'):del sys.modules[k]
    sys.path.insert(0,str(ROOT))
    try:yield importlib.import_module('review_core.pool_store')
    finally:sys.path.pop(0)

def artifact(status,rows):
    return {'status':status,'rows':rows,'role':'test-role','target_date':'20261028','source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,**FLAGS}

def binding(store):
    verified=store.read_verified('20261028','test-role')
    path=store.current_path('20261028','test-role')
    return {'current_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**{k:verified[k] for k in ('run_id','artifact_sha256','manifest_sha256','receipt_sha256')}}

def test_only_explicit_matching_failed_slot_can_be_recovered(store_module,tmp_path):
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact('CANNOT_CONFIRM',[]))
    previous=store.read_verified('20261028','test-role'); files=[previous[k].read_bytes() for k in ('artifact_path','manifest_path','receipt_path')];b=binding(store)
    with pytest.raises(store_module.ConflictError):store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]))
    for key in b:
        wrong=dict(b);wrong[key]='wrong'
        with pytest.raises(store_module.ConflictError):store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]),expected_previous=wrong)
    assert binding(store)==b
    result=store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]),expected_previous=b)
    assert result['status']=='PARTIAL' and store.read_verified('20261028','test-role')['current']['previous_failed']==b
    assert files==[previous[k].read_bytes() for k in ('artifact_path','manifest_path','receipt_path')]
    with pytest.raises(store_module.ConflictError):store.publish('20261028','test-role',artifact('READY',[{'x':2}]),expected_previous=binding(store))

def test_failed_pointer_verification_inverse_cas_retains_old_and_new_run(store_module,tmp_path,monkeypatch):
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact('CANNOT_CONFIRM',[]));b=binding(store)
    old=store.current_path('20261028','test-role').read_bytes();original=store._verify_current;calls=0
    def fail_attempt(date,role):
        nonlocal calls
        calls+=1
        if calls==2:raise store_module.StoreError('injected verification failure')
        return original(date,role)
    monkeypatch.setattr(store,'_verify_current',fail_attempt)
    with pytest.raises(store_module.StoreError,match='injected'):store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]),expected_previous=b)
    assert store.current_path('20261028','test-role').read_bytes()==old
    assert len(list((tmp_path/'runs'/'20261028'/'test-role').iterdir()))==2

def test_failed_verification_with_unknown_current_never_overwrites(store_module,tmp_path,monkeypatch):
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact('CANNOT_CONFIRM',[]));b=binding(store)
    original=store._verify_current;calls=0;path=store.current_path('20261028','test-role')
    def change_current(date,role):
        nonlocal calls
        calls+=1
        if calls==2:
            path.write_bytes(b'UNKNOWN')
            raise store_module.StoreError('injected concurrent mutation')
        return original(date,role)
    monkeypatch.setattr(store,'_verify_current',change_current)
    with pytest.raises(store_module.StoreError,match='inverse CAS failed'):store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]),expected_previous=b)
    assert path.read_bytes()==b'UNKNOWN'

@pytest.fixture
def control():
    root=Path(__file__).resolve().parents[1]/'deliveries/v4_business_gaps_20261027/control'
    sys.path.insert(0,str(root))
    try:
        for k in ('prepare','controller'):sys.modules.pop(k,None)
        prep=importlib.import_module('prepare');controller=importlib.import_module('controller')
        yield prep,controller
    finally:sys.path.pop(0)

def test_r5_overlay_is_single_projection_and_rejects_scope_drift(control):
    prep,_=control
    overlays={'main':[],'api':[{'path':'infrastructure/review_core_stage7_pool_source.py'}],'collector':[],'stage':[]}
    prep.validate_mode_overlay(prep.R5_MODE,overlays)
    for bad in (dict(overlays, api=[]),dict(overlays,api=[{'path':'apps/api/v35_api/app.py'}]),dict(overlays,main=[{'path':'x'}])):
        with pytest.raises(ValueError):prep.validate_mode_overlay(prep.R5_MODE,bad)

def test_r5_rejects_unchanged_identity_or_plist_drift(control):
    prep,controller=control;rows=[];base={};components={}
    for key,label in prep.LABELS.items():
        old='/release/'+key+'/app';plist=str(Path.home()/'Library/LaunchAgents'/(label+'.plist'))
        base[key]={'app_root':old,'manifest':str(Path(old).parent/'manifest'),'manifest_sha256':'m','application_inventory_sha256':'i','plist_sha256':'p'}
        unchanged=key in prep.R4_UNCHANGED
        components[key]={'candidate_app':old if unchanged else old+'-new','release_root':str(Path(old).parent) if unchanged else '/new/'+key,'path':base[key]['manifest'],'sha256':'m','application_inventory_sha256':'i'}
        rows.append({'component':key,'label':label,'plist':plist,'before_sha256':'p','after_sha256':'p' if unchanged else 'n'})
    plan={'scope':prep.SCOPE,'control_mode':prep.R5_MODE,'operations':rows,'base':base,'components':components,**FLAGS}
    controller.require_scope(plan)
    components['main']['application_inventory_sha256']='changed'
    with pytest.raises(ValueError,match='UNCHANGED_IDENTITY_DRIFT'):controller.require_scope(plan)

@pytest.mark.parametrize('old_status,old_rows',[('READY',[{'x':1}]),('PARTIAL',[{'x':1}]),('CANNOT_CONFIRM',[{'x':1}])])
def test_recovery_never_replaces_nonfailed_or_nonempty(store_module,tmp_path,old_status,old_rows):
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact(old_status,old_rows));old=binding(store)
    with pytest.raises(store_module.ConflictError):store.publish('20261028','test-role',artifact('PARTIAL',[{'x':2}]),expected_previous=old)
    assert binding(store)==old

def test_recovery_rejects_new_unsafe_or_wrong_identity(store_module,tmp_path):
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact('CANNOT_CONFIRM',[]));old=binding(store)
    for key,value in [('target_date','20261029'),('role','other'),('stage_selection_eligible',True),('production_allowed',True)]:
        bad=artifact('PARTIAL',[{'x':1}]);bad[key]=value
        with pytest.raises(store_module.StoreError):store.publish('20261028','test-role',bad,expected_previous=old)
        assert binding(store)==old

def test_both_original_publishers_forward_explicit_binding(monkeypatch):
    for name in list(sys.modules):
        if name=='review_core' or name.startswith('review_core.'):del sys.modules[name]
    sys.path.insert(0,str(ROOT))
    try:
        for module_name,publisher,builder,args in [('review_core.fupan_pool','publish_fupan_review_pool','build_fupan_review_pool',('/store','20261027','20261028','/bundle','/shared')),('review_core.stage7_pool','publish_stage7_replay_pool','build_stage7_replay_pool',('/store','20261027','20261028','/shared'))]:
            mod=importlib.import_module(module_name);seen={}
            class FakeStore:
                def __init__(self,root):pass
                def publish(self,*args,**kwargs):seen.update(kwargs);return kwargs
            monkeypatch.setattr(mod,'PoolStore',FakeStore);monkeypatch.setattr(mod,builder,lambda *args,**kwargs:{'status':'PARTIAL','row_count':1})
            getattr(mod,publisher)(*args,expected_previous={'current_sha256':'expected'})
            assert seen['expected_previous']=={'current_sha256':'expected'}
    finally:sys.path.pop(0)

def test_r5_action_guard_rejects_unchanged_service(control):
    import os
    prep,ctl=control;c=object.__new__(ctl.Controller);c.p={'control_mode':prep.R5_MODE};c.phase='FORWARD';c.uncertain=False;c.attempted=set()
    for key in prep.R4_UNCHANGED:
        with pytest.raises(RuntimeError,match='SERVICE_ACTION_OUTSIDE_FIXED_SCOPE'):
            c.command(['bootout',f'gui/{os.getuid()}/'+prep.LABELS[key]])

def test_r5_recovery_never_unloads_unchanged(control):
    from types import SimpleNamespace
    prep,ctl=control;c=object.__new__(ctl.Controller);c.p={'control_mode':prep.R5_MODE}
    states={key:({'loaded':True,'version':'UNCHANGED','disk':'UNCHANGED'} if key in prep.R4_UNCHANGED else {'loaded':True,'version':'NEW','disk':'NEW'}) for key in prep.LABELS}
    actions=[];c.binding=lambda key,old:states[key];c.row=lambda key:{'component':key,'label':prep.LABELS[key]}
    c.unload=lambda key:actions.append(('unload',key));c.bootstrap=lambda key:actions.append(('bootstrap',key));c.record=lambda *args,**kwargs:None
    c.op=SimpleNamespace(install_plist=lambda row,rollback:actions.append(('install',row['component'])),label_state=lambda label:42)
    c.wait_verify=lambda old:None;c.cas=lambda **kw:None;c.verify_graph=lambda old:None;c.verify=lambda old:'ok'
    assert c.rollback({})=='ok'
    assert actions==[('unload','collector'),('install','collector'),('unload','api'),('install','api')]
    states['stage']={'loaded':False,'disk':'UNCHANGED'};actions.clear()
    with pytest.raises(RuntimeError,match='UNCHANGED_SERVICE_NOT_BOUND'):c.rollback({})
    assert actions==[]

def test_existing_r4_and_full_overlay_contracts_preserved(control):
    prep,_=control
    paths={'apps/api/v35_api/app.py','domains/_preselection_parts/source_validation.py','stage_center/consumer.py','domains/runtime_graph_evidence.py','infrastructure/runtime_graph/current.py'}
    old={'main':[],'api':[{'path':p} for p in paths],'collector':[],'stage':[]}
    prep.validate_mode_overlay(prep.R4_MODE,old)
    with pytest.raises(ValueError,match='R4_OVERLAY_SCOPE'):prep.validate_mode_overlay(prep.R4_MODE,dict(old,api=[]))
    prep.validate_mode_overlay('FULL',{key:[{'path':'x'}] for key in ('main','api','collector','stage')})

def test_recovery_history_is_bound_to_new_manifest(store_module,tmp_path):
    import json
    store=store_module.PoolStore(tmp_path);store.publish('20261028','test-role',artifact('CANNOT_CONFIRM',[]));old=binding(store)
    store.publish('20261028','test-role',artifact('PARTIAL',[{'x':1}]),expected_previous=old)
    path=store.current_path('20261028','test-role');pointer=json.loads(path.read_bytes());pointer['previous_failed']['artifact_sha256']='0'*64;path.write_text(json.dumps(pointer))
    with pytest.raises(store_module.StoreError,match='history mismatch'):store.read_verified('20261028','test-role')
