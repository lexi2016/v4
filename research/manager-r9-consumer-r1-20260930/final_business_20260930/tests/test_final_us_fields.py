"""Original hourly->archive->material->relation chain; synthetic source facts only."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import pytest
from ops import collect_hourly_research_input as collector
from domains.research_hourly import build_research_lane_snapshot
from domains.research import build_research_archive
from contracts.research import validate_research_archive
from v4.manager_research.existing_materials import project_archive
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.issuer_us_relations import material_us_relations
from v4.manager_research.workspace_projection import digest

START=datetime.fromisoformat('2026-09-28T16:10:00+08:00')
CUT=datetime.fromisoformat('2026-09-30T09:29:30+08:00')
FIELDS=dict(retrieved_at='2026-09-29T18:01:00+08:00',available_at='2026-09-29T18:02:00+08:00',
    related_us_symbols=['QTEST'],source_refs=[dict(payload_sha256='c'*64,url='https://example.invalid/real-source')])

@pytest.fixture
def make_rows(tmp_path,monkeypatch):
    def make(fields=None,text='样本科技已签署NASDAQ:QTEST合作协议。'):
        topic=dict(create_time='2026-09-29T18:00:00+08:00',title='样本科技业务披露',content_head=text,
            topic_id='12345678901234567',themes=[{'theme':'生物医药'}],companies=[{'code':'00001','name':'样本科技'}])
        if fields:topic.update(deepcopy(fields))
        path=tmp_path/'summary.json';path.write_text(json.dumps({'effective_topics':[topic]},ensure_ascii=False))
        status=dict(fetched_at='2026-09-29T19:00:00+08:00',slot='1900',paths={'summary':str(path)})
        monkeypatch.setattr(collector,'_latest_zsxq_status',lambda *a:(tmp_path/'status.json',status))
        return collector._zsxq_rows(tmp_path,'20260929','1900')[0]
    return make

def archive(rows):
    snap=build_research_lane_snapshot('20260929',rows,{'00001':{'name':'样本科技','aliases':['样本科技','00001']}})
    snap['source_manifest'].update(published_at='2026-09-29T19:00:01+08:00')
    result=build_research_archive(snap,source_input_sha256=sha256(json.dumps(snap,sort_keys=True).encode()).hexdigest())
    return snap,result

def consumer(arc):
    mats,gaps=project_archive(arc,dict(status='VERIFIED',payload_path='research/archive.json',payload_sha256=digest(arc)),'20260929')
    ctx=dict(plan_trade_date='20260930',market_session='20260929',focus_window_start=START.isoformat(),research_cutoff=CUT.isoformat())
    cards=project_material_discovery(mats,{'HK.00001':{'name':'样本科技'}},
        dict(status='OWNER_VERIFIED',source_date='20260929',artifact_sha256='b'*64),ctx)
    return mats,cards,material_us_relations(cards,START,CUT),gaps


def test_explicit_original_fields_reach_consumer_without_clock_alias(make_rows):
    rows=make_rows(FIELDS);snap,arc=archive(rows)
    validate_research_archive(arc)
    mats,cards,(_,ind,audit),gaps=consumer(arc)
    assert mats[0]['retrieved_at']==FIELDS['retrieved_at']
    assert mats[0]['available_at']==FIELDS['available_at']
    assert mats[0]['source_row']['related_us_symbols']==['QTEST']
    assert mats[0]['source_row']['source_refs']==FIELDS['source_refs']
    assert 'HK.00001' in ind,audit
    assert ind['HK.00001'][0]['related_us_symbols']==['QTEST']
    assert ind['HK.00001'][0]['is_new_catalyst'] is False


def test_no_source_times_means_missing_not_crawl_time(make_rows):
    rows=make_rows({'related_us_symbols':['QTEST']});_,arc=archive(rows)
    mats,cards,(_,ind,audit),gaps=consumer(arc)
    assert mats[0]['retrieved_at'] is None and mats[0]['available_at'] is None
    assert ind=={} and any('ACQUISITION' in s for s in gaps)
    assert mats[0]['source_time_observations']['available_at']['source_field']=='article.available_at'


@pytest.mark.parametrize('changes',[{'retrieved_at':'not-a-time'}, {'available_at':'2026-09-30T10:00:00+08:00'},
    {'available_at':None}])
def test_bad_original_clock_is_not_repaired_or_admitted(make_rows,changes):
    fields=deepcopy(FIELDS);fields.update(changes)
    rows=make_rows(fields);_,arc=archive(rows)
    mats,cards,(_,ind,audit),gaps=consumer(arc)
    assert ind=={}
    for key,val in changes.items():assert mats[0][key]==val


def test_no_name_to_ticker_invention_even_with_source_metadata(make_rows):
    rows=make_rows({**FIELDS,'related_us_symbols':['LLY']},'样本科技已签署与礼来的合作协议。')
    _,arc=archive(rows);_,_,(_,ind,_),_=consumer(arc)
    assert ind=={}


def test_original_standing_contract_is_forwarded_not_approved(make_rows):
    contract={'schema_version':'v4.manager_research.business_relation_validity.v1','status':'ACTIVE','issuer_symbol':'HK.00001'}
    rows=make_rows({**FIELDS,'business_relation_validity':contract});_,arc=archive(rows)
    mats,*_=consumer(arc)
    assert mats[0]['source_row']['business_relation_validity']==contract
    assert mats[0]['claim_type']=='RESEARCH_OPINION'


def test_passthrough_does_not_change_stage_or_stock_ranking(make_rows):
    r0=make_rows();s0,a0=archive(r0)
    r1=make_rows(FIELDS);s1,a1=archive(r1)
    for key in ['stock_research_timeline','stock_research_daily','research_pool_bridge','research_items']:
        assert s1[key]==s0[key]
    assert a1['stock_pool']==a0['stock_pool']
    for arc in (a0,a1):
        assert arc['production_allowed'] is False and arc['buy_gate_updated'] is False and arc['orders_sent'] is False


def test_conflicting_raw_candidates_do_not_merge_clocks(make_rows):
    rows=make_rows(FIELDS);snap,arc=archive(rows)
    duplicate=deepcopy(snap['raw_items'][0]);duplicate['raw_id']='different';duplicate['raw_payload']['raw_id']='different'
    duplicate['raw_payload']['available_at']='2026-09-29T18:09:00+08:00'
    # The explicit fields live in the original row, never in a generated clock.
    snap['raw_items'].append(duplicate)
    conflict=build_research_archive(snap,source_input_sha256='a'*64)
    mats,_,(_,ind,_),_=consumer(conflict)
    assert ind=={} and mats[0]['available_at'] is None


def test_new_archive_envelope_survives_original_disk_store_and_refs_tamper_is_rejected(make_rows,tmp_path):
    from infrastructure.research_store import ResearchArchiveStore
    rows=make_rows(FIELDS);_,arc=archive(rows)
    store=ResearchArchiveStore(tmp_path/'original-archive')
    receipt=store.publish(arc,mode='REPLAY')
    readback=ResearchArchiveStore(store.root).read_exact('20260929')
    assert readback==arc
    mats,_,(_,ind,_),_=consumer(readback)
    assert ind['HK.00001'][0]['related_us_symbols']==['QTEST']
    assert mats[0]['source_time_observations']['retrieved_at']['source_field']=='article.manager_source_evidence.fields.retrieved_at'
    path=store.root/receipt['payload_path']
    damaged=json.loads(path.read_text())
    damaged['articles'][0]['manager_source_evidence']['fields']['source_refs'][0]['payload_sha256']='d'*64
    path.write_text(json.dumps(damaged))
    with pytest.raises(ValueError,match='manifest or receipt mismatch'):
        ResearchArchiveStore(store.root).read_exact('20260929')


def test_cross_article_identity_never_lends_time_or_ticker(make_rows):
    rows=make_rows(FIELDS);snap,_=archive(rows)
    for raw in snap['raw_items']:
        raw['raw_payload']['stock_code']='00002'
    arc=build_research_archive(snap,source_input_sha256='a'*64)
    mats,_,(_,ind,_),_=consumer(arc)
    assert not ind and mats[0]['available_at'] is None


def test_envelope_cannot_override_claim_status_or_binding_source(make_rows):
    rows=make_rows({**FIELDS,'claim_type':'SOURCE_STATEMENT','verification':'OWNER_VERIFIED'})
    _,arc=archive(rows)
    assert 'claim_type' not in arc['articles'][0]['manager_source_evidence']['fields']
    arc['articles'][0]['manager_source_evidence']['fields']['claim_type']='SOURCE_STATEMENT'
    with pytest.raises(ValueError,match='manager source evidence'):
        validate_research_archive(arc)
