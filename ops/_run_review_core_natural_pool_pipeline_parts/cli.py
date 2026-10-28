"""ops.run_review_core_natural_pool_pipeline: cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __as_text_path_body(_v4_scope, /, value, label):
    try:
        text = _v4_global(_v4_scope, 'os').fspath(value)
    except _v4_global(_v4_scope, 'TypeError') as error:
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} must be a filesystem path") from error
    if not _v4_global(_v4_scope, 'isinstance')(text, _v4_global(_v4_scope, 'str')) or not text.strip():
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} must be a non-empty absolute POSIX path")
    if "\\" in text:
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} rejects backslash paths")
    if _v4_global(_v4_scope, '_WINDOWS_DRIVE_RE').match(text) or text.startswith("//"):
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} rejects Windows/UNC paths")
    lowered = text.casefold()
    if _v4_global(_v4_scope, 'any')(marker in lowered for marker in _v4_global(_v4_scope, '_FORBIDDEN_PATH_MARKERS')):
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} rejects Desktop/Windows roots")
    path = _v4_global(_v4_scope, 'Path')(text).expanduser()
    if not path.is_absolute():
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} must be absolute")
    _v4_global(_v4_scope, '_reject_symlink_components')(path, label)
    try:
        return _v4_global(_v4_scope, 'str')(path.resolve(strict=False))
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} cannot be resolved") from error


def __reject_symlink_components_body(_v4_scope, /, path, label):
    """Reject leaf and ancestor symlinks before canonicalizing the path."""

    current = path
    while True:
        try:
            if current.is_symlink():
                raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} rejects symlink component: {current}")
        except _v4_global(_v4_scope, 'OSError') as error:
            raise _v4_global(_v4_scope, 'PathBoundaryError')(f"{label} symlink check failed: {current}") from error
        parent = current.parent
        if parent == current:
            return
        current = parent


def __read_calendar_body(_v4_scope, /, path):
    if not path.is_file():
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar is missing: {path}")
    try:
        raw = path.read_bytes()
        payload = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar is unreadable: {path}") from error
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar root must be an object")
    if not _v4_global(_v4_scope, 'isinstance')(payload.get("schema_version"), _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'str')(
        payload.get("schema_version")
    ).strip():
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar schema_version is missing")
    if _v4_global(_v4_scope, 'isinstance')(payload.get("year"), _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(payload.get("year"), _v4_global(_v4_scope, 'int')):
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar year is missing")
    if not _v4_global(_v4_scope, 'isinstance')(payload.get("timezone"), _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'str')(
        payload.get("timezone")
    ).strip():
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar timezone is missing")
    markets = payload.get("markets")
    if not _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar markets are missing")
    for market in ("a_share", "hk_connect_southbound"):
        if not _v4_global(_v4_scope, 'isinstance')(markets.get(market), _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar market is missing: {market}")
    for market, raw_config in markets.items():
        if not _v4_global(_v4_scope, 'isinstance')(raw_config, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar market is invalid: {market}")
        config = raw_config
        periods = config.get("holiday_periods", [])
        explicit = config.get("trading_dates", config.get("open_dates"))
        if periods is None:
            periods = []
        if not _v4_global(_v4_scope, 'isinstance')(periods, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar holiday periods are invalid: {market}")
        if explicit is not None and not _v4_global(_v4_scope, 'isinstance')(explicit, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar trading dates are invalid: {market}")
        if explicit is None and "holiday_periods" not in config:
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar dates are missing: {market}")
        for index, period in _v4_global(_v4_scope, 'enumerate')(periods):
            if not _v4_global(_v4_scope, 'isinstance')(period, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar holiday period is invalid: {market}[{index}]")
            start = _v4_global(_v4_scope, '_validate_date')(period.get("start"), f"{market}.holiday.start")
            end = _v4_global(_v4_scope, '_validate_date')(period.get("end"), f"{market}.holiday.end")
            if start > end:
                raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar holiday range is invalid: {market}")
        if explicit is not None:
            for index, item in _v4_global(_v4_scope, 'enumerate')(explicit):
                _v4_global(_v4_scope, '_validate_date')(item, f"{market}.trading_dates[{index}]")
        dependencies = config.get("derives_from", [])
        if dependencies is None:
            dependencies = []
        if not _v4_global(_v4_scope, 'isinstance')(dependencies, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar dependencies are invalid: {market}")
        for dependency in dependencies:
            if not _v4_global(_v4_scope, 'isinstance')(dependency, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'isinstance')(markets.get(dependency), _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar dependency is unknown: {market}->{dependency}")
    return _v4_global(_v4_scope, 'dict')(payload), _v4_global(_v4_scope, '_sha256_bytes')(raw)


def __market_open_body(_v4_scope, /, calendar, day, market, seen):
    markets = calendar.get("markets")
    config = markets.get(market) if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')) else None
    if not _v4_global(_v4_scope, 'isinstance')(config, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar market is missing: {market}")
    active = _v4_global(_v4_scope, 'set')(seen or ())
    if market in active:
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"calendar dependency cycle: {market}")
    active.add(market)
    value = _v4_global(_v4_scope, '_date')(day)
    explicit = config.get("trading_dates", config.get("open_dates"))
    if explicit is not None and day not in {_v4_global(_v4_scope, 'str')(item) for item in explicit}:
        return False
    if value.weekday() >= 5:
        return False
    periods = config.get("holiday_periods", [])
    for period in periods:
        start = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, '_validate_date')(period.get("start"), "holiday.start"))
        end = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, '_validate_date')(period.get("end"), "holiday.end"))
        if start <= value <= end:
            return False
    dependencies = config.get("derives_from", []) or []
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, '_market_open')(calendar, day, _v4_global(_v4_scope, 'str')(dependency), active) for dependency in dependencies):
        return False
    return True


def _resolve_adjacent_dates_body(_v4_scope, /, trade_date, calendar):
    """Return (previous HK-connect day, next A-share day)."""

    current = _v4_global(_v4_scope, '_date')(trade_date)
    previous = ""
    target = ""
    for offset in _v4_global(_v4_scope, 'range')(1, 3661):
        candidate = (current - _v4_global(_v4_scope, 'timedelta')(days=offset)).strftime("%Y%m%d")
        if _v4_global(_v4_scope, '_market_open')(calendar, candidate, "hk_connect_southbound"):
            previous = candidate
            break
    for offset in _v4_global(_v4_scope, 'range')(1, 3661):
        candidate = (current + _v4_global(_v4_scope, 'timedelta')(days=offset)).strftime("%Y%m%d")
        if _v4_global(_v4_scope, '_market_open')(calendar, candidate, "a_share"):
            target = candidate
            break
    if not previous or not target:
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar cannot prove adjacent trade dates")
    return previous, target


def _resolve_trade_dates_body(_v4_scope, /, trade_date, *, previous_trade_date, target_date, calendar_path):
    """Resolve and verify current, previous, and next dates from a calendar."""

    if trade_date is None:
        raise _v4_global(_v4_scope, 'CalendarValidationError')("trade_date is required")
    if calendar_path is None:
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar_path is required")
    calendar_file = _v4_global(_v4_scope, '_path')(calendar_path, "calendar_path")
    _v4_global(_v4_scope, '_require_calendar_root')(calendar_file, "calendar_path")
    trade = _v4_global(_v4_scope, '_validate_date')(trade_date, "trade_date")
    supplied_previous = (
        _v4_global(_v4_scope, '_validate_date')(previous_trade_date, "previous_trade_date")
        if previous_trade_date is not None
        else None
    )
    supplied_target = (
        _v4_global(_v4_scope, '_validate_date')(target_date, "target_date") if target_date is not None else None
    )
    calendar, digest = _v4_global(_v4_scope, '_read_calendar')(calendar_file)
    if not _v4_global(_v4_scope, '_market_open')(calendar, trade, "a_share"):
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"trade date is not open: {trade}")
    expected_previous, expected_target = _v4_global(_v4_scope, 'resolve_adjacent_dates')(trade, calendar)
    if supplied_previous is not None and supplied_previous != expected_previous:
        raise _v4_global(_v4_scope, 'CalendarValidationError')(
            f"previous_trade_date mismatch: {supplied_previous} != {expected_previous}"
        )
    if supplied_target is not None and supplied_target != expected_target:
        raise _v4_global(_v4_scope, 'CalendarValidationError')(
            f"target_date mismatch: {supplied_target} != {expected_target}"
        )
    previous = supplied_previous or expected_previous
    target = supplied_target or expected_target
    if not (previous < trade < target):
        raise _v4_global(_v4_scope, 'CalendarValidationError')("date order must be previous < trade < target")
    if not _v4_global(_v4_scope, '_market_open')(calendar, previous, "hk_connect_southbound"):
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"previous trade date is not open: {previous}")
    if not _v4_global(_v4_scope, '_market_open')(calendar, target, "a_share"):
        raise _v4_global(_v4_scope, 'CalendarValidationError')(f"target date is not open: {target}")
    return trade, previous, target, _v4_global(_v4_scope, 'str')(calendar_file), digest


def _validate_request_body(_v4_scope, /, *, trade_date, calendar_path, review_core_package_root, shared_package_root, shared_store_root, runtime_root, hk_root, close_root, fupan_store_root, stage7_store_root, bundle_root, previous_trade_date, target_date):
    """Validate all explicit CLI boundaries before importing Review Core."""

    calendar = _v4_global(_v4_scope, '_path')(calendar_path, "calendar_path")
    _v4_global(_v4_scope, '_require_calendar_root')(calendar, "calendar_path")
    trade, previous, target, calendar_text, calendar_sha = _v4_global(_v4_scope, 'resolve_trade_dates')(
        trade_date,
        previous_trade_date=previous_trade_date,
        target_date=target_date,
        calendar_path=calendar,
    )

    package = _v4_global(_v4_scope, '_path')(review_core_package_root, "review_core_package_root")
    _v4_global(_v4_scope, '_require_package_root')(package, "review_core_package_root")
    module_path = _v4_global(_v4_scope, '_package_module_path')(package)
    if not module_path.is_file():
        raise _v4_global(_v4_scope, 'PathBoundaryError')(f"official Review Core pool_pipeline is missing: {module_path}")
    try:
        if not _v4_global(_v4_scope, '_under')(module_path, package):
            raise _v4_global(_v4_scope, 'PathBoundaryError')("review_core pool_pipeline escapes package root")
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'PathBoundaryError')("review_core pool_pipeline cannot be resolved") from error

    shared_package = _v4_global(_v4_scope, '_path')(shared_package_root, "shared_package_root")
    _v4_global(_v4_scope, '_require_package_root')(shared_package, "shared_package_root")

    values = {
        "shared_store_root": _v4_global(_v4_scope, '_path')(shared_store_root, "shared_store_root"),
        "runtime_root": _v4_global(_v4_scope, '_path')(runtime_root, "runtime_root"),
        "hk_root": _v4_global(_v4_scope, '_path')(hk_root, "hk_root"),
        "close_root": _v4_global(_v4_scope, '_path')(close_root, "close_root"),
        "fupan_store_root": _v4_global(_v4_scope, '_path')(fupan_store_root, "fupan_store_root"),
        "stage7_store_root": _v4_global(_v4_scope, '_path')(stage7_store_root, "stage7_store_root"),
        "bundle_root": _v4_global(_v4_scope, '_path')(bundle_root, "bundle_root"),
    }
    for label, value in values.items():
        _v4_global(_v4_scope, '_require_write_root')(value, label)

    # resolve_trade_dates read the same canonical path after boundary
    # validation, so no unbounded calendar can influence the date contract.
    if _v4_global(_v4_scope, 'str')(calendar) != calendar_text:
        raise _v4_global(_v4_scope, 'CalendarValidationError')("calendar path changed during validation")

    return _v4_global(_v4_scope, 'PipelineRequest')(
        trade_date=trade,
        previous_trade_date=previous,
        target_date=target,
        calendar_path=calendar,
        calendar_sha256=calendar_sha,
        review_core_package_root=package,
        shared_package_root=shared_package,
        shared_store_root=values["shared_store_root"],
        runtime_root=values["runtime_root"],
        hk_root=values["hk_root"],
        close_root=values["close_root"],
        fupan_store_root=values["fupan_store_root"],
        stage7_store_root=values["stage7_store_root"],
        bundle_root=values["bundle_root"],
    )


def _build_command_body(_v4_scope, /, request, *, python_executable):
    """Build argv for the official module without shell interpolation."""

    executable = python_executable or _v4_global(_v4_scope, 'sys').executable
    return [
        executable,
        "-X",
        "utf8",
        "-m",
        "review_core.pool_pipeline",
        "--trade-date",
        request.trade_date,
        "--previous-trade-date",
        request.previous_trade_date,
        "--target-date",
        request.target_date,
        "--calendar-path",
        _v4_global(_v4_scope, 'str')(request.calendar_path),
        "--runtime-root",
        _v4_global(_v4_scope, 'str')(request.runtime_root),
        "--shared-root",
        _v4_global(_v4_scope, 'str')(request.shared_store_root),
        "--hk-root",
        _v4_global(_v4_scope, 'str')(request.hk_root),
        "--close-root",
        _v4_global(_v4_scope, 'str')(request.close_root),
        "--fupan-store-root",
        _v4_global(_v4_scope, 'str')(request.fupan_store_root),
        "--stage7-store-root",
        _v4_global(_v4_scope, 'str')(request.stage7_store_root),
        "--bundle-root",
        _v4_global(_v4_scope, 'str')(request.bundle_root),
        "--shared-store-root",
        _v4_global(_v4_scope, 'str')(request.shared_store_root),
    ]


def _build_environment_body(_v4_scope, /, request, *, base_env):
    """Bind package/store roots and remove inherited checkout import paths."""

    environment = _v4_global(_v4_scope, 'dict')(base_env if base_env is not None else _v4_global(_v4_scope, 'os').environ)
    environment["PYTHONPATH"] = _v4_global(_v4_scope, 'str')(request.review_core_package_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["V3_SHARED_DATA_PACKAGE_ROOT"] = _v4_global(_v4_scope, 'str')(request.shared_package_root)
    # STORE_ROOT is the explicit adapter contract; the V3_SHARED_DATA alias is
    # retained because the released Review Core readers consume it directly.
    environment["STORE_ROOT"] = _v4_global(_v4_scope, 'str')(request.shared_store_root)
    environment["V3_SHARED_DATA_STORE_ROOT"] = _v4_global(_v4_scope, 'str')(request.shared_store_root)
    return environment


def __has_provenance_body(_v4_scope, /, workload):
    nested = workload.get("provenance")
    for name in _v4_global(_v4_scope, 'PROVENANCE_FIELDS'):
        value = workload.get(name)
        if not _v4_global(_v4_scope, 'str')(value or "").strip() and _v4_global(_v4_scope, 'isinstance')(nested, _v4_global(_v4_scope, 'Mapping')):
            value = nested.get(name)
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value.strip():
            return False
    return True


def __base_envelope_body(_v4_scope, /, request):
    return {
        "schema": _v4_global(_v4_scope, 'ADAPTER_SCHEMA'),
        "schema_version": _v4_global(_v4_scope, 'ADAPTER_SCHEMA'),
        "role": _v4_global(_v4_scope, 'ADAPTER_ROLE'),
        "trade_date": request.trade_date,
        "previous_trade_date": request.previous_trade_date,
        "target_date": request.target_date,
        "calendar": {
            "path": _v4_global(_v4_scope, 'str')(request.calendar_path),
            "sha256": request.calendar_sha256,
        },
        "roots": {
            "review_core_package_root": _v4_global(_v4_scope, 'str')(request.review_core_package_root),
            "shared_package_root": _v4_global(_v4_scope, 'str')(request.shared_package_root),
            "shared_store_root": _v4_global(_v4_scope, 'str')(request.shared_store_root),
            "runtime_root": _v4_global(_v4_scope, 'str')(request.runtime_root),
            "hk_root": _v4_global(_v4_scope, 'str')(request.hk_root),
            "close_root": _v4_global(_v4_scope, 'str')(request.close_root),
            "fupan_store_root": _v4_global(_v4_scope, 'str')(request.fupan_store_root),
            "stage7_store_root": _v4_global(_v4_scope, 'str')(request.stage7_store_root),
            "bundle_root": _v4_global(_v4_scope, 'str')(request.bundle_root),
        },
        "run_id": "",
        "receipt_path": "",
        "status": "CANNOT_CONFIRM",
        "overall_status": "CANNOT_CONFIRM",
        "workloads": {},
        "errors": [],
        **{name: False for name in _v4_global(_v4_scope, 'SAFETY_FLAGS')},
    }


def __execution_metadata_body(_v4_scope, /, request, command, environment):
    return {
        "mode": "subprocess",
        "shell": False,
        "cwd": _v4_global(_v4_scope, 'str')(request.review_core_package_root),
        "command": _v4_global(_v4_scope, 'list')(command),
        "env": {
            "PYTHONPATH": environment["PYTHONPATH"],
            "V3_SHARED_DATA_PACKAGE_ROOT": environment["V3_SHARED_DATA_PACKAGE_ROOT"],
            "STORE_ROOT": environment["STORE_ROOT"],
            "V3_SHARED_DATA_STORE_ROOT": environment["V3_SHARED_DATA_STORE_ROOT"],
        },
    }


def __parser_body(_v4_scope, /):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(prog="run-review-core-natural-pool-pipeline")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--calendar-path", required=True)
    parser.add_argument("--review-core-package-root", required=True)
    parser.add_argument("--shared-package-root", required=True)
    parser.add_argument("--shared-store-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--hk-root", required=True)
    parser.add_argument("--close-root", required=True)
    parser.add_argument("--fupan-store-root", required=True)
    parser.add_argument("--stage7-store-root", required=True)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--previous-trade-date", required=False)
    parser.add_argument("--target-date", required=False)
    return parser


def __failure_envelope_body(_v4_scope, /, error):
    return {
        "schema": _v4_global(_v4_scope, 'ADAPTER_SCHEMA'),
        "schema_version": _v4_global(_v4_scope, 'ADAPTER_SCHEMA'),
        "role": _v4_global(_v4_scope, 'ADAPTER_ROLE'),
        "status": "CANNOT_CONFIRM",
        "overall_status": "CANNOT_CONFIRM",
        "exit_code": 2,
        "error": _v4_global(_v4_scope, '_error')(_v4_global(_v4_scope, 'type')(error).__name__, _v4_global(_v4_scope, 'str')(error) or _v4_global(_v4_scope, 'type')(error).__name__),
        "errors": [_v4_global(_v4_scope, '_error')(_v4_global(_v4_scope, 'type')(error).__name__, _v4_global(_v4_scope, 'str')(error) or _v4_global(_v4_scope, 'type')(error).__name__)],
        **{name: False for name in _v4_global(_v4_scope, 'SAFETY_FLAGS')},
    }


def _main_body(_v4_scope, /, argv):
    args = _v4_global(_v4_scope, '_parser')().parse_args(argv)
    try:
        request = _v4_global(_v4_scope, 'validate_request')(
            trade_date=args.trade_date,
            calendar_path=args.calendar_path,
            review_core_package_root=args.review_core_package_root,
            shared_package_root=args.shared_package_root,
            shared_store_root=args.shared_store_root,
            runtime_root=args.runtime_root,
            hk_root=args.hk_root,
            close_root=args.close_root,
            fupan_store_root=args.fupan_store_root,
            stage7_store_root=args.stage7_store_root,
            bundle_root=args.bundle_root,
            previous_trade_date=args.previous_trade_date,
            target_date=args.target_date,
        )
    except _v4_global(_v4_scope, 'AdapterError') as error:
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, '_failure_envelope')(error), ensure_ascii=False, sort_keys=True))
        return 2
    result = _v4_global(_v4_scope, 'run_pipeline')(request)
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
    return _v4_global(_v4_scope, 'int')(result.get("exit_code", 2))
