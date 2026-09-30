"""Exact-date research context for the V4 stage-center consumer.

The stage consumer reads the same ``HourlyResearchStore`` used by the
hourly research producer.  It never resolves a legacy application root,
``latest`` across dates, or a second research producer.  Values that are not
present in the verified V4 artifact stay ``None`` and are carried as
``CANNOT_CONFIRM`` evidence to the stage envelope.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import _sha256 as _canonical_sha256
from infrastructure.owned_io import SafeRoot
from domains.research import build_research_archive
from domains.research_hourly import (
    canonical_stage_a_code, hourly_source_time, project_hourly_stage_fields,
    validate_hourly_stage_source,
)
from infrastructure.research_store import HourlyResearchStore
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader


class ResearchContextError(ValueError):
    """An exact-date V4 research or morning-news artifact failed validation."""


_DATE_RE = re.compile(r"^\d{8}$")
_SLOT_RE = re.compile(r"^(?:[01]\d|2[0-3])[0-5]\d$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ResearchScore:
    """Verified research fields for one canonical A-share code.

    ``None`` means that the source did not prove the scalar.  It is distinct
    from a measured zero and prevents a missing research field from being
    treated as an observed score by this adapter.
    """

    news_quality_score: float | None = None
    research_quality_score: float | None = None
    latest_research_slot: str = ""
    research_delta_hits: int | None = None
    news_research_reason: tuple[str, ...] = ()
    source_health: str = "CANNOT_CONFIRM"


@dataclass(frozen=True)
class ResearchContext:
    """Scores valid for one exact trade date and one stage cutoff."""

    trade_date: str
    stage_cutoff: str
    selected_slot: str
    by_code: Mapping[str, ResearchScore]
    source_evidence: tuple[str, ...]
    cannot_confirm: tuple[str, ...] = ()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ResearchContextError(f"{label} is unreadable") from error
    if not isinstance(value, Mapping):
        raise ResearchContextError(f"{label} must be an object")
    return dict(value)


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _canonical_a_code(value: Any) -> str:
    return canonical_stage_a_code(value)


def _normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if _DATE_RE.fullmatch(text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", "")
    return ""


def _cutoff_minutes(value: Any) -> int:
    text = str(value or "").strip()
    if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", text):
        hour, minute = (int(part) for part in text.split(":")[:2])
    elif re.fullmatch(r"(?:[01]?\d|2[0-3])[0-5]\d", text):
        padded = text.zfill(4)
        hour, minute = int(padded[:2]), int(padded[2:])
    else:
        raise ResearchContextError(f"stage cutoff is not an exact clock time: {value!r}")
    return hour * 60 + minute


def _slot_minutes(slot: str) -> int:
    if _SLOT_RE.fullmatch(slot) is None:
        raise ResearchContextError(f"hourly research slot is invalid: {slot!r}")
    return int(slot[:2]) * 60 + int(slot[2:])


def _v4_data_root(root: Path | str) -> Path:
    """Resolve an explicitly supplied V4-owned root and reject old roots."""

    supplied = Path(root).expanduser()
    if not supplied.is_absolute():
        raise ResearchContextError("V4 research data root must be absolute")
    resolved = supplied.resolve()
    folded = str(resolved).casefold()
    forbidden = (
        "/v3_system",
        "/v3.5",
        "/v35",
        "com.codex.v3",
        "shared-research-collector",
    )
    if any(token in folded for token in forbidden):
        raise ResearchContextError("legacy research root is forbidden")
    return resolved


def _string_reasons(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        return ()
    return tuple(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _payload_base_sha(payload: Mapping[str, Any]) -> str:
    without_extension = dict(payload)
    without_extension.pop("stage_evidence_v1", None)
    return _canonical_sha256(without_extension)


# This compatibility contract identifies the producer/policy, not a trading
# date, source SHA or stock list. Source bytes and the final complete archive
# projection remain independently verified by _bound_source_rows.
_V35_REPORT_ROLE_PRODUCER_IDENTITY = {
    "collector_identity_sha256": "66b941f5a066250c4fd9830170302b8b1f7041760a37c6e4bf02ea222aa307ab",
    "module_path": "v3.5/domains/research_hourly",
    "producer": "ops.collect_hourly_research_input",
    "producer_oracle_sha256": "850fffdf16b7c0127852cbe9cc374aed353e8d7cb1c2ba73d2eff880c95d022e",
    "report_subject_policy_sha256": "0308fe6172e96b32e2ad0c2baa1187247e046d70c55134b329087e77a2297351",
    "research_hourly_domain_identity_sha256": "6c67bec8d162ed47d8ebc20ce9ae8da2b8e520399260165cc0bb992baa9c8e22",
}


def _apply_v35_report_role_warning_projection(
    projected: Mapping[str, Any],
    source: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    trade_date: str,
    slot: str,
    source_input_sha256: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Reproduce source-audited report_subject_scoring.v1 role warnings.

    Only the verified source supplies warning content and order. The archive
    is a comparison target, never a source of missing values. Actual source
    timestamps/capture origin are not rewritten or granted a cutoff exception.
    """
    if "report_entity_audit" not in source:
        return dict(projected), ()
    manifest = source.get("source_manifest")
    if not isinstance(manifest, Mapping) or any(
        manifest.get(key) != expected
        for key, expected in _V35_REPORT_ROLE_PRODUCER_IDENTITY.items()
    ):
        raise ValueError("V35_REPORT_ROLE_SOURCE_IDENTITY_MISMATCH")
    if (
        source.get("schema_version") != "v3_research_lane.v2"
        or source.get("trade_date") != trade_date
        or source.get("slot") != slot
        or manifest.get("trade_date") != trade_date
        or manifest.get("hourly_slot") != slot
        or payload.get("schema_version") != "v3_5.research_archive.v1"
        or payload.get("archive_date") != trade_date
        or payload.get("source_input_sha256") != source_input_sha256
        or projected.get("source_input_sha256") != source_input_sha256
    ):
        raise ValueError("V35_REPORT_ROLE_SOURCE_ARCHIVE_IDENTITY_MISMATCH")
    audit = source["report_entity_audit"]
    if not isinstance(audit, Mapping) or audit.get("policy_version") != "report_subject_scoring.v1":
        raise ValueError("V35_REPORT_ROLE_AUDIT_MISSING_OR_UNKNOWN")
    affected, excluded = audit.get("affected_codes"), audit.get("excluded_evidence")
    if (
        not isinstance(affected, list) or not isinstance(excluded, list)
        or any(not isinstance(code, str) or re.fullmatch(r"\d{6}", code) is None for code in affected)
        or affected != sorted(set(affected))
        or any(
            not isinstance(item, Mapping)
            or item.get("research_subject_eligible") is not False
            or not isinstance(item.get("stock_code"), str)
            or re.fullmatch(r"\d{6}", item["stock_code"]) is None
            for item in excluded
        )
    ):
        raise ValueError("V35_REPORT_ROLE_AUDIT_SHAPE_OR_ORDER_INVALID")
    if set(affected) != {item["stock_code"] for item in excluded}:
        raise ValueError("V35_REPORT_ROLE_AFFECTED_CODE_AUDIT_MISMATCH")

    prefix = "REPORT_ROLE_EVIDENCE_EXCLUDED:"
    role_warnings = [prefix + code for code in affected]
    current_gaps, archived_gaps = projected.get("cannot_confirm"), payload.get("cannot_confirm")
    if any(
        not isinstance(gaps, list)
        or any(not isinstance(item, str) for item in gaps)
        or len(gaps) != len(set(gaps))
        for gaps in (current_gaps, archived_gaps)
    ):
        raise ValueError("V35_REPORT_ROLE_CANNOT_CONFIRM_SHAPE_INVALID")
    base_gaps = [item for item in current_gaps if not item.startswith(prefix)]
    expected_gaps = [*base_gaps, *role_warnings]
    # An already-aware builder is idempotent only if its complete sequence
    # agrees. Do not remove an extra/misordered role warning from either side.
    if current_gaps != base_gaps and current_gaps != expected_gaps:
        raise ValueError("V35_REPORT_ROLE_REBUILT_WARNING_SEQUENCE_MISMATCH")
    if archived_gaps != expected_gaps:
        raise ValueError("V35_REPORT_ROLE_ARCHIVE_WARNING_SEQUENCE_MISMATCH")
    compatible = dict(projected)
    compatible["cannot_confirm"] = expected_gaps
    evidence = (
        "v4_hourly_archive_projection_compat=SOURCE_AUDITED_V35_REPORT_SUBJECT_SCORING_V1",
        f"v4_hourly_archive_projection_compat_source_sha256={source_input_sha256}",
        f"v4_hourly_archive_projection_compat_payload_base_sha256={_payload_base_sha(compatible)}",
        f"v4_hourly_archive_projection_compat_warning_count={len(role_warnings)}",
        f"v4_hourly_archive_projection_compat_warning_list_sha256={_canonical_sha256(role_warnings)}",
    )
    return compatible, evidence


def _source_slot_cutoff(trade_date: str, slot: str) -> datetime:
    """Return the producer cutoff encoded by an exact hourly slot."""
    return datetime.strptime(f"{trade_date}{slot}", "%Y%m%d%H%M").replace(
        second=59,
        microsecond=999999,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )


def _verified_hourly_slot(
    root: Path,
    *,
    trade_date: str,
    cutoff: datetime,
    excluded_slots: set[str] | None = None,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Return the latest slot whose *actual source time* is PIT-safe.

    Slot labels are only coarse candidate bounds.  A 15:00 archive generated
    at 15:00:07 cannot serve a 15:00:00 stage cutoff, so this reader walks
    eligible labels newest-to-oldest and binds the first archive whose
    receipt/manifest identity is valid and whose ``source_generated_at`` is
    not later than the exact cutoff.  Corrupt identity never falls through to
    an older slot; only a valid-but-too-late archive may be skipped.
    """

    cutoff_minutes = cutoff.hour * 60 + cutoff.minute
    store = HourlyResearchStore(root)
    try:
        slots = store.list_slots(trade_date, mode="LIVE")
    except (OSError, TypeError, ValueError) as error:
        raise ResearchContextError(
            f"V4 hourly research slots are not verified: {error}"
        ) from error
    excluded = excluded_slots or set()
    eligible = sorted(
        (
            slot
            for slot in slots
            if _slot_minutes(slot) <= cutoff_minutes and slot not in excluded
        ),
        key=_slot_minutes,
        reverse=True,
    )
    if not eligible:
        raise ResearchContextError(
            "V4 exact-date hourly research slot missing before cutoff"
        )
    rejected_after_cutoff: list[str] = []
    for slot in eligible:
        try:
            payload = store.read_exact(trade_date, slot, mode="LIVE")
        except (OSError, TypeError, ValueError) as error:
            raise ResearchContextError(
                f"V4 exact-date hourly research read failed: {error}"
            ) from error
        if payload is None:
            raise ResearchContextError("V4 exact-date hourly research payload missing")
        relative = HourlyResearchStore._relative(trade_date, slot, "LIVE")
        receipt_relative = HourlyResearchStore._receipt_relative(
            trade_date, slot, "LIVE"
        )
        payload_path = store._path(relative)
        receipt_path = store._path(receipt_relative)
        manifest_path = store._path("manifest.json")
        if not payload_path.is_file() or not receipt_path.is_file() or not manifest_path.is_file():
            raise ResearchContextError(
                "V4 hourly artifact/receipt/manifest pair is incomplete"
            )
        receipt = _read_json(receipt_path, "V4 hourly receipt")
        payload_sha = _sha(payload_path)
        receipt_sha = _sha(receipt_path)
        manifest_sha = _sha(manifest_path)
        canonical_payload_sha = _canonical_sha256(payload)
        if (
            _normalize_date(payload.get("archive_date")) != trade_date
            or receipt.get("archive_date") != trade_date
            or receipt.get("slot") != slot
            or receipt.get("payload_path") != relative
            or receipt.get("payload_sha256") != canonical_payload_sha
            or not _SHA_RE.fullmatch(str(receipt.get("source_input_sha256") or ""))
        ):
            raise ResearchContextError("V4 hourly receipt identity mismatch")
        manifest = store._manifest()
        if manifest.get(relative) != canonical_payload_sha:
            raise ResearchContextError("V4 hourly manifest payload SHA mismatch")
        try:
            generated_at = hourly_source_time(payload.get("source_generated_at"))
        except (TypeError, ValueError) as error:
            raise ResearchContextError("V4 hourly source_generated_at is invalid") from error
        if generated_at > cutoff:
            rejected_after_cutoff.append(
                f"{slot}:{generated_at.isoformat()}>{cutoff.isoformat()}"
            )
            continue
        return slot, payload, {
            "payload_path": str(payload_path),
            "receipt_path": str(receipt_path),
            "manifest_path": str(manifest_path),
            "payload_sha256": payload_sha,
            "receipt_sha256": receipt_sha,
            "manifest_sha256": manifest_sha,
            "source_input_sha256": str(receipt["source_input_sha256"]),
            "actual_source_generated_at": generated_at.isoformat(),
            "pit_rejected_slots": ";".join(rejected_after_cutoff),
        }
    detail = ";".join(rejected_after_cutoff)
    raise ResearchContextError(
        "RESEARCH_ARCHIVE_PIT_AFTER_STAGE_CUTOFF"
        + (f":{detail}" if detail else "")
    )


def _bound_source_rows(
    root: Path, *, payload: Mapping[str, Any], paths: Mapping[str, str],
    trade_date: str, slot: str, cutoff: datetime,
) -> tuple[tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]] | None, tuple[str, ...]]:
    relative = f"research/hourly/source/{paths['source_input_sha256']}.json"
    try:
        raw = SafeRoot(root).read_bytes(relative)
    except FileNotFoundError:
        return None, (f"RESEARCH_SOURCE_WITNESS_MISSING:{relative}",)
    except (OSError, ValueError) as error:
        raise ResearchContextError("RESEARCH_SOURCE_WITNESS_UNSAFE") from error
    if hashlib.sha256(raw).hexdigest() != paths["source_input_sha256"]:
        raise ResearchContextError("RESEARCH_SOURCE_WITNESS_SHA_MISMATCH")
    try:
        source = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(source, Mapping):
            raise ValueError("source must be an object")
        # The witness serves this exact stage decision, not the enclosing hourly
        # slot.  A 15:00:30 observation must not pass a 15:00:00 stage cutoff
        # merely because the 1500 archive slot itself closes at 15:00:59.  The
        # producer's own manifest declaration remains slot-bound, so keep that
        # independent identity check explicit rather than weakening either
        # clock.
        source_cutoff = cutoff
        manifest_pit_cutoff = _source_slot_cutoff(trade_date, slot)
        validate_hourly_stage_source(
            source, trade_date=trade_date, slot=slot, cutoff=source_cutoff,
            manifest_pit_cutoff=manifest_pit_cutoff,
        )
        # Independently compare the original, unchanged archive projection.
        # Hash matching alone must not associate arbitrary source data with it.
        projected = build_research_archive(source, source_input_sha256=paths["source_input_sha256"])
        projected, projection_compat_evidence = _apply_v35_report_role_warning_projection(
            projected,
            source,
            payload,
            trade_date=trade_date,
            slot=slot,
            source_input_sha256=paths["source_input_sha256"],
        )
        if _payload_base_sha(projected) != _payload_base_sha(payload):
            raise ValueError("SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH")
        rows = project_hourly_stage_fields(source)
    except (TypeError, ValueError, UnicodeError) as error:
        raise ResearchContextError(f"RESEARCH_SOURCE_WITNESS_INVALID:{error}") from error
    return rows, (
        f"v4_hourly_source_witness={root / relative}",
        f"v4_hourly_source_witness_sha256={paths['source_input_sha256']}",
        "v4_stage_field_projection=SHA_BOUND_ORIGINAL_SOURCE_NOT_SYNTHETIC_STAGE_EXTENSION",
        f"v4_hourly_source_manifest_sha256={_canonical_sha256(source['source_manifest'])}",
        f"v4_hourly_source_published_at={source['source_manifest'].get('published_at', '')}",
        f"v4_hourly_source_pit_cutoff={source['source_manifest'].get('pit_cutoff', '')}",
        f"v4_hourly_source_pit_cutoff_bound={source_cutoff.isoformat(timespec='seconds')}",
        f"v4_hourly_source_manifest_pit_cutoff_bound={manifest_pit_cutoff.isoformat(timespec='seconds')}",
        "v4_research_delta_scope=SOURCE_DECLARED_FLAGS_NOT_INDEPENDENT_NEWNESS_VERIFICATION",
        *projection_compat_evidence,
    )


def _stage_extension(
    payload: Mapping[str, Any],
    *,
    trade_date: str,
    slot: str,
    paths: Mapping[str, str],
) -> tuple[Mapping[str, Any] | None, list[str]]:
    value = payload.get("stage_evidence_v1")
    if value is None:
        return None, ["RESEARCH_STAGE_EVIDENCE_MISSING"]
    if not isinstance(value, Mapping):
        return None, ["RESEARCH_STAGE_EVIDENCE_INVALID"]
    gaps: list[str] = []
    if value.get("trade_date") != trade_date:
        gaps.append("RESEARCH_STAGE_EVIDENCE_DATE_MISMATCH")
    if value.get("slot") != slot:
        gaps.append("RESEARCH_STAGE_EVIDENCE_SLOT_MISMATCH")
    if value.get("source_input_sha256") != paths.get("source_input_sha256"):
        gaps.append("RESEARCH_STAGE_EVIDENCE_SOURCE_SHA_MISMATCH")
    if value.get("payload_base_sha256") != _payload_base_sha(payload):
        gaps.append("RESEARCH_STAGE_EVIDENCE_PAYLOAD_BASE_SHA_MISMATCH")
    if value.get("payload_sha256_scope") != "ARCHIVE_WITHOUT_STAGE_EVIDENCE_V1":
        gaps.append("RESEARCH_STAGE_EVIDENCE_PAYLOAD_SCOPE_INVALID")
    return value, gaps


def _stage_rows(
    extension: Mapping[str, Any] | None,
    *,
    codes: set[str],
) -> tuple[
    dict[str, list[Mapping[str, Any]]],
    dict[str, list[Mapping[str, Any]]],
    list[str],
]:
    items_by_code: dict[str, list[Mapping[str, Any]]] = {}
    evidence_by_code: dict[str, list[Mapping[str, Any]]] = {}
    gaps: list[str] = []
    if extension is None:
        return items_by_code, evidence_by_code, gaps
    items = extension.get("items")
    evidence = extension.get("evidence")
    if not isinstance(items, list) or not isinstance(evidence, list):
        return items_by_code, evidence_by_code, [
            "RESEARCH_STAGE_EVIDENCE_ROWS_INVALID"
        ]
    for item in items:
        if not isinstance(item, Mapping):
            gaps.append("RESEARCH_STAGE_EVIDENCE_ITEM_INVALID")
            continue
        code = _canonical_a_code(item.get("stock_code"))
        if not code or (codes and code not in codes):
            continue
        if (
            not isinstance(item.get("item_quality"), str)
            or type(item.get("is_new_since_last_slot")) is not bool
            or type(item.get("is_recheck_duplicate")) is not bool
        ):
            gaps.append(f"RESEARCH_STAGE_EVIDENCE_ITEM_INVALID:{code}")
            continue
        items_by_code.setdefault(code, []).append(item)
    for row in evidence:
        if not isinstance(row, Mapping):
            gaps.append("RESEARCH_STAGE_EVIDENCE_ROW_INVALID")
            continue
        code = _canonical_a_code(row.get("stock_code"))
        if not code or (codes and code not in codes):
            continue
        if (
            type(row.get("is_new_since_last_slot")) is not bool
            or type(row.get("is_recheck_duplicate")) is not bool
        ):
            gaps.append(f"RESEARCH_STAGE_EVIDENCE_ROW_INVALID:{code}")
            continue
        evidence_by_code.setdefault(code, []).append(row)
    return items_by_code, evidence_by_code, gaps


def _stage_rows_need_source_fallback(
    items_by_code: Mapping[str, list[Mapping[str, Any]]],
    *,
    codes: set[str],
) -> bool:
    """Return whether optional extension rows leave source facts unbound."""
    for code in codes:
        rows = items_by_code.get(code, [])
        if not rows:
            return True
        if any(
            type(row.get(flag)) is not bool
            for row in rows
            for flag in ("is_new_since_last_slot", "is_recheck_duplicate")
        ):
            return True
        # Numeric quality is optional, but a source witness may carry an
        # explicit finite observation that the extension did not copy.
        if any(
            "quality_score" not in row
            or _safe_float(row.get("quality_score")) is None
            for row in rows
        ):
            return True
    return False


def _merge_source_rows(
    target: dict[str, list[Mapping[str, Any]]],
    source_rows: list[Mapping[str, Any]],
    *,
    codes: set[str],
    identity_fields: tuple[str, ...],
) -> list[str]:
    """Fill missing optional-extension fields from the exact source witness.

    The extension remains the first-class row when it agrees.  A source row
    can only merge by its explicit item/evidence identity; conflicting facts
    are retained as a code-local gap instead of being silently combined.
    """
    gaps: list[str] = []
    for source_row in source_rows:
        code = _canonical_a_code(source_row.get("stock_code"))
        if not code or (codes and code not in codes):
            continue
        candidates = target.setdefault(code, [])
        source_identity = tuple(
            str(source_row.get(field) or "") for field in identity_fields
        )
        match_index: int | None = None
        if any(source_identity):
            for index, candidate in enumerate(candidates):
                candidate_identity = tuple(
                    str(candidate.get(field) or "") for field in identity_fields
                )
                if candidate_identity == source_identity:
                    match_index = index
                    break
        elif len(candidates) == 1:
            match_index = 0
        if match_index is None:
            candidates.append(source_row)
            continue
        current = candidates[match_index]
        conflicts = [
            field
            for field in (
                *identity_fields,
                "quality_score",
                "item_quality",
                "is_new_since_last_slot",
                "is_recheck_duplicate",
            )
            if current.get(field) not in (None, "")
            and source_row.get(field) not in (None, "")
            and current.get(field) != source_row.get(field)
        ]
        if conflicts:
            gaps.append(
                "RESEARCH_STAGE_SOURCE_CONFLICT:"
                + code
                + ":"
                + ",".join(conflicts)
            )
            continue
        merged = dict(source_row)
        merged.update(dict(current))
        candidates[match_index] = merged
    return gaps


def _morning_scores(
    root: Path,
    *,
    trade_date: str,
) -> tuple[
    dict[str, tuple[float, tuple[str, ...]]],
    list[str],
    tuple[str, ...],
]:
    gaps: list[str] = []
    evidence: list[str] = [
        f"v4_morning_news_root={root}",
        f"v4_morning_news_trade_date={trade_date}",
    ]
    try:
        payload = SharedMorningNewsReader(root).read(trade_date)
    except (OSError, TypeError, ValueError) as error:
        raise ResearchContextError(
            f"V4 exact-date morning news verification failed: {error}"
        ) from error
    if payload is None:
        return {}, ["MORNING_NEWS_EXACT_DATE_MISSING"], tuple(evidence)
    for reason in _string_reasons(payload.get("cannot_confirm")):
        gaps.append(reason)
    mentions = payload.get("stock_mentions")
    if not isinstance(mentions, list):
        return {}, [*gaps, "MORNING_NEWS_MENTION_REGISTRY_INVALID"], tuple(evidence)
    scores: dict[str, tuple[float, tuple[str, ...]]] = {}
    for mention in mentions:
        if not isinstance(mention, Mapping):
            gaps.append("MORNING_NEWS_MENTION_INVALID")
            continue
        code = _canonical_a_code(mention.get("stock_code") or mention.get("code"))
        if not code:
            continue
        score = _safe_float(mention.get("news_quality_score"))
        if score is None:
            gaps.append(f"MORNING_NEWS_QUALITY_SCORE_MISSING:{code}")
            continue
        reasons = _string_reasons(
            mention.get("intersection_summary")
            or mention.get("trigger_basis")
            or mention.get("source_title")
        )
        prior = scores.get(code)
        if prior is None or score > prior[0]:
            scores[code] = (score, reasons)
        elif score == prior[0]:
            scores[code] = (score, tuple(dict.fromkeys((*prior[1], *reasons))))
    evidence.append(
        f"v4_morning_news_status={payload.get('status') or payload.get('source_role') or ''}"
    )
    return scores, gaps, tuple(evidence)


def load_research_context(
    v4_data_root: Path | str,
    *,
    trade_date: str,
    stage_cutoff: str,
    morning_root: Path | str | None = None,
) -> ResearchContext:
    """Read the latest verified hourly slot at or before ``stage_cutoff``.

    The selected slot is derived only from the exact-date manifest/receipt
    set.  Missing per-item quality or delta evidence remains a visible gap;
    ``stock_pool.research_score`` is intentionally not used as an alias.
    """
    if _DATE_RE.fullmatch(str(trade_date)) is None:
        raise ResearchContextError("trade_date must be YYYYMMDD")
    root = _v4_data_root(v4_data_root)
    if not root.exists():
        raise ResearchContextError(f"V4 research data root is missing: {root}")
    cutoff_minutes = _cutoff_minutes(stage_cutoff)
    # A slot label alone is not its publication time (15:00:07 cannot serve
    # a 15:00:00 cutoff). Keep exact seconds and select by actual source time.
    clock_parts = str(stage_cutoff).strip().split(":")
    cutoff = datetime.strptime(trade_date, "%Y%m%d").replace(
        hour=cutoff_minutes // 60, minute=cutoff_minutes % 60,
        second=int(clock_parts[2]) if len(clock_parts) == 3 else 0,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    # Archive ``source_generated_at`` is only the first PIT gate.  The bound
    # source witness can contain a later observation that the archive projection
    # does not preserve.  A valid-but-too-late witness makes only that candidate
    # slot unusable; try the next older verified slot.  Identity, SHA, projection
    # and other structural failures remain hard errors and never fall through.
    excluded_slots: set[str] = set()
    witness_pit_rejections: list[str] = []
    while True:
        try:
            slot, payload, paths = _verified_hourly_slot(
                root, trade_date=trade_date, cutoff=cutoff, excluded_slots=excluded_slots
            )
        except ResearchContextError as error:
            if witness_pit_rejections and str(error) == "V4 exact-date hourly research slot missing before cutoff":
                raise ResearchContextError(
                    "RESEARCH_SOURCE_WITNESS_PIT_AFTER_STAGE_CUTOFF:"
                    + ";".join(witness_pit_rejections)
                ) from error
            raise
        try:
            projected_rows, witness_evidence = _bound_source_rows(
                root, payload=payload, paths=paths, trade_date=trade_date, slot=slot, cutoff=cutoff,
            )
        except ResearchContextError as error:
            reason = str(error)
            pit_only = (
                reason.startswith(
                    "RESEARCH_SOURCE_WITNESS_INVALID:HOURLY_SOURCE_MANIFEST_PIT_MISMATCH"
                )
                or reason.startswith(
                    "RESEARCH_SOURCE_WITNESS_INVALID:HOURLY_SOURCE_ROW_PIT_MISMATCH:"
                )
            )
            if not pit_only:
                raise
            excluded_slots.add(slot)
            witness_pit_rejections.append(f"{slot}:{reason}")
            continue
        if witness_pit_rejections:
            paths = dict(paths)
            prior = str(paths.get("pit_rejected_slots") or "")
            paths["pit_rejected_slots"] = ";".join(
                item for item in (prior, *witness_pit_rejections) if item
            )
        break
    pool_codes = {
        code
        for row in payload.get("stock_pool", [])
        if isinstance(row, Mapping)
        for code in (_canonical_a_code(row.get("stock_code")),)
        if code
    }
    article_codes = {
        code
        for row in payload.get("articles", [])
        if isinstance(row, Mapping)
        for code in (_canonical_a_code(row.get("stock_code")),)
        if code
    }
    extension, extension_gaps = _stage_extension(
        payload,
        trade_date=trade_date,
        slot=slot,
        paths=paths,
    )
    items_by_code, evidence_by_code, row_gaps = _stage_rows(
        extension,
        codes=pool_codes | article_codes,
    )
    # ``projected_rows`` / ``witness_evidence`` were bound while choosing the
    # exact usable slot above.  A missing witness still stays visible as
    # CANNOT_CONFIRM; only an explicitly PIT-late, otherwise valid witness may
    # cause selection to move to an older slot.
    source_fallback_needed = extension is None or _stage_rows_need_source_fallback(
        items_by_code,
        codes=pool_codes | article_codes,
    )
    if projected_rows is None:
        extension_gaps.extend(witness_evidence)
    elif source_fallback_needed:
        # The optional extension is a cache of already-produced facts. A
        # partial cache must not hide complete facts in the exact source
        # witness. Merge by explicit identity and preserve code-local
        # conflicts; never manufacture a score or delta.
        source_items, source_rows, source_gaps = projected_rows
        row_gaps.extend(source_gaps)
        row_gaps.extend(
            _merge_source_rows(
                items_by_code,
                source_items,
                codes=pool_codes | article_codes,
                identity_fields=("item_id", "raw_id"),
            )
        )
        row_gaps.extend(
            _merge_source_rows(
                evidence_by_code,
                source_rows,
                codes=pool_codes | article_codes,
                identity_fields=("evidence_id",),
            )
        )
    stage_codes = set(items_by_code) | set(evidence_by_code)
    news_root = _v4_data_root(morning_root if morning_root is not None else root)
    news_scores, news_gaps, morning_evidence = _morning_scores(
        news_root, trade_date=trade_date
    )
    all_codes = pool_codes | article_codes | stage_codes | set(news_scores)
    gaps = list(dict.fromkeys([*extension_gaps, *row_gaps, *news_gaps]))
    if not all_codes:
        gaps.append("RESEARCH_ARCHIVE_HAS_NO_A_CODES")

    source_evidence = [
        f"v4_hourly_data_root={root}",
        f"v4_hourly_payload={paths['payload_path']}",
        f"v4_hourly_payload_sha256={paths['payload_sha256']}",
        f"v4_hourly_manifest={paths['manifest_path']}",
        f"v4_hourly_manifest_sha256={paths['manifest_sha256']}",
        f"v4_hourly_receipt={paths['receipt_path']}",
        f"v4_hourly_receipt_sha256={paths['receipt_sha256']}",
        f"v4_hourly_receipt_payload_sha256={_canonical_sha256(payload)}",
        f"v4_hourly_source_input_sha256={paths['source_input_sha256']}",
        f"v4_hourly_actual_source_generated_at={paths['actual_source_generated_at']}",
        f"v4_hourly_pit_rejected_slots={paths['pit_rejected_slots']}",
        f"v4_hourly_slot={slot}",
        f"v4_stage_cutoff={stage_cutoff}",
        *morning_evidence,
        *witness_evidence,
    ]

    by_code: dict[str, ResearchScore] = {}
    for code in sorted(all_codes):
        item_rows = items_by_code.get(code, [])
        evidence_rows = evidence_by_code.get(code, [])
        reasons: list[str] = []
        code_has_gap = bool(extension_gaps or any(
            ":A." not in gap or gap.rsplit(":", 1)[-1] == code
            for gap in (*row_gaps, *news_gaps)
        ))
        if code in news_scores:
            reasons.extend(news_scores[code][1])
        quality_values = [
            _safe_float(item.get("quality_score"))
            for item in item_rows
            if "quality_score" in item
        ]
        research_quality = (
            max(quality_values)
            if item_rows and len(quality_values) == len(item_rows)
            and all(value is not None for value in quality_values)
            else None
        )
        if research_quality is None:
            gaps.append(f"RESEARCH_ITEM_QUALITY_SCORE_MISSING:{code}")
            code_has_gap = True
        elif item_rows:
            reasons.extend(
                str(item.get("source_title") or "").strip()
                for item in item_rows
                if str(item.get("source_title") or "").strip()
            )
        delta = (
            sum(1 for item in item_rows if item.get("is_new_since_last_slot") is True)
            if item_rows and all(
                type(item.get(flag)) is bool
                for item in item_rows
                for flag in ("is_new_since_last_slot", "is_recheck_duplicate")
            )
            else None
        )
        if delta is None:
            gaps.append(f"RESEARCH_DELTA_FLAGS_MISSING:{code}")
            code_has_gap = True
        for row in evidence_rows:
            reasons.extend(_string_reasons(row.get("cannot_confirm")))
        news = news_scores.get(code)
        if news is None:
            gaps.append(f"MORNING_NEWS_SCORE_MISSING:{code}")
            code_has_gap = True
        by_code[code] = ResearchScore(
            news_quality_score=news[0] if news else None,
            research_quality_score=research_quality,
            latest_research_slot=(
                slot if code in (pool_codes | article_codes | stage_codes) else ""
            ),
            research_delta_hits=delta,
            news_research_reason=tuple(dict.fromkeys(reasons)),
            source_health="READY_WITH_GAPS" if code_has_gap else "READY",
        )
    deduped_gaps = tuple(dict.fromkeys(gaps))
    source_evidence.extend(
        f"v4_research_cannot_confirm={item}" for item in deduped_gaps
    )
    if extension is not None:
        source_evidence.extend(
            (
                f"v4_stage_source_manifest_sha256={extension.get('manifest_sha256')}",
                f"v4_stage_source_receipt_sha256={extension.get('receipt_sha256')}",
            )
        )
    return ResearchContext(
        trade_date=trade_date,
        stage_cutoff=str(stage_cutoff),
        selected_slot=slot,
        by_code=by_code,
        source_evidence=tuple(dict.fromkeys(source_evidence)),
        cannot_confirm=deduped_gaps,
    )


__all__ = [
    "ResearchContext",
    "ResearchContextError",
    "ResearchScore",
    "load_research_context",
]
