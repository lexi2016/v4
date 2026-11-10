"""Price readiness regression; no capture, publication, or live state writes."""
from copy import deepcopy

import pytest

from stage_center import selection


SHA = "a" * 64
EVIDENCE = ("native_snapshot_contract=V4_A_OPENING_NATIVE_SNAPSHOT_V1",
            f"native_snapshot_sha256={SHA}", "selection_contract=STAGE_CENTER_TOP10_V1")


def native_row(**changes):
    row = dict(code="A.688585", trade_date="20261109", time="2026-11-09 09:25:00",
               last_price=189.02, open_price=0, high_price=0, low_price=0,
               prev_close_price=180.02, amount=0, volume=0,
               bid_vol=100, ask_vol=100, native_quote_snapshot=True,
               native_snapshot_sha256=SHA, native_capture_started_at="2026-11-09T09:25:00.05+08:00",
               native_captured_at="2026-11-09T09:25:00.5+08:00",
               native_source_update_time="2026-11-09 09:30:00",
               native_market_cutoff_at="2026-11-09T09:25:05+08:00",
               source_time_semantics="PREOPEN_SESSION_OPEN_LABEL",
               source_method="get_market_snapshot", is_open_call_auction_match=False)
    row.update(changes)
    return row


def select(row, evidence=EVIDENCE):
    return selection.select_a_0925_auction([row], "20261109", "b" * 64, source_evidence=evidence)


@pytest.mark.parametrize("code,price,previous", [("A.688585",189.02,180.02),("A.300825",10.96,10.76),("A.301321",34.44,33.68)])
def test_positive_last_is_not_overwritten_by_unready_open(code, price, previous):
    row = native_row(code=code, last_price=price, prev_close_price=previous)
    before = deepcopy(row)
    result = select(row)
    output = result["rows"][0]
    assert output["current_change_pct"] == round((price/previous-1)*100,4)
    assert output["scoring_price"] == price
    assert output["price_basis"] == "NATIVE_LAST_PRICE_OBSERVATION"
    assert output["open_price"] is None and output["high_price"] is None
    assert output["qmt_amount"] is None
    assert output["field_readiness"]["open_price"] == "UNKNOWN"
    assert output["score"] == min(100, max(0, round(50+min(10,(price/previous-1)*100)*10,6)))
    assert output["trade_status"] == "WATCH_ONLY" and output["action_level"] == "NO_BUY"
    assert result["cannot_confirm"] and row == before


@pytest.mark.parametrize("field", ["last_price", "prev_close_price"])
@pytest.mark.parametrize("value", [None,0,-1,float("nan"),float("inf")])
def test_invalid_native_price_is_explicitly_isolated(field,value):
    result=select(native_row(**{field:value}))
    assert result["rows"] == []
    assert result["cannot_confirm"]


@pytest.mark.parametrize("change", [dict(native_captured_at="2026-11-09T09:25:05.000001+08:00"),
                                   dict(native_source_update_time="2026-11-08 09:30:00"),
                                   dict(is_open_call_auction_match=True)])
def test_native_clock_and_non_transaction_boundary_remain_closed(change):
    assert select(native_row(**change))["rows"] == []


def test_normal_transaction_price_and_score_are_unchanged():
    row=dict(code="A.000001",time="09:25",price=11,prev_close_price=10,amount=1e8,
             bid_vol=600,ask_vol=400,is_open_call_auction_match=True)
    result=select(row,())
    expected=min(100,selection.live_stage_quality_score(dict(open=11,lastPrice=11,lastClose=10,
                amount=1e8,bidVol=600,askVol=400),{},"STAGE_0925"))
    assert result["rows"][0]["score"] == expected
    assert result["rows"][0]["source_mode"] == "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"


def test_bad_transaction_price_does_not_fallback_to_quote():
    result=select(dict(code="A.000001",time="09:25",price=0,last_price=11,
                       prev_close_price=10,is_open_call_auction_match=True),())
    assert result["rows"] == [] and result["cannot_confirm"]


def test_native_readiness_has_new_identity_and_old_hashes_are_readable():
    result=select(native_row())
    assert result["algorithm_sha256"] not in {selection.A_SHARE_LIVE_ALGORITHM_SHA256,
                                             selection.LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256}
    assert selection.A_SHARE_LIVE_ALGORITHM_SHA256 in selection.ALGORITHM_SHA_ALLOWLIST
    assert selection.LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256 in selection.ALGORITHM_SHA_ALLOWLIST


def test_normal_native_open_price_keeps_old_score_and_valid_card_levels():
    row=native_row(open_price=188, high_price=190, low_price=187, amount=1e7, volume=100)
    result=select(row)["rows"][0]
    assert result["price_basis"] == "NATIVE_OPEN_PRICE_OBSERVATION"
    assert result["score"] == min(100,selection.live_stage_quality_score(
        dict(open=188,lastPrice=188,lastClose=row["prev_close_price"],amount=1e7,bidVol=100,askVol=100),{},"STAGE_0925"))
    assert result["support"] == 187 and result["pressure"] == 190


def test_capture_readiness_describes_partial_fields_without_altering_rows():
    from infrastructure.stage_quote_provider import native_opening_field_readiness
    rows=[dict(last_price=11,prev_close_price=10,open_price=0,high_price=None,low_price=float("inf"),turnover=0,volume=0),
          dict(last_price=12,prev_close_price=10,open_price=11,high_price=12,low_price=11,turnover=100,volume=10)]
    before=deepcopy(rows)
    result=native_opening_field_readiness(rows)
    assert result["positive_finite_rows"]["last_price"] == 2
    assert result["positive_finite_rows"]["open_price"] == 1
    assert result["all_fields_positive_finite_rows"] == 1
    assert result["status"] == "PARTIAL_OR_UNKNOWN"
    assert result["auction_transaction_certified"] is False
    assert rows == before
