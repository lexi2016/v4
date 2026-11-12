"""Single-writer A-share D-1 daily evidence artifact.

The collector reads only the exact verified V2 stage universe and PyTDX HQ
daily bars.  Publication goes through the shared store's existing immutable
artifact/manifest/receipt/latest path; the reader delegates trio verification
to ``read_verified_latest`` and validates only this module's row semantics.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

from .consumer import read_verified_latest
from .hashing import sha256_json
from .market_calendar import evaluate_a_share_trade_date
from .store import SafeRootStore, StoreError
from .allowlist import AllowlistRegistry, SourceSpec
from scripts.live_acquisition.universe import (
    UNIVERSE_SCHEMA_VERSION_V2,
    resolve_stage_universe,
)


ROLE = "A_SHARE_D1_DAILY_EVIDENCE_V1"
SOURCE = "PYTDX_HQ_A_D1_DAILY"
_DATE_FMT = "%Y%m%d"
_A_MARKET = {"SH": 1, "SZ": 0, "BJ": 2}


def _prior_a_session(target_date: str) -> str:
    try:
        datetime.strptime(target_date, _DATE_FMT)
    except ValueError as error:
        raise ValueError("target_trade_date must use YYYYMMDD") from error
    cursor = datetime.strptime(target_date, _DATE_FMT).date() - timedelta(days=1)
    while cursor.year == 2026:
        date8 = cursor.strftime(_DATE_FMT)
        if bool(evaluate_a_share_trade_date(date8).get("eligible")):
            return date8
        cursor -= timedelta(days=1)
    raise ValueError("no prior A-share trading date in frozen calendar")


def _canonical_codes(store_root: Path, target_date: str) -> tuple[list[str], list[str]]:
    universe = resolve_stage_universe(store_root, target_date, "A_SHARE")
    if universe.schema_version != UNIVERSE_SCHEMA_VERSION_V2:
        raise ValueError("A D-1 evidence requires exact V2 stage universe")
    if universe.path.name != "A_SHARE_STAGE_CANDIDATES_V2.json":
        raise ValueError("A D-1 evidence cannot use legacy universe")
    if len(universe.codes) != 219:
        raise ValueError("A D-1 evidence requires the exact 219-code universe")
    futu_codes: list[str] = []
    canonical: list[str] = []
    for value in universe.codes:
        exchange, code = str(value).split(".", 1)
        futu_codes.append(f"{exchange}.{code}")
        canonical.append(f"A.{code}")
    if len(set(canonical)) != len(canonical):
        raise ValueError("A D-1 universe contains duplicate codes")
    return futu_codes, canonical


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_date(row: Mapping[str, Any]) -> str | None:
    try:
        return f"{int(row.get('year')):04d}{int(row.get('month')):02d}{int(row.get('day')):02d}"
    except (TypeError, ValueError):
        return None


def _connect_default_api(probe_market: int, probe_code: str, signal_date: str) -> Any:
    from pytdx.config.hosts import hq_hosts
    from pytdx.hq import TdxHq_API

    if isinstance(probe_market, bool) or probe_market not in (0, 1, 2):
        raise ValueError("PyTDX HQ probe market must be SH=1, SZ=0 or BJ=2")
    if not isinstance(probe_code, str) or len(probe_code) != 6 or not probe_code.isdigit():
        raise ValueError("PyTDX HQ probe code must be a six-digit string")
    try:
        datetime.strptime(signal_date, _DATE_FMT)
    except (TypeError, ValueError) as error:
        raise ValueError("PyTDX HQ probe signal date must use YYYYMMDD") from error

    for entry in hq_hosts[:12]:
        host, port = _host_port(entry)
        api = TdxHq_API(heartbeat=False)
        connected = False
        try:
            if api.connect(host, port, time_out=1.2):
                connected = True
                bars = api.get_security_bars(9, probe_market, probe_code, 0, 80) or []
                by_date = {
                    date: _number(bar.get("close"))
                    for bar in bars
                    if isinstance(bar, Mapping)
                    for date in [_bar_date(bar)]
                    if date is not None and _number(bar.get("close")) not in (None, 0)
                }
                prior_dates = sorted(date for date in by_date if date < signal_date)
                if by_date.get(signal_date) not in (None, 0) and prior_dates:
                    return api
        except Exception:
            pass
        try:
            if connected:
                api.disconnect()
            else:
                api.disconnect()
        except Exception:
            pass
    raise ConnectionError("no PyTDX HQ host available")


def _host_port(entry: Any) -> tuple[str, int]:
    """Extract host/port from official ``(name, host, port)`` or test pairs."""
    if not isinstance(entry, (tuple, list)) or len(entry) not in (2, 3):
        raise ValueError("PyTDX HQ host entry must be a 2- or 3-tuple")
    values = entry[-2:]
    host = str(values[0]).strip()
    if not host:
        raise ValueError("PyTDX HQ host is empty")
    try:
        port = int(values[1])
    except (TypeError, ValueError) as error:
        raise ValueError("PyTDX HQ port is invalid") from error
    if not 1 <= port <= 65535:
        raise ValueError("PyTDX HQ port is out of range")
    return host, port


def _collect_rows(
    store_root: Path,
    target_date: str,
    *,
    api: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str], str, str]:
    futu_codes, canonical_codes = _canonical_codes(store_root, target_date)
    signal_date = _prior_a_session(target_date)
    owned_api = api is None
    if api is None:
        first_exchange, first_code = futu_codes[0].split(".", 1)
        api = _connect_default_api(_A_MARKET[first_exchange], first_code, signal_date)
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    try:
        for futu_code, canonical in zip(futu_codes, canonical_codes):
            exchange, code = futu_code.split(".", 1)
            try:
                bars = api.get_security_bars(
                    9, _A_MARKET[exchange], str(code), 0, 80
                ) or []
                by_date = {
                    date: _number(bar.get("close"))
                    for bar in bars
                    if isinstance(bar, Mapping)
                    for date in [_bar_date(bar)]
                    if date is not None and _number(bar.get("close")) not in (None, 0)
                }
                close = by_date.get(signal_date)
                prior_dates = sorted(date for date in by_date if date < signal_date)
                previous = by_date.get(prior_dates[-1]) if prior_dates else None
                if close is None or previous in (None, 0):
                    missing.append(canonical)
                    continue
                change = round((close / previous - 1) * 100, 4)
                rows.append({
                    "symbol": canonical,
                    "signal_date": signal_date,
                    "target_date": target_date,
                    "close": close,
                    "prev_close": previous,
                    "d1_change_pct": change,
                    "source": f"{SOURCE}:{signal_date}",
                })
            except Exception:
                missing.append(canonical)
    finally:
        if owned_api:
            try:
                api.disconnect()
            except Exception:
                pass
    return rows, missing, signal_date, sha256_json(canonical_codes)


def _write_source(path: Path, rows: list[dict[str, Any]], target_date: str) -> None:
    fields = [
        "trade_date", "bar_time", "symbol", "signal_date", "target_date",
        "close", "prev_close", "d1_change_pct", "source",
        "open", "high", "low", "volume",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "trade_date": target_date,
                "bar_time": "15:00:00",
                "open": row["close"],
                "high": row["close"],
                "low": row["close"],
                "volume": 0,
            })


def publish_a_d1_evidence(
    store_root: Path | str,
    target_trade_date: str,
    python_path: Path | str | None = None,
    *,
    process_runner: Callable[..., Any] | None = None,
    api: Any | None = None,
    historical_backfill: bool = False,
    expected_previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect and publish one exact target-date A D-1 evidence run.

    ``python_path`` and ``process_runner`` are accepted for the frozen caller
    contract; the injected ``api`` is used by deterministic tests, while the
    default path opens PyTDX HQ directly.
    """
    del python_path, process_runner
    root = Path(store_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows, missing, signal_date, codes_sha = _collect_rows(root, target_trade_date, api=api)
    source_id = f"a_d1_daily_{target_trade_date}_{codes_sha[:12]}"
    source_fd, source_name = tempfile.mkstemp(prefix="a_d1_", suffix=".csv", dir=root)
    os.close(source_fd)
    source_path = Path(source_name)
    try:
        _write_source(source_path, rows, target_trade_date)
        cannot = ("A_D1_EVIDENCE_INCOMPLETE",) if missing else ()
        spec = SourceSpec(
            source_id=source_id,
            role=ROLE,
            trade_date=target_trade_date,
            market="A_SHARE",
            stages=("D1_PREMARKET",),
            cutoff_at="15:00:00",
            source_path=source_path,
            required_columns=("trade_date", "bar_time", "open", "high", "low", "close", "volume"),
            cannot_confirm=cannot,
            provenance={
                "role": ROLE,
                "signal_date": signal_date,
                "target_date": target_trade_date,
                "codes_sha256": codes_sha,
                "missing_symbols": ",".join(missing),
            },
        )
        allowlist = AllowlistRegistry({(target_trade_date, ROLE): (spec,)})
        result = SafeRootStore(root, allowlist=allowlist).replay_file(
            owner="v3_shared_data",
            trade_date=target_trade_date,
            role=ROLE,
            source_id=source_id,
            stage_id="D1_PREMARKET",
            historical_backfill=historical_backfill,
            expected_previous=expected_previous,
        )
        result.update({
            "role": ROLE,
            "signal_date": signal_date,
            "target_date": target_trade_date,
            "row_count": len(rows),
            "missing_symbols": missing,
            "codes_sha256": codes_sha,
            "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        })
        return result
    finally:
        try:
            source_path.unlink()
        except FileNotFoundError:
            pass


def collect_a_d1_evidence(
    store_root: Path | str,
    target_trade_date: str,
    *,
    api: Any | None = None,
    api_factory: Callable[[], Any] | None = None,
    historical_backfill: bool = False,
    expected_previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility-shaped collection entry used by local evidence tests."""
    if api is None and api_factory is not None:
        api = api_factory()
    return publish_a_d1_evidence(
        store_root,
        target_trade_date,
        api=api,
        historical_backfill=historical_backfill,
        expected_previous=expected_previous,
    )


def read_verified_a_d1_evidence(
    store_root: Path | str, *, target_trade_date: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read exact role/latest via the shared verifier and validate row fields."""
    run = read_verified_latest(store_root, target_trade_date, ROLE)
    manifest = run.manifest
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("role") != ROLE:
        raise StoreError("A D-1 provenance missing")
    signal_date = str(provenance.get("signal_date") or "")
    if signal_date != _prior_a_session(target_trade_date):
        raise StoreError("A D-1 signal date mismatch")
    expected_futu, expected_codes = _canonical_codes(Path(store_root), target_trade_date)
    del expected_futu
    rows: dict[str, dict[str, Any]] = {}
    with run.artifact_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            symbol = str(raw.get("symbol") or "")
            if symbol not in expected_codes or symbol in rows:
                raise StoreError("A D-1 row symbol/order mismatch")
            if raw.get("signal_date") != signal_date or raw.get("target_date") != target_trade_date:
                raise StoreError("A D-1 row date mismatch")
            try:
                close = float(raw["close"])
                previous = float(raw["prev_close"])
                change = float(raw["d1_change_pct"])
            except (KeyError, TypeError, ValueError) as error:
                raise StoreError("A D-1 row numeric fields invalid") from error
            rows[symbol] = {
                "symbol": symbol,
                "signal_date": signal_date,
                "target_date": target_trade_date,
                "close": close,
                "prev_close": previous,
                "d1_change_pct": change,
                "source": raw.get("source") or f"{SOURCE}:{signal_date}",
            }
    missing_symbols = [symbol for symbol in expected_codes if symbol not in rows]
    status = str(run.receipt.get("status") or "")
    if status == "READY" and missing_symbols:
        raise StoreError("READY A D-1 evidence is incomplete")
    evidence = {
        "role": ROLE,
        "status": status,
        "signal_date": signal_date,
        "target_date": target_trade_date,
        "row_count": len(rows),
        "missing_symbols": missing_symbols,
        "artifact_sha256": run.verification["artifact_sha256"],
        "manifest_sha256": run.verification["manifest_sha256"],
        "receipt_sha256": run.verification["receipt_sha256"],
        "codes_sha256": provenance.get("codes_sha256"),
        "safety": {key: False for key in ("production_allowed", "buy_gate_updated", "orders_sent")},
    }
    return rows, evidence


__all__ = [
    "ROLE",
    "collect_a_d1_evidence",
    "publish_a_d1_evidence",
    "read_verified_a_d1_evidence",
]
