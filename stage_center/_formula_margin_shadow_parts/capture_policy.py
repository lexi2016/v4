"""stage_center.formula_margin_shadow: capture_policy (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __admission_mode_body(_v4_scope, /, value, *, default):
    """Return the explicit truth/capture admission mode.

    The default is intentionally the engineering mode for the in-memory
    shadow builder.  A caller that wants a forward or truth admission must
    state ``REAL_AUTHORITY`` explicitly; that mode is still fail-closed until
    the existing owner membership and final-close contracts are available.
    """

    raw = value.get("admission_mode", value.get("truth_admission_mode")) if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) else None
    if raw in (None, ""):
        if default is None:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("admission_mode is required")
        raw = default
    mode = _v4_global(_v4_scope, 'str')(raw).strip().upper()
    if mode not in _v4_global(_v4_scope, 'ADMISSION_MODES'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"admission_mode must be one of {_v4_global(_v4_scope, 'ADMISSION_MODES')}")
    return mode


def __validate_runtime_capture_timestamp_body(_v4_scope, /, value, trade_date, stage_id):
    """Validate a runtime timestamp against the exact Shanghai stage window."""

    parsed = value if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'datetime')) else _v4_global(_v4_scope, '_parse_timestamp')(value, trade_date, "runtime captured_at")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
    parsed = parsed.astimezone(_v4_global(_v4_scope, 'SHANGHAI'))
    if parsed.strftime("%Y%m%d") != _v4_global(_v4_scope, '_exact_date')(trade_date, "trade_date"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("runtime capture date does not match trade_date")
    window = _v4_global(_v4_scope, 'STAGE_CAPTURE_WINDOWS').get(stage_id)
    if window is None:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"stage must be one of {_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'STAGE_CAPTURE_WINDOWS'))}")
    local_time = parsed.time().replace(tzinfo=None)
    start = _v4_global(_v4_scope, 'time').fromisoformat(window[0])
    end = _v4_global(_v4_scope, 'time').fromisoformat(window[1])
    if local_time < start:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"runtime capture is before {stage_id} window")
    if local_time > end:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"runtime capture is after {stage_id} cutoff")
    return parsed


def _canonical_json_body(_v4_scope, /, value):
    """Return the hash/signature encoding used by every immutable artifact."""

    return (
        _v4_global(_v4_scope, 'json').dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def __parse_timestamp_body(_v4_scope, /, value, trade_date, label):
    """Parse an explicit Shanghai timestamp; a time-only value uses the date."""

    text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if not text:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} is missing")
    if _v4_global(_v4_scope, 'len')(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}T00:00:00"
    elif _v4_global(_v4_scope, 'len')(text) <= 8 and text.count(":") in (1, 2):
        text = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{text}"
    else:
        text = text.replace("/", "-").replace("Z", "+00:00")
        if "T" not in text and " " in text:
            text = text.replace(" ", "T", 1)
        if "T" not in text and _v4_global(_v4_scope, 'len')(text) == 10:
            text += "T00:00:00"
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(text)
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} is not an ISO timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
    return parsed.astimezone(_v4_global(_v4_scope, 'SHANGHAI'))


def __lane_labels_body(_v4_scope, /, value, label):
    """Canonicalize lane labels without guessing from a delimited string.

    A string remains one literal lane label.  A list/tuple/set is a genuine
    multi-label value and compares order-insensitively.  We never map
    ``candidate_bucket`` or ``formal_eligible`` to a lane.
    """

    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')):
        labels = [value.strip()]
    elif _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'), _v4_global(_v4_scope, 'set'), _v4_global(_v4_scope, 'frozenset'))):
        labels = [_v4_global(_v4_scope, 'str')(item).strip() for item in value]
    else:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} must be a lane label or label list")
    labels = [item for item in labels if item]
    if not labels:
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{label} cannot be empty")
    return _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'dict').fromkeys(labels)))


def __no_trade_gate_body(_v4_scope, /, row):
    derived: int | None = None
    if "trade_status_contract" in row or "trade_status" in row:
        contract = _v4_global(_v4_scope, 'str')(row.get("trade_status_contract") or row.get("trade_status") or "")
        derived = 0 if contract == "NO_TRADE" else 1
    if "no_trade_gate" in row:
        value = row.get("no_trade_gate")
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'bool')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("no_trade_gate cannot be bool")
        try:
            numeric = _v4_global(_v4_scope, 'int')(value)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("no_trade_gate must be an integer") from error
        if numeric not in (0, 1):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("no_trade_gate is outside hk comparator domain")
        if derived is not None and numeric != derived:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("no_trade_gate conflicts with trade_status_contract")
        return numeric
    if "trade_status_contract" not in row and "trade_status" not in row:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("trade_status_contract/trade_status is required")
    return _v4_global(_v4_scope, 'int')(derived)


def __stage_contract_body(_v4_scope, /, metadata):
    trade_date = _v4_global(_v4_scope, '_exact_date')(metadata.get("trade_date"), "trade_date")
    stage_id = _v4_global(_v4_scope, 'str')(metadata.get("stage") or metadata.get("stage_id") or "").strip()
    if stage_id not in _v4_global(_v4_scope, 'STAGE_CUTOFFS'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"stage must be one of {_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'STAGE_CUTOFFS'))}")
    cutoff = _v4_global(_v4_scope, '_parse_timestamp')(metadata.get("cutoff_ts"), trade_date, "cutoff_ts")
    expected = _v4_global(_v4_scope, 'time').fromisoformat(_v4_global(_v4_scope, 'STAGE_CUTOFFS')[stage_id])
    if cutoff.strftime("%H:%M:%S") != expected.strftime("%H:%M:%S"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{stage_id} cutoff must be {_v4_global(_v4_scope, 'STAGE_CUTOFFS')[stage_id]}")
    if cutoff.strftime("%Y%m%d") != trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("cutoff_ts must be on trade_date")
    if _v4_global(_v4_scope, 'str')(metadata.get("market") or _v4_global(_v4_scope, 'MARKET')) != _v4_global(_v4_scope, 'MARKET'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula margin shadow is HK_CONNECT only")
    return trade_date, stage_id, cutoff.isoformat(), cutoff


def __validate_price_body(_v4_scope, /, row, cutoff):
    price = _v4_global(_v4_scope, '_finite')(row.get("stage_price"))
    if price <= 0:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("stage_price must be positive")
    price_ts = _v4_global(_v4_scope, '_parse_timestamp')(row.get("price_ts"), cutoff.strftime("%Y%m%d"), "price_ts")
    if price_ts > cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("stage price was captured after the cutoff")
    currency = _v4_global(_v4_scope, 'str')(row.get("currency") or "").strip().upper()
    adjustment = _v4_global(_v4_scope, 'str')(row.get("adjustment_mode") or "").strip()
    source = _v4_global(_v4_scope, 'str')(row.get("price_source") or "").strip()
    if not currency or not adjustment or not source:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("stage price currency/adjustment_mode/price_source are required")
    return {
        "stage_price": price,
        "price_ts": price_ts.isoformat(),
        "currency": currency,
        "adjustment_mode": adjustment,
        "price_source": source,
    }


def __immutable_json_body(_v4_scope, /, path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"refusing to overwrite immutable artifact: {path}")
    encoded = _v4_global(_v4_scope, 'canonical_json')(payload)
    descriptor, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = _v4_global(_v4_scope, 'Path')(temporary)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        try:
            _v4_global(_v4_scope, 'os').link(temporary_path, path)
        except _v4_global(_v4_scope, 'FileExistsError') as error:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"immutable artifact raced with another writer: {path}") from error
    finally:
        try:
            temporary_path.unlink()
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass
    return _v4_global(_v4_scope, 'sha256_bytes')(encoded)


def __immutable_bytes_body(_v4_scope, /, path, encoded):
    """Publish exact consumed bytes once, without following symlinks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"refusing to overwrite immutable artifact: {path}")
    descriptor, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = _v4_global(_v4_scope, 'Path')(temporary)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        try:
            _v4_global(_v4_scope, 'os').link(temporary_path, path)
        except _v4_global(_v4_scope, 'FileExistsError') as error:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"immutable artifact raced with another writer: {path}") from error
    finally:
        try:
            temporary_path.unlink()
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass
    return _v4_global(_v4_scope, 'sha256_bytes')(encoded)


def __selector_result_codes_body(_v4_scope, /, selector_result):
    rows = selector_result.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return rows are required")
    codes: list[str] = []
    for row in rows[:_v4_global(_v4_scope, 'TOP_K')]:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return rows must be objects")
        codes.append(_v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code"))))
    if _v4_global(_v4_scope, 'len')(codes) != _v4_global(_v4_scope, 'TOP_K') or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(codes)) != _v4_global(_v4_scope, 'TOP_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return Top10 is incomplete or duplicated")
    return codes


def __cli_body(_v4_scope, /):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="V4 formula-margin shadow manual, read-only tool")
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--input", type=_v4_global(_v4_scope, 'Path'), required=True)
    preflight_capture = sub.add_parser("preflight-capture")
    preflight_capture.add_argument("--input", type=_v4_global(_v4_scope, 'Path'), required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--input", type=_v4_global(_v4_scope, 'Path'), required=True)
    capture.add_argument("--output-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--input", type=_v4_global(_v4_scope, 'Path'), required=True)
    freeze.add_argument("--output-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    label = sub.add_parser("label")
    label.add_argument("--run-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    label.add_argument("--input", type=_v4_global(_v4_scope, 'Path'), required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--run-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    verify.add_argument("--external-revalidate", action="store_true")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--run-root", type=_v4_global(_v4_scope, 'Path'), action="append", required=True)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = _v4_global(_v4_scope, 'preflight_input')(args.input)
        elif args.command == "preflight-capture":
            result = _v4_global(_v4_scope, 'preflight_capture_input')(args.input)
        elif args.command == "capture":
            result = _v4_global(_v4_scope, 'capture_selector_snapshot')(args.input, args.output_root)
        elif args.command == "freeze":
            result = _v4_global(_v4_scope, 'freeze_snapshot')(
                _v4_global(_v4_scope, '_read_json')(args.input),
                args.output_root,
                require_full_pool=True,
            )
        elif args.command == "label":
            result = _v4_global(_v4_scope, 'append_labels')(args.run_root, _v4_global(_v4_scope, '_read_json')(args.input))
        elif args.command == "verify":
            result = _v4_global(_v4_scope, 'verify_frozen_artifacts')(args.run_root, external_revalidate=args.external_revalidate)
        else:
            result = _v4_global(_v4_scope, 'evaluate_runs')(args.run_root)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        result = {"status": "CANNOT_CONFIRM", "error": _v4_global(_v4_scope, 'str')(error)}
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") not in {"CANNOT_CONFIRM", "REJECTED"} else 2
