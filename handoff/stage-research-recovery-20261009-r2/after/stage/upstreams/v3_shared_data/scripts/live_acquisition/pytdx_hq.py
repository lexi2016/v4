"""Fail-closed PyTDX HQ collector for North Exchange A-share minutes.

The shared stage bundle keeps Shanghai/Shenzhen on the Futu bridge and sends
only canonical ``BJ.920xxx`` symbols through this isolated market-2 probe.
The probe requests the exact historical trade date; the collector then applies
the frozen stage window and never synthesizes a missing bar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .contracts import STAGE_WINDOWS, StageSourceResult, market_role
from .futu_minute import aggregate_futu_minute_window_rows

MARKER = "__PYTDX_HQ_MINUTE_JSON__"
MARKET_BJ = 2
_MARKET_BY_PREFIX = {"SH": 1, "SZ": 0, "BJ": MARKET_BJ}
_A_SHARE_RE = re.compile(r"^(SH|SZ|BJ)\.\d{6}$")
PYTDX_HQ_BATCH_SIZE = 32
PYTDX_HQ_BATCH_TIMEOUT_SECONDS = 180.0


# Fixed subprocess probe.  It deliberately imports only pytdx.hq and uses the
# exact market/date call; it does not import either V3 or V3.5 code.
_PYTDX_HQ_PROBE = r"""
import json
import sys
from datetime import datetime

from pytdx.config.hosts import hq_hosts
from pytdx.hq import TdxHq_API

MARKER = "__PYTDX_HQ_MINUTE_JSON__"

payload = json.loads(sys.stdin.read())
trade_date = str(payload["trade_date"])
codes = list(payload["codes"])
market_by_code = payload.get("market_by_code")
if not isinstance(market_by_code, dict):
    market = int(payload.get("market") or 0)
    market_by_code = {code: market for code in codes}
else:
    market_by_code = {str(code): int(value) for code, value in market_by_code.items()}
if any(int(market_by_code.get(code, -1)) not in (0, 1, 2) for code in codes):
    raise ValueError("PyTDX HQ market mapping must use SH=1, SZ=0, BJ=2")

def fixed_minute_times():
    '''Return the fixed A-share 1-minute sequence used by the legacy V3.

    ``get_history_minute_time_data`` does not transmit a timestamp; its rows
    are ordered deltas.  The shared contract therefore binds row index to the
    trading-minute sequence, with the first 120 rows representing the morning
    session and later rows continuing at 13:01.
    '''
    labels = []
    hour, minute = 9, 31
    while (hour, minute) <= (11, 30):
        labels.append(f"{hour:02d}:{minute:02d}")
        minute += 1
        if minute == 60:
            hour += 1
            minute = 0
    hour, minute = 13, 1
    while (hour, minute) <= (15, 0):
        labels.append(f"{hour:02d}:{minute:02d}")
        minute += 1
        if minute == 60:
            hour += 1
            minute = 0
    return labels

MINUTE_TIMES = fixed_minute_times()

def parse_datetime(row):
    value = row.get("datetime") or row.get("time") or row.get("time_key")
    if value:
        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
    fields = ("year", "month", "day", "hour", "minute")
    if all(field in row for field in fields):
        return datetime(
            int(row["year"]), int(row["month"]), int(row["day"]),
            int(row["hour"]), int(row["minute"]),
        )
    raise ValueError("PyTDX HQ row has no parseable datetime")

def number(row, *fields):
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return row[field]
    return None

def normalize_rows(code, source_rows, trade_date):
    target = datetime.strptime(trade_date, "%Y%m%d").date()
    source_rows = list(source_rows or [])
    parsed = []
    unstamped = []
    for row in source_rows:
        try:
            parsed.append((parse_datetime(row), row))
        except ValueError:
            unstamped.append(row)
    if unstamped:
        if parsed:
            raise ValueError("PyTDX HQ response mixes stamped and unstamped rows")
        if len(source_rows) > len(MINUTE_TIMES):
            raise ValueError(
                f"PyTDX HQ response has {len(source_rows)} rows; "
                f"fixed sequence supports at most {len(MINUTE_TIMES)}"
            )
        parsed = [
            (
                datetime.combine(
                    target,
                    datetime.strptime(MINUTE_TIMES[index], "%H:%M").time(),
                ),
                row,
            )
            for index, row in enumerate(source_rows)
        ]
    parsed.sort(key=lambda item: item[0])
    day_rows = [(when, row) for when, row in parsed if when.date() == target]
    out = []
    previous_close = None
    for when, row in day_rows:
        if previous_close is None:
            previous_close = number(row, "last_close", "prev_close", "pre_close")
            if isinstance(previous_close, bool):
                previous_close = None
        price = number(row, "price", "close")
        out.append({
            "time_key": when.strftime("%Y-%m-%d %H:%M:%S"),
            "code": code,
            "name": str(row.get("name") or code),
            # The HQ wire response has only price/vol.  Reusing the same
            # observed price for OHLC preserves a verifiable stage basis;
            # previous-close remains None unless the source explicitly sends
            # one and is never inferred from the current price.
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": number(row, "vol", "volume"),
            "turnover": number(row, "amount", "turnover"),
            "last_close": previous_close,
        })
    return out

def connect_first_available():
    errors = []
    for _name, host, port in hq_hosts[:80]:
        api = TdxHq_API(multithread=True)
        try:
            if api.connect(host, port, time_out=1.5):
                return api, f"{host}:{port}"
        except Exception as exc:
            errors.append(f"{host}:{port} {type(exc).__name__}: {exc}")
        try:
            api.disconnect()
        except Exception:
            pass
    raise ConnectionError("no PyTDX HQ host available; " + " | ".join(errors))

api, source_host = connect_first_available()
raw_rows = []
errors = []
no_data_codes = []
completed = 0
try:
    for code in codes:
        try:
            security_code = str(code.split(".", 1)[1]).strip()
            if len(security_code) != 6 or not security_code.isdigit():
                raise ValueError(f"invalid six-digit PyTDX security code: {security_code!r}")
            code_market = int(market_by_code[code])
            source_rows = api.get_history_minute_time_data(
                code_market, security_code, int(trade_date)
            ) or []
            normalized = normalize_rows(code, source_rows, trade_date)
            if normalized:
                raw_rows.extend(normalized)
            else:
                no_data_codes.append(code)
            completed += 1
        except Exception as exc:
            no_data_codes.append(code)
            errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
finally:
    try:
        api.disconnect()
    except Exception:
        pass

print(MARKER + json.dumps({
    "raw_rows": raw_rows,
    "errors": errors,
    "no_data_codes": no_data_codes,
    "requested_code_count": len(codes),
    "completed_code_count": completed,
    "source_host": source_host,
}, ensure_ascii=False, default=str))
"""


def _failure(
    status: str,
    *,
    error: str,
    cannot_confirm: list[str],
    rows: list[dict[str, Any]] | None = None,
    requested: int = 0,
    completed: int = 0,
    no_data_codes: list[str] | None = None,
) -> StageSourceResult:
    return StageSourceResult(
        source_id="pytdx_hq",
        display_name="TDXPy HQ",
        fidelity="TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE",
        status=status,
        rows=list(rows or []),
        error=error,
        cannot_confirm=cannot_confirm,
        requested_code_count=requested,
        completed_code_count=completed,
        no_data_codes=list(no_data_codes or []),
    )


def _fixed_minute_time_keys(trade_date: str) -> list[str]:
    """Build the immutable V3 A-share minute sequence for one trade date."""
    trade_day = datetime.strptime(trade_date, "%Y%m%d").date()
    labels: list[str] = []
    current = datetime.combine(trade_day, datetime.strptime("09:31", "%H:%M").time())
    morning_end = datetime.combine(trade_day, datetime.strptime("11:30", "%H:%M").time())
    while current <= morning_end:
        labels.append(current.strftime("%Y-%m-%d %H:%M:%S"))
        current += timedelta(minutes=1)
    current = datetime.combine(trade_day, datetime.strptime("13:01", "%H:%M").time())
    afternoon_end = datetime.combine(trade_day, datetime.strptime("15:00", "%H:%M").time())
    while current <= afternoon_end:
        labels.append(current.strftime("%Y-%m-%d %H:%M:%S"))
        current += timedelta(minutes=1)
    return labels


def _bind_unstamped_rows(trade_date: str, raw_rows: list[Any]) -> list[dict[str, Any]]:
    """Bind probe rows lacking timestamps to the fixed A-share sequence.

    The HQ wire payload itself has only price/volume deltas.  The child probe
    normally adds ``time_key``; this defensive binding keeps the parent
    fail-closed and testable if a compatible probe returns code-tagged rows
    without that field.  A code's rows must be wholly stamped or wholly
    unstamped, and the 240-minute sequence is never exceeded.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        code = str(row.get("code") or "").strip().upper()
        if not code:
            passthrough.append(row)
            continue
        grouped.setdefault(code, []).append(row)

    time_keys = _fixed_minute_time_keys(trade_date)
    bound: list[dict[str, Any]] = list(passthrough)
    for code, rows in grouped.items():
        stamped = [bool(str(row.get("time_key") or "").strip()) for row in rows]
        if any(stamped) and not all(stamped):
            raise ValueError(f"PyTDX HQ rows mix stamped and unstamped values for {code}")
        if all(stamped):
            bound.extend(rows)
            continue
        if len(rows) > len(time_keys):
            raise ValueError(
                f"PyTDX HQ response has {len(rows)} rows for {code}; "
                f"fixed sequence supports at most {len(time_keys)}"
            )
        for index, row in enumerate(rows):
            enriched = dict(row)
            enriched["time_key"] = time_keys[index]
            bound.append(enriched)
    return bound


def _parse_payload(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(MARKER):
            value = json.JSONDecoder().raw_decode(line[len(MARKER):].strip())[0]
            if not isinstance(value, dict):
                raise ValueError("PyTDX HQ marker payload must be an object")
            return value
    raise ValueError(f"PyTDX HQ stdout missing {MARKER}")


def _validate_codes(codes: list[Any]) -> list[str]:
    if not isinstance(codes, (list, tuple)) or not codes:
        raise ValueError("codes must be a nonempty list")
    if any(not isinstance(code, str) or not _A_SHARE_RE.fullmatch(code) for code in codes):
        raise ValueError("PyTDX HQ codes must be unique SH/SZ/BJ A-share symbols")
    if len(set(codes)) != len(codes):
        raise ValueError("PyTDX HQ codes must be unique")
    return list(codes)


def _collect_pytdx_hq_batch(
    python_path: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    *,
    market: str = "A_SHARE",
    process_runner: Callable[..., Any],
    timeout_seconds: float = 90,
) -> StageSourceResult:
    """Collect one exact-date A-share 1-minute probe batch through PyTDX HQ.

    The market is derived from each canonical code (SH=1, SZ=0, BJ=2) and is
    carried in the probe request so a mixed A-share batch cannot silently use
    one exchange's market id for all symbols.
    """
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid trade_date {trade_date!r}") from exc
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    market_role(market, stage_id)
    if market != "A_SHARE":
        raise ValueError("PyTDX HQ collector is A_SHARE only")
    python_path = Path(python_path)
    if not python_path.is_file():
        raise ValueError(f"python_path is not a file: {python_path}")
    validated_codes = _validate_codes(codes)
    requested = len(validated_codes)
    market_by_code = {
        code: _MARKET_BY_PREFIX[code.split(".", 1)[0]] for code in validated_codes
    }
    stdin = json.dumps({
        "trade_date": trade_date,
        "stage_id": stage_id,
        "codes": validated_codes,
        "market_by_code": market_by_code,
    }, ensure_ascii=False)
    try:
        proc = process_runner(
            [str(python_path), "-c", _PYTDX_HQ_PROBE],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
    except Exception as exc:
        return _failure(
            "READ_FAILED",
            error=f"PyTDX HQ probe execution failed: {exc}",
            cannot_confirm=["PyTDX HQ probe execution failed"],
            requested=requested,
        )
    if proc.returncode != 0:
        evidence = str(proc.stderr or proc.stdout or "")[-1200:]
        return _failure(
            "READ_FAILED",
            error=f"PyTDX HQ probe exit code {proc.returncode}: {evidence}",
            cannot_confirm=["PyTDX HQ probe returned an error"],
            requested=requested,
        )
    try:
        payload = _parse_payload(proc.stdout)
        raw_rows = payload.get("raw_rows")
        errors = payload.get("errors")
        no_data_codes = payload.get("no_data_codes")
        requested_payload = int(payload.get("requested_code_count"))
        completed = int(payload.get("completed_code_count"))
        if (
            not isinstance(raw_rows, list)
            or not isinstance(errors, list)
            or not isinstance(no_data_codes, list)
            or not all(isinstance(code, str) for code in no_data_codes)
        ):
            raise ValueError("PyTDX HQ coverage payload is malformed")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "READ_FAILED",
            error=f"PyTDX HQ payload invalid: {exc}",
            cannot_confirm=["PyTDX HQ output cannot be verified"],
            requested=requested,
        )

    try:
        raw_rows = _bind_unstamped_rows(trade_date, raw_rows)
    except ValueError as exc:
        return _failure(
            "READ_FAILED",
            error=f"PyTDX HQ timestamp binding failed: {exc}",
            cannot_confirm=["PyTDX HQ minute rows have no verifiable timestamp binding"],
            requested=requested,
            completed=completed,
        )
    aggregated = aggregate_futu_minute_window_rows(trade_date, stage_id, raw_rows)
    # The shared universe order is authoritative for downstream projections;
    # normalize the collector's time/code sort back to the requested order.
    rows_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in aggregated:
        rows_by_code.setdefault(str(row.get("code") or ""), []).append(row)
    aggregated = [
        row
        for code in validated_codes
        for row in rows_by_code.get(code, [])
    ]
    row_codes = [str(row.get("code") or "") for row in aggregated]
    missing = [code for code in validated_codes if code not in set(row_codes)]
    no_data = list(dict.fromkeys(
        [code for code in no_data_codes if code in validated_codes] + missing
    ))
    errors_text = json.dumps(errors, ensure_ascii=False)[:1200] if errors else ""
    full_coverage = (
        requested_payload == requested
        and completed == requested
        and not errors
        and len(row_codes) == requested
        and len(set(row_codes)) == requested
        and not no_data
        and set(row_codes) == set(validated_codes)
    )
    if full_coverage:
        return _failure(
            "READ_OK",
            error=f"source_host={payload.get('source_host')}; rows={len(aggregated)}",
            cannot_confirm=[],
            rows=aggregated,
            requested=requested_payload,
            completed=completed,
        )
    if not errors_text:
        errors_text = f"PyTDX HQ coverage incomplete; no_data={','.join(no_data)}"
    status = "DATA_PARTIAL" if aggregated else "READ_FAILED"
    return _failure(
        status,
        error=errors_text,
        cannot_confirm=[
            f"PyTDX HQ exact-date/window coverage incomplete: completed={completed}/{requested_payload}"
        ],
        rows=aggregated,
        requested=requested_payload if requested_payload else requested,
        completed=completed,
        no_data_codes=no_data,
    )


def _merge_batch_results(
    results: list[StageSourceResult],
    requested_codes: list[str],
) -> StageSourceResult:
    rows_by_code: dict[str, dict[str, Any]] = {}
    for result in results:
        for row in result.rows:
            code = str(row.get("code") or "")
            if code in requested_codes and code not in rows_by_code:
                rows_by_code[code] = row

    rows = [rows_by_code[code] for code in requested_codes if code in rows_by_code]
    no_data_codes = list(dict.fromkeys(
        code
        for result in results
        for code in result.no_data_codes
        if code in requested_codes
    ))
    cannot_confirm = list(dict.fromkeys(
        reason
        for result in results
        for reason in result.cannot_confirm
        if reason
    ))
    source_evidence = [
        f"batch_{index + 1}: {result.error}"
        for index, result in enumerate(results)
        if result.error
    ]
    completed = sum(max(0, int(result.completed_code_count or 0)) for result in results)
    full_coverage = (
        len(rows) == len(requested_codes)
        and all(result.status == "READ_OK" and not result.cannot_confirm for result in results)
        and not no_data_codes
    )
    if full_coverage:
        return _failure(
            "READ_OK",
            error="; ".join(source_evidence) or f"rows={len(rows)}",
            cannot_confirm=[],
            rows=rows,
            requested=len(requested_codes),
            completed=completed,
        )

    cannot_confirm.append(
        f"PyTDX HQ batch coverage incomplete: completed={completed}/{len(requested_codes)}"
    )
    return _failure(
        "DATA_PARTIAL" if rows else "READ_FAILED",
        error="; ".join(source_evidence) or "PyTDX HQ batch probes returned no rows",
        cannot_confirm=list(dict.fromkeys(cannot_confirm)),
        rows=rows,
        requested=len(requested_codes),
        completed=completed,
        no_data_codes=no_data_codes,
    )


def collect_pytdx_hq_minute(
    python_path: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    *,
    market: str = "A_SHARE",
    process_runner: Callable[..., Any],
    timeout_seconds: float = 90,
) -> StageSourceResult:
    """Collect exact-date A-share minutes in bounded independent batches."""

    validated_codes = _validate_codes(codes)
    batch_timeout = min(float(timeout_seconds), PYTDX_HQ_BATCH_TIMEOUT_SECONDS)
    results = [
        _collect_pytdx_hq_batch(
            python_path,
            trade_date,
            stage_id,
            validated_codes[index:index + PYTDX_HQ_BATCH_SIZE],
            market=market,
            process_runner=process_runner,
            timeout_seconds=batch_timeout,
        )
        for index in range(0, len(validated_codes), PYTDX_HQ_BATCH_SIZE)
    ]
    return _merge_batch_results(results, validated_codes)
