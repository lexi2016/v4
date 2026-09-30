"""Focused compatibility surface for the proven HK Stage 8 chain."""

from .builders import production_natural_collectors, should_use_natural_route
from .precapture import prepare_due_snapshot
from .snapshot import (
    _HK_ACTIVE_SNAPSHOT_DIR,
    _HK_ACTIVE_SNAPSHOT_SAFETY,
    _HK_ACTIVE_SNAPSHOT_SCHEMA,
    _atomic_snapshot_create,
    _canonical_snapshot_codes,
    _futu_snapshot_probe,
    _snapshot_codes_sha,
    _snapshot_cutoff_iso,
    _snapshot_path,
    _snapshot_rows_sha,
    load_hk_active_snapshot,
    prepare_hk_active_snapshot,
)
from .rtdata import (
    _SHANGHAI,
    _STAGE8_CAPTURE_START_AT,
    _STAGE8_CUTOFF_AT,
    _STAGE8_NATURAL_SOURCE,
    _STAGE8_RT_DATA_BATCH_SIZE,
    _STAGE8_START_AT,
    _collect_hk_stage8_natural,
    _fetch_hk_stage8_rtdata,
    _rt_data_records,
    _stage8_active_snapshot_codes,
    _stage8_aggregate_rtdata_rows,
    _stage8_market_timestamp,
)

__all__ = [
    "load_hk_active_snapshot",
    "prepare_hk_active_snapshot",
    "prepare_due_snapshot",
    "production_natural_collectors",
    "should_use_natural_route",
]
