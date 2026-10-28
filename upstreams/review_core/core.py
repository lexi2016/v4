from __future__ import annotations

import csv
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "VideoEvidenceV1"
CURRENT_SCHEMA_VERSION = "ReviewCoreCurrentV1"
RECEIPT_SCHEMA_VERSION = "ReviewCoreReceiptV1"
CAPTURE_SCHEMA_VERSION = "ReviewCoreCaptureManifestV1"
ASR_POINTER_SCHEMA_VERSION = "ReviewCoreCurrentAsrPointerV1"
GAP_SCHEMA_VERSION = "ReviewCoreVideoGapAuditV1"
ALLOWED_DATE_SCOPES = {
    "SAME_DAY_FUPAN",
    "TARGET_SESSION_FUPAN_PUBLISHED_LATE",
    "DAILY_VIDEO_NOT_LOCKED",
}
SAFETY_FLAG_NAMES = ("production_allowed", "buy_gate_updated", "orders_sent")

DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / ".runtime"
DEFAULT_SOURCE_ROOT = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug"
)
V3_PRODUCER_RELATIVE = Path(
    "30_runtime/timeline_scheduler/bilibili_fupan_update_watch.py"
)

# These are intentionally copied from the current V3 producer's title oracle.
RELEVANT_TITLE_HINTS = (
    "复盘",
    "A股",
    "股",
    "指数",
    "主线",
    "题材",
    "涨停",
    "趋势",
    "明天",
    "操盘",
    "高位",
    "低位",
    "机构",
    "兑现",
    "行情",
    "思路",
    "持续性",
    "预期",
    "分歧",
    "空仓",
    "跑路",
    "强势",
    "高潮",
    "反包",
    "锚定",
    "业绩",
)
NEGATIVE_TITLE_HINTS = ("回测系统", "止盈止损", "课程", "教程", "python", "代码")


class EvidenceValidationError(ValueError):
    """Raised when an exact-date evidence bundle is not safe to read."""


class ImmutableRunError(EvidenceValidationError):
    """Raised when a deterministic run path already contains another bundle."""


def _as_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return Path(value)


def normalize_trade_date(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 8:
        raise ValueError(f"invalid trade date: {value!r}")
    datetime.strptime(digits, "%Y%m%d")
    return digits


def _upload_date8(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _previous_weekday(date8: str) -> str:
    current = datetime.strptime(date8, "%Y%m%d").date() - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current.strftime("%Y%m%d")


def _date_label_variants(date8: str) -> set[str]:
    parsed = datetime.strptime(date8, "%Y%m%d")
    return {
        f"{parsed.month}.{parsed.day}",
        f"{parsed.month}月{parsed.day}",
        f"{parsed.month}月{parsed.day}日",
        f"{parsed.month}-{parsed.day}",
    }


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _is_fupan_title(title: str) -> bool:
    text = str(title or "")
    return any(hint in text for hint in RELEVANT_TITLE_HINTS) and not any(
        hint in text for hint in NEGATIVE_TITLE_HINTS
    )


def _is_weekend_late_target_session(upload_date: str, trade_date: str) -> bool:
    normalized_upload = _upload_date8(upload_date)
    if not normalized_upload:
        return False
    upload_day = datetime.strptime(normalized_upload, "%Y%m%d").date()
    target_day = datetime.strptime(trade_date, "%Y%m%d").date()
    return (
        upload_day.weekday() >= 5
        and target_day.weekday() == 4
        and _previous_weekday(normalized_upload) == trade_date
        and 1 <= (upload_day - target_day).days <= 2
    )


def classify_date_scope(title: str, upload_date: str, trade_date: str) -> str:
    """Apply the V3 title/date oracle, with a fail-closed no-lock result."""

    target = normalize_trade_date(trade_date)
    text = _compact_text(title)
    normalized_upload = _upload_date8(upload_date)
    if any(hint in text for hint in NEGATIVE_TITLE_HINTS):
        return "DAILY_VIDEO_NOT_LOCKED"
    if not _is_fupan_title(text):
        if normalized_upload == target and any(
            label in text for label in _date_label_variants(target)
        ):
            return "SAME_DAY_FUPAN"
        return "DAILY_VIDEO_NOT_LOCKED"
    if normalized_upload == target or any(
        label in text for label in _date_label_variants(target)
    ):
        return "SAME_DAY_FUPAN"
    if _is_weekend_late_target_session(normalized_upload, target):
        return "TARGET_SESSION_FUPAN_PUBLISHED_LATE"
    return "DAILY_VIDEO_NOT_LOCKED"


def _rank_value(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("candidate_rank") or "999999"))
    except (TypeError, ValueError):
        return 999999


def select_target_video(
    candidates: Iterable[dict[str, Any]],
    trade_date: str,
    *,
    target_mid: str | None = None,
    target_uploader: str | None = None,
) -> dict[str, Any]:
    """Select only an exact-day or explicit weekend-late target video.

    The legacy V3 producer has compatibility scopes for prior/latest videos.
    The standalone contract deliberately does not substitute either scope for
    a missing target-day video.
    """

    target = normalize_trade_date(trade_date)
    matched: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        bv_id = str(row.get("bv_id") or row.get("bvid") or "").strip()
        title = str(row.get("title") or "")
        upload_date = _upload_date8(row.get("upload_date") or row.get("pubdate"))
        explicit_target = row.get("target_trade_date") or row.get("trade_date")
        if explicit_target:
            try:
                if normalize_trade_date(str(explicit_target)) != target:
                    continue
            except ValueError:
                continue
        if target_mid:
            candidate_mid = str(row.get("target_mid") or row.get("uploader_mid") or row.get("author_mid") or row.get("owner_mid") or row.get("mid") or "").strip()
            if candidate_mid and candidate_mid != target_mid:
                continue
        if target_uploader:
            candidate_uploader = str(row.get("uploader") or row.get("author") or "").strip()
            if candidate_uploader and candidate_uploader != target_uploader:
                continue
        if not bv_id or str(row.get("metadata_status") or "METADATA_READY") == "METADATA_INCOMPLETE":
            continue
        scope = classify_date_scope(title, upload_date, target)
        if scope not in {"SAME_DAY_FUPAN", "TARGET_SESSION_FUPAN_PUBLISHED_LATE"}:
            continue
        row["bv_id"] = bv_id
        row["title"] = title
        row["upload_date"] = upload_date
        row["date_scope"] = scope
        matched.append(row)
    matched.sort(
        key=lambda row: (
            0 if row["date_scope"] == "SAME_DAY_FUPAN" else 1,
            _rank_value(row),
            row["bv_id"],
        )
    )
    if matched:
        selected = matched[0]
        return {
            **selected,
            "target_trade_date": target,
            "discovery_status": "TARGET_BV_LOCKED",
        }
    return {
        "bv_id": "",
        "title": "",
        "upload_date": "",
        "date_scope": "DAILY_VIDEO_NOT_LOCKED",
        "target_trade_date": target,
        "discovery_status": "DAILY_VIDEO_NOT_LOCKED",
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"cannot read JSON artifact: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceValidationError(f"JSON artifact is not an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise EvidenceValidationError(f"cannot read CSV artifact: {path}: {exc}") from exc


def _atomic_write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        actual = sha256_file(path)
        expected = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise EvidenceValidationError(f"atomic write SHA mismatch: {path}")
        return actual
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _atomic_write_bytes(path, encoded.encode("utf-8"))


def _copy_checked(source: Path, destination: Path) -> tuple[str, str]:
    if not source.is_file():
        raise EvidenceValidationError(f"source artifact missing: {source}")
    source_sha = sha256_file(source)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != source_sha:
            raise ImmutableRunError(f"refusing to overwrite immutable artifact: {destination}")
        return source_sha, "REUSE_EXISTING"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_handle:
            shutil.copyfileobj(input_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        if sha256_file(destination) != source_sha:
            raise EvidenceValidationError(f"copied artifact SHA mismatch: {destination}")
        return source_sha, "IMPORT_COPY"
    finally:
        if temporary.exists():
            temporary.unlink()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise EvidenceValidationError(f"artifact path escapes data root: {path}") from exc


def _safe_relative_path(value: Any) -> str:
    text = str(value or "")
    candidate = Path(text)
    if not text or candidate.is_absolute() or ".." in candidate.parts:
        raise EvidenceValidationError(f"unsafe artifact reference: {text!r}")
    return candidate.as_posix()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _source_path(value: Any, package: Path | None = None) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    direct = Path(value)
    if direct.is_file():
        return direct.resolve()
    if package is not None and not direct.is_absolute():
        relative = (package / direct).resolve()
        if relative.is_file():
            return relative
    return None


def _source_hash_entry(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256_file(path)}


def _implementation_source_hashes() -> dict[str, dict[str, str]]:
    package_root = Path(__file__).resolve().parent
    paths = (
        package_root / "core.py",
        package_root / "cli.py",
        package_root / "__init__.py",
        package_root / "__main__.py",
        package_root / "config.py",
        package_root / "producer.py",
        package_root / "scheduler.py",
        package_root / "scheduler_entry.py",
    )
    return {
        path.name: _source_hash_entry(path)
        for path in paths
        if path.is_file()
    }


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _locate_source_index(
    source_root: Path,
    trade_date: str,
    source_index_path: Path | None,
) -> Path | None:
    if source_index_path is not None:
        return source_index_path if source_index_path.is_file() else None
    candidates = [
        source_root / f"{trade_date}_bilibili_fupan_update_watch" / f"source_up_video_index_{trade_date}.csv",
        source_root / f"source_up_video_index_{trade_date}.csv",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _locate_package(
    source_root: Path,
    trade_date: str,
    selection: dict[str, Any],
    source_package_root: Path | None,
) -> Path | None:
    bv_id = str(selection.get("bv_id") or "")
    if not bv_id:
        return None
    row_package = selection.get("package")
    if isinstance(row_package, str) and Path(row_package).is_dir():
        return Path(row_package).resolve()
    bases = [
        source_package_root,
        source_root / "复盘skills" / "视频归档",
        source_root,
        source_root.parent / "复盘skills" / "视频归档",
    ]
    for base in bases:
        if base is None:
            continue
        for candidate in (
            base / f"{trade_date}_bilibili_capture_{bv_id}",
            base / f"bilibili_capture_{bv_id}",
        ):
            if candidate.is_dir():
                return candidate.resolve()
    return None


def _locate_optional_file(source_root: Path, package: Path | None, names: Iterable[Path]) -> Path | None:
    for name in names:
        if name.is_file():
            return name.resolve()
        if package is not None:
            candidate = (package / name).resolve()
            if candidate.is_file():
                return candidate
        candidate = (source_root / name).resolve()
        if candidate.is_file():
            return candidate
    return None


def _load_source_bundle(
    trade_date: str,
    source_root: Path,
    source_index_path: Path | None,
    source_package_root: Path | None,
) -> dict[str, Any]:
    index_path = _locate_source_index(source_root, trade_date, source_index_path)
    candidates = _read_csv(index_path) if index_path else []
    selection = select_target_video(candidates, trade_date)
    locked_video = bool(selection.get("bv_id"))
    source_hashes: dict[str, dict[str, str]] = {}
    source_hashes["review_core_implementation"] = _implementation_source_hashes()
    if index_path is not None:
        source_hashes["source_index"] = _source_hash_entry(index_path)
    producer_path = source_root.parent.parent / V3_PRODUCER_RELATIVE
    if producer_path.is_file():
        source_hashes["v3_producer"] = _source_hash_entry(producer_path)

    package = _locate_package(source_root, trade_date, selection, source_package_root)
    capture_path = (
        _locate_optional_file(
            source_root,
            package,
            [
                Path(f"capture_manifest_{trade_date}.json"),
                source_root
                / f"{trade_date}_bilibili_fupan_update_watch"
                / f"capture_manifest_{trade_date}.json",
            ],
        )
        if locked_video
        else None
    )
    capture = _read_json(capture_path) if capture_path else {}
    if capture_path:
        source_hashes["source_capture_manifest"] = _source_hash_entry(capture_path)

    watch_root = source_root / f"{trade_date}_bilibili_fupan_update_watch"
    gap_path = (
        _locate_optional_file(
            source_root,
            package,
            [
                watch_root / f"video_gap_matrix_{trade_date}.csv",
                Path(f"video_gap_matrix_{trade_date}.csv"),
                source_root
                / f"{trade_date}_fupan_page_complete"
                / f"video_gap_matrix_{trade_date}.csv",
            ],
        )
        if locked_video
        else None
    )
    gap_rows = _read_csv(gap_path) if gap_path else []
    if gap_path:
        source_hashes["source_gap_audit"] = _source_hash_entry(gap_path)

    acceptance_path = (
        _locate_optional_file(
            source_root,
            package,
            [watch_root / f"acceptance_{trade_date}.json", Path(f"acceptance_{trade_date}.json")],
        )
        if locked_video
        else None
    )
    acceptance = _read_json(acceptance_path) if acceptance_path else {}
    if acceptance_path:
        source_hashes["source_acceptance"] = _source_hash_entry(acceptance_path)

    pointer_path: Path | None = None
    pointer: dict[str, Any] = {}
    package_files: list[Path] = []
    if locked_video and package is not None:
        package_files = sorted(path.resolve() for path in package.rglob("*") if path.is_file())
        pointer_candidates = [
            package / "transcript_stockdict" / f"current_asr_pointer_{trade_date}.json",
            package / "transcript" / f"current_asr_pointer_{trade_date}.json",
        ]
        pointer_path = next((path.resolve() for path in pointer_candidates if path.is_file()), None)
        if pointer_path is None:
            pointer_path = next(
                (path for path in package_files if "current_asr_pointer" in path.name),
                None,
            )
    if pointer_path:
        pointer = _read_json(pointer_path)
        source_hashes["source_asr_pointer"] = _source_hash_entry(pointer_path)
    for path in package_files:
        try:
            relative = path.relative_to(package).as_posix() if package else path.name
        except ValueError:
            relative = path.name
        source_hashes[f"package/{relative}"] = _source_hash_entry(path)

    return {
        "source_root": source_root,
        "index_path": index_path,
        "candidates": candidates,
        "selection": selection,
        "package": package,
        "package_files": package_files,
        "capture_path": capture_path,
        "capture": capture,
        "gap_path": gap_path,
        "gap_rows": gap_rows,
        "acceptance_path": acceptance_path,
        "acceptance": acceptance,
        "pointer_path": pointer_path,
        "pointer": pointer,
        "source_hashes": source_hashes,
    }


def _kind_for_package_file(path: Path) -> str:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if "media" in parts:
        return "media"
    if name.endswith(".funasr_raw.txt"):
        return "transcript"
    if name.endswith(".funasr_segments.csv"):
        return "segment"
    if name.endswith(".funasr_tokens.csv"):
        return "asr_token"
    if "run_manifest" in name:
        return "asr_trace"
    if "current_asr_pointer" in name:
        return "asr_pointer_source"
    if "transcript_stockdict" in parts:
        return "asr_support"
    if "audio" in parts:
        return "audio"
    return "asr_support"


def _package_local_path(package: Path, source_path: Path) -> str:
    relative = source_path.relative_to(package)
    parts = relative.parts
    if parts and parts[0].lower() == "transcript":
        return (Path("asr") / "transcript" / Path(*parts[1:])).as_posix()
    if parts and parts[0].lower() == "transcript_stockdict":
        return (Path("asr") / "stockdict" / Path(*parts[1:])).as_posix()
    if parts and parts[0].lower() == "audio":
        return (Path("asr") / "audio" / Path(*parts[1:])).as_posix()
    return (Path("asr") / "imported" / Path(*parts)).as_posix()


def _selection_digest(trade_date: str, bundle: dict[str, Any]) -> str:
    selection = bundle["selection"]
    payload = {
        "contract": SCHEMA_VERSION,
        "trade_date": trade_date,
        "selection": {
            "bv_id": selection.get("bv_id", ""),
            "title": selection.get("title", ""),
            "upload_date": selection.get("upload_date", ""),
            "date_scope": selection.get("date_scope", "DAILY_VIDEO_NOT_LOCKED"),
        },
        "source_sha256": bundle["source_hashes"],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _run_id(trade_date: str, bundle: dict[str, Any], input_digest: str) -> str:
    bv_id = str(bundle["selection"].get("bv_id") or "none")
    return f"rcv1-{trade_date}-{bv_id}-{input_digest[:16]}"


def _register_ref(
    refs: list[dict[str, Any]],
    *,
    path: str,
    kind: str,
    sha256: str,
    size: int,
    source_path: Path | None = None,
    source_sha256: str | None = None,
    import_mode: str = "MATERIALIZED",
) -> dict[str, Any]:
    ref = {
        "kind": kind,
        "path": path,
        "sha256": sha256,
        "size": size,
        "import_mode": import_mode,
    }
    if source_path is not None:
        ref["source_path"] = str(source_path)
    if source_sha256 is not None:
        ref["original_source_sha256"] = source_sha256
    refs.append(ref)
    return ref


def _resolve_mapped_path(
    value: Any,
    *,
    package: Path | None,
    source_to_local: dict[str, str],
) -> str | None:
    source = _source_path(value, package)
    if source is None:
        return None
    return source_to_local.get(str(source.resolve()))


def _normalize_path_list(
    value: Any,
    *,
    package: Path | None,
    source_to_local: dict[str, str],
    missing: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        mapped = _resolve_mapped_path(item, package=package, source_to_local=source_to_local)
        if mapped:
            normalized.append(mapped)
        elif item:
            missing.append(f"unimported source reference: {item}")
    return _unique(normalized)


def _normalize_capture_manifest(
    bundle: dict[str, Any],
    *,
    trade_date: str,
    bv_id: str,
    run_rel: str,
    source_to_local: dict[str, str],
) -> dict[str, Any]:
    source = copy.deepcopy(bundle.get("capture") or {})
    missing: list[str] = []
    normalized: dict[str, Any] = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "trade_date": trade_date,
        "bv_id": bv_id,
        "status": str(source.get("status") or "SOURCE_CAPTURE_NOT_AVAILABLE"),
        "import_mode": "IMPORT_COPY" if source else "NO_SOURCE_CAPTURE",
        "source_path": str(bundle["capture_path"]) if bundle.get("capture_path") else "",
        "original_source_sha256": (
            bundle["source_hashes"].get("source_capture_manifest", {}).get("sha256", "")
        ),
        "archive_root": run_rel,
        "cannot_confirm": list(source.get("cannot_confirm") or []),
    }
    for key in (
        "media_files",
        "audio_files",
        "subtitle_files",
        "transcript_files",
        "segment_files",
        "token_files",
        "asr_run_manifests",
        "metadata_files",
    ):
        normalized[key] = _normalize_path_list(
            source.get(key), package=bundle.get("package"), source_to_local=source_to_local, missing=missing
        )
    for key in ("stock_alias_recovery_csv", "stock_mentions_recovered_csv"):
        mapped = _resolve_mapped_path(
            source.get(key), package=bundle.get("package"), source_to_local=source_to_local
        )
        normalized[key] = mapped or ""
        if source.get(key) and not mapped:
            missing.append(f"unimported source reference: {source[key]}")
    for key in ("asr_engine", "asr_status", "asr_spotcheck_status", "asr_spotcheck_reason"):
        if key in source:
            normalized[key] = source[key]
    normalized["cannot_confirm"] = _unique(
        [str(item) for item in normalized["cannot_confirm"]] + missing
    )
    return normalized


def _normalize_pointer(
    bundle: dict[str, Any],
    *,
    trade_date: str,
    bv_id: str,
    source_to_local: dict[str, str],
) -> dict[str, Any]:
    source = copy.deepcopy(bundle.get("pointer") or {})
    if source and (
        source.get("trade_date") != trade_date
        or source.get("bv") != bv_id
    ):
        raise EvidenceValidationError("ASR pointer exact date or BV mismatch")
    normalized = {
        key: value
        for key, value in source.items()
        if key not in {"raw_asr_path", "current_asr_md", "stock_mentions_csv", "segment_path", "trace_path"}
    }
    for key in ("raw_asr_path", "current_asr_md", "stock_mentions_csv", "segment_path", "trace_path"):
        if source.get(key):
            mapped = _resolve_mapped_path(
                source.get(key), package=bundle.get("package"), source_to_local=source_to_local
            )
            if mapped:
                normalized[key] = mapped
    normalized.update(
        {
            "schema_version": ASR_POINTER_SCHEMA_VERSION,
            "trade_date": trade_date,
            "bv": bv_id,
            "import_mode": "IMPORT_COPY" if source else "NO_SOURCE_POINTER",
            "source_path": str(bundle["pointer_path"]) if bundle.get("pointer_path") else "",
            "original_source_sha256": bundle["source_hashes"].get("source_asr_pointer", {}).get("sha256", ""),
        }
    )
    normalized["referenced_artifacts"] = _unique(
        value
        for key, value in normalized.items()
        if key.endswith("_path") or key in {"current_asr_md", "stock_mentions_csv", "segment_path", "trace_path"}
        if isinstance(value, str) and value.startswith(("review/", "media/"))
    )
    if not source:
        normalized["status"] = "NOT_AVAILABLE"
    return normalized


def _valid_imported_asr_pointer(
    pointer: dict[str, Any],
    capture: dict[str, Any],
    refs: list[dict[str, Any]],
    *,
    trade_date: str,
    bv_id: str,
) -> bool:
    if not bv_id:
        return False
    if pointer.get("trade_date") != trade_date or pointer.get("bv") != bv_id:
        return False
    if pointer.get("status") != "CURRENT_ASR_STOCKDICT_READY":
        return False
    ref_paths = {
        str(ref.get("path"))
        for ref in refs
        if isinstance(ref, dict) and ref.get("path")
    }
    referenced = [pointer.get("raw_asr_path")]
    referenced.extend(pointer.get("referenced_artifacts") or [])
    if not referenced:
        return False
    if any(not isinstance(path, str) or path not in ref_paths for path in referenced):
        return False
    for key in ("segment_files", "asr_run_manifests"):
        values = capture.get(key)
        if not isinstance(values, list) or not values:
            return False
        if any(not isinstance(path, str) or path not in ref_paths for path in values):
            return False
    return True


def _filter_false_missing_pointer_residue(
    values: Iterable[Any],
    *,
    valid_imported_pointer: bool,
) -> list[str]:
    messages = [str(value) for value in values if value]
    if not valid_imported_pointer:
        return _unique(messages)
    filtered: list[str] = []
    for message in messages:
        lowered = message.lower()
        is_missing_pointer_residue = (
            "current_asr_pointer" in message
            and ("缺少" in message or "missing" in lowered)
        )
        if not is_missing_pointer_residue:
            filtered.append(message)
    return _unique(filtered)


def _normalize_gap_audit(
    bundle: dict[str, Any],
    *,
    trade_date: str,
    bv_id: str,
    source_to_local: dict[str, str],
) -> dict[str, Any]:
    rows = copy.deepcopy(bundle.get("gap_rows") or [])
    package = bundle.get("package")
    for row in rows:
        for key in ("evidence_route", "evidence_path"):
            mapped = _resolve_mapped_path(row.get(key), package=package, source_to_local=source_to_local)
            if mapped:
                row[key] = mapped
    targeted = 0
    for row in rows:
        if str(row.get("gap_type") or "") in {"ASR_TARGETED_SPOTCHECK", "ASR_SEGMENT_SPOTCHECK_REQUIRED"}:
            targeted += 1
    status = "VIDEO_GAP_AUDIT_READY" if rows else "DAILY_VIDEO_NOT_LOCKED"
    return {
        "schema_version": GAP_SCHEMA_VERSION,
        "trade_date": trade_date,
        "bv_id": bv_id,
        "status": status,
        "gap_rows": rows,
        "gap_row_count": len(rows),
        "targeted_spotcheck_count": targeted,
        "source_path": str(bundle["gap_path"]) if bundle.get("gap_path") else "",
        "original_source_sha256": bundle["source_hashes"].get("source_gap_audit", {}).get("sha256", ""),
        "import_mode": "IMPORT_COPY" if bundle.get("gap_path") else "NO_SOURCE_GAP_AUDIT",
    }


def _segment_count(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return 0


def _spotcheck_count(bundle: dict[str, Any], gap_audit: dict[str, Any]) -> int:
    values: list[Any] = [gap_audit.get("targeted_spotcheck_count", 0)]
    capture = bundle.get("capture") or {}
    values.append(capture.get("targeted_spotcheck_count", 0))
    acceptance = bundle.get("acceptance") or {}
    for video in acceptance.get("videos") or []:
        if isinstance(video, dict):
            values.append(video.get("targeted_spotcheck_count", 0))
            quality = video.get("quality") or {}
            if isinstance(quality, dict):
                values.append(quality.get("targeted_spotcheck_count", 0))
    result = 0
    for value in values:
        try:
            result = max(result, int(value or 0))
        except (TypeError, ValueError):
            continue
    return result


def _write_registered_json(
    stage: Path,
    run_rel: str,
    name: str,
    payload: dict[str, Any],
    kind: str,
    refs: list[dict[str, Any]],
    source_path: Path | None = None,
) -> Path:
    path = stage / name
    digest = _atomic_write_json(path, payload)
    source_sha = sha256_file(source_path) if source_path and source_path.is_file() else None
    _register_ref(
        refs,
        path=f"{run_rel}/{Path(name).as_posix()}",
        kind=kind,
        sha256=digest,
        size=path.stat().st_size,
        source_path=source_path,
        source_sha256=source_sha,
    )
    return path


def _materialize(
    trade_date: str,
    data_root: Path,
    source_bundle: dict[str, Any],
    input_digest: str,
    run_id: str,
) -> dict[str, Any]:
    selection = source_bundle["selection"]
    bv_id = str(selection.get("bv_id") or "")
    review_date_root = data_root / "review" / trade_date
    runs_root = review_date_root / "runs"
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise ImmutableRunError(f"immutable run already exists without idempotent current: {run_dir}")
    stage = runs_root / f".{run_id}.staging"
    if stage.exists():
        raise ImmutableRunError(f"staging run already exists: {stage}")
    stage.mkdir(parents=True, exist_ok=False)
    run_rel = f"review/{trade_date}/runs/{run_id}"
    refs: list[dict[str, Any]] = []
    source_to_local: dict[str, str] = {}
    media_refs: list[dict[str, Any]] = []
    transcript_sources: list[Path] = []
    segment_source: Path | None = None

    package = source_bundle.get("package")
    for source_path in source_bundle.get("package_files") or []:
        kind = _kind_for_package_file(source_path)
        if kind == "media":
            destination_relative = Path("media") / bv_id / sha256_file(source_path) / source_path.name
            destination = data_root / destination_relative
            source_sha, import_mode = _copy_checked(source_path, destination)
            local_path = destination_relative.as_posix()
            source_to_local[str(source_path.resolve())] = local_path
            ref = _register_ref(
                refs,
                path=local_path,
                kind="media",
                sha256=source_sha,
                size=destination.stat().st_size,
                source_path=source_path,
                source_sha256=source_sha,
                import_mode="REUSE_CONTENT_ADDRESSED" if import_mode == "REUSE_EXISTING" else import_mode,
            )
            media_refs.append(ref)
            continue
        if package is None:
            continue
        local_under_run = _package_local_path(package, source_path)
        destination = stage / local_under_run
        source_sha, import_mode = _copy_checked(source_path, destination)
        local_path = f"{run_rel}/{local_under_run}"
        source_to_local[str(source_path.resolve())] = local_path
        _register_ref(
            refs,
            path=local_path,
            kind=kind,
            sha256=source_sha,
            size=destination.stat().st_size,
            source_path=source_path,
            source_sha256=source_sha,
            import_mode=import_mode,
        )
        if kind == "transcript":
            transcript_sources.append(source_path)
        if kind == "segment" and segment_source is None:
            segment_source = source_path

    source_index_payload = {
        "schema_version": "ReviewCoreSourceIndexV1",
        "trade_date": trade_date,
        "run_id": run_id,
        "selected_video": selection,
        "candidates": source_bundle.get("candidates") or [],
        "source_path": str(source_bundle["index_path"]) if source_bundle.get("index_path") else "",
        "source_sha256": source_bundle["source_hashes"].get("source_index", {}).get("sha256", ""),
        "network_used": False,
    }
    _write_registered_json(
        stage,
        run_rel,
        "source_index.json",
        source_index_payload,
        "source_index",
        refs,
        source_bundle.get("index_path"),
    )

    video_session = {
        "schema_version": "ReviewCoreVideoSessionV1",
        "trade_date": trade_date,
        "target_trade_date": trade_date,
        "run_id": run_id,
        "bv_id": bv_id,
        "title": str(selection.get("title") or ""),
        "upload_date": str(selection.get("upload_date") or ""),
        "date_scope": str(selection.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED"),
        "discovery_status": str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED"),
        "producer_identity": "v3.bilibili_fupan_update_watch",
        "network_used": False,
        "import_mode": "IMPORT_EXISTING_EVIDENCE" if bv_id else "NO_MATCH",
        "source_sha256": source_bundle.get("source_hashes") or {},
    }
    _write_registered_json(stage, run_rel, "video_session.json", video_session, "video_session", refs)

    capture_payload = _normalize_capture_manifest(
        source_bundle,
        trade_date=trade_date,
        bv_id=bv_id,
        run_rel=run_rel,
        source_to_local=source_to_local,
    )

    pointer_payload = _normalize_pointer(
        source_bundle,
        trade_date=trade_date,
        bv_id=bv_id,
        source_to_local=source_to_local,
    )
    _write_registered_json(
        stage,
        run_rel,
        "asr/current_asr_pointer.json",
        pointer_payload,
        "asr_pointer",
        refs,
        source_bundle.get("pointer_path"),
    )

    gap_payload = _normalize_gap_audit(
        source_bundle,
        trade_date=trade_date,
        bv_id=bv_id,
        source_to_local=source_to_local,
    )
    _write_registered_json(
        stage,
        run_rel,
        "video_gap_audit.json",
        gap_payload,
        "video_gap_audit",
        refs,
        source_bundle.get("gap_path"),
    )

    valid_imported_pointer = _valid_imported_asr_pointer(
        pointer_payload,
        capture_payload,
        refs,
        trade_date=trade_date,
        bv_id=bv_id,
    )
    capture_payload["cannot_confirm"] = _filter_false_missing_pointer_residue(
        capture_payload.get("cannot_confirm") or [],
        valid_imported_pointer=valid_imported_pointer,
    )
    _write_registered_json(
        stage,
        run_rel,
        "capture_manifest.json",
        capture_payload,
        "capture_manifest",
        refs,
        source_bundle.get("capture_path"),
    )

    transcript_ref = next((ref for ref in refs if ref["kind"] == "transcript"), None)
    primary_media = next(
        (ref for ref in media_refs if str(ref["path"]).lower().endswith(".mp4")),
        media_refs[0] if media_refs else None,
    )
    cannot_confirm: list[str] = []
    capture_cannot_confirm = capture_payload.get("cannot_confirm") or []
    acceptance_cannot_confirm = source_bundle.get("acceptance", {}).get("cannot_confirm") or []
    cannot_confirm.extend(str(value) for value in capture_cannot_confirm)
    cannot_confirm.extend(str(value) for value in acceptance_cannot_confirm)
    if not bv_id:
        cannot_confirm.append("DAILY_VIDEO_NOT_LOCKED: no same-day or weekend-late target video")
    if bv_id and not primary_media:
        cannot_confirm.append("media artifact was not available for import")
    if bv_id and not transcript_ref:
        cannot_confirm.append("ASR transcript artifact was not available for import")
    cannot_confirm = _filter_false_missing_pointer_residue(
        cannot_confirm,
        valid_imported_pointer=valid_imported_pointer,
    )
    cannot_confirm = _unique(cannot_confirm)

    gap_status = str(gap_payload.get("status") or "DAILY_VIDEO_NOT_LOCKED")
    capture_status = str(capture_payload.get("status") or "NOT_RUN") if bv_id else "NOT_RUN"
    asr_status = capture_status if bv_id else "NOT_RUN"
    if bv_id and not source_bundle.get("capture_path"):
        capture_status = asr_status = "CAPTURE_NOT_AVAILABLE"
    asr_segment_count = _segment_count(segment_source)
    targeted_spotcheck_count = _spotcheck_count(source_bundle, gap_payload)
    date_scope = str(selection.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED")
    if date_scope not in ALLOWED_DATE_SCOPES:
        date_scope = "DAILY_VIDEO_NOT_LOCKED"
    discovery_status = str(selection.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED")
    producer_identity = {
        "name": "v3.bilibili_fupan_update_watch",
        "module": "bilibili_fupan_update_watch.py",
        "contract": "single_video_producer",
        "source_sha256": source_bundle["source_hashes"].get("v3_producer", {}).get("sha256", ""),
    }
    output_sha256 = {ref["path"]: ref["sha256"] for ref in refs}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "run_id": run_id,
        "bv_id": bv_id,
        "title": str(selection.get("title") or ""),
        "upload_date": str(selection.get("upload_date") or ""),
        "target_trade_date": trade_date,
        "date_scope": date_scope,
        "discovery_status": discovery_status,
        "capture_status": capture_status,
        "asr_status": asr_status,
        "asr_segment_count": asr_segment_count,
        "gap_status": gap_status,
        "gap_row_count": int(gap_payload.get("gap_row_count") or 0),
        "targeted_spotcheck_count": targeted_spotcheck_count,
        "media_sha256": primary_media["sha256"] if primary_media else "",
        "transcript_sha256": transcript_ref["sha256"] if transcript_ref else "",
        "cannot_confirm": cannot_confirm,
        "producer_identity": producer_identity,
        "producer": producer_identity,
        "implementation_sha256": source_bundle["source_hashes"].get(
            "review_core_implementation", {}
        ),
        "input_sha256": source_bundle.get("source_hashes") or {},
        "output_sha256": output_sha256,
        "artifact_refs": refs,
        "media_refs": media_refs,
        "network_used": False,
        "network_allowed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "video_evidence_boundary": "ENHANCEMENT_ONLY_INDEPENDENT_REVIEW_NOT_VIDEO_AUGMENTED",
    }
    manifest_path = _write_registered_json(stage, run_rel, "manifest.json", manifest, "manifest", refs)
    # The manifest is deliberately not included in its own output_sha256 map.
    manifest_sha = sha256_file(manifest_path)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "trade_date": trade_date,
        "run_id": run_id,
        "status": "IMPORTED" if bv_id else "DAILY_VIDEO_NOT_LOCKED",
        "input_digest": input_digest,
        "acquisition_count": 0,
        "asr_execution_count": 0,
        "import_count": sum(1 for ref in refs if ref["import_mode"] == "IMPORT_COPY"),
        "artifact_count": len(refs),
        "network_used": False,
        "manifest_sha256": manifest_sha,
        "safety_flags": {name: False for name in SAFETY_FLAG_NAMES},
    }
    receipt_path = stage / "receipt.json"
    _atomic_write_json(receipt_path, receipt)
    receipt_sha = sha256_file(receipt_path)
    if run_dir.exists():
        raise ImmutableRunError(f"refusing to overwrite immutable run: {run_dir}")
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, run_dir)

    current_payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "trade_date": trade_date,
        "run_id": run_id,
        "input_digest": input_digest,
        "run_path": run_rel,
        "manifest_path": f"{run_rel}/manifest.json",
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "safety_flags": {name: False for name in SAFETY_FLAG_NAMES},
    }
    current_path = data_root / "review" / trade_date / "current.json"
    _atomic_write_json(current_path, current_payload)
    inspected = inspect_bundle(trade_date, data_root)
    return {
        "status": inspected["discovery_status"],
        "idempotent": False,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "current_path": str(current_path),
        "manifest": inspected,
        "acquisition_count": 0,
        "asr_execution_count": 0,
    }


def _existing_current(data_root: Path, trade_date: str) -> dict[str, Any] | None:
    current_path = data_root / "review" / trade_date / "current.json"
    if not current_path.is_file():
        return None
    current = _read_json(current_path)
    if current.get("trade_date") != trade_date:
        raise EvidenceValidationError(f"stale current pointer for exact date {trade_date}")
    return current


def run_video(
    trade_date: str,
    *,
    data_root: Path | str | None = None,
    source_root: Path | str | None = None,
    source_index_path: Path | str | None = None,
    source_package_root: Path | str | None = None,
    mode: str = "import-existing",
    allow_network: bool = False,
    tools: Any | None = None,
    acquisition_tools: Any | None = None,
    config: Any | None = None,
    funasr_path: Path | str | None = None,
    ffmpeg_path: Path | str | None = None,
    ytdlp_path: Path | str | None = None,
    python_path: Path | str | None = None,
    target_mid: str | None = None,
    target_uploader: str | None = None,
    independent_review_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the standalone producer in import-existing or acquire mode.

    The original A1 call shape remains import-only and network-free.  Acquire
    mode is delegated lazily to ``review_core.producer`` so this core module
    never imports or executes a V3 orchestrator.
    """

    if mode == "acquire":
        from .producer import acquire_video

        runtime_root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
        return acquire_video(
            trade_date,
            data_root=runtime_root,
            allow_network=allow_network,
            tools=tools if tools is not None else acquisition_tools,
            config=config,
            source_root=source_root,
            funasr_path=funasr_path,
            ffmpeg_path=ffmpeg_path,
            ytdlp_path=ytdlp_path,
            python_path=python_path,
            target_mid=target_mid,
            target_uploader=target_uploader,
            independent_review_input=independent_review_input,
        )
    if mode not in {"import-existing", "import_existing", "import"}:
        raise ValueError(f"unsupported run-video mode: {mode}")

    target = normalize_trade_date(trade_date)
    runtime_root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    runtime_root = runtime_root.absolute()
    source_base = Path(source_root) if source_root is not None else DEFAULT_SOURCE_ROOT
    source_base = source_base.absolute()
    bundle = _load_source_bundle(
        target,
        source_base,
        Path(source_index_path).absolute() if source_index_path else None,
        Path(source_package_root).absolute() if source_package_root else None,
    )
    input_digest = _selection_digest(target, bundle)
    run_id = _run_id(target, bundle, input_digest)
    current = _existing_current(runtime_root, target)
    if current is not None and current.get("input_digest") == input_digest:
        inspected = inspect_bundle(target, runtime_root)
        if inspected.get("run_id") != run_id:
            raise EvidenceValidationError("current pointer run_id does not match deterministic input")
        return {
            "status": inspected["discovery_status"],
            "idempotent": True,
            "run_id": run_id,
            "run_dir": str(runtime_root / "review" / target / "runs" / run_id),
            "current_path": str(runtime_root / "review" / target / "current.json"),
            "manifest": inspected,
            "acquisition_count": 0,
            "asr_execution_count": 0,
        }
    if current is not None:
        # A different deterministic input is a new immutable version. Validate
        # the current version before advancing the mutable exact-date pointer.
        inspect_bundle(target, runtime_root)
    return _materialize(target, runtime_root, bundle, input_digest, run_id)


def _validate_ref(data_root: Path, ref: dict[str, Any]) -> Path:
    if not isinstance(ref, dict):
        raise EvidenceValidationError("artifact_refs contains a non-object")
    relative = _safe_relative_path(ref.get("path"))
    path = data_root / Path(relative)
    if not _inside(data_root, path) or not path.is_file():
        raise EvidenceValidationError(f"missing referenced artifact: {relative}")
    expected = str(ref.get("sha256") or "")
    actual = sha256_file(path)
    if not expected or actual != expected:
        raise EvidenceValidationError(f"SHA mismatch for referenced artifact: {relative}")
    return path


def _validate_local_reference(data_root: Path, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise EvidenceValidationError("missing local artifact reference")
    relative = _safe_relative_path(value)
    path = data_root / Path(relative)
    if not _inside(data_root, path) or not path.is_file():
        raise EvidenceValidationError(f"missing referenced local path: {relative}")


def _validate_pointer(data_root: Path, pointer_path: Path, manifest: dict[str, Any]) -> None:
    pointer = _read_json(pointer_path)
    if pointer.get("schema_version") != ASR_POINTER_SCHEMA_VERSION:
        raise EvidenceValidationError("ASR pointer schema mismatch")
    if pointer.get("trade_date") != manifest["trade_date"]:
        raise EvidenceValidationError("ASR pointer date mismatch")
    if str(pointer.get("bv") or "") != str(manifest.get("bv_id") or ""):
        raise EvidenceValidationError("ASR pointer BV mismatch")
    for key, value in pointer.items():
        if key == "source_path":
            continue
        if key.endswith("_path") or key in {"current_asr_md", "stock_mentions_csv", "segment_path", "trace_path"}:
            if value:
                _validate_local_reference(data_root, value)
    for value in pointer.get("referenced_artifacts") or []:
        _validate_local_reference(data_root, value)


def _validate_capture(data_root: Path, capture_path: Path, manifest: dict[str, Any]) -> None:
    capture = _read_json(capture_path)
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise EvidenceValidationError("capture manifest schema mismatch")
    if capture.get("trade_date") != manifest["trade_date"]:
        raise EvidenceValidationError("capture manifest date mismatch")
    if str(capture.get("bv_id") or "") != str(manifest.get("bv_id") or ""):
        raise EvidenceValidationError("capture manifest BV mismatch")
    for key in (
        "media_files",
        "audio_files",
        "subtitle_files",
        "transcript_files",
        "segment_files",
        "token_files",
        "asr_run_manifests",
        "metadata_files",
    ):
        for value in capture.get(key) or []:
            _validate_local_reference(data_root, value)
    for key in ("stock_alias_recovery_csv", "stock_mentions_recovered_csv"):
        if capture.get(key):
            _validate_local_reference(data_root, capture[key])


def _validate_gap(data_root: Path, gap_path: Path, manifest: dict[str, Any]) -> None:
    gap = _read_json(gap_path)
    if gap.get("schema_version") != GAP_SCHEMA_VERSION:
        raise EvidenceValidationError("video gap audit schema mismatch")
    if gap.get("trade_date") != manifest["trade_date"]:
        raise EvidenceValidationError("video gap audit date mismatch")
    if str(gap.get("bv_id") or "") != str(manifest.get("bv_id") or ""):
        raise EvidenceValidationError("video gap audit BV mismatch")
    rows = gap.get("gap_rows")
    if not isinstance(rows, list) or int(gap.get("gap_row_count") or 0) != len(rows):
        raise EvidenceValidationError("video gap audit row count mismatch")
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceValidationError("video gap audit row is not an object")
        for key in ("evidence_route", "evidence_path"):
            if row.get(key):
                _validate_local_reference(data_root, row[key])


def inspect_bundle(trade_date: str, data_root: Path | str | None = None) -> dict[str, Any]:
    """Read exactly one date pointer and reject any stale or unsafe fallback."""

    target = normalize_trade_date(trade_date)
    runtime_root = (Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT).absolute()
    current_path = runtime_root / "review" / target / "current.json"
    if not current_path.is_file():
        raise EvidenceValidationError(f"exact-date current pointer missing: {target}")
    current = _read_json(current_path)
    if current.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise EvidenceValidationError("current pointer schema mismatch")
    if current.get("trade_date") != target:
        raise EvidenceValidationError("current pointer date mismatch")
    for name in SAFETY_FLAG_NAMES:
        if current.get("safety_flags", {}).get(name) is not False:
            raise EvidenceValidationError(f"unsafe current flag: {name}")
    run_rel = _safe_relative_path(current.get("run_path"))
    expected_run_rel = f"review/{target}/runs/{current.get('run_id', '')}"
    if run_rel != expected_run_rel:
        raise EvidenceValidationError("stale or non-exact current run path")
    manifest_rel = _safe_relative_path(current.get("manifest_path"))
    expected_manifest_rel = f"{run_rel}/manifest.json"
    if manifest_rel != expected_manifest_rel:
        raise EvidenceValidationError("current manifest path is not exact-date")
    manifest_path = runtime_root / Path(manifest_rel)
    if not manifest_path.is_file():
        raise EvidenceValidationError("current manifest is missing")
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != str(current.get("manifest_sha256") or ""):
        raise EvidenceValidationError("current manifest SHA mismatch")
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceValidationError("VideoEvidenceV1 schema mismatch")
    if manifest.get("trade_date") != target or manifest.get("target_trade_date") != target:
        raise EvidenceValidationError("VideoEvidenceV1 exact date mismatch")
    if manifest.get("run_id") != current.get("run_id"):
        raise EvidenceValidationError("manifest run_id mismatch")
    if manifest.get("date_scope") not in ALLOWED_DATE_SCOPES:
        raise EvidenceValidationError("invalid VideoEvidenceV1 date_scope")
    for name in SAFETY_FLAG_NAMES:
        if manifest.get(name) is not False:
            raise EvidenceValidationError(f"unsafe manifest flag: {name}")
        if current.get("safety_flags", {}).get(name) is not False:
            raise EvidenceValidationError(f"unsafe current flag: {name}")
    refs = manifest.get("artifact_refs")
    if not isinstance(refs, list):
        raise EvidenceValidationError("artifact_refs missing")
    validated_refs = [_validate_ref(runtime_root, ref) for ref in refs]
    ref_by_kind = {ref.get("kind"): ref for ref in refs if isinstance(ref, dict)}
    required_names = {
        "source_index.json": "source_index",
        "video_session.json": "video_session",
        "capture_manifest.json": "capture_manifest",
        "video_gap_audit.json": "video_gap_audit",
        "asr/current_asr_pointer.json": "asr_pointer",
    }
    for name, kind in required_names.items():
        relative = f"{run_rel}/{name}"
        matching = [ref for ref in refs if ref.get("path") == relative and ref.get("kind") == kind]
        if not matching:
            raise EvidenceValidationError(f"required bundle artifact missing: {relative}")
    output_sha = manifest.get("output_sha256")
    if not isinstance(output_sha, dict):
        raise EvidenceValidationError("output_sha256 missing")
    for ref in refs:
        if output_sha.get(ref.get("path")) != ref.get("sha256"):
            raise EvidenceValidationError(f"output SHA ledger mismatch: {ref.get('path')}")
    media_refs = [ref for ref in refs if ref.get("kind") == "media"]
    for ref in media_refs:
        path = str(ref.get("path") or "")
        parts = Path(path).parts
        if len(parts) < 4 or parts[0] != "media" or parts[1] != str(manifest.get("bv_id") or ""):
            raise EvidenceValidationError("media reference is not content-addressed")
        if parts[2] != ref.get("sha256"):
            raise EvidenceValidationError("content-addressed media directory SHA mismatch")
    primary_media_sha = str(manifest.get("media_sha256") or "")
    if primary_media_sha and primary_media_sha not in {ref.get("sha256") for ref in media_refs}:
        raise EvidenceValidationError("primary media SHA is not referenced")
    transcript_refs = [ref for ref in refs if ref.get("kind") == "transcript"]
    transcript_sha = str(manifest.get("transcript_sha256") or "")
    if transcript_sha and transcript_sha not in {ref.get("sha256") for ref in transcript_refs}:
        raise EvidenceValidationError("transcript SHA is not referenced")

    pointer_path = runtime_root / Path(f"{run_rel}/asr/current_asr_pointer.json")
    capture_path = runtime_root / Path(f"{run_rel}/capture_manifest.json")
    gap_path = runtime_root / Path(f"{run_rel}/video_gap_audit.json")
    _validate_pointer(runtime_root, pointer_path, manifest)
    _validate_capture(runtime_root, capture_path, manifest)
    _validate_gap(runtime_root, gap_path, manifest)

    receipt_path = runtime_root / Path(f"{run_rel}/receipt.json")
    if not receipt_path.is_file():
        raise EvidenceValidationError("receipt is missing")
    if sha256_file(receipt_path) != str(current.get("receipt_sha256") or ""):
        raise EvidenceValidationError("receipt SHA mismatch")
    receipt = _read_json(receipt_path)
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise EvidenceValidationError("receipt schema mismatch")
    if receipt.get("trade_date") != target or receipt.get("run_id") != current.get("run_id"):
        raise EvidenceValidationError("receipt identity mismatch")
    if receipt.get("manifest_sha256") != manifest_sha:
        raise EvidenceValidationError("receipt manifest SHA mismatch")
    for name in SAFETY_FLAG_NAMES:
        if receipt.get("safety_flags", {}).get(name) is not False:
            raise EvidenceValidationError(f"unsafe receipt flag: {name}")
    if current.get("input_digest") != _digest_from_manifest(manifest):
        raise EvidenceValidationError("current input digest does not match manifest input SHA")
    # Keep the returned object pure evidence; do not expose mutable Path values.
    return manifest


def _digest_from_manifest(manifest: dict[str, Any]) -> str:
    payload = {
        "contract": SCHEMA_VERSION,
        "trade_date": manifest.get("trade_date"),
        "selection": {
            "bv_id": manifest.get("bv_id", ""),
            "title": manifest.get("title", ""),
            "upload_date": manifest.get("upload_date", ""),
            "date_scope": manifest.get("date_scope", "DAILY_VIDEO_NOT_LOCKED"),
        },
        "source_sha256": manifest.get("input_sha256") or {},
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def reconcile(
    *,
    data_root: Path | str | None = None,
    lookback_trading_days: int = 5,
) -> dict[str, Any]:
    runtime_root = (Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT).absolute()
    if lookback_trading_days < 1:
        raise ValueError("lookback_trading_days must be positive")
    review_root = runtime_root / "review"
    dates: list[str] = []
    if review_root.is_dir():
        dates = sorted(
            (path.name for path in review_root.iterdir() if path.is_dir() and re.fullmatch(r"\d{8}", path.name)),
            reverse=True,
        )[:lookback_trading_days]
    results: list[dict[str, Any]] = []
    for target in dates:
        try:
            manifest = inspect_bundle(target, runtime_root)
            results.append(
                {
                    "trade_date": target,
                    "status": "VALID",
                    "run_id": manifest.get("run_id"),
                    "bv_id": manifest.get("bv_id", ""),
                    "date_scope": manifest.get("date_scope"),
                }
            )
        except EvidenceValidationError as exc:
            results.append({"trade_date": target, "status": "INVALID", "error": str(exc)})
    overall = "RECONCILE_OK" if all(item["status"] == "VALID" for item in results) else "RECONCILE_PARTIAL"
    return {
        "status": overall,
        "lookback_trading_days": lookback_trading_days,
        "dates": results,
        "network_used": False,
    }


def run_review(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Lazy ReviewBundleV1 entry point kept separate from VideoEvidenceV1.

    Import lazily so the existing video producer/inspector remains usable
    without creating a module cycle.  ReviewBundleV1 is an integration layer;
    it does not alter the VideoEvidenceV1 manifest or independent review.
    """

    from .review import run_review as _run_review

    return _run_review(*args, **kwargs)


def inspect_review_bundle(trade_date: str, output_root: Path | str | None = None) -> dict[str, Any]:
    """Lazy strict ReviewBundleV1 pointer inspection helper."""

    from .review import inspect_review_bundle as _inspect_review_bundle

    return _inspect_review_bundle(trade_date, output_root)
