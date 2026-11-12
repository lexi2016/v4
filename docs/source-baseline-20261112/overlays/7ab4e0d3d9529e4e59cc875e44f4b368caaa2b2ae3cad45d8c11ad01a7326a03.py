"""ops.macos_research_panel_daily: panel_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __resolve_a_sync_run_budget_body(_v4_scope, /, raw):
    """Resolve the A sync wall-clock budget, rejecting unsafe values."""
    if raw is None:
        return _v4_global(_v4_scope, 'DEFAULT_A_SYNC_RUN_BUDGET_SECONDS')
    if _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'bool')):
        raise _v4_global(_v4_scope, 'ValueError')("A sync run budget must be a positive finite number")
    try:
        value = _v4_global(_v4_scope, 'float')(raw)
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')) as error:
        raise _v4_global(_v4_scope, 'ValueError')("A sync run budget must be a positive finite number") from error
    if not _v4_global(_v4_scope, 'math').isfinite(value) or value <= 0.0:
        raise _v4_global(_v4_scope, 'ValueError')("A sync run budget must be a positive finite number")
    return value


def __validate_rows_body(_v4_scope, /, rows, target_date, *, minimum_rows, lane):
    target_date = _v4_global(_v4_scope, '_date')(target_date)
    if _v4_global(_v4_scope, 'len')(rows) < minimum_rows:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} minimum coverage requires {minimum_rows} rows, got {_v4_global(_v4_scope, 'len')(rows)}")
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    checked: list[dict[str, Any]] = []
    for row in rows:
        actual = _v4_global(_v4_scope, '_date')(row.get("trade_date") or row.get("trade_date_compact"))
        if actual != target_date:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} exact target date mismatch: {actual} != {target_date}")
        code = _v4_global(_v4_scope, '_code')(row)
        if code in seen:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} duplicate code: {code}")
        seen.add(code)
        open_, high, low, close = (_v4_global(_v4_scope, '_number')(row, name) for name in ("open", "high", "low", "close"))
        if _v4_global(_v4_scope, 'min')(open_, high, low, close) <= 0 or high < low or close < low or close > high:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} non-positive or invalid OHLC: {code}")
        row = _v4_global(_v4_scope, 'dict')(row)
        row["code"] = code
        row["trade_date"] = target_date
        checked.append(row)
    return checked, _v4_global(_v4_scope, 'len')(checked) / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(seen), 1)


def __atomic_write_body(_v4_scope, /, path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        _v4_global(_v4_scope, 'os').replace(temp_name, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temp_name):
            _v4_global(_v4_scope, 'os').unlink(temp_name)


def __ensure_pointer_seed_body(_v4_scope, /, pointer, seed):
    if pointer.exists():
        target = _v4_global(_v4_scope, 'Path')(pointer.read_text(encoding="utf-8-sig").strip())
        if target.is_file():
            return target
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"pointer target missing: {pointer}")
    if seed is None:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"pointer missing and no seed: {pointer}")
    target = _v4_global(_v4_scope, 'Path')(seed).resolve()
    if not target.is_file():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"pointer seed missing: {target}")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    _v4_global(_v4_scope, '_atomic_write')(pointer, (_v4_global(_v4_scope, 'str')(target) + "\n").encode())
    return target


def __a_exchange_body(_v4_scope, /, row):
    exchange = _v4_global(_v4_scope, 'str')(row.get("exchange") or row.get("market") or "").strip().lower()
    if exchange in {"sh", "sz", "bj"}:
        return exchange
    code = _v4_global(_v4_scope, '_code')(row)
    if code.startswith(("6",)):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    raise _v4_global(_v4_scope, 'SnapshotGateError')(f"cannot infer A exchange for {code}")


def _run_lanes_body(_v4_scope, /, *, target_date, receipt_root, a_runner, hk_runner, lane):
    target_date = _v4_global(_v4_scope, '_date')(target_date)
    requested_lane = _v4_global(_v4_scope, '_normalize_lane')(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes: dict[str, dict[str, Any]] = {}
    for lane, runner in (("A", a_runner), ("HK", hk_runner)):
        if lane not in requested:
            lanes[lane] = _v4_global(_v4_scope, '_not_requested_lane')()
            continue
        try:
            outcome = _v4_global(_v4_scope, 'dict')(runner(target_date))
            outcome.setdefault("status", "READY")
            if outcome.get("target_date", target_date) != target_date:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{lane} exact target date mismatch")
            lanes[lane] = _v4_global(_v4_scope, '_receipt')(_v4_global(_v4_scope, 'Path')(receipt_root), lane, target_date, {**outcome, "runner_called": True, "receipt_written": True})
        except _v4_global(_v4_scope, 'Exception') as error:  # independent lane: never prevent the other lane
            lanes[lane] = _v4_global(_v4_scope, '_receipt')(_v4_global(_v4_scope, 'Path')(receipt_root), lane, target_date, {"status": "FAILED", "error": _v4_global(_v4_scope, 'str')(error), "coverage_rate": 0.0, "sha256": "", "runner_called": True, "receipt_written": True})
    statuses = {lanes[name].get("status") for name in requested}
    overall = "READY" if statuses == {"READY"} else "FAILED" if statuses == {"FAILED"} else "PARTIAL"
    return {"schema_version": "v3.macos.research_panel_daily.v1", "target_date": target_date, "requested_lane": requested_lane, "overall_status": overall, "lanes": lanes, **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
