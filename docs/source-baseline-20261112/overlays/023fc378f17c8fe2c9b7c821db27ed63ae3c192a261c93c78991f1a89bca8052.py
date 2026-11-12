"""Shared, path-neutral helpers for the daily research-panel adapter."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import tempfile
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


A_DAY_STRUCT = __import__("struct").Struct("<IIIIIfII")
HK_DAY_STRUCT = __import__("struct").Struct("<IfffffII")
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
LANE_CHOICES = ("A", "HK", "ALL")


class SnapshotGateError(ValueError):
    """Raised when a lane input cannot be proven safe for the target date."""


HKCONNECT_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")
PYTDX_KLINE_DAY = 9
MAX_EXCLUDED_EVIDENCE = 100
COMMON_A_PREFIXES = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("430", "83", "87", "88", "92"),
}
AUTHORITY_DAY_MINIMUM_DEFAULT = 1



def _today_shanghai() -> str:
    """Return the local trading date used when the CLI date is omitted."""
    return _datetime.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _scheduled_day_is_cross_market_trading_day(target_date: str) -> bool:
    """Return whether an implicit daily run may collect both panel lanes.

    An omitted ``--date`` is the launchd path.  It must be fail-closed when
    launchd coalesces a missed weekday run onto a weekend or an exchange
    holiday; an explicit date remains a deliberate, testable replay request.
    The calendar is loaded from this source tree, never inferred from the
    weekday alone.
    """
    try:
        from contracts.trading_calendar import (
            TradingDayState,
            load_market_calendar,
            resolve_market_states,
        )

        calendar = load_market_calendar(Path(__file__).resolve().parents[1] / "contracts" / "market_calendar_2026.json")
        states = resolve_market_states(calendar, _date(target_date))
    except Exception:
        return False
    return all(
        states.get(market) in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }
        for market in ("a_share", "hk_securities")
    )


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    else:
        records = frame
    if records is None:
        return []
    return [dict(row) for row in records]


def _compact_datetime(value: Any) -> str:
    text = str(value or "")
    digits = "".join(character for character in text if character.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _canonical_sha(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _universe_code(row: Mapping[str, Any]) -> tuple[str, str, int]:
    value = str(row.get("ts_code") or row.get("code") or "").strip().upper()
    if "." not in value:
        raise SnapshotGateError(f"A universe row missing exchange: {value!r}")
    code, exchange = value.split(".", 1)
    code = "".join(ch for ch in code if ch.isdigit()).zfill(6)
    exchange = exchange.split("_", 1)[0]
    market = {"SZ": 0, "SH": 1, "BJ": 2}.get(exchange)
    if market is None or len(code) != 6:
        raise SnapshotGateError(f"unsupported A universe code: {value!r}")
    return code, exchange.lower(), market


def _date(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        raise SnapshotGateError(f"invalid target date: {value!r}")
    try:
        _datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise SnapshotGateError(f"invalid target date: {value!r}") from error
    return text


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    result = [dict(row) for row in rows]
    if not result:
        raise SnapshotGateError("empty snapshot")
    return result


def _number(row: Mapping[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = row.get(name)
        if value is not None and str(value) != "":
            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise SnapshotGateError(f"non-numeric {name}") from error
    return default


def _code(row: Mapping[str, Any]) -> str:
    value = row.get("code") or row.get("code_norm") or row.get("ts_code")
    text = str(value or "").strip().upper()
    if "." in text:
        left, right = text.split(".", 1)
        text = right if left == "HK" else left
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise SnapshotGateError("missing security code")
    return digits


def _validate_rows(rows: list[dict[str, Any]], target_date: str, *, minimum_rows: int, lane: str) -> tuple[list[dict[str, Any]], float]:
    target_date = _date(target_date)
    if len(rows) < minimum_rows:
        raise SnapshotGateError(f"{lane} minimum coverage requires {minimum_rows} rows, got {len(rows)}")
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    for row in rows:
        actual = _date(row.get("trade_date") or row.get("trade_date_compact"))
        if actual != target_date:
            raise SnapshotGateError(f"{lane} exact target date mismatch: {actual} != {target_date}")
        code = _code(row)
        if code in seen:
            raise SnapshotGateError(f"{lane} duplicate code: {code}")
        seen.add(code)
        open_, high, low, close = (_number(row, name) for name in ("open", "high", "low", "close"))
        if min(open_, high, low, close) <= 0 or high < low or close < low or close > high:
            raise SnapshotGateError(f"{lane} non-positive or invalid OHLC: {code}")
        row = dict(row)
        row["code"] = code
        row["trade_date"] = target_date
        checked.append(row)
    return checked, len(checked) / max(len(seen), 1)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _after_1700_attempt_path(receipt_root: Path | str, target_date: str) -> Path:
    return Path(receipt_root).expanduser().resolve() / "after_1700_ensure" / f"{_date(target_date)}.json"


def _normalize_lane(lane: str) -> str:
    normalized = str(lane or "ALL").upper()
    if normalized not in LANE_CHOICES:
        raise ValueError(f"lane must be one of {LANE_CHOICES!r}")
    return normalized


def _not_requested_lane() -> dict[str, Any]:
    return {"status": "NOT_REQUESTED", "runner_called": False, "receipt_written": False, **SAFETY_FLAGS}


def build_subprocess_command(script: Path | str, target_date: str, receipt_root: Path | str) -> list[str]:
    return ["/usr/bin/python3", str(Path(script)), "--date", _date(target_date), "--receipt-root", str(Path(receipt_root))]


def _load_universe(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotGateError(f"A universe JSON is unreadable: {path}") from error
    if isinstance(payload, Mapping):
        payload = payload.get("rows") or payload.get("universe") or payload.get("data")
    if not isinstance(payload, list):
        raise SnapshotGateError("A universe JSON must contain a list of rows")
    rows = _rows(payload)
    return rows[: int(limit)] if limit is not None else rows


def _a_day_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for exchange in ("sh", "sz", "bj"):
        for path in sorted((root / "vipdoc" / exchange / "lday").glob(f"{exchange}*.day")):
            code = path.stem[len(exchange) :]
            if code.isdigit() and code.startswith(COMMON_A_PREFIXES[exchange]):
                files.append(path)
    return files


def _absolute_path_argument(parser: argparse.ArgumentParser, value: Path, name: str) -> Path:
    path = value.expanduser()
    if not path.is_absolute():
        parser.error(f"{name} must be an absolute path")
    return path
