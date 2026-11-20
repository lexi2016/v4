import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.research_workbench_formula_group_supplement import (
    PINNED_SCORE_RULES_MAP_SHA256,
    PINNED_SCORE_RULES_SHA256,
)


WORKTREE = Path(__file__).resolve().parents[1]
OVERLAYS = WORKTREE / 'docs/handoffs/formula_groups_daily_completion_20261118/overlays'
SYMBOL = '000610.SZ'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
MANIFEST = dict(path='/products/20261120.json', sha256='b' * 64)


def _write_ref(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())


def _patched_host(tmp_path):
    binding = json.loads((OVERLAYS / 'API_WORKBENCH_BINDING.json').read_text())
    source = Path(binding['source_path'])
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == binding['source_sha256']
    api_app = source.parent.parent
    if str(api_app) not in sys.path:
        sys.path.insert(0, str(api_app))
    import infrastructure
    if str(source.parent) not in infrastructure.__path__:
        infrastructure.__path__.insert(0, str(source.parent))
    candidate_root = tmp_path / 'candidate'
    target = candidate_root / 'infrastructure/research_workbench_host.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    subprocess.run(['git', 'apply', '--unidiff-zero', str(OVERLAYS / 'api-workbench.patch')],
        cwd=candidate_root, check=True, capture_output=True, text=True)
    spec = importlib.util.spec_from_file_location('candidate_research_workbench_host', target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _product():
    return dict(data_date='20261120', source_generation='e' * 64,
        source_identity=dict(input_sha256='f' * 64, selector_artifact_sha256='9' * 64,
            basis=dict(price_basis='QFQ_ASOF', volume_basis='QFQ_EVENT_VOLUME')),
        manifest=MANIFEST)


class _Source:
    def __init__(self, root, product):
        self.root = root
        self.product = product

    def _a_product_root(self):
        return self.root

    def read_a_daily_product(self, *args, **kwargs):
        return self.product


def _score_replay_fixture(tmp_path, host_module, product):
    root = tmp_path / 'score-replay'
    basis = product['source_identity']['basis']
    rules = PINNED_SCORE_RULES_SHA256
    index = dict(schema='v4.workbench.daily_score_action_index.v1', data_date='20261120',
        source_generation=product['source_generation'], input_sha256=product['source_identity']['input_sha256'],
        numeric_manifest=MANIFEST, source_selector_sha256=product['source_identity']['selector_artifact_sha256'],
        rules=rules, price_basis=basis, items={SYMBOL:dict(path='/unused',sha256='a'*64)},
        **FLAGS)
    index_ref = _write_ref(root / 'indexes/index.json', index)
    descriptor = dict(status='READY', data_date='20261120',
        source_generation=product['source_generation'], input_sha256=product['source_identity']['input_sha256'],
        numeric_manifest=MANIFEST, counts=dict(total=1), index=index_ref, **FLAGS)
    receipt = dict(schema='V4_FORMULA_GROUP_SCORE_ACTION_REPLAY_V1',
        status='PREPARED_EXACT_OWNER_REPLAY', same_rule_sha=True, descriptor=descriptor,
        statuses={SYMBOL:dict(record_status='MATERIALIZED',score_status='READY',score=4)},
        source_date='2026-11-20', source_generation=product['source_generation'],
        input_sha256=product['source_identity']['input_sha256'], numeric_manifest=MANIFEST,
        formula_group_sha256='c' * 64, score_rules=rules, price_basis=basis,
        score_rule_map_sha256=PINNED_SCORE_RULES_MAP_SHA256, **FLAGS)
    receipt_ref = _write_ref(root / 'receipts/replay.json', receipt)
    return dict(receipt=receipt_ref, artifact_root=str(root)), dict(
        status='MATERIALIZED', row=dict(hold_score=dict(kb_hold_score_status='READY',kb_hold_score=4)))


@pytest.fixture
def patched_host(tmp_path):
    return _patched_host(tmp_path)


def test_formula_replay_uses_pinned_owner_rules_when_base_index_is_absent(tmp_path, patched_host, monkeypatch):
    product = _product()
    root = tmp_path / 'daily-products'
    root.mkdir()
    (root / 'index.json').write_text(json.dumps({'score_action':{}}))
    source = _Source(root, product)
    host = patched_host.ResearchWorkbenchHost.__new__(patched_host.ResearchWorkbenchHost)
    host.source = source
    host._view = lambda *args: product
    host._observation_date = lambda _: '2026-11-23'
    host._formula_groups = lambda *args: (dict(artifact={'sha256':'d'*64}), [{'symbol':SYMBOL}])
    bound, replay_value = _score_replay_fixture(tmp_path, patched_host, product)
    host._formula_group_binding = lambda *args: {'score_action':bound}
    module = __import__('infrastructure.research_workbench_score_action', fromlist=['read_score_action'])
    monkeypatch.setattr(module, 'read_score_action', lambda *args: replay_value)

    result = host._formula_score_replay('2026-11-20', SYMBOL, product, original_descriptor=None)

    assert result == replay_value


def test_daily_score_action_uses_formula_replay_when_canonical_index_is_missing(tmp_path, patched_host,
        monkeypatch):
    product = _product()
    root = tmp_path / 'daily-products'
    root.mkdir()
    (root / 'index.json').write_text(json.dumps({'score_action':{}}))
    host = patched_host.ResearchWorkbenchHost.__new__(patched_host.ResearchWorkbenchHost)
    host.source = _Source(root, product)
    host._view = lambda *args: product
    host._observation_date = lambda _: '2026-11-23'
    host.v192_group = lambda *args: dict(status='READY', rows=[])
    host._formula_groups = lambda *args: (dict(artifact={'sha256':'d'*64}), [{'symbol':SYMBOL}])
    expected = dict(status='MATERIALIZED', row={'hold_score':{'kb_hold_score_status':'READY','kb_hold_score':4}})
    calls = []
    host._formula_score_replay = lambda *args: calls.append(args) or expected

    result = host.daily_score_action('2026-11-20', SYMBOL)

    assert result['status'] == 'MATERIALIZED'
    assert result['row'] == expected['row']
    assert len(calls) == 1 and calls[0][-1] is None


def test_existing_canonical_score_is_never_replaced_by_formula_replay(tmp_path, patched_host, monkeypatch):
    product = _product()
    root = tmp_path / 'daily-products'
    root.mkdir()
    descriptor = dict(index=dict(path='/canonical/index.json',sha256='a'*64))
    (root / 'index.json').write_text(json.dumps({'score_action':{'20261120':descriptor}}))
    host = patched_host.ResearchWorkbenchHost.__new__(patched_host.ResearchWorkbenchHost)
    host.source = _Source(root, product)
    host._view = lambda *args: product
    host._observation_date = lambda _: '2026-11-23'
    canonical = dict(status='MATERIALIZED', row={'hold_score':{'kb_hold_score':5}})
    score_module = __import__('infrastructure.research_workbench_score_action', fromlist=['read_score_action'])
    monkeypatch.setattr(score_module, 'read_score_action', lambda *args: canonical)
    host._formula_score_replay = lambda *args: pytest.fail('canonical score must be preserved')

    result = host.daily_score_action('2026-11-20', SYMBOL)

    assert result['status'] == 'MATERIALIZED'
    assert result['row'] == canonical['row']


def test_existing_v192_materialized_score_is_never_replaced_by_formula_replay(tmp_path, patched_host,
        monkeypatch):
    import types

    product = _product()
    root = tmp_path / 'daily-products'
    root.mkdir()
    (root / 'index.json').write_text(json.dumps({'score_action':{}}))
    host = patched_host.ResearchWorkbenchHost.__new__(patched_host.ResearchWorkbenchHost)
    host.source = _Source(root, product)
    host._view = lambda *args: product
    host._observation_date = lambda _: '2026-11-23'
    host.v192_group = lambda *args: dict(status='READY', source_artifact_sha256='f'*64,
        rows=[dict(symbol=SYMBOL, v192_assets={'available':True})])
    host._formula_groups = lambda *args: (dict(artifact={'sha256':'d'*64}), [{'symbol':SYMBOL}])
    v192 = dict(status='MATERIALIZED', row={'hold_score':{'kb_hold_score':6}})
    score_module = __import__('infrastructure.research_workbench_score_action', fromlist=['read_score_action'])
    monkeypatch.setattr(score_module, 'read_score_action', lambda *args: v192)
    monkeypatch.setitem(sys.modules, 'infrastructure.research_workbench_v192_assets',
        types.SimpleNamespace(load=lambda *args: dict(module=dict(artifact_root='/v192', score_action={}))))
    host._formula_score_replay = lambda *args: pytest.fail('materialized V192 score must be preserved')

    result = host.daily_score_action('2026-11-20', SYMBOL)

    assert result['status'] == 'MATERIALIZED'
    assert result['row'] == v192['row']
