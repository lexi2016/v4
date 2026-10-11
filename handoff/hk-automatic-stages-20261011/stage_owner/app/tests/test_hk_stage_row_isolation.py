from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center import live_collectors
from stage_center.acquisition import SourceResult
from stage_center.contracts import EIGHT_STAGES
from stage_center import raw_store
from stage_center.raw_store import RawStore
from stage_center.runner import RunnerConfig, StageCenterRunner
from stage_center.scheduler import DueDecision
from stage_center.selection import SelectionStore, select_hk_four_lane
from test_hk_partial_rows import CODES, TRADE_DATE, _write_partial_d1


E6_ROOT = Path(__file__).resolve().parents[4]
MINUTE_STAGE_IDS = tuple(
    stage.stage_id
    for stage in EIGHT_STAGES
    if stage.stage_id not in {"STAGE_0925"}
)


def _row(code: str, stage_id: str) -> dict[str, object]:
    stage = next(item for item in EIGHT_STAGES if item.stage_id == stage_id)
    start_hm = stage.window.split("-")[0]
    start = f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]} {start_hm}:00"
    end = f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]} {stage.cutoff}"
    return {
        "batch_index": 0,
        "code": code,
        "name": code,
        "update_time": end,
        "last_price": 10.5,
        "open_price": 10.0,
        "high_price": 10.7,
        "low_price": 9.9,
        "prev_close_price": 10.0,
        "turnover": 1000000.0,
        "volume": 100000.0,
        "bid_price": 10.49,
        "ask_price": 10.51,
        "bid_vol": 1000.0,
        "ask_vol": 900.0,
        "window_start": start,
        "window_end": end,
        "bar_count": 1,
        "temporal_cutoff_safe": True,
        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        "current_change_pct": 5.0,
        "volume_ratio": 1.2,
    }


class TestHKStageRowIsolation(unittest.TestCase):
    def test_partial_hk_rows_publish_for_each_minute_stage(self) -> None:
        for stage_id in MINUTE_STAGE_IDS:
            with self.subTest(stage_id=stage_id), tempfile.TemporaryDirectory(dir=E6_ROOT / "receipts") as temporary:
                root = Path(temporary)
                data_root = root / "data"
                d1_path = _write_partial_d1(data_root)
                d1_root = data_root / "preselection_pools"
                config_kwargs: dict[str, object] = {}
                if stage_id == "STAGE_1545_1555":
                    replay_root = root / "hk-stage8-replay"
                    replay_root.mkdir()
                    config_kwargs["hk_stage_replay_root"] = replay_root
                config = RunnerConfig(
                    candidate_acquisition_root=root / "missing-candidate",
                    raw_root=root / "raw",
                    selection_root=root / "selection",
                    receipt_root=root / "runner-receipts",
                    hk_d1_root=d1_root,
                    shared_data_root=root / "shared",
                    python_path=Path(sys.executable),
                    **config_kwargs,
                )
                calls: list[tuple[str, tuple[str, ...]]] = []

                def collector(plan, market: str) -> SourceResult:
                    requested = tuple(plan.codes_for(market))
                    calls.append((market, requested))
                    self.assertEqual(set(requested), set(CODES))
                    rows = (_row(CODES[0], stage_id), _row(CODES[1], stage_id))
                    return SourceResult(
                        source_id="fixture_pytdx_partial",
                        status="PARTIAL_WITH_ROWS",
                        rows=rows,
                        requested_rows=len(CODES),
                        missing_symbols=(CODES[2],),
                        source_evidence=("fixture=one HK symbol unavailable; remaining exact D1 members retained",),
                    )

                def builder(source, plan, raw):
                    return select_hk_four_lane(
                        source.rows,
                        plan.trade_date,
                        plan.stage_id,
                        raw["artifact_sha256"],
                        source_status=source.status,
                        requested_rows=source.requested_rows,
                        missing_symbols=source.missing_symbols,
                        cannot_confirm=source.cannot_confirm,
                        source_evidence=source.source_evidence,
                    )

                decision = DueDecision(
                    stage_id=stage_id,
                    trade_date=TRADE_DATE,
                    status="DUE",
                    scheduled_at=None,
                    idempotency_key=f"hk-row-isolation-{stage_id}",
                    calendar={
                        "a_share": "NON_TRADING_DAY",
                        "hk_securities": "FULL_TRADING_DAY",
                        "hk_connect": "FULL_TRADING_DAY",
                    },
                )
                with (
                    patch.object(live_collectors, "production_selection_builders", return_value={
                        "A_SHARE": lambda *_args: {},
                        "HK_CONNECT": builder,
                    }),
                    patch("stage_center.runner._stage_markets_for_date", return_value=("HK_CONNECT",)),
                    patch.object(raw_store, "eligible_stage_markets", return_value=("HK_CONNECT",)),
                ):
                    result = StageCenterRunner(config, collectors={"HK_CONNECT": collector})._run_one(decision)

                self.assertTrue(d1_path.is_file())
                self.assertEqual(calls, [("HK_CONNECT", CODES)])
                self.assertEqual(result["status"], "PARTIAL_WITH_ROWS", result)
                market = result["markets"]["HK_CONNECT"]
                self.assertEqual(market["selection_status"], "PARTIAL_WITH_ROWS")
                self.assertEqual(market["selected_rows"], 2)
                self.assertEqual(market["source_status"], "PARTIAL_WITH_ROWS")
                self.assertEqual(market["missing_symbols"], [CODES[2]])
                self.assertFalse(result["production_allowed"])
                self.assertFalse(result["buy_gate_updated"])
                self.assertFalse(result["orders_sent"])

                with patch.object(raw_store, "eligible_stage_markets", return_value=("HK_CONNECT",)):
                    raw_bundle = RawStore(root / "raw").read_verified_bundle(TRADE_DATE, stage_id)
                raw_market = raw_bundle["receipt"]["markets"]["HK_CONNECT"]
                self.assertEqual(raw_market["status"], "PARTIAL_WITH_ROWS")
                self.assertEqual(raw_market["row_count"], 2)
                selection = SelectionStore(root / "selection").read_verified(TRADE_DATE, stage_id, "HK_CONNECT")
                self.assertEqual(selection["selection_status"], "PARTIAL_WITH_ROWS")
                self.assertEqual(len(selection["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
