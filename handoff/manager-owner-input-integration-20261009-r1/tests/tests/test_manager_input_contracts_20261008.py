"""Synthetic regression tests for the 20261008 manager input contract repair.

No real market/account fixture or network provider is used. Native owner readers
and sidecar publication operate only under pytest's temporary authority root.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
from pathlib import Path

import pandas as pd
import pytest

from v4.manager_research import connect_selection, workspace_plan
from v3_shared_data.shared_data import hk_daily_supplement as supplement
from v3_shared_data.shared_data.hashing import sha256_json
from v3_shared_data.shared_data.hk_security_master import publish_hk_security_master

DAY = "20261007"
TARGET = "20261008"
CUTOFF = "2026-10-08T08:00:00+08:00"
CODE = "HK.00001"
FALSE_FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _scope(*, target_v2: bool) -> dict:
    codes = [CODE]
    source_date = TARGET if target_v2 else DAY
    source = {
        "market": "HK_CONNECT", "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
        "source_date": source_date, "sha256": "1" * 64,
    }
    scope = {
        "status": "OWNER_VERIFIED", "target_trade_date": TARGET, "source_date": source_date,
        "codes": codes, "source": source, "gaps": [],
        "membership_semantics": ("TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2" if target_v2
            else "EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES"),
    }
    if target_v2:
        source.update(acquired_at="2026-10-08T07:00:00+08:00",
                      available_at="2026-10-08T07:01:00+08:00")
        scope["identity"] = connect_selection.digest([TARGET, codes, source["sha256"]])
        return scope
    source.update(
        dispatch_finished_at="2026-10-07T18:00:00+08:00",
        availability_upper_bound="2026-10-07T18:00:00+08:00",
        availability_semantics="SUCCESSFUL_HK_DISPATCH_FINISH_UPPER_BOUND_FOR_CAPTURE_AVAILABILITY",
        capture_codes_sha256=connect_selection.digest(codes),
    )
    for key in ("capture_manifest_sha256", "panel_receipt_sha256", "panel_summary_sha256",
                "master_manifest_sha256", "master_receipt_sha256",
                "master_artifact_sha256", "dispatch_receipt_sha256"):
        source[key] = "2" * 64
    scope["effective_available_at"] = source["dispatch_finished_at"]
    scope["identity"] = connect_selection.digest([
        TARGET, DAY, codes, source["sha256"], source["capture_manifest_sha256"],
        source["panel_receipt_sha256"], source["master_manifest_sha256"],
        source["master_receipt_sha256"], source["master_artifact_sha256"],
        source["dispatch_receipt_sha256"], source["dispatch_finished_at"],
    ])
    return scope


def _authority(tmp_path: Path, *, close: float = 80.0, volume: float | None = 150.0,
               bare_volume_unit: str | None = None) -> tuple[Path, dict, dict]:
    root = tmp_path / "authority"
    sessions = workspace_plan.rebound_history_sessions(DAY)
    rows = [
        {"trade_date_compact":day, "code_norm":CODE, "name":"Synthetic issuer",
         "open":99.0, "high":100.0, "low":98.0, "close":99.0,
         "amount":10.0, "trade":100.0, "pre_close":99.0}
        for day in sessions["prior60"]
    ]
    rows.append(
        {"trade_date_compact":DAY, "code_norm":CODE, "name":"Synthetic issuer",
         "open":close, "high":close, "low":close-1.0, "close":close,
         "amount":10.0, "trade":volume, "pre_close":99.0})
    frame = pd.DataFrame(rows)
    staging = tmp_path / "synthetic_panel.parquet"
    frame.to_parquet(staging, index=False)
    panel_bytes = staging.read_bytes()
    panel_sha = hashlib.sha256(panel_bytes).hexdigest()
    panel_relative = f"panels/{DAY}-{panel_sha[:12]}/hkconnect_vipdoc_daily_panel.parquet"
    asset = root / "assets" / "hk_0_2"
    panel_path = asset / panel_relative
    panel_path.parent.mkdir(parents=True)
    panel_path.write_bytes(panel_bytes)
    manifest = {
        "asset_schema_version":"v3_shared_data.hk_0_2_panel_asset.v2",
        "source_contract":"tdx_vipdoc_71_day+verified_zero_trade_repairs",
        "panel_relative":panel_relative, "panel_sha256":panel_sha, "panel_max_date":DAY,
        "panel_code_count":1, "panel_rows":len(rows), "research_only":True,
        "manifest_prepared_at":"2026-10-07T18:00:00+08:00", **FALSE_FLAGS,
    }
    if bare_volume_unit is not None:
        manifest["volume_unit"] = bare_volume_unit
    manifest_path = panel_path.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (asset / "panel_latest.json").write_text(json.dumps({
        "manifest_relative":manifest_path.relative_to(asset).as_posix()}), encoding="utf-8")
    publish_hk_security_master(
        root, trade_date=DAY,
        rows=[{"code":CODE, "name":"Synthetic issuer", "outstanding_shares":1000,
               "circular_market_val":100000, "listing_date":"2010-01-01", "lot_size":100,
               "stock_owner":"", "stock_child_type":"", "sec_status":"NORMAL"}],
        universe_codes_sha256=sha256_json([CODE]),
        captured_at="2026-10-07T18:01:00+08:00")
    panel, gaps = workspace_plan._read_hk02_panel_witness(
        root, DAY, research_cutoff=CUTOFF, required_history_date=sessions["previous5"][-1])
    assert panel is not None, gaps
    master, _ = workspace_plan._screen_security_master_witness(root, DAY)
    return root, panel, master


def _clock(start: datetime):
    counter = itertools.count()
    return lambda: start + timedelta(seconds=next(counter))


def _published_sidecar(tmp_path: Path, *, missing_panel_volume: bool = False):
    root, panel, master = _authority(tmp_path, volume=None if missing_panel_volume else 150.0)
    dates, _ = supplement.requested_sessions(DAY)

    class SyntheticAPI:
        def get_instrument_bars(self, category, market, code, start, count):
            assert (category, market, code, start, count) == (4, 71, "00001", 0, 6)
            return [{
                "datetime":datetime.strptime(day, "%Y%m%d").strftime("%Y-%m-%d 16:00"),
                "open":79.0, "high":80.0, "low":78.0, "close":79.0,
                "trade":150 if day == DAY else 100, "amount":10.0,
            } for day in dates]

        def disconnect(self):
            pass

    outcome = supplement.capture_daily_supplement(
        root, target_date=DAY,
        connector=lambda:(SyntheticAPI(), f"{supplement.SOURCE_HOST}:{supplement.SOURCE_PORT}"),
        clock=_clock(datetime(2026, 10, 7, 10, 2, tzinfo=timezone.utc)))
    assert outcome["status"] == "READY"
    return root, panel, master, dates


@pytest.mark.parametrize(
    ("target", "clock", "session", "phase"),
    [
        (TARGET, "2026-10-08T08:00:00+08:00", DAY, "PREOPEN_COMPLETED_SESSION"),
        (TARGET, "2026-10-08T16:09:59+08:00", DAY, "INTRADAY_COMPLETED_SESSION"),
        (TARGET, "2026-10-08T16:10:00+08:00", TARGET, "POST_CLOSE_COMPLETED_SESSION"),
        ("20261009", "2026-10-08T17:00:00+08:00", TARGET, "PREOPEN_COMPLETED_SESSION"),
        ("20261005", "2026-10-05T08:00:00+08:00", "20261002", "PREOPEN_COMPLETED_SESSION"),
        ("20261020", "2026-10-20T08:00:00+08:00", "20261016", "PREOPEN_COMPLETED_SESSION"),
        ("20261224", "2026-12-24T12:10:00+08:00", "20261223", "POST_CLOSE_COMPLETED_SESSION"),
        ("20261228", "2026-12-28T08:00:00+08:00", "20261223", "PREOPEN_COMPLETED_SESSION"),
    ],
)
def test_screen_context_selects_only_completed_full_hk_session(target, clock, session, phase):
    planning = workspace_plan.plan_context(target, now=datetime.fromisoformat(clock))
    original = deepcopy(planning)
    context = workspace_plan.screen_context(planning)
    assert planning == original
    assert context["market_session"] == session
    assert context["screen_phase"] == phase
    assert context["screen_target_trade_date"] == target
    assert context["planning_market_session"] == planning["market_session"]
    assert context["screen_session_policy"] == "COMPLETED_FULL_HK_SECURITIES_SESSION"
    assert datetime.fromisoformat(context["market_session_close"]) <= datetime.fromisoformat(clock)
    assert workspace_plan.screen_context(context) == context


@pytest.mark.parametrize("cutoff", [None, "2026-10-08T08:00:00", "invalid"])
def test_screen_context_requires_aware_cutoff(cutoff):
    with pytest.raises(ValueError, match="SCREEN_RESEARCH_CUTOFF_UNVERIFIED"):
        workspace_plan.screen_context({"plan_trade_date":TARGET, "market_session":DAY,
                                       "research_cutoff":cutoff})


def test_sidecar_accepts_actual_panel_witness_timestamp_and_preserves_unit_unknown(tmp_path):
    root, panel, master, dates = _published_sidecar(tmp_path)
    value = workspace_plan._read_hk02_daily_supplement_witness(
        root, DAY, dates, CUTOFF, panel, master, master["names"])
    assert value is not None and value["status"] == "READY"
    assert value["manifest"]["panel_identity"]["manifest_prepared_at"] == panel["panel_available_at"]
    bar = value["records"][CODE]["bars"][-1]
    assert bar["native_fields"]["volume_unit_status"] == "NOT_PROVEN"
    assert bar["native_fields"]["scale_applied"] == 1
    assert bar["native_fields"]["volume_unit"] is None


def test_sidecar_still_rejects_panel_time_mismatch_and_late_publication(tmp_path):
    root, panel, master, dates = _published_sidecar(tmp_path)
    changed = dict(panel, panel_available_at="2026-10-07T17:59:00+08:00")
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_POINTER_IDENTITY_INVALID"):
        workspace_plan._read_hk02_daily_supplement_witness(
            root, DAY, dates, CUTOFF, changed, master, master["names"])
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF"):
        workspace_plan._read_hk02_daily_supplement_witness(
            root, DAY, dates, "2026-10-07T18:02:00+08:00", panel, master, master["names"])


def test_actual_supplement_repairs_all_six_numeric_volumes_without_inventing_unit_proof(tmp_path):
    root, _, _, _ = _published_sidecar(tmp_path, missing_panel_volume=True)
    result = workspace_plan.read_rebound_screen(root, workspace_plan.plan_context(
        TARGET, now=datetime.fromisoformat(CUTOFF)))
    assert result["cards"] == []
    assert len(result["pending"]) == 1
    row = result["pending"][0]
    assert row["volume_source"] == "PYTDX_EXHQ_CATEGORY_4_MARKET_71"
    assert row["current_volume"] == 150.0
    assert row["previous5_mean_volume"] == 100.0
    assert row["history_numeric_status"] == "KNOWN"
    assert row["volume_scale_applied"] == 1
    assert row["volume_unit_status"] == "NOT_PROVEN"
    assert row["volume_flag_5d_ge_1_5"] is None
    assert result["authority"]["daily_supplement"]["status"] == "READY"


def test_formal_cards_require_target_day_v2_and_reject_d1_capture():
    card = {"symbol":CODE, "market":"HK", "name":"Synthetic issuer"}
    accepted, rejected = connect_selection.filter_cards([card], _scope(target_v2=False), target_date=TARGET)
    assert accepted == []
    assert rejected[0]["reason"] == "TARGET_HK_CONNECT_AUTHORITY_V2_REQUIRED"
    accepted, rejected = connect_selection.filter_cards([card], _scope(target_v2=True), target_date=TARGET)
    assert len(accepted) == 1 and rejected == []
    assert accepted[0]["connect_eligibility"] == "VERIFIED_TARGET_UNIVERSE"


def test_read_scope_retains_d1_as_diagnostic_when_target_v2_is_missing(monkeypatch, tmp_path):
    from domains import manager_research_evidence
    from v4.manager_research import connect_capture_adapter
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(tmp_path))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(tmp_path))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", "a" * 64)
    monkeypatch.setenv("V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT", str(tmp_path / "dispatch"))

    def missing(*args, **kwargs):
        assert kwargs["require_v2"] is True
        raise ValueError("HK_UNIVERSE_V2_ARTIFACT_MISSING")

    monkeypatch.setattr(manager_research_evidence, "read_universe_evidence", missing)
    monkeypatch.setattr(connect_capture_adapter, "read_d1_scope", lambda *args, **kwargs:_scope(target_v2=False))
    result = connect_selection.read_scope(
        {"plan_trade_date":TARGET, "market_session":DAY, "research_cutoff":CUTOFF})
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["codes"] == [] and result["identity"] is None
    assert result["previous_session_capture"]["status"] == "OWNER_VERIFIED"
    assert "HK_UNIVERSE_V2_ARTIFACT_MISSING" in ";".join(result["gaps"])


def test_target_v2_reader_success_does_not_consult_previous_capture(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from domains import manager_research_evidence
    from v4.manager_research import connect_capture_adapter
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(tmp_path))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(tmp_path))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", "a" * 64)
    monkeypatch.setenv("V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT", str(tmp_path / "dispatch"))
    native = _scope(target_v2=True)
    monkeypatch.setattr(manager_research_evidence, "read_universe_evidence",
                        lambda *args, **kwargs:SimpleNamespace(codes=(CODE,), source=native["source"]))
    monkeypatch.setattr(connect_capture_adapter, "read_d1_scope",
                        lambda *args, **kwargs:pytest.fail("verified target V2 is already authoritative"))
    result = connect_selection.read_scope(
        {"plan_trade_date":TARGET, "market_session":DAY, "research_cutoff":CUTOFF})
    assert result["status"] == "OWNER_VERIFIED"
    assert result["membership_semantics"] == "TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2"
    assert result["codes"] == [CODE]


@pytest.mark.parametrize(("close", "volume"), [(80.0, 150.0), (80.0, 100.0), (81.0, 150.0), (81.0, 100.0)])
def test_unproved_volume_is_pending_for_every_numeric_gate_combination(tmp_path, close, volume):
    root, _, _ = _authority(tmp_path, close=close, volume=volume)
    planning = workspace_plan.plan_context(TARGET, now=datetime.fromisoformat(CUTOFF))
    result = workspace_plan.read_rebound_screen(root, planning)
    assert result["status"] == "READY_WITH_GAPS", result["gaps"]
    assert result["cards"] == [] and result["strict"] == [] and result["near"] == []
    assert result["excluded"] == []
    assert len(result["pending"]) == 1
    row = result["pending"][0]
    assert row["oversold_flag"] is (close <= 80.0)
    assert row["volume_ratio_5d"] == volume / 100.0
    assert row["volume_ratio_status"] == "UNVERIFIED_UNIT_OR_SCALE"
    assert row["volume_flag_5d_ge_1_5"] is None
    assert row["volume_unit_status"] == "NOT_PROVEN"
    assert "VOLUME_UNIT_OR_SCALE_NOT_PROVEN" in row["history_unknown_reasons"]
    assert row["connect_eligibility"] == "TARGET_DATE_AUTHORITY_NOT_EVALUATED"
    assert result["data_context"]["market_session"] == DAY


def test_bare_shares_string_and_lot_size_do_not_attest_volume(tmp_path):
    root, _, _ = _authority(tmp_path, bare_volume_unit="SHARES")
    result = workspace_plan.read_rebound_screen(root, workspace_plan.plan_context(
        TARGET, now=datetime.fromisoformat(CUTOFF)))
    assert result["cards"] == []
    row = result["pending"][0]
    assert row["volume_flag_5d_ge_1_5"] is None
    assert row["volume_unit_status"] == "NOT_PROVEN"
    assert row["volume_scale_applied"] is None
    assert "REBOUND_BARE_UNIT_DECLARATION_NOT_ATTESTED" in row["volume_provenance"]["gaps"]


def test_rebound_consumer_cannot_read_an_unfinished_target_panel(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness",
                        lambda root, day, **kwargs:(calls.append(day) or (None, ["SYNTHETIC_MISSING"])))
    context = {"plan_trade_date":TARGET, "market_session":TARGET,
               "research_cutoff":"2026-10-08T16:09:59+08:00"}
    result = workspace_plan.read_rebound_screen(tmp_path, context)
    assert calls == [DAY]
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["data_context"]["market_session"] == DAY


def test_postclose_reads_selection_day_panel_without_changing_plan_reference(tmp_path):
    root, _, _ = _authority(tmp_path)
    planning = workspace_plan.plan_context(DAY, now=datetime.fromisoformat(
        "2026-10-07T18:03:00+08:00"))
    original = deepcopy(planning)
    assert planning["market_session"] == "20261006"
    result = workspace_plan.read_rebound_screen(root, planning)
    assert planning == original
    assert result["data_context"]["market_session"] == DAY
    assert result["data_context"]["planning_market_session"] == "20261006"
    assert result["data_context"]["screen_phase"] == "POST_CLOSE_COMPLETED_SESSION"
    assert result["coverage"]["input_candidate_count"] == 1
    assert result["coverage"]["numeric_history_complete_count"] == 1
    assert result["pending"][0]["volume_flag_5d_ge_1_5"] is None


def test_completed_session_still_requires_panel_available_before_cutoff(tmp_path):
    root, _, _ = _authority(tmp_path)
    context = workspace_plan.plan_context(DAY, now=datetime.fromisoformat(
        "2026-10-07T17:59:59+08:00"))
    result = workspace_plan.read_rebound_screen(root, context)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["data_context"]["market_session"] == DAY
    assert "PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF" in result["gaps"]
    assert result["cards"] == []


@pytest.mark.parametrize(("close", "volume", "oversold", "quantity"), [
    (80.0, 150.0, True, True), (80.0001, 149.9999, False, False)])
def test_existing_arithmetic_keeps_inclusive_080_and_15_boundaries(close, volume, oversold, quantity):
    # Arithmetic is independently testable; this fixture grants no owner proof.
    value = workspace_plan.rebound_v3_metrics(
        price=close, low=70, amount=150_000_000, volume=volume,
        previous5_mean=100, prior60_high=100)
    assert value["gates"]["oversold"] is oversold
    assert value["gates"]["volume"] is quantity
