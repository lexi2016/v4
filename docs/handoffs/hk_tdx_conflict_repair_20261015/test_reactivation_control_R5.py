"""Actual accepted store write failures; synthetic temporary market payloads."""
from pathlib import Path
from types import SimpleNamespace
import copy,json,sys
import pytest

H=Path(__file__).resolve().parent
PUB=json.loads((H/'PUBLICATION_COMBINED_R3.json').read_bytes())
sys.path.insert(0,PUB['shared']['app_root']);sys.path.insert(0,PUB['api']['app_root']);sys.path.insert(0,str(H))
from HK_REACTIVATION_CONTROL_R5 import IntentPoolStore,rollback_consumer,rollback_shared_entries,restore_independently,sha
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.data_store import _sha256,_canonical_bytes
from infrastructure.interprocess_lock import owned_interprocess_lock
from domains.preselection_materializer import build_shared_hk_0_2_pool,build_expected_missing_pool
from shared_data.store import SafeRootStore

POOL='hkconnect_d1_top100'

def test_failure_injection_uses_frozen_actual_API_store():
    import infrastructure.preselection_pool_store as module
    assert Path(module.__file__)==Path(PUB['api']['app_root'])/'infrastructure/preselection_pool_store.py'

def case(tmp_path,target,existing):
    root=tmp_path/'data';intents=tmp_path/'intents';intents.mkdir()
    base=PreselectionPoolStore(root)
    a=build_expected_missing_pool(target,pool_id='a_d1_premarket_pool',display_name='synthetic A protected',market='A',reason='test')
    base.materialize(a)
    signal='20261014' if target=='20261015' else '20261015'
    rows=[dict(code_norm=f'HK.{i:05d}',rank=str(i),name=f'Synthetic{i}',score_prob_active=1-i/1000,
        signal_date=signal,target_date=target,d1_freshness_status='PASS',selected_strategy='prob_active',history_resolution_identity='f'*64) for i in range(1,101)]
    pool=SimpleNamespace(rows=rows,run=SimpleNamespace(verification=dict(artifact_sha256='a'*64,manifest_sha256='b'*64,
        receipt_sha256='c'*64,run_id='synthetic-new',row_count=100,artifact_relative='runs/synthetic/artifact.csv'),
        receipt=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)))
    payload=build_shared_hk_0_2_pool(tmp_path,trade_date=target,signal_date=signal,reader=lambda *a,**kw:pool)
    payload.update(signal_date=signal,target_date=target,stage_selection_eligible=True,source_manifest_sha256='b'*64,source_receipt_sha256='c'*64)
    old=None;snapshot=None
    if existing:
        old=copy.deepcopy(payload);old['source_run_id']='synthetic-old';old['source_sha256']='0'*64
        base.materialize(old);snapshot=base._read_pool_snapshot_unlocked(target,POOL)
    manifest_rel=f'preselection_pools/{target}/manifest.json';manifest=base._read(manifest_rel)
    expected={k:snapshot[k] for k in ['artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256']} if existing else None
    config=dict(consumer_expected_previous=expected,
        consumer_preexisting_manifest_sha256=sha(base._io.read_bytes(manifest_rel)),
        consumer_non_HK_manifest_sha256=_sha256({k:v for k,v in manifest.items() if k!=POOL}),
        new_consumer_sha256=_sha256(payload))
    store=IntentPoolStore(root).configure_intents(intents,{target:config})
    a_paths=[f'preselection_pools/{target}/a_d1_premarket_pool.json',f'preselection_pools/{target}/receipts/a_d1_premarket_pool.json']
    a_bytes={rel:base._io.read_bytes(rel) for rel in a_paths}
    return SimpleNamespace(base=base,store=store,payload=payload,old=old,snapshot=snapshot,manifest=manifest,
        intents=intents,root=root,target=target,config=config,a_bytes=a_bytes)

def publish(case):
    if case.snapshot is None:return case.store.materialize(case.payload)
    artifact=f'preselection_pools/{case.target}/{POOL}.json'
    receipt=case.store._receipt(trade_date=case.target,pool_id=POOL,artifact_path=artifact,artifact_sha256=_sha256(case.payload),payload=case.payload)
    manifest=dict(case.manifest);manifest[POOL]=_sha256(case.payload)
    with owned_interprocess_lock(case.root/'.import.lock',timeout_seconds=1,timeout_message='test'):
        case.store._commit_main_snapshot(case.snapshot,payload=case.payload,receipt=receipt,manifest=manifest)

def restore(case):
    intent=json.loads((case.intents/f'CONSUMER_INTENT_{case.target}_R5.json').read_bytes())
    with owned_interprocess_lock(case.root/'.import.lock',timeout_seconds=1,timeout_message='test'):
        result=rollback_consumer(case.base,intent)
    for rel,raw in case.a_bytes.items():assert case.base._io.read_bytes(rel)==raw
    assert {k:v for k,v in case.base._read(f'preselection_pools/{case.target}/manifest.json').items() if k!=POOL}=={k:v for k,v in case.manifest.items() if k!=POOL}
    return result

@pytest.mark.parametrize('failure',['receipt','manifest'])
def test_actual_create16_partial_failure_restores_absence_and_A(tmp_path,monkeypatch,failure):
    c=case(tmp_path,'20261016',False);write=c.store._write
    target=f'preselection_pools/{c.target}/'+('receipts/'+POOL+'.json' if failure=='receipt' else 'manifest.json')
    def fail(relative,value):
        if relative==target:raise OSError('injected actual create write failure')
        return write(relative,value)
    monkeypatch.setattr(c.store,'_write',fail)
    with pytest.raises(OSError):publish(c)
    assert (c.root/f'preselection_pools/{c.target}/{POOL}.json').exists()
    result=restore(c);assert result['after']==json.loads((c.intents/f'CONSUMER_INTENT_{c.target}_R5.json').read_bytes())['old']
    assert not (c.root/f'preselection_pools/{c.target}/{POOL}.json').exists()
    assert not (c.root/f'preselection_pools/{c.target}/receipts/{POOL}.json').exists()

@pytest.mark.parametrize('interrupted_after',['pending','artifact','receipt','manifest'])
def test_actual_refresh15_each_component_interruption_own_journal(tmp_path,monkeypatch,interrupted_after):
    c=case(tmp_path,'20261015',True);write=c.store._write
    paths=dict(pending=f'preselection_pending_commits/{c.target}/{POOL}.json',artifact=f'preselection_pools/{c.target}/{POOL}.json',
        receipt=f'preselection_pools/{c.target}/receipts/{POOL}.json',manifest=f'preselection_pools/{c.target}/manifest.json')
    def interrupt(relative,value):
        write(relative,value)
        if relative==paths[interrupted_after]:raise KeyboardInterrupt('simulated process interruption')
    monkeypatch.setattr(c.store,'_write',interrupt)
    with pytest.raises(KeyboardInterrupt):publish(c)
    assert (c.root/paths['pending']).exists()
    result=restore(c);assert result['own_pending_removed'] is True
    assert c.base._read(paths['artifact'])==c.old
    assert not (c.root/paths['pending']).exists()

@pytest.mark.parametrize('target,existing',[('20261015',True),('20261016',False)])
def test_complete_publication_and_already_original_recovery(tmp_path,target,existing):
    c=case(tmp_path,target,existing);publish(c);restore(c);restore(c)

def test_foreign_component_refused_before_any_rollback_write(tmp_path,monkeypatch):
    c=case(tmp_path,'20261016',False);write=c.store._write
    def fail(relative,value):
        if relative.endswith('/receipts/'+POOL+'.json'):raise OSError('stop')
        return write(relative,value)
    monkeypatch.setattr(c.store,'_write',fail)
    with pytest.raises(OSError):publish(c)
    rel=f'preselection_pools/{c.target}/{POOL}.json';c.base._io.write_bytes(rel,b'foreign exact event')
    with pytest.raises(AssertionError,match='FOREIGN_COMPONENT'):restore(c)
    assert c.base._io.read_bytes(rel)==b'foreign exact event'

def test_foreign_HK_pending_preserved(tmp_path,monkeypatch):
    c=case(tmp_path,'20261015',True);write=c.store._write
    def interrupt(relative,value):
        write(relative,value)
        if relative.startswith('preselection_pending_commits/'):raise KeyboardInterrupt()
    monkeypatch.setattr(c.store,'_write',interrupt)
    with pytest.raises(KeyboardInterrupt):publish(c)
    rel=f'preselection_pending_commits/{c.target}/{POOL}.json';foreign=c.base._read(rel);foreign['foreign']=True;c.base._write(rel,foreign)
    before=c.base._io.read_bytes(rel)
    with pytest.raises(AssertionError,match='FOREIGN_HK_PENDING'):restore(c)
    assert c.base._io.read_bytes(rel)==before

@pytest.mark.parametrize('field',['updated_at','owner','artifact_relative','extra_field'])
def test_shared_foreign_full_pointer_event_preserved_other_own_event_restored(tmp_path,field):
    store=SafeRootStore(tmp_path/'shared');old={'run_id':'old'}
    new={'run_id':'new','artifact_sha256':'a'*64,'manifest_sha256':'b'*64,'receipt_sha256':'c'*64,
        'owner':'v3_shared_data','artifact_relative':'runs/new/artifact.csv','updated_at':'own-event'}
    foreign=dict(new);foreign[field]='foreign-event'
    key='20261015/HK_CONNECT_D1_TOP100_0_2';key2='20261016/HK_CONNECT_D1_TOP100_0_2'
    other={'run_id':'A unchanged'}
    store._write_json(store.latest_path,dict(schema_version='v3_shared_data.latest.v1',entries={key:foreign,key2:new,'other/A':other}))
    intent=dict(old_entries={key:old,key2:None},new_entries={key:new,key2:new})
    result=rollback_shared_entries(store,intent);assert result['errors']==[dict(slot=key,error='FOREIGN_FULL_POINTER_EVENT')]
    actual=store._load_latest()['entries'];assert actual[key]==foreign and key2 not in actual and actual['other/A']==other

def test_driver_failure_does_not_abort_remaining_safe_restores():
    events=[]
    def fail():events.append('pool');raise OSError('injected component recovery failure')
    def safe(name):events.append(name);return 'safe exact CAS restored'
    result=restore_independently([('pool',fail),('pointer',lambda:safe('pointer')),('plist',lambda:safe('plist')),('service',lambda:safe('service'))])
    assert events==['pool','pointer','plist','service']
    assert result[0]['status']=='FAILED_PRESERVED_FOR_AUDIT'
    assert all(row['status']=='RESTORED_OR_ALREADY_ORIGINAL' for row in result[1:])

def test_wrapper_preserves_A_pending_and_continues_independent_steps(tmp_path,monkeypatch):
    import ROLLBACK_REACTIVATION_R5 as wrapper
    c=case(tmp_path,'20261016',False)
    rel='preselection_pending_commits/20261016/a_d1_premarket_pool.json';c.base._io.write_bytes(rel,b'A foreign journal must not recover')
    monkeypatch.setitem(wrapper.PLAN,'consumer_root',str(c.root));monkeypatch.setattr(wrapper,'H',c.intents)
    pending=c.base._io.read_bytes(rel);continued=[]
    result=restore_independently([('HK',lambda:wrapper.rollback_target('20261016')),('pointer',lambda:continued.append(True))])
    assert result[0]['status']=='FAILED_PRESERVED_FOR_AUDIT' and continued==[True]
    assert c.base._io.read_bytes(rel)==pending

@pytest.mark.parametrize('target,existing',[('20261015',True),('20261016',False)])
def test_actual_rollback_wrapper_accepts_own_partial_not_complete_trio(tmp_path,monkeypatch,target,existing):
    import ROLLBACK_REACTIVATION_R5 as wrapper
    c=case(tmp_path,target,existing);write=c.store._write
    def interrupt(relative,value):
        write(relative,value)
        if relative==f'preselection_pools/{target}/{POOL}.json':raise KeyboardInterrupt()
    monkeypatch.setattr(c.store,'_write',interrupt)
    with pytest.raises(KeyboardInterrupt):publish(c)
    monkeypatch.setattr(wrapper,'PLAN',dict(consumer_root=str(c.root),targets={target:c.config}))
    monkeypatch.setattr(wrapper,'H',c.intents)
    (c.intents/f'PUBLISHED_{target}_CONSUMER.json').write_text(json.dumps(dict(result=dict(sha256=_sha256(c.payload)))))
    result=wrapper.rollback_target(target)
    assert result['status']=='EXACT_COMPONENTS_RESTORED'
    for rel,raw in c.a_bytes.items():assert c.base._io.read_bytes(rel)==raw

def test_durable_intent_failure_prevents_live_create(tmp_path,monkeypatch):
    import HK_REACTIVATION_CONTROL_R5 as control
    c=case(tmp_path,'20261016',False)
    def fail(*args):raise OSError('intent fsync/write failed')
    monkeypatch.setattr(control,'durable_intent',fail)
    with pytest.raises(OSError,match='intent fsync'):publish(c)
    assert not (c.root/f'preselection_pools/{c.target}/{POOL}.json').exists()
    assert c.base._read(f'preselection_pools/{c.target}/manifest.json')==c.manifest

def test_same_payload_create_reentry_refused_as_foreign_event(tmp_path):
    c=case(tmp_path,'20261016',False);publish(c)
    intent=(c.intents/f'CONSUMER_INTENT_{c.target}_R5.json').read_bytes()
    with pytest.raises(AssertionError):publish(c)
    assert (c.intents/f'CONSUMER_INTENT_{c.target}_R5.json').read_bytes()==intent
