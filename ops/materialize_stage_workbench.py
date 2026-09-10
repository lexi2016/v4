"""Materialize one eight-stage workbench slice from a V3.5 data root.

CLI counterpart of ``POST /api/v3/workbench/stage/ensure`` for the
``stage_workbench`` runtime workload. It builds the same StageRunner
dependency graph as the API and calls ``ensure`` for one date/stage, then
prints a machine-readable receipt. Read-only: it never writes into legacy V3
and keeps the trading safety flags false.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from contracts.stages import FROZEN_STAGE_IDS
from domains.stage_input_producer import StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"


def build_stage_runner(data_root: Path) -> StageRunner:
    store = NativeDataStore(data_root)
    stage_store = StageStore(store.root)
    quote_provider = StageQuoteProvider(
        primary=FutuQuoteProvider(),
        a_replay=TdxMinuteReplayProvider(),
        references=stage_store,
        hk_replay=HkConnectStageReplayProvider(),
    )
    return StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            store,
            stage_store,
            quote_provider,
        ),
        opening_second_filter_store=OpeningSecondFilterStore(store.root),
    )


def materialize(data_root: Path, trade_date: str, stage_id: str, *, force: bool) -> dict:
    if stage_id not in FROZEN_STAGE_IDS:
        raise ValueError(f"unknown stage_id: {stage_id}")
    runner = build_stage_runner(data_root)
    result = runner.ensure(trade_date, stage_id, force=force)
    return {
        "ok": bool(result.get("ok", True)),
        "schema_version": "v3_5.stage_workbench_materialize.v1",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "data_root": str(data_root.resolve()),
        "ensure_status": result.get("ensure_status"),
        "run_id": result.get("run_id"),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "receipt": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--date", required=True, help="trade date YYYYMMDD")
    parser.add_argument("--stage", required=True, help="eight-stage id, e.g. STAGE_0925")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    payload = materialize(args.data_root, args.date, args.stage, force=args.force)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
