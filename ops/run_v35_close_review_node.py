"""Close-review node receipt runner canary (V3.5).

A bounded per-node executor that runs exactly one of several review choices
and publishes an evidence receipt under
``runtime_graph/evidence/node_action_status/``.  It never accepts arbitrary
command strings; ``FUPAN_8771_VERIFY`` only reaches the 8873 loopback API
through ``urllib``.  Production video nodes consume the exact-date Review
Core VideoEvidenceV1 projection; old V3.5 producers remain reachable only
from isolated temporary unit fixtures.

Receipts are terminal (``SUCCESS`` / ``ACTION_RAN_WITH_CANNOT_CONFIRM`` /
``FAIL``).  A stored ``SUCCESS`` receipt is reused as-is only while every
local path it declares in ``artifacts`` still exists; a
``ACTION_RAN_WITH_CANNOT_CONFIRM`` receipt is never reused (same-day
video/ASR/OCR inputs may arrive later), so the next run re-checks and
overwrites the receipt atomically.  ``FAIL`` is likewise re-run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from infrastructure.owned_path import resolve_owned_path
from infrastructure.isolated_package_loader import load_isolated_package_module
from ops.build_bilibili_stockdict import build_stockdict
from ops.build_video_gap_audit import materialize_gap_audit
from ops.build_video_ocr_alignment import materialize_alignment
from ops.capture_bilibili_fupan import _write as _capture_write
from ops.capture_bilibili_fupan import capture_locked_video
from ops.check_bilibili_fupan import discover_bilibili_fupan, write_discovery
from ops.daily_materialize import resolve_selector_panel

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))


RECEIPT_SCHEMA = "v3_5_close_review_node_receipt.v1"
DEFAULT_LOOPBACK_BASE = "http://127.0.0.1:8873"
HTTP_TIMEOUT_SECONDS = 10.0
MAX_ERROR_DETAIL = 240
DATE_PATTERN = re.compile(r"^\d{8}$")
REUSABLE_STATUSES = {"SUCCESS"}
EXIT_OK_STATUSES = {"SUCCESS", "ACTION_RAN_WITH_CANNOT_CONFIRM"}
_DEFAULT_V35_DATA_ROOT = Path(__file__).resolve().parents[3] / ".runtime" / "data"
_SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_REVIEW_CORE_PACKAGE_ENV_NAMES = ("REVIEW_CORE_PACKAGE_ROOT", "V35_REVIEW_CORE_PACKAGE_ROOT")
_REVIEW_CORE_DATA_ENV_NAMES = ("REVIEW_CORE_DATA_ROOT", "V35_REVIEW_CORE_RUNTIME_ROOT")

NODES = (
    "bilibili_fupan_nightly",
    "FUPAN_V3_PUBLISH",
    "FUPAN_8771_VERIFY",
    "FUPAN_VIDEO_CHECK",
    "FUPAN_VIDEO_DOWNLOAD_ASR",
    "FUPAN_STOCKDICT",
    "FUPAN_VIDEO_TABLE_OCR_ALIGN",
    "FUPAN_VIDEO_GAP",
)


class HttpVerifyFailed(RuntimeError):
    """Raised when a loopback HTTP probe cannot be completed."""


def _required_review_core_binding(names: tuple[str, ...], label: str) -> str:
    """Return one explicit binding and reject missing or conflicting aliases."""
    from ops._run_v35_close_review_node_parts.source_binding import __required_review_core_binding_body as _v4_impl
    return _v4_impl(globals(), names, label)


def _review_core_package_parent() -> Path:
    from ops._run_v35_close_review_node_parts.source_binding import __review_core_package_parent_body as _v4_impl
    return _v4_impl(globals())


def _review_core_data_root() -> Path:
    configured = _required_review_core_binding(
        _REVIEW_CORE_DATA_ENV_NAMES, "Review Core data"
    )
    raw = Path(configured).expanduser()
    if not raw.is_absolute():
        raise RuntimeError("Review Core data binding must be an absolute path")
    return raw.resolve()


def _load_shared_video_layer(trade_date: str) -> dict[str, Any]:
    """Resolve one explicit Review Core projection without old-root discovery."""
    from ops._run_v35_close_review_node_parts.source_binding import __load_shared_video_layer_body as _v4_impl
    return _v4_impl(globals(), trade_date)


def _strict_shared_video_route(data_root: Path) -> bool:
    resolved = data_root.expanduser().resolve()
    if os.environ.get("REVIEW_CORE_DATA_ROOT") or os.environ.get("V35_REVIEW_EVIDENCE_STRICT") == "1":
        return True
    if resolved == _DEFAULT_V35_DATA_ROOT.resolve():
        return True
    return resolved.name.lower() == "data" and resolved.parent.name.lower() == ".runtime"


def _legacy_fixture_route(data_root: Path) -> bool:
    try:
        return data_root.expanduser().resolve().is_relative_to(
            Path(tempfile.gettempdir()).resolve()
        )
    except (OSError, ValueError):
        return False


def _should_use_shared_video_route(data_root: Path) -> bool:
    return _strict_shared_video_route(data_root) or not _legacy_fixture_route(data_root)


def _shared_video_result(
    *, data_root: Path, date: str, node: str
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.source_binding import __shared_video_result_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, node=node)


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def _validate_date(date: str) -> None:
    if not isinstance(date, str) or not DATE_PATTERN.fullmatch(date):
        raise ValueError(f"DATE_INVALID: {date!r}")


def _resolve_data_root(data_root: str | os.PathLike[str]) -> Path:
    return Path(data_root).expanduser().resolve()


def _receipt_path(data_root: Path, date: str, node: str) -> Path:
    return (
        data_root
        / "runtime_graph"
        / "evidence"
        / "node_action_status"
        / date
        / f"{node}.json"
    )


def _load_receipt(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _artifact_local_paths(artifacts: Any) -> list[str]:
    if not isinstance(artifacts, dict):
        return []
    paths: list[str] = []
    for value in artifacts.values():
        if not isinstance(value, str):
            continue
        if value.startswith(("http://", "https://")):
            continue
        paths.append(value)
    return paths


def _is_reusable(
    receipt: dict[str, Any] | None, *, node: str, date: str
) -> bool:
    from ops._run_v35_close_review_node_parts.receipt_io import __is_reusable_body as _v4_impl
    return _v4_impl(globals(), receipt, node=node, date=date)


def _atomic_write(path: Path, receipt: dict[str, Any]) -> None:
    from ops._run_v35_close_review_node_parts.receipt_io import __atomic_write_body as _v4_impl
    return _v4_impl(globals(), path, receipt)


def _exit_code(status: str) -> int:
    return 0 if status in EXIT_OK_STATUSES else 1


def _bilibili_nightly(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.node_cli import __bilibili_nightly_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _fupan_publish(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.fupan_publish import __fupan_publish_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _validate_loopback_url(url: str) -> bool:
    from ops._run_v35_close_review_node_parts.http_verification import __validate_loopback_url_body as _v4_impl
    return _v4_impl(globals(), url)


def _join_url(base_url: str, path: str) -> str:
    return urljoin(base_url, path)


def _http_get(url: str, timeout: float) -> int:
    with urlopen(url, timeout=timeout) as response:
        return int(response.status)


def _http_status(url: str, http_getter: Callable[..., int]) -> int:
    from ops._run_v35_close_review_node_parts.http_verification import __http_status_body as _v4_impl
    return _v4_impl(globals(), url, http_getter)


def _verify_fupan_8771(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int],
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.fupan_publish import __verify_fupan_8771_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _run_within_repo(command: list[str]) -> dict[str, Any]:
    """Run a fixed producer command with no shell and no user-controlled args."""
    from ops._run_v35_close_review_node_parts.node_cli import __run_within_repo_body as _v4_impl
    return _v4_impl(globals(), command)


def _default_discovery_runner() -> list[str]:
    return [sys.executable, "-m", "yt_dlp"]


def _resolve_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _resolve_funasr_script() -> Path | None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate = repo_root / "scripts" / "funasr" / "run_funasr.py"
    return candidate if candidate.is_file() else None


def _video_check(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.video_download import __video_check_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _video_download_asr(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.video_download import __video_download_asr_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _selector_pointer_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/selector_pointer.txt",
    )


def _stockdict_pointer_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/transcript_stockdict/current_asr_pointer.json",
    )


def _stockdict_mentions_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/transcript_stockdict/stock_mentions.json",
    )


def _alignment_pointer_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/video_ocr_alignment/alignment_pointer.json",
    )


def _video_gap_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/video_gap/video_gap_audit.json",
    )


def _video_session_path(data_root: Path, date: str) -> Path:
    return resolve_owned_path(
        data_root,
        f"close_review_sources/{date}/bilibili/video_session.json",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_alignment_inputs(data_root: Path, date: str) -> dict[str, Path]:
    """Derive machine-scoped alignment inputs from the current native ASR."""
    from ops._run_v35_close_review_node_parts.video_alignment import __prepare_alignment_inputs_body as _v4_impl
    return _v4_impl(globals(), data_root, date)


def _materialize_video_session(
    data_root: Path,
    date: str,
    gap: dict[str, Any],
) -> Path:
    from ops._run_v35_close_review_node_parts.video_session import __materialize_video_session_body as _v4_impl
    return _v4_impl(globals(), data_root, date, gap)


def _fupan_stockdict(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.stock_dictionary import __fupan_stockdict_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _fupan_video_table_ocr_align(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.video_alignment import __fupan_video_table_ocr_align_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _fupan_video_gap(
    *,
    data_root: Path,
    date: str,
    loopback_base_url: str,
    http_getter: Callable[..., int] | None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: Path | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    from ops._run_v35_close_review_node_parts.video_gap import __fupan_video_gap_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, date=date, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def _atomic_write_str(path: Path, value: str) -> None:
    from ops._run_v35_close_review_node_parts.receipt_io import __atomic_write_str_body as _v4_impl
    return _v4_impl(globals(), path, value)


_HANDLERS: dict[
    str, Callable[..., tuple[str, str, str, dict[str, Any]]]
] = {
    "bilibili_fupan_nightly": _bilibili_nightly,
    "FUPAN_V3_PUBLISH": _fupan_publish,
    "FUPAN_8771_VERIFY": _verify_fupan_8771,
    "FUPAN_VIDEO_CHECK": _video_check,
    "FUPAN_VIDEO_DOWNLOAD_ASR": _video_download_asr,
    "FUPAN_STOCKDICT": _fupan_stockdict,
    "FUPAN_VIDEO_TABLE_OCR_ALIGN": _fupan_video_table_ocr_align,
    "FUPAN_VIDEO_GAP": _fupan_video_gap,
}


def run_node(
    *,
    node: str,
    date: str,
    data_root: str | os.PathLike[str],
    loopback_base_url: str = DEFAULT_LOOPBACK_BASE,
    http_getter: Callable[..., int] | None = None,
    funasr_script: Path | None = None,
    ffmpeg: str | None = None,
    selector_data_root: str | os.PathLike[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run one close-review node and publish its receipt.

    Returns ``(exit_code, receipt)``.  ``http_getter`` is injected in tests;
    by default the loopback probes go through ``urllib.request.urlopen``.
    ``funasr_script``/``ffmpeg``/``selector_data_root`` are optional
    overrides for the video nodes; the CLI accepts them as plain Path/name
    flags, never command arrays.
    """
    from ops._run_v35_close_review_node_parts.node_cli import _run_node_body as _v4_impl
    return _v4_impl(globals(), node=node, date=date, data_root=data_root, loopback_base_url=loopback_base_url, http_getter=http_getter, funasr_script=funasr_script, ffmpeg=ffmpeg, selector_data_root=selector_data_root)


def main(argv: list[str] | None = None) -> int:
    from ops._run_v35_close_review_node_parts.node_cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
