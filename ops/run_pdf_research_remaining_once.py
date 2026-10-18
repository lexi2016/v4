#!/usr/bin/env python3
"""Finite, receipt-gated continuation for the frozen R3 PDF cohort.

This module prepares or executes one immutable singleton plan at a time through
the existing PDF batch runner. Execution requires a separate root-issued
authorization that binds the completed pilot, resource/sentinel evidence,
independent review, and candidate adoption.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Mapping, Sequence

from ops import run_pdf_research_batch as batch


PROJECT_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
R_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_QWEN_MAC_MEMORY_20261019_R1")
CONTINUATION_ROOT = R_ROOT / "continuation"
EVIDENCE_ROOT = CONTINUATION_ROOT / "resume-writer"
SCOPE_PATH = CONTINUATION_ROOT / "ROOT_REMAINING_ONCE_SCOPE.json"
AUTHORIZATION_PATH = CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION.json"
PILOT_PLAN_PATH = CONTINUATION_ROOT / "pilot-continuation-r2.json"
PILOT_SELECTION_PATH = CONTINUATION_ROOT / "pilot-selection-r2.json"
ORIGINAL_PROGRESS_SHA256 = "67a658ecc731cd01413523bb9a8cff3393a21e317f4cdfb00f011e055b4fdb84"
EXPECTED_MANIFEST_SHA256 = "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9"
EXPECTED_RUNNER_SHA256 = "53b94d869d380ac33d2f5a51ab278aa502c2be610b40241e09503c45b5f29007"
EXPECTED_SCOPE_SHA256 = "50eecbf8b9c26c5cb30fdea0e379f08a24d3da80b5b8b83f1cdcc4a9bd1f077f"
EXPECTED_PILOT_PLAN_SHA256 = "d9c8a6ce47b5e0fd723f40f91b4aa0d11fe8c5f4e9c4195ef0e066b8c0a56c87"
EXPECTED_PILOT_SELECTION_FILE_SHA256 = "6428b8e14520e70b4cb578b4b9642c38d1a868056ce4229e605d1046b167abac"
EXPECTED_PILOT_SELECTION_SHA256 = "086f60a515eb0ca75294e7734ac14dc3ccfa58add84e3e3a863206748480a4b3"
PILOT_SENTINEL_DOCUMENT_IDS = (
    "164aa74b82025d8fdbdcfff70c8eae9c5e6c4900f270859a6b2020c294733039",
    "2a3972cc4d2103ecb87fc2ddfdb01f34172460fb3efd502706f5c5ae565aeab9",
)
EXPECTED_RUNTIME_PYTHON = Path(
    "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python"
)
EXPECTED_RUNTIME_VERSION = "3.12.13"
SCOPE_SCHEMA = "v4.pdf_remaining_once.scope.v1"
AUTHORIZATION_SCHEMA = "v4.pdf_remaining_once.execution_authorization.v1"
JOURNAL_SCHEMA = "v4.pdf_remaining_once.dispatch_journal.v1"
PLAN_SCHEMA = batch.CONTINUATION_PLAN_SCHEMA
EXPECTED_POST_PILOT_COHORT = 2056
PILOT_DOCUMENT_COUNT = 10
QUARANTINE_POSITION_1_BASED = 143
QUARANTINE_DOCUMENT_ID = "23dd2b2a5a3b5a9107e389f27b1b73bf6e6ba6a61e63afa9a35f0b73246809a9"
MIN_AVAILABLE_BYTES = 8_589_934_592
MAX_SWAP_GROWTH_BYTES = 536_870_912
RESOURCE_SAMPLE_INTERVAL_SECONDS = 1.0
SUCCESS_STATUSES = frozenset(
    {
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
    }
)
SOURCE_ONLY_STATUSES = frozenset(
    {
        "TEXT_UNAVAILABLE",
        "SOURCE_INVALID",
        "SOURCE_REPAIR_FAILED_NO_MODEL",
        "PARTIAL_SOURCE_NO_MODEL_REQUEST",
    }
)
SAFE_JSONL_EVENT_TYPES = frozenset(
    {"binding", "plan_created", "plan_only_pass", "dispatch_intent", "reconciled", "halt"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DispatcherError(RuntimeError):
    """Fail-closed error with a stable machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"


def _read_regular(path: Path, code: str) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise DispatcherError(code)
        return path.read_bytes()
    except OSError:
        raise DispatcherError(code) from None


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _assert_runtime(executable: str | Path | None = None, version: str | None = None) -> None:
    executable = Path(executable or sys.executable)
    version = version or ".".join(str(part) for part in sys.version_info[:3])
    try:
        observed_executable = executable.resolve(strict=True)
        expected_executable = EXPECTED_RUNTIME_PYTHON.resolve(strict=True)
    except OSError:
        raise DispatcherError("NATIVE_PYTHON_312_UNAVAILABLE") from None
    if observed_executable != expected_executable or version != EXPECTED_RUNTIME_VERSION:
        raise DispatcherError("NATIVE_PYTHON_312_REQUIRED")


def _verify_static_bindings() -> dict[str, Any]:
    scope_raw = _read_regular(SCOPE_PATH, "FROZEN_SCOPE_UNAVAILABLE")
    if sha256_bytes(scope_raw) != EXPECTED_SCOPE_SHA256:
        raise DispatcherError("FROZEN_SCOPE_SHA_MISMATCH")
    try:
        scope = json.loads(scope_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("FROZEN_SCOPE_INVALID") from None
    if not isinstance(scope, dict) or scope.get("schema") != SCOPE_SCHEMA:
        raise DispatcherError("FROZEN_SCOPE_INVALID")
    # ALLOWED_PATHS governs this writer checkout. The root may integrate these
    # exact reviewed bytes into the canonical checkout, so runtime identity is
    # enforced by the authorization's dispatcher SHA rather than checkout path.
    runner_path = PROJECT_ROOT / "ops/run_pdf_research_batch.py"
    runner_raw = _read_regular(runner_path, "CANONICAL_RUNNER_UNAVAILABLE")
    if sha256_bytes(runner_raw) != EXPECTED_RUNNER_SHA256:
        raise DispatcherError("CANONICAL_RUNNER_SHA_MISMATCH")
    if batch.EXPECTED_BATCH_MANIFEST_SHA256 != EXPECTED_MANIFEST_SHA256:
        raise DispatcherError("RUNNER_MANIFEST_BINDING_MISMATCH")
    return {"scope_sha256": EXPECTED_SCOPE_SHA256, "runner_sha256": EXPECTED_RUNNER_SHA256}


def _safe_reference(path_value: Any, *, root: Path) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise DispatcherError("AUTHORIZATION_EVIDENCE_PATH_INVALID")
    path = Path(path_value).expanduser().absolute()
    root = root.expanduser().resolve(strict=True)
    try:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, ValueError):
        raise DispatcherError("AUTHORIZATION_EVIDENCE_PATH_OUTSIDE_ROOT") from None
    if path.is_symlink() or not path.is_file():
        raise DispatcherError("AUTHORIZATION_EVIDENCE_UNAVAILABLE")
    return path


def _verified_json_evidence(ref: Any, *, expected_statuses: set[str], code: str) -> dict[str, Any]:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise DispatcherError(code)
    path = _safe_reference(ref["path"], root=CONTINUATION_ROOT)
    raw = _read_regular(path, code)
    if not isinstance(ref["sha256"], str) or sha256_bytes(raw) != ref["sha256"]:
        raise DispatcherError(code)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError(code) from None
    if not isinstance(value, dict) or value.get("status") not in expected_statuses:
        raise DispatcherError(code)
    return value


def _validate_pilot_receipts(auth: Mapping[str, Any], pilot_plan: Mapping[str, Any]) -> tuple[set[str], str]:
    pilot = auth.get("pilot")
    required = {
        "plan_sha256",
        "selection_file_sha256",
        "selection_sha256",
        "progress",
        "receipts",
    }
    if not isinstance(pilot, dict) or set(pilot) != required:
        raise DispatcherError("PILOT_AUTHORIZATION_BINDING_INVALID")
    if (
        pilot.get("plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
        or pilot.get("selection_file_sha256") != EXPECTED_PILOT_SELECTION_FILE_SHA256
        or pilot.get("selection_sha256") != EXPECTED_PILOT_SELECTION_SHA256
    ):
        raise DispatcherError("PILOT_AUTHORIZATION_BINDING_MISMATCH")
    selected = pilot_plan.get("selected_documents")
    if not isinstance(selected, list) or len(selected) != PILOT_DOCUMENT_COUNT:
        raise DispatcherError("PILOT_SELECTION_INVALID")
    expected_ids = [row.get("document_id") for row in selected if isinstance(row, dict)]
    if len(expected_ids) != PILOT_DOCUMENT_COUNT or len(set(expected_ids)) != PILOT_DOCUMENT_COUNT:
        raise DispatcherError("PILOT_SELECTION_INVALID")

    progress_ref = pilot.get("progress")
    if not isinstance(progress_ref, dict) or set(progress_ref) != {"path", "sha256"}:
        raise DispatcherError("PILOT_PROGRESS_BINDING_INVALID")
    pilot_state_raw = Path(str(pilot_plan.get("state_root", ""))).expanduser().absolute()
    expected_pilot_state_root = batch.DEFAULT_STATE_ROOT.parent / f"continuation-{pilot_plan.get('continuation_id')}"
    if pilot_state_raw != expected_pilot_state_root.expanduser().absolute() or pilot_state_raw.is_symlink():
        raise DispatcherError("PILOT_STATE_ROOT_BINDING_MISMATCH")
    expected_pilot_progress = pilot_state_raw / "run-progress.json"
    if Path(str(progress_ref.get("path", ""))).expanduser().absolute() != expected_pilot_progress.expanduser().absolute():
        raise DispatcherError("PILOT_PROGRESS_PATH_MISMATCH")
    try:
        progress_root = pilot_state_raw.resolve(strict=True)
    except (KeyError, OSError):
        raise DispatcherError("PILOT_STATE_ROOT_UNAVAILABLE") from None
    if progress_root.is_symlink() or not progress_root.is_dir():
        raise DispatcherError("PILOT_STATE_ROOT_UNSAFE")
    progress_path = _safe_reference(progress_ref["path"], root=progress_root)
    progress_raw = _read_regular(progress_path, "PILOT_PROGRESS_UNAVAILABLE")
    if not isinstance(progress_ref.get("sha256"), str) or sha256_bytes(progress_raw) != progress_ref["sha256"]:
        raise DispatcherError("PILOT_PROGRESS_SHA_MISMATCH")
    try:
        progress = json.loads(progress_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("PILOT_PROGRESS_INVALID") from None
    if not isinstance(progress, dict) or progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES":
        raise DispatcherError("PILOT_NOT_COMPLETED")
    if progress.get("continuation_id") != pilot_plan.get("continuation_id"):
        raise DispatcherError("PILOT_PROGRESS_IDENTITY_MISMATCH")
    if (
        progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or progress.get("continuation_plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
        or progress.get("model_settings_sha256") != auth.get("model_settings_sha256")
    ):
        raise DispatcherError("PILOT_PROGRESS_BINDING_MISMATCH")
    pilot_rows = progress.get("documents")
    if not isinstance(pilot_rows, list) or len(pilot_rows) != PILOT_DOCUMENT_COUNT:
        raise DispatcherError("PILOT_PROGRESS_DOCUMENTS_INVALID")
    progress_by_id = {row.get("document_id"): row for row in pilot_rows if isinstance(row, dict)}
    if set(progress_by_id) != set(expected_ids):
        raise DispatcherError("PILOT_PROGRESS_SELECTION_MISMATCH")

    refs = pilot.get("receipts")
    if not isinstance(refs, list) or len(refs) != PILOT_DOCUMENT_COUNT:
        raise DispatcherError("PILOT_RECEIPTS_INCOMPLETE")
    receipt_ids: set[str] = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"document_id", "path", "sha256"}:
            raise DispatcherError("PILOT_RECEIPT_REFERENCE_INVALID")
        document_id = ref.get("document_id")
        if document_id not in expected_ids or document_id in receipt_ids:
            raise DispatcherError("PILOT_RECEIPT_SELECTION_MISMATCH")
        expected_receipt_path = progress_root / "documents" / document_id / "receipt.json"
        if Path(str(ref.get("path", ""))).expanduser().absolute() != expected_receipt_path:
            raise DispatcherError("PILOT_RECEIPT_PATH_MISMATCH")
        path = _safe_reference(ref.get("path"), root=progress_root)
        raw = _read_regular(path, "PILOT_RECEIPT_UNAVAILABLE")
        if not isinstance(ref.get("sha256"), str) or sha256_bytes(raw) != ref["sha256"]:
            raise DispatcherError("PILOT_RECEIPT_SHA_MISMATCH")
        try:
            receipt = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise DispatcherError("PILOT_RECEIPT_INVALID") from None
        if (
            not isinstance(receipt, dict)
            or receipt.get("document_id") != document_id
            or receipt.get("pdf_sha256") != document_id
            or receipt.get("status") not in SUCCESS_STATUSES
            or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
            or receipt.get("research_only") is not True
            or receipt.get("production_allowed") is not False
            or receipt.get("buy_gate_updated") is not False
            or receipt.get("orders_sent") is not False
        ):
            raise DispatcherError("PILOT_RECEIPT_NOT_SUCCESSFUL")
        continuation = receipt.get("continuation")
        if (
            not isinstance(continuation, dict)
            or continuation.get("continuation_id") != pilot_plan.get("continuation_id")
            or continuation.get("plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
            or continuation.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
            or continuation.get("model_settings_sha256") != auth.get("model_settings_sha256")
        ):
            raise DispatcherError("PILOT_RECEIPT_BINDING_MISMATCH")
        row = progress_by_id[document_id]
        if (
            row.get("status") != receipt["status"]
            or row.get("continuation_id") != pilot_plan.get("continuation_id")
            or row.get("continuation_plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
            or row.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
            or row.get("model_settings_sha256") != auth.get("model_settings_sha256")
        ):
            raise DispatcherError("PILOT_PROGRESS_RECEIPT_MISMATCH")
        receipt_ids.add(document_id)
    return receipt_ids, str(pilot["progress"]["sha256"])


def load_and_validate_authorization(path: Path = AUTHORIZATION_PATH) -> dict[str, Any]:
    if path.expanduser().absolute() != AUTHORIZATION_PATH.expanduser().absolute():
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_PATH_MISMATCH")
    raw = _read_regular(path, "ROOT_EXECUTION_AUTHORIZATION_REQUIRED")
    try:
        auth = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_INVALID") from None
    if not isinstance(auth, dict) or auth.get("schema") != AUTHORIZATION_SCHEMA:
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_INVALID")
    expected_fields = {
        "schema",
        "status",
        "authorization_id",
        "scope_sha256",
        "dispatcher_sha256",
        "runner_sha256",
        "manifest_sha256",
        "original_progress_sha256",
        "runtime_python",
        "runtime_version",
        "model_settings_sha256",
        "max_documents",
        "pilot",
        "resource_gate",
        "sentinel_gate",
        "reviewer_receipt",
        "adoption_receipt",
        "research_only",
    }
    if set(auth) != expected_fields or auth.get("status") != "AUTHORIZED":
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_INVALID")
    try:
        auth_path = path.expanduser().absolute()
        auth_root = CONTINUATION_ROOT.resolve(strict=True)
        auth_path.parent.resolve(strict=True).relative_to(auth_root)
    except (OSError, ValueError):
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_OUTSIDE_ROOT") from None
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(auth.get("authorization_id", ""))):
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_ID_INVALID")
    bindings = {
        "scope_sha256": EXPECTED_SCOPE_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "original_progress_sha256": ORIGINAL_PROGRESS_SHA256,
        "runtime_python": str(EXPECTED_RUNTIME_PYTHON),
        "runtime_version": EXPECTED_RUNTIME_VERSION,
    }
    if any(auth.get(key) != value for key, value in bindings.items()):
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_BINDING_MISMATCH")
    if auth.get("dispatcher_sha256") != sha256_bytes(Path(__file__).read_bytes()):
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_DISPATCHER_SHA_MISMATCH")
    max_documents = auth.get("max_documents")
    if type(max_documents) is not int or not 1 <= max_documents <= EXPECTED_POST_PILOT_COHORT:
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_LIMIT_INVALID")
    if auth.get("research_only") != {
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }:
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_SAFETY_INVALID")

    pilot_plan_raw = _read_regular(PILOT_PLAN_PATH, "PILOT_PLAN_UNAVAILABLE")
    if sha256_bytes(pilot_plan_raw) != EXPECTED_PILOT_PLAN_SHA256:
        raise DispatcherError("PILOT_PLAN_SHA_MISMATCH")
    try:
        pilot_plan = json.loads(pilot_plan_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("PILOT_PLAN_INVALID") from None
    if not isinstance(pilot_plan, dict) or pilot_plan.get("schema") != PLAN_SCHEMA:
        raise DispatcherError("PILOT_PLAN_INVALID")
    if auth.get("model_settings_sha256") != pilot_plan.get("observed_model_settings_sha256"):
        raise DispatcherError("ROOT_ADOPTION_MODEL_SETTINGS_MISMATCH")

    selection_raw = _read_regular(PILOT_SELECTION_PATH, "PILOT_SELECTION_UNAVAILABLE")
    if sha256_bytes(selection_raw) != EXPECTED_PILOT_SELECTION_FILE_SHA256:
        raise DispatcherError("PILOT_SELECTION_FILE_SHA_MISMATCH")
    try:
        selection = json.loads(selection_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("PILOT_SELECTION_INVALID") from None
    if not isinstance(selection, dict):
        raise DispatcherError("PILOT_SELECTION_INVALID")
    selection_obj = selection.get("selection")
    if not isinstance(selection_obj, dict) or selection_obj.get("selection_sha256") != EXPECTED_PILOT_SELECTION_SHA256:
        raise DispatcherError("PILOT_SELECTION_BINDING_INVALID")
    selection_ids = [
        row.get("document_id") for row in selection_obj.get("selected_documents", []) if isinstance(row, dict)
    ]
    plan_ids = [row.get("document_id") for row in pilot_plan.get("selected_documents", []) if isinstance(row, dict)]
    if len(selection_ids) != PILOT_DOCUMENT_COUNT or selection_ids != plan_ids:
        raise DispatcherError("PILOT_SELECTION_PLAN_MISMATCH")
    pilot_auth = auth.get("pilot")
    if not isinstance(pilot_auth, dict) or set(pilot_auth) != {
        "plan_sha256",
        "selection_file_sha256",
        "selection_sha256",
        "progress",
        "receipts",
    }:
        raise DispatcherError("PILOT_AUTHORIZATION_BINDING_INVALID")
    if (
        pilot_auth.get("plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
        or pilot_auth.get("selection_file_sha256") != EXPECTED_PILOT_SELECTION_FILE_SHA256
        or pilot_auth.get("selection_sha256") != EXPECTED_PILOT_SELECTION_SHA256
    ):
        raise DispatcherError("PILOT_AUTHORIZATION_BINDING_MISMATCH")
    progress_ref = pilot_auth.get("progress")
    if (
        not isinstance(progress_ref, dict)
        or set(progress_ref) != {"path", "sha256"}
        or not isinstance(progress_ref.get("sha256"), str)
        or not SHA256_RE.fullmatch(progress_ref["sha256"])
    ):
        raise DispatcherError("PILOT_PROGRESS_BINDING_INVALID")
    for key, statuses in (
        ("resource_gate", {"PASS"}),
        ("sentinel_gate", {"PASS"}),
        ("reviewer_receipt", {"PASS", "REVIEWED_PASS"}),
        ("adoption_receipt", {"ADOPTED", "ROOT_ADOPTED"}),
    ):
        evidence = _verified_json_evidence(
            auth[key], expected_statuses=statuses, code=f"{key.upper()}_EVIDENCE_INVALID"
        )
        if key == "resource_gate":
            available = evidence.get("minimum_available_memory_bytes")
            swap_growth = evidence.get("maximum_swap_used_growth_bytes")
            if (
                type(available) is not int
                or available < MIN_AVAILABLE_BYTES
                or type(swap_growth) is not int
                or swap_growth < 0
                or swap_growth > MAX_SWAP_GROWTH_BYTES
                or evidence.get("pilot_successful_receipt_count") != PILOT_DOCUMENT_COUNT
            ):
                raise DispatcherError("RESOURCE_GATE_THRESHOLDS_NOT_MET")
        elif key == "sentinel_gate":
            sentinel_ids = evidence.get("sentinel_document_ids")
            if (
                evidence.get("sentinel_pass") is not True
                or not isinstance(sentinel_ids, list)
                or len(sentinel_ids) != len(PILOT_SENTINEL_DOCUMENT_IDS)
                or not all(isinstance(item, str) for item in sentinel_ids)
                or set(sentinel_ids) != set(PILOT_SENTINEL_DOCUMENT_IDS)
            ):
                raise DispatcherError("SENTINEL_GATE_NOT_PASSED")
        elif key == "reviewer_receipt":
            if (
                evidence.get("scope_sha256") != EXPECTED_SCOPE_SHA256
                or evidence.get("dispatcher_sha256") != auth.get("dispatcher_sha256")
            ):
                raise DispatcherError("REVIEWER_RECEIPT_BINDING_MISMATCH")
        elif key == "adoption_receipt":
            if evidence.get("model_settings_sha256") != auth.get("model_settings_sha256"):
                raise DispatcherError("ROOT_ADOPTION_RECEIPT_BINDING_MISMATCH")
        expected_pilot_progress_sha = progress_ref["sha256"]
        if (
            evidence.get("pilot_plan_sha256") != EXPECTED_PILOT_PLAN_SHA256
            or evidence.get("pilot_selection_sha256") != EXPECTED_PILOT_SELECTION_SHA256
            or evidence.get("pilot_progress_sha256") != expected_pilot_progress_sha
        ):
            raise DispatcherError(f"{key.upper()}_PILOT_BINDING_MISMATCH")
    # Actual pilot receipts are read only after the separately issued auth and
    # all resource, sentinel, independent-review, and adoption gates pass.
    pilot_ids, pilot_progress_sha = _validate_pilot_receipts(auth, pilot_plan)
    return {
        "authorization": auth,
        "authorization_sha256": sha256_bytes(raw),
        "pilot_document_ids": pilot_ids,
        "pilot_progress_sha256": pilot_progress_sha,
        "pilot_plan": pilot_plan,
    }


def _load_original_r3(manifest_path: Path) -> tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest, manifest_sha, documents = batch.load_manifest(manifest_path)
    if manifest_sha != EXPECTED_MANIFEST_SHA256 or len(documents) != 2209:
        raise DispatcherError("FROZEN_MANIFEST_BINDING_MISMATCH")
    progress_path = batch.DEFAULT_STATE_ROOT / "run-progress.json"
    progress_raw = _read_regular(progress_path, "ORIGINAL_R3_PROGRESS_UNAVAILABLE")
    if sha256_bytes(progress_raw) != ORIGINAL_PROGRESS_SHA256:
        raise DispatcherError("ORIGINAL_R3_PROGRESS_SHA_MISMATCH")
    try:
        progress = json.loads(progress_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("ORIGINAL_R3_PROGRESS_INVALID") from None
    if not isinstance(progress, dict) or progress.get("status") != "STOPPED_GRACEFULLY":
        raise DispatcherError("ORIGINAL_R3_PROGRESS_STATUS_INVALID")
    prior_rows = batch._prior_progress_rows(progress)
    if len(prior_rows) != 142:
        raise DispatcherError("ORIGINAL_R3_PROGRESS_ROW_COUNT_INVALID")
    return manifest_sha, documents, prior_rows


def select_next_document(
    documents: Sequence[Mapping[str, Any]],
    original_rows: Mapping[str, Mapping[str, Any]],
    pilot_ids: set[str],
    dispatched_ids: set[str],
) -> tuple[dict[str, Any] | None, int]:
    if len(documents) != 2209 or len(original_rows) != 142 or len(pilot_ids) != PILOT_DOCUMENT_COUNT:
        raise DispatcherError("COHORT_INPUT_COUNTS_INVALID")
    quarantine = str(documents[QUARANTINE_POSITION_1_BASED - 1].get("document_id", ""))
    if quarantine != QUARANTINE_DOCUMENT_ID:
        raise DispatcherError("QUARANTINE_POSITION_BINDING_MISMATCH")
    excluded = set(original_rows) | set(pilot_ids) | set(dispatched_ids) | {quarantine}
    eligible = [row for row in documents if str(row.get("document_id")) not in excluded]
    if not eligible:
        return None, 0
    return dict(eligible[0]), len(eligible)


def build_singleton_plan(
    document: Mapping[str, Any],
    *,
    manifest_sha256: str,
    prior_progress_sha256: str,
    model_settings_sha256: str,
    continuation_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    continuation_id = continuation_id or f"resume-{uuid.uuid4().hex}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", continuation_id):
        raise DispatcherError("CONTINUATION_ID_INVALID")
    document_id = document.get("document_id")
    source_sha = document.get("pdf_sha256")
    if not isinstance(document_id, str) or document_id != source_sha or not SHA256_RE.fullmatch(document_id):
        raise DispatcherError("MANIFEST_DOCUMENT_ID_INVALID")
    if manifest_sha256 != EXPECTED_MANIFEST_SHA256 or prior_progress_sha256 != ORIGINAL_PROGRESS_SHA256:
        raise DispatcherError("PLAN_SOURCE_BINDING_MISMATCH")
    if model_settings_sha256 not in batch.CONTINUATION_ALLOWED_SETTINGS_SHA256S:
        raise DispatcherError("MODEL_SETTINGS_BINDING_UNSUPPORTED")
    state_root = batch.DEFAULT_STATE_ROOT.parent / f"continuation-{continuation_id}"
    plan = {
        "schema": PLAN_SCHEMA,
        "continuation_id": continuation_id,
        "source_run_id": batch.CONTINUATION_SOURCE_RUN_ID,
        "manifest_sha256": manifest_sha256,
        "prior_progress_path": str(batch.DEFAULT_STATE_ROOT / "run-progress.json"),
        "prior_progress_sha256": prior_progress_sha256,
        "prior_progress_status": "STOPPED_GRACEFULLY",
        "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        "expected_model_settings_sha256": model_settings_sha256,
        "observed_model_settings_sha256": model_settings_sha256,
        "state_root": str(state_root),
        "selected_documents": [
            {"document_id": document_id, "prior_status": "UNPROCESSED", "source_sha256": source_sha}
        ],
        "one_time_recovery_limit": 1,
        "excluded_prior_statuses": sorted(batch.CONTINUATION_EXCLUDED_PRIOR_STATUSES),
        "research_only": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    return plan, _json_bytes(plan)


class DurableJournal:
    """Append-only, fsynced local ledger with a single-writer flock."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "dispatch.jsonl"
        self.lock_path = root / "dispatch.lock"
        self._lock_fd: int | None = None
        self.events: list[dict[str, Any]] = []

    def __enter__(self) -> "DurableJournal":
        if self.root.is_symlink():
            raise DispatcherError("DISPATCH_JOURNAL_ROOT_UNSAFE")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise DispatcherError("DISPATCH_JOURNAL_ROOT_UNSAFE")
        if self.lock_path.is_symlink():
            raise DispatcherError("DISPATCH_JOURNAL_LOCK_UNSAFE")
        self._lock_fd = os.open(
            self.lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise DispatcherError("DISPATCH_JOURNAL_BUSY") from None
        self.events = self._read_events()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = _read_regular(self.path, "DISPATCH_JOURNAL_UNREADABLE")
        if raw and not raw.endswith(b"\n"):
            raise DispatcherError("DISPATCH_JOURNAL_TRUNCATED")
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise DispatcherError("DISPATCH_JOURNAL_CORRUPT") from None
            if not isinstance(event, dict) or event.get("event") not in SAFE_JSONL_EVENT_TYPES:
                raise DispatcherError("DISPATCH_JOURNAL_CORRUPT")
            events.append(event)
        if events and events[0].get("event") != "binding":
            raise DispatcherError("DISPATCH_JOURNAL_BINDING_MISSING")
        return events

    def append(self, event: Mapping[str, Any]) -> None:
        if event.get("event") not in SAFE_JSONL_EVENT_TYPES:
            raise DispatcherError("DISPATCH_JOURNAL_EVENT_INVALID")
        if self.path.is_symlink():
            raise DispatcherError("DISPATCH_JOURNAL_UNSAFE")
        record = {"at_utc": datetime.now(timezone.utc).isoformat(), **dict(event)}
        raw = canonical_json(record) + b"\n"
        fd = os.open(
            self.path,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(self.root)
        self.events.append(record)


def _event_binding(context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": "binding",
        "schema": JOURNAL_SCHEMA,
        "authorization_id": context["authorization"]["authorization_id"],
        "authorization_sha256": context["authorization_sha256"],
        "scope_sha256": EXPECTED_SCOPE_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "manifest_sha256": context["manifest_sha256"],
        "original_progress_sha256": ORIGINAL_PROGRESS_SHA256,
        "pilot_progress_sha256": context["pilot_progress_sha256"],
        "model_settings_sha256": context["authorization"]["model_settings_sha256"],
    }


def _verify_or_create_binding(journal: DurableJournal, context: Mapping[str, Any]) -> None:
    binding = _event_binding(context)
    if not journal.events:
        journal.append(binding)
        return
    observed = {key: value for key, value in journal.events[0].items() if key != "at_utc"}
    if observed != binding:
        raise DispatcherError("DISPATCH_JOURNAL_BINDING_MISMATCH")


def _latest_document_events(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events[1:]:
        document_id = event.get("document_id")
        if isinstance(document_id, str):
            latest[document_id] = dict(event)
    return latest


def _halt_if_required(journal: DurableJournal, latest: Mapping[str, Mapping[str, Any]]) -> None:
    for event in journal.events:
        if event.get("event") == "halt":
            raise DispatcherError("DISPATCHER_PREVIOUSLY_HALTED")
    for event in latest.values():
        if event.get("event") == "dispatch_intent":
            raise DispatcherError("DISPATCH_OUTCOME_AMBIGUOUS_FAIL_CLOSED")
        if event.get("event") == "reconciled" and event.get("decision") in {"HALT", "RESUME_REQUIRED"}:
            if event.get("decision") == "HALT":
                raise DispatcherError("DISPATCHER_PREVIOUSLY_HALTED")


def _write_immutable(path: Path, raw: bytes) -> str:
    if path.parent.is_symlink():
        raise DispatcherError("PLAN_PATH_UNSAFE")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise DispatcherError("PLAN_PATH_UNSAFE")
    if path.is_symlink():
        raise DispatcherError("PLAN_PATH_UNSAFE")
    if path.exists():
        if _read_regular(path, "PLAN_PATH_UNSAFE") != raw:
            raise DispatcherError("PLAN_IMMUTABLE_CONFLICT")
        return sha256_bytes(raw)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if _read_regular(path, "PLAN_PATH_UNSAFE") != raw:
            raise DispatcherError("PLAN_IMMUTABLE_CONFLICT") from None
        return sha256_bytes(raw)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return sha256_bytes(raw)


def _load_saved_plan(event: Mapping[str, Any], *, evidence_root: Path) -> tuple[Path, bytes]:
    path = _safe_reference(event.get("plan_path"), root=evidence_root)
    raw = _read_regular(path, "SAVED_PLAN_UNAVAILABLE")
    if sha256_bytes(raw) != event.get("plan_sha256"):
        raise DispatcherError("SAVED_PLAN_SHA_MISMATCH")
    encoded = event.get("plan_bytes_b64")
    if not isinstance(encoded, str):
        raise DispatcherError("SAVED_PLAN_BYTES_MISSING")
    try:
        recorded_raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise DispatcherError("SAVED_PLAN_BYTES_INVALID") from None
    if recorded_raw != raw:
        raise DispatcherError("SAVED_PLAN_BYTES_MISMATCH")
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("SAVED_PLAN_INVALID") from None
    if not isinstance(plan, dict) or len(plan.get("selected_documents", [])) != 1:
        raise DispatcherError("SAVED_PLAN_NOT_SINGLETON")
    selected = plan["selected_documents"][0]
    if (
        plan.get("state_root") != event.get("state_root")
        or plan.get("continuation_id") != event.get("continuation_id")
        or not isinstance(selected, dict)
        or selected.get("document_id") != event.get("document_id")
    ):
        raise DispatcherError("SAVED_PLAN_BINDING_MISMATCH")
    return path, raw


def _make_command(plan_path: Path, *, execute: bool) -> list[str]:
    command = [
        str(EXPECTED_RUNTIME_PYTHON),
        "-m",
        "ops.run_pdf_research_batch",
        "--manifest",
        str(batch.DEFAULT_MANIFEST),
        "--continuation-plan",
        str(plan_path),
    ]
    if execute:
        command.append("--execute")
    return command


def _run_plan_only(
    plan_path: Path,
    *,
    expected_sha256: str | None = None,
    popen: Callable[..., Any] = subprocess.run,
) -> None:
    plan_raw = _read_regular(plan_path, "PLAN_ONLY_INPUT_INVALID")
    plan_sha = sha256_bytes(plan_raw)
    if expected_sha256 is not None and plan_sha != expected_sha256:
        raise DispatcherError("PLAN_CHANGED_BEFORE_PLAN_ONLY")
    try:
        plan = json.loads(plan_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("PLAN_ONLY_INPUT_INVALID") from None
    if not isinstance(plan, dict):
        raise DispatcherError("PLAN_ONLY_INPUT_INVALID")
    result = popen(
        _make_command(plan_path, execute=False),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DispatcherError("RUNNER_PLAN_ONLY_FAILED")
    if _read_regular(plan_path, "PLAN_ONLY_INPUT_INVALID") != plan_raw:
        raise DispatcherError("PLAN_CHANGED_DURING_PLAN_ONLY")
    try:
        output = json.loads(result.stdout.strip().splitlines()[-1])
    except (AttributeError, IndexError, json.JSONDecodeError):
        raise DispatcherError("RUNNER_PLAN_ONLY_OUTPUT_INVALID") from None
    if (
        not isinstance(output, dict)
        or output.get("status") != "PLAN_ONLY"
        or output.get("continuation_id") != plan.get("continuation_id")
        or output.get("selected_document_count") != 1
        or output.get("state_root") != plan.get("state_root")
        or output.get("continuation_plan_sha256") != plan_sha
    ):
        raise DispatcherError("RUNNER_PLAN_ONLY_BINDING_MISMATCH")


def sample_resource_metrics() -> dict[str, int]:
    try:
        import psutil

        return {
            "available_bytes": int(psutil.virtual_memory().available),
            "swap_used_bytes": int(psutil.swap_memory().used),
        }
    except Exception:
        raise DispatcherError("RESOURCE_SAMPLE_CANNOT_CONFIRM") from None


def _persist_sample(path: Path, row: Mapping[str, Any]) -> None:
    if path.parent.is_symlink() or path.is_symlink():
        raise DispatcherError("RESOURCE_SAMPLE_PATH_UNSAFE")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise DispatcherError("RESOURCE_SAMPLE_PATH_UNSAFE")
    record = {"at_utc": datetime.now(timezone.utc).isoformat(), **dict(row)}
    raw = canonical_json(record) + b"\n"
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def _owned_child_create_time(pid: int) -> float:
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        raise DispatcherError("CHILD_OWNERSHIP_CANNOT_CONFIRM") from None


def _signal_owned_child(proc: Any, expected_create_time: float) -> None:
    if proc.poll() is not None:
        return
    try:
        import psutil

        observed = float(psutil.Process(proc.pid).create_time())
    except Exception:
        raise DispatcherError("CHILD_OWNERSHIP_CANNOT_CONFIRM") from None
    if abs(observed - expected_create_time) > 1e-6:
        raise DispatcherError("CHILD_OWNERSHIP_CHANGED")
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)


def _run_execution_child(
    plan_path: Path,
    *,
    expected_plan_sha256: str | None = None,
    baseline_swap_used: int,
    samples_path: Path,
    sampler: Callable[[], Mapping[str, int]] = sample_resource_metrics,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep_fn: Callable[[float], Any] = time.sleep,
    create_time_fn: Callable[[int], float] = _owned_child_create_time,
    signal_fn: Callable[[Any, float], None] = _signal_owned_child,
) -> dict[str, Any]:
    plan_raw = _read_regular(plan_path, "EXECUTION_PLAN_UNAVAILABLE")
    if expected_plan_sha256 is not None and sha256_bytes(plan_raw) != expected_plan_sha256:
        raise DispatcherError("PLAN_CHANGED_BEFORE_EXECUTION")
    try:
        initial = dict(sampler())
    except Exception:
        return {
            "returncode": None,
            "resource_stop_reason": "RESOURCE_SAMPLE_CANNOT_CONFIRM",
            "child_started": False,
            "stdout_sha256": None,
        }
    _persist_sample(samples_path, {"phase": "pre_dispatch", **initial})
    reason = _resource_stop_reason(initial, baseline_swap_used)
    if reason:
        return {"returncode": None, "resource_stop_reason": reason, "child_started": False, "stdout_sha256": None}

    proc = popen(
        _make_command(plan_path, execute=True),
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    expected_create_time: float | None = None
    stop_reason: str | None = None
    try:
        expected_create_time = create_time_fn(proc.pid)
    except Exception:
        stop_reason = "CHILD_OWNERSHIP_CANNOT_CONFIRM"
    while proc.poll() is None:
        sleep_fn(RESOURCE_SAMPLE_INTERVAL_SECONDS)
        try:
            sample = dict(sampler())
            _persist_sample(samples_path, {"phase": "running", **sample})
            detected = _resource_stop_reason(sample, baseline_swap_used)
        except Exception:
            detected = "RESOURCE_SAMPLE_CANNOT_CONFIRM"
        if detected and stop_reason is None:
            stop_reason = detected
            if expected_create_time is not None:
                try:
                    signal_fn(proc, expected_create_time)
                except Exception as exc:
                    stop_reason = getattr(exc, "code", None) or "CHILD_OWNERSHIP_CANNOT_CONFIRM"
        try:
            proc.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
    try:
        returncode = proc.wait(timeout=0)
    except subprocess.TimeoutExpired:
        # The process is polled above; this is defensive and never kills it.
        while proc.poll() is None:
            sleep_fn(RESOURCE_SAMPLE_INTERVAL_SECONDS)
        returncode = proc.wait()
    stdout_stream = getattr(proc, "stdout", None)
    stderr_stream = getattr(proc, "stderr", None)
    stdout = stdout_stream.read() if hasattr(stdout_stream, "read") else ""
    stderr = stderr_stream.read() if hasattr(stderr_stream, "read") else ""
    stdout_raw = stdout if isinstance(stdout, bytes) else str(stdout).encode("utf-8")
    stderr_raw = stderr if isinstance(stderr, bytes) else str(stderr).encode("utf-8")
    return {
        "returncode": returncode,
        "resource_stop_reason": stop_reason,
        "child_started": True,
        "stdout_sha256": sha256_bytes(stdout_raw),
        "stderr_sha256": sha256_bytes(stderr_raw),
    }


def _resource_stop_reason(sample: Mapping[str, Any], baseline_swap_used: int) -> str | None:
    available = sample.get("available_bytes")
    swap_used = sample.get("swap_used_bytes")
    if type(available) is not int or type(swap_used) is not int or available < 0 or swap_used < 0:
        return "RESOURCE_SAMPLE_CANNOT_CONFIRM"
    if available < MIN_AVAILABLE_BYTES:
        return "AVAILABLE_MEMORY_BELOW_8_GIB"
    if swap_used - baseline_swap_used > MAX_SWAP_GROWTH_BYTES:
        return "SWAP_GROWTH_ABOVE_512_MIB"
    return None


def _reconcile_singleton(
    plan: Mapping[str, Any],
    plan_sha256: str,
    *,
    child: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = plan["selected_documents"][0]["document_id"]
    state_root = Path(plan["state_root"])
    progress_path = state_root / "run-progress.json"
    receipt_path = state_root / "documents" / document_id / "receipt.json"
    progress_raw = _read_regular(progress_path, "EXECUTION_PROGRESS_UNAVAILABLE")
    receipt_raw = _read_regular(receipt_path, "EXECUTION_RECEIPT_UNAVAILABLE")
    try:
        progress = json.loads(progress_raw.decode("utf-8"))
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("EXECUTION_RECEIPT_JSON_INVALID") from None
    if not isinstance(progress, dict) or not isinstance(receipt, dict):
        raise DispatcherError("EXECUTION_RECEIPT_JSON_INVALID")
    row_list = progress.get("documents")
    if not isinstance(row_list, list) or len(row_list) != 1 or not isinstance(row_list[0], dict):
        raise DispatcherError("EXECUTION_PROGRESS_SINGLETON_INVALID")
    row = row_list[0]
    continuation = receipt.get("continuation")
    if (
        row.get("document_id") != document_id
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or row.get("status") != receipt.get("status")
        or progress.get("continuation_id") != plan.get("continuation_id")
        or progress.get("continuation_plan_sha256") != plan_sha256
        or progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or progress.get("model_settings_sha256") != plan.get("expected_model_settings_sha256")
        or not isinstance(continuation, dict)
        or continuation.get("continuation_id") != plan.get("continuation_id")
        or continuation.get("plan_sha256") != plan_sha256
        or continuation.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or continuation.get("model_settings_sha256") != plan.get("expected_model_settings_sha256")
    ):
        raise DispatcherError("EXECUTION_RECEIPT_BINDING_MISMATCH")
    if any(
        receipt.get(key) is not expected
        for key, expected in (
            ("research_only", True),
            ("production_allowed", False),
            ("buy_gate_updated", False),
            ("orders_sent", False),
        )
    ):
        raise DispatcherError("EXECUTION_RECEIPT_SAFETY_BINDING_INVALID")
    status = receipt.get("status")
    requests = receipt.get("model_request_count")
    if status in SUCCESS_STATUSES:
        decision = "CONTINUE"
        if type(requests) is not int or requests < 1:
            raise DispatcherError("EXECUTION_MODEL_REQUEST_COUNT_INVALID")
    elif status in SOURCE_ONLY_STATUSES:
        if requests not in (None, 0) or receipt.get("chunks") or receipt.get("synthesis"):
            raise DispatcherError("SOURCE_ONLY_RECEIPT_MODEL_ACTIVITY_UNCLEAR")
        decision = "CONTINUE"
    elif isinstance(status, str) and status.startswith("DEFERRED"):
        decision = "RESUME_REQUIRED"
    else:
        decision = "HALT"
    if child.get("returncode") != 0 or child.get("resource_stop_reason"):
        decision = "HALT"
    progress_status = progress.get("status")
    if progress_status not in {"COMPLETED_WITH_PER_DOCUMENT_STATES", "DEFERRED", "STOPPED_GRACEFULLY"}:
        decision = "HALT"
    elif progress_status == "STOPPED_GRACEFULLY":
        decision = "HALT"
    elif isinstance(status, str) and status.startswith("DEFERRED") and progress_status != "DEFERRED":
        decision = "HALT"
    elif (not isinstance(status, str) or not status.startswith("DEFERRED")) and progress_status == "DEFERRED":
        decision = "HALT"
    return {
        "document_id": document_id,
        "status": status,
        "decision": decision,
        "model_request_count": requests,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_bytes(receipt_raw),
        "progress_sha256": sha256_bytes(progress_raw),
        "returncode": child.get("returncode"),
        "resource_stop_reason": child.get("resource_stop_reason"),
        "stdout_sha256": child.get("stdout_sha256"),
        "stderr_sha256": child.get("stderr_sha256"),
    }


def _find_pending_plan(latest: Mapping[str, Mapping[str, Any]], *, evidence_root: Path) -> tuple[dict[str, Any], Path, bytes] | None:
    pending = [
        event
        for event in latest.values()
        if (
            event.get("event") in {"plan_created", "plan_only_pass"}
            or (event.get("event") == "reconciled" and event.get("decision") == "RESUME_REQUIRED")
        )
    ]
    if len(pending) > 1:
        raise DispatcherError("MULTIPLE_DEFERRED_PLANS_INVALID")
    if not pending:
        return None
    event = pending[0]
    path, raw = _load_saved_plan(event, evidence_root=evidence_root)
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("SAVED_PLAN_INVALID") from None
    return plan, path, raw


def execute_once(
    *,
    authorization_path: Path = AUTHORIZATION_PATH,
    manifest_path: Path = batch.DEFAULT_MANIFEST,
    evidence_root: Path = EVIDENCE_ROOT,
    max_documents: int | None = None,
    sampler: Callable[[], Mapping[str, int]] = sample_resource_metrics,
    plan_only: Callable[[Path], None] | None = None,
    child_runner: Callable[..., Mapping[str, Any]] | None = None,
    continuation_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    _assert_runtime()
    static = _verify_static_bindings()
    auth_context = load_and_validate_authorization(authorization_path)
    auth = auth_context["authorization"]
    if max_documents is not None and (type(max_documents) is not int or max_documents < 1):
        raise DispatcherError("DISPATCH_LIMIT_INVALID")
    limit = min(max_documents or auth["max_documents"], auth["max_documents"])
    manifest_sha, documents, original_rows = _load_original_r3(manifest_path)
    context = {
        **auth_context,
        "manifest_sha256": manifest_sha,
        "static": static,
    }
    journal = DurableJournal(evidence_root)
    completed_this_call = 0
    authorization_limit_reached = False
    cohort_exhausted = False
    resume_required = False
    with journal:
        _verify_or_create_binding(journal, context)
        latest = _latest_document_events(journal.events)
        _halt_if_required(journal, latest)
        _assert_no_duplicate_document_ids(journal.events)
        if not latest:
            _first, initial_count = select_next_document(
                documents,
                original_rows,
                auth_context["pilot_document_ids"],
                set(),
            )
            if initial_count != EXPECTED_POST_PILOT_COHORT:
                raise DispatcherError("POST_PILOT_COHORT_COUNT_MISMATCH")
        baseline = dict(sampler())
        baseline_swap = baseline.get("swap_used_bytes")
        if type(baseline.get("available_bytes")) is not int or type(baseline_swap) is not int:
            raise DispatcherError("RESOURCE_BASELINE_CANNOT_CONFIRM")
        if _resource_stop_reason(baseline, baseline_swap):
            journal.append({"event": "halt", "reason": _resource_stop_reason(baseline, baseline_swap), "phase": "before_first_plan"})
            raise DispatcherError("RESOURCE_GATE_FAILED_BEFORE_DISPATCH")
        samples_path = evidence_root / "resource-samples.jsonl"
        _persist_sample(samples_path, {"phase": "invocation_baseline", **baseline})
        pending = _find_pending_plan(latest, evidence_root=evidence_root)
        while completed_this_call < limit:
            if pending is not None:
                plan, plan_path, plan_raw = pending
                document_id = plan["selected_documents"][0]["document_id"]
                if plan_only is None:
                    _run_plan_only(plan_path, expected_sha256=sha256_bytes(plan_raw))
                else:
                    plan_only(plan_path)
                journal.append({
                    "event": "plan_only_pass",
                    "document_id": document_id,
                    "continuation_id": plan["continuation_id"],
                    "plan_path": str(plan_path),
                    "plan_sha256": sha256_bytes(plan_raw),
                    "plan_bytes_b64": base64.b64encode(plan_raw).decode("ascii"),
                    "state_root": plan["state_root"],
                    "resume_of": latest[document_id].get("plan_sha256"),
                })
                pending = None
            else:
                if len(latest) >= auth["max_documents"]:
                    authorization_limit_reached = True
                    break
                dispatched_ids = set(latest)
                document, remaining = select_next_document(
                    documents,
                    original_rows,
                    auth_context["pilot_document_ids"],
                    dispatched_ids,
                )
                if document is None:
                    cohort_exhausted = True
                    break
                continuation_id = continuation_id_factory() if continuation_id_factory else f"resume-{uuid.uuid4().hex}"
                plan, plan_raw = build_singleton_plan(
                    document,
                    manifest_sha256=manifest_sha,
                    prior_progress_sha256=ORIGINAL_PROGRESS_SHA256,
                    model_settings_sha256=auth["model_settings_sha256"],
                    continuation_id=continuation_id,
                )
                document_id = plan["selected_documents"][0]["document_id"]
                plan_path = evidence_root / "plans" / f"{continuation_id}.json"
                plan_sha = _write_immutable(plan_path, plan_raw)
                journal.append({
                    "event": "plan_created",
                    "document_id": document_id,
                    "continuation_id": continuation_id,
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_sha,
                    "plan_bytes_b64": base64.b64encode(plan_raw).decode("ascii"),
                    "state_root": plan["state_root"],
                    "remaining_eligible_at_selection": remaining,
                })
                if plan_only is None:
                    _run_plan_only(plan_path, expected_sha256=plan_sha)
                else:
                    plan_only(plan_path)
                journal.append({
                    "event": "plan_only_pass",
                    "document_id": document_id,
                    "continuation_id": continuation_id,
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_sha,
                    "plan_bytes_b64": base64.b64encode(plan_raw).decode("ascii"),
                    "state_root": plan["state_root"],
                })
            plan_sha = sha256_bytes(plan_raw)
            journal.append({
                "event": "dispatch_intent",
                "document_id": document_id,
                "continuation_id": plan["continuation_id"],
                "plan_path": str(plan_path),
                "plan_sha256": plan_sha,
                "state_root": plan["state_root"],
                "attempt": completed_this_call + 1,
            })
            child = (
                child_runner(
                    plan_path,
                    baseline_swap_used=baseline_swap,
                    samples_path=samples_path,
                    sampler=sampler,
                )
                if child_runner is not None
                else _run_execution_child(
                    plan_path,
                    expected_plan_sha256=plan_sha,
                    baseline_swap_used=baseline_swap,
                    samples_path=samples_path,
                    sampler=sampler,
                )
            )
            if child.get("child_started") is False:
                reason = child.get("resource_stop_reason") or "CHILD_NOT_STARTED_CANNOT_CONFIRM"
                reconciliation = {
                    "document_id": document_id,
                    "status": "PRE_DISPATCH_RESOURCE_STOP",
                    "decision": "HALT",
                    "model_request_count": 0,
                    "receipt_path": None,
                    "receipt_sha256": None,
                    "progress_sha256": None,
                    "returncode": child.get("returncode"),
                    "resource_stop_reason": reason,
                }
                journal.append({
                    "event": "reconciled",
                    "continuation_id": plan["continuation_id"],
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_sha,
                    "plan_bytes_b64": base64.b64encode(plan_raw).decode("ascii"),
                    "state_root": plan["state_root"],
                    **reconciliation,
                })
                latest[document_id] = dict(journal.events[-1])
                journal.append({"event": "halt", "reason": reason, "document_id": document_id})
                completed_this_call += 1
                break
            try:
                reconciliation = _reconcile_singleton(plan, plan_sha, child=child)
            except Exception as exc:
                code = getattr(exc, "code", None) or type(exc).__name__
                reconciliation = {
                    "document_id": document_id,
                    "status": "AMBIGUOUS_TERMINAL_RECEIPT",
                    "decision": "HALT",
                    "reconciliation_error": str(code)[:96],
                    "receipt_path": None,
                    "receipt_sha256": None,
                    "progress_sha256": None,
                    "returncode": child.get("returncode"),
                    "resource_stop_reason": child.get("resource_stop_reason"),
                    "stdout_sha256": child.get("stdout_sha256"),
                    "stderr_sha256": child.get("stderr_sha256"),
                }
            journal.append({
                "event": "reconciled",
                "continuation_id": plan["continuation_id"],
                "plan_path": str(plan_path),
                "plan_sha256": plan_sha,
                "plan_bytes_b64": base64.b64encode(plan_raw).decode("ascii"),
                "state_root": plan["state_root"],
                **reconciliation,
            })
            latest[document_id] = dict(journal.events[-1])
            completed_this_call += 1
            if reconciliation["decision"] == "HALT":
                journal.append({"event": "halt", "reason": reconciliation["status"], "document_id": document_id})
                break
            if reconciliation["decision"] == "RESUME_REQUIRED":
                resume_required = True
                break
    return {
        "status": (
            "HALTED"
            if any(event.get("event") == "halt" for event in journal.events)
            else "RESUME_REQUIRED" if resume_required
            else "AUTHORIZATION_LIMIT_REACHED" if authorization_limit_reached
            else "COHORT_EXHAUSTED" if cohort_exhausted
            else "READY_FOR_NEXT_INVOCATION"
        ),
        "completed_this_invocation": completed_this_call,
        "latest_terminal_status": next((event.get("status") for event in reversed(journal.events) if event.get("event") == "reconciled"), None),
        "journal_path": str(journal.path),
    }


def _assert_no_duplicate_document_ids(events: Sequence[Mapping[str, Any]]) -> None:
    created: set[str] = set()
    continuation_ids: set[str] = set()
    state_roots: set[str] = set()
    for event in events:
        if event.get("event") == "plan_created":
            document_id = event.get("document_id")
            continuation_id = event.get("continuation_id")
            state_root = event.get("state_root")
            if (
                not isinstance(document_id, str)
                or document_id in created
                or not isinstance(continuation_id, str)
                or continuation_id in continuation_ids
                or not isinstance(state_root, str)
                or state_root in state_roots
            ):
                raise DispatcherError("CROSS_PLAN_DUPLICATE_DOCUMENT")
            created.add(document_id)
            continuation_ids.add(continuation_id)
            state_roots.add(state_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, default=AUTHORIZATION_PATH)
    parser.add_argument("--max-documents", type=int, help="per-invocation cap; authorization still sets the cumulative ceiling")
    parser.add_argument("--execute", action="store_true", help="requires root authorization plus completed pilot gates")
    args = parser.parse_args(argv)
    try:
        _assert_runtime()
        if not args.execute:
            _verify_static_bindings()
            print(json.dumps({"status": "PREPARATION_ONLY", "execution": "NOT_RUN"}, sort_keys=True))
            return 0
        result = execute_once(authorization_path=args.authorization, max_documents=args.max_documents)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        print(json.dumps({"status": "STOPPED", "code": str(code)[:96]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
