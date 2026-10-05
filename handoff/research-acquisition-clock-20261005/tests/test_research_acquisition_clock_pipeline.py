"""Synthetic source/clock/master; HK positives inject an analyzer result.

Default-adapter tests below establish only A-share entry and HK exclusion.

No network or historical owner data is accessed. Removing receipt propagation
must make the successful Manager relation test fail, without weakening PIT.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ops import run_zsxq_hourly_delta as capture
from ops.collect_hourly_research_input import build_hourly_research_input
from ops.run_hourly_research import run_hourly_research_file
from domains.research import build_research_archive
from domains.research_hourly import validate_hourly_stage_source
from infrastructure.research_lane_source import ResearchLaneSource
from v4.manager_research.existing_materials import _read_archive
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.research_attention import build_research_attention
from contracts.research import validate_research_archive

DAY = '20260925'
START = '2026-09-25T08:40:00+08:00'
RETRIEVED = '2026-09-25T08:45:12.123456+08:00'
AVAILABLE = '2026-09-25T08:46:01.654321+08:00'
BODY = '星海科技与US.VRT签署数据中心设备供货协议。' * 3
CTX = dict(plan_trade_date='20260928', market_session=DAY,
           focus_window_start='2026-09-24T16:10:00+08:00', research_cutoff='2026-09-28T08:00:00+08:00')
MASTER = {'HK.01234': {'name': '星海科技'}}
IDENTITY = dict(status='OWNER_VERIFIED', source_date=DAY, artifact_sha256='a'*64,
                owner='SYNTHETIC_MASTER', manifest_sha256='b'*64)


def produce(tmp_path, monkeypatch, *, real_selector_panel=None, pages=1):
    calls = []
    topic = dict(topic_id='12345678901234567', create_time='2026-09-25T08:30:00+08:00', content=BODY)
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(dict(topics=[topic] if len(calls) == 1 else [], has_more=len(calls) < pages)), '')
    # Lookup/analyzer port is synthetic; all time acquisition and persistence
    # remain in the actual collector. Consumer subject parsing is not mocked.
    def analyzer(recent, _panel, _root):
        assert recent['topics_brief'][0]['content'] == BODY
        return dict(effective_topic_count=1, effective_topics=[dict(topic,
            title='星海科技数据中心供货', content_head=BODY, evidence=BODY,
            companies=[dict(code='01234', name='星海科技')], themes=[dict(theme='数据中心')])])
    clock = iter([RETRIEVED, AVAILABLE])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert len(calls) == pages  # No acquisition clock before final page returns.
            value = next(clock)
            if value == AVAILABLE:
                assert list(tmp_path.glob('external_sources/zsxq_hourly/*/zsxq_summary.json'))
            return datetime.fromisoformat(value)
    monkeypatch.setattr(capture, 'datetime', Clock)
    status = capture.materialize_zsxq_hourly_delta(data_root=tmp_path, trade_date=DAY, slot='0900',
        groups=[('SYNTHETIC', 'SYNTHETIC')], process_runner=runner,
        **(dict(selector_panel=real_selector_panel, refetch_root=Path(capture.__file__).resolve().parents[1]/"upstreams")
           if real_selector_panel else dict(analyzer=analyzer)),
        now=datetime.fromisoformat(START))
    assert len(calls) == pages
    return status


def snapshot(tmp_path):
    result = build_hourly_research_input(data_root=tmp_path, business_date=DAY, slot='0900')
    return json.loads((tmp_path/result['source_path']).read_bytes())


def archive(source):
    return build_research_archive(source, source_input_sha256=hashlib.sha256(
        json.dumps(source, sort_keys=True).encode()).hexdigest())


def manager(tmp_path, payload, *, identity=IDENTITY, context=CTX):
    lane = ResearchLaneSource(tmp_path)
    lane.store.publish(payload, mode='LIVE')
    materials, gaps, binding = _read_archive(lane, DAY, '')
    attention = manager_attention(materials, identity=identity, context=context)
    return materials, gaps, binding, attention


def manager_attention(materials, *, identity=IDENTITY, context=CTX):
    cards = project_material_discovery(materials, MASTER, identity, context)
    us = dict(status='READY', mapping_eligible=True, captured_at='2026-09-25T20:15:06Z',
        expected_us_session=DAY, source_identity=dict(status='VERIFIED', payload_sha256='f'*64,
            receipt_sha256='1'*64, manifest_sha256='2'*64),
        raw_industry_up=[], raw_individual_up=[dict(symbol='VRT', change_pct=2, session_date=DAY)])
    attention = build_research_attention(context['plan_trade_date'], context=context, market_screen={},
        stocks=[], material_cards=cards, themes=[], announcement_observation={}, us_market=us)
    return attention


def test_real_capture_boundaries_are_preserved_in_status_and_frozen_input(tmp_path, monkeypatch):
    status = produce(tmp_path, monkeypatch)
    receipt = status['acquisition_receipt']
    assert receipt['retrieved_at'] == RETRIEVED != status['fetched_at']
    assert receipt['available_at'] == AVAILABLE
    assert receipt['summary_sha256'] == hashlib.sha256(Path(status['paths']['summary']).read_bytes()).hexdigest()
    source = snapshot(tmp_path)
    for collection in ('research_items', 'stock_research_timeline'):
        row = source[collection][0]
        assert row['retrieved_at'] == RETRIEVED
        assert row['available_at'] == AVAILABLE
        assert row['acquisition_provenance']['status_sha256'] == hashlib.sha256(
            (tmp_path/status['status_path']).read_bytes()).hexdigest()


def test_injected_hk_analyzer_output_archive_consumers_reach_manager_relation(tmp_path, monkeypatch):
    produce(tmp_path/'producer', monkeypatch)
    source = snapshot(tmp_path/'producer'); before = deepcopy(source)
    payload = archive(source)
    article = payload['articles'][0]
    assert article['retrieved_at'] == RETRIEVED
    assert article['available_at'] == AVAILABLE
    assert source == before
    materials, gaps, binding, attention = manager(tmp_path/'archive', payload)
    assert binding['status'] == 'VERIFIED'
    assert not any('ACQUISITION_TIME_MISSING' in gap for gap in gaps)
    assert materials[0]['retrieved_at'] == RETRIEVED
    assert attention['us_mapping_diagnostics']['accepted_hk_mapping_count'] == 1
    assert attention['cards'][0]['symbol'] == 'HK.01234'
    assert attention['cards'][0]['decision']['state'] != 'INSUFFICIENT'
    assert attention['production_allowed'] is False and attention['orders_sent'] is False


def test_new_acquisition_after_slot_cannot_hide_behind_old_start_clock(tmp_path, monkeypatch):
    produce(tmp_path, monkeypatch); source = snapshot(tmp_path)
    assert source['source_manifest']['pit_cutoff'] == '2026-09-25T09:00:59+08:00'
    validate_hourly_stage_source(source, trade_date=DAY, slot='0900',
        cutoff=datetime.fromisoformat('2026-09-25T09:00:59+08:00'))
    # Actual acquisition becomes later than the slot, while every legacy clock
    # remains early. Both the existing runner and Stage call this validator.
    source['stock_research_timeline'][0]['available_at'] = '2026-09-25T09:01:00+08:00'
    with pytest.raises(ValueError, match='PIT_MISMATCH:stock_research_timeline.available_at'):
        validate_hourly_stage_source(source, trade_date=DAY, slot='0900',
            cutoff=datetime.fromisoformat('2026-09-25T09:00:59+08:00'))


def test_injected_hk_output_hourly_runner_checks_sha_and_keeps_retry_bytes(tmp_path, monkeypatch):
    produce(tmp_path, monkeypatch)
    result = build_hourly_research_input(data_root=tmp_path, business_date=DAY, slot='0900')
    source_path = tmp_path/result['source_path']; source_bytes = source_path.read_bytes()
    arguments = dict(data_root=tmp_path, source=source_path, business_date=DAY,
        target_date=DAY, slot='0900', mode='LIVE', expected_source_sha256=result['source_sha256'])
    with pytest.raises(ValueError, match='SOURCE_SHA_MISMATCH'):
        run_hourly_research_file(**{**arguments, 'expected_source_sha256':'0'*64})
    run = run_hourly_research_file(**arguments)
    assert run['status'] == 'SUCCEEDED'
    lane = ResearchLaneSource(tmp_path)
    payload = lane.hourly_store.read_exact(DAY,'0900',mode='LIVE')
    assert payload['source_input_sha256'] == hashlib.sha256(source_bytes).hexdigest()
    assert payload['articles'][0]['available_at'] == AVAILABLE
    materials, gaps, binding = _read_archive(lane,DAY,'0900')
    assert binding['status'] == 'VERIFIED' and materials[0]['retrieved_at'] == RETRIEVED
    assert not any('ACQUISITION_TIME_MISSING' in gap for gap in gaps)
    attention = manager_attention(materials)
    assert attention['us_mapping_diagnostics']['accepted_hk_mapping_count'] == 1
    assert attention['production_allowed'] is False and attention['orders_sent'] is False
    saved = {p:p.read_bytes() for p in tmp_path.rglob('*.json')}
    again = run_hourly_research_file(**arguments)
    assert again['payload_sha256'] == run['payload_sha256']
    assert source_path.read_bytes() == source_bytes
    assert all(p.read_bytes()==raw for p,raw in saved.items())


@pytest.mark.parametrize('problem', ['missing_receipt','wrong_summary_sha','changed_summary',
    'wrong_run','wrong_path','missing_pair','naive','malformed','reversed','before_publication'])
def test_unproven_acquisition_stays_unknown_and_does_not_make_us_relation(tmp_path, monkeypatch, problem):
    status = produce(tmp_path/'producer', monkeypatch)
    proof = status['acquisition_receipt']
    if problem == 'missing_receipt': status.pop('acquisition_receipt')
    if problem == 'wrong_summary_sha': proof['summary_sha256'] = '0'*64
    if problem == 'changed_summary':
        path = Path(status['paths']['summary']); data = json.loads(path.read_bytes())
        data['effective_topics'][0]['content_head'] += 'changed'
        path.write_text(json.dumps(data))
    if problem == 'wrong_run': proof['run_id'] = 'different'
    if problem == 'wrong_path': proof['summary_path'] = 'different.json'
    if problem == 'missing_pair': proof.pop('retrieved_at')
    if problem == 'naive': proof['retrieved_at'] = '2026-09-25T08:45:00'
    if problem == 'malformed': proof['retrieved_at'] = 'yesterday'
    if problem == 'reversed': proof['retrieved_at'] = '2026-09-25T08:47:00+08:00'
    if problem == 'before_publication': proof['retrieved_at'] = '2026-09-25T08:29:59+08:00'
    (tmp_path/'producer'/status['status_path']).write_text(json.dumps(status))
    payload = archive(snapshot(tmp_path/'producer'))
    assert 'available_at' not in payload['articles'][0]
    _materials, gaps, _binding, attention = manager(tmp_path/'archive', payload)
    assert any('ACQUISITION_TIME_MISSING' in gap for gap in gaps)
    diagnostics = attention['us_mapping_diagnostics']
    assert diagnostics['accepted_hk_mapping_count'] is None
    assert diagnostics['assessment_state'] in ('INSUFFICIENT','NOT_EVALUATED')


def test_cutoff_and_issuer_identity_are_still_required_after_valid_capture(tmp_path, monkeypatch):
    produce(tmp_path/'producer', monkeypatch); payload = archive(snapshot(tmp_path/'producer'))
    context = {**CTX, 'research_cutoff': '2026-09-25T08:45:30+08:00'}
    late = manager(tmp_path/'late', payload, context=context)[3]
    assert not late['cards']
    with pytest.raises(ValueError, match='NATIVE_IDENTITY_NOT_VERIFIED'):
        manager(tmp_path/'wrong', payload, identity={**IDENTITY, 'status':'UNVERIFIED'})


def test_third_party_sentence_does_not_gain_an_issuer_relation(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__, fromlist=['BODY']), 'BODY',
        '星海科技发布营收公告。另一家公司与US.VRT签署数据中心设备供货协议。')
    produce(tmp_path/'producer', monkeypatch)
    attention = manager(tmp_path/'archive', archive(snapshot(tmp_path/'producer')))[3]
    assert not any('US_INDIVIDUAL_MAPPING' in row['qualified_lanes'] for row in attention['cards'])


def test_legacy_success_is_reused_without_new_clock_or_file_changes(tmp_path, monkeypatch):
    status = produce(tmp_path, monkeypatch); status.pop('acquisition_receipt')
    path = tmp_path/status['status_path']; path.write_text(json.dumps(status))
    source = snapshot(tmp_path); old = archive(source)
    assert 'retrieved_at' not in old['articles'][0]
    lane = ResearchLaneSource(tmp_path/'archive'); lane.store.publish(old, mode='LIVE')
    saved = {p: p.read_bytes() for p in tmp_path.rglob('*.json')}
    reused = capture.materialize_zsxq_hourly_delta(data_root=tmp_path, trade_date=DAY, slot='0900',
        process_runner=lambda *_a, **_k: pytest.fail('legacy data must not be refetched'))
    assert reused['reused'] is True and 'acquisition_receipt' not in reused
    validate_research_archive(lane.store.read_exact(DAY))
    assert archive(deepcopy(source)) == old
    assert all(p.read_bytes() == data for p, data in saved.items())


def test_extended_archive_requires_complete_pair_proof_and_original_identity(tmp_path, monkeypatch):
    produce(tmp_path, monkeypatch); source = snapshot(tmp_path); payload = archive(source)
    legacy_source = deepcopy(source)
    for row in legacy_source['stock_research_timeline']:
        for key in ('retrieved_at','available_at','acquisition_provenance'):row.pop(key,None)
    legacy = archive(legacy_source)
    for field in ('article_id','dedupe_key'):
        assert payload['articles'][0][field] == legacy['articles'][0][field]
    for key in ('retrieved_at','available_at','acquisition_provenance'):
        bad = deepcopy(payload);bad['articles'][0].pop(key)
        with pytest.raises(ValueError):validate_research_archive(bad)
    bad = deepcopy(payload);bad['articles'][0]['retrieved_at'] = '2026-09-25T08:30:00+08:00'
    with pytest.raises(ValueError,match='binding'):validate_research_archive(bad)


def test_merged_different_receipts_cannot_lend_earlier_clocks_to_later_text(tmp_path, monkeypatch):
    produce(tmp_path, monkeypatch); source = snapshot(tmp_path)
    row = deepcopy(source['stock_research_timeline'][0]); row['evidence_sentence'] += ' later content'
    row['acquisition_provenance']['summary_sha256'] = '0'*64
    source['stock_research_timeline'].append(row)
    payload = archive(source)
    assert payload['articles'][0]['duplicate_evidence_count'] == 2
    assert 'available_at' not in payload['articles'][0]


@pytest.mark.parametrize('market', ['A', 'HK'])
def test_default_production_adapter_market_boundary(tmp_path, monkeypatch, market):
    """Synthetic parquet/topics; actual lookup, analyzer and collector unchanged.

    This deliberately shows the HK production entry is NOT established by the
    injected-analyzer tests above. No fabricated HK->A identity conversion.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    panel = tmp_path/'selector.parquet'
    rows = [dict(trade_date=DAY, ts_code=f'{600000+i:06d}.SH', name=f'合成公司{i}')
            for i in range(1000)]
    # Even a supplied HK panel row must be filtered by the actual A-only lookup.
    rows[0]['name'] = '合成甲企'
    rows += [dict(trade_date=DAY, ts_code='00300.HK', name='合成港企'),
             dict(trade_date=DAY, ts_code='HK.00300', name='合成港企')]
    pq.write_table(pa.Table.from_pylist(rows), panel)
    company = '合成甲企（600000）' if market == 'A' else '合成港企（HK.00300）'
    monkeypatch.setattr(__import__(__name__, fromlist=['BODY']), 'BODY',
        (company + '与US.VRT签署数据中心设备供货协议，提供服务器电源及液冷设备，相关订单按合同交付。') * 3)
    status = produce(tmp_path/'data', monkeypatch, real_selector_panel=panel)
    summary = json.loads(Path(status['paths']['summary']).read_bytes())
    assert summary['stock_lookup_health']['ok'] is True
    assert summary['stock_lookup_health']['master_count'] == 1000
    assert summary['effective_topics']  # HK text is retained, not a fetch failure.
    codes = {c['code'] for t in summary['effective_topics'] for c in t['companies'] if c.get('code')}
    source = snapshot(tmp_path/'data')
    if market == 'HK':
        assert not codes
        assert source['stock_research_timeline'] == []
        with pytest.raises(ValueError, match='research archive requires articles'):
            archive(source)
    else:
        assert codes == {'600000.SH'}
        assert source['stock_research_timeline']
        result = build_hourly_research_input(data_root=tmp_path/'data', business_date=DAY, slot='0900')
        run = run_hourly_research_file(data_root=tmp_path/'data',
            source=tmp_path/'data'/result['source_path'], business_date=DAY, target_date=DAY,
            slot='0900', mode='LIVE', expected_source_sha256=result['source_sha256'])
        assert run['status'] == 'SUCCEEDED'
        materials, gaps, binding = _read_archive(ResearchLaneSource(tmp_path/'data'), DAY, '0900')
        assert binding['status'] == 'VERIFIED'
        assert materials and all(row['available_at'] == AVAILABLE for row in materials)
        assert not any('ACQUISITION_TIME_MISSING' in gap for gap in gaps)


def test_receipt_is_recorded_only_after_all_pages_complete(tmp_path, monkeypatch):
    status = produce(tmp_path, monkeypatch, pages=2)
    assert status['acquisition_receipt']['retrieved_at'] == RETRIEVED
    assert snapshot(tmp_path)['stock_research_timeline'][0]['available_at'] == AVAILABLE


def test_actual_capture_clock_rollback_never_produces_qualified_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__, fromlist=['AVAILABLE']), 'AVAILABLE',
                        '2026-09-25T08:44:00+08:00')
    status = produce(tmp_path, monkeypatch)
    assert status['acquisition_receipt']['retrieved_at'] > status['acquisition_receipt']['available_at']
    payload = archive(snapshot(tmp_path))
    assert 'available_at' not in payload['articles'][0]


@pytest.mark.parametrize('changed', ['summary', 'status'])
def test_capture_artifact_change_during_input_read_discards_pair(tmp_path, monkeypatch, changed):
    from ops import collect_hourly_research_input as collector
    status = produce(tmp_path, monkeypatch)
    original = collector._read_json
    summary_path = Path(status['paths']['summary'])
    status_path = tmp_path/status['status_path']
    def read_then_replace(path):
        value = original(path)
        if Path(path) == summary_path:
            target = summary_path if changed == 'summary' else status_path
            data = json.loads(target.read_bytes())
            data['synthetic_concurrent_writer'] = True
            target.write_text(json.dumps(data))
        return value
    monkeypatch.setattr(collector, '_read_json', read_then_replace)
    payload = archive(snapshot(tmp_path))
    assert 'available_at' not in payload['articles'][0]
