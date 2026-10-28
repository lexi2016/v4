"""domains.hk_prefix_research: control_checks (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __terminal_contract_gate_body(_v4_scope, /, pair_rows):
    """Evaluate the frozen terminal endpoint coverage gate without tuning."""

    total = _v4_global(_v4_scope, 'len')(pair_rows)
    complete = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'bool')(row.get("complete_terminal_pair")) for row in pair_rows)
    by_type: dict[str, dict[str, int]] = {}
    for row in pair_rows:
        event_type = _v4_global(_v4_scope, 'str')(row.get("event_type") or "UNKNOWN")
        bucket = by_type.setdefault(event_type, {"complete": 0, "total": 0})
        bucket["total"] += 1
        bucket["complete"] += _v4_global(_v4_scope, 'bool')(row.get("complete_terminal_pair"))
    status = "PASS" if complete >= _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS') else "NOT_SUPPORTED"
    return {
        "metric_contract_version": _v4_global(_v4_scope, 'METRIC_CONTRACT_VERSION'),
        "status": status,
        "complete_terminal_pairs": complete,
        "total_pairs": total,
        "required_complete_pairs": _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS'),
        "coverage": f"{complete}/{total}",
        "by_event_type": by_type,
        "indeterminate_pair_count": total - complete,
        "reason": (
            "terminal endpoint coverage meets the frozen minimum"
            if status == "PASS"
            else f"terminal endpoint coverage {complete}/{total} is below required {_v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS')}/{total}"
        ),
    }


def __future_isolation_check_body(_v4_scope, /, artifacts, *, scan):
    """Append a changed future row and prove every prior result is unchanged."""

    checked = 0
    for artifact in artifacts:
        baseline, _ = _v4_global(_v4_scope, '_scan_artifact')(artifact.rows, scan=scan)
        last = _v4_global(_v4_scope, 'dict')(artifact.rows[-1])
        last_date = _v4_global(_v4_scope, 'datetime').fromisoformat(_v4_global(_v4_scope, 'str')(last["close_at"]))
        future_at = (last_date + _v4_global(_v4_scope, 'timedelta')(days=1)).isoformat()
        future = _v4_global(_v4_scope, 'dict')(last)
        future.update(
            {
                "session_index": _v4_global(_v4_scope, 'int')(last["session_index"]) + 1,
                "close_at": future_at,
                "available_at": future_at,
                "open": 9999.0,
                "high": 10000.0,
                "low": 9998.0,
                "close": 9999.5,
                "volume": 999999.0,
            }
        )
        changed, _ = _v4_global(_v4_scope, '_scan_artifact')(
            _v4_global(_v4_scope, 'tuple')([*artifact.rows, future]),
            scan=scan,
            expected_rows=_v4_global(_v4_scope, 'len')(artifact.rows),
            asof=_v4_global(_v4_scope, 'str')(artifact.rows[-1]["close_at"]),
        )
        if baseline != changed:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"future suffix changed prefix result: {artifact.series_id}")
        checked += 1
    return {
        "status": "PASS",
        "checked_series": checked,
        "future_rows_consumed": 0,
        "future_numeric_mutation_changed_past": False,
        "policy": "FILTER_AFTER_ASOF_BEFORE_PRICE_VOLUME_USE",
    }


def __positive_control_check_body(_v4_scope, /, scan):
    """Use a fixed pre-2026 synthetic path as a past-positive machine control."""

    origin = _v4_global(_v4_scope, 'datetime')(2020, 1, 1, 16, tzinfo=_v4_global(_v4_scope, 'timezone')(_v4_global(_v4_scope, 'timedelta')(hours=8)))
    rows: list[dict[str, Any]] = []
    for index in _v4_global(_v4_scope, 'range')(30):
        timestamp = (origin + _v4_global(_v4_scope, 'timedelta')(days=index)).isoformat()
        rows.append(
            {
                "series_id": "SYNTHETIC_PAST_POSITIVE",
                "session_index": index,
                "close_at": timestamp,
                "available_at": timestamp,
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "volume": 100.0,
                "price_basis": "SYNTHETIC_STABLE",
                "quality": "OK",
            }
        )
    rows[22].update({"low": 9.4, "close": 9.6, "volume": 160.0})
    rows[23].update({"open": 9.7, "high": 10.5, "low": 9.6, "close": 10.3, "volume": 140.0})
    rows[24].update({"open": 10.25, "high": 10.4, "low": 10.1, "close": 10.35, "volume": 60.0})
    for index in _v4_global(_v4_scope, 'range')(25, 30):
        rows[index].update({"open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 110.0})
    result, metrics = _v4_global(_v4_scope, '_scan_artifact')(_v4_global(_v4_scope, 'tuple')(rows[:25]), scan=scan)
    expected = "RETEST_HELD_PROVISIONAL"
    if metrics["terminal_state"] != expected:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("past-positive machine control did not reach expected state")
    return {
        "status": "PASS",
        "fixture": "SYNTHETIC_PAST_POSITIVE",
        "asof": rows[24]["close_at"],
        "rows": _v4_global(_v4_scope, 'len')(result),
        "expected_terminal_state": expected,
        "observed_terminal_state": metrics["terminal_state"],
        "fit_calls": 0,
    }


def __field_check_body(_v4_scope, /, artifacts):
    for artifact in artifacts:
        if _v4_global(_v4_scope, 'len')(artifact.rows) != _v4_global(_v4_scope, 'PREFIX_LENGTH'):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"prefix row count mismatch: {artifact.series_id}")
        for row in artifact.rows:
            if _v4_global(_v4_scope, 'set')(row) != _v4_global(_v4_scope, '_PREFIX_FIELD_SET') or _v4_global(_v4_scope, 'set')(row).intersection(_v4_global(_v4_scope, '_FORBIDDEN_PREFIX_FIELDS')):
                raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"prefix schema/identity leak: {artifact.series_id}")
            if _v4_global(_v4_scope, 'int')(row["session_index"]) < 0:
                raise _v4_global(_v4_scope, 'HKPrefixResearchError')("negative market session index")
            if _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'str')(row["close_at"])[0:4]) > _v4_global(_v4_scope, 'MAX_YEAR'):
                raise _v4_global(_v4_scope, 'HKPrefixResearchError')("2026 row entered historical prefix")
    return {
        "status": "PASS",
        "checked_series": _v4_global(_v4_scope, 'len')(artifacts),
        "checked_rows": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(item.rows) for item in artifacts),
        "prefix_fields": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'PREFIX_FIELDS')),
        "forbidden_fields_rejected": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, '_FORBIDDEN_PREFIX_FIELDS')),
    }
