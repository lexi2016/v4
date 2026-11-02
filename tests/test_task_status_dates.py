"""Focused receipt-date contract for the task-status projection; no live ledger writes."""
import pytest
from domains.task_status import _receipt_matches_business_date

DATE = '20261102'


def receipt(**overrides):
    value = {'business_date': DATE, 'scheduled_date': DATE, 'target_date': '20261103', 'slot': '1800'}
    value.update(overrides)
    return value


def test_hourly_next_target_slot_accepts_frozen_calendar_target():
    assert _receipt_matches_business_date(receipt(), DATE, 'hourly_research')


@pytest.mark.parametrize('target', [DATE, '20261105'])
def test_hourly_next_target_slot_rejects_wrong_target(target):
    assert not _receipt_matches_business_date(receipt(target_date=target), DATE, 'hourly_research')


def test_hourly_non_next_target_slot_accepts_business_date():
    assert _receipt_matches_business_date(receipt(slot='1000', target_date=DATE), DATE, 'hourly_research')


def test_non_hourly_receipt_requires_only_business_date():
    assert _receipt_matches_business_date(
        receipt(slot=None, scheduled_date='20261101', target_date='20261105'), DATE, None)
    assert not _receipt_matches_business_date(receipt(business_date='20261103', slot=None), DATE, None)


@pytest.mark.parametrize('slot', [None, '18', '18000', 1800])
def test_hourly_missing_or_odd_slot_is_rejected(slot):
    value = receipt()
    if slot is None: value.pop('slot')
    else: value['slot'] = slot
    assert not _receipt_matches_business_date(value, DATE, 'hourly_research')


def test_hourly_scheduled_date_must_match_business_date():
    assert not _receipt_matches_business_date(receipt(scheduled_date='20261103'), DATE, 'hourly_research')


def test_frozen_calendar_edge_rejects_unproven_next_target():
    value = receipt(business_date='20261231', scheduled_date='20261231', target_date='20270104')
    assert not _receipt_matches_business_date(value, '20261231', 'hourly_research')


@pytest.mark.parametrize('resolver', ['load_market_calendar', 'next_trade_day'])
def test_unavailable_calendar_evidence_is_a_nonmatching_receipt(monkeypatch, resolver):
    import contracts.trading_calendar as calendar
    import ops.run_scheduled_slot as owner
    def unavailable(*args, **kwargs):
        raise ValueError('market calendar cannot be loaded' if resolver == 'load_market_calendar'
                         else 'NEXT_TRADE_DAY_UNAVAILABLE')
    monkeypatch.setattr(calendar if resolver == 'load_market_calendar' else owner, resolver, unavailable)
    assert not _receipt_matches_business_date(receipt(), DATE, 'hourly_research')
    # Other workloads and same-day slots do not require next-session evidence.
    assert _receipt_matches_business_date(receipt(), DATE)
    assert _receipt_matches_business_date(receipt(slot='1000', target_date=DATE), DATE, 'hourly_research')


def test_unexpected_target_resolver_error_is_not_hidden(monkeypatch):
    import ops.run_scheduled_slot as owner
    def broken(*args, **kwargs):
        raise RuntimeError('unexpected resolver defect')
    monkeypatch.setattr(owner, 'next_trade_day', broken)
    with pytest.raises(RuntimeError, match='unexpected resolver defect'):
        _receipt_matches_business_date(receipt(), DATE, 'hourly_research')


def test_status_router_calendar_edge_is_200_with_conservative_projection(tmp_path, monkeypatch):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v4_api.runtime_router import create_runtime_router
    from infrastructure.scheduling.execution_ledger import ExecutionLedger, _ledger_digest
    for name in ('V4_TASK_STATUS_US_LEDGER_ROOT', 'V4_TASK_STATUS_EVIDENCE_ROOT', 'V4_RUNTIME_GRAPH_INBOX'):
        monkeypatch.delenv(name, raising=False)
    date = '20261231'
    value = receipt(business_date=date, scheduled_date=date, target_date='20270104',
                    mode='LIVE', run_id='calendar-edge', selected_workload_ids=['hourly_research'],
                    status='SUCCEEDED', prev_ledger_sha256='', finished_at='2026-12-31T18:01:00+08:00',
                    workload_results=[{'workload_id': 'hourly_research', 'status': 'SUCCEEDED'}],
                    production_allowed=False, buy_gate_updated=False, orders_sent=False)
    value['ledger_sha256'] = _ledger_digest(value)
    ledger_root = tmp_path / 'ledger'
    path = ledger_root / 'receipts/live/20261231/1800/calendar-edge.dispatch-receipt.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    assert ExecutionLedger(ledger_root).verify_receipt_chain(date, mode='LIVE')[0]
    app = FastAPI()
    app.include_router(create_runtime_router(tmp_path / 'data', ledger_root, tmp_path / 'selection', date))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/api/v4/tasks/status', params={'date': date})
    assert response.status_code == 200, response.text
    payload = response.json()
    hourly = next(row for row in payload['groups']['logical'] if row['workload_id'] == 'hourly_research')
    assert hourly['status'] == 'CANNOT_CONFIRM'
    assert hourly['result_code'] == 'EXECUTION_RECEIPT_DATE_MISMATCH'
    assert hourly['last_run'] is None
    assert payload['scheduler_observation']['status'] == 'RECEIPT_DATE_MISMATCH'
    assert payload['scheduler_observation']['date_bound_receipt_count'] == 0
    assert all(payload[key] is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
    assert path.read_bytes() == before
