"""Pure timestamp and point-in-time checks for hourly research sources."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TIMELINE_TIME_FIELDS = (
    "event_time",
    "source_published_at",
    "first_seen_at",
    "last_checked_at",
)
_DAILY_TIME_FIELDS = ("first_seen_time", "last_seen_time")
_LATE_RECOVERY_OBSERVATION_FIELDS = frozenset(
    {"first_seen_at", "last_checked_at", "first_seen_time", "last_seen_time"}
)
_HOURLY_SOURCE_TIMES = (
    "event_time", "published_at", "source_published_at", "first_seen_at",
    "last_checked_at", "crawl_time", "display_event_time", "first_seen_time",
    "last_seen_time",
)
_HOURLY_OBSERVATION_TIMES = frozenset({
    "first_seen_at", "last_checked_at", "crawl_time", "first_seen_time",
    "last_seen_time",
})


def strict_source_receipt_time(value: Any) -> datetime | None:
    """Parse a receipt timestamp only when it contains an explicit timezone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_SHANGHAI)


def legacy_source_time(value: Any) -> datetime:
    """Interpret naive legacy producer timestamps in Asia/Shanghai."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("HOURLY_SOURCE_PIT_TIMESTAMP_MISSING")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=_SHANGHAI)
        if parsed.tzinfo is None
        else parsed.astimezone(_SHANGHAI)
    )


def runner_timestamp(value: Any, field: str) -> datetime:
    """Parse runner timestamps, retaining legacy naive-time interpretation."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"hourly research point-in-time field is missing: {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"invalid hourly research point-in-time field: {field}"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def collector_source_cutoff(business_date: str, slot: str) -> datetime:
    """Collector/source-receipt cutoff, rounded to the slot's :59 second."""
    return datetime.strptime(
        business_date + slot, "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59)


def runner_source_cutoff(business_date: str, slot: str) -> datetime:
    """Runner cutoff preserves its inclusive final microsecond boundary."""
    return datetime.strptime(
        f"{business_date}{slot}", "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59, microsecond=999999)


def runner_manual_empty_time_shape(
    source: Mapping[str, Any], *, business_date: str, slot: str, mode: str
) -> bool:
    """Recognize the narrow 20261012/1700 empty timestamp shape.

    This shape permits the separate PIT-time check to represent the genuine
    materialization clock. It does not authenticate the receipt or authorize
    publication; callers must independently verify the READY_EMPTY proof.
    """
    manifest = source.get("source_manifest")
    hourly = source.get("hourly_research")
    return (
        (business_date, slot, mode)
        == ("20261012", "1700", "LIVE")
        and isinstance(manifest, dict)
        and manifest.get("materialization_origin") == "MANUAL_RECOVERY"
        and manifest.get("capture_origin") == "ORIGINAL_SLOT"
        and manifest.get("original_time_capture") is True
        and manifest.get("natural_execution_verified") is False
        and isinstance(hourly, dict)
        and hourly.get("status") == "READY_EMPTY"
        and type(hourly.get("row_count")) is int
        and hourly.get("row_count") == 0
        and all(
            source.get(name) == []
            for name in (
                "raw_items", "research_items", "stock_research_timeline",
                "stock_research_daily",
            )
        )
    )


def validate_runner_point_in_time_source(
    source: dict[str, Any],
    *,
    business_date: str,
    slot: str,
    allow_late_observation_times: bool = False,
    allow_manual_materialization: bool = False,
    publication_available_at: datetime | None = None,
) -> None:
    """Validate runner manifest times and the two stock projection collections."""
    manifest = source.get("source_manifest")
    if not isinstance(manifest, dict) or manifest.get("hourly_slot") != slot:
        raise ValueError("hourly research source slot is missing or mismatched")
    cutoff = runner_source_cutoff(business_date, slot)
    manifest_times = [
        (field, manifest[field])
        for field in ("generated_at", "published_at")
        if manifest.get(field) not in {None, ""}
    ]
    if not manifest_times:
        raise ValueError(
            "hourly research point-in-time manifest timestamp is missing"
        )
    manual_materialization = False
    if allow_manual_materialization:
        materialized = manifest.get("materialized_at")
        try:
            materialized_time = runner_timestamp(
                materialized, "source_manifest.materialized_at"
            )
        except ValueError:
            materialized_time = None
        manual_materialization = (
            manifest.get("materialization_origin") == "MANUAL_RECOVERY"
            and manifest.get("capture_origin") == "ORIGINAL_SLOT"
            and manifest.get("original_time_capture") is True
            and manifest.get("natural_execution_verified") is False
            and materialized_time is not None
            and materialized_time.strftime("%Y%m%d") == business_date
            and materialized_time >= cutoff
            and manifest.get("generated_at") == materialized
            and manifest.get("published_at") == materialized
        )
    if publication_available_at is not None:
        if (publication_available_at.tzinfo is None
            or publication_available_at.strftime("%Y%m%d") != business_date):
            raise ValueError("hourly research publication date invalid")
    for field, value in manifest_times:
        if (
            runner_timestamp(value, f"source_manifest.{field}") > (publication_available_at or cutoff)
            and not manual_materialization
        ):
            raise ValueError("hourly research source is not point-in-time safe")
    for collection, fields in (
        ("stock_research_timeline", _TIMELINE_TIME_FIELDS),
        ("stock_research_daily", _DAILY_TIME_FIELDS),
    ):
        rows = source.get(collection)
        if not isinstance(rows, list):
            raise ValueError(f"hourly research source {collection} is missing")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"hourly research source {collection} is invalid")
            for field in fields:
                value = row.get(field)
                if value in {None, ""}:
                    continue
                parsed = runner_timestamp(value, f"{collection}[{index}].{field}")
                bound = (publication_available_at if publication_available_at is not None
                         and field in _LATE_RECOVERY_OBSERVATION_FIELDS else cutoff)
                if (
                    parsed > bound
                    and not (
                        allow_late_observation_times
                        and field in _LATE_RECOVERY_OBSERVATION_FIELDS
                    )
                ):
                    raise ValueError(
                        "hourly research source is not point-in-time safe"
                    )


def validate_hourly_stage_source(
    source: Mapping[str, Any],
    *,
    trade_date: str,
    slot: str,
    cutoff: datetime,
    allow_late_observations: bool = False,
    allow_manual_materialization: bool = False,
    manifest_pit_cutoff: datetime | None = None,
) -> None:
    """Validate stage input and the times omitted by archive projection.

    Stage boundaries use the caller's actual cutoff. Only the original CLI
    recovery may allow late observation fields; the manual timestamp shape is
    a time exception and does not establish READY_EMPTY authorization.
    """
    manifest = source.get("source_manifest")
    if (
        source.get("trade_date") != trade_date
        or not isinstance(manifest, Mapping)
        or manifest.get("hourly_slot") != slot
    ):
        raise ValueError("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    if source.get("slot", slot) != slot or manifest.get("trade_date", trade_date) != trade_date:
        raise ValueError("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    declared_pit_cutoff = manifest.get("pit_cutoff")
    requires_pit_cutoff = bool(
        source.get("slot") == slot
        or manifest.get("producer") == "ops.collect_hourly_research_input"
        or manifest.get("capture_origin") == "ORIGINAL_SLOT"
        or declared_pit_cutoff not in (None, "")
    )
    if declared_pit_cutoff in (None, ""):
        if requires_pit_cutoff:
            raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISSING")
    else:
        declared_cutoff = legacy_source_time(declared_pit_cutoff)
        expected_cutoff = (manifest_pit_cutoff or cutoff).replace(microsecond=0)
        if declared_cutoff != expected_cutoff:
            raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISMATCH")
    manual_materialization = False
    if allow_manual_materialization:
        materialized = manifest.get("materialized_at")
        if materialized not in (None, ""):
            materialized_time = legacy_source_time(materialized)
            manual_materialization = (
                manifest.get("materialization_origin") == "MANUAL_RECOVERY"
                and manifest.get("capture_origin") == "ORIGINAL_SLOT"
                and manifest.get("original_time_capture") is True
                and manifest.get("natural_execution_verified") is False
                and materialized_time.strftime("%Y%m%d") == trade_date
                and materialized_time >= cutoff
                and manifest.get("generated_at") == materialized
                and manifest.get("published_at") == materialized
            )
    for name in ("generated_at", "published_at"):
        if manifest.get(name) not in (None, ""):
            value = legacy_source_time(manifest[name])
            if value.strftime("%Y%m%d") != trade_date or (
                value > cutoff and not manual_materialization
            ):
                raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_MISMATCH")
    for name in ("raw_items", "research_items", "stock_research_timeline", "stock_research_daily"):
        rows = source.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("HOURLY_SOURCE_ROWS_INVALID:" + name)
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("HOURLY_SOURCE_ROW_INVALID:" + name)
            values = [row]
            if name == "raw_items" and "raw_payload" in row:
                if not isinstance(row["raw_payload"], Mapping):
                    raise ValueError("HOURLY_SOURCE_RAW_PAYLOAD_INVALID")
                values.append(row["raw_payload"])
            for value in values:
                if value.get("trade_date", trade_date) != trade_date or value.get("slot", slot) != slot:
                    raise ValueError("HOURLY_SOURCE_ROW_DATE_SLOT_MISMATCH")
                for field in _HOURLY_SOURCE_TIMES:
                    if value.get(field) in (None, ""):
                        continue
                    if legacy_source_time(value[field]) > cutoff and not (
                        allow_late_observations
                        and field in _HOURLY_OBSERVATION_TIMES
                    ):
                        raise ValueError(
                            "HOURLY_SOURCE_ROW_PIT_MISMATCH:" + name + "." + field
                        )


__all__ = [
    "collector_source_cutoff",
    "legacy_source_time",
    "runner_manual_empty_time_shape",
    "runner_source_cutoff",
    "runner_timestamp",
    "strict_source_receipt_time",
    "validate_hourly_stage_source",
    "validate_runner_point_in_time_source",
]
