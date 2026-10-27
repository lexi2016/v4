from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

WORK=Path(__file__).parents[1]
sys.path.insert(0,str(WORK))
from upstreams.v3_shared_data.shared_data import a_share_security_master as owner
from ops import run_review_core_natural_pool_pipeline as adapter
FLAGS={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
DATE='20261027'

def cached_fixture(tmp_path):
    root=tmp_path/'cache';root.mkdir();count={'observation_date':DATE,'count':2000};(root/'hq-SZ-count.json').write_text(json.dumps(count))
    page={'observation_date':DATE,'captured_at':'2026-10-27T10:00:00+08:00','market':0,'exchange':'SZ','offset':0,'count':2000,'provider':'PYTDX_HQ','method':'get_security_list','host':'fixture','rows':[{'code':'000001','name':'平安银行'}]}
    p=root/'hq-SZ-00000.json';p.write_text(json.dumps(page));sha=hashlib.sha256(p.read_bytes()).hexdigest()
    row={'ts_code':'000001.SZ','code':'000001','exchange':'SZ','name':'平安银行','provider':'PYTDX_HQ','method':'get_security_list','host':'fixture','observed_at':page['captured_at'],'available_at':page['captured_at'],'observation_date':DATE,'evidence_path':str(p),'evidence_sha256':sha}
    old={'schema_version':owner.DISPLAY_SCHEMA,'source_kind':'DISPLAY_NAME_ONLY','observation_date':DATE,'captured_at':page['captured_at'],'requested_codes':['000001.SZ'],'rows':[row],'pages':[{'path':str(p),'sha256':sha}],'missing_codes':[],'conflicted_codes':[],'research_only':True,**FLAGS}
    return root,p,row,old

class API:
    client=None
    def get_security_list(self,market,offset):
        assert market==0 and offset==1000
        return [{'code':'000002','name':'万科A'}]
    def get_security_count(self,market):return 2000

def test_same_date_extension_preserves_old_rows_and_adds_unfetched_page(tmp_path):
    root,p,row,old=cached_fixture(tmp_path);store=tmp_path/'store';receipt=owner.publish_current_display_names(store,old)
    index=store/'assets/a_share_display_names/latest.json';prior_sha=hashlib.sha256(index.read_bytes()).hexdigest();old_bytes=p.read_bytes()
    obs=owner.acquire_current_display_names(root,observation_date=DATE,requested_codes=['000001.SZ','000002.SZ'],api=API(),official_rows=[row],cached_page_pins={str(p):row['evidence_sha256']},output_path=tmp_path/'obs.json',allow_partial=True)
    assert obs['missing_codes']==[] and obs['rows'][0]==row and p.read_bytes()==old_bytes
    assert len(obs['pages'])==2 and (root/'hq-SZ-01000.json').exists()
    result=owner.publish_current_display_names(store,obs,extend=True,expected_prior_run_id=receipt['run_id'],expected_index_sha256=prior_sha)
    assert result['row_count']==2 and owner.load_current_display_names(store,DATE)[0]['000001']==row

def test_prior_pin_and_date_mismatch_fail_without_overwrite(tmp_path):
    root,p,row,old=cached_fixture(tmp_path);before=p.read_bytes()
    with pytest.raises(owner.StoreError,match='SHA'):owner.acquire_current_display_names(root,observation_date=DATE,requested_codes=['000002.SZ'],api=API(),cached_page_pins={str(p):'f'*64},allow_partial=True)
    with pytest.raises(owner.StoreError,match='date mismatch'):owner.acquire_current_display_names(root,observation_date='20261028',requested_codes=['000002.SZ'],cache_only=True,cached_page_pins={str(p):row['evidence_sha256']},allow_partial=True)
    assert p.read_bytes()==before

def fake_request(tmp_path):
    return SimpleNamespace(trade_date=DATE,target_date='20261028',shared_store_root=tmp_path)

def test_next_date_is_never_relabelled_and_original_pipeline_status_stays(tmp_path,monkeypatch):
    now=datetime.fromisoformat('2026-10-28T00:01:00+08:00')
    with pytest.raises(ValueError,match='NOT_CURRENT_SIGNAL'):adapter._daily_name_coverage(fake_request(tmp_path),owner=owner,pool_reader=lambda r:([],[]),clock=now)
    request=fake_request(tmp_path);monkeypatch.setattr(adapter,'validate_request',lambda **kwargs:request)
    monkeypatch.setattr(adapter,'run_pipeline',lambda request:{'status':'PARTIAL','exit_code':2})
    monkeypatch.setattr(adapter,'_daily_name_coverage',lambda request:(_ for _ in ()).throw(ValueError('fixture')))
    argv=['--trade-date','20261027','--calendar-path','/c','--review-core-package-root','/r','--shared-package-root','/s','--shared-store-root','/s','--runtime-root','/r','--hk-root','/h','--close-root','/c','--fupan-store-root','/f','--stage7-store-root','/s','--bundle-root','/b']
    assert adapter.main(argv)==2

def test_partial_members_and_exchange_conflicts_remain_explicit(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kwargs):
            assert set(kwargs['requested_codes'])=={'000001.SZ','920999.SH','920999.SZ','920999.BJ'}
            return {'rows':[{'ts_code':'000001.SZ','code':'000001','exchange':'SZ','name':'平安银行'}], 'pages':[], 'conflicted_codes':[], 'source_errors':[{'exchange':'BJ','error':'unavailable'}]}
        def publish_current_display_names(self,root,observation,**kwargs):
            assert observation['requested_codes']==['000001.SZ'] and observation['coverage_audit']['missing_codes']==['920999']
            return {'run_id':'new'}
    rows=[{'ts_code':'000001.SZ','signal_date':DATE,'target_date':'20261028'},{'code':'920999','signal_date':DATE,'target_date':'20261028'}]
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda request:(rows,[{'pool':'stage7','reason':'missing'}]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='PARTIAL' and result['matched_count']==1 and result['missing_codes']==['920999'] and result['source_failures']

def test_cross_market_identity_conflict_is_quarantined_without_acquisition(tmp_path):
    class FakeOwner: DisplayNameObservationMissing=owner.DisplayNameObservationMissing
    rows=[{'ts_code':'000001.SZ'},{'ts_code':'000001.SH'}]
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda request:(rows,[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='PARTIAL' and result['conflicted_codes']==['000001'] and result['matched_count']==0

def test_three_pool_original_readers_enforce_date_and_isolate_failure(tmp_path,monkeypatch):
    import infrastructure.preselection_pool_store as pools
    req=SimpleNamespace(trade_date=DATE,target_date='20261028',review_core_package_root=tmp_path,fupan_store_root=tmp_path/'f',stage7_store_root=tmp_path/'s')
    main={'signal_date':DATE,'target_date':'20261028','status':'V192_CANDIDATE_READY','rows':[{'ts_code':'000001.SZ'}]}
    monkeypatch.setenv('V35_DATA_ROOT',str(tmp_path));monkeypatch.setattr(pools,'PreselectionPoolStore',lambda root:SimpleNamespace(read_pool_snapshot=lambda *a:{'artifact':main,'artifact_raw_sha256':'a'*64,'manifest_raw_sha256':'b'*64,'receipt_raw_sha256':'c'*64}))
    stage={'trade_date':'20261028','artifact_sha256':'a'*64,'manifest_sha256':'b'*64,'receipt_sha256':'c'*64,'artifact':{'signal_date':DATE,'target_date':'20261028','status':'READY','rows':[{'code':'600000'}]}}
    body={'fupan':{'error':'receipt SHA mismatch'},'stage7':{'value':stage}}
    monkeypatch.setattr(adapter,'build_environment',lambda request:{})
    monkeypatch.setattr(adapter.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(body)))
    rows,errors,proofs=adapter._read_name_pool_rows(req)
    assert len(rows)==2 and errors[0]['pool']=='fupan' and 'receipt SHA' in errors[0]['reason']
    assert {p['pool'] for p in proofs}=={'main','stage7'} and all(p['receipt_sha256']=='c'*64 for p in proofs)
    main['signal_date']='20261026';rows,errors,proofs=adapter._read_name_pool_rows(req)
    assert len(rows)==1 and {x['pool'] for x in errors}=={'main','fupan'}

def test_invalid_identity_field_is_quarantined(tmp_path):
    class FakeOwner: DisplayNameObservationMissing=owner.DisplayNameObservationMissing
    row={'code':'000001','ts_code':'INVALID','signal_date':DATE,'target_date':'20261028'}
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda request:([row],[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='CANNOT_CONFIRM' and result['requested_count']==0 and result['invalid_rows']

def test_unavailable_market_reports_gap_but_keeps_valid_other_market(tmp_path):
    class PartialAPI:
        client=None
        def get_security_count(self,market):
            if market!=0:raise OSError('market unavailable')
            return 1
        def get_security_list(self,market,offset):return [{'code':'000001','name':'平安银行'}]
    observation=owner.acquire_current_display_names(tmp_path/'source',observation_date=DATE,
        requested_codes=['000001.SZ','920999.BJ'],api=PartialAPI(),allow_partial=True,output_path=tmp_path/'obs.json')
    assert [r['ts_code'] for r in observation['rows']]==['000001.SZ']
    assert observation['missing_codes']==['920999.BJ'] and observation['source_errors'][0]['exchange']=='BJ'

def test_cli_permits_same_day_extension_with_fresh_pages(tmp_path,monkeypatch):
    import importlib.util
    root,p,row,old=cached_fixture(tmp_path);store=tmp_path/'store';receipt=owner.publish_current_display_names(store,old)
    index=store/'assets/a_share_display_names/latest.json';index_sha=hashlib.sha256(index.read_bytes()).hexdigest()
    sys.path.insert(0,str(WORK/'upstreams/v3_shared_data'))
    try:
        spec=importlib.util.spec_from_file_location('r7_original_name_cli',WORK/'upstreams/v3_shared_data/scripts/acquire_a_share_security_master.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        monkeypatch.setattr(cli,'load_current_display_names',lambda *args:({'000001':row},{'run_id':receipt['run_id']}))
        captured={}
        def fake_acquire(*args,**kwargs):captured.update(kwargs);return old
        monkeypatch.setattr(cli,'acquire_current_display_names',fake_acquire)
        monkeypatch.setattr(cli,'publish_current_display_names',lambda *args,**kwargs:{'status':'READY'})
        request=tmp_path/'request.json';request.write_text(json.dumps(['000001.SZ','000002.SZ']))
        args=['--current-display-names','--observation-date',DATE,'--signal-date',DATE,'--request-json',str(request),'--evidence-root',str(root),'--store-root',str(store),'--extend-display-names','--expected-prior-run-id',receipt['run_id'],'--expected-index-sha256',index_sha,'--observation-output',str(tmp_path/'new.json')]
        assert cli.main(args)==0 and captured['cache_only'] is False and captured['cached_page_pins'][str(p)]==row['evidence_sha256']
    finally:sys.path.pop(0)

def test_acquisition_failure_reports_each_missing_code_without_publishing(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kwargs):raise OSError('no network')
        def publish_current_display_names(self,*args,**kwargs):pytest.fail('unexpected publication')
    rows=[{'ts_code':'000001.SZ'},{'code':'920999'}]
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda request:(rows,[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='CANNOT_CONFIRM' and result['missing_codes']==['000001','920999'] and result['matched_count']==0

def test_existing_registry_expands_new_verified_member_via_original_owner(tmp_path,monkeypatch):
    root,p,row,old=cached_fixture(tmp_path);store=tmp_path/'store';first=owner.publish_current_display_names(store,old)
    request=SimpleNamespace(trade_date=DATE,target_date='20261028',shared_store_root=store)
    acquire=owner.acquire_current_display_names
    monkeypatch.setattr(owner,'acquire_current_display_names',lambda *args,**kw:acquire(*args,api=API(),**kw))
    rows=[{'ts_code':'000001.SZ'},{'ts_code':'000002.SZ'}]
    result=adapter._daily_name_coverage(request,owner=owner,pool_reader=lambda r:(rows,[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='READY' and result['matched_count']==2 and result['published_run_id']!=first['run_id']
    mapping,_=owner.load_current_display_names(store,DATE);assert mapping['000001']==row and mapping['000002']['name']=='万科A'

def test_unknown_code_on_two_exchange_pages_is_conflict(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kwargs):
            return {'rows':[{'ts_code':'000001.SZ','code':'000001','exchange':'SZ'},{'ts_code':'000001.SH','code':'000001','exchange':'SH'}],'pages':[],'conflicted_codes':[],'source_errors':[]}
        def publish_current_display_names(self,*args,**kwargs):pytest.fail('ambiguous exchange must not publish')
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda r:([{'code':'000001'}],[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='CANNOT_CONFIRM' and result['conflicted_codes']==['000001'] and result['matched_count']==0

def test_next_signal_date_is_new_real_observation_not_prior_date(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kw):
            assert kw['observation_date']=='20261028'
            return {'rows':[{'ts_code':'000001.SZ','code':'000001','exchange':'SZ'}],'pages':[],'conflicted_codes':[],'source_errors':[]}
        def publish_current_display_names(self,root,observation,**kw):
            assert kw['extend'] is False
            return {'run_id':'new-date'}
    request=SimpleNamespace(trade_date='20261028',target_date='20261029',shared_store_root=tmp_path)
    result=adapter._daily_name_coverage(request,owner=FakeOwner(),pool_reader=lambda r:([{'ts_code':'000001.SZ'}],[]),clock=datetime.fromisoformat('2026-10-28T21:15:00+08:00'))
    assert result['status']=='READY' and result['published_run_id']=='new-date'

def test_wrong_previous_index_cas_keeps_prior_registry(tmp_path):
    root,p,row,old=cached_fixture(tmp_path);store=tmp_path/'store';prior=owner.publish_current_display_names(store,old)
    index=store/'assets/a_share_display_names/latest.json';before=index.read_bytes();page_before=p.read_bytes()
    with pytest.raises(owner.StoreError,match='CAS mismatch'):
        owner.publish_current_display_names(store,old,extend=True,expected_prior_run_id=prior['run_id'],expected_index_sha256='f'*64)
    assert index.read_bytes()==before and p.read_bytes()==page_before

def test_unqualified_singleton_with_failed_market_is_not_published(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kwargs):
            assert set(kwargs['requested_codes'])=={'000001.SZ','000001.SH','000001.BJ'}
            return {'rows':[{'ts_code':'000001.SZ','code':'000001','exchange':'SZ','name':'平安银行'}], 'pages':[], 'conflicted_codes':[], 'source_errors':[{'exchange':'BJ','error':'unavailable'}]}
        def publish_current_display_names(self,*args,**kwargs):pytest.fail('unqualified code with incomplete markets must not publish')
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda r:([{'code':'000001'}],[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='CANNOT_CONFIRM' and result['missing_codes']==['000001'] and result['matched_count']==0

def test_qualified_code_can_publish_despite_other_market_failure(tmp_path):
    class FakeOwner:
        DisplayNameObservationMissing=owner.DisplayNameObservationMissing
        def acquire_current_display_names(self,*args,**kwargs):
            return {'rows':[{'ts_code':'000001.SZ','code':'000001','exchange':'SZ','name':'平安银行'}], 'pages':[], 'conflicted_codes':[], 'source_errors':[{'exchange':'BJ','error':'unavailable'}]}
        def publish_current_display_names(self,root,observation,**kwargs):
            assert observation['requested_codes']==['000001.SZ']
            return {'run_id':'qualified'}
    result=adapter._daily_name_coverage(fake_request(tmp_path),owner=FakeOwner(),pool_reader=lambda r:([{'ts_code':'000001.SZ'}],[]),clock=datetime.fromisoformat('2026-10-27T21:15:00+08:00'))
    assert result['status']=='PARTIAL' and result['matched_count']==1 and result['published_run_id']=='qualified'
