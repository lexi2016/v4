"""SIMULATED contract/arithmetical tests. No real condition or rule approval."""
from __future__ import annotations

import copy
import importlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from domains.manager_close_discovery import build_workbench_payload
from domains.manager_research_evidence import (
    EvidenceError, persist_snapshot, read_snapshot_evidence, read_universe_evidence,
)
from infrastructure.manager_input_attestation import digest, encoded

HK = ZoneInfo('Asia/Hong_Kong')
APP = Path(__file__).resolve().parents[1]
DATE = '20260918'
AS_OF = datetime(2026, 9, 18, 15, 30, 20, tzinfo=HK)


def implementation():
    assert importlib.util.find_spec('domains.manager_condition_evidence') is not None, (
        'Existing manager owner needs the read-only content-bound condition audit'
    )
    return importlib.import_module('domains.manager_condition_evidence')


def quote(date=DATE, **changes):
    d = datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%d')
    row = {
        'fixture_label': 'SIMULATED', 'code': 'HK.00001', 'name': 'SIMULATED',
        'last_price': 12.0, 'prev_close_price': 11.0, 'turnover': 200_000_000.0,
        'currency': 'HKD', 'unit': 'HKD', 'update_time': d + ' 15:30:00',
        'volume': 300.0, 'volume_ratio': 999.0,
        'security_id': 'SIMULATED-ordinary-HK00001',
        'trading_status': 'NORMAL', 'session_definition': 'HKEX_FULL_DAY_REGULAR_V1',
        'volume_unit': 'SHARES', 'volume_measure': 'CUMULATIVE_REGULAR_SESSION',
        'volume_adjustment': 'NONE', 'share_basis_id': 'SIMULATED-no-share-change',
        'price_currency': 'HKD', 'price_unit': 'HKD_PER_SHARE',
        'price_adjustment': 'NONE', 'price_adjustment_basis_id': 'SIMULATED-no-price-action',
    }
    row.update(changes)
    return row


def publish(tmp_path, date=DATE, rows=None, *, available=None):
    from stage_center.hk_universe_preflight import ensure_hk_connect_universe
    at = available or datetime.strptime(date + '153020', '%Y%m%d%H%M%S').replace(tzinfo=HK)
    codes = [f'HK.{i:05d}' for i in range(1, 652)]
    class Frame:
        def to_dict(self, *, orient): return [{'code': c} for c in codes]
    class Quote:
        def get_plate_stock(self, plate): return 0, Frame()
        def close(self): pass
    ur = tmp_path / 'universe'
    ensure_hk_connect_universe(ur, date, now=at.replace(hour=15, minute=0), quote_context_factory=Quote)
    u = read_universe_evidence(ur, date, clock=lambda: at.replace(minute=0, second=21))
    state = tmp_path / 'state'
    persist_snapshot(state, trade_date=date, rows=rows if rows is not None else [quote(date)], errors=[],
                     started_at=at.replace(second=0), available_at=at, universe=u, app_root=APP)
    s = read_snapshot_evidence(state, date, as_of=at, universe=u, app_root=APP)
    return u, s


def audit(tmp_path, u, s, **changes):
    kwargs = dict(state_root=tmp_path/'state', universe_root=tmp_path/'universe', app_root=APP,
                  trade_date=DATE, as_of=AS_OF, universe=u, snapshot=s, clock=lambda: AS_OF)
    kwargs.update(changes)
    result = implementation().read_condition_audit(**kwargs)
    return result, implementation().condition_details(result, universe=u, snapshot=s, as_of=AS_OF)


def build(u, s, result=None):
    return build_workbench_payload(trade_date=DATE, as_of=AS_OF, generated_at=AS_OF,
        universe_source=u.source, eligible_symbols=u.codes, snapshot_source=s.source,
        snapshot_rows=s.rows, universe_evidence=u, snapshot_evidence=s,
        condition_evidence=result)


def _write_api_payload(tmp_path, payload):
    from apps.api.v35_api.app import create_app
    from infrastructure.manager_input_attestation import encoded
    path = tmp_path / 'state' / 'workbench_research' / DATE / '1530.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(payload))
    return create_app(data_root=tmp_path / 'data', shared_data_root=tmp_path / 'universe',
        ledger_root=tmp_path / 'ledger', stage_center_selection_root=tmp_path / 'stage',
        manager_research_state_root=tmp_path / 'state', current_date=DATE)


async def _get_api_payload(app):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://SIMULATED') as client:
        return await client.get('/api/v4/manager/workbench-research', params={'date': DATE})


def test_missing_archives_are_explicit_not_provider_ratio(tmp_path):
    u, s = publish(tmp_path)
    result, details = audit(tmp_path, u, s)
    row = details['symbols']['HK.00001']
    assert row['volume']['valid_sample_count'] == 0
    assert row['volume']['diagnostic_ratio'] is None
    assert row['price']['valid_sample_count'] == 0
    assert details['window']['requested_sessions'] == 20
    assert len(details['archive_gaps']) == 20
    assert row['volume']['predicate'] == row['price']['predicate'] == 'unknown'
    assert build(u, s, result)['candidates'][0]['qualified'] is None


def test_same_clock_actual_archives_compute_facts_not_conditions(tmp_path):
    publish(tmp_path, '20260916', [quote('20260916', volume=100, last_price=10)])
    publish(tmp_path, '20260917', [quote('20260917', volume=200, last_price=11)])
    u, s = publish(tmp_path)
    result, details = audit(tmp_path, u, s)
    row = details['symbols']['HK.00001']
    assert row['volume']['valid_sample_count'] == 2
    assert row['volume']['diagnostic_baseline_mean'] == 150
    assert row['volume']['diagnostic_ratio'] == 2
    assert row['price']['valid_sample_count'] == 2
    assert row['price']['sampled_low'] == 10
    assert row['price']['sampled_high'] == 11
    assert row['price']['relative_to_sampled_high_pct'] == pytest.approx(100/11)
    assert row['price']['sample_basis'] == 'SAME_CLOCK_LAST_TRADE_ONLY_NOT_DAILY_OHLC'
    assert all(len(x['artifact_sha256']) == 64 and len(x['receipt_sha256']) == 64 for x in row['volume']['samples'])
    c = build(u, s, result)['candidates'][0]
    assert [x['value'] for x in c['predicates'][1:3]] == ['unknown', 'unknown']
    assert c['volume_comparison']['ratio'] is None
    assert c['volume_comparison']['evidence_audit']['diagnostic_ratio'] == 2
    assert c['position']['historical_position_state'] == 'UNKNOWN'
    assert c['qualified'] is None


@pytest.mark.parametrize('field,value', [
    ('volume', None), ('volume', -1), ('volume', True), ('volume', float('inf')),
    ('volume_unit', None), ('volume_unit', 'LOTS'), ('volume_measure', 'FULL_DAY_TOTAL'),
    ('volume_adjustment', None), ('volume_adjustment', 'QFQ'),
    ('share_basis_id', None), ('security_id', None), ('trading_status', 'SUSPENDED'),
    ('session_definition', 'HKEX_HALF_DAY'),
])
def test_volume_contract_missing_or_invalid_is_not_filled(tmp_path, field, value):
    publish(tmp_path, '20260917', [quote('20260917')])
    u, s = publish(tmp_path, rows=[quote(**{field: value})])
    _, details = audit(tmp_path, u, s)
    row = details['symbols']['HK.00001']['volume']
    assert row['valid_sample_count'] == 0
    assert row['diagnostic_ratio'] is None
    assert row['current_gaps']


@pytest.mark.parametrize('changes', [
    {'update_time': '2026-09-17 15:30:01'},
    {'update_time': '2026-09-17 15:29:59'},
    {'update_time': '2026-09-17 15:31:00'},
    {'security_id': 'SIMULATED-other-listing'},
    {'share_basis_id': 'SIMULATED-before-split'},
    {'volume_unit': 'LOTS'}, {'trading_status': 'SUSPENDED'}, {'code': 'HK.00002'},
])
def test_history_comparability_requires_same_security_clock_and_share_basis(tmp_path, changes):
    publish(tmp_path, '20260917', [quote('20260917', **changes)])
    u, s = publish(tmp_path)
    _, details = audit(tmp_path, u, s)
    row = details['symbols']['HK.00001']['volume']
    assert row['valid_sample_count'] == 0
    assert row['excluded_samples']


@pytest.mark.parametrize('changes', [
    {'price_currency': None}, {'price_currency': 'USD'}, {'price_unit': None},
    {'price_adjustment': None}, {'price_adjustment': 'QFQ'},
    {'price_adjustment_basis_id': None}, {'price_adjustment_basis_id': 'SIMULATED-other-factor-vintage'},
    {'last_price': 0}, {'last_price': -10}, {'last_price': float('nan')}, {'last_price': True},
])
def test_price_currency_adjustment_basis_and_positive_finite_values_are_required(tmp_path, changes):
    publish(tmp_path, '20260917', [quote('20260917', **changes)])
    u, s = publish(tmp_path)
    _, details = audit(tmp_path, u, s)
    p = details['symbols']['HK.00001']['price']
    assert p['valid_sample_count'] == 0
    assert p['sampled_high'] is None
    assert p['predicate'] == 'unknown'


def test_duplicate_historical_rows_are_excluded_as_a_pair(tmp_path):
    publish(tmp_path, '20260917', [quote('20260917'), quote('20260917', volume=1)])
    u, s = publish(tmp_path)
    _, d = audit(tmp_path, u, s)
    assert d['symbols']['HK.00001']['volume']['valid_sample_count'] == 0
    assert 'DUPLICATE_QUOTE' in str(d['symbols']['HK.00001']['volume']['excluded_samples'])


def test_zero_baseline_not_infinity_and_current_zero_is_valid(tmp_path):
    publish(tmp_path, '20260917', [quote('20260917', volume=0)])
    u, s = publish(tmp_path, rows=[quote(volume=0)])
    _, d = audit(tmp_path, u, s)
    v = d['symbols']['HK.00001']['volume']
    assert v['valid_sample_count'] == 1
    assert v['diagnostic_baseline_mean'] == 0
    assert v['diagnostic_ratio'] is None
    assert 'ZERO_VOLUME_BASELINE' in v['gaps']


def test_tampered_history_is_excluded_not_repaired(tmp_path):
    _, old = publish(tmp_path, '20260917')
    path = tmp_path/'state'/old.source['artifact_ref']
    before = path.read_bytes()
    path.write_bytes(before.replace(b'300.0', b'301.0'))
    damaged = path.read_bytes()
    u, s = publish(tmp_path)
    _, d = audit(tmp_path, u, s)
    assert d['symbols']['HK.00001']['volume']['valid_sample_count'] == 0
    assert path.read_bytes() == damaged
    assert '20260917' in str(d['archive_gaps'])


def test_provider_fields_and_arbitrary_approved_claim_cannot_enable_conditions(tmp_path):
    u, s = publish(tmp_path, rows=[quote(volume_ratio=9999, approved=True,
        historical_position_state='BREAKOUT', volume_rule_version='APPROVED', source_ref='fake.json')])
    result, _ = audit(tmp_path, u, s)
    c = build(u, s, result)['candidates'][0]
    assert [p['value'] for p in c['predicates'][1:3]] == ['unknown', 'unknown']
    assert c['qualified'] is None


def test_unsealed_or_mutated_audit_not_accepted(tmp_path):
    u, s = publish(tmp_path)
    result, details = audit(tmp_path, u, s)
    mod = implementation()
    fake = mod.ConditionAudit(result.snapshot_sha256, result.universe_sha256,
                              result.as_of, result.content)
    with pytest.raises(EvidenceError): mod.condition_details(fake, universe=u, snapshot=s, as_of=AS_OF)
    details['symbols']['HK.00001']['volume']['predicate'] = True
    fresh = mod.condition_details(result, universe=u, snapshot=s, as_of=AS_OF)
    assert fresh['symbols']['HK.00001']['volume']['predicate'] == 'unknown'
    with pytest.raises(EvidenceError): build(u, s, details)


def test_audit_binds_snapshot_and_exact_as_of(tmp_path):
    u, s = publish(tmp_path)
    result, _ = audit(tmp_path, u, s)
    with pytest.raises(EvidenceError):
        implementation().condition_details(result, universe=u, snapshot=s, as_of=AS_OF.replace(second=21))
    mutated = copy.deepcopy(s)
    mutated.rows[0]['volume'] = 900
    with pytest.raises(EvidenceError):
        implementation().condition_details(result, universe=u, snapshot=mutated, as_of=AS_OF)


def test_window_is_prior_only_no_latest_fallback_no_writes(tmp_path):
    # A future archive and the current day must never become historical samples.
    publish(tmp_path, '20260921')
    u, s = publish(tmp_path)
    before = {str(p.relative_to(tmp_path)): digest(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
    _, d = audit(tmp_path, u, s)
    after = {str(p.relative_to(tmp_path)): digest(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after
    assert len(d['window']['dates']) == len(set(d['window']['dates'])) == 20
    assert max(d['window']['dates']) < DATE
    assert '20260921' not in str(d)
    assert d['rules']['volume_authorized'] is False and d['rules']['price_authorized'] is False


def test_no_condition_argument_preserves_legacy_payload(tmp_path):
    u, s = publish(tmp_path)
    args = dict(trade_date=DATE, as_of=AS_OF, generated_at=AS_OF, universe_source=u.source,
                eligible_symbols=u.codes, snapshot_source=s.source, snapshot_rows=s.rows,
                universe_evidence=u, snapshot_evidence=s)
    assert build_workbench_payload(**args) == build_workbench_payload(**args, condition_evidence=None)


def test_replaced_immutable_audit_content_cannot_be_consumed(tmp_path):
    from dataclasses import replace
    u, s = publish(tmp_path)
    result, d = audit(tmp_path, u, s)
    d['symbols']['HK.00001']['volume']['diagnostic_ratio'] = 99999
    fake = replace(result, content=encoded(d))
    with pytest.raises(EvidenceError):
        implementation().condition_details(fake, universe=u, snapshot=s, as_of=AS_OF)


def test_projected_diagnostic_contains_its_exact_content_hash_and_unknown_daily_contract(tmp_path):
    u, s = publish(tmp_path)
    result, _ = audit(tmp_path, u, s)
    candidate = build(u, s, result)['candidates'][0]
    for name in ('volume_comparison', 'position'):
        diagnostic = dict(candidate[name]['evidence_audit'])
        sha = diagnostic.pop('diagnostic_content_sha256')
        assert digest(encoded(diagnostic)) == sha
        assert len(diagnostic['archive_gaps']) == 20
        assert diagnostic['rules']['numeric_thresholds'] is None
    p = candidate['position']['evidence_audit']['daily_price_window']
    assert p['state'] == 'INPUT_UNBOUND'
    assert p['valid_sample_count'] is None and p['window_sessions'] is None
    assert p['last_usable_bar_date'] is None
    assert 'BAR_AVAILABLE_AT' in p['required_evidence']


def test_receipt_race_does_not_allow_changed_safety_after_native_admission(tmp_path):
    u, s = publish(tmp_path)
    receipt = tmp_path/'state'/s.source['receipt_ref']
    value = json.loads(receipt.read_bytes())
    value['orders_sent'] = True
    receipt.write_bytes(encoded(value))
    with pytest.raises(EvidenceError):
        audit(tmp_path, u, s)


def test_materializer_retains_diagnostics_via_existing_api_and_single_fetch(tmp_path):
    import asyncio
    import httpx
    from test_manager_materializer_rework import inputs, fingerprint
    from test_manager_r2_rework import row
    from ops import materialize_manager_close_discovery as materializer
    from apps.api.v35_api.app import create_app
    args = inputs(tmp_path)
    calls = []
    def fetch(*args):
        calls.append(args)
        return [row()], []
    result = materializer.materialize(**args, snapshot_fetcher=fetch)
    assert result['status'] == 'MATERIALIZED' and len(calls) == 1
    app = create_app(data_root=tmp_path/'data', shared_data_root=tmp_path/'universe',
        ledger_root=tmp_path/'ledger', stage_center_selection_root=tmp_path/'stage',
        manager_research_state_root=tmp_path/'state', current_date=DATE)
    before = fingerprint(tmp_path)
    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://SIMULATED') as client:
            response = await client.get('/api/v4/manager/workbench-research', params={'date': DATE})
            assert response.status_code == 200
            body = response.json()
            c = body['candidates'][0]
            for k in ('volume_comparison', 'position'):
                a = c[k]['evidence_audit']
                assert a['predicate'] == 'unknown' and a['approved_valid_sample_count'] is None
                assert len(a['archive_gaps']) == 20
            assert c['qualified'] is None
            assert body['RESEARCH_ONLY'] is True and body['production_allowed'] is False
            assert body['buy_gate_updated'] is False and body['orders_sent'] is False
    asyncio.run(get())
    assert fingerprint(tmp_path) == before and len(calls) == 1
    assert materializer.materialize(**args, snapshot_fetcher=fetch)['status'] == 'ALREADY_EXISTS'
    assert len(calls) == 1


def test_get_rejects_rehashed_diagnostic_sample_against_published_quote(tmp_path):
    import asyncio
    from apps.api.v35_api.manager_workbench_router import validate_workbench_payload

    publish(tmp_path, '20260917', [quote('20260917', volume=100, last_price=10)])
    u, s = publish(tmp_path, rows=[quote(volume=300, last_price=12)])
    result, _ = audit(tmp_path, u, s)
    payload = build(u, s, result)
    sample = payload['candidates'][0]['volume_comparison']['evidence_audit']['samples'][0]
    sample['value'] = 987654321.0
    sample['quote_sha256'] = '0' * 64
    diagnostic = payload['candidates'][0]['volume_comparison']['evidence_audit']
    diagnostic.pop('diagnostic_content_sha256')
    diagnostic['diagnostic_content_sha256'] = digest(encoded(diagnostic))
    # The writer-side contract only checks the projection's own hash.  The
    # GET path adds the existing owner archive binding below.
    validate_workbench_payload(payload, expected_date=DATE)
    app = _write_api_payload(tmp_path, payload)
    response = asyncio.run(_get_api_payload(app))
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'FAILED'
    assert body['candidates'] == []
    assert body['cannot_confirm'] == ['WORKBENCH_RESEARCH_ARTIFACT_INVALID']
    assert '987654321.0' not in response.text


def test_get_accepts_diagnostic_when_published_archives_match(tmp_path):
    import asyncio

    publish(tmp_path, '20260917', [quote('20260917', volume=100, last_price=10)])
    u, s = publish(tmp_path, rows=[quote(volume=300, last_price=12)])
    result, _ = audit(tmp_path, u, s)
    app = _write_api_payload(tmp_path, build(u, s, result))
    response = asyncio.run(_get_api_payload(app))
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'PARTIAL'
    assert len(body['candidates']) == 1
    assert body['candidates'][0]['volume_comparison']['evidence_audit']['valid_sample_count'] == 1
    assert body['candidates'][0]['volume_comparison']['evidence_audit']['samples'][0]['value'] == 100.0


def test_get_keeps_legacy_r2_payload_without_evidence_audit_readable(tmp_path):
    import asyncio

    u, s = publish(tmp_path, rows=[quote(volume=300, last_price=12)])
    payload = build(u, s)
    assert 'evidence_audit' not in payload['candidates'][0]['volume_comparison']
    assert 'evidence_audit' not in payload['candidates'][0]['position']
    app = _write_api_payload(tmp_path, payload)
    response = asyncio.run(_get_api_payload(app))
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'PARTIAL'
    assert len(body['candidates']) == 1
    assert body['candidates'][0]['qualified'] is None


@pytest.mark.parametrize('mutation', [
    lambda a: a.update(diagnostic_ratio=999),
    lambda a: a.update(predicate=True),
    lambda a: a.update(approved_valid_sample_count=0),
    lambda a: a['current_snapshot'].update(artifact_sha256='0'*64),
    lambda a: a['current_snapshot'].update(available_at='2026-09-18T15:31:00+08:00'),
    lambda a: a['rules'].update(volume_authorized=True),
])
def test_existing_router_rejects_corrupt_or_self_approved_projection(tmp_path, mutation):
    from apps.api.v35_api.manager_workbench_router import validate_workbench_payload, WorkbenchResearchContractError
    u, s = publish(tmp_path)
    result, _ = audit(tmp_path, u, s)
    payload = build(u, s, result)
    a = payload['candidates'][0]['volume_comparison']['evidence_audit']
    mutation(a)
    # Rehash all cases except corrupt arithmetic: a checksum is not permission.
    if a.get('diagnostic_ratio') != 999:
        a.pop('diagnostic_content_sha256')
        a['diagnostic_content_sha256'] = digest(encoded(a))
    with pytest.raises(WorkbenchResearchContractError):
        validate_workbench_payload(payload, expected_date=DATE)


def test_conflicting_explicit_market_excludes_history(tmp_path):
    publish(tmp_path, '20260917', [quote('20260917', market='US')])
    u, s = publish(tmp_path)
    _, d = audit(tmp_path, u, s)
    assert d['symbols']['HK.00001']['volume']['valid_sample_count'] == 0
    assert d['symbols']['HK.00001']['price']['valid_sample_count'] == 0


def test_finite_extreme_volume_mean_cannot_abort_existing_owner(tmp_path):
    import sys
    for day in ('20260915', '20260916', '20260917'):
        publish(tmp_path, day, [quote(day, volume=sys.float_info.max)])
    u, s = publish(tmp_path, rows=[quote(volume=sys.float_info.max)])
    _, d = audit(tmp_path, u, s)
    v = d['symbols']['HK.00001']['volume']
    assert v['valid_sample_count'] == 3
    assert v['diagnostic_baseline_mean'] == sys.float_info.max
    assert v['diagnostic_ratio'] == 1
    assert v['predicate'] == 'unknown'
