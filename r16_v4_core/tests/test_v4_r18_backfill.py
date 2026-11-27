"""Historical D25 replay against real r17 owners, never a live service or scheduler."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from test_v4_r16_authoritative_slots import (
    DAY, a_daily_entry, hk_cache_entry, observation_fixture, research_entries, snapshot,
    stage7_entry, write_ref,
)
from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.runner import a_daily_authority, cli
from v4_core.runner.state import writer_lease
from v4_core.runner.cache_lanes import read_hk_cache
from v4_core.runner.evidence import EvidenceError
from v4_core.storage.db import V4Store

A = 'slot_4_a_share_daily'
HK = 'slot_5_hk_and_evening'
REVIEW = 'slot_6_review_and_maint'


def tree(root):
    return {p.relative_to(root): (p.stat().st_mtime_ns, sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
            for p in root.rglob('*')}


@pytest.fixture
def setup(tmp_path, monkeypatch, capsys):
    for key in list(os.environ):
        if key.startswith('V4_'):
            monkeypatch.delenv(key)
    home = tmp_path / 'candidate'
    monkeypatch.setenv('V4_CORE_HOME', str(home))
    monkeypatch.setenv('V4_R16_INPUT_DIR', str(tmp_path / 'inputs'))
    monkeypatch.setenv('V4_MIN_FREE_GIB', '0')

    def invoke(slot, *flags):
        try:
            code = cli.main(['backfill', '--trade-date', DAY, '--slot', slot, *flags])
        except SystemExit as exc:
            pytest.fail(f'native backfill command rejected valid arguments: {exc.code}')
        result = json.loads(capsys.readouterr().out)
        assert (code == 0) == (result['status'] in {'DRY_RUN', 'DONE'})
        return result

    return V4Config.from_env(home), invoke


def by_phase(result, phase):
    return next(row for row in result['windows'] if row['phase'] == phase)


def test_default_plan_is_read_only_and_uses_scheduled_not_manual_slots(tmp_path, setup):
    cfg, invoke = setup
    before = tree(tmp_path)
    result = invoke('all')
    assert result['status'] == 'DRY_RUN' and result['execution_mode'] == 'BACKFILL'
    phases = [row['phase'] for row in result['windows']]
    assert phases[-8:] == ['source_check', 'main_stage', 'a_daily', 'hk_ingest', 'hk_cache_write', 'hk_cache_read', 'evening', 'review']
    assert by_phase(result, 'main_preopen')['window'] == '09:25'
    assert all(r['slot_id'] != 'slot_1_preopen_research' for r in result['windows'])
    assert invoke('slot_1_preopen_research', '--mode', 'execute')['status'] == 'CANNOT_CONFIRM'
    assert tree(tmp_path) == before and not cfg.base_dir.exists()


def test_d25_checkpoint_failure_retries_without_promoting_partial_symbols(tmp_path, setup, monkeypatch):
    cfg, invoke = setup
    client = TestClient(create_app(cfg))
    route = '/api/v4/tasks/status'
    natural = V4Store(cfg.db_path)
    natural.upsert_daily_bars([{'market':'A', 'symbol':'000001.SZ', 'trade_date':'2026-11-24',
                                'open':10.8,'high':11.,'low':10.7,'close':10.9,'pre_close':None,
                                'volume':1000,'amount':10900}])
    natural.upsert_adj_factors([{'market':'A', 'symbol':'000001.SZ', 'trade_date':'2026-11-24', 'adj_factor':1.}])
    natural_bytes = cfg.db_path.read_bytes()
    natural_files = tree(cfg.data_dir)
    natural_status = client.get(route, params={'date': DAY}).json()
    query = {'date': DAY, 'slot': A, 'backfill': 'status'}
    assert client.get(route, params=query).status_code == 404
    before = tree(tmp_path)
    assert client.get(route, params={**query, 'backfill': 'dry-run'}).json()['status'] == 'DRY_RUN'
    assert tree(tmp_path) == before
    missing = invoke(A, '--mode', 'execute')
    assert by_phase(missing, 'a_daily')['schedule_status'] == 'CANNOT_CONFIRM'
    _, blank = snapshot(tmp_path)
    entry = a_daily_entry(blank.directory)
    selection = write_ref(blank.directory, 'selection.json', [
        {'trade_date': DAY, 'symbol': sym, 'selection_group': '192'}
        for sym in ('000001.SZ', '000002.SZ', '600000.SH', '688000.SH')])
    _, inputs = snapshot(tmp_path, a_daily=entry, selections=selection,
                         stage7=stage7_entry(blank.directory), workloads=research_entries(blank.directory))
    real_publish = a_daily_authority.publish_bytes

    def drift(path, data, **kw):
        if path.name == 'checkpoint.json':
            path.write_bytes(b'independent checkpoint change')
        return real_publish(path, data, **kw)

    with monkeypatch.context() as m:
        m.setattr(a_daily_authority, 'publish_bytes', drift)
        failed = by_phase(invoke(A, '--mode', 'execute'), 'a_daily')
    assert failed['schedule_status'] == 'FAILED' and 'checkpoint changed' in failed['error'].lower()
    recovered = by_phase(invoke(A, '--mode', 'execute', '--reason', 'reconciled D25 fixture'), 'a_daily')
    assert recovered['schedule_status'] == 'PARTIAL'   # three real quarantines and an incomplete HK close
    workload = recovered['workload']
    assert workload['downstream']['status'] == 'DONE'
    assert workload['downstream']['qfq']['qfq_rows_written'] == 2  # real prior + verified target, not a truncated series
    assert cfg.db_path.read_bytes() == natural_bytes
    assert tree(cfg.data_dir) == natural_files
    assert (workload['downstream']['top200_count'], workload['downstream']['workbench_quarantined_count']) == (1, 3)
    assert {row['reason'] for row in workload['quarantine']} == {
        'TARGET_DATE_MISSING', 'INVALID_BAR:non_positive_ohlc', 'SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED'}
    assert recovered['dated_inputs_sha256'] == sha256((inputs.directory / 'inputs.json').read_bytes()).hexdigest()
    assert recovered['execution_mode'] == 'BACKFILL' and recovered['reason'] == 'reconciled D25 fixture'
    assert datetime.fromisoformat(recovered['triggered_at']).date().isoformat() != DAY
    assert not recovered['natural_window_evidence'] and not recovered['pit_evidence']
    assert recovered['RESEARCH_ONLY'] and not any(recovered[k] for k in ('production_allowed','orders_sent','buy_gate_updated'))
    assert client.get(route, params=query).json()['windows'][-1]['backfill_ref'] == recovered['backfill_ref']
    assert client.get(route, params={'date': DAY}).json() == natural_status
    assert not (cfg.logs_dir / 'daily_windows').exists() and not (cfg.data_dir / 'history').exists()
    assert by_phase(invoke(REVIEW, '--mode', 'execute'), 'review')['schedule_status'] == 'CANNOT_CONFIRM'


def test_hk_evening_corrected_inputs_then_done_does_not_touch_any_file(tmp_path, setup):
    cfg, invoke = setup
    _, blank = snapshot(tmp_path)
    hour = research_entries(blank.directory)['hourly_announcements']
    raw = json.loads((blank.directory / hour['source']['path']).read_bytes())
    raw['cannot_confirm'] = []
    raw['source_manifest']['natural_execution_verified'] = True
    hour.update(status='READY', source=write_ref(blank.directory, 'verified.json', raw))
    hk_bars = write_ref(blank.directory, 'hk-bars.json', [{'trade_date': DAY, 'symbol': '00700.HK', 'market': 'HK',
                         'open': 100., 'high': 102., 'low': 99., 'close': 101., 'volume': 1000, 'amount': 100000.}])
    payload = dict(hk_cache=hk_cache_entry(blank.directory), hk_bars=hk_bars, workloads={'hourly_announcements': hour})
    snapshot(tmp_path, **payload)
    upstream = blank.directory / 'hk.csv'
    original = upstream.read_bytes()
    upstream.unlink()
    partial = invoke(HK, '--mode', 'execute')
    assert by_phase(partial, 'hk_cache_write')['schedule_status'] == 'CANNOT_CONFIRM'
    assert by_phase(partial, 'hk_cache_read')['schedule_status'] == 'CANNOT_CONFIRM'
    assert by_phase(partial, 'evening')['schedule_status'] == 'PARTIAL'
    upstream.write_bytes(original)
    hourly = by_phase(partial, 'evening')['workload']
    link = observation_fixture(blank.directory, hourly, 'good')
    payload.update(next_a_session=link['next_a_session'], workloads={**payload['workloads'], **link['workloads']})
    snapshot(tmp_path, **payload)
    success = invoke(HK, '--mode', 'execute', '--reason', 'recovered original source')
    assert success['status'] == 'DONE'
    assert by_phase(success, 'hk_cache_read')['workload']['source_identity']['artifact']['sha256'] == sha256(original).hexdigest()
    assert by_phase(success, 'evening')['paired_workloads']['next_day_observation']['target_date'] == '2026-11-26'
    before = tree(tmp_path)
    assert invoke(HK, '--mode', 'execute')['status'] == 'DONE'
    assert tree(tmp_path) == before
    with pytest.raises(SystemExit):
        cli.main(['backfill','--trade-date', DAY,'--slot', HK,'--mode','execute','--force','--reason','  '])
    assert tree(tmp_path) == before
    forced = invoke(HK, '--mode', 'execute', '--force', '--reason', 'verify restored source')
    assert by_phase(forced, 'evening')['attempt_id'] != by_phase(success, 'evening')['attempt_id']
    assert not (cfg.data_dir / 'hk_cache').exists() and not (cfg.logs_dir / 'daily_windows').exists()
    with pytest.raises(EvidenceError, match='HK_CACHE_WRITER_OUTPUT_UNAVAILABLE'):
        read_hk_cache(cfg.data_dir, DAY, '2026-11-26')
    # A crash between windows can leave an old DONE reader after a failed forced writer.
    reader_path = cfg.base_dir / by_phase(forced, 'hk_cache_read')['backfill_ref']
    previous_reader = reader_path.read_bytes()
    upstream.unlink()
    invalidated = invoke(HK, '--mode', 'execute', '--force', '--reason', 'inspect missing HK input')
    assert by_phase(invalidated, 'hk_cache_read')['schedule_status'] == 'CANNOT_CONFIRM'
    reader_path.write_bytes(previous_reader)  # retained pre-crash reader journal
    client = TestClient(create_app(cfg))
    status = client.get('/api/v4/tasks/status', params={'date':DAY, 'slot':HK, 'backfill':'status'}).json()
    assert by_phase(status, 'hk_cache_read')['schedule_status'] == 'CANNOT_CONFIRM'
    assert by_phase(invoke(HK, '--mode', 'execute'), 'hk_cache_read')['schedule_status'] == 'CANNOT_CONFIRM'
    assert reader_path.read_bytes() == previous_reader  # do not alter the old DONE without --force


def _dated_a_fixture(tmp_path, symbols):
    _, blank = snapshot(tmp_path)
    selection = write_ref(blank.directory, 'selections.json', [
        {'trade_date': DAY, 'symbol': sym, 'selection_group':'192'} for sym in symbols])
    return snapshot(tmp_path, a_daily=a_daily_entry(blank.directory), stage7=stage7_entry(blank.directory),
                    workloads=research_entries(blank.directory), selections=selection)[1]


def test_partial_retry_replaces_exact_dated_selection_and_scores(tmp_path, setup):
    cfg, invoke = setup
    symbols = ['000001.SZ', '000002.SZ', '600000.SH', '688000.SH']
    natural = V4Store(cfg.db_path)
    natural.upsert_workbench_selections([{'trade_date':DAY, 'symbol':'000999.SZ', 'selection_group':'192'}])
    before = tree(cfg.data_dir)
    inputs = _dated_a_fixture(tmp_path, symbols)
    first = by_phase(invoke(A, '--mode','execute'), 'a_daily')['workload']
    assert first['downstream']['workbench_count'] == 4
    revised = write_ref(inputs.directory, 'new.json', [{'symbol':symbols[0], 'trade_date':DAY, 'selection_group':'192'}])
    snapshot(tmp_path, **{**inputs.payload, 'selections':revised})
    record = by_phase(invoke(A, '--mode','execute'), 'a_daily')
    assert record['upstream_sha256']['new.json'] == revised['sha256']
    assert record['workload']['downstream']['workbench_count'] == 1
    store = V4Store(cfg.base_dir / 'backfill' / DAY / 'owner-results.sqlite3')
    assert set(store.get_workbench_selections(DAY)) == {symbols[0]}
    assert [r['symbol'] for r in store.get_workbench_scores(DAY)] == [symbols[0]]
    assert set(store.get_a_workbench_quarantines(DAY)) == set(symbols[1:])
    assert tree(cfg.data_dir) == before
    assert natural.get_workbench_selections(DAY) == {'000999.SZ':'192'}


def test_all_runs_real_review_with_verified_partial_1610_and_unrelated_hk_gap(tmp_path, setup):
    cfg, invoke = setup
    _dated_a_fixture(tmp_path, ['000001.SZ'])
    result = invoke('all', '--mode','execute')
    a = by_phase(result, 'a_daily')
    review = by_phase(result, 'review')
    assert a['schedule_status'] == 'PARTIAL'
    assert by_phase(result, 'hk_cache_read')['schedule_status'] == 'CANNOT_CONFIRM'
    assert review['schedule_status'] == 'CANNOT_CONFIRM' and 'detail' in review['workload']
    assert review['upstream_sha256'][a['backfill_ref']] == sha256((cfg.base_dir / a['backfill_ref']).read_bytes()).hexdigest()
    bundle_path = cfg.base_dir / 'backfill' / DAY / 'products' / 'review_core' / f'{DAY}.json'
    bundle = json.loads(bundle_path.read_bytes())
    assert sha256(bundle_path.read_bytes()).hexdigest() == review['workload']['detail']['publication_sha256']
    assert bundle['inputs']['a_share_daily']['status'] == 'READY'
    assert bundle['inputs']['a_share_daily']['source_status'] == 'PARTIAL'
    assert bundle['inputs']['stage7']['status'] == 'READY' and set(bundle['cannot_confirm']) == {'fupan','hk_close'}
    assert bundle['research_only'] and not any(bundle[k] for k in ('production_allowed','orders_sent','buy_gate_updated'))
    assert review['execution_mode'] == 'BACKFILL' and not (review['pit_evidence'] or review['natural_window_evidence'])
    assert not (cfg.data_dir / 'review_core').exists()


def _external_hk(tmp_path, monkeypatch):
    rows = [{'symbol':'00700.HK','market':'HK','trade_date':DAY,'open':101.,'high':103.,'low':98.,
             'close':99.,'volume':12000,'amount':1200000.}]
    ref = write_ref(tmp_path, 'dated-hk.json', rows)
    path = tmp_path / ref['path']
    monkeypatch.setenv('V4_HK_BARS_JSON', str(path))
    return path, ref['sha256']


def test_hk_1720_binds_standalone_source_without_an_index(tmp_path, setup, monkeypatch):
    cfg, invoke = setup
    path, digest = _external_hk(tmp_path, monkeypatch)
    result = invoke(HK, '--mode', 'execute')
    ingest = by_phase(result,'hk_ingest')
    assert ingest['schedule_status'] == 'DONE' and ingest['workload']['detail']['hk_ingested_accepted'] == 1
    assert ingest['dated_inputs_sha256'] is None and ingest['upstream_sha256'][str(path)] == digest
    assert by_phase(result, 'evening')['schedule_status'] == 'CANNOT_CONFIRM'
    assert not (cfg.data_dir / '.r16-writer.lock').exists()


@pytest.mark.parametrize('preexisting', [True,False])
def test_execute_never_writes_original_writer_metadata(setup, preexisting):
    cfg, invoke = setup
    if preexisting:
        with writer_lease(cfg.data_dir,cfg.logs_dir,'last natural writer'):
            pass
    before = tree(cfg.data_dir)
    invoke(REVIEW,'--mode','execute')
    assert tree(cfg.data_dir) == before and cfg.data_dir.exists() is preexisting
    assert (cfg.base_dir / 'backfill' / DAY / 'products' / '.r16-writer.lock').is_file()


@pytest.mark.parametrize('change', ['writer_appears','source_changes'])
def test_mutation_during_1720_cannot_publish_done(tmp_path, setup, monkeypatch, change):
    from v4_core.runner import backfill
    cfg, invoke = setup
    path, _ = _external_hk(tmp_path, monkeypatch)
    owner = backfill.dispatch_window
    def overlap(*args, **kwargs):
        result = owner(*args, **kwargs)
        if args[3] == 'hk_ingest':
            if change == 'source_changes':
                path.write_bytes(path.read_bytes() + b'\n')
            else:
                with writer_lease(cfg.data_dir, cfg.logs_dir, 'overlapping natural writer'):
                    pass
        return result
    monkeypatch.setattr(backfill, 'dispatch_window', overlap)
    record = by_phase(invoke(HK, '--mode', 'execute'), 'hk_ingest')
    assert record['schedule_status'] == 'CANNOT_CONFIRM'
    assert 'CHANGED' in record['workload']['reason']


def test_forced_1540_registry_reopen_fences_the_sources_it_actually_consumed(tmp_path, setup, monkeypatch):
    from v4_core.runner import backfill
    from v4_core.runner.cache_lanes import read_stage7

    cfg, invoke = setup
    _, blank = snapshot(tmp_path)
    stage = stage7_entry(blank.directory)
    _, inputs = snapshot(tmp_path, stage7=stage)
    assert by_phase(invoke(A, '--mode', 'execute'), 'source_check')['schedule_status'] == 'DONE'
    # The r17 reader reopens the registry's source root, not the new CLI root.
    other, _ = snapshot(tmp_path / 'other')
    monkeypatch.setenv('V4_R16_INPUT_DIR', str(other))
    artifact = inputs.directory / stage['artifact']['path']
    original = artifact.read_bytes()
    owner = backfill.dispatch_window

    def change_after_real_read(*args, **kwargs):
        result = owner(*args, **kwargs)
        if args[3] == 'source_check' and result[0] == 'READY':
            artifact.write_bytes(original + b'changed after read')
        return result

    flags = ('--mode', 'execute', '--force', '--reason', 'verify retained Stage7 registry')
    with monkeypatch.context() as m:
        m.setattr(backfill, 'dispatch_window', change_after_real_read)
        rejected = by_phase(invoke(A, *flags), 'source_check')
    products = cfg.base_dir / 'backfill' / DAY / 'products'
    with pytest.raises(EvidenceError, match='EVIDENCE_SHA256_MISMATCH:stage.csv'):
        read_stage7(products, DAY)
    assert rejected['schedule_status'] == 'CANNOT_CONFIRM'
    artifact.write_bytes(original)
    restored = by_phase(invoke(A, *flags), 'source_check')
    assert restored['schedule_status'] == 'DONE'
    audit = restored['upstream_sha256']
    index = inputs.directory / 'inputs.json'
    registry = products / 'stage_raw' / f'{DAY}.json'
    for p in (index, registry, *(inputs.directory / stage[k]['path'] for k in ('artifact','manifest','receipt'))):
        assert audit[str(p)] == sha256(p.read_bytes()).hexdigest()
    assert audit[f'{index}#stage7'] == json.loads(registry.read_bytes())['source_binding_sha256']
    assert restored['dated_inputs_sha256'] == sha256((other / DAY / 'inputs.json').read_bytes()).hexdigest()


def test_rejects_replay_result_directory_aliased_to_natural_data(tmp_path, setup):
    cfg, _ = setup
    cfg.ensure_dirs()
    replay = cfg.base_dir / 'backfill' / DAY
    replay.mkdir(parents=True)
    (replay / 'products').symlink_to(cfg.data_dir, target_is_directory=True)
    before = tree(cfg.base_dir)
    with pytest.raises(SystemExit):
        cli.main(['backfill', '--trade-date', DAY, '--slot', A, '--mode', 'execute'])
    assert tree(cfg.base_dir) == before


def test_refuses_live_writer_and_live_slot_and_recovers_expired_running(tmp_path, setup):
    cfg, invoke = setup
    with writer_lease(cfg.data_dir, cfg.logs_dir, 'real natural owner'):
        busy = invoke(REVIEW, '--mode', 'execute')
        assert busy['status'] == 'WRITER_BUSY'
    row = by_phase(invoke(REVIEW, '--mode', 'execute'), 'review')
    path = cfg.base_dir / row['backfill_ref']
    running = {**row, 'schedule_status': 'RUNNING', 'attempt_id': 'stale-case', 'pid': os.getpid(),
               'lease_expires_at': (datetime.now(cli.BEIJING) + timedelta(hours=1)).isoformat()}
    path.write_text(json.dumps(running) + '\n')
    original = path.read_bytes()
    assert by_phase(invoke(REVIEW, '--mode','execute'), 'review')['schedule_status'] == 'ALREADY_RUNNING'
    assert path.read_bytes() == original
    running['lease_expires_at'] = '2026-01-01T00:00:00+08:00'
    path.write_text(json.dumps(running) + '\n')
    recovered = by_phase(invoke(REVIEW, '--mode', 'execute'), 'review')
    assert recovered['schedule_status'] == 'CANNOT_CONFIRM' and recovered['attempt_id'] != 'stale-case'
    assert 'LEASE_EXPIRED' in path.read_text() and 'stale-case' in path.read_text()
