import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest


OPS_PATH = Path(__file__).resolve().parents[1] / 'ops/observe_workbench_f10_release.py'
SPEC = importlib.util.spec_from_file_location('observe_workbench_f10_release_test', OPS_PATH)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SYMBOLS = [f'{number:06d}.SZ' for number in range(1, 23)]
RUN_ID = 'a' * 32
SOURCE_DATE = '2026-11-23'
OBSERVATION_DATE = '2026-11-24'
GENERATION = 'b' * 64
INPUT = 'c' * 64
SELECTOR = 'd' * 64
NUMERIC = dict(path='/numeric/manifest.json', sha256='e' * 64)


def _write_ref(directory, value):
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / f'{digest}.json'
    path.write_bytes(raw)
    return dict(path=str(path), sha256=digest)


def _source_bundle(root, *, source_date=SOURCE_DATE, observation_date=OBSERVATION_DATE,
        generation=GENERATION, input_sha=INPUT, symbols=None, f10_sha='f' * 64):
    symbols = list(SYMBOLS if symbols is None else symbols)
    day = source_date.replace('-', '')
    day_root = root / day
    formula = dict(schema='V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1',
        source_date=source_date, observation_date=observation_date, generation=generation,
        input_sha256=input_sha, selector_sha256=SELECTOR, numeric_manifest=NUMERIC,
        rows=[dict(symbol=symbol, display_name=symbol, groups=[]) for symbol in symbols], **FLAGS)
    formula_ref = _write_ref(day_root / 'formula/artifacts', formula)
    roster_sha = observer._canonical_sha(sorted(symbols))
    formula_receipt = dict(status='COMMITTED', source_date=source_date,
        generation=generation, numeric_manifest=NUMERIC, artifact=formula_ref, **FLAGS)
    formula_receipt_ref = _write_ref(day_root / 'formula/receipts', formula_receipt)

    daily_derivatives = dict(schema='V4_A_DAILY_DERIVATIVES_V1',
        status='COMPLETE_DESCRIPTIVE_NONPIT', data_date=day, source_generation=generation,
        completed_source_provenance=dict(status='EXACT_COMPLETED_SOURCE', numeric_manifest=NUMERIC),
        top200=dict(status='PUBLISHED_TOP200', artifact=dict(path='/top200/index.json', sha256='2' * 64),
            before=dict(symbols=[f'{i:06d}.SZ' for i in range(5000)]),
            after=dict(symbols=[f'{i:06d}.SZ' for i in range(5000)])),
        computation=dict(status='REUSED'), attempt=dict(path='/attempts/latest.json', sha256='3' * 64),
        **FLAGS)
    formula_groups = dict(status='COMMITTED', source_date=day, observation_date=observation_date,
        source_generation=generation, numeric_manifest=NUMERIC, artifact=formula_ref,
        receipt=formula_receipt_ref, workbench_supplements={}, **FLAGS)
    workload = dict(workload_id='research_panel_daily_a', status='SUCCEEDED',
        target_date=day, daily_derivatives=daily_derivatives, formula_groups=formula_groups,
        production_allowed=False, buy_gate_updated=False, orders_sent=False)
    bundle = dict(root=root, formula_ref=formula_ref, f10_ref=None, workload=workload,
        identity=dict(source_date=source_date, observation_date=observation_date,
            generation=generation, input_sha256=input_sha,
            numeric_manifest=NUMERIC, selector_sha256=SELECTOR,
            numeric_manifest_sha256=NUMERIC['sha256'], formula_group_sha256=formula_ref['sha256'],
            roster_symbols_sha256=roster_sha, roster_count=len(symbols), symbols=sorted(symbols)))
    _publish_f10_state(bundle, 'PARTIAL')
    return bundle


def _publish_f10_state(bundle, status, sequence=0):
    identity = bundle['identity']
    source_date = identity['source_date']
    day = source_date.replace('-', '')
    root = bundle['root']
    f10_receipt = dict(schema='v4.a_share.f10_daily_receipt.v1', status=status,
        data_date=day, source_generation=identity['generation'], input_sha256=identity['input_sha256'],
        selector_sha256=identity['selector_sha256'], numeric_manifest=identity['numeric_manifest'],
        priority_scope=dict(symbols=identity['symbols'], count=identity['roster_count']),
        historical_PIT=False, **FLAGS)
    if sequence:
        f10_receipt['snapshot_sequence'] = sequence
    f10_ref = _write_ref(root / 'daily_products/a_share/f10' / day / identity['generation'][:16] / 'receipts', f10_receipt)
    supplement_identity = dict(source_date=source_date,
        observation_date=identity['observation_date'], generation=identity['generation'],
        input_sha256=identity['input_sha256'], numeric_manifest=identity['numeric_manifest'],
        selector_sha256=identity['selector_sha256'],
        formula_group_sha256=identity['formula_group_sha256'],
        roster_symbols_sha256=identity['roster_symbols_sha256'], roster_count=identity['roster_count'])
    supplement_artifact = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1',
        status='PARTIAL', **supplement_identity, f10=dict(status=status, receipt=f10_ref), **FLAGS)
    day_root = root / day
    supplement_artifact_ref = _write_ref(day_root / 'supplements/artifacts', supplement_artifact)
    supplement_receipt = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1',
        status='COMMITTED', artifact=supplement_artifact_ref, **supplement_identity, **FLAGS)
    supplement_receipt_ref = _write_ref(day_root / 'supplements/receipts', supplement_receipt)
    pointer = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1',
        module='formula_group_supplement', status='PARTIAL', **supplement_identity,
        artifact=supplement_artifact_ref, receipt=supplement_receipt_ref, **FLAGS)
    latest_path = day_root / 'supplements/latest.json'
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_raw = json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    latest_path.write_bytes(latest_raw)
    pointer_ref = dict(path=str(latest_path), sha256=hashlib.sha256(latest_raw).hexdigest())
    supplement_result = dict(status='PARTIAL', **supplement_identity,
        pointer=pointer_ref, receipt=supplement_receipt_ref, artifact=supplement_artifact_ref,
        f10=dict(status=status, receipt=f10_ref), counts=dict(roster=identity['roster_count']), **FLAGS)
    bundle['f10_ref'] = f10_ref
    bundle['workload']['formula_groups']['workbench_supplements'] = supplement_result
    return f10_ref


def _dispatch(ledger, *, run_id=RUN_ID, source_date=SOURCE_DATE,
        bundle=None, slot='1610', invoked=True):
    date8 = source_date.replace('-', '')
    data = dict(schema_version='v4.scheduler_dispatch_receipt.v1', run_id=run_id,
        slot=slot, business_date=date8, target_date=date8, scheduled_date=date8,
        mode='LIVE', release_id='candidate-main', status='SUCCEEDED', attempt=1,
        selected_workload_ids=['research_panel_daily_a'],
        started_workload_ids=(['research_panel_daily_a'] if invoked else []),
        invoked_workload_ids=(['research_panel_daily_a'] if invoked else []),
        succeeded_workload_ids=(['research_panel_daily_a'] if invoked else []),
        workload_results=([bundle['workload']] if bundle is not None and invoked else []),
        production_allowed=False, buy_gate_updated=False, orders_sent=False)
    data['ledger_sha256'] = observer._canonical_sha(data)
    path = ledger / 'receipts/live' / date8 / slot / f'{run_id}.dispatch-receipt.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return path


def _api_view(bundle, *, status, observed, failed, remaining, receipt_sha, event_id):
    identity = bundle['identity']
    coverage = dict(schema='V4_WORKBENCH_FORMULA_GROUP_F10_COVERAGE_V1',
        status=status, observed=observed, failed=failed, remaining=remaining,
        source_date=identity['source_date'], observation_date=identity['observation_date'],
        generation=identity['generation'], input_sha256=identity['input_sha256'],
        numeric_manifest_sha256=identity['numeric_manifest_sha256'],
        formula_group_sha256=identity['formula_group_sha256'],
        roster_symbols_sha256=identity['roster_symbols_sha256'], roster_count=identity['roster_count'],
        receipt_sha256=receipt_sha, **FLAGS)
    day = dict(schema='RESEARCH_SYSTEM_DAY_V1', source_date=identity['source_date'],
        observation_date=identity['observation_date'], generation=identity['generation'],
        input_sha256=identity['input_sha256'], numeric_manifest=NUMERIC,
        scope_count=identity['roster_count'], rows=[dict(symbol=SYMBOLS[0])],
        formula_groups=dict(artifact=bundle['formula_ref'], f10_coverage=coverage), **FLAGS)
    versions = dict(schema='V4_WORKBENCH_VERSIONS_V1', source_date=identity['source_date'],
        observation_date=identity['observation_date'], generation=identity['generation'],
        input_sha256=identity['input_sha256'], numeric_manifest=NUMERIC,
        modules=dict(list='4' * 64), event_id=event_id, **FLAGS)
    return dict(day={k:day[k] for k in ('source_date','observation_date','generation','input_sha256','numeric_manifest','scope_count')},
        formula_coverage=coverage, formula_roster=bundle['formula_ref'], versions=versions,
        day_response=day)


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def readline(self):
        if not hasattr(self, '_read'):
            self._read = True
            return b'id: event\n'
        return b'\n'


def _prepare(tmp_path, monkeypatch, bundles):
    out = tmp_path / 'observer-output'
    out.mkdir()
    ledger = tmp_path / 'ledger'
    monkeypatch.setattr(observer, 'OUT', out)
    monkeypatch.setattr(observer, 'http', lambda path: dict(status='READ_ONLY', route=path))
    monkeypatch.setattr(observer, 'urlopen', lambda *args, **kwargs: _FakeStream())
    state = {'views': []}
    monkeypatch.setattr(observer, 'collect', lambda source_date, rows: state['views'].pop(0))
    config = dict(first_natural_date='2026-11-23', ledger_root=str(ledger), observations_required=3)
    rows = {'main': {'candidate_release_id': 'candidate-main'}}
    return out, ledger, config, rows, state


def _natural(observer_module, config, rows, day=SOURCE_DATE, hour=16):
    date = datetime.strptime(day, '%Y-%m-%d').replace(hour=hour, minute=10, tzinfo=observer_module.TZ)
    observer_module.natural_tick(config, rows, date)


def test_same_run_partial_then_complete_appends_recovery_without_rewriting_pending(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner')
    _dispatch(ledger, bundle=bundle)
    partial = _api_view(bundle, status='PARTIAL', observed=20, failed=2, remaining=0,
        receipt_sha=bundle['f10_ref']['sha256'], event_id='6' * 64)
    complete = _api_view(bundle, status='COMPLETE', observed=22, failed=0, remaining=0,
        receipt_sha='7' * 64, event_id='8' * 64)
    state['views'].append(partial)

    _natural(observer, config, rows)

    pending_paths = list(out.glob('NATURAL_*_PENDING.json'))
    assert len(pending_paths) == 1
    pending_bytes = pending_paths[0].read_bytes()
    pending = json.loads(pending_bytes)
    assert pending['business_status'] == 'PARTIAL'
    assert pending['run_id'] == RUN_ID
    assert pending['readback']['formula_coverage']['status'] == 'PARTIAL'
    assert pending['readback']['formula_coverage']['observed'] == 20
    assert pending['readback']['formula_coverage']['failed'] == 2

    complete_receipt_ref = _publish_f10_state(bundle, 'COMPLETE')
    complete = _api_view(bundle, status='COMPLETE', observed=22, failed=0, remaining=0,
        receipt_sha=complete_receipt_ref['sha256'], event_id='8' * 64)
    state['views'].append(complete)
    _natural(observer, config, rows)

    recovery_paths = list(out.glob('NATURAL_*_RECOVERY.json'))
    business_paths = list(out.glob('NATURAL_*_BUSINESS_READBACK.json'))
    assert len(recovery_paths) == 1
    assert business_paths == []
    assert pending_paths[0].read_bytes() == pending_bytes
    recovery = json.loads(recovery_paths[0].read_bytes())
    assert recovery['recovered_from'] == [pending['evidence_id']]
    assert recovery['business_status'] == 'CANNOT_CONFIRM'
    assert recovery['publisher_attribution'] == 'CANNOT_CONFIRM_PUBLISHER'
    assert recovery['readback']['formula_coverage']['status'] == 'COMPLETE'
    assert recovery['readback']['versions']['event_id'] == '8' * 64
    assert recovery['daily_derivatives']['top200']['status'] == 'PUBLISHED_TOP200'
    assert recovery['daily_derivatives']['top200']['artifact']['sha256'] == '2' * 64
    assert recovery['daily_derivatives']['top200']['before'] == {}
    assert recovery['daily_derivatives']['top200']['after'] == {}
    assert recovery['daily_derivatives']['computation']['status'] == 'REUSED'
    assert recovery['daily_derivatives']['attempt']['sha256'] == '3' * 64
    assert recovery['formula_groups']['workbench_supplements']['status'] == 'PARTIAL'
    assert observer._valid_business_days() == set()

    state['views'].append(complete)
    before = {path.name:path.read_bytes() for path in out.glob('NATURAL_*.json')}
    _natural(observer, config, rows)
    after = {path.name:path.read_bytes() for path in out.glob('NATURAL_*.json')}
    assert after == before


def test_other_run_with_different_generation_cannot_borrow_current_api_readback(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    first = _source_bundle(tmp_path / 'owner-one')
    second = _source_bundle(tmp_path / 'owner-two', generation='9' * 64, input_sha='8' * 64)
    _dispatch(ledger, run_id='a' * 32, bundle=first, slot='1610')
    _dispatch(ledger, run_id='b' * 32, bundle=second, slot='1640')
    partial = _api_view(first, status='PARTIAL', observed=20, failed=2, remaining=0,
        receipt_sha=first['f10_ref']['sha256'], event_id='6' * 64)
    state['views'].extend([partial, partial])

    _natural(observer, config, rows)

    other_pending = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1640_{"b" * 32}_*_PENDING.json'))
    assert len(other_pending) == 1
    other = json.loads(other_pending[0].read_bytes())
    assert other['business_status'] == 'CANNOT_CONFIRM'
    assert other['readback'] is None
    assert 'NATURAL_API_TO_WORKLOAD_SOURCE_IDENTITY_MISMATCH' in other['error']
    assert not list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1640_{"b" * 32}_*_BUSINESS_READBACK.json'))


def test_same_roster_second_run_owns_advanced_receipt_not_older_run(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner')
    first_path = _dispatch(ledger, run_id='a' * 32, bundle=bundle, slot='1610')
    partial = _api_view(bundle, status='PARTIAL', observed=20, failed=2, remaining=0,
        receipt_sha=bundle['f10_ref']['sha256'], event_id='6' * 64)
    state['views'].append(partial)
    _natural(observer, config, rows)
    first_pending = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_{"a" * 32}_*_PENDING.json'))
    assert len(first_pending) == 1
    original_pending_bytes = first_pending[0].read_bytes()

    new_f10_ref = _publish_f10_state(bundle, 'COMPLETE', 1)
    bundle['workload']['formula_groups']['status'] = 'ALREADY_COMMITTED'
    second_path = _dispatch(ledger, run_id='b' * 32, bundle=bundle, slot='1640')
    assert first_path.read_bytes() != second_path.read_bytes()
    complete = _api_view(bundle, status='COMPLETE', observed=22, failed=0, remaining=0,
        receipt_sha=new_f10_ref['sha256'], event_id='8' * 64)
    state['views'].extend([complete, complete])

    _natural(observer, config, rows)

    first_recovery = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_{"a" * 32}_*_RECOVERY.json'))
    first_business = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_{"a" * 32}_*_BUSINESS_READBACK.json'))
    second_business = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1640_{"b" * 32}_*_BUSINESS_READBACK.json'))
    assert len(first_recovery) == 1
    assert len(first_business) == 0
    assert len(second_business) == 1
    recovery = json.loads(first_recovery[0].read_bytes())
    business = json.loads(second_business[0].read_bytes())
    assert recovery['business_status'] == 'CANNOT_CONFIRM'
    assert recovery['publisher_attribution'] == 'CANNOT_CONFIRM_OLDER_RUN_AS_PUBLISHER'
    assert recovery['error'] == 'F10_ADVANCE_OWNED_BY_DISTINCT_DISPATCH:' + 'b' * 32
    assert business['receipt_relation'] == 'MATCHED_DISPATCH_SUPPLEMENT_RECEIPT'
    assert business['f10_receipt_sha256'] == new_f10_ref['sha256']
    assert first_pending[0].read_bytes() == original_pending_bytes


def test_two_pending_runs_unclaimed_then_late_owner_dispatch_never_promotes_old_runs(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner')
    _dispatch(ledger, run_id='a' * 32, bundle=bundle, slot='1610')
    _dispatch(ledger, run_id='b' * 32, bundle=bundle, slot='1610')
    partial_a = _api_view(bundle, status='PARTIAL', observed=20, failed=2, remaining=0,
        receipt_sha=bundle['f10_ref']['sha256'], event_id='6' * 64)
    partial_b = _api_view(bundle, status='PARTIAL', observed=20, failed=2, remaining=0,
        receipt_sha=bundle['f10_ref']['sha256'], event_id='7' * 64)
    state['views'].extend([partial_a, partial_b])
    _natural(observer, config, rows)
    pending_paths = sorted(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_PENDING.json'))
    assert len(pending_paths) == 2
    pending_bytes = {path.name:path.read_bytes() for path in pending_paths}

    new_f10_ref = _publish_f10_state(bundle, 'COMPLETE', 1)
    complete = _api_view(bundle, status='COMPLETE', observed=22, failed=0, remaining=0,
        receipt_sha=new_f10_ref['sha256'], event_id='8' * 64)
    state['views'].extend([complete, complete])
    _natural(observer, config, rows)

    unclaimed_recoveries = sorted(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_RECOVERY.json'))
    assert len(unclaimed_recoveries) == 2
    assert not list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_BUSINESS_READBACK.json'))
    assert observer._valid_business_days() == set()
    assert all(json.loads(path.read_bytes())['publisher_attribution'] == 'CANNOT_CONFIRM_PUBLISHER'
        for path in unclaimed_recoveries)

    bundle['workload']['formula_groups']['status'] = 'ALREADY_COMMITTED'
    _dispatch(ledger, run_id='c' * 32, bundle=bundle, slot='1640')
    state['views'].extend([complete, complete, complete])
    _natural(observer, config, rows)

    all_old_recoveries = sorted(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_RECOVERY.json'))
    old_business = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_BUSINESS_READBACK.json'))
    new_business = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1640_{"c" * 32}_*_BUSINESS_READBACK.json'))
    assert len(all_old_recoveries) == 4
    assert old_business == []
    assert len(new_business) == 1
    claimed = [json.loads(path.read_bytes()) for path in all_old_recoveries
        if json.loads(path.read_bytes())['publisher_claim'] is not None]
    assert len(claimed) == 2
    assert all(record['publisher_claim']['run_id'] == 'c' * 32 for record in claimed)
    assert all(path.read_bytes() == pending_bytes[path.name] for path in pending_paths)
    assert observer._valid_business_days() == {SOURCE_DATE.replace('-', '')}


def test_complete_readback_without_current_owner_sha_chain_is_not_business(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner')
    _dispatch(ledger, bundle=bundle)
    current_ref = _publish_f10_state(bundle, 'COMPLETE', 1)
    latest_path = Path(bundle['workload']['formula_groups']['workbench_supplements']['pointer']['path'])
    latest_path.write_text('{}')
    state['views'].append(_api_view(bundle, status='COMPLETE', observed=22,
        failed=0, remaining=0, receipt_sha=current_ref['sha256'], event_id='8' * 64))

    _natural(observer, config, rows)

    pending = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1610_*_PENDING.json'))
    assert len(pending) == 1
    record = json.loads(pending[0].read_bytes())
    assert record['business_status'] == 'CANNOT_CONFIRM'
    assert 'NATURAL_CURRENT_SUPPLEMENT_POINTER_CONFLICT' in record['error']
    assert not list(out.glob('NATURAL_*_BUSINESS_READBACK.json'))


def test_business_day_gate_rejects_advanced_or_unattributed_legacy_records(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner')
    direct_ref = _publish_f10_state(bundle, 'COMPLETE', 1)
    bundle['workload']['formula_groups']['status'] = 'ALREADY_COMMITTED'
    _dispatch(ledger, bundle=bundle)
    state['views'].append(_api_view(bundle, status='COMPLETE', observed=22,
        failed=0, remaining=0, receipt_sha=direct_ref['sha256'], event_id='8' * 64))
    _natural(observer, config, rows)
    direct = list(out.glob('NATURAL_*_BUSINESS_READBACK.json'))
    assert len(direct) == 1
    assert observer._valid_business_days() == {SOURCE_DATE.replace('-', '')}

    record = json.loads(direct[0].read_bytes())
    record['receipt_relation'] = 'ADVANCED_WITHIN_EXACT_RUN_SOURCE_IDENTITY'
    record['publisher_attribution'] = 'CANNOT_CONFIRM_FROM_POINTER_PREDECESSOR'
    direct[0].write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    assert not observer._business_record_valid(record)
    assert observer._valid_business_days() == set()


def test_same_day_recovery_files_count_once_and_do_not_stop_next_trade_day(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    bundle = _source_bundle(tmp_path / 'owner-one')
    _dispatch(ledger, bundle=bundle)
    views = [
        _api_view(bundle, status='PARTIAL', observed=20, failed=2, remaining=0,
            receipt_sha=bundle['f10_ref']['sha256'], event_id='6' * 64),
    ]
    for view in views:
        state['views'].append(view)
        _natural(observer, config, rows)
    for sequence, event_id in enumerate(('8' * 64, 'a' * 64, 'c' * 64), start=1):
        complete_ref = _publish_f10_state(bundle, 'COMPLETE', sequence)
        state['views'].append(_api_view(bundle, status='COMPLETE', observed=22,
            failed=0, remaining=0, receipt_sha=complete_ref['sha256'], event_id=event_id))
        _natural(observer, config, rows)
    same_day_business = list(out.glob('NATURAL_*_BUSINESS_READBACK.json'))
    same_day_recovery = list(out.glob('NATURAL_*_RECOVERY.json'))
    assert same_day_business == []
    assert len(same_day_recovery) == 3
    assert observer._valid_business_days() == set()

    next_date = '2026-11-24'
    next_bundle = _source_bundle(tmp_path / 'owner-next', source_date=next_date,
        observation_date='2026-11-25', generation='d' * 64, input_sha='e' * 64)
    next_ref = _publish_f10_state(next_bundle, 'COMPLETE', 1)
    next_bundle['workload']['formula_groups']['status'] = 'ALREADY_COMMITTED'
    _dispatch(ledger, run_id='d' * 32, source_date=next_date, bundle=next_bundle)
    state['views'].append(_api_view(next_bundle, status='COMPLETE', observed=22,
        failed=0, remaining=0, receipt_sha=next_ref['sha256'], event_id='1' * 64))

    _natural(observer, config, rows, day=next_date)

    assert len(list(out.glob(f'NATURAL_{next_date.replace("-", "")}_*_BUSINESS_READBACK.json'))) == 1
    assert observer._valid_business_days() == {next_date.replace('-', '')}


def test_uninvoked_1640_dispatch_is_archived_not_called_a_natural_run(tmp_path, monkeypatch):
    out, ledger, config, rows, state = _prepare(tmp_path, monkeypatch, [])
    _dispatch(ledger, run_id='e' * 32, bundle=None, slot='1640', invoked=False)
    obs = ledger / 'scheduler_observations/live' / SOURCE_DATE.replace('-', '') / '1640'
    obs.mkdir(parents=True)
    (obs / 'prior.observation.json').write_text(json.dumps({'status':'FINISHED','slot':'1640'}))

    _natural(observer, config, rows)

    paths = list(out.glob(f'NATURAL_{SOURCE_DATE.replace("-", "")}_1640_*_NOT_TRIGGERED.json'))
    assert len(paths) == 1
    record = json.loads(paths[0].read_bytes())
    assert record['trigger_status'] == 'NOT_TRIGGERED'
    assert record['workload_invocation_status'] == 'NOT_INVOKED'
    assert record['business_status'] == 'CANNOT_CONFIRM'
    assert record['readback'] is None
    assert record['scheduler_observations'] == [{'status':'FINISHED','slot':'1640'}]
    assert not list(out.glob('NATURAL_*_BUSINESS_READBACK.json'))
