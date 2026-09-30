"""Mac research-panel adapter for the daily A/H authority chain.

The adapter accepts every path explicitly from its caller, collects or packs
path-neutral lane inputs, and dynamically invokes the original Windows A-share
sync/formula authorities plus the original HK 0.2 authority.  Its receipts and
``production_allowed``/``buy_gate_updated``/``orders_sent`` flags are
research-only safety evidence; they do not grant production or trading
permission.  Any pointer or authority promotion remains governed by those
explicit authority entry points rather than by this module's documentation.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _datetime
import hashlib
import json
import math
import os
import importlib.util
import subprocess
import sys
import struct
import tempfile
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from infrastructure.owned_io import SafeRoot
from infrastructure.formula_generation import (
    FormulaGenerationError,
    is_v4_formula_state_owner,
    read_formula_generation,
)

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



A_DAY_STRUCT = struct.Struct("<IIIIIfII")
HK_DAY_STRUCT = struct.Struct("<IfffffII")
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
LANE_CHOICES = ("A", "HK", "ALL")
FORMULA_GENERATION_SCHEMA = "v4.a_formula.generation_pointer.v1"
FORMULA_GENERATION_POINTER_NAME = "CURRENT_FORMULA_GENERATION.json"


class SnapshotGateError(ValueError):
    """Raised when a lane input cannot be proven safe for the target date."""


HKCONNECT_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")
PYTDX_KLINE_DAY = 9
MAX_EXCLUDED_EVIDENCE = 100
COMMON_A_PREFIXES = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("430", "83", "87", "88", "92"),
}
AUTHORITY_DAY_MINIMUM_DEFAULT = 1
DEFAULT_A_SYNC_RUN_BUDGET_SECONDS = 540.0
A_SYNC_RUN_BUDGET_ENV = "V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"
A_SYNC_HOST_ENV = "V35_A_SYNC_HOST"
A_FORMULA_GENERATION_POINTER_ENV = "V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER"


def _resolve_a_sync_run_budget(raw: Any | None) -> float:
    """Resolve the A sync wall-clock budget, rejecting unsafe values."""
    from ops._macos_research_panel_daily_parts.panel_primitives import __resolve_a_sync_run_budget_body as _v4_impl
    return _v4_impl(globals(), raw)


def _today_shanghai() -> str:
    """Return the local trading date used when the CLI date is omitted."""
    return _datetime.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _scheduled_day_is_cross_market_trading_day(target_date: str) -> bool:
    """Return whether an implicit daily run may collect both panel lanes.

    An omitted ``--date`` is the launchd path.  It must be fail-closed when
    launchd coalesces a missed weekday run onto a weekend or an exchange
    holiday; an explicit date remains a deliberate, testable replay request.
    The calendar is loaded from this source tree, never inferred from the
    weekday alone.
    """
    from ops._macos_research_panel_daily_parts.calendar_schedule import __scheduled_day_is_cross_market_trading_day_body as _v4_impl
    return _v4_impl(globals(), target_date)


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    else:
        records = frame
    if records is None:
        return []
    return [dict(row) for row in records]


def _compact_datetime(value: Any) -> str:
    text = str(value or "")
    digits = "".join(character for character in text if character.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _canonical_sha(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _universe_code(row: Mapping[str, Any]) -> tuple[str, str, int]:
    value = str(row.get("ts_code") or row.get("code") or "").strip().upper()
    if "." not in value:
        raise SnapshotGateError(f"A universe row missing exchange: {value!r}")
    code, exchange = value.split(".", 1)
    code = "".join(ch for ch in code if ch.isdigit()).zfill(6)
    exchange = exchange.split("_", 1)[0]
    market = {"SZ": 0, "SH": 1, "BJ": 2}.get(exchange)
    if market is None or len(code) != 6:
        raise SnapshotGateError(f"unsupported A universe code: {value!r}")
    return code, exchange.lower(), market


def collect_a_pytdx_rows(
    universe_rows: Iterable[Mapping[str, Any]],
    target_date: str,
    *,
    client_factory: Callable[[], Any] | None = None,
    host: str | None = None,
    port: int | None = None,
    hq_hosts_override: Sequence[tuple[str, str, int]] | None = None,
    lookback: int = 400,
    minimum_rows: int = 1,
    required_coverage_ratio: float = 1.0,
) -> dict[str, Any]:
    """Collect one exact-date A-share bar per universe code from pytdx HQ."""
    from ops._macos_research_panel_daily_parts.a_market_capture import _collect_a_pytdx_rows_body as _v4_impl
    return _v4_impl(globals(), universe_rows, target_date, client_factory=client_factory, host=host, port=port, hq_hosts_override=hq_hosts_override, lookback=lookback, minimum_rows=minimum_rows, required_coverage_ratio=required_coverage_ratio)


def collect_hk_futu_rows(
    target_date: str,
    *,
    context_factory: Callable[[], Any] | None = None,
    batch_size: int = 200,
    minimum_universe_count: int = 600,
    required_coverage_ratio: float = 0.0,
) -> dict[str, Any]:
    """Collect an exact-date full HK Connect snapshot from Futu OpenD."""
    from ops._macos_research_panel_daily_parts.hk_market_capture import _collect_hk_futu_rows_body as _v4_impl
    return _v4_impl(globals(), target_date, context_factory=context_factory, batch_size=batch_size, minimum_universe_count=minimum_universe_count, required_coverage_ratio=required_coverage_ratio)


def _date(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        raise SnapshotGateError(f"invalid target date: {value!r}")
    try:
        _datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise SnapshotGateError(f"invalid target date: {value!r}") from error
    return text


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    result = [dict(row) for row in rows]
    if not result:
        raise SnapshotGateError("empty snapshot")
    return result


def _number(row: Mapping[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = row.get(name)
        if value is not None and str(value) != "":
            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise SnapshotGateError(f"non-numeric {name}") from error
    return default


def _code(row: Mapping[str, Any]) -> str:
    value = row.get("code") or row.get("code_norm") or row.get("ts_code")
    text = str(value or "").strip().upper()
    if "." in text:
        left, right = text.split(".", 1)
        text = right if left == "HK" else left
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise SnapshotGateError("missing security code")
    return digits


def _validate_rows(rows: list[dict[str, Any]], target_date: str, *, minimum_rows: int, lane: str) -> tuple[list[dict[str, Any]], float]:
    from ops._macos_research_panel_daily_parts.panel_primitives import __validate_rows_body as _v4_impl
    return _v4_impl(globals(), rows, target_date, minimum_rows=minimum_rows, lane=lane)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    from ops._macos_research_panel_daily_parts.panel_primitives import __atomic_write_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _panel_frame(panel_path: Path) -> list[dict[str, Any]]:
    if not panel_path.is_file():
        raise SnapshotGateError(f"A seed panel missing: {panel_path}")
    try:
        import pandas as pd

        frame = pd.read_parquet(panel_path)
        return _rows(frame)
    except Exception as error:
        raise SnapshotGateError(f"A seed panel unreadable: {panel_path}") from error


def bootstrap_a_vipdoc_from_panel(panel_path: Path | str, tdx_root: Path | str, *, tail_records: int = 260) -> dict[str, Any]:
    """Seed SH/SZ/BJ VIPDOC files from a panel tail without overwriting history."""
    from ops._macos_research_panel_daily_parts.a_market_capture import _bootstrap_a_vipdoc_from_panel_body as _v4_impl
    return _v4_impl(globals(), panel_path, tdx_root, tail_records=tail_records)


def _validate_seed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from ops._macos_research_panel_daily_parts.a_market_capture import __validate_seed_rows_body as _v4_impl
    return _v4_impl(globals(), rows)


def _load_authority_module(script_path: Path | str, module_name: str) -> Any:
    from ops._macos_research_panel_daily_parts.bounded_execution import __load_authority_module_body as _v4_impl
    return _v4_impl(globals(), script_path, module_name)


def _day_file_last_date(path: Path, record_struct: struct.Struct) -> int | None:
    records = _existing_records(path, record_struct)
    return int(records[-1][0]) if records else None


def run_windows_a_sync_authority(
    script_path: Path | str,
    tdx_root: Path | str,
    target_date: str,
    receipt_root: Path | str,
    *,
    minimum_target_date_files: int = 1,
    module_name: str = "macos_windows_a_sync_authority",
    authority_args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.bounded_execution import _run_windows_a_sync_authority_body as _v4_impl
    return _v4_impl(globals(), script_path, tdx_root, target_date, receipt_root, minimum_target_date_files=minimum_target_date_files, module_name=module_name, authority_args=authority_args)


def _parquet_max_date(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["trade_date"])
        values = table.column("trade_date").to_pylist()
        return max(int(str(value).replace("-", "")) for value in values) if values else None
    except Exception as error:
        raise SnapshotGateError(f"parquet target-date audit failed: {path}") from error


def selector_pointer_is_ready(
    pointer: Path | str | None,
    target_date: str,
    formula_generation_pointer: Path | str | None = None,
) -> bool:
    """Return true only when the authoritative selector reaches target date.

    A generation pointer enables the strict V4 contract: the exact selector
    and source/sidecar provenance must be verified together.  The two argument
    form remains the compatibility path for older callers and fixtures.
    """
    from ops._macos_research_panel_daily_parts.formula_pointer import _selector_pointer_is_ready_body as _v4_impl
    return _v4_impl(globals(), pointer, target_date, formula_generation_pointer)


def _path_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _formula_generation_target(
    output_root: Path,
    payload: Mapping[str, Any],
    role: str,
) -> Path:
    from ops._macos_research_panel_daily_parts.formula_pointer import __formula_generation_target_body as _v4_impl
    return _v4_impl(globals(), output_root, payload, role)


def _read_formula_generation(output_root: Path | str) -> dict[str, Any] | None:
    from ops._macos_research_panel_daily_parts.formula_pointer import __read_formula_generation_body as _v4_impl
    return _v4_impl(globals(), output_root)


def _find_formula_generation(target: Path) -> dict[str, Any] | None:
    from ops._macos_research_panel_daily_parts.formula_pointer import __find_formula_generation_body as _v4_impl
    return _v4_impl(globals(), target)


def _after_1700_attempt_path(receipt_root: Path | str, target_date: str) -> Path:
    return Path(receipt_root).expanduser().resolve() / "after_1700_ensure" / f"{_date(target_date)}.json"


def _normalize_lane(lane: str) -> str:
    normalized = str(lane or "ALL").upper()
    if normalized not in LANE_CHOICES:
        raise ValueError(f"lane must be one of {LANE_CHOICES!r}")
    return normalized


def _not_requested_lane() -> dict[str, Any]:
    return {"status": "NOT_REQUESTED", "runner_called": False, "receipt_written": False, **SAFETY_FLAGS}


def _read_lane_receipt(receipt_root: Path | str, lane: str, target_date: str) -> Mapping[str, Any] | None:
    """Read only the exact dated lane receipt used by the after-1700 gate."""

    path = Path(receipt_root).expanduser().resolve() / f"{lane.lower()}-{_date(target_date)}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _receipt_safety_is_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name) is False for name in SAFETY_FLAGS)


def _fast_path_lane_detail(
    receipt_root: Path | str,
    lane: str,
    target_date: str,
    *,
    ready: bool,
) -> dict[str, Any]:
    """Project an already verified dated receipt into the public lane envelope.

    The after-1700 fast path must remain idempotent without turning an old or
    malformed ``READY`` file into a new readiness claim.  The lane validators
    establish ``ready``; this helper rereads the same exact-date bytes only to
    carry their digest/size and a truthful lane status to the registry.
    """
    from ops._macos_research_panel_daily_parts.scheduled_readiness import __fast_path_lane_detail_body as _v4_impl
    return _v4_impl(globals(), receipt_root, lane, target_date, ready=ready)


def _a_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    selector_ready: bool,
    payload: Mapping[str, Any] | None = None,
    formula_generation_pointer: Path | str | None = None,
) -> tuple[bool, bool]:
    """Require exact A selector plus the formula's exact backtest readiness."""
    from ops._macos_research_panel_daily_parts.scheduled_readiness import __a_lane_receipt_ready_body as _v4_impl
    return _v4_impl(globals(), receipt_root, target_date, selector_ready, payload, formula_generation_pointer)


def _hk_lane_receipt_ready(
    receipt_root: Path | str,
    target_date: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Require the exact HK date receipt and a non-empty verified snapshot."""
    from ops._macos_research_panel_daily_parts.scheduled_readiness import __hk_lane_receipt_ready_body as _v4_impl
    return _v4_impl(globals(), receipt_root, target_date, payload)


def ensure_after_1700(
    *,
    target_date: str,
    receipt_root: Path | str,
    selector_pointer: Path | str | None,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str | None = None,
    now: _datetime.datetime | None = None,
    formula_generation_pointer: Path | str | None = None,
) -> dict[str, Any]:
    """Idempotently ensure the daily panel after 17:00.

    StartInterval can invoke this function repeatedly.  Explicit lane callers
    use only their exact dated receipt as a fast path: A requires selector and
    backtest readiness, HK requires a verified HK snapshot, and ALL requires
    both.  The dated attempt marker applies only a bounded time backoff and
    never converts a stale pointer into a permanent success or permanent
    lockout.
    """
    from ops._macos_research_panel_daily_parts.scheduled_readiness import _ensure_after_1700_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, receipt_root=receipt_root, selector_pointer=selector_pointer, a_runner=a_runner, hk_runner=hk_runner, lane=lane, now=now, formula_generation_pointer=formula_generation_pointer)


def ensure_exit_code(result: Mapping[str, Any]) -> int:
    """Map an after-17:00 result to a truthful process exit code.

    A retry marker or a completed attempt is not success evidence while the
    selector pointer still misses the exact target date.  launchd must keep
    retrying those results instead of recording a false healthy run.
    """
    from ops._macos_research_panel_daily_parts.scheduled_readiness import _ensure_exit_code_body as _v4_impl
    return _v4_impl(globals(), result)


def _ensure_pointer_seed(pointer: Path, seed: Path | str | None) -> Path:
    from ops._macos_research_panel_daily_parts.panel_primitives import __ensure_pointer_seed_body as _v4_impl
    return _v4_impl(globals(), pointer, seed)


def run_bounded_process(command: Sequence[str], *, timeout_seconds: float, cwd: Path | str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run one authority child in its own POSIX process group.

    This is a wall-clock boundary only.  macOS RSS/address-space enforcement is
    not claimed here; the child reports that limitation in its receipt.
    """
    from ops._macos_research_panel_daily_parts.bounded_execution import _run_bounded_process_body as _v4_impl
    return _v4_impl(globals(), command, timeout_seconds=timeout_seconds, cwd=cwd, env=env)


def run_v4_a_formula_offline(
    *,
    input_root: Path | str,
    input_manifest: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    target_date: str,
    timeout_seconds: float,
    legacy_formula_source: Path | str | None = None,
) -> dict[str, Any]:
    """Call the V4 increment runner without importing a legacy authority."""
    from ops._macos_research_panel_daily_parts.a_formula_execution import _run_v4_a_formula_offline_body as _v4_impl
    return _v4_impl(globals(), input_root=input_root, input_manifest=input_manifest, data_root=data_root, return_root=return_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, selector_seed=selector_seed, backtest_seed=backtest_seed, contract_csv=contract_csv, target_date=target_date, timeout_seconds=timeout_seconds, legacy_formula_source=legacy_formula_source)


def _strict_v4_path_root(
    generation_pointer: Path | str,
    *,
    tdx_root: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    receipt_root: Path | str,
) -> tuple[Path, Path]:
    """Check that the strict live candidate has one V4-owned write root."""
    from ops._macos_research_panel_daily_parts.a_formula_execution import __strict_v4_path_root_body as _v4_impl
    return _v4_impl(globals(), generation_pointer, tdx_root=tdx_root, data_root=data_root, return_root=return_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, receipt_root=receipt_root)


def run_v4_a_live_generation(
    *,
    sync_script: Path | str,
    tdx_root: Path | str,
    receipt_root: Path | str,
    target_date: str,
    minimum_target_date_files: int,
    sync_authority_args: Mapping[str, Any],
    data_root: Path | str,
    return_root: Path | str,
    generation_pointer: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    formula_timeout_seconds: float,
) -> dict[str, Any]:
    """Run the strict V4 live boundary without importing an old formula module."""
    from ops._macos_research_panel_daily_parts.a_formula_execution import _run_v4_a_live_generation_body as _v4_impl
    return _v4_impl(globals(), sync_script=sync_script, tdx_root=tdx_root, receipt_root=receipt_root, target_date=target_date, minimum_target_date_files=minimum_target_date_files, sync_authority_args=sync_authority_args, data_root=data_root, return_root=return_root, generation_pointer=generation_pointer, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, selector_seed=selector_seed, backtest_seed=backtest_seed, contract_csv=contract_csv, formula_timeout_seconds=formula_timeout_seconds)


def run_windows_a_formula_authority(
    script_path: Path | str,
    *,
    tdx_root: Path | str,
    data_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str | None,
    backtest_seed: Path | str | None,
    contract_csv: Path | str,
    canonical_formula_path: Path | str,
    return_root: Path | str,
    target_date: str,
    module_name: str = "macos_windows_formula_authority",
) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.a_formula_execution import _run_windows_a_formula_authority_body as _v4_impl
    return _v4_impl(globals(), script_path, tdx_root=tdx_root, data_root=data_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, selector_seed=selector_seed, backtest_seed=backtest_seed, contract_csv=contract_csv, canonical_formula_path=canonical_formula_path, return_root=return_root, target_date=target_date, module_name=module_name)


def run_hk_0_2_authority(updater_script: Path | str, python_executable: Path | str, asset_root: Path | str, tdx_root: Path | str, target_date: str) -> dict[str, Any]:
    target = _date(target_date)
    argv = [str(python_executable), str(Path(updater_script)), "--asset-root", str(Path(asset_root)), "--tdx-root", str(Path(tdx_root)), "--through-date", target]
    completed = subprocess.run(argv, shell=False, check=True, capture_output=True, text=True)
    try:
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise SnapshotGateError("HK authority output is not JSON") from error
    if outcome.get("status") != "READY" or _date(outcome.get("through_date")) != target:
        raise SnapshotGateError(f"HK authority through-date postcondition failed: {outcome}")
    return {**outcome, "target_date": target, "argv": argv, **SAFETY_FLAGS}


def _existing_records(path: Path, record_struct: struct.Struct) -> list[tuple[Any, ...]]:
    if not path.exists():
        return []
    payload = path.read_bytes()
    if len(payload) % record_struct.size:
        raise SnapshotGateError(f"existing .day has trailing bytes: {path.name}")
    return [record_struct.unpack(payload[offset : offset + record_struct.size]) for offset in range(0, len(payload), record_struct.size)]


def _a_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        int(round(_number(row, "open") * 100)),
        int(round(_number(row, "high") * 100)),
        int(round(_number(row, "low") * 100)),
        int(round(_number(row, "close") * 100)),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol"))),
        0,
    )


def _hk_record(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["trade_date"]),
        _number(row, "open"),
        _number(row, "high"),
        _number(row, "low"),
        _number(row, "close"),
        _number(row, "turnover", "amount"),
        int(round(_number(row, "volume", "vol", default=1))),
        0,
    )


def _pack_day_file(destination: Path, rows: Iterable[Mapping[str, Any]], target_date: str, *, lane: str, minimum_rows: int, record_struct: struct.Struct, record_builder: Callable[[Mapping[str, Any]], tuple[Any, ...]]) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.day_file_output import __pack_day_file_body as _v4_impl
    return _v4_impl(globals(), destination, rows, target_date, lane=lane, minimum_rows=minimum_rows, record_struct=record_struct, record_builder=record_builder)


def _a_exchange(row: Mapping[str, Any]) -> str:
    from ops._macos_research_panel_daily_parts.panel_primitives import __a_exchange_body as _v4_impl
    return _v4_impl(globals(), row)


def _grouped_result(results: list[dict[str, Any]], target_date: str, *, lane: str) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.day_file_output import __grouped_result_body as _v4_impl
    return _v4_impl(globals(), results, target_date, lane=lane)


def pack_a_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 1) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.day_file_output import _pack_a_day_body as _v4_impl
    return _v4_impl(globals(), destination, rows, target_date=target_date, minimum_rows=minimum_rows)


def pack_hk_day(destination: Path | str, rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int = 600, expected_codes: set[str] | None = None) -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.day_file_output import _pack_hk_day_body as _v4_impl
    return _v4_impl(globals(), destination, rows, target_date=target_date, minimum_rows=minimum_rows, expected_codes=expected_codes)


def validate_snapshot(rows: Iterable[Mapping[str, Any]], *, target_date: str, minimum_rows: int, expected_codes: set[str] | None = None, lane: str) -> dict[str, Any]:
    checked, _ = _validate_rows(_rows(rows), target_date, minimum_rows=minimum_rows, lane=lane)
    actual = {_code(row) for row in checked}
    expected = {_code({"code": code}) for code in expected_codes} if expected_codes else actual
    if actual != expected:
        raise SnapshotGateError(f"{lane} coverage mismatch: {len(actual)}/{len(expected)}")
    canonical = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"trade_date": _date(target_date), "row_count": len(checked), "coverage_rate": len(actual) / max(len(expected), 1), "sha256": hashlib.sha256(canonical).hexdigest(), **SAFETY_FLAGS}


def _receipt(root: Path, lane: str, target_date: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
    payload = {"schema_version": "v3.macos.research_panel_receipt.v1", "lane": lane, "target_date": _date(target_date), **dict(outcome), **SAFETY_FLAGS}
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / f"{lane.lower()}-{_date(target_date)}.json", (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def run_lanes(*, target_date: str, receipt_root: Path | str, a_runner: Callable[[str], Mapping[str, Any]], hk_runner: Callable[[str], Mapping[str, Any]], lane: str = "ALL") -> dict[str, Any]:
    from ops._macos_research_panel_daily_parts.panel_primitives import _run_lanes_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, receipt_root=receipt_root, a_runner=a_runner, hk_runner=hk_runner, lane=lane)


def _non_trading_day_result(target_date: str, receipt_root: Path | str, *, lane: str = "ALL") -> dict[str, Any]:
    """Emit explicit no-op receipts for an implicit non-trading-day launch."""
    from ops._macos_research_panel_daily_parts.calendar_schedule import __non_trading_day_result_body as _v4_impl
    return _v4_impl(globals(), target_date, receipt_root, lane=lane)


def run_scheduled_lanes(
    *,
    target_date: str | None,
    receipt_root: Path | str,
    a_runner: Callable[[str], Mapping[str, Any]],
    hk_runner: Callable[[str], Mapping[str, Any]],
    lane: str = "ALL",
) -> dict[str, Any]:
    """Run launchd's implicit date only on a proven A/H business day.

    Callers that supply ``target_date`` retain the existing explicit replay
    semantics, including the ability to diagnose a holiday snapshot.
    """
    from ops._macos_research_panel_daily_parts.calendar_schedule import _run_scheduled_lanes_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, receipt_root=receipt_root, a_runner=a_runner, hk_runner=hk_runner, lane=lane)


def build_subprocess_command(script: Path | str, target_date: str, receipt_root: Path | str) -> list[str]:
    return ["/usr/bin/python3", str(Path(script)), "--date", _date(target_date), "--receipt-root", str(Path(receipt_root))]


def _load_universe(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotGateError(f"A universe JSON is unreadable: {path}") from error
    if isinstance(payload, Mapping):
        payload = payload.get("rows") or payload.get("universe") or payload.get("data")
    if not isinstance(payload, list):
        raise SnapshotGateError("A universe JSON must contain a list of rows")
    rows = _rows(payload)
    return rows[: int(limit)] if limit is not None else rows


def _a_day_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for exchange in ("sh", "sz", "bj"):
        for path in sorted((root / "vipdoc" / exchange / "lday").glob(f"{exchange}*.day")):
            code = path.stem[len(exchange) :]
            if code.isdigit() and code.startswith(COMMON_A_PREFIXES[exchange]):
                files.append(path)
    return files


def _absolute_path_argument(parser: argparse.ArgumentParser, value: Path, name: str) -> Path:
    path = value.expanduser()
    if not path.is_absolute():
        parser.error(f"{name} must be an absolute path")
    return path


def _public_envelope(result: Mapping[str, Any], receipt_root: Path) -> dict[str, Any]:
    """Bounded stdout protocol; full updater evidence stays in dated receipts.

    Digests bind this invocation's response to the exact bytes, not to a latest
    pointer. The registry independently reads and verifies those bytes. This
    is transport evidence, not a replacement for authority/manifest validation.
    """
    from ops._macos_research_panel_daily_parts.cli import __public_envelope_body as _v4_impl
    return _v4_impl(globals(), result, receipt_root)


def main(argv: Sequence[str] | None = None) -> int:
    from ops._macos_research_panel_daily_parts.cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
