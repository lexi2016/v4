import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest


def test_candidate_gaps_remain_pool_evidence_and_do_not_erase_source_gaps():
    from stage_center._runner_parts.row_evidence import __with_candidate_evidence_body
    from stage_center.acquisition import SourceResult
    scope = {'replace': replace}
    candidate = SimpleNamespace(current_sha256='a'*64, strict_schema='v3', run_id='r',
        source_pool_provenance_sha256='b'*64, cannot_confirm=('P1:SOURCE_REJECTED:missing',),
        source_pool_provenance=({'pool_id':'P1','status':'CANNOT_CONFIRM','diagnostics':['SOURCE_REJECTED:missing']},))
    source = SourceResult('test','PARTIAL_WITH_ROWS',rows=({'code':'A.000001'},),cannot_confirm=('QUOTE_MISSING',))
    actual = __with_candidate_evidence_body(scope, source, candidate, (), candidate_sha='a'*64,candidate_run_id='r')
    assert actual.status == 'PARTIAL_WITH_ROWS' and actual.cannot_confirm == ('QUOTE_MISSING',)
    assert 'candidate_pool_gap=P1:SOURCE_REJECTED:missing' in actual.source_evidence


def test_beijing_exchange_is_not_mapped_to_shanghai():
    from infrastructure.tdx_minute_replay_provider import _market_and_code
    with pytest.raises(ValueError): _market_and_code('A.920509')
    assert _market_and_code('A.600000') == (1,'600000')
    assert _market_and_code('A.000001') == (0,'000001')


def test_partial_trio_requires_completed_time_and_declared_hashes(tmp_path):
    from infrastructure.research_source_evidence import read_zsxq_slot_evidence
    date, slot = '20261027','0900'
    run = f'{date}_{slot}00_090000123456'; rel=f'external_sources/zsxq_hourly/{run}'
    folder=tmp_path/rel; folder.mkdir(parents=True)
    safety={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    summary={'ok':True,'raw_topic_count':1,'effective_topic_count':1,'effective_topics':[{}],**safety}
    fetch={'ok':True,'success':True,'page_count':1,'count':1,'groups':[{'source_has_more':True}],**safety}
    def put(p,v): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v),encoding='utf-8')
    sp=folder/'zsxq_summary.json'; fp=folder/'zsxq_recent_topics_fetch_result.json'; put(sp,summary);put(fp,fetch)
    status_rel=f'research_module/runtime_outputs/zsxq_hourly/{date}/{slot}/v35_zsxq_hourly_status_{date}_{slot}.json'
    st={'schema_version':'v3_5.zsxq_hourly_delta.v1','source':'zsxq','trade_date':date,'slot':slot,
        'status_path':status_rel,'fetch_ok':True,'status':'PARTIAL','latest_run_id':run,'fetched_at':'2026-10-27T09:00:00+08:00',
        'source_completed_at':'2026-10-27T09:01:00+08:00','source_cutoff':'2026-10-27T09:00:59+08:00',
        'summary_sha256':hashlib.sha256(sp.read_bytes()).hexdigest(),'fetch_result_sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),
        'page_count':1,'topic_count':1,'effective_topic_count':1,'cannot_confirm':['ZSXQ_PAGINATION_BOUNDED_HAS_MORE'],
        'paths':{'run_dir':rel,'summary':f'{rel}/zsxq_summary.json','fetch_result':f'{rel}/zsxq_recent_topics_fetch_result.json'},**safety}
    p=tmp_path/status_rel;put(p,st)
    assert read_zsxq_slot_evidence(tmp_path,date,slot).status['status']=='PARTIAL'
    for key,value in [('summary_sha256','0'*64),('source_completed_at','2026-10-28T09:01:00+08:00'),('source','other'),('source_completed_at','2099-10-27T09:01:00+08:00')]:
        bad={**st,key:value};put(p,bad);assert read_zsxq_slot_evidence(tmp_path,date,slot) is None
    bad=st.copy();bad.pop('source_completed_at');put(p,bad);assert read_zsxq_slot_evidence(tmp_path,date,slot) is None


def test_0925_rejects_0930_and_tdx_empty_and_bj():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from infrastructure.stage_quote_provider import NativeAOpeningSnapshotProvider
    now = datetime(2026,10,28,9,25,2,tzinfo=ZoneInfo('Asia/Shanghai'))
    class Primary:
        def snapshot(self, symbols, **kwargs):
            return {'trade_date':'20261028','stage_id':'STAGE_0925','source':'fixture',
              'capture_started_at':now.isoformat(),'captured_at':now.isoformat(),
              'rows':[{'symbol':'A.000001','source_update_time':'2026-10-28 09:30:00','last_price':10}],
              'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    class EmptyFallback:
        def snapshot(self, symbols, **kwargs):
            assert symbols == ('A.000001',)
            raise ValueError('TDX_NATIVE_QUOTES_UNAVAILABLE:zero_rows')
    result=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=EmptyFallback(),now=lambda:now).snapshot(
        ['A.000001','A.920509'],trade_date='20261028')
    assert result['rows']==[] and set(result['missing_symbols'])=={'A.000001','A.920509'}
    assert any('TDX_NATIVE_QUOTES_UNAVAILABLE' in error for error in result['errors'])
    assert any(x['symbol']=='A.920509' for x in result['rejected_rows'])


def test_producer_binds_complete_clock_and_bytes(tmp_path,monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ops import run_zsxq_hourly_delta as owner
    from infrastructure.research_source_evidence import read_zsxq_slot_evidence
    current=datetime.now(ZoneInfo('Asia/Shanghai'))
    day=current.strftime('%Y%m%d')
    monkeypatch.setattr(owner,'collect_paginated_topics',lambda **kwargs: {
        'topics':[{'topic_id':'t'}], 'bounded_has_more':True,'page_count':1,
        'group_results':[{'group_id':'g','source_has_more':True,'reached_since':False}],
    })
    result=owner.materialize_zsxq_hourly_delta(data_root=tmp_path,trade_date=day,slot='0900',
        analyzer=lambda *_: {'raw_topic_count':1,'effective_topic_count':1,'effective_topics':[{}]}, now=current)
    assert result['status']=='PARTIAL'
    assert datetime.fromisoformat(result['source_completed_at']) >= datetime.fromisoformat(result['fetched_at'])
    evidence=read_zsxq_slot_evidence(tmp_path,day,'0900')
    assert evidence is not None and evidence.summary_sha256==result['summary_sha256']
    assert evidence.fetch_result_sha256==result['fetch_result_sha256']


def test_partial_consumer_reports_gap_when_manager_attestation_rejects(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ops import collect_hourly_research_input as owner
    from infrastructure import manager_input_attestation as attestation
    now=datetime.now(ZoneInfo('Asia/Shanghai'));day=now.strftime('%Y%m%d')
    status={'status':'PARTIAL','fetched_at':now.isoformat(),'source_completed_at':now.isoformat(),'source_cutoff':f'{day[:4]}-{day[4:6]}-{day[6:]}T09:00:59+08:00','slot':'0900','status_path':'status.json'}
    selected=(tmp_path/'status.json',status);trio=({'effective_topics':[{}]}, {}, 'a'*64,'b'*64,'c'*64)
    monkeypatch.setattr(owner,'_latest_zsxq_status',lambda *a,**k:selected)
    monkeypatch.setattr(owner,'_read_status_artifacts',lambda *a,**k:trio)
    row={'stock_code':'000001','stock_name':'test','source_path':'status.json'}
    monkeypatch.setattr(owner,'_zsxq_rows',lambda *a,**k:([row],['ZSXQ_SOURCE_PARTIAL_INCOMPLETE']))
    monkeypatch.setattr(owner,'build_research_lane_snapshot',lambda *a,**k:{'source_manifest':{'source_types':['zsxq']},'stock_research_timeline':[row],'quality_status':'READY','cannot_confirm':[]})
    def reject(*a,**k):raise attestation.PublicationError('PARTIAL_SOURCE_NOT_SUPPORTED')
    monkeypatch.setattr(attestation,'publish_attestation',reject)
    result=owner.build_hourly_research_input(data_root=tmp_path,business_date=day,slot='0900')
    assert result['status']=='PARTIAL_WITH_ROWS' and result['source_status']=='PARTIAL'
    assert result['manager_publication']['status']=='INPUT_MISSING'
    data=json.loads((tmp_path/result['source_path']).read_text())
    assert data['hourly_research']['status']=='PARTIAL_WITH_ROWS'
    assert data['source_manifest']['zsxq_source_completeness']=='PARTIAL'
    assert data['source_manifest']['zsxq_summary_sha256']=='b'*64
