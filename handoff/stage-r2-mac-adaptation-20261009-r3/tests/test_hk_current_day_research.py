"""Research admission must not invent formal eligibility or stage quotes."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stage_center import live_collectors, runner, selection
from stage_center.acquisition import AcquisitionPlan, SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import SAFETY_FLAGS


DAY = "20261009"
STAGE = "STAGE_0930_0935"
PIN_NAME = "CURRENT_DAY_RESEARCH_PIN.json"


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return sha256(path.read_bytes()).hexdigest()


def bundle(tmp_path, count=12):
    root = tmp_path / "security_source"
    root.mkdir()
    rows = [{"code": f"HK.{i:05d}", "name": f"研究样本{i}",
             "outstanding_shares": 10000000, "circular_market_val": 40000000,
             "listing_date": "2010-01-01", "lot_size": 100,
             "stock_owner": "", "stock_child_type": "STOCK", "sec_status": "NORMAL"}
            for i in range(1, count + 1)]
    files = {
        "snapshot_rows_projected.json": rows,
        "receipt.json": {"opaque_provider_receipt": "no_schema_assumption"},
        "reference_codes_20261008.json": [r["code"] for r in rows],
        "FINAL_RECEIPT.json": {"opaque_final_receipt": True},
    }
    pin = {"schema_version": "v4.hk_current_day_research_pin.v1",
           "mode": "CURRENT_DAY_RESEARCH_ONLY", "market": "HK_CONNECT",
           "trade_date": DAY, "universe_as_of": "20261008",
           "captured_at": "2026-10-09T15:38:41+08:00", "stale_universe": True,
           "hk_connect_membership_status": "CANNOT_CONFIRM", "formal_d1_eligible": False,
           "formal_pit": False, "row_count": count,
           "files": {name: write_json(root / name, value) for name, value in files.items()},
           **SAFETY_FLAGS}
    write_json(root / PIN_NAME, pin)
    return root, rows, pin


def config(tmp_path, research_root=None):
    kwargs = dict(candidate_acquisition_root=tmp_path / "candidate", raw_root=tmp_path / "raw",
                  selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipts")
    if research_root is not None:
        kwargs["hk_current_day_research_root"] = research_root
    return runner.build_production_config(**kwargs)


def bound_plan(root, binding, stage_id=STAGE):
    candidate = runner._candidate_from_hk_binding(root=root, trade_date=DAY, binding=binding)
    return AcquisitionPlan(trade_date=DAY, stage_id=stage_id, markets=("A_SHARE", "HK_CONNECT"),
                           candidate_input=candidate, a_share_route=None, hk_route="existing",
                           universe_bindings={"HK_CONNECT": binding})


def minute_row(code, index=1, stamp="2026-10-09 09:35:00"):
    return {"batch_index": index, "code": code, "name": code, "update_time": stamp,
            "last_price": 10.0 + index, "open_price": 10.0,
            "high_price": 12.0 + index, "low_price": 9.0, "prev_close_price": 10.0,
            "turnover": 20000000.0 + index, "volume": 500.0,
            "bid_price": None, "ask_price": None, "bid_vol": None, "ask_vol": None,
            "window_start": "2026-10-09 09:30:00", "window_end": "2026-10-09 09:35:00",
            "bar_count": 5, "temporal_cutoff_safe": True}


def raw_evidence(source):
    return {"artifact_sha256": "a" * 64, "status": source.status,
            "requested_rows": source.requested_rows, "missing_symbols": list(source.missing_symbols),
            "cannot_confirm": list(source.cannot_confirm), "source_evidence": list(source.source_evidence),
            "cutoff_at": "09:35:05", "trade_date": DAY, "stage_id": STAGE, "market": "HK_CONNECT"}


def test_explicit_config_is_optional_and_preserves_default_strict_gate(tmp_path):
    default = config(tmp_path)
    assert getattr(default, "hk_current_day_research_root", None) is None
    with pytest.raises(runner.RunnerError, match="HK D1 root is required"):
        runner._validate_exact_selection_inputs(default, DAY, STAGE, market="HK_CONNECT")
    root, _, _ = bundle(tmp_path)
    explicit = config(tmp_path, root)
    assert explicit.hk_current_day_research_root == root.resolve()


def test_695_security_rows_bind_without_formal_d1_authority(tmp_path):
    root, rows, _ = bundle(tmp_path, count=695)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    assert binding.role == "HK_CURRENT_DAY_RESEARCH"
    assert binding.status == "READY"
    assert binding.codes == tuple(row["code"] for row in rows)
    assert binding.sha256 == sha256((root / PIN_NAME).read_bytes()).hexdigest()
    evidence = runner._validate_exact_selection_inputs(config(tmp_path, root), DAY, STAGE,
                                                       market="HK_CONNECT", hk_binding=binding)
    source = [e for e in evidence if e.startswith("research_source=")]
    assert len(source) == 1
    info = json.loads(source[0].partition("=")[2])
    assert info["mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert info["hk_connect_membership_status"] == "CANNOT_CONFIRM"
    assert info["formal_d1_eligible"] is False
    assert info["stale_universe"] is True
    assert info["source_sha256"] == binding.sha256
    assert not any("STRICT_0_2_READY" in e or "hk_d1_membership=" in e for e in evidence)


@pytest.mark.parametrize("filename", ["snapshot_rows_projected.json", "receipt.json",
                                      "reference_codes_20261008.json", "FINAL_RECEIPT.json"])
def test_each_input_sha_is_checked(tmp_path, filename):
    root, _, _ = bundle(tmp_path)
    with (root / filename).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(runner.RunnerError, match="SHA_MISMATCH"):
        runner._build_hk_current_day_research_binding(root, DAY)


@pytest.mark.parametrize("key,value", [("trade_date", "20261008"),
                                      ("captured_at", "2026-10-08T15:38:41+08:00"),
                                      ("universe_as_of", "20261010"),
                                      ("stale_universe", False),
                                      ("hk_connect_membership_status", "READY"),
                                      ("formal_d1_eligible", True), ("orders_sent", True)])
def test_pin_identity_date_and_safety_cannot_be_promoted(tmp_path, key, value):
    root, _, pin = bundle(tmp_path)
    pin[key] = value
    write_json(root / PIN_NAME, pin)
    with pytest.raises(runner.RunnerError, match="HK_CURRENT_DAY_RESEARCH"):
        runner._build_hk_current_day_research_binding(root, DAY)


def test_code_reference_mismatch_rejected_even_with_matching_file_hash(tmp_path):
    root, rows, pin = bundle(tmp_path)
    rows[0]["code"] = "HK.09999"
    pin["files"]["snapshot_rows_projected.json"] = write_json(root / "snapshot_rows_projected.json", rows)
    write_json(root / PIN_NAME, pin)
    with pytest.raises(runner.RunnerError, match="CODE_SET_MISMATCH"):
        runner._build_hk_current_day_research_binding(root, DAY)


def test_security_snapshot_cannot_smuggle_prices(tmp_path):
    root, rows, pin = bundle(tmp_path)
    rows[0]["last_price"] = 999.0
    pin["files"]["snapshot_rows_projected.json"] = write_json(root / "snapshot_rows_projected.json", rows)
    write_json(root / PIN_NAME, pin)
    with pytest.raises(runner.RunnerError, match="SECURITY_FIELDS"):
        runner._build_hk_current_day_research_binding(root, DAY)


def test_authority_overlay_keeps_real_quote_and_absent_quote_values(tmp_path):
    root, rows, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    quote = minute_row(rows[0]["code"])
    quote["open_price"] = None
    source = SourceResult("pytdx_exhq", "PARTIAL_WITH_ROWS", (quote,), requested_rows=len(rows),
                          source_evidence=binding.evidence)
    result = runner._attach_hk_authority(source, d1_root=None, second_root=None, preselection_source_root=None,
                                          trade_date=DAY, stage_id=STAGE, hk_binding=binding)
    assert result.rows[0]["last_price"] == quote["last_price"]
    assert result.rows[0]["open_price"] is None
    assert result.rows[0]["update_time"] == "2026-10-09 09:35:00"
    assert result.rows[0]["name"] == rows[0]["name"]
    assert result.rows[0]["candidate_lanes"] == []
    assert not result.rows[0].get("d1_status")
    assert quote["name"] == quote["code"]


def test_changed_pin_is_rejected_before_authority_overlay(tmp_path):
    root, rows, pin = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    pin["captured_at"] = "2026-10-09T15:39:00+08:00"
    write_json(root / PIN_NAME, pin)
    source = SourceResult("pytdx_exhq", "PARTIAL_WITH_ROWS", (minute_row(rows[0]["code"]),))
    with pytest.raises(runner.RunnerError, match="BINDING_CHANGED"):
        runner._attach_hk_authority(source, d1_root=None, second_root=None, preselection_source_root=None,
                                   trade_date=DAY, stage_id=STAGE, hk_binding=binding)


@pytest.mark.parametrize("stage", ["STAGE_0925", "STAGE_1545_1555"])
def test_current_security_research_does_not_fabricate_auction_or_rtdata(tmp_path, stage):
    root, _, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    with pytest.raises(runner.RunnerError, match="MINUTE_STAGE_REQUIRED"):
        runner._validate_exact_selection_inputs(config(tmp_path, root), DAY, stage,
                                                market="HK_CONNECT", hk_binding=binding)


def install_quote_bridge(monkeypatch, rows, missing=()):
    calls = []
    def collect(python_path, trade_date, stage_id, codes, **kwargs):
        calls.append((trade_date, stage_id, tuple(codes), kwargs["market"]))
        return SimpleNamespace(status="READ_OK", rows=tuple(rows), cannot_confirm=(),
                               no_data_codes=missing, requested_code_count=len(codes))
    monkeypatch.setattr(live_collectors, "_shared_scripts_root", lambda root: root)
    monkeypatch.setattr(live_collectors, "_load_shared_module",
                        lambda root, name: SimpleNamespace(collect_pytdx_exhq_minute=collect))
    monkeypatch.setattr(live_collectors, "_scoped_process_runner", lambda root, proc: proc)
    def unexpected_snapshot(*args, **kwargs):
        pytest.fail("Explicit current security research must not manufacture a Futu LIVE lane")
    monkeypatch.setattr(live_collectors, "refresh_hk_active_lanes", unexpected_snapshot)
    return calls


def test_explicit_research_uses_existing_pytdx_bridge_and_four_lane_top10(tmp_path, monkeypatch):
    root, rows, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    plan = bound_plan(root, binding)
    quotes = [minute_row(row["code"], i) for i, row in enumerate(rows, 1)]
    calls = install_quote_bridge(monkeypatch, quotes)
    collectors = live_collectors.production_collectors(plan, python_path=Path("/usr/bin/python3"),
                                                       shared_root=tmp_path)
    acquired = collectors["HK_CONNECT"](plan, "HK_CONNECT")
    assert calls == [(DAY, STAGE, binding.codes, "HK_CONNECT")]
    assert acquired.status == "PARTIAL_WITH_ROWS"
    assert len(acquired.rows) == 12
    assert all(row["candidate_lanes"] == [] for row in acquired.rows)
    source = runner._attach_hk_authority(acquired, d1_root=None, second_root=None, preselection_source_root=None,
                                        trade_date=DAY, stage_id=STAGE, hk_binding=binding)
    chosen = live_collectors.production_selection_builders(STAGE)["HK_CONNECT"](
        source, plan, raw_evidence(source))
    assert len(chosen["rows"]) == 10
    assert chosen["algorithm_sha256"] == selection.ALGORITHM_SHA256
    assert all(row["action_level"] == "NO_BUY" and row["formal_eligible"] is False
               and row["candidate_lanes"] == [] for row in chosen["rows"])
    assert all(chosen[flag] is False for flag in SAFETY_FLAGS)
    assert len([e for e in chosen["source_evidence"] if e.startswith("research_source=")]) == 1
    direct_rows = [{"code": q["code"], "name": q["name"], "candidate_lanes": [],
                    "pct_chg": (q["last_price"] - q["prev_close_price"]) / q["prev_close_price"] * 100,
                    "turnover": q["turnover"], "turnover_hkd": q["turnover"],
                    "last_price": q["last_price"], "open_price": q["open_price"],
                    "high_price": q["high_price"], "low_price": q["low_price"],
                    "update_time": q["update_time"]} for q in source.rows]
    original = selection.select_hk_four_lane(direct_rows, DAY, STAGE, "a" * 64,
                       source_status="PARTIAL_WITH_ROWS", requested_rows=12,
                       source_evidence=("selection_contract=V3_TOP10_RECOMMENDATION",))
    assert [(r["code"], r["score"]) for r in chosen["rows"]] == [(r["code"], r["score"]) for r in original["rows"]]


@pytest.mark.parametrize("bad_stamp", ["2026-10-09 15:38:41", "2026-10-08 09:35:00", None])
def test_research_filters_wrong_stage_quotes_and_preserves_missing(tmp_path, monkeypatch, bad_stamp):
    root, rows, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    quotes = [minute_row(rows[0]["code"]), minute_row(rows[1]["code"], 2, bad_stamp)]
    install_quote_bridge(monkeypatch, quotes)
    plan = bound_plan(root, binding)
    result = live_collectors.collect_hk_minute(plan, codes=binding.codes, python_path=Path("/usr/bin/python3"),
                                             shared_root=tmp_path)
    assert [r["code"] for r in result.rows] == [rows[0]["code"]]
    assert set(result.missing_symbols) == set(binding.codes[1:])
    assert any("QUOTE_TIME" in reason for reason in result.cannot_confirm)


def test_missing_real_minute_data_stays_missing(tmp_path, monkeypatch):
    root, _, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    install_quote_bridge(monkeypatch, [])
    plan = bound_plan(root, binding)
    result = live_collectors.collect_hk_minute(plan, codes=binding.codes, python_path=Path("/usr/bin/python3"),
                                             shared_root=tmp_path)
    assert result.rows == ()
    assert result.status == "CANNOT_CONFIRM"
    assert set(result.missing_symbols) == set(binding.codes)
    chosen = live_collectors.production_selection_builders(STAGE)["HK_CONNECT"](
        result, plan, raw_evidence(result))
    assert chosen["rows"] == []
    assert chosen["selection_status"] == "CANNOT_CONFIRM"


def test_marker_alone_cannot_enable_research_builder(tmp_path):
    candidate = CandidateInput(root=tmp_path, trade_date=DAY, current_relative="test.json",
              current_sha256="b" * 64, run_id="fixture", codes=("A.000001",),
              artifact_sha256="b" * 64, manifest_sha256="b" * 64, receipt_sha256="b" * 64,
              source_projection_sha256="b" * 64, source_evidence=())
    plan = AcquisitionPlan(DAY, STAGE, ("A_SHARE", "HK_CONNECT"), candidate, None, "existing")
    source = SourceResult("pytdx_exhq", "READY", (minute_row("HK.00001"),), requested_rows=1,
                          source_evidence=("hk_selection_mode=CURRENT_DAY_RESEARCH_ONLY",))
    chosen = live_collectors.production_selection_builders(STAGE)["HK_CONNECT"](
        source, plan, raw_evidence(source))
    assert chosen["rows"] == []
    assert chosen["selection_status"] == "CANNOT_CONFIRM"


def test_research_binding_cannot_downgrade_a_config_that_did_not_opt_in(tmp_path):
    root, _, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    strict = replace(config(tmp_path), hk_d1_root=tmp_path / "strict-d1")
    with pytest.raises(runner.RunnerError, match="EXPLICIT_ROOT_REQUIRED"):
        runner._validate_exact_selection_inputs(strict, DAY, STAGE,
                                               market="HK_CONNECT", hk_binding=binding)


def test_builder_rejects_conflicting_raw_research_source_identity(tmp_path):
    root, rows, _ = bundle(tmp_path)
    binding = runner._build_hk_current_day_research_binding(root, DAY)
    source = SourceResult("pytdx_exhq", "PARTIAL_WITH_ROWS", (minute_row(rows[0]["code"]),),
                          requested_rows=len(rows), source_evidence=binding.evidence)
    raw = raw_evidence(source)
    raw["source_evidence"] = ['research_source={"source_sha256":"wrong"}']
    with pytest.raises(runner.RunnerError, match="SOURCE_BINDING_MISMATCH"):
        live_collectors.production_selection_builders(STAGE)["HK_CONNECT"](
            source, bound_plan(root, binding), raw)
