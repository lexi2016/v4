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
REPO_ROOT = Path('/Users/lexi/Desktop/学习/v4_app')
RELEASE_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-auto-d1-20261011-r1/app')
STAGE = EVIDENCE_ROOT / 'writer/deploy-scheduler-source/after'
DATE, EMPTY_SLOT, NEWER_SLOT = '20261012', '1700', '2200'
SOURCE_REL = f'research/incoming/{DATE}/{EMPTY_SLOT}.json'
STATUS_REL = (
    f'research_module/runtime_outputs/zsxq_hourly/{DATE}/{EMPTY_SLOT}/'
    f'v35_zsxq_hourly_status_{DATE}_{EMPTY_SLOT}.json'
)


def load_candidate(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_variant(name: str):
    if name == 'canonical':
        sys.path.insert(0, str(REPO_ROOT))
        import contracts.research as contract
        import domains.research as domain
        import infrastructure.research_store as store_module
        return contract, domain, store_module
    if name != 'scheduler':
        raise AssertionError(name)
    sys.path.insert(0, str(RELEASE_ROOT))
    import contracts
    contract = load_candidate('contracts.research', STAGE / 'contracts/research.py')
    import domains
    load_candidate('domains.report_subjects', STAGE / 'domains/report_subjects.py')
    load_candidate('domains.research_hourly', STAGE / 'domains/research_hourly.py')
    domain = load_candidate('domains.research', STAGE / 'domains/research.py')
    import infrastructure
    store_module = load_candidate('infrastructure.research_store', STAGE / 'infrastructure/research_store.py')
    return contract, domain, store_module


def load_existing_1700_source() -> tuple[dict, str]:
    source_bytes = (LIVE_ROOT / SOURCE_REL).read_bytes()
    source = json.loads(source_bytes.decode('utf-8-sig'))
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    assert source_sha == '7fdd82b622af70725b73c42fe29e0ef4b0da36d79c626d871e769048e1c87b9a'
    assert source['source_manifest']['source_receipts'] == [STATUS_REL]
    return source, source_sha


def isolated_store(store_module, output_root: Path):
    """Read exact source artifacts from LIVE_ROOT and route all writes to temp."""
    live_prefixes = (
        'research/incoming/',
        'research_module/runtime_outputs/zsxq_hourly/',
        'external_sources/zsxq_hourly/',
    )

    class IsolatedHourlyResearchStore(store_module.HourlyResearchStore):
        def __init__(self):
            super().__init__(LIVE_ROOT)

        def _path(self, relative: str) -> Path:
            base = LIVE_ROOT if relative.startswith(live_prefixes) else output_root
            return store_module.resolve_owned_path(base, relative)

        def _read(self, relative: str):
            return json.loads(self._path(relative).read_bytes().decode('utf-8-sig'))

        def _write(self, relative: str, value) -> None:
            destination = self._path(relative)
            if destination == LIVE_ROOT or LIVE_ROOT in destination.parents:
                raise AssertionError('isolated canary attempted to write into live data root')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
                encoding='utf-8',
            )

    return IsolatedHourlyResearchStore()


def seed_valid_newer_latest(root: Path, store, contract) -> bytes:
    path = LIVE_ROOT / f'research/hourly/live/{DATE}/{NEWER_SLOT}.json'
    newer_payload = json.loads(path.read_text(encoding='utf-8-sig'))
    assert contract.validate_research_archive(newer_payload) == DATE
    result = store.publish(newer_payload, slot=NEWER_SLOT, mode='LIVE')
    assert result['latest_updated'] is True
    latest_path = root / 'research/hourly/latest.json'
    latest_bytes = latest_path.read_bytes()
    latest = json.loads(latest_bytes)
    assert latest['archive_date'] == DATE and latest['slot'] == NEWER_SLOT
    assert latest['payload_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    return latest_bytes


def verify(name: str) -> None:
    contract, domain, store_module = load_variant(name)
    with tempfile.TemporaryDirectory(prefix=f'{name}-latest22-ready-empty-', dir=EVIDENCE_ROOT / 'writer') as temporary:
        root = Path(temporary)
        store = isolated_store(store_module, root)
        latest_before = seed_valid_newer_latest(root, store, contract)
        latest_sha = hashlib.sha256(latest_before).hexdigest()
        source, source_sha = load_existing_1700_source()
        empty_payload = domain.build_research_archive(source, source_input_sha256=source_sha)
        assert contract.validate_research_archive(empty_payload) == DATE
        published = store.publish(empty_payload, slot=EMPTY_SLOT, mode='LIVE')
        assert published['latest_updated'] is False
        assert store.read_exact(DATE, EMPTY_SLOT, mode='LIVE') is not None
        assert (root / 'research/hourly/latest.json').read_bytes() == latest_before
        assert hashlib.sha256((root / 'research/hourly/latest.json').read_bytes()).hexdigest() == latest_sha

    with tempfile.TemporaryDirectory(prefix=f'{name}-latest22-no-proof-', dir=EVIDENCE_ROOT / 'writer') as temporary:
        root = Path(temporary)
        store = isolated_store(store_module, root)
        latest_before = seed_valid_newer_latest(root, store, contract)
        source, source_sha = load_existing_1700_source()
        no_proof_payload = domain.build_research_archive(source, source_input_sha256=source_sha)
        no_proof_payload.pop('ready_empty_evidence_v1')
        assert no_proof_payload['source_input_sha256'] == source_sha
        try:
            store.publish(no_proof_payload, slot=EMPTY_SLOT, mode='LIVE')
        except ValueError as error:
            no_proof_rejection = str(error)
        else:
            raise AssertionError(f'{name} store accepted the same empty 1700 input without proof')
        assert (root / 'research/hourly/latest.json').read_bytes() == latest_before
        assert not (root / f'research/hourly/live/{DATE}/{EMPTY_SLOT}.json').exists()
    print(f'{name}: exact 1700 READY_EMPTY published behind valid 2200 latest; latest_sha256={latest_sha}; no-proof rejected ({no_proof_rejection})')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: test_verified_empty_older_slot.py canonical|scheduler')
    verify(sys.argv[1])
