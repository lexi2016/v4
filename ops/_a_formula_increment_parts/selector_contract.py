"""ops.a_formula_increment: selector_contract (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _load_authoritative_contract_rows_body(_v4_scope, /, contract_csv):
    raw_path = _v4_global(_v4_scope, 'Path')(contract_csv).expanduser()
    if _v4_global(_v4_scope, '_path_has_symlink')(raw_path):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"contract csv has a symlinked parent: {raw_path}")
    path = _v4_global(_v4_scope, '_resolved')(contract_csv)
    if not path.is_file():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"contract csv missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in _v4_global(_v4_scope, 'csv').DictReader(handle) if row.get("column")]
    if _v4_global(_v4_scope, 'len')(rows) != 199:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"contract row count must be 199, got {_v4_global(_v4_scope, 'len')(rows)}")
    return rows


def _build_contract_policy_body(_v4_scope, /, rows, contract_csv):
    official = [row["column"] for row in rows if row.get("allowed_in_current") == "yes"]
    if _v4_global(_v4_scope, 'len')(official) != 187 or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(official)) != _v4_global(_v4_scope, 'len')(official):
        raise _v4_global(_v4_scope, 'AuthorityError')("contract official projection is not exactly 187 columns")
    sidecar = [row["column"] for row in rows if row.get("script_action") == "sidecar_only"]
    # The review contract has six explicit sidecar rows; aliases and lineage
    # rows are also retained in the auxiliary artifact, yielding the required 12.
    by_name = {row["column"]: row for row in rows}
    forced = [name for name in _v4_global(_v4_scope, 'SIDEcar_COLUMNS') if name in by_name]
    if _v4_global(_v4_scope, 'len')(forced) != 12:
        raise _v4_global(_v4_scope, 'AuthorityError')("contract auxiliary projection is not exactly 12 columns")
    versions = _v4_global(_v4_scope, 'sorted')({row.get("contract_version", "") for row in rows if row.get("contract_version")})
    return {
        "contract_csv": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_resolved')(contract_csv)),
        "rows": rows,
        "official_columns": official,
        "sidecar_columns": forced,
        "contract_version": versions[-1] if versions else "authoritative_field_contract_v0_2_phase1",
        "row_count": _v4_global(_v4_scope, 'len')(rows),
        "official_count": _v4_global(_v4_scope, 'len')(official),
        "sidecar_count": _v4_global(_v4_scope, 'len')(forced),
        "script_sidecar_columns": sidecar,
    }


def _validate_new_selector_rows_body(_v4_scope, /, frame, target_date, *, role):
    if frame.empty:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} candidate is empty")
    missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'KEY_COLUMNS') + ("open", "high", "low", "close")) - _v4_global(_v4_scope, 'set')(frame.columns))
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} candidate missing required columns: {','.join(missing)}")
    duplicate_rows = _v4_global(_v4_scope, 'int')(frame.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).sum())
    future_rows = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'pd').to_numeric(frame["trade_date"], errors="coerce").gt(target_date).sum())
    ohlc_bad = _v4_global(_v4_scope, 'int')((frame[["open", "high", "low", "close"]].apply(_v4_global(_v4_scope, 'pd').to_numeric, errors="coerce").le(0)).any(axis=1).sum())
    high_low_bad = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'pd').to_numeric(frame["high"], errors="coerce").lt(_v4_global(_v4_scope, 'pd').to_numeric(frame["low"], errors="coerce")).sum())
    close_outside = _v4_global(_v4_scope, 'int')((_v4_global(_v4_scope, 'pd').to_numeric(frame["close"], errors="coerce").gt(_v4_global(_v4_scope, 'pd').to_numeric(frame["high"], errors="coerce")) | _v4_global(_v4_scope, 'pd').to_numeric(frame["close"], errors="coerce").lt(_v4_global(_v4_scope, 'pd').to_numeric(frame["low"], errors="coerce"))).sum())
    if duplicate_rows or future_rows or ohlc_bad or high_low_bad or close_outside:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} candidate row gate failed: duplicate={duplicate_rows},future={future_rows},ohlc={ohlc_bad},range={high_low_bad},close={close_outside}")
    if not (_v4_global(_v4_scope, 'pd').to_numeric(frame["trade_date"], errors="coerce") == target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} candidate has no target-date rows")
    _v4_global(_v4_scope, '_validate_signal_fields')(frame)
    return {
        "status": "PASS",
        "role": role,
        "rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(frame)),
        "target_rows": _v4_global(_v4_scope, 'int')((frame["trade_date"] == target_date).sum()),
        "target_date": target_date,
        "duplicate_rows": duplicate_rows,
        "future_rows": future_rows,
        "ohlc_bad": ohlc_bad,
    }


def __validate_backtest_frame_body(_v4_scope, /, frame, target_date):
    if frame.empty:
        raise _v4_global(_v4_scope, 'AuthorityError')("backtest candidate is empty")
    missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'KEY_COLUMNS') + ("open", "high", "low", "close")) - _v4_global(_v4_scope, 'set')(frame.columns))
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"backtest candidate missing required columns: {','.join(missing)}")
    duplicate_rows = _v4_global(_v4_scope, 'int')(frame.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).sum())
    future_rows = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'pd').to_numeric(frame["trade_date"], errors="coerce").gt(target_date).sum())
    numeric = frame[["open", "high", "low", "close"]].apply(_v4_global(_v4_scope, 'pd').to_numeric, errors="coerce")
    range_bad = _v4_global(_v4_scope, 'int')((numeric.le(0)).any(axis=1).sum())
    range_bad += _v4_global(_v4_scope, 'int')(numeric["high"].lt(numeric["low"]).sum())
    range_bad += _v4_global(_v4_scope, 'int')((numeric["close"].gt(numeric["high"]) | numeric["close"].lt(numeric["low"])).sum())
    if duplicate_rows or future_rows or range_bad:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"backtest candidate row gate failed: duplicate={duplicate_rows},future={future_rows},range={range_bad}")
    if not (_v4_global(_v4_scope, 'pd').to_numeric(frame["trade_date"], errors="coerce") == target_date).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("backtest candidate has no target-date rows")
    return {"status": "PASS", "role": "backtest", "rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(frame)), "target_rows": _v4_global(_v4_scope, 'int')((frame["trade_date"] == target_date).sum()), "duplicate_rows": duplicate_rows, "future_rows": future_rows}
