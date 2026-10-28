"""ops.run_v35_close_review_node: video_download (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __video_check_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(data_root=data_root, date=date, node="FUPAN_VIDEO_CHECK")
    discovery_runner = _v4_global(_v4_scope, '_default_discovery_runner')()
    acceptance = _v4_global(_v4_scope, 'discover_bilibili_fupan')(
        date,
        yt_dlp=discovery_runner,
        runner=_v4_global(_v4_scope, '_run_within_repo'),
    )
    _v4_global(_v4_scope, 'write_discovery')(data_root, acceptance)
    artifacts = {
        "acceptance": _v4_global(_v4_scope, 'str')(
            _v4_global(_v4_scope, 'resolve_owned_path')(
                data_root, f"close_review_sources/{date}/bilibili/acceptance.json"
            )
        ),
        "source_index": _v4_global(_v4_scope, 'str')(
            _v4_global(_v4_scope, 'resolve_owned_path')(
                data_root, f"close_review_sources/{date}/bilibili/source_index.json"
            )
        ),
        "manifest": _v4_global(_v4_scope, 'str')(
            _v4_global(_v4_scope, 'resolve_owned_path')(
                data_root, f"close_review_sources/{date}/bilibili/manifest.json"
            )
        ),
    }
    if (
        acceptance.get("today_bv_status") == "TODAY_BV_LOCKED"
        and _v4_global(_v4_scope, 'isinstance')(acceptance.get("locked_videos"), _v4_global(_v4_scope, 'list'))
        and acceptance["locked_videos"]
    ):
        return (
            "SUCCESS",
            "TODAY_BV_LOCKED",
            "same-day fupan video locked",
            artifacts,
        )
    reason = _v4_global(_v4_scope, 'str')(
        acceptance.get("today_bv_status")
        or acceptance.get("lookup_reason")
        or "SAME_DAY_VIDEO_NOT_LOCKED"
    )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        reason,
        reason,
        artifacts,
    )


def __video_download_asr_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_DOWNLOAD_ASR",
        )
    acceptance = data_root / "close_review_sources" / date / "bilibili" / "acceptance.json"
    locked = False
    if acceptance.is_file():
        try:
            payload = _v4_global(_v4_scope, 'json').loads(acceptance.read_bytes().decode("utf-8-sig"))
            locked = (
                payload.get("trade_date") == date
                and payload.get("today_bv_status") == "TODAY_BV_LOCKED"
                and _v4_global(_v4_scope, 'isinstance')(payload.get("locked_videos"), _v4_global(_v4_scope, 'list'))
                and _v4_global(_v4_scope, 'bool')(payload["locked_videos"])
            )
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
            locked = False
    if not locked:
        refresh_status, refresh_reason, refresh_details, refresh_artifacts = _v4_global(_v4_scope, '_video_check')(
            data_root=data_root,
            date=date,
            loopback_base_url=loopback_base_url,
            http_getter=http_getter,
            funasr_script=funasr_script,
            ffmpeg=ffmpeg,
            selector_data_root=selector_data_root,
        )
        if refresh_status != "SUCCESS":
            return (
                "ACTION_RAN_WITH_CANNOT_CONFIRM",
                refresh_reason,
                refresh_details,
                refresh_artifacts,
            )
    try:
        manifest = _v4_global(_v4_scope, 'capture_locked_video')(
            data_root,
            date,
            acceptance_path=acceptance,
            yt_dlp=[_v4_global(_v4_scope, 'sys').executable, "-m", "yt_dlp"],
            ffmpeg=ffmpeg if ffmpeg is not None else _v4_global(_v4_scope, '_resolve_ffmpeg')(),
            funasr_script=funasr_script if funasr_script is not None else _v4_global(_v4_scope, '_resolve_funasr_script')(),
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            {},
        )
    manifest_path = _v4_global(_v4_scope, 'resolve_owned_path')(
        data_root, f"close_review_sources/{date}/bilibili/capture_manifest.json"
    )
    _v4_global(_v4_scope, '_capture_write')(manifest_path, manifest)
    artifacts = {"capture_manifest": _v4_global(_v4_scope, 'str')(manifest_path)}
    status = _v4_global(_v4_scope, 'str')(manifest.get("status") or "")
    if status == "ASR_REVIEW_REQUIRED":
        videos = manifest.get("videos")
        if _v4_global(_v4_scope, 'isinstance')(videos, _v4_global(_v4_scope, 'list')) and _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'isinstance')(video, _v4_global(_v4_scope, 'dict')) and video.get("transcript_files")
            for video in videos
        ):
            return (
                "SUCCESS",
                "ASR_REVIEW_REQUIRED",
                "capture manifest materialized with transcripts",
                artifacts,
            )
    if status in {"NOT_MATERIALIZED", "TOOL_BLOCKED"}:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            status,
            _v4_global(_v4_scope, 'str')(manifest.get("reason") or ""),
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        status or "CAPTURE_INCOMPLETE",
        "capture manifest materialized without transcripts",
        artifacts,
    )
