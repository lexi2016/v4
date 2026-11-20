import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops._formula_groups_daily_parts import workbench_supplements as supplements


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SYMBOLS = [f'{number:06d}.SZ' for number in range(100, 122)]
OBSERVED = set(SYMBOLS[:20])
FAILED = set(SYMBOLS[20:])
GENERATION = 'a' * 64
INPUT = 'b' * 64
SELECTOR = 'c' * 64
NUMERIC = dict(path='/products/20261120.json', sha256='d' * 64)


def _context(tmp_path):
    return SimpleNamespace(target=20261120, generation=GENERATION, root=tmp_path,
        identity=dict(input_sha256=INPUT, selector_artifact_sha256=SELECTOR,
            basis=dict(volume_basis='QFQ_EVENT_VOLUME')),
        unchanged=lambda:None)


def _write_ref(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())


def _coverage_binding(tmp_path, observed, failed, *, include_unreadable_non_roster=False):
    scope_sha = '9' * 64
    upstream = dict(path='/products/upstream.json',sha256='0' * 64)
    items = {}
    for index, symbol in enumerate(sorted(observed)):
        row = dict(symbol=symbol,status='OBSERVED',**FLAGS)
        items[symbol] = _write_ref(tmp_path/f'items/{index}.json',row)
    if include_unreadable_non_roster:
        items['999999.BJ'] = dict(path=str(tmp_path/'missing-outside-roster.json'),sha256='1'*64)
    checkpoint = dict(schema='v4.a_share.f10_checkpoint.v1',
        identity=dict(data_date='20261120',source_generation=GENERATION,input_sha256=INPUT,
            selector_sha256=SELECTOR,scope_sha256=scope_sha),
        items=items,upstream_success_receipt=upstream,**FLAGS)
    checkpoint_ref = _write_ref(tmp_path/'checkpoint.json',checkpoint)
    receipt = dict(schema='v4.a_share.f10_daily_receipt.v1',status='PARTIAL',
        data_date='20261120',source_generation=GENERATION,input_sha256=INPUT,
        selector_sha256=SELECTOR,numeric_manifest=NUMERIC,scope_sha256=scope_sha,
        scope=dict(kind='ADMITTED_DAILY_UNIVERSE',count=100,symbols=None),
        priority_scope=dict(symbols=sorted(SYMBOLS),count=len(SYMBOLS)),
        checkpoint=checkpoint_ref,upstream_success_receipt=upstream,
        requested=100,observed=len(observed)+(1 if include_unreadable_non_roster else 0),
        failures={symbol:{'status':'FAILED'} for symbol in failed},
        remaining=['888888.SZ'],**FLAGS)
    return dict(status='PARTIAL',receipt=_write_ref(tmp_path/'receipt.json',receipt))


def _owner_fixture(tmp_path, monkeypatch, *, retry_succeeds):
    context = _context(tmp_path)
    formula_ref = dict(path='/formula.json', sha256='e' * 64)
    formula = dict(observation_date='2026-11-23')
    score_replay = dict(statuses={symbol:dict(record_status='MATERIALIZED') for symbol in SYMBOLS})
    values = {formula_ref['path']:formula, '/score-replay.json':score_replay}
    product = dict(rows=[dict(symbol=symbol) for symbol in SYMBOLS])
    old_score_binding=dict(status='READY',receipt=dict(path='/old-score-replay.json',sha256='9'*64),
        artifact_root=str(tmp_path/'score-action'))
    previous = dict(pointer=dict(status='COMPLETE'), artifact_ref=dict(path='/old-artifact.json',sha256='f'*64),
        receipt_ref=dict(path='/old-receipt.json',sha256='0'*64),
        artifact=dict(status='COMPLETE',f10=dict(status='PARTIAL',receipt=dict(path='/old-f10.json',sha256='1'*64)),
            score_action=old_score_binding))
    monkeypatch.setattr(supplements, '_numeric_product', lambda _: (NUMERIC, {}, product, {}))
    monkeypatch.setattr(supplements, '_checked', lambda ref: values[ref['path']])
    monkeypatch.setattr(supplements, '_group_identity', lambda *args: ('2026-11-20',SYMBOLS,'2'*64))
    monkeypatch.setattr(supplements, '_current_supplement', lambda *_: (tmp_path/'latest.json','old-pointer-sha',previous))
    monkeypatch.setattr(supplements, '_d35c_roster_complete', lambda *_: False)
    monkeypatch.setattr(supplements, '_build_d35c_bundle', lambda *args, **kwargs: dict(items={
        symbol:dict(status='READY',unresolved_conditions=0) for symbol in SYMBOLS}))
    score_bindings=[]
    def build_score_replay(*args,**kwargs):
        score_bindings.append(kwargs.get('previous_binding'))
        return dict(status='READY'),score_replay
    monkeypatch.setattr(supplements, '_build_score_replay', build_score_replay)
    monkeypatch.setattr(supplements, '_immutable', lambda root, value: (
        dict(path='/score-replay.json',sha256='3'*64) if 'score_action' in str(root)
        else dict(path='/immutable.json',sha256='4'*64)))
    pointer_values=[]
    monkeypatch.setattr(supplements, '_atomic_pointer', lambda path, value, expected:
        pointer_values.append(value) or dict(path=str(path),sha256='5'*64))
    coverage_calls=[]
    def coverage(*args):
        coverage_calls.append(args[-1])
        incomplete = (OBSERVED, FAILED, set())
        complete = (set(SYMBOLS), set(), set())
        if len(coverage_calls) < 3 or not retry_succeeds:
            return incomplete
        return complete
    monkeypatch.setattr(supplements, '_f10_roster_coverage', coverage)

    from ops import research_panel_f10
    fetch_calls=[]
    monkeypatch.setattr(research_panel_f10, 'exact_daily_source_receipt', lambda *args: dict(path='/source.json',sha256='6'*64))
    monkeypatch.setattr(research_panel_f10, 'complete_f10', lambda *args, **kwargs:
        fetch_calls.append(kwargs) or dict(status='PARTIAL',receipt=dict(path='/new-f10.json',sha256='7'*64),
            requested=len(SYMBOLS),observed=20,failure_count=2,remaining_count=0))
    monkeypatch.setattr(research_panel_f10, 'publish_f10_completion', lambda *args: dict(status='PUBLISHED'))
    result = supplements.complete(context, tmp_path/'formula-groups', formula_ref,
        dict(path='/formula-receipt.json',sha256='8'*64))
    return result, fetch_calls, coverage_calls, pointer_values, score_bindings, old_score_binding


@pytest.mark.parametrize('retry_succeeds,expected', [(True,'COMPLETE'),(False,'PARTIAL')])
def test_false_complete_reenters_same_f10_owner_and_corrects_status(tmp_path, monkeypatch,
        retry_succeeds, expected):
    result, fetch_calls, coverage_calls, pointers, score_bindings, old_score_binding = _owner_fixture(
        tmp_path, monkeypatch, retry_succeeds=retry_succeeds)

    assert result['status'] == expected
    assert len(fetch_calls) == 1
    assert fetch_calls[0]['priority_symbols'] == SYMBOLS
    assert fetch_calls[0]['priority_only'] is True
    assert len(coverage_calls) == 3
    assert pointers[-1]['status'] == expected
    assert score_bindings == [old_score_binding]


def test_f10_complete_signal_requires_all_observed_not_attempted():
    assert not supplements._f10_roster_complete(SYMBOLS,
        set(SYMBOLS[:20]), FAILED, set())
    assert supplements._f10_roster_complete(SYMBOLS, set(SYMBOLS), set(), set())


def test_actual_f10_receipt_partition_counts_only_exact_roster_and_skips_other_shards(tmp_path):
    context = _context(tmp_path)
    binding = _coverage_binding(tmp_path,OBSERVED,FAILED,include_unreadable_non_roster=True)

    observed, failed, remaining = supplements._f10_roster_coverage(context,NUMERIC,SYMBOLS,binding)

    assert observed == OBSERVED
    assert failed == FAILED
    assert remaining == set()
    assert not supplements._f10_roster_complete(SYMBOLS,observed,failed,remaining)


def test_previous_partial_chart_is_reused_and_legacy_ready_is_downgraded_without_recompute(
        tmp_path, monkeypatch):
    symbol = SYMBOLS[0]
    item = dict(status='READY',source_kind='DERIVED_BOUND_SELECTOR_PREFIX',
        source_sha256='a'*64,unresolved_conditions=1,chart_rows_sha256='b'*64,
        marks=[dict(trade_date='20261120',id=1,kind='DRAWTEXT',payload='信号',styles=['COLORRED'],y='1')],
        lines={'白线':[dict(trade_date='20261120',y='1')],
               '黄线':[dict(trade_date='20261120',y='2')]})
    previous = dict(items={symbol:item})
    context = SimpleNamespace(target=20261120, generation=GENERATION,
        identity=dict(input_sha256=INPUT,selector_artifact_sha256=SELECTOR,
            basis=dict(volume_basis='QFQ_EVENT_VOLUME')),
        snapshot_ref=dict(path='/snapshot',sha256='c'*64),panel=Path('/selector'),
        unchanged=lambda:None)
    monkeypatch.setattr(supplements,'_d35c_item',lambda *args:pytest.fail('same-source partial marks must be reused'))

    bundle = supplements._build_d35c_bundle(context,{},NUMERIC,
        dict(path='/formula.json',sha256='d'*64),{},'2026-11-20',[symbol],'e'*64,
        previous_bundle=previous)

    projected = bundle['items'][symbol]
    assert projected['status'] == 'PARTIAL_WITH_UNKNOWN'
    assert projected['marks'] == item['marks']
    assert projected['lines'] == item['lines']


def test_malformed_previous_chart_projection_is_recomputed(tmp_path, monkeypatch):
    symbol = SYMBOLS[0]
    malformed = dict(status='PARTIAL_WITH_UNKNOWN',source_kind='DERIVED_BOUND_SELECTOR_PREFIX',
        source_sha256='a'*64,unresolved_conditions=1,chart_rows_sha256='b'*64,
        marks=[],lines={'白线':[dict(trade_date='20261120',y='1')]})
    previous = dict(items={symbol:malformed})
    context = SimpleNamespace(target=20261120, generation=GENERATION,
        identity=dict(input_sha256=INPUT,selector_artifact_sha256=SELECTOR,
            basis=dict(volume_basis='QFQ_EVENT_VOLUME')),
        snapshot_ref=dict(path='/snapshot',sha256='c'*64),panel=Path('/selector'),
        unchanged=lambda:None,read=lambda _: ([],{}),qualify=lambda _: {'status':'ACCEPTED'})
    monkeypatch.setattr(supplements,'_chart_rows',lambda *args: [dict(trade_date='20261120')])
    recomputed = dict(status='PARTIAL_WITH_UNKNOWN',source_kind='DERIVED_BOUND_SELECTOR_PREFIX',
        source_sha256='a'*64,unresolved_conditions=1,chart_rows_sha256='b'*64,
        marks=[],lines={'白线':[dict(trade_date='20261120',y='1')],
                       '黄线':[dict(trade_date='20261120',y='2')]})
    calls=[]
    monkeypatch.setattr(supplements,'_checked',lambda _: previous)
    monkeypatch.setattr(supplements,'_d35c_item',lambda *args:calls.append(args) or recomputed)

    assert not supplements._d35c_roster_complete(
        dict(path='/previous-marks.json',sha256='c'*64),[symbol])

    bundle = supplements._build_d35c_bundle(context,{},NUMERIC,
        dict(path='/formula.json',sha256='d'*64),{},'2026-11-20',[symbol],'e'*64,
        previous_bundle=previous)

    assert len(calls)==1
    assert bundle['items'][symbol] == recomputed
