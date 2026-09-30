"""Read-only Mac collector adapters built from the verified shared_data core.

The module does not start OpenD, change subscriptions, or touch a live store.
It invokes the existing shared-data probes with explicit code lists and
normalizes their result into the stage-center ``SourceResult`` contract.  The
caller owns publication and supplies the exact candidate/full-universe roots.
"""
from __future__ import annotations

import subprocess
import csv
import hashlib
import json
import inspect
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .acquisition import AcquisitionPlan, SourceResult
from .contracts import STAGE_BY_ID

BridgeRunner = Callable[..., Any]


def _has_runner_verified_formal_overlay(row: Mapping[str, Any]) -> bool:
    """Return whether the runner attached the exact-date formal authority.

    ``_formal_authority_overlay_verified`` is retained as a compatibility
    field in the in-memory row, but it is caller-controlled input at this
    boundary.  Only the runner-owned proof object can authorize the formal
    lane; a raw collector or direct builder caller cannot obtain that proof by
    setting the legacy boolean marker.
    """
    from stage_center._live_collectors_parts.temporal_validation import __has_runner_verified_formal_overlay_body as _v4_impl
    return _v4_impl(globals(), row)


def _scoped_process_runner(shared_root: Path, process_runner: BridgeRunner) -> BridgeRunner:
    """Bind child imports to the explicit shared-data package root.

    The legacy probe is a ``python -m scripts...`` child.  launchd can invoke
    the parent from an arbitrary working directory, so relying on inherited
    cwd/PYTHONPATH produces the observed ``ModuleNotFoundError``.  This
    wrapper changes only the child invocation; it never mutates ``os.environ``
    in the parent process.
    """
    from stage_center._live_collectors_parts.shared_module_loading import __scoped_process_runner_body as _v4_impl
    return _v4_impl(globals(), shared_root, process_runner)


def _safe_number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_a_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(\d{6})", text)
    return f"A.{match.group(1)}" if match else ""


def _canonical_hk_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(?:HK\.)?(\d{5})", text)
    return f"HK.{match.group(1)}" if match else ""


def _auction_time(value: Any, trade_date: str) -> str | None:
    text = str(value or "").strip()
    if trade_date not in re.sub(r"\D+", "", text):
        return None
    match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not match:
        return None
    hh, mm, ss = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if not (9 * 60 + 20 <= hh * 60 + mm <= 9 * 60 + 25):
        return None
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {hh:02d}:{mm:02d}:{ss:02d}"


def _stage_0925_cutoff_iso(trade_date: str) -> str:
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        raise ValueError("STAGE_0925 replay trade_date must be YYYYMMDD")
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T09:25:05"


def _stage_0925_hk_reference_cutoff_iso(trade_date: str) -> str:
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        raise ValueError("HK STAGE_0925 replay trade_date must be YYYYMMDD")
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T09:20:05"


def _stage_cutoff_iso(trade_date: str, stage_id: str) -> str:
    stage = STAGE_BY_ID.get(stage_id)
    if stage is None or not re.fullmatch(r"\d{8}", str(trade_date)):
        raise ValueError(f"{stage_id} replay identity is invalid")
    hh, mm, ss = (int(item) for item in stage.cutoff.split(":"))
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{hh:02d}:{mm:02d}:{ss:02d}"


def _exact_market_timestamp(value: Any, trade_date: str) -> datetime | None:
    """Parse a market timestamp while binding date-only times to ``trade_date``."""
    from stage_center._live_collectors_parts.temporal_validation import __exact_market_timestamp_body as _v4_impl
    return _v4_impl(globals(), value, trade_date)


def _snapshot_temporal_cutoff_safe(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    cutoff_at: str,
) -> bool:
    from stage_center._live_collectors_parts.temporal_validation import __snapshot_temporal_cutoff_safe_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date=trade_date, cutoff_at=cutoff_at)


def _replay_auction_time(value: Any, trade_date: str) -> str | None:
    """Normalize a provider's HH:MM[:SS] tick time under the exact date."""
    text = str(value or "").strip()
    if not text:
        return None
    if re.search(r"\d{4}-\d{2}-\d{2}", text):
        return _auction_time(text, trade_date)
    return _auction_time(f"{trade_date} {text}", trade_date)


def _validate_replay_payload(
    payload: Any,
    *,
    trade_date: str,
    stage_id: str,
    cutoff_at: str,
) -> tuple[Mapping[str, Any], str, Sequence[Any]]:
    """Validate a read-only replay envelope before normalizing any rows."""
    from stage_center._live_collectors_parts.temporal_validation import __validate_replay_payload_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff_at)


def _shared_scripts_root(path: Path | str) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"shared_data root is not a directory: {root}")
    return root


def _load_shared_module(shared_root: Path, module_name: str) -> Any:
    # Importing a module from the existing Mac release is intentionally lazy:
    # a dry-run/config validation never imports network clients.
    from stage_center._live_collectors_parts.shared_module_loading import __load_shared_module_body as _v4_impl
    return _v4_impl(globals(), shared_root, module_name)


def _to_source(result: Any, *, source_id: str, route: str, requested: int) -> SourceResult:
    from stage_center._live_collectors_parts.temporal_validation import __to_source_body as _v4_impl
    return _v4_impl(globals(), result, source_id=source_id, route=route, requested=requested)


def _tdx_code(code: str) -> str:
    """Map the stage-center canonical A.###### code to PyTDX's exchange code."""
    from stage_center._live_collectors_parts.temporal_validation import __tdx_code_body as _v4_impl
    return _v4_impl(globals(), code)


def collect_a_share_minute(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    process_runner: BridgeRunner = subprocess.run,
) -> SourceResult:
    """Use shared_data's Futu/PyTDX route for an explicit A code list."""
    from stage_center._live_collectors_parts.a_minute import _collect_a_share_minute_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, python_path=python_path, shared_root=shared_root, process_runner=process_runner)


def collect_a_share_hq_minute(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    process_runner: BridgeRunner = subprocess.run,
) -> SourceResult:
    """Use the verified PyTDX HQ path for the full A-share universe.

    The shared bridge's HQ probe is the V3 route for large universes and
    preserves the exact cutoff/amount aggregation.  Futu's 100-code
    subscription ceiling is therefore never used for this production path.
    """
    from stage_center._live_collectors_parts.a_minute import _collect_a_share_hq_minute_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, python_path=python_path, shared_root=shared_root, process_runner=process_runner)


def _collect_hk_0925_replay(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    replay_provider: Any | None,
) -> SourceResult:
    from stage_center._live_collectors_parts.hk_replay import __collect_hk_0925_replay_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, replay_provider=replay_provider)


def _collect_hk_stage8_replay(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    replay_provider: Any | None,
) -> SourceResult:
    from stage_center._live_collectors_parts.hk_replay import __collect_hk_stage8_replay_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, replay_provider=replay_provider)


def collect_hk_minute(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    process_runner: BridgeRunner = subprocess.run,
    replay_provider: Any | None = None,
) -> SourceResult:
    """Use ExHQ bars and the original Futu predicate on the fixed D-1 codes.

    ExHQ is the exact minute source, but it does not prove the V3
    ``LIVE_HKCONNECT_GAINER`` trigger.  The trigger came from a separate Futu
    full-market snapshot in the old V3 implementation. The V4 runner binds
    both probes to the same exact D-1 Top100; it never enumerates a plate.  The Futu result is copied only into the
    selection-only row fields; the immutable raw acquisition rows remain the
    ExHQ rows.
    """
    from stage_center._live_collectors_parts.hk_minute import _collect_hk_minute_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, python_path=python_path, shared_root=shared_root, process_runner=process_runner, replay_provider=replay_provider)


def refresh_hk_active_lanes(
    source: SourceResult,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    process_runner: BridgeRunner = subprocess.run,
    trade_date: str | None = None,
    stage_id: str | None = None,
    cutoff_at: str | None = None,
) -> SourceResult:
    """Re-probe only the V3 active trigger for an existing raw HK source.

    This is the recovery path after raw publication has succeeded but a
    selection publication failed.  It never calls ExHQ and never changes the
    immutable raw rows; it only rebuilds the selection-only lane metadata from
    the same explicit code-bounded Futu snapshot and carries its evidence.
    """
    from stage_center._live_collectors_parts.hk_minute import _refresh_hk_active_lanes_body as _v4_impl
    return _v4_impl(globals(), source, codes=codes, python_path=python_path, shared_root=shared_root, process_runner=process_runner, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff_at)


def _futu_hkconnect_active_snapshot(
    shared_root: Path,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    process_runner: BridgeRunner,
    trade_date: str | None = None,
    cutoff_at: str | None = None,
) -> tuple[dict[str, Mapping[str, Any]], tuple[str, ...], tuple[str, ...]]:
    """Run the old V3 Futu full-scan trigger against one explicit code set.

    The predicate is intentionally byte-for-byte in meaning with V3's
    ``_futu_hkconnect_active_snapshot``: positive percentage change, turnover
    at least 20m HKD, and volume ratio at least one.  A partial/failed full
    scan cannot establish an inactive result, therefore it returns no active
    rows and a fail-closed evidence marker.
    """
    from stage_center._live_collectors_parts.hk_active_snapshot import __futu_hkconnect_active_snapshot_body as _v4_impl
    return _v4_impl(globals(), shared_root, codes=codes, python_path=python_path, process_runner=process_runner, trade_date=trade_date, cutoff_at=cutoff_at)


def collect_a_share_auction(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    auction_root: Path | str | None = None,
    process_runner: BridgeRunner = subprocess.run,
    replay_provider: Any | None = None,
) -> SourceResult:
    """Read the exact-date V3 auction artifact; never substitute minute bars."""
    from stage_center._live_collectors_parts.a_auction import _collect_a_share_auction_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, python_path=python_path, shared_root=shared_root, auction_root=auction_root, process_runner=process_runner, replay_provider=replay_provider)


def collect_hk_auction(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    auction_root: Path | str | None = None,
    process_runner: BridgeRunner = subprocess.run,
    replay_provider: Any | None = None,
) -> SourceResult:
    """Exact 09:15-09:20 HK route using the existing shared_data capture."""
    from stage_center._live_collectors_parts.hk_auction import _collect_hk_auction_body as _v4_impl
    return _v4_impl(globals(), plan, codes=codes, python_path=python_path, shared_root=shared_root, auction_root=auction_root, process_runner=process_runner, replay_provider=replay_provider)


def production_collectors(
    plan: AcquisitionPlan,
    *,
    python_path: Path | str,
    shared_root: Path | str,
    a_auction_root: Path | str | None = None,
    hk_auction_root: Path | str | None = None,
    hk_stage_replay_root: Path | str | None = None,
) -> dict[str, Callable[[AcquisitionPlan, str], SourceResult]]:
    """Return the packaged read-only collector bridge for one stage.

    09:25 remains intentionally fail-closed until an exact auction provider
    yields rows; no minute collector is substituted for the auction contract.
    """
    from stage_center._live_collectors_parts.collector_registry import _production_collectors_body as _v4_impl
    return _v4_impl(globals(), plan, python_path=python_path, shared_root=shared_root, a_auction_root=a_auction_root, hk_auction_root=hk_auction_root, hk_stage_replay_root=hk_stage_replay_root)


def production_selection_builders(
    stage_id: str,
    *,
    research_root: Path | str | None = None,
    morning_root: Path | str | None = None,
) -> dict[str, Callable[..., Mapping[str, Any]]]:
    """Build selection transforms from the package's frozen V3 pure formulas."""
    from stage_center._live_collectors_parts.selection_builder_registry import _production_selection_builders_body as _v4_impl
    return _v4_impl(globals(), stage_id, research_root=research_root, morning_root=morning_root)


__all__ = ["collect_a_share_auction", "collect_a_share_hq_minute", "collect_a_share_minute", "collect_hk_auction", "collect_hk_minute", "production_collectors", "production_selection_builders"]
