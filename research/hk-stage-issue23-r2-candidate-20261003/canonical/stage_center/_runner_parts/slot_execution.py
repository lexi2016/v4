"""stage_center.runner: slot_execution (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageCenterRunner__run_one_body(_v4_scope, /, self, decision, *, historical_backfill, backfill_run_id, historical_markets):
    if historical_backfill and backfill_run_id is None:
        run_id = _v4_global(_v4_scope, 'uuid4')().hex
        return self._backfill_runner(run_id)._run_one(
            decision,
            historical_backfill=True,
            backfill_run_id=run_id,
            historical_markets=historical_markets,
        )
    trade_date, stage_id = decision.trade_date, decision.stage_id
    markets = _v4_global(_v4_scope, '_resolve_stage_market_scope')(
        stage_id,
        trade_date,
        historical_backfill=historical_backfill,
        historical_markets=historical_markets,
    )
    if not markets:
        raise _v4_global(_v4_scope, 'RunnerError')("no securities market is open for this stage date")
    candidate_error = ""
    hk_binding: StageUniverseBinding | None = None
    hk_binding_error = ""
    try:
        candidate = _v4_global(_v4_scope, 'read_candidate_input')(self.config.candidate_acquisition_root, trade_date)
    except (_v4_global(_v4_scope, 'CandidateInputError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        # A and HK have separate fixed authorities; never fill either
        # lane from a full-market scan when the other lane is unavailable.
        candidate = None
        candidate_error = _v4_global(_v4_scope, 'str')(error)
        try:
            if "HK_CONNECT" not in markets or self.config.hk_d1_root is None:
                raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 root is required")
            hk_binding = _v4_global(_v4_scope, '_build_hk_stage_binding')(
                self.config.hk_d1_root,
                trade_date,
                preselection_source_root=self.config.preselection_source_root,
            )
        except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as hk_error:
            errors = {"A_SHARE": candidate_error, "HK_CONNECT": _v4_global(_v4_scope, 'str')(hk_error)}
            return self._write_receipt({
                "status": "CANNOT_CONFIRM", "due_status": decision.status,
                "trade_date": trade_date, "stage_id": stage_id,
                "error": candidate_error, "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING",
                "markets": {market: {"status": "CANNOT_CONFIRM", "selected_rows": 0,
                            "cannot_confirm": [errors[market]], "write_performed": False}
                            for market in markets}, "write_performed": False,
            }, trade_date, stage_id)
        candidate = _v4_global(_v4_scope, '_candidate_from_hk_binding')(
            root=self.config.candidate_acquisition_root,
            trade_date=trade_date,
            binding=hk_binding,
        )
    a_candidate_missing = _v4_global(_v4_scope, 'bool')(candidate_error)
    if (
        not self.config.injected_test_mode
        and "HK_CONNECT" in markets
        and hk_binding is None
    ):
        try:
            if self.config.hk_d1_root is None:
                raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 root is required")
            hk_binding = _v4_global(_v4_scope, '_build_hk_stage_binding')(
                self.config.hk_d1_root,
                trade_date,
                preselection_source_root=self.config.preselection_source_root,
            )
        except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
            # Keep the HK authority failure lane-local.  A valid A
            # candidate may still be planned and collected independently.
            hk_binding_error = _v4_global(_v4_scope, 'str')(error)
    universe_bindings: dict[str, StageUniverseBinding] = {}
    if a_candidate_missing:
        universe_bindings["A_SHARE"] = _v4_global(_v4_scope, 'StageUniverseBinding').unavailable(
            market="A_SHARE", trade_date=trade_date, reason=candidate_error
        )
    else:
        universe_bindings["A_SHARE"] = _v4_global(_v4_scope, 'StageUniverseBinding').ready(
            market="A_SHARE",
            trade_date=trade_date,
            role="A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
            codes=_v4_global(_v4_scope, 'tuple')(candidate.codes),
            source_run_id=candidate.run_id,
            sha256=candidate.current_sha256,
            evidence=_v4_global(_v4_scope, 'tuple')(candidate.source_evidence),
        )
    if hk_binding is not None:
        universe_bindings["HK_CONNECT"] = hk_binding
    candidate_sha_by_market: dict[str, str | None] = {
        market: None for market in markets
    }
    candidate_run_id_by_market: dict[str, str | None] = {
        market: None for market in markets
    }
    if self.config.injected_test_mode:
        for market in markets:
            candidate_sha_by_market[market] = candidate.current_sha256
            candidate_run_id_by_market[market] = candidate.run_id
    else:
        if "A_SHARE" in markets and not a_candidate_missing:
            candidate_sha_by_market["A_SHARE"] = candidate.current_sha256
            candidate_run_id_by_market["A_SHARE"] = candidate.run_id
        if "HK_CONNECT" in markets and hk_binding is not None:
            candidate_sha_by_market["HK_CONNECT"] = hk_binding.sha256
            candidate_run_id_by_market["HK_CONNECT"] = hk_binding.source_run_id
    write_performed = False
    exact_input_errors: dict[str, str] = {}
    sources: dict[str, SourceResult] = {}
    try:
        self._validate_hk_auction_root_binding(stage_id)
        existing_state, existing = self._existing_slot(
            trade_date,
            stage_id,
            markets,
            candidate_sha_by_market,
        )
        if existing_state == "VERIFIED" and existing is not None:
            # An immutable slot may be reused only with its same fixed
            # HK authority. A damaged/replaced D1 input must not be hidden
            # behind the A pointer's unchanged idempotency identity.
            if "HK_CONNECT" in markets and not self.config.injected_test_mode:
                try:
                    if self.config.hk_d1_root is None:
                        raise _v4_global(_v4_scope, 'RunnerError')("production HK D1 root is required")
                    current_hk = _v4_global(_v4_scope, '_build_hk_stage_binding')(
                        self.config.hk_d1_root,
                        trade_date,
                        preselection_source_root=self.config.preselection_source_root,
                    )
                    raw_hk = existing["raw_verified"].get("HK_CONNECT") or {}
                    if not _v4_global(_v4_scope, '_evidence_has')(raw_hk.get("source_evidence", ()), "hk_d1_sha256", current_hk.sha256):
                        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 source SHA differs from verified slot")
                except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                    published = _v4_global(_v4_scope, 'dict')(existing["selections"])
                    published["HK_CONNECT"] = {"status": "CANNOT_CONFIRM", "selection_status": "CANNOT_CONFIRM",
                        "selected_rows": 0, "cannot_confirm": [_v4_global(_v4_scope, 'str')(error)], "write_performed": False}
                    return self._write_receipt({"status": "PARTIAL_WITH_ROWS" if "A_SHARE" in published else "CANNOT_CONFIRM",
                        "trade_date": trade_date, "stage_id": stage_id, "due_status": decision.status,
                        "candidate_current_sha256": candidate.current_sha256, "markets": published,
                        "error": _v4_global(_v4_scope, 'str')(error), "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING",
                        "write_performed": False}, trade_date, stage_id)
            return self._write_receipt({"status": "NOOP_ALREADY_VERIFIED", "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id, "bundle_id": (existing["raw"].get("receipt") or {}).get("bundle_id"), "markets": {market: envelope for market, envelope in existing["selections"].items()}, "write_performed": False}, trade_date, stage_id)
        existing_raw_verified: dict[str, Mapping[str, Any]] = _v4_global(_v4_scope, 'dict')((existing or {}).get("raw_verified") or {})
        existing_selections: dict[str, Mapping[str, Any]] = _v4_global(_v4_scope, 'dict')((existing or {}).get("selections") or {})
        exact_evidence_by_market: dict[str, tuple[str, ...]] = {}
        exact_input_errors: dict[str, str] = {}
        if a_candidate_missing and "A_SHARE" in markets:
            exact_input_errors["A_SHARE"] = candidate_error
            exact_evidence_by_market["A_SHARE"] = (
                f"a_share_universe_binding_error={candidate_error}",
            )
        if hk_binding_error and "HK_CONNECT" in markets:
            exact_input_errors["HK_CONNECT"] = hk_binding_error
            exact_evidence_by_market["HK_CONNECT"] = (
                f"hk_d1_universe_binding_error={hk_binding_error}",
            )
        for market in markets:
            if market == "A_SHARE" and market in exact_input_errors:
                continue
            try:
                exact_evidence_by_market[market] = _v4_global(_v4_scope, '_validate_exact_selection_inputs')(
                    self.config,
                    trade_date,
                    stage_id,
                    market=market,
                    hk_binding=universe_bindings.get(market),
                )
            except _v4_global(_v4_scope, 'RunnerError') as error:
                # Exact-input failures are lane-local. Preserve the
                # reason for that market while allowing the other lane to
                # continue through collection and publication.
                exact_evidence_by_market[market] = ()
                exact_input_errors[market] = _v4_global(_v4_scope, 'str')(error)
        exact_evidence = _v4_global(_v4_scope, 'tuple')(
            item
            for market in markets
            for item in exact_evidence_by_market.get(market, ())
        )
        exact_evidence = _v4_global(_v4_scope, 'tuple')(
            _v4_global(_v4_scope, 'dict').fromkeys(
                (
                    *exact_evidence,
                    *(f"{market.lower()}_exact_input_error={error}" for market, error in exact_input_errors.items()),
                )
            )
        )
        if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
            return self._write_receipt({"status": decision.status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "write_performed": False}, trade_date, stage_id)
        if self.config.injected_test_mode:
            collectors = self.collectors
        else:
            if self.config.shared_data_root is None or self.config.python_path is None:
                raise _v4_global(_v4_scope, 'RunnerError')("production shared_data_root and python_path are required")
            from stage_center.live_collectors import production_collectors, production_selection_builders
            if self.collectors:
                collectors = self.collectors
            elif stage_id == "STAGE_1545_1555":
                from stage_center.hk_stage8 import production_natural_collectors, should_use_natural_route

                if should_use_natural_route(
                    trade_date,
                    historical_backfill=historical_backfill,
                ):
                    collectors = production_natural_collectors(
                        snapshot_root=self.config.raw_root,
                    )
                else:
                    collectors = production_collectors(
                        plan=_v4_global(_v4_scope, 'build_plan')(
                            self.config.candidate_acquisition_root,
                            trade_date,
                            stage_id,
                            candidate=candidate,
                            universe_bindings=universe_bindings,
                            historical_backfill=historical_backfill,
                        ),
                        python_path=self.config.python_path,
                        shared_root=self.config.shared_data_root,
                        a_auction_root=self.config.a_auction_root,
                        hk_auction_root=self.config.hk_auction_root,
                        hk_stage_replay_root=self.config.hk_stage_replay_root,
                    )
            else:
                collectors = production_collectors(
                    plan=_v4_global(_v4_scope, 'build_plan')(
                        self.config.candidate_acquisition_root,
                        trade_date,
                        stage_id,
                        candidate=candidate,
                        universe_bindings=universe_bindings,
                        historical_backfill=historical_backfill,
                    ),
                    python_path=self.config.python_path,
                    shared_root=self.config.shared_data_root,
                    a_auction_root=self.config.a_auction_root,
                    hk_auction_root=self.config.hk_auction_root,
                    hk_stage_replay_root=self.config.hk_stage_replay_root,
                )
            if self.config.selection_builders is None:
                builders = production_selection_builders(stage_id)
            else:
                builders = self.config.selection_builders
        missing_raw_markets = _v4_global(_v4_scope, 'tuple')(market for market in markets if market not in existing_raw_verified)
        if not _v4_global(_v4_scope, 'set')(missing_raw_markets).issubset(_v4_global(_v4_scope, 'set')(collectors)):
            raise _v4_global(_v4_scope, 'RunnerError')(f"collectors are missing required markets {missing_raw_markets!r}")
        builders = self.config.selection_builders
        if builders is None and not self.config.injected_test_mode:
            from stage_center.live_collectors import production_selection_builders
            builders = production_selection_builders(stage_id)
        if builders is None:
            raise _v4_global(_v4_scope, 'RunnerError')("production selection builders are not installed")
        missing_builders = _v4_global(_v4_scope, 'tuple')(market for market in markets if market not in builders)
        if missing_builders:
            raise _v4_global(_v4_scope, 'RunnerError')(
                f"selection builders are missing required markets {missing_builders!r}"
            )
        # The stage calendar decides which lanes can run today. Keep the
        # required-market check strict, then discard builders for closed
        # markets so an HK-only observation does not fail on A's builder.
        builders = {market: builders[market] for market in markets}
        selection_membership: dict[str, set[str] | None] = {market: None for market in markets}
        if not self.config.injected_test_mode:
            if "HK_CONNECT" in markets and "HK_CONNECT" not in exact_input_errors:
                try:
                    hk_d1_binding = universe_bindings.get("HK_CONNECT")
                    if hk_d1_binding is None:
                        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 binding is unavailable after exact-input validation")
                    _v4_global(_v4_scope, '_validated_hk_binding_evidence')(hk_d1_binding, trade_date)
                    hk_d1_codes = _v4_global(_v4_scope, 'set')(hk_d1_binding.codes)
                    # Acquisition and selection share the same exact D-1
                    # Top100 binding already validated above. This binding is required for every HK stage,
                    # not just Stage8; no full-market collection is invoked.
                    selection_membership["HK_CONNECT"] = hk_d1_codes
                    # Minute stages use the frozen D-1 Top100.  The 09:25
                    # stage additionally binds the exact 09:20 second-filter
                    # universe; no current/previous-stage rows can fill it.
                    if stage_id == "STAGE_0925":
                        assert self.config.hk_second_filter_root is not None
                        second_codes, _second_sha = _v4_global(_v4_scope, '_hk_second_filter_codes')(self.config.hk_second_filter_root, trade_date)
                        selection_membership["HK_CONNECT"] = hk_d1_codes & second_codes
                except _v4_global(_v4_scope, 'RunnerError') as error:
                    exact_input_errors["HK_CONNECT"] = _v4_global(_v4_scope, 'str')(error)
        plan = _v4_global(_v4_scope, 'build_plan')(
            self.config.candidate_acquisition_root,
            trade_date,
            stage_id,
            candidate=candidate,
            universe_bindings=universe_bindings,
            historical_backfill=historical_backfill,
        )
        sources: dict[str, SourceResult] = {}
        selection_sources: dict[str, SourceResult] = {}
        for market in markets:
            if market in exact_input_errors:
                error = exact_input_errors[market]
                result = _v4_global(_v4_scope, 'SourceResult')(
                    market,
                    "CANNOT_CONFIRM",
                    cannot_confirm=(error,),
                    requested_rows=_v4_global(_v4_scope, 'len')(plan.codes_for(market)) or None,
                    source_evidence=(f"exact_input_error={error}",),
                )
            elif market in existing_raw_verified:
                result = _v4_global(_v4_scope, '_read_verified_raw_source')(self.config.raw_root, existing_raw_verified[market])
            else:
                try:
                    _v4_global(_v4_scope, '_deadline').checkpoint("COLLECTOR_START", market=market, stage_id=stage_id, trade_date=trade_date)
                    result = collectors[market](plan, market)
                    _v4_global(_v4_scope, '_deadline').checkpoint("COLLECTOR_END", market=market, stage_id=stage_id, trade_date=trade_date,
                                         source_observation=_v4_global(_v4_scope, '_deadline').source_observation(result))
                    if not _v4_global(_v4_scope, 'isinstance')(result, _v4_global(_v4_scope, 'SourceResult')):
                        raise _v4_global(_v4_scope, 'RunnerError')(f"collector {market} did not return SourceResult")
                except _v4_global(_v4_scope, '_deadline').DeadlineExceeded:
                    raise
                except _v4_global(_v4_scope, 'Exception') as error:
                    result = _v4_global(_v4_scope, 'SourceResult')(market, "CANNOT_CONFIRM", cannot_confirm=(f"COLLECTOR_ERROR:{_v4_global(_v4_scope, 'type')(error).__name__}",), requested_rows=_v4_global(_v4_scope, 'len')(plan.codes_for(market)) or None, source_evidence=(f"collector_error={_v4_global(_v4_scope, 'type')(error).__name__}",))
            if result.rows and result.requested_rows is not None and _v4_global(_v4_scope, 'len')(result.rows) < result.requested_rows and result.status == "READY":
                result = _v4_global(_v4_scope, 'replace')(result, status="PARTIAL_WITH_ROWS")
            elif result.rows and result.missing_symbols and result.status == "READY":
                result = _v4_global(_v4_scope, 'replace')(result, status="PARTIAL_WITH_ROWS")
            # Stage8 selection recovery must re-read the exact replay
            # provider, never rebuild LIVE lanes from a current Futu
            # snapshot.  Raw publication intentionally excludes lane
            # metadata, so a missing selection cannot be reconstructed
            # from the raw CSV alone.
            if (
                market == "HK_CONNECT"
                and stage_id == "STAGE_1545_1555"
                and market in existing_raw_verified
                and market not in existing_selections
                and market not in exact_input_errors
                and not self.config.injected_test_mode
            ):
                if self.config.hk_stage_replay_root is None:
                    raise _v4_global(_v4_scope, 'RunnerError')("HK Stage8 selection recovery requires explicit replay root")
                _v4_global(_v4_scope, '_deadline').checkpoint("COLLECTOR_START", market=market, stage_id=stage_id, trade_date=trade_date)
                result = collectors[market](plan, market)
                _v4_global(_v4_scope, '_deadline').checkpoint("COLLECTOR_END", market=market, stage_id=stage_id, trade_date=trade_date,
                                     source_observation=_v4_global(_v4_scope, '_deadline').source_observation(result))
            # Selection-only recovery must re-run the same read-only V3
            # active trigger when raw is already complete.  Raw bars are
            # never recollected or rewritten, and the active probe's
            # canonical SHA must match the evidence bound to that raw run.
            if (
                market == "HK_CONNECT"
                and stage_id != "STAGE_1545_1555"
                and stage_id != "STAGE_0925"
                and market in existing_raw_verified
                and market not in existing_selections
                and market not in exact_input_errors
                and not self.config.injected_test_mode
            ):
                previous_sha = _v4_global(_v4_scope, '_evidence_value')(result.source_evidence, "active_snapshot_sha256")
                previous_codes_sha = _v4_global(_v4_scope, '_evidence_value')(result.source_evidence, "active_snapshot_codes_sha256")
                expected_cutoff = _v4_global(_v4_scope, 'next')(
                    stage.cutoff for stage in _v4_global(_v4_scope, 'EIGHT_STAGES') if stage.stage_id == stage_id
                )
                previous_status = _v4_global(_v4_scope, '_evidence_value')(
                    result.source_evidence, "active_snapshot_status"
                )
                previous_trade_date = _v4_global(_v4_scope, '_evidence_value')(
                    result.source_evidence, "active_snapshot_trade_date"
                )
                previous_cutoff = _v4_global(_v4_scope, '_evidence_value')(
                    result.source_evidence, "active_snapshot_cutoff"
                )
                previous_temporal = _v4_global(_v4_scope, '_evidence_value')(
                    result.source_evidence, "active_snapshot_temporal_cutoff_safe"
                )
                reuse_degraded_observation = (
                    result.status == "PARTIAL_WITH_ROWS"
                    and _v4_global(_v4_scope, 'bool')(result.rows)
                    and previous_temporal == "false"
                    and _v4_global(_v4_scope, '_evidence_value')(
                        result.source_evidence,
                        "active_snapshot_degraded_to_pytdx_observation",
                    )
                    == "true"
                )
                recovery_error: str | None = None
                if not _v4_global(_v4_scope, 'all')(
                    (
                        previous_sha,
                        previous_codes_sha,
                        previous_status,
                        previous_trade_date,
                        previous_cutoff,
                    )
                ):
                    recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_MISSING"
                elif not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-f]{64}", previous_sha) or not _v4_global(_v4_scope, 're').fullmatch(
                    r"[0-9a-f]{64}", previous_codes_sha
                ):
                    recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_INVALID"
                elif (
                    previous_status != "FUTU_HKCONNECT_FULL_SCAN"
                    or previous_trade_date != trade_date
                    or previous_cutoff != expected_cutoff
                ):
                    recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_INVALID"
                elif reuse_degraded_observation:
                    # The raw run is already exact-date/exact-stage and
                    # carries the historical PyTDX observation marker.  In
                    # this narrow mode the old runner deliberately reused
                    # those immutable rows instead of asking for a new
                    # current snapshot.  The builder will keep this lane
                    # PARTIAL/WATCH_ONLY and retain the evidence markers.
                    exact_evidence_by_market[market] = _v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys(
                            (
                                *exact_evidence_by_market.get(market, ()),
                                "hk_active_selection_recovery=DEGRADED_OBSERVATION_REUSE",
                            )
                        )
                    )
                elif previous_temporal != "true":
                    # An unsafe or unproven historical cutoff cannot be
                    # repaired by reading a new active snapshot. Keep the
                    # HK lane unconfirmed instead of relabelling current
                    # observations as the completed historical stage.
                    recovery_error = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"
                else:
                    try:
                        if not plan.codes_for("HK_CONNECT") or self.config.shared_data_root is None or self.config.python_path is None:
                            raise _v4_global(_v4_scope, 'RunnerError')("HK active-lane recovery requires explicit fixed D1 bridge roots")
                        from stage_center.live_collectors import refresh_hk_active_lanes
                        refreshed = refresh_hk_active_lanes(
                            result,
                            codes=plan.codes_for("HK_CONNECT"),
                            python_path=self.config.python_path,
                            shared_root=self.config.shared_data_root,
                            trade_date=trade_date,
                            stage_id=stage_id,
                            cutoff_at=expected_cutoff,
                        )
                        current_sha = _v4_global(_v4_scope, '_evidence_value')(refreshed.source_evidence, "active_snapshot_sha256")
                        current_codes_sha = _v4_global(_v4_scope, '_evidence_value')(refreshed.source_evidence, "active_snapshot_codes_sha256")
                        if not previous_sha or previous_sha != current_sha or not previous_codes_sha or previous_codes_sha != current_codes_sha:
                            recovery_error = "HK_ACTIVE_SNAPSHOT_EVIDENCE_CHANGED"
                        elif "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in refreshed.cannot_confirm:
                            recovery_error = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"
                        elif "HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE" in refreshed.cannot_confirm:
                            recovery_error = "HK_ACTIVE_SNAPSHOT_UNAVAILABLE"
                        else:
                            result = refreshed
                    except _v4_global(_v4_scope, 'Exception') as error:
                        recovery_error = f"HK_ACTIVE_SELECTION_RECOVERY_FAILED:{_v4_global(_v4_scope, 'type')(error).__name__}"
                if recovery_error:
                    exact_input_errors[market] = recovery_error
                    exact_evidence_by_market[market] = _v4_global(_v4_scope, 'tuple')(
                        _v4_global(_v4_scope, 'dict').fromkeys(
                            (
                                *exact_evidence_by_market.get(market, ()),
                                f"hk_active_selection_recovery_error={recovery_error}",
                            )
                        )
                    )
            sources[market] = _v4_global(_v4_scope, '_with_candidate_evidence')(
                result,
                candidate,
                (
                    *exact_evidence_by_market.get(market, ()),
                    *((f"exact_input_error={exact_input_errors[market]}",) if market in exact_input_errors else ()),
                    f"due_status={decision.status}",
                ),
                candidate_sha=candidate_sha_by_market.get(market),
                candidate_run_id=candidate_run_id_by_market.get(market),
            )
            if market == "A_SHARE" and not self.config.injected_test_mode and market not in exact_input_errors:
                selected_source = sources[market]
                if self.config.v3_formal_root is not None:
                    try:
                        selected_source = _v4_global(_v4_scope, '_attach_a_authority')(selected_source, formal_root=self.config.v3_formal_root, trade_date=trade_date)
                    except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                        selected_source = _v4_global(_v4_scope, 'replace')(selected_source, source_evidence=(*selected_source.source_evidence, f"a_formal_overlay_unavailable={error}"))
                if self.config.a_research_panel_receipt_root is not None:
                    try:
                        selected_source = _v4_global(_v4_scope, '_attach_a_name_authority')(
                            selected_source, candidate_root=self.config.candidate_acquisition_root,
                            research_panel_receipt_root=self.config.a_research_panel_receipt_root, trade_date=trade_date)
                    except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                        selected_source = _v4_global(_v4_scope, 'replace')(selected_source, source_evidence=(*selected_source.source_evidence, f"a_name_overlay_unavailable={error}"))
                selection_sources[market] = selected_source
            if (
                market == "HK_CONNECT"
                and not self.config.injected_test_mode
                and self.config.hk_d1_root is not None
                and market not in exact_input_errors
            ):
                try:
                    selection_sources[market] = _v4_global(_v4_scope, '_attach_hk_authority')(
                        sources[market],
                        d1_root=self.config.hk_d1_root,
                        second_root=(
                            self.config.hk_second_filter_root
                            if stage_id == "STAGE_0925" or stage_id in _v4_global(_v4_scope, 'HK_CONTINUATION_STAGES')
                            else None
                        ),
                        trade_date=trade_date,
                        stage_id=stage_id,
                        preselection_source_root=self.config.preselection_source_root,
                        hk_binding=universe_bindings.get("HK_CONNECT"),
                    )
                except _v4_global(_v4_scope, 'RunnerError') as error:
                    exact_input_errors[market] = _v4_global(_v4_scope, 'str')(error)
            if market in exact_input_errors and market not in selection_sources:
                sources[market] = _v4_global(_v4_scope, 'replace')(
                    sources[market],
                    status="CANNOT_CONFIRM",
                    rows=(),
                    cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*sources[market].cannot_confirm, exact_input_errors[market]))),
                )
            selection_sources[market] = _v4_global(_v4_scope, '_selection_source')(
                selection_sources.get(market, sources[market]),
                market=market,
                membership=selection_membership.get(market),
            )
        # Re-read the explicit pointer before any publication: a changed
        # candidate cannot produce a selection artifact for the old input.
        if not a_candidate_missing:
            _v4_global(_v4_scope, 'read_candidate_input')(
                self.config.candidate_acquisition_root,
                trade_date,
                expected_current_sha256=candidate.current_sha256,
            )
        if (
            not self.config.injected_test_mode
            and "HK_CONNECT" in universe_bindings
            and "HK_CONNECT" not in exact_input_errors
        ):
            binding = universe_bindings["HK_CONNECT"]
            if binding.status == "READY" and self.config.hk_d1_root is not None:
                try:
                    fresh = _v4_global(_v4_scope, '_build_hk_stage_binding')(
                        self.config.hk_d1_root,
                        trade_date,
                        preselection_source_root=self.config.preselection_source_root,
                    )
                    if fresh.sha256 != binding.sha256 or fresh.codes != binding.codes:
                        raise _v4_global(_v4_scope, 'RunnerError')("HK D1 source SHA changed before publication")
                except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
                    # Reject this lane's old acquisition, not a valid A
                    # aggregate. No HK raw/selection/latest is published.
                    exact_input_errors["HK_CONNECT"] = _v4_global(_v4_scope, 'str')(error)
                    sources["HK_CONNECT"] = _v4_global(_v4_scope, 'replace')(
                        sources["HK_CONNECT"], status="CANNOT_CONFIRM", rows=(),
                        cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*sources["HK_CONNECT"].cannot_confirm, _v4_global(_v4_scope, 'str')(error)))),
                    )
                    selection_sources["HK_CONNECT"] = sources["HK_CONNECT"]
        raw_store = _v4_global(_v4_scope, 'RawStore')(self.config.raw_root)
        raw_markets: dict[str, dict[str, Any]] = {}
        stage_spec = _v4_global(_v4_scope, 'next')(stage for stage in _v4_global(_v4_scope, 'EIGHT_STAGES') if stage.stage_id == stage_id)
        # Validate every market's raw projection before touching the
        # store.  A sequential publish must not leave A_SHARE latest
        # behind when HK_CONNECT later violates the 19-field contract.
        projected_rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for market in markets:
            source = sources[market]
            if source.status == "CANNOT_CONFIRM" and not source.rows:
                continue
            projected_rows[market] = _v4_global(_v4_scope, '_project_raw_rows')(
                source.rows,
                trade_date=trade_date,
                stage_id=stage_id,
                market=market,
            )
        for market in markets:
            source = sources[market]
            # A zero-row CANNOT_CONFIRM is a receipt-only outcome.  It
            # must never create a raw latest pointer or selection latest
            # entry that looks like a materialized stage.
            if source.status == "CANNOT_CONFIRM" and not source.rows:
                continue
            window = stage_spec.hk_window if stage_id == "STAGE_0925" and market == "HK_CONNECT" else stage_spec.window
            cutoff_at = "09:20:05" if stage_id == "STAGE_0925" and market == "HK_CONNECT" else stage_spec.cutoff
            if market in existing_raw_verified:
                raw_markets[market] = _v4_global(_v4_scope, 'dict')(existing_raw_verified[market])
                continue
            _v4_global(_v4_scope, '_deadline').begin_write("RAW_PUBLISH", market=market, stage_id=stage_id)
            raw_markets[market] = _v4_global(_v4_scope, 'publish_raw_artifact')(
                self.config.raw_root,
                trade_date=trade_date,
                stage_id=stage_id,
                market=market,
                source_id=source.source_id,
                source_status=source.status,
                rows=projected_rows[market],
                cannot_confirm=source.cannot_confirm,
                source_evidence=source.source_evidence,
                requested_rows=source.requested_rows,
                missing_symbols=source.missing_symbols,
                window=window,
                cutoff_at=cutoff_at,
            )
            write_performed = True
            _v4_global(_v4_scope, '_deadline').end_write("RAW_PUBLISH", market=market, artifact_sha256=raw_markets[market].get("artifact_sha256"))
        raw_bundle: dict[str, Any] = {"markets": raw_markets}
        if not raw_markets:
            raise _v4_global(_v4_scope, 'RunnerError')("all market collectors returned zero-row CANNOT_CONFIRM")
        if _v4_global(_v4_scope, 'set')(raw_markets) == _v4_global(_v4_scope, 'set')(markets):
            try:
                _v4_global(_v4_scope, '_deadline').begin_write("BUNDLE_PUBLISH", stage_id=stage_id)
                raw_bundle.update(raw_store.publish_bundle(trade_date=trade_date, stage_id=stage_id, status=("READY" if _v4_global(_v4_scope, 'all')(item["status"] == "READY" for item in raw_markets.values()) else "PARTIAL_WITH_ROWS"), markets=raw_markets))
                _v4_global(_v4_scope, '_deadline').end_write("BUNDLE_PUBLISH", stage_id=stage_id)
            except _v4_global(_v4_scope, 'RawStoreError') as error:
                # An immutable raw bundle may have been left absent after
                # a prior selection-only failure.  Re-read an identical
                # bundle if the store reports a conflict; any differing
                # market identity remains fail-closed.
                if "bundle slot conflict" not in _v4_global(_v4_scope, 'str')(error):
                    raise
                raw_bundle.update(raw_store.read_verified_bundle(trade_date, stage_id))
        published: dict[str, Any] = {}
        selection_store = _v4_global(_v4_scope, 'SelectionStore')(self.config.selection_root)
        for market in markets:
            if market not in raw_markets:
                published[market] = {
                    "market": market,
                    "selection_status": "CANNOT_CONFIRM",
                    "status": "CANNOT_CONFIRM",
                    "selected_rows": 0,
                    "source_status": sources[market].status,
                    "cannot_confirm": _v4_global(_v4_scope, 'list')(sources[market].cannot_confirm),
                    "write_performed": False,
                }
                continue
            if market in existing_selections:
                published[market] = _v4_global(_v4_scope, 'dict')(existing_selections[market])
                continue
            builder_raw = _v4_global(_v4_scope, 'dict')(raw_bundle["markets"][market])
            # These roots have distinct owners and must remain separate in
            # the exact-date selection context.
            _v4_global(_v4_scope, '_attach_stage_research_roots')(
                builder_raw,
                self.config,
                stage_id,
                market=market,
            )
            envelope = _v4_global(_v4_scope, 'dict')(builders[market](selection_sources[market], plan, builder_raw))
            envelope.setdefault("source_evidence", [])
            envelope["source_evidence"] = _v4_global(_v4_scope, 'list')(
                _v4_global(_v4_scope, 'dict').fromkeys(
                    (
                        *envelope["source_evidence"],
                        *(
                            (
                                f"candidate_current_sha256={candidate_sha_by_market[market]}",
                                f"candidate_run_id={candidate_run_id_by_market[market]}",
                            )
                            if candidate_sha_by_market.get(market) is not None
                            else ()
                        ),
                        *exact_evidence_by_market.get(market, ()),
                        *((f"exact_input_error={exact_input_errors[market]}",) if market in exact_input_errors else ()),
                        f"due_status={decision.status}",
                    )
                )
            )
            envelope["raw_artifact_sha256"] = raw_bundle["markets"][market]["artifact_sha256"]
            _v4_global(_v4_scope, '_deadline').begin_write("SELECTION_PUBLISH", market=market, stage_id=stage_id)
            published[market] = selection_store.publish(envelope, market=market)
            _v4_global(_v4_scope, '_deadline').end_write("SELECTION_PUBLISH", market=market, run_id=published[market].get("run_id"))
            write_performed = True
        statuses = {_v4_global(_v4_scope, 'str')(item.get("selection_status")) for item in published.values()}
        status = "READY" if statuses == {"READY"} and _v4_global(_v4_scope, 'len')(published) == _v4_global(_v4_scope, 'len')(markets) else "READY_EMPTY" if statuses == {"READY_EMPTY"} and _v4_global(_v4_scope, 'len')(published) == _v4_global(_v4_scope, 'len')(markets) else "PARTIAL_WITH_ROWS" if statuses and ("PARTIAL_WITH_ROWS" in statuses or _v4_global(_v4_scope, 'len')(published) < _v4_global(_v4_scope, 'len')(markets) or "READY" in statuses) else "CANNOT_CONFIRM"
        source_evidence = [f"candidate_current_sha256={candidate.current_sha256}", f"candidate_run_id={candidate.run_id}", *exact_evidence]
        if decision.status in {"LATE_CATCHUP_REPLAY", "HISTORICAL_BACKFILL"}:
            source_evidence.append(decision.status)
        return self._write_receipt({"status": status, "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id, "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id, "bundle_id": raw_bundle.get("bundle_id"), "markets": published, "source_evidence": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(source_evidence)), "write_performed": True}, trade_date, stage_id)
    except (_v4_global(_v4_scope, 'RunnerError'), _v4_global(_v4_scope, 'RawStoreError'), _v4_global(_v4_scope, 'SelectionError'), _v4_global(_v4_scope, 'CandidateInputError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        lane_failures = {}
        for market in markets:
            source = sources.get(market)
            reasons = ([exact_input_errors[market]] if market in exact_input_errors
                       else _v4_global(_v4_scope, 'list')(source.cannot_confirm) if source else [_v4_global(_v4_scope, 'str')(error)])
            lane_failures[market] = {
                "status": source.status if source else "CANNOT_CONFIRM",
                "cannot_confirm": reasons, "first_error": reasons[0] if reasons else _v4_global(_v4_scope, 'str')(error),
                "observed_rows": _v4_global(_v4_scope, 'len')(source.rows) if source else 0,
                "requested_rows": source.requested_rows if source else None,
                "source_evidence": _v4_global(_v4_scope, 'list')(source.source_evidence) if source else [],
            }
        return self._write_receipt({
            "status": "PARTIAL_COMMIT_RETRY_REQUIRED" if write_performed else "CANNOT_CONFIRM",
            "due_status": decision.status, "trade_date": trade_date, "stage_id": stage_id,
            "candidate_current_sha256": candidate.current_sha256, "error": _v4_global(_v4_scope, 'str')(error),
            "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING" if exact_input_errors else "COLLECTION_OR_PUBLICATION",
            "markets": lane_failures, "write_performed": write_performed,
            **_v4_global(_v4_scope, '_deadline').failure_fields(error),
        }, trade_date, stage_id)
