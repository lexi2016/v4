"""domains.hk_prefix_research: io_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __terminal_endpoint_metrics_body(_v4_scope, /, states):
    """Return the terminal indicator and its uncertainty interval.

    The terminal state is the only primary endpoint.  A qualifying state is
    one, a non-qualifying known state is zero, and UNKNOWN/WARMUP are
    indeterminate endpoints with the conservative [0, 1] interval.  Path
    occupancy is calculated separately by ``_scan_artifact`` and must never
    stand in for this endpoint.
    """

    if not states:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reference extractor emitted no states")
    terminal = _v4_global(_v4_scope, 'str')(states[-1] or "")
    if terminal not in _v4_global(_v4_scope, '_KNOWN_STATES') and terminal != "UNKNOWN":
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"reference extractor emitted unknown state: {terminal}")
    if terminal in _v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES'):
        return {
            "terminal_unknown": terminal == "UNKNOWN",
            "terminal_determinable": False,
            "terminal_lower": 0.0,
            "terminal_upper": 1.0,
            "terminal_qualifies": False,
            "terminal_indeterminate_reason": f"{terminal}_ENDPOINT_INDETERMINATE",
        }
    indicator = _v4_global(_v4_scope, 'float')(terminal in _v4_global(_v4_scope, '_QUALIFYING_STATES'))
    return {
        "terminal_unknown": False,
        "terminal_determinable": True,
        "terminal_lower": indicator,
        "terminal_upper": indicator,
        "terminal_qualifies": _v4_global(_v4_scope, 'bool')(indicator),
        "terminal_indeterminate_reason": "",
    }


def __safe_json_body(_v4_scope, /, value):
    """Convert pandas/numpy scalars and nonfinite values for receipts."""

    if value is None or _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bool'), _v4_global(_v4_scope, 'int'))):
        return value
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'float')):
        return value if _v4_global(_v4_scope, 'math').isfinite(value) else None
    if _v4_global(_v4_scope, 'hasattr')(value, "item"):
        return _v4_global(_v4_scope, '_safe_json')(value.item())
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        return {_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, '_safe_json')(item) for key, item in value.items()}
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'), _v4_global(_v4_scope, 'set'), _v4_global(_v4_scope, 'frozenset'))):
        return [_v4_global(_v4_scope, '_safe_json')(item) for item in value]
    return _v4_global(_v4_scope, 'str')(value)


def __iso_date_body(_v4_scope, /, value, *, field):
    text = _v4_global(_v4_scope, 'str')(value or "").strip()
    try:
        if _v4_global(_v4_scope, 'len')(text) == 10:
            parsed = _v4_global(_v4_scope, 'datetime').strptime(text, "%Y-%m-%d")
        elif _v4_global(_v4_scope, 'len')(text) == 8:
            parsed = _v4_global(_v4_scope, 'datetime').strptime(text, "%Y%m%d")
        else:
            raise _v4_global(_v4_scope, 'ValueError')
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"{field} must be YYYY-MM-DD or YYYYMMDD") from error
    return parsed.strftime("%Y-%m-%d")


def __assert_safe_flags_body(_v4_scope, /, value, *, label):
    if (
        value.get("RESEARCH_ONLY") is not True
        and value.get("research_only") is not True
    ):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"unsafe {label} safety flags")
    if (
        value.get("production_allowed") is not False
        or value.get("buy_gate_updated") is not False
        or value.get("orders_sent") is not False
    ):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"unsafe {label} safety flags")


def __csv_number_body(_v4_scope, /, value):
    if value is None or (_v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'float')) and not _v4_global(_v4_scope, 'math').isfinite(value)):
        return ""
    try:
        numeric = _v4_global(_v4_scope, 'float')(value)
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')):
        return ""
    if not _v4_global(_v4_scope, 'math').isfinite(numeric):
        return ""
    # repr(float) is deterministic and preserves the source float32 value
    # after the owner reader has converted it to a Python scalar.
    return _v4_global(_v4_scope, 'repr')(numeric)


def __write_csv_new_body(_v4_scope, /, path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", newline="", encoding="utf-8") as handle:
            writer = _v4_global(_v4_scope, 'csv').DictWriter(handle, fieldnames=_v4_global(_v4_scope, 'list')(fields), extrasaction="raise", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: _v4_global(_v4_scope, '_csv_number')(row.get(field)) if field in {"open", "high", "low", "close", "volume"} else row.get(field, "") for field in fields})
    except _v4_global(_v4_scope, 'FileExistsError') as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"refuse to overwrite existing evidence: {path}") from error
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')(f"cannot write CSV evidence: {path}") from error
    return {"path": _v4_global(_v4_scope, 'str')(path), "bytes": path.stat().st_size, "sha256": _v4_global(_v4_scope, 'sha256_file')(path)}


def __anonymous_index_body(_v4_scope, /, artifacts, prefix_dir):
    return [
        {
            "series_id": item.series_id,
            # Keep the review index portable when the evidence directory is
            # copied to Drive or unpacked by another Chat session.
            "prefix_file": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')("derived_windows") / f"{item.series_id}.csv"),
            "row_count": item.row_count,
            "input_sha256": item.input_sha256,
            "prefix_content_sha256": item.prefix_content_sha256,
            "review_status": "NOT_REVIEWED",
        }
        for item in artifacts
    ]


def __write_artifact_set_body(_v4_scope, /, root, artifacts, *, groups, write_identity):
    prefix_dir = root / "derived_windows"
    for artifact in artifacts:
        _v4_global(_v4_scope, '_write_prefix_csv')(prefix_dir / f"{artifact.series_id}.csv", artifact)
    anonymous = _v4_global(_v4_scope, '_anonymous_index')(artifacts, prefix_dir)
    _v4_global(_v4_scope, '_write_csv_new')(root / "anonymous_prefix_index.csv", _v4_global(_v4_scope, 'tuple')(anonymous[0]) if anonymous else ("series_id",), anonymous)
    result_rows = []
    for artifact in artifacts:
        result_rows.append(
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
        )
    if write_identity:
        identity_dir = root / "identity"
        _v4_global(_v4_scope, '_write_json_new')(identity_dir / "results_summary.json", result_rows)
        pairs = _v4_global(_v4_scope, '_pair_rows')(artifacts, groups)
        summary = _v4_global(_v4_scope, '_summary_rows')(pairs)
        contract_gate = _v4_global(_v4_scope, '_terminal_contract_gate')(pairs)
        _v4_global(_v4_scope, '_write_csv_new')(identity_dir / "results_mapping.csv", _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, '_identity_rows')(artifacts)[0]) if artifacts else ("series_id",), _v4_global(_v4_scope, '_identity_rows')(artifacts))
        _v4_global(_v4_scope, '_write_csv_new')(root / "pair_metrics.csv", _v4_global(_v4_scope, 'tuple')(pairs[0]) if pairs else ("pair_group_id",), pairs)
        _v4_global(_v4_scope, '_write_csv_new')(root / "summary_by_event_type.csv", _v4_global(_v4_scope, 'tuple')(summary[0]), summary)
        _v4_global(_v4_scope, '_write_csv_new')(root / "unknown_bounds.csv", _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, '_unknown_rows')(artifacts)[0]) if artifacts else ("series_id",), _v4_global(_v4_scope, '_unknown_rows')(artifacts))
        return {"anonymous": anonymous, "pairs": pairs, "summary": summary, "contract_gate": contract_gate}
    return {"anonymous": anonymous}
