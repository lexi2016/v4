"""stage_center.live_collectors: hk_auction (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _collect_hk_auction_body(_v4_scope, /, plan, *, codes, python_path, shared_root, auction_root, process_runner, replay_provider):
    """Exact 09:15-09:20 HK route using the existing shared_data capture."""
    if plan.stage_id != "STAGE_0925":
        raise _v4_global(_v4_scope, 'ValueError')("HK auction collector is restricted to STAGE_0925")
    root = _v4_global(_v4_scope, 'Path')(auction_root).expanduser().resolve() if auction_root is not None else None
    csv_path = None
    if root is not None:
        stem = f"hkconnect_0920_auction_second_filter_{plan.trade_date}.csv"
        candidates = (root if root.is_file() else root / stem, root / plan.trade_date / stem, root / "0920_auction_second_filter" / stem)
        csv_path = _v4_global(_v4_scope, 'next')((candidate for candidate in candidates if candidate.is_file()), None)
    if csv_path is not None:
        rows: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for raw in _v4_global(_v4_scope, 'csv').DictReader(stream):
                code = _v4_global(_v4_scope, '_canonical_hk_code')(raw.get("code") or raw.get("ts_code") or raw.get("stock_code"))
                if not code:
                    continue
                update = _v4_global(_v4_scope, 'str')(raw.get("collector_wall_time") or raw.get("update_time") or f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:19:59")
                rows.append({
                    "batch_index": _v4_global(_v4_scope, 'len')(rows) + 1,
                    "code": code,
                    "name": raw.get("name") or code,
                    "update_time": update,
                    "last_price": _v4_global(_v4_scope, '_safe_number')(raw.get("last_price")) or 0.0,
                    "open_price": _v4_global(_v4_scope, '_safe_number')(raw.get("reference_price_hkd") or raw.get("last_price")) or 0.0,
                    "high_price": _v4_global(_v4_scope, '_safe_number')(raw.get("last_price")) or 0.0,
                    "low_price": _v4_global(_v4_scope, '_safe_number')(raw.get("last_price")) or 0.0,
                    "prev_close_price": _v4_global(_v4_scope, '_safe_number')(raw.get("prev_close_price")) or 0.0,
                    "turnover": _v4_global(_v4_scope, '_safe_number')(raw.get("turnover")) or 0.0,
                    "volume": _v4_global(_v4_scope, '_safe_number')(raw.get("volume")) or 0.0,
                    "bid_price": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_price")) or "",
                    "ask_price": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_price")) or "",
                    "bid_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("bid_vol")) or "",
                    "ask_vol": _v4_global(_v4_scope, '_safe_number')(raw.get("ask_vol")) or "",
                    "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:15:00",
                    "window_end": update,
                    "bar_count": 1,
                    "temporal_cutoff_safe": True,
                    "target_date": plan.trade_date,
                    "signal_date": raw.get("signal_date") or "",
                    "rank": raw.get("rank") or "",
                    "auction_score": raw.get("auction_score") or raw.get("stage1_ref_score") or 0.0,
                    "second_filter_status": raw.get("second_filter_status") or "WATCH_ONLY",
                    "preselect_lane": raw.get("preselect_lane") or "",
                    "reference_price_hkd": raw.get("reference_price_hkd") or raw.get("last_price") or "",
                    "strict_failure_price_hkd": raw.get("strict_failure_price_hkd") or raw.get("bid_price") or "",
                })
        status = "READY" if rows else "CANNOT_CONFIRM"
        return _v4_global(_v4_scope, 'SourceResult')("hk_auction_second_filter", status, _v4_global(_v4_scope, 'tuple')(rows), requested_rows=_v4_global(_v4_scope, 'len')(codes), missing_symbols=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(codes) - {_v4_global(_v4_scope, 'str')(row["code"]) for row in rows})), cannot_confirm=() if rows else ("HK_0920_EXACT_SECOND_FILTER_ROWS_MISSING",), source_evidence=("route=hk_connect_0915_0920_auction_second_filter", "exact_date=true", f"second_filter_csv={csv_path}", f"second_filter_csv_sha256={_v4_global(_v4_scope, '_sha_file')(csv_path)}"))
    return _v4_global(_v4_scope, '_collect_hk_0925_replay')(
        plan,
        codes=codes,
        replay_provider=replay_provider,
    )
