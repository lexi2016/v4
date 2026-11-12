"""Regression for committed QFQ results exceeding registry metadata budget."""
from contextlib import contextmanager, nullcontext
import copy
import hashlib
import json
from pathlib import Path

import pytest
from ops import research_storage_governance as g
from ops.research_storage_retention import FLAGS


def owner_result(tmp_path):
    run = tmp_path / 'qfq_test'
    run.mkdir()
    candidates = {}
    hashes = {}
    for role in ('selector', 'backtest'):
        path = tmp_path / (role + '.parquet')
        path.write_bytes(role.encode())
        candidates[role] = str(path)
        hashes[role] = g.digest(path)
    candidate = dict(status='CANDIDATE_READY', target_date=20261111,
        generation_id='a' * 64, run_dir=str(run), candidates=candidates,
        candidate_sha256=hashes,
        dependency_classifications={f'{i:06}.SZ': 'APPEND_ONLY_UNCHANGED_PREFIX' for i in range(5775)},
        **FLAGS)
    (run / 'candidate_receipt.json').write_text(json.dumps(candidate))
    result = dict(candidate, status='READY', selector=candidates['selector'],
        backtest=candidates['backtest'], selector_pointer_ready=True, backtest_pointer_ready=True)
    (run / 'stage_status.json').write_text(json.dumps(result))
    return result


def claim_fixture(tmp_path, monkeypatch):
    directory = tmp_path / 'output'
    directory.mkdir()
    config = g.configuration(dict(data_root=str(tmp_path), run_root=str(directory),
        governance=dict(enabled=True, pool_id='test', pool_identity_verified=True,
                        registry_root=str(tmp_path / 'registry'))))
    # Resource admission itself is unchanged and outside this regression.
    monkeypatch.setattr(g.Registry, 'space', lambda *args, **kwargs: {'fixture': True})
    registry = g.Registry(config, tmp_path)
    claim = g.Claim(registry, 'test-key', directory, 1024, category='debug')
    claim.begin(reuse_ready=False)
    return registry, claim


def test_5775_complete_result_red_then_compact_ready(tmp_path, monkeypatch):
    result = owner_result(tmp_path)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    before = registry.path.read_bytes()
    receipts = {name: (Path(result['run_dir']) / name).read_bytes()
                for name in ('candidate_receipt.json', 'stage_status.json')}
    assert len(json.dumps(result)) > 128 * 1024
    with pytest.raises(g.RetentionError, match='RESULT_METADATA_BUDGET'):
        claim.finish(result, result['candidates'].values())
    assert registry.path.read_bytes() == before
    summary = g.qfq_registry_summary(result)
    assert len(json.dumps(summary)) < 8192
    assert 'dependency_classifications' not in summary
    for field, name in [('complete_owner_receipt', 'candidate_receipt.json'),
                        ('ready_owner_receipt', 'stage_status.json')]:
        assert summary[field]['sha256'] == hashlib.sha256(receipts[name]).hexdigest()
        assert Path(summary[field]['path']).read_bytes() == receipts[name]
    claim.finish(summary, result['candidates'].values())
    row = registry.read()['tasks']['test-key']
    assert row['state'] == 'READY' and row['reserved_bytes'] == 0
    assert row['result'] == summary and len(row['artifacts']) == 2
    g.validate_artifacts(row['artifacts'])
    assert len(result['dependency_classifications']) == 5775


@pytest.mark.parametrize('drift', ['generation_id', 'candidate_sha256', 'candidates', 'target_date',
                                  'status', 'selector_pointer_ready', 'orders_sent'])
def test_completion_conflict_retains_original_claim(tmp_path, monkeypatch, drift):
    result = owner_result(tmp_path)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    before = registry.path.read_bytes()
    path = Path(result['run_dir']) / 'stage_status.json'
    document = json.loads(path.read_bytes())
    document[drift] = 'CHANGED'
    path.write_text(json.dumps(document))
    with pytest.raises(g.RetentionError, match='QFQ_OWNER_RECEIPT'):
        g.qfq_registry_summary(result)
    assert registry.path.read_bytes() == before
    assert registry.read()['tasks']['test-key']['state'] == 'RUNNING'


def test_original_failure_still_retains_reservation(tmp_path, monkeypatch):
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    claim.finish(error=g.RetentionError('SOURCE_BINDING_FAILED'))
    row = registry.read()['tasks']['test-key']
    assert row['state'] == 'FAILED_RECOVERABLE'
    assert row['reserved_bytes'] == 1024 and row['error'] == 'SOURCE_BINDING_FAILED'
    assert 'result' not in row


@pytest.mark.parametrize('drift', [False, True])
def test_original_governed_call_returns_full_owner_result(tmp_path, monkeypatch, drift):
    from ops import research_panel_qfq as q
    result = owner_result(tmp_path)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    if drift:
        path = Path(result['run_dir']) / 'candidate_receipt.json'
        document = json.loads(path.read_bytes()); document['generation_id'] = 'wrong'
        path.write_text(json.dumps(document))
    before = registry.path.read_bytes()
    @contextmanager
    def admitted(*args, **kwargs):
        yield claim, None
    monkeypatch.setattr(g, 'admission', admitted)
    monkeypatch.setattr(g, 'qfq_invocation_key', lambda *a, **kw: 'test-key')
    monkeypatch.setattr(g, 'qfq_write_seams', lambda *a: nullcontext())
    monkeypatch.setattr(g, 'input_write_seams', lambda *a: nullcontext())
    returned = g.governed_qfq(lambda **kw: result, {}, {'predicted_bytes': 1024},
        data_root=tmp_path, return_root=tmp_path / 'output', pointers={}, target=20261111)
    assert returned is result and len(returned['dependency_classifications']) == 5775
    row = registry.read()['tasks']['test-key']
    if drift:
        assert returned['status'] == 'READY'  # already committed owner data
        assert returned['storage_governance']['status'] == 'COMMITTED_REGISTRY_RECORDING_BLOCKED'
        assert claim.recording_failed and registry.path.read_bytes() == before
    else:
        assert row['state'] == 'READY' and row['result']['complete_owner_receipt']


def idempotent_result(tmp_path):
    full = owner_result(tmp_path)
    for name in ('candidate_receipt.json', 'stage_status.json'):
        path = Path(full['run_dir']) / name
        document = json.loads(path.read_bytes()); document['input_sha256'] = 'b' * 64
        path.write_text(json.dumps(document))
    keys = ('status', 'target_date', 'run_dir', 'selector', 'backtest',
            'selector_pointer_ready', 'backtest_pointer_ready', *FLAGS)
    return dict({key: full[key] for key in keys}, already_current=True,
        authority=dict(final_status='PASS_QFQ_FULL_HISTORY_IDEMPOTENT',
                       generation_id=full['generation_id'], source_sha256='b' * 64))


def test_actual_idempotent_owner_shape_compacts_without_fabricating_result(tmp_path, monkeypatch):
    result = idempotent_result(tmp_path)
    original = copy.deepcopy(result)
    registry, claim = claim_fixture(tmp_path, monkeypatch)
    summary = g.qfq_registry_summary(result)
    assert summary['generation_id'] == 'a' * 64
    assert len(summary['candidate_sha256']) == 2
    assert result == original and 'generation_id' not in result
    claim.finish(summary, [result['selector'], result['backtest']])
    assert registry.read()['tasks']['test-key']['state'] == 'READY'


@pytest.mark.parametrize('drift', ['generation_id', 'source_sha256', 'final_status',
                                  'selector', 'target_date', 'candidate_sha256', 'marker'])
def test_idempotent_caller_claims_cannot_override_owner_receipts(tmp_path, drift):
    result = idempotent_result(tmp_path)
    if drift in ('generation_id', 'source_sha256', 'final_status'):
        result['authority'][drift] = 'wrong'
    elif drift == 'marker':
        result['already_current'] = False
    else:
        result[drift] = 'wrong'
    with pytest.raises(g.RetentionError, match='QFQ_OWNER_'):
        g.qfq_registry_summary(result)
