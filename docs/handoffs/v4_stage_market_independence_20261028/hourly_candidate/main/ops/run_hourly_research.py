"""Materialize one graph-backed hourly research slot from a frozen input."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import contracts.research as research_contract_module
import domains.research as research_domain_module
import domains.research_hourly as research_hourly_domain_module
import infrastructure.data_store as data_store_module
import domains.research_hourly as research_hourly_module
import infrastructure.interprocess_lock as interprocess_lock_module
import infrastructure.owned_io as owned_io_module
import infrastructure.owned_path as owned_path_module
import infrastructure.market_time as market_time_module
import infrastructure.research_store as research_store_module
import infrastructure.trading_safety as trading_safety_module
import ops.collect_hourly_research_input as collector_module
import ops.research_shared_bundle as research_shared_bundle_module
import infrastructure.research_source_evidence as research_source_evidence_module
import domains.research_source_validation as research_source_validation_module
from infrastructure.research_source_evidence import read_zsxq_slot_evidence
from domains.research_source_validation import (
    collector_source_cutoff,
    runner_manual_empty_time_shape,
    runner_source_cutoff,
    runner_timestamp,
    strict_source_receipt_time,
    validate_hourly_stage_source,
    validate_runner_point_in_time_source,
)
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from domains.research import build_research_archive
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot
from infrastructure.research_store import (
    HourlyResearchStore,
    ResearchArchiveStore,
    validate_hourly_recovery_provenance,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TIMELINE_TIME_FIELDS = (
    "event_time",
    "source_published_at",
    "first_seen_at",
    "last_checked_at",
)
_DAILY_TIME_FIELDS = ("first_seen_time", "last_seen_time")
_LATE_RECOVERY_OBSERVATION_FIELDS = frozenset(
    {"first_seen_at", "last_checked_at", "first_seen_time", "last_seen_time"}
)


def _research_transformer_identity_manifest() -> dict[str, Any]:
    components: dict[str, str] = {}
    for module in (
        research_contract_module,
        research_domain_module,
        research_hourly_module,
        data_store_module,
        owned_path_module,
        owned_io_module,
        interprocess_lock_module,
        market_time_module,
        trading_safety_module,
        collector_module,
        research_source_evidence_module,
        research_source_validation_module,
        research_store_module,
    ):
        source_file = inspect.getsourcefile(module)
        if source_file is None:
            raise ValueError("hourly research transformer source is unavailable")
        components[module.__name__] = hashlib.sha256(
            Path(source_file).read_bytes()
        ).hexdigest()
    policy_file = Path(__file__).resolve().parents[1] / "domains" / "report_subjects.py"
    components["domains.report_subjects"] = hashlib.sha256(
        policy_file.read_bytes()
    ).hexdigest()
    components["ops.run_hourly_research"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    shared_bundle = research_shared_bundle_module.build_research_shared_bundle()
    if re.fullmatch(r"[0-9a-f]{64}", str(shared_bundle.get("bundle_sha256") or "")) is None:
        raise ValueError("hourly research shared bundle identity is invalid")
    return {
        "schema_version": "v3_5.research_transformer_identity.v2",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "components": components,
        "shared_bundle_sha256": shared_bundle["bundle_sha256"],
        "shared_bundle_manifest_sha256": shared_bundle["manifest_sha256"],
    }

def _research_transformer_identity_sha256() -> str:
    identity = _research_transformer_identity_manifest()
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_source(data_root: Path, business_date: str, slot: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"research/incoming/{business_date}/{slot}.json",
    )



def _has_late_recovery_gap(value: Any) -> bool:
    return isinstance(value, list) and any(
        isinstance(gap, dict)
        and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
        for gap in value
    )


def _validate_first_late_recovery_provenance(
    *,
    data_root: Path,
    business_date: str,
    slot: str,
    recovery_path: Path,
    recovery_sha256: str,
    recovery_payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate a late recovery whose canonical slot has no preimage.

    The first late publication is allowed to start from an absent incoming
    file.  It still needs the same exact owned recovery path, date/slot/cutoff,
    receipts and safety flags.  Empty supersession SHA fields explicitly mean
    "no preimage" and are never treated as a usable digest.
    """

    canonical_path = _default_source(data_root, business_date, slot).resolve(
        strict=False
    )
    resolved_recovery = Path(recovery_path).resolve(strict=False)
    match = re.fullmatch(
        rf"{re.escape(slot)}\.recovery-([0-9a-f]{{16}})\.json",
        resolved_recovery.name,
    )
    if (
        match is None
        or resolved_recovery.parent != canonical_path.parent
        or canonical_path.is_file()
        or not isinstance(recovery_sha256, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", recovery_sha256)
        or not recovery_sha256.lower().startswith(match.group(1))
    ):
        raise ValueError("hourly research first-admission recovery identity is invalid")
    if hashlib.sha256(resolved_recovery.read_bytes()).hexdigest() != recovery_sha256.lower():
        raise ValueError("hourly research first-admission recovery bytes SHA mismatch")
    manifest = recovery_payload.get("source_manifest")
    metadata = recovery_payload.get("recovery_metadata")
    if not isinstance(manifest, dict) or not isinstance(metadata, dict):
        raise ValueError("hourly research first-admission recovery provenance is invalid")
    cutoff = datetime.strptime(
        f"{business_date}{slot}", "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59)
    cutoff_text = cutoff.isoformat(timespec="seconds")
    if (
        recovery_payload.get("recovery") is not True
        or recovery_payload.get("trade_date") != business_date
        or recovery_payload.get("slot") != slot
        or recovery_payload.get("pit_cutoff") != cutoff_text
        or recovery_payload.get("source_path") != canonical_path.as_posix()
        or recovery_payload.get("original_source_path") != canonical_path.as_posix()
        or recovery_payload.get("capture_origin") != "LATE_RECOVERY"
        or recovery_payload.get("original_time_capture") is not False
        or recovery_payload.get("natural_execution_verified") is not False
    ):
        raise ValueError("hourly research first-admission recovery provenance is invalid")
    for field in ("original_source_sha256", "supersedes", "retry_of_sha256"):
        if recovery_payload.get(field) not in {None, ""}:
            raise ValueError("hourly research first-admission recovery has a preimage")
    receipts = recovery_payload.get("source_receipts")
    manifest_receipts = manifest.get("source_receipts")
    metadata_receipts = metadata.get("source_receipts")
    if (
        not isinstance(receipts, list)
        or not receipts
        or any(type(value) is not str or not value.strip() for value in receipts)
        or manifest_receipts != receipts
        or metadata_receipts != receipts
    ):
        raise ValueError("hourly research first-admission recovery receipts are invalid")
    if (
        manifest.get("trade_date") != business_date
        or manifest.get("hourly_slot") != slot
        or manifest.get("pit_cutoff") != cutoff_text
        or manifest.get("capture_origin") != "LATE_RECOVERY"
        or manifest.get("original_time_capture") is not False
        or manifest.get("natural_execution_verified") is not False
        or metadata.get("trade_date") != business_date
        or metadata.get("slot") != slot
        or metadata.get("pit_cutoff") != cutoff_text
        or metadata.get("source_path") != canonical_path.as_posix()
        or metadata.get("original_source_path") != canonical_path.as_posix()
        or metadata.get("original_source_sha256") not in {None, ""}
        or metadata.get("supersedes") not in {None, ""}
        or metadata.get("retry_of_sha256") not in {None, ""}
        or metadata.get("capture_origin") != "LATE_RECOVERY"
        or metadata.get("original_time_capture") is not False
        or metadata.get("natural_execution_verified") is not False
        or recovery_payload.get("repair_authorization") is not None
        or metadata.get("repair_authorization") is not None
    ):
        raise ValueError("hourly research first-admission recovery provenance is invalid")
    return {
        "original_source_path": canonical_path.as_posix(),
        "original_source_sha256": None,
        "source_receipts": list(receipts),
        "repair_authorization": None,
        "pit_cutoff": cutoff_text,
        "first_admission": True,
    }


def _publish_runtime_evidence(
    *,
    data_root: Path,
    business_date: str,
    slot: str,
    mode: str,
    source_sha256: str,
    publication: dict[str, Any] | None,
    execution_origin: str = "ORIGINAL_SLOT",
    natural_execution_verified: bool = False,
    ready_empty: bool = False,
    source_partial: bool = False,
) -> dict[str, Any]:
    store = NativeDataStore(data_root)
    artifact_relative = f"hourly_research/{business_date}/{slot}/summary.json"
    summary = {
        "schema_version": "v3_5.hourly_research_summary.v1",
        "status": "PARTIAL_WITH_ROWS" if source_partial else "READY_EMPTY" if ready_empty else "READY_WITH_RESEARCH_POOL",
        "source_status": "PARTIAL" if source_partial else "READY_EMPTY" if ready_empty else "READY",
        "business_date": business_date,
        "trade_date": business_date,
        "slot": slot,
        "mode": mode,
        "source_sha256": source_sha256,
        "payload_path": "" if ready_empty else str(publication.get("payload_path") or ""),
        "payload_sha256": "" if ready_empty else str(publication.get("payload_sha256") or ""),
        "execution_origin": execution_origin,
        "natural_execution_verified": bool(natural_execution_verified),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    store._write(artifact_relative, summary)
    event = {
        "schema_version": "v3_5.research_event.v1",
        "status": "READY",
        "trade_date": business_date,
        "slot": slot,
        "event_id": f"research:{business_date}:{slot}:{source_sha256[:12]}",
        "source_status": "PARTIAL" if source_partial else "READY_EMPTY" if ready_empty else "READY",
        "event_reason": (
            "hourly_research_late_recovery_completed"
            if execution_origin == "LATE_RECOVERY"
            else "hourly_research_manual_recovery_completed"
            if execution_origin == "MANUAL_RECOVERY"
            else "hourly_research_generation_completed"
        ),
        "execution_origin": execution_origin,
        "natural_execution_verified": bool(natural_execution_verified),
        "artifact_path": artifact_relative,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "default_status": "RESEARCH_ONLY",
        "buy_gate_effect": "none",
        "live_order_effect": "none",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if mode == "LIVE":
        event_relative = (
            "research_module/runtime_outputs/events/latest_research_event.json"
        )
        event_path = resolve_owned_path(data_root, event_relative)
        existing: dict[str, Any] = {}
        if event_path.is_file():
            try:
                loaded = json.loads(event_path.read_text(encoding="utf-8-sig"))
                existing = dict(loaded) if isinstance(loaded, dict) else {}
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                existing = {}
        existing_key = (str(existing.get("trade_date") or ""), str(existing.get("slot") or ""))
        if existing_key <= (business_date, slot):
            store._write(event_relative, event)
    for node_id in (
        "hourly_research_delta",
        "v3_hourly_research_delta_0730_1530",
    ):
        store._write(
            f"runtime_graph/evidence/node_action_status/{business_date}/{node_id}.json",
            {
                "schema_version": "v3_5.runtime_graph_node_receipt.v1",
                "node_id": node_id,
                "status": "READY",
                "effective_status": "READY",
                "source_status": "PARTIAL" if source_partial else "READY_EMPTY" if ready_empty else "READY",
                "business_date": business_date,
                "trade_date": business_date,
                "slot": slot,
                "artifact_path": artifact_relative,
                "source_sha256": source_sha256,
                "execution_origin": execution_origin,
                "natural_execution_verified": bool(natural_execution_verified),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )
    return {
        "runtime_status": summary["status"],
        "runtime_artifact_path": artifact_relative,
        "runtime_event_id": event["event_id"],
        "execution_origin": execution_origin,
        "natural_execution_verified": bool(natural_execution_verified),
    }


def _verified_manual_empty_source(
    *, data_root: Path, source_payload: dict[str, Any], source_sha256: str,
    source_identity: str, business_date: str, slot: str, mode: str,
) -> bool:
    if (business_date, slot, mode) != ("20261012", "1700", "LIVE"):
        return False
    expected_input = f"research/incoming/{business_date}/{slot}.json"
    if source_identity != expected_input:
        return False
    input_path = resolve_owned_path(data_root, expected_input)
    try:
        input_bytes = input_path.read_bytes()
        source = json.loads(input_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if hashlib.sha256(input_bytes).hexdigest() != source_sha256 or source != source_payload:
        return False
    manifest = source.get("source_manifest")
    hourly = source.get("hourly_research")
    expected_receipt = (
        f"research_module/runtime_outputs/zsxq_hourly/{business_date}/{slot}/"
        f"v35_zsxq_hourly_status_{business_date}_{slot}.json"
    )
    if (
        not isinstance(manifest, dict) or not isinstance(hourly, dict)
        or source.get("schema_version") != "v3_research_lane.v2"
        or source.get("trade_date") != business_date or source.get("slot") != slot
        or manifest.get("trade_date") != business_date
        or manifest.get("hourly_slot") != slot
        or manifest.get("source_receipts") != [expected_receipt]
        or manifest.get("capture_origin") != "ORIGINAL_SLOT"
        or manifest.get("original_time_capture") is not True
        or manifest.get("materialization_origin") != "MANUAL_RECOVERY"
        or manifest.get("natural_execution_verified") is not False
        or hourly.get("status") != "READY_EMPTY"
        or hourly.get("trade_date") != business_date
        or hourly.get("latest_slot") != slot
        or type(hourly.get("row_count")) is not int or hourly.get("row_count") != 0
        or any(source.get(name) != [] for name in (
            "raw_items", "research_items", "stock_research_timeline", "stock_research_daily"
        ))
        or source.get("write_policy") != "read_only"
        or source.get("default_status") != "RESEARCH_ONLY"
        or source.get("buy_gate_effect") != "none"
        or source.get("live_order_effect") != "none"
        or any(source.get(key) is not False for key in (
            "production_allowed", "buy_gate_updated", "orders_sent"
        ) if key in source)
    ):
        return False
    evidence = read_zsxq_slot_evidence(data_root, business_date, slot)
    if evidence is None:
        return False
    status_path, status = evidence.status_path, evidence.status
    try:
        cutoff = collector_source_cutoff(business_date, slot)
    except ValueError:
        return False
    fetched = strict_source_receipt_time(status.get("fetched_at"))
    source_cutoff = strict_source_receipt_time(status.get("source_cutoff"))
    materialized = strict_source_receipt_time(manifest.get("materialized_at"))
    available = strict_source_receipt_time(manifest.get("available_at"))
    if fetched is None or source_cutoff is None or materialized is None or available is None:
        return False
        return False
    receipt_sha = evidence.status_sha256
    if (
        status.get("schema_version") != "v3_5.zsxq_hourly_delta.v1"
        or status.get("source") != "zsxq"
        or status.get("trade_date") != business_date
        or status.get("slot") != slot
        or status.get("status_path") != expected_receipt
        or status.get("status") != "READY_EMPTY"
        or status.get("fetch_ok") is not True
        or status.get("production_allowed") is not False
        or status.get("buy_gate_updated") is not False
        or status.get("orders_sent") is not False
    ):
        return False
    proof = manifest.get("ready_empty_source_proof")
    expected_proof = {
        "schema_version": "v3_5.zsxq_ready_empty.v1",
        "trade_date": business_date, "slot": slot, "status": "READY_EMPTY",
        "source_receipt_path": expected_receipt,
        "source_receipt_sha256": receipt_sha,
        "summary_sha256": evidence.summary_sha256,
        "fetch_result_sha256": evidence.fetch_result_sha256,
        "fetch_ok": True, "fetch_success": True,
        "page_count": status.get("page_count"),
        "topic_count": 0, "effective_topic_count": 0,
        "fetched_at": status.get("fetched_at"),
        "source_cutoff": status.get("source_cutoff"),
        "capture_origin": "ORIGINAL_SLOT",
        "materialization_origin": "MANUAL_RECOVERY",
        "materialized_at": manifest.get("materialized_at"),
        "available_at": manifest.get("available_at"),
        "natural_execution_verified": False,
    }
    if (
        evidence.status_sha256 != receipt_sha
        or manifest.get("source_receipt_sha256") != receipt_sha
        or manifest.get("source_cutoff") != status.get("source_cutoff")
        or manifest.get("pit_cutoff") != status.get("source_cutoff")
        or manifest.get("fetched_at") != status.get("fetched_at")
        or manifest.get("generated_at") != manifest.get("materialized_at")
        or manifest.get("published_at") != manifest.get("materialized_at")
        or manifest.get("available_at") != manifest.get("materialized_at")
        or proof != expected_proof
        or source_cutoff != cutoff
        or fetched.strftime("%Y%m%d") != business_date or fetched > cutoff
        or materialized.strftime("%Y%m%d") != business_date
        or materialized < cutoff or available != materialized
    ):
        return False
    return True


def _timestamp(value: Any, field: str) -> datetime:
    return runner_timestamp(value, field)


def _validate_point_in_time_source(
    source: dict[str, Any],
    *,
    business_date: str,
    slot: str,
    allow_late_observation_times: bool = False,
    allow_manual_materialization: bool = False,
    publication_available_at: datetime | None = None,
) -> None:
    return validate_runner_point_in_time_source(
        source,
        business_date=business_date,
        slot=slot,
        allow_late_observation_times=allow_late_observation_times,
        allow_manual_materialization=allow_manual_materialization,
        publication_available_at=publication_available_at,
    )


def run_hourly_research_file(
    *,
    data_root: Path,
    source: Path | None,
    business_date: str,
    target_date: str,
    slot: str,
    mode: str,
) -> dict[str, Any]:
    normalized_mode = DispatchMode(str(mode).upper())
    request = DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=target_date,
        slot=slot,
        mode=normalized_mode,
    )
    if request.target_date != request.business_date:
        raise ValueError(
            "hourly research target_date must equal business_date"
        )
    data_root = Path(data_root)
    source_path = (
        _default_source(data_root, request.business_date, request.slot)
        if source is None
        else Path(source)
    )
    raw = source_path.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    source_payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(source_payload, dict):
        raise ValueError("hourly research source must be an object")
    try:
        source_identity = source_path.resolve().relative_to(data_root.resolve()).as_posix()
    except ValueError:
        source_identity = (
            f"research/incoming/{request.business_date}/{request.slot}.json"
            if source is None
            else "EXTERNAL_READ_ONLY"
        )
    recovery_match = re.fullmatch(
        rf"{re.escape(request.slot)}\.recovery-([0-9a-f]{{16}})\.json",
        source_path.name,
    )
    recovery_gaps = source_payload.get("cannot_confirm")
    recovery_metadata = source_payload.get("recovery_metadata")
    if recovery_metadata is not None and not isinstance(recovery_metadata, dict):
        raise ValueError("hourly research recovery provenance is invalid")
    has_late_recovery_gap = (
        isinstance(recovery_gaps, list)
        and any(
            isinstance(gap, dict)
            and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
            for gap in recovery_gaps
        )
    )
    verified_recovery = False
    recovery_info: dict[str, Any] | None = None
    if recovery_match is not None and source is not None:
        try:
            recovery_info = validate_hourly_recovery_provenance(
                data_root=data_root,
                archive_date=request.business_date,
                slot=request.slot,
                recovery_path=source_path,
                recovery_sha256=source_sha,
                recovery_payload=source_payload,
                require_explicit_authorization=not has_late_recovery_gap,
            )
        except ValueError as error:
            # Only the collector's exact late-observation boundary may open
            # the no-preimage first-admission path.  A recovery-shaped file
            # without that typed gap still requires the normal formal source
            # and authorization proof; never turn an unrelated failure into a
            # first-admission success.
            if not has_late_recovery_gap:
                raise ValueError("hourly research recovery provenance is invalid") from error
            # A late 2100 source may be the first observation for the slot.
            # In that case the collector emits a recovery artifact while the
            # canonical incoming preimage is absent, so the general CAS
            # validator (which intentionally requires an old source) cannot
            # apply.  Validate the no-preimage boundary explicitly instead.
            try:
                recovery_info = _validate_first_late_recovery_provenance(
                    data_root=data_root,
                    business_date=request.business_date,
                    slot=request.slot,
                    recovery_path=source_path,
                    recovery_sha256=source_sha,
                    recovery_payload=source_payload,
                )
            except ValueError:
                raise ValueError("hourly research recovery provenance is invalid") from error
        verified_recovery = True
    elif recovery_match is not None:
        raise ValueError("hourly research recovery provenance is invalid")
    verified_late_recovery = bool(
        verified_recovery
        and (
            has_late_recovery_gap
            or (recovery_info or {}).get("repair_authorization") is not None
        )
    )
    verified_manual_empty = _verified_manual_empty_source(
        data_root=data_root,
        source_payload=source_payload,
        source_sha256=source_sha,
        source_identity=source_identity,
        business_date=request.business_date,
        slot=request.slot,
        mode=request.mode.value,
    )
    # Let a structurally empty manual candidate reach the explicit
    # NOT_MATERIALIZED boundary when its source receipt no longer verifies.
    # This clock allowance does not authorize archive publication.
    source_manifest = source_payload.get("source_manifest")
    source_hourly = source_payload.get("hourly_research")
    manual_empty_time_shape = (
            source is None
            and runner_manual_empty_time_shape(
                source_payload,
                business_date=request.business_date,
                slot=request.slot,
                mode=request.mode.value,
            )
        )
    if verified_recovery:
        manifest = source_payload.get("source_manifest")
        cutoff = runner_source_cutoff(request.business_date, request.slot)
        declared_cutoff = (
            manifest.get("pit_cutoff")
            if isinstance(manifest, dict)
            else None
        )
        if (
            not isinstance(manifest, dict)
            or manifest.get("trade_date") != request.business_date
            or manifest.get("hourly_slot") != request.slot
            or declared_cutoff is None
            or _timestamp(declared_cutoff, "source_manifest.pit_cutoff")
            != cutoff
        ):
            raise ValueError("hourly research recovery provenance is invalid")
    manual_empty_time_allowed = verified_manual_empty or manual_empty_time_shape
    input_publication = None
    if isinstance(source_manifest, dict) and source_manifest.get('producer') == 'ops.collect_hourly_research_input':
        from infrastructure.manager_input_attestation import read_attestation, aware
        input_publication = read_attestation(
            source_path, data_root=data_root, owner_root=Path(__file__).resolve().parents[1],
            as_of=datetime.now(_SHANGHAI),
        )
        if input_publication['artifact_sha256'] != source_sha:
            raise ValueError('HOURLY_PUBLICATION_SOURCE_SHA_MISMATCH')
        validate_hourly_stage_source(
            source_payload, trade_date=request.business_date, slot=request.slot,
            cutoff=aware(input_publication['available_at']),
            manifest_pit_cutoff=collector_source_cutoff(request.business_date, request.slot),
        )
    _validate_point_in_time_source(
        source_payload,
        business_date=request.business_date,
        slot=request.slot,
        allow_late_observation_times=(
            verified_late_recovery or verified_manual_empty or manual_empty_time_shape
        ),
        allow_manual_materialization=manual_empty_time_allowed,
        publication_available_at=aware(input_publication["available_at"]) if input_publication else None,
    )
    store = HourlyResearchStore(data_root)
    transformer_identity_sha = _research_transformer_identity_sha256()
    has_rows = bool(source_payload.get("stock_research_timeline")) and bool(
        source_payload.get("stock_research_daily")
    )
    # A completed collector with no research rows is an upstream evidence
    # boundary, not a successful empty hourly artifact.  Keep compatibility
    # with older hand-built inputs that only carry the canonical timeline and
    # daily collections, while rejecting the current collector's explicit
    # empty raw/normalized collections before touching the formal store.
    raw_items = source_payload.get("raw_items")
    research_items = source_payload.get("research_items")
    if isinstance(raw_items, list) and isinstance(research_items, list):
        has_rows = has_rows and bool(raw_items) and bool(research_items)
    if not has_rows and not verified_manual_empty:
        return {
            "schema_version": "v3_5.hourly_research_run.v1",
            "status": "NOT_MATERIALIZED",
            "failure_class": "UPSTREAM_NOT_READY",
            "reason": "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED",
            "hourly_artifact_status": "NOT_MATERIALIZED",
            "business_date": request.business_date,
            "target_date": request.target_date,
            "slot": request.slot,
            "mode": request.mode.value,
            "source_path": source_identity,
            "external_source_sha256": source_sha,
            "external_source_read_only": True,
            "execution_origin": "LATE_RECOVERY" if verified_recovery else "ORIGINAL_SLOT",
            "natural_execution_verified": False,
            "row_count": 0,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    existing_payload = (
        store.read_exact(
            request.business_date,
            request.slot,
            mode=request.mode.value,
        )
        if verified_recovery
        else None
    )
    first_admission_recovery = bool(
        verified_recovery and (recovery_info or {}).get("first_admission") is True
    )
    late_first_admission = bool(
        verified_recovery
        and has_late_recovery_gap
        and existing_payload is None
    )
    previous_source_sha = (
        str(existing_payload.get("source_input_sha256") or "")
        if existing_payload is not None
        else ""
    )
    recovery_continuation = False
    first_admission_continuation = False
    expected_hourly_sha = ""
    recovery_provenance: dict[str, Any] | None = None
    if verified_recovery:
        supersedes = str(
            source_payload.get("supersedes")
            or (recovery_metadata or {}).get("supersedes")
            or ""
        ).lower()
        if existing_payload is None and not late_first_admission:
            raise ValueError("hourly research late recovery requires an existing artifact")
        if existing_payload is not None:
            if supersedes and supersedes == previous_source_sha:
                expected_hourly_sha = _sha256(existing_payload)
            elif source_sha == previous_source_sha:
                formal_supersession_relative = HourlyResearchStore._supersession_relative(
                    request.business_date,
                    request.slot,
                    request.mode.value,
                    _sha256(existing_payload),
                )
                formal_supersession_present = store._path(
                    formal_supersession_relative
                ).is_file()
                if (first_admission_recovery and not supersedes) or not formal_supersession_present:
                    # The formal artifact may already be committed after a
                    # first-admission generic publish interruption.  There is
                    # deliberately no formal CAS bridge for that path.
                    first_admission_continuation = True
                else:
                    recovery_continuation = True
            else:
                raise ValueError("hourly research late recovery source mismatch")
        recovery_provenance = {
            "source_path": source_identity,
            "source_input_sha256": source_sha,
            "supersedes_source_sha256": supersedes,
            "trade_date": request.business_date,
            "slot": request.slot,
            "source_manifest": dict(source_payload.get("source_manifest") or {}),
            "recovery_metadata": dict(recovery_metadata or {}),
            "source_receipts": list(
                (recovery_info or {}).get("source_receipts") or []
            ),
            "cannot_confirm": source_payload.get("cannot_confirm"),
            "original_source_path": (recovery_info or {}).get(
                "original_source_path"
            ),
            "original_source_sha256": (recovery_info or {}).get(
                "original_source_sha256"
            ),
            "repair_authorization": (recovery_info or {}).get(
                "repair_authorization"
            ),
            "capture_origin": "LATE_RECOVERY",
            "natural_execution_verified": False,
        }
    # Preserve the exact already-read source bytes; do not change source, archive, receipt or phase6 identity. A previous import may gain this missing witness on retry without replacing any published artifact.
    source_relative = f"research/hourly/source/{source_sha}.json"
    source_io = SafeRoot(data_root)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("HOURLY_SOURCE_WITNESS_TOO_LARGE")
    try:
        prior_source = source_io.read_bytes(source_relative)
    except FileNotFoundError:
        try:
            source_io.write_bytes(source_relative, raw, require_absent=True)
        except FileExistsError:
            if source_io.read_bytes(source_relative) != raw:
                raise ValueError("HOURLY_SOURCE_WITNESS_SHA_CONFLICT")
    else:
        if prior_source != raw:
            raise ValueError("HOURLY_SOURCE_WITNESS_SHA_CONFLICT")
    publication = None
    late_recovery_reuse = False
    archive_payload: dict[str, Any] | None = None
    if has_rows or verified_manual_empty:
        if verified_recovery:
            # Build before the first store mutation so a retry can compare
            # the already-committed hourly payload and the generic archive
            # preimage while the lane is still unchanged.
            archive_payload = build_research_archive(
                source_payload,
                source_input_sha256=source_sha,
            )
            if archive_payload["archive_date"] != request.business_date:
                raise ValueError("hourly research source date mismatch")
            generic_bridge_validated = False
            if recovery_continuation:
                # Validate the formal CAS bridge before looking at the generic
                # digest.  A matching current digest alone is not proof that
                # the generic supersession receipt still binds the same
                # preimage, reason and recovery provenance.
                continuation = store.verify_recovery_replacement(
                    existing_payload,
                    slot=request.slot,
                    mode=request.mode.value,
                    current_source_sha256=source_sha,
                    previous_source_sha256=str(
                        recovery_provenance["supersedes_source_sha256"]
                    ),
                    reason="VERIFIED_LATE_SOURCE_RECOVERY",
                    transformer_identity_sha256=transformer_identity_sha,
                    source_provenance=recovery_provenance,
                    natural_execution_verified=False,
                )
                if continuation["payload_sha256"] != _sha256(archive_payload):
                    raise ValueError(
                        "hourly research recovery replacement payload mismatch"
                    )
                expected_hourly_sha = continuation["previous_payload_sha256"]
            if (
                request.mode is DispatchMode.LIVE
                and request.slot == "2100"
            ):
                archive_store = ResearchArchiveStore(data_root)
                generic_existing = archive_store.read_exact(request.business_date)
                generic_digest = (
                    _sha256(generic_existing) if generic_existing is not None else ""
                )
                new_digest = _sha256(archive_payload)
                allowed_generic_digests = {new_digest}
                if late_first_admission or first_admission_continuation:
                    # A first late admission has no generic preimage.  An
                    # empty digest is the only valid absence; a completed
                    # retry may also see the new archive already present.
                    allowed_generic_digests.add("")
                if expected_hourly_sha:
                    allowed_generic_digests.add(expected_hourly_sha)
                if generic_digest not in allowed_generic_digests:
                    raise ValueError("research archive replacement source mismatch")
                if first_admission_continuation and generic_digest == new_digest:
                    # First-admission generic publication is immutable and has
                    # no supersession bridge.  A matching current archive is
                    # therefore the complete retry proof.
                    generic_bridge_validated = True
                elif recovery_continuation and generic_digest == new_digest:
                    # This is an already-completed generic replacement.  Run
                    # its full content-addressed validation before any formal
                    # reuse so a tampered bridge cannot be accepted.
                    archive_store.replace(
                        archive_payload,
                        mode="LIVE",
                        expected_sha256=expected_hourly_sha,
                        reason="VERIFIED_LATE_SOURCE_RECOVERY",
                        source_provenance=recovery_provenance,
                    )
                    generic_bridge_validated = True
            if late_first_admission:
                # The first late canonical has no formal preimage.  Publish
                # immutably and retain the source's late provenance; CAS
                # replacement remains the only path once a formal exists.
                publication = store.publish(
                    archive_payload,
                    slot=request.slot,
                    mode=request.mode.value,
                    transformer_identity_sha256=transformer_identity_sha,
                )
            elif first_admission_continuation:
                publication = store.reuse_matching_source(
                    request.business_date,
                    request.slot,
                    mode=request.mode.value,
                    source_input_sha256=source_sha,
                    transformer_identity_sha256=transformer_identity_sha,
                )
                if publication is None:
                    raise ValueError(
                        "hourly research first-admission formal artifact is incomplete"
                    )
                late_recovery_reuse = generic_bridge_validated
            elif recovery_continuation:
                publication = store.replace(
                    archive_payload,
                    slot=request.slot,
                    mode=request.mode.value,
                    expected_sha256=expected_hourly_sha,
                    reason="VERIFIED_LATE_SOURCE_RECOVERY",
                    transformer_identity_sha256=transformer_identity_sha,
                    expected_source_sha256=str(
                        recovery_provenance["supersedes_source_sha256"]
                    ),
                    source_provenance=recovery_provenance,
                    natural_execution_verified=False,
                )
            else:
                publication = store.replace(
                    archive_payload,
                    slot=request.slot,
                    mode=request.mode.value,
                    expected_sha256=expected_hourly_sha,
                    reason="VERIFIED_LATE_SOURCE_RECOVERY",
                    transformer_identity_sha256=transformer_identity_sha,
                    expected_source_sha256=str(
                        recovery_provenance["supersedes_source_sha256"]
                    ),
                    source_provenance=recovery_provenance,
                    natural_execution_verified=False,
                )
        else:
            publication = store.reuse_matching_source(
                request.business_date,
                request.slot,
                mode=request.mode.value,
                source_input_sha256=source_sha,
                transformer_identity_sha256=transformer_identity_sha,
            )
            if publication is None:
                archive_payload = build_research_archive(
                    source_payload,
                    source_input_sha256=source_sha,
                )
                if archive_payload["archive_date"] != request.business_date:
                    raise ValueError("hourly research source date mismatch")
                publication = store.publish(
                    archive_payload,
                    slot=request.slot,
                    mode=request.mode.value,
                    transformer_identity_sha256=transformer_identity_sha,
                )
    exact_archive_publication = None
    if (
        has_rows
        and request.mode is DispatchMode.LIVE
        and request.slot == "2100"
    ):
        if archive_payload is None:
            archive_payload = store.read_exact(
                request.business_date,
                request.slot,
                mode=request.mode.value,
            )
        if archive_payload is None:
            raise ValueError("verified LIVE 2100 archive is missing")
        archive_store = ResearchArchiveStore(data_root)
        if verified_recovery:
            if late_first_admission or first_admission_continuation or late_recovery_reuse:
                exact_archive_publication = archive_store.publish(
                    archive_payload,
                    mode="LIVE",
                )
            else:
                exact_archive_publication = archive_store.replace(
                    archive_payload,
                    mode="LIVE",
                    expected_sha256=expected_hourly_sha,
                    reason="VERIFIED_LATE_SOURCE_RECOVERY",
                    source_provenance=recovery_provenance,
                )
        else:
            exact_archive_publication = archive_store.publish(
                archive_payload,
                mode="LIVE",
            )
    hourly_publication = None
    if input_publication is not None:
        from infrastructure.manager_input_attestation import publish_hourly_attestation
        hourly_publication = publish_hourly_attestation(
            data_root=data_root, owner_root=Path(__file__).resolve().parents[1],
            date=request.business_date, slot=request.slot, mode=request.mode.value,
        )
    runtime_evidence = _publish_runtime_evidence(
        data_root=data_root,
        business_date=request.business_date,
        slot=request.slot,
        mode=request.mode.value,
        source_sha256=source_sha,
        publication=publication,
        execution_origin=(
            "MANUAL_RECOVERY" if verified_manual_empty
            else "LATE_RECOVERY" if verified_recovery
            else "ORIGINAL_SLOT"
        ),
        natural_execution_verified=False,
        ready_empty=verified_manual_empty,
        source_partial=(source_manifest or {}).get("zsxq_source_completeness") == "PARTIAL",
    )
    return {
        "schema_version": "v3_5.hourly_research_run.v1",
        "status": "SUCCEEDED",
        "business_date": request.business_date,
        "target_date": request.target_date,
        "slot": request.slot,
        "mode": request.mode.value,
        "source_path": source_identity,
        "external_source_sha256": source_sha,
        "external_source_read_only": True,
        "execution_origin": (
            "MANUAL_RECOVERY" if verified_manual_empty
            else "LATE_RECOVERY" if verified_recovery
            else "ORIGINAL_SLOT"
        ),
        "capture_origin": "ORIGINAL_SLOT" if verified_manual_empty else (
            "LATE_RECOVERY" if verified_recovery else "ORIGINAL_SLOT"
        ),
        "hourly_artifact_status": "PARTIAL_WITH_ROWS" if (source_manifest or {}).get("zsxq_source_completeness") == "PARTIAL" else "READY_EMPTY" if verified_manual_empty else "READY_WITH_RESEARCH_POOL",
        "source_status": "PARTIAL" if (source_manifest or {}).get("zsxq_source_completeness") == "PARTIAL" else "READY_EMPTY" if verified_manual_empty else "READY",
        "hourly_publication": hourly_publication,
        **(
            {
                "source_receipt_sha256": source_payload["source_manifest"]["source_receipt_sha256"],
                "source_cutoff": source_payload["source_manifest"]["source_cutoff"],
                "fetched_at": source_payload["source_manifest"]["fetched_at"],
                "materialized_at": source_payload["source_manifest"]["materialized_at"],
                "available_at": source_payload["source_manifest"]["available_at"],
            }
            if verified_manual_empty else {}
        ),
        "late_recovery_first_admission": late_first_admission,
        "late_recovery_idempotent_reuse": late_recovery_reuse,
        "natural_execution_verified": False,
        **(publication or {
            "payload_path": "",
            "receipt_path": "",
            "payload_sha256": "",
            "latest_updated": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }),
        **(
            {
                "exact_archive_path": exact_archive_publication["payload_path"],
                "exact_archive_receipt_path": exact_archive_publication[
                    "receipt_path"
                ],
                "exact_archive_payload_sha256": exact_archive_publication[
                    "payload_sha256"
                ],
                "exact_archive_latest_updated": exact_archive_publication[
                    "latest_updated"
                ],
            }
            if exact_archive_publication is not None
            else {}
        ),
        **runtime_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize one V3.5 hourly research slot"
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument(
        "--mode",
        required=True,
        type=str.upper,
        choices=tuple(item.value for item in DispatchMode),
    )
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    try:
        result = run_hourly_research_file(
            data_root=args.data_root,
            source=args.source,
            business_date=args.date,
            target_date=args.target_date,
            slot=args.slot,
            mode=args.mode,
        )
    except FileNotFoundError:
        result = {
            "schema_version": "v3_5.hourly_research_run.v1",
            "status": "NOT_MATERIALIZED",
            "business_date": args.date,
            "target_date": args.target_date,
            "slot": args.slot,
            "mode": args.mode,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"SUCCEEDED", "ALREADY_EXISTS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
