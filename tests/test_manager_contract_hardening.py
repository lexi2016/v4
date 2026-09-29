"""Contract-hardening regressions for the V4 manager job (audit F05/F03).

Converted from the independent audit probes R02/R03/R04: observation times
must be real target-date bar times at or before the fixed 09:40 cut-off,
row-level identity claims must agree with the requested identity, and rows
carrying nested trading semantics are rejected before any job is admitted.
"""
from __future__ import annotations

import pytest

from v4.manager_research.contracts import ContractError, normalise_observation_input


def _payload(row_time: object = "2026-09-08 09:40:00", **row_extra) -> dict:
    row = {"code": "HK.00123", "name": "测试标的", "rank": 1, **row_extra}
    if row_time is not None:
        row["source_last_bar_time"] = row_time
    return {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "markets": {
            "HK_CONNECT": {
                "rows": [row],
                "cannot_confirm": [],
            }
        },
    }


def test_valid_target_date_cutoff_time_passes() -> None:
    result = normalise_observation_input(_payload())
    assert result["rows"][0]["source_last_bar_time"] == "2026-09-08 09:40:00"
    assert result["target_trade_date"] == "20260908"


def test_iso_t_shape_before_cutoff_passes() -> None:
    result = normalise_observation_input(_payload("2026-09-08T09:39:59"))
    assert result["rows"][0]["source_last_bar_time"] == "2026-09-08T09:39:59"


@pytest.mark.parametrize(
    "row_time,case_id",
    [
        (None, "absent"),
        ("", "empty"),
        ("   ", "blank"),
        ("NOT_A_TIMESTAMP", "invalid"),
        ("2026-09-08 16:00:00", "after-cutoff"),
        ("2026-09-08 09:40:01", "one-second-after-cutoff"),
        ("2026-09-07 09:40:00", "cross-date"),
    ],
    ids=lambda value: value if isinstance(value, str) else "absent",
)
def test_invalid_or_post_cutoff_times_fail_closed(row_time: object, case_id: str) -> None:
    with pytest.raises(ContractError):
        normalise_observation_input(_payload(row_time))


@pytest.mark.parametrize(
    "field,value,case_id",
    [
        ("market", "A_SHARE", "market-conflict"),
        ("stage_id", "STAGE_1545_1555", "stage-conflict"),
        ("target_trade_date", "20260907", "date-conflict"),
    ],
    ids=["market-conflict", "stage-conflict", "date-conflict"],
)
def test_row_level_identity_conflicts_are_rejected(field: str, value: str, case_id: str) -> None:
    with pytest.raises(ContractError, match="conflicts"):
        normalise_observation_input(_payload(**{field: value}))


def test_exact_market_spelling_passes_and_aliases_fail_closed() -> None:
    result = normalise_observation_input(_payload(market="HK_CONNECT"))
    assert result["rows"][0]["market"] == "HK_CONNECT"
    for wrong in ("HK", "A_SHARE"):
        with pytest.raises(ContractError, match="conflicts"):
            normalise_observation_input(_payload(market=wrong))


def test_legacy_integer_order_alias_is_recognized() -> None:
    # Real selection rows carry ``order`` as the legacy rank position; it is
    # an accepted alias (kept for evidence and identity compatibility), not
    # an order instruction.
    result = normalise_observation_input(_payload(order=1))
    row = result["rows"][0]
    assert row["order"] == 1
    assert row["stage_rank"] == 1


def test_non_integer_order_field_still_fails_closed() -> None:
    with pytest.raises(ContractError, match="legacy order must equal validated stage_rank"):
        normalise_observation_input(_payload(order="BUY"))


@pytest.mark.parametrize(
    "unsafe,case_id",
    [
        ({"orders_sent": True}, "top-level-flag"),
        ({"meta": {"production_allowed": True}}, "nested-flag"),
        ({"meta": [{"buy": "YES"}]}, "nested-action"),
        ({"meta": ({"orders_sent": True},)}, "tuple-nested-flag"),
    ],
    ids=["top-level-flag", "nested-flag", "nested-action", "tuple-nested-flag"],
)
def test_rows_carrying_nested_trading_semantics_are_rejected(unsafe: dict, case_id: str) -> None:
    with pytest.raises(ContractError, match="unsafe observation row"):
        normalise_observation_input(_payload(**unsafe))
