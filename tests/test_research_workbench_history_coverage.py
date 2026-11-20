"""Narrow regressions for workbench catalog reads and exact-day observations."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.research_workbench_host import FLAGS, ResearchWorkbenchHost
from infrastructure.research_workbench_host import checked


GENERATION = 'a' * 64
INPUT = 'b' * 64
SOURCE_DATE = '2026-11-18'
OBSERVATION_DATE = '2026-11-19'


def write_ref(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def history_host(index, tmp_path, *, skill=False):
    calls = {'index': 0, 'references': [], 'full_product': 0}

    def read_reference(reference):
        calls['references'].append(reference)
        return checked(reference)

    def read_full_product(*_args, **_kwargs):
        calls['full_product'] += 1
        raise AssertionError('history must not hydrate full daily products')

    host = object.__new__(ResearchWorkbenchHost)
    host.source = SimpleNamespace(_a_product_reference=read_reference,
                                  read_a_daily_product=read_full_product)
    host.binding = {}
    host.skill_r2 = (SimpleNamespace(history_entry=lambda observation_date: {
        'source_date': '2026-10-28', 'observation_date': observation_date,
        'revision': 'skill-generation'}) if skill else None)
    host._index = lambda: calls.__setitem__('index', calls['index'] + 1) or index
    host._observation_date = lambda source_date: source_date
    return host, calls


def manifest_ref(tmp_path, day, generation):
    manifest = {
        'schema_version': 'v4.a_share.daily_product_manifest.v1',
        'data_date': day,
        'source_generation': generation,
        'input_sha256': INPUT,
        'sample_only': False,
        **FLAGS,
    }
    return write_ref(tmp_path / f'{day}.manifest.json', manifest)


def test_history_reads_index_once_and_only_checked_manifests(tmp_path):
    date_refs = {
        '20261118': manifest_ref(tmp_path, '20261118', GENERATION),
        '20261117': manifest_ref(tmp_path, '20261117', 'c' * 64),
    }
    attempt = write_ref(tmp_path / '20261119.attempt.json', {
        'schema': 'V4_A_DAILY_DERIVATIVES_V1', 'data_date': '20261119',
        'status': 'PARTIAL', **FLAGS,
    })
    overlapping_attempt = write_ref(tmp_path / '20261118.attempt.json', {
        'schema': 'V4_A_DAILY_DERIVATIVES_V1', 'data_date': '20261118',
        'status': 'PARTIAL', **FLAGS,
    })
    host, calls = history_host({'dates': date_refs,
                                'attempts': {'20261119': attempt, '20261118': overlapping_attempt}},
                               tmp_path, skill=True)

    result = host.history()

    assert calls == {'index': 1, 'references': [date_refs['20261118'], date_refs['20261117'], attempt],
                     'full_product': 0}
    assert [row['source_date'] for row in result['days']] == [
        '2026-11-19', '2026-11-18', '2026-11-17', '2026-10-28']
    assert result['days'][0]['status'] == 'PARTIAL'
    assert result['days'][1]['numeric_manifest'] == date_refs['20261118']
    assert result['days'][3]['revision'] == 'skill-generation'


@pytest.mark.parametrize('mutation', ['wrong_date', 'wrong_schema', 'sample'])
def test_history_rejects_manifest_identity_conflict_without_full_product_load(tmp_path, mutation):
    manifest = {
        'schema_version': 'v4.a_share.daily_product_manifest.v1',
        'data_date': '20261118', 'source_generation': GENERATION,
        'input_sha256': INPUT, 'sample_only': False, **FLAGS,
    }
    if mutation == 'wrong_date':
        manifest['data_date'] = '20261117'
    elif mutation == 'wrong_schema':
        manifest['schema_version'] = 'v4.a_share.daily_product.v1'
    else:
        manifest['sample_only'] = True
    reference = write_ref(tmp_path / 'manifest.json', manifest)
    host, calls = history_host({'dates': {'20261118': reference}}, tmp_path)

    with pytest.raises(ValueError, match='WORKBENCH_DATE_MANIFEST_IDENTITY_CONFLICT'):
        host.history()

    assert calls['index'] == 1
    assert calls['full_product'] == 0


def test_history_preserves_special_skill_date_attempt_without_duplicate(tmp_path):
    attempt = write_ref(tmp_path / '20261028.attempt.json', {
        'schema': 'V4_A_DAILY_DERIVATIVES_V1', 'data_date': '20261028',
        'status': 'PARTIAL', **FLAGS,
    })
    host, calls = history_host({'dates': {}, 'attempts': {'20261028': attempt}}, tmp_path, skill=True)

    result = host.history()

    assert [row['source_date'] for row in result['days']] == ['2026-10-28']
    assert result['days'][0]['status'] == 'PARTIAL'
    assert result['days'][0]['attempt'] == attempt
    assert calls['references'] == [attempt]
    assert calls['full_product'] == 0


def observation_host(tmp_path, symbols, snapshot=None):
    generation = GENERATION
    manifest = {'path': '/fixture/manifest.json', 'sha256': 'c' * 64}
    product = {
        'rows': [{'symbol': symbol} for symbol in symbols],
        'source_generation': generation,
        'source_identity': {'input_sha256': INPUT},
        'manifest': manifest,
    }
    host = object.__new__(ResearchWorkbenchHost)
    host.skill_r2 = None
    host._is_skill_date = lambda _source_date: False
    host._view = lambda _source_date, _revision=None: product
    host._observation_date = lambda _source_date: OBSERVATION_DATE
    host._observation_commit = lambda _day: (
        {'snapshot': write_ref(tmp_path / 'snapshot.json', snapshot)} if snapshot is not None else None)
    return host, product


def snapshot_for(product, rows, **changes):
    expected = sorted(row['symbol'] for row in product['rows'])
    snapshot = {
        'schema': 'OBSERVATION_SNAPSHOT_VIEW_V1',
        'source_date': SOURCE_DATE,
        'observation_date': OBSERVATION_DATE,
        'source_generation': GENERATION,
        'input_sha256': INPUT,
        'parent_admission_sha256': GENERATION,
        'daily_contract_sha256': hashlib.sha256(json.dumps(
            expected, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
        'rows': rows,
        'analysis_admission': 'NOT_GRANTED',
        'formula_review': 'PENDING',
        **FLAGS,
    }
    snapshot.update(changes)
    return snapshot


def test_missing_observation_coverage_keeps_valid_counts_unknown(tmp_path):
    host, _ = observation_host(tmp_path, ['600001.SH', '000001.SZ'])

    result = host.observations(SOURCE_DATE, OBSERVATION_DATE)

    assert result['latest'] is None
    assert result['status'] == 'UNKNOWN_NO_BOUND_INTRADAY_SNAPSHOT'
    assert result['coverage'] == {
        'schema': 'V4_WORKBENCH_OBSERVATION_COVERAGE_V1', 'scope_kind': 'SOURCE_PRODUCT',
        'status': 'UNKNOWN_MISSING',
        'source_date': SOURCE_DATE, 'observation_date': OBSERVATION_DATE,
        'generation': GENERATION, 'input_sha256': INPUT,
        'numeric_manifest': {'path': '/fixture/manifest.json', 'sha256': 'c' * 64},
        'expected_count': 2, 'observed_count': None, 'valid_count': None, 'missing_count': None,
        'reasons': ['NO_BOUND_INTRADAY_SNAPSHOT'], **FLAGS,
    }


@pytest.mark.parametrize(('symbols', 'rows', 'status', 'counts', 'reasons'), [
    (['600001.SH', '000001.SZ', '600002.SH'], [], 'ZERO_VALID', (3, 0, 0, 3),
     ['ZERO_VALID_OBSERVATION_ROWS']),
    (['600001.SH', '000001.SZ', '600002.SH'], [{'symbol': '600001.SH'}], 'PARTIAL', (3, 1, 1, 2),
     ['MISSING_CANDIDATE_OBSERVATION_ROWS']),
    (['600001.SH', '000001.SZ'], [{'symbol': '600001.SH'}, {'symbol': '000001.SZ'}], 'COMPLETE', (2, 2, 2, 0), []),
    ([], [], 'EMPTY', (0, 0, 0, 0), ['EMPTY_EXPECTED_CANDIDATE_SCOPE']),
])
def test_observation_coverage_reports_zero_partial_complete_and_true_empty(
        tmp_path, symbols, rows, status, counts, reasons):
    host, product = observation_host(tmp_path, symbols, snapshot=None)
    snapshot = snapshot_for(product, rows)
    host._observation_commit = lambda _day: {'snapshot': write_ref(tmp_path / 'snapshot.json', snapshot)}

    result = host.observations(SOURCE_DATE, OBSERVATION_DATE)

    coverage = result['coverage']
    assert result['status'] == 'STORED_ONLY'
    assert result['latest']['schema'] == 'OBSERVATION_SNAPSHOT_VIEW_V1'
    assert (coverage['expected_count'], coverage['observed_count'], coverage['valid_count'],
            coverage['missing_count']) == counts
    assert coverage['status'] == status
    assert coverage['reasons'] == reasons


@pytest.mark.parametrize('mutation', ['generation', 'foreign', 'duplicate', 'contract'])
def test_observation_coverage_still_rejects_wrong_source_or_scope(tmp_path, mutation):
    host, product = observation_host(tmp_path, ['600001.SH', '000001.SZ'])
    snapshot = snapshot_for(product, [{'symbol': '600001.SH'}])
    if mutation == 'generation':
        snapshot['source_generation'] = 'f' * 64
    elif mutation == 'foreign':
        snapshot['rows'] = [{'symbol': '600999.SH'}]
    elif mutation == 'duplicate':
        snapshot['rows'] = [{'symbol': '600001.SH'}, {'symbol': '600001.SH'}]
    else:
        snapshot['daily_contract_sha256'] = '0' * 64
    host._observation_commit = lambda _day: {'snapshot': write_ref(tmp_path / 'snapshot.json', snapshot)}

    with pytest.raises(ValueError, match='WORKBENCH_OBSERVATION_IDENTITY_CONFLICT'):
        host.observations(SOURCE_DATE, OBSERVATION_DATE)
