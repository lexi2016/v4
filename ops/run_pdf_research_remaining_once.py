#!/usr/bin/env python3
"""Finite, receipt-gated continuation for the frozen PDF cohort.

This module prepares or executes one immutable singleton plan at a time through
the existing PDF batch runner. Cohort status comes from the frozen completion
inventory; existing failures stay outstanding and are held unless a specific
recovery path is validated.
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
COMPLETION_EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1"
)
EVIDENCE_ROOT = COMPLETION_EVIDENCE_ROOT / "remaining-execution-r1"
REMAINING_INVENTORY_PATH = COMPLETION_EVIDENCE_ROOT / "inventory/remaining-core-inventory.json"
EXPECTED_REMAINING_INVENTORY_SHA256 = "58c94d2899e02a17df46e2e3c9ed9e65ad7aa5e19194e7046c849fbe929a7dad"
REMAINING_SELECTION_PATH = COMPLETION_EVIDENCE_ROOT / "writer/remaining-selection-r1/selection.json"
TOOL_CANARY_PLAN_PATH = COMPLETION_EVIDENCE_ROOT / "writer/actual-tool-canary-r3/continuation-plan.json"
TOOL_CANARY_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
    "zsxq_hourly/pdf_local/research/batches/continuation-tool-canary-20261019-r3"
)
THREE_DOCUMENT_CANARY_PLAN_PATH = COMPLETION_EVIDENCE_ROOT / "writer/actual-three-document-canary/continuation-plan.json"
THREE_DOCUMENT_CANARY_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
    "zsxq_hourly/pdf_local/research/batches/continuation-three-document-canary-20261019-r1"
)
PPI_RECOVERY_PLAN_PATH = COMPLETION_EVIDENCE_ROOT / "writer/actual-three-document-canary/ppi-chunk2-recovery-r1/continuation-plan.json"
PPI_RECOVERY_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
    "zsxq_hourly/pdf_local/research/batches/recovery-039fa67f32522085560d4c6032850a54d39612fdc2a1c6d12aae1925227428a1"
)
AI_VIDEO_RECOVERY_PLAN_PATH = COMPLETION_EVIDENCE_ROOT / "writer/ai-video-memory-recovery-r1/continuation-plan.json"
AI_VIDEO_RECOVERY_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
    "zsxq_hourly/pdf_local/research/batches/recovery-2c2e7b6aa372bc32abcb482043688cdd02feff3505d0f678c49efb171c467fc3"
)
THREE_DOCUMENT_CANARY_CONTINUATION_ID = "three-document-canary-20261019-r1"
THREE_DOCUMENT_CANARY_PLAN_SHA256 = "393665466e50d74effefdbd6ea8e2f0b187baa1f342f5ef73de7999380866888"
THREE_DOCUMENT_CANARY_PROGRESS_SHA256 = "20c451ed88ce495b66f691ffbe77be39a3e50bfe754cd819cfbb85b708a455ef"
THREE_DOCUMENT_CANARY_QUEUE_SHA256 = "8e676cf4302b4c526cfe4e786f7c4a5e758986d1e30225754219563ed105ecc0"
PPI_RECOVERY_CONTINUATION_ID = "ppi-chunk2-recovery-20261019-r1"
PPI_RECOVERY_PLAN_SHA256 = "8892257dbdfbd8e9140575053442813971a6f1966f934794f1d31f82f6f4ebe9"
PPI_RECOVERY_PROGRESS_SHA256 = "8f47951b0394e7160db0e4b34d15d7d700583182213d7a113a7bf9c8e34e4d5b"
PPI_RECOVERY_DOCUMENT_PROGRESS_SHA256 = "af80b75351e87f816254c8e6a216b9cbb14a454780c467e0faad0adaaa5643a2"
PPI_RECOVERY_RECEIPT_SHA256 = "03ff49b9eef8867d73acac1b808979bfe2cb0dc94d09b89080a6169bbe6246be"
PPI_RECOVERY_REPORT_SHA256 = "01538e7fc7c19aa1520ed7c02323e364c862be4d72f441a49d5f3f3d9d680c47"
PPI_RECOVERY_PAGE_INPUT_SHA256 = "7731789b3a3e4446e0c821496e0f29133e31964d7e65a85ef0dc16b58672493c"
PPI_RECOVERY_QUEUE_SHA256 = "bd1388720f75f12c7caae41cbe8439e8191ce5df946403addd4268ceb9cdf667"
AI_VIDEO_RECOVERY_CONTINUATION_ID = "memory-recovery-ai-video-20261019-r1"
AI_VIDEO_RECOVERY_PLAN_SHA256 = "7b41c24d7ce9d77629b9da2bb6a1ab2060dcc5586e4a03e77e457d7ba8c4e6af"
AI_VIDEO_RECOVERY_PROGRESS_SHA256 = "51c0f2302b843e6765f25b93d7b8472d9cf1a8857e948c528ec0f89982654cd2"
AI_VIDEO_RECOVERY_DOCUMENT_PROGRESS_SHA256 = "215931a8a4917272716c4eb4dee850f455eb8c11eb16517ae26e2a6692c02bc5"
AI_VIDEO_RECOVERY_RECEIPT_SHA256 = "36b029d65106a748ca19e5cdd8fa0ed61717efd7a66a3ae0b3eec84e8f215276"
AI_VIDEO_RECOVERY_REPORT_SHA256 = "365d71e591e41f7fcad17bf135bf8f853448bbbb81be2c8d813d6345567f1735"
AI_VIDEO_RECOVERY_PAGE_INPUT_SHA256 = "d1a644f6f463ce0528ceec582798e723ec50088c57078e6902f7a7695983f961"
AI_VIDEO_RECOVERY_QUEUE_SHA256 = "17eb6e96fe361bd5e8fa0401a2ac38b91b3477b9e3212c5e78697091f01adace"
THREE_DOCUMENT_CANARY_IDS = (
    "8a8e06be978f10311bfdff6e6a17b6d49bce6c5db29400e88c4df014bd5558aa",
    "6892ef7be8071665aa96fdf125a4a1acac8367f3f7eb3a772e84fd121b9fd87b",
    "eeed6e4916c2a8b44d0f3911d9303de754e6164d8d33cc7f11f4c15dae9f49a5",
)
THREE_DOCUMENT_ORIGINAL_BINDINGS = {
    "8a8e06be978f10311bfdff6e6a17b6d49bce6c5db29400e88c4df014bd5558aa": {
        "status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "progress_sha256": "42213404cb187fc6ee683ee53dfd501159c363b00b135d993564f198b9318bff",
        "receipt_sha256": "925fbe8fc3d01bb9886f067f68dd662e4f16cca937504e1cb985712fe1231ea6",
        "page_input_sha256": "d8ea959fc5a3d5334bf0373938e7cb51595a123506e7fb3d20a91ee4f4455098",
        "report_sha256": "94726be4535b39d56d678acb5ce9ca687ad63a595c1d35e32fc700e8ef219b69",
    },
    "6892ef7be8071665aa96fdf125a4a1acac8367f3f7eb3a772e84fd121b9fd87b": {
        "status": "FAILED_NO_RETRY",
        "progress_sha256": "c74c7a87d397e304c8df980f4f0b192061c578ba2858e543895787f268bbf72c",
        "receipt_sha256": "dec0ac530f63194956ce3e755d9e062d332abccf1b601966418238c438626634",
        "page_input_sha256": "7731789b3a3e4446e0c821496e0f29133e31964d7e65a85ef0dc16b58672493c",
        "report_sha256": None,
    },
    "eeed6e4916c2a8b44d0f3911d9303de754e6164d8d33cc7f11f4c15dae9f49a5": {
        "status": "FAILED_NO_RETRY",
        "progress_sha256": "f5d00a49a617d58f95669c881578d7c17017042ba60fa76f54383e1b4c89a888",
        "receipt_sha256": "6e9843b06c2aaed4da7cb06cbe85e2f5332cf129adc4174cf7784d89c91ee469",
        "page_input_sha256": "d1a644f6f463ce0528ceec582798e723ec50088c57078e6902f7a7695983f961",
        "report_sha256": None,
    },
}
TOOL_CANARY_DOCUMENT_ID = "fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b"
TOOL_CANARY_CONTINUATION_ID = "tool-canary-20261019-r3"
EXPECTED_TOOL_CANARY_PLAN_SHA256 = "40cab1194bd19d3caa5b54f4d9129fd8903c770d0cdc13f5f708b4b623e2f2d5"
EXPECTED_TOOL_CANARY_PROGRESS_SHA256 = "efc7767988563f15550e6f5008ca26bf6875891214ae46954044c64cabb4bc89"
EXPECTED_TOOL_CANARY_RECEIPT_SHA256 = "cfd15fc9c0b47abbaa8c966b6047da991034c062e059c2394e51cc2518e0d6ab"
EXPECTED_TOOL_CANARY_REPORT_SHA256 = "d521155a327dec9d0013acd66894160b7a744e401403959e1b637e4916e15fe0"
EXPECTED_TOOL_CANARY_PAGE_INPUT_SHA256 = "2408358e4ae95ff5e31dc296f1f24722ccd60870a3836d75bf07107f2d22be2e"
EXPECTED_TOOL_CANARY_QUEUE_SHA256 = "f9708301309395b582d9dcc458ac63a2fbb23bea3e2d1c44db1a0ecfd9983f76"
EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256 = "0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7"
TERMINAL_RECEIPT_BINDINGS = {
    "2bf9390cd9f4490b42f7cee921c23437b6c014dab1f973c07f6d5a6a9938232e": (
        Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
             "zsxq_hourly/pdf_local/research/batches/continuation-resume-4d4f62ca2f654a6aa3b9f7b25a90b3b6/"
             "documents/2bf9390cd9f4490b42f7cee921c23437b6c014dab1f973c07f6d5a6a9938232e/receipt.json"),
        "f3921ac864c8749ecf5ef4365fa75d3778b62de9758f07de53dfcc7e46f130a1",
    ),
    "a87847018b68a74f4f9969c3ddce8352cf7ba03450c0ec51fbdd5c8ad181d0f5": (
        Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
             "zsxq_hourly/pdf_local/research/batches/continuation-resume-7c46270727404030a4b82ac12a271ef1/"
             "documents/a87847018b68a74f4f9969c3ddce8352cf7ba03450c0ec51fbdd5c8ad181d0f5/receipt.json"),
        "861a1dca49bae7cfcbc60ac6591a46f1098d4cb12701164d26862f83e5c937f6",
    ),
}
SCOPE_PATH = CONTINUATION_ROOT / "ROOT_REMAINING_ONCE_SCOPE.json"
AUTHORIZATION_PATH = CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION.json"
PILOT_PLAN_PATH = CONTINUATION_ROOT / "pilot-continuation-r2.json"
PILOT_SELECTION_PATH = CONTINUATION_ROOT / "pilot-selection-r2.json"
ORIGINAL_PROGRESS_SHA256 = "67a658ecc731cd01413523bb9a8cff3393a21e317f4cdfb00f011e055b4fdb84"
EXPECTED_MANIFEST_SHA256 = "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9"
EXPECTED_RUNNER_SHA256 = "9bacc8a23c9885de18278427e3099cdc72cbd2f871a6d7908b36ea51301e9ade"
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
FROZEN_COHORT_DOCUMENT_COUNT = 2209
PRESERVED_COMPLETED_DOCUMENT_COUNT = 86
PRE_CANARY_OUTSTANDING_DOCUMENT_COUNT = 2123
CURRENT_COMPLETED_DOCUMENT_COUNT = 90
CURRENT_OUTSTANDING_DOCUMENT_COUNT = 2119
REMAINING_NONQUARANTINED_DOCUMENT_COUNT = 2118
REMAINING_UNPROCESSED_RUNNABLE_COUNT = 2050
EXPECTED_POST_PILOT_COHORT = REMAINING_UNPROCESSED_RUNNABLE_COUNT
PILOT_DOCUMENT_COUNT = 10
QUARANTINE_DOCUMENT_ID = "23dd2b2a5a3b5a9107e389f27b1b73bf6e6ba6a61e63afa9a35f0b73246809a9"
MIN_AVAILABLE_BYTES = 8_589_934_592
MAX_SWAP_GROWTH_BYTES = 536_870_912
RESOURCE_SAMPLE_INTERVAL_SECONDS = 1.0
MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES = 1_073_741_824
MEMORY_RECOVERY_SWAP_REDUCTION_BYTES = 536_870_912
MEMORY_RECOVERY_STABLE_SAMPLE_COUNT = 2
MEMORY_RECOVERY_POLL_SECONDS = 5.0
MEMORY_RECOVERY_MAX_WAIT_SECONDS = 900.0
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
    {
        "binding",
        "source_adoption",
        "plan_created",
        "plan_only_pass",
        "dispatch_intent",
        "reconciled",
        "memory_recovery_wait",
        "halt_resolution",
        "halt",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HALT_RESUME_SCHEMA = "v4.pdf_remaining_once.halt_resume_adoption.v1"
HALT_RESUME_DESCRIPTOR_FIELDS = frozenset(
    {
        "schema",
        "status",
        "authorization_id",
        "previous_authorization_path",
        "previous_authorization_sha256",
        "journal_path",
        "journal_prefix_sha256",
        "journal_event_count",
        "reconciled_event_index",
        "reconciled_event_line_sha256",
        "halt_event_index",
        "halt_event_line_sha256",
        "document_id",
        "continuation_id",
        "plan_sha256",
        "receipt_sha256",
        "run_progress_sha256",
        "document_progress_sha256",
        "page_input_sha256",
        "queue_key",
        "queue_state_sha256",
        "job_input_sha256",
        "stream_receipt_sha256",
        "request_input_sha256",
        "raw_sse_sha256",
        "resource_samples_path",
        "resource_samples_prefix_bytes",
        "resource_samples_prefix_sha256",
        "failed_resource_sample_line_sha256",
        "recovery_generation",
        "old_dispatcher_sha256",
        "old_runner_sha256",
        "new_dispatcher_sha256",
        "new_runner_sha256",
        "reviewer_receipt_sha256",
    }
)
COMPLETED_INVENTORY_STATUSES = frozenset(
    {"USER_ACCEPTED_REUSED_REPORT", "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"}
)
OUTSTANDING_INVENTORY_STATUSES = frozenset(
    {"FAILED_DOCUMENT_ISOLATED", "FAILED_NO_RETRY", "SOURCE_REPAIR_FAILED_NO_MODEL", "UNPROCESSED"}
)


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
        "prepared_text_manifest_sha256",
    }
    if set(auth) != expected_fields or auth.get("status") != "AUTHORIZED":
        raise DispatcherError("ROOT_EXECUTION_AUTHORIZATION_INVALID")
    if not SHA256_RE.fullmatch(str(auth.get("prepared_text_manifest_sha256", ""))):
        raise DispatcherError("ROOT_PREPARED_MANIFEST_AUTHORIZATION_REQUIRED")
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
    adoption_evidence: dict[str, Any] | None = None
    for key, statuses in (
        ("resource_gate", {"PASS"}),
        ("sentinel_gate", {"PASS"}),
        ("reviewer_receipt", {"PASS", "REVIEWED_PASS"}),
        ("adoption_receipt", {"ADOPTED", "ROOT_ADOPTED"}),
    ):
        evidence = _verified_json_evidence(
            auth[key], expected_statuses=statuses, code=f"{key.upper()}_EVIDENCE_INVALID"
        )
        if key == "adoption_receipt":
            adoption_evidence = evidence
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
            if (evidence.get("model_settings_sha256") != auth.get("model_settings_sha256")
                    or evidence.get("prepared_text_manifest_sha256") != auth.get("prepared_text_manifest_sha256")):
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
        "adoption_evidence": adoption_evidence,
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


def _verify_terminal_receipt(document_id: str, path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = _read_regular(path, "TERMINAL_COMPLETION_RECEIPT_UNAVAILABLE")
    if sha256_bytes(raw) != expected_sha256:
        raise DispatcherError("TERMINAL_COMPLETION_RECEIPT_SHA_MISMATCH")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TERMINAL_COMPLETION_RECEIPT_INVALID") from None
    if (
        not isinstance(receipt, dict)
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
        or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or receipt.get("research_only") is not True
        or receipt.get("production_allowed") is not False
        or receipt.get("buy_gate_updated") is not False
        or receipt.get("orders_sent") is not False
    ):
        raise DispatcherError("TERMINAL_COMPLETION_RECEIPT_BINDING_MISMATCH")
    return {"path": str(path), "sha256": expected_sha256, "status": receipt["status"]}


def _verify_current_tool_canary_completion() -> dict[str, Any]:
    """Verify the post-inventory canary receipt before changing its prior status."""
    plan_raw = _read_regular(TOOL_CANARY_PLAN_PATH, "TOOL_CANARY_PLAN_UNAVAILABLE")
    if sha256_bytes(plan_raw) != EXPECTED_TOOL_CANARY_PLAN_SHA256:
        raise DispatcherError("TOOL_CANARY_PLAN_SHA_MISMATCH")
    try:
        plan = json.loads(plan_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TOOL_CANARY_PLAN_INVALID") from None
    selected = plan.get("selected_documents") if isinstance(plan, dict) else None
    if (
        not isinstance(plan, dict)
        or plan.get("continuation_id") != TOOL_CANARY_CONTINUATION_ID
        or plan.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or plan.get("state_root") != str(TOOL_CANARY_STATE_ROOT)
        or plan.get("expected_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or plan.get("observed_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or not isinstance(selected, list)
        or len(selected) != 1
        or not isinstance(selected[0], dict)
        or selected[0].get("document_id") != TOOL_CANARY_DOCUMENT_ID
        or selected[0].get("source_sha256") != TOOL_CANARY_DOCUMENT_ID
        or selected[0].get("prior_status") != "FAILED_NO_RETRY"
        or plan.get("research_only") != {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    ):
        raise DispatcherError("TOOL_CANARY_PLAN_BINDING_INVALID")

    plan_sha256 = sha256_bytes(plan_raw)
    progress_path = TOOL_CANARY_STATE_ROOT / "run-progress.json"
    progress_raw = _read_regular(progress_path, "TOOL_CANARY_PROGRESS_UNAVAILABLE")
    if sha256_bytes(progress_raw) != EXPECTED_TOOL_CANARY_PROGRESS_SHA256:
        raise DispatcherError("TOOL_CANARY_PROGRESS_SHA_MISMATCH")
    try:
        progress = json.loads(progress_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TOOL_CANARY_PROGRESS_INVALID") from None
    rows = progress.get("documents") if isinstance(progress, dict) else None
    if (
        not isinstance(progress, dict)
        or progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
        or progress.get("continuation_id") != TOOL_CANARY_CONTINUATION_ID
        or progress.get("continuation_plan_sha256") != plan_sha256
        or progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or progress.get("model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or progress.get("research_only") is not True
        or progress.get("production_allowed") is not False
        or progress.get("buy_gate_updated") is not False
        or progress.get("orders_sent") is not False
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("document_id") != TOOL_CANARY_DOCUMENT_ID
        or rows[0].get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    ):
        raise DispatcherError("TOOL_CANARY_PROGRESS_BINDING_INVALID")

    document_root = TOOL_CANARY_STATE_ROOT / "documents" / TOOL_CANARY_DOCUMENT_ID
    receipt_path = document_root / "receipt.json"
    receipt_raw = _read_regular(receipt_path, "TOOL_CANARY_RECEIPT_UNAVAILABLE")
    if sha256_bytes(receipt_raw) != EXPECTED_TOOL_CANARY_RECEIPT_SHA256:
        raise DispatcherError("TOOL_CANARY_RECEIPT_SHA_MISMATCH")
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TOOL_CANARY_RECEIPT_INVALID") from None
    continuation = receipt.get("continuation") if isinstance(receipt, dict) else None
    chunks = receipt.get("chunks") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("document_id") != TOOL_CANARY_DOCUMENT_ID
        or receipt.get("pdf_sha256") != TOOL_CANARY_DOCUMENT_ID
        or receipt.get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
        or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or receipt.get("model_request_count") != 1
        or receipt.get("research_only") is not True
        or receipt.get("production_allowed") is not False
        or receipt.get("buy_gate_updated") is not False
        or receipt.get("orders_sent") is not False
        or not isinstance(continuation, dict)
        or continuation.get("continuation_id") != TOOL_CANARY_CONTINUATION_ID
        or continuation.get("plan_sha256") != plan_sha256
        or continuation.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or continuation.get("model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or not isinstance(chunks, list)
        or len(chunks) != 1
        or not isinstance(chunks[0], dict)
        or chunks[0].get("status") not in {"SUCCEEDED", "SUCCEEDED_REUSED", "SUCCEEDED_REUSED_CONTINUATION_SOURCE"}
    ):
        raise DispatcherError("TOOL_CANARY_RECEIPT_BINDING_INVALID")

    report_path = document_root / "report.md"
    report_raw = _read_regular(report_path, "TOOL_CANARY_REPORT_UNAVAILABLE")
    if sha256_bytes(report_raw) != EXPECTED_TOOL_CANARY_REPORT_SHA256:
        raise DispatcherError("TOOL_CANARY_REPORT_SHA_MISMATCH")
    page_input_path = document_root / "page-input.json"
    page_input_raw = _read_regular(page_input_path, "TOOL_CANARY_PAGE_INPUT_UNAVAILABLE")
    if sha256_bytes(page_input_raw) != EXPECTED_TOOL_CANARY_PAGE_INPUT_SHA256:
        raise DispatcherError("TOOL_CANARY_PAGE_INPUT_SHA_MISMATCH")
    try:
        page_input = json.loads(page_input_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TOOL_CANARY_PAGE_INPUT_INVALID") from None
    pages = page_input.get("pages") if isinstance(page_input, dict) else None
    if (
        not isinstance(page_input, dict)
        or page_input.get("document_id") != TOOL_CANARY_DOCUMENT_ID
        or page_input.get("pdf_sha256") != TOOL_CANARY_DOCUMENT_ID
        or not isinstance(pages, list)
        or len(pages) != 1
    ):
        raise DispatcherError("TOOL_CANARY_PAGE_INPUT_BINDING_INVALID")

    queue_path = TOOL_CANARY_STATE_ROOT / "queue" / "queue-state.json"
    queue_raw = _read_regular(queue_path, "TOOL_CANARY_QUEUE_UNAVAILABLE")
    if sha256_bytes(queue_raw) != EXPECTED_TOOL_CANARY_QUEUE_SHA256:
        raise DispatcherError("TOOL_CANARY_QUEUE_SHA_MISMATCH")
    try:
        queue = json.loads(queue_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("TOOL_CANARY_QUEUE_INVALID") from None
    jobs = queue.get("jobs") if isinstance(queue, dict) else None
    job = next(iter(jobs.values()), None) if isinstance(jobs, dict) and len(jobs) == 1 else None
    identity = job.get("identity") if isinstance(job, dict) else None
    if (
        not isinstance(queue, dict)
        or queue.get("schema") != "v4.announcement-engine-queue/v1"
        or not isinstance(jobs, dict)
        or len(jobs) != 1
        or not isinstance(job, dict)
        or job.get("queue_id") != "v4-pdf-simple-batch"
        or job.get("model_id") != "qwen3_8_flash_next"
        or job.get("status") != "SUCCEEDED"
        or job.get("attempt_count") != 1
        or job.get("max_attempts") != 1
        or not isinstance(identity, dict)
        or not str(identity.get("article_id", "")).startswith(f"{TOOL_CANARY_DOCUMENT_ID}:chunk:000001:")
    ):
        raise DispatcherError("TOOL_CANARY_QUEUE_BINDING_INVALID")
    attempts = job.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 1:
        raise DispatcherError("TOOL_CANARY_QUEUE_ATTEMPT_COUNT_INVALID")
    return {
        "continuation_id": TOOL_CANARY_CONTINUATION_ID,
        "plan_sha256": plan_sha256,
        "progress_sha256": EXPECTED_TOOL_CANARY_PROGRESS_SHA256,
        "receipt_sha256": EXPECTED_TOOL_CANARY_RECEIPT_SHA256,
        "report_sha256": EXPECTED_TOOL_CANARY_REPORT_SHA256,
        "page_input_sha256": EXPECTED_TOOL_CANARY_PAGE_INPUT_SHA256,
        "queue_sha256": EXPECTED_TOOL_CANARY_QUEUE_SHA256,
        "model_settings_sha256": EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256,
    }


def _read_bound_json(
    path: Path,
    expected_sha256: str,
    *,
    unavailable_code: str,
    mismatch_code: str,
    invalid_code: str,
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular(path, unavailable_code)
    if sha256_bytes(raw) != expected_sha256:
        raise DispatcherError(mismatch_code)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError(invalid_code) from None
    if not isinstance(value, dict):
        raise DispatcherError(invalid_code)
    return raw, value


def build_memory_recovery_plan(
    prior_plan: Mapping[str, Any],
    prior_plan_raw: bytes,
    document: Mapping[str, Any],
    *,
    model_settings_sha256: str,
    continuation_id: str | None = None,
) -> tuple[dict[str, Any], bytes] | None:
    """Build one generic recovery plan only for a fully evidenced prefill failure."""
    document_id = document.get("document_id")
    selected = prior_plan.get("selected_documents")
    matching_prior_rows = [
        row for row in selected or []
        if isinstance(row, dict) and row.get("document_id") == document_id
    ] if isinstance(selected, list) else []
    if (
        not isinstance(document_id, str)
        or document.get("pdf_sha256") != document_id
        or not isinstance(selected, list)
        or len(matching_prior_rows) != 1
        or matching_prior_rows[0].get("source_sha256") != document_id
        or matching_prior_rows[0].get("prior_status") != "UNPROCESSED"
        or "recovery" in matching_prior_rows[0]
        or prior_plan.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or prior_plan.get("prior_progress_path") != str(batch.DEFAULT_STATE_ROOT / "run-progress.json")
        or prior_plan.get("prior_progress_sha256") != ORIGINAL_PROGRESS_SHA256
        or model_settings_sha256 not in batch.CONTINUATION_ALLOWED_SETTINGS_SHA256S
    ):
        raise DispatcherError("MEMORY_RECOVERY_INITIAL_PLAN_INVALID")
    prior_state_root = Path(str(prior_plan.get("state_root", ""))).expanduser().absolute()
    batches_root = batch.DEFAULT_STATE_ROOT.expanduser().absolute().parent
    if (
        prior_state_root.parent != batches_root
        or not re.fullmatch(r"continuation-[a-z0-9][a-z0-9-]{0,95}", prior_state_root.name)
        or prior_state_root.is_symlink()
        or not prior_state_root.is_dir()
    ):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_STATE_ROOT_INVALID")
    plan_sha256 = sha256_bytes(prior_plan_raw)
    saved_plan_raw = _read_regular(prior_state_root / "continuation-plan.json", "MEMORY_RECOVERY_PRIOR_PLAN_UNAVAILABLE")
    if saved_plan_raw != prior_plan_raw:
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_PLAN_MISMATCH")

    relative_document_root = Path("documents") / document_id
    relative_paths = {
        "continuation-plan.json": Path("continuation-plan.json"),
        "run-progress.json": Path("run-progress.json"),
        f"documents/{document_id}/progress.json": relative_document_root / "progress.json",
        f"documents/{document_id}/receipt.json": relative_document_root / "receipt.json",
        f"documents/{document_id}/page-input.json": relative_document_root / "page-input.json",
    }
    run_raw = _read_regular(prior_state_root / relative_paths["run-progress.json"], "MEMORY_RECOVERY_PRIOR_PROGRESS_UNAVAILABLE")
    progress_raw = _read_regular(prior_state_root / relative_paths[f"documents/{document_id}/progress.json"], "MEMORY_RECOVERY_PRIOR_DOCUMENT_PROGRESS_UNAVAILABLE")
    receipt_raw = _read_regular(prior_state_root / relative_paths[f"documents/{document_id}/receipt.json"], "MEMORY_RECOVERY_PRIOR_RECEIPT_UNAVAILABLE")
    page_input_raw = _read_regular(prior_state_root / relative_paths[f"documents/{document_id}/page-input.json"], "MEMORY_RECOVERY_PRIOR_PAGE_INPUT_UNAVAILABLE")
    try:
        run_progress = json.loads(run_raw.decode("utf-8"))
        progress = json.loads(progress_raw.decode("utf-8"))
        receipt = json.loads(receipt_raw.decode("utf-8"))
        page_input = json.loads(page_input_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_ARTIFACT_INVALID") from None
    if (
        not isinstance(run_progress, dict)
        or run_progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
        or run_progress.get("continuation_id") != prior_plan.get("continuation_id")
        or run_progress.get("continuation_plan_sha256") != plan_sha256
        or run_progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or run_progress.get("queue_root") != str(prior_state_root / "queue")
        or not isinstance(run_progress.get("documents"), list)
        or sum(1 for row in run_progress["documents"] if isinstance(row, dict) and row.get("document_id") == document_id and row.get("status") == "FAILED_NO_RETRY") != 1
        or not isinstance(progress, dict)
        or progress.get("document_id") != document_id
        or progress.get("pdf_sha256") != document_id
        or progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or progress.get("status") != "FAILED_NO_RETRY"
        or type(progress.get("model_requests")) is not int
        or progress["model_requests"] < 1
        or progress.get("page_input_sha256") != sha256_bytes(page_input_raw)
        or not isinstance(page_input, dict)
        or page_input.get("document_id") != document_id
        or page_input.get("pdf_sha256") != document_id
        or page_input.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or not isinstance(receipt, dict)
        or receipt.get("schema") != "v4.pdf_research_simple_batch.document_receipt.v1"
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or receipt.get("status") != "FAILED_NO_RETRY"
        or receipt.get("report") is not None
        or not isinstance(receipt.get("page_input"), dict)
        or receipt["page_input"].get("sha256") != sha256_bytes(page_input_raw)
    ):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_DOCUMENT_BINDING_INVALID")

    failure_rows: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for collection in ("chunks", "synthesis"):
        rows = receipt.get(collection, [])
        if not isinstance(rows, list):
            raise DispatcherError("MEMORY_RECOVERY_PRIOR_RECEIPT_ROWS_INVALID")
        for row in rows:
            if not isinstance(row, dict):
                raise DispatcherError("MEMORY_RECOVERY_PRIOR_RECEIPT_ROWS_INVALID")
            queue_item = row.get("queue_item")
            if row.get("status") == "FAILED_NO_RETRY":
                if not isinstance(queue_item, dict):
                    raise DispatcherError("MEMORY_RECOVERY_PRIOR_QUEUE_REFERENCE_INVALID")
                failure_rows.append((collection, row, queue_item))
    if len(failure_rows) != 1:
        return None
    _, failed_row, queue_item_ref = failure_rows[0]
    key = queue_item_ref.get("idempotency_key")
    queue_identity_ref = queue_item_ref.get("identity")
    article_id = queue_identity_ref.get("article_id") if isinstance(queue_identity_ref, dict) else None
    if (
        not isinstance(key, str)
        or not SHA256_RE.fullmatch(key)
        or not isinstance(article_id, str)
        or not article_id.startswith(f"{document_id}:")
    ):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_QUEUE_REFERENCE_INVALID")
    queue_relative = Path("queue") / "queue-state.json"
    job_relative = Path("queue") / "jobs" / key / "input.json"
    stream_dir = Path("evidence") / "streams" / key / "attempt-0001"
    stream_relative = stream_dir / "stream-receipt.json"
    request_relative = stream_dir / "round-01.request-input.json"
    raw_relative = stream_dir / "round-01.raw.sse"
    relative_paths.update(
        {
            "queue/queue-state.json": queue_relative,
            f"queue/jobs/{key}/input.json": job_relative,
            f"evidence/streams/{key}/attempt-0001/stream-receipt.json": stream_relative,
            f"evidence/streams/{key}/attempt-0001/round-01.request-input.json": request_relative,
            f"evidence/streams/{key}/attempt-0001/round-01.raw.sse": raw_relative,
        }
    )
    queue_raw = _read_regular(prior_state_root / queue_relative, "MEMORY_RECOVERY_PRIOR_QUEUE_UNAVAILABLE")
    job_input_raw = _read_regular(prior_state_root / job_relative, "MEMORY_RECOVERY_PRIOR_JOB_INPUT_UNAVAILABLE")
    stream_raw = _read_regular(prior_state_root / stream_relative, "MEMORY_RECOVERY_PRIOR_STREAM_RECEIPT_UNAVAILABLE")
    request_raw = _read_regular(prior_state_root / request_relative, "MEMORY_RECOVERY_PRIOR_REQUEST_INPUT_UNAVAILABLE")
    response_raw = _read_regular(prior_state_root / raw_relative, "MEMORY_RECOVERY_PRIOR_RESPONSE_UNAVAILABLE")
    try:
        queue_state = json.loads(queue_raw.decode("utf-8"))
        job_input = json.loads(job_input_raw.decode("utf-8"))
        stream_receipt = json.loads(stream_raw.decode("utf-8"))
        request_input = json.loads(request_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_QUEUE_ARTIFACT_INVALID") from None
    jobs = queue_state.get("jobs") if isinstance(queue_state, dict) else None
    job = jobs.get(key) if isinstance(jobs, dict) else None
    attempts = job.get("attempts") if isinstance(job, dict) else None
    rounds = stream_receipt.get("rounds") if isinstance(stream_receipt, dict) else None
    failure_attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    raw_sha256 = sha256_bytes(response_raw)
    settings_bound = batch._continuation_recovery_request_settings_confirmed(
        stream_receipt,
        expected_model_settings_sha256=model_settings_sha256,
    )
    if (
        not isinstance(queue_state, dict)
        or queue_state.get("schema") != "v4.announcement-engine-queue/v1"
        or not isinstance(job, dict)
        or job.get("idempotency_key") != key
        or job.get("queue_id") != "v4-pdf-simple-batch"
        or job.get("model_id") != "qwen3_8_flash_next"
        or job.get("status") != "FAILED"
        or job.get("attempt_count") != 1
        or job.get("max_attempts") != 1
        or job.get("payload_sha256") != sha256_bytes(job_input_raw)
        or job.get("input_path") != f"jobs/{key}/input.json"
        or job.get("raw_path") is not None
        or job.get("raw_sha256") is not None
        or not isinstance(job.get("identity"), dict)
        or job["identity"].get("article_id") != article_id
        or job["identity"].get("model_id") != job_input.get("model_id")
        or not isinstance(failure_attempt, dict)
        or failure_attempt.get("number") != 1
        or failure_attempt.get("status") != "FAILED"
        or not isinstance(job_input, dict)
        or job_input.get("article_id") != article_id
        or job_input.get("source_sha256") != document_id
        or job_input.get("source_document_id") != document_id
        or not isinstance(job_input.get("model_binding"), dict)
        or job_input["model_binding"].get("model_settings_sha256") != model_settings_sha256
        or job_input["model_binding"].get("runtime_settings_sha256") != batch.EXPECTED_RUNTIME_SHA256
        or not isinstance(job_input.get("pdf_tool_binding"), dict)
        or job_input["pdf_tool_binding"].get("page_input_sha256") != sha256_bytes(page_input_raw)
        or not isinstance(stream_receipt, dict)
        or stream_receipt.get("status") != "FAILED"
        or stream_receipt.get("idempotency_key") != key
        or stream_receipt.get("model_id") != "qwen3_8_flash_next"
        or stream_receipt.get("model_settings_sha256") != model_settings_sha256
        or stream_receipt.get("runtime_settings_sha256") != batch.EXPECTED_RUNTIME_SHA256
        or not isinstance(rounds, list)
        or len(rounds) != 1
        or not isinstance(rounds[0], dict)
        or (
            "status" in rounds[0]
            and rounds[0].get("status") != "FAILED"
        )
        or rounds[0].get("request_input_sha256") != sha256_bytes(request_raw)
        or rounds[0].get("raw_sse_sha256") != raw_sha256
        or not batch._continuation_recovery_raw_has_exact_error(response_raw)
        or not settings_bound
        or not isinstance(request_input, dict)
        or request_input.get("model") != "qwen3_8_flash_next"
        or request_input.get("temperature") != 0.0
        or request_input.get("stream") is not True
        or type(request_input.get("max_tokens")) is not int
        or request_input["max_tokens"] < 1
        or not isinstance(request_input.get("messages"), list)
        or not request_input["messages"]
    ):
        # A non-prefill model error is deliberately not routed through memory recovery.
        if batch._continuation_recovery_raw_has_exact_error(response_raw):
            raise DispatcherError("MEMORY_RECOVERY_PRIOR_EVIDENCE_MISMATCH")
        return None

    artifact_hashes = {
        relative: sha256_bytes(_read_regular(prior_state_root / relative_path, "MEMORY_RECOVERY_PRIOR_ARTIFACT_UNAVAILABLE"))
        for relative, relative_path in relative_paths.items()
    }
    if artifact_hashes["queue/jobs/" + key + "/input.json"] != job.get("payload_sha256"):
        raise DispatcherError("MEMORY_RECOVERY_PRIOR_PAYLOAD_SHA_MISMATCH")
    continuation_id = continuation_id or f"memory-recovery-{key[:24]}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", continuation_id):
        raise DispatcherError("MEMORY_RECOVERY_CONTINUATION_ID_INVALID")
    recovery = {
        "generation": 1,
        "prior_document_receipt_sha256": artifact_hashes[f"documents/{document_id}/receipt.json"],
        "prior_queue_idempotency_key": key,
        "prior_payload_sha256": job["payload_sha256"],
        "prior_article_id": article_id,
        "prior_source_sha256": document_id,
        "prior_raw_sha256": raw_sha256,
        "prior_state_root": str(prior_state_root),
        "prior_artifact_sha256": artifact_hashes,
    }
    state_root = batches_root / f"recovery-{key}"
    plan = {
        "schema": PLAN_SCHEMA,
        "continuation_id": continuation_id,
        "source_run_id": batch.CONTINUATION_SOURCE_RUN_ID,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "prior_progress_path": str(batch.DEFAULT_STATE_ROOT / "run-progress.json"),
        "prior_progress_sha256": ORIGINAL_PROGRESS_SHA256,
        "prior_progress_status": "STOPPED_GRACEFULLY",
        "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        "expected_model_settings_sha256": model_settings_sha256,
        "observed_model_settings_sha256": model_settings_sha256,
        "state_root": str(state_root),
        "selected_documents": [{
            "document_id": document_id,
            "prior_status": "FAILED_NO_RETRY",
            "source_sha256": document_id,
            "recovery": recovery,
        }],
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


def _wait_for_recovery_resource_change(
    failure_sample: Mapping[str, Any],
    *,
    baseline_swap_used: int,
    sampler: Callable[[], Mapping[str, int]],
    sleep_fn: Callable[[float], Any] = time.sleep,
    persist: Callable[[Mapping[str, Any]], None] | None = None,
    timeout_seconds: float = MEMORY_RECOVERY_MAX_WAIT_SECONDS,
    poll_seconds: float = MEMORY_RECOVERY_POLL_SECONDS,
) -> dict[str, Any]:
    before_available = failure_sample.get("available_bytes")
    before_swap = failure_sample.get("swap_used_bytes")
    if type(before_available) is not int or type(before_swap) is not int or before_available < 0 or before_swap < 0:
        return {"status": "RESOURCE_SAMPLE_CANNOT_CONFIRM", "before": dict(failure_sample), "after": None}
    if timeout_seconds < 0 or poll_seconds <= 0:
        raise DispatcherError("MEMORY_RECOVERY_WAIT_BOUND_INVALID")
    stable = 0
    last: dict[str, Any] | None = None
    started = time.monotonic()
    while time.monotonic() - started <= timeout_seconds:
        sleep_fn(min(poll_seconds, max(0.0, timeout_seconds - (time.monotonic() - started))))
        try:
            last = dict(sampler())
        except Exception:
            last = None
        if persist is not None:
            persist({"phase": "memory_recovery_wait", "before": dict(failure_sample), "sample": last})
        if last is None or _resource_stop_reason(last, baseline_swap_used):
            stable = 0
            continue
        available_gain = last["available_bytes"] - before_available
        swap_reduction = before_swap - last["swap_used_bytes"]
        observed_change = (
            available_gain >= MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES
            or swap_reduction >= MEMORY_RECOVERY_SWAP_REDUCTION_BYTES
        )
        stable = stable + 1 if observed_change else 0
        if stable >= MEMORY_RECOVERY_STABLE_SAMPLE_COUNT:
            return {
                "status": "RESOURCE_CHANGE_OBSERVED",
                "before": dict(failure_sample),
                "after": last,
                "available_gain_bytes": available_gain,
                "swap_reduction_bytes": swap_reduction,
                "stable_samples": stable,
            }
    return {"status": "RESOURCE_CHANGE_NOT_OBSERVED_WITHIN_BOUND", "before": dict(failure_sample), "after": last}


def _verify_document_output(
    *,
    state_root: Path,
    document_id: str,
    expected_status: str,
    expected_progress_sha256: str,
    expected_receipt_sha256: str,
    expected_page_input_sha256: str,
    expected_report_sha256: str | None,
    expected_model_requests: int | None,
    label: str,
) -> dict[str, Any]:
    document_root = state_root / "documents" / document_id
    _progress_raw, progress = _read_bound_json(
        document_root / "progress.json",
        expected_progress_sha256,
        unavailable_code=f"{label}_DOCUMENT_PROGRESS_UNAVAILABLE",
        mismatch_code=f"{label}_DOCUMENT_PROGRESS_SHA_MISMATCH",
        invalid_code=f"{label}_DOCUMENT_PROGRESS_INVALID",
    )
    _receipt_raw, receipt = _read_bound_json(
        document_root / "receipt.json",
        expected_receipt_sha256,
        unavailable_code=f"{label}_DOCUMENT_RECEIPT_UNAVAILABLE",
        mismatch_code=f"{label}_DOCUMENT_RECEIPT_SHA_MISMATCH",
        invalid_code=f"{label}_DOCUMENT_RECEIPT_INVALID",
    )
    page_input_raw = _read_regular(document_root / "page-input.json", f"{label}_PAGE_INPUT_UNAVAILABLE")
    if sha256_bytes(page_input_raw) != expected_page_input_sha256:
        raise DispatcherError(f"{label}_PAGE_INPUT_SHA_MISMATCH")
    try:
        page_input = json.loads(page_input_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError(f"{label}_PAGE_INPUT_INVALID") from None
    if (
        not isinstance(page_input, dict)
        or page_input.get("schema") != "v4.pdf_research_simple_batch.page_input.v1"
        or page_input.get("document_id") != document_id
        or page_input.get("pdf_sha256") != document_id
        or page_input.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or not isinstance(page_input.get("pages"), list)
        or not page_input["pages"]
    ):
        raise DispatcherError(f"{label}_PAGE_INPUT_BINDING_INVALID")
    requests = progress.get("model_requests")
    receipt_requests = receipt.get("model_request_count")
    report_ref = receipt.get("report")
    if (
        progress.get("document_id") != document_id
        or progress.get("pdf_sha256") != document_id
        or progress.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or progress.get("status") != expected_status
        or progress.get("page_input_sha256") != expected_page_input_sha256
        or receipt.get("schema") != "v4.pdf_research_simple_batch.document_receipt.v1"
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or receipt.get("status") != expected_status
        or receipt.get("page_input", {}).get("sha256") != expected_page_input_sha256
        or any(
            receipt.get(key) is not expected
            for key, expected in (
                ("research_only", True),
                ("production_allowed", False),
                ("buy_gate_updated", False),
                ("orders_sent", False),
            )
        )
        or (expected_model_requests is not None and requests != expected_model_requests)
        or (expected_model_requests is not None and receipt_requests != expected_model_requests)
    ):
        raise DispatcherError(f"{label}_DOCUMENT_OUTPUT_BINDING_INVALID")
    if expected_report_sha256 is None:
        if report_ref is not None or (document_root / "report.md").exists():
            raise DispatcherError(f"{label}_UNEXPECTED_REPORT_PRESENT")
        report_sha256 = None
    else:
        if not isinstance(report_ref, dict) or report_ref.get("sha256") != expected_report_sha256:
            raise DispatcherError(f"{label}_REPORT_RECEIPT_BINDING_INVALID")
        report_raw = _read_regular(document_root / "report.md", f"{label}_REPORT_UNAVAILABLE")
        report_sha256 = sha256_bytes(report_raw)
        if report_sha256 != expected_report_sha256 or report_ref.get("bytes") != len(report_raw):
            raise DispatcherError(f"{label}_REPORT_SHA_MISMATCH")
    return {
        "status": expected_status,
        "progress_sha256": expected_progress_sha256,
        "receipt_sha256": expected_receipt_sha256,
        "page_input_sha256": expected_page_input_sha256,
        "report_sha256": report_sha256,
        "model_requests": requests,
    }


def _verify_queue_state(
    *,
    state_root: Path,
    expected_sha256: str,
    expected_job_count: int,
    expected_status_counts: Mapping[str, int],
    selected_document_ids: set[str],
    label: str,
) -> dict[str, Any]:
    _raw, queue = _read_bound_json(
        state_root / "queue" / "queue-state.json",
        expected_sha256,
        unavailable_code=f"{label}_QUEUE_UNAVAILABLE",
        mismatch_code=f"{label}_QUEUE_SHA_MISMATCH",
        invalid_code=f"{label}_QUEUE_INVALID",
    )
    jobs = queue.get("jobs")
    if (
        queue.get("schema") != "v4.announcement-engine-queue/v1"
        or not isinstance(jobs, dict)
        or len(jobs) != expected_job_count
    ):
        raise DispatcherError(f"{label}_QUEUE_BINDING_INVALID")
    observed_counts: dict[str, int] = {}
    for key, job in jobs.items():
        identity = job.get("identity") if isinstance(job, dict) else None
        article_id = identity.get("article_id") if isinstance(identity, dict) else None
        if (
            not isinstance(job, dict)
            or job.get("idempotency_key") != key
            or job.get("queue_id") != "v4-pdf-simple-batch"
            or job.get("model_id") != "qwen3_8_flash_next"
            or job.get("attempt_count") != 1
            or job.get("max_attempts") != 1
            or not isinstance(job.get("attempts"), list)
            or len(job["attempts"]) != 1
            or not isinstance(article_id, str)
            or not any(article_id.startswith(f"{document_id}:") for document_id in selected_document_ids)
        ):
            raise DispatcherError(f"{label}_QUEUE_JOB_BINDING_INVALID")
        status = job.get("status")
        observed_counts[status] = observed_counts.get(status, 0) + 1
    if observed_counts != dict(expected_status_counts):
        raise DispatcherError(f"{label}_QUEUE_STATUS_COUNTS_INVALID")
    return {"queue_sha256": expected_sha256, "job_count": expected_job_count, "status_counts": observed_counts}


def _verify_three_document_canary_completions(
    manifest_documents: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Fold the three frozen canary documents from their exact receipts into current status."""
    plan_raw, plan = _read_bound_json(
        THREE_DOCUMENT_CANARY_PLAN_PATH,
        THREE_DOCUMENT_CANARY_PLAN_SHA256,
        unavailable_code="THREE_DOCUMENT_CANARY_PLAN_UNAVAILABLE",
        mismatch_code="THREE_DOCUMENT_CANARY_PLAN_SHA_MISMATCH",
        invalid_code="THREE_DOCUMENT_CANARY_PLAN_INVALID",
    )
    selected = plan.get("selected_documents")
    if (
        plan.get("continuation_id") != THREE_DOCUMENT_CANARY_CONTINUATION_ID
        or plan.get("manifest_sha256") != manifest_sha256
        or plan.get("state_root") != str(THREE_DOCUMENT_CANARY_STATE_ROOT)
        or plan.get("expected_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or plan.get("observed_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or not isinstance(selected, list)
        or [row.get("document_id") for row in selected if isinstance(row, dict)] != list(THREE_DOCUMENT_CANARY_IDS)
        or any(
            not isinstance(row, dict)
            or row.get("prior_status") != "UNPROCESSED"
            or row.get("source_sha256") != row.get("document_id")
            for row in selected
        )
        or plan.get("research_only") != {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    ):
        raise DispatcherError("THREE_DOCUMENT_CANARY_PLAN_BINDING_INVALID")
    validated = batch.validate_continuation_plan(
        THREE_DOCUMENT_CANARY_PLAN_PATH,
        manifest_sha256=manifest_sha256,
        documents=manifest_documents,
    )
    if validated.get("plan_sha256") != THREE_DOCUMENT_CANARY_PLAN_SHA256:
        raise DispatcherError("THREE_DOCUMENT_CANARY_PLAN_VALIDATION_MISMATCH")
    _progress_raw, run_progress = _read_bound_json(
        THREE_DOCUMENT_CANARY_STATE_ROOT / "run-progress.json",
        THREE_DOCUMENT_CANARY_PROGRESS_SHA256,
        unavailable_code="THREE_DOCUMENT_CANARY_PROGRESS_UNAVAILABLE",
        mismatch_code="THREE_DOCUMENT_CANARY_PROGRESS_SHA_MISMATCH",
        invalid_code="THREE_DOCUMENT_CANARY_PROGRESS_INVALID",
    )
    rows = run_progress.get("documents")
    if (
        run_progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
        or run_progress.get("continuation_id") != THREE_DOCUMENT_CANARY_CONTINUATION_ID
        or run_progress.get("continuation_plan_sha256") != THREE_DOCUMENT_CANARY_PLAN_SHA256
        or run_progress.get("manifest_sha256") != manifest_sha256
        or run_progress.get("model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
        or run_progress.get("research_only") is not True
        or run_progress.get("production_allowed") is not False
        or run_progress.get("buy_gate_updated") is not False
        or run_progress.get("orders_sent") is not False
        or not isinstance(rows, list)
        or len(rows) != len(THREE_DOCUMENT_CANARY_IDS)
    ):
        raise DispatcherError("THREE_DOCUMENT_CANARY_PROGRESS_BINDING_INVALID")
    run_statuses = {
        row.get("document_id"): row.get("status")
        for row in rows
        if isinstance(row, dict)
    }
    if run_statuses != {document_id: binding["status"] for document_id, binding in THREE_DOCUMENT_ORIGINAL_BINDINGS.items()}:
        raise DispatcherError("THREE_DOCUMENT_CANARY_DOCUMENT_STATUS_MISMATCH")
    _verify_queue_state(
        state_root=THREE_DOCUMENT_CANARY_STATE_ROOT,
        expected_sha256=THREE_DOCUMENT_CANARY_QUEUE_SHA256,
        expected_job_count=4,
        expected_status_counts={"FAILED": 2, "SUCCEEDED": 2},
        selected_document_ids=set(THREE_DOCUMENT_CANARY_IDS),
        label="THREE_DOCUMENT_CANARY",
    )

    outputs: dict[str, Any] = {}
    for document_id, binding in THREE_DOCUMENT_ORIGINAL_BINDINGS.items():
        outputs[document_id] = _verify_document_output(
            state_root=THREE_DOCUMENT_CANARY_STATE_ROOT,
            document_id=document_id,
            expected_status=binding["status"],
            expected_progress_sha256=binding["progress_sha256"],
            expected_receipt_sha256=binding["receipt_sha256"],
            expected_page_input_sha256=binding["page_input_sha256"],
            expected_report_sha256=binding["report_sha256"],
            expected_model_requests=1 if binding["status"] in SUCCESS_STATUSES else None,
            label="THREE_DOCUMENT_CANARY",
        )

    recovery_specs = (
        {
            "document_id": THREE_DOCUMENT_CANARY_IDS[1],
            "plan_path": PPI_RECOVERY_PLAN_PATH,
            "plan_sha256": PPI_RECOVERY_PLAN_SHA256,
            "state_root": PPI_RECOVERY_STATE_ROOT,
            "continuation_id": PPI_RECOVERY_CONTINUATION_ID,
            "progress_sha256": PPI_RECOVERY_PROGRESS_SHA256,
            "document_progress_sha256": PPI_RECOVERY_DOCUMENT_PROGRESS_SHA256,
            "receipt_sha256": PPI_RECOVERY_RECEIPT_SHA256,
            "page_input_sha256": PPI_RECOVERY_PAGE_INPUT_SHA256,
            "report_sha256": PPI_RECOVERY_REPORT_SHA256,
            "queue_sha256": PPI_RECOVERY_QUEUE_SHA256,
            "model_requests": 2,
            "queue_job_count": 2,
        },
        {
            "document_id": THREE_DOCUMENT_CANARY_IDS[2],
            "plan_path": AI_VIDEO_RECOVERY_PLAN_PATH,
            "plan_sha256": AI_VIDEO_RECOVERY_PLAN_SHA256,
            "state_root": AI_VIDEO_RECOVERY_STATE_ROOT,
            "continuation_id": AI_VIDEO_RECOVERY_CONTINUATION_ID,
            "progress_sha256": AI_VIDEO_RECOVERY_PROGRESS_SHA256,
            "document_progress_sha256": AI_VIDEO_RECOVERY_DOCUMENT_PROGRESS_SHA256,
            "receipt_sha256": AI_VIDEO_RECOVERY_RECEIPT_SHA256,
            "page_input_sha256": AI_VIDEO_RECOVERY_PAGE_INPUT_SHA256,
            "report_sha256": AI_VIDEO_RECOVERY_REPORT_SHA256,
            "queue_sha256": AI_VIDEO_RECOVERY_QUEUE_SHA256,
            "model_requests": 1,
            "queue_job_count": 1,
        },
    )
    for spec in recovery_specs:
        _, recovery_plan = _read_bound_json(
            spec["plan_path"],
            spec["plan_sha256"],
            unavailable_code="THREE_DOCUMENT_RECOVERY_PLAN_UNAVAILABLE",
            mismatch_code="THREE_DOCUMENT_RECOVERY_PLAN_SHA_MISMATCH",
            invalid_code="THREE_DOCUMENT_RECOVERY_PLAN_INVALID",
        )
        recovery_selected = recovery_plan.get("selected_documents")
        if (
            recovery_plan.get("continuation_id") != spec["continuation_id"]
            or recovery_plan.get("state_root") != str(spec["state_root"])
            or recovery_plan.get("expected_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
            or recovery_plan.get("observed_model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
            or not isinstance(recovery_selected, list)
            or len(recovery_selected) != 1
            or not isinstance(recovery_selected[0], dict)
            or recovery_selected[0].get("document_id") != spec["document_id"]
        ):
            raise DispatcherError("THREE_DOCUMENT_RECOVERY_PLAN_BINDING_INVALID")
        recovery_validated = batch.validate_continuation_plan(
            spec["plan_path"],
            manifest_sha256=manifest_sha256,
            documents=manifest_documents,
        )
        if recovery_validated.get("plan_sha256") != spec["plan_sha256"]:
            raise DispatcherError("THREE_DOCUMENT_RECOVERY_PLAN_VALIDATION_MISMATCH")
        _run_raw, recovery_run = _read_bound_json(
            spec["state_root"] / "run-progress.json",
            spec["progress_sha256"],
            unavailable_code="THREE_DOCUMENT_RECOVERY_PROGRESS_UNAVAILABLE",
            mismatch_code="THREE_DOCUMENT_RECOVERY_PROGRESS_SHA_MISMATCH",
            invalid_code="THREE_DOCUMENT_RECOVERY_PROGRESS_INVALID",
        )
        if (
            recovery_run.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
            or recovery_run.get("continuation_id") != spec["continuation_id"]
            or recovery_run.get("continuation_plan_sha256") != spec["plan_sha256"]
            or recovery_run.get("manifest_sha256") != manifest_sha256
            or recovery_run.get("model_settings_sha256") != EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256
            or not isinstance(recovery_run.get("documents"), list)
            or len(recovery_run["documents"]) != 1
            or not isinstance(recovery_run["documents"][0], dict)
            or recovery_run["documents"][0].get("document_id") != spec["document_id"]
            or recovery_run["documents"][0].get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
        ):
            raise DispatcherError("THREE_DOCUMENT_RECOVERY_PROGRESS_BINDING_INVALID")
        outputs[spec["document_id"]] = _verify_document_output(
            state_root=spec["state_root"],
            document_id=spec["document_id"],
            expected_status="MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
            expected_progress_sha256=spec["document_progress_sha256"],
            expected_receipt_sha256=spec["receipt_sha256"],
            expected_page_input_sha256=spec["page_input_sha256"],
            expected_report_sha256=spec["report_sha256"],
            expected_model_requests=spec["model_requests"],
            label="THREE_DOCUMENT_RECOVERY",
        )
        _verify_queue_state(
            state_root=spec["state_root"],
            expected_sha256=spec["queue_sha256"],
            expected_job_count=spec["queue_job_count"],
            expected_status_counts={"SUCCEEDED": spec["queue_job_count"]},
            selected_document_ids={spec["document_id"]},
            label="THREE_DOCUMENT_RECOVERY",
        )

    return {
        "continuation_id": THREE_DOCUMENT_CANARY_CONTINUATION_ID,
        "plan_sha256": sha256_bytes(plan_raw),
        "progress_sha256": THREE_DOCUMENT_CANARY_PROGRESS_SHA256,
        "queue_sha256": THREE_DOCUMENT_CANARY_QUEUE_SHA256,
        "documents": outputs,
        "recovery_plans": {
            PPI_RECOVERY_CONTINUATION_ID: PPI_RECOVERY_PLAN_SHA256,
            AI_VIDEO_RECOVERY_CONTINUATION_ID: AI_VIDEO_RECOVERY_PLAN_SHA256,
        },
    }


def load_current_completion_statuses(
    manifest_documents: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Load frozen inventory states and fold in receipt-bound canary results."""
    raw = _read_regular(REMAINING_INVENTORY_PATH, "REMAINING_INVENTORY_UNAVAILABLE")
    if sha256_bytes(raw) != EXPECTED_REMAINING_INVENTORY_SHA256:
        raise DispatcherError("REMAINING_INVENTORY_SHA_MISMATCH")
    try:
        inventory = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("REMAINING_INVENTORY_INVALID") from None
    if not isinstance(inventory, dict) or inventory.get("schema") != "v4.pdf_tool_enabled_completion.remaining_core_inventory.v1":
        raise DispatcherError("REMAINING_INVENTORY_SCHEMA_INVALID")
    frozen = inventory.get("frozen_cohort")
    summary = inventory.get("summary")
    completed_rows = inventory.get("completed")
    outstanding_rows = inventory.get("outstanding")
    if (
        not isinstance(frozen, dict)
        or frozen.get("manifest_sha256") != manifest_sha256
        or manifest_sha256 != EXPECTED_MANIFEST_SHA256
        or frozen.get("document_count") != FROZEN_COHORT_DOCUMENT_COUNT
        or not isinstance(summary, dict)
        or summary.get("completed_count") != PRESERVED_COMPLETED_DOCUMENT_COUNT
        or summary.get("outstanding_count") != PRE_CANARY_OUTSTANDING_DOCUMENT_COUNT
        or summary.get("unique_document_count") != FROZEN_COHORT_DOCUMENT_COUNT
        or not isinstance(completed_rows, list)
        or len(completed_rows) != PRESERVED_COMPLETED_DOCUMENT_COUNT
        or not isinstance(outstanding_rows, list)
        or len(outstanding_rows) != PRE_CANARY_OUTSTANDING_DOCUMENT_COUNT
        or len(manifest_documents) != FROZEN_COHORT_DOCUMENT_COUNT
    ):
        raise DispatcherError("REMAINING_INVENTORY_BINDING_INVALID")
    manifest_by_id = {
        str(document.get("document_id")): document
        for document in manifest_documents
        if isinstance(document, Mapping)
    }
    if len(manifest_by_id) != FROZEN_COHORT_DOCUMENT_COUNT:
        raise DispatcherError("MANIFEST_DOCUMENT_IDS_INVALID")
    statuses: dict[str, str] = {}
    for bucket, allowed_statuses, rows in (
        ("completed", COMPLETED_INVENTORY_STATUSES, completed_rows),
        ("outstanding", OUTSTANDING_INVENTORY_STATUSES, outstanding_rows),
    ):
        for row in rows:
            if not isinstance(row, dict):
                raise DispatcherError("REMAINING_INVENTORY_ROW_INVALID")
            document_id = row.get("document_id")
            status = row.get("actual_prior_status")
            document = manifest_by_id.get(str(document_id))
            if (
                not isinstance(document_id, str)
                or not SHA256_RE.fullmatch(document_id)
                or document_id in statuses
                or status not in allowed_statuses
                or document is None
                or document.get("pdf_sha256") != document_id
            ):
                raise DispatcherError(f"REMAINING_INVENTORY_{bucket.upper()}_ROW_INVALID")
            statuses[document_id] = status
    if set(statuses) != set(manifest_by_id):
        raise DispatcherError("REMAINING_INVENTORY_PARTITION_MISMATCH")

    # Keep the immutable inventory view separate from the live reconciled
    # statuses below. Exact receipts may legitimately advance a document that
    # was failed or unprocessed in the frozen inventory; the source history
    # check must compare against that historical view, not the receipt-updated
    # execution view.
    frozen_inventory_statuses = dict(statuses)

    if statuses.get(QUARANTINE_DOCUMENT_ID) != "UNPROCESSED":
        raise DispatcherError("QUARANTINE_STATUS_BINDING_MISMATCH")
    if statuses.get(TOOL_CANARY_DOCUMENT_ID) != "FAILED_NO_RETRY":
        raise DispatcherError("TOOL_CANARY_PRIOR_STATUS_MISMATCH")

    terminal_receipts: dict[str, dict[str, Any]] = {}
    for document_id, (path, expected_sha256) in TERMINAL_RECEIPT_BINDINGS.items():
        row = next((item for item in completed_rows if item.get("document_id") == document_id), None)
        if (
            not isinstance(row, dict)
            or row.get("actual_prior_status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
            or row.get("status_source") != "remaining2056_stop_terminal_receipt"
            or row.get("receipt_path") is not None
        ):
            raise DispatcherError("TERMINAL_COMPLETION_INVENTORY_BINDING_INVALID")
        terminal_receipts[document_id] = _verify_terminal_receipt(document_id, path, expected_sha256)
    referenced_terminal_ids = {
        row.get("document_id")
        for row in completed_rows
        if isinstance(row, dict) and row.get("status_source") == "remaining2056_stop_terminal_receipt"
    }
    if referenced_terminal_ids != set(TERMINAL_RECEIPT_BINDINGS):
        raise DispatcherError("TERMINAL_COMPLETION_RECEIPT_SET_MISMATCH")

    canary_receipt = _verify_current_tool_canary_completion()
    statuses[TOOL_CANARY_DOCUMENT_ID] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    three_document_canary = _verify_three_document_canary_completions(
        manifest_documents,
        manifest_sha256=manifest_sha256,
    )
    for document_id, binding in THREE_DOCUMENT_ORIGINAL_BINDINGS.items():
        if statuses.get(document_id) != "UNPROCESSED":
            raise DispatcherError("THREE_DOCUMENT_CANARY_PRIOR_STATUS_MISMATCH")
        statuses[document_id] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    completed_count = sum(status in COMPLETED_INVENTORY_STATUSES for status in statuses.values())
    outstanding_count = len(statuses) - completed_count
    outstanding_status_counts: dict[str, int] = {}
    for status in statuses.values():
        if status not in COMPLETED_INVENTORY_STATUSES:
            outstanding_status_counts[status] = outstanding_status_counts.get(status, 0) + 1
    unprocessed_count = outstanding_status_counts.get("UNPROCESSED", 0)
    if (
        completed_count != CURRENT_COMPLETED_DOCUMENT_COUNT
        or outstanding_count != CURRENT_OUTSTANDING_DOCUMENT_COUNT
        or outstanding_status_counts.get("FAILED_DOCUMENT_ISOLATED") != 2
        or outstanding_status_counts.get("FAILED_NO_RETRY") != 59
        or outstanding_status_counts.get("SOURCE_REPAIR_FAILED_NO_MODEL") != 7
        or unprocessed_count != 2051
        or unprocessed_count - 1 != REMAINING_UNPROCESSED_RUNNABLE_COUNT
        or outstanding_count - 1 != REMAINING_NONQUARANTINED_DOCUMENT_COUNT
    ):
        raise DispatcherError("CURRENT_COMPLETION_COUNTS_MISMATCH")
    return statuses, {
        "inventory_sha256": EXPECTED_REMAINING_INVENTORY_SHA256,
        "frozen_inventory_statuses": frozen_inventory_statuses,
        "completed_count": completed_count,
        "outstanding_count": outstanding_count,
        "outstanding_status_counts": outstanding_status_counts,
        "runnable_unprocessed_count": unprocessed_count - 1,
        "quarantine_document_id": QUARANTINE_DOCUMENT_ID,
        "terminal_receipts": terminal_receipts,
        "current_tool_canary": canary_receipt,
        "three_document_canary": three_document_canary,
    }


def select_next_document(
    documents: Sequence[Mapping[str, Any]],
    status_by_id: Mapping[str, str],
    pilot_ids: set[str],
    dispatched_ids: set[str],
    prepared_rows: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, int]:
    if (
        len(documents) != FROZEN_COHORT_DOCUMENT_COUNT
        or len(status_by_id) != FROZEN_COHORT_DOCUMENT_COUNT
        or len(pilot_ids) not in {0, PILOT_DOCUMENT_COUNT}
    ):
        raise DispatcherError("COHORT_INPUT_COUNTS_INVALID")
    document_ids = [str(row.get("document_id", "")) for row in documents]
    if len(set(document_ids)) != FROZEN_COHORT_DOCUMENT_COUNT or set(document_ids) != set(status_by_id):
        raise DispatcherError("COHORT_STATUS_PARTITION_INVALID")
    if QUARANTINE_DOCUMENT_ID not in set(document_ids):
        raise DispatcherError("QUARANTINE_POSITION_BINDING_MISMATCH")
    if any(status_by_id.get(document_id) not in COMPLETED_INVENTORY_STATUSES for document_id in pilot_ids):
        raise DispatcherError("PILOT_COMPLETION_STATUS_MISMATCH")
    excluded = set(pilot_ids) | set(dispatched_ids) | {QUARANTINE_DOCUMENT_ID}
    eligible: list[Mapping[str, Any]] = []
    for row in documents:
        document_id = str(row.get("document_id", ""))
        status = status_by_id[document_id]
        if status not in COMPLETED_INVENTORY_STATUSES | OUTSTANDING_INVENTORY_STATUSES:
            raise DispatcherError("COHORT_STATUS_UNKNOWN")
        if document_id in excluded or status in COMPLETED_INVENTORY_STATUSES:
            continue
        if prepared_rows is not None:
            prepared = prepared_rows.get(document_id)
            if not isinstance(prepared, Mapping) or prepared.get("manifest_row", {}).get("status") != "READY":
                continue
        # Failure statuses remain visible in the frozen inventory, but the
        # runner accepts only UNPROCESSED or a separately proven recovery plan.
        if status == "UNPROCESSED":
            eligible.append(row)
    if not eligible:
        return None, 0
    return dict(eligible[0]), len(eligible)


def validate_unprocessed_selection(
    document_ids: Sequence[str],
    documents: Sequence[Mapping[str, Any]],
    status_by_id: Mapping[str, str],
    *,
    expected_count: int,
) -> list[dict[str, Any]]:
    if type(expected_count) is not int or len(document_ids) != expected_count:
        raise DispatcherError("FROZEN_SELECTION_COUNT_INVALID")
    if len(set(document_ids)) != len(document_ids):
        raise DispatcherError("FROZEN_SELECTION_DUPLICATE_DOCUMENT")
    manifest_by_id = {str(row.get("document_id")): row for row in documents}
    if len(manifest_by_id) != len(documents):
        raise DispatcherError("MANIFEST_DOCUMENT_IDS_INVALID")
    selected: list[dict[str, Any]] = []
    for document_id in document_ids:
        row = manifest_by_id.get(document_id)
        if (
            not SHA256_RE.fullmatch(document_id)
            or row is None
            or row.get("pdf_sha256") != document_id
            or status_by_id.get(document_id) != "UNPROCESSED"
            or document_id in {QUARANTINE_DOCUMENT_ID, TOOL_CANARY_DOCUMENT_ID}
        ):
            raise DispatcherError("FROZEN_SELECTION_DOCUMENT_NOT_RUNNABLE")
        selected.append(dict(row))
    return selected


def build_singleton_plan(
    document: Mapping[str, Any],
    *,
    manifest_sha256: str,
    prior_progress_sha256: str,
    model_settings_sha256: str,
    continuation_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    return build_unprocessed_continuation_plan(
        [document],
        manifest_sha256=manifest_sha256,
        prior_progress_sha256=prior_progress_sha256,
        model_settings_sha256=model_settings_sha256,
        continuation_id=continuation_id,
    )


def build_unprocessed_continuation_plan(
    documents: Sequence[Mapping[str, Any]],
    *,
    manifest_sha256: str,
    prior_progress_sha256: str,
    model_settings_sha256: str,
    continuation_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    continuation_id = continuation_id or f"resume-{uuid.uuid4().hex}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", continuation_id):
        raise DispatcherError("CONTINUATION_ID_INVALID")
    if not 1 <= len(documents) <= batch.CONTINUATION_MAX_DOCUMENTS:
        raise DispatcherError("CONTINUATION_SELECTION_COUNT_INVALID")
    selected_documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for document in documents:
        document_id = document.get("document_id")
        source_sha = document.get("pdf_sha256")
        if (
            not isinstance(document_id, str)
            or document_id in seen
            or document_id != source_sha
            or not SHA256_RE.fullmatch(document_id)
        ):
            raise DispatcherError("MANIFEST_DOCUMENT_ID_INVALID")
        seen.add(document_id)
        selected_documents.append(
            {"document_id": document_id, "prior_status": "UNPROCESSED", "source_sha256": source_sha}
        )
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
        "selected_documents": selected_documents,
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
        "prepared_text_manifest_sha256": context["prepared_text_manifest_sha256"],
        "original_progress_sha256": ORIGINAL_PROGRESS_SHA256,
        "pilot_progress_sha256": context["pilot_progress_sha256"],
        "model_settings_sha256": context["authorization"]["model_settings_sha256"],
    }


def _halt_resume_descriptor(context: Mapping[str, Any], journal: DurableJournal) -> dict[str, Any] | None:
    adoption = context.get("adoption_evidence")
    if not isinstance(adoption, Mapping):
        return None
    descriptor = adoption.get("halt_resume")
    if descriptor is None:
        return None
    if not isinstance(descriptor, dict) or set(descriptor) != HALT_RESUME_DESCRIPTOR_FIELDS:
        raise DispatcherError("HALT_RESUME_DESCRIPTOR_INVALID")
    hash_fields = {
        "previous_authorization_sha256",
        "journal_prefix_sha256",
        "reconciled_event_line_sha256",
        "halt_event_line_sha256",
        "plan_sha256",
        "receipt_sha256",
        "run_progress_sha256",
        "document_progress_sha256",
        "page_input_sha256",
        "queue_key",
        "queue_state_sha256",
        "job_input_sha256",
        "stream_receipt_sha256",
        "request_input_sha256",
        "raw_sse_sha256",
        "resource_samples_prefix_sha256",
        "failed_resource_sample_line_sha256",
        "old_dispatcher_sha256",
        "old_runner_sha256",
        "new_dispatcher_sha256",
        "new_runner_sha256",
        "reviewer_receipt_sha256",
    }
    if (
        any(not isinstance(descriptor.get(key), str) or not SHA256_RE.fullmatch(descriptor[key]) for key in hash_fields)
        or descriptor.get("schema") != HALT_RESUME_SCHEMA
        or descriptor.get("status") != "ROOT_ADOPTED"
        or descriptor.get("authorization_id") != context["authorization"].get("authorization_id")
        or type(descriptor.get("recovery_generation")) is not int
        or descriptor.get("recovery_generation") != 1
        or type(descriptor.get("journal_event_count")) is not int
        or descriptor["journal_event_count"] < 2
        or type(descriptor.get("reconciled_event_index")) is not int
        or type(descriptor.get("halt_event_index")) is not int
        or type(descriptor.get("resource_samples_prefix_bytes")) is not int
        or descriptor["resource_samples_prefix_bytes"] < 0
        or not isinstance(descriptor.get("document_id"), str)
        or not SHA256_RE.fullmatch(descriptor["document_id"])
        or not isinstance(descriptor.get("continuation_id"), str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", descriptor["continuation_id"])
        or not isinstance(descriptor.get("journal_path"), str)
        or not isinstance(descriptor.get("resource_samples_path"), str)
    ):
        raise DispatcherError("HALT_RESUME_DESCRIPTOR_INVALID")
    auth = context["authorization"]
    current_dispatcher_sha = sha256_bytes(Path(__file__).read_bytes())
    current_runner_sha = sha256_bytes((PROJECT_ROOT / "ops/run_pdf_research_batch.py").read_bytes())
    reviewer_ref = auth.get("reviewer_receipt")
    if (
        auth.get("max_documents") != EXPECTED_POST_PILOT_COHORT
        or descriptor.get("new_dispatcher_sha256") != current_dispatcher_sha
        or descriptor.get("new_dispatcher_sha256") != auth.get("dispatcher_sha256")
        or descriptor.get("new_runner_sha256") != current_runner_sha
        or descriptor.get("new_runner_sha256") != EXPECTED_RUNNER_SHA256
        or not isinstance(reviewer_ref, Mapping)
        or descriptor.get("reviewer_receipt_sha256") != reviewer_ref.get("sha256")
        or Path(descriptor["journal_path"]).expanduser().absolute() != journal.path.expanduser().absolute()
        or Path(descriptor["resource_samples_path"]).expanduser().absolute()
        != (journal.root / "resource-samples.jsonl").expanduser().absolute()
    ):
        raise DispatcherError("HALT_RESUME_CODE_OR_PATH_BINDING_MISMATCH")

    old_auth_path = _safe_reference(descriptor.get("previous_authorization_path"), root=CONTINUATION_ROOT)
    old_auth_raw = _read_regular(old_auth_path, "HALT_RESUME_PREVIOUS_AUTHORIZATION_UNAVAILABLE")
    if sha256_bytes(old_auth_raw) != descriptor["previous_authorization_sha256"]:
        raise DispatcherError("HALT_RESUME_PREVIOUS_AUTHORIZATION_SHA_MISMATCH")
    try:
        old_auth = json.loads(old_auth_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise DispatcherError("HALT_RESUME_PREVIOUS_AUTHORIZATION_INVALID") from None
    if (
        not isinstance(old_auth, dict)
        or old_auth.get("schema") != AUTHORIZATION_SCHEMA
        or old_auth.get("status") != "AUTHORIZED"
        or old_auth.get("authorization_id") != auth.get("authorization_id")
        or old_auth.get("max_documents") != auth.get("max_documents")
        or old_auth.get("scope_sha256") != auth.get("scope_sha256")
        or old_auth.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or old_auth.get("runner_sha256") != descriptor.get("old_runner_sha256")
        or old_auth.get("dispatcher_sha256") != descriptor.get("old_dispatcher_sha256")
        or not isinstance(old_auth.get("model_settings_sha256"), str)
        or old_auth.get("model_settings_sha256") != auth.get("model_settings_sha256")
    ):
        raise DispatcherError("HALT_RESUME_PREVIOUS_AUTHORIZATION_BINDING_MISMATCH")

    journal_raw = _read_regular(journal.path, "DISPATCH_JOURNAL_UNREADABLE")
    if journal_raw and not journal_raw.endswith(b"\n"):
        raise DispatcherError("DISPATCH_JOURNAL_TRUNCATED")
    lines = journal_raw.splitlines(keepends=True)
    count = descriptor["journal_event_count"]
    if (
        len(lines) < count
        or sha256_bytes(b"".join(lines[:count])) != descriptor.get("journal_prefix_sha256")
        or descriptor.get("reconciled_event_index") != count - 2
        or descriptor.get("halt_event_index") != count - 1
        or len(journal.events) != len(lines)
    ):
        raise DispatcherError("HALT_RESUME_JOURNAL_PREFIX_MISMATCH")
    old_events = journal.events[:count]
    if (
        sha256_bytes(lines[count - 2]) != descriptor.get("reconciled_event_line_sha256")
        or sha256_bytes(lines[count - 1]) != descriptor.get("halt_event_line_sha256")
    ):
        raise DispatcherError("HALT_RESUME_TERMINAL_EVENT_SHA_MISMATCH")
    prior_binding = {key: value for key, value in old_events[0].items() if key != "at_utc"}
    failed = old_events[count - 2]
    halt = old_events[count - 1]
    if (
        prior_binding.get("event") != "binding"
        or prior_binding.get("authorization_id") != auth.get("authorization_id")
        or prior_binding.get("authorization_sha256") != descriptor.get("previous_authorization_sha256")
        or prior_binding.get("runner_sha256") != descriptor.get("old_runner_sha256")
        or prior_binding.get("scope_sha256") != EXPECTED_SCOPE_SHA256
        or failed.get("event") != "reconciled"
        or failed.get("document_id") != descriptor.get("document_id")
        or failed.get("continuation_id") != descriptor.get("continuation_id")
        or failed.get("decision") != "HALT"
        or failed.get("status") != "FAILED_NO_RETRY"
        or failed.get("plan_sha256") != descriptor.get("plan_sha256")
        or failed.get("receipt_sha256") != descriptor.get("receipt_sha256")
        or failed.get("progress_sha256") != descriptor.get("run_progress_sha256")
        or failed.get("model_request_count") != 1
        or failed.get("returncode") != 0
        or failed.get("resource_stop_reason") is not None
        or halt.get("event") != "halt"
        or halt.get("reason") != "FAILED_NO_RETRY"
        or halt.get("document_id") != descriptor.get("document_id")
    ):
        raise DispatcherError("HALT_RESUME_TERMINAL_BINDING_MISMATCH")

    plan_events = [
        (index, event)
        for index, event in enumerate(old_events[:count - 2])
        if event.get("event") == "plan_created"
        and event.get("document_id") == descriptor["document_id"]
        and event.get("continuation_id") == descriptor["continuation_id"]
        and event.get("plan_sha256") == descriptor["plan_sha256"]
    ]
    if len(plan_events) != 1:
        raise DispatcherError("HALT_RESUME_PLAN_EVENT_MISMATCH")
    plan_index, plan_event = plan_events[0]
    try:
        plan_raw = base64.b64decode(plan_event.get("plan_bytes_b64", ""), validate=True)
        plan = json.loads(plan_raw.decode("utf-8"))
    except (ValueError, base64.binascii.Error, UnicodeError, json.JSONDecodeError):
        raise DispatcherError("HALT_RESUME_PLAN_EVENT_INVALID") from None
    if (
        sha256_bytes(plan_raw) != descriptor["plan_sha256"]
        or plan.get("continuation_id") != descriptor["continuation_id"]
        or plan.get("state_root") != plan_event.get("state_root")
        or plan_event.get("plan_path") != str(journal.root / "plans" / f"{descriptor['continuation_id']}.json")
        or plan_index + 3 != count - 2
        or old_events[plan_index + 1].get("event") != "plan_only_pass"
        or old_events[plan_index + 2].get("event") != "dispatch_intent"
        or any(
            prior_event.get("document_id") != descriptor["document_id"]
            or prior_event.get("continuation_id") != descriptor["continuation_id"]
            or prior_event.get("plan_sha256") != descriptor["plan_sha256"]
            or prior_event.get("state_root") != plan.get("state_root")
            for prior_event in (plan_event, old_events[plan_index + 1], old_events[plan_index + 2], failed)
        )
    ):
        raise DispatcherError("HALT_RESUME_PLAN_BINDING_MISMATCH")
    prior_state_root = Path(str(plan.get("state_root", ""))).expanduser().absolute()
    if _read_regular(prior_state_root / "continuation-plan.json", "HALT_RESUME_PLAN_UNAVAILABLE") != plan_raw:
        raise DispatcherError("HALT_RESUME_SAVED_PLAN_MISMATCH")
    selection = plan.get("selected_documents")
    document = next(
        (row for row in context.get("documents", []) if isinstance(row, Mapping) and row.get("document_id") == descriptor["document_id"]),
        None,
    )
    if not isinstance(selection, list) or len(selection) != 1 or not isinstance(document, Mapping):
        raise DispatcherError("HALT_RESUME_DOCUMENT_BINDING_MISMATCH")
    recovery_candidate = build_memory_recovery_plan(
        plan,
        plan_raw,
        document,
        model_settings_sha256=auth["model_settings_sha256"],
    )
    if recovery_candidate is None:
        raise DispatcherError("HALT_RESUME_PREFILL_EVIDENCE_UNAVAILABLE")
    _recovery_plan, _recovery_raw = recovery_candidate
    recovery = _recovery_plan["selected_documents"][0]["recovery"]
    artifacts = recovery["prior_artifact_sha256"]
    if (
        recovery["generation"] != descriptor["recovery_generation"]
        or recovery["prior_queue_idempotency_key"] != descriptor["queue_key"]
        or recovery["prior_document_receipt_sha256"] != descriptor["receipt_sha256"]
        or artifacts.get("run-progress.json") != descriptor["run_progress_sha256"]
        or artifacts.get(f"documents/{descriptor['document_id']}/progress.json") != descriptor["document_progress_sha256"]
        or artifacts.get(f"documents/{descriptor['document_id']}/page-input.json") != descriptor["page_input_sha256"]
        or artifacts.get("queue/queue-state.json") != descriptor["queue_state_sha256"]
        or artifacts.get(f"queue/jobs/{descriptor['queue_key']}/input.json") != descriptor["job_input_sha256"]
        or artifacts.get(f"evidence/streams/{descriptor['queue_key']}/attempt-0001/stream-receipt.json") != descriptor["stream_receipt_sha256"]
        or artifacts.get(f"evidence/streams/{descriptor['queue_key']}/attempt-0001/round-01.request-input.json") != descriptor["request_input_sha256"]
        or artifacts.get(f"evidence/streams/{descriptor['queue_key']}/attempt-0001/round-01.raw.sse") != descriptor["raw_sse_sha256"]
    ):
        raise DispatcherError("HALT_RESUME_FAILURE_CHAIN_MISMATCH")

    samples_path = Path(descriptor["resource_samples_path"]).expanduser().absolute()
    samples_raw = _read_regular(samples_path, "HALT_RESUME_RESOURCE_SAMPLES_UNAVAILABLE")
    prefix_bytes = descriptor["resource_samples_prefix_bytes"]
    if len(samples_raw) < prefix_bytes or sha256_bytes(samples_raw[:prefix_bytes]) != descriptor["resource_samples_prefix_sha256"]:
        raise DispatcherError("HALT_RESUME_RESOURCE_PREFIX_MISMATCH")
    prefix = samples_raw[:prefix_bytes]
    if prefix and not prefix.endswith(b"\n"):
        raise DispatcherError("HALT_RESUME_RESOURCE_PREFIX_TRUNCATED")
    matching_samples = []
    for line in prefix.splitlines(keepends=True):
        if sha256_bytes(line) == descriptor["failed_resource_sample_line_sha256"]:
            try:
                sample = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise DispatcherError("HALT_RESUME_RESOURCE_SAMPLE_INVALID") from None
            matching_samples.append(sample)
    if (
        len(matching_samples) != 1
        or not isinstance(matching_samples[0], dict)
        or matching_samples[0].get("phase") != "running"
        or type(matching_samples[0].get("available_bytes")) is not int
        or type(matching_samples[0].get("swap_used_bytes")) is not int
    ):
        raise DispatcherError("HALT_RESUME_FAILURE_RESOURCE_SAMPLE_MISMATCH")
    return {
        **descriptor,
        "prior_plan": plan,
        "prior_plan_raw": plan_raw,
        "prior_state_root": str(prior_state_root),
        "failure_sample": matching_samples[0],
        "recovery_plan": _recovery_plan,
        "recovery_raw": _recovery_raw,
    }


def _source_adoption_event(context: Mapping[str, Any], descriptor: Mapping[str, Any]) -> dict[str, Any]:
    adoption_ref = context["authorization"]["adoption_receipt"]
    return {
        "event": "source_adoption",
        "schema": JOURNAL_SCHEMA,
        "authorization_id": context["authorization"]["authorization_id"],
        "previous_authorization_sha256": descriptor["previous_authorization_sha256"],
        "authorization_sha256": context["authorization_sha256"],
        "adoption_receipt_sha256": adoption_ref["sha256"],
        "journal_prefix_sha256": descriptor["journal_prefix_sha256"],
        "journal_event_count": descriptor["journal_event_count"],
        "document_id": descriptor["document_id"],
        "plan_sha256": descriptor["plan_sha256"],
        "recovery_generation": descriptor["recovery_generation"],
        "old_dispatcher_sha256": descriptor["old_dispatcher_sha256"],
        "old_runner_sha256": descriptor["old_runner_sha256"],
        "new_dispatcher_sha256": descriptor["new_dispatcher_sha256"],
        "new_runner_sha256": descriptor["new_runner_sha256"],
        "prepared_text_manifest_sha256": context["prepared_text_manifest_sha256"],
    }


def _verify_or_create_binding(journal: DurableJournal, context: Mapping[str, Any]) -> None:
    binding = _event_binding(context)
    descriptor = _halt_resume_descriptor(context, journal)
    if not journal.events:
        if descriptor is not None:
            raise DispatcherError("HALT_RESUME_EXISTING_JOURNAL_REQUIRED")
        journal.append(binding)
        return
    observed = {key: value for key, value in journal.events[0].items() if key != "at_utc"}
    if observed == binding:
        if descriptor is not None:
            raise DispatcherError("HALT_RESUME_OLD_BINDING_REQUIRED")
        return
    if descriptor is None:
        raise DispatcherError("DISPATCH_JOURNAL_BINDING_MISMATCH")
    source_event = _source_adoption_event(context, descriptor)
    event_count = descriptor["journal_event_count"]
    if len(journal.events) == event_count:
        journal.append(source_event)
        return
    if len(journal.events) <= event_count:
        raise DispatcherError("HALT_RESUME_SOURCE_ADOPTION_MISSING")
    observed_source_event = {key: value for key, value in journal.events[event_count].items() if key != "at_utc"}
    if observed_source_event != source_event:
        raise DispatcherError("HALT_RESUME_SOURCE_ADOPTION_MISMATCH")


def _latest_document_events(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events[1:]:
        document_id = event.get("document_id")
        if isinstance(document_id, str):
            latest[document_id] = dict(event)
    return latest


def _prepare_halt_resume(
    journal: DurableJournal,
    context: Mapping[str, Any],
    *,
    sampler: Callable[[], Mapping[str, int]],
    sleep_fn: Callable[[float], Any],
    samples_path: Path,
) -> str | None:
    descriptor = _halt_resume_descriptor(context, journal)
    if descriptor is None:
        return None
    event_count = descriptor["journal_event_count"]
    source_index = event_count
    source_event = _source_adoption_event(context, descriptor)
    if len(journal.events) <= source_index:
        raise DispatcherError("HALT_RESUME_SOURCE_ADOPTION_MISSING")
    if {key: value for key, value in journal.events[source_index].items() if key != "at_utc"} != source_event:
        raise DispatcherError("HALT_RESUME_SOURCE_ADOPTION_MISMATCH")
    post = journal.events[source_index + 1:]
    doc_id = descriptor["document_id"]
    waits = [
        event for event in post
        if event.get("event") == "memory_recovery_wait"
        and event.get("document_id") == doc_id
        and event.get("prior_plan_sha256") == descriptor["plan_sha256"]
    ]
    resolutions = [
        event for event in post
        if event.get("event") == "halt_resolution"
        and event.get("document_id") == doc_id
        and event.get("prior_plan_sha256") == descriptor["plan_sha256"]
    ]
    recovery_plans = [
        event for event in post
        if event.get("event") == "plan_created"
        and event.get("document_id") == doc_id
        and event.get("recovery_generation") == 1
        and event.get("recovery_of_plan_sha256") == descriptor["plan_sha256"]
    ]
    if len(waits) > 1 or len(resolutions) > 1 or len(recovery_plans) > 1:
        raise DispatcherError("HALT_RESUME_DUPLICATE_TRANSITION")
    if post and post[0].get("event") != "memory_recovery_wait":
        raise DispatcherError("HALT_RESUME_UNEXPECTED_POST_ADOPTION_EVENT")
    if waits and journal.events.index(waits[0]) != source_index + 1:
        raise DispatcherError("HALT_RESUME_WAIT_ORDER_INVALID")
    if resolutions and (
        not waits
        or journal.events.index(resolutions[0]) != journal.events.index(waits[0]) + 1
    ):
        raise DispatcherError("HALT_RESUME_RESOLUTION_ORDER_INVALID")
    if recovery_plans and (
        not resolutions
        or journal.events.index(recovery_plans[0]) != journal.events.index(resolutions[0]) + 1
    ):
        raise DispatcherError("HALT_RESUME_PLAN_ORDER_INVALID")
    if (
        (not waits and post)
        or (waits and not resolutions and len(post) != 1)
        or (resolutions and not recovery_plans and len(post) != 2)
        or (recovery_plans and [event.get("event") for event in post[:3]] != [
            "memory_recovery_wait", "halt_resolution", "plan_created"
        ])
    ):
        raise DispatcherError("HALT_RESUME_UNEXPECTED_POST_ADOPTION_EVENT")
    recovery_binding = descriptor["recovery_plan"]["selected_documents"][0]["recovery"]
    if waits:
        wait_event = waits[0]
        if (
            set(wait_event)
            != {
                "at_utc",
                "event",
                "document_id",
                "status",
                "decision",
                "prior_plan_sha256",
                "prior_state_root",
                "prior_queue_idempotency_key",
                "before",
                "after",
                "available_gain_bytes",
                "swap_reduction_bytes",
                "stable_samples",
            }
            or
            wait_event.get("document_id") != doc_id
            or wait_event.get("status") != "RESOURCE_CHANGE_OBSERVED"
            or wait_event.get("decision") != "CONTINUE"
            or wait_event.get("prior_plan_sha256") != descriptor["plan_sha256"]
            or wait_event.get("prior_state_root") != descriptor["prior_state_root"]
            or wait_event.get("prior_queue_idempotency_key") != descriptor["queue_key"]
            or not _resource_change_event_is_bound(wait_event)
        ):
            raise DispatcherError("HALT_RESUME_WAIT_EVIDENCE_INVALID")
    else:
        if resolutions or recovery_plans:
            raise DispatcherError("HALT_RESUME_WAIT_EVENT_MISSING")
        try:
            before_swap = descriptor["failure_sample"]["swap_used_bytes"]
            baseline = dict(sampler())
        except Exception:
            raise DispatcherError("HALT_RESUME_RESOURCE_SAMPLE_CANNOT_CONFIRM") from None
        if type(before_swap) is not int or type(baseline.get("swap_used_bytes")) is not int:
            raise DispatcherError("HALT_RESUME_RESOURCE_SAMPLE_CANNOT_CONFIRM")
        wait_result = _wait_for_recovery_resource_change(
            descriptor["failure_sample"],
            baseline_swap_used=baseline["swap_used_bytes"],
            sampler=sampler,
            sleep_fn=sleep_fn,
            persist=lambda row: _persist_sample(samples_path, row),
        )
        if wait_result.get("status") != "RESOURCE_CHANGE_OBSERVED":
            raise DispatcherError("HALT_RESUME_RESOURCE_CHANGE_NOT_OBSERVED")
        journal.append({
            "event": "memory_recovery_wait",
            "document_id": doc_id,
            "status": wait_result["status"],
            "decision": "CONTINUE",
            "prior_plan_sha256": descriptor["plan_sha256"],
            "prior_state_root": descriptor["prior_state_root"],
            "prior_queue_idempotency_key": descriptor["queue_key"],
            "before": wait_result["before"],
            "after": wait_result["after"],
            "available_gain_bytes": wait_result["available_gain_bytes"],
            "swap_reduction_bytes": wait_result["swap_reduction_bytes"],
            "stable_samples": wait_result["stable_samples"],
        })
        wait_event = journal.events[-1]

    wait_index = next(index for index, event in enumerate(journal.events) if event is wait_event)
    wait_line_sha = sha256_bytes(canonical_json(wait_event) + b"\n")
    resolution_base = {
        "event": "halt_resolution",
        "authorization_id": context["authorization"]["authorization_id"],
        "authorization_sha256": context["authorization_sha256"],
        "document_id": doc_id,
        "status": "RESOURCE_CHANGE_OBSERVED",
        "prior_plan_sha256": descriptor["plan_sha256"],
        "recovery_generation": descriptor["recovery_generation"],
        "wait_event_index": wait_index,
        "wait_event_line_sha256": wait_line_sha,
        "before": wait_event["before"],
        "after": wait_event["after"],
        "available_gain_bytes": wait_event["available_gain_bytes"],
        "swap_reduction_bytes": wait_event["swap_reduction_bytes"],
        "stable_samples": wait_event["stable_samples"],
    }
    if resolutions:
        resolution = resolutions[0]
        if {key: value for key, value in resolution.items() if key != "at_utc"} != resolution_base:
            raise DispatcherError("HALT_RESUME_RESOLUTION_MISMATCH")
    else:
        journal.append(resolution_base)
        resolution = journal.events[-1]

    recovery_plan = descriptor["recovery_plan"]
    recovery_raw = descriptor["recovery_raw"]
    recovery_path = journal.root / "plans" / f"{recovery_plan['continuation_id']}.json"
    if recovery_plans:
        plan_event = recovery_plans[0]
        if (
            plan_event.get("plan_sha256") != sha256_bytes(recovery_raw)
            or plan_event.get("continuation_id") != recovery_plan["continuation_id"]
            or plan_event.get("recovery_of_plan_sha256") != descriptor["plan_sha256"]
            or plan_event.get("state_root") != recovery_plan["state_root"]
        ):
            raise DispatcherError("HALT_RESUME_RECOVERY_PLAN_MISMATCH")
    else:
        plan_sha = _write_immutable(recovery_path, recovery_raw)
        try:
            validated = batch.validate_continuation_plan(
                recovery_path,
                manifest_sha256=context["manifest_sha256"],
                documents=context["documents"],
            )
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            raise DispatcherError(f"HALT_RESUME_PLAN_REJECTED:{str(code)[:64]}") from None
        if validated.get("plan_sha256") != plan_sha:
            raise DispatcherError("HALT_RESUME_RECOVERY_PLAN_SHA_MISMATCH")
        journal.append({
            "event": "plan_created",
            "document_id": doc_id,
            "continuation_id": recovery_plan["continuation_id"],
            "plan_path": str(recovery_path),
            "plan_sha256": plan_sha,
            "plan_bytes_b64": base64.b64encode(recovery_raw).decode("ascii"),
            "state_root": recovery_plan["state_root"],
            "inventory_sha256": context["inventory_summary"]["inventory_sha256"],
            "outstanding_count": context["inventory_summary"]["outstanding_count"],
            "recovery_generation": 1,
            "recovery_of_plan_sha256": descriptor["plan_sha256"],
        })
    return doc_id


def _halt_if_required(
    journal: DurableJournal,
    latest: Mapping[str, Mapping[str, Any]],
    *,
    halt_resume_descriptor: Mapping[str, Any] | None = None,
) -> None:
    resolved_halt_index: int | None = None
    resolved_reconciled_index: int | None = None
    if halt_resume_descriptor is not None:
        resolved_halt_index = halt_resume_descriptor.get("halt_event_index")
        resolved_reconciled_index = halt_resume_descriptor.get("reconciled_event_index")
        if (
            type(resolved_halt_index) is not int
            or type(resolved_reconciled_index) is not int
            or not isinstance(halt_resume_descriptor.get("reconciled_event_line_sha256"), str)
            or not isinstance(halt_resume_descriptor.get("continuation_id"), str)
            or not isinstance(halt_resume_descriptor.get("document_id"), str)
            or resolved_halt_index < 0
            or resolved_reconciled_index < 0
            or resolved_halt_index >= len(journal.events)
            or resolved_reconciled_index >= len(journal.events)
        ):
            raise DispatcherError("HALT_RESUME_TERMINAL_BINDING_MISMATCH")
        reconciled_event = journal.events[resolved_reconciled_index]
        if (
            reconciled_event.get("event") != "reconciled"
            or reconciled_event.get("decision") != "HALT"
            or reconciled_event.get("document_id") != halt_resume_descriptor["document_id"]
            or reconciled_event.get("continuation_id") != halt_resume_descriptor["continuation_id"]
            or sha256_bytes(canonical_json(reconciled_event) + b"\n")
            != halt_resume_descriptor["reconciled_event_line_sha256"]
            or journal.events[resolved_halt_index].get("event") != "halt"
            or journal.events[resolved_halt_index].get("document_id") != halt_resume_descriptor["document_id"]
        ):
            raise DispatcherError("HALT_RESUME_TERMINAL_BINDING_MISMATCH")
    for index, event in enumerate(journal.events):
        if event.get("event") == "halt" and index != resolved_halt_index:
            raise DispatcherError("DISPATCHER_PREVIOUSLY_HALTED")
        if event.get("event") == "reconciled" and event.get("decision") == "HALT":
            if (
                index != resolved_reconciled_index
                or halt_resume_descriptor is None
                or event.get("document_id") != halt_resume_descriptor["document_id"]
                or event.get("continuation_id") != halt_resume_descriptor["continuation_id"]
                or sha256_bytes(canonical_json(event) + b"\n")
                != halt_resume_descriptor["reconciled_event_line_sha256"]
            ):
                raise DispatcherError("DISPATCHER_PREVIOUSLY_HALTED")
    for event in latest.values():
        if event.get("event") == "dispatch_intent":
            raise DispatcherError("DISPATCH_OUTCOME_AMBIGUOUS_FAIL_CLOSED")


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


def _make_command(
    plan_path: Path,
    *,
    execute: bool,
    prepared_text_manifest_path: Path | None = None,
    prepared_text_manifest_sha256: str | None = None,
) -> list[str]:
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
        if prepared_text_manifest_path is None or prepared_text_manifest_sha256 is None:
            raise DispatcherError("PREPARED_TEXT_MANIFEST_REQUIRED")
        command.extend(
            [
                "--prepared-text-manifest",
                str(prepared_text_manifest_path),
                "--prepared-text-manifest-sha256",
                prepared_text_manifest_sha256,
            ]
        )
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
    prepared_text_manifest_path: Path,
    prepared_text_manifest_sha256: str,
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
    last_resource_sample = initial

    proc = popen(
        _make_command(
            plan_path,
            execute=True,
            prepared_text_manifest_path=prepared_text_manifest_path,
            prepared_text_manifest_sha256=prepared_text_manifest_sha256,
        ),
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
            last_resource_sample = sample
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
        "last_resource_sample": last_resource_sample,
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
    sleep_fn: Callable[[float], Any] = time.sleep,
    plan_only: Callable[[Path], None] | None = None,
    child_runner: Callable[..., Mapping[str, Any]] | None = None,
    continuation_id_factory: Callable[[], str] | None = None,
    prepared_text_manifest_path: Path | None = None,
    prepared_text_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if prepared_text_manifest_path is None or prepared_text_manifest_sha256 is None:
        raise DispatcherError("PREPARED_TEXT_MANIFEST_REQUIRED")
    try:
        _, expected_parent_sha, _ = batch.load_manifest(manifest_path)
        prepared_manifest = batch.pdf_text_preparation.verify_frozen_manifest(
            batch,
            prepared_text_manifest_path,
            expected_sha256=prepared_text_manifest_sha256,
            expected_parent_sha256=expected_parent_sha,
        )
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        raise DispatcherError(f"PREPARED_TEXT_MANIFEST_REJECTED:{str(code)[:64]}") from None
    if expected_parent_sha != EXPECTED_MANIFEST_SHA256:
        raise DispatcherError("PREPARED_PARENT_MANIFEST_SHA_MISMATCH")
    _assert_runtime()
    static = _verify_static_bindings()
    auth_context = load_and_validate_authorization(authorization_path)
    auth = auth_context["authorization"]
    if auth.get("prepared_text_manifest_sha256") != prepared_manifest["manifest_sha256"]:
        raise DispatcherError("ROOT_PREPARED_MANIFEST_AUTHORIZATION_MISMATCH")
    # Keep old dispatches, HALT and duplicate prevention in their original root.
    # A manifest-specific empty root is never a substitute for state adoption.
    if evidence_root != EVIDENCE_ROOT and (EVIDENCE_ROOT / "dispatch.jsonl").is_file():
        raise DispatcherError("PREPARED_DISPATCH_MUST_RETAIN_HISTORY")
    if max_documents is not None and (type(max_documents) is not int or max_documents < 1):
        raise DispatcherError("DISPATCH_LIMIT_INVALID")
    limit = min(max_documents or auth["max_documents"], auth["max_documents"])
    manifest_sha, documents, original_rows = _load_original_r3(manifest_path)
    status_by_id, inventory_summary = load_current_completion_statuses(
        documents,
        manifest_sha256=manifest_sha,
    )
    frozen_inventory_statuses = inventory_summary.get("frozen_inventory_statuses")
    if (
        not isinstance(frozen_inventory_statuses, Mapping)
        or any(frozen_inventory_statuses.get(document_id) != row.get("status") for document_id, row in original_rows.items())
    ):
        raise DispatcherError("ORIGINAL_PROGRESS_INVENTORY_STATUS_MISMATCH")
    context = {
        **auth_context,
        "manifest_sha256": manifest_sha,
        "documents": documents,
        "inventory_summary": inventory_summary,
        "static": static,
        "prepared_text_manifest_path": str(prepared_manifest["path"]),
        "prepared_text_manifest_sha256": prepared_manifest["manifest_sha256"],
    }
    journal = DurableJournal(evidence_root)
    completed_this_call = 0
    authorization_limit_reached = False
    cohort_exhausted = False
    resume_required = False
    with journal:
        _verify_or_create_binding(journal, context)
        samples_path = evidence_root / "resource-samples.jsonl"
        resumed_document_id = _prepare_halt_resume(
            journal,
            context,
            sampler=sampler,
            sleep_fn=sleep_fn,
            samples_path=samples_path,
        )
        latest = _latest_document_events(journal.events)
        resolved_halt_resume_descriptor = None
        if resumed_document_id is not None:
            resolved_halt_resume_descriptor = _halt_resume_descriptor(context, journal)
            if resolved_halt_resume_descriptor is None:
                raise DispatcherError("HALT_RESUME_DESCRIPTOR_MISSING")
        _halt_if_required(journal, latest, halt_resume_descriptor=resolved_halt_resume_descriptor)
        _assert_no_duplicate_document_ids(journal.events)
        if not latest:
            _first, initial_count = select_next_document(
                documents,
                status_by_id,
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
                    status_by_id,
                    auth_context["pilot_document_ids"],
                    dispatched_ids,
                    prepared_manifest["documents"],
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
                    "inventory_sha256": inventory_summary["inventory_sha256"],
                    "outstanding_count": inventory_summary["outstanding_count"],
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
            if prepared_manifest["documents"].get(document_id, {}).get("manifest_row", {}).get("status") != "READY":
                raise DispatcherError("PENDING_PLAN_PREPARED_DOCUMENT_NOT_READY")
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
                    prepared_text_manifest_path=prepared_manifest["path"],
                    prepared_text_manifest_sha256=prepared_manifest["manifest_sha256"],
                )
                if child_runner is not None
                else _run_execution_child(
                    plan_path,
                    expected_plan_sha256=plan_sha,
                    baseline_swap_used=baseline_swap,
                    samples_path=samples_path,
                    prepared_text_manifest_path=prepared_manifest["path"],
                    prepared_text_manifest_sha256=prepared_manifest["manifest_sha256"],
                    sampler=sampler,
                    sleep_fn=sleep_fn,
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
            selected_entry = plan["selected_documents"][0]
            is_memory_recovery = isinstance(selected_entry, dict) and isinstance(selected_entry.get("recovery"), dict)
            recovery_candidate: tuple[dict[str, Any], bytes] | None = None
            recovery_error: str | None = None
            if (
                not is_memory_recovery
                and reconciliation.get("status") == "FAILED_NO_RETRY"
                and reconciliation.get("decision") == "HALT"
                and child.get("returncode") == 0
                and child.get("resource_stop_reason") is None
            ):
                try:
                    recovery_candidate = build_memory_recovery_plan(
                        plan,
                        plan_raw,
                        next(row for row in documents if row.get("document_id") == document_id),
                        model_settings_sha256=auth["model_settings_sha256"],
                    )
                except DispatcherError as exc:
                    recovery_error = getattr(exc, "code", None) or str(exc)
            if (
                is_memory_recovery
                and reconciliation.get("status") == "FAILED_NO_RETRY"
                and child.get("returncode") == 0
                and child.get("resource_stop_reason") is None
            ):
                # The recovery limit is one. A second failed report is terminal
                # for this document, but it must not stop unrelated documents.
                reconciliation["decision"] = "CONTINUE"
                reconciliation["memory_recovery_status"] = "SINGLE_RECOVERY_FAILED_ISOLATED"
            elif recovery_candidate is not None:
                reconciliation["decision"] = "CONTINUE"
                reconciliation["memory_recovery_status"] = "WAITING_FOR_RESOURCE_CHANGE"
            elif recovery_error is not None:
                reconciliation["memory_recovery_status"] = f"EVIDENCE_REJECTED:{recovery_error[:72]}"
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
            if recovery_candidate is not None:
                recovery_plan, recovery_raw = recovery_candidate
                wait_result = _wait_for_recovery_resource_change(
                    child.get("last_resource_sample") if isinstance(child.get("last_resource_sample"), Mapping) else {},
                    baseline_swap_used=baseline_swap,
                    sampler=sampler,
                    sleep_fn=sleep_fn,
                    persist=lambda row: _persist_sample(samples_path, row),
                )
                candidate_entry = recovery_plan["selected_documents"][0]
                recovery_binding = candidate_entry.get("recovery") if isinstance(candidate_entry, dict) else None
                journal.append({
                    "event": "memory_recovery_wait",
                    "document_id": document_id,
                    "status": wait_result.get("status"),
                    "decision": "CONTINUE",
                    "prior_plan_sha256": plan_sha,
                    "prior_state_root": plan.get("state_root"),
                    "prior_queue_idempotency_key": recovery_binding.get("prior_queue_idempotency_key") if isinstance(recovery_binding, dict) else None,
                    "before": wait_result.get("before"),
                    "after": wait_result.get("after"),
                    "available_gain_bytes": wait_result.get("available_gain_bytes"),
                    "swap_reduction_bytes": wait_result.get("swap_reduction_bytes"),
                    "stable_samples": wait_result.get("stable_samples"),
                })
                latest[document_id] = dict(journal.events[-1])
                if wait_result.get("status") == "RESOURCE_CHANGE_OBSERVED":
                    recovery_path = evidence_root / "plans" / f"{recovery_plan['continuation_id']}.json"
                    recovery_sha = _write_immutable(recovery_path, recovery_raw)
                    try:
                        validated_recovery = batch.validate_continuation_plan(
                            recovery_path,
                            manifest_sha256=manifest_sha,
                            documents=documents,
                        )
                    except Exception as exc:
                        code = getattr(exc, "code", None) or type(exc).__name__
                        journal.append({"event": "halt", "reason": f"MEMORY_RECOVERY_PLAN_REJECTED:{str(code)[:64]}", "document_id": document_id})
                        break
                    if validated_recovery.get("plan_sha256") != recovery_sha:
                        journal.append({"event": "halt", "reason": "MEMORY_RECOVERY_PLAN_SHA_MISMATCH", "document_id": document_id})
                        break
                    journal.append({
                        "event": "plan_created",
                        "document_id": document_id,
                        "continuation_id": recovery_plan["continuation_id"],
                        "plan_path": str(recovery_path),
                        "plan_sha256": recovery_sha,
                        "plan_bytes_b64": base64.b64encode(recovery_raw).decode("ascii"),
                        "state_root": recovery_plan["state_root"],
                        "inventory_sha256": inventory_summary["inventory_sha256"],
                        "outstanding_count": inventory_summary["outstanding_count"],
                        "recovery_generation": 1,
                        "recovery_of_plan_sha256": plan_sha,
                    })
                    latest[document_id] = dict(journal.events[-1])
                    pending = (recovery_plan, recovery_path, recovery_raw)
                    continue
                completed_this_call += 1
                continue
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
            if any(event.get("event") == "halt" and (resolved_halt_resume_descriptor is None or index != resolved_halt_resume_descriptor["halt_event_index"]) for index, event in enumerate(journal.events))
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
    continuation_ids: set[str] = set()
    state_roots: set[str] = set()
    original_plans: dict[str, tuple[int, str, str, Mapping[str, Any]]] = {}
    recovery_counts: dict[str, int] = {}
    for event_index, event in enumerate(events):
        if event.get("event") == "plan_created":
            document_id = event.get("document_id")
            continuation_id = event.get("continuation_id")
            state_root = event.get("state_root")
            encoded_plan = event.get("plan_bytes_b64")
            if not isinstance(encoded_plan, str):
                raise DispatcherError("PLAN_CREATED_BYTES_MISSING")
            try:
                plan_raw = base64.b64decode(encoded_plan, validate=True)
                plan = json.loads(plan_raw.decode("utf-8"))
            except (ValueError, base64.binascii.Error, UnicodeError, json.JSONDecodeError):
                raise DispatcherError("PLAN_CREATED_BYTES_INVALID") from None
            selected = plan.get("selected_documents") if isinstance(plan, dict) else None
            selection = selected[0] if isinstance(selected, list) and len(selected) == 1 else None
            if (
                not isinstance(document_id, str)
                or not isinstance(continuation_id, str)
                or continuation_id in continuation_ids
                or not isinstance(state_root, str)
                or state_root in state_roots
                or not isinstance(plan, dict)
                or plan.get("continuation_id") != continuation_id
                or plan.get("state_root") != state_root
                or event.get("plan_sha256") != sha256_bytes(plan_raw)
                or not isinstance(selection, dict)
                or selection.get("document_id") != document_id
            ):
                raise DispatcherError("CROSS_PLAN_DUPLICATE_DOCUMENT")
            previous = original_plans.get(document_id)
            if previous is None:
                if selection.get("prior_status") != "UNPROCESSED" or "recovery" in selection:
                    raise DispatcherError("CROSS_PLAN_UNEXPECTED_RECOVERY")
                original_plans[document_id] = (event_index, continuation_id, state_root, plan)
            else:
                previous_index, previous_continuation_id, previous_state_root, previous_plan = previous
                previous_plan_sha = sha256_bytes(_json_bytes(previous_plan))
                recovery = selection.get("recovery")
                interim = events[previous_index + 1:event_index]
                failure_events = [
                    (idx, prior_event)
                    for idx, prior_event in enumerate(interim, start=previous_index + 1)
                    if prior_event.get("event") == "reconciled"
                    and prior_event.get("document_id") == document_id
                    and prior_event.get("continuation_id") == previous_continuation_id
                    and prior_event.get("plan_sha256") == previous_plan_sha
                    and prior_event.get("status") == "FAILED_NO_RETRY"
                    and prior_event.get("decision") == "CONTINUE"
                    and prior_event.get("memory_recovery_status") == "WAITING_FOR_RESOURCE_CHANGE"
                ]
                halted_failure_events = [
                    (idx, prior_event)
                    for idx, prior_event in enumerate(interim, start=previous_index + 1)
                    if prior_event.get("event") == "reconciled"
                    and prior_event.get("document_id") == document_id
                    and prior_event.get("continuation_id") == previous_continuation_id
                    and prior_event.get("plan_sha256") == previous_plan_sha
                    and prior_event.get("status") == "FAILED_NO_RETRY"
                    and prior_event.get("decision") == "HALT"
                ]
                resource_events = []
                if len(failure_events) == 1:
                    failure_index, _failure_event = failure_events[0]
                    resource_events = [
                        prior_event
                        for prior_event in interim[failure_index - previous_index:]
                        if prior_event.get("event") == "memory_recovery_wait"
                        and prior_event.get("document_id") == document_id
                        and prior_event.get("prior_plan_sha256") == previous_plan_sha
                        and prior_event.get("prior_state_root") == previous_state_root
                        and prior_event.get("prior_queue_idempotency_key") == recovery.get("prior_queue_idempotency_key")
                        and prior_event.get("status") == "RESOURCE_CHANGE_OBSERVED"
                    ] if isinstance(recovery, dict) else []
                halted_resolution_events = []
                if len(halted_failure_events) == 1 and isinstance(recovery, dict):
                    failure_index, _failure_event = halted_failure_events[0]
                    after_failure = interim[failure_index - previous_index:]
                    halts = [
                        prior_event for prior_event in after_failure
                        if prior_event.get("event") == "halt"
                        and prior_event.get("document_id") == document_id
                        and prior_event.get("reason") == "FAILED_NO_RETRY"
                    ]
                    source_adoptions = [
                        prior_event for prior_event in after_failure
                        if prior_event.get("event") == "source_adoption"
                        and prior_event.get("document_id") == document_id
                        and prior_event.get("plan_sha256") == previous_plan_sha
                    ]
                    resource_events = [
                        prior_event for prior_event in after_failure
                        if prior_event.get("event") == "memory_recovery_wait"
                        and prior_event.get("document_id") == document_id
                        and prior_event.get("prior_plan_sha256") == previous_plan_sha
                        and prior_event.get("prior_state_root") == previous_state_root
                        and prior_event.get("prior_queue_idempotency_key") == recovery.get("prior_queue_idempotency_key")
                        and prior_event.get("status") == "RESOURCE_CHANGE_OBSERVED"
                    ]
                    halted_resolution_events = [
                        prior_event for prior_event in after_failure
                        if prior_event.get("event") == "halt_resolution"
                        and prior_event.get("document_id") == document_id
                        and prior_event.get("prior_plan_sha256") == previous_plan_sha
                        and prior_event.get("recovery_generation") == 1
                        and prior_event.get("status") == "RESOURCE_CHANGE_OBSERVED"
                    ]
                    if len(halts) != 1 or len(source_adoptions) != 1:
                        resource_events = []
                        halted_resolution_events = []
                observed_resource_change = (
                    len(resource_events) == 1
                    and _resource_change_event_is_bound(resource_events[0])
                    and (
                        len(failure_events) == 1
                        or (
                            len(halted_failure_events) == 1
                            and len(halted_resolution_events) == 1
                            and _resource_change_event_is_bound(halted_resolution_events[0])
                            and halted_resolution_events[0].get("before") == resource_events[0].get("before")
                            and halted_resolution_events[0].get("after") == resource_events[0].get("after")
                            and halted_resolution_events[0].get("wait_event_line_sha256")
                            == sha256_bytes(canonical_json(resource_events[0]) + b"\n")
                        )
                    )
                )
                if (
                    recovery_counts.get(document_id, 0) != 0
                    or not isinstance(recovery, dict)
                    or recovery.get("generation") != 1
                    or recovery.get("prior_state_root") != previous_state_root
                    or not isinstance(recovery.get("prior_queue_idempotency_key"), str)
                    or not SHA256_RE.fullmatch(recovery["prior_queue_idempotency_key"])
                    or not isinstance(recovery.get("prior_artifact_sha256"), dict)
                    or selection.get("prior_status") != "FAILED_NO_RETRY"
                    or event.get("recovery_of_plan_sha256") != previous_plan_sha
                    or not observed_resource_change
                ):
                    raise DispatcherError("CROSS_PLAN_DUPLICATE_DOCUMENT")
                recovery_counts[document_id] = 1
            continuation_ids.add(continuation_id)
            state_roots.add(state_root)


def _resource_change_event_is_bound(event: Mapping[str, Any]) -> bool:
    before = event.get("before")
    after = event.get("after")
    if (
        not isinstance(before, Mapping)
        or not isinstance(after, Mapping)
        or type(before.get("available_bytes")) is not int
        or type(before.get("swap_used_bytes")) is not int
        or type(after.get("available_bytes")) is not int
        or type(after.get("swap_used_bytes")) is not int
        or type(event.get("stable_samples")) is not int
        or event.get("stable_samples") != MEMORY_RECOVERY_STABLE_SAMPLE_COUNT
    ):
        return False
    available_gain = after["available_bytes"] - before["available_bytes"]
    swap_reduction = before["swap_used_bytes"] - after["swap_used_bytes"]
    return (
        event.get("available_gain_bytes") == available_gain
        and event.get("swap_reduction_bytes") == swap_reduction
        and (
            available_gain >= MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES
            or swap_reduction >= MEMORY_RECOVERY_SWAP_REDUCTION_BYTES
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, default=AUTHORIZATION_PATH)
    parser.add_argument("--max-documents", type=int, help="per-invocation cap; authorization still sets the cumulative ceiling")
    parser.add_argument("--prepared-text-manifest", type=Path, help="full frozen text-stage manifest required for model execution")
    parser.add_argument("--prepared-text-manifest-sha256", help="expected SHA-256 of the frozen text-stage manifest")
    parser.add_argument("--execute", action="store_true", help="requires root authorization plus completed pilot gates")
    args = parser.parse_args(argv)
    try:
        _assert_runtime()
        if not args.execute:
            _verify_static_bindings()
            print(json.dumps({"status": "PREPARATION_ONLY", "execution": "NOT_RUN"}, sort_keys=True))
            return 0
        result = execute_once(
            authorization_path=args.authorization,
            max_documents=args.max_documents,
            prepared_text_manifest_path=args.prepared_text_manifest,
            prepared_text_manifest_sha256=args.prepared_text_manifest_sha256,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        print(json.dumps({"status": "STOPPED", "code": str(code)[:96]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
