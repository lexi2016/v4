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


def read_hk_0925_0930_substitute_inputs(
    *,
    raw_store_root: Path | str,
    source_run_id: str,
    expected_raw_artifact_sha256: str,
    d1_ranked_rows_path: Path | str,
    expected_d1_ranked_rows_sha256: str,
    d1_candidate_receipt_path: Path | str,
    expected_d1_candidate_receipt_sha256: str,
    trade_date: str,
) -> dict[str, Any]:
    """Read the exact saved 09:30-09:35 source for the 20261009 09:25 reference.

    This is a reader for an already verified Stage0930 raw run; it makes no
    provider call and never writes the source artifact.  The caller must opt
    into the one historical date and provide the original D1 Top100 receipt.
    Missing or malformed member rows are isolated and returned as diagnostics.
    """
    from stage_center.raw_store import RawStore

    if trade_date != "20261009":
        raise ValueError("HK 09:30 substitute is restricted to historical trade_date 20261009")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_raw_artifact_sha256)):
        raise ValueError("expected raw artifact SHA256 is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_d1_ranked_rows_sha256)):
        raise ValueError("expected D1 ranked rows SHA256 is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_d1_candidate_receipt_sha256)):
        raise ValueError("expected D1 candidate receipt SHA256 is invalid")

    ranked_path = Path(d1_ranked_rows_path).expanduser().resolve()
    candidate_receipt_path = Path(d1_candidate_receipt_path).expanduser().resolve()
    if _sha_file(ranked_path) != expected_d1_ranked_rows_sha256:
        raise ValueError("D1 ranked rows physical SHA mismatch")
    if _sha_file(candidate_receipt_path) != expected_d1_candidate_receipt_sha256:
        raise ValueError("D1 candidate receipt physical SHA mismatch")
    ranked_rows = json.loads(ranked_path.read_text(encoding="utf-8"))
    d1_receipt = json.loads(candidate_receipt_path.read_text(encoding="utf-8"))
    if not isinstance(ranked_rows, list) or len(ranked_rows) != 100:
        raise ValueError("D1 ranked rows must contain exactly 100 rows")
    identity = d1_receipt.get("input_identity")
    if (
        d1_receipt.get("schema_version") != "v4.hk_0_2_score_candidate_receipt.v1"
        or d1_receipt.get("status") != "CANDIDATE_ONLY_CANNOT_CONFIRM"
        or d1_receipt.get("target_date") != trade_date
        or d1_receipt.get("signal_date") != "20261008"
        or d1_receipt.get("score_rows") != 100
        or d1_receipt.get("unique_score_codes") != 100
        or d1_receipt.get("row_output_sha256") != expected_d1_ranked_rows_sha256
        or not isinstance(identity, Mapping)
        or identity.get("eligibility_status") != "RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED"
        or d1_receipt.get("RESEARCH_ONLY") is not True
        or d1_receipt.get("production_allowed") is not False
        or d1_receipt.get("buy_gate_updated") is not False
        or d1_receipt.get("orders_sent") is not False
    ):
        raise ValueError("D1 candidate receipt identity/provenance mismatch")

    d1_by_code: dict[str, Mapping[str, Any]] = {}
    for row in ranked_rows:
        if not isinstance(row, Mapping):
            raise ValueError("D1 ranked row is malformed")
        code = _canonical_hk_code(row.get("code"))
        rank = _safe_number(row.get("rank"))
        if (
            not code
            or code in d1_by_code
            or str(row.get("target_date") or "").replace("-", "") != trade_date
            or str(row.get("signal_date") or "").replace("-", "") != "20261008"
            or rank is None
            or int(rank) < 1
            or int(rank) > 100
        ):
            raise ValueError("D1 ranked rows are not a unique 20261009 candidate Top100")
        d1_by_code[code] = row
    if len(d1_by_code) != 100 or {int(_safe_number(row.get("rank")) or 0) for row in ranked_rows} != set(range(1, 101)):
        raise ValueError("D1 ranked rows do not bind ranks 1 through 100")

    store_root = Path(raw_store_root).expanduser().resolve()
    verified = RawStore(store_root).verify_run(
        trade_date,
        "STAGE_0930_0935",
        "HK_CONNECT",
        source_run_id,
    )
    source_manifest = json.loads((store_root / str(verified["manifest_relative"])).read_text(encoding="utf-8"))
    source_receipt = json.loads((store_root / str(verified["receipt_relative"])).read_text(encoding="utf-8"))
    if (
        verified.get("artifact_sha256") != expected_raw_artifact_sha256
        or verified.get("source_id") != "pytdx_exhq"
        or verified.get("source_status") != "PARTIAL_WITH_ROWS"
        or verified.get("status") != "PARTIAL_WITH_ROWS"
        or verified.get("role") != "HK_CONNECT_1MIN_STAGE_0930_0935"
        or verified.get("requested_rows") != 695
        or verified.get("source_rows") != 695
        or verified.get("window") != "09:30-09:35"
        or verified.get("cutoff_at") != "09:35:05"
        or source_manifest.get("temporal_cutoff_safe") is not False
        or source_receipt.get("temporal_cutoff_safe") is not False
    ):
        raise ValueError("saved Stage0930 raw run identity/cutoff provenance mismatch")

    artifact_path = store_root / str(verified["artifact_relative"])
    with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    if len(raw_rows) != 695:
        raise ValueError("verified Stage0930 raw artifact row count mismatch")
    raw_by_code: dict[str, list[Mapping[str, Any]]] = {}
    for row in raw_rows:
        code = _canonical_hk_code(row.get("code"))
        if code in d1_by_code:
            raw_by_code.setdefault(code, []).append(row)

    selected_rows: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    row_issues: list[str] = []
    for code, d1_row in sorted(d1_by_code.items(), key=lambda item: int(_safe_number(item[1].get("rank")) or 0)):
        candidates = raw_by_code.get(code, [])
        if len(candidates) != 1:
            missing_symbols.append(code)
            row_issues.append(f"HK_0930_SUBSTITUTE_RAW_ROW_COUNT:{code}:{len(candidates)}")
            continue
        raw = dict(candidates[0])
        expected_window = (
            raw.get("trade_date") == trade_date
            and raw.get("bar_time") == "09:35:00"
            and raw.get("update_time") == "2026-10-09 09:35:00"
            and raw.get("window_start") == "2026-10-09 09:31:00"
            and raw.get("window_end") == "2026-10-09 09:35:00"
            and _safe_number(raw.get("bar_count")) == 5
        )
        price_fields = ("open_price", "last_price", "high_price", "low_price", "prev_close_price")
        if not expected_window or any((_safe_number(raw.get(field)) or 0.0) <= 0 for field in price_fields):
            missing_symbols.append(code)
            row_issues.append(f"HK_0930_SUBSTITUTE_RAW_ROW_INVALID:{code}")
            continue
        name = str(d1_row.get("name") or "").strip()
        selected_rows.append({
            **raw,
            "code": code,
            "name": name,
            "stock_name": name,
            "candidate_lanes": [],
            "d1_status": "RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
            "d1_model_id": str(d1_row.get("selected_strategy") or "prob_active"),
            "d1_prob_active": d1_row.get("score_prob_active"),
            "d1_rank": d1_row.get("rank"),
            "d1_score": d1_row.get("hybrid_score"),
            "d1_source_evidence": [
                "d1_membership=RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
                f"d1_ranked_rows_sha256={expected_d1_ranked_rows_sha256}",
            ],
        })

    captured_at = ""
    for item in source_manifest.get("source_evidence", ()):
        if str(item).startswith("research_source="):
            try:
                captured_at = str(json.loads(str(item).split("=", 1)[1]).get("captured_at") or "")
            except (TypeError, ValueError):
                captured_at = ""
            break
    evidence = [
        "substitute_kind=HK_0930_0935_FOR_HK_0925",
        "substitute_label=09:30-09:35开盘数据替代补算",
        "substitute_selection_algorithm_stage=STAGE_0930_0935",
        f"source_stage_id={verified['stage_id']}",
        f"source_window={verified['window']}",
        "source_last_bar_time=2026-10-09 09:35:00",
        f"source_raw_run_id={source_run_id}",
        f"source_raw_artifact_sha256={verified['artifact_sha256']}",
        f"source_raw_manifest_sha256={verified['manifest_sha256']}",
        f"source_raw_receipt_sha256={verified['receipt_sha256']}",
        f"source_requested_rows={verified['requested_rows']}",
        f"source_rows={verified['source_rows']}",
        "source_manifest_temporal_cutoff_safe=false",
        "target_stage_temporal_cutoff_safe=false",
        f"source_captured_at={captured_at}" if captured_at else "source_captured_at=CANNOT_CONFIRM",
        f"d1_target_date={trade_date}",
        "d1_signal_date=20261008",
        f"d1_ranked_rows_sha256={expected_d1_ranked_rows_sha256}",
        f"d1_candidate_receipt_sha256={expected_d1_candidate_receipt_sha256}",
        "d1_membership_status=RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
        "source_market=HK_CONNECT",
    ]
    evidence.extend(str(item) for item in verified.get("source_evidence", ()) if str(item))
    cannot_confirm = [
        *verified.get("cannot_confirm", ()),
        *row_issues,
        "HK_0920_EXACT_AUCTION_UNAVAILABLE",
        "HK_0925_REPLACED_BY_0930_0935_RESEARCH_ONLY",
        "HK_0930_CAPTURE_AFTER_STAGE_0925_CUTOFF",
        "HK_D1_MEMBERSHIP_PIT_UNVERIFIED",
    ]
    if not captured_at:
        cannot_confirm.append("HK_0930_SOURCE_CAPTURE_TIME_CANNOT_CONFIRM")
    return {
        "trade_date": trade_date,
        "stage_id": "STAGE_0925",
        "source_stage_id": "STAGE_0930_0935",
        "source_run_id": source_run_id,
        "raw_artifact_sha256": verified["artifact_sha256"],
        "requested_rows": 100,
        "source_rows": len(selected_rows),
        "rows": tuple(selected_rows),
        "missing_symbols": tuple(missing_symbols),
        "source_status": "PARTIAL_WITH_ROWS" if selected_rows else "CANNOT_CONFIRM",
        "cannot_confirm": tuple(dict.fromkeys(str(item) for item in cannot_confirm if str(item))),
        "source_evidence": tuple(dict.fromkeys(evidence)),
        "source_capture_time": captured_at,
        "source_temporal_cutoff_safe": False,
        "d1_ranked_rows_sha256": expected_d1_ranked_rows_sha256,
        "d1_candidate_receipt_sha256": expected_d1_candidate_receipt_sha256,
    }


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
