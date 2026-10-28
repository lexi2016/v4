"""SIMULATED tests only. No natural market data or authorized all-four positive."""
from __future__ import annotations
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from domains.manager_catalyst_tracking import CatalystEvent, read_catalyst_events, candidate_catalyst, prior_workbench_candidates
from domains.manager_close_discovery import build_workbench_payload, FOUR_FLAGS
from domains.manager_research_evidence import read_universe_evidence, persist_snapshot, read_snapshot_evidence, EvidenceError
from infrastructure.manager_input_attestation import publish_attestation

HK=ZoneInfo('Asia/Hong_Kong')
AS_OF=datetime(2026,9,18,15,30,20,tzinfo=HK)
DATE='20260918'
APP=Path(__file__).resolve().parents[1]


def row(**changes):
    out={'code':'HK.00001','name':'SIMULATED 甲公司','update_time':'2026-09-18 15:30:00','last_price':10.5,'prev_close_price':10.,'turnover':200_000_000.,'currency':'HKD','unit':'HKD','volume_ratio':2.,'volume_ratio_baseline_as_of':'2026-09-18T15:29:00+08:00','volume_ratio_baseline_period':'ARBITRARY_PERIOD','volume_ratio_rule_version':'ARBITRARY_VERSION','volume_ratio_rule_source':'stage_center.live_collectors._futu_hkconnect_active_snapshot','historical_position_state':'BREAKOUT','historical_baseline_as_of':'2026-09-17T16:00:00+08:00','historical_rule_version':'ARBITRARY_RULE','historical_source_ref':'arbitrary/history.json'}
    out.update(changes); return out


def source(role='EXISTING_SHARED_FUTU_1530_SNAPSHOT'):
    return {'owner':'v35_dispatcher.hourly_research','role':role,'artifact_ref':'workbench_research/20260918/inputs/1530_futu_snapshot.json','run_id':'SIMULATED','sha256':'a'*64,'source_date':DATE,'market':'HK_CONNECT','observed_at':'2026-09-18T15:30:00+08:00','available_at':'2026-09-18T15:30:00+08:00','reason':'SIMULATED'}


def build(rows=None, **extra):
    args=dict(trade_date=DATE,as_of=AS_OF,generated_at=AS_OF,universe_source=source('HK_CONNECT_FULL_MARKET_AUTHORITY'),eligible_symbols=['HK.00001'],snapshot_rows=rows or [row()],snapshot_source=source())
    args.update(extra); return build_workbench_payload(**args)


def universe(root):
    from stage_center.hk_universe_preflight import ensure_hk_connect_universe
    codes=[f'HK.{i:05}' for i in range(1,652)]
    class Frame:
        def to_dict(self,*,orient): return [{'code':c} for c in codes]
    class Quote:
        def get_plate_stock(self,plate): return 0,Frame()
        def close(self): pass
    ensure_hk_connect_universe(root,DATE,now=AS_OF.replace(hour=15,minute=0),quote_context_factory=Quote)
    return read_universe_evidence(root,DATE,as_of=AS_OF,clock=lambda:AS_OF.replace(minute=0,second=21))


def verified(tmp_path, rows):
    univ=universe(tmp_path/'universe')
    state=tmp_path/'state'
    persist_snapshot(state,trade_date=DATE,rows=rows,errors=[],started_at=AS_OF.replace(second=0),available_at=AS_OF,universe=univ,app_root=APP)
    snap=read_snapshot_evidence(state,DATE,as_of=AS_OF,universe=univ,app_root=APP)
    return univ,snap


def verified_build(tmp_path,rows):
    u,s=verified(tmp_path,rows)
    return build(rows,universe_source=u.source,eligible_symbols=u.codes,snapshot_source=s.source,universe_evidence=u,snapshot_evidence=s)


def predicates(c): return {p['predicate_id']:p['value'] for p in c['predicates']}


def test_f09_self_reported_strings_never_qualify():
    event=CatalystEvent(event_id='SIMULATED',source_date=DATE,source_ref='research/incoming/20260918/1500.json',source_sha256='b'*64,source_run_id='fake',source_owner='existing_hourly_research_input',source_available_at='2026-09-18T15:00:00+08:00',title='SIMULATED',published_at='2026-09-18T14:00:00+08:00',first_seen_at='2026-09-18T15:00:00+08:00',themes=(),mapped_symbols=('HK.00001',),mapping_basis='EXPLICIT_HK_CODE')
    c=build(catalyst_events=[event])['candidates'][0]
    assert c['qualified'] is None
    assert list(predicates(c).values())==['unknown']*4
    assert c['data_status']=='TURNOVER_OBSERVATION_PENDING'


@pytest.mark.parametrize('amount,expected',[(100_000_000,False),(100_000_000.01,True),(200_000_000,True)])
def test_verified_amount_is_strictly_greater_than_100m(tmp_path,amount,expected):
    c=verified_build(tmp_path,[row(turnover=amount)])['candidates'][0]
    assert predicates(c)['turnover_gt_100m_hkd'] is expected
    assert predicates(c)['verified_volume_expansion']=='unknown'
    assert predicates(c)['verified_oversold_or_breakout']=='unknown'
    assert c['qualified'] is (None if expected else False)


@pytest.mark.parametrize('currency,unit',[('USD','USD'),('HKD',None),(None,None),('HKD','MILLION_HKD')])
def test_currency_or_units_are_never_inferred(tmp_path,currency,unit):
    c=verified_build(tmp_path,[row(currency=currency,unit=unit)])['candidates'][0]
    assert predicates(c)['turnover_gt_100m_hkd'] is not True
    assert c['turnover_amount']['currency']==(currency or 'UNKNOWN')


def test_snapshot_actual_content_hash_and_universe_binding(tmp_path):
    u,s=verified(tmp_path,[row()])
    p=tmp_path/'state'/s.source['artifact_ref']
    raw=json.loads(p.read_text()); raw['rows'][0]['turnover']=999999999
    p.write_text(json.dumps(raw))
    with pytest.raises(EvidenceError): read_snapshot_evidence(tmp_path/'state',DATE,as_of=AS_OF,universe=u,app_root=APP)


def test_universe_chain_not_just_existing_filenames(tmp_path):
    u=universe(tmp_path)
    p=tmp_path/u.source['receipt_ref']; p.write_text('{}')
    with pytest.raises((EvidenceError,ValueError)): read_universe_evidence(tmp_path,DATE,as_of=AS_OF)


def test_duplicate_quotes_exclude_both_and_never_hide_conflict(tmp_path):
    p=verified_build(tmp_path,[row(),row(turnover=400_000_000)])
    assert p['candidates']==[]
    assert p['status']=='PARTIAL'
    assert any('DUPLICATE' in r for r in p['coverage']['missing_reasons'])


def make_news(root, *, date=DATE, slot='1500', available=None, attest=True):
    p=root/'research'/'incoming'/date/(slot+'.json'); p.parent.mkdir(parents=True,exist_ok=True)
    code_hash=lambda rel:hashlib.sha256((APP/rel).read_bytes()).hexdigest()
    manifest={'producer':'ops.collect_hourly_research_input','version':'20260918150000-1234abcd','module_path':'v3.5/domains/research_hourly','trade_date':date,'hourly_slot':slot,'generated_at':f'{date[:4]}-{date[4:6]}-{date[6:]}T15:00:00+08:00','collector_identity_sha256':code_hash('ops/collect_hourly_research_input.py'),'research_hourly_domain_identity_sha256':code_hash('domains/research_hourly.py'),'source_receipts':[]}
    receipt_ref=f'research_module/runtime_outputs/zsxq_hourly/{date}/{slot}/v35_zsxq_hourly_status_{date}_{slot}.json'
    manifest['source_receipts']=[receipt_ref]
    receipt=root/receipt_ref; receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({'fixture_label':'SIMULATED','trade_date':date,'slot':slot,'status_path':receipt_ref,'fetch_ok':True,'status':'READY','fetched_at':f'{date[:4]}-{date[4:6]}-{date[6:]}T15:00:00+08:00'}))
    data={'schema_version':'v3_research_lane.v2','module_id':'research_intelligence','write_policy':'read_only','default_status':'RESEARCH_ONLY','buy_gate_effect':'none','live_order_effect':'none','trade_date':date,'source_manifest':manifest,'fixture_label':'SIMULATED','research_items':[{'id':'SIMULATED_EVENT','title':'SIMULATED direct catalyst','stock_code':'HK.00001','published_at':f'{date[:4]}-{date[4:6]}-{date[6:]}T14:00:00+08:00','first_seen_at':f'{date[:4]}-{date[4:6]}-{date[6:]}T15:00:00+08:00'}]}
    p.write_text(json.dumps(data,ensure_ascii=False))
    if attest: publish_attestation(p,data_root=root,owner_root=APP,available_at=available or AS_OF.replace(minute=0,second=1))
    return p


def read_news(root,p): return read_catalyst_events([p],as_of=AS_OF,universe_names={'HK.00001':'SIMULATED 甲公司'},reference_root=root,owner_root=APP)


def test_manifest_strings_without_bound_receipt_are_unknown(tmp_path):
    p=make_news(tmp_path,attest=False)
    events,gaps=read_news(tmp_path,p)
    assert not events and gaps


def test_new_byte_bound_owner_publication_can_confirm_direct_pit(tmp_path):
    p=make_news(tmp_path)
    events,gaps=read_news(tmp_path,p)
    assert len(events)==1 and not gaps
    assert candidate_catalyst('HK.00001',events,as_of=AS_OF)['status']=='CONFIRMED_PIT'


@pytest.mark.parametrize('mutation',['bytes','wrong_date','fake_producer','wrong_code_sha','late_receipt'])
def test_news_rejects_actual_identity_hash_time_conflicts(tmp_path,mutation):
    p=make_news(tmp_path,available=AS_OF.replace(minute=31) if mutation=='late_receipt' else None)
    if mutation!='late_receipt':
        value=json.loads(p.read_text())
        if mutation=='bytes': value['research_items'][0]['title']='altered'
        elif mutation=='wrong_date': value['trade_date']='20260917'
        elif mutation=='fake_producer': value['source_manifest']['producer']='invented'
        else: value['source_manifest']['collector_identity_sha256']='0'*64
        p.write_text(json.dumps(value))
    assert read_news(tmp_path,p)[0]==[]


def test_old_published_time_does_not_make_new_catalyst(tmp_path):
    p=make_news(tmp_path,date='20260917',available=AS_OF.replace(day=17,minute=0))
    events,_=read_news(tmp_path,p)
    assert len(events)==1
    assert candidate_catalyst('HK.00001',events,as_of=AS_OF)['status']=='KNOWN_CONTEXT'


def test_weak_prior_json_rejected(tmp_path):
    p=tmp_path/'prior.json'; p.write_text(json.dumps({'trade_date':'20260917','market':'HK_CONNECT','candidates':[{'symbol':'HK.00001'}]}))
    assert prior_workbench_candidates(p,expected_date='20260917')=={}


def test_universe_capture_time_is_not_invented_as_availability(tmp_path):
    u=universe(tmp_path)
    from domains.manager_research_evidence import read_universe_evidence
    witnessed=AS_OF.replace(second=10)
    v=read_universe_evidence(tmp_path,DATE,as_of=AS_OF,clock=lambda:witnessed)
    assert datetime.fromisoformat(v.source['available_at'])==witnessed
    assert datetime.fromisoformat(v.source['observed_at'])<witnessed


def test_reader_distinguishes_no_execution_from_failed_execution(tmp_path,monkeypatch):
    import apps.api.v35_api.manager_workbench_router as router
    monkeypatch.setattr(router,'_now_hk',lambda:AS_OF)
    reader=router.ManagerWorkbenchResearchReader(tmp_path)
    assert reader.read(DATE)['status']=='NOT_RUN'
    p=tmp_path/f'workbench_research/{DATE}/1530.status.json';p.parent.mkdir(parents=True)
    failed=router._empty_envelope(DATE,'FAILED','SIMULATED_BRIDGE_FAILURE')
    failed.update(as_of=AS_OF.isoformat(),generated_at=AS_OF.isoformat())
    p.write_text(json.dumps(failed))
    assert reader.read(DATE)['status']=='FAILED'
    assert reader.read(DATE)['candidates']==[]


def test_r2_validator_rejects_missing_or_faked_required_legs(tmp_path):
    from apps.api.v35_api.manager_workbench_router import validate_workbench_payload,WorkbenchResearchContractError
    p=verified_build(tmp_path,[row()])
    validate_workbench_payload(p,expected_date=DATE)
    p['candidates'][0]['predicates']=p['candidates'][0]['predicates'][:1]
    with pytest.raises(WorkbenchResearchContractError): validate_workbench_payload(p,expected_date=DATE)


def test_numeric_booleans_are_not_predicate_truth(tmp_path):
    from apps.api.v35_api.manager_workbench_router import validate_workbench_payload,WorkbenchResearchContractError
    p=verified_build(tmp_path,[row()]);p['candidates'][0]['predicates'][1]['value']=0
    with pytest.raises(WorkbenchResearchContractError): validate_workbench_payload(p,expected_date=DATE)


def test_reader_never_exposes_artifact_generated_in_future(tmp_path,monkeypatch):
    import apps.api.v35_api.manager_workbench_router as router
    p=verified_build(tmp_path/'fixture',[row()]);out=tmp_path/f'workbench_research/{DATE}/1530.json';out.parent.mkdir(parents=True)
    out.write_text(json.dumps(p));monkeypatch.setattr(router,'_now_hk',lambda:AS_OF.replace(second=10))
    assert router.ManagerWorkbenchResearchReader(tmp_path).read(DATE)['candidates']==[]

def test_numeric_boolean_in_publication_receipt_rejected(tmp_path):
    p=make_news(tmp_path); owner=APP
    side=p.with_name(p.name+'.publication.json'); data=json.loads(side.read_text()); data['RESEARCH_ONLY']=1
    side.write_text(json.dumps(data))
    events,gaps=read_catalyst_events([p],as_of=AS_OF,universe_names={'HK.00001':'SIMULATED 甲公司'},reference_root=tmp_path,owner_root=owner)
    assert events==[] and gaps

@pytest.mark.parametrize('status',['FAILED','INPUT_MISSING','PENDING_SLOT'])
def test_newer_failed_or_running_attempt_cannot_display_an_old_card(tmp_path,monkeypatch,status):
    import apps.api.v35_api.manager_workbench_router as router
    from infrastructure.manager_close_attempt import write_attempt
    p=verified_build(tmp_path/'fixture',[row()])
    out=tmp_path/f'workbench_research/{DATE}/1530.json';out.parent.mkdir(parents=True);out.write_text(json.dumps(p))
    later=AS_OF.replace(second=30);monkeypatch.setattr(router,'_now_hk',lambda:later)
    write_attempt(tmp_path,DATE,status,'EXECUTION_STARTED' if status=='PENDING_SLOT' else 'SIMULATED_NEW_FAILURE',later)
    response=router.ManagerWorkbenchResearchReader(tmp_path).read(DATE)
    assert response['status']==status and response['candidates']==[]
    assert out.read_text()==json.dumps(p)  # Audit bytes are retained; GET never deletes.
