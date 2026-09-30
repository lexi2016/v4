"""Immutable pre-cutoff HK full-scan snapshots for Stage 8."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..contracts import STAGE_BY_ID
from ..live_collectors import (
    _canonical_hk_code,
    _load_shared_module,
    _safe_number,
    _scoped_process_runner,
)

BridgeRunner = Callable[..., Any]

_HK_ACTIVE_SNAPSHOT_SCHEMA = "stage_center.hk_active_snapshot.v1"
_HK_ACTIVE_SNAPSHOT_DIR = ".hk_active_snapshots"
_HK_ACTIVE_SNAPSHOT_MARKET = "HK_CONNECT"
_HK_ACTIVE_SNAPSHOT_SOURCE_ROLE = "FUTU_HKCONNECT_FULL_SCAN"
_HK_ACTIVE_SNAPSHOT_CAPTURE_START_AT = "15:50:00"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_HK_ACTIVE_SNAPSHOT_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _stage8_market_timestamp(value: Any, trade_date: str) -> datetime | None:
    """Parse a Stage 8 timestamp and normalize explicit offsets to Shanghai."""
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


def _stage8_snapshot_temporal_cutoff_safe(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    cutoff_at: str,
) -> bool:
    """Validate exact-day row timestamps against the Stage 8 cutoff."""
    cutoff = _stage8_market_timestamp(cutoff_at, trade_date)
    if cutoff is None or cutoff.strftime("%Y%m%d") != trade_date:
        return False
    for row in rows:
        captured = _stage8_market_timestamp(
            row.get("update_time") or row.get("update_time_us") or row.get("time"),
            trade_date,
        )
        if (
            captured is None
            or captured.strftime("%Y%m%d") != trade_date
            or captured > cutoff
        ):
            return False
    return True


def _canonical_snapshot_codes(codes: Sequence[str]) -> tuple[str, ...]:
    normalized = {
        _canonical_hk_code(code)
        for code in codes
        if _canonical_hk_code(code)
    }
    return tuple(sorted(normalized))


def _snapshot_codes_sha(codes: Sequence[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(_canonical_snapshot_codes(codes)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_rows_sha(rows: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(rows),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_path(snapshot_root: Path | str, trade_date: str, stage_id: str) -> Path:
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        raise ValueError("active snapshot trade_date must be YYYYMMDD")
    if stage_id not in STAGE_BY_ID:
        raise ValueError(f"active snapshot stage_id is unknown: {stage_id}")
    return (
        Path(snapshot_root).expanduser().resolve()
        / _HK_ACTIVE_SNAPSHOT_DIR
        / trade_date
        / stage_id
        / "snapshot.json"
    )


def _snapshot_cutoff_iso(trade_date: str, cutoff_at: str) -> str:
    cutoff = _stage8_market_timestamp(cutoff_at, trade_date)
    if cutoff is None or cutoff.strftime("%Y%m%d") != trade_date:
        raise ValueError("active snapshot cutoff is not exact-date")
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_snapshot_create(path: Path, payload: Mapping[str, Any]) -> bool:
    """Create one snapshot without replacing a successful prior capture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _futu_snapshot_probe(
    shared_root: Path,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    process_runner: BridgeRunner,
    trade_date: str | None,
    cutoff_at: str | None,
) -> tuple[tuple[str, ...], list[dict[str, Any]], dict[str, Mapping[str, Any]], tuple[str, ...], tuple[str, ...]]:
    """Fetch and canonicalize one full Futu snapshot, without applying the lane predicate."""
    requested = _canonical_snapshot_codes(codes)
    evidence_base = (
        "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
        f"active_snapshot_requested_rows={len(requested)}",
    )
    if trade_date is not None and cutoff_at is not None:
        evidence_base += (
            f"active_snapshot_trade_date={trade_date}",
            f"active_snapshot_cutoff={cutoff_at}",
        )
    if not requested:
        return (
            requested,
            [],
            {},
            ("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING",),
            evidence_base,
        )
    try:
        module = _load_shared_module(shared_root, "shared_data.hk_auction_0920")
        fetch = module.fetch_futu_snapshot
        first_parameter = next(iter(inspect.signature(fetch).parameters), "")
        if first_parameter in {"codes", "symbols"}:
            fetched = fetch(list(requested), process_runner=process_runner)
        else:
            fetched = fetch(python_path, list(requested), process_runner=process_runner)
        if not isinstance(fetched, tuple) or len(fetched) != 2:
            raise ValueError("Futu snapshot bridge returned an invalid result")
        raw_rows, errors = fetched
        bridge_errors = tuple(str(item) for item in (errors or ()) if str(item))
        snapshot_rows = [item for item in (raw_rows or ()) if isinstance(item, Mapping)]
    except Exception as error:
        error_type = type(error).__name__
        error_detail = " ".join(str(error).split())[:256]
        typed_error = f"HK_ACTIVE_SNAPSHOT_BRIDGE_ERROR:{error_type}"
        if error_detail:
            typed_error = f"{typed_error}:{error_detail}"
        return (
            requested,
            [],
            {},
            (typed_error,),
            evidence_base
            + (
                f"active_snapshot_bridge_error_type={error_type}",
                f"active_snapshot_bridge_error_detail={error_detail}",
            ),
        )

    raw_codes = [
        _canonical_hk_code(
            raw.get("code") or raw.get("stock_code") or raw.get("symbol")
        )
        for raw in snapshot_rows
    ]
    raw_codes = [code for code in raw_codes if code]
    duplicate_codes = len(raw_codes) != len(set(raw_codes))
    by_code: dict[str, Mapping[str, Any]] = {}
    canonical_rows: list[dict[str, Any]] = []
    for raw in snapshot_rows:
        code = _canonical_hk_code(
            raw.get("code") or raw.get("stock_code") or raw.get("symbol")
        )
        if not code or code in by_code:
            continue
        normalized = {
            "code": code,
            "prev_close_price": _safe_number(raw.get("prev_close_price") or raw.get("prev_close")),
            "last_price": _safe_number(raw.get("last_price") or raw.get("last")),
            "turnover": _safe_number(raw.get("turnover")),
            "volume_ratio": _safe_number(raw.get("volume_ratio")),
            "update_time": str(raw.get("update_time") or raw.get("update_time_us") or ""),
        }
        by_code[code] = normalized
        canonical_rows.append(normalized)
    canonical_rows.sort(key=lambda item: item["code"])
    snapshot_sha = _snapshot_rows_sha(canonical_rows)
    codes_sha = _snapshot_codes_sha(requested)
    evidence = evidence_base + (
        f"active_snapshot_codes_sha256={codes_sha}",
        f"active_snapshot_sha256={snapshot_sha}",
        f"active_snapshot_returned_rows={len(by_code)}",
    )
    errors_out: list[str] = list(bridge_errors)
    if duplicate_codes:
        errors_out.append("HK_ACTIVE_SNAPSHOT_DUPLICATE_CODE")
    if set(by_code) != set(requested) or len(by_code) != len(requested):
        errors_out.append("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING")
    if trade_date is not None and cutoff_at is not None:
        if not _stage8_snapshot_temporal_cutoff_safe(
            canonical_rows,
            trade_date=trade_date,
            cutoff_at=cutoff_at,
        ):
            errors_out.append("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE")
    return requested, canonical_rows, by_code, tuple(dict.fromkeys(errors_out)), evidence


def load_hk_active_snapshot(
    snapshot_root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    codes: Sequence[str],
    cutoff_at: str,
) -> dict[str, Any]:
    """Read and strictly validate one persisted exact-date/exact-stage snapshot."""
    path = _snapshot_path(snapshot_root, trade_date, stage_id)
    requested = _canonical_snapshot_codes(codes)
    evidence_base = (
        f"active_snapshot_path={path}",
        f"active_snapshot_trade_date={trade_date}",
        f"active_snapshot_stage_id={stage_id}",
        f"active_snapshot_codes_sha256={_snapshot_codes_sha(requested)}",
    )
    if not path.is_file():
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_UNAVAILABLE",),
            "source_evidence": evidence_base,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_CORRUPT",),
            "source_evidence": evidence_base,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        errors.append("HK_ACTIVE_SNAPSHOT_CORRUPT")
        payload = {}
    if payload.get("schema_version") != _HK_ACTIVE_SNAPSHOT_SCHEMA:
        errors.append("HK_ACTIVE_SNAPSHOT_SCHEMA_MISMATCH")
    if payload.get("trade_date") != trade_date:
        errors.append("HK_ACTIVE_SNAPSHOT_TRADE_DATE_MISMATCH")
    if payload.get("stage_id") != stage_id:
        errors.append("HK_ACTIVE_SNAPSHOT_STAGE_ID_MISMATCH")
    if payload.get("market") != _HK_ACTIVE_SNAPSHOT_MARKET:
        errors.append("HK_ACTIVE_SNAPSHOT_MARKET_MISMATCH")
    if payload.get("source_role") != _HK_ACTIVE_SNAPSHOT_SOURCE_ROLE:
        errors.append("HK_ACTIVE_SNAPSHOT_SOURCE_ROLE_MISMATCH")
    if any(payload.get(flag) is not False for flag in _HK_ACTIVE_SNAPSHOT_SAFETY):
        errors.append("HK_ACTIVE_SNAPSHOT_SAFETY_FLAG_MISMATCH")
    expected_codes_sha = _snapshot_codes_sha(requested)
    if payload.get("codes_sha256") != expected_codes_sha:
        errors.append("HK_ACTIVE_SNAPSHOT_CODE_SET_SHA_MISMATCH")
    stored_codes = payload.get("codes")
    if stored_codes != list(requested):
        errors.append("HK_ACTIVE_SNAPSHOT_CODE_SET_MISMATCH")
    rows = payload.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        errors.append("HK_ACTIVE_SNAPSHOT_CORRUPT")
        rows = []
    normalized_rows = [dict(row) for row in rows]
    normalized_rows.sort(key=lambda item: str(item.get("code") or ""))
    stored_row_codes = [str(row.get("code") or "") for row in normalized_rows]
    if len(stored_row_codes) != len(set(stored_row_codes)):
        errors.append("HK_ACTIVE_SNAPSHOT_DUPLICATE_CODE")
    if set(stored_row_codes) != set(requested) or len(normalized_rows) != len(requested):
        errors.append("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING")
    requested_rows = payload.get("requested_rows")
    if type(requested_rows) is not int or requested_rows != len(requested):
        errors.append("HK_ACTIVE_SNAPSHOT_REQUESTED_ROWS_MISMATCH")
    returned_rows = payload.get("returned_rows")
    if type(returned_rows) is not int or returned_rows != len(normalized_rows):
        errors.append("HK_ACTIVE_SNAPSHOT_RETURNED_ROWS_MISMATCH")
    if payload.get("full_coverage") is not True:
        errors.append("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING")
    if payload.get("temporal_cutoff_safe") is not True:
        errors.append("HK_ACTIVE_SNAPSHOT_TEMPORAL_FLAG_MISMATCH")
    actual_snapshot_sha = _snapshot_rows_sha(normalized_rows)
    if payload.get("snapshot_sha256") != actual_snapshot_sha:
        errors.append("HK_ACTIVE_SNAPSHOT_SHA_MISMATCH")
    cutoff_iso = _snapshot_cutoff_iso(trade_date, cutoff_at)
    if payload.get("cutoff_at") != cutoff_iso:
        errors.append("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH")
    captured = _stage8_market_timestamp(payload.get("captured_at"), trade_date)
    cutoff = _stage8_market_timestamp(cutoff_iso, trade_date)
    capture_start = _stage8_market_timestamp(
        _HK_ACTIVE_SNAPSHOT_CAPTURE_START_AT,
        trade_date,
    )
    captured_on_trade_date = (
        captured is not None
        and cutoff is not None
        and captured.strftime("%Y%m%d") == trade_date
    )
    if (
        not captured_on_trade_date
        or captured > cutoff
        or not _stage8_snapshot_temporal_cutoff_safe(
            normalized_rows,
            trade_date=trade_date,
            cutoff_at=cutoff_iso,
        )
    ):
        errors.append("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE")
    if (
        not captured_on_trade_date
        or capture_start is None
        or captured < capture_start
        or captured > cutoff
    ):
        errors.append("HK_ACTIVE_SNAPSHOT_CAPTURE_WINDOW_UNSAFE")
    source_evidence = evidence_base + (
        f"active_snapshot_sha256={actual_snapshot_sha}",
        f"active_snapshot_returned_rows={len(normalized_rows)}",
        "active_snapshot_source=PERSISTED_EXACT_STAGE",
    )
    if errors:
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": tuple(dict.fromkeys(errors)),
            "source_evidence": source_evidence,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    return {
        "status": "READY",
        "snapshot_path": str(path),
        "rows": tuple(normalized_rows),
        "by_code": {str(row["code"]): row for row in normalized_rows},
        "active_snapshot_codes_sha256": expected_codes_sha,
        "active_snapshot_sha256": actual_snapshot_sha,
        "source_evidence": source_evidence
        + ("active_snapshot_temporal_cutoff_safe=true",),
        "temporal_cutoff_safe": True,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }


def prepare_hk_active_snapshot(
    snapshot_root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    captured_at: str,
    cutoff_at: str,
    process_runner: BridgeRunner = subprocess.run,
) -> dict[str, Any]:
    """Capture one immutable exact-stage Futu snapshot before the cutoff."""
    path = _snapshot_path(snapshot_root, trade_date, stage_id)
    if path.exists():
        existing = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=codes,
            cutoff_at=cutoff_at,
        )
        if existing["status"] == "READY":
            return {
                **existing,
                "status": "NOOP_ALREADY_VERIFIED",
                "write_performed": False,
            }
        return {**existing, "write_performed": False}
    cutoff_iso = _snapshot_cutoff_iso(trade_date, cutoff_at)
    captured = _stage8_market_timestamp(captured_at, trade_date)
    cutoff = _stage8_market_timestamp(cutoff_iso, trade_date)
    capture_start = _stage8_market_timestamp(
        _HK_ACTIVE_SNAPSHOT_CAPTURE_START_AT,
        trade_date,
    )
    if (
        captured is None
        or cutoff is None
        or capture_start is None
        or captured.strftime("%Y%m%d") != trade_date
        or captured < capture_start
        or captured > cutoff
    ):
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",),
            "write_performed": False,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    requested, rows, _by_code, probe_errors, evidence = _futu_snapshot_probe(
        Path(shared_root).expanduser().resolve(),
        codes=codes,
        python_path=python_path,
        process_runner=process_runner,
        trade_date=trade_date,
        cutoff_at=cutoff_iso,
    )
    if probe_errors:
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": probe_errors,
            "source_evidence": evidence,
            "write_performed": False,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    payload = {
        "schema_version": _HK_ACTIVE_SNAPSHOT_SCHEMA,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": _HK_ACTIVE_SNAPSHOT_MARKET,
        "source_role": _HK_ACTIVE_SNAPSHOT_SOURCE_ROLE,
        "codes": list(requested),
        "codes_sha256": _snapshot_codes_sha(requested),
        "requested_rows": len(requested),
        "returned_rows": len(rows),
        "full_coverage": True,
        "rows": rows,
        "snapshot_sha256": _snapshot_rows_sha(rows),
        "captured_at": captured_at,
        "cutoff_at": cutoff_iso,
        "temporal_cutoff_safe": True,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }
    if not _atomic_snapshot_create(path, payload):
        existing = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=codes,
            cutoff_at=cutoff_at,
        )
        if existing["status"] == "READY":
            return {**existing, "status": "NOOP_ALREADY_VERIFIED", "write_performed": False}
        return {**existing, "write_performed": False}
    return {
        "status": "READY",
        "snapshot_path": str(path),
        "active_snapshot_codes_sha256": payload["codes_sha256"],
        "active_snapshot_sha256": payload["snapshot_sha256"],
        "full_coverage": True,
        "temporal_cutoff_safe": True,
        "source_evidence": evidence
        + (
            f"active_snapshot_path={path}",
            "active_snapshot_full_coverage=true",
            "active_snapshot_temporal_cutoff_safe=true",
        ),
        "write_performed": True,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }
