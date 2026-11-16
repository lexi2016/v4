from copy import deepcopy
import hashlib
import json
from pathlib import Path
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
    assert result['formula_groups']['labels'] == {'b23_entry': '192选股', 'pb2_confirm': '回测选股'}
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


def test_two_group_mode_hides_legacy_members_when_approved_date_is_missing(tmp_path, group_fixture):
    product, bundle = group_fixture
    host, _ = bind_fixture(tmp_path, product, bundle)
    binding = host.binding.pop('candidate_group_override')
    host.binding['candidate_group_overrides'] = {'2026-11-13': binding}
    host.binding['candidate_group_formula_sha256'] = bundle['formula_sha256']
    assert host.day('2026-11-13')['scope_count'] == 2

    pending = host.day('2026-11-12')
    assert pending['formula_groups']['labels'] == {'b23_entry': '192选股', 'pb2_confirm': '回测选股'}
    assert pending['formula_groups']['status'] == 'CANNOT_CONFIRM_NOT_MATERIALIZED'
    assert pending['formula_groups']['group_counts'] == {'b23_entry': None, 'pb2_confirm': None}
    assert pending['rows'] == []


def test_historical_skill_day_uses_same_date_identity_with_two_pending_groups(tmp_path, group_fixture):
    product, bundle = group_fixture
    host, _ = bind_fixture(tmp_path, product, bundle)
    revision = product['source_generation']
    receipt = {'path': '/test/d28-receipt.json', 'sha256': '1' * 64}
    host.binding = {'candidate_group_overrides': {}, 'candidate_group_formula_sha256': bundle['formula_sha256']}
    host._index = lambda: {'dates': {}}
    host._observation_date = lambda _: '2026-10-29'

    def versions(observation, requested_revision):
        assert observation == '2026-10-29'
        if requested_revision != revision:
            raise ValueError('SKILL_R2_REVISION_CONFLICT')
        return {'source_date': '2026-10-28', 'observation_date': observation, 'generation': revision,
                'input_sha256': product['source_identity']['input_sha256'], 'numeric_manifest': receipt}

    host.skill_r2 = SimpleNamespace(versions=versions)
    pending = host.day('2026-10-28', revision)
    assert (pending['source_date'], pending['observation_date']) == ('2026-10-28', '2026-10-29')
    assert pending['numeric_manifest'] == receipt and pending['revision'] == revision
    assert pending['scope_count'] == 0 and pending['rows'] == []
    assert pending['formula_groups'] == {
        'labels': {'b23_entry': '192选股', 'pb2_confirm': '回测选股'},
        'group_counts': {'b23_entry': None, 'pb2_confirm': None},
        'formula_sha256': bundle['formula_sha256'], 'artifact': None, 'status': 'CANNOT_CONFIRM_NOT_MATERIALIZED',
    }
    with pytest.raises(ValueError, match='SKILL_R2_REVISION_CONFLICT'):
        host.day('2026-10-28', 'wrong-revision')


def test_two_group_mode_reads_exact_date_owner_commit_and_pins_formulas(tmp_path, group_fixture):
    product, bundle = group_fixture
    host, _ = bind_fixture(tmp_path, product, bundle)
    host.binding = {'candidate_group_overrides': {}, 'candidate_group_formula_sha256': dict(bundle['formula_sha256']),
                    'formula_groups_root': str(tmp_path)}
    host._module_reference = ResearchWorkbenchHost._module_reference.__get__(host)
    day = tmp_path / '2026-11-13'
    day.mkdir()

    def put(path, value):
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}

    artifact = put(day / 'artifact.json', bundle)
    receipt = put(day / 'receipt.json', {'status': 'COMMITTED', 'artifact': artifact})
    pointer = {**FLAGS, 'schema': 'V4_WORKBENCH_MODULE_COMMIT_V1', 'module': 'formula_groups',
               'date': day.name, 'artifact': artifact, 'receipt': receipt}
    put(day / 'latest.json', pointer)
    assert host.day(day.name)['scope_count'] == 2

    bundle['formula_sha256']['b23_entry'] = '3' * 64
    pointer['artifact'] = put(day / 'artifact.json', bundle)
    pointer['receipt'] = put(day / 'receipt.json', {'status': 'COMMITTED', 'artifact': pointer['artifact']})
    put(day / 'latest.json', pointer)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_CONTRACT_INVALID'):
        host.day(day.name)

    pointer['artifact'] = put(tmp_path / 'outside.json', bundle)
    put(day / 'latest.json', pointer)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_REFERENCE_OUTSIDE_OWNER'):
        host.day(day.name)


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


def test_selected_member_can_have_unknown_in_the_other_formula(tmp_path, group_fixture):
    product, bundle = group_fixture
    bundle['rows'][1]['group_states'] = {'b23_entry': 'TRUE', 'pb2_confirm': 'UNKNOWN'}
    host, _ = bind_fixture(tmp_path, product, bundle)
    assert host.day('2026-11-13')['rows'][1]['group_states']['pb2_confirm'] == 'UNKNOWN'

    bundle['rows'][1]['group_states']['pb2_confirm'] = 'TRUE'
    host, _ = bind_fixture(tmp_path, product, bundle)
    with pytest.raises(ValueError, match='WORKBENCH_FORMULA_GROUP_STATE_CONFLICT'):
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


def test_f10_only_receipt_advances_formula_event_and_ignores_unbound_receipts(tmp_path, group_fixture):
    from infrastructure.research_workbench_host import checked

    product, bundle = group_fixture
    host, _ = bind_fixture(tmp_path, product, bundle)
    host.classifications.version = lambda: 'classification'
    host._observation_commit = lambda day: None
    host._v192_version = lambda day: None
    index = {'f10': {}}
    host._index = lambda: index
    host.source = SimpleNamespace(_a_product_reference=checked)
    source_date = '2026-11-13'
    day = product['data_date']
    receipt = dict(schema='v4.a_share.f10_daily_receipt.v1', status='PARTIAL', data_date=day,
                   source_generation=product['source_generation'], input_sha256=product['source_identity']['input_sha256'],
                   selector_sha256=product['source_identity']['selector_artifact_sha256'], historical_PIT=False, **FLAGS)

    def publish(name, **changes):
        path = tmp_path / name
        raw = json.dumps({**receipt, **changes}).encode()
        path.write_bytes(raw)
        reference = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        index['f10'][day] = reference
        return reference

    absent = host.versions(source_date)
    publish('f10-first.json', observed=50)
    first = host.versions(source_date)
    publish('f10-second.json', observed=51)
    fresh = host.versions(source_date)
    assert first['event_id'] != absent['event_id'] != fresh['event_id']
    assert fresh['event_id'] != first['event_id']
    assert first['modules']['f10'] != fresh['modules']['f10']
    assert {key: value for key, value in fresh['modules'].items() if key != 'f10'} == absent['modules']
    assert 'f10' not in host.versions('2026-11-12')['modules']

    for key, value in [('source_generation', 'd' * 64), ('input_sha256', 'd' * 64),
                       ('data_date', '20261112'), ('selector_sha256', 'd' * 64),
                       ('historical_PIT', True), ('production_allowed', True)]:
        bad = publish(f'f10-bad-{key}.json', **{key: value})
        assert host.versions(source_date) == absent
        with pytest.raises(ValueError, match='F10_RECEIPT'):
            host._f10_receipt(product, bad, formula=True)
    drift = publish('f10-drift.json')
    Path(drift['path']).write_text('{}')
    assert host.versions(source_date) == absent
