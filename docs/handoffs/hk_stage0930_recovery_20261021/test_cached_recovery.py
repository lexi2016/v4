"""Incident capsule boundary checks; actual native runner result is separately recorded."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import pytest
from cached_source import audit_cache, cached_collector, sha
from recover_hk_0930_reviewed import seal_one_shot_receipt, OneShotScope, a_snapshot

HERE=Path(__file__).resolve().parent
PINS=json.loads((HERE/'operator_capsule_pins.json').read_text())


def test_exact_cached_500_bars_and_100_membership():
    dataset,rows=audit_cache(PINS)
    assert len(rows)==500 and {r['code'] for r in rows}==set(PINS['expected_codes'])
    assert dataset['captured_at']=='2026-10-21T09:41:22.678854+08:00'


def test_changed_raw_sha_rejected():
    p=copy.deepcopy(PINS);p['capture_sha256']='0'*64
    with pytest.raises(RuntimeError,match='capture bytes changed'):audit_cache(p)


def test_changed_membership_rejected():
    p=copy.deepcopy(PINS);p['expected_codes'][0]='HK.09999'
    with pytest.raises(RuntimeError,match='source100 changed'):audit_cache(p)


@pytest.mark.parametrize('pending',[True,False])
def test_all_pending_and_terminal_writes_consume_one_attempt(pending):
    raw={'markets':{'A_SHARE':{'selected_rows':10}},'execution_pending':pending,'status':'CANNOT_CONFIRM'}
    sealed=seal_one_shot_receipt(raw)
    assert sealed['operator_attempt_consumed'] is True
    assert sealed['operator_retry_authorized'] is False
    assert sealed['node_attempt_count']==2 and sealed['retry_exhausted'] is False
    assert sealed['node_outcome']=='SETTLED_PARTIAL'
    assert sealed['execution_pending']==pending


def test_missing_preserved_A_refused():
    with pytest.raises(RuntimeError,match='preserved A lane absent'):seal_one_shot_receipt({'markets':{}})


def test_actual_owner_and_A_frozen_bytes_unchanged():
    assert sha(PINS['original_receipt_path'])==PINS['original_receipt_sha256']
    assert a_snapshot(PINS['expected_config'])==PINS['expected_a_snapshot']


def test_native_isolated_acceptance_record():
    d=json.loads((HERE/'isolated_result.json').read_text())
    h=d['result']['markets']['HK_CONNECT'];o=d['observed']
    assert h['selected_rows']==10 and h['selection_status']=='PARTIAL_WITH_ROWS'
    assert len(o['selector_input_codes'])==100 and set(o['selector_input_codes'])==set(PINS['expected_codes'])
    assert o['provider_network_requests']==0 and o['selector_trade_statuses']==['NO_TRADE']
    assert d['A_PRESERVED'] and d['actual_owner_unchanged']


def test_capsule_compiles_and_support_hash_matches():
    for name in ('recover_hk_0930_reviewed.py','cached_source.py','verify_isolated.py'):
        ast.parse((HERE/name).read_text())
    assert sha(HERE/'cached_source.py')==PINS['support_sha256']
