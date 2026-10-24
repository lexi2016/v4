"""Offline-testable A-share and HK snapshot collectors."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .macos_research_panel_daily_common import (
    HKCONNECT_PLATE_CODES,
    MAX_EXCLUDED_EVIDENCE,
    PYTDX_KLINE_DAY,
    SAFETY_FLAGS,
    SnapshotGateError,
    _canonical_sha,
    _compact_datetime,
    _date,
    _atomic_write,
    _number,
    _rows,
    _universe_code,
)


# The daily gate consumes this in-process envelope after the panel collector
# returns.  It is deliberately a side channel: the historical collector
# result remains byte-for-byte compatible with the V3.5 facade contract.
_LAST_HK_CAPTURE: dict[str, Any] | None = None


def collect_a_pytdx_rows(
    universe_rows: Iterable[Mapping[str, Any]],
    target_date: str,
    *,
    client_factory: Callable[[], Any] | None = None,
    host: str | None = None,
    port: int | None = None,
    hq_hosts_override: Sequence[tuple[str, str, int]] | None = None,
    lookback: int = 400,
    minimum_rows: int = 1,
    required_coverage_ratio: float = 1.0,
) -> dict[str, Any]:
    """Collect one exact-date A-share bar per universe code from pytdx HQ."""
    target = _date(target_date)
    universe: dict[str, tuple[str, str, int]] = {}
    for source in _rows(universe_rows):
        code, exchange, market = _universe_code(source)
        universe[f"{code}.{exchange.upper()}"] = (code, exchange, market)
    if len(universe) < minimum_rows:
        raise SnapshotGateError(f"A minimum coverage requires {minimum_rows} universe rows, got {len(universe)}")
    if client_factory is None:
        from pytdx.hq import TdxHq_API

        client_factory = TdxHq_API
    if host is not None:
        candidate_hosts = [("explicit", str(host), int(port or 7709))]
    elif hq_hosts_override is not None:
        candidate_hosts = [(str(name), str(address), int(candidate_port)) for name, address, candidate_port in hq_hosts_override]
    else:
        try:
            from pytdx.config.hosts import hq_hosts

            candidate_hosts = [(str(name), str(address), int(candidate_port)) for name, address, candidate_port in hq_hosts]
        except (ImportError, TypeError, ValueError) as error:
            raise SnapshotGateError("pytdx official hq_hosts are unavailable") from error
    if not candidate_hosts:
        raise SnapshotGateError("pytdx HQ host probe list is empty")

    probe_code, _, probe_market = next(iter(sorted(universe.values())))
    selected_client: Any | None = None
    selected_host: tuple[str, str, int] | None = None
    probe_errors: list[str] = []
    for candidate in candidate_hosts:
        name, address, candidate_port = candidate
        client = client_factory()
        try:
            connected = client.connect(address, candidate_port)
            if connected is False:
                raise SnapshotGateError("connect returned false")
            probe_response = client.get_security_bars(PYTDX_KLINE_DAY, probe_market, probe_code, 0, max(1, int(lookback)))
            probe_ok = False
            for raw in _frame_records(probe_response):
                if _compact_datetime(raw.get("datetime") or raw.get("trade_date")) != target:
                    continue
                probe_ohlc = [_number(raw, field) for field in ("open", "high", "low", "close")]
                if min(probe_ohlc) > 0 and probe_ohlc[1] >= probe_ohlc[2] and probe_ohlc[3] >= probe_ohlc[2] and probe_ohlc[3] <= probe_ohlc[1]:
                    probe_ok = True
                    break
            if not probe_ok:
                raise SnapshotGateError("probe exact-date coverage has no valid daily bar")
            selected_client = client
            selected_host = candidate
            break
        except Exception as error:
            probe_errors.append(f"{name or address}:{candidate_port}:{error}")
            disconnect = getattr(client, "disconnect", None)
            if callable(disconnect):
                disconnect()
    if selected_client is None or selected_host is None:
        raise SnapshotGateError("pytdx HQ host probe failed: " + ";".join(probe_errors))

    client = selected_client
    rows: list[dict[str, Any]] = []
    try:
        for _, (code, exchange, market) in sorted(universe.items()):
            response = client.get_security_bars(PYTDX_KLINE_DAY, market, code, 0, max(1, int(lookback)))
            for raw in _frame_records(response):
                if _compact_datetime(raw.get("datetime") or raw.get("trade_date")) != target:
                    continue
                row = {
                    "trade_date": target,
                    "code": code,
                    "exchange": exchange,
                    "open": _number(raw, "open"),
                    "high": _number(raw, "high"),
                    "low": _number(raw, "low"),
                    "close": _number(raw, "close"),
                    "volume": int(round(_number(raw, "vol", "volume") * 100)),
                    "turnover": _number(raw, "amount", "turnover"),
                    "source": "PYTDX_HQ_DAILY",
                }
                if min(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < row["low"] or row["close"] < row["low"] or row["close"] > row["high"]:
                    continue
                rows.append(row)
                break
    finally:
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            disconnect()
    rows_by_code = {str(row["code"]): row for row in rows}
    rows = [rows_by_code[code] for code, _, _ in sorted(universe.values()) if code in rows_by_code]
    coverage = len(rows) / max(len(universe), 1)
    if len(rows) < minimum_rows or coverage + 1e-12 < float(required_coverage_ratio):
        raise SnapshotGateError(f"A exact-date coverage below gate: universe={len(universe)},rows={len(rows)},coverage={coverage:.8f}")
    source_sha = _canonical_sha({"target_date": target, "rows": rows})
    return {"status": "READY", "target_date": target, "rows": rows, "universe_count": len(universe), "row_count": len(rows), "coverage_rate": coverage, "source_sha256": source_sha, "sha256": source_sha, "selected_host": {"host": selected_host[1], "port": selected_host[2]}, **SAFETY_FLAGS}


def collect_hk_futu_rows(
    target_date: str,
    *,
    context_factory: Callable[[], Any] | None = None,
    batch_size: int = 200,
    minimum_universe_count: int = 600,
    required_coverage_ratio: float = 0.0,
) -> dict[str, Any]:
    """Collect an exact-date full HK Connect snapshot from Futu OpenD."""
    # A failed invocation must not leave a previous capture available to the
    # gate.  ``globals`` also points at the compatibility facade when this
    # function has been rebound there with FunctionType.
    globals().pop("_LAST_HK_CAPTURE", None)
    target = _date(target_date)
    capture_manifest_value = os.environ.get("V35_HK_CAPTURE_PATH")
    capture_manifest_path = Path(capture_manifest_value).expanduser() if capture_manifest_value else None
    capture_metadata_enabled = capture_manifest_path is not None
    if capture_manifest_path is not None and (
        capture_manifest_path.name == f"{target}.json" or capture_manifest_path.exists()
    ):
        capture_manifest_path = capture_manifest_path.with_name(
            f"{target}-{os.getpid()}-{os.urandom(12).hex()}.json"
        )
    capture_raw_path = (
        capture_manifest_path.with_name(f"{capture_manifest_path.stem}.capture.json")
        if capture_manifest_path is not None
        else None
    )
    capture_run_id = (
        os.environ.get("V35_HK_CAPTURE_RUN_ID") or capture_manifest_path.stem
        if capture_manifest_path is not None
        else None
    )

    def write_manifest(payload: bytes) -> None:
        if capture_manifest_path is None:
            return
        if capture_manifest_path.exists():
            existing = capture_manifest_path.read_bytes()
            try:
                existing_envelope = json.loads(existing.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise SnapshotGateError(
                    f"HK capture manifest path is not a pending or ready envelope: {capture_manifest_path}"
                ) from error
            if isinstance(existing_envelope, Mapping) and existing_envelope.get("status") == "READY":
                if existing != payload:
                    raise SnapshotGateError(
                        f"HK capture manifest is immutable and already READY: {capture_manifest_path}"
                    )
                return
        _atomic_write(capture_manifest_path, payload)

    def write_raw_capture(payload: bytes) -> None:
        if capture_raw_path is None:
            return
        if capture_raw_path.exists():
            if capture_raw_path.read_bytes() != payload:
                raise SnapshotGateError(
                    f"HK raw capture path is immutable: {capture_raw_path}"
                )
            return
        _atomic_write(capture_raw_path, payload)

    if capture_manifest_path is not None:
        write_manifest(
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
                    "status": "PENDING",
                    "target_date": target,
                    "capture_run_id": capture_run_id,
                    "capture_relative_path": capture_raw_path.name,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    if context_factory is None:
        def context_factory():
            import futu

            return futu.OpenQuoteContext(host="127.0.0.1", port=11111)
    context = context_factory()
    universe: dict[str, str] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    try:
        for plate_code in HKCONNECT_PLATE_CODES:
            return_code, frame = context.get_plate_stock(plate_code)
            if return_code != 0:
                raise SnapshotGateError(f"Futu plate lookup failed: {plate_code}")
            for item in _frame_records(frame):
                code = str(item.get("code") or "").strip().upper()
                if code.startswith("HK."):
                    universe[code] = str(item.get("stock_name") or item.get("name") or "").strip()
        codes = sorted(universe)
        minimum_universe = max(600, int(minimum_universe_count))
        if len(codes) < minimum_universe:
            raise SnapshotGateError(f"HK universe below minimum: {len(codes)} < {minimum_universe_count}")
        step = max(1, int(batch_size))
        for offset in range(0, len(codes), step):
            return_code, frame = context.get_market_snapshot(codes[offset : offset + step])
            if return_code != 0:
                raise SnapshotGateError(f"Futu market snapshot failed at offset {offset}")
            batch_codes: set[str] = set()
            for item in _frame_records(frame):
                code = str(item.get("code") or "").strip().upper()
                if not code or code not in universe:
                    raise SnapshotGateError(
                        f"Futu market snapshot returned unmatched code: {code!r}"
                    )
                if code in batch_codes:
                    raise SnapshotGateError(
                        f"Futu market snapshot returned duplicate code: {code}"
                    )
                batch_codes.add(code)
                snapshots[code] = item
    finally:
        close = getattr(context, "close", None)
        if callable(close):
            close()
    rows: list[dict[str, Any]] = []
    excluded: dict[str, list[str]] = {}
    positive_volume_count = 0
    positive_turnover_count = 0
    required_fields = ("open_price", "high_price", "low_price", "last_price", "volume", "turnover")
    for code in codes:
        source = snapshots.get(code) or {}
        if _compact_datetime(source.get("update_time")) != target:
            excluded[code] = ["stale_or_missing_date"]
            continue
        missing = [field for field in required_fields if field not in source or source.get(field) in (None, "")]
        if missing:
            excluded[code] = [f"missing_{field}" for field in missing]
            continue
        try:
            open_price = _number(source, "open_price")
            high_price = _number(source, "high_price")
            low_price = _number(source, "low_price")
            last_price = _number(source, "last_price")
            volume = _number(source, "volume")
            turnover = _number(source, "turnover")
        except (TypeError, ValueError, SnapshotGateError):
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
        if min(open_price, high_price, low_price, last_price) <= 0 or high_price < low_price or last_price < low_price or last_price > high_price:
            reasons.append("non_positive_ohlc")
        if reasons:
            excluded[code] = reasons
            continue
        try:
            row = {
                "trade_date": target,
                "code": code,
                "name": str(source.get("name") or universe.get(code) or "").strip(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": last_price,
                "volume": int(round(volume)),
                "turnover": turnover,
                "source": "FUTU_HKCONNECT_SNAPSHOT",
            }
            rows.append(row)
        except (TypeError, ValueError, SnapshotGateError):
            excluded[code] = ["row_encoding_error"]
            continue
    coverage = len(rows) / max(len(codes), 1)
    positive_volume_coverage = positive_volume_count / max(len(codes), 1)
    positive_turnover_coverage = positive_turnover_count / max(len(codes), 1)
    minimum_universe = max(600, int(minimum_universe_count))
    if len(rows) < minimum_universe:
        raise SnapshotGateError(
            "HK exact-date coverage below gate: "
            f"universe={len(codes)},rows={len(rows)},coverage={coverage:.8f}"
        )
    if positive_volume_coverage + 1e-12 < 0.8 or positive_turnover_coverage + 1e-12 < 0.8:
        raise SnapshotGateError(
            "HK positive-trade coverage below gate: "
            f"volume={positive_volume_coverage:.8f},turnover={positive_turnover_coverage:.8f}"
        )
    if coverage + 1e-12 < float(required_coverage_ratio):
        raise SnapshotGateError(f"HK exact-date coverage below gate: universe={len(codes)},rows={len(rows)},coverage={coverage:.8f}")
    evidence_codes = sorted(excluded)
    evidence_codes_limited = evidence_codes[:MAX_EXCLUDED_EVIDENCE]
    evidence_reasons = {code: sorted(excluded[code]) for code in evidence_codes_limited}
    source_payload = {
        "target_date": target,
        "plates": HKCONNECT_PLATE_CODES,
        "rows": rows,
        "excluded_count": len(evidence_codes),
        "excluded_codes": evidence_codes,
        "excluded_reasons": {code: sorted(excluded[code]) for code in evidence_codes},
        "positive_volume_coverage_rate": positive_volume_coverage,
        "positive_turnover_coverage_rate": positive_turnover_coverage,
    }
    source_sha = _canonical_sha(source_payload)
    security_fields = (
        "code",
        "name",
        "outstanding_shares",
        "circular_market_val",
        "listing_date",
        "lot_size",
        "stock_owner",
        "stock_child_type",
        "sec_status",
    )
    security_master_rows = [
        {
            field: (
                code
                if field == "code"
                else source.get(field)
                if field != "name"
                else str(source.get("name") or universe.get(code) or "").strip()
            )
            for field in security_fields
        }
        for code in codes
        for source in (snapshots.get(code) or {},)
    ]
    capture = {
        "schema_version": "v3.macos.research_panel_hk_capture.v1",
        "target_date": target,
        "plates": list(HKCONNECT_PLATE_CODES),
        "codes": list(codes),
        "rows": rows,
        "security_master_rows": security_master_rows,
        "source_payload": source_payload,
        "source_sha256": source_sha,
        **SAFETY_FLAGS,
    }
    capture["capture_sha256"] = _canonical_sha(capture)
    if capture_manifest_path is not None:
        capture_bytes = json.dumps(
            capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        capture_raw_sha256 = hashlib.sha256(capture_bytes).hexdigest()
        write_raw_capture(capture_bytes)
        excluded_codes = sorted(str(code) for code in excluded)
        stale_codes = sorted(
            code
            for code in excluded_codes
            if "stale_or_missing_date" in set(excluded.get(code, ()))
        )
        write_manifest(
            json.dumps(
                {
                    "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
                    "status": "READY",
                    "target_date": target,
                    "capture_run_id": capture_run_id,
                    "capture_relative_path": capture_raw_path.name,
                    "capture_path": capture_raw_path.name,
                    "capture": capture,
                    "capture_sha256": capture["capture_sha256"],
                    "capture_raw_sha256": capture_raw_sha256,
                    "codes": list(capture["codes"]),
                    "excluded_codes": excluded_codes,
                    "stale_codes": stale_codes,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    globals()["_LAST_HK_CAPTURE"] = capture
    result = {
        "status": "READY",
        "target_date": target,
        "rows": rows,
        "universe_count": len(codes),
        "row_count": len(rows),
        "coverage_rate": coverage,
        "positive_volume_coverage_rate": positive_volume_coverage,
        "positive_turnover_coverage_rate": positive_turnover_coverage,
        "excluded_count": len(evidence_codes),
        "excluded_codes": evidence_codes_limited,
        "excluded_reasons": evidence_reasons,
        "source_sha256": source_sha,
        "sha256": source_sha,
        **SAFETY_FLAGS,
    }
    if capture_metadata_enabled:
        result.update(
            {
                "capture_manifest_path": str(capture_manifest_path),
                "capture_raw_path": str(capture_raw_path),
                "capture_raw_sha256": capture_raw_sha256,
                "capture_run_id": capture_run_id,
            }
        )
    return result
