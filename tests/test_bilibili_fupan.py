from __future__ import annotations

import json
from pathlib import Path

from domains.bilibili_fupan import build_video_acceptance, classify_video_date
from ops.check_bilibili_fupan import discover_bilibili_fupan, write_discovery


def test_title_and_upload_date_bind_the_same_day_without_copying_video_claims() -> None:
    assert classify_video_date("7.31 A股复盘", "20260731", "20260731") == "SAME_DAY_FUPAN"
    assert classify_video_date("Python 回测系统教程", "20260731", "20260731") == "NOT_FUPAN"
    acceptance = build_video_acceptance(
        "20260731",
        [{"bv_id": "BV1abc123", "title": "7.31 A股复盘", "upload_date": "20260731", "uploader": "比巴卜作手"}],
    )
    assert acceptance["status"] == "VIDEO_METADATA_READY"
    assert acceptance["today_bv_status"] == "TODAY_BV_LOCKED"
    assert acceptance["asr_status"] == "NOT_USED"
    assert acceptance["checks"]["no_video_claim_promoted_to_market_fact"] is True


def test_discovery_uses_flat_list_only_as_shortlist_and_full_metadata_for_decision() -> None:
    commands: list[list[str]] = []

    def runner(command: list[str]) -> dict:
        commands.append(command)
        if "--flat-playlist" in command:
            return {"returncode": 0, "stdout": "BV1sameDay\nBV1course\n", "stderr": ""}
        bv = "BV1sameDay" if "BV1sameDay" in command[-1] else "BV1course"
        payload = {
            "title": "7.31 指数复盘" if bv == "BV1sameDay" else "Python 回测系统教程",
            "upload_date": "20260731",
            "duration": 600,
            "uploader": "比巴卜作手",
        }
        return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}

    acceptance = discover_bilibili_fupan(
        "20260731", yt_dlp="yt-dlp.exe", runner=runner
    )

    assert acceptance["checks"]["source_index_rows"] == 2
    assert acceptance["checks"]["same_day_video_count"] == 1
    assert len(commands) == 3
    assert all("--cookies-from-browser" not in command for command in commands)
    assert all("--dump-single-json" in command for command in commands[1:])


def test_missing_tool_is_typed_and_owned_output_has_hashes(tmp_path: Path) -> None:
    acceptance = discover_bilibili_fupan("20260731", yt_dlp=None)
    manifest = write_discovery(tmp_path / "data", acceptance)

    assert acceptance["status"] == "TOOL_BLOCKED"
    assert acceptance["today_bv_status"] == "DAILY_VIDEO_NOT_LOCKED"
    assert manifest["files"]
    assert (tmp_path / "data" / "close_review_sources" / "20260731" / "bilibili" / "acceptance.json").is_file()
    assert manifest["production_allowed"] is False


def test_empty_public_shortlist_is_not_misreported_as_no_new_video() -> None:
    acceptance = discover_bilibili_fupan(
        "20260731",
        yt_dlp="yt-dlp.exe",
        runner=lambda command: {"returncode": 0, "stdout": "", "stderr": ""},
    )

    assert acceptance["status"] == "BLOCKED_NEED_USER_COOKIE_OR_BV"
    assert acceptance["today_bv_status"] == "DAILY_VIDEO_NOT_LOCKED"
    assert acceptance["cannot_confirm"] == ["UP_SHORTLIST_EMPTY"]
