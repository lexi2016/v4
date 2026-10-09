"""Real SourceResult -> native builder -> unmodified formula -> on-disk store.

All source observations below are synthetic. No real market input is read.
"""
from __future__ import annotations

import ast
import copy
import csv
from datetime import datetime, timedelta
import json
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from conftest import RUNTIME
import stage_center.live_collectors as live
import stage_center.selection as selection
from stage_center.acquisition import AcquisitionPlan, SourceResult
from stage_center.contracts import STAGE_BY_ID
from scripts.live_acquisition import pytdx_hq

DATE = "20261009"
SHA = "a" * 64
STAGES = ("STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500")


def plan(stage, codes):
    return AcquisitionPlan(DATE, stage, ("A_SHARE",), SimpleNamespace(codes=tuple(codes)), "pytdx_hq_large_universe", "futu_read_only_with_pytdx_fallback")


def raw(source, stage):
    return {"artifact_sha256": SHA, "status": source.status, "requested_rows": source.requested_rows,
            "missing_symbols": source.missing_symbols, "cannot_confirm": source.cannot_confirm,
            "source_evidence": source.source_evidence, "cutoff_at": STAGE_BY_ID[stage].cutoff}


def read_rows(tmp_path, envelope):
    store = selection.SelectionStore(tmp_path / "selection")
    store.publish(envelope, market=envelope["market"])
    found = store.read_verified(DATE, envelope["stage_id"], envelope["market"])
    assert found["run_id"] == envelope["run_id"]
    assert found["algorithm_sha256"] == envelope["algorithm_sha256"]
    assert found["rows"] == envelope["rows"]
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert found[key] is False
    return found


def auction_source(tmp_path, previous, price, *, count=1):
    codes = tuple(f"A.{600000+i:06d}" for i in range(1, count + 1))
    path = tmp_path / "generated_stages" / DATE / f"generated_stage1_0925_auction_{DATE}.csv"
    path.parent.mkdir(parents=True)
    rows = [{"code": code, "name": "合成样本", "last_time": "2026-10-09 09:25:00", "last_close": price,
             "prev_close_price": previous, "amount": 50_000_000, "volume": 1000} for code in codes]
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    stage_plan = plan("STAGE_0925", codes)
    source = live.collect_a_share_auction(stage_plan, codes=codes, python_path=sys.executable,
                                         shared_root=RUNTIME, auction_root=tmp_path)
    return source, stage_plan


@pytest.mark.parametrize("previous,price,expected,reason", [(100, 105, 5.0, None), (100, 100, 0.0, None), (None, 105, None, "PREV_CLOSE_PRICE_MISSING"), (0, 105, None, "PREV_CLOSE_PRICE_INVALID")])
def test_auction_provider_source_builder_selector_store(tmp_path, previous, price, expected, reason):
    source, stage_plan = auction_source(tmp_path, previous, price)
    before = copy.deepcopy(source.rows)
    assert source.rows[0]["prev_close_price"] == previous
    result = live.production_selection_builders("STAGE_0925")["A_SHARE"](source, stage_plan, raw(source, "STAGE_0925"))
    saved = read_rows(tmp_path, result)
    row = saved["rows"][0]
    assert row["code"] == source.rows[0]["code"]
    assert row["prev_close_price"] == (previous if previous and previous > 0 else None)
    assert row["current_change_pct"] == expected
    assert row["current_change_pct_missing_reason"] == reason
    assert source.rows == before
    assert result["algorithm_sha256"] == selection.A_SHARE_LIVE_ALGORITHM_SHA256


def hq_native_probe_functions():
    """Use the actual fixed probe normalizer, without its network main block."""
    tree = ast.parse(pytdx_hq._PYTDX_HQ_PROBE)
    body = [node for node in tree.body if isinstance(node, (ast.FunctionDef,)) or
            (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MINUTE_TIMES" for target in node.targets))]
    scope = {"datetime": datetime}
    exec(compile(ast.Module(body=body, type_ignores=[]), "native_pytdx_hq_probe_functions", "exec"), scope)
    return scope


def native_hq_source(monkeypatch, stage, *, previous=100, price=105, count=1, missing_count=0):
    codes = tuple(f"A.{600000+i:06d}" for i in range(1, count + 1))
    stage_plan = plan(stage, codes)
    normalize = hq_native_probe_functions()["normalize_rows"]
    window_start, window_end, _cutoff = pytdx_hq.STAGE_WINDOWS[stage]
    first_at = datetime.strptime(DATE + " " + window_start, "%Y%m%d %H:%M:%S") + timedelta(minutes=1)
    end_at = datetime.strptime(DATE + " " + window_end, "%Y%m%d %H:%M:%S")
    last_at = end_at.replace(second=0) if end_at.second else end_at - timedelta(minutes=1)
    seen = []
    def synthetic_wire(argv, **kwargs):
        payload = json.loads(kwargs["input"])
        seen.extend(payload["codes"])
        all_rows, missing = [], []
        for code in payload["codes"]:
            ordinal = int(code.split(".")[1]) - 600000
            if ordinal <= missing_count:
                missing.append(code); continue
            row_price = 115 if count > 200 and ordinal == count else price
            wire_by_time = {
                "2026-10-09 09:31:00": {"price": 100},
                first_at.strftime("%Y-%m-%d %H:%M:%S"): {"price": 100},
                last_at.strftime("%Y-%m-%d %H:%M:%S"): {"price": row_price},
            }
            wire = [{"datetime": when, **values, "vol": 10,
                     "amount": 50_000_000, "last_close": previous} for when, values in sorted(wire_by_time.items())]
            all_rows.extend(normalize(code, wire, DATE))
        return SimpleNamespace(returncode=0, stderr="", stdout=pytdx_hq.MARKER + json.dumps({
            "raw_rows": all_rows, "errors": [], "no_data_codes": missing,
            "requested_code_count": len(payload["codes"]), "completed_code_count": len(payload["codes"]),
            "source_host": "SYNTHETIC_OFFLINE"}))
    monkeypatch.setattr(live, "_load_shared_module", lambda _root, name: pytdx_hq if name == "scripts.live_acquisition.pytdx_hq" else (_ for _ in ()).throw(AssertionError(name)))
    source = live.collect_a_share_hq_minute(stage_plan, codes=codes, python_path=sys.executable,
                                           shared_root=RUNTIME / "upstreams/v3_shared_data", process_runner=synthetic_wire)
    assert len(seen) == count
    return source, stage_plan


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("previous,price,expected,reason", [(100, 105, 5.0, None), (100, 100, 0.0, None), (None, 105, None, "PREV_CLOSE_PRICE_MISSING")])
def test_native_hq_field_chain_all_stages_without_optional_context(monkeypatch, tmp_path, stage, previous, price, expected, reason):
    source, stage_plan = native_hq_source(monkeypatch, stage, previous=previous, price=price)
    assert source.rows[0]["prev_close_price"] == previous
    result = live.production_selection_builders(stage)["A_SHARE"](source, stage_plan, raw(source, stage))
    saved = read_rows(tmp_path, result)
    row = saved["rows"][0]
    assert row["code"] == source.rows[0]["code"]
    assert row["prev_close_price"] == previous
    assert row["current_change_pct"] == expected
    assert row["current_change_pct_missing_reason"] == reason
    assert row["news_quality_score"] is None
    assert row["research_quality_score"] is None
    assert row["research_bonus"] is None
    assert any("OPTIONAL_RESEARCH_CONTEXT_UNAVAILABLE" in reason for reason in result["cannot_confirm"])


@pytest.mark.parametrize("missing_count", [10, 11])
def test_216_full_inputs_partial_per_symbol_reach_original_top10(monkeypatch, tmp_path, missing_count):
    source, stage_plan = native_hq_source(monkeypatch, STAGES[0], count=216, missing_count=missing_count)
    result = live.production_selection_builders(STAGES[0])["A_SHARE"](source, stage_plan, raw(source, STAGES[0]))
    read_rows(tmp_path, result)
    assert result["requested_rows"] == 216
    assert result["source_rows"] == 216 - missing_count
    assert result["selected_rows"] == 10
    assert result["rows"][0]["code"] == "SH.600216"
    assert len(result["missing_symbols"]) == missing_count
    assert result["selection_status"] == "PARTIAL_WITH_ROWS"


def test_invalid_optional_source_witness_is_retained_and_not_consumed(monkeypatch, tmp_path):
    import stage_center.research_context as context
    from domains.research import build_research_archive
    from infrastructure.research_store import HourlyResearchStore
    issue = "RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH"
    original_source = {"schema_version": "v3_research_lane.v2", "trade_date": DATE, "slot": "0900",
        "source_manifest": {"hourly_slot": "0900", "trade_date": DATE, "pit_cutoff": "2026-10-09T09:00:59+08:00",
                            "published_at": "2026-10-09T09:00:00+08:00"},
        "stock_research_timeline": [{"stock_code": "600001", "stock_name": "合成样本", "source_title": "Synthetic source witness",
                                      "source_name": "SYNTHETIC_OFFLINE", "source_path": "synthetic/source.json",
                                      "event_time": "2026-10-09T09:00:00+08:00"}],
        "stock_research_daily": [{"stock_code": "600001", "stock_name": "合成样本"}],
        "research_items": [], "raw_items": []}
    source_bytes = json.dumps(original_source, ensure_ascii=False).encode()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    original_path = tmp_path / "research/hourly/source" / (source_sha + ".json")
    original_path.parent.mkdir(parents=True)
    original_path.write_bytes(source_bytes)
    archive = build_research_archive(original_source, source_input_sha256=source_sha)
    # This is a internally consistent archive/receipt/manifest whose payload
    # is not the projection of its SHA-matched original source. The original
    # validator must detect exactly that mismatch, not a mocked exception.
    archive["cannot_confirm"].append("SYNTHETIC_ARCHIVE_PROJECTION_CORRUPTION")
    HourlyResearchStore(tmp_path).publish(archive, slot="0900", mode="LIVE")
    frozen = {str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in tmp_path.rglob("*.json")}
    with pytest.raises(context.ResearchContextError, match=issue):
        context.load_research_context(tmp_path, trade_date=DATE, stage_cutoff=STAGE_BY_ID[STAGES[0]].cutoff)
    source, stage_plan = native_hq_source(monkeypatch, STAGES[0])
    result = live.production_selection_builders(STAGES[0], research_root=tmp_path)["A_SHARE"](source, stage_plan, raw(source, STAGES[0]))
    assert result["selected_rows"] == 1
    assert any(issue in reason for reason in result["cannot_confirm"])
    assert result["rows"][0]["research_bonus"] is None
    assert result["rows"][0]["source_health"] == "CANNOT_CONFIRM"
    read_rows(tmp_path, result)
    assert all(hashlib.sha256((tmp_path / path).read_bytes()).hexdigest() == sha for path, sha in frozen.items())


def test_raw_identity_failure_still_raises(monkeypatch):
    source, stage_plan = native_hq_source(monkeypatch, STAGES[0])
    broken = raw(source, STAGES[0]); broken["artifact_sha256"] = "invalid"
    with pytest.raises(selection.SelectionError, match="raw_artifact_sha256"):
        live.production_selection_builders(STAGES[0])["A_SHARE"](source, stage_plan, broken)
