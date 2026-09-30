"""Read one exact-date daily research review from an explicitly configured root.

V4 consumes a dated JSON artifact here.  A V4 generation envelope is exposed as
declared provenance only; this read-only module does not independently verify
receipts, inputs, or producer identity.  It deliberately does not import the
historical application's server, lifespan, or producer graph, and it has no
write path.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


REVIEW_ROOT_ENV = "V4_DAILY_REVIEW_ROOT"
SCHEMA_VERSION = "daily_research_review.v1"
SOURCE_ROLE = "VIBE_DUANXIAN_DAILY_REVIEW"
GENERATOR_GAP = "V4_DAILY_RESEARCH_REVIEW_GENERATOR_NOT_CONNECTED"
V4_GENERATION_SCHEMA = "v4.research_review_generation.v1"
V4_GENERATION_OWNER = "v4_app.domains.research_review_generation"
V4_ASSEMBLY_SCHEMA = "v4.vibe_assembly.v1"
V4_SHARED_AUTHORITY_ID = "V4_OWNED_VIBE_SINGLE_FETCH_OWNER"
V4_GENERATION_DECLARED = "V4_DECLARED_PROVENANCE"
# Keep the import name for callers that used the prior read-only label.  The
# value now makes clear that the reader does not assert independent ownership.
V4_GENERATION_READ_ONLY = V4_GENERATION_DECLARED
V4_PROVENANCE_GAP = "V4_DAILY_RESEARCH_REVIEW_PROVENANCE_UNVERIFIED"
V4_NATURAL_GENERATION_GAP = "V4_DAILY_RESEARCH_REVIEW_NATURAL_GENERATION_CANNOT_CONFIRM"
_LEGACY_REFERENCE = "vibe-astock/main.py -> duanxian.review_store.save"

_SAFETY_FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

_REQUIRED_SECTIONS = (
    ("market_facts", "breadth", "market_breadth"),
    ("market_facts", "feedback_matrix", "feedback_matrix"),
    ("market_facts", "loss_effect", "loss_effect"),
    ("market_facts", "theme_tree", "theme_tree"),
    ("market_facts", "event_ledger", "event_ledger"),
    ("emotion_metrics", "money_effect", "money_effect"),
    ("emotion_metrics", "promotion", "promotion"),
    ("emotion_metrics", "ladder_gap", "ladder_gap"),
)


def _date_pair(value: str) -> tuple[str, str]:
    """Return (compact, ISO) for one strict calendar date."""

    candidate = str(value or "").strip()
    if len(candidate) == 8 and candidate.isdigit():
        parsed = datetime.strptime(candidate, "%Y%m%d")
        return candidate, parsed.strftime("%Y-%m-%d")
    if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
        parsed = datetime.strptime(candidate, "%Y-%m-%d")
        return parsed.strftime("%Y%m%d"), candidate
    raise ValueError("date must use YYYYMMDD or YYYY-MM-DD")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _generation(
    status: str,
    reasons: list[str],
    *,
    owner: str = "CANNOT_CONFIRM",
    producer_reference: str = "",
    reference_only_producer: str = "",
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "owner": owner,
        "cannot_confirm": _unique(reasons),
    }
    if producer_reference:
        result["producer_reference"] = producer_reference
    if reference_only_producer:
        result["reference_only_producer"] = reference_only_producer
    if source_provenance is not None:
        result["source_provenance"] = deepcopy(dict(source_provenance))
    return result


def _declared_v4_generation(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Recognize a minimally well-formed V4 declaration without verifying it.

    Receipt, input, and source hashes are claims made by the producer.  They
    are intentionally not checked here because this endpoint is a read-only
    projection layer; the independent generation receipt remains the authority
    for verification.
    """

    raw = payload.get("v4_generation")
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        return None, "V4_GENERATION_METADATA_NOT_OBJECT"
    if raw.get("schema_version") != V4_GENERATION_SCHEMA:
        return None, "V4_GENERATION_SCHEMA_MISMATCH"
    if raw.get("owner") != V4_GENERATION_OWNER:
        return None, "V4_GENERATION_OWNER_MISMATCH"
    if raw.get("mode") != "v4_owned_graph_candidate":
        return None, "V4_GENERATION_MODE_UNVERIFIED"
    if raw.get("research_only") is not True:
        return None, "V4_GENERATION_RESEARCH_ONLY_MISSING"
    if raw.get("production_allowed") is not False:
        return None, "V4_GENERATION_PRODUCTION_FLAG_UNSAFE"
    if raw.get("natural_generation") != "CANNOT_CONFIRM":
        return None, "V4_GENERATION_NATURAL_STATUS_UNVERIFIED"
    if raw.get("write_policy") != "exact_date_only_no_latest_pointer":
        return None, "V4_GENERATION_WRITE_POLICY_UNVERIFIED"

    source = raw.get("source_provenance")
    if not isinstance(source, Mapping):
        return None, "V4_GENERATION_SOURCE_PROVENANCE_MISSING"
    if source.get("shared_authority_id") != V4_SHARED_AUTHORITY_ID:
        return None, "V4_GENERATION_SHARED_AUTHORITY_MISMATCH"
    if source.get("source_role") != SOURCE_ROLE:
        return None, "V4_GENERATION_SOURCE_ROLE_MISMATCH"

    assembly = source.get("assembly")
    if assembly is not None and (
        not isinstance(assembly, Mapping)
        or assembly.get("schema") != V4_ASSEMBLY_SCHEMA
    ):
        return None, "V4_GENERATION_ASSEMBLY_SCHEMA_INVALID"
    return raw, None


def _project_v4_provenance(source: Mapping[str, Any]) -> dict[str, Any]:
    """Expose producer declarations while making verification unavailable."""

    projected: dict[str, Any] = {}
    for key in (
        "assembly",
        "graph",
        "input_snapshot",
        "natural_generation",
        "section_and_function_sources",
        "shared_authority_id",
        "snapshot",
        "source",
        "source_role",
    ):
        if key in source:
            projected[key] = deepcopy(source[key])
    if "authority_receipt_sha256" in source:
        projected["declared_authority_receipt_sha256"] = deepcopy(
            source["authority_receipt_sha256"]
        )
    if "authority_receipt_independently_verified" in source:
        projected["declared_authority_receipt_independently_verified"] = deepcopy(
            source["authority_receipt_independently_verified"]
        )
    projected["authority_receipt_independently_verified"] = False
    projected["independently_verified"] = False
    projected["provenance_status"] = "DECLARED_ONLY"
    return projected


def _v4_uncertainty_reasons(source: Mapping[str, Any]) -> list[str]:
    reasons = [V4_PROVENANCE_GAP, V4_NATURAL_GENERATION_GAP]
    section_sources = source.get("section_and_function_sources")
    if isinstance(section_sources, Mapping):
        for name in sorted(section_sources):
            entry = section_sources[name]
            if isinstance(entry, Mapping) and str(entry.get("status")) in {
                "CANNOT_CONFIRM",
                "PARTIAL_WITH_CANNOT_CONFIRM",
            }:
                reasons.append(f"V4_SOURCE_CANNOT_CONFIRM:{name}")
    return _unique(reasons)


def _cannot_confirm(
    trade_date: str,
    target_date: str,
    reason: str,
    *,
    source_path: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CANNOT_CONFIRM",
        "artifact_status": "CANNOT_CONFIRM",
        "trade_date": trade_date,
        "target_date": target_date,
        "source_role": SOURCE_ROLE,
        "source_path": source_path,
        "read_diagnostic": {
            "source_role": SOURCE_ROLE,
            "expected_path": source_path or None,
            "failure_layer": ("ROOT_BINDING" if "ROOT_" in reason else
                              "EXACT_DATE_ARTIFACT_READ" if "DATE_FILE_MISSING" in reason else "ARTIFACT_VALIDATION"),
            "reason": reason,
            "artifact_verified": False,
            "owner_execution_verified": False,
            "historical_recovery_status": "INPUT_CLOSURE_NOT_PROVIDED",
            "message": "精确日期读链未通过；路径是预期位置，不是产物存在或生产成功证据。",
        },
        "source_artifact_sha256": "",
        "artifact_sha256": "",
        "data_as_of": "",
        "generated_at": "",
        "generation_status": "CANNOT_CONFIRM",
        "generation": _generation("CANNOT_CONFIRM", [GENERATOR_GAP]),
        "cannot_confirm": _unique([reason]),
        "write_policy": "read_only",
        **_SAFETY_FLAGS,
    }


def _resolve_root(review_root: Path | str | None) -> tuple[Path | None, str | None]:
    configured = os.fspath(review_root) if review_root is not None else os.environ.get(REVIEW_ROOT_ENV, "")
    configured = str(configured).strip()
    if not configured:
        return None, "DAILY_RESEARCH_REVIEW_ROOT_NOT_CONFIGURED"
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        return None, "DAILY_RESEARCH_REVIEW_ROOT_MUST_BE_ABSOLUTE"
    try:
        root = candidate.resolve()
    except OSError:
        return None, "DAILY_RESEARCH_REVIEW_ROOT_CANNOT_RESOLVE"
    if not root.is_dir():
        return None, "DAILY_RESEARCH_REVIEW_ROOT_NOT_FOUND"
    return root, None


def _exact_artifact(root: Path, target_date: str) -> tuple[Path | None, str | None]:
    """Resolve only ``<root>/<target-date>.json``; never inspect ``latest``."""

    path = root / f"{target_date}.json"
    if path.parent != root or path.name != f"{target_date}.json":
        return None, "DAILY_RESEARCH_REVIEW_PATH_INVALID"
    if path.is_symlink():
        return None, "DAILY_RESEARCH_REVIEW_ARTIFACT_SYMLINK_REJECTED"
    try:
        resolved = path.resolve()
    except OSError:
        return None, "DAILY_RESEARCH_REVIEW_ARTIFACT_CANNOT_RESOLVE"
    if resolved.parent != root:
        return None, "DAILY_RESEARCH_REVIEW_ARTIFACT_ESCAPES_ROOT"
    if not path.is_file():
        return None, "DAILY_RESEARCH_REVIEW_DATE_FILE_MISSING"
    return path, None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    # A dated review is normally small.  A bounded read prevents a configured
    # review root from turning this read-only API into an unbounded file read.
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("DAILY_RESEARCH_REVIEW_ARTIFACT_TOO_LARGE")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("DAILY_RESEARCH_REVIEW_ARTIFACT_NOT_OBJECT")
    return value


def _validate_dates(payload: Mapping[str, Any], compact: str, target_date: str) -> None:
    for field in ("target_date", "trade_date"):
        if field not in payload:
            raise ValueError(f"DAILY_RESEARCH_REVIEW_{field.upper()}_MISSING")
        try:
            observed_compact, observed_iso = _date_pair(str(payload[field]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"DAILY_RESEARCH_REVIEW_{field.upper()}_INVALID") from error
        if observed_compact != compact or observed_iso != target_date:
            raise ValueError(
                f"DAILY_RESEARCH_REVIEW_{field.upper()}_MISMATCH:{observed_iso}:{target_date}"
            )


def load_daily_research_review(
    trade_date: str,
    review_root: Path | str | None = None,
) -> dict[str, Any]:
    """Read and project one exact-date research artifact.

    ``review_root`` is intended for explicit callers and tests.  The live API
    uses ``V4_DAILY_REVIEW_ROOT``.  Missing configuration, missing dated files,
    malformed JSON, date mismatch, and unsafe paths all fail closed with
    ``CANNOT_CONFIRM``.  A ``latest.json`` file is never considered.
    """

    try:
        compact, target_date = _date_pair(trade_date)
    except (TypeError, ValueError):
        compact = str(trade_date or "")
        target_date = compact
        return _cannot_confirm(compact, target_date, "DAILY_RESEARCH_REVIEW_REQUEST_DATE_INVALID")

    root, root_error = _resolve_root(review_root)
    if root is None:
        return _cannot_confirm(compact, target_date, root_error or "DAILY_RESEARCH_REVIEW_ROOT_INVALID")
    path, path_error = _exact_artifact(root, target_date)
    if path is None:
        return _cannot_confirm(compact, target_date, path_error or "DAILY_RESEARCH_REVIEW_PATH_INVALID",
                               source_path=str(root / f"{target_date}.json"))

    try:
        payload = _read_json(path)
        _validate_dates(payload, compact, target_date)
        sections: dict[str, Any] = {}
        for parent_key, child_key, output_key in _REQUIRED_SECTIONS:
            parent = payload.get(parent_key)
            if not isinstance(parent, Mapping):
                raise ValueError(f"DAILY_RESEARCH_REVIEW_{parent_key.upper()}_INVALID")
            child = parent.get(child_key)
            if not isinstance(child, Mapping):
                raise ValueError(f"DAILY_RESEARCH_REVIEW_{parent_key}_{child_key}_INVALID")
            sections[output_key] = deepcopy(dict(child))
        artifact_sha = _sha256_file(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        reason = str(error) or f"{type(error).__name__}"
        return _cannot_confirm(compact, target_date, reason, source_path=str(path))

    v4_generation, provenance_error = _declared_v4_generation(payload)
    if v4_generation is not None:
        source_provenance = v4_generation["source_provenance"]
        projected_provenance = _project_v4_provenance(source_provenance)
        reasons = _v4_uncertainty_reasons(source_provenance)
        generation_status = V4_GENERATION_DECLARED
        generation = _generation(
            generation_status,
            reasons,
            owner="CANNOT_CONFIRM",
            producer_reference=V4_GENERATION_OWNER,
            source_provenance=projected_provenance,
        )
        generation.update(
            {
                "declared_owner": V4_GENERATION_OWNER,
                "provenance_status": "DECLARED_ONLY",
                "independently_verified": False,
            }
        )
    elif provenance_error is not None:
        reasons = _unique([V4_PROVENANCE_GAP, provenance_error])
        generation_status = "EXTERNAL_SOURCE_READ_ONLY"
        generation = _generation(
            "REFERENCE_ONLY",
            reasons,
            reference_only_producer=_LEGACY_REFERENCE,
        )
    else:
        reasons = [GENERATOR_GAP]
        generation_status = "EXTERNAL_SOURCE_READ_ONLY"
        generation = _generation(
            "REFERENCE_ONLY",
            reasons,
            reference_only_producer=_LEGACY_REFERENCE,
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY",
        "artifact_status": "READY",
        "trade_date": compact,
        "target_date": target_date,
        "source_role": SOURCE_ROLE,
        "source_path": str(path),
        "source_artifact_sha256": artifact_sha,
        "artifact_sha256": artifact_sha,
        "source_schema_version": payload.get("schema_version"),
        "data_as_of": str(payload.get("data_as_of") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "generation_status": generation_status,
        "generation": generation,
        "cannot_confirm": reasons,
        "write_policy": "read_only",
        **sections,
        **_SAFETY_FLAGS,
    }
    if v4_generation is not None:
        result["source_provenance"] = deepcopy(generation["source_provenance"])
    focus = payload.get("focus")
    if isinstance(focus, Mapping):
        result["focus"] = deepcopy(dict(focus))
    return result


__all__ = [
    "GENERATOR_GAP",
    "REVIEW_ROOT_ENV",
    "SCHEMA_VERSION",
    "V4_ASSEMBLY_SCHEMA",
    "V4_GENERATION_DECLARED",
    "V4_GENERATION_OWNER",
    "V4_GENERATION_READ_ONLY",
    "V4_GENERATION_SCHEMA",
    "V4_NATURAL_GENERATION_GAP",
    "V4_PROVENANCE_GAP",
    "V4_SHARED_AUTHORITY_ID",
    "load_daily_research_review",
]
