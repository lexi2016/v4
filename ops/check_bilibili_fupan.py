"""Public NO_COOKIES Bilibili metadata check for one exact review date."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from domains.bilibili_fupan import build_video_acceptance
from infrastructure.data_store import _canonical_bytes, _sha256
from infrastructure.owned_path import resolve_owned_path


DEFAULT_UP_URL = "https://space.bilibili.com/3546557003598528/video"
Runner = Callable[[list[str]], dict[str, Any]]


def _run(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except FileNotFoundError as error:
        return {"returncode": 127, "stdout": "", "stderr": str(error)}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "YT_DLP_TIMEOUT"}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def discover_bilibili_fupan(
    trade_date: str,
    *,
    yt_dlp: str | list[str] | None,
    up_url: str = DEFAULT_UP_URL,
    max_candidates: int = 8,
    runner: Runner = _run,
) -> dict[str, Any]:
    if not yt_dlp:
        return build_video_acceptance(
            trade_date, [], lookup_status="TOOL_BLOCKED", lookup_reason="YT_DLP_NOT_DISCOVERED"
        )
    prefix = [yt_dlp] if isinstance(yt_dlp, str) else list(yt_dlp)
    shortlist = runner([
        *prefix, "--flat-playlist", "--playlist-end", str(max_candidates),
        "--print", "%(id)s", up_url,
    ])
    if int(shortlist.get("returncode") or 0) != 0:
        return build_video_acceptance(
            trade_date,
            [],
            lookup_status="LOOKUP_BLOCKED",
            lookup_reason="UP_LOOKUP_BLOCKED:" + str(shortlist.get("stderr") or "")[:240],
        )
    bv_ids: list[str] = []
    for line in str(shortlist.get("stdout") or "").splitlines():
        match = re.search(r"BV[0-9A-Za-z]+", line)
        if match and match.group(0) not in bv_ids:
            bv_ids.append(match.group(0))
    if not bv_ids:
        return build_video_acceptance(
            trade_date,
            [],
            lookup_status="LOOKUP_BLOCKED",
            lookup_reason="UP_SHORTLIST_EMPTY",
        )
    candidates: list[dict[str, Any]] = []
    metadata_errors: list[str] = []
    for bv_id in bv_ids[:max_candidates]:
        metadata = runner([
            *prefix, "--dump-single-json", "--skip-download", "--no-playlist",
            f"https://www.bilibili.com/video/{bv_id}/",
        ])
        if int(metadata.get("returncode") or 0) != 0:
            metadata_errors.append(f"{bv_id}:METADATA_INCOMPLETE")
            continue
        try:
            payload = json.loads(str(metadata.get("stdout") or ""))
        except json.JSONDecodeError:
            metadata_errors.append(f"{bv_id}:METADATA_INCOMPLETE")
            continue
        candidates.append({
            "bv_id": bv_id,
            "title": payload.get("title"),
            "upload_date": payload.get("upload_date"),
            "duration": payload.get("duration"),
            "uploader": payload.get("uploader"),
        })
    acceptance = build_video_acceptance(trade_date, candidates)
    acceptance["cannot_confirm"].extend(metadata_errors)
    return acceptance


def _write_owned(root: Path, relative: str, value: Any) -> None:
    destination = resolve_owned_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(_canonical_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_discovery(data_root: Path, acceptance: dict[str, Any]) -> dict[str, Any]:
    trade_date = acceptance["trade_date"]
    base = f"close_review_sources/{trade_date}/bilibili"
    source_relative = f"{base}/source_index.json"
    acceptance_relative = f"{base}/acceptance.json"
    source = {
        "schema_version": "v3_5.bilibili_fupan_source_index.v1",
        "trade_date": trade_date,
        "rows": acceptance["source_index"],
    }
    manifest = {
        "schema_version": "v3_5.bilibili_fupan_manifest.v1",
        "trade_date": trade_date,
        "files": {
            source_relative: _sha256(source),
            acceptance_relative: _sha256(acceptance),
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write_owned(data_root, source_relative, source)
    _write_owned(data_root, acceptance_relative, acceptance)
    _write_owned(data_root, f"{base}/manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Check exact-date public Bilibili fupan metadata")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--up-url", default=DEFAULT_UP_URL)
    parser.add_argument("--yt-dlp")
    parser.add_argument("--max-candidates", default=8, type=int)
    args = parser.parse_args()
    command = [args.yt_dlp] if args.yt_dlp else (
        [shutil.which("yt-dlp")] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
    )
    acceptance = discover_bilibili_fupan(
        args.date,
        yt_dlp=command,
        up_url=args.up_url,
        max_candidates=args.max_candidates,
    )
    manifest = write_discovery(args.data_root, acceptance)
    print(json.dumps({
        "status": acceptance["status"],
        "trade_date": acceptance["trade_date"],
        "today_bv_status": acceptance["today_bv_status"],
        "source_index_rows": acceptance["checks"]["source_index_rows"],
        "same_day_video_count": acceptance["checks"]["same_day_video_count"],
        "manifest_sha256": _sha256(manifest),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
