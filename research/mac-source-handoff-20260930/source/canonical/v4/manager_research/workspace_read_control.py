"""Bounded reads and pure projection memoization inside the existing owner.

No persistent cache, worker pool, producer, network client or scheduler. Owner
reads/validators always run before memoization; raw sources are never memoized.
Cancellation is cooperative BETWEEN owner calls, not thread preemption.
"""
from __future__ import annotations
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
from threading import Event, RLock
import time
from typing import Any, Callable, Iterator

READ_CONTRACT = '20260923.workspace-history-read.r1'
_LOG = logging.getLogger(__name__)

class WorkspaceReadError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

@dataclass
class ReadTrace:
    date: str
    mode: str
    deadline: float
    alive: Callable[[], bool] = lambda: True
    started: float = field(default_factory=time.monotonic)
    stages: dict[str, dict] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def check(self) -> None:
        if not self.alive():
            raise WorkspaceReadError('WORKSPACE_READ_CANCELLED')
        if time.monotonic() >= self.deadline:
            raise WorkspaceReadError('WORKSPACE_READ_TIMEOUT')

    def result(self, outcome: str = 'RETURNED') -> dict:
        return dict(contract=READ_CONTRACT, target_trade_date=self.date, mode=self.mode,
            elapsed_ms=round((time.monotonic()-self.started)*1000, 3),
            stages=self.stages, counts=self.counts, outcome=outcome,
            cancellation='COOPERATIVE_BETWEEN_OWNER_CALLS_NOT_THREAD_PREEMPTION')

_TRACE: ContextVar[ReadTrace | None] = ContextVar('manager_workspace_read_trace', default=None)

def checkpoint() -> None:
    trace = _TRACE.get()
    if trace:
        trace.check()

def count(name: str, amount: int = 1) -> None:
    trace = _TRACE.get()
    if trace:
        trace.counts[name] = trace.counts.get(name, 0) + amount

@contextmanager
def phase(name: str) -> Iterator[None]:
    checkpoint()
    trace = _TRACE.get()
    start = time.monotonic()
    try:
        yield
    finally:
        if trace:
            item = trace.stages.setdefault(name, dict(calls=0, elapsed_ms=0.0))
            item['calls'] += 1
            item['elapsed_ms'] = round(item['elapsed_ms']+(time.monotonic()-start)*1000, 3)
    checkpoint()


def contract_identity() -> str:
    """On-disk reader/semantic/calendar identity; a change requires revalidation.

    This is NOT an assertion that edited source has been reloaded by a process.
    Deployment still needs its original restart/independent-review procedure.
    """
    package = Path(__file__).parent
    root = package.parents[1]
    # Explicit source dependencies, not an unbounded scan of the host project.
    # Missing conditional modules are represented as MISSING: their appearance
    # invalidates old memo keys/plans. Their original owner gates still decide
    # admission; a fingerprint does not make missing dependencies usable.
    dependencies = (
        'stage_center/scheduler.py','stage_center/contracts.py','stage_center/calendar.py',
        'stage_center/candidate_input.py','contracts/stages.py',
        'contracts/us_equity_calendar.py','contracts/us_equity_calendar_2026.json',
        'domains/manager_condition_evidence.py', 'domains/manager_close_rebound.py',
        'domains/manager_catalyst_tracking.py', 'domains/manager_research_evidence.py',
        'contracts/trading_calendar.py', 'contracts/market_calendar_2026.json',
        'contracts/research.py', 'contracts/research_day_product.py',
        'infrastructure/owned_io.py', 'infrastructure/owned_path.py',
        'infrastructure/interprocess_lock.py', 'infrastructure/trading_safety.py',
        'infrastructure/data_store.py', 'infrastructure/research_store.py',
        'infrastructure/research_lane_source.py', 'infrastructure/manager_input_attestation.py',
        'infrastructure/hkconnect_close_store.py',
        'upstreams/v3_shared_data/shared_data/hk_security_master.py',
        'upstreams/v3_shared_data/shared_data/hashing.py',
        'upstreams/v3_shared_data/shared_data/paths.py',
        'upstreams/v3_shared_data/shared_data/store.py',
        'v4/manager_research/DEPENDENCY_MANIFEST.json',
    )
    paths = [*sorted(package.glob('*.py')), *(root/name for name in dependencies)]
    if len(paths) > 128:
        raise WorkspaceReadError('WORKSPACE_READER_CONTRACT_BOUND_EXCEEDED')
    sha = hashlib.sha256(READ_CONTRACT.encode())
    total = 0
    for path in paths:
        sha.update(str(path.relative_to(root)).encode()+b'\0')
        try:
            with path.open('rb') as handle:
                raw = handle.read(8*1024*1024+1)
        except FileNotFoundError:
            sha.update(b'MISSING\0')
            continue
        total += len(raw)
        if len(raw) > 8*1024*1024 or total > 64*1024*1024:
            raise WorkspaceReadError('WORKSPACE_READER_CONTRACT_BYTES_BOUND_EXCEEDED')
        sha.update(hashlib.sha256(raw).digest())
    return sha.hexdigest()


class ProjectionMemo:
    """Full VERIFIED input key; 4 entries / 16 MiB / 30 s, in this process only."""
    def __init__(self, *, capacity: int = 4, max_bytes: int = 16*1024*1024, ttl: float = 30.0):
        self.capacity, self.max_bytes, self.ttl = capacity, max_bytes, ttl
        self._values: OrderedDict[str, tuple[float, int, Any]] = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    def compute(self, name: str, inputs: Any, function: Callable[[], Any]) -> Any:
        from .workspace_projection import digest
        # Never invoke this until the originating owner validated the inputs.
        key = digest([READ_CONTRACT, contract_identity(), name, inputs])
        with self._lock:
            now = time.monotonic()
            for old, item in list(self._values.items()):
                if now-item[0] >= self.ttl:
                    self._bytes -= self._values.pop(old)[1]
            item = self._values.get(key)
            if item:
                self._values.move_to_end(key)
                count('pure_projection_memo_hit')
                return deepcopy(item[2])
        count('pure_projection_memo_miss')
        value = function()  # exception is never cached
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()
        if len(raw) <= self.max_bytes and self.capacity > 0:
            with self._lock:
                old = self._values.pop(key, None)
                if old:
                    self._bytes -= old[1]
                while self._values and (len(self._values) >= self.capacity or self._bytes+len(raw) > self.max_bytes):
                    _, old = self._values.popitem(last=False)
                    self._bytes -= old[1]
                self._values[key] = (time.monotonic(), len(raw), deepcopy(value))
                self._bytes += len(raw)
        return value


def project(service: Any, name: str, inputs: Any, function: Callable[[], Any]) -> Any:
    memo = getattr(service, '_workspace_projection_memo', None)
    return memo.compute(name, inputs, function) if memo is not None else function()

@dataclass
class _Flight:
    clients: list[Event] = field(default_factory=list)
    done: Event = field(default_factory=Event)
    value: Any = None
    error: BaseException | None = None

class ReadCoordinator:
    """In-flight only: no TTL result reuse before source validation.

    Per service/process: two different keys, eight subscribers per key. A
    cancelled subscriber cannot cancel another subscriber's work. A blocking
    native owner retains its slot until it really returns; no replacement
    thread is spawned to evade the bound.
    """
    def __init__(self, max_active: int = 2, max_subscribers: int = 8):
        self.max_active, self.max_subscribers = max_active, max_subscribers
        self._lock = RLock()
        self._flights: dict[tuple, _Flight] = {}

    def run(self, key: tuple, function: Callable[[], dict], *, cancelled: Event | None = None,
            seconds: float = 175.0) -> dict:
        client = cancelled if cancelled is not None else Event()
        if client.is_set():
            raise WorkspaceReadError('WORKSPACE_READ_CANCELLED')
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                if len(self._flights) >= self.max_active:
                    raise WorkspaceReadError('WORKSPACE_READ_BUSY')
                flight = self._flights[key] = _Flight()
            assert flight is not None
            if len(flight.clients) >= self.max_subscribers:
                raise WorkspaceReadError('WORKSPACE_READ_BUSY')
            flight.clients.append(client)
        if not leader:
            try:
                deadline = time.monotonic()+seconds
                while not flight.done.wait(0.025):
                    if client.is_set():
                        raise WorkspaceReadError('WORKSPACE_READ_CANCELLED')
                    if time.monotonic() >= deadline:
                        raise WorkspaceReadError('WORKSPACE_READ_TIMEOUT')
                if client.is_set():
                    raise WorkspaceReadError('WORKSPACE_READ_CANCELLED')
                if flight.error:
                    raise flight.error
                result = deepcopy(flight.value)
                result.setdefault('read_metrics', {})['joined_inflight'] = True
                return result
            finally:
                client.set()
        def alive() -> bool:
            with self._lock:
                return any(not c.is_set() for c in flight.clients)
        trace = ReadTrace(str(key[0]), str(key[1]), time.monotonic()+seconds, alive)
        token = _TRACE.set(trace)
        outcome = 'RETURNED'
        try:
            value = function()
            trace.check()
            value['read_metrics'] = {**trace.result(), 'joined_inflight': False}
            flight.value = deepcopy(value)
            if client.is_set():
                # Followers still receive the completed validated snapshot.
                raise WorkspaceReadError('WORKSPACE_READ_CANCELLED')
            return value
        except BaseException as exc:
            outcome = exc.code if isinstance(exc, WorkspaceReadError) else type(exc).__name__
            if flight.value is None:
                flight.error = exc
            raise
        finally:
            _TRACE.reset(token)
            _LOG.info('workspace_read %s', json.dumps(trace.result(outcome), ensure_ascii=False))
            with self._lock:
                flight.done.set()
                if self._flights.get(key) is flight:
                    del self._flights[key]
