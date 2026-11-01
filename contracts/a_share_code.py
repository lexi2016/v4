"""A-share security identity.

A six-digit token is not automatically an A-share code. Titles and filenames
carry dates in the same shape ("更新261029", "...-261030.pdf"), and treating
those as codes silently invents an entity that no source data can verify.

The accepted prefixes below were taken from the codes that actually appear in
the research pools, not from memory: 00/30/60/68/92 are the stock ranges and
15/16/18/51/52/56/58 are the fund and ETF ranges that share the pool.
"""
from __future__ import annotations

import re
from typing import Any

_SIX_DIGITS = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?(?!\d)", re.IGNORECASE)
_EXACT = re.compile(r"(?:A\.)?(\d{6})", re.IGNORECASE)

PREFIXES = frozenset({
    "00", "30",              # SZ 主板 / 创业板
    "60", "68",              # SH 主板 / 科创板
    "15", "16", "18",        # SZ 基金、ETF
    "51", "52", "56", "58",  # SH 基金、ETF
    "43", "83", "87", "88",  # 北交所、原新三板
    "92",                    # 北交所新号段
})


def is_a_share_code(code: str) -> bool:
    """True only for a six-digit code whose prefix is a real A-share range."""
    return bool(re.fullmatch(r"\d{6}", code)) and code[:2] in PREFIXES


def a_share_symbol(value: Any) -> str:
    """Return ``A.<code>`` for the first valid code in a value, else ``""``.

    Every six-digit token is considered, not just the first one: a title can
    carry a date before the code ("更新261029 600519"). A token that is part of
    a longer digit run is not a code, so "6005191" yields nothing. A value with
    no valid code yields no symbol: dropping an unverifiable row is the
    intended behaviour, never inventing one.
    """
    for match in _SIX_DIGITS.finditer(str(value or "")):
        if is_a_share_code(match.group(1)):
            return f"A.{match.group(1)}"
    return ""


def canonical_a_share_code(value: Any) -> str:
    """Return ``A.<code>`` only when the whole value is an A-share code."""
    match = _EXACT.fullmatch(str(value or "").strip().upper())
    return f"A.{match.group(1)}" if match and is_a_share_code(match.group(1)) else ""
