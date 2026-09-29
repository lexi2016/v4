"""Synthetic contract data, not recorded market data or production acceptance."""
import copy

import pytest

from stage_center import selection


def auction(prev_close=None, *, code="A.600000", price=10.0):
    return {"code": code, "trade_date": "20260928", "time": "09:25:00",
            "price": price, "open_price": price, "prev_close_price": prev_close,
            "amount": 10_000_000, "pool_score": 50}


def select(rows):
    return selection.select_a_0925_auction(rows, "20260928", "a" * 64)


@pytest.mark.parametrize("previous", [None, "", 0, -1])
def test_missing_or_invalid_previous_close_is_not_measured_zero(previous):
    source = auction(previous)
    original = copy.deepcopy(source)
    result = select([source])
    row = result["rows"][0]
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE" not in row["lane_evidence"]
    assert "current_change_pct_basis=UNAVAILABLE" in row["lane_evidence"]
    assert "A_AUCTION_PREV_CLOSE_UNAVAILABLE:A.600000" in result["cannot_confirm"]
    assert row["action_level"] == "NO_BUY"
    assert row["trade_status"] == "WATCH_ONLY"
    assert row["formal_eligible"] is False
    assert source == original
    assert all(result[name] is False for name in selection.SAFETY_FLAGS)


@pytest.mark.parametrize("previous,expected", [(10.0, 0.0), (8.0, 25.0), (12.5, -20.0)])
def test_valid_previous_close_keeps_real_comparison(previous, expected):
    row = select([auction(previous)])["rows"][0]
    assert row["current_change_pct"] == expected
    assert row["qmt_gap_pct"] == expected
    assert "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE" in row["lane_evidence"]


def test_missingness_fix_does_not_change_frozen_scores_or_ranking():
    rows = [dict(auction(v, code=f"A.{600000+i:06d}", price=10+i/10), amount=10_000_000*(i+1))
            for i, v in enumerate([None, 10, 10.2, 11, 0, -1, None])]
    actual = [(row["code"], row["score"], row["rank"]) for row in select(rows)["rows"]]
    # Captured by executing the pinned baseline, not derived from the repair.
    assert actual == [("A.600001", 61.7, 1), ("A.600006", 52.95, 2),
                      ("A.600004", 52.45, 3), ("A.600002", 51.95, 4),
                      ("A.600000", 51.45, 5), ("A.600003", 0.0, 6),
                      ("A.600005", 0.0, 7)]


def test_explicit_unknown_does_not_use_open_price_as_previous_close():
    card = selection._stage_card_evidence(
        {"current_change_pct": None}, code="A.600000", open_price=10,
        last_price=11, high_price=11, low_price=10, source_last_bar_time=None,
        next_validation_time=None)
    assert card["current_change_pct"] is None


def test_legacy_absent_field_keeps_existing_window_fallback():
    card = selection._stage_card_evidence(
        {}, code="A.600000", open_price=10, last_price=11, high_price=11,
        low_price=10, source_last_bar_time=None, next_validation_time=None)
    assert card["current_change_pct"] == 10.0


def test_unknown_survives_original_store_publication_and_verified_read(tmp_path):
    envelope = select([auction()])
    store = selection.SelectionStore(tmp_path / "selection")
    store.publish(envelope, market="A_SHARE")
    read = store.read_verified("20260928", "STAGE_0925", "A_SHARE")
    assert read == envelope
    assert read["rows"][0]["current_change_pct"] is None
