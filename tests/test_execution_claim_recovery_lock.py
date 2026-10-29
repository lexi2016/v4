"""Claim recovery mutex checks with real, task-owned child processes."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import execution_ledger as module
from infrastructure.scheduling.execution_ledger import ExecutionLedger


ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "claims/live/20260730/1200/dispatch.claim.json"
LOCK_NAME = ".dispatch.claim.json.reclaim.lock"


def request():
    return DispatchRequest("20260730", "20260730", "20260731", "1200", DispatchMode.LIVE)


WORKER = r'''
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import execution_ledger as module
root, action = pathlib.Path(sys.argv[2]), sys.argv[3]
request = DispatchRequest("20260730", "20260730", "20260731", "1200", DispatchMode.LIVE)
if action == "crash_reclaimer":
    original_read = module._read_existing_claim
    reads = 0
    def read(path):
        global reads
        reads += 1
        if reads == 2:
            lock = path.with_name("." + path.name + ".reclaim.lock")
            meta = lock.stat()
            print(json.dumps({"event": "LOCKED", "inode": [meta.st_dev, meta.st_ino]}), flush=True)
            assert sys.stdin.readline().strip() == "CRASH"
            os._exit(73)
        return original_read(path)
    module._read_existing_claim = read
if action == "compete":
    print("READY", flush=True)
    assert sys.stdin.readline().strip() == "GO"
claim = module.ExecutionLedger(root).try_claim_dispatch(request)
print(json.dumps({"acquired": claim.acquired, "run_id": claim.run_id, "pid": os.getpid()}), flush=True)
if action == "compete":
    assert sys.stdin.readline().strip() == "STOP"
'''


def command(root, action):
    return [sys.executable, "-c", WORKER, str(ROOT), str(root.resolve()), action]


def read_line(process):
    assert select.select([process.stdout], [], [], 10)[0], "recovery worker timed out"
    result = process.stdout.readline().strip()
    assert result, "recovery worker closed its output"
    return result


def start(root, action):
    return subprocess.Popen(
        command(root, action), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )


def send(process, message):
    process.stdin.write(message + "\n")
    process.stdin.flush()


def finish(process, *, expected=0):
    try:
        output, error = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=10)
        raise
    assert process.returncode == expected, (output, error)


def seed_dead_claim(root):
    result = subprocess.run(command(root, "seed"), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    claim = json.loads((root / RELATIVE).read_bytes())
    assert json.loads(result.stdout)["acquired"]
    assert not module._pid_is_alive(claim["pid"])
    return claim


def inode(path):
    meta = path.stat()
    return [meta.st_dev, meta.st_ino]


def test_abrupt_reclaimer_death_releases_mutex_without_replacing_inode(tmp_path):
    old = seed_dead_claim(tmp_path)
    final = tmp_path / RELATIVE
    lock = final.with_name(LOCK_NAME)
    reclaimer = start(tmp_path, "crash_reclaimer")
    try:
        held = json.loads(read_line(reclaimer))
        assert held["event"] == "LOCKED"
        before = final.read_bytes()
        blocked = ExecutionLedger(tmp_path).try_claim_dispatch(request())
        assert not blocked.acquired and blocked.run_id == old["run_id"]
        assert final.read_bytes() == before
        assert reclaimer.poll() is None
        send(reclaimer, "CRASH")
        finish(reclaimer, expected=73)
        assert inode(lock) == held["inode"]
        assert lock.read_bytes() == b""
        recovered = ExecutionLedger(tmp_path).try_claim_dispatch(request())
        assert recovered.acquired
        assert json.loads(final.read_bytes())["run_id"] == recovered.run_id
        assert recovered.run_id != old["run_id"]
        assert inode(lock) == held["inode"]
        assert not ExecutionLedger(tmp_path).try_claim_dispatch(request()).acquired
        assert inode(lock) == held["inode"]
    finally:
        if reclaimer.poll() is None:
            send(reclaimer, "CRASH")
            finish(reclaimer, expected=73)


def test_two_recoverers_share_stable_legacy_empty_marker_and_one_winner(tmp_path):
    seed_dead_claim(tmp_path)
    final = tmp_path / RELATIVE
    lock = final.with_name(LOCK_NAME)
    # A residual marker from a fully exited legacy O_EXCL consumer. This
    # fixture never claims compatibility with an overlapping legacy reclaimer.
    lock.write_bytes(b"")
    original_inode = inode(lock)
    processes = []
    try:
        for _ in range(2):
            processes.append(start(tmp_path, "compete"))
        for process in processes:
            assert read_line(process) == "READY"
        for process in processes:
            send(process, "GO")
        results = [json.loads(read_line(process)) for process in processes]
        assert all(process.poll() is None for process in processes)
        assert sum(result["acquired"] for result in results) == 1
        winner = next(result for result in results if result["acquired"])
        current = json.loads(final.read_bytes())
        assert current["run_id"] == winner["run_id"] and current["pid"] == winner["pid"]
        assert inode(lock) == original_inode
        assert not ExecutionLedger(tmp_path).try_claim_dispatch(request()).acquired
        assert inode(lock) == original_inode
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    send(process, "STOP")
                except BrokenPipeError:
                    pass
        for process in processes:
            finish(process)


def test_live_owner_is_not_reclaimed(tmp_path):
    ledger = ExecutionLedger(tmp_path)
    first = ledger.try_claim_dispatch(request())
    before = (tmp_path / RELATIVE).read_bytes()
    retry = ledger.try_claim_dispatch(request())
    assert not retry.acquired and retry.run_id == first.run_id
    assert (tmp_path / RELATIVE).read_bytes() == before


@pytest.mark.parametrize("error_number", [errno.EPERM, errno.EIO])
def test_unknown_process_liveness_is_not_proof_of_death(tmp_path, monkeypatch, error_number):
    old = seed_dead_claim(tmp_path)
    original_kill = os.kill

    def uncertain_kill(pid, signal):
        if pid == old["pid"] and signal == 0:
            raise OSError(error_number, "injected uncertain process inspection")
        return original_kill(pid, signal)

    before = (tmp_path / RELATIVE).read_bytes()
    monkeypatch.setattr(os, "kill", uncertain_kill)
    retry = ExecutionLedger(tmp_path).try_claim_dispatch(request())
    assert not retry.acquired and retry.run_id == old["run_id"]
    assert (tmp_path / RELATIVE).read_bytes() == before


@pytest.mark.parametrize("successor_alive", [False, True])
def test_stale_observation_cannot_replace_successor(tmp_path, successor_alive):
    observed = seed_dead_claim(tmp_path)
    destination = tmp_path / RELATIVE
    successor = dict(observed, run_id="successor", pid=os.getpid() if successor_alive else observed["pid"])
    raw = json.dumps(successor, sort_keys=True).encode()
    destination.write_bytes(raw)
    replacement = json.dumps(dict(observed, run_id="stale-reclaimer", pid=os.getpid())).encode()
    assert not ExecutionLedger(tmp_path)._replace_dead_claim(destination, observed=observed, encoded=replacement)
    assert destination.read_bytes() == raw


def test_completed_dead_owner_claim_is_not_reclaimed(tmp_path):
    claim = seed_dead_claim(tmp_path)
    receipt = {field: claim[field] for field in ("run_id", "business_date", "slot", "mode")}
    receipt.update(status="SUCCEEDED", production_allowed=False, buy_gate_updated=False, orders_sent=False)
    receipt["ledger_sha256"] = module._ledger_digest(receipt)
    receipt_path = tmp_path / f'receipts/live/20260730/1200/{claim["run_id"]}.dispatch-receipt.json'
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt))
    before = (tmp_path / RELATIVE).read_bytes()
    retry = ExecutionLedger(tmp_path).try_claim_dispatch(request())
    assert not retry.acquired and retry.run_id == claim["run_id"]
    assert (tmp_path / RELATIVE).read_bytes() == before
