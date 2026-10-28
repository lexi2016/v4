"""Valid natural-stage receipts can exceed the old one-MiB reader override."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from stage_center.execution_evidence import _exact_bytes, read_stage_execution


def receipt_path(root):
    path = root / '20261014/STAGE_0930_0935/receipt.json'
    path.parent.mkdir(parents=True)
    return path


def test_large_valid_receipt_is_read_without_claiming_natural_verification(tmp_path):
    receipt = {'schema_version': 'stage_center.runner.receipt.v1', 'runner': 'stage_center',
               'trade_date': '20261014', 'stage_id': 'STAGE_0930_0935', 'markets': {},
               'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
               'source_evidence': ['x' * 1_280_000]}
    raw = json.dumps(receipt).encode()
    receipt_path(tmp_path).write_bytes(raw)
    result = read_stage_execution(tmp_path, '20261014', 'STAGE_0930_0935', {})
    assert result['status'] != 'EXECUTION_RECEIPT_READ_REFUSED'
    assert result['natural_verified'] is False
    assert result['execution_verified'] is False
    assert _exact_bytes(tmp_path, '20261014', 'STAGE_0930_0935') == raw


def test_symlink_still_refused(tmp_path):
    target = tmp_path / 'other.json'
    target.write_text('{}')
    receipt_path(tmp_path).symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        _exact_bytes(tmp_path, '20261014', 'STAGE_0930_0935')


def test_malformed_json_still_refused(tmp_path):
    receipt_path(tmp_path).write_text('{invalid')
    result = read_stage_execution(tmp_path, '20261014', 'STAGE_0930_0935', {})
    assert result['status'] == 'EXECUTION_RECEIPT_READ_REFUSED'
