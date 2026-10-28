"""Shadow-only 21:15 orchestration for the released review-core pools.

The module deliberately calls the three released producers directly.  It has
no fallback to legacy V3 tasks, no network access, and no BUY/order behavior.
Every orchestration receipt is written once to a deterministic slot and is
never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # package invocation: ``python -m review_core.pool_pipeline``
    from .fupan_pool import publish_fupan_review_pool
    from .hk_review import run_hk_close_review
    from .stage7_pool import publish_stage7_replay_pool
except ImportError:  # focused invocation from review_core/
    from fupan_pool import publish_fupan_review_pool
    from hk_review import run_hk_close_review
    from stage7_pool import publish_stage7_replay_pool


PIPELINE_RECEIPT_SCHEMA = "review_core.pool_pipeline.receipt.v1"
PIPELINE_ROLE = "REVIEW_CORE_POOLS_2115"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parent / ".runtime"
DEFAULT_SHARED_ROOT = Path(r"C:\Users\huang\Desktop\学习\v3_shared_data")
DEFAULT_CALENDAR_PATH = Path(r"C:\Users\huang\Desktop\学习\v3.5\contracts\market_calendar_2026.json")
_REQUIRED_MARKETS = ("a_share", "hk_connect_southbound")


class CalendarError(ValueError):
    """Calendar input is missing, malformed, or cannot prove a date boundary."""


class PipelineConflictError(RuntimeError):
    """A deterministic receipt slot already contains a different result."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"non-canonical pipeline JSON: {error}") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _date8(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise CalendarError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise CalendarError(f"{label} must be a real calendar date") from error
    return value


def _date_value(value: str) -> Date:
    return datetime.strptime(value, "%Y%m%d").date()


def _read_calendar(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise CalendarError(f"CALENDAR_MISSING:{path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CalendarError(f"CALENDAR_INVALID:{type(error).__name__}") from error
    if not isinstance(payload, Mapping):
        raise CalendarError("CALENDAR_INVALID:root_not_object")
    if not isinstance(payload.get("schema_version"), str) or not str(payload.get("schema_version")).strip():
        raise CalendarError("CALENDAR_UNKNOWN:schema_version_missing")
    if isinstance(payload.get("year"), bool) or not isinstance(payload.get("year"), int):
        raise CalendarError("CALENDAR_UNKNOWN:year_missing")
    if not isinstance(payload.get("timezone"), str) or not str(payload.get("timezone")).strip():
        raise CalendarError("CALENDAR_UNKNOWN:timezone_missing")
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        raise CalendarError("CALENDAR_UNKNOWN:markets_missing")
    for market, raw_config in markets.items():
        config = raw_config
        if not isinstance(config, Mapping):
            raise CalendarError(f"CALENDAR_UNKNOWN:{market}_missing")
        periods = config.get("holiday_periods")
        open_dates = config.get("trading_dates", config.get("open_dates"))
        if periods is None and open_dates is None:
            raise CalendarError(f"CALENDAR_UNKNOWN:{market}_dates_missing")
        if periods is not None and not isinstance(periods, list):
            raise CalendarError(f"CALENDAR_INVALID:{market}_holiday_periods")
        if open_dates is not None and not isinstance(open_dates, list):
            raise CalendarError(f"CALENDAR_INVALID:{market}_trading_dates")
        if isinstance(periods, list):
            for index, period in enumerate(periods):
                if not isinstance(period, Mapping):
                    raise CalendarError(f"CALENDAR_INVALID:{market}_holiday_periods[{index}]")
                start = _date8(period.get("start"), f"{market}.holiday_periods[{index}].start")
                end = _date8(period.get("end"), f"{market}.holiday_periods[{index}].end")
                if start > end:
                    raise CalendarError(f"CALENDAR_INVALID:{market}_holiday_periods[{index}].range")
        if isinstance(open_dates, list):
            for index, item in enumerate(open_dates):
                _date8(item, f"{market}.trading_dates[{index}]")
        derives_from = config.get("derives_from", [])
        if derives_from is not None and not isinstance(derives_from, list):
            raise CalendarError(f"CALENDAR_INVALID:{market}_derives_from")
        for dependency in derives_from:
            if not isinstance(dependency, str) or not isinstance(markets.get(dependency), Mapping):
                raise CalendarError(f"CALENDAR_UNKNOWN:{market}_dependency:{dependency}")
    for market in _REQUIRED_MARKETS:
        if not isinstance(markets.get(market), Mapping):
            raise CalendarError(f"CALENDAR_UNKNOWN:{market}_missing")
    return dict(payload), _sha256_bytes(raw)


def _market_open_for(
    calendar: Mapping[str, Any], day: str, market: str, _seen: set[str] | None = None
) -> bool:
    markets = calendar.get("markets")
    if not isinstance(markets, Mapping):
        raise CalendarError("CALENDAR_UNKNOWN:markets_missing")
    config = markets.get(market)
    if not isinstance(config, Mapping):
        raise CalendarError(f"CALENDAR_UNKNOWN:{market}_missing")
    seen = set(_seen or ())
    if market in seen:
        raise CalendarError(f"CALENDAR_INVALID:cyclic_dependency:{market}")
    seen.add(market)
    value = _date_value(day)
    explicit = config.get("trading_dates", config.get("open_dates"))
    if isinstance(explicit, list) and day not in {str(item) for item in explicit}:
        return False
    if value.weekday() >= 5:
        return False
    periods = config.get("holiday_periods")
    if not isinstance(periods, list):
        raise CalendarError(f"CALENDAR_UNKNOWN:{market}_holiday_periods")
    for period in periods:
        if not isinstance(period, Mapping):
            raise CalendarError(f"CALENDAR_INVALID:{market}_holiday_period")
        start = _date_value(_date8(period.get("start"), "holiday.start"))
        end = _date_value(_date8(period.get("end"), "holiday.end"))
        if start <= value <= end:
            return False
    derives_from = config.get("derives_from", [])
    if derives_from is not None:
        if not isinstance(derives_from, list):
            raise CalendarError(f"CALENDAR_INVALID:{market}_derives_from")
        if any(not _market_open_for(calendar, day, str(dependency), seen) for dependency in derives_from):
            return False
    return True


def _market_open(calendar: Mapping[str, Any], day: str, market: str = "a_share") -> bool:
    return _market_open_for(calendar, day, market)


def _adjacent_dates(trade_date: str, calendar: Mapping[str, Any]) -> tuple[str, str]:
    current = _date_value(trade_date)
    previous: str | None = None
    target: str | None = None
    for offset in range(1, 3661):
        candidate = (current - timedelta(days=offset)).strftime("%Y%m%d")
        if _market_open(calendar, candidate, "hk_connect_southbound"):
            previous = candidate
            break
    for offset in range(1, 3661):
        candidate = (current + timedelta(days=offset)).strftime("%Y%m%d")
        if _market_open(calendar, candidate, "a_share"):
            target = candidate
            break
    if previous is None or target is None:
        raise CalendarError("CALENDAR_UNKNOWN:adjacent_trade_date_not_proven")
    return previous, target


def resolve_trade_dates(
    trade_date: str | None,
    *,
    previous_trade_date: str | None = None,
    target_date: str | None = None,
    calendar_path: Path | str | None = None,
) -> tuple[str, str, str, str, str]:
    """Resolve and validate the exact current, previous, and next dates.

    A caller may provide all three dates explicitly.  If any boundary is
    omitted, an explicit calendar JSON is mandatory; no weekday-only holiday
    inference is used.  When a calendar is supplied, even explicit dates are
    checked against it and against their adjacent-day relationship.
    """

    if trade_date is None:
        # The scheduled shadow task runs at 21:15 Shanghai time.  The explicit
        # calendar below remains authoritative and rejects weekends/holidays;
        # this is only a current-date clock, never a holiday guess.
        trade_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    trade = _date8(trade_date, "trade_date")
    previous = _date8(previous_trade_date, "previous_trade_date") if previous_trade_date is not None else None
    target = _date8(target_date, "target_date") if target_date is not None else None
    path = Path(calendar_path) if calendar_path is not None else None
    calendar_sha = ""
    calendar: dict[str, Any] | None = None
    if path is not None:
        calendar, calendar_sha = _read_calendar(path)
        if not _market_open(calendar, trade, "a_share"):
            raise CalendarError(f"CALENDAR_DATE_NOT_OPEN:trade_date:{trade}")
        derived_previous, derived_target = _adjacent_dates(trade, calendar)
        if previous is None:
            previous = derived_previous
        if target is None:
            target = derived_target
        if previous != derived_previous:
            raise CalendarError(f"CALENDAR_DATE_MISMATCH:previous_trade_date:{previous}:{derived_previous}")
        if target != derived_target:
            raise CalendarError(f"CALENDAR_DATE_MISMATCH:target_date:{target}:{derived_target}")
    elif previous is None or target is None:
        raise CalendarError("CALENDAR_REQUIRED:explicit calendar path needed to derive dates")
    assert previous is not None and target is not None
    if not (previous < trade < target):
        raise CalendarError("DATE_ORDER_INVALID:previous < trade < target required")
    if calendar is not None and (
        not _market_open(calendar, previous, "hk_connect_southbound")
        or not _market_open(calendar, target, "a_share")
    ):
        raise CalendarError("CALENDAR_DATE_NOT_OPEN:boundary")
    return trade, previous, target, str(path) if path is not None else "", calendar_sha


def _root(value: Path | str | None, default: Path) -> Path:
    return (Path(value) if value is not None else default).absolute()


def _typed_error(error: BaseException) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error) or type(error).__name__}


def _workload_record(name: str, result: Any) -> dict[str, Any]:
    publication: Any = result
    review: Any = result.get("review") if isinstance(result, Mapping) else None
    if name == "hk_close_review" and isinstance(result, Mapping):
        publication = result.get("publication")
    if not isinstance(publication, Mapping):
        return {"status": "CANNOT_CONFIRM", "error": {"type": "InvalidResult", "message": "workload result is not an object"}}
    status = str(publication.get("status") or (review.get("status") if isinstance(review, Mapping) else "") or "").upper()
    if status not in {"READY", "PARTIAL", "CANNOT_CONFIRM", "READY_EMPTY", "FAILED"}:
        return {"status": "CANNOT_CONFIRM", "error": {"type": "MissingStatus", "message": "workload status missing or unsupported"}}
    record: dict[str, Any] = {
        "status": status,
        "run_id": str(publication.get("run_id") or ""),
        "artifact_sha256": str(publication.get("artifact_sha256") or ""),
        "manifest_sha256": str(publication.get("manifest_sha256") or ""),
        "receipt_sha256": str(publication.get("receipt_sha256") or ""),
    }
    if status == "READY" and any(not record[key] for key in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256")):
        return {"status": "CANNOT_CONFIRM", "error": {"type": "MissingProvenance", "message": "READY workload lacks run/artifact/manifest/receipt provenance"}}
    return record


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    data = _canonical(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PipelineConflictError(f"existing receipt cannot be verified: {path}") from error
    if not isinstance(value, dict):
        raise PipelineConflictError(f"existing receipt is not an object: {path}")
    return value


def _overall_status(workloads: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = [str(item.get("status") or "CANNOT_CONFIRM") for item in workloads.values()]
    if all(status in {"READY", "READY_EMPTY"} for status in statuses):
        return "READY"
    if any(status in {"CANNOT_CONFIRM", "FAILED"} or "error" in item for status, item in ((str(v.get("status") or ""), v) for v in workloads.values())):
        return "CANNOT_CONFIRM"
    return "PARTIAL"


def run_pool_pipeline(
    trade_date: str | None = None,
    *,
    previous_trade_date: str | None = None,
    target_date: str | None = None,
    calendar_path: Path | str | None = None,
    runtime_root: Path | str | None = None,
    shared_root: Path | str | None = None,
    hk_root: Path | str | None = None,
    close_root: Path | str | None = None,
    fupan_store_root: Path | str | None = None,
    stage7_store_root: Path | str | None = None,
    bundle_root: Path | str | None = None,
    shared_store_root: Path | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run exactly one call to each released pool workload and receipt it."""

    trade, previous, target, calendar_text, calendar_sha = resolve_trade_dates(
        trade_date,
        previous_trade_date=previous_trade_date,
        target_date=target_date,
        calendar_path=calendar_path,
    )
    runtime = _root(runtime_root, DEFAULT_RUNTIME_ROOT)
    shared = _root(shared_root, DEFAULT_SHARED_ROOT)
    hk_store = _root(hk_root, runtime)
    close = _root(close_root, shared)
    fupan_store = _root(fupan_store_root, runtime / "fupan_pools")
    stage7_store = _root(stage7_store_root, runtime / "stage7_pools")
    # ReviewBundleV1 is produced below the Review Core runtime root.  The
    # fupan producer appends ``review_bundle/<signal_date>`` itself.
    bundle = _root(bundle_root, runtime)
    shared_store = _root(shared_store_root, shared)
    identity: dict[str, Any] = {
        "trade_date": trade,
        "previous_trade_date": previous,
        "target_date": target,
        "calendar_path": calendar_text,
        "calendar_sha256": calendar_sha,
        "roots": {
            "runtime": str(runtime),
            "shared": str(shared),
            "hk": str(hk_store),
            "close": str(close),
            "fupan": str(fupan_store),
            "stage7": str(stage7_store),
            "bundle": str(bundle),
            "shared_store": str(shared_store),
        },
    }
    input_sha = _sha256_bytes(_canonical(identity))
    run_id = f"{trade}-{PIPELINE_ROLE.lower()}-{input_sha[:16]}"
    workloads: dict[str, dict[str, Any]] = {}

    try:
        workloads["hk_close_review"] = _workload_record(
            "hk_close_review",
            run_hk_close_review(
                hk_store,
                trade,
                shared_root=shared,
                close_root=close,
                expected_signal_date=previous,
            ),
        )
    except Exception as error:  # each released workload remains independently attempted
        workloads["hk_close_review"] = {"status": "CANNOT_CONFIRM", "error": _typed_error(error)}
    try:
        workloads["fupan_pool"] = _workload_record(
            "fupan_pool", publish_fupan_review_pool(fupan_store, trade, target, bundle, shared_store)
        )
    except Exception as error:
        workloads["fupan_pool"] = {"status": "CANNOT_CONFIRM", "error": _typed_error(error)}
    try:
        workloads["stage7_pool"] = _workload_record(
            "stage7_pool", publish_stage7_replay_pool(stage7_store, trade, target, shared_store)
        )
    except Exception as error:
        workloads["stage7_pool"] = {"status": "CANNOT_CONFIRM", "error": _typed_error(error)}

    status = _overall_status(workloads)
    result_identity = {"input": identity, "workloads": workloads, "status": status, **{name: False for name in SAFETY_FLAGS}}
    result_sha = _sha256_bytes(_canonical(result_identity))
    receipt: dict[str, Any] = {
        "schema": PIPELINE_RECEIPT_SCHEMA,
        "schema_version": PIPELINE_RECEIPT_SCHEMA,
        "role": PIPELINE_ROLE,
        "run": run_id,
        "run_id": run_id,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trade_date": trade,
        "previous_trade_date": previous,
        "target_date": target,
        "input": identity,
        "calendar": {"path": calendar_text, "sha256": calendar_sha},
        "status": status,
        "workloads": workloads,
        "result_sha256": result_sha,
        **{name: False for name in SAFETY_FLAGS},
    }
    receipt_path = runtime / "pool_pipeline" / trade / f"{run_id}.json"
    if receipt_path.is_file():
        existing = _read_json(receipt_path)
        if existing.get("schema") != PIPELINE_RECEIPT_SCHEMA or existing.get("run_id") != run_id:
            raise PipelineConflictError(f"receipt identity conflict: {receipt_path}")
        existing_identity = {
            "input": existing.get("input"),
            "workloads": existing.get("workloads"),
            "status": existing.get("status"),
            **{name: existing.get(name) for name in SAFETY_FLAGS},
        }
        if _sha256_bytes(_canonical(existing_identity)) != existing.get("result_sha256"):
            raise PipelineConflictError(f"receipt integrity conflict: {receipt_path}")
        if existing.get("result_sha256") != result_sha:
            raise PipelineConflictError(f"receipt result conflict: {receipt_path}")
        return {**existing, "receipt_path": str(receipt_path), "idempotent": True}
    _write_atomic(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path), "idempotent": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-core-pool-pipeline")
    parser.add_argument("--trade-date")
    parser.add_argument("--previous-trade-date")
    parser.add_argument("--target-date")
    parser.add_argument("--calendar-path", required=False)
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--shared-root", default=str(DEFAULT_SHARED_ROOT))
    parser.add_argument("--hk-root", default=None)
    parser.add_argument("--close-root", default=None)
    parser.add_argument("--fupan-store-root", default=None)
    parser.add_argument("--stage7-store-root", default=None)
    parser.add_argument("--bundle-root", default=None)
    parser.add_argument("--shared-store-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = run_pool_pipeline(
            args.trade_date,
            previous_trade_date=args.previous_trade_date,
            target_date=args.target_date,
            calendar_path=args.calendar_path,
            runtime_root=args.runtime_root,
            shared_root=args.shared_root,
            hk_root=args.hk_root,
            close_root=args.close_root,
            fupan_store_root=args.fupan_store_root,
            stage7_store_root=args.stage7_store_root,
            bundle_root=args.bundle_root,
            shared_store_root=args.shared_store_root,
        )
    except (CalendarError, PipelineConflictError) as error:
        parser.exit(2, f"{type(error).__name__}: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "CalendarError",
    "PIPELINE_RECEIPT_SCHEMA",
    "PIPELINE_ROLE",
    "PipelineConflictError",
    "main",
    "resolve_trade_dates",
    "run_pool_pipeline",
]
