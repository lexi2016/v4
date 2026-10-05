from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time
from domains.research_review_generation import run_generation, GenerationRefused
from test_research_review_generation import _payload


def test_same_date_concurrent_public_entries_invoke_backend_only_once(tmp_path):
    started = Event(); guard = Lock(); calls = []
    def backend(date):
        with guard:
            calls.append(date)
        started.set()
        time.sleep(0.15)
        return _payload(date)
    def invoke():
        try:
            return run_generation("20260911", review_root=tmp_path / "reviews", backend=backend)["status"]
        except GenerationRefused:
            return "REFUSED"
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(invoke)
        assert started.wait(2)
        second = pool.submit(invoke)
        statuses = [first.result(timeout=5), second.result(timeout=5)]
    assert len(calls) == 1
    assert sorted(statuses) == ["READY_FOR_REVIEW", "REFUSED"]
