"""Capture the existing Vibe radar response into V4's dated evidence binding.

This is a V4-owned consumer/update helper. It calls only the fixed loopback
Vibe refresh endpoint during the 06:55 Asia/Shanghai window, stores immutable
response and receipt bytes, then atomically adds an exact plan-date pointer to
the existing V4 binding. It does not alter or configure the Vibe producer.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot

SHANGHAI = ZoneInfo("Asia/Shanghai")
BINDING_SCHEMA = "v4.manager_existing_vibe_binding.v1"
SNAPSHOT_SCHEMA = "v4.manager_vibe_radar_snapshot_binding.v1"
RECEIPT_SCHEMA = "v4.manager_vibe_radar_refresh_receipt.v1"
ENDPOINT = "http://127.0.0.1:8910/api/radar/refresh"
PRODUCER = "existing Vibe newsradar.fetch_radar"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 42
SAFE_CAPTURE_TIME = (6, 55)
SAFE_CAPTURE_END = (7, 0)
DATE_RE = re.compile(r"^20\d{6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _exact_path(value: Any, code: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(code)
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise ValueError(code)
    return path


def _date(value: Any) -> str:
    if not isinstance(value, str) or DATE_RE.fullmatch(value) is None:
        raise ValueError("VIBE_PLAN_TRADE_DATE_INVALID")
    try:
        if datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") != value:
            raise ValueError
    except ValueError as exc:
        raise ValueError("VIBE_PLAN_TRADE_DATE_INVALID") from exc
    return value


def eligible_hk_plan_trade_date(source_date: str) -> str:
    """Choose today's HK plan date when open, otherwise the next calendar session."""
    from contracts.trading_calendar import (
        TradingDayState,
        load_market_calendar,
        parse_trade_date,
        resolve_market_states,
    )

    date = _date(source_date)
    calendar = load_market_calendar()
    parsed = parse_trade_date(date, year=calendar.year)
    if parsed is None:
        raise ValueError("VIBE_PLAN_TRADE_DATE_OUTSIDE_CALENDAR")
    for offset in range(0, 32):
        candidate = parsed + timedelta(days=offset)
        if candidate.year != calendar.year:
            break
        token = candidate.strftime("%Y%m%d")
        state = resolve_market_states(calendar, token)["hk_securities"]
        if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            return token
    raise ValueError("VIBE_NEXT_HK_PLAN_DATE_UNAVAILABLE")


def _validated_binding(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != BINDING_SCHEMA:
        raise ValueError("VIBE_EXISTING_BINDING_INVALID")
    implementation = value.get("implementation_manifest_sha256")
    if not isinstance(implementation, str) or SHA_RE.fullmatch(implementation) is None:
        raise ValueError("VIBE_IMPLEMENTATION_MANIFEST_SHA_INVALID")
    return value


def _provider_sources(template: Mapping[str, Any]) -> tuple[Path, dict[str, str]]:
    root = _exact_path(template.get("provider_root"), "VIBE_PROVIDER_ROOT_INVALID")
    configured = template.get("provider_source_sha256")
    if not isinstance(configured, Mapping) or not configured:
        raise ValueError("VIBE_PROVIDER_SOURCE_BINDING_MISSING")
    io = SafeRoot(root)
    current: dict[str, str] = {}
    for relative, expected in sorted(configured.items()):
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or ".." in Path(relative).parts or not isinstance(expected, str)
                or SHA_RE.fullmatch(expected) is None):
            raise ValueError("VIBE_PROVIDER_SOURCE_BINDING_INVALID")
        raw = io.read_bytes(relative, max_bytes=2 * 1024 * 1024)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError("VIBE_PROVIDER_SOURCE_DRIFT")
        current[relative] = actual
    return root, current


def _response_identity(raw: bytes) -> tuple[dict[str, Any], int, dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("VIBE_RADAR_RESPONSE_JSON_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("VIBE_RADAR_RESPONSE_SHAPE_INVALID")
    data = payload.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("industries"), list):
        raise ValueError("VIBE_RADAR_RESPONSE_SHAPE_INVALID")
    generated = data.get("generated_at")
    industries = data["industries"]
    if not isinstance(generated, str) or not generated.strip():
        raise ValueError("VIBE_RADAR_GENERATED_AT_INVALID")
    if any(not isinstance(row, Mapping) or not isinstance(row.get("items"), list) for row in industries):
        raise ValueError("VIBE_RADAR_INDUSTRY_SHAPE_INVALID")
    stats = data.get("stats")
    if not isinstance(stats, Mapping) or stats.get("industries") != len(industries):
        raise ValueError("VIBE_RADAR_STATS_INVALID")
    article_count = sum(len(row["items"]) for row in industries)
    return dict(payload), article_count, dict(stats)


def _post_refresh(
    *,
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[bytes, int, str]:
    connection = connection_factory("127.0.0.1", 8910, timeout=timeout)
    try:
        connection.request(
            "POST",
            "/api/radar/refresh",
            body=b"",
            headers={"Accept": "application/json", "Content-Length": "0"},
        )
        response = connection.getresponse()
        if (response.status != 200
                or response.getheader("Content-Type", "").split(";", 1)[0] != "application/json"):
            raise ValueError("VIBE_RADAR_REFRESH_HTTP_FAILED")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if not raw or len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("VIBE_RADAR_RESPONSE_SIZE_INVALID")
        return raw, response.status, response.getheader("Content-Type", "")
    finally:
        connection.close()


def _recent_verified_entry(binding: Mapping[str, Any], plan_date: str, local_now: datetime) -> dict[str, Any] | None:
    try:
        from v4.manager_research.existing_materials import _read_vibe_radar_snapshot

        _, readback = _read_vibe_radar_snapshot(binding, plan_date)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError):
        return None
    if readback.get("status") != "VERIFIED":
        return None
    available = readback.get("available_at")
    try:
        timestamp = datetime.fromisoformat(str(available)).astimezone(SHANGHAI)
    except (TypeError, ValueError):
        return None
    if timestamp.strftime("%Y%m%d") != local_now.strftime("%Y%m%d"):
        return None
    if (timestamp.hour, timestamp.minute) >= SAFE_CAPTURE_END:
        return None
    rows = binding.get("radar_snapshots_by_plan_date")
    if isinstance(rows, Mapping):
        item = rows.get(plan_date)
    else:
        item = binding.get("radar_snapshot")
    return dict(item) if isinstance(item, Mapping) else None


def capture_and_bind(
    plan_trade_date: str,
    binding_path: str | Path,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
) -> dict[str, Any]:
    """Capture exact-date evidence and atomically append it to the existing V4 binding."""
    plan_date = _date(plan_trade_date)
    local_start = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    if (local_start.hour, local_start.minute) != SAFE_CAPTURE_TIME:
        raise ValueError("VIBE_REFRESH_OUTSIDE_SAFE_WINDOW")
    if eligible_hk_plan_trade_date(local_start.strftime("%Y%m%d")) != plan_date:
        raise ValueError("VIBE_PLAN_DATE_NOT_NEXT_ELIGIBLE_HK_SESSION")
    finish_clock = clock or (lambda: datetime.now(SHANGHAI))

    path = _exact_path(str(binding_path), "VIBE_BINDING_PATH_INVALID")
    parent = SafeRoot(path.parent)
    relative_binding = path.name
    lock_name = f".{path.name}.refresh.lock"
    state: Path | None = None
    saved_entry: dict[str, Any] | None = None
    response_sha = ""

    # One updater may run at a time; the API reader does not take this lock and
    # sees either the prior binding or the complete atomically replaced one.
    with parent.kernel_lock(lock_name, timeout=2.0):
        original_raw = parent.read_bytes(relative_binding, max_bytes=1024 * 1024)
        config = _validated_binding(original_raw)
        state = _exact_path(config.get("state_root"), "VIBE_STATE_ROOT_INVALID")
        template = config.get("radar_snapshot")
        if not isinstance(template, Mapping) or template.get("schema_version") != SNAPSHOT_SCHEMA:
            raise ValueError("VIBE_RADAR_PROVIDER_BINDING_TEMPLATE_MISSING")
        prior = _recent_verified_entry(config, plan_date, local_start)
        if prior is not None:
            return {
                "status": "ALREADY_CAPTURED",
                "plan_trade_date": plan_date,
                "snapshot_date": prior.get("snapshot_date"),
                "available_at": prior.get("available_at"),
                "response_sha256": prior.get("response_sha256"),
                "binding_sha256": hashlib.sha256(original_raw).hexdigest(),
                "RESEARCH_ONLY": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        provider_root, provider_shas = _provider_sources(template)
        raw, http_status, content_type = _post_refresh(connection_factory=connection_factory)
        finish = finish_clock().astimezone(SHANGHAI)
        if (finish.strftime("%Y%m%d") != local_start.strftime("%Y%m%d")
                or (finish.hour, finish.minute) >= SAFE_CAPTURE_END):
            raise ValueError("VIBE_REFRESH_COMPLETED_OUTSIDE_SAFE_WINDOW")
        payload, article_count, stats = _response_identity(raw)
        generated_at = str(payload["data"]["generated_at"])
        if generated_at.replace("-", "")[:8] != finish.strftime("%Y%m%d"):
            raise ValueError("VIBE_RADAR_GENERATED_DATE_MISMATCH")
        generated_minute = datetime.strptime(generated_at, "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)
        if generated_minute > finish:
            raise ValueError("VIBE_RADAR_GENERATED_AFTER_CAPTURE")

        response_sha = hashlib.sha256(raw).hexdigest()
        snapshot_date = finish.strftime("%Y%m%d")
        capture_id = uuid4().hex
        evidence_root = state / "radar_snapshots" / snapshot_date / response_sha / capture_id
        try:
            evidence_relative = evidence_root.relative_to(state).as_posix()
        except ValueError as exc:
            raise ValueError("VIBE_RADAR_EVIDENCE_PATH_INVALID") from exc
        if evidence_root.resolve() != evidence_root:
            raise ValueError("VIBE_RADAR_EVIDENCE_ROOT_NOT_EXACT")
        evidence_io = SafeRoot(evidence_root)
        evidence_io.ensure_directory("controller_evidence")
        response_relative = "controller_evidence/radar_refresh.raw.json"
        receipt_relative = "controller_evidence/refresh_attempt.json"
        evidence_io.write_bytes(response_relative, raw, require_absent=True)
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "url": ENDPOINT,
            "method": "POST",
            "producer": PRODUCER,
            "status": "RESPONSE_SAVED",
            "http_status": http_status,
            "content_type": content_type,
            "sha256": response_sha,
            "bytes": len(raw),
            "article_count": article_count,
            "finished_at": finish.isoformat(timespec="microseconds"),
            "generated_at": generated_at,
            "stats": stats,
            "provider_source_sha256": provider_shas,
            "plan_trade_date": plan_date,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
        evidence_io.write_bytes(receipt_relative, receipt_raw, require_absent=True)

        entry = {
            "schema_version": SNAPSHOT_SCHEMA,
            "plan_trade_date": plan_date,
            "snapshot_date": snapshot_date,
            "evidence_root": str(evidence_root),
            "response_path": response_relative,
            "response_bytes": len(raw),
            "response_sha256": response_sha,
            "capture_receipt_path": receipt_relative,
            "capture_receipt_sha256": receipt_sha,
            "available_at": receipt["finished_at"],
            "generated_at": generated_at,
            "raw_article_count": article_count,
            "provider_root": str(provider_root),
            "provider_source_sha256": provider_shas,
            "market_scope": "MULTI_MARKET_NEWS",
        }
        updated = dict(config)
        snapshots = updated.get("radar_snapshots_by_plan_date")
        if snapshots is None:
            snapshots = {}
            legacy = updated.get("radar_snapshot")
            if isinstance(legacy, Mapping):
                legacy_date = legacy.get("plan_trade_date")
                if isinstance(legacy_date, str) and DATE_RE.fullmatch(legacy_date):
                    snapshots[legacy_date] = dict(legacy)
        elif not isinstance(snapshots, Mapping):
            raise ValueError("VIBE_RADAR_SNAPSHOT_DATE_MAP_INVALID")
        snapshots = {str(key): dict(value) for key, value in snapshots.items()
                     if isinstance(value, Mapping)}
        snapshots[plan_date] = entry
        updated["radar_snapshots_by_plan_date"] = snapshots

        # Validate the just-written immutable pair through the same reader used
        # by the workspace before publishing its binding pointer.
        from v4.manager_research.existing_materials import _read_vibe_radar_snapshot

        rows, readback = _read_vibe_radar_snapshot(updated, plan_date)
        if readback.get("status") != "VERIFIED" or len(rows) > article_count:
            raise ValueError("VIBE_RADAR_CAPTURE_READBACK_FAILED")
        new_raw = json.dumps(updated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        parent.write_bytes(relative_binding, new_raw)
        saved_entry = entry

    assert saved_entry is not None and state is not None
    return {
        "status": "CAPTURED_AND_BOUND",
        "plan_trade_date": plan_date,
        "snapshot_date": saved_entry["snapshot_date"],
        "available_at": saved_entry["available_at"],
        "response_sha256": response_sha,
        "binding_sha256": hashlib.sha256(new_raw).hexdigest(),
        "article_count": saved_entry["raw_article_count"],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-trade-date", required=True)
    parser.add_argument("--binding", default=os.environ.get("V4_MANAGER_VIBE_BINDING", ""))
    args = parser.parse_args(argv)
    if not args.binding:
        raise ValueError("VIBE_BINDING_PATH_NOT_CONFIGURED")
    result = capture_and_bind(args.plan_trade_date, args.binding)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception,) as exc:
        print(json.dumps({
            "status": "FAILED",
            "reason": type(exc).__name__,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, sort_keys=True))
        raise SystemExit(2)
