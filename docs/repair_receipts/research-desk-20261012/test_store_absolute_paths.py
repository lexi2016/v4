from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
EVIDENCE_ROOT = Path('/Users/lexi/Desktop/学习/agents调试/V4_RESEARCH_DESK_20261012_FIX_R1')
LIVE_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
DATE, SLOT = '20261012', '1700'
STATUS_REL = (
    f'research_module/runtime_outputs/zsxq_hourly/{DATE}/{SLOT}/'
    f'v35_zsxq_hourly_status_{DATE}_{SLOT}.json'
)
SOURCE_REL = f'research/incoming/{DATE}/{SLOT}.json'
API_RELEASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-chain-20261012-r3/app')
SCHEDULER_RELEASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-auto-d1-20261011-r1/app')
API_STAGE = EVIDENCE_ROOT / 'writer/deploy-source/after'
SCHEDULER_STAGE = EVIDENCE_ROOT / 'writer/deploy-scheduler-source/after'


def load_candidate(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_variant(name: str):
    if name == 'api':
        release, stage = API_RELEASE, API_STAGE
        sys.path.insert(0, str(release))
        import contracts
        contract = load_candidate('contracts.research', stage / 'contracts/research.py')
        import domains
        domain = load_candidate('domains.research', stage / 'domains/research.py')
        import infrastructure
        store_module = load_candidate('infrastructure.research_store', stage / 'infrastructure/research_store.py')
    elif name == 'scheduler':
        release, stage = SCHEDULER_RELEASE, SCHEDULER_STAGE
        sys.path.insert(0, str(release))
        import contracts
        contract = load_candidate('contracts.research', stage / 'contracts/research.py')
        import domains
        load_candidate('domains.report_subjects', stage / 'domains/report_subjects.py')
        load_candidate('domains.research_hourly', stage / 'domains/research_hourly.py')
        domain = load_candidate('domains.research', stage / 'domains/research.py')
        import infrastructure
        store_module = load_candidate('infrastructure.research_store', stage / 'infrastructure/research_store.py')
    else:
        raise AssertionError(name)
    assert contract.validate_research_archive
    return domain, store_module


def copy_live_canary(root: Path, *, outside_summary: bool = False) -> tuple[dict, str, str]:
    source_raw = (LIVE_ROOT / SOURCE_REL).read_bytes()
    status_source = json.loads(source_raw.decode('utf-8-sig'))
    original_source_sha = hashlib.sha256(source_raw).hexdigest()
    receipt_relative = status_source['source_manifest']['source_receipts'][0]
    assert receipt_relative == STATUS_REL
    status_raw = (LIVE_ROOT / receipt_relative).read_bytes()
    status = json.loads(status_raw.decode('utf-8-sig'))
    run_id = status['latest_run_id']
    run_relative = f'external_sources/zsxq_hourly/{run_id}'
    assert status['paths']['run_dir'] == run_relative
    summary_relative = f'{run_relative}/zsxq_summary.json'
    fetch_relative = f'{run_relative}/zsxq_recent_topics_fetch_result.json'
    summary_raw = (LIVE_ROOT / summary_relative).read_bytes()
    fetch_raw = (LIVE_ROOT / fetch_relative).read_bytes()

    status['paths']['summary'] = str(root / summary_relative)
    status['paths']['fetch_result'] = str(root / fetch_relative)
    if outside_summary:
        status['paths']['summary'] = str(root.parent / 'outside-owned-root' / 'zsxq_summary.json')
    for relative, raw in (
        (summary_relative, summary_raw),
        (fetch_relative, fetch_raw),
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    status_path = root / receipt_relative
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    receipt_sha = hashlib.sha256(status_path.read_bytes()).hexdigest()

    source = json.loads(source_raw.decode('utf-8-sig'))
    manifest = source['source_manifest']
    manifest['source_receipt_sha256'] = receipt_sha
    proof = manifest['ready_empty_source_proof']
    proof['source_receipt_sha256'] = receipt_sha
    source_path = root / SOURCE_REL
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )
    source_input_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    return source, source_input_sha, original_source_sha


def verify_variant(name: str) -> None:
    domain, store_module = load_variant(name)
    with tempfile.TemporaryDirectory(prefix=f'{name}-absolute-path-canary-', dir=EVIDENCE_ROOT / 'writer') as temporary:
        root = Path(temporary)
        source, source_sha, original_sha = copy_live_canary(root)
        payload = domain.build_research_archive(source, source_input_sha256=source_sha)
        store = store_module.HourlyResearchStore(root)
        store.publish(payload, slot=SLOT, mode='LIVE')
        stored = store.read_exact(DATE, SLOT, mode='LIVE')
        assert stored is not None
        assert stored['article_count'] == stored['stock_pool_count'] == 0

        with tempfile.TemporaryDirectory(prefix=f'{name}-outside-path-negative-', dir=EVIDENCE_ROOT / 'writer') as negative_temp:
            negative_root = Path(negative_temp)
            bad_source, bad_sha, _ = copy_live_canary(negative_root, outside_summary=True)
            bad_payload = domain.build_research_archive(bad_source, source_input_sha256=bad_sha)
            bad_store = store_module.HourlyResearchStore(negative_root)
            try:
                bad_store.publish(bad_payload, slot=SLOT, mode='LIVE')
            except ValueError as error:
                assert 'outside the owned root' in str(error) or 'run identity mismatch' in str(error)
            else:
                raise AssertionError(f'{name} store accepted an absolute path outside its owned root')
    print(f'{name}: exact 20261012/1700 copied-source absolute-path canary PASS; root-outside negative PASS; original_input_sha256={original_sha}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: test_store_absolute_paths.py api|scheduler')
    verify_variant(sys.argv[1])
