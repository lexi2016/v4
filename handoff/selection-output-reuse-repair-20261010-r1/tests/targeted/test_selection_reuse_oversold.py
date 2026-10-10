"""Synthetic behavioral regression for the real read_rebound_screen function.

This is not an owner or market replay. The test imports the active checkout module.
Only unavailable file/calendar/owner boundaries are mocked. Synthetic calendar
tokens are not claims about real HK sessions. Volume stays NOT_PROVEN, and every
scenario must remain pending with zero selected rows.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
from v4.manager_research import workspace_plan as wp


def run_synthetic_screen(close: float | None, prior_high: float) -> dict:
    day = "20261009"
    # Test tokens only: deliberately no substituted production calendar.
    dates = [(date(2026, 10, 9) - timedelta(days=n)).strftime("%Y%m%d")
             for n in range(60, 0, -1)]
    symbol = "HK.00001"
    context = dict(plan_trade_date=day, market_session=day,
        research_cutoff="2026-10-09T18:00:00+08:00",
        screen_phase="POST_CLOSE_COMPLETED_SESSION",
        screen_session_policy="COMPLETED_FULL_HK_SECURITIES_SESSION")
    history_sessions = dict(prior60=dates, previous5=dates[-5:],
        panel_session=dates[-1], calendar_sha256="c" * 64)
    records = [dict(trade_date_compact=d, code_norm=symbol, name="SYNTHETIC ONLY",
        open=0.30, high=prior_high, low=0.27, close=0.30,
        amount=1.0, trade=100.0, pre_close=0.30) for d in dates]
    records.append(dict(trade_date_compact=day, code_norm=symbol,
        name="SYNTHETIC ONLY", open=0.28, high=0.30, low=0.27, close=close,
        amount=1.0, trade=150.0, pre_close=0.30))
    panel = dict(owner="SYNTHETIC_OWNER_BOUNDARY", panel_path="/synthetic/panel",
        panel_sha256="1" * 64, panel_manifest_path="/synthetic/manifest",
        panel_manifest_sha256="2" * 64, panel_rows=61, panel_code_count=1,
        source_contract="SYNTHETIC_OWNER_BOUNDARY")
    master = dict(owner="SYNTHETIC_MASTER_BOUNDARY", captured_at="2026-10-09T17:00:00+08:00",
        names={symbol: dict(name="SYNTHETIC ONLY")}, artifact_path="/synthetic/master",
        artifact_sha256="3" * 64, manifest_path="/synthetic/master_manifest",
        manifest_sha256="4" * 64)
    unproven_volume = dict(status="NOT_PROVEN", unit_status="NOT_PROVEN", unit=None,
        scale_applied=None, gaps=["SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN"])
    missing_owner_modules = {}
    for name in ("v3_shared_data", "v3_shared_data.shared_data", "v3_shared_data.shared_data.store",
                 "upstreams", "upstreams.v3_shared_data", "upstreams.v3_shared_data.shared_data",
                 "upstreams.v3_shared_data.shared_data.hk_security_master"):
        module = types.ModuleType(name)
        module.__path__ = []
        missing_owner_modules[name] = module
    missing_owner_modules["v3_shared_data.shared_data.store"].StoreError = type("StoreError", (Exception,), {})
    missing_owner_modules["upstreams.v3_shared_data.shared_data.hk_security_master"].HKSecurityMasterReadError = type(
        "HKSecurityMasterReadError", (Exception,), {})
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, missing_owner_modules))
        stack.enter_context(patch.object(wp, "screen_context", return_value=context))
        stack.enter_context(patch.object(wp, "rebound_history_sessions", return_value=history_sessions))
        stack.enter_context(patch.object(wp, "_read_hk02_panel_witness", return_value=(panel, [])))
        stack.enter_context(patch.object(wp, "_screen_security_master_witness", return_value=(master, {})))
        stack.enter_context(patch.object(wp, "_screen_panel_volume_evidence", return_value=unproven_volume))
        stack.enter_context(patch.object(wp, "_read_hk02_daily_supplement_witness", return_value=None))
        stack.enter_context(patch.object(pd, "read_parquet", return_value=pd.DataFrame(records)))
        result = wp.read_rebound_screen(Path("/synthetic"), context)
    return result


class OversoldBoundaryRegression(unittest.TestCase):
    def assert_pending_boundary(self, close, high, expected):
        result = run_synthetic_screen(close, high)
        self.assertEqual(result["cards"], [])
        self.assertEqual(result["strict"], [])
        self.assertEqual(result["near"], [])
        self.assertEqual(len(result["pending"]), 1, result)
        row = result["pending"][0]
        self.assertEqual(row["volume_unit_status"], "NOT_PROVEN")
        self.assertIsNone(row["volume_flag_5d_ge_1_5"])
        self.assertEqual(row["history_status"], "PARTIAL_UNKNOWN")
        self.assertIs(row["oversold_flag"], expected)
        self.assertTrue(result["RESEARCH_ONLY"])
        self.assertFalse(result["production_allowed"])
        self.assertFalse(result["buy_gate_updated"])
        self.assertFalse(result["orders_sent"])

    def test_decimal_equality_at_80_percent_is_inclusive(self):
        self.assert_pending_boundary(0.28, 0.35, True)

    def test_second_decimal_equality_is_inclusive(self):
        self.assert_pending_boundary(0.56, 0.70, True)

    def test_above_boundary_does_not_get_tolerance(self):
        self.assert_pending_boundary(0.2800000000000001, 0.35, False)

    def test_below_boundary_passes(self):
        self.assert_pending_boundary(0.2799999999999999, 0.35, True)

    def test_missing_close_remains_unknown(self):
        self.assert_pending_boundary(None, 0.35, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
