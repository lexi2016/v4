"""stage_center.live_collectors: a_auction (review candidate, not deployment)."""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from ._namespace import read_global as _v4_global

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _shanghai_datetime(value: str) -> datetime:
    """Parse an ISO timestamp as Shanghai market time, preserving offsets."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def _collect_a_share_auction_body(_v4_scope, /, plan, *, codes, python_path, shared_root, auction_root, process_runner, replay_provider):
    """Read the exact-date V3 auction artifact; never substitute minute bars."""
    if plan.stage_id != "STAGE_0925":
        raise _v4_global(_v4_scope, 'ValueError')("A auction collector is restricted to STAGE_0925")
    root = _v4_global(_v4_scope, 'Path')(auction_root).expanduser().resolve() if auction_root is not None else None
    csv_path = (
        root / "generated_stages" / plan.trade_date / f"generated_stage1_0925_auction_{plan.trade_date}.csv"
        if root is not None else None
    )
    if csv_path is not None and csv_path.is_file():
        rows: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for raw in _v4_global(_v4_scope, 'csv').DictReader(stream):
                code = _v4_global(_v4_scope, '_canonical_a_code')(raw.get("ts_code") or raw.get("stock_code") or raw.get("code"))
                when = _v4_global(_v4_scope, '_auction_time')(raw.get("last_time") or raw.get("first_time") or raw.get("update_time"), plan.trade_date)
                if not code or not when:
                    continue
                amount = _v4_global(_v4_scope, '_safe_number')(raw.get("amount_in_window") or raw.get("auction_amount_est_yuan") or raw.get("amount"))
                price = _v4_global(_v4_scope, '_safe_number')(raw.get("last_close") or raw.get("first_open") or raw.get("last_price"))
                rows.append({
                    "batch_index": _v4_global(_v4_scope, 'len')(rows) + 1,
                    "code": code,
                    "name": raw.get("name") or raw.get("display_name") or code,
                    "update_time": when,
                    "last_price": price,
                    "open_price": _v4_global(_v4_scope, '_safe_number')(raw.get("first_open")) or price,
                    "high_price": _v4_global(_v4_scope, '_safe_number')(raw.get("high_price")) or price,
                    "low_price": _v4_global(_v4_scope, '_safe_number')(raw.get("low_price")) or price,
                    "prev_close_price": _v4_global(_v4_scope, '_safe_number')(raw.get("prev_close_price")),
                    "turnover": amount or 0.0,
                    "volume": _v4_global(_v4_scope, '_safe_number')(raw.get("volume")) or 0.0,
                    "bid_price": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_price")) or "",
                    "ask_price": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_price")) or "",
                    "bid_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_vol")) or "",
                    "ask_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_vol")) or "",
                    "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:20:00",
                    "window_end": when,
                    "bar_count": 1,
                    "temporal_cutoff_safe": True,
                    "time": when,
                    "amount": amount or 0.0,
                    "trade_date": plan.trade_date,
                    "is_open_call_auction_match": True,
                })
        status = "READY" if _v4_global(_v4_scope, 'len')(rows) >= _v4_global(_v4_scope, 'len')(codes) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return _v4_global(_v4_scope, 'SourceResult')(
            source_id="a_share_auction",
            status=status,
            rows=_v4_global(_v4_scope, 'tuple')(rows),
            cannot_confirm=() if status == "READY" else (f"A_0925_EXACT_AUCTION_ROWS_{_v4_global(_v4_scope, 'len')(rows)}/{_v4_global(_v4_scope, 'len')(codes)}",),
            requested_rows=_v4_global(_v4_scope, 'len')(codes),
            missing_symbols=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(codes) - {_v4_global(_v4_scope, 'str')(row["code"]) for row in rows})),
            source_evidence=("route=a_share_exact_date_auction_transaction", "exact_date=true", f"auction_csv={csv_path}", f"auction_csv_sha256={_v4_global(_v4_scope, '_sha_file')(csv_path)}"),
        )
    # The generated CSV is the preferred exact artifact.  When it is absent,
    # replay the same date/cutoff through the existing read-only PyTDX history
    # provider.  This is deliberately a narrow fallback: it never reads a
    # current snapshot and never turns L0 transaction data into an order book.
    cutoff_iso = _v4_global(_v4_scope, '_stage_0925_cutoff_iso')(plan.trade_date)
    replay_evidence = (
        "route=a_share_exact_date_auction_transaction",
        "exact_date=true",
        "replay_method=pytdx.hq.get_history_transaction_data",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_iso}",
    )
    try:
        if replay_provider is None:
            from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider

            replay_provider = TdxMinuteReplayProvider()
        payload = replay_provider.snapshot(
            _v4_global(_v4_scope, 'tuple')(codes),
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_iso,
        )
        if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("replay payload must be a mapping")
        if _v4_global(_v4_scope, 'str')(payload.get("trade_date") or plan.trade_date) != plan.trade_date:
            raise _v4_global(_v4_scope, 'ValueError')("replay trade_date mismatch")
        if _v4_global(_v4_scope, 'str')(payload.get("stage_id") or plan.stage_id) != plan.stage_id:
            raise _v4_global(_v4_scope, 'ValueError')("replay stage_id mismatch")
        if payload.get("temporal_cutoff_safe") is not True:
            raise _v4_global(_v4_scope, 'ValueError')("replay temporal cutoff is not safe")
        for safety_key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            if payload.get(safety_key) is not False:
                raise _v4_global(_v4_scope, 'ValueError')(f"replay safety flag {safety_key} must be false")
        captured_at = _v4_global(_v4_scope, 'str')(payload.get("captured_at") or "")
        captured = _shanghai_datetime(captured_at)
        cutoff = _shanghai_datetime(cutoff_iso)
        market_cutoff_at = _v4_global(_v4_scope, 'str')(payload.get("market_cutoff_at") or "")
        if not market_cutoff_at:
            raise _v4_global(_v4_scope, 'ValueError')("replay market_cutoff_at is missing")
        market_cutoff = _shanghai_datetime(market_cutoff_at)
        capture_mode = _v4_global(_v4_scope, 'str')(payload.get("capture_mode") or "").strip().upper()
        if capture_mode not in {"NATURAL", "RECOVERY"}:
            raise _v4_global(_v4_scope, 'ValueError')("replay capture_mode is missing or invalid")
        if (
            market_cutoff != cutoff
            or (
                capture_mode == "NATURAL"
                and (captured.strftime("%Y%m%d") != plan.trade_date or captured > cutoff)
            )
            or (capture_mode == "RECOVERY" and captured <= cutoff)
        ):
            raise _v4_global(_v4_scope, 'ValueError')("replay captured_at is outside exact date/cutoff")
        raw_rows = payload.get("rows")
        if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
            raise _v4_global(_v4_scope, 'ValueError')("replay rows must be a sequence")
        envelope_method = _v4_global(_v4_scope, 'str')(payload.get("source_method") or "").strip()
        row_methods = [
            _v4_global(_v4_scope, 'str')(raw.get("source_method") or "").strip()
            for raw in raw_rows
            if _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping'))
        ]
        source_methods = {method for method in row_methods if method}
        replay_method = envelope_method or (
            next(iter(source_methods)) if len(source_methods) == 1 and all(row_methods) else ""
        )
        if replay_method not in {
            "pytdx.hq.get_transaction_data",
            "pytdx.hq.get_history_transaction_data",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("replay source_method is missing or untrusted")
        if any(method and method != replay_method for method in row_methods):
            raise _v4_global(_v4_scope, 'ValueError')("replay source_method does not match row evidence")
        requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, '_canonical_a_code')(code) for code in codes if _v4_global(_v4_scope, '_canonical_a_code')(code)))
        by_code: dict[str, dict[str, Any]] = {}
        invalid_rows: list[str] = []
        expected_tick_time = f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:25:00"
        for raw in raw_rows:
            if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
                invalid_rows.append("non_mapping_row")
                continue
            code = _v4_global(_v4_scope, '_canonical_a_code')(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _v4_global(_v4_scope, '_replay_auction_time')(raw.get("source_last_tick_time") or raw.get("time") or captured_at, plan.trade_date)
            if update_time != expected_tick_time:
                invalid_rows.append(code or "unknown_code")
                continue
            numeric = {
                key: _v4_global(_v4_scope, '_safe_number')(raw.get(key))
                for key in ("open_price", "last_price", "high_price", "low_price", "prev_close_price", "turnover", "volume")
            }
            if update_time is None or _v4_global(_v4_scope, 'any')(numeric[key] is None for key in ("open_price", "last_price", "high_price", "low_price", "turnover", "volume")):
                invalid_rows.append(code or "unknown_code")
                continue
            by_code[code] = {
                "batch_index": _v4_global(_v4_scope, 'len')(by_code) + 1,
                "code": code,
                "name": raw.get("name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "update_time": update_time,
                "time": update_time,
                "last_price": numeric["last_price"],
                "open_price": numeric["open_price"],
                "high_price": numeric["high_price"],
                "low_price": numeric["low_price"],
                "prev_close_price": numeric["prev_close_price"],
                "turnover": numeric["turnover"],
                "amount": numeric["turnover"],
                "volume": numeric["volume"],
                "bid_price": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_price") or raw.get("bid_price1")) or "",
                "ask_price": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_price") or raw.get("ask_price1")) or "",
                "bid_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_vol") or raw.get("bid_vol1")) or "",
                "ask_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_vol") or raw.get("ask_vol1")) or "",
                "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:20:00",
                "window_end": update_time,
                "bar_count": raw.get("source_tick_count", 1),
                "temporal_cutoff_safe": True,
                "trade_date": plan.trade_date,
                "is_open_call_auction_match": True,
                "source_method": raw.get("source_method") or replay_method,
                "source_last_tick_time": raw.get("source_last_tick_time") or update_time,
            }
        rows = _v4_global(_v4_scope, 'tuple')(by_code[code] for code in requested if code in by_code)
        missing = _v4_global(_v4_scope, 'tuple')(code for code in requested if code not in by_code)
        cannot = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'str')(item) for item in (payload.get("cannot_confirm") or ()) if _v4_global(_v4_scope, 'str')(item))
        if capture_mode == "RECOVERY":
            cannot.append("CANNOT_CONFIRM_NATURAL_0925_CAPTURE_RECOVERY_ONLY")
        if missing:
            cannot.append("PYTDX_0925_AUCTION_ROWS_MISSING: " + ", ".join(missing))
        if invalid_rows:
            cannot.append("PYTDX_0925_INVALID_ROWS: " + ", ".join(_v4_global(_v4_scope, 'dict').fromkeys(invalid_rows)))
        status = "READY" if _v4_global(_v4_scope, 'len')(rows) == _v4_global(_v4_scope, 'len')(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return _v4_global(_v4_scope, 'SourceResult')(
            source_id="a_share_auction",
            status=status,
            rows=rows,
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(cannot)),
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            missing_symbols=missing,
            source_evidence=_v4_global(_v4_scope, 'tuple')(
                _v4_global(_v4_scope, 'dict').fromkeys(
                    (
                        *replay_evidence,
                        f"replay_method={replay_method}",
                        f"replay_source={payload.get('source') or 'PYTDX_A_SHARE_0925_HISTORY_TRANSACTION'}",
                        f"replay_captured_at={captured_at}",
                        f"replay_capture_mode={capture_mode}",
                        f"replay_market_cutoff_at={market_cutoff_at}",
                        "replay_temporal_cutoff_safe=true",
                    )
                )
            ),
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return _v4_global(_v4_scope, 'SourceResult')(
            source_id="a_share_auction",
            status="CANNOT_CONFIRM",
            cannot_confirm=(f"PYTDX_0925_REPLAY_ERROR:{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",),
            error=_v4_global(_v4_scope, 'str')(error),
            requested_rows=_v4_global(_v4_scope, 'len')(codes),
            source_evidence=replay_evidence,
        )
