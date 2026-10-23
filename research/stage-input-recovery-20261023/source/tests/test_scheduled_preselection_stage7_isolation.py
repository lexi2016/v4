"""An unreadable optional Stage7 lane must not suppress verified sibling pools."""
import csv
import hashlib
import json
from pathlib import Path

import pytest

from ops import materialize_scheduled_preselection as scheduled


def _stage7_manifest():
    return {
        'status': 'STAGE7_TAIL_POOL_READY', 'target_date': '20261023',
        'signal_date': '20261022', 'source_role': 'real_d1_stage7_tail_replay',
        'row_count': 1, 'upstream_manifest': {
            'trade_date': '20261022', 'stage_id': 'STAGE_1445_1500',
            'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        },
    }


def _run(tmp_path, monkeypatch, raw, manifest=None):
    day = tmp_path / '20261023'
    day.mkdir()
    (day / 'stage7.csv').write_bytes(raw)
    (day / 'stage7.manifest.json').write_text(json.dumps(manifest or _stage7_manifest()))
    (day / 'fupan.csv').write_text('sentinel')
    (day / 'fupan.manifest.json').write_text('{}')
    a = {'pool_id': 'a_d1_premarket_pool', 'rows': [{'symbol': 'A.000001'}]}
    fupan = {'pool_id': 'a_d1_fupan_watchlist_pool', 'rows': [{'symbol': 'A.000002'}]}
    research = {'pool_id': 'a_share_research_recommendation_pool', 'rows': [{'symbol': 'A.000003'}]}
    hk = {'pool_id': 'hkconnect_d1_top100', 'status': 'STRICT_0_2_READY',
          'rows': [{'symbol': f'HK.{index:05d}'} for index in range(1, 101)]}
    monkeypatch.setattr(scheduled, 'build_hourly_research_pool', lambda *a, **k: research)
    monkeypatch.setattr(scheduled, 'build_fupan_watchlist_pool', lambda *a, **k: fupan)
    monkeypatch.setattr(scheduled, 'build_shared_hk_0_2_pool', lambda *a, **k: hk)
    monkeypatch.setattr(scheduled, 'load_baimao_preselection_pool', lambda *a, **k: {'pool_id': 'a_share_baimao_research_map', 'rows': []})
    before = {p: p.read_bytes() for p in day.iterdir()}
    artifacts = scheduled.build_scheduled_artifacts(
        trade_date='20261023', signal_date='20261022', selector=None,
        input_root=tmp_path, shared_data_root=tmp_path / 'shared',
        shared_package_root=tmp_path / 'package', data_root=tmp_path / 'data',
        reuse_formal_pools={'a_d1_premarket_pool': a},
    )
    assert {p: p.read_bytes() for p in day.iterdir()} == before
    by_id = {item['pool_id']: item for item in artifacts}
    assert by_id[a['pool_id']] == a
    assert by_id[fupan['pool_id']] is fupan
    assert by_id[research['pool_id']] is research
    assert by_id[hk['pool_id']] is hk
    assert len(by_id[hk['pool_id']]['rows']) == 100
    return by_id['a_d1_stage7_fenshi_review_pool'], day


@pytest.mark.parametrize('raw,error_type', [
    (b'stock_code,signal_date,cannot_confirm\n000001,20261022,' + b'x' * 140000 + b'\n', 'Error'),
    (b'stock_code,signal_date,cannot_confirm\n000001,20261022,\xff\n', 'UnicodeDecodeError'),
], ids=['oversized-field', 'invalid-utf8'])
def test_optional_stage7_parse_failure_preserves_ready_siblings(tmp_path, monkeypatch, raw, error_type):
    limit = csv.field_size_limit()
    artifact, day = _run(tmp_path, monkeypatch, raw)
    assert csv.field_size_limit() == limit
    assert artifact['source_role'] == 'EXPECTED_MISSING'
    assert artifact['rows'] == []
    assert artifact['status'] == 'CANNOT_CONFIRM'
    assert any(f'A_D1_STAGE7_INPUT_CONTRACT_INVALID:{error_type}:' in r for r in artifact['cannot_confirm'])
    for name in ('stage7.csv', 'stage7.manifest.json'):
        p = day / name
        assert f'REJECTED_INPUT_OBSERVED_AFTER_ERROR:{p}:sha256={hashlib.sha256(p.read_bytes()).hexdigest()}' in artifact['cannot_confirm']
    assert all(artifact[k] is False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))


def test_optional_stage7_valid_csv_keeps_existing_verified_behavior(tmp_path, monkeypatch):
    artifact, _ = _run(tmp_path, monkeypatch, b'stock_code,signal_date,cannot_confirm\n000001,20261022,retained\n')
    assert artifact['source_role'] == 'VERIFIED_D1_STAGE7_REPLAY'
    assert artifact['rows'][0]['symbol'] == 'A.000001'
    assert artifact['rows'][0]['cannot_confirm'] == 'retained'


def test_stage7_date_contract_error_is_still_rejected(tmp_path, monkeypatch):
    manifest = _stage7_manifest()
    manifest['signal_date'] = '20261021'
    with pytest.raises(ValueError, match='date mismatch'):
        _run(tmp_path, monkeypatch, b'stock_code,signal_date\n000001,20261022\n', manifest)
