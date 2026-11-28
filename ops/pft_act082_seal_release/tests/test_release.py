"""Safety checks for the authorized SEALED extension. No real identities."""

import os
import stat
from math import log
from statistics import stdev
from types import SimpleNamespace

import pytest

from ops.pft_act082_seal_release.inputs import CUTOFF, HISTORY_START, QUOTE_COLUMNS, read_at_cutoff
from ops.pft_act082_seal_release.run import _eligible_metadata, _profiles, append_truncation_denial, quote_profiles


def test_quote_adapter_rejects_postcutoff_bound_before_read():
    def fail(*args, **kwargs):
        raise AssertionError("reader called despite disallowed query")

    reader = SimpleNamespace(read_table=fail)
    with pytest.raises(ValueError, match="outside authorized cutoff"):
        read_at_cutoff(reader, "", kind="quote", earliest=HISTORY_START, latest=20251001)


def test_quote_adapter_fixes_projection_and_rejects_postcutoff_return():
    table = SimpleNamespace(column_names=list(QUOTE_COLUMNS),
                            to_pylist=lambda: [{"trade_date": 20251001}], nbytes=20)

    def projected(path, *, columns, filters):
        assert columns == list(QUOTE_COLUMNS)
        assert ("trade_date", "<=", CUTOFF) in filters
        return table

    with pytest.raises(ValueError, match="disallowed quote date"):
        read_at_cutoff(SimpleNamespace(read_table=projected), "", kind="quote",
                       earliest=HISTORY_START, latest=CUTOFF)


def test_only_f10_metadata_is_allowed_its_later_source_date():
    old, new = "830001.BJ", "920001.BJ"
    aliases = {old: new, new: new}
    metadata = _eligible_metadata([{
        "ts_code": old, "trade_date": str(CUTOFF), "market_type": "BJ",
        "tdx_finance_industry_code": "F10-01", "market_cap_yi": 10.0, "finance_source_date": 20260713.0,
    }, {
        "ts_code": new, "trade_date": str(CUTOFF), "market_type": "BJ",
        "tdx_finance_industry_code": "", "market_cap_yi": None, "finance_source_date": None,
    }], aliases)
    assert len(metadata) == 1
    record = _profiles(metadata, {new: (CUTOFF, .1)}, required_day=CUTOFF)[new]
    assert (record["asof"], record["f10_source_date"], record["industry"]) == (
        "2025-09-30", "2026-07-13", "F10-01",
    )
    assert _profiles(metadata, {new: (20250929, .1)}, required_day=CUTOFF) == {}


def test_pre_cut_log_returns_combine_alias_same_session_once():
    old, new = "830001.BJ", "920001.BJ"
    aliases = {old: new, new: new}
    prices = [{"ts_code": old, "trade_date": 20250900+i, "close": 10.+i/10} for i in range(10, 31)]
    prices.append(dict(prices[-1], ts_code=new, close=20.))
    quote, collapsed = quote_profiles(prices, aliases, {new})
    observed_once = [row["close"] for row in prices[:-2]] + [20.]
    expected = stdev(log(b) - log(a) for a, b in zip(observed_once, observed_once[1:]))
    assert list(quote) == [new]
    assert collapsed == 1 and quote[new][0] == CUTOFF and quote[new][1] == expected
    with pytest.raises(ValueError, match="uncut market price"):
        quote_profiles(prices + [dict(prices[-1], trade_date=20251001)], aliases, {new})


def test_actual_os_append_only_denial_probe_is_nondestructive(tmp_path):
    audit = tmp_path / "audit"
    fixture = b"synthetic only\n"
    audit.write_bytes(fixture)
    os.chflags(audit, stat.UF_APPEND)
    try:
        proof = append_truncation_denial(audit)
        assert proof["truncation_denied"] and proof["audit_unchanged"]
        assert audit.read_bytes() == fixture
    finally:
        os.chflags(audit, 0)

