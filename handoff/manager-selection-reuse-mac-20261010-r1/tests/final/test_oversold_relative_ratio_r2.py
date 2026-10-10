from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import v4.manager_research.workspace_plan as workspace_plan


DAY = "20261009"
TARGET = "20261012"
AUTHORITY_ROOT = Path("/synthetic/authority")


def _prior_weekdays(count: int = 60) -> list[str]:
    cursor = date(2026, 10, 9) - timedelta(days=1)
    sessions = []
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    return list(reversed(sessions))


def _sidecar_bar(session: str, volume: float) -> dict:
    return {
        "trade_date": session,
        "open": 80.0,
        "high": 100.0,
        "low": 78.0,
        "close": 79.0,
        "trade": volume,
        "amount": None,
        "native_fields": {
            "volume_field": "trade",
            "amount_field": "amount",
            "scale_applied": 1,
            "volume_unit": None,
            "volume_unit_status": "NOT_PROVEN",
        },
    }


def test_same_response_supplement_ratio_reenters_two_gate_screen_but_unit_stays_unknown(monkeypatch):
    prior60 = _prior_weekdays()
    previous5 = prior60[-5:]
    codes = ["HK.01001", "HK.01002", "HK.01003", "HK.01004"]
    names = {code: {"name": f"{code} synthetic"} for code in codes}
    panel = {
        "owner": "SYNTHETIC_PANEL",
        "panel_path": "synthetic-panel.parquet",
        "panel_sha256": "b" * 64,
        "panel_manifest_path": "synthetic-panel-manifest.json",
        "panel_manifest_sha256": "a" * 64,
        "panel_available_at": "2026-10-09T08:00:00+00:00",
        "panel_max_date": DAY,
        "panel_rows": 244,
        "panel_code_count": 4,
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
        "row_count": 4,
        "captured_at": "2026-10-09T08:00:00+00:00",
        "names": names,
    }
    rows = []
    for code in codes:
        for session in prior60:
            rows.append({
                "trade_date_compact": session,
                "code_norm": code,
                "name": names[code]["name"],
                "open": 80.0,
                "high": 100.0,
                "low": 78.0,
                "close": 80.0,
                "amount": 1000.0,
                "trade": (None if code != codes[3] and session == previous5[-1] else 10.0),
                "pre_close": 80.0,
            })
        close = 79.0 if code in {codes[0], codes[2], codes[3]} else 81.0
        rows.append({
            "trade_date_compact": DAY,
            "code_norm": code,
            "name": names[code]["name"],
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "amount": 12345.0,
            "trade": 15.0 if code == codes[3] else None,
            "pre_close": close + 1.0,
        })
    frame = pd.DataFrame(rows)

    ready_records = {}
    for code in codes[:2]:
        bars = [_sidecar_bar(session, 10.0) for session in previous5]
        bars.append(_sidecar_bar(DAY, 15.0))
        ready_records[code] = {
            "status": "READY",
            "request_sha256": ("1" if code == codes[0] else "2") * 64,
            "response_sha256": ("3" if code == codes[0] else "4") * 64,
            "bars": bars,
            "error_code": None,
        }
    ready_records[codes[2]] = {
        "status": "PENDING",
        "request_sha256": "5" * 64,
        "response_sha256": "6" * 64,
        "bars": [_sidecar_bar(session, 10.0) for session in previous5],
        "error_code": None,
    }
    supplement = {
        "status": "PARTIAL_WITH_PENDING",
        "target_date": DAY,
        "manifest_sha256": "7" * 64,
        "raw_capture_sha256": "8" * 64,
        "manifest": {
            "run_id": "synthetic-run",
            "method": "get_instrument_bars",
            "category": 4,
            "market": 71,
        },
        "pointer": {
            "raw_capture_relative": "daily_supplements/runs/synthetic/raw.json",
            "manifest_relative": "daily_supplements/runs/synthetic/manifest.json",
        },
        "records": ready_records,
    }
    sessions = {
        "prior60": prior60,
        "previous5": previous5,
        "panel_session": prior60[0],
        "calendar_sha256": "e" * 64,
    }
    panel_volume = {
        "status": "NOT_PROVEN",
        "unit_status": "NOT_PROVEN",
        "unit": None,
        "scale_applied": None,
        "source": "SYNTHETIC_PANEL",
        "native_field": "trade",
        "required_sessions": [*previous5, DAY],
        "gaps": ["SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN"],
    }
    monkeypatch.setattr(workspace_plan, "screen_context", lambda context: {
        **context,
        "market_session": DAY,
        "plan_trade_date": TARGET,
        "research_cutoff": "2026-10-11T15:00:00+00:00",
        "screen_phase": "PREOPEN_PLAN",
        "screen_session_policy": "LATEST_COMPLETED_FULL_HK_SESSION_ONLY",
    })
    monkeypatch.setattr(workspace_plan, "rebound_history_sessions", lambda *_: sessions)
    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness", lambda *_args, **_kwargs: (panel, []))
    monkeypatch.setattr(workspace_plan, "_screen_security_master_witness", lambda *_: (master, {}))
    monkeypatch.setattr(workspace_plan, "_screen_panel_volume_evidence", lambda *_: panel_volume)
    monkeypatch.setattr(workspace_plan, "_read_hk02_daily_supplement_witness", lambda *_: supplement)
    monkeypatch.setattr(pd, "read_parquet", lambda _path, columns=None: frame.loc[:, columns].copy())

    result = workspace_plan.read_rebound_screen(AUTHORITY_ROOT, {
        "market_session": DAY,
        "plan_trade_date": TARGET,
        "research_cutoff": "2026-10-11T15:00:00+00:00",
    })

    assert result["coverage"]["input_candidate_count"] == 4
    assert result["coverage"]["strict_count"] == 1
    assert result["coverage"]["near_count"] == 1
    assert result["coverage"]["history_pending_count"] == 2
    assert {row["code"] for row in result["strict"]} == {codes[0]}
    assert {row["code"] for row in result["near"]} == {codes[1]}
    assert {row["code"] for row in result["pending"]} == {codes[2], codes[3]}

    strict = result["strict"][0]
    assert strict["volume_ratio_5d"] == 1.5
    assert strict["volume_flag_5d_ge_1_5"] is True
    assert strict["oversold_cutoff_80pct_prior60_high"] == 80.0
    assert strict["volume_ratio_status"] == "RELATIVE_RATIO_ONLY_UNIT_UNKNOWN"
    assert strict["volume_relative_comparability_status"] == "VERIFIED_SAME_RESPONSE_RAW_FIELD_UNIT_UNKNOWN"
    assert strict["volume_unit_status"] == "NOT_PROVEN"
    assert strict["volume_provenance"]["unit"] is None
    assert strict["volume_provenance"]["source_run_id"] == "synthetic-run"
    assert strict["volume_provenance"]["request_sha256"] == "1" * 64
    assert strict["volume_provenance"]["response_sha256"] == "3" * 64
    assert strict["volume_provenance"]["required_sessions"] == [*previous5, DAY]

    near = result["near"][0]
    assert near["near_failed_gate"] == "oversold_close_le_80pct_prior60_high"
    assert near["volume_flag_5d_ge_1_5"] is True

    pending_missing_target = next(row for row in result["pending"] if row["code"] == codes[2])
    assert pending_missing_target["current_volume"] is None
    assert pending_missing_target["volume_flag_5d_ge_1_5"] is None
    assert pending_missing_target["history_status"] == "PARTIAL_UNKNOWN"

    # The complete panel-only row has numeric values but no inherited-history
    # unit/scale attestation, so it cannot qualify on its apparent 1.5 ratio.
    pending_panel = next(row for row in result["pending"] if row["code"] == codes[3])
    assert pending_panel["volume_ratio_5d"] == 1.5
    assert pending_panel["volume_flag_5d_ge_1_5"] is None
    assert pending_panel["volume_unit_status"] == "NOT_PROVEN"
    assert pending_panel["history_status"] == "PARTIAL_UNKNOWN"
