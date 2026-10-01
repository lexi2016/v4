"""Arbitrary-cwd stage-center tick wrapper with safe check/dry-run modes."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from contracts.trading_calendar import (
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from stage_center.contracts import STAGE_BY_ID
from stage_center.raw_store import RawStore
from stage_center.selection import SelectionStore

SAFETY_FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
REQUIRED_ROOTS = ("candidate_acquisition_root", "raw_root", "selection_root", "receipt_root")
ALL_ROOTS = REQUIRED_ROOTS + (
    "v3_formal_root", "v3_research_root", "hk_d1_root", "hk_second_filter_root", "hk_full_universe_root",
    "a_auction_root", "hk_auction_root", "hk_stage_replay_root", "a_research_panel_receipt_root", "shared_data_root", "python_path",
)
SAFE_EXIT_STATUSES = {
    "CHECK_OK", "DRY_RUN", "READY", "READY_EMPTY", "PARTIAL_WITH_ROWS",
    "NOOP_ALREADY_VERIFIED", "TICK_COMPLETE", "NOT_DUE", "TOO_EARLY",
    "NON_TRADING_DAY", "SKIPPED_NON_TRADING_DAY", "SKIPPED_SLOT_LOCKED",
    "DEADLINE_CHAIN_READY", "DEADLINE_ONLY_NOT_DUE",
    "SKIPPED_RETRY_BACKOFF", "SKIPPED_ALREADY_SETTLED", "SKIPPED_CANDIDATE_CHANGED",
}

MAX_STDOUT_BYTES = 4096
_BULKY_STDOUT_KEYS = frozenset({"rows", "files"})

_DEADLINE_STAGE_BY_CLOCK = {
    (9, 27): "STAGE_0925",
    (9, 37): "STAGE_0930_0935",
    (9, 41): "STAGE_0935_0940",
    (9, 46): "STAGE_0940_0945",
    (10, 31): "STAGE_0945_1030",
    (13, 16): "STAGE_1300_1315",
    (15, 1): "STAGE_1445_1500",
    (15, 56): "STAGE_1545_1555",
}


def _deadline_stage_for(
    hour: int,
    minute: int,
    *,
    deadline_only: bool = True,
) -> str | None:
    """Resolve a deadline only when the caller explicitly opted in."""
    if not deadline_only:
        return None
    return _DEADLINE_STAGE_BY_CLOCK.get((int(hour), int(minute)))


def _deadline_markets(stage_id: str) -> tuple[str, ...]:
    try:
        return tuple(STAGE_BY_ID[stage_id].markets)
    except KeyError as error:
        raise ValueError(f"unknown deadline stage {stage_id!r}") from error


def _deadline_failure(
    *,
    market: str,
    layer: str,
    expected_path: Path,
    observed_status: str,
) -> dict[str, object]:
    return {
        "status": "ALERT",
        "market": market,
        "first_failed_layer": layer,
        "expected_absolute_path": str(expected_path),
        "observed_status": observed_status,
    }


def _check_deadline_lane(
    raw_root: Path,
    selection_root: Path,
    trade_date: str,
    stage_id: str,
    market: str,
) -> dict[str, object]:
    """Verify one raw -> bundle -> selection chain without writing."""
    raw_root = Path(raw_root).expanduser().resolve()
    selection_root = Path(selection_root).expanduser().resolve()
    raw_latest = raw_root / "latest.json"
    if not raw_latest.is_file():
        return _deadline_failure(
            market=market,
            layer="RAW_LATEST",
            expected_path=raw_latest,
            observed_status="ABSENT",
        )
    try:
        latest = json.loads(raw_latest.read_text(encoding="utf-8"))
        entry = latest.get("entries", {}).get(f"{trade_date}/{stage_id}/{market}")
    except (OSError, UnicodeError, ValueError, AttributeError):
        return _deadline_failure(
            market=market,
            layer="RAW_LATEST",
            expected_path=raw_latest,
            observed_status="INVALID",
        )
    if not isinstance(entry, dict):
        return _deadline_failure(
            market=market,
            layer="RAW_LATEST_ENTRY",
            expected_path=raw_latest,
            observed_status="ABSENT",
        )
    run_id = entry.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return _deadline_failure(
            market=market,
            layer="RAW_LATEST_ENTRY",
            expected_path=raw_latest,
            observed_status="INVALID",
        )
    role = RawStore._role(stage_id, market)
    raw_prefix = raw_root / "runs" / trade_date / role / run_id
    for layer, name in (
        ("RAW_ARTIFACT", "artifact.csv"),
        ("RAW_MANIFEST", "manifest.json"),
        ("RAW_RECEIPT", "receipt.json"),
    ):
        path = raw_prefix / name
        if not path.is_file():
            return _deadline_failure(
                market=market,
                layer=layer,
                expected_path=path,
                observed_status="ABSENT",
            )
    try:
        RawStore(raw_root).verify_latest(trade_date, stage_id, market)
    except Exception as error:
        return _deadline_failure(
            market=market,
            layer="RAW_CHAIN_INTEGRITY",
            expected_path=raw_prefix / "manifest.json",
            observed_status=f"INVALID:{type(error).__name__}",
        )

    bundle_latest = raw_root / "bundle_latest.json"
    if not bundle_latest.is_file():
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_LATEST",
            expected_path=bundle_latest,
            observed_status="ABSENT",
        )
    try:
        bundle = json.loads(bundle_latest.read_text(encoding="utf-8"))
        bundle_entry = bundle.get("entries", {}).get(f"{trade_date}/{stage_id}")
    except (OSError, UnicodeError, ValueError, AttributeError):
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_LATEST",
            expected_path=bundle_latest,
            observed_status="INVALID",
        )
    if not isinstance(bundle_entry, dict):
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_LATEST_ENTRY",
            expected_path=bundle_latest,
            observed_status="ABSENT",
        )
    receipt_relative = bundle_entry.get("receipt_relative")
    if not isinstance(receipt_relative, str) or not receipt_relative:
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_RECEIPT",
            expected_path=bundle_latest,
            observed_status="INVALID",
        )
    bundle_receipt = (raw_root / receipt_relative).resolve()
    try:
        bundle_receipt.relative_to(raw_root)
    except ValueError:
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_RECEIPT",
            expected_path=bundle_latest,
            observed_status="PATH_ESCAPE",
        )
    if not bundle_receipt.is_file():
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_RECEIPT",
            expected_path=bundle_receipt,
            observed_status="ABSENT",
        )
    try:
        RawStore(raw_root).read_verified_bundle(trade_date, stage_id)
    except Exception as error:
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_INTEGRITY",
            expected_path=bundle_receipt,
            observed_status=f"INVALID:{type(error).__name__}",
        )

    selection_latest = selection_root / "selection_latest.json"
    if not selection_latest.is_file():
        return _deadline_failure(
            market=market,
            layer="SELECTION_LATEST",
            expected_path=selection_latest,
            observed_status="ABSENT",
        )
    try:
        selection_payload = json.loads(selection_latest.read_text(encoding="utf-8"))
        selection_entry = selection_payload.get("entries", {}).get(
            f"{trade_date}/{stage_id}/{market}"
        )
    except (OSError, UnicodeError, ValueError, AttributeError):
        return _deadline_failure(
            market=market,
            layer="SELECTION_LATEST",
            expected_path=selection_latest,
            observed_status="INVALID",
        )
    if not isinstance(selection_entry, dict):
        return _deadline_failure(
            market=market,
            layer="SELECTION_LATEST_ENTRY",
            expected_path=selection_latest,
            observed_status="ABSENT",
        )
    selection_run_id = selection_entry.get("run_id")
    if not isinstance(selection_run_id, str) or not selection_run_id:
        return _deadline_failure(
            market=market,
            layer="SELECTION_LATEST_ENTRY",
            expected_path=selection_latest,
            observed_status="INVALID",
        )
    selection_role = SelectionStore._role(stage_id, market)
    selection_prefix = (
        selection_root / "selection_runs" / trade_date / selection_role / selection_run_id
    )
    for layer, name in (
        ("SELECTION_ARTIFACT", "artifact.csv"),
        ("SELECTION_MANIFEST", "manifest.json"),
        ("SELECTION_RECEIPT", "receipt.json"),
    ):
        path = selection_prefix / name
        if not path.is_file():
            return _deadline_failure(
                market=market,
                layer=layer,
                expected_path=path,
                observed_status="ABSENT",
            )
    try:
        SelectionStore(selection_root).read_verified(trade_date, stage_id, market)
    except Exception as error:
        return _deadline_failure(
            market=market,
            layer="SELECTION_CHAIN_INTEGRITY",
            expected_path=selection_prefix / "manifest.json",
            observed_status=f"INVALID:{type(error).__name__}",
        )
    return {"status": "READY", "market": market}


def deadline_chain_check(
    raw_root: Path | str,
    selection_root: Path | str,
    trade_date: str,
    stage_id: str,
    *,
    markets: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Check the immutable stage chains at a deadline without side effects."""
    requested_markets = tuple(markets) if markets is not None else _deadline_markets(stage_id)
    unknown = set(requested_markets) - set(STAGE_BY_ID[stage_id].markets)
    if unknown:
        raise ValueError(f"deadline market is not in stage contract: {sorted(unknown)!r}")
    lanes: dict[str, dict[str, object]] = {}
    first_failure: dict[str, object] | None = None
    for market in requested_markets:
        lane = _check_deadline_lane(
            Path(raw_root),
            Path(selection_root),
            trade_date,
            stage_id,
            market,
        )
        lanes[market] = lane
        if lane.get("status") != "READY" and first_failure is None:
            first_failure = lane
    if first_failure is None:
        return {
            "status": "DEADLINE_CHAIN_READY",
            "alert_type": "NONE",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "lanes": lanes,
            "first_failed_layer": None,
            "expected_absolute_path": None,
            "observed_status": "READY",
            **SAFETY_FLAGS,
        }
    return {
        "status": "DEADLINE_CHAIN_ALERT",
        "alert_type": "STAGE_CHAIN_MISSING_LAYER",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "lanes": lanes,
        "first_failed_layer": first_failure.get("first_failed_layer"),
        "failed_market": first_failure.get("market"),
        "expected_absolute_path": first_failure.get("expected_absolute_path"),
        "observed_status": first_failure.get("observed_status"),
        **SAFETY_FLAGS,
    }


def _canonical_second_filter_root(value: str, trade_date: str) -> Path:
    """Resolve one explicit second-filter root without cwd or date inference.

    The reviewed V3 artifact is nested as ``root/<date>/0920_auction_second_filter``.
    Returning that leaf lets both the runner validator and ``collect_hk_auction``
    use their existing ``root/<stem>`` contract while preserving a single root
    identity for the 09:25 HK auction route.
    """
    if not re.fullmatch(r"\d{8}", trade_date):
        raise ValueError("trade_date must be YYYYMMDD")
    root = Path(value).expanduser().resolve()
    if root.is_file():
        return root
    candidates = (
        root / trade_date / "0920_auction_second_filter",
        root / trade_date,
        root / "0920_auction_second_filter",
        root,
    )
    return next((candidate for candidate in candidates if candidate.exists()), root)


def resolve_runtime_roots(payload: dict[str, str], trade_date: str) -> dict[str, str]:
    """Return a date-bound production config with one canonical HK root."""
    result = dict(payload)
    second = _canonical_second_filter_root(result["hk_second_filter_root"], trade_date)
    auction = _canonical_second_filter_root(result["hk_auction_root"], trade_date)
    if second != auction:
        raise ValueError("hk_second_filter_root and hk_auction_root must resolve to the same canonical root")
    result["hk_second_filter_root"] = str(second)
    result["hk_auction_root"] = str(second)
    return result


def _preflight_roots(payload: dict[str, str], trade_date: str) -> dict[str, str]:
    resolved = resolve_runtime_roots(payload, trade_date)
    for key in ALL_ROOTS:
        value = Path(resolved[key]).expanduser()
        if key == "python_path":
            if not value.is_file():
                raise ValueError(f"explicit python executable missing: {value}")
        elif not value.exists():
            raise ValueError(f"explicit root missing: {key}={value}")
    return resolved


def _load(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config must be a JSON object")
    for key in REQUIRED_ROOTS:
        if not isinstance(payload.get(key), str) or not payload[key].strip().startswith("/"):
            raise ValueError(f"explicit absolute root required: {key}")
    for key in ALL_ROOTS:
        if payload.get(key) is None:
            raise ValueError(f"explicit root required: {key}")
        if not str(payload[key]).startswith("/"):
            raise ValueError(f"explicit absolute path required: {key}")
        if "/explicit/release-config/" in str(payload[key]):
            raise ValueError(f"placeholder root is not deployable: {key}")
    return payload


def _safe_payload(status: str, config: Path, *, evaluated_at: str | None = None) -> dict[str, object]:
    return {"schema_version": "stage_center.tick_wrapper.v1", "status": status, "config": str(config.resolve()), "evaluated_at": evaluated_at, **SAFETY_FLAGS}


def _binary_json_descriptor(value: bytes | bytearray | memoryview, type_name: str) -> dict[str, object]:
    raw = bytes(value)
    return {
        "type": type_name,
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _json_safe_projection(value: object) -> object:
    """Project wrapper output to JSON without changing the internal result."""
    if isinstance(value, bytes):
        return _binary_json_descriptor(value, "bytes")
    if isinstance(value, bytearray):
        return _binary_json_descriptor(value, "bytearray")
    if isinstance(value, memoryview):
        return _binary_json_descriptor(value, "memoryview")
    if isinstance(value, dict):
        projected: dict[str, object] = {}
        for key, item in value.items():
            projected[_json_safe_key(key)] = _json_safe_projection(item)
        return projected
    if isinstance(value, (list, tuple)):
        return [_json_safe_projection(item) for item in value]
    return value


def _json_safe_key(key: object) -> str:
    projected = _json_safe_projection(key)
    if isinstance(projected, str):
        return projected
    if projected is None:
        return "null"
    if isinstance(projected, bool):
        return "true" if projected else "false"
    if isinstance(projected, (int, float)):
        return str(projected)
    return json.dumps(
        projected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _compact_stdout_value(value: object, *, key: str | None = None) -> object:
    """Keep tick stdout useful without serializing immutable row payloads."""
    if isinstance(value, bytes):
        return _binary_json_descriptor(value, "bytes")
    if isinstance(value, bytearray):
        return _binary_json_descriptor(value, "bytearray")
    if isinstance(value, memoryview):
        return _binary_json_descriptor(value, "memoryview")
    if key in _BULKY_STDOUT_KEYS and isinstance(value, (list, tuple)):
        return {"count": len(value), "truncated": True}
    if isinstance(value, Mapping):
        compact: dict[str, object] = {}
        for raw_key, item in value.items():
            compact_key = _json_safe_key(raw_key)
            compact[compact_key] = _compact_stdout_value(item, key=compact_key)
        return compact
    if isinstance(value, (list, tuple)):
        if len(value) > 16:
            return {
                "count": len(value),
                "items": [_compact_stdout_value(item) for item in value[:3]],
                "truncated": True,
            }
        return [_compact_stdout_value(item) for item in value]
    if isinstance(value, str) and len(value) > 512:
        return value[:509] + "..."
    return value


def _compact_stdout_payload(value: object) -> dict[str, object] | object:
    """Project one wrapper result to a bounded, JSON-safe summary."""
    compact = _compact_stdout_value(value)
    try:
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        encoded = b""
    if len(encoded) + 1 <= MAX_STDOUT_BYTES:
        return compact
    if isinstance(compact, Mapping):
        summary: dict[str, object] = {
            field: compact[field]
            for field in (
                "schema_version",
                "status",
                "trade_date",
                "stage_id",
                "due_status",
                "dispatch_kind",
                "attempted_at",
                "retry_after",
                *SAFETY_FLAGS,
            )
            if field in compact
        }
        stages = compact.get("stages")
        if isinstance(stages, list):
            summary["stages"] = [
                {
                    field: item[field]
                    for field in ("stage_id", "status", "due_status", "dispatch_kind")
                    if isinstance(item, Mapping) and field in item
                }
                for item in stages
            ]
        summary["output_truncated"] = True
        compact = summary
    return compact


def _print_json(value: object) -> None:
    payload = _compact_stdout_payload(value)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    # The fallback contains only scalar/status fields and is intentionally
    # bounded as a final guard even if a future status field is unexpectedly
    # large.
    if len(encoded) + 1 > MAX_STDOUT_BYTES:
        status = payload.get("status") if isinstance(payload, Mapping) else None
        payload = {
            "schema_version": "stage_center.tick_stdout.v1",
            "status": str(status or "CANNOT_CONFIRM")[:128],
            "output_truncated": True,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    print(encoded.decode("utf-8"))


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _calendar_gate(
    trade_date: str,
    *,
    calendar=None,
) -> dict[str, object]:
    """Decide whether a tick may invoke any exact-date producer.

    This gate intentionally precedes the HK universe preflight.  A weekend or
    holiday must not create a full-universe run merely because a deadline
    wrapper was invoked; the typed result remains safe and auditable.
    """
    calendar = calendar or load_market_calendar()
    states = resolve_market_states(calendar, trade_date)
    serialized = {key: value.value for key, value in states.items()}
    if any(value is TradingDayState.UNKNOWN for value in states.values()):
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "calendar": serialized,
            "error": "CALENDAR_UNKNOWN",
            **SAFETY_FLAGS,
        }
    if all(
        states[key] is TradingDayState.NON_TRADING_DAY
        for key in ("a_share", "hk_connect")
    ):
        return {
            "status": "NON_TRADING_DAY",
            "trade_date": trade_date,
            "calendar": serialized,
            **SAFETY_FLAGS,
        }
    return {
        "status": "ELIGIBLE",
        "trade_date": trade_date,
        "calendar": serialized,
        **SAFETY_FLAGS,
    }


def _as_shanghai(value: datetime) -> datetime:
    """Normalize a parsed timestamp before comparing live and replay time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _historical_request_requires_flag(
    trade_date: str,
    evaluated_at: datetime,
    *,
    now: datetime,
) -> bool:
    """Reject an implicit live tick that would read a historical time slice."""
    current = _as_shanghai(now)
    instant = _as_shanghai(evaluated_at)
    return trade_date != current.strftime("%Y%m%d") or instant < current


def _load_universe_materializer(path: Path) -> Callable[..., dict[str, object]]:
    if not path.is_file():
        raise ValueError(f"exact-date universe materializer missing: {path}")
    spec = importlib.util.spec_from_file_location("stage_center_exact_date_universe_materializer", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"exact-date universe materializer cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    materializer = getattr(module, "materialize_stage_universes", None)
    if not callable(materializer):
        raise ValueError(f"exact-date universe materializer entrypoint missing: {path}")
    return materializer


def _run_universe_preflight(
    payload: dict[str, str],
    trade_date: str,
    *,
    materializer: Callable[..., dict[str, object]] | None = None,
    now: datetime | None = None,
    quote_context_factory: Callable[[], object] | None = None,
) -> dict[str, object]:
    """Materialize exact-date universes before the first stage-center tick.

    The default producer is the local Futu HK Connect plate-membership bridge;
    the optional ``materializer`` seam is retained only for focused tests and
    compatibility with the first-batch contract.  No selector panel or older
    date is inferred.
    """
    result: dict[str, object] = {"trade_date": trade_date, **SAFETY_FLAGS}
    try:
        store_value = payload.get("universe_store_root") or payload.get("hk_full_universe_root")
        if not isinstance(store_value, str) or not store_value.strip().startswith("/"):
            raise ValueError("exact-date HK universe store root missing")
        if materializer is not None:
            # Legacy test seam: callers explicitly provide all three inputs;
            # this path is never selected by the live wrapper.
            v35_value = payload.get("universe_v35_data_root") or payload.get("candidate_acquisition_root")
            panel_value = payload.get("universe_selector_panel")
            if not isinstance(v35_value, str) or not v35_value.strip().startswith("/") or not isinstance(panel_value, str) or not panel_value.strip().startswith("/"):
                raise ValueError("legacy exact-date materializer inputs missing")
            output = materializer(
                Path(store_value).expanduser().resolve(),
                Path(v35_value).expanduser().resolve(),
                Path(panel_value).expanduser().resolve(),
                trade_date,
            )
        else:
            from stage_center.hk_universe_preflight import ensure_hk_connect_universe

            output = ensure_hk_connect_universe(
                Path(store_value).expanduser().resolve(),
                trade_date,
                now=now,
                quote_context_factory=quote_context_factory,
            )
        if not isinstance(output, dict) or output.get("ok") is not True or output.get("status") not in (None, "READY", "NOOP_ALREADY_VERIFIED"):
            detail = output.get("error") if isinstance(output, dict) else "invalid universe preflight result"
            raise ValueError(f"exact-date universe preflight failed: {detail or 'status not READY'}")
        if output.get("trade_date") not in (None, trade_date):
            raise ValueError("exact-date universe materializer trade_date mismatch")
        unsafe = [key for key in SAFETY_FLAGS if output.get(key) is not False]
        if unsafe:
            raise ValueError("exact-date universe preflight safety flags must be false: " + ",".join(unsafe))
        return {**output, "status": output.get("status") or "READY", "trade_date": trade_date, **SAFETY_FLAGS}
    except (OSError, ImportError, RuntimeError, TypeError, ValueError) as error:
        return {**result, "status": "CANNOT_CONFIRM", "error": str(error)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one safe stage-center tick")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stage-id")
    parser.add_argument("--trade-date")
    parser.add_argument("--evaluated-at")
    parser.add_argument(
        "--deadline-only",
        action="store_true",
        help="run the read-only deadline chain only at its exact calendar minute",
    )
    parser.add_argument(
        "--historical-backfill",
        action="store_true",
        help="explicitly authorize exact-date replay/backfill inputs",
    )
    args = parser.parse_args(argv)
    try:
        if args.check or args.dry_run:
            config = _load(args.config)
            result = _safe_payload("CHECK_OK" if args.check else "DRY_RUN", args.config)
        else:
            evaluated = datetime.now(SHANGHAI)
            trade_date = args.trade_date or evaluated.strftime("%Y%m%d")
            instant = _as_shanghai(datetime.fromisoformat(args.evaluated_at)) if args.evaluated_at else evaluated
            deadline_stage = _deadline_stage_for(
                instant.hour,
                instant.minute,
                deadline_only=args.deadline_only,
            )
            if args.deadline_only and deadline_stage is None:
                config = _load(args.config)
                result = {
                    **_safe_payload(
                        "DEADLINE_ONLY_NOT_DUE",
                        args.config,
                        evaluated_at=instant.isoformat(),
                    ),
                    "trade_date": trade_date,
                    "stage_id": None,
                    "provider_invocations": 0,
                    "business_writes": 0,
                    "deadline_only": True,
                }
                _print_json(result)
                return _exit_code(str(result["status"]))
            if not args.historical_backfill and _historical_request_requires_flag(
                trade_date,
                instant,
                now=evaluated,
            ):
                result = {
                    **_safe_payload("CANNOT_CONFIRM", args.config, evaluated_at=instant.isoformat()),
                    "trade_date": trade_date,
                    "error": "HISTORICAL_BACKFILL_FLAG_REQUIRED",
                }
                _print_json(result)
                return _exit_code("CANNOT_CONFIRM")
            config = _load(args.config)
            calendar_gate = _calendar_gate(trade_date)
            if calendar_gate["status"] != "ELIGIBLE":
                result = {
                    **_safe_payload(
                        str(calendar_gate["status"]),
                        args.config,
                        evaluated_at=instant.isoformat(),
                    ),
                    **calendar_gate,
                }
                _print_json(result)
                return _exit_code(str(calendar_gate["status"]))
            config = _preflight_roots(config, trade_date)
            if args.deadline_only and deadline_stage is not None:
                if args.historical_backfill:
                    result = {
                        **_safe_payload(
                            "DEADLINE_ONLY_NOT_DUE",
                            args.config,
                            evaluated_at=instant.isoformat(),
                        ),
                        "trade_date": trade_date,
                        "stage_id": deadline_stage,
                        "provider_invocations": 0,
                        "business_writes": 0,
                        "deadline_only": True,
                    }
                else:
                    deadline = deadline_chain_check(
                        Path(config["raw_root"]),
                        Path(config["selection_root"]),
                        trade_date,
                        deadline_stage,
                        markets=_deadline_markets(deadline_stage),
                    )
                    result = {
                        **_safe_payload(
                            deadline["status"],
                            args.config,
                            evaluated_at=instant.isoformat(),
                        ),
                        "trade_date": trade_date,
                        "stage_id": deadline_stage,
                        "deadline_check": deadline,
                        "status": deadline["status"],
                        "provider_invocations": 0,
                        "business_writes": 0,
                        "deadline_only": True,
                    }
                _print_json(result)
                return _exit_code(str(result["status"]))
            universe_preflight = _run_universe_preflight(config, trade_date)
            from stage_center.runner import StageCenterRunner, build_production_config

            runner_config = build_production_config(**{key: Path(config[key]) for key in ALL_ROOTS if key in config and config[key] is not None})
            result = StageCenterRunner(runner_config).tick(
                trade_date,
                instant,
                stage_id=args.stage_id,
                historical_backfill=args.historical_backfill,
            )
            if isinstance(result, dict):
                # HK full-market preflight is an upstream diagnostic only. A
                # CANNOT_CONFIRM there must remain lane-local in the runner,
                # with the A result still returned to the caller.
                result["universe_preflight"] = universe_preflight
    except Exception as error:  # wrapper's stdout remains typed and fail-closed
        result = {**_safe_payload("CANNOT_CONFIRM", args.config), "error": str(error)}
    _print_json(result)
    return _exit_code(str(result.get("status", "CANNOT_CONFIRM")))


def _exit_code(status: str) -> int:
    return 0 if status in SAFE_EXIT_STATUSES else 3


if __name__ == "__main__":
    raise SystemExit(main())
