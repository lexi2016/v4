"""Synthetic behavior regression for the canonical rebound-screen cutoff."""
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd

from v4.manager_research import workspace_plan as wp


def run_screen(close, prior_high, module=wp):
    day = "20261009"
    prior_dates = [(date(2026, 10, 9) - timedelta(days=n)).strftime("%Y%m%d")
                   for n in range(60, 0, -1)]
    symbol = "HK.00001"
    context = {
        "plan_trade_date": day,
        "market_session": day,
        "research_cutoff": None,
    }
    sessions = {
        "prior60": prior_dates,
        "previous5": prior_dates[-5:],
        "calendar_sha256": "c" * 64,
    }
    rows = [
        {
            "trade_date_compact": session,
            "code_norm": symbol,
            "name": "SYNTHETIC ONLY",
            "open": 0.30,
            "high": prior_high,
            "low": 0.27,
            "close": 0.30,
            "amount": 1.0,
            "trade": 100.0,
            "pre_close": 0.30,
        }
        for session in prior_dates
    ]
    rows.append({
        "trade_date_compact": day,
        "code_norm": symbol,
        "name": "SYNTHETIC ONLY",
        "open": 0.28,
        "high": 0.30,
        "low": 0.27,
        "close": close,
        "amount": 1.0,
        "trade": 1.0,
        "pre_close": 0.30,
    })
    panel = {
        "owner": "SYNTHETIC_OWNER_BOUNDARY",
        "panel_path": "/synthetic/panel",
        "panel_sha256": "1" * 64,
        "panel_manifest_path": "/synthetic/manifest",
        "panel_manifest_sha256": "2" * 64,
        "panel_rows": 61,
        "panel_code_count": 1,
        "source_contract": "SYNTHETIC_OWNER_BOUNDARY",
        "amount_unit": "HKD",
        "price_basis": "RAW",
        "session_kind": "FULL_DAY_CLOSE",
    }
    master = {
        "owner": "SYNTHETIC_MASTER_BOUNDARY",
        "manifest_sha256": "4" * 64,
        "artifact_path": "/synthetic/master",
        "artifact_sha256": "3" * 64,
        "manifest_path": "/synthetic/master_manifest",
        "names": {symbol: {"name": "SYNTHETIC ONLY"}},
    }
    frame = pd.DataFrame(rows)
    with (
        patch.object(module, "rebound_history_sessions", return_value=sessions),
        patch.object(module, "_read_hk02_panel_witness", return_value=(panel, [])),
        patch.object(module, "_screen_security_master_witness", return_value=(master, {})),
        patch.object(pd, "read_parquet", return_value=frame),
    ):
        result = module.read_rebound_screen(Path("/synthetic"), context)
    assert result["status"] in {"READY", "READY_WITH_GAPS"}, (result["status"], result["gaps"])
    rows = [*result["strict"], *result["near"], *result["pending"],
            *result.get("excluded", []), *result.get("screen_unresolved", [])]
    assert len(rows) == 1, result
    return rows[0]


def test_exact_80_percent_boundary_is_inclusive():
    assert run_screen(0.28, 0.35)["oversold_flag"] is True
    assert run_screen(0.56, 0.70)["oversold_flag"] is True


def test_above_boundary_has_no_tolerance_and_below_passes():
    assert run_screen(0.2800000000000001, 0.35)["oversold_flag"] is False
    assert run_screen(0.2799999999999999, 0.35)["oversold_flag"] is True


def test_missing_close_stays_unknown():
    assert run_screen(None, 0.35)["oversold_flag"] is None


def test_before_snapshot_reproduces_float_equality_failure():
    before = Path("/Users/lexi/Desktop/学习/agents调试/V4_SELECTION_REUSE_REPAIR_MAC_20261010_R1/canonical-integration/before/v4/manager_research/workspace_plan.py")
    spec = importlib.util.spec_from_file_location("v4.manager_research._workspace_plan_before", before)
    assert spec is not None and spec.loader is not None
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    assert run_screen(0.28, 0.35, baseline)["oversold_flag"] is False
