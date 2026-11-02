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
