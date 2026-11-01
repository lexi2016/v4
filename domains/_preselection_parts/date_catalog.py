"""domains.preselection: date_catalog (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global
import stat
from typing import Mapping


def _date_catalog_body(
    _v4_scope,
    /,
    store,
    *,
    current_date,
    stage_selection_root,
    preselection_source_root,
):
    catalog = store.read_catalog()
    persisted_system_date = str(catalog["system_date"])
    materialized = catalog.get("materialized_rows", {})
    independent_dates = _v4_global(
        _v4_scope,
        '_verified_independent_pool_dates',
    )(
        store,
        preselection_source_root=preselection_source_root,
        include_evidence=True,
    )
    independent_dates, independent_pool_evidence = independent_dates
    stage_artifacts = _v4_global(_v4_scope, '_verified_stage_artifact_catalog')(stage_selection_root)
    stage_artifact_dates = tuple(stage_artifacts)
    wall_date = current_date or _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'ZoneInfo')("Asia/Shanghai")).strftime("%Y%m%d")
    # The natural-day clock is a runtime fact, not a persisted producer state.
    # A stale catalog must not make an explicit/current date disappear from the
    # date family merely because today's pools are incomplete.
    system_date = wall_date
    candidate_dates = (
        list(catalog["stage_dates"])
        + [date for date, rows in materialized.items() if rows > 0]
        + list(independent_dates)
        + list(stage_artifact_dates)
    )
    # Independent pool materialization and stage-center artifacts are separate
    # evidence lanes. A shared date must remain visible when either lane is
    # present; do not let an independent pool date hide an exact stage date.
    evidence_stage = sorted(
        {
            date
            for date in (
                list(catalog["stage_dates"])
                + [date for date, rows in materialized.items() if rows > 0]
                + list(stage_artifact_dates)
            )
            if date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
    )
    stage = list(evidence_stage)
    future = sorted(
        {
            date
            for date in list(catalog["future_target_dates"])
            + list(independent_dates)
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
    default_candidates = sorted(
        {
            date
            for date, rows in materialized.items()
            if rows > 0 and date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
        | {
            date
            for date, item in stage_artifacts.items()
            if str(item.get("status")) in ("MATERIALIZED", "PARTIAL")
            if date <= system_date and _v4_global(_v4_scope, '_is_trading_date')(date)
        }
    )
    default = (
        default_candidates[-1]
        if default_candidates
        else (evidence_stage[-1] if evidence_stage else "")
    )
    navigation_dates = set(stage + future + list(stage_artifact_dates))
    hk_observation_only_dates = _v4_global(_v4_scope, '_hk_observation_only_dates')()
    if _v4_global(_v4_scope, '_is_navigation_trading_date')(system_date):
        # The wall-clock trading date is navigable so the UI can show an
        # explicit DATA_BLOCKED_EMPTY/CANNOT_CONFIRM page, but it is not added
        # to stage_dates or default_date without exact evidence.
        navigation_dates.add(system_date)
    materialized_stage_dates = sorted(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "MATERIALIZED"
    )
    partial_stage_dates = sorted(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "PARTIAL"
    )
    blocked_stage_dates = sorted(
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
        "dates": sorted(navigation_dates, reverse=True),
        "stage_dates": stage,
        "future_target_dates": future,
        "independent_pool_evidence": independent_pool_evidence,
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
    except (OSError, _v4_global(_v4_scope, 'SelectionError'), ValueError, TypeError):
        return {}
    entries = latest.get("entries")
    if not isinstance(entries, _v4_global(_v4_scope, 'Mapping')):
        return {}
    by_date: dict[str, dict[str, Any]] = {}
    store = _v4_global(_v4_scope, 'SelectionStore')(root)
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, _v4_global(_v4_scope, 'Mapping')):
            continue
        parts = key.split("/")
        if len(parts) != 3 or not _v4_global(_v4_scope, 're').fullmatch(r"\d{8}", parts[0]):
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
        except (OSError, _v4_global(_v4_scope, 'SelectionError'), ValueError, TypeError) as error:
            item["blocked_entries"] += 1
            item["cannot_confirm"].append(f"STAGE_ARTIFACT_INVALID:{stage_id}:{market}:{type(error).__name__}")
            continue
        item["verified_entries"] += 1
        item["verified_markets"].append(market)
        item["receipt_paths"].append(
            f"selection_runs/{trade_date}/{market}_SELECTION_{stage_id}/{entry.get('run_id', '')}/receipt.json"
        )
        artifact_id = envelope.get("artifact_id")
        if artifact_id:
            item["artifact_ids"].append(str(artifact_id))
        selection_status = str(envelope.get("selection_status") or "CANNOT_CONFIRM")
        if selection_status in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"}:
            item["cannot_confirm"].extend(str(reason) for reason in envelope.get("cannot_confirm") or [])
    for item in by_date.values():
        verified_by_stage: dict[str, set[str]] = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, _v4_global(_v4_scope, 'Mapping')):
                continue
            parts = key.split("/")
            if len(parts) != 3 or parts[0] != item["trade_date"]:
                continue
            stage_id, market = parts[1], parts[2]
            if stage_id not in _v4_global(_v4_scope, 'STAGE_BY_ID'):
                continue
            try:
                store.read_verified(item["trade_date"], stage_id, market)
            except (OSError, _v4_global(_v4_scope, 'SelectionError'), ValueError, TypeError):
                continue
            verified_by_stage.setdefault(stage_id, set()).add(market)
        for stage_id in item["stage_ids"]:
            expected = tuple(_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets) if stage_id in _v4_global(_v4_scope, 'STAGE_BY_ID') else ()
            item["expected_markets"][stage_id] = list(expected)
            missing = sorted(set(expected) - verified_by_stage.get(stage_id, set()))
            for market in missing:
                item["missing_markets"].append(f"{stage_id}:{market}")
                item["cannot_confirm"].append(f"STAGE_MARKET_MISSING:{stage_id}:{market}")
        if item["verified_entries"] == 0:
            item["status"] = "BLOCKED"
        elif item["blocked_entries"] or item["cannot_confirm"]:
            item["status"] = "PARTIAL"
        else:
            item["status"] = "MATERIALIZED"
        item["stage_ids"] = sorted(set(item["stage_ids"]))
        item["markets"] = sorted(set(item["markets"]))
        item["verified_markets"] = sorted(set(item["verified_markets"]))
        item["expected_markets"] = {
            stage_id: sorted(set(markets))
            for stage_id, markets in item["expected_markets"].items()
        }
        item["missing_markets"] = sorted(set(item["missing_markets"]))
        item["receipt_paths"] = sorted(set(item["receipt_paths"]))
        item["artifact_ids"] = sorted(set(item["artifact_ids"]))
        item["cannot_confirm"] = sorted(set(item["cannot_confirm"]))
    return dict(sorted(by_date.items()))


def __verified_independent_pool_dates_body(
    _v4_scope,
    /,
    store,
    *,
    preselection_source_root=None,
    include_evidence=False,
):
    """Discover dates with at least one SHA-verified independent pool.

    Pool families are independently published.  Requiring ``read_all`` here
    made one missing optional pool hide a target date whose other artifact
    trio was already complete.
    """
    roots = [_v4_global(_v4_scope, 'Path')(store.root)]
    if preselection_source_root is not None:
        source_root = _v4_global(_v4_scope, 'Path')(preselection_source_root).expanduser()
        if source_root not in roots:
            roots.append(source_root)
    resolver = _v4_global(_v4_scope, 'PreselectionSourceResolver')(
        store.root,
        source_root=preselection_source_root,
    )
    from infrastructure import preselection_pool_sources as pool_source_reader
    import infrastructure.preselection_pool_store as pool_store_api

    dates: list[str] = []
    evidence_by_date: dict[str, Any] = {}
    for pool_root in roots:
        root = pool_root / "preselection_pools"
        try:
            root_stat = root.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError(
                "preselection pool root is not a safe directory"
            )
        children = tuple(root.iterdir())
        for child in children:
            date = child.name
            try:
                child_stat = child.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(child_stat.st_mode):
                raise ValueError(
                    "preselection pool date directory cannot be a symlink"
                )
            if len(date) != 8 or not date.isdigit():
                continue
            if not stat.S_ISDIR(child_stat.st_mode):
                raise ValueError(
                    f"preselection pool date path is not a directory: {date}"
                )
            snapshots, integrity_errors = pool_source_reader.read_all_with_quarantine(
                resolver,
                date,
                _api=pool_store_api,
            )
            if not snapshots:
                continue
            dates.append(date)
            pools_by_id: dict[str, dict[str, Any]] = {}
            for snapshot in snapshots:
                artifact = snapshot.get("artifact")
                pool_id = artifact.get("pool_id") if isinstance(artifact, Mapping) else None
                if pool_id not in pool_store_api.POOL_ORDER or pool_id in pools_by_id:
                    raise ValueError(
                        "date catalog pool snapshot identity is invalid"
                    )
                pools_by_id[pool_id] = {
                    "pool_id": pool_id,
                    "market_lane": "HK_CONNECT" if pool_id == "hkconnect_d1_top100" else "A_SHARE",
                    "market": artifact.get("market"),
                    "status": "VERIFIED",
                    "source_role": artifact.get("source_role"),
                    "source_sha256": artifact.get("source_sha256"),
                    "pool_sha256": snapshot.get("pool_sha256"),
                    "physical_source_root": snapshot.get("physical_source_root", str(resolver.root_for_date(date))),
                    "diagnostics": [],
                }
            for error in integrity_errors:
                if not isinstance(error, pool_store_api.PreselectionPoolIntegrityError):
                    raise ValueError(
                        "date catalog quarantine outcome is untyped"
                    )
                if error.pool_id not in pool_store_api.POOL_ORDER or error.pool_id in pools_by_id:
                    raise ValueError(
                        "date catalog quarantine pool identity is invalid"
                    )
                pools_by_id[error.pool_id] = {
                    "pool_id": error.pool_id,
                    "market_lane": "HK_CONNECT" if error.pool_id == "hkconnect_d1_top100" else "A_SHARE",
                    "market": "HK" if error.pool_id == "hkconnect_d1_top100" else "A",
                    "status": "CANNOT_CONFIRM",
                    "source_role": None,
                    "source_sha256": None,
                    "pool_sha256": None,
                    "physical_source_root": str(resolver.root_for_date(date)),
                    "diagnostics": [f"PRESELECTION_POOL_INTEGRITY:{error.pool_id}:{error.reason}"],
                }
            for pool_id in pool_store_api.POOL_ORDER:
                if pool_id not in pools_by_id:
                    pools_by_id[pool_id] = {
                        "pool_id": pool_id,
                        "market_lane": "HK_CONNECT" if pool_id == "hkconnect_d1_top100" else "A_SHARE",
                        "market": "HK" if pool_id == "hkconnect_d1_top100" else "A",
                        "status": "MISSING",
                        "source_role": None,
                        "source_sha256": None,
                        "pool_sha256": None,
                        "physical_source_root": str(resolver.root_for_date(date)),
                        "diagnostics": [f"POOL_NOT_AVAILABLE:{pool_id}"],
                    }
            evidence_by_date[date] = {
                "trade_date": date,
                "physical_source_root": str(resolver.root_for_date(date)),
                "pools": pools_by_id,
            }
    normalized_dates = tuple(
        sorted(set(dates))
    )
    if include_evidence:
        return normalized_dates, evidence_by_date
    return normalized_dates
