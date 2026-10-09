"""Independent projection/score invariants against exact reviewed source slices.

Imports use separately declared source roots and historical support. No Mac,
provider, live store, scheduler or API is invoked by these synthetic probes.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


PROJECT = Path(__file__).resolve().parents[3] / "quote_fields"
PINS = {
    "a_auction.py": "01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1",
    "a_live.py": "4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0",
}
for name, sha in PINS.items():
    assert hashlib.sha256((PROJECT / "after/stage_center/_selection_parts" / name).read_bytes()).hexdigest() == sha
for entry in json.loads((PROJECT / "SUPPORT_MANIFEST.json").read_text())["files"]:
    assert hashlib.sha256((PROJECT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]

for name, locations in {
    "stage_center": [PROJECT / "support/stage_center"],
    "stage_center._selection_parts": [PROJECT / "after/stage_center/_selection_parts", PROJECT / "support/stage_center/_selection_parts"],
    "infrastructure": [PROJECT / "support/infrastructure"],
}.items():
    package = types.ModuleType(name)
    package.__path__ = [str(p) for p in locations]
    sys.modules[name] = package

import stage_center.selection as selection


def load_before(name):
    qualified = "stage_center._selection_parts.independent_before_" + name
    spec = importlib.util.spec_from_file_location(qualified, PROJECT / "before/stage_center/_selection_parts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


OLD_AUCTION = load_before("a_auction")
OLD_LIVE = load_before("a_live")
DATE = "20261009"
STAGES = ("STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500")


def auction(previous=100, price=105):
    return {
        "code": "A.000001", "trade_date": DATE, "time": "2026-10-09 09:25:00",
        "price": price, "open_price": price, "last_price": price, "prev_close_price": previous,
        "high_price": price, "low_price": price, "amount": 2_500_000,
    }


def live(previous=100, last=105, opened=102):
    return {
        "code": "A.000001", "trade_date": DATE,
        "qmt": {"lastClose": previous, "lastPrice": last, "open": opened,
                "high": 110, "low": 90, "amount": 2_500_000,
                "bidVol": [3], "askVol": [2]},
        "candidate": {"score": 33}, "acquisition_rank": 1,
    }


def compute(rows, stage, old=False, requested=None):
    kwargs = dict(source_status="READY", requested_rows=len(rows) if requested is None else requested,
                  missing_symbols=(), cannot_confirm=(), source_evidence=("selection_contract=V3_TOP10_RECOMMENDATION",))
    if stage == "STAGE_0925":
        if old:
            return OLD_AUCTION._select_a_0925_auction_body(selection.__dict__, rows, DATE, "a" * 64, next_validation_time=None, **kwargs)
        return selection.select_a_0925_auction(rows, DATE, "a" * 64, **kwargs)
    if old:
        return OLD_LIVE._select_a_live_stage_body(selection.__dict__, rows, DATE, stage, "a" * 64, **kwargs)
    return selection.select_a_live_stage(rows, DATE, stage, "a" * 64, **kwargs)


def result_ranking(result):
    return [(r["code"], r["score"], r["stage_score"], r["rank"]) for r in result["rows"]]


def test_auction_numeric_strings_and_alias_priority():
    source = auction("", "100.00")
    source["prev_close"] = "100.0"
    source["current_change_pct"] = 999
    before_input = copy.deepcopy(source)
    row = compute([source], "STAGE_0925")["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == row["qmt_gap_pct"] == 0
    assert source == before_input


def test_auction_invalid_primary_baseline_cannot_be_hidden_by_secondary_alias():
    source = auction(0)
    source["prev_close"] = 100
    row = compute([source], "STAGE_0925")["rows"][0]
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_INVALID"


def test_live_nested_missing_baseline_does_not_borrow_unscored_top_level_price():
    source = live(None)
    source["lastClose"] = source["prev_close_price"] = source["qmt_prev_close"] = 100
    source["current_change_pct"] = 999
    row = compute([source], STAGES[0])["rows"][0]
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_MISSING"


def test_live_known_open_gap_and_missing_last_remain_separate():
    source = live(100, None, 102)
    row = compute([source], STAGES[0])["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] == pytest.approx(2)
    assert row["qmt_gap_pct_missing_reason"] is None
    assert row["current_change_pct_missing_reason"] == "LAST_PRICE_MISSING_OR_INVALID"


def test_live_known_day_return_overrides_conflicting_card_value():
    source = live("100.0", "105.0", "110.0")
    source["current_change_pct"] = 123
    row = compute([source], STAGES[0])["rows"][0]
    assert row["current_change_pct"] == 5
    assert row["qmt_gap_pct"] == pytest.approx(10)
    assert row["current_change_pct_basis"] == "LAST_PRICE_VS_PREV_CLOSE"


@pytest.mark.parametrize("stage", ("STAGE_0925", *STAGES))
def test_same_formula_calls_and_240_row_ranking_with_missing_inputs(stage, monkeypatch):
    rows = []
    for index in range(240):
        previous = [None, "100.0", 100, True, 0, -10][index % 6]
        price = [95, 100, 105, 107][index % 4]
        source = auction(previous, price) if stage == "STAGE_0925" else live(previous, price, [None, 99, 100, 104][index % 4])
        source.update(code=f"A.{index + 1:06d}", acquisition_rank=(index * 17) % 241)
        source["news_quality_score"] = index % 7
        source["research_quality_score"] = index % 9
        rows.append(source)
    original_rows = copy.deepcopy(rows)
    calls = []
    real_formula = selection.live_stage_quality_score

    def record(qmt, candidate, stage_id):
        calls.append(copy.deepcopy((qmt, candidate, stage_id)))
        return real_formula(qmt, candidate, stage_id)

    monkeypatch.setattr(selection, "live_stage_quality_score", record)
    before = compute(rows, stage, old=True, requested=246)
    before_calls = copy.deepcopy(calls)
    calls.clear()
    after = compute(rows, stage, requested=246)
    assert calls == before_calls
    assert len(calls) == 240
    assert result_ranking(after) == result_ranking(before)
    assert after["algorithm_sha256"] == before["algorithm_sha256"] == "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2"
    assert after["requested_rows"] == 246 and after["source_rows"] == 240 and after["selected_rows"] == 10
    assert rows == original_rows
    assert after["selection_status"] == "PARTIAL_WITH_ROWS"
    assert all(after[f] is False for f in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_output_projection_does_not_authorize_false_natural_or_missing_source():
    source = auction(None)
    result = compute([source], "STAGE_0925")
    assert result["rows"][0]["formal_eligible"] is False
    assert result["rows"][0]["action_level"] == "NO_BUY"
    assert not any(k in result for k in ("natural_verified", "execution_verified"))
    assert result["raw_artifact_sha256"] == "a" * 64
    assert result["rows"][0]["current_change_pct"] is None


def test_live_empty_batch_keeps_existing_ready_empty_identity():
    before = compute([], STAGES[0], old=True)
    after = compute([], STAGES[0])
    assert after == before
    assert after["selection_status"] == "READY_EMPTY"


def test_numeric_precision_is_day_return_and_true_zero():
    row = compute([live(153.7, 168.2, 165)], STAGES[-1])["rows"][0]
    assert row["current_change_pct"] == round((168.2 / 153.7 - 1) * 100, 4)
    zero = compute([live(153.7, 153.7, 165)], STAGES[-1])["rows"][0]
    assert zero["current_change_pct"] == 0
    assert zero["current_change_pct_missing_reason"] is None
