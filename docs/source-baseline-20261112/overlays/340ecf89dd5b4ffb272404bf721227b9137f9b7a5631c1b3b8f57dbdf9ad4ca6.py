"""Stable, exact-date macOS entry point for the Review Core daily chain.

This module is intentionally narrower than :mod:`review_core.scheduler`:
launchd calls it repeatedly, but it may only select the requested/current
date.  All source/tool roots are supplied by the caller, and an already READY
exact-date ReviewBundle is a hard idempotency boundary that does not perform
discovery, download, or ASR again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from . import scheduler
from .core import normalize_trade_date


SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


@dataclass(frozen=True)
class DailyPaths:
    """Explicit roots for one exact-date macOS invocation."""

    data_root: Path
    selector_pointer: Path
    selector_path: Path | None
    public_source_root: Path
    tdx_root: Path
    source_root: Path | None
    receipt_root: Path
    funasr_path: Path | None
    ffmpeg_path: Path | None
    ytdlp_path: Path | None
    python_path: Path | None

    def __post_init__(self) -> None:
        for field in (
            "data_root",
            "selector_pointer",
            "selector_path",
            "public_source_root",
            "tdx_root",
            "receipt_root",
            "funasr_path",
            "ffmpeg_path",
            "ytdlp_path",
            "python_path",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, Path(value).expanduser().absolute())
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).expanduser().absolute())


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> tuple[str, int]:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = hashlib.sha256(encoded).hexdigest()
    return digest, len(encoded)


def _selector_target(pointer: Path) -> Path | None:
    try:
        value = pointer.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return None
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = pointer.parent / candidate
    return candidate.resolve()


def _parquet_has_date(path: Path, target_date: str) -> bool:
    try:
        import pyarrow.parquet as parquet

        table = parquet.read_table(path, columns=["trade_date"])
        values = table.column("trade_date").to_pylist()
    except Exception:
        return False
    normalized = {str(value).replace("-", "")[:8] for value in values}
    return target_date in normalized


def selector_is_ready(pointer: Path, target_date: str, expected_path: Path | None = None) -> bool:
    """Require the explicit selector pointer and parquet to contain target date."""

    target = normalize_trade_date(target_date)
    pointed = _selector_target(Path(pointer))
    if pointed is None or not pointed.is_file():
        return False
    if expected_path is not None and pointed != Path(expected_path).expanduser().absolute():
        return False
    return _parquet_has_date(pointed, target)


def _safe_flags(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name, False) is False for name in SAFETY_FLAGS)


def review_bundle_is_ready(data_root: Path, target_date: str) -> bool:
    """Check the exact current ReviewBundle without touching the network."""

    target = normalize_trade_date(target_date)
    try:
        from .core import inspect_bundle
        from .review import inspect_review_bundle

        video = inspect_bundle(target, Path(data_root))
        review = inspect_review_bundle(target, Path(data_root))
    except Exception:
        return False
    if not isinstance(video, Mapping) or not isinstance(review, Mapping):
        return False
    if video.get("trade_date") != target or review.get("trade_date") != target:
        return False
    if video.get("discovery_status") != "TARGET_BV_LOCKED":
        return False
    if video.get("capture_status") in {"ACCESS_BLOCKED", "CAPTURE_NOT_AVAILABLE"}:
        return False
    asr_status = str(video.get("asr_status") or "").upper()
    if asr_status in {"", "NOT_RUN", "FAILED", "ASR_FAILED"}:
        return False
    try:
        if int(video.get("asr_segment_count") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if review.get("status") != "READY":
        return False
    return _safe_flags(video) and _safe_flags(review)


def _run_id(target_date: str, paths: DailyPaths, selector_path: Path | None = None) -> str:
    identity = {
        "trade_date": target_date,
        "data_root": str(paths.data_root),
        "selector": str(selector_path or paths.selector_path or ""),
        "public_source_root": str(paths.public_source_root),
        "tdx_root": str(paths.tdx_root),
    }
    digest = hashlib.sha256(_canonical(identity)).hexdigest()[:16]
    return f"review-core-daily-{target_date}-{digest}"


def _write_result(
    target_date: str,
    paths: DailyPaths,
    payload: Mapping[str, Any],
    *,
    selector_path: Path | None = None,
) -> dict[str, Any]:
    run_id = _run_id(target_date, paths, selector_path)
    body = {
        "schema_version": "review_core.macos_daily_receipt.v1",
        **dict(payload),
        "run_id": run_id,
        "safety_flags": dict(SAFETY_FLAGS),
        **SAFETY_FLAGS,
    }
    receipt_path = paths.receipt_root / target_date / f"{run_id}.json"
    receipt_sha, receipt_size = _atomic_json(receipt_path, body)
    current_path = paths.receipt_root / target_date / "current.json"
    _atomic_json(current_path, {"trade_date": target_date, "run_id": run_id, "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha, **SAFETY_FLAGS})
    result = dict(body)
    result.update({"receipt_path": str(receipt_path), "receipt_sha256": receipt_sha, "receipt_size": receipt_size, "current_path": str(current_path)})
    return result


def _current_receipt(paths: DailyPaths, target_date: str) -> dict[str, Any]:
    pointer = paths.receipt_root / target_date / "current.json"
    try:
        current = json.loads(pointer.read_text(encoding="utf-8-sig"))
        receipt_path = Path(str(current.get("receipt_path") or ""))
        payload = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("trade_date") == target_date else {}


def run_daily(
    trade_date: str | None = None,
    *,
    paths: DailyPaths,
    allow_network: bool = False,
    tools: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run exactly one date, with zero lookback and machine-verifiable receipt."""

    implicit = trade_date is None
    clock = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        clock = clock.astimezone(ZoneInfo("Asia/Shanghai"))
    target = scheduler.resolve_trade_date(trade_date, now=clock)
    base = {
        "trade_date": target,
        "selected_dates": [target],
        "lookback_trading_days": 0,
        "allow_network": bool(allow_network),
        "network_used": False,
        "acquisition_count": 0,
        "asr_execution_count": 0,
        "selector_path": str(paths.selector_path or ""),
        "selector_pointer": str(paths.selector_pointer),
        "public_source_root": str(paths.public_source_root),
        "tdx_root": str(paths.tdx_root),
        "source_root": str(paths.source_root) if paths.source_root else "",
        "observed_at": clock.isoformat(),
    }
    if implicit and (clock.hour, clock.minute) < (20, 25):
        return _write_result(
            target,
            paths,
            {**base, "status": "WAITING_NOT_BEFORE_2025", "reason": "IMPLICIT_LAUNCHD_NOT_BEFORE_2025_SHANGHAI"},
        )
    if not selector_is_ready(paths.selector_pointer, target):
        return _write_result(target, paths, {**base, "status": "BLOCKED", "reason": "SELECTOR_NOT_READY"})
    selector_path = _selector_target(paths.selector_pointer) or paths.selector_path
    if selector_path is None:
        return _write_result(target, paths, {**base, "status": "BLOCKED", "reason": "SELECTOR_PATH_UNRESOLVED"})
    base["selector_path"] = str(selector_path)
    if review_bundle_is_ready(paths.data_root, target):
        return _write_result(
            target,
            paths,
            {**base, "status": "READY", "idempotent": True, "reason": "EXACT_REVIEW_BUNDLE_ALREADY_READY"},
            selector_path=selector_path,
        )

    previous = _current_receipt(paths, target) if implicit else {}
    if previous.get("network_used") or previous.get("last_network_at"):
        last_raw = str(previous.get("last_network_at") or previous.get("observed_at") or "")
        try:
            last_at = datetime.fromisoformat(last_raw)
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            elapsed = (clock - last_at.astimezone(ZoneInfo("Asia/Shanghai"))).total_seconds()
        except (TypeError, ValueError, OverflowError):
            elapsed = 300.0
        if elapsed < 300.0:
            return _write_result(
                target,
                paths,
                {
                    **base,
                    "status": "RETRY_BACKOFF",
                    "reason": "RECENT_NETWORK_ATTEMPT_BACKOFF_300_SECONDS",
                    "last_network_at": last_raw,
                },
                selector_path=selector_path,
            )

    if not paths.public_source_root.is_dir() or not paths.tdx_root.is_dir():
        missing = [
            label
            for label, path in (("PUBLIC_SOURCE_ROOT", paths.public_source_root), ("TDX_ROOT", paths.tdx_root))
            if not path.is_dir()
        ]
        return _write_result(target, paths, {**base, "status": "BLOCKED", "reason": ",".join(missing)}, selector_path=selector_path)

    try:
        scheduled = scheduler.run_once(
            target,
            data_root=paths.data_root,
            mode="acquire",
            allow_network=allow_network,
            tools=tools,
            source_root=paths.source_root,
            lookback_trading_days=0,
            funasr_path=paths.funasr_path,
            ffmpeg_path=paths.ffmpeg_path,
            ytdlp_path=paths.ytdlp_path,
            python_path=paths.python_path,
            public_source_root=paths.public_source_root,
            selector_path=selector_path,
            tdx_root=paths.tdx_root,
        )
    except Exception as error:
        return _write_result(
            target,
            paths,
            {**base, "status": "BLOCKED", "reason": f"{type(error).__name__}: {error}"},
            selector_path=selector_path,
        )

    item = (scheduled.get("results") or [{}])[0] if isinstance(scheduled, Mapping) else {}
    scheduled_network_used = bool(scheduled.get("network_used"))
    return _write_result(
        target,
        paths,
        {
            **base,
            "status": scheduled.get("status", "PARTIAL"),
            "idempotent": bool(item.get("idempotent")),
            "scheduler_run_id": scheduled.get("scheduler_run_id", ""),
            "scheduler_receipt_path": scheduled.get("receipt_path", ""),
            "network_used": scheduled_network_used,
            "last_network_at": clock.isoformat() if scheduled_network_used else str(previous.get("last_network_at") or ""),
            "acquisition_count": int(item.get("acquisition_count", 0) or 0),
            "asr_execution_count": int(item.get("asr_execution_count", 0) or 0),
            "results": scheduled.get("results", []),
        },
        selector_path=selector_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="trade_date", default=None)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--selector-pointer", required=True, type=Path)
    parser.add_argument("--selector-path", required=False, type=Path)
    parser.add_argument("--public-source-root", required=True, type=Path)
    parser.add_argument("--tdx-root", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--receipt-root", required=True, type=Path)
    parser.add_argument("--funasr-path", type=Path)
    parser.add_argument("--ffmpeg-path", type=Path)
    parser.add_argument("--ytdlp-path", type=Path)
    parser.add_argument("--python-path", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = DailyPaths(
        data_root=args.data_root,
        selector_pointer=args.selector_pointer,
        selector_path=args.selector_path,
        public_source_root=args.public_source_root,
        tdx_root=args.tdx_root,
        source_root=args.source_root,
        receipt_root=args.receipt_root,
        funasr_path=args.funasr_path,
        ffmpeg_path=args.ffmpeg_path,
        ytdlp_path=args.ytdlp_path,
        python_path=args.python_path,
    )
    result = run_daily(args.trade_date, paths=paths, allow_network=args.allow_network)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"READY", "SCHEDULED", "WAITING_NOT_BEFORE_2025", "RETRY_BACKOFF"} else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DailyPaths", "main", "review_bundle_is_ready", "run_daily", "selector_is_ready"]
