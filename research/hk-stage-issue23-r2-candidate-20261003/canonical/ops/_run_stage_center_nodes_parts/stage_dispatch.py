"""ops.run_stage_center_nodes: stage_dispatch (review candidate, not deployment)."""
from __future__ import annotations
import hashlib as _stage_hashlib
from ._namespace import read_global as _v4_global


_SETTLED_HK_RECOVERY_AUTH_ID = "hk-stage-20261002-1445-1500-r2"
_SETTLED_HK_RECOVERY_INCIDENT = {
    "schema_version": "stage_center.settled_hk_recovery_authorization.v1",
    "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
    "trade_date": "20261002",
    "stage_id": "STAGE_1445_1500",
    "mode": "RECOVERY",
    "prior_receipt_sha256": "b2f4e758f7480c668904e40b6a71181ebc8e19a3916e76f215c4c812fe303a23",
    "prior_node_attempt_count": 2,
    "max_attempts": 3,
    "reserved_node_attempt_count": 3,
    "stale_candidate_current_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
    "stale_candidate_run_id": "hk-d1-20260930-f45233cd1d30d04a",
    "corrected_pool_id": "hkconnect_d1_top100",
    "corrected_candidate_artifact_sha256": "9486b32cd8290994e1bf82cd15863fb7d0c00100bd52f1f6eb5d03af80b72077",
    "target_date": "20261002",
    "source_date": "20260930",
    "row_count": 100,
    "unique_code_count": 100,
    "execution_limit": 1,
}


def _settled_hk_recovery_result(_v4_scope, /, *, status, trade_date, stage_id, mode, attempt_count, reason):
    return {
        "status": status,
        "stage_id": stage_id,
        "node_id": stage_id,
        "trade_date": trade_date,
        "dispatch_mode": mode,
        "node_attempt_count": attempt_count,
        "first_failed_layer": reason,
        "write_performed": False,
        **_v4_global(_v4_scope, '_safe_flags')(),
    }


def _settled_hk_recovery_authorization(_v4_scope, /, path_value):
    path = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(path_value)).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')("authorization must be an absolute regular file")
    if path.stat().st_size > 65536:
        raise _v4_global(_v4_scope, 'ValueError')("authorization file exceeds the bounded size")
    raw = path.read_bytes()
    payload = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ValueError')("authorization must be a JSON object")
    if any(payload.get(key) != expected for key, expected in _SETTLED_HK_RECOVERY_INCIDENT.items()):
        raise _v4_global(_v4_scope, 'ValueError')("authorization incident binding mismatch")
    for key in ("prior_node_attempt_count", "max_attempts", "reserved_node_attempt_count", "row_count", "unique_code_count", "execution_limit"):
        if _v4_global(_v4_scope, 'type')(payload.get(key)) is not _v4_global(_v4_scope, 'int'):
            raise _v4_global(_v4_scope, 'ValueError')("authorization count fields must be integers")
    if payload.get("authorization_status") != "AUTHORIZED" or payload.get("review_status") != "APPROVED":
        raise _v4_global(_v4_scope, 'ValueError')("authorization is not approved for one-shot execution")
    authorized_by = payload.get("authorized_by")
    writer_id = payload.get("implementation_writer_id")
    reviewer_id = payload.get("independent_reviewer_id")
    if (not _v4_global(_v4_scope, 'isinstance')(authorized_by, _v4_global(_v4_scope, 'str'))
            or not authorized_by.strip()
            or not _v4_global(_v4_scope, 'isinstance')(writer_id, _v4_global(_v4_scope, 'str'))
            or not writer_id.strip()
            or not _v4_global(_v4_scope, 'isinstance')(reviewer_id, _v4_global(_v4_scope, 'str'))
            or not reviewer_id.strip()
            or len({authorized_by.strip(), writer_id.strip(), reviewer_id.strip()}) != 3
            or not _v4_global(_v4_scope, 'isinstance')(payload.get("approval_id"), _v4_global(_v4_scope, 'str'))
            or not payload.get("approval_id", "").strip()):
        raise _v4_global(_v4_scope, 'ValueError')("authorization approval identity is incomplete")
    for key in ("authorized_at", "independently_reviewed_at"):
        try:
            approved_at = _v4_global(_v4_scope, 'datetime').fromisoformat(payload.get(key, ""))
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamp is invalid") from error
        if (approved_at.tzinfo is None
                or _v4_global(_v4_scope, '_as_shanghai')(approved_at).strftime("%Y%m%d") != _SETTLED_HK_RECOVERY_INCIDENT["trade_date"]):
            raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamp is outside the incident date")
    flags = payload.get("safety_flags")
    if (not _v4_global(_v4_scope, 'isinstance')(flags, _v4_global(_v4_scope, 'Mapping'))
            or any(flags.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise _v4_global(_v4_scope, 'ValueError')("authorization safety flags must remain false")
    digest = _stage_hashlib.sha256(raw).hexdigest()
    return payload, raw, digest


def _settled_hk_recovery_receipt_matches(_v4_scope, /, receipt):
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'dict')):
        return False
    if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _SETTLED_HK_RECOVERY_INCIDENT["trade_date"],
        "stage_id": _SETTLED_HK_RECOVERY_INCIDENT["stage_id"],
        "node_id": _SETTLED_HK_RECOVERY_INCIDENT["stage_id"],
        "dispatch_mode": "RECOVERY",
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 2,
        "write_performed": True,
        "candidate_current_sha256": _SETTLED_HK_RECOVERY_INCIDENT["stale_candidate_current_sha256"],
        "candidate_run_id": _SETTLED_HK_RECOVERY_INCIDENT["stale_candidate_run_id"],
        "due_status": "LATE_CATCHUP_REPLAY",
    }
    if any(receipt.get(key) != expected for key, expected in required.items()):
        return False
    if _v4_global(_v4_scope, 'type')(receipt.get("node_attempt_count")) is not _v4_global(_v4_scope, 'int'):
        return False
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')) else None
    return (
        _v4_global(_v4_scope, 'isinstance')(hk, _v4_global(_v4_scope, 'Mapping'))
        and hk.get("source_status") == "PARTIAL_WITH_ROWS"
        and hk.get("selection_status") == "PARTIAL_WITH_ROWS"
        and _v4_global(_v4_scope, 'type')(hk.get("selected_rows")) is _v4_global(_v4_scope, 'int')
        and hk.get("selected_rows") == 10
        and hk.get("cannot_confirm") == ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"]
        and not any(hk.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    )


def __dispatch_settled_hk_recovery_body(
    _v4_scope, /, config, trade_date, stage_id, evaluated_at, *, mode, runner,
    precaptures, observed_receipt, authorization_path, max_attempts,
):
    """Consume one exact, approved recovery authorization under the original slot lock."""
    from stage_center.runner import SlotLock, _slot_lock_path, _build_hk_stage_binding

    scope_reason = "SETTLED_HK_RECOVERY_SCOPE_MISMATCH"
    if (mode != "RECOVERY" or trade_date != _SETTLED_HK_RECOVERY_INCIDENT["trade_date"]
            or stage_id != _SETTLED_HK_RECOVERY_INCIDENT["stage_id"] or max_attempts != 3):
        return _settled_hk_recovery_result(
            _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
            mode=mode, attempt_count=_v4_global(_v4_scope, '_node_attempt_count')(observed_receipt), reason=scope_reason,
        )
    decision = _v4_global(_v4_scope, 'next')((
        item for item in runner.due_decisions(
            trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
        ) if item.stage_id == stage_id
    ), None)
    if decision is None:
        return _settled_hk_recovery_result(
            _v4_scope, status="SKIPPED_SETTLED_RECOVERY_NOT_DUE", trade_date=trade_date,
            stage_id=stage_id, mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_STAGE_NOT_DUE",
        )

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return _settled_hk_recovery_result(
            _v4_scope, status="SKIPPED_SLOT_LOCKED", trade_date=trade_date, stage_id=stage_id,
            mode=mode, attempt_count=2, reason="STAGE_SLOT_LOCKED",
        )
    try:
        _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        decision = _v4_global(_v4_scope, 'next')((
            item for item in runner.due_decisions(
                trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
            ) if item.stage_id == stage_id
        ), None)
        if decision is None:
            return _settled_hk_recovery_result(
                _v4_scope, status="SKIPPED_SETTLED_RECOVERY_NOT_DUE", trade_date=trade_date,
                stage_id=stage_id, mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_STAGE_NOT_DUE",
            )
        receipt_path = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id)
        history_root = receipt_path.parent / "settled_hk_recovery_r2"
        history_dir = history_root / _SETTLED_HK_RECOVERY_AUTH_ID
        if history_root.is_symlink() or history_dir.exists() or history_dir.is_symlink():
            return _settled_hk_recovery_result(
                _v4_scope, status="SKIPPED_SETTLED_RECOVERY_ALREADY_CONSUMED", trade_date=trade_date,
                stage_id=stage_id, mode=mode, attempt_count=3, reason="SETTLED_HK_RECOVERY_ALREADY_CONSUMED",
            )

        try:
            authorization, authorization_raw, authorization_sha = _settled_hk_recovery_authorization(
                _v4_scope, authorization_path
            )
            now = _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, '_rearm_wall_now')())
            authorized_at = _v4_global(_v4_scope, '_as_shanghai')(
                _v4_global(_v4_scope, 'datetime').fromisoformat(authorization["authorized_at"])
            )
            reviewed_at = _v4_global(_v4_scope, '_as_shanghai')(
                _v4_global(_v4_scope, 'datetime').fromisoformat(authorization["independently_reviewed_at"])
            )
            if reviewed_at > authorized_at or authorized_at > now or reviewed_at > now:
                raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamps are invalid")
            if receipt_path.is_symlink():
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt must be a regular file")
            if _v4_global(_v4_scope, 'os').path.realpath(receipt_path.parent) != _v4_global(_v4_scope, 'os').path.realpath(
                    _v4_global(_v4_scope, 'Path')(config["receipt_root"]).expanduser() / trade_date / stage_id):
                raise _v4_global(_v4_scope, 'ValueError')("stage receipt path is not the configured slot path")
            raw_receipt = receipt_path.read_bytes()
            if len(raw_receipt) > 2 * 1024 * 1024:
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt exceeds the bounded size")
            receipt_sha = _stage_hashlib.sha256(raw_receipt).hexdigest()
            current_receipt = _v4_global(_v4_scope, 'json').loads(raw_receipt.decode("utf-8"))
            reread_receipt = _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id)
            if (receipt_sha != _SETTLED_HK_RECOVERY_INCIDENT["prior_receipt_sha256"]
                    or current_receipt != observed_receipt or reread_receipt != current_receipt
                    or not _settled_hk_recovery_receipt_matches(_v4_scope, current_receipt)):
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt identity mismatch")
            if (max_attempts != authorization.get("max_attempts")
                    or _v4_global(_v4_scope, '_node_attempt_count')(current_receipt) != authorization.get("prior_node_attempt_count")):
                raise _v4_global(_v4_scope, 'ValueError')("attempt reservation binding mismatch")
            rearm_marker = receipt_path.parent / "dependency_rearm.json"
            if rearm_marker.exists() or rearm_marker.is_symlink():
                raise _v4_global(_v4_scope, 'ValueError')("dependency rearm marker is present")

            local_evaluated = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
            scheduled_at = getattr(decision, "scheduled_at", None)
            expected_cutoff = _v4_global(_v4_scope, 'datetime').strptime(
                f"{trade_date} {_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].cutoff}",
                "%Y%m%d %H:%M:%S",
            ).replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
            if (evaluated_at.tzinfo is None or now.tzinfo is None
                    or local_evaluated.strftime("%Y%m%d") != trade_date
                    or now.strftime("%Y%m%d") != trade_date
                    or local_evaluated > now
                    or decision.status != "LATE_CATCHUP_REPLAY"
                    or getattr(decision, "trade_date", None) != trade_date
                    or getattr(decision, "stage_id", None) != stage_id
                    or scheduled_at is None
                    or _v4_global(_v4_scope, '_as_shanghai')(scheduled_at) != expected_cutoff
                    or local_evaluated <= expected_cutoff):
                raise _v4_global(_v4_scope, 'ValueError')("same-day late recovery decision is invalid")
            gate = _v4_global(_v4_scope, '_calendar_gate')(
                trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets
            )
            if gate.get("status") != "ELIGIBLE":
                raise _v4_global(_v4_scope, 'ValueError')("stage calendar is not eligible")
            safety_config = config.get("safety")
            if (safety_config is not None
                    and (not _v4_global(_v4_scope, 'isinstance')(safety_config, _v4_global(_v4_scope, 'Mapping'))
                         or any(safety_config.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")))):
                raise _v4_global(_v4_scope, 'ValueError')("configured safety flags must remain false")
            pool_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["hk_d1_root"]))
            source_root = config.get("preselection_source_root")
            if not source_root:
                raise _v4_global(_v4_scope, 'ValueError')("exact HK preselection source root is required")
            binding = _build_hk_stage_binding(
                pool_root, trade_date,
                preselection_source_root=_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(source_root)),
            )
            expected_pool_sha = _SETTLED_HK_RECOVERY_INCIDENT["corrected_candidate_artifact_sha256"]
            if (binding.status != "READY" or binding.market != "HK_CONNECT"
                    or binding.trade_date != trade_date or binding.role != "HK_CONNECT_D1_TOP100"
                    or len(binding.codes) != 100 or len(set(binding.codes)) != 100
                    or binding.sha256 != expected_pool_sha
                    or binding.source_run_id != "hk-d1-" + expected_pool_sha[:16]):
                raise _v4_global(_v4_scope, 'ValueError')("corrected exact-date HK D-1 pool binding mismatch")
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'RuntimeError'),
                _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'),
                _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'AttributeError'),
                _v4_global(_v4_scope, 'ImportError')) as error:
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_VALIDATION_FAILED",
            ) | {"error": _v4_global(_v4_scope, 'str')(error)}

        history_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if history_root.is_symlink():
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_HISTORY_PATH_UNSAFE",
            )
        try:
            history_dir.mkdir(mode=0o700)
            prior_copy = history_dir / "prior_receipt.json"
            fd = _v4_global(_v4_scope, 'os').open(
                prior_copy, _v4_global(_v4_scope, 'os').O_WRONLY | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL, 0o600
            )
            with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
                stream.write(raw_receipt)
                stream.flush()
                _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            reservation = {
                "schema_version": "stage_center.settled_hk_recovery_reservation.v1",
                "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
                "authorization_sha256": authorization_sha,
                "prior_receipt_sha256": receipt_sha,
                "original_node_attempt_count": 2,
                "reserved_node_attempt_count": 3,
                "corrected_pool_sha256": binding.sha256,
                "corrected_pool_source_run_id": binding.source_run_id,
                "decision_status": decision.status,
                "reserved_at": now.isoformat(),
                "status": "RESERVED_BEFORE_PROVIDER",
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
            reservation_raw = _v4_global(_v4_scope, 'json').dumps(
                reservation, ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8") + b"\n"
            fd = _v4_global(_v4_scope, 'os').open(
                history_dir / "reservation.json",
                _v4_global(_v4_scope, 'os').O_WRONLY | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL, 0o600,
            )
            with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
                stream.write(reservation_raw)
                stream.flush()
                _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            directory_fd = _v4_global(_v4_scope, 'os').open(history_dir, _v4_global(_v4_scope, 'os').O_RDONLY)
            try:
                _v4_global(_v4_scope, 'os').fsync(directory_fd)
            finally:
                _v4_global(_v4_scope, 'os').close(directory_fd)
            for protected_path in (prior_copy, history_dir / "reservation.json"):
                _v4_global(_v4_scope, 'os').chmod(protected_path, 0o400)
            for directory in (history_dir, history_root, receipt_path.parent):
                directory_fd = _v4_global(_v4_scope, 'os').open(directory, _v4_global(_v4_scope, 'os').O_RDONLY)
                try:
                    _v4_global(_v4_scope, 'os').fsync(directory_fd)
                finally:
                    _v4_global(_v4_scope, 'os').close(directory_fd)
            _v4_global(_v4_scope, 'os').chmod(history_dir, 0o500)
            _v4_global(_v4_scope, 'os').chmod(history_root, 0o500)
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'FileExistsError')) as error:
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_RESERVATION_FAILED",
            ) | {"error": _v4_global(_v4_scope, 'str')(error)}

        if hasattr(decision, "same_day_late_observation_recovery"):
            decision.same_day_late_observation_recovery = True
        captured = _v4_global(_v4_scope, 'list')(precaptures or ())
        attempt_count = 3
        _v4_global(_v4_scope, '_deadline').due(
            decision.scheduled_at, trade_date=trade_date, stage_id=stage_id,
            due_status=decision.status, dispatch_mode=mode,
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        from stage_center.attempt_evidence import capture_attempt
        with capture_attempt(
            runner._receipt_path(trade_date, stage_id).parent,
            trade_date=trade_date, stage_id=stage_id, attempt_number=attempt_count,
            evaluated_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
            due_status=decision.status,
        ) as attempt_journal:
            result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            attempt_journal.finish(result)
        result["attempt_diagnostic"] = attempt_journal.summary()
        _v4_global(_v4_scope, '_deadline').event("BUSINESS_RETURN", status=result.get("status"))
        result.update({
            "node_id": stage_id,
            "dispatch_mode": mode,
            "node_attempt_count": attempt_count,
            "pre_captures": captured,
            "settled_hk_recovery": {
                "schema_version": "stage_center.settled_hk_recovery_result.v1",
                "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
                "authorization_sha256": authorization_sha,
                "prior_receipt_sha256": receipt_sha,
                "reserved_node_attempt_count": attempt_count,
                "corrected_pool_sha256": binding.sha256,
                "reservation_path": str(history_dir / "reservation.json"),
                "prior_receipt_archive_path": str(history_dir / "prior_receipt.json"),
                "same_day_late_observation_recovery": True,
            },
        })
        if result.get("status") == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            result["status"] = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        status = _v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM")
        outcome = _v4_global(_v4_scope, '_node_outcome')(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = _v4_global(_v4_scope, 'bool')(outcome == "TRANSIENT" and attempt_count >= max_attempts)
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                + _v4_global(_v4_scope, 'timedelta')(seconds=_v4_global(_v4_scope, '_config_float')(
                    config, "node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS')
                ))
            ).isoformat()
        else:
            result.pop("retry_after", None)
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _v4_global(_v4_scope, '_deadline').complete_receipt(
            runner._receipt_path(trade_date, stage_id), persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        return persisted
    finally:
        lock.release()


def __dispatch_stage_body(_v4_scope, /, config, trade_date, stage_id, evaluated_at, *, mode, runner, precaptures):
    """Run exactly one stage under the runner's existing per-stage lock."""

    if stage_id not in _v4_global(_v4_scope, 'STAGE_BY_ID'):
        raise _v4_global(_v4_scope, 'ValueError')(f"unknown stage node {stage_id!r}")
    gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets)
    if gate["status"] != "ELIGIBLE":
        return {**gate, "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode}
    runner = runner or _v4_global(_v4_scope, '_build_runner')(config)
    max_attempts = _v4_global(_v4_scope, '_config_int')(config, "node_max_attempts", _v4_global(_v4_scope, 'DEFAULT_MAX_ATTEMPTS'))
    retry_backoff = _v4_global(_v4_scope, '_config_float')(
        config, "node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS')
    )
    receipt = _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id)
    attempt_count = _v4_global(_v4_scope, '_node_attempt_count')(receipt)
    existing_status = _v4_global(_v4_scope, 'str')((receipt or {}).get("status") or "")
    authorization_path = config.get("_settled_hk_recovery_authorization_path")
    if authorization_path is not None:
        return __dispatch_settled_hk_recovery_body(
            _v4_scope, config, trade_date, stage_id, evaluated_at,
            mode=mode, runner=runner, precaptures=precaptures,
            observed_receipt=receipt, authorization_path=authorization_path,
            max_attempts=max_attempts,
        )
    # The inner runner may replace receipt.json before it exits. This immutable
    # reservation survives that write and prevents a crash from reopening retries.
    rearm_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / "dependency_rearm.json"
    if rearm_marker.exists() and not _v4_global(_v4_scope, '_stage_settled')(receipt):
        attempt_count = _v4_global(_v4_scope, 'max')(attempt_count, max_attempts + 1)
        existing_status = "CANNOT_CONFIRM"
    if _v4_global(_v4_scope, '_stage_settled')(receipt) and existing_status not in _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        return {
            "status": "SKIPPED_ALREADY_SETTLED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "node_outcome": (receipt or {}).get("node_outcome", "SETTLED"),
            "node_attempt_count": attempt_count,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    rearm = None
    if existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        if attempt_count >= max_attempts:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
        if attempt_count >= max_attempts and rearm is None:
            previous = receipt or {}
            return {
                "status": "SKIPPED_RETRY_EXHAUSTED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT_EXHAUSTED",
                "node_attempt_count": attempt_count,
                "retry_exhausted": True,
                "first_failed_layer": (
                    previous.get("first_failed_layer")
                    or previous.get("blocked_layer")
                    or "STAGE_RETRY_BUDGET_EXHAUSTED"
                ),
                "error": previous.get("error"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        if rearm is None and not _v4_global(_v4_scope, '_retry_is_due')(
            receipt,
            _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
            retry_backoff_seconds=retry_backoff,
        ):
            return {
                "status": "SKIPPED_RETRY_BACKOFF",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT",
                "node_attempt_count": attempt_count,
                "retry_after": (receipt or {}).get("retry_after"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }

    from stage_center.runner import SlotLock, _slot_lock_path

    decision = _v4_global(_v4_scope, 'next')(
        item
        for item in runner.due_decisions(
            trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
        )
        if item.stage_id == stage_id
    )
    if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY"}:
        return {
            "status": decision.status,
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return {
            "status": "SKIPPED_SLOT_LOCKED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    try:
        _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        # Recheck after acquiring the original lock; never overwrite a newer run.
        if _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id) != receipt:
            return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                    "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
        if rearm is not None:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
            if rearm is None:
                return {"status": "SKIPPED_DEPENDENCY_NOT_READY", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            rearm_marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                with rearm_marker.open("x", encoding="utf-8") as stream:
                    _v4_global(_v4_scope, 'json').dump({"schema_version": "stage_center.dependency_rearm.v1",
                               "trade_date": trade_date, "stage_id": stage_id,
                               **rearm, **_v4_global(_v4_scope, '_safe_flags')()}, stream, sort_keys=True)
                    stream.flush()
                    _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            except _v4_global(_v4_scope, 'FileExistsError'):
                return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            runner._write_receipt({**(receipt or {}), **rearm}, trade_date, stage_id)
        # Stage-8 pre-capture is scheduled at 15:50 and, when a launch lands
        # exactly on 15:55:00, may be retried once more before the 15:55:05
        # consumer cutoff.  Never invoke it after the immutable window.
        captured = _v4_global(_v4_scope, 'list')(precaptures or ())
        attempt_count += 1
        _v4_global(_v4_scope, '_deadline').due(
            decision.scheduled_at,
            trade_date=trade_date,
            stage_id=stage_id,
            due_status=decision.status,
            dispatch_mode=mode,
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        # Diagnostics only; slot lock, attempt budget and cutoff policy are unchanged.
        from stage_center.attempt_evidence import capture_attempt
        with capture_attempt(
            runner._receipt_path(trade_date, stage_id).parent,
            trade_date=trade_date, stage_id=stage_id, attempt_number=attempt_count,
            evaluated_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
            due_status=decision.status,
        ) as attempt_journal:
            result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            attempt_journal.finish(result)
        result["attempt_diagnostic"] = attempt_journal.summary()
        _v4_global(_v4_scope, '_deadline').event("BUSINESS_RETURN", status=result.get("status"))
        result.update(
            {
                "node_id": stage_id,
                "dispatch_mode": mode,
                "node_attempt_count": attempt_count,
                "pre_captures": captured,
            }
        )
        # Preserve consumed re-arm metadata across both success and failure.
        result.update({k: v for k, v in (receipt or {}).items()
                       if k.startswith("dependency_rearm_")})
        if rearm is not None:
            result.update(rearm)
        status = _v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM")
        if status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            # A partial status without a committed write is not a valid
            # settled partial.  Reclassify it into the bounded retry lane.
            result["status"] = status = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        outcome = _v4_global(_v4_scope, '_node_outcome')(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = _v4_global(_v4_scope, 'bool')(
            outcome == "TRANSIENT" and attempt_count >= max_attempts
        )
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                + _v4_global(_v4_scope, 'timedelta')(seconds=retry_backoff)
            ).isoformat()
        else:
            result.pop("retry_after", None)
        # _record_dispatch_metadata is the existing receipt writer and keeps
        # the base runner's schema and safety flags.  The final write adds the
        # node cap metadata atomically through the same per-stage lock.
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _v4_global(_v4_scope, '_deadline').complete_receipt(
            runner._receipt_path(trade_date, stage_id),
            persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        return persisted
    finally:
        lock.release()
