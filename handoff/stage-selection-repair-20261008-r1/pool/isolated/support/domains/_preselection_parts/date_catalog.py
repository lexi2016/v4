"""domains.preselection: date_catalog (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _date_catalog_body(_v4_scope, /, store, *, current_date, stage_selection_root):
    catalog = store.read_catalog()
    persisted_system_date = _v4_global(_v4_scope, 'str')(catalog["system_date"])
    materialized = catalog.get("materialized_rows", {})
    independent_dates = _v4_global(_v4_scope, '_verified_independent_pool_dates')(store)
    stage_artifacts = _v4_global(_v4_scope, '_verified_stage_artifact_catalog')(stage_selection_root)
    stage_artifact_dates = _v4_global(_v4_scope, 'tuple')(stage_artifacts)
    wall_date = current_date or _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai")).strftime("%Y%m%d")
    # The natural-day clock is a runtime fact, not a persisted producer state.
    # A stale catalog must not make an explicit/current date disappear from the
    # date family merely because today's pools are incomplete.
    system_date = wall_date
    candidate_dates = (
        _v4_global(_v4_scope, 'list')(catalog["stage_dates"])
        + [date for date, rows in materialized.items() if rows > 0]
        + _v4_global(_v4_scope, 'list')(independent_dates)
        + _v4_global(_v4_scope, 'list')(stage_artifact_dates)
    )
    # Independent pool materialization and stage-center artifacts are separate
    # evidence lanes. A shared date must remain visible when either lane is
    # present; do not let an independent pool date hide an exact stage date.
    evidence_stage = _v4_global(_v4_scope, 'sorted')(
        {
            date
            for date in (
                _v4_global(_v4_scope, 'list')(catalog["stage_dates"])
                + [date for date, rows in materialized.items() if rows > 0]
                + _v4_global(_v4_scope, 'list')(stage_artifact_dates)
            )
            if date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
    )
    stage = _v4_global(_v4_scope, 'list')(evidence_stage)
    future = _v4_global(_v4_scope, 'sorted')(
        {
            date
            for date in _v4_global(_v4_scope, 'list')(catalog["future_target_dates"])
            + _v4_global(_v4_scope, 'list')(independent_dates)
            # Producer target dates are relative to the persisted catalog
            # clock.  The wall date still controls current-date navigation;
            # retaining this distinction keeps a verified target visible when
            # the catalog itself is stale by one or more days.
            if date > persisted_system_date
            if _v4_global(_v4_scope, '_is_trading_date')(date)
        }
    )
    # ``stage_dates`` and ``default_date`` are evidence projections only.  The
    # persisted catalog date is not proof that a same-date artifact exists and
    # must never be promoted merely because the producer catalog is stale.
    # The legacy pool-import lane can freeze while the verified stage-center
    # lane keeps producing, so the default is the newest date with materialized
    # pool rows or a verified stage artifact -- never the newest date of the
    # legacy lane alone, and never a stage-list date without rows or artifacts.
    default_candidates = _v4_global(_v4_scope, 'sorted')(
        {
            date
            for date, rows in materialized.items()
            if rows > 0 and date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
        | {
            date
            for date, item in stage_artifacts.items()
            if _v4_global(_v4_scope, 'str')(item.get("status")) in ("MATERIALIZED", "PARTIAL")
            if date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
    )
    default = (
        default_candidates[-1]
        if default_candidates
        else (evidence_stage[-1] if evidence_stage else "")
    )
    navigation_dates = _v4_global(_v4_scope, 'set')(stage + future + _v4_global(_v4_scope, 'list')(stage_artifact_dates))
    hk_observation_only_dates = _v4_global(_v4_scope, '_hk_observation_only_dates')()
    if _v4_global(_v4_scope, '_is_navigation_trading_date')(system_date):
        # The wall-clock trading date is navigable so the UI can show an
        # explicit DATA_BLOCKED_EMPTY/CANNOT_CONFIRM page, but it is not added
        # to stage_dates or default_date without exact evidence.
        navigation_dates.add(system_date)
    materialized_stage_dates = _v4_global(_v4_scope, 'sorted')(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "MATERIALIZED"
    )
    partial_stage_dates = _v4_global(_v4_scope, 'sorted')(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "PARTIAL"
    )
    blocked_stage_dates = _v4_global(_v4_scope, 'sorted')(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "BLOCKED"
    )
    return {
        "ok": True,
        "default_date": default,
        # Navigation is not artifact evidence. Keep the original default_date
        # contract while allowing the current A-share or HK securities day to be empty.
        "navigation_date": system_date if _v4_global(_v4_scope, '_is_navigation_trading_date')(system_date) else default,
        "navigation_timezone": "Asia/Shanghai",
        "navigation_policy": "A_SHARE_OR_HK_SECURITIES_TRADING_DAY_ELSE_EVIDENCE_DEFAULT",
        "dates": _v4_global(_v4_scope, 'sorted')(navigation_dates, reverse=True),
        "stage_dates": stage,
        "future_target_dates": future,
        "system_date": system_date,
        "hk_observation_only_dates": hk_observation_only_dates,
        "stage_artifacts": stage_artifacts,
        "materialized": materialized_stage_dates,
        "partial": partial_stage_dates,
        "blocked": blocked_stage_dates,
        "materialized_stage_dates": materialized_stage_dates,
        "partial_stage_dates": partial_stage_dates,
        "blocked_stage_dates": blocked_stage_dates,
    }


def __verified_stage_artifact_catalog_body(_v4_scope, /, stage_selection_root):
    """Project exact-date stage artifacts from the existing selection root.

    This is deliberately a read-only view of the stage-center latest pointer.
    A date is ``MATERIALIZED`` only when at least one pointer entry verifies
    its immutable run trio; invalid entries remain visible as ``BLOCKED``.
    No date or stage artifact is copied into the data store.
    """
    if stage_selection_root is None:
        return {}
    root = _v4_global(_v4_scope, 'Path')(stage_selection_root).expanduser()
    try:
        latest = _v4_global(_v4_scope, 'SelectionStore')(root)._latest()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'SelectionError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')):
        return {}
    entries = latest.get("entries")
    if not _v4_global(_v4_scope, 'isinstance')(entries, _v4_global(_v4_scope, 'Mapping')):
        return {}
    by_date: dict[str, dict[str, Any]] = {}
    store = _v4_global(_v4_scope, 'SelectionStore')(root)
    for key, entry in entries.items():
        if not _v4_global(_v4_scope, 'isinstance')(key, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'isinstance')(entry, _v4_global(_v4_scope, 'Mapping')):
            continue
        parts = key.split("/")
        if _v4_global(_v4_scope, 'len')(parts) != 3 or not _v4_global(_v4_scope, 're').fullmatch(r"\d{8}", parts[0]):
            continue
        trade_date, stage_id, market = parts
        item = by_date.setdefault(
            trade_date,
            {
                "status": "BLOCKED",
                "trade_date": trade_date,
                "stage_ids": [],
                "markets": [],
                "verified_markets": [],
                "expected_markets": {},
                "missing_markets": [],
                "verified_entries": 0,
                "blocked_entries": 0,
                "receipt_paths": [],
                "artifact_ids": [],
                "cannot_confirm": [],
            },
        )
        if stage_id not in item["stage_ids"]:
            item["stage_ids"].append(stage_id)
        if market not in item["markets"]:
            item["markets"].append(market)
        try:
            envelope = store.read_verified(trade_date, stage_id, market)
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'SelectionError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')) as error:
            item["blocked_entries"] += 1
            item["cannot_confirm"].append(f"STAGE_ARTIFACT_INVALID:{stage_id}:{market}:{_v4_global(_v4_scope, 'type')(error).__name__}")
            continue
        item["verified_entries"] += 1
        item["verified_markets"].append(market)
        item["receipt_paths"].append(
            f"selection_runs/{trade_date}/{market}_SELECTION_{stage_id}/{entry.get('run_id', '')}/receipt.json"
        )
        artifact_id = envelope.get("artifact_id")
        if artifact_id:
            item["artifact_ids"].append(_v4_global(_v4_scope, 'str')(artifact_id))
        selection_status = _v4_global(_v4_scope, 'str')(envelope.get("selection_status") or "CANNOT_CONFIRM")
        if selection_status in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"}:
            item["cannot_confirm"].extend(_v4_global(_v4_scope, 'str')(reason) for reason in envelope.get("cannot_confirm") or [])
    for item in by_date.values():
        verified_by_stage: dict[str, set[str]] = {}
        for key, entry in entries.items():
            if not _v4_global(_v4_scope, 'isinstance')(key, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'isinstance')(entry, _v4_global(_v4_scope, 'Mapping')):
                continue
            parts = key.split("/")
            if _v4_global(_v4_scope, 'len')(parts) != 3 or parts[0] != item["trade_date"]:
                continue
            stage_id, market = parts[1], parts[2]
            if stage_id not in _v4_global(_v4_scope, 'STAGE_BY_ID'):
                continue
            try:
                store.read_verified(item["trade_date"], stage_id, market)
            except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'SelectionError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')):
                continue
            verified_by_stage.setdefault(stage_id, _v4_global(_v4_scope, 'set')()).add(market)
        for stage_id in item["stage_ids"]:
            expected = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets) if stage_id in _v4_global(_v4_scope, 'STAGE_BY_ID') else ()
            item["expected_markets"][stage_id] = _v4_global(_v4_scope, 'list')(expected)
            missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(expected) - verified_by_stage.get(stage_id, _v4_global(_v4_scope, 'set')()))
            for market in missing:
                item["missing_markets"].append(f"{stage_id}:{market}")
                item["cannot_confirm"].append(f"STAGE_MARKET_MISSING:{stage_id}:{market}")
        if item["verified_entries"] == 0:
            item["status"] = "BLOCKED"
        elif item["blocked_entries"] or item["cannot_confirm"]:
            item["status"] = "PARTIAL"
        else:
            item["status"] = "MATERIALIZED"
        item["stage_ids"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["stage_ids"]))
        item["markets"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["markets"]))
        item["verified_markets"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["verified_markets"]))
        item["expected_markets"] = {
            stage_id: _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(markets))
            for stage_id, markets in item["expected_markets"].items()
        }
        item["missing_markets"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["missing_markets"]))
        item["receipt_paths"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["receipt_paths"]))
        item["artifact_ids"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["artifact_ids"]))
        item["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(item["cannot_confirm"]))
    return _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(by_date.items()))


def __verified_independent_pool_dates_body(_v4_scope, /, store):
    """Discover dates with at least one SHA-verified independent pool.

    Pool families are independently published.  Requiring ``read_all`` here
    made one missing optional pool hide a target date whose other artifact
    trio was already complete.
    """
    root = _v4_global(_v4_scope, 'Path')(store.root) / "preselection_pools"
    if not root.is_dir():
        return ()
    pool_store = _v4_global(_v4_scope, 'PreselectionPoolStore')(store.root)
    dates: list[str] = []
    try:
        children = _v4_global(_v4_scope, 'tuple')(root.iterdir())
    except _v4_global(_v4_scope, 'OSError'):
        return ()
    for child in children:
        date = child.name
        if not child.is_dir() or _v4_global(_v4_scope, 'len')(date) != 8 or not date.isdigit():
            continue
        for pool_id in _v4_global(_v4_scope, 'POOL_ORDER'):
            try:
                pool_store.read_pool(date, pool_id)
            except (_v4_global(_v4_scope, 'FileNotFoundError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
                continue
            dates.append(date)
            break
    return _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(dates)))
