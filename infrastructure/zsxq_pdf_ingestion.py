"""Bounded PDF download and local page OCR derived from an existing ZSXQ run.

This module consumes the exact owned hourly status and its three original
source files. It never fetches topics or modifies that source run.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore
from infrastructure.owned_path import resolve_owned_path


SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_PAGE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_ATTEMPTS = 2
RENDER_SCALE_TO = 2600
DEFAULT_CLI = Path(
    "/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/"
    "shared-research-runtime/npm/node_modules/.bin/zsxq-cli"
)
DEFAULT_PDFINFO = Path(
    "/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/bin/override/pdfinfo"
)
DEFAULT_PDFTOPPM = Path(
    "/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/"
    "dependencies/bin/override/pdftoppm"
)
VISION_OCR_SOURCE = Path(
    "/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/"
    "scripts/wechat_macos_ocr.py"
)
STATE_RELATIVE = "external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json"
LOCK_RELATIVE = "external_sources/zsxq_hourly/.zsxq_pdf_ingestion.lock"
SAFETY = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
Runner = Callable[..., subprocess.CompletedProcess[str]]
PageCounter = Callable[[Path], int]
PageRenderer = Callable[[Path, int, Path], Path]
OCRPage = Callable[[Path], Mapping[str, Any]]
MetadataLookup = Callable[[Path, str], Mapping[str, Any]]
URLLookup = Callable[[Path, str], str]
BytesDownloader = Callable[[str, int], bytes]


class ZsxqPdfError(ValueError):
    """A stable, safe-to-record ingestion error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def _iso(value: datetime | None = None) -> str:
    stamp = value or _now()
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return stamp.astimezone(SHANGHAI).isoformat(timespec="seconds")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except (TypeError, ValueError) as error:
        raise ZsxqPdfError("TRADE_DATE_INVALID") from error
    return value


def _safe_run_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ZsxqPdfError("SOURCE_RUN_ID_INVALID")
    return value


def _json_read(store: NativeDataStore, relative: str) -> dict[str, Any]:
    try:
        value = store._read(relative)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ZsxqPdfError("SOURCE_JSON_UNREADABLE") from error
    if not isinstance(value, dict):
        raise ZsxqPdfError("SOURCE_JSON_INVALID")
    return value


def _source_binding(
    store: NativeDataStore,
    *,
    trade_date: str,
    slot: str,
    source_run_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    _date(trade_date)
    _safe_run_id(source_run_id)
    if not re.fullmatch(r"(?:0830|(?:0[9]|1[0-9]|2[0-3])00)", slot or ""):
        raise ZsxqPdfError("SOURCE_SLOT_INVALID")
    status_relative = (
        f"research_module/runtime_outputs/zsxq_hourly/{trade_date}/{slot}/"
        f"v35_zsxq_hourly_status_{trade_date}_{slot}.json"
    )
    status = _json_read(store, status_relative)
    if (
        status.get("trade_date") != trade_date
        or str(status.get("slot")) != slot
        or status.get("latest_run_id") != source_run_id
        or status.get("fetch_ok") is not True
        or status.get("status") not in {"READY", "READY_EMPTY"}
    ):
        raise ZsxqPdfError("SOURCE_STATUS_BINDING_MISMATCH")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if status.get(key) is not False:
            raise ZsxqPdfError("SOURCE_SAFETY_BOUNDARY_MISSING")

    run_relative = f"external_sources/zsxq_hourly/{source_run_id}"
    if (status.get("paths") or {}).get("run_dir") != run_relative:
        raise ZsxqPdfError("SOURCE_RUN_PATH_MISMATCH")
    fetch_relative = f"{run_relative}/zsxq_recent_topics_fetch_result.json"
    recent_relative = f"{run_relative}/zsxq_recent_topics.json"
    summary_relative = f"{run_relative}/zsxq_summary.json"
    fetch_result = _json_read(store, fetch_relative)
    recent = _json_read(store, recent_relative)
    summary = _json_read(store, summary_relative)
    if fetch_result.get("success") is not True or recent.get("success") is not True:
        raise ZsxqPdfError("SOURCE_FETCH_NOT_READY")
    for payload in (fetch_result, summary):
        for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            if payload.get(key) is not False:
                raise ZsxqPdfError("SOURCE_SAFETY_BOUNDARY_MISSING")

    hashes: dict[str, str] = {}
    for label, relative in (
        ("status", status_relative),
        ("fetch_result", fetch_relative),
        ("recent_topics", recent_relative),
        ("summary", summary_relative),
    ):
        raw = store._io.read_bytes(relative)
        hashes[label] = _sha256(raw)
    return status, fetch_result, recent, summary, hashes


def enumerate_pdf_documents(
    recent_topics: Mapping[str, Any], *, trade_date: str, source_run_id: str
) -> list[dict[str, Any]]:
    """Enumerate every raw topics_brief.files reference, including noise topics."""
    topics = recent_topics.get("topics_brief")
    if not isinstance(topics, list):
        raise ZsxqPdfError("RAW_TOPICS_MISSING")
    documents: list[dict[str, Any]] = []
    for topic in topics:
        if not isinstance(topic, Mapping):
            continue
        group = topic.get("group") if isinstance(topic.get("group"), Mapping) else {}
        group_id = str(group.get("group_id") or "").strip()
        topic_id = str(topic.get("topic_id") or topic.get("id") or "").strip()
        if not group_id or not topic_id:
            continue
        files = topic.get("files") or []
        if not isinstance(files, list):
            continue
        for raw_file in files:
            if not isinstance(raw_file, Mapping):
                continue
            name = str(raw_file.get("name") or "")
            if Path(name).suffix.lower() != ".pdf":
                continue
            file_id = str(raw_file.get("file_id") or "").strip()
            if not re.fullmatch(r"[0-9]{1,32}", file_id):
                continue
            try:
                size = int(raw_file.get("size"))
            except (TypeError, ValueError):
                size = 0
            binding = "\n".join((trade_date, source_run_id, group_id, topic_id, file_id))
            documents.append(
                {
                    "document_key": _sha256(binding.encode("utf-8")),
                    "trade_date": trade_date,
                    "source_run_id": source_run_id,
                    "group_id": group_id,
                    "group_name": str(group.get("name") or ""),
                    "topic_id": topic_id,
                    "topic_title": str(topic.get("title") or ""),
                    "source_topic_published_at": topic.get("create_time"),
                    "file_id": file_id,
                    "original_filename": name,
                    "expected_size": size,
                    "source_hash_raw": raw_file.get("hash"),
                    "source_hash_algorithm": None,
                    "file_created_at": raw_file.get("create_time"),
                    "file_source": raw_file.get("source"),
                    "pdf_published_at": None,
                    "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT",
                    "data_role": "CURRENT_KNOWLEDGE_SUPPLEMENT",
                    "late_processing": True,
                }
            )
    if len({row["document_key"] for row in documents}) != len(documents):
        raise ZsxqPdfError("SOURCE_DOCUMENT_IDENTITY_DUPLICATE")
    return documents


def verify_pdf_bytes(raw: bytes, expected_size: int, *, max_bytes: int = MAX_PDF_BYTES) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise ZsxqPdfError("PDF_BYTES_EMPTY")
    if len(raw) > max_bytes:
        raise ZsxqPdfError("PDF_SIZE_LIMIT_EXCEEDED")
    if expected_size <= 0 or len(raw) != expected_size:
        raise ZsxqPdfError("PDF_SIZE_MISMATCH")
    if not raw.startswith(b"%PDF-"):
        raise ZsxqPdfError("PDF_MAGIC_INVALID")
    return _sha256(raw)


def _cli_json(cli: Path, args: list[str], *, process_runner: Runner) -> dict[str, Any]:
    command = [str(cli), *args]
    try:
        completed = process_runner(
            command,
            timeout=30,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ZsxqPdfError("ZSXQ_API_TIMEOUT") from error
    except OSError as error:
        raise ZsxqPdfError("ZSXQ_API_UNAVAILABLE") from error
    if completed.returncode != 0:
        raise ZsxqPdfError("ZSXQ_API_CALL_FAILED")
    try:
        value = json.loads((completed.stdout or "").lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise ZsxqPdfError("ZSXQ_API_JSON_INVALID") from error
    if not isinstance(value, dict) or value.get("success") is not True:
        raise ZsxqPdfError("ZSXQ_API_RESPONSE_INVALID")
    return value


def _cli_file_metadata(cli: Path, file_id: str, *, process_runner: Runner = subprocess.run) -> Mapping[str, Any]:
    payload = _cli_json(
        cli,
        ["api", "raw", "--method", "GET", "--path", f"/v2/files/{file_id}"],
        process_runner=process_runner,
    )
    file_row = (((payload.get("body") or {}).get("resp_data") or {}).get("file"))
    if not isinstance(file_row, Mapping):
        raise ZsxqPdfError("ZSXQ_FILE_METADATA_MISSING")
    return file_row


def _cli_download_url(cli: Path, file_id: str, *, process_runner: Runner = subprocess.run) -> str:
    payload = _cli_json(
        cli,
        ["api", "raw", "--method", "GET", "--path", f"/v2/files/{file_id}/download_url"],
        process_runner=process_runner,
    )
    url = (((payload.get("body") or {}).get("resp_data") or {}).get("download_url"))
    if not isinstance(url, str):
        raise ZsxqPdfError("ZSXQ_DOWNLOAD_URL_MISSING")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ZsxqPdfError("ZSXQ_DOWNLOAD_URL_UNSAFE")
    return url


class _HttpsRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, message: str, headers: Any, new_url: str) -> Request | None:
        if urlsplit(new_url).scheme != "https":
            raise ZsxqPdfError("DOWNLOAD_REDIRECT_DOWNGRADE")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def _download_pdf_bytes(url: str, expected_size: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ZsxqPdfError("ZSXQ_DOWNLOAD_URL_UNSAFE")
    request = Request(url, headers={"User-Agent": "v4-zsxq-pdf-ingestion/1"}, method="GET")
    opener = build_opener(_HttpsRedirectHandler())
    try:
        with opener.open(request, timeout=60) as response:
            if response.status != 200 or urlsplit(response.geturl()).scheme != "https":
                raise ZsxqPdfError("PDF_HTTP_STATUS_INVALID")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    content_length = int(declared)
                except ValueError as error:
                    raise ZsxqPdfError("PDF_CONTENT_LENGTH_INVALID") from error
                if content_length > MAX_PDF_BYTES:
                    raise ZsxqPdfError("PDF_SIZE_LIMIT_EXCEEDED")
                if content_length != expected_size:
                    raise ZsxqPdfError("PDF_SIZE_MISMATCH")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, MAX_PDF_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise ZsxqPdfError("PDF_SIZE_LIMIT_EXCEEDED")
                chunks.append(chunk)
            raw = b"".join(chunks)
    except ZsxqPdfError:
        raise
    except HTTPError as error:
        raise ZsxqPdfError(f"PDF_HTTP_ERROR_{int(error.code)}") from error
    except (URLError, TimeoutError, OSError) as error:
        # Never include exception text: urllib errors may contain the signed URL.
        raise ZsxqPdfError("PDF_DOWNLOAD_FAILED") from error
    verify_pdf_bytes(raw, expected_size)
    return raw


def _pdfinfo_page_count(pdf_path: Path, *, pdfinfo: Path = DEFAULT_PDFINFO) -> int:
    try:
        completed = subprocess.run(
            [str(pdfinfo), str(pdf_path)],
            timeout=20,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ZsxqPdfError("PDFINFO_UNAVAILABLE") from error
    if completed.returncode != 0:
        raise ZsxqPdfError("PDFINFO_FAILED")
    match = re.search(r"(?m)^Pages:\s+(\d+)\s*$", completed.stdout or "")
    if not match:
        raise ZsxqPdfError("PDF_PAGE_COUNT_MISSING")
    count = int(match.group(1))
    if count < 1:
        raise ZsxqPdfError("PDF_PAGE_COUNT_INVALID")
    if count > MAX_PDF_PAGES:
        raise ZsxqPdfError("PDF_PAGE_LIMIT_EXCEEDED")
    return count


def _render_pdf_page(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
    *,
    pdftoppm: Path = DEFAULT_PDFTOPPM,
) -> Path:
    prefix = output_dir / f"render-{page_number:04d}"
    try:
        completed = subprocess.run(
            [
                str(pdftoppm),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-png",
                "-scale-to",
                str(RENDER_SCALE_TO),
                str(pdf_path),
                str(prefix),
            ],
            timeout=45,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ZsxqPdfError("PDF_PAGE_RENDER_FAILED") from error
    if completed.returncode != 0:
        raise ZsxqPdfError("PDF_PAGE_RENDER_FAILED")
    candidates = sorted(output_dir.glob(prefix.name + "*.png"))
    if len(candidates) != 1:
        raise ZsxqPdfError("PDF_PAGE_RENDER_MISSING")
    try:
        size = candidates[0].stat().st_size
    except OSError as error:
        raise ZsxqPdfError("PDF_PAGE_RENDER_MISSING") from error
    if size <= 0 or size > MAX_PAGE_IMAGE_BYTES:
        raise ZsxqPdfError("PDF_PAGE_IMAGE_SIZE_INVALID")
    return candidates[0]


def _load_vision_module() -> tuple[Any, str, str]:
    if not VISION_OCR_SOURCE.is_file():
        raise ZsxqPdfError("LOCAL_VISION_SOURCE_MISSING")
    source_sha = _file_sha256(VISION_OCR_SOURCE)
    old_write_bytecode = sys.dont_write_bytecode
    old_path = list(sys.path)
    old_common = sys.modules.get("wechat_common")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(VISION_OCR_SOURCE.parent))
    module_name = "_v4_zsxq_reused_wechat_vision_ocr"
    try:
        spec = importlib.util.spec_from_file_location(module_name, VISION_OCR_SOURCE)
        if spec is None or spec.loader is None:
            raise ZsxqPdfError("LOCAL_VISION_IMPORT_FAILED")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        config_sha = str(module._ocr_config_sha256())
        return module, source_sha, config_sha
    except ZsxqPdfError:
        raise
    except Exception as error:
        raise ZsxqPdfError("LOCAL_VISION_IMPORT_FAILED") from error
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_write_bytecode
        if old_common is None:
            sys.modules.pop("wechat_common", None)
        else:
            sys.modules["wechat_common"] = old_common
        sys.modules.pop(module_name, None)


def _renderer_version(pdftoppm: Path = DEFAULT_PDFTOPPM) -> str:
    try:
        result = subprocess.run(
            [str(pdftoppm), "-v"],
            timeout=10,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "CANNOT_CONFIRM"
    match = re.search(r"(?m)^pdftoppm version\s+([^\s]+)", (result.stderr or "") + "\n" + (result.stdout or ""))
    return match.group(1) if match else "CANNOT_CONFIRM"


def _safe_artifact_path(data_root: Path, relative: str) -> Path:
    return resolve_owned_path(data_root, relative)


def _read_index(store: NativeDataStore) -> dict[str, Any]:
    try:
        index = store._read(STATE_RELATIVE)
    except FileNotFoundError:
        return {"schema_version": "v4.zsxq_pdf_ingestion_index.v1", "sources": {}, "documents": {}, "ocr_cache": {}}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ZsxqPdfError("PROCESSING_INDEX_UNREADABLE") from error
    if not isinstance(index, dict) or index.get("schema_version") != "v4.zsxq_pdf_ingestion_index.v1":
        raise ZsxqPdfError("PROCESSING_INDEX_INVALID")
    for key in ("sources", "documents", "ocr_cache"):
        if not isinstance(index.get(key), dict):
            raise ZsxqPdfError("PROCESSING_INDEX_INVALID")
    return index


def _write_json(store: NativeDataStore, relative: str, value: Mapping[str, Any]) -> None:
    try:
        store._write(relative, dict(value))
    except (OSError, ValueError) as error:
        raise ZsxqPdfError("OWNED_ARTIFACT_WRITE_FAILED") from error


def _error_code(error: BaseException) -> str:
    if isinstance(error, ZsxqPdfError):
        return error.code
    if isinstance(error, subprocess.TimeoutExpired):
        return "PROCESS_TIMEOUT"
    return type(error).__name__.upper()


def _metadata_matches(source: Mapping[str, Any], live: Mapping[str, Any]) -> bool:
    if str(live.get("file_id") or "") != str(source.get("file_id") or ""):
        return False
    if str(live.get("name") or "") != str(source.get("original_filename") or ""):
        return False
    try:
        if int(live.get("size")) != int(source.get("expected_size")):
            return False
    except (TypeError, ValueError):
        return False
    source_hash = source.get("source_hash_raw")
    live_hash = live.get("hash")
    return source_hash is None or live_hash == source_hash


def _artifact_engine_identity(
    engine_info: Mapping[str, Any], *, renderer_version: str, renderer_path: Path
) -> tuple[str, dict[str, Any]]:
    descriptor = {
        "vision_engine": engine_info.get("engine"),
        "vision_source_sha256": engine_info.get("vision_source_sha256"),
        "vision_config_sha256": engine_info.get("vision_config_sha256"),
        "renderer": "pdftoppm",
        "renderer_path": str(renderer_path),
        "renderer_version": renderer_version,
        "render_scale_to": RENDER_SCALE_TO,
    }
    digest = _sha256(json.dumps(descriptor, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest, descriptor


def _all_pages_covered(pages: Iterable[Mapping[str, Any]], page_count: int) -> bool:
    rows = list(pages)
    return len(rows) == page_count and [row.get("page_number") for row in rows] == list(range(1, page_count + 1)) and all(
        row.get("status") in {"OCR_OK", "OCR_EMPTY"} and row.get("method")
        for row in rows
    )


def _read_pages(store: NativeDataStore, relative: str) -> list[dict[str, Any]]:
    try:
        rows = store._read(relative)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ZsxqPdfError("PAGE_RESULTS_UNREADABLE") from error
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ZsxqPdfError("PAGE_RESULTS_INVALID")
    return rows


def _verify_completed_artifact(
    store: NativeDataStore,
    artifact: Mapping[str, Any],
    *,
    expected_engine_identity: str,
) -> None:
    if artifact.get("status") != "READY" or artifact.get("engine_identity") != expected_engine_identity:
        raise ZsxqPdfError("COMPLETED_ARTIFACT_ENGINE_MISMATCH")
    pdf_relative = str(artifact.get("pdf_path") or "")
    pages_relative = str(artifact.get("pages_path") or "")
    pdf_path = _safe_artifact_path(store.root, pdf_relative)
    if not pdf_path.is_file():
        raise ZsxqPdfError("COMPLETED_PDF_MISSING")
    raw_size = pdf_path.stat().st_size
    pdf_raw = store._io.read_bytes(pdf_relative, max_bytes=MAX_PDF_BYTES)
    if raw_size != int(artifact.get("pdf_size") or 0) or _sha256(pdf_raw) != artifact.get("pdf_sha256"):
        raise ZsxqPdfError("COMPLETED_PDF_INTEGRITY_MISMATCH")
    if not pdf_raw.startswith(b"%PDF-"):
        raise ZsxqPdfError("COMPLETED_PDF_MAGIC_INVALID")
    pages_raw = store._io.read_bytes(pages_relative)
    if _sha256(pages_raw) != artifact.get("pages_file_sha256"):
        raise ZsxqPdfError("COMPLETED_PAGES_INTEGRITY_MISMATCH")
    pages = _read_pages(store, pages_relative)
    if not _all_pages_covered(pages, int(artifact.get("page_count") or 0)):
        raise ZsxqPdfError("COMPLETED_PAGE_COVERAGE_INVALID")


def _copy_cache_artifact(
    store: NativeDataStore,
    cache_row: Mapping[str, Any],
    *,
    engine_identity: str,
    pdf_sha256: str,
    page_count: int,
) -> list[dict[str, Any]]:
    if cache_row.get("pdf_sha256") != pdf_sha256 or cache_row.get("engine_identity") != engine_identity:
        raise ZsxqPdfError("OCR_CACHE_IDENTITY_MISMATCH")
    pages_path = str(cache_row.get("pages_path") or "")
    pages_raw = store._io.read_bytes(pages_path)
    if _sha256(pages_raw) != cache_row.get("pages_file_sha256"):
        raise ZsxqPdfError("OCR_CACHE_INTEGRITY_MISMATCH")
    pages = _read_pages(store, pages_path)
    if not _all_pages_covered(pages, page_count):
        raise ZsxqPdfError("OCR_CACHE_COVERAGE_INVALID")
    return pages


def _process_one(
    *,
    store: NativeDataStore,
    source: dict[str, Any],
    artifact_state: dict[str, Any],
    cache: dict[str, Any],
    processing_root: str,
    cli: Path,
    engine_identity: str,
    engine_descriptor: Mapping[str, Any],
    metadata_lookup: MetadataLookup,
    url_lookup: URLLookup,
    downloader: BytesDownloader,
    page_counter: PageCounter,
    page_renderer: PageRenderer,
    ocr_page: OCRPage,
    now: Callable[[], datetime],
    persist: Callable[[], None],
) -> dict[str, Any]:
    existing = artifact_state.get("status") == "READY"
    if existing:
        _verify_completed_artifact(
            store, artifact_state, expected_engine_identity=engine_identity
        )
        pages_relative = str(artifact_state["pages_path"])
        receipt_relative = str(
            artifact_state.get("receipt_path")
            or f"{processing_root}/receipts/{source['document_key']}_{engine_identity[:16]}.json"
        )
        pages = _read_pages(store, pages_relative)
        artifact_state["real_pdf_path"] = str(
            _safe_artifact_path(store.root, str(artifact_state["pdf_path"]))
        )
        refreshed_receipt = _document_receipt(
            source,
            artifact_state,
            pages,
            engine_descriptor,
            engine_identity,
            receipt_relative,
            pages_relative,
            str(artifact_state["pdf_path"]),
        )
        store._write(receipt_relative, refreshed_receipt)
        artifact_state["receipt_path"] = receipt_relative
        artifact_state["reuse_count"] = int(artifact_state.get("reuse_count") or 0) + 1
        persist()
        return {
            "file_id": source["file_id"],
            "status": "READY",
            "reused": True,
            "real_pdf_path": str(_safe_artifact_path(store.root, str(artifact_state["pdf_path"]))),
            "pages_path": artifact_state.get("pages_path"),
            "receipt_path": artifact_state.get("receipt_path"),
            "pdf_sha256": artifact_state.get("pdf_sha256"),
        }

    attempts = int(artifact_state.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        artifact_state.update(status="FAILED", last_error_code=artifact_state.get("last_error_code") or "RETRY_LIMIT_REACHED")
        persist()
        return {"file_id": source["file_id"], "status": "FAILED", "reused": False}
    artifact_state.update(
        status="PROCESSING",
        attempts=attempts + 1,
        last_error_code=None,
        updated_at=_iso(now()),
    )
    persist()
    started_monotonic = time.monotonic()
    downloaded_at: str | None = None
    ocr_started_at: str | None = None
    pdf_relative = f"{processing_root}/pdfs/{source['document_key']}.pdf"
    engine_suffix = engine_identity[:16]
    pages_relative = f"{processing_root}/pages/{source['document_key']}_{engine_suffix}.json"
    receipt_relative = f"{processing_root}/receipts/{source['document_key']}_{engine_suffix}.json"
    try:
        if int(source.get("expected_size") or 0) > MAX_PDF_BYTES:
            raise ZsxqPdfError("PDF_SIZE_LIMIT_EXCEEDED")
        live = metadata_lookup(cli, str(source["file_id"]))
        if not _metadata_matches(source, live):
            raise ZsxqPdfError("ZSXQ_FILE_METADATA_MISMATCH")
        if source.get("source_hash_raw") is None:
            raise ZsxqPdfError("SOURCE_HASH_MISSING")
        if source.get("source_hash_algorithm") is not None:
            raise ZsxqPdfError("SOURCE_HASH_ALGORITHM_MUST_REMAIN_UNKNOWN")
        url = url_lookup(cli, str(source["file_id"]))
        raw = downloader(url, int(source["expected_size"]))
        pdf_sha = verify_pdf_bytes(raw, int(source["expected_size"]))
        downloaded_at = _iso(now())
        store._io.write_bytes(pdf_relative, raw)
        actual_pdf_path = _safe_artifact_path(store.root, pdf_relative)
        artifact_state["real_pdf_path"] = str(actual_pdf_path)

        page_count = page_counter(actual_pdf_path)
        if page_count < 1 or page_count > MAX_PDF_PAGES:
            raise ZsxqPdfError("PDF_PAGE_COUNT_INVALID")
        cache_key = _sha256(
            "\n".join((str(source["file_id"]), pdf_sha, engine_identity)).encode("utf-8")
        )
        if cache_key in cache:
            pages = _copy_cache_artifact(
                store,
                cache[cache_key],
                engine_identity=engine_identity,
                pdf_sha256=pdf_sha,
                page_count=page_count,
            )
            store._write(pages_relative, pages)
            pages_raw = store._io.read_bytes(pages_relative)
            completed_at = _iso(now())
            artifact_state.update(
                status="READY",
                file_id=source["file_id"],
                pdf_path=pdf_relative,
                pdf_size=len(raw),
                pdf_sha256=pdf_sha,
                source_hash_raw=source.get("source_hash_raw"),
                source_hash_algorithm=None,
                pages_path=pages_relative,
                pages_file_sha256=_sha256(pages_raw),
                page_count=page_count,
                ocr_page_count=page_count,
                page_statuses=[row.get("status") for row in pages],
                downloaded_at=downloaded_at,
                ocr_started_at=None,
                ocr_completed_at=cache[cache_key].get("ocr_completed_at"),
                reused_from=cache[cache_key].get("source_run_id"),
                reused=True,
                completed_at=completed_at,
                available_at=completed_at,
                late_processing=True,
                pit_status=source["pit_status"],
                data_role=source["data_role"],
                pdf_published_at=None,
                duration_seconds=round(time.monotonic() - started_monotonic, 3),
            )
            receipt = _document_receipt(
                source, artifact_state, pages, engine_descriptor, engine_identity,
                receipt_relative, pages_relative, pdf_relative,
            )
            store._write(receipt_relative, receipt)
            artifact_state["receipt_path"] = receipt_relative
            persist()
            return {
                "file_id": source["file_id"],
                "status": "READY",
                "reused": True,
                "real_pdf_path": str(actual_pdf_path),
                "pages_path": pages_relative,
                "receipt_path": receipt_relative,
                "pdf_sha256": pdf_sha,
            }

        old_pages: list[dict[str, Any]] = []
        if artifact_state.get("pages_path") == pages_relative:
            try:
                old_pages = _read_pages(store, pages_relative)
                if not all(isinstance(row.get("page_number"), int) for row in old_pages):
                    old_pages = []
            except ZsxqPdfError:
                old_pages = []
        page_by_number = {int(row["page_number"]): row for row in old_pages}
        ocr_started_at = _iso(now()) if not page_by_number else artifact_state.get("ocr_started_at") or _iso(now())
        artifact_state.update(
            file_id=source["file_id"],
            pdf_path=pdf_relative,
            pdf_size=len(raw),
            pdf_sha256=pdf_sha,
            source_hash_raw=source.get("source_hash_raw"),
            source_hash_algorithm=None,
            pages_path=pages_relative,
            page_count=page_count,
            downloaded_at=downloaded_at,
            ocr_started_at=ocr_started_at,
            engine_identity=engine_identity,
        )
        pages = [page_by_number[number] for number in sorted(page_by_number) if 1 <= number <= page_count]
        store._write(pages_relative, pages)
        persist()
        with tempfile.TemporaryDirectory(prefix="zsxq_pdf_pages_") as temp_name:
            temp_dir = Path(temp_name)
            for page_number in range(1, page_count + 1):
                if page_number in page_by_number and page_by_number[page_number].get("status") in {"OCR_OK", "OCR_EMPTY"}:
                    continue
                observed_at = _iso(now())
                try:
                    image_path = page_renderer(actual_pdf_path, page_number, temp_dir)
                    result = dict(ocr_page(image_path))
                    status = str(result.get("status") or "OCR_ERROR")
                    if status not in {"OCR_OK", "OCR_EMPTY"}:
                        raise ZsxqPdfError("LOCAL_OCR_PAGE_FAILED")
                    row = {
                        "page_number": page_number,
                        "status": status,
                        "method": str(result.get("method") or engine_descriptor.get("vision_engine") or "macOS Vision"),
                        "text": str(result.get("text") or ""),
                        "observed_at": observed_at,
                        "image_width": int(result.get("width") or 0),
                        "image_height": int(result.get("height") or 0),
                    }
                except Exception as error:
                    row = {
                        "page_number": page_number,
                        "status": _error_code(error),
                        "method": str(engine_descriptor.get("vision_engine") or "macOS Vision"),
                        "text": "",
                        "observed_at": observed_at,
                    }
                page_by_number[page_number] = row
                pages = [page_by_number[number] for number in sorted(page_by_number)]
                store._write(pages_relative, pages)
                artifact_state.update(
                    processed_page_count=len(pages),
                    page_statuses=[item.get("status") for item in pages],
                    progress_updated_at=_iso(now()),
                )
                persist()
                if row["status"] not in {"OCR_OK", "OCR_EMPTY"}:
                    break

        pages = [page_by_number[number] for number in sorted(page_by_number)]
        pages_raw = store._io.read_bytes(pages_relative)
        coverage = _all_pages_covered(pages, page_count)
        completed_at = _iso(now()) if coverage else None
        artifact_state.update(
            status="READY" if coverage else "PENDING" if attempts + 1 < MAX_ATTEMPTS else "FAILED",
            pages_file_sha256=_sha256(pages_raw),
            processed_page_count=len(pages),
            ocr_page_count=sum(1 for row in pages if row.get("status") in {"OCR_OK", "OCR_EMPTY"}),
            page_statuses=[row.get("status") for row in pages],
            full_page_coverage=coverage,
            ocr_completed_at=completed_at,
            completed_at=completed_at,
            available_at=completed_at,
            late_processing=True,
            pit_status=source["pit_status"],
            data_role=source["data_role"],
            pdf_published_at=None,
            reused=False,
            duration_seconds=round(time.monotonic() - started_monotonic, 3),
        )
        artifact_state["last_error_code"] = None if coverage else str(
            pages[-1].get("status") if pages else "PAGE_COVERAGE_MISSING"
        )
        receipt = _document_receipt(
            source, artifact_state, pages, engine_descriptor, engine_identity,
            receipt_relative, pages_relative, pdf_relative,
        )
        store._write(receipt_relative, receipt)
        artifact_state["receipt_path"] = receipt_relative
        if coverage:
            cache[cache_key] = {
                "file_id": source["file_id"],
                "pdf_sha256": pdf_sha,
                "engine_identity": engine_identity,
                "pages_path": pages_relative,
                "pages_file_sha256": _sha256(pages_raw),
                "page_count": page_count,
                "source_run_id": source["source_run_id"],
                "ocr_completed_at": completed_at,
            }
        persist()
        return {
            "file_id": source["file_id"],
            "status": artifact_state["status"],
            "reused": False,
            "page_count": page_count,
            "full_page_coverage": coverage,
            "real_pdf_path": str(actual_pdf_path),
            "pages_path": pages_relative,
            "receipt_path": receipt_relative,
            "pdf_sha256": pdf_sha,
        }
    except Exception as error:
        code = _error_code(error)
        artifact_state.update(
            status="PENDING" if attempts + 1 < MAX_ATTEMPTS else "FAILED",
            last_error_code=code,
            downloaded_at=downloaded_at,
            ocr_started_at=ocr_started_at,
            updated_at=_iso(now()),
            duration_seconds=round(time.monotonic() - started_monotonic, 3),
        )
        persist()
        return {"file_id": source["file_id"], "status": artifact_state["status"], "error_code": code, "reused": False}


def _document_receipt(
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    pages: list[dict[str, Any]],
    engine_descriptor: Mapping[str, Any],
    engine_identity: str,
    receipt_path: str,
    pages_path: str,
    pdf_path: str,
) -> dict[str, Any]:
    page_texts = [str(row.get("text") or "") for row in pages]
    all_text = "\n".join(page_texts)
    nonempty = [text for text in page_texts if text.strip()]
    return {
        "schema_version": "v4.zsxq_pdf_document_receipt.v1",
        "status": artifact.get("status"),
        "trade_date": source["trade_date"],
        "source_run_id": source["source_run_id"],
        "group_id": source["group_id"],
        "group_name": source["group_name"],
        "topic_id": source["topic_id"],
        "topic_title": source["topic_title"],
        "source_topic_published_at": source.get("source_topic_published_at"),
        "source_fetched_at": source.get("source_fetched_at"),
        "file_id": source["file_id"],
        "original_filename": source["original_filename"],
        "file_created_at": source.get("file_created_at"),
        "pdf_published_at": None,
        "expected_size": source["expected_size"],
        "pdf_size": artifact.get("pdf_size"),
        "pdf_sha256": artifact.get("pdf_sha256"),
        "source_hash_raw": source.get("source_hash_raw"),
        "source_hash_algorithm": None,
        "real_pdf_path": artifact.get("real_pdf_path"),
        "page_count": artifact.get("page_count"),
        "ocr_page_count": artifact.get("ocr_page_count"),
        "full_page_coverage": artifact.get("full_page_coverage", artifact.get("status") == "READY"),
        "pages": [
            {
                "page_number": row.get("page_number"),
                "status": row.get("status"),
                "method": row.get("method"),
                "text_sha256": _sha256(str(row.get("text") or "").encode("utf-8")),
            }
            for row in pages
        ],
        "downloaded_at": artifact.get("downloaded_at"),
        "ocr_started_at": artifact.get("ocr_started_at"),
        "ocr_completed_at": artifact.get("ocr_completed_at"),
        "completed_at": artifact.get("completed_at"),
        "available_at": artifact.get("available_at"),
        "late_processing": True,
        "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT",
        "data_role": "CURRENT_KNOWLEDGE_SUPPLEMENT",
        "engine_identity": engine_identity,
        "engine": dict(engine_descriptor),
        "reused": bool(artifact.get("reused")),
        "reused_from": artifact.get("reused_from"),
        "attempts": artifact.get("attempts"),
        "last_error_code": artifact.get("last_error_code"),
        "body_length_chars": len(all_text),
        "first_body_excerpt": nonempty[0][:400] if nonempty else "",
        "last_page_excerpt": page_texts[-1][-400:] if page_texts else "",
        "pages_path": pages_path,
        "pdf_path": pdf_path,
        "pages_file_sha256": artifact.get("pages_file_sha256"),
        **SAFETY,
    }


def process_pdf_batch(
    *,
    data_root: Path,
    trade_date: str,
    slot: str,
    source_run_id: str,
    cli: Path = DEFAULT_CLI,
    limit: int = 1,
    file_id: str | None = None,
    metadata_lookup: MetadataLookup | None = None,
    url_lookup: URLLookup | None = None,
    downloader: BytesDownloader | None = None,
    page_counter: PageCounter | None = None,
    page_renderer: PageRenderer | None = None,
    ocr_page: OCRPage | None = None,
    engine_info: Mapping[str, Any] | None = None,
    renderer_path: Path = DEFAULT_PDFTOPPM,
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Process a bounded number of PDFs from an already completed hourly run."""
    _date(trade_date)
    _safe_run_id(source_run_id)
    if limit < 1 or limit > 100:
        raise ZsxqPdfError("PDF_BATCH_LIMIT_INVALID")
    if file_id is not None and not re.fullmatch(r"[0-9]{1,32}", str(file_id)):
        raise ZsxqPdfError("PDF_FILE_ID_INVALID")
    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ZsxqPdfError("DATA_ROOT_INVALID")
    store = NativeDataStore(root)
    status, fetch_result, recent, summary, input_hashes = _source_binding(
        store,
        trade_date=trade_date,
        slot=slot,
        source_run_id=source_run_id,
    )
    documents = enumerate_pdf_documents(recent, trade_date=trade_date, source_run_id=source_run_id)
    if file_id is not None and not any(row["file_id"] == str(file_id) for row in documents):
        raise ZsxqPdfError("REQUESTED_FILE_NOT_IN_SOURCE_RUN")
    if engine_info is None:
        vision_module, vision_source_sha, vision_config_sha = _load_vision_module()
        engine_info = {
            "engine": str(getattr(vision_module, "ENGINE", "macOS Vision Swift executable")),
            "vision_source_sha256": vision_source_sha,
            "vision_config_sha256": vision_config_sha,
        }
    version = _renderer_version(renderer_path) if page_counter is None or page_renderer is None else "TEST_INJECTED"
    engine_identity, engine_descriptor = _artifact_engine_identity(
        engine_info, renderer_version=version, renderer_path=renderer_path
    )
    metadata = metadata_lookup or (lambda selected_cli, selected_file_id: _cli_file_metadata(selected_cli, selected_file_id))
    get_url = url_lookup or (lambda selected_cli, selected_file_id: _cli_download_url(selected_cli, selected_file_id))
    get_bytes = downloader or _download_pdf_bytes
    count_pages = page_counter or _pdfinfo_page_count
    render_page = page_renderer or (lambda pdf, page, out: _render_pdf_page(pdf, page, out))

    runtime: dict[str, Any] = {"module": None, "executable": None, "temp": None}

    def run_ocr(image_path: Path) -> Mapping[str, Any]:
        if ocr_page is not None:
            return ocr_page(image_path)
        if runtime["module"] is None:
            module, _, _ = _load_vision_module()
            temp = tempfile.TemporaryDirectory(prefix="zsxq_vision_helper_")
            runtime.update(module=module, temp=temp)
            try:
                runtime["executable"] = module._compile_vision_helper(Path(temp.name))
            except Exception as error:
                temp.cleanup()
                runtime.update(module=None, executable=None, temp=None)
                raise ZsxqPdfError("LOCAL_VISION_COMPILE_FAILED") from error
        return runtime["module"]._vision_ocr(runtime["executable"], image_path)

    source_signature = _sha256(
        json.dumps(
            {"trade_date": trade_date, "slot": slot, "source_run_id": source_run_id, "input_hashes": input_hashes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    processing_run_id = (
        f"pdfproc_{source_run_id}_{source_signature[:12]}_{engine_identity[:12]}"
    )
    _safe_run_id(processing_run_id)
    processing_root = f"external_sources/zsxq_hourly/{processing_run_id}"
    batch_started_at = _iso(now())
    batch_start_monotonic = time.monotonic()
    outcomes: list[dict[str, Any]] = []
    try:
        with store._io.kernel_lock(LOCK_RELATIVE, timeout=600, poll=0.05):
            index = _read_index(store)
            prior_source = index["sources"].get(source_run_id)
            if prior_source and prior_source.get("source_signature") != source_signature:
                raise ZsxqPdfError("SOURCE_RUN_MUTATED_SINCE_ENQUEUE")
            index["sources"][source_run_id] = {
                "trade_date": trade_date,
                "slot": slot,
                "source_run_id": source_run_id,
                "source_signature": source_signature,
                "input_sha256": input_hashes,
                "topic_count": len(recent.get("topics_brief") or []),
                "pdf_reference_count": len(documents),
                "fetch_count": fetch_result.get("count"),
                "source_fetched_at": status.get("fetched_at"),
                "processing_run_id": processing_run_id,
            }
            for source in documents:
                source["source_fetched_at"] = status.get("fetched_at")
                row = index["documents"].setdefault(
                    source["document_key"],
                    {"source": source, "engine_runs": {}},
                )
                if row.get("source") != source:
                    raise ZsxqPdfError("SOURCE_DOCUMENT_IDENTITY_COLLISION")
                row.setdefault("engine_runs", {}).setdefault(
                    engine_identity,
                    {
                        "status": "PENDING",
                        "attempts": 0,
                        "engine_identity": engine_identity,
                        "full_page_coverage": False,
                        "created_at": _iso(now()),
                    },
                )
            _write_json(store, STATE_RELATIVE, index)

            chosen = [row for row in documents if file_id is not None and row["file_id"] == str(file_id)]
            if file_id is None:
                chosen = []
                for source in documents:
                    engine_run = index["documents"][source["document_key"]]["engine_runs"][engine_identity]
                    if engine_run.get("status") != "READY" and int(engine_run.get("attempts") or 0) < MAX_ATTEMPTS:
                        chosen.append(source)
                    if len(chosen) >= limit:
                        break
            else:
                chosen = chosen[:1]
            for source in chosen:
                document_row = index["documents"][source["document_key"]]
                engine_run = document_row["engine_runs"][engine_identity]
                cache = index["ocr_cache"]

                def persist_current() -> None:
                    _write_json(store, STATE_RELATIVE, index)

                outcome = _process_one(
                    store=store,
                    source=source,
                    artifact_state=engine_run,
                    cache=cache,
                    processing_root=processing_root,
                    cli=Path(cli),
                    engine_identity=engine_identity,
                    engine_descriptor=engine_descriptor,
                    metadata_lookup=metadata,
                    url_lookup=get_url,
                    downloader=get_bytes,
                    page_counter=count_pages,
                    page_renderer=render_page,
                    ocr_page=run_ocr,
                    now=now,
                    persist=persist_current,
                )
                outcomes.append(outcome)
                batch_receipt = {
                    "schema_version": "v4.zsxq_pdf_batch_receipt.v1",
                    "status": "READY" if outcomes and all(item.get("status") == "READY" for item in outcomes) else "PARTIAL",
                    "mode": "pdf_only_existing_run_no_topic_refetch",
                    "processing_run_id": processing_run_id,
                    "trade_date": trade_date,
                    "slot": slot,
                    "source_run_id": source_run_id,
                    "data_root": str(store.root.resolve()),
                    "source_status_path": str(_safe_artifact_path(store.root, f"research_module/runtime_outputs/zsxq_hourly/{trade_date}/{slot}/v35_zsxq_hourly_status_{trade_date}_{slot}.json")),
                    "source_run_path": str(_safe_artifact_path(store.root, f"external_sources/zsxq_hourly/{source_run_id}")),
                    "processing_run_path": str(_safe_artifact_path(store.root, processing_root)),
                    "source_signature": source_signature,
                    "input_sha256": input_hashes,
                    "enumeration_scope": "topics_brief.files_all_topics_including_noise",
                    "topic_count": len(recent.get("topics_brief") or []),
                    "pdf_reference_count": len(documents),
                    "processed_this_batch": outcomes,
                    "pending_total": sum(
                        1
                        for entry in index["documents"].values()
                        for run in entry.get("engine_runs", {}).values()
                        if run.get("status") in {"PENDING", "PROCESSING"}
                    ),
                    "failed_total": sum(
                        1
                        for entry in index["documents"].values()
                        for run in entry.get("engine_runs", {}).values()
                        if run.get("status") == "FAILED"
                    ),
                    "batch_started_at": batch_started_at,
                    "batch_completed_at": _iso(now()),
                    "batch_duration_seconds": round(time.monotonic() - batch_start_monotonic, 3),
                    "engine_identity": engine_identity,
                    "engine": engine_descriptor,
                    "commands": {
                        "file_metadata": {"executable": str(cli), "argv": ["api", "raw", "--method", "GET", "--path", "/v2/files/{file_id}"]},
                        "download_url": {"executable": str(cli), "argv": ["api", "raw", "--method", "GET", "--path", "/v2/files/{file_id}/download_url"], "url_value_persisted": False},
                        "attachment_get": {"method": "GET", "target": "HTTPS URL returned by the authenticated CLI; held in memory only"},
                        "page_count": [str(DEFAULT_PDFINFO), "<stored-pdf-path>"],
                        "page_render": [str(renderer_path), "-f", "{page}", "-l", "{page}", "-png", "-scale-to", str(RENDER_SCALE_TO), "<stored-pdf-path>", "<temporary-page-prefix>"],
                        "vision_compile": ["swiftc", "-O", "-framework", "Vision", "-framework", "ImageIO", "-framework", "CoreGraphics", "-o", "<temporary-helper>", "-"],
                        "vision_call": "Existing wechat_macos_ocr.py _vision_ocr; one Swift process per rendered page",
                    },
                    "signed_download_urls_persisted": False,
                    "cli_stdout_stderr_persisted": False,
                    "permission_note": "Real local CLI API and HTTPS attachment GET were explicitly authorized.",
                    "diagnostic_redaction_note": "One transient diagnostic output contained an unrelated group metadata URL; no API response, signed file URL, or credential field was persisted.",
                    **SAFETY,
                }
                _write_json(store, f"{processing_root}/processing_receipt.json", batch_receipt)
            if not chosen:
                outcomes = []
                batch_receipt = {
                    "schema_version": "v4.zsxq_pdf_batch_receipt.v1",
                    "status": "PENDING",
                    "mode": "pdf_only_existing_run_no_topic_refetch",
                    "processing_run_id": processing_run_id,
                    "trade_date": trade_date,
                    "slot": slot,
                    "source_run_id": source_run_id,
                    "data_root": str(store.root.resolve()),
                    "source_status_path": str(_safe_artifact_path(store.root, f"research_module/runtime_outputs/zsxq_hourly/{trade_date}/{slot}/v35_zsxq_hourly_status_{trade_date}_{slot}.json")),
                    "source_run_path": str(_safe_artifact_path(store.root, f"external_sources/zsxq_hourly/{source_run_id}")),
                    "processing_run_path": str(_safe_artifact_path(store.root, processing_root)),
                    "source_signature": source_signature,
                    "input_sha256": input_hashes,
                    "enumeration_scope": "topics_brief.files_all_topics_including_noise",
                    "topic_count": len(recent.get("topics_brief") or []),
                    "pdf_reference_count": len(documents),
                    "processed_this_batch": [],
                    "pending_total": sum(
                        1
                        for entry in index["documents"].values()
                        for run in entry.get("engine_runs", {}).values()
                        if run.get("status") in {"PENDING", "PROCESSING"}
                    ),
                    "failed_total": sum(
                        1
                        for entry in index["documents"].values()
                        for run in entry.get("engine_runs", {}).values()
                        if run.get("status") == "FAILED"
                    ),
                    "batch_started_at": batch_started_at,
                    "batch_completed_at": _iso(now()),
                    "batch_duration_seconds": round(time.monotonic() - batch_start_monotonic, 3),
                    "engine_identity": engine_identity,
                    "engine": engine_descriptor,
                    "commands": {
                        "file_metadata": {"executable": str(cli), "argv": ["api", "raw", "--method", "GET", "--path", "/v2/files/{file_id}"]},
                        "download_url": {"executable": str(cli), "argv": ["api", "raw", "--method", "GET", "--path", "/v2/files/{file_id}/download_url"], "url_value_persisted": False},
                        "attachment_get": {"method": "GET", "target": "HTTPS URL returned by the authenticated CLI; held in memory only"},
                        "page_count": [str(DEFAULT_PDFINFO), "<stored-pdf-path>"],
                        "page_render": [str(renderer_path), "-f", "{page}", "-l", "{page}", "-png", "-scale-to", str(RENDER_SCALE_TO), "<stored-pdf-path>", "<temporary-page-prefix>"],
                        "vision_compile": ["swiftc", "-O", "-framework", "Vision", "-framework", "ImageIO", "-framework", "CoreGraphics", "-o", "<temporary-helper>", "-"],
                        "vision_call": "Existing wechat_macos_ocr.py _vision_ocr; one Swift process per rendered page",
                    },
                    "signed_download_urls_persisted": False,
                    "cli_stdout_stderr_persisted": False,
                    "diagnostic_redaction_note": "One transient diagnostic output contained an unrelated group metadata URL; no API response, signed file URL, or credential field was persisted.",
                    **SAFETY,
                }
                _write_json(store, f"{processing_root}/processing_receipt.json", batch_receipt)
        result_status = "READY" if outcomes and all(item.get("status") == "READY" for item in outcomes) else "PARTIAL" if outcomes else "PENDING"
        return {
            "status": result_status,
            "processing_run_id": processing_run_id,
            "processing_root": processing_root,
            "source_run_id": source_run_id,
            "trade_date": trade_date,
            "slot": slot,
            "topic_count": len(recent.get("topics_brief") or []),
            "pdf_reference_count": len(documents),
            "processed_this_batch": outcomes,
            "pending_total": batch_receipt["pending_total"],
            "failed_total": batch_receipt["failed_total"],
            "input_sha256": input_hashes,
            "engine_identity": engine_identity,
            "engine": engine_descriptor,
            "receipt_path": f"{processing_root}/processing_receipt.json",
            **SAFETY,
        }
    finally:
        if runtime.get("temp") is not None:
            runtime["temp"].cleanup()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--pdf-limit", type=int, default=1)
    parser.add_argument("--pdf-file-id")
    args = parser.parse_args(argv)
    try:
        result = process_pdf_batch(
            data_root=args.data_root,
            trade_date=args.date,
            slot=args.slot,
            source_run_id=args.source_run_id,
            cli=args.cli,
            limit=args.pdf_limit,
            file_id=args.pdf_file_id,
        )
    except Exception as error:
        code = _error_code(error)
        print(json.dumps({"status": "CANNOT_CONFIRM", "error_code": code, **SAFETY}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
