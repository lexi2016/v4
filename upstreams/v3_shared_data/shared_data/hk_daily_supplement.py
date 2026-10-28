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


def requested_sessions(target_date: str, count: int = BAR_COUNT) -> tuple[list[str], str]:
    """Return target plus the preceding full HK sessions; default remains six."""
    target_date = validate_date(target_date)
    if isinstance(count, bool) or count not in {BAR_COUNT, 61}:
        raise ValueError("HK_DAILY_SUPPLEMENT_SESSION_COUNT_INVALID")
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
    while len(previous) < count - 1:
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


def _read_panel_identity(authority_root: Path, target_date: str, *, manifest_relative: str | None = None, manifest_sha256: str | None = None, allow_projection: bool = False) -> dict[str, Any]:
    asset_root = authority_root / "assets" / "hk_0_2"
    if (manifest_relative is None)!=(manifest_sha256 is None):
        raise ValueError('HK_DAILY_SUPPLEMENT_PANEL_PIN_INCOMPLETE')
    if manifest_relative is None:
        pointer = json.loads((asset_root / "panel_latest.json").read_bytes())
        manifest_rel = str(pointer.get("manifest_relative") or "")
    else:
        prefix='assets/hk_0_2/'
        if not manifest_relative.startswith(prefix):raise ValueError('HK_DAILY_SUPPLEMENT_PANEL_PIN_PATH_INVALID')
        manifest_rel=manifest_relative[len(prefix):]
    manifest_path = resolve_under(asset_root, manifest_rel)
    manifest_raw = manifest_path.read_bytes()
    if manifest_sha256 is not None and _sha(manifest_raw)!=manifest_sha256:raise ValueError("HK_DAILY_SUPPLEMENT_PANEL_PIN_SHA_MISMATCH")
    manifest = json.loads(manifest_raw)
    if (manifest.get("asset_schema_version") != "v3_shared_data.hk_0_2_panel_asset.v2"
            or manifest.get("source_contract") != "tdx_vipdoc_71_day+verified_zero_trade_repairs"
            or (manifest.get("panel_max_date") != target_date and not (allow_projection and isinstance(manifest.get("panel_max_date"),str) and manifest["panel_max_date"] > target_date))
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
    if manifest_path.read_bytes()!=manifest_raw or panel_path.read_bytes()!=panel_raw:raise ValueError("HK_DAILY_SUPPLEMENT_PANEL_CHANGED_DURING_READ")
    return {
        "panel_manifest_relative": f"assets/hk_0_2/{manifest_rel}",
        "panel_manifest_sha256": _sha(manifest_raw),
        "manifest_prepared_at": manifest.get("manifest_prepared_at"),
        "panel_relative": f"assets/hk_0_2/{panel_rel}",
        "panel_sha256": panel_sha,
        "panel_max_date": manifest["panel_max_date"],
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


def fetch_hk_daily_bars(
    codes: Sequence[str],
    *,
    start: int = START_OFFSET,
    count: int = BAR_COUNT,
    request_context: Mapping[str, Any] | None = None,
    connector: Callable[[], tuple[Any, str]] = _connect,
    clock: Callable[[], datetime] = _clock,
) -> dict[str, Any]:
    """Fetch immutable raw category-4 / market-71 responses for HK codes.

    This is the shared low-level request used by the bounded sidecar and the
    existing HK daily producer.  It deliberately does not interpret dates,
    apply volume conversion, write a pointer, or choose a source fallback.
    """
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise ValueError("HK_DAILY_SUPPLEMENT_START_INVALID")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("HK_DAILY_SUPPLEMENT_COUNT_INVALID")
    selected: list[str] = []
    for value in codes:
        token = str(value).strip().upper()
        if token.startswith("HK."):
            token = token[3:]
        if len(token) != 5 or not token.isascii() or not token.isdigit():
            raise ValueError("HK_DAILY_SUPPLEMENT_CODE_INVALID")
        selected.append(token)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("HK_DAILY_SUPPLEMENT_CODE_SET_INVALID")
    extra_request = dict(request_context or {})
    if set(extra_request) & {"category", "market", "code", "start", "count"}:
        raise ValueError("HK_DAILY_SUPPLEMENT_REQUEST_CONTEXT_INVALID")

    api, host = connector()
    records: list[dict[str, Any]] = []
    try:
        for code in selected:
            request = {
                "category": CATEGORY_DAILY,
                "market": MARKET_HK,
                "code": code,
                "start": start,
                "count": count,
                **extra_request,
            }
            request_started = clock()
            try:
                response = api.get_instrument_bars(
                    CATEGORY_DAILY, MARKET_HK, code, start, count
                ) or []
                acquired = clock()
                raw_rows = [dict(row) for row in response]
                records.append({
                    "code": f"HK.{code}",
                    "status": "RESPONSE_CAPTURED",
                    "error_code": None,
                    "request": request,
                    "request_sha256": _sha(_canonical(request)),
                    "request_started_at": _time_text(request_started),
                    "response_acquired_at": _time_text(acquired),
                    "request_finished_at": _time_text(clock()),
                    "returned_count": len(raw_rows),
                    "source_rows": raw_rows,
                    "response_sha256": _sha(_canonical(raw_rows)),
                })
            except Exception as error:
                finished = clock()
                records.append({
                    "code": f"HK.{code}",
                    "status": "QUERY_FAILED",
                    "error_code": "HK_DAILY_SUPPLEMENT_QUERY_FAILED",
                    "request": request,
                    "request_sha256": _sha(_canonical(request)),
                    "request_started_at": _time_text(request_started),
                    "response_acquired_at": _time_text(finished),
                    "request_finished_at": _time_text(finished),
                    "returned_count": 0,
                    "source_rows": [],
                    "response_sha256": _sha(_canonical([])),
                    "error_type": type(error).__name__,
                })
    finally:
        api.disconnect()
    return {
        "provider": "PYTDX_EXHQ",
        "host": host,
        "category": CATEGORY_DAILY,
        "market": MARKET_HK,
        "method": "get_instrument_bars",
        "start": start,
        "count": count,
        "records": records,
    }


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

    fetched = fetch_hk_daily_bars(
        selected_codes,
        start=START_OFFSET,
        count=BAR_COUNT,
        request_context={"requested_sessions": sessions},
        connector=connector,
        clock=clock,
    )
    records: list[dict[str, Any]] = []
    for raw_record in fetched["records"]:
        code = raw_record["code"]
        if raw_record["status"] == "QUERY_FAILED":
            records.append({
                **raw_record,
                "missing_sessions": list(sessions),
                "bars": [],
            })
            continue
        raw_rows = raw_record["source_rows"]
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
        missing = [day for day in sessions if day not in seen]
        status = "INVALID" if error_code else ("PENDING" if missing else "READY")
        records.append({
            **raw_record,
            "status": status,
            "error_code": error_code,
            "bars": bars,
            "missing_sessions": missing,
        })

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
        "source": {"provider": "PYTDX_EXHQ", "host": fetched["host"],
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

# Explicit profile: native TDX trade and parser wire param1, not Futu NONE.
TDXPY_PROFILE = {
    "provider": "TDXPY_0_2_7", "category": 4, "start": 0, "count": 128,
    "param1": 1, "adjustment": "TDX_PROTOCOL_PARAM1_FIXED",
    "wheel_sha256": "5514d35608fac2c7b2acf693de6f41ba7ccda58207b65a3f374c89887560737c",
    "parser_sha256": "263abf7d5c63e836bddb6ffb35f7d7150d4a33b7d4ac96eefd49d8a8d64a99ad",
}
TDXPY_NODES = ("116.205.143.214:7727", "103.221.142.82:7727")
TDXPY_MARKETS = {31: "香港主板", 48: "香港创业板", 49: "香港基金"}
WINDOW_SCHEMA = "v3_shared_data.hk_0_2_daily_supplement_tdxpy_window.v1"
WINDOW_MANIFEST = "v3_shared_data.hk_0_2_daily_supplement_tdxpy_manifest.v1"
_TRANSPORT_ERROR_TYPES={"CONNECTIONERROR","CONNECTIONABORTEDERROR","CONNECTIONREFUSEDERROR",
    "CONNECTIONRESETERROR","BROKENPIPEERROR","TIMEOUTERROR","SOCKETTIMEOUT","NETWORKERROR",
    "REMOTEDISCONNECTED","TDXCONNECTIONERROR","TDXSOCKETERROR","TDXTIMEOUTERROR",
    "RESPONSEHEADERRECVFAILS"}
_TRANSPORT_ERROR_CODES={"TDXPY_CONNECT_FAILED","HK_DAILY_SUPPLEMENT_TDX_CONNECT_FAILED"}
_OS_TRANSPORT_MESSAGES=("CONNECTION RESET","CONNECTION REFUSED","CONNECTION ABORTED",
    "BROKEN PIPE","NETWORK IS UNREACHABLE","NO ROUTE TO HOST","TIMED OUT","TEMPORARY FAILURE")


def is_tdxpy_transport_error(error_type,error):
    """Recognize explicit connection/timeout evidence without retrying data quarantine."""
    kind=str(error_type or "").rsplit(".",1)[-1].upper()
    message=str(error or "").upper()
    if kind in _TRANSPORT_ERROR_TYPES or any(code in message for code in _TRANSPORT_ERROR_CODES):
        return True
    return kind in {"OSERROR","IOERROR"} and any(token in message for token in _OS_TRANSPORT_MESSAGES)


def _json_native(value):
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, Mapping):
        return {k: _json_native(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_native(v) for v in value]
    return value


def _catalogue_document(endpoint,calls,available_at,*,failure=None,recovered_from=None,cache_refresh=None):
    if len(calls)<2 or calls[0]['method']!='get_markets' or calls[1]['method']!='get_instrument_count':
        raise ValueError('TDXPY_CATALOGUE_HEADER_MISSING')
    total=calls[1]['response'];rows=[];gaps=[];seen_positions=set();final_total=None
    for call in calls[2:]:
        if call['method']=='get_instrument_info':
            offset,count=call['arguments'];page=call['response']
            if not isinstance(page,list) or len(page)>count:raise ValueError('TDXPY_CATALOGUE_PAGE_INVALID')
            positions=set(range(offset,offset+len(page)))
            if seen_positions & positions:raise ValueError('TDXPY_CATALOGUE_PAGE_OVERLAP')
            seen_positions.update(positions);rows.extend(page)
            if len(page)!=count:gaps.append(dict(code='TDXPY_CATALOGUE_PAGE_INCOMPLETE',start=offset,requested=count,returned=len(page)))
        elif call['method']=='get_instrument_count':final_total=call['response']
        else:raise ValueError('TDXPY_CATALOGUE_REQUESTS_INVALID')
    if final_total is None:gaps.append(dict(code='TDXPY_CATALOGUE_FINAL_COUNT_UNOBSERVED'))
    elif final_total!=total:gaps.append(dict(code='TDXPY_CATALOGUE_TOTAL_CHANGED',initial=total,final=final_total))
    if seen_positions!=set(range(total)):gaps.append(dict(code='TDXPY_GLOBAL_CATALOGUE_COVERAGE_PARTIAL',observed=len(seen_positions),declared=total))
    if failure:gaps.append(dict(code='TDXPY_CATALOGUE_CAPTURE_ERROR',error=failure))
    doc=dict(endpoint=endpoint,markets=calls[0]['response'],rows=rows,total=total,calls=calls,
        available_at=available_at,coverage_status='PARTIAL' if gaps else 'COMPLETE',coverage_gaps=gaps)
    if recovered_from:doc['recovered_from']=recovered_from
    if cache_refresh:doc['cache_refresh']=cache_refresh
    return doc


def _catalogue_transient_failure(doc):
    return any(isinstance(failure,dict)
        and is_tdxpy_transport_error(failure.get('error_type'),failure.get('error'))
        for failure in _catalogue_capture_errors(doc))


def _catalogue_capture_errors(doc):
    return [gap['error'] for gap in doc.get('coverage_gaps',[])
        if gap.get('code')=='TDXPY_CATALOGUE_CAPTURE_ERROR' and isinstance(gap.get('error'),dict)]


def _catalogue_preserves_entries(previous,current):
    if previous.get('endpoint')!=current.get('endpoint') or previous.get('total')!=current.get('total'):
        return False
    if previous.get('markets')!=current.get('markets'):
        return False
    old={(row.get('market'),row.get('code')):row for row in previous.get('rows',[])}
    new={(row.get('market'),row.get('code')):row for row in current.get('rows',[])}
    return len(old)==len(previous.get('rows',[])) and all(new.get(key)==row for key,row in old.items())


def _archive_and_replace_partial_catalogue(output,cpath,previous,current):
    previous_bytes=cpath.read_bytes();previous_sha=_sha(previous_bytes)
    relative=f"catalogues/archive/{previous['endpoint'].replace(':','_')}/{previous_sha}.json"
    archive_path=resolve_under(output,relative)
    if archive_path.exists():
        if archive_path.read_bytes()!=previous_bytes:
            raise ValueError('TDXPY_CATALOGUE_CACHE_ARCHIVE_SHA_COLLISION')
    else:
        _write_atomic(archive_path,previous_bytes,replace=False)
    current=dict(current,cache_refresh=dict(schema_version='v3_shared_data.tdxpy_catalogue_cache_refresh.v1',
        previous_relative=relative,previous_sha256=previous_sha))
    _verify_catalogue(current,output)
    if cpath.read_bytes()!=previous_bytes:
        raise ValueError('TDXPY_CATALOGUE_CACHE_CHANGED_DURING_REFRESH')
    _write_atomic(cpath,_canonical(current),replace=True)
    return current


def _catalogue(api, endpoint, clock):
    """Preserve observed global pages; identity admission remains per security."""
    calls=[]
    def call(method,*args):
        started=_time_text(clock());result=_json_native(getattr(api,method)(*args))
        calls.append(dict(method=method,arguments=list(args),request_sha256=_sha(_canonical(dict(endpoint=endpoint,method=method,arguments=list(args)))),
            started_at=started,available_at=_time_text(clock()),response=result,response_sha256=_sha(_canonical(result))))
        return result
    failure=None
    try:
        call('get_markets');total=call('get_instrument_count')
        if isinstance(total,bool) or not isinstance(total,int) or total<1:raise ValueError('TDXPY_CATALOGUE_COUNT_INVALID')
        for offset in range(0,total,100):
            page=call('get_instrument_info',offset,min(100,total-offset))
            if not isinstance(page,list) or len(page)>min(100,total-offset):raise ValueError('TDXPY_CATALOGUE_PAGE_INVALID')
        call('get_instrument_count')
    except Exception as error:
        failure=dict(error_type=type(error).__name__,error=str(error))
        if len(calls)<2:
            error.tdx_catalogue_attempt=dict(endpoint=endpoint,calls=calls,**failure,available_at=_time_text(clock()))
            raise
    doc=_catalogue_document(endpoint,calls,_time_text(clock()),failure=failure)
    _verify_catalogue(doc)
    return doc


def _verify_catalogue(doc,root=None):
    if doc.get('endpoint') not in TDXPY_NODES:raise ValueError('TDXPY_ENDPOINT_UNAPPROVED')
    calls=doc.get('calls',[]);total=doc.get('total');last_time=None
    if isinstance(total,bool) or not isinstance(total,int) or total<1:raise ValueError('TDXPY_CATALOGUE_COUNT_INVALID')
    if len(calls)<2 or [(c.get('method'),c.get('arguments')) for c in calls[:2]]!=[('get_markets',[]),('get_instrument_count',[])]:raise ValueError('TDXPY_CATALOGUE_REQUESTS_INVALID')
    next_offset=0;ended=False
    for i,c in enumerate(calls):
        if last_time is not None and _timestamp(c['started_at'])<last_time:raise ValueError('TDXPY_CATALOGUE_TIME_ORDER_INVALID')
        last_time=_timestamp(c['available_at'])
        if (c.get('request_sha256')!=_sha(_canonical(dict(endpoint=doc['endpoint'],method=c.get('method'),arguments=c.get('arguments'))))
            or c.get('response_sha256')!=_sha(_canonical(c.get('response'))) or _timestamp(c['started_at'])>last_time):raise ValueError('TDXPY_CATALOGUE_RECEIPT_INVALID')
        if i>=2:
            if c['method']=='get_instrument_info':
                if ended or c['arguments']!=[next_offset,min(100,total-next_offset)] or next_offset>=total:raise ValueError('TDXPY_CATALOGUE_REQUESTS_INVALID')
                next_offset+=100
            elif c['method']=='get_instrument_count':
                if i!=len(calls)-1 or c['arguments']!=[]:raise ValueError('TDXPY_CATALOGUE_REQUESTS_INVALID')
                ended=True
            else:raise ValueError('TDXPY_CATALOGUE_REQUESTS_INVALID')
    failure=next((g['error'] for g in doc.get('coverage_gaps',[]) if g.get('code')=='TDXPY_CATALOGUE_CAPTURE_ERROR'),None)
    rebuilt=_catalogue_document(doc['endpoint'],calls,doc['available_at'],failure=failure,
        recovered_from=doc.get('recovered_from'),cache_refresh=doc.get('cache_refresh'))
    if rebuilt!=doc or calls[1]['response']!=total or _timestamp(doc['available_at'])<last_time:raise ValueError('TDXPY_CATALOGUE_IDENTITY_INVALID')
    cache_refresh=doc.get('cache_refresh')
    if cache_refresh:
        if (root is None or set(cache_refresh)!={'schema_version','previous_relative','previous_sha256'}
                or cache_refresh.get('schema_version')!='v3_shared_data.tdxpy_catalogue_cache_refresh.v1'
                or not cache_refresh.get('previous_relative','').startswith('catalogues/archive/')):
            raise ValueError('TDXPY_CATALOGUE_CACHE_REFRESH_REFERENCE_INVALID')
        previous_bytes=resolve_under(root,cache_refresh['previous_relative']).read_bytes()
        if _sha(previous_bytes)!=cache_refresh['previous_sha256']:
            raise ValueError('TDXPY_CATALOGUE_CACHE_REFRESH_SHA_MISMATCH')
        previous=_verify_catalogue(json.loads(previous_bytes),root)
        if (previous.get('endpoint')!=doc.get('endpoint') or previous.get('coverage_status')!='PARTIAL'
                or not _catalogue_transient_failure(previous)):
            raise ValueError('TDXPY_CATALOGUE_CACHE_REFRESH_SOURCE_INVALID')
    for market,name in TDXPY_MARKETS.items():
        matches=[r for r in doc['markets'] if r.get('market')==market]
        if len(matches)!=1 or matches[0].get('name')!=name or matches[0].get('category')!=2:raise ValueError('TDXPY_HK_MARKET_IDENTITY_INVALID')
    if doc.get('recovered_from'):
        if root is None:raise ValueError('TDXPY_RECOVERED_CATALOGUE_ROOT_REQUIRED')
        source=doc['recovered_from'];raw_bytes=resolve_under(root,source['raw_relative']).read_bytes();manifest_bytes=resolve_under(root,source['manifest_relative']).read_bytes()
        if _sha(raw_bytes)!=source['raw_sha256'] or _sha(manifest_bytes)!=source['manifest_sha256']:raise ValueError('TDXPY_RECOVERY_SOURCE_SHA_MISMATCH')
        raw=json.loads(raw_bytes);manifest=json.loads(manifest_bytes)
        if manifest.get('raw_relative')!=source['raw_relative'] or manifest.get('raw_sha256')!=source['raw_sha256'] or manifest.get('profile')!=TDXPY_PROFILE or raw.get('profile')!=TDXPY_PROFILE:raise ValueError('TDXPY_RECOVERY_PROFILE_INVALID')
        failed=raw['failed_catalogues'][source['failed_catalogue_index']]
        if failed['endpoint']!=doc['endpoint'] or failed['calls']!=calls or failed['available_at']!=doc['available_at']:raise ValueError('TDXPY_RECOVERY_CALLS_IDENTITY_INVALID')
    return doc


def _recover_catalogue(root,endpoint):
    # Reuse the known failed capture's observed pages, preserving its exact
    # immutable raw/manifest identity and actual observation time.
    candidates=[]
    for mp in sorted((root/'runs').glob('*/*/manifest.json')):
        manifest_bytes=mp.read_bytes();manifest=json.loads(manifest_bytes)
        if manifest.get('schema_version')!=WINDOW_MANIFEST or manifest.get('profile')!=TDXPY_PROFILE:continue
        relative=manifest['raw_relative'];raw_bytes=resolve_under(root,relative).read_bytes()
        if _sha(raw_bytes)!=manifest['raw_sha256']:raise ValueError('TDXPY_RECOVERY_SOURCE_SHA_MISMATCH')
        raw=json.loads(raw_bytes)
        for index,failed in enumerate(raw.get('failed_catalogues',[])):
            if failed.get('endpoint')!=endpoint or len(failed.get('calls',[]))<2:continue
            ref=dict(raw_relative=relative,raw_sha256=_sha(raw_bytes),manifest_relative=mp.relative_to(root).as_posix(),manifest_sha256=_sha(manifest_bytes),failed_catalogue_index=index)
            doc=_catalogue_document(endpoint,failed['calls'],failed['available_at'],failure=dict(error_type=failed['error_type'],error=failed['error']),recovered_from=ref)
            _verify_catalogue(doc,root);candidates.append(doc)
    return max(candidates,key=lambda d:len(d['rows'])) if candidates else None


def _catalogue_security(catalogue, code):
    matches = [r for r in catalogue['rows'] if r.get('market') in TDXPY_MARKETS and r.get('code')==code[3:]]
    if len(matches)!=1 or not matches[0].get('name'):
        raise ValueError("TDXPY_SECURITY_MARKET_IDENTITY_UNKNOWN")
    row = matches[0]
    market = next(r for r in catalogue['markets'] if r['market']==row['market'])
    return dict(security=row, market=market)


def _window_bars(source_rows, sessions):
    dates = [_bar_date(r) for r in source_rows]
    if len(dates)!=len(set(dates)):
        raise ValueError("HK_DAILY_SUPPLEMENT_DUPLICATE_DATE")
    wanted = set(sessions)
    bars = [_decode_bar(r,sessions[-1],wanted) for r,d in zip(source_rows,dates) if d in wanted]
    bars.sort(key=lambda b:b['trade_date'])
    if [b['trade_date'] for b in bars] != sessions:
        raise ValueError("TDXPY_EXACT_61_SESSION_INCOMPLETE")
    for b in bars:
        b['native_fields']['price_basis'] = 'TDX_PROTOCOL_PARAM1_FIXED'
    return bars, [d for d in dates if d not in wanted]


def _verify_window_record(record, catalogue, sessions, calendar_sha):
    code=record['code']; security=_catalogue_security(catalogue,code)
    request=dict(**TDXPY_PROFILE,endpoint=catalogue['endpoint'],market=security['security']['market'],
                 code=code,requested_sessions=sessions,calendar_sha256=calendar_sha)
    if record.get('security_identity')!=security or record.get('request')!=request or record.get('request_sha256')!=_sha(_canonical(request)):
        raise ValueError('TDXPY_SECURITY_REQUEST_IDENTITY_INVALID')
    rows=record['source_rows']
    if record.get('response_sha256')!=_sha(_canonical(rows)) or record.get('returned_count')!=len(rows):
        raise ValueError('TDXPY_RESPONSE_SHA_MISMATCH')
    if _timestamp(record['request_started_at'])<_timestamp(catalogue['available_at']) or _timestamp(record['request_started_at'])>_timestamp(record['response_acquired_at']) or _timestamp(record['response_acquired_at'])>_timestamp(record['request_finished_at']):
        raise ValueError('TDXPY_RESPONSE_TIME_INVALID')
    bars,outside=_window_bars(rows,sessions)
    if record.get('bars')!=bars or record.get('outside_requested_sessions')!=outside or record.get('status')!='READY':
        raise ValueError('TDXPY_WINDOW_PROJECTION_INVALID')
    return record


def _saved_panel_binding(output,target_date):
    identities=set()
    for path in sorted((output/'runs').glob('*/*/manifest.json')):
        manifest=json.loads(path.read_bytes())
        if manifest.get('schema_version')!=WINDOW_MANIFEST or manifest.get('target_date')!=target_date or manifest.get('profile')!=TDXPY_PROFILE:continue
        raw_bytes=resolve_under(output,manifest['raw_relative']).read_bytes()
        if _sha(raw_bytes)!=manifest['raw_sha256']:raise ValueError('TDXPY_HISTORY_SOURCE_SHA_MISMATCH')
        raw=json.loads(raw_bytes)
        if raw.get('panel_identity')!=manifest.get('panel_identity'):raise ValueError('TDXPY_HISTORY_PANEL_IDENTITY_MISMATCH')
        panel=manifest['panel_identity'];identities.add((panel['panel_manifest_relative'],panel['panel_manifest_sha256']))
    if len(identities)>1:raise ValueError('TDXPY_HISTORY_PANEL_BINDING_AMBIGUOUS')
    if not identities:return None
    relative,digest=next(iter(identities));return dict(manifest_relative=relative,manifest_sha256=digest)


def read_tdxpy_panel_identity(authority_root,pin,target_date):
    output=Path(pin['source_local_path']).resolve();data=resolve_under(output,pin['manifest_relative']).read_bytes()
    if _sha(data)!=pin['manifest_sha256']:raise ValueError('TDXPY_MANIFEST_RAW_SHA_MISMATCH')
    manifest=json.loads(data)
    if manifest.get('target_date')!=target_date or manifest.get('profile')!=TDXPY_PROFILE:raise ValueError('TDXPY_PANEL_DATE_PROFILE_INVALID')
    panel=manifest['panel_identity']
    return _read_panel_identity(Path(authority_root).resolve(),target_date,
       manifest_relative=panel['panel_manifest_relative'],manifest_sha256=panel['panel_manifest_sha256'],allow_projection=manifest.get('capture_scope') in {'PANEL_GAPS','PANEL_GAP_CANARY'})


def _verify_panel_gap_plan(plan, panel, master, codes, sessions, calendar_sha):
    if (not isinstance(plan,dict) or plan.get('schema_version')!='v3_shared_data.hk_0_2_panel_window_gaps.v1'
            or plan.get('window_validator')!='OVERSOLD_60_5_V1' or plan.get('price_date')!=sessions[-1]
            or plan.get('requested_sessions')!=sessions or plan.get('calendar_sha256')!=calendar_sha
            or plan.get('panel_identity')!=panel or plan.get('master_identity')!=master
            or plan.get('master_scope_count')!=len(codes)
            or plan.get('replacement_reason')!='COMPLETE_61_SAME_PROFILE_REQUIRED_NO_UNVERIFIED_SOURCE_MIX'
            or plan.get('protocol_request_count')!=128 or plan.get('projected_session_count')!=61):
        raise ValueError('TDXPY_PANEL_GAP_PLAN_IDENTITY_INVALID')
    if (panel['panel_max_date']!=sessions[-1] and (plan.get('phase')!='RETROSPECTIVE'
            or not sessions[-1] < panel['panel_max_date'] <= plan.get('target_date',''))):
        raise ValueError('TDXPY_PANEL_PROJECTION_PHASE_INVALID')
    if _timestamp(plan['cutoff'])<_timestamp(panel['manifest_prepared_at']):raise ValueError('TDXPY_PANEL_GAP_PLAN_BEFORE_PARENT')
    rows=plan.get('records',[])
    if ([r.get('code') for r in rows]!=sorted(codes) or any(not isinstance(r.get('reasons'),list)
            or any(not isinstance(x,str) or not x.isidentifier() for x in r['reasons'])
            or not isinstance(r.get('missing_sessions'),list) or not set(r['missing_sessions']).issubset(sessions)
            or (r['missing_sessions'] and not r['reasons']) for r in rows)):
        raise ValueError('TDXPY_PANEL_GAP_SCOPE_INVALID')
    gaps=[r['code'] for r in rows if r['reasons']]
    if (plan.get('gap_codes')!=gaps or plan.get('panel_valid_count')!=len(codes)-len(gaps)):
        raise ValueError('TDXPY_PANEL_GAP_COUNTS_INVALID')
    return gaps


def capture_tdxpy_window_supplement(authority_root, *, target_date, connector,
                                   output_root=None, canary_codes=None, clock=_clock, panel_binding=None, panel_gap_plan=None):
    """Same HK supplement owner, explicit approved profile; no panel mutation.

    connector(endpoint) uses the pinned official SDK, bounded socket timeouts,
    and returns an API. Successful immutable per-security cache is reused only
    for an identical profile/request/calendar/catalogue security identity.
    """
    root=Path(authority_root).resolve(); target_date=validate_date(target_date)
    sessions,calendar_sha=requested_sessions(target_date,61)
    output=Path(output_root).resolve() if output_root else root/'assets/hk_0_2/daily_supplements/tdxpy61'
    saved_binding=_saved_panel_binding(output,target_date) if panel_gap_plan is None else None
    if panel_binding is not None and saved_binding is not None and dict(panel_binding)!=saved_binding:raise ValueError('TDXPY_SAVED_PANEL_BINDING_DRIFT')
    if panel_gap_plan is not None:
        gap_parent=panel_gap_plan['panel_identity']
        gap_binding=dict(manifest_relative=gap_parent['panel_manifest_relative'],manifest_sha256=gap_parent['panel_manifest_sha256'])
        if panel_binding is not None and panel_binding!=gap_binding:raise ValueError('TDXPY_PANEL_GAP_BINDING_MISMATCH')
        panel_binding=gap_binding
    projection_args=dict(allow_projection=True) if panel_gap_plan is not None and panel_gap_plan.get('phase')=='RETROSPECTIVE' else {}
    panel=_read_panel_identity(root,target_date,**(panel_binding or saved_binding or {}),**projection_args)
    master,codes=_read_master_identity(root,target_date)
    subset=normalize_canary_codes(canary_codes)
    gap_codes=_verify_panel_gap_plan(panel_gap_plan,panel,master,codes,sessions,calendar_sha) if panel_gap_plan is not None else codes
    selected=gap_codes if subset is None else subset
    if panel_gap_plan is not None and not set(selected).issubset(gap_codes):raise ValueError('TDXPY_NON_GAP_CAPTURE_FORBIDDEN')
    if panel_gap_plan is not None and not selected:
        return dict(status='NO_PANEL_GAPS',target_date=target_date,scope_count=0,master_scope_count=len(codes),
            ready_count=0,unassessed_count=0,cache_hits=0,network_bar_requests=0,panel_gap_plan_sha256=_sha(_canonical(panel_gap_plan)))
    scope=('PANEL_GAPS' if subset is None else 'PANEL_GAP_CANARY') if panel_gap_plan is not None else ('FULL_MASTER' if subset is None else 'CANARY')
    if not selected or not set(selected).issubset(codes):raise ValueError('TDXPY_SCOPE_INVALID')
    if panel_gap_plan is not None and _timestamp(panel_gap_plan['cutoff'])>_timestamp(_time_text(clock())):raise ValueError('TDXPY_PANEL_GAP_PLAN_AFTER_CAPTURE')
    output.mkdir(parents=True,exist_ok=True)
    with (output/'.capture.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        started=_time_text(clock());catalogues=[];records={};errors={};attempts=[];failed_catalogues=[]
        catalogue_cache_refreshes=[];requests=0;hits=0
        if any(_timestamp(v)>_timestamp(started) for v in (panel['manifest_prepared_at'],master['captured_at'])):
            raise ValueError('TDXPY_PARENT_AFTER_CAPTURE')
        for endpoint in TDXPY_NODES:
            if len(records)==len(selected):break
            api=None;connection_error=None;refresh_needed=False;pending_cache_codes=[]
            cpath=resolve_under(output,'catalogues/'+endpoint.replace(':','_')+'.json')
            try:
                if cpath.exists():
                    catalogue=_verify_catalogue(json.loads(cpath.read_bytes()),output)
                else:
                    catalogue=_recover_catalogue(output,endpoint)
                    if catalogue is not None:
                        # A recovered catalogue is already immutable evidence. Save
                        # it before any refresh so refresh provenance has a source.
                        _write_atomic(cpath,_canonical(catalogue),replace=False)
                if catalogue is None:
                    # A missing catalogue is the only reason to connect before the
                    # exact per-security request cache can be checked.
                    api=connector(endpoint)
                    catalogue=_catalogue(api,endpoint,clock)
                    _write_atomic(cpath,_canonical(catalogue),replace=False)
                else:
                    refresh_needed=_catalogue_transient_failure(catalogue)
                    # Compute exact request cache misses from the cached catalogue
                    # first. A complete cached request set must survive an offline
                    # connector without losing already verified READY records.
                    for code in selected:
                        if code in records:continue
                        try:
                            identity=_catalogue_security(catalogue,code)
                            request=dict(**TDXPY_PROFILE,endpoint=endpoint,market=identity['security']['market'],code=code,
                                         requested_sessions=sessions,calendar_sha256=calendar_sha)
                            cache_path=resolve_under(output,'cache/'+_sha(_canonical(request))+'.json')
                        except Exception:
                            continue
                        if not cache_path.exists():pending_cache_codes.append(code)
                    if refresh_needed or pending_cache_codes:
                        try:
                            api=connector(endpoint)
                        except Exception as error:
                            connection_error=error
                            if refresh_needed:
                                catalogue_cache_refreshes.append(dict(endpoint=endpoint,
                                    previous_sha256=_sha(_canonical(catalogue)),status='FAILED',
                                    error_type=type(error).__name__,error=str(error)))
                    if refresh_needed and api is not None:
                        cached=catalogue
                        try:
                            refreshed=_catalogue(api,endpoint,clock)
                        except Exception as error:
                            catalogue_cache_refreshes.append(dict(endpoint=endpoint,
                                previous_sha256=_sha(_canonical(cached)),status='FAILED',
                                error_type=type(error).__name__,error=str(error)))
                        else:
                            previous_rows=len(cached.get('rows',[]));refreshed_rows=len(refreshed.get('rows',[]))
                            should_replace=(refreshed.get('coverage_status')=='COMPLETE'
                                or (_catalogue_preserves_entries(cached,refreshed)
                                    and (refreshed_rows>previous_rows or not _catalogue_transient_failure(refreshed))))
                            if should_replace:
                                catalogue=_archive_and_replace_partial_catalogue(output,cpath,cached,refreshed)
                                status=('RECOVERED' if catalogue.get('coverage_status')=='COMPLETE'
                                    else 'PARTIAL_REFRESHED_STABLE' if not _catalogue_transient_failure(catalogue)
                                    else 'PARTIAL_IMPROVED')
                            else:
                                status='PARTIAL_NOT_SUPERSET_RETAINED'
                            refresh_event=dict(endpoint=endpoint,previous_sha256=_sha(_canonical(cached)),
                                status=status,refreshed_coverage=refreshed.get('coverage_status'),
                                refreshed_row_count=refreshed_rows)
                            failures=_catalogue_capture_errors(refreshed)
                            if failures:
                                refresh_event.update(refreshed_error_type=failures[0].get('error_type'),
                                    refreshed_error=failures[0].get('error'))
                            catalogue_cache_refreshes.append(refresh_event)
                if _timestamp(catalogue['available_at'])>_timestamp(_time_text(clock())):raise ValueError('TDXPY_CATALOGUE_FUTURE')
                catalogue_sha=_sha(_canonical(catalogue));catalogues.append(catalogue)
                for code in selected:
                    if code in records:continue
                    request=None;rows=None;begin=None;acquired=None
                    try:
                        identity=_catalogue_security(catalogue,code)
                        request=dict(**TDXPY_PROFILE,endpoint=endpoint,market=identity['security']['market'],code=code,
                                     requested_sessions=sessions,calendar_sha256=calendar_sha)
                        cache_path=resolve_under(output,'cache/'+_sha(_canonical(request))+'.json')
                        if cache_path.exists():
                            record=_verify_window_record(json.loads(cache_path.read_bytes()),catalogue,sessions,calendar_sha)
                            hits+=1;records[code]={**record,'cache_hit':True,'catalogue_sha256':catalogue_sha};continue
                        if api is None:
                            if connection_error is not None and (code in pending_cache_codes or refresh_needed):
                                raise connection_error
                            raise ValueError('TDXPY_REQUEST_CACHE_MISS_WITHOUT_NETWORK')
                        begin=_time_text(clock());requests+=1
                        rows=_json_native(api.get_instrument_bars(4,request['market'],code[3:],0,128))
                        acquired=_time_text(clock())
                        if not isinstance(rows,list):raise ValueError('TDXPY_RESPONSE_INVALID')
                        bars,outside=_window_bars(rows,sessions)
                        record=dict(code=code,status='READY',request=request,request_sha256=_sha(_canonical(request)),
                            security_identity=identity,request_started_at=begin,response_acquired_at=acquired,
                            request_finished_at=_time_text(clock()),source_rows=rows,response_sha256=_sha(_canonical(rows)),
                            returned_count=len(rows),bars=bars,outside_requested_sessions=outside,
                            catalogue_sha256=catalogue_sha,cache_hit=False)
                        _verify_window_record(record,catalogue,sessions,calendar_sha)
                        _write_atomic(cache_path,_canonical(record),replace=False);records[code]=record
                    except Exception as error:
                        # Retain failed raw response and exact request whenever
                        # available; no partial bars are admitted as complete.
                        errors.setdefault(code,[]).append(dict(endpoint=endpoint,error_type=type(error).__name__,error=str(error)))
                        attempts.append(dict(code=code,endpoint=endpoint,request=request,
                            request_sha256=_sha(_canonical(request)) if request else None,request_started_at=begin,
                            response_acquired_at=acquired,request_finished_at=_time_text(clock()),source_rows=rows,
                            response_sha256=_sha(_canonical(rows)) if rows is not None else None,
                            error_type=type(error).__name__,error=str(error)))
            except Exception as error:
                if hasattr(error,'tdx_catalogue_attempt'):failed_catalogues.append(error.tdx_catalogue_attempt)
                for code in selected:
                    if code not in records:errors.setdefault(code,[]).append(dict(endpoint=endpoint,error_type=type(error).__name__,error=str(error)))
            finally:
                if api is not None:api.disconnect()
        for code in selected:
            if code not in records:records[code]=dict(code=code,status='UNASSESSED',errors=errors.get(code,[]),bars=[])
        prepared=_time_text(clock())
        raw=dict(schema_version=WINDOW_SCHEMA,target_date=target_date,requested_sessions=sessions,calendar_sha256=calendar_sha,
            profile=TDXPY_PROFILE,capture_scope=scope,selected_codes=selected,
            panel_identity=panel,master_identity=master,capture_started_at=started,available_at=prepared,
            catalogues=catalogues,records=[records[c] for c in selected],errors=errors,failed_attempts=attempts,
            failed_catalogues=failed_catalogues,catalogue_cache_refreshes=catalogue_cache_refreshes,
            network_bar_requests=requests,cache_hits=hits,**SAFETY)
        if panel_gap_plan is not None:
            raw.update(panel_gap_plan=panel_gap_plan,panel_gap_plan_sha256=_sha(_canonical(panel_gap_plan)))
        raw_bytes=_canonical(raw);raw_sha=_sha(raw_bytes);run_id=raw_sha[:24]
        relative=f'runs/{target_date}/{run_id}/raw_capture.json'
        manifest=dict(schema_version=WINDOW_MANIFEST,target_date=target_date,run_id=run_id,raw_relative=relative,raw_sha256=raw_sha,
            profile=TDXPY_PROFILE,requested_sessions=sessions,calendar_sha256=calendar_sha,available_at=prepared,
            capture_scope=raw['capture_scope'],code_count=len(selected),master_code_count=len(codes),selected_codes_sha256=_sha(_canonical(selected)),
            panel_identity=panel,master_identity=master,catalogue_coverage_status='PARTIAL' if any(c['coverage_status']=='PARTIAL' for c in catalogues) else 'COMPLETE',ready_count=sum(r['status']=='READY' for r in records.values()),
            unassessed_count=sum(r['status']!='READY' for r in records.values()),**SAFETY)
        if panel_gap_plan is not None:
            manifest.update(panel_gap_plan_sha256=raw['panel_gap_plan_sha256'],gap_codes=gap_codes,
                panel_valid_count=panel_gap_plan['panel_valid_count'],projection_price_date=target_date)
        manifest_rel=f'runs/{target_date}/{run_id}/manifest.json'
        _write_atomic(resolve_under(output,relative),raw_bytes,replace=False)
        _write_atomic(resolve_under(output,manifest_rel),_canonical(manifest),replace=False)
        return dict(source_local_path=str(output),manifest_relative=manifest_rel,manifest_sha256=_sha(_canonical(manifest)),
            raw_relative=relative,raw_sha256=raw_sha,run_id=run_id,scope_count=len(selected),master_scope_count=len(codes),
            ready_count=manifest['ready_count'],unassessed_count=manifest['unassessed_count'],cache_hits=hits,network_bar_requests=requests,
            available_at=prepared,target_date=target_date,
            **(dict(panel_gap_plan_sha256=raw['panel_gap_plan_sha256']) if panel_gap_plan is not None else {}))


def read_tdxpy_window_supplement(pin, *, target_date, cutoff, expected_panel_sha, expected_master_sha, expected_codes, expected_panel_manifest_sha=None, expected_master_manifest_sha=None):
    root=Path(pin['source_local_path']).resolve()
    raw_bytes=resolve_under(root,pin['raw_relative']).read_bytes()
    manifest_bytes=resolve_under(root,pin['manifest_relative']).read_bytes()
    if _sha(raw_bytes)!=pin['raw_sha256'] or _sha(manifest_bytes)!=pin['manifest_sha256']:
        raise ValueError('TDXPY_ARTIFACT_RAW_SHA_MISMATCH')
    raw=json.loads(raw_bytes);manifest=json.loads(manifest_bytes)
    sessions,calendar_sha=requested_sessions(target_date,61)
    if (raw.get('schema_version')!=WINDOW_SCHEMA or manifest.get('schema_version')!=WINDOW_MANIFEST
            or raw.get('target_date')!=target_date or manifest.get('target_date')!=target_date
            or raw.get('profile')!=TDXPY_PROFILE or manifest.get('profile')!=TDXPY_PROFILE
            or manifest.get('raw_relative')!=pin['raw_relative'] or manifest.get('raw_sha256')!=pin['raw_sha256']
            or manifest.get('run_id')!=pin['raw_sha256'][:24] or manifest.get('available_at')!=raw.get('available_at')
            or any(raw.get(k)!=v or manifest.get(k)!=v for k,v in SAFETY.items())):
        raise ValueError('TDXPY_MANIFEST_IDENTITY_INVALID')
    for doc in (raw,manifest):
        if (doc.get('requested_sessions')!=sessions or doc.get('calendar_sha256')!=calendar_sha
                or doc['panel_identity']['panel_sha256']!=expected_panel_sha
                or doc['master_identity']['artifact_sha256']!=expected_master_sha
                or (expected_panel_manifest_sha is not None and doc['panel_identity'].get('panel_manifest_sha256')!=expected_panel_manifest_sha)
                or (expected_master_manifest_sha is not None and doc['master_identity'].get('manifest_sha256')!=expected_master_manifest_sha)
                or _timestamp(doc['available_at'])>_timestamp(cutoff)):
            raise ValueError('TDXPY_WINDOW_PARENT_OR_CUTOFF_INVALID')
    if raw['panel_identity']!=manifest['panel_identity'] or raw['master_identity']!=manifest['master_identity'] or _timestamp(raw['capture_started_at'])>_timestamp(raw['available_at']):
        raise ValueError('TDXPY_PARENT_OR_TIME_INVALID')
    selected=raw['selected_codes']
    if (selected!=sorted(set(selected)) or not set(selected).issubset(expected_codes)
            or (raw['capture_scope']=='FULL_MASTER' and set(selected)!=set(expected_codes))
            or raw['capture_scope'] not in {'FULL_MASTER','CANARY','PANEL_GAPS','PANEL_GAP_CANARY'} or manifest['capture_scope']!=raw['capture_scope']
            or (raw['capture_scope'] in {'CANARY','PANEL_GAP_CANARY'} and len(selected)>3)
            or manifest['code_count']!=len(selected) or manifest['master_code_count']!=len(expected_codes)
            or manifest['selected_codes_sha256']!=_sha(_canonical(selected))
            or raw['master_identity']['universe_codes_sha256']!=_sha(_canonical(sorted(expected_codes)))):
        raise ValueError('TDXPY_FULL_MASTER_SCOPE_INVALID')
    if raw['capture_scope'] in {'PANEL_GAPS','PANEL_GAP_CANARY'}:
        plan=raw.get('panel_gap_plan')
        gaps=_verify_panel_gap_plan(plan,raw['panel_identity'],raw['master_identity'],sorted(expected_codes),sessions,calendar_sha)
        if (raw.get('panel_gap_plan_sha256')!=_sha(_canonical(plan)) or manifest.get('panel_gap_plan_sha256')!=raw['panel_gap_plan_sha256']
                or manifest.get('gap_codes')!=gaps or manifest.get('panel_valid_count')!=plan['panel_valid_count']
                or manifest.get('projection_price_date')!=target_date or not set(selected).issubset(gaps)
                or (raw['capture_scope']=='PANEL_GAPS' and selected!=gaps)
                or _timestamp(plan['cutoff'])>_timestamp(raw['capture_started_at'])):
            raise ValueError('TDXPY_PANEL_GAP_DERIVATION_INVALID')
    catalogues={_sha(_canonical(c)):_verify_catalogue(c,root) for c in raw['catalogues']}
    if any(_timestamp(c['available_at'])>_timestamp(raw['available_at']) for c in catalogues.values()):raise ValueError('TDXPY_CATALOGUE_AFTER_CAPTURE')
    expected_coverage='PARTIAL' if any(c['coverage_status']=='PARTIAL' for c in catalogues.values()) else 'COMPLETE'
    if manifest.get('catalogue_coverage_status')!=expected_coverage:raise ValueError('TDXPY_CATALOGUE_COVERAGE_STATUS_INVALID')
    records=raw['records']
    if [r['code'] for r in records]!=selected:raise ValueError('TDXPY_RECORD_SCOPE_INVALID')
    for record in records:
        if record['status']=='READY':
            cat=catalogues[record['catalogue_sha256']]
            _verify_window_record(record,cat,sessions,calendar_sha)
            if _timestamp(record['request_finished_at'])>_timestamp(raw['available_at']):raise ValueError('TDXPY_RESPONSE_AFTER_CAPTURE')
        elif record['status']!='UNASSESSED' or record.get('bars')!=[]:
            raise ValueError('TDXPY_RECORD_STATUS_INVALID')
    if manifest['ready_count']!=sum(r['status']=='READY' for r in records) or manifest['unassessed_count']!=sum(r['status']!='READY' for r in records):
        raise ValueError('TDXPY_RECORD_COUNTS_INVALID')
    if resolve_under(root,pin['raw_relative']).read_bytes()!=raw_bytes or resolve_under(root,pin['manifest_relative']).read_bytes()!=manifest_bytes:
        raise ValueError('TDXPY_ARTIFACT_CHANGED_DURING_READ')
    return manifest,records

__all__ += ["capture_tdxpy_window_supplement", "read_tdxpy_window_supplement", "read_tdxpy_panel_identity"]
