"""domains.hk_prefix_research: frozen_binding (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _load_frozen_group_binding_body(_v4_scope, /, binding_path, *, matched_verdict_path):
    """Read and verify the exact 24-group/72-control binding without sampling."""

    path = _v4_global(_v4_scope, 'Path')(binding_path)
    binding = _v4_global(_v4_scope, '_read_json')(path)
    if binding.get("groups") != 24 or binding.get("controls") != 72:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding group/control counts mismatch")
    if binding.get("resampled") is not False:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding must declare resampled=false")
    declared_source = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(binding.get("source_csv") or ""))
    matched_path = _v4_global(_v4_scope, 'Path')(matched_verdict_path) if matched_verdict_path is not None else declared_source
    if not matched_path.is_file():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict source CSV is missing")
    declared_sha = _v4_global(_v4_scope, 'str')(binding.get("source_sha256") or "").lower()
    matched_sha = _v4_global(_v4_scope, 'sha256_file')(matched_path)
    if not _v4_global(_v4_scope, '_is_sha256')(declared_sha) or matched_sha != declared_sha:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict source checksum mismatch")
    rows = _v4_global(_v4_scope, '_read_csv')(matched_path)
    by_group: dict[str, dict[str, str]] = {}
    for row in rows:
        group_id = _v4_global(_v4_scope, 'str')(row.get("pair_group_id") or "")
        if not group_id or group_id in by_group:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict pair_group_id is missing or duplicated")
        by_group[group_id] = row

    groups: list[FrozenPrefixGroup] = []
    seen_group_ids: set[str] = _v4_global(_v4_scope, 'set')()
    seen_series_keys: set[tuple[str, str]] = _v4_global(_v4_scope, 'set')()
    raw_groups = binding.get("groups_binding")
    if not _v4_global(_v4_scope, 'isinstance')(raw_groups, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(raw_groups) != 24:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding groups_binding must contain 24 rows")
    for raw in raw_groups:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_REQUIRED_GROUP_FIELDS').issubset(raw):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding group fields are incomplete")
        pair_group_id = _v4_global(_v4_scope, 'str')(raw["pair_group_id"])
        if pair_group_id in seen_group_ids:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("duplicate frozen pair_group_id")
        seen_group_ids.add(pair_group_id)
        event_date = _v4_global(_v4_scope, '_iso_date')(raw["event_date"], field="event_date")
        if _v4_global(_v4_scope, 'int')(event_date[:4]) > _v4_global(_v4_scope, 'MAX_YEAR'):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("2026 or later event entered historical prefix binding")
        event_type = _v4_global(_v4_scope, 'str')(raw["event_type"] or "").strip()
        if event_type not in {"new_event", "continuation_event"}:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("unknown frozen event_type")
        case_code = _v4_global(_v4_scope, '_normalize_code')(raw["case_code"])
        controls = raw["controls"]
        if not _v4_global(_v4_scope, 'isinstance')(controls, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(controls) != 3:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("each frozen group must retain exactly three controls")
        normalized_controls = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, '_normalize_code')(item) for item in controls)
        if not case_code or _v4_global(_v4_scope, 'any')(not item for item in normalized_controls):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding contains an invalid HK code")
        if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(normalized_controls)) != _v4_global(_v4_scope, 'len')(normalized_controls):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("duplicate controls within frozen group")
        if not pair_group_id.startswith("PAIR_"):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen pair_group_id namespace mismatch")
        if pair_group_id not in by_group:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen binding group absent from matched verdict")
        matched = by_group[pair_group_id]
        if (
            _v4_global(_v4_scope, 'str')(matched.get("event_date") or "") != event_date
            or _v4_global(_v4_scope, 'str')(matched.get("event_type") or "") != event_type
            or _v4_global(_v4_scope, '_normalize_code')(matched.get("code_raw")) != case_code
        ):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict event identity mismatch")
        matched_controls = _v4_global(_v4_scope, 'tuple')(
            _v4_global(_v4_scope, '_normalize_code')(matched.get(f"control_{index}_code_norm"))
            for index in _v4_global(_v4_scope, 'range')(1, 4)
        )
        if matched_controls != normalized_controls:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict control identity mismatch")
        series_key = (case_code, event_date)
        if series_key in seen_series_keys:
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("duplicate case/date in frozen binding")
        seen_series_keys.add(series_key)
        groups.append(
            _v4_global(_v4_scope, 'FrozenPrefixGroup')(
                pair_group_id=pair_group_id,
                episode_id=_v4_global(_v4_scope, 'str')(raw["episode_id"]),
                event_date=event_date,
                event_type=event_type,
                case_code=case_code,
                controls=normalized_controls,
            )
        )
    if _v4_global(_v4_scope, 'set')(by_group) != seen_group_ids or _v4_global(_v4_scope, 'len')(rows) != 24:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("matched verdict row set is not the frozen 24-group set")
    metadata = {
        "path": _v4_global(_v4_scope, 'str')(path),
        "sha256": _v4_global(_v4_scope, 'sha256_file')(path),
        "source_csv_declared": _v4_global(_v4_scope, 'str')(declared_source),
        "matched_verdict_path": _v4_global(_v4_scope, 'str')(matched_path),
        "matched_verdict_sha256": matched_sha,
        "groups": _v4_global(_v4_scope, 'len')(groups),
        "controls": _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, 'len')(group.controls) for group in groups),
        "resampled": False,
        "event_type_counts": _v4_global(_v4_scope, 'dict')(
            _v4_global(_v4_scope, 'Counter')(group.event_type for group in groups)
        ),
    }
    return groups, metadata


def _load_frozen_market_calendar_body(_v4_scope, /, calendar_path, parity_path, *, receipt_path, code_path):
    """Load the accepted R1 calendar and validate its S/D/T semantics.

    The market-day index is made only from the frozen ``calendar_sdt.parquet``
    S/D/T rows.  It never derives dates from nonempty per-security bars.
    ``calendar_parity_rows`` is read as a separate identity/semantic check.
    """

    import pandas as pd

    calendar_file = _v4_global(_v4_scope, 'Path')(calendar_path)
    parity_file = _v4_global(_v4_scope, 'Path')(parity_path)
    if not calendar_file.is_file() or not parity_file.is_file():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen R1 calendar artifact is missing")
    try:
        calendar_raw = pd.read_parquet(calendar_file)
        parity_raw = pd.read_parquet(parity_file, columns=_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, '_REQUIRED_PARITY_COLUMNS')))
    except _v4_global(_v4_scope, 'Exception') as error:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("cannot read frozen R1 calendar artifacts") from error
    calendar = _v4_global(_v4_scope, '_validate_calendar_frame')(
        calendar_raw, label="calendar_sdt", required=_v4_global(_v4_scope, '_REQUIRED_CALENDAR_COLUMNS')
    )
    parity = _v4_global(_v4_scope, '_validate_calendar_frame')(
        parity_raw, label="calendar_parity_rows", required=_v4_global(_v4_scope, '_REQUIRED_PARITY_COLUMNS')
    )
    sources = _v4_global(_v4_scope, 'set')(calendar["calendar_source"].astype(_v4_global(_v4_scope, 'str')))
    certifications = _v4_global(_v4_scope, 'set')(calendar["calendar_certification"].astype(_v4_global(_v4_scope, 'str')))
    if sources != {_v4_global(_v4_scope, 'CALENDAR_SOURCE')} or certifications != {_v4_global(_v4_scope, 'CALENDAR_CERTIFICATION')}:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 calendar source/certification identity mismatch")
    parity_sources = _v4_global(_v4_scope, 'set')(parity["calendar_source"].astype(_v4_global(_v4_scope, 'str')))
    parity_certs = _v4_global(_v4_scope, 'set')(parity["calendar_certification"].astype(_v4_global(_v4_scope, 'str')))
    if parity_sources != {_v4_global(_v4_scope, 'CALENDAR_SOURCE')} or parity_certs != {_v4_global(_v4_scope, 'CALENDAR_CERTIFICATION')}:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 parity source/certification identity mismatch")
    if calendar["sdt_id"].duplicated().any():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("calendar_sdt has duplicate sdt_id")
    market_dates = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(calendar["S"]) | _v4_global(_v4_scope, 'set')(calendar["D"]) | _v4_global(_v4_scope, 'set')(calendar["T"]))
    if not market_dates:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("frozen R1 calendar has no market dates")
    date_to_index = {date: index for index, date in _v4_global(_v4_scope, 'enumerate')(market_dates)}
    ordered = calendar.sort_values("sdt_id", kind="mergesort").reset_index(drop=True)
    for row in ordered.itertuples(index=False):
        if not (
            date_to_index[row.S] + 1 == date_to_index[row.D]
            and date_to_index[row.D] + 1 == date_to_index[row.T]
        ):
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 calendar S/D/T rows are not adjacent market sessions")
    calendar_triples = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'zip')(calendar["S"], calendar["D"], calendar["T"]))
    parity_triples = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'zip')(parity["S"], parity["D"], parity["T"]))
    # ``calendar_parity_rows`` is the R1 feature/parity join and only covers
    # the dates for which that downstream parity table was materialized.  The
    # full S/D/T calendar is older and wider.  Its triples are authoritative
    # for the market-session index; parity must be a subset and must never
    # introduce a triple absent from that frozen calendar.
    if not parity_triples.issubset(calendar_triples):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("calendar parity rows contain an unfrozen S/D/T triple")

    receipt = _v4_global(_v4_scope, 'Path')(receipt_path) if receipt_path is not None else None
    code = _v4_global(_v4_scope, 'Path')(code_path) if code_path is not None else None
    receipt_sha = _v4_global(_v4_scope, 'sha256_file')(receipt) if receipt is not None and receipt.is_file() else None
    code_sha = _v4_global(_v4_scope, 'sha256_file')(code) if code is not None and code.is_file() else None
    if receipt is not None and not receipt.is_file():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 calendar receipt is missing")
    if code is not None and not code.is_file():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 calendar implementation code is missing")
    if receipt is not None:
        receipt_payload = _v4_global(_v4_scope, '_read_json')(receipt)
        if receipt_payload.get("artifact") != "HK_OPERATOR_CALENDAR_HQ_20260912":
            raise _v4_global(_v4_scope, 'HKPrefixResearchError')("R1 calendar receipt artifact mismatch")
        _v4_global(_v4_scope, '_assert_safe_flags')(receipt_payload.get("research_flags") or {}, label="calendar receipt")
    return _v4_global(_v4_scope, 'FrozenMarketCalendar')(
        dates=_v4_global(_v4_scope, 'tuple')(market_dates),
        date_to_index=date_to_index,
        calendar_path=calendar_file,
        calendar_sha256=_v4_global(_v4_scope, 'sha256_file')(calendar_file),
        parity_path=parity_file,
        parity_sha256=_v4_global(_v4_scope, 'sha256_file')(parity_file),
        calendar_source=_v4_global(_v4_scope, 'CALENDAR_SOURCE'),
        calendar_certification=_v4_global(_v4_scope, 'CALENDAR_CERTIFICATION'),
        row_count=_v4_global(_v4_scope, 'len')(calendar),
        parity_row_count=_v4_global(_v4_scope, 'len')(parity),
        receipt_path=receipt,
        receipt_sha256=receipt_sha,
        code_path=code,
        code_sha256=code_sha,
    )
