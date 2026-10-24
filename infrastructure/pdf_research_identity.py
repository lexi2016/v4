"""Pure input identities for PDF research; no stores, model calls or publication.

Occurrences describe where bytes were found. Analysis identity describes exactly
what the model sees, so occurrence duplicates can share an analysis only when
all visible input and semantic configuration are identical.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from infrastructure.pdf_research import PageText

INPUT_MANIFEST_SCHEMA = "v4.pdf_research.analysis_input.v1"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class IdentityError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise IdentityError("ANALYSIS_INPUT_NOT_CANONICAL_JSON") from None


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(name + "_REQUIRED")
    return value


@dataclass(frozen=True)
class SourceOccurrence:
    namespace: str
    original_source_id: str

    def __post_init__(self) -> None:
        _required_string(self.namespace, "SOURCE_NAMESPACE")
        _required_string(self.original_source_id, "ORIGINAL_SOURCE_ID")

    @property
    def occurrence_id(self) -> str:
        return hashlib.sha256(canonical_json([self.namespace, self.original_source_id])).hexdigest()


@dataclass(frozen=True)
class AnalysisConfiguration:
    model_id: str
    model_version: str
    model_config: Mapping[str, Any]
    schema: Mapping[str, Any]
    schema_version: str
    prompt: Any
    prompt_version: str
    semantic_pipeline_version: str


@dataclass(frozen=True)
class AnalysisInputIdentity:
    analysis_id: str
    canonical_manifest: bytes

    @property
    def manifest(self) -> dict[str, Any]:
        # Return a fresh value: callers cannot mutate the bytes behind this ID.
        return json.loads(self.canonical_manifest)


def build_analysis_identity(
    *,
    pdf_sha256: str,
    pages: Sequence[PageText],
    page_count: int,
    extraction_provenance: Mapping[str, Any],
    extraction_version: str,
    model_visible_metadata: Mapping[str, Any],
    configuration: AnalysisConfiguration,
) -> AnalysisInputIdentity:
    """Hash a complete caller-supplied input contract, never titles or paths.

    Metadata must contain every field visible in the actual request. Dates are
    explicit inputs; unknown dates stay null and are never inferred from a name.
    Partial page coverage is recorded, not promoted to complete coverage.
    """
    if not isinstance(pdf_sha256, str) or not _SHA256.fullmatch(pdf_sha256):
        raise IdentityError("PDF_SHA256_INVALID")
    if type(page_count) is not int or page_count < 1:
        raise IdentityError("PAGE_COUNT_INVALID")
    if not isinstance(extraction_provenance, Mapping) or not isinstance(model_visible_metadata, Mapping):
        raise IdentityError("INPUT_METADATA_INVALID")
    _required_string(extraction_version, "EXTRACTION_VERSION")
    for name in ("model_id", "model_version", "schema_version", "prompt_version", "semantic_pipeline_version"):
        _required_string(getattr(configuration, name), name.upper())
    if not isinstance(configuration.model_config, Mapping) or not isinstance(configuration.schema, Mapping):
        raise IdentityError("ANALYSIS_CONFIGURATION_INVALID")
    if configuration.prompt is None:
        raise IdentityError("PROMPT_REQUIRED")
    rows = []
    previous = 0
    for page in pages:
        number = page.page_number
        if type(number) is not int or not previous < number <= page_count or page.page_total != page_count:
            raise IdentityError("PAGE_ORDER_OR_COVERAGE_INVALID")
        if not isinstance(page.text, str) or not page.text.strip():
            raise IdentityError("PAGE_TEXT_MISSING")
        if page.status not in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"}:
            raise IdentityError("PAGE_TEXT_STATUS_INVALID")
        sha = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
        if page.text_sha256 is not None and page.text_sha256 != sha:
            raise IdentityError("PAGE_TEXT_SHA_MISMATCH")
        rows.append({"page_number": number, "text_sha256": sha, "status": page.status,
                     "extraction_method": page.extraction_method})
        previous = number
    if not rows:
        raise IdentityError("PAGE_TEXT_MISSING")
    metadata = dict(model_visible_metadata)
    for name in ("source_document_date", "archived_date"):
        metadata.setdefault(name, None)
        if metadata[name] is not None and (not isinstance(metadata[name], str) or not metadata[name].strip()):
            raise IdentityError("DATE_METADATA_INVALID")
    manifest = {
        "schema": INPUT_MANIFEST_SCHEMA,
        "pdf_sha256": pdf_sha256,
        "page_count": page_count,
        "coverage": "COMPLETE" if [row["page_number"] for row in rows] == list(range(1, page_count + 1)) else "PARTIAL",
        "pages": rows,
        "extraction": {"version": extraction_version, "provenance": dict(extraction_provenance)},
        "model_visible_metadata": metadata,
        "model": {"id": configuration.model_id, "version": configuration.model_version, "config": dict(configuration.model_config)},
        "output_schema": {"version": configuration.schema_version, "schema": dict(configuration.schema)},
        "prompt": {"version": configuration.prompt_version, "content": configuration.prompt},
        "semantic_pipeline_version": configuration.semantic_pipeline_version,
    }
    raw = canonical_json(manifest)
    return AnalysisInputIdentity(hashlib.sha256(raw).hexdigest(), raw)
