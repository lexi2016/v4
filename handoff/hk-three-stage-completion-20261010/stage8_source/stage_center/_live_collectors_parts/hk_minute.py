"""stage_center.live_collectors: hk_minute (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _current_day_research_source(_v4_scope, source, plan, *, codes):
    """Keep only existing, exact-stage PyTDX rows for the explicit binding."""
    from stage_center.runner import RunnerError, V3_RESEARCH_STAGES, _validated_hk_binding_evidence
    from stage_center.raw_store import RAW_FIELDS, validate_rows

    binding = plan.universe_bindings.get("HK_CONNECT")
    if binding is None or binding.role != "HK_CURRENT_DAY_RESEARCH":
        raise RunnerError("HK_CURRENT_DAY_RESEARCH_BINDING_REQUIRED")
    evidence = _validated_hk_binding_evidence(binding, plan.trade_date)
    if plan.stage_id not in V3_RESEARCH_STAGES:
        raise RunnerError("HK_CURRENT_DAY_RESEARCH_MINUTE_STAGE_REQUIRED")
    if tuple(codes) != binding.codes:
        raise RunnerError("HK_CURRENT_DAY_RESEARCH_QUOTE_CODE_SET_MISMATCH")
    expected_research = next(item for item in evidence if item.startswith("research_source="))
    if any(str(item).startswith("research_source=") and item != expected_research for item in source.source_evidence):
        raise RunnerError("HK_CURRENT_DAY_RESEARCH_SOURCE_BINDING_MISMATCH")
    accepted = []
    cannot = list(source.cannot_confirm)
    seen = set()
    requested = set(codes)
    if source.source_id != "pytdx_exhq":
        raise RunnerError("HK_CURRENT_DAY_RESEARCH_PYTDX_SOURCE_REQUIRED")
    for row in source.rows:
        code = row.get("code") if isinstance(row, dict) else None
        if code not in requested or code in seen:
            cannot.append(f"HK_CURRENT_DAY_RESEARCH_QUOTE_CODE_INVALID:{code}")
            continue
        seen.add(code)
        core = {key: row[key] for key in RAW_FIELDS if key in row}
        valid, issues = validate_rows((core,), trade_date=plan.trade_date, stage_id=plan.stage_id, market="HK_CONNECT")
        if issues or not valid:
            cannot.append(f"HK_CURRENT_DAY_RESEARCH_QUOTE_TIME_OR_SHAPE_INVALID:{code}")
            continue
        price = _v4_global(_v4_scope, '_safe_number')(row.get("last_price"))
        bars = _v4_global(_v4_scope, '_safe_number')(row.get("bar_count"))
        if price is None or price <= 0 or bars is None or bars <= 0:
            cannot.append(f"HK_CURRENT_DAY_RESEARCH_QUOTE_PRICE_OR_BARS_MISSING:{code}")
            continue
        # The shared minute contract, not a current security record, owns
        # these quote fields. No Futu trigger/static lane is asserted here.
        accepted.append({**valid[0], "candidate_lanes": []})
    observed = {row["code"] for row in accepted}
    missing = tuple(dict.fromkeys((*source.missing_symbols, *(code for code in codes if code not in observed))))
    cannot.append("HK_CURRENT_DAY_RESEARCH_MEMBERSHIP_CANNOT_CONFIRM")
    if not accepted:
        cannot.append("HK_CURRENT_DAY_RESEARCH_REAL_MINUTE_DATA_MISSING")
    return _v4_global(_v4_scope, 'replace')(
        source, status=("PARTIAL_WITH_ROWS" if accepted and source.status in {"READY", "PARTIAL_WITH_ROWS"} else "CANNOT_CONFIRM"),
        rows=tuple(accepted), requested_rows=len(codes), missing_symbols=missing,
        cannot_confirm=tuple(dict.fromkeys(cannot)),
        source_evidence=tuple(dict.fromkeys((*source.source_evidence, *evidence,
            "hk_research_quote_source=EXISTING_PYTDX_EXHQ_EXACT_STAGE",
            "hk_research_live_lane_asserted=false"))),
    )


def _collect_hk_minute_body(_v4_scope, /, plan, *, codes, python_path, shared_root, process_runner, replay_provider):
    """Use ExHQ bars and the original Futu predicate on the fixed D-1 codes.

    ExHQ is the exact minute source, but it does not prove the V3
    ``LIVE_HKCONNECT_GAINER`` trigger.  The trigger came from a separate Futu
    full-market snapshot in the old V3 implementation. The V4 runner binds
    both probes to the same exact D-1 Top100; it never enumerates a plate.  The Futu result is copied only into the
    selection-only row fields; the immutable raw acquisition rows remain the
    ExHQ rows.
    """
    binding = getattr(plan, "universe_bindings", {}).get("HK_CONNECT")
    current_research = binding is not None and binding.role == "HK_CURRENT_DAY_RESEARCH"
    if current_research:
        from stage_center.runner import RunnerError, V3_RESEARCH_STAGES, _validated_hk_binding_evidence

        _validated_hk_binding_evidence(binding, plan.trade_date)
        if plan.stage_id not in V3_RESEARCH_STAGES:
            raise RunnerError("HK_CURRENT_DAY_RESEARCH_MINUTE_STAGE_REQUIRED")
        if tuple(codes) != binding.codes:
            raise RunnerError("HK_CURRENT_DAY_RESEARCH_QUOTE_CODE_SET_MISMATCH")
    if plan.stage_id == "STAGE_1545_1555" and not current_research:
        # Ordinary Stage 8 remains on the exact RT_DATA replay contract. An
        # explicit current-day research binding uses the existing PyTDX path
        # below and remains an unverified historical observation.
        return _v4_global(_v4_scope, '_collect_hk_stage8_replay')(plan, codes=codes, replay_provider=replay_provider)
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    module = _v4_global(_v4_scope, '_load_shared_module')(root, "scripts.live_acquisition.pytdx_exhq")
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    result = module.collect_pytdx_exhq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        _v4_global(_v4_scope, 'list')(codes),
        market="HK_CONNECT",
        process_runner=scoped_runner,
    )
    source = _v4_global(_v4_scope, '_to_source')(result, source_id="pytdx_exhq", route=("shared_pytdx_exhq_hk_current_day_research" if current_research else "shared_pytdx_exhq_hk_exact_d1_top100"), requested=_v4_global(_v4_scope, 'len')(codes))
    if current_research:
        return _current_day_research_source(_v4_scope, source, plan, codes=codes)
    if not source.rows:
        return source

    same_day_late_observation_recovery = bool(
        _v4_global(_v4_scope, 'getattr')(plan, "same_day_late_observation_recovery", False)
    )
    if same_day_late_observation_recovery or _v4_global(_v4_scope, 'getattr')(plan, "historical_backfill", False):
        return _refresh_hk_active_lanes_body(
            _v4_scope,
            source,
            codes=codes,
            python_path=python_path,
            shared_root=root,
            process_runner=process_runner,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
            historical_backfill=_v4_global(_v4_scope, 'getattr')(plan, "historical_backfill", False),
            same_day_late_observation_recovery=same_day_late_observation_recovery,
        )

    # This is intentionally a second, read-only module load.  The shared
    # auction module owns the already-reviewed Futu snapshot bridge and keeps
    # its child cwd/PYTHONPATH scoped by the same runner wrapper as ExHQ.
    return _v4_global(_v4_scope, 'refresh_hk_active_lanes')(
        source,
        codes=codes,
        python_path=python_path,
        shared_root=root,
        process_runner=process_runner,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        cutoff_at=_v4_global(_v4_scope, 'STAGE_BY_ID')[plan.stage_id].cutoff,
    )


def _refresh_hk_active_lanes_body(_v4_scope, /, source, *, codes, python_path, shared_root, process_runner, trade_date, stage_id, cutoff_at, historical_backfill=False, same_day_late_observation_recovery=False):
    """Re-probe only the V3 active trigger for an existing raw HK source.

    This is the recovery path after raw publication has succeeded but a
    selection publication failed.  It never calls ExHQ and never changes the
    immutable raw rows; it only rebuilds the selection-only lane metadata from
    the same explicit code-bounded Futu snapshot and carries its evidence.
    """
    root = _v4_global(_v4_scope, '_shared_scripts_root')(shared_root)
    scoped_runner = _v4_global(_v4_scope, '_scoped_process_runner')(root, process_runner)
    active, evidence, probe_errors = _v4_global(_v4_scope, '_futu_hkconnect_active_snapshot')(
        root,
        codes=codes,
        python_path=python_path,
        process_runner=scoped_runner,
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    )
    if "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors and trade_date and cutoff_at:
        cannot_confirm = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors)))
        source_evidence = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence)))
        if historical_backfill or same_day_late_observation_recovery:
            recovery_evidence = (
                ("same_day_late_observation_recovery=true",)
                if same_day_late_observation_recovery
                else ()
            )
            return _v4_global(_v4_scope, 'replace')(
                source,
                status="PARTIAL_WITH_ROWS",
                rows=_v4_global(_v4_scope, 'tuple')(source.rows),
                cannot_confirm=cannot_confirm,
                source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((
                    *source_evidence,
                    *recovery_evidence,
                    "active_snapshot_degraded_to_pytdx_observation=true",
                ))),
            )
        return _v4_global(_v4_scope, 'replace')(
            source,
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=cannot_confirm,
            source_evidence=source_evidence,
        )
    enriched: list[dict[str, Any]] = []
    for row in source.rows:
        code = _v4_global(_v4_scope, '_canonical_hk_code')(row.get("code"))
        merged = _v4_global(_v4_scope, 'dict')(row)
        # A lane is valid only when this exact full-scan probe matched the
        # code.  Never carry a D-1/static lane into the live minute copy.
        merged["candidate_lanes"] = []
        snapshot = active.get(code)
        if snapshot is not None:
            merged["candidate_lanes"] = ["LIVE_HKCONNECT_GAINER"]
            merged["source_universe"] = "HK_CONNECT_D1_TOP100"
            merged["data_confidence"] = "STAGE_RTDATA_CONFIRMED"
            merged["active_gainer_pass"] = True
            merged["volume_ratio"] = snapshot.get("volume_ratio")
            merged["active_snapshot_status"] = "FUTU_HKCONNECT_FULL_SCAN"
        enriched.append(merged)
    cannot = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.cannot_confirm, *probe_errors)))
    return _v4_global(_v4_scope, 'replace')(source, rows=_v4_global(_v4_scope, 'tuple')(enriched), cannot_confirm=cannot, source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*source.source_evidence, *evidence))))
