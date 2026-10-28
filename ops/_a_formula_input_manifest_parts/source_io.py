"""ops.a_formula_input_manifest: source_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __ensure_distinct_roots_body(_v4_scope, /, tdx_root, output_root):
    if output_root == tdx_root or _v4_global(_v4_scope, '_inside')(tdx_root, output_root) or _v4_global(_v4_scope, '_inside')(output_root, tdx_root):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root must be separate from the TDX source root")
    # A V4 candidate must never write into an immutable release or formal
    # Application Support tree.  This is a path guard, not an assertion that
    # the caller's entire environment has been inventoried.
    output_text = _v4_global(_v4_scope, 'str')(output_root)
    if (
        ("/Library/Application Support/" in output_text or "/releases/" in output_text)
        and not (
            _v4_global(_v4_scope, 'is_v4_formula_state_path')(tdx_root)
            and _v4_global(_v4_scope, 'is_v4_formula_state_path')(output_root)
        )
    ):
        raise _v4_global(_v4_scope, 'InputManifestError')("input output root cannot target formal release/Application Support")


def __read_sync_receipt_body(_v4_scope, /, path, target_date):
    receipt_path = _v4_global(_v4_scope, '_resolved_regular')(path, "sync receipt")
    try:
        raw = receipt_path.read_bytes()
        payload = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt is unreadable") from error
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt must be an object")
    if _v4_global(_v4_scope, 'str')(payload.get("status", "")).upper() not in {"READY", "PASS"}:
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt is not READY")
    if _v4_global(_v4_scope, '_date')(payload.get("target_date"), "sync receipt target_date") != target_date:
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt target_date mismatch")
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(flag) is not False:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync receipt safety flag is not false: {flag}")
    files = payload.get("files")
    if not _v4_global(_v4_scope, 'isinstance')(files, _v4_global(_v4_scope, 'list')) or not files:
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt has no explicit files")
    return payload, raw, _v4_global(_v4_scope, '_sha256_bytes')(raw)


def __receipt_files_body(_v4_scope, /, payload, *, tdx_root, target_date):
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    admitted: list[tuple[str, str, Path]] = []
    for raw_value in payload.get("files", []):
        if not _v4_global(_v4_scope, 'isinstance')(raw_value, _v4_global(_v4_scope, 'str')) or "\x00" in raw_value or "\\" in raw_value:
            raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt file path is unsafe")
        raw_path = _v4_global(_v4_scope, 'Path')(raw_value).expanduser()
        path = _v4_global(_v4_scope, '_resolved_regular')(raw_path, "sync source file")
        if not _v4_global(_v4_scope, '_inside')(tdx_root, path):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source file escapes TDX root: {path}")
        relative = path.relative_to(tdx_root).as_posix()
        if not _v4_global(_v4_scope, '_DAY_PATH').fullmatch(relative):
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source path is not a canonical vipdoc day file: {relative}")
        if relative in seen:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source file is duplicated: {relative}")
        seen.add(relative)
        rows = _v4_global(_v4_scope, 'read_hq_day_bars')(path)
        if path.stat().st_size == 0 or path.stat().st_size % _v4_global(_v4_scope, 'DAY_STRUCT').size:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source file has invalid .day byte size: {relative}")
        if not rows:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source file is empty: {relative}")
        previous = 0
        target_seen = False
        for row in rows:
            ok, reason = _v4_global(_v4_scope, 'valid_hq_bar')(row)
            if not ok:
                raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source bar invalid ({relative}): {reason}")
            row_date = _v4_global(_v4_scope, 'int')(row["year"]) * 10000 + _v4_global(_v4_scope, 'int')(row["month"]) * 100 + _v4_global(_v4_scope, 'int')(row["day"])
            _v4_global(_v4_scope, '_date')(row_date, f"sync source {relative} bar")
            if row_date <= previous:
                raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source dates are not strictly increasing: {relative}")
            if row_date > _v4_global(_v4_scope, 'int')(target_date):
                raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source contains future bar: {relative}:{row_date}")
            previous = row_date
            target_seen = target_seen or row_date == _v4_global(_v4_scope, 'int')(target_date)
        if not target_seen:
            raise _v4_global(_v4_scope, 'InputManifestError')(f"sync source has no exact target-date row: {relative}")
        market = relative.split("/", 2)[1]
        code = _v4_global(_v4_scope, 'Path')(relative).stem[_v4_global(_v4_scope, 'len')(market):]
        admitted.append((relative, market, path))
    if not admitted:
        raise _v4_global(_v4_scope, 'InputManifestError')("sync receipt admitted no source files")
    return _v4_global(_v4_scope, 'sorted')(admitted)


def __frame_for_day_file_body(_v4_scope, /, path, relative, market, target_date):
    code = _v4_global(_v4_scope, 'Path')(relative).stem[_v4_global(_v4_scope, 'len')(market):]
    exchange = _v4_global(_v4_scope, '_MARKET_CODES')[market]
    records: list[dict[str, Any]] = []
    for row in _v4_global(_v4_scope, 'read_hq_day_bars')(path):
        row_date = _v4_global(_v4_scope, 'int')(row["year"]) * 10000 + _v4_global(_v4_scope, 'int')(row["month"]) * 100 + _v4_global(_v4_scope, 'int')(row["day"])
        records.append(
            {
                "ts_code": f"{code}.{exchange}",
                "trade_date": row_date,
                "raw_code": code,
                "exchange": exchange,
                "market_type": "A",
                "name": "tdx-day",
                "open": _v4_global(_v4_scope, 'float')(row["open"]),
                "high": _v4_global(_v4_scope, 'float')(row["high"]),
                "low": _v4_global(_v4_scope, 'float')(row["low"]),
                "close": _v4_global(_v4_scope, 'float')(row["close"]),
                "volume": _v4_global(_v4_scope, 'float')(row["vol"]),
                "amount": _v4_global(_v4_scope, 'float')(row["amount"]),
            }
        )
    frame = _v4_global(_v4_scope, 'pd').DataFrame.from_records(records)
    if frame.empty or not (frame["trade_date"] == _v4_global(_v4_scope, 'int')(target_date)).any():
        raise _v4_global(_v4_scope, 'InputManifestError')(f"decoded source has no target row: {relative}")
    return frame


def __write_parquet_body(_v4_scope, /, frame, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise _v4_global(_v4_scope, 'InputManifestError')(f"refusing to overwrite input artifact: {destination}")
    with _v4_global(_v4_scope, 'tempfile').NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as handle:
        temporary = _v4_global(_v4_scope, 'Path')(handle.name)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        with temporary.open("rb") as handle:
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass
    return _v4_global(_v4_scope, 'len')(frame), _v4_global(_v4_scope, '_sha256_file')(destination)


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description=_v4_global(_v4_scope, '__doc__'))
    parser.add_argument("--sync-receipt", required=False, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument(
        "--accepted-only-manifest",
        required=False,
        type=_v4_global(_v4_scope, 'Path'),
        help="Explicit v3.5 accepted-only .day manifest; preserves REBUILD_REQUIRED provenance.",
    )
    parser.add_argument(
        "--accepted-only-copy-receipt",
        required=False,
        type=_v4_global(_v4_scope, 'Path'),
        help="Receipt binding the accepted-only manifest to its isolated copied root.",
    )
    parser.add_argument(
        "--accepted-only-path",
        action="append",
        default=None,
        help="Canonical accepted-only relative path to include; repeat for a bounded subset canary.",
    )
    parser.add_argument("--tdx-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--output-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    try:
        accepted_mode = args.accepted_only_manifest is not None or args.accepted_only_copy_receipt is not None
        if accepted_mode:
            if args.sync_receipt is not None:
                raise _v4_global(_v4_scope, 'InputManifestError')("sync and accepted-only input modes are mutually exclusive")
            if args.accepted_only_manifest is None or args.accepted_only_copy_receipt is None:
                raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only manifest and copy receipt are both required")
            result = _v4_global(_v4_scope, 'build_accepted_only_a_formula_input_manifest')(
                accepted_manifest=args.accepted_only_manifest,
                copy_receipt=args.accepted_only_copy_receipt,
                tdx_root=args.tdx_root,
                output_root=args.output_root,
                target_date=args.target_date,
                run_id=args.run_id,
                selected_relative_paths=args.accepted_only_path,
            )
        else:
            if args.accepted_only_path:
                raise _v4_global(_v4_scope, 'InputManifestError')("accepted-only paths require accepted-only input mode")
            if args.sync_receipt is None:
                raise _v4_global(_v4_scope, 'InputManifestError')("one input mode is required")
            result = _v4_global(_v4_scope, 'build_a_formula_input_manifest')(
                sync_receipt=args.sync_receipt,
                tdx_root=args.tdx_root,
                output_root=args.output_root,
                target_date=args.target_date,
                run_id=args.run_id,
            )
    except _v4_global(_v4_scope, 'Exception') as error:
        result = {
            "status": "FAILED",
            "error_type": _v4_global(_v4_scope, 'type')(error).__name__,
            "error": _v4_global(_v4_scope, 'str')(error),
            "network": "NOT_USED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
