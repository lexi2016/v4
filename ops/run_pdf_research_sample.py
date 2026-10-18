#!/usr/bin/env python3
"""Run only the frozen V3 PDF canary/sample through the isolated research queue."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from infrastructure import local_document_model as local_model
from infrastructure import pdf_research


SAMPLE_SCOPE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_PDF_RESEARCH_V3_SAMPLE_20261018_R1"
)
SCOPE_PATH = SAMPLE_SCOPE_ROOT / "scope.json"
SAMPLE_MANIFEST_PATH = SAMPLE_SCOPE_ROOT / "sample-manifest-v1.json"
SOURCE_REVIEW_RECEIPT_PATH = SAMPLE_SCOPE_ROOT / "source-review-receipt.json"
CANARY_REVIEW_RECEIPT_PATH = SAMPLE_SCOPE_ROOT / "canary-review-receipt.json"
SAMPLE_ACCEPTANCE_RECEIPT_PATH = SAMPLE_SCOPE_ROOT / "sample-acceptance-receipt.json"
RUNTIME_BINDING_EVIDENCE_PATH = SAMPLE_SCOPE_ROOT / "runtime-binding-evidence.json"
EXECUTION_SCOPE_RECEIPT_PATH = SAMPLE_SCOPE_ROOT / "execution-scope-receipt.json"
FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH = SAMPLE_SCOPE_ROOT / "first-chunk-acceptance-receipt.json"
EXPECTED_SCOPE_SHA256 = "16125a6159ac0053d03ab12d35343e326f1b8eb69172fbd9e9feb92246346768"
EXPECTED_SAMPLE_MANIFEST_SHA256 = "2195b24526dc7e43603dd438f3109f345239d32ab7aa91c5c74e3465d15db806"
EXPECTED_RUNTIME_BINDING_EVIDENCE_SHA256 = "76fa412e3c2caaa35347b7e017ef09046492ae0d034aae9f16f0752ccb3ae97e"
PREVIOUSLY_REVIEWED_RUNTIME_SETTINGS_SHA256 = "e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99"
PREVIOUSLY_REVIEWED_MODEL_SETTINGS_SHA256 = "7a98bb5d2b6687b808d72b8c7bb385a23c714e9753a067fab81407c4e9245b99"
EXECUTION_SCOPE_SCHEMA = "v4.pdf_research_v3.execution_scope.v2"
EXECUTION_SCOPE_AUTHORIZER = "/root"
CANARY_MAX_MODEL_CALLS = 16


class SampleCliError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_frozen_json(path: Path, *, expected_sha256: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise SampleCliError("FROZEN_INPUT_UNAVAILABLE")
    observed_sha256 = _sha256_file(path)
    if observed_sha256 != expected_sha256:
        raise SampleCliError("FROZEN_INPUT_SHA_MISMATCH")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SampleCliError("FROZEN_INPUT_JSON_INVALID") from None
    if not isinstance(value, dict):
        raise SampleCliError("FROZEN_INPUT_JSON_INVALID")
    return value, observed_sha256


def _reviewed_files() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    relative_paths = (
        "infrastructure/local_document_model.py",
        "infrastructure/pdf_research.py",
        "ops/run_pdf_research_sample.py",
        "tests/test_local_document_model.py",
        "tests/test_pdf_research.py",
        "tests/test_pdf_research_sample_cli.py",
        "docs/handoffs/pdf_research_v3_sample_20261018/README.md",
    )
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = repo_root / relative
        if path.is_symlink() or not path.is_file():
            raise SampleCliError("SOURCE_REVIEW_FILE_UNAVAILABLE")
        result[relative] = _sha256_file(path)
    return result


def _read_review_receipt(path: Path, expected_schema: str, *, expected_status: str = "PASS") -> dict[str, Any]:
    try:
        relative = path.absolute().relative_to(SAMPLE_SCOPE_ROOT.absolute())
    except ValueError:
        raise SampleCliError("REVIEW_RECEIPT_OUTSIDE_SCOPE") from None
    cursor = SAMPLE_SCOPE_ROOT
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SampleCliError("REVIEW_RECEIPT_SYMLINK_FORBIDDEN")
    if not path.is_file():
        raise SampleCliError("REVIEW_RECEIPT_REQUIRED")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SampleCliError("REVIEW_RECEIPT_INVALID") from None
    if not isinstance(value, dict) or value.get("schema") != expected_schema or value.get("status") != expected_status:
        raise SampleCliError("REVIEW_RECEIPT_NOT_PASS")
    return value


def validate_source_review_receipt(path: Path | None = None) -> dict[str, Any]:
    receipt_path = path or SOURCE_REVIEW_RECEIPT_PATH
    receipt = _read_review_receipt(receipt_path, "v4.pdf_research_v3.source_review.v1")
    scope, scope_sha = _read_frozen_inputs_only_scope()
    if receipt.get("scope_sha256") != scope_sha:
        raise SampleCliError("SOURCE_REVIEW_SCOPE_MISMATCH")
    if receipt.get("reviewed_files") != _reviewed_files():
        raise SampleCliError("SOURCE_REVIEW_STALE")
    if receipt.get("reviewer") == "/root/pdf_v3_sample_writer":
        raise SampleCliError("SOURCE_REVIEW_NOT_INDEPENDENT")
    del scope
    return receipt


def _read_frozen_inputs_only_scope() -> tuple[dict[str, Any], str]:
    scope, scope_sha = _read_frozen_json(SCOPE_PATH, expected_sha256=EXPECTED_SCOPE_SHA256)
    if scope.get("status") != "FROZEN" or scope.get("phase") != "V3_IMPLEMENTATION_OFFLINE_FIRST":
        raise SampleCliError("SCOPE_NOT_FROZEN")
    if scope.get("approved_plan_sha256") != "b35f68e2240ed00585aaab6a80e5d5dec65de9707b9d564734f2a2a3f409db53":
        raise SampleCliError("APPROVED_PLAN_HASH_MISMATCH")
    return scope, scope_sha


def load_frozen_documents(phase: str) -> tuple[dict[str, Any], str, str, list[dict[str, Any]]]:
    scope, scope_sha = _read_frozen_inputs_only_scope()
    manifest, manifest_sha = _read_frozen_json(
        SAMPLE_MANIFEST_PATH,
        expected_sha256=EXPECTED_SAMPLE_MANIFEST_SHA256,
    )
    allowed_paths = scope.get("ALLOWED_PATHS")
    if not isinstance(allowed_paths, list) or str(SAMPLE_SCOPE_ROOT) not in allowed_paths:
        raise SampleCliError("SAMPLE_SCOPE_ROOT_NOT_ALLOWLISTED")
    try:
        docs = pdf_research.validate_sample_manifest(manifest, phase=phase)
    except pdf_research.PdfResearchError as exc:
        raise SampleCliError(exc.code) from None
    return scope, scope_sha, manifest_sha, docs


def _validate_canary_receipt(manifest_sha: str) -> dict[str, Any]:
    receipt = _read_review_receipt(CANARY_REVIEW_RECEIPT_PATH, "v4.pdf_research_v3.canary_review.v1")
    if receipt.get("sample_id") != "S01" or receipt.get("sample_manifest_sha256") != manifest_sha:
        raise SampleCliError("CANARY_REVIEW_INPUT_MISMATCH")
    if not isinstance(receipt.get("result_sha256"), str) or len(receipt["result_sha256"]) != 64:
        raise SampleCliError("CANARY_REVIEW_RESULT_SHA_MISSING")
    return receipt


def _validate_sample_acceptance(manifest_sha: str, canary_receipt: Mapping[str, Any]) -> dict[str, Any]:
    receipt = _read_review_receipt(
        SAMPLE_ACCEPTANCE_RECEIPT_PATH,
        "v4.pdf_research_v3.sample_acceptance.v1",
        expected_status="ACCEPTED",
    )
    if receipt.get("decision") != "ACCEPTED":
        raise SampleCliError("USER_ACCEPTANCE_REQUIRED_BEFORE_SAMPLE")
    if receipt.get("sample_manifest_sha256") != manifest_sha or receipt.get("canary_result_sha256") != canary_receipt.get("result_sha256"):
        raise SampleCliError("SAMPLE_ACCEPTANCE_INPUT_MISMATCH")
    return receipt


def _read_accepted_runtime_binding_evidence() -> tuple[dict[str, Any], str]:
    evidence, evidence_sha = _read_frozen_json(
        RUNTIME_BINDING_EVIDENCE_PATH,
        expected_sha256=EXPECTED_RUNTIME_BINDING_EVIDENCE_SHA256,
    )
    if (
        evidence.get("schema") != "v4.pdf_research_v3.runtime_binding_evidence.v1"
        or evidence.get("stage") != "OFFLINE_IMPLEMENTATION_ONLY"
        or evidence.get("runtime_binding_status") != "MATCH"
        or evidence.get("runtime_settings_sha256") != PREVIOUSLY_REVIEWED_RUNTIME_SETTINGS_SHA256
        or evidence.get("model_settings_sha256") != PREVIOUSLY_REVIEWED_MODEL_SETTINGS_SHA256
        or evidence.get("runtime_settings_comparison") != "MATCH_PREVIOUS_HASH_ONLY"
        or evidence.get("model_settings_comparison") != "MATCH_PREVIOUS_HASH_ONLY"
        or evidence.get("model_id") != local_model.MODEL_ID
        or evidence.get("request_profile") != local_model.PROFILE_NAME
    ):
        raise SampleCliError("ACCEPTED_RUNTIME_EVIDENCE_INVALID")
    return evidence, evidence_sha


def _expected_runtime_identity(
    evidence: Mapping[str, Any],
    source_review: Mapping[str, Any],
    *,
    scope_configuration_sha256: str,
) -> dict[str, Any]:
    """Project frozen runtime evidence and the ROOT-frozen reviewed configuration digest."""
    if not isinstance(scope_configuration_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", scope_configuration_sha256):
        raise SampleCliError("EXECUTION_SCOPE_CONFIGURATION_HASH_INVALID")
    local_paths = (
        "infrastructure/local_document_model.py",
        "infrastructure/pdf_research.py",
        "ops/run_pdf_research_sample.py",
    )
    reviewed_files = source_review.get("reviewed_files")
    evidence_sources = evidence.get("source_sha256")
    if not isinstance(reviewed_files, Mapping) or not isinstance(evidence_sources, Mapping):
        raise SampleCliError("ACCEPTED_RUNTIME_SOURCE_IDENTITY_INVALID")

    pinned_helpers = {
        **local_model.PINNED_SOURCE_SHA256,
        "v4/manager_workbench/inputs/pdf_pages.py": "ec1d4990277868e42d6d3a7ff93972e80a89e44dcfaa7c9d9f656c32ae07a770",
    }
    if any(evidence_sources.get(name) != sha for name, sha in pinned_helpers.items()):
        raise SampleCliError("ACCEPTED_RUNTIME_HELPER_HASH_MISMATCH")
    expected_sources = dict(pinned_helpers)
    for name in local_paths:
        sha = reviewed_files.get(name)
        if not isinstance(sha, str) or len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise SampleCliError("SOURCE_REVIEW_LOCAL_HASH_INVALID")
        expected_sources[name] = sha
    if set(evidence_sources) != set(expected_sources):
        raise SampleCliError("ACCEPTED_RUNTIME_SOURCE_SET_MISMATCH")

    runtime_python = evidence.get("runtime_python")
    required_runtime_python = evidence.get("required_runtime_python")
    if (
        not isinstance(runtime_python, str)
        or not isinstance(required_runtime_python, str)
        or Path(required_runtime_python).resolve() != local_model.RUNTIME_PYTHON.resolve()
    ):
        raise SampleCliError("ACCEPTED_RUNTIME_INTERPRETER_MISMATCH")
    schema_sha = local_model.sha256_bytes(local_model.canonical_json(pdf_research.V3_OUTPUT_SCHEMA))
    wrapper_sha = local_model.sha256_bytes(
        local_model.canonical_json({"json": pdf_research.V3_OUTPUT_SCHEMA})
    )
    identity = {
        "model_id": evidence.get("model_id"),
        "workflow_profile": evidence.get("request_profile"),
        "tools": [],
        "request_temperature": local_model.REQUEST_TEMPERATURE,
        "enable_thinking": local_model.ENABLE_THINKING,
        "request_schema_sha256": schema_sha,
        "request_schema_wrapper_sha256": wrapper_sha,
        "runtime_settings_path": evidence.get("runtime_settings_path"),
        "runtime_settings_sha256": evidence.get("runtime_settings_sha256"),
        "model_settings_path": evidence.get("model_settings_path"),
        "model_settings_sha256": evidence.get("model_settings_sha256"),
        "runtime_limits_sha256": evidence.get("runtime_limits_sha256"),
        "max_completion_tokens": local_model.MAX_COMPLETION_TOKENS,
        "request_policy_sha256": evidence.get("request_policy_sha256"),
        "configuration_sha256": scope_configuration_sha256,
        "runtime_python": runtime_python,
        "source_sha256": expected_sources,
        "active_server_memory_settings": evidence.get("active_server_memory_settings"),
        "evidence_root": str(local_model.PDF_EVIDENCE_ROOT),
    }
    required_hashes = (
        "runtime_settings_sha256",
        "model_settings_sha256",
        "runtime_limits_sha256",
        "request_policy_sha256",
        "configuration_sha256",
    )
    if any(
        not isinstance(identity.get(name), str)
        or len(identity[name]) != 64
        or any(char not in "0123456789abcdef" for char in identity[name])
        for name in required_hashes
    ):
        raise SampleCliError("ACCEPTED_RUNTIME_HASH_MISSING")
    return identity


def _observed_runtime_identity(binding: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return {
            "model_id": binding.get("model_id"),
            "workflow_profile": binding.get("workflow_profile"),
            "tools": binding.get("tools"),
            "request_temperature": binding.get("request_temperature"),
            "enable_thinking": binding.get("enable_thinking"),
            "request_schema_sha256": binding.get("request_schema_sha256"),
            "request_schema_wrapper_sha256": binding.get("request_schema_wrapper_sha256"),
            "runtime_settings_path": binding.get("runtime_settings_path"),
            "runtime_settings_sha256": binding.get("runtime_settings_sha256"),
            "model_settings_path": binding.get("model_settings_path"),
            "model_settings_sha256": binding.get("model_settings_sha256"),
            "runtime_limits_sha256": local_model.sha256_bytes(
                local_model.canonical_json(binding["runtime_limits"])
            ),
            "max_completion_tokens": binding.get("max_completion_tokens"),
            "request_policy_sha256": local_model.sha256_bytes(
                local_model.canonical_json(binding["request_policy"])
            ),
            "configuration_sha256": binding.get("configuration_sha256"),
            "runtime_python": binding.get("runtime_python"),
            "source_sha256": binding.get("source_sha256"),
            "active_server_memory_settings": binding.get("active_server_memory_settings"),
            "evidence_root": binding.get("evidence_root"),
        }
    except (KeyError, TypeError, ValueError):
        raise SampleCliError("CURRENT_RUNTIME_BINDING_INVALID") from None


def _validate_execution_scope_receipt(
    *,
    scope_sha: str,
    manifest_sha: str,
    documents: list[dict[str, Any]],
    source_review: Mapping[str, Any],
    runtime_evidence: Mapping[str, Any],
    runtime_evidence_sha: str,
) -> tuple[dict[str, Any], dict[str, Any], list[int], dict[int, dict[str, Any]]]:
    if [document.get("document_id") for document in documents] != ["S01"]:
        raise SampleCliError("EXECUTION_SCOPE_CANARY_SET_MISMATCH")
    try:
        receipt = _read_review_receipt(
            EXECUTION_SCOPE_RECEIPT_PATH,
            EXECUTION_SCOPE_SCHEMA,
            expected_status="FROZEN",
        )
    except SampleCliError as exc:
        if exc.code == "REVIEW_RECEIPT_REQUIRED":
            raise SampleCliError("EXECUTION_SCOPE_REQUIRED") from None
        raise
    source_review_sha = _sha256_file(SOURCE_REVIEW_RECEIPT_PATH)
    if receipt.get("authorized_by") != EXECUTION_SCOPE_AUTHORIZER:
        raise SampleCliError("EXECUTION_SCOPE_MISMATCH")
    scoped_identity = receipt.get("expected_runtime_identity")
    if not isinstance(scoped_identity, Mapping):
        raise SampleCliError("EXECUTION_SCOPE_MISMATCH")
    expected_identity = _expected_runtime_identity(
        runtime_evidence,
        source_review,
        scope_configuration_sha256=scoped_identity.get("configuration_sha256"),
    )
    selected_chunk_indices = receipt.get("selected_chunk_indices")
    reusable_chunk_indices = receipt.get("reusable_chunk_indices")
    first_chunk_acceptance_sha256 = receipt.get("first_chunk_acceptance_receipt_sha256")
    accepted_prior_chunks: dict[int, dict[str, Any]] = {}
    if not isinstance(selected_chunk_indices, list) or any(type(index) is not int for index in selected_chunk_indices):
        raise SampleCliError("EXECUTION_SCOPE_CHUNK_SELECTION_INVALID")
    if selected_chunk_indices == [1]:
        if not isinstance(reusable_chunk_indices, list) or reusable_chunk_indices != [] or first_chunk_acceptance_sha256 is not None:
            raise SampleCliError("EXECUTION_SCOPE_CHUNK_SELECTION_INVALID")
    elif (
        not selected_chunk_indices
        or any(type(index) is not int or index < 2 or index > CANARY_MAX_MODEL_CALLS for index in selected_chunk_indices)
        or selected_chunk_indices != list(range(2, selected_chunk_indices[-1] + 1))
        or not isinstance(reusable_chunk_indices, list)
        or any(type(index) is not int for index in reusable_chunk_indices)
        or reusable_chunk_indices != [1]
        or not isinstance(first_chunk_acceptance_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", first_chunk_acceptance_sha256)
    ):
        raise SampleCliError("EXECUTION_SCOPE_CHUNK_SELECTION_INVALID")
    else:
        if FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH.is_symlink() or not FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH.is_file():
            raise SampleCliError("FIRST_CHUNK_ACCEPTANCE_RECEIPT_REQUIRED")
        if _sha256_file(FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH) != first_chunk_acceptance_sha256:
            raise SampleCliError("FIRST_CHUNK_ACCEPTANCE_RECEIPT_SHA_MISMATCH")
        accepted = _read_review_receipt(
            FIRST_CHUNK_ACCEPTANCE_RECEIPT_PATH,
            "v4.pdf_research_v3.chunk_acceptance.v1",
        )
        accepted_schema_sha256 = local_model.sha256_bytes(
            local_model.canonical_json(pdf_research.V3_OUTPUT_SCHEMA)
        )
        accepted_chunk_id = accepted.get("chunk_id")
        accepted_chunk_sha256 = accepted.get("chunk_sha256")
        expected_acceptance = {
            "reviewer": accepted.get("reviewer"),
            "sample_id": "S01",
            "sample_manifest_sha256": manifest_sha,
            "scope_sha256": scope_sha,
            "source_review_receipt_sha256": source_review_sha,
            "runtime_binding_evidence_sha256": runtime_evidence_sha,
            "chunk_index": 1,
            "request_schema_sha256": accepted_schema_sha256,
            "source_sha256": documents[0]["pdf_sha256"],
        }
        hash_fields = ("idempotency_key", "payload_sha256", "raw_sha256", "validated_sha256")
        if (
            not isinstance(accepted.get("reviewer"), str)
            or accepted.get("reviewer") in {"", "/root/pdf_v3_sample_writer"}
            or type(accepted.get("chunk_index")) is not int
            or any(accepted.get(name) != value for name, value in expected_acceptance.items())
            or not isinstance(accepted_chunk_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", accepted_chunk_sha256)
            or accepted_chunk_id != f"S01:0001:{accepted_chunk_sha256}"
            or any(not isinstance(accepted.get(name), str) or not re.fullmatch(r"[0-9a-f]{64}", accepted[name]) for name in hash_fields)
        ):
            raise SampleCliError("FIRST_CHUNK_ACCEPTANCE_RECEIPT_MISMATCH")
        accepted_prior_chunks[1] = {
            name: accepted[name]
            for name in (
                "idempotency_key",
                "payload_sha256",
                "raw_sha256",
                "validated_sha256",
                "chunk_id",
                "chunk_index",
                "chunk_sha256",
                "request_schema_sha256",
                "source_sha256",
            )
        }
    expected = {
        "authorized_by": EXECUTION_SCOPE_AUTHORIZER,
        "execution_phase": "V3_CANARY_EXECUTION",
        "source_scope_phase": "V3_IMPLEMENTATION_OFFLINE_FIRST",
        "request_phase": "CANARY",
        "scope_sha256": scope_sha,
        "sample_manifest_path": str(SAMPLE_MANIFEST_PATH),
        "sample_manifest_sha256": manifest_sha,
        "selected_document_ids": ["S01"],
        "selected_chunk_indices": selected_chunk_indices,
        "reusable_chunk_indices": reusable_chunk_indices,
        "first_chunk_acceptance_receipt_sha256": first_chunk_acceptance_sha256,
        "source_review_receipt_sha256": source_review_sha,
        "runtime_binding_evidence_path": str(RUNTIME_BINDING_EVIDENCE_PATH),
        "runtime_binding_evidence_sha256": runtime_evidence_sha,
        "expected_runtime_identity": expected_identity,
        "request_budget": {
            "maximum_model_calls": CANARY_MAX_MODEL_CALLS,
            "max_attempts_per_chunk": 1,
            "max_source_characters_per_chunk": pdf_research.MAX_SOURCE_CHARACTERS_PER_CHUNK,
            "max_serialized_request_envelope_bytes": pdf_research.MAX_SERIALIZED_REQUEST_ENVELOPE_BYTES,
            "automatic_resume": False,
        },
        "write_allowlist": pdf_research.expected_write_allowlist(),
        "shared_model_lock_path": str(pdf_research.GLOBAL_MODEL_LOCK_PATH),
        "independent_queue_root": str(pdf_research.PDF_RESEARCH_STATE_ROOT / "queue"),
        "ocr_allowed": False,
        "download_allowed": False,
        "pdf_lookup_allowed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(receipt.get(name) != value for name, value in expected.items()):
        raise SampleCliError("EXECUTION_SCOPE_MISMATCH")
    return receipt, expected_identity, selected_chunk_indices, accepted_prior_chunks


def _verify_frozen_runtime_binding(
    binding: Mapping[str, Any], expected_identity: Mapping[str, Any]
) -> None:
    if _observed_runtime_identity(binding) != dict(expected_identity):
        raise SampleCliError("FROZEN_RUNTIME_BINDING_MISMATCH")


def build_execution_plan(phase: str, *, execute: bool) -> dict[str, Any]:
    scope, scope_sha, manifest_sha, documents = load_frozen_documents(phase)
    if phase == "SAMPLE":
        canary_review = _validate_canary_receipt(manifest_sha)
        _validate_sample_acceptance(manifest_sha, canary_review)
    if phase == "CANARY" and (len(documents) != 1 or documents[0]["document_id"] != "S01"):
        raise SampleCliError("CANARY_SELECTION_NOT_S01")
    return {
        "schema": "v4.pdf_research_v3.execution_plan.v1",
        "status": "EXECUTION_READY_PENDING_SOURCE_REVIEW" if execute else "PLAN_ONLY",
        "phase": phase,
        "scope_sha256": scope_sha,
        "sample_manifest_path": str(SAMPLE_MANIFEST_PATH),
        "sample_manifest_sha256": manifest_sha,
        "selected_document_ids": [document["document_id"] for document in documents],
        "selected_chunk_indices": [1] if phase == "CANARY" else None,
        "selected_document_count": len(documents),
        "maximum_document_count": pdf_research.SAMPLE_MAX_DOCUMENTS,
        "source_manifest_fallthrough": False,
        "selection_notes_or_tags_in_model_input": False,
        "ocr_invocations_allowed": False,
        "download_allowed": False,
        "pdf_lookup_allowed": False,
        "model_request_enabled": bool(execute),
        "required_runtime_python": str(local_model.RUNTIME_PYTHON),
        "shared_model_id": local_model.MODEL_ID,
        "shared_model_lock_path": str(pdf_research.GLOBAL_MODEL_LOCK_PATH),
        "independent_queue_root": str(pdf_research.PDF_RESEARCH_STATE_ROOT / "queue"),
        "write_allowlist": pdf_research.expected_write_allowlist(),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def capture_runtime_binding() -> dict[str, Any]:
    """Keep the accepted runtime binding immutable; drift requires a new parent scope."""
    raise SampleCliError("RUNTIME_BINDING_CAPTURE_DISABLED_AFTER_FREEZE")


def execute_sample(phase: str) -> list[dict[str, Any]]:
    if phase != "CANARY":
        raise SampleCliError("EXECUTION_SCOPE_PHASE_UNSUPPORTED")
    scope, scope_sha, manifest_sha, documents = load_frozen_documents(phase)
    source_review = validate_source_review_receipt()
    if EXECUTION_SCOPE_RECEIPT_PATH.is_symlink() or not EXECUTION_SCOPE_RECEIPT_PATH.is_file():
        raise SampleCliError("EXECUTION_SCOPE_REQUIRED")
    runtime_evidence, runtime_evidence_sha = _read_accepted_runtime_binding_evidence()
    execution_scope, expected_identity, selected_chunk_indices, accepted_prior_chunks = _validate_execution_scope_receipt(
        scope_sha=scope_sha,
        manifest_sha=manifest_sha,
        documents=documents,
        source_review=source_review,
        runtime_evidence=runtime_evidence,
        runtime_evidence_sha=runtime_evidence_sha,
    )
    local_model.require_runtime_python()
    binding = local_model.build_request_material(pdf_research.V3_OUTPUT_SCHEMA)
    _verify_frozen_runtime_binding(binding, expected_identity)
    api_identity = local_model.inspect_local_api_identity()
    if api_identity.get("status") != "MATCH":
        raise SampleCliError("LOCAL_MODEL_API_IDENTITY_NOT_MATCH")

    def verify_runtime_binding() -> None:
        local_model.require_runtime_python()
        observed = local_model.build_request_material(pdf_research.V3_OUTPUT_SCHEMA)
        try:
            local_model.verify_request_material(binding, observed)
        except local_model.LocalModelError:
            raise SampleCliError("FROZEN_RUNTIME_BINDING_MISMATCH") from None
        _verify_frozen_runtime_binding(observed, expected_identity)

    source_manifest_projection = {
        "schema": "v4.pdf_research_v3.source_manifest.v1",
        "scope_sha256": scope_sha,
        "sample_manifest_sha256": manifest_sha,
        "phase": phase,
        "documents": documents,
        "source_reviewed_files": source_review["reviewed_files"],
        "execution_scope_receipt_sha256": _sha256_file(EXECUTION_SCOPE_RECEIPT_PATH),
        "execution_scope_phase": execution_scope["execution_phase"],
        "selected_chunk_indices": selected_chunk_indices,
        "reusable_chunk_indices": execution_scope["reusable_chunk_indices"],
        "first_chunk_acceptance_receipt_sha256": execution_scope["first_chunk_acceptance_receipt_sha256"],
        "source_review_receipt_sha256": _sha256_file(SOURCE_REVIEW_RECEIPT_PATH),
    }
    source_manifest_path = pdf_research.PDF_RESEARCH_STATE_ROOT / "source-manifests" / f"{manifest_sha}.json"
    verify_runtime_binding()
    pdf_research._atomic_private_json(source_manifest_path, source_manifest_projection, pdf_research.PDF_RESEARCH_STATE_ROOT)
    verify_runtime_binding()
    queue = pdf_research.create_pdf_queue()
    results: list[dict[str, Any]] = []
    for document in documents:
        result = pdf_research.analyze_document(
            document,
            queue=queue,
            binding=binding,
            selected_chunk_indices=selected_chunk_indices,
            accepted_prior_chunks=accepted_prior_chunks,
            maximum_model_calls=CANARY_MAX_MODEL_CALLS,
            binding_guard=verify_runtime_binding,
        )
        result["sample_manifest_sha256"] = manifest_sha
        result["source_review_status"] = "PASS"
        result["source_review_receipt_sha256"] = _sha256_file(SOURCE_REVIEW_RECEIPT_PATH)
        pdf_research.persist_document_result(result, manifest_sha)
        results.append(result)
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("CANARY", "SAMPLE"))
    parser.add_argument("--execute", action="store_true", help="Run the bounded local-model phase after review gates pass")
    parser.add_argument("--capture-runtime-binding", action="store_true", help="Disabled after the accepted runtime binding is frozen")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.execute and args.capture_runtime_binding:
        raise SystemExit("EXECUTE_AND_CAPTURE_ARE_MUTUALLY_EXCLUSIVE")
    try:
        if args.capture_runtime_binding:
            value = capture_runtime_binding()
        elif args.execute:
            value = {"schema": "v4.pdf_research_v3.run_output.v1", "results": execute_sample(args.phase)}
        else:
            value = build_execution_plan(args.phase, execute=False)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (SampleCliError, pdf_research.PdfResearchError, local_model.LocalModelError) as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        print(json.dumps({"status": "CANNOT_CONFIRM", "error_code": code}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
