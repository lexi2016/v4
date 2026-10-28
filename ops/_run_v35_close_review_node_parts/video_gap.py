"""ops.run_v35_close_review_node: video_gap (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __fupan_video_gap_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_GAP",
        )
    current_asr_pointer = _v4_global(_v4_scope, '_stockdict_pointer_path')(data_root, date)
    alignment_pointer = _v4_global(_v4_scope, '_alignment_pointer_path')(data_root, date)
    review_path = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, f"a_share_reviews/{date}.json")
    gap_path = _v4_global(_v4_scope, '_video_gap_path')(data_root, date)
    missing = [
        name
        for name, path in (
            ("current_asr_pointer", current_asr_pointer),
            ("alignment_pointer", alignment_pointer),
            ("review", review_path),
        )
        if not path.is_file()
    ]
    if missing:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "DEPENDENCY_MISSING",
            "missing " + ", ".join(missing),
            {},
        )
    try:
        result = _v4_global(_v4_scope, 'materialize_gap_audit')(
            data_root,
            date,
            current_asr_pointer_path=current_asr_pointer,
            alignment_pointer_path=alignment_pointer,
            review_path=review_path,
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "current_asr_pointer": _v4_global(_v4_scope, 'str')(current_asr_pointer),
        "alignment_pointer": _v4_global(_v4_scope, 'str')(alignment_pointer),
        "review": _v4_global(_v4_scope, 'str')(review_path),
        "video_gap_audit": _v4_global(_v4_scope, 'str')(gap_path),
    }
    status = _v4_global(_v4_scope, 'str')(result.get("status") or "")
    if status == "VIDEO_GAP_AUDIT_READY" and gap_path.is_file():
        try:
            video_session = _v4_global(_v4_scope, '_materialize_video_session')(data_root, date, result)
        except _v4_global(_v4_scope, 'Exception') as error:
            return (
                "FAIL",
                "HANDLER_ERROR",
                f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
                artifacts,
            )
        artifacts["video_session"] = _v4_global(_v4_scope, 'str')(video_session)
        return (
            "SUCCESS",
            "VIDEO_GAP_AUDIT_READY",
            "video gap audit materialized",
            artifacts,
        )
    if status in {"NOT_MATERIALIZED", "VIDEO_GAP_AUDIT_PARTIAL"}:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            status,
            _v4_global(_v4_scope, 'str')(result.get("reason") or ""),
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        status or "GAP_AUDIT_INCOMPLETE",
        _v4_global(_v4_scope, 'str')(result.get("reason") or ""),
        artifacts,
    )
