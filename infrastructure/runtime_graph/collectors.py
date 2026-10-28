"""Pure, fail-closed evidence collection for the v3 runtime fact graph."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from .contracts import EvidenceLayer, EvidenceResult, GraphStatus
from .contracts import required_evidence_layers
from .validators import validate_semantics
from .v4_native_evidence import (
    V4_ARTIFACT_SOURCE_KINDS,
    V4_EXECUTION_SOURCE_KINDS,
    artifact_record,
    execution_record,
)
from .v4_api_evidence import api_evidence


CalendarDecision = Callable[[str, str], Any]
HttpGet = Callable[[str], Any]
ReadText = Callable[[Path], str]
PathExists = Callable[[Path], bool]
PathLstat = Callable[[Path], os.stat_result | None]

_ARTIFACT_SOURCE_KINDS = frozenset({"json", "text_pointer", "artifact", "manifest", "acceptance", "v35_artifact", "stage_latest"})
_JSON_SOURCE_KINDS = frozenset({"json", "manifest", "acceptance"})
_RECEIPT_SUCCESS = frozenset({"PASS", "READY", "SUCCESS", "COMPLETED", "ACTION_OK"})
_RECEIPT_RUNNING = frozenset({"RUNNING", "STARTED"})
_RECEIPT_FAILURE = frozenset({"FAIL", "FAILED", "ERROR", "ABORTED", "CANCELLED", "ACTION_FAILED"})
_RECEIPT_GAP = frozenset({"ACTION_RAN_WITH_CANNOT_CONFIRM", "BLOCKED_CLOSE_DATA"})
_EXPECTED_CALENDAR_SKIPS = frozenset({"NON_TRADING_DAY"})
_DEFAULT_API_DATE_FIELDS = ("business_date", "trade_date", "current_date", "page_trade_date")
_DEFAULT_RECEIPT_DATE_FIELDS = (
    "business_date",
    "trade_date",
    "execution_date",
    "target_date",
    "current_date",
)
_SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_SHANGHAI = timezone(timedelta(hours=8))


def _safe_value(value: Any) -> Any:
    """Project arbitrary injected values to JSON-safe details without errors."""
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(item) for item in value]
    return str(value)


def _safe_mapping(value: Any) -> dict[str, Any]:
    return _safe_value(value) if isinstance(value, Mapping) else {}


def _default_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _default_path_exists(path: Path) -> bool:
    return path.exists()


def _default_path_lstat(path: Path) -> os.stat_result | None:
    """Inspect link metadata without following it; only absence is non-error."""
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _normal_roots(roots: Mapping[str, Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    for root in roots.values():
        try:
            result.append(Path(os.path.abspath(str(root))))
        except (TypeError, ValueError, OSError):
            continue
    return tuple(result)


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(str(path)), os.path.normcase(str(root)))) == os.path.normcase(str(root))
    except ValueError:
        return False


def _resolve_path(
    value: str,
    business_date: str,
    roots: Mapping[str, Path],
    *,
    base: Path | None = None,
    target_date: str | None = None,
) -> Path | None:
    """Render only known templates and return a lexical path contained in a root."""
    rendered = value
    rendered = rendered.replace("{date}", business_date).replace("{execution_date}", business_date)
    rendered = rendered.replace("{target_date}", target_date or business_date)
    for key, root in roots.items():
        rendered = rendered.replace("{" + str(key) + "}", str(root))
    if "{" in rendered or "}" in rendered:
        return None
    normal_roots = _normal_roots(roots)
    if not normal_roots:
        return None
    try:
        candidate = Path(rendered)
        if not candidate.is_absolute():
            candidate = (base if base is not None else normal_roots[0]) / candidate
        normalized = Path(os.path.abspath(str(candidate)))
    except (TypeError, ValueError, OSError):
        return None
    return normalized if any(_is_within(normalized, root) for root in normal_roots) else None


def _path_exists(path: Path, path_exists: PathExists) -> bool:
    try:
        return path_exists(path) is True
    except Exception:
        return False


def _path_lstat(path: Path, path_lstat: PathLstat) -> os.stat_result | None | object:
    try:
        return path_lstat(path)
    except Exception:
        return _LSTAT_ERROR


_LSTAT_ERROR = object()


def _is_reparse_or_link(metadata: object) -> bool:
    try:
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        return bool(attributes & reparse_flag) or stat.S_ISLNK(int(getattr(metadata, "st_mode", 0)))
    except Exception:
        return True


def _reparse_safe(path: Path, roots: Mapping[str, Path], path_lstat: PathLstat) -> bool:
    """lstat root, every lexical ancestor, and leaf before any following probe."""
    root = next((item for item in _normal_roots(roots) if _is_within(path, item)), None)
    if root is None:
        return False
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        metadata = _path_lstat(current, path_lstat)
        if metadata is _LSTAT_ERROR:
            return False
        if metadata is not None and _is_reparse_or_link(metadata):
            return False
    return True


def _read_mapping(path: Path, read_text: ReadText, path_exists: PathExists) -> tuple[dict[str, Any] | None, str]:
    if not _path_exists(path, path_exists):
        return None, "UNREADABLE"
    try:
        raw = read_text(path)
    except Exception:
        return None, "UNREADABLE"
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None, "MALFORMED"
    if not isinstance(payload, Mapping):
        return None, "MALFORMED"
    return _safe_mapping(payload), "OK"


def _sources(node: Mapping[str, Any], allowed_kinds: frozenset[str] | str) -> list[Mapping[str, Any]]:
    values = node.get("status_sources")
    if not isinstance(values, list | tuple):
        return []
    allowed = {allowed_kinds} if isinstance(allowed_kinds, str) else allowed_kinds
    return [value for value in values if isinstance(value, Mapping) and value.get("kind") in allowed]


def _field_value(payload: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False, None
        value = value[part]
    return True, _safe_value(value)


def _semantic_source(source: Mapping[str, Any], payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Project only declaratively named semantic fields; never retain raw payloads."""
    alias = source.get("semantic_alias")
    declared = source.get("semantic_fields")
    if not isinstance(alias, str) or not alias or not isinstance(declared, Mapping):
        return None
    fields: dict[str, Any] = {}
    if payload is not None:
        for name, path in declared.items():
            if isinstance(name, str) and name and isinstance(path, str) and path:
                present, value = _field_value(payload, path)
                if present:
                    fields[name] = value
    return {"semantic_alias": alias, "semantic_fields": fields}


def _scheduled_start(value: Any) -> time:
    """Return the first due time from the frozen V3 schedule notation."""
    if not isinstance(value, str) or not value:
        raise ValueError("SCHEDULE_INVALID")
    first = value.split("/", 1)[0].split("-", 1)[0]
    try:
        return datetime.strptime(first, "%H:%M").time()
    except ValueError as error:
        raise ValueError("SCHEDULE_INVALID") from error


def _schedule_is_due(*, business_date: str, scheduled_time: Any, now: datetime) -> bool:
    date = datetime.strptime(business_date, "%Y%m%d").date()
    local_now = _normalized_now(now)
    if date != local_now.date():
        return date < local_now.date()
    return local_now.time().replace(tzinfo=None) >= _scheduled_start(scheduled_time)


def _calendar_evidence(
    node: Mapping[str, Any],
    business_date: str,
    now: datetime,
    calendar_decision: CalendarDecision,
) -> tuple[EvidenceResult, bool]:
    try:
        raw_decision = calendar_decision(str(node.get("run_policy") or ""), business_date)
    except Exception:
        return EvidenceResult(EvidenceLayer.CALENDAR, GraphStatus.EVIDENCE_GAP, "CALENDAR_UNAVAILABLE", {}), False
    if not isinstance(raw_decision, Mapping) or type(raw_decision.get("should_run")) is not bool:
        return EvidenceResult(EvidenceLayer.CALENDAR, GraphStatus.EVIDENCE_GAP, "CALENDAR_UNAVAILABLE", {}), False
    decision = _safe_mapping(raw_decision)
    if raw_decision["should_run"] is False:
        status = str(decision.get("status") or "")
        if status not in _EXPECTED_CALENDAR_SKIPS:
            return (
                EvidenceResult(
                    EvidenceLayer.CALENDAR,
                    GraphStatus.EVIDENCE_GAP,
                    "CALENDAR_UNAVAILABLE",
                    decision,
                ),
                False,
            )
        return (
            EvidenceResult(
                EvidenceLayer.CALENDAR,
                GraphStatus.SKIPPED_EXPECTED,
                status,
                decision,
            ),
            False,
        )
    try:
        due = _schedule_is_due(
            business_date=business_date,
            scheduled_time=node.get("scheduled_time"),
            now=now,
        )
    except (TypeError, ValueError):
        return (
            EvidenceResult(
                EvidenceLayer.CALENDAR,
                GraphStatus.EVIDENCE_GAP,
                "SCHEDULE_INVALID",
                decision,
            ),
            False,
        )
    if not due:
        return (
            EvidenceResult(
                EvidenceLayer.CALENDAR,
                GraphStatus.NOT_DUE,
                "SCHEDULE_NOT_DUE",
                {
                    **decision,
                    "scheduled_time": str(node["scheduled_time"]),
                    "evaluated_at": _normalized_now(now).isoformat(timespec="seconds"),
                },
            ),
            False,
        )
    return EvidenceResult(EvidenceLayer.CALENDAR, GraphStatus.PASS, "CALENDAR_OPEN", decision), True


def _receipt_date_fields(node: Mapping[str, Any]) -> tuple[str, ...]:
    declared = node.get("receipt_date_fields")
    if isinstance(declared, list | tuple):
        fields = tuple(item for item in declared if isinstance(item, str) and item)
        if fields:
            return fields
    return _DEFAULT_RECEIPT_DATE_FIELDS


def _safety_boundary_state(payload: Mapping[str, Any]) -> tuple[GraphStatus | None, str | None]:
    values = tuple(payload.get(flag) for flag in _SAFETY_FLAGS)
    if any(value is True for value in values):
        return GraphStatus.FAIL, "SAFETY_BOUNDARY_VIOLATION"
    if values != (False, False, False):
        return GraphStatus.EVIDENCE_GAP, "SAFETY_BOUNDARY_UNCONFIRMED"
    return None, None


def _execution_evidence(
    node: Mapping[str, Any],
    business_date: str,
    roots: Mapping[str, Path],
    read_text: ReadText,
    path_exists: PathExists,
    path_lstat: PathLstat,
    target_date: str | None = None,
) -> EvidenceResult:
    declared = _sources(node, "receipt") + _sources(node, V4_EXECUTION_SOURCE_KINDS)
    if not declared:
        return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.EVIDENCE_GAP, "RECEIPT_UNDECLARED", {})
    date_fields = _receipt_date_fields(node)
    records: list[dict[str, Any]] = []
    for source in declared:
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            records.append({"path": "", "reason": "RECEIPT_PATH_UNSAFE"})
            continue
        source_target_date = target_date if source.get("kind") in V4_EXECUTION_SOURCE_KINDS else None
        path = _resolve_path(raw_path, business_date, roots, target_date=source_target_date)
        if path is None or not _reparse_safe(path, roots, path_lstat):
            records.append({"path": "", "reason": "RECEIPT_PATH_UNSAFE"})
            continue
        receipt, outcome = _read_mapping(path, read_text, path_exists)
        if receipt is None:
            records.append({"path": str(path), "reason": f"RECEIPT_{outcome}"})
            continue
        if source.get("kind") in V4_EXECUTION_SOURCE_KINDS:
            records.append(
                execution_record(
                    source=source,
                    path=path,
                    receipt=receipt,
                    business_date=business_date,
                    target_date=target_date,
                    roots=roots,
                    read_text=read_text,
                    path_exists=path_exists,
                    path_lstat=path_lstat,
                )
            )
            continue
        record: dict[str, Any] = {"path": str(path), "receipt": receipt}
        if receipt.get("node_id") != node.get("node_id"):
            record["reason"] = "RECEIPT_IDENTITY_INVALID"
        else:
            dates = [receipt[field] for field in date_fields if field in receipt]
            if not dates or any(str(value) != business_date for value in dates):
                record["reason"] = "RECEIPT_DATE_INVALID"
            else:
                safety_status, safety_reason = _safety_boundary_state(receipt)
                if safety_status is not None:
                    record["reason"] = safety_reason
                    if safety_status is GraphStatus.FAIL:
                        record["state"] = GraphStatus.FAIL.value
                else:
                    status = str(receipt.get("effective_status") or receipt.get("status") or "").upper()
                    if status in _RECEIPT_FAILURE:
                        record["reason"] = "RECEIPT_FAILED"
                        record["state"] = GraphStatus.FAIL.value
                    elif status in _RECEIPT_RUNNING:
                        record["reason"] = "RECEIPT_RUNNING"
                        record["state"] = GraphStatus.RUNNING.value
                    elif status in _RECEIPT_SUCCESS:
                        record["reason"] = "RECEIPT_PASS"
                        record["state"] = GraphStatus.PASS.value
                    elif status in _RECEIPT_GAP:
                        record["reason"] = "RECEIPT_CANNOT_CONFIRM"
                    else:
                        record["reason"] = "RECEIPT_STATUS_UNRECOGNIZED"
        records.append(record)
    records.sort(key=lambda item: (str(item.get("path") or ""), str(item.get("reason") or "")))
    details = {"receipts": records}
    states = {record.get("state") for record in records}
    if GraphStatus.FAIL.value in states:
        reason = (
            "SAFETY_BOUNDARY_VIOLATION"
            if any(record.get("reason") == "SAFETY_BOUNDARY_VIOLATION" for record in records)
            else "RECEIPT_FAILED"
        )
        return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.FAIL, reason, details)
    invalid_reasons = ("RECEIPT_IDENTITY_INVALID", "RECEIPT_DATE_INVALID")
    for reason in invalid_reasons:
        if any(record.get("reason") == reason for record in records):
            return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.EVIDENCE_GAP, reason, details)
    for reason in ("RECEIPT_PATH_UNSAFE", "RECEIPT_MALFORMED", "RECEIPT_UNREADABLE", "RECEIPT_STATUS_UNRECOGNIZED", "RECEIPT_CANNOT_CONFIRM", "SAFETY_BOUNDARY_UNCONFIRMED", "V4_RECEIPT_DATE_MISMATCH", "V4_RECEIPT_UNDECLARED", "V4_RECEIPT_PATH_UNSAFE", "V4_CHAIN_UNREADABLE_UNREADABLE", "V4_RECEIPT_SHA_MISMATCH", "V4_RECEIPT_IDENTITY_MISMATCH", "V4_RECEIPT_SAFETY_MISMATCH"):
        if any(record.get("reason") == reason for record in records):
            return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.EVIDENCE_GAP, reason, details)
    if GraphStatus.RUNNING.value in states:
        return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.RUNNING, "RECEIPT_RUNNING", details)
    if GraphStatus.PASS.value in states:
        return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.PASS, "RECEIPT_PASS", details)
    return EvidenceResult(EvidenceLayer.EXECUTION, GraphStatus.EVIDENCE_GAP, "RECEIPT_UNREADABLE", details)


def _artifact_evidence(
    node: Mapping[str, Any],
    business_date: str,
    roots: Mapping[str, Path],
    read_text: ReadText,
    path_exists: PathExists,
    path_lstat: PathLstat,
    target_date: str | None = None,
) -> EvidenceResult:
    output_values = node.get("expected_outputs")
    outputs = output_values if isinstance(output_values, list | tuple) else []
    sources = _sources(node, _ARTIFACT_SOURCE_KINDS)
    if not outputs and not sources:
        return EvidenceResult(EvidenceLayer.ARTIFACT, GraphStatus.EVIDENCE_GAP, "ARTIFACT_UNDECLARED", {})
    output_records: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    readable = False
    integrity_failed = False
    fixed_sources = _sources(node, V4_ARTIFACT_SOURCE_KINDS)
    output_target_date = target_date if fixed_sources else None
    for raw_output in outputs:
        if not isinstance(raw_output, str) or not raw_output:
            output_records.append({"path": "", "readable": False})
            continue
        path = _resolve_path(raw_output, business_date, roots, target_date=output_target_date)
        if path is None or not _reparse_safe(path, roots, path_lstat):
            output_records.append({"path": "", "readable": False, "reason": "PATH_UNSAFE"})
            continue
        if path.suffix.lower() == ".json":
            payload, outcome = _read_mapping(path, read_text, path_exists)
            output_records.append({"path": str(path), "readable": payload is not None, "outcome": outcome})
            readable = readable or payload is not None
        else:
            exists = _path_exists(path, path_exists)
            output_records.append({"path": str(path), "exists": exists})
            readable = readable or exists
    for source in sources:
        kind = str(source.get("kind"))
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        source_target_date = target_date if kind in V4_ARTIFACT_SOURCE_KINDS else None
        path = _resolve_path(raw_path, business_date, roots, target_date=source_target_date)
        if path is None or not _reparse_safe(path, roots, path_lstat):
            if kind in V4_ARTIFACT_SOURCE_KINDS:
                integrity_failed = True
            continue
        if kind == "v35_artifact":
            valid, semantic = artifact_record(
                source=source,
                path=path,
                node_id=str(node.get("node_id") or ""),
                business_date=business_date,
                target_date=target_date,
                roots=roots,
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            )
            if not valid:
                integrity_failed = True
                continue
            if semantic is not None:
                source_records.append(semantic)
            readable = True
            continue
        if kind == "stage_latest":
            valid, semantic = artifact_record(
                source=source,
                path=path,
                node_id=str(node.get("node_id") or ""),
                business_date=business_date,
                target_date=target_date,
                roots=roots,
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            )
            if not valid:
                integrity_failed = True
                continue
            if semantic is not None:
                source_records.append(semantic)
            readable = True
            continue
        if kind == "text_pointer":
            pointer_exists = _path_exists(path, path_exists)
            target_path: Path | None = None
            if pointer_exists:
                try:
                    pointer_value = read_text(path).strip()
                except Exception:
                    pointer_value = ""
                if pointer_value:
                    candidate = _resolve_path(pointer_value, business_date, roots, base=path.parent)
                    if candidate is not None and _reparse_safe(candidate, roots, path_lstat):
                        target_path = candidate
            target_exists = bool(target_path and _path_exists(target_path, path_exists))
            readable = readable or (pointer_exists and target_exists)
            continue
        if kind in _JSON_SOURCE_KINDS or path.suffix.lower() == ".json":
            payload, outcome = _read_mapping(path, read_text, path_exists)
            semantic = _semantic_source(source, payload)
            if semantic is not None:
                source_records.append(semantic)
            readable = readable or payload is not None
            continue
        exists = _path_exists(path, path_exists)
        readable = readable or exists
    details = {"outputs": output_records, "sources": source_records, "receipts": []}
    if integrity_failed:
        return EvidenceResult(EvidenceLayer.ARTIFACT, GraphStatus.EVIDENCE_GAP, "V4_INTEGRITY_INVALID", details)
    if not readable:
        return EvidenceResult(EvidenceLayer.ARTIFACT, GraphStatus.EVIDENCE_GAP, "V4_INTEGRITY_INVALID" if integrity_failed else "ARTIFACT_UNREADABLE", details)
    return validate_semantics(
        str(node.get("semantic_validator") or ""),
        details,
        business_date,
        node_id=str(node.get("node_id") or ""),
        target_date=target_date,
    )


def _normal_page_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=_SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(_SHANGHAI)


def _normalized_now(now: datetime) -> datetime:
    return now.replace(tzinfo=_SHANGHAI) if now.tzinfo is None else now.astimezone(_SHANGHAI)


def _page_evidence(
    node: Mapping[str, Any],
    business_date: str,
    now: datetime,
    roots: Mapping[str, Path],
    read_text: ReadText,
    path_exists: PathExists,
    path_lstat: PathLstat,
) -> EvidenceResult:
    raw_path = node.get("page_receipt")
    if not isinstance(raw_path, str) or not raw_path:
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, "PAGE_RECEIPT_UNDECLARED", {})
    path = _resolve_path(raw_path, business_date, roots)
    if path is None or not _reparse_safe(path, roots, path_lstat):
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, "PAGE_RECEIPT_PATH_UNSAFE", {})
    receipt, outcome = _read_mapping(path, read_text, path_exists)
    if receipt is None:
        reason = "PAGE_RECEIPT_MALFORMED" if outcome == "MALFORMED" else "PAGE_RECEIPT_UNREADABLE"
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, reason, {"path": str(path)})
    checked_at = _normal_page_time(receipt.get("checked_at"))
    if checked_at is None:
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, "PAGE_RECEIPT_MALFORMED", {"path": str(path)})
    elapsed_seconds = (_normalized_now(now) - checked_at).total_seconds()
    if elapsed_seconds < -60:
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, "PAGE_RECEIPT_FUTURE", {"path": str(path)})
    if elapsed_seconds > 900:
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.EVIDENCE_GAP, "PAGE_RECEIPT_STALE", {"path": str(path)})
    row_count = receipt.get("row_count")
    valid = (
        receipt.get("schema_version") == "v3_page_receipt.v1"
        and receipt.get("source") == "codex_iab"
        and receipt.get("node_id") == node.get("node_id")
        and receipt.get("business_date") == business_date
        and receipt.get("page_date") == business_date
        and receipt.get("status") == "PASS"
        and receipt.get("loading_state") == "COMPLETE"
        and isinstance(row_count, int)
        and not isinstance(row_count, bool)
        and row_count >= 0
    )
    details = {"path": str(path), "receipt": receipt}
    safety_status, safety_reason = _safety_boundary_state(receipt)
    if safety_status is not None:
        return EvidenceResult(EvidenceLayer.PAGE, safety_status, str(safety_reason), details)
    if not valid:
        return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.FAIL, "PAGE_MISMATCH", details)
    return EvidenceResult(EvidenceLayer.PAGE, GraphStatus.PASS, "PAGE_PASS", details)


def collect_node_evidence(
    *,
    node: Mapping[str, Any],
    business_date: str,
    now: datetime,
    roots: Mapping[str, Path],
    calendar_decision: CalendarDecision,
    http_get: HttpGet,
    target_date: str | None = None,
    read_text: ReadText | None = None,
    path_exists: PathExists | None = None,
    path_lstat: PathLstat | None = None,
) -> tuple[EvidenceResult, ...]:
    """Observe declared evidence only; never mutate or recompute runtime state."""
    reader = read_text or _default_read_text
    exists = path_exists or _default_path_exists
    lstat_reader = path_lstat or _default_path_lstat
    calendar, should_run = _calendar_evidence(node, business_date, now, calendar_decision)
    if not should_run:
        return (calendar,)
    required = required_evidence_layers(node)
    evidence: dict[EvidenceLayer, EvidenceResult] = {EvidenceLayer.CALENDAR: calendar}
    if EvidenceLayer.EXECUTION in required:
        evidence[EvidenceLayer.EXECUTION] = _execution_evidence(
            node, business_date, roots, reader, exists, lstat_reader, target_date
        )
    if EvidenceLayer.ARTIFACT in required:
        evidence[EvidenceLayer.ARTIFACT] = _artifact_evidence(
            node, business_date, roots, reader, exists, lstat_reader, target_date
        )
    if EvidenceLayer.API in required:
        evidence[EvidenceLayer.API] = api_evidence(node, business_date, http_get, target_date)
    if EvidenceLayer.PAGE in required:
        evidence[EvidenceLayer.PAGE] = _page_evidence(
            node, business_date, now, roots, reader, exists, lstat_reader
        )
    return tuple(evidence[layer] for layer in required)
