from copy import deepcopy
from datetime import date, timedelta
import gzip
import hashlib
import json

import pytest

from infrastructure.research_workbench_d35c_marks import (
    ENGINE_SHA, FLAGS, FORMULA_SHA, IDENTITY_FIELDS, SCHEMA, canonical_sha, chart_original_marks,
    chart_original_marks_from_projection,
)


@pytest.fixture
def sample():
    reference = {'path': '/bound/marks', 'sha256': 'a' * 64}
    chart = {key: reference if key in {'numeric_manifest', 'selector', 'snapshot'} else key for key in IDENTITY_FIELDS}
    chart.update(symbol='603658.SH', rows=[{'trade_date': '20261113', 'close': 38}])
    mark = {'trade_date': '20261113', 'id': 1, 'kind': 'DRAWTEXT', 'payload': '守线', 'styles': ['COLORFFFFFF'], 'y': '37.53728'}
    item = {'status': 'READY', 'marks': [mark], 'unresolved_conditions': 0, 'source_kind': 'DERIVED_BOUND_SELECTOR_PREFIX',
            'source_sha256': 'b' * 64, 'chart_rows_sha256': canonical_sha(chart['rows'])}
    bundle = dict(schema=SCHEMA, formula_sha256=FORMULA_SHA, engine_sha256=ENGINE_SHA,
        items={'603658.SH': item}, **{key: chart[key] for key in IDENTITY_FIELDS}, **FLAGS)
    return chart, bundle, reference


def test_exact_d35c_payload_and_source_window(sample):
    chart, bundle, reference = sample
    result = chart_original_marks(bundle, reference, chart, ['603658.SH'])
    assert result['marks'] == bundle['items']['603658.SH']['marks']
    assert result['formula_sha256'] == FORMULA_SHA
    changed = deepcopy(chart)
    changed['rows'][0]['close'] = 39
    with pytest.raises(ValueError, match='WINDOW_CONFLICT'):
        chart_original_marks(bundle, reference, changed, ['603658.SH'])
    with pytest.raises(ValueError, match='SOURCE_CONFLICT'):
        chart_original_marks(bundle, reference, chart, ['603658.SH', '000860.SZ'])


def test_original_line_sidecar_requires_full_ordered_window_and_preserves_gaps(sample):
    chart, bundle, reference = sample
    dates = [row['trade_date'] for row in chart['rows']]
    item = bundle['items']['603658.SH']
    item['lines'] = {
        '白线': [dict(trade_date=dates[0], y='13.58671489947057447652402281')],
        '黄线': [dict(trade_date=dates[0], y=None)],
    }
    result = chart_original_marks(bundle, reference, chart, ['603658.SH'])
    assert result['lines']['白线'][0]['y'] == '13.58671489947057447652402281'
    assert result['lines']['黄线'][0]['y'] is None

    item['lines']['白线'][0]['trade_date'] = '20261112'
    with pytest.raises(ValueError, match='LINE_DATE_CONFLICT'):
        chart_original_marks(bundle, reference, chart, ['603658.SH'])


def test_stale_and_duplicate_marks_are_never_plotted(sample):
    chart, bundle, reference = sample
    mark = bundle['items']['603658.SH']['marks'][0]
    mark['trade_date'] = '20261112'
    with pytest.raises(ValueError, match='MARK_INVALID'):
        chart_original_marks(bundle, reference, chart, ['603658.SH'])
    mark['trade_date'] = '20261113'
    bundle['items']['603658.SH']['marks'].append(mark)
    with pytest.raises(ValueError, match='DUPLICATE_MARK'):
        chart_original_marks(bundle, reference, chart, ['603658.SH'])


def test_unmaterialized_marker_retains_explicit_gap(sample):
    chart, bundle, reference = sample
    bundle['items']['603658.SH'] = {'status': 'CANNOT_CONFIRM'}
    result = chart_original_marks(bundle, reference, chart, ['603658.SH'])
    assert result['status'] == 'CANNOT_CONFIRM'
    assert 'marks' not in result


def native_projection_fixture():
    source_date = '2026-11-19'
    chart_rows = []
    day = date.fromisoformat(source_date)
    while len(chart_rows) < 120:
        if day.weekday() < 5:
            code = day.strftime('%Y%m%d')
            chart_rows.append(dict(trade_date=code, open=10.0, high=12.0, low=9.0, close=11.0, volume=100.0))
        day -= timedelta(days=1)
    chart_rows.reverse()
    numeric = {'path': '/numeric/manifest.json', 'sha256': '1' * 64}
    selector = {'path': '/numeric/selector.parquet', 'sha256': '2' * 64}
    snapshot = {'path': '/numeric/snapshot.json', 'sha256': '3' * 64}
    chart = dict(schema='V4_WORKBENCH_DAILY_K_V1', source_date=source_date, symbol='000410.SZ',
        generation='4' * 64, input_sha256='5' * 64, numeric_manifest=numeric, selector=selector,
        snapshot=snapshot, formula_group_sha256='6' * 64, price_basis='QFQ_ASOF_20261119',
        volume_basis='QFQ_EVENT_VOLUME', historical_PIT=False, rows=chart_rows,
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    formula_rows = []
    for bar in chart_rows:
        drawings = [dict(id=i, kind='DRAWTEXT', styles=['COLORFFFFFF'], condition=i == 1,
                         y='10.5' if i == 1 else None, payload='守线') for i in range(1, 23)]
        formula_rows.append(dict(trade_date=int(bar['trade_date']),
            ohlcv=dict(trade_date=int(bar['trade_date']), open='10.0', high='12.0', low='9.0',
                       close='11.0', vol='100.0'), drawings=drawings))
    projection = dict(schema='v4.d35c.bound_candidate_projection.v1', symbol=chart['symbol'],
        data_date='20261119', authority='DERIVED_RENDERING_ONLY', historical_PIT=False,
        source=dict(generation_id=chart['generation'], source_input_sha256=chart['input_sha256'],
                    price_basis='QFQ_ASOF', volume_basis='QFQ_EVENT_VOLUME'),
        lineage=dict(formula={'sha256': FORMULA_SHA}, engine={'sha256': ENGINE_SHA}),
        formula_result=dict(formula_sha256=FORMULA_SHA, mode='prefix', field_count=51,
                             drawing_count=22, rows=formula_rows), unsupported_drawings=[],
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    raw = gzip.compress(json.dumps(projection, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    reference = {'path': '/charts/000410.SZ.projection.json.gz', 'sha256': hashlib.sha256(raw).hexdigest()}
    return chart, projection, raw, reference


def test_native_original_projection_reuses_only_exact_120_qfq_window():
    chart, projection, raw, reference = native_projection_fixture()
    result = chart_original_marks_from_projection(raw, reference, chart)
    assert result['status'] == 'READY'
    assert result['source_kind'] == 'REUSED_ORIGINAL_V4_PROJECTION'
    assert result['sidecar'] == reference
    assert result['unresolved_conditions'] == 0
    assert len(result['marks']) == 120
    assert result['marks'][-1] == dict(trade_date='20261119', id=1, kind='DRAWTEXT',
                                       payload='守线', styles=['COLORFFFFFF'], y='10.5')
    assert 'lines' not in result  # A legacy projection never gets close-price approximations.

    changed = deepcopy(chart)
    changed['rows'][-1]['close'] = 11.01
    with pytest.raises(ValueError, match='WINDOW_OHLCV_CONFLICT'):
        chart_original_marks_from_projection(raw, reference, changed)
    with pytest.raises(ValueError, match='PROJECTION_SHA_CONFLICT'):
        chart_original_marks_from_projection(raw + b'x', reference, chart)


def test_native_original_projection_passes_through_only_complete_named_formula_values():
    chart, projection, _, old_reference = native_projection_fixture()
    rows = projection['formula_result']['rows']
    for index, row in enumerate(rows):
        row['values'] = {
            '白线': '13.58671489947057447652402281' if index == 119 else f'{10 + index / 100:.2f}',
            '黄线': None if index == 60 else ('14.00682487468671679197994987' if index == 119 else f'{11 + index / 100:.2f}'),
        }
    raw = gzip.compress(json.dumps(projection, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    reference = {**old_reference, 'sha256': hashlib.sha256(raw).hexdigest()}
    result = chart_original_marks_from_projection(raw, reference, chart)
    assert list(result['lines']) == ['白线', '黄线']
    assert [point['trade_date'] for point in result['lines']['白线']] == [row['trade_date'] for row in chart['rows']]
    assert len(result['lines']['黄线']) == len(chart['rows']) == 120
    assert result['lines']['白线'][-1]['y'] == '13.58671489947057447652402281'
    assert result['lines']['黄线'][-1]['y'] == '14.00682487468671679197994987'
    assert result['lines']['黄线'][60]['y'] is None


def test_native_original_projection_rejects_partial_or_unbounded_line_values():
    chart, projection, _, reference = native_projection_fixture()
    rows = projection['formula_result']['rows']
    for row in rows:
        row['values'] = {'白线': '13.5', '黄线': '14.0'}
    rows[25]['values'].pop('黄线')
    raw = gzip.compress(json.dumps(projection, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    bad_reference = {**reference, 'sha256': hashlib.sha256(raw).hexdigest()}
    with pytest.raises(ValueError, match='LINE_COVERAGE_CONFLICT'):
        chart_original_marks_from_projection(raw, bad_reference, chart)

    rows[25]['values']['黄线'] = '14.0'
    rows[0]['values']['白线'] = '1e-999999999'
    raw = gzip.compress(json.dumps(projection, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    bad_reference = {**reference, 'sha256': hashlib.sha256(raw).hexdigest()}
    with pytest.raises(ValueError, match='LINE_VALUE_INVALID'):
        chart_original_marks_from_projection(raw, bad_reference, chart)


def test_native_original_projection_rejects_date_or_window_drift():
    chart, _, raw, reference = native_projection_fixture()
    changed = deepcopy(chart)
    changed['rows'].pop()
    with pytest.raises(ValueError, match='PROJECTION_IDENTITY_CONFLICT'):
        chart_original_marks_from_projection(raw, reference, changed)
    changed = deepcopy(chart)
    changed['rows'][10]['trade_date'] = '20261118'
    with pytest.raises(ValueError, match='WINDOW_DATE_CONFLICT'):
        chart_original_marks_from_projection(raw, reference, changed)


def test_dynamic_formula_chart_reuses_native_projection_without_formula_group_sidecar():
    from types import SimpleNamespace
    import threading
    from infrastructure.research_workbench_host import ResearchWorkbenchHost

    chart, _, raw, reference = native_projection_fixture()
    source_date = chart['source_date']
    product = dict(data_date='20261119', source_generation=chart['generation'],
        source_identity={'input_sha256': chart['input_sha256']}, manifest=chart['numeric_manifest'],
        artifact={'path': '/numeric/product.json', 'sha256': '7' * 64},
        rows=[dict(symbol=chart['symbol'])], original_charts={'manifest': {'sha256': '8' * 64}})
    formula_ref = {'path': '/formula/roster.json', 'sha256': chart['formula_group_sha256']}
    summary = {'artifact': formula_ref}
    seen = {}

    class Source:
        def read_original_chart(self, day, symbol, **kwargs):
            seen.update(day=day, symbol=symbol, **kwargs)
            return dict(status='READY', symbol=symbol, data_date=day,
                source_generation=product['source_generation'], input_sha256=product['source_identity']['input_sha256'],
                product_manifest=product['manifest'], assets={'projection': reference}, _asset_bytes=raw)

    host = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.source = Source()
    host._view = lambda *args: product
    host._formula_groups = lambda *args: (summary, [dict(symbol=chart['symbol'], source_row={'symbol': chart['symbol']})])
    host._observation_date = lambda _: '2026-11-20'
    host._quote_references = SimpleNamespace(read_daily_chart=lambda _product, _symbol: deepcopy(chart))
    host._formula_group_binding = lambda _: {'artifact': formula_ref}
    host.chart_views = lambda *args: {'projections': {'rows': [dict(symbol=chart['symbol'], sha256=reference['sha256'])]}}
    host._lock = threading.RLock()

    result = host.formula_daily_chart(source_date, chart['symbol'])
    assert result['original_marks']['status'] == 'READY'
    assert result['original_marks']['sidecar']['sha256'] == reference['sha256']
    assert seen == dict(day='20261119', symbol=chart['symbol'], generation=chart['generation'],
        input_sha256=chart['input_sha256'], asset='projection', asset_sha256=reference['sha256'])

    broken = deepcopy(chart)
    broken['rows'][-1]['close'] = 11.01
    host._quote_references = SimpleNamespace(read_daily_chart=lambda _product, _symbol: deepcopy(broken))
    result = host.formula_daily_chart(source_date, chart['symbol'])
    assert result['original_marks'] == dict(status='CANNOT_CONFIRM',
        reason='ORIGINAL_D35C_NATIVE_PROJECTION_INVALID')
