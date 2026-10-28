"""One-shot, observation-only V4 runtime graph collector."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from infrastructure.runtime_graph.contracts import GraphStatus
from infrastructure.runtime_graph.http_client import make_http_get, validate_api_base
from infrastructure.runtime_graph.service import RuntimeGraphService


SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_API_BASE = "http://127.0.0.1:8873"
RESULT_SCHEMA = "v3_runtime_graph_collector_result.v1"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("DATE_INVALID") from error
    return value


def normalize_now(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(SHANGHAI)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("NOW_INVALID") from error
    else:
        raise ValueError("NOW_INVALID")
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def collect_once(
    *,
    business_date: str,
    data_root: Path,
    now: datetime | str | None = None,
    api_base: str = DEFAULT_API_BASE,
    http_get: Callable[[str], Mapping[str, Any]] | None = None,
    read_text: Callable[[Path], str] | None = None,
    path_exists: Callable[[Path], bool] | None = None,
    path_lstat: Callable[[Path], os.stat_result | None] | None = None,
) -> dict[str, Any]:
    date = _validate_date(business_date)
    base = validate_api_base(api_base)
    normalized_now = normalize_now(now)
    service = RuntimeGraphService(Path(data_root), now_provider=lambda: normalized_now)
    build = service.collect(
        date,
        now=normalized_now,
        api_base=base,
        http_get=http_get or make_http_get(base),
        read_text=read_text,
        path_exists=path_exists,
        path_lstat=path_lstat,
    )
    snapshot = build.state.payload
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "business_date": date,
        "status": snapshot["status"],
        "topology_version_sha": snapshot["topology_version_sha"],
        "snapshot_published": build.snapshot_published,
        "events_recorded": build.events_recorded,
        "event_count": build.event_count,
        "generated_at": snapshot["generated_at"],
        **SAFETY_FLAGS,
    }
    if not build.events_recorded:
        result.update(status=GraphStatus.FAIL.value, reason="EVENT_RECORDING_FAILED")
    return result


def _exit_code(result: Mapping[str, Any]) -> int:
    if not result.get("snapshot_published") or not result.get("events_recorded") or result.get("status") == GraphStatus.FAIL.value:
        return 1
    return 2 if result.get("status") == GraphStatus.EVIDENCE_GAP.value else 0


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect one V4 runtime graph snapshot")
    parser.add_argument("--date")
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--now")
    try:
        args = parser.parse_args(argv)
        if args.events:
            from infrastructure.runtime_graph.current import load_config
            from infrastructure.runtime_graph.event_collector import collect_events
            result = collect_events(load_config(args.config), make_http_get(args.api_base), initialize=args.initialize, business_date=args.date)
            _emit(result)
            return 1 if result["status"] == "FAILED" else 0
        if not args.date:
            raise ValueError("DATE_REQUIRED_FOR_LEGACY_COLLECT")
        result = collect_once(
            business_date=args.date,
            data_root=args.data_root,
            now=args.now,
            api_base=args.api_base,
        )
        _emit(result)
        return _exit_code(result)
    except Exception as error:
        _emit({
            "schema_version": RESULT_SCHEMA,
            "business_date": getattr(locals().get("args"), "date", None),
            "status": GraphStatus.FAIL.value,
            "snapshot_published": False,
            "events_recorded": False,
            "reason": f"{type(error).__name__}:{error}",
            **SAFETY_FLAGS,
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
