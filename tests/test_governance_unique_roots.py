from pathlib import Path
import time

import pytest

from ops import research_storage_governance as governance
from ops.research_storage_governance import unique_roots
from ops.research_storage_retention import under


def old_oracle(paths):
    roots = {Path(path) for path in paths}
    return {p for p in roots if not any(p != other and under(p, other) for other in roots)}


def test_unique_roots_exact_lexical_parent_semantics():
    cases = [[], ['/', '/a', '/a/b'], ['.', 'a', 'a/b', '../a', '../a/b'],
        ['/a/b', '/a/b', '/a/b2', '/a/c', '/a/b/../x'],
        [f'/delta/run/{i}/role/block.parquet' for i in range(100)] +
        ['/delta/run/5', '/unrelated', '/unrelated/a', 'relative/x', 'relative']]
    for paths in cases:
        assert unique_roots(paths) == old_oracle(paths)


def test_unique_roots_ten_thousand_logical_block_paths():
    paths = [f'/data/role/{i % 2}/run/stock/{i}/delta.parquet' for i in range(10000)]
    start = time.perf_counter()
    result = unique_roots(paths)
    elapsed = time.perf_counter() - start
    assert result == {Path(path) for path in paths}
    print(f'10000 distinct logical block roots: {elapsed:.6f}s')


@pytest.mark.parametrize('preserve', [False, True])
def test_abandon_task_retains_requested_billing_without_reservation(tmp_path, monkeypatch, preserve):
    accounted = tmp_path / 'run'; accounted.mkdir()
    evidence = tmp_path / 'failed' / 'checkpoint.json'; evidence.parent.mkdir()
    evidence.write_bytes(b'failed checkpoint evidence')
    policy = dict(data_root=str(tmp_path), run_root=str(accounted), governance=dict(enabled=True,
        registry_root=str(tmp_path / 'registry'), pool_id='fixture', pool_identity_verified=True))
    registry = governance.Registry(governance.configuration(policy), tmp_path)
    state = registry.read()
    row = dict(state='FAILED_RECOVERABLE', directory=str(evidence.parent), owner={'pid': 1}, token='pinned',
        reserved_bytes=1024, written_bytes=100, logical_written_bytes=105, category='ordinary',
        billing_paths=[str(evidence.parent)], error='original failure')
    state['tasks']['failed'] = row.copy()
    with registry.transaction():
        registry.save(state)

    opts = {'preserve_billing_paths': True} if preserve else {}
    with pytest.raises(governance.RetentionError, match='ABANDON_REGISTRY_DRIFT'):
        governance.abandon_task(policy, key='failed', expected_registry_sha256='stale',
            expected_token='pinned', reason='retain checkpoint', **opts)
    governance.abandon_task(policy, key='failed', expected_registry_sha256=governance.digest(registry.path),
        expected_token='pinned', reason='retain checkpoint', **opts)
    terminal = registry.read()['tasks']['failed']
    assert terminal['state'] == 'ABANDONED' and registry.remaining(terminal) == 0
    assert terminal['error'] == row['error'] and evidence.read_bytes() == b'failed checkpoint evidence'
    assert terminal['billing_paths'] == (row['billing_paths'] if preserve else [])
    assert terminal['abandonment']['released_billing_paths'] == ([] if preserve else row['billing_paths'])
    assert terminal['abandonment']['previous_sha256'] == governance.canonical(row)

    # The real ordinary admission sums retained paths, while the abandoned
    # claim contributes zero to the remaining reservations of other tasks.
    disk_usage = governance.shutil.disk_usage
    monkeypatch.setattr(governance.shutil, 'disk_usage', lambda path:
        disk_usage(path)._replace(total=200 * governance.GIB, free=150 * governance.GIB))
    with governance.admission(policy, key='next', directory=accounted, predicted=1, reuse_ready=False) as (claim, _):
        active = registry.read()['tasks']['next']
        assert active['category_baseline_bytes'] == (evidence.stat().st_size if preserve else 0)
        assert active['space']['other_remaining_bytes'] == 0
        claim.finish(error=governance.RetentionError('fixture cleanup'))
