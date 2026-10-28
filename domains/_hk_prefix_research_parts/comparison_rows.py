"""domains.hk_prefix_research: comparison_rows (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __identity_rows_body(_v4_scope, /, artifacts):
    return [
        {
            "series_id": item.series_id,
            "pair_group_id": item.pair_group_id,
            "group_index": item.group_index,
            "role": item.role,
            "code": item.code,
            "event_date": item.event_date,
            "event_type": item.event_type,
            "row_count": item.row_count,
            "source_observed_rows": item.source_observed_rows,
            "source_missing_rows": item.source_missing_rows,
            "terminal_state": item.terminal_state,
            "unknown_count": item.unknown_count,
            "indeterminate_count": item.indeterminate_count,
            "known_count": item.known_count,
            "qualifying_count": item.qualifying_count,
            "terminal_unknown": item.terminal_unknown,
            "terminal_determinable": item.terminal_determinable,
            "terminal_lower": item.terminal_lower,
            "terminal_upper": item.terminal_upper,
            "terminal_indeterminate_reason": item.terminal_indeterminate_reason,
            "terminal_qualifies": item.terminal_qualifies,
            "occupancy_lower_rate": item.occupancy_lower_rate,
            "occupancy_upper_rate": item.occupancy_upper_rate,
            "unknown_reason_counts": _v4_global(_v4_scope, 'json').dumps(item.unknown_reason_counts, ensure_ascii=False, sort_keys=True),
            "input_sha256": item.input_sha256,
            "prefix_content_sha256": item.prefix_content_sha256,
            "comparison_status": "TERMINAL_BINARY_DESCRIPTIVE_UNREGISTERED_CONTROL_THRESHOLD",
        }
        for item in artifacts
    ]


def __pair_rows_body(_v4_scope, /, artifacts, groups):
    by_group: dict[str, dict[str, PrefixArtifact]] = {}
    for artifact in artifacts:
        by_group.setdefault(artifact.pair_group_id, {})[artifact.role] = artifact
    output: list[dict[str, Any]] = []
    for group in groups:
        members = by_group.get(group.pair_group_id)
        if not members or _v4_global(_v4_scope, 'set')(members) != {"EVENT", "CONTROL_1", "CONTROL_2", "CONTROL_3"}:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("full frozen group does not have four derived series")
        event = members["EVENT"]
        controls = [members[f"CONTROL_{index}"] for index in _v4_global(_v4_scope, 'range')(1, 4)]
        control_terminal_lower = _v4_global(_v4_scope, 'sum')(item.terminal_lower for item in controls) / 3
        control_terminal_upper = _v4_global(_v4_scope, 'sum')(item.terminal_upper for item in controls) / 3
        control_terminal_qualifies = _v4_global(_v4_scope, 'sum')(item.terminal_qualifies for item in controls)
        control_terminal_unknown = _v4_global(_v4_scope, 'sum')(item.terminal_unknown for item in controls)
        control_terminal_indeterminate = _v4_global(_v4_scope, 'sum')(
            not item.terminal_determinable for item in controls
        )
        complete = _v4_global(_v4_scope, 'bool')(
            event.terminal_determinable
            and _v4_global(_v4_scope, 'all')(item.terminal_determinable for item in controls)
        )
        incomplete_roles = []
        if not event.terminal_determinable:
            incomplete_roles.append("EVENT")
        incomplete_roles.extend(
            item.role for item in controls if not item.terminal_determinable
        )
        terminal_delta = (
            event.terminal_lower - control_terminal_lower if complete else None
        )
        terminal_delta_lower = event.terminal_lower - control_terminal_upper
        terminal_delta_upper = event.terminal_upper - control_terminal_lower
        if terminal_delta_lower > terminal_delta_upper + 1e-12:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("terminal delta bounds are inverted")
        output.append(
            {
                "pair_group_id": group.pair_group_id,
                "event_date": group.event_date,
                "event_type": group.event_type,
                "event_series_id": event.series_id,
                "control_series_ids": ",".join(item.series_id for item in controls),
                "event_terminal_state": event.terminal_state,
                "event_terminal_qualifies": event.terminal_qualifies,
                "event_terminal_unknown": event.terminal_unknown,
                "event_terminal_determinable": event.terminal_determinable,
                "event_terminal_lower": event.terminal_lower,
                "event_terminal_upper": event.terminal_upper,
                "event_terminal_indeterminate_reason": event.terminal_indeterminate_reason,
                "control_terminal_qualifying_count": control_terminal_qualifies,
                "control_terminal_unknown_count": control_terminal_unknown,
                "control_terminal_indeterminate_count": control_terminal_indeterminate,
                "control_terminal_determinable": _v4_global(_v4_scope, 'all')(item.terminal_determinable for item in controls),
                "control_terminal_lower_mean": control_terminal_lower,
                "control_terminal_upper_mean": control_terminal_upper,
                "complete_terminal_pair": complete,
                "incomplete_endpoint_roles": ",".join(incomplete_roles),
                "terminal_case_indicator": event.terminal_lower if complete else None,
                "terminal_control_indicator_mean": control_terminal_lower if complete else None,
                "terminal_delta": terminal_delta,
                "terminal_delta_lower": terminal_delta_lower,
                "terminal_delta_upper": terminal_delta_upper,
                "occupancy_case_lower_rate": event.occupancy_lower_rate,
                "occupancy_control_lower_rate_mean": _v4_global(_v4_scope, 'sum')(item.occupancy_lower_rate for item in controls) / 3,
                "occupancy_pair_lower_delta": event.occupancy_lower_rate - _v4_global(_v4_scope, 'sum')(item.occupancy_lower_rate for item in controls) / 3,
                "occupancy_case_upper_rate": event.occupancy_upper_rate,
                "occupancy_control_upper_rate_mean": _v4_global(_v4_scope, 'sum')(item.occupancy_upper_rate for item in controls) / 3,
                "occupancy_pair_upper_delta": event.occupancy_upper_rate - _v4_global(_v4_scope, 'sum')(item.occupancy_upper_rate for item in controls) / 3,
                "comparison_status": "TERMINAL_BINARY_DESCRIPTIVE_UNREGISTERED_CONTROL_THRESHOLD",
                "post_outcome_used": False,
            }
        )
    return output


def __summary_rows_body(_v4_scope, /, pair_rows):
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for row in pair_rows:
        by_type.setdefault(_v4_global(_v4_scope, 'str')(row["event_type"]), []).append(row)
    output: list[dict[str, Any]] = []
    for event_type in ("new_event", "continuation_event"):
        rows = by_type.get(event_type, [])
        complete_rows = [row for row in rows if _v4_global(_v4_scope, 'bool')(row.get("complete_terminal_pair"))]
        mean_delta = (
            _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'float')(row["terminal_delta"]) for row in complete_rows) / _v4_global(_v4_scope, 'len')(complete_rows)
            if complete_rows else None
        )
        mean_lower = (
            _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'float')(row["terminal_delta_lower"]) for row in rows) / _v4_global(_v4_scope, 'len')(rows)
            if rows else None
        )
        mean_upper = (
            _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'float')(row["terminal_delta_upper"]) for row in rows) / _v4_global(_v4_scope, 'len')(rows)
            if rows else None
        )
        coverage = f"{_v4_global(_v4_scope, 'len')(complete_rows)}/{_v4_global(_v4_scope, 'len')(rows)}"
        output.append(
            {
                "event_type": event_type,
                "group_count": _v4_global(_v4_scope, 'len')(rows),
                "complete_terminal_pair_count": _v4_global(_v4_scope, 'len')(complete_rows),
                "required_complete_pairs": _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS'),
                "terminal_coverage": coverage,
                "terminal_delta_mean": mean_delta,
                "terminal_delta_lower_mean": mean_lower,
                "terminal_delta_upper_mean": mean_upper,
                "coverage_status": "PASS" if _v4_global(_v4_scope, 'len')(complete_rows) >= _v4_global(_v4_scope, 'MIN_COMPLETE_TERMINAL_PAIRS') else "NOT_SUPPORTED",
                "comparison_status": "NOT_SUPPORTED_TERMINAL_COVERAGE",
                "unknown_policy": "PRESERVE_UNKNOWN_AND_REPORT_BOUNDS",
            }
        )
    return output


def __unknown_rows_body(_v4_scope, /, artifacts):
    return [
        {
            "series_id": item.series_id,
            "unknown_count": item.unknown_count,
            "indeterminate_count": item.indeterminate_count,
            "known_count": item.known_count,
            "terminal_unknown": item.terminal_unknown,
            "terminal_determinable": item.terminal_determinable,
            "terminal_lower": item.terminal_lower,
            "terminal_upper": item.terminal_upper,
            "terminal_indeterminate_reason": item.terminal_indeterminate_reason,
            "occupancy_lower_rate": item.occupancy_lower_rate,
            "occupancy_upper_rate": item.occupancy_upper_rate,
            "unknown_reasons": _v4_global(_v4_scope, 'json').dumps(item.unknown_reason_counts, ensure_ascii=False, sort_keys=True),
        }
        for item in artifacts
    ]
