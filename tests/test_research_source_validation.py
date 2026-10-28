from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from domains.research_source_validation import (
    collector_source_cutoff,
    legacy_source_time,
    runner_manual_empty_time_shape,
    runner_source_cutoff,
    runner_timestamp,
    strict_source_receipt_time,
    validate_hourly_stage_source,
    validate_runner_point_in_time_source,
)


def test_collector_and_runner_keep_their_distinct_cutoff_precision() -> None:
    collector = collector_source_cutoff("20261012", "1700")
    runner = runner_source_cutoff("20261012", "1700")

    assert collector.isoformat(timespec="microseconds") == "2026-10-12T17:00:59.000000+08:00"
    assert runner.isoformat(timespec="microseconds") == "2026-10-12T17:00:59.999999+08:00"
    assert strict_source_receipt_time("2026-10-12T17:00:59") is None
    assert legacy_source_time("2026-10-12T17:00:59").utcoffset() == timedelta(hours=8)
    assert runner_timestamp("2026-10-12T17:00:59", "fixture").utcoffset() == timedelta(hours=8)


def test_runner_point_in_time_boundary_is_inclusive_through_final_microsecond() -> None:
    source = {
        "source_manifest": {
            "hourly_slot": "1700",
            "generated_at": "2026-10-12T17:00:59.999999+08:00",
            "published_at": "2026-10-12T17:00:59.999999+08:00",
        },
        "stock_research_timeline": [],
        "stock_research_daily": [],
    }

    validate_runner_point_in_time_source(
        source, business_date="20261012", slot="1700"
    )
    source["source_manifest"]["published_at"] = "2026-10-12T17:01:00+08:00"
    with pytest.raises(ValueError, match="point-in-time safe"):
        validate_runner_point_in_time_source(
            source, business_date="20261012", slot="1700"
        )


def test_stage_check_uses_callers_actual_cutoff_and_observation_exception() -> None:
    cutoff = datetime.fromisoformat("2026-10-12T17:00:01+08:00")
    source = {
        "trade_date": "20261012",
        "slot": "1700",
        "source_manifest": {
            "trade_date": "20261012",
            "hourly_slot": "1700",
            "producer": "ops.collect_hourly_research_input",
            "pit_cutoff": "2026-10-12T17:00:59+08:00",
            "generated_at": "2026-10-12T17:00:00+08:00",
            "published_at": "2026-10-12T17:00:00+08:00",
        },
        "raw_items": [],
        "research_items": [],
        "stock_research_timeline": [{
            "trade_date": "20261012",
            "slot": "1700",
            "last_checked_at": (cutoff + timedelta(seconds=1)).isoformat(),
        }],
        "stock_research_daily": [],
    }
    manifest_pit_cutoff = runner_source_cutoff("20261012", "1700").replace(
        microsecond=0
    )

    with pytest.raises(ValueError, match="HOURLY_SOURCE_ROW_PIT_MISMATCH"):
        validate_hourly_stage_source(
            source,
            trade_date="20261012",
            slot="1700",
            cutoff=cutoff,
            manifest_pit_cutoff=manifest_pit_cutoff,
        )
    validate_hourly_stage_source(
        source,
        trade_date="20261012",
        slot="1700",
        cutoff=cutoff,
        allow_late_observations=True,
        manifest_pit_cutoff=manifest_pit_cutoff,
    )


def test_runner_empty_time_shape_is_narrow_and_does_not_require_a_proof() -> None:
    source = {
        "source_manifest": {
            "materialization_origin": "MANUAL_RECOVERY",
            "capture_origin": "ORIGINAL_SLOT",
            "original_time_capture": True,
            "natural_execution_verified": False,
        },
        "hourly_research": {"status": "READY_EMPTY", "row_count": 0},
        "raw_items": [],
        "research_items": [],
        "stock_research_timeline": [],
        "stock_research_daily": [],
    }

    assert runner_manual_empty_time_shape(
        source, business_date="20261012", slot="1700", mode="LIVE"
    )
    assert not runner_manual_empty_time_shape(
        source, business_date="20261013", slot="1700", mode="LIVE"
    )
