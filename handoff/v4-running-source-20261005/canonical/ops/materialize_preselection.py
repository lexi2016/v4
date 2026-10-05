"""Materialize the seven V3 preselection pools from explicit graph inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from domains.preselection_materializer import (
    build_baimao_pool,
    build_research_preview_pool,
    build_selector_premarket_pool,
    build_upstream_csv_pool,
    build_wechat_pool,
    materialize_preselection_date,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from v4_migration.write_authority_reference import (
    WriteAuthorityResolutionError,
    reject_cli_authority_declaration,
)


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"


def build_artifacts(args: argparse.Namespace) -> list[dict]:
    date = args.trade_date
    return [
        build_selector_premarket_pool(args.selector, date),
        build_upstream_csv_pool(
            args.fupan, date, pool_id="a_d1_fupan_watchlist_pool",
            display_name="A股 D-1 复盘继续观察池", market="A", status="available",
            producer_id="v3_fupan_watchlist_upstream_v1",
        ),
        build_upstream_csv_pool(
            args.stage7, date, pool_id="a_d1_stage7_fenshi_review_pool",
            display_name="A股 D-1 Stage7/分时复盘池", market="A", status="available",
            producer_id="v3_stage7_fenshi_upstream_v1",
        ),
        build_research_preview_pool(args.research_preview, args.selector, date),
        build_baimao_pool(args.baimao, date),
        build_upstream_csv_pool(
            args.hk, date, pool_id="hkconnect_d1_top100",
            display_name="港股通 0.2 D-1 Top100", market="HK", status="STRICT_0_2_READY",
            producer_id="v3_hkconnect_d1_upstream_v1",
        ),
        build_wechat_pool(args.wechat_manifest, args.wechat_rows, date),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--fupan", type=Path, required=True)
    parser.add_argument("--stage7", type=Path, required=True)
    parser.add_argument("--research-preview", type=Path, required=True)
    parser.add_argument("--baimao", type=Path)
    parser.add_argument("--hk", type=Path, required=True)
    parser.add_argument("--wechat-rows", type=Path, required=True)
    parser.add_argument("--wechat-manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--write-authorization-ref",
        action="append",
        default=None,
        help="untrusted declaration; denied until a separately implemented owner trust provider exists",
    )
    args = parser.parse_args(argv)
    try:
        reject_cli_authority_declaration(args.write_authorization_ref)
    except WriteAuthorityResolutionError as error:
        print(json.dumps({
            "status": "REJECTED",
            "reason": error.reason_code,
            "detail": str(error),
            "authorization_source": error.source,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 3
    input_paths = tuple(Path(path) for path in (
        args.fupan, args.stage7, args.research_preview, args.hk,
        args.wechat_manifest, args.wechat_rows,
    ))
    before = {path: path.read_bytes() for path in input_paths}
    results = materialize_preselection_date(
        PreselectionPoolStore(args.data_root), build_artifacts(args)
    )
    if any(path.read_bytes() != content for path, content in before.items()):
        raise RuntimeError("read-only preselection input changed")
    print(json.dumps({"trade_date": args.trade_date, "artifacts": results}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
