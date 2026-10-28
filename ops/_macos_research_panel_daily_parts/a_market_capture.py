"""ops.macos_research_panel_daily: a_market_capture (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _collect_a_pytdx_rows_body(_v4_scope, /, universe_rows, target_date, *, client_factory, host, port, hq_hosts_override, lookback, minimum_rows, required_coverage_ratio):
    """Collect one exact-date A-share bar per universe code from pytdx HQ."""
    target = _v4_global(_v4_scope, '_date')(target_date)
    universe: dict[str, tuple[str, str, int]] = {}
    for source in _v4_global(_v4_scope, '_rows')(universe_rows):
        code, exchange, market = _v4_global(_v4_scope, '_universe_code')(source)
        universe[f"{code}.{exchange.upper()}"] = (code, exchange, market)
    if _v4_global(_v4_scope, 'len')(universe) < minimum_rows:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A minimum coverage requires {minimum_rows} universe rows, got {_v4_global(_v4_scope, 'len')(universe)}")
    if client_factory is None:
        from pytdx.hq import TdxHq_API

        client_factory = TdxHq_API
    if host is not None:
        candidate_hosts = [("explicit", _v4_global(_v4_scope, 'str')(host), _v4_global(_v4_scope, 'int')(port or 7709))]
    elif hq_hosts_override is not None:
        candidate_hosts = [(_v4_global(_v4_scope, 'str')(name), _v4_global(_v4_scope, 'str')(address), _v4_global(_v4_scope, 'int')(candidate_port)) for name, address, candidate_port in hq_hosts_override]
    else:
        try:
            from pytdx.config.hosts import hq_hosts

            candidate_hosts = [(_v4_global(_v4_scope, 'str')(name), _v4_global(_v4_scope, 'str')(address), _v4_global(_v4_scope, 'int')(candidate_port)) for name, address, candidate_port in hq_hosts]
        except (_v4_global(_v4_scope, 'ImportError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'SnapshotGateError')("pytdx official hq_hosts are unavailable") from error
    if not candidate_hosts:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("pytdx HQ host probe list is empty")

    probe_code, _, probe_market = _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(_v4_global(_v4_scope, 'sorted')(universe.values())))
    selected_client: Any | None = None
    selected_host: tuple[str, str, int] | None = None
    probe_errors: list[str] = []
    for candidate in candidate_hosts:
        name, address, candidate_port = candidate
        client = client_factory()
        try:
            connected = client.connect(address, candidate_port)
            if connected is False:
                raise _v4_global(_v4_scope, 'SnapshotGateError')("connect returned false")
            probe_response = client.get_security_bars(_v4_global(_v4_scope, 'PYTDX_KLINE_DAY'), probe_market, probe_code, 0, _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(lookback)))
            probe_ok = False
            for raw in _v4_global(_v4_scope, '_frame_records')(probe_response):
                if _v4_global(_v4_scope, '_compact_datetime')(raw.get("datetime") or raw.get("trade_date")) != target:
                    continue
                probe_ohlc = [_v4_global(_v4_scope, '_number')(raw, field) for field in ("open", "high", "low", "close")]
                if _v4_global(_v4_scope, 'min')(probe_ohlc) > 0 and probe_ohlc[1] >= probe_ohlc[2] and probe_ohlc[3] >= probe_ohlc[2] and probe_ohlc[3] <= probe_ohlc[1]:
                    probe_ok = True
                    break
            if not probe_ok:
                raise _v4_global(_v4_scope, 'SnapshotGateError')("probe exact-date coverage has no valid daily bar")
            selected_client = client
            selected_host = candidate
            break
        except _v4_global(_v4_scope, 'Exception') as error:
            probe_errors.append(f"{name or address}:{candidate_port}:{error}")
            disconnect = _v4_global(_v4_scope, 'getattr')(client, "disconnect", None)
            if _v4_global(_v4_scope, 'callable')(disconnect):
                disconnect()
    if selected_client is None or selected_host is None:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("pytdx HQ host probe failed: " + ";".join(probe_errors))

    client = selected_client
    rows: list[dict[str, Any]] = []
    try:
        for _, (code, exchange, market) in _v4_global(_v4_scope, 'sorted')(universe.items()):
            response = client.get_security_bars(_v4_global(_v4_scope, 'PYTDX_KLINE_DAY'), market, code, 0, _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(lookback)))
            for raw in _v4_global(_v4_scope, '_frame_records')(response):
                if _v4_global(_v4_scope, '_compact_datetime')(raw.get("datetime") or raw.get("trade_date")) != target:
                    continue
                row = {
                    "trade_date": target,
                    "code": code,
                    "exchange": exchange,
                    "open": _v4_global(_v4_scope, '_number')(raw, "open"),
                    "high": _v4_global(_v4_scope, '_number')(raw, "high"),
                    "low": _v4_global(_v4_scope, '_number')(raw, "low"),
                    "close": _v4_global(_v4_scope, '_number')(raw, "close"),
                    "volume": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, '_number')(raw, "vol", "volume") * 100)),
                    "turnover": _v4_global(_v4_scope, '_number')(raw, "amount", "turnover"),
                    "source": "PYTDX_HQ_DAILY",
                }
                if _v4_global(_v4_scope, 'min')(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < row["low"] or row["close"] < row["low"] or row["close"] > row["high"]:
                    continue
                rows.append(row)
                break
    finally:
        disconnect = _v4_global(_v4_scope, 'getattr')(client, "disconnect", None)
        if _v4_global(_v4_scope, 'callable')(disconnect):
            disconnect()
    rows_by_code = {_v4_global(_v4_scope, 'str')(row["code"]): row for row in rows}
    rows = [rows_by_code[code] for code, _, _ in _v4_global(_v4_scope, 'sorted')(universe.values()) if code in rows_by_code]
    coverage = _v4_global(_v4_scope, 'len')(rows) / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(universe), 1)
    if _v4_global(_v4_scope, 'len')(rows) < minimum_rows or coverage + 1e-12 < _v4_global(_v4_scope, 'float')(required_coverage_ratio):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A exact-date coverage below gate: universe={_v4_global(_v4_scope, 'len')(universe)},rows={_v4_global(_v4_scope, 'len')(rows)},coverage={coverage:.8f}")
    source_sha = _v4_global(_v4_scope, '_canonical_sha')({"target_date": target, "rows": rows})
    return {"status": "READY", "target_date": target, "rows": rows, "universe_count": _v4_global(_v4_scope, 'len')(universe), "row_count": _v4_global(_v4_scope, 'len')(rows), "coverage_rate": coverage, "source_sha256": source_sha, "sha256": source_sha, "selected_host": {"host": selected_host[1], "port": selected_host[2]}, **_v4_global(_v4_scope, 'SAFETY_FLAGS')}


def _bootstrap_a_vipdoc_from_panel_body(_v4_scope, /, panel_path, tdx_root, *, tail_records):
    """Seed SH/SZ/BJ VIPDOC files from a panel tail without overwriting history."""
    if _v4_global(_v4_scope, 'int')(tail_records) < 1:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("tail_records must be positive")
    rows = _v4_global(_v4_scope, '_panel_frame')(_v4_global(_v4_scope, 'Path')(panel_path))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for source in rows:
        code_value = _v4_global(_v4_scope, 'str')(source.get("ts_code") or source.get("code") or "").strip().upper()
        if "." not in code_value:
            continue
        code, exchange = code_value.split(".", 1)
        exchange = exchange.split("_", 1)[0].lower()
        if exchange not in {"sh", "sz", "bj"}:
            continue
        if not code.isdigit() or _v4_global(_v4_scope, 'len')(code) != 6:
            continue
        if not code.startswith(_v4_global(_v4_scope, 'COMMON_A_PREFIXES')[exchange]):
            continue
        row = {
            "trade_date": _v4_global(_v4_scope, '_date')(source.get("trade_date") or source.get("trade_date_compact")),
            "code": code,
            "exchange": exchange,
            "open": _v4_global(_v4_scope, '_number')(source, "open"),
            "high": _v4_global(_v4_scope, '_number')(source, "high"),
            "low": _v4_global(_v4_scope, '_number')(source, "low"),
            "close": _v4_global(_v4_scope, '_number')(source, "close"),
            "volume": _v4_global(_v4_scope, '_number')(source, "volume", "vol"),
            "turnover": _v4_global(_v4_scope, '_number')(source, "amount", "turnover"),
        }
        if _v4_global(_v4_scope, 'min')(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < row["low"] or row["close"] < row["low"] or row["close"] > row["high"]:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A seed invalid OHLC: {code}")
        grouped.setdefault((exchange, code), []).append(row)
    if not grouped:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("A seed panel has no SH/SZ/BJ rows")
    results = []
    destination = _v4_global(_v4_scope, 'Path')(tdx_root)
    for (exchange, code), code_rows in _v4_global(_v4_scope, 'sorted')(grouped.items()):
        ordered = _v4_global(_v4_scope, 'sorted')(code_rows, key=lambda item: _v4_global(_v4_scope, 'int')(item["trade_date"]))[-_v4_global(_v4_scope, 'int')(tail_records):]
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code}.day"
        checked = _v4_global(_v4_scope, '_validate_seed_rows')(ordered)
        encoded = b"".join(_v4_global(_v4_scope, 'A_DAY_STRUCT').pack(*_v4_global(_v4_scope, '_a_record')(row)) for row in checked)
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A seed conflict: {path}")
            already_current = True
        else:
            _v4_global(_v4_scope, '_atomic_write')(path, encoded)
            already_current = False
        results.append({"status": "READY", "already_current": already_current, "target_date": checked[-1]["trade_date"], "row_count": _v4_global(_v4_scope, 'len')(checked), "coverage_rate": 1.0, "sha256": _v4_global(_v4_scope, '_sha')(path), "path": _v4_global(_v4_scope, 'str')(path), **_v4_global(_v4_scope, 'SAFETY_FLAGS')})
    return _v4_global(_v4_scope, '_grouped_result')(results, _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'str')(item["target_date"]) for item in results), lane="A") | {"seed_panel": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(panel_path)), "tail_records": _v4_global(_v4_scope, 'int')(tail_records)}


def __validate_seed_rows_body(_v4_scope, /, rows):
    if not rows:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("A seed has no rows")
    dates: set[int] = _v4_global(_v4_scope, 'set')()
    checked = []
    for row in rows:
        date_value = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_date')(row.get("trade_date")))
        if date_value in dates:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A seed duplicate date: {date_value}")
        dates.add(date_value)
        if _v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'float')(row["open"]), _v4_global(_v4_scope, 'float')(row["high"]), _v4_global(_v4_scope, 'float')(row["low"]), _v4_global(_v4_scope, 'float')(row["close"])) <= 0:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A seed non-positive OHLC: {row.get('code')}")
        checked.append(_v4_global(_v4_scope, 'dict')(row, trade_date=_v4_global(_v4_scope, 'str')(date_value)))
    return _v4_global(_v4_scope, 'sorted')(checked, key=lambda item: _v4_global(_v4_scope, 'int')(item["trade_date"]))
