"""Read-only real-cache canary; never invokes a quote provider, scorer or stage owner.

Run against the actual API dependency baseline, with this candidate app overlaid.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

API_BASELINE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-semantic-recovery-20261021-r4/app')
STAGE_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage')
POOL_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
STAGE = 'STAGE_0930_0935'
sys.path.insert(0, str(API_BASELINE))
spec = importlib.util.spec_from_file_location('morning_observation_candidate', Path(__file__).parents[1] / 'apps/api/v35_api/app.py')
api = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(api)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(stage=STAGE):
    from stage_center.consumer import StageSelectionConsumer
    return StageSelectionConsumer(STAGE_ROOT / 'selection', a_name_pool_root=POOL_ROOT).get('20261023', stage, allow_backfill=True)


def observe(root, pool_root, p, stage=STAGE):
    hk = p['markets']['HK_CONNECT']
    return api._hk_morning_history_observation(root / 'selection', pool_root, hk, hk['rows'], trade_date='20261023', stage_id=stage)


def test_real_conservative_four_bar_cache_produces_ten_observations(cache_copy):
    p = payload()
    root, pool = cache_copy
    info = observe(root, pool, p)
    assert info and info['window_bar_count'] == 400
    assert info['bars_per_code'] == 4 and info['d1_membership_count'] == 100
    assert info['source_id'] == 'FUTU_K_1M'
    assert info['captured_after_cutoff'] is True
    assert info['natural'] is False and info['formal_eligible'] is False
    assert info['missing_fields'] == ['order_book', 'volume_ratio', 'native_update_time', 'native_snapshot']
    assert all(info[k] is False for k in ['production_allowed', 'buy_gate_updated', 'orders_sent'])
    assert len(p['markets']['HK_CONNECT']['rows']) == 10


@pytest.fixture(scope='module')
def cache_copy(tmp_path_factory):
    root = tmp_path_factory.mktemp('history-observation')
    packets = Path('/Users/lexi/Desktop/学习/agents调试/V4_STAGE_INPUT_RECOVERY_20261023/morning-observation/observations/20261023')
    for stage, binding in api._HK_MORNING_HISTORY_20261023.items():
        for relative in binding['files']:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(STAGE_ROOT / relative, target)
        shutil.copytree(packets / stage, root / 'selection/historical_observations/20261023' / stage)
    shutil.copyfile(STAGE_ROOT / 'selection/selection_latest.json', root / 'selection/selection_latest.json')
    latest = json.loads((root / 'selection/selection_latest.json').read_text())
    for stage in api._HK_MORNING_HISTORY_20261023:
        entry = latest['entries'][f'20261023/{stage}/A_SHARE']
        source = STAGE_ROOT / 'selection' / Path(entry['artifact_relative']).parent
        shutil.copytree(source, root / 'selection' / Path(entry['artifact_relative']).parent)
    pool = root / 'pool'
    target = pool / 'preselection_pools/20261023/hkconnect_d1_top100.json'
    target.parent.mkdir(parents=True)
    shutil.copyfile(POOL_ROOT / 'preselection_pools/20261023/hkconnect_d1_top100.json', target)
    return root, pool


@pytest.mark.parametrize('mutation', ['hash', 'source', 'date', 'market', 'window', 'cutoff', 'membership', 'artifact', 'packet_hash', 'safe_window'])
def test_source_or_artifact_drift_is_hidden(cache_copy, monkeypatch, mutation):
    root, pool = cache_copy
    p = payload()
    original = copy.deepcopy(api._HK_MORNING_HISTORY_20261023)
    binding = original[STAGE]
    monkeypatch.setattr(api, '_HK_MORNING_HISTORY_20261023', original)
    relative = binding['capture_relative']
    target = root / relative
    if mutation == 'packet_hash':
        target = root / 'selection/historical_observations/20261023' / STAGE / 'observation_receipt.json'
    raw = target.read_bytes()
    try:
        cache = json.loads(raw)
        if mutation == 'safe_window':
            safe = copy.deepcopy(api._HK_MORNING_HISTORY_SAFE_PACKETS)
            safe[STAGE]['window_end'] = '2026-10-23 09:35:00'
            monkeypatch.setattr(api, '_HK_MORNING_HISTORY_SAFE_PACKETS', safe)
        elif mutation in {'hash', 'packet_hash'}:
            target.write_bytes(raw + b' ')
        elif mutation == 'artifact':
            p['markets']['HK_CONNECT']['rows'][0]['last_price'] = 999999
        elif mutation == 'cutoff':
            binding['cutoff_at'] = '2026-10-23T09:34:05+08:00'
        else:
            if mutation == 'source':
                cache['adjustment'] = 'QFQ'
            elif mutation == 'date':
                cache['trade_date'] = '20261022'
            elif mutation == 'market':
                cache['market'] = 'A_SHARE'
            elif mutation == 'window':
                next(r for r in cache['rows'] if r['time_key'] == '2026-10-23 09:31:00')['time_key'] = '2026-10-23 09:30:00'
            elif mutation == 'membership':
                cache['codes'][0] = 'HK.99999'
            target.write_text(json.dumps(cache), encoding='utf-8')
            # Pass the byte gate to exercise the separate semantic gate.
            binding['files'][relative] = sha(target)
            binding['capture_sha256'] = sha(target)
        assert observe(root, pool, p) == {}
    finally:
        target.write_bytes(raw)


def test_endpoint_four_observations_preserve_a_and_formal_boundaries(tmp_path, cache_copy):
    root, pool = cache_copy
    from stage_center.consumer import StageSelectionConsumer
    consumer = StageSelectionConsumer(STAGE_ROOT / 'selection', a_name_pool_root=POOL_ROOT)
    app = api.create_app(data_root=tmp_path, stage_center_selection_root=root / 'selection', preselection_source_root=POOL_ROOT, current_date='20261023')
    baseline_spec = importlib.util.spec_from_file_location('morning_observation_baseline', API_BASELINE / 'apps/api/v35_api/app.py')
    baseline = importlib.util.module_from_spec(baseline_spec)
    baseline_spec.loader.exec_module(baseline)
    baseline_app = baseline.create_app(data_root=tmp_path / 'baseline', stage_center_selection_root=root / 'selection', preselection_source_root=POOL_ROOT, current_date='20261023')
    with TestClient(app) as client, TestClient(baseline_app) as baseline_client:
        for stage, expected in [(STAGE, 400), ('STAGE_0935_0940', 400), ('STAGE_0940_0945', 400), ('STAGE_0945_1030', 4400)]:
            original = consumer.get('20261023', stage, allow_backfill=True)
            response = client.get('/api/v3/workbench/stage', params={'date': '20261023', 'stage': stage})
            assert response.status_code == 200
            body = response.json()
            hk = body['markets']['HK']
            assert hk['display_mode'] == 'OBSERVATION_UNVERIFIED'
            assert hk['status'] == 'PARTIAL_WITH_ROWS' and hk['observation_count'] == 10
            assert hk['historical_observation']['window_bar_count'] == expected
            assert hk['formal_count'] == 0 and hk['natural'] is False
            assert body['stage']['display_status'] == body['stage']['status'] + '；港股历史回放观察·未验证；分钟线事后采集；缺原时点盘口、量比/原生更新时间；边界分钟未计入；不能证明原时点选股结果'
            from stage_center.selection import SelectionStore
            derived = SelectionStore(root / 'selection/historical_observations/20261023' / stage / 'selection').read_verified('20261023', stage, 'HK_CONNECT')
            assert hk['rows'] == [{**row, 'order': i + 1} for i, row in enumerate(derived['rows'])]
            assert hk['original_formal_selection']['run_id'] == original['markets']['HK_CONNECT']['run_id']
            assert hk['run_id'] == derived['run_id']
            assert hk['historical_observation']['boundary_bars_excluded'] is True
            assert body['markets']['A']['run_id'] == original['markets']['A_SHARE']['run_id']
            baseline_body = baseline_client.get('/api/v3/workbench/stage', params={'date': '20261023', 'stage': stage}).json()
            assert body['markets']['A'] == baseline_body['markets']['A']
            assert len(body['markets']['A']['rows']) == 10
            assert '早盘历史回放观察 / 缺失原时点盘口 / 非正式阶段结果' in hk['display_reasons']
            assert all(row['formal_eligible'] is False for row in hk['rows'])
            assert all(hk[k] is False for k in ['production_allowed', 'buy_gate_updated', 'orders_sent'])
        unrelated = client.get('/api/v3/workbench/stage', params={'date': '20261022', 'stage': STAGE}).json()
        assert 'historical_observation' not in unrelated['markets'].get('HK', {})
        prior = baseline_client.get('/api/v3/workbench/stage', params={'date': '20261022', 'stage': STAGE}).json()
        assert unrelated['markets']['HK'] == prior['markets']['HK']
        assert unrelated['stage']['display_status'] == prior['stage']['display_status']
        manager_params = {'date': '20261023', 'stage': STAGE, 'market': 'HK_CONNECT'}
        assert client.get('/api/v3/manager/stage-selection', params=manager_params).json() == baseline_client.get('/api/v3/manager/stage-selection', params=manager_params).json()
        missing = client.get('/api/v3/workbench/stage', params={'date': '20261023', 'stage': 'STAGE_0925'}).json()
        assert missing['markets'].get('HK', {}).get('display_mode') != 'OBSERVATION_UNVERIFIED'
