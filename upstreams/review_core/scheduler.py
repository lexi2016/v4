"""Bounded one-pass scheduler entry for the standalone review_core producer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.10+ ships zoneinfo
    ZoneInfo = None  # type: ignore[assignment]

from .core import EvidenceValidationError, inspect_bundle, normalize_trade_date, run_video
from .producer import AcquisitionTools


DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / ".runtime"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo is not None else None
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def local_trade_date(now: datetime | None = None) -> str:
    """Return the current calendar date in the Asia/Shanghai timezone."""

    current = now or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is not None and SHANGHAI_TZ is not None:
        current = current.astimezone(SHANGHAI_TZ)
    return current.strftime("%Y%m%d")


def resolve_trade_date(trade_date: str | None, *, now: datetime | None = None) -> str:
    """Resolve an optional explicit date without consulting a stale artifact."""

    return normalize_trade_date(trade_date) if trade_date else local_trade_date(now)


def _atomic_receipt(path: Path, payload: Mapping[str, Any]) -> tuple[Path, str]:
    """Write a unique scheduler receipt atomically and return path/SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    temporary_name = ""
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return path, digest


def _write_scheduler_receipt(runtime: Path, target: str, payload: Mapping[str, Any]) -> tuple[Path, str]:
    """Persist one immutable receipt below the target-date scheduler ledger."""

    run_id = str(payload.get("scheduler_run_id") or f"scheduler-{target}-{uuid.uuid4().hex}")
    receipt_path = runtime / "scheduler_receipts" / target / f"{run_id}.json"
    return _atomic_receipt(receipt_path, payload)


def _prior_weekdays(trade_date: str, count: int) -> list[str]:
    current = datetime.strptime(trade_date, "%Y%m%d").date()
    dates: list[str] = []
    while len(dates) < count:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
    return dates


def _is_complete(data_root: Path, trade_date: str) -> bool:
    try:
        manifest = inspect_bundle(trade_date, data_root)
    except (EvidenceValidationError, OSError, ValueError):
        return False
    if manifest.get("trade_date") != trade_date:
        return False
    if any(manifest.get(name) is not False for name in SAFETY_FLAGS):
        return False
    nested_video_flags = manifest.get("safety_flags")
    if nested_video_flags is not None and any(nested_video_flags.get(name) is not False for name in SAFETY_FLAGS):
        return False
    if manifest.get("discovery_status") != "TARGET_BV_LOCKED" or manifest.get("capture_status") in {
        "ACCESS_BLOCKED",
        "CAPTURE_NOT_AVAILABLE",
    }:
        return False
    try:
        from .review import inspect_review_bundle

        review_bundle = inspect_review_bundle(trade_date, data_root)
    except (EvidenceValidationError, OSError, ValueError, TypeError):
        return False
    if not isinstance(review_bundle, Mapping) or review_bundle.get("trade_date") != trade_date:
        return False
    if any(review_bundle.get(name) is not False for name in SAFETY_FLAGS):
        return False
    review_flags = review_bundle.get("safety_flags")
    if not isinstance(review_flags, Mapping) or any(review_flags.get(name) is not False for name in SAFETY_FLAGS):
        return False
    review_status = review_bundle.get("status")
    return isinstance(review_status, str) and review_status not in {"BLOCKED", "NOT_MATERIALIZED", "CANNOT_CONFIRM"}


def _ready_video_manifest(data_root: Path, trade_date: str) -> Mapping[str, Any] | None:
    """Return an already materialized exact-date video, if safe to reuse.

    A review bundle may be missing or partial while the immutable video run is
    already complete.  Re-running acquire in that state needlessly hits the
    public endpoint and can create a false lookup-blocked run.  Require the
    exact-date current pointer to exist so test seams or stale manifests cannot
    suppress the first acquisition.
    """

    current_path = data_root / "review" / trade_date / "current.json"
    if not current_path.is_file():
        return None
    try:
        manifest = inspect_bundle(trade_date, data_root)
    except (EvidenceValidationError, OSError, ValueError, TypeError):
        return None
    if not isinstance(manifest, Mapping):
        return None
    if manifest.get("trade_date") != trade_date or manifest.get("target_trade_date") != trade_date:
        return None
    if manifest.get("discovery_status") != "TARGET_BV_LOCKED":
        return None
    if manifest.get("capture_status") in {"ACCESS_BLOCKED", "CAPTURE_NOT_AVAILABLE"}:
        return None
    asr_status = str(manifest.get("asr_status") or "").upper()
    if asr_status in {"", "NOT_RUN", "FAILED", "ASR_FAILED"}:
        return None
    try:
        if int(manifest.get("asr_segment_count") or 0) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    if any(manifest.get(name) is not False for name in SAFETY_FLAGS):
        return None
    return manifest


def run_local_review(
    trade_date: str,
    *,
    data_root: Path | str | None = None,
    output_root: Path | str | None = None,
    public_source_root: Path | str | None = None,
    selector_path: Path | str | None = None,
    selector_root: Path | str | None = None,
    tdx_root: Path | str | None = None,
    formal_pool_path: Path | str | None = None,
    review_pool_path: Path | str | None = None,
    stage_root: Path | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the exact-date local page/replay pipeline once.

    The import is intentionally lazy so scheduler/video imports stay
    independent from the review bundle implementation and test seams can
    replace this boundary without touching the producer.
    """

    from .review import run_review

    runtime = (Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT).absolute()
    options = dict(kwargs)
    options.setdefault("data_root", runtime)
    options.setdefault("output_root", Path(output_root).absolute() if output_root is not None else runtime)
    options.setdefault("video_data_root", runtime)
    if public_source_root is not None:
        options.setdefault("public_source_root", Path(public_source_root).absolute())
    elif runtime != DEFAULT_DATA_ROOT.absolute():
        # A caller-provided runtime is an isolated test/shadow root unless it
        # explicitly supplies the shared public source.  Do not accidentally
        # scan the machine-wide source while validating a temporary run.
        options.setdefault("public_source_root", runtime)
    for name, value in {
        "selector_path": selector_path,
        "selector_root": selector_root,
        "tdx_root": tdx_root,
        "formal_pool_path": formal_pool_path,
        "review_pool_path": review_pool_path,
        "stage_root": stage_root,
    }.items():
        if value is not None:
            options.setdefault(name, Path(value).absolute())
    return run_review(trade_date, **options)


def run_once(
    trade_date: str | None = None,
    *,
    data_root: Path | str | None = None,
    mode: str = "import-existing",
    allow_network: bool = False,
    tools: AcquisitionTools | None = None,
    source_root: Path | str | None = None,
    lookback_trading_days: int = 5,
    funasr_path: Path | str | None = None,
    ffmpeg_path: Path | str | None = None,
    ytdlp_path: Path | str | None = None,
    python_path: Path | str | None = None,
    public_source_root: Path | str | None = None,
    selector_path: Path | str | None = None,
    selector_root: Path | str | None = None,
    tdx_root: Path | str | None = None,
    formal_pool_path: Path | str | None = None,
    review_pool_path: Path | str | None = None,
    stage_root: Path | str | None = None,
) -> dict[str, Any]:
    """Process exact date plus at most five incomplete prior weekdays.

    This function is deliberately a bounded one-pass entry point.  It does not
    register Windows tasks, start services, or mutate any scheduler state.
    """

    target = resolve_trade_date(trade_date)
    if lookback_trading_days < 0:
        raise ValueError("lookback_trading_days must be non-negative")
    runtime = (Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT).absolute()
    if mode not in {"import-existing", "acquire"}:
        raise ValueError(f"unsupported scheduler mode: {mode}")
    selected = [target]
    current = datetime.strptime(target, "%Y%m%d").date()
    incomplete = 0
    while incomplete < lookback_trading_days:
        current -= timedelta(days=1)
        if current.weekday() >= 5:
            continue
        date8 = current.strftime("%Y%m%d")
        if _is_complete(runtime, date8):
            continue
        selected.append(date8)
        incomplete += 1
    results: list[dict[str, Any]] = []
    for date8 in selected:
        item: dict[str, Any]
        try:
            reusable_video = _ready_video_manifest(runtime, date8)
            if reusable_video is not None:
                result = {
                    "status": reusable_video.get("discovery_status"),
                    "run_id": reusable_video.get("run_id"),
                    "idempotent": True,
                    "acquisition_count": 0,
                    "asr_execution_count": 0,
                    "network_used": False,
                    "discovery_attempt": reusable_video.get("discovery_attempt") or {},
                    "discovery_error": reusable_video.get("discovery_error") or "",
                }
            else:
                result = run_video(
                    date8,
                    data_root=runtime,
                    source_root=source_root,
                    mode=mode,
                    allow_network=allow_network,
                    tools=tools,
                    funasr_path=funasr_path,
                    ffmpeg_path=ffmpeg_path,
                    ytdlp_path=ytdlp_path,
                    python_path=python_path,
                )
            item = {
                "trade_date": date8,
                "status": result.get("status"),
                "run_id": result.get("run_id"),
                "idempotent": result.get("idempotent", False),
                "acquisition_count": result.get("acquisition_count", 0),
                "asr_execution_count": result.get("asr_execution_count", 0),
                "network_used": bool(result.get("network_used", mode == "acquire" and allow_network)),
                "discovery_attempt": result.get("discovery_attempt") or (result.get("manifest") or {}).get("discovery_attempt") or {},
                "discovery_error": result.get("discovery_error") or (result.get("manifest") or {}).get("discovery_error") or "",
            }
        except Exception as exc:
            item = {"trade_date": date8, "status": "BLOCKED", "error": str(exc), "error_type": type(exc).__name__}
        try:
            review_result = run_local_review(
                date8,
                data_root=runtime,
                output_root=runtime,
                video_data_root=runtime,
                public_source_root=public_source_root,
                selector_path=selector_path,
                selector_root=selector_root,
                tdx_root=tdx_root,
                formal_pool_path=formal_pool_path,
                review_pool_path=review_pool_path,
                stage_root=stage_root,
            )
            item["review_status"] = review_result.get("status")
            item["review_run_id"] = review_result.get("run_id")
            item["review_idempotent"] = review_result.get("idempotent", False)
        except Exception as exc:
            item["review_status"] = "BLOCKED"
            item["review_error"] = str(exc)
            item["review_error_type"] = type(exc).__name__
        results.append(item)
    scheduler_run_id = f"scheduler-{target}-{datetime.now(SHANGHAI_TZ).strftime('%Y%m%dT%H%M%S%f') if SHANGHAI_TZ else datetime.now().strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
    network_used = bool(mode == "acquire" and allow_network and any(item.get("network_used") for item in results))
    discovery_attempts = [
        {
            "trade_date": item.get("trade_date"),
            **dict(item.get("discovery_attempt") or {}),
        }
        for item in results
        if item.get("discovery_attempt")
    ]
    status = (
        "SCHEDULED"
        if all(item.get("status") != "BLOCKED" and item.get("review_status") != "BLOCKED" for item in results)
        else "RECONCILE_PARTIAL"
    )
    receipt = {
        "schema_version": "review_core.scheduler_receipt.v1",
        "scheduler_run_id": scheduler_run_id,
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat() if SHANGHAI_TZ else datetime.now().isoformat(),
        "trade_date": target,
        "mode": mode,
        "allow_network": bool(allow_network),
        "selected": selected,
        "selected_dates": selected,
        "results": results,
        "network_used": network_used,
        "discovery_attempts": discovery_attempts,
        "safety_flags": dict(SAFETY_FLAGS),
        **SAFETY_FLAGS,
    }
    receipt_path, receipt_sha256 = _write_scheduler_receipt(runtime, target, receipt)
    return {
        "status": status,
        "trade_date": target,
        "mode": mode,
        "lookback_trading_days": lookback_trading_days,
        "selected_dates": selected,
        "results": results,
        "network_used": network_used,
        "discovery_attempts": discovery_attempts,
        "safety_flags": dict(SAFETY_FLAGS),
        **SAFETY_FLAGS,
        "scheduler_run_id": scheduler_run_id,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review-core-scheduler")
    parser.add_argument("--trade-date")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--mode", choices=("import-existing", "acquire"), default="acquire")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--lookback-trading-days", type=int, default=5)
    parser.add_argument("--funasr-path", type=Path)
    parser.add_argument("--ffmpeg-path", type=Path)
    parser.add_argument("--ytdlp-path", type=Path)
    parser.add_argument("--python-path", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_once(**vars(args)), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (EvidenceValidationError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["local_trade_date", "main", "resolve_trade_date", "run_local_review", "run_once"]
