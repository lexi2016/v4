"""stage_center.selection: primitives_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __selection_identity_ids_body(_v4_scope, /, trade_date, stage_id, market, raw_artifact_sha256, algorithm_sha256, rows):
    """Return the immutable IDs for the shared selection identity.

    Every algorithm uses the same canonical payload: the logical slot,
    external raw-artifact SHA, algorithm SHA, and final serialized rows. No
    legacy or compatible identity is accepted by :class:`SelectionStore`.
    """
    identity = {
        "identity": f"{trade_date}/{stage_id}/{market}",
        "raw_artifact_sha256": raw_artifact_sha256,
        "algorithm_sha256": algorithm_sha256,
        "rows": _v4_global(_v4_scope, 'list')(rows),
    }
    canonical = _v4_global(_v4_scope, '_canonical_sha')(identity)
    return f"selection-{canonical[:24]}", f"run-{canonical[:24]}"


def __atomic_write_bytes_body(_v4_scope, /, path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.{_v4_global(_v4_scope, 'uuid4')().hex}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __atomic_write_csv_body(_v4_scope, /, path, rows, *, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.{_v4_global(_v4_scope, 'uuid4')().hex}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = _v4_global(_v4_scope, 'csv').DictWriter(
                stream,
                fieldnames=fields,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __safe_relative_body(_v4_scope, /, root, relative):
    if (
        not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str'))
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or (_v4_global(_v4_scope, 'len')(relative) > 1 and relative[1] == ":")
    ):
        raise _v4_global(_v4_scope, 'SelectionError')("selection path must be normalized and relative")
    parsed = _v4_global(_v4_scope, 'PurePosixPath')(relative)
    if parsed.as_posix() != relative or _v4_global(_v4_scope, 'any')(part in {"", ".", ".."} for part in parsed.parts):
        raise _v4_global(_v4_scope, 'SelectionError')("selection path must be normalized and relative")
    current = root
    for part in _v4_global(_v4_scope, 'Path')(relative).parts:
        current = current / part
        if current.is_symlink():
            raise _v4_global(_v4_scope, 'SelectionError')("selection symlink component is forbidden")
    try:
        current.resolve().relative_to(root.resolve())
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'SelectionError')("selection path escapes store root") from error
    return current


def __stage_card_evidence_body(_v4_scope, /, source, *, code, open_price, last_price, high_price, low_price, source_last_bar_time, next_validation_time):
    """Normalize the evidence that both stage-center consumers render.

    The old V3 formulas only needed a code and score.  The shared artifact is
    also the UI's evidence boundary, so all stage-card fields are carried in
    one place.  Price-level defaults intentionally follow the old V3 rule:
    support/invalidation are the observed stage low and pressure is the stage
    high.  No code is ever used as a display name.
    """
    def first(*values: Any) -> Any:
        for value in values:
            if value not in (None, ""):
                return value
        return None

    normalized_open = _v4_global(_v4_scope, '_optional_number')(first(open_price, source.get("open_price"), source.get("open"), source.get("first_open")))
    normalized_last = _v4_global(_v4_scope, '_optional_number')(first(last_price, source.get("last_price"), source.get("last"), source.get("last_close"), source.get("close")))
    normalized_high = _v4_global(_v4_scope, '_optional_number')(first(high_price, source.get("high_price"), source.get("high")))
    normalized_low = _v4_global(_v4_scope, '_optional_number')(first(low_price, source.get("low_price"), source.get("low")))
    current_change = _v4_global(_v4_scope, '_optional_number')(source.get("current_change_pct"))
    if current_change is None:
        current_change = _v4_global(_v4_scope, '_live_pct_change')(normalized_last, normalized_open)
    support = _v4_global(_v4_scope, '_optional_number')(first(source.get("support"), source.get("support_primary_price"), source.get("support_price")))
    pressure = _v4_global(_v4_scope, '_optional_number')(first(source.get("pressure"), source.get("pressure_price"), source.get("resistance_price")))
    invalidation = _v4_global(_v4_scope, '_optional_number')(first(source.get("invalidation"), source.get("invalidation_price")))
    support = normalized_low if support is None else support
    pressure = normalized_high if pressure is None else pressure
    invalidation = support if invalidation is None else invalidation
    name = first(source.get("name"), source.get("stock_name"))
    if name is not None and _v4_global(_v4_scope, 'str')(name).strip() == code:
        name = None
    last_bar_time = first(source_last_bar_time, source.get("source_last_bar_time"), source.get("update_time"), source.get("source_last_tick_time"))
    validation_time = first(next_validation_time, source.get("next_validation_time"))
    return {
        "name": name,
        "stock_name": name,
        "current_change_pct": None if current_change is None else _v4_global(_v4_scope, 'round')(current_change, 4),
        "open_price": normalized_open,
        "last_price": normalized_last,
        "high_price": normalized_high,
        "low_price": normalized_low,
        "support": support,
        "pressure": pressure,
        "invalidation": invalidation,
        "source_last_bar_time": last_bar_time,
        "next_validation_time": validation_time,
        "support_primary_price": support,
        "pressure_price": pressure,
        "invalidation_price": invalidation,
    }


def __a_normalized_row_body(_v4_scope, /, row, *, source_mode):
    code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(row, "code", "ts_code", "stock_code") or "").strip()
    if not code:
        raise _v4_global(_v4_scope, 'SelectionError')("A selection row code is required")
    first_open = _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(row, "first_open", "open"))
    last_close = _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(row, "last_close", "close"))
    high = _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(row, "high", "high_price"))
    low = _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(row, "low", "low_price"))
    can_compute = first_open is not None and last_close is not None and high is not None and low is not None
    window_change = _v4_global(_v4_scope, '_optional_number')(row.get("window_change_pct"))
    if window_change is None:
        window_change = ((last_close / first_open - 1) * 100) if can_compute and first_open else 0.0
    close_position = _v4_global(_v4_scope, '_optional_number')(row.get("close_position"))
    if close_position is None:
        close_position = ((last_close - low) / (high - low)) if can_compute and high != low else 0.5
    observed_rows = _v4_global(_v4_scope, '_optional_number')(row.get("bar_count"))
    expected_rows = _v4_global(_v4_scope, '_optional_number')(row.get("expected_rows"))
    complete_default = _v4_global(_v4_scope, 'bool')(
        observed_rows is not None and expected_rows is not None and observed_rows >= expected_rows
    )
    complete = _v4_global(_v4_scope, '_truthy')(row.get("complete"), complete_default)
    amount = _v4_global(_v4_scope, '_number')(_v4_global(_v4_scope, '_a_row_value')(row, "amount", "amount_in_window"))
    label, note = _v4_global(_v4_scope, 'a_stage_label')(window_change, close_position, complete)
    card = _v4_global(_v4_scope, '_stage_card_evidence')(
        row,
        code=code,
        open_price=first_open,
        last_price=last_close,
        high_price=high,
        low_price=low,
    )
    support = card["support"]
    pressure = card["pressure"]
    invalidation = card["invalidation"]
    return {
        "code": code,
        "score": _v4_global(_v4_scope, 'a_stage_score')(
            window_change_pct=window_change,
            close_position=close_position,
            amount=amount,
            complete=complete,
        ),
        "status": label,
        "formal_eligible": _v4_global(_v4_scope, '_truthy')(row.get("formal_eligible")),
        "support": support,
        "pressure": pressure,
        "invalidation": invalidation,
        "source_mode": source_mode,
        "lane_evidence": ["A_SHARE_FORMAL_POOL" if _v4_global(_v4_scope, '_truthy')(row.get("formal_eligible")) else "A_SHARE_STAGE_BARS"],
        "action_level": "WATCH_ONLY",
        "trade_status": "WATCH_ONLY",
        "note": note,
        "window_change_pct": _v4_global(_v4_scope, 'round')(window_change, 4),
        "close_position": _v4_global(_v4_scope, 'round')(close_position, 4),
        "complete": complete,
        **card,
    }


def __hk_continuation_passes_body(_v4_scope, /, row, stage_id, cap_limit_yi):
    stage_ids = [stage.stage_id for stage in _v4_global(_v4_scope, 'EIGHT_STAGES')]
    if stage_id not in stage_ids or stage_ids.index(stage_id) < stage_ids.index("STAGE_0940_0945"):
        return False
    lanes = _v4_global(_v4_scope, 'set')(row.get("candidate_lanes") or [])
    if not {"PREOPEN_AUCTION_CONTINUATION", "LIVE_HKCONNECT_GAINER"}.issubset(lanes):
        return False
    cap = _v4_global(_v4_scope, '_hk_float')(row, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
    if cap is not None and cap > _v4_global(_v4_scope, 'max')(cap_limit_yi, 150.0):
        return False
    pct = _v4_global(_v4_scope, '_hk_float')(row, "pct_chg")
    window = _v4_global(_v4_scope, '_hk_float')(row, "stage_window_change_pct", "window_change_pct")
    turnover = _v4_global(_v4_scope, '_hk_money_yi')(row)
    return ((pct is not None and pct >= 4) or (window is not None and window >= 3)) and turnover is not None and turnover >= 0.2
