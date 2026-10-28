"""Bounded instrument-family admission for the A-stock research lanes.

This is NOT a security master, listing/PIT/tradability proof, or BUY gate.
Keep existing date, source, and availability checks.  Code families exclude
funds/ETFs, bonds, indices and subscription codes; supplied exchange/type
metadata can veto an otherwise equity-shaped code.  Unqualified 000001
retains the existing Shenzhen-stock interpretation, whereas 000001.SH is
an index and is rejected.  Names are descriptive and never classify a row.

References (checked 2026-10-22):
https://www.szse.cn/marketServices/technicalservice/index.html
https://www.sse.com.cn/assortment/stock/list/share/
https://www.bse.cn/service/code_mapping.html
Legacy 43/83/87 equity families are kept for historical-source compatibility,
not asserted to be current BSE listings.  STAR CDR689 is retained as equity.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

A_STOCK_INSTRUMENT_CONTRACT = "A_STOCK_INSTRUMENT_FAMILY_V1"
_CODE = re.compile(r"(?:A\.)?(\d{6})(?:\.(SH|SZ|BJ))?\Z", re.ASCII)
_NON_STOCK_TYPES = frozenset({
    "ETF", "FUND", "MUTUALFUND", "LOF", "REIT", "REITS", "INDEX", "IDX",
    "BOND", "CONVERTIBLEBOND", "WARRANT", "OPTION", "FUTURE", "FUTURES",
    "REPO", "BSHARE", "PREFERRED", "PREFERREDSTOCK",
    "基金", "指数", "债券", "可转债", "期权", "权证", "优先股",
})


def a_share_instrument_rejection(value: Any, row: Mapping[str, Any] | None = None) -> str | None:
    """Return an exclusion reason, or None for an equity-family candidate."""
    match = _CODE.fullmatch(str(value or "").strip().upper())
    if match is None:
        return "INVALID_A_STOCK_CODE"
    code, suffix = match.groups()
    if code.startswith(("00", "30")):
        exchange = "SZ"
    elif code.startswith(("60", "688", "689")):
        exchange = "SH"
    elif code.startswith(("920", "43", "83", "87")):
        exchange = "BJ"
    else:
        return "NON_EQUITY_CODE_FAMILY"
    # Existing V3-derived BSE rows sometimes retain .SZ source suffixes;
    # their920/43/83/87 equity family remains authoritative for TYPE only.
    if suffix and suffix != exchange and exchange != "BJ":
        return "NON_EQUITY_EXCHANGE_CODE"
    if row is not None:
        for key in ("instrument_type", "security_type", "stock_type", "sec_type"):
            kind = re.sub(r"[\s_-]", "", str(row.get(key) or "")).upper()
            if kind in _NON_STOCK_TYPES:
                return f"NON_EQUITY_TYPE:{key}={kind}"
        # Do not lose exchange information when an upstream normalized A.*
        # symbol accompanies a more specific source code (e.g.000001.SH).
        for key in ("ts_code", "stock_code", "code", "symbol"):
            other = _CODE.fullmatch(str(row.get(key) or "").strip().upper())
            if other and other.group(2) and other.group(2) != exchange and exchange != "BJ":
                return f"NON_EQUITY_EXCHANGE_CODE:{key}"
    return None


def a_share_row_code(row: Mapping[str, Any]) -> str:
    """Use the stage contract's existing field precedence, without guessing."""
    return str(next((row[key] for key in ("symbol", "normalized_code", "code", "stock_code", "ts_code")
                     if row.get(key) not in (None, "")), ""))
