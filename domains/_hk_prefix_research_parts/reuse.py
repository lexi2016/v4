"""domains.hk_prefix_research: reuse (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __read_reused_prefix_csv_body(_v4_scope, /, path, *, series_id):
    """Read one already materialized prefix without touching the raw parquet."""

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(handle))
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"cannot read reused prefix window: {path}") from error
    if _v4_global(_v4_scope, 'len')(rows) != _v4_global(_v4_scope, 'PREFIX_LENGTH') or (rows and _v4_global(_v4_scope, 'set')(rows[0]) != _v4_global(_v4_scope, '_PREFIX_FIELD_SET')):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix window schema or row count mismatch")
    converted: list[dict[str, Any]] = []
    for raw in rows:
        if _v4_global(_v4_scope, 'set')(raw) != _v4_global(_v4_scope, '_PREFIX_FIELD_SET'):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix window schema mismatch")
        if _v4_global(_v4_scope, 'str')(raw.get("series_id") or "") != series_id:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix window series identity mismatch")
        item: dict[str, Any] = _v4_global(_v4_scope, 'dict')(raw)
        try:
            item["session_index"] = _v4_global(_v4_scope, 'int')(raw["session_index"])
            for field in ("open", "high", "low", "close"):
                item[field] = None if raw[field] == "" else _v4_global(_v4_scope, 'float')(raw[field])
            # The frozen source schema declares ``trade`` as an integer
            # volume column; preserve that type when the CSV serializer
            # emitted the integral value with a trailing .0.
            if raw["volume"] == "":
                item["volume"] = None
            elif _v4_global(_v4_scope, 'str')(raw["volume"]).endswith(".0"):
                item["volume"] = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'float')(raw["volume"]))
            else:
                item["volume"] = _v4_global(_v4_scope, 'float')(raw["volume"])
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix window numeric field is invalid") from error
        converted.append(item)
    return _v4_global(_v4_scope, 'tuple')(converted)


def __reused_artifacts_body(_v4_scope, /, source_root, index_rows, mapping_rows, groups, *, extractor_path):
    """Reconstruct corrected metrics from the frozen 96 CSVs only.

    The old raw parquet is intentionally not opened in this path. Re-running
    the accepted zero-fit scanner on each already frozen window recovers the
    full state sequence needed to distinguish UNKNOWN/WARMUP endpoints while
    retaining the original window bytes for export.
    """

    scan = _v4_global(_v4_scope, '_load_scan_function')(extractor_path)
    index_by_series = {_v4_global(_v4_scope, 'str')(row.get("series_id") or ""): row for row in index_rows}
    mapping_by_series = {_v4_global(_v4_scope, 'str')(row.get("series_id") or ""): row for row in mapping_rows}
    group_by_id = {group.pair_group_id: group for group in groups}
    expected_series = {f"SERIES_{index:03d}" for index in _v4_global(_v4_scope, 'range')(1, 97)}
    if _v4_global(_v4_scope, 'set')(index_by_series) != expected_series or _v4_global(_v4_scope, 'set')(mapping_by_series) != expected_series:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused frozen CSV identity set is not exactly 96 series")
    artifacts: list[PrefixArtifact] = []
    for series_id in _v4_global(_v4_scope, 'sorted')(expected_series, key=lambda value: _v4_global(_v4_scope, 'int')(value.split("_")[-1])):
        index = index_by_series[series_id]
        mapping = mapping_by_series[series_id]
        relative = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(index.get("prefix_file") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix file path is unsafe")
        window_path = (source_root / relative).resolve(strict=False)
        source_resolved = source_root.resolve(strict=False)
        try:
            window_path.relative_to(source_resolved)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix file escapes source root") from error
        rows = _v4_global(_v4_scope, '_read_reused_prefix_csv')(window_path, series_id=series_id)
        input_sha = _v4_global(_v4_scope, 'str')(index.get("input_sha256") or "")
        prefix_sha = _v4_global(_v4_scope, 'str')(index.get("prefix_content_sha256") or "")
        if not _v4_global(_v4_scope, '_is_sha256')(input_sha) or not _v4_global(_v4_scope, '_is_sha256')(prefix_sha):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused prefix index digest is invalid")
        if _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(rows)) != input_sha:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reused prefix input digest mismatch: {series_id}")
        scan_rows, metrics = _v4_global(_v4_scope, '_scan_artifact')(rows, scan=scan)
        if _v4_global(_v4_scope, 'str')(scan_rows[-1].get("prefix_content_sha256") or "") != prefix_sha:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reused prefix content digest mismatch: {series_id}")
        pair_group_id = _v4_global(_v4_scope, 'str')(mapping.get("pair_group_id") or "")
        group = group_by_id.get(pair_group_id)
        if group is None:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reused identity row references an unknown frozen group")
        role = _v4_global(_v4_scope, 'str')(mapping.get("role") or "")
        code = _v4_global(_v4_scope, '_normalize_code')(mapping.get("code"))
        expected_code = ""
        if role == "EVENT":
            expected_code = group.case_code
        elif role.startswith("CONTROL_") and role[-1].isdigit():
            expected_code = group.controls[_v4_global(_v4_scope, 'int')(role[-1]) - 1]
        if not code or code != expected_code:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reused identity code mismatch: {series_id}")
        if _v4_global(_v4_scope, 'str')(mapping.get("event_date") or "") != group.event_date or _v4_global(_v4_scope, 'str')(mapping.get("event_type") or "") != group.event_type:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reused identity event mismatch: {series_id}")
        observed = _v4_global(_v4_scope, 'sum')(row["quality"] != "MISSING_SOURCE_ROW" for row in rows)
        missing = _v4_global(_v4_scope, 'len')(rows) - observed
        if _v4_global(_v4_scope, 'int')(mapping.get("source_observed_rows") or -1) != observed or _v4_global(_v4_scope, 'int')(mapping.get("source_missing_rows") or -1) != missing:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reused source quality counts mismatch: {series_id}")
        artifacts.append(
            _v4_global(_v4_scope, 'PrefixArtifact')(
                series_id=series_id,
                group_index=_v4_global(_v4_scope, 'int')(mapping.get("group_index") or 0),
                pair_group_id=pair_group_id,
                role=role,
                code=code,
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
        )
    return artifacts


def __write_reused_result_body(_v4_scope, /, root, artifacts, *, groups):
    """Write corrected identity/metric ledgers for copied anonymous windows."""

    identity_dir = root / "identity"
    result_rows = [
        {
            "series_id": artifact.series_id,
            "terminal_state": artifact.terminal_state,
            "unknown_count": artifact.unknown_count,
            "indeterminate_count": artifact.indeterminate_count,
            "known_count": artifact.known_count,
            "qualifying_count": artifact.qualifying_count,
            "terminal_unknown": artifact.terminal_unknown,
            "terminal_determinable": artifact.terminal_determinable,
            "terminal_lower": artifact.terminal_lower,
            "terminal_upper": artifact.terminal_upper,
            "terminal_indeterminate_reason": artifact.terminal_indeterminate_reason,
            "terminal_qualifies": artifact.terminal_qualifies,
            "occupancy_lower_rate": artifact.occupancy_lower_rate,
            "occupancy_upper_rate": artifact.occupancy_upper_rate,
            "prefix_content_sha256": artifact.prefix_content_sha256,
        }
        for artifact in artifacts
    ]
    _v4_global(_v4_scope, '_write_json_new')(identity_dir / "results_summary.json", result_rows)
    identity = _v4_global(_v4_scope, '_identity_rows')(artifacts)
    _v4_global(_v4_scope, '_write_csv_new')(identity_dir / "results_mapping.csv", _v4_global(_v4_scope, 'tuple')(identity[0]), identity)
    pairs = _v4_global(_v4_scope, '_pair_rows')(artifacts, groups)
    summary = _v4_global(_v4_scope, '_summary_rows')(pairs)
    contract_gate = _v4_global(_v4_scope, '_terminal_contract_gate')(pairs)
    _v4_global(_v4_scope, '_write_csv_new')(root / "pair_metrics.csv", _v4_global(_v4_scope, 'tuple')(pairs[0]), pairs)
    _v4_global(_v4_scope, '_write_csv_new')(root / "summary_by_event_type.csv", _v4_global(_v4_scope, 'tuple')(summary[0]), summary)
    unknown = _v4_global(_v4_scope, '_unknown_rows')(artifacts)
    _v4_global(_v4_scope, '_write_csv_new')(root / "unknown_bounds.csv", _v4_global(_v4_scope, 'tuple')(unknown[0]), unknown)
    return {"result_rows": result_rows, "pairs": pairs, "summary": summary, "contract_gate": contract_gate}
