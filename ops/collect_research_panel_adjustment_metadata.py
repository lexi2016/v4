"""Bounded maintenance invocation of the original daily producer's factor cache.

This writes metadata only and does not produce price panels or change CURRENT.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.research_panel_factor_cache import QfqGateError, _json, collect_metadata, sha


def execute(*, universe_path: Path, universe_sha256: str, target: int, cache_root: Path,
            min_interval: float = .2, force_refresh: bool = False, collector=collect_metadata) -> tuple[int, dict]:
    if not universe_path.is_absolute() or sha(universe_path) != universe_sha256:
        raise QfqGateError("UNIVERSE_INPUT_SHA256_MISMATCH")
    universe = json.loads(universe_path.read_text())
    items = universe["items"]
    codes = [item["ts_code"] for item in items]
    if (str(universe.get("target_date")) != str(target) or universe.get("target_count") != len(codes)
            or len(codes) != len(set(codes)) or not codes or any(not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code) for code in codes)):
        raise QfqGateError("UNIVERSE_ASOF_COUNT_OR_KEYS_INVALID")
    source_path = Path(universe["source_path"])
    if sha(source_path) != universe["source_sha256"]:
        raise QfqGateError("ORIGINAL_UNIVERSE_RECEIPT_DRIFT")
    result = collector(codes, cache_root=cache_root, target=target, min_interval=min_interval,
                       force_refresh=force_refresh, max_age_seconds=86400, retries=2)
    receipt = dict(status=result["status"], counts=result["counts"], requested_count=len(codes), asof_date=target,
                   universe_path=str(universe_path), universe_sha256=universe_sha256,
                   source_path=str(source_path), source_sha256=universe["source_sha256"],
                   requested_codes_sha256=result["requested_codes_sha256"], finished_at=result["finished_at"],
                   cache_dir=str(cache_root / str(target)), RESEARCH_ONLY=True,
                   production_allowed=False, buy_gate_updated=False, orders_sent=False)
    _json(cache_root / str(target) / "collection_receipt.json", receipt)
    # Expected unsupported BJ is an explicit partial metadata terminal. All
    # unexpected errors fail the process, with partial checkpoints preserved.
    return (0 if receipt["status"] in ("READY", "PARTIAL_EXPECTED_UNSUPPORTED") else 2), receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--min-interval", type=float, default=.2)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    try:
        code, receipt = execute(universe_path=args.universe, universe_sha256=args.universe_sha256, target=args.target,
                                cache_root=args.cache_root, min_interval=args.min_interval, force_refresh=args.force_refresh)
    except Exception as exc:
        print(json.dumps(dict(status="FAILED", error=str(exc)), ensure_ascii=False))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
