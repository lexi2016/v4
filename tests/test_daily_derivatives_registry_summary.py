"""Large daily owner receipts retain detail without overflowing task metadata."""
from contextlib import contextmanager, nullcontext
import copy
import json
from pathlib import Path
import sys
import types

import pytest
from ops import research_storage_governance as g
from ops.research_storage_retention import FLAGS


def write_ref(path, value):
    path.write_text(json.dumps(value))
    return dict(path=str(path), sha256=g.digest(path))


def owner_result(tmp_path):
    numeric = dict(path=str(tmp_path / 'numeric.json'), sha256='a' * 64)
    top = dict(schema='V4_A_SHARE_TOP200_V1', data_date='20261111',
               source_generation='b' * 64, numeric_manifest=numeric, top200_count=200, **FLAGS)
    top_ref = write_ref(tmp_path / 'top200.json', top)
    index = tmp_path / 'index.json'
    write_ref(index, dict(dates={'20261111': numeric}, top200={'20261111': top_ref}))
    result = dict(schema='V4_A_DAILY_DERIVATIVES_V1', status='COMPLETE_DESCRIPTIVE_NONPIT',
        completeness_scope='CURRENT_DAY_DERIVATIVES', data_date='20261111', source_generation='b' * 64,
        completed_source_provenance=dict(numeric_manifest=numeric),
        history_status='PARTIAL_NEEDS_EXPLICIT_BOOTSTRAP', historical_completion=False,
        history_bootstrap_in_daily_path=False,
        history=dict(candidate_count=426, complete_stocks=108, incomplete_stocks=318,
                     missing_label_date_count=947908,
                     incomplete=[dict(symbol=f'{i:06}.SZ', missing='x' * 1000) for i in range(318)]),
        top200=dict(status='PUBLISHED_TOP200', index=dict(path=str(index), sha256='old-CAS-hash'),
                    before=dict(index={'prior-evidence': 'retained'})), **FLAGS)
    result['attempt'] = write_ref(tmp_path / 'attempt.json', result)
    f10 = dict(schema='v4.a_share.f10_daily_receipt.v1', status='PARTIAL',
        data_date='20261111', source_generation='b' * 64, upstream_success_receipt=result['attempt'],
        requested=5809, observed=4619, failures=list(range(1190)), remaining=[], **FLAGS)
    result['f10'] = dict(status='PARTIAL', receipt=write_ref(tmp_path / 'f10.json', f10),
                         requested=5809, observed=4619, failure_count=1190, remaining_count=0)
    return result


def claim_fixture(tmp_path, monkeypatch):
    config = g.configuration(dict(data_root=str(tmp_path), run_root=str(tmp_path),
        governance=dict(enabled=True, pool_id='test', pool_identity_verified=True,
                        registry_root=str(tmp_path / 'registry'))))
    monkeypatch.setattr(g.Registry, 'space', lambda *a, **kw: {'fixture': True})
    registry = g.Registry(config, tmp_path)
    claim = g.Claim(registry, 'test-key', tmp_path, 1024, category='debug')
    claim.begin(reuse_ready=False)
    return registry, claim


def test_large_owner_result_red_then_bounded_finish(tmp_path, monkeypatch):
    result = owner_result(tmp_path)
    original = copy.deepcopy(result)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    with pytest.raises(g.RetentionError, match='RESULT_METADATA_BUDGET'):
        claim.finish(result, [tmp_path / 'index.json'])
    assert registry.read()['tasks']['test-key']['state'] == 'RUNNING'
    summary = g.daily_derivatives_registry_summary(result)
    assert len(json.dumps(summary)) < 8192
    claim.finish(summary, [tmp_path / 'index.json'])
    row = registry.read()['tasks']['test-key']
    assert row['state'] == 'READY' and claim.finalized and row['reserved_bytes'] == 0
    assert result == original and len(result['history']['incomplete']) == 318
    assert summary['history']['missing_label_date_count'] == 947908
    assert summary['history_status'] == 'PARTIAL_NEEDS_EXPLICIT_BOOTSTRAP'
    assert summary['historical_completion'] is False
    assert summary['f10']['status'] == 'PARTIAL' and summary['f10']['failure_count'] == 1190
    assert json.loads(Path(summary['complete_owner_receipt']['path']).read_bytes())['history'] == result['history']


@pytest.mark.parametrize('drift', ['attempt_sha', 'history_status', 'top200_sha', 'top200_date',
                                   'f10_upstream', 'f10_status', 'f10_count'])
def test_conflicts_never_record_ready(tmp_path, monkeypatch, drift):
    result = owner_result(tmp_path)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    if drift == 'attempt_sha':
        result['attempt']['sha256'] = '0' * 64
    elif drift == 'history_status':
        result['history_status'] = 'COMPLETE'
    elif drift.startswith('top200'):
        index = json.loads((tmp_path / 'index.json').read_bytes())
        if drift == 'top200_sha':
            index['top200']['20261111']['sha256'] = '0' * 64
        else:
            top = json.loads((tmp_path / 'top200.json').read_bytes()); top['data_date'] = '20261110'
            index['top200']['20261111'] = write_ref(tmp_path / 'top200.json', top)
        write_ref(tmp_path / 'index.json', index)
    elif drift == 'f10_count':
        result['f10']['observed'] = 5809
    else:
        f10 = json.loads((tmp_path / 'f10.json').read_bytes())
        f10['upstream_success_receipt' if drift == 'f10_upstream' else 'status'] = 'WRONG'
        result['f10']['receipt'] = write_ref(tmp_path / 'f10.json', f10)
    with pytest.raises(g.RetentionError, match='DERIVATIVES_'):
        g.daily_derivatives_registry_summary(result)
    assert registry.read()['tasks']['test-key']['state'] == 'RUNNING'


def governed_fixture(tmp_path, monkeypatch, result):
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    owner = types.ModuleType('ops.research_panel_daily_product')
    owner.__file__ = g.__file__
    owner.SourceContext = lambda *a: types.SimpleNamespace(root=tmp_path, scope={'000001.SZ'},
                                                          identity={}, config_ref={})
    for name in ('ops.research_panel_daily_product', 'ops.research_daily_product_parallel',
                 'ops.render_original_formula_projection'):
        monkeypatch.setitem(sys.modules, name, owner)
    monkeypatch.setattr(g, 'configured_policy', lambda: dict(data_root=str(tmp_path),
        governance=dict(product_peak_bytes=1024)))
    monkeypatch.setattr(g, 'configuration', lambda p: dict(product_output_roots=[str(tmp_path)]))
    monkeypatch.setattr(g, 'product_write_seams', lambda *a: nullcontext())
    @contextmanager
    def admission(*a, **kw):
        assert kw['reuse_ready'] is False
        yield claim, None
    monkeypatch.setattr(g, 'admission', admission)
    returned = g._governed_product(lambda *a, **kw: result, data_root=tmp_path, target=20261111,
                                    output_root=tmp_path)
    return returned, registry.read()['tasks']['test-key']


def test_original_full_return_and_partial_preserved(tmp_path, monkeypatch):
    result = owner_result(tmp_path); original = copy.deepcopy(result)
    returned, row = governed_fixture(tmp_path, monkeypatch, result)
    assert returned is result and returned == original
    assert row['state'] == 'READY' and row['result']['f10']['status'] == 'PARTIAL'


@pytest.mark.parametrize('status', ['FAILED', 'CANNOT_CONFIRM'])
def test_failed_business_not_ready(tmp_path, monkeypatch, status):
    (tmp_path / 'index.json').write_text('{}')
    result = dict(schema='V4_A_DAILY_DERIVATIVES_V1', status=status)
    returned, row = governed_fixture(tmp_path, monkeypatch, result)
    assert returned is result and row['state'] == 'FAILED_RECOVERABLE'
    assert row['error'] == 'PRODUCT_PARTIAL_RETAINED' and 'result' not in row


def test_ordinary_product_path_unchanged(tmp_path, monkeypatch):
    (tmp_path / 'index.json').write_text('{}')
    result = dict(schema='ordinary', status='PARTIAL', detail=['not', 'summarized'])
    returned, row = governed_fixture(tmp_path, monkeypatch, result)
    assert returned is result and row['result'] == result and row['state'] == 'READY'
