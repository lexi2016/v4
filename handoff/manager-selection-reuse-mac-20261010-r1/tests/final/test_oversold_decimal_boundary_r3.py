from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import v4.manager_research.workspace_plan as workspace_plan


def _prior_weekdays(count: int = 60) -> list[str]:
    cursor = date(2026, 10, 8)
    sessions = []
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    return list(reversed(sessions))


def test_exact_80_percent_price_boundary_remains_inclusive(monkeypatch) -> None:
    day = "20261009"
    prior60 = _prior_weekdays()
    code = "HK.00001"
    frame = pd.DataFrame([
        {
            "trade_date_compact": session,
            "code_norm": code,
            "name": "synthetic boundary",
            "open": 0.25,
            "high": 0.29,
            "low": 0.24,
            "close": 0.25,
            "amount": 1000.0,
            "trade": 10.0,
            "pre_close": 0.25,
        }
        for session in prior60
    ] + [{
        "trade_date_compact": day,
        "code_norm": code,
        "name": "synthetic boundary",
        "open": 0.23,
        "high": 0.24,
        "low": 0.20,
        "close": 0.232,
        "amount": 1000.0,
        "trade": 15.0,
        "pre_close": 0.25,
    }])
    panel = {
        "owner": "SYNTHETIC_PANEL",
        "panel_path": "synthetic-panel.parquet",
        "panel_sha256": "b" * 64,
        "panel_manifest_path": "synthetic-panel-manifest.json",
        "panel_manifest_sha256": "a" * 64,
        "panel_available_at": "2026-10-09T08:00:00+00:00",
        "panel_max_date": day,
        "panel_rows": len(frame),
        "panel_code_count": 1,
        "source_contract": "synthetic-test-only",
        "price_currency": "HKD",
        "price_basis": "RAW",
        "session_kind": "FULL_DAY_CLOSE",
        "amount_unit": "HKD",
    }
    master = {
        "owner": "SYNTHETIC_MASTER",
        "artifact_path": "synthetic-master.csv",
        "artifact_sha256": "d" * 64,
        "manifest_path": "synthetic-master-manifest.json",
        "manifest_sha256": "c" * 64,
        "run_id": "synthetic-master",
        "row_count": 1,
        "captured_at": "2026-10-09T08:00:00+00:00",
        "names": {code: {"name": "synthetic boundary"}},
    }
    sessions = {
        "prior60": prior60,
        "previous5": prior60[-5:],
        "panel_session": prior60[0],
        "calendar_sha256": "e" * 64,
    }
    monkeypatch.setattr(workspace_plan, "screen_context", lambda context: {
        **context,
        "market_session": day,
        "plan_trade_date": "20261012",
        "research_cutoff": "2026-10-11T15:00:00+00:00",
        "screen_phase": "PREOPEN_PLAN",
        "screen_session_policy": "LATEST_COMPLETED_FULL_HK_SESSION_ONLY",
    })
    monkeypatch.setattr(workspace_plan, "rebound_history_sessions", lambda *_: sessions)
    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness", lambda *_args, **_kwargs: (panel, []))
    monkeypatch.setattr(workspace_plan, "_screen_security_master_witness", lambda *_: (master, {}))
    monkeypatch.setattr(workspace_plan, "_screen_panel_volume_evidence", lambda *_: {
        "status": "OWNER_VERIFIED",
        "unit_status": "OWNER_VERIFIED",
        "unit": "synthetic-test-only",
        "scale_applied": 1,
        "source": "SYNTHETIC_PANEL",
        "native_field": "trade",
        "required_sessions": [*prior60[-5:], day],
        "gaps": [],
    })
    monkeypatch.setattr(pd, "read_parquet", lambda _path, columns=None: frame.loc[:, columns].copy())

    result = workspace_plan.read_rebound_screen(Path("/synthetic/authority"), {
        "market_session": day,
        "plan_trade_date": "20261012",
        "research_cutoff": "2026-10-11T15:00:00+00:00",
    })

    assert result["coverage"]["strict_count"] == 1
    row = result["strict"][0]
    assert row["prior60_session_high"] == 0.29
    assert row["oversold_cutoff_80pct_prior60_high"] == 0.232
    assert row["oversold_flag"] is True
