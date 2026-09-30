"""Same-day 15:45-15:55 Futu RT_DATA collection for HK Stage 8."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..acquisition import AcquisitionPlan, SourceResult
from ..live_collectors import _canonical_hk_code, _exact_market_timestamp, _safe_number
from .snapshot import (
    _canonical_snapshot_codes,
    _snapshot_codes_sha,
    _snapshot_path,
    _snapshot_rows_sha,
    load_hk_active_snapshot,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STAGE8_START_AT = "15:45:00"
_STAGE8_CAPTURE_START_AT = "15:50:00"
_STAGE8_CUTOFF_AT = "15:55:00"
_STAGE8_RT_DATA_BATCH_SIZE = 30
_STAGE8_NATURAL_SOURCE = "FUTU_RTDATA_NATURAL"

def _stage8_market_timestamp(value: Any, trade_date: str) -> datetime | None:
    """Parse an RT_DATA timestamp and normalize explicit offsets to Shanghai."""
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-").replace("Z", "+00:00")
    if re.fullmatch(r"\d{8}.*", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if not re.search(r"\d{4}-\d{2}-\d{2}", text):
        text = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {text}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    else:
        parsed = parsed.astimezone(_SHANGHAI)
    return parsed.replace(tzinfo=None)
def _rt_data_records(frame: Any) -> list[dict[str, Any]]:
    """Convert one Futu RT_DATA response without importing pandas here."""
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            values = frame.to_dict(orient="records")
        except TypeError:
            values = frame.to_dict("records")
        return [dict(row) for row in values if isinstance(row, Mapping)]
    if isinstance(frame, Mapping):
        return [dict(frame)]
    if isinstance(frame, Sequence) and not isinstance(frame, (str, bytes, bytearray)):
        return [dict(row) for row in frame if isinstance(row, Mapping)]
    return []


def _fetch_hk_stage8_rtdata(
    codes: Sequence[str],
    *,
    batch_size: int = _STAGE8_RT_DATA_BATCH_SIZE,
    quote_context_factory: Callable[..., Any] | None = None,
    futu_module: Any | None = None,
) -> dict[str, Any]:
    """Read exact-window RT_DATA in bounded subscribe/get/unsubscribe batches.

    The production path uses the installed read-only Futu package.  Tests can
    inject both the module and context factory, keeping this seam deterministic
    and preventing any real OpenD access during regression runs.
    """
    requested = _canonical_snapshot_codes(codes)
    if not requested:
        return {
            "rows": (),
            "errors": ("HK_STAGE8_RTDATA_CODE_SET_EMPTY",),
            "cleanup_warnings": (),
            "missing_codes": (),
            "batch_evidence": (),
        }
    if batch_size != _STAGE8_RT_DATA_BATCH_SIZE:
        raise ValueError("Stage 8 RT_DATA batch size must remain 30")
    if futu_module is None:
        try:
            import futu as futu_module  # type: ignore[import-not-found]
        except Exception as error:
            return {
                "rows": (),
                "errors": (f"HK_STAGE8_RTDATA_FUTU_IMPORT:{type(error).__name__}",),
                "cleanup_warnings": (),
                "missing_codes": requested,
                "batch_evidence": (),
            }
    factory = quote_context_factory or futu_module.OpenQuoteContext
    try:
        try:
            quote_ctx = factory(host="127.0.0.1", port=11111)
        except TypeError:
            quote_ctx = factory()
    except Exception as error:
        return {
            "rows": (),
            "errors": (f"HK_STAGE8_RTDATA_CONTEXT:{type(error).__name__}",),
            "cleanup_warnings": (),
            "missing_codes": requested,
            "batch_evidence": (),
        }

    ret_ok = getattr(futu_module, "RET_OK", 0)
    subtype = getattr(getattr(futu_module, "SubType", object), "RT_DATA", "RT_DATA")
    rows: list[dict[str, Any]] = []
    missing: set[str] = set()
    errors: list[str] = []
    cleanup_warnings: list[str] = []
    batch_evidence: list[str] = []
    try:
        for offset in range(0, len(requested), batch_size):
            batch = list(requested[offset : offset + batch_size])
            batch_no = offset // batch_size + 1
            subscribed = False
            ret = None
            message: Any = ""
            try:
                ret, message = quote_ctx.subscribe(
                    batch,
                    [subtype],
                    subscribe_push=False,
                )
                subscribed = ret == ret_ok
                batch_evidence.append(
                    f"stage8_rtdata_batch={batch_no};requested={len(batch)};subscribe_ok={str(subscribed).lower()}"
                )
                if not subscribed:
                    errors.append(f"HK_STAGE8_RTDATA_SUBSCRIBE_FAILED:batch={batch_no}")
                    missing.update(batch)
                    continue
                for code in batch:
                    try:
                        row_ret, data = quote_ctx.get_rt_data(code)
                    except Exception as error:
                        errors.append(f"HK_STAGE8_RTDATA_GET_ERROR:{code}:{type(error).__name__}")
                        missing.add(code)
                        continue
                    if row_ret != ret_ok:
                        errors.append(f"HK_STAGE8_RTDATA_GET_FAILED:{code}")
                        missing.add(code)
                        continue
                    records = _rt_data_records(data)
                    if not records:
                        errors.append(f"HK_STAGE8_RTDATA_EMPTY:{code}")
                        missing.add(code)
                        continue
                    rows.extend(records)
            except Exception as error:
                errors.append(f"HK_STAGE8_RTDATA_SUBSCRIBE_ERROR:batch={batch_no}:{type(error).__name__}")
                missing.update(batch)
            finally:
                if subscribed:
                    try:
                        unsub_ret = quote_ctx.unsubscribe(batch, [subtype])
                        if unsub_ret is None:
                            unsub_ok = True
                        elif isinstance(unsub_ret, (tuple, list)):
                            unsub_ok = not unsub_ret or unsub_ret[0] == ret_ok
                        else:
                            unsub_ok = unsub_ret == ret_ok or unsub_ret is True
                        batch_evidence.append(
                            f"stage8_rtdata_batch={batch_no};unsubscribe_ok={str(unsub_ok).lower()}"
                        )
                        if not unsub_ok:
                            warning = f"HK_STAGE8_RTDATA_UNSUBSCRIBE_FAILED:batch={batch_no}"
                            errors.append(warning)
                            cleanup_warnings.append(warning)
                    except Exception as error:
                        warning = f"HK_STAGE8_RTDATA_UNSUBSCRIBE_ERROR:batch={batch_no}:{type(error).__name__}"
                        errors.append(warning)
                        cleanup_warnings.append(warning)
    finally:
        try:
            quote_ctx.close()
        except Exception as error:
            warning = f"HK_STAGE8_RTDATA_CLOSE_ERROR:{type(error).__name__}"
            errors.append(warning)
            cleanup_warnings.append(warning)
    rows_by_code = {
        _canonical_hk_code(row.get("code") or row.get("symbol")): row
        for row in rows
        if _canonical_hk_code(row.get("code") or row.get("symbol"))
    }
    missing.update(code for code in requested if code not in rows_by_code)
    return {
        "rows": tuple(rows),
        "errors": tuple(dict.fromkeys(errors)),
        "cleanup_warnings": tuple(dict.fromkeys(cleanup_warnings)),
        "missing_codes": tuple(sorted(missing)),
        "batch_evidence": tuple(batch_evidence),
        "requested_code_count": len(requested),
        "completed_code_count": len(rows_by_code),
    }


def _stage8_active_snapshot_codes(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Select the frozen LIVE HK gainer lane from the full-scan snapshot."""
    active: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        code = _canonical_hk_code(row.get("code"))
        previous = _safe_number(row.get("prev_close_price") or row.get("prev_close"))
        last = _safe_number(row.get("last_price") or row.get("last"))
        turnover = _safe_number(row.get("turnover"))
        volume_ratio = _safe_number(row.get("volume_ratio"))
        pct = ((last - previous) / previous * 100.0) if last is not None and previous not in (None, 0) else None
        if (
            code
            and pct is not None
            and pct > 0
            and turnover is not None
            and turnover >= 20_000_000
            and volume_ratio is not None
            and volume_ratio >= 1
        ):
            active[code] = row
    return active


def _stage8_aggregate_rtdata_rows(
    series: Sequence[tuple[datetime, Mapping[str, Any]]],
    *,
    code: str,
    active_snapshot_row: Mapping[str, Any],
    trade_date: str,
    batch_index: int,
) -> dict[str, Any]:
    """Aggregate every exact-window RT_DATA row into one replay-equivalent row."""
    ordered = sorted(series, key=lambda item: item[0])
    first_time, first = ordered[0]
    last_time, last = ordered[-1]
    prices = [
        value
        for value in (
            _safe_number(row.get("cur_price") or row.get("last_price") or row.get("last"))
            for _when, row in ordered
        )
        if value is not None
    ]
    first_price = prices[0] if prices else None
    last_price = prices[-1] if prices else None
    previous = _safe_number(
        active_snapshot_row.get("prev_close_price")
        or first.get("last_close")
        or first.get("prev_close_price")
        or first.get("prev_close")
    )
    turnover = sum(_safe_number(row.get("turnover") or row.get("turnover_hkd")) or 0.0 for _when, row in ordered)
    volume = sum(_safe_number(row.get("volume")) or 0.0 for _when, row in ordered)
    high_values = [
        value
        for value in (
            _safe_number(row.get("high") or row.get("high_price"))
            for _when, row in ordered
        )
        if value is not None
    ]
    low_values = [
        value
        for value in (
            _safe_number(row.get("low") or row.get("low_price"))
            for _when, row in ordered
        )
        if value is not None
    ]
    last_time_text = last_time.strftime("%Y-%m-%d %H:%M:%S")
    first_time_text = first_time.strftime("%Y-%m-%d %H:%M:%S")
    pct = ((last_price - previous) / previous * 100.0) if last_price is not None and previous not in (None, 0) else None
    window_change = ((last_price - first_price) / first_price * 100.0) if last_price is not None and first_price not in (None, 0) else None
    volume_ratio = _safe_number(active_snapshot_row.get("volume_ratio"))
    return {
        "batch_index": batch_index,
        "code": code,
        "name": last.get("name") or last.get("stock_name") or first.get("name") or code,
        "update_time": last_time_text,
        "last_price": last_price,
        "open_price": _safe_number(first.get("open") or first.get("open_price")) or first_price,
        "high_price": max(high_values or prices or [last_price or 0.0]),
        "low_price": min(low_values or prices or [last_price or 0.0]),
        "prev_close_price": previous,
        "turnover": turnover,
        "volume": volume,
        "bid_price": _safe_number(last.get("bid_price")) or "",
        "ask_price": _safe_number(last.get("ask_price")) or "",
        "bid_vol": _safe_number(last.get("bid_vol")) or "",
        "ask_vol": _safe_number(last.get("ask_vol")) or "",
        "window_start": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {_STAGE8_START_AT}",
        "window_end": last_time_text,
        "bar_count": len(ordered),
        "temporal_cutoff_safe": True,
        "pct_chg": pct,
        "volume_ratio": volume_ratio,
        "turnover_hkd": turnover,
        "turnover_hkd_yi": turnover / 100_000_000,
        "stage_turnover_hkd": turnover,
        "stage_turnover_hkd_yi": turnover / 100_000_000,
        "stage_volume": volume,
        "stage_first_price": first_price,
        "stage_last_price": last_price,
        "stage_high_price": max(high_values or prices or [last_price or 0.0]),
        "stage_low_price": min(low_values or prices or [last_price or 0.0]),
        "stage_window_change_pct": window_change,
        "stage_cumulative_pct_chg": pct,
        "stage_replay_latest_time": last_time_text,
        "stage_replay_bar_count": len(ordered),
        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        "source_universe": "LIVE_HKCONNECT_GAINER",
        "active_gainer_pass": True,
        "stage_id": "STAGE_1545_1555",
        "trade_date": trade_date,
        "rtdata_first_time": first_time_text,
        "rtdata_latest_time": last_time_text,
    }


def _collect_hk_stage8_natural(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    snapshot_root: Path | str,
    rtdata_provider: Callable[..., Mapping[str, Any]] | None = None,
    natural_now: datetime | None = None,
) -> SourceResult:
    """Consume due-time RT_DATA using only the pre-captured full-scan lane."""
    now = natural_now or datetime.now(_SHANGHAI)
    now = now.astimezone(_SHANGHAI) if now.tzinfo is not None else now.replace(tzinfo=_SHANGHAI)
    requested = _canonical_snapshot_codes(codes)
    evidence = (
        "route=hk_connect_stage8_natural_rtd_data",
        f"stage8_source={_STAGE8_NATURAL_SOURCE}",
        "stage8_exact_date=true",
        "stage8_exact_window=15:45:00-15:55:00",
        "stage8_precapture_source=FUTU_HKCONNECT_FULL_SCAN",
    )
    if now.strftime("%Y%m%d") != plan.trade_date:
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=len(requested), cannot_confirm=("HK_STAGE8_NATURAL_TRADE_DATE_REQUIRED",), source_evidence=evidence)
    cutoff = _exact_market_timestamp(
        f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]}T{_STAGE8_CUTOFF_AT}",
        plan.trade_date,
    )
    if cutoff is None or now.replace(tzinfo=None) < cutoff:
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=len(requested), cannot_confirm=("HK_STAGE8_CUTOFF_NOT_REACHED",), source_evidence=evidence)
    path = _snapshot_path(snapshot_root, plan.trade_date, plan.stage_id)
    loaded = load_hk_active_snapshot(snapshot_root, trade_date=plan.trade_date, stage_id=plan.stage_id, codes=requested, cutoff_at=_STAGE8_CUTOFF_AT)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        payload = {}
    if loaded["status"] != "READY" or payload.get("source_role") != "FUTU_HKCONNECT_FULL_SCAN":
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=len(requested), cannot_confirm=tuple(dict.fromkeys((*loaded.get("cannot_confirm", ()), "HK_STAGE8_ACTIVE_SNAPSHOT_UNAVAILABLE"))), source_evidence=tuple(dict.fromkeys((*evidence, *loaded.get("source_evidence", ())))))
    active_snapshot_rows = _stage8_active_snapshot_codes(loaded.get("rows", ()))
    active_codes = tuple(sorted(active_snapshot_rows))
    active_codes_sha = _snapshot_codes_sha(active_codes)
    active_evidence = (
        f"stage8_active_snapshot_sha256={loaded.get('active_snapshot_sha256', '')}",
        f"stage8_active_codes_sha256={active_codes_sha}",
        f"stage8_active_code_count={len(active_codes)}",
    )
    if not active_codes:
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=0, cannot_confirm=("HK_STAGE8_ACTIVE_CODES_EMPTY",), source_evidence=tuple(dict.fromkeys((*evidence, *active_evidence))))
    provider = rtdata_provider or _fetch_hk_stage8_rtdata
    try:
        fetched = dict(provider(active_codes, batch_size=_STAGE8_RT_DATA_BATCH_SIZE))
    except Exception as error:
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=len(active_codes), cannot_confirm=(f"HK_STAGE8_RTDATA_PROVIDER_ERROR:{type(error).__name__}",), source_evidence=tuple(dict.fromkeys((*evidence, *active_evidence))))
    stage_start = _exact_market_timestamp(f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]}T{_STAGE8_START_AT}", plan.trade_date)
    raw_by_code: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = {}
    temporal_error = False
    outside_window_count = 0
    before_window_count = 0
    after_window_count = 0
    invalid_timestamp_count = 0
    cross_day_count = 0
    for raw in (fetched.get("rows") or ()):
        if not isinstance(raw, Mapping):
            continue
        code = _canonical_hk_code(raw.get("code") or raw.get("symbol") or raw.get("stock_code"))
        if code not in active_snapshot_rows:
            continue
        when = _stage8_market_timestamp(raw.get("time") or raw.get("update_time"), plan.trade_date)
        if when is None:
            temporal_error = True
            invalid_timestamp_count += 1
            continue
        if when.strftime("%Y%m%d") != plan.trade_date:
            temporal_error = True
            cross_day_count += 1
            continue
        if stage_start is None or cutoff is None:
            temporal_error = True
            invalid_timestamp_count += 1
            continue
        if when < stage_start:
            outside_window_count += 1
            before_window_count += 1
            continue
        if when > cutoff:
            outside_window_count += 1
            after_window_count += 1
            continue
        if raw.get("is_blank") is True or str(raw.get("is_blank") or "").strip().lower() == "true":
            temporal_error = True
            invalid_timestamp_count += 1
            continue
        raw_by_code.setdefault(code, []).append((when, dict(raw)))
    missing = tuple(sorted(set(active_codes) - set(raw_by_code)))
    cleanup_warnings = tuple(str(item) for item in (fetched.get("cleanup_warnings") or ()) if str(item))
    provider_errors = tuple(
        str(item)
        for item in (fetched.get("errors") or ())
        if str(item) and str(item) not in cleanup_warnings
    )
    cannot = list(provider_errors)
    if temporal_error:
        cannot.append("HK_STAGE8_RTDATA_TEMPORAL_CUTOFF_UNSAFE")
    if missing:
        cannot.append("HK_STAGE8_RTDATA_ROWS_MISSING")
    row_evidence = tuple(
        f"stage8_rtdata_raw_row_sha256={code}:{_snapshot_rows_sha([dict(row) for _when, row in series])}"
        for code, series in sorted(raw_by_code.items())
    )
    source_evidence = tuple(
        dict.fromkeys(
            (
                *evidence,
                *active_evidence,
                f"stage8_rtdata_requested_code_count={len(active_codes)}",
                f"stage8_rtdata_completed_code_count={len(raw_by_code)}",
                f"stage8_rtdata_missing_code_count={len(missing)}",
                f"stage8_rtdata_outside_window_count={outside_window_count}",
                f"stage8_rtdata_before_window_count={before_window_count}",
                f"stage8_rtdata_after_window_count={after_window_count}",
                f"stage8_rtdata_invalid_timestamp_count={invalid_timestamp_count}",
                f"stage8_rtdata_cross_day_count={cross_day_count}",
                "stage8_rtdata_future_rows=0",
                *cleanup_warnings,
                *tuple(fetched.get("batch_evidence") or ()),
                *row_evidence,
            )
        )
    )
    if temporal_error:
        return SourceResult("futu_hkconnect_stage8_natural_rtdata", "CANNOT_CONFIRM", requested_rows=len(active_codes), missing_symbols=missing, cannot_confirm=tuple(dict.fromkeys(cannot)), source_evidence=source_evidence)
    rows = tuple(
        _stage8_aggregate_rtdata_rows(raw_by_code[code], code=code, active_snapshot_row=active_snapshot_rows[code], trade_date=plan.trade_date, batch_index=index)
        for index, code in enumerate(sorted(raw_by_code), start=1)
    )
    status = "READY" if not missing and not provider_errors else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
    return SourceResult("futu_hkconnect_stage8_natural_rtdata", status, rows=rows, requested_rows=len(active_codes), missing_symbols=missing, cannot_confirm=tuple(dict.fromkeys(cannot)), source_evidence=source_evidence)
