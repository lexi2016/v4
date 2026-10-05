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

    configured = {
        name: str(os.environ.get(name) or "").strip()
        for name in names
        if str(os.environ.get(name) or "").strip()
    }
    if not configured:
        raise RuntimeError(f"{label} binding is missing")
    values = set(configured.values())
    if len(values) != 1:
        raise RuntimeError(f"{label} bindings disagree")
    return next(iter(values))


def _review_core_package_parent() -> Path:
    configured = _required_review_core_binding(
        _REVIEW_CORE_PACKAGE_ENV_NAMES, "Review Core package"
    )
    raw = Path(configured).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise RuntimeError("Review Core package binding must be an absolute regular path")
    package = raw if raw.name == "review_core" else raw / "review_core"
    if package.is_symlink() or not package.is_dir():
        raise RuntimeError(f"Review Core package directory is missing or linked: {package}")
    init = package / "__init__.py"
    if init.is_symlink() or not init.is_file():
        raise RuntimeError(f"Review Core package initializer is missing: {init}")
    return package.parent.resolve()


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

    package_root = _review_core_package_parent()
    data_root = _review_core_data_root()
    consumer = load_isolated_package_module(
        package_root,
        package_directory="review_core",
        module_leaf="consumer",
        namespace_prefix="v35_review_core_video",
    )
    loader = getattr(consumer, "load_v35_video_layer", None)
    if not callable(loader):
        raise RuntimeError("Review Core video consumer is unavailable")
    return dict(loader(trade_date, data_root))


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
    try:
        layer = _load_shared_video_layer(date)
    except Exception as error:  # fail-closed: do not consult old V3.5 folders
        layer = {
            "status": "CANNOT_CONFIRM",
            "target_trade_date": date,
            "cannot_confirm": [f"REVIEW_CORE_INVALID: {type(error).__name__}: {error}"],
            "safety_flags": {key: False for key in _SAFETY_FLAGS},
            "evidence_paths": {},
        }
    target = str(layer.get("target_trade_date") or date)
    flags = layer.get("safety_flags") if isinstance(layer.get("safety_flags"), dict) else {}
    safe = target == date and all(flags.get(key) is False for key in _SAFETY_FLAGS)
    artifacts = {
        str(key): str(value)
        for key, value in (layer.get("evidence_paths") or {}).items()
        if str(value or "")
    } if isinstance(layer.get("evidence_paths"), dict) else {}
    details = json.dumps(
        {
            "mode": "REVIEW_CORE_READ_ONLY",
            "node": node,
            "trade_date": date,
            "materialization_status": (
                "ALREADY_MATERIALIZED_READ_ONLY"
                if safe and str(layer.get("status") or "") not in {"CANNOT_CONFIRM", "NOT_MATERIALIZED"}
                else str(layer.get("status") or "CANNOT_CONFIRM")
            ),
            "review_core_status": str(layer.get("status") or "CANNOT_CONFIRM"),
            "layer": layer,
            "old_producer_calls": 0,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if safe and str(layer.get("status") or "") not in {"CANNOT_CONFIRM", "NOT_MATERIALIZED"}:
        return "SUCCESS", "ALREADY_MATERIALIZED_READ_ONLY", details, artifacts
    reason = str(layer.get("status") or "CANNOT_CONFIRM")
    return "ACTION_RAN_WITH_CANNOT_CONFIRM", reason, details, artifacts


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
    if receipt is None:
        return False
    if receipt.get("node_id") != node or receipt.get("date") != date:
        return False
    if receipt.get("status") not in REUSABLE_STATUSES:
        return False
    return all(
        Path(path).exists() for path in _artifact_local_paths(receipt.get("artifacts"))
    )


def _atomic_write(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(
            data_root=data_root,
            date=date,
            node="bilibili_fupan_nightly",
        )
    return _video_check(
        data_root=data_root,
        date=date,
        loopback_base_url=loopback_base_url,
        http_getter=http_getter,
        funasr_script=funasr_script,
        ffmpeg=ffmpeg,
        selector_data_root=selector_data_root,
    )


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
    payload_rel = f"a_share_reviews/{date}.json"
    receipt_rel = f"a_share_reviews/receipts/{date}.json"
    manifest_rel = "a_share_reviews/manifest.json"
    payload_path = resolve_owned_path(data_root, payload_rel)
    receipt_path = resolve_owned_path(data_root, receipt_rel)
    manifest_path = resolve_owned_path(data_root, manifest_rel)
    artifacts = {
        "payload": str(payload_path),
        "receipt": str(receipt_path),
        "manifest": str(manifest_path),
    }
    missing = [
        name
        for name, path in (
            ("payload", payload_path),
            ("receipt", receipt_path),
            ("manifest", manifest_path),
        )
        if not path.is_file()
    ]
    if missing:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_EVIDENCE_MISSING",
            "missing " + ", ".join(missing),
            artifacts,
        )
    try:
        with open(payload_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_UNREADABLE",
            f"{type(error).__name__}: {error}",
            artifacts,
        )
    try:
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_RECEIPT_UNREADABLE",
            f"{type(error).__name__}: {error}",
            artifacts,
        )
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_MANIFEST_UNREADABLE",
            f"{type(error).__name__}: {error}",
            artifacts,
        )
    if not isinstance(payload, dict) or payload.get("trade_date") != date:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_DATE_INVALID",
            "payload trade_date mismatch",
            artifacts,
        )
    if payload.get("source_role") != "V3_5_NATIVE_CLOSE_MODEL":
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_PAYLOAD_SOURCE_ROLE_INVALID",
            f"source_role {payload.get('source_role')!r}",
            artifacts,
        )
    if not isinstance(receipt, dict) or receipt.get("trade_date") != date:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_RECEIPT_DATE_INVALID",
            "receipt trade_date mismatch",
            artifacts,
        )
    if not isinstance(manifest, dict) or payload_rel not in manifest:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "REVIEW_MANIFEST_MISSING_PAYLOAD",
            "manifest lacks payload entry",
            artifacts,
        )
    return (
        "SUCCESS",
        "REVIEW_ARTIFACT_MATERIALIZED",
        "authoritative review evidence materialized",
        artifacts,
    )


def _validate_loopback_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return False
    try:
        if parsed.port != 8873:
            return False
    except ValueError:
        return False
    return True


def _join_url(base_url: str, path: str) -> str:
    return urljoin(base_url, path)


def _http_get(url: str, timeout: float) -> int:
    with urlopen(url, timeout=timeout) as response:
        return int(response.status)


def _http_status(url: str, http_getter: Callable[..., int]) -> int:
    try:
        return int(http_getter(url, HTTP_TIMEOUT_SECONDS))
    except HTTPError as error:
        try:
            return int(error.code)
        finally:
            error.close()
    except (OSError, URLError) as error:
        raise HttpVerifyFailed(
            f"{url}: {type(error).__name__}: {error}"
        ) from error


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
    if not _validate_loopback_url(loopback_base_url):
        return (
            "FAIL",
            "URL_REJECTED",
            "non-loopback or non-8873 or credential-bearing base URL",
            {},
        )
    probes = (
        (
            "review_endpoint",
            _join_url(loopback_base_url, f"/api/v3/review?date={date}"),
        ),
        ("root_endpoint", _join_url(loopback_base_url, "/")),
    )
    artifacts: dict[str, Any] = {}
    for name, url in probes:
        if not _validate_loopback_url(url):
            return ("FAIL", "URL_REJECTED", f"probe URL rejected: {url}", {})
        try:
            status = _http_status(url, http_getter)
        except HttpVerifyFailed as error:
            return ("FAIL", "HTTP_VERIFY_FAILED", f"{name}: {error}", {})
        if status != 200:
            return (
                "FAIL",
                "HTTP_VERIFY_FAILED",
                f"{name} returned HTTP {status}",
                {},
            )
        artifacts[name] = url
    return (
        "SUCCESS",
        "HTTP_200_CONFIRMED",
        "both loopback endpoints returned HTTP 200",
        artifacts,
    )


def _run_within_repo(command: list[str]) -> dict[str, Any]:
    """Run a fixed producer command with no shell and no user-controlled args."""
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
        return {"returncode": 124, "stdout": "", "stderr": "PRODUCER_TIMEOUT"}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(data_root=data_root, date=date, node="FUPAN_VIDEO_CHECK")
    discovery_runner = _default_discovery_runner()
    acceptance = discover_bilibili_fupan(
        date,
        yt_dlp=discovery_runner,
        runner=_run_within_repo,
    )
    write_discovery(data_root, acceptance)
    artifacts = {
        "acceptance": str(
            resolve_owned_path(
                data_root, f"close_review_sources/{date}/bilibili/acceptance.json"
            )
        ),
        "source_index": str(
            resolve_owned_path(
                data_root, f"close_review_sources/{date}/bilibili/source_index.json"
            )
        ),
        "manifest": str(
            resolve_owned_path(
                data_root, f"close_review_sources/{date}/bilibili/manifest.json"
            )
        ),
    }
    if (
        acceptance.get("today_bv_status") == "TODAY_BV_LOCKED"
        and isinstance(acceptance.get("locked_videos"), list)
        and acceptance["locked_videos"]
    ):
        return (
            "SUCCESS",
            "TODAY_BV_LOCKED",
            "same-day fupan video locked",
            artifacts,
        )
    reason = str(
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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_DOWNLOAD_ASR",
        )
    acceptance = data_root / "close_review_sources" / date / "bilibili" / "acceptance.json"
    locked = False
    if acceptance.is_file():
        try:
            payload = json.loads(acceptance.read_bytes().decode("utf-8-sig"))
            locked = (
                payload.get("trade_date") == date
                and payload.get("today_bv_status") == "TODAY_BV_LOCKED"
                and isinstance(payload.get("locked_videos"), list)
                and bool(payload["locked_videos"])
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            locked = False
    if not locked:
        refresh_status, refresh_reason, refresh_details, refresh_artifacts = _video_check(
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
        manifest = capture_locked_video(
            data_root,
            date,
            acceptance_path=acceptance,
            yt_dlp=[sys.executable, "-m", "yt_dlp"],
            ffmpeg=ffmpeg if ffmpeg is not None else _resolve_ffmpeg(),
            funasr_script=funasr_script if funasr_script is not None else _resolve_funasr_script(),
        )
    except Exception as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{type(error).__name__}: {error}",
            {},
        )
    manifest_path = resolve_owned_path(
        data_root, f"close_review_sources/{date}/bilibili/capture_manifest.json"
    )
    _capture_write(manifest_path, manifest)
    artifacts = {"capture_manifest": str(manifest_path)}
    status = str(manifest.get("status") or "")
    if status == "ASR_REVIEW_REQUIRED":
        videos = manifest.get("videos")
        if isinstance(videos, list) and any(
            isinstance(video, dict) and video.get("transcript_files")
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
            str(manifest.get("reason") or ""),
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        status or "CAPTURE_INCOMPLETE",
        "capture manifest materialized without transcripts",
        artifacts,
    )


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
    pointer_path = _stockdict_pointer_path(data_root, date)
    pointer = json.loads(pointer_path.read_bytes().decode("utf-8-sig"))
    if pointer.get("trade_date") != date:
        raise ValueError("current ASR pointer date mismatch")
    base = resolve_owned_path(data_root, f"close_review_sources/{date}/bilibili")
    transcript_dir = base / "transcript"
    inputs = base / "video_ocr_alignment" / "inputs"
    segments_path = inputs / "asr_segments.json"
    spotcheck_path = inputs / "spotcheck_rows.json"

    evidence_bv = {
        str(row.get("filename") or ""): str(row.get("bv_id") or "")
        for row in pointer.get("transcript_evidence") or []
        if isinstance(row, dict)
    }
    segments: list[dict[str, Any]] = []
    seen_segments: set[tuple[str, str, str, str, str]] = set()
    for path in sorted(transcript_dir.glob("*.funasr_segments.csv")):
        bv_id = evidence_bv.get(path.name) or path.name.split(".", 1)[0]
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for raw in csv.DictReader(source):
                row = {key: str(value or "") for key, value in raw.items()}
                row["bv_id"] = bv_id
                key = (
                    bv_id,
                    row.get("segment_index", ""),
                    row.get("start", ""),
                    row.get("end", ""),
                    row.get("text", ""),
                )
                if key not in seen_segments:
                    seen_segments.add(key)
                    segments.append(row)

    spotchecks: list[dict[str, Any]] = []
    seen_mentions: set[tuple[str, str, str]] = set()
    for mention in pointer.get("stock_mentions") or []:
        if not isinstance(mention, dict):
            continue
        bv_id = str(mention.get("bv_id") or "")
        stock_code = str(mention.get("stock_code") or "")
        stock_name = str(mention.get("stock_name") or "")
        key = (bv_id, stock_code, stock_name)
        if not stock_name or key in seen_mentions:
            continue
        seen_mentions.add(key)
        segment = next(
            (
                row for row in segments
                if row.get("bv_id") == bv_id and stock_name in row.get("text", "")
            ),
            {},
        )
        spotchecks.append({
            "bv_id": bv_id,
            "frame_time": str(segment.get("start") or mention.get("timestamp") or ""),
            "frame_path": "",
            "segment_index": str(segment.get("segment_index") or ""),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "asr_text": str(segment.get("text") or stock_name),
            "status": "ASR_STOCKDICT_OBSERVATION_READY",
        })
    if not spotchecks and segments:
        segment = segments[0]
        spotchecks.append({
            "bv_id": str(segment.get("bv_id") or ""),
            "frame_time": str(segment.get("start") or ""),
            "frame_path": "",
            "segment_index": str(segment.get("segment_index") or ""),
            "stock_code": "",
            "stock_name": "",
            "asr_text": str(segment.get("text") or ""),
            "status": "ASR_METHOD_OBSERVATION_READY",
        })
    if not segments_path.is_file():
        _capture_write(segments_path, {"trade_date": date, "rows": segments})
    if not spotcheck_path.is_file():
        _capture_write(spotcheck_path, {"trade_date": date, "rows": spotchecks})
    return {"asr_segments": segments_path, "spotcheck_rows": spotcheck_path}


def _materialize_video_session(
    data_root: Path,
    date: str,
    gap: dict[str, Any],
) -> Path:
    base = resolve_owned_path(data_root, f"close_review_sources/{date}/bilibili")
    acceptance_path = base / "acceptance.json"
    pointer_path = _stockdict_pointer_path(data_root, date)
    alignment_path = _alignment_pointer_path(data_root, date)
    gap_path = _video_gap_path(data_root, date)
    acceptance = json.loads(acceptance_path.read_bytes().decode("utf-8-sig"))
    locked = acceptance.get("locked_videos") or []
    if acceptance.get("trade_date") != date or not locked or not isinstance(locked[0], dict):
        raise ValueError("locked target video missing for video session")
    video = locked[0]
    segments_path = base / "video_ocr_alignment" / "inputs" / "asr_segments.json"
    segment_count = 0
    if segments_path.is_file():
        segment_payload = json.loads(segments_path.read_bytes().decode("utf-8-sig"))
        segment_count = len(segment_payload.get("rows") or [])
    targeted = int(gap.get("targeted_spotcheck_count") or 0)
    session = {
        "schema_version": "v3_5.video_session.v1",
        "status": "VIDEO_SESSION_READY",
        "target_trade_date": date,
        "bv_id": str(video.get("bv_id") or ""),
        "title": str(video.get("title") or ""),
        "upload_date": str(video.get("upload_date") or ""),
        "date_scope": str(video.get("date_scope") or ""),
        "asr_status": (
            "ASR_SEGMENT_SPOTCHECK_REQUIRED"
            if targeted
            else "ASR_STOCKDICT_OBSERVATION_READY"
        ),
        "asr_segment_count": segment_count,
        "targeted_spotcheck_count": targeted,
        "source_sha256s": {
            "acceptance": _sha256_file(acceptance_path),
            "current_asr_pointer": _sha256_file(pointer_path),
            "alignment_pointer": _sha256_file(alignment_path),
            "video_gap_audit": _sha256_file(gap_path),
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
    destination = _video_session_path(data_root, date)
    _capture_write(destination, session)
    return destination


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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(
            data_root=data_root,
            date=date,
            node="FUPAN_STOCKDICT",
        )
    if selector_data_root is None:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "SELECTOR_DATA_ROOT_MISSING",
            "selector-data-root not provided",
            {},
        )
    capture_manifest = resolve_owned_path(
        data_root, f"close_review_sources/{date}/bilibili/capture_manifest.json"
    )
    pointer_path = _stockdict_pointer_path(data_root, date)
    selector_pointer = _selector_pointer_path(data_root, date)
    if not capture_manifest.is_file():
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "CAPTURE_MANIFEST_MISSING",
            "capture_manifest.json not found",
            {},
        )
    try:
        selector_panel = resolve_selector_panel(selector_data_root, date)
    except Exception as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "SELECTOR_PANEL_UNAVAILABLE",
            f"{type(error).__name__}: {error}",
            {},
        )
    selector_pointer.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_str(selector_pointer, str(selector_panel))
    try:
        pointer = build_stockdict(
            data_root,
            date,
            capture_manifest_path=capture_manifest,
            panel_pointer=selector_pointer,
        )
    except Exception as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{type(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "capture_manifest": str(capture_manifest),
        "selector_pointer": str(selector_pointer),
        "current_asr_pointer": str(pointer_path),
        "stock_mentions": str(_stockdict_mentions_path(data_root, date)),
    }
    if (
        pointer.get("status") == "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"
        and pointer_path.is_file()
    ):
        return (
            "SUCCESS",
            "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY",
            "current ASR stockdict pointer materialized",
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        str(pointer.get("status") or "NOT_MATERIALIZED"),
        str(pointer.get("reason") or ""),
        artifacts,
    )


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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_TABLE_OCR_ALIGN",
        )
    current_asr_pointer = _stockdict_pointer_path(data_root, date)
    alignment_pointer = _alignment_pointer_path(data_root, date)
    if not current_asr_pointer.is_file():
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "CURRENT_ASR_POINTER_MISSING",
            "current_asr_pointer.json not found",
            {},
        )
    inputs = resolve_owned_path(
        data_root, f"close_review_sources/{date}/bilibili/video_ocr_alignment/inputs"
    )
    names = (
        "spotcheck_rows",
        "asr_segments",
        "news_rows",
        "anchor_rows",
        "board_rows",
        "tdx_rows",
    )
    paths: dict[str, Path | None] = {}
    for name in names:
        candidate = inputs / f"{name}.json"
        paths[name] = candidate if candidate.is_file() else None
    if paths["spotcheck_rows"] is None or paths["asr_segments"] is None:
        try:
            generated = _prepare_alignment_inputs(data_root, date)
            paths["spotcheck_rows"] = paths["spotcheck_rows"] or generated["spotcheck_rows"]
            paths["asr_segments"] = paths["asr_segments"] or generated["asr_segments"]
        except Exception as error:
            return (
                "FAIL",
                "HANDLER_ERROR",
                f"{type(error).__name__}: {error}",
                {},
            )
    try:
        result = materialize_alignment(
            data_root,
            date,
            current_asr_pointer_path=current_asr_pointer,
            spotcheck_path=paths["spotcheck_rows"],
            asr_segments_path=paths["asr_segments"],
            news_path=paths["news_rows"],
            anchors_path=paths["anchor_rows"],
            boards_path=paths["board_rows"],
            tdx_path=paths["tdx_rows"],
        )
    except Exception as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{type(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "current_asr_pointer": str(current_asr_pointer),
        "alignment_pointer": str(alignment_pointer),
    }
    if (
        result.get("status") == "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY"
        and alignment_pointer.is_file()
    ):
        return (
            "SUCCESS",
            "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY",
            "video OCR alignment pointer materialized",
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        str(result.get("status") or "NOT_MATERIALIZED"),
        str(result.get("reason") or ""),
        artifacts,
    )


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
    if _should_use_shared_video_route(data_root):
        return _shared_video_result(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_GAP",
        )
    current_asr_pointer = _stockdict_pointer_path(data_root, date)
    alignment_pointer = _alignment_pointer_path(data_root, date)
    review_path = resolve_owned_path(data_root, f"a_share_reviews/{date}.json")
    gap_path = _video_gap_path(data_root, date)
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
        result = materialize_gap_audit(
            data_root,
            date,
            current_asr_pointer_path=current_asr_pointer,
            alignment_pointer_path=alignment_pointer,
            review_path=review_path,
        )
    except Exception as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{type(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "current_asr_pointer": str(current_asr_pointer),
        "alignment_pointer": str(alignment_pointer),
        "review": str(review_path),
        "video_gap_audit": str(gap_path),
    }
    status = str(result.get("status") or "")
    if status == "VIDEO_GAP_AUDIT_READY" and gap_path.is_file():
        try:
            video_session = _materialize_video_session(data_root, date, result)
        except Exception as error:
            return (
                "FAIL",
                "HANDLER_ERROR",
                f"{type(error).__name__}: {error}",
                artifacts,
            )
        artifacts["video_session"] = str(video_session)
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
            str(result.get("reason") or ""),
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        status or "GAP_AUDIT_INCOMPLETE",
        str(result.get("reason") or ""),
        artifacts,
    )


def _atomic_write_str(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(value.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    resolved = _resolve_data_root(data_root)
    _validate_date(date)
    if node not in _HANDLERS:
        raise ValueError(f"NODE_UNKNOWN: {node!r}")
    receipt_path = _receipt_path(resolved, date, node)
    existing = _load_receipt(receipt_path)
    if _is_reusable(existing, node=node, date=date):
        return _exit_code(existing["status"]), existing
    getter = http_getter or _http_get
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        status, reason, details, artifacts = _HANDLERS[node](
            data_root=resolved,
            date=date,
            loopback_base_url=loopback_base_url,
            http_getter=getter,
            funasr_script=funasr_script,
            ffmpeg=ffmpeg,
            selector_data_root=(
                _resolve_data_root(selector_data_root)
                if selector_data_root is not None
                else None
            ),
        )
    except Exception as error:
        status = "FAIL"
        reason = "HANDLER_ERROR"
        details = f"{type(error).__name__}: {error}"[:MAX_ERROR_DETAIL]
        artifacts = {}
    completed_at = datetime.now(UTC).isoformat(timespec="seconds")
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "node_id": node,
        "date": date,
        # ``date`` is retained for the runner's compatibility contract.  The
        # frozen runtime graph reads explicit business/trade date fields from
        # receipts, so publish both aliases with the same target trading date.
        "business_date": date,
        "trade_date": date,
        "status": status,
        "reason": reason,
        "started_at": started_at,
        "completed_at": completed_at,
        "artifacts": artifacts,
        "details": details,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _atomic_write(receipt_path, receipt)
    return _exit_code(status), receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one V3.5 close-review node and publish its receipt"
    )
    parser.add_argument("--node", required=True, choices=list(NODES))
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--loopback-base-url", default=DEFAULT_LOOPBACK_BASE)
    parser.add_argument("--funasr-script", type=Path)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--selector-data-root", type=Path)
    args = parser.parse_args(argv)
    try:
        code, receipt = run_node(
            node=args.node,
            date=args.date,
            data_root=args.data_root,
            loopback_base_url=args.loopback_base_url,
            funasr_script=args.funasr_script,
            ffmpeg=args.ffmpeg,
            selector_data_root=args.selector_data_root,
        )
    except ValueError as error:
        _emit(
            {
                "schema_version": RECEIPT_SCHEMA,
                "status": "FAIL",
                "reason": f"{type(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 1
    _emit(receipt)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
