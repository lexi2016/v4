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
    from .runner import _FORMAL_AUTHORITY_OVERLAY_PROOF

    return row.get("_formal_authority_overlay_proof") is _FORMAL_AUTHORITY_OVERLAY_PROOF


def _scoped_process_runner(shared_root: Path, process_runner: BridgeRunner) -> BridgeRunner:
    """Bind child imports to the explicit shared-data package root.

    The legacy probe is a ``python -m scripts...`` child.  launchd can invoke
    the parent from an arbitrary working directory, so relying on inherited
    cwd/PYTHONPATH produces the observed ``ModuleNotFoundError``.  This
    wrapper changes only the child invocation; it never mutates ``os.environ``
    in the parent process.
    """
    root = str(shared_root.resolve())

    def run(command: Any, **kwargs: Any) -> Any:
        child_env = dict(os.environ)
        supplied_env = kwargs.get("env")
        if isinstance(supplied_env, Mapping):
            child_env.update({str(key): str(value) for key, value in supplied_env.items()})
        existing = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = os.pathsep.join(item for item in (root, existing) if item)
        kwargs["cwd"] = root
        kwargs["env"] = child_env
        return process_runner(command, **kwargs)

    return run


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
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-").replace("Z", "+00:00")
    if re.fullmatch(r"\d{8}.*", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if not re.search(r"\d{4}-\d{2}-\d{2}", text):
        text = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {text}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _snapshot_temporal_cutoff_safe(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    cutoff_at: str,
) -> bool:
    cutoff = _exact_market_timestamp(cutoff_at, trade_date)
    if cutoff is None or cutoff.date().isoformat().replace("-", "") != trade_date:
        return False
    for row in rows:
        captured = _exact_market_timestamp(
            row.get("update_time") or row.get("update_time_us") or row.get("time"),
            trade_date,
        )
        if captured is None or captured.date().isoformat().replace("-", "") != trade_date or captured > cutoff:
            return False
    return True


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
    if not isinstance(payload, Mapping):
        raise ValueError("replay payload must be a mapping")
    if str(payload.get("trade_date") or "") != trade_date:
        raise ValueError("replay trade_date mismatch")
    if str(payload.get("stage_id") or "") != stage_id:
        raise ValueError("replay stage_id mismatch")
    if payload.get("temporal_cutoff_safe") is not True:
        raise ValueError("replay temporal cutoff is not safe")
    for safety_key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(safety_key) is not False:
            raise ValueError(f"replay safety flag {safety_key} must be false")
    captured_at = str(payload.get("captured_at") or "")
    captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).replace(tzinfo=None)
    cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00")).replace(tzinfo=None)
    if captured.date().isoformat().replace("-", "") != trade_date or captured > cutoff:
        raise ValueError("replay captured_at is outside exact date/cutoff")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("replay rows must be a sequence")
    return payload, captured_at, raw_rows


def _shared_scripts_root(path: Path | str) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"shared_data root is not a directory: {root}")
    return root


def _load_shared_module(shared_root: Path, module_name: str) -> Any:
    # Importing a module from the existing Mac release is intentionally lazy:
    # a dry-run/config validation never imports network clients.
    import importlib
    import sys

    package_root = shared_root
    module_path = package_root.joinpath(*module_name.split("." )).with_suffix(".py")
    if not module_path.is_file():
        raise ValueError(f"shared collector module missing: {module_path}")
    # The shared bridge uses package-relative imports (``scripts.*``).  Add
    # its explicit root only for the import operation and restore sys.path
    # immediately, so an unrelated local ``scripts`` package cannot leak into
    # later slots.
    original_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "scripts" or name.startswith("scripts.")
    }
    try:
        for name in tuple(saved_modules):
            sys.modules.pop(name, None)
        sys.path.insert(0, str(package_root))
        module = importlib.import_module(module_name)
        module_file = Path(str(getattr(module, "__file__", ""))).resolve()
        try:
            module_file.relative_to(package_root)
        except ValueError as error:
            raise ValueError(f"shared collector resolved outside explicit root: {module_file}") from error
        return module
    finally:
        sys.path[:] = original_path
        for name in tuple(sys.modules):
            if name == "scripts" or name.startswith("scripts."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)


def _to_source(result: Any, *, source_id: str, route: str, requested: int) -> SourceResult:
    status = str(getattr(result, "status", "CANNOT_CONFIRM"))
    status = {"READ_OK": "READY", "DATA_PARTIAL": "PARTIAL_WITH_ROWS", "READ_FAILED": "CANNOT_CONFIRM"}.get(status, status)
    rows = tuple(getattr(result, "rows", ()) or ())
    cannot = tuple(getattr(result, "cannot_confirm", ()) or ())
    missing = tuple(getattr(result, "no_data_codes", ()) or ())
    return SourceResult(
        source_id=source_id,
        status=status,
        rows=rows,
        cannot_confirm=cannot,
        error=str(getattr(result, "error", "") or ""),
        requested_rows=int(getattr(result, "requested_code_count", requested) or requested),
        missing_symbols=missing,
        source_evidence=(f"route={route}", f"shared_data_root={result.__class__.__module__}"),
    )


def _tdx_code(code: str) -> str:
    """Map the stage-center canonical A.###### code to PyTDX's exchange code."""
    raw = str(code or "").strip().upper()
    if raw.startswith(("SH.", "SZ.", "BJ.")):
        return raw
    digits = raw.split(".", 1)[-1]
    if len(digits) != 6 or not digits.isdigit():
        raise ValueError(f"invalid canonical A code: {code!r}")
    if digits.startswith(("600", "601", "603", "605", "688", "689")):
        prefix = "SH"
    elif digits.startswith(("430", "830", "831", "832", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879")):
        prefix = "BJ"
    else:
        prefix = "SZ"
    return f"{prefix}.{digits}"


def collect_a_share_minute(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    python_path: Path | str,
    shared_root: Path | str,
    process_runner: BridgeRunner = subprocess.run,
) -> SourceResult:
    """Use shared_data's Futu/PyTDX route for an explicit A code list."""
    root = _shared_scripts_root(shared_root)
    module = _load_shared_module(root, "scripts.live_acquisition.futu_bridge")
    scoped_runner = _scoped_process_runner(root, process_runner)
    result = module.collect_futu_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        list(codes),
        market="A_SHARE",
        process_runner=scoped_runner,
    )
    return _to_source(result, source_id="futu", route="shared_futu_a_share_minute", requested=len(codes))


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
    root = _shared_scripts_root(shared_root)
    module = _load_shared_module(root, "scripts.live_acquisition.pytdx_hq")
    scoped_runner = _scoped_process_runner(root, process_runner)
    tdx_codes = [_tdx_code(code) for code in codes]
    result = module.collect_pytdx_hq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        tdx_codes,
        market="A_SHARE",
        process_runner=scoped_runner,
    )
    return _to_source(result, source_id="pytdx_hq", route="shared_pytdx_hq_a_share_exact_cutoff", requested=len(codes))


def _collect_hk_0925_replay(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    replay_provider: Any | None,
) -> SourceResult:
    cutoff_at = _stage_0925_hk_reference_cutoff_iso(plan.trade_date)
    evidence = (
        "route=hk_connect_0915_0920_auction_second_filter",
        "exact_date=true",
        "replay_method=v3_hkconnect_0915_0920_reference_snapshot",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_at}",
    )
    requested = tuple(dict.fromkeys(_canonical_hk_code(code) for code in codes if _canonical_hk_code(code)))
    if replay_provider is None:
        return SourceResult(
            "hk_auction_second_filter",
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_0925_REPLAY_PROVIDER_UNAVAILABLE",),
            source_evidence=evidence,
        )
    try:
        payload = replay_provider.snapshot(
            requested,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        payload, captured_at, raw_rows = _validate_replay_payload(
            payload,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        by_code: dict[str, dict[str, Any]] = {}
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            code = _canonical_hk_code(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _exact_market_timestamp(
                raw.get("update_time") or raw.get("time") or raw.get("stage_replay_latest_time"),
                plan.trade_date,
            )
            if update_time is None or update_time > datetime.fromisoformat(cutoff_at):
                raise ValueError(f"replay row timestamp outside exact cutoff: {code}")
            by_code[code] = {
                "batch_index": len(by_code) + 1,
                "code": code,
                "name": raw.get("name") or raw.get("stock_name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "update_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_price": _safe_number(raw.get("last_price")),
                "open_price": _safe_number(raw.get("open_price") or raw.get("reference_price_hkd") or raw.get("last_price")),
                "high_price": _safe_number(raw.get("high_price") or raw.get("last_price")),
                "low_price": _safe_number(raw.get("low_price") or raw.get("last_price")),
                "prev_close_price": _safe_number(raw.get("prev_close_price") or raw.get("prev_close")),
                "turnover": _safe_number(raw.get("turnover") or raw.get("turnover_hkd")) or 0.0,
                "amount": _safe_number(raw.get("turnover") or raw.get("turnover_hkd")) or 0.0,
                "volume": _safe_number(raw.get("volume")) or 0.0,
                "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:15:00",
                "window_end": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "bar_count": raw.get("bar_count", 1),
                "temporal_cutoff_safe": True,
                "target_date": plan.trade_date,
                "signal_date": raw.get("signal_date") or "",
                "rank": raw.get("rank") or "",
                "auction_score": raw.get("auction_score") or raw.get("stage1_ref_score") or 0.0,
                "second_filter_status": raw.get("second_filter_status") or "WATCH_ONLY",
                "preselect_lane": raw.get("preselect_lane") or "",
                "reference_price_hkd": raw.get("reference_price_hkd") or raw.get("last_price") or "",
                "strict_failure_price_hkd": raw.get("strict_failure_price_hkd") or raw.get("bid_price") or "",
            }
        rows = tuple(by_code[code] for code in requested if code in by_code)
        missing = tuple(code for code in requested if code not in by_code)
        cannot = [str(item) for item in (payload.get("cannot_confirm") or ()) if str(item)]
        if missing:
            cannot.append("HK_0925_REPLAY_ROWS_MISSING: " + ", ".join(missing))
        status = "READY" if len(rows) == len(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return SourceResult(
            "hk_auction_second_filter",
            status,
            rows=rows,
            requested_rows=len(requested),
            missing_symbols=missing,
            cannot_confirm=tuple(dict.fromkeys(cannot)),
            source_evidence=tuple(dict.fromkeys((*evidence, f"replay_source={payload.get('source') or 'V3_HKCONNECT_0915_0920_REFERENCE_SNAPSHOT'}", f"replay_captured_at={captured_at}"))),
        )
    except Exception as error:
        return SourceResult(
            "hk_auction_second_filter",
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=(f"HK_0925_REPLAY_ERROR:{type(error).__name__}:{error}",),
            source_evidence=evidence,
        )


def _collect_hk_stage8_replay(
    plan: AcquisitionPlan,
    *,
    codes: Sequence[str],
    replay_provider: Any | None,
) -> SourceResult:
    cutoff_at = _stage_cutoff_iso(plan.trade_date, plan.stage_id)
    evidence = (
        "route=v3_hkconnect_stage8_rtd_data_replay",
        "exact_date=true",
        "replay_method=v3_hkconnect_stage8_rtd_data",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_at}",
    )
    requested = tuple(dict.fromkeys(_canonical_hk_code(code) for code in codes if _canonical_hk_code(code)))
    if replay_provider is None:
        return SourceResult(
            "v3_hkconnect_stage8_replay",
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=("HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE",),
            source_evidence=evidence,
        )
    try:
        payload = replay_provider.snapshot(
            requested,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        payload, captured_at, raw_rows = _validate_replay_payload(
            payload,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        cutoff = datetime.fromisoformat(cutoff_at)
        by_code: dict[str, dict[str, Any]] = {}
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            code = _canonical_hk_code(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _exact_market_timestamp(
                raw.get("stage_replay_latest_time") or raw.get("update_time") or raw.get("time"),
                plan.trade_date,
            )
            if update_time is None or update_time > cutoff:
                raise ValueError(f"replay row timestamp outside exact cutoff: {code}")
            source_universe = str(raw.get("source_universe") or "")
            candidate_lanes = [
                token
                for token in (item.strip() for item in source_universe.split("|"))
                if token in {
                    "LIVE_HKCONNECT_GAINER",
                    "NEW_HKCONNECT_BATCH",
                    "OLD_DEMON_MEMORY",
                    "LOW_FLOAT_FILTER",
                    "PREOPEN_AUCTION_CONTINUATION",
                }
            ]
            last_price = _safe_number(raw.get("last_price"))
            prev_close = _safe_number(raw.get("prev_close_price") or raw.get("prev_close"))
            pct = _safe_number(raw.get("pct_chg"))
            if pct is None and prev_close not in (None, 0) and last_price is not None:
                pct = (last_price - prev_close) / prev_close * 100.0
            turnover = _safe_number(raw.get("turnover_hkd") or raw.get("turnover"))
            by_code[code] = {
                "code": code,
                "name": raw.get("name") or raw.get("stock_name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "candidate_lanes": candidate_lanes,
                "source_universe": source_universe,
                "prev_close_price": prev_close,
                "last_price": last_price,
                "pct_chg": pct,
                "turnover": turnover,
                "turnover_hkd": turnover,
                "volume_ratio": _safe_number(raw.get("volume_ratio")),
                "turnover_rate": _safe_number(raw.get("turnover_rate")),
                "platform_circular_market_cap_hkd_yi": _safe_number(raw.get("platform_circular_market_cap_hkd_yi")),
                "offer_float_market_cap_hkd_yi": _safe_number(raw.get("offer_float_market_cap_hkd_yi")),
                "stage_window_change_pct": _safe_number(raw.get("stage_window_change_pct")),
                "update_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "stage_replay_latest_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "temporal_cutoff_safe": True,
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
            }
        rows = tuple(by_code[code] for code in requested if code in by_code)
        missing = tuple(code for code in requested if code not in by_code)
        cannot = [str(item) for item in (payload.get("cannot_confirm") or ()) if str(item)]
        if missing:
            cannot.append("HK_STAGE8_REPLAY_ROWS_MISSING: " + ", ".join(missing))
        status = "READY" if len(rows) == len(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return SourceResult(
            "v3_hkconnect_stage8_replay",
            status,
            rows=rows,
            requested_rows=len(requested),
            missing_symbols=missing,
            cannot_confirm=tuple(dict.fromkeys(cannot)),
            source_evidence=tuple(dict.fromkeys((*evidence, f"replay_source={payload.get('source') or 'V3_HKCONNECT_STAGE8_RTDATA_REPLAY'}", f"replay_captured_at={captured_at}"))),
        )
    except Exception as error:
        return SourceResult(
            "v3_hkconnect_stage8_replay",
            "CANNOT_CONFIRM",
            requested_rows=len(requested),
            cannot_confirm=(f"HK_STAGE8_REPLAY_ERROR:{type(error).__name__}:{error}",),
            source_evidence=evidence,
        )


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
    if plan.stage_id == "STAGE_1545_1555":
        # Stage 8 is a historical RT_DATA replay contract.  A live ExHQ/Futu
        # scan is not an equivalent source and must never be used as a
        # fallback when the exact replay provider is unavailable.
        return _collect_hk_stage8_replay(plan, codes=codes, replay_provider=replay_provider)
    root = _shared_scripts_root(shared_root)
    module = _load_shared_module(root, "scripts.live_acquisition.pytdx_exhq")
    scoped_runner = _scoped_process_runner(root, process_runner)
    result = module.collect_pytdx_exhq_minute(
        python_path,
        plan.trade_date,
        plan.stage_id,
        list(codes),
        market="HK_CONNECT",
        process_runner=scoped_runner,
    )
    source = _to_source(result, source_id="pytdx_exhq", route="shared_pytdx_exhq_hk_exact_d1_top100", requested=len(codes))
    if not source.rows:
        return source

    # This is intentionally a second, read-only module load.  The shared
    # auction module owns the already-reviewed Futu snapshot bridge and keeps
    # its child cwd/PYTHONPATH scoped by the same runner wrapper as ExHQ.
    return refresh_hk_active_lanes(
        source,
        codes=codes,
        python_path=python_path,
        shared_root=root,
        process_runner=process_runner,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        cutoff_at=STAGE_BY_ID[plan.stage_id].cutoff,
    )


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
    root = _shared_scripts_root(shared_root)
    scoped_runner = _scoped_process_runner(root, process_runner)
    active, evidence, probe_errors = _futu_hkconnect_active_snapshot(
        root,
        codes=codes,
        python_path=python_path,
        process_runner=scoped_runner,
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    )
    if "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in probe_errors and trade_date and cutoff_at:
        return replace(
            source,
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=tuple(dict.fromkeys((*source.cannot_confirm, *probe_errors))),
            source_evidence=tuple(dict.fromkeys((*source.source_evidence, *evidence))),
        )
    enriched: list[dict[str, Any]] = []
    for row in source.rows:
        code = _canonical_hk_code(row.get("code"))
        merged = dict(row)
        # A lane is valid only when this exact full-scan probe matched the
        # code.  Never carry a D-1/static lane into the live minute copy.
        merged["candidate_lanes"] = []
        snapshot = active.get(code)
        if snapshot is not None:
            merged["candidate_lanes"] = ["LIVE_HKCONNECT_GAINER"]
            merged["source_universe"] = "HK_CONNECT_D1_TOP100"
            merged["data_confidence"] = "STAGE_RTDATA_CONFIRMED"
            merged["active_gainer_pass"] = True
            merged["volume_ratio"] = snapshot.get("volume_ratio")
            merged["active_snapshot_status"] = "FUTU_HKCONNECT_FULL_SCAN"
        enriched.append(merged)
    cannot = tuple(dict.fromkeys((*source.cannot_confirm, *probe_errors)))
    return replace(source, rows=tuple(enriched), cannot_confirm=cannot, source_evidence=tuple(dict.fromkeys((*source.source_evidence, *evidence))))


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
    requested = tuple(dict.fromkeys(_canonical_hk_code(code) for code in codes if _canonical_hk_code(code)))
    # Preserve the historical trigger identifier used by recovery, while
    # explicitly distinguishing it from full-market coverage.
    evidence_base = ("active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN", "active_snapshot_scope=EXPLICIT_REQUESTED_CODES", f"active_snapshot_requested_rows={len(requested)}")
    if trade_date is not None and cutoff_at is not None:
        evidence_base += (f"active_snapshot_trade_date={trade_date}", f"active_snapshot_cutoff={cutoff_at}")
    if not requested:
        return {}, evidence_base + ("active_snapshot_sha256=" + hashlib.sha256(b"[]").hexdigest(),), ("HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE",)
    try:
        module = _load_shared_module(shared_root, "shared_data.hk_auction_0920")
        # shared_data.hk_auction_0920's reviewed bridge takes the explicit
        # Python executable first, then the exact code list.  A narrow
        # signature check also keeps deterministic test doubles (which expose
        # the older ``(codes, ...)`` seam) from changing production behavior.
        fetch = module.fetch_futu_snapshot
        first_parameter = next(iter(inspect.signature(fetch).parameters), "")
        if first_parameter in {"codes", "symbols"}:
            fetched = fetch(list(requested), process_runner=process_runner)
        else:
            fetched = fetch(python_path, list(requested), process_runner=process_runner)
        if not isinstance(fetched, tuple) or len(fetched) != 2:
            raise ValueError("Futu snapshot bridge returned an invalid result")
        raw_rows, errors = fetched
        snapshot_rows = [item for item in (raw_rows or ()) if isinstance(item, Mapping)]
        errors_tuple = tuple(str(item) for item in (errors or ()) if str(item))
    except Exception:
        snapshot_rows = []
        errors_tuple = ("bridge_error",)

    canonical_rows: list[dict[str, Any]] = []
    by_code: dict[str, Mapping[str, Any]] = {}
    for raw in snapshot_rows:
        code = _canonical_hk_code(raw.get("code") or raw.get("stock_code") or raw.get("symbol"))
        if not code or code in by_code:
            continue
        normalized = {
            "code": code,
            "prev_close_price": _safe_number(raw.get("prev_close_price") or raw.get("prev_close")),
            "last_price": _safe_number(raw.get("last_price") or raw.get("last")),
            "turnover": _safe_number(raw.get("turnover")),
            "volume_ratio": _safe_number(raw.get("volume_ratio")),
            "update_time": str(raw.get("update_time") or raw.get("update_time_us") or ""),
        }
        by_code[code] = normalized
        canonical_rows.append(normalized)
    canonical_rows.sort(key=lambda item: item["code"])
    snapshot_sha = hashlib.sha256(
        json.dumps(canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    codes_sha = hashlib.sha256(
        json.dumps(list(requested), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence = evidence_base + (
        f"active_snapshot_codes_sha256={codes_sha}",
        f"active_snapshot_sha256={snapshot_sha}",
        f"active_snapshot_returned_rows={len(by_code)}",
    )
    if errors_tuple or set(by_code) != set(requested):
        return {}, evidence, ("HK_ACTIVE_GAINER_SNAPSHOT_UNAVAILABLE",)
    if trade_date is not None and cutoff_at is not None and not _snapshot_temporal_cutoff_safe(
        canonical_rows,
        trade_date=trade_date,
        cutoff_at=cutoff_at,
    ):
        return {}, evidence + ("active_snapshot_temporal_cutoff_safe=false",), ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",)
    if trade_date is not None and cutoff_at is not None:
        evidence += ("active_snapshot_temporal_cutoff_safe=true",)

    active: dict[str, Mapping[str, Any]] = {}
    for code, row in by_code.items():
        prev_close = row.get("prev_close_price")
        last_price = row.get("last_price")
        turnover = row.get("turnover")
        volume_ratio = row.get("volume_ratio")
        pct = ((float(last_price) / float(prev_close)) - 1.0) * 100.0 if prev_close not in (None, 0) and last_price is not None else None
        if pct is not None and pct > 0 and turnover is not None and turnover >= 20_000_000 and volume_ratio is not None and volume_ratio >= 1:
            active[code] = row
    if not active:
        return {}, evidence + ("active_snapshot_active_rows=0",), ("HK_ACTIVE_GAINER_NO_MATCH",)
    return active, evidence + (f"active_snapshot_active_rows={len(active)}",), ()


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
    if plan.stage_id != "STAGE_0925":
        raise ValueError("A auction collector is restricted to STAGE_0925")
    root = Path(auction_root).expanduser().resolve() if auction_root is not None else None
    csv_path = (
        root / "generated_stages" / plan.trade_date / f"generated_stage1_0925_auction_{plan.trade_date}.csv"
        if root is not None else None
    )
    if csv_path is not None and csv_path.is_file():
        rows: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for raw in csv.DictReader(stream):
                code = _canonical_a_code(raw.get("ts_code") or raw.get("stock_code") or raw.get("code"))
                when = _auction_time(raw.get("last_time") or raw.get("first_time") or raw.get("update_time"), plan.trade_date)
                if not code or not when:
                    continue
                amount = _safe_number(raw.get("amount_in_window") or raw.get("auction_amount_est_yuan") or raw.get("amount"))
                price = _safe_number(raw.get("last_close") or raw.get("first_open") or raw.get("last_price"))
                rows.append({
                    "batch_index": len(rows) + 1,
                    "code": code,
                    "name": raw.get("name") or raw.get("display_name") or code,
                    "update_time": when,
                    "last_price": price,
                    "open_price": _safe_number(raw.get("first_open")) or price,
                    "high_price": _safe_number(raw.get("high_price")) or price,
                    "low_price": _safe_number(raw.get("low_price")) or price,
                    "prev_close_price": _safe_number(raw.get("prev_close_price")),
                    "turnover": amount or 0.0,
                    "volume": _safe_number(raw.get("volume")) or 0.0,
                    "bid_price": _safe_number(raw.get("bid_price")) or "",
                    "ask_price": _safe_number(raw.get("ask_price")) or "",
                    "bid_vol": _safe_number(raw.get("bid_vol")) or "",
                    "ask_vol": _safe_number(raw.get("ask_vol")) or "",
                    "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:20:00",
                    "window_end": when,
                    "bar_count": 1,
                    "temporal_cutoff_safe": True,
                    "time": when,
                    "amount": amount or 0.0,
                    "trade_date": plan.trade_date,
                    "is_open_call_auction_match": True,
                })
        status = "READY" if len(rows) >= len(codes) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return SourceResult(
            source_id="a_share_auction",
            status=status,
            rows=tuple(rows),
            cannot_confirm=() if status == "READY" else (f"A_0925_EXACT_AUCTION_ROWS_{len(rows)}/{len(codes)}",),
            requested_rows=len(codes),
            missing_symbols=tuple(sorted(set(codes) - {str(row["code"]) for row in rows})),
            source_evidence=("route=a_share_exact_date_auction_transaction", "exact_date=true", f"auction_csv={csv_path}", f"auction_csv_sha256={_sha_file(csv_path)}"),
        )
    # The generated CSV is the preferred exact artifact.  When it is absent,
    # replay the same date/cutoff through the existing read-only PyTDX history
    # provider.  This is deliberately a narrow fallback: it never reads a
    # current snapshot and never turns L0 transaction data into an order book.
    cutoff_iso = _stage_0925_cutoff_iso(plan.trade_date)
    replay_evidence = (
        "route=a_share_exact_date_auction_transaction",
        "exact_date=true",
        "replay_method=pytdx.hq.get_history_transaction_data",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_iso}",
    )
    try:
        if replay_provider is None:
            from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider

            replay_provider = TdxMinuteReplayProvider()
        payload = replay_provider.snapshot(
            tuple(codes),
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_iso,
        )
        if not isinstance(payload, Mapping):
            raise ValueError("replay payload must be a mapping")
        if str(payload.get("trade_date") or plan.trade_date) != plan.trade_date:
            raise ValueError("replay trade_date mismatch")
        if str(payload.get("stage_id") or plan.stage_id) != plan.stage_id:
            raise ValueError("replay stage_id mismatch")
        if payload.get("temporal_cutoff_safe") is not True:
            raise ValueError("replay temporal cutoff is not safe")
        for safety_key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            if payload.get(safety_key) is not False:
                raise ValueError(f"replay safety flag {safety_key} must be false")
        captured_at = str(payload.get("captured_at") or "")
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        cutoff = datetime.fromisoformat(cutoff_iso)
        if captured.date() != cutoff.date() or captured > cutoff:
            raise ValueError("replay captured_at is outside exact date/cutoff")
        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
            raise ValueError("replay rows must be a sequence")
        requested = tuple(dict.fromkeys(_canonical_a_code(code) for code in codes if _canonical_a_code(code)))
        by_code: dict[str, dict[str, Any]] = {}
        invalid_rows: list[str] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                invalid_rows.append("non_mapping_row")
                continue
            code = _canonical_a_code(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _replay_auction_time(raw.get("source_last_tick_time") or raw.get("time") or captured_at, plan.trade_date)
            numeric = {
                key: _safe_number(raw.get(key))
                for key in ("open_price", "last_price", "high_price", "low_price", "prev_close_price", "turnover", "volume")
            }
            if update_time is None or any(numeric[key] is None for key in ("open_price", "last_price", "high_price", "low_price", "turnover", "volume")):
                invalid_rows.append(code or "unknown_code")
                continue
            by_code[code] = {
                "batch_index": len(by_code) + 1,
                "code": code,
                "name": raw.get("name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "update_time": update_time,
                "time": update_time,
                "last_price": numeric["last_price"],
                "open_price": numeric["open_price"],
                "high_price": numeric["high_price"],
                "low_price": numeric["low_price"],
                "prev_close_price": numeric["prev_close_price"],
                "turnover": numeric["turnover"],
                "amount": numeric["turnover"],
                "volume": numeric["volume"],
                "bid_price": _safe_number(raw.get("bid_price") or raw.get("bid_price1")) or "",
                "ask_price": _safe_number(raw.get("ask_price") or raw.get("ask_price1")) or "",
                "bid_vol": _safe_number(raw.get("bid_vol") or raw.get("bid_vol1")) or "",
                "ask_vol": _safe_number(raw.get("ask_vol") or raw.get("ask_vol1")) or "",
                "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:20:00",
                "window_end": update_time,
                "bar_count": raw.get("source_tick_count", 1),
                "temporal_cutoff_safe": True,
                "trade_date": plan.trade_date,
                "is_open_call_auction_match": True,
                "source_method": raw.get("source_method") or "pytdx.hq.get_history_transaction_data",
                "source_last_tick_time": raw.get("source_last_tick_time") or update_time,
            }
        rows = tuple(by_code[code] for code in requested if code in by_code)
        missing = tuple(code for code in requested if code not in by_code)
        cannot = list(str(item) for item in (payload.get("cannot_confirm") or ()) if str(item))
        if missing:
            cannot.append("PYTDX_0925_AUCTION_ROWS_MISSING: " + ", ".join(missing))
        if invalid_rows:
            cannot.append("PYTDX_0925_INVALID_ROWS: " + ", ".join(dict.fromkeys(invalid_rows)))
        status = "READY" if len(rows) == len(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return SourceResult(
            source_id="a_share_auction",
            status=status,
            rows=rows,
            cannot_confirm=tuple(dict.fromkeys(cannot)),
            requested_rows=len(requested),
            missing_symbols=missing,
            source_evidence=tuple(
                dict.fromkeys(
                    (
                        *replay_evidence,
                        f"replay_source={payload.get('source') or 'PYTDX_A_SHARE_0925_HISTORY_TRANSACTION'}",
                        f"replay_captured_at={captured_at}",
                        "replay_temporal_cutoff_safe=true",
                    )
                )
            ),
        )
    except Exception as error:
        return SourceResult(
            source_id="a_share_auction",
            status="CANNOT_CONFIRM",
            cannot_confirm=(f"PYTDX_0925_REPLAY_ERROR:{type(error).__name__}:{error}",),
            error=str(error),
            requested_rows=len(codes),
            source_evidence=replay_evidence,
        )


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
    if plan.stage_id != "STAGE_0925":
        raise ValueError("HK auction collector is restricted to STAGE_0925")
    root = Path(auction_root).expanduser().resolve() if auction_root is not None else None
    csv_path = None
    if root is not None:
        stem = f"hkconnect_0920_auction_second_filter_{plan.trade_date}.csv"
        candidates = (root if root.is_file() else root / stem, root / plan.trade_date / stem, root / "0920_auction_second_filter" / stem)
        csv_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if csv_path is not None:
        rows: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for raw in csv.DictReader(stream):
                code = _canonical_hk_code(raw.get("code") or raw.get("ts_code") or raw.get("stock_code"))
                if not code:
                    continue
                update = str(raw.get("collector_wall_time") or raw.get("update_time") or f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:19:59")
                rows.append({
                    "batch_index": len(rows) + 1,
                    "code": code,
                    "name": raw.get("name") or code,
                    "update_time": update,
                    "last_price": _safe_number(raw.get("last_price")) or 0.0,
                    "open_price": _safe_number(raw.get("reference_price_hkd") or raw.get("last_price")) or 0.0,
                    "high_price": _safe_number(raw.get("last_price")) or 0.0,
                    "low_price": _safe_number(raw.get("last_price")) or 0.0,
                    "prev_close_price": _safe_number(raw.get("prev_close_price")) or 0.0,
                    "turnover": _safe_number(raw.get("turnover")) or 0.0,
                    "volume": _safe_number(raw.get("volume")) or 0.0,
                    "bid_price": _safe_number(raw.get("bid_price")) or "",
                    "ask_price": _safe_number(raw.get("ask_price")) or "",
                    "bid_vol": _safe_number(raw.get("bid_vol")) or "",
                    "ask_vol": _safe_number(raw.get("ask_vol")) or "",
                    "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:15:00",
                    "window_end": update,
                    "bar_count": 1,
                    "temporal_cutoff_safe": True,
                    "target_date": plan.trade_date,
                    "signal_date": raw.get("signal_date") or "",
                    "rank": raw.get("rank") or "",
                    "auction_score": raw.get("auction_score") or raw.get("stage1_ref_score") or 0.0,
                    "second_filter_status": raw.get("second_filter_status") or "WATCH_ONLY",
                    "preselect_lane": raw.get("preselect_lane") or "",
                    "reference_price_hkd": raw.get("reference_price_hkd") or raw.get("last_price") or "",
                    "strict_failure_price_hkd": raw.get("strict_failure_price_hkd") or raw.get("bid_price") or "",
                })
        status = "READY" if rows else "CANNOT_CONFIRM"
        return SourceResult("hk_auction_second_filter", status, tuple(rows), requested_rows=len(codes), missing_symbols=tuple(sorted(set(codes) - {str(row["code"]) for row in rows})), cannot_confirm=() if rows else ("HK_0920_EXACT_SECOND_FILTER_ROWS_MISSING",), source_evidence=("route=hk_connect_0915_0920_auction_second_filter", "exact_date=true", f"second_filter_csv={csv_path}", f"second_filter_csv_sha256={_sha_file(csv_path)}"))
    return _collect_hk_0925_replay(
        plan,
        codes=codes,
        replay_provider=replay_provider,
    )


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
    if plan.stage_id == "STAGE_0925":
        return {
            "A_SHARE": lambda stage_plan, _market: collect_a_share_auction(
                stage_plan,
                codes=stage_plan.codes_for("A_SHARE"),
                python_path=python_path,
                shared_root=shared_root,
                auction_root=a_auction_root,
            ),
            "HK_CONNECT": lambda stage_plan, _market: collect_hk_auction(
                stage_plan,
                codes=stage_plan.codes_for("HK_CONNECT"),
                python_path=python_path,
                shared_root=shared_root,
                auction_root=hk_auction_root,
            ),
        }
    if plan.stage_id == "STAGE_1545_1555":
        # The final HK window has no A-share lane in the frozen contract.
        # Returning an A collector here makes the runner reject the stage
        # before it can publish the HK observation.
        replay_provider = None
        if hk_stage_replay_root is not None:
            from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider

            # The root is explicit and date/stage resolution remains inside
            # the provider.  No environment variable or cwd-based fallback is
            # allowed for the production Stage8 route.
            replay_provider = HkConnectStageReplayProvider(
                data_root=Path(hk_stage_replay_root).expanduser().resolve()
            )
        return {
            "HK_CONNECT": lambda stage_plan, _market: collect_hk_minute(
                stage_plan,
                codes=stage_plan.codes_for("HK_CONNECT"),
                python_path=python_path,
                shared_root=shared_root,
                replay_provider=replay_provider,
            ),
        }
    return {
        "A_SHARE": lambda stage_plan, _market: collect_a_share_hq_minute(
            stage_plan,
            codes=stage_plan.codes_for("A_SHARE"),
            python_path=python_path,
            shared_root=shared_root,
        ),
        "HK_CONNECT": lambda stage_plan, _market: collect_hk_minute(
            stage_plan,
            codes=stage_plan.codes_for("HK_CONNECT"),
            python_path=python_path,
            shared_root=shared_root,
        ),
    }


def production_selection_builders(
    stage_id: str,
    *,
    research_root: Path | str | None = None,
) -> dict[str, Callable[..., Mapping[str, Any]]]:
    """Build selection transforms from the package's frozen V3 pure formulas."""
    from .selection import select_a_0925_auction, select_a_stage, select_hk_0925_second_filter, select_hk_four_lane

    top10_contract_evidence = "selection_contract=V3_TOP10_RECOMMENDATION"
    research_stages = {
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }

    def a_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if stage_id == "STAGE_0925":
            rows = [
                {
                    "code": row.get("code"),
                    "name": row.get("name") or row.get("stock_name"),
                    "stock_name": row.get("stock_name") or row.get("name"),
                    "time": row.get("update_time"),
                    "amount": row.get("turnover"),
                    "open_price": row.get("open_price"),
                    "last_price": row.get("last_price"),
                    "high_price": row.get("high_price"),
                    "low_price": row.get("low_price"),
                    "update_time": row.get("update_time"),
                    "next_validation_time": raw.get("cutoff_at"),
                    "trade_date": plan.trade_date,
                }
                for row in source.rows
            ]
            return select_a_0925_auction(rows, plan.trade_date, str(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=tuple(dict.fromkeys((*raw["source_evidence"], *source.source_evidence, top10_contract_evidence))))
        research_context = None
        context_root = research_root or raw.get("_v4_research_data_root")
        if stage_id in research_stages and context_root is None:
            raise ValueError(
                f"V4 research data root is required for {stage_id} A_SHARE"
            )
        if stage_id in research_stages:
            from .research_context import ResearchContextError, load_research_context

            try:
                research_context = load_research_context(
                    context_root,
                    trade_date=plan.trade_date,
                    stage_cutoff=str(raw.get("cutoff_at") or ""),
                )
            except ResearchContextError:
                # The runner catches ValueError and publishes a fail-closed
                # receipt.  Never fall back to a current V4 score or a
                # future hourly slot when the frozen V3 evidence is invalid.
                raise
        rows = []
        for index, row in enumerate(source.rows, start=1):
            # ``select_a_live_stage`` is the Windows V3 authority.  Preserve
            # the exact qmt field names and amount/price semantics rather than
            # silently switching to the older minute-bar score.
            # A raw collector row is not a formal-pool authority.  The runner
            # marks rows only after its exact-date formal attach step has
            # verified membership; inherited ``formal_eligible`` values and
            # lane evidence remain untrusted source data.
            formal_overlay_verified = _has_runner_verified_formal_overlay(row)
            formal_value = row.get("formal_eligible", False)
            formal_eligible = formal_overlay_verified and str(formal_value).strip().lower() in {"true", "1", "yes"}
            lane_evidence = list(row.get("lane_evidence") or ())
            if formal_eligible:
                lane_evidence.append("A_SHARE_FORMAL_POOL")
            else:
                # The raw adapter may carry a stale formal marker.  Formal
                # identity is granted only by the exact-date authority
                # overlay, never by inherited source evidence.
                lane_evidence = [item for item in lane_evidence if item != "A_SHARE_FORMAL_POOL"]
                lane_evidence.append("STAGE_ACQUISITION_UNIVERSE")
            candidate_score = row.get("pool_score") if formal_eligible else None
            if candidate_score in (None, ""):
                candidate_score = None
            research = None
            if research_context is not None:
                code_key = _canonical_a_code(row.get("code") or row.get("stock_code"))
                research = research_context.by_code.get(code_key)
                if research is None:
                    # An exact-date archive that has no entry for a candidate
                    # code cannot prove a research value.  Keep that absence
                    # visible at the stage envelope instead of allowing the
                    # selection helper's numeric defaults to look observed.
                    research_context_gap = f"RESEARCH_CONTEXT_CODE_MISSING:{code_key or row.get('code')}"
                else:
                    missing_fields = tuple(
                        field
                        # Delta is explanatory metadata, not an input to
                        # selection.py's unchanged two-score bonus formula.
                        # Its absence remains in context.cannot_confirm.
                        for field in (
                            "news_quality_score",
                            "research_quality_score",
                        )
                        if getattr(research, field) is None
                    )
                    research_context_gap = (
                        f"RESEARCH_CONTEXT_FIELDS_MISSING:{code_key or row.get('code')}:{','.join(missing_fields)}"
                        if missing_fields
                        else None
                    )
            else:
                research_context_gap = None
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "formal_eligible": formal_eligible,
                "formal_rank": row.get("formal_rank", "") if formal_eligible else "",
                "candidate": {"score": candidate_score},
                "qmt": {
                    "open": row.get("open_price"),
                    "lastPrice": row.get("last_price"),
                    "lastClose": row.get("prev_close_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "amount": row.get("turnover"),
                    "bidVol": [row.get("bid_vol")],
                    "askVol": [row.get("ask_vol")],
                },
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
                "lane_evidence": list(dict.fromkeys((*lane_evidence, "PYTDX_EXACT_STAGE_ADAPTER"))),
                "acquisition_rank": row.get("acquisition_rank", row.get("batch_index", index)),
                "news_quality_score": research.news_quality_score if research is not None else None,
                "research_quality_score": research.research_quality_score if research is not None else None,
                "latest_research_slot": research.latest_research_slot if research is not None else "",
                "research_delta_hits": research.research_delta_hits if research is not None else None,
                "news_research_reason": "；".join(research.news_research_reason) if research is not None else "",
                "source_health": research.source_health if research is not None else "CANNOT_CONFIRM",
                "_research_context_gap": research_context_gap,
            })
        from .selection import _selection_identity_ids, select_a_live_stage
        research_evidence = research_context.source_evidence if research_context is not None else ()
        formal_overlay_supplied = any(_has_runner_verified_formal_overlay(row) for row in source.rows)
        context_gaps = list(research_context.cannot_confirm if research_context is not None else ())
        if not formal_overlay_supplied:
            context_gaps.append("FORMAL_OVERLAY_CANNOT_CONFIRM")
        context_gaps.extend(
            str(row["_research_context_gap"])
            for row in rows
            if row.get("_research_context_gap")
        )
        source_status = (
            "CANNOT_CONFIRM"
            if context_gaps
            else raw["status"]
        )
        formal_evidence = (
            "formal_overlay=EXACT_DATE_AUTHORITY"
            if formal_overlay_supplied
            else "formal_overlay=CANNOT_CONFIRM"
        )
        envelope = select_a_live_stage(rows, plan.trade_date, plan.stage_id, str(raw["artifact_sha256"]), source_status=source_status, requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=tuple(dict.fromkeys((*raw["cannot_confirm"], *context_gaps))), source_evidence=tuple(dict.fromkeys((*raw["source_evidence"], *source.source_evidence, *research_evidence, formal_evidence, top10_contract_evidence))))
        original_by_code = {
            str(row.get("code") or row.get("stock_code") or "").strip().upper(): row
            for row in rows
        }
        for selected in envelope.get("rows", ()):
            original = original_by_code.get(
                str(selected.get("code") or selected.get("stock_code") or "").strip().upper()
            )
            if original is None or not original.get("_research_context_gap"):
                continue
            # ``select_a_live_stage`` retains its historical numeric scoring
            # formula, but a missing research scalar must not be serialized as
            # an observed zero in the fail-closed envelope.
            for field in (
                "news_quality_score",
                "research_quality_score",
                "research_delta_hits",
                "latest_research_slot",
                "news_research_reason",
                "source_health",
            ):
                selected[field] = original.get(field)
            selected["research_bonus"] = None
            selected.pop("_research_context_gap", None)
        for row in rows:
            row.pop("_research_context_gap", None)
        # The projection above changes the serialized rows after
        # ``select_a_live_stage`` has initially calculated its identity.  Bind
        # the existing immutable identity helper to the final rows so the
        # publisher and reader validate exactly the bytes being published.
        artifact_id, run_id = _selection_identity_ids(
            plan.trade_date,
            plan.stage_id,
            "A_SHARE",
            str(envelope["raw_artifact_sha256"]),
            str(envelope["algorithm_sha256"]),
            list(envelope.get("rows") or ()),
        )
        envelope["artifact_id"] = artifact_id
        envelope["run_id"] = run_id
        return envelope

    def hk_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        rows = []
        d1_evidence: list[str] = list(source.source_evidence)
        for row in source.rows:
            previous = _safe_number(row.get("prev_close_price"))
            last = _safe_number(row.get("last_price"))
            pct = ((last - previous) / previous * 100.0) if previous and last is not None else None
            # The acquisition row does not assert a lane.  The runner adds
            # D-1/second-filter metadata before invoking this transform; an
            # empty lane list therefore stays empty and cannot become a
            # fabricated LIVE_HKCONNECT_GAINER.
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "candidate_lanes": list(row.get("candidate_lanes") or ()),
                "candidate_bucket": row.get("candidate_bucket", ""),
                "trade_status_contract": row.get("trade_status_contract", ""),
                "second_filter_rank": row.get("second_filter_rank", ""),
                "second_filter_score": row.get("second_filter_score", ""),
                "second_filter_status": row.get("second_filter_status", ""),
                "second_filter_action_level": row.get("second_filter_action_level", ""),
                "pct_chg": pct,
                "turnover": row.get("turnover"),
                "turnover_hkd": row.get("turnover"),
                "volume_ratio": row.get("volume_ratio"),
                "turnover_rate": row.get("turnover_rate"),
                "platform_circular_market_cap_hkd_yi": row.get("platform_circular_market_cap_hkd_yi"),
                "offer_float_market_cap_hkd_yi": row.get("offer_float_market_cap_hkd_yi"),
                "stage_window_change_pct": row.get("stage_window_change_pct"),
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "stage_id": plan.stage_id,
                # These fields are copied from the exact-date D-1 authority
                # by the runner. They remain selection-envelope metadata and
                # never alter the four-lane score.
                "d1_status": row.get("d1_status", row.get("strict_0_2_status", "")),
                "d1_model_id": row.get("d1_model_id", row.get("model_id", row.get("model", ""))),
                "d1_prob_active": row.get("d1_prob_active", row.get("prob_active", "")),
                "d1_rank": row.get("d1_rank", row.get("pool_rank", row.get("rank", ""))),
                "d1_score": row.get("d1_score", row.get("pool_score", row.get("score", ""))),
                "d1_source_evidence": list(row.get("d1_source_evidence") or ()),
            })
            model_id = rows[-1].get("d1_model_id")
            d1_status = rows[-1].get("d1_status")
            if model_id:
                d1_evidence.append(f"hk_d1_model_id={model_id}")
            if d1_status:
                d1_evidence.append(f"hk_d1_status={d1_status}")
            d1_evidence.extend(str(item) for item in rows[-1]["d1_source_evidence"] if str(item))
        d1_evidence = list(dict.fromkeys(d1_evidence))
        # Full-market ExHQ rows alone do not prove a V3 lane.  Inactive rows
        # remain in raw acquisition for coverage, but are excluded from the
        # selection-only copy.  This preserves the old V3 behavior where the
        # live trigger defines the minute candidate set rather than allowing a
        # single inactive member to erase otherwise verified active rows.
        if stage_id == "STAGE_0925":
            active_rows = [item for item in rows if item["candidate_lanes"]]
        else:
            active_rows = [
                item
                for item in rows
                if "LIVE_HKCONNECT_GAINER" in item["candidate_lanes"]
            ]
        if not active_rows:
            if (
                rows
                and source.status == "PARTIAL_WITH_ROWS"
                and "active_snapshot_degraded_to_pytdx_observation=true"
                in source.source_evidence
            ):
                # This is the established historical observation contract: the
                # exact raw rows are useful for a Top-10 watch list even when
                # the live snapshot cutoff is unsafe.  Do not manufacture a
                # LIVE_HKCONNECT_GAINER lane or refresh the snapshot here.
                return select_hk_four_lane(
                    rows,
                    plan.trade_date,
                    plan.stage_id,
                    str(raw["artifact_sha256"]),
                    source_status="PARTIAL_WITH_ROWS",
                    requested_rows=raw.get("requested_rows", source.requested_rows),
                    missing_symbols=tuple(
                        dict.fromkeys(
                            (
                                *source.missing_symbols,
                                *raw.get("missing_symbols", ()),
                            )
                        )
                    ),
                    cannot_confirm=tuple(
                        dict.fromkeys(
                            (
                                *source.cannot_confirm,
                                *raw.get("cannot_confirm", ()),
                            )
                        )
                    ),
                    source_evidence=tuple(
                        dict.fromkeys(
                            (
                                *raw.get("source_evidence", ()),
                                *source.source_evidence,
                                *d1_evidence,
                                top10_contract_evidence,
                                "hk_lane_authority_missing",
                                "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
                            )
                        )
                    ),
                )
            return select_hk_four_lane(
                [],
                plan.trade_date,
                plan.stage_id,
                str(raw["artifact_sha256"]),
                source_status="CANNOT_CONFIRM",
                requested_rows=raw.get("requested_rows"),
                missing_symbols=raw.get("missing_symbols", ()),
                cannot_confirm=(*raw.get("cannot_confirm", ()), "HK_LANE_EVIDENCE_MISSING"),
                source_evidence=(*raw.get("source_evidence", ()), *d1_evidence, top10_contract_evidence, "hk_lane_authority_missing"),
            )
        if len(active_rows) < len(rows):
            missing = tuple(dict.fromkeys((*raw.get("missing_symbols", ()), *(str(item.get("code")) for item in rows if not item["candidate_lanes"]))))
            return select_hk_four_lane(
                active_rows,
                plan.trade_date,
                plan.stage_id,
                str(raw["artifact_sha256"]),
                source_status="PARTIAL_WITH_ROWS",
                requested_rows=raw.get("requested_rows"),
                missing_symbols=missing,
                cannot_confirm=raw.get("cannot_confirm", ()),
                source_evidence=tuple(dict.fromkeys((*raw.get("source_evidence", ()), *d1_evidence, top10_contract_evidence))),
            )
        if stage_id == "STAGE_0925":
            return select_hk_0925_second_filter(rows, plan.trade_date, str(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=tuple(dict.fromkeys((*raw["source_evidence"], *d1_evidence, top10_contract_evidence))))
        final_rows = active_rows if stage_id == "STAGE_1545_1555" else rows
        return select_hk_four_lane(final_rows, plan.trade_date, plan.stage_id, str(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=tuple(dict.fromkeys((*raw["source_evidence"], *d1_evidence, top10_contract_evidence))))

    if stage_id == "STAGE_1545_1555":
        return {"HK_CONNECT": hk_builder}
    return {"A_SHARE": a_builder, "HK_CONNECT": hk_builder}


__all__ = ["collect_a_share_auction", "collect_a_share_hq_minute", "collect_a_share_minute", "collect_hk_auction", "collect_hk_minute", "production_collectors", "production_selection_builders"]
