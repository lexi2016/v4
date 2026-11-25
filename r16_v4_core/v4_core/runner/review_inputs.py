"""Materialize verified research inputs and compose the candidate Review Core record."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable
import uuid

from v4_core.config import V4Config
from v4_core.runner.a_daily_authority import read_a_daily_publication
from v4_core.runner.cache_lanes import read_stage7
from v4_core.runner.daily_products import build_fupan_pool, build_next_day_observation
from v4_core.runner.evidence import DatedInputs, EvidenceError, SAFETY_FLAGS, aware_time, iso_date, mapping, require
from v4_core.runner.native_research import build_hk_close, build_hourly_archive
from v4_core.runner.state import json_bytes, publish_bytes, publish_json
from v4_core.storage.db import V4Store

_REVIEW_ROLES = {
    "next_day_observation": "NEXT_DAY_OBSERVATION_EDITION",
    "fupan": "FUPAN_REVIEW_BUNDLE",
}


def _safe_native(record: dict, reason: str) -> None:
    require(all(record.get(key) is False for key in SAFETY_FLAGS if key != "research_only")
            and record.get("research_only", record.get("RESEARCH_ONLY", True)) is True, reason)


def _workload_entry(inputs: DatedInputs, lane: str) -> dict[str, Any]:
    return mapping(inputs.entry("workloads").get(lane), f"{lane.upper()}_SOURCE_UNBOUND")


def _required_rows(payload: dict, key: str) -> int:
    values = payload.get(key)
    require(isinstance(values, list) and values and all(isinstance(row, dict) for row in values),
            f"WORKLOAD_{key.upper()}_ROWS_UNAVAILABLE")
    return len(values)


def _next_a_session(inputs: DatedInputs) -> str:
    binding = inputs.entry("next_a_session")
    artifact = inputs.file(binding.get("calendar"))
    receipt_file = inputs.file(binding.get("receipt"))
    calendar = mapping(artifact.json(), "NEXT_A_SESSION_CALENDAR_INVALID")
    receipt = mapping(receipt_file.json(), "NEXT_A_SESSION_RECEIPT_INVALID")
    day = inputs.trade_date
    target = iso_date(calendar.get("target_date"))
    require(day < target and calendar.get("schema") == "v4_core.a_session_binding.v1"
            and receipt.get("schema") == "v4_core.a_session_binding_receipt.v1"
            and all(item.get("market") == "A" and iso_date(item.get("source_date")) == day
                    and iso_date(item.get("target_date")) == target and item.get("status") == "READY"
                    for item in (calendar, receipt))
            and receipt.get("calendar_sha256") == artifact.sha256
            and isinstance(calendar.get("source_identity"), str) and calendar["source_identity"]
            and receipt.get("source_identity") == calendar["source_identity"],
            "NEXT_A_SESSION_CALENDAR_BINDING_MISMATCH")
    source_day, target_day = date.fromisoformat(day), date.fromisoformat(target)
    sessions = calendar.get("sessions")
    require(isinstance(sessions, list) and len(sessions) == (target_day - source_day).days + 1,
            "NEXT_A_SESSION_CALENDAR_COVERAGE_MISMATCH")
    for offset, item in enumerate(sessions):
        row = mapping(item, "NEXT_A_SESSION_CALENDAR_ROW_INVALID")
        expected = source_day + timedelta(days=offset)
        require(iso_date(row.get("trade_date")) == expected.isoformat()
                and row.get("is_session") is (expected in {source_day, target_day}),
                "NEXT_A_SESSION_CALENDAR_SEQUENCE_MISMATCH")
    return target


def _validate_research_lane(
    inputs: DatedInputs, lane: str, asof: datetime, *, hourly: dict | None = None,
    cfg: V4Config | None = None, stage_owner_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, list]]:
    entry = _workload_entry(inputs, lane)
    observed = aware_time(entry.get("observed_at"))
    require(observed.date().isoformat() == inputs.trade_date, f"{lane.upper()}_OBSERVED_DATE_MISMATCH")
    require(observed <= asof, f"{lane.upper()}_EVIDENCE_AFTER_READBACK:{observed.isoformat()}")
    if lane == "hourly_announcements":
        require(entry.get("source"), "HOURLY_NATIVE_SOURCE_UNBOUND")
        projection, rows = build_hourly_archive(inputs, entry, asof)
        return _native_with_reference(inputs, lane, entry, observed, projection, rows)
    if lane == "hk_close":
        require(entry.get("close_snapshot") and entry.get("close_snapshot_receipt") and entry.get("model_pool"),
                "HK_CLOSE_NATIVE_SOURCES_UNBOUND")
        projection, rows = build_hk_close(inputs, entry, asof, stage_owner_root=stage_owner_root)
        return _native_with_reference(inputs, lane, entry, observed, projection, rows)
    if lane == "fupan" and entry.get("pool") is not None:
        projection, rows = build_fupan_pool(inputs, entry, _next_a_session(inputs), observed)
        return {**projection, "lane": lane, "trade_date": inputs.trade_date, "observed_at": observed.isoformat()}, rows
    if lane == "next_day_observation" and entry.get("candidate_pool") is not None:
        require(cfg is not None and hourly is not None and hourly.get("status") == "READY",
                "NEXT_DAY_OBSERVATION_HOURLY_PUBLICATION_UNAVAILABLE")
        hourly_rows = _read_hourly_observation_source(cfg, inputs, hourly, observed)
        projection, rows = build_next_day_observation(inputs, entry, _next_a_session(inputs), hourly, hourly_rows)
        return {
            **projection, "lane": lane, "trade_date": inputs.trade_date,
            "observed_at": observed.isoformat(), "finished_at": asof.isoformat(),
        }, rows
    return _external_publication(inputs, lane, entry, observed, hourly=hourly)


def _read_hourly_observation_source(
    cfg: V4Config, inputs: DatedInputs, hourly: dict, observed: datetime,
) -> list[dict]:
    path = cfg.data_dir / "review_inputs" / inputs.trade_date / "hourly_announcements.json"
    try:
        content = path.read_bytes()
        value = mapping(json.loads(content), "OBSERVATION_HOURLY_PUBLICATION_INVALID")
    except (OSError, ValueError) as exc:
        raise EvidenceError("OBSERVATION_HOURLY_PUBLICATION_UNAVAILABLE") from exc
    require(sha256(content).hexdigest() == hourly.get("publication_sha256")
            and value.get("status") == "READY" and iso_date(value.get("trade_date")) == inputs.trade_date
            and value.get("source_binding_sha256") == inputs.entry_sha256("workloads", "hourly_announcements")
            and aware_time(value.get("observed_at")) <= observed, "OBSERVATION_HOURLY_PUBLICATION_SHA_OR_ASOF_MISMATCH")
    rows = mapping(value.get("rows"), "OBSERVATION_HOURLY_ROWS_MISSING").get("stock_pool")
    require(isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows),
            "OBSERVATION_HOURLY_ROWS_MISSING")
    return rows


def _native_with_reference(
    inputs: DatedInputs, lane: str, entry: dict, observed: datetime, projection: dict, rows: dict[str, list],
) -> tuple[dict[str, Any], dict[str, list]]:
    projection.update(lane=lane, trade_date=inputs.trade_date, observed_at=observed.isoformat())
    if entry.get("artifact") is None and entry.get("receipt") is None:
        return projection, rows
    try:
        reference, reference_rows = _external_publication(inputs, lane, entry, observed)
        if lane == "hourly_announcements":
            require(reference_rows["articles"] and projection["source_input_sha256"] == reference["source_input_sha256"],
                    "HOURLY_REFERENCE_NATIVE_SOURCE_MISMATCH")
        projection["reference_identity"] = reference["source_identity"]
        projection["reference_row_parity"] = {
            key: value == reference_rows.get(key) for key, value in rows.items() if key != "stage_rows"
        }
    except EvidenceError as exc:
        projection["reference_status"] = "CANNOT_CONFIRM"
        projection["reference_reason"] = str(exc)
    return projection, rows


def _external_publication(
    inputs: DatedInputs, lane: str, entry: dict, observed: datetime, *, hourly: dict | None = None,
) -> tuple[dict[str, Any], dict[str, list]]:
    artifact = inputs.file(entry.get("artifact"))
    receipt_file = inputs.file(entry.get("receipt"))
    payload = mapping(artifact.json(), f"{lane.upper()}_ARTIFACT_INVALID")
    receipt = mapping(receipt_file.json(), f"{lane.upper()}_RECEIPT_INVALID")
    _safe_native(payload, f"{lane.upper()}_ARTIFACT_UNSAFE")
    source_status = entry.get("status")
    source_identity = {"artifact": artifact.identity(), "receipt": receipt_file.identity()}
    day = inputs.trade_date
    if lane == "hk_close":
        require(iso_date(payload.get("trade_date")) == iso_date(receipt.get("trade_date")) == day
                and receipt.get("source_sha256") == artifact.sha256
                and payload.get("status") == source_status, "HK_CLOSE_NATIVE_BINDING_MISMATCH")
        row_sets = {key: payload.get(key) for key in ("model_rows", "stage_rows", "close_top20")}
        counts = {key: _required_rows(payload, key) for key in row_sets}
        require(source_status in {"MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE", "READY"}, "HK_CLOSE_STATUS_UNRECOGNIZED")
        require(source_status != "READY" or not any(payload.get(key) for key in
                ("cannot_confirm", "missing_stages", "unverified_stages")), "HK_CLOSE_CONTAINS_UNVERIFIED_STAGE")
        status = "READY" if source_status == "READY" else "PARTIAL"
    elif lane == "hourly_announcements":
        require(iso_date(payload.get("archive_date")) == iso_date(receipt.get("archive_date")) == day
                and receipt.get("payload_sha256") == artifact.sha256 and receipt.get("slot") == "1900"
                and receipt.get("mode") == "LIVE"
                and receipt.get("source_input_sha256") == payload.get("source_input_sha256"),
                "HOURLY_ANNOUNCEMENT_NATIVE_BINDING_MISMATCH")
        _safe_native(receipt, "HOURLY_ANNOUNCEMENT_RECEIPT_UNSAFE")
        row_sets = {key: payload.get(key) for key in ("articles", "stock_pool")}
        counts = {"article_count": _required_rows(payload, "articles"),
                  "stock_pool_count": _required_rows(payload, "stock_pool")}
        require(all(payload.get(key) == receipt.get(key) == value for key, value in counts.items())
                and source_status in {"PARTIAL_WITH_ROWS", "READY"} and payload.get("status") == "READY",
                "HOURLY_ANNOUNCEMENT_COUNT_OR_STATUS_MISMATCH")
        require(source_status != "READY" or (receipt.get("source_status") == "READY"
                and receipt.get("natural_execution_verified") is True and not payload.get("cannot_confirm")),
                "HOURLY_ANNOUNCEMENT_UPSTREAM_COMPLETION_UNVERIFIED")
        status = "READY" if source_status == "READY" else "PARTIAL"
    else:
        role = _REVIEW_ROLES[lane]
        manifest_file = inputs.file(entry.get("manifest"))
        manifest = mapping(manifest_file.json(), f"{lane.upper()}_MANIFEST_INVALID")
        _safe_native(manifest, f"{lane.upper()}_MANIFEST_UNSAFE")
        _safe_native(receipt, f"{lane.upper()}_RECEIPT_UNSAFE")
        require(source_status == "READY" and all(
            iso_date(record.get("trade_date")) == day and record.get("role") == role
            and record.get("status") == "READY" for record in (payload, manifest, receipt)
        ) and isinstance(manifest.get("run_id"), str) and manifest["run_id"]
            and receipt.get("run_id") == payload.get("run_id") == manifest["run_id"]
            and receipt.get("manifest_sha256") == manifest_file.sha256
            and receipt.get("artifact_sha256") == manifest.get("artifact_sha256") == artifact.sha256,
            f"{lane.upper()}_AUTHORITATIVE_BINDING_MISMATCH")
        row_sets = {"rows": payload.get("rows")}
        counts = {"row_count": _required_rows(payload, "rows")}
        require(counts["row_count"] == receipt.get("row_count") == manifest.get("row_count"),
                f"{lane.upper()}_ROW_COUNT_MISMATCH")
        if lane == "next_day_observation":
            target = _next_a_session(inputs)
            require(all(iso_date(item.get("target_date")) == target for item in (payload, manifest, receipt)),
                    "OBSERVATION_TARGET_DATE_MISMATCH")
            require(hourly and hourly.get("status") == "READY" and hourly.get("publication_sha256")
                    and all(item.get("upstream_hourly_publication_sha256") == hourly["publication_sha256"]
                            for item in (payload, manifest, receipt)), "OBSERVATION_HOURLY_PUBLICATION_SHA_MISMATCH")
            finished = aware_time(receipt.get("finished_at"))
            require(aware_time(hourly.get("observed_at")) <= finished <= observed
                    and all(aware_time(item.get("finished_at")) == finished for item in (payload, manifest)),
                    "OBSERVATION_COMPLETION_TIME_MISMATCH")
        source_identity["manifest"] = manifest_file.identity()
        status = "READY"
    projection = {
        "source_mode": "VERIFIED_EXTERNAL_PUBLICATION_READBACK",
        "status": status, "source_status": source_status, "trade_date": day, "lane": lane,
        "observed_at": observed.isoformat(), "source_identity": source_identity, **counts, **SAFETY_FLAGS,
    }
    if lane == "hourly_announcements":
        projection["source_input_sha256"] = payload["source_input_sha256"]
    elif lane == "next_day_observation":
        projection.update(target_date=target, finished_at=finished.isoformat(),
                          upstream_hourly_publication_sha256=hourly["publication_sha256"])
    return projection, row_sets


def validate_research_lane(inputs: DatedInputs, lane: str, asof: datetime) -> dict[str, Any]:
    projection, _ = _validate_research_lane(inputs, lane, asof)
    return projection


def materialize_research_lane(
    cfg: V4Config, inputs: DatedInputs, lane: str, asof: datetime, *, hourly: dict | None = None,
    stage_owner_root: Path | None = None,
) -> dict[str, Any]:
    projection, row_sets = _validate_research_lane(
        inputs, lane, asof, hourly=hourly, cfg=cfg, stage_owner_root=stage_owner_root,
    )
    return _persist_research_lane(cfg, inputs, lane, projection, row_sets)


def _persist_research_lane(
    cfg: V4Config, inputs: DatedInputs, lane: str, projection: dict, row_sets: dict[str, list],
) -> dict[str, Any]:
    target = cfg.data_dir / "review_inputs" / inputs.trade_date / f"{lane}.json"
    projection = {**projection, "source_binding_sha256": inputs.entry_sha256("workloads", lane),
                  "publication_path": target.relative_to(cfg.data_dir).as_posix()}
    if lane == "next_day_observation":
        projection["calendar_binding_sha256"] = inputs.entry_sha256("next_a_session")
    descriptor = json_bytes({"schema": "v4_core.review_input.v1", **projection, "rows": row_sets})
    if target.is_file() and target.read_bytes() == descriptor:
        digest = sha256(descriptor).hexdigest()
    else:
        digest = publish_bytes(target, descriptor)
    return {**projection, "publication_sha256": digest}


def await_linked_observation(
    cfg: V4Config, hourly: dict, deadline: datetime,
    clock: Callable[[], datetime], sleep: Callable[[float], None], *,
    loader: Callable[[], tuple[DatedInputs | None, str]],
) -> tuple[dict, datetime]:
    day = hourly["trade_date"]
    lane = "next_day_observation"
    while True:
        observed = min(clock(), deadline)
        try:
            inputs, gap = loader()
            require(inputs is not None, gap)
            require(inputs.trade_date == day and inputs.entry_sha256("workloads", "hourly_announcements") == hourly["source_binding_sha256"],
                    "OBSERVATION_HOURLY_SOURCE_CHANGED_AFTER_PUBLICATION")
            projection, rows = _validate_research_lane(inputs, lane, observed, hourly=hourly, cfg=cfg)
        except EvidenceError as exc:
            if observed >= deadline:
                return {"status": "CANNOT_CONFIRM", "reason": str(exc), **SAFETY_FLAGS}, observed
            sleep(min(5, (deadline - observed).total_seconds()))
        else:
            return _persist_research_lane(cfg, inputs, lane, projection, rows), observed


def lane_or_gap(
    cfg: V4Config, inputs: DatedInputs, lane: str, asof: datetime, *, hourly: dict | None = None,
    stage_owner_root: Path | None = None,
) -> dict[str, Any]:
    try:
        return materialize_research_lane(cfg, inputs, lane, asof, hourly=hourly, stage_owner_root=stage_owner_root)
    except EvidenceError as exc:
        return {"status": "CANNOT_CONFIRM", "reason": str(exc), **SAFETY_FLAGS}


def _read_1610_window(cfg: V4Config, day: str, asof: datetime) -> dict[str, Any]:
    window_path = cfg.logs_dir / "daily_windows" / f"{day}_1610.jsonl"
    try:
        records = [json.loads(line) for line in window_path.read_bytes().splitlines()]
    except (OSError, ValueError) as exc:
        raise EvidenceError("DAILY_1610_WINDOW_RECEIPT_UNAVAILABLE") from exc
    require(records and isinstance(records[-1], dict), "DAILY_1610_WINDOW_RECEIPT_UNAVAILABLE")
    completed = records[-1]
    require(completed.get("phase") == "a_daily" and completed.get("window") == "16:10"
            and iso_date(completed.get("trade_date")) == day
            and completed.get("schedule_status") in {"DONE", "PARTIAL"}
            and aware_time(completed.get("evidence_observed_through")) <= asof,
            "DAILY_1610_WINDOW_RECEIPT_UNBOUND")
    return completed


def read_materialized_hk_close(
    cfg: V4Config, inputs: DatedInputs, asof: datetime, *, allow_2115_upgrade: bool = False,
    stage_owner_root: Path | None = None,
) -> dict[str, Any]:
    day = inputs.trade_date
    completed = _read_1610_window(cfg, day, asof)
    artifact_path = cfg.data_dir / "review_inputs" / day / "hk_close.json"
    try:
        content = artifact_path.read_bytes()
        artifact = mapping(json.loads(content), "HK_CLOSE_CANDIDATE_ARTIFACT_INVALID")
    except (OSError, ValueError) as exc:
        raise EvidenceError("HK_CLOSE_1610_PUBLICATION_UNAVAILABLE") from exc
    paired = mapping(completed.get("paired_workloads"), "HK_CLOSE_1610_WINDOW_RECEIPT_UNBOUND")
    owner = mapping(paired.get("hk_connect_close_review"), "HK_CLOSE_1610_OWNER_RECEIPT_UNBOUND")
    digest = sha256(content).hexdigest()
    require(owner.get("publication_sha256") == digest and artifact.get("schema") == "v4_core.review_input.v1"
            and artifact.get("source_mode") == "NATIVE_INPUT_MATERIALIZATION"
            and iso_date(artifact.get("trade_date")) == day,
            "HK_CLOSE_1610_ARTIFACT_SHA_OR_IDENTITY_MISMATCH")
    require(artifact == {"schema": "v4_core.review_input.v1",
                         **{key: value for key, value in owner.items() if key != "publication_sha256"},
                         "rows": artifact.get("rows")}, "HK_CLOSE_1610_OWNER_RECEIPT_MISMATCH")
    expected_binding = inputs.entry_sha256("workloads", "hk_close")
    if artifact.get("source_binding_sha256") == expected_binding and (
        not allow_2115_upgrade or owner["status"] == "READY" or stage_owner_root is None
    ):
        return owner
    require(allow_2115_upgrade and owner.get("status") == "PARTIAL",
            "HK_CLOSE_1610_ARTIFACT_SHA_OR_IDENTITY_MISMATCH")
    entry = _workload_entry(inputs, "hk_close")
    identities = mapping(owner.get("source_identity"), "HK_CLOSE_1610_OWNER_SOURCE_UNBOUND")
    for key in ("close_snapshot", "close_snapshot_receipt", "model_pool"):
        require(inputs.file(entry.get(key)).identity() == identities.get(key),
                f"HK_CLOSE_2115_BASE_SOURCE_CHANGED:{key}")
    projection, rows = _validate_research_lane(inputs, "hk_close", asof, stage_owner_root=stage_owner_root)
    path = artifact_path.with_name("hk_close_review_2115.json")
    upgraded = {
        **projection, "source_binding_sha256": expected_binding, "original_1610_publication_sha256": digest,
        "publication_path": path.relative_to(cfg.data_dir).as_posix(),
    }
    if projection["status"] != "READY":
        return upgraded
    publication = publish_json(path, {"schema": "v4_core.review_input.v1", **upgraded, "rows": rows})
    return {**upgraded, "publication_sha256": publication}


def read_materialized_a_daily(
    cfg: V4Config, store: V4Store, inputs: DatedInputs, asof: datetime,
) -> dict[str, Any]:
    day = inputs.trade_date
    completed = _read_1610_window(cfg, day, asof)
    owner = mapping(completed.get("workload"), "A_1610_OWNER_RECEIPT_UNBOUND")
    downstream = mapping(owner.get("downstream"), "A_1610_DOWNSTREAM_RECEIPT_UNBOUND")
    require(owner.get("status") in {"READY", "PARTIAL"}
            and downstream.get("trade_date") == day and downstream.get("step") == "all"
            and downstream.get("status") == "DONE" and downstream.get("top200_reference_status") == "READY",
            "A_1610_DOWNSTREAM_NOT_DONE_OR_REFERENCE_GAPS")
    publication = read_a_daily_publication(cfg.data_dir / "history", store, inputs, owner)
    execution = next((item for item in store.get_slot_executions(day) if item["slot_id"] == "slot_4_a_share_daily"), None)
    qfq = mapping(downstream.get("qfq"), "A_1610_QFQ_RECEIPT_UNBOUND")
    require(execution is not None and execution["status"] == "DONE" and execution["trade_date"] == day
            and execution["execution_ref"] == downstream.get("execution_ref")
            and execution["detail"].get("qfq") == qfq
            and all(execution["detail"].get(key) == downstream.get(key) for key in ("top200_count", "workbench_count")),
            "A_1610_DOWNSTREAM_EXECUTION_RECEIPT_MISMATCH")
    scores = store.get_workbench_scores(day)
    top200 = store.get_top200(day)
    with store.connect() as conn:
        all_qfq, target_qfq = conn.execute(
            "SELECT COUNT(*), COUNT(CASE WHEN trade_date=? THEN 1 END) FROM qfq_bars "
            "WHERE market='A' AND asof_date=?", (day, day),
        ).fetchone()
    require(0 < len(top200) == downstream.get("top200_count")
            and 0 < len(scores) == downstream.get("workbench_count")
            and target_qfq == qfq.get("symbols_processed") == publication["accepted_count"]
            and all_qfq == qfq.get("qfq_rows_written"), "A_1610_DOWNSTREAM_PUBLICATION_COUNTS_MISMATCH")
    from v4_core.api.routes_workbench import compute_workbench_lineage

    lineage = compute_workbench_lineage(day, scores)
    require(all(downstream.get(key) == value for key, value in lineage.items()),
            "A_1610_DOWNSTREAM_WORKBENCH_LINEAGE_MISMATCH")
    return {"status": "READY", "source_status": owner["status"], "execution_ref": execution["execution_ref"],
            "counts": {"bars": publication["accepted_count"], "top200": len(top200), "workbench": len(scores)},
            **publication, **SAFETY_FLAGS}


def compose_review_core(
    cfg: V4Config, inputs: DatedInputs, asof: datetime, *, stage_owner_root: Path | None = None,
) -> dict[str, Any]:
    day = inputs.trade_date
    store = V4Store(cfg.db_path)
    run_id = f"review-{uuid.uuid4().hex[:12]}"
    evidence = {"fupan": lane_or_gap(cfg, inputs, "fupan", asof)}
    try:
        evidence["hk_close"] = read_materialized_hk_close(
            cfg, inputs, asof, allow_2115_upgrade=True, stage_owner_root=stage_owner_root,
        )
    except EvidenceError as exc:
        evidence["hk_close"] = {"status": "CANNOT_CONFIRM", "reason": str(exc), **SAFETY_FLAGS}
    try:
        evidence["stage7"], _ = read_stage7(cfg.data_dir, day)
    except EvidenceError as exc:
        evidence["stage7"] = {"status": "CANNOT_CONFIRM", "reason": str(exc), **SAFETY_FLAGS}
    try:
        evidence["a_share_daily"] = read_materialized_a_daily(cfg, store, inputs, asof)
    except EvidenceError as exc:
        evidence["a_share_daily"] = {"status": "CANNOT_CONFIRM", "reason": str(exc), **SAFETY_FLAGS}
    local_counts = evidence["a_share_daily"].get("counts", {})
    missing = [lane for lane, item in evidence.items() if item["status"] != "READY"]
    status = "CANNOT_CONFIRM" if missing else "READY"
    bundle = {
        "schema": "v4_core.review_core_bundle.v1", "trade_date": day, "run_id": run_id,
        "status": status, "cannot_confirm": missing, "inputs": evidence, "a_share_counts": local_counts,
        **SAFETY_FLAGS,
    }
    digest = publish_json(cfg.data_dir / "review_core" / f"{day}.json", bundle)
    detail = {**bundle, "publication_sha256": digest}
    store.save_review_record(day, "GENERATED" if status == "READY" else "CANNOT_CONFIRM", detail, plan_run_id=run_id)
    return store.record_slot_execution(day, "slot_6_review_and_maint", "Review Core复盘池链与维护", "21:15",
                                       "DONE" if status == "READY" else status, run_id, detail)
