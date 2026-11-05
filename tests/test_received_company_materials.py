"""Exact-scope received projection and the existing owner's real CAS/lock path."""
import copy
import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'ops/import_received_company_materials.py'
spec = importlib.util.spec_from_file_location('received_company_materials', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return m.ref(path)


@pytest.fixture
def batch(tmp_path):
    root, stage = tmp_path / 'product', tmp_path / 'stage'
    root.mkdir()
    codes = ['300149.SZ', '300856.SZ', '688111.SH']
    date, target, generation, input_sha = '20261104', '20261105', 'a' * 64, 'b' * 64
    lock = tmp_path / 'A_LONG.lock'
    lock.touch()
    owner = tmp_path / 'owner.py'
    owner.write_text('from received_company_materials import save as atomic_save\n'
                     'def save(path, value, immutable=False):\n'
                     '    return atomic_save(path, value)\n')
    # The unchanged existing adapter is a read-only dependency, explicitly pinned.
    adapter = Path(os.environ.get('V4_EXISTING_PUBLICATION_ADAPTER', str(owner)))
    product = dict(data_date=date, source_generation=generation, source_identity={'input_sha256': input_sha},
                   rows=[dict(symbol=code) for code in codes], **m.FLAGS)
    artifact = m.save(root / 'numeric.json', product)
    numeric = m.save(root / 'manifest.json', dict(data_date=date, source_generation=generation,
                     input_sha256=input_sha, artifact=artifact, **m.FLAGS))
    index = dict(dates={date: numeric, '20261029': {'keep': True}}, latest_date=date, latest=numeric,
                 company_materials={'20261029': {'keep': True}}, display_names={'keep': True},
                 top200={'keep': True}, other_owner={'value': 42})
    event = dict(schema_version='v4.a_share.daily_completion.v1', data_date=date, source_generation=generation,
                 input_sha256=input_sha, manifest=numeric, artifact=artifact, event_id='c' * 64,
                 original_charts={'keep': True}, top200={'keep': True}, status='PARTIAL_WITH_ROWS', **m.FLAGS)
    m.save(root / 'index.json', index)
    m.save(root / 'events/latest.json', event)
    fundamentals, screens, performances = [], [], []
    for i, code in enumerate(codes):
        fundamentals.append(dict(symbol=code, source_date=date, observation_date=target,
            source_generation=generation, input_digest='pack', screened_name=code, as_of='2026-11-04T23:58:08+08:00',
            business='收到的业务原文', profit_driver='营收3.14亿元，不从原文猜数', status='PARTIAL' if i == 1 else 'COMPLETED',
            source_ids=json.dumps(['source-' + code]), missing_inputs='["valuation missing"]', **m.FLAGS))
        screens.append(dict(symbol=code, source_date=date, target_date=target, v4_generation=generation,
            full_chain_status='CANNOT_CONFIRM', errors=['D_CLOSE_MISMATCH_CANONICAL'] if i == 1 else [],
            volume_to_current_MA5=0.88, volume_to_prior_MA5=0.99, p5_key_type='REVERSAL'))
        performances.append(dict(symbol=code, source_date=date, target_date=target, source_generation=generation,
            numeric_manifest_sha256=numeric['sha256'], close=11.2, current_target_day_return_pct=None,
            current_target_day_performance_status='NOT_MATERIALIZED_NOT_READ', **m.FLAGS))
    inputs = dict(fundamentals=write_csv(tmp_path / 'fund.csv', fundamentals),
        sources=write_csv(tmp_path / 'sources.csv', [dict(source_id='source-' + c, symbol=c, url='https://example.org/'+c) for c in codes]),
        claims=write_csv(tmp_path / 'claims.csv', [dict(symbol=c, statement='原文') for c in codes]),
        input_manifest=m.save(tmp_path / 'input.json', dict(source_date=date, target_date=target,
            source_generation=generation, source_input_sha256=input_sha, numeric_manifest_sha256=numeric['sha256'], input_digest='pack')),
        return_manifest=m.save(tmp_path / 'return.json', dict(source_date=date, target_date=target, input_digest='pack', **m.FLAGS)),
        secondary_rows=m.save(tmp_path / 'screen.json', screens),
        secondary_receipt=m.save(tmp_path / 'screen_receipt.json', dict(scope_size=3, strict_full_chain_certified_count=0,
            safety_flags=m.FLAGS, selected_watchlist_by_theme={'医药': {'technical_observe': [codes[0]], 'wait_for_trigger': [codes[1]]}})),
        daily_performance=m.save(tmp_path / 'performance.json', dict(rows=performances, source_date=date, target_date=target,
            source_generation=generation, numeric_manifest_sha256=numeric['sha256'], **m.FLAGS)))
    config = dict(schema='V4_RECEIVED_RESEARCH_IMPORT_V1', product_root=str(root), source_date=date, target_date=target,
        generation=generation, input_sha256=input_sha, numeric_manifest_sha256=numeric['sha256'], scope_count=3,
        owner_publisher=m.ref(owner), publication_adapter=m.ref(adapter), owner_lock=str(lock), inputs=inputs, **m.FLAGS)
    # Let the actual adapter import our fixture owner's atomic save without files
    # outside the frozen allowlist in the repository.
    import sys
    sys.modules['received_company_materials'] = m
    return dict(config=config, root=root, stage=stage, index=index, event=event, codes=codes, tmp=tmp_path)


def prepare(batch):
    return m.prepare(m.save(batch['tmp'] / 'config.json', batch['config']), batch['stage'])


def shard(plan, symbol):
    return next(m.load(local) for target, local in plan['immutable_files'].items() if target.endswith('/'+symbol+'.json'))


def test_exact_projection_preserves_raw_status_nulls_and_non_target_fields(batch):
    plan = prepare(batch)
    assert m.load(m.ref(batch['root'] / 'index.json')) == batch['index']
    assert m.load(m.ref(batch['root'] / 'events/latest.json')) == batch['event']
    after_index, after_event = m.load(plan['staged_index']), m.load(plan['staged_event'])
    assert {k: v for k, v in after_index.items() if k != 'company_materials'} == {k: v for k, v in batch['index'].items() if k != 'company_materials'}
    assert after_index['company_materials']['20261029'] == {'keep': True}
    assert {k: v for k, v in after_event.items() if k not in ('company_materials','event_id')} == {k: v for k, v in batch['event'].items() if k != 'event_id'}
    assert len(plan['immutable_files']) == 4
    row = shard(plan, batch['codes'][1])
    assert row['received_fundamentals']['status'] == 'PARTIAL'
    assert row['financials_reported'] == {} and row['shareholders_reported'] == {}
    assert row['daily_performance']['close'] == 11.2
    assert row['daily_performance']['current_target_day_return_pct'] is None
    assert all(value is None for value in row['secondary_screen']['reference_fields'].values())
    assert row['secondary_screen']['received_record']['volume_to_current_MA5'] == .88
    assert row['secondary_screen']['status'] == 'CANNOT_CONFIRM'
    assert row['secondary_screen']['role'] == 'wait_for_trigger'
    assert plan['summary']['original_producer_status_counts'] == {'COMPLETED': 2, 'PARTIAL': 1}


@pytest.mark.parametrize('mutation', ['extra','missing','duplicate','identity','sha','unsafe','target_intraday'])
def test_scope_identity_and_source_drift_fail_before_publication(batch, mutation):
    config = batch['config']
    path = Path(config['inputs']['secondary_rows']['path'])
    rows = m.load(config['inputs']['secondary_rows'])
    if mutation == 'extra': rows.append({**rows[0], 'symbol': '000001.SZ'})
    elif mutation == 'missing': rows.pop()
    elif mutation == 'duplicate': rows.append(rows[0])
    elif mutation == 'identity': rows[0]['target_date'] = '20261106'
    elif mutation == 'unsafe': config['production_allowed'] = True
    elif mutation == 'target_intraday':
        payload = m.load(config['inputs']['daily_performance'])
        payload['rows'][0]['current_target_day_return_pct'] = 1.2
        config['inputs']['daily_performance'] = m.save(Path(config['inputs']['daily_performance']['path']), payload)
    if mutation == 'sha': path.write_text('[]')
    elif mutation not in ('unsafe','target_intraday'): config['inputs']['secondary_rows'] = m.save(path, rows)
    with pytest.raises(ValueError): prepare(batch)
    assert m.load(m.ref(batch['root'] / 'index.json')) == batch['index']


@pytest.mark.skipif(not os.environ.get('V4_EXISTING_PUBLICATION_ADAPTER'), reason='Existing owner adapter must be explicitly pinned')
@pytest.mark.parametrize('drift', ['none','index','event','lock'])
def test_existing_owner_publication_cas_and_stable_lock(batch, drift):
    plan = prepare(batch)
    plan_ref = m.ref(batch['stage'] / 'PUBLICATION_PLAN.json')
    if drift in ('index','event'):
        path = batch['root'] / ('index.json' if drift == 'index' else 'events/latest.json')
        value = json.loads(path.read_text()); value['parallel_owner'] = 'preserve'; m.save(path, value)
    elif drift == 'lock':
        path = Path(batch['config']['owner_lock'])
        path.rename(path.with_suffix('.old')); path.touch()
    if drift == 'none':
        result = m.publish(plan_ref)
        assert result['status'] == 'PUBLISHED_HISTORY_SYNC'  # Existing adapter's unchanged receipt type.
        assert len(result['completed']) == 3
        assert json.loads((batch['root'] / 'index.json').read_text()) == m.load(plan['staged_index'])
    else:
        with pytest.raises(ValueError, match='DRIFT'):
            m.publish(plan_ref)
        if drift in ('index','event'):
            assert json.loads(path.read_text())['parallel_owner'] == 'preserve'
