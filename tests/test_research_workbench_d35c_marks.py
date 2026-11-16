from copy import deepcopy

import pytest

from infrastructure.research_workbench_d35c_marks import (
    ENGINE_SHA, FLAGS, FORMULA_SHA, IDENTITY_FIELDS, SCHEMA, canonical_sha, chart_original_marks,
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
