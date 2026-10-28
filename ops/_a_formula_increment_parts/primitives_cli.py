"""ops.a_formula_increment: primitives_cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __jsonable_body(_v4_scope, /, value):
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'Path'),)):
        return _v4_global(_v4_scope, 'str')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'np').integer,)):
        return _v4_global(_v4_scope, 'int')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'np').floating,)):
        return _v4_global(_v4_scope, 'float')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'np').bool_,)):
        return _v4_global(_v4_scope, 'bool')(value)
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'pd').Timestamp,)):
        return value.isoformat()
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'dict')):
        return {_v4_global(_v4_scope, 'str')(k): _v4_global(_v4_scope, '_jsonable')(v) for k, v in value.items()}
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))):
        return [_v4_global(_v4_scope, '_jsonable')(v) for v in value]
    return value


def __path_has_symlink_body(_v4_scope, /, path, *, stop):
    path = _v4_global(_v4_scope, 'Path')(path).expanduser()
    stop = _v4_global(_v4_scope, 'Path')(stop).expanduser() if stop else None
    current = path if path.exists() else path.parent
    while True:
        if current.is_symlink():
            return True
        if stop is not None and current == stop:
            break
        if current.parent == current:
            break
        current = current.parent
    return False


def __safe_output_root_body(_v4_scope, /, data_root, return_root, selector_pointer, backtest_pointer):
    raw_values = {
        "data_root": _v4_global(_v4_scope, 'Path')(data_root).expanduser(),
        "return_root": _v4_global(_v4_scope, 'Path')(return_root).expanduser(),
        "selector_pointer": _v4_global(_v4_scope, 'Path')(selector_pointer).expanduser(),
        "backtest_pointer": _v4_global(_v4_scope, 'Path')(backtest_pointer).expanduser(),
    }
    for label, raw in raw_values.items():
        if _v4_global(_v4_scope, '_path_has_symlink')(raw):
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{label} has a symlinked parent")
    data_root = _v4_global(_v4_scope, '_resolved')(data_root)
    return_root = _v4_global(_v4_scope, '_resolved')(return_root)
    selector_pointer = _v4_global(_v4_scope, '_resolved')(selector_pointer)
    backtest_pointer = _v4_global(_v4_scope, '_resolved')(backtest_pointer)
    output_root = return_root.parent
    if not output_root.is_absolute():
        raise _v4_global(_v4_scope, 'AuthorityError')("offline output root must be absolute")
    for label, value in (("data_root", data_root), ("return_root", return_root), ("selector_pointer", selector_pointer), ("backtest_pointer", backtest_pointer)):
        _v4_global(_v4_scope, '_reject_formal_root')(value, label)
        if not _v4_global(_v4_scope, '_within')(value, output_root):
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{label} must be under one isolated output root: {value}")
        if _v4_global(_v4_scope, '_path_has_symlink')(value, stop=output_root):
            raise _v4_global(_v4_scope, 'AuthorityError')(f"{label} has a symlinked parent")
    if output_root == data_root or output_root == return_root:
        raise _v4_global(_v4_scope, 'AuthorityError')("offline output root must contain separate output subdirectories")
    output_root.mkdir(parents=True, exist_ok=True)
    if _v4_global(_v4_scope, '_path_has_symlink')(output_root):
        raise _v4_global(_v4_scope, 'AuthorityError')("isolated output root is symlinked")
    return output_root


def __normalize_date_series_body(_v4_scope, /, series):
    raw = series.astype(_v4_global(_v4_scope, 'str')).str.strip()
    compact = raw.where(
        raw.str.fullmatch(r"\d{8}"),
        raw.where(raw.str.fullmatch(r"\d{4}-\d{2}-\d{2}")).str.replace("-", "", regex=False),
    )
    if compact.isna().any() or compact.str.fullmatch(r"\d{8}").eq(False).any():
        raise _v4_global(_v4_scope, 'AuthorityError')("trade_date contains invalid values")
    parsed = _v4_global(_v4_scope, 'pd').to_datetime(compact, format="%Y%m%d", errors="coerce")
    if parsed.isna().any():
        raise _v4_global(_v4_scope, 'AuthorityError')("trade_date contains invalid values")
    return _v4_global(_v4_scope, 'pd').to_numeric(compact, errors="raise").astype("int64")


def __read_seed_body(_v4_scope, /, path, role):
    raw_path = _v4_global(_v4_scope, 'Path')(path).expanduser()
    if _v4_global(_v4_scope, '_path_has_symlink')(raw_path):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed has a symlinked parent: {raw_path}")
    candidate = _v4_global(_v4_scope, '_resolved')(path)
    if not candidate.is_file():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed missing or not regular: {candidate}")
    if candidate.suffix.lower() != ".parquet":
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed must be parquet: {candidate}")
    try:
        frame = _v4_global(_v4_scope, 'pd').read_parquet(candidate)
    except _v4_global(_v4_scope, 'Exception') as error:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed unreadable: {candidate}") from error
    missing = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'KEY_COLUMNS')) - _v4_global(_v4_scope, 'set')(frame.columns))
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed missing key columns: {','.join(missing)}")
    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype(_v4_global(_v4_scope, 'str'))
    frame["trade_date"] = _v4_global(_v4_scope, '_normalize_date_series')(frame["trade_date"])
    if frame.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} seed has duplicate keys")
    return frame.sort_values(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS')), kind="mergesort").reset_index(drop=True)


def __audit_increment_boundary_body(_v4_scope, /, current, increment):
    if increment.empty:
        return {"status": "PASS", "rows": 0, "future_rows": 0, "duplicate_rows": 0, "bad_symbols": []}
    if increment.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).any():
        return {"status": "FAIL", "rows": _v4_global(_v4_scope, 'len')(increment), "future_rows": 0, "duplicate_rows": _v4_global(_v4_scope, 'int')(increment.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).sum()), "bad_symbols": []}
    future_rows = 0
    bad_symbols: list[str] = []
    if not current.empty:
        latest = current.groupby("ts_code", sort=False)["trade_date"].max().to_dict()
        for code, group in increment.groupby("ts_code", sort=False):
            if _v4_global(_v4_scope, 'int')(group["trade_date"].min()) <= _v4_global(_v4_scope, 'int')(latest.get(code, 0)):
                bad_symbols.append(_v4_global(_v4_scope, 'str')(code))
    result = {
        "status": "PASS" if not bad_symbols else "FAIL",
        "rows": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'len')(increment)),
        "future_rows": _v4_global(_v4_scope, 'int')(future_rows),
        "duplicate_rows": _v4_global(_v4_scope, 'int')(increment.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).sum()),
        "bad_symbols": _v4_global(_v4_scope, 'sorted')(bad_symbols),
    }
    return result


def __append_rows_body(_v4_scope, /, current, increment, *, role):
    if increment.empty:
        return current.copy()
    columns = _v4_global(_v4_scope, 'list')(current.columns)
    missing = [column for column in columns if column not in increment.columns]
    if missing:
        # Explicit aliases are part of the reviewed daily source schema.
        increment = increment.copy()
        if "vol" in missing and "volume" in increment.columns:
            increment["vol"] = increment["volume"]
        if "turnover" in missing and "amount" in increment.columns:
            increment["turnover"] = increment["amount"]
        missing = [column for column in columns if column not in increment.columns]
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} increment cannot preserve schema columns: {','.join(missing)}")
    extra = [column for column in increment.columns if column not in columns]
    combined = _v4_global(_v4_scope, 'pd').concat([current, increment.loc[:, columns + extra]], ignore_index=True, sort=False)
    if combined.duplicated(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))).any():
        raise _v4_global(_v4_scope, 'AuthorityError')(f"{role} append produced duplicate keys")
    return combined.sort_values(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS')), kind="mergesort").reset_index(drop=True)


def __generation_payload_body(_v4_scope, /, output_root, selector_target, backtest_target, generation_metadata):
    selector = _v4_global(_v4_scope, '_generation_target_metadata')(selector_target, output_root, "selector")
    backtest = _v4_global(_v4_scope, '_generation_target_metadata')(backtest_target, output_root, "backtest")
    if selector["path"] == backtest["path"]:
        raise _v4_global(_v4_scope, 'AuthorityError')("selector/backtest targets must differ")
    identity = {"selector": selector, "backtest": backtest}
    payload = {
        "schema": _v4_global(_v4_scope, 'FORMULA_GENERATION_SCHEMA'),
        "status": "READY",
        "generation_id": _v4_global(_v4_scope, '_sha256_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(identity)),
        "selector": selector,
        "backtest": backtest,
    }
    # The selector/backtest pair remains the stable generation identity.  The
    # optional fields bind that pair to the exact input/source/sidecar used by
    # the V4 runner without changing the legacy identity or its projections.
    if generation_metadata is not None:
        if not _v4_global(_v4_scope, 'isinstance')(generation_metadata, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'AuthorityError')("generation metadata must be an object")
        payload.update(_v4_global(_v4_scope, '_jsonable')(_v4_global(_v4_scope, 'dict')(generation_metadata)))
    return (_v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"), payload


def __parser_body(_v4_scope, /):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="V4 A formula increment authority; explicit offline input only")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--input-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--input-manifest", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--data-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--return-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--selector-pointer", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--backtest-pointer", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--selector-seed", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--backtest-seed", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--contract-csv", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--legacy-formula-source", default="")
    return parser


def _main_body(_v4_scope, /, argv):
    args = _v4_global(_v4_scope, '_parser')().parse_args(argv)
    outcome = _v4_global(_v4_scope, 'run_increment_authority')(
        target_date=args.target_date,
        input_root=args.input_root,
        input_manifest=args.input_manifest,
        data_root=args.data_root,
        return_root=args.return_root,
        selector_pointer=args.selector_pointer,
        backtest_pointer=args.backtest_pointer,
        selector_seed=args.selector_seed,
        backtest_seed=args.backtest_seed,
        contract_csv=args.contract_csv,
        legacy_formula_source=args.legacy_formula_source,
    )
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, '_jsonable')(outcome), ensure_ascii=False, sort_keys=True))
    return 0 if outcome.get("status") == "READY" else 2
