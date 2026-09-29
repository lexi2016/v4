"""Shared writer durability must not replace domain-specific validators."""
import os
import stat
import pytest
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.preselection_overlay_store import PreselectionOverlayStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.interprocess_lock import owned_interprocess_lock

@pytest.mark.parametrize('store_type', [AShareReviewStore, PreselectionOverlayStore, PreselectionPoolStore])
def test_shared_writer_fsyncs_file_and_publication_directory(tmp_path, monkeypatch, store_type):
    synced = []
    original = os.fsync

    def record(fd):
        synced.append(os.fstat(fd).st_mode)
        original(fd)
    monkeypatch.setattr(os, 'fsync', record)
    store = store_type(tmp_path / 'owned')
    store._write('nested/value.json', {'source': 'fixture'})
    assert store._read('nested/value.json') == {'source': 'fixture'}
    assert any((stat.S_ISREG(mode) for mode in synced))
    assert any((stat.S_ISDIR(mode) for mode in synced))

def test_body_timeout_is_not_misreported_as_lock_acquisition_timeout(tmp_path):
    original = TimeoutError('source operation timed out')
    with pytest.raises(TimeoutError) as caught:
        with owned_interprocess_lock(tmp_path / 'lock', timeout_seconds=1, timeout_message='lock timeout'):
            raise original
    assert caught.value is original

@pytest.mark.parametrize('relative', ['C:outside', 'C:/outside', 'Z:relative/path'])
def test_shared_writer_preserves_windows_drive_rejection_on_posix(tmp_path, relative):
    from infrastructure.owned_io import OwnedIOError, SafeRoot
    with pytest.raises(OwnedIOError):
        SafeRoot(tmp_path).write_bytes(relative, b'not a valid relative artifact')
