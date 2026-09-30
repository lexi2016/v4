"""Frozen contracts for the shared live A-share minute acquisition core.

Deterministic pure contracts only: no host/V3 paths, no runtime reads, no
network. These exact values are frozen by the DS2B test suite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Fixed source priority: Futu OpenD -> PyTDX -> QMT/TDXQT. Never reordered.
SOURCE_PRIORITY = ("futu", "pytdx", "qmt_tdxqt")

# Six A-share minute stages only, each mapped to
# (window_start, window_end, cutoff_at) as "%H:%M:%S" strings.
# window_end carries the +5 seconds for the first three stages, so a bar
# labelled 09:35:00 is included for STAGE_0930_0935 (09:31:00 <= t < 09:35:05).
STAGE_WINDOWS = {
    "STAGE_0930_0935": ("09:30:00", "09:35:05", "09:35:05"),
    "STAGE_0935_0940": ("09:35:00", "09:40:05", "09:40:05"),
    "STAGE_0940_0945": ("09:40:00", "09:45:05", "09:45:05"),
    "STAGE_0945_1030": ("09:45:00", "10:30:00", "10:30:00"),
    "STAGE_1300_1315": ("13:00:00", "13:15:00", "13:15:00"),
    "STAGE_1445_1500": ("14:45:00", "15:00:00", "15:00:00"),
    "STAGE_1545_1555": ("15:45:00", "15:55:05", "15:55:05"),
}

MARKETS = ("A_SHARE", "HK_CONNECT")
STAGE_MARKETS = {
    stage_id: (("HK_CONNECT",) if stage_id == "STAGE_1545_1555" else MARKETS)
    for stage_id in STAGE_WINDOWS
}


def market_role(market: str, stage_id: str) -> str:
    """Return the frozen shared-store role for one market/stage slot."""
    if market not in MARKETS:
        raise ValueError(f"unknown market {market!r}")
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    if market not in STAGE_MARKETS[stage_id]:
        raise ValueError(f"market {market!r} is not in stage {stage_id!r}")
    return f"{market}_1MIN_{stage_id}"

# Exact V3 19-field normalized minute row (header of the frozen V3 oracle CSV
# runs/20260806/STAGE_0930_0935/adapter_futu_STAGE_0930_0935.csv).
NORMALIZED_MINUTE_FIELDS = (
    "batch_index",
    "code",
    "name",
    "update_time",
    "last_price",
    "open_price",
    "high_price",
    "low_price",
    "prev_close_price",
    "turnover",
    "volume",
    "bid_price",
    "ask_price",
    "bid_vol",
    "ask_vol",
    "window_start",
    "window_end",
    "bar_count",
    "temporal_cutoff_safe",
)

# Persisted artifact: trade_date and bar_time (time-of-day of update_time)
# prefixed to the exact 19 V3 fields.
ARTIFACT_FIELDS = ("trade_date", "bar_time") + NORMALIZED_MINUTE_FIELDS


@dataclass(frozen=True)
class StageSourceResult:
    """One live acquisition attempt from a single source.

    ``rows`` are 19-field normalized minute dicts (NORMALIZED_MINUTE_FIELDS);
    ``cannot_confirm`` carries explicit evidence that forbids upgrading this
    result to READY.
    """

    source_id: str
    display_name: str
    status: str
    fidelity: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    cannot_confirm: list[str] = field(default_factory=list)
    requested_code_count: int = 0
    completed_code_count: int = 0
    no_data_codes: list[str] = field(default_factory=list)
    name_dictionary_sha256: str = ""
