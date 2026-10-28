"""Strict, read-only consumer mapping for :mod:`review_core` video evidence.

The consumer is intentionally smaller than the producer.  It resolves one
exact-date ``current.json`` pointer, delegates all integrity checks to
``review_core.core.inspect_bundle`` and exposes stable DTOs for legacy V3
readers.  It never searches old archive pointers and never writes artifacts.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / ".runtime"
DEFAULT_REVIEW_CORE_DATA_ROOT = Path(
    os.environ.get("REVIEW_CORE_DATA_ROOT", str(DEFAULT_DATA_ROOT))
).absolute()
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
# Frozen V3 oracle evidence for the first consumer canary.  Future dates are
# intentionally left open; their exact BV must be supplied by Review Core.
EXPECTED_BV_BY_DATE = {"20260811": "BV14Fuq63E3m"}


def resolve_review_core_data_root(data_root: Path | str | None = None) -> Path:
    """Resolve the only permitted Review Core runtime root.

    V3 may override the root with ``REVIEW_CORE_DATA_ROOT`` for a test or a
    future deployment.  No global/current or V3 artifact root is considered.
    """

    if data_root is not None:
        return Path(data_root).absolute()
    configured = str(os.environ.get("REVIEW_CORE_DATA_ROOT") or "").strip()
    return (Path(configured) if configured else DEFAULT_DATA_ROOT).absolute()


def _core_module() -> Any:
    """Import the sibling core in this isolated package namespace."""

    package = str(__package__ or "").strip()
    if not package:
        raise ImportError("Review Core consumer package namespace is missing")
    return importlib.import_module(".core", package=package)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_payload(trade_date: str, root: Path, reason: str) -> dict[str, Any]:
    flags = {name: False for name in SAFETY_FLAGS}
    comparison = {
        "mode": "read-only",
        "status": "CANNOT_CONFIRM",
        "display_status": "不能确认 Review Core 视频证据",
        "raw_status": {"trade_date": trade_date},
        "gap_row_count": 0,
        "learning_row_count": 0,
        "source_paths": [],
        "rows": [],
        "learning_rows": [],
        "cannot_confirm": [reason],
        "independent_review": {
            "video_input_count": 0,
            "video_augmented_review_complete": False,
        },
        "safety_flags": flags,
    }
    return {
        "status": "CANNOT_CONFIRM",
        "trade_date": trade_date,
        "data_root": str(root),
        "manifest": {},
        "watch_status": {
            "trade_date": trade_date,
            "status": "CANNOT_CONFIRM",
            "today_bv_status": "DAILY_VIDEO_NOT_LOCKED",
            "asr_status": "NOT_RUN",
            "videos": [],
            "checks": {"video_gap_rows": 0, "targeted_spotcheck_count": 0},
            "paths": {"review_core_data_root": str(root)},
            "cannot_confirm": [reason],
            "safety_flags": flags,
        },
        "video_comparison": comparison,
        "safety_flags": flags,
        "cannot_confirm": [reason],
    }


def _artifact_paths(root: Path, manifest: Mapping[str, Any], trade_date: str) -> dict[str, str]:
    current = root / "review" / trade_date / "current.json"
    current_payload = _json(current)
    run_rel = str(current_payload.get("run_path") or "").replace("\\", "/").strip("/")
    for ref in manifest.get("artifact_refs") or []:
        if isinstance(ref, Mapping):
            path = str(ref.get("path") or "")
            if not run_rel and "/runs/" in path:
                parts = Path(path).as_posix().split("/")
                try:
                    run_index = parts.index("runs")
                    if len(parts) > run_index + 1:
                        run_rel = "/".join(parts[: run_index + 2])
                except ValueError:
                    pass
            if run_rel:
                break
    result = {
        "review_core_data_root": str(root),
        "current": str(current),
        "manifest": str(root / run_rel / "manifest.json") if run_rel else "",
        "run": str(root / run_rel) if run_rel else "",
        "capture_manifest": str(root / run_rel / "capture_manifest.json") if run_rel else "",
        "video_gap_audit": str(root / run_rel / "video_gap_audit.json") if run_rel else "",
        "asr_pointer": str(root / run_rel / "asr" / "current_asr_pointer.json") if run_rel else "",
    }
    result["video_gap_matrix"] = result["video_gap_audit"]
    for ref in manifest.get("artifact_refs") or []:
        if not isinstance(ref, Mapping):
            continue
        kind = str(ref.get("kind") or "")
        path = str(ref.get("path") or "")
        if not path:
            continue
        absolute = str(root / Path(path))
        if kind == "transcript" and not result.get("transcript"):
            result["transcript"] = absolute
        elif kind == "segment" and not result.get("segments"):
            result["segments"] = absolute
        elif kind == "media" and not result.get("media"):
            result["media"] = absolute
        elif kind == "audio" and not result.get("audio"):
            result["audio"] = absolute
    return result


def _gap_rows(paths: Mapping[str, str]) -> list[dict[str, Any]]:
    path = Path(str(paths.get("video_gap_audit") or ""))
    payload = _json(path)
    rows = payload.get("gap_rows")
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _map_valid_manifest(trade_date: str, root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    paths = _artifact_paths(root, manifest, trade_date)
    rows = _gap_rows(paths)
    bv_id = str(manifest.get("bv_id") or "")
    date_scope = str(manifest.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED")
    discovery_status = str(manifest.get("discovery_status") or "")
    locked = bool(bv_id and discovery_status == "TARGET_BV_LOCKED")
    asr_status = str(manifest.get("asr_status") or "NOT_RUN")
    gap_status = str(manifest.get("gap_status") or "")
    flags = {name: manifest.get(name) is False for name in SAFETY_FLAGS}
    safe_flags = {name: False for name in SAFETY_FLAGS} if all(flags.values()) else {
        name: manifest.get(name) for name in SAFETY_FLAGS
    }
    cannot_confirm = [str(value) for value in manifest.get("cannot_confirm") or [] if str(value)]
    video = {
        "trade_date": trade_date,
        "target_trade_date": str(manifest.get("target_trade_date") or ""),
        "bv_id": bv_id,
        "title": str(manifest.get("title") or ""),
        "upload_date": str(manifest.get("upload_date") or ""),
        "date_scope": date_scope,
        "discovery_status": discovery_status,
        "capture_status": str(manifest.get("capture_status") or ""),
        "asr_status": asr_status,
        "gap_status": gap_status,
        "asr_segment_count": _safe_int(manifest.get("asr_segment_count")),
        "gap_row_count": _safe_int(manifest.get("gap_row_count")),
        "targeted_spotcheck_count": _safe_int(manifest.get("targeted_spotcheck_count")),
        "media_sha256": str(manifest.get("media_sha256") or ""),
        "transcript_sha256": str(manifest.get("transcript_sha256") or ""),
        "cannot_confirm": cannot_confirm,
        "paths": paths,
        "safety_flags": safe_flags,
    }
    watch_status = {
        "trade_date": trade_date,
        "status": gap_status if locked and gap_status else "DAILY_VIDEO_NOT_LOCKED",
        "today_bv_status": "TODAY_BV_LOCKED" if locked else "DAILY_VIDEO_NOT_LOCKED",
        "asr_status": asr_status,
        "capture_status": str(manifest.get("capture_status") or ""),
        "discovery_status": discovery_status,
        "checks": {
            "video_gap_rows": video["gap_row_count"],
            "asr_segment_count": video["asr_segment_count"],
            "targeted_spotcheck_count": video["targeted_spotcheck_count"],
        },
        "paths": paths,
        "videos": [
            {
                **video,
                "package": paths.get("run", ""),
                "quality": {
                    "gap_rows": video["gap_row_count"],
                    "targeted_spotcheck_count": video["targeted_spotcheck_count"],
                    "transcript_path": paths.get("transcript", ""),
                    "current_review_quality_status": gap_status,
                },
            }
        ] if locked else [],
        "cannot_confirm": cannot_confirm,
        "safety_flags": safe_flags,
    }
    status = "READY" if locked and all(value is False for value in safe_flags.values()) else "CANNOT_CONFIRM"
    if not locked and "DAILY_VIDEO_NOT_LOCKED" not in cannot_confirm:
        cannot_confirm = [*cannot_confirm, "DAILY_VIDEO_NOT_LOCKED"]
    comparison = {
        "mode": "read-only",
        "status": "VIDEO_COMPARISON_READY" if status == "READY" else "CANNOT_CONFIRM",
        "display_status": "Review Core 视频差距已物化" if status == "READY" else "不能确认 Review Core 视频证据",
        "asr_display_status": asr_status,
        "status_boundary": "VideoEvidenceV1 is review evidence only; it never updates independent facts or BUY gate.",
        "raw_status": {
            "trade_date": trade_date,
            "target_trade_date": video["target_trade_date"],
            "bv_id": bv_id,
            "title": video["title"],
            "upload_date": video["upload_date"],
            "date_scope": date_scope,
            "discovery_status": discovery_status,
            "capture_status": video["capture_status"],
            "asr_status": asr_status,
            "gap_status": gap_status,
            "asr_segment_count": video["asr_segment_count"],
            "gap_row_count": video["gap_row_count"],
            "targeted_spotcheck_count": video["targeted_spotcheck_count"],
            "media_sha256": video["media_sha256"],
            "transcript_sha256": video["transcript_sha256"],
        },
        "gap_row_count": video["gap_row_count"],
        "learning_row_count": 1 if locked else 0,
        "source_paths": list(dict.fromkeys([str(value) for value in paths.values() if value])),
        "rows": rows,
        "gap_preview": rows[:8],
        "learning_rows": [video] if locked else [],
        "video_methodology_blocks": [],
        "fallback_context": {},
        "cannot_confirm": cannot_confirm,
        "independent_review": {
            "video_input_count": 0,
            "video_augmented_review_complete": False,
        },
        "safety_flags": safe_flags,
    }
    return {
        "status": status,
        "trade_date": trade_date,
        "data_root": str(root),
        "manifest": manifest,
        "video": video,
        "watch_status": watch_status,
        "video_comparison": comparison,
        "safety_flags": safe_flags,
        "cannot_confirm": cannot_confirm,
    }


def load_video_evidence(
    trade_date: str,
    data_root: Path | str | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Load exactly one Review Core date, returning a fail-closed DTO."""

    target = "".join(ch for ch in str(trade_date) if ch.isdigit())
    root = resolve_review_core_data_root(data_root)
    try:
        if len(target) != 8:
            raise ValueError(f"invalid exact trade date: {trade_date}")
        current_path = root / "review" / target / "current.json"
        if not current_path.is_file():
            raise FileNotFoundError(f"exact-date current pointer missing: {target}")
        core = _core_module()
        manifest = core.inspect_bundle(target, root)
        if not isinstance(manifest, dict):
            raise ValueError("Review Core inspect_bundle returned non-object")
        expected_bv = str(os.environ.get("REVIEW_CORE_TARGET_BV") or EXPECTED_BV_BY_DATE.get(target) or "").strip()
        actual_bv = str(manifest.get("bv_id") or "").strip()
        if expected_bv and actual_bv != expected_bv:
            raise ValueError(f"exact BV mismatch: expected {expected_bv}, got {actual_bv or '<empty>'}")
        return _map_valid_manifest(target, root, manifest)
    except Exception as exc:  # fail-closed adapter boundary
        if strict:
            raise
        return _error_payload(target, root, f"REVIEW_CORE_INVALID: {type(exc).__name__}: {exc}")


def read_exact_video_evidence(
    trade_date: str,
    data_root: Path | str | None = None,
) -> dict[str, Any]:
    """Strict alias used by V3 consumers and tests."""

    return load_video_evidence(trade_date, data_root, strict=True)


def _unique_text(values: Any) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, (list, tuple, set)) else []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _v35_video_layer_from_mapping(mapped: Mapping[str, Any]) -> dict[str, Any]:
    """Project the shared VideoEvidenceV1 DTO into the V3.5 layer shape.

    This is deliberately a projection only: it does not inspect V3.5-owned
    folders, infer a BV, or create any artifact.  ``load_video_evidence`` is
    the sole integrity/date/SHA authority for the input mapping.
    """

    trade_date = str(mapped.get("trade_date") or "")
    video = mapped.get("video") if isinstance(mapped.get("video"), Mapping) else {}
    comparison = (
        mapped.get("video_comparison")
        if isinstance(mapped.get("video_comparison"), Mapping)
        else {}
    )
    raw_flags = mapped.get("safety_flags")
    flags = {
        name: (raw_flags.get(name) if isinstance(raw_flags, Mapping) else None)
        for name in SAFETY_FLAGS
    }
    target_trade_date = str(video.get("target_trade_date") or trade_date)
    cannot_confirm = _unique_text(mapped.get("cannot_confirm"))
    cannot_confirm.extend(
        value
        for value in _unique_text(video.get("cannot_confirm"))
        if value not in cannot_confirm
    )
    cannot_confirm.extend(
        value
        for value in _unique_text(comparison.get("cannot_confirm"))
        if value not in cannot_confirm
    )
    if target_trade_date != trade_date:
        reason = f"V35_VIDEO_DATE_MISMATCH: expected {trade_date}, got {target_trade_date}"
        if reason not in cannot_confirm:
            cannot_confirm.append(reason)

    source_paths = comparison.get("source_paths")
    evidence_paths = dict(video.get("paths") or {}) if isinstance(video.get("paths"), Mapping) else {}
    if not evidence_paths and isinstance(source_paths, (list, tuple)):
        evidence_paths = {
            f"evidence_{index}": str(path)
            for index, path in enumerate(source_paths)
            if str(path or "")
        }

    requested_status = str(mapped.get("status") or "CANNOT_CONFIRM")
    layer_status = str(video.get("gap_status") or "")
    if not layer_status:
        layer_status = (
            "VIDEO_GAP_AUDIT_READY"
            if requested_status == "READY" and video.get("bv_id")
            else requested_status
        )
    if requested_status != "READY":
        layer_status = "CANNOT_CONFIRM"
    if any(value is not False for value in flags.values()):
        layer_status = "CANNOT_CONFIRM"
    independent = comparison.get("independent_review")
    if not isinstance(independent, Mapping):
        independent = {
            "video_input_count": 0,
            "video_augmented_review_complete": False,
        }
    independent_review = {
        "video_input_count": _safe_int(independent.get("video_input_count")),
        "video_augmented_review_complete": bool(
            independent.get("video_augmented_review_complete", False)
        ),
    }
    return {
        "status": layer_status,
        "trade_date": trade_date,
        "target_trade_date": target_trade_date,
        "upload_date": str(video.get("upload_date") or ""),
        "date_scope": str(video.get("date_scope") or ""),
        "bv_id": str(video.get("bv_id") or ""),
        "video_title": str(video.get("title") or ""),
        "asr_status": str(video.get("asr_status") or ""),
        "asr_segment_count": _safe_int(video.get("asr_segment_count")),
        "gap_row_count": _safe_int(video.get("gap_row_count")),
        "targeted_spotcheck_count": _safe_int(video.get("targeted_spotcheck_count")),
        "rows": [dict(row) for row in comparison.get("rows") or [] if isinstance(row, Mapping)],
        "learning_rows": [
            dict(row)
            for row in comparison.get("learning_rows") or []
            if isinstance(row, Mapping)
        ],
        "evidence_paths": evidence_paths,
        "cannot_confirm": cannot_confirm,
        "safety_flags": flags,
        "independent_review": independent_review,
    }


def load_v35_video_layer(
    trade_date: str,
    data_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return the stable V3.5 VideoEvidenceV1 projection.

    The underlying loader remains fail-closed and exact-date.  This function
    is intentionally side-effect free so V3.5 nodes can consume it without
    invoking discovery, capture, ASR, OCR, or gap producers.
    """

    return _v35_video_layer_from_mapping(load_video_evidence(trade_date, data_root))


load_review_core_v35_video_layer = load_v35_video_layer
load_review_core_video = load_video_evidence


__all__ = [
    "DEFAULT_REVIEW_CORE_DATA_ROOT",
    "load_review_core_video",
    "load_review_core_v35_video_layer",
    "load_video_evidence",
    "load_v35_video_layer",
    "read_exact_video_evidence",
    "resolve_review_core_data_root",
]
