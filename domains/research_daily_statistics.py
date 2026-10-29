"""Pure descriptive statistics for explicitly supplied daily event groups.

This module deliberately does not fetch prices, infer event rules, or bind an
input to a producer. The caller supplies approved close rows, an authoritative
market calendar, and already-evaluated event dates plus their source identity.
"""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import mean, median
from typing import Any

_REQUIRED_IDENTITY_FIELDS = (
    "generation",
    "input",
    "formula",
    "rule_sha256",
    "asof",
    "market",
    "basis",
    "pit_status",
)
_RULE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HORIZONS = (("d2", 2), ("d5", 5))
_PERCENTILE_WINDOW = 250
_OUTCOME_STATUSES = (
    "positive",
    "negative",
    "flat",
    "not_matured",
    "missing_price",
    "nonfinite_price",
    "nonpositive_price",
    "nonfinite_return",
)


def _iso_date(value: Any, *, field: str) -> tuple[str, date]:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use canonical YYYY-MM-DD form: {value!r}")
    return value, parsed


def _sequence(value: Any, *, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    return value


def _classify_price(value: Any, *, field: str) -> tuple[str, float | None]:
    if value is None:
        return "missing_price", None
    if isinstance(value, (bool, str, bytes)):
        raise TypeError(f"{field} must be numeric or None")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field} must be numeric or None") from exc
    if not math.isfinite(numeric):
        return "nonfinite_price", None
    if numeric <= 0:
        return "nonpositive_price", None
    return "valid", numeric


def _identity_metadata(
    source_identity: Mapping[str, Any] | None,
    *,
    group_rule_sha256: str,
    asof: str,
    identity_facts: dict[str, Any],
) -> tuple[str, list[str], dict[str, Any] | None]:
    if source_identity is None:
        return "MISSING", list(_REQUIRED_IDENTITY_FIELDS), None
    if not isinstance(source_identity, Mapping):
        raise TypeError("source_identity must be a mapping or None")

    identity = copy.deepcopy(dict(source_identity))
    missing = [
        key
        for key in _REQUIRED_IDENTITY_FIELDS
        if key not in identity or identity[key] is None or identity[key] == ""
    ]

    bound_asof = identity.get("asof")
    if bound_asof not in (None, ""):
        _, parsed_bound_asof = _iso_date(bound_asof, field="source_identity.asof")
        if parsed_bound_asof.isoformat() != asof:
            raise ValueError("source identity asof conflicts with requested asof")

    bound_rule = identity.get("rule_sha256")
    if bound_rule not in (None, "") and bound_rule != group_rule_sha256:
        raise ValueError("source identity rule_sha256 conflicts with group rule_sha256")

    for key in ("market", "basis"):
        value = identity.get(key)
        if value not in (None, ""):
            if key in identity_facts and identity_facts[key] != value:
                raise ValueError(f"source identity {key} conflicts across event groups")
            identity_facts[key] = value

    return ("INCOMPLETE" if missing else "BOUND"), missing, identity


def _evaluate_event_return(
    *,
    event_date: str,
    horizon_sessions: int,
    calendar: Sequence[str],
    calendar_index: Mapping[str, int],
    asof_index: int,
    close_by_date: Mapping[str, Any],
) -> tuple[str, str, str | None, float | None]:
    event_index = calendar_index[event_date]
    target_index = event_index + horizon_sessions
    target_date = calendar[target_index] if target_index < len(calendar) else None

    if target_index > asof_index:
        return "not_matured", "TARGET_AFTER_ASOF", target_date, None

    event_status, event_close = _classify_price(
        close_by_date.get(event_date), field=f"close[{event_date}]"
    )
    if event_status != "valid":
        detail = {
            "missing_price": "MISSING_EVENT_PRICE",
            "nonfinite_price": "NONFINITE_EVENT_PRICE",
            "nonpositive_price": "NONPOSITIVE_EVENT_PRICE",
        }[event_status]
        return event_status, detail, target_date, None

    # target_index <= asof_index and asof is in the calendar, so this lookup
    # always names the exact calendar session; a missing individual bar stays
    # missing and is never replaced with a later stock bar.
    assert target_date is not None
    target_status, target_close = _classify_price(
        close_by_date.get(target_date), field=f"close[{target_date}]"
    )
    if target_status != "valid":
        detail = {
            "missing_price": (
                "MISSING_TARGET_BAR"
                if target_date not in close_by_date
                else "MISSING_TARGET_PRICE"
            ),
            "nonfinite_price": "NONFINITE_TARGET_PRICE",
            "nonpositive_price": "NONPOSITIVE_TARGET_PRICE",
        }[target_status]
        return target_status, detail, target_date, None

    assert event_close is not None and target_close is not None
    try:
        return_pct = (target_close / event_close - 1.0) * 100.0
    except OverflowError:
        return "nonfinite_return", "NONFINITE_RETURN", target_date, None
    if not math.isfinite(return_pct):
        return "nonfinite_return", "NONFINITE_RETURN", target_date, None
    if return_pct > 0:
        status = "positive"
    elif return_pct < 0:
        status = "negative"
    else:
        status = "flat"
    return status, "OK", target_date, return_pct


def _horizon_statistics(
    event_dates: Sequence[str],
    *,
    horizon_sessions: int,
    calendar: Sequence[str],
    calendar_index: Mapping[str, int],
    asof_index: int,
    close_by_date: Mapping[str, Any],
    case_limit: int,
) -> dict[str, Any]:
    counts = {status: 0 for status in _OUTCOME_STATUSES}
    valid_returns: list[float] = []
    cases: list[dict[str, Any]] = []

    # The caller passes dates in calendar order. Iterate oldest-to-newest for
    # stable accumulation, then return the most recent cases first.
    for event_date in event_dates:
        status, detail, target_date, return_pct = _evaluate_event_return(
            event_date=event_date,
            horizon_sessions=horizon_sessions,
            calendar=calendar,
            calendar_index=calendar_index,
            asof_index=asof_index,
            close_by_date=close_by_date,
        )
        counts[status] += 1
        if status in ("positive", "negative", "flat"):
            assert return_pct is not None
            valid_returns.append(return_pct)
        cases.append(
            {
                "event_date": event_date,
                "target_date": target_date,
                "status": status,
                "detail_status": detail,
                "return_pct": return_pct,
            }
        )

    valid = counts["positive"] + counts["negative"] + counts["flat"]
    total = len(event_dates)
    classified_total = sum(counts.values())
    if classified_total != total:
        raise AssertionError("event outcome counts do not reconcile")

    return {
        "horizon_trading_sessions": horizon_sessions,
        "total": total,
        "valid": valid,
        "positive": counts["positive"],
        "negative": counts["negative"],
        "flat": counts["flat"],
        "not_matured": counts["not_matured"],
        "missing_price": counts["missing_price"],
        "nonfinite_price": counts["nonfinite_price"],
        "nonpositive_price": counts["nonpositive_price"],
        "nonfinite_return": counts["nonfinite_return"],
        "mean_return_pct": mean(valid_returns) if valid_returns else None,
        "median_return_pct": median(valid_returns) if valid_returns else None,
        "positive_fraction": counts["positive"] / valid if valid else None,
        "reconciliation": {
            "classified_total": classified_total,
            "matches": classified_total == total,
        },
        "cases": list(reversed(cases[-case_limit:])) if case_limit else [],
    }


def _price_distribution(
    close_by_date: Mapping[str, Any],
    *,
    asof: str,
) -> dict[str, Any]:
    valid_closes: list[tuple[str, float]] = []
    for close_date, raw_close in close_by_date.items():
        status, value = _classify_price(raw_close, field=f"close[{close_date}]")
        if status == "valid":
            assert value is not None
            valid_closes.append((close_date, value))
    valid_closes.sort(key=lambda item: item[0])

    if asof not in close_by_date:
        current_status = "NO_CLOSE_ROWS" if not close_by_date else "MISSING_ASOF_BAR"
        current_close = None
    else:
        classified, current_value = _classify_price(
            close_by_date[asof], field=f"close[{asof}]"
        )
        current_status = {
            "valid": "VALID",
            "missing_price": "MISSING_ASOF_PRICE",
            "nonfinite_price": "NONFINITE_ASOF_CLOSE",
            "nonpositive_price": "NONPOSITIVE_ASOF_CLOSE",
        }[classified]
        current_close = current_value if classified == "valid" else None

    recent = valid_closes[-_PERCENTILE_WINDOW:]
    all_count = len(valid_closes)
    recent_count = len(recent)

    def percentile_le(rows: Sequence[tuple[str, float]]) -> float | None:
        if current_close is None or not rows:
            return None
        return sum(value <= current_close for _, value in rows) / len(rows)

    return {
        "status": current_status,
        "asof": asof,
        "current_close": current_close,
        "comparison": "count(close <= current_asof_close) / n; includes asof and equals",
        "near_250": {
            "requested_n": _PERCENTILE_WINDOW,
            "n": recent_count,
            "start_date": recent[0][0] if recent else None,
            "end_date": recent[-1][0] if recent else None,
            "insufficient": recent_count < _PERCENTILE_WINDOW,
            "percentile_le": percentile_le(recent),
        },
        "all_history": {
            "n": all_count,
            "start_date": valid_closes[0][0] if valid_closes else None,
            "end_date": valid_closes[-1][0] if valid_closes else None,
            "percentile_le": percentile_le(valid_closes),
        },
    }


def build_daily_event_statistics(
    *,
    close_rows: Sequence[Mapping[str, Any]],
    market_calendar: Sequence[str],
    asof: str,
    event_groups: Sequence[Mapping[str, Any]],
    case_limit: int = 20,
) -> dict[str, Any]:
    """Build deterministic D+2/D+5 and close-price percentile summaries.

    Inputs are treated as already approved, same-stock QFQ closes and fully
    evaluated event-group date sets. The function validates identity metadata
    without manufacturing any missing identity fields. It does not perform
    event selection, data access, or PIT certification.
    """
    asof, asof_date = _iso_date(asof, field="asof")
    calendar_values = _sequence(market_calendar, field="market_calendar")
    calendar: list[str] = []
    parsed_calendar: list[date] = []
    for index, value in enumerate(calendar_values):
        day_text, day = _iso_date(value, field=f"market_calendar[{index}]")
        calendar.append(day_text)
        parsed_calendar.append(day)
    if not calendar:
        raise ValueError("market_calendar cannot be empty")
    if len(set(calendar)) != len(calendar):
        raise ValueError("market_calendar contains duplicate sessions")
    if parsed_calendar != sorted(parsed_calendar):
        raise ValueError("market_calendar must be strictly increasing")
    if asof not in calendar:
        raise ValueError("asof must be present in market_calendar")
    asof_index = calendar.index(asof)

    if isinstance(case_limit, bool) or not isinstance(case_limit, int) or case_limit < 0:
        raise ValueError("case_limit must be a nonnegative integer")

    close_values = _sequence(close_rows, field="close_rows")
    close_by_date: dict[str, Any] = {}
    calendar_dates = set(calendar)
    for index, row in enumerate(close_values):
        if not isinstance(row, Mapping):
            raise TypeError(f"close_rows[{index}] must be a mapping")
        day_text, day = _iso_date(row.get("date"), field=f"close_rows[{index}].date")
        if day > asof_date:
            continue
        if day_text in close_by_date:
            raise ValueError(f"duplicate close row for {day_text}")
        if day_text not in calendar_dates:
            raise ValueError(f"close date {day_text} is absent from market_calendar")
        close_by_date[day_text] = row.get("close")

    groups = _sequence(event_groups, field="event_groups")
    if not groups:
        return {
            "status": "NO_EVENT_GROUPS",
            "asof": asof,
            "price_distribution": _price_distribution(close_by_date, asof=asof),
            "groups": [],
        }

    output_groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    identity_facts: dict[str, Any] = {}
    calendar_index = {day: index for index, day in enumerate(calendar)}

    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise TypeError(f"event_groups[{group_index}] must be a mapping")
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"event_groups[{group_index}].group_id is required")
        group_id = group_id.strip()
        if group_id in seen_group_ids:
            raise ValueError(f"duplicate group_id: {group_id}")
        seen_group_ids.add(group_id)

        rule_sha256 = group.get("rule_sha256")
        if not isinstance(rule_sha256, str) or not _RULE_SHA256_RE.fullmatch(rule_sha256):
            raise ValueError(f"group {group_id} requires a lowercase SHA-256 rule_sha256")

        identity_status, missing_identity_fields, source_identity = _identity_metadata(
            group.get("source_identity"),
            group_rule_sha256=rule_sha256,
            asof=asof,
            identity_facts=identity_facts,
        )

        raw_dates = _sequence(group.get("event_dates"), field=f"{group_id}.event_dates")
        parsed_events: list[tuple[str, date]] = []
        seen_dates: set[str] = set()
        for event_index, raw_date in enumerate(raw_dates):
            event_text, event_day = _iso_date(
                raw_date, field=f"{group_id}.event_dates[{event_index}]"
            )
            if event_text in seen_dates:
                raise ValueError(f"duplicate event date {event_text} in group {group_id}")
            seen_dates.add(event_text)
            parsed_events.append((event_text, event_day))

        eligible_events = [
            event_text for event_text, event_day in parsed_events
            if event_day <= asof_date
        ]
        for event_text in eligible_events:
            if event_text not in calendar_index:
                raise ValueError(
                    f"event date {event_text} in group {group_id} is absent from market_calendar"
                )
        eligible_events.sort(key=calendar_index.__getitem__)

        if not parsed_events:
            group_status = "EMPTY_EVENT_SET"
        elif not eligible_events:
            group_status = "NO_EVENTS_ASOF"
        else:
            group_status = "AVAILABLE"

        output_groups.append(
            {
                "group_id": group_id,
                "rule_sha256": rule_sha256,
                "source_identity": source_identity,
                "identity_status": identity_status,
                "identity_missing_fields": missing_identity_fields,
                "status": group_status,
                "eligible_event_count": len(eligible_events),
                "horizons": {
                    name: _horizon_statistics(
                        eligible_events,
                        horizon_sessions=horizon_sessions,
                        calendar=calendar,
                        calendar_index=calendar_index,
                        asof_index=asof_index,
                        close_by_date=close_by_date,
                        case_limit=case_limit,
                    )
                    for name, horizon_sessions in _HORIZONS
                },
            }
        )

    return {
        "status": "DESCRIPTIVE_STATS_COMPUTED",
        "asof": asof,
        "price_distribution": _price_distribution(close_by_date, asof=asof),
        "groups": output_groups,
    }


__all__ = ["build_daily_event_statistics"]
