"""Refresh the exact-date source-only research pool after the V3 cutoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from domains.preselection_materializer import build_hourly_research_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore


def refresh_research_preselection(
    *,
    data_root: Path,
    trade_date: str,
) -> dict:
    artifact = build_hourly_research_pool(
        data_root,
        trade_date=trade_date,
    )
    publication = PreselectionPoolStore(data_root).materialize(artifact)
    return {
        "schema_version": "v3_5.research_preselection_refresh.v1",
        "status": "SUCCEEDED",
        "trade_date": trade_date,
        "row_count": len(artifact["rows"]),
        "source_role": artifact["source_role"],
        "source_sha256": artifact["source_sha256"],
        "publication": publication,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    try:
        result = refresh_research_preselection(
            data_root=args.data_root,
            trade_date=args.date,
        )
    except FileNotFoundError as error:
        result = {
            "schema_version": "v3_5.research_preselection_refresh.v1",
            "status": "NOT_MATERIALIZED",
            "trade_date": args.date,
            "reason": str(error),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
