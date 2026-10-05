"""Research-only PyTDX daily-bar supplement owned by the HK0.2 updater.

This sidecar preserves native category-4 ``trade`` values and binds every
capture to the exact immutable HK0.2 panel and HK security-master revision.
It never mutates the canonical panel pointer or applies volume/unit conversion.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .paths import resolve_under, validate_date

POINTER_SCHEMA = "v3_shared_data.hk_0_2_daily_supplement_pointer.v1"
MANIFEST_SCHEMA = "v3_shared_data.hk_0_2_daily_supplement_manifest.v2"
CAPTURE_SCHEMA = "v3_shared_data.hk_0_2_daily_supplement_capture.v2"
CATEGORY_DAILY = 4
MARKET_HK = 71
START_OFFSET = 0
BAR_COUNT = 6
SOURCE_HOST = "119.97.142.130"
SOURCE_PORT = 7721
SAFETY = {"research_only": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _time_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("HK_DAILY_SUPPLEMENT_NAIVE_CLOCK")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("HK_DAILY_SUPPLEMENT_TIME_MISSING")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("HK_DAILY_SUPPLEMENT_TIME_NAIVE")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("HK_DAILY_SUPPLEMENT_NUMBER_INVALID")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("HK_DAILY_SUPPLEMENT_NUMBER_INVALID") from error
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError("HK_DAILY_SUPPLEMENT_NUMBER_INVALID")
    return number


def requested_sessions(target_date: str) -> tuple[list[str], str]:
    """Return target plus its five immediately preceding full HK sessions."""
    target_date = validate_date(target_date)
    from contracts.trading_calendar import (
        CALENDAR_PATH, TradingDayState, load_market_calendar,
        previous_session, resolve_market_states,
    )

    calendar_bytes = CALENDAR_PATH.read_bytes()
    calendar = load_market_calendar()
    if resolve_market_states(calendar, target_date)["hk_securities"] != TradingDayState.FULL_TRADING_DAY:
        raise ValueError("HK_DAILY_SUPPLEMENT_TARGET_NOT_FULL_SESSION")
    previous: list[str] = []
    cursor = target_date
    while len(previous) < 5:
        cursor = previous_session(calendar, cursor, market="hk_securities")
        if resolve_market_states(calendar, cursor)["hk_securities"] == TradingDayState.FULL_TRADING_DAY:
            previous.append(cursor)
    if CALENDAR_PATH.read_bytes() != calendar_bytes:
        raise ValueError("HK_DAILY_SUPPLEMENT_CALENDAR_CHANGED")
    return sorted(previous) + [target_date], _sha(calendar_bytes)


def _safe_identity_path(root: Path, absolute: str | Path) -> str:
    path = Path(absolute).resolve()
    path.relative_to(root.resolve())
    relative = path.relative_to(root.resolve()).as_posix()
    resolve_under(root, relative)
    return relative


def _read_panel_identity(authority_root: Path, target_date: str) -> dict[str, Any]:
    asset_root = authority_root / "assets" / "hk_0_2"
    pointer = json.loads((asset_root / "panel_latest.json").read_bytes())
    manifest_rel = str(pointer.get("manifest_relative") or "")
    manifest_path = resolve_under(asset_root, manifest_rel)
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest.get("asset_schema_version") != "v3_shared_data.hk_0_2_panel_asset.v2"
            or manifest.get("source_contract") != "tdx_vipdoc_71_day+verified_zero_trade_repairs"
            or manifest.get("panel_max_date") != target_date
            or manifest.get("research_only") is not True
            or manifest.get("production_allowed") is not False
            or manifest.get("buy_gate_updated") is not False
            or manifest.get("orders_sent") is not False):
        raise ValueError("HK_DAILY_SUPPLEMENT_PANEL_IDENTITY_INVALID")
    panel_rel = str(manifest.get("panel_relative") or "")
    panel_path = resolve_under(asset_root, panel_rel)
    panel_raw = panel_path.read_bytes()
    panel_sha = _sha(panel_raw)
    if panel_sha != manifest.get("panel_sha256"):
        raise ValueError("HK_DAILY_SUPPLEMENT_PANEL_SHA_MISMATCH")
    return {
        "panel_manifest_relative": f"assets/hk_0_2/{manifest_rel}",
        "panel_manifest_sha256": _sha(manifest_raw),
        "manifest_prepared_at": manifest.get("manifest_prepared_at"),
        "panel_relative": f"assets/hk_0_2/{panel_rel}",
        "panel_sha256": panel_sha,
        "panel_max_date": target_date,
    }


def _read_master_identity(authority_root: Path, target_date: str) -> tuple[dict[str, Any], list[str]]:
    from .hk_security_master import load_verified_hk_security_master

    rows, manifest = load_verified_hk_security_master(authority_root, target_date)
    asset_root = authority_root / "assets" / "hk_security_master"
    latest = json.loads((asset_root / "latest.json").read_bytes())
    entry = latest["entries"][target_date]
    manifest_rel = str(entry["manifest_relative"])
    manifest_raw = resolve_under(asset_root, manifest_rel).read_bytes()
    artifact_rel = str(manifest["artifact_relative"])
    artifact_raw = resolve_under(asset_root, artifact_rel).read_bytes()
    codes = sorted(rows)
    return ({
        "manifest_relative": f"assets/hk_security_master/{manifest_rel}",
        "manifest_sha256": _sha(manifest_raw),
        "artifact_relative": f"assets/hk_security_master/{artifact_rel}",
        "artifact_sha256": _sha(artifact_raw),
        "run_id": str(manifest["run_id"]),
        "trade_date": target_date,
        "row_count": len(codes),
        "universe_codes_sha256": _sha(_canonical(codes)),
        "captured_at": manifest.get("captured_at"),
    }, codes)


def normalize_canary_codes(values: Sequence[str] | None) -> list[str] | None:
    """Normalize a deliberately small explicit HK security-master subset."""
    if values is None:
        return None
    tokens = [part.strip().upper() for value in values for part in str(value).split(",")]
    if not tokens or any(not token for token in tokens):
        raise ValueError("HK_DAILY_SUPPLEMENT_CANARY_CODES_INVALID")
    normalized: list[str] = []
    for token in tokens:
        code = token[3:] if token.startswith("HK.") else token
        if len(code) != 5 or not code.isascii() or not code.isdigit():
            raise ValueError("HK_DAILY_SUPPLEMENT_CANARY_CODES_INVALID")
        normalized.append("HK." + code)
    if len(set(normalized)) != len(normalized):
        raise ValueError("HK_DAILY_SUPPLEMENT_CANARY_CODES_DUPLICATE")
    if len(normalized) > 3:
        raise ValueError("HK_DAILY_SUPPLEMENT_CANARY_CODES_LIMIT_EXCEEDED")
    return sorted(normalized)


def _bar_date(row: Mapping[str, Any]) -> str:
    raw_date = row.get("datetime")
    if raw_date:
        parsed = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
    else:
        parsed = date(int(row["year"]), int(row["month"]), int(row["day"]))
    return parsed.strftime("%Y%m%d")


def _decode_bar(row: Mapping[str, Any], target_date: str,
                requested: set[str]) -> dict[str, Any] | None:
    day = _bar_date(row)
    if day > target_date:
        raise ValueError("HK_DAILY_SUPPLEMENT_FUTURE_ROW")
    if day not in requested:
        return None
    open_, high = _finite(row.get("open"), positive=True), _finite(row.get("high"), positive=True)
    low, close = _finite(row.get("low"), positive=True), _finite(row.get("close"), positive=True)
    trade = _finite(row.get("trade"), positive=False)
    amount = _finite(row.get("amount"), positive=False) if row.get("amount") is not None else None
    if high < max(open_, low, close) or low > min(open_, high, close):
        raise ValueError("HK_DAILY_SUPPLEMENT_OHLC_INVALID")
    return {"trade_date": day, "open": open_, "high": high, "low": low,
            "close": close, "trade": trade, "amount": amount,
            "native_fields": {"volume_field": "trade", "amount_field": "amount",
                              "scale_applied": 1, "volume_unit": None,
                              "volume_unit_status": "NOT_PROVEN",
                              "price_basis": "NOT_PROVEN"}}


def _connect() -> tuple[Any, str]:
    from pytdx.exhq import TdxExHq_API

    api = TdxExHq_API(heartbeat=False, auto_retry=False, raise_exception=True)
    if not api.connect(SOURCE_HOST, SOURCE_PORT, time_out=2.0):
        try:
            api.disconnect()
        finally:
            raise ConnectionError("HK_DAILY_SUPPLEMENT_TDX_CONNECT_FAILED")
    return api, f"{SOURCE_HOST}:{SOURCE_PORT}"


def _write_atomic(path: Path, data: bytes, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and path.exists():
            raise FileExistsError(path.name)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _pointer_bytes(pointer_path: Path) -> bytes | None:
    try:
        return pointer_path.read_bytes()
    except FileNotFoundError:
        return None


def capture_daily_supplement(
    authority_root: Path | str,
    *,
    target_date: str,
    canary_codes: Sequence[str] | None = None,
    connector: Callable[[], tuple[Any, str]] = _connect,
    clock: Callable[[], datetime] = _clock,
) -> dict[str, Any]:
    """Capture one exact master universe into an immutable sidecar run.

    Calling this function performs network reads and writes only the daily
    sidecar namespace. The normal HK0.2 panel and ``panel_latest`` are untouched.
    """
    target_date = validate_date(target_date)
    canary_codes = normalize_canary_codes(canary_codes)
    root = Path(authority_root).expanduser().resolve()
    sessions, calendar_sha = requested_sessions(target_date)
    panel = _read_panel_identity(root, target_date)
    master, codes = _read_master_identity(root, target_date)
    if not codes:
        raise ValueError("HK_DAILY_SUPPLEMENT_EMPTY_SECURITY_MASTER")
    selected_codes = codes if canary_codes is None else canary_codes
    if canary_codes is not None and not set(canary_codes).issubset(codes):
        raise ValueError("HK_DAILY_SUPPLEMENT_CANARY_CODE_OUTSIDE_MASTER")
    capture_started_at = clock()
    capture_started_utc = _timestamp(_time_text(capture_started_at))
    parent_times = (
        _timestamp(panel.get("manifest_prepared_at")),
        _timestamp(master.get("captured_at")),
    )
    if any(value > capture_started_utc for value in parent_times):
        raise ValueError("HK_DAILY_SUPPLEMENT_PARENT_AFTER_CAPTURE_START")
    asset_root = root / "assets" / "hk_0_2"
    pointer_rel = f"daily_supplements/pointers/{target_date}.json"
    pointer_path = resolve_under(asset_root, pointer_rel)
    if canary_codes is None:
        prior_pointer = _pointer_bytes(pointer_path)
        prior_doc = json.loads(prior_pointer) if prior_pointer is not None else None
        prior_manifest_sha = str((prior_doc or {}).get("manifest_sha256") or "") or None
    else:
        prior_pointer = None
        prior_manifest_sha = None

    api, host = connector()
    records: list[dict[str, Any]] = []
    try:
        for code in selected_codes:
            request = {"category": CATEGORY_DAILY, "market": MARKET_HK,
                       "code": code.split(".", 1)[1], "start": START_OFFSET,
                       "count": BAR_COUNT, "requested_sessions": sessions}
            request_started = clock()
            try:
                response = api.get_instrument_bars(
                    CATEGORY_DAILY, MARKET_HK, request["code"], START_OFFSET, BAR_COUNT
                ) or []
                acquired = clock()
                raw_rows = [dict(row) for row in response]
                bars: list[dict[str, Any]] = []
                seen: set[str] = set()
                error_code = None
                try:
                    source_dates = [_bar_date(row) for row in raw_rows]
                    if len(set(source_dates)) != len(source_dates):
                        raise ValueError("HK_DAILY_SUPPLEMENT_DUPLICATE_DATE")
                    for row in raw_rows:
                        bar = _decode_bar(row, target_date, set(sessions))
                        if bar is not None:
                            seen.add(bar["trade_date"])
                            bars.append(bar)
                except (ValueError, KeyError, TypeError, OverflowError) as error:
                    error_code = str(error) if str(error).startswith("HK_DAILY_SUPPLEMENT_") else "HK_DAILY_SUPPLEMENT_ROW_INVALID"
                    bars = []
                finished = clock()
                missing = [day for day in sessions if day not in seen]
                status = "INVALID" if error_code else ("PENDING" if missing else "READY")
                records.append({
                    "code": code, "status": status, "error_code": error_code,
                    "request": request, "request_sha256": _sha(_canonical(request)),
                    "request_started_at": _time_text(request_started),
                    "response_acquired_at": _time_text(acquired),
                    "request_finished_at": _time_text(finished),
                    "returned_count": len(raw_rows), "source_rows": raw_rows,
                    "response_sha256": _sha(_canonical(raw_rows)), "bars": bars,
                    "missing_sessions": missing,
                })
            except Exception as error:
                finished = clock()
                records.append({
                    "code": code, "status": "QUERY_FAILED",
                    "error_code": "HK_DAILY_SUPPLEMENT_QUERY_FAILED",
                    "request": request, "request_sha256": _sha(_canonical(request)),
                    "request_started_at": _time_text(request_started),
                    "response_acquired_at": _time_text(finished),
                    "request_finished_at": _time_text(finished),
                    "returned_count": 0, "source_rows": [],
                    "response_sha256": _sha(_canonical([])), "bars": [],
                    "missing_sessions": list(sessions),
                    "error_type": type(error).__name__,
                })
    finally:
        api.disconnect()

    prepared_at = clock()
    prepared_utc = _timestamp(_time_text(prepared_at))
    if prepared_utc < capture_started_utc:
        raise ValueError("HK_DAILY_SUPPLEMENT_CAPTURE_TIME_ORDER_INVALID")
    for record in records:
        times = [_timestamp(record[key]) for key in
                 ("request_started_at", "response_acquired_at", "request_finished_at")]
        if not capture_started_utc <= times[0] <= times[1] <= times[2] <= prepared_utc:
            raise ValueError("HK_DAILY_SUPPLEMENT_CAPTURE_TIME_ORDER_INVALID")
    statuses = [record["status"] for record in records]
    status = "READY" if all(value == "READY" for value in statuses) else "PARTIAL_WITH_PENDING"
    capture_scope = "FULL_MASTER" if canary_codes is None else "CANARY"
    raw_capture = {
        "schema_version": CAPTURE_SCHEMA, "target_date": target_date,
        "requested_sessions": sessions, "calendar_sha256": calendar_sha,
        "capture_scope": capture_scope, "canary_codes": canary_codes,
        "capture_started_at": _time_text(capture_started_at),
        "capture_prepared_at": _time_text(prepared_at),
        "source": {"provider": "PYTDX_EXHQ", "host": host,
                   "category": CATEGORY_DAILY, "market": MARKET_HK,
                   "method": "get_instrument_bars", "start": START_OFFSET,
                   "count": BAR_COUNT},
        "records": records, **SAFETY,
    }
    raw_bytes = _canonical(raw_capture)
    raw_sha = _sha(raw_bytes)
    run_id = _sha(_canonical({"target_date": target_date, "raw_capture_sha256": raw_sha,
                              "panel": panel, "master": master,
                              "selected_codes": selected_codes}))[:24]
    run_rel = (f"daily_supplements/runs/{target_date}/{run_id}" if canary_codes is None
               else f"daily_supplements/canary_staging/{target_date}/{run_id}")
    raw_rel = f"{run_rel}/raw_capture.json"
    manifest_rel = f"{run_rel}/manifest.json"
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "status": status,
        "target_date": target_date, "run_id": run_id,
        "raw_capture_relative": raw_rel, "raw_capture_sha256": raw_sha,
        "requested_sessions": sessions, "calendar_sha256": calendar_sha,
        "capture_scope": capture_scope, "canary_codes": canary_codes,
        "capture_started_at": _time_text(capture_started_at),
        "prepared_at": _time_text(prepared_at), "provider": "PYTDX_EXHQ",
        "method": "get_instrument_bars", "category": CATEGORY_DAILY,
        "market": MARKET_HK, "start": START_OFFSET, "count": BAR_COUNT,
        "code_count": len(selected_codes), "master_code_count": len(codes),
        "selected_codes": selected_codes,
        "selected_codes_sha256": _sha(_canonical(selected_codes)),
        "universe_codes_sha256": master["universe_codes_sha256"],
        "panel_identity": panel, "security_master_identity": master,
        "record_status_counts": {key: statuses.count(key) for key in sorted(set(statuses))},
        "publication_status": ("OFFICIAL_DAILY_POINTER_CAS" if canary_codes is None
                               else "CANARY_STAGED_NOT_CONSUMER_READABLE"),
        **SAFETY,
    }
    manifest_bytes = _canonical(manifest)
    manifest_sha = _sha(manifest_bytes)

    run_root = resolve_under(asset_root, run_rel)
    if canary_codes is not None:
        # Canary captures are immutable and have no date pointer, so a partial
        # subset can never be read as the full owner input by the consumer.
        staged_at = clock()
        if _timestamp(_time_text(staged_at)) < prepared_utc:
            raise ValueError("HK_DAILY_SUPPLEMENT_CAPTURE_TIME_ORDER_INVALID")
        manifest["staged_at"] = _time_text(staged_at)
        manifest_bytes = _canonical(manifest)
        manifest_sha = _sha(manifest_bytes)
        run_root.mkdir(parents=True, exist_ok=False)
        _write_atomic(resolve_under(asset_root, raw_rel), raw_bytes, replace=False)
        _write_atomic(resolve_under(asset_root, manifest_rel), manifest_bytes, replace=False)
        return {"status": "CANARY_STAGED", "capture_status": status,
                "publication_status": "CANARY_STAGED_NOT_CONSUMER_READABLE",
                "target_date": target_date, "run_id": run_id,
                "manifest_relative": manifest_rel, "manifest_sha256": manifest_sha,
                "raw_capture_sha256": raw_sha, "code_count": len(selected_codes),
                "master_code_count": len(codes), "selected_codes": selected_codes,
                "record_status_counts": manifest["record_status_counts"], **SAFETY}

    # The lock makes the official pointer replacement a compare-and-swap
    # against the exact bytes observed before acquisition. The panel pointer
    # is outside this sidecar namespace.
    lock_path = resolve_under(asset_root, f"daily_supplements/pointers/.{target_date}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if _pointer_bytes(pointer_path) != prior_pointer:
            raise ValueError("HK_DAILY_SUPPLEMENT_POINTER_CAS_CONFLICT")
        run_root.mkdir(parents=True, exist_ok=False)
        _write_atomic(resolve_under(asset_root, raw_rel), raw_bytes, replace=False)
        _write_atomic(resolve_under(asset_root, manifest_rel), manifest_bytes, replace=False)
        published_at = clock()
        if _timestamp(_time_text(published_at)) < prepared_utc:
            raise ValueError("HK_DAILY_SUPPLEMENT_CAPTURE_TIME_ORDER_INVALID")
        pointer = {
            "schema_version": POINTER_SCHEMA, "target_date": target_date,
            "run_id": run_id, "manifest_relative": manifest_rel,
            "manifest_sha256": manifest_sha, "raw_capture_relative": raw_rel,
            "raw_capture_sha256": raw_sha, "published_at": _time_text(published_at),
            "previous_manifest_sha256": prior_manifest_sha,
            "panel_identity": panel, "security_master_identity": master,
            **SAFETY,
        }
        _write_atomic(pointer_path, _canonical(pointer), replace=True)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {"status": status, "target_date": target_date, "run_id": run_id,
            "manifest_relative": manifest_rel, "manifest_sha256": manifest_sha,
            "raw_capture_sha256": raw_sha, "code_count": len(selected_codes),
            "record_status_counts": manifest["record_status_counts"], **SAFETY}


def read_verified_daily_supplement(
    authority_root: Path | str,
    *,
    target_date: str,
    requested: list[str],
    research_cutoff: str,
    expected_panel: Mapping[str, Any],
    expected_master: Mapping[str, Any],
    expected_codes: list[str],
) -> dict[str, Any] | None:
    """Read one stable exact-date sidecar; absent pointer returns ``None``."""
    target_date = validate_date(target_date)
    cutoff = _timestamp(research_cutoff)
    exact_sessions, calendar_sha = requested_sessions(target_date)
    if requested != exact_sessions:
        raise ValueError("HK_DAILY_SUPPLEMENT_REQUESTED_SESSIONS_INVALID")
    root = Path(authority_root).expanduser().resolve()
    asset_root = root / "assets" / "hk_0_2"
    pointer_rel = f"daily_supplements/pointers/{target_date}.json"
    pointer_path = resolve_under(asset_root, pointer_rel)
    try:
        pointer_raw = pointer_path.read_bytes()
    except FileNotFoundError:
        return None
    pointer = json.loads(pointer_raw)
    if (pointer.get("schema_version") != POINTER_SCHEMA
            or pointer.get("target_date") != target_date
            or pointer.get("production_allowed") is not False
            or pointer.get("buy_gate_updated") is not False
            or pointer.get("orders_sent") is not False
            or pointer.get("research_only") is not True
            or pointer.get("panel_identity", {}).get("panel_sha256") != expected_panel.get("panel_sha256")
            or pointer.get("panel_identity", {}).get("panel_manifest_sha256") != expected_panel.get("panel_manifest_sha256")
            or pointer.get("panel_identity", {}).get("manifest_prepared_at") != expected_panel.get("manifest_prepared_at")
            or pointer.get("security_master_identity", {}).get("manifest_sha256") != expected_master.get("manifest_sha256")
            or pointer.get("security_master_identity", {}).get("artifact_sha256") != expected_master.get("artifact_sha256")
            or pointer.get("security_master_identity", {}).get("captured_at") != expected_master.get("captured_at")):
        raise ValueError("HK_DAILY_SUPPLEMENT_POINTER_IDENTITY_INVALID")
    if _timestamp(pointer.get("published_at")) > cutoff:
        raise ValueError("HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF")
    manifest_rel = str(pointer.get("manifest_relative") or "")
    raw_rel = str(pointer.get("raw_capture_relative") or "")
    manifest_raw = resolve_under(asset_root, manifest_rel).read_bytes()
    raw_raw = resolve_under(asset_root, raw_rel).read_bytes()
    if _sha(manifest_raw) != pointer.get("manifest_sha256") or _sha(raw_raw) != pointer.get("raw_capture_sha256"):
        raise ValueError("HK_DAILY_SUPPLEMENT_CHECKSUM_MISMATCH")
    manifest, capture = json.loads(manifest_raw), json.loads(raw_raw)
    if (manifest.get("schema_version") != MANIFEST_SCHEMA
            or manifest.get("target_date") != target_date
            or manifest.get("run_id") != pointer.get("run_id")
            or manifest.get("raw_capture_relative") != raw_rel
            or manifest.get("raw_capture_sha256") != pointer.get("raw_capture_sha256")
            or manifest.get("requested_sessions") != requested
            or manifest.get("calendar_sha256") != calendar_sha
            or manifest.get("capture_scope") != "FULL_MASTER"
            or manifest.get("canary_codes") is not None
            or manifest.get("provider") != "PYTDX_EXHQ"
            or manifest.get("method") != "get_instrument_bars"
            or manifest.get("category") != CATEGORY_DAILY
            or manifest.get("market") != MARKET_HK
            or manifest.get("start") != START_OFFSET
            or manifest.get("count") != BAR_COUNT
            or manifest.get("research_only") is not True
            or manifest.get("production_allowed") is not False
            or manifest.get("buy_gate_updated") is not False
            or manifest.get("orders_sent") is not False
            or capture.get("schema_version") != CAPTURE_SCHEMA
            or capture.get("target_date") != target_date
            or capture.get("requested_sessions") != requested
            or capture.get("calendar_sha256") != calendar_sha
            or capture.get("capture_scope") != "FULL_MASTER"
            or capture.get("canary_codes") is not None
            or capture.get("research_only") is not True
            or capture.get("production_allowed") is not False
            or capture.get("buy_gate_updated") is not False
            or capture.get("orders_sent") is not False
            or capture.get("source") != {
                "provider": "PYTDX_EXHQ", "host": f"{SOURCE_HOST}:{SOURCE_PORT}",
                "category": CATEGORY_DAILY, "market": MARKET_HK,
                "method": "get_instrument_bars", "start": START_OFFSET,
                "count": BAR_COUNT,
            }
            or manifest.get("panel_identity") != pointer.get("panel_identity")
            or manifest.get("security_master_identity") != pointer.get("security_master_identity")):
        raise ValueError("HK_DAILY_SUPPLEMENT_MANIFEST_CONTRACT_INVALID")
    prepared = _timestamp(manifest.get("prepared_at"))
    capture_started = _timestamp(manifest.get("capture_started_at"))
    panel_ready = _timestamp(manifest.get("panel_identity", {}).get("manifest_prepared_at"))
    master_ready = _timestamp(manifest.get("security_master_identity", {}).get("captured_at"))
    if (prepared > cutoff or capture_started > prepared
            or panel_ready > capture_started or master_ready > capture_started
            or _timestamp(capture.get("capture_started_at")) != capture_started
            or _timestamp(capture.get("capture_prepared_at")) != prepared
            or _timestamp(pointer.get("published_at")) < prepared):
        raise ValueError("HK_DAILY_SUPPLEMENT_PREPARED_AFTER_CUTOFF")
    if (manifest.get("code_count") != len(expected_codes)
            or manifest.get("master_code_count") != len(expected_codes)
            or manifest.get("selected_codes") != sorted(expected_codes)
            or manifest.get("selected_codes_sha256") != _sha(_canonical(sorted(expected_codes)))
            or manifest.get("universe_codes_sha256") != _sha(_canonical(sorted(expected_codes)))):
        raise ValueError("HK_DAILY_SUPPLEMENT_UNIVERSE_MISMATCH")
    records = capture.get("records")
    if not isinstance(records, list) or [r.get("code") for r in records] != sorted(expected_codes):
        raise ValueError("HK_DAILY_SUPPLEMENT_RECORD_UNIVERSE_INVALID")
    by_code: dict[str, Any] = {}
    for record in records:
        code = record["code"]
        request = record.get("request")
        if (request.get("category") != CATEGORY_DAILY or request.get("market") != MARKET_HK
                or request.get("code") != code.split(".", 1)[1]
                or request.get("start") != START_OFFSET or request.get("count") != BAR_COUNT
                or request.get("requested_sessions") != requested
                or record.get("request_sha256") != _sha(_canonical(request))
                or record.get("response_sha256") != _sha(_canonical(record.get("source_rows")))):
            raise ValueError("HK_DAILY_SUPPLEMENT_REQUEST_OR_RESPONSE_INVALID")
        source_rows = record.get("source_rows")
        if not isinstance(source_rows, list) or record.get("returned_count") != len(source_rows):
            raise ValueError("HK_DAILY_SUPPLEMENT_SOURCE_ROWS_INVALID")
        times = [_timestamp(record[key]) for key in
                 ("request_started_at", "response_acquired_at", "request_finished_at")]
        if not capture_started <= times[0] <= times[1] <= times[2] <= prepared or any(value > cutoff for value in times):
            raise ValueError("HK_DAILY_SUPPLEMENT_RECORD_TIME_INVALID")
        bars = record.get("bars")
        if record.get("status") not in {"READY", "PENDING", "INVALID", "QUERY_FAILED"}:
            raise ValueError("HK_DAILY_SUPPLEMENT_RECORD_STATUS_INVALID")
        if record.get("status") in {"INVALID", "QUERY_FAILED"} and bars:
            raise ValueError("HK_DAILY_SUPPLEMENT_INVALID_CODE_HAS_BARS")
        seen: set[str] = set()
        for bar in bars or []:
            day = bar.get("trade_date")
            if day not in requested or day > target_date or day in seen:
                raise ValueError("HK_DAILY_SUPPLEMENT_BAR_DATE_INVALID")
            seen.add(day)
            if (bar.get("native_fields", {}).get("scale_applied") != 1
                    or bar.get("native_fields", {}).get("volume_unit_status") != "NOT_PROVEN"
                    or bar.get("native_fields", {}).get("volume_unit") is not None):
                raise ValueError("HK_DAILY_SUPPLEMENT_BAR_UNIT_INVALID")
        if record.get("status") in {"READY", "PENDING"}:
            source_dates = [_bar_date(row) for row in source_rows]
            if len(set(source_dates)) != len(source_dates):
                raise ValueError("HK_DAILY_SUPPLEMENT_DUPLICATE_SOURCE_DATE")
            decoded = [bar for row in source_rows
                       if (bar := _decode_bar(row, target_date, set(requested))) is not None]
            if _canonical(decoded) != _canonical(bars):
                raise ValueError("HK_DAILY_SUPPLEMENT_NORMALIZED_ROWS_MISMATCH")
            missing = [day for day in requested if day not in seen]
            expected_status = "READY" if not missing else "PENDING"
            if record.get("status") != expected_status or record.get("missing_sessions") != missing:
                raise ValueError("HK_DAILY_SUPPLEMENT_MISSING_SESSION_STATUS_INVALID")
        by_code[code] = record
    status_counts = {key: sum(record.get("status") == key for record in records)
                     for key in sorted({record.get("status") for record in records})}
    aggregate_status = ("READY" if status_counts == {"READY": len(expected_codes)}
                        else "PARTIAL_WITH_PENDING")
    if (manifest.get("record_status_counts") != status_counts
            or manifest.get("status") != aggregate_status
            or capture.get("source", {}).get("host") != f"{SOURCE_HOST}:{SOURCE_PORT}"):
        raise ValueError("HK_DAILY_SUPPLEMENT_AGGREGATE_OR_SOURCE_INVALID")
    if (pointer_path.read_bytes() != pointer_raw
            or resolve_under(asset_root, manifest_rel).read_bytes() != manifest_raw
            or resolve_under(asset_root, raw_rel).read_bytes() != raw_raw):
        raise ValueError("HK_DAILY_SUPPLEMENT_CHANGED_DURING_READ")
    return {"status": manifest["status"], "target_date": target_date,
            "requested_sessions": requested, "manifest": manifest,
            "pointer": pointer, "records": by_code,
            "manifest_sha256": _sha(manifest_raw),
            "raw_capture_sha256": _sha(raw_raw)}


__all__ = ["capture_daily_supplement", "read_verified_daily_supplement",
           "requested_sessions", "normalize_canary_codes"]
