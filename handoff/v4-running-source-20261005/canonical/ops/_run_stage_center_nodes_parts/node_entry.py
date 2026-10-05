"""ops.run_stage_center_nodes: node_entry (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __calendar_gate_body(_v4_scope, /, trade_date, *, markets):
    """Resolve the pure calendar contract before any materializer/network call."""

    states = _v4_global(_v4_scope, 'resolve_market_states')(trade_date)
    serialized = {key: state.value for key, state in states.items()}
    if _v4_global(_v4_scope, 'any')(state is _v4_global(_v4_scope, 'TradingDayState').UNKNOWN for state in states.values()):
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "calendar": serialized,
            "error": "CALENDAR_UNKNOWN",
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    relevant = _v4_global(_v4_scope, 'tuple')(
        states["a_share"] if market == "A_SHARE" else states["hk_securities"]
        for market in markets
    )
    if relevant and _v4_global(_v4_scope, 'all')(state is _v4_global(_v4_scope, 'TradingDayState').NON_TRADING_DAY for state in relevant):
        return {
            "status": "SKIPPED_NON_TRADING_DAY",
            "trade_date": trade_date,
            "calendar": serialized,
            "markets": _v4_global(_v4_scope, 'list')(markets),
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    return {
        "status": "ELIGIBLE",
        "trade_date": trade_date,
        "calendar": serialized,
        "markets": _v4_global(_v4_scope, 'list')(markets),
        **_v4_global(_v4_scope, '_safe_flags')(),
    }


def __read_receipt_body(_v4_scope, /, config, trade_date, stage_id):
    path = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id)
    try:
        value = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'FileNotFoundError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')):
        return None
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'dict')):
        return None
    if value.get("trade_date") != trade_date or value.get("stage_id") != stage_id:
        return None
    pending = _v4_global(_v4_scope, '_deadline').pending_receipt_marker(path)
    if pending.exists() or pending.is_symlink():
        value = _v4_global(_v4_scope, 'dict')(value)
        value["deadline_original_status"] = value.get("status")
        value.update(
            status="CANNOT_CONFIRM",
            node_outcome="TRANSIENT",
            first_failed_layer="END_TO_END_DEADLINE",
            deadline_status="CANNOT_CONFIRM",
            deadline_receipt_pending=True,
            deadline_receipt_pending_marker_path=_v4_global(_v4_scope, 'str')(pending),
        )
    return value


def __retry_is_due_body(_v4_scope, /, receipt, evaluated_at, *, retry_backoff_seconds):
    if not receipt:
        return True
    retry_after = receipt.get("retry_after")
    if _v4_global(_v4_scope, 'isinstance')(retry_after, _v4_global(_v4_scope, 'str')) and retry_after:
        try:
            retry_time = _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, 'datetime').fromisoformat(retry_after))
        except _v4_global(_v4_scope, 'ValueError'):
            retry_time = None
        if retry_time is not None:
            return evaluated_at >= retry_time
    attempted_at = receipt.get("attempted_at")
    if _v4_global(_v4_scope, 'isinstance')(attempted_at, _v4_global(_v4_scope, 'str')) and attempted_at:
        try:
            attempt_time = _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, 'datetime').fromisoformat(attempted_at))
        except _v4_global(_v4_scope, 'ValueError'):
            attempt_time = None
        if attempt_time is not None:
            return evaluated_at >= attempt_time + _v4_global(_v4_scope, 'timedelta')(seconds=retry_backoff_seconds)
    return False


def __candidate_current_is_verified_body(_v4_scope, /, config, trade_date):
    """Read the exact current pointer without creating a second producer."""

    from stage_center.candidate_input import CandidateInputError, read_candidate_input

    try:
        candidate = read_candidate_input(
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["candidate_acquisition_root"])), trade_date
        )
    except (CandidateInputError, _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')):
        return None
    return {
        "status": "PREP_ALREADY_VERIFIED",
        "trade_date": trade_date,
        "run_id": candidate.run_id,
        "current_sha256": candidate.current_sha256,
        "row_count": _v4_global(_v4_scope, 'len')(candidate.codes),
        "current_relative": candidate.current_relative,
        "source_evidence": _v4_global(_v4_scope, 'list')(candidate.source_evidence),
        "idempotent": True,
        **_v4_global(_v4_scope, '_safe_flags')(),
    }


def _materialize_candidate_body(_v4_scope, /, config, trade_date, *, materializer):
    """Prepare one exact-date canonical ``a_all_pool_rows`` current pointer."""

    gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=("A_SHARE",))
    if gate["status"] != "ELIGIBLE":
        return {**gate, "node_id": _v4_global(_v4_scope, 'PREP_NODE_ID')}
    # Explicit source bindings must pass the materializer and its physical
    # revalidation. A prior target pointer alone does not verify a new source.
    existing = None
    if "preselection_source_root" not in config:
        existing = _v4_global(_v4_scope, '_candidate_current_is_verified')(config, trade_date)
    if existing is not None:
        return {**existing, "node_id": _v4_global(_v4_scope, 'PREP_NODE_ID')}

    # Target owns the strict current; source owns the exact-date physical
    # pool trios. Never infer a source from whichever directory has rows.
    if materializer is None:
        from ops.materialize_stage_acquisition_universe import (
            materialize_stage_acquisition_universe,
        )

        materializer = materialize_stage_acquisition_universe
    root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["candidate_acquisition_root"])).expanduser()
    if "preselection_source_root" not in config:
        # Preserve the legacy same-root normalization. With an explicit source,
        # leave the target lexical so resolve_source_root can reject symlinks
        # before any canonical path resolution.
        root = root.resolve()
    try:
        if "preselection_source_root" in config:
            from infrastructure.stage_source_roots import resolve_source_root
            if config["preselection_source_root"] is None:
                raise ValueError("explicit preselection source root must not be null")
            source = resolve_source_root(root, config["preselection_source_root"])
            output = materializer(root, trade_date, preselection_source_root=source)
        else:
            output = materializer(root, trade_date)
        if not _v4_global(_v4_scope, 'isinstance')(output, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("canonical candidate materializer returned a non-object")
        if output.get("trade_date") not in (None, trade_date):
            raise _v4_global(_v4_scope, 'ValueError')("canonical candidate materializer trade_date mismatch")
        if output.get("status") not in {"READY", "NOOP_ALREADY_VERIFIED"}:
            raise _v4_global(_v4_scope, 'ValueError')(
                f"canonical candidate materializer status is {output.get('status')!r}"
            )
        result = {"node_id": _v4_global(_v4_scope, 'PREP_NODE_ID'), **_v4_global(_v4_scope, 'dict')(output), **_v4_global(_v4_scope, '_safe_flags')()}
        result.setdefault("status", "PREP_READY")
        return result
    except (_v4_global(_v4_scope, 'ImportError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'RuntimeError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        return {
            "status": "CANNOT_CONFIRM",
            "node_id": _v4_global(_v4_scope, 'PREP_NODE_ID'),
            "trade_date": trade_date,
            "error": _v4_global(_v4_scope, 'str')(error),
            "blocked_layer": "A_SHARE_CANONICAL_A_ALL_POOL_ROWS",
            "core_input": "BLOCKED",
            **_v4_global(_v4_scope, '_safe_flags')(),
        }


def __build_runner_body(_v4_scope, /, config):
    """Build production runner with fixed HK D-1 authority and no preflight."""

    from stage_center.runner import build_production_config, StageCenterRunner

    if not config.get("hk_d1_root"):
        raise _v4_global(_v4_scope, 'ValueError')("fixed HK D-1 Top100 root is required")
    kwargs = {
        key: _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config[key]))
        for key in _v4_global(_v4_scope, 'REQUIRED_CONFIG_KEYS')
        if key in config and key != "candidate_source_root"
    }
    if config.get("v4_morning_news_root") is not None:
        kwargs["v4_morning_news_root"] = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["v4_morning_news_root"]))
    # The runner's production constructor does not accept arbitrary config
    # metadata.  ``hk_full_universe_root`` is retained in the release config
    # for lineage, but with hk_d1_root present it is never selected as a
    # fallback by the Stage-8 path.
    return StageCenterRunner(build_production_config(**kwargs))


def __exact_hk_d1_dependency_rearm_body(_v4_scope, /, config, trade_date, receipt, evaluated_at):
    """One extra attempt only after the existing exact-D1 validator succeeds.

    Never a historical replay permission. Persist the returned reservation under
    the existing slot lock BEFORE running, so a crash consumes this one chance.
    """
    if (_v4_global(_v4_scope, '_receipt_path')(config, trade_date, _v4_global(_v4_scope, 'str')((receipt or {}).get("stage_id", ""))).parent / "dependency_rearm.json").exists():
        return None
    if not receipt or evaluated_at.tzinfo is None:
        return None
    now = _v4_global(_v4_scope, '_rearm_wall_now')()
    if (trade_date != _v4_global(_v4_scope, '_as_shanghai')(now).strftime("%Y%m%d")
            or trade_date != _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).strftime("%Y%m%d")
            or evaluated_at > now or receipt.get("trade_date") != trade_date):
        return None
    attempts = receipt.get("node_attempt_count")
    used = receipt.get("dependency_rearm_count", 0)
    cap = _v4_global(_v4_scope, '_config_int')(config, "node_max_attempts", _v4_global(_v4_scope, 'DEFAULT_MAX_ATTEMPTS'))
    if (_v4_global(_v4_scope, 'type')(attempts) is not _v4_global(_v4_scope, 'int') or attempts != cap
            or _v4_global(_v4_scope, 'type')(used) is not _v4_global(_v4_scope, 'int') or used != 0
            or receipt.get("retry_exhausted") is not True
            or receipt.get("status") != "CANNOT_CONFIRM"
            or receipt.get("schema_version") != "stage_center.runner.receipt.v1"
            or receipt.get("first_failed_layer") != "EXACT_SELECTION_INPUT_BINDING"
            or receipt.get("stage_id") not in _v4_global(_v4_scope, 'STAGE_BY_ID')
            or _v4_global(_v4_scope, 'any')(receipt.get(k) is not False for k in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return None
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')) else None
    if (not _v4_global(_v4_scope, 'isinstance')(hk, _v4_global(_v4_scope, 'Mapping')) or hk.get("status") != "CANNOT_CONFIRM"
            or _v4_global(_v4_scope, 'type')(hk.get("selected_rows")) is not _v4_global(_v4_scope, 'int') or hk["selected_rows"] != 0
            or hk.get("cannot_confirm") != ["exact-date input missing: hkconnect_d1_top100.json"]
            or not config.get("hk_d1_root")):
        return None
    from stage_center.runner import _build_hk_d1_binding
    from stage_center.acquisition import StageUniverseBinding
    try:
        binding = _build_hk_d1_binding(
            _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["hk_d1_root"])),
            trade_date,
            preselection_source_root=config.get("preselection_source_root"),
        )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'RuntimeError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        return None
    if (not _v4_global(_v4_scope, 'isinstance')(binding, StageUniverseBinding) or binding.status != "READY"
            or binding.market != "HK_CONNECT" or binding.trade_date != trade_date
            or binding.role != "HK_CONNECT_D1_TOP100"
            or _v4_global(_v4_scope, 'len')(binding.codes) != 100 or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(binding.codes)) != 100
            or not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-f]{64}", binding.sha256)
            or binding.source_run_id != "hk-d1-" + binding.sha256[:16]):
        return None
    return {
        "dependency_rearm_count": 1,
        "dependency_rearm_reason": "EXACT_HK_D1_BINDING_RECOVERED_SAME_DAY",
        "dependency_rearm_source_run_id": binding.source_run_id,
        "dependency_rearm_source_sha256": binding.sha256,
        "dependency_rearm_reserved_at": now.isoformat(),
    }


def __node_candidates_body(_v4_scope, /, trade_date, evaluated_at, *, explicit_node, config):
    current = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
    if explicit_node is not None:
        node = _v4_global(_v4_scope, 'NODE_BY_ID').get(explicit_node)
        if node is None:
            raise _v4_global(_v4_scope, 'ValueError')(f"unknown node {explicit_node!r}")
        return (node,) if _v4_global(_v4_scope, '_node_due')(node, trade_date, current) else ()
    due = [node for node in _v4_global(_v4_scope, 'NODES') if _v4_global(_v4_scope, '_node_due')(node, trade_date, current)]
    due = [
        node
        for node in due
        if node.is_prep
        or not _v4_global(_v4_scope, '_stage_settled')(_v4_global(_v4_scope, '_read_receipt')(config, trade_date, node.stage_id or ""))
    ]
    return _v4_global(_v4_scope, 'tuple')(due[: _v4_global(_v4_scope, '_config_int')(config, "node_max_nodes_per_run", _v4_global(_v4_scope, 'DEFAULT_MAX_NODES_PER_RUN'))])


def _run_nodes_body(_v4_scope, /, config, *, trade_date, evaluated_at, explicit_node, materializer, runner, sleep):
    """Run prep and/or serial due nodes, returning a bounded typed receipt."""

    evaluated = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
    if not _v4_global(_v4_scope, '_valid_trade_date')(trade_date):
        return {
            "status": "CANNOT_CONFIRM",
            "error": "TRADE_DATE_INVALID",
            "trade_date": trade_date,
            "node_schedule_version": _v4_global(_v4_scope, 'NODE_SCHEDULE_VERSION'),
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    nodes = _v4_global(_v4_scope, '_node_candidates')(
        trade_date, evaluated, explicit_node=explicit_node, config=config
    )
    if not nodes:
        status = "TOO_EARLY" if explicit_node else "NO_NODE_DUE"
        return {
            "status": status,
            "trade_date": trade_date,
            "evaluated_at": evaluated.isoformat(),
            "node_id": explicit_node,
            "nodes": [],
            "node_schedule_version": _v4_global(_v4_scope, 'NODE_SCHEDULE_VERSION'),
            **_v4_global(_v4_scope, '_safe_flags')(),
        }

    results: list[dict[str, Any]] = []
    prepared_snapshots: dict[str, list[Mapping[str, Any]]] = {}
    for node in nodes:
        if node.is_prep:
            gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=("A_SHARE",))
            if node.node_id == _v4_global(_v4_scope, 'PREP_NODE_ID'):
                if gate["status"] != "ELIGIBLE":
                    result = {**gate, "node_id": node.node_id, "dispatch_mode": _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated)}
                else:
                    result = _v4_global(_v4_scope, 'materialize_candidate')(config, trade_date, materializer=materializer)
                    result["dispatch_mode"] = _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated)
                    result["node_id"] = node.node_id
            else:
                gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=("HK_CONNECT",))
                if gate["status"] != "ELIGIBLE":
                    result = {**gate, "node_id": node.node_id, "stage_id": "STAGE_1545_1555", "dispatch_mode": _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated)}
                else:
                    runner = runner or _v4_global(_v4_scope, '_build_runner')(config)
                    captures = _v4_global(_v4_scope, 'list')(
                        runner._prepare_hk_active_snapshots(
                            trade_date,
                            evaluated,
                            stage_id="STAGE_1545_1555",
                        )
                    )
                    prepared_snapshots["STAGE_1545_1555"] = captures
                    capture_statuses = {_v4_global(_v4_scope, 'str')(item.get("status") or "") for item in captures}
                    if "CANNOT_CONFIRM" in capture_statuses:
                        capture_status = "CANNOT_CONFIRM"
                    elif captures and capture_statuses <= {"READY", "NOOP_ALREADY_VERIFIED"}:
                        capture_status = "PRECAPTURE_COMPLETE"
                    else:
                        capture_status = "PRECAPTURE_NOT_DUE"
                    result = {
                        "status": capture_status,
                        "node_id": node.node_id,
                        "stage_id": "STAGE_1545_1555",
                        "trade_date": trade_date,
                        "dispatch_mode": _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated),
                        "pre_captures": captures,
                        **_v4_global(_v4_scope, '_safe_flags')(),
                    }
            results.append(result)
            continue

        stage = _v4_global(_v4_scope, 'STAGE_BY_ID')[node.stage_id or ""]
        mode = _v4_global(_v4_scope, '_node_mode')(node, trade_date, evaluated)
        target = _v4_global(_v4_scope, 'datetime').strptime(
            f"{trade_date} {stage.cutoff}", "%Y%m%d %H:%M:%S"
        ).replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
        after_wait, waited = _v4_global(_v4_scope, '_bounded_wait_until')(target, evaluated, sleep=sleep)
        if waited:
            evaluated = after_wait
            mode = "NATURAL"
        stage_precaptures = prepared_snapshots.get(node.stage_id or "")
        if (
            node.stage_id == "STAGE_1545_1555"
            and stage_precaptures is None
            and evaluated <= target.replace(second=0)
        ):
            runner = runner or _v4_global(_v4_scope, '_build_runner')(config)
            stage_precaptures = _v4_global(_v4_scope, 'list')(
                runner._prepare_hk_active_snapshots(
                    trade_date,
                    evaluated,
                    stage_id=node.stage_id,
                )
            )
            prepared_snapshots[node.stage_id] = stage_precaptures
        result = _v4_global(_v4_scope, '_dispatch_stage')(
            config,
            trade_date,
            node.stage_id or node.node_id,
            evaluated,
            mode=mode,
            runner=runner,
            precaptures=stage_precaptures,
        )
        results.append(result)

    statuses = {_v4_global(_v4_scope, 'str')(item.get("status") or "") for item in results}
    exhausted = [item for item in results if item.get("status") == "SKIPPED_RETRY_EXHAUSTED"]
    if exhausted:
        overall = "RETRY_EXHAUSTED"
    elif statuses <= {"SKIPPED_ALREADY_SETTLED", "SKIPPED_RETRY_BACKOFF", "SKIPPED_SLOT_LOCKED", "SKIPPED_RECEIPT_CHANGED", "SKIPPED_DEPENDENCY_NOT_READY", "SKIPPED_NON_TRADING_DAY", "SKIPPED_SETTLED_RECOVERY_NOT_DUE", "SKIPPED_SETTLED_RECOVERY_ALREADY_CONSUMED"}:
        overall = "RECOVERY_SKIPPED" if _v4_global(_v4_scope, 'any')(item.get("dispatch_mode") == "RECOVERY" for item in results) else "NODES_SKIPPED"
    elif statuses & _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        overall = "CANNOT_CONFIRM"
    else:
        overall = "NODES_COMPLETE"
    return {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "status": overall,
        "trade_date": trade_date,
        "evaluated_at": evaluated.isoformat(),
        "node_schedule_version": _v4_global(_v4_scope, 'NODE_SCHEDULE_VERSION'),
        "nodes": results,
        "node_count": _v4_global(_v4_scope, 'len')(results),
        "recovery": _v4_global(_v4_scope, 'any')(item.get("dispatch_mode") == "RECOVERY" for item in results),
        "exhausted_stages": [
            {
                "stage_id": item.get("stage_id"),
                "node_attempt_count": item.get("node_attempt_count"),
                "first_failed_layer": item.get("first_failed_layer"),
                "error": item.get("error"),
            }
            for item in exhausted
        ],
        "first_failed_layer": _v4_global(_v4_scope, 'next')(
            (item.get("first_failed_layer") for item in exhausted if item.get("first_failed_layer")),
            None,
        ),
        **_v4_global(_v4_scope, '_safe_flags')(),
    }


def __compact_body(_v4_scope, /, value, *, key):
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Path')):
        return _v4_global(_v4_scope, 'str')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        return {_v4_global(_v4_scope, 'str')(k): _v4_global(_v4_scope, '_compact')(v, key=_v4_global(_v4_scope, 'str')(k)) for k, v in value.items()}
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))):
        if key in {"rows", "files"}:
            return {"count": _v4_global(_v4_scope, 'len')(value), "truncated": True}
        return [_v4_global(_v4_scope, '_compact')(item) for item in value[:16]] + ([{"truncated": True, "count": _v4_global(_v4_scope, 'len')(value)}] if _v4_global(_v4_scope, 'len')(value) > 16 else [])
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) and _v4_global(_v4_scope, 'len')(value) > 512:
        return value[:509] + "..."
    return value


def __print_json_body(_v4_scope, /, payload):
    compact = _v4_global(_v4_scope, '_compact')(payload)
    encoded = _v4_global(_v4_scope, 'json').dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if _v4_global(_v4_scope, 'len')(encoded) > 4095:
        # Keep failures ahead of successful PREP nodes. Full diagnostics remain
        # in the dated receipt; stdout has a strict launchd envelope budget.
        node_rows = _v4_global(_v4_scope, 'list')(payload.get("nodes") or [])
        def market_items(node):
            markets = node.get("markets")
            if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')):
                return tuple(
                    (market, lane)
                    for market, lane in markets.items()
                    if _v4_global(_v4_scope, 'isinstance')(lane, _v4_global(_v4_scope, 'Mapping'))
                )
            if _v4_global(_v4_scope, 'isinstance')(markets, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))):
                summary = {"status": node.get("status"), "first_error": node.get("error")}
                return tuple(
                    (market, summary)
                    for market in markets
                    if _v4_global(_v4_scope, 'isinstance')(market, _v4_global(_v4_scope, 'str'))
                )
            return ()

        node_rows.sort(key=lambda node: not (node.get("error") or _v4_global(_v4_scope, 'any')(
            lane.get("first_error") or lane.get("cannot_confirm")
            for _market, lane in market_items(node))))
        compact = {
            "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
            "status": _v4_global(_v4_scope, 'str')(payload.get("status") or "CANNOT_CONFIRM"),
            "trade_date": payload.get("trade_date"),
            "node_schedule_version": _v4_global(_v4_scope, 'NODE_SCHEDULE_VERSION'),
            "output_truncated": True,
            "first_failed_layer": payload.get("first_failed_layer"),
            "nodes": [{"stage_id": node.get("stage_id"), "status": node.get("status"),
                       "error": _v4_global(_v4_scope, 'str')(node.get("error") or "")[:100],
                       "first_failed_layer": node.get("first_failed_layer"),
                       "markets": {market: {"status": lane.get("status", lane.get("selection_status")),
                                    "first_error": _v4_global(_v4_scope, 'str')(lane.get("first_error") or _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(lane.get("cannot_confirm") or []), ""))[:120]}
                                   for market, lane in market_items(node)
                                   if market in {"A_SHARE", "HK_CONNECT"}}}
                      for node in node_rows[:2]],
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
        encoded = _v4_global(_v4_scope, 'json').dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _v4_global(_v4_scope, 'print')(encoded.decode("utf-8"))


def __exit_code_body(_v4_scope, /, status):
    return 0 if status in {
        "CHECK_OK",
        "NODES_COMPLETE",
        "NODES_SKIPPED",
        "RECOVERY_COMPLETE",
        "RECOVERY_SKIPPED",
        "NO_NODE_DUE",
        "TOO_EARLY",
        "SKIPPED_NON_TRADING_DAY",
        "DEADLINE_ONLY_NOT_DUE",
        "DEADLINE_CHAIN_READY",
        "SKIPPED_RETRY_BACKOFF",
        "SKIPPED_RETRY_EXHAUSTED",
        "SKIPPED_ALREADY_SETTLED",
        "SKIPPED_SLOT_LOCKED",
        "SKIPPED_RECEIPT_CHANGED",
        "SKIPPED_DEPENDENCY_NOT_READY",
    } else 3


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Run one bounded stage-center calendar node")
    parser.add_argument("--config", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--node", choices=_v4_global(_v4_scope, 'NODE_IDS'))
    parser.add_argument("--trade-date")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--deadline-only", action="store_true")
    parser.add_argument("--historical-backfill", action="store_true")
    parser.add_argument("--settled-hk-recovery-authorization", type=_v4_global(_v4_scope, 'Path'))
    args = parser.parse_args(argv)
    trace = None
    try:
        if _v4_global(_v4_scope, 'os').environ.get("V4_STAGE_CANARY_ROOT"):
            _v4_global(_v4_scope, '_deadline').install_offline_canary_guard(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').environ["V4_STAGE_CANARY_ROOT"]))
        trace = _v4_global(_v4_scope, '_deadline').install(
            _v4_global(_v4_scope, '_ENTRY_MONOTONIC_NS') if argv is None and _v4_global(_v4_scope, '__name__') == "__main__" else _v4_global(_v4_scope, 'time').monotonic_ns(),
            _v4_global(_v4_scope, '_ENTRY_WALL_NS') if argv is None and _v4_global(_v4_scope, '__name__') == "__main__" else _v4_global(_v4_scope, 'time').time_ns(),
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("IMPORTS_ARGUMENTS_DONE")
        config = _v4_global(_v4_scope, '_load_config')(args.config)
        _v4_global(_v4_scope, '_deadline').checkpoint("CONFIG_LOADED")
        config.pop("_settled_hk_recovery_authorization_path", None)
        now = _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'SHANGHAI'))
        evaluated = (
            _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, 'datetime').fromisoformat(args.evaluated_at))
            if args.evaluated_at
            else now
        )
        trade_date = args.trade_date or evaluated.strftime("%Y%m%d")
        authorization_error = None
        if args.settled_hk_recovery_authorization is not None:
            authorization_path = args.settled_hk_recovery_authorization.expanduser()
            if (not authorization_path.is_absolute() or args.node != "STAGE_1445_1500"
                    or args.trade_date != "20261002" or args.historical_backfill
                    or args.check or args.deadline_only):
                authorization_error = "SETTLED_HK_RECOVERY_REQUIRES_EXPLICIT_20261002_STAGE_1445_1500_RECOVERY"
            else:
                config["_settled_hk_recovery_authorization_path"] = str(authorization_path)
        if authorization_error is not None:
            result = {
                "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
                "status": "CANNOT_CONFIRM",
                "trade_date": trade_date,
                "error": authorization_error,
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        elif args.check:
            result = {
                "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
                "status": "CHECK_OK",
                "config": _v4_global(_v4_scope, 'str')(args.config.resolve()),
                "node_ids": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'NODE_IDS')),
                "calendar_intervals": [
                    {"hour": node.hour, "minute": node.minute, "node_id": node.node_id}
                    for node in _v4_global(_v4_scope, 'NODES')
                ],
                "max_attempts": config["node_max_attempts"],
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        elif args.deadline_only:
            from ops.run_stage_center_tick import deadline_chain_check, _deadline_stage_for

            stage_id = _deadline_stage_for(evaluated.hour, evaluated.minute)
            if stage_id is None:
                result = {
                    "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
                    "status": "DEADLINE_ONLY_NOT_DUE",
                    "trade_date": trade_date,
                    "stage_id": None,
                    "provider_invocations": 0,
                    "business_writes": 0,
                    **_v4_global(_v4_scope, '_safe_flags')(),
                }
            else:
                calendar_gate = _v4_global(_v4_scope, '_calendar_gate')(
                    trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets
                )
                if calendar_gate["status"] != "ELIGIBLE":
                    result = {
                        **calendar_gate,
                        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
                        "stage_id": stage_id,
                        "provider_invocations": 0,
                        "business_writes": 0,
                    }
                else:
                    result = deadline_chain_check(
                        _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["raw_root"])),
                        _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["selection_root"])),
                        trade_date,
                        stage_id,
                    )
        elif not args.historical_backfill and trade_date != now.strftime("%Y%m%d"):
            result = {
                "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
                "status": "CANNOT_CONFIRM",
                "trade_date": trade_date,
                "error": "HISTORICAL_BACKFILL_FLAG_REQUIRED",
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        else:
            result = _v4_global(_v4_scope, 'run_nodes')(
                config,
                trade_date=trade_date,
                evaluated_at=evaluated,
                explicit_node=args.node,
            )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'RuntimeError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        result = {
            "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
            "status": "CANNOT_CONFIRM",
            "error": _v4_global(_v4_scope, 'str')(error),
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    timing = _v4_global(_v4_scope, '_deadline').summary()
    if timing is not None:
        result["end_to_end_deadline"] = timing
    _v4_global(_v4_scope, '_print_json')(result)
    if trace is not None:
        trace.close()
        _v4_global(_v4_scope, '_deadline').set_current(None)
    return _v4_global(_v4_scope, '_exit_code')(_v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM"))
