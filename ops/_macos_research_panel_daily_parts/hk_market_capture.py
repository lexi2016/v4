"""ops.macos_research_panel_daily: hk_market_capture (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _collect_hk_futu_rows_body(_v4_scope, /, target_date, *, context_factory, batch_size, minimum_universe_count, required_coverage_ratio):
    """Collect an exact-date full HK Connect snapshot from Futu OpenD."""
    target = _v4_global(_v4_scope, '_date')(target_date)
    if context_factory is None:
        def context_factory():
            import futu

            return futu.OpenQuoteContext(host="127.0.0.1", port=11111)
    context = context_factory()
    universe: dict[str, str] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    try:
        for plate_code in _v4_global(_v4_scope, 'HKCONNECT_PLATE_CODES'):
            return_code, frame = context.get_plate_stock(plate_code)
            if return_code != 0:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(f"Futu plate lookup failed: {plate_code}")
            for item in _v4_global(_v4_scope, '_frame_records')(frame):
                code = _v4_global(_v4_scope, 'str')(item.get("code") or "").strip().upper()
                if code.startswith("HK."):
                    universe[code] = _v4_global(_v4_scope, 'str')(item.get("stock_name") or item.get("name") or "").strip()
        codes = _v4_global(_v4_scope, 'sorted')(universe)
        minimum_universe = _v4_global(_v4_scope, 'max')(600, _v4_global(_v4_scope, 'int')(minimum_universe_count))
        if _v4_global(_v4_scope, 'len')(codes) < minimum_universe:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"HK universe below minimum: {_v4_global(_v4_scope, 'len')(codes)} < {minimum_universe_count}")
        step = _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(batch_size))
        for offset in _v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(codes), step):
            return_code, frame = context.get_market_snapshot(codes[offset : offset + step])
            if return_code != 0:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(f"Futu market snapshot failed at offset {offset}")
            for item in _v4_global(_v4_scope, '_frame_records')(frame):
                code = _v4_global(_v4_scope, 'str')(item.get("code") or "").strip().upper()
                if code in universe:
                    snapshots[code] = item
    finally:
        close = _v4_global(_v4_scope, 'getattr')(context, "close", None)
        if _v4_global(_v4_scope, 'callable')(close):
            close()
    rows: list[dict[str, Any]] = []
    excluded: dict[str, list[str]] = {}
    positive_volume_count = 0
    positive_turnover_count = 0
    required_fields = ("open_price", "high_price", "low_price", "last_price", "volume", "turnover")
    for code in codes:
        source = snapshots.get(code) or {}
        if _v4_global(_v4_scope, '_compact_datetime')(source.get("update_time")) != target:
            excluded[code] = ["stale_or_missing_date"]
            continue
        missing = [field for field in required_fields if field not in source or source.get(field) in (None, "")]
        if missing:
            excluded[code] = [f"missing_{field}" for field in missing]
            continue
        try:
            open_price = _v4_global(_v4_scope, '_number')(source, "open_price")
            high_price = _v4_global(_v4_scope, '_number')(source, "high_price")
            low_price = _v4_global(_v4_scope, '_number')(source, "low_price")
            last_price = _v4_global(_v4_scope, '_number')(source, "last_price")
            volume = _v4_global(_v4_scope, '_number')(source, "volume")
            turnover = _v4_global(_v4_scope, '_number')(source, "turnover")
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'SnapshotGateError')):
            excluded[code] = ["non_numeric_fields"]
            continue
        reasons: list[str] = []
        if volume > 0:
            positive_volume_count += 1
        else:
            reasons.append("non_positive_volume")
        if turnover > 0:
            positive_turnover_count += 1
        else:
            reasons.append("non_positive_turnover")
        if _v4_global(_v4_scope, 'min')(open_price, high_price, low_price, last_price) <= 0 or high_price < low_price or last_price < low_price or last_price > high_price:
            reasons.append("non_positive_ohlc")
        if reasons:
            excluded[code] = reasons
            continue
        try:
            row = {
                "trade_date": target,
                "code": code,
                "name": _v4_global(_v4_scope, 'str')(source.get("name") or universe.get(code) or "").strip(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": last_price,
                "volume": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'round')(volume)),
                "turnover": turnover,
                "source": "FUTU_HKCONNECT_SNAPSHOT",
            }
            rows.append(row)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'SnapshotGateError')):
            excluded[code] = ["row_encoding_error"]
            continue
    coverage = _v4_global(_v4_scope, 'len')(rows) / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    positive_volume_coverage = positive_volume_count / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    positive_turnover_coverage = positive_turnover_count / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    minimum_universe = _v4_global(_v4_scope, 'max')(600, _v4_global(_v4_scope, 'int')(minimum_universe_count))
    if _v4_global(_v4_scope, 'len')(rows) < minimum_universe:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK exact-date coverage below gate: "
            f"universe={_v4_global(_v4_scope, 'len')(codes)},rows={_v4_global(_v4_scope, 'len')(rows)},coverage={coverage:.8f}"
        )
    if positive_volume_coverage + 1e-12 < 0.8 or positive_turnover_coverage + 1e-12 < 0.8:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK positive-trade coverage below gate: "
            f"volume={positive_volume_coverage:.8f},turnover={positive_turnover_coverage:.8f}"
        )
    if coverage + 1e-12 < _v4_global(_v4_scope, 'float')(required_coverage_ratio):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"HK exact-date coverage below gate: universe={_v4_global(_v4_scope, 'len')(codes)},rows={_v4_global(_v4_scope, 'len')(rows)},coverage={coverage:.8f}")
    evidence_codes = _v4_global(_v4_scope, 'sorted')(excluded)
    evidence_codes_limited = evidence_codes[:_v4_global(_v4_scope, 'MAX_EXCLUDED_EVIDENCE')]
    evidence_reasons = {code: _v4_global(_v4_scope, 'sorted')(excluded[code]) for code in evidence_codes_limited}
    source_sha = _v4_global(_v4_scope, '_canonical_sha')(
        {
            "target_date": target,
            "plates": _v4_global(_v4_scope, 'HKCONNECT_PLATE_CODES'),
            "rows": rows,
            "excluded_count": _v4_global(_v4_scope, 'len')(evidence_codes),
            "excluded_codes": evidence_codes,
            "excluded_reasons": {code: _v4_global(_v4_scope, 'sorted')(excluded[code]) for code in evidence_codes},
            "positive_volume_coverage_rate": positive_volume_coverage,
            "positive_turnover_coverage_rate": positive_turnover_coverage,
        }
    )
    return {
        "status": "READY",
        "target_date": target,
        "rows": rows,
        "universe_count": _v4_global(_v4_scope, 'len')(codes),
        "row_count": _v4_global(_v4_scope, 'len')(rows),
        "coverage_rate": coverage,
        "positive_volume_coverage_rate": positive_volume_coverage,
        "positive_turnover_coverage_rate": positive_turnover_coverage,
        "excluded_count": _v4_global(_v4_scope, 'len')(evidence_codes),
        "excluded_codes": evidence_codes_limited,
        "excluded_reasons": evidence_reasons,
        "source_sha256": source_sha,
        "sha256": source_sha,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
