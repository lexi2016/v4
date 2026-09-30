"""ops.run_v35_macos_scheduler: schedule_selection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __fixed_slot_catchup_allowed_body(_v4_scope, /, slot, moment):
    """Apply slot-specific catch-up deadlines to non-hourly owners.

    The 09:15 HK auction capture is an opening-window input.  A late wake can
    recover it only while the capture window is still open; after 09:19:59 a
    retry of that slot would be a false representation of the live auction.
    Other fixed slots retain the caller's normal bounded catch-up window.
    """

    if slot == "1130":
        return moment.hour == 11 and moment.minute <= 38
    if slot != "0915":
        return True
    return moment.hour == 9 and moment.minute <= 19


def __slot_blocks_retry_body(_v4_scope, /, ledger_root, business_date, slot, *, moment, retry_backoff_seconds, max_failed_attempts, upstream_fingerprint, release_id):
    claim = (
        ledger_root
        / "claims"
        / "live"
        / business_date
        / slot
        / "dispatch.claim.json"
    )
    if claim.is_file():
        return True
    receipts = ledger_root / "receipts" / "live" / business_date / slot
    if not receipts.is_dir():
        return False
    observed: list[dict[str, Any]] = []
    for path in receipts.glob("*.dispatch-receipt.json"):
        try:
            payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
            return True
        if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
            return True
        observed.append(payload)
    if not observed:
        return False
    if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(payload.get("status") or "") != "FAILED" for payload in observed):
        return True
    failure_classes = {_v4_global(_v4_scope, 'str')(payload.get("failure_class") or "").upper() for payload in observed}
    if failure_classes & _v4_global(_v4_scope, 'TERMINAL_FAILURE_CLASSES'):
        return True
    intraday_outcome = _v4_global(_v4_scope, '_intraday_attempt_outcome')(observed)
    if intraday_outcome == "BLOCK":
        return True
    # A new exact upstream pointer or release invalidates the old retry cap.
    # This is the key distinction from the former permanent three-attempt
    # block: a repaired selector/current or a new immutable release gets a
    # fresh attempt without changing the historical receipts.
    if upstream_fingerprint is not None and _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'str')(payload.get("upstream_fingerprint") or "") != upstream_fingerprint
        for payload in observed
    ):
        return False
    if release_id is not None and _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'str')(payload.get("release_id") or "") != release_id
        for payload in observed
    ):
        return False
    legacy_receipts = [payload for payload in observed if not _v4_global(_v4_scope, 'str')(payload.get("failure_class") or "").strip()]
    typed_classes = failure_classes - {""}
    if typed_classes and not typed_classes.issubset(_v4_global(_v4_scope, 'RETRYABLE_FAILURE_CLASSES')):
        # Unknown failure types stay fail-closed until the executor classifies
        # them; they must not be retried blindly by the minute launcher.
        return True
    if legacy_receipts and _v4_global(_v4_scope, 'len')(legacy_receipts) >= _v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(max_failed_attempts)):
        # Receipts emitted before typed failure metadata existed retain the
        # historical bounded-attempt contract.  A current release or exact
        # upstream fingerprint was handled above and intentionally resets this
        # compatibility cap without rewriting the old receipts.
        return True
    # Retryable upstream/network failures are governed by time backoff, not a
    # permanent attempt ceiling.  ``max_failed_attempts`` remains accepted for
    # compatibility with older callers but is intentionally not used to turn
    # a recoverable input outage into a terminal receipt.
    finished: list[datetime] = []
    retry_after: list[datetime] = []
    for payload in observed:
        retry_value = _v4_global(_v4_scope, 'str')(payload.get("retry_after") or "")
        if retry_value:
            try:
                parsed_retry = _v4_global(_v4_scope, 'datetime').fromisoformat(retry_value.replace("Z", "+00:00"))
            except _v4_global(_v4_scope, 'ValueError'):
                return True
            if parsed_retry.tzinfo is None or parsed_retry.utcoffset() is None:
                return True
            retry_after.append(parsed_retry.astimezone(_v4_global(_v4_scope, 'UTC')))
            continue
        raw = _v4_global(_v4_scope, 'str')(payload.get("finished_at") or "")
        try:
            parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(raw.replace("Z", "+00:00"))
        except _v4_global(_v4_scope, 'ValueError'):
            return True
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return True
        finished.append(parsed.astimezone(_v4_global(_v4_scope, 'UTC')))
    current = moment.astimezone(_v4_global(_v4_scope, 'UTC'))
    if retry_after:
        return current < _v4_global(_v4_scope, 'max')(retry_after)
    return current - _v4_global(_v4_scope, 'max')(finished) < _v4_global(_v4_scope, 'timedelta')(
        seconds=_v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(retry_backoff_seconds))
    )


def _resolve_due_slot_body(_v4_scope, /, *, ledger_root, now, catchup_window_minutes, upstream_fingerprint, release_id, capture_only):
    """Resolve an exact slot or the earliest bounded unclaimed catch-up.

    Only the most recent hour and only a bounded sub-hour window are eligible.
    Claims and successful receipts block duplicates. Failed hourly receipts are
    eligible for a bounded, backoff-controlled retry so a temporary network
    outage can recover after wake. Special stage and pool slots are never
    synthesized.
    """
    moment = now or _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'SHANGHAI'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
    else:
        moment = moment.astimezone(_v4_global(_v4_scope, 'SHANGHAI'))
    business_date = moment.strftime("%Y%m%d")
    observed_slot = moment.strftime("%H%M")
    exact = {
        "business_date": business_date,
        "observed_slot": observed_slot,
        "slot": observed_slot,
        "catchup": False,
        "lag_minutes": 0,
    }
    if capture_only or "1530" <= observed_slot < "1532":
        state = _v4_global(_v4_scope, 'capture_state')(_v4_global(_v4_scope, 'Path')(ledger_root), business_date, moment)
        return {**exact, "slot": "1530" if state["due"] else None,
                "catchup": observed_slot != "1530", "capture_retry": state,
                "status": state["status"], "retry_blocked": not state["due"]}
    # Do not let an older post-close retry monopolize the dispatcher at an
    # exact hourly wake.  The current hourly workload is independent of the
    # prior close node and must get one attempt; the ordered post-close list
    # remains eligible on the next five-minute wake.  This prevents a failed
    # 15:00 receipt from starving 16:00/17:00 research indefinitely while
    # preserving dependency order for the non-hourly 17:30 evidence slot.
    if observed_slot in _v4_global(_v4_scope, 'CATCHUP_EXACT_PRIORITY_SLOTS') and not _v4_global(_v4_scope, '_slot_blocks_retry')(
        _v4_global(_v4_scope, 'Path')(ledger_root),
        business_date,
        observed_slot,
        moment=moment,
        upstream_fingerprint=upstream_fingerprint,
        release_id=release_id,
    ):
        return exact
    if 15 <= _v4_global(_v4_scope, 'int')(observed_slot[:2]) <= _v4_global(_v4_scope, 'CRITICAL_SAME_DAY_CATCHUP_END_HOUR'):
        # v16 fairness: among already-due slots, give unattempted owners their
        # first chance before retrying failed siblings. Stable order preserves
        # the existing post-close sequence within each group; gates stay below.
        def attempted(slot: str) -> bool:
            receipts = _v4_global(_v4_scope, 'Path')(ledger_root) / "receipts" / "live" / business_date / slot
            return receipts.is_dir() and _v4_global(_v4_scope, 'any')(receipts.glob("*.dispatch-receipt.json"))

        for slot in _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'POST_CLOSE_CATCHUP_SLOTS'), key=attempted):
            if slot == "1530":
                continue  # Deadline-bound capture is never ordinary late catch-up.
            if observed_slot < slot:
                continue
            if _v4_global(_v4_scope, '_slot_blocks_retry')(
                _v4_global(_v4_scope, 'Path')(ledger_root),
                business_date,
                slot,
                moment=moment,
                upstream_fingerprint=upstream_fingerprint,
                release_id=release_id,
            ):
                continue
            scheduled = moment.replace(
                hour=_v4_global(_v4_scope, 'int')(slot[:2]), minute=_v4_global(_v4_scope, 'int')(slot[2:]), second=0, microsecond=0
            )
            if slot == observed_slot:
                return exact
            return {
                "business_date": business_date,
                "observed_slot": observed_slot,
                "slot": slot,
                "catchup": True,
                "lag_minutes": _v4_global(_v4_scope, 'int')((moment - scheduled).total_seconds() // 60),
            }
    if observed_slot in _v4_global(_v4_scope, 'ALL_SLOTS'):
        if _v4_global(_v4_scope, '_slot_blocks_retry')(
            _v4_global(_v4_scope, 'Path')(ledger_root),
            business_date,
            observed_slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            return {
                **exact,
                "slot": None,
                "status": "RETRY_BACKOFF",
                "retry_blocked": True,
            }
        return exact
    window = _v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(catchup_window_minutes))
    for slot in _v4_global(_v4_scope, 'reversed')(_v4_global(_v4_scope, 'CATCHUP_FIXED_SLOTS')):
        if not _v4_global(_v4_scope, '_fixed_slot_catchup_allowed')(slot, moment):
            continue
        scheduled = moment.replace(
            hour=_v4_global(_v4_scope, 'int')(slot[:2]),
            minute=_v4_global(_v4_scope, 'int')(slot[2:]),
            second=0,
            microsecond=0,
        )
        lag_minutes = _v4_global(_v4_scope, 'int')((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _v4_global(_v4_scope, '_slot_blocks_retry')(
            _v4_global(_v4_scope, 'Path')(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    for slot in _v4_global(_v4_scope, 'reversed')(_v4_global(_v4_scope, 'CATCHUP_HOURLY_SLOTS')):
        scheduled = moment.replace(
            hour=_v4_global(_v4_scope, 'int')(slot[:2]),
            minute=0,
            second=0,
            microsecond=0,
        )
        lag_minutes = _v4_global(_v4_scope, 'int')((moment - scheduled).total_seconds() // 60)
        if lag_minutes < 0 or lag_minutes > window:
            continue
        if _v4_global(_v4_scope, '_slot_blocks_retry')(
            _v4_global(_v4_scope, 'Path')(ledger_root),
            business_date,
            slot,
            moment=moment,
            upstream_fingerprint=upstream_fingerprint,
            release_id=release_id,
        ):
            continue
        return {
            "business_date": business_date,
            "observed_slot": observed_slot,
            "slot": slot,
            "catchup": True,
            "lag_minutes": lag_minutes,
        }
    return exact
