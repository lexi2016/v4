from copy import deepcopy
import json
from pathlib import Path

import pytest

from infrastructure.research_workbench_formula_group_supplement import (
    prior_company_snapshot,
    prior_company_snapshot_from_answer,
    prior_f10_snapshot,
)


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SYMBOL = '000610.SZ'
SOURCE_DATE = '2026-11-20'
OBSERVATION_DATE = '2026-11-23'
ROSTER_SHA = 'a' * 64
CURRENT_MANIFEST = dict(path='/products/20261120.json', sha256='b' * 64)
MATERIAL_REF = dict(path='/products/company/000610.SZ.json', sha256='c' * 64)
MATERIALS_MANIFEST = dict(path='/products/company-index/20261119.json', sha256='d' * 64)


def fixture_answer(*, material_date='20261119', view_mode='HISTORICAL_ASOF', symbol=SYMBOL):
    current = dict(data_date='20261120', source_generation='e' * 64,
        input_sha256='f' * 64, numeric_manifest=CURRENT_MANIFEST)
    material = dict(schema_version='v4.a_share.company_materials.v1', symbol=symbol,
        data_date=material_date, source_generation='1' * 64, input_sha256='2' * 64,
        numeric_manifest=dict(path='/products/20261119.json', sha256='3' * 64),
        business_reported={'value':'公司主营快照'}, financials_reported={'latest_report_period':'2026-09-30'},
        shareholders_reported={'holder_count':12345}, report_catalog=[{'title':'2025年报'}],
        formula_group_scope={'source_date':'20261119'},
        secondary_screen={'received_record':{'market_view':'旧日研究'}},
        received_source_record={'observation':'不应复制'}, **FLAGS)
    lifecycle = dict(material_source_date=material_date,
        received_at='2026-11-19T23:45:51.227370+08:00', view_mode=view_mode,
        historical_PIT_safe=False, asof_cutoff='2026-11-20T23:59:59.999999+08:00',
        received_time_status='RECORDED_LOCAL_RECEIPT', disclosure_time_status='UNKNOWN_DATE_ONLY_PRESENT',
        freshness_status='HISTORICAL_NOT_REVIEWED_FOR_CURRENT_CANDIDATES',
        current_candidate_identity=current,
        material_identity=dict(data_date=material_date, source_generation='1' * 64,
            input_sha256='2' * 64, numeric_manifest=material['numeric_manifest']))
    return dict(status='PARTIAL_RECEIVED', symbol=symbol, data_date='20261120',
        source_generation='e' * 64, input_sha256='f' * 64, numeric_manifest=CURRENT_MANIFEST,
        materials_manifest=MATERIALS_MANIFEST, material_ref=MATERIAL_REF,
        materials=material, material_lifecycle=lifecycle,
        research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


class Source:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def read_a_daily_company_materials(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return deepcopy(self.answer)


class ProductSource:
    def __init__(self, root):
        self.root = root

    def _a_product_root(self):
        return self.root

    @staticmethod
    def _a_product_reference(reference):
        return json.loads(Path(reference['path']).read_bytes())


def product():
    return dict(data_date='20261120', source_generation='e' * 64,
        source_identity=dict(input_sha256='f' * 64, selector_artifact_sha256='9' * 64),
        manifest=CURRENT_MANIFEST)


def write_ref(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
    return dict(path=str(path.resolve()), sha256=__import__('hashlib').sha256(path.read_bytes()).hexdigest())


def prior_f10_fixture(tmp_path, *, prior_day='20261119'):
    old_input, old_generation = '6' * 64, '7' * 64
    old_product_identity = dict(input_sha256=old_input, selector_artifact_sha256='8' * 64)
    old_product_ref = write_ref(tmp_path / 'old-product.json', dict(schema_version='v4.a_share.daily_product.v1',
        status='PARTIAL_WITH_ROWS', sample_only=False, data_date=prior_day,
        source_generation=old_generation, source_identity=old_product_identity, **FLAGS))
    old_manifest_ref = write_ref(tmp_path / 'old-manifest.json', dict(schema_version='v4.a_share.daily_product_manifest.v1',
        status='PARTIAL_WITH_ROWS', data_date=prior_day, source_generation=old_generation,
        input_sha256=old_input, artifact=old_product_ref, sample_only=False, **FLAGS))
    captured = dict(symbol=SYMBOL, status='OBSERVED', captured_at='2026-11-19T22:00:00+08:00',
        source_updated_date='2026-11-19', finance_updated_date='2026-11-19',
        financials={'holder_count':10000}, source_text_sha256='9' * 64,
        historical_PIT=False, **FLAGS)
    stock_ref = write_ref(tmp_path / 'stock.json', captured)
    checkpoint_identity = dict(data_date=prior_day, source_generation=old_generation,
        input_sha256=old_input, selector_sha256=old_product_identity['selector_artifact_sha256'],
        scope_sha256='a' * 64)
    checkpoint_ref = write_ref(tmp_path / 'checkpoint.json', dict(schema='v4.a_share.f10_checkpoint.v1',
        identity=checkpoint_identity, items={SYMBOL:stock_ref}, **FLAGS))
    receipt_ref = write_ref(tmp_path / 'receipt.json', dict(schema='v4.a_share.f10_daily_receipt.v1',
        status='PARTIAL', data_date=prior_day, source_generation=old_generation,
        input_sha256=old_input, selector_sha256=old_product_identity['selector_artifact_sha256'],
        scope_sha256='a' * 64, numeric_manifest=old_manifest_ref,
        checkpoint=checkpoint_ref, requested=1, observed=1, historical_PIT=False, **FLAGS))
    write_ref(tmp_path / 'index.json', dict(f10={prior_day:receipt_ref}))
    current = dict(data_date='20261120', source_generation='e' * 64,
        source_identity=dict(input_sha256='f' * 64, selector_artifact_sha256='5' * 64),
        manifest=CURRENT_MANIFEST)
    return ProductSource(tmp_path), current


def bind_legacy_f10_derivatives_receipt(source, day='20261119'):
    index_path = Path(source.root) / 'index.json'
    index = json.loads(index_path.read_bytes())
    prior_ref = index['f10'][day]
    receipt = json.loads(Path(prior_ref['path']).read_bytes())
    numeric_ref = receipt.pop('numeric_manifest')
    upstream = write_ref(Path(source.root) / f'{day}-derivatives.json', dict(
        schema='V4_A_DAILY_DERIVATIVES_V1', status='COMPLETE_DESCRIPTIVE_NONPIT',
        data_date=day, source_generation=receipt['source_generation'],
        completed_source_provenance=dict(status='EXACT_COMPLETED_SOURCE', numeric_manifest=numeric_ref),
        **FLAGS))
    receipt['upstream_success_receipt'] = upstream
    receipt_ref = write_ref(Path(source.root) / f'{day}-legacy-f10-receipt.json', receipt)
    index['f10'][day] = receipt_ref
    write_ref(index_path, index)


def add_unbound_f10_receipt(source, day='20261119'):
    index_path = Path(source.root) / 'index.json'
    index = json.loads(index_path.read_bytes())
    index['f10'][day] = write_ref(Path(source.root) / f'{day}-unbound-f10-receipt.json', dict(
        schema='v4.a_share.f10_daily_receipt.v1', status='PARTIAL', data_date=day,
        source_generation='5' * 64, input_sha256='6' * 64, selector_sha256='7' * 64,
        scope_sha256='8' * 64, checkpoint={'path':str(Path(source.root) / 'missing-checkpoint.json'),
            'sha256':'9' * 64}, observed=0, historical_PIT=False, **FLAGS))
    write_ref(index_path, index)


def test_prior_company_projection_keeps_actual_dates_and_only_company_snapshot_fields():
    source = Source(fixture_answer())

    result = prior_company_snapshot(source, product(), SOURCE_DATE, OBSERVATION_DATE, SYMBOL, ROSTER_SHA)

    assert result['status'] == 'PRIOR_AVAILABLE'
    assert result['symbol'] == SYMBOL
    assert result['selected_source_date'] == SOURCE_DATE
    assert result['source_date'] == '20261119'
    assert result['received_at'] == '2026-11-19T23:45:51.227370+08:00'
    assert result['material_ref'] == MATERIAL_REF
    assert result['business_reported']['value'] == '公司主营快照'
    assert result['financials_reported']['latest_report_period'] == '2026-09-30'
    assert result['shareholders_reported']['holder_count'] == 12345
    assert 'secondary_screen' not in result
    assert 'formula_group_scope' not in result
    assert 'received_source_record' not in result
    args, kwargs = source.calls[0]
    assert args[0] == '20261120' and args[1] == SYMBOL
    assert kwargs['allow_processed_symbol'] is True
    assert kwargs['formula_roster_sha256'] == ROSTER_SHA
    assert kwargs['formula_observation_date'] == '20261123'


@pytest.mark.parametrize('material_date,view_mode', [
    ('20261121', 'HISTORICAL_ASOF'),
    ('20261120', 'CURRENT_RESEARCH'),
])
def test_prior_company_projection_rejects_future_or_nonhistorical_material(material_date, view_mode):
    source = Source(fixture_answer(material_date=material_date, view_mode=view_mode))

    with pytest.raises(ValueError, match='WORKBENCH_PRIOR_COMPANY_SOURCE_CONFLICT'):
        prior_company_snapshot(source, product(), SOURCE_DATE, OBSERVATION_DATE, SYMBOL, ROSTER_SHA)


def test_current_reader_can_return_a_verified_prior_origin_without_relabeling_it_current():
    source = Source(fixture_answer(view_mode='CURRENT_RESEARCH'))

    result = prior_company_snapshot(source, product(), SOURCE_DATE, OBSERVATION_DATE, SYMBOL, ROSTER_SHA)

    assert result['source_date'] == '20261119'
    assert result['material_lifecycle']['reader_view_mode'] == 'CURRENT_RESEARCH'
    assert result['material_lifecycle']['view_mode'] == 'HISTORICAL_ASOF'
    assert result['selected_asof_cutoff'] == '2026-11-20T23:59:59.999999+08:00'
    assert result['material_lifecycle']['reader_asof_cutoff'] == '2026-11-20T23:59:59.999999+08:00'
    assert result['material_lifecycle']['selected_asof_cutoff'] == result['selected_asof_cutoff']
    assert result['observation_date'] == OBSERVATION_DATE


def test_missing_material_is_not_promoted_to_a_prior_company_snapshot():
    answer = fixture_answer()
    answer['status'] = 'NOT_MATERIALIZED'
    source = Source(answer)

    assert prior_company_snapshot(source, product(), SOURCE_DATE, OBSERVATION_DATE, SYMBOL, ROSTER_SHA) is None


def test_prior_exact_roster_company_snapshot_preserves_both_selection_identities():
    prior_product = dict(data_date='20261119', source_generation='1' * 64,
        source_identity=dict(input_sha256='2' * 64),
        manifest=dict(path='/products/20261119.json', sha256='3' * 64))
    old_observation = '20261120'
    old_roster = dict(path='/formula-groups/20261119/artifact.json', sha256='4' * 64)
    answer = fixture_answer()
    answer['data_date'] = '20261119'
    answer['source_generation'] = '1' * 64
    answer['input_sha256'] = '2' * 64
    answer['numeric_manifest'] = prior_product['manifest']
    answer['company_scope_status'] = 'FORMULA_ROSTER_EXACT_MATCH'
    answer['formula_roster_sha256'] = old_roster['sha256']
    answer['formula_group_membership'] = dict(symbol=SYMBOL, source_date='20261119',
        observation_date=old_observation, roster_sha256=old_roster['sha256'],
        owner_row_ref=dict(path='/formula-groups/20261119/rows/000610.json', sha256='5' * 64))
    answer['material_lifecycle']['current_candidate_identity'] = dict(data_date='20261119',
        source_generation='1' * 64, input_sha256='2' * 64, numeric_manifest=prior_product['manifest'])
    answer['materials']['source_generation'] = '1' * 64
    answer['materials']['input_sha256'] = '2' * 64
    answer['materials']['numeric_manifest'] = prior_product['manifest']
    answer['materials']['business_reported'] = {'value':None}
    answer['materials']['financials_reported'] = {'latest_report_period':None}
    answer['materials']['received_fundamentals'] = {'received_source_record':{
        'business_and_profit_sources':'原始 D19 主营叙述',
        'financial_period':'2026年三季报',
        'secondary_screen':'不得输出'}}
    answer['materials']['formula_group_scope'] = dict(schema='V4_FORMULA_GROUP_SCOPED_IMPORT_V1',
        source_date='20261119', observation_date=old_observation,
        source_generation='1' * 64, input_sha256='2' * 64,
        numeric_manifest=prior_product['manifest'], roster_sha256=old_roster['sha256'])

    result = prior_company_snapshot_from_answer(answer, product(), SOURCE_DATE, OBSERVATION_DATE,
        SYMBOL, ROSTER_SHA, prior_product=prior_product,
        prior_source_date='2026-11-19', prior_observation_date='2026-11-20',
        prior_roster_ref=old_roster)

    assert result['source_date'] == '20261119'
    assert result['selected_source_date'] == SOURCE_DATE
    assert result['observation_date'] == OBSERVATION_DATE
    assert result['current_candidate_identity']['data_date'] == '20261120'
    assert result['prior_formula_scope']['source_date'] == '20261119'
    assert result['prior_formula_scope']['observation_date'] == '20261120'
    assert result['prior_formula_scope']['roster_sha256'] == old_roster['sha256']
    assert result['business_reported']['value'] == '原始 D19 主营叙述'
    assert result['financials_reported']['latest_report_period'] == '2026年三季报'
    assert 'received_fundamentals' not in result
    assert 'secondary_screen' not in result and 'formula_group_scope' not in result


@pytest.mark.parametrize('received_at', [
    '2026-11-19T23:45:51.227370',
    '2026-11-21T00:00:00+08:00',
])
def test_prior_company_rejects_naive_or_after_selected_cutoff_receipt(received_at):
    answer = fixture_answer()
    answer['material_lifecycle']['received_at'] = received_at

    with pytest.raises(ValueError, match='WORKBENCH_PRIOR_COMPANY_SOURCE_CONFLICT'):
        prior_company_snapshot_from_answer(answer, product(), SOURCE_DATE, OBSERVATION_DATE,
            SYMBOL, ROSTER_SHA)


def test_prior_company_checks_reader_cutoff_but_preserves_later_current_reader_cutoff():
    answer = fixture_answer()
    answer['material_lifecycle']['asof_cutoff'] = '2026-11-20T12:00:00+08:00'
    answer['material_lifecycle']['received_at'] = '2026-11-20T13:00:00+08:00'
    with pytest.raises(ValueError, match='WORKBENCH_PRIOR_COMPANY_SOURCE_CONFLICT'):
        prior_company_snapshot_from_answer(answer, product(), SOURCE_DATE, OBSERVATION_DATE,
            SYMBOL, ROSTER_SHA)

    answer = fixture_answer()
    answer['material_lifecycle']['asof_cutoff'] = '2026-11-21T00:10:00+08:00'
    answer['material_lifecycle']['received_at'] = '2026-11-20T23:59:59.999999+08:00'
    result = prior_company_snapshot_from_answer(answer, product(), SOURCE_DATE, OBSERVATION_DATE,
        SYMBOL, ROSTER_SHA)

    assert result['received_at'] == answer['material_lifecycle']['received_at']
    assert result['material_lifecycle']['reader_asof_cutoff'] == '2026-11-21T00:10:00+08:00'
    assert result['selected_asof_cutoff'] == '2026-11-20T23:59:59.999999+08:00'


def test_caller_cannot_weaken_selected_source_cutoff():
    with pytest.raises(ValueError, match='WORKBENCH_PRIOR_COMPANY_SELECTED_CUTOFF_INVALID'):
        prior_company_snapshot_from_answer(fixture_answer(), product(), SOURCE_DATE,
            OBSERVATION_DATE, SYMBOL, ROSTER_SHA,
            selected_asof_cutoff='2026-11-21T23:59:59.999999+08:00')


def test_prior_f10_reads_only_earlier_owner_receipts_and_keeps_original_lineage(tmp_path):
    source, current = prior_f10_fixture(tmp_path)

    result = prior_f10_snapshot(source, current, SOURCE_DATE, OBSERVATION_DATE, SYMBOL)

    assert result['status'] == 'PRIOR_AVAILABLE'
    assert result['source_date'] == '20261119'
    assert result['selected_source_date'] == SOURCE_DATE
    assert result['selected_observation_date'] == OBSERVATION_DATE
    assert result['material_identity']['data_date'] == '20261119'
    assert result['current_candidate_identity']['data_date'] == '20261120'
    assert result['f10']['captured_at'] == '2026-11-19T22:00:00+08:00'


def test_prior_f10_resolves_legacy_numeric_manifest_through_derivatives_receipt(tmp_path):
    source, current = prior_f10_fixture(tmp_path)
    bind_legacy_f10_derivatives_receipt(source)

    result = prior_f10_snapshot(source, current, SOURCE_DATE, OBSERVATION_DATE, SYMBOL)

    assert result['source_date'] == '20261119'
    assert result['material_identity']['numeric_manifest']['path'].endswith('old-manifest.json')


def test_unbound_newer_f10_date_is_skipped_in_favor_of_older_verified_snapshot(tmp_path):
    source, current = prior_f10_fixture(tmp_path, prior_day='20261118')
    add_unbound_f10_receipt(source, '20261119')

    result = prior_f10_snapshot(source, current, SOURCE_DATE, OBSERVATION_DATE, SYMBOL)

    assert result['source_date'] == '20261118'
    assert result['status'] == 'PRIOR_AVAILABLE'


def test_historical_selection_never_reads_a_future_f10_receipt(tmp_path):
    source, current = prior_f10_fixture(tmp_path, prior_day='20261120')
    current['data_date'] = '20261119'

    result = prior_f10_snapshot(source, current, '2026-11-19', '2026-11-20', SYMBOL)

    assert result is None
