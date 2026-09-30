"""Concurrent issuer-map cache checks against an in-memory transport only."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
import v4.manager_research.hkex_provider as module
from v4.manager_research.hkex_provider import HkexOfficialProvider, ProviderError
from v4.manager_research.ports import SourceResponse


def response(url, status=200):
    return SourceResponse(url=url, status_code=status,
        body=json.dumps([{"c":"00001","i":1,"n":"Offline issuer"}]).encode(),
        headers={}, retrieved_at="2026-09-06T00:00:00+00:00", final_url=url)


def test_concurrent_cache_miss_fetches_once():
    lock=threading.Lock()
    calls=[]
    start=threading.Barrier(4)
    def transport(url, **kw):
        with lock: calls.append(url)
        time.sleep(0.08)
        return response(url)
    provider=HkexOfficialProvider(transport)
    def load():
        start.wait(timeout=2)
        return provider._load_active_stocks()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _: load(), range(4)))
    assert len(calls) == 1
    assert all(result == results[0] for result in results)


def test_expired_cache_failure_does_not_return_previous_mapping(monkeypatch):
    now=[1000.0]
    calls=[]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    def transport(url, **kw):
        calls.append(url)
        return response(url, 200 if len(calls)==1 else 503)
    provider=HkexOfficialProvider(transport)
    provider._load_active_stocks()
    now[0] += 301.0  # default TTL is an engineering freshness limit, NOT a PIT proof
    with pytest.raises(ProviderError, match="503"):
        provider._load_active_stocks()
    with pytest.raises(ProviderError, match="503"):
        provider._load_active_stocks()
    assert len(calls)==3
