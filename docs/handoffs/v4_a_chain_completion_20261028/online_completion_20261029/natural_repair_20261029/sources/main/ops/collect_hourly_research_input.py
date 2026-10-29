"""Build one V4-owned hourly research source from already-landed inputs.

This is a bounded port of V3's ``run_hourly_research.py`` input path.  The
business normalizer is the frozen V3 implementation in
``domains.research_hourly``; this module only discovers an owned ZSXQ status,
applies the original item-quality rules, and atomically publishes the frozen
source consumed by ``ops.run_hourly_research``.

Oracle SHA-256 (V3 producer):
850FFFDF16B7C0127852CBE9CC374AED353E8D7CB1C2BA73D2EFF880C95D022E
"""
from __future__ import annotations

from domains.report_subjects import bind_report_attachments, canonical_title_code

import argparse
import hashlib
import inspect
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import domains.research_hourly as research_hourly_domain_module
from domains.research_hourly import build_research_lane_snapshot
from domains.research_source_validation import (
    collector_source_cutoff,
    strict_source_receipt_time,
)
from infrastructure.research_source_evidence import read_zsxq_slot_evidence
from infrastructure.owned_path import resolve_owned_path
from infrastructure.interprocess_lock import owned_interprocess_lock


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SLOTS = ("0830", *(f"{hour:02d}00" for hour in range(7, 24)))
_VOLATILE_IDENTITY_KEYS = frozenset(
    {"generated_at", "crawl_time", "first_seen_at", "last_checked_at", "observed_at"}
)


def _collector_identity_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _research_hourly_domain_identity_sha256() -> str:
    source_file = inspect.getsourcefile(research_hourly_domain_module)
    if source_file is None:
        raise ValueError("research hourly domain source is unavailable")
    return hashlib.sha256(Path(source_file).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _normalize_repair_sha(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(
            "hourly research repair expected old input SHA must be SHA-256"
        )
    return value.lower()


def _recovery_context(
    path: Path,
    payload: Mapping[str, Any],
    *,
    require_complete: bool,
) -> tuple[str, str, str, list[str]]:
    """Read exact date/slot/cutoff/receipts without writing anything."""

    resolved = path.resolve(strict=False)
    path_date = resolved.parent.name
    path_slot = resolved.stem
    canonical_layout = (
        resolved.parent.parent.name == "incoming"
        and resolved.parent.parent.parent.name == "research"
    )
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("hourly research recovery source manifest is invalid")
    path_date_from_path = str(path_date)
    path_slot_from_path = str(path_slot)
    declared_date = payload.get("trade_date")
    manifest_date = manifest.get("trade_date")
    declared_slot = payload.get("slot")
    manifest_slot = manifest.get("hourly_slot")
    if canonical_layout:
        expected_date = path_date_from_path
        expected_slot = path_slot_from_path
    else:
        expected_date = str(declared_date or manifest_date or "")
        expected_slot = str(declared_slot or manifest_slot or path_slot_from_path)
    for value in (declared_date, manifest_date):
        if value not in {None, ""} and (
            type(value) is not str or value != expected_date
        ):
            raise ValueError("hourly research recovery date mismatched")
    for value in (declared_slot, manifest_slot):
        if value not in {None, ""} and (
            type(value) is not str or value != expected_slot
        ):
            raise ValueError("hourly research recovery slot mismatched")
    path_date = expected_date
    path_slot = expected_slot
    if not re.fullmatch(r"\d{8}", path_date) or not re.fullmatch(
        r"\d{4}", path_slot
    ) or int(path_slot[:2]) > 23 or int(path_slot[2:]) > 59:
        raise ValueError("hourly research recovery date or slot is invalid")
    if require_complete and (
        declared_date in {None, ""}
        or manifest_date in {None, ""}
        or manifest_slot in {None, ""}
    ):
        raise ValueError("hourly research recovery date or slot is missing")
    payload_cutoff = payload.get("pit_cutoff")
    manifest_cutoff = manifest.get("pit_cutoff")
    cutoff_values = [
        str(value)
        for value in (payload_cutoff, manifest_cutoff)
        if value not in {None, ""}
    ]
    if len(set(cutoff_values)) > 1:
        raise ValueError("hourly research recovery PIT cutoff mismatched")
    cutoff = cutoff_values[0] if cutoff_values else ""
    expected_cutoff = _cutoff(path_date, path_slot).isoformat(timespec="seconds")
    if cutoff and cutoff != expected_cutoff:
        raise ValueError("hourly research recovery PIT cutoff is mismatched")
    if require_complete and cutoff != expected_cutoff:
        raise ValueError("hourly research recovery PIT cutoff is missing")
    raw_receipts = payload.get("source_receipts")
    if raw_receipts is None:
        raw_receipts = manifest.get("source_receipts")
    if (
        not isinstance(raw_receipts, list)
        or (require_complete or canonical_layout) and not raw_receipts
        or any(type(item) is not str or not item.strip() for item in raw_receipts)
    ):
        if require_complete or canonical_layout:
            raise ValueError("hourly research recovery source receipts are invalid")
        receipts: list[str] = []
    else:
        receipts = list(raw_receipts)
    if "source_receipts" in payload and payload.get("source_receipts") != receipts:
        raise ValueError("hourly research recovery source receipts mismatch")
    if "source_receipts" in manifest and manifest.get("source_receipts") != receipts:
        raise ValueError("hourly research recovery source receipts mismatch")
    return path_date, path_slot, cutoff or expected_cutoff, receipts



def _write_recovery_artifact(
    path: Path,
    payload: Mapping[str, Any],
    *,
    superseded_sha: str | None,
    repair_expected_old_input_sha256: str | None = None,
) -> Path:
    """Write one content-addressed late recovery artifact.

    A normal recovery supersedes the bytes already at ``path``.  A late first
    admission may have no canonical preimage at all; it still gets the same
    explicit recovery filename and late provenance, with empty SHA fields
    rather than a fabricated preimage digest.
    """

    expected_repair_sha = _normalize_repair_sha(repair_expected_old_input_sha256)
    canonical_layout = (
        path.resolve(strict=False).parent.parent.name == "incoming"
        and path.resolve(strict=False).parent.parent.parent.name == "research"
    )
    if superseded_sha is None and not canonical_layout:
        raise ValueError("hourly research late recovery requires an owned canonical input")
    business_date, slot, pit_cutoff, source_receipts = _recovery_context(
        path,
        payload,
        require_complete=True,
    )
    recovery_payload = dict(payload)
    superseded = str(superseded_sha or "")
    recovery_payload["retry_of_sha256"] = superseded
    recovery_payload["supersedes"] = superseded
    manifest = dict(
        recovery_payload.get("source_manifest")
        if isinstance(recovery_payload.get("source_manifest"), Mapping)
        else {}
    )
    original_source_path = path.resolve(strict=False).as_posix()
    manifest["trade_date"] = business_date
    manifest["hourly_slot"] = slot
    manifest["pit_cutoff"] = pit_cutoff
    manifest["source_receipts"] = list(source_receipts)
    manifest["collector_identity_sha256"] = _collector_identity_sha256()
    manifest[
        "research_hourly_domain_identity_sha256"
    ] = _research_hourly_domain_identity_sha256()
    manifest["capture_origin"] = "LATE_RECOVERY"
    manifest["original_time_capture"] = False
    manifest["natural_execution_verified"] = False
    recovery_payload["source_manifest"] = manifest
    recovery_payload["trade_date"] = business_date
    recovery_payload["slot"] = slot
    recovery_payload["pit_cutoff"] = pit_cutoff
    recovery_payload["recovery"] = True
    recovery_payload["source_path"] = original_source_path
    recovery_payload["original_source_path"] = original_source_path
    recovery_payload["original_source_sha256"] = superseded
    recovery_payload["source_receipts"] = list(source_receipts)
    recovery_payload["capture_origin"] = "LATE_RECOVERY"
    recovery_payload["original_time_capture"] = False
    recovery_payload["natural_execution_verified"] = False
    recovery_metadata = {
        "retry_of_sha256": superseded,
        "supersedes": superseded,
        "original_source_path": original_source_path,
        "original_source_sha256": superseded,
        "pit_cutoff": pit_cutoff,
        "source_receipts": list(source_receipts),
        "trade_date": business_date,
        "slot": slot,
        "source_path": original_source_path,
        "capture_origin": "LATE_RECOVERY",
        "original_time_capture": False,
        "natural_execution_verified": False,
    }
    if expected_repair_sha is not None:
        authorization = {
            "kind": "EXPLICIT_EXPECTED_OLD_INPUT_SHA256",
            "expected_old_input_sha256": expected_repair_sha,
            "canonical_path": original_source_path,
        }
        recovery_metadata["repair_authorization"] = authorization
        recovery_payload["repair_authorization"] = authorization
    recovery_payload["recovery_metadata"] = recovery_metadata
    encoded = json.dumps(
        recovery_payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    recovery = path.with_name(f"{path.stem}.recovery-{digest}{path.suffix}")
    if recovery.is_file():
        if recovery.read_bytes() == encoded:
            return recovery
        raise ValueError(
            f"conflicting hourly research recovery input: {recovery.name}"
        )
    temporary = recovery.with_name(f".{recovery.name}.{os.getpid()}.tmp")
    recovery.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(encoded)
    os.replace(temporary, recovery)
    return recovery



def _same_sealed_original_source_retry(
    path: Path, existing: Mapping[str, Any], payload: Mapping[str, Any],
) -> bool:
    """Reuse original bytes only after full same-source publication proof.

    Regeneration changes the observation clock/version and can cross the slot
    cutoff. These retry observations must not replace an already-published
    original capture or pretend that the later execution completed earlier.
    """
    from infrastructure.manager_input_attestation import read_attestation

    try:
        old = existing["source_manifest"]
        new = payload["source_manifest"]
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            return False
        date, slot = existing["trade_date"], old["hourly_slot"]
        cutoff = _cutoff(date, slot)
        old_time = _strict_as_time(old.get("generated_at"))
        new_time = _strict_as_time(new.get("generated_at"))
        if (old_time is None or new_time is None
            or not old_time <= cutoff or not old_time <= new_time <= datetime.now(_SHANGHAI)
            or new_time.strftime("%Y%m%d") != date
            or _strict_as_time(old.get("published_at")) != old_time
            or _strict_as_time(new.get("published_at")) != new_time
            or old.get("capture_origin") != "ORIGINAL_SLOT"
            or old.get("original_time_capture") is not True
            or any(manifest.get("natural_execution_verified") is not False for manifest in (old, new))
            or new.get("capture_origin") != ("LATE_RECOVERY" if new_time > cutoff else "ORIGINAL_SLOT")
            or new.get("original_time_capture") is not (new_time <= cutoff)
            or not existing.get("stock_research_timeline")
            or any(key in manifest for manifest in (old, new)
                   for key in ("materialization_origin", "materialized_at", "ready_empty_source_proof"))):
            return False
        expected_cutoff = cutoff.isoformat(timespec="seconds")
        if any(manifest.get("pit_cutoff") != expected_cutoff for manifest in (old, new)):
            return False
        versions = [manifest.get("version") for manifest in (old, new)]
        if any(not isinstance(version, str) or not re.fullmatch(r"\d{14}-[0-9a-f]{8}", version)
               for version in versions) or versions[0][15:] != versions[1][15:]:
            return False
        clocks = [datetime.strptime(version[:14], "%Y%m%d%H%M%S").replace(tzinfo=_SHANGHAI)
                  for version in versions]
        if (any(clock.strftime("%Y%m%d") != date for clock in clocks)
            or not clocks[0] <= clocks[1] <= new_time or clocks[0] > old_time):
            return False
        # Compare every business/source/safety field, including nested clocks.
        # Only these five regenerated manifest observations can differ.
        comparable = dict(payload)
        comparable["source_manifest"] = dict(new)
        for key in ("generated_at", "published_at", "version", "capture_origin", "original_time_capture"):
            comparable["source_manifest"][key] = old[key]
        if comparable != existing:
            return False
        owner = Path(__file__).resolve().parents[1]
        expected_code = {
            "collector_identity_sha256": _collector_identity_sha256(),
            "research_hourly_domain_identity_sha256": _research_hourly_domain_identity_sha256(),
            "report_subject_policy_sha256": hashlib.sha256(
                resolve_owned_path(owner, "domains/report_subjects.py").read_bytes()).hexdigest(),
        }
        if any(old.get(key) != digest for key, digest in expected_code.items()):
            return False
        # Existing reader validates exact date/slot path, original input and
        # manifest SHA, original source receipt + artifact hashes and owner code.
        root = path.parent.parent.parent.parent
        publication = read_attestation(path, data_root=root, owner_root=owner, as_of=new_time)
        return (_strict_as_time(publication.get("available_at")) <= cutoff
                and json.loads(path.read_bytes()) == existing)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    repair_expected_old_input_sha256: str | None = None,
) -> Path:
    expected_repair_sha = _normalize_repair_sha(repair_expected_old_input_sha256)
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    if path.is_file():
        if path.read_bytes() == encoded:
            return path
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            existing = {}
        if _canonical_identity(existing) == _canonical_identity(payload):
            if expected_repair_sha is not None:
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected_repair_sha:
                    raise ValueError(
                        "hourly research explicit repair expected old input SHA mismatch"
                    )
                if (
                    not isinstance(payload.get("stock_research_timeline"), list)
                    or not payload.get("stock_research_timeline")
                ):
                    raise ValueError(
                        "hourly research explicit repair requires non-empty rows"
                    )
                _recovery_context(path, payload, require_complete=True)
            return path
        if expected_repair_sha is None and _same_sealed_original_source_retry(path, existing, payload):
            return path
        existing_rows = (
            existing.get("stock_research_timeline")
            if isinstance(existing, Mapping)
            else None
        )
        new_rows = payload.get("stock_research_timeline")
        gaps = payload.get("cannot_confirm")
        explicit_late_recovery = isinstance(gaps, list) and any(
            isinstance(gap, Mapping)
            and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
            for gap in gaps
        )
        canonical_layout = (
            path.resolve(strict=False).parent.parent.name == "incoming"
            and path.resolve(strict=False).parent.parent.parent.name == "research"
        )
        if expected_repair_sha is not None:
            if not isinstance(new_rows, list) or not new_rows:
                raise ValueError(
                    "hourly research explicit repair requires non-empty rows"
                )
            if not isinstance(existing_rows, list) or not existing_rows:
                raise ValueError(
                    "hourly research explicit repair requires non-empty canonical input"
                )
            if not canonical_layout:
                raise ValueError(
                    "hourly research explicit repair requires an owned canonical input"
                )
            actual_old_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_old_sha != expected_repair_sha:
                raise ValueError(
                    "hourly research explicit repair expected old input SHA mismatch"
                )
        if (
            isinstance(existing_rows, list)
            and existing_rows
            and not explicit_late_recovery
            and expected_repair_sha is None
        ):
            raise ValueError(f"conflicting hourly research input: {path.name}")
        if (
            isinstance(new_rows, list)
            and new_rows
            and (
                not existing_rows
                or explicit_late_recovery
                or expected_repair_sha is not None
            )
        ):
            superseded_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            business_date, slot, pit_cutoff, source_receipts = _recovery_context(
                path,
                payload,
                require_complete=expected_repair_sha is not None,
            )
            if expected_repair_sha is not None and superseded_sha != expected_repair_sha:
                raise ValueError(
                    "hourly research explicit repair expected old input SHA mismatch"
                )
            return _write_recovery_artifact(
                path,
                payload,
                superseded_sha=superseded_sha,
                repair_expected_old_input_sha256=expected_repair_sha,
            )
        if expected_repair_sha is not None:
            raise ValueError("hourly research explicit repair was not authorized")
        raise ValueError(f"conflicting hourly research input: {path.name}")
    if expected_repair_sha is not None:
        raise ValueError(
            "hourly research explicit repair requires an existing canonical input"
        )
    missing_path_late_recovery = (
        isinstance(payload.get("cannot_confirm"), list)
        and any(
            isinstance(gap, Mapping)
            and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
            for gap in payload.get("cannot_confirm") or []
        )
        and isinstance(payload.get("stock_research_timeline"), list)
        and bool(payload.get("stock_research_timeline"))
        and path.resolve(strict=False).parent.parent.name == "incoming"
        and path.resolve(strict=False).parent.parent.parent.name == "research"
    )
    if missing_path_late_recovery:
        return _write_recovery_artifact(
            path,
            payload,
            superseded_sha=None,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return path


def _canonical_identity(value: Any, path: tuple[str, ...] = ()) -> Any:
    """Remove only volatile observation timestamps from same-slot identity."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_identity(item, (*path, str(key)))
            for key, item in value.items()
            if key not in _VOLATILE_IDENTITY_KEYS
            and not (key == "published_at" and path == ("source_manifest",))
        }
    if isinstance(value, list):
        return [_canonical_identity(item, path) for item in value]
    return value


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    canonical = canonical_title_code(text)
    if canonical and canonical.startswith("HK."):
        return canonical
    digits = "".join(character for character in text if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _clean_name(value: Any) -> str:
    return re.sub(r"[（(].*?[）)]", "", str(value or "")).replace(" ", "").strip()


def _zsxq_topic_url(topic_id: Any) -> str:
    """Build a ZSXQ topic URL only from an exact 17-digit ASCII topic id."""
    if isinstance(topic_id, bool):
        return ""
    if isinstance(topic_id, int):
        candidate = str(topic_id)
    elif isinstance(topic_id, str):
        candidate = topic_id
    else:
        return ""
    if not re.fullmatch(r"[0-9]{17}", candidate):
        return ""
    return f"https://wx.zsxq.com/dweb2/index/topic_detail/{candidate}"


def _compact(*values: Any, limit: int = 5000) -> str:
    text = re.sub(r"\s+", " ", " ".join(str(value or "") for value in values)).strip()
    return text[:limit]


def _as_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def _cutoff(business_date: str, slot: str) -> datetime:
    return collector_source_cutoff(business_date, slot)


def _strict_as_time(value: Any) -> datetime | None:
    """Parse a source-receipt timestamp only when its timezone is explicit."""
    return strict_source_receipt_time(value)


def _latest_zsxq_status(data_root: Path, business_date: str, slot: str, *, allow_ready_empty: bool=False) -> tuple[Path, dict[str, Any]] | None:
    evidence = read_zsxq_slot_evidence(data_root, business_date, slot)
    if evidence is None:
        return None
    if evidence.status.get("status") == "READY_EMPTY" and not allow_ready_empty:
        return None
    return evidence.status_path, evidence.status

def _read_status_artifacts(data_root: Path, business_date: str, slot: str, status_path: Path, status: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, str, str] | None:
    evidence = read_zsxq_slot_evidence(data_root, business_date, slot)
    if evidence is None:
        return None
    try:
        if Path(status_path).resolve() != evidence.status_path.resolve():
            return None
    except OSError:
        return None
    if dict(status) != evidence.status:
        return None
    return (evidence.summary, evidence.fetch_result, evidence.status_sha256, evidence.summary_sha256, evidence.fetch_result_sha256)


def _source_quality(
    *, body: str, code: str, theme: str, source_type: str, cannot_confirm: list[str]
) -> tuple[str, str]:
    # Exact V3 build_item weights for the ZSXQ lane.
    score = 48.0
    if len(body) >= 120:
        score += 15
    if code:
        score += 15
    if theme:
        score += 6
    if "研报" in body or "research" in body.lower() or source_type in {"research", "report"}:
        score += 6
    score = min(100.0, score)
    level = "HIGH" if score >= 80 else "MEDIUM" if score >= 55 else "LOW"
    evidence = (
        "L2_MEDIUM"
        if cannot_confirm
        else "L3_STRONG"
        if score >= 80
        else "L2_MEDIUM"
        if score >= 55
        else "L1_WEAK"
    )
    return level, evidence


def _zsxq_rows(
    data_root: Path, business_date: str, slot: str, *, allow_ready_empty: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    selected = _latest_zsxq_status(
        data_root, business_date, slot, allow_ready_empty=allow_ready_empty
    )
    if selected is None:
        return [], ["ZSXQ_STATUS_NOT_AVAILABLE_BY_SLOT"]
    status_path, status = selected
    fetched_at = _as_time(status.get("source_completed_at") if status.get("status") == "PARTIAL" else status.get("fetched_at"))
    cutoff = _cutoff(business_date, slot)
    if fetched_at is None:
        return [], ["ZSXQ_STATUS_NOT_POINT_IN_TIME_SAFE"]
    late_recovery = fetched_at > cutoff
    if late_recovery:
        source_cutoff = _as_time(status.get("source_cutoff"))
        if source_cutoff is None or source_cutoff > cutoff:
            return [], ["ZSXQ_STATUS_NOT_POINT_IN_TIME_SAFE"]
    artifacts = _read_status_artifacts(
        data_root, business_date, slot, status_path, status
    )
    if artifacts is None:
        return [], ["ZSXQ_SUMMARY_UNREADABLE"]
    summary = artifacts[0]
    if status.get("status") == "READY_EMPTY":
        if allow_ready_empty:
            return [], []
        return [], ["ZSXQ_READY_EMPTY_REQUIRES_MANUAL_RECOVERY"]
    boundary = [
        str(value)
        for value in status.get("cannot_confirm") or []
        if str(value).strip()
    ]
    if status.get("status") == "PARTIAL":
        boundary.append("ZSXQ_SOURCE_PARTIAL_INCOMPLETE")
    if late_recovery:
        boundary.append("ZSXQ_SOURCE_COMPLETED_AFTER_SLOT" if status.get("source_completed_at") else "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT")
    if summary.get("primary_refetch_failed") is True:
        boundary.append("ZSXQ_PRIMARY_REFETCH_FAILED_FALLBACK_USED")
    rows: list[dict[str, Any]] = []
    stock_master: dict[str, dict[str, Any]] = {}
    for topic in summary.get("effective_topics") or []:
        if not isinstance(topic, Mapping):
            continue
        published = _as_time(topic.get("create_time"))
        if published is None or published > cutoff:
            continue
        themes = topic.get("themes") if isinstance(topic.get("themes"), list) else []
        theme = " / ".join(
            str(item.get("theme") or "").strip()
            for item in themes
            if isinstance(item, Mapping) and str(item.get("theme") or "").strip()
        )
        companies_raw = topic.get("companies")
        companies = (
            [companies_raw]
            if isinstance(companies_raw, Mapping)
            else [item for item in companies_raw if isinstance(item, Mapping)]
            if isinstance(companies_raw, list)
            else []
        )
        for company in bind_report_attachments({**topic, "companies": companies}):
            code = _normalize_code(company.get("code"))
            if not code:
                continue
            name = _clean_name(company.get("name")) or code
            attachment_unmatched = company.get("attachment_binding_status") == "NO_MATCH_UNCONFIRMED"
            title = "" if attachment_unmatched else str(company.get("bound_source_title") or "")
            body = str(topic.get("content_head") or topic.get("evidence") or title)
            topic_id = topic.get("topic_id")
            group_id = topic.get("group_id")
            topic_group = topic.get("group")
            if group_id is None and isinstance(topic_group, Mapping):
                group_id = topic_group.get("group_id")
            topic_url = _zsxq_topic_url(topic_id)
            source_cannot_confirm = [*boundary]
            if attachment_unmatched and "ZSXQ_REPORT_ATTACHMENT_UNMATCHED" not in source_cannot_confirm:
                source_cannot_confirm.append("ZSXQ_REPORT_ATTACHMENT_UNMATCHED")
            if not topic_url and "URL_REQUIRED" not in source_cannot_confirm:
                source_cannot_confirm.append("URL_REQUIRED")
            confidence, evidence_level = _source_quality(
                body=body,
                code=code,
                theme=theme,
                source_type="zsxq",
                cannot_confirm=source_cannot_confirm,
            )
            raw_id = hashlib.sha256(
                f"{business_date}|zsxq|{topic_id}|{code}|{title}".encode("utf-8")
            ).hexdigest()[:16]
            observed = fetched_at.isoformat(timespec="seconds")
            rows.append(
                {
                    "raw_id": raw_id,
                    "trade_date": business_date,
                    "source_type": "zsxq",
                    "source_name": "知识星球",
                    "source_path": (
                        f"research_module/runtime_outputs/zsxq_hourly/"
                        f"{business_date}/{status.get('slot')}/{status_path.name}"
                    ),
                    "url": topic_url,
                    "topic_id": topic_id,
                    "group_id": group_id,
                    "source_original_companies": companies,
                    "source_original_topic_title": topic.get("title"),
                    "source_attachment_names": topic.get("attachment_file_names", []),
                    "source_attachment_file_count": topic.get("attachment_file_count", len(topic.get("attachment_file_names") or [])),
                    "source_attachment_names_complete": company.get("attachment_names_complete"),
                    "source_report_binding": company,
                    "title": title,
                    "raw_text": _compact(body, title),
                    "published_at": published.isoformat(timespec="seconds"),
                    "crawl_time": observed,
                    "source_published_at": published.isoformat(timespec="seconds"),
                    "first_seen_at": observed,
                    "last_checked_at": observed,
                    "display_event_time": published.isoformat(timespec="seconds"),
                    "is_new_since_last_slot": True,
                    "is_recheck_duplicate": False,
                    "source_evidence_level": evidence_level,
                    "source_confidence": confidence,
                    "source_cannot_confirm": source_cannot_confirm,
                    "themes": [theme] if theme else [],
                    "mentioned_stock_candidates": [name, code],
                    "stock": name,
                    "stock_code": code,
                    "stock_name": name,
                    "slot": slot,
                }
            )
            stock_master[code] = {"name": name, "aliases": [name, code]}
    return rows, boundary


def build_hourly_research_input(
    *,
    data_root: Path,
    business_date: str,
    slot: str,
    repair_expected_old_input_sha256: str | None = None,
    manual_recovery: bool = False,
) -> dict[str, Any]:
    if slot not in _SLOTS:
        raise ValueError("hourly research slot must be 0830 or 0700 through 2300")
    datetime.strptime(business_date, "%Y%m%d")
    if manual_recovery and (business_date, slot) != ("20261012", "1700"):
        raise ValueError("manual empty recovery is limited to 20261012/1700")
    selected = _latest_zsxq_status(
        Path(data_root), business_date, slot, allow_ready_empty=manual_recovery
    )
    status = selected[1] if selected is not None else {}
    artifacts = (
        _read_status_artifacts(Path(data_root), business_date, slot, *selected)
        if selected is not None
        else None
    )
    fetched_at = _strict_as_time(status.get("fetched_at"))
    cutoff = _cutoff(business_date, slot)
    manual_empty_proof = bool(
        manual_recovery
        and selected is not None
        and status.get("status") == "READY_EMPTY"
        and artifacts is not None
        and fetched_at is not None
        and fetched_at.strftime("%Y%m%d") == business_date
        and fetched_at <= cutoff
        and datetime.now(_SHANGHAI) >= cutoff
    )
    rows, gaps = _zsxq_rows(
        Path(data_root), business_date, slot, allow_ready_empty=manual_empty_proof
    )
    if status.get("status") == "PARTIAL":
        current = _read_status_artifacts(Path(data_root), business_date, slot, *selected) if selected else None
        if artifacts is None or current is None or current[2:] != artifacts[2:]:
            rows, gaps = [], ["ZSXQ_PARTIAL_SOURCE_BYTES_CHANGED"]
    stock_master = {
        str(row["stock_code"]): {
            "name": str(row["stock_name"]),
            "aliases": [str(row["stock_name"]), str(row["stock_code"])],
        }
        for row in rows
    }
    snapshot = build_research_lane_snapshot(business_date, rows, stock_master)
    cutoff = _cutoff(business_date, slot)
    repair_requested = repair_expected_old_input_sha256 is not None
    late_recovery = "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT" in gaps
    now = datetime.now(_SHANGHAI)
    recovery_observation = late_recovery or repair_requested or manual_empty_proof or now > cutoff
    # A late replay keeps the actual collection time.  Clamping it to the
    # historical slot would fabricate a natural in-slot execution receipt.
    generated_at = now
    snapshot["source_manifest"].update(
        {
            "trade_date": business_date,
            "generated_at": generated_at.isoformat(timespec="microseconds"),
            "published_at": generated_at.isoformat(timespec="microseconds"),
            "hourly_slot": slot,
            "pit_cutoff": cutoff.isoformat(timespec="seconds"),
            "producer": "ops.collect_hourly_research_input",
            "publication_clock_contract": "ACTUAL_COMPLETION_V1",
            "producer_oracle_sha256": "850fffdf16b7c0127852cbe9cc374aed353e8d7cb1c2ba73d2eff880c95d022e",
            "collector_identity_sha256": _collector_identity_sha256(),
            "research_hourly_domain_identity_sha256": _research_hourly_domain_identity_sha256(),
            "report_subject_policy_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / "domains" / "report_subjects.py").read_bytes()).hexdigest(),
            "source_receipts": sorted(
                {
                    str(row.get("source_path"))
                    for row in rows
                    if isinstance(row, Mapping) and str(row.get("source_path") or "").strip()
                }
            ),
            "capture_origin": "LATE_RECOVERY" if recovery_observation else "ORIGINAL_SLOT",
            "original_time_capture": not recovery_observation,
            "natural_execution_verified": False,
        }
    )
    materialized_at = now
    if manual_empty_proof:
        status_receipt = str(status["status_path"])
        source_cutoff = str(status["source_cutoff"])
        receipt_sha = artifacts[2]
        snapshot["source_manifest"].update(
            {
                "generated_at": materialized_at.isoformat(timespec="seconds"),
                "published_at": materialized_at.isoformat(timespec="seconds"),
                "hourly_slot": slot,
                "trade_date": business_date,
                "source_receipts": [status_receipt],
                "source_receipt_sha256": receipt_sha,
                "fetched_at": str(status["fetched_at"]),
                "source_cutoff": source_cutoff,
                "pit_cutoff": source_cutoff,
                "capture_origin": "ORIGINAL_SLOT",
                "original_time_capture": True,
                "materialization_origin": "MANUAL_RECOVERY",
                "materialized_at": materialized_at.isoformat(timespec="seconds"),
                "available_at": materialized_at.isoformat(timespec="seconds"),
                "natural_execution_verified": False,
                "ready_empty_source_proof": {
                    "schema_version": "v3_5.zsxq_ready_empty.v1",
                    "trade_date": business_date,
                    "slot": slot,
                    "status": "READY_EMPTY",
                    "source_receipt_path": status_receipt,
                    "source_receipt_sha256": receipt_sha,
                    "summary_sha256": artifacts[3],
                    "fetch_result_sha256": artifacts[4],
                    "fetch_ok": status.get("fetch_ok"),
                    "fetch_success": artifacts[1].get("success"),
                    "page_count": status.get("page_count"),
                    "topic_count": status.get("topic_count"),
                    "effective_topic_count": status.get("effective_topic_count"),
                    "fetched_at": str(status["fetched_at"]),
                    "source_cutoff": source_cutoff,
                    "capture_origin": "ORIGINAL_SLOT",
                    "materialization_origin": "MANUAL_RECOVERY",
                    "materialized_at": materialized_at.isoformat(timespec="seconds"),
                    "available_at": materialized_at.isoformat(timespec="seconds"),
                    "natural_execution_verified": False,
                },
            }
        )
    if status.get("status") == "PARTIAL" and artifacts is not None:
        snapshot["source_manifest"]["zsxq_source_completeness"] = "PARTIAL"
        snapshot["source_manifest"]["zsxq_status_sha256"] = artifacts[2]
        snapshot["source_manifest"]["zsxq_summary_sha256"] = artifacts[3]
        snapshot["source_manifest"]["zsxq_fetch_result_sha256"] = artifacts[4]
        snapshot["source_manifest"]["zsxq_fetched_at"] = str(status["fetched_at"])
        snapshot["source_manifest"]["zsxq_source_completed_at"] = str(status["source_completed_at"])
    # Keep the declared request context on the source itself as well as in
    # its manifest.  Explicit late recovery validates both representations
    # before it can create a superseding artifact.
    snapshot["trade_date"] = business_date
    snapshot["slot"] = slot
    snapshot["pit_cutoff"] = cutoff.isoformat(timespec="seconds")
    snapshot["cannot_confirm"] = [
        *snapshot.get("cannot_confirm", []),
        *({"module": "research_intelligence", "reason": gap} for gap in gaps),
    ]
    snapshot["hourly_research"] = {
        "schema_version": "hourly_research_dashboard.v1",
        "trade_date": business_date,
        "latest_slot": slot,
        "latest_research_slot": slot,
        "slot_count": 1,
        "status": "PARTIAL_WITH_ROWS" if rows and status.get("status") == "PARTIAL" else "READY_WITH_RESEARCH_POOL" if rows else "READY_EMPTY",
        "row_count": len(rows),
        "source_status": "PARTIAL" if status.get("status") == "PARTIAL" else status.get("status", "CANNOT_CONFIRM"),
    }
    # An unavailable collector is not a verified empty business result.  Keep
    # the original evidence gap visible, without occupying an immutable slot.
    source_manifest = snapshot["source_manifest"]
    missing = []
    if not manual_empty_proof:
        if not rows or not snapshot.get("stock_research_timeline"):
            missing.append("EXACT_SOURCE_ROWS_MISSING")
        if not source_manifest.get("source_receipts"):
            missing.append("EXACT_SOURCE_RECEIPTS_MISSING")
        if not source_manifest.get("source_types"):
            missing.append("EXACT_SOURCE_TYPES_MISSING")
        if snapshot.get("quality_status") == "QUALITY_FAIL":
            missing.append("SOURCE_QUALITY_FAIL")
    def unavailable(reasons: list[str], *, existing_sha: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": "v3_5.hourly_research_input_run.v1",
            "status": "INPUT_MISSING", "source_status": "CANNOT_CONFIRM",
            "business_date": business_date, "slot": slot, "row_count": 0,
            "source_path": None, "source_sha256": None,
            "existing_input_sha256": existing_sha,
            "collector_identity_sha256": source_manifest["collector_identity_sha256"],
            "research_hourly_domain_identity_sha256": source_manifest["research_hourly_domain_identity_sha256"],
            "cannot_confirm": reasons,
            "manager_publication": {"status": "INPUT_MISSING", "reason": "EXACT_WITNESS_NOT_PUBLISHED"},
            "recovery": False, "natural_execution_verified": False,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
    explicit_repair_sha = _normalize_repair_sha(repair_expected_old_input_sha256)
    if explicit_repair_sha is not None and not rows:
        # Preserve the original explicit-repair error contract. An automatic
        # empty retry is typed INPUT_MISSING; an invalid repair stays an error.
        raise ValueError("hourly research explicit repair requires non-empty rows")
    if missing:
        return unavailable(missing)
    destination = resolve_owned_path(
        data_root, f"research/incoming/{business_date}/{slot}.json"
    )
    # Reuse the existing import lock to serialize publication/CAS.  An already
    # sealed empty slot requires a separately authorized exact-witness repair;
    # a retry must not implicitly mint a replacement from newer material.
    with owned_interprocess_lock(Path(data_root) / ".import.lock",
                                 timeout_seconds=10,
                                 timeout_message="hourly source import lock timeout"):
        if destination.exists():
            previous_bytes = destination.read_bytes()
            previous = json.loads(previous_bytes)
            expected_old = _normalize_repair_sha(repair_expected_old_input_sha256)
            if expected_old is not None and hashlib.sha256(previous_bytes).hexdigest() != expected_old:
                raise ValueError("hourly research explicit repair expected old input SHA mismatch")
            previous_rows = previous.get("stock_research_timeline")
            if not previous_rows:
                return unavailable(["SEALED_EMPTY_CANONICAL_REQUIRES_EXACT_WITNESS_CAS"],
                                   existing_sha=hashlib.sha256(previous_bytes).hexdigest())
        published_path = _atomic_json(
            destination, snapshot,
            repair_expected_old_input_sha256=repair_expected_old_input_sha256,
        )
    source_path = published_path.relative_to(Path(data_root)).as_posix()
    # Metadata only, after the original publication. Do not change source
    # bytes, collector order, legacy recovery behavior or task success policy.
    from infrastructure.manager_input_attestation import publish_attestation, PublicationError
    try:
        publication=publish_attestation(published_path,data_root=Path(data_root),owner_root=Path(__file__).resolve().parents[1])
        manager_publication={"status":"VERIFIED_PUBLICATION","available_at":publication["available_at"],"run_id":publication["run_id"]}
    except (PublicationError,OSError,ValueError,TypeError):
        manager_publication={"status":"INPUT_MISSING","reason":"MANAGER_PIT_PUBLICATION_UNVERIFIED"}
    return {
        "schema_version": "v3_5.hourly_research_input_run.v1",
        "status": ("PARTIAL_WITH_ROWS" if status.get("status") == "PARTIAL" else "READY_WITH_RESEARCH_POOL" if rows else "READY_EMPTY") if manager_publication["status"] == "VERIFIED_PUBLICATION" else "INPUT_MISSING",
        "materialization_status": "PARTIAL_WITH_ROWS" if rows and status.get("status") == "PARTIAL" else "READY_WITH_RESEARCH_POOL" if rows else "READY_EMPTY",
        "business_date": business_date,
        "slot": slot,
        "row_count": len(rows),
        "source_status": "PARTIAL" if status.get("status") == "PARTIAL" else status.get("status", "CANNOT_CONFIRM"),
        "source_path": source_path,
        "manager_publication": manager_publication,
        "source_sha256": hashlib.sha256(published_path.read_bytes()).hexdigest(),
        "recovery": published_path != destination,
        "capture_origin": "ORIGINAL_SLOT" if manual_empty_proof else (
            "LATE_RECOVERY" if recovery_observation else "ORIGINAL_SLOT"
        ),
        "execution_origin": "MANUAL_RECOVERY" if manual_empty_proof else (
            "LATE_RECOVERY" if recovery_observation else "ORIGINAL_SLOT"
        ),
        "materialized_at": materialized_at.isoformat(timespec="seconds"),
        **(
            {
                "available_at": materialized_at.isoformat(timespec="seconds"),
                "source_receipt_sha256": artifacts[2],
                "summary_sha256": artifacts[3],
                "fetch_result_sha256": artifacts[4],
                "source_cutoff": str(status["source_cutoff"]),
                "fetched_at": str(status["fetched_at"]),
            }
            if manual_empty_proof and artifacts is not None else {}
        ),
        "natural_execution_verified": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one V4 hourly research input")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--repair-expected-old-input-sha256")
    parser.add_argument("--manual-recovery", action="store_true")
    args = parser.parse_args()
    result = build_hourly_research_input(
        data_root=args.data_root,
        business_date=args.date,
        slot=args.slot,
        repair_expected_old_input_sha256=args.repair_expected_old_input_sha256,
        manual_recovery=args.manual_recovery,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {
        "READY_WITH_RESEARCH_POOL",
        "READY_EMPTY",
        "PARTIAL_WITH_ROWS",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
