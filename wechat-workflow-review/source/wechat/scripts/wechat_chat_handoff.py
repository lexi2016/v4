#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and archive a local WeChat -> Chat research handoff.

The command deliberately stops at a research handoff boundary:

* ``package`` consumes one existing intake/OCR run.  It never fetches a URL,
  runs OCR, extracts securities, or writes a V3/formal pool.
* ``import`` archives files returned by a user.  It preserves the original
  bytes, binds them to an explicit source run and package identity, and never
  treats Chat self-reported counts as local acceptance.

Package image validation additionally requires Pillow; import/archive uses stdlib.
No command performs network requests, OCR, publication, or trading.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

try:
    from wechat_common import (_reject_symlink_components, safe_run_path, validate_run_dir,
                               _ArticleBodyTextParser, normalize_date, ocr_record_complete, validate_slice_geometry)
except ImportError:  # pragma: no cover - supports direct import from another cwd
    import sys

    sys.path.insert(0, str(SCRIPT_DIR))
    from wechat_common import (_reject_symlink_components, safe_run_path, validate_run_dir,
                               _ArticleBodyTextParser, normalize_date, ocr_record_complete, validate_slice_geometry)


class HandoffError(ValueError):
    """A fail-closed package/import contract error."""


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_IMAGE_MARKER_RE = re.compile(r"\[IMAGE(\d{3})\]")
_SOURCE_INDEX_RE = re.compile(r"^IMAGE\d{3}$")
_REVIEW_CONTRACT_VERSION = "wechat-event-dispositions-v1"
_EVENT_DISPOSITIONS = frozenset({"PROMOTE", "HOLD", "REJECT", "CANNOT_CONFIRM"})
_REQUIRED_MANIFEST_FIELDS = {
    "idx",
    "url",
    "local_path",
    "download_status",
    "image_size",
    "sha256",
    "bytes",
}
_COVERAGE_HEADERS = {
    "source_index",
    "event",
    "subject",
    "claim",
    "date",
    "number",
    "unit",
    "source_grade",
    "uncertainty",
    "original_checked",
    "original_scope",
    "text_read",
}
_MENTIONS_HEADERS = {
    "market",
    "code",
    "name",
    "source_index",
    "mapping_status",
    "source_named_or_derived",
    "claim_context",
    "entity_id",
    "source_name",
    "listing_origin",
}
_UNMAPPED_HEADERS = {"name", "reason", "source_index"}
_SUMMARY_FIELDS = {
    "schema_version", "input_digest", "return_id", "reading_mode", "artifact_sha256",
    "production_allowed", "buy_gate_updated", "orders_sent",
    "url",
    "package_id",
    "manifest_sha256",
    "article_date",
    "image_count",
    "coverage_counts",
    "mentions_counts",
    "status",
    "missing_inputs",
}
_CHAT_SUMMARY_STATUS_ALLOWED = frozenset({
    "COMPLETE_WITH_ALL_SOURCES",
    "PARTIAL",
    "PARTIAL_WITH_UNREADABLE",
    "CANNOT_CONFIRM",
    "RESEARCH_ONLY",
    "WATCH_ONLY",
    "NO_BUY_GATE",
})
_CHAT_SUMMARY_STATUS_FORBIDDEN = frozenset({
    "RESEARCH_VERIFIED",
    "API_VERIFIED",
    "UI_VERIFIED",
    "NATURAL_VERIFIED",
})


def _read_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise HandoffError(f"{label} is not a regular file: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HandoffError(f"cannot read {label}: {path}") from exc
    return data


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(_read_bytes(path, label).decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"invalid {label}: {path}") from exc


def _json_no_duplicate_keys(data: bytes, *, label: str) -> Any:
    """Load JSON while preserving the contract's fail-closed duplicate-key rule."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HandoffError(f"{label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"{label} is not valid JSON") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise HandoffError(f"cannot hash file: {path}") from exc
    return digest.hexdigest()


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        return raw
    # Short-token URLs use their path. Long /s URLs carry article identity
    # in __biz/mid/idx/sn; never collapse distinct articles by dropping them.
    host = (parts.hostname or "").lower()
    if host == "mp.weixin.qq.com":
        path = parts.path.rstrip("/")
        query = ""
        if path == "/s":
            pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                     if k in {"__biz", "mid", "idx", "sn"}]
            query = urlencode(sorted(pairs))
        return urlunsplit(("https", host, path, query, ""))
    return raw


def _safe_package_id(value: object) -> str:
    text = str(value or "").strip()
    if not _PACKAGE_ID_RE.fullmatch(text):
        raise HandoffError("package_id must be a simple non-empty identifier")
    return text


def _run_file(run_dir: Path, value: object, *, label: str, required: bool = True) -> Path:
    """Resolve a manifest path inside ``run_dir`` without traversal/symlinks."""

    raw = str(value or "").strip()
    if not raw:
        raise HandoffError(f"{label} path is empty")
    path = Path(raw)
    # Existing manifests from the Windows/Mac handoff can contain a ROOT
    # relative ``runs/<run-id>/...`` path.  Trim the run prefix only after
    # checking that it names this exact run; never accept a parent component.
    if ".." in path.parts:
        raise HandoffError(f"unsafe {label} path: {raw}")
    run_name = run_dir.name
    parts = list(path.parts)
    if run_name in parts:
        path = Path(*parts[parts.index(run_name) + 1 :])
    try:
        return safe_run_path(run_dir, path, must_exist=required, label=label)
    except (OSError, ValueError) as exc:
        if not required and isinstance(exc, FileNotFoundError):
            return safe_run_path(run_dir, path, must_exist=False, label=label)
        raise HandoffError(str(exc)) from exc


def _external_file(value: object, *, label: str, required: bool = True) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise HandoffError(f"{label} path is required")
        return None
    path = Path(raw).expanduser()
    if ".." in path.parts:
        raise HandoffError(f"unsafe {label} path: {raw}")
    if path.is_symlink():
        raise HandoffError(f"{label} must not be a symlink: {raw}")
    try:
        _reject_symlink_components(path, label)
    except (OSError, ValueError) as exc:
        raise HandoffError(f"unsafe {label} path: {raw}") from exc
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise HandoffError(f"{label} does not exist: {raw}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise HandoffError(f"{label} is not a regular file: {raw}")
    return resolved


def _ensure_output_dir(value: object, *, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise HandoffError(f"{label} is required")
    path = Path(raw).expanduser()
    if ".." in path.parts:
        raise HandoffError(f"unsafe {label} path: {raw}")
    _reject_symlink_components(path, label)
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise HandoffError(f"{label} is not a directory: {path}")
    return path.resolve()


def _write_if_same(path: Path, data: bytes, *, label: str) -> bool:
    """Create a file, or accept an exact existing copy without overwriting it."""

    try:
        _reject_symlink_components(path, label)
    except (OSError, ValueError) as exc:
        raise HandoffError(f"unsafe {label} path: {path}") from exc
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise HandoffError(f"refusing to overwrite non-file {label}: {path}")
        existing = _read_bytes(path, label)
        if existing == data:
            return False
        raise HandoffError(f"refusing to overwrite existing {label}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Atomic create-only publication: a concurrent writer must not be
            # overwritten between the existence check and the final write.
            os.link(temp_name, path)
        except FileExistsError:
            if _read_bytes(path, label) != data:
                raise HandoffError(f"concurrent different {label}: {path}")
            return False
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return True


def _copy_if_same(source: Path, destination: Path, *, label: str) -> bool:
    data = _read_bytes(source, label)
    return _write_if_same(destination, data, label=label)


def _identity_from_intake(run_dir: Path) -> dict[str, Any]:
    intake_path = _run_file(run_dir, "wechat_article_intake_summary.json", label="intake summary")
    intake = _read_json(intake_path, "intake summary")
    if not isinstance(intake, dict):
        raise HandoffError("intake summary must be a JSON object")
    if str(intake.get("identity_status") or "").upper() != "PASS":
        raise HandoffError("intake identity_status is not PASS")
    url = _canonical_url(intake.get("canonical_url") or intake.get("article_url") or intake.get("url"))
    url_parts = urlsplit(url)
    if (
        not url
        or (url_parts.hostname or "").lower() != "mp.weixin.qq.com"
        or not (url_parts.path.startswith("/s/") or (url_parts.path == "/s" and {"__biz", "mid", "idx"}.issubset(dict(parse_qsl(url_parts.query)))))
    ):
        raise HandoffError("intake article URL is missing or not a WeChat article")
    title = " ".join(str(intake.get("title") or "").split())
    account = " ".join(str(intake.get("account_name") or intake.get("account") or "").split())
    biz = str(intake.get("biz") or "").strip()
    try:
        article_date = normalize_date(intake.get("article_date"), label="article_date")
    except ValueError as exc:
        raise HandoffError(str(exc)) from exc
    content_hash = str(intake.get("content_hash") or intake.get("evidence_hash") or "").strip().lower()
    if not title or not account or not biz or not re.fullmatch(r"20\d{6}", article_date) or not content_hash:
        raise HandoffError("intake identity is incomplete (title/account/biz/article_date/content_hash)")
    raw_image_count = intake.get("image_count")
    if type(raw_image_count) is not int or raw_image_count < 0:
        raise HandoffError("intake image_count must be a non-negative integer")
    image_count = raw_image_count
    published_at = str(intake.get("published_at") or intake.get("published_at_iso") or "").strip()
    if not published_at:
        raw_publish_time = intake.get("raw_publish_time")
        try:
            timestamp = int(str(raw_publish_time).strip())
            published_at = _dt.datetime.fromtimestamp(
                timestamp, tz=_dt.timezone(_dt.timedelta(hours=8))
            ).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            published_at = ""
    try:
        published = _dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published.tzinfo is None or published.utcoffset() is None:
            raise ValueError("timezone is required")
        if published.strftime("%Y%m%d") != article_date:
            raise ValueError("published_at date does not match article_date")
    except ValueError as exc:
        raise HandoffError("published_at must be a real timezone-aware article timestamp: " + str(exc)) from exc
    return {
        "url": url,
        "original_url": str(intake.get("article_url") or intake.get("url") or url),
        "article_id": str(intake.get("article_id") or url_parts.path.rsplit("/", 1)[-1]),
        "captured_at": str(intake.get("captured_at") or intake.get("fetched_at") or ""),
        "title": title,
        "account": account,
        "biz": biz,
        "article_date": article_date,
        "published_at": published_at,
        "content_hash": content_hash,
        "image_count": image_count,
        "intake_sha256": _sha256_file(intake_path),
        "intake_path": str(intake_path),
    }


def _manifest_rows(run_dir: Path, identity: dict[str, Any]) -> tuple[Path, bytes, list[dict[str, str]]]:
    manifest_path = _run_file(run_dir, "wechat_article_image_manifest.csv", label="image manifest")
    manifest_bytes = _read_bytes(manifest_path, "image manifest")
    try:
        reader = csv.DictReader(manifest_bytes.decode("utf-8-sig").splitlines())
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise HandoffError("image manifest is not valid UTF-8 CSV") from exc
    if not fieldnames or not _REQUIRED_MANIFEST_FIELDS.issubset(set(fieldnames)):
        raise HandoffError("image manifest is missing required fields")
    expected_count = int(identity["image_count"])
    if len(rows) != expected_count:
        raise HandoffError(f"image manifest count mismatch: expected {expected_count}, got {len(rows)}")
    image_root = run_dir / "wechat_article_images"
    if image_root.is_symlink() or not image_root.is_dir():
        raise HandoffError("article image directory is missing or unsafe")
    if expected_count == 0 and any(image_root.iterdir()):
        raise HandoffError("text-only intake has image files outside its empty manifest")
    seen_urls: set[str] = set()
    for expected_index, row in enumerate(rows, start=1):
        try:
            index = int(str(row.get("idx") or "").strip())
        except ValueError as exc:
            raise HandoffError(f"image manifest idx is invalid at row {expected_index}") from exc
        if index != expected_index:
            raise HandoffError(f"image manifest order is not 1..N at row {expected_index}")
        url = str(row.get("url") or "").strip()
        if not url:
            raise HandoffError(f"image manifest URL is empty at IMAGE{index:03d}")
        if url in seen_urls:
            # Duplicate source URLs can be legitimate, so retain the row but
            # make the duplicate explicit in the package manifest.  Position
            # order, rather than URL uniqueness, is the identity contract.
            row["duplicate_source_url"] = "true"
        seen_urls.add(url)
        if not str(row.get("download_status") or "").upper().startswith("OK"):
            raise HandoffError(f"image download is not OK at IMAGE{index:03d}")
        declared_sha = str(row.get("sha256") or row.get("image_sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(declared_sha):
            raise HandoffError(f"image SHA-256 is missing/invalid at IMAGE{index:03d}")
        declared_bytes = str(row.get("bytes") or "").strip()
        try:
            byte_count = int(declared_bytes)
        except ValueError as exc:
            raise HandoffError(f"image byte count is invalid at IMAGE{index:03d}") from exc
        if byte_count <= 0:
            raise HandoffError(f"image is empty at IMAGE{index:03d}")
        image_path = _run_file(run_dir, row.get("local_path"), label=f"IMAGE{index:03d}")
        if (image_path.parent != image_root or image_path.stem.lower() not in {
            f"img_{index:02d}", f"img_{index:03d}", f"image{index:03d}"
        } or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}):
            raise HandoffError(f"image path/order mismatch at IMAGE{index:03d}")
        image_bytes = _read_bytes(image_path, f"IMAGE{index:03d}")
        if len(image_bytes) != byte_count or _sha256_bytes(image_bytes) != declared_sha:
            raise HandoffError(f"image bytes/SHA-256 mismatch at IMAGE{index:03d}")
        width, height, image_format = _decode_image(image_bytes, f"IMAGE{index:03d}")
        suffix_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
        if suffix_format[image_path.suffix.lower()] != image_format:
            raise HandoffError(f"image extension/format mismatch at IMAGE{index:03d}")
        if re.sub(r"[X×]", "x", row["image_size"].strip()) != f"{width}x{height}":
            raise HandoffError(f"image dimensions mismatch at IMAGE{index:03d}")
        row["_package_path"] = f"images/IMAGE{index:03d}{image_path.suffix.lower()}"
        row["_format"] = image_format
        row["_resolved_path"] = str(image_path)
        row["_declared_sha"] = declared_sha
        row["_declared_bytes"] = str(byte_count)
    return manifest_path, manifest_bytes, rows


def _package_manifest_csv(manifest_bytes: bytes, rows: list[dict[str, str]]) -> bytes:
    """Make the package manifest self-contained without leaking local paths."""

    try:
        reader = csv.DictReader(manifest_bytes.decode("utf-8-sig").splitlines())
        fieldnames = list(reader.fieldnames or [])
    except (UnicodeError, csv.Error) as exc:
        raise HandoffError("image manifest cannot be normalized for packaging") from exc
    if not fieldnames:
        raise HandoffError("image manifest has no header")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        normalized = {key: str(row.get(key) or "") for key in fieldnames}
        index = int(row["idx"])
        normalized["local_path"] = row["_package_path"]
        writer.writerow(normalized)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _decode_image(data: bytes, label: str) -> tuple[int, int, str]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise HandoffError("Pillow is required to verify original image decoding") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            size, fmt = image.size, image.format
            if fmt not in {"JPEG", "PNG", "WEBP"}:
                raise HandoffError(f"unsupported original image format: {label}: {fmt}")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return int(size[0]), int(size[1]), str(fmt)
    except (OSError, ValueError, SyntaxError) as exc:
        raise HandoffError(f"cannot decode original image: {label}") from exc


class _BodyWithImageMarkers(_ArticleBodyTextParser):
    """Use the shared HTML scope parser, adding only ordered image markers."""

    def __init__(self, url_to_indexes: dict[str, list[int]]) -> None:
        super().__init__()
        self._url_to_indexes = {key: list(value) for key, value in url_to_indexes.items()}
        self.body_image_count = 0

    def on_image(self, attrs: list[tuple[str, str | None]]) -> None:
        self.body_image_count += 1
        attr = {str(key).lower(): str(value or "").strip() for key, value in attrs}
        source = _canonical_url(attr.get("data-src") or attr.get("src"))
        indexes = self._url_to_indexes.get(source) or []
        if indexes:
            self._parts.append(f"\n[IMAGE{indexes.pop(0):03d}]\n")


def _body_with_markers(run_dir: Path, rows: list[dict[str, str]]) -> str:
    html_path = _run_file(run_dir, "wechat_article_raw.html", label="raw article HTML")
    raw = _read_bytes(html_path, "raw article HTML").decode("utf-8-sig", errors="replace")
    mapping: dict[str, list[int]] = {}
    for row in rows:
        mapping.setdefault(_canonical_url(row["url"]), []).append(int(row["idx"]))
    parser = _BodyWithImageMarkers(mapping)
    try:
        parser.feed(raw)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise HandoffError("raw article HTML cannot be parsed") from exc
    text = parser.text()
    markers = [int(item) for item in _IMAGE_MARKER_RE.findall(text)]
    expected = list(range(1, len(rows) + 1))
    if markers != expected:
        raise HandoffError(f"BODY image markers are incomplete/out of order: {markers[:8]}...")
    if not rows and (not parser._found_root or parser.body_image_count or not text.strip()):
        raise HandoffError("zero-image intake requires non-empty BODY text and no article-body images")
    return text


def _ocr_records(run_dir: Path, rows: list[dict[str, str]]) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    summary_path = _run_file(run_dir, "wechat_article_ocr_summary.json", label="OCR summary")
    summary = _read_json(summary_path, "OCR summary")
    if not isinstance(summary, dict):
        raise HandoffError("OCR summary must be a JSON object")
    expected_count = len(rows)
    required_zero = ("timeout_count", "error_count", "empty_count")
    if expected_count == 0:
        if (summary.get("status") != "OCR_NOT_APPLICABLE" or
                summary.get("ocr_applicable") is not False or
                summary.get("body_source_required") is not True):
            raise HandoffError("zero-image package requires explicit OCR_NOT_APPLICABLE/body source status")
        for key in ("image_count", "processed_count", "ok_count", *required_zero):
            value = summary.get(key)
            if type(value) is not int or value != 0:
                raise HandoffError(f"zero-image OCR summary {key} must be integer zero")
        results_path = _run_file(run_dir, "windows_ocr_results.json", label="full OCR results")
        raw_results = _read_json(results_path, "full OCR results")
        if raw_results != []:
            raise HandoffError("zero-image OCR results must be an empty list")
        ocr_text_path = _run_file(run_dir, "wechat_article_ocr_text.txt", label="full OCR text")
        ocr_text = _read_bytes(ocr_text_path, "full OCR text").decode("utf-8-sig", errors="replace")
        if ocr_text.strip():
            raise HandoffError("zero-image OCR text must be empty")
        return {}, summary
    if str(summary.get("status") or "").upper() != "OCR_OK":
        raise HandoffError("full OCR summary status is not OCR_OK")
    for key in ("image_count", "processed_count", "ok_count"):
        try:
            if int(summary.get(key) or -1) != expected_count:
                raise HandoffError(f"OCR summary {key} does not match image count")
        except (TypeError, ValueError) as exc:
            raise HandoffError(f"OCR summary {key} is invalid") from exc
    for key in required_zero:
        value = summary.get(key)
        if key not in summary or isinstance(value, bool) or not isinstance(value, int):
            raise HandoffError(f"OCR summary {key} is missing or not an integer")
        if value != 0:
            raise HandoffError(f"OCR summary {key} is not zero")
    results_path = _run_file(run_dir, "windows_ocr_results.json", label="full OCR results")
    raw_results = _read_json(results_path, "full OCR results")
    if not isinstance(raw_results, list) or len(raw_results) != expected_count:
        raise HandoffError("full OCR results count does not match image count")
    declared_sha = {int(row["idx"]): str(row["_declared_sha"]) for row in rows}
    records: dict[int, dict[str, Any]] = {}
    slice_items = None
    for expected_index, record in enumerate(raw_results, start=1):
        if not isinstance(record, dict):
            raise HandoffError(f"OCR record {expected_index} is not an object")
        try:
            index = int(record.get("index") or 0)
        except (TypeError, ValueError) as exc:
            raise HandoffError(f"OCR record {expected_index} index is invalid") from exc
        if index != expected_index or index in records:
            raise HandoffError("OCR records are missing or out of order")
        if not ocr_record_complete(record):
            raise HandoffError(f"OCR status is not OK at IMAGE{index:03d}")
        text = str(record.get("text") or "")
        if not text.strip():
            raise HandoffError(f"OCR text is empty at IMAGE{index:03d}")
        if str(record.get("image_sha256") or "").strip().lower() != declared_sha[index]:
            raise HandoffError(f"OCR source SHA-256 mismatch at IMAGE{index:03d}")
        width, height = (int(v) for v in re.split(r"[xX×]", rows[index - 1]["image_size"]))
        if record.get("parts") or max(width, height) > 10000:
            from wechat_macos_ocr import _load_manifest_items, _cache_row_matches
            if slice_items is None:
                try:
                    slice_items = _load_manifest_items(run_dir)
                except (ValueError, RuntimeError) as exc:
                    raise HandoffError("OCR slice manifest invalid: " + str(exc)) from exc
            if index not in slice_items or not _cache_row_matches(record, slice_items[index], run_dir=run_dir):
                raise HandoffError(f"OCR slice provenance/coverage is incomplete at IMAGE{index:03d}")
        records[index] = record
    ocr_text_path = _run_file(run_dir, "wechat_article_ocr_text.txt", label="full OCR text")
    ocr_text = _read_bytes(ocr_text_path, "full OCR text").decode("utf-8-sig", errors="replace")
    if not ocr_text.strip():
        raise HandoffError("full OCR text is empty")
    text_markers = [int(item) for item in re.findall(r"=====IMAGE(\d{3})\b", ocr_text)]
    if text_markers and text_markers != list(range(1, expected_count + 1)):
        raise HandoffError("full OCR text image boundaries are missing or out of order")
    return records, summary


def _render_body(identity: dict[str, Any], body: str, rows: list[dict[str, str]], package_id: str, manifest_sha: str) -> str:
    source_note = (
        "正文顺序中的 `[IMAGE###]` 是原图边界标记；本文件保留正文文字，不替代原图阅读。"
        if rows else
        "本文章正文没有原图；BODY.md 是完整文字来源，OCR_FULL.md 标记 OCR_NOT_APPLICABLE。"
    )
    lines = [
        "# BODY.md — 微信文章正文",
        "",
        f"- package_id: `{package_id}`",
        f"- URL: {identity['url']}",
        f"- 标题: {identity['title']}",
        f"- 公众号: {identity['account']}",
        f"- biz: `{identity['biz']}`",
        f"- article_date: `{identity['article_date']}`",
        f"- package manifest SHA-256: `{manifest_sha}`",
        "",
        source_note,
        "",
        body,
        "",
    ]
    return "\n".join(lines)


def _render_ocr(identity: dict[str, Any], rows: list[dict[str, str]], records: dict[int, dict[str, Any]], package_id: str, manifest_sha: str) -> str:
    if not rows:
        return "\n".join([
            "# OCR_FULL.md — OCR 不适用",
            "",
            f"- package_id: `{package_id}`",
            f"- URL: {identity['url']}",
            f"- article_date: `{identity['article_date']}`",
            f"- package manifest SHA-256: `{manifest_sha}`",
            "- status: `OCR_NOT_APPLICABLE`",
            "- image_count: `0`",
            "- engine: `NONE`",
            "- semantic_status: `BODY_TEXT_NOT_SEMANTICALLY_VERIFIED`",
            "",
            "本篇没有正文图片，因此未执行 OCR。BODY.md 是完整文字输入；此状态不代表已阅读或核验任何图片。",
            "",
        ])
    lines = [
        "# OCR_FULL.md — 逐图机器转录",
        "",
        f"- package_id: `{package_id}`",
        f"- URL: {identity['url']}",
        f"- article_date: `{identity['article_date']}`",
        f"- package manifest SHA-256: `{manifest_sha}`",
        "- engine: " + ", ".join(sorted({str(r.get("engine") or "LEGACY_ENGINE_UNRECORDED") for r in records.values()})),
        f"- sliced_images: {sum(bool(r.get('parts')) for r in records.values())}",
        f"- legacy_config_unknown: {sum(not bool(r.get('ocr_config_sha256')) for r in records.values())}",
        "- semantic_status: `MACHINE_TRANSCRIPT_NOT_SEMANTICALLY_VERIFIED`",
        "",
        "Chat 必须把 OCR 当索引：数字、代码、单位、归属、模糊字样与关键证据请回看对应原图。",
        "",
    ]
    for row in rows:
        index = int(row["idx"])
        record = records[index]
        image_name = row["_package_path"]
        text = str(record.get("text") or "").strip()
        lines.extend([
            f"=====IMAGE{index:03d} | {image_name} | sha256={row['_declared_sha']} | status={record.get('status')} | chars={len(text)}=====",
            text,
            f"=====END IMAGE{index:03d}=====",
            "",
        ])
    return "\n".join(lines)


def _render_readme(identity: dict[str, Any], package_id: str, manifest_sha: str, source_run: Path, ocr_summary: dict[str, Any]) -> str:
    image_instructions = (
        "Chat 必须按 BODY.md、OCR_FULL.md 和 IMAGE001→IMAGE### 顺序阅读。OCR 不是语义核验，也不证明已逐图视觉阅读；数字、代码、单位、归属、边界或模糊字样必须回看对应原图。"
        if identity["image_count"] else
        "本文没有原图；完整文字来源为 BODY.md。OCR_NOT_APPLICABLE 表示没有图片可供 OCR，不代表图片已被阅读或核验。"
    )
    return "\n".join([
        "# 微信文章 Chat 研究资料包",
        "",
        f"- package_id: `{package_id}`",
        f"- source_run: `{source_run.name}`",
        f"- URL: {identity['url']}",
        f"- 标题: {identity['title']}",
        f"- 公众号: {identity['account']}",
        f"- biz: `{identity['biz']}`",
        f"- published_at: `{identity['published_at'] or 'intake 未提供；见本地 intake'}`",
        f"- article_date/signal_date: `{identity['article_date']}`",
        f"- image_count: `{identity['image_count']}`",
        f"- package manifest SHA-256: `{manifest_sha}`",
        f"- full OCR: `{ocr_summary.get('status')}`, chars=`{ocr_summary.get('text_length')}`",
        "",
        "## 使用边界",
        "",
        "本包是绑定文章身份的研究输入。正文与机器 OCR 的语义均未由打包程序核验。" + image_instructions,
        "",
        "本包是一个冻结研究输入，不表示重新执行OCR。旧报告按原始package_id、input_digest及可信ZIP SHA归档，不能绑定新版正文/OCR。",
        "",
        "研究输出必须保持 `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`。不得把全文提及池、研究观察或 Chat 报告升级为正式池、BUY gate 或交易状态。",
        "",
        "输出请生成 `report.md`、`coverage.csv`、`mentions.csv`、`unmapped.csv`、`summary.json`。来源原文与研究者派生映射分开；A/BJ 与 HK 分开；日期、税币、segment/group、现金流口径分开。",
        "",
        "`manifest.csv` 保留有序图片清单；`manifest.json.input_descriptor/input_digest`绑定正文、OCR及原图。包外ZIP SHA保护整个归档；这些摘要不是原图阅读证据。",
        "",
    ])


def _load_prompt_template() -> str:
    path = ROOT / "templates" / "chat_research_prompt.md"
    data = _read_bytes(path, "Chat prompt template")
    return data.decode("utf-8-sig")


def _render_prompt(identity: dict[str, Any], package_id: str, manifest_sha: str, input_digest: str = "", reading_mode: str = "OCR_RISK_REVIEW") -> str:
    template = _load_prompt_template()
    if identity["image_count"]:
        source_reading_instructions = "\n".join([
            f"顺序为 BODY 全文、OCR_FULL 中 IMAGE001→IMAGE{identity['image_count']:03d}，建立全量来源账本。",
            "- `OCR_RISK_REVIEW`：完整读正文／OCR；名称、代码、金额、单位、期间、归属、税币、公司／分部、关键证据和矛盾必须核看原图。密集表格、跨栏、文字异常少或截断的图直接核看；对 NO_EVENT／低信息来源做少量盲抽查。只读OCR不等于原图已读。",
            "- `FULL_ORIGINAL_REVIEW`：在上述基础上逐张完整打开并阅读原图。不能在回传中降级为OCR主读模式。",
            "打不开或无法辨认的部分如实记原因，必要时按编号补原图；UNREADABLE不得补猜，完整声明相应停止。",
        ])
    else:
        source_reading_instructions = "\n".join([
            "本冻结包 image_count=0；按 BODY.md 完整阅读唯一正文来源。OCR_FULL.md 的 OCR_NOT_APPLICABLE 表示原文没有图片、无需 OCR；coverage.csv 只写一行 BODY，不得虚构图片来源。",
            "不得声称已读图或把 OCR_NOT_APPLICABLE 当作 OCR 成功。若你从正文发现图片内容或图片来源缺失迹象，按 CANNOT_CONFIRM 记录并指出缺口。",
        ])
    if identity["image_count"]:
        coverage_order_instructions = (
            f"coverage.csv 恰好一行 BODY，再按顺序添加 IMAGE001→IMAGE{identity['image_count']:03d}各一行；"
            "BODY内部定位写claim，不新增BODY001。"
        )
    else:
        coverage_order_instructions = (
            "coverage.csv 恰好只有一行 BODY；BODY内部定位写claim，不新增BODY001或虚构图片来源。"
        )
    replacements = {
        "{{INPUT_DIGEST}}": input_digest,
        "{{REVIEW_CONTRACT_VERSION}}": _REVIEW_CONTRACT_VERSION,
        "{{READING_MODE}}": reading_mode,
        "{{PACKAGE_ID}}": package_id,
        "{{URL}}": identity["url"],
        "{{TITLE}}": identity["title"],
        "{{ACCOUNT}}": identity["account"],
        "{{BIZ}}": identity["biz"],
        "{{ARTICLE_DATE}}": identity["article_date"],
        "{{IMAGE_COUNT}}": str(identity["image_count"]),
        "{{LAST_IMAGE}}": f"{identity['image_count']:03d}",
        "{{MANIFEST_SHA256}}": manifest_sha,
        "{{SOURCE_READING_INSTRUCTIONS}}": source_reading_instructions,
        "{{COVERAGE_ORDER_INSTRUCTIONS}}": coverage_order_instructions,
    }
    for key, value in replacements.items():
        template = template.replace(key, str(value))
    unresolved = sorted(set(re.findall(r"\{\{[^{}]+\}\}", template)))
    if unresolved:
        raise HandoffError(
            "Chat prompt has unsupported placeholders: " + ", ".join(unresolved)
        )
    return template if template.endswith("\n") else template + "\n"


def _package_manifest(identity: dict[str, Any], source_run: Path, package_id: str, source_manifest_sha: str, package_manifest_sha: str, rows: list[dict[str, str]], records: dict[int, dict[str, Any]]) -> dict[str, Any]:
    images = []
    for row in rows:
        index = int(row["idx"])
        text = str(records[index].get("text") or "").strip().replace("\r\n", "\n")
        size = str(row.get("image_size") or "")
        width = height = None
        match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", size)
        if match:
            width, height = int(match.group(1)), int(match.group(2))
        images.append({
            "idx": index,
            "source_url": str(row["url"]),
            "path": row["_package_path"],
            "sha256": str(row["_declared_sha"]),
            "bytes": int(row["_declared_bytes"]),
            "width": width,
            "height": height,
            "size": size,
            "format": row["_format"],
            "download_status": "OK",
            "ocr_status": str(records[index].get("status") or ""),
            "ocr_chars": len(text),
            "ocr_text_sha256": _sha256_bytes(text.encode("utf-8")),
        })
    return {
        "manifest_version": "chat-materials-ocr-v2",
        "review_contract_version": _REVIEW_CONTRACT_VERSION,
        "package_id": package_id,
        "source_run_id": source_run.name,
        "original_url": identity["url"],
        "source_url_raw": identity.get("original_url", identity["url"]),
        "article_id": identity.get("article_id", ""),
        "captured_at": identity.get("captured_at", ""),
        "title": identity["title"],
        "account": identity["account"],
        "biz": identity["biz"],
        "published_at": identity["published_at"],
        "article_date": identity["article_date"],
        "content_hash": identity["content_hash"],
        "content_hash_note": "intake evidence hash; not a semantic or image-content hash",
        "source_manifest_sha256": source_manifest_sha,
        "manifest_sha256": package_manifest_sha,
        "source_intake_sha256": identity["intake_sha256"],
        "total_images": len(images),
        "ocr_status": "OCR_OK" if images else "OCR_NOT_APPLICABLE",
        "ocr_applicable": bool(images),
        "body_source_required": not images,
        "ocr_semantic_status": "MACHINE_TRANSCRIPT_NOT_SEMANTICALLY_VERIFIED" if images else "BODY_TEXT_NOT_SEMANTICALLY_VERIFIED",
        "body_file": "BODY.md",
        "ocr_file": "OCR_FULL.md",
        "image_directory": "images/" if images else "",
        "images": images,
    }


def _zip_bytes(files: Iterable[tuple[str, bytes]]) -> bytes:
    buffer = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in files:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise HandoffError(f"unsafe package archive path: {name}")
                info = zipfile.ZipInfo(name)
                info.date_time = (2020, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        buffer.seek(0)
        return buffer.read()
    finally:
        buffer.close()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def package_run(run_dir_value: object, out_dir_value: object, package_id_value: object,
                *, reading_mode: str = "OCR_RISK_REVIEW") -> dict[str, Any]:
    run_dir = validate_run_dir(run_dir_value)
    out_dir = _ensure_output_dir(out_dir_value, label="package output directory")
    if out_dir == run_dir:
        raise HandoffError("package output directory must be separate from source run")
    if reading_mode not in {"OCR_RISK_REVIEW", "FULL_ORIGINAL_REVIEW"}:
        raise HandoffError("unknown reading mode")
    package_id = _safe_package_id(package_id_value)
    identity = _identity_from_intake(run_dir)
    manifest_path, manifest_bytes, rows = _manifest_rows(run_dir, identity)
    raw_path = _run_file(run_dir, "wechat_article_raw.html", label="raw HTML")
    ocr_path = _run_file(run_dir, "windows_ocr_results.json", label="OCR records")
    snapshots = {p: _sha256_file(p) for p in (manifest_path, raw_path, ocr_path, Path(identity["intake_path"]))}
    source_manifest_sha = _sha256_bytes(manifest_bytes)
    csv_bytes = _package_manifest_csv(manifest_bytes, rows)
    manifest_sha = _sha256_bytes(csv_bytes)  # legacy field: image CSV only
    body = _body_with_markers(run_dir, rows)
    records, ocr_summary = _ocr_records(run_dir, rows)
    manifest_obj = _package_manifest(identity, run_dir, package_id, source_manifest_sha, manifest_sha, rows, records)
    body_bytes = _render_body(identity, body, rows, package_id, manifest_sha).encode("utf-8")
    ocr_bytes = _render_ocr(identity, rows, records, package_id, manifest_sha).encode("utf-8")
    source_files = [("BODY.md", body_bytes), ("OCR_FULL.md", ocr_bytes), ("manifest.csv", csv_bytes)]
    source_ids = ["BODY", "OCR_FULL", "IMAGE_MANIFEST"]
    for row in rows:
        data = _read_bytes(Path(row["_resolved_path"]), row["_package_path"])
        if _sha256_bytes(data) != row["_declared_sha"]:
            raise HandoffError("image changed during packaging")
        source_files.append((row["_package_path"], data))
        source_ids.append(f"IMAGE{int(row['idx']):03d}")
    identity_keys = ("original_url", "article_id", "title", "account", "biz", "published_at", "article_date", "content_hash", "source_run_id")
    descriptor = {
        "review_contract_version": _REVIEW_CONTRACT_VERSION,
        "identity": {k: manifest_obj[k] for k in identity_keys},
        "raw_html_sha256": snapshots[raw_path],
        "sources": [{"source_id": sid, "path": name, "bytes": len(data), "sha256": _sha256_bytes(data)}
                    for sid, (name, data) in zip(source_ids, source_files)],
    }
    input_digest = _sha256_bytes(_canonical_json(descriptor))
    manifest_obj.update(input_descriptor=descriptor, input_digest=input_digest,
                        reading_mode=reading_mode, task_version="wechat-research-v2")
    files = [
        ("README.md", _render_readme(identity, package_id, manifest_sha, run_dir, ocr_summary).encode("utf-8")),
        ("PROMPT.md", _render_prompt(identity, package_id, manifest_sha, input_digest, reading_mode).encode("utf-8")),
        ("manifest.json", (json.dumps(manifest_obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    ] + source_files
    if any(_sha256_file(path) != digest for path, digest in snapshots.items()):
        raise HandoffError("source changed during packaging; no snapshot published")
    zip_data = _zip_bytes(files)
    zip_name = f"wechat_chat_materials_{package_id}.zip"
    receipt = {
        "receipt_version": "wechat-chat-ocr-package-v2", "status": "PACKAGE_READY",
        "review_contract_version": _REVIEW_CONTRACT_VERSION,
        "package_id": package_id, "input_digest": input_digest, "reading_mode": reading_mode,
        "source_run_id": run_dir.name, "source_run": str(run_dir),
        "original_url": identity["url"], "article_date": identity["article_date"],
        "published_at": identity["published_at"], "source_manifest_sha256": source_manifest_sha,
        "manifest_sha256": manifest_sha, "source_intake_sha256": identity["intake_sha256"],
        "image_count": len(rows), "ocr_status": ocr_summary.get("status"),
        "ocr_processed": ocr_summary.get("processed_count"),
        "ocr_timeout": ocr_summary.get("timeout_count"), "ocr_error": ocr_summary.get("error_count"),
        "ocr_empty": ocr_summary.get("empty_count"),
        "zip": {"path": zip_name, "sha256": _sha256_bytes(zip_data), "bytes": len(zip_data)},
        "semantic_claim": ("MACHINE_TRANSCRIPT_NOT_SEMANTICALLY_VERIFIED" if rows
                            else "BODY_TEXT_NOT_SEMANTICALLY_VERIFIED_OCR_NOT_APPLICABLE"),
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    output_files = files + [(zip_name, zip_data), ("PACKAGE_RECEIPT.json", (json.dumps(receipt, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))]
    # Preflight all conflicts before publishing any new file.
    for name, data in output_files:
        path = out_dir / name
        _reject_symlink_components(path, name)
        if path.exists() and (not path.is_file() or _read_bytes(path, name) != data):
            raise HandoffError(f"existing package differs: {name}; use a new version/output directory")
    for name, data in output_files:
        _write_if_same(out_dir / name, data, label=name)
    return receipt


def _now_local_iso() -> str:
    tz = _dt.timezone(_dt.timedelta(hours=8))
    return _dt.datetime.now(tz).replace(microsecond=0).isoformat()


def _archive_versioned(out_dir: Path, base_name: str, data: bytes, *, label: str) -> tuple[str, str, bool]:
    """Archive bytes without overwriting; return filename, sha, idempotent."""

    digest = _sha256_bytes(data)
    base = out_dir / base_name
    if base.exists() or base.is_symlink():
        if base.is_file() and not base.is_symlink() and _read_bytes(base, label) == data:
            return base.name, digest, True
        path = Path(base_name)
        suffix = path.suffix
        stem = path.name[: -len(suffix)] if suffix else path.name
        index = 2
        while True:
            candidate = out_dir / f"{stem}.v{index}.{digest[:12]}{suffix}"
            if not candidate.exists() and not candidate.is_symlink():
                _write_if_same(candidate, data, label=candidate.name)
                return candidate.name, digest, False
            if candidate.is_file() and _read_bytes(candidate, label) == data:
                return candidate.name, digest, True
            index += 1
    _write_if_same(base, data, label=base_name)
    return base.name, digest, False


def _zip_member_names(archive: zipfile.ZipFile) -> set[str]:
    """Return safe ZIP member names and reject traversal/duplicate members."""

    names: set[str] = set()
    infos = archive.infolist()
    if len(infos) > 10000 or sum(i.file_size for i in infos) > 1024 * 1024 * 1024:
        raise HandoffError("package exceeds bounded archive limits")
    for info in infos:
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise HandoffError("package ZIP must not contain symlinks")
        name = str(info.filename)
        if not name or "\x00" in name or "\\" in name:
            raise HandoffError(f"unsafe package ZIP member: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise HandoffError(f"unsafe package ZIP member: {name!r}")
        if name in names:
            raise HandoffError(f"duplicate package ZIP member: {name}")
        names.add(name)
    return names


def _zip_json(archive: zipfile.ZipFile, name: str, *, label: str) -> dict[str, Any]:
    try:
        raw = archive.read(name)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise HandoffError(f"invalid {label} in package ZIP") from exc
    value = _json_no_duplicate_keys(raw, label=f"{label} in package ZIP")
    if not isinstance(value, dict):
        raise HandoffError(f"{label} in package ZIP must be a JSON object")
    return value


def _zip_manifest_rows(archive: zipfile.ZipFile, names: set[str], expected_count: int) -> tuple[bytes, list[dict[str, str]]]:
    if "manifest.csv" not in names:
        raise HandoffError("package ZIP is missing manifest.csv")
    try:
        manifest_bytes = archive.read("manifest.csv")
        reader = csv.DictReader(manifest_bytes.decode("utf-8-sig").splitlines())
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    except (KeyError, UnicodeError, csv.Error, zipfile.BadZipFile) as exc:
        raise HandoffError("package ZIP manifest.csv is invalid") from exc
    if not fieldnames or not {"idx", "sha256", "bytes"}.issubset(set(fieldnames)):
        raise HandoffError("package ZIP manifest.csv is missing required fields")
    path_field = "local_path" if "local_path" in fieldnames else "path" if "path" in fieldnames else ""
    if not path_field or len(rows) != expected_count:
        raise HandoffError("package ZIP manifest.csv count/path fields are invalid")
    for expected_index, row in enumerate(rows, start=1):
        try:
            index = int(str(row.get("idx") or ""))
            byte_count = int(str(row.get("bytes") or ""))
        except (TypeError, ValueError) as exc:
            raise HandoffError(f"package ZIP manifest.csv has invalid IMAGE{expected_index:03d} types") from exc
        if index != expected_index or byte_count <= 0:
            raise HandoffError("package ZIP manifest.csv rows are missing or out of order")
        digest = str(row.get("sha256") or row.get("image_sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(digest):
            raise HandoffError(f"package ZIP manifest.csv has invalid SHA at IMAGE{index:03d}")
        member = str(row.get(path_field) or "").strip()
        allowed_members = {f"images/IMAGE{index:03d}{ext}" for ext in (".jpg", ".jpeg", ".png", ".webp")}
        if member not in allowed_members or member not in names:
            raise HandoffError(f"package ZIP image path mismatch at IMAGE{index:03d}")
        try:
            image_bytes = archive.read(member)
        except (KeyError, zipfile.BadZipFile) as exc:
            raise HandoffError(f"package ZIP image is unreadable at IMAGE{index:03d}") from exc
        if len(image_bytes) != byte_count or _sha256_bytes(image_bytes) != digest:
            raise HandoffError(f"package ZIP image hash/bytes mismatch at IMAGE{index:03d}")
    return manifest_bytes, rows


def _validate_package_zip(package_zip: Path, *, source_run: Path, package_id: str,
                          declared_sha: str, observed_sha: str) -> dict[str, Any]:
    """Verify a frozen input; never compare it with the current run's OCR/body.

    The expected external ZIP SHA is the trust anchor. Recomputing the observed
    SHA alone proves no provenance. Legacy snapshots remain archivable but are
    not silently promoted to the v2 contract.
    """
    try:
        with zipfile.ZipFile(package_zip) as archive:
            names = _zip_member_names(archive)
            if not {"manifest.json", "manifest.csv", "BODY.md"}.issubset(names):
                raise HandoffError("package ZIP missing manifest/BODY")
            frozen_manifest_bytes = archive.read("manifest.json")
            manifest = _zip_json(archive, "manifest.json", label="manifest")
            embedded_id = str(manifest.get("package_id") or "")
            if embedded_id and embedded_id != package_id:
                raise HandoffError("package ZIP package_id mismatch")
            embedded_run = str(manifest.get("source_run_id") or "")
            if embedded_run and embedded_run != source_run.name:
                raise HandoffError("package ZIP source_run_id mismatch")
            image_count = manifest.get("total_images")
            if isinstance(image_count, bool) or not isinstance(image_count, int) or image_count < 0:
                raise HandoffError("package ZIP image count invalid")
            csv_bytes, rows = _zip_manifest_rows(archive, names, image_count)
            if image_count == 0 and any(name.startswith("images/") for name in names):
                raise HandoffError("zero-image package ZIP contains unmanifested image files")
            manifest_sha = _sha256_bytes(csv_bytes)
            if manifest.get("manifest_sha256") not in (None, "", manifest_sha):
                raise HandoffError("package image manifest digest mismatch")
            url = _canonical_url(manifest.get("original_url") or manifest.get("url"))
            if not url or (urlsplit(url).hostname or "") != "mp.weixin.qq.com":
                raise HandoffError("package article URL invalid")
            base = {
                "package_id_embedded": embedded_id, "article_url": url,
                "article_id": manifest.get("article_id", ""),
                "article_title": manifest.get("title", ""), "article_date": manifest.get("article_date", ""),
                "image_count": image_count, "content_hash": manifest.get("content_hash", ""),
                "package_manifest_sha256_observed": manifest_sha,
                "package_manifest_sha256_declared": manifest.get("manifest_sha256", ""),
                "package_manifest_sha256_status": "VERIFIED",
                "frozen_manifest_member": "manifest.json",
                "frozen_manifest_sha256_observed": _sha256_bytes(frozen_manifest_bytes),
                "review_contract_version": manifest.get("review_contract_version", ""),
                "reading_mode": manifest.get("reading_mode", "OCR_RISK_REVIEW"),
            }
            if manifest.get("manifest_version") != "chat-materials-ocr-v2":
                return {**base, "review_contract_version": "",
                        "frozen_identity_metadata_status": "NO_VERIFIED_FROZEN_PACKAGE",
                        "package_identity_status": "LEGACY_INPUT_UNVERIFIED",
                        "package_id_binding_status": "LEGACY_INPUT_UNVERIFIED", "input_digest": ""}
            if not embedded_id or not embedded_run or "OCR_FULL.md" not in names:
                raise HandoffError("v2 package requires package_id, source_run_id and OCR_FULL.md")
            if image_count == 0 and (
                    manifest.get("ocr_status") != "OCR_NOT_APPLICABLE" or
                    manifest.get("ocr_applicable") is not False or
                    manifest.get("body_source_required") is not True):
                raise HandoffError("zero-image v2 package lacks explicit OCR_NOT_APPLICABLE/body source status")
            descriptor = manifest.get("input_descriptor")
            if not isinstance(descriptor, dict):
                raise HandoffError("complete input descriptor is missing")
            manifest_has_review_contract = "review_contract_version" in manifest
            descriptor_has_review_contract = "review_contract_version" in descriptor
            if manifest_has_review_contract != descriptor_has_review_contract:
                raise HandoffError("review_contract_version must be bound in manifest and input_descriptor")
            review_contract_version = ""
            if manifest_has_review_contract:
                review_contract_version = manifest.get("review_contract_version")
                if review_contract_version != _REVIEW_CONTRACT_VERSION or descriptor.get("review_contract_version") != review_contract_version:
                    raise HandoffError("unsupported or unbound review_contract_version")
            digest = _sha256_bytes(_canonical_json(descriptor))
            if digest != manifest.get("input_digest"):
                raise HandoffError("input digest mismatch")
            did = descriptor.get("identity")
            immutable_descriptor_keys = (
                "original_url", "article_id", "title", "account", "biz",
                "published_at", "article_date", "content_hash", "source_run_id",
            )
            if not isinstance(did, dict) or any(
                    k not in did or k not in manifest or did.get(k) != manifest.get(k)
                    for k in immutable_descriptor_keys):
                raise HandoffError("input identity differs from manifest")
            sources = descriptor.get("sources")
            expected_ids = ["BODY", "OCR_FULL", "IMAGE_MANIFEST"] + [f"IMAGE{i:03d}" for i in range(1, image_count+1)]
            expected_paths = ["BODY.md", "OCR_FULL.md", "manifest.csv"] + [str(r.get("local_path") or r.get("path")) for r in rows]
            if not isinstance(sources, list) or len(sources) != len(expected_ids):
                raise HandoffError("complete input source list is missing")
            for sid, path, entry in zip(expected_ids, expected_paths, sources):
                if not isinstance(entry, dict) or entry.get("source_id") != sid or entry.get("path") != path or path not in names:
                    raise HandoffError("input source order/path mismatch")
                data = archive.read(path)
                if entry.get("bytes") != len(data) or entry.get("sha256") != _sha256_bytes(data):
                    raise HandoffError(f"input source content mismatch: {path}")
            images = manifest.get("images")
            if not isinstance(images, list) or len(images) != image_count:
                raise HandoffError("image descriptor list incomplete")
            for index, (row, entry) in enumerate(zip(rows, images), 1):
                if (not isinstance(entry, dict) or entry.get("idx") != index or
                        entry.get("path") != row.get("local_path") or entry.get("sha256") != row["sha256"] or
                        entry.get("bytes") != int(row["bytes"]) or entry.get("source_url") != row.get("url")):
                    raise HandoffError("image JSON/CSV mismatch")
            body = archive.read("BODY.md").decode("utf-8-sig")
            if [int(v) for v in _IMAGE_MARKER_RE.findall(body)] != list(range(1, image_count+1)):
                raise HandoffError("frozen BODY image order mismatch")
            ocr = archive.read("OCR_FULL.md").decode("utf-8-sig")
            boundaries = list(re.finditer(r"^=====IMAGE(\d{3})[^\n]*\n(.*?)\n=====END IMAGE\1=====", ocr, re.M | re.S))
            if len(boundaries) != image_count:
                raise HandoffError("frozen OCR boundaries incomplete")
            if image_count == 0 and "OCR_NOT_APPLICABLE" not in ocr:
                raise HandoffError("zero-image OCR_FULL.md must declare OCR_NOT_APPLICABLE")
            for index, match in enumerate(boundaries, 1):
                text = match.group(2).strip().replace("\r\n", "\n")
                if int(match.group(1)) != index or _sha256_bytes(text.encode("utf-8")) != images[index-1].get("ocr_text_sha256"):
                    raise HandoffError("frozen OCR text/order digest mismatch")
            current_identity = _identity_from_intake(source_run)
            package_identity = {
                "original_url": url,
                "article_id": manifest.get("article_id", ""),
                "title": manifest.get("title", ""),
                "account": manifest.get("account", ""),
                "biz": manifest.get("biz", ""),
                "published_at": manifest.get("published_at", ""),
                "article_date": manifest.get("article_date", ""),
                "content_hash": manifest.get("content_hash", ""),
                "image_count": image_count,
                "source_run_id": embedded_run,
            }
            current_package_identity = {
                "original_url": current_identity["url"],
                "article_id": current_identity["article_id"],
                "title": current_identity["title"],
                "account": current_identity["account"],
                "biz": current_identity["biz"],
                "published_at": current_identity["published_at"],
                "article_date": current_identity["article_date"],
                "content_hash": current_identity["content_hash"],
                "image_count": current_identity["image_count"],
                "source_run_id": source_run.name,
            }
            mismatches = [
                key for key in current_package_identity
                if package_identity[key] != current_package_identity[key]
            ]
            if mismatches:
                raise HandoffError(
                    "package ZIP immutable article identity differs from current source run: "
                    + ", ".join(mismatches)
                )
            verified = bool(declared_sha and declared_sha == observed_sha)
            frozen_metadata = ({
                "account": str(manifest.get("account") or ""),
                "biz": str(manifest.get("biz") or ""),
                "published_at": str(manifest.get("published_at") or ""),
                "frozen_identity_metadata_status": "VERIFIED_FROM_TRUSTED_FROZEN_MANIFEST",
            } if verified else {
                "frozen_identity_metadata_status": "UNTRUSTED_NO_TRUSTED_ZIP_SHA",
            })
            return {**base, **frozen_metadata, "input_digest": digest,
                    "package_identity_status": "VERIFIED" if verified else "UNVERIFIED_NO_TRUSTED_ZIP_HASH",
                    "package_id_binding_status": "VERIFIED" if verified else "UNVERIFIED_NO_TRUSTED_ZIP_HASH",
                    "review_contract_version": review_contract_version,
                    "package_ocr_source_status": "FROZEN_BYTES_VERIFIED_NOT_SEMANTIC_REVIEW"}
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError) as exc:
        raise HandoffError("package ZIP is unreadable or structurally invalid") from exc


def _binding_identity(source_run: Path, package_id_value: object, package_zip_value: object, package_sha_value: object) -> dict[str, Any]:
    package_id = _safe_package_id(package_id_value)
    declared_sha = str(package_sha_value or "").strip().lower()
    if declared_sha and not _SHA256_RE.fullmatch(declared_sha):
        raise HandoffError("package_sha256 must be a 64-character SHA-256")
    package_zip = _external_file(package_zip_value, label="package zip", required=False)
    observed_sha = _sha256_file(package_zip) if package_zip else ""
    if declared_sha and observed_sha and declared_sha != observed_sha:
        raise HandoffError("package zip SHA-256 does not match explicit trusted package_sha256")
    if package_zip:
        validated = _validate_package_zip(package_zip, source_run=source_run, package_id=package_id,
                                          declared_sha=declared_sha, observed_sha=observed_sha)
        if _sha256_file(package_zip) != observed_sha:
            raise HandoffError("package ZIP changed during identity verification")
    else:
        identity = _identity_from_intake(source_run)
        validated = {
            "article_url": identity["url"], "article_title": identity["title"],
            "article_date": identity["article_date"], "image_count": identity["image_count"],
            "content_hash": identity["content_hash"], "input_digest": "",
            "review_contract_version": "",
            "frozen_identity_metadata_status": "NO_VERIFIED_FROZEN_PACKAGE",
            "package_identity_status": "UNVERIFIED_NO_PACKAGE_ZIP", "package_id_embedded": "",
            "package_id_binding_status": "UNVERIFIED_NO_PACKAGE_ZIP",
            "package_manifest_sha256_observed": "", "package_manifest_sha256_declared": "",
            "reading_mode": "OCR_RISK_REVIEW",
        }
    return {
        "source_run_id": source_run.name, "source_run": str(source_run), "package_id": package_id,
        "package_zip": str(package_zip) if package_zip else "",
        "package_sha256_declared": declared_sha, "package_sha256_observed": observed_sha,
        "package_sha256_status": "VERIFIED" if declared_sha and observed_sha else "UNVERIFIED",
        **validated,
    }


def _expected_source_indices(image_count: int) -> set[str]:
    return {"BODY", *(f"IMAGE{index:03d}" for index in range(1, image_count + 1))}


def _csv_return_rows(data: bytes, *, label: str, required_headers: set[str]) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise HandoffError(f"{label} is not valid UTF-8 CSV") from exc
    if not headers or len(headers) != len(set(headers)) or not required_headers.issubset(set(headers)):
        raise HandoffError(f"{label} is missing required headers")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise HandoffError(f"{label} has malformed rows")
    return headers, rows


def _check_source_index(value: object, expected_sources: set[str], *, label: str) -> str:
    source_index = str(value or "").strip().upper()
    if source_index not in expected_sources:
        raise HandoffError(f"{label} has invalid source_index: {source_index!r}")
    return source_index


def _check_counts(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise HandoffError(f"{label} must be an object of integer counts")
    counts: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise HandoffError(f"{label} contains a non-negative integer count violation")
        counts[key] = raw
    return counts


def _validate_event_dispositions(
    summary: dict[str, Any], *, coverage_rows: list[dict[str, str]] | None,
    binding: dict[str, Any],
) -> str:
    """Validate source-index dispositions only when a trusted frozen package requires them."""
    if binding.get("package_identity_status") != "VERIFIED":
        return "NOT_RUN_UNTRUSTED_FROZEN_PACKAGE"
    if binding.get("review_contract_version") != _REVIEW_CONTRACT_VERSION:
        return "NOT_RUN_LEGACY_PACKAGE"
    if summary.get("review_contract_version") != _REVIEW_CONTRACT_VERSION:
        raise HandoffError("summary.json review_contract_version does not match trusted frozen package")
    if coverage_rows is None:
        raise HandoffError("event_dispositions requires validated coverage.csv")
    dispositions = summary.get("event_dispositions")
    if not isinstance(dispositions, dict):
        raise HandoffError("summary.json event_dispositions must be a source_index mapping")
    event_sources = {row["source_index"] for row in coverage_rows if row["event"] == "EVENT"}
    disposition_sources = set(dispositions)
    if disposition_sources != event_sources:
        missing = sorted(event_sources - disposition_sources)
        extra = sorted(disposition_sources - event_sources)
        raise HandoffError(
            "summary.json event_dispositions must cover EVENT source_index values exactly once "
            f"(missing={missing}, non_event_or_unknown={extra})"
        )
    for source_index, disposition in dispositions.items():
        if not isinstance(source_index, str) or not isinstance(disposition, str) or disposition not in _EVENT_DISPOSITIONS:
            raise HandoffError(f"summary.json event_dispositions has invalid decision at {source_index!r}")
    return "PASS"


def _validate_structured_returns(
    structured_data: dict[str, bytes], *, binding: dict[str, Any], report_data: bytes = b"",
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Validate v2 syntax, bindings and arithmetic only, never research truth.

    Process CSVs before the summary regardless of caller dictionary order.
    Failed artifacts are still archived unchanged by the importer.
    """
    image_count = int(binding["image_count"])
    expected_sources = _expected_source_indices(image_count)
    results: dict[str, dict[str, Any]] = {}
    coverage_rows: list[dict[str, str]] | None = None
    mention_rows: list[dict[str, str]] | None = None
    coverage_counts: dict[str, int] | None = None
    mention_counts: dict[str, int] | None = None
    for key in ("coverage", "mentions", "unmapped", "summary"):
        if key not in structured_data:
            continue
        data = structured_data[key]
        try:
            detail: dict[str, Any] = {}
            if key == "coverage":
                _, rows = _csv_return_rows(data, label="coverage.csv", required_headers=_COVERAGE_HEADERS)
                ordered = ["BODY"] + [f"IMAGE{i:03d}" for i in range(1, image_count+1)]
                if [r["source_index"] for r in rows] != ordered:
                    raise HandoffError("coverage.csv must contain BODY then IMAGE001..N exactly once")
                for row in rows:
                    sid = row["source_index"]
                    if row["event"] not in {"EVENT", "NO_EVENT", "UNREADABLE"}:
                        raise HandoffError(f"coverage.csv invalid event at {sid}")
                    checked, scope, text_read = row["original_checked"], row["original_scope"], row["text_read"]
                    if checked not in {"true", "false", "unreadable"} or text_read not in {"true", "false"}:
                        raise HandoffError(f"coverage.csv invalid reading fields at {sid}")
                    if sid == "BODY":
                        if checked != "false" or scope != "NOT_APPLICABLE":
                            raise HandoffError("BODY uses text_read, not image review")
                    elif scope not in {"FULL", "PARTIAL", "NONE"} or ((checked == "true") != (scope in {"FULL", "PARTIAL"})):
                        raise HandoffError(f"coverage.csv original_checked/scope mismatch at {sid}")
                    if (checked == "unreadable" or row["event"] == "UNREADABLE") and not row["uncertainty"].strip():
                        raise HandoffError(f"unreadable source requires a reason: {sid}")
                    if row["event"] != "UNREADABLE" and text_read != "true" and checked != "true":
                        raise HandoffError(f"source has no declared reading: {sid}")
                    if row["event"] in {"EVENT", "NO_EVENT"} and not row["claim"].strip():
                        raise HandoffError(f"event/no-event requires a short excerpt or reason: {sid}")
                coverage_rows = rows
                coverage_counts = {"total": len(rows), **{tag: sum(r["event"] == tag for r in rows) for tag in ("EVENT", "NO_EVENT", "UNREADABLE")}}
                detail["recomputed_counts"] = coverage_counts
                detail["self_reported_visual_full"] = sum(r["original_scope"] == "FULL" for r in rows)
                detail["self_reported_visual_partial"] = sum(r["original_scope"] == "PARTIAL" for r in rows)
            elif key == "mentions":
                _, rows = _csv_return_rows(data, label="mentions.csv", required_headers=_MENTIONS_HEADERS)
                names_by_entity: dict[str, str] = {}
                entities_by_code: dict[tuple[str, str], str] = {}
                seen: set[tuple[str, str, str, str]] = set()
                for row in rows:
                    sid = _check_source_index(row["source_index"], expected_sources, label="mentions.csv")
                    if any(not row[k].strip() for k in ("name", "mapping_status", "entity_id", "claim_context")):
                        raise HandoffError(f"mentions.csv empty required field at {sid}")
                    market, code = row["market"], row["code"]
                    patterns = {"A": r"[0-9]{6}\.(SH|SZ)", "BJ": r"[0-9]{6}\.BJ", "HK": r"[0-9]{5}\.HK"}
                    if market not in patterns or not re.fullmatch(patterns[market], code):
                        raise HandoffError(f"mentions.csv invalid market/code format at {sid}; unresolved names belong in unmapped.csv")
                    if row["source_named_or_derived"] not in {"SOURCE_NAMED", "RESEARCHER_DERIVED"}:
                        raise HandoffError(f"mentions.csv invalid company provenance at {sid}")
                    origin = row["listing_origin"]
                    if origin not in {"SOURCE_CODE", "NAME_RESOLVED", "SUPPLEMENTAL_LISTING", "RESEARCH_DERIVED"}:
                        raise HandoffError(f"mentions.csv invalid listing_origin at {sid}")
                    if (origin == "RESEARCH_DERIVED") != (row["source_named_or_derived"] == "RESEARCHER_DERIVED"):
                        raise HandoffError(f"mentions.csv company/listing provenance contradiction at {sid}")
                    if row["source_named_or_derived"] == "SOURCE_NAMED" and not row["source_name"].strip():
                        raise HandoffError(f"mentions.csv source name missing at {sid}")
                    entity = row["entity_id"]
                    if entity in names_by_entity and names_by_entity[entity] != row["name"]:
                        raise HandoffError("same entity_id has inconsistent canonical company names")
                    names_by_entity[entity] = row["name"]
                    if (market, code) in entities_by_code and entities_by_code[(market, code)] != entity:
                        raise HandoffError("same security is assigned to different entities")
                    entities_by_code[(market, code)] = entity
                    occurrence = (sid, entity, market, code)
                    if occurrence in seen:
                        raise HandoffError("duplicate source/company/listing row; combine its excerpts")
                    seen.add(occurrence)
                mention_rows = rows
                mention_counts = {
                    "total": len(rows), **{m: sum(r["market"] == m for r in rows) for m in ("A", "BJ", "HK")},
                    "entities": len(names_by_entity),
                    "source_named_entities": len({r["entity_id"] for r in rows if r["source_named_or_derived"] == "SOURCE_NAMED"}),
                    "supplemental_listing_rows": sum(r["listing_origin"] == "SUPPLEMENTAL_LISTING" for r in rows),
                }
                detail["recomputed_counts"] = mention_counts
                detail["issuer_mapping_independently_verified"] = False
            elif key == "unmapped":
                _, rows = _csv_return_rows(data, label="unmapped.csv", required_headers=_UNMAPPED_HEADERS)
                for row in rows:
                    if not row["name"].strip() or not row["reason"].strip():
                        raise HandoffError("unmapped.csv requires nonempty name/reason")
                    _check_source_index(row["source_index"], expected_sources, label="unmapped.csv")
                detail["recomputed_count"] = len(rows)
            else:
                summary = _json_no_duplicate_keys(data, label="summary.json")
                if not isinstance(summary, dict) or not _SUMMARY_FIELDS.issubset(summary):
                    raise HandoffError("summary.json missing v2 identity/status fields; legacy bytes may be archived but not upgraded")
                if type(summary["schema_version"]) is not int or summary["schema_version"] != 2:
                    raise HandoffError("summary.json requires schema_version=2")
                if "chat_report_status" in summary:
                    raise HandoffError("summary.json must use status")
                if _canonical_url(summary["url"]) != binding["article_url"] or summary["package_id"] != binding["package_id"]:
                    raise HandoffError("summary.json URL/package_id mismatch")
                if (not _SHA256_RE.fullmatch(str(summary["input_digest"])) or
                        summary["input_digest"] != binding.get("input_digest")):
                    raise HandoffError("summary.json input_digest mismatch/unverified")
                if summary["manifest_sha256"] != binding.get("package_manifest_sha256_observed"):
                    raise HandoffError("summary.json image manifest digest mismatch")
                if summary["article_date"] != binding["article_date"] or type(summary["image_count"]) is not int or summary["image_count"] != image_count:
                    raise HandoffError("summary.json date/image_count mismatch")
                for safety in ("production_allowed", "buy_gate_updated", "orders_sent"):
                    if summary[safety] is not False:
                        raise HandoffError(f"summary.json {safety} must be boolean false")
                for counts_key, recomputed in (("coverage_counts", coverage_counts), ("mentions_counts", mention_counts)):
                    counts = _check_counts(summary[counts_key], label=counts_key)
                    if recomputed is None or counts != recomputed:
                        raise HandoffError(f"summary.json {counts_key} differs from recomputed CSV counts")
                status = summary["status"]
                if status not in _CHAT_SUMMARY_STATUS_ALLOWED:
                    raise HandoffError("summary.json status cannot claim independent verification/local acceptance")
                missing = summary["missing_inputs"]
                if not isinstance(missing, list) or any(not isinstance(v, str) for v in missing):
                    raise HandoffError("summary.json missing_inputs must be a string list")
                event_dispositions_status = _validate_event_dispositions(
                    summary, coverage_rows=coverage_rows, binding=binding,
                )
                mode = summary["reading_mode"]
                if mode not in {"OCR_RISK_REVIEW", "FULL_ORIGINAL_REVIEW"}:
                    raise HandoffError("unknown reading mode")
                if binding.get("reading_mode") == "FULL_ORIGINAL_REVIEW" and mode != "FULL_ORIGINAL_REVIEW":
                    raise HandoffError("cannot downgrade the frozen reading-mode requirement")
                if status == "COMPLETE_WITH_ALL_SOURCES":
                    if missing or not coverage_rows or any(r["event"] == "UNREADABLE" or r["original_checked"] == "unreadable" for r in coverage_rows):
                        raise HandoffError("complete claim contradicts missing/unreadable sources")
                    if mode == "FULL_ORIGINAL_REVIEW" and any(r["source_index"] != "BODY" and r["original_scope"] != "FULL" for r in coverage_rows):
                        raise HandoffError("full-original review claim lacks full original coverage")
                    if mode == "OCR_RISK_REVIEW" and any(r["text_read"] != "true" for r in coverage_rows):
                        raise HandoffError("OCR primary reading requires complete text reading")
                rid = _safe_package_id(summary["return_id"])
                try:
                    report_text = report_data.decode("utf-8-sig")
                    marker = re.match(r"^<!-- wechat-return: (\{[^\n]+\}) -->\r?\n", report_text)
                    header = json.loads(marker.group(1)) if marker else None
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise HandoffError("report binding header invalid") from exc
                if not isinstance(header, dict) or any(header.get(k) != summary[k] for k in ("package_id", "input_digest", "return_id")):
                    raise HandoffError("report header does not bind this input and return_id")
                if not report_text[marker.end():].strip():
                    raise HandoffError("report body is empty")
                hashes = summary["artifact_sha256"]
                payloads = {"report.md": report_data, **{f"{k}.csv": structured_data[k] for k in ("coverage", "mentions", "unmapped") if k in structured_data}}
                if not isinstance(hashes, dict) or set(hashes) != set(payloads) or len(payloads) != 4:
                    raise HandoffError("summary artifact hashes must bind report and three CSV originals")
                if any(hashes[name] != _sha256_bytes(payload) for name, payload in payloads.items()):
                    raise HandoffError("mixed/changed returned file bytes")
                detail.update(return_id=rid, chat_claimed_complete=(status == "COMPLETE_WITH_ALL_SOURCES"),
                              recomputed_coverage_counts=coverage_counts, recomputed_mentions_counts=mention_counts,
                              package_id_status=binding.get("package_identity_status"),
                              review_contract_version=binding.get("review_contract_version") or "LEGACY_UNVERSIONED",
                              event_dispositions_contract_status=event_dispositions_status)
            results[key] = {"valid": True, "validation_status": "VALIDATED", **detail}
        except (HandoffError, TypeError, ValueError) as exc:
            results[key] = {"valid": False, "validation_status": "INVALID", "error": str(exc)}
    return results, [key for key, value in results.items() if not value["valid"]]


def import_chat_return(
    *,
    source_run_value: object,
    package_id_value: object,
    package_zip_value: object,
    package_sha_value: object,
    report_value: object,
    coverage_value: object,
    mentions_value: object,
    unmapped_value: object,
    summary_value: object,
    out_dir_value: object,
) -> dict[str, Any]:
    source_run = validate_run_dir(source_run_value)
    out_dir = _ensure_output_dir(out_dir_value, label="Chat return archive directory")
    binding = _binding_identity(source_run, package_id_value, package_zip_value, package_sha_value)
    inputs = {
        "report": report_value,
        "coverage": coverage_value,
        "mentions": mentions_value,
        "unmapped": unmapped_value,
        "summary": summary_value,
    }
    archived: dict[str, dict[str, Any]] = {}
    structured_data: dict[str, bytes] = {}
    report_data = b""
    missing: list[str] = []
    base_names = {
        "report": "report.md",
        "coverage": "coverage.csv",
        "mentions": "mentions.csv",
        "unmapped": "unmapped.csv",
        "summary": "summary.json",
    }
    for key, value in inputs.items():
        path = _external_file(value, label=f"{key} result", required=False)
        if path is None:
            missing.append(base_names[key])
            continue
        data = _read_bytes(path, f"{key} result")
        if not data:
            raise HandoffError(f"{key} result is empty")
        if key == "report":
            report_data = data
        else:
            structured_data[key] = data
        destination_name, digest, idempotent = _archive_versioned(out_dir, base_names[key], data, label=base_names[key])
        archived[key] = {
            "input_path": str(path),
            "original_filename": path.name,
            "archived_filename": destination_name,
            "bytes": len(data),
            "sha256": digest,
            "content_id": f"sha256:{digest}",
            "idempotent": idempotent,
            "received_at": _now_local_iso(),
        }
    if "report" not in archived:
        raise HandoffError("report result is required")
    structured_results, invalid_keys = _validate_structured_returns(structured_data, binding=binding, report_data=report_data)
    for key, result in structured_results.items():
        if key in archived:
            archived[key]["validation_status"] = result.get("validation_status", "INVALID")
            if result.get("error"):
                archived[key]["validation_error"] = result["error"]
    invalid_artifacts = [base_names[key] for key in invalid_keys]
    required_outputs = ["coverage.csv", "mentions.csv", "unmapped.csv", "summary.json"]
    if missing and invalid_artifacts:
        status = "REPORT_WITH_STRUCTURED_PARTIAL"
        structured_validation_status = "PARTIAL"
    elif missing:
        status = "REPORT_ONLY_ARCHIVED"
        structured_validation_status = "MISSING"
    elif invalid_artifacts:
        status = "REPORT_AND_STRUCTURED_INVALID"
        structured_validation_status = "INVALID"
    elif binding.get("package_identity_status") != "VERIFIED":
        status = "REPORT_WITH_STRUCTURED_UNBOUND"
        structured_validation_status = "SYNTAX_ONLY_UNBOUND"
    else:
        status = "REPORT_AND_STRUCTURED_ARCHIVED"
        structured_validation_status = "COMPLETE"
    summary_validation = structured_results.get("summary", {})
    if binding.get("package_identity_status") != "VERIFIED":
        event_dispositions_receipt_status = "NOT_RUN_UNTRUSTED_FROZEN_PACKAGE"
    elif not binding.get("review_contract_version"):
        event_dispositions_receipt_status = "NOT_RUN_LEGACY_PACKAGE"
    elif "summary" not in structured_data:
        event_dispositions_receipt_status = "NOT_RUN_MISSING_SUMMARY"
    elif summary_validation.get("valid"):
        event_dispositions_receipt_status = summary_validation.get("event_dispositions_contract_status", "NOT_RUN")
    else:
        event_dispositions_receipt_status = "INVALID"
    manifest = {
        "receipt_version": "wechat-chat-return-v2",
        "status": status,
        "binding": binding,
        "review_contract_version": binding.get("review_contract_version") or "LEGACY_UNVERSIONED",
        "event_dispositions_contract_status": event_dispositions_receipt_status,
        "report_origin": "USER_PROVIDED_CHAT_RETURN",
        "report_package_relationship": "This report was supplied by the user and was not generated by the package command; package_id is an explicit binding identity and embedded package verification status is recorded in binding.",
        "received_at": _now_local_iso(),
        "archived_files": archived,
        "missing_artifacts": missing,
        "invalid_artifacts": invalid_artifacts,
        "required_return_files": required_outputs,
        "structured_validation_status": structured_validation_status,
        "validation_details": structured_results,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "local_acceptance": {
            "report_bytes_archived": True,
            "bytes_archived": True,
            "input_binding_valid": binding.get("package_identity_status") == "VERIFIED" and structured_results.get("summary", {}).get("valid", False),
            "structure_valid": not missing and not invalid_artifacts,
            "chat_claimed_complete": structured_results.get("summary", {}).get("chat_claimed_complete", False),
            "independent_review_scope": [],
            "structured_files_complete": not missing and not invalid_artifacts,
            "structured_validation_status": structured_validation_status,
            "event_dispositions_contract_status": event_dispositions_receipt_status,
            "chat_self_reported_numbers_accepted": False,
            "semantic_research_accepted": False,
            "research_boundary": "RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE",
        },
    }
    manifest_path = out_dir / "IMPORT_RECEIPT.json"
    receipt_candidates: list[Path] = []
    if manifest_path.exists() and not manifest_path.is_symlink():
        receipt_candidates.append(manifest_path)
    receipt_candidates.extend(
        candidate
        for candidate in sorted(out_dir.glob("IMPORT_RECEIPT.v*.json"))
        if candidate.is_file() and not candidate.is_symlink()
    )
    for candidate in receipt_candidates:
        try:
            existing_obj = json.loads(_read_bytes(candidate, candidate.name).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(existing_obj, dict):
            continue
        if (
            existing_obj.get("binding") == binding
            and existing_obj.get("missing_artifacts") == missing
            and existing_obj.get("invalid_artifacts", []) == invalid_artifacts
            and existing_obj.get("status") == status
            and existing_obj.get("structured_validation_status") == structured_validation_status
        ):
            previous_files = existing_obj.get("archived_files")
            if isinstance(previous_files, dict) and set(previous_files) == set(archived) and all(
                isinstance(previous_files.get(key), dict)
                and previous_files[key].get("sha256") == archived[key].get("sha256")
                and previous_files[key].get("validation_status", "VALIDATED") == archived[key].get("validation_status", "VALIDATED")
                for key in archived
            ):
                return existing_obj
    receipt_name = "IMPORT_RECEIPT.json"
    if manifest_path.exists() and not manifest_path.is_symlink():
        # A different return is a new immutable receipt version.  Keep the
        # original receipt and never rewrite it in place.
        candidate_payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        receipt_name = f"IMPORT_RECEIPT.v2.{_sha256_bytes(candidate_payload)[:12]}.json"
        manifest["receipt_filename"] = receipt_name
        payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_if_same(out_dir / receipt_name, payload, label=receipt_name)
        return manifest
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_if_same(manifest_path, payload, label="IMPORT_RECEIPT.json")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地微信 OCR → Chat 资料包与回传归档工具")
    sub = parser.add_subparsers(dest="command", required=True)
    package = sub.add_parser("package", help="校验现有 run 并生成 OCR Chat 资料包")
    package.add_argument("--run-dir", required=True)
    package.add_argument("--out-dir", required=True)
    package.add_argument("--package-id", required=True)
    package.add_argument("--reading-mode", choices=["OCR_RISK_REVIEW", "FULL_ORIGINAL_REVIEW"], default="OCR_RISK_REVIEW")

    archive = sub.add_parser("import", help="按明确 source run/package identity 归档用户回传")
    archive.add_argument("--source-run", required=True)
    archive.add_argument("--package-id", required=True)
    archive.add_argument("--package-zip", default="")
    archive.add_argument("--package-sha256", default="")
    archive.add_argument("--report", required=True)
    archive.add_argument("--coverage", default="")
    archive.add_argument("--mentions", default="")
    archive.add_argument("--unmapped", default="")
    archive.add_argument("--summary", default="")
    archive.add_argument("--out-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "package":
            receipt = package_run(args.run_dir, args.out_dir, args.package_id, reading_mode=args.reading_mode)
        else:
            receipt = import_chat_return(
                source_run_value=args.source_run,
                package_id_value=args.package_id,
                package_zip_value=args.package_zip,
                package_sha_value=args.package_sha256,
                report_value=args.report,
                coverage_value=args.coverage,
                mentions_value=args.mentions,
                unmapped_value=args.unmapped,
                summary_value=args.summary,
                out_dir_value=args.out_dir,
            )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except (HandoffError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
