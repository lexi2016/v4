"""Offline acceptance checks for the HK0.2 daily-supplement sidecar."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import itertools
import json
import sys
from pathlib import Path
import types

import pandas as pd
import pytest

from upstreams.v3_shared_data.shared_data import hk_daily_supplement as supplement
from upstreams.v3_shared_data.scripts import update_hk_0_2_panel
from v4.manager_research import workspace_plan


TARGET = "20260930"
SESSIONS = ["20260923", "20260924", "20260925", "20260928", "20260929", TARGET]
PANEL_ID = {
    "panel_manifest_relative": "assets/hk_0_2/panels/panel/manifest.json",
    "panel_manifest_sha256": "a" * 64,
    "panel_relative": "assets/hk_0_2/panels/panel/hkconnect_vipdoc_daily_panel.parquet",
    "panel_sha256": "b" * 64,
    "panel_max_date": TARGET,
    "manifest_prepared_at": "2026-09-30T02:00:00+00:00",
}
MASTER_CODES = ["HK.00001", "HK.00002"]
MASTER_ID = {
    "manifest_relative": "assets/hk_security_master/runs/master/manifest.json",
    "manifest_sha256": "c" * 64,
    "artifact_relative": "assets/hk_security_master/runs/master/artifact.csv",
    "artifact_sha256": "d" * 64,
    "run_id": "master",
    "trade_date": TARGET,
    "row_count": 2,
    "captured_at": "2026-09-30T02:01:00+00:00",
    "universe_codes_sha256": hashlib.sha256(
        json.dumps(MASTER_CODES, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()
    ).hexdigest(),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bar(day: str, *, trade: int = 10, high: float = 80) -> dict:
    parsed = datetime.strptime(day, "%Y%m%d")
    return {
        "datetime": parsed.strftime("%Y-%m-%d 15:00"),
        "open": 70.0, "high": high, "low": 69.0, "close": 70.0,
        "trade": trade, "amount": 12345.0,
    }


def _clock(start: datetime):
    counter = itertools.count()
    return lambda: start + timedelta(seconds=next(counter))


class FakeAPI:
    def __init__(self, *, variant: str = "missing_target"):
        self.variant = variant
        self.disconnected = False
        self.calls: list[tuple] = []

    def get_instrument_bars(self, category, market, code, start, count):
        self.calls.append((category, market, code, start, count))
        rows = [_bar(day, trade=10 + index) for index, day in enumerate(SESSIONS)]
        if code == "00002" and self.variant == "missing_target":
            rows = rows[:-1]
        elif code == "00002" and self.variant == "duplicate":
            rows.append(dict(rows[-1]))
        elif code == "00002" and self.variant == "future":
            rows.append(_bar("20261001"))
        return rows

    def disconnect(self):
        self.disconnected = True


def _patch_capture_inputs(monkeypatch, codes=MASTER_CODES):
    identity = dict(MASTER_ID)
    identity["row_count"] = len(codes)
    identity["universe_codes_sha256"] = hashlib.sha256(
        json.dumps(sorted(codes), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(supplement, "requested_sessions", lambda day: (SESSIONS, "e" * 64))
    monkeypatch.setattr(supplement, "_read_panel_identity", lambda root, day: dict(PANEL_ID))
    monkeypatch.setattr(supplement, "_read_master_identity", lambda root, day: (identity, sorted(codes)))
    return identity


def _read(root: Path, *, cutoff: str, master_id: dict | None = None,
          codes: list[str] | None = None):
    return supplement.read_verified_daily_supplement(
        root, target_date=TARGET, requested=SESSIONS, research_cutoff=cutoff,
        expected_panel=PANEL_ID,
        expected_master=master_id or MASTER_ID,
        expected_codes=codes or MASTER_CODES,
    )


def test_capture_publishes_only_sidecar_and_missing_target_stays_pending(tmp_path, monkeypatch):
    root = tmp_path / "authority"
    _patch_capture_inputs(monkeypatch)
    api = FakeAPI()
    start = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
    outcome = supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"), clock=_clock(start),
    )
    assert outcome["status"] == "PARTIAL_WITH_PENDING"
    assert outcome["record_status_counts"] == {"PENDING": 1, "READY": 1}
    assert api.disconnected is True
    assert api.calls == [(4, 71, "00001", 0, 6), (4, 71, "00002", 0, 6)]
    assert not (root / "assets" / "hk_0_2" / "panel_latest.json").exists()

    result = _read(root, cutoff="2026-10-01T03:01:00+00:00")
    assert result is not None
    assert result["manifest"]["calendar_sha256"] == "e" * 64
    assert result["manifest"]["record_status_counts"] == {"PENDING": 1, "READY": 1}
    assert result["records"]["HK.00001"]["status"] == "READY"
    assert result["records"]["HK.00002"]["status"] == "PENDING"
    assert result["records"]["HK.00002"]["missing_sessions"] == [TARGET]
    native = result["records"]["HK.00001"]["bars"][0]["native_fields"]
    assert native == {
        "volume_field": "trade", "amount_field": "amount", "scale_applied": 1,
        "volume_unit": None, "volume_unit_status": "NOT_PROVEN", "price_basis": "NOT_PROVEN",
    }
    assert result["manifest"]["capture_started_at"] == "2026-10-01T03:00:00.000000+00:00"
    assert result["manifest"]["prepared_at"] == "2026-10-01T03:00:07.000000+00:00"
    assert result["pointer"]["published_at"] == "2026-10-01T03:00:08.000000+00:00"

    pointer_path = root / "assets" / "hk_0_2" / "daily_supplements" / "pointers" / f"{TARGET}.json"
    first_pointer = json.loads(pointer_path.read_bytes())
    old_manifest = (root / "assets" / "hk_0_2" / first_pointer["manifest_relative"]).read_bytes()
    old_capture = (root / "assets" / "hk_0_2" / first_pointer["raw_capture_relative"]).read_bytes()
    later_api = FakeAPI()
    later_start = datetime(2026, 10, 1, 3, 10, tzinfo=timezone.utc)
    second = supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (later_api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"), clock=_clock(later_start),
    )
    second_pointer = json.loads(pointer_path.read_bytes())
    assert second["run_id"] != outcome["run_id"]
    assert second_pointer["previous_manifest_sha256"] == _sha(
        root / "assets" / "hk_0_2" / first_pointer["manifest_relative"]
    )
    assert (root / "assets" / "hk_0_2" / first_pointer["manifest_relative"]).read_bytes() == old_manifest
    assert (root / "assets" / "hk_0_2" / first_pointer["raw_capture_relative"]).read_bytes() == old_capture
    assert _read(root, cutoff="2026-10-01T03:11:00+00:00") is not None


@pytest.mark.parametrize("variant", ["duplicate", "future"])
def test_duplicate_or_future_rows_fail_closed_for_code(tmp_path, monkeypatch, variant):
    _patch_capture_inputs(monkeypatch)
    api = FakeAPI(variant=variant)
    outcome = supplement.capture_daily_supplement(
        tmp_path / "authority", target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )
    result = _read(tmp_path / "authority", cutoff="2026-10-01T03:01:00+00:00")
    assert outcome["status"] == "PARTIAL_WITH_PENDING"
    record = result["records"]["HK.00002"]
    assert record["status"] == "INVALID"
    assert record["bars"] == []
    assert record["error_code"] in {
        "HK_DAILY_SUPPLEMENT_DUPLICATE_DATE", "HK_DAILY_SUPPLEMENT_FUTURE_ROW",
    }


def test_capture_records_actual_later_times_and_consumer_cutoff_is_separate(tmp_path, monkeypatch):
    _patch_capture_inputs(monkeypatch)
    api = FakeAPI()
    root = tmp_path / "authority"
    outcome = supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 10, tzinfo=timezone.utc)),
    )
    assert api.disconnected is True
    assert outcome["status"] == "PARTIAL_WITH_PENDING"
    assert _read(root, cutoff="2026-10-01T03:11:00+00:00") is not None
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF"):
        _read(root, cutoff="2026-10-01T03:09:59+00:00")


def test_capture_reuses_verified_ready_cache_without_connector_or_republication(tmp_path, monkeypatch):
    _patch_capture_inputs(monkeypatch)
    root = tmp_path / "authority"
    api = FakeAPI(variant="complete")
    first = supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )
    assert first["status"] == "READY"
    pointer_path = root / "assets" / "hk_0_2" / "daily_supplements" / "pointers" / f"{TARGET}.json"
    pointer_bytes = pointer_path.read_bytes()
    calls_before = list(api.calls)

    second = supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: pytest.fail("verified READY cache must bypass the provider"),
        clock=_clock(datetime(2026, 10, 1, 3, 10, tzinfo=timezone.utc)),
    )

    assert second["status"] == "READY" and second["reused"] is True
    assert second["run_id"] == first["run_id"]
    assert second["published_at"] == first["published_at"]
    assert pointer_path.read_bytes() == pointer_bytes
    assert api.calls == calls_before


def test_capture_rejects_parent_revision_published_after_actual_capture_start(tmp_path, monkeypatch):
    _patch_capture_inputs(monkeypatch)
    panel = dict(PANEL_ID, manifest_prepared_at="2026-10-01T03:00:01+00:00")
    monkeypatch.setattr(supplement, "_read_panel_identity", lambda *_: panel)
    connector = lambda: pytest.fail("parent-time validation must precede provider connection")
    root = tmp_path / "authority"
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_PARENT_AFTER_CAPTURE_START"):
        supplement.capture_daily_supplement(
            root, target_date=TARGET, connector=connector,
            clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
        )
    assert not (root / "assets" / "hk_0_2").exists()


def test_reader_rejects_pointer_published_after_cutoff(tmp_path, monkeypatch):
    _patch_capture_inputs(monkeypatch)
    api = FakeAPI()
    root = tmp_path / "authority"
    supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )
    pointer_path = root / "assets" / "hk_0_2" / "daily_supplements" / "pointers" / f"{TARGET}.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["published_at"] = "2026-10-01T03:02:00+00:00"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF"):
        _read(root, cutoff="2026-10-01T03:01:00+00:00")


def test_reader_rejects_a_noncanonical_six_session_request(tmp_path, monkeypatch):
    _patch_capture_inputs(monkeypatch)
    api = FakeAPI()
    root = tmp_path / "authority"
    supplement.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )
    monkeypatch.setattr(supplement, "requested_sessions",
                        lambda day: ([*SESSIONS[:-1], "20261001"], "e" * 64))
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_REQUESTED_SESSIONS_INVALID"):
        _read(root, cutoff="2026-10-01T03:01:00+00:00")


def test_explicit_updater_uses_market_session_and_normalizes_bounded_canary_codes(
    tmp_path, monkeypatch, capsys,
):
    asset_root = tmp_path / "authority" / "assets" / "hk_0_2"
    calls = {}

    def capture(authority_root, *, target_date, canary_codes):
        calls.update(authority_root=authority_root, target_date=target_date,
                     canary_codes=canary_codes)
        return {"status": "CANARY_STAGED"}

    fake_module = types.SimpleNamespace(
        capture_daily_supplement=capture,
        normalize_canary_codes=supplement.normalize_canary_codes,
    )
    monkeypatch.setitem(sys.modules, "shared_data.hk_daily_supplement", fake_module)
    monkeypatch.setattr(sys, "argv", [
        "update_hk_0_2_panel.py", "--asset-root", str(asset_root),
        "--tdx-root", str(tmp_path / "vipdoc"), "--through-date", TARGET,
        "--daily-supplement", "--canary-codes", "00002,HK.00001",
    ])
    monkeypatch.setattr(update_hk_0_2_panel, "update_hk_0_2_panel_from_vipdoc",
                        lambda *_args, **_kwargs: pytest.fail("normal panel updater must not run"))

    assert update_hk_0_2_panel.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "CANARY_STAGED"
    assert calls["target_date"] == "20260930"  # exact owner market_session, not plan trade date
    assert calls["canary_codes"] == ["HK.00001", "HK.00002"]
    assert not asset_root.exists()


def test_canary_capture_is_a_bounded_subset_with_no_consumer_pointer(tmp_path, monkeypatch):
    full_codes = ["HK.00001", "HK.00002", "HK.00005", "HK.00700", "HK.00941"]
    master_identity = _patch_capture_inputs(monkeypatch, codes=full_codes)
    api = FakeAPI()
    root = tmp_path / "authority"
    result = supplement.capture_daily_supplement(
        root, target_date=TARGET, canary_codes=["00005", "HK.00002"],
        connector=lambda: (api, f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )

    assert result["status"] == "CANARY_STAGED"
    assert result["publication_status"] == "CANARY_STAGED_NOT_CONSUMER_READABLE"
    assert result["capture_status"] == "PARTIAL_WITH_PENDING"
    assert result["selected_codes"] == ["HK.00002", "HK.00005"]
    assert result["code_count"] == 2 and result["master_code_count"] == 5
    assert api.calls == [(4, 71, "00002", 0, 6), (4, 71, "00005", 0, 6)]

    asset_root = root / "assets" / "hk_0_2"
    assert not (asset_root / "daily_supplements" / "pointers" / f"{TARGET}.json").exists()
    manifest_path = asset_root / result["manifest_relative"]
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["capture_scope"] == "CANARY"
    assert manifest["publication_status"] == "CANARY_STAGED_NOT_CONSUMER_READABLE"
    assert manifest["selected_codes"] == ["HK.00002", "HK.00005"]
    assert manifest["master_code_count"] == 5
    assert manifest["universe_codes_sha256"] == master_identity["universe_codes_sha256"]
    assert manifest["staged_at"] > manifest["prepared_at"]
    assert _read(root, cutoff="2026-10-01T03:01:00+00:00", codes=full_codes) is None


@pytest.mark.parametrize(("canary_codes", "error"), [
    (["00001", "HK.00001"], "HK_DAILY_SUPPLEMENT_CANARY_CODES_DUPLICATE"),
    (["00001", "00002", "00005", "00700"], "HK_DAILY_SUPPLEMENT_CANARY_CODES_LIMIT_EXCEEDED"),
    (["00006"], "HK_DAILY_SUPPLEMENT_CANARY_CODE_OUTSIDE_MASTER"),
])
def test_invalid_canary_selection_fails_before_connect_or_write(tmp_path, monkeypatch,
                                                                 canary_codes, error):
    _patch_capture_inputs(monkeypatch)
    connector = lambda: pytest.fail("invalid canary must fail before provider connection")
    root = tmp_path / "authority"
    with pytest.raises(ValueError, match=error):
        supplement.capture_daily_supplement(root, target_date=TARGET,
                                             canary_codes=canary_codes,
                                             connector=connector)
    assert not (root / "assets" / "hk_0_2").exists()


def _supplement_bar(day: str, trade: float, *, high: float = 80.0,
                    close: float = 70.0, low: float = 69.0, amount: float | None = 88888.0):
    return {"trade_date": day, "open": 70.0, "high": high, "low": low,
            "close": close, "trade": trade, "amount": amount,
            "native_fields": {"volume_field": "trade", "amount_field": "amount",
                              "scale_applied": 1, "volume_unit": None,
                              "volume_unit_status": "NOT_PROVEN",
                              "price_basis": "NOT_PROVEN"}}


def test_screen_uses_master_universe_sidecar_volume_and_missing_only_price_overlay(monkeypatch):
    day = TARGET
    prior60 = [(date(2026, 7, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(60)]
    previous5 = prior60[-5:]
    codes = ["HK.00001", "HK.00002", "HK.00003"]
    names = {code: {"name": f"Verified {code}"} for code in codes}
    master = {"owner": "FIXTURE_MASTER", "artifact_path": "master.csv",
              "artifact_sha256": "d" * 64, "manifest_path": "master.json",
              "manifest_sha256": "c" * 64, "run_id": "m", "row_count": 3,
              "captured_at": "2026-09-30T12:00:00+00:00", "names": names}
    panel = {"owner": "FIXTURE_PANEL", "panel_path": "panel.parquet",
             "panel_sha256": "b" * 64, "panel_manifest_path": "panel.json",
             "panel_manifest_sha256": "a" * 64, "panel_max_date": day,
             "panel_rows": 180, "panel_code_count": 4,
             "source_contract": "fixture", "price_currency": "HKD",
             "price_basis": "RAW", "session_kind": "FULL_DAY_CLOSE", "amount_unit": "HKD"}
    rows = []
    for code in codes:
        for index, session in enumerate(prior60):
            if code == "HK.00002" and session == previous5[-1]:
                continue
            rows.append({"trade_date_compact": session, "code_norm": code, "name": code,
                         "open": 70.0, "high": 100.0, "low": 60.0, "close": 70.0,
                         "amount": 1000.0, "trade": 99999.0, "pre_close": 70.0})
    # Existing prices are kept when sidecar differs. Missing target OHLC is
    # filled from the sidecar, but target amount remains the panel value.
    rows.append({"trade_date_compact": day, "code_norm": "HK.00001", "name": "old name",
                 "open": float("nan"), "high": float("nan"), "low": float("nan"),
                 "close": float("nan"), "amount": 12345.0, "trade": 999999.0,
                 "pre_close": 69.0})
    rows.append({"trade_date_compact": day, "code_norm": "HK.99999", "name": "panel only",
                 "open": 70.0, "high": 90.0, "low": 69.0, "close": 70.0,
                 "amount": 1.0, "trade": 100.0, "pre_close": 70.0})
    frame = pd.DataFrame(rows)
    bar_map = {}
    for code in codes:
        by_date = {session: _supplement_bar(session, 10.0, high=150.0)
                   for session in previous5}
        by_date[day] = _supplement_bar(day, 15.0, high=90.0, close=70.0,
                                       low=69.0, amount=999999.0)
        bar_map[code] = by_date
    # Code 2 has a missing panel previous-five row, filled from the exact
    # sidecar. Code 3 deliberately has no target bar and remains pending.
    bar_map["HK.00003"].pop(day)
    records = {
        code: {"status": "READY" if day in bars else "PENDING",
               "bars": list(bars.values()), "error_code": None}
        for code, bars in bar_map.items()
    }
    pointer = {"raw_capture_relative": "daily_supplements/runs/r/raw_capture.json",
               "manifest_relative": "daily_supplements/runs/r/manifest.json"}
    manifest_sha = "f" * 64
    capture_sha = "1" * 64
    supplement_witness = {"status": "PARTIAL_WITH_PENDING", "records": records,
                          "pointer": pointer, "manifest_sha256": manifest_sha,
                          "raw_capture_sha256": capture_sha}
    sessions = {"prior60": prior60, "previous5": previous5,
                "panel_session": prior60[0], "calendar_sha256": "e" * 64}
    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness", lambda *_: (panel, []))
    monkeypatch.setattr(workspace_plan, "_screen_security_master_witness", lambda *_: (master, {}))
    monkeypatch.setattr(workspace_plan, "rebound_history_sessions", lambda *_: sessions)
    monkeypatch.setattr(workspace_plan, "_read_hk02_daily_supplement_witness",
                        lambda *_: supplement_witness)
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: frame.copy())

    result = workspace_plan.read_rebound_screen(Path("/fixture/authority"), {
        "market_session": day, "plan_trade_date": "20261002",
        "research_cutoff": "2026-10-01T03:00:00+00:00",
    })
    assert result["coverage"]["input_candidate_count"] == 3
    assert result["coverage"]["master_universe_count"] == 3
    assert result["coverage"]["panel_only_excluded_codes"] == ["HK.99999"]
    assert result["coverage"]["history_pending_count"] == 1
    assert result["pending"][0]["code"] == "HK.00003"
    row1 = next(row for row in result["cards"] if row["code"] == "HK.00001")
    row2 = next(row for row in result["cards"] if row["code"] == "HK.00002")
    assert row1["current_volume"] == 15.0
    assert row1["previous5_mean_volume"] == 10.0
    assert row1["volume_ratio_5d"] == 1.5
    assert row1["volume_flag_5d_ge_1_5"] is True
    assert row1["prior60_session_high"] == 100.0  # existing panel highs beat sidecar 150
    assert row1["amount_hkd"] == 12345.0  # no sidecar amount substitution
    assert row2["amount_hkd"] is None  # synthesized target has unknown amount
    assert row2["current_volume"] == 15.0
    assert row2["prior60_session_count"] == 60  # one missing prior-five price row was overlaid
    assert row2["background20_status"] == "NOT_CAPTURED_IN_SIX_BAR_SUPPLEMENT"
    assert all(row["volume_scale_applied"] == 1 and row["volume_unit_status"] == "NOT_PROVEN"
               for row in result["cards"])


def test_complete_panel_history_skips_sidecar_and_preserves_canonical_baseline(monkeypatch):
    day = TARGET
    prior60 = [(date(2026, 7, 1) + timedelta(days=index)).strftime("%Y%m%d")
               for index in range(60)]
    previous5 = prior60[-5:]
    code = "HK.00001"
    frame = pd.DataFrame([
        {"trade_date_compact": session, "code_norm": code, "name": "Canonical",
         "open": 70.0, "high": 100.0, "low": 60.0, "close": 70.0,
         "amount": 1000.0, "trade": 10.0, "pre_close": 70.0}
        for session in prior60
    ] + [{"trade_date_compact": day, "code_norm": code, "name": "Canonical",
          "open": 70.0, "high": 90.0, "low": 69.0, "close": 70.0,
          "amount": 12345.0, "trade": 15.0, "pre_close": 70.0}])
    panel = {"owner": "FIXTURE_PANEL", "panel_path": "panel.parquet",
             "panel_sha256": "b" * 64, "panel_manifest_path": "panel.json",
             "panel_manifest_sha256": "a" * 64, "panel_max_date": day,
             "panel_rows": len(frame), "panel_code_count": 1,
             "source_contract": "fixture", "price_currency": "HKD",
             "price_basis": "RAW", "session_kind": "FULL_DAY_CLOSE", "amount_unit": "HKD"}
    master = {"owner": "FIXTURE_MASTER", "artifact_path": "master.csv",
              "artifact_sha256": "d" * 64, "manifest_path": "master.json",
              "manifest_sha256": "c" * 64, "run_id": "m", "row_count": 1,
              "captured_at": "2026-09-30T12:00:00+00:00",
              "names": {code: {"name": "Canonical"}}}
    sessions = {"prior60": prior60, "previous5": previous5,
                "panel_session": prior60[0], "calendar_sha256": "e" * 64}
    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness", lambda *_: (panel, []))
    monkeypatch.setattr(workspace_plan, "_screen_security_master_witness", lambda *_: (master, {}))
    monkeypatch.setattr(workspace_plan, "rebound_history_sessions", lambda *_: sessions)
    monkeypatch.setattr(workspace_plan, "_read_hk02_daily_supplement_witness",
                        lambda *_: pytest.fail("canonical complete panel must not read sidecar"))
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: frame.copy())

    result = workspace_plan.read_rebound_screen(Path("/fixture/authority"), {
        "market_session": day, "plan_trade_date": "20261002",
        "research_cutoff": "2026-10-01T03:00:00+00:00",
    })
    assert result["coverage"]["input_candidate_count"] == 1
    assert result["coverage"]["history_complete_count"] == 1
    assert result["coverage"]["history_pending_count"] == 0
    row = result["cards"][0]
    assert row["history_source"] == "V4_SHARED_HK_0_2_PANEL_AUTHORITY"
    assert row["volume_source"] == "V4_SHARED_HK_0_2_PANEL_AUTHORITY"
    assert row["current_volume"] == 15.0
    assert row["previous5_mean_volume"] == 10.0
    assert row["volume_ratio_5d"] == 1.5
