"""ops.run_v35_close_review_node: video_session (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __materialize_video_session_body(_v4_scope, /, data_root, date, gap):
    base = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, f"close_review_sources/{date}/bilibili")
    acceptance_path = base / "acceptance.json"
    pointer_path = _v4_global(_v4_scope, '_stockdict_pointer_path')(data_root, date)
    alignment_path = _v4_global(_v4_scope, '_alignment_pointer_path')(data_root, date)
    gap_path = _v4_global(_v4_scope, '_video_gap_path')(data_root, date)
    acceptance = _v4_global(_v4_scope, 'json').loads(acceptance_path.read_bytes().decode("utf-8-sig"))
    locked = acceptance.get("locked_videos") or []
    if acceptance.get("trade_date") != date or not locked or not _v4_global(_v4_scope, 'isinstance')(locked[0], _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ValueError')("locked target video missing for video session")
    video = locked[0]
    segments_path = base / "video_ocr_alignment" / "inputs" / "asr_segments.json"
    segment_count = 0
    if segments_path.is_file():
        segment_payload = _v4_global(_v4_scope, 'json').loads(segments_path.read_bytes().decode("utf-8-sig"))
        segment_count = _v4_global(_v4_scope, 'len')(segment_payload.get("rows") or [])
    targeted = _v4_global(_v4_scope, 'int')(gap.get("targeted_spotcheck_count") or 0)
    session = {
        "schema_version": "v3_5.video_session.v1",
        "status": "VIDEO_SESSION_READY",
        "target_trade_date": date,
        "bv_id": _v4_global(_v4_scope, 'str')(video.get("bv_id") or ""),
        "title": _v4_global(_v4_scope, 'str')(video.get("title") or ""),
        "upload_date": _v4_global(_v4_scope, 'str')(video.get("upload_date") or ""),
        "date_scope": _v4_global(_v4_scope, 'str')(video.get("date_scope") or ""),
        "asr_status": (
            "ASR_SEGMENT_SPOTCHECK_REQUIRED"
            if targeted
            else "ASR_STOCKDICT_OBSERVATION_READY"
        ),
        "asr_segment_count": segment_count,
        "targeted_spotcheck_count": targeted,
        "source_sha256s": {
            "acceptance": _v4_global(_v4_scope, '_sha256_file')(acceptance_path),
            "current_asr_pointer": _v4_global(_v4_scope, '_sha256_file')(pointer_path),
            "alignment_pointer": _v4_global(_v4_scope, '_sha256_file')(alignment_path),
            "video_gap_audit": _v4_global(_v4_scope, '_sha256_file')(gap_path),
        },
        "provenance": "V3_5_NATIVE_DAILY_VIDEO_PIPELINE",
        "cannot_confirm": (
            ["TARGETED_ASR_SEGMENT_SPOTCHECK_REMAINS"]
            if targeted
            else ["MACHINE_SCOPED_OBSERVATION_ONLY_NOT_MARKET_FACT"]
        ),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    destination = _v4_global(_v4_scope, '_video_session_path')(data_root, date)
    _v4_global(_v4_scope, '_capture_write')(destination, session)
    return destination
