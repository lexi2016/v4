from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
import pytest
from ops import research_panel_factor_cache as cache

def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def sync(tmp_path,code='000001.SZ',target=20261029,sop=False):
    tmp_path.mkdir(parents=True,exist_ok=True)
    raw=tmp_path/'raw.day';raw.write_bytes(b'unchanged raw source')
    proof=save(tmp_path/'proof.json',{'verdict':'PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION'})
    row={'symbol':code[:6],'market':{'SZ':0,'SH':1,'BJ':2}[code[-2:]],'path':str(raw),'source_sha256_after':hashlib.sha256(raw.read_bytes()).hexdigest()}
    if sop:row.update(classification='QUARANTINED',quarantine=True,target_date_ready=False,lifecycle_skip=True,reason_code=cache._LIFECYCLE_REASON,records_written=0,lifecycle_asset_sha256=cache._LIFECYCLE_ASSET_SHA,lifecycle_fact={'ts_code':code,'verified':True,'requires_recent_listed_A_share_bars':False,'delisting_effective_date':'20260601','accepted_review_literal':'PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION','accepted_review_ref':proof,'accepted_case_result_ref':proof})
    summary={'target_date':target,'target_keys':[{'symbol':row['symbol'],'market':row['market']}],'symbol_reconciliation':[row],'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    return save(tmp_path/'summary.json',summary),summary
class Client:
    def __init__(self):self.calls=[]
    def get_rehab(self,code):self.calls.append(code);return 0,[]
    def close(self):pass

def run(root,ref,client,codes):
    return cache.collect_metadata(codes,cache_root=root,target=20261029,prequery_sync_ref=ref,client_factory=lambda:client,min_interval=0,retries=0)

def test_verified_sop_skips_provider_and_preserves_proof(tmp_path):
    ref,summary=sync(tmp_path/'input',sop=True);client=Client();r=run(tmp_path/'cache',ref,client,['000001.SZ'])
    assert client.calls==[] and r['provider_call_count']==0 and r['requested_count']==1
    row=r['symbols']['000001.SZ'];assert row['status']=='SOP_SKIPPED' and row['capture_date'] is None and row['queried_at'] is None
    assert row['original_sync_row']==summary['symbol_reconciliation'][0]
    assert r['counts']['SOP_SKIPPED']==1 and sum(r['counts'].values())==1
@pytest.mark.parametrize('failure',['wrong_target','missing_proof','raw_drift','wrong_code','not_effective','asset_drift','generic_error'])
def test_unproven_classification_never_acquires_sop_skip(tmp_path,failure):
    ref,s=sync(tmp_path/'input',sop=True);row=s['symbol_reconciliation'][0]
    if failure=='wrong_target':s['target_date']=20261028
    if failure=='missing_proof':row['lifecycle_fact'].pop('accepted_review_ref')
    if failure=='raw_drift':Path(row['path']).write_bytes(b'drift')
    if failure=='wrong_code':row['lifecycle_fact']['ts_code']='600001.SH'
    if failure=='not_effective':row['lifecycle_fact']['delisting_effective_date']='20261030'
    if failure=='asset_drift':row['lifecycle_asset_sha256']='0'*64
    if failure=='generic_error':row.update(lifecycle_skip=False,reason_code='ERROR')
    ref=save(Path(ref['path']),s);client=Client()
    if failure=='wrong_target':
        with pytest.raises(cache.QfqGateError,match='TARGET_OR_SAFETY'):run(tmp_path/'cache',ref,client,['000001.SZ'])
        assert client.calls==[]
    elif failure == 'generic_error':
        r=run(tmp_path/'cache',ref,client,['000001.SZ']);assert client.calls==['SZ.000001'];assert r['symbols']['000001.SZ']['status']=='EMPTY'
    else:
        with pytest.raises(cache.QfqGateError,match='SOP_REBIND_REQUIRED'):
            run(tmp_path/'cache',ref,client,['000001.SZ'])
        assert client.calls==[]

def prior_bj(root,code='920001.BJ',target=20261028):
    error=f'The format of code BJ.{code[:6]} is wrong'
    response=save(root/str(target)/'response.json',{'source':'Futu OpenD get_rehab','code':'BJ.'+code[:6],'return_code':-1,'error':error})
    return save(root/str(target)/'checkpoint.json',{'asof_date':target,'symbols':{code:{'status':'UNSUPPORTED_MARKET','error':error,'response':response,'queried_at':'2026-10-28T10:00:00+00:00','capture_date':20261028,'asof_date':target}}})
def test_prior_bj_routes_without_new_query_and_keeps_old_dates(tmp_path):
    ref,_=sync(tmp_path/'input',code='920001.BJ');root=tmp_path/'cache';prior_bj(root);client=Client();r=run(root,ref,client,['920001.BJ'])
    assert client.calls==[] and r['provider_call_count']==0 and r['known_prior_capability_count']==1
    row=r['symbols']['920001.BJ'];assert row['status']=='UNSUPPORTED_MARKET' and row['capture_date'] is None and row['queried_at'] is None
    assert row['capability_evidence']['original']['capture_date']==20261028
    assert sum(r['counts'].values())==1
@pytest.mark.parametrize('bad',['response_drift','code_drift','generic_error'])
def test_bj_unbound_capability_does_not_skip(tmp_path,bad):
    ref,_=sync(tmp_path/'input',code='920001.BJ');root=tmp_path/'cache';prior_bj(root);p=root/'20261028/checkpoint.json';state=json.loads(p.read_text());row=state['symbols']['920001.BJ']
    if bad=='response_drift':Path(row['response']['path']).write_text('{}')
    if bad=='code_drift':state['symbols']['920002.BJ']=state['symbols'].pop('920001.BJ')
    if bad=='generic_error':row['status']='ERROR'
    p.write_text(json.dumps(state));client=Client();r=run(root,ref,client,['920001.BJ']);assert client.calls==['BJ.920001'];assert r['symbols']['920001.BJ']['status']=='EMPTY'
def test_normal_query_and_same_day_cache_freshness_unchanged(tmp_path):
    ref,_=sync(tmp_path/'input');client=Client();root=tmp_path/'cache';a=run(root,ref,client,['000001.SZ']);b=run(root,ref,client,['000001.SZ'])
    assert client.calls==['SZ.000001'];assert a['provider_call_count']==1 and b['provider_call_count']==0
def test_mixed_requested_identities_and_actual_provider_calls_reconcile(tmp_path):
    summaries=[]
    for code,sop in [('000001.SZ',True),('600001.SH',False),('920001.BJ',False)]:
        _,s=sync(tmp_path/code,code=code,sop=sop);summaries.append(s)
    summary=summaries[0]
    summary['target_keys']=[x for s in summaries for x in s['target_keys']]
    summary['symbol_reconciliation']=[x for s in summaries for x in s['symbol_reconciliation']]
    ref=save(tmp_path/'mixed.json',summary);root=tmp_path/'cache';prior_bj(root);client=Client()
    r=run(root,ref,client,['000001.SZ','600001.SH','920001.BJ'])
    assert r['requested_count']==3 and sum(r['counts'].values())==3
    assert r['provider_call_count']==1 and r['provider_identity_count']==1 and client.calls==['SH.600001']
    assert r['sop_skipped_count']==1 and r['known_prior_capability_count']==1
@pytest.mark.parametrize('literal',["PASS_SINGLE_STOCK_TARGET_WINDOW_DELISTED_CLASSIFICATION","PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION_AFTER_QUERY_FIX"])
def test_existing_fixed_asset_sop_literal_variants_keep_original_proof(tmp_path,literal):
    ref,s=sync(tmp_path/'input',sop=True);s['symbol_reconciliation'][0]['lifecycle_fact']['accepted_review_literal']=literal;ref=save(Path(ref['path']),s)
    client=Client();r=run(tmp_path/'cache',ref,client,['000001.SZ'])
    assert client.calls==[] and r['counts']['SOP_SKIPPED']==1
    assert r['symbols']['000001.SZ']['original_sync_row']==s['symbol_reconciliation'][0]

@pytest.mark.parametrize('bad',['none','price_admission','market_scope','event_type','quality','literal','missing_mirror','mirror_drift','factset_sha','effective_date'])
def test_controller_quarantine_fact_preserves_pending_and_caveat(tmp_path,monkeypatch,bad):
    code='600193.SH';ref,s=sync(tmp_path/'input',code=code,sop=True);fact=s['symbol_reconciliation'][0]['lifecycle_fact']
    mirror=tmp_path/'mirror.pdf';mirror.write_bytes(b'original broker mirror bytes');mirror_ref={'path':str(mirror),'sha256':hashlib.sha256(mirror.read_bytes()).hexdigest(),'source_quality':cache._MIRROR_CAVEAT}
    approved={'schema':'controller_relayed_lineage_fact_set.v1','delisting_facts':{code:'20260706'},'quality_caveats':{code:cache._MIRROR_CAVEAT},'consumer_independent_review':'PENDING','bound_primary_artifacts':{'600193_broker_notice_mirror_pdf':{'path':str(mirror),'sha256':mirror_ref['sha256']}}}
    case=save(tmp_path/'controller.json',approved);monkeypatch.setattr(cache,'_CONTROLLER_FACT_SET_SHA',case['sha256'])
    fact.update(delisting_effective_date='20260706',accepted_case_result_ref=case,accepted_review_literal=cache._CONTROLLER_PENDING_LITERAL,old_market_only=True,price_chain_admitted=False,event_type='DELISTING',historical_PIT=False,source_quality=cache._MIRROR_CAVEAT,source_caveat='original mirror provenance caveat',issuer_or_broker_mirror_refs=[mirror_ref]);fact.pop('accepted_review_ref')
    if bad=='price_admission':fact['price_chain_admitted']=True
    if bad=='market_scope':fact['old_market_only']=False
    if bad=='event_type':fact['event_type']='SUSPENSION'
    if bad=='quality':fact['source_quality']='PRIMARY_SOURCE_VERIFIED'
    if bad=='literal':fact['accepted_review_literal']='PASS'
    if bad=='missing_mirror':fact['issuer_or_broker_mirror_refs']=[]
    if bad=='mirror_drift':mirror.write_bytes(b'drift')
    if bad=='factset_sha':fact['accepted_case_result_ref']['sha256']='0'*64
    if bad=='effective_date':fact['delisting_effective_date']='20260707'
    ref=save(Path(ref['path']),s);client=Client()
    if bad != 'none':
        with pytest.raises(cache.QfqGateError,match='SOP_REBIND_REQUIRED'):run(tmp_path/'cache',ref,client,[code])
        assert not client.calls
        return
    r=run(tmp_path/'cache',ref,client,[code]);row=r['symbols'][code]
    if bad=='none':
        assert not client.calls and row['status']=='SOP_SKIPPED'
        assert row['original_sync_row']==s['symbol_reconciliation'][0]
        retained=row['original_sync_row']['lifecycle_fact']
        assert retained['accepted_review_literal']==cache._CONTROLLER_PENDING_LITERAL
        assert retained['source_quality']==cache._MIRROR_CAVEAT and retained['price_chain_admitted'] is False
    else:assert client.calls==['SH.600193'] and row['status']=='EMPTY'
