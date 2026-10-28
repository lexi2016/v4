"""ops.a_share_daily_sync: sync_workflow (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _run_sync_body(_v4_scope, /, targets, *, target_date, api_factory, host_candidates, count, timeout, dry_run, request_deadline_seconds, symbol_budget_seconds, run_budget_seconds, progress_path, trusted_cas_inputs):
    """Synchronize A daily files with bounded host failover and resume.

    A malformed response invalidates only the symbol currently being fetched.
    A request timeout interrupts the synchronous SDK call in place, so no
    executor thread is left behind.  Accepted symbols are persisted after the
    exact-date append and are skipped on a later run with the same target
    scope.  Connect/request failures quarantine the endpoint for this run;
    Empty responses rotate through the configured hosts within the existing
    symbol/run budgets; a persistent empty result remains symbol-specific
    quarantine evidence. Other content failures remain terminal.
    A reviewed CAS input is indexed once and can only accept an exact-date
    local file after the same history, field, path, record-count, and SHA
    gates pass; uncovered or changed files continue through the owner route.
    """

    target_text = _v4_global(_v4_scope, 'str')(target_date).replace("-", "").replace("/", "")
    if _v4_global(_v4_scope, 'len')(target_text) != 8 or not target_text.isdigit():
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid target date: {target_date!r}")
    try:
        _v4_global(_v4_scope, 'datetime').strptime(target_text, "%Y%m%d")
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid target date: {target_date!r}") from error
    target_int = _v4_global(_v4_scope, 'int')(target_text)
    target_list = _v4_global(_v4_scope, 'list')(targets)
    _v4_global(_v4_scope, '_validate_target_scope')(target_list)
    hosts = [(_v4_global(_v4_scope, 'str')(host), _v4_global(_v4_scope, 'int')(port)) for host, port in host_candidates]
    if not hosts:
        raise _v4_global(_v4_scope, 'ValueError')("TDX host candidates are empty")
    request_deadline = _v4_global(_v4_scope, '_positive_budget')(request_deadline_seconds, "request_deadline_seconds")
    symbol_budget = _v4_global(_v4_scope, '_positive_budget')(symbol_budget_seconds, "symbol_budget_seconds")
    run_budget = _v4_global(_v4_scope, '_positive_budget')(run_budget_seconds, "run_budget_seconds")
    target_fingerprint = _v4_global(_v4_scope, '_target_scope_fingerprint')(target_list)
    if progress_path is None:
        progress_file = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'RUN_DIR')) / "progress" / f"{target_int}-{target_fingerprint}.json"
    else:
        progress_file = _v4_global(_v4_scope, 'Path')(progress_path)
    trusted_cas_path = trusted_cas_inputs
    if trusted_cas_path in (None, ""):
        trusted_cas_path = _v4_global(_v4_scope, 'os').environ.get(_v4_global(_v4_scope, 'TRUSTED_CAS_INPUTS_ENV'))
    trusted_cas_index = _v4_global(_v4_scope, '_trusted_cas_load_inputs')(
        trusted_cas_path,
        target_int,
        expected_target_fingerprint=target_fingerprint,
    )
    progress = _v4_global(_v4_scope, '_load_progress')(progress_file, target_int, target_list, dry_run=dry_run)
    run_id = f"{target_int}-{target_fingerprint[:16]}-{_v4_global(_v4_scope, 'time').time_ns()}"
    prior_completed_symbols = {
        _v4_global(_v4_scope, 'str')(value)
        for value in progress.get("completed_symbols", [])
        if _v4_global(_v4_scope, 'str')(value).strip()
    }
    processed_symbols: set[str] = _v4_global(_v4_scope, 'set')()
    progress["last_run_id"] = run_id
    progress["rule_id"] = _v4_global(_v4_scope, 'RULE_ID')
    progress["rule_version"] = _v4_global(_v4_scope, 'RULE_VERSION')
    progress["field_rule_id"] = _v4_global(_v4_scope, 'FIELD_RULE_ID')
    progress["field_rule_version"] = _v4_global(_v4_scope, 'FIELD_RULE_VERSION')
    progress["last_run_started_at"] = _v4_global(_v4_scope, '_observed_at')()
    run_history = _v4_global(_v4_scope, 'list')(progress.get("run_history", [])) if _v4_global(_v4_scope, 'isinstance')(progress.get("run_history"), _v4_global(_v4_scope, 'list')) else []
    run_history.append(
        {
            "run_id": run_id,
            "target_date": _v4_global(_v4_scope, 'str')(target_int),
            "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
            "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
            "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
            "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        }
    )
    progress["run_history"] = run_history[-32:]
    target_list = _v4_global(_v4_scope, '_resume_target_order')(target_list, progress, target_int)
    # Endpoint quarantine is intentionally scoped to this invocation.  The
    # durable progress file retains accepted symbols, host events, and raw
    # snapshots as evidence, but a transient outage must not make a later
    # recovery skip every configured endpoint forever.
    progress["failed_hosts"] = []
    _v4_global(_v4_scope, '_persist_progress')(progress_file, progress)
    started_at = _v4_global(_v4_scope, 'time').monotonic()
    run_deadline = started_at + run_budget
    by_symbol: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    raw_response_snapshots: list[dict[str, Any]] = []
    api: Any | None = None
    host_position = -1
    host_info: tuple[str, int] | None = None
    last_host_attempted: tuple[str, int] | None = None
    failed_hosts: set[str] = _v4_global(_v4_scope, 'set')()
    run_timeout = False
    timeout_scope: str | None = None
    interrupted = False
    pending_rows: list[dict[str, Any]] = []

    def remaining_run() -> float:
        return run_deadline - _v4_global(_v4_scope, 'time').monotonic()

    def persist_event(
        symbol: str | None,
        *,
        event: str,
        host: str | None = None,
        attempt_ordinal: int | None = None,
        failure_type: str | None = None,
    ) -> None:
        if symbol is not None:
            item = _v4_global(_v4_scope, 'dict')(progress.get("symbol_progress", {}).get(symbol, {}))
            item.update(
                {
                    "symbol": symbol,
                    "target_date": _v4_global(_v4_scope, 'str')(target_int),
                    "event": event,
                    "host": host,
                    "attempt_ordinal": attempt_ordinal,
                    "failure_type": failure_type,
                }
            )
            progress.setdefault("symbol_progress", {})[symbol] = item
        progress["failed_hosts"] = _v4_global(_v4_scope, 'sorted')(failed_hosts)
        events = _v4_global(_v4_scope, 'list')(progress.get("host_events", []))
        if host is not None:
            events.append(
                {
                    "symbol": symbol,
                    "event": event,
                    "host": host,
                    "attempt_ordinal": attempt_ordinal,
                    "failure_type": failure_type,
                    "at": _v4_global(_v4_scope, 'time').monotonic(),
                }
            )
            # Keep the durable cursor bounded even when a live run has many
            # empty provider responses.
            progress["host_events"] = events[-2048:]
        progress["last_event"] = {
            "symbol": symbol,
            "event": event,
            "host": host,
            "attempt_ordinal": attempt_ordinal,
            "failure_type": failure_type,
        }
        _v4_global(_v4_scope, '_persist_progress')(progress_file, progress)

    def mark_completed(symbol: str, row: Mapping[str, Any]) -> None:
        if dry_run:
            return
        completed = {_v4_global(_v4_scope, 'str')(value) for value in progress.get("completed_symbols", [])}
        completed.add(symbol)
        progress["completed_symbols"] = _v4_global(_v4_scope, 'sorted')(completed)
        progress.setdefault("symbol_progress", {})[symbol] = {
            "symbol": symbol,
            "target_date": _v4_global(_v4_scope, 'str')(target_int),
            "status": _v4_global(_v4_scope, 'str')(row.get("status") or "ACCEPTED"),
            "classification": "ACCEPTED",
            "target_date_ready": _v4_global(_v4_scope, 'bool')(row.get("target_date_ready")),
            "last_date_after": row.get("last_date_after"),
            "host": row.get("host"),
            "attempt_ordinal": row.get("attempt_ordinal"),
            "source_sha256_before": row.get("source_sha256_before"),
            "source_sha256_after": row.get("source_sha256_after"),
            "raw_response_snapshots": _v4_global(_v4_scope, 'list')(row.get("raw_response_snapshots") or []),
            "run_id": row.get("run_id") or run_id,
            "rule_id": row.get("rule_id") or _v4_global(_v4_scope, 'RULE_ID'),
            "rule_version": row.get("rule_version") or _v4_global(_v4_scope, 'RULE_VERSION'),
            "field_rule_id": row.get("field_rule_id") or _v4_global(_v4_scope, 'FIELD_RULE_ID'),
            "field_rule_version": row.get("field_rule_version") or _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
            "recorded_at": row.get("recorded_at") or _v4_global(_v4_scope, '_observed_at')(),
        }
        for key in (
            "trusted_cas_rule_id",
            "trusted_cas_rule_version",
            "trusted_cas_cohort",
            "trusted_cas_receipt_ref",
            "trusted_cas_receipt_sha256",
            "trusted_cas_cohort_review_ref",
            "trusted_cas_cohort_review_sha256",
            "trusted_cas_candidate_manifest_ref",
            "trusted_cas_candidate_manifest_sha256",
            "candidate_after_sha256",
        ):
            if key in row:
                progress["symbol_progress"][symbol][key] = row[key]
        persist_event(symbol, event="COMPLETED", host=row.get("host"), attempt_ordinal=row.get("attempt_ordinal"))

    def append_pending(start_index: int, reason: str) -> None:
        for pending in target_list[start_index:]:
            symbol = _v4_global(_v4_scope, 'str')(pending.code)
            if symbol in by_symbol:
                continue
            source_sha = _v4_global(_v4_scope, '_file_sha256')(_v4_global(_v4_scope, 'Path')(pending.path))
            recorded_at = _v4_global(_v4_scope, '_observed_at')()
            row = {
                "symbol": symbol,
                "market": _v4_global(_v4_scope, 'int')(pending.market),
                "status": "CANNOT_CONFIRM",
                "fetch_status": "A_SYNC_TIMEOUT",
                "classification": "UNPROCESSED",
                "reason_code": "A_SYNC_TIMEOUT",
                "quarantine": False,
                "path": _v4_global(_v4_scope, 'str')(pending.path),
                "target_date_ready": False,
                "last_date_before": _v4_global(_v4_scope, 'read_last_date')(pending.path),
                "last_date_after": _v4_global(_v4_scope, 'read_last_date')(pending.path),
                "source_sha256_before": source_sha,
                "source_sha256_after": source_sha,
                "host": "not_attempted",
                "failure_type": reason,
                "raw_response_snapshots": [],
                "run_id": run_id,
                "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
                "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
                "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = row
            reconciliation_rows.append(_v4_global(_v4_scope, 'dict')(row))
            pending_rows.append(row)
            # Do not overwrite a prior accepted marker merely because this
            # invocation ran out of budget before reaching that target.
            if symbol not in prior_completed_symbols:
                progress.setdefault("symbol_progress", {})[symbol] = _v4_global(_v4_scope, 'dict')(row)
        progress["pending_symbols"] = _v4_global(_v4_scope, 'sorted')(row["symbol"] for row in pending_rows)

    def open_next_host(symbol: str, symbol_deadline: float) -> tuple[Any, tuple[str, int]]:
        nonlocal host_position, last_host_attempted
        last_error: Exception | None = None
        while host_position + 1 < _v4_global(_v4_scope, 'len')(hosts):
            host_position += 1
            candidate = hosts[host_position]
            candidate_label = _v4_global(_v4_scope, '_host_label')(*candidate)
            if candidate_label in failed_hosts:
                continue
            last_host_attempted = candidate
            candidate_api = api_factory(candidate[0], candidate[1])
            try:
                remaining = _v4_global(_v4_scope, 'min')(symbol_deadline - _v4_global(_v4_scope, 'time').monotonic(), remaining_run())
                if remaining <= 0:
                    raise _v4_global(_v4_scope, 'SyncTimeoutError')("SYMBOL", symbol_budget, symbol_budget)
                with _v4_global(_v4_scope, '_deadline_guard')(remaining, scope="CONNECT"):
                    _v4_global(_v4_scope, '_connect_session')(candidate_api, candidate[0], candidate[1], timeout)
                persist_event(symbol, event="HOST_CONNECTED", host=candidate_label)
                return candidate_api, candidate
            except _v4_global(_v4_scope, 'Exception') as error:
                last_error = error
                deadline_exhausted = (
                    _v4_global(_v4_scope, 'isinstance')(error, _v4_global(_v4_scope, 'SyncTimeoutError'))
                    and (
                        error.unsupported_context
                        or remaining_run() <= 0
                        or symbol_deadline - _v4_global(_v4_scope, 'time').monotonic() <= 0
                    )
                )
                if (
                    _v4_global(_v4_scope, 'isinstance')(error, _v4_global(_v4_scope, 'SyncTimeoutError'))
                    and not deadline_exhausted
                ) or not _v4_global(_v4_scope, 'isinstance')(error, (_v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'SyncTimeoutError'))):
                    failed_hosts.add(candidate_label)
                persist_event(
                    symbol,
                    event="HOST_FAILED",
                    host=candidate_label,
                    failure_type=_v4_global(_v4_scope, 'str')(error),
                )
                _v4_global(_v4_scope, '_disconnect_session')(candidate_api)
                if deadline_exhausted:
                    # A symbol/run deadline is terminal for this attempt.  Do
                    # not probe another endpoint after the budget is exhausted;
                    # the outer loop preserves the typed scope and evidence.
                    raise
        raise _v4_global(_v4_scope, 'RuntimeError')(f"no usable TDX host remains: {last_error!r}")

    for item_index, item in _v4_global(_v4_scope, 'enumerate')(target_list):
        if remaining_run() <= 0:
            run_timeout = True
            timeout_scope = "RUN"
            append_pending(item_index, "A_SYNC_TIMEOUT:RUN")
            break
        symbol = _v4_global(_v4_scope, 'str')(item.code)
        processed_symbols.add(symbol)
        recorded_at = _v4_global(_v4_scope, '_observed_at')()
        source_sha_before = _v4_global(_v4_scope, '_file_sha256')(_v4_global(_v4_scope, 'Path')(item.path))
        history, history_failure = _v4_global(_v4_scope, '_local_history_status')(_v4_global(_v4_scope, 'Path')(item.path), target_int)
        field_violations = _v4_global(_v4_scope, '_local_field_signature_violations')(
            _v4_global(_v4_scope, 'Path')(item.path),
            symbol=symbol,
            market=_v4_global(_v4_scope, 'int')(item.market),
            run_id=run_id,
            recorded_at=recorded_at,
        )
        existing = history[-2:]
        last_date = _v4_global(_v4_scope, 'day_int')(history[-1]) if history else None
        if last_date == target_int and _v4_global(_v4_scope, 'len')(history) >= 2:
            previous_close = _v4_global(_v4_scope, 'float')(history[-2]["close"])
        else:
            previous_close = _v4_global(_v4_scope, 'float')(history[-1]["close"]) if history else None
        prior_entry = progress.get("symbol_progress", {}).get(symbol, {})
        if not _v4_global(_v4_scope, 'isinstance')(prior_entry, _v4_global(_v4_scope, 'Mapping')):
            prior_entry = {}
        prior_source_sha = prior_entry.get("source_sha256_after") or prior_entry.get("source_sha256_before")
        source_identity_changed = (
            symbol in prior_completed_symbols
            and (not _v4_global(_v4_scope, 'isinstance')(prior_source_sha, _v4_global(_v4_scope, 'str')) or prior_source_sha != source_sha_before)
        )
        prior_target_date = _v4_global(_v4_scope, 'str')(prior_entry.get("target_date") or target_int)
        prior_reason = _v4_global(_v4_scope, 'str')(prior_entry.get("reason_code") or "").split(":", 1)[0].upper()
        terminal_source_unchanged = (
            prior_target_date == _v4_global(_v4_scope, 'str')(target_int)
            and _v4_global(_v4_scope, 'isinstance')(prior_source_sha, _v4_global(_v4_scope, 'str'))
            and prior_source_sha == source_sha_before
            and prior_reason in _v4_global(_v4_scope, '_NONRETRYABLE_CONTENT_FAILURE_CODES')
            and _v4_global(_v4_scope, 'str')(prior_entry.get("classification") or "").upper() == "QUARANTINED"
            and _v4_global(_v4_scope, '_field_rule_identity_current')(prior_entry)
        )
        trusted_cas_entry = _v4_global(_v4_scope, '_trusted_cas_local_reuse')(
            trusted_cas_index,
            item,
            target_int,
            source_sha_before,
            history,
            history_failure,
            field_violations,
        )
        if trusted_cas_entry is not None:
            # The reviewed-CAS path is a local, receipt-bound acceptance.  It
            # deliberately happens before source_identity_changed and before
            # any provider session is opened, while retaining the original
            # target/date/field gates above.
            trusted_accepted = {
                "symbol": symbol,
                "market": _v4_global(_v4_scope, 'int')(item.market),
                "status": "TRUSTED_CAS_CURRENT",
                "fetch_status": "TRUSTED_CAS_REUSE",
                "classification": "ACCEPTED",
                "reason_code": None,
                "quarantine": False,
                "path": _v4_global(_v4_scope, 'str')(item.path),
                "target_date_ready": True,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "host": "trusted_cas",
                "records_written": 0,
                "attempt_ordinal": 0,
                "raw_response_snapshots": [],
                "source_sha256_before": source_sha_before,
                "source_sha256_after": source_sha_before,
                "candidate_after_sha256": trusted_cas_entry.get("candidate_after_sha256"),
                "trusted_cas_rule_id": _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_ID'),
                "trusted_cas_rule_version": _v4_global(_v4_scope, 'TRUSTED_CAS_RULE_VERSION'),
                "trusted_cas_cohort": trusted_cas_entry.get("cohort"),
                "trusted_cas_receipt_ref": trusted_cas_entry.get("receipt_path"),
                "trusted_cas_receipt_sha256": trusted_cas_entry.get("receipt_sha256"),
                "trusted_cas_cohort_review_ref": trusted_cas_entry.get("cohort_review_path"),
                "trusted_cas_cohort_review_sha256": trusted_cas_entry.get("cohort_review_sha256"),
                "trusted_cas_candidate_manifest_ref": trusted_cas_entry.get("candidate_manifest_path"),
                "trusted_cas_candidate_manifest_sha256": trusted_cas_entry.get("candidate_manifest_sha256"),
                "run_id": run_id,
                "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
                "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
                "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = trusted_accepted
            reconciliation_rows.append(_v4_global(_v4_scope, 'dict')(trusted_accepted))
            mark_completed(symbol, trusted_accepted)
            if remaining_run() <= 0:
                run_timeout = True
                timeout_scope = "RUN"
                append_pending(item_index + 1, "A_SYNC_TIMEOUT:RUN")
                break
            continue
        symbol_started_at = _v4_global(_v4_scope, 'time').monotonic()
        symbol_deadline = symbol_started_at + symbol_budget
        symbol_snapshots: list[dict[str, Any]] = []
        prior_snapshots = prior_entry.get("raw_response_snapshots")
        prior_raw_response_snapshots = (
            _v4_global(_v4_scope, 'list')(prior_snapshots) if _v4_global(_v4_scope, 'isinstance')(prior_snapshots, _v4_global(_v4_scope, 'list')) else []
        )
        final_failure: dict[str, Any] | None = None
        terminal_content_failure = False
        if field_violations and prior_reason != _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'):
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                "reason_code": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                "field_violations": field_violations,
            }
            terminal_content_failure = True
        elif history_failure is not None:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": history_failure,
                # Keep the current scan's typed field evidence alongside the
                # primary history failure. A changed source may expose both
                # a duplicate date and the known malformed signature.
                "field_violations": field_violations,
            }
        elif terminal_source_unchanged:
            # Same-date content/history failures are terminal for this source
            # identity.  Retain their raw evidence without spending another
            # provider call; a new target date or changed bytes reopens them.
            final_failure = {
                "symbol": symbol,
                "host": prior_entry.get("host") or "retained_quarantine",
                "failure_type": _v4_global(_v4_scope, 'str')(prior_entry.get("failure_type") or prior_reason),
                "reason_code": prior_reason,
                "raw_response_snapshots": _v4_global(_v4_scope, 'list')(prior_entry.get("raw_response_snapshots") or []),
                "field_violations": _v4_global(_v4_scope, 'list')(prior_entry.get("field_violations") or []),
                "retained_quarantine": True,
            }
        elif field_violations:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                "reason_code": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                "field_violations": field_violations,
            }
            terminal_content_failure = True
        elif last_date is not None and last_date > target_int:
            final_failure = {
                "symbol": symbol,
                "host": "not_attempted",
                "failure_type": _v4_global(_v4_scope, 'SOURCE_DATE_AFTER_TARGET'),
            }
        if (
            final_failure is None
            and last_date == target_int
            and history
            and _v4_global(_v4_scope, 'valid_hq_bar')(history[-1])[0]
            and not source_identity_changed
        ):
            accepted = {
                "symbol": symbol,
                "market": _v4_global(_v4_scope, 'int')(item.market),
                "status": "ALREADY_CURRENT",
                "fetch_status": "ALREADY_CURRENT",
                "classification": "ACCEPTED",
                "reason_code": None,
                "quarantine": False,
                "path": _v4_global(_v4_scope, 'str')(item.path),
                "target_date_ready": True,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "raw_response_snapshots": [],
                "source_sha256_before": source_sha_before,
                "source_sha256_after": source_sha_before,
                "run_id": run_id,
                "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
                "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
                "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
                "recorded_at": recorded_at,
            }
            by_symbol[symbol] = accepted
            reconciliation_rows.append(_v4_global(_v4_scope, 'dict')(accepted))
            mark_completed(symbol, accepted)
            if remaining_run() <= 0:
                run_timeout = True
                timeout_scope = "RUN"
                append_pending(item_index + 1, "A_SYNC_TIMEOUT:RUN")
                break
            continue
        # A failed symbol may have consumed the full host list.  Start the
        # next symbol from the first configured endpoint, while preserving the
        # run-wide failed endpoint quarantine and any healthy live session.
        if api is None:
            host_position = -1
            host_info = None
            last_host_attempted = None
        while True:
            if final_failure is not None:
                break
            remaining = _v4_global(_v4_scope, 'min')(symbol_deadline - _v4_global(_v4_scope, 'time').monotonic(), remaining_run())
            if remaining <= 0:
                final_failure = {
                    "symbol": symbol,
                    "host": _v4_global(_v4_scope, '_host_label')(*(last_host_attempted or host_info))
                    if (last_host_attempted or host_info)
                    else "not_attempted",
                    "failure_type": "A_SYNC_TIMEOUT:RUN" if remaining_run() <= 0 else "A_SYNC_TIMEOUT:SYMBOL",
                }
                if _v4_global(_v4_scope, 'str')(final_failure["failure_type"]).endswith(":RUN"):
                    run_timeout = True
                    timeout_scope = "RUN"
                break
            if api is None:
                try:
                    api, host_info = open_next_host(symbol, symbol_deadline)
                except _v4_global(_v4_scope, 'SyncTimeoutError') as error:
                    effective_timeout_scope = (
                        "UNSUPPORTED_CONTEXT"
                        if error.unsupported_context
                        else "RUN"
                        if error.scope == "RUN" or remaining_run() <= 0
                        else "SYMBOL"
                        if error.scope == "SYMBOL" or symbol_deadline - _v4_global(_v4_scope, 'time').monotonic() <= 0
                        else error.scope
                    )
                    timeout_failure_type = _v4_global(_v4_scope, 'str')(error)
                    if effective_timeout_scope == "UNSUPPORTED_CONTEXT":
                        timeout_failure_type = "A_SYNC_TIMEOUT:UNSUPPORTED_CONTEXT"
                    elif effective_timeout_scope != error.scope:
                        timeout_failure_type = timeout_failure_type.replace(
                            f"A_SYNC_TIMEOUT:{error.scope}",
                            f"A_SYNC_TIMEOUT:{effective_timeout_scope}",
                            1,
                        )
                    final_failure = {
                        "symbol": symbol,
                        "host": _v4_global(_v4_scope, '_host_label')(*(last_host_attempted or host_info))
                        if (last_host_attempted or host_info)
                        else "unavailable",
                        "failure_type": timeout_failure_type,
                        "timeout_scope": effective_timeout_scope,
                        "deadline_seconds": error.deadline_seconds,
                        "elapsed_seconds": error.elapsed_seconds,
                        "unsupported_context": _v4_global(_v4_scope, 'bool')(error.unsupported_context),
                    }
                    if effective_timeout_scope in {"RUN", "UNSUPPORTED_CONTEXT"}:
                        run_timeout = True
                        timeout_scope = effective_timeout_scope
                    elif effective_timeout_scope == "SYMBOL":
                        timeout_scope = "SYMBOL"
                    break
                except _v4_global(_v4_scope, 'Exception') as error:
                    final_failure = {
                        "symbol": symbol,
                        "host": _v4_global(_v4_scope, '_host_label')(*(last_host_attempted or host_info))
                        if (last_host_attempted or host_info)
                        else "unavailable",
                        "failure_type": "host_unavailable",
                        "error": _v4_global(_v4_scope, 'repr')(error),
                    }
                    break
            assert host_info is not None
            attempt_ordinal = _v4_global(_v4_scope, 'len')(symbol_snapshots) + 1
            attempt_snapshots: list[dict[str, Any]] = []
            attempt_field_violations: list[dict[str, Any]] = []
            host_label = _v4_global(_v4_scope, '_host_label')(*host_info)

            def capture_response(rows: Any) -> None:
                attempt_snapshots.append(
                    _v4_global(_v4_scope, '_write_raw_response_snapshot')(
                        target_date=target_int,
                        target=item,
                        request={
                            "code": symbol,
                            "count": _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(count)),
                            "kline": 9,
                            "market": _v4_global(_v4_scope, 'int')(item.market),
                            "start": 0,
                            "target_date": _v4_global(_v4_scope, 'str')(target_int),
                        },
                        host=_v4_global(_v4_scope, '_host_label')(*host_info),
                        host_ordinal=host_position + 1,
                        attempt_ordinal=attempt_ordinal,
                        response_rows=rows,
                        run_id=run_id,
                        rule_id=_v4_global(_v4_scope, 'RULE_ID'),
                        rule_version=_v4_global(_v4_scope, 'RULE_VERSION'),
                        observed_at=recorded_at,
                    )
                )

            try:
                remaining = _v4_global(_v4_scope, 'min')(symbol_deadline - _v4_global(_v4_scope, 'time').monotonic(), remaining_run())
                if remaining <= 0:
                    raise _v4_global(_v4_scope, 'SyncTimeoutError')("RUN" if remaining_run() <= 0 else "SYMBOL", symbol_budget, symbol_budget)
                with _v4_global(_v4_scope, '_deadline_guard')(_v4_global(_v4_scope, 'min')(request_deadline, remaining), scope="REQUEST"):
                    bars, failure_type = _v4_global(_v4_scope, '_fetch_valid_target_bars')(
                        api,
                        item,
                        target_int,
                        previous_close,
                        count,
                        after_date=last_date,
                        capture_response=capture_response,
                        field_violations=attempt_field_violations,
                        run_id=run_id,
                        recorded_at=recorded_at,
                    )
                symbol_snapshots.extend(attempt_snapshots)
                if attempt_field_violations and attempt_snapshots:
                    for violation in attempt_field_violations:
                        violation["source_snapshot"] = _v4_global(_v4_scope, 'dict')(attempt_snapshots[-1])
                        violation["source_file_sha256"] = attempt_snapshots[-1]["sha256"]
                        violation["source_ref"] = (
                            f"{attempt_snapshots[-1]['path']}#response_index={violation['row_index']}"
                        )
                if failure_type in {"OK", "ok"}:
                    if last_date == target_int:
                        if not history or not _v4_global(_v4_scope, '_bars_equivalent')(history[-1], bars[-1]):
                            final_failure = {
                                "symbol": symbol,
                                "host": host_label,
                                "failure_type": _v4_global(_v4_scope, 'SOURCE_IDENTITY_CHANGED'),
                            }
                            terminal_content_failure = True
                            persist_event(
                                symbol,
                                event="CONTENT_FAILURE",
                                host=host_label,
                                attempt_ordinal=attempt_ordinal,
                                failure_type=_v4_global(_v4_scope, 'SOURCE_IDENTITY_CHANGED'),
                            )
                            break
                        bars_to_write: list[dict[str, Any]] = []
                        accepted_status = "REVALIDATED_CURRENT"
                        accepted_fetch_status = "REVALIDATED"
                    else:
                        bars_to_write = [bar for bar in bars if _v4_global(_v4_scope, 'day_int')(bar) > (last_date or 0)]
                        accepted_status = "UPDATED"
                        accepted_fetch_status = "OK"
                    append_field_violations = [
                        violation
                        for row_index, bar in _v4_global(_v4_scope, 'enumerate')(bars_to_write)
                        if (
                            violation := _v4_global(_v4_scope, '_provider_field_signature_violation')(
                                bar,
                                symbol=symbol,
                                market=_v4_global(_v4_scope, 'int')(item.market),
                                row_index=row_index,
                                run_id=run_id,
                                recorded_at=recorded_at,
                            )
                        ) is not None
                    ]
                    if append_field_violations:
                        for violation in append_field_violations:
                            if attempt_snapshots:
                                violation["source_snapshot"] = _v4_global(_v4_scope, 'dict')(attempt_snapshots[-1])
                                violation["source_file_sha256"] = attempt_snapshots[-1]["sha256"]
                                violation["source_ref"] = (
                                    f"{attempt_snapshots[-1]['path']}#response_index={violation['row_index']}"
                                )
                        final_failure = {
                            "symbol": symbol,
                            "host": host_label,
                            "failure_type": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                            "reason_code": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                            "field_violations": append_field_violations,
                        }
                        terminal_content_failure = True
                        persist_event(
                            symbol,
                            event="CONTENT_FAILURE",
                            host=host_label,
                            attempt_ordinal=attempt_ordinal,
                            failure_type=_v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
                        )
                        break
                    if not dry_run:
                        _v4_global(_v4_scope, 'append_bars')(item.path, bars_to_write)
                    last_after = last_date if not bars_to_write else _v4_global(_v4_scope, 'day_int')(bars_to_write[-1])
                    source_sha_after = _v4_global(_v4_scope, '_file_sha256')(_v4_global(_v4_scope, 'Path')(item.path))
                    accepted = {
                        "symbol": symbol,
                        "market": _v4_global(_v4_scope, 'int')(item.market),
                        "status": accepted_status,
                        "fetch_status": accepted_fetch_status,
                        "classification": "ACCEPTED",
                        "reason_code": None,
                        "quarantine": False,
                        "path": _v4_global(_v4_scope, 'str')(item.path),
                        "target_date_ready": last_after == target_int,
                        "last_date_before": last_date,
                        "last_date_after": last_after,
                        "host": _v4_global(_v4_scope, '_host_label')(*host_info),
                        "records_written": _v4_global(_v4_scope, 'len')(bars_to_write),
                        "attempt_ordinal": attempt_ordinal,
                        "raw_response_snapshots": prior_raw_response_snapshots + _v4_global(_v4_scope, 'list')(symbol_snapshots),
                        "source_sha256_before": source_sha_before,
                        "source_sha256_after": source_sha_after,
                        "run_id": run_id,
                        "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
                        "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
                        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
                        "recorded_at": recorded_at,
                    }
                    by_symbol[symbol] = accepted
                    reconciliation_rows.append(_v4_global(_v4_scope, 'dict')(accepted))
                    mark_completed(symbol, accepted)
                    final_failure = None
                    if remaining_run() <= 0:
                        run_timeout = True
                        timeout_scope = "RUN"
                    break
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": failure_type,
                    "reason_code": _v4_global(_v4_scope, '_reason_code')(failure_type),
                    "field_violations": _v4_global(_v4_scope, 'list')(attempt_field_violations),
                }
                terminal_content_failure = (
                    _v4_global(_v4_scope, '_reason_code')(failure_type) in _v4_global(_v4_scope, '_NONRETRYABLE_CONTENT_FAILURE_CODES')
                )
                persist_event(
                    symbol,
                    event="CONTENT_FAILURE",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=_v4_global(_v4_scope, 'str')(failure_type),
                )
            except _v4_global(_v4_scope, 'SyncTimeoutError') as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _v4_global(_v4_scope, '_write_raw_response_snapshot')(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(count)),
                                "kline": 9,
                                "market": _v4_global(_v4_scope, 'int')(item.market),
                                "start": 0,
                                "target_date": _v4_global(_v4_scope, 'str')(target_int),
                            },
                            host=host_label,
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error=_v4_global(_v4_scope, 'str')(error),
                            run_id=run_id,
                            rule_id=_v4_global(_v4_scope, 'RULE_ID'),
                            rule_version=_v4_global(_v4_scope, 'RULE_VERSION'),
                            observed_at=recorded_at,
                        )
                    )
                # A request deadline is still symbol-scoped evidence while
                # the run remains inside its global budget.  Do not turn one
                # slow symbol into a run-wide endpoint quarantine: the next
                # symbol must be able to use the same provider lane.
                effective_timeout_scope = (
                    "UNSUPPORTED_CONTEXT"
                    if error.unsupported_context
                    else "RUN"
                    if error.scope == "RUN" or remaining_run() <= 0
                    else "SYMBOL"
                )
                timeout_failure_type = _v4_global(_v4_scope, 'str')(error)
                if effective_timeout_scope == "UNSUPPORTED_CONTEXT":
                    timeout_failure_type = "A_SYNC_TIMEOUT:UNSUPPORTED_CONTEXT"
                elif effective_timeout_scope != error.scope:
                    timeout_failure_type = timeout_failure_type.replace(
                        f"A_SYNC_TIMEOUT:{error.scope}",
                        f"A_SYNC_TIMEOUT:{effective_timeout_scope}",
                        1,
                    )
                if effective_timeout_scope == "RUN":
                    failed_hosts.add(host_label)
                persist_event(
                    symbol,
                    event="REQUEST_TIMEOUT",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=timeout_failure_type,
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": timeout_failure_type,
                    "timeout_scope": effective_timeout_scope,
                    "deadline_seconds": error.deadline_seconds,
                    "elapsed_seconds": error.elapsed_seconds,
                    "unsupported_context": _v4_global(_v4_scope, 'bool')(error.unsupported_context),
                }
                if effective_timeout_scope in {"RUN", "UNSUPPORTED_CONTEXT"}:
                    run_timeout = True
                    timeout_scope = effective_timeout_scope
                elif effective_timeout_scope == "SYMBOL":
                    timeout_scope = "SYMBOL"
            except _v4_global(_v4_scope, 'KeyboardInterrupt') as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _v4_global(_v4_scope, '_write_raw_response_snapshot')(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(count)),
                                "kline": 9,
                                "market": _v4_global(_v4_scope, 'int')(item.market),
                                "start": 0,
                                "target_date": _v4_global(_v4_scope, 'str')(target_int),
                            },
                            host=host_label,
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error="A_SYNC_INTERRUPTED",
                            run_id=run_id,
                            rule_id=_v4_global(_v4_scope, 'RULE_ID'),
                            rule_version=_v4_global(_v4_scope, 'RULE_VERSION'),
                            observed_at=recorded_at,
                        )
                    )
                interrupted = True
                timeout_scope = "INTERRUPTED"
                persist_event(
                    symbol,
                    event="INTERRUPTED",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type="A_SYNC_INTERRUPTED",
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": "A_SYNC_INTERRUPTED",
                    "error": _v4_global(_v4_scope, 'repr')(error),
                }
            except _v4_global(_v4_scope, 'Exception') as error:
                if not attempt_snapshots:
                    symbol_snapshots.append(
                        _v4_global(_v4_scope, '_write_raw_response_snapshot')(
                            target_date=target_int,
                            target=item,
                            request={
                                "code": symbol,
                                "count": _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(count)),
                                "kline": 9,
                                "market": _v4_global(_v4_scope, 'int')(item.market),
                                "start": 0,
                                "target_date": _v4_global(_v4_scope, 'str')(target_int),
                            },
                            host=_v4_global(_v4_scope, '_host_label')(*host_info),
                            host_ordinal=host_position + 1,
                            attempt_ordinal=attempt_ordinal,
                            response_error=_v4_global(_v4_scope, 'repr')(error),
                            run_id=run_id,
                            rule_id=_v4_global(_v4_scope, 'RULE_ID'),
                            rule_version=_v4_global(_v4_scope, 'RULE_VERSION'),
                            observed_at=recorded_at,
                        )
                    )
                protocol_details = _v4_global(_v4_scope, '_protocol_response_details')(error)
                failure_type = (
                    _v4_global(_v4_scope, 'PROTOCOL_RESPONSE_MALFORMED')
                    if protocol_details is not None
                    else "request_error"
                )
                final_failure = {
                    "symbol": symbol,
                    "host": host_label,
                    "failure_type": failure_type,
                    **(
                        protocol_details
                        if protocol_details is not None
                        else {"error": _v4_global(_v4_scope, 'repr')(error)}
                    ),
                }
                failed_hosts.add(host_label)
                persist_event(
                    symbol,
                    event="REQUEST_FAILURE",
                    host=host_label,
                    attempt_ordinal=attempt_ordinal,
                    failure_type=failure_type,
                )
            # Every failed provider request, including EMPTY_RESPONSE, closes
            # the current session before the next attempt.  EMPTY_RESPONSE is
            # retryable for this symbol, so the next iteration advances to the
            # next host while terminal content failures remain symbol-final.
            _v4_global(_v4_scope, '_disconnect_session')(api)
            api = None
            if run_timeout or interrupted or symbol_deadline - _v4_global(_v4_scope, 'time').monotonic() <= 0:
                break
            if terminal_content_failure:
                break
            if host_position + 1 >= _v4_global(_v4_scope, 'len')(hosts):
                break
            final_failure = None
        if final_failure is not None:
            failure_type = _v4_global(_v4_scope, 'str')(final_failure.get("failure_type") or "REQUEST_ERROR")
            quarantined = {
                "symbol": symbol,
                "market": _v4_global(_v4_scope, 'int')(item.market),
                "status": "CANNOT_CONFIRM" if failure_type.startswith("A_SYNC_TIMEOUT") else "FAILED",
                "fetch_status": "REBUILD_REQUIRED",
                "classification": "QUARANTINED",
                "reason_code": _v4_global(_v4_scope, '_reason_code')(failure_type),
                "quarantine": True,
                "path": _v4_global(_v4_scope, 'str')(item.path),
                "target_date_ready": False,
                "last_date_before": last_date,
                "last_date_after": last_date,
                "source_sha256_before": source_sha_before,
                "source_sha256_after": _v4_global(_v4_scope, '_file_sha256')(_v4_global(_v4_scope, 'Path')(item.path)),
                "raw_response_snapshots": prior_raw_response_snapshots + _v4_global(_v4_scope, 'list')(symbol_snapshots),
                "field_violations": _v4_global(_v4_scope, 'list')(final_failure.get("field_violations") or []),
                "run_id": run_id,
                "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
                "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
                "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
                "recorded_at": recorded_at,
                **final_failure,
            }
            # Keep the legacy failure list byte-for-byte compatible while the
            # reconciliation carries the typed reason used by new consumers.
            quarantined["failure_type"] = _v4_global(_v4_scope, '_compat_failure_type')(failure_type)
            by_symbol[symbol] = quarantined
            reconciliation_rows.append(_v4_global(_v4_scope, 'dict')(quarantined))
            progress.setdefault("symbol_progress", {})[symbol] = {
                **quarantined,
                "failure_type": failure_type,
                "reason_code": _v4_global(_v4_scope, '_reason_code')(failure_type),
                "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
                "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
            }
            failure_entry = _v4_global(_v4_scope, 'dict')(final_failure)
            failure_entry["failure_type"] = _v4_global(_v4_scope, '_compat_failure_type')(failure_type)
            failures.append(failure_entry)
            if failure_type.startswith("A_SYNC_TIMEOUT"):
                run_timeout = run_timeout or failure_type.endswith(":RUN") or remaining_run() <= 0
                if final_failure.get("unsupported_context"):
                    # Preserve the explicit pre-provider context failure so a
                    # fail-closed authority receipt does not call it a real
                    # elapsed RUN timeout.
                    timeout_scope = timeout_scope or "UNSUPPORTED_CONTEXT"
                elif run_timeout:
                    timeout_scope = "RUN"
            # Reset the endpoint cursor after an exhausted symbol.  This is
            # essential after all hosts return EMPTY_RESPONSE: the next symbol
            # must begin at the first configured endpoint.
            _v4_global(_v4_scope, '_disconnect_session')(api)
            api = None
            host_position = -1
            host_info = None
            last_host_attempted = None
        raw_response_snapshots.extend(symbol_snapshots)
        if run_timeout or interrupted:
            append_pending(item_index + 1, "A_SYNC_INTERRUPTED" if interrupted else "A_SYNC_TIMEOUT:RUN")
            break

    _v4_global(_v4_scope, '_disconnect_session')(api)
    completed_count = _v4_global(_v4_scope, 'sum')(row.get("classification") == "ACCEPTED" for row in reconciliation_rows)
    status = "INTERRUPTED" if interrupted else "TIMEOUT" if run_timeout else "PASS" if not failures else "FAILED"
    accepted_count = _v4_global(_v4_scope, 'sum')(row.get("classification") == "ACCEPTED" for row in reconciliation_rows)
    quarantine_count = _v4_global(_v4_scope, 'sum')(row.get("classification") == "QUARANTINED" for row in reconciliation_rows)
    target_count = _v4_global(_v4_scope, 'len')(target_list)
    progress["failed_hosts"] = _v4_global(_v4_scope, 'sorted')(failed_hosts)
    current_accepted_symbols = {
        symbol
        for symbol, row in by_symbol.items()
        if row.get("classification") == "ACCEPTED"
    }
    if dry_run:
        progress["completed_symbols"] = []
    else:
        target_symbols = {_v4_global(_v4_scope, 'str')(item.code) for item in target_list}
        # A bounded run may stop before reaching a prior accepted target after
        # pending work is moved to the front.  Retain that durable marker until
        # the target is actually processed and fails; then replace it with the
        # current accepted union.  This prevents a partial receipt from
        # reclassifying untouched completed work as unprocessed.
        carried_completed = prior_completed_symbols - processed_symbols
        pending_symbols = {_v4_global(_v4_scope, 'str')(row["symbol"]) for row in pending_rows}
        progress["completed_symbols"] = _v4_global(_v4_scope, 'sorted')(
            ((carried_completed | current_accepted_symbols) - pending_symbols) & target_symbols
        )
    progress["pending_symbols"] = _v4_global(_v4_scope, 'sorted')(row["symbol"] for row in pending_rows)
    progress["last_event"] = {
        "symbol": None,
        "event": "INTERRUPTED" if interrupted else "TIMEOUT" if run_timeout else "COMPLETE",
        "timeout_scope": timeout_scope,
    }
    _v4_global(_v4_scope, '_persist_progress')(progress_file, progress)
    reconciliation = {
        "target_count": target_count,
        "accepted_count": accepted_count,
        "quarantine_count": quarantine_count,
        "pending_count": _v4_global(_v4_scope, 'len')(pending_rows),
        "symbols": reconciliation_rows,
    }
    return {
        "task_name": _v4_global(_v4_scope, 'TASK_NAME'),
        "run_id": run_id,
        "rule_id": _v4_global(_v4_scope, 'RULE_ID'),
        "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "status": status,
        "exit_code": 0 if status == "PASS" else 130 if status == "INTERRUPTED" else 124 if status == "TIMEOUT" else 2,
        "target_date": _v4_global(_v4_scope, 'str')(target_int),
        "target_fingerprint": target_fingerprint,
        "target_keys": _v4_global(_v4_scope, '_target_scope_keys')(target_list),
        "target_count": target_count,
        "updated_count": _v4_global(_v4_scope, 'sum')(item.get("status") == "UPDATED" for item in by_symbol.values()),
        "accepted_count": accepted_count,
        "quarantine_count": quarantine_count,
        "completed_count": completed_count,
        "pending_count": _v4_global(_v4_scope, 'len')(pending_rows),
        "timeout": _v4_global(_v4_scope, 'bool')(run_timeout),
        "interrupted": _v4_global(_v4_scope, 'bool')(interrupted),
        "timeout_scope": timeout_scope,
        "progress_path": _v4_global(_v4_scope, 'str')(progress_file),
        "progress": progress,
        "budgets": {
            "request_deadline_seconds": request_deadline,
            "symbol_budget_seconds": symbol_budget,
            "run_budget_seconds": run_budget,
            "run_elapsed_seconds": _v4_global(_v4_scope, 'max')(0.0, _v4_global(_v4_scope, 'time').monotonic() - started_at),
        },
        "accepted_target_date_file_count": accepted_count,
        "coverage_rate": (accepted_count / target_count) if target_count else None,
        "authority_status": "CANNOT_CONFIRM" if run_timeout else "PASS" if not failures else "REBUILD_REQUIRED" if accepted_count else "FAILED",
        "reconciliation": reconciliation,
        "symbol_reconciliation": reconciliation_rows,
        "raw_response_snapshots": raw_response_snapshots,
        "failures": failures,
        "by_symbol": by_symbol,
        "host": _v4_global(_v4_scope, '_host_label')(*host_info) if host_info else None,
        "trusted_cas": {
            "configured": trusted_cas_path not in (None, ""),
            "loaded": trusted_cas_index is not None,
            "config_path": trusted_cas_index.get("config_path") if trusted_cas_index else None,
            "config_sha256": trusted_cas_index.get("config_sha256") if trusted_cas_index else None,
            "target_date": trusted_cas_index.get("target_date") if trusted_cas_index else None,
            "cohort_counts": trusted_cas_index.get("cohort_counts") if trusted_cas_index else None,
        },
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
