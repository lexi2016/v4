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


@pytest.mark.parametrize("field", ["open_price", "high_price", "low_price", "turnover", "volume"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_optional_unknown_survives_native_snapshot_collector_raw_and_selector(tmp_path, field, value):
    """Exercise the real adapter boundary, rather than only pure selection."""
    from datetime import datetime
    from infrastructure.stage_quote_provider import NativeAOpeningSnapshotProvider, write_native_a_opening_snapshot
    from stage_center.acquisition import build_plan
    from stage_center.candidate_input import CandidateInput
    from stage_center.live_collectors import collect_a_share_auction, production_selection_builders
    from stage_center.raw_store import RAW_FIELDS, validate_rows

    at=datetime.fromisoformat("2026-11-09T09:25:01+08:00")
    candidate=CandidateInput(root=tmp_path,trade_date="20261109",current_relative="current.json",current_sha256="c"*64,
        run_id="optional-readiness",codes=("A.000001",),artifact_sha256="a"*64,manifest_sha256="b"*64,
        receipt_sha256="d"*64,source_projection_sha256="e"*64,source_evidence=())
    quote=dict(symbol="A.000001",last_price=11,prev_close_price=10,open_price=11,high_price=11,low_price=11,
               turnover=1000,volume=100,source_update_time="2026-11-09 09:25:01")
    quote[field]=value
    class Primary:
        def snapshot(self, *args, **kwargs):
            return dict(trade_date="20261109",stage_id="STAGE_0925",rows=[quote],capture_started_at=at.isoformat(),
                        captured_at=at.isoformat(),production_allowed=False,buy_gate_updated=False,orders_sent=False)
    class NoFallback:
        def snapshot(self, *args, **kwargs):
            pytest.fail("a valid snapshot must not query a fallback")
    payload=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=NoFallback(),now=lambda:at).snapshot(candidate.codes,trade_date="20261109")
    assert len(payload["rows"]) == 1
    write_native_a_opening_snapshot(tmp_path,payload,candidate)
    plan=build_plan(tmp_path,"20261109","STAGE_0925",candidate=candidate)
    source=collect_a_share_auction(plan,codes=candidate.codes,python_path="/unused",shared_root=tmp_path,auction_root=tmp_path)
    assert len(source.rows) == 1
    assert source.rows[0][field] is None
    projection=[{key:row.get(key,"") for key in RAW_FIELDS} for row in source.rows]
    checked,issues=validate_rows(projection,trade_date="20261109",stage_id="STAGE_0925",market="A_SHARE")
    assert len(checked) == 1 and not issues
    raw=dict(artifact_sha256="a"*64,status=source.status,requested_rows=1,missing_symbols=(),
             cannot_confirm=source.cannot_confirm,source_evidence=source.source_evidence,cutoff_at="09:25:05")
    result=production_selection_builders("STAGE_0925")["A_SHARE"](source,plan,raw)
    selected=result["rows"][0]
    assert selected["scoring_price"] == 11 and selected["qmt_gap_pct"] == 10
    selected_field="amount" if field == "turnover" else field
    assert selected["field_readiness"][selected_field] == "UNKNOWN"
    if field in ("open_price", "high_price", "low_price"):
        assert selected[field] is None
    if field == "turnover":
        assert selected["qmt_amount"] is None
    assert selected["trade_status"] == "WATCH_ONLY" and selected["action_level"] == "NO_BUY"
