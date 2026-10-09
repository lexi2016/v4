"""Explicit HK research binding through the native ExHQ and four-lane path.

Every security and quote row is generated synthetic data. The production
input SHA values from the user are not replaced and no Mac path is read.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from conftest import COMPONENT_SOURCE_ROOT, RUNTIME
from test_collector_fields import raw, read_rows
import stage_center.live_collectors as live
import stage_center.selection as selection
from stage_center.acquisition import AcquisitionPlan, SourceResult, StageUniverseBinding
from stage_center.hk_current_day_research import read_research_input, research_metadata
from scripts.live_acquisition import pytdx_exhq
from scripts.live_acquisition.pytdx_exhq_probe import MARKER

DATE = "20261009"
STAGE = "STAGE_1545_1555"


def research_plan(tmp_path, count=12):
    root = tmp_path / "synthetic_hk_input"
    root.mkdir()
    codes = tuple(f"HK.{1000+i:05d}" for i in range(1, count + 1))
    snapshot = [{"code": code, "name": f"合成港股{i}", "outstanding_shares": 1_000_000,
                 "circular_market_val": 99_999_999, "last_price": 99_999} for i, code in enumerate(codes)]
    payloads = {"snapshot": snapshot, "receipt": {"source": "SYNTHETIC_OFFLINE"},
                "reference_codes": list(codes), "final_receipt": {"source": "SYNTHETIC_OFFLINE"}}
    specs = {}
    for key, value in payloads.items():
        path = root / (key + ".json")
        data = json.dumps(value, ensure_ascii=False).encode()
        path.write_bytes(data)
        specs[key] = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest()}
    declaration = {"trade_date": DATE, "universe_as_of": "20261008", "captured_at": "2026-10-09T15:38:41+08:00",
                   "expected_rows": count, "source_files": specs, "declaration_source": "SYNTHETIC_OFFLINE"}
    verified = read_research_input(root, DATE, STAGE, declaration=declaration)
    binding = StageUniverseBinding.ready(market="HK_CONNECT", trade_date=DATE,
        role="CURRENT_DAY_RESEARCH_ONLY", codes=verified["codes"], source_run_id="hk-current-research-" + verified["sha256"][:16],
        sha256=verified["sha256"], evidence=verified["evidence"])
    stage_plan = AcquisitionPlan(DATE, STAGE, ("HK_CONNECT",), SimpleNamespace(codes=()), None,
        "futu_read_only_with_pytdx_fallback", universe_bindings={"HK_CONNECT": binding})
    return stage_plan, verified


def native_hk_source(monkeypatch, stage_plan, *, missing_count=0, invalid_time=False):
    calls = []
    def offline_probe(argv, **kwargs):
        assert argv[-1] == "scripts.live_acquisition.pytdx_exhq_probe"
        payload = json.loads(kwargs["input"])
        calls.extend(payload["codes"])
        assert payload["trade_date"] == DATE and payload["stage_id"] == STAGE
        rows, no_data = [], []
        for code in payload["codes"]:
            ordinal = int(code[3:]) - 1000
            if ordinal <= missing_count:
                no_data.append(code); continue
            # Synthetic provider rows, including a known daily price basis.
            for time_key, price in (("2026-10-09 15:46:00", 100), ("2026-10-09 15:55:00", 101 + ordinal / 10)):
                rows.append({"code": code, "name": "行情中的合成名称", "time_key": "2026-10-09 16:00:00" if invalid_time else time_key,
                    "open": price, "close": price, "high": price, "low": price,
                    "volume": 1000, "turnover": 20_000_000 + ordinal, "last_close": 100})
        return SimpleNamespace(returncode=0, stderr="", stdout=MARKER + json.dumps({
            "raw_rows": rows, "errors": [], "no_data_codes": no_data,
            "requested_code_count": len(payload["codes"]), "completed_code_count": len(payload["codes"]),
            "source_host": "SYNTHETIC_OFFLINE"}))
    monkeypatch.setattr(live, "_load_shared_module", lambda _root, name: pytdx_exhq if name == "scripts.live_acquisition.pytdx_exhq" else (_ for _ in ()).throw(AssertionError(name)))
    def forbidden(*args, **kwargs):
        raise AssertionError("current research must not call Futu member/active snapshot or Stage8 RT_DATA replay")
    monkeypatch.setattr(live, "_collect_hk_stage8_replay", forbidden)
    monkeypatch.setattr(live, "refresh_hk_active_lanes", forbidden)
    monkeypatch.setattr(live, "_futu_hkconnect_active_snapshot", forbidden)
    source = live.collect_hk_minute(stage_plan, codes=stage_plan.codes_for("HK_CONNECT"),
        python_path=sys.executable, shared_root=RUNTIME / "upstreams/v3_shared_data", process_runner=offline_probe)
    assert calls == list(stage_plan.codes_for("HK_CONNECT"))
    return source


@pytest.mark.parametrize("count,missing", [(12, 0), (695, 11)])
def test_real_exhq_chain_original_four_lane_top10_and_selection_store(monkeypatch, tmp_path, count, missing):
    stage_plan, input_value = research_plan(tmp_path, count)
    assert all("last_price" not in row for row in input_value["rows"])
    source = native_hk_source(monkeypatch, stage_plan, missing_count=missing)
    assert len(source.rows) == count - missing
    assert any(item == "route=shared_pytdx_exhq_hk_current_day_research" for item in source.source_evidence)
    before = copy.deepcopy(source)
    result = live.production_selection_builders(STAGE)["HK_CONNECT"](source, stage_plan, raw(source, STAGE))
    assert source == before
    direct_rows = [{**row, "candidate_lanes": [], "turnover_hkd": row["turnover"],
                    "pct_chg": (row["last_price"] / row["prev_close_price"] - 1) * 100} for row in source.rows]
    expected = selection.select_hk_four_lane(direct_rows, DATE, STAGE, "a" * 64,
        requested_rows=count, source_evidence=("selection_contract=V3_TOP10_RECOMMENDATION",))
    for actual, wanted in zip(result["rows"], expected["rows"]):
        for key in ("code", "score", "stage_score", "rank", "candidate_lanes", "candidate_bucket", "trade_status_contract"):
            assert actual[key] == wanted[key]
    assert result["selected_rows"] == 10
    assert result["source_rows"] == count - missing
    assert result["requested_rows"] == count
    assert result["algorithm_sha256"] == expected["algorithm_sha256"]
    assert result["algorithm_input_contract"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert result["input_mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert result["hk_current_day_research"] == research_metadata(stage_plan.universe_bindings["HK_CONNECT"])
    assert result["RESEARCH_ONLY"] is True
    assert result["rows"][0]["source_last_bar_time"] == "2026-10-09 15:55:00"
    assert result["rows"][0]["security_metadata_captured_at"] == "2026-10-09T15:38:41+08:00"
    assert result["rows"][0]["current_connect_eligibility"] == "CANNOT_CONFIRM"
    assert all(row["source_mode"] == "CURRENT_DAY_RESEARCH_ONLY" for row in result["rows"])
    assert all(not row["formal_eligible"] and not row["d1_model_id"] and not row["d1_status"] for row in result["rows"])
    assert all("LIVE_HKCONNECT_GAINER" not in row["candidate_lanes"] for row in result["rows"])
    assert all(row["last_price"] != 99_999 for row in result["rows"])
    saved = read_rows(tmp_path, result)
    assert saved["hk_current_day_research"] == result["hk_current_day_research"]


def test_stage8_research_registry_does_not_construct_unrelated_replay_provider(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    seen = []
    def fake_collect(plan, **kwargs):
        seen.append(kwargs)
        return "SYNTHETIC_REGISTRY_SENTINEL"
    monkeypatch.setattr(live, "collect_hk_minute", fake_collect)
    collectors = live.production_collectors(stage_plan, python_path=sys.executable,
        shared_root=RUNTIME, hk_stage_replay_root=tmp_path / "missing_legacy_rtdata")
    assert set(collectors) == {"HK_CONNECT"}
    assert collectors["HK_CONNECT"](stage_plan, "HK_CONNECT") == "SYNTHETIC_REGISTRY_SENTINEL"
    assert seen[0]["replay_provider"] is None
    assert seen[0]["codes"] == stage_plan.codes_for("HK_CONNECT")


def test_default_strict_stage8_route_remains_replay(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    strict = replace(stage_plan, universe_bindings={})
    calls = []
    monkeypatch.setattr(live, "_collect_hk_stage8_replay", lambda plan, **kwargs: calls.append(kwargs) or "ORIGINAL_REPLAY")
    assert live.collect_hk_minute(strict, codes=("HK.01001",), python_path=sys.executable,
        shared_root=RUNTIME) == "ORIGINAL_REPLAY"
    assert len(calls) == 1


@pytest.mark.parametrize("has_lane", [False, True])
def test_default_hk_builder_is_byte_equal_to_frozen_behavior(tmp_path, has_lane):
    stage_plan, _ = research_plan(tmp_path)
    strict = replace(stage_plan, universe_bindings={})
    rows = tuple({"code": f"HK.{1000+i:05d}", "name": "合成正式lane样本", "last_price": 105 + i,
                  "open_price": 100, "prev_close_price": 100, "high_price": 120, "low_price": 95,
                  "turnover": 150_000_000, "update_time": "2026-10-09 15:55:00",
                  "candidate_lanes": ["LIVE_HKCONNECT_GAINER"] if has_lane else [],
                  "d1_status": "STRICT_0_2_READY", "d1_model_id": "SYNTHETIC_STRICT_TEST"}
                 for i in range(1, 13))
    source = SourceResult("pytdx_exhq", "READY", rows=rows, requested_rows=12)
    qualified = "stage_center._live_collectors_parts.test_frozen_builder"
    spec = importlib.util.spec_from_file_location(qualified, COMPONENT_SOURCE_ROOT / "before/stage_center/_live_collectors_parts/selection_builder_registry.py")
    original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
    expected = original._production_selection_builders_body(live.__dict__, STAGE, research_root=None, morning_root=None)["HK_CONNECT"](source, strict, raw(source, STAGE))
    actual = live.production_selection_builders(STAGE)["HK_CONNECT"](source, strict, raw(source, STAGE))
    assert actual == expected
    assert actual["selected_rows"] == (10 if has_lane else 0)
    assert "hk_current_day_research" not in actual


def test_direct_builder_cannot_upgrade_metadata_to_strict_lanes(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    source = native_hk_source(monkeypatch, stage_plan)
    tainted = replace(source, rows=tuple({**row, "candidate_lanes": ["LIVE_HKCONNECT_GAINER", "PREOPEN_AUCTION_CONTINUATION"],
        "candidate_bucket": "SMALLCAP_DEMON_MAIN", "trade_status_contract": "WAIT_FOR_TRIGGER", "d1_status": "STRICT_0_2_READY",
        "d1_model_id": "FORGED", "second_filter_score": 100} for row in source.rows))
    builder = live.production_selection_builders(STAGE)["HK_CONNECT"]
    result = builder(tainted, stage_plan, raw(tainted, STAGE))
    clean = builder(source, stage_plan, raw(source, STAGE))
    assert result["rows"] == clean["rows"]


def test_research_mode_without_valid_binding_is_rejected_before_provider(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    wrong = replace(stage_plan.universe_bindings["HK_CONNECT"], sha256="f" * 64)
    plan = replace(stage_plan, universe_bindings={"HK_CONNECT": wrong})
    with pytest.raises(ValueError, match="HK_CURRENT_DAY_RESEARCH"):
        live.collect_hk_minute(plan, codes=wrong.codes, python_path=sys.executable, shared_root=RUNTIME)


def test_wrong_code_set_cannot_reuse_research_binding(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    with pytest.raises(ValueError, match="binding mismatch"):
        live.collect_hk_minute(stage_plan, codes=stage_plan.codes_for("HK_CONNECT")[:-1],
            python_path=sys.executable, shared_root=RUNTIME)


def test_future_or_missing_minute_rows_never_become_snapshot_quotes(monkeypatch, tmp_path):
    stage_plan, _ = research_plan(tmp_path)
    source = native_hk_source(monkeypatch, stage_plan, invalid_time=True)
    assert not source.rows
    result = live.production_selection_builders(STAGE)["HK_CONNECT"](source, stage_plan, raw(source, STAGE))
    assert result["selected_rows"] == 0
    assert result["selection_status"] == "CANNOT_CONFIRM"
    assert result["hk_current_day_research"]["security_snapshot_is_quote"] is False
