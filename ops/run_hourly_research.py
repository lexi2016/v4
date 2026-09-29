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
import infrastructure.data_store as data_store_module
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from domains.research import build_research_archive
from domains.research_hourly import validate_hourly_stage_source
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore


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


def _research_transformer_identity_sha256() -> str:
    components: dict[str, str] = {}
    for module in (
        research_contract_module,
        research_domain_module,
        data_store_module,
    ):
        source_file = inspect.getsourcefile(module)
        if source_file is None:
            raise ValueError("hourly research transformer source is unavailable")
        components[module.__name__] = hashlib.sha256(
            Path(source_file).read_bytes()
        ).hexdigest()
    identity = {
        "schema_version": "v3_5.research_transformer_identity.v1",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "components": components,
    }
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


def _publish_runtime_evidence(
    *,
    data_root: Path,
    business_date: str,
    slot: str,
    mode: str,
    source_sha256: str,
    source_pit_cutoff: str,
    expected_pit_cutoff: str,
    publication: dict[str, Any] | None,
) -> dict[str, Any]:
    store = NativeDataStore(data_root)
    ready_empty = publication is None
    artifact_relative = f"hourly_research/{business_date}/{slot}/summary.json"
    summary = {
        "schema_version": "v3_5.hourly_research_summary.v1",
        "status": "READY_EMPTY" if ready_empty else "READY_WITH_RESEARCH_POOL",
        "business_date": business_date,
        "trade_date": business_date,
        "slot": slot,
        "mode": mode,
        "source_sha256": source_sha256,
        "source_pit_cutoff": source_pit_cutoff,
        "expected_pit_cutoff": expected_pit_cutoff,
        "payload_path": "" if ready_empty else str(publication.get("payload_path") or ""),
        "payload_sha256": "" if ready_empty else str(publication.get("payload_sha256") or ""),
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
        "event_reason": "hourly_research_generation_completed",
        "artifact_path": artifact_relative,
        "source_sha256": source_sha256,
        "source_pit_cutoff": source_pit_cutoff,
        "expected_pit_cutoff": expected_pit_cutoff,
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
                "business_date": business_date,
                "trade_date": business_date,
                "slot": slot,
                "artifact_path": artifact_relative,
                "source_sha256": source_sha256,
                "source_pit_cutoff": source_pit_cutoff,
                "expected_pit_cutoff": expected_pit_cutoff,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )
    return {
        "runtime_status": summary["status"],
        "runtime_artifact_path": artifact_relative,
        "runtime_event_id": event["event_id"],
    }


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"hourly research point-in-time field is missing: {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"invalid hourly research point-in-time field: {field}"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def _validate_point_in_time_source(
    source: dict[str, Any],
    *,
    business_date: str,
    slot: str,
    allow_late_observation_times: bool = False,
) -> None:
    manifest = source.get("source_manifest")
    if not isinstance(manifest, dict) or manifest.get("hourly_slot") != slot:
        raise ValueError("hourly research source slot is missing or mismatched")
    cutoff = datetime.strptime(
        f"{business_date}{slot}", "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59, microsecond=999999)
    manifest_times = [
        (field, manifest[field])
        for field in ("generated_at", "published_at")
        if manifest.get(field) not in {None, ""}
    ]
    if not manifest_times:
        raise ValueError(
            "hourly research point-in-time manifest timestamp is missing"
        )
    for field, value in manifest_times:
        if _timestamp(value, f"source_manifest.{field}") > cutoff:
            raise ValueError("hourly research source is not point-in-time safe")
    for collection, fields in (
        ("stock_research_timeline", _TIMELINE_TIME_FIELDS),
        ("stock_research_daily", _DAILY_TIME_FIELDS),
    ):
        rows = source.get(collection)
        if not isinstance(rows, list):
            raise ValueError(f"hourly research source {collection} is missing")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"hourly research source {collection} is invalid")
            for field in fields:
                value = row.get(field)
                if value in {None, ""}:
                    continue
                parsed = _timestamp(value, f"{collection}[{index}].{field}")
                if (
                    parsed > cutoff
                    and not (
                        allow_late_observation_times
                        and field in _LATE_RECOVERY_OBSERVATION_FIELDS
                    )
                ):
                    raise ValueError(
                        "hourly research source is not point-in-time safe"
                    )


def run_hourly_research_file(
    *,
    data_root: Path,
    source: Path | None,
    business_date: str,
    target_date: str,
    slot: str,
    mode: str,
    expected_source_sha256: str | None = None,
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
    if expected_source_sha256 is not None and (
        re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256) is None
        or source_sha != expected_source_sha256
    ):
        raise ValueError("HOURLY_SOURCE_SHA_MISMATCH")
    source_payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(source_payload, dict):
        raise ValueError("hourly research source must be an object")
    stage_cutoff = datetime.strptime(
        f"{request.business_date}{request.slot}", "%Y%m%d%H%M"
    ).replace(tzinfo=_SHANGHAI, second=59, microsecond=999999)
    source_manifest = source_payload.get("source_manifest")
    source_pit_cutoff = (
        str(source_manifest.get("pit_cutoff") or "")
        if isinstance(source_manifest, dict)
        else ""
    )
    source_identity = (
        f"research/incoming/{request.business_date}/{request.slot}.json"
        if source is None
        else "EXTERNAL_READ_ONLY"
    )
    recovery_match = re.fullmatch(
        rf"{re.escape(request.slot)}\.recovery-([0-9a-f]{{16}})\.json",
        source_path.name,
    )
    expected_recovery_parent = resolve_owned_path(
        data_root, f"research/incoming/{request.business_date}"
    )
    recovery_gaps = source_payload.get("cannot_confirm")
    verified_late_recovery = (
        source is not None
        and recovery_match is not None
        and source_sha.startswith(recovery_match.group(1))
        and source_path.resolve().parent == expected_recovery_parent.resolve()
        and isinstance(recovery_gaps, list)
        and any(
            isinstance(gap, dict)
            and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
            for gap in recovery_gaps
        )
    )
    _validate_point_in_time_source(
        source_payload,
        business_date=request.business_date,
        slot=request.slot,
        allow_late_observation_times=verified_late_recovery,
    )
    validate_hourly_stage_source(
        source_payload, trade_date=request.business_date, slot=request.slot,
        cutoff=stage_cutoff,
        allow_late_observations=verified_late_recovery,
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
    if not has_rows:
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
            "source_pit_cutoff": source_pit_cutoff,
            "expected_pit_cutoff": stage_cutoff.isoformat(timespec="seconds"),
            "external_source_read_only": True,
            "row_count": 0,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    # Preserve the exact already-read source bytes; do not change source,
    # archive, receipt or phase6 identity. A previous import may gain this
    # missing witness on retry without replacing any published artifact.
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
    archive_payload: dict[str, Any] | None = None
    if has_rows:
        publication = store.reuse_matching_source(
            request.business_date,
            request.slot,
            mode=request.mode.value,
            source_input_sha256=source_sha,
            transformer_identity_sha256=transformer_identity_sha,
        )
    if has_rows and publication is None:
        archive_payload = build_research_archive(
            source_payload,
            source_input_sha256=source_sha,
        )
        if archive_payload["archive_date"] != request.business_date:
            raise ValueError("hourly research source date mismatch")
        # Normal publication is delegated to HourlyResearchStore.publish(),
        # which has the narrow payload-without-receipt recovery path.  Reading
        # first would classify that recoverable interrupted state as a
        # manifest/receipt tamper and prevent the second attempt from
        # reaching the store's idempotent repair logic.  A verified late
        # recovery still requires a complete prior artifact because replace()
        # must CAS against its exact SHA.
        existing_payload = (
            store.read_exact(
                request.business_date,
                request.slot,
                mode=request.mode.value,
            )
            if verified_late_recovery
            else None
        )
        if existing_payload is not None and verified_late_recovery:
            publication = store.replace(
                archive_payload,
                slot=request.slot,
                mode=request.mode.value,
                expected_sha256=_sha256(existing_payload),
                reason="VERIFIED_LATE_SOURCE_RECOVERY",
                transformer_identity_sha256=transformer_identity_sha,
            )
        else:
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
        exact_archive_publication = ResearchArchiveStore(data_root).publish(
            archive_payload,
            mode="LIVE",
        )
    runtime_evidence = _publish_runtime_evidence(
        data_root=data_root,
        business_date=request.business_date,
        slot=request.slot,
        mode=request.mode.value,
        source_sha256=source_sha,
        source_pit_cutoff=source_pit_cutoff,
        expected_pit_cutoff=stage_cutoff.isoformat(timespec="seconds"),
        publication=publication,
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
        "source_pit_cutoff": source_pit_cutoff,
        "expected_pit_cutoff": stage_cutoff.isoformat(timespec="seconds"),
        "external_source_read_only": True,
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
    parser.add_argument("--expected-source-sha256", help="Optional approved raw-byte SHA; checked before writing")
    args = parser.parse_args()
    try:
        result = run_hourly_research_file(
            data_root=args.data_root,
            source=args.source,
            business_date=args.date,
            target_date=args.target_date,
            slot=args.slot,
            mode=args.mode,
            expected_source_sha256=args.expected_source_sha256,
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
