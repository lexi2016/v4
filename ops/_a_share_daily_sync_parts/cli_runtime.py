"""ops.a_share_daily_sync: cli_runtime (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __atomic_write_bytes_body(_v4_scope, /, path, payload):
    """Atomically persist a small progress/receipt object in its parent."""
    _v4_global(_v4_scope, 'ensure_dir')(path.parent)
    fd, temporary_name = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = _v4_global(_v4_scope, 'Path')(temporary_name)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
        try:
            directory_fd = _v4_global(_v4_scope, 'os').open(_v4_global(_v4_scope, 'str')(path.parent), _v4_global(_v4_scope, 'os').O_RDONLY)
        except _v4_global(_v4_scope, 'OSError'):
            directory_fd = -1
        if directory_fd >= 0:
            try:
                _v4_global(_v4_scope, 'os').fsync(directory_fd)
            finally:
                _v4_global(_v4_scope, 'os').close(directory_fd)
    finally:
        if fd >= 0:
            _v4_global(_v4_scope, 'os').close(fd)
        try:
            temporary.unlink()
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass


def __file_sha256_body(_v4_scope, /, path):
    """Return the current regular-file identity without following symlinks."""
    try:
        if _v4_global(_v4_scope, '_local_path_failure')(path) is not None or not path.is_file():
            return None
        digest = _v4_global(_v4_scope, 'hashlib').sha256()
        with path.open("rb") as handle:
            for chunk in _v4_global(_v4_scope, 'iter')(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')):
        return None


def _discover_targets_body(_v4_scope, /, markets, tdx_root):
    targets: List[Tuple[str, int, str, Path, Optional[int]]] = []
    for market_name in markets:
        for prefix, template_dir in _v4_global(_v4_scope, 'DIR_BY_MARKET').get(market_name, []):
            directory = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(template_dir).replace(_v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'TDX_ROOT')), _v4_global(_v4_scope, 'str')(tdx_root)))
            if not directory.exists():
                continue
            for path in directory.glob(f"{prefix}*.day"):
                code = path.stem[_v4_global(_v4_scope, 'len')(prefix):]
                if _v4_global(_v4_scope, 'len')(code) != 6 or not code.isdigit():
                    continue
                if not code.startswith(_v4_global(_v4_scope, 'EQUITY_CODE_PREFIXES_BY_MARKET')[prefix]):
                    continue
                targets.append((prefix, _v4_global(_v4_scope, 'MARKET_BY_PREFIX')[prefix], code, path, _v4_global(_v4_scope, 'read_last_date')(path)))
    return targets


def __runtime_host_candidates_body(_v4_scope, /, preferred_host):
    candidates: list[tuple[str, int]] = []
    if preferred_host:
        host, _, port_text = _v4_global(_v4_scope, 'str')(preferred_host).partition(":")
        candidates.append((host, _v4_global(_v4_scope, 'int')(port_text or 7709)))
    for item in _v4_global(_v4_scope, 'hq_hosts'):
        if _v4_global(_v4_scope, 'len')(item) >= 3:
            _name, host, port = item[:3]
            candidates.append((_v4_global(_v4_scope, 'str')(host), _v4_global(_v4_scope, 'int')(port)))
        elif _v4_global(_v4_scope, 'len')(item) == 2:
            host, port = item
            candidates.append((_v4_global(_v4_scope, 'str')(host), _v4_global(_v4_scope, 'int')(port)))
    return _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(candidates))


def _run_body(_v4_scope, /, args):
    """Run the bounded sync and persist a truthful summary."""

    _v4_global(_v4_scope, 'ensure_dir')(_v4_global(_v4_scope, 'RUN_DIR'))
    markets = [x.strip().lower() for x in args.markets.split(",") if x.strip()]
    discovered = _v4_global(_v4_scope, 'discover_targets')(markets, args.tdx_root)
    if args.limit:
        discovered = discovered[: args.limit]
    targets = [
        _v4_global(_v4_scope, 'DailyTarget')(code=code, market=market, path=path)
        for _prefix, market, code, path, _last_date in discovered
    ]
    target_date = _v4_global(_v4_scope, 'getattr')(args, "target_date", None)
    if not target_date:
        raise _v4_global(_v4_scope, 'ValueError')("tdx daily sync requires an exact target_date")
    result = _v4_global(_v4_scope, 'run_sync')(
        targets,
        target_date=_v4_global(_v4_scope, 'str')(target_date),
        api_factory=_v4_global(_v4_scope, '_runtime_api_factory'),
        host_candidates=_v4_global(_v4_scope, '_runtime_host_candidates')(_v4_global(_v4_scope, 'getattr')(args, "host", None)),
        count=args.count,
        timeout=args.timeout,
        dry_run=_v4_global(_v4_scope, 'bool')(args.dry_run),
        request_deadline_seconds=_v4_global(_v4_scope, 'getattr')(args, "request_deadline_seconds", _v4_global(_v4_scope, 'DEFAULT_REQUEST_DEADLINE_SECONDS')),
        symbol_budget_seconds=_v4_global(_v4_scope, 'getattr')(args, "symbol_budget_seconds", _v4_global(_v4_scope, 'DEFAULT_SYMBOL_BUDGET_SECONDS')),
        run_budget_seconds=_v4_global(_v4_scope, 'getattr')(args, "run_budget_seconds", _v4_global(_v4_scope, 'DEFAULT_RUN_BUDGET_SECONDS')),
        progress_path=_v4_global(_v4_scope, 'getattr')(args, "progress_path", None),
        trusted_cas_inputs=_v4_global(_v4_scope, 'getattr')(args, "trusted_cas_inputs", None),
    )
    result.update(
        {
            "run_dir": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'RUN_DIR')),
            "tdx_root": _v4_global(_v4_scope, 'str')(args.tdx_root),
            "markets": markets,
            "dry_run": _v4_global(_v4_scope, 'bool')(args.dry_run),
            "count": args.count,
            "note": "This sync updates SH/SZ/BJ vipdoc daily files only. HK extended market ExHQ is not written by this script.",
        }
    )
    _v4_global(_v4_scope, 'write_csv')(_v4_global(_v4_scope, 'RUN_DIR') / "file_results.csv", _v4_global(_v4_scope, 'list')(result["by_symbol"].values()))
    _v4_global(_v4_scope, 'write_json')(_v4_global(_v4_scope, 'RUN_DIR') / "summary.json", result)
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, indent=2, default=_v4_global(_v4_scope, 'str')), flush=True)
    return result


def _parse_args_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Sync latest SH/SZ/BJ daily bars from pytdx into local TDX vipdoc .day files.")
    parser.add_argument("--tdx-root", type=_v4_global(_v4_scope, 'Path'), default=_v4_global(_v4_scope, 'TDX_ROOT'))
    parser.add_argument("--target-date", required=True, help="Exact YYYYMMDD target required for a truthful sync.")
    parser.add_argument("--markets", default="a,bj", help="Comma separated: a,bj. HK extended market is intentionally not supported here.")
    parser.add_argument("--count", type=_v4_global(_v4_scope, 'int'), default=20, help="Latest bars to request per symbol.")
    parser.add_argument("--host", default=None, help="Optional host:port override.")
    parser.add_argument("--timeout", type=_v4_global(_v4_scope, 'float'), default=1.5)
    parser.add_argument("--sleep", type=_v4_global(_v4_scope, 'float'), default=0.0)
    parser.add_argument("--limit", type=_v4_global(_v4_scope, 'int'), default=0)
    parser.add_argument("--progress-every", type=_v4_global(_v4_scope, 'int'), default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--request-deadline-seconds",
        type=_v4_global(_v4_scope, 'float'),
        default=_v4_global(_v4_scope, 'DEFAULT_REQUEST_DEADLINE_SECONDS'),
        help="Whole SDK request wall-clock deadline, including response-body reads.",
    )
    parser.add_argument(
        "--symbol-budget-seconds",
        type=_v4_global(_v4_scope, 'float'),
        default=_v4_global(_v4_scope, 'DEFAULT_SYMBOL_BUDGET_SECONDS'),
        help="Cumulative wall-clock budget for one symbol across endpoint attempts.",
    )
    parser.add_argument(
        "--run-budget-seconds",
        type=_v4_global(_v4_scope, 'float'),
        default=_v4_global(_v4_scope, 'DEFAULT_RUN_BUDGET_SECONDS'),
        help="Overall A-sync wall-clock budget below the outer executor timeout.",
    )
    parser.add_argument(
        "--progress-path",
        type=_v4_global(_v4_scope, 'Path'),
        default=None,
        help="Optional date-bound atomic progress receipt path.",
    )
    parser.add_argument(
        "--trusted-cas-inputs",
        type=_v4_global(_v4_scope, 'Path'),
        default=None,
        help="Optional receipt-bound reviewed CAS references; exact target-date only.",
    )
    return parser.parse_args(_v4_global(_v4_scope, 'list')(argv) if argv is not None else None)
