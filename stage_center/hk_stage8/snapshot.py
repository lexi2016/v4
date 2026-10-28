"""Immutable pre-cutoff HK full-scan snapshots for stage-scoped consumers."""
from __future__ import annotations

import hashlib
import base64
from uuid import uuid4
import inspect
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..contracts import HK_SNAPSHOT_SCHEDULE, STAGE_BY_ID
from ..live_collectors import (
    _canonical_hk_code,
    _load_shared_module,
    _safe_number,
    _scoped_process_runner,
)

BridgeRunner = Callable[..., Any]

_HK_ACTIVE_SNAPSHOT_SCHEMA = "stage_center.hk_active_snapshot.v2"
_HK_ACTIVE_SNAPSHOT_DIR = ".hk_active_snapshots_v2"
_HK_ACTIVE_SNAPSHOT_MARKET = "HK_CONNECT"
_HK_ACTIVE_SNAPSHOT_SOURCE_ROLE = "FUTU_HKCONNECT_FULL_SCAN"
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


def _snapshot_temporal_exclusion_reason(
    row: Mapping[str, Any], *, trade_date: str, cutoff_at: str
) -> str | None:
    cutoff = _stage8_market_timestamp(cutoff_at, trade_date)
    captured = _stage8_market_timestamp(
        row.get("update_time") or row.get("update_time_us") or row.get("time"),
        trade_date,
    )
    if captured is None:
        return "timestamp_missing_or_unparseable"
    if captured.strftime("%Y%m%d") != trade_date:
        return "wrong_trade_date"
    if cutoff is None or cutoff.strftime("%Y%m%d") != trade_date or captured > cutoff:
        return "after_cutoff"
    return None


def _snapshot_temporal_partition(
    rows: Sequence[Mapping[str, Any]], *, trade_date: str, cutoff_at: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        reason = _snapshot_temporal_exclusion_reason(
            normalized, trade_date=trade_date, cutoff_at=cutoff_at
        )
        normalized["active_snapshot_eligible"] = reason is None
        if reason is None:
            normalized.pop("active_snapshot_exclusion_reason", None)
            eligible.append(normalized)
        else:
            normalized["active_snapshot_exclusion_reason"] = reason
            excluded.append(normalized)
    return eligible, excluded


def _snapshot_temporal_partition_evidence(
    rows: Sequence[Mapping[str, Any]],
    *,
    requested_rows: int,
    trade_date: str,
    cutoff_at: str,
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    eligible, excluded = _snapshot_temporal_partition(
        rows, trade_date=trade_date, cutoff_at=cutoff_at
    )
    exclusions = [
        {
            "code": str(row.get("code") or ""),
            "reason": str(row.get("active_snapshot_exclusion_reason") or ""),
        }
        for row in excluded
    ]
    evidence = (
        "active_snapshot_policy=PER_STOCK_TEMPORAL_ELIGIBILITY_V1",
        "active_snapshot_temporal_cutoff_scope=eligible_rows_only",
        f"active_snapshot_requested_rows={requested_rows}",
        f"active_snapshot_eligible_rows={len(eligible)}",
        f"active_snapshot_excluded_rows={len(excluded)}",
        "active_snapshot_exclusions_json=" + json.dumps(
            exclusions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    return evidence, exclusions


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


def _snapshot_window(trade_date: str, stage_id: str, cutoff_at: str) -> tuple[datetime, datetime, str]:
    schedule = HK_SNAPSHOT_SCHEDULE.get(stage_id)
    if schedule is None:
        raise ValueError("active snapshot stage is not configured for pre-capture")
    start_at, end_at, expected_cutoff_at = schedule
    if cutoff_at != expected_cutoff_at:
        raise ValueError("active snapshot cutoff does not match the stage schedule")
    start = _stage8_market_timestamp(start_at, trade_date)
    end = _stage8_market_timestamp(end_at, trade_date)
    cutoff_iso = _snapshot_cutoff_iso(trade_date, cutoff_at)
    if start is None or end is None or start > end:
        raise ValueError("active snapshot capture window is invalid")
    return start, end, cutoff_iso


def _snapshot_now(clock: Callable[[], datetime] | None = None) -> datetime:
    current = (clock or (lambda: datetime.now(_SHANGHAI)))()
    if not isinstance(current, datetime):
        raise TypeError("active snapshot clock must return datetime")
    if current.tzinfo is None:
        return current.replace(tzinfo=_SHANGHAI)
    return current.astimezone(_SHANGHAI)


def _snapshot_provider_time_safe(
    current: datetime,
    *,
    trade_date: str,
    capture_start: datetime,
    capture_end: datetime,
    cutoff_at: str,
) -> bool:
    cutoff = _stage8_market_timestamp(cutoff_at, trade_date)
    local = current.astimezone(_SHANGHAI) if current.tzinfo else current.replace(tzinfo=_SHANGHAI)
    start = capture_start.replace(tzinfo=_SHANGHAI)
    end = capture_end.replace(tzinfo=_SHANGHAI)
    return bool(
        cutoff is not None
        and local.strftime("%Y%m%d") == trade_date
        and start <= local < end
        and local.replace(tzinfo=None) < cutoff
    )


def _valid_pool_artifact_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


class _SnapshotCaptureWindowExpired(RuntimeError):
    """Raised when provider invocation or completion crosses its capture window."""


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


def record_hk_capture_event(
    snapshot_root: Path | str, *, trade_date: str, stage_id: str,
    payload: Mapping[str, Any], attempt_id: str | None = None, event: str = "result",
) -> dict[str, Any]:
    """Append diagnostic evidence through the same immutable atomic store.

    These events never authorize an active stock or replace snapshot.json.
    Native transport is recorded before the shared bridge parses its payload.
    """
    identity = attempt_id or uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", identity) or not re.fullmatch(r"[a-z0-9_-]+", event):
        raise ValueError("invalid snapshot capture event identity")
    path = _snapshot_path(snapshot_root, trade_date, stage_id).parent / "attempts" / identity / f"{event}.json"
    data = {
        **payload,
        "schema_version": "stage_center.hk_snapshot_capture_attempt.v1",
        "attempt_id": identity, "event": event,
        "trade_date": trade_date, "stage_id": stage_id,
        "market": _HK_ACTIVE_SNAPSHOT_MARKET,
        "recorded_at": datetime.now(_SHANGHAI).isoformat(),
        "capture_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "authorizes_selection": False, **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }
    if not _atomic_snapshot_create(path, data):
        raise FileExistsError(f"snapshot attempt event already exists: {path}")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "attempt_id": identity, "event": event}


def hk_snapshot_capture_receipt(snapshot_root: Path | str, *, trade_date: str, stage_id: str) -> dict[str, Any]:
    """Bind durable native attempts to any later stage failure receipt."""
    path = _snapshot_path(snapshot_root, trade_date, stage_id)
    result: dict[str, Any] = {"snapshot_path": str(path), "authorizes_selection": False}
    if path.is_file():
        raw = path.read_bytes()
        stored = json.loads(raw)
        result.update(snapshot_file_sha256=hashlib.sha256(raw).hexdigest(),
                      captured_at=stored.get("captured_at"), requested_rows=stored.get("requested_rows"),
                      returned_rows=stored.get("returned_rows"), pool_artifact_sha256=stored.get("pool_artifact_sha256"))
    events = []
    for event_path in sorted(path.parent.glob("attempts/*/result.json")):
        raw = event_path.read_bytes()
        data = json.loads(raw)
        events.append({"path": str(event_path), "sha256": hashlib.sha256(raw).hexdigest(),
                       **{key: data.get(key) for key in ("attempt_id", "status", "captured_at", "provider_started_at",
                           "provider_finished_at", "requested_rows", "returned_rows", "cannot_confirm", "payload_events")}})
    result["attempts"] = events
    result["status"] = "RECORDED" if events or path.is_file() else "UNAVAILABLE"
    return result


def _futu_snapshot_probe(
    shared_root: Path,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    process_runner: BridgeRunner,
    trade_date: str | None,
    stage_id: str | None,
    cutoff_at: str | None,
    pool_artifact_sha256: str,
    clock: Callable[[], datetime] | None = None,
    preserve_payload: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> tuple[
    tuple[str, ...],
    list[dict[str, Any]],
    dict[str, Mapping[str, Any]],
    tuple[str, ...],
    tuple[str, ...],
    str | None,
    str | None,
]:
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
    evidence_base += (f"active_snapshot_pool_artifact_sha256={pool_artifact_sha256}",)
    if not _valid_pool_artifact_sha(pool_artifact_sha256):
        return requested, [], {}, ("HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_INVALID",), evidence_base, None, None
    if trade_date is None or stage_id is None or cutoff_at is None:
        return requested, [], {}, ("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH",), evidence_base, None, None
    try:
        capture_start, capture_end, cutoff_iso = _snapshot_window(trade_date, stage_id, cutoff_at)
    except ValueError:
        return requested, [], {}, ("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH",), evidence_base, None, None
    if not requested:
        return (
            requested,
            [],
            {},
            ("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING",),
            evidence_base,
            None,
            None,
        )
    provider_times: dict[str, str | None] = {
        "boundary_at": None,
        "started_at": None,
        "finished_at": None,
    }
    transport_observations: list[str] = []

    def transport_evidence() -> tuple[str, ...]:
        if stage_id != "STAGE_1545_1555":
            return ()
        return tuple(transport_observations or (
            "active_snapshot_transport_raw_status=NO_RESPONSE",
        ))

    try:
        module = _load_shared_module(shared_root, "shared_data.hk_auction_0920")
        fetch = module.fetch_futu_snapshot

        # The bridge import and callable resolution can consume the remaining
        # window, so recheck after them immediately before invoking the fetch.
        boundary_time = _snapshot_now(clock)
        provider_times["boundary_at"] = boundary_time.isoformat()
        if not _snapshot_provider_time_safe(
            boundary_time,
            trade_date=trade_date,
            capture_start=capture_start,
            capture_end=capture_end,
            cutoff_at=cutoff_iso,
        ):
            raise _SnapshotCaptureWindowExpired("provider invocation is outside the exact capture window")

        def guarded_process_runner(*args: Any, **kwargs: Any) -> Any:
            started = _snapshot_now(clock)
            provider_times["boundary_at"] = started.isoformat()
            if not _snapshot_provider_time_safe(
                started,
                trade_date=trade_date,
                capture_start=capture_start,
                capture_end=capture_end,
                cutoff_at=cutoff_iso,
            ):
                raise _SnapshotCaptureWindowExpired("provider runner start is outside the exact capture window")
            # Only report an actual provider start after the final guard passes
            # and immediately before the external runner is invoked.
            provider_times["started_at"] = started.isoformat()
            try:
                completed = process_runner(*args, **kwargs)
            except Exception as error:
                if preserve_payload is not None:
                    failed: dict[str, Any] = {"error_type": type(error).__name__, "error": str(error),
                        "provider_started_at": provider_times["started_at"],
                        "provider_failed_at": _snapshot_now(clock).isoformat()}
                    for field in ("stdout", "stderr", "output"):
                        value = getattr(error, field, None)
                        if value is not None:
                            raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
                            failed[field + "_base64"] = base64.b64encode(raw).decode("ascii")
                            failed[field + "_sha256"] = hashlib.sha256(raw).hexdigest()
                    preserve_payload("provider-error", failed)
                raise
            # Preserve the original native protocol before parsing, filtering,
            # row validation or the completion-time guard can reject it.
            if preserve_payload is not None:
                native: dict[str, Any] = {"returncode": completed.returncode,
                    "provider_started_at": provider_times["started_at"],
                    "provider_received_at": _snapshot_now(clock).isoformat()}
                for field in ("stdout", "stderr"):
                    value = getattr(completed, field, None)
                    raw = value if isinstance(value, bytes) else (value or "").encode("utf-8")
                    native[field + "_base64"] = base64.b64encode(raw).decode("ascii")
                    native[field + "_sha256"] = hashlib.sha256(raw).hexdigest()
                preserve_payload("transport", native)
            if stage_id == "STAGE_1545_1555":
                # This is the last boundary before shared fetch_futu_snapshot
                # filters non-Mapping rows. Observe its original protocol
                # payload here; filtered fetch rows cannot prove emptiness.
                observation = ("active_snapshot_transport_raw_status=UNKNOWN",)
                try:
                    marker = module.MARKER
                    if not isinstance(marker, str) or not marker:
                        raise ValueError("snapshot transport marker is unavailable")
                    marker_line = next(
                        (line for line in reversed(completed.stdout.splitlines())
                         if line.startswith(marker)), None,
                    )
                    encoded = marker_line[len(marker):].strip() if marker_line else ""
                    original = json.JSONDecoder().raw_decode(encoded)[0]
                    if (completed.returncode == 0 and isinstance(original, Mapping)
                            and isinstance(original.get("rows"), list)):
                        observation = (
                            "active_snapshot_transport_raw_status=VERIFIED",
                            f"active_snapshot_transport_raw_rows={len(original['rows'])}",
                            "active_snapshot_transport_payload_sha256="
                            + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                        )
                except (AttributeError, TypeError, ValueError):
                    pass
                transport_observations.extend(observation)
            finished = _snapshot_now(clock)
            provider_times["finished_at"] = finished.isoformat()
            if not _snapshot_provider_time_safe(
                finished,
                trade_date=trade_date,
                capture_start=capture_start,
                capture_end=capture_end,
                cutoff_at=cutoff_iso,
            ):
                raise _SnapshotCaptureWindowExpired("provider result reached the cutoff or capture-window end")
            return completed

        first_parameter = next(iter(inspect.signature(fetch).parameters), "")
        if preserve_payload is not None:
            bridge_file = getattr(module, "__file__", None)
            preserve_payload("provider", {"bridge_module_sha256": hashlib.sha256(Path(bridge_file).read_bytes()).hexdigest() if bridge_file else None,
                "query_parameters": {"codes": list(requested),
                    "include_order_book": bool("include_order_book" in inspect.signature(fetch).parameters and stage_id != "STAGE_1545_1555"),
                    "bridge_signature": str(inspect.signature(fetch))}})
        if first_parameter in {"codes", "symbols"}:
            fetched = fetch(list(requested), process_runner=guarded_process_runner)
        else:
            options = {"include_order_book": True} if "include_order_book" in inspect.signature(fetch).parameters and stage_id != "STAGE_1545_1555" else {}
            fetched = fetch(python_path, list(requested), process_runner=guarded_process_runner, **options)
        if preserve_payload is not None:
            preserve_payload("bridge", {"bridge_response": fetched,
                "provider_started_at": provider_times["started_at"],
                "provider_finished_at": provider_times["finished_at"]})
        if provider_times["started_at"] is None:
            raise ValueError("Futu snapshot bridge did not invoke the guarded provider runner")
        result_time = _snapshot_now(clock)
        if not _snapshot_provider_time_safe(
            result_time,
            trade_date=trade_date,
            capture_start=capture_start,
            capture_end=capture_end,
            cutoff_at=cutoff_iso,
        ):
            provider_times["finished_at"] = result_time.isoformat()
            raise _SnapshotCaptureWindowExpired("provider result processing reached the cutoff or capture-window end")
        provider_times["finished_at"] = result_time.isoformat()
        if not isinstance(fetched, tuple) or len(fetched) != 2:
            raise ValueError("Futu snapshot bridge returned an invalid result")
        raw_rows, errors = fetched
        if stage_id == "STAGE_1545_1555":
            # Keep the bridge response count before Mapping/code filtering;
            # malformed nonempty data must never become an empty retry case.
            evidence_base += (f"active_snapshot_bridge_returned_rows={len(raw_rows or ())}",)
        bridge_errors = tuple(str(item) for item in (errors or ()) if str(item))
        snapshot_rows = [item for item in (raw_rows or ()) if isinstance(item, Mapping)]
    except _SnapshotCaptureWindowExpired as error:
        time_evidence = tuple(
            f"active_snapshot_provider_{key}={value}"
            for key, value in provider_times.items()
            if value is not None
        )
        return (
            requested,
            [],
            {},
            ("HK_ACTIVE_SNAPSHOT_PROVIDER_WINDOW_EXPIRED",),
            evidence_base + transport_evidence() + time_evidence + (f"active_snapshot_provider_window_error={str(error)}",),
            provider_times["started_at"],
            provider_times["finished_at"],
        )
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
            evidence_base + transport_evidence()
            + (
                f"active_snapshot_bridge_error_type={error_type}",
                f"active_snapshot_bridge_error_detail={error_detail}",
            ),
            provider_times["started_at"],
            provider_times["finished_at"],
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
        for field in ("order_book", "order_book_error", "order_book_requested_at", "order_book_received_at", "native_field_evidence"):
            if field in raw:
                normalized[field] = raw[field]
        by_code[code] = normalized
        canonical_rows.append(normalized)
    canonical_rows.sort(key=lambda item: item["code"])
    eligible_rows, excluded_rows = _snapshot_temporal_partition(
        canonical_rows, trade_date=trade_date, cutoff_at=cutoff_at
    )
    canonical_rows = sorted(
        (*eligible_rows, *excluded_rows), key=lambda item: str(item.get("code") or "")
    )
    by_code = {str(row["code"]): row for row in canonical_rows}
    snapshot_sha = _snapshot_rows_sha(canonical_rows)
    codes_sha = _snapshot_codes_sha(requested)
    temporal_partition_evidence, _exclusions = _snapshot_temporal_partition_evidence(
        canonical_rows,
        requested_rows=len(requested),
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    )
    evidence = evidence_base + transport_evidence() + (
        f"active_snapshot_codes_sha256={codes_sha}",
        f"active_snapshot_sha256={snapshot_sha}",
        f"active_snapshot_returned_rows={len(by_code)}",
        *temporal_partition_evidence,
        *(
            (f"active_snapshot_provider_started_at={provider_times['started_at']}",)
            if provider_times["started_at"] is not None else ()
        ),
        *(
            (f"active_snapshot_provider_finished_at={provider_times['finished_at']}",)
            if provider_times["finished_at"] is not None else ()
        ),
    )
    errors_out: list[str] = list(bridge_errors)
    if duplicate_codes:
        errors_out.append("HK_ACTIVE_SNAPSHOT_DUPLICATE_CODE")
    if set(by_code) != set(requested) or len(by_code) != len(requested):
        errors_out.append("HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING")
    if trade_date is not None and cutoff_at is not None:
        if not eligible_rows:
            errors_out.extend((
                "HK_ACTIVE_SNAPSHOT_NO_ELIGIBLE_ROWS",
                "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
            ))
        elif not _stage8_snapshot_temporal_cutoff_safe(
            eligible_rows,
            trade_date=trade_date,
            cutoff_at=cutoff_at,
        ):
            errors_out.append("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE")
    return (
        requested,
        canonical_rows,
        by_code,
        tuple(dict.fromkeys(errors_out)),
        evidence,
        provider_times["started_at"],
        provider_times["finished_at"],
    )


def load_hk_active_snapshot(
    snapshot_root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    codes: Sequence[str],
    cutoff_at: str,
    pool_artifact_sha256: str | None,
) -> dict[str, Any]:
    """Read and strictly validate one persisted exact-date/exact-stage snapshot."""
    path = _snapshot_path(snapshot_root, trade_date, stage_id)
    requested = _canonical_snapshot_codes(codes)
    evidence_base = (
        f"active_snapshot_path={path}",
        f"active_snapshot_trade_date={trade_date}",
        f"active_snapshot_stage_id={stage_id}",
        f"active_snapshot_codes_sha256={_snapshot_codes_sha(requested)}",
        f"active_snapshot_expected_pool_artifact_sha256={pool_artifact_sha256 or ''}",
    )
    try:
        capture_start, capture_end, cutoff_iso = _snapshot_window(
            trade_date, stage_id, cutoff_at
        )
    except ValueError:
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH",),
            "source_evidence": evidence_base,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
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
    if not _valid_pool_artifact_sha(pool_artifact_sha256):
        errors.append("HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_REQUIRED")
    elif payload.get("pool_artifact_sha256") != pool_artifact_sha256:
        errors.append("HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_MISMATCH")
    elif not _valid_pool_artifact_sha(payload.get("pool_artifact_sha256")):
        errors.append("HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_INVALID")
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
    eligible_rows, excluded_rows = _snapshot_temporal_partition(
        normalized_rows, trade_date=trade_date, cutoff_at=cutoff_iso
    )
    has_partition_markers = any(
        "active_snapshot_eligible" in row or "active_snapshot_exclusion_reason" in row
        for row in normalized_rows
    )
    if has_partition_markers:
        for row, expected in zip(normalized_rows, sorted((*eligible_rows, *excluded_rows), key=lambda item: str(item.get("code") or ""))):
            if (
                type(row.get("active_snapshot_eligible")) is not bool
                or row.get("active_snapshot_eligible") is not expected.get("active_snapshot_eligible")
                or row.get("active_snapshot_exclusion_reason") != expected.get("active_snapshot_exclusion_reason")
            ):
                errors.append("HK_ACTIVE_SNAPSHOT_ELIGIBILITY_PARTITION_MISMATCH")
                break
        if (
            payload.get("eligibility_policy") != "PER_STOCK_TEMPORAL_ELIGIBILITY_V1"
            or payload.get("temporal_cutoff_scope") != "eligible_rows_only"
            or type(payload.get("eligible_rows_count")) is not int
            or payload.get("eligible_rows_count") != len(eligible_rows)
            or type(payload.get("excluded_rows_count")) is not int
            or payload.get("excluded_rows_count") != len(excluded_rows)
        ):
            errors.append("HK_ACTIVE_SNAPSHOT_ELIGIBILITY_PARTITION_MISMATCH")
    elif excluded_rows:
        errors.extend((
            "HK_ACTIVE_SNAPSHOT_ELIGIBILITY_PARTITION_MISSING",
            "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
        ))
    if not eligible_rows:
        errors.extend(("HK_ACTIVE_SNAPSHOT_NO_ELIGIBLE_ROWS", "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"))
    if payload.get("cutoff_at") != cutoff_iso:
        errors.append("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH")
    provider_started = _stage8_market_timestamp(payload.get("provider_started_at"), trade_date)
    provider_finished = _stage8_market_timestamp(payload.get("provider_finished_at"), trade_date)
    captured = _stage8_market_timestamp(payload.get("captured_at"), trade_date)
    cutoff = _stage8_market_timestamp(cutoff_iso, trade_date)
    captured_on_trade_date = (
        captured is not None
        and cutoff is not None
        and captured.strftime("%Y%m%d") == trade_date
    )
    if (
        not captured_on_trade_date
        or provider_started is None
        or provider_finished is None
        or provider_started.strftime("%Y%m%d") != trade_date
        or provider_finished.strftime("%Y%m%d") != trade_date
        or provider_started > provider_finished
        or provider_started < capture_start
        or provider_started >= capture_end
        or provider_finished >= capture_end
        or provider_finished >= cutoff
        or captured != provider_finished
        or captured > cutoff
        or not eligible_rows
        or not _stage8_snapshot_temporal_cutoff_safe(
            eligible_rows,
            trade_date=trade_date,
            cutoff_at=cutoff_iso,
        )
    ):
        errors.append("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE")
    if (
        not captured_on_trade_date
        or capture_start is None
        or captured < capture_start
        or captured > capture_end
    ):
        errors.append("HK_ACTIVE_SNAPSHOT_CAPTURE_WINDOW_UNSAFE")
    partition_evidence, exclusions = _snapshot_temporal_partition_evidence(
        normalized_rows,
        requested_rows=len(requested),
        trade_date=trade_date,
        cutoff_at=cutoff_iso,
    )
    enriched_rows = sorted((*eligible_rows, *excluded_rows), key=lambda item: str(item.get("code") or ""))
    source_evidence = evidence_base + (
        f"active_snapshot_sha256={actual_snapshot_sha}",
        f"active_snapshot_returned_rows={len(normalized_rows)}",
        *partition_evidence,
        f"active_snapshot_capture_window_start={capture_start.replace(tzinfo=_SHANGHAI).isoformat()}",
        f"active_snapshot_capture_window_end={capture_end.replace(tzinfo=_SHANGHAI).isoformat()}",
        "active_snapshot_source=PERSISTED_EXACT_STAGE",
        f"active_snapshot_provider_started_at={payload.get('provider_started_at') or ''}",
        f"active_snapshot_provider_finished_at={payload.get('provider_finished_at') or ''}",
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
        "status": "PARTIAL_WITH_ROWS" if excluded_rows else "READY",
        "snapshot_path": str(path),
        "rows": tuple(enriched_rows),
        "eligible_rows": tuple(eligible_rows),
        "excluded_rows": tuple(excluded_rows),
        "exclusions": exclusions,
        "requested_rows": len(requested),
        "returned_rows": len(enriched_rows),
        "eligible_rows_count": len(eligible_rows),
        "excluded_rows_count": len(excluded_rows),
        "by_code": {str(row["code"]): row for row in enriched_rows},
        "active_snapshot_codes_sha256": expected_codes_sha,
        "active_snapshot_pool_artifact_sha256": pool_artifact_sha256,
        "active_snapshot_sha256": actual_snapshot_sha,
        "source_evidence": source_evidence
        + ("active_snapshot_temporal_cutoff_safe=true",),
        "temporal_cutoff_safe": True,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }


def _stage8_transient_empty_failure(
    rows: Sequence[Mapping[str, Any]], errors: Sequence[str], evidence: Sequence[str]
) -> bool:
    """Retry only an empty transport failure, never a data-contract failure."""
    if rows or not errors:
        return False
    transport_statuses = [item.split("=", 1)[1] for item in evidence
                          if item.startswith("active_snapshot_transport_raw_status=")]
    transport_counts = [item.split("=", 1)[1] for item in evidence
                        if item.startswith("active_snapshot_transport_raw_rows=")]
    if transport_statuses != ["NO_RESPONSE"] and not (
        transport_statuses == ["VERIFIED"] and transport_counts == ["0"]
    ):
        return False
    raw_counts = [item.split("=", 1)[1] for item in evidence
                  if item.startswith("active_snapshot_bridge_returned_rows=")]
    if raw_counts and raw_counts != ["0"]:
        return False
    transport_errors = {"网络中断", "network interrupted", "connection reset by peer"}
    transport_prefixes = tuple(
        f"HK_ACTIVE_SNAPSHOT_BRIDGE_ERROR:{kind}"
        for kind in ("ConnectionError", "ConnectionResetError", "ConnectionAbortedError",
                     "TimeoutError", "TimeoutExpired")
    )
    derived_errors = {
        "HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING",
        "HK_ACTIVE_SNAPSHOT_NO_ELIGIBLE_ROWS",
        "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
    }
    saw_transport = False
    saw_transport_exception = False
    for error in errors:
        if error in transport_prefixes or error.startswith(tuple(
            prefix + ":" for prefix in transport_prefixes
        )):
            saw_transport_exception = True
            saw_transport = True
        elif error in transport_errors:
            saw_transport = True
        elif error not in derived_errors:
            return False
    # A raised transport exception may have no response. A returned response
    # must prove raw protocol emptiness before the shared wrapper's filters;
    # missing/unknown/multiple observations never count as empty.
    if transport_statuses == ["NO_RESPONSE"]:
        return saw_transport_exception and not raw_counts
    return saw_transport and (raw_counts == ["0"] or saw_transport_exception)


def prepare_hk_active_snapshot(
    snapshot_root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    evaluated_at: str,
    cutoff_at: str,
    pool_artifact_sha256: str,
    process_runner: BridgeRunner = subprocess.run,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    capture_source_evidence: Sequence[str] = (),
    capture_only: bool = False,
) -> dict[str, Any]:
    """Capture one immutable exact-stage Futu snapshot before the cutoff."""
    path = _snapshot_path(snapshot_root, trade_date, stage_id)
    if not _valid_pool_artifact_sha(pool_artifact_sha256):
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_INVALID",),
            "source_evidence": (f"active_snapshot_pool_artifact_sha256={pool_artifact_sha256}",),
            "write_performed": False,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    if path.exists():
        existing = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=codes,
            cutoff_at=cutoff_at,
            pool_artifact_sha256=pool_artifact_sha256,
        )
        if existing["status"] == "READY":
            return {
                **existing,
                "status": "NOOP_ALREADY_VERIFIED",
                "write_performed": False,
            }
        if existing["status"] == "PARTIAL_WITH_ROWS":
            return {**existing, "already_verified": True, "write_performed": False}
        return {**existing, "write_performed": False}
    try:
        capture_start, capture_end, cutoff_iso = _snapshot_window(
            trade_date, stage_id, cutoff_at
        )
    except ValueError as error:
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH",),
            "error": str(error),
            "write_performed": False,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    # evaluated_at explains why the scheduler considered this node due; the
    # provider boundary records its own actual start and finish times.
    _ = evaluated_at
    is_stage8 = stage_id == "STAGE_1545_1555"
    capture_attempts: list[dict[str, Any]] = []
    durable_attempts: list[dict[str, Any]] = []
    for attempt in range(1, 4 if is_stage8 else 2):
        identity = uuid4().hex
        query_context = {
            "evaluated_at": evaluated_at, "cutoff_at": cutoff_iso,
            "codes": list(_canonical_snapshot_codes(codes)), "codes_sha256": _snapshot_codes_sha(codes),
            "pool_artifact_sha256": pool_artifact_sha256,
            "requested_rows": len(_canonical_snapshot_codes(codes)),
            "source_role": _HK_ACTIVE_SNAPSHOT_SOURCE_ROLE,
            "source_evidence": list(capture_source_evidence),
            "query": {"method": "fetch_futu_snapshot", "shared_package_root": str(shared_root),
                      "python_path": str(python_path)},
        }
        payload_events = [record_hk_capture_event(snapshot_root, trade_date=trade_date, stage_id=stage_id,
            attempt_id=identity, event="query", payload=query_context)]

        def preserve_payload(event: str, native: Mapping[str, Any]) -> None:
            payload_events.append(record_hk_capture_event(snapshot_root, trade_date=trade_date, stage_id=stage_id,
                attempt_id=identity, event=f"{event}-{uuid4().hex}", payload={**query_context, **native}))

        try:
            probe = _futu_snapshot_probe(
                Path(shared_root).expanduser().resolve(),
                codes=codes,
                python_path=python_path,
                process_runner=process_runner,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
                pool_artifact_sha256=pool_artifact_sha256,
                clock=clock,
                preserve_payload=preserve_payload,
            )
            requested, rows, _by_code, probe_errors, evidence, provider_started_at, provider_finished_at = probe
        except Exception as error:
            # Raw protocol was already saved even if normalization failed.
            requested, rows = _canonical_snapshot_codes(codes), []
            probe_errors = (f"HK_ACTIVE_SNAPSHOT_PARSE_ERROR:{type(error).__name__}:{error}",)
            evidence, provider_started_at, provider_finished_at = (), None, None
        durable_attempts.append(record_hk_capture_event(snapshot_root, trade_date=trade_date, stage_id=stage_id,
            attempt_id=identity, payload={**query_context,
                "status": "CANNOT_CONFIRM" if probe_errors else "CAPTURED_DIAGNOSTIC" if capture_only else "CAPTURED",
                "cannot_confirm": list(probe_errors), "returned_rows": len(rows),
                "provider_started_at": provider_started_at, "provider_finished_at": provider_finished_at,
                "captured_at": provider_finished_at, "payload_events": payload_events,
                "normalized_rows_sha256": _snapshot_rows_sha(rows)}))
        if not is_stage8:
            break
        capture_attempts.append({
            "attempt_number": attempt,
            "cannot_confirm": list(probe_errors),
            "source_evidence": list(evidence),
            "requested_rows": len(requested),
            "returned_rows": len(rows),
            "provider_started_at": provider_started_at,
            "provider_finished_at": provider_finished_at,
        })
        if attempt == 3 or not _stage8_transient_empty_failure(rows, probe_errors, evidence):
            break
        # Use actual wall time, never the scheduler's stale evaluated_at.
        # The probe independently checks again after sleeping/importing and
        # immediately before and after every external process invocation.
        if not _snapshot_provider_time_safe(
            _snapshot_now(clock), trade_date=trade_date,
            capture_start=capture_start, capture_end=capture_end,
            cutoff_at=cutoff_iso,
        ):
            break
        sleeper(1.0)
        if not _snapshot_provider_time_safe(
            _snapshot_now(clock), trade_date=trade_date,
            capture_start=capture_start, capture_end=capture_end,
            cutoff_at=cutoff_iso,
        ):
            break
    attempt_metadata = {"native_capture_attempts": durable_attempts}
    if is_stage8:
        attempt_metadata["capture_attempts"] = capture_attempts
    if is_stage8:
        evidence += ("active_snapshot_capture_attempts_json=" + json.dumps(
            capture_attempts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),)
    eligible_rows, excluded_rows = _snapshot_temporal_partition(
        rows, trade_date=trade_date, cutoff_at=cutoff_iso
    )
    _partition_evidence, exclusions = _snapshot_temporal_partition_evidence(
        rows,
        requested_rows=len(requested),
        trade_date=trade_date,
        cutoff_at=cutoff_iso,
    )
    if probe_errors or capture_only:
        return {
            "status": "CANNOT_CONFIRM",
            "snapshot_path": str(path),
            "cannot_confirm": probe_errors or ("HK_ACTIVE_SNAPSHOT_LOCAL_SELECTION_BINDING_UNAVAILABLE",),
            "strict_active_eligibility": False,
            "source_evidence": evidence,
            "requested_rows": len(requested),
            "returned_rows": len(rows),
            "eligible_rows_count": len(eligible_rows),
            "excluded_rows_count": len(excluded_rows),
            "exclusions": exclusions,
            "provider_started_at": provider_started_at,
            "provider_finished_at": provider_finished_at,
            "write_performed": False,
            **attempt_metadata,
            **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    payload = {
        "schema_version": _HK_ACTIVE_SNAPSHOT_SCHEMA,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": _HK_ACTIVE_SNAPSHOT_MARKET,
        "source_role": _HK_ACTIVE_SNAPSHOT_SOURCE_ROLE,
        "pool_artifact_sha256": pool_artifact_sha256,
        "codes": list(requested),
        "codes_sha256": _snapshot_codes_sha(requested),
        "requested_rows": len(requested),
        "returned_rows": len(rows),
        "full_coverage": True,
        "rows": rows,
        "snapshot_sha256": _snapshot_rows_sha(rows),
        "eligibility_policy": "PER_STOCK_TEMPORAL_ELIGIBILITY_V1",
        "temporal_cutoff_scope": "eligible_rows_only",
        "eligible_rows_count": len(eligible_rows),
        "excluded_rows_count": len(excluded_rows),
        "provider_started_at": provider_started_at,
        "provider_finished_at": provider_finished_at,
        "captured_at": provider_finished_at,
        "cutoff_at": cutoff_iso,
        "temporal_cutoff_safe": True,
        **attempt_metadata,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }
    if is_stage8 and not _snapshot_provider_time_safe(
        _snapshot_now(clock), trade_date=trade_date,
        capture_start=capture_start, capture_end=capture_end,
        cutoff_at=cutoff_iso,
    ):
        return {
            "status": "CANNOT_CONFIRM", "snapshot_path": str(path),
            "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_PROVIDER_WINDOW_EXPIRED",),
            "source_evidence": evidence, "write_performed": False,
            **attempt_metadata, **_HK_ACTIVE_SNAPSHOT_SAFETY,
        }
    if not _atomic_snapshot_create(path, payload):
        existing = load_hk_active_snapshot(
            snapshot_root,
            trade_date=trade_date,
            stage_id=stage_id,
            codes=codes,
            cutoff_at=cutoff_at,
            pool_artifact_sha256=pool_artifact_sha256,
        )
        if existing["status"] == "READY":
            return {**existing, "status": "NOOP_ALREADY_VERIFIED", "write_performed": False}
        if existing["status"] == "PARTIAL_WITH_ROWS":
            return {**existing, "already_verified": True, "write_performed": False}
        return {**existing, "write_performed": False}
    return {
        "status": "PARTIAL_WITH_ROWS" if excluded_rows else "READY",
        "snapshot_path": str(path),
        "active_snapshot_codes_sha256": payload["codes_sha256"],
        "active_snapshot_pool_artifact_sha256": pool_artifact_sha256,
        "active_snapshot_sha256": payload["snapshot_sha256"],
        "requested_rows": len(requested),
        "returned_rows": len(rows),
        "eligible_rows_count": len(eligible_rows),
        "excluded_rows_count": len(excluded_rows),
        "exclusions": exclusions,
        "provider_started_at": provider_started_at,
        "provider_finished_at": provider_finished_at,
        "captured_at": provider_finished_at,
        "full_coverage": True,
        "temporal_cutoff_safe": True,
        "source_evidence": evidence
        + (
            f"active_snapshot_path={path}",
            "active_snapshot_full_coverage=true",
            "active_snapshot_temporal_cutoff_safe=true",
        ),
        "write_performed": True,
        **attempt_metadata,
        **_HK_ACTIVE_SNAPSHOT_SAFETY,
    }
