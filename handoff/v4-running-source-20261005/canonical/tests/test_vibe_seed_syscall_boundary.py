"""M05: inject the competing directory at the libc-call boundary.

Simulated tests exercise the exact current helper with an interposed libc.
The two Darwin-only tests forward to the real renameatx_np. Skips are not PASS.
No real Vibe input/version or credential is touched; all paths are under tmp_path.
"""
import ctypes
import errno
import os
import sys
from types import SimpleNamespace

import pytest
from ops import seed_vibe_cache_version as seed

REAL_DARWIN = sys.platform == 'darwin'


def stage_pair(tmp_path):
    stage = tmp_path / 'staged-version'
    stage.mkdir()
    (stage / 'ours.json').write_text('{"synthetic":true}')
    return stage, tmp_path / 'published-version'


def test_competitor_is_inserted_at_the_syscall_boundary_not_before_helper(tmp_path, monkeypatch):
    stage, destination = stage_pair(tmp_path)
    calls = []

    def rename(srcfd, src, dstfd, dst, flags):
        assert not destination.exists()
        assert srcfd == dstfd and flags == 0x00000004
        assert src == os.fsencode(stage.name) and dst == os.fsencode(destination.name)
        os.fstat(srcfd)
        calls.append(srcfd)
        # This happens inside the libc-call seam, after the helper opened its fd.
        destination.mkdir()
        (destination / 'winner.json').write_text('competing-writer')
        ctypes.set_errno(errno.EEXIST)
        return -1

    monkeypatch.setattr(seed.sys, 'platform', 'darwin')
    monkeypatch.setattr(seed.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(renameatx_np=rename))
    assert not destination.exists()
    with pytest.raises(seed.BoundaryError, match='CACHE_SEED_DESTINATION_NOT_ABSENT'):
        seed._rename_stage_no_replace(stage, destination)
    assert len(calls) == 1
    assert (stage / 'ours.json').read_text() == '{"synthetic":true}'
    assert (destination / 'winner.json').read_text() == 'competing-writer'
    assert not (destination / 'ours.json').exists()
    with pytest.raises(OSError):
        os.fstat(calls[0])


@pytest.mark.parametrize('number,reason', [
    (errno.ENOTSUP, 'CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE'),
    (errno.EINVAL, 'CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE'),
    (errno.EIO, 'CACHE_SEED_ATOMIC_COMMIT_FAILED'),
])
def test_syscall_error_never_falls_back_to_replace(tmp_path, monkeypatch, number, reason):
    stage, destination = stage_pair(tmp_path)
    calls = []
    def rename(srcfd, src, dstfd, dst, flags):
        calls.append(flags)
        ctypes.set_errno(number)
        return -1
    def forbidden(*args, **kwargs):
        raise AssertionError('unsafe ordinary rename fallback')
    monkeypatch.setattr(seed.sys, 'platform', 'darwin')
    monkeypatch.setattr(seed.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(renameatx_np=rename))
    monkeypatch.setattr(seed.os, 'rename', forbidden)
    with pytest.raises(seed.BoundaryError, match=reason):
        seed._rename_stage_no_replace(stage, destination)
    assert calls == [0x00000004] and stage.is_dir() and not destination.exists()


def test_absent_syscall_is_fail_closed(tmp_path, monkeypatch):
    stage, destination = stage_pair(tmp_path)
    monkeypatch.setattr(seed.sys, 'platform', 'darwin')
    monkeypatch.setattr(seed.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace())
    with pytest.raises(seed.BoundaryError, match='CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE'):
        seed._rename_stage_no_replace(stage, destination)
    assert stage.is_dir() and not destination.exists()


@pytest.mark.skipif(not REAL_DARWIN, reason='real macOS renameatx_np required')
def test_real_macos_competitor_between_helper_entry_and_kernel_commit(tmp_path, monkeypatch):
    stage, destination = stage_pair(tmp_path)
    libc = ctypes.CDLL(None, use_errno=True)
    real = libc.renameatx_np
    real.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    real.restype = ctypes.c_int
    calls = []
    def interposed(*args):
        assert not destination.exists()
        destination.mkdir()
        (destination / 'winner.json').write_text('competing-writer')
        calls.append(args)
        return real(*args)
    monkeypatch.setattr(seed.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace(renameatx_np=interposed))
    with pytest.raises(seed.BoundaryError, match='CACHE_SEED_DESTINATION_NOT_ABSENT'):
        seed._rename_stage_no_replace(stage, destination)
    assert len(calls) == 1 and calls[0][-1] == 0x00000004
    assert (destination / 'winner.json').read_text() == 'competing-writer'
    assert (stage / 'ours.json').exists() and not (destination / 'ours.json').exists()


@pytest.mark.skipif(not REAL_DARWIN, reason='real macOS renameatx_np required')
def test_real_macos_atomic_commit_of_absent_destination(tmp_path):
    stage, destination = stage_pair(tmp_path)
    seed._rename_stage_no_replace(stage, destination)
    assert not stage.exists() and (destination / 'ours.json').read_text() == '{"synthetic":true}'
