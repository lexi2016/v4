"""Bounded, read-only raw ASR projection from a verified same-day bundle.

Content availability never promotes the producer's ASR or review status.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


MAX_SEGMENT_BYTES = 2 * 1024 * 1024
MAX_SEGMENT_ROWS = 5000
_QUALITY = "原始 ASR 转写，未经人工复核，可能有识别错误或非复盘内容；不构成已采纳的市场结论。"


def _relative_segment_path(value: Any, target: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("VIDEO_CONTENT_INVALID_PATH")
    path = PurePosixPath(value)
    if (
        path.is_absolute() or ".." in path.parts or "." in value.split("/")
        or len(path.parts) < 6 or path.parts[:3] != ("review", target, "runs")
    ):
        raise ValueError("VIDEO_CONTENT_INVALID_PATH")
    return path


def _read_segment_bytes(root: Path, relative: PurePosixPath, size: Any) -> bytes:
    """Walk using no-follow directory descriptors, including the final file."""
    if type(size) is not int or not 0 < size <= MAX_SEGMENT_BYTES:
        raise ValueError("VIDEO_CONTENT_SIZE_LIMIT_OR_MISMATCH")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                raise ValueError("VIDEO_CONTENT_SIZE_LIMIT_OR_MISMATCH")
            data = stream.read(MAX_SEGMENT_BYTES + 1)
        if len(data) != size:
            raise ValueError("VIDEO_CONTENT_SIZE_LIMIT_OR_MISMATCH")
        return data
    finally:
        os.close(directory)


def _manifest_binds(manifest: Mapping[str, Any], ref: Mapping[str, Any], video: Mapping[str, Any], target: str) -> bool:
    readiness = manifest.get("readiness")
    bound_video = readiness.get("video") if isinstance(readiness, Mapping) else None
    if not isinstance(bound_video, Mapping) or any(
        bound_video.get(key) != video.get(key)
        for key in ("trade_date", "target_trade_date", "bv_id", "asr_segment_count")
    ):
        return False
    bound_artifacts = bound_video.get("artifact_refs")
    if not isinstance(bound_artifacts, list) or not any(
        isinstance(item, Mapping) and item.get("kind") == "segment"
        and all(item.get(key) == ref.get(key) for key in ("path", "sha256", "size"))
        for item in bound_artifacts
    ):
        return False
    refs = manifest.get("source_refs")
    if not isinstance(refs, list):
        return False
    for bound in refs:
        if not isinstance(bound, Mapping):
            continue
        identity = bound.get("semantic_identity")
        if (
            bound.get("artifact_kind") == "segment"
            and bound.get("artifact_path") == ref.get("path")
            and bound.get("sha256") == ref.get("sha256")
            and isinstance(identity, Mapping)
            and identity.get("trade_date") == target
            and identity.get("sha256") == ref.get("sha256")
            and identity.get("size") == ref.get("size")
        ):
            return True
    return False


def _segments(data: bytes, sha: str, expected_count: Any) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    columns = reader.fieldnames or []
    if len(columns) != len(set(columns)) or not {"segment_index", "start", "end", "text"} <= set(columns):
        raise ValueError("VIDEO_CONTENT_INVALID_CSV_COLUMNS")
    rows = []
    seen = set()
    for row in reader:
        if len(rows) >= MAX_SEGMENT_ROWS or None in row or any(value is None for value in row.values()):
            raise ValueError("VIDEO_CONTENT_INVALID_CSV_ROW")
        index = row["segment_index"]
        if not re.fullmatch(r"[0-9]+", index) or index in seen or not row["text"].strip():
            raise ValueError("VIDEO_CONTENT_INVALID_CSV_ROW")
        start, end = float(row["start"]), float(row["end"])
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end:
            raise ValueError("VIDEO_CONTENT_INVALID_TIME")
        seen.add(index)
        rows.append({
            "segment_id": index, "start_seconds": start, "end_seconds": end,
            "text": row["text"], "evidence_status": "ASR_UNVERIFIED", "source_sha256": sha,
        })
    if not rows or type(expected_count) is not int or len(rows) != expected_count:
        raise ValueError("VIDEO_CONTENT_SEGMENT_COUNT_MISMATCH")
    return rows


def video_transcript_content(
    video: Mapping[str, Any], target: str, root: Path, manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only content fields; invalid ASR cannot invalidate market review."""
    result: dict[str, Any] = {
        "transcript_segments": [], "content_status": "CANNOT_CONFIRM",
        "content_quality": {"status": "ASR_UNVERIFIED", "message": _QUALITY, "segment_count": 0},
        "content_cannot_confirm": [], "content_source": None,
    }
    try:
        refs = video.get("artifact_refs") or []
        if not isinstance(refs, list):
            raise ValueError("VIDEO_CONTENT_INVALID_ARTIFACT_REFS")
        candidates = [ref for ref in refs if isinstance(ref, Mapping) and ref.get("kind") == "segment"]
        if not candidates:
            raise ValueError("VIDEO_CONTENT_NO_SEGMENT_ARTIFACT")
        if (
            video.get("trade_date") != target or video.get("target_trade_date") != target
            or video.get("date_scope") != "SAME_DAY_FUPAN"
            or video.get("discovery_status") != "TARGET_BV_LOCKED"
            or not re.fullmatch(r"BV[A-Za-z0-9]{10}", str(video.get("bv_id") or ""))
        ):
            raise ValueError("VIDEO_CONTENT_SAME_DAY_IDENTITY_REQUIRED")
        if len(candidates) != 1:
            raise ValueError("VIDEO_CONTENT_AMBIGUOUS_SEGMENT_ARTIFACT")
        ref = candidates[0]
        relative = _relative_segment_path(ref.get("path"), target)
        sha = ref.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("VIDEO_CONTENT_INVALID_SHA")
        if not _manifest_binds(manifest, ref, video, target):
            raise ValueError("VIDEO_CONTENT_MANIFEST_BINDING_REQUIRED")
        data = _read_segment_bytes(root, relative, ref.get("size"))
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError("VIDEO_CONTENT_SHA_MISMATCH")
        rows = _segments(data, sha, video.get("asr_segment_count"))
        result.update(
            transcript_segments=rows, content_status="RAW_ASR_AVAILABLE",
            content_source={"path": str(relative), "sha256": sha},
        )
        result["content_quality"]["segment_count"] = len(rows)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("VIDEO_CONTENT_") else "VIDEO_CONTENT_UNREADABLE_OR_INVALID_CSV"
        result["content_cannot_confirm"] = [reason]
    return result
