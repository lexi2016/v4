"""Material store regressions (fetch once, parse once, reuse everywhere)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from v4.manager_research.materials import MaterialStore


class CountingTransport:
    def __init__(self, body: bytes, *, retrieved_at: str | None = None, delay: float = 0.0):
        self.body = body
        self.retrieved_at = retrieved_at
        self.delay = delay
        self.calls = 0

    def __call__(self, url: str):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        payload = {"body": self.body, "content_type": "text/plain"}
        if self.retrieved_at is not None:
            payload["retrieved_at"] = self.retrieved_at
        return payload


def test_miss_then_hit_uses_cache(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    transport = CountingTransport(b"hello", retrieved_at=retrieved_at)

    first = store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)
    second = store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)

    assert transport.calls == 1
    assert first.from_cache is False and second.from_cache is True
    assert second.sha256 == first.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert second.body == b"hello"
    assert second.url == "https://example.invalid/a"
    assert second.retrieved_at == retrieved_at


def test_stale_retrieved_at_refetches_and_immutable_ttl_does_not(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    stale = CountingTransport(b"v1", retrieved_at="2020-01-01T00:00:00Z")
    store.fetch("k", url="https://example.invalid/a", ttl_seconds=60, transport=stale)
    store.fetch("k", url="https://example.invalid/a", ttl_seconds=60, transport=stale)
    assert stale.calls == 2  # TTL expired by retrieved_at, never by "now"

    immutable = CountingTransport(b"v1", retrieved_at="2020-01-01T00:00:00Z")
    store.fetch("i", url="https://example.invalid/immutable", ttl_seconds=None, transport=immutable)
    store.fetch("i", url="https://example.invalid/immutable", ttl_seconds=None, transport=immutable)
    assert immutable.calls == 1


def test_force_bypasses_cache(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    transport = CountingTransport(b"x")
    store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)
    door = store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport, force=True)
    assert transport.calls == 2
    assert door.from_cache is False


def test_concurrent_callers_single_flight(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    transport = CountingTransport(b"once", delay=0.2)
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(2)
        material = store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)
        results.append(material.from_cache)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert transport.calls == 1
    assert sorted(results) == [False, True]


def test_same_bytes_share_one_blob(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    body = b"shared-bytes"
    store.fetch("k1", url="https://example.invalid/1", ttl_seconds=None, transport=CountingTransport(body))
    store.fetch("k2", url="https://example.invalid/2", ttl_seconds=None, transport=CountingTransport(body))
    blobs = list((tmp_path / "materials" / "blobs").iterdir())
    assert len(blobs) == 1
    assert blobs[0].read_bytes() == body


def test_corrupt_index_is_a_miss(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    transport = CountingTransport(b"payload")
    store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)
    index = tmp_path / "materials" / "index" / (hashlib.sha256(b"k").hexdigest() + ".json")
    index.write_bytes(b"{not-json")
    store.fetch("k", url="https://example.invalid/a", ttl_seconds=3600, transport=transport)
    assert transport.calls == 2


def test_parsed_cache_is_versioned_and_failure_persists_nothing(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    material = store.fetch("k", url="https://example.invalid/a", ttl_seconds=None, transport=CountingTransport(b"raw"))
    parse_calls = {"n": 0}

    def parse(body: bytes):
        parse_calls["n"] += 1
        return {"facts": [body.decode()]}

    first = store.parsed(material, parser_id="pdf", parser_version=1, parse_fn=parse)
    second = store.parsed(material, parser_id="pdf", parser_version=1, parse_fn=parse)
    assert first == second == {"facts": ["raw"]}
    assert parse_calls["n"] == 1

    store.parsed(material, parser_id="pdf", parser_version=2, parse_fn=parse)
    assert parse_calls["n"] == 2  # parser upgrade re-parses

    def broken(_body: bytes):
        raise ValueError("parse exploded")

    with pytest.raises(ValueError):
        store.parsed(material, parser_id="pdf", parser_version=3, parse_fn=broken)
    parsed_dir = tmp_path / "materials" / "parsed"
    assert not any("v3.json" in path.name for path in parsed_dir.glob("*.json"))
