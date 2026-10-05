"""Capture a locked exact-date Bilibili review video and run local ASR."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from infrastructure.data_store import _canonical_bytes, _date
from infrastructure.owned_path import resolve_owned_path


Runner = Callable[[list[str]], dict[str, Any]]


def _run(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except FileNotFoundError as error:
        return {"returncode": 127, "stdout": "", "stderr": str(error)}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "CAPTURE_TIMEOUT"}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _raw_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(_canonical_bytes(payload))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def capture_locked_video(
    data_root: Path,
    trade_date: str,
    *,
    acceptance_path: Path,
    yt_dlp: list[str] | None,
    ffmpeg: str | None,
    funasr_script: Path | None,
    runner: Runner = _run,
) -> dict[str, Any]:
    trade_date = _date(trade_date)
    acceptance_bytes = acceptance_path.read_bytes()
    acceptance = json.loads(acceptance_bytes.decode("utf-8-sig"))
    if acceptance.get("trade_date") != trade_date:
        raise ValueError("Bilibili acceptance date mismatch")
    locked = acceptance.get("locked_videos")
    if acceptance.get("today_bv_status") != "TODAY_BV_LOCKED" or not isinstance(locked, list) or not locked:
        return {
            "schema_version": "v3_5.bilibili_capture_manifest.v1",
            "status": "NOT_MATERIALIZED",
            "trade_date": trade_date,
            "reason": "TODAY_BV_NOT_LOCKED",
            "source_acceptance_sha256": hashlib.sha256(acceptance_bytes).hexdigest(),
            "videos": [],
            "cookie_mode": "NO_COOKIES",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    if not yt_dlp or not ffmpeg or funasr_script is None or not funasr_script.is_file():
        missing = [
            name for name, ready in (
                ("YT_DLP", bool(yt_dlp)), ("FFMPEG", bool(ffmpeg)),
                ("FUNASR_SCRIPT", funasr_script is not None and funasr_script.is_file()),
            ) if not ready
        ]
        return {
            "schema_version": "v3_5.bilibili_capture_manifest.v1",
            "status": "TOOL_BLOCKED",
            "trade_date": trade_date,
            "reason": "MISSING_" + "_".join(missing),
            "source_acceptance_sha256": hashlib.sha256(acceptance_bytes).hexdigest(),
            "videos": [],
            "cookie_mode": "NO_COOKIES",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    base = f"close_review_sources/{trade_date}/bilibili"
    media_dir = resolve_owned_path(data_root, f"{base}/media")
    audio_dir = resolve_owned_path(data_root, f"{base}/audio")
    transcript_dir = resolve_owned_path(data_root, f"{base}/transcript")
    for path in (media_dir, audio_dir, transcript_dir):
        path.mkdir(parents=True, exist_ok=True)
    videos: list[dict[str, Any]] = []
    for source in locked:
        bv_id = str(source.get("bv_id") or "")
        if not bv_id.startswith("BV") or not bv_id.isalnum():
            raise ValueError("invalid locked BV identity")
        output_template = str(media_dir / f"{bv_id}.%(ext)s")
        capture = runner([
            *yt_dlp, "--no-playlist", "--windows-filenames", "-f", "bestaudio/best",
            "-o", output_template, str(source.get("source_url") or f"https://www.bilibili.com/video/{bv_id}/"),
        ])
        media_files = sorted(media_dir.glob(f"{bv_id}.*"))
        if int(capture.get("returncode") or 0) != 0 or not media_files:
            videos.append({"bv_id": bv_id, "status": "TOOL_BLOCKED", "reason": "PUBLIC_MEDIA_CAPTURE_FAILED"})
            continue
        audio = audio_dir / f"{bv_id}.16k.wav"
        extract = runner([ffmpeg, "-y", "-i", str(media_files[0]), "-ar", "16000", "-ac", "1", str(audio)])
        if int(extract.get("returncode") or 0) != 0 or not audio.is_file():
            videos.append({"bv_id": bv_id, "status": "TOOL_BLOCKED", "reason": "FFMPEG_AUDIO_EXTRACT_FAILED", "media_sha256": _raw_sha(media_files[0])})
            continue
        asr = runner([sys.executable, str(funasr_script), "--out-dir", str(transcript_dir), str(audio)])
        transcripts = sorted(transcript_dir.glob(f"{bv_id}*"))
        asr_ready = int(asr.get("returncode") or 0) == 0 and any(path.is_file() for path in transcripts)
        videos.append({
            "bv_id": bv_id,
            "status": "ASR_REVIEW_REQUIRED" if asr_ready else "TOOL_BLOCKED",
            "reason": "ASR_STOCKDICT_NOT_RUN" if asr_ready else "FUNASR_OUTPUT_NOT_READY",
            "media_sha256": _raw_sha(media_files[0]),
            "audio_sha256": _raw_sha(audio),
            "transcript_files": [path.name for path in transcripts if path.is_file()],
        })
    overall = "ASR_REVIEW_REQUIRED" if videos and all(row["status"] == "ASR_REVIEW_REQUIRED" for row in videos) else "TOOL_BLOCKED"
    return {
        "schema_version": "v3_5.bilibili_capture_manifest.v1",
        "status": overall,
        "trade_date": trade_date,
        "source_acceptance_sha256": hashlib.sha256(acceptance_bytes).hexdigest(),
        "videos": videos,
        "cookie_mode": "NO_COOKIES",
        "asr_engine": "LOCAL_FUNASR",
        "cannot_confirm": ["ASR_STOCKDICT_NOT_RUN"] if overall == "ASR_REVIEW_REQUIRED" else ["VIDEO_CAPTURE_OR_ASR_INCOMPLETE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture an exact-date locked public Bilibili fupan video")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--yt-dlp")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--funasr-script", type=Path)
    args = parser.parse_args()
    yt_dlp = [args.yt_dlp] if args.yt_dlp else [sys.executable, "-m", "yt_dlp"]
    manifest = capture_locked_video(
        args.data_root,
        args.date,
        acceptance_path=args.acceptance,
        yt_dlp=yt_dlp,
        ffmpeg=args.ffmpeg,
        funasr_script=args.funasr_script,
    )
    destination = resolve_owned_path(
        args.data_root, f"close_review_sources/{args.date}/bilibili/capture_manifest.json"
    )
    _write(destination, manifest)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
