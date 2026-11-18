"""Mechanical checks of persisted reservations. These create no output scoring rows."""
from datetime import datetime, timezone
import hashlib
import multiprocessing

import pytest

from research.p515_prospective_readiness.coordinator import (
    BudgetExceeded, DuplicateAttempt, NoGoError, _CoordinatorStore, fixed_d_dates,
)

_IDENTITY = {"study_id": "SYNTHETIC_FIXTURE_ONLY", "mode": "SYNTHETIC_FIXTURE_ONLY"}
_AT = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
_SHA = "a" * 64


def _intent_worker(root, start, ready, result):
    store = _CoordinatorStore(root, _IDENTITY)
    ready.put(True)
    assert start.wait(10)
    try:
        store.claim_intent("20261127", "fixture", created_at=_AT)
    except DuplicateAttempt:
        result.put("duplicate")
    else:
        result.put("created")


def _reserve(store, D, n, *, event_ids=None):
    store.claim_intent(D, f"fixture-{D}", created_at=_AT)
    ids = list(event_ids if event_ids is not None else (f"fixture-{D}-{i}" for i in range(n)))
    store.reserve(
        D=D, attempt_id=hashlib.sha256(D.encode()).hexdigest(), eligible_count=n, output_rows=2 * n,
        input_sha256=_SHA, matrix_sha256=_SHA, keys_sha256=_SHA, created_at=_AT,
        event_records=[(i + ":PB1", i, 1, None) for i in ids],
    )


def test_budget_caps_and_consumed_reservation_survive_reopen(tmp_path):
    store = _CoordinatorStore(tmp_path, _IDENTITY)
    sessions = [d.strftime("%Y%m%d") for d in fixed_d_dates()]
    _reserve(store, sessions[0], 200)
    store.begin_fixture_callback(sessions[0], at=_AT)
    # Deliberately leave CALL_STARTED without a result to simulate an interrupted callback.
    store = _CoordinatorStore(tmp_path, _IDENTITY)
    assert store.totals() == (1, 400, 200)
    with pytest.raises(NoGoError):
        store.begin_fixture_callback(sessions[0], at=_AT)
    for D in sessions[1:]:
        _reserve(store, D, 200)
    assert store.totals() == (15, 6000, 3000)
    with pytest.raises(BudgetExceeded, match="15 daily"):
        _reserve(store, "20261214", 1)
    assert store.execution_counts()["model_api_predict_calls"] == 0


def test_unique_pb_conflict_is_persistent_across_days(tmp_path):
    store = _CoordinatorStore(tmp_path, _IDENTITY)
    _reserve(store, "20261127", 1, event_ids=["synthetic-family"])
    reopened = _CoordinatorStore(tmp_path, _IDENTITY)
    with pytest.raises(DuplicateAttempt, match="PB"):
        _reserve(reopened, "20261130", 1, event_ids=["synthetic-family"])
    assert reopened.totals() == (1, 2, 1)


def test_two_processes_only_one_intent(tmp_path):
    _CoordinatorStore(tmp_path, _IDENTITY)
    ctx = multiprocessing.get_context("spawn")
    start, ready, result = ctx.Event(), ctx.Queue(), ctx.Queue()
    processes = [ctx.Process(target=_intent_worker, args=(tmp_path, start, ready, result))
                 for _ in range(2)]
    try:
        for process in processes:
            process.start()
        assert ready.get(timeout=10) and ready.get(timeout=10)
        start.set()
        assert sorted(result.get(timeout=10) for _ in processes) == ["created", "duplicate"]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        for queue in (ready, result):
            queue.close()
            queue.join_thread()
