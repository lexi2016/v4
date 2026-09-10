from __future__ import annotations

import json
from pathlib import Path

from ops.capture_bilibili_fupan import capture_locked_video


def _acceptance(path: Path, *, locked: bool) -> None:
    payload = {
        "trade_date": "20260731",
        "today_bv_status": "TODAY_BV_LOCKED" if locked else "DAILY_VIDEO_NOT_LOCKED",
        "locked_videos": [{"bv_id": "BV1sameDay", "source_url": "https://www.bilibili.com/video/BV1sameDay/"}] if locked else [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_unlocked_date_never_invokes_media_tools(tmp_path: Path) -> None:
    acceptance = tmp_path / "acceptance.json"
    _acceptance(acceptance, locked=False)
    called = []
    manifest = capture_locked_video(
        tmp_path / "data", "20260731", acceptance_path=acceptance,
        yt_dlp=["yt-dlp"], ffmpeg="ffmpeg", funasr_script=tmp_path / "missing.py",
        runner=lambda command: called.append(command) or {"returncode": 0},
    )

    assert manifest["status"] == "NOT_MATERIALIZED"
    assert called == []


def test_locked_public_video_runs_capture_audio_asr_but_stays_review_required(tmp_path: Path) -> None:
    acceptance = tmp_path / "acceptance.json"
    _acceptance(acceptance, locked=True)
    funasr = tmp_path / "funasr.py"
    funasr.write_text("# fake", encoding="utf-8")

    def runner(command: list[str]) -> dict:
        if "-o" in command:
            template = Path(command[command.index("-o") + 1])
            Path(str(template).replace("%(ext)s", "m4a")).write_bytes(b"media")
        elif "-ar" in command:
            Path(command[-1]).write_bytes(b"wav")
        elif "--out-dir" in command:
            out = Path(command[command.index("--out-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "BV1sameDay.funasr_raw.txt").write_text("raw asr", encoding="utf-8")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    manifest = capture_locked_video(
        tmp_path / "data", "20260731", acceptance_path=acceptance,
        yt_dlp=["python", "-m", "yt_dlp"], ffmpeg="ffmpeg", funasr_script=funasr,
        runner=runner,
    )

    assert manifest["status"] == "ASR_REVIEW_REQUIRED"
    assert manifest["videos"][0]["reason"] == "ASR_STOCKDICT_NOT_RUN"
    assert manifest["videos"][0]["transcript_files"] == ["BV1sameDay.funasr_raw.txt"]
    assert manifest["production_allowed"] is False
