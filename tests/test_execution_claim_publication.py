"""Isolated initial-claim publication checks; never use dispatcher state."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.execution_ledger import ExecutionLedger


ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "claims/live/20260730/1200/dispatch.claim.json"


def request() -> DispatchRequest:
    return DispatchRequest("20260730", "20260730", "20260731", "1200", DispatchMode.LIVE)


@pytest.mark.parametrize("point", ["before_write", "during_write", "before_publish"])
def test_initial_write_failure_never_leaves_partial_final(tmp_path, monkeypatch, point):
    original_fdopen = os.fdopen

    class FaultingWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.wrapped.close()

        def write(self, raw):
            if point == "during_write":
                self.wrapped.write(raw[:len(raw) // 2])
                self.wrapped.flush()
            raise OSError("injected claim write failure")

    def fdopen(fd, mode, *args, **kwargs):
        wrapped = original_fdopen(fd, mode, *args, **kwargs)
        return FaultingWriter(wrapped) if mode == "wb" and point != "before_publish" else wrapped

    def failed_write(fd, raw):
        if point == "during_write":
            original_write(fd, raw[:len(raw) // 2])
        raise OSError("injected claim write failure")

    def failed_link(*args, **kwargs):
        raise OSError("injected claim publication failure")

    original_write = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "fdopen", fdopen)
        # The old initial-claim implementation uses this unbuffered path.
        patch.setattr(os, "write", failed_write)
        if point == "before_publish":
            patch.setattr(os, "link", failed_link)
        with pytest.raises(OSError, match="injected claim"):
            ExecutionLedger(tmp_path).try_claim_dispatch(request())
    assert not (tmp_path / RELATIVE).exists()
    assert not list(tmp_path.rglob("*.tmp"))
    assert ExecutionLedger(tmp_path).try_claim_dispatch(request()).acquired


def test_short_raw_writes_finish_before_file_and_directory_fsync(tmp_path, monkeypatch):
    original_fdopen, original_fsync, original_link = os.fdopen, os.fsync, os.link
    writes = []
    events = []

    class ShortRaw(io.RawIOBase):
        def __init__(self, fd):
            super().__init__()
            self.raw = io.FileIO(fd, "wb", closefd=True)

        def writable(self):
            return True

        def fileno(self):
            return self.raw.fileno()

        def write(self, raw):
            count = self.raw.write(raw[:7])
            writes.append(count)
            return count

        def close(self):
            if not self.closed:
                super().close()
                self.raw.close()

    def fdopen(fd, mode, *args, **kwargs):
        if mode == "wb":
            return io.BufferedWriter(ShortRaw(fd))
        return original_fdopen(fd, mode, *args, **kwargs)

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            assert json.loads((tmp_path / RELATIVE).read_bytes())["pid"] == os.getpid()
            events.append("directory_fsync")
        else:
            assert not (tmp_path / RELATIVE).exists()
            events.append("file_fsync")
        return original_fsync(fd)

    def link(*args, **kwargs):
        assert events == ["file_fsync"]
        result = original_link(*args, **kwargs)
        assert json.loads((tmp_path / RELATIVE).read_bytes())["target_date"] == "20260731"
        events.append("publish")
        return result

    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "link", link)
    claim = ExecutionLedger(tmp_path).try_claim_dispatch(request())
    raw = (tmp_path / RELATIVE).read_bytes()
    assert claim.acquired
    assert len(writes) > 1 and sum(writes) == len(raw)
    assert all(0 < count <= 7 for count in writes)
    assert json.loads(raw)["run_id"] == claim.run_id
    assert events == ["file_fsync", "publish", "directory_fsync"]


WORKER = r'''
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.execution_ledger import ExecutionLedger
root, action = pathlib.Path(sys.argv[2]), sys.argv[3]
request = DispatchRequest("20260730", "20260730", "20260731", "1200", DispatchMode.LIVE)
original_fdopen, original_write, original_link = os.fdopen, os.write, os.link
class InterruptedWriter:
    def __init__(self, wrapped): self.wrapped = wrapped
    def __enter__(self): return self
    def __exit__(self, *args): self.wrapped.close()
    def write(self, raw):
        if action == "during_write":
            self.wrapped.write(raw[:len(raw)//2]); self.wrapped.flush()
        os._exit(73)
def fdopen(fd, mode, *args, **kwargs):
    wrapped = original_fdopen(fd, mode, *args, **kwargs)
    return InterruptedWriter(wrapped) if mode == "wb" else wrapped
def write(fd, raw):
    if action == "during_write": original_write(fd, raw[:len(raw)//2])
    os._exit(73)
def link(*args, **kwargs):
    if action == "before_publish": os._exit(73)
    result = original_link(*args, **kwargs)
    if action == "after_publish": os._exit(73)
    return result
if action in ("before_write", "during_write"):
    os.fdopen, os.write = fdopen, write
if action in ("before_publish", "after_publish"): os.link = link
if action == "compete":
    print("READY", flush=True)
    assert sys.stdin.readline().strip() == "GO"
claim = ExecutionLedger(root).try_claim_dispatch(request)
print(json.dumps({"acquired": claim.acquired, "run_id": claim.run_id, "pid": os.getpid()}), flush=True)
if action == "compete": assert sys.stdin.readline().strip() == "STOP"
'''


@pytest.mark.parametrize("point", ["before_write", "during_write", "before_publish", "after_publish"])
def test_process_interruption_final_is_absent_or_complete(tmp_path, point):
    process = subprocess.run(
        [sys.executable, "-c", WORKER, str(ROOT), str(tmp_path.resolve()), point],
        capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 73, process.stderr
    final = tmp_path / RELATIVE
    if point == "after_publish":
        old = json.loads(final.read_bytes())
        assert old["pid"] > 0 and old["target_date"] == "20260731"
        assert old["mode"] == "LIVE" and old["run_id"]
    else:
        assert not final.exists()
    # Abrupt interruption may leave an unpublished private temp. It must not
    # block a fresh claim, or alter the existing dead-owner recovery boundary.
    recovered = ExecutionLedger(tmp_path).try_claim_dispatch(request())
    assert recovered.acquired
    assert json.loads(final.read_bytes())["run_id"] == recovered.run_id
    if point == "after_publish":
        assert recovered.run_id != old["run_id"]
    for temporary in tmp_path.rglob("*.tmp"):
        temporary.unlink()


def test_same_key_processes_publish_one_winner_while_owner_stays_alive(tmp_path):
    processes = []

    def read_line(process):
        assert select.select([process.stdout], [], [], 10)[0], "claim worker timed out"
        return process.stdout.readline().strip()

    try:
        for _ in range(4):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", WORKER, str(ROOT), str(tmp_path.resolve()), "compete"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        for process in processes:
            assert read_line(process) == "READY"
        for process in processes:
            process.stdin.write("GO\n")
            process.stdin.flush()
        results = [json.loads(read_line(process)) for process in processes]
        assert all(process.poll() is None for process in processes)
        assert sum(result["acquired"] for result in results) == 1
        assert len({result["run_id"] for result in results}) == 1
        winner = next(result for result in results if result["acquired"])
        assert json.loads((tmp_path / RELATIVE).read_bytes())["pid"] == winner["pid"]
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    process.stdin.write("STOP\n")
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
        for process in processes:
            try:
                _, error = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=10)
                raise
            assert process.returncode == 0, error


def test_published_claim_remains_complete_after_directory_fsync_failure(tmp_path, monkeypatch):
    original_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        return original_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        with pytest.raises(OSError, match="injected directory fsync"):
            ExecutionLedger(tmp_path).try_claim_dispatch(request())
    old = json.loads((tmp_path / RELATIVE).read_bytes())
    retry = ExecutionLedger(tmp_path).try_claim_dispatch(request())
    assert not retry.acquired and retry.run_id == old["run_id"]
    assert old["pid"] == os.getpid()


def test_different_identity_cannot_replace_existing_claim(tmp_path):
    ledger = ExecutionLedger(tmp_path)
    original = ledger.try_claim_dispatch(request())
    raw = (tmp_path / RELATIVE).read_bytes()
    different = DispatchRequest("20260730", "20260730", "20260801", "1200", DispatchMode.LIVE)
    with pytest.raises(ValueError, match="execution claim identity conflict"):
        ledger.try_claim_dispatch(different)
    assert (tmp_path / RELATIVE).read_bytes() == raw
    retry = ledger.try_claim_dispatch(request())
    assert not retry.acquired and retry.run_id == original.run_id
