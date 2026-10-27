"""R4: post-enrichment display names and original committed failure evidence."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

W = Path(__file__).parents[1]
API = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/business-gaps-20261027-r1-api/app')
sys.path.insert(0, str(API))


def load(name, rel):
    importlib.import_module(name.rpartition('.')[0])
    spec = importlib.util.spec_from_file_location(name, W / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


graph_owner = load('infrastructure.runtime_graph.current', 'infrastructure/runtime_graph/current.py')
consumer = load('stage_center.consumer', 'stage_center/consumer.py')
projection = load('domains._preselection_parts.source_validation', 'domains/_preselection_parts/source_validation.py')
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
digest = lambda raw: hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()


def failure_fixture(tmp_path, monkeypatch):
    opening, candidates, receipts, graph = [tmp_path / p for p in ('opening', 'candidates', 'receipts', 'graph')]
    for p in (opening, candidates, receipts, graph):
        p.mkdir()
    codes = ('A.000995', 'A.600048')
    candidate = SimpleNamespace(codes=codes, run_id='original-run')
    import stage_center.candidate_input as candidate_owner
    def read_candidate(root, date, *, expected_current_sha256):
        if root != candidates or date != '20261027' or expected_current_sha256 != 'a' * 64:
            raise candidate_owner.CandidateInputError('candidate identity differs')
        return candidate
    monkeypatch.setattr(candidate_owner, 'read_candidate_input', read_candidate)
    receipt = dict(schema_version='stage_center.runner.receipt.v1', runner='stage_center', trade_date='20261027',
        stage_id='STAGE_0925', candidate_current_sha256='a' * 64, candidate_run_id=candidate.run_id, **FLAGS)
    receipt_path = receipts / '20261027/STAGE_0925/receipt.json'
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(wire(receipt))
    attempt = dict(trade_date='20261027', stage_id='STAGE_0925', attempt_id='1' * 32,
        candidate_current_sha256='a' * 64, candidate_run_id=candidate.run_id, authorizes_selection=False,
        RESEARCH_ONLY=True, status='CANNOT_CONFIRM', error='ValueError:A_NATIVE_NO_VALID_OBSERVATION_ROWS',
        finished_at='2026-10-27T09:25:01+08:00', **FLAGS)
    attempt['payload'] = dict(schema_version='stage_center.a_opening_native_snapshot.v1', trade_date='20261027',
        stage_id='STAGE_0925', capture_mode='NATURAL', temporal_cutoff_safe=True, rows=[], requested_symbols=list(codes),
        capture_started_at='2026-10-27T09:25:00+08:00', captured_at='2026-10-27T09:25:00.900000+08:00',
        market_cutoff_at='2026-10-27T09:25:05+08:00', raw_batches=[{'raw_rows':[{'update_time':'2026-10-27 09:30:00'}, {'update_time':''}]}],
        rejected_rows=[{'symbol':c} for c in codes], **FLAGS)
    attempt_path = opening / 'native_opening/20261027/STAGE_0925/attempts' / (attempt['attempt_id'] + '.json')
    attempt_path.parent.mkdir(parents=True)
    attempt_path.write_bytes(wire(attempt))
    hint = dict(schema_version='v4.runtime_graph_hint.v1', owner='STAGE_PRECAPTURE', node_id='PRECAPTURE_A_0925',
        phase='COMMITTED', business_date='20261027', source_path=str(attempt_path), source_sha256=digest(attempt_path.read_bytes()),
        observed_at='2026-10-27T09:25:01.100000+08:00', **FLAGS)
    event = dict(hint=hint, hint_sha256=digest(wire(hint)), **FLAGS)
    event_path = graph / 'runtime_graph/v4/events/event.json'
    event_path.parent.mkdir(parents=True)
    event_path.write_bytes(wire(event))
    payload = dict(trade_date='20261027', stage_id='STAGE_0925', markets={'A_SHARE':consumer._invalid_market('A_SHARE')},
        execution_evidence=dict(observed_sha256=digest(receipt_path.read_bytes()), due_status='DUE',
            candidate_current_sha256='a' * 64, candidate_run_id=candidate.run_id, execution_verified=False, natural_verified=False))
    config = dict(graph_root=str(graph), stage_receipt_root=str(receipts), native_reader_roots=dict(
        stage_a_opening_root=str(opening), stage_candidate_root=str(candidates)))
    return SimpleNamespace(payload=payload, config=config, attempt=attempt, attempt_path=attempt_path,
        event=event, event_path=event_path, receipt_path=receipt_path)


def update_attempt(f):
    f.attempt_path.write_bytes(wire(f.attempt))
    f.event['hint']['source_sha256'] = digest(f.attempt_path.read_bytes())
    f.event['hint_sha256'] = digest(wire(f.event['hint']))
    f.event_path.write_bytes(wire(f.event))


def test_malformed_bound_attempt_shape_remains_unknown(tmp_path, monkeypatch):
    f = failure_fixture(tmp_path, monkeypatch)
    f.attempt = []
    update_attempt(f)
    assert consumer.read_a_opening_source_failure(f.payload, config=f.config) is None


def test_original_committed_sha_failure_is_only_a_display_diagnostic(tmp_path, monkeypatch):
    f = failure_fixture(tmp_path, monkeypatch)
    before = deepcopy(f.payload)
    result = consumer.read_a_opening_source_failure(f.payload, config=f.config)
    assert result['source_status'] == 'CANNOT_CONFIRM'
    assert (result['requested_rows'], result['source_rows']) == (2, 0)
    assert any('source_time_after_capture=1;source_time_missing=1' in s for s in result['source_evidence'])
    assert any('NOT_INDEPENDENT_CERTIFICATION' in s for s in result['source_evidence'])
    assert f.payload == before and not f.payload['execution_evidence']['natural_verified']


@pytest.mark.parametrize('defect', ['absent_event','raw_sha','hint_sha','date','stage','candidate','candidate_sha',
    'safety','receipt_sha','ambiguous','not_due','success_manifest','accepted_rows','clock','outside_root'])
def test_unbound_or_conflicting_failure_remains_unknown(tmp_path, monkeypatch, defect):
    f = failure_fixture(tmp_path, monkeypatch)
    if defect == 'absent_event': f.event_path.unlink()
    elif defect == 'raw_sha': f.attempt_path.write_bytes(f.attempt_path.read_bytes() + b' ')
    elif defect == 'hint_sha':
        f.event['hint_sha256'] = '0' * 64; f.event_path.write_bytes(wire(f.event))
    elif defect in ('date','stage','candidate','safety','accepted_rows','clock'):
        if defect == 'date': f.attempt['trade_date'] = '20261026'
        elif defect == 'stage': f.attempt['stage_id'] = 'STAGE_0930_0935'
        elif defect == 'candidate': f.attempt['candidate_run_id'] = 'another-run'
        elif defect == 'safety': f.attempt['payload']['orders_sent'] = True
        elif defect == 'accepted_rows': f.attempt['payload']['rows'] = [{'symbol':'A.000995'}]
        else: f.attempt['finished_at'] = '2026-10-27T09:25:06+08:00'
        update_attempt(f)
    elif defect == 'candidate_sha': f.payload['execution_evidence']['candidate_current_sha256'] = '0' * 64
    elif defect == 'receipt_sha': f.receipt_path.write_bytes(f.receipt_path.read_bytes() + b' ')
    elif defect == 'ambiguous': (f.event_path.parent / 'duplicate.json').write_bytes(wire(f.event))
    elif defect == 'not_due': f.payload['execution_evidence']['due_status'] = 'NOT_DUE'
    elif defect == 'success_manifest': (f.attempt_path.parent.parent / 'manifest.json').write_text('{}')
    else:
        f.event['hint']['source_path'] = '/tmp/other.json'
        f.event['hint_sha256'] = digest(wire(f.event['hint'])); f.event_path.write_bytes(wire(f.event))
    assert consumer.read_a_opening_source_failure(f.payload, config=f.config) is None


def test_stage_walker_changes_only_display_fields_and_never_hk_news_or_score(tmp_path, monkeypatch):
    import upstreams.v3_shared_data.shared_data.a_share_security_master as master
    names = {'300860':'锋尚文化', '300473':'德尔股份', '600865':'百大集团'}
    rows = [dict(code=prefix+code, stock_code=prefix+code, name=None, stock_name=None, trade_date='20261027',
        stage_score=117.49, formal_eligible=False, news_missing_reason='original missing name', features={'name':None})
        for prefix,code in [('SZ.','300860'),('SZ.','300473'),('SH.','600865')]]
    current = {code:dict(ts_code=code+('.SH' if code.startswith('6') else '.SZ'), name=name,
        observed_at='2026-10-27T10:00:00+08:00', available_at='2026-10-27T10:00:00+08:00', evidence_sha256='a'*64)
        for code,name in names.items()}
    monkeypatch.setenv('V4_MANAGER_SECURITY_MASTER_ROOT', str(tmp_path))
    monkeypatch.setattr(master, 'load_current_display_names', lambda *a: (current, {'run_id':'original107','observation_date':'20261027'}))
    monkeypatch.setattr(consumer.StageSelectionConsumer, '_load_a_name_authority', lambda *a:{'mapping':{},'conflicted_codes':[]})
    value=dict(markets={'A':{'rows':rows},'HK':{'rows':[{'code':'HK.09903','name':None}]}},
        selection_markets={'A_SHARE':{'rows':rows}},market_summaries={'A':{'rows':rows}},unified_rows=rows)
    original=deepcopy(value)
    output=projection.project_a_display_names(value,'20261027',tmp_path,as_of=datetime.fromisoformat('2026-10-27T20:00:00+08:00'))
    for row in output['markets']['A']['rows']:
        assert row['name']==names[row['code'][3:]] and row['stock_name']==row['name']
        assert row['stage_score']==117.49 and row['formal_eligible'] is False
        assert row['features']=={'name':None} and row['news_missing_reason']=='original missing name'
        assert row['display_identity']['observed_at']=='2026-10-27T10:00:00+08:00'
    assert value==original and output['markets']['HK']==original['markets']['HK']
    assert output['selection_markets']['A_SHARE']['rows'][0]['name']=='锋尚文化'


def test_api_projects_names_after_original_news_enrichment(tmp_path, monkeypatch):
    api=load('apps.api.v35_api.app','apps/api/v35_api/app.py')
    import stage_center.news_link_projection as news
    import infrastructure.runtime_graph.current as graph
    order=[]
    def enrich(rows,*a,**k):
        assert rows[0]['name'] is None
        order.append('original_enrichment')
        return [{**r,'news_missing_reason':'original missing name'} for r in rows]
    def display(response,*a,**k):
        assert order==['original_enrichment']
        assert response['markets']['A']['rows'][0]['news_missing_reason']=='original missing name'
        order.append('display');return response
    monkeypatch.setattr(news,'project_news_links',enrich)
    monkeypatch.setattr(projection,'project_a_display_names',display)
    monkeypatch.setattr(graph,'load_config',lambda: {})
    row=dict(code='SZ.300860',stock_code='SZ.300860',name=None,stock_name=None,rank=1,stage_score=117.49)
    payload=dict(trade_date='20261027',stage_id='STAGE_0930_0935',status='PARTIAL_WITH_ROWS',
        markets={'A_SHARE':dict(market='A_SHARE',status='PARTIAL_WITH_ROWS',rows=[row])},execution_evidence={})
    monkeypatch.setattr(api.StageSelectionConsumer,'get',lambda *a,**k:deepcopy(payload))
    app=api.create_app(data_root=tmp_path,stage_center_selection_root=tmp_path/'selection')
    route=next(r for r in app.routes if getattr(r,'path',None)=='/api/v3/workbench/stage' and 'GET' in r.methods)
    result=route.endpoint(date='20261027',stage='STAGE_0930_0935',limit=10)
    assert order==['original_enrichment','display'] and result['markets']['A']['rows'][0]['stage_score']==117.49


@pytest.mark.parametrize('limit', [0,10001,True,'4096'])
def test_original_event_reader_rejects_unbounded_or_invalid_scan_limit(tmp_path,limit):
    with pytest.raises(ValueError,match='GRAPH_EVENT_SCAN_LIMIT_INVALID'):
        graph_owner.read_events({'graph_root':str(tmp_path)},'PRECAPTURE_A_0925',128,scan_limit=limit)


def test_original_event_reader_default_unchanged_explicit_extension_finds_older_event(tmp_path,monkeypatch):
    root=tmp_path/'runtime_graph/v4/events';root.mkdir(parents=True)
    for i in range(2001):
        p=root/(str(i)+'.json');p.write_bytes(wire({'hint':{'node_id':'PRECAPTURE_A_0925' if i==0 else 'other'}}))
        import os
        os.utime(p,(i+100,i+100))
    config={'graph_root':str(tmp_path)}
    assert graph_owner.read_events(config,'PRECAPTURE_A_0925',128)['events']==[]
    assert len(graph_owner.read_events(config,'PRECAPTURE_A_0925',128,scan_limit=4096)['events'])==1
