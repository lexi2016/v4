"""Deterministic Phase 6 benchmark for verified hourly-research retries."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from infrastructure.research_store import HourlyResearchStore
from ops.run_hourly_research import run_hourly_research_file


SOURCE_SHA256 = "8ba8b92b6c85b977caac13390533fbf0aec05bfd4e52045229f0964a159be96c"
DERIVED_SOURCE_SHA256 = "62460168d82c2a0d17cac6d7b32d1052c3744e097fcc3a036f19b6fd8329e13a"
BUSINESS_DATE = "20260730"
SLOT = "2310"
MODE = "REPLAY"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int((len(ordered) * percentile) + 0.999999) - 1))
    return ordered[rank]


def _derived_source(raw: bytes) -> bytes:
    if _sha_bytes(raw) != SOURCE_SHA256:
        raise ValueError("frozen Phase 6 source SHA mismatch")
    source = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(source, dict) or not isinstance(source.get("source_manifest"), dict):
        raise ValueError("frozen Phase 6 source shape mismatch")
    if source["source_manifest"].get("hourly_slot") != "2300":
        raise ValueError("frozen Phase 6 source slot mismatch")
    source["source_manifest"]["hourly_slot"] = SLOT
    derived = json.dumps(
        source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if _sha_bytes(derived) != DERIVED_SOURCE_SHA256:
        raise ValueError("derived Phase 6 source SHA mismatch")
    return derived


def _run(data_root: Path, source: Path) -> dict[str, Any]:
    return run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date=BUSINESS_DATE,
        target_date=BUSINESS_DATE,
        slot=SLOT,
        mode=MODE,
    )


def benchmark(source_path: Path, *, iterations: int, code_commit: str) -> dict[str, Any]:
    if iterations < 3:
        raise ValueError("benchmark requires at least three measured iterations")
    original_raw = source_path.read_bytes()
    derived = _derived_source(original_raw)
    with tempfile.TemporaryDirectory(prefix="v35-phase6-") as temporary:
        root = Path(temporary)
        benchmark_source = root / "derived-production-scale-source.json"
        benchmark_source.write_bytes(derived)
        data_root = root / "data"
        first = _run(data_root, benchmark_source)
        warmup = _run(data_root, benchmark_source)
        durations: list[float] = []
        results: list[dict[str, Any]] = []
        for _ in range(iterations):
            started = time.perf_counter()
            result = _run(data_root, benchmark_source)
            durations.append(time.perf_counter() - started)
            results.append(result)
        payload_hashes = {
            str(item["payload_sha256"])
            for item in [first, warmup, *results]
        }
        if len(payload_hashes) != 1:
            raise ValueError("idempotent retry changed the payload SHA")
        artifact = HourlyResearchStore(data_root).read_exact(
            BUSINESS_DATE,
            SLOT,
            mode=MODE,
        )
        if artifact is None or artifact.get("source_input_sha256") != DERIVED_SOURCE_SHA256:
            raise ValueError("benchmark artifact source identity mismatch")
        if any(
            item.get(flag) is not False
            for item in [first, warmup, *results]
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
        ):
            raise ValueError("benchmark safety flag changed")
        if source_path.read_bytes() != original_raw:
            raise ValueError("frozen external source changed during benchmark")
        artifact_bytes = json.dumps(
            artifact,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "schema_version": "v3_5.phase6_benchmark_result.v1",
            "benchmark_id": "phase6.hourly_research.content_addressed_idempotent_retry.v1",
            "code_commit": code_commit,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "business_date": BUSINESS_DATE,
            "slot": SLOT,
            "mode": MODE,
            "iterations": iterations,
            "warmup_iterations": 1,
            "source_sha256": SOURCE_SHA256,
            "derived_source_sha256": DERIVED_SOURCE_SHA256,
            "payload_sha256": payload_hashes.pop(),
            "artifact_canonical_sha256": _sha_bytes(artifact_bytes),
            "article_count": artifact["article_count"],
            "stock_pool_count": artifact["stock_pool_count"],
            "durations_seconds": durations,
            "median_seconds": statistics.median(durations),
            "p95_seconds": _percentile(durations, 0.95),
            "source_read_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = benchmark(
        args.source,
        iterations=args.iterations,
        code_commit=args.code_commit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
