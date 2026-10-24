"""Mac research-panel adapter for the daily A/H authority chain.

The adapter accepts every path explicitly from its caller, collects or packs
path-neutral lane inputs, and dynamically invokes the original Windows A-share
sync/formula authorities plus the original HK 0.2 authority.  Its receipts and
``production_allowed``/``buy_gate_updated``/``orders_sent`` flags are
research-only safety evidence; they do not grant production or trading
permission.  Any pointer or authority promotion remains governed by those
explicit authority entry points rather than by this module's documentation.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _datetime
import hashlib
import json
import math
import os
import importlib.util
import subprocess
import sys
import struct
import tempfile
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from infrastructure.owned_io import SafeRoot
from infrastructure.formula_generation import (
    FormulaGenerationError,
    is_v4_formula_state_owner,
    read_formula_generation,
)


A_DAY_STRUCT = struct.Struct("<IIIIIfII")
HK_DAY_STRUCT = struct.Struct("<IfffffII")
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
LANE_CHOICES = ("A", "HK", "ALL")
FORMULA_GENERATION_SCHEMA = "v4.a_formula.generation_pointer.v1"
FORMULA_GENERATION_POINTER_NAME = "CURRENT_FORMULA_GENERATION.json"


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
DEFAULT_A_SYNC_RUN_BUDGET_SECONDS = 540.0
A_SYNC_RUN_BUDGET_ENV = "V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"
A_SYNC_HOST_ENV = "V35_A_SYNC_HOST"
A_FORMULA_GENERATION_POINTER_ENV = "V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER"


def _resolve_a_sync_run_budget(raw: Any | None) -> float:
    """Resolve the A sync wall-clock budget, rejecting unsafe values."""
    if raw is None:
        return DEFAULT_A_SYNC_RUN_BUDGET_SECONDS
    if isinstance(raw, bool):
        raise ValueError("A sync run budget must be a positive finite number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("A sync run budget must be a positive finite number") from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("A sync run budget must be a positive finite number")
    return value


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    capture_manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Collect an exact-date full HK Connect snapshot from Futu OpenD."""
    from ops._hk_provider_capture import ProviderCapture, now
    target = _date(target_date)
    capture = ProviderCapture(capture_manifest_path or os.environ.get("V35_HK_CAPTURE_PATH"), target, source_path=Path(__file__))
    try:
        if context_factory is None:
            def context_factory():
                import futu

                return futu.OpenQuoteContext(host="127.0.0.1", port=11111)
        context = context_factory()
        universe: dict[str, str] = {}
        snapshots: dict[str, dict[str, Any]] = {}
        quote_observations = []
        try:
            for plate_code in HKCONNECT_PLATE_CODES:
                request = capture.request("get_plate_stock", {"plate_code": plate_code})
                try:
                    return_code, frame = context.get_plate_stock(plate_code)
                except Exception as error:
                    capture.response(request, None, None, error={"type": type(error).__name__, "message": str(error)})
                    raise
                observed = capture.response(request, return_code, frame, completed_at=now())
                if return_code != 0:
                    raise SnapshotGateError(f"Futu plate lookup failed: {plate_code}")
                for item, reference in observed:
                    code = reference["code"] or ""
                    if code.startswith("HK."):
                        reference.update(disposition="MEMBERSHIP_OBSERVED_DUPLICATE" if code in universe else "MEMBERSHIP_OBSERVED", reasons=[])
                        universe[code] = str(item.get("stock_name") or item.get("name") or "").strip()
                    else:
                        reference.update(disposition="INVALID_MEMBERSHIP_CODE", reasons=["not_hk_code"])
            codes = sorted(universe)
            capture.set_codes(codes)
            minimum_universe = max(600, int(minimum_universe_count))
            if len(codes) < minimum_universe:
                raise SnapshotGateError(f"HK universe below minimum: {len(codes)} < {minimum_universe_count}")
            step = max(1, int(batch_size))
            for offset in range(0, len(codes), step):
                requested_codes = codes[offset : offset + step]
                request = capture.request("get_market_snapshot", {"codes": requested_codes})
                try:
                    return_code, frame = context.get_market_snapshot(codes[offset : offset + step])
                except Exception as error:
                    capture.response(request, None, None, error={"type": type(error).__name__, "message": str(error)})
                    raise
                observed = capture.response(request, return_code, frame, completed_at=now())
                if return_code != 0:
                    raise SnapshotGateError(f"Futu market snapshot failed at offset {offset}")
                quote_observations.extend(observed)
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                close()
        snapshots = capture.snapshots(quote_observations, universe)
        rows: list[dict[str, Any]] = []
        excluded: dict[str, list[str]] = {}
        positive_volume_count = 0
        positive_turnover_count = 0
        required_fields = ("open_price", "high_price", "low_price", "last_price", "volume", "turnover")
        for code in codes:
            if capture.code_states.get(code, {}).get("disposition") == "PENDING_CONFLICT":
                excluded[code] = ["conflicting_snapshot_facts"]
                continue
            source = snapshots.get(code) or {}
            if _compact_datetime(source.get("update_time")) != target:
                excluded[code] = ["stale_or_missing_date"]
                capture.disposition(code, reasons=excluded[code])
                continue
            missing = [field for field in required_fields if field not in source or source.get(field) in (None, "")]
            if missing:
                excluded[code] = [f"missing_{field}" for field in missing]
                capture.disposition(code, reasons=excluded[code])
                continue
            try:
                # Preserve raw values in SDK evidence; bool/nonfinite values cannot
                # become financial numeric facts during the existing projection.
                for field in required_fields:
                    value = source[field]
                    scalar = value.item() if callable(getattr(value, "item", None)) else value
                    if isinstance(scalar, bool) or not math.isfinite(float(scalar)):
                        raise SnapshotGateError("invalid financial numeric type")
                open_price = _number(source, "open_price")
                high_price = _number(source, "high_price")
                low_price = _number(source, "low_price")
                last_price = _number(source, "last_price")
                volume = _number(source, "volume")
                turnover = _number(source, "turnover")
            except (TypeError, ValueError, OverflowError, SnapshotGateError):
                excluded[code] = ["non_numeric_fields"]
                capture.disposition(code, reasons=excluded[code])
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
                capture.disposition(code, reasons=reasons)
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
                capture.disposition(code, accepted=row)
            except (TypeError, ValueError, OverflowError, SnapshotGateError):
                excluded[code] = ["row_encoding_error"]
                capture.disposition(code, reasons=excluded[code])
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
        source_sha = _canonical_sha(
            {
                "target_date": target,
                "plates": HKCONNECT_PLATE_CODES,
                "rows": rows,
                "excluded_count": len(evidence_codes),
                "excluded_codes": evidence_codes,
                "excluded_reasons": {code: sorted(excluded[code]) for code in evidence_codes},
                "positive_volume_coverage_rate": positive_volume_coverage,
                "positive_turnover_coverage_rate": positive_turnover_coverage,
            }
        )
        capture_refs = capture.finish("COLLECTED")
        return {
            "provider_capture": capture_refs,
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

    except Exception as error:
        raise capture.fail(error) from error


def _run_hk_retained(target: str, *, receipt_root: Path, tdx_root: Path,
                     updater_script: Path, python_executable: str, asset_root: Path,
                     context_factory=None, authority_runner=None) -> dict[str, Any]:
    """Same existing HK child chain, with durable provider evidence references."""
    import uuid
    from ops._hk_provider_capture import lane_receipt
    target = _date(target)
    capture_path = Path(receipt_root).resolve() / "hk_capture" / target / (target + "-" + uuid.uuid4().hex + ".json")
    refs, packed, authority = {}, None, None
    try:
        collected = collect_hk_futu_rows(target, context_factory=context_factory,
            minimum_universe_count=600, required_coverage_ratio=0.0,
            capture_manifest_path=capture_path)
        refs = collected["provider_capture"]
        packed = pack_hk_day(tdx_root, collected["rows"], target_date=target, minimum_rows=600)
        authority = (authority_runner or run_hk_0_2_authority)(updater_script,
            python_executable, asset_root, tdx_root, target)
        refs = lane_receipt(refs, packed=packed, authority=authority)
        return {**collected, **packed, "authority": authority,
            "source_sha256": collected["source_sha256"], "provider_capture": refs}
    except Exception as error:
        refs = getattr(error, "capture_refs", None) or refs
        try:
            refs = lane_receipt(refs, packed=packed, authority=authority,
                error=type(error).__name__ + ":" + str(error))
        except Exception as storage:
            refs = dict(refs, retention_status="INCOMPLETE_STORAGE_FAILURE", storage_error=type(storage).__name__)
        return {"status": "FAILED", "target_date": target, "error": str(error),
            "coverage_rate": 0.0, "sha256": "", "provider_capture": refs, **SAFETY_FLAGS}


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


def _panel_frame(panel_path: Path) -> list[dict[str, Any]]:
    if not panel_path.is_file():
        raise SnapshotGateError(f"A seed panel missing: {panel_path}")
    try:
        import pandas as pd

        frame = pd.read_parquet(panel_path)
        return _rows(frame)
    except Exception as error:
        raise SnapshotGateError(f"A seed panel unreadable: {panel_path}") from error


def bootstrap_a_vipdoc_from_panel(panel_path: Path | str, tdx_root: Path | str, *, tail_records: int = 260) -> dict[str, Any]:
    """Seed SH/SZ/BJ VIPDOC files from a panel tail without overwriting history."""
    if int(tail_records) < 1:
        raise SnapshotGateError("tail_records must be positive")
    rows = _panel_frame(Path(panel_path))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for source in rows:
        code_value = str(source.get("ts_code") or source.get("code") or "").strip().upper()
        if "." not in code_value:
            continue
        code, exchange = code_value.split(".", 1)
        exchange = exchange.split("_", 1)[0].lower()
        if exchange not in {"sh", "sz", "bj"}:
            continue
        if not code.isdigit() or len(code) != 6:
            continue
        if not code.startswith(COMMON_A_PREFIXES[exchange]):
            continue
        row = {
            "trade_date": _date(source.get("trade_date") or source.get("trade_date_compact")),
            "code": code,
            "exchange": exchange,
            "open": _number(source, "open"),
            "high": _number(source, "high"),
            "low": _number(source, "low"),
            "close": _number(source, "close"),
            "volume": _number(source, "volume", "vol"),
            "turnover": _number(source, "amount", "turnover"),
        }
        if min(row["open"], row["high"], row["low"], row["close"]) <= 0 or row["high"] < row["low"] or row["close"] < row["low"] or row["close"] > row["high"]:
            raise SnapshotGateError(f"A seed invalid OHLC: {code}")
        grouped.setdefault((exchange, code), []).append(row)
    if not grouped:
        raise SnapshotGateError("A seed panel has no SH/SZ/BJ rows")
    results = []
    destination = Path(tdx_root)
    for (exchange, code), code_rows in sorted(grouped.items()):
        ordered = sorted(code_rows, key=lambda item: int(item["trade_date"]))[-int(tail_records):]
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code}.day"
        checked = _validate_seed_rows(ordered)
        encoded = b"".join(A_DAY_STRUCT.pack(*_a_record(row)) for row in checked)
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise SnapshotGateError(f"A seed conflict: {path}")
            already_current = True
        else:
            _atomic_write(path, encoded)
            already_current = False
        results.append({"status": "READY", "already_current": already_current, "target_date": checked[-1]["trade_date"], "row_count": len(checked), "coverage_rate": 1.0, "sha256": _sha(path), "path": str(path), **SAFETY_FLAGS})
    return _grouped_result(results, max(str(item["target_date"]) for item in results), lane="A") | {"seed_panel": str(Path(panel_path)), "tail_records": int(tail_records)}


def _validate_seed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise SnapshotGateError("A seed has no rows")
    dates: set[int] = set()
    checked = []
    for row in rows:
        date_value = int(_date(row.get("trade_date")))
        if date_value in dates:
            raise SnapshotGateError(f"A seed duplicate date: {date_value}")
        dates.add(date_value)
        if min(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) <= 0:
            raise SnapshotGateError(f"A seed non-positive OHLC: {row.get('code')}")
        checked.append(dict(row, trade_date=str(date_value)))
    return sorted(checked, key=lambda item: int(item["trade_date"]))


def _load_authority_module(script_path: Path | str, module_name: str) -> Any:
    path = Path(script_path).resolve()
    if not path.is_file():
        raise SnapshotGateError(f"authority script missing: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SnapshotGateError(f"authority module cannot load: {path}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses with postponed annotations resolve their defining module
    # during import. Match the v16 loader; restore prior identity on failure.
    missing = object()
    previous = sys.modules.get(module_name, missing)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is missing:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module


def _day_file_last_date(path: Path, record_struct: struct.Struct) -> int | None:
    records = _existing_records(path, record_struct)
    return int(records[-1][0]) if records else None


def run_windows_a_sync_authority(
    script_path: Path | str,
    tdx_root: Path | str,
    target_date: str,
    receipt_root: Path | str,
    *,
    minimum_target_date_files: int = 1,
    module_name: str = "macos_windows_a_sync_authority",
    authority_args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target = int(_date(target_date))
    root = Path(tdx_root).resolve()
    module = _load_authority_module(script_path, module_name)
    module.TDX_ROOT = root
    module.DATA_ROOT = Path(receipt_root).resolve()
    module.RUN_DIR = Path(receipt_root).resolve() / "a_sync_authority"
    module.DIR_BY_MARKET = {
        "a": [("sh", root / "vipdoc" / "sh" / "lday"), ("sz", root / "vipdoc" / "sz" / "lday")],
        "bj": [("bj", root / "vipdoc" / "bj" / "lday")],
    }
    args_values = {
        "tdx_root": root,
        "target_date": target,
        "markets": "a,bj",
        "limit": 0,
        "host": None,
        "timeout": 1.5,
        "count": 20,
        "sleep": 0.0,
        "progress_every": 10_000,
        "dry_run": False,
    }
    # Merge overrides before constructing Namespace so an explicit host (or
    # another authority option) replaces the default instead of becoming a
    # duplicate keyword argument.
    args_values.update(dict(authority_args or {}))
    args = argparse.Namespace(**args_values)
    reported = dict(module.run(args))
    if reported.get("status") != "PASS" or int(reported.get("exit_code", 0) or 0) != 0:
        raise SnapshotGateError(
            "A sync authority did not prove exact-date success: "
            f"status={reported.get('status')},exit_code={reported.get('exit_code')}"
        )
    files = _a_day_files(root)
    target_files = [path for path in files if _day_file_last_date(path, A_DAY_STRUCT) == target]
    if len(target_files) < int(minimum_target_date_files):
        raise SnapshotGateError(f"A sync target-date postcondition failed: {len(target_files)} < {minimum_target_date_files}")
    receipt = Path(receipt_root) / "a_sync_authority.json"
    payload = {"status": "READY", "authority_status": reported.get("status"), "target_date": target, "target_date_file_count": len(target_files), "files": [str(path) for path in target_files], "authority": reported, **SAFETY_FLAGS}
    _atomic_write(receipt, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def _parquet_max_date(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["trade_date"])
        values = table.column("trade_date").to_pylist()
        return max(int(str(value).replace("-", "")) for value in values) if values else None
    except Exception as error:
        raise SnapshotGateError(f"parquet target-date audit failed: {path}") from error


def selector_pointer_is_ready(
    pointer: Path | str | None,
    target_date: str,
    formula_generation_pointer: Path | str | None = None,
) -> bool:
    """Return true only when the authoritative selector reaches target date.

    A generation pointer enables the strict V4 contract: the exact selector
    and source/sidecar provenance must be verified together.  The two argument
    form remains the compatibility path for older callers and fixtures.
    """

    if formula_generation_pointer is not None:
        try:
            generation = read_formula_generation(
                formula_generation_pointer,
                expected_target_date=_date(target_date),
                require_source=True,
            )
            if pointer is None:
                return True
            from infrastructure.formula_generation import read_legacy_pointer

            return read_legacy_pointer(pointer) == generation["selector"]
        except (FormulaGenerationError, OSError, UnicodeError, ValueError):
            return False

    target = int(_date(target_date))
    if pointer is None:
        return False
    pointer_path = Path(pointer).expanduser().resolve()
    try:
        pointed = Path(pointer_path.read_text(encoding="utf-8-sig").strip()).expanduser()
    except (OSError, UnicodeError):
        return False
    if not pointed.is_absolute():
        pointed = pointer_path.parent / pointed
    pointed = pointed.resolve()
    try:
        generation = _find_formula_generation(pointed)
        if generation is not None:
            pointed = generation["selector"]
        return pointed.is_file() and _parquet_max_date(pointed) == target
    except (OSError, SnapshotGateError):
        return False


def _path_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _formula_generation_target(
    output_root: Path,
    payload: Mapping[str, Any],
    role: str,
) -> Path:
    detail = payload.get(role)
    if not isinstance(detail, Mapping):
        raise SnapshotGateError(f"formula generation missing {role} target")
    raw_path = detail.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SnapshotGateError(f"formula generation {role} path is invalid")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = output_root / candidate
    resolved = candidate.resolve()
    if not _path_inside(output_root, resolved) or candidate.is_symlink():
        raise SnapshotGateError(f"formula generation {role} target escapes output root")
    current = candidate
    while True:
        if current.is_symlink():
            raise SnapshotGateError(f"formula generation {role} target has symlink ancestry")
        if current == output_root:
            break
        if current.parent == current:
            raise SnapshotGateError(f"formula generation {role} target has invalid ancestry")
        current = current.parent
    if not resolved.is_file():
        raise SnapshotGateError(f"formula generation {role} target is missing")
    expected_bytes = detail.get("bytes")
    expected_sha = detail.get("sha256")
    if not isinstance(expected_bytes, int) or expected_bytes != resolved.stat().st_size:
        raise SnapshotGateError(f"formula generation {role} target bytes mismatch")
    if not isinstance(expected_sha, str) or _sha256_file(resolved) != expected_sha:
        raise SnapshotGateError(f"formula generation {role} target SHA mismatch")
    return resolved


def _read_formula_generation(output_root: Path | str) -> dict[str, Any] | None:
    root = Path(output_root).expanduser().resolve()
    path = root / FORMULA_GENERATION_POINTER_NAME
    if not path.is_file():
        return None
    if path.is_symlink():
        raise SnapshotGateError("formula generation pointer is symlinked")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotGateError("formula generation pointer is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema") != FORMULA_GENERATION_SCHEMA or payload.get("status") != "READY":
        raise SnapshotGateError("formula generation pointer schema/status is invalid")
    identity = {"selector": payload.get("selector"), "backtest": payload.get("backtest")}
    generation_id = payload.get("generation_id")
    expected_generation_id = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not isinstance(generation_id, str) or generation_id != expected_generation_id:
        raise SnapshotGateError("formula generation identity mismatch")
    selector = _formula_generation_target(root, payload, "selector")
    backtest = _formula_generation_target(root, payload, "backtest")
    if selector == backtest:
        raise SnapshotGateError("formula generation selector/backtest targets must differ")
    return {
        "path": path,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "generation_id": generation_id,
        "selector": selector,
        "backtest": backtest,
    }


def _find_formula_generation(target: Path) -> dict[str, Any] | None:
    current = target if target.is_dir() else target.parent
    for _ in range(64):
        try:
            generation = _read_formula_generation(current)
        except SnapshotGateError:
            raise
        if generation is not None:
            return generation
        if current.parent == current:
            break
        current = current.parent
    return None


def _after_1700_attempt_path(receipt_root: Path | str, target_date: str) -> Path:
    return Path(receipt_root).expanduser().resolve() / "after_1700_ensure" / f"{_date(target_date)}.json"


def _normalize_lane(lane: str) -> str:
    normalized = str(lane or "ALL").upper()
    if normalized not in LANE_CHOICES:
        raise ValueError(f"lane must be one of {LANE_CHOICES!r}")
    return normalized


def _not_requested_lane() -> dict[str, Any]:
    return {"status": "NOT_REQUESTED", "runner_called": False, "receipt_written": False, **SAFETY_FLAGS}


def _read_lane_receipt(receipt_root: Path | str, lane: str, target_date: str) -> Mapping[str, Any] | None:
    """Read only the exact dated lane receipt used by the after-1700 gate."""

    path = Path(receipt_root).expanduser().resolve() / f"{lane.lower()}-{_date(target_date)}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _receipt_safety_is_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name) is False for name in SAFETY_FLAGS)


def _fast_path_lane_detail(
    receipt_root: Path | str,
    lane: str,
    target_date: str,
    *,
    ready: bool,
) -> dict[str, Any]:
    """Project an already verified dated receipt into the public lane envelope.

    The after-1700 fast path must remain idempotent without turning an old or
    malformed ``READY`` file into a new readiness claim.  The lane validators
    establish ``ready``; this helper rereads the same exact-date bytes only to
    carry their digest/size and a truthful lane status to the registry.
    """

    target = _date(target_date)
    name = f"{lane.lower()}-{target}.json"
    try:
        raw = SafeRoot(receipt_root).read_bytes(name)
        receipt = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {
            "status": "CANNOT_CONFIRM",
            "lane_ready": False,
            "runner_called": False,
            "receipt_written": False,
            **SAFETY_FLAGS,
        }
    identity_ok = (
        isinstance(receipt, Mapping)
        and receipt.get("schema_version") == "v3.macos.research_panel_receipt.v1"
        and receipt.get("lane") == lane
        and str(receipt.get("target_date") or "") == target
        and _receipt_safety_is_false(receipt)
    )
    status = str(receipt.get("status") or "CANNOT_CONFIRM").upper() if identity_ok else "CANNOT_CONFIRM"
    lane_ready = bool(ready and status == "READY")
    if status == "READY" and not lane_ready:
        status = "CANNOT_CONFIRM"
    return {
        "status": status,
        "lane_ready": lane_ready,
        "runner_called": False,
        "receipt_written": True,
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "receipt_bytes": len(raw),
        **SAFETY_FLAGS,
    }


def _a_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    selector_ready: bool,
    payload: Mapping[str, Any] | None = None,
    formula_generation_pointer: Path | str | None = None,
) -> tuple[bool, bool]:
    """Require exact A selector plus the formula's exact backtest readiness."""

    if not selector_ready:
        return False, False
    receipt = payload or _read_lane_receipt(receipt_root, "A", target_date)
    if not isinstance(receipt, Mapping):
        return False, False
    if (
        receipt.get("status") != "READY"
        or str(receipt.get("target_date") or "") != _date(target_date)
        or not _receipt_safety_is_false(receipt)
    ):
        return False, False
    generation_verified = False
    if formula_generation_pointer is not None:
        try:
            generation = read_formula_generation(
                formula_generation_pointer,
                expected_target_date=_date(target_date),
                require_source=True,
            )
            receipt_generation = receipt.get("generation")
            if not isinstance(receipt_generation, Mapping):
                formula = receipt.get("formula")
                receipt_generation = formula.get("generation_pointer") if isinstance(formula, Mapping) else None
            if not isinstance(receipt_generation, Mapping):
                return False, False
            if (
                str(receipt_generation.get("generation_id") or "") != generation["generation_id"]
                or str(receipt_generation.get("sha256") or "").lower() != generation["sha256"]
                or str(receipt_generation.get("path") or "") != str(generation["path"])
            ):
                return False, False
            generation_verified = True
        except (FormulaGenerationError, OSError, UnicodeError, ValueError):
            return False, False
    backtest_ready = receipt.get("backtest_pointer_ready")
    formula = receipt.get("formula")
    if backtest_ready is None and isinstance(formula, Mapping):
        backtest_ready = formula.get("backtest_pointer_ready")
    # The strict generation pointer is the authoritative pair.  Its reader
    # has already verified the exact backtest artifact and target date, so a
    # legacy receipt that predates ``backtest_pointer_ready`` remains usable
    # only when that strict pair was verified above.
    if backtest_ready is None and generation_verified:
        backtest_ready = True
    return backtest_ready is True, backtest_ready is True


def _hk_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Require the exact HK date receipt and a non-empty verified snapshot."""

    receipt = payload or _read_lane_receipt(receipt_root, "HK", target_date)
    if not isinstance(receipt, Mapping):
        return False
    try:
        row_count = int(receipt.get("row_count") or 0)
        coverage_rate = float(receipt.get("coverage_rate") or 0.0)
    except (TypeError, ValueError):
        return False
    digest = receipt.get("sha256")
    return bool(
        receipt.get("status") == "READY"
        and str(receipt.get("target_date") or "") == _date(target_date)
        and _receipt_safety_is_false(receipt)
        and isinstance(digest, str)
        and bool(digest.strip())
        and row_count > 0
        and coverage_rate > 0.0
    )


def ensure_after_1700(
    *,
    target_date: str,
    receipt_root: Path | str,
    selector_pointer: Path | str | None,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str | None = None,
    now: _datetime.datetime | None = None,
    formula_generation_pointer: Path | str | None = None,
) -> dict[str, Any]:
    """Idempotently ensure the daily panel after 17:00.

    StartInterval can invoke this function repeatedly.  Explicit lane callers
    use only their exact dated receipt as a fast path: A requires selector and
    backtest readiness, HK requires a verified HK snapshot, and ALL requires
    both.  The dated attempt marker applies only a bounded time backoff and
    never converts a stale pointer into a permanent success or permanent
    lockout.
    """

    target = _date(target_date)
    requested_lane = _normalize_lane(lane or "ALL")
    strict_lane_readiness = lane is not None
    moment = now or _datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        moment = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    common = {
        "schema_version": "v3.macos.research_panel_after_1700_ensure.v1",
        "target_date": target,
        "observed_at": moment.isoformat(),
        "selector_pointer": str(Path(selector_pointer).expanduser().resolve()) if selector_pointer is not None else None,
        "formula_generation_pointer": str(Path(formula_generation_pointer).expanduser().resolve()) if formula_generation_pointer is not None else None,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if moment.hour < 17:
        return {**common, "status": "BEFORE_1700", "runner_called": False, "idempotent": True}
    selector_ready = (
        selector_pointer_is_ready(selector_pointer, target, formula_generation_pointer)
        if requested_lane != "HK"
        else False
    ) if formula_generation_pointer is not None else (
        selector_pointer_is_ready(selector_pointer, target) if requested_lane != "HK" else False
    )
    common["selector_pointer_ready"] = selector_ready
    a_ready, backtest_ready = _a_lane_receipt_ready(
        receipt_root,
        target,
        selector_ready,
        formula_generation_pointer=formula_generation_pointer,
    ) if formula_generation_pointer is not None else _a_lane_receipt_ready(
        receipt_root, target, selector_ready
    )
    hk_ready = _hk_lane_receipt_ready(receipt_root, target)
    common.update(
        {
            "a_lane_ready": a_ready,
            "hk_lane_ready": hk_ready,
            "backtest_pointer_ready": backtest_ready,
        }
    )
    already_ready = (
        (requested_lane == "A" and a_ready)
        or (requested_lane == "HK" and hk_ready)
        or (requested_lane == "ALL" and a_ready and hk_ready)
    )
    # Calls that predate the explicit lane contract retain the old selector
    # fast path; launchd and all current callers pass lane explicitly.
    if already_ready or (selector_ready and not strict_lane_readiness and requested_lane == "ALL"):
        requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
        lanes = {
            name: (
                _fast_path_lane_detail(receipt_root, name, target, ready=ready)
                if name in requested
                else _not_requested_lane()
            )
            for name, ready in (("A", a_ready), ("HK", hk_ready))
        }
        fast_path_verified = all(lanes[name].get("lane_ready") is True for name in requested)
        if not already_ready or fast_path_verified:
            return {
                **common,
                "status": "ALREADY_READY",
                "runner_called": False,
                "idempotent": True,
                "lanes": lanes,
                **({"lane_ready": already_ready, "requested_lane": requested_lane} if strict_lane_readiness else {}),
            }

    attempt_path = _after_1700_attempt_path(receipt_root, target)
    if requested_lane != "ALL":
        # Lane-local backoff; a failed A update must not suppress HK work.
        attempt_path = attempt_path.with_name(f"{target}-{requested_lane.lower()}.json")
    if attempt_path.is_file():
        try:
            payload = json.loads(attempt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, Mapping):
            attempt_count = int(payload.get("attempt_count") or 1)
            previous_raw = str(payload.get("observed_at") or "")
            try:
                previous = _datetime.datetime.fromisoformat(previous_raw)
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                elapsed = (moment - previous.astimezone(ZoneInfo("Asia/Shanghai"))).total_seconds()
            except (TypeError, ValueError, OverflowError):
                elapsed = 300.0
            if elapsed < 300.0:
                return {
                    **common,
                    **dict(payload),
                    "status": "RETRY_BACKOFF",
                    "runner_called": False,
                    "idempotent": True,
                }
        else:
            attempt_count = 1
    else:
        attempt_count = 0

    result = run_lanes(
        target_date=target,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=requested_lane,
    )
    selector_ready_after = (
        selector_pointer_is_ready(selector_pointer, target, formula_generation_pointer)
        if requested_lane != "HK"
        else False
    ) if formula_generation_pointer is not None else (
        selector_pointer_is_ready(selector_pointer, target) if requested_lane != "HK" else False
    )
    a_payload = (result.get("lanes") or {}).get("A") if isinstance(result.get("lanes"), Mapping) else None
    hk_payload = (result.get("lanes") or {}).get("HK") if isinstance(result.get("lanes"), Mapping) else None
    a_ready_after, backtest_ready_after = (
        _a_lane_receipt_ready(
            receipt_root,
            target,
            selector_ready_after,
            a_payload if isinstance(a_payload, Mapping) else None,
            formula_generation_pointer,
        )
        if formula_generation_pointer is not None
        else _a_lane_receipt_ready(
            receipt_root, target, selector_ready_after, a_payload if isinstance(a_payload, Mapping) else None
        )
    )
    hk_ready_after = _hk_lane_receipt_ready(
        receipt_root, target, hk_payload if isinstance(hk_payload, Mapping) else None
    )
    lane_ready = (
        (requested_lane == "A" and a_ready_after)
        or (requested_lane == "HK" and hk_ready_after)
        or (requested_lane == "ALL" and a_ready_after and hk_ready_after)
    )
    payload = {
        **common,
        "status": "ATTEMPTED",
        "runner_called": True,
        "idempotent": False,
        "attempt_count": attempt_count + 1,
        "overall_status": result.get("overall_status"),
        "requested_lane": requested_lane,
        "lanes": result.get("lanes", {}),
        "selector_pointer_ready": selector_ready_after,
        "a_lane_ready": a_ready_after,
        "hk_lane_ready": hk_ready_after,
        "backtest_pointer_ready": backtest_ready_after,
        "lane_ready": lane_ready,
    }
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(attempt_path, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def ensure_exit_code(result: Mapping[str, Any]) -> int:
    """Map an after-17:00 result to a truthful process exit code.

    A retry marker or a completed attempt is not success evidence while the
    selector pointer still misses the exact target date.  launchd must keep
    retrying those results instead of recording a false healthy run.
    """

    status = str(result.get("status") or "")
    if "lane_ready" in result:
        lane_ready = result.get("lane_ready") is True
        if status == "BEFORE_1700":
            return 0
        if status in {"ALREADY_READY", "ATTEMPTED"} and lane_ready:
            return 0
        return 2
    pointer_ready = result.get("selector_pointer_ready") is True
    backtest_pointer = result.get("backtest_pointer_ready")
    if backtest_pointer is None:
        lanes = result.get("lanes")
        if isinstance(lanes, Mapping):
            a_lane = lanes.get("A") or lanes.get("a")
            if isinstance(a_lane, Mapping):
                formula = a_lane.get("formula")
                if isinstance(formula, Mapping):
                    backtest_pointer = formula.get("backtest_pointer_ready")
    if backtest_pointer is False:
        pointer_ready = False
    if status == "BEFORE_1700":
        return 0
    if status == "ALREADY_READY" and pointer_ready:
        return 0
    if status == "ATTEMPTED" and pointer_ready:
        return 0
    return 2


def _ensure_pointer_seed(pointer: Path, seed: Path | str | None) -> Path:
    if pointer.exists():
        target = Path(pointer.read_text(encoding="utf-8-sig").strip())
        if target.is_file():
            return target
        raise SnapshotGateError(f"pointer target missing: {pointer}")
    if seed is None:
        raise SnapshotGateError(f"pointer missing and no seed: {pointer}")
    target = Path(seed).resolve()
    if not target.is_file():
        raise SnapshotGateError(f"pointer seed missing: {target}")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(pointer, (str(target) + "\n").encode())
    return target


def run_bounded_process(command: Sequence[str], *, timeout_seconds: float, cwd: Path | str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run one authority child in its own POSIX process group.

    This is a wall-clock boundary only.  macOS RSS/address-space enforcement is
    not claimed here; the child reports that limitation in its receipt.
    """
    timeout = _resolve_a_sync_run_budget(timeout_seconds)
    process = subprocess.Popen(
        [str(item) for item in command],
        cwd=str(Path(cwd).resolve()),
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr[-4000:],
            "timed_out": False,
            "process_group_terminated": False,
            "pid": process.pid,
        }
    except subprocess.TimeoutExpired:
        import signal
        group_terminated = False
        try:
            os.killpg(process.pid, signal.SIGTERM)
            group_terminated = True
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=min(2.0, max(0.1, timeout)))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                group_terminated = True
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr[-4000:],
            "timed_out": True,
            "process_group_terminated": group_terminated,
            "pid": process.pid,
        }


def run_v4_a_formula_offline(
    *,
    input_root: Path | str,
    input_manifest: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    target_date: str,
    timeout_seconds: float,
    legacy_formula_source: Path | str | None = None,
) -> dict[str, Any]:
    """Call the V4 increment runner without importing a legacy authority."""
    project_root = Path(__file__).resolve().parents[1]
    runner = project_root / "ops" / "a_formula_increment.py"
    command = [
        sys.executable,
        str(runner),
        "--target-date", _date(target_date),
        "--input-root", str(Path(input_root).resolve()),
        "--input-manifest", str(Path(input_manifest).resolve()),
        "--data-root", str(Path(data_root).resolve()),
        "--return-root", str(Path(return_root).resolve()),
        "--selector-pointer", str(Path(selector_pointer).resolve()),
        "--backtest-pointer", str(Path(backtest_pointer).resolve()),
        "--selector-seed", str(Path(selector_seed).resolve()),
        "--backtest-seed", str(Path(backtest_seed).resolve()),
        "--contract-csv", str(Path(contract_csv).resolve()),
    ]
    if legacy_formula_source is not None:
        command.extend(["--legacy-formula-source", str(Path(legacy_formula_source).resolve())])
    child_env = dict(os.environ)
    # An offline V4 run must resolve imports from this checkout.  Do not carry
    # an active release/PYTHONPATH into the child process.
    child_env["PYTHONPATH"] = str(project_root)
    process_result = run_bounded_process(command, timeout_seconds=timeout_seconds, cwd=project_root, env=child_env)
    if process_result["timed_out"]:
        raise SnapshotGateError(
            "V4 offline formula timed out: "
            f"pid={process_result['pid']},group_terminated={process_result['process_group_terminated']}"
        )
    outcome = None
    for line in reversed(str(process_result.get("stdout", "")).splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            outcome = dict(value)
            break
    if process_result.get("returncode") != 0 or not isinstance(outcome, Mapping) or outcome.get("status") != "READY":
        detail = "offline V4 formula runner returned no valid READY result"
        if isinstance(outcome, Mapping):
            detail = f"offline V4 formula runner failed: {outcome.get('error_type')}:{outcome.get('error')}"
        raise SnapshotGateError(detail)
    outcome["driver_command"] = command
    outcome["process"] = {
        "returncode": process_result.get("returncode"),
        "timed_out": False,
        "process_group_terminated": False,
        "pid": process_result.get("pid"),
        "stderr_tail": process_result.get("stderr", ""),
        "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
    }
    return outcome


def _strict_v4_path_root(
    generation_pointer: Path | str,
    *,
    tdx_root: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    receipt_root: Path | str,
) -> tuple[Path, Path]:
    """Check that the strict live candidate has one V4-owned write root."""

    pointer = Path(generation_pointer).expanduser()
    pointer_path = pointer / FORMULA_GENERATION_POINTER_NAME if pointer.is_dir() else pointer
    if pointer_path.name != FORMULA_GENERATION_POINTER_NAME:
        raise SnapshotGateError("strict V4 generation pointer must be CURRENT_FORMULA_GENERATION.json")
    root = pointer_path.parent.expanduser().resolve(strict=False)
    expected_return_parent = Path(return_root).expanduser().resolve(strict=False).parent
    if expected_return_parent != root:
        raise SnapshotGateError("strict V4 return root and generation pointer must share one output root")
    raw_values = {
        "tdx_root": Path(tdx_root).expanduser(),
        "data_root": Path(data_root).expanduser(),
        "return_root": Path(return_root).expanduser(),
        "selector_pointer": Path(selector_pointer).expanduser(),
        "backtest_pointer": Path(backtest_pointer).expanduser(),
        "receipt_root": Path(receipt_root).expanduser(),
    }
    for label, raw in raw_values.items():
        current = raw if raw.exists() or raw.is_symlink() else raw.parent
        while True:
            if current.is_symlink():
                raise SnapshotGateError(f"strict V4 {label} has symlink ancestry")
            if current.parent == current:
                break
            current = current.parent
    if "/releases/" in str(root):
        raise SnapshotGateError("strict V4 output root cannot be a formal release root")
    if "/Library/Application Support/" in str(root) and not is_v4_formula_state_owner(root):
        raise SnapshotGateError("strict V4 output root is not the designated V4 formula state owner")
    for label, raw in raw_values.items():
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise SnapshotGateError(f"strict V4 {label} must remain under the generation output root") from error
    root.mkdir(parents=True, exist_ok=True)
    return root, pointer_path


def run_v4_a_live_generation(
    *,
    sync_script: Path | str,
    tdx_root: Path | str,
    receipt_root: Path | str,
    target_date: str,
    minimum_target_date_files: int,
    sync_authority_args: Mapping[str, Any],
    data_root: Path | str,
    return_root: Path | str,
    generation_pointer: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    formula_timeout_seconds: float,
) -> dict[str, Any]:
    """Run the strict V4 live boundary without importing an old formula module."""

    output_root, generation_path = _strict_v4_path_root(
        generation_pointer,
        tdx_root=tdx_root,
        data_root=data_root,
        return_root=return_root,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        receipt_root=receipt_root,
    )
    try:
        existing = read_formula_generation(
            generation_path,
            expected_target_date=_date(target_date),
            require_source=True,
        )
        return {
            "status": "READY",
            "already_current": True,
            "target_date": _date(target_date),
            "sync": {"status": "SKIPPED_EXISTING_GENERATION", "runner_called": False, "network": "NOT_USED"},
            "formula": {"status": "READY", "already_current": True, "generation_pointer": {
                "path": str(existing["path"]),
                "sha256": existing["sha256"],
                "bytes": existing["bytes"],
                "generation_id": existing["generation_id"],
            }},
            "generation": {
                "path": str(existing["path"]),
                "sha256": existing["sha256"],
                "bytes": existing["bytes"],
                "generation_id": existing["generation_id"],
                "target_date": existing["target_date"],
                "selector_source": str(existing["selector_source"]),
                "selector_sidecar": str(existing["selector_sidecar"]),
            },
            "runner_called": False,
            **SAFETY_FLAGS,
        }
    except (FormulaGenerationError, OSError, UnicodeError, ValueError):
        pass

    sync = run_windows_a_sync_authority(
        sync_script,
        Path(tdx_root),
        _date(target_date),
        Path(receipt_root),
        minimum_target_date_files=max(int(minimum_target_date_files), 1),
        authority_args=dict(sync_authority_args),
    )
    sync_receipt = Path(receipt_root).expanduser().resolve() / "a_sync_authority.json"
    if not sync_receipt.is_file():
        raise SnapshotGateError("A sync receipt was not written")
    receipt_sha = _sha256_file(sync_receipt)
    input_root = Path(data_root).expanduser().resolve() / "a_formula_inputs" / f"{_date(target_date)}-{receipt_sha[:16]}"
    from ops.a_formula_input_manifest import build_a_formula_input_manifest

    manifest = build_a_formula_input_manifest(
        sync_receipt=sync_receipt,
        tdx_root=tdx_root,
        output_root=input_root,
        target_date=_date(target_date),
        run_id=f"a-live-{_date(target_date)}-{receipt_sha[:16]}",
    )
    formula = run_v4_a_formula_offline(
        input_root=input_root,
        input_manifest=Path(manifest["path"]),
        data_root=data_root,
        return_root=return_root,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        selector_seed=selector_seed,
        backtest_seed=backtest_seed,
        contract_csv=contract_csv,
        target_date=_date(target_date),
        timeout_seconds=formula_timeout_seconds,
        legacy_formula_source=None,
    )
    try:
        generation = read_formula_generation(
            generation_path,
            expected_target_date=_date(target_date),
            require_source=True,
        )
    except (FormulaGenerationError, OSError, UnicodeError, ValueError) as error:
        raise SnapshotGateError(f"strict V4 formula generation is not verified: {error}") from error
    generation_summary = {
        "path": str(generation["path"]),
        "sha256": generation["sha256"],
        "bytes": generation["bytes"],
        "generation_id": generation["generation_id"],
        "target_date": generation["target_date"],
        "selector_source": str(generation["selector_source"]),
        "selector_source_sha256": generation["selector_source_evidence"]["sha256"],
        "selector_sidecar": str(generation["selector_sidecar"]),
        "selector_sidecar_sha256": generation["selector_sidecar_evidence"]["sha256"],
    }
    return {
        "status": "READY",
        "already_current": False,
        "target_date": _date(target_date),
        "sync": sync,
        "input_manifest": manifest,
        "formula": formula,
        "generation": generation_summary,
        "runner_called": True,
        **SAFETY_FLAGS,
    }


def run_windows_a_formula_authority(
    script_path: Path | str,
    *,
    tdx_root: Path | str,
    data_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str | None,
    backtest_seed: Path | str | None,
    contract_csv: Path | str,
    canonical_formula_path: Path | str,
    return_root: Path | str,
    target_date: str,
    module_name: str = "macos_windows_formula_authority",
) -> dict[str, Any]:
    target = int(_date(target_date))
    data = Path(data_root).resolve()
    tdx = Path(tdx_root).resolve()
    selector_ptr = Path(selector_pointer).resolve()
    backtest_ptr = Path(backtest_pointer).resolve()
    generation = _read_formula_generation(Path(return_root).resolve().parent)
    if generation is not None:
        selector_current = generation["selector"]
        backtest_current = generation["backtest"]
    else:
        selector_current = _ensure_pointer_seed(selector_ptr, selector_seed)
        backtest_current = _ensure_pointer_seed(backtest_ptr, backtest_seed)
    selector_max = _parquet_max_date(selector_current)
    backtest_max = _parquet_max_date(backtest_current)
    if selector_max == target and backtest_max == target:
        return {
            "status": "READY",
            "already_current": True,
            "target_date": target,
            "selector": str(selector_current),
            "backtest": str(backtest_current),
            "selector_pointer_ready": True,
            "backtest_pointer_ready": True,
            "generation_pointer": {
                "path": str(generation["path"]),
                "sha256": generation["sha256"],
                "bytes": generation["bytes"],
                "generation_id": generation["generation_id"],
            } if generation is not None else None,
            **SAFETY_FLAGS,
        }
    module = _load_authority_module(script_path, module_name)
    module.TDX_ROOT = tdx
    module.DATA_ROOT = data
    module.TDX_INDUSTRY_NAMES = tdx / "T0002" / "hq_cache" / "tdxzs.cfg"
    module.TDX_STOCK_INDUSTRIES = tdx / "T0002" / "hq_cache" / "tdxhy.cfg"
    module.XDXR_CACHE_ROOT = data / "runtime" / "cache" / getattr(module, "TASK_NAME", "formula") / "tdx_xdxr"
    module.RULES_FILE = data / "DATA_LAYER_AGENTS_RULES.md"
    module.RETURN_ROOT = Path(return_root).resolve()
    module.SELECTOR_POINTER = selector_ptr
    module.BACKTEST_POINTER = backtest_ptr
    module.SCRIPT_DIR = data / "tools" / "debug_scripts" / getattr(module, "TASK_NAME", "formula")
    module.PROMOTED_SELECTOR_ROOT = data / "selector_ready_panels" / getattr(module, "TASK_NAME", "formula")
    module.PROMOTED_BACKTEST_ROOT = data / "backtest_panels" / getattr(module, "TASK_NAME", "formula")
    module.CONTRACT_CSV = Path(contract_csv).resolve()
    module.CONTRACT_DIR = module.CONTRACT_CSV.parent
    module.CANONICAL_FORMULA_PATH = Path(canonical_formula_path).resolve()
    module.RUN_TS = _datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    module.RUN_DIR = module.RETURN_ROOT / module.RUN_TS
    # macOS uses spawn for multiprocessing; dynamically loaded Windows modules
    # cannot be imported by spawned workers.  The authority already supports a
    # serial branch, so force that branch without changing formula functions.
    if hasattr(module, "DAILY_FORMULA_MAX_WORKERS"):
        module.DAILY_FORMULA_MAX_WORKERS = 1
    module._CANONICAL_FORMULA_MODULE = None
    module.main(False)
    summary_files = sorted(module.RUN_DIR.rglob("task_summary.json"))
    if not summary_files:
        raise SnapshotGateError("formula authority task_summary missing")
    summary = json.loads(summary_files[-1].read_text(encoding="utf-8"))
    if not str(summary.get("final_status", "")).startswith("PASS"):
        raise SnapshotGateError(f"formula authority final_status not PASS: {summary.get('final_status')}")
    generation = _read_formula_generation(Path(return_root).resolve().parent)
    if generation is not None:
        selector_target = generation["selector"]
        backtest_target = generation["backtest"]
    else:
        selector_target = Path(selector_ptr.read_text(encoding="utf-8-sig").strip())
        backtest_target = Path(backtest_ptr.read_text(encoding="utf-8-sig").strip())
    for role, path in (("selector", selector_target), ("backtest", backtest_target)):
        if not path.is_file() or _parquet_max_date(path) != target:
            raise SnapshotGateError(f"{role} pointer target-date postcondition failed: {path}")
    return {
        "status": "READY",
        "target_date": target,
        "selector": str(selector_target),
        "backtest": str(backtest_target),
        "selector_pointer_ready": True,
        "backtest_pointer_ready": True,
        "generation_pointer": {
            "path": str(generation["path"]),
            "sha256": generation["sha256"],
            "bytes": generation["bytes"],
            "generation_id": generation["generation_id"],
        } if generation is not None else None,
        "run_dir": str(module.RUN_DIR),
        "authority": summary,
        **SAFETY_FLAGS,
    }


def run_hk_0_2_authority(updater_script: Path | str, python_executable: Path | str, asset_root: Path | str, tdx_root: Path | str, target_date: str) -> dict[str, Any]:
    target = _date(target_date)
    argv = [str(python_executable), str(Path(updater_script)), "--asset-root", str(Path(asset_root)), "--tdx-root", str(Path(tdx_root)), "--through-date", target]
    completed = subprocess.run(argv, shell=False, check=True, capture_output=True, text=True)
    try:
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise SnapshotGateError("HK authority output is not JSON") from error
    if outcome.get("status") != "READY" or _date(outcome.get("through_date")) != target:
        raise SnapshotGateError(f"HK authority through-date postcondition failed: {outcome}")
    return {**outcome, "target_date": target, "argv": argv, **SAFETY_FLAGS}


def _existing_records(path: Path, record_struct: struct.Struct) -> list[tuple[Any, ...]]:
    if not path.exists():
        return []
    payload = path.read_bytes()
    if len(payload) % record_struct.size:
        raise SnapshotGateError(f"existing .day has trailing bytes: {path.name}")
    return [record_struct.unpack(payload[offset : offset + record_struct.size]) for offset in range(0, len(payload), record_struct.size)]


def _a_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        int(round(_number(row, "open") * 100)),
        int(round(_number(row, "high") * 100)),
        int(round(_number(row, "low") * 100)),
        int(round(_number(row, "close") * 100)),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol"))),
        0,
    )


def _hk_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        _number(row, "open"),
        _number(row, "high"),
        _number(row, "low"),
        _number(row, "close"),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol", default=1))),
        0,
    )


def _pack_day_file(destination: Path, rows: Iterable[Mapping[str, Any]], target_date: str, *, lane: str, minimum_rows: int, record_struct: struct.Struct, record_builder: Callable[[Mapping[str, Any]], tuple[Any, ...]]) -> dict[str, Any]:
    checked, coverage = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    encoded = b"".join(record_struct.pack(*record_builder(row)) for row in checked)
    existing = _existing_records(destination, record_struct)
    target_int = int(_date(target_date))
    existing_dates = [int(record[0]) for record in existing]
    if existing_dates and target_int < max(existing_dates):
        raise SnapshotGateError(f"{lane} target date is older than existing file: {target_date}")
    existing_target = [record_struct.pack(*record) for record in existing if int(record[0]) == target_int]
    if existing_target:
        if b"".join(existing_target) != encoded:
            raise SnapshotGateError(f"{lane} target-date conflict: {destination}")
        return {
            "status": "READY",
            "already_current": True,
            "target_date": _date(target_date),
            "row_count": len(checked),
            "coverage_rate": coverage,
            "sha256": _sha(destination),
            "path": str(destination),
            **SAFETY_FLAGS,
        }
    payload = destination.read_bytes() if destination.exists() else b""
    _atomic_write(destination, payload + encoded)
    return {
        "status": "READY",
        "already_current": False,
        "target_date": _date(target_date),
        "row_count": len(checked),
        "coverage_rate": coverage,
        "sha256": _sha(destination),
        "path": str(destination),
        **SAFETY_FLAGS,
    }


def _a_exchange(row: Mapping[str, Any]) -> str:
    exchange = str(row.get("exchange") or row.get("market") or "").strip().lower()
    if exchange in {"sh", "sz", "bj"}:
        return exchange
    code = _code(row)
    if code.startswith(("6",)):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    raise SnapshotGateError(f"cannot infer A exchange for {code}")


def _grouped_result(results: list[dict[str, Any]], target_date: str, *, lane: str) -> dict[str, Any]:
    if not results:
        raise SnapshotGateError(f"{lane} empty grouped result")
    return {
        "status": "READY",
        "target_date": _date(target_date),
        "row_count": sum(int(result.get("row_count", 0)) for result in results),
        "file_count": len(results),
        "coverage_rate": 1.0,
        "sha256": hashlib.sha256("".join(sorted(str(result["sha256"]) for result in results)).encode()).hexdigest(),
        "files": results,
        **SAFETY_FLAGS,
    }


def pack_a_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 1) -> dict[str, Any]:
    destination = Path(destination)
    incoming = _rows(rows)
    if destination.suffix.lower() == ".day":
        raise SnapshotGateError("pack_a_day destination must be a TDX root, not a single .day file")
    checked, _ = _validate_rows(incoming, target_date, minimum_rows=minimum_rows, lane="A")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in checked:
        grouped.setdefault(_code(row), []).append(row)
    results = []
    for code, code_rows in sorted(grouped.items()):
        exchange = _a_exchange(code_rows[0])
        path = destination / "vipdoc" / exchange / "lday" / f"{exchange}{code.zfill(6)}.day"
        results.append(_pack_day_file(path, code_rows, target_date, lane="A", minimum_rows=1, record_struct=A_DAY_STRUCT, record_builder=_a_record))
    return _grouped_result(results, target_date, lane="A")


def pack_hk_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 600, expected_codes: set[str] | None = None) -> dict[str, Any]:
    destination = Path(destination)
    incoming = _rows(rows)
    if destination.suffix.lower() == ".day":
        raise SnapshotGateError("pack_hk_day destination must be a TDX root, not a single .day file")
    checked, coverage = _validate_rows(incoming, target_date, minimum_rows=minimum_rows, lane="HK")
    if expected_codes is not None:
        expected = {"".join(ch for ch in str(code) if ch.isdigit()).zfill(5) for code in expected_codes}
        actual = {str(row["code"]).zfill(5) for row in checked}
        if actual != expected:
            raise SnapshotGateError(f"HK snapshot coverage mismatch: {len(actual)}/{len(expected)}")
        coverage = len(actual) / max(len(expected), 1)
    results = []
    for row in checked:
        code = str(row["code"]).zfill(5)
        path = destination / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
        results.append(_pack_day_file(path, [row], target_date, lane="HK", minimum_rows=1, record_struct=HK_DAY_STRUCT, record_builder=_hk_record))
    return _grouped_result(results, target_date, lane="HK") | {"coverage_rate": coverage}


def validate_snapshot(rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int, expected_codes: set[str] | None = None, lane: str) -> dict[str, Any]:
    checked, _ = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    actual = {_code(row) for row in checked}
    expected = {_code({"code": code}) for code in expected_codes} if expected_codes else actual
    if actual != expected:
        raise SnapshotGateError(f"{lane} coverage mismatch: {len(actual)}/{len(expected)}")
    canonical = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"trade_date": _date(target_date), "row_count": len(checked), "coverage_rate": len(actual) / max(len(expected), 1), "sha256": hashlib.sha256(canonical).hexdigest(), **SAFETY_FLAGS}


def _receipt(root: Path, lane: str, target_date: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
    payload = {"schema_version": "v3.macos.research_panel_receipt.v1", "lane": lane, "target_date": _date(target_date), **dict(outcome), **SAFETY_FLAGS}
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / f"{lane.lower()}-{_date(target_date)}.json", (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def run_lanes(*, target_date: str, receipt_root: Path | str, a_runner: Callable[[str], Mapping[str, Any]], hk_runner: Callable[[str], Mapping[str, Any]], lane: str = "ALL") -> dict[str, Any]:
    target_date = _date(target_date)
    requested_lane = _normalize_lane(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes: dict[str, dict[str, Any]] = {}
    for lane, runner in (("A", a_runner), ("HK", hk_runner)):
        if lane not in requested:
            lanes[lane] = _not_requested_lane()
            continue
        try:
            outcome = dict(runner(target_date))
            outcome.setdefault("status", "READY")
            if outcome.get("target_date", target_date) != target_date:
                raise SnapshotGateError(f"{lane} exact target date mismatch")
            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, {**outcome, "runner_called": True, "receipt_written": True})
        except Exception as error:  # independent lane: never prevent the other lane
            lanes[lane] = _receipt(Path(receipt_root), lane, target_date, {"status": "FAILED", "error": str(error), "coverage_rate": 0.0, "sha256": "", "runner_called": True, "receipt_written": True})
    statuses = {lanes[name].get("status") for name in requested}
    overall = "READY" if statuses == {"READY"} else "FAILED" if statuses == {"FAILED"} else "PARTIAL"
    return {"schema_version": "v3.macos.research_panel_daily.v1", "target_date": target_date, "requested_lane": requested_lane, "overall_status": overall, "lanes": lanes, **SAFETY_FLAGS}


def _non_trading_day_result(target_date: str, receipt_root: Path | str, *, lane: str = "ALL") -> dict[str, Any]:
    """Emit explicit no-op receipts for an implicit non-trading-day launch."""
    target_date = _date(target_date)
    requested_lane = _normalize_lane(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes = {
        lane: _receipt(
            Path(receipt_root),
            lane,
            target_date,
            {
                "status": "NON_TRADING_DAY",
                "reason_code": "IMPLICIT_DATE_NOT_CROSS_MARKET_TRADING_DAY",
                "coverage_rate": 0.0,
                "row_count": 0,
                "sha256": "",
                "runner_called": False,
            },
        )
        for lane in requested
    }
    lanes.update({name: _not_requested_lane() for name in {"A", "HK"} - requested})
    return {
        "schema_version": "v3.macos.research_panel_daily.v1",
        "target_date": target_date,
        "requested_lane": requested_lane,
        "overall_status": "NON_TRADING_DAY",
        "lanes": lanes,
        "runner_called": False,
        **SAFETY_FLAGS,
    }


def run_scheduled_lanes(
    *,
    target_date: str | None,
    receipt_root: Path | str,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str = "ALL",
) -> dict[str, Any]:
    """Run launchd's implicit date only on a proven A/H business day.

    Callers that supply ``target_date`` retain the existing explicit replay
    semantics, including the ability to diagnose a holiday snapshot.
    """
    explicit_date = target_date is not None
    resolved = _date(target_date if explicit_date else _today_shanghai())
    if not explicit_date and not _scheduled_day_is_cross_market_trading_day(resolved):
        return _non_trading_day_result(resolved, receipt_root, lane=lane)
    return run_lanes(
        target_date=resolved,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=lane,
    )


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


def _public_envelope(result: Mapping[str, Any], receipt_root: Path) -> dict[str, Any]:
    """Bounded stdout protocol; full updater evidence stays in dated receipts.

    Digests bind this invocation's response to the exact bytes, not to a latest
    pointer. The registry independently reads and verifies those bytes. This
    is transport evidence, not a replacement for authority/manifest validation.
    """
    payload = {key: result[key] for key in (
        "target_date", "requested_lane", "overall_status", "status", "runner_called",
        "lane_ready", "selector_pointer_ready", "idempotent",
    ) if key in result}
    # Retain the v16 compact-envelope header; receipt digests are additional
    # transport evidence. The paired registry requires the digest extension.
    overall = result.get("overall_status", result.get("status", "CANNOT_CONFIRM"))
    payload.update(schema_version="v3.macos.research_panel_authority_envelope.v1",
                   status=result.get("status", overall), overall_status=overall,
                   lane=result.get("requested_lane"), **SAFETY_FLAGS)
    lanes = result.get("lanes")
    compact: dict[str, Any] = {}
    if isinstance(lanes, Mapping):
        for lane in ("A", "HK"):
            detail = lanes.get(lane)
            if not isinstance(detail, Mapping):
                continue
            status = str(detail.get("status", "CANNOT_CONFIRM"))
            compact[lane] = {"status": status}
            if status != "NOT_REQUESTED":
                digest = detail.get("receipt_sha256")
                size = detail.get("receipt_bytes")
                if isinstance(digest, str) and isinstance(size, int):
                    compact[lane].update(receipt_sha256=digest, receipt_bytes=size)
                elif detail.get("receipt_written") is not False:
                    name = f"{lane.lower()}-{_date(result.get('target_date'))}.json"
                    raw = SafeRoot(receipt_root).read_bytes(name)
                    compact[lane].update(receipt_sha256=hashlib.sha256(raw).hexdigest(), receipt_bytes=len(raw))
    payload["lanes"] = compact
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research-only A/H daily lane receipt helper")
    parser.add_argument("--date", required=False, default=None)
    parser.add_argument("--lane", choices=LANE_CHOICES, default="ALL")
    parser.add_argument("--receipt-root", required=True, type=Path)
    parser.add_argument("--a-tdx-root", required=False, type=Path)
    parser.add_argument("--hk-tdx-root", required=False, type=Path)
    parser.add_argument("--a-universe", required=False, type=Path, help="Legacy collector input; ignored by authority chain")
    parser.add_argument("--a-minimum-rows", type=int, default=1)
    parser.add_argument("--a-limit", type=int, default=None, help="Canary-only A universe limit; never lowers HK minimum 600")
    parser.add_argument(
        "--a-sync-run-budget-seconds",
        default=None,
        help=f"Positive finite A sync wall-clock budget in seconds (default: {int(DEFAULT_A_SYNC_RUN_BUDGET_SECONDS)}; env: {A_SYNC_RUN_BUDGET_ENV})",
    )
    parser.add_argument(
        "--a-host",
        default=os.environ.get(A_SYNC_HOST_ENV) or None,
        help=f"Explicit pytdx HQ host override (default: env {A_SYNC_HOST_ENV}); otherwise probe official hq_hosts",
    )
    parser.add_argument("--a-port", type=int, default=None, help="Explicit pytdx HQ port (requires --a-host)")
    parser.add_argument("--a-sync-script", type=Path, required=False)
    parser.add_argument("--a-formula-script", type=Path, required=False)
    parser.add_argument("--a-seed-panel", type=Path, required=False)
    parser.add_argument("--a-data-root", type=Path, required=False)
    parser.add_argument("--a-selector-pointer", type=Path, required=False)
    parser.add_argument("--a-backtest-pointer", type=Path, required=False)
    parser.add_argument("--a-selector-seed", type=Path, required=False)
    parser.add_argument("--a-backtest-seed", type=Path, required=False)
    parser.add_argument("--a-contract-csv", type=Path, required=False)
    parser.add_argument("--a-canonical-formula", type=Path, required=False)
    parser.add_argument("--a-return-root", type=Path, required=False)
    parser.add_argument(
        "--a-formula-generation-pointer",
        type=Path,
        default=os.environ.get(A_FORMULA_GENERATION_POINTER_ENV) or None,
        help=f"Strict V4 generation pointer (default: env {A_FORMULA_GENERATION_POINTER_ENV})",
    )
    parser.add_argument("--a-offline-input-root", type=Path, required=False, help="Explicit A parquet input root for an isolated offline run")
    parser.add_argument("--a-offline-input-manifest", type=Path, required=False, help="Manifest binding the A offline input date/source/SHA")
    parser.add_argument("--a-formula-timeout-seconds", type=float, default=900.0, help="Bounded V4 offline formula child wall-clock timeout")
    parser.add_argument("--hk-updater-script", type=Path, required=False)
    parser.add_argument("--hk-python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--hk-asset-root", type=Path, required=False)
    args = parser.parse_args(argv)
    offline_requested = args.a_offline_input_root is not None or args.a_offline_input_manifest is not None
    offline_a = args.a_offline_input_root is not None and args.a_offline_input_manifest is not None
    if offline_requested and not offline_a:
        parser.error("--a-offline-input-root and --a-offline-input-manifest must be supplied together")
    if offline_a and args.lane != "A":
        parser.error("offline A input is only supported with --lane A")
    if offline_a and args.date is None:
        parser.error("offline A input requires an explicit --date")
    if offline_a and (not math.isfinite(args.a_formula_timeout_seconds) or args.a_formula_timeout_seconds <= 0):
        parser.error("--a-formula-timeout-seconds must be a positive finite number")
    raw_a_sync_run_budget = args.a_sync_run_budget_seconds
    if raw_a_sync_run_budget is None:
        raw_a_sync_run_budget = os.environ.get(A_SYNC_RUN_BUDGET_ENV)
    try:
        a_sync_run_budget = _resolve_a_sync_run_budget(raw_a_sync_run_budget) if args.lane != "HK" else None
    except ValueError as error:
        parser.error(str(error))
    args.receipt_root = _absolute_path_argument(parser, args.receipt_root, "--receipt-root")
    if args.lane != "HK":
        if args.a_minimum_rows < 1:
            parser.error("--a-minimum-rows must be positive")
        if args.a_limit is not None and (args.a_limit < 1 or args.a_minimum_rows > args.a_limit):
            parser.error("--a-minimum-rows cannot exceed --a-limit")
        if args.a_port is not None and args.a_host is None:
            parser.error("--a-port requires --a-host")
        if args.a_port is not None and not 1 <= int(args.a_port) <= 65535:
            parser.error("--a-port must be between 1 and 65535")
        if args.a_port is not None and ":" in str(args.a_host):
            parser.error("--a-host must omit the port when --a-port is used")
    authority_paths = {
        "--a-tdx-root": args.a_tdx_root,
        "--hk-tdx-root": args.hk_tdx_root,
        "--a-sync-script": args.a_sync_script,
        "--a-formula-script": args.a_formula_script,
        "--a-seed-panel": args.a_seed_panel,
        "--a-data-root": args.a_data_root,
        "--a-selector-pointer": args.a_selector_pointer,
        "--a-backtest-pointer": args.a_backtest_pointer,
        "--a-selector-seed": args.a_selector_seed,
        "--a-backtest-seed": args.a_backtest_seed,
        "--a-contract-csv": args.a_contract_csv,
        "--a-canonical-formula": args.a_canonical_formula,
        "--a-return-root": args.a_return_root,
        "--a-formula-generation-pointer": args.a_formula_generation_pointer,
        "--hk-updater-script": args.hk_updater_script,
        "--hk-asset-root": args.hk_asset_root,
    }
    authority_paths = {name: value for name, value in authority_paths.items()
        if args.lane == "ALL" or name.startswith("--" + args.lane.lower() + "-")}
    if offline_a:
        authority_paths.update({
            "--a-offline-input-root": args.a_offline_input_root,
            "--a-offline-input-manifest": args.a_offline_input_manifest,
        })
        required_offline = {
            "--a-offline-input-root", "--a-offline-input-manifest", "--a-data-root",
            "--a-selector-pointer", "--a-backtest-pointer", "--a-selector-seed",
            "--a-backtest-seed", "--a-contract-csv", "--a-return-root",
        }
        optional_offline = {"--a-formula-script", "--a-canonical-formula"}
        authority_paths = {
            name: value for name, value in authority_paths.items()
            if name in required_offline or (name in optional_offline and value is not None)
        }
    missing = [name for name, value in authority_paths.items() if value is None and name != "--a-formula-generation-pointer"]
    if missing:
        parser.error("authority chain requires explicit paths: " + ", ".join(missing))
    if authority_paths.get("--a-formula-generation-pointer") is None:
        authority_paths.pop("--a-formula-generation-pointer", None)
    for name, value in authority_paths.items():
        authority_paths[name] = _absolute_path_argument(parser, value, name)
    python_executable = _absolute_path_argument(parser, args.hk_python_executable, "--hk-python-executable") if args.lane != "A" else None

    def run_a(target: str) -> dict[str, Any]:
        if offline_a:
            formula = run_v4_a_formula_offline(
                input_root=authority_paths["--a-offline-input-root"],
                input_manifest=authority_paths["--a-offline-input-manifest"],
                data_root=authority_paths["--a-data-root"],
                return_root=authority_paths["--a-return-root"],
                selector_pointer=authority_paths["--a-selector-pointer"],
                backtest_pointer=authority_paths["--a-backtest-pointer"],
                selector_seed=authority_paths["--a-selector-seed"],
                backtest_seed=authority_paths["--a-backtest-seed"],
                contract_csv=authority_paths["--a-contract-csv"],
                target_date=target,
                timeout_seconds=args.a_formula_timeout_seconds,
                legacy_formula_source=authority_paths.get("--a-formula-script") or authority_paths.get("--a-canonical-formula"),
            )
            return {
                "status": "READY",
                "target_date": target,
                "bootstrap": None,
                "sync": {"status": "SKIPPED_OFFLINE_INPUT", "runner_called": False, "network": "NOT_USED"},
                "formula": formula,
                "sha256": formula.get("receipt_sha256", ""),
                **SAFETY_FLAGS,
            }
        sync_authority_args: dict[str, Any] = {"run_budget_seconds": a_sync_run_budget}
        if args.a_host is not None:
            sync_host = str(args.a_host)
            if args.a_port is not None:
                sync_host = f"{sync_host}:{int(args.a_port)}"
            sync_authority_args["host"] = sync_host
        if args.a_formula_generation_pointer is not None:
            return run_v4_a_live_generation(
                sync_script=authority_paths["--a-sync-script"],
                tdx_root=authority_paths["--a-tdx-root"],
                receipt_root=args.receipt_root,
                target_date=target,
                minimum_target_date_files=max(args.a_minimum_rows, 1),
                sync_authority_args=sync_authority_args,
                data_root=authority_paths["--a-data-root"],
                return_root=authority_paths["--a-return-root"],
                generation_pointer=authority_paths["--a-formula-generation-pointer"],
                selector_pointer=authority_paths["--a-selector-pointer"],
                backtest_pointer=authority_paths["--a-backtest-pointer"],
                selector_seed=authority_paths["--a-selector-seed"],
                backtest_seed=authority_paths["--a-backtest-seed"],
                contract_csv=authority_paths["--a-contract-csv"],
                formula_timeout_seconds=args.a_formula_timeout_seconds,
            )
        day_files_before = _a_day_files(args.a_tdx_root)
        bootstrap = None
        if not day_files_before:
            bootstrap = bootstrap_a_vipdoc_from_panel(authority_paths["--a-seed-panel"], args.a_tdx_root)
        sync = run_windows_a_sync_authority(
            authority_paths["--a-sync-script"],
            args.a_tdx_root,
            target,
            args.receipt_root,
            minimum_target_date_files=max(args.a_minimum_rows, 1),
            authority_args=sync_authority_args,
        )
        formula = run_windows_a_formula_authority(
            authority_paths["--a-formula-script"],
            tdx_root=args.a_tdx_root,
            data_root=authority_paths["--a-data-root"],
            selector_pointer=authority_paths["--a-selector-pointer"],
            backtest_pointer=authority_paths["--a-backtest-pointer"],
            selector_seed=authority_paths["--a-selector-seed"],
            backtest_seed=authority_paths["--a-backtest-seed"],
            contract_csv=authority_paths["--a-contract-csv"],
            canonical_formula_path=authority_paths["--a-canonical-formula"],
            return_root=authority_paths["--a-return-root"],
            target_date=target,
        )
        return {"status": "READY", "target_date": target, "bootstrap": bootstrap, "sync": sync, "formula": formula, "sha256": formula.get("authority", {}).get("source_sha256", ""), **SAFETY_FLAGS}

    def run_hk(target: str) -> dict[str, Any]:
        return _run_hk_retained(target, receipt_root=args.receipt_root,
            tdx_root=args.hk_tdx_root, updater_script=authority_paths["--hk-updater-script"],
            python_executable=python_executable, asset_root=authority_paths["--hk-asset-root"])

    # Existing authorities can print arbitrarily large diagnostics. Keep stdout
    # exclusively for the bounded machine protocol consumed by the registry.
    with contextlib.redirect_stdout(sys.stderr):
        if args.date is None:
            result = ensure_after_1700(
                target_date=_today_shanghai(), receipt_root=args.receipt_root,
                selector_pointer=authority_paths.get("--a-selector-pointer"),
                a_runner=run_a, hk_runner=run_hk, lane=args.lane,
                formula_generation_pointer=authority_paths.get("--a-formula-generation-pointer"),
            )
            exit_code = ensure_exit_code(result)
        else:
            result = run_scheduled_lanes(
                target_date=args.date, receipt_root=args.receipt_root,
                a_runner=run_a, hk_runner=run_hk, lane=args.lane,
            )
            exit_code = 0 if result["overall_status"] in {"READY", "NON_TRADING_DAY"} else 2 if result["overall_status"] == "PARTIAL" else 1
    print(json.dumps(_public_envelope(result, args.receipt_root), ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
