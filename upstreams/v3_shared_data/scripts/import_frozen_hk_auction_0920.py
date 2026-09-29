"""Explicit offline importer for one frozen HK 09:20 reference CSV.

This migration-only entry is intentionally not referenced by any scheduler.
It requires the caller to supply the expected source SHA-256 and never searches
legacy directories.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.hashing import sha256_json
from shared_data.hk_auction_0920 import (
    TOP_FILTER_N,
    TOP_REFERENCE_N,
    build_second_filter_rows,
    load_verified_candidates,
    publish_reference_rows,
)
from shared_data.store import StoreError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_frozen_reference(
    store_root: Path,
    trade_date: str,
    source: Path,
    expected_sha256: str,
) -> dict:
    actual_sha = _sha256(source)
    if actual_sha.lower() != expected_sha256.lower():
        raise StoreError("frozen HK auction source SHA-256 mismatch")
    with open(source, "r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if len(rows) != TOP_REFERENCE_N:
        raise StoreError(f"frozen HK auction source must be Top{TOP_REFERENCE_N}")
    if any(str(row.get("target_date") or "") != trade_date for row in rows):
        raise StoreError("frozen HK auction source trade date mismatch")
    clocks = []
    max_loop = 0
    for row in rows:
        stamp = str(row.get("collector_wall_time") or "")
        match = re.search(r"(\d{2}:\d{2}:\d{2})", stamp)
        if match is None or match.group(1) > "09:19:59":
            raise StoreError("frozen HK auction source is not cutoff safe")
        clocks.append(match.group(1))
        max_loop = max(max_loop, int(float(row.get("collector_loop") or 0)))
    if max(clocks) < "09:19:00" or max_loop < 2:
        raise StoreError("frozen HK auction source lacks continuous coverage evidence")
    candidates, evidence = load_verified_candidates(store_root, trade_date)
    filtered = build_second_filter_rows(candidates, rows)
    if len(filtered) != TOP_FILTER_N:
        raise StoreError(f"frozen HK auction second filter must be Top{TOP_FILTER_N}")
    source_output_sha = sha256_json({
        "contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
        "trade_date": trade_date,
        "rows": filtered,
    })
    published = publish_reference_rows(
        store_root,
        trade_date,
        rows,
        signal_date=evidence["signal_date"],
        d1_pool_sha256=evidence["d1_pool_sha256"],
        source_output_sha256=source_output_sha,
    )
    return {
        "ok": published.get("status") == "READY",
        "status": published.get("status"),
        "trade_date": trade_date,
        "source_sha256": actual_sha,
        "source_output_sha256": source_output_sha,
        "reference_row_count": len(rows),
        "second_filter_row_count": len(filtered),
        "run": published,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        result = import_frozen_reference(
            args.store_root,
            args.trade_date,
            args.source,
            args.expected_sha256,
        )
    except (OSError, StoreError, ValueError) as exc:
        result = {"ok": False, "status": "FAILED", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
