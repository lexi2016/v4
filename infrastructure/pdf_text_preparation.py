"""Resumable, source-bound preparation of PDF page text before model use."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import os
import re
import tempfile
from typing import Any, Callable, Mapping, Sequence

from infrastructure import pdf_research


PREPARED_ROOT = pdf_research.PDF_RESEARCH_STATE_ROOT / "prepared"
PREPARED_MANIFEST_NAME = "prepared-text-manifest.json"
RUN_SCHEMA = "v4.pdf_research_text_preparation.run.v1"
PAGE_SCHEMA = "v4.pdf_research_text_preparation.page_checkpoint.v1"
DOCUMENT_SCHEMA = "v4.pdf_research_text_preparation.document.v1"
MANIFEST_SCHEMA = "v4.pdf_research_text_preparation.manifest.v1"
PAGE_INPUT_SCHEMA = "v4.pdf_research_simple_batch.page_input.v1"
RUN_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,63}\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
SUCCESS_REPORT_STATUSES = frozenset(
    {
        "USER_ACCEPTED_REUSED_REPORT",
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
    }
)
TERMINAL_STATUSES = frozenset({"READY", "QUARANTINED", "FAILED"})
FATAL_SOURCE_CODES = frozenset(
    {
        "SOURCE_PDF_CHANGED_DURING_HASH",
        "SOURCE_PDF_BINDING_MISMATCH",
        "NATIVE_EXTRACTION_PDF_SHA_MISMATCH",
        "NATIVE_EXTRACTION_PAGE_COUNT_MISMATCH",
        "PAGE_IMAGE_PDF_SHA_MISMATCH",
        "PREPARATION_EXTRACTOR_IDENTITY_DRIFT",
        "PREPARATION_PARENT_MANIFEST_DRIFT",
        "IMMUTABLE_ARTIFACT_CONFLICT",
        "PREPARATION_OUTPUT_COLLISION",
        "PREPARATION_RESUME_PAGE_BINDING_MISMATCH",
        "PAGE_CHECKPOINT_BINDING_MISMATCH",
        "PAGE_CHECKPOINT_TEXT_SHA_MISMATCH",
    }
)
CONTACT_PATTERN = re.compile(
    r"(?:\b1[3-9]\d{9}\b|\b\+?\d[\d ()-]{7,}\d\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:www\.|https?://)[^\s]+|微信|電話|电话|郵箱|邮箱|傳真|传真|地址|聯絡|联系)",
    re.IGNORECASE,
)
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)


class PreparationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise PreparationError("PREPARATION_INPUT_NOT_REGULAR")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise PreparationError(code)
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PreparationError(code) from None
    if not isinstance(value, dict):
        raise PreparationError(code)
    return value, raw


def _relative_path(root: Path, value: Any, code: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise PreparationError(code)
    relative = Path(value)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise PreparationError(code)
    root_resolved = root.resolve(strict=True)
    candidate = root / relative
    try:
        candidate.resolve(strict=False).relative_to(root_resolved)
    except ValueError:
        raise PreparationError(code) from None
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PreparationError(code)
    return candidate


def _atomic_json(path: Path, value: Mapping[str, Any], root: Path) -> str:
    raw = canonical_json(value) + b"\n"
    if path.is_symlink():
        raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE")
    try:
        path.parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError:
        raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE") from None
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return sha256_bytes(raw)


def _meaningful_units(text: str) -> tuple[str, list[str], int]:
    normalized = "".join(ch.casefold() for ch in text if ch.isalnum() or HAN_RE.fullmatch(ch))
    han = [ch for ch in normalized if HAN_RE.fullmatch(ch)]
    han_bigrams = [han[index] + han[index + 1] for index in range(len(han) - 1)]
    latin = LATIN_TOKEN_RE.findall(normalized)
    units = set(han_bigrams) | {token.casefold() for token in latin}
    meaningful_characters = sum(1 for ch in text if ch.isalnum() or HAN_RE.fullmatch(ch))
    return normalized, sorted(units), meaningful_characters


def assess_text_quality(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        return {"status": "BLOCKED", "reason": "PAGE_TEXT_TYPE_INVALID", "meaningful_characters": 0, "unique_units": 0}
    normalized, units, meaningful = _meaningful_units(text)
    lines = [re.sub(r"\W+", "", line.casefold()) for line in text.splitlines()]
    nonempty_lines = [line for line in lines if line]
    repeated_line_fraction = (
        1.0 - len(set(nonempty_lines)) / len(nonempty_lines) if nonempty_lines else 0.0
    )
    contact_matches = sorted({match.casefold() for match in CONTACT_PATTERN.findall(text)})
    if not normalized:
        status, reason = "BLOCKED", "PAGE_TEXT_EMPTY"
    elif meaningful <= 128 and len(units) <= 6:
        status, reason = "LOW_INFORMATION", "SPARSE_TEXT_NEEDS_CONTEXT"
    else:
        status, reason = "PASS", None
    return {
        "status": status,
        "reason": reason,
        "meaningful_characters": meaningful,
        "unique_units": len(units),
        "normalized_sha256": sha256_bytes(normalized.encode("utf-8")),
        "repeated_line_fraction": round(repeated_line_fraction, 6),
        "contact_markers": contact_matches,
    }


def assess_document_pages(pages: Sequence[pdf_research.PageText]) -> dict[int, dict[str, Any]]:
    assessments = {page.page_number: assess_text_quality(page.text) for page in pages}
    signatures = Counter(
        assessment["normalized_sha256"]
        for page in pages
        if (assessment := assessments[page.page_number])["status"] != "BLOCKED"
        and assessment["meaningful_characters"] <= 160
    )
    contact_counts: Counter[str] = Counter()
    for page in pages:
        assessment = assessments[page.page_number]
        if assessment["meaningful_characters"] <= 160:
            contact_counts.update(assessment["contact_markers"])
    repeated_signatures = {
        signature
        for signature, count in signatures.items()
        if count >= max(2, math.ceil(len(pages) * 0.6))
    }
    repeated_contacts = {
        marker
        for marker, count in contact_counts.items()
        if count >= max(2, math.ceil(len(pages) * 0.6))
    }
    for page in pages:
        assessment = assessments[page.page_number]
        repeated_page = assessment["normalized_sha256"] in repeated_signatures
        repeated_contact = bool(set(assessment["contact_markers"]) & repeated_contacts)
        assessment["repeated_short_page"] = repeated_page
        assessment["repeated_contact_page"] = repeated_contact
        assessment["needs_context"] = bool(
            repeated_page
            or repeated_contact and assessment["meaningful_characters"] <= 160
            or assessment["status"] == "LOW_INFORMATION"
        )
        if repeated_page:
            assessment["reason"] = "REPEATED_SHORT_PAGE_WATERMARK_OR_HEADER"
        elif repeated_contact and assessment["meaningful_characters"] <= 160:
            assessment["reason"] = "REPEATED_CONTACT_ONLY_PAGE"
    return assessments


def cached_text_replaces_native(
    native_text: str,
    cached_text: str,
    *,
    native_assessment: Mapping[str, Any],
    cached_assessment: Mapping[str, Any],
) -> bool:
    if cached_assessment.get("status") != "PASS" or not cached_text.strip():
        return False
    if not native_text.strip() or native_assessment.get("status") == "BLOCKED":
        return True
    if not native_assessment.get("needs_context"):
        return False
    return (
        cached_assessment.get("meaningful_characters", 0)
        >= native_assessment.get("meaningful_characters", 0) + 32
        and cached_assessment.get("unique_units", 0)
        > native_assessment.get("unique_units", 0)
    )


def inspect_page_images(
    pdf_path: Path,
    *,
    pdf_sha256: str,
    page_count: int,
    page_numbers: Sequence[int],
) -> dict[int, bool | None]:
    """Read image presence only for suspicious pages; no rendering or OCR."""
    if not page_numbers:
        return {}
    helper = pdf_research._pinned_pdf_pages_helper()
    pypdf = helper.pinned_pypdf()
    try:
        raw = pdf_path.read_bytes()
        if sha256_bytes(raw) != pdf_sha256:
            raise PreparationError("PAGE_IMAGE_PDF_SHA_MISMATCH")
        reader = pypdf.PdfReader(__import__("io").BytesIO(raw), strict=False)
        if len(reader.pages) != page_count:
            raise PreparationError("NATIVE_EXTRACTION_PAGE_COUNT_MISMATCH")
    except PreparationError:
        raise
    except Exception:
        return {page_number: None for page_number in page_numbers}
    result: dict[int, bool | None] = {}
    for page_number in page_numbers:
        try:
            images = reader.pages[page_number - 1].images
            result[page_number] = bool(len(images))
        except Exception:
            result[page_number] = None
    return result


def _extractor_identity(batch: Any) -> dict[str, Any]:
    paths = {
        "batch_runner": Path(batch.__file__),
        "pdf_research": Path(pdf_research.__file__),
        "preparation": Path(__file__),
        "pinned_pdf_helper": Path(pdf_research.PDF_PAGES_HELPER_PATH),
        "pinned_pdf_dependency_manifest": Path(pdf_research.PDF_PAGES_HELPER_PATH).parent / "_vendor/DEPENDENCY_MANIFEST.json",
    }
    sources: dict[str, Any] = {}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise PreparationError("PREPARATION_EXTRACTOR_IDENTITY_UNAVAILABLE")
        sources[name] = {"path": str(path), "sha256": _file_sha256(path)}
    if sources["pinned_pdf_helper"]["sha256"] != pdf_research.PDF_PAGES_HELPER_SHA256:
        raise PreparationError("PREPARATION_EXTRACTOR_IDENTITY_DRIFT")
    identity = {
        "method": "pinned-native-plus-quality-qualified-cache-plus-existing-vision-repair-v1",
        "sources": sources,
        "vision": {
            "pdf_ingestion_sha256": batch.EXPECTED_PDF_INGESTION_SHA256,
            "vision_source_sha256": batch.EXPECTED_VISION_SOURCE_SHA256,
            "vision_config_sha256": batch.EXPECTED_VISION_CONFIG_SHA256,
            "renderer_sha256": batch.EXPECTED_RENDERER_SHA256,
            "renderer_version": batch.EXPECTED_RENDERER_VERSION,
        },
    }
    identity["sha256"] = sha256_bytes(canonical_json(identity))
    return identity


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise PreparationError("PREPARATION_RUN_ID_INVALID")


def _run_root(prepared_root: Path, run_id: str) -> Path:
    _validate_run_id(run_id)
    root = prepared_root.expanduser().absolute()
    target = root / run_id
    if root.is_symlink() or target.is_symlink():
        raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE")
    return target


def _immutable_json(batch: Any, path: Path, value: Mapping[str, Any], root: Path) -> str:
    return batch._write_immutable(path, canonical_json(value) + b"\n", root)


def _page_checkpoint_value(
    *,
    run_id: str,
    parent_sha256: str,
    document: Mapping[str, Any],
    page: pdf_research.PageText,
    source_row: Mapping[str, Any],
    extractor_sha256: str,
) -> dict[str, Any]:
    text_sha = sha256_bytes(page.text.encode("utf-8"))
    if page.text_sha256 not in (None, text_sha):
        raise PreparationError("PAGE_CHECKPOINT_TEXT_SHA_MISMATCH")
    quality = source_row.get("preparation_quality")
    if not isinstance(quality, Mapping):
        quality = assess_text_quality(page.text)
    gate = source_row.get("preparation_gate")
    if gate == "READY" and page.text.strip() and page.status in {"NATIVE_TEXT", "COMPLETE", "OCR_OK"}:
        status = "READY"
        reason = None
    elif source_row.get("preparation_failure_code"):
        status = (
            "FAILED"
            if source_row.get("selected")
            in {"SOURCE_REPAIR_FAILED_NO_RETRY", "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY"}
            else "QUARANTINED"
        )
        reason = str(source_row["preparation_failure_code"])[:96]
    else:
        status = "QUARANTINED"
        reason = str(source_row.get("preparation_failure_code") or quality.get("reason") or "PAGE_QUALITY_UNRESOLVED")[:96]
    return {
        "schema": PAGE_SCHEMA,
        "run_id": run_id,
        "parent_manifest_sha256": parent_sha256,
        "document_id": str(document["document_id"]),
        "pdf_sha256": str(document["pdf_sha256"]),
        "local_pdf_path": str(document["local_pdf_path"]),
        "source_pdf_bytes": document.get("pdf_bytes"),
        "extractor_identity_sha256": extractor_sha256,
        "page_number": page.page_number,
        "page_count": page.page_total,
        "status": status,
        "text_status": page.status,
        "text": page.text,
        "text_sha256": text_sha,
        "extraction_method": page.extraction_method or source_row.get("extraction_method") or "CANNOT_CONFIRM",
        "selected_source": source_row.get("selected"),
        "quality": dict(quality),
        "source_evidence": dict(source_row),
        "failure_code": reason,
    }


def _load_page_checkpoints(
    root: Path,
    *,
    run_id: str,
    parent_sha256: str,
    document: Mapping[str, Any],
    extractor_sha256: str,
) -> dict[int, tuple[pdf_research.PageText, dict[str, Any], dict[str, Any]]]:
    page_dir = root / "documents" / str(document["document_id"]) / "pages"
    if page_dir.is_symlink():
        raise PreparationError("PAGE_CHECKPOINT_PATH_UNSAFE")
    if not page_dir.exists():
        return {}
    result: dict[int, tuple[pdf_research.PageText, dict[str, Any], dict[str, Any]]] = {}
    for path in sorted(page_dir.glob("page-*.json")):
        checkpoint, raw = _read_json(path, "PAGE_CHECKPOINT_INVALID")
        match = re.fullmatch(r"page-(\d{4})\.json", path.name)
        page_number = int(match.group(1)) if match else None
        text = checkpoint.get("text")
        if (
            checkpoint.get("schema") != PAGE_SCHEMA
            or checkpoint.get("run_id") != run_id
            or checkpoint.get("parent_manifest_sha256") != parent_sha256
            or checkpoint.get("document_id") != document.get("document_id")
            or checkpoint.get("pdf_sha256") != document.get("pdf_sha256")
            or checkpoint.get("local_pdf_path") != document.get("local_pdf_path")
            or checkpoint.get("extractor_identity_sha256") != extractor_sha256
            or type(page_number) is not int
            or checkpoint.get("page_number") != page_number
            or type(checkpoint.get("page_count")) is not int
            or not isinstance(text, str)
            or checkpoint.get("text_sha256") != sha256_bytes(text.encode("utf-8"))
            or checkpoint.get("status") not in {"READY", "QUARANTINED", "FAILED"}
        ):
            raise PreparationError("PAGE_CHECKPOINT_BINDING_MISMATCH")
        page = pdf_research.PageText(
            page_number=page_number,
            page_total=checkpoint["page_count"],
            text=text,
            status=str(checkpoint.get("text_status") or ("TEXT_UNAVAILABLE" if checkpoint["status"] != "READY" else "COMPLETE")),
            text_sha256=checkpoint["text_sha256"],
            extraction_method=checkpoint.get("extraction_method"),
        )
        source_row = checkpoint.get("source_evidence")
        if not isinstance(source_row, dict):
            raise PreparationError("PAGE_CHECKPOINT_BINDING_MISMATCH")
        result[page_number] = (page, source_row, {"sha256": sha256_bytes(raw), "path": path})
    if len(result) != len(list(page_dir.glob("page-*.json"))):
        raise PreparationError("PAGE_CHECKPOINT_DUPLICATE_OR_INVALID")
    return result


def _prior_report_roots(batch: Any) -> list[Path]:
    research_root = pdf_research.PDF_RESEARCH_STATE_ROOT.resolve(strict=False)
    roots: list[Path] = []
    for item in (batch.R1_STATE_ROOT, batch.DEFAULT_STATE_ROOT):
        candidate = Path(item).expanduser().absolute()
        if candidate.resolve(strict=False).is_relative_to(research_root / "batches") and candidate not in roots:
            roots.append(candidate)
    journal = Path(
        "/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1/remaining-execution-r1/dispatch.jsonl"
    )
    expected = "8e583d56bb2c0fd60fa97d93a16e54b9665bbc87f673f1070c45e3f870d5bb79"
    if journal.is_file() and not journal.is_symlink():
        raw = journal.read_bytes()
        if sha256_bytes(raw) != expected:
            raise PreparationError("PRIOR_DISPATCH_JOURNAL_DRIFT")
        batches_root = (research_root / "batches").resolve(strict=False)
        for line in raw.splitlines():
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise PreparationError("PRIOR_DISPATCH_JOURNAL_INVALID") from None
            value = event.get("state_root") if isinstance(event, dict) else None
            if not isinstance(value, str):
                continue
            candidate = Path(value).expanduser().absolute()
            if candidate.resolve(strict=False).is_relative_to(batches_root) and candidate not in roots:
                roots.append(candidate)
    return roots


def _page_text_hashes(page_input: Mapping[str, Any]) -> list[str]:
    pages = page_input.get("pages")
    if not isinstance(pages, list):
        raise PreparationError("PRIOR_PAGE_INPUT_INVALID")
    values: list[str] = []
    for expected_number, row in enumerate(pages, 1):
        if not isinstance(row, dict) or row.get("page_number") != expected_number:
            raise PreparationError("PRIOR_PAGE_INPUT_INVALID")
        text = row.get("text")
        if not isinstance(text, str):
            raise PreparationError("PRIOR_PAGE_INPUT_INVALID")
        observed = sha256_bytes(text.encode("utf-8"))
        if row.get("text_sha256") not in (None, observed):
            raise PreparationError("PRIOR_PAGE_INPUT_INVALID")
        values.append(observed)
    return values


def _find_prior_successes(
    batch: Any,
    document_id: str,
    *,
    parent_sha256: str,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    research_root = pdf_research.PDF_RESEARCH_STATE_ROOT.resolve(strict=False)
    for state_root in _prior_report_roots(batch):
        receipt_path = state_root / "documents" / document_id / "receipt.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            continue
        receipt, receipt_raw = _read_json(receipt_path, "PRIOR_REPORT_RECEIPT_INVALID")
        if receipt.get("status") not in SUCCESS_REPORT_STATUSES:
            continue
        if (
            receipt.get("document_id") != document_id
            or receipt.get("pdf_sha256") != document_id
            or receipt.get("manifest_sha256") != parent_sha256
        ):
            raise PreparationError("PRIOR_REPORT_IDENTITY_MISMATCH")
        page_ref = receipt.get("page_input")
        report_ref = receipt.get("report")
        if not isinstance(page_ref, dict) or not isinstance(report_ref, dict):
            continue
        page_path = Path(str(page_ref.get("path", "")))
        report_path = Path(str(report_ref.get("path", "")))
        try:
            page_path.resolve(strict=True).relative_to(research_root)
            report_path.resolve(strict=True).relative_to(research_root)
            receipt_path.resolve(strict=True).relative_to(research_root)
        except (ValueError, OSError):
            continue
        if page_path.is_symlink() or report_path.is_symlink() or not page_path.is_file() or not report_path.is_file():
            continue
        page_sha = _file_sha256(page_path)
        report_sha = _file_sha256(report_path)
        receipt_sha = sha256_bytes(receipt_raw)
        if page_sha != page_ref.get("sha256") or report_sha != report_ref.get("sha256"):
            continue
        page_input, _raw = _read_json(page_path, "PRIOR_PAGE_INPUT_INVALID")
        if (
            page_input.get("schema") != PAGE_INPUT_SCHEMA
            or page_input.get("document_id") != document_id
            or page_input.get("pdf_sha256") != document_id
            or page_input.get("manifest_sha256") != parent_sha256
        ):
            continue
        text_hashes = _page_text_hashes(page_input)
        key = (receipt_sha, page_sha, report_sha)
        if key in seen:
            continue
        seen.add(key)
        references.append(
            {
                "receipt_path": str(receipt_path),
                "receipt_sha256": receipt_sha,
                "prior_status": receipt["status"],
                "page_input_path": str(page_path),
                "page_input_sha256": page_sha,
                "page_text_sha256s": text_hashes,
                "report_path": str(report_path),
                "report_sha256": report_sha,
            }
        )
    return sorted(references, key=lambda row: (row["receipt_path"], row["receipt_sha256"]))


def _document_receipt_path(root: Path, document_id: str) -> Path:
    return root / "documents" / document_id / "document.json"


def prepare_only(
    batch: Any,
    *,
    manifest_path: Path,
    run_id: str,
    document_ids: Sequence[str] | None = None,
    prepared_root: Path = PREPARED_ROOT,
) -> dict[str, Any]:
    manifest, parent_sha, documents = batch.load_manifest(manifest_path)
    if parent_sha != batch.EXPECTED_BATCH_MANIFEST_SHA256 or len(documents) != 2209:
        raise PreparationError("PREPARATION_PARENT_MANIFEST_DRIFT")
    run_root = _run_root(prepared_root, run_id)
    run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if run_root.is_symlink():
        raise PreparationError("PREPARATION_OUTPUT_PATH_UNSAFE")
    extractor = _extractor_identity(batch)
    run_value = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "parent_manifest_path": str(Path(manifest_path).expanduser().absolute()),
        "parent_manifest_sha256": parent_sha,
        "parent_document_count": len(documents),
        "extractor_identity": extractor,
        "extractor_identity_sha256": extractor["sha256"],
    }
    run_path = run_root / "run.json"
    run_bytes = canonical_json(run_value) + b"\n"
    if run_path.exists():
        if run_path.is_symlink() or run_path.read_bytes() != run_bytes:
            raise PreparationError("PREPARATION_RUN_BINDING_MISMATCH")
    else:
        _immutable_json(batch, run_path, run_value, run_root)

    manifest_path_out = run_root / PREPARED_MANIFEST_NAME
    if manifest_path_out.exists():
        frozen, frozen_raw = _read_json(manifest_path_out, "PREPARED_MANIFEST_INVALID")
        verified = verify_frozen_manifest(
            batch,
            manifest_path_out,
            expected_sha256=sha256_bytes(frozen_raw),
            expected_parent_sha256=parent_sha,
        )
        return {
            "status": frozen.get("status"),
            "run_id": run_id,
            "prepared_text_manifest_path": str(manifest_path_out),
            "prepared_text_manifest_sha256": verified["manifest_sha256"],
            "document_count": len(documents),
            "counts": frozen.get("counts"),
            "model_requests": 0,
            "model_stage": "NOT_RUN",
        }

    manifest_by_id = {str(row.get("document_id")): row for row in documents}
    if len(manifest_by_id) != len(documents):
        raise PreparationError("PREPARATION_PARENT_DOCUMENT_IDS_INVALID")
    selected_ids = list(document_ids) if document_ids is not None else [str(row["document_id"]) for row in documents]
    if len(set(selected_ids)) != len(selected_ids) or any(document_id not in manifest_by_id for document_id in selected_ids):
        raise PreparationError("PREPARATION_SELECTION_INVALID")
    full_scope = document_ids is None
    selected_documents = [manifest_by_id[document_id] for document_id in selected_ids]
    existing_rows: dict[str, dict[str, Any]] = {}
    progress_path = run_root / "progress.json"
    if progress_path.exists():
        progress, _raw = _read_json(progress_path, "PREPARATION_PROGRESS_INVALID")
        if (
            progress.get("run_id") != run_id
            or progress.get("parent_manifest_sha256") != parent_sha
            or progress.get("extractor_identity_sha256") != extractor["sha256"]
            or progress.get("full_scope") is not full_scope
        ):
            raise PreparationError("PREPARATION_PROGRESS_BINDING_MISMATCH")
        rows = progress.get("documents")
        if not isinstance(rows, list):
            raise PreparationError("PREPARATION_PROGRESS_INVALID")
        existing_rows = {str(row.get("document_id")): dict(row) for row in rows if isinstance(row, dict)}

    for document in selected_documents:
        document_id = str(document["document_id"])
        receipt_path = _document_receipt_path(run_root, document_id)
        if receipt_path.exists():
            receipt, raw = _read_json(receipt_path, "PREPARATION_DOCUMENT_RECEIPT_INVALID")
            if (
                receipt.get("schema") != DOCUMENT_SCHEMA
                or receipt.get("run_id") != run_id
                or receipt.get("parent_manifest_sha256") != parent_sha
                or receipt.get("extractor_identity_sha256") != extractor["sha256"]
                or receipt.get("document_id") != document_id
                or receipt.get("pdf_sha256") != document.get("pdf_sha256")
            ):
                raise PreparationError("PREPARATION_DOCUMENT_RECEIPT_BINDING_MISMATCH")
            existing_rows[document_id] = {
                "document_id": document_id,
                "status": receipt["status"],
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": sha256_bytes(raw),
                "page_count": receipt.get("page_count"),
                "error_code": receipt.get("error_code"),
            }
            continue

        checkpoints = _load_page_checkpoints(
            run_root,
            run_id=run_id,
            parent_sha256=parent_sha,
            document=document,
            extractor_sha256=extractor["sha256"],
        )
        resume_map = {
            page_number: (page, source_row)
            for page_number, (page, source_row, _reference) in checkpoints.items()
        }
        document_root = run_root / "documents" / document_id
        document_root.mkdir(mode=0o700, parents=True, exist_ok=True)

        def persist_page(page: pdf_research.PageText, source_row: Mapping[str, Any]) -> None:
            value = _page_checkpoint_value(
                run_id=run_id,
                parent_sha256=parent_sha,
                document=document,
                page=page,
                source_row=source_row,
                extractor_sha256=extractor["sha256"],
            )
            path = document_root / "pages" / f"page-{page.page_number:04d}.json"
            _immutable_json(batch, path, value, run_root)
            checkpoints[page.page_number] = (
                page,
                dict(source_row),
                {"path": path, "sha256": _file_sha256(path)},
            )

        try:
            repair_budget = {"remaining": max(1, int(batch._candidate_page_count(document) or 500))}
            pages, source = batch._load_pages(
                document,
                state_root=run_root,
                repair_budget=repair_budget,
                preparation_mode=True,
                resume_pages=resume_map,
                page_callback=persist_page,
            )
            page_count = len(pages)
            if page_count < 1 or any(page.page_number != offset for offset, page in enumerate(pages, 1)):
                raise PreparationError("PREPARATION_PAGE_COVERAGE_INVALID")
            source_rows = source.get("page_extraction_sources")
            if not isinstance(source_rows, list) or len(source_rows) != page_count:
                raise PreparationError("PREPARATION_PAGE_SOURCE_ROWS_INVALID")
            for page, source_row in zip(pages, source_rows, strict=True):
                if page.page_number not in checkpoints:
                    persist_page(page, source_row)
            page_refs = []
            page_checkpoint_statuses = []
            for page_number in range(1, page_count + 1):
                page, _source_row, reference = checkpoints[page_number]
                checkpoint, raw = _read_json(Path(reference["path"]), "PAGE_CHECKPOINT_INVALID")
                page_refs.append(
                    {
                        "page_number": page_number,
                        "status": checkpoint["status"],
                        "path": str(Path(reference["path"]).relative_to(run_root)),
                        "sha256": sha256_bytes(raw),
                        "text_sha256": checkpoint["text_sha256"],
                        "extraction_method": checkpoint["extraction_method"],
                        "quality": checkpoint["quality"],
                    }
                )
                page_checkpoint_statuses.append(checkpoint["status"])
            ready = (
                all(status == "READY" for status in page_checkpoint_statuses)
                and source.get("page_extraction_status") == "COMPLETE"
                and source.get("all_pages_nonempty") is True
            )
            page_input = batch._page_input_value(
                {**dict(document), "_manifest_sha256": parent_sha},
                pages,
                source,
            )
            page_input_raw = batch._json_bytes(page_input, newline=True)
            page_input_path = document_root / "page-input.json"
            page_input_sha = batch._write_immutable(page_input_path, page_input_raw, run_root)
            old_successes = _find_prior_successes(batch, document_id, parent_sha256=parent_sha)
            new_text_hashes = _page_text_hashes(page_input)
            changed_prior = [
                old
                for old in old_successes
                if old["page_text_sha256s"] != new_text_hashes
            ]
            revision = None
            if changed_prior:
                revision_core = {
                    "document_id": document_id,
                    "new_page_input_sha256": page_input_sha,
                    "supersedes": [
                        {key: old[key] for key in ("receipt_path", "receipt_sha256", "page_input_sha256", "report_sha256")}
                        for old in changed_prior
                    ],
                }
                revision = {
                    "revision_id": sha256_bytes(canonical_json(revision_core)),
                    "reason": "PREPARED_SOURCE_TEXT_CHANGED",
                    "supersedes": changed_prior,
                }
            status = "READY" if ready else "QUARANTINED"
            receipt = {
                "schema": DOCUMENT_SCHEMA,
                "run_id": run_id,
                "parent_manifest_sha256": parent_sha,
                "extractor_identity_sha256": extractor["sha256"],
                "document_id": document_id,
                "pdf_sha256": document["pdf_sha256"],
                "local_pdf_path": document["local_pdf_path"],
                "status": status,
                "page_count": page_count,
                "page_input": {
                    "path": str(page_input_path.relative_to(run_root)),
                    "sha256": page_input_sha,
                    "bytes": len(page_input_raw),
                },
                "page_checkpoints": page_refs,
                "source": source,
                "source_text_sha256s": new_text_hashes,
                "revision": revision,
                "error_code": None if ready else "PAGE_QUALITY_OR_COVERAGE_UNRESOLVED",
                "model_requests": 0,
            }
            receipt_sha = _immutable_json(batch, receipt_path, receipt, run_root)
            existing_rows[document_id] = {
                "document_id": document_id,
                "status": status,
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": receipt_sha,
                "page_count": page_count,
                "error_code": receipt["error_code"],
            }
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            code = str(code)[:96]
            if code in FATAL_SOURCE_CODES:
                _atomic_json(
                    progress_path,
                    {
                        "schema": "v4.pdf_research_text_preparation.progress.v1",
                        "run_id": run_id,
                        "parent_manifest_sha256": parent_sha,
                        "extractor_identity_sha256": extractor["sha256"],
                        "full_scope": full_scope,
                        "status": "STOPPED_SOURCE_INTEGRITY",
                        "documents": [existing_rows[key] for key in sorted(existing_rows)],
                        "model_requests": 0,
                    },
                    run_root,
                )
                raise PreparationError(code) from None
            failure_receipt = {
                "schema": DOCUMENT_SCHEMA,
                "run_id": run_id,
                "parent_manifest_sha256": parent_sha,
                "extractor_identity_sha256": extractor["sha256"],
                "document_id": document_id,
                "pdf_sha256": document.get("pdf_sha256"),
                "local_pdf_path": document.get("local_pdf_path"),
                "status": "FAILED",
                "page_count": (
                    next(iter(checkpoints.values()))[0].page_total
                    if checkpoints
                    else batch._candidate_page_count(document)
                ),
                "page_input": None,
                "page_checkpoints": [
                    {
                        "page_number": page_number,
                        "status": _read_json(reference["path"], "PAGE_CHECKPOINT_INVALID")[0].get("status"),
                        "path": str(Path(reference["path"]).relative_to(run_root)),
                        "sha256": _file_sha256(Path(reference["path"])),
                        "text_sha256": page.text_sha256,
                        "extraction_method": page.extraction_method,
                        "quality": _read_json(reference["path"], "PAGE_CHECKPOINT_INVALID")[0].get("quality"),
                    }
                    for page_number, (page, _source_row, reference) in sorted(checkpoints.items())
                ],
                "source": None,
                "source_text_sha256s": [],
                "revision": None,
                "error_code": code,
                "model_requests": 0,
            }
            if receipt_path.exists():
                raise PreparationError("PREPARATION_OUTPUT_COLLISION") from None
            receipt_sha = _immutable_json(batch, receipt_path, failure_receipt, run_root)
            existing_rows[document_id] = {
                "document_id": document_id,
                "status": "FAILED",
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": receipt_sha,
                "page_count": failure_receipt["page_count"],
                "error_code": code,
            }
        current_selected_rows = [
            existing_rows[document_id]
            for document_id in selected_ids
            if document_id in existing_rows
        ]
        counts = Counter(row["status"] for row in current_selected_rows)
        _atomic_json(
            progress_path,
            {
                "schema": "v4.pdf_research_text_preparation.progress.v1",
                "run_id": run_id,
                "parent_manifest_sha256": parent_sha,
                "extractor_identity_sha256": extractor["sha256"],
                "full_scope": full_scope,
                "status": "PREPARING" if len(current_selected_rows) < len(selected_ids) else "PARTIAL_SCOPE_COMPLETE" if not full_scope else "COHORT_TERMINAL",
                "parent_document_count": len(documents),
                "selected_document_count": len(selected_ids),
                "pending_selected_count": len(selected_ids) - len(current_selected_rows),
                "counts": {name: counts.get(name, 0) for name in sorted(TERMINAL_STATUSES)},
                "documents": [existing_rows[key] for key in sorted(existing_rows)],
                "model_requests": 0,
            },
            run_root,
        )

    if not full_scope:
        progress, progress_raw = _read_json(progress_path, "PREPARATION_PROGRESS_INVALID")
        return {
            "status": "PARTIAL_SCOPE_COMPLETE",
            "run_id": run_id,
            "parent_manifest_sha256": parent_sha,
            "parent_document_count": len(documents),
            "selected_document_count": len(selected_ids),
            "pending_full_cohort": len(documents) - len(selected_ids),
            "progress_path": str(progress_path),
            "progress_sha256": sha256_bytes(progress_raw),
            "prepared_text_manifest_path": None,
            "full_manifest_created": False,
            "model_requests": 0,
            "model_stage": "NOT_RUN",
        }

    rows: list[dict[str, Any]] = []
    for document in documents:
        document_id = str(document["document_id"])
        row = existing_rows.get(document_id)
        receipt_path = _document_receipt_path(run_root, document_id)
        if row is None or not receipt_path.is_file() or receipt_path.is_symlink():
            continue
        receipt, raw = _read_json(receipt_path, "PREPARATION_DOCUMENT_RECEIPT_INVALID")
        rows.append(
            {
                "document_id": document_id,
                "pdf_sha256": document["pdf_sha256"],
                "local_pdf_path": document["local_pdf_path"],
                "status": receipt["status"],
                "receipt_path": str(receipt_path.relative_to(run_root)),
                "receipt_sha256": sha256_bytes(raw),
                "page_count": receipt.get("page_count"),
                "page_input": receipt.get("page_input"),
                "page_checkpoints": receipt.get("page_checkpoints", []),
                "source_text_sha256s": receipt.get("source_text_sha256s", []),
                "revision": receipt.get("revision"),
                "error_code": receipt.get("error_code"),
            }
        )
    if len(rows) != len(documents) or any(row["status"] not in TERMINAL_STATUSES for row in rows):
        return {
            "status": "PREPARATION_INCOMPLETE",
            "run_id": run_id,
            "parent_manifest_sha256": parent_sha,
            "parent_document_count": len(documents),
            "terminal_document_count": len(rows),
            "pending": len(documents) - len(rows),
            "progress_path": str(progress_path),
            "prepared_text_manifest_path": None,
            "full_manifest_created": False,
            "model_requests": 0,
            "model_stage": "NOT_RUN",
        }
    counts = Counter(row["status"] for row in rows)
    frozen = {
        "schema": MANIFEST_SCHEMA,
        "status": "FROZEN_COMPLETE",
        "run_id": run_id,
        "parent_manifest_path": str(Path(manifest_path).expanduser().absolute()),
        "parent_manifest_sha256": parent_sha,
        "parent_document_count": len(documents),
        "extractor_identity": extractor,
        "extractor_identity_sha256": extractor["sha256"],
        "full_cohort": True,
        "counts": {
            "total": len(documents),
            "ready": counts.get("READY", 0),
            "quarantined": counts.get("QUARANTINED", 0),
            "failed": counts.get("FAILED", 0),
            "pending": 0,
        },
        "documents": rows,
        "model_requests": 0,
        "model_stage": "NOT_RUN",
    }
    manifest_sha = _immutable_json(batch, manifest_path_out, frozen, run_root)
    return {
        "status": "FROZEN_COMPLETE",
        "run_id": run_id,
        "parent_manifest_sha256": parent_sha,
        "prepared_text_manifest_path": str(manifest_path_out),
        "prepared_text_manifest_sha256": manifest_sha,
        "document_count": len(documents),
        "counts": frozen["counts"],
        "model_requests": 0,
        "model_stage": "NOT_RUN",
    }


def verify_frozen_manifest(
    batch: Any,
    manifest_path: Path,
    *,
    expected_sha256: str,
    expected_parent_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
        raise PreparationError("PREPARED_MANIFEST_EXPECTED_SHA_REQUIRED")
    path = manifest_path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise PreparationError("PREPARED_MANIFEST_UNAVAILABLE")
    raw = path.read_bytes()
    observed_sha = sha256_bytes(raw)
    if observed_sha != expected_sha256:
        raise PreparationError("PREPARED_MANIFEST_SHA_MISMATCH")
    try:
        frozen = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise PreparationError("PREPARED_MANIFEST_INVALID") from None
    if not isinstance(frozen, dict):
        raise PreparationError("PREPARED_MANIFEST_INVALID")
    parent_path = Path(str(frozen.get("parent_manifest_path", "")))
    parent, parent_sha, documents = batch.load_manifest(parent_path)
    if expected_parent_sha256 is not None and parent_sha != expected_parent_sha256:
        raise PreparationError("PREPARED_PARENT_MANIFEST_SHA_MISMATCH")
    rows = frozen.get("documents")
    counts = frozen.get("counts")
    if (
        frozen.get("schema") != MANIFEST_SCHEMA
        or frozen.get("status") != "FROZEN_COMPLETE"
        or frozen.get("full_cohort") is not True
        or frozen.get("parent_manifest_sha256") != parent_sha
        or frozen.get("parent_document_count") != len(documents)
        or len(documents) != 2209
        or not isinstance(rows, list)
        or len(rows) != len(documents)
        or not isinstance(counts, dict)
        or counts.get("total") != len(documents)
        or counts.get("pending") != 0
        or sum(counts.get(key, 0) for key in ("ready", "quarantined", "failed")) != len(documents)
        or frozen.get("model_requests") != 0
        or frozen.get("model_stage") != "NOT_RUN"
    ):
        raise PreparationError("PREPARED_MANIFEST_NOT_FULLY_TERMINAL")
    observed_counts = {
        status: sum(1 for row in rows if isinstance(row, dict) and row.get("status") == status)
        for status in TERMINAL_STATUSES
    }
    if any(counts.get(status) != observed_counts[status] for status in TERMINAL_STATUSES):
        raise PreparationError("PREPARED_MANIFEST_COUNTS_MISMATCH")
    root = path.parent
    verified_rows: dict[str, dict[str, Any]] = {}
    parent_by_id = {str(row["document_id"]): row for row in documents}
    for parent_row, row in zip(documents, rows, strict=True):
        if not isinstance(row, dict):
            raise PreparationError("PREPARED_DOCUMENT_ROW_INVALID")
        document_id = str(parent_row.get("document_id"))
        if (
            row.get("document_id") != document_id
            or row.get("pdf_sha256") != parent_row.get("pdf_sha256")
            or row.get("local_pdf_path") != parent_row.get("local_pdf_path")
            or row.get("status") not in TERMINAL_STATUSES
        ):
            raise PreparationError("PREPARED_DOCUMENT_BINDING_MISMATCH")
        receipt_path = _relative_path(root, row.get("receipt_path"), "PREPARED_DOCUMENT_RECEIPT_UNSAFE")
        receipt, receipt_raw = _read_json(receipt_path, "PREPARED_DOCUMENT_RECEIPT_UNAVAILABLE")
        if (
            sha256_bytes(receipt_raw) != row.get("receipt_sha256")
            or receipt.get("schema") != DOCUMENT_SCHEMA
            or receipt.get("run_id") != frozen.get("run_id")
            or receipt.get("parent_manifest_sha256") != parent_sha
            or receipt.get("extractor_identity_sha256") != frozen.get("extractor_identity_sha256")
            or receipt.get("document_id") != document_id
            or receipt.get("pdf_sha256") != row.get("pdf_sha256")
            or receipt.get("status") != row.get("status")
        ):
            raise PreparationError("PREPARED_DOCUMENT_RECEIPT_BINDING_MISMATCH")
        page_refs = row.get("page_checkpoints")
        if not isinstance(page_refs, list):
            raise PreparationError("PREPARED_PAGE_COVERAGE_INVALID")
        expected_page_count = row.get("page_count")
        if type(expected_page_count) is int:
            if row.get("status") != "FAILED" and len(page_refs) != expected_page_count:
                raise PreparationError("PREPARED_PAGE_COVERAGE_INVALID")
            if row.get("status") == "FAILED" and len(page_refs) > expected_page_count:
                raise PreparationError("PREPARED_PAGE_COVERAGE_INVALID")
        elif row.get("status") == "READY" or page_refs:
            raise PreparationError("PREPARED_PAGE_COVERAGE_INVALID")
        page_checkpoint_rows: list[dict[str, Any]] = []
        for expected_number, page_ref in enumerate(page_refs, 1):
            if not isinstance(page_ref, dict) or page_ref.get("page_number") != expected_number:
                raise PreparationError("PREPARED_PAGE_COVERAGE_INVALID")
            checkpoint_path = _relative_path(root, page_ref.get("path"), "PREPARED_PAGE_CHECKPOINT_UNSAFE")
            checkpoint, checkpoint_raw = _read_json(checkpoint_path, "PREPARED_PAGE_CHECKPOINT_UNAVAILABLE")
            text = checkpoint.get("text")
            if (
                sha256_bytes(checkpoint_raw) != page_ref.get("sha256")
                or checkpoint.get("schema") != PAGE_SCHEMA
                or checkpoint.get("run_id") != frozen.get("run_id")
                or checkpoint.get("parent_manifest_sha256") != parent_sha
                or checkpoint.get("document_id") != document_id
                or checkpoint.get("pdf_sha256") != row.get("pdf_sha256")
                or checkpoint.get("extractor_identity_sha256") != frozen.get("extractor_identity_sha256")
                or checkpoint.get("page_number") != expected_number
                or checkpoint.get("page_count") != row.get("page_count")
                or checkpoint.get("text_status") not in {"NATIVE_TEXT", "COMPLETE", "OCR_OK", "BLANK", "TEXT_UNAVAILABLE"}
                or checkpoint.get("status") != page_ref.get("status")
                or checkpoint.get("text_sha256") != page_ref.get("text_sha256")
                or not isinstance(text, str)
                or sha256_bytes(text.encode("utf-8")) != page_ref.get("text_sha256")
            ):
                raise PreparationError("PREPARED_PAGE_CHECKPOINT_BINDING_MISMATCH")
            page_checkpoint_rows.append(checkpoint)
        if row["status"] == "READY":
            page_input_ref = row.get("page_input")
            if not isinstance(page_input_ref, dict):
                raise PreparationError("PREPARED_PAGE_INPUT_UNAVAILABLE")
            page_input_path = _relative_path(root, page_input_ref.get("path"), "PREPARED_PAGE_INPUT_UNSAFE")
            page_input, page_input_raw = _read_json(page_input_path, "PREPARED_PAGE_INPUT_UNAVAILABLE")
            if (
                sha256_bytes(page_input_raw) != page_input_ref.get("sha256")
                or page_input.get("schema") != PAGE_INPUT_SCHEMA
                or page_input.get("manifest_sha256") != parent_sha
                or page_input.get("document_id") != document_id
                or page_input.get("pdf_sha256") != row.get("pdf_sha256")
                or page_input.get("source", {}).get("page_count") != row.get("page_count")
            ):
                raise PreparationError("PREPARED_PAGE_INPUT_BINDING_MISMATCH")
            page_rows = page_input.get("pages")
            if not isinstance(page_rows, list) or len(page_rows) != row.get("page_count"):
                raise PreparationError("PREPARED_PAGE_INPUT_COVERAGE_INVALID")
            for expected_number, (page_row, checkpoint) in enumerate(zip(page_rows, page_checkpoint_rows, strict=True), 1):
                if (
                    not isinstance(page_row, dict)
                    or page_row.get("page_number") != expected_number
                    or page_row.get("text") != checkpoint.get("text")
                    or page_row.get("text_sha256") not in (None, checkpoint.get("text_sha256"))
                    or checkpoint.get("status") != "READY"
                    or not isinstance(page_row.get("text"), str)
                    or not page_row["text"].strip()
                ):
                    raise PreparationError("PREPARED_PAGE_INPUT_TEXT_MISMATCH")
            revision = row.get("revision")
            if revision is not None:
                if not isinstance(revision, dict) or revision.get("reason") != "PREPARED_SOURCE_TEXT_CHANGED" or not isinstance(revision.get("supersedes"), list):
                    raise PreparationError("PREPARED_REVISION_REFERENCE_INVALID")
                for old in revision["supersedes"]:
                    _verify_supersedes(old)
            verified_rows[document_id] = {
                "document": parent_by_id[document_id],
                "manifest_row": row,
                "receipt": receipt,
                "page_input": page_input,
                "page_input_raw": page_input_raw,
                "page_input_sha256": page_input_ref["sha256"],
            }
        else:
            verified_rows[document_id] = {"document": parent_by_id[document_id], "manifest_row": row, "receipt": receipt}
    return {
        "manifest": frozen,
        "manifest_sha256": observed_sha,
        "parent_manifest_sha256": parent_sha,
        "documents": verified_rows,
        "path": path,
        "root": root,
    }


def _verify_supersedes(reference: Any) -> None:
    if not isinstance(reference, dict):
        raise PreparationError("PREPARED_REVISION_REFERENCE_INVALID")
    research_root = pdf_research.PDF_RESEARCH_STATE_ROOT.resolve(strict=False)
    for path_key, sha_key in (
        ("receipt_path", "receipt_sha256"),
        ("page_input_path", "page_input_sha256"),
        ("report_path", "report_sha256"),
    ):
        path = Path(str(reference.get(path_key, "")))
        expected = reference.get(sha_key)
        try:
            path.resolve(strict=True).relative_to(research_root)
        except (ValueError, OSError):
            raise PreparationError("PREPARED_SUPERSEDES_ARTIFACT_DRIFT") from None
        if path.is_symlink() or not path.is_file() or not isinstance(expected, str) or _file_sha256(path) != expected:
            raise PreparationError("PREPARED_SUPERSEDES_ARTIFACT_DRIFT")


def pages_from_frozen_manifest(
    verified: Mapping[str, Any],
    document_id: str,
) -> tuple[list[pdf_research.PageText], dict[str, Any], dict[str, Any]]:
    rows = verified.get("documents")
    row = rows.get(document_id) if isinstance(rows, Mapping) else None
    if not isinstance(row, Mapping) or row.get("manifest_row", {}).get("status") != "READY":
        raise PreparationError("PREPARED_DOCUMENT_NOT_READY")
    page_input = row.get("page_input")
    if not isinstance(page_input, Mapping):
        raise PreparationError("PREPARED_PAGE_INPUT_UNAVAILABLE")
    pages: list[pdf_research.PageText] = []
    for expected_number, page in enumerate(page_input.get("pages", []), 1):
        if not isinstance(page, Mapping) or page.get("page_number") != expected_number:
            raise PreparationError("PREPARED_PAGE_INPUT_COVERAGE_INVALID")
        text = page.get("text")
        if not isinstance(text, str) or not text.strip():
            raise PreparationError("PREPARED_PAGE_INPUT_TEXT_INVALID")
        text_sha = sha256_bytes(text.encode("utf-8"))
        if page.get("text_sha256") not in (None, text_sha):
            raise PreparationError("PREPARED_PAGE_INPUT_TEXT_SHA_MISMATCH")
        pages.append(
            pdf_research.PageText(
                page_number=expected_number,
                page_total=len(page_input["pages"]),
                text=text,
                status=str(page.get("status") or "COMPLETE"),
                text_sha256=text_sha,
                extraction_method=str(page.get("extraction_method") or "FROZEN_PREPARED_TEXT"),
            )
        )
    source = page_input.get("source")
    if not isinstance(source, dict):
        raise PreparationError("PREPARED_PAGE_INPUT_SOURCE_INVALID")
    source = {
        **source,
        "prepared_text_manifest_sha256": verified.get("manifest_sha256"),
        "prepared_text_page_input_sha256": row.get("page_input_sha256"),
        "prepared_text_status": "FROZEN_READY",
    }
    return pages, source, dict(row.get("manifest_row", {}))
