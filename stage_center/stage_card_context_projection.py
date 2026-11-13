"""Read-only context for native preopen cards; no selection or price model."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from contracts.stages import STAGE_DEFINITIONS


def stage_card_cutoff(market: dict, *, trade_date: str) -> str:
    """Resolve only an explicit cutoff or the SHA-bound native 0925 contract."""
    evidence = market.get("source_evidence") or []
    def values(key: str) -> set[str]:
        return {v.split("=", 1)[1] for v in evidence
                if isinstance(v, str) and v.startswith(key + "=")}
    cutoffs = values("v4_stage_cutoff")
    native = values("route") == {"a_share_native_quote_snapshot"}
    if len(cutoffs) > 1:
        raise ValueError("STAGE_CUTOFF_CONFLICT")
    if not native:
        if len(cutoffs) != 1:
            raise ValueError("STAGE_CUTOFF_MISSING")
        value = next(iter(cutoffs))
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", value) is None:
            raise ValueError("STAGE_CUTOFF_INVALID")
        return value + ":00" if len(value) == 5 else value
    if (market.get("selection_manifest_receipt_verified") is not True
            or market.get("stage_id") != "STAGE_0925"
            or market.get("trade_date") != trade_date
            or market.get("market") != "A_SHARE"
            or values("native_snapshot_contract") != {"V4_A_OPENING_NATIVE_SNAPSHOT_V1"}
            or len(values("native_snapshot_manifest")) != 1
            or len(values("native_snapshot_sha256")) != 1):
        raise ValueError("NATIVE_STAGE_CUTOFF_IDENTITY_MISSING")
    path = Path(next(iter(values("native_snapshot_manifest"))))
    if not path.is_absolute() or path.name != "manifest.json":
        raise ValueError("NATIVE_STAGE_CUTOFF_MANIFEST_INVALID")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw = path.with_name("snapshot.json").read_bytes()
    snapshot = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if (manifest.get("schema_version") != "stage_center.a_opening_native_snapshot.v1.manifest"
            or manifest.get("artifact_relative") != f"native_opening/{trade_date}/STAGE_0925/snapshot.json"
            or manifest.get("artifact_sha256") != digest
            or values("native_snapshot_sha256") != {digest}
            or snapshot.get("schema_version") != "stage_center.a_opening_native_snapshot.v1"
            or any(obj.get("trade_date") != trade_date or obj.get("stage_id") != "STAGE_0925"
                   for obj in (manifest, snapshot))
            or any(obj.get(flag) is not False for obj in (manifest, snapshot)
                   for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("NATIVE_STAGE_CUTOFF_BINDING_INVALID")
    boundary = datetime.strptime(trade_date, "%Y%m%d").replace(
        hour=9, minute=25, second=5, tzinfo=ZoneInfo("Asia/Shanghai"))
    cutoff = STAGE_DEFINITIONS["STAGE_0925"]["cutoff"]
    if (boundary.strftime("%H:%M:%S") != cutoff
            or datetime.fromisoformat(snapshot["market_cutoff_at"]) != boundary
            or snapshot.get("temporal_cutoff_safe") is not True
            or snapshot.get("RESEARCH_ONLY") is not True
            or manifest.get("captured_at") != snapshot.get("captured_at")
            or values("native_snapshot_captured_at") != {snapshot.get("captured_at")}
            or not boundary.replace(second=0) <= datetime.fromisoformat(snapshot["captured_at"]) <= boundary
            or (cutoffs and cutoffs != {cutoff})):
        raise ValueError("NATIVE_STAGE_CUTOFF_CONFLICT")
    return cutoff


def research_card_context(rows: list[dict], market: dict, *, trade_date: str,
                          cutoff: str, research_root: Path | str | None,
                          morning_root: Path | str | None) -> list[dict]:
    """Expose verified original research scores separately from original stage fields."""
    from stage_center.research_context import ResearchContextError, load_research_context
    context = None
    error = "RESEARCH_DATA_ROOT_NOT_CONFIGURED"
    if research_root:
        try:
            context = load_research_context(research_root, trade_date=trade_date,
                                           stage_cutoff=cutoff, morning_root=morning_root)
            error = ""
        except (OSError, ValueError, TypeError, KeyError) as exc:
            error = str(exc) if isinstance(exc, ResearchContextError) else "RESEARCH_CONTEXT_READ_FAILED"
    provenance = [v for v in context.source_evidence if v.startswith((
        "v4_hourly_payload=", "v4_hourly_payload_sha256=", "v4_hourly_manifest=",
        "v4_hourly_manifest_sha256=", "v4_hourly_receipt=", "v4_hourly_receipt_sha256=",
        "v4_hourly_source_input_sha256=", "v4_hourly_source_witness=",
        "v4_hourly_source_witness_sha256=", "v4_hourly_actual_source_generated_at=",
        "v4_hourly_source_published_at=", "v4_hourly_source_pit_cutoff_bound=",
        "v4_hourly_warning_projection_compatibility=", "v4_hourly_legacy_archive_base_sha256=",
        "v4_hourly_expanded_source_gaps_sha256=", "v4_hourly_legacy_archive_warnings=",
    ))] if context else []
    has_witness = any(v.startswith("v4_hourly_source_witness_sha256=") for v in provenance)
    available_at = next((v.split("=", 1)[1] for v in provenance
                         if v.startswith("v4_hourly_actual_source_generated_at=")), None)
    available_at = available_at or next((v.split("=", 1)[1] for v in provenance
                                         if v.startswith("v4_hourly_source_published_at=")), None)
    result = []
    for source in rows:
        row = dict(source)
        if isinstance(row.get("research_quality_score"), (int, float)):
            result.append(row)
            continue
        code = "A." + str(row.get("code") or "").split(".")[-1]
        item = context.by_code.get(code) if context else None
        reason = error or ("RESEARCH_CONTEXT_CODE_MISSING:" + code if item is None
                           else "RESEARCH_ITEM_QUALITY_SCORE_MISSING:" + code)
        if item and not has_witness:
            reason = "RESEARCH_SOURCE_WITNESS_MISSING"
        row["research_context_check"] = {
            "trade_date": trade_date, "cutoff": cutoff,
            "slot": context.selected_slot if context else None,
            "status": "VERIFIED" if item and has_witness else "CANNOT_CONFIRM",
            "reason": reason, "source_evidence": provenance,
        }
        if item and has_witness and item.research_quality_score is not None:
            row["research_link"] = {
                "score": item.research_quality_score, "trade_date": trade_date,
                "slot": context.selected_slot, "cutoff": cutoff,
                "available_at": available_at, "source_evidence": provenance,
                "source_notes": list(item.news_research_reason),
                "selection_artifact_sha256": market.get("selection_artifact_sha256"),
                "mode": "READ_ONLY_SUPPLEMENT_NOT_IN_ORIGINAL_STAGE_SCORE",
                "pit_status": "SOURCE_AND_WITNESS_VALIDATED_AT_CUTOFF",
            }
            row["research_context_check"].update(status="VERIFIED", reason="")
            row["research_missing_reason"] = "原阶段未生成研报分；盘前研报补充未计入原阶段分"
        else:
            label = ("盘前研报归档与原始来源投影不一致，未补分"
                     if "SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH" in reason
                     else "截至该阶段的研报来源或个股质量分未通过核验，未补分")
            if context and has_witness:
                slot_label = context.selected_slot[:2] + ":" + context.selected_slot[2:]
                label = (f"{slot_label} 研报归档无该股记录（已核验）" if item is None
                         else f"{slot_label} 已核验归档未提供个股质量分")
            row["research_missing_reason"] = label
        result.append(row)
    return result


def exact_legacy_warning_projection(projected: dict, source: dict, payload: dict) -> tuple[dict, tuple[str, ...]]:
    """Recognize only the old count representation, after all source/PIT gates.

    This reconstructs the archived builder's known warning format. Every other
    field and the complete resulting payload still have to match the archive.
    Original source warnings remain in the bound witness and are hash cited.
    """
    from domains.research import build_research_archive, project_legacy_source_gaps
    from infrastructure.data_store import _sha256
    def base(value: dict) -> dict:
        return {k: v for k, v in value.items() if k not in ("stage_evidence_v1", "cannot_confirm")}
    gaps = source.get("cannot_confirm")
    if (not isinstance(gaps, list) or not gaps
            or base(projected) != base(payload)
            or f"LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:{len(gaps)}" not in payload.get("cannot_confirm", [])):
        return projected, ()
    without_gaps = dict(source, cannot_confirm=[])
    old_base = build_research_archive(without_gaps, source_input_sha256=payload["source_input_sha256"])
    legacy = dict(projected)
    legacy["cannot_confirm"] = sorted(set([
        *old_base.get("cannot_confirm", []), *_legacy_report_role_warning_reasons(source),
        f"LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:{len(gaps)}",
    ]))
    expected = {k: v for k, v in payload.items() if k != "stage_evidence_v1"}
    if _sha256({k: v for k, v in legacy.items() if k != "stage_evidence_v1"}) != _sha256(expected):
        return projected, ()
    return legacy, (
        "v4_hourly_warning_projection_compatibility=EXACT_LEGACY_SOURCE_GAP_COUNT",
        f"v4_hourly_legacy_archive_base_sha256={_sha256(expected)}",
        f"v4_hourly_expanded_source_gaps_sha256={_sha256(project_legacy_source_gaps(source))}",
        "v4_hourly_legacy_archive_warnings=" + json.dumps(payload["cannot_confirm"], ensure_ascii=False, separators=(",", ":")),
    )


def _context_text(value: Any) -> str:
    return str(value or "").strip()


def _legacy_report_role_warning_reasons(source: Mapping[str, Any]) -> list[str]:
    """Project source-bound excluded report entities as non-blocking warnings.

    The audit is part of the immutable hourly source witness.  Only emit a
    warning after its affected-code summary agrees with the individually
    excluded evidence and every evidence path resolves to a declared source
    receipt.  This keeps the projection deterministic without binding it to a
    particular date or source digest.
    """
    audit = source.get("report_entity_audit")
    if audit is None:
        return []
    if not isinstance(audit, Mapping) or audit.get("policy_version") != "report_subject_scoring.v1":
        raise ValueError("REPORT_ROLE_AUDIT_POLICY_MISSING_OR_UNKNOWN")

    affected = audit.get("affected_codes")
    excluded = audit.get("excluded_evidence")
    manifest = source.get("source_manifest")
    receipts = manifest.get("source_receipts") if isinstance(manifest, Mapping) else None
    source_date = _context_text(source.get("trade_date"))
    source_slot = _context_text(source.get("slot") or (manifest or {}).get("hourly_slot")) if isinstance(manifest, Mapping) else ""
    if (
        re.fullmatch(r"\d{8}", source_date) is None
        or re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", source_slot) is None
        or not isinstance(manifest, Mapping)
        or manifest.get("trade_date") != source_date
        or manifest.get("hourly_slot") != source_slot
        or not isinstance(affected, list)
        or any(not isinstance(code, str) or re.fullmatch(r"(?:\d{6}|HK\.\d{5})", code) is None for code in affected)
        or affected != sorted(set(affected))
        or not isinstance(excluded, list)
        or type(audit.get("excluded_evidence_count")) is not int
        or audit.get("excluded_evidence_count") != len(excluded)
        or not isinstance(receipts, list)
        or not receipts
        or any(not isinstance(path, str) or not path.strip() for path in receipts)
        or len(receipts) != len(set(receipts))
    ):
        raise ValueError("REPORT_ROLE_AUDIT_SHAPE_INVALID")

    excluded_codes: set[str] = set()
    evidence_ids: set[str] = set()
    for item in excluded:
        if not isinstance(item, Mapping):
            raise ValueError("REPORT_ROLE_AUDIT_EXCLUDED_EVIDENCE_INVALID")
        role = item.get("entity_role")
        code = item.get("stock_code")
        evidence_id = item.get("evidence_id")
        source_path = item.get("source_path")
        if (
            not isinstance(role, str)
            or not role.strip()
            or item.get("research_subject_eligible") is not False
            or not isinstance(code, str)
            or re.fullmatch(r"(?:\d{6}|HK\.\d{5})", code) is None
            or not isinstance(evidence_id, str)
            or not evidence_id.strip()
            or evidence_id in evidence_ids
            or not isinstance(source_path, str)
            or source_path not in receipts
        ):
            raise ValueError("REPORT_ROLE_AUDIT_EXCLUDED_EVIDENCE_INVALID")
        evidence_ids.add(evidence_id)
        excluded_codes.add(code)

    if sorted(excluded_codes) != affected:
        raise ValueError("REPORT_ROLE_AUDIT_AFFECTED_CODE_MISMATCH")
    return [f"REPORT_ROLE_EVIDENCE_EXCLUDED:{code}" for code in affected]

