"""stage_center.live_collectors: temporal_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __has_runner_verified_formal_overlay_body(_v4_scope, /, row):
    """Return whether the runner attached the exact-date formal authority.

    ``_formal_authority_overlay_verified`` is retained as a compatibility
    field in the in-memory row, but it is caller-controlled input at this
    boundary.  Only the runner-owned proof object can authorize the formal
    lane; a raw collector or direct builder caller cannot obtain that proof by
    setting the legacy boolean marker.
    """
    from stage_center.runner import _FORMAL_AUTHORITY_OVERLAY_PROOF

    return row.get("_formal_authority_overlay_proof") is _FORMAL_AUTHORITY_OVERLAY_PROOF


def __exact_market_timestamp_body(_v4_scope, /, value, trade_date):
    """Parse a market timestamp while binding date-only times to ``trade_date``."""
    text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-").replace("Z", "+00:00")
    if _v4_global(_v4_scope, 're').fullmatch(r"\d{8}.*", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if not _v4_global(_v4_scope, 're').search(r"\d{4}-\d{2}-\d{2}", text):
        text = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {text}"
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(text)
    except _v4_global(_v4_scope, 'ValueError'):
        return None
    return parsed.replace(tzinfo=None)


def __snapshot_temporal_cutoff_safe_body(_v4_scope, /, rows, *, trade_date, cutoff_at):
    cutoff = _v4_global(_v4_scope, '_exact_market_timestamp')(cutoff_at, trade_date)
    if cutoff is None or cutoff.date().isoformat().replace("-", "") != trade_date:
        return False
    for row in rows:
        captured = _v4_global(_v4_scope, '_exact_market_timestamp')(
            row.get("update_time") or row.get("update_time_us") or row.get("time"),
            trade_date,
        )
        if captured is None or captured.date().isoformat().replace("-", "") != trade_date or captured > cutoff:
            return False
    return True


def __validate_replay_payload_body(_v4_scope, /, payload, *, trade_date, stage_id, cutoff_at):
    """Validate a read-only replay envelope before normalizing any rows."""
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("replay payload must be a mapping")
    if _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "") != trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("replay trade_date mismatch")
    if _v4_global(_v4_scope, 'str')(payload.get("stage_id") or "") != stage_id:
        raise _v4_global(_v4_scope, 'ValueError')("replay stage_id mismatch")
    if payload.get("temporal_cutoff_safe") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("replay temporal cutoff is not safe")
    for safety_key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(safety_key) is not False:
            raise _v4_global(_v4_scope, 'ValueError')(f"replay safety flag {safety_key} must be false")
    captured_at = _v4_global(_v4_scope, 'str')(payload.get("captured_at") or "")
    captured = _v4_global(_v4_scope, 'datetime').fromisoformat(captured_at.replace("Z", "+00:00")).replace(tzinfo=None)
    cutoff = _v4_global(_v4_scope, 'datetime').fromisoformat(cutoff_at.replace("Z", "+00:00")).replace(tzinfo=None)
    if captured.date().isoformat().replace("-", "") != trade_date or captured > cutoff:
        raise _v4_global(_v4_scope, 'ValueError')("replay captured_at is outside exact date/cutoff")
    raw_rows = payload.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
        raise _v4_global(_v4_scope, 'ValueError')("replay rows must be a sequence")
    return payload, captured_at, raw_rows


def __to_source_body(_v4_scope, /, result, *, source_id, route, requested):
    status = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(result, "status", "CANNOT_CONFIRM"))
    status = {"READ_OK": "READY", "DATA_PARTIAL": "PARTIAL_WITH_ROWS", "READ_FAILED": "CANNOT_CONFIRM"}.get(status, status)
    rows = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'getattr')(result, "rows", ()) or ())
    cannot = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'getattr')(result, "cannot_confirm", ()) or ())
    missing = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'getattr')(result, "no_data_codes", ()) or ())
    return _v4_global(_v4_scope, 'SourceResult')(
        source_id=source_id,
        status=status,
        rows=rows,
        cannot_confirm=cannot,
        error=_v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(result, "error", "") or ""),
        requested_rows=_v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(result, "requested_code_count", requested) or requested),
        missing_symbols=missing,
        source_evidence=(f"route={route}", f"shared_data_root={result.__class__.__module__}"),
    )


def __tdx_code_body(_v4_scope, /, code):
    """Map the stage-center canonical A.###### code to PyTDX's exchange code."""
    raw = _v4_global(_v4_scope, 'str')(code or "").strip().upper()
    if raw.startswith(("SH.", "SZ.", "BJ.")):
        return raw
    digits = raw.split(".", 1)[-1]
    if _v4_global(_v4_scope, 'len')(digits) != 6 or not digits.isdigit():
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid canonical A code: {code!r}")
    if digits.startswith(("600", "601", "603", "605", "688", "689")):
        prefix = "SH"
    elif digits.startswith(("430", "830", "831", "832", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879")):
        prefix = "BJ"
    else:
        prefix = "SZ"
    return f"{prefix}.{digits}"
