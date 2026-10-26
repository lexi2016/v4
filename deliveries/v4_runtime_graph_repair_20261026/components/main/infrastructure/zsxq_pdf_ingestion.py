"""Bounded PDF download and local page OCR derived from an existing ZSXQ run.

This module consumes the exact owned hourly status and its three original
source files. It never fetches topics or modifies that source run.
"""
from __future__ import annotations
from infrastructure.runtime_graph.notifications import notify as _graph_notify, set_context as _graph_context

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
from infrastructure.owned_io import SafeRoot
from infrastructure.owned_path import resolve_owned_path


SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES_PER_BATCH = 2
MAX_PDF_CONTINUATION_DOCUMENTS = 1
MAX_PDF_CONTINUATION_SECONDS = 180
PDF_QUEUE_RETRY_BACKOFF_SECONDS = 300
PAGE_LIMIT_RECOVERY_TRANSIENT_CODE = "PDF_RECOVERY_SOURCE_TEMPORARILY_UNAVAILABLE"
MAX_PAGE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_ATTEMPTS = 2
PERMANENT_FAILURE_CODES = frozenset(
    {
        "PDF_SIZE_LIMIT_EXCEEDED",
        "PDF_MAGIC_INVALID",
        "PDF_PAGE_LIMIT_EXCEEDED",
        "PDF_PAGE_COUNT_INVALID",
        "ZSXQ_FILE_METADATA_MISMATCH",
        "SOURCE_HASH_MISSING",
        "SOURCE_HASH_ALGORITHM_MUST_REMAIN_UNKNOWN",
        "ZSXQ_DOWNLOAD_URL_UNSAFE",
        "DOWNLOAD_REDIRECT_DOWNGRADE",
    }
)
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


def _store_io(store: NativeDataStore) -> Any:
    """Use the secure owned-I/O boundary across active V4 store revisions."""
    io = getattr(store, "_io", None)
    if io is not None:
        return io
    io = getattr(store, "_zsxq_pdf_io", None)
    if io is None:
        io = SafeRoot(Path(store.root))
        setattr(store, "_zsxq_pdf_io", io)
    return io


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
        raw = _store_io(store).read_bytes(relative)
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
        files = topic.get("files") or []
        if not isinstance(files, list):
            continue
        for raw_file in files:
            if not isinstance(raw_file, Mapping):
                continue
            name = str(raw_file.get("name") or "")
            if Path(name).suffix.lower() != ".pdf":
                continue
            if not group_id or not topic_id:
                raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_INCOMPLETE")
            file_id = str(raw_file.get("file_id") or "").strip()
            if not re.fullmatch(r"[0-9]{1,32}", file_id):
                raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_INCOMPLETE")
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


def _engine_run_is_retryable(engine_run: Mapping[str, Any]) -> bool:
    status = str(engine_run.get("status") or "").upper()
    if status == "READY":
        return False
    if status == "FAILED":
        return (
            engine_run.get("failure_class") != "PERMANENT"
            and int(engine_run.get("attempts") or 0) < MAX_ATTEMPTS
        )
    return status in {"PENDING", "PROCESSING", "PARTIAL"}


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
    if type(page_count) is not int or page_count < 1:
        return False
    rows = list(pages)
    if len(rows) != page_count:
        return False
    for expected_page_number, row in enumerate(rows, start=1):
        if type(row.get("page_number")) is not int or row["page_number"] != expected_page_number:
            return False
        if row.get("status") not in {"OCR_OK", "OCR_EMPTY"} or not row.get("method"):
            return False
    return True


def _latest_engine_run(document_row: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    runs = document_row.get("engine_runs")
    if not isinstance(runs, Mapping) or not runs:
        return None
    candidates = [
        (str(identity), dict(value))
        for identity, value in runs.items()
        if isinstance(value, Mapping)
    ]
    return max(
        candidates,
        key=lambda item: (
            str(item[1].get("updated_at") or item[1].get("completed_at") or item[1].get("created_at") or ""),
            item[0],
        ),
        default=None,
    )


def _source_row_for_document(
    store: NativeDataStore,
    index: Mapping[str, Any],
    document_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    documents = index.get("documents")
    if not isinstance(documents, Mapping):
        raise ZsxqPdfError("PROCESSING_INDEX_INVALID")
    document_row = documents.get(document_id)
    if not isinstance(document_row, Mapping) or not isinstance(document_row.get("source"), Mapping):
        raise ZsxqPdfError("DOCUMENT_NOT_FOUND")
    source = dict(document_row["source"])
    trade_date = _date(str(source.get("trade_date") or ""))
    source_run_id = _safe_run_id(str(source.get("source_run_id") or ""))
    if source.get("document_key") != document_id:
        raise ZsxqPdfError("SOURCE_DOCUMENT_IDENTITY_MISMATCH")
    source_rows = index.get("sources")
    source_entry = source_rows.get(source_run_id) if isinstance(source_rows, Mapping) else None
    if not isinstance(source_entry, Mapping):
        raise ZsxqPdfError("SOURCE_RUN_NOT_REGISTERED")
    slot = str(source_entry.get("slot") or "")
    if source_entry.get("trade_date") != trade_date or source_entry.get("source_run_id") != source_run_id:
        raise ZsxqPdfError("SOURCE_RUN_IDENTITY_MISMATCH")

    status, fetch_result, recent, _summary, input_hashes = _source_binding(
        store,
        trade_date=trade_date,
        slot=slot,
        source_run_id=source_run_id,
    )
    if dict(source_entry.get("input_sha256") or {}) != input_hashes:
        raise ZsxqPdfError("SOURCE_INPUT_SHA256_MISMATCH")
    signature = _sha256(
        json.dumps(
            {"trade_date": trade_date, "slot": slot, "source_run_id": source_run_id, "input_hashes": input_hashes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if source_entry.get("source_signature") != signature:
        raise ZsxqPdfError("SOURCE_SIGNATURE_MISMATCH")
    enumerated = enumerate_pdf_documents(recent, trade_date=trade_date, source_run_id=source_run_id)
    expected = next((row for row in enumerated if row.get("document_key") == document_id), None)
    if expected is None:
        raise ZsxqPdfError("SOURCE_DOCUMENT_NOT_ENUMERATED")
    expected["source_fetched_at"] = status.get("fetched_at")
    if source != expected:
        raise ZsxqPdfError("SOURCE_DOCUMENT_METADATA_MISMATCH")
    return source, dict(document_row)


def _verified_source_enumeration(
    store: NativeDataStore,
    index: Mapping[str, Any],
    source_run_id: str,
    source_entry: Mapping[str, Any],
) -> int:
    """Recheck one exact-date attachment enumeration before treating zero as a result."""
    trade_date = _date(str(source_entry.get("trade_date") or ""))
    if source_entry.get("source_run_id") != source_run_id:
        raise ZsxqPdfError("SOURCE_RUN_IDENTITY_MISMATCH")
    slot = str(source_entry.get("slot") or "")
    if (
        source_entry.get("enumeration_complete") is not True
        or source_entry.get("enumeration_scope") != "topics_brief.files_all_topics_including_noise"
    ):
        raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_MISSING")
    status, _fetch_result, recent, _summary, input_hashes = _source_binding(
        store,
        trade_date=trade_date,
        slot=slot,
        source_run_id=source_run_id,
    )
    if dict(source_entry.get("input_sha256") or {}) != input_hashes:
        raise ZsxqPdfError("SOURCE_INPUT_SHA256_MISMATCH")
    signature = _sha256(
        json.dumps(
            {"trade_date": trade_date, "slot": slot, "source_run_id": source_run_id, "input_hashes": input_hashes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if source_entry.get("source_signature") != signature:
        raise ZsxqPdfError("SOURCE_SIGNATURE_MISMATCH")
    topics = recent.get("topics_brief")
    if not isinstance(topics, list) or source_entry.get("topic_count") != len(topics):
        raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_MISSING")
    enumerated = enumerate_pdf_documents(recent, trade_date=trade_date, source_run_id=source_run_id)
    reference_count = source_entry.get("pdf_reference_count")
    if type(reference_count) is not int or reference_count != len(enumerated):
        raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_MISSING")
    expected_ids = {str(row.get("document_key") or "") for row in enumerated}
    documents = index.get("documents")
    if not isinstance(documents, Mapping):
        raise ZsxqPdfError("PROCESSING_INDEX_INVALID")
    indexed_ids = {
        str(document_id)
        for document_id, row in documents.items()
        if isinstance(row, Mapping)
        and isinstance(row.get("source"), Mapping)
        and row["source"].get("source_run_id") == source_run_id
    }
    if indexed_ids != expected_ids or status.get("trade_date") != trade_date:
        raise ZsxqPdfError("PDF_SOURCE_ENUMERATION_MISSING")
    return reference_count


def _safe_document_paths(
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    engine_identity: str,
) -> tuple[str, str, str]:
    document_id = str(source.get("document_key") or "")
    source_run_id = str(source.get("source_run_id") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", document_id):
        raise ZsxqPdfError("DOCUMENT_ID_INVALID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", source_run_id):
        raise ZsxqPdfError("SOURCE_RUN_ID_INVALID")
    if not re.fullmatch(r"[0-9a-f]{64}", engine_identity):
        raise ZsxqPdfError("ENGINE_IDENTITY_INVALID")
    processing_prefix = rf"external_sources/zsxq_hourly/pdfproc_{re.escape(source_run_id)}_[0-9a-f]{{12}}_[0-9a-f]{{12}}"
    pdf_path = str(artifact.get("pdf_path") or "")
    pages_path = str(artifact.get("pages_path") or "")
    receipt_path = str(artifact.get("receipt_path") or "")
    if not re.fullmatch(processing_prefix + rf"/pdfs/{document_id}\.pdf", pdf_path):
        raise ZsxqPdfError("PDF_PATH_NOT_OWNED")
    if not re.fullmatch(processing_prefix + rf"/pages/{document_id}_{engine_identity[:16]}\.json", pages_path):
        raise ZsxqPdfError("PAGES_PATH_NOT_OWNED")
    if not re.fullmatch(processing_prefix + rf"/receipts/{document_id}_{engine_identity[:16]}\.json", receipt_path):
        raise ZsxqPdfError("RECEIPT_PATH_NOT_OWNED")
    return pdf_path, pages_path, receipt_path


def _verified_document_detail(
    store: NativeDataStore,
    index: Mapping[str, Any],
    document_id: str,
    *,
    verify_pdf: bool,
) -> dict[str, Any]:
    source, document_row = _source_row_for_document(store, index, document_id)
    latest = _latest_engine_run(document_row)
    if latest is None:
        raise ZsxqPdfError("DOCUMENT_PROCESSING_NOT_STARTED")
    engine_identity, artifact = latest
    pdf_path, pages_path, receipt_path = _safe_document_paths(source, artifact, engine_identity)
    if artifact.get("status") not in {"READY", "PENDING", "PROCESSING", "FAILED", "PARTIAL"}:
        raise ZsxqPdfError("DOCUMENT_STATUS_INVALID")
    if not artifact.get("pdf_sha256") or not artifact.get("pages_file_sha256"):
        raise ZsxqPdfError("DOCUMENT_ARTIFACTS_NOT_AVAILABLE")
    pdf_file = _safe_artifact_path(store.root, pdf_path)
    pages_file = _safe_artifact_path(store.root, pages_path)
    receipt_file = _safe_artifact_path(store.root, receipt_path)
    if not (pdf_file.is_file() and pages_file.is_file() and receipt_file.is_file()):
        raise ZsxqPdfError("DOCUMENT_ARTIFACT_MISSING")
    if pdf_file.is_symlink() or pages_file.is_symlink() or receipt_file.is_symlink():
        raise ZsxqPdfError("DOCUMENT_ARTIFACT_SYMLINK_REJECTED")
    receipt_raw = _store_io(store).read_bytes(receipt_path, max_bytes=2 * 1024 * 1024)
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ZsxqPdfError("DOCUMENT_RECEIPT_INVALID") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "v4.zsxq_pdf_document_receipt.v1":
        raise ZsxqPdfError("DOCUMENT_RECEIPT_INVALID")
    pdf_size = pdf_file.stat().st_size
    if pdf_size > MAX_PDF_BYTES:
        raise ZsxqPdfError("PDF_SIZE_LIMIT_EXCEEDED")
    if pdf_size != int(artifact.get("pdf_size") or 0):
        raise ZsxqPdfError("COMPLETED_PDF_SIZE_MISMATCH")
    if verify_pdf:
        pdf_raw = _store_io(store).read_bytes(pdf_path, max_bytes=MAX_PDF_BYTES)
        if _sha256(pdf_raw) != artifact.get("pdf_sha256") or not pdf_raw.startswith(b"%PDF-"):
            raise ZsxqPdfError("COMPLETED_PDF_INTEGRITY_MISMATCH")
    elif not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("pdf_sha256") or "")):
        raise ZsxqPdfError("COMPLETED_PDF_SHA256_INVALID")
    pages_raw = _store_io(store).read_bytes(pages_path, max_bytes=32 * 1024 * 1024)
    if _sha256(pages_raw) != artifact.get("pages_file_sha256"):
        raise ZsxqPdfError("COMPLETED_PAGES_INTEGRITY_MISMATCH")
    pages = _read_pages(store, pages_path)
    page_count = artifact.get("page_count")
    if type(page_count) is not int or page_count < 1:
        raise ZsxqPdfError("PAGE_COUNT_INVALID")
    if len(pages) > page_count or len({row.get("page_number") for row in pages}) != len(pages):
        raise ZsxqPdfError("PAGE_COVERAGE_INVALID")
    for row in pages:
        if type(row.get("page_number")) is not int or not 1 <= row["page_number"] <= page_count:
            raise ZsxqPdfError("PAGE_COVERAGE_INVALID")
        if not isinstance(row.get("text"), str) or not isinstance(row.get("status"), str):
            raise ZsxqPdfError("PAGE_RESULTS_INVALID")
    if artifact.get("status") == "READY" and not _all_pages_covered(pages, page_count):
        raise ZsxqPdfError("COMPLETED_PAGE_COVERAGE_INVALID")
    receipt_pages = receipt.get("pages")
    expected_receipt_pages = [
        {
            "page_number": row.get("page_number"),
            "status": row.get("status"),
            "method": row.get("method"),
            "text_sha256": _sha256(str(row.get("text") or "").encode("utf-8")),
        }
        for row in pages
    ]
    source_fields = (
        "trade_date", "source_run_id", "group_id", "group_name", "topic_id", "topic_title",
        "source_topic_published_at", "source_fetched_at", "file_id", "original_filename",
        "expected_size", "pdf_published_at", "pit_status", "data_role", "late_processing",
    )
    if any(receipt.get(key) != source.get(key) for key in source_fields):
        raise ZsxqPdfError("DOCUMENT_RECEIPT_SOURCE_MISMATCH")
    if (
        receipt.get("status") != artifact.get("status")
        or receipt.get("engine_identity") != engine_identity
        or receipt.get("pdf_path") != pdf_path
        or receipt.get("pages_path") != pages_path
        or receipt.get("pdf_sha256") != artifact.get("pdf_sha256")
        or receipt.get("pdf_size") != artifact.get("pdf_size")
        or receipt.get("page_count") != page_count
        or receipt.get("pages_file_sha256") != artifact.get("pages_file_sha256")
        or receipt.get("downloaded_at") != artifact.get("downloaded_at")
        or receipt_pages != expected_receipt_pages
        or receipt.get("pdf_published_at") is not None
        or receipt.get("late_processing") is not True
        or receipt.get("pit_status") != "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT"
        or any(receipt.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise ZsxqPdfError("DOCUMENT_RECEIPT_ARTIFACT_MISMATCH")
    if str(receipt.get("real_pdf_path") or "") != str(pdf_file):
        raise ZsxqPdfError("DOCUMENT_RECEIPT_PATH_MISMATCH")
    excerpts = [str(row.get("text") or "") for row in pages if str(row.get("text") or "").strip()]
    return {
        "status": str(artifact.get("status") or "CANNOT_CONFIRM"),
        "document_id": document_id,
        "research_date": str(source["trade_date"]),
        "source": {key: source.get(key) for key in source_fields},
        "processing": {
            "page_count": page_count,
            "processed_page_count": len(pages),
            "downloaded_at": artifact.get("downloaded_at"),
            "ocr_started_at": artifact.get("ocr_started_at"),
            "ocr_completed_at": artifact.get("ocr_completed_at"),
            "completed_at": artifact.get("completed_at"),
            "available_at": artifact.get("available_at"),
            "engine_identity": engine_identity,
            "engine": receipt.get("engine"),
            "late_processing": True,
            "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT",
        },
        "excerpt": excerpts[0][:400] if excerpts else "",
        "last_page_excerpt": str(pages[-1].get("text") or "")[-400:] if pages else "",
        "pages": [
            {
                "page_number": row.get("page_number"),
                "status": row.get("status"),
                "method": row.get("method"),
                "text": row.get("text") or "",
                "text_sha256": _sha256(str(row.get("text") or "").encode("utf-8")),
                "observed_at": row.get("observed_at"),
            }
            for row in pages
        ],
        "receipt": {
            "path": receipt_path,
            "sha256": _sha256(receipt_raw),
            "integrity": "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED" if verify_pdf else "SOURCE_AND_PAGE_HASHES_VERIFIED",
        },
        **SAFETY,
    }


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
    pdf_raw = _store_io(store).read_bytes(pdf_relative, max_bytes=MAX_PDF_BYTES)
    if raw_size != int(artifact.get("pdf_size") or 0) or _sha256(pdf_raw) != artifact.get("pdf_sha256"):
        raise ZsxqPdfError("COMPLETED_PDF_INTEGRITY_MISMATCH")
    if not pdf_raw.startswith(b"%PDF-"):
        raise ZsxqPdfError("COMPLETED_PDF_MAGIC_INVALID")
    pages_raw = _store_io(store).read_bytes(pages_relative)
    if _sha256(pages_raw) != artifact.get("pages_file_sha256"):
        raise ZsxqPdfError("COMPLETED_PAGES_INTEGRITY_MISMATCH")
    pages = _read_pages(store, pages_relative)
    page_count = artifact.get("page_count")
    if type(page_count) is not int or page_count < 1:
        raise ZsxqPdfError("PAGE_COUNT_INVALID")
    if not _all_pages_covered(pages, page_count):
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
    pages_raw = _store_io(store).read_bytes(pages_path)
    if _sha256(pages_raw) != cache_row.get("pages_file_sha256"):
        raise ZsxqPdfError("OCR_CACHE_INTEGRITY_MISMATCH")
    pages = _read_pages(store, pages_path)
    if not _all_pages_covered(pages, page_count):
        raise ZsxqPdfError("OCR_CACHE_COVERAGE_INVALID")
    return pages


def _verified_partial_pdf(
    store: NativeDataStore,
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    pdf_relative: str,
) -> tuple[bytes, str, Path] | None:
    """Reuse owned PDF bytes for a partial OCR continuation when their binding still holds."""
    if (
        artifact.get("file_id") != source.get("file_id")
        or artifact.get("pdf_path") != pdf_relative
        or artifact.get("source_hash_raw") != source.get("source_hash_raw")
        or artifact.get("pdf_size") != source.get("expected_size")
        or not artifact.get("downloaded_at")
        or not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("pdf_sha256") or ""))
    ):
        return None
    pdf_path = _safe_artifact_path(store.root, pdf_relative)
    if not pdf_path.is_file():
        return None
    raw = _store_io(store).read_bytes(pdf_relative, max_bytes=MAX_PDF_BYTES)
    try:
        pdf_sha = verify_pdf_bytes(raw, int(source.get("expected_size") or 0))
    except ZsxqPdfError:
        return None
    if pdf_sha != artifact.get("pdf_sha256"):
        return None
    return raw, pdf_sha, pdf_path


def _page_limit_recovery_candidate(
    store: NativeDataStore,
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    processing_root: str,
) -> tuple[str, Path] | None:
    """Identify the one legacy failure eligible for source revalidation by the producer."""
    recovery = artifact.get("page_limit_recovery")
    if recovery is not None and (
        not isinstance(recovery, Mapping)
        or recovery.get("status") != "RETRYABLE"
        or type(recovery.get("revalidation_attempts")) is not int
        or not 1 <= recovery["revalidation_attempts"] < MAX_ATTEMPTS
    ):
        return None
    if (
        str(artifact.get("status") or "").upper() != "FAILED"
        or artifact.get("failure_class") != "PERMANENT"
        or artifact.get("last_error_code") != "PDF_PAGE_LIMIT_EXCEEDED"
        or type(artifact.get("attempts")) is not int
        or artifact.get("attempts") != 1
        or not artifact.get("downloaded_at")
    ):
        return None
    document_key = str(source.get("document_key") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", document_key):
        return None
    pdf_relative = f"{processing_root}/pdfs/{document_key}.pdf"
    pdf_path = _safe_artifact_path(store.root, pdf_relative)
    if artifact.get("real_pdf_path") != str(pdf_path) or pdf_path.is_symlink() or not pdf_path.is_file():
        return None
    try:
        expected_size = int(source.get("expected_size") or 0)
        if not 0 < expected_size <= MAX_PDF_BYTES or pdf_path.stat().st_size != expected_size:
            return None
    except (OSError, TypeError, ValueError):
        return None
    return pdf_relative, pdf_path


def _page_limit_recovery_terminal_error(error: Exception) -> bool:
    """Keep confirmed content-integrity and URL-safety failures closed."""
    return isinstance(error, ZsxqPdfError) and error.code in {
        "PDF_BYTES_EMPTY",
        "PDF_CONTENT_LENGTH_INVALID",
        "PDF_MAGIC_INVALID",
        "PDF_PAGE_COUNT_INVALID",
        "PDF_PAGE_COUNT_MISSING",
        "PDF_SIZE_LIMIT_EXCEEDED",
        "PDF_SIZE_MISMATCH",
        "SOURCE_HASH_ALGORITHM_MUST_REMAIN_UNKNOWN",
        "SOURCE_HASH_MISSING",
        "ZSXQ_FILE_METADATA_MISMATCH",
        "ZSXQ_DOWNLOAD_URL_UNSAFE",
        "DOWNLOAD_REDIRECT_DOWNGRADE",
    }


def _page_limit_recovery_lookup(callback: Callable[..., Any], *args: Any) -> Any:
    """Redact callback failures and let the durable queue retry them once."""
    try:
        return callback(*args)
    except Exception as error:
        if _page_limit_recovery_terminal_error(error):
            raise
        raise ZsxqPdfError(PAGE_LIMIT_RECOVERY_TRANSIENT_CODE) from error


def _verified_page_limit_recovery(
    store: NativeDataStore,
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    processing_root: str,
    *,
    cli: Path,
    metadata_lookup: MetadataLookup,
    url_lookup: URLLookup,
    downloader: BytesDownloader,
    page_counter: PageCounter | None = None,
) -> tuple[bytes, str, int, Path] | None:
    """Bind an unpinned legacy cache to one metadata-validated source download."""
    candidate = _page_limit_recovery_candidate(store, source, artifact, processing_root)
    if candidate is None:
        return None
    pdf_relative, pdf_path = candidate
    file_id = str(source.get("file_id") or "")
    try:
        expected_size = int(source.get("expected_size") or 0)
        live_metadata = _page_limit_recovery_lookup(metadata_lookup, cli, file_id)
        if not _metadata_matches(source, live_metadata):
            return None
        source_url = _page_limit_recovery_lookup(url_lookup, cli, file_id)
        downloaded_raw = _page_limit_recovery_lookup(downloader, source_url, expected_size)
        downloaded_sha = verify_pdf_bytes(downloaded_raw, expected_size)
        cached_raw = _store_io(store).read_bytes(pdf_relative, max_bytes=MAX_PDF_BYTES)
        cached_sha = verify_pdf_bytes(cached_raw, expected_size)
        if cached_sha != downloaded_sha:
            return None
        page_count = _page_limit_recovery_lookup(page_counter or _pdfinfo_page_count, pdf_path)
    except ZsxqPdfError as error:
        if error.code == PAGE_LIMIT_RECOVERY_TRANSIENT_CODE:
            raise
        return None
    except Exception:
        return None
    if type(page_count) is not int or page_count < 1:
        return None
    return cached_raw, downloaded_sha, page_count, pdf_path


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
    max_pages_per_batch: int,
    now: Callable[[], datetime],
    persist: Callable[[], None],
) -> dict[str, Any]:
    _graph_notify("ZSXQ_PDF", "zsxq_pdf", None, "EXECUTOR_ENTERED")
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
        failure_class=None,
        updated_at=_iso(now()),
    )
    persist()
    started_monotonic = time.monotonic()
    downloaded_at: str | None = artifact_state.get("downloaded_at")
    ocr_started_at: str | None = artifact_state.get("ocr_started_at")
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
        cached_pdf = _verified_partial_pdf(store, source, artifact_state, pdf_relative)
        if cached_pdf is not None:
            raw, pdf_sha, actual_pdf_path = cached_pdf
        else:
            url = url_lookup(cli, str(source["file_id"]))
            raw = downloader(url, int(source["expected_size"]))
            downloaded_at = _iso(now())
            pdf_sha = verify_pdf_bytes(raw, int(source["expected_size"]))
            _store_io(store).write_bytes(pdf_relative, raw)
            actual_pdf_path = _safe_artifact_path(store.root, pdf_relative)
        artifact_state["real_pdf_path"] = str(actual_pdf_path)

        page_count = page_counter(actual_pdf_path)
        if type(page_count) is not int or page_count < 1:
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
            pages_raw = _store_io(store).read_bytes(pages_relative)
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
                processed_page_count=page_count,
                ocr_page_count=page_count,
                full_page_coverage=True,
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
        if (
            artifact_state.get("pages_path") == pages_relative
            and artifact_state.get("pdf_sha256") == pdf_sha
        ):
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
            processed_this_batch = 0
            for page_number in range(1, page_count + 1):
                if page_number in page_by_number and page_by_number[page_number].get("status") in {"OCR_OK", "OCR_EMPTY"}:
                    continue
                if processed_this_batch >= max_pages_per_batch:
                    break
                observed_at = _iso(now())
                try:
                    image_path = page_renderer(actual_pdf_path, page_number, temp_dir)
                    result = dict(ocr_page(image_path))
                    status = str(result.get("status") or "OCR_ERROR")
                    if status not in {"OCR_OK", "OCR_EMPTY"}:
                        # Keep actionable engine diagnostics such as timeout
                        # visible in the page receipt instead of replacing
                        # them with one generic local-OCR failure.
                        raise ZsxqPdfError(
                            "OCR_TIMEOUT" if status == "OCR_TIMEOUT" else "LOCAL_OCR_PAGE_FAILED"
                        )
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
                processed_this_batch += 1
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
        pages_raw = _store_io(store).read_bytes(pages_relative)
        coverage = _all_pages_covered(pages, page_count)
        page_error = any(row.get("status") not in {"OCR_OK", "OCR_EMPTY"} for row in pages)
        completed_at = _iso(now()) if coverage else None
        artifact_state.update(
            status=(
                "READY"
                if coverage
                else "PARTIAL"
                if not page_error
                else "PENDING"
                if attempts + 1 < MAX_ATTEMPTS
                else "FAILED"
            ),
            pages_file_sha256=_sha256(pages_raw),
            processed_page_count=len(pages),
            ocr_page_count=sum(1 for row in pages if row.get("status") in {"OCR_OK", "OCR_EMPTY"}),
            page_statuses=[row.get("status") for row in pages],
            full_page_coverage=coverage,
            downloaded_at=downloaded_at,
            ocr_completed_at=completed_at,
            completed_at=completed_at,
            available_at=completed_at,
            late_processing=True,
            failure_class=None,
            pit_status=source["pit_status"],
            data_role=source["data_role"],
            pdf_published_at=None,
            reused=False,
            duration_seconds=round(time.monotonic() - started_monotonic, 3),
        )
        if not page_error and not coverage:
            # Successful page chunks are progress, not failed attempts. A long
            # document may therefore resume over multiple bounded hourly runs.
            artifact_state["attempts"] = attempts
            artifact_state["progress_batches"] = int(artifact_state.get("progress_batches") or 0) + 1
        artifact_state["last_error_code"] = None if coverage or not page_error else str(
            next((row.get("status") for row in reversed(pages) if row.get("status") not in {"OCR_OK", "OCR_EMPTY"}), "PAGE_COVERAGE_MISSING")
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
            "error_code": artifact_state.get("last_error_code"),
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
        permanent = code in PERMANENT_FAILURE_CODES
        artifact_state.update(
            status="FAILED" if permanent or attempts + 1 >= MAX_ATTEMPTS else "PENDING",
            failure_class="PERMANENT" if permanent else "TRANSIENT",
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
    time_budget_seconds: int = MAX_PDF_CONTINUATION_SECONDS,
    now: Callable[[], datetime] = _now,
    max_pages_per_document: int = MAX_PDF_PAGES_PER_BATCH,
    enqueue_only: bool = False,
) -> dict[str, Any]:
    """Process a bounded number of PDFs from an already completed hourly run."""
    _date(trade_date)
    _safe_run_id(source_run_id)
    if limit < 1 or limit > 100:
        raise ZsxqPdfError("PDF_BATCH_LIMIT_INVALID")
    if type(time_budget_seconds) is not int or not 1 <= time_budget_seconds <= MAX_PDF_CONTINUATION_SECONDS:
        raise ZsxqPdfError("PDF_TIME_BUDGET_INVALID")
    if type(max_pages_per_document) is not int or not 1 <= max_pages_per_document <= MAX_PDF_PAGES_PER_BATCH:
        raise ZsxqPdfError("PDF_PAGE_BATCH_LIMIT_INVALID")
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
    try:
        documents = enumerate_pdf_documents(recent, trade_date=trade_date, source_run_id=source_run_id)
    except ZsxqPdfError as error:
        if error.code != "PDF_SOURCE_ENUMERATION_INCOMPLETE":
            raise
        source_signature = _sha256(
            json.dumps(
                {"trade_date": trade_date, "slot": slot, "source_run_id": source_run_id, "input_hashes": input_hashes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        lock_budget_seconds = time_budget_seconds
        with _store_io(store).kernel_lock(
            LOCK_RELATIVE,
            timeout=lock_budget_seconds,
            poll=min(0.05, lock_budget_seconds),
        ):
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
                "enumeration_complete": False,
                "enumeration_scope": "topics_brief.files_all_topics_including_noise",
                "enumeration_error": error.code,
                "fetch_count": fetch_result.get("count"),
                "source_fetched_at": status.get("fetched_at"),
            }
            _write_json(store, STATE_RELATIVE, index)
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "slot": slot,
            "source_run_id": source_run_id,
            "cannot_confirm": [error.code],
            **SAFETY,
        }
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
        lock_budget_seconds = time_budget_seconds - (time.monotonic() - batch_start_monotonic)
        if lock_budget_seconds <= 0:
            raise ZsxqPdfError("PDF_TIME_BUDGET_EXHAUSTED")
        with _store_io(store).kernel_lock(
            LOCK_RELATIVE,
            timeout=lock_budget_seconds,
            poll=min(0.05, lock_budget_seconds),
        ):
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
                "enumeration_complete": True,
                "enumeration_scope": "topics_brief.files_all_topics_including_noise",
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

            chosen = []
            if file_id is not None:
                selected = next((row for row in documents if row["file_id"] == str(file_id)), None)
                if selected is not None:
                    engine_run = index["documents"][selected["document_key"]]["engine_runs"][engine_identity]
                    if (
                        str(engine_run.get("status") or "").upper() == "READY"
                        or engine_run.get("failure_class") != "PERMANENT"
                    ):
                        chosen = [selected]
                    elif engine_run.get("last_error_code") == "PDF_PAGE_LIMIT_EXCEEDED":
                        previous_recovery = engine_run.get("page_limit_recovery")
                        previous_attempts = (
                            previous_recovery.get("revalidation_attempts")
                            if isinstance(previous_recovery, Mapping)
                            and previous_recovery.get("status") == "RETRYABLE"
                            and type(previous_recovery.get("revalidation_attempts")) is int
                            else 0
                        )
                        revalidation_attempts = previous_attempts + 1
                        transient_recovery_failure = False
                        try:
                            verified = _verified_page_limit_recovery(
                                store,
                                selected,
                                engine_run,
                                processing_root,
                                cli=Path(cli),
                                metadata_lookup=metadata,
                                url_lookup=get_url,
                                downloader=get_bytes,
                                page_counter=count_pages,
                            )
                        except ZsxqPdfError as error:
                            if error.code != PAGE_LIMIT_RECOVERY_TRANSIENT_CODE:
                                raise
                            verified = None
                            transient_recovery_failure = True
                        if verified is None:
                            if transient_recovery_failure and revalidation_attempts < MAX_ATTEMPTS:
                                recovery_status = "RETRYABLE"
                                recovery_reason = PAGE_LIMIT_RECOVERY_TRANSIENT_CODE
                            elif transient_recovery_failure:
                                recovery_status = "REJECTED"
                                recovery_reason = "PDF_RECOVERY_RETRY_EXHAUSTED"
                            else:
                                recovery_status = "REJECTED"
                                recovery_reason = "PDF_RECOVERY_SOURCE_REVALIDATION_FAILED"
                            engine_run["page_limit_recovery"] = {
                                "status": recovery_status,
                                "prior_error_code": "PDF_PAGE_LIMIT_EXCEEDED",
                                "reason_code": recovery_reason,
                                "revalidation_attempts": revalidation_attempts,
                                "source_run_id": source_run_id,
                                "processing_run_id": processing_run_id,
                                "checked_at": _iso(now()),
                            }
                            engine_run["updated_at"] = _iso(now())
                            _write_json(store, STATE_RELATIVE, index)
                        else:
                            raw, pdf_sha, observed_pages, pdf_path = verified
                            engine_run.update(
                                status="PENDING",
                                failure_class=None,
                                last_error_code=None,
                                file_id=selected["file_id"],
                                pdf_path=f"{processing_root}/pdfs/{selected['document_key']}.pdf",
                                pdf_size=len(raw),
                                pdf_sha256=pdf_sha,
                                source_hash_raw=selected.get("source_hash_raw"),
                                page_count=observed_pages,
                                real_pdf_path=str(pdf_path),
                                page_limit_recovery={
                                    "status": "VERIFIED",
                                    "prior_error_code": "PDF_PAGE_LIMIT_EXCEEDED",
                                    "revalidation_attempts": revalidation_attempts,
                                    "observed_page_count": observed_pages,
                                    "pdf_sha256": pdf_sha,
                                    "verification_method": "METADATA_VALIDATED_REFETCH_SHA256_MATCH",
                                    "source_run_id": source_run_id,
                                    "processing_run_id": processing_run_id,
                                    "verified_at": _iso(now()),
                                },
                                updated_at=_iso(now()),
                            )
                            _write_json(store, STATE_RELATIVE, index)
                            chosen = [selected]
            else:
                chosen = []
                if not enqueue_only:
                    for source in documents:
                        engine_run = index["documents"][source["document_key"]]["engine_runs"][engine_identity]
                        if _engine_run_is_retryable(engine_run):
                            chosen.append(source)
                        if len(chosen) >= limit:
                            break
            for source in chosen:
                if time.monotonic() - batch_start_monotonic >= time_budget_seconds:
                    break
                document_row = index["documents"][source["document_key"]]
                engine_run = document_row["engine_runs"][engine_identity]
                cache = index["ocr_cache"]

                def persist_current() -> None:
                    _write_json(store, STATE_RELATIVE, index)

                _graph_context(run_id=processing_run_id + ":" + source["document_key"], business_date=trade_date)
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
                    max_pages_per_batch=max_pages_per_document,
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
                _graph_notify("ZSXQ_PDF", "zsxq_pdf", trade_date, "COMMITTED",
                              run_id=processing_run_id + ":" + source["document_key"],
                              source_path=store.root / f"{processing_root}/processing_receipt.json")
            def queue_counts() -> tuple[int, int, int, int]:
                runs = [
                    latest[1]
                    for entry in index["documents"].values()
                    if isinstance(entry, Mapping)
                    for latest in [_latest_engine_run(entry)]
                    if latest is not None
                ]
                ready_count = sum(1 for run in runs if run.get("status") == "READY")
                pending_count = sum(1 for run in runs if run.get("status") in {"PENDING", "PROCESSING"})
                failed_count = sum(1 for run in runs if run.get("status") == "FAILED")
                partial_count = sum(1 for run in runs if run.get("status") == "PARTIAL")
                return ready_count, partial_count, failed_count, pending_count

            ready_count, partial_count, failed_count, pending_count = queue_counts()
            if not outcomes:
                outcomes = []
                if pending_count:
                    result_status = "PENDING"
                elif failed_count or partial_count:
                    result_status = "PARTIAL" if ready_count or partial_count else "FAILED"
                else:
                    result_status = "READY_EMPTY" if not documents else "READY"
                batch_receipt = {
                    "schema_version": "v4.zsxq_pdf_batch_receipt.v1",
                    "status": result_status,
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
                    "done_total": ready_count,
                    "partial_total": partial_count,
                    "pending_total": pending_count,
                    "failed_total": failed_count,
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
            else:
                ready_count, partial_count, failed_count, pending_count = queue_counts()
                if pending_count:
                    result_status = "PARTIAL" if outcomes or ready_count or failed_count or partial_count else "PENDING"
                elif failed_count or partial_count:
                    result_status = "PARTIAL" if ready_count or partial_count else "FAILED"
                else:
                    result_status = "READY" if ready_count else "READY_EMPTY"
                batch_receipt["status"] = result_status
                batch_receipt["done_total"] = ready_count
                batch_receipt["partial_total"] = partial_count
                batch_receipt["pending_total"] = pending_count
                batch_receipt["failed_total"] = failed_count
                batch_receipt["batch_completed_at"] = _iso(now())
                batch_receipt["batch_duration_seconds"] = round(time.monotonic() - batch_start_monotonic, 3)
                _write_json(store, f"{processing_root}/processing_receipt.json", batch_receipt)
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
            "done_total": batch_receipt.get("done_total", ready_count),
            "partial_total": batch_receipt.get("partial_total", partial_count),
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


def pending_pdf_tasks(
    data_root: Path,
    *,
    exclude_source_run_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Return only already-enumerated, retryable work from the owned index."""
    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ZsxqPdfError("DATA_ROOT_INVALID")
    index = _read_index(NativeDataStore(root))
    excluded = set(exclude_source_run_ids)
    tasks: list[dict[str, Any]] = []
    verified_sources: dict[str, tuple[str, bool]] = {}
    for document_id, row in index["documents"].items():
        if not isinstance(row, Mapping) or not isinstance(row.get("source"), Mapping):
            continue
        source = row["source"]
        source_run_id = str(source.get("source_run_id") or "")
        if source_run_id in excluded:
            continue
        source_meta = index["sources"].get(source_run_id)
        latest = _latest_engine_run(row)
        if not isinstance(source_meta, Mapping) or latest is None:
            continue
        if source_run_id not in verified_sources:
            try:
                source_date = _date(str(source.get("trade_date") or ""))
                source_slot = str(source_meta.get("slot") or "")
                _status, _fetch, _recent, _summary, hashes = _source_binding(
                    NativeDataStore(root),
                    trade_date=source_date,
                    slot=source_slot,
                    source_run_id=source_run_id,
                )
                signature = _sha256(
                    json.dumps(
                        {"trade_date": source_date, "slot": source_slot, "source_run_id": source_run_id, "input_hashes": hashes},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                verified_sources[source_run_id] = (
                    "",
                    dict(source_meta.get("input_sha256") or {}) == hashes
                    and source_meta.get("source_signature") == signature
                    and source_meta.get("trade_date") == source_date,
                )
            except Exception as error:
                verified_sources[source_run_id] = (_error_code(error), False)
        if not verified_sources[source_run_id][1]:
            continue
        _engine_identity, run = latest
        status = str(run.get("status") or "").upper()
        retryable = _engine_run_is_retryable(run)
        if not retryable and run.get("last_error_code") == "PDF_PAGE_LIMIT_EXCEEDED":
            engine_prefix = _engine_identity[:12]
            expected_processing_run_id = (
                f"pdfproc_{source_run_id}_{str(source_meta.get('source_signature') or '')[:12]}_{engine_prefix}"
            )
            processing_run_id = str(source_meta.get("processing_run_id") or "")
            if processing_run_id == expected_processing_run_id and re.fullmatch(
                r"[A-Za-z0-9_-]{1,100}", processing_run_id
            ):
                processing_root = f"external_sources/zsxq_hourly/{processing_run_id}"
                retryable = _page_limit_recovery_candidate(
                    NativeDataStore(root),
                    source,
                    run,
                    processing_root,
                ) is not None
        if not retryable:
            continue
        try:
            _date(str(source.get("trade_date") or ""))
            _safe_run_id(source_run_id)
            file_id = str(source.get("file_id") or "")
            if not re.fullmatch(r"[0-9]{1,32}", file_id):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(document_id)):
                continue
        except ZsxqPdfError:
            continue
        tasks.append(
            {
                "document_id": str(document_id),
                "source_run_id": source_run_id,
                "trade_date": str(source["trade_date"]),
                "slot": str(source_meta.get("slot") or ""),
                "file_id": file_id,
                "source_fetched_at": str(source.get("source_fetched_at") or ""),
                "status": status,
            }
        )
    return sorted(tasks, key=lambda row: (row["source_fetched_at"], row["trade_date"], row["slot"], row["document_id"]))


def _retry_backoff_remaining(
    artifact: Mapping[str, Any], *, now: datetime, backoff_seconds: int
) -> int:
    if not artifact.get("last_error_code"):
        return 0
    updated_at = artifact.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        return backoff_seconds
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return backoff_seconds
    if updated.tzinfo is None or now.tzinfo is None or now.utcoffset() is None:
        return backoff_seconds
    elapsed = (now.astimezone(updated.tzinfo) - updated).total_seconds()
    return max(0, int(backoff_seconds - elapsed + 0.999))


def process_next_pdf_task(
    data_root: Path,
    *,
    cli: Path = DEFAULT_CLI,
    time_budget_seconds: int = 90,
    max_pages_per_document: int = MAX_PDF_PAGES_PER_BATCH,
    retry_backoff_seconds: int = PDF_QUEUE_RETRY_BACKOFF_SECONDS,
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Advance one already-enumerated PDF from the durable owned index."""
    if type(time_budget_seconds) is not int or not 1 <= time_budget_seconds <= MAX_PDF_CONTINUATION_SECONDS:
        raise ZsxqPdfError("PDF_TIME_BUDGET_INVALID")
    if type(max_pages_per_document) is not int or not 1 <= max_pages_per_document <= MAX_PDF_PAGES_PER_BATCH:
        raise ZsxqPdfError("PDF_PAGE_BATCH_LIMIT_INVALID")
    if type(retry_backoff_seconds) is not int or not 1 <= retry_backoff_seconds <= 3600:
        raise ZsxqPdfError("PDF_RETRY_BACKOFF_INVALID")

    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ZsxqPdfError("DATA_ROOT_INVALID")
    tasks = pending_pdf_tasks(root)
    if not tasks:
        return {
            "schema_version": "v4.zsxq_pdf_queue_tick.v1",
            "status": "NO_RETRYABLE_TASKS",
            "processed_document_count": 0,
            "pending_task_count": 0,
            "time_budget_seconds": time_budget_seconds,
            "max_pages_per_document": max_pages_per_document,
            "retry_backoff_seconds": retry_backoff_seconds,
            **SAFETY,
        }

    store = NativeDataStore(root)
    index = _read_index(store)
    now_value = now()
    eligible: list[dict[str, Any]] = []
    retry_waits: list[int] = []
    for task in tasks:
        document = index["documents"].get(task["document_id"])
        latest = _latest_engine_run(document) if isinstance(document, Mapping) else None
        artifact = latest[1] if latest else {}
        remaining = _retry_backoff_remaining(
            artifact, now=now_value, backoff_seconds=retry_backoff_seconds
        )
        if remaining:
            retry_waits.append(remaining)
            continue
        eligible.append(task)
    if not eligible:
        return {
            "schema_version": "v4.zsxq_pdf_queue_tick.v1",
            "status": "RETRY_BACKOFF",
            "processed_document_count": 0,
            "pending_task_count": len(tasks),
            "retry_wait_count": len(retry_waits),
            "next_retry_seconds": min(retry_waits) if retry_waits else retry_backoff_seconds,
            "time_budget_seconds": time_budget_seconds,
            "max_pages_per_document": max_pages_per_document,
            "retry_backoff_seconds": retry_backoff_seconds,
            **SAFETY,
        }

    task = eligible[0]
    document_id = task["document_id"]
    document = index["documents"].get(document_id)
    latest = _latest_engine_run(document) if isinstance(document, Mapping) else None
    before = dict(latest[1]) if latest else {}
    try:
        batch = process_pdf_batch(
            data_root=root,
            trade_date=task["trade_date"],
            slot=task["slot"],
            source_run_id=task["source_run_id"],
            cli=cli,
            limit=1,
            file_id=task["file_id"],
            max_pages_per_document=max_pages_per_document,
            time_budget_seconds=time_budget_seconds,
            now=now,
        )
    except Exception as error:
        return {
            "schema_version": "v4.zsxq_pdf_queue_tick.v1",
            "status": "CANNOT_CONFIRM",
            "document_id": document_id,
            "trade_date": task["trade_date"],
            "source_run_id": task["source_run_id"],
            "reason_code": _error_code(error),
            "processed_document_count": 0,
            "pending_task_count": len(tasks),
            "time_budget_seconds": time_budget_seconds,
            "max_pages_per_document": max_pages_per_document,
            **SAFETY,
        }

    latest_index = _read_index(store)
    latest_document = latest_index["documents"].get(document_id)
    latest_run = _latest_engine_run(latest_document) if isinstance(latest_document, Mapping) else None
    artifact = latest_run[1] if latest_run else {}
    document_status = str(artifact.get("status") or "CANNOT_CONFIRM").upper()
    remaining = _retry_backoff_remaining(
        artifact, now=now(), backoff_seconds=retry_backoff_seconds
    )
    status = "RETRY_BACKOFF" if remaining and document_status in {"PENDING", "FAILED"} else document_status
    outcomes = batch.get("processed_this_batch") or []
    return {
        "schema_version": "v4.zsxq_pdf_queue_tick.v1",
        "status": status,
        "document_status": document_status,
        "document_id": document_id,
        "trade_date": task["trade_date"],
        "slot": task["slot"],
        "source_run_id": task["source_run_id"],
        "processed_document_count": int(bool(outcomes)),
        "processed_page_count": artifact.get("processed_page_count"),
        "page_count": artifact.get("page_count"),
        "last_error_code": artifact.get("last_error_code"),
        "failure_class": artifact.get("failure_class"),
        "pdf_sha256": artifact.get("pdf_sha256"),
        "pages_file_sha256": artifact.get("pages_file_sha256"),
        "receipt_path": artifact.get("receipt_path"),
        "done_total": batch.get("done_total"),
        "partial_total": batch.get("partial_total"),
        "failed_total": batch.get("failed_total"),
        "pending_total": batch.get("pending_total"),
        "pending_task_count": len(pending_pdf_tasks(root)),
        "retry_after_seconds": remaining,
        "before_status": before.get("status"),
        "before_attempts": before.get("attempts"),
        "time_budget_seconds": time_budget_seconds,
        "max_pages_per_document": max_pages_per_document,
        "retry_backoff_seconds": retry_backoff_seconds,
        **SAFETY,
    }


def process_pdf_continuation(
    *,
    data_root: Path,
    trade_date: str,
    slot: str,
    source_run_id: str,
    cli: Path = DEFAULT_CLI,
    max_documents: int = MAX_PDF_CONTINUATION_DOCUMENTS,
    time_budget_seconds: int = MAX_PDF_CONTINUATION_SECONDS,
) -> dict[str, Any]:
    """Advance the exact current run plus one older pending item within a fixed budget."""
    _date(trade_date)
    _safe_run_id(source_run_id)
    if type(max_documents) is not int or not 1 <= max_documents <= MAX_PDF_CONTINUATION_DOCUMENTS:
        raise ZsxqPdfError("PDF_CONTINUATION_LIMIT_INVALID")
    if type(time_budget_seconds) is not int or not 1 <= time_budget_seconds <= MAX_PDF_CONTINUATION_SECONDS:
        raise ZsxqPdfError("PDF_TIME_BUDGET_INVALID")
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    remaining_documents = max_documents
    try:
        enqueued = process_pdf_batch(
            data_root=data_root,
            trade_date=trade_date,
            slot=slot,
            source_run_id=source_run_id,
            cli=cli,
            limit=1,
            enqueue_only=True,
            time_budget_seconds=time_budget_seconds,
        )
        results.append(enqueued)
    except Exception as error:
        results.append({"status": "CANNOT_CONFIRM", "error_code": _error_code(error), "source_run_id": source_run_id})

    if remaining_documents > 0 and time.monotonic() - started < time_budget_seconds:
        try:
            queued_tasks = pending_pdf_tasks(data_root)
        except Exception as error:
            queued_tasks = []
            results.append({"status": "CANNOT_CONFIRM", "error_code": _error_code(error), "source": "pending_index"})
        if queued_tasks:
            task = queued_tasks[0]
            remaining = max(1, int(time_budget_seconds - (time.monotonic() - started)))
            try:
                outcome = process_pdf_batch(
                    data_root=data_root,
                    trade_date=task["trade_date"],
                    slot=task["slot"],
                    source_run_id=task["source_run_id"],
                    cli=cli,
                    limit=1,
                    file_id=task["file_id"],
                    max_pages_per_document=1,
                    time_budget_seconds=remaining,
                )
            except Exception as error:
                outcome = {
                    "status": "CANNOT_CONFIRM",
                    "error_code": _error_code(error),
                    "source_run_id": task["source_run_id"],
                    "document_id": task["document_id"],
                }
            results.append(outcome)
            remaining_documents -= len(outcome.get("processed_this_batch") or [])

    try:
        index = _read_index(NativeDataStore(Path(data_root).expanduser()))
        latest_runs = [
            latest[1]
            for document in index["documents"].values()
            if isinstance(document, Mapping)
            for latest in [_latest_engine_run(document)]
            if latest is not None
        ]
        done_total = sum(1 for row in latest_runs if row.get("status") == "READY")
        partial_total = sum(1 for row in latest_runs if row.get("status") == "PARTIAL")
        failed_total = sum(1 for row in latest_runs if row.get("status") == "FAILED")
        pending_total = sum(1 for row in latest_runs if row.get("status") in {"PENDING", "PROCESSING"})
    except Exception as error:
        done_total = partial_total = failed_total = pending_total = 0
        results.append({"status": "CANNOT_CONFIRM", "error_code": _error_code(error), "source": "processing_index"})
    if pending_total:
        processed_document_count = sum(len(row.get("processed_this_batch") or []) for row in results)
        status = "PARTIAL" if processed_document_count or done_total or failed_total or partial_total else "PENDING"
    elif failed_total or partial_total:
        status = "PARTIAL" if done_total or partial_total else "FAILED"
    else:
        status = "READY" if done_total else "READY_EMPTY"
    if any(row.get("status") == "CANNOT_CONFIRM" for row in results) and not any(row.get("processed_this_batch") for row in results):
        status = "CANNOT_CONFIRM"
    return {
        "schema_version": "v4.zsxq_pdf_continuation.v1",
        "status": status,
        "trade_date": trade_date,
        "slot": slot,
        "source_run_id": source_run_id,
        "processed_document_count": sum(len(row.get("processed_this_batch") or []) for row in results),
        "done_total": done_total,
        "partial_total": partial_total,
        "failed_total": failed_total,
        "pending_total": pending_total,
        "max_documents": max_documents,
        "time_budget_seconds": time_budget_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "batches": results,
        **SAFETY,
    }


def _aggregate_projection_status(counts: Mapping[str, int], *, materialized: bool) -> str:
    if not materialized:
        return "NOT_MATERIALIZED"
    done = counts.get("completed_count", 0)
    partial = counts.get("partial_count", 0)
    failed = counts.get("failed_count", 0)
    pending = counts.get("pending_count", 0)
    cannot = counts.get("cannot_confirm_count", 0)
    if cannot and not any((done, partial, failed, pending)):
        return "CANNOT_CONFIRM"
    if pending:
        return "PARTIAL" if any((done, partial, failed, cannot)) else "PENDING"
    if partial or failed or cannot:
        return "PARTIAL" if any((done, partial)) else "FAILED" if failed else "CANNOT_CONFIRM"
    return "READY" if done else "READY_EMPTY"


def read_pdf_ingestion_projection(data_root: Path, research_date: str) -> dict[str, Any]:
    """Read exact-date metadata and short excerpts; never downloads or invokes OCR."""
    try:
        selected_date = _date(research_date)
        root = Path(data_root).expanduser()
        if not root.is_dir() or root.is_symlink():
            raise ZsxqPdfError("DATA_ROOT_INVALID")
        store = NativeDataStore(root)
        index_path = _safe_artifact_path(root, STATE_RELATIVE)
        if not index_path.is_file():
            return {
                "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                "status": "NOT_ASSESSED",
                "research_date": selected_date,
                "items": [],
                "cannot_confirm": ["PDF_SOURCE_ENUMERATION_MISSING", "PDF_INGESTION_NOT_MATERIALIZED"],
                **SAFETY,
            }
        index = _read_index(store)
        items: list[dict[str, Any]] = []
        cannot_confirm: list[str] = []
        for document_id, row in index["documents"].items():
            if not isinstance(row, Mapping) or not isinstance(row.get("source"), Mapping):
                continue
            source_stub = row["source"]
            if source_stub.get("trade_date") != selected_date:
                continue
            source_fields = (
                "trade_date", "source_run_id", "group_id", "group_name", "topic_id", "topic_title",
                "source_topic_published_at", "source_fetched_at", "file_id", "original_filename",
                "expected_size", "pdf_published_at", "pit_status", "data_role", "late_processing",
            )
            try:
                source, verified_row = _source_row_for_document(store, index, str(document_id))
                latest = _latest_engine_run(verified_row)
                artifact = latest[1] if latest else {}
                status = str(artifact.get("status") or "PENDING").upper()
                if status == "PROCESSING":
                    status = "PENDING"
                detail: dict[str, Any] | None = None
                if artifact.get("receipt_path") and artifact.get("pages_path") and artifact.get("pdf_path"):
                    try:
                        detail = _verified_document_detail(store, index, str(document_id), verify_pdf=False)
                    except ZsxqPdfError as error:
                        if status == "READY":
                            status = "CANNOT_CONFIRM"
                            cannot_confirm.append(error.code)
                elif status == "READY":
                    status = "CANNOT_CONFIRM"
                    cannot_confirm.append("COMPLETED_ARTIFACT_RECEIPT_MISSING")
                if status not in {"READY", "PARTIAL", "FAILED", "PENDING", "CANNOT_CONFIRM"}:
                    status = "CANNOT_CONFIRM"
                    cannot_confirm.append("DOCUMENT_STATUS_INVALID")
                item = {
                    "document_id": str(document_id),
                    "research_date": selected_date,
                    "status": status,
                    "source": {key: source.get(key) for key in source_fields},
                    "page_count": (detail or {}).get("processing", {}).get("page_count", artifact.get("page_count")),
                    "processed_page_count": (detail or {}).get("processing", {}).get("processed_page_count", artifact.get("processed_page_count")),
                    "downloaded_at": artifact.get("downloaded_at"),
                    "ocr_started_at": artifact.get("ocr_started_at"),
                    "ocr_completed_at": artifact.get("ocr_completed_at"),
                    "completed_at": artifact.get("completed_at"),
                    "available_at": artifact.get("available_at"),
                    "engine": (detail or {}).get("processing", {}).get("engine"),
                    "excerpt": (detail or {}).get("excerpt", ""),
                    "last_page_excerpt": (detail or {}).get("last_page_excerpt", ""),
                    "reason_code": artifact.get("last_error_code") or (cannot_confirm[-1] if status == "CANNOT_CONFIRM" and cannot_confirm else None),
                    "can_open_detail": bool(detail),
                }
                items.append(item)
            except ZsxqPdfError as error:
                cannot_confirm.append(error.code)
                items.append({
                    "document_id": str(document_id),
                    "research_date": selected_date,
                    "status": "CANNOT_CONFIRM",
                    "reason_code": error.code,
                    "source": {},
                    "can_open_detail": False,
                })
        if not items:
            sources = index.get("sources")
            date_sources = {
                str(source_run_id): row
                for source_run_id, row in (sources.items() if isinstance(sources, Mapping) else [])
                if isinstance(row, Mapping) and row.get("trade_date") == selected_date
            }
            if not date_sources:
                return {
                    "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                    "status": "NOT_ASSESSED",
                    "research_date": selected_date,
                    "items": [],
                    "cannot_confirm": ["PDF_SOURCE_ENUMERATION_MISSING"],
                    **SAFETY,
                }
            try:
                enumerated_total = sum(
                    _verified_source_enumeration(store, index, source_run_id, source_entry)
                    for source_run_id, source_entry in date_sources.items()
                )
            except ZsxqPdfError as error:
                return {
                    "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                    "status": "CANNOT_CONFIRM",
                    "research_date": selected_date,
                    "items": [],
                    "cannot_confirm": sorted({"PDF_SOURCE_ENUMERATION_MISSING", error.code}),
                    **SAFETY,
                }
            if enumerated_total != 0:
                return {
                    "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                    "status": "CANNOT_CONFIRM",
                    "research_date": selected_date,
                    "items": [],
                    "cannot_confirm": ["PDF_SOURCE_ENUMERATION_MISSING"],
                    **SAFETY,
                }
            return {
                "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                "status": "READY_EMPTY",
                "research_date": selected_date,
                "completed_count": 0,
                "done_count": 0,
                "partial_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "cannot_confirm_count": 0,
                "total_count": 0,
                "enumeration_source_run_count": len(date_sources),
                "items": [],
                "cannot_confirm": [],
                **SAFETY,
            }
        items.sort(key=lambda row: (str((row.get("source") or {}).get("source_topic_published_at") or ""), str(row.get("document_id") or "")), reverse=True)
        counts = {
            "completed_count": sum(1 for row in items if row.get("status") == "READY"),
            "partial_count": sum(1 for row in items if row.get("status") == "PARTIAL"),
            "failed_count": sum(1 for row in items if row.get("status") == "FAILED"),
            "pending_count": sum(1 for row in items if row.get("status") == "PENDING"),
            "cannot_confirm_count": sum(1 for row in items if row.get("status") == "CANNOT_CONFIRM"),
            "total_count": len(items),
        }
        if not items:
            cannot_confirm.append(f"NO_PDF_REFERENCES_ENUMERATED:{selected_date}")
        return {
            "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
            "status": _aggregate_projection_status(counts, materialized=True),
            "research_date": selected_date,
            **counts,
            "done_count": counts["completed_count"],
            "items": items,
            "cannot_confirm": sorted(set(cannot_confirm)),
            **SAFETY,
        }
    except ZsxqPdfError as error:
        selected = research_date if isinstance(research_date, str) else ""
        return {
            "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
            "status": "CANNOT_CONFIRM",
            "research_date": selected,
            "items": [],
            "cannot_confirm": sorted({"PDF_SOURCE_ENUMERATION_MISSING", error.code}),
            **SAFETY,
        }


def read_pdf_document_detail(data_root: Path, document_id: str, research_date: str) -> dict[str, Any]:
    """Return verified stored page text for one exact-date document, read-only."""
    selected_date = _date(research_date)
    if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{64}", document_id):
        raise ZsxqPdfError("DOCUMENT_ID_INVALID")
    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ZsxqPdfError("DATA_ROOT_INVALID")
    store = NativeDataStore(root)
    index = _read_index(store)
    source, _row = _source_row_for_document(store, index, document_id)
    if source.get("trade_date") != selected_date:
        raise ZsxqPdfError("DOCUMENT_DATE_MISMATCH")
    detail = _verified_document_detail(store, index, document_id, verify_pdf=True)
    detail["schema_version"] = "v4.zsxq_pdf_document_detail.v1"
    return detail


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
    parser.add_argument("--pdf-time-budget-seconds", type=int, default=MAX_PDF_CONTINUATION_SECONDS)
    args = parser.parse_args(argv)
    try:
        if args.pdf_file_id:
            result = process_pdf_batch(
                data_root=args.data_root,
                trade_date=args.date,
                slot=args.slot,
                source_run_id=args.source_run_id,
                cli=args.cli,
                limit=1,
                file_id=args.pdf_file_id,
                time_budget_seconds=args.pdf_time_budget_seconds,
            )
        else:
            result = process_pdf_continuation(
                data_root=args.data_root,
                trade_date=args.date,
                slot=args.slot,
                source_run_id=args.source_run_id,
                cli=args.cli,
                max_documents=args.pdf_limit,
                time_budget_seconds=args.pdf_time_budget_seconds,
            )
    except Exception as error:
        code = _error_code(error)
        print(json.dumps({"status": "CANNOT_CONFIRM", "error_code": code, **SAFETY}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
