"""Bounded regressions: actual frozen sources/CLI/store/context and stage builder.

V4_STAGE_GAP_FIXTURES points at the uploaded bundle, never a market-data root.
Synthetic mutations below are negative/contract tests, not historical results.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_store import HourlyResearchStore
from domains.research_hourly import project_hourly_stage_fields
from ops.run_hourly_research import run_hourly_research_file
from stage_center.research_context import ResearchContextError, load_research_context

FIXTURE_SHAS = {
    '0900': '2c1623db0e8835ea3d6f98363cb7980c8e14b3dc272672d8e9794688db41dd63',
    '1400': '72f1079ee65747ff040cebc77f3eb0ca0d8e849362bfbeef75e5acbdcc6f3a99',
}
ROOT = Path(sys.modules[run_hourly_research_file.__module__].__file__).resolve().parents[1]


def source_file(slot='0900'):
    configured = os.environ.get('V4_STAGE_GAP_FIXTURES')
    assert configured, 'V4_STAGE_GAP_FIXTURES must name the provided, SHA-pinned bundle'
    p = Path(configured) / 'frozen' / f'source_{slot}.json'
    assert hashlib.sha256(p.read_bytes()).hexdigest() == FIXTURE_SHAS[slot]
    return p


def source_value(slot='0900'):
    return json.loads(source_file(slot).read_bytes())


def join_key(row, *, evidence=False):
    return tuple(row.get(k, '') for k in ('trade_date','source_type','source_name','source_path','url')) + (
        row.get('source_title' if evidence else 'title',''),
        row.get('display_event_time') or row.get('event_time'),
        row.get('source_published_at',''), row.get('first_seen_at',''), row.get('last_checked_at',''))


def mapped_item(source):
    for item in source['research_items']:
        matches=[row for row in source['stock_research_timeline'] if join_key(row,evidence=True)==join_key(item)]
        if matches:
            return item, matches
    raise AssertionError('fixture has no exact copied-identity item/evidence pair')


def witness(root, sha):
    return root / 'research/hourly/source' / f'{sha}.json'


def run_cli(root, source, slot='0900', extra=()):
    args = [sys.executable, '-B', '-m', 'ops.run_hourly_research', '--data-root', str(root),
            '--date', '20260915', '--target-date', '20260915', '--slot', slot,
            '--mode', 'LIVE', '--source', str(source), *extra]
    p = subprocess.run(args, cwd=ROOT, env=os.environ.copy(), text=True,
                       capture_output=True, timeout=40)
    return p


def materialize(root, source, slot='0900'):
    return run_hourly_research_file(data_root=root, source=source,
        business_date='20260915', target_date='20260915', slot=slot, mode='LIVE')


def changed_source(tmp_path, mutate):
    value = source_value()
    mutate(value)
    p = tmp_path / 'SYNTHETIC_CONTRACT_INPUT.json'
    p.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return p


@pytest.mark.parametrize('slot,cutoff,pool_size', [('0900','09:35:05',21),('1400','14:45:00',34)])
def test_frozen_public_cli_preserves_archive_bytes_and_recovers_declared_flags(tmp_path, slot, cutoff, pool_size):
    root = tmp_path / 'v4-data'
    src = source_file(slot)
    p = run_cli(root, src, slot)
    assert p.returncode == 0, p.stderr
    result = json.loads(p.stdout)
    assert result['external_source_sha256'] == FIXTURE_SHAS[slot]
    assert witness(root, FIXTURE_SHAS[slot]).read_bytes() == src.read_bytes()
    frozen = src.parent
    assert (root / result['payload_path']).read_bytes() == (frozen/f'materialized_payload_{slot}.json').read_bytes()
    assert (root / result['receipt_path']).read_bytes() == (frozen/f'hourly_receipt_{slot}.json').read_bytes()
    context = load_research_context(root, trade_date='20260915', stage_cutoff=cutoff)
    assert context.selected_slot == slot and len(context.by_code) == pool_size
    expected = defaultdict(set)
    for row in source_value(slot)['stock_research_timeline']:
        if row['is_new_since_last_slot'] is True:
            expected['A.'+row['stock_code']].add(row['dedup_key'])
    for code, score in context.by_code.items():
        assert score.research_delta_hits == len(expected[code])
        assert score.research_quality_score is None
        assert score.news_quality_score is None
    assert 'RESEARCH_STAGE_EVIDENCE_MISSING' not in context.cannot_confirm
    assert not any(x.startswith('RESEARCH_DELTA_FLAGS_MISSING:') for x in context.cannot_confirm)
    assert any('source_witness' in e for e in context.source_evidence)
    assert all(result[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent'))
    assert result['source_pit_cutoff'] == source_value(slot)['source_manifest']['pit_cutoff']
    assert result['expected_pit_cutoff'].endswith(':' + slot[2:] + ':59+08:00')
    assert any(
        'v4_hourly_source_pit_cutoff=' + source_value(slot)['source_manifest']['pit_cutoff'] == item
        for item in context.source_evidence
    )
    before = {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in root.rglob('*') if f.is_file()}
    again = run_cli(root, src, slot)
    assert again.returncode == 0 and not json.loads(again.stdout)['latest_updated']
    for rel, sha in before.items():
        assert hashlib.sha256((root/rel).read_bytes()).hexdigest() == sha
    assert hashlib.sha256(src.read_bytes()).hexdigest() == FIXTURE_SHAS[slot]


def test_cli_source_pin_fails_before_any_artifact(tmp_path):
    root = tmp_path/'v4-data'
    p = run_cli(root, source_file(), extra=('--expected-source-sha256','0'*64))
    assert p.returncode != 0
    assert 'SOURCE_SHA_MISMATCH' in p.stderr
    assert not root.exists()


def test_existing_archive_can_bind_source_without_rewriting_archive(tmp_path):
    root = tmp_path/'v4-data'
    first = materialize(root, source_file())
    w = witness(root,FIXTURE_SHAS['0900'])
    assert w.exists()
    w.unlink()
    paths = [root/first['payload_path'], root/first['receipt_path'], root/'manifest.json']
    before = [p.read_bytes() for p in paths]
    second = materialize(root, source_file())
    assert not second['latest_updated']
    assert [p.read_bytes() for p in paths] == before
    assert w.read_bytes() == source_file().read_bytes()


def test_corrupted_source_witness_is_not_used_or_overwritten(tmp_path):
    root=tmp_path/'v4-data'; materialize(root,source_file())
    w=witness(root,FIXTURE_SHAS['0900']); assert w.exists()
    w.write_bytes(b'{}')
    with pytest.raises(ResearchContextError, match='SOURCE.*SHA'):
        load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    with pytest.raises(ValueError, match='SOURCE.*SHA|SOURCE.*CONFLICT'):
        materialize(root,source_file())
    assert w.read_bytes()==b'{}'


def test_missing_witness_keeps_unknown_without_legacy_fallback(tmp_path):
    root=tmp_path/'v4-data'; materialize(root,source_file())
    w=witness(root,FIXTURE_SHAS['0900']); assert w.exists();w.unlink()
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    assert all(s.research_delta_hits is None for s in ctx.by_code.values())
    assert any('SOURCE_WITNESS_MISSING' in g for g in ctx.cannot_confirm)


def test_symlinked_witness_is_refused_without_outside_write(tmp_path):
    root=tmp_path/'v4-data'; materialize(root,source_file())
    w=witness(root,FIXTURE_SHAS['0900']); assert w.exists();w.unlink()
    outside=tmp_path/'outside-source.json';outside.write_bytes(source_file().read_bytes());before=outside.read_bytes()
    w.symlink_to(outside)
    with pytest.raises((ResearchContextError, OSError, ValueError)):
        load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    with pytest.raises((OSError,ValueError)):
        materialize(root,source_file())
    assert outside.read_bytes()==before


@pytest.mark.parametrize('field', ['trade_date','slot','manifest_date','manifest_slot','published_at','item_published_at','raw_observed_at'])
def test_bad_source_identity_and_pit_are_refused(tmp_path,field):
    def mutate(s):
        if field=='trade_date':s['trade_date']='20260914'
        elif field=='slot':s['slot']='1000'
        elif field=='manifest_date':s['source_manifest']['trade_date']='20260914'
        elif field=='manifest_slot':s['source_manifest']['hourly_slot']='1000'
        elif field=='published_at':s['source_manifest']['published_at']='2026-09-15T09:01:00+08:00'
        elif field=='item_published_at':s['research_items'][0]['source_published_at']='2026-09-15T10:00:00+08:00'
        else:s['raw_items'][0]['raw_payload']['last_checked_at']='2026-09-15T10:00:00+08:00'
    p=changed_source(tmp_path,mutate)
    with pytest.raises(ValueError):materialize(tmp_path/'v4-data',p)
    assert not (tmp_path/'v4-data/research/hourly/live/20260915/0900.json').exists()


@pytest.mark.parametrize('declared', ['2026-09-15T08:59:00+08:00', None])
def test_source_manifest_pit_cutoff_is_required_and_slot_bound(tmp_path, declared):
    def mutate(source):
        if declared is None:
            source['source_manifest'].pop('pit_cutoff')
        else:
            source['source_manifest']['pit_cutoff'] = declared
    source = changed_source(tmp_path, mutate)
    with pytest.raises(ValueError, match='PIT_CUTOFF'):
        materialize(tmp_path / 'v4-data', source)
    assert not (tmp_path / 'v4-data').exists()


def test_partial_optional_stage_extension_falls_back_to_exact_source_witness(tmp_path):
    def mutate(source):
        item, _ = mapped_item(source)
        raw = next(row for row in source['raw_items'] if row['raw_id'] == item['raw_id'])
        raw['raw_payload']['quality_score'] = 68.0
        source['source_manifest']['manifest_sha256'] = 'b' * 64
        source['source_manifest']['receipt_sha256'] = 'c' * 64
        source['stage_evidence_v1'] = {'items': [], 'evidence': source['stock_research_timeline']}
    source_path = changed_source(tmp_path, mutate)
    source = json.loads(source_path.read_bytes())
    code = 'A.' + mapped_item(source)[1][0]['stock_code']
    root = tmp_path / 'v4-data'
    result = materialize(root, source_path)
    assert result['status'] == 'SUCCEEDED'
    context = load_research_context(root, trade_date='20260915', stage_cutoff='09:35:05')
    assert context.by_code[code].research_quality_score == 68.0
    assert context.by_code[code].research_delta_hits == 1
    assert 'RESEARCH_STAGE_EVIDENCE_MISSING' not in context.cannot_confirm
    assert any('source_pit_cutoff=' in item for item in context.source_evidence)


def test_missing_raw_id_is_a_code_local_lineage_gap(tmp_path):
    source = source_value()
    item, matches = mapped_item(source)
    item['raw_id'] = ''
    code = 'A.' + matches[0]['stock_code']
    projected, _, gaps = project_hourly_stage_fields(source)
    assert not any(row.get('stock_code') == code for row in projected)
    assert 'RESEARCH_RAW_LINEAGE_MISSING:' + code in gaps


def test_stage_cutoff_checks_actual_publish_seconds_not_just_slot(tmp_path):
    root=tmp_path/'v4-data';materialize(root,source_file())
    with pytest.raises(ResearchContextError,match='PIT|cutoff'):
        load_research_context(root,trade_date='20260915',stage_cutoff='09:00:00')
    assert load_research_context(root,trade_date='20260915',stage_cutoff='09:00:59').selected_slot=='0900'


def test_wrong_date_never_uses_previous_date_or_1400_for_morning(tmp_path):
    root=tmp_path/'v4-data';materialize(root,source_file('1400'),'1400')
    with pytest.raises(ResearchContextError):load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    with pytest.raises(ResearchContextError):load_research_context(root,trade_date='20260916',stage_cutoff='14:45:00')


def test_numeric_quality_is_copied_only_when_explicit_and_finite(tmp_path):
    def mutate(s):
        # Synthetically supply an explicit numeric observation; no item_quality conversion.
        item,_=mapped_item(s);raw=next(r for r in s['raw_items'] if r['raw_id']==item['raw_id'])
        raw['raw_payload']['quality_score']=68.0
    p=changed_source(tmp_path,mutate);s=json.loads(p.read_bytes())
    code=mapped_item(s)[1][0]['stock_code']
    root=tmp_path/'v4-data';materialize(root,p)
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    assert ctx.by_code['A.'+code].research_quality_score==68.0
    assert any(v.research_quality_score is None for v in ctx.by_code.values())


@pytest.mark.parametrize('value',[True,'68','OK',float('nan'),float('inf')])
def test_quality_aliases_and_invalid_numbers_never_become_scores(tmp_path,value):
    def mutate(s):mapped_item(s)[0]['quality_score']=value
    p=changed_source(tmp_path,mutate);root=tmp_path/'v4-data';materialize(root,p)
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    assert all(v.research_quality_score is None for v in ctx.by_code.values())
    assert any('QUALITY_SCORE' in g for g in ctx.cannot_confirm)


def test_one_missing_delta_does_not_poison_other_items_or_numeric_score(tmp_path):
    def mutate(s):
        item,matches=mapped_item(s);item['quality_score']=68
        item.pop('is_new_since_last_slot')
        for raw in s['raw_items']:
            if raw['raw_id']==item['raw_id']:raw['raw_payload'].pop('is_new_since_last_slot')
        for row in s['stock_research_timeline']:
            if row in matches:row.pop('is_new_since_last_slot')
    p=changed_source(tmp_path,mutate);s=json.loads(p.read_bytes());root=tmp_path/'v4-data';materialize(root,p)
    code=mapped_item(s)[1][0]['stock_code']
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    assert ctx.by_code['A.'+code].research_quality_score==68
    assert ctx.by_code['A.'+code].research_delta_hits is None
    assert any(v.research_delta_hits is not None for k,v in ctx.by_code.items() if k!='A.'+code)


def test_hk_and_embedded_strings_do_not_become_a_codes(tmp_path):
    from stage_center.research_context import _canonical_a_code
    for code in ['HK.000001','HK.00700','BAD000001DATA','A.0000012','US.123456']:
        assert _canonical_a_code(code)==''
    assert _canonical_a_code('000001')=='A.000001'
    assert _canonical_a_code('A.000001')=='A.000001'


def test_real_frozen_cli_to_production_stage_builder_keeps_original_formula(tmp_path):
    from stage_center.live_collectors import production_selection_builders
    from stage_center.acquisition import AcquisitionPlan,SourceResult
    from stage_center.candidate_input import CandidateInput
    from stage_center.selection import select_a_live_stage,SelectionStore
    root=tmp_path/'v4-data';p=run_cli(root,source_file());assert p.returncode==0,p.stderr
    code='A.000333';candidate=CandidateInput(root=root,trade_date='20260915',current_relative='fixture',
        current_sha256='a'*64,run_id='EXPLICIT_SYNTHETIC_ONE_ROW',codes=(code,),artifact_sha256='b'*64,
        manifest_sha256='c'*64,receipt_sha256='d'*64,source_projection_sha256='e'*64,source_evidence=())
    plan=AcquisitionPlan(trade_date='20260915',stage_id='STAGE_0930_0935',markets=('A_SHARE',),
        candidate_input=candidate,a_share_route='pytdx_hq_large_universe',hk_route='unused')
    row={'code':code,'name':'SYNTHETIC_QUOTE_NOT_HISTORICAL','trade_date':'20260915',
         'open_price':10.0,'last_price':10.1,'high_price':10.2,'low_price':9.9,'prev_close_price':10.0,
         'turnover':1000000.0,'bid_vol':1.0,'ask_vol':1.0,'update_time':'2026-09-15 09:35:00'}
    source=SourceResult(source_id='EXPLICIT_TRANSPORT_FIXTURE',status='READY',requested_rows=1,rows=(row,))
    raw={'status':'READY','artifact_sha256':'f'*64,'requested_rows':1,'missing_symbols':[],
         'cannot_confirm':[],'source_evidence':[],'cutoff_at':'09:35:05','_v4_research_data_root':root}
    envelope=production_selection_builders('STAGE_0930_0935')['A_SHARE'](source,plan,raw)
    assert envelope['selected_rows']==1
    result=envelope['rows'][0]
    assert result['research_delta_hits'] is not None
    assert result['news_quality_score'] is None and result['research_quality_score'] is None
    assert result['research_bonus'] is None
    assert envelope['selection_status']=='PARTIAL_WITH_ROWS'
    # Actual original selector, same synthetic price inputs and no invented bonus.
    original=select_a_live_stage([{'code':code,'trade_date':'20260915','qmt':{'open':10.,'lastPrice':10.1,
        'lastClose':10.,'high':10.2,'low':9.9,'amount':1000000.,'bidVol':1.,'askVol':1.},
        'candidate':{'score':None}}], '20260915','STAGE_0930_0935','f'*64)
    assert result['stage_score']==original['rows'][0]['stage_score']
    store=SelectionStore(tmp_path/'selection');store.publish(envelope,market='A_SHARE')
    read=store.read_verified('20260915','STAGE_0930_0935','A_SHARE')
    assert read['rows']==envelope['rows']
    assert all(read[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent'))


def test_delta_is_not_a_numeric_bonus_gate_in_actual_bridge(tmp_path):
    from test_stage_research_context_v4 import _live_stage_fixture
    from stage_center.live_collectors import production_selection_builders
    from infrastructure.data_store import NativeDataStore
    root=tmp_path/'v4-data'
    plan, quote, raw=_live_stage_fixture(root)
    # Missing delta only: keep the same valid archive contract, but use the
    # source-witness route where optional facts are independently present.
    from test_stage_research_context_v4 import _source
    source=_source('20260911',slot='0900',with_stage_evidence=True)
    item=source['research_items'][0]
    item.update(trade_date='20260911',source_type='hourly_research',source_name='小时研报',
        title=item['source_title'],event_time='2026-09-11T09:00:00+08:00',
        display_event_time='2026-09-11T09:00:00+08:00',source_published_at='2026-09-11T08:31:00+08:00',
        first_seen_at='2026-09-11T08:32:00+08:00',last_checked_at='2026-09-11T09:00:00+08:00')
    item.pop('is_new_since_last_slot')
    source['stock_research_timeline'][0].pop('is_new_since_last_slot')
    source['stock_research_timeline'][0]['trade_date']='20260911'
    source['source_manifest'].pop('manifest_sha256');source['source_manifest'].pop('receipt_sha256')
    # Separate clean root: never replace the fixture's existing archive.
    fresh=tmp_path/'fresh-v4';src=tmp_path/'SYNTHETIC_ONE_DELTA_GAP.json'
    src.write_text(json.dumps(source,ensure_ascii=False))
    from test_stage_research_context_v4 import _write_morning
    _write_morning(fresh,'20260911')
    run_hourly_research_file(data_root=fresh,source=src,business_date='20260911',target_date='20260911',slot='0900',mode='LIVE')
    raw['_v4_research_data_root']=fresh
    ctx=load_research_context(fresh,trade_date='20260911',stage_cutoff='09:35:05')
    assert ctx.by_code['A.000001'].news_quality_score==12.0
    assert ctx.by_code['A.000001'].research_quality_score==72.5
    assert ctx.by_code['A.000001'].research_delta_hits is None
    result=production_selection_builders('STAGE_0930_0935')['A_SHARE'](quote,plan,raw)
    assert result['rows'][0]['research_bonus']==(12.0+72.5)/40.0
    assert result['rows'][0]['research_delta_hits'] is None
    assert result['selection_status']=='PARTIAL_WITH_ROWS'


@pytest.mark.parametrize('cutoff,slot', [('09:35:05','0900'),('09:40:05','0900'),('09:45:05','0900'),
                                       ('10:30:00','0900'),('13:15:00','0900'),('15:00:00','1400')])
def test_six_research_cutoffs_only_consume_available_same_date_past_slots(tmp_path,cutoff,slot):
    root=tmp_path/'v4-data'
    for s in ('0900','1400'):materialize(root,source_file(s),s)
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff=cutoff)
    assert ctx.selected_slot==slot
    assert all(v.research_quality_score is None and v.news_quality_score is None for v in ctx.by_code.values())


def test_actual_node_and_runner_consume_frozen_source_without_final_ready_mock(tmp_path,monkeypatch,capsys):
    from test_v4_core_stage_recovery import bound_config, stage_transport
    from ops import run_stage_center_nodes as nodes
    from stage_center.selection import SelectionStore
    monkeypatch.setenv('V35_RELEASE_ID','synthetic-stage-gap-regression')
    config=bound_config(tmp_path/'roots')
    root=Path(config['v4_research_data_root'])
    p=run_cli(root,source_file());assert p.returncode==0,p.stderr
    calls=stage_transport(monkeypatch)
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    rc=nodes.main(['--config',str(path),'--node','STAGE_0930_0935','--trade-date','20260915',
                  '--evaluated-at','2026-09-15T09:35:05+08:00','--historical-backfill'])
    output=json.loads(capsys.readouterr().out)
    # Synthetic quotes/pools. The real original projection/store/context/runner
    # publish PARTIAL A and valid HK, not fabricated historical A213 or READY.
    selection=SelectionStore(Path(config['selection_root']))
    a=selection.read_verified('20260915','STAGE_0930_0935','A_SHARE')
    hk=selection.read_verified('20260915','STAGE_0930_0935','HK_CONNECT')
    assert a['selected_rows']>0 and a['selection_status']=='PARTIAL_WITH_ROWS'
    assert hk['selected_rows']==10
    assert not any('RESEARCH_STAGE_EVIDENCE_MISSING' in x for x in a['cannot_confirm'])
    assert any('v4_hourly_source_witness_sha256='+FIXTURE_SHAS['0900']==x for x in a['source_evidence'])
    assert all(a[k] is False and hk[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent'))
    # Save the actual entry/receipt for the bounded evidence pack.
    (tmp_path/'actual_node_output.json').write_text(json.dumps({'exit_code':rc,'result':output},indent=2,ensure_ascii=False))


def test_stage8_input_and_natural_receipts_untouched_by_this_candidate():
    from stage_center.runner import V3_RESEARCH_STAGES
    assert 'STAGE_1545_1555' not in V3_RESEARCH_STAGES
    bundle=Path(os.environ['V4_STAGE_GAP_FIXTURES'])
    original=json.loads((bundle/'SHA_MANIFEST.json').read_text())
    for entry in original['entries']:
        if entry['path'].startswith('stage8/') or entry['path'].startswith('evidence/natural_stage8'):
            assert hashlib.sha256((bundle/entry['path']).read_bytes()).hexdigest()==entry['sha256']
    assert (ROOT/'stage_center/runner.py').read_bytes()==(bundle/'release/stage_center/runner.py').read_bytes()


@pytest.mark.parametrize('cutoff',['9:35', '9:35:05', '935', '09:35', '0935'])
def test_preexisting_cutoff_clock_formats_remain_supported(tmp_path, cutoff):
    root=tmp_path/'v4-data';materialize(root,source_file())
    context=load_research_context(root,trade_date='20260915',stage_cutoff=cutoff)
    assert context.selected_slot=='0900'


def test_ambiguous_item_lineage_is_not_joined_by_title_or_code(tmp_path):
    def mutate(s):
        item,_=mapped_item(s)
        duplicate=copy.deepcopy(item);duplicate['item_id']='SYNTHETIC_DIFFERENT_ITEM_SAME_COPIED_IDENTITY'
        s['research_items'].append(duplicate)
    p=changed_source(tmp_path,mutate);source=json.loads(p.read_bytes())
    _,matches=mapped_item(source);affected={'A.'+row['stock_code'] for row in matches}
    root=tmp_path/'v4-data';materialize(root,p)
    ctx=load_research_context(root,trade_date='20260915',stage_cutoff='09:35:05')
    assert any('LINEAGE_MISSING_OR_AMBIGUOUS' in reason for reason in ctx.cannot_confirm)
    for code in affected:
        assert ctx.by_code[code].research_delta_hits is None
    assert any(v.research_delta_hits is not None for k,v in ctx.by_code.items() if k not in affected)
