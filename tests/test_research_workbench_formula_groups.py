from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from threading import RLock

import pytest

from infrastructure.research_workbench_host import FLAGS, ResearchWorkbenchHost


@pytest.fixture
def group_fixture():
    product = {
        'data_date': '20261113', 'source_generation': 'a' * 64,
        'source_identity': {'input_sha256': 'b' * 64, 'selector_artifact_sha256': 'c' * 64},
        'manifest': {'path': '/test/numeric.json', 'sha256': 'd' * 64},
        'artifact': {'path': '/test/product.json', 'sha256': 'e' * 64},
        'processed_count': 3,
        'formula_group_admitted_symbols': {'600001.SH', '000001.SZ', '600002.SH'},
        'rows': [{'symbol': '600002.SH', 'groups': 'original', 'display_name': '历史候选'}],
    }
    bundle = {
        **FLAGS, 'schema': 'V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1',
        'source_date': '2026-11-13', 'observation_date': '2026-11-16',
        'generation': product['source_generation'], 'input_sha256': product['source_identity']['input_sha256'],
        'selector_sha256': product['source_identity']['selector_artifact_sha256'],
        'numeric_manifest': product['manifest'], 'formula_sha256': {'pb2_confirm': 'f' * 64, 'b23_entry': '0' * 64},
        'group_counts': {'pb2_confirm': 1, 'b23_entry': 2},
        'rows': [
            {'symbol': '600001.SH', 'display_name': '候选甲', 'groups': ['pb2_confirm', 'b23_entry']},
            {'symbol': '000001.SZ', 'display_name': '候选乙', 'groups': ['b23_entry']},
        ],
    }
    return product, bundle


def bind_fixture(tmp_path, product, bundle, *, binding_date='2026-11-13'):
    path = tmp_path / 'groups.json'
    raw = json.dumps(bundle).encode()
    path.write_bytes(raw)
    ref = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
    host = object.__new__(ResearchWorkbenchHost)
    host.binding = {'candidate_group_override': {'source_date': binding_date, 'artifact': ref}}
    host.skill_r2 = None
    host._view = lambda source_date, revision: product
    host._observation_date = lambda source_date: '2026-11-16'
    host._module_reference = lambda name, source_date: None
    host.workflow = lambda source_date: {'time_contract': {'nodes': []}}
    host.classifications = SimpleNamespace(root=None)
    host._quote_references = SimpleNamespace(read=lambda view: {'test_symbols': [r['symbol'] for r in view['rows']]})
    host._lock = RLock()
    host._row_cache = {}
    return host, path


def test_day_replaces_groups_and_quote_scope_only_for_bound_date(tmp_path, group_fixture):
    product, bundle = group_fixture
    original = deepcopy(product)
    host, _ = bind_fixture(tmp_path, product, bundle)
    result = host.day('2026-11-13')
    assert result['formula_groups']['group_counts'] == {'pb2_confirm': 1, 'b23_entry': 2}
    assert list(result['formula_groups']['labels']) == ['pb2_confirm', 'b23_entry']
    assert result['scope_count'] == 2
    assert result['rows'][0]['group_states'] == {'pb2_confirm': 'TRUE', 'b23_entry': 'TRUE'}
    assert result['rows'][1]['group_states'] == {'pb2_confirm': 'FALSE', 'b23_entry': 'TRUE'}
    assert result['statistics_status'] == 'NOT_MATERIALIZED_FOR_SELECTED_FORMULAS'
    assert result['source_close_reference']['test_symbols'] == ['600001.SH', '000001.SZ']
    assert product == original

    other_date = host.day('2026-11-12')
    assert 'formula_groups' not in other_date
    assert other_date['rows'][0]['symbol'] == '600002.SH'
    assert other_date['rows'][0]['group_states']['original'] == 'TRUE'
    host.binding.pop('candidate_group_override')
    assert host.day('2026-11-13')['rows'] == other_date['rows']


@pytest.mark.parametrize(('key', 'value'), [
    ('source_date', '2026-11-12'),
    ('observation_date', '2026-11-17'),
    ('generation', '1' * 64),
    ('input_sha256', '2' * 64),
    ('selector_sha256', '3' * 64),
    ('numeric_manifest', {}),
])
def test_stale_or_different_bundle_fails_closed(tmp_path, group_fixture, key, value):
    product, bundle = group_fixture
    bundle[key] = value
    host, _ = bind_fixture(tmp_path, product, bundle)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_SOURCE_CONFLICT'):
        host.day('2026-11-13')


def test_changed_bytes_or_extra_group_cannot_appear(tmp_path, group_fixture):
    product, bundle = group_fixture
    host, path = bind_fixture(tmp_path, product, bundle)
    path.write_text('{}')
    with pytest.raises(ValueError, match='WORKBENCH_SOURCE_SHA_DRIFT'):
        host.day('2026-11-13')

    bundle['rows'][0]['groups'].append('original')
    host, _ = bind_fixture(tmp_path, product, bundle)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_ROW_INVALID'):
        host.day('2026-11-13')


def test_unadmitted_symbol_cannot_appear(tmp_path, group_fixture):
    product, bundle = group_fixture
    bundle['rows'][0]['symbol'] = '600999.SH'
    host, _ = bind_fixture(tmp_path, product, bundle)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_ROW_INVALID'):
        host.day('2026-11-13')


def test_two_group_labels_allow_verified_empty_membership(tmp_path, group_fixture):
    product, bundle = group_fixture
    bundle['rows'] = []
    bundle['group_counts'] = {'pb2_confirm': 0, 'b23_entry': 0}
    host, _ = bind_fixture(tmp_path, product, bundle)
    result = host.day('2026-11-13')
    assert result['scope_count'] == 0
    assert result['formula_groups']['group_counts'] == bundle['group_counts']


def test_formula_chart_rejects_a_stock_outside_the_bound_group():
    from infrastructure.research_workbench_quote_reference import SourceCloseReferences

    with pytest.raises(KeyError, match='WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND'):
        SourceCloseReferences().read_daily_chart({'rows': [{'symbol': '600001.SH'}]}, '600002.SH')


def test_daily_chart_rows_keep_actual_sessions_and_require_source_day():
    from infrastructure.research_workbench_quote_reference import _daily_chart_rows

    values = [dict(ts_code='600001.SH', trade_date=date, open=11, low=10, high=13, close=12, volume=100)
              for date in ('20261113', '20261111')]
    values.append(dict(values[1], ts_code='600002.SH'))
    projected = _daily_chart_rows(values, ['600001.SH', '600002.SH'], '20260801', '20261113')
    assert list(projected) == ['600001.SH']
    assert [row['trade_date'] for row in projected['600001.SH']] == ['20261111', '20261113']
    assert projected['600001.SH'][-1]['close'] == 12

    with pytest.raises(ValueError, match='WORKBENCH_DAILY_K_ROW_IDENTITY_CONFLICT'):
        _daily_chart_rows(values[:1] * 2, ['600001.SH'], '20260801', '20261113')
    with pytest.raises(ValueError, match='WORKBENCH_DAILY_K_BAR_INVALID'):
        _daily_chart_rows([dict(values[0], high=11)], ['600001.SH'], '20260801', '20261113')


def test_formula_f10_projects_only_verified_source_labels():
    from infrastructure.research_workbench_host import _formula_f10_source_detail

    text = ('｜★主营业务:专用仪器研发、生产与服务。 ｜\n'
            '｜★股东户数变化:截止2026-09-30,公司股东数1234,比上期增加12户。 ｜\n'
            '｜概念描述:其他产品。 ｜')
    stock = {'category': {'name': '最新提示'}, 'source_text': text,
             'source_text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'financials': {'holder_count': 1234.0}}
    expected = {'main_business': '专用仪器研发、生产与服务。', 'shareholder_record_date': '2026-09-30'}
    assert _formula_f10_source_detail(stock, '20261113') == expected
    assert _formula_f10_source_detail({**stock, 'source_text_sha256': 'a' * 64}, '20261113') == dict.fromkeys(expected)
    assert _formula_f10_source_detail({**stock, 'financials': {'holder_count': 555}}, '20261113')['shareholder_record_date'] is None
    assert _formula_f10_source_detail(stock, '20260929')['shareholder_record_date'] is None
    ambiguous = text + '\n｜★主营业务:其他。｜'
    assert _formula_f10_source_detail({**stock, 'source_text': ambiguous,
        'source_text_sha256': hashlib.sha256(ambiguous.encode()).hexdigest()}, '20261113')['main_business'] is None
