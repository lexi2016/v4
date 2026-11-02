"""Three owned-role cutover: in-memory launch transport and tmp plists only."""
from contextlib import nullcontext
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops import activate_runtime_main_stage_api as main
from ops.prepare_runtime_governance_publication import omitted_owner_proof, validate_transition_publication_set


@pytest.fixture
def fixed():
    value = importlib.reload(main.fixed)
    yield value
    importlib.reload(value)


def synthetic_plan(tmp_path):
    return {'roles': {role: {'label': role,
        'preimage': {'V4_APP_ROOT': str(tmp_path/'app'), 'V4_RELEASE_MANIFEST_SHA256': 'old'},
        'candidate': {'app_root': str(tmp_path/'app'), 'manifest_sha256': 'new'}} for role in ('main','stage','api')}}


def setup_switch(tmp_path, monkeypatch, fixed, plan=None):
    evidence = tmp_path / 'evidence'; evidence.mkdir(); records = {}; targets = {}
    for role, pid in (('main',101),('stage',None),('api',202)):
        path = tmp_path / (role+'.plist'); old = role.encode()+b'old'; new = role.encode()+b'new'; path.write_bytes(old)
        (evidence/(role+'.original.plist')).write_bytes(old); (evidence/(role+'.staged.plist')).write_bytes(new)
        job = {'pid':pid,'state':'running' if pid else 'not running'}
        records[role] = {'label':role,'path':str(path),'mode':path.stat().st_mode & 0o777,'original_sha256':fixed.sha(old),'staged_sha256':fixed.sha(new),'loaded':job}
        targets[role] = (role,tmp_path,'old',tmp_path,'new')
    plan = synthetic_plan(tmp_path) if plan is None else plan
    plan_path = tmp_path/'plan.json'; plan_path.write_text(json.dumps(plan))
    (evidence/'preparation.json').write_text(json.dumps({'records':records,'script_pins':{},'plan_path':str(plan_path.resolve()),
        'plan_sha256':fixed.sha(plan_path.read_bytes()),'protection':{},'data_protection':{}}))
    monkeypatch.setattr(fixed,'EVIDENCE',evidence); monkeypatch.setattr(fixed,'TARGETS',targets)
    for name,value in {'pinned':lambda *a:None,'guards':nullcontext,'loaded':lambda label,*a,**k:records[label]['loaded'],'assert_idle':lambda *a:None,'external_protection':lambda:{},'data_protection':lambda:{},'tools':lambda:None,'verify_release':lambda *a:None,'verify_forward':lambda:{}}.items(): monkeypatch.setattr(fixed,name,value)
    monkeypatch.setattr(main,'assert_main_idle',lambda *a:None); monkeypatch.setattr(main,'zero_admission',lambda *a:{})
    return records, plan_path


def test_switch_requires_the_prepared_plan_path_and_bytes(tmp_path):
    path=tmp_path/'plan.json';path.write_text('{"roles":{}}')
    prepared={'plan_path':str(path.resolve()),'plan_sha256':main.fixed.sha(path.read_bytes())}
    assert main.prepared_plan(prepared,path)=={'roles':{}}
    other=tmp_path/'other.json';other.write_text('{"roles":{"x":1}}')
    with pytest.raises(ValueError,match='ACTIVATION_PLAN_NOT_THE_PREPARED_PLAN'):
        main.prepared_plan(prepared,other)
    path.write_text('{"roles":{"changed":1}}')
    with pytest.raises(ValueError,match='ACTIVATION_PLAN_NOT_THE_PREPARED_PLAN'):
        main.prepared_plan(prepared,path)
    plan=synthetic_plan(tmp_path)
    assert main.prepared_targets(plan)=={role:(role,tmp_path,'old',tmp_path,'new') for role in ('main','stage','api')}


@pytest.mark.parametrize('failed,restored',[('main',['main']),('stage',['stage','main']),('api',['api','stage','main'])])
def test_three_role_failure_only_restores_touched_owned_roles_reverse(tmp_path,monkeypatch,fixed,failed,restored):
    records,plan_path=setup_switch(tmp_path,monkeypatch,fixed); calls=[]; raised=False
    monkeypatch.setattr(fixed,'unload',lambda role,*a:calls.append(('unload',role)))
    def start(role,raw,ownership):
        nonlocal raised
        calls.append(('start',role,raw))
        if role==failed and not raised: raised=True;raise RuntimeError('fixture failure')
        ownership[role]=records[role]['loaded'];return ownership[role]
    monkeypatch.setattr(fixed,'start',start)
    with pytest.raises(RuntimeError,match='fixture failure'):main.switch('fixture',plan_path)
    assert [row[1] for row in calls if row[0]=='start' and row[2].endswith(b'old')]==restored
    assert all(Path(row['path']).read_bytes()==role.encode()+b'old' for role,row in records.items())


def test_main_children_or_cas_drift_stop_before_any_unload(tmp_path,monkeypatch,fixed):
    records,plan_path=setup_switch(tmp_path,monkeypatch,fixed); calls=[]
    monkeypatch.setattr(fixed,'unload',lambda *a:calls.append(a))
    def busy(pid): raise ValueError('MAIN_HEALTHY_CHILDREN_ACTIVE')
    monkeypatch.setattr(main,'assert_main_idle',busy)
    with pytest.raises(ValueError,match='MAIN_HEALTHY_CHILDREN_ACTIVE'): main.switch('fixture',plan_path)
    assert not calls
    monkeypatch.setattr(main,'assert_main_idle',lambda *a:None)
    Path(records['main']['path']).write_bytes(b'foreign-change')
    with pytest.raises(ValueError,match='ACTIVE_PLIST_CAS_CHANGED'): main.switch('fixture',plan_path)
    assert not calls and Path(records['main']['path']).read_bytes()==b'foreign-change'


def test_actual_main_child_tree_rejects_healthy_descendants(monkeypatch,fixed):
    monkeypatch.setattr(fixed.subprocess,'check_output',lambda *a,**k:'101 1 Main\n102 101 healthy-worker\n103 102 worker-child\n')
    with pytest.raises(ValueError,match='MAIN_HEALTHY_CHILDREN_ACTIVE'): main.assert_main_idle(101)


def test_zero_omitted_owner_proof_and_later_matching_receipt_refusal(tmp_path,monkeypatch):
    folder=tmp_path/'receipts/live/20261101/2300';folder.mkdir(parents=True)
    path=folder/'one.dispatch-receipt.json';path.write_text(json.dumps({'release_id':'retained-owner','app_root':'/retained/app'}))
    proof=omitted_owner_proof(tmp_path,'f10-owner','/f10/app')
    assert proof['receipt_count']==1 and not proof['matching_receipts']
    path.write_text(json.dumps({'release_id':'f10-owner','app_root':'/f10/app'}))
    with pytest.raises(ValueError,match='OMITTED_MAIN_RECEIPTS_APPEARED'):main.zero_admission({'omitted_main_owner_zero_proof':proof})


@pytest.mark.parametrize('changed', ['new_receipt','changed_receipt','missing_receipt','new_publication','wrong_date'])
def test_transition_set_admission_refuses_evidence_drift(tmp_path,monkeypatch,changed):
    receipt=tmp_path/'candidate_receipt.json';receipt.write_text('{}')
    proof={'as_of':'2026-11-02T12:59:00+08:00', 'owner':{'trade_date':'20261102'},
           'matching_receipts':[{'path':'first','sha256':'a'}],
           'publications':[{'slot':'0830','publication_sha256':'b'}]}
    current=json.loads(json.dumps(proof))
    if changed=='new_receipt':current['matching_receipts'].append({'path':'second','sha256':'c'})
    if changed=='changed_receipt':current['matching_receipts'][0]['sha256']='d'
    if changed=='missing_receipt':current['matching_receipts']=[]
    if changed=='new_publication':current['publications'].append({'slot':'0900','publication_sha256':'e'})
    if changed=='wrong_date':current['owner']['trade_date']='20261103'
    monkeypatch.setattr(main,'transition_owner_proof',lambda *a,**kw:current)
    plan={'transition_owner_proof':proof,'candidate_receipt_path':str(receipt),
          'candidate_receipt_sha256':main.fixed.sha(receipt.read_bytes())}
    with pytest.raises(ValueError,match='TRANSITION_EVIDENCE_SET_CHANGED'):main.zero_admission(plan)


def test_transition_set_admission_accepts_only_matching_candidate_and_set(tmp_path,monkeypatch):
    receipt=tmp_path/'candidate_receipt.json';receipt.write_text('{}')
    proof={'as_of':'2026-11-02T12:59:00+08:00','matching_receipts':[{'sha256':'a'}]}
    plan={'transition_owner_proof':proof,'candidate_receipt_path':str(receipt),
          'candidate_receipt_sha256':main.fixed.sha(receipt.read_bytes())}
    monkeypatch.setattr(main,'transition_owner_proof',lambda *a,**kw:proof)
    assert main.zero_admission(plan)==proof
    receipt.write_text('{"drift":true}')
    with pytest.raises(ValueError,match='TRANSITION_CANDIDATE_RECEIPT_DRIFT'):main.zero_admission(plan)


def test_transition_publication_files_must_match_receipt_slots(tmp_path):
    a=tmp_path/'0830.json';b=tmp_path/'0900.json';a.write_text('{}');b.write_text('{}')
    validate_transition_publication_set({'0830':[{}],'0900':[{}]},[a,b])
    with pytest.raises(ValueError,match='PUBLICATION_RECEIPT_SET_MISMATCH'):
        validate_transition_publication_set({'0830':[{}],'0900':[{}]},[a])
    # A later-owner file is no longer a set mismatch, but it cannot be accepted
    # without the trade date and data root needed to verify its cited pair.
    with pytest.raises(ValueError,match='PUBLICATION_EXTRA_CONTEXT_REQUIRED'):
        validate_transition_publication_set({'0830':[{}]},[a,b])


def test_three_role_scope_rejects_pre_or_wrong_forward_order(tmp_path):
    path=tmp_path/'plan.json';path.write_text(json.dumps({'roles':{'main':{},'stage':{},'api':{},'pre':{}},'forward_order':['main','stage','api'],'rollback_order':['api','stage','main']}))
    with pytest.raises(ValueError,match='EXACT_MAIN_STAGE_API_ROLES_REQUIRED'):main.configure(path,tmp_path/'evidence')


def test_delayed_rollback_refuses_new_main_receipts_before_any_unload(tmp_path,monkeypatch,fixed):
    ledger=tmp_path/'ledger';folder=ledger/'receipts/live/20261101/1500';folder.mkdir(parents=True)
    (folder/'new-main.dispatch-receipt.json').write_text(json.dumps({'release_id':'new-main','app_root':str(tmp_path/'app'),'status':'SUCCEEDED'}))
    plan=synthetic_plan(tmp_path);plan['roles']['main']['candidate']['release_id']='new-main'
    plan['omitted_main_owner_zero_proof']={'ledger_root':str(ledger)}
    records,plan_path=setup_switch(tmp_path,monkeypatch,fixed,plan);calls=[]
    for role,row in records.items(): Path(row['path']).write_bytes(role.encode()+b'new')
    monkeypatch.setattr(fixed,'unload',lambda *a:calls.append(a))
    with pytest.raises(ValueError,match='ROLLBACK_NEW_MAIN_RECEIPTS_EXIST'):main.switch('fixture',plan_path,rollback=True)
    assert not calls and all(Path(row['path']).read_bytes()==role.encode()+b'new' for role,row in records.items())
