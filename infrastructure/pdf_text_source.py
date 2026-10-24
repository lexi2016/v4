"""Existing PDF extraction and OCR leaves, shared by preparation and legacy CLIs.

No model requests, registry or publication responsibilities live here.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from infrastructure import pdf_research, pdf_text_preparation

R_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1")


FIRST_CONTENT_FAIL_PDF_SHA256 = "075d0083f99e6a4912086798fd0bf737c3807d6e14a365ab2f2d2dd14f4d883c"


SECOND_CONTENT_FAIL_PDF_SHA256 = "93930e8298dc18a9e2438d5c31420675d1b86e1d87f793139ca76db45f389ee9"


SOURCE_CANARY_ATTEMPT_PATH = R_ROOT / "writer/ocr-scale-canary/attempt.json"


SOURCE_CANARY_ATTEMPT_SHA256 = "c5c222520e38162103603e494a906be9a3ea7d48fa5953bae6b7d4619c6d3664"


SOURCE_CANARY_TEXT_SHA256 = "3098a17443a681086478856fa96192805d84d06120fb1afb5cc7cfad674434a6"


SOURCE_CANARY_SCOPE_SHA256 = "bfa21e0d18b4d7a5012403af269c8fc1cb6742e1ae58ef56705c3c56a41982ee"


SOURCE_CANARY_REVIEW_SHA256 = "48565633b8bd6abec4f4c40c799cb1170bec04200991d662b57c52914fa586e5"


SOURCE_CANARY_REVIEW_DEFAULT = R_ROOT / "reviewer/ocr-scale-content-verdict.json"


SLICE_CANARY_ATTEMPT_PATH = R_ROOT / "writer/slice-canary/attempt.json"


SLICE_CANARY_ATTEMPT_SHA256 = "5ba455f74357c0f17a3b0084ebe18109a2532c34d88a7ee718b6cc8d55e79774"


SLICE_CANARY_MANIFEST_PATH = R_ROOT / "writer/slice-canary/slice-manifest.json"


SLICE_CANARY_MANIFEST_SHA256 = "7080fc6b5e74db9e9361b776da3b402b0b8bb94e01f68f6da200da7fe01a3692"


SLICE_CANARY_TEXT_PATH = R_ROOT / "writer/slice-canary/ordered-text.txt"


SLICE_CANARY_TEXT_SHA256 = "31d5b7e5e8c55638307bbd4f0e514afdb437b6986860eea501b66aa289a34b3d"


SLICE_CANARY_SCOPE_SHA256 = "f12cacd0f00c67db6b1dea24347ca7b0fd4e5e7ce1d1c32d8141db2402b23534"


SLICE_CANARY_REVIEW_DEFAULT = R_ROOT / "reviewer/slice-source-content-verdict.json"


SLICE_CANARY_REVIEW_SHA256 = "6982589eb94cc268a62043e3136f1f96abc2c9b2f7c4c7ef3f379353ebc3b31b"


SLICE_SOURCE_REVIEW_SCOPE_SHA256 = "68849328bca22feffc9118cbd6f9494d49629e8fcb74d3bf7064f3666a053e8c"


V3_OCR_SCRIPTS_ROOT = Path("/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/scripts")


V3_PREPARE_OCR_PATH = V3_OCR_SCRIPTS_ROOT / "wechat_prepare_ocr.py"


V3_COMMON_PATH = V3_OCR_SCRIPTS_ROOT / "wechat_common.py"


EXPECTED_V3_PREPARE_OCR_SHA256 = "980c9004a1fa38862708ee325970ab8adfebbd66661cb42f0f8318436eebe606"


EXPECTED_V3_COMMON_SHA256 = "25934b26357060e3322dcf393816383558a166a5a969244a7e4f1e8de4582446"


EXPECTED_PDF_INGESTION_SHA256 = "8a16a457edbd6a7a95c3b3c7af5335d8243946b0e5f2b2f2eb48f5fc3e7c9f9b"


EXPECTED_VISION_SOURCE_SHA256 = "be7e039d778babd32918da2b7d9620a7b3b9e98e6e62625840eaad1b6d4d834d"


EXPECTED_VISION_CONFIG_SHA256 = "631e624bf348d42d2cb2d333e599e412cddd230593e0372663076e8865ba7814"


EXPECTED_RENDERER_SHA256 = "de772e88ab9977ccde25def9b403bf42675d75f5dd82b19fbd7d8123ad183159"


EXPECTED_RENDERER_VERSION = "26.05.0"


BASELINE_RENDER_SCALE_TO = 2_600


MAX_REPAIR_RENDER_SCALE_TO = 13_000


TARGET_RENDER_PIXELS_PER_POINT = MAX_REPAIR_RENDER_SCALE_TO / 5_001


LOW_RENDER_DENSITY_PIXELS_PER_POINT = 1.0


MAX_REPAIR_IMAGE_BYTES = 32 * 1024 * 1024


MAX_REPAIR_RENDER_SECONDS = 45


MAX_REPAIR_VISION_SECONDS = 30


MAX_REPAIR_VISION_AGGREGATE_SECONDS = 60


MAX_REPAIR_PAGES_PER_TICK = 2


SOURCE_REPAIR_SCHEMA = "v4.pdf_simple_batch.longscan_source_repair.v1"


SOURCE_CANARY_REVIEW_SCHEMA = "v4.pdf_simple_batch.source_text_canary_review.v1"


class BatchError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Any, *, newline: bool = False) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return raw + (b"\n" if newline else b"")


def _within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        return True
    except ValueError:
        return False


def _checked_output(path: Path, root: Path) -> Path:
    path = path.expanduser().absolute()
    root = root.expanduser().absolute()
    if not _within(path, root):
        raise BatchError("OUTPUT_OUTSIDE_BATCH_STATE_ROOT")
    cursor = root
    if cursor.is_symlink():
        raise BatchError("BATCH_STATE_ROOT_SYMLINK_FORBIDDEN")
    for part in path.relative_to(root).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise BatchError("BATCH_OUTPUT_PARENT_SYMLINK_FORBIDDEN")
    if path.is_symlink():
        raise BatchError("BATCH_OUTPUT_SYMLINK_FORBIDDEN")
    return path


def _write_immutable(path: Path, raw: bytes, root: Path) -> str:
    path = _checked_output(path, root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing != raw:
            raise BatchError("IMMUTABLE_ARTIFACT_CONFLICT")
        return _sha256(existing)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise BatchError("IMMUTABLE_ARTIFACT_CONFLICT")
        return _sha256(raw)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _candidate_page_count(document: Mapping[str, Any]) -> int | None:
    explicit = document.get("page_count")
    if type(explicit) is int and explicit > 0:
        return explicit
    counts = {
        candidate.get("page_count")
        for candidate in document.get("cache_candidates", [])
        if isinstance(candidate, dict) and type(candidate.get("page_count")) is int and candidate["page_count"] > 0
    }
    if len(counts) > 1:
        raise BatchError("CACHE_CANDIDATE_PAGE_COUNT_CONFLICT")
    return next(iter(counts)) if counts else None


def _read_source_text_canary_review() -> dict[str, Any] | None:
    path = SOURCE_CANARY_REVIEW_DEFAULT
    if path.is_symlink() or not path.is_file():
        return None
    raw = path.read_bytes()
    if _sha256(raw) != SOURCE_CANARY_REVIEW_SHA256:
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_SHA_MISMATCH")
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_INVALID") from None
    scope = review.get("scope") if isinstance(review, dict) else None
    acceptance = review.get("acceptance") if isinstance(review, dict) else None
    boundary = review.get("accepted_markdown_boundary") if isinstance(review, dict) else None
    if (
        not isinstance(review, dict)
        or review.get("schema") != SOURCE_CANARY_REVIEW_SCHEMA
        or review.get("status") != "SOURCE_CONTENT_PASS"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or review.get("pdf_sha256") != FIRST_CONTENT_FAIL_PDF_SHA256
        or review.get("attempt_sha256") != SOURCE_CANARY_ATTEMPT_SHA256
        or review.get("text_sha256") != SOURCE_CANARY_TEXT_SHA256
        or review.get("text_characters") != 5_353
        or not isinstance(scope, dict)
        or scope.get("document_id") != FIRST_CONTENT_FAIL_PDF_SHA256
        or scope.get("page_number") != 1
        or not isinstance(acceptance, dict)
        or acceptance.get("source_content_pass") is not True
        or acceptance.get("full_page_row_level_transcription_pass") is not False
        or not isinstance(boundary, dict)
        or not isinstance(boundary.get("adequate_for"), str)
        or not isinstance(boundary.get("can_report_from_text"), list)
        or not isinstance(boundary.get("must_mark_uncertain_or_unknown"), list)
        or not isinstance(boundary.get("exclude_or_bound"), list)
    ):
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_BINDING_MISMATCH")
    return {
        "path": str(path),
        "sha256": SOURCE_CANARY_REVIEW_SHA256,
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": boundary,
        "acceptance": acceptance,
    }


def _read_scale_canary_page(
    document_id: str,
    page_number: int,
    expected_page_count: int | None = None,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    if document_id != FIRST_CONTENT_FAIL_PDF_SHA256 or page_number != 1:
        return None
    review = _read_source_text_canary_review()
    if review is None:
        return None
    path = SOURCE_CANARY_ATTEMPT_PATH
    if path.is_symlink() or not path.is_file() or _sha256_file(path) != SOURCE_CANARY_ATTEMPT_SHA256:
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_SHA_MISMATCH")
    try:
        attempt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_INVALID") from None
    text_record = attempt.get("text") if isinstance(attempt, dict) else None
    text = text_record.get("value") if isinstance(text_record, dict) else None
    page = attempt.get("page") if isinstance(attempt, dict) else None
    source_pdf = attempt.get("source_pdf") if isinstance(attempt, dict) else None
    render = attempt.get("render_identity") if isinstance(attempt, dict) else None
    full_result = (attempt.get("ocr_attempt") or {}).get("full_vision_result") if isinstance(attempt, dict) else None
    if (
        not isinstance(attempt, dict)
        or attempt.get("schema") != "v4.pdf_simple_batch.ocr_scale_canary_attempt.v1"
        or attempt.get("status") != "NEW_TEXT_REVIEW_REQUIRED"
        or attempt.get("document_id") != document_id
        or attempt.get("scope_sha256") != SOURCE_CANARY_SCOPE_SHA256
        or not isinstance(source_pdf, dict)
        or source_pdf.get("sha256") != document_id
        or type(source_pdf.get("page_count")) is not int
        or source_pdf.get("page_count") < 1
        or (expected_page_count is not None and source_pdf.get("page_count") != expected_page_count)
        or not isinstance(text, str)
        or len(text) != 5_353
        or _sha256(text.encode("utf-8")) != SOURCE_CANARY_TEXT_SHA256
        or text_record.get("sha256") != SOURCE_CANARY_TEXT_SHA256
        or not isinstance(page, dict)
        or page.get("page_number") != 1
        or page.get("original_dimensions_points") != {"height_points": 5001.0, "width_points": 600.0}
        or page.get("rendered_dimensions_pixels") != {"height_pixels": 13000, "width_pixels": 1560}
        or not isinstance(full_result, dict)
        or full_result.get("status") != "OCR_OK"
        or not isinstance(render, dict)
        or render.get("renderer_sha256") != EXPECTED_RENDERER_SHA256
        or render.get("render_scale_to") != MAX_REPAIR_RENDER_SCALE_TO
    ):
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_BINDING_MISMATCH")
    page_text = pdf_research.PageText(
        page_number=1,
        page_total=source_pdf["page_count"],
        text=text,
        status="OCR_OK",
        text_sha256=SOURCE_CANARY_TEXT_SHA256,
        extraction_method="macOS Vision single-variable 13000px canary",
    )
    return page_text, {
        "status": "REUSED_SOURCE_TEXT_CANARY",
        "attempt_path": str(path),
        "attempt_sha256": SOURCE_CANARY_ATTEMPT_SHA256,
        "text_sha256": SOURCE_CANARY_TEXT_SHA256,
        "reviewer_receipt_path": review["path"],
        "reviewer_receipt_sha256": review["sha256"],
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": review["accepted_markdown_boundary"],
        "original_dimensions_points": page["original_dimensions_points"],
        "rendered_dimensions_pixels": page["rendered_dimensions_pixels"],
        "render_scale_to": render["render_scale_to"],
        "renderer_sha256": render["renderer_sha256"],
        "rendered_image_sha256": render["render_image"]["sha256"],
    }


def _read_slice_canary_page(
    document_id: str,
    page_number: int,
    expected_page_count: int | None = None,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    if document_id != SECOND_CONTENT_FAIL_PDF_SHA256 or page_number != 1:
        return None
    paths = (SLICE_CANARY_ATTEMPT_PATH, SLICE_CANARY_MANIFEST_PATH, SLICE_CANARY_TEXT_PATH, SLICE_CANARY_REVIEW_DEFAULT)
    expected_hashes = (
        SLICE_CANARY_ATTEMPT_SHA256,
        SLICE_CANARY_MANIFEST_SHA256,
        SLICE_CANARY_TEXT_SHA256,
        SLICE_CANARY_REVIEW_SHA256,
    )
    values: list[Any] = []
    for path, expected in zip(paths, expected_hashes):
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != expected:
            raise BatchError("SLICE_SOURCE_CANARY_SHA_MISMATCH")
        try:
            values.append(path.read_bytes())
        except OSError:
            raise BatchError("SLICE_SOURCE_CANARY_READ_FAILED") from None
    try:
        attempt, manifest, text_bytes, review = (
            json.loads(values[0].decode("utf-8")),
            json.loads(values[1].decode("utf-8")),
            values[2],
            json.loads(values[3].decode("utf-8")),
        )
        text = text_bytes.decode("utf-8")
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("SLICE_SOURCE_CANARY_INVALID") from None
    document = attempt.get("document") if isinstance(attempt, dict) else None
    helper = attempt.get("helper_identity") if isinstance(attempt, dict) else None
    result = attempt.get("result") if isinstance(attempt, dict) else None
    render = attempt.get("render") if isinstance(attempt, dict) else None
    segmentation = attempt.get("segmentation") if isinstance(attempt, dict) else None
    parts = manifest.get("parts") if isinstance(manifest, dict) else None
    boundary = review.get("accepted_markdown_boundary") if isinstance(review, dict) else None
    if (
        not isinstance(attempt, dict)
        or attempt.get("schema") != "v4.pdf_research_simple_batch.longscan_slice_ocr_canary.v1"
        or attempt.get("status") != "OCR_COMPLETE_SOURCE_REVIEW_PENDING"
        or not isinstance(document, dict)
        or document.get("pdf_sha256") != document_id
        or document.get("page_number") != 1
        or document.get("page_count") != 1
        or (expected_page_count is not None and expected_page_count != 1)
        or attempt.get("scope_sha256") != SLICE_CANARY_SCOPE_SHA256
        or not isinstance(helper, dict)
        or helper.get("prepare_crop_sha256") != EXPECTED_V3_PREPARE_OCR_SHA256
        or helper.get("common_sha256") != EXPECTED_V3_COMMON_SHA256
        or helper.get("renderer_sha256") != EXPECTED_RENDERER_SHA256
        or helper.get("renderer_version") != EXPECTED_RENDERER_VERSION
        or helper.get("vision_source_sha256") != EXPECTED_VISION_SOURCE_SHA256
        or helper.get("vision_config_sha256") != EXPECTED_VISION_CONFIG_SHA256
        or helper.get("slice_height") != 9_000
        or not isinstance(render, dict)
        or render.get("width_pixels") != 1_541
        or render.get("height_pixels") != 13_000
        or not isinstance(segmentation, dict)
        or segmentation.get("gap_free") is not True
        or segmentation.get("overlap") != 0
        or not isinstance(result, dict)
        or result.get("status") != "OCR_OK_SLICED"
        or result.get("part_text_order") != [1, 2]
        or result.get("sha256") != SLICE_CANARY_TEXT_SHA256
        or result.get("characters") != 5_202
        or not isinstance(manifest, dict)
        or manifest.get("source_pdf_sha256") != document_id
        or manifest.get("source_image_sha256") != render.get("sha256")
        or manifest.get("width") != 1_541
        or manifest.get("height") != 13_000
        or manifest.get("geometry_validation") != "PASS_GAP_FREE_CONTIGUOUS_NONOVERLAPPING"
        or not isinstance(parts, list)
        or [(row.get("part"), row.get("top"), row.get("bottom")) for row in parts if isinstance(row, dict)] != [(1, 0, 9_000), (2, 9_000, 13_000)]
        or not isinstance(review, dict)
        or review.get("schema") != SOURCE_CANARY_REVIEW_SCHEMA
        or review.get("status") != "SOURCE_CONTENT_PASS"
        or review.get("pdf_sha256") != document_id
        or review.get("scope_sha256") != SLICE_SOURCE_REVIEW_SCOPE_SHA256
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or not isinstance(boundary, dict)
        or not isinstance(boundary.get("adequate_for"), str)
        or not isinstance(boundary.get("can_report_from_text"), list)
        or not isinstance(boundary.get("uncertainties_to_preserve"), list)
        or not isinstance(boundary.get("exclude_or_bound"), list)
        or _sha256(text_bytes) != SLICE_CANARY_TEXT_SHA256
        or len(text) != 5_202
    ):
        raise BatchError("SLICE_SOURCE_CANARY_BINDING_MISMATCH")
    page_text = pdf_research.PageText(
        page_number=1,
        page_total=1,
        text=text,
        status="OCR_OK",
        text_sha256=SLICE_CANARY_TEXT_SHA256,
        extraction_method="reviewed V3 sliced Vision OCR canary",
    )
    return page_text, {
        "status": "REUSED_SOURCE_TEXT_CANARY",
        "attempt_path": str(paths[0]),
        "attempt_sha256": SLICE_CANARY_ATTEMPT_SHA256,
        "slice_manifest_sha256": SLICE_CANARY_MANIFEST_SHA256,
        "text_sha256": SLICE_CANARY_TEXT_SHA256,
        "reviewer_receipt_path": str(paths[3]),
        "reviewer_receipt_sha256": SLICE_CANARY_REVIEW_SHA256,
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": boundary,
        "rendered_image_sha256": render["sha256"],
        "slice_geometry": [{"part": row["part"], "top": row["top"], "bottom": row["bottom"]} for row in parts],
    }


def _page_geometry(pdf_path: Path, expected_page_count: int, pdf_sha256: str) -> list[dict[str, float]]:
    helper = pdf_research._pinned_pdf_pages_helper()
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        raw = pdf_path.read_bytes()
        if _sha256(raw) != pdf_sha256:
            raise BatchError("PAGE_GEOMETRY_PDF_SHA_MISMATCH")
        pypdf = helper.pinned_pypdf()
        reader = pypdf.PdfReader(BytesIO(raw), strict=False)
        if len(reader.pages) != expected_page_count:
            raise BatchError("PAGE_GEOMETRY_PAGE_COUNT_MISMATCH")
        result: list[dict[str, float]] = []
        for page in reader.pages:
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
            user_unit = float(page.get("/UserUnit", 1) or 1)
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            if not math.isfinite(user_unit) or user_unit <= 0:
                raise BatchError("PAGE_GEOMETRY_UNSUPPORTED")
            width *= user_unit
            height *= user_unit
            if rotation in {90, 270}:
                width, height = height, width
            if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                raise BatchError("PAGE_GEOMETRY_UNSUPPORTED")
            result.append({"width_points": width, "height_points": height, "rotation_degrees": float(rotation)})
        return result
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError(f"PAGE_GEOMETRY_UNSUPPORTED:{type(exc).__name__}") from None
    finally:
        sys.dont_write_bytecode = previous


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BatchError("REPAIR_RENDER_NOT_PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _perform_page_ocr(pdf_path: Path, page_number: int, render_scale_to: int) -> tuple[str, dict[str, Any]]:
    import importlib

    ingestion_path = Path(__file__).resolve().parents[1] / "infrastructure/zsxq_pdf_ingestion.py"
    if ingestion_path.is_symlink() or _sha256_file(ingestion_path) != EXPECTED_PDF_INGESTION_SHA256:
        raise BatchError("PINNED_PDF_INGESTION_SHA_MISMATCH")
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        ingestion = importlib.import_module("infrastructure.zsxq_pdf_ingestion")
        renderer_path = Path(ingestion.DEFAULT_PDFTOPPM)
        if (
            not renderer_path.is_file()
            or _sha256_file(renderer_path) != EXPECTED_RENDERER_SHA256
            or ingestion._renderer_version(renderer_path) != EXPECTED_RENDERER_VERSION
        ):
            raise BatchError("PINNED_PDF_RENDERER_MISMATCH")
        vision, vision_sha, config_sha = ingestion._load_vision_module()
        if (
            vision_sha != EXPECTED_VISION_SOURCE_SHA256
            or config_sha != EXPECTED_VISION_CONFIG_SHA256
            or getattr(vision, "OCR_TIMEOUT_SECONDS", None) != MAX_REPAIR_VISION_SECONDS
        ):
            raise BatchError("PINNED_VISION_HELPER_MISMATCH")
        scripts_root = V3_OCR_SCRIPTS_ROOT
        prepare_path = V3_PREPARE_OCR_PATH
        common_path = V3_COMMON_PATH
        if (
            prepare_path.is_symlink()
            or common_path.is_symlink()
            or _sha256_file(prepare_path) != EXPECTED_V3_PREPARE_OCR_SHA256
            or _sha256_file(common_path) != EXPECTED_V3_COMMON_SHA256
        ):
            raise BatchError("PINNED_V3_SLICE_HELPER_MISMATCH")
        with tempfile.TemporaryDirectory(prefix="pdf_batch_repair_") as temporary:
            temp_root = Path(temporary)
            previous_scale = ingestion.RENDER_SCALE_TO
            ingestion.RENDER_SCALE_TO = render_scale_to
            try:
                image_path = ingestion._render_pdf_page(pdf_path, page_number, temp_root, pdftoppm=renderer_path)
            finally:
                ingestion.RENDER_SCALE_TO = previous_scale
            image_bytes = image_path.stat().st_size
            if image_bytes <= 0 or image_bytes > MAX_REPAIR_IMAGE_BYTES:
                raise BatchError("REPAIR_RENDER_IMAGE_SIZE_INVALID")
            width_pixels, height_pixels = _png_dimensions(image_path)
            if width_pixels > 10_000:
                raise BatchError("REPAIR_HORIZONTAL_SLICING_UNSUPPORTED")
            if height_pixels > 18_000:
                raise BatchError("REPAIR_SLICE_COUNT_EXCEEDED")
            previous_path = list(sys.path)
            sys.path.insert(0, str(scripts_root))
            try:
                common = importlib.import_module("wechat_common")
                prepare = importlib.import_module("wechat_prepare_ocr")
            finally:
                sys.path[:] = previous_path
            if (
                Path(common.__file__).resolve() != common_path.resolve()
                or Path(prepare.__file__).resolve() != prepare_path.resolve()
                or _sha256_file(Path(common.__file__)) != EXPECTED_V3_COMMON_SHA256
                or _sha256_file(Path(prepare.__file__)) != EXPECTED_V3_PREPARE_OCR_SHA256
            ):
                raise BatchError("PINNED_V3_SLICE_HELPER_MISMATCH")
            geometry = {"width": width_pixels, "height": height_pixels, "sliced": height_pixels > 10_000, "parts": []}
            if geometry["sliced"]:
                geometry["parts"] = [
                    {
                        "part": part_number,
                        "top": top,
                        "bottom": min(top + 9_000, height_pixels),
                        "width": width_pixels,
                        "height": min(top + 9_000, height_pixels) - top,
                    }
                    for part_number, top in enumerate(range(0, height_pixels, 9_000), start=1)
                ]
            try:
                common.validate_slice_geometry(geometry)
            except (ValueError, TypeError, KeyError):
                raise BatchError("REPAIR_SLICE_GEOMETRY_INVALID") from None
            if len(geometry["parts"]) > 2:
                raise BatchError("REPAIR_SLICE_COUNT_EXCEEDED")
            executable = vision._compile_vision_helper(temp_root)
            intervals = geometry["parts"] or [{"part": 1, "top": 0, "bottom": height_pixels, "width": width_pixels, "height": height_pixels}]
            page_texts: list[str] = []
            slice_provenance: list[dict[str, Any]] = []
            aggregate_started = time.monotonic()
            for part in intervals:
                part_path = image_path
                if geometry["sliced"]:
                    part_path = temp_root / f"page-{page_number:04d}-part-{part['part']:02d}.png"
                    prepare._crop_image(
                        image_path,
                        part_path,
                        width=width_pixels,
                        top=part["top"],
                        height=part["height"],
                    )
                crop_width, crop_height = prepare._image_size(part_path)
                if (crop_width, crop_height) != (part["width"], part["height"]):
                    raise BatchError("REPAIR_SLICE_DIMENSIONS_MISMATCH")
                call_started = time.monotonic()
                ocr_result = vision._vision_ocr(executable, part_path)
                call_elapsed = time.monotonic() - call_started
                if time.monotonic() - aggregate_started > MAX_REPAIR_VISION_AGGREGATE_SECONDS:
                    raise BatchError("REPAIR_VISION_AGGREGATE_TIMEOUT")
                if not isinstance(ocr_result, Mapping) or ocr_result.get("status") != "OCR_OK":
                    raise BatchError("REPAIR_VISION_FAILED")
                part_text = ocr_result.get("text")
                if not isinstance(part_text, str) or not part_text.strip():
                    raise BatchError("REPAIR_VISION_TEXT_EMPTY")
                page_texts.append(part_text)
                slice_provenance.append(
                    {
                        "part": part["part"],
                        "top": part["top"],
                        "bottom": part["bottom"],
                        "width_pixels": crop_width,
                        "height_pixels": crop_height,
                        "crop_sha256": _sha256_file(part_path),
                        "text_sha256": _sha256(part_text.encode("utf-8")),
                        "text_characters": len(part_text),
                        "elapsed_seconds": call_elapsed,
                    }
                )
            text = "\n".join(page_texts)
            aggregate_elapsed = time.monotonic() - aggregate_started
            provenance = {
                "method": "existing_pdf_ingestion_renderer_and_macos_vision_leaf",
                "pdf_sha256": pdf_research._sha256_path(pdf_path),
                "page_number": page_number,
                "source_text_sha256": _sha256(text.encode("utf-8")),
                "source_text_characters": len(text),
                "renderer_path": str(renderer_path),
                "renderer_sha256": EXPECTED_RENDERER_SHA256,
                "renderer_version": EXPECTED_RENDERER_VERSION,
                "vision_source_sha256": vision_sha,
                "vision_config_sha256": config_sha,
                "render_scale_to": render_scale_to,
                "rendered_dimensions_pixels": {"width_pixels": width_pixels, "height_pixels": height_pixels},
                "rendered_image_sha256": _sha256_file(image_path),
                "rendered_image_bytes": image_bytes,
                "slice_helper_sha256": EXPECTED_V3_PREPARE_OCR_SHA256,
                "slice_geometry_helper_sha256": EXPECTED_V3_COMMON_SHA256,
                "slice_geometry_status": "GAP_FREE_CONTIGUOUS_NONOVERLAPPING",
                "slice_count": len(slice_provenance),
                "slice_provenance": slice_provenance,
                "vision_aggregate_elapsed_seconds": aggregate_elapsed,
                "vision_aggregate_timeout_seconds": MAX_REPAIR_VISION_AGGREGATE_SECONDS,
                "render_timeout_seconds": MAX_REPAIR_RENDER_SECONDS,
                "vision_timeout_seconds": MAX_REPAIR_VISION_SECONDS,
                "attempts_used_for_page": 1,
            }
            return text, provenance
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError(f"REPAIR_VISION_FAILED:{type(exc).__name__}") from None
    finally:
        sys.dont_write_bytecode = previous_bytecode


def _is_ocr_page(page: pdf_research.PageText | None) -> bool:
    if page is None:
        return False
    method = str(page.extraction_method or "").casefold()
    return page.status == "OCR_OK" or "ocr" in method or "vision" in method


def _derived_page_path(state_root: Path, document_id: str, page_number: int) -> Path:
    return state_root / "documents" / document_id / "derived-ocr" / f"page-{page_number:04d}.json"


def _read_derived_page(
    state_root: Path,
    document_id: str,
    page_number: int,
    page_total: int,
    pdf_sha256: str,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    path = _derived_page_path(state_root, document_id, page_number)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise BatchError("DERIVED_OCR_INPUT_PATH_INVALID")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("DERIVED_OCR_INPUT_INVALID") from None
    text = value.get("text") if isinstance(value, dict) else None
    provenance = value.get("provenance") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("schema") != SOURCE_REPAIR_SCHEMA
        or value.get("pdf_sha256") != pdf_sha256
        or value.get("page_number") != page_number
        or value.get("page_count") != page_total
        or not isinstance(text, str)
        or not text.strip()
        or _sha256(text.encode("utf-8")) != value.get("text_sha256")
        or not isinstance(provenance, dict)
    ):
        raise BatchError("DERIVED_OCR_INPUT_BINDING_MISMATCH")
    return (
        pdf_research.PageText(page_number, page_total, text, "OCR_OK", value["text_sha256"], "derived OCR in isolated batch state"),
        {"status": "REUSED_DERIVED_OCR", "path": str(path), "sha256": _sha256_file(path), **provenance},
    )


def _cache_render_dimensions(candidate: Mapping[str, Any], page_number: int) -> tuple[int, int] | None:
    path_value = candidate.get("path")
    if not isinstance(path_value, str):
        return None
    try:
        path = Path(path_value)
        if path.is_symlink() or _sha256_file(path) != candidate.get("sha256"):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    rows = value.get("pages") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return None
    row = next(
        (item for item in rows if isinstance(item, dict) and item.get("page_number") == page_number),
        rows[page_number - 1] if page_number <= len(rows) and isinstance(rows[page_number - 1], dict) else None,
    )
    if not isinstance(row, dict):
        return None
    dimensions = row.get("rendered_dimensions_pixels") or row.get("render_dimensions_pixels")
    if not isinstance(dimensions, dict):
        render = row.get("render_identity")
        image = render.get("render_image") if isinstance(render, dict) else None
        dimensions = image if isinstance(image, dict) else None
    if not isinstance(dimensions, dict):
        return None
    width = dimensions.get("width_pixels", dimensions.get("width"))
    height = dimensions.get("height_pixels", dimensions.get("height"))
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        return None
    return width, height


def _source_repair_qualification(source: Mapping[str, Any]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    general_ocr_pages: list[int] = []
    for row in source.get("page_extraction_sources", []):
        if not isinstance(row, dict):
            continue
        page_number = row.get("page_number")
        canary = row.get("source_text_canary")
        if isinstance(canary, dict):
            accepted.append({"page_number": page_number, **canary})
        elif row.get("selected") in {"REUSED_DERIVED_OCR", "RENDERED_DERIVED_OCR"} or (
            row.get("selected") in {"EXISTING_CACHE", "EXISTING_CACHE_QUALITY_REPLACEMENT"}
            and (
                row.get("cache_status") == "OCR_OK"
                or "ocr" in str(row.get("extraction_method", "")).casefold()
                or "vision" in str(row.get("extraction_method", "")).casefold()
            )
        ):
            general_ocr_pages.append(page_number)
    return {
        "semantic_source_acceptance_status": "SOURCE_REVIEW_PENDING",
        "reviewed_canary_pages": accepted,
        "unreviewed_ocr_pages": general_ocr_pages,
        "generic_ocr_limitations": (
            "For unreviewed OCR pages, names, codes, table rows and exact numbers may be mistranscribed; "
            "the limitation concerns extracted text quality and does not imply damage or unreadability of the original PDF."
            if general_ocr_pages
            else None
        ),
    }


def _discover_native_pages(pdf_path: Path, pdf_sha: str) -> tuple[list[pdf_research.PageText] | None, str]:
    """Use only the already pinned native helper when inventory has no page count/cache."""
    if pdf_path.stat().st_size > pdf_research.PDF_PAGES_MAX_BYTES:
        return None, "NATIVE_EXTRACTION_SIZE_LIMIT"
    helper = pdf_research._pinned_pdf_pages_helper()
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        raw = pdf_path.read_bytes()
        extracted = helper.extract_pdf_pages(
            raw,
            max_pages=500,
            max_bytes=pdf_research.PDF_PAGES_MAX_BYTES,
        )
    except Exception as exc:
        return None, f"NATIVE_EXTRACTION_FAILED:{type(exc).__name__}"
    finally:
        sys.dont_write_bytecode = previous
    if extracted.get("pdf_sha256") != pdf_sha:
        raise BatchError("NATIVE_EXTRACTION_PDF_SHA_MISMATCH")
    page_count = extracted.get("page_count")
    rows = extracted.get("pages")
    if type(page_count) is not int or not isinstance(rows, list) or len(rows) != page_count:
        raise BatchError("NATIVE_EXTRACTION_PAGE_COUNT_INVALID")
    pages: list[pdf_research.PageText] = []
    for index, row in enumerate(rows, start=1):
        text = row.get("text") if isinstance(row, dict) and isinstance(row.get("text"), str) else ""
        status = "NATIVE_TEXT" if text.strip() and row.get("status") == "COMPLETE" else "BLANK"
        pages.append(
            pdf_research.PageText(
                page_number=index,
                page_total=page_count,
                text=text,
                status=status,
                text_sha256=_sha256(text.encode("utf-8")),
                extraction_method="pypdf-6.10.0-native",
            )
        )
    return pages, "COMPLETE" if extracted.get("complete") is True else "PARTIAL_OR_BLANK"


def load_pages(
    document: Mapping[str, Any],
    *,
    state_root: Path | None = None,
    repair_budget: dict[str, int] | None = None,
    preparation_mode: bool = False,
    read_only: bool = False,
    resume_pages: Mapping[int, tuple[pdf_research.PageText, Mapping[str, Any]]] | None = None,
    page_callback: Callable[[pdf_research.PageText, Mapping[str, Any]], None] | None = None,
    before_page: Callable[[], None] | None = None,
) -> tuple[list[pdf_research.PageText], dict[str, Any]]:
    pdf_path = pdf_research._validate_pdf_path(Path(str(document.get("local_pdf_path", ""))))
    before = pdf_path.stat()
    pdf_sha = pdf_research._sha256_path(pdf_path)
    after = pdf_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BatchError("SOURCE_PDF_CHANGED_DURING_HASH")
    if pdf_sha != document.get("pdf_sha256") or before.st_size != document.get("pdf_bytes"):
        raise BatchError("SOURCE_PDF_BINDING_MISMATCH")
    page_count = _candidate_page_count(document)

    cache_options = sorted(
        (item for item in document.get("cache_candidates", []) if isinstance(item, dict)),
        key=lambda item: (0 if item.get("coverage_status") == "COMPLETE" else 1),
    )
    cached_pages: list[pdf_research.PageText] | None = None
    cache_info: dict[str, Any] | None = None
    selected_cache_candidate: Mapping[str, Any] | None = None
    cache_errors: list[str] = []
    for candidate in cache_options:
        cache_sha = candidate.get("sha256")
        if (
            candidate.get("page_count") != page_count
            or not isinstance(cache_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", cache_sha)
            or not isinstance(candidate.get("path"), str)
        ):
            if read_only:
                raise BatchError("CACHE_CANDIDATE_IDENTITY_INVALID")
            cache_errors.append("CACHE_CANDIDATE_IDENTITY_INVALID")
            continue
        try:
            cached_pages, cache_info = pdf_research.load_page_cache(
                pages_cache_path=Path(candidate["path"]),
                pages_cache_sha256=cache_sha,
                pages_cache_pdf_sha256=candidate.get("pdf_sha256"),
                pdf_sha256=pdf_sha,
                page_count=page_count,
            )
            selected_cache_candidate = candidate
            break
        except Exception as exc:
            if read_only:
                raise
            cache_errors.append(str(getattr(exc, "code", None) or type(exc).__name__)[:96])

    if cache_options and cached_pages is None and cache_errors:
        raise BatchError("PAGE_CACHE_CANDIDATES_INVALID:" + ";".join(cache_errors))

    if page_count is None:
        native_pages, native_status = _discover_native_pages(pdf_path, pdf_sha)
        if native_pages:
            page_count = len(native_pages)
        else:
            raise BatchError("PAGE_COUNT_UNAVAILABLE")
    else:
        native_pages, native_status = pdf_research.extract_native_pdf_pages(pdf_path, page_count)
    native_quality = pdf_text_preparation.assess_document_pages(native_pages or [])
    cached_quality = {
        page.page_number: pdf_text_preparation.assess_text_quality(page.text)
        for page in (cached_pages or [])
    }
    cache_replacements: set[int] = set()
    suspicious_pages: list[int] = []
    for page_number in range(1, page_count + 1):
        native = native_pages[page_number - 1] if native_pages and page_number <= len(native_pages) else None
        cached = cached_pages[page_number - 1] if cached_pages and page_number <= len(cached_pages) else None
        native_assessment = native_quality.get(page_number, pdf_text_preparation.assess_text_quality(""))
        cached_assessment = cached_quality.get(page_number, {})
        cache_usable = (
            cached is not None
            and bool(cached.text.strip())
            and cached.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"}
            and cached_assessment.get("status") == "PASS"
        )
        if cache_usable and pdf_text_preparation.cached_text_replaces_native(
            native.text if native is not None else "",
            cached.text,
            native_assessment=native_assessment,
            cached_assessment=cached_assessment,
        ):
            cache_replacements.add(page_number)
        elif native is None or native.status != "NATIVE_TEXT" or native_assessment.get("needs_context"):
            suspicious_pages.append(page_number)
    try:
        image_presence = pdf_text_preparation.inspect_page_images(
            pdf_path,
            pdf_sha256=pdf_sha,
            page_count=page_count,
            # Even a good native layer can omit an image/table/chart body.
            page_numbers=[page for page in range(1, page_count + 1) if page not in cache_replacements],
        )
    except pdf_text_preparation.PreparationError as exc:
        if exc.code in pdf_text_preparation.FATAL_SOURCE_CODES:
            raise BatchError(exc.code) from None
        image_presence = {page_number: None for page_number in range(1, page_count + 1) if page_number not in cache_replacements}
    try:
        geometries = [] if read_only else _page_geometry(pdf_path, page_count, pdf_sha)
        geometry_error = None
    except BatchError as exc:
        geometries = []
        geometry_error = exc.code
    budget = repair_budget if repair_budget is not None else {"remaining": MAX_REPAIR_PAGES_PER_TICK}
    canary_review: dict[str, Any] | None = None
    canary_review_checked = False
    selected: list[pdf_research.PageText] = []
    page_sources: list[dict[str, Any]] = []
    repair_states: list[str] = []
    ocr_invoked = False
    new_ocr_attempts = 0
    for index in range(page_count):
        native = native_pages[index] if native_pages and index < len(native_pages) else None
        cached = cached_pages[index] if cached_pages and index < len(cached_pages) else None
        page_number = index + 1
        geometry = geometries[index] if index < len(geometries) else None
        row: dict[str, Any] = {"page_number": page_number}
        if before_page is not None:
            before_page()
        if resume_pages is not None and page_number in resume_pages:
            resumed_page, resumed_row = resume_pages[page_number]
            if resumed_page.page_total != page_count or resumed_page.page_number != page_number:
                raise BatchError("PREPARATION_RESUME_PAGE_BINDING_MISMATCH")
            selected.append(resumed_page)
            page_sources.append(dict(resumed_row))
            selected_kind = str(resumed_row.get("selected", ""))
            if selected_kind in {"RENDERED_DERIVED_OCR", "REUSED_DERIVED_OCR", "EXISTING_CACHE_QUALITY_REPLACEMENT"}:
                repair_states.append("COMPLETE")
            elif selected_kind.startswith("SOURCE_REPAIR_PENDING"):
                repair_states.append("PENDING_RESUME")
            continue
        if geometry is not None:
            width_points = geometry["width_points"]
            height_points = geometry["height_points"]
            long_edge_points = max(width_points, height_points)
            baseline_density = BASELINE_RENDER_SCALE_TO / long_edge_points
            row.update(
                {
                    "original_dimensions_points": geometry,
                    "baseline_render_scale_to": BASELINE_RENDER_SCALE_TO,
                    "baseline_render_density_pixels_per_point": baseline_density,
                }
            )
        else:
            baseline_density = None
            row["page_geometry_status"] = geometry_error or "CANNOT_CONFIRM"
        native_assessment = native_quality.get(page_number, pdf_text_preparation.assess_text_quality(""))
        cached_assessment = cached_quality.get(page_number, {})
        image_status = image_presence.get(page_number)
        cache_render = (
            _cache_render_dimensions(selected_cache_candidate, page_number)
            if cached_pages and selected_cache_candidate is not None
            else None
        )
        cache_density = None
        if geometry is not None and cache_render is not None:
            cache_density = min(
                cache_render[0] / geometry["width_points"],
                cache_render[1] / geometry["height_points"],
            )
            row["cache_render_dimensions_pixels"] = {"width_pixels": cache_render[0], "height_pixels": cache_render[1]}
            row["cache_render_density_pixels_per_point"] = cache_density
        metadata_proves_adequate = cache_density is not None and cache_density >= 1.0
        if page_number in cache_replacements and cached is not None:
            selected.append(cached)
            row.update(
                {
                    "selected": "EXISTING_CACHE_QUALITY_REPLACEMENT",
                    "cache_status": cached.status,
                    "extraction_method": cached.extraction_method or "UNSPECIFIED",
                    "native_text_quality": dict(native_assessment),
                    "cache_text_quality": dict(cached_assessment),
                    "quality_replacement_reason": "CACHE_HAS_DISTINCT_INFORMATION_WHERE_NATIVE_TEXT_IS_SUSPICIOUS",
                    "cache_render_metadata_verified_adequate": metadata_proves_adequate or baseline_density is not None and baseline_density >= 1.0,
                    "preparation_gate": "READY",
                }
            )
            if _is_ocr_page(cached):
                row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is False and (
            not native_assessment.get("needs_context")
            or image_status is False and not native_assessment.get("repeated_short_page") and not native_assessment.get("repeated_contact_page")
        ):
            selected.append(native)
            row.update(
                {
                    "selected": "PINNED_PYPDF_NATIVE",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "READY",
                    "preparation_quality_reason": "SPARSE_NATIVE_TEXT_NO_IMAGE_EVIDENCE" if native_assessment.get("needs_context") else "NATIVE_TEXT_PASSES_QUALITY_CHECK",
                }
            )
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is None:
            selected.append(pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None))
            row.update(
                {
                    "selected": "PAGE_IMAGE_IDENTITY_UNKNOWN",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "QUARANTINED",
                    "preparation_failure_code": "PAGE_IMAGE_IDENTITY_UNKNOWN",
                }
            )
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is False:
            selected.append(pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None))
            row.update(
                {
                    "selected": "REPEATED_SHORT_TEXT_WITHOUT_BODY",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "QUARANTINED",
                    "preparation_failure_code": "REPEATED_SHORT_TEXT_WITHOUT_BODY",
                }
            )
        else:
            unknown_non_native_cache = (
                cached is not None
                and bool(cached.text.strip())
                and not (cached.status == "NATIVE_TEXT" or "pypdf" in str(cached.extraction_method or "").casefold())
            )
            low_resolution = (baseline_density is None and unknown_non_native_cache) or (
                baseline_density is not None and baseline_density < LOW_RENDER_DENSITY_PIXELS_PER_POINT and not metadata_proves_adequate
            )
            if image_status is True:
                low_resolution = True
            row["low_resolution_raster_suspected"] = low_resolution
            row["native_text_quality"] = dict(native_assessment)
            row["image_presence"] = image_status if page_number in image_presence else "NOT_INSPECTED"
            if low_resolution and not read_only:
                repair_states.append("NEEDS_REPAIR")
                recovered: tuple[pdf_research.PageText, dict[str, Any]] | None = None
                if not preparation_mode and not canary_review_checked:
                    canary_review = _read_source_text_canary_review()
                    canary_review_checked = True
                if canary_review is not None and state_root is not None:
                    recovered = _read_derived_page(state_root, str(document["document_id"]), page_number, page_count, pdf_sha)
                if recovered is None:
                    recovered = _read_scale_canary_page(str(document["document_id"]), page_number, page_count)
                    if recovered is not None:
                        repair_provenance = dict(recovered[1])
                        row["selected"] = "REUSED_SOURCE_TEXT_CANARY"
                        row["source_text_canary"] = repair_provenance
                if recovered is None:
                    recovered = _read_slice_canary_page(str(document["document_id"]), page_number, page_count)
                    if recovered is not None:
                        repair_provenance = dict(recovered[1])
                        row["selected"] = "REUSED_SOURCE_TEXT_CANARY"
                        row["source_text_canary"] = repair_provenance
                    if recovered is None and canary_review is None and not preparation_mode:
                        repair_states[-1] = "PENDING_SOURCE_TEXT_CANARY_REVIEW"
                        row["selected"] = "SOURCE_REPAIR_PENDING_CANARY_REVIEW"
                    elif recovered is None and state_root is None:
                        repair_states[-1] = "PENDING_BATCH_STATE_ROOT"
                        row["selected"] = "SOURCE_REPAIR_PENDING_STATE_ROOT"
                    elif recovered is None:
                        failed_path = state_root / "documents" / str(document["document_id"]) / "derived-ocr" / f"page-{page_number:04d}.failed.json"
                        if failed_path.is_file():
                            repair_states[-1] = "FAILED_PREVIOUS_ATTEMPT"
                            row["selected"] = "SOURCE_REPAIR_FAILED_NO_RETRY"
                        elif geometry is None:
                            failed_value = {
                                "schema": SOURCE_REPAIR_SCHEMA,
                                "pdf_sha256": pdf_sha,
                                "page_number": page_number,
                                "status": "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY",
                                "failure_code": geometry_error or "PAGE_GEOMETRY_UNAVAILABLE",
                                "attempts_used_for_page": 0,
                            }
                            _write_immutable(failed_path, _json_bytes(failed_value, newline=True), state_root)
                            repair_states[-1] = "FAILED_UNSUPPORTED_GEOMETRY"
                            row["selected"] = "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY"
                            row["failure_code"] = failed_value["failure_code"]
                        elif budget.get("remaining", 0) <= 0:
                            repair_states[-1] = "PENDING_TICK_BUDGET"
                            row["selected"] = "SOURCE_REPAIR_PENDING_TICK_BUDGET"
                        else:
                            long_edge = max(geometry["width_points"], geometry["height_points"]) if geometry else 0
                            render_scale_to = min(
                                MAX_REPAIR_RENDER_SCALE_TO,
                                max(BASELINE_RENDER_SCALE_TO, math.ceil(long_edge * TARGET_RENDER_PIXELS_PER_POINT)),
                            )
                            budget["remaining"] -= 1
                            new_ocr_attempts += 1
                            ocr_invoked = True
                            try:
                                text, provenance = _perform_page_ocr(pdf_path, page_number, render_scale_to)
                                if provenance.get("pdf_sha256") != pdf_sha or provenance.get("page_number") != page_number:
                                    raise BatchError("REPAIR_OCR_SOURCE_BINDING_MISMATCH")
                                rendered = provenance.get("rendered_dimensions_pixels")
                                if not isinstance(rendered, dict):
                                    raise BatchError("REPAIR_RENDER_DIMENSIONS_UNAVAILABLE")
                                raster_density = min(
                                    rendered.get("width_pixels", 0) / geometry["width_points"],
                                    rendered.get("height_pixels", 0) / geometry["height_points"],
                                )
                                if raster_density < LOW_RENDER_DENSITY_PIXELS_PER_POINT:
                                    raise BatchError("REPAIR_RENDER_DENSITY_STILL_LOW")
                                provenance.update(
                                    {
                                        "original_dimensions_points": geometry,
                                        "baseline_render_density_pixels_per_point": baseline_density,
                                        "repair_render_density_pixels_per_point": raster_density,
                                        "repair_trigger": "BASELINE_RENDER_DENSITY_BELOW_1_PIXEL_PER_POINT",
                                        "semantic_source_review_status": "SOURCE_REVIEW_PENDING",
                                    }
                                )
                                derived_value = {
                                    "schema": SOURCE_REPAIR_SCHEMA,
                                    "pdf_sha256": pdf_sha,
                                    "page_number": page_number,
                                    "page_count": page_count,
                                    "text": text,
                                    "text_sha256": _sha256(text.encode("utf-8")),
                                    "provenance": provenance,
                                }
                                derived_path = _derived_page_path(state_root, str(document["document_id"]), page_number)
                                derived_sha = _write_immutable(derived_path, _json_bytes(derived_value, newline=True), state_root)
                                recovered = (
                                    pdf_research.PageText(page_number, page_count, text, "OCR_OK", derived_value["text_sha256"], "derived OCR in isolated batch state"),
                                    {"status": "RENDERED_DERIVED_OCR", "path": str(derived_path), "sha256": derived_sha, **provenance},
                                )
                            except Exception as exc:
                                code = str(getattr(exc, "code", None) or type(exc).__name__)[:96]
                                failed_value = {
                                    "schema": SOURCE_REPAIR_SCHEMA,
                                    "pdf_sha256": pdf_sha,
                                    "page_number": page_number,
                                    "status": "SOURCE_REPAIR_FAILED_NO_RETRY",
                                    "failure_code": code,
                                    "attempts_used_for_page": 1,
                                    "original_dimensions_points": geometry,
                                    "baseline_render_density_pixels_per_point": baseline_density,
                                }
                                _write_immutable(failed_path, _json_bytes(failed_value, newline=True), state_root)
                                repair_states[-1] = "FAILED_SINGLE_ATTEMPT"
                                row["selected"] = "SOURCE_REPAIR_FAILED_NO_RETRY"
                                row["failure_code"] = code
                if recovered is not None:
                    selected.append(recovered[0])
                    if row.get("selected") != "REUSED_SOURCE_TEXT_CANARY":
                        row["selected"] = recovered[1].get("status")
                        row["repair_provenance"] = dict(recovered[1])
                    if recovered[1].get("status") != "REUSED_SOURCE_TEXT_CANARY":
                        general_ocr = True
                    else:
                        general_ocr = False
                    if general_ocr:
                        row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
                else:
                    selected.append(
                        pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None)
                    )
            elif cached is not None and cached.text.strip() and cached.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"}:
                selected.append(cached)
                row.update(
                    {
                        "selected": "EXISTING_CACHE",
                        "cache_status": cached.status,
                        "extraction_method": cached.extraction_method or "UNSPECIFIED",
                        "cache_render_metadata_verified_adequate": metadata_proves_adequate or baseline_density is not None and baseline_density >= 1.0,
                        "preparation_gate": "READY" if cached_assessment.get("status") == "PASS" else "QUARANTINED",
                        "preparation_quality": dict(cached_assessment),
                    }
                )
                if _is_ocr_page(cached):
                    row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
            elif native is not None:
                selected.append(native)
                row["selected"] = "PINNED_PYPDF_NATIVE_EMPTY_OR_FAILED"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_NATIVE_TEXT_EMPTY_OR_FAILED"
            elif cached is not None:
                selected.append(cached)
                row["selected"] = "EXISTING_CACHE_EMPTY"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_CACHE_TEXT_EMPTY"
            else:
                selected.append(
                    pdf_research.PageText(
                        page_number=page_number,
                        page_total=page_count,
                        text="",
                        status="TEXT_UNAVAILABLE",
                        text_sha256=_sha256(b""),
                        extraction_method=None,
                    )
                )
                row["selected"] = "TEXT_UNAVAILABLE"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_TEXT_UNAVAILABLE"
        chosen_page = selected[-1]
        quality = pdf_text_preparation.assess_text_quality(chosen_page.text)
        row.setdefault("preparation_quality", dict(quality))
        row.setdefault("page_status", chosen_page.status)
        if row.get("preparation_gate") not in {"READY", "QUARANTINED"}:
            sparse_native_without_image = (
                chosen_page.text.strip()
                and chosen_page.status in {"NATIVE_TEXT", "COMPLETE"}
                and image_status is False
                and not native_assessment.get("repeated_short_page")
                and not native_assessment.get("repeated_contact_page")
            )
            if chosen_page.text.strip() and chosen_page.status in {"NATIVE_TEXT", "COMPLETE", "OCR_OK"} and (
                quality.get("status") == "PASS" or sparse_native_without_image
            ):
                row["preparation_gate"] = "READY"
            else:
                row["preparation_gate"] = "QUARANTINED"
                row.setdefault("preparation_failure_code", quality.get("reason") or "PAGE_QUALITY_UNRESOLVED")
        if page_callback is not None and row.get("selected", "").startswith("SOURCE_REPAIR_PENDING") is False:
            page_callback(chosen_page, row)
        page_sources.append(row)
    if len(selected) != page_count:
        raise BatchError("SELECTED_PAGE_COUNT_MISMATCH")
    complete = all(page.text.strip() and page.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"} for page in selected)
    all_nonempty = all(bool(page.text.strip()) for page in selected)
    any_nonempty = any(bool(page.text.strip()) for page in selected)
    has_ocr = any(
        row.get("selected") in {"EXISTING_CACHE", "EXISTING_CACHE_QUALITY_REPLACEMENT"}
        and (row.get("cache_status") == "OCR_OK" or "ocr" in str(row.get("extraction_method", "")).casefold())
        for row in page_sources
    )
    repair_status = (
        "FAILED_SINGLE_ATTEMPT"
        if "FAILED_SINGLE_ATTEMPT" in repair_states
        else "FAILED_UNSUPPORTED_GEOMETRY"
        if "FAILED_UNSUPPORTED_GEOMETRY" in repair_states
        else "FAILED_PREVIOUS_ATTEMPT"
        if "FAILED_PREVIOUS_ATTEMPT" in repair_states
        else "PENDING"
        if any(status.startswith("PENDING") for status in repair_states)
        else "COMPLETE"
        if repair_states
        else "NOT_REQUIRED"
    )
    source = {
        "pdf_path": str(pdf_path),
        "pdf_sha256": pdf_sha,
        "pdf_bytes": before.st_size,
        "pdf_mtime_ns": before.st_mtime_ns,
        "page_count": page_count,
        "source_page_text_sha256": _sha256("".join(page.text for page in selected).encode("utf-8")),
        "page_extraction_status": "COMPLETE" if complete else "PARTIAL" if any_nonempty else "TEXT_UNAVAILABLE",
        "all_pages_nonempty": all_nonempty,
        "any_page_nonempty": any_nonempty,
        "selected_pages_complete": complete,
        "page_extraction_sources": page_sources,
        "source_repair_status": repair_status,
        "source_text_acceptance": _source_repair_qualification({"page_extraction_sources": page_sources}),
        "new_ocr_attempts_this_tick": new_ocr_attempts,
        "cache": cache_info or {"status": "UNAVAILABLE", "errors": cache_errors},
        "native_extraction_status": native_status,
        "cached_ocr_visual_quality_status": "CANNOT_CONFIRM_NOT_VISUALLY_REVIEWED" if has_ocr else "NOT_APPLICABLE_NO_SELECTED_OCR_CACHE",
        "ocr_invoked": ocr_invoked,
        "page_image_inspection": "NOT_RUN_READ_ONLY" if read_only else "REQUESTED",
        "source_paths": list(document.get("source_paths", [])),
        "data_role": document.get("data_role") or "CANNOT_CONFIRM",
        "pit_status": document.get("pit_status") or "CANNOT_CONFIRM",
    }
    return selected, source

