"""domains.hk_prefix_research: artifact_build (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __artifact_digest_body(_v4_scope, /, artifacts):
    records = [
        {
            "series_id": item.series_id,
            "input_sha256": item.input_sha256,
            "prefix_content_sha256": item.prefix_content_sha256,
            "terminal_state": item.terminal_state,
            "row_count": item.row_count,
        }
        for item in artifacts
    ]
    return _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(records))


def __make_artifact_body(_v4_scope, /, source_frame, calendar, *, group_index, group, role, code, series_id, scan):
    rows, observed, missing = _v4_global(_v4_scope, 'build_prefix_rows')(
        source_frame,
        calendar,
        code=code,
        event_date=group.event_date,
        series_id=series_id,
    )
    scan_rows, metrics = _v4_global(_v4_scope, '_scan_artifact')(rows, scan=scan)
    input_sha = _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(rows))
    prefix_sha = _v4_global(_v4_scope, 'str')(scan_rows[-1].get("prefix_content_sha256") or "")
    if not _v4_global(_v4_scope, '_is_sha256')(prefix_sha):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reference extractor did not emit a prefix content hash")
    return _v4_global(_v4_scope, 'PrefixArtifact')(
        series_id=series_id,
        group_index=group_index,
        pair_group_id=group.pair_group_id,
        role=role,
        code=_v4_global(_v4_scope, '_normalize_code')(code),
        event_date=group.event_date,
        event_type=group.event_type,
        rows=rows,
        scan_rows=scan_rows,
        input_sha256=input_sha,
        prefix_content_sha256=prefix_sha,
        terminal_state=metrics["terminal_state"],
        row_count=_v4_global(_v4_scope, 'len')(rows),
        unknown_count=metrics["unknown_count"],
        indeterminate_count=metrics["indeterminate_count"],
        known_count=metrics["known_count"],
        qualifying_count=metrics["qualifying_count"],
        terminal_unknown=metrics["terminal_unknown"],
        terminal_determinable=metrics["terminal_determinable"],
        terminal_lower=metrics["terminal_lower"],
        terminal_upper=metrics["terminal_upper"],
        terminal_indeterminate_reason=metrics["terminal_indeterminate_reason"],
        terminal_qualifies=metrics["terminal_qualifies"],
        occupancy_lower_rate=metrics["occupancy_lower_rate"],
        occupancy_upper_rate=metrics["occupancy_upper_rate"],
        unknown_reason_counts=metrics["unknown_reason_counts"],
        source_observed_rows=observed,
        source_missing_rows=missing,
    )


def __group_artifacts_body(_v4_scope, /, source_frame, calendar, groups, *, scan, group_limit):
    selected = _v4_global(_v4_scope, 'list')(groups if group_limit is None else groups[:group_limit])
    artifacts: list[PrefixArtifact] = []
    series_number = 1
    for group_index, group in _v4_global(_v4_scope, 'enumerate')(selected):
        codes = [("EVENT", group.case_code)] + [
            (f"CONTROL_{index}", code)
            for index, code in _v4_global(_v4_scope, 'enumerate')(group.controls, start=1)
        ]
        for role, code in codes:
            series_id = f"SERIES_{series_number:03d}"
            artifacts.append(
                _v4_global(_v4_scope, '_make_artifact')(
                    source_frame,
                    calendar,
                    group_index=group_index,
                    group=group,
                    role=role,
                    code=code,
                    series_id=series_id,
                    scan=scan,
                )
            )
            series_number += 1
    return artifacts
