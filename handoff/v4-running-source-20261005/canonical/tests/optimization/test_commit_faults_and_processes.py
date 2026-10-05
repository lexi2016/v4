"""Fault injection and actual local-process contention, with bounded joins."""
from __future__ import annotations
import copy
import json
import multiprocessing
import os
import runpy
from pathlib import Path
import pytest
from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import OwnedIOError, SafeRoot
from v4.manager_research.contracts import sha256_json
from v4.manager_research.safety import assert_manager_safe_tree
from v4.manager_research.store import ManagerResearchStore, StoreConflict, StoreError
DATE = '20260908'

def _write_from_process(root, tag, start, output):
    store = ManagerResearchStore(root)
    start.wait(3)
    try:
        store.write_product({'target_trade_date': DATE, 'input_identity': 'shared-key', 'writer': tag})
        output.put('ok')
    except StoreConflict:
        output.put('conflict')

def _crash_with_owner(path, signal):
    with owned_interprocess_lock(Path(path), timeout_seconds=2, timeout_message='timeout'):
        signal.send('acquired')
        signal.close()
        # deliberately skip context-manager cleanup
        os._exit(0)

def test_two_processes_do_not_silently_overwrite(tmp_path):
    ctx = multiprocessing.get_context('fork')
    start, output = (ctx.Event(), ctx.Queue())
    processes = [ctx.Process(
        target=_write_from_process,
        args=(tmp_path, tag, start, output),
    ) for tag in ('A', 'B')]
    try:
        for process in processes:
            process.start()
        start.set()
        results = [output.get(timeout=5), output.get(timeout=5)]
        for process in processes:
            process.join(5)
            assert process.exitcode == 0
        assert sorted(results) == ['conflict', 'ok']
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(2)
        output.close()
        output.join_thread()

def test_process_death_releases_kernel_lock_and_valid_legacy_owner(tmp_path):
    ctx = multiprocessing.get_context('fork')
    receiver, sender = ctx.Pipe(duplex=False)
    path = tmp_path / 'research.lock'
    process = ctx.Process(target=_crash_with_owner, args=(str(path), sender))
    try:
        process.start()
        sender.close()
        assert receiver.poll(5)
        assert receiver.recv() == 'acquired'
        process.join(5)
        assert process.exitcode == 0
        assert path.exists()
        (tmp_path / 'research.lock.reclaim').write_text('orphan recovery marker')
        with owned_interprocess_lock(path, timeout_seconds=1, timeout_message='timeout'):
            assert json.loads(path.read_text())['pid'] == os.getpid()
        assert not path.exists()
        assert path.with_name(path.name + '.mutex').exists()
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(2)

def test_unknown_empty_legacy_owner_is_not_deleted_by_age(tmp_path):
    path = tmp_path / 'research.lock'
    path.write_bytes(b'')
    os.utime(path, (0, 0))
    with pytest.raises(ValueError, match='timeout'):
        with owned_interprocess_lock(path, timeout_seconds=0.02, timeout_message='timeout'):
            pytest.fail('undecodable legacy owner must fail closed')
    assert path.read_bytes() == b''

def _job(generation='A', attempt=1, **extra):
    return dict(
        job_id='job',
        target_trade_date=DATE,
        input_identity='key',
        generation=generation,
        attempt=attempt,
        status='QUEUED',
        **extra,
    )

def _product(tag='A'):
    return dict(target_trade_date=DATE, input_identity='key', status='READY', value=tag)

def _receipt():
    return dict(target_trade_date=DATE, input_identity='key', job_id='job', status='READY')

def test_new_attempt_rejects_late_previous_generation(tmp_path):
    store = ManagerResearchStore(tmp_path)
    old = store.admit_job(_job())
    assert store.cancel_job('job')['status'] == 'CANCELLED'
    newer = store.admit_job(_job(generation='B', attempt=2))
    with pytest.raises(StoreConflict):
        store.write_job({**old, 'status': 'RUNNING'})
    with pytest.raises(StoreConflict):
        store.commit_result({**old, 'status': 'READY'}, _product(), _receipt())
    assert store.read_job('job') == newer
    assert store.read_product(DATE, 'key') is None

def test_cancel_at_last_receipt_boundary_wins_before_publication(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path)
    job = store.admit_job(_job())
    original = store.write_receipt

    def cancel_then_mirror(*args):
        assert store.cancel_job('job')['status'] == 'CANCELLED'
        return original(*args)
    monkeypatch.setattr(store, 'write_receipt', cancel_then_mirror)
    with pytest.raises(StoreConflict):
        store.commit_result({**job, 'status': 'READY'}, _product(), _receipt())
    assert store.read_product(DATE, 'key') is None
    assert store.read_job('job')['status'] == 'CANCELLED'
    assert store.read_receipt(DATE, 'job') is None

def test_publish_failure_preserves_previous_complete_result(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path)
    old = store.admit_job(_job())
    store.commit_result({**old, 'status': 'READY'}, _product('old'), _receipt())
    new = store.admit_job(_job(generation='B', attempt=2))
    original = store._write_atomic

    def fail_commit(path, value):
        if path.parent.parent.name == '.commits':
            raise OSError('injected atomic publication failure')
        return original(path, value)
    monkeypatch.setattr(store, '_write_atomic', fail_commit)
    with pytest.raises(OSError):
        store.commit_result({**new, 'status': 'READY'}, _product('new'), _receipt())
    assert store.read_product(DATE, 'key')['value'] == 'old'
    assert store.read_job('job')['status'] == 'QUEUED'
    assert store.read_receipt(DATE, 'job') is None

def test_commit_checksum_detects_torn_or_tampered_content(tmp_path):
    store = ManagerResearchStore(tmp_path)
    job = store.admit_job(_job())
    store.commit_result({**job, 'status': 'READY'}, _product(), _receipt())
    path = store._commit_path(DATE, 'key')
    value = json.loads(path.read_text())
    value['product']['value'] = 'tampered'
    path.write_text(json.dumps(value))
    with pytest.raises(StoreError, match='INTEGRITY'):
        store.read_product(DATE, 'key')

def test_complete_bundle_does_not_depend_on_receipt_mirror(tmp_path):
    store = ManagerResearchStore(tmp_path)
    job = store.admit_job(_job())
    store.commit_result({**job, 'status': 'READY'}, _product(), _receipt())
    store._receipt_path(DATE, 'job').unlink()
    assert store.read_receipt(DATE, 'job') == _receipt()
    # publication won; do not lie about cancellation
    assert store.cancel_job('job')['status'] == 'READY'

def test_job_id_cannot_be_rebound_to_another_exact_input(tmp_path):
    store = ManagerResearchStore(tmp_path)
    job = store.admit_job(_job())
    with pytest.raises(StoreConflict):
        store.write_job({**job, 'input_identity': 'different', 'status': 'RUNNING'})
    assert store.read_job('job')['input_identity'] == 'key'

def test_research_label_projection_cannot_hide_colliding_nested_payload():
    value = {
        'schema_version': 'v4.manager_research.recommendation.v1',
        'execution_scope': 'RESEARCH_ONLY',
        'research_label': {'orders_sent': True},
        'action': 'BUY',
    }
    with pytest.raises(ValueError):
        assert_manager_safe_tree(value)

def test_safe_root_detects_root_replacement(tmp_path):
    root = tmp_path / 'root'
    io = SafeRoot(root)
    io.write_bytes('a', b'old')
    root.rename(tmp_path / 'previous')
    root.mkdir()
    with pytest.raises(OwnedIOError, match='REPLACED'):
        io.write_bytes('b', b'new')
    assert not (root / 'b').exists()

def test_safe_root_refuses_leaf_symlink_and_parent_traversal(tmp_path):
    io = SafeRoot(tmp_path / 'root')
    io.ensure_directory()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'untouched')
    (tmp_path / 'root' / 'leaf').symlink_to(outside)
    with pytest.raises((OwnedIOError, OSError)):
        io.write_bytes('leaf', b'bad')
    with pytest.raises(OwnedIOError):
        io.write_bytes('../outside', b'bad')
    assert outside.read_bytes() == b'untouched'
