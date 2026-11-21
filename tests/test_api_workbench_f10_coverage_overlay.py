import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = REPO_ROOT / 'docs/handoffs/formula_groups_daily_completion_20261118/overlays'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SOURCE_DATE = '2026-11-20'
OBSERVATION_DATE = '2026-11-23'
GENERATION = 'e' * 64
INPUT = 'f' * 64
NUMERIC = dict(path='/numeric/manifest.json', sha256='b' * 64)
SYMBOLS = ['000610.SZ', '000513.SZ']


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _candidate_host(tmp_path, monkeypatch):
    binding = json.loads((OVERLAYS / 'API_WORKBENCH_F10_COVERAGE_BINDING.json').read_text())
    source = Path(binding['source_path'])
    if not source.is_file():
        pytest.skip(f"requires exact installed API preimage fixture: {source} SHA256={binding['preimage_sha256']}")
    source_bytes = source.read_bytes()
    if _sha(source_bytes) != binding['preimage_sha256']:
        pytest.skip(f"requires exact installed API preimage fixture: {source} SHA256={binding['preimage_sha256']}")
    app_root = tmp_path / 'candidate-app'
    target = app_root / 'infrastructure/research_workbench_host.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(source_bytes)
    patch = REPO_ROOT / binding['patch_path']
    assert _sha(patch.read_bytes()) == binding['patch_sha256']
    subprocess.run([*binding['patch_apply_args'], str(patch)], cwd=app_root, check=True)
    assert _sha(target.read_bytes()) == binding['postimage_sha256']

    monkeypatch.syspath_prepend(str(REPO_ROOT))
    import infrastructure
    candidate_package_path = str(source.parent)
    if candidate_package_path not in infrastructure.__path__:
        monkeypatch.setattr(infrastructure, '__path__', [*infrastructure.__path__, candidate_package_path])
    name = 'candidate_research_workbench_host_f10_coverage_test'
    spec = importlib.util.spec_from_file_location(name, target)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module, binding


def test_exact_formula_day_http_projects_f10_coverage_identity_and_versions_refresh(tmp_path, monkeypatch):
    module, overlay = _candidate_host(tmp_path, monkeypatch)
    formula_ref = dict(path='/formula-groups/2026-11-20/latest.json', sha256='a' * 64)
    product = dict(data_date=SOURCE_DATE.replace('-', ''), source_generation=GENERATION,
        source_identity=dict(input_sha256=INPUT, selector_artifact_sha256='9' * 64),
        manifest=NUMERIC, rows=[], processed_count=len(SYMBOLS), artifact=dict(path='/product', sha256='c' * 64))
    summary = dict(schema='V4_WORKBENCH_FORMULA_GROUP_SUMMARY_V1', artifact=formula_ref,
        status='READY', group_counts=dict(b23_entry=1, pb2_confirm=1), **FLAGS)
    rows = [dict(symbol=symbol, source_row=dict(symbol=symbol)) for symbol in SYMBOLS]
    monkeypatch.setattr(module, '_formula_group_rows', lambda *args, **kwargs: (summary, rows))

    host = module.ResearchWorkbenchHost.__new__(module.ResearchWorkbenchHost)
    host.binding = dict(candidate_group_overrides={SOURCE_DATE: {'artifact': formula_ref}},
        candidate_group_formula_sha256={'b23_entry': '1' * 64, 'pb2_confirm': '2' * 64},
        observation_dates={})
    host.source = object()
    host.classifications = SimpleNamespace(root=None, version=lambda: 'classification-v1', close=lambda: None)
    host._quote_references = SimpleNamespace(read=lambda value: {'status': 'READ_ONLY', 'rows': {}})
    host._view = lambda *args, **kwargs: product
    host._observation_date = lambda day: OBSERVATION_DATE
    host._is_skill_date = lambda day: False
    host._module_reference = lambda name, day: formula_ref if name == 'formula_groups' else None
    host._observation_commit = lambda observation: None
    host._index = lambda: dict(company_materials_scoped={}, latest_date=None,
        company_materials={}, company_materials_versions={}, dates={}, attempts={}, top200={},
        score_action={}, display_names={}, f10={})
    host._v192_version = lambda day: None
    host.workflow = lambda day: {'time_contract': {'nodes': []}}
    coverage_state = {'value': None}
    host._formula_group_binding = lambda day, value=None: {
        'artifact': formula_ref,
        **({'f10_coverage': coverage_state['value']} if coverage_state['value'] is not None else {})}

    binding_file = tmp_path / 'host-binding.json'
    binding_bytes = (json.dumps(FLAGS, sort_keys=True, separators=(',', ':')) + '\n').encode()
    binding_file.write_bytes(binding_bytes)
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING', str(binding_file))
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256', _sha(binding_bytes))
    monkeypatch.setattr(module, 'ResearchWorkbenchHost', lambda source, binding: host)
    app = FastAPI()
    app.include_router(module.create_workbench_router(object()))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f'/workbench/days/{SOURCE_DATE}')
        assert response.status_code == 200
        absent = response.json()['formula_groups']['f10_coverage']
        assert absent['status'] == 'CANNOT_CONFIRM'
        assert (absent['observed'], absent['failed'], absent['remaining']) == (0, 0, len(SYMBOLS))
        assert absent['formula_group_sha256'] == formula_ref['sha256']
        assert absent['source_date'] == SOURCE_DATE
        assert absent['observation_date'] == OBSERVATION_DATE
        assert absent['generation'] == GENERATION
        assert absent['input_sha256'] == INPUT
        assert absent['numeric_manifest_sha256'] == NUMERIC['sha256']
        assert absent['roster_symbols_sha256'] == _canonical_roster_sha(SYMBOLS)
        assert absent['roster_count'] == len(SYMBOLS)
        assert 'path' not in json.dumps(absent).lower()

        coverage_state['value'] = dict(schema='V4_WORKBENCH_FORMULA_GROUP_F10_COVERAGE_V1',
            status='PARTIAL', observed=1, failed=1, remaining=0, source_date=SOURCE_DATE,
            observation_date=OBSERVATION_DATE, generation=GENERATION, input_sha256=INPUT,
            numeric_manifest_sha256=NUMERIC['sha256'], roster_symbols_sha256='d' * 64,
            roster_count=len(SYMBOLS), **FLAGS)
        partial = client.get(f'/workbench/days/{SOURCE_DATE}').json()['formula_groups']['f10_coverage']
        assert partial['status'] == 'PARTIAL'
        assert (partial['observed'], partial['failed'], partial['remaining']) == (1, 1, 0)
        assert partial['formula_group_sha256'] == formula_ref['sha256']

        # The existing versions endpoint feeds the event stream; the coverage
        # identity must therefore invalidate list/SSE consumers on a real change.
        coverage_state['value'] = None
        before = client.get(f'/workbench/days/{SOURCE_DATE}/versions').json()
        coverage_state['value'] = dict(partial, status='COMPLETE', observed=2, failed=0, remaining=0)
        after = client.get(f'/workbench/days/{SOURCE_DATE}/versions').json()
        assert before['event_id'] != after['event_id']
        assert before['modules']['list'] != after['modules']['list']
        assert overlay['preimage_sha256'] == _sha(Path(overlay['source_path']).read_bytes())

        def reject_malformed_roster(*args, **kwargs):
            raise ValueError('WORKBENCH_FORMULA_GROUP_CONTRACT_INVALID')

        monkeypatch.setattr(module, '_formula_group_rows', reject_malformed_roster)
        compatible = client.get(f'/workbench/days/{SOURCE_DATE}/versions')
        assert compatible.status_code == 200
        legacy = compatible.json()
        assert legacy['schema'] == 'V4_WORKBENCH_VERSIONS_V1'
        assert legacy['source_date'] == SOURCE_DATE
        assert legacy['observation_date'] == OBSERVATION_DATE
        assert set(legacy['modules']) >= {'catalog', 'top200', 'list', 'company', 'score_action', 'v192', 'workflow'}


def _canonical_roster_sha(symbols):
    raw = json.dumps(sorted(symbols), ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()
    return _sha(raw)
