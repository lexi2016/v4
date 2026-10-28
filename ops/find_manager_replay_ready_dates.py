"""CLI for read-only discovery of dates eligible for the R4 Manager replay canary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v4.manager_research.replay_readiness import (
    ScanConfig,
    safe_receipt_destination,
    scan_replay_ready_dates,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--universe-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--news-owner-root", type=Path, required=True)
    parser.add_argument("--universe-owner-root", type=Path, required=True)
    parser.add_argument("--universe-owner-sha256", required=True)
    parser.add_argument("--rebound-authority-root", type=Path, required=True)
    parser.add_argument("--materializer-app-root", type=Path, required=True)
    parser.add_argument("--materializer-source-sha256", required=True)
    parser.add_argument("--max-dates", type=int, default=120)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    config = ScanConfig(
        state_root=args.state_root, universe_root=args.universe_root, data_root=args.data_root,
        news_owner_root=args.news_owner_root, universe_owner_root=args.universe_owner_root,
        universe_owner_sha256=args.universe_owner_sha256, rebound_authority_root=args.rebound_authority_root,
        materializer_app_root=args.materializer_app_root, materializer_source_sha256=args.materializer_source_sha256,
        max_dates=args.max_dates,
    )
    receipt_path = None
    if args.receipt:
        try:
            receipt_path = safe_receipt_destination(args.receipt, config)
        except ValueError as exc:
            parser.error(str(exc))
    result = scan_replay_ready_dates(config)
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if receipt_path is not None:
        try:
            receipt_path = safe_receipt_destination(receipt_path, config)
        except ValueError as exc:
            parser.error(str(exc))
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path = safe_receipt_destination(receipt_path, config)
        receipt_path.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0 if result["ready_count"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
