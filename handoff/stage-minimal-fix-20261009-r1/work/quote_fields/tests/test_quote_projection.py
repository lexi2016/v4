"""Regressions for final observation fields, with the scoring path frozen.

The baseline counterexample is the real card helper's open/last fallback
overwriting an unknown auction day return. Live day returns must project the
same qmt previous-close value already supplied to the frozen formula.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import stage_center.selection as selection
from conftest import BEFORE_AUCTION, BEFORE_LIVE


DATE = "20261009"
RAW_SHA = "e" * 64
ALGORITHM_SHA = "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2"
TOP10 = ("selection_contract=V3_TOP10_RECOMMENDATION",)
LIVE_STAGES = (
    "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945",
    "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500",
)
MISSING = object()


def auction_row(previous=100, price=105, *, code="A.000001"):
    row = {
        "code": code, "trade_date": DATE, "time": "2026-10-09 09:25:00",
        "price": price, "open_price": price, "last_price": price,
        "high_price": price, "low_price": price, "amount": 10_000_000,
        "is_open_call_auction_match": True,
    }
    if previous is not MISSING:
        row["prev_close_price"] = previous
    return row


def live_row(previous=100, last=105, *, opened=102, code="A.000001", rank=1):
    qmt = {
        "open": opened, "lastPrice": last, "high": 106, "low": 101,
        "amount": 10_000_000, "bidVol": [5], "askVol": [5],
    }
    if previous is not MISSING:
        qmt["lastClose"] = previous
    return {
        "code": code, "trade_date": DATE, "qmt": qmt,
        "candidate": {"score": 20}, "formal_eligible": False,
        "acquisition_rank": rank,
    }


def run(rows, stage="STAGE_0925", *, before=False, requested=None, missing=()):
    kwargs = {
        "source_status": "PARTIAL_WITH_ROWS" if missing else "READY",
        "requested_rows": len(rows) if requested is None else requested,
        "missing_symbols": missing,
        "cannot_confirm": (),
        "source_evidence": TOP10,
    }
    if stage == "STAGE_0925":
        if before:
            return BEFORE_AUCTION._select_a_0925_auction_body(
                selection.__dict__, rows, DATE, RAW_SHA,
                next_validation_time=None, **kwargs,
            )
        return selection.select_a_0925_auction(rows, DATE, RAW_SHA, **kwargs)
    if before:
        return BEFORE_LIVE._select_a_live_stage_body(
            selection.__dict__, rows, DATE, stage, RAW_SHA, **kwargs,
        )
    return selection.select_a_live_stage(rows, DATE, stage, RAW_SHA, **kwargs)


def ranking(envelope):
    return [
        (row["code"], row["score"], row["stage_score"], row["rank"])
        for row in envelope["rows"]
    ]


INVALID_BASES = [
    (MISSING, "PREV_CLOSE_PRICE_MISSING"),
    (None, "PREV_CLOSE_PRICE_MISSING"),
    ("", "PREV_CLOSE_PRICE_MISSING"),
    (0, "PREV_CLOSE_PRICE_INVALID"),
    (-100, "PREV_CLOSE_PRICE_INVALID"),
    ("bad-price", "PREV_CLOSE_PRICE_INVALID"),
    (float("nan"), "PREV_CLOSE_PRICE_INVALID"),
    (float("inf"), "PREV_CLOSE_PRICE_INVALID"),
    (True, "PREV_CLOSE_PRICE_INVALID"),
]


@pytest.mark.parametrize("previous,reason", INVALID_BASES)
def test_auction_unknown_daily_change_is_not_open_last_zero(previous, reason):
    source = auction_row(previous)
    current = run([source])
    row = current["rows"][0]
    assert "prev_close_price" in row
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["current_change_pct_missing_reason"] == reason
    assert ranking(current) == ranking(run([source], before=True))


@pytest.mark.parametrize("previous,reason", INVALID_BASES)
def test_live_unknown_daily_change_is_not_intrastage_return(previous, reason):
    source = live_row(previous)
    current = run([source], LIVE_STAGES[0])
    row = current["rows"][0]
    assert "prev_close_price" in row
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["current_change_pct_missing_reason"] == reason
    assert ranking(current) == ranking(run([source], LIVE_STAGES[0], before=True))


@pytest.mark.parametrize("stage", ("STAGE_0925", *LIVE_STAGES))
@pytest.mark.parametrize("price,expected", [(105, 5), (100, 0), (95, -5)])
def test_observed_daily_return_and_true_zero_are_preserved(stage, price, expected):
    source = auction_row(100, price) if stage == "STAGE_0925" else live_row(100, price)
    current = run([source], stage)
    row = current["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == expected
    assert row.get("current_change_pct_missing_reason") is None
    assert ranking(current) == ranking(run([source], stage, before=True))
    assert current["algorithm_sha256"] == ALGORITHM_SHA


def test_auction_daily_return_uses_match_price_even_when_card_last_differs():
    source = auction_row(100, 105)
    source["last_price"] = 109
    row = run([source])["rows"][0]
    assert row["current_change_pct"] == 5
    assert row["last_price"] == 109


@pytest.mark.parametrize("stage", ("STAGE_0925", LIVE_STAGES[0]))
@pytest.mark.parametrize("last", [None, 0, -5, float("nan"), True])
def test_missing_or_invalid_last_is_distinct_from_missing_previous_close(stage, last):
    source = auction_row(100, last) if stage == "STAGE_0925" else live_row(100, last)
    current = run([source], stage)
    row = current["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] is None
    expected = "AUCTION_PRICE_MISSING_OR_INVALID" if stage == "STAGE_0925" else "LAST_PRICE_MISSING_OR_INVALID"
    assert row["current_change_pct_missing_reason"] == expected
    assert ranking(current) == ranking(run([source], stage, before=True))


@pytest.mark.parametrize("stage", ("STAGE_0925", *LIVE_STAGES))
def test_216_input_accounting_and_top10_scoring_rank_remain_unchanged(stage):
    count = 205 if stage == "STAGE_0925" else 206
    rows = []
    for index in range(count):
        previous = [None, 100, 0, -100, True][index % 5]
        price = 90 + index / 10
        if stage == "STAGE_0925":
            row = auction_row(previous, price, code=f"A.{index+1:06d}")
        else:
            row = live_row(previous, price, code=f"A.{index+1:06d}", rank=index+1)
        rows.append(row)
    # The last source row outranks all earlier rows, so a hidden 200-row
    # display cap before the scorer would be caught here.
    if stage == "STAGE_0925":
        rows[-1]["prev_close_price"] = 100
        rows[-1]["price"] = rows[-1]["open_price"] = rows[-1]["last_price"] = 110
        rows[-1]["amount"] = 600_000_000
        for row in rows[:-1]:
            row["prev_close_price"] = None
    else:
        rows[-1]["qmt"]["lastPrice"] = 500
    missing = tuple(f"A.{index+1:06d}" for index in range(count, 216))
    original = copy.deepcopy(rows)
    current = run(rows, stage, requested=216, missing=missing)
    before = run(rows, stage, before=True, requested=216, missing=missing)
    assert rows == original
    assert current["requested_rows"] == 216
    assert current["source_rows"] == count
    assert current["selected_rows"] == 10
    assert current["missing_symbols"] == list(missing)
    assert current["rows"][0]["code"] == rows[-1]["code"]
    assert current["selection_status"] == "PARTIAL_WITH_ROWS"
    assert ranking(current) == ranking(before)
    assert current["algorithm_sha256"] == before["algorithm_sha256"] == ALGORITHM_SHA
    assert not any(key.startswith("_") for row in current["rows"] for key in row)


def test_current_support_pressure_invalidation_rule_is_unchanged():
    source = auction_row(100, 105)
    current = run([source])["rows"][0]
    before = run([source], before=True)["rows"][0]
    for field in ("support", "pressure", "invalidation", "support_primary_price", "pressure_price", "invalidation_price"):
        assert current[field] == before[field] == 105


def test_live_flattened_qmt_input_projects_existing_baseline_without_new_aliases():
    source = {
        "code": "A.000001", "qmt_open": 102, "qmt_last": 105,
        "qmt_prev_close": 100, "qmt_high": 106, "qmt_low": 101,
        "qmt_amount": 10_000_000,
    }
    row = run([source], LIVE_STAGES[0])["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == 5


def test_live_0925_tie_break_runs_before_missing_gap_output_projection():
    rows = [
        live_row(None, 100, opened=100, code="A.000001", rank=1),
        live_row(100, 100, opened=100, code="A.000002", rank=2),
    ]
    kwargs = {"source_status": "READY", "requested_rows": 2,
              "missing_symbols": (), "cannot_confirm": (), "source_evidence": TOP10}
    before = BEFORE_LIVE._select_a_live_stage_body(
        selection.__dict__, rows, DATE, "STAGE_0925", RAW_SHA, **kwargs,
    )
    after = selection.select_a_live_stage(rows, DATE, "STAGE_0925", RAW_SHA, **kwargs)
    assert ranking(after) == ranking(before)
    assert [row["code"] for row in after["rows"]] == ["A.000001", "A.000002"]
    assert after["rows"][0]["qmt_gap_pct"] is None
    assert after["rows"][1]["qmt_gap_pct"] == 0


def test_live_no_open_or_last_does_not_export_a_zero_gap():
    source = live_row(100, None, opened=None)
    current = run([source], LIVE_STAGES[0])
    row = current["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["qmt_gap_pct_missing_reason"] == "OPEN_PRICE_MISSING_OR_INVALID"
    assert ranking(current) == ranking(run([source], LIVE_STAGES[0], before=True))


@pytest.mark.parametrize("stage", ("STAGE_0925", LIVE_STAGES[0]))
def test_nullable_price_observations_survive_real_store_and_json(tmp_path, stage):
    source = auction_row(None) if stage == "STAGE_0925" else live_row(None)
    envelope = run([source], stage)
    store = selection.SelectionStore(tmp_path / "synthetic")
    stored = store.publish(envelope, market="A_SHARE")
    readback = store.read_verified(DATE, stage, "A_SHARE")
    assert stored == readback == envelope
    row = json.loads(json.dumps(readback, allow_nan=False))["rows"][0]
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_MISSING"
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert readback[flag] is False


def file_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and not path.name.startswith(".")}


def test_old_run_is_preserved_and_new_projection_cannot_overwrite_slot(tmp_path):
    rows = [auction_row(None)]
    before = run(rows, before=True)
    after = run(rows)
    assert before["rows"][0]["current_change_pct"] == 0
    assert after["rows"][0]["current_change_pct"] is None
    assert before["run_id"] != after["run_id"]
    store = selection.SelectionStore(tmp_path / "existing")
    store.publish(before, market="A_SHARE")
    original = file_bytes(store.root)
    assert store.read_verified(DATE, "STAGE_0925", "A_SHARE") == before
    with pytest.raises(selection.SelectionError, match="selection slot conflict"):
        store.publish(after, market="A_SHARE")
    assert file_bytes(store.root) == original


def test_wrong_date_still_rejected_without_any_projection():
    row = auction_row()
    row["trade_date"] = "20261008"
    with pytest.raises(selection.SelectionError, match="trade_date drift"):
        run([row])
