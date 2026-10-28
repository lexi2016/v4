"""stage_center.live_collectors: hk_active_snapshot (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __futu_hkconnect_active_snapshot_body(_v4_scope, /, shared_root, *, codes, python_path, process_runner, trade_date, cutoff_at):
    """Run the old V3 Futu full-scan trigger against one explicit code set.

    The predicate is intentionally byte-for-byte in meaning with V3's
    ``_futu_hkconnect_active_snapshot``: positive percentage change, turnover
    at least 20m HKD, and volume ratio at least one.  A partial/failed full
    scan cannot establish an inactive result, therefore it returns no active
    rows and a fail-closed evidence marker.
    """
    requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, '_canonical_hk_code')(code) for code in codes if _v4_global(_v4_scope, '_canonical_hk_code')(code)))
    # Preserve the historical trigger identifier used by recovery, while
    # explicitly distinguishing it from full-market coverage.
    evidence_base = ("active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN", "active_snapshot_scope=EXPLICIT_REQUESTED_CODES", f"active_snapshot_requested_rows={_v4_global(_v4_scope, 'len')(requested)}")
    if trade_date is not None and cutoff_at is not None:
        evidence_base += (f"active_snapshot_trade_date={trade_date}", f"active_snapshot_cutoff={cutoff_at}")
    if not requested:
        return {}, evidence_base + ("active_snapshot_sha256=" + _v4_global(_v4_scope, 'hashlib').sha256(b"[]").hexdigest(),), ("HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE",)
    from stage_center.attempt_evidence import wall_now, emit_snapshot, temporal_diagnostic
    fetch_started_at = wall_now()
    try:
        module = _v4_global(_v4_scope, '_load_shared_module')(shared_root, "shared_data.hk_auction_0920")
        # shared_data.hk_auction_0920's reviewed bridge takes the explicit
        # Python executable first, then the exact code list.  A narrow
        # signature check also keeps deterministic test doubles (which expose
        # the older ``(codes, ...)`` seam) from changing production behavior.
        fetch = module.fetch_futu_snapshot
        first_parameter = _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(_v4_global(_v4_scope, 'inspect').signature(fetch).parameters), "")
        if first_parameter in {"codes", "symbols"}:
            fetched = fetch(_v4_global(_v4_scope, 'list')(requested), process_runner=process_runner)
        else:
            fetched = fetch(python_path, _v4_global(_v4_scope, 'list')(requested), process_runner=process_runner)
        if not _v4_global(_v4_scope, 'isinstance')(fetched, _v4_global(_v4_scope, 'tuple')) or _v4_global(_v4_scope, 'len')(fetched) != 2:
            raise _v4_global(_v4_scope, 'ValueError')("Futu snapshot bridge returned an invalid result")
        raw_rows, errors = fetched
        snapshot_rows = [item for item in (raw_rows or ()) if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping'))]
        errors_tuple = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(item) for item in (errors or ()) if _v4_global(_v4_scope, 'str')(item))
    except _v4_global(_v4_scope, 'Exception'):
        snapshot_rows = []
        errors_tuple = ("bridge_error",)

    fetch_finished_at = wall_now()
    canonical_rows: list[dict[str, Any]] = []
    by_code: dict[str, Mapping[str, Any]] = {}
    for raw in snapshot_rows:
        code = _v4_global(_v4_scope, '_canonical_hk_code')(raw.get("code") or raw.get("stock_code") or raw.get("symbol"))
        if not code or code in by_code:
            continue
        normalized = {
            "code": code,
            "prev_close_price": _v4_global(_v4_scope, '_safe_number')(raw.get("prev_close_price") or raw.get("prev_close")),
            "last_price": _v4_global(_v4_scope, '_safe_number')(raw.get("last_price") or raw.get("last")),
            "turnover": _v4_global(_v4_scope, '_safe_number')(raw.get("turnover")),
            "volume_ratio": _v4_global(_v4_scope, '_safe_number')(raw.get("volume_ratio")),
            "update_time": _v4_global(_v4_scope, 'str')(raw.get("update_time") or raw.get("update_time_us") or ""),
        }
        by_code[code] = normalized
        canonical_rows.append(normalized)
    canonical_rows.sort(key=lambda item: item["code"])
    snapshot_sha = _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    codes_sha = _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, 'list')(requested), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence = evidence_base + (
        f"active_snapshot_codes_sha256={codes_sha}",
        f"active_snapshot_sha256={snapshot_sha}",
        f"active_snapshot_returned_rows={_v4_global(_v4_scope, 'len')(by_code)}",
    )
    if trade_date is not None and cutoff_at is not None:
        diagnostic = temporal_diagnostic(
            canonical_rows, trade_date=trade_date, cutoff_at=cutoff_at,
            parse_timestamp=_v4_global(_v4_scope, '_exact_market_timestamp'),
            fetch_started_at=fetch_started_at, fetch_finished_at=fetch_finished_at,
            snapshot_sha256=snapshot_sha, requested_codes_sha256=codes_sha,
            bridge_errors=errors_tuple,
        )
        emit_snapshot(diagnostic)
        evidence += ("active_snapshot_temporal_diagnostic=" +
                     _v4_global(_v4_scope, 'json').dumps(diagnostic, ensure_ascii=False,
                                                       sort_keys=True, separators=(",", ":")),)
    if errors_tuple or _v4_global(_v4_scope, 'set')(by_code) != _v4_global(_v4_scope, 'set')(requested):
        return {}, evidence, ("HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE",)
    if trade_date is not None and cutoff_at is not None and not _v4_global(_v4_scope, '_snapshot_temporal_cutoff_safe')(
        canonical_rows,
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    ):
        return {}, evidence + ("active_snapshot_temporal_cutoff_safe=false",), ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",)
    if trade_date is not None and cutoff_at is not None:
        evidence += ("active_snapshot_temporal_cutoff_safe=true",)

    active: dict[str, Mapping[str, Any]] = {}
    for code, row in by_code.items():
        prev_close = row.get("prev_close_price")
        last_price = row.get("last_price")
        turnover = row.get("turnover")
        volume_ratio = row.get("volume_ratio")
        pct = ((_v4_global(_v4_scope, 'float')(last_price) / _v4_global(_v4_scope, 'float')(prev_close)) - 1.0) * 100.0 if prev_close not in (None, 0) and last_price is not None else None
        if pct is not None and pct > 0 and turnover is not None and turnover >= 20_000_000 and volume_ratio is not None and volume_ratio >= 1:
            active[code] = row
    if not active:
        return {}, evidence + ("active_snapshot_active_rows=0",), ("HK_ACTIVE_GAINER_NO_MATCH",)
    return active, evidence + (f"active_snapshot_active_rows={_v4_global(_v4_scope, 'len')(active)}",), ()
