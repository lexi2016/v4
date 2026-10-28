"""ops.a_formula_increment: feature_computation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __normalize_input_frame_body(_v4_scope, /, frame, target_date):
    work = frame.copy()
    if "volume" not in work.columns and "vol" in work.columns:
        work["volume"] = work["vol"]
    if "amount" not in work.columns and "turnover" in work.columns:
        work["amount"] = work["turnover"]
    missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'BASE_COLUMNS')) - _v4_global(_v4_scope, 'set')(work.columns))
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"offline input missing base columns: {','.join(missing)}")
    work["ts_code"] = work["ts_code"].astype(_v4_global(_v4_scope, 'str')).str.strip()
    if work["ts_code"].eq("").any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input contains blank ts_code")
    work["trade_date"] = _v4_global(_v4_scope, '_normalize_date_series')(work["trade_date"])
    if work["trade_date"].gt(target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input contains future rows")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        work[column] = _v4_global(_v4_scope, 'pd').to_numeric(work[column], errors="coerce")
    if work[_v4_global(_v4_scope, 'list')(("open", "high", "low", "close"))].isna().any().any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input contains nonnumeric OHLC")
    if (work[["open", "high", "low", "close"]] <= 0).any().any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input contains nonpositive OHLC")
    if work["high"].lt(work["low"]).any() or work["close"].gt(work["high"]).any() or work["close"].lt(work["low"]).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input contains structurally invalid OHLC")
    duplicate_count = _v4_global(_v4_scope, 'int')(work.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).sum())
    if duplicate_count:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"offline input duplicate key rows: {duplicate_count}")
    work = work.sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)
    if not (work.groupby("ts_code", sort=False)["trade_date"].diff().dropna() > 0).all():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input dates are not strictly increasing per symbol")
    if not (work["trade_date"] == target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline input has no target-date row")
    return work


def __backfill_increment_contract_columns_body(_v4_scope, /, features, *current_frames):
    """Carry stable source/contract columns from the reviewed seed rows.

    The live ``.day`` adapter intentionally contains only market bars.  The
    existing selector/backtest seeds remain the authority for stable metadata
    (exchange, source, panel constants, and similar contract columns); formula
    values computed for the new rows are never replaced.  A symbol with no
    seed metadata fails closed instead of receiving a guessed default.
    """

    work = features.copy()
    if "ts_code" not in work.columns:
        raise _v4_global(_v4_scope, 'AuthorityError')("formula features are missing ts_code")
    keys = work["ts_code"].astype(_v4_global(_v4_scope, 'str'))
    for current in current_frames:
        if current is None or current.empty or "ts_code" not in current.columns:
            continue
        ordered = current.sort_values(["ts_code", "trade_date"], kind="mergesort")
        latest = ordered.groupby("ts_code", sort=False).tail(1).set_index("ts_code")
        for column in current.columns:
            if column in work.columns or column in _v4_global(_v4_scope, 'KEY_COLUMNS'):
                continue
            work[column] = keys.map(latest[column])
    return work


def _compute_formula_features_body(_v4_scope, /, history):
    """Compute the reviewed formula once through the V4 pure authority."""
    if history.empty:
        raise _v4_global(_v4_scope, 'AuthorityError')("formula history is empty")
    input_keys = history[_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].astype(_v4_global(_v4_scope, 'str')).reset_index(drop=True)
    try:
        computed = _v4_global(_v4_scope, 'a_formula_authority').compute_partition_formula(history.copy()).reset_index(drop=True)
    except _v4_global(_v4_scope, 'Exception') as error:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"formula computation failed: {_v4_global(_v4_scope, 'type')(error).__name__}: {error}") from error
    if _v4_global(_v4_scope, 'len')(computed) != _v4_global(_v4_scope, 'len')(history):
        raise _v4_global(_v4_scope, 'AuthorityError')("formula row count changed")
    output_keys = computed[_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].astype(_v4_global(_v4_scope, 'str')).reset_index(drop=True)
    if not input_keys.equals(output_keys):
        raise _v4_global(_v4_scope, 'AuthorityError')("formula changed key order")
    computed["primary_buy_signal"] = (
        computed.get("brick_buy2_attack", 0).eq(1)
        | computed.get("B3", 0).eq(1)
        | computed.get("double_breakout", 0).eq(1)
    ).astype(_v4_global(_v4_scope, 'np').int8)
    computed["secondary_buy_signal"] = (
        computed.get("brick_buy1_low_absorb", 0).eq(1)
        | computed.get("B2", 0).eq(1)
        | computed.get("breakout_cross_star", 0).eq(1)
    ).astype(_v4_global(_v4_scope, 'np').int8)
    computed["formula_source"] = _v4_global(_v4_scope, 'FORMULA_SOURCE')
    return computed
