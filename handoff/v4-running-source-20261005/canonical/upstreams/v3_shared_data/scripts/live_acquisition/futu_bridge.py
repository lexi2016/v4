"""Actual Futu bridge for shared live A-share minute acquisition (DS2C).

Direct port of the current V3 ``run_futu_minute_window_via_python`` flow:
a fixed quote-only probe talks to localhost OpenD 11111 (K_1M/QFQ, subscribe
chunks of 30, get_cur_kline per subscribed code, unsubscribe, close) and emits
the unique ``__FUTU_MINUTE_JSON__`` marker. No trade context, no service
startup, no shell. All validation happens before the runner call; every
execution/payload failure returns a fail-closed ``StageSourceResult`` —
stdout is never executed and tracebacks never leak as code. The
``process_runner`` is injectable (the tests use fakes); ``subprocess.run`` is
the production runner.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .contracts import STAGE_WINDOWS, StageSourceResult, market_role
from .futu_minute import aggregate_futu_minute_window_rows

MARKER = "__FUTU_MINUTE_JSON__"
_CODE_PATTERNS = {
    # BJ is a first-class Futu market prefix.  Do not rewrite SH/SZ symbols
    # here: the upstream universe owns canonical-market mapping.
    "A_SHARE": re.compile(r"^(SH|SZ|BJ)\.\d{6}$"),
    "HK_CONNECT": re.compile(r"^HK\.\d{5}$"),
}


class _PayloadError(ValueError):
    """Internal marker/payload parse failure; always converted to a result."""


# Fixed probe: current V3 Futu OpenD localhost:11111 K_1M/QFQ flow. Quote
# side only; deterministic; emits the unique JSON marker exactly once.
_FUTU_PROBE = r"""
import json
import socket
import sys

import futu as ft

payload = json.loads(sys.stdin.read())
codes = payload["codes"]
num_bars = int(payload.get("num_bars") or 30)
socket.setdefaulttimeout(3.0)
quote_ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
rows = []
errors = []
no_data_codes = []

def mark_no_data(code):
    if code not in no_data_codes:
        no_data_codes.append(code)

def read_and_unsubscribe(batch):
    # Read one successful subscription and release it before returning.
    try:
        for code in batch:
            try:
                ret, data = quote_ctx.get_cur_kline(
                    code,
                    num_bars,
                    ft.SubType.K_1M,
                    ft.AuType.QFQ,
                )
                if ret == ft.RET_OK:
                    if hasattr(data, "to_dict"):
                        code_rows = data.to_dict(orient="records")
                        if code_rows:
                            rows.extend(code_rows)
                        else:
                            mark_no_data(code)
                            errors.append(f"{code}: empty kline response")
                    else:
                        mark_no_data(code)
                        errors.append(f"{code}: unsupported response {type(data).__name__}")
                else:
                    mark_no_data(code)
                    errors.append(f"{code}: {data}")
            except Exception as exc:
                mark_no_data(code)
                errors.append(f"{code}: {exc}")
    finally:
        try:
            quote_ctx.unsubscribe(batch, [ft.SubType.K_1M])
        except Exception as exc:
            errors.append(f"unsubscribe {batch[:3]} count={len(batch)}: {exc}")

fallback_codes = []
try:
    for start in range(0, len(codes), 30):
        chunk = codes[start:start + 30]
        try:
            ret, message = quote_ctx.subscribe(
                chunk,
                [ft.SubType.K_1M],
                is_first_push=False,
                subscribe_push=False,
            )
            if ret == ft.RET_OK:
                # Release this batch immediately after its reads.  Never hold
                # subscriptions until the entire universe has been scanned.
                read_and_unsubscribe(chunk)
            else:
                errors.append(f"subscribe {chunk[:3]} count={len(chunk)}: {message}")
                fallback_codes.extend(chunk)
        except Exception as exc:
            errors.append(f"subscribe {chunk[:3]} count={len(chunk)}: {exc}")
            fallback_codes.extend(chunk)

    # A single unsupported symbol can make a 30-code subscribe fail.  Retry
    # each member alone so valid A-share symbols survive; unsupported symbols
    # remain explicit typed no-data evidence.
    for code in fallback_codes:
        try:
            ret, message = quote_ctx.subscribe(
                [code],
                [ft.SubType.K_1M],
                is_first_push=False,
                subscribe_push=False,
            )
            if ret == ft.RET_OK:
                read_and_unsubscribe([code])
            else:
                mark_no_data(code)
                errors.append(f"{code}: {message}")
        except Exception as exc:
            mark_no_data(code)
            errors.append(f"{code}: {exc}")
finally:
    try:
        quote_ctx.close()
    except Exception:
        pass
print("__FUTU_MINUTE_JSON__" + json.dumps(
    {"rows": rows, "errors": errors, "no_data_codes": no_data_codes},
    ensure_ascii=False,
    default=str,
))
"""


def _validate_codes(codes: list[Any], market: str = "A_SHARE") -> list[str]:
    """Validate unique ordered Futu symbols for the requested market."""
    pattern = _CODE_PATTERNS.get(market)
    if pattern is None:
        raise ValueError(f"unknown market {market!r}")
    if not isinstance(codes, (list, tuple)) or not codes:
        raise ValueError("codes must be a nonempty list")
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or not pattern.fullmatch(code):
            expected = "SH.######, SZ.###### or BJ.######" if market == "A_SHARE" else "HK.#####"
            raise ValueError(f"invalid futu code {code!r}; expected {expected}")
        if code in seen:
            raise ValueError(f"duplicate futu code {code!r}")
        seen.add(code)
    return list(codes)


def _failure(status: str, rows: list[dict[str, Any]], error: str,
             cannot_confirm: list[str], market: str = "A_SHARE",
             *, requested_code_count: int = 0,
             completed_code_count: int = 0,
             no_data_codes: list[str] | None = None) -> StageSourceResult:
    return StageSourceResult(
        source_id="futu",
        display_name="富途 OpenD",
        fidelity=f"FUTU_{market}_1MIN_CUTOFF_SAFE",
        status=status,
        rows=rows,
        error=error,
        cannot_confirm=cannot_confirm,
        requested_code_count=requested_code_count,
        completed_code_count=completed_code_count,
        no_data_codes=list(no_data_codes or []),
    )


def _parse_marker_payload(stdout: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Parse only the unique marker line; anything else is a payload failure."""
    stdout = stdout or ""
    for line in reversed(stdout.splitlines()):
        if line.startswith(MARKER):
            raw = line[len(MARKER):]
            try:
                # V3 oracle: raw_decode tolerates same-line trailing text.
                payload = json.JSONDecoder().raw_decode(raw.strip())[0]
            except (TypeError, ValueError) as exc:
                raise _PayloadError(f"futu bridge: 标记载荷不是合法 JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise _PayloadError("futu bridge: 标记载荷必须是 JSON 对象")
            rows = payload.get("rows")
            errors = payload.get("errors")
            no_data_codes = payload.get("no_data_codes", [])
            if not isinstance(rows, list):
                raise _PayloadError("futu bridge: 标记载荷 rows 必须是数组")
            if not isinstance(errors, list):
                errors = []
            if not isinstance(no_data_codes, list) or not all(
                isinstance(code, str) for code in no_data_codes
            ):
                raise _PayloadError("futu bridge: no_data_codes must be a string array")
            return rows, errors, no_data_codes
    raise _PayloadError(f"futu bridge: stdout 中没有 {MARKER} 标记")


def collect_futu_minute(
    python_path: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    *,
    market: str = "A_SHARE",
    process_runner: Callable[..., Any],
    timeout_seconds: float = 45,
) -> StageSourceResult:
    """Collect Futu K_1M minute bars for one frozen stage into a StageSourceResult.

    Validation (stage, python file, unique ordered SH./SZ./BJ. codes) happens
    before the runner call. The probe runs with fixed argv ``[python_path, -c,
    probe]``, JSON stdin ``{"codes": [...], "num_bars": N}``, shell never
    true, UTF-8 text capture and the frozen timeout. Payload rows are
    aggregated only via ``aggregate_futu_minute_window_rows``. Status is
    READ_OK exactly when the aggregated row count equals the requested unique
    code count, DATA_PARTIAL when some rows, READ_FAILED when none; READ_OK
    keeps cannot_confirm=[] while the other statuses carry explicit evidence.
    """
    window = STAGE_WINDOWS.get(stage_id)
    if window is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    market_role(market, stage_id)
    if python_path is None:
        raise ValueError("python_path must be a file")
    python_path = Path(python_path)
    if not python_path.is_file():
        raise ValueError(f"python_path is not a file: {python_path}")
    validated_codes = _validate_codes(codes, market)

    def failure(status: str, rows: list[dict[str, Any]], error: str,
                cannot_confirm: list[str], **kwargs: Any) -> StageSourceResult:
        return _failure(status, rows, error, cannot_confirm, market, **kwargs)

    window_start_str, window_end_str, _cutoff_at = window
    span = datetime.strptime(window_end_str, "%H:%M:%S") - datetime.strptime(window_start_str, "%H:%M:%S")
    window_minutes = max(1, int(span.total_seconds() // 60))
    num_bars = min(60, max(10, window_minutes + 5))

    stdin = json.dumps({"codes": validated_codes, "num_bars": num_bars}, ensure_ascii=False)
    try:
        proc = process_runner(
            [str(python_path), "-c", _FUTU_PROBE],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
    except Exception as exc:
        return failure(
            "READ_FAILED", [],
            f"futu bridge: 采集进程执行失败: {exc}",
            ["futu 采集进程执行失败"],
            requested_code_count=len(validated_codes),
        )

    if proc.returncode != 0:
        evidence = str(proc.stderr or proc.stdout or "")[-1200:]
        return failure(
            "READ_FAILED", [],
            f"futu bridge: 采集进程退出码 {proc.returncode}: {evidence}",
            ["futu 采集进程返回错误"],
            requested_code_count=len(validated_codes),
        )

    try:
        raw_rows, payload_errors, payload_no_data_codes = _parse_marker_payload(proc.stdout)
    except _PayloadError as exc:
        return failure(
            "READ_FAILED", [], str(exc), ["futu 采集输出无法解析"],
            requested_code_count=len(validated_codes),
        )

    aggregated = aggregate_futu_minute_window_rows(trade_date, stage_id, raw_rows)
    errors_text = "; ".join(str(item) for item in payload_errors)[:1000]
    row_codes = {row.get("code") for row in aggregated}
    no_data_codes = list(dict.fromkeys(
        [code for code in payload_no_data_codes if code in validated_codes]
        + [code for code in validated_codes if code not in row_codes]
    ))
    if no_data_codes and not errors_text:
        errors_text = f"futu no-data codes: {','.join(no_data_codes)}"
    if len(aggregated) == len(validated_codes) and not no_data_codes:
        return failure(
            "READ_OK", aggregated, errors_text, [],
            requested_code_count=len(validated_codes),
            completed_code_count=len(aggregated),
        )
    if aggregated:
        detail = f"，缺少：{','.join(no_data_codes)}" if no_data_codes else ""
        return failure(
            "DATA_PARTIAL", aggregated, errors_text,
            [f"futu 只返回 {len(aggregated)}/{len(validated_codes)} 只标的分钟线{detail}"],
            requested_code_count=len(validated_codes),
            completed_code_count=len(aggregated),
            no_data_codes=no_data_codes,
        )
    return failure(
        "READ_FAILED", [],
        "; ".join(part for part in ("futu 未聚合出任何分钟行", errors_text) if part),
        ["futu 未返回任何标的分钟线"],
        requested_code_count=len(validated_codes),
        no_data_codes=no_data_codes,
    )
