"""Trading-day-gated scheduled owner for shared A/H stage bundles.

The Windows tasks pass only a frozen stage id.  The trade date is resolved
from the local market clock and every outcome, including NOT_DUE and FAILED,
is written as an atomic scheduler receipt.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.market_calendar import evaluate_a_share_trade_date
from shared_data.store import StoreError
from scripts.acquire_stage_bundle import run_stage_bundle
from scripts.acquire_hk_security_master import ensure_hk_security_master
from scripts.acquire_stage_raw import resolve_futu_python
from scripts.materialize_stage_universes import materialize_stage_universes
from scripts.live_acquisition.contracts import STAGE_WINDOWS

SCHEDULED_STAGE_SPECS = (
    ("V3Shared_Acquire_STAGE_0930_0935", "STAGE_0930_0935", "09:35"),
    ("V3Shared_Acquire_STAGE_0935_0940", "STAGE_0935_0940", "09:40"),
    ("V3Shared_Acquire_STAGE_0940_0945", "STAGE_0940_0945", "09:45"),
    ("V3Shared_Acquire_STAGE_0945_1030", "STAGE_0945_1030", "10:30"),
    ("V3Shared_Acquire_STAGE_1300_1315", "STAGE_1300_1315", "13:15"),
    ("V3Shared_Acquire_STAGE_1445_1500", "STAGE_1445_1500", "15:00"),
    ("V3Shared_Acquire_STAGE_1545_1555", "STAGE_1545_1555", "15:55"),
)

_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

_DEFAULT_RETRY_ATTEMPTS = 2
_DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
_MANAGER_CLOSE_CAPTURE_MODE_ENV = "V4_MANAGER_CLOSE_CAPTURE_MODE"
_MANAGER_PYTDX_LATE_OBSERVATION_MODE = "PYTDX_LATE_OBSERVATION"
_V35_DATA_ROOT_ENV = "V35_DATA_ROOT"
_SELECTOR_PANEL_ENV = "V3_SHARED_SELECTOR_READY_PANEL"
_SELECTOR_POINTER_ENV = "V3_SHARED_SELECTOR_READY_PANEL_POINTER"
_SELECTOR_POINTER_RELATIVE = (
    Path("数据") / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
)

# Only transport failures may be retried.  These markers are deliberately
# specific to the fixed Futu/OpenD and PyTDX bridges; coverage, cutoff,
# schema, date, and validation errors must remain fail-closed on the first
# attempt.  Do not add a generic "failed"/"error" marker here.
_TRANSIENT_TRANSPORT_MARKERS = (
    "opend unavailable",
    "opend timed out",
    "opend connection",
    "connection error",
    "connectionerror",
    "connection reset",
    "connection refused",
    "connection aborted",
    "broken pipe",
    "no tdxpy exhq host available",
)


def _has_transport_marker(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in _TRANSIENT_TRANSPORT_MARKERS):
        return True
    # The bridge wrappers turn subprocess.TimeoutExpired and equivalent
    # socket errors into text.  Require the source prefix as well as the
    # transport word so a semantic "coverage timeout" never retries.
    source = "futu bridge" in text or "futu security-master" in text or "pytdx" in text or "tdxpy" in text
    transport = any(marker in text for marker in ("timed out", "timeout", "connection"))
    return source and transport


def _is_retryable_transport_exception(error: BaseException) -> bool:
    """Return True only for typed transport failures or fixed markers.

    ``FileNotFoundError``/``PermissionError`` are OSError subclasses but are
    configuration/filesystem failures, not transient network failures, so
    only an exact plain OSError is accepted by the typed branch.  Bridge
    wrappers that convert a subprocess timeout into text are covered by the
    explicit markers above.
    """
    if isinstance(error, ValueError):
        return False
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    if type(error) is OSError:
        return True
    return _has_transport_marker(error)


def _result_has_transport_failure(result: object) -> bool:
    """Inspect only persisted ``error`` fields for a known transport marker."""
    if not isinstance(result, dict):
        return False
    errors: list[str] = []

    def visit(value: object) -> None:
        if not isinstance(value, dict):
            return
        if "error" in value:
            errors.append(str(value.get("error") or ""))
        # ``run_stage_bundle`` nests per-market evidence here.  The security
        # master runner returns a flat error field and needs no other walk.
        markets = value.get("markets")
        if isinstance(markets, dict):
            for market in markets.values():
                visit(market)

    visit(result)
    return any(_has_transport_marker(error) for error in errors)


def _validate_retry_controls(max_attempts: int, retry_backoff_seconds: float) -> None:
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if (
        isinstance(retry_backoff_seconds, bool)
        or not isinstance(retry_backoff_seconds, (int, float))
        or not math.isfinite(float(retry_backoff_seconds))
        or retry_backoff_seconds < 0
    ):
        raise ValueError("retry_backoff_seconds must be a finite non-negative number")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def seconds_until_cutoff(now: datetime, stage_id: str) -> float:
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    cutoff_text = STAGE_WINDOWS[stage_id][2]
    cutoff_time = datetime.strptime(cutoff_text, "%H:%M:%S").time()
    cutoff = datetime.combine(now.date(), cutoff_time, tzinfo=now.tzinfo)
    return max(0.0, (cutoff - now).total_seconds())


def _trusted_universe_inputs() -> tuple[Path, Path, Path]:
    """Resolve the sibling V3.5 data root and selector-ready pointer safely."""
    workspace_root = _PROJECT_ROOT.parent
    default_v35_root = (workspace_root / "v3.5" / ".runtime" / "data").resolve()
    default_pointer = (workspace_root / _SELECTOR_POINTER_RELATIVE).resolve()
    selector_root = (workspace_root / "数据" / "selector_ready_panels").resolve()
    raw_v35_root = str(os.environ.get(_V35_DATA_ROOT_ENV) or "").strip()
    raw_pointer = str(os.environ.get(_SELECTOR_POINTER_ENV) or "").strip()
    raw_panel = str(os.environ.get(_SELECTOR_PANEL_ENV) or "").strip()
    v35_root = (Path(raw_v35_root) if raw_v35_root else default_v35_root).resolve()
    pointer = (Path(raw_pointer) if raw_pointer else default_pointer).resolve()
    if v35_root != default_v35_root:
        raise ValueError(f"V3.5 data root must be the trusted sibling: {default_v35_root}")
    if pointer != default_pointer:
        raise ValueError(f"selector-ready pointer must be the trusted pointer: {default_pointer}")
    if not v35_root.is_dir():
        raise ValueError(f"V3.5 data root missing: {v35_root}")
    if not pointer.is_file():
        raise ValueError(f"selector-ready pointer missing: {pointer}")
    try:
        pointed_text = pointer.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"selector-ready pointer unreadable: {pointer}") from exc
    if not pointed_text:
        raise ValueError(f"selector-ready pointer empty: {pointer}")
    pointed_panel = Path(pointed_text)
    if not pointed_panel.is_absolute():
        raise ValueError("selector-ready pointer must contain an absolute target")
    pointed_panel = pointed_panel.resolve()
    panel = (Path(raw_panel) if raw_panel else pointed_panel).resolve()
    if panel != pointed_panel:
        raise ValueError("selector-ready environment disagrees with pointer")
    try:
        panel.relative_to(selector_root)
    except ValueError as exc:
        raise ValueError(f"selector-ready target outside trusted root: {selector_root}") from exc
    if panel.suffix.lower() != ".parquet" or not panel.is_file():
        raise ValueError(f"selector-ready target missing: {panel}")
    return v35_root, pointer, panel


def _materialize_stage_universes_preflight(
    store_root: Path, trade_date: str
) -> dict[str, Any]:
    v35_root, pointer, panel = _trusted_universe_inputs()
    result = materialize_stage_universes(store_root, v35_root, panel, trade_date)
    return {
        **result,
        "status": "READY" if result.get("ok") else "FAILED",
        "selector_pointer": str(pointer),
        "selector_panel": str(panel),
    }


def _manager_pytdx_security_master_reuse_only(
    store_root: Path, trade_date: str, python_path: Path
) -> dict[str, Any]:
    """Reuse an exact verified master in manager PyTDX mode; never fetch via Futu."""

    def futu_disabled_collector(_python_path, _codes):
        raise StoreError("MANAGER_PYTDX_LATE_OBSERVATION_FUTU_SECURITY_MASTER_DISABLED")

    try:
        return ensure_hk_security_master(
            store_root,
            trade_date,
            python_path,
            collector=futu_disabled_collector,
        )
    except (OSError, StoreError, ValueError) as error:
        return {
            "ok": False,
            "status": "MANAGER_HK_SECURITY_MASTER_NOT_READY",
            "error": f"MANAGER_PYTDX_LATE_OBSERVATION_REQUIRES_EXISTING_HK_SECURITY_MASTER:{error}",
        }


def run_scheduled_stage_bundle(
    root: Path,
    trade_date: str,
    stage_id: str,
    *,
    now: datetime | None = None,
    python_path: Path | None = None,
    bundle_runner: Callable[..., dict[str, Any]] = run_stage_bundle,
    security_master_runner: Callable[..., dict[str, Any]] = ensure_hk_security_master,
    universe_runner: Callable[..., dict[str, Any]] = _materialize_stage_universes_preflight,
    max_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if stage_id not in {item[1] for item in SCHEDULED_STAGE_SPECS}:
        raise ValueError(f"stage is not a scheduled owner: {stage_id!r}")
    _validate_retry_controls(max_attempts, retry_backoff_seconds)
    now = now or datetime.now().astimezone()
    root = Path(root)
    manager_capture_mode = os.environ.get(_MANAGER_CLOSE_CAPTURE_MODE_ENV, "").strip()
    manager_pytdx_late_observation = (
        stage_id == "STAGE_1545_1555"
        and manager_capture_mode == _MANAGER_PYTDX_LATE_OBSERVATION_MODE
    )
    manager_capture_mode_invalid = (
        stage_id == "STAGE_1545_1555"
        and bool(manager_capture_mode)
        and not manager_pytdx_late_observation
    )
    calendar = evaluate_a_share_trade_date(trade_date)
    remaining = seconds_until_cutoff(now, stage_id) if now.strftime("%Y%m%d") == trade_date else 0.0

    bundle: dict[str, Any] | None = None
    security_master: dict[str, Any] | None = None
    universe_preflight: dict[str, Any] | None = None
    error = ""
    attempts = 0
    if remaining > 0:
        ok = False
        status = "NOT_DUE"
        error = f"stage cutoff not reached: {STAGE_WINDOWS[stage_id][2]}"
    elif manager_capture_mode_invalid:
        ok = False
        status = "FAILED"
        error = "MANAGER_CLOSE_CAPTURE_MODE_INVALID"
    elif not calendar.get("eligible"):
        ok = str(calendar.get("status")) in {
            "SKIPPED_NON_TRADING_DAY_WEEKEND",
            "SKIPPED_NON_TRADING_DAY_HOLIDAY",
        }
        status = "SKIPPED_NON_TRADING_DAY" if ok else "FAILED"
        if not ok:
            error = str(calendar.get("status") or "calendar rejected date")
    else:
        ok = False
        status = "FAILED"
        try:
            universe_preflight = universe_runner(root, trade_date)
            if not isinstance(universe_preflight, dict) or not universe_preflight.get("ok"):
                detail = (
                    universe_preflight.get("error")
                    if isinstance(universe_preflight, dict)
                    else "invalid preflight result"
                )
                raise StoreError(f"universe preflight failed: {detail or 'unknown error'}")
            if universe_preflight.get("status") != "READY":
                raise StoreError(
                    "universe preflight failed: status must be READY, got "
                    + str(universe_preflight.get("status") or "missing")
                )
            unsafe_flags = [
                key for key in _SAFETY if universe_preflight.get(key) is not False
            ]
            if unsafe_flags:
                raise StoreError(
                    "universe preflight safety flags must be false: "
                    + ", ".join(unsafe_flags)
                )
        except (OSError, StoreError, ValueError) as exc:
            error = str(exc)
            attempts = 0
        else:
            retryable = False
            for attempts in range(1, max_attempts + 1):
                try:
                    resolved_python = Path(python_path) if python_path is not None else resolve_futu_python()
                    security_master = (
                        _manager_pytdx_security_master_reuse_only(root, trade_date, resolved_python)
                        if manager_pytdx_late_observation
                        else security_master_runner(root, trade_date, resolved_python)
                    )
                    if not security_master.get("ok") or security_master.get("status") != "READY":
                        raise StoreError(
                            "HK security master not READY: "
                            + str(security_master.get("error") or security_master.get("status"))
                        )
                    bundle = bundle_runner(root, trade_date, stage_id, resolved_python)
                    ok = bool(bundle.get("ok"))
                    status = str(bundle.get("status") or ("READY" if ok else "FAILED"))
                    error = str(bundle.get("error") or "")
                    retryable = not ok and _result_has_transport_failure(bundle)
                except (OSError, StoreError, ValueError) as exc:
                    ok = False
                    status = "FAILED"
                    error = str(exc)
                    retryable = _is_retryable_transport_exception(exc)

                if ok or not retryable or attempts >= max_attempts:
                    break
                sleep_fn(retry_backoff_seconds)

    receipt = {
        "schema_version": "v3_shared_data.scheduled_stage_bundle_receipt.v1",
        "ok": ok,
        "status": status,
        "attempts": attempts,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "calendar": calendar,
        "universe_preflight": universe_preflight,
        "hk_security_master": security_master,
        "bundle": bundle,
        "error": error,
        **_SAFETY,
    }
    receipt_path = root / "scheduler" / "stages" / trade_date / stage_id / "receipt.json"
    latest_path = root / "scheduler" / "stages" / stage_id / "latest.json"
    _write_json_atomic(receipt_path, receipt)
    _write_json_atomic(latest_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path), "latest_path": str(latest_path)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default="auto")
    parser.add_argument("--stage-id", required=True, choices=[item[1] for item in SCHEDULED_STAGE_SPECS])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    if not root_text:
        print(json.dumps({"ok": False, "status": "FAILED", "error": "V3_SHARED_DATA_STORE_ROOT missing"}))
        return 1

    now = datetime.now().astimezone()
    trade_date = now.strftime("%Y%m%d") if args.trade_date == "auto" else str(args.trade_date)
    remaining = seconds_until_cutoff(now, args.stage_id) if now.strftime("%Y%m%d") == trade_date else 0.0
    if 0 < remaining <= 30:
        time.sleep(remaining + 0.25)
        now = datetime.now().astimezone()

    result = run_scheduled_stage_bundle(
        Path(root_text),
        trade_date,
        args.stage_id,
        now=now,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

