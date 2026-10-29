"""New retry branch only: isolated sealed fixtures, no producer or network."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

import pytest

BASE = Path(__file__).resolve().parents[1]
MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-retirement-20261028-main/app')
sys.path[:0] = [str(MAIN), str(MAIN / 'upstreams')]
from infrastructure.manager_input_attestation import publish_attestation

spec = importlib.util.spec_from_file_location('candidate_retry', BASE / 'sources/main/ops/collect_hourly_research_input.py')
CANDIDATE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CANDIDATE)
HK = ZoneInfo('Asia/Shanghai')
FLAGS = {'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    owner = tmp_path / 'owner'
    for relative in ['ops/collect_hourly_research_input.py', 'domains/research_hourly.py',
                     'domains/report_subjects.py', 'infrastructure/manager_input_attestation.py']:
        source = BASE / 'sources/main' / relative if relative.startswith('ops/') else MAIN / relative
        target = owner / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    monkeypatch.setattr(CANDIDATE, '__file__', str(owner / 'ops/collect_hourly_research_input.py'))
    data = tmp_path / 'data'
    run = 'external_sources/zsxq_hourly/20261029_090000_fixture'
    summary_rel = run + '/zsxq_summary.json'
    fetch_rel = run + '/zsxq_recent_topics_fetch_result.json'
    summary_sha = write(data / summary_rel, {'ok': True, 'raw_topic_count': 1,
        'effective_topic_count': 1, 'effective_topics': [{'topic_id': 'fixture'}], **FLAGS})
    fetch_sha = write(data / fetch_rel, {'ok': True, 'success': True, 'count': 1, 'page_count': 1,
        'groups': [{'source_has_more': True, 'reached_since': False}], **FLAGS})
    status_rel = 'research_module/runtime_outputs/zsxq_hourly/20261029/0900/v35_zsxq_hourly_status_20261029_0900.json'
    status = {'schema_version': 'v3_5.zsxq_hourly_delta.v1', 'source': 'zsxq',
        'trade_date': '20261029', 'slot': '0900', 'status_path': status_rel,
        'fetch_ok': True, 'status': 'PARTIAL', 'latest_run_id': '20261029_090000_fixture',
        'paths': {'run_dir': run, 'summary': summary_rel, 'fetch_result': fetch_rel},
        'fetched_at': '2026-10-29T09:00:00+08:00',
        'source_completed_at': '2026-10-29T09:00:12+08:00',
        'source_cutoff': '2026-10-29T09:00:59+08:00',
        'summary_sha256': summary_sha, 'fetch_result_sha256': fetch_sha,
        'page_count': 1, 'topic_count': 1, 'effective_topic_count': 1,
        'cannot_confirm': ['ZSXQ_PAGINATION_BOUNDED_HAS_MORE'], **FLAGS}
    status_sha = write(data / status_rel, status)
    manifest = {'trade_date': '20261029', 'hourly_slot': '0900',
        'module_path': 'v3.5/domains/research_hourly', 'producer': 'ops.collect_hourly_research_input',
        'version': '20261029090020-0a0b0c0d', 'publication_clock_contract': 'ACTUAL_COMPLETION_V1',
        'generated_at': '2026-10-29T09:00:20+08:00', 'published_at': '2026-10-29T09:00:20+08:00',
        'pit_cutoff': '2026-10-29T09:00:59+08:00', 'source_receipts': [status_rel],
        'collector_identity_sha256': CANDIDATE._collector_identity_sha256(),
        'research_hourly_domain_identity_sha256': CANDIDATE._research_hourly_domain_identity_sha256(),
        'report_subject_policy_sha256': hashlib.sha256((owner / 'domains/report_subjects.py').read_bytes()).hexdigest(),
        'capture_origin': 'ORIGINAL_SLOT', 'original_time_capture': True,
        'natural_execution_verified': False, 'zsxq_source_completeness': 'PARTIAL',
        'zsxq_status_sha256': status_sha, 'zsxq_summary_sha256': summary_sha,
        'zsxq_fetch_result_sha256': fetch_sha,
        'zsxq_fetched_at': status['fetched_at'], 'zsxq_source_completed_at': status['source_completed_at']}
    original = {'schema_version': 'v3_research_lane.v2', 'module_id': 'research_intelligence',
        'trade_date': '20261029', 'slot': '0900', 'pit_cutoff': manifest['pit_cutoff'],
        'write_policy': 'read_only', 'default_status': 'RESEARCH_ONLY', 'buy_gate_effect': 'none',
        'live_order_effect': 'none', 'source_manifest': manifest,
        'stock_research_timeline': [{'stock_code': '002286', 'source_published_at': '2026-10-29T08:59:00+08:00'}],
        'raw_items': [{'raw_id': 'fixture', 'crawl_time': '2026-10-29T09:00:00+08:00'}]}
    path = data / 'research/incoming/20261029/0900.json'
    write(path, original)
    publish_attestation(path, data_root=data, owner_root=owner,
        available_at=datetime(2026, 10, 29, 9, 0, 21, tzinfo=HK))
    return path, original, data, owner, [status_rel, summary_rel, fetch_rel]


def regenerated(original, clock='09:06:01'):
    candidate = deepcopy(original)
    manifest = candidate['source_manifest']
    manifest.update(generated_at=f'2026-10-29T{clock}+08:00',
        published_at=f'2026-10-29T{clock}+08:00',
        version='20261029' + clock.replace(':', '') + '-0a0b0c0d',
        capture_origin='LATE_RECOVERY' if clock > '09:00:59' else 'ORIGINAL_SLOT',
        original_time_capture=clock <= '09:00:59')
    return candidate


def reject(path, candidate, **kwargs):
    before = path.read_bytes()
    sidecar = path.with_name(path.name + '.publication.json')
    publication = sidecar.read_bytes()
    with pytest.raises(ValueError, match='conflicting hourly research input|expected old input SHA mismatch'):
        CANDIDATE._atomic_json(path, candidate, **kwargs)
    assert path.read_bytes() == before
    assert sidecar.read_bytes() == publication


@pytest.mark.parametrize('clock', ['09:00:40', '09:06:01'])
def test_same_attested_source_retry_keeps_original_bytes_and_capture(sealed, clock):
    path, original, data, _, _ = sealed
    before = {str(p.relative_to(data)): p.read_bytes() for p in data.rglob('*.json')}
    candidate = regenerated(original, clock)
    assert CANDIDATE._same_sealed_original_source_retry(path, original, candidate) is True
    assert CANDIDATE._atomic_json(path, candidate) == path
    assert {str(p.relative_to(data)): p.read_bytes() for p in data.rglob('*.json')} == before
    reread = json.loads(path.read_bytes())
    assert reread['source_manifest']['capture_origin'] == 'ORIGINAL_SLOT'
    assert reread['source_manifest']['original_time_capture'] is True
    assert reread['source_manifest']['natural_execution_verified'] is False
    assert candidate['source_manifest']['generated_at'].endswith(clock + '+08:00')


@pytest.mark.parametrize('source_index', [0, 1, 2], ids=['status', 'summary', 'fetch'])
def test_changed_source_receipt_or_artifact_refuses_reuse(sealed, source_index):
    path, original, data, _, refs = sealed
    target = data / refs[source_index]
    changed = json.loads(target.read_bytes())
    changed['retry_changed_source'] = True
    write(target, changed)
    reject(path, regenerated(original))


@pytest.mark.parametrize('target', ['input', 'publication'])
def test_sealed_input_or_publication_sha_tampering_refuses_reuse(sealed, target):
    path, original, _, _, _ = sealed
    if target == 'input':
        original['raw_items'][0]['raw_id'] = 'changed-sealed-input'
        write(path, original)
    else:
        sidecar = path.with_name(path.name + '.publication.json')
        changed = json.loads(sidecar.read_bytes())
        changed['artifact_sha256'] = '0' * 64
        write(sidecar, changed)
    reject(path, regenerated(original))


@pytest.mark.parametrize('case', ['date', 'slot', 'collector', 'domain', 'policy', 'content',
    'nested-clock', 'safety', 'version-suffix', 'version-format', 'capture', 'time', 'manual-mode'])
def test_wrong_request_business_code_or_time_identity_still_conflicts(sealed, case):
    path, original, _, _, _ = sealed
    candidate = regenerated(original)
    manifest = candidate['source_manifest']
    if case == 'date': candidate['trade_date'] = '20261028'
    elif case == 'slot': manifest['hourly_slot'] = '0830'
    elif case == 'collector': manifest['collector_identity_sha256'] = '0' * 64
    elif case == 'domain': manifest['research_hourly_domain_identity_sha256'] = '0' * 64
    elif case == 'policy': manifest['report_subject_policy_sha256'] = '0' * 64
    elif case == 'content': candidate['stock_research_timeline'][0]['stock_code'] = '000001'
    elif case == 'nested-clock': candidate['raw_items'][0]['crawl_time'] = '2026-10-29T09:06:00+08:00'
    elif case == 'safety': candidate['live_order_effect'] = 'enabled'
    elif case == 'version-suffix': manifest['version'] = '20261029090601-deadbeef'
    elif case == 'version-format': manifest['version'] = 'not-a-version'
    elif case == 'capture': manifest['capture_origin'] = 'ORIGINAL_SLOT'
    elif case == 'time': manifest['published_at'] = '2026-10-29T09:00:20+08:00'
    elif case == 'manual-mode': manifest['materialization_origin'] = 'MANUAL_RECOVERY'
    reject(path, candidate)


def test_current_collector_upgrade_does_not_compatibility_reuse_old_source(sealed):
    path, original, _, owner, _ = sealed
    code = owner / 'ops/collect_hourly_research_input.py'
    code.write_text(code.read_text() + '\n# synthetic successor identity\n')
    reject(path, regenerated(original))


def test_explicit_repair_does_not_enter_automatic_reuse(sealed):
    path, original, _, _, _ = sealed
    reject(path, regenerated(original), repair_expected_old_input_sha256='0' * 64)
