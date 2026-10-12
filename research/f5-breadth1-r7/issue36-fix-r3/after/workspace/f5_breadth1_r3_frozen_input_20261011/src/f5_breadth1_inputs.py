"""Full-parent-pool BREADTH1 aggregation and exact row-key mapping.

The real-panel loader is fail-closed behind an admission binding.  Unit tests
exercise the same aggregation/mapping functions with explicitly synthetic data;
they never call the real-panel loader.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import gzip
import csv
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


EXPECTED_MANIFEST_SHA256 = "b151979a05587bdf571f329300bd34b9a03aad68726b1afec7eb735b6ed844a8"
EXPECTED_FEATURES_SHA256 = "a180ff1828cd9142de1133b710193175a0acb8757065a92b43801a8c2a6dbd5e"
REQUIRED_PANEL_COLUMNS = ("code", "session_id", "market_date", "feature_row_present", "ret_1d")
PANEL_SOURCE_COLUMNS = ("code", "session_id", "feature_row_present", "ret_1d")
ADMISSION_RELEASE_FILES = frozenset({
    "input_binding", "input_manifest", "train_x64", "train_y", "train_keys",
    "eval_x64", "eval_meta", "evaluation_calendar", "pretruth_scores",
})
FROZEN_OBSERVED_PROVENANCE_MODE = "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
PRODUCER_EVIDENCE_SCHEMAS = {
    "producer_output_run_receipt": "F5_BREADTH1_PRODUCER_OUTPUT_RUN_RECEIPT_V1",
    "producer_environment_receipt": "F5_BREADTH1_PRODUCER_ENVIRONMENT_RECEIPT_V1",
    "full_grid_flag_join_receipt": "F5_BREADTH1_FULL_GRID_FLAG_JOIN_RECEIPT_V1",
}
MAX_ADMISSION_RECEIPT_BYTES = 16 * 1024 * 1024
INPUT_ADMISSION_READ_RELEASE_RELATIVE_PATH = (
    Path("research") / "hk_burst_f5" / "batches"
    / "breadth1_r3_frozen_input_20261011" / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE.json"
)
INPUT_ADMISSION_RECOVERY_GRANT_ID = "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011"
PANEL_HEADER_RECOVERY_ACTION_KEY = "F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011:F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011:input_admission_recovery:PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011"
PANEL_HEADER_RECOVERY_EXECUTION_ID = "F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011_ONE_SHOT"


class AdmissionBlocked(RuntimeError):
    """Real inputs cannot be opened because a required source gate is unresolved."""

    def __init__(self, message: str, *, diagnostics: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class InputContractError(ValueError):
    """The parent pool or row mapping violates the frozen BREADTH1 contract."""

    def __init__(self, message: str, *, diagnostics: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


@dataclass(frozen=True)
class VerifiedInputAdmissionReadRelease:
    """A SHA-pinned, bounded, read-only authorization for the first audit."""

    path: Path
    expected_sha256: str
    release_value: Mapping[str, Any]
    contract_sha256: str
    input_binding_sha256: str
    bytes_read: int
    payload: bytes


def validate_admission_read_budget(value: Any) -> dict[str, int]:
    """Validate the separately bound first-pass file and byte caps."""

    if not isinstance(value, Mapping):
        raise AdmissionBlocked("READ_BUDGET_MISSING")
    fields = ("max_files", "max_file_bytes", "max_total_bytes")
    result: dict[str, int] = {}
    for name in fields:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise AdmissionBlocked(f"READ_BUDGET_INVALID:{name}")
        result[name] = int(item)
    if result["max_file_bytes"] > result["max_total_bytes"]:
        raise AdmissionBlocked("READ_BUDGET_INVALID:file_cap_exceeds_total_cap")
    return result


def load_verified_input_admission_read_release(
    path: Path,
    expected_sha256: str,
    *,
    contract_sha256: str,
    input_binding_sha256: str,
    input_binding_path: Path,
    resume_authorization: Mapping[str, Any] | None = None,
) -> VerifiedInputAdmissionReadRelease:
    """Verify the separate approval document before any target input file opens."""

    if not _is_sha256(expected_sha256) or not _is_sha256(contract_sha256) or not _is_sha256(input_binding_sha256):
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_IDENTITY_INVALID")
    path = Path(path)
    project_root = Path(__file__).resolve().parents[3]
    from f5_breadth1_budget import (
        PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH,
        PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH,
    )
    expected_path = project_root / INPUT_ADMISSION_READ_RELEASE_RELATIVE_PATH
    resume_path = path.resolve() == PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH.resolve()
    if resume_path:
        release_binding = (
            resume_authorization.get("read_release_normalization")
            if isinstance(resume_authorization, Mapping) else None
        )
        authorization_ref = (
            resume_authorization.get("authorization_ref")
            if isinstance(resume_authorization, Mapping) else None
        )
        if (
            not isinstance(release_binding, Mapping)
            or release_binding.get("resume_path") != str(PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH.resolve())
            or release_binding.get("resume_sha256") != expected_sha256
            or not isinstance(authorization_ref, Mapping)
            or authorization_ref.get("path") != str(PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH.resolve())
            or not _is_sha256(authorization_ref.get("sha256"))
        ):
            raise AdmissionBlocked("R7_RESUME_READ_RELEASE_REQUIRES_FIXED_AUTHORIZATION")
    if (
        (path.resolve() != expected_path.resolve() and not resume_path)
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 1024 * 1024
    ):
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_PATH_OR_SIZE_INVALID")
    payload = _bounded_file_read(path, 1024 * 1024, "input admission release")
    actual = sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_SHA_MISMATCH")
    release = _parse_json_snapshot(payload, "INPUT_ADMISSION_RELEASE")
    from f5_breadth1_budget import (
        _valid_prior_panel_header_diagnostic, _valid_prior_panel_header_runtime_failure,
        _valid_prior_panel_header_r5_failure, _valid_prior_panel_header_r6_failure,
        _valid_prior_train_label_diagnostic,
    )
    from f5_breadth1_core import EXPERIMENT_ID, ROUTE_ID

    if (
        release.get("schema") != "F5_BREADTH1_INPUT_ADMISSION_READ_RELEASE_V2"
        or release.get("status") != "APPROVED_READ_ONLY"
        or release.get("synthetic_only") is not False
        or release.get("route_id") != ROUTE_ID
        or release.get("candidate_id") != ROUTE_ID
        or release.get("contract_sha256") != contract_sha256
        or release.get("input_binding_sha256") != input_binding_sha256
        or release.get("recovery_grant_id") != INPUT_ADMISSION_RECOVERY_GRANT_ID
        or not _valid_prior_train_label_diagnostic(release.get("prior_train_label_diagnostic"))
        or not _valid_prior_panel_header_diagnostic(release.get("prior_panel_header_diagnostic"))
        or not _valid_prior_panel_header_runtime_failure(release.get("prior_panel_header_runtime_failure"))
        or not _valid_prior_panel_header_r5_failure(release.get("prior_panel_header_r5_failure"))
        or not _valid_prior_panel_header_r6_failure(release.get("prior_panel_header_r6_failure"))
    ):
        raise AdmissionBlocked("INPUT_ADMISSION_READ_RELEASE_BINDING_MISMATCH")
    budget = validate_admission_read_budget(release.get("read_budget"))
    files = release.get("files")
    if not isinstance(files, Mapping) or set(files) != ADMISSION_RELEASE_FILES:
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_FILE_SET_MISMATCH")
    for name, item in files.items():
        if not isinstance(item, Mapping):
            raise AdmissionBlocked(f"INPUT_ADMISSION_RELEASE_FILE_BINDING_INVALID:{name}")
        file_path = item.get("path")
        maximum = item.get("max_bytes")
        if (
            not isinstance(file_path, str) or not Path(file_path).is_absolute() or Path(file_path).is_symlink()
            or isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1
            or maximum > budget["max_file_bytes"] or not _is_sha256(item.get("sha256"))
        ):
            raise AdmissionBlocked(f"INPUT_ADMISSION_RELEASE_FILE_BOUNDS_INVALID:{name}")
    if release.get("provenance_mode") != FROZEN_OBSERVED_PROVENANCE_MODE:
        raise AdmissionBlocked("FROZEN_INPUT_PROVENANCE_MODE_REQUIRED")
    expected_projection = {
        "input_binding": "JSON_OBJECT", "input_manifest": "JSON_OBJECT",
        "train_x64": "NPY_FLOAT32_2D", "train_y": "NPY_BINARY_NUMERIC_1D",
        "train_keys": "CSV_GZIP_IDENTITY", "eval_x64": "NPY_FLOAT32_2D",
        "eval_meta": "CSV_GZIP_IDENTITY_ONLY", "evaluation_calendar": "CSV_GZIP_CALENDAR",
        "pretruth_scores": "CSV_GZIP_IDENTITY_ONLY_NO_PROBABILITY",
    }
    for name, projection in expected_projection.items():
        if files[name].get("projection") != projection:
            raise AdmissionBlocked(f"INPUT_ADMISSION_RELEASE_PROJECTION_MISMATCH:{name}")
    if files["pretruth_scores"].get("identity_columns") != ["session_id", "code", "scoreable"]:
        raise AdmissionBlocked("PRETRUTH_RELEASE_MUST_BIND_IDENTITY_ONLY_PROJECTION")
    if release.get("historical_producer_status") != "LINEAGE_UNAVAILABLE":
        raise AdmissionBlocked("HISTORICAL_PRODUCER_LIMITATION_MUST_REMAIN_EXPLICIT")
    input_binding_descriptor = files["input_binding"]
    current_binding_path = Path(input_binding_path)
    bindings_root = project_root / "research" / "hk_burst_f5" / "batches" / "breadth1_r3_frozen_input_20261011" / "bindings"
    if (
        current_binding_path.is_symlink()
        or not current_binding_path.is_absolute()
        or Path(input_binding_descriptor["path"]).resolve() != current_binding_path.resolve()
        or current_binding_path.resolve().parent != bindings_root.resolve()
        or input_binding_descriptor["sha256"] != input_binding_sha256
    ):
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH")
    manifest = files["input_manifest"]
    if manifest.get("sha256") != EXPECTED_MANIFEST_SHA256:
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_MANIFEST_SHA_DIFFERS_FROM_FROZEN_PROXY")
    panel_root = release.get("panel_root")
    if not isinstance(panel_root, str) or not Path(panel_root).is_absolute():
        raise AdmissionBlocked("INPUT_ADMISSION_RELEASE_PANEL_ROOT_MISSING")
    if "actions" in release or any(name in release for name in ("fit", "predict", "truth_decode")):
        raise AdmissionBlocked("INPUT_ADMISSION_READ_RELEASE_CANNOT_AUTHORIZE_MODEL_OR_TRUTH_ACTIONS")
    return VerifiedInputAdmissionReadRelease(
        path=path,
        expected_sha256=actual,
        release_value=dict(release),
        contract_sha256=contract_sha256,
        input_binding_sha256=input_binding_sha256,
        bytes_read=len(payload),
        payload=payload,
    )


def load_verified_r7_resume_read_release(
    path: Path,
    expected_sha256: str,
    *,
    contract_sha256: str,
    input_binding_sha256: str,
    input_binding_path: Path,
    resume_authorization: Mapping[str, Any],
) -> VerifiedInputAdmissionReadRelease:
    """Verify the new release is the four-field control rebind of original R7.

    The original R7 release and its registry claim stay immutable. This
    separate, reviewed resume release changes only the code/control identities
    needed to attest this recovery build and the stale pending-binding
    descriptor/path. It does not change the frozen data files or read caps.
    """
    from f5_breadth1_budget import (
        PANEL_HEADER_RECOVERY_READ_RELEASE_PATH,
        PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH,
    )
    normalization = resume_authorization.get("read_release_normalization")
    authorization_ref = resume_authorization.get("authorization_ref")
    if (
        not isinstance(normalization, Mapping)
        or not isinstance(authorization_ref, Mapping)
        or normalization.get("original_path") != str(PANEL_HEADER_RECOVERY_READ_RELEASE_PATH.resolve())
        or normalization.get("resume_path") != str(Path(path).resolve())
        or normalization.get("resume_sha256") != expected_sha256
        or normalization.get("resume_contract_sha256") != contract_sha256
        or normalization.get("resume_binding_sha256") != input_binding_sha256
        or authorization_ref.get("path") != str(PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH.resolve())
        or not _is_sha256(authorization_ref.get("sha256"))
    ):
        raise AdmissionBlocked("R7_RESUME_READ_RELEASE_AUTHORIZATION_IDENTITY_MISMATCH")
    loaded = load_verified_input_admission_read_release(
        path, expected_sha256, contract_sha256=contract_sha256,
        input_binding_sha256=input_binding_sha256,
        input_binding_path=input_binding_path,
        resume_authorization=resume_authorization,
    )
    original_path = PANEL_HEADER_RECOVERY_READ_RELEASE_PATH
    if original_path.is_symlink() or not original_path.is_file() or original_path.stat().st_size > 1024 * 1024:
        raise AdmissionBlocked("R7_ORIGINAL_READ_RELEASE_PATH_INVALID")
    original_payload = _bounded_file_read(original_path, 1024 * 1024, "original R7 read release")
    original_sha = sha256(original_payload).hexdigest()
    if original_sha != normalization.get("original_sha256"):
        raise AdmissionBlocked("R7_ORIGINAL_READ_RELEASE_SHA_MISMATCH")
    original = _parse_json_snapshot(original_payload, "R7_ORIGINAL_READ_RELEASE")
    expected = json.loads(json.dumps(original))
    expected["contract_sha256"] = contract_sha256
    expected["input_binding_sha256"] = input_binding_sha256
    expected["files"]["input_binding"]["path"] = str(Path(input_binding_path).resolve())
    expected["files"]["input_binding"]["sha256"] = input_binding_sha256
    if expected != dict(loaded.release_value):
        raise AdmissionBlocked("R7_RESUME_READ_RELEASE_CHANGED_FROZEN_READ_SCOPE")
    mutations = normalization.get("only_mutation_json_pointers")
    if mutations != [
        "/contract_sha256", "/input_binding_sha256",
        "/files/input_binding/path", "/files/input_binding/sha256",
    ]:
        raise AdmissionBlocked("R7_RESUME_READ_RELEASE_MUTATION_SET_MISMATCH")
    return loaded


def audit_real_input_admission(
    release: VerifiedInputAdmissionReadRelease,
    *,
    registry_claim: Any,
    registry_adapter: Any = None,
    resume_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one bounded first-pass audit without requiring an admission PASS.

    This is the bootstrap gate. Its output PASS is computed only after the
    exact released reads, producer link, row/key/flag/return checks, and B
    aggregation succeed. It never reads labels, scores, model artifacts, or
    truth-bearing controls.
    """

    from f5_breadth1_core import EXPERIMENT_ID, ROUTE_ID
    from f5_breadth1_budget import (
        ActionBudgetClaim, CANDIDATE_ID, PANEL_HEADER_RECOVERY_ACTION_KEY, PANEL_HEADER_RECOVERY_EXECUTION_ID,
        PANEL_HEADER_R5_RECOVERY_EXECUTION_ID, PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
        PANEL_HEADER_R6_RECOVERY_EXECUTION_ID, PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
        PANEL_HEADER_R4_RECOVERY_EXECUTION_ID, PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
        PANEL_HEADER_FAILED_EXECUTION_ID, PANEL_HEADER_FAILED_RECEIPT_SHA256,
        _valid_prior_panel_header_diagnostic, _valid_prior_train_label_diagnostic,
        _valid_prior_panel_header_runtime_failure,
        _valid_prior_panel_header_r5_failure,
        _valid_prior_panel_header_r6_failure,
        RECOVERY_ACTION,
    )
    project_root = Path(__file__).resolve().parents[3]
    resume = resume_context if isinstance(resume_context, Mapping) else None
    resume_controls = resume.get("resume_control_identity") if resume is not None else None
    old_identity = resume.get("original_r7_identity") if resume is not None else None
    if (
        type(registry_claim) is not ActionBudgetClaim
        or registry_adapter is None
        or not callable(getattr(registry_adapter, "list_events", None))
        or Path(getattr(registry_adapter, "registry_path", "")).resolve()
        != (project_root / "contracts" / "EXPERIMENT_REGISTRY.jsonl").resolve()
        or getattr(registry_claim, "route_id", None) != ROUTE_ID
        or getattr(registry_claim, "candidate_id", None) != CANDIDATE_ID
        or getattr(registry_claim, "action", None) != RECOVERY_ACTION
        or getattr(registry_claim, "action_key", None) != PANEL_HEADER_RECOVERY_ACTION_KEY
        or getattr(registry_claim, "execution_id", None) != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or getattr(registry_claim, "sealed_status", None) != "NOT_CHECKED"
    ):
        raise AdmissionBlocked("FIRST_PASS_REQUIRES_FIXED_OFFICIAL_INPUT_ADMISSION_ACTION_CLAIM")
    if not isinstance(release, VerifiedInputAdmissionReadRelease):
        raise AdmissionBlocked("FIRST_PASS_REQUIRES_VERIFIED_READ_RELEASE")
    if resume is None:
        if (
            registry_claim.contract_sha256 != release.contract_sha256
            or registry_claim.input_binding_sha256 != release.input_binding_sha256
            or registry_claim.release_sha256 != release.expected_sha256
        ):
            raise AdmissionBlocked("FIRST_PASS_REGISTRY_CLAIM_BINDING_MISMATCH")
    elif (
        not isinstance(resume_controls, Mapping)
        or not isinstance(old_identity, Mapping)
        or resume.get("status") != "AUTHORIZED_PRETARGET_R7_RESUMPTION"
        or registry_claim.contract_sha256 != old_identity.get("contract_sha256")
        or registry_claim.input_binding_sha256 != old_identity.get("input_binding_sha256")
        or registry_claim.release_sha256 != old_identity.get("read_release_sha256")
        or release.contract_sha256 != resume_controls.get("contract_sha256")
        or release.input_binding_sha256 != resume_controls.get("pending_binding_sha256")
        or release.expected_sha256 != resume_controls.get("read_release_sha256")
    ):
        raise AdmissionBlocked("R7_RESUME_REGISTRY_CLAIM_AND_REBOUND_CONTROLS_MISMATCH")
    # The claim method has released the official registry lock before this
    # read. Verify the durable start outside that lock; never nest list_events
    # under the action adapter's lock.
    lifecycle = [
        event for event in registry_adapter.list_events(EXPERIMENT_ID)
        if event.get("execution_id") == registry_claim.execution_id
    ]
    starts = [event for event in lifecycle if event.get("event_type") == "RUN_STARTED"]
    start = starts[0] if len(starts) == 1 else None
    metrics = start.get("deterministic_metrics") if isinstance(start, Mapping) else None
    expected_lifecycle_count = 2 if resume is not None else 1
    resume_terminal = (
        next((event for event in lifecycle if event.get("event_type") == "TERMINAL"), None)
        if resume is not None else None
    )
    resume_failure = resume.get("preserved_original_failure") if resume is not None else None
    if (
        len(lifecycle) != expected_lifecycle_count
        or not isinstance(start, Mapping)
        or start.get("registry_event_id") != registry_claim.registry_event_id
        or start.get("event_sha256") != registry_claim.registry_event_sha256
        or start.get("contract_sha256") != (old_identity.get("contract_sha256") if resume is not None else release.contract_sha256)
        or start.get("input_binding_sha256") != (old_identity.get("input_binding_sha256") if resume is not None else release.input_binding_sha256)
        or start.get("budget_action") != RECOVERY_ACTION
        or start.get("budget_action_key") != registry_claim.action_key
        or start.get("budget_action_debit") != 1
        or not isinstance(metrics, Mapping)
        or metrics.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY"
        or metrics.get("real_fit_budget_debit") != 0
        or metrics.get("budget_release_sha256") != (old_identity.get("read_release_sha256") if resume is not None else release.expected_sha256)
        or metrics.get("recovery_grant_id") != INPUT_ADMISSION_RECOVERY_GRANT_ID
        or metrics.get("linked_failed_execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
        or metrics.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
        or metrics.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
        or metrics.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
        or metrics.get("prior_panel_header_runtime_failure_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
        or metrics.get("prior_panel_header_r5_failure_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
        or metrics.get("prior_panel_header_r6_failure_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
        or (resume is not None and (
            not isinstance(resume_failure, Mapping)
            or not isinstance(resume_terminal, Mapping)
            or resume_terminal.get("event_sha256") != resume_failure.get("terminal_event_sha256")
            or resume_terminal.get("registry_event_id") != resume_failure.get("terminal_event_id")
            or resume_terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or resume_terminal.get("budget_action_debit") != 0
            or resume_terminal.get("started_event_sha256") != start.get("event_sha256")
            or resume_terminal.get("contract_sha256") != start.get("contract_sha256")
            or resume_terminal.get("input_binding_sha256") != start.get("input_binding_sha256")
            or resume_terminal.get("budget_action_key") != registry_claim.action_key
            or resume_terminal.get("budget_action") != RECOVERY_ACTION
            or not isinstance(resume_failure.get("pipeline_terminal_path"), str)
            or not Path(resume_failure["pipeline_terminal_path"]).is_file()
            or Path(resume_failure["pipeline_terminal_path"]).is_symlink()
            or sha256(Path(resume_failure["pipeline_terminal_path"]).read_bytes()).hexdigest()
                != resume_failure.get("pipeline_terminal_sha256")
        ))
    ):
        raise AdmissionBlocked("FIRST_PASS_FIXED_INPUT_ADMISSION_ACTION_NOT_PRESENT_IN_OFFICIAL_REGISTRY")
    registry_start_event_sha256 = registry_claim.registry_event_sha256
    if not _is_sha256(registry_start_event_sha256):
        raise AdmissionBlocked("FIRST_PASS_OFFICIAL_START_EVENT_SHA_MISSING")
    # The output receipt is a new batch artifact and may not overwrite prior evidence.
    from pathlib import Path as _Path

    project_root = _Path(__file__).resolve().parents[3]
    batch_root = project_root / "research" / "hk_burst_f5" / "batches" / "breadth1_r3_frozen_input_20261011"
    receipt_path = _Path(release.release_value["output_receipt_path"]).resolve()
    try:
        receipt_path.relative_to((batch_root / "receipts" / "input_admission").resolve())
    except ValueError as exc:
        raise AdmissionBlocked("INPUT_ADMISSION_RECEIPT_MUST_STAY_IN_BATCH") from exc
    if receipt_path.exists():
        raise AdmissionBlocked("INPUT_ADMISSION_RECEIPT_ALREADY_EXISTS_NO_OVERWRITE")

    budget = validate_admission_read_budget(release.release_value.get("read_budget"))
    files = release.release_value["files"]
    cache: dict[str, bytes] = {}
    read_records: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    accounting_complete = True
    pre_admission_binding_snapshot: Mapping[str, Any] | None = None
    prior_train_label_diagnostic = release.release_value.get("prior_train_label_diagnostic")
    prior_panel_header_diagnostic = release.release_value.get("prior_panel_header_diagnostic")
    prior_panel_header_runtime_failure = release.release_value.get("prior_panel_header_runtime_failure")
    prior_panel_header_r5_failure = release.release_value.get("prior_panel_header_r5_failure")
    prior_panel_header_r6_failure = release.release_value.get("prior_panel_header_r6_failure")
    prepared_for_fit: PreparedRealInputs | None = None
    key_identity_diagnostics: dict[str, Any] | None = None
    train_label_identity: dict[str, Any] | None = None

    def read_file(name: str, path: _Path, expected_sha: str, max_bytes: int) -> bytes:
        nonlocal total_bytes, accounting_complete
        if path.is_symlink():
            raise AdmissionBlocked(f"INPUT_ADMISSION_SYMLINK_NOT_ALLOWED:{name}")
        resolved = path.resolve(strict=True)
        key = str(resolved)
        if key in cache:
            if sha256(cache[key]).hexdigest() != expected_sha:
                raise AdmissionBlocked(f"INPUT_ADMISSION_SHARED_FILE_SHA_MISMATCH:{name}")
            return cache[key]
        if len(read_records) >= budget["max_files"]:
            raise AdmissionBlocked("INPUT_ADMISSION_FILE_COUNT_BUDGET_EXCEEDED")
        if max_bytes > budget["max_file_bytes"]:
            raise AdmissionBlocked(f"INPUT_ADMISSION_FILE_CAP_EXCEEDS_RELEASE:{name}")
        remaining = budget["max_total_bytes"] - total_bytes
        try:
            payload = _bounded_file_read(resolved, min(max_bytes, remaining), name)
        except BaseException as exc:
            # The reader did not return a measurable snapshot. Preserve the
            # attempted path and known prefix; never report an unknown read as 0.
            accounting_complete = False
            read_records[name] = {
                "path": key, "sha256": None, "bytes": None,
                "expected_sha256": expected_sha,
                "read_status": "FAILED_READ_ACCOUNTING_INCOMPLETE",
                "error_type": type(exc).__name__,
            }
            raise
        total_bytes += len(payload)
        read_records[name] = {"path": key, "sha256": None, "bytes": len(payload)}
        digest = sha256(payload).hexdigest()
        read_records[name]["sha256"] = digest
        if digest != expected_sha:
            read_records[name]["expected_sha256"] = expected_sha
            read_records[name]["read_status"] = "READ_COMPLETED_SHA_MISMATCH"
            raise AdmissionBlocked(f"INPUT_ADMISSION_FILE_SHA_MISMATCH:{name}")
        # Only a verified snapshot can be reused; a failed read still consumes
        # its file/byte allowance and is retained above in the receipt.
        cache[key] = payload
        return payload

    def read_accounting_snapshot() -> dict[str, Any]:
        return {
            "file_count": len(read_records) if accounting_complete else None,
            "total_bytes": total_bytes if accounting_complete else None,
            "files": read_records,
            "accounting_complete": accounting_complete,
            "status": "COMPLETE" if accounting_complete else "CANNOT_CONFIRM",
            "attempted_file_count": len(read_records),
            "completed_file_count": sum(isinstance(record.get("bytes"), int) for record in read_records.values()),
            "known_total_bytes": total_bytes,
        }

    def finish_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
        from f5_breadth1_core import write_json_exclusive

        receipt["receipt_path"] = str(receipt_path)
        receipt["release_sha256"] = release.expected_sha256
        receipt["contract_sha256"] = release.contract_sha256
        receipt["input_binding_sha256"] = release.input_binding_sha256
        receipt["pre_admission_binding_sha256"] = release.input_binding_sha256
        binding_record = receipt.get("actual_read", {}).get("files", {}).get("input_binding")
        receipt["pre_admission_binding_path"] = (
            binding_record.get("path") if isinstance(binding_record, Mapping) else None
        )
        receipt["read_release_sha256"] = release.expected_sha256
        receipt["registry_execution_id"] = registry_claim.execution_id
        receipt["registry_start_event_sha256"] = registry_start_event_sha256
        receipt["registry_budget_action"] = registry_claim.action
        receipt["registry_budget_action_key"] = registry_claim.action_key
        receipt["recovery_grant_id"] = INPUT_ADMISSION_RECOVERY_GRANT_ID
        if resume is not None:
            receipt["r7_resume"] = {
                "authorization_path": resume.get("authorization_path"),
                "authorization_sha256": resume.get("authorization_sha256"),
                "checkpoint_path": resume.get("checkpoint_path"),
                "checkpoint_sha256": resume.get("checkpoint_sha256"),
                "physical_invocation_index": 3,
                "logical_r7_action_debit_total": 1,
                "additional_r7_action_debit": 0,
                "original_start_event_sha256": start.get("event_sha256"),
                "original_failed_terminal_event_sha256": resume_failure.get("terminal_event_sha256"),
                "original_contract_sha256": old_identity.get("contract_sha256"),
                "original_input_binding_sha256": old_identity.get("input_binding_sha256"),
                "original_read_release_sha256": old_identity.get("read_release_sha256"),
                "resume_contract_sha256": release.contract_sha256,
                "resume_input_binding_sha256": release.input_binding_sha256,
                "resume_read_release_sha256": release.expected_sha256,
            }
        receipt["linked_failed_execution_id"] = PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
        receipt["linked_failed_receipt_sha256"] = PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
        receipt["linked_r5_ancestor_execution_id"] = PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
        receipt["linked_r5_ancestor_receipt_sha256"] = PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
        receipt["linked_r4_ancestor_failure_execution_id"] = PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
        receipt["linked_r4_ancestor_failure_receipt_sha256"] = PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
        receipt["linked_r3_parent_header_failure_execution_id"] = PANEL_HEADER_FAILED_EXECUTION_ID
        receipt["linked_r3_parent_header_failure_receipt_sha256"] = PANEL_HEADER_FAILED_RECEIPT_SHA256
        if prior_train_label_diagnostic is not None:
            receipt["prior_train_label_diagnostic"] = dict(prior_train_label_diagnostic)
        if prior_panel_header_diagnostic is not None:
            receipt["prior_panel_header_diagnostic"] = dict(prior_panel_header_diagnostic)
        if prior_panel_header_runtime_failure is not None:
            receipt["prior_panel_header_runtime_failure"] = dict(prior_panel_header_runtime_failure)
        if prior_panel_header_r5_failure is not None:
            receipt["prior_panel_header_r5_failure"] = dict(prior_panel_header_r5_failure)
        if prior_panel_header_r6_failure is not None:
            receipt["prior_panel_header_r6_failure"] = dict(prior_panel_header_r6_failure)
        receipt_sha = write_json_exclusive(receipt, receipt_path)
        result = {**receipt, "receipt_sha256": receipt_sha}
        if pre_admission_binding_snapshot is not None:
            # Internal handoff only: these are the already-read bytes parsed
            # for the audit, returned in memory so the runner can create a
            # separate final binding without reopening a target input.
            result["_pre_admission_binding_snapshot"] = dict(pre_admission_binding_snapshot)
        return result

    # The release loader already opened and SHA-verified this exact file once.
    # Seed the cache from that immutable snapshot; reopening it here would
    # double the physical read while reporting a unique-file count of one.
    release_path = str(release.path.resolve())
    if len(release.payload) != release.bytes_read or sha256(release.payload).hexdigest() != release.expected_sha256:
        raise AdmissionBlocked("INPUT_ADMISSION_READ_RELEASE_SNAPSHOT_INVALID")
    cache[release_path] = release.payload
    total_bytes = len(release.payload)
    read_records["input_admission_read_release"] = {
        "path": release_path,
        "sha256": release.expected_sha256,
        "bytes": release.bytes_read,
    }

    try:
        binding_descriptor = files["input_binding"]
        binding_bytes = read_file(
            "input_binding", _Path(binding_descriptor["path"]),
            binding_descriptor["sha256"], binding_descriptor["max_bytes"],
        )
        if sha256(binding_bytes).hexdigest() != release.input_binding_sha256:
            raise AdmissionBlocked("INPUT_ADMISSION_BINDING_SNAPSHOT_SHA_MISMATCH")
        binding_value = _parse_json_snapshot(binding_bytes, "REAL_INPUT_BINDING")
        pre_admission_binding_snapshot = dict(binding_value)
        binding_prior_diagnostic = binding_value.get("prior_train_label_diagnostic")
        binding_prior_panel_diagnostic = binding_value.get("prior_panel_header_diagnostic")
        binding_prior_panel_runtime_failure = binding_value.get("prior_panel_header_runtime_failure")
        binding_prior_panel_r5_failure = binding_value.get("prior_panel_header_r5_failure")
        binding_prior_panel_r6_failure = binding_value.get("prior_panel_header_r6_failure")
        if (
            not _valid_prior_train_label_diagnostic(prior_train_label_diagnostic)
            or binding_prior_diagnostic != prior_train_label_diagnostic
            or not _valid_prior_panel_header_diagnostic(prior_panel_header_diagnostic)
            or binding_prior_panel_diagnostic != prior_panel_header_diagnostic
            or not _valid_prior_panel_header_runtime_failure(prior_panel_header_runtime_failure)
            or binding_prior_panel_runtime_failure != prior_panel_header_runtime_failure
            or not _valid_prior_panel_header_r5_failure(prior_panel_header_r5_failure)
            or binding_prior_panel_r5_failure != prior_panel_header_r5_failure
            or not _valid_prior_panel_header_r6_failure(prior_panel_header_r6_failure)
            or binding_prior_panel_r6_failure != prior_panel_header_r6_failure
        ):
            raise AdmissionBlocked("TRAIN_LABEL_DIAGNOSTIC_SUMMARY_MISSING_OR_INVALID")
        source_binding = binding_value.get("source_binding")
        if (
            not isinstance(source_binding, Mapping)
            or source_binding.get("provenance_mode") != FROZEN_OBSERVED_PROVENANCE_MODE
            or source_binding.get("status") != "LINEAGE_UNAVAILABLE"
            or release.release_value.get("historical_producer_status") != "LINEAGE_UNAVAILABLE"
        ):
            raise AdmissionBlocked("FROZEN_INPUT_AS_OBSERVED_RESEARCH_LIMITATION_NOT_BOUND")
        frozen_artifacts = binding_value.get("frozen_artifacts")
        if not isinstance(frozen_artifacts, Mapping) or set(frozen_artifacts) != {
            "input_manifest", "train_x64", "train_y", "train_keys", "eval_x64", "eval_meta",
            "evaluation_calendar", "pretruth_scores",
        }:
            raise AdmissionBlocked("FROZEN_ARTIFACT_IDENTITY_SET_MISSING")
        for name, expected in frozen_artifacts.items():
            descriptor = files.get(name)
            if (
                not isinstance(expected, Mapping) or not isinstance(descriptor, Mapping)
                or descriptor.get("path") != expected.get("path")
                or descriptor.get("sha256") != expected.get("sha256")
                or descriptor.get("max_bytes") != expected.get("max_bytes")
            ):
                raise AdmissionBlocked(f"FROZEN_ARTIFACT_IDENTITY_DIFFERS_FROM_BINDING:{name}")
        parent_source = binding_value.get("parent_source")
        bound_read = binding_value.get("first_pass_read_release")
        release_budget = release.release_value.get("read_budget")
        panel_cap = parent_source.get("max_panel_bytes") if isinstance(parent_source, Mapping) else None
        calendar_cap = parent_source.get("max_calendar_bytes") if isinstance(parent_source, Mapping) else None
        if (
            not isinstance(parent_source, Mapping)
            or isinstance(panel_cap, bool) or not isinstance(panel_cap, int) or panel_cap < 1 or panel_cap > budget["max_file_bytes"]
            or isinstance(calendar_cap, bool) or not isinstance(calendar_cap, int) or calendar_cap < 1 or calendar_cap > budget["max_file_bytes"]
            or str(Path(parent_source.get("panel_root", "")).resolve())
            != str(Path(release.release_value.get("panel_root", "")).resolve())
            or not isinstance(bound_read, Mapping)
            or not isinstance(release_budget, Mapping)
            or any(release_budget.get(key) != bound_read.get(key) for key in ("max_files", "max_file_bytes", "max_total_bytes"))
        ):
            raise AdmissionBlocked("FROZEN_PARENT_PANEL_ROOT_DIFFERS_FROM_BINDING")

        train_descriptor = files["train_keys"]
        calendar_descriptor = files["evaluation_calendar"]
        manifest_descriptor = files["input_manifest"]
        train_x64_descriptor = files["train_x64"]
        train_y_descriptor = files["train_y"]
        eval_x64_descriptor = files["eval_x64"]
        eval_meta_descriptor = files["eval_meta"]
        pretruth_descriptor = files["pretruth_scores"]
        train_bytes = read_file(
            "train_keys", _Path(train_descriptor["path"]), train_descriptor["sha256"], train_descriptor["max_bytes"]
        )
        eval_calendar_bytes = read_file(
            "evaluation_calendar", _Path(calendar_descriptor["path"]), calendar_descriptor["sha256"], calendar_descriptor["max_bytes"]
        )
        manifest_bytes = read_file(
            "input_manifest", _Path(manifest_descriptor["path"]), manifest_descriptor["sha256"], manifest_descriptor["max_bytes"]
        )
        train_x64_bytes = read_file("train_x64", _Path(train_x64_descriptor["path"]), train_x64_descriptor["sha256"], train_x64_descriptor["max_bytes"])
        train_y_bytes = read_file("train_y", _Path(train_y_descriptor["path"]), train_y_descriptor["sha256"], train_y_descriptor["max_bytes"])
        eval_x64_bytes = read_file("eval_x64", _Path(eval_x64_descriptor["path"]), eval_x64_descriptor["sha256"], eval_x64_descriptor["max_bytes"])
        eval_meta_bytes = read_file("eval_meta", _Path(eval_meta_descriptor["path"]), eval_meta_descriptor["sha256"], eval_meta_descriptor["max_bytes"])
        pretruth_bytes = read_file("pretruth_scores", _Path(pretruth_descriptor["path"]), pretruth_descriptor["sha256"], pretruth_descriptor["max_bytes"])
        train_keys = _csv_from_bytes(train_bytes, "train_keys", required=("code", "session_id"))
        train_keys = train_keys.loc[:, ["code", "session_id"]].copy()
        train_keys["session_id"] = _strict_int_values(train_keys["session_id"], "train_keys.session_id")
        eval_calendar = _csv_from_bytes(eval_calendar_bytes, "evaluation_calendar", required=("session_id", "market_date"))
        eval_calendar = eval_calendar.loc[:, ["session_id", "market_date"]].copy()
        eval_calendar["session_id"] = _strict_int_values(eval_calendar["session_id"], "evaluation_calendar.session_id")
        train_x64 = _npy_from_bytes(train_x64_bytes, "train_x64", np.float32, 2)
        train_y = _npy_from_bytes(train_y_bytes, "train_y", None, 1)
        eval_x64 = _npy_from_bytes(eval_x64_bytes, "eval_x64", np.float32, 2)
        eval_meta = _csv_from_bytes(eval_meta_bytes, "eval_meta identity projection", required=("code", "session_id"))
        eval_meta = eval_meta.loc[:, ["code", "session_id"]].copy()
        eval_projection = _pretruth_projection(pretruth_bytes, pretruth_descriptor)
        eval_meta, eval_projection, key_identity_diagnostics = _align_pretruth_to_eval_identity(eval_meta, eval_projection)
        if train_x64.shape != (539631, 64) or train_y.shape != (539631,) or len(train_keys) != len(train_y):
            raise InputContractError("FROZEN_TRAIN_ARRAY_OR_KEY_SHAPE_MISMATCH")
        if eval_x64.shape != (169986, 64) or len(eval_projection) != len(eval_x64):
            raise InputContractError("FROZEN_EVAL_ARRAY_OR_PRETRUTH_IDENTITY_SHAPE_MISMATCH")
        train_y_binary_domain = bool(np.isin(train_y, [0, 1]).all())
        train_y_positive_count = int((train_y == 1).sum())
        train_label_identity = {
            "train_y_shape": list(train_y.shape),
            "train_y_dtype": str(train_y.dtype),
            "train_y_dtype_kind_allowed": train_y.dtype.kind in "iuf",
            "train_y_binary_domain": train_y_binary_domain,
            "train_y_min": float(np.min(train_y)) if train_y.size else None,
            "train_y_max": float(np.max(train_y)) if train_y.size else None,
            "train_positive_rows": train_y_positive_count,
            "train_y_positive_count_is_899": train_y_positive_count == 899,
        }
        if (
            not train_label_identity["train_y_dtype_kind_allowed"]
            or not train_y_binary_domain
            or train_y_positive_count != 899
        ):
            raise InputContractError(
                "FROZEN_TRAIN_LABEL_IDENTITY_MISMATCH",
                diagnostics={"train_label_identity": dict(train_label_identity)},
            )
        if train_keys.duplicated(["code", "session_id"]).any() or eval_projection.duplicated(["code", "session_id"]).any():
            raise InputContractError("FROZEN_ROW_KEY_DUPLICATE")
        mask_values = pd.to_numeric(eval_projection["scoreable"], errors="raise").to_numpy(dtype=float)
        if not np.isin(mask_values, [0.0, 1.0]).all():
            raise InputContractError("PRETRUTH_SCOREABLE_MASK_NOT_BINARY")
        scoreable_mask = mask_values.astype(bool)
        if not np.isfinite(train_x64[~np.isnan(train_x64)]).all() or not np.isfinite(eval_x64[~np.isnan(eval_x64)]).all():
            raise InputContractError("FROZEN_FEATURE_ARRAY_CONTAINS_INFINITY")
        required_sessions = required_sessions_from_keys_and_calendar(train_keys, eval_calendar)
        manifest = _parse_json_snapshot(manifest_bytes, "INPUT_MANIFEST")
        if manifest.get("schema") != "SPIKE5_INPUT_V1" or manifest.get("membership_mode") != "FIXED_CURRENT_SNAPSHOT_PROXY":
            raise InputContractError("frozen parent manifest schema or membership changed")
        features_sha = (manifest.get("source_hashes", {}).get("features") or {}).get("sha256")
        if features_sha != EXPECTED_FEATURES_SHA256:
            raise AdmissionBlocked("registered full-history feature identity changed")
        codes = _unique_nonempty_strings(manifest.get("codes", ()), "manifest.codes")
        panel_root_value = release.release_value["panel_root"]
        panel_root = _Path(panel_root_value)
        if panel_root.is_symlink() or not panel_root.is_dir():
            raise AdmissionBlocked("INPUT_ADMISSION_PANEL_ROOT_INVALID")
        panel_root = panel_root.resolve(strict=True)
        panels = manifest.get("panels")
        if not isinstance(panels, list) or len(panels) != len(codes) or len(panels) + 10 > budget["max_files"]:
            raise AdmissionBlocked("INPUT_ADMISSION_PANEL_COUNT_EXCEEDS_RELEASE")
        panel_codes = [str(item.get("code", "")) for item in panels if isinstance(item, Mapping)]
        if len(panel_codes) != len(panels) or set(panel_codes) != set(codes) or len(set(panel_codes)) != len(panel_codes):
            raise InputContractError("manifest panel identities are incomplete or duplicated")
        frames: list[pd.DataFrame] = []
        for item in panels:
            raw_relative = str(item.get("path", ""))
            relative = PurePosixPath(raw_relative)
            if not raw_relative or "\\" in raw_relative or relative.is_absolute() or ".." in relative.parts:
                raise AdmissionBlocked("unsafe panel path in frozen manifest")
            panel_path = panel_root / _Path(*relative.parts)
            try:
                panel_path.resolve(strict=True).relative_to(panel_root)
            except (ValueError, FileNotFoundError) as exc:
                raise AdmissionBlocked("panel path resolves outside or is missing from bound root") from exc
            payload = read_file(f"panel:{item['code']}", panel_path, str(item.get("sha256", "")), panel_cap)
            _verify_gzip_csv_header(payload, f"parent panel {item['code']}", PANEL_SOURCE_COLUMNS)
            frame = pd.read_csv(
                BytesIO(payload), compression="gzip", usecols=list(PANEL_SOURCE_COLUMNS),
                # Validate parsed integer/binary values before narrowing:
                # int8 parsing silently wraps 257 to 1 and coerces True to 1.
                dtype={"code": "string"},
            )
            expected_panel_rows = item.get("rows")
            if isinstance(expected_panel_rows, bool) or not isinstance(expected_panel_rows, int) or len(frame) != expected_panel_rows:
                raise InputContractError(f"parent panel row count differs from frozen manifest: {item['code']}")
            frames.append(frame)
        parent = pd.concat(frames, ignore_index=True)

        calendar_item = manifest.get("calendar")
        if not isinstance(calendar_item, Mapping):
            raise AdmissionBlocked("parent calendar pointer missing")
        calendar_relative = PurePosixPath(str(calendar_item.get("path", "")))
        if calendar_relative.is_absolute() or ".." in calendar_relative.parts:
            raise AdmissionBlocked("unsafe parent calendar path")
        parent_calendar_path = panel_root / _Path(*calendar_relative.parts)
        try:
            parent_calendar_path.resolve(strict=True).relative_to(panel_root)
        except (ValueError, FileNotFoundError) as exc:
            raise AdmissionBlocked("parent calendar path resolves outside or is missing from bound root") from exc
        parent_calendar_bytes = read_file(
            "parent_calendar", parent_calendar_path, str(calendar_item.get("sha256", "")), calendar_cap
        )
        _verify_gzip_csv_header(parent_calendar_bytes, "parent calendar", ("session_id", "market_date"))
        parent_calendar = pd.read_csv(
            BytesIO(parent_calendar_bytes), compression="gzip", usecols=["session_id", "market_date"]
        )
        if not {"session_id", "market_date"} <= set(parent_calendar.columns):
            raise InputContractError("parent calendar lacks session/date identity")
        parent_calendar = parent_calendar.loc[:, ["session_id", "market_date"]]
        parent_sessions = _strict_int_values(parent_calendar["session_id"], "parent_calendar.session_id")
        parent = _attach_parent_market_date(parent, parent_calendar)
        if not set(required_sessions) <= set(parent_sessions):
            raise InputContractError("prebound required session is absent from parent calendar")
        eval_map = validate_calendar_dates_for_admission(eval_calendar)
        parent_map = validate_calendar_dates_for_admission(parent_calendar)
        if any(parent_map.get(session) != date for session, date in eval_map.items()):
            raise InputContractError("prebound evaluation calendar differs from parent calendar")

        producer = ProducerBinding(
            synthetic=False,
            provenance_mode=FROZEN_OBSERVED_PROVENANCE_MODE,
            full_grid_and_flag_join_verified=True,
        )
        data_audit = _audit_parent_pool_rows(
            parent,
            expected_codes=codes,
            expected_sessions=parent_sessions,
            required_sessions=required_sessions,
            producer_binding=producer,
        )
        producer_status = "LINEAGE_UNAVAILABLE"
        blockers = list(data_audit["blockers"])
        breadth_summary = None
        if not blockers:
            breadth = aggregate_breadth1(
                parent,
                expected_codes=codes,
                expected_sessions=parent_sessions,
                required_sessions=required_sessions,
                producer_binding=producer,
            )
            breadth_summary = breadth.loc[:, ["session_id", "positive_finite_count", "finite_return_count", "ret_nan_count", "ret_nan_flag0_count", "ret_nan_flag1_count"]].to_dict(orient="records")
            train_x65, _, _ = append_breadth1_column(
                train_x64, train_keys, breadth, original_mask=np.ones(len(train_x64), dtype=np.bool_),
            )
            eval_keys = eval_projection.loc[:, ["code", "session_id"]].copy()
            eval_x65, mapped_eval_keys, mapped_mask = append_breadth1_column(
                eval_x64, eval_keys, breadth, original_mask=scoreable_mask,
            )
            if not np.array_equal(mapped_mask, scoreable_mask):
                raise InputContractError("PRETRUTH_SCOREABLE_MASK_CHANGED")
            score_row_keys = mapped_eval_keys.loc[mapped_mask].reset_index(drop=True)
            score_x = eval_x65[mapped_mask].copy()
            from f5_breadth1_core import npy_array_sha256, row_keys_sha256
            verified_arrays = {
                "train_x65_npy_sha256": npy_array_sha256(train_x65),
                "train_y_npy_sha256": npy_array_sha256(train_y),
                "score_x65_npy_sha256": npy_array_sha256(score_x),
                "eval_row_keys_sha256": row_keys_sha256(mapped_eval_keys),
                "score_row_keys_sha256": row_keys_sha256(score_row_keys),
                "scoreable_mask_npy_sha256": npy_array_sha256(scoreable_mask),
                "train_rows": int(len(train_x65)),
                "train_positive_rows": int(np.count_nonzero(train_y == 1)),
                "evaluation_G_rows": int(len(mapped_eval_keys)),
                "evaluation_S_rows": int(len(score_x)),
            }
        else:
            verified_arrays = None
        status = "PASS" if not blockers else (
            "INPUT_REJECTED" if any(item.startswith("REJECT:") for item in blockers) else
            "CANNOT_CONFIRM_INPUT_CLASSIFICATION"
        )
        receipt = {
            "schema": "F5_BREADTH1_INPUT_ADMISSION_RECEIPT_V1",
            "status": status,
            "decision": "INPUT_ADMISSION_PASS" if status == "PASS" else "NO_FIT_EFFECT_NOT_TESTED",
            "real_input_accessed": True,
            "input_manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "features_sha256": features_sha,
            "required_sessions": list(required_sessions),
            "parent_code_count": len(codes),
            "parent_session_count": len(parent_sessions),
            "parent_grid_rows": len(parent),
            "producer_status": producer_status,
            "provenance_mode": FROZEN_OBSERVED_PROVENANCE_MODE,
            "historical_producer_status": "LINEAGE_UNAVAILABLE",
            "historical_source_limitation": "Producer source/run receipt/environment/fill semantics and exact warmup causes are not recoverable; no cause is inferred for stored ret_1d NaNs.",
            "verified_arrays": verified_arrays,
            "verified_static_input_identity": {
                "train_x64_shape": list(train_x64.shape),
                **dict(train_label_identity or {}),
                "train_y_unique_value_counts": [
                    {"value": int(value) if isinstance(value, np.integer) else float(value), "count": int(count)}
                    for value, count in zip(*np.unique(train_y, return_counts=True))
                ],
                "eval_x64_shape": list(eval_x64.shape),
                "eval_identity_rows": int(len(eval_projection)),
                "pretruth_projection_columns": ["session_id", "code", "scoreable"],
                "probability_or_truth_parsed": False,
            },
            "evaluation_key_alignment": key_identity_diagnostics,
            "prior_train_label_diagnostic": dict(prior_train_label_diagnostic) if prior_train_label_diagnostic is not None else None,
            "prior_panel_header_diagnostic": dict(prior_panel_header_diagnostic) if prior_panel_header_diagnostic is not None else None,
            "prior_panel_header_runtime_failure": dict(prior_panel_header_runtime_failure) if prior_panel_header_runtime_failure is not None else None,
            "data_audit": data_audit,
            "breadth_by_session": breadth_summary,
            "read_budget": budget,
            "actual_read": read_accounting_snapshot(),
            "read_authorization": {
                "path": str(release.path.resolve()),
                "sha256": release.expected_sha256,
                "bytes": release.bytes_read,
                "counted_inside_input_file_budget": True,
            },
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    except BaseException as exc:
        receipt = {
            "schema": "F5_BREADTH1_INPUT_ADMISSION_RECEIPT_V1",
            "status": "INPUT_REJECTED" if isinstance(exc, InputContractError) else "CANNOT_CONFIRM_INPUT_ADMISSION",
            "decision": "NO_FIT_EFFECT_NOT_TESTED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "evaluation_key_alignment": (
                dict(key_identity_diagnostics)
                if key_identity_diagnostics is not None
                else dict(getattr(exc, "diagnostics", {}) or {})
            ),
            "verified_static_input_identity": dict(train_label_identity or {}),
            "header_diagnostics": dict(getattr(exc, "diagnostics", {}) or {}),
            "prior_train_label_diagnostic": dict(prior_train_label_diagnostic) if prior_train_label_diagnostic is not None else None,
            "prior_panel_header_diagnostic": dict(prior_panel_header_diagnostic) if prior_panel_header_diagnostic is not None else None,
            "prior_panel_header_runtime_failure": dict(prior_panel_header_runtime_failure) if prior_panel_header_runtime_failure is not None else None,
            "read_budget": budget,
            "actual_read": read_accounting_snapshot(),
            "read_authorization": {
                "path": str(release.path.resolve()),
                "sha256": release.expected_sha256,
                "bytes": release.bytes_read,
                "counted_inside_input_file_budget": True,
            },
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    result = finish_receipt(receipt)
    if receipt.get("status") == "PASS":
        prepared_receipt = {
            "schema": "F5_BREADTH1_REAL_PREPARE_RECEIPT_V1",
            "status": "PREPARED_AWAITING_WORKER",
            "input_binding_sha256": release.input_binding_sha256,
            "input_admission_receipt_sha256": result["receipt_sha256"],
            "verified_arrays": dict(verified_arrays),
            "artifact_files_read": int(receipt["actual_read"]["file_count"]),
            "artifact_bytes_read": int(receipt["actual_read"]["total_bytes"]),
            "feature_count_before_after": [64, 65],
            "training_rows": int(len(train_x65)),
            "evaluation_G_rows": int(len(mapped_eval_keys)),
            "evaluation_S_rows": int(len(score_x)),
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
        }
        prepared_for_fit = PreparedRealInputs(
            train_x=train_x65,
            train_y=train_y,
            score_x=score_x,
            eval_row_keys=mapped_eval_keys,
            score_row_keys=score_row_keys,
            scoreable_mask=scoreable_mask,
            calendar=eval_calendar,
            receipt=prepared_receipt,
        )
        result["_prepared_inputs"] = prepared_for_fit
    return result


@dataclass(frozen=True)
class ProducerBinding:
    """Evidence needed to classify a missing frozen return.

    ``synthetic=True`` is only for synthetic fixtures.  A real binding requires
    the exact producer-to-output receipt plus a pandas version or an explicit
    ``fill_method`` from the producer record.
    """

    synthetic: bool = False
    provenance_mode: str = "UNBOUND"
    full_grid_and_flag_join_verified: bool = False
    producer_sha256: str | None = None
    output_run_receipt_sha256: str | None = None
    pandas_version: str | None = None
    fill_method: str | None = None
    warmup_nan_keys: frozenset[tuple[str, int]] = frozenset()

    def require_real_source(self) -> None:
        if self.synthetic:
            raise AdmissionBlocked("synthetic producer binding cannot authorize real input access")
        if self.provenance_mode == FROZEN_OBSERVED_PROVENANCE_MODE:
            if not self.full_grid_and_flag_join_verified:
                raise AdmissionBlocked("FROZEN_INPUT_STRUCTURAL_GRID_AND_FLAG_CHECK_REQUIRED")
            return
        missing = []
        if not self.full_grid_and_flag_join_verified:
            missing.append("full_grid_and_flag_join_receipt")
        if not _is_sha256(self.producer_sha256):
            missing.append("actual_build_features_source_sha256")
        if not _is_sha256(self.output_run_receipt_sha256):
            missing.append("features_output_run_receipt_sha256")
        if not (self.pandas_version or self.fill_method):
            missing.append("producer_pandas_version_or_explicit_fill_method")
        if missing:
            raise AdmissionBlocked("CANNOT_CONFIRM_PRODUCER_LINK: " + ", ".join(missing))


def verify_real_producer_evidence(
    *,
    source_descriptor: Mapping[str, Any],
    source_bytes: bytes,
    output_receipt_bytes: bytes,
    environment_receipt_bytes: bytes,
    grid_receipt_bytes: bytes,
    expected_features_sha256: str,
    expected_input_manifest_sha256: str,
    expected_source_sha256: str,
    expected_output_receipt_sha256: str,
    expected_environment_receipt_sha256: str,
    expected_grid_receipt_sha256: str,
    expected_source_reference: str,
    expected_relative_source_path: str,
    expected_pandas_version: str | None,
    expected_fill_method: str | None,
    expected_warmup_nan_keys: Sequence[Sequence[Any]],
) -> tuple[ProducerBinding, dict[str, Any]]:
    """Verify bytes against independently frozen source and receipt identities.

    Each payload comes from the admission audit's SHA-checked bounded byte
    cache. A release descriptor alone cannot supply its own trusted hashes.
    """

    source_sha = sha256(source_bytes).hexdigest()
    reference = source_descriptor.get("immutable_reference")
    relative_path = source_descriptor.get("relative_source_path")
    if (
        source_sha != source_descriptor.get("sha256")
        or source_descriptor.get("source_kind") not in {"IMMUTABLE_ARCHIVE_MEMBER", "VERSIONED_COMMIT_BLOB"}
        or not isinstance(reference, str) or not reference
        or not isinstance(relative_path, str) or Path(relative_path).name != "build_features.py"
        or _is_candidate_working_copy_source(str(source_descriptor.get("path", "")))
    ):
        raise AdmissionBlocked("PRODUCER_STATIC_SOURCE_IDENTITY_INVALID")

    output = _parse_json_snapshot(output_receipt_bytes, "PRODUCER_OUTPUT_RUN_RECEIPT")
    environment = _parse_json_snapshot(environment_receipt_bytes, "PRODUCER_ENVIRONMENT_RECEIPT")
    grid = _parse_json_snapshot(grid_receipt_bytes, "FULL_GRID_FLAG_JOIN_RECEIPT")
    output_sha = sha256(output_receipt_bytes).hexdigest()
    environment_sha = sha256(environment_receipt_bytes).hexdigest()
    grid_sha = sha256(grid_receipt_bytes).hexdigest()
    expected_pins = (
        expected_source_sha256, expected_output_receipt_sha256,
        expected_environment_receipt_sha256, expected_grid_receipt_sha256,
    )
    if any(not _is_sha256(value) for value in expected_pins):
        raise AdmissionBlocked("LINEAGE_UNAVAILABLE:producer_evidence_sha_pins_missing")
    if (
        not isinstance(expected_source_reference, str) or not expected_source_reference
        or not isinstance(expected_relative_source_path, str) or not expected_relative_source_path
    ):
        raise AdmissionBlocked("LINEAGE_UNAVAILABLE:immutable_source_identity_missing")
    if (
        source_sha != expected_source_sha256
        or output_sha != expected_output_receipt_sha256
        or environment_sha != expected_environment_receipt_sha256
        or grid_sha != expected_grid_receipt_sha256
        or reference != expected_source_reference
        or relative_path != expected_relative_source_path
    ):
        raise AdmissionBlocked("PRODUCER_EVIDENCE_DIFFERS_FROM_FROZEN_LINEAGE_BINDING")
    run_id = output.get("producer_run_id")
    if (
        output.get("schema") != PRODUCER_EVIDENCE_SCHEMAS["producer_output_run_receipt"]
        or output.get("status") != "PASS"
        or not isinstance(run_id, str) or not run_id
        or output.get("producer_source_sha256") != source_sha
        or output.get("producer_source_reference") != reference
        or output.get("producer_source_relative_path") != relative_path
        or output.get("features_sha256") != expected_features_sha256
        or output.get("environment_receipt_sha256") != environment_sha
        or output.get("full_grid_flag_join_receipt_sha256") != grid_sha
        or output.get("warmup_keys_verified") is not True
        or not isinstance(output.get("verified_warmup_nan_keys"), list)
    ):
        raise AdmissionBlocked("PRODUCER_OUTPUT_RUN_RECEIPT_DOES_NOT_BIND_SOURCE_OUTPUT_AND_EVIDENCE")

    environment_pandas = environment.get("pandas_version")
    environment_fill = environment.get("fill_method")
    if (
        environment.get("schema") != PRODUCER_EVIDENCE_SCHEMAS["producer_environment_receipt"]
        or environment.get("status") != "PASS"
        or environment.get("producer_run_id") != run_id
        or environment.get("producer_source_sha256") != source_sha
        or not isinstance(environment.get("python_version"), str)
        or not environment.get("python_version")
        or not (
            isinstance(environment_pandas, str) and environment_pandas
            or isinstance(environment_fill, str) and environment_fill
        )
        or environment_pandas != expected_pandas_version
        or environment_fill != expected_fill_method
    ):
        raise AdmissionBlocked("PRODUCER_ENVIRONMENT_SEMANTIC_EVIDENCE_INVALID")
    if (
        grid.get("schema") != PRODUCER_EVIDENCE_SCHEMAS["full_grid_flag_join_receipt"]
        or grid.get("status") != "PASS"
        or grid.get("producer_run_id") != run_id
        or grid.get("producer_source_sha256") != source_sha
        or grid.get("features_sha256") != expected_features_sha256
        or grid.get("input_manifest_sha256") != expected_input_manifest_sha256
        or grid.get("feature_row_present_join") != "VERIFIED_ONE_TO_ONE"
        or grid.get("ret_1d_grid_parity") is not True
    ):
        raise AdmissionBlocked("FULL_GRID_FLAG_AND_RETURN_PARITY_RECEIPT_INVALID")

    warmup_keys = _parse_warmup_keys(output["verified_warmup_nan_keys"])
    expected_warmups = _parse_warmup_keys(expected_warmup_nan_keys)
    if warmup_keys != expected_warmups:
        raise AdmissionBlocked("PRODUCER_WARMUP_KEYS_DIFF_FROM_FROZEN_LINEAGE_BINDING")
    producer = ProducerBinding(
        synthetic=False,
        full_grid_and_flag_join_verified=True,
        producer_sha256=source_sha,
        output_run_receipt_sha256=output_sha,
        pandas_version=environment_pandas,
        fill_method=environment_fill,
        warmup_nan_keys=frozenset(warmup_keys),
    )
    producer.require_real_source()
    return producer, {
        "status": "PASS_VERIFIED_SNAPSHOT_CHAIN",
        "producer_run_id": run_id,
        "source": {
            "path": str(Path(source_descriptor["path"]).resolve()),
            "sha256": source_sha,
            "source_kind": source_descriptor["source_kind"],
            "immutable_reference": reference,
            "relative_source_path": relative_path,
            "bytes": len(source_bytes),
        },
        "output_run_receipt": {"sha256": output_sha, "bytes": len(output_receipt_bytes)},
        "environment_receipt": {"sha256": environment_sha, "bytes": len(environment_receipt_bytes)},
        "full_grid_flag_join_receipt": {"sha256": grid_sha, "bytes": len(grid_receipt_bytes)},
        "warmup_nan_key_count": len(warmup_keys),
        "warmup_nan_keys": [list(key) for key in sorted(warmup_keys)],
        "pandas_version": environment_pandas,
        "fill_method": environment_fill,
    }


def required_sessions_from_keys_and_calendar(
    train_keys: pd.DataFrame,
    eval_calendar: pd.DataFrame,
) -> tuple[int, ...]:
    """Bind required dates before BREADTH1 exists or any result is observed."""

    _require_columns(train_keys, ("session_id",), "train_keys")
    _require_columns(eval_calendar, ("session_id", "market_date"), "eval_calendar")
    train = _strict_int_values(train_keys["session_id"], "train_keys.session_id")
    calendar_sessions = _strict_int_values(eval_calendar["session_id"], "eval_calendar.session_id")
    if len(set(calendar_sessions)) != len(calendar_sessions):
        raise InputContractError("evaluation calendar has duplicate session_id")
    dates = eval_calendar["market_date"].astype(str)
    if dates.eq("").any() or dates.duplicated().any():
        raise InputContractError("evaluation calendar market_date must be non-empty and unique")
    if not train or not calendar_sessions:
        raise InputContractError("train keys and evaluation calendar must both bind sessions")
    return tuple(sorted(set(train) | set(calendar_sessions)))


def aggregate_breadth1(
    parent_rows: pd.DataFrame,
    *,
    expected_codes: Sequence[str],
    expected_sessions: Sequence[int],
    required_sessions: Sequence[int],
    producer_binding: ProducerBinding,
) -> pd.DataFrame:
    """Aggregate integer N/D on the complete pool, then cast once to float32.

    Rows from mature/purged/scoreable subsets must never be passed here.  Such
    columns may be present for a test that proves their values do not affect B.
    """

    _require_columns(parent_rows, REQUIRED_PANEL_COLUMNS, "parent_rows")
    if producer_binding.synthetic:
        pass
    else:
        producer_binding.require_real_source()
    codes = _unique_nonempty_strings(expected_codes, "expected_codes")
    sessions = _unique_int_sequence(expected_sessions, "expected_sessions")
    required = _unique_int_sequence(required_sessions, "required_sessions")
    if not codes or not sessions or not required:
        raise InputContractError("codes, full sessions, and required sessions must be non-empty")
    if not set(required) <= set(sessions):
        raise InputContractError("required sessions are not contained in the frozen parent calendar")

    frame = parent_rows.loc[:, list(REQUIRED_PANEL_COLUMNS)].copy()
    frame["code"] = frame["code"].astype(str)
    if frame["code"].eq("").any() or frame["code"].isin({"nan", "None"}).any():
        raise InputContractError("parent pool contains an empty code key")
    frame["session_id"] = _strict_int_values(frame["session_id"], "parent_rows.session_id")
    if frame.duplicated(["code", "session_id"]).any():
        raise InputContractError("duplicate (code, session_id) parent key")
    if not set(frame["code"]) <= set(codes):
        raise InputContractError("parent pool contains an unbound code")
    if not set(frame["session_id"]) <= set(sessions):
        raise InputContractError("parent pool contains an unbound session")
    expected_count = len(codes) * len(sessions)
    if len(frame) != expected_count:
        raise InputContractError(f"incomplete parent grid: rows={len(frame)} expected={expected_count}")
    per_session = frame.groupby("session_id", sort=False)["code"].agg(list)
    if set(per_session.index.astype(int)) != set(sessions):
        raise InputContractError("parent pool is missing a calendar session")
    code_set = set(codes)
    if any(len(values) != len(codes) or set(values) != code_set for values in per_session):
        raise InputContractError("incomplete cross-section in parent pool")

    flags = _strict_binary_values(frame["feature_row_present"], "feature_row_present")
    try:
        returns = pd.to_numeric(frame["ret_1d"], errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InputContractError("ret_1d must be numeric or NaN") from exc
    if np.isinf(returns).any():
        raise InputContractError("ret_1d contains infinity")

    finite = np.isfinite(returns)
    missing = np.isnan(returns)
    if np.any(finite & (flags == 0)):
        raise InputContractError("feature_row_present=0 conflicts with finite ret_1d anywhere in the full parent grid")
    needed = frame["session_id"].isin(required).to_numpy()
    if producer_binding.provenance_mode != FROZEN_OBSERVED_PROVENANCE_MODE and not producer_binding.synthetic:
        warmup_keys = set((str(code), int(session)) for code, session in producer_binding.warmup_nan_keys)
        row_keys = list(zip(frame["code"], frame["session_id"].astype(int)))
        unclassified = [
            key for ix, key in enumerate(row_keys)
            if needed[ix] and missing[ix] and flags[ix] == 1 and key not in warmup_keys
        ]
        if unclassified:
            raise InputContractError(f"feature_row_present=1 ret_1d NaN has no producer-backed warmup cause: {unclassified[:3]}")

    rows: list[dict[str, Any]] = []
    sessions_array = frame["session_id"].to_numpy(dtype=np.int64)
    for session in required:
        at = sessions_array == session
        session_returns = returns[at]
        session_finite = np.isfinite(session_returns)
        denominator = int(session_finite.sum())
        numerator = int((session_finite & (session_returns > 0)).sum())
        if denominator == 0:
            raise InputContractError(f"required session {session} has empty finite-return denominator")
        # Fixed operation order: integer counts, one division, one float32 cast.
        breadth = np.float32(numerator / denominator)
        rows.append({
            "session_id": int(session),
            "positive_finite_count": numerator,
            "finite_return_count": denominator,
            "ret_nan_count": int((at & missing).sum()),
            "ret_nan_flag0_count": int((at & missing & (flags == 0)).sum()),
            "ret_nan_flag1_count": int((at & missing & (flags == 1)).sum()),
            "breadth1": breadth,
        })
    result = pd.DataFrame(rows)
    if result["session_id"].duplicated().any() or not np.isfinite(result["breadth1"].to_numpy()).all():
        raise InputContractError("invalid per-session BREADTH1 output")
    if not result["breadth1"].between(0, 1).all():
        raise InputContractError("BREADTH1 value outside [0, 1]")
    result["breadth1"] = result["breadth1"].to_numpy(dtype=np.float32)
    return result


def append_breadth1_column(
    x64: np.ndarray,
    row_keys: pd.DataFrame,
    breadth_by_session: pd.DataFrame,
    *,
    original_mask: np.ndarray,
) -> tuple[np.ndarray, pd.DataFrame, np.ndarray]:
    """Append B by session without sorting or changing the original 64 columns."""

    if not isinstance(x64, np.ndarray) or x64.ndim != 2 or x64.dtype != np.float32 or x64.shape[1] != 64:
        raise InputContractError("original feature matrix must be float32 with exactly 64 columns")
    _require_columns(row_keys, ("code", "session_id"), "row_keys")
    if len(row_keys) != x64.shape[0]:
        raise InputContractError("row key count does not match original matrix")
    if row_keys[["code", "session_id"]].isna().any().any():
        raise InputContractError("original feature row keys contain null values")
    normalized_keys = row_keys.loc[:, ["code", "session_id"]].copy()
    normalized_keys["code"] = normalized_keys["code"].astype(str)
    normalized_keys["session_id"] = _strict_int_values(normalized_keys["session_id"], "row_keys.session_id")
    if normalized_keys["code"].eq("").any() or normalized_keys["code"].isin({"nan", "None"}).any():
        raise InputContractError("original feature row keys contain an empty code")
    if normalized_keys.duplicated(["code", "session_id"]).any():
        raise InputContractError("duplicate row key in original feature matrix")
    if (
        not isinstance(original_mask, np.ndarray)
        or original_mask.dtype != np.bool_
        or original_mask.ndim != 1
        or original_mask.shape[0] != x64.shape[0]
    ):
        raise InputContractError("original scoreable/maturity mask must be one-dimensional bool aligned to feature rows")
    _require_columns(breadth_by_session, ("session_id", "breadth1"), "breadth_by_session")
    if breadth_by_session["session_id"].duplicated().any():
        raise InputContractError("BREADTH1 day table has duplicate session")
    values = breadth_by_session.set_index("session_id")["breadth1"]
    sessions = _strict_int_values(row_keys["session_id"], "row_keys.session_id")
    missing_sessions = sorted(set(sessions) - set(values.index.astype(int)))
    if missing_sessions:
        raise InputContractError(f"BREADTH1 missing for matrix sessions: {missing_sessions[:5]}")
    column = np.asarray([values.loc[session] for session in sessions], dtype=np.float32)
    if not np.isfinite(column).all():
        raise InputContractError("mapped BREADTH1 column contains non-finite values")
    x65 = np.empty((x64.shape[0], 65), dtype=np.float32)
    x65[:, :64] = x64
    x65[:, 64] = column
    copied_keys = row_keys.loc[:, ["code", "session_id"]].copy().reset_index(drop=True)
    copied_mask = original_mask.copy()
    assert_original_prefix_and_rows(x64, x65, row_keys, copied_keys, original_mask, copied_mask)
    return x65, copied_keys, copied_mask


def assert_original_prefix_and_rows(
    x64: np.ndarray,
    x65: np.ndarray,
    original_keys: pd.DataFrame,
    candidate_keys: pd.DataFrame,
    original_mask: np.ndarray,
    candidate_mask: np.ndarray,
) -> None:
    if x64.dtype != np.float32 or x65.dtype != np.float32 or x64.ndim != 2 or x65.ndim != 2:
        raise InputContractError("matrix dtype/shape must stay float32 and two-dimensional")
    if x64.shape[0] != x65.shape[0] or x64.shape[1] != 64 or x65.shape[1] != 65:
        raise InputContractError("matrix row count or 64+1 column count changed")
    old = x64.view(np.uint32)
    new = x65[:, :64].view(np.uint32)
    if not np.array_equal(old, new):
        raise InputContractError("original 64 float32 values/order/NaN bit patterns changed")
    if not original_keys.reset_index(drop=True).equals(candidate_keys.reset_index(drop=True)):
        raise InputContractError("original row keys/order changed")
    if not np.array_equal(original_mask, candidate_mask):
        raise InputContractError("original mask changed")


def load_admitted_parent_pool(
    *,
    action_context: Any,
    input_manifest_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Read the frozen parent pool from the exact action-verified binding snapshot.

    Every panel/calendar artifact is hashed and parsed from the same byte
    snapshot. A caller cannot pass a second unchecked admission object.
    """

    from f5_breadth1_budget import VerifiedActionContext

    if not isinstance(action_context, VerifiedActionContext):
        raise AdmissionBlocked("real panel bytes require the exact VerifiedActionContext returned by the action budget")
    context = action_context
    if not getattr(context, "input_binding_value", None):
        raise AdmissionBlocked("verified real action context has no input binding snapshot")
    admission_binding = context.input_binding_value
    _require_real_admission_binding(admission_binding, input_manifest_path)
    admission_receipt = getattr(context, "input_admission_receipt_value", None)
    if (
        not isinstance(admission_receipt, Mapping)
        or admission_receipt.get("status") != "PASS"
        or getattr(context, "input_admission_receipt_sha256", None)
        != admission_binding.get("input_admission_receipt_sha256")
    ):
        raise AdmissionBlocked("real parent loader requires the verified admission receipt snapshot")
    source_binding = admission_binding.get("source_binding")
    if (
        not isinstance(source_binding, Mapping)
        or source_binding.get("provenance_mode") != FROZEN_OBSERVED_PROVENANCE_MODE
        or source_binding.get("status") != "LINEAGE_UNAVAILABLE"
        or admission_receipt.get("provenance_mode") != FROZEN_OBSERVED_PROVENANCE_MODE
        or admission_receipt.get("historical_producer_status") != "LINEAGE_UNAVAILABLE"
    ):
        raise AdmissionBlocked("FROZEN_INPUT_AS_OBSERVED_RESEARCH_STATUS_NOT_BOUND")
    parent_budget = admission_binding.get("parent_read_budget")
    if not isinstance(parent_budget, Mapping):
        raise AdmissionBlocked("parent pool file/byte read budget is not bound")
    max_files = parent_budget.get("max_files")
    max_file_bytes = parent_budget.get("max_file_bytes")
    max_total_bytes = parent_budget.get("max_total_bytes")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (max_files, max_file_bytes, max_total_bytes)):
        raise AdmissionBlocked("parent pool file/byte read budget is invalid")
    path = Path(input_manifest_path)
    if path.is_symlink() or not path.is_file():
        raise AdmissionBlocked("input manifest path is invalid")
    manifest_bytes = _bounded_file_read(path, min(max_file_bytes, max_total_bytes), "input manifest")
    bytes_read = len(manifest_bytes)
    actual_manifest_sha = sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise AdmissionBlocked("input_manifest SHA differs from frozen proxy manifest")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema") != "SPIKE5_INPUT_V1":
        raise AdmissionBlocked("unsupported frozen parent manifest schema")
    if manifest.get("membership_mode") != "FIXED_CURRENT_SNAPSHOT_PROXY":
        raise AdmissionBlocked("parent membership contract changed")
    features_sha = (manifest.get("source_hashes", {}).get("features") or {}).get("sha256")
    if features_sha != EXPECTED_FEATURES_SHA256:
        raise AdmissionBlocked("registered full-history feature identity changed")
    raw_panel_root = admission_binding.get("panel_root")
    if not isinstance(raw_panel_root, str) or not raw_panel_root.strip():
        raise AdmissionBlocked("panel_root is not bound")
    panel_root = Path(raw_panel_root).resolve()
    parent_source = admission_binding.get("parent_source")
    panel_max_bytes = parent_source.get("max_panel_bytes") if isinstance(parent_source, Mapping) else None
    calendar_max_bytes = parent_source.get("max_calendar_bytes") if isinstance(parent_source, Mapping) else None
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > max_file_bytes for value in (panel_max_bytes, calendar_max_bytes)):
        raise AdmissionBlocked("parent pool per-artifact read caps are invalid")
    producer = ProducerBinding(
        synthetic=False,
        provenance_mode=FROZEN_OBSERVED_PROVENANCE_MODE,
        full_grid_and_flag_join_verified=True,
    )
    producer.require_real_source()

    codes = _unique_nonempty_strings(manifest.get("codes", ()), "manifest.codes")
    panels = manifest.get("panels")
    if not isinstance(panels, list) or len(panels) != len(codes):
        raise AdmissionBlocked("manifest panel list does not cover every frozen code")
    if len(panels) + 2 > max_files:
        raise AdmissionBlocked("parent pool file count exceeds its bound before panel reads")
    panel_codes = [str(item.get("code", "")) for item in panels if isinstance(item, Mapping)]
    if len(panel_codes) != len(panels) or set(panel_codes) != set(codes) or len(set(panel_codes)) != len(panel_codes):
        raise AdmissionBlocked("manifest panel code identities are incomplete or duplicated")
    frames: list[pd.DataFrame] = []
    panel_receipts: list[dict[str, Any]] = []
    for item in panels:
        relative = PurePosixPath(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise AdmissionBlocked("unsafe panel path in frozen manifest")
        panel_path = panel_root / Path(*relative.parts)
        try:
            panel_path.resolve().relative_to(panel_root)
        except ValueError as exc:
            raise AdmissionBlocked("panel path resolves outside the bound panel root") from exc
        remaining = max_total_bytes - bytes_read
        payload = _bounded_file_read(panel_path, min(panel_max_bytes, remaining), f"panel {item.get('code')}")
        bytes_read += len(payload)
        if bytes_read > max_total_bytes:
            raise AdmissionBlocked("parent pool total byte budget exceeded")
        digest = sha256(payload).hexdigest()
        if digest != item.get("sha256"):
            raise AdmissionBlocked(f"frozen panel SHA mismatch for {item.get('code')}")
        _verify_gzip_csv_header(payload, f"panel {item.get('code')}", PANEL_SOURCE_COLUMNS)
        frame = pd.read_csv(
            BytesIO(payload),
            compression="gzip",
            usecols=list(PANEL_SOURCE_COLUMNS),
            # Keep original numeric/boolean observations for strict guards.
            dtype={"code": "string"},
        )
        expected_rows = item.get("rows")
        if isinstance(expected_rows, bool) or not isinstance(expected_rows, int) or len(frame) != expected_rows:
            raise InputContractError(f"frozen panel row count mismatch for {item.get('code')}")
        frames.append(frame)
        panel_receipts.append({"code": str(item["code"]), "rows": len(frame), "sha256": digest, "bytes": len(payload)})
    parent = pd.concat(frames, ignore_index=True)

    calendar_item = manifest.get("calendar")
    if not isinstance(calendar_item, Mapping):
        raise AdmissionBlocked("parent calendar pointer missing")
    calendar_relative = PurePosixPath(str(calendar_item.get("path", "")))
    if calendar_relative.is_absolute() or ".." in calendar_relative.parts:
        raise AdmissionBlocked("unsafe parent calendar path")
    calendar_path = panel_root / Path(*calendar_relative.parts)
    try:
        calendar_path.resolve().relative_to(panel_root)
    except ValueError as exc:
        raise AdmissionBlocked("calendar path resolves outside the bound panel root") from exc
    calendar_bytes = _bounded_file_read(calendar_path, min(calendar_max_bytes, max_total_bytes - bytes_read), "parent calendar")
    bytes_read += len(calendar_bytes)
    if bytes_read > max_total_bytes:
        raise AdmissionBlocked("parent pool total byte budget exceeded")
    calendar_sha = sha256(calendar_bytes).hexdigest()
    if calendar_sha != calendar_item.get("sha256"):
        raise AdmissionBlocked("parent calendar SHA mismatch")
    _verify_gzip_csv_header(calendar_bytes, "parent calendar", ("session_id", "market_date"))
    calendar = pd.read_csv(
        BytesIO(calendar_bytes), compression="gzip", usecols=["session_id", "market_date"]
    )
    if "session_id" not in calendar or "market_date" not in calendar:
        raise AdmissionBlocked("parent calendar lacks session/date identity")
    calendar = calendar.loc[:, ["session_id", "market_date"]]
    parent = _attach_parent_market_date(parent, calendar)
    return parent, calendar, {
        "manifest_sha256": actual_manifest_sha,
        "features_sha256": features_sha,
        "codes": list(codes),
        "panel_count": len(panel_receipts),
        "panel_receipts": panel_receipts,
        "calendar_sha256": calendar_sha,
        "calendar_rows": len(calendar),
        "file_count": len(panel_receipts) + 2,
        "bytes_read": bytes_read,
        "pandas_version": pd.__version__,
        "producer_binding": producer,
    }


@dataclass(frozen=True)
class PreparedRealInputs:
    """One prepared model/evaluation snapshot derived from a verified context."""

    train_x: np.ndarray
    train_y: np.ndarray
    score_x: np.ndarray
    eval_row_keys: pd.DataFrame
    score_row_keys: pd.DataFrame
    scoreable_mask: np.ndarray
    calendar: pd.DataFrame
    receipt: Mapping[str, Any]


def prepare_real_inputs(action_context: Any) -> PreparedRealInputs:
    """Prepare the frozen candidate from the same, already verified binding.

    Real byte access is only reachable from a VerifiedActionContext whose
    action budget verified the execution contract, input binding, release,
    and complete source-code identity. Each payload is parsed from its SHA-
    checked byte snapshot; source paths and byte ceilings must be present in
    that binding before the file is opened.
    """

    from f5_breadth1_budget import VerifiedActionContext
    from f5_breadth1_core import npy_array_sha256, row_keys_sha256

    if not isinstance(action_context, VerifiedActionContext):
        raise AdmissionBlocked("PREPARE_REQUIRES_VERIFIED_ACTION_CONTEXT")
    binding = action_context.input_binding_value
    if binding.get("status") != "PASS" or binding.get("synthetic_only") is not False:
        raise AdmissionBlocked("PREPARE_REQUIRES_PASSED_REAL_INPUT_ADMISSION_BINDING")
    admission_receipt = getattr(action_context, "input_admission_receipt_value", None)
    admission_receipt_sha = getattr(action_context, "input_admission_receipt_sha256", None)
    admission_receipt_bytes = getattr(action_context, "input_admission_receipt_bytes", None)
    if (
        not _is_sha256(binding.get("input_admission_receipt_sha256"))
        or admission_receipt_sha != binding.get("input_admission_receipt_sha256")
        or not isinstance(admission_receipt, Mapping)
        or admission_receipt.get("status") != "PASS"
        or isinstance(admission_receipt_bytes, bool)
        or not isinstance(admission_receipt_bytes, int) or admission_receipt_bytes < 1
    ):
        raise AdmissionBlocked("PREPARE_INPUT_ADMISSION_RECEIPT_SHA_MISSING")
    artifacts = binding.get("prepare_artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "train_x64", "train_y", "train_keys", "eval_x64", "evaluation_calendar", "pretruth_scores",
    }:
        raise AdmissionBlocked("PREPARE_ARTIFACT_BINDING_SET_MISMATCH")
    frozen_artifacts = binding.get("frozen_artifacts")
    if not isinstance(frozen_artifacts, Mapping):
        raise AdmissionBlocked("PREPARE_FROZEN_ARTIFACT_IDENTITY_MISSING")

    parent_budget = binding.get("parent_read_budget")
    if not isinstance(parent_budget, Mapping):
        raise AdmissionBlocked("parent pool file/byte read budget is not bound")
    parent_max_files = parent_budget.get("max_files")
    parent_max_bytes = parent_budget.get("max_total_bytes")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (parent_max_files, parent_max_bytes)):
        raise AdmissionBlocked("parent pool file/byte read budget is invalid")
    total_limit = binding.get("prepare_artifact_max_total_bytes")
    if isinstance(total_limit, bool) or not isinstance(total_limit, int) or total_limit < 1:
        raise AdmissionBlocked("PREPARE_TOTAL_BYTE_BUDGET_MISSING")
    prepare_total_max = binding.get("prepare_total_max_bytes")
    if (
        isinstance(prepare_total_max, bool) or not isinstance(prepare_total_max, int)
        or prepare_total_max < total_limit + parent_max_bytes + admission_receipt_bytes
    ):
        raise AdmissionBlocked("PREPARE_TOTAL_READ_BUDGET_MUST_COVER_ALL_BOUND_PHASE_READS")
    total_max_files = binding.get("prepare_total_max_files")
    if isinstance(total_max_files, bool) or not isinstance(total_max_files, int) or total_max_files < len(artifacts) + parent_max_files + 1:
        raise AdmissionBlocked("PREPARE_TOTAL_FILE_BUDGET_MUST_COVER_ALL_BOUND_PHASE_READS")

    payloads: dict[str, bytes] = {}
    receipts: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    max_file_bytes = binding.get("prepare_artifact_max_file_bytes")
    if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 1:
        raise AdmissionBlocked("PREPARE_PER_FILE_BYTE_BUDGET_MISSING")
    for name in sorted(artifacts):
        descriptor = artifacts[name]
        if not isinstance(descriptor, Mapping):
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_BINDING_INVALID:{name}")
        raw_path = descriptor.get("path")
        expected_sha = descriptor.get("sha256")
        maximum = descriptor.get("max_bytes")
        frozen_descriptor = frozen_artifacts.get(name)
        if (
            not isinstance(raw_path, str) or not Path(raw_path).is_absolute()
            or not _is_sha256(expected_sha)
            or isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1
            or maximum > max_file_bytes
            or not isinstance(frozen_descriptor, Mapping)
            or raw_path != frozen_descriptor.get("path")
            or expected_sha != frozen_descriptor.get("sha256")
        ):
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_BOUNDS_INVALID:{name}")
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_PATH_INVALID:{name}")
        resolved = path.resolve(strict=True)
        if resolved != path:
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_PATH_RESOLVES_DIFFERENTLY:{name}")
        size_before = resolved.stat().st_size
        if size_before > maximum or total_bytes + size_before > total_limit:
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_BYTE_BUDGET_EXCEEDED:{name}")
        with resolved.open("rb") as handle:
            payload = handle.read(maximum + 1)
        if len(payload) != size_before or len(payload) > maximum or sha256(payload).hexdigest() != expected_sha:
            raise AdmissionBlocked(f"PREPARE_ARTIFACT_SNAPSHOT_IDENTITY_MISMATCH:{name}")
        total_bytes += len(payload)
        payloads[name] = payload
        receipts[name] = {"sha256": expected_sha, "bytes": len(payload), "path": raw_path}

    train_x64 = _npy_from_bytes(payloads["train_x64"], "train_x64", np.float32, 2)
    train_y = _npy_from_bytes(payloads["train_y"], "train_y", None, 1)
    if train_y.dtype not in (np.dtype("int8"), np.dtype("int16"), np.dtype("int32"), np.dtype("int64"), np.dtype("uint8")):
        raise AdmissionBlocked("TRAIN_Y_DTYPE_MUST_BE_INTEGER")
    if not np.isin(train_y, [0, 1]).all():
        raise AdmissionBlocked("TRAIN_Y_LABELS_MUST_BE_BINARY")
    train_y = train_y.copy()
    train_keys = _csv_from_bytes(payloads["train_keys"], "train_keys", required=("code", "session_id"))
    train_row_keys = train_keys.loc[:, ["code", "session_id"]].copy()
    eval_x64 = _npy_from_bytes(payloads["eval_x64"], "eval_x64", np.float32, 2)
    eval_calendar = _csv_from_bytes(payloads["evaluation_calendar"], "evaluation_calendar", required=("session_id", "market_date"))
    eval_calendar = eval_calendar.loc[:, ["session_id", "market_date"]].copy()
    eval_calendar["session_id"] = _strict_int_values(eval_calendar["session_id"], "evaluation_calendar.session_id")
    eval_projection = _pretruth_projection(payloads["pretruth_scores"], artifacts["pretruth_scores"])
    eval_row_keys = eval_projection.loc[:, ["code", "session_id"]].copy()
    mask_values = pd.to_numeric(eval_projection["scoreable"], errors="raise").to_numpy(dtype=float)
    if not np.isin(mask_values, [0.0, 1.0]).all():
        raise AdmissionBlocked("PRETRUTH_SCOREABLE_MASK_NOT_BINARY")
    scoreable_mask = mask_values.astype(bool)
    original_mask = scoreable_mask

    if train_x64.ndim != 2 or train_x64.shape[1] != 64 or train_x64.shape[0] != len(train_y):
        raise AdmissionBlocked("TRAIN_X64_SHAPE_OR_LABEL_ALIGNMENT_INVALID")
    if len(train_row_keys) != len(train_x64):
        raise AdmissionBlocked("TRAIN_ROW_KEY_COUNT_MISMATCH")
    if eval_x64.shape != (len(eval_row_keys), 64) or len(scoreable_mask) != len(eval_x64):
        raise AdmissionBlocked("EVALUATION_X64_PRETRUTH_IDENTITY_SHAPE_MISMATCH")
    if train_row_keys.duplicated(["code", "session_id"]).any() or eval_row_keys.duplicated(["code", "session_id"]).any():
        raise AdmissionBlocked("PREPARE_DUPLICATE_ROW_KEY")
    allowed_train_sessions = set(_strict_int_values(train_keys["session_id"], "train_keys.session_id"))
    if not set(_strict_int_values(train_row_keys["session_id"], "train_row_keys.session_id")) <= allowed_train_sessions:
        raise AdmissionBlocked("TRAIN_ROW_KEYS_OUTSIDE_ORIGINAL_TRAIN_KEYS")
    if not np.isfinite(train_x64[~np.isnan(train_x64)]).all():
        raise AdmissionBlocked("TRAIN_X64_CONTAINS_INFINITY")
    if not np.isfinite(eval_x64[~np.isnan(eval_x64)]).all():
        raise AdmissionBlocked("EVAL_X64_CONTAINS_INFINITY")

    manifest_path = binding.get("input_manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise AdmissionBlocked("INPUT_MANIFEST_PATH_MISSING")
    parent, calendar, parent_receipt = load_admitted_parent_pool(
        action_context=action_context,
        input_manifest_path=Path(manifest_path),
    )
    required_sessions = required_sessions_from_keys_and_calendar(train_keys, eval_calendar)
    manifest_codes = _unique_nonempty_strings(parent_receipt["codes"], "manifest.codes")
    manifest_sessions = _strict_int_values(calendar["session_id"], "calendar.session_id")
    parent_date_map = {int(row.session_id): str(row.market_date) for row in calendar.itertuples(index=False)}
    if any(parent_date_map.get(int(row.session_id)) != str(row.market_date) for row in eval_calendar.itertuples(index=False)):
        raise AdmissionBlocked("EVALUATION_CALENDAR_DIFFERS_FROM_FROZEN_PARENT_CALENDAR")
    breadth = aggregate_breadth1(
        parent,
        expected_codes=manifest_codes,
        expected_sessions=manifest_sessions,
        required_sessions=required_sessions,
        producer_binding=parent_receipt["producer_binding"],
    )
    train_x65, _, _ = append_breadth1_column(
        train_x64, train_row_keys, breadth,
        original_mask=np.ones(len(train_x64), dtype=np.bool_),
    )
    eval_x65, mapped_eval_keys, mapped_mask = append_breadth1_column(
        eval_x64, eval_row_keys, breadth, original_mask=scoreable_mask,
    )
    if not np.array_equal(mapped_mask, scoreable_mask):
        raise AdmissionBlocked("PREPARE_SCOREABLE_MASK_CHANGED")
    score_row_keys = mapped_eval_keys.loc[mapped_mask].reset_index(drop=True)
    score_x = eval_x65[mapped_mask].copy()
    array_identity = {
        "train_x65_npy_sha256": npy_array_sha256(train_x65),
        "train_y_npy_sha256": npy_array_sha256(train_y),
        "score_x65_npy_sha256": npy_array_sha256(score_x),
        "eval_row_keys_sha256": row_keys_sha256(mapped_eval_keys),
        "score_row_keys_sha256": row_keys_sha256(score_row_keys),
        "scoreable_mask_npy_sha256": npy_array_sha256(scoreable_mask),
        "train_rows": int(len(train_x65)),
        "train_positive_rows": int(np.count_nonzero(train_y == 1)),
        "evaluation_G_rows": int(len(mapped_eval_keys)),
        "evaluation_S_rows": int(len(score_x)),
    }
    bound_arrays = binding.get("verified_arrays")
    if not isinstance(bound_arrays, Mapping) or bound_arrays.get("status") != "PASS":
        raise AdmissionBlocked("VERIFIED_ARRAY_IDENTITY_RECEIPT_MISSING_FROM_BOUND_INPUT_CONTEXT")
    for name, actual in array_identity.items():
        if bound_arrays.get(name) != actual:
            raise AdmissionBlocked(f"VERIFIED_ARRAY_IDENTITY_BINDING_MISMATCH:{name}")
    if total_bytes + parent_receipt["bytes_read"] + admission_receipt_bytes > prepare_total_max:
        raise AdmissionBlocked("PREPARE_TOTAL_READ_BUDGET_EXCEEDED")
    receipt = {
        "schema": "F5_BREADTH1_REAL_PREPARE_RECEIPT_V1",
        "status": "PREPARED_AWAITING_WORKER",
        "input_binding_sha256": action_context.input_binding_sha256,
        "input_admission_receipt_sha256": binding["input_admission_receipt_sha256"],
        "artifact_bytes_read": total_bytes + parent_receipt["bytes_read"] + admission_receipt_bytes,
        "artifact_files_read": len(artifacts) + parent_receipt["file_count"] + 1,
        "admission_receipt_snapshot": {
            "sha256": admission_receipt_sha,
            "bytes": admission_receipt_bytes,
            "status": admission_receipt.get("status"),
            "read_release_sha256": admission_receipt.get("read_release_sha256"),
        },
        "prepare_artifacts": receipts,
        "verified_arrays": dict(array_identity),
        "train_x64_npy_sha256": npy_array_sha256(train_x64),
        "train_x65_npy_sha256": array_identity["train_x65_npy_sha256"],
        "train_y_npy_sha256": array_identity["train_y_npy_sha256"],
        "score_x65_npy_sha256": array_identity["score_x65_npy_sha256"],
        "eval_row_keys_sha256": array_identity["eval_row_keys_sha256"],
        "score_row_keys_sha256": array_identity["score_row_keys_sha256"],
        "scoreable_mask_npy_sha256": array_identity["scoreable_mask_npy_sha256"],
        "feature_count_before_after": [64, 65],
        "training_rows": int(len(train_x65)),
        "evaluation_G_rows": int(len(mapped_eval_keys)),
        "evaluation_S_rows": int(len(score_x)),
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_truth_decode_calls": 0,
    }
    return PreparedRealInputs(
        train_x=train_x65,
        train_y=train_y,
        score_x=score_x,
        eval_row_keys=mapped_eval_keys,
        score_row_keys=score_row_keys,
        scoreable_mask=scoreable_mask,
        calendar=eval_calendar,
        receipt=receipt,
    )


def _npy_from_bytes(payload: bytes, label: str, dtype: Any | None, ndim: int) -> np.ndarray:
    try:
        value = np.load(BytesIO(payload), allow_pickle=False)
    except (ValueError, OSError) as exc:
        raise AdmissionBlocked(f"{label.upper()}_NPY_INVALID") from exc
    if not isinstance(value, np.ndarray) or value.ndim != ndim or (dtype is not None and value.dtype != dtype):
        raise AdmissionBlocked(f"{label.upper()}_NPY_SHAPE_OR_DTYPE_INVALID")
    return value


def _bounded_file_read(path: Path, max_bytes: int, label: str) -> bytes:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise AdmissionBlocked(f"{label} has no positive byte allowance")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise AdmissionBlocked(f"{label} path is invalid")
    size_before = path.stat().st_size
    if size_before > max_bytes:
        raise AdmissionBlocked(f"{label} exceeds its bound before read")
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) != size_before or len(payload) > max_bytes:
        raise AdmissionBlocked(f"{label} changed or exceeded its bound during read")
    return payload


def _csv_from_bytes(payload: bytes, label: str, *, required: Sequence[str]) -> pd.DataFrame:
    try:
        _verify_gzip_csv_header(payload, label, required)
        return pd.read_csv(
            BytesIO(payload),
            compression="gzip",
            usecols=list(required),
            dtype={"code": "string"} if "code" in required else None,
        )
    except (OSError, UnicodeDecodeError, StopIteration, pd.errors.ParserError) as exc:
        raise AdmissionBlocked(f"{label.upper()}_CSV_INVALID") from exc


def _verify_gzip_csv_header(payload: bytes, label: str, required: Sequence[str]) -> tuple[str, ...]:
    error_prefix = f"{label.upper().replace(' ', '_')}_CSV_HEADER_INVALID"
    try:
        with gzip.GzipFile(fileobj=BytesIO(payload), mode="rb") as stream:
            header = next(csv.reader([stream.readline().decode("utf-8")]))
    except (OSError, UnicodeDecodeError, StopIteration, csv.Error) as exc:
        diagnostics = {
            "status": "REJECTED",
            "parser_rejection_condition": "GZIP_READ_DECODE_OR_CSV_PARSE_ERROR",
            "parser_exception_type": type(exc).__name__,
            "expected_required_columns": list(required),
            "actual_header_columns": None,
            "duplicate_header_columns": None,
            "missing_required_header_columns": None,
        }
        raise AdmissionBlocked(error_prefix, diagnostics=diagnostics) from exc
    duplicate_columns = sorted({column for column in header if header.count(column) > 1})
    missing_columns = [column for column in required if column not in set(header)]
    if duplicate_columns or missing_columns:
        if duplicate_columns and missing_columns:
            condition = "DUPLICATE_AND_MISSING_REQUIRED_COLUMNS"
        elif duplicate_columns:
            condition = "DUPLICATE_COLUMNS"
        else:
            condition = "MISSING_REQUIRED_COLUMNS"
        diagnostics = {
            "status": "REJECTED",
            "parser_rejection_condition": condition,
            "expected_required_columns": list(required),
            "actual_header_columns": list(header),
            "duplicate_header_columns": duplicate_columns,
            "missing_required_header_columns": missing_columns,
        }
        raise AdmissionBlocked(error_prefix, diagnostics=diagnostics)
    return tuple(header)


def _pretruth_projection(payload: bytes, descriptor: Mapping[str, Any]) -> pd.DataFrame:
    identity_columns = descriptor.get("identity_columns")
    required_identity = ["session_id", "code", "scoreable"]
    if identity_columns != required_identity:
        raise AdmissionBlocked("PRETRUTH_IDENTITY_PROJECTION_NOT_EXACT")
    try:
        with gzip.GzipFile(fileobj=BytesIO(payload), mode="rb") as stream:
            header = next(csv.reader([stream.readline().decode("utf-8")]))
        if len(header) != len(set(header)) or not set(required_identity) <= set(header):
            raise AdmissionBlocked("PRETRUTH_REQUIRED_PROJECTION_COLUMNS_MISSING")
        frame = pd.read_csv(
            BytesIO(payload), compression="gzip", usecols=["session_id", "code", "scoreable"],
            dtype={"code": "string", "session_id": "string"},
        )
        frame = frame.loc[:, ["session_id", "code", "scoreable"]]
        return frame
    except (OSError, UnicodeDecodeError, StopIteration, pd.errors.ParserError, ValueError) as exc:
        if isinstance(exc, AdmissionBlocked):
            raise
        if isinstance(exc, InputContractError):
            raise
        raise AdmissionBlocked("PRETRUTH_PROJECTION_INVALID") from exc


def _align_pretruth_to_eval_identity(
    eval_meta: pd.DataFrame,
    pretruth_projection: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Require unique exact key sets and map scoreable rows into frozen eval order."""

    def keys(frame: pd.DataFrame) -> tuple[list[tuple[int, str] | None], int, int, int]:
        out: list[tuple[int, str] | None] = []
        null_rows = 0
        empty_code_rows = 0
        invalid_session_rows = 0
        for session, code in zip(frame["session_id"].tolist(), frame["code"].tolist()):
            if pd.isna(code):
                null_rows += 1
                out.append(None)
                continue
            code_value = str(code)
            if not code_value or not code_value.strip():
                empty_code_rows += 1
                out.append(None)
                continue
            if pd.isna(session):
                null_rows += 1
                out.append(None)
                continue
            try:
                if isinstance(session, (bool, np.bool_)):
                    raise ValueError
                if isinstance(session, (int, np.integer)):
                    session_value = int(session)
                elif isinstance(session, str) and session.isdecimal():
                    session_value = int(session)
                elif isinstance(session, (float, np.floating)) and np.isfinite(session) and float(session).is_integer():
                    session_value = int(session)
                else:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                invalid_session_rows += 1
                out.append(None)
                continue
            out.append((session_value, code_value))
        return out, null_rows, empty_code_rows, invalid_session_rows

    eval_keys, eval_null_rows, eval_empty_code_rows, eval_invalid_session_rows = keys(eval_meta)
    source_keys, source_null_rows, source_empty_code_rows, source_invalid_session_rows = keys(pretruth_projection)
    valid_eval = [key for key in eval_keys if key is not None]
    valid_source = [key for key in source_keys if key is not None]
    eval_key_set = set(valid_eval)
    source_key_set = set(valid_source)
    eval_duplicate_rows = len(valid_eval) - len(eval_key_set)
    source_duplicate_rows = len(valid_source) - len(source_key_set)
    missing = sorted(eval_key_set - source_key_set)[:10]
    extra = sorted(source_key_set - eval_key_set)[:10]
    key_sets_equal = (
        eval_null_rows == 0 and source_null_rows == 0
        and eval_empty_code_rows == 0 and source_empty_code_rows == 0
        and eval_invalid_session_rows == 0 and source_invalid_session_rows == 0
        and eval_duplicate_rows == 0 and source_duplicate_rows == 0
        and eval_key_set == source_key_set
    )
    order_only = key_sets_equal and eval_keys != source_keys
    diagnostics = {
        "status": "MATCHED_ORDER_ONLY" if order_only else "MATCHED_SAME_ORDER" if key_sets_equal else "KEY_SET_MISMATCH",
        "eval_meta_rows": len(eval_keys),
        "pretruth_identity_rows": len(source_keys),
        "eval_meta_null_key_rows": eval_null_rows,
        "pretruth_null_key_rows": source_null_rows,
        "eval_meta_invalid_session_rows": eval_invalid_session_rows,
        "pretruth_invalid_session_rows": source_invalid_session_rows,
        "eval_meta_empty_code_rows": eval_empty_code_rows,
        "pretruth_empty_code_rows": source_empty_code_rows,
        "eval_meta_duplicate_key_rows": eval_duplicate_rows,
        "pretruth_duplicate_key_rows": source_duplicate_rows,
        "missing_pretruth_key_count": len(eval_key_set - source_key_set),
        "extra_pretruth_key_count": len(source_key_set - eval_key_set),
        "missing_pretruth_key_samples_session_code": [[sid, code] for sid, code in missing],
        "extra_pretruth_key_samples_session_code": [[sid, code] for sid, code in extra],
        "key_sets_equal": key_sets_equal,
        "order_only_difference": order_only,
        "scoreable_rows_reordered": len(valid_eval) if order_only else 0,
        "truth_or_probability_read": False,
    }
    if not key_sets_equal:
        raise InputContractError("A_PRETRUTH_KEYS_DO_NOT_MATCH_FROZEN_EVAL_KEYS", diagnostics=diagnostics)
    source_positions = {key: index for index, key in enumerate(source_keys)}
    aligned = pretruth_projection.iloc[[source_positions[key] for key in eval_keys]].reset_index(drop=True)
    normalized_eval = eval_meta.copy().reset_index(drop=True)
    normalized_eval["session_id"] = [key[0] for key in eval_keys if key is not None]
    aligned["session_id"] = [key[0] for key in eval_keys if key is not None]
    if not aligned.loc[:, ["code", "session_id"]].equals(normalized_eval.loc[:, ["code", "session_id"]]):
        raise InputContractError("A_PRETRUTH_KEY_REINDEX_FAILED", diagnostics=diagnostics)
    return normalized_eval, aligned, diagnostics


def _require_real_admission_binding(binding: Mapping[str, Any], manifest_path: Path) -> None:
    if binding.get("status") != "PASS":
        raise AdmissionBlocked("real input admission is not PASS; no panel/calendar bytes were opened")
    if binding.get("input_manifest_path") != str(Path(manifest_path).resolve()):
        raise AdmissionBlocked("input manifest path does not match admission binding")
    if binding.get("input_manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise AdmissionBlocked("admission binding does not pin the original input manifest SHA")
    producer = binding.get("source_binding")
    if (
        not isinstance(producer, Mapping)
        or producer.get("provenance_mode") != FROZEN_OBSERVED_PROVENANCE_MODE
        or producer.get("status") != "LINEAGE_UNAVAILABLE"
    ):
        raise AdmissionBlocked("FROZEN_INPUT_AS_OBSERVED_RESEARCH_LIMITATION_NOT_BOUND")
    if not _is_sha256(binding.get("input_manifest_sha256")):
        raise AdmissionBlocked("admission binding manifest SHA invalid")
    if not binding.get("panel_root"):
        raise AdmissionBlocked("admission binding panel root missing")


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise InputContractError(f"{label} missing columns: {missing}")


def _strict_int_values(values: pd.Series, label: str) -> list[int]:
    out: list[int] = []
    for value in values.tolist():
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise InputContractError(f"{label} must contain strict integers")
        out.append(int(value))
    return out


def _unique_int_sequence(values: Sequence[int], label: str) -> tuple[int, ...]:
    out = []
    for value in values:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise InputContractError(f"{label} must contain strict integers")
        out.append(int(value))
    if len(set(out)) != len(out):
        raise InputContractError(f"{label} contains duplicates")
    return tuple(out)


def _unique_nonempty_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    out = tuple(str(value) for value in values)
    if any(not value or value in {"nan", "None"} for value in out):
        raise InputContractError(f"{label} contains empty keys")
    if len(set(out)) != len(out):
        raise InputContractError(f"{label} contains duplicates")
    return out


def _strict_binary_values(values: pd.Series, label: str) -> np.ndarray:
    out = []
    for value in values.tolist():
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or int(value) not in (0, 1):
            raise InputContractError(f"{label} must contain strict integer 0/1 values")
        out.append(int(value))
    return np.asarray(out, dtype=np.int8)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _is_candidate_working_copy_source(value: str) -> bool:
    project_root = Path(__file__).resolve().parents[3]
    if not isinstance(value, str) or not Path(value).is_absolute():
        return True
    path = Path(value).resolve(strict=False)
    forbidden_roots = (
        project_root / "workspace" / "f5_breadth1_r1_20261010",
        project_root / "workspace" / "f5_breadth1_r3_frozen_input_20261011",
    )
    for root in forbidden_roots:
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            pass
    return False


def _parse_json_snapshot(payload: bytes, label: str) -> dict[str, Any]:
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise AdmissionBlocked(f"{label}_DUPLICATE_JSON_KEY:{key}")
            result[key] = item
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionBlocked(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise AdmissionBlocked(f"{label}_MUST_BE_OBJECT")
    return value


def _parse_warmup_keys(value: Any) -> set[tuple[str, int]]:
    if not isinstance(value, (list, tuple)):
        raise AdmissionBlocked("PRODUCER_WARMUP_KEYS_MUST_BE_EXACT_LIST")
    output: set[tuple[str, int]] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise AdmissionBlocked("PRODUCER_WARMUP_KEYS_CONTAIN_INVALID_KEY")
        code, session = item
        if not isinstance(code, str) or not code or isinstance(session, bool) or not isinstance(session, int):
            raise AdmissionBlocked("PRODUCER_WARMUP_KEYS_CONTAIN_INVALID_KEY")
        if (code, session) in output:
            raise AdmissionBlocked("PRODUCER_WARMUP_KEYS_CONTAIN_DUPLICATE_KEY")
        output.add((code, session))
    return output


def validate_calendar_dates_for_admission(frame: pd.DataFrame) -> dict[int, str]:
    _require_columns(frame, ("session_id", "market_date"), "calendar")
    sessions = _strict_int_values(frame["session_id"], "calendar.session_id")
    raw_dates = frame["market_date"]
    dates = [str(value).strip() for value in raw_dates.tolist()]
    missing_dates = raw_dates.isna().to_numpy(dtype=bool)
    invalid_dates = [
        value.casefold() in {"", "nan", "none", "nat"}
        for value in dates
    ]
    if (
        len(set(sessions)) != len(sessions)
        or missing_dates.any()
        or any(invalid_dates)
        or len(set(dates)) != len(dates)
    ):
        raise InputContractError("calendar session/date values must be unique and non-empty")
    if pd.to_datetime(dates, errors="coerce").isna().any():
        raise InputContractError("calendar contains an invalid market_date")
    return dict(zip(sessions, dates))


def _attach_parent_market_date(
    parent_rows: pd.DataFrame,
    parent_calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Derive the panel date solely from its bound parent-calendar session key."""

    _require_columns(parent_rows, PANEL_SOURCE_COLUMNS, "parent_panel")
    session_to_date = validate_calendar_dates_for_admission(parent_calendar)
    frame = parent_rows.copy()
    sessions = _strict_int_values(frame["session_id"], "parent_panel.session_id")
    mapped = [session_to_date.get(session) for session in sessions]
    missing_sessions = sorted({session for session, market_date in zip(sessions, mapped) if market_date is None})
    if missing_sessions:
        raise InputContractError(
            "parent panel session_id is absent from the frozen parent calendar",
            diagnostics={"unmapped_parent_session_count": len(missing_sessions)},
        )
    frame["session_id"] = sessions
    frame.insert(2, "market_date", mapped)
    return frame


def _audit_parent_pool_rows(
    parent_rows: pd.DataFrame,
    *,
    expected_codes: Sequence[str],
    expected_sessions: Sequence[int],
    required_sessions: Sequence[int],
    producer_binding: ProducerBinding,
) -> dict[str, Any]:
    """Audit grid, flag, and return observations without granting a source PASS."""

    _require_columns(parent_rows, REQUIRED_PANEL_COLUMNS, "parent_rows")
    codes = _unique_nonempty_strings(expected_codes, "expected_codes")
    sessions = _unique_int_sequence(expected_sessions, "expected_sessions")
    required = _unique_int_sequence(required_sessions, "required_sessions")
    if not set(required) <= set(sessions):
        raise InputContractError("required sessions are outside the frozen parent calendar")
    frame = parent_rows.loc[:, list(REQUIRED_PANEL_COLUMNS)].copy()
    frame["code"] = frame["code"].astype(str)
    frame["session_id"] = _strict_int_values(frame["session_id"], "parent_rows.session_id")
    if frame["code"].eq("").any() or frame["code"].isin({"nan", "None"}).any():
        raise InputContractError("parent pool has an empty code key")
    if frame.duplicated(["code", "session_id"]).any():
        raise InputContractError("duplicate (code, session_id) parent key")
    if not set(frame["code"]) <= set(codes) or not set(frame["session_id"]) <= set(sessions):
        raise InputContractError("parent pool contains unbound code/session keys")
    if len(frame) != len(codes) * len(sessions):
        raise InputContractError("incomplete parent grid")
    code_set = set(codes)
    if any(len(values) != len(codes) or set(values) != code_set for values in frame.groupby("session_id", sort=False)["code"].agg(list)):
        raise InputContractError("incomplete parent cross-section")
    flags = _strict_binary_values(frame["feature_row_present"], "feature_row_present")
    try:
        returns = pd.to_numeric(frame["ret_1d"], errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InputContractError("ret_1d must be numeric or NaN") from exc
    if np.isinf(returns).any():
        raise InputContractError("ret_1d contains infinity")
    finite = np.isfinite(returns)
    missing = np.isnan(returns)
    if np.any(finite & (flags == 0)):
        raise InputContractError("feature_row_present=0 conflicts with finite ret_1d")
    needed = frame["session_id"].isin(required).to_numpy()
    keys = list(zip(frame["code"], frame["session_id"].astype(int)))
    ret_nan = [key for ix, key in enumerate(keys) if needed[ix] and missing[ix]]
    ret_nan_flag0 = [key for ix, key in enumerate(keys) if needed[ix] and missing[ix] and flags[ix] == 0]
    ret_nan_flag1 = [key for ix, key in enumerate(keys) if needed[ix] and missing[ix] and flags[ix] == 1]
    empty_sessions = [session for session in required if not np.isfinite(returns[frame["session_id"].to_numpy() == session]).any()]
    blockers: list[str] = []
    flag_value_conflicts = int(np.count_nonzero(finite & (flags == 0)))
    if flag_value_conflicts:
        blockers.append("REJECT:FEATURE_FLAG_VALUE_CONTRADICTION")
    if empty_sessions:
        blockers.append("REJECT:EMPTY_REQUIRED_FINITE_DENOMINATOR")
    return {
        "full_grid_complete": True,
        "parent_rows": int(len(frame)),
        "code_count": int(len(codes)),
        "session_count": int(len(sessions)),
        "required_session_count": int(len(required)),
        "duplicate_keys": 0,
        "feature_flag_value_conflicts": flag_value_conflicts,
        "finite_returns": int(finite.sum()),
        "positive_finite_returns": int((finite & (returns > 0)).sum()),
        "ret_nan_required_rows": int(len(ret_nan)),
        "ret_nan_flag0_required_rows": int(len(ret_nan_flag0)),
        "ret_nan_flag1_required_rows": int(len(ret_nan_flag1)),
        "ret_nan_cause": "NOT_INFERRED",
        "empty_required_denominator_sessions": empty_sessions,
        "blockers": blockers,
    }

