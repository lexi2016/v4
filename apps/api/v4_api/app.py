from datetime import datetime
import hashlib
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import BoundedSemaphore
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apps.api.v4_api.baimao_router import create_baimao_router
from apps.api.v4_api.preselection_router import create_preselection_router
from apps.api.v4_api.preselection_service import PreselectionPoolService
from apps.api.v4_api.research_lane_router import create_research_lane_router
from apps.api.v4_api.runtime_router import create_runtime_router
from apps.api.v4_api.runtime_graph_router import create_runtime_graph_router
from apps.api.v4_api.review_router import create_review_router
from apps.api.v4_api.manual_collection_router import create_manual_collection_router
from apps.api.v4_api.research_router import create_research_router
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains.preselection import date_catalog
from domains.stage_input_producer import ReadOnlyQuoteProvider, StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.review_store import ReviewStore
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
from stage_center.consumer import StageSelectionConsumer
from stage_center.research_read_binding import ApprovedResearchReadBinding, ResearchReadError
from apps.api.v4_api.evidence.loader import (
    row_dicts as _evidence_row_dicts,
    tuple_keyed as _evidence_tuple_keyed,
    tagged_value as _evidence_tagged,
    tuple_rows as _evidence_tuple_rows,
)
from apps.api.v4_api.projection import ProjectionContext, project_shared_selection
from apps.api.v4_api.stage_workbench import StageWorkbenchContext, read_stage_workbench

_STAGE_RESEARCH_READER_SHA256 = "c33a1452df34c7dcc7fc96e61b1177079c54c467164b7cb957d773f2d2e0ba05"


# One process-wide pool and admission limit: timed-out reads cannot spawn a
# new pool per request or leave an unbounded queue behind stalled readers.
_STAGE_BATCH_CAPACITY = 8
_stage_batch_executor = ThreadPoolExecutor(
    max_workers=_STAGE_BATCH_CAPACITY, thread_name_prefix="v4-stage-batch"
)
_stage_batch_slots = BoundedSemaphore(_STAGE_BATCH_CAPACITY)


def _bounded_stage_summaries(read_summary, ordered, *, workers, timeout_seconds):
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    slots = _stage_batch_slots
    pending = {}
    remaining = iter(ordered)
    summaries = {}
    exhausted = False
    try:
        while time.monotonic() < deadline:
            while not exhausted and len(pending) < workers and time.monotonic() < deadline:
                if not slots.acquire(blocking=False):
                    break
                try:
                    stage_id = next(remaining)
                except StopIteration:
                    slots.release()
                    exhausted = True
                    break
                try:
                    future = _stage_batch_executor.submit(read_summary, stage_id)
                except BaseException:
                    slots.release()
                    raise
                future.add_done_callback(lambda _future: slots.release())
                pending[future] = stage_id
            if not pending:
                # Saturation is an incomplete read, never an invitation to
                # queue more work or to bypass the response deadline.
                break
            done, _ = wait(pending, timeout=max(0.0, deadline - time.monotonic()),
                           return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                del pending[future]
                name, summary = future.result()
                if summary is not None:
                    summaries[name] = summary
    finally:
        for future in pending:
            future.cancel()
    return summaries


_V4_STATE_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v4.local"
    / "state"
)
_CANONICAL_MANAGER_RESEARCH_STATE_ROOT = _V4_STATE_ROOT / "manager_auto_research"

_DAY25_HK0930_BACKFILL_RUN_ID = "55742332ec504f119a54c42ce9cad3cd"
_DAY25_HK0930_BINDING_KEY = (
    "20260925",
    "STAGE_0930_0935",
    "HK_CONNECT",
    _DAY25_HK0930_BACKFILL_RUN_ID,
)
_APPROVED_EXACT_STAGE_BACKFILLS = _evidence_tagged("approved_exact_stage_backfills")

_DAY24_HK0930_BACKFILL_RUN_ID = "1d3ab9f9bd3a44c3811bf1fed2b74108"


# BEGIN MONTH_HK_AFTERFACT_R5_API_BINDINGS
_MONTH_HK_AFTERFACT_R5_BINDINGS = _evidence_row_dicts("hk_afterfact_r5_bindings")
# END MONTH_HK_AFTERFACT_R5_API_BINDINGS


# R8 uses immutable exact-target D1 evidence for all affected date/stage cells.
# The source artifacts remain research-only; these bindings do not update shared pointers.
_MONTH_HK_AFTERFACT_R8_BINDING_ROWS = _evidence_tuple_rows("hk_afterfact_r8_binding_rows")
_HK_R8_POOL_EVIDENCE = _evidence_tagged("hk_r8_pool_evidence")
_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE = _evidence_tuple_keyed("hk_r8_observation_mode")
_HK_R8_COMMON_REQUIRED_EVIDENCE = _evidence_tagged("hk_r8_common_required_evidence")

def _hk_r8_required_evidence(
    trade_date: str,
    stage_id: str,
    pool: Mapping[str, str],
    source_page_set_sha256: str,
    observation_mode_sha256: str,
) -> tuple[str, ...]:
    if _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE.get((trade_date, stage_id)) != observation_mode_sha256:
        raise ValueError(f"R8 observation contract digest is not bound to {trade_date}/{stage_id}")
    pool_path = _V4_STATE_ROOT / "data" / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
    required = [
        *_HK_R8_COMMON_REQUIRED_EVIDENCE,
        f"historical_price_signal_date={pool['price_signal_date']}",
        f"historical_source_page_set_sha256={source_page_set_sha256}",
        f"historical_pool_artifact_path={pool_path}",
        f"historical_pool_artifact_sha256={pool['pool_sha256']}",
        f"stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:{observation_mode_sha256}",
        f"hk_d1_source_trade_date={pool['source_date']}",
        f"hk_d1_source_signal_date={pool['signal_date']}",
        f"hk_d1_binding_sha256={pool['pool_sha256']}",
        f"hk_d1_sha256={pool['pool_sha256']}",
        f"candidate_current_sha256={pool['pool_sha256']}",
        f"candidate_run_id={pool['source_run_id']}",
        f"hk_d1_json={pool_path}",
        f"hk_d1_json_sha256={pool['pool_sha256']}",
        f"hk_d1_source_sha256={pool['pool_source_sha256']}",
        "HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE",
        "HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
        "HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
    ]
    if trade_date == "20261005":
        required.extend((
            "hk_d1_binding_mode=MANIFEST_BOUND_AFTERFACT_EXACT_TARGET_DATE",
            f"hk_afterfact_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:{observation_mode_sha256}",
        ))
    return tuple(required)

_MONTH_HK_AFTERFACT_R8_BINDINGS = tuple(
    {
        "date": date,
        "stage_id": stage_id,
        "market": "HK_CONNECT",
        "backfill_run_id": backfill_run_id,
        "selection_run_id": selection_run_id,
        "artifact_id": artifact_id,
        "raw_artifact_sha256": raw_artifact_sha256,
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "selected_rows": 10,
        "source_rows": 100,
        "cannot_confirm_count": 3,
        "selection_manifest_sha256": manifest_sha256,
        "selection_receipt_sha256": selection_receipt_sha256,
        "selection_artifact_sha256": selection_artifact_sha256,
        "runner_receipt_sha256": runner_receipt_sha256,
        "observation_mode_sha256": _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE[(date, stage_id)],
        "required_evidence": _hk_r8_required_evidence(
            date,
            stage_id,
            _HK_R8_POOL_EVIDENCE[date],
            source_page_set_sha256,
            _HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE[(date, stage_id)],
        ),
    }
    for (
        date, stage_id, backfill_run_id, selection_run_id, artifact_id,
        raw_artifact_sha256, manifest_sha256, selection_receipt_sha256,
        selection_artifact_sha256, runner_receipt_sha256, source_page_set_sha256,
    ) in _MONTH_HK_AFTERFACT_R8_BINDING_ROWS
)
_HK_R8_BINDING_BY_DATE_STAGE = {
    (item["date"], item["stage_id"]): item for item in _MONTH_HK_AFTERFACT_R8_BINDINGS
}

# Revoke the 10/05 15:45 R5 wrapper: it was bound to the 09/30 pool.
# Its immutable artifact and receipt remain available in the original evidence store.
_REVOKED_HK_STAGE_BACKFILL_KEYS = _evidence_tagged("revoked_hk_stage_backfill_keys")


# R9 adds 87 exact target-pool after-fact observation bindings. The source
# artifacts are immutable evidence candidates; ordinary reads compose them
# read-only and never publish to shared selection pointers.
_HK_R9_POOL_EVIDENCE = _evidence_tagged("hk_r9_pool_evidence")
_MONTH_HK_AFTERFACT_R9_STAGE_ROWS = _evidence_row_dicts("hk_afterfact_r9_stage_rows")

def _hk_r9_required_evidence(row: Mapping[str, Any], pool: Mapping[str, str]) -> tuple[str, ...]:
    required = [
        "buy_gate_updated=false",
        "historical_capture_after_target_cutoff=true",
        f"historical_capture_batch_receipt_sha256={row['capture_batch_receipt_sha256']}",
        "historical_formal_stage_eligibility=CANNOT_CONFIRM",
        "historical_natural_time_capture=CANNOT_CONFIRM",
        "historical_pit_safe=false",
        f"historical_price_signal_date={pool['signal_date']}",
        "historical_provider=pytdx_exhq",
        f"historical_source_page_set_sha256={row['source_page_set_sha256']}",
        "historical_temporal_cutoff_safe=false",
        "orders_sent=false",
        "production_allowed=false",
        f"historical_target_pool_code_set_sha256={pool['code_set_sha256']}",
        f"historical_capture_observed_pool_codes={row['observed_rows']}",
        f"historical_capture_missing_pool_codes={row['missing_rows']}",
        f"historical_pool_artifact_path={pool['pool_path']}",
        f"historical_pool_artifact_sha256={pool['pool_sha256']}",
        f"stage_center_observation_mode={row['observation_mode_marker']}",
        "due_status=HISTORICAL_BACKFILL",
        "historical_observation_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1",
        f"hk_d1_source_trade_date={pool['source_date']}",
        f"hk_d1_source_signal_date={pool['signal_date']}",
        f"hk_d1_binding_sha256={pool['pool_sha256']}",
        f"hk_d1_sha256={pool['pool_sha256']}",
        f"candidate_current_sha256={pool['pool_sha256']}",
        f"candidate_run_id={pool['source_run_id']}",
        f"hk_d1_json={pool['pool_path']}",
        "hk_d1_membership=exact_date_top100",
        "hk_acquisition_scope=EXACT_D1_TOP100",
        "hk_d1_status=STRICT_0_2_READY",
        f"hk_d1_json_sha256={pool['pool_sha256']}",
        f"hk_d1_source_sha256={pool['source_sha256']}",
        "selection_contract=V3_TOP10_RECOMMENDATION",
        "selection_mode=RESEARCH_ONLY",
        "historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY",
        "observation_status=OBSERVATION_UNVERIFIED",
        "formal_stage_eligibility=CANNOT_CONFIRM",
        "natural_time_capture=CANNOT_CONFIRM",
        "formal_pit=false",
        "algorithm_sha256=fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
    ]
    if row["date"] == "20260907":
        required.append(
            f"historical_target_pool_artifact_sha256={pool['pool_sha256']}"
        )
    if row["date"] != "20260907":
        required.extend((
            f"historical_target_d1_manifest_sha256={pool['pool_manifest_sha256']}",
            f"historical_target_d1_receipt_sha256={pool['pool_receipt_sha256']}",
        ))
    required.extend(row["missing_evidence_markers"])
    return tuple(required)

_MONTH_HK_AFTERFACT_R9_BINDINGS = tuple(
    {
        **row,
        "market": "HK_CONNECT",
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "source_rows": row["source_rows"],
        "required_evidence": _hk_r9_required_evidence(
            row, _HK_R9_POOL_EVIDENCE[row["date"]]
        ),
        "pool_artifact_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_sha256"],
        "pool_manifest_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_manifest_sha256"],
        "pool_receipt_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_receipt_sha256"],
        "pool_code_set_sha256": _HK_R9_POOL_EVIDENCE[row["date"]]["code_set_sha256"],
        "pool_path": _HK_R9_POOL_EVIDENCE[row["date"]]["pool_path"],
        "pool_signal_date": _HK_R9_POOL_EVIDENCE[row["date"]]["signal_date"],
    }
    for row in _MONTH_HK_AFTERFACT_R9_STAGE_ROWS
)
_HK_R9_BINDING_BY_DATE_STAGE = {
    (item["date"], item["stage_id"]): item
    for item in _MONTH_HK_AFTERFACT_R9_BINDINGS
}

_HK_MORNING_SELECTION_RECOVERY_REQUIRED_EVIDENCE = _evidence_tagged("hk_morning_selection_recovery_required_evidence")
_HK_MORNING_SELECTION_RECOVERY_ROWS = _evidence_tagged("hk_morning_selection_recovery_rows")
_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE = {
    ("20261016", row["stage_id"]): {
        **row,
        "market": "HK_CONNECT",
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "f2991c472b17742acfd3adb81458ff13826f99dfb7b8a223ad8d6a5dfbbd1a1e",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "CANNOT_CONFIRM",
        "requested_rows": 100,
        "source_rows": 100,
        "selected_rows": 10,
        "missing_rows": 0,
        "missing_codes": (),
        "cannot_confirm_count": 1,
        "required_evidence": _HK_MORNING_SELECTION_RECOVERY_REQUIRED_EVIDENCE,
    }
    for row in _HK_MORNING_SELECTION_RECOVERY_ROWS
}

# These nine legacy observations were captured from the live ordinary reader
# and its verified SelectionStore entries. Their HK D1 markers consistently
# identify a different pool from the exact target-date candidate below. Keep
# the compatibility boundary pinned to each old run, artifact, pool path, and
# SelectionStore manifest/receipt identity. In particular, candidate_current
# markers are intentionally not treated as HK D1 pool aliases.
_HK_R9_LEGACY_STALE_POOL_CONTRACTS = _evidence_tagged("hk_r9_legacy_stale_pool_contracts")
_HK_R9_LEGACY_STALE_LANE_IDENTITIES = _evidence_tagged("hk_r9_legacy_stale_lane_identities")
_HK_R9_LEGACY_STALE_POOL_KEYS = frozenset(_HK_R9_LEGACY_STALE_LANE_IDENTITIES)

def _resolve_exact_backfill_selection_root(selection_root: Path | str, run_id: str) -> Path:
    """Resolve one pinned run-scoped store without following namespace symlinks."""
    configured_root = Path(selection_root).expanduser()
    if configured_root.is_symlink():
        raise HTTPException(status_code=404, detail="backfill selection namespace is unavailable")
    try:
        root = configured_root.resolve(strict=True)
        backfill_root = root / "backfill"
        run_root = backfill_root / run_id
        if (
            not root.is_dir()
            or backfill_root.is_symlink()
            or backfill_root.resolve(strict=True) != backfill_root
            or not backfill_root.is_dir()
            or run_root.is_symlink()
            or run_root.resolve(strict=True) != run_root
            or run_root.resolve(strict=True).parent != backfill_root
            or not run_root.is_dir()
        ):
            raise HTTPException(status_code=404, detail="backfill selection run is unavailable")
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="backfill selection run is unavailable")
    return run_root


def _new_scoped_stage_selection_consumer(
    root: Path | str,
    shared_consumer: StageSelectionConsumer,
) -> StageSelectionConsumer:
    """Build a run-scoped consumer across supported release constructor names."""
    parameters = inspect.signature(StageSelectionConsumer).parameters
    accepts_keywords = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if "a_name_pool_root" in parameters or accepts_keywords:
        kwargs["a_name_pool_root"] = shared_consumer.a_name_pool_root
    else:
        raise TypeError("StageSelectionConsumer lacks a_name_pool_root support")

    receipt_root = shared_consumer.runner_receipt_root
    if "runner_receipt_root" in parameters:
        kwargs["runner_receipt_root"] = receipt_root
    elif "execution_receipt_root" in parameters:
        kwargs["execution_receipt_root"] = receipt_root
    elif accepts_keywords:
        kwargs["runner_receipt_root"] = receipt_root
    else:
        raise TypeError("StageSelectionConsumer lacks a runner receipt root parameter")
    return StageSelectionConsumer(root, **kwargs)


def _resolve_manager_research_state_root(
    manager_research_state_root: Path | str | None,
    data_root: Path | str | None,
) -> Path:
    """Resolve the manager lane below its one canonical state root.

    ``V4_DATA_ROOT`` points at the shared host data tree and is also passed as
    ``data_root`` by the live launcher.  The manager product has its own
    sibling state directory, so that host argument must not become a nested
    manager store.  A noncanonical explicit data root remains isolated for
    embedded tests and callers; the dedicated manager argument and env
    override always take precedence.
    """

    if manager_research_state_root is not None:
        return Path(manager_research_state_root)
    env_state_root = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    if env_state_root:
        return Path(env_state_root)
    if data_root is not None:
        explicit_data_root = Path(data_root).expanduser()
        if explicit_data_root.resolve() == (_V4_STATE_ROOT / "data").resolve():
            return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT
        return explicit_data_root / "manager_auto_research"
    return _CANONICAL_MANAGER_RESEARCH_STATE_ROOT


class _RevalidatingStaticFiles(StaticFiles):
    """Serve HTML entry points with revalidation, hashed assets as usual.

    A cached HTML document can reference a hashed asset that a later release
    no longer ships, so documents must be revalidated (``no-cache``) instead
    of being served from heuristic freshness; content-hashed assets keep
    their default caching because their names change with their bytes.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["cache-control"] = "no-cache"
        return response


def _strict_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from error
    return value



# Exact saved 20261023 observation inputs; this grants no formal/PIT eligibility.
_HK_MORNING_HISTORY_20261023 = _evidence_tagged("hk_morning_history_20261023")

_HK_MORNING_HISTORY_SAFE_PACKETS = _evidence_tagged("hk_morning_history_safe_packets")

def _hk_morning_history_observation(
    selection_root: Path | None, pool_root: Path, market_payload: Mapping[str, Any],
    rows: list[dict], *, trade_date: str, stage_id: str,
) -> dict[str, Any]:
    """Verify saved bars and original scorer output for the approved dated observation.

    Read only: no acquisition, scoring, repair or fallback. Bar labels and the
    late capture clock remain distinct from the requested stage cutoff.
    """
    import csv
    import io
    import json
    import math

    binding = _HK_MORNING_HISTORY_20261023.get(stage_id) if trade_date == "20261023" else None
    if binding is None or selection_root is None:
        return {}
    root = Path(selection_root).parent
    try:
        # Verify full immutable trios and the cache before interpreting any values.
        documents: dict[str, bytes] = {}
        for relative, expected in binding["files"].items():
            path = root / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return {}
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                return {}
            documents[relative] = raw
        manifest = json.loads(documents[binding["selection_manifest"]])
        envelope = manifest["selection_envelope"]
        for key in ("trade_date", "stage_id", "market", "run_id", "artifact_id",
                    "algorithm_id", "algorithm_sha256", "raw_artifact_sha256",
                    "selection_status", "source_status", "requested_rows", "source_rows",
                    "selected_rows", "missing_symbols", "cannot_confirm", "source_evidence"):
            if market_payload.get(key) != envelope.get(key):
                return {}
        if (envelope["trade_date"] != trade_date or envelope["stage_id"] != stage_id
                or envelope["market"] != "HK_CONNECT" or envelope["run_id"] != binding["run_id"]
                or market_payload.get("status") != "PARTIAL_WITH_ROWS"
                or envelope["selection_status"] != "PARTIAL_WITH_ROWS"
                or envelope["source_status"] != "CANNOT_CONFIRM"
                or envelope["cannot_confirm"] != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
                or envelope["missing_symbols"] or envelope["requested_rows"] != 100
                or envelope["source_rows"] != 100 or envelope["selected_rows"] != 10
                or len(rows) != 10):
            return {}
        # Consumer adds only the display order. All scorer values must be identical.
        if [{k: v for k, v in row.items() if k != "order"} for row in rows] != envelope["rows"]:
            return {}
        if any(row.get("formal_eligible") is not False or row.get("action_level") != "NO_BUY"
               or row.get("source_mode") != "HK_CONNECT_FOUR_LANE"
               or row.get("trade_status") not in {"NO_TRADE", "WATCH_ONLY"} for row in rows):
            return {}
        if any(envelope.get(key) is not False for key in
               ("production_allowed", "buy_gate_updated", "orders_sent")):
            return {}
        pool_bytes = (Path(pool_root) / "preselection_pools/20261023/hkconnect_d1_top100.json").read_bytes()
        if hashlib.sha256(pool_bytes).hexdigest() != "e8921f1eadf3cbac3d63fe2b012e5c9ac25652af08a68681886fc179b540dbef":
            return {}
        pool = json.loads(pool_bytes)
        codes = {row["code_norm"] for row in pool["rows"]}
        if (len(codes) != 100 or len(pool["rows"]) != 100 or pool["market"] != "HK"
                or pool["target_date"] != trade_date or pool["signal_date"] != "20261022"
                or pool["status"] != "STRICT_0_2_READY"):
            return {}
        capture = json.loads(documents[binding["capture_relative"]])
        if (capture["market"] != "HK_CONNECT" or capture["trade_date"] != trade_date
                or capture["stage_id"] != stage_id or capture["adjustment"] != "NONE"
                or capture["captured_at"] != binding["captured_at"]
                or capture["errors"] or capture["no_data_codes"]
                or len(capture["codes"]) != 100 or set(capture["codes"]) != codes):
            return {}
        cutoff = datetime.fromisoformat(binding["cutoff_at"])
        captured = datetime.fromisoformat(capture["captured_at"])
        # Bind the requested cutoff to the frozen stage definition, not caller data.
        if binding["cutoff_at"] != f"2026-10-23T{STAGE_DEFINITIONS[stage_id]['cutoff']}+08:00":
            return {}
        if captured <= cutoff:
            return {}
        raw_manifest = json.loads(documents[binding["raw_manifest"]])
        if (raw_manifest["trade_date"] != trade_date or raw_manifest["stage_id"] != stage_id
                or raw_manifest["market"] != "HK_CONNECT" or raw_manifest["source_id"] != "futu"
                or raw_manifest["temporal_cutoff_safe"] is not False
                or raw_manifest["artifact_sha256"] != envelope["raw_artifact_sha256"]):
            return {}
        safe = _HK_MORNING_HISTORY_SAFE_PACKETS[stage_id]
        packet_root = Path(selection_root) / "historical_observations/20261023" / stage_id
        packet: dict[str, bytes] = {}
        for relative, expected in safe["files"].items():
            path = packet_root / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return {}
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                return {}
            packet[relative] = raw
        from stage_center.selection import SelectionStore
        observed = SelectionStore(packet_root / "selection").read_verified(trade_date, stage_id, "HK_CONNECT")
        if (observed["run_id"] != safe["selection_run_id"] or len(observed["rows"]) != 10
                or observed["algorithm_sha256"] != envelope["algorithm_sha256"]
                or observed["source_status"] != "CANNOT_CONFIRM"
                or observed["selection_status"] != "PARTIAL_WITH_ROWS"
                or observed["requested_rows"] != 100 or observed["source_rows"] != 100
                or any(row.get("formal_eligible") is not False or row.get("action_level") != "NO_BUY"
                       for row in observed["rows"])
                or any(observed.get(key) is not False for key in
                       ("production_allowed", "buy_gate_updated", "orders_sent"))):
            return {}
        bars = {code: [] for code in codes}
        for bar in capture["rows"]:
            if safe["window_start"] <= bar["time_key"] <= safe["window_end"]:
                if bar["code"] not in codes:
                    return {}
                if any(not math.isfinite(float(bar[key])) for key in
                       ("open", "high", "low", "close", "volume", "turnover", "last_close")):
                    return {}
                bars[bar["code"]].append(bar)
        raw_rows = list(csv.DictReader(io.StringIO(packet["derived_raw.csv"].decode("utf-8-sig"))))
        if len(raw_rows) != 100 or {row["code"] for row in raw_rows} != codes:
            return {}
        for raw_row in raw_rows:
            code_bars = sorted(bars[raw_row["code"]], key=lambda bar: bar["time_key"])
            if (len(code_bars) != safe["bars_per_code"]
                    or len({bar["time_key"] for bar in code_bars}) != len(code_bars)
                    or code_bars[0]["time_key"] != safe["window_start"]
                    or code_bars[-1]["time_key"] != safe["window_end"]
                    or raw_row["trade_date"] != trade_date
                    or raw_row["window_start"] != safe["window_start"]
                    or raw_row["window_end"] != safe["window_end"]
                    or int(raw_row["bar_count"]) != len(code_bars)):
                return {}
            aggregate = {
                "open_price": code_bars[0]["open"], "last_price": code_bars[-1]["close"],
                "high_price": max(bar["high"] for bar in code_bars),
                "low_price": min(bar["low"] for bar in code_bars),
                "volume": sum(bar["volume"] for bar in code_bars),
                "turnover": sum(bar["turnover"] for bar in code_bars),
            }
            if any(not math.isclose(float(raw_row[key]), float(value), rel_tol=1e-9, abs_tol=1e-6)
                   for key, value in aggregate.items()):
                return {}
        return {
            "label": "早盘历史回放观察 / 缺失原时点盘口 / 非正式阶段结果",
            "source_id": "FUTU_K_1M", "raw_source_id": "futu", "adjustment": "NONE",
            "trade_date": trade_date, "stage_id": stage_id, "selection_run_id": observed["run_id"], "original_selection_run_id": binding["run_id"],
            "artifact_id": observed["artifact_id"], "raw_artifact_sha256": observed["raw_artifact_sha256"],
            "algorithm_id": observed["algorithm_id"], "algorithm_sha256": observed["algorithm_sha256"],
            "source_evidence": observed["source_evidence"],
            "_rows": [{**row, "order": index + 1} for index, row in enumerate(observed["rows"])],
            "capture_sha256": binding["capture_sha256"], "captured_at": capture["captured_at"],
            "asof_cutoff": binding["cutoff_at"], "captured_after_cutoff": True,
            "bar_label_start": safe["window_start"], "bar_label_end": safe["window_end"],
            "bar_interval_semantics": "CANNOT_CONFIRM", "stage_window_coverage": "CONSERVATIVE_INTERSECTION_ONLY", "boundary_bars_excluded": True,
            "bars_per_code": safe["bars_per_code"], "window_bar_count": sum(map(len, bars.values())),
            "d1_membership_count": 100, "formal_eligible": False, "natural": False,
            "active_snapshot_available": False, "temporal_cutoff_safe": False,
            "missing_fields": ["order_book", "volume_ratio", "native_update_time", "native_snapshot"],
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        return {}


_STAGE_TIMELINE_MARKET_KEYS = (
    "status",
    "display_mode",
    "source_status",
    "requested_rows",
    "source_rows",
    "selection_manifest_receipt_verified",
    "observation_count",
)


def _project_stage_timeline_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the fields the stage timeline renders.

    The summary is copied from the same projection the single-stage route
    returns, so the compact timeline payload and the full stage view cannot
    disagree. Stock rows, source evidence and the snapshot/evidence bodies are
    deliberately dropped: they were ~96% of each stage response.
    """
    markets = payload.get("markets")
    compact_markets: dict[str, dict[str, Any]] = {}
    if isinstance(markets, Mapping):
        for market in ("A", "HK"):
            summary = markets.get(market)
            if isinstance(summary, Mapping):
                compact_markets[market] = {
                    key: summary.get(key) for key in _STAGE_TIMELINE_MARKET_KEYS
                }

    def _snapshot_side(value: Any, rows_key: str) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        side: dict[str, Any] = {"status": value.get("status")}
        side_markets = value.get("markets")
        picked = side_markets.get("A_SHARE") if isinstance(side_markets, Mapping) else None
        if isinstance(picked, Mapping):
            side["markets"] = {
                "A_SHARE": {
                    key: picked.get(key)
                    for key in ("mode", rows_key, "captured_at")
                }
            }
        return side

    execution = payload.get("execution_evidence")
    compact_execution = None
    if isinstance(execution, Mapping):
        compact_execution = {
            key: execution.get(key) for key in ("status", "due_status")
        }

    stage = payload.get("stage")
    compact_stage = None
    if isinstance(stage, Mapping):
        compact_stage = {
            key: stage.get(key)
            for key in ("stage_id", "label", "window", "status", "display_status")
        }

    summary: dict[str, Any] = {
        "schema_version": payload.get("schema_version"),
        "trade_date": payload.get("trade_date"),
        "stage_id": payload.get("stage_id"),
        "status": payload.get("status"),
        "stage": compact_stage,
        "markets": compact_markets,
        "execution_evidence": compact_execution,
        "selected_a_rows": payload.get("selected_a_rows"),
        "selected_hk_rows": payload.get("selected_hk_rows"),
        "selected_total_rows": payload.get("selected_total_rows"),
        "selection_mode": payload.get("selection_mode"),
        "snapshot_reselection": _snapshot_side(payload.get("snapshot_reselection"), "selected_rows"),
        "snapshot_recovery": _snapshot_side(payload.get("snapshot_recovery"), "observed_rows"),
    }
    for flag in TRADING_SAFETY_FLAGS:
        summary[flag] = payload.get(flag, False)
    summary["RESEARCH_ONLY"] = payload.get("RESEARCH_ONLY", True)
    summary["write_performed"] = payload.get("write_performed", False)
    return summary


def create_app(
    data_root: Path | None = None,
    quote_provider: ReadOnlyQuoteProvider | None = None,
    shared_data_root: Path | str | None = None,
    ledger_root: Path | None = None,
    stage_center_selection_root: Path | None = None,
    current_date: str | None = None,
    manager_research_state_root: Path | str | None = None,
    manager_research_observation_reader: Any | None = None,
    manager_research_source_provider: Any | None = None,
    research_data_root: Path | str | None = None,
    research_ledger_root: Path | str | None = None,
    morning_news_data_root: Path | str | None = None,
    preselection_source_root: Path | str | None = None,
    stage_center_research_binding_path: Path | str | None = None,
    stage_center_research_binding_sha256: str | None = None,
    manager_workbench_config: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="V4", version="0.1.0")
    store = NativeDataStore(data_root or Path.cwd() / ".runtime" / "data")
    review_store = ReviewStore(store.root)
    configured_research_root = research_data_root or os.environ.get("V4_RESEARCH_DATA_ROOT")
    resolved_research_root = Path(configured_research_root).expanduser() if configured_research_root else store.root
    configured_pool_source = (
        preselection_source_root or os.environ.get("V4_PRESELECTION_SOURCE_ROOT")
    )
    resolved_pool_source = (
        Path(configured_pool_source).expanduser()
        if configured_pool_source
        else store.root
    )
    configured_morning_news_root = (
        morning_news_data_root or os.environ.get("V4_MORNING_NEWS_DATA_ROOT")
    )
    configured_research_ledger = research_ledger_root
    if configured_research_ledger:
        resolved_research_ledger = Path(configured_research_ledger).expanduser()
    elif ledger_root is not None and not configured_research_root:
        # Preserve the existing single-root application contract for callers
        # that have not configured a separate research producer root.
        resolved_research_ledger = Path(ledger_root).expanduser()
    else:
        resolved_research_ledger = resolved_research_root.parent / "dispatcher"
    research_source = ResearchLaneSource(
        resolved_research_root,
        ledger_root=resolved_research_ledger,
    )
    configured_selection_root = stage_center_selection_root
    shared_selection_consumer = (
        StageSelectionConsumer(
            configured_selection_root,
            a_name_pool_root=resolved_pool_source,
        )
        if configured_selection_root is not None
        else None
    )
    approved_research_reader = (
        ApprovedResearchReadBinding(
            binding_path=(stage_center_research_binding_path
                          if stage_center_research_binding_path is not None
                          else Path(__file__).resolve().parents[3] / "stage_center/approved_research_read.json"),
            history_root=configured_selection_root,
            api_root=Path(__file__).resolve().parents[3],
            expected_reader_sha256=_STAGE_RESEARCH_READER_SHA256,
            expected_binding_sha256=stage_center_research_binding_sha256,
            a_name_pool_root=shared_selection_consumer.a_name_pool_root,
        ) if shared_selection_consumer is not None else None
    )
    if shared_selection_consumer is None:
        stage_store = StageStore(store.root)
        resolved_quote_provider = quote_provider or StageQuoteProvider(
            primary=FutuQuoteProvider(),
            a_replay=TdxMinuteReplayProvider(),
            references=stage_store,
            hk_replay=HkConnectStageReplayProvider(),
        )
        stage_runner = StageRunner(
            stage_store,
            input_producer=StageInputProducer(
                store,
                stage_store,
                resolved_quote_provider,
            ),
            opening_second_filter_store=OpeningSecondFilterStore(store.root),
        )
    else:
        # Explicit shared-root mode is read-only: do not instantiate a quote
        # provider, input producer, or StageRunner writer path at all.
        stage_runner = None

    def shared_selection_unconfigured(trade_date: str, stage_id: str) -> dict:
        return {
            "schema_version": "stage_center.selection_consumer.v1",
            "response_source": "SHARED_STAGE_CENTER",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": "CANNOT_CONFIRM",
            "markets": {},
            "selection_markets": {},
            "market_summaries": {},
            "unified_rows": [],
            "artifact_id": None,
            "bundle_artifact_id": None,
            "cannot_confirm": ["SHARED_STAGE_CENTER_NOT_CONFIGURED"],
            "write_performed": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _catalog() -> dict:
        return date_catalog(
            store,
            current_date=current_date,
            stage_selection_root=configured_selection_root,
            preselection_source_root=(
                resolved_pool_source if configured_pool_source else None
            ),
            # Navigation readers share one read-only projection; the verified
            # scans behind it are the slowest part of the first page load.
            use_cache=True,
        )

    projection_ctx = ProjectionContext(
        store=store,
        configured_selection_root=configured_selection_root,
        configured_pool_source=configured_pool_source,
        resolved_pool_source=resolved_pool_source,
        configured_morning_news_root=configured_morning_news_root,
        morning_history_observation=_hk_morning_history_observation,
        morning_selection_recovery_bindings=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,
    )


    def _quarantine_known_hk_auction_pool_mismatch(
        payload: dict, trade_date: str, stage_id: str
    ) -> dict:
        """Hide only the pinned 10/05 auction artifact proven to use the wrong D1 pool."""
        if (
            trade_date != "20261005"
            or stage_id != "STAGE_0925"
            or shared_selection_consumer is None
        ):
            return payload
        market = (payload.get("markets") or {}).get("HK_CONNECT")
        if not isinstance(market, Mapping):
            return payload
        try:
            key = shared_selection_consumer.store._key(trade_date, stage_id, "HK_CONNECT")
            entry = shared_selection_consumer.store._latest().get("entries", {}).get(key)
        except (OSError, ValueError, TypeError, KeyError):
            return payload
        source_evidence = list(market.get("source_evidence") or ())
        required_source = {
            "candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
            "hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
            "hk_d1_source_trade_date=20260930",
            "hk_observation_trade_date=20261005",
        }
        if (
            not isinstance(entry, Mapping)
            or entry.get("trade_date") != trade_date
            or entry.get("stage_id") != stage_id
            or entry.get("market") != "HK_CONNECT"
            or entry.get("run_id") != "run-6a45f94febaf762962082e81"
            or entry.get("artifact_sha256") != "abea293be53b9114f2835ed94d6e52bdc33a54debe51891f102edcb05102357d"
            or entry.get("manifest_sha256") != "25398bdf783d2916aa8aa64c0581071d99d8c7a85ebbdb8b6fbc3b4dbed08177"
            or entry.get("receipt_sha256") != "8bed1cd1e889cea9fa26c107c159018c2b1614aa0d54029ef1c483c8da0e40dc"
            or market.get("run_id") != entry.get("run_id")
            or not required_source.issubset(set(source_evidence))
        ):
            return payload

        quarantined = dict(market)
        quarantined_rows = list(market.get("rows") or ())
        reasons = list(market.get("cannot_confirm") or ())
        if "HK_D1_TARGET_POOL_MISMATCH" not in reasons:
            reasons.append("HK_D1_TARGET_POOL_MISMATCH")
        quarantined.update(
            {
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": None,
                "rows": [],
                "cannot_confirm": reasons,
                "quarantined_source": {
                    "status": "CANNOT_CONFIRM",
                    "reason": "HK_D1_TARGET_POOL_MISMATCH",
                    "artifact_sha256": entry["artifact_sha256"],
                    "manifest_sha256": entry["manifest_sha256"],
                    "receipt_sha256": entry["receipt_sha256"],
                    "artifact_relative": entry.get("artifact_relative"),
                    "run_id": entry["run_id"],
                    "source_selected_rows": len(quarantined_rows),
                    "source_requested_rows": market.get("requested_rows"),
                    "source_rows": market.get("source_rows"),
                    "source_evidence": source_evidence,
                    "source_pool_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
                    "target_pool_sha256": "8799c7ef056981549204ece5958222acad92204bfbf9ba5f12ef26bae57dad01",
                    "rows_retained_in_verified_source_artifact": True,
                },
            }
        )
        markets = dict(payload.get("markets") or {})
        markets["HK_CONNECT"] = quarantined
        result = dict(payload)
        result["markets"] = markets
        return result

    def _read_exact_target_hk_override(
        payload: dict,
        trade_date: str,
        stage_id: str,
        limit: int,
        binding: Mapping[str, Any],
        *,
        source_label: str,
        target_pool_sha256: str,
        superseded_source_reason: str | None = None,
    ) -> dict:
        try:
            exact = stage_workbench(
                date=trade_date,
                stage=stage_id,
                limit=limit,
                market="HK_CONNECT",
                backfill_run_id=binding["backfill_run_id"],
            )
        except HTTPException as error:
            # These frozen historical composite reads have independently verified
            # A-share trios. An invalid HK override must not hide that A lane;
            # the explicit HK read above still rejects its invalid binding.
            if error.status_code != 409 or (trade_date, stage_id) not in {
                ('20260918', 'STAGE_0930_0935'),
                ('20260918', 'STAGE_0935_0940'),
                ('20260918', 'STAGE_0940_0945'),
                ('20260918', 'STAGE_0945_1030'),
                ('20260918', 'STAGE_1300_1315'),
                ('20260918', 'STAGE_1445_1500'),
                ('20260922', 'STAGE_0935_0940'),
                ('20260922', 'STAGE_0940_0945'),
                ('20260922', 'STAGE_0945_1030'),
                ('20260924', 'STAGE_0930_0935'),
                ('20260924', 'STAGE_1445_1500'),
                ('20260929', 'STAGE_0930_0935'),
                ('20260929', 'STAGE_0935_0940'),
                ('20260929', 'STAGE_0940_0945'),
                ('20260929', 'STAGE_0945_1030'),
                ('20260929', 'STAGE_1300_1315'),
                ('20260929', 'STAGE_1445_1500'),
                ('20260930', 'STAGE_0930_0935'),
                ('20260930', 'STAGE_0935_0940'),
                ('20260930', 'STAGE_0940_0945'),
                ('20260930', 'STAGE_0945_1030'),
                ('20260930', 'STAGE_1300_1315'),
                ('20260930', 'STAGE_1445_1500'),
            }:
                raise
            markets = dict(payload.get("markets") or {})
            a_market = markets.get("A_SHARE")
            if not isinstance(a_market, Mapping) or not (
                a_market.get("selection_manifest_receipt_verified") is True
                and int(a_market.get("selected_rows") or 0) > 0
            ):
                raise
            from stage_center.consumer import _invalid_market_with_reason
            denied = _invalid_market_with_reason(
                "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
            )
            denied["cannot_confirm"].append(str(error.detail))
            denied["recovery_provenance"] = {
                "mode": "BACKFILL_BINDING_REJECTED",
                "backfill_run_id": binding["backfill_run_id"],
                "source": source_label,
                "http_status": error.status_code,
            }
            markets["HK_CONNECT"] = denied
            result = dict(payload)
            result.update(markets=markets, artifact_id=None,
                          bundle_artifact_id=None, run_id=None)
            execution = dict(payload.get("execution_evidence") or {})
            execution_markets = dict(execution.get("markets") or {})
            execution_markets["HK_CONNECT"] = {
                "status": "CANNOT_CONFIRM", "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": list(denied["cannot_confirm"]),
            }
            execution.update(markets=execution_markets,
                             execution_verified=False, natural_verified=False)
            result["execution_evidence"] = execution
            return result
        exact_markets = exact.get("selection_markets")
        exact_hk = exact_markets.get("HK_CONNECT") if isinstance(exact_markets, Mapping) else None
        if not isinstance(exact_hk, Mapping):
            raise HTTPException(status_code=409, detail="approved exact-target HK candidate is unavailable")

        markets = dict(payload.get("markets") or {})
        prior_hk = markets.get("HK_CONNECT")
        hk_market = dict(exact_hk)
        if isinstance(prior_hk, Mapping) and prior_hk.get("run_id") != hk_market.get("run_id"):
            superseded_source = {
                "status": "SUPERSEDED_BY_EXACT_TARGET_D1_RESEARCH_CANDIDATE",
                "displayed_as_valid_observation": False,
                "artifact_id": prior_hk.get("artifact_id"),
                "run_id": prior_hk.get("run_id"),
                "raw_artifact_sha256": prior_hk.get("raw_artifact_sha256"),
                "requested_rows": prior_hk.get("requested_rows"),
                "source_rows": prior_hk.get("source_rows"),
                "selected_rows": prior_hk.get("selected_rows"),
                "source_evidence": list(prior_hk.get("source_evidence") or ()),
            }
            if superseded_source_reason is not None:
                superseded_source["replacement_reason"] = superseded_source_reason
                superseded_source["target_pool_sha256"] = target_pool_sha256
            hk_market["superseded_source"] = superseded_source
        markets["HK_CONNECT"] = hk_market
        result = dict(payload)
        result.update(
            {
                "markets": markets,
                "RESEARCH_ONLY": True,
                "artifact_id": None,
                "bundle_artifact_id": None,
                "run_id": None,
                "market_readback_bindings": {
                    "scope": "DATE_STAGE_MARKET_SCOPED_READ_ONLY",
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "markets": {
                        "HK_CONNECT": {
                            "source": source_label,
                            "backfill_run_id": binding["backfill_run_id"],
                            "run_id": hk_market.get("run_id"),
                            "requested_rows": hk_market.get("requested_rows"),
                            "source_rows": hk_market.get("source_rows"),
                            "selected_rows": hk_market.get("selected_rows"),
                            "raw_artifact_sha256": hk_market.get("raw_artifact_sha256"),
                            "selection_manifest_sha256": hk_market.get("selection_manifest_sha256"),
                            "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                            "target_pool_sha256": target_pool_sha256,
                        }
                    },
                    "single_bundle_artifact_id": None,
                },
            }
        )
        if binding.get("requested_rows") is not None:
            result["market_readback_bindings"]["markets"]["HK_CONNECT"].update(
                {
                    "candidate_batch_receipt_sha256": binding[
                        "candidate_batch_receipt_sha256"
                    ],
                    "candidate_receipt_sha256": binding[
                        "candidate_receipt_sha256"
                    ],
                    "candidate_manifest_sha256": binding[
                        "candidate_manifest_sha256"
                    ],
                    "candidate_source_evidence_sha256": binding[
                        "source_evidence_sha256"
                    ],
                    "missing_rows": binding["missing_rows"],
                    "missing_codes": list(binding["missing_codes"]),
                    "missing_reason_by_code": dict(
                        binding["missing_reason_by_code"]
                    ),
                }
            )
        prior_execution = dict(payload.get("execution_evidence") or {})
        execution_markets = dict(prior_execution.get("markets") or {})
        exact_execution = exact.get("execution_evidence")
        exact_execution_markets = (
            exact_execution.get("markets") if isinstance(exact_execution, Mapping) else None
        )
        exact_execution_hk = (
            exact_execution_markets.get("HK_CONNECT")
            if isinstance(exact_execution_markets, Mapping)
            else None
        )
        if isinstance(exact_execution_hk, Mapping):
            execution_markets["HK_CONNECT"] = dict(exact_execution_hk)
        else:
            execution_markets["HK_CONNECT"] = {
                "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                "selection_binding": "BOUND_TO_VERIFIED_SELECTION",
                "runner_receipt_verified": hk_market.get("runner_receipt_verified") is True,
                "runner_receipt_sha256": hk_market.get("runner_receipt_sha256"),
                "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": [
                    "HK_BACKFILL_EXECUTION_MARKET_DETAILS_NOT_EXPOSED_BY_SELECTION_CONSUMER"
                ],
            }
        prior_execution.update(
            {
                "markets": execution_markets,
                "scope": "READ_ONLY_MARKET_SCOPED_SELECTION_COMPOSITION",
                "status": "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED",
                "execution_verified": False,
                "natural_verified": False,
                "cannot_confirm": [
                    "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
                ],
            }
        )
        prior_execution.pop("observed_sha256", None)
        prior_execution.pop("receipt_sha256_binding", None)
        result["execution_evidence"] = prior_execution
        return result

    def _read_r8_exact_target_hk_override(
        payload: dict, trade_date: str, stage_id: str, limit: int
    ) -> dict | None:
        binding = _HK_R8_BINDING_BY_DATE_STAGE.get((trade_date, stage_id))
        if binding is None:
            return None
        return _read_exact_target_hk_override(
            payload,
            trade_date,
            stage_id,
            limit,
            binding,
            source_label="APPROVED_EXACT_TARGET_D1_AFTERFACT_CANDIDATE_R8",
            target_pool_sha256=_HK_R8_POOL_EVIDENCE[trade_date]["pool_sha256"],
        )

    def _read_r9_exact_target_hk_override(
        payload: dict, trade_date: str, stage_id: str, limit: int
    ) -> dict | None:
        binding = _HK_R9_BINDING_BY_DATE_STAGE.get((trade_date, stage_id))
        if binding is None:
            return None
        markets = payload.get("markets")
        prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
        rows = prior_hk.get("rows") if isinstance(prior_hk, Mapping) else None
        legacy_stale = _HK_R9_LEGACY_STALE_LANE_IDENTITIES.get(
            (trade_date, stage_id)
        )
        replace_for_legacy_pool_mismatch = False
        if isinstance(prior_hk, Mapping):
            # R9 may repair a missing lane or replace a verified nonempty lane
            # only when its exact pool provenance proves it belongs to a
            # different target pool. Preserve an effective ordinary result
            # when it is already bound to this date's target pool. If the
            # consumer found this exact R9 backfill run because no ordinary
            # lane existed, apply the exact route binding without marking that
            # same candidate as a superseded source.
            if prior_hk.get("backfill_run_id") == binding["backfill_run_id"]:
                replace_existing = True
            elif (
                rows == []
                and prior_hk.get("status") == "CANNOT_CONFIRM"
                and prior_hk.get("selected_rows") in (None, 0)
            ):
                replace_existing = True
            elif isinstance(rows, list) and rows and legacy_stale is not None:
                legacy_contract = _HK_R9_LEGACY_STALE_POOL_CONTRACTS.get(trade_date)
                target_pool = _HK_R9_POOL_EVIDENCE.get(trade_date)
                evidence = prior_hk.get("source_evidence")

                def marker_values(name: str) -> list[str]:
                    prefix = f"{name}="
                    return [
                        marker.partition("=")[2]
                        for marker in evidence
                        if isinstance(marker, str) and marker.startswith(prefix)
                    ] if isinstance(evidence, list) else []

                def marker_matches(name: str, expected: str | None) -> bool:
                    values = marker_values(name)
                    return values == ([expected] if expected is not None else [])

                try:
                    latest = shared_selection_consumer.store._latest()
                    latest_key = shared_selection_consumer.store._key(
                        trade_date, stage_id, "HK_CONNECT"
                    )
                    current_entry = latest.get("entries", {}).get(latest_key)
                except (AttributeError, OSError, ValueError, TypeError, KeyError):
                    current_entry = None

                observation_count = prior_hk.get("observation_count")
                selected_rows = prior_hk.get("selected_rows")
                count_evidence = (
                    observation_count
                    if isinstance(observation_count, int)
                    and not isinstance(observation_count, bool)
                    else selected_rows
                )
                count_matches = (
                    isinstance(count_evidence, int)
                    and not isinstance(count_evidence, bool)
                    and count_evidence == legacy_stale["observation_count"]
                    and len(rows) == count_evidence
                    and (
                        observation_count is None
                        or observation_count == count_evidence
                    )
                    and (selected_rows is None or selected_rows == count_evidence)
                )
                entry_matches = isinstance(current_entry, Mapping) and all(
                    current_entry.get(field) == expected
                    for field, expected in (
                        ("trade_date", trade_date),
                        ("stage_id", stage_id),
                        ("market", "HK_CONNECT"),
                        ("run_id", legacy_stale["run_id"]),
                        ("artifact_sha256", legacy_stale["selection_artifact_sha256"]),
                        ("manifest_sha256", legacy_stale["selection_manifest_sha256"]),
                        ("receipt_sha256", legacy_stale["selection_receipt_sha256"]),
                    )
                ) and all(
                    current_entry.get(flag) is False
                    for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
                )
                target_matches = (
                    isinstance(target_pool, Mapping)
                    and binding.get("pool_artifact_sha256") == target_pool.get("pool_sha256")
                    and binding.get("pool_path") == target_pool.get("pool_path")
                    and binding.get("pool_signal_date") == target_pool.get("signal_date")
                    and target_pool.get("source_date") == trade_date
                    and target_pool.get("pool_sha256") != legacy_contract.get("pool_sha256")
                ) if isinstance(legacy_contract, Mapping) else False
                legacy_source_matches = (
                    isinstance(legacy_contract, Mapping)
                    and marker_matches("hk_d1_sha256", legacy_contract.get("pool_sha256"))
                    and marker_matches("hk_d1_json_sha256", legacy_contract.get("pool_sha256"))
                    and marker_matches("hk_d1_json", legacy_contract.get("pool_path"))
                    and marker_matches(
                        "hk_d1_source_trade_date",
                        legacy_contract.get("source_trade_date"),
                    )
                    and marker_matches(
                        "hk_d1_source_signal_date",
                        legacy_contract.get("source_signal_date"),
                    )
                    and marker_matches(
                        "hk_d1_binding_sha256",
                        legacy_contract.get("binding_sha256"),
                    )
                )
                optional_display_mode = prior_hk.get("display_mode")
                replace_for_legacy_pool_mismatch = all(
                    (
                        trade_date in _HK_R9_LEGACY_STALE_POOL_CONTRACTS,
                        prior_hk.get("run_id") == legacy_stale["run_id"],
                        prior_hk.get("artifact_id") == legacy_stale["artifact_id"],
                        prior_hk.get("raw_artifact_sha256") == legacy_stale["raw_artifact_sha256"],
                        prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"},
                        prior_hk.get("selection_status", "PARTIAL_WITH_ROWS")
                        in {"READY", "PARTIAL_WITH_ROWS"},
                        optional_display_mode in (None, "OBSERVATION_UNVERIFIED"),
                        prior_hk.get("requested_rows") == legacy_stale["requested_rows"],
                        prior_hk.get("source_rows") == legacy_stale["source_rows"],
                        entry_matches,
                        target_matches,
                        legacy_source_matches,
                        count_matches,
                    )
                )
                replace_existing = replace_for_legacy_pool_mismatch
            elif (
                isinstance(rows, list)
                and rows
                and prior_hk.get("status") in {"READY", "PARTIAL_WITH_ROWS"}
                and prior_hk.get("selected_rows") == len(rows)
            ):
                source_evidence = prior_hk.get("source_evidence")
                pool_markers = [
                    marker.partition("=")[2]
                    for marker in source_evidence
                    if isinstance(marker, str)
                    and marker.startswith("historical_pool_artifact_sha256=")
                ] if isinstance(source_evidence, list) else []
                existing_pool_sha256 = pool_markers[0] if len(pool_markers) == 1 else ""
                is_sha256 = (
                    len(existing_pool_sha256) == 64
                    and all(character in "0123456789abcdefABCDEF" for character in existing_pool_sha256)
                )
                replace_existing = (
                    is_sha256
                    and existing_pool_sha256.lower()
                    != str(binding["pool_artifact_sha256"]).lower()
                )
            else:
                replace_existing = False
            if not replace_existing:
                return None
        return _read_exact_target_hk_override(
            payload,
            trade_date,
            stage_id,
            limit,
            binding,
            source_label=(
                "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9_LEGACY_POOL_REPAIR"
                if replace_for_legacy_pool_mismatch
                else "APPROVED_MONTH_HK_EXACT_TARGET_D1_AFTERFACT_R9"
            ),
            target_pool_sha256=binding["pool_artifact_sha256"],
            superseded_source_reason=(
                "EXACT_PINNED_LEGACY_HK_D1_POOL_MISMATCH"
                if replace_for_legacy_pool_mismatch
                else None
            ),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, bool]:
        return dict(TRADING_SAFETY_FLAGS)

    @app.get("/api/v4/meta/stages")
    def stage_metadata() -> dict:
        return {
            "stages": list(FROZEN_STAGE_IDS),
            "definitions": [
                {"stage_id": stage_id, **STAGE_DEFINITIONS[stage_id]}
                for stage_id in FROZEN_STAGE_IDS
            ],
        }

    @app.get("/api/v1/runs/date-list")
    def run_date_list(date: str | None = None) -> dict:
        requested = _strict_date(date) if date is not None else None
        response = {
            **_catalog(),
            "review_dates": review_store.list_dates(),
            "research_dates": research_source.list_dates(),
            "research_source": research_source.binding(),
        }
        # ``stage_artifacts`` and ``independent_pool_evidence`` are navigation
        # inputs only: they feed the date lists above and have no client or
        # server consumer. Serializing them added ~2.4 MB to this response.
        response.pop("stage_artifacts", None)
        response.pop("independent_pool_evidence", None)
        response["requested_date"] = requested
        response["selected_date"] = requested or response["navigation_date"]
        # Reuse the existing read-only validator. A configured string alone is
        # not proof of a running release; no path or exception detail is exposed.
        from infrastructure.scheduling.dispatcher import validate_release_identity
        identity = {"application": "V4", "status": "CANNOT_CONFIRM",
                    "release_id": "", "process_status": "CANNOT_CONFIRM"}
        try:
            verified = validate_release_identity()
            identity.update(status="MANIFEST_EXECUTION_FILES_VERIFIED",
                            release_id=verified["release_id"],
                            manifest_sha256=verified["release_manifest_sha256"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
        response["runtime_identity"] = identity
        return response

    app.include_router(create_preselection_router(
        PreselectionPoolService(
            store,
            configured_pool_source=bool(configured_pool_source),
            resolved_pool_source=resolved_pool_source,
        ),
        get_catalog=_catalog,
        validate_date=_strict_date,
    ))

    def _read_hk_morning_selection_recovery_override(
        payload: dict,
        trade_date: str,
        stage_id: str,
        limit: int,
    ) -> dict | None:
        binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
            (trade_date, stage_id)
        )
        if binding is None:
            return None
        try:
            from stage_center.selection import SelectionStore

            if configured_selection_root is None:
                return None
            store = SelectionStore(configured_selection_root)
            original = store.read_verified(trade_date, stage_id, "HK_CONNECT")
            verified = store._verify_run(
                trade_date, stage_id, "HK_CONNECT", binding["selection_run_id"]
            )
            if not isinstance(original, Mapping):
                return None
            original_rows = original.get("rows")
            if (
                original.get("run_id") != binding["selection_run_id"]
                or original.get("artifact_id") != binding["artifact_id"]
                or original.get("raw_artifact_sha256") != binding["raw_artifact_sha256"]
                or original.get("algorithm_id") != binding["algorithm_id"]
                or original.get("algorithm_sha256") != binding["algorithm_sha256"]
                or original.get("source_status") != "CANNOT_CONFIRM"
                or original.get("selection_status") != "PARTIAL_WITH_ROWS"
                or original.get("requested_rows") != 100
                or original.get("source_rows") != 100
                or original.get("selected_rows") != 10
                or original.get("missing_symbols")
                or original.get("cannot_confirm") != ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE"]
                or not isinstance(original_rows, list)
                or len(original_rows) != 10
            ):
                return None
            if (
                verified.get("manifest_sha256") != binding["original_manifest_sha256"]
                or verified.get("receipt_sha256") != binding["original_receipt_sha256"]
                or verified.get("artifact_sha256") != binding["selection_artifact_sha256"]
            ):
                return None
            markets = payload.get("markets")
            prior_hk = markets.get("HK_CONNECT") if isinstance(markets, Mapping) else None
            if isinstance(prior_hk, Mapping) and any(
                prior_hk.get(field) not in (None, expected)
                for field, expected in (
                    ("run_id", binding["selection_run_id"]),
                    ("artifact_id", binding["artifact_id"]),
                    ("raw_artifact_sha256", binding["raw_artifact_sha256"]),
                )
            ):
                return None
            # The ordinary consumer hides rows for CANNOT_CONFIRM. Reattach the
            # verified exact identity only for supersession comparison; the
            # exact backfill route supplies the displayed observation rows.
            payload = dict(payload)
            markets = dict(markets or {})
            markets["HK_CONNECT"] = {
                "market": "HK_CONNECT",
                "status": original["selection_status"],
                "selection_status": original["selection_status"],
                "source_status": original["source_status"],
                "artifact_id": original["artifact_id"],
                "run_id": original["run_id"],
                "raw_artifact_sha256": original["raw_artifact_sha256"],
                "requested_rows": original["requested_rows"],
                "source_rows": original["source_rows"],
                "selected_rows": original["selected_rows"],
                "source_evidence": list(original.get("source_evidence") or []),
                "missing_symbols": list(original.get("missing_symbols") or []),
                "cannot_confirm": list(original.get("cannot_confirm") or []),
                "rows": list(original_rows),
            }
            payload["markets"] = markets
            result = _read_exact_target_hk_override(
                payload,
                trade_date,
                stage_id,
                limit,
                {
                    "backfill_run_id": binding["backfill_run_id"],
                    # The candidate is an exact selection-row projection; it does
                    # not claim a new full-pool acquisition or missing-code list.
                    "requested_rows": None,
                },
                source_label="HK_MORNING_PRECAPTURE_OBSERVATION_REPROJECTION_R1",
                target_pool_sha256="78646320d1140bb574b6aee66c9bd6b51f57ca0797fd96e4f2775e245a57efd8",
            )
            result["markets"]["HK_CONNECT"]["trade_date"] = trade_date
            result["markets"]["HK_CONNECT"]["stage_id"] = stage_id
            return result
        except (OSError, ValueError, TypeError, KeyError):
            return None
        except HTTPException as error:
            if error.status_code in {404, 409}:
                return None
            raise

    stage_workbench_ctx = StageWorkbenchContext(
        approved_research_reader=approved_research_reader,
        shared_selection_consumer=shared_selection_consumer,
        configured_selection_root=configured_selection_root,
        stage_runner=stage_runner,
        projection=projection_ctx,
        approved_exact_stage_backfills=_APPROVED_EXACT_STAGE_BACKFILLS,
        morning_binding_by_date_stage=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,
        quarantine_hk_auction_pool_mismatch=_quarantine_known_hk_auction_pool_mismatch,
        hk_morning_override=_read_hk_morning_selection_recovery_override,
        r8_override=_read_r8_exact_target_hk_override,
        r9_override=_read_r9_exact_target_hk_override,
        scoped_selection_root=_resolve_exact_backfill_selection_root,
        new_scoped_consumer=_new_scoped_stage_selection_consumer,
    )

    @app.get("/api/v4/workbench/stage")
    def stage_workbench(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=10, ge=1, le=50),
        market: str | None = None,
        backfill_run_id: str | None = None,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        return read_stage_workbench(
            stage_workbench_ctx, selected, stage, limit, market, backfill_run_id
        )

    @app.post("/api/v4/workbench/stage/ensure")
    def stage_workbench_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is not None:
            return project_shared_selection(projection_ctx,
                shared_selection_consumer.ensure(selected, stage, force=force),
                limit=50,
                ordinary_hk_display=True,
            )
        return stage_runner.ensure(selected, stage, force=force)

    @app.get("/api/v4/workbench/stage-batch")
    def stage_workbench_batch(
        date: str | None = None,
        stages: str | None = None,
    ) -> dict:
        """Timeline summaries for several stages in one round trip."""
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        requested = [item for item in (stages or "").split(",") if item]
        if any(stage_id not in FROZEN_STAGE_IDS for stage_id in requested):
            raise HTTPException(status_code=422, detail="unknown stage")
        ordered = [
            stage_id
            for stage_id in FROZEN_STAGE_IDS
            if not requested or stage_id in requested
        ]

        def _summary_for(stage_id: str) -> tuple[str, dict | None]:
            try:
                payload = stage_workbench(selected, stage_id, 50)
            except HTTPException:
                return stage_id, None
            except (OSError, ValueError, TypeError, KeyError):
                return stage_id, None
            return stage_id, _project_stage_timeline_summary(payload)

        summaries: dict[str, dict] = {}
        if ordered:
            workers = min(
                len(ordered),
                max(1, int(os.environ.get("V4_STAGE_BATCH_WORKERS", "8") or "8")),
            )
            timeout_seconds = float(os.environ.get("V4_STAGE_BATCH_TIMEOUT_SECONDS", "12") or "12")
            summaries = _bounded_stage_summaries(
                _summary_for, ordered, workers=min(workers, _STAGE_BATCH_CAPACITY),
                timeout_seconds=timeout_seconds,
            )

        return {
            "schema_version": "v4.stage_timeline_batch.v1",
            "trade_date": selected,
            "stages": summaries,
            **dict(TRADING_SAFETY_FLAGS),
            "RESEARCH_ONLY": True,
            "write_performed": False,
        }

    @app.get("/api/v4/stage-center/selection")
    def shared_stage_selection(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(projection_ctx,
            shared_selection_consumer.get(selected, stage),
            limit,
            ordinary_hk_display=True,
        )

    @app.get("/api/v4/manager/stage-selection")
    def manager_stage_selection(
        date: str | None = None,
        stage: str | None = None,
        market: str | None = None,
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict:
        """Read the manager's exact HK_CONNECT stage lane only.

        The shared stage-center route remains a compatibility projection for
        its historical scheduled-market response.  This dedicated route is a
        narrower boundary for the manager consumer and never falls back to
        the unified or A-share lane.
        """
        if date is None:
            raise HTTPException(status_code=422, detail="date is required")
        selected = _strict_date(date)
        if stage != "STAGE_0935_0940":
            raise HTTPException(status_code=422, detail="stage must be STAGE_0935_0940")
        if market != "HK_CONNECT":
            raise HTTPException(status_code=422, detail="market must be HK_CONNECT")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(projection_ctx,
            shared_selection_consumer.get(selected, stage, markets=("HK_CONNECT",)),
            limit,
        )

    @app.post("/api/v4/stage-center/selection/ensure")
    def shared_stage_selection_ensure(
        date: str | None = None,
        stage: str = "STAGE_0940_0945",
        force: bool = False,
    ) -> dict:
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if not selected:
            selected = _catalog()["system_date"]
        if stage not in FROZEN_STAGE_IDS:
            raise HTTPException(status_code=422, detail="unknown stage")
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return project_shared_selection(projection_ctx,
            shared_selection_consumer.ensure(selected, stage, force=force),
            limit=200,
            ordinary_hk_display=True,
        )

    app.include_router(
        create_runtime_router(
            store.root,
            ledger_root=ledger_root,
            stage_selection_root=configured_selection_root,
            current_date=current_date,
        )
    )
    app.include_router(create_runtime_graph_router(store.root))
    app.include_router(create_manual_collection_router(
        Path(os.environ.get("V4_REVIEW_CORE_CLOSE_ROOT") or store.root),
        stage_selection_root=configured_selection_root,
    ))
    app.include_router(create_review_router(
        store.root,
        hk_close_root=os.environ.get("V4_REVIEW_CORE_CLOSE_ROOT") or None,
        review_root=os.environ.get("V4_DAILY_REVIEW_ROOT"),
        generation_bindings_path=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_PATH"),
        generation_bindings_sha256=os.environ.get("V4_REVIEW_GENERATION_BINDINGS_SHA256"),
        intraday_root=os.environ.get("V4_INTRADAY_RESEARCH_ROOT"),
    ))
    app.include_router(
        create_research_router(
            store.root,
            # Legacy article/day/hourly GETs use the same explicit producer
            # binding as the decision-desk lane; selection/materialization
            # ownership stays on the V4 consumer root inside the router.
            research_read_root=resolved_research_root,
            wechat_archive_root=os.environ.get("V4_WECHAT_ARCHIVE_ROOT"),
            shared_data_root=os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT"),
        )
    )

    # Research is an owned V4 read-only slice.  Register the compatibility
    # routes unconditionally so a caller does not need the removed V3 module
    # roots or the legacy router signature.  Missing archives remain typed
    # NOT_MATERIALIZED responses from the owned stores.
    app.include_router(create_baimao_router(store.root))
    app.include_router(
        # Only the GET-only research decision-desk lane consumes the explicit
        # producer root.  The legacy-compatible research router above keeps
        # its V4 store root for any materialization/write owner.
        create_research_lane_router(
            resolved_research_root,
            shared_data_root=shared_data_root,
            morning_news_data_root=configured_morning_news_root,
            ledger_root=resolved_research_ledger,
            # US digest already writes the native data store.  Do not move the
            # independent research lane, morning news or external-news reader.
            us_market_data_root=store.root,
        )
    )

    # The new manager is the sole manager write owner in this application.
    from v4.manager_workbench.binding import api_config, assemble_api
    manager_config = api_config(
        manager_root=_resolve_manager_research_state_root(manager_research_state_root, data_root),
        shared_root=(os.environ.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT")
                     or os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") or shared_data_root),
        stage_root=configured_selection_root,
        us_root=store.root,
        relation_root=Path(__file__).resolve().parents[3],
        injected=manager_workbench_config,
    )
    assemble_api(app, config=manager_config)

    # Explicit bounded HKEX source capture reuses its original owner/store.
    # It does not assemble the removed manager router or ordinary model jobs.
    from v4.manager_research.hkex_runtime import assemble_hkex_announcements_api
    assemble_hkex_announcements_api(
        app, manager_root=manager_config.manager_root,
        security_master_root=(os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") or manager_config.shared_root),
    )

    # Read-only user-authorized opening slice before all static catchalls.
    from apps.api.v4_api.research_panel_mount import register_opening_research
    register_opening_research(app, module_role="combined", selection_root=configured_selection_root)

    preview_root = Path(__file__).resolve().parents[2] / "web" / "preview"
    if preview_root.is_dir():
        app.mount("/preview", StaticFiles(directory=preview_root, html=True), name="preview")

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", _RevalidatingStaticFiles(directory=dist, html=True), name="web")

    from infrastructure.api_namespace import install_legacy_aliases
    install_legacy_aliases(app)

    return app
