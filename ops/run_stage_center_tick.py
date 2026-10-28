"""Arbitrary-cwd stage-center tick wrapper with safe check/dry-run modes."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable
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
    "v4_research_data_root", "v4_morning_news_root", "v3_formal_root", "v3_research_root", "hk_d1_root", "hk_second_filter_root", "hk_full_universe_root",
    "a_auction_root", "hk_auction_root", "hk_stage_replay_root", "a_research_panel_receipt_root", "shared_data_root", "python_path",
)
SAFE_EXIT_STATUSES = {
    "CHECK_OK", "DRY_RUN", "READY", "READY_EMPTY", "PARTIAL_WITH_ROWS",
    "NOOP_ALREADY_VERIFIED", "TICK_COMPLETE", "NOT_DUE", "TOO_EARLY",
    "NON_TRADING_DAY", "SKIPPED_NON_TRADING_DAY", "SKIPPED_SLOT_LOCKED",
}


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
    if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", run_id) is None:
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
    expected_entry_identity = {
        "trade_date": trade_date,
        "stage_id": stage_id,
        "owner": "stage_center",
        **SAFETY_FLAGS,
    }
    for key, expected in expected_entry_identity.items():
        if bundle_entry.get(key) != expected:
            return _deadline_failure(
                market=market,
                layer="RAW_BUNDLE_LATEST_ENTRY",
                expected_path=bundle_latest,
                observed_status=f"IDENTITY_MISMATCH:{key}",
            )
    bundle_id = bundle_entry.get("bundle_id")
    if not isinstance(bundle_id, str) or re.fullmatch(
        rf"{re.escape(trade_date)}-{re.escape(stage_id.lower())}-[0-9a-f]{{16}}",
        bundle_id,
    ) is None:
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_LATEST_ENTRY",
            expected_path=bundle_latest,
            observed_status="INVALID_BUNDLE_ID",
        )
    expected_receipt_relative = (
        f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}/receipt.json"
    )
    receipt_relative = bundle_entry.get("receipt_relative")
    if receipt_relative != expected_receipt_relative:
        return _deadline_failure(
            market=market,
            layer="RAW_BUNDLE_RECEIPT",
            expected_path=raw_root / expected_receipt_relative,
            observed_status="NON_CANONICAL_RECEIPT_PATH",
        )
    bundle_receipt = (raw_root / expected_receipt_relative).resolve()
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
        verified_bundle = RawStore(raw_root).read_verified_bundle(trade_date, stage_id)
        receipt = verified_bundle.get("receipt")
        if not isinstance(receipt, dict):
            raise ValueError("bundle receipt is not an object")
        for key, expected in {
            "trade_date": trade_date,
            "stage_id": stage_id,
            "bundle_id": bundle_id,
            "owner": "stage_center",
            **SAFETY_FLAGS,
        }.items():
            if receipt.get(key) != expected:
                raise ValueError(f"bundle receipt identity mismatch: {key}")
        if receipt.get("receipt_relative") != expected_receipt_relative:
            raise ValueError("bundle receipt path mismatch")
        if bundle_entry.get("status") != receipt.get("status"):
            raise ValueError("bundle latest status mismatch")
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
    if not isinstance(selection_run_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", selection_run_id) is None:
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
    datetime.strptime(trade_date, "%Y%m%d")
    if re.fullmatch(r"\d{8}", trade_date) is None:
        raise ValueError("deadline trade_date invalid")
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
    for key in ("shared_data_root", "python_path"):
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
        if key in {"v4_morning_news_root", "v3_formal_root", "v3_research_root", "hk_full_universe_root", "a_research_panel_receipt_root"} and payload.get(key) is None:
            continue
        if payload.get(key) is None:
            raise ValueError(f"explicit root required: {key}")
        if not str(payload[key]).startswith("/"):
            raise ValueError(f"explicit absolute path required: {key}")
        if "/explicit/release-config/" in str(payload[key]):
            raise ValueError(f"placeholder root is not deployable: {key}")
    return payload


def _safe_payload(status: str, config: Path, *, evaluated_at: str | None = None) -> dict[str, object]:
    return {"schema_version": "stage_center.tick_wrapper.v1", "status": status, "config": str(config.resolve()), "evaluated_at": evaluated_at, **SAFETY_FLAGS}


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
        for key in ("a_share", "hk_securities")
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
                print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_default))
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
                print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_default))
                return _exit_code(str(calendar_gate["status"]))
            config = _preflight_roots(config, trade_date)
            # Fixed A current and exact HK D-1 authorities are checked per
            # lane by the runner. Never run the legacy full-market producer.
            from stage_center.runner import StageCenterRunner, build_production_config

            runner_config = build_production_config(**{key: Path(config[key]) for key in ALL_ROOTS if key in config and config[key] is not None})
            result = StageCenterRunner(runner_config).tick(
                trade_date,
                instant,
                stage_id=args.stage_id,
                historical_backfill=args.historical_backfill,
            )
    except Exception as error:  # wrapper's stdout remains typed and fail-closed
        result = {**_safe_payload("CANNOT_CONFIRM", args.config), "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_default))
    return _exit_code(str(result.get("status", "CANNOT_CONFIRM")))


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON type: {type(value).__name__}")


def _exit_code(status: str) -> int:
    return 0 if status in SAFE_EXIT_STATUSES else 3


if __name__ == "__main__":
    raise SystemExit(main())
