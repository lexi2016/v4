"""Candidate-scoped, append-only action budgets over the official registry.

No sidecar decides remaining quota.  Every action claim and terminal is written
through the existing official builder and compatibility validator while holding
the same registry OS lock used by ``OfficialRegistryAdapter``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from f5_breadth1_core import (
    ArtifactContractError,
    EXPERIMENT_ID,
    ROUTE_ID,
    sha256_file,
    verify_candidate_code_bindings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BATCH_ROOT = PROJECT_ROOT / "research" / "hk_burst_f5" / "batches" / "breadth1_r3_frozen_input_20261011"
OFFICIAL_REGISTRY_PATH = PROJECT_ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"
OFFICIAL_GUARD_DIR = PROJECT_ROOT / "workspace" / "hkconnect_price_semantics_v2_20260919" / "zero_label_parity"
OFFICIAL_BUILDER_PATH = PROJECT_ROOT / "contracts" / "build_experiment_registry_backfill_20260821.py"
OFFICIAL_VALIDATOR_PATH = PROJECT_ROOT / "contracts" / "validate_experiment_registry_append_compatibility_v1.py"
CANDIDATE_ID = "F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011"
RECOVERY_GRANT_ID = "INPUT_ADMISSION_RECOVERY_R1_20261011"
RECOVERY_ACTION = "input_admission_recovery"
RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{RECOVERY_GRANT_ID}"
RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_INPUT_ADMISSION_RECOVERY_R1_20261011_ONE_SHOT"
RECOVERY_GRANT_PATH = BATCH_ROOT / "bindings" / "INPUT_ADMISSION_RECOVERY_R1_GRANT.json"
RECOVERY_READ_RELEASE_PATH = BATCH_ROOT / "bindings" / "INPUT_ADMISSION_RECOVERY_R1_READ_RELEASE.json"
RECOVERY_READ_PLAN_PATH = BATCH_ROOT / "bindings" / "REAL_INPUT_READ_PLAN_RECOVERY_R1.json"
KEY_ALIGNMENT_RECOVERY_GRANT_ID = "INPUT_KEY_ALIGNMENT_RECOVERY_R2_20261011"
KEY_ALIGNMENT_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{KEY_ALIGNMENT_RECOVERY_GRANT_ID}"
KEY_ALIGNMENT_EXECUTION_ID = f"{ROUTE_ID}_INPUT_KEY_ALIGNMENT_RECOVERY_R2_20261011_ONE_SHOT"
KEY_ALIGNMENT_RECOVERY_GRANT_PATH = BATCH_ROOT / "bindings" / "INPUT_KEY_ALIGNMENT_RECOVERY_R2_GRANT.json"
KEY_ALIGNMENT_READ_RELEASE_PATH = BATCH_ROOT / "bindings" / "INPUT_KEY_ALIGNMENT_RECOVERY_R2_READ_RELEASE.json"
KEY_ALIGNMENT_READ_PLAN_PATH = BATCH_ROOT / "bindings" / "REAL_INPUT_READ_PLAN_KEY_ALIGNMENT_RECOVERY_R2.json"
TRAIN_LABEL_RECOVERY_GRANT_ID = "TRAIN_LABEL_RECOVERY_R3_20261011"
TRAIN_LABEL_RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{TRAIN_LABEL_RECOVERY_GRANT_ID}"
TRAIN_LABEL_RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_TRAIN_LABEL_RECOVERY_R3_20261011_ONE_SHOT"
TRAIN_LABEL_RECOVERY_GRANT_PATH = BATCH_ROOT / "bindings" / "TRAIN_LABEL_RECOVERY_R3_GRANT.json"
TRAIN_LABEL_RECOVERY_READ_RELEASE_PATH = BATCH_ROOT / "bindings" / "TRAIN_LABEL_RECOVERY_R3_READ_RELEASE.json"
TRAIN_LABEL_RECOVERY_READ_PLAN_PATH = BATCH_ROOT / "bindings" / "REAL_INPUT_READ_PLAN_TRAIN_LABEL_RECOVERY_R3.json"
PANEL_HEADER_R4_RECOVERY_GRANT_ID = "PARENT_PANEL_DATE_RECOVERY_R4_20261011"
PANEL_HEADER_R4_RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{PANEL_HEADER_R4_RECOVERY_GRANT_ID}"
PANEL_HEADER_R4_RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_PARENT_PANEL_DATE_RECOVERY_R4_20261011_ONE_SHOT"
PANEL_HEADER_R4_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "r4_one_shot_pipeline" / "R4_ADMISSION_RUNTIME_FAILURE_RECEIPT.json"
PANEL_HEADER_R4_FAILED_RECEIPT_SHA256 = "e58ec6c92b2b2e94fad58c77c0a24c4110c783905b75d06fd0c9a7fd512887b6"
PANEL_HEADER_R4_FAILED_START_SHA256 = "e7d406a605b9d65dd8cecc4ec5621c1784d94ce68ec05cebc8e5fedef994a4f3"
PANEL_HEADER_R4_FAILED_TERMINAL_SHA256 = "df2e455000e9eb6350cf78566049b53eb686ec5f5dc0ea3c59b80d1c27a7a0f8"
PANEL_HEADER_R4_CONTRACT_SHA256 = "ec0c7e7fbb8d01f5030b623fd52f9f9e15a865d8bbe0ab108beeb44cec5143de"
PANEL_HEADER_R4_BINDING_SHA256 = "492c7681187b35b6f437002630c6c0e36adf0d11a4052abc25d0f07a8319918d"
PANEL_HEADER_R4_READ_RELEASE_SHA256 = "2e1c20c7c5d7051a3dad235f9c99c86d68965dac9f07a59d1408c439d62f0a84"
PANEL_HEADER_R5_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "r5_one_shot_pipeline" / "R5_ADMISSION_READ_RELEASE_FAILURE_RECEIPT.json"
PANEL_HEADER_R5_FAILED_RECEIPT_SHA256 = "6003fc3057fa0f1fbc735a2072e590cb38756efab9cd92875de06376f9973971"
PANEL_HEADER_R5_RECOVERY_GRANT_ID = "PARENT_PANEL_DATE_RECOVERY_R5_ENGINEERING_RETRY_20261011"
PANEL_HEADER_R5_RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{PANEL_HEADER_R5_RECOVERY_GRANT_ID}"
PANEL_HEADER_R5_RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_PARENT_PANEL_DATE_RECOVERY_R5_ENGINEERING_RETRY_20261011_ONE_SHOT"
PANEL_HEADER_R5_FAILED_START_SHA256 = "767f6d88d9c3ab9cd3fbe56e80f4e49422ce9600d2200a25715e3cf20388934a"
PANEL_HEADER_R5_FAILED_TERMINAL_SHA256 = "f1a4a5f9149ab029b1e5130576e884a9a6ae5320c40f71c17ad6d3d24d53e39b"
PANEL_HEADER_R5_CONTRACT_SHA256 = "ab688600e29167bc53572feaf876f4c1bd034155a807389c84f366d32353c9c8"
PANEL_HEADER_R5_BINDING_SHA256 = "e0cafbab67e6f118ed15b2d88907a898e6bc56af658b4a93ca3b76c46db3d0fc"
PANEL_HEADER_R5_READ_RELEASE_SHA256 = "b73dcf26dfc196c7712572d115e8380978bb92fed7eeb7fb11393308ac86f288"
PANEL_HEADER_R6_RECOVERY_GRANT_ID = "PARENT_PANEL_DATE_RECOVERY_R6_ENGINEERING_RETRY_20261011"
PANEL_HEADER_R6_RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{PANEL_HEADER_R6_RECOVERY_GRANT_ID}"
PANEL_HEADER_R6_RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_PARENT_PANEL_DATE_RECOVERY_R6_ENGINEERING_RETRY_20261011_ONE_SHOT"
PANEL_HEADER_R6_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "R6_ADMISSION_RUNTIME_NAMEERROR_RECEIPT.json"
PANEL_HEADER_R6_FAILED_RECEIPT_SHA256 = "a27eb9f90bb4602838a046416d86051835d5042f0f12af377caf617d2808c7e2"
PANEL_HEADER_R6_FAILED_START_SHA256 = "1316f094c7a24de75ca2bdd8de7c030fded39dec4b11f7d0d14b6908b6b3122c"
PANEL_HEADER_R6_FAILED_TERMINAL_SHA256 = "28700bc957bd1da47b955e1c18abe92ae2bb78a45abb789277fc9ca09bc52737"
PANEL_HEADER_R6_CONTRACT_SHA256 = "747e740c294d9ccce5c3580f6c99416e62bcd8a7c4ecb8ccc4d1e5f4ea616149"
PANEL_HEADER_R6_BINDING_SHA256 = "73230aff339f0dada87c03e0eddef2207dea4f589ba82a40f68819b6f2686381"
PANEL_HEADER_R6_READ_RELEASE_SHA256 = "ecafd24351119bf0bf7993c27b6ccd04585e908fa5691f8298e5d0773c5a98f0"
PANEL_HEADER_R6_GRANT_SHA256 = "024690f73f3faf8714e3d6dafe46067b0117d2f008c1c357dc10e96b86e1efbf"
PANEL_HEADER_RECOVERY_GRANT_ID = "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011"
PANEL_HEADER_RECOVERY_ACTION_KEY = f"{ROUTE_ID}:{CANDIDATE_ID}:{RECOVERY_ACTION}:{PANEL_HEADER_RECOVERY_GRANT_ID}"
PANEL_HEADER_RECOVERY_EXECUTION_ID = f"{ROUTE_ID}_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_20261011_ONE_SHOT"
PANEL_HEADER_RECOVERY_GRANT_PATH = BATCH_ROOT / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_GRANT.json"
PANEL_HEADER_RECOVERY_READ_RELEASE_PATH = BATCH_ROOT / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE.json"
PANEL_HEADER_RECOVERY_READ_PLAN_PATH = BATCH_ROOT / "bindings" / "REAL_INPUT_READ_PLAN_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY.json"
PANEL_HEADER_RECOVERY_OUTPUT_PATH = BATCH_ROOT / "receipts" / "r7_one_shot_pipeline_recovery_01"
PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH = BATCH_ROOT / "receipts" / "r7_one_shot_pipeline" / "PIPELINE_TERMINAL_RECEIPT.json"
PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256 = "53ecf0df022637644c350d2fa50a274712d436d61bc9c2a5f9fff289909c8545"
PANEL_HEADER_RECOVERY_PRIOR_FAILURE_ACTION_DEBIT = 0
PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH = BATCH_ROOT / "receipts" / "r7_recovery_05" / "control_resume" / "R7_RECOVERY_05_RESUME_AUTHORIZATION_V2.json"
PANEL_HEADER_RECOVERY_RESUME_CONTRACT_PATH = BATCH_ROOT / "receipts" / "r7_recovery_05" / "control_resume" / "R7_RECOVERY_05_RESUME_CONTRACT_V2.json"
PANEL_HEADER_RECOVERY_RESUME_PENDING_BINDING_PATH = BATCH_ROOT / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_PENDING_BINDING_RESUME_02.json"
PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH = BATCH_ROOT / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE_RESUME_02.json"
PANEL_HEADER_RECOVERY_RESUME_FINAL_BINDING_PATH = BATCH_ROOT / "bindings" / "PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_ADMITTED_BINDING_RESUME_02.json"
PANEL_HEADER_RECOVERY_RESUME_RUN_PATH = BATCH_ROOT / "receipts" / "r7_recovery_05" / "resume_invocation_02"
PANEL_HEADER_RECOVERY_RESUME_CHECKPOINT_PATH = PANEL_HEADER_RECOVERY_RESUME_RUN_PATH / "RESUME_CHECKPOINT_PRETARGET.json"
PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256 = "e58ec6c92b2b2e94fad58c77c0a24c4110c783905b75d06fd0c9a7fd512887b6"
PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_PATH = BATCH_ROOT / "receipts" / "r4_one_shot_pipeline" / "R4_ADMISSION_RUNTIME_FAILURE_RECEIPT.json"
PANEL_HEADER_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "input_admission" / "INPUT_ADMISSION_AUDIT_RECEIPT_TRAIN_LABEL_RECOVERY_R3.json"
PANEL_HEADER_FAILED_RECEIPT_SHA256 = "1adbfabc9919745787a7a6c3d77e504660a214b2dbab71014ae3858d803f7e0a"
PANEL_HEADER_FAILED_EXECUTION_ID = TRAIN_LABEL_RECOVERY_EXECUTION_ID
PANEL_HEADER_FAILED_START_SHA256 = "0590a45ca4476f58098b1e793f3b9872f74ee2af0eeb18a12daa2df8a4c681d4"
PANEL_HEADER_FAILED_TERMINAL_SHA256 = "88519580c2c6f56b5363e813e7020a58660ae08beeaf2516b4503427ca89d0d2"
PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH = BATCH_ROOT / "receipts" / "registry_append" / f"{PANEL_HEADER_FAILED_EXECUTION_ID}.json"
PANEL_HEADER_FAILED_REGISTRY_RECEIPT_SHA256 = "b687f38767ba2aa79c90dd43c414ce651f1beee03d3e1becfa90d6aa0e83540d"
PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH = BATCH_ROOT / "diagnostics" / "parent_panel_header_r1_20261011" / "PANEL_HEADER_DIAGNOSTIC_RECEIPT.json"
PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256 = "0459b9fe6001a2b93ed4dbdc3d44b6b1f0015621b9b4714c2a52f347dbe7ee5b"
PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID = f"{ROUTE_ID}_PANEL_HEADER_DIAGNOSTIC_R1_20261011_ONE_SHOT"
PANEL_HEADER_DIAGNOSTIC_START_EVENT_ID = f"{PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID}_RUN_STARTED"
PANEL_HEADER_DIAGNOSTIC_TERMINAL_EVENT_ID = f"{PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID}_TERMINAL"
PANEL_HEADER_DIAGNOSTIC_START_SHA256 = "954063515a870263a0c0fe732dce5734c7dc57892d6160a0f8eae6a9a6fb3294"
PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256 = "f66d5be4f89690dc6582175fea81512e8a538633d1762e5d590c2f9673345908"
TRAIN_LABEL_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "input_admission" / "INPUT_ADMISSION_AUDIT_RECEIPT_KEY_ALIGNMENT_RECOVERY_R2.json"
TRAIN_LABEL_FAILED_RECEIPT_SHA256 = "76e2c3fa388b90c08033ae8fd4a338a26c9eb73a9dc382b0de301a23b7eac2d5"
TRAIN_LABEL_FAILED_EXECUTION_ID = KEY_ALIGNMENT_EXECUTION_ID
TRAIN_LABEL_FAILED_CONTRACT_SHA256 = "d9fd7f49fa292e58a35da057427f2f8e2862f7399f695f4a4e1ad89aceedd78d"
TRAIN_LABEL_FAILED_BINDING_SHA256 = "c6e3717e1cfe23ebccc0662d1e3c322bf1e1b9f5f7d54b29df9de47ebf495b31"
TRAIN_LABEL_FAILED_START_SHA256 = "ac2fc5662043452ecd40fed76aef0f625bec52ba893293826fa929f6e013476d"
TRAIN_LABEL_FAILED_TERMINAL_SHA256 = "c0f75f4d0cf010453b0f244eeb38f99b05632a3ba02ff33ac631295898782c94"
TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_PATH = BATCH_ROOT / "receipts" / "registry_append" / f"{TRAIN_LABEL_FAILED_EXECUTION_ID}.json"
TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_SHA256 = "f7a2ba9515f9bfe37fddd439ab200b477091a5669a50e809f711ff11281c11f5"
TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH = BATCH_ROOT / "diagnostics" / "train_label_diagnostic_r2_20261011" / "TRAIN_LABEL_DIAGNOSTIC_RECEIPT.json"
TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256 = "404dc25f7e23c6969d5bc2493923da5cc34522b371310b1fbc07cb96973ac084"
TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID = f"{ROUTE_ID}_TRAIN_LABEL_DIAGNOSTIC_R2_20261011_ONE_SHOT"
TRAIN_LABEL_DIAGNOSTIC_START_SHA256 = "7033d4b7273459247340c7c5bbd5439450d7d348e00e4c689c4e72991ca50954"
TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256 = "707cee37ef885acf07fc09732782797e745435676803225892964fc95381f6fb"
TRAIN_LABEL_DIAGNOSTIC_CORRECTION_EVENT_ID = f"{TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID}_CORRECTION_TRAIN_LABEL_ARRAY_READ"
TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256 = "57a5cebf9cbe2bcaedca5f4ddefec063e1a65c2f26108d7bc06ad6ad46adc410"
TRAIN_LABEL_DIAGNOSTIC_START_EVENT_ID = f"{TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID}_RUN_STARTED"
TRAIN_LABEL_DIAGNOSTIC_TERMINAL_EVENT_ID = f"{TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID}_TERMINAL"
KEY_ALIGNMENT_FAILED_RECEIPT_PATH = BATCH_ROOT / "receipts" / "input_admission" / "INPUT_ADMISSION_AUDIT_RECEIPT_RECOVERY_R1.json"
KEY_ALIGNMENT_FAILED_RECEIPT_SHA256 = "18892cf7078a12d6844b3973d96611a40e237dce01b4320a825444cc0ef74ff2"
KEY_ALIGNMENT_FAILED_EXECUTION_ID = f"{ROUTE_ID}_INPUT_ADMISSION_RECOVERY_R1_20261011_ONE_SHOT"
KEY_ALIGNMENT_FAILED_START_SHA256 = "3dbf33666c83e6f82474af257504255b979a355a960e71922e5ffe8c8171f29c"
KEY_ALIGNMENT_FAILED_TERMINAL_SHA256 = "3a8506ded4862d9a57e9335b36ca4e51cdb3cb5cf6ed224990ac52ee3b0f6b0a"
KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH = BATCH_ROOT / "receipts" / "registry_append" / f"{KEY_ALIGNMENT_FAILED_EXECUTION_ID}.json"
KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_SHA256 = "6d28d6ecdeeb138b204b70652742b3d56c246a30223d64356ceaa517e4597a87"
FAILED_ADMISSION_EXECUTION_ID = (
    f"{ROUTE_ID}_{CANDIDATE_ID}_INPUT_ADMISSION_ONE_SHOT"
)
FAILED_ADMISSION_RECEIPT_PATH = (
    BATCH_ROOT / "receipts" / "stage2_admission_one_shot" / "INPUT_ADMISSION_ATTEMPT_RECEIPT.json"
)
FAILED_ADMISSION_RECEIPT_SHA256 = "8349dab1c771867509f64ca4f0fde44cd1b7b4121030ae90e38c4bd9c9570463"
FAILED_ADMISSION_START_SHA256 = "c4349cd826d060af3837a62e2a6c649883c399aee9f1de18d9e1566f96b75476"
FAILED_ADMISSION_TERMINAL_SHA256 = "813b0de8773a1e10a553e6246bc83c973947fd8d85cb05bbe26ef64dac7b59bc"
FAILED_ADMISSION_START_ID = f"{FAILED_ADMISSION_EXECUTION_ID}_RUN_STARTED"
FAILED_ADMISSION_TERMINAL_ID = f"{FAILED_ADMISSION_EXECUTION_ID}_TERMINAL"
ACTION_SET = frozenset({"input_admission", RECOVERY_ACTION, "fit", "predict", "truth_decode"})
ACTION_CAP = 1
METRICS_SOURCE_ROOT = PROJECT_ROOT / "handoffs" / "BREADTH1_ADMISSION_MATERIALS_20261010" / "sources" / "f5"
REQUIRED_METRICS_DEPENDENCIES = frozenset({
    "spike5/settings.py",
    "spike5/common.py",
    "spike5/features.py",
    "config/contract.json",
    "config/base_features.json",
    "config/feature_order_64.json",
})

OFFICIAL_COMPONENT_SHA256 = {
    "execution_guard_core.py": "85929366a7b018480085c02f80edd312f7f47de94bab5c32982d4e8637d7d7e0",
    "registry_adapter.py": "8596f2a20c165b5fbc2b92a597cb3e1177f6e40bfefac62753b40b3c7daae17f",
    "build_experiment_registry_backfill_20260821.py": "df4bfc89fa5487966a8c7e1c1c50832e140339c2ccda3a02a9a59e5aaaeb58cf",
    "validate_experiment_registry_append_compatibility_v1.py": "80e49d05d13f33ee7e2cb8d4d10cae0e297bcdf5b113ff857d3bd141dea0f438",
}


class ActionBudgetError(RuntimeError):
    """The candidate action budget cannot be safely interpreted or consumed."""


class ActionBudgetConsumed(ActionBudgetError):
    """The fixed route/candidate/action key already has a durable start event."""


class ActionBudgetIdentityDrift(ActionBudgetError):
    """An existing route/candidate event is bound to different frozen inputs."""


class OfficialActionCapabilityMissing(ActionBudgetError):
    """The bound official builder/validator/adapter interface is incomplete."""


@dataclass(frozen=True)
class VerifiedActionRelease:
    path: Path
    expected_sha256: str


@dataclass(frozen=True)
class VerifiedActionContext:
    """One read of all action identity documents and the code they bind."""

    contract_value: Mapping[str, Any]
    input_binding_value: Mapping[str, Any]
    release_value: Mapping[str, Any]
    contract_sha256: str
    input_binding_sha256: str
    release_sha256: str
    input_admission_receipt_value: Mapping[str, Any]
    input_admission_receipt_sha256: str
    input_admission_receipt_bytes: int


@dataclass(frozen=True)
class ActionBudgetClaim:
    route_id: str
    candidate_id: str
    action: str
    action_key: str
    execution_id: str
    contract_sha256: str
    input_binding_sha256: str
    release_sha256: str
    sealed_status: str
    registry_event_id: str
    registry_event_sha256: str


def _require_real_execution_contract(contract: Mapping[str, Any]) -> None:
    if (
        contract.get("is_execution_contract") is not True
        or contract.get("status") != "REAL_EXECUTION_READY"
        or contract.get("real_release_issued") is not True
        or contract.get("synthetic_only") is not False
    ):
        raise ActionBudgetIdentityDrift("REAL_ACTION_REQUIRES_EXPLICIT_EXECUTION_READY_CONTRACT_AND_RELEASE")


def _require_admission_gated_real_action(
    contract: Mapping[str, Any],
    binding: Mapping[str, Any],
    admission_receipt_snapshot: tuple[Mapping[str, Any], str, int] | None,
    *,
    contract_sha256: str,
    input_binding_sha256: str,
) -> None:
    """Permit the frozen R3 draft only after its exact admission PASS is verified.

    The admission check and subsequent actions intentionally share the same
    frozen contract bytes.  Its draft status cannot authorize an action by
    itself: this transition requires the final PASS binding, the byte-verified
    receipt, and the linked fixed R2 admission lifecycle before any release is
    considered.
    """
    if contract.get("status") == "REAL_EXECUTION_READY":
        _require_real_execution_contract(contract)
        return
    if admission_receipt_snapshot is None:
        raise ActionBudgetIdentityDrift("ADMISSION_GATED_ACTION_REQUIRES_VERIFIED_RECEIPT")
    receipt, receipt_sha256, receipt_bytes = admission_receipt_snapshot
    source_binding = binding.get("source_binding")
    receipt_path = binding.get("input_admission_receipt_path")
    pre_binding_sha256 = binding.get("pre_admission_binding_sha256")
    if (
        contract.get("route_id") != ROUTE_ID
        or contract.get("candidate_id") != CANDIDATE_ID
        or contract.get("status") != "DRAFT_NO_REAL_RUN"
        or contract.get("is_execution_contract") is not False
        or contract.get("real_release_issued") is not False
        or contract.get("synthetic_only") is not False
        or binding.get("schema") != "F5_BREADTH1_REAL_INPUT_BINDING_V1"
        or binding.get("route_id") != ROUTE_ID
        or binding.get("candidate_id") != CANDIDATE_ID
        or binding.get("status") != "PASS"
        or binding.get("input_admission_status") != "PASS"
        or binding.get("synthetic_only") is not False
        or binding.get("contract_sha256") != contract_sha256
        or binding.get("input_admission_receipt_sha256") != receipt_sha256
        or binding.get("input_admission_receipt_path") != receipt_path
        or not isinstance(receipt_path, str)
        or Path(receipt_path).is_symlink()
        or not Path(receipt_path).is_absolute()
        or not isinstance(pre_binding_sha256, str)
        or len(pre_binding_sha256) != 64
        or receipt.get("schema") != "F5_BREADTH1_INPUT_ADMISSION_RECEIPT_V1"
        or receipt.get("status") != "PASS"
        or receipt.get("decision") != "INPUT_ADMISSION_PASS"
        or receipt.get("real_input_accessed") is not True
        or receipt.get("contract_sha256") != contract_sha256
        or receipt.get("input_binding_sha256") != pre_binding_sha256
        or receipt.get("pre_admission_binding_sha256") != pre_binding_sha256
        or receipt.get("receipt_path") != receipt_path
        or receipt.get("registry_execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or receipt.get("registry_budget_action_key") != PANEL_HEADER_RECOVERY_ACTION_KEY
        or receipt.get("registry_budget_action") != RECOVERY_ACTION
        or receipt.get("recovery_grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
        or receipt.get("linked_failed_execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
        or receipt.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
        or receipt.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
        or receipt.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
        or receipt.get("linked_r4_ancestor_failure_execution_id") != PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
        or receipt.get("linked_r4_ancestor_failure_receipt_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
        or receipt.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
        or receipt.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
        or receipt.get("historical_producer_status") != "LINEAGE_UNAVAILABLE"
        or receipt.get("provenance_mode") != "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
        or not _valid_prior_train_label_diagnostic(receipt.get("prior_train_label_diagnostic"))
        or not _valid_prior_panel_header_diagnostic(receipt.get("prior_panel_header_diagnostic"))
        or not _valid_prior_panel_header_runtime_failure(receipt.get("prior_panel_header_runtime_failure"))
        or not _valid_prior_panel_header_r5_failure(receipt.get("prior_panel_header_r5_failure"))
        or not _valid_prior_panel_header_r6_failure(receipt.get("prior_panel_header_r6_failure"))
        or receipt_bytes < 1
        or not isinstance(source_binding, Mapping)
        or source_binding.get("status") != "LINEAGE_UNAVAILABLE"
        or source_binding.get("provenance_mode") != "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
        or binding.get("input_admission_read_release_sha256") != receipt.get("read_release_sha256")
        or input_binding_sha256 == pre_binding_sha256
    ):
        raise ActionBudgetIdentityDrift("ADMISSION_GATED_REAL_ACTION_IDENTITY_MISMATCH")


def _parse_json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        def unique_pairs(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ActionBudgetIdentityDrift(f"{label}_DUPLICATE_JSON_KEY:{key}")
                result[key] = item
            return result

        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionBudgetIdentityDrift(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, Mapping):
        raise ActionBudgetIdentityDrift(f"{label}_MUST_BE_JSON_OBJECT")
    return value


def _valid_prior_train_label_diagnostic(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    counts = value.get("unique_value_counts")
    return (
        value.get("status") == "DIAGNOSTIC_COMPLETE"
        and value.get("diagnostic_receipt_sha256") == TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256
        and value.get("registry_start_event_sha256") == TRAIN_LABEL_DIAGNOSTIC_START_SHA256
        and value.get("registry_terminal_event_sha256") == TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256
        and value.get("registry_correction_event_sha256") == TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256
        and value.get("target_expected_sha256") == "2ee8f46889ab1c1c2d23bc851b47ed6925a983c08c75bbcfeafd393cace007d6"
        and value.get("target_actual_sha256") == "2ee8f46889ab1c1c2d23bc851b47ed6925a983c08c75bbcfeafd393cace007d6"
        and value.get("target_bytes_read") == 4317176
        and value.get("physical_file_reads") == 1
        and value.get("dtype") == "float64"
        and value.get("dtype_kind") == "f"
        and value.get("shape") == [539631]
        and value.get("array_nbytes") == 4317048
        and value.get("finite_count") == 539631
        and value.get("nonfinite_count") == 0
        and value.get("minimum") == 0.0
        and value.get("maximum") == 1.0
        and value.get("unique_value_count") == 2
        and counts == [{"value": 0.0, "count": 538732}, {"value": 1.0, "count": 899}]
        and value.get("positive_count") == 899
        and value.get("shape_predicate") is True
        and value.get("integer_dtype_predicate") is False
        and value.get("binary_domain_predicate") is True
        and value.get("positive_899_predicate") is True
        and value.get("combined_guard_pass") is False
        and value.get("corrected_dtype_kind_accepts_float") is True
        and value.get("corrected_guard_expected_pass") is True
        and value.get("positive_count_semantics") == "899 positive rows in the frozen y_train array; 183 distinct positive episodes"
        and value.get("positive_count_basis_status") == "LINEAGE_LOOKUP_RESULT_REPORTED"
        and value.get("positive_count_basis_refs") == [
            "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_MAP_CLASSIFICATION_RECOVERY01_RESULT.json:7",
            "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_WEIGHT_BUILD_GLOBAL01_RESULT.json:38",
        ]
    )


def _train_label_diagnostic_summary(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "DIAGNOSTIC_COMPLETE",
        "diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
        "registry_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
        "registry_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
        "registry_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
        "target_expected_sha256": diagnostic["expected_sha256"],
        "target_actual_sha256": diagnostic["actual_sha256"],
        "target_bytes_read": diagnostic["bytes_read"],
        "physical_file_reads": diagnostic["physical_file_reads"],
        "dtype": diagnostic["dtype"],
        "dtype_kind": diagnostic["dtype_kind"],
        "shape": diagnostic["shape"],
        "array_nbytes": diagnostic["array_nbytes"],
        "finite_count": diagnostic["finite_count"],
        "nonfinite_count": diagnostic["nonfinite_count"],
        "minimum": diagnostic["minimum"],
        "maximum": diagnostic["maximum"],
        "unique_value_count": diagnostic["unique_value_count"],
        "unique_value_counts": diagnostic["unique_value_counts"],
        "positive_count": diagnostic["positive_count"],
        "shape_predicate": diagnostic["old_shape_predicate"],
        "integer_dtype_predicate": diagnostic["old_integer_dtype_predicate"],
        "binary_domain_predicate": diagnostic["old_binary_domain_predicate"],
        "positive_899_predicate": diagnostic["old_positive_899_predicate"],
        "combined_guard_pass": diagnostic["old_combined_guard_pass"],
        "corrected_dtype_kind_accepts_float": diagnostic["dtype_kind"] in "iuf",
        "corrected_guard_expected_pass": True,
        "positive_count_semantics": "899 positive rows in the frozen y_train array; 183 distinct positive episodes",
        "positive_count_basis_status": "LINEAGE_LOOKUP_RESULT_REPORTED",
        "positive_count_basis_refs": [
            "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_MAP_CLASSIFICATION_RECOVERY01_RESULT.json:7",
            "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_WEIGHT_BUILD_GLOBAL01_RESULT.json:38",
        ],
    }


def _verify_train_label_diagnostic(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Verify the fixed diagnostic receipt and its correction-complete registry chain."""
    if (
        not TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH.is_file()
        or TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH.is_symlink()
        or sha256_file(TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH) != TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256
    ):
        raise ActionBudgetIdentityDrift("TRAIN_LABEL_DIAGNOSTIC_RECEIPT_IDENTITY_MISMATCH")
    receipt = _parse_json_object(TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH.read_bytes(), "TRAIN_LABEL_DIAGNOSTIC_RECEIPT")
    diagnostic = receipt.get("diagnostic")
    if (
        receipt.get("schema") != "F5_BREADTH1_TRAIN_LABEL_DIAGNOSTIC_RECEIPT_V1"
        or receipt.get("status") != "DIAGNOSTIC_COMPLETE"
        or receipt.get("execution_id") != TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID
        or receipt.get("registry_start_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_START_SHA256
        or receipt.get("registry_terminal_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256
        or receipt.get("physical_target_file_reads") != 1
        or receipt.get("target_bytes_read") != 4317176
        or receipt.get("real_fit_calls") != 0
        or receipt.get("real_predict_calls") != 0
        or receipt.get("model_load_calls") != 0
        or receipt.get("real_truth_decode_calls") != 0
        or receipt.get("truth_access") != "NOT_READ"
        or receipt.get("research_only") is not True
        or receipt.get("production_allowed") is not False
        or receipt.get("buy_gate_updated") is not False
        or receipt.get("orders_sent") is not False
        or not isinstance(diagnostic, Mapping)
        or diagnostic.get("status") != "DIAGNOSTIC_COMPLETE"
        or diagnostic.get("expected_sha256") != "2ee8f46889ab1c1c2d23bc851b47ed6925a983c08c75bbcfeafd393cace007d6"
        or diagnostic.get("actual_sha256") != "2ee8f46889ab1c1c2d23bc851b47ed6925a983c08c75bbcfeafd393cace007d6"
        or diagnostic.get("bytes_read") != 4317176
        or diagnostic.get("physical_file_reads") != 1
        or diagnostic.get("dtype") != "float64"
        or diagnostic.get("dtype_kind") != "f"
        or diagnostic.get("shape") != [539631]
        or diagnostic.get("array_nbytes") != 4317048
        or diagnostic.get("finite_count") != 539631
        or diagnostic.get("nonfinite_count") != 0
        or diagnostic.get("minimum") != 0.0
        or diagnostic.get("maximum") != 1.0
        or diagnostic.get("unique_value_count") != 2
        or diagnostic.get("unique_value_counts") != [{"value": 0.0, "count": 538732}, {"value": 1.0, "count": 899}]
        or diagnostic.get("positive_count") != 899
        or diagnostic.get("old_shape_predicate") is not True
        or diagnostic.get("old_integer_dtype_predicate") is not False
        or diagnostic.get("old_binary_domain_predicate") is not True
        or diagnostic.get("old_positive_899_predicate") is not True
        or diagnostic.get("old_combined_guard_pass") is not False
    ):
        raise ActionBudgetIdentityDrift("TRAIN_LABEL_DIAGNOSTIC_RECEIPT_CONTENT_MISMATCH")
    lifecycle = [event for event in events if event.get("execution_id") == TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID]
    by_id = {event.get("registry_event_id"): event for event in lifecycle}
    if len(lifecycle) != 3 or set(by_id) != {
        TRAIN_LABEL_DIAGNOSTIC_START_EVENT_ID,
        TRAIN_LABEL_DIAGNOSTIC_TERMINAL_EVENT_ID,
        TRAIN_LABEL_DIAGNOSTIC_CORRECTION_EVENT_ID,
    }:
        raise ActionBudgetIdentityDrift("TRAIN_LABEL_DIAGNOSTIC_REGISTRY_LIFECYCLE_NOT_EXACT")
    start = by_id[TRAIN_LABEL_DIAGNOSTIC_START_EVENT_ID]
    terminal = by_id[TRAIN_LABEL_DIAGNOSTIC_TERMINAL_EVENT_ID]
    correction = by_id[TRAIN_LABEL_DIAGNOSTIC_CORRECTION_EVENT_ID]
    metrics = terminal.get("deterministic_metrics")
    corrected = correction.get("deterministic_metrics")
    if (
        start.get("event_type") != "RUN_STARTED"
        or start.get("event_sha256") != TRAIN_LABEL_DIAGNOSTIC_START_SHA256
        or start.get("decision") != "RUNNING"
            or not isinstance(start.get("deterministic_metrics"), Mapping)
            or start["deterministic_metrics"].get("training_label_array_read") != 0
        or terminal.get("event_type") != "TERMINAL"
        or terminal.get("event_sha256") != TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256
        or terminal.get("decision") != "DIAGNOSTIC_COMPLETE"
        or not isinstance(metrics, Mapping)
        or metrics.get("training_label_array_read") != 1
        or metrics.get("train_label_file_reads") != 1
        or metrics.get("train_label_bytes_read") != 4317176
        or metrics.get("label_dtype") != "float64"
        or metrics.get("label_shape") != [539631]
        or metrics.get("label_min") != 0.0
        or metrics.get("label_max") != 1.0
        or metrics.get("label_positive_count") != 899
        or correction.get("event_type") != "CORRECTION"
        or correction.get("event_sha256") != TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256
        or not isinstance(corrected, Mapping)
        or corrected.get("corrects_registry_event_id") != TRAIN_LABEL_DIAGNOSTIC_TERMINAL_EVENT_ID
        or corrected.get("corrects_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256
        or corrected.get("corrected_fields") != ["input_identity.training_label_array_read"]
        or not isinstance(correction.get("input_identity"), Mapping)
        or correction["input_identity"].get("training_label_array_read") != 1
    ):
        raise ActionBudgetIdentityDrift("TRAIN_LABEL_DIAGNOSTIC_REGISTRY_CONTENT_MISMATCH")
    return diagnostic


def _panel_header_diagnostic_summary(receipt: Mapping[str, Any]) -> dict[str, Any]:
    diagnostic = receipt.get("diagnostic")
    if not isinstance(diagnostic, Mapping):
        return {}
    return {
        "status": "HEADER_DIAGNOSTIC_COMPLETE",
        "diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
        "registry_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
        "registry_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
        "target_expected_sha256": diagnostic.get("expected_sha256"),
        "target_actual_sha256": diagnostic.get("actual_sha256"),
        "target_bytes_read": diagnostic.get("bytes_read"),
        "physical_file_reads": diagnostic.get("physical_file_reads"),
        "expected_header_columns": diagnostic.get("expected_header_columns"),
        "actual_header_column_count": diagnostic.get("actual_header_column_count"),
        "actual_header_columns": diagnostic.get("actual_header_columns"),
        "duplicate_header_columns": diagnostic.get("duplicate_header_columns"),
        "missing_required_header_columns": diagnostic.get("missing_required_header_columns"),
        "parser_rejection_condition": diagnostic.get("parser_rejection_condition"),
    }


def _valid_prior_panel_header_diagnostic(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("status") == "HEADER_DIAGNOSTIC_COMPLETE"
        and value.get("diagnostic_receipt_sha256") == PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256
        and value.get("registry_start_event_sha256") == PANEL_HEADER_DIAGNOSTIC_START_SHA256
        and value.get("registry_terminal_event_sha256") == PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
        and value.get("target_expected_sha256") == "5303a9f7ad55cc438c200b260538d7265729af2a2c6c396c955211b9dd806902"
        and value.get("target_actual_sha256") == "5303a9f7ad55cc438c200b260538d7265729af2a2c6c396c955211b9dd806902"
        and value.get("target_bytes_read") == 534661
        and value.get("physical_file_reads") == 1
        and value.get("expected_header_columns") == ["code", "session_id", "market_date", "feature_row_present", "ret_1d"]
        and value.get("actual_header_column_count") == 48
        and isinstance(value.get("actual_header_columns"), list)
        and len(value["actual_header_columns"]) == 48
        and value.get("duplicate_header_columns") == []
        and value.get("missing_required_header_columns") == ["market_date"]
        and value.get("parser_rejection_condition") == "MISSING_REQUIRED_COLUMNS"
    )


def _panel_header_runtime_failure_summary(receipt: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle = receipt.get("registry_lifecycle")
    if not isinstance(lifecycle, Mapping):
        return {}
    return {
        "status": "R4_ACTION_FAILED",
        "execution_id": PANEL_HEADER_R4_RECOVERY_EXECUTION_ID,
        "recovery_grant_id": PANEL_HEADER_R4_RECOVERY_GRANT_ID,
        "contract_sha256": PANEL_HEADER_R4_CONTRACT_SHA256,
        "input_binding_sha256": PANEL_HEADER_R4_BINDING_SHA256,
        "read_release_sha256": PANEL_HEADER_R4_READ_RELEASE_SHA256,
        "failure_receipt_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
        "registry_start_event_sha256": PANEL_HEADER_R4_FAILED_START_SHA256,
        "registry_terminal_event_sha256": PANEL_HEADER_R4_FAILED_TERMINAL_SHA256,
        "error_type": "AttributeError",
        "failure_location": "_attach_parent_market_date:sessions.map(session_to_date)",
        "physical_input_file_count": None,
        "input_bytes_read": None,
        "input_read_counts_status": "CANNOT_CONFIRM",
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_model_load_calls": 0,
        "real_truth_decode_calls": 0,
    }


def _valid_prior_panel_header_runtime_failure(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return value == {
        "status": "R4_ACTION_FAILED",
        "execution_id": PANEL_HEADER_R4_RECOVERY_EXECUTION_ID,
        "recovery_grant_id": PANEL_HEADER_R4_RECOVERY_GRANT_ID,
        "contract_sha256": PANEL_HEADER_R4_CONTRACT_SHA256,
        "input_binding_sha256": PANEL_HEADER_R4_BINDING_SHA256,
        "read_release_sha256": PANEL_HEADER_R4_READ_RELEASE_SHA256,
        "failure_receipt_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
        "registry_start_event_sha256": PANEL_HEADER_R4_FAILED_START_SHA256,
        "registry_terminal_event_sha256": PANEL_HEADER_R4_FAILED_TERMINAL_SHA256,
        "error_type": "AttributeError",
        "failure_location": "_attach_parent_market_date:sessions.map(session_to_date)",
        "physical_input_file_count": None,
        "input_bytes_read": None,
        "input_read_counts_status": "CANNOT_CONFIRM",
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_model_load_calls": 0,
        "real_truth_decode_calls": 0,
    }


def _panel_header_r5_precall_failure_summary() -> dict[str, Any]:
    return {
        "status": "INPUT_ADMISSION_FAILED_BEFORE_TARGET_DATA_READ",
        "execution_id": PANEL_HEADER_R5_RECOVERY_EXECUTION_ID,
        "recovery_grant_id": PANEL_HEADER_R5_RECOVERY_GRANT_ID,
        "contract_sha256": PANEL_HEADER_R5_CONTRACT_SHA256,
        "input_binding_sha256": PANEL_HEADER_R5_BINDING_SHA256,
        "read_release_sha256": PANEL_HEADER_R5_READ_RELEASE_SHA256,
        "failure_receipt_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
        "registry_start_event_sha256": PANEL_HEADER_R5_FAILED_START_SHA256,
        "registry_terminal_event_sha256": PANEL_HEADER_R5_FAILED_TERMINAL_SHA256,
        "failed_stage": "verified_read_release_binding",
        "error_type": "AdmissionBlocked",
        "error": "INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH",
        "failure_location": "load_verified_input_admission_read_release: frozen_binding_path hard-coded to R4 draft",
        "data_read_ledger_status": "NOT_CREATED_PRE_AUDIT",
        "target_input_files_opened": 0,
        "target_input_bytes_read": 0,
        "real_input_accessed": False,
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_model_load_calls": 0,
        "real_truth_decode_calls": 0,
        "failure_or_interruption_refund": False,
    }


def _valid_prior_panel_header_r5_failure(value: Any) -> bool:
    return isinstance(value, Mapping) and dict(value) == _panel_header_r5_precall_failure_summary()


def _panel_header_r6_runtime_failure_summary() -> dict[str, Any]:
    return {
        "status": "R6_ACTION_FAILED_BEFORE_FROZEN_TARGET_INPUT_READ",
        "execution_id": PANEL_HEADER_R6_RECOVERY_EXECUTION_ID,
        "recovery_grant_id": PANEL_HEADER_R6_RECOVERY_GRANT_ID,
        "contract_sha256": PANEL_HEADER_R6_CONTRACT_SHA256,
        "input_binding_sha256": PANEL_HEADER_R6_BINDING_SHA256,
        "read_release_sha256": PANEL_HEADER_R6_READ_RELEASE_SHA256,
        "recovery_grant_sha256": PANEL_HEADER_R6_GRANT_SHA256,
        "failure_receipt_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
        "registry_start_event_sha256": PANEL_HEADER_R6_FAILED_START_SHA256,
        "registry_terminal_event_sha256": PANEL_HEADER_R6_FAILED_TERMINAL_SHA256,
        "error_type": "NameError",
        "error": "name '_valid_prior_panel_header_r5_failure' is not defined",
        "failure_location": "audit_real_input_admission:_valid_prior_panel_header_r5_failure@410",
        "control_document_file_count": 2,
        "control_document_bytes": 39673,
        "target_input_files_opened": 0,
        "target_input_bytes_read": 0,
        "read_counts_status": "CONTROL_READS_TRACED_TARGET_ZERO_FORMAL_RECEIPT_NOT_PERSISTED",
        "real_input_accessed": False,
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_model_load_calls": 0,
        "real_truth_decode_calls": 0,
        "failure_or_interruption_refund": False,
    }


def _valid_prior_panel_header_r6_failure(value: Any) -> bool:
    return isinstance(value, Mapping) and dict(value) == _panel_header_r6_runtime_failure_summary()


def _verify_panel_header_diagnostic(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    path = PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH
    if not path.is_file() or path.is_symlink() or sha256_file(path) != PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256:
        raise ActionBudgetIdentityDrift("PANEL_HEADER_DIAGNOSTIC_RECEIPT_IDENTITY_MISMATCH")
    receipt = _parse_json_object(path.read_bytes(), "PANEL_HEADER_DIAGNOSTIC_RECEIPT")
    diagnostic = receipt.get("diagnostic")
    summary = _panel_header_diagnostic_summary(receipt)
    if (
        receipt.get("schema") != "F5_BREADTH1_PARENT_PANEL_HEADER_DIAGNOSTIC_RECEIPT_V1"
        or receipt.get("status") != "HEADER_DIAGNOSTIC_COMPLETE"
        or receipt.get("execution_id") != PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID
        or receipt.get("registry_start_event_id") != PANEL_HEADER_DIAGNOSTIC_START_EVENT_ID
        or receipt.get("registry_start_event_sha256") != PANEL_HEADER_DIAGNOSTIC_START_SHA256
        or receipt.get("registry_terminal_event_id") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_EVENT_ID
        or receipt.get("registry_terminal_event_sha256") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
        or receipt.get("physical_target_file_reads") != 1
        or receipt.get("target_bytes_read") != 534661
        or receipt.get("fit_calls") != 0
        or receipt.get("model_load_calls") != 0
        or receipt.get("predict_calls") != 0
        or receipt.get("evaluation_truth_reads") != 0
        or receipt.get("truth_access") != "NOT_READ"
        or receipt.get("research_only") is not True
        or receipt.get("production_allowed") is not False
        or receipt.get("buy_gate_updated") is not False
        or receipt.get("orders_sent") is not False
        or not isinstance(diagnostic, Mapping)
        or diagnostic.get("status") != "HEADER_REJECTED"
        or diagnostic.get("expected_sha256") != "5303a9f7ad55cc438c200b260538d7265729af2a2c6c396c955211b9dd806902"
        or diagnostic.get("actual_sha256") != "5303a9f7ad55cc438c200b260538d7265729af2a2c6c396c955211b9dd806902"
        or diagnostic.get("bytes_read") != 534661
        or diagnostic.get("physical_file_reads") != 1
        or diagnostic.get("sha256_verified") is not True
        or diagnostic.get("actual_header_column_count") != 48
        or len(diagnostic.get("actual_header_columns", [])) != 48
        or diagnostic.get("duplicate_header_columns") != []
        or diagnostic.get("missing_required_header_columns") != ["market_date"]
        or diagnostic.get("parser_rejection_condition") != "MISSING_REQUIRED_COLUMNS"
        or not _valid_prior_panel_header_diagnostic(summary)
    ):
        raise ActionBudgetIdentityDrift("PANEL_HEADER_DIAGNOSTIC_RECEIPT_CONTENT_MISMATCH")
    lifecycle = [event for event in events if event.get("execution_id") == PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID]
    by_id = {event.get("registry_event_id"): event for event in lifecycle}
    if len(lifecycle) != 2 or set(by_id) != {
        PANEL_HEADER_DIAGNOSTIC_START_EVENT_ID, PANEL_HEADER_DIAGNOSTIC_TERMINAL_EVENT_ID,
    }:
        raise ActionBudgetIdentityDrift("PANEL_HEADER_DIAGNOSTIC_REGISTRY_LIFECYCLE_NOT_EXACT")
    start = by_id[PANEL_HEADER_DIAGNOSTIC_START_EVENT_ID]
    terminal = by_id[PANEL_HEADER_DIAGNOSTIC_TERMINAL_EVENT_ID]
    if (
        start.get("event_type") != "RUN_STARTED"
        or start.get("event_sha256") != PANEL_HEADER_DIAGNOSTIC_START_SHA256
        or start.get("decision") != "RUNNING"
        or terminal.get("event_type") != "TERMINAL"
        or terminal.get("event_sha256") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
        or terminal.get("decision") != "HEADER_DIAGNOSTIC_COMPLETE"
    ):
        raise ActionBudgetIdentityDrift("PANEL_HEADER_DIAGNOSTIC_REGISTRY_CONTENT_MISMATCH")
    return summary


def _verify_contract_code_hashes(
    contract: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> None:
    expected = contract.get("code_sha256")
    binding_expected = binding.get("code_sha256")
    if not isinstance(expected, Mapping) or not expected:
        raise ActionBudgetIdentityDrift("CONTRACT_CODE_SHA_BINDING_MISSING")
    if not isinstance(binding_expected, Mapping) or dict(expected) != dict(binding_expected):
        raise ActionBudgetIdentityDrift("CONTRACT_AND_INPUT_CODE_SHA_BINDINGS_DIFFER")
    try:
        verify_candidate_code_bindings(expected)
    except ArtifactContractError as exc:
        raise ActionBudgetIdentityDrift(str(exc)) from exc
    metrics = contract.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ActionBudgetIdentityDrift("CONTRACT_METRICS_SOURCE_BINDING_MISSING")
    source_sha = metrics.get("source_sha256")
    source_path = METRICS_SOURCE_ROOT / "spike5" / "metrics.py"
    if not _is_sha(source_sha) or not source_path.is_file() or sha256_file(source_path) != source_sha:
        raise ActionBudgetIdentityDrift("CONTRACT_METRICS_SOURCE_SHA_MISMATCH")
    dependencies = metrics.get("transitive_sources_sha256")
    if not isinstance(dependencies, Mapping) or set(dependencies) != REQUIRED_METRICS_DEPENDENCIES:
        raise ActionBudgetIdentityDrift("CONTRACT_METRICS_DEPENDENCY_SET_INCOMPLETE")
    metric_root = METRICS_SOURCE_ROOT.resolve()
    for relative, digest in dependencies.items():
        if not isinstance(relative, str) or not _is_sha(digest):
            raise ActionBudgetIdentityDrift("CONTRACT_METRICS_DEPENDENCY_BINDING_INVALID")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ActionBudgetIdentityDrift("CONTRACT_METRICS_DEPENDENCY_PATH_UNSAFE")
        resolved = (metric_root / path).resolve()
        if not _is_relative_to(resolved, metric_root):
            raise ActionBudgetIdentityDrift("CONTRACT_METRICS_DEPENDENCY_PATH_ESCAPES_ROOT")
        if not resolved.is_file() or sha256_file(resolved) != digest:
            raise ActionBudgetIdentityDrift(f"CONTRACT_METRICS_DEPENDENCY_SHA_MISMATCH:{relative}")


def load_verified_action_release(
    release: VerifiedActionRelease,
    *,
    contract_sha256: str,
    input_binding_sha256: str,
    candidate_id: str = CANDIDATE_ID,
    contract_value: Mapping[str, Any] | None = None,
    input_binding_value: Mapping[str, Any] | None = None,
    admission_receipt_snapshot: tuple[Mapping[str, Any], str, int] | None = None,
) -> dict[str, Any]:
    """Read one approval document from a single SHA-verified byte snapshot."""

    payload = Path(release.path).read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != release.expected_sha256:
        raise ActionBudgetError("REAL_RELEASE_SHA_MISMATCH")
    return _decode_verified_action_release(
        payload,
        release_sha256=actual,
        contract_sha256=contract_sha256,
        input_binding_sha256=input_binding_sha256,
        candidate_id=candidate_id,
        contract_value=contract_value,
        input_binding_value=input_binding_value,
        admission_receipt_snapshot=admission_receipt_snapshot,
    )


def _decode_verified_action_release(
    payload: bytes,
    *,
    release_sha256: str,
    contract_sha256: str,
    input_binding_sha256: str,
    candidate_id: str,
    contract_value: Mapping[str, Any] | None,
    input_binding_value: Mapping[str, Any] | None = None,
    admission_receipt_snapshot: tuple[Mapping[str, Any], str, int] | None = None,
) -> dict[str, Any]:
    try:
        value = _parse_json_object(payload, "REAL_RELEASE")
    except ActionBudgetIdentityDrift as exc:
        raise ActionBudgetError(str(exc)) from exc
    if not isinstance(value, Mapping) or value.get("schema") != "F5_BREADTH1_ACTION_BUDGET_RELEASE_V1":
        raise ActionBudgetError("REAL_RELEASE_SCHEMA_MISMATCH")
    if value.get("status") != "APPROVED" or value.get("route_id") != ROUTE_ID:
        raise ActionBudgetError("REAL_RELEASE_NOT_APPROVED_FOR_THIS_ROUTE")
    if value.get("synthetic_only") is not False:
        raise ActionBudgetError("REAL_RELEASE_MUST_EXPLICITLY_BIND_REAL_INPUTS")
    if value.get("candidate_id") != candidate_id:
        raise ActionBudgetError("REAL_RELEASE_CANDIDATE_MISMATCH")
    if value.get("contract_sha256") != contract_sha256 or value.get("input_binding_sha256") != input_binding_sha256:
        raise ActionBudgetError("REAL_RELEASE_BINDING_MISMATCH")
    if contract_value is not None:
        if contract_value.get("status") == "REAL_EXECUTION_READY":
            _require_real_execution_contract(contract_value)
        elif input_binding_value is not None and admission_receipt_snapshot is not None:
            _require_admission_gated_real_action(
                contract_value,
                input_binding_value,
                admission_receipt_snapshot,
                contract_sha256=contract_sha256,
                input_binding_sha256=input_binding_sha256,
            )
        else:
            raise ActionBudgetIdentityDrift("REAL_RELEASE_REQUIRES_READY_CONTRACT_OR_VERIFIED_ADMISSION_GATE")
        if value.get("real_release_issued") is not True:
            raise ActionBudgetError("REAL_RELEASE_ISSUANCE_FLAG_MISSING")
    if not _is_sha(value.get("input_admission_receipt_sha256")):
        raise ActionBudgetError("REAL_RELEASE_INPUT_ADMISSION_RECEIPT_MISSING")
    action_scope = value.get("action_scope")
    if action_scope == "FIT_PREDICT":
        expected_actions = {"fit", "predict"}
        if value.get("sealed_status") != "PREDICTIONS_NOT_YET_SEALED" or any(
            name in value for name in ("candidate_artifacts", "prediction_seal", "prior_action_terminals")
        ):
            raise ActionBudgetError("FIT_PREDICT_RELEASE_MUST_PRECEDE_SEALED_ARTIFACTS")
    elif action_scope == "SEALED_TRUTH_EVALUATION":
        expected_actions = {"truth_decode"}
        if value.get("sealed_status") != "PREDICTIONS_SEALED_AWAITING_TRUTH_RELEASE":
            raise ActionBudgetError("TRUTH_RELEASE_SEALED_STATUS_MISMATCH")
        seal = value.get("prediction_seal")
        if (
            not isinstance(seal, Mapping)
            or not isinstance(seal.get("path"), str)
            or not Path(seal["path"]).is_absolute()
            or not _is_sha(seal.get("sha256"))
        ):
            raise ActionBudgetError("TRUTH_RELEASE_PREDICTION_SEAL_BINDING_MISSING")
        handoff = value.get("awaiting_truth_terminal")
        if (
            not isinstance(handoff, Mapping)
            or not isinstance(handoff.get("path"), str)
            or not Path(handoff["path"]).is_absolute()
            or not _is_sha(handoff.get("sha256"))
        ):
            raise ActionBudgetError("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_BINDING_MISSING")
        candidate_artifacts = value.get("candidate_artifacts")
        if not isinstance(candidate_artifacts, Mapping) or set(candidate_artifacts) != {
            "scoreable_prediction", "candidate_scores", "candidate_top3",
        }:
            raise ActionBudgetError("TRUTH_RELEASE_CANDIDATE_ARTIFACT_SET_MISMATCH")
        for name, item in candidate_artifacts.items():
            if (
                not isinstance(item, Mapping) or not isinstance(item.get("path"), str)
                or not Path(item["path"]).is_absolute() or not _is_sha(item.get("sha256"))
            ):
                raise ActionBudgetError(f"TRUTH_RELEASE_CANDIDATE_ARTIFACT_BINDING_INVALID:{name}")
        prior = value.get("prior_action_terminals")
        if not isinstance(prior, Mapping) or set(prior) != {"fit", "predict"} or any(
            not _is_sha(prior.get(name)) for name in ("fit", "predict")
        ):
            raise ActionBudgetError("TRUTH_RELEASE_PRIOR_ACTION_TERMINALS_MISSING")
    else:
        raise ActionBudgetError("REAL_RELEASE_ACTION_SCOPE_INVALID")
    sealed_status = value.get("sealed_status")
    if not isinstance(sealed_status, str) or not sealed_status:
        raise ActionBudgetError("REAL_RELEASE_SEALED_STATUS_MISSING")
    actions = value.get("actions")
    if not isinstance(actions, Mapping) or set(actions) != expected_actions:
        raise ActionBudgetError("REAL_RELEASE_ACTION_BUDGETS_MISSING")
    for action in sorted(expected_actions):
        item = actions.get(action)
        if not isinstance(item, Mapping):
            raise ActionBudgetError(f"REAL_RELEASE_{action.upper()}_BUDGET_MISSING")
        cap = item.get("max_calls")
        receipt_sha = item.get("official_registry_receipt_sha256")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap != ACTION_CAP:
            raise ActionBudgetError(f"REAL_RELEASE_{action.upper()}_CAP_MUST_EQUAL_ONE")
        if not _is_sha(receipt_sha):
            raise ActionBudgetError(f"REAL_RELEASE_{action.upper()}_DURABLE_RECEIPT_MISSING")
    return dict(value)


def _load_verified_r7_resume_record(
    binding: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    contract_sha256: str,
    input_binding_sha256: str,
    batch_root: Path,
) -> Mapping[str, Any] | None:
    """Verify the one authorized R7 pretarget continuation proof, if present."""
    resume = receipt.get("r7_resume")
    if resume is None:
        if binding.get("r7_resume") is not None:
            raise ActionBudgetIdentityDrift("R7_RESUME_BINDING_WITHOUT_ADMISSION_RECEIPT")
        return None
    if not isinstance(resume, Mapping) or binding.get("r7_resume") != dict(resume):
        raise ActionBudgetIdentityDrift("R7_RESUME_RECEIPT_BINDING_MISMATCH")
    auth_path_value = resume.get("authorization_path")
    auth_sha = resume.get("authorization_sha256")
    checkpoint_path_value = resume.get("checkpoint_path")
    checkpoint_sha = resume.get("checkpoint_sha256")
    if (
        not isinstance(auth_path_value, str) or not Path(auth_path_value).is_absolute()
        or not _is_sha(auth_sha)
        or not isinstance(checkpoint_path_value, str) or not Path(checkpoint_path_value).is_absolute()
        or not _is_sha(checkpoint_sha)
        or resume.get("physical_invocation_index") != 2
        or resume.get("logical_r7_action_debit_total") != 1
        or resume.get("additional_r7_action_debit") != 0
        or resume.get("resume_contract_sha256") != contract_sha256
        or resume.get("resume_input_binding_sha256") != input_binding_sha256
        or resume.get("resume_read_release_sha256") != receipt.get("read_release_sha256")
    ):
        raise ActionBudgetIdentityDrift("R7_RESUME_RECEIPT_IDENTITY_INCOMPLETE")
    auth_path = Path(auth_path_value)
    checkpoint_path = Path(checkpoint_path_value)
    control_root = batch_root / "receipts" / "r7_recovery_05" / "control_resume"
    run_root = batch_root / "receipts" / "r7_recovery_05" / "resume_invocation_02"
    try:
        auth_path.resolve(strict=True).relative_to(control_root.resolve())
        checkpoint_path.resolve(strict=True).relative_to(run_root.resolve())
    except (OSError, ValueError) as exc:
        raise ActionBudgetIdentityDrift("R7_RESUME_RECEIPT_PATH_OUTSIDE_FIXED_RECOVERY") from exc
    for path in (auth_path, checkpoint_path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ActionBudgetIdentityDrift("R7_RESUME_RECEIPT_CONTROL_PATH_INVALID")
    auth_payload = auth_path.read_bytes()
    if hashlib.sha256(auth_payload).hexdigest() != auth_sha:
        raise ActionBudgetIdentityDrift("R7_RESUME_AUTHORIZATION_SHA_MISMATCH")
    auth = dict(_parse_json_object(auth_payload, "R7_RESUME_AUTHORIZATION"))
    checkpoint_payload = checkpoint_path.read_bytes()
    if hashlib.sha256(checkpoint_payload).hexdigest() != checkpoint_sha:
        raise ActionBudgetIdentityDrift("R7_RESUME_CHECKPOINT_SHA_MISMATCH")
    checkpoint = dict(_parse_json_object(checkpoint_payload, "R7_RESUME_CHECKPOINT"))
    old_identity = auth.get("original_r7_identity")
    failure = auth.get("preserved_original_failure")
    controls = auth.get("resume_control_identity")
    if (
        auth.get("schema") != "BREADTH1_R7_PRETARGET_RESUME_AUTHORIZATION_V2"
        or auth.get("status") != "AUTHORIZED_PRETARGET_ENGINEERING_RESUMPTION"
        or not isinstance(old_identity, Mapping)
        or not isinstance(failure, Mapping)
        or not isinstance(controls, Mapping)
        or old_identity.get("route_id") != ROUTE_ID
        or old_identity.get("candidate_id") != CANDIDATE_ID
        or old_identity.get("grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
        or old_identity.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or old_identity.get("action_key") != PANEL_HEADER_RECOVERY_ACTION_KEY
        or old_identity.get("logical_action_cap") != 1
        or old_identity.get("logical_action_debit_consumed") != 1
        or failure.get("start_event_sha256") != resume.get("original_start_event_sha256")
        or failure.get("terminal_event_sha256") != resume.get("original_failed_terminal_event_sha256")
        or controls.get("contract_sha256") != contract_sha256
        or controls.get("pending_binding_sha256") != input_binding_sha256
        or controls.get("read_release_sha256") != receipt.get("read_release_sha256")
        or checkpoint.get("schema") != "BREADTH1_R7_RESUME_CHECKPOINT_V1"
        or checkpoint.get("status") != "PRETARGET_RESUME_AUTHENTICATED"
        or checkpoint.get("authorization_sha256") != auth_sha
        or checkpoint.get("r7_start_event_sha256") != resume.get("original_start_event_sha256")
        or checkpoint.get("r7_failed_terminal_event_sha256") != resume.get("original_failed_terminal_event_sha256")
        or checkpoint.get("physical_invocation_index") != 2
        or checkpoint.get("additional_r7_action_debit") != 0
        or any(checkpoint.get(name) != 0 for name in ("target_input_reads", "fit_calls", "predict_calls", "model_load_calls", "truth_decode_calls"))
    ):
        raise ActionBudgetIdentityDrift("R7_RESUME_AUTHORIZATION_OR_CHECKPOINT_CONTENT_MISMATCH")
    failure_path_value = failure.get("pipeline_terminal_path") if isinstance(failure, Mapping) else None
    if not isinstance(failure_path_value, str) or not Path(failure_path_value).is_absolute():
        raise ActionBudgetIdentityDrift("R7_RESUME_PRIOR_FAILURE_PATH_MISSING")
    failure_path = Path(failure_path_value)
    try:
        failure_path.resolve(strict=True).relative_to(
            (batch_root / "receipts" / "r7_one_shot_pipeline_recovery_01").resolve()
        )
    except (OSError, ValueError) as exc:
        raise ActionBudgetIdentityDrift("R7_RESUME_PRIOR_FAILURE_OUTSIDE_FIXED_RECOVERY") from exc
    if failure_path.is_symlink() or not failure_path.is_file() or failure_path.stat().st_size > 4 * 1024 * 1024:
        raise ActionBudgetIdentityDrift("R7_RESUME_PRIOR_FAILURE_PATH_INVALID")
    prior = dict(_parse_json_object(failure_path.read_bytes(), "R7_PRIOR_FAILURE_TERMINAL"))
    if (
        prior.get("schema") != "F5_BREADTH1_R7_ONE_PROCESS_TERMINAL_V1"
        or prior.get("status") != "NO_FIT"
        or prior.get("stage") != "input_admission"
        or prior.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or prior.get("error_type") != "AdmissionBlocked"
        or prior.get("error") != "INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH"
        or prior.get("input_read_observation") is not None
        or prior.get("action_debits") != {"admission": 1, "fit": 0, "predict": 0, "truth_decode": 0}
        or prior.get("real_fit_calls") != 0
        or prior.get("real_predict_calls") != 0
        or prior.get("real_truth_decode_calls") != 0
        or prior.get("real_model_load_calls") != 0
        or failure_path.stat().st_size != len(failure_path.read_bytes())
    ):
        raise ActionBudgetIdentityDrift("R7_RESUME_PRIOR_FAILURE_CONTENT_MISMATCH")
    return {"authorization": auth, "authorization_sha256": auth_sha,
            "checkpoint": checkpoint, "checkpoint_sha256": checkpoint_sha}


def _load_verified_admission_receipt(
    binding: Mapping[str, Any],
    contract: Mapping[str, Any],
    contract_sha256: str,
    input_binding_sha256: str,
    registry_adapter: Any,
    registry_events: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, int]:
    """Read and verify the actual admission receipt before trusting binding PASS."""

    path_value = binding.get("input_admission_receipt_path")
    expected_sha = binding.get("input_admission_receipt_sha256")
    pre_admission_binding_sha = binding.get("pre_admission_binding_sha256")
    read_release_sha = binding.get("input_admission_read_release_sha256")
    if (
        not isinstance(path_value, str) or not Path(path_value).is_absolute()
        or not _is_sha(expected_sha) or not _is_sha(pre_admission_binding_sha)
        or not _is_sha(read_release_sha)
    ):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_IDENTITY_INCOMPLETE")
    contract_path_value = getattr(registry_adapter, "contract_path", None)
    input_binding_path_value = getattr(registry_adapter, "input_binding_path", None)
    if not isinstance(contract_path_value, (str, Path)) or not isinstance(input_binding_path_value, (str, Path)):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_ADAPTER_PATHS_MISSING")
    contract_path = Path(contract_path_value).resolve()
    if contract_path.parent.name != "contracts":
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_CONTRACT_OUTSIDE_BATCH_CONTRACTS")
    batch_root = contract_path.parent.parent
    bindings_root = batch_root / "bindings"
    admission_receipts_root = batch_root / "receipts" / "input_admission"
    action_binding_path = Path(input_binding_path_value).resolve()
    try:
        action_binding_path.relative_to(bindings_root.resolve())
    except ValueError as exc:
        raise ActionBudgetIdentityDrift("REAL_ACTION_INPUT_BINDING_OUTSIDE_BATCH") from exc
    if action_binding_path.is_symlink() or not action_binding_path.is_file():
        raise ActionBudgetIdentityDrift("REAL_ACTION_INPUT_BINDING_PATH_INVALID")
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_PATH_INVALID")
    try:
        path.resolve(strict=True).relative_to(admission_receipts_root.resolve())
    except ValueError as exc:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_OUTSIDE_BATCH") from exc
    maximum = binding.get("input_admission_receipt_max_bytes")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 16 * 1024 * 1024:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_BYTE_CAP_INVALID")
    if path.stat().st_size > maximum:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_EXCEEDS_BOUND")
    with path.open("rb") as handle:
        payload = handle.read(maximum + 1)
    if len(payload) != path.stat().st_size or len(payload) > maximum:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_CHANGED_DURING_READ")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_SHA_MISMATCH")
    try:
        receipt = dict(_parse_json_object(payload, "INPUT_ADMISSION_RECEIPT"))
    except ActionBudgetIdentityDrift as exc:
        raise ActionBudgetIdentityDrift(str(exc)) from exc
    r7_resume_record = _load_verified_r7_resume_record(
        binding, receipt, contract_sha256=contract_sha256,
        input_binding_sha256=input_binding_sha256, batch_root=batch_root,
    )
    feature = contract.get("feature") if isinstance(contract.get("feature"), Mapping) else {}
    lineage_binding = binding.get("source_binding") if isinstance(binding.get("source_binding"), Mapping) else {}
    observed_frozen_input = lineage_binding.get("provenance_mode") == "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
    input_paths = contract.get("input_paths_and_sha256") if isinstance(contract.get("input_paths_and_sha256"), Mapping) else {}
    manifest_binding = input_paths.get("input_manifest") if isinstance(input_paths.get("input_manifest"), Mapping) else {}
    feature_binding = input_paths.get("feature_table") if isinstance(input_paths.get("feature_table"), Mapping) else {}
    data_audit = receipt.get("data_audit")
    producer_evidence = receipt.get("producer_evidence")
    actual_read = receipt.get("actual_read")
    read_budget = receipt.get("read_budget")
    read_authorization = receipt.get("read_authorization")
    expected_features = feature.get("full_features_artifact_sha256") or feature_binding.get("sha256")
    expected_manifest = feature.get("source_manifest_sha256") or manifest_binding.get("sha256")
    file_count = actual_read.get("file_count") if isinstance(actual_read, Mapping) else None
    total_bytes = actual_read.get("total_bytes") if isinstance(actual_read, Mapping) else None
    max_files = read_budget.get("max_files") if isinstance(read_budget, Mapping) else None
    max_total_bytes = read_budget.get("max_total_bytes") if isinstance(read_budget, Mapping) else None
    read_records = actual_read.get("files") if isinstance(actual_read, Mapping) else None
    read_records_valid = isinstance(read_records, Mapping) and file_count == len(read_records)
    read_record_bytes = 0
    resolved_read_paths: set[Path] = set()
    if isinstance(read_records, Mapping):
        for record in read_records.values():
            if (
                not isinstance(record, Mapping)
                or not _is_sha(record.get("sha256"))
                or not isinstance(record.get("path"), str)
                or not Path(record["path"]).is_absolute()
            ):
                raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_FILE_RECORD_INVALID")
            count_bytes = record.get("bytes")
            if isinstance(count_bytes, bool) or not isinstance(count_bytes, int) or count_bytes < 1:
                raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_FILE_BYTE_COUNT_INVALID")
            read_record_bytes += count_bytes
            resolved_path = Path(record["path"]).resolve()
            if resolved_path in resolved_read_paths:
                raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_DUPLICATE_PHYSICAL_FILE")
            resolved_read_paths.add(resolved_path)
    max_file_bytes = read_budget.get("max_file_bytes") if isinstance(read_budget, Mapping) else None
    release_record = read_records.get("input_admission_read_release") if isinstance(read_records, Mapping) else None
    binding_record = read_records.get("input_binding") if isinstance(read_records, Mapping) else None
    read_release_path = Path(str(read_authorization.get("path", ""))) if isinstance(read_authorization, Mapping) else Path()
    try:
        read_release_path.resolve(strict=True).relative_to(bindings_root.resolve())
        read_release_path_valid = not read_release_path.is_symlink()
    except (OSError, ValueError):
        read_release_path_valid = False
    pre_binding_path_value = binding.get("pre_admission_binding_path")
    pre_binding_path = Path(pre_binding_path_value) if isinstance(pre_binding_path_value, str) else Path()
    try:
        pre_binding_path.resolve(strict=True).relative_to(bindings_root.resolve())
        pre_binding_path_valid = (
            pre_binding_path.is_absolute()
            and not pre_binding_path.is_symlink()
            and pre_binding_path.resolve() != action_binding_path
            and pre_binding_path.is_file()
        )
    except (OSError, ValueError):
        pre_binding_path_valid = False
    parent_code_count = receipt.get("parent_code_count")
    parent_session_count = receipt.get("parent_session_count")
    parent_grid_rows = receipt.get("parent_grid_rows")
    required_sessions = receipt.get("required_sessions")
    panel_records = {
        name: record for name, record in read_records.items()
        if isinstance(name, str) and name.startswith("panel:")
    } if isinstance(read_records, Mapping) else {}
    read_record_names = set(read_records) if isinstance(read_records, Mapping) else set()
    required_read_names = (
        {
            "input_admission_read_release", "input_binding", "input_manifest", "train_keys",
            "evaluation_calendar", "train_x64", "train_y", "eval_x64", "eval_meta",
            "pretruth_scores", "parent_calendar",
        }
        if observed_frozen_input else {
            "input_admission_read_release", "input_binding", "input_manifest", "train_keys",
            "evaluation_calendar", "producer_source", "producer_output_run_receipt",
            "producer_environment_receipt", "full_grid_flag_join_receipt", "parent_calendar",
        }
    )
    expected_read_names = required_read_names | set(panel_records)
    audit_fields = (
        (("full_grid_complete", True), ("duplicate_keys", 0),
         ("feature_flag_value_conflicts", 0), ("empty_required_denominator_sessions", []),
         ("ret_nan_cause", "NOT_INFERRED"), ("blockers", []))
        if observed_frozen_input else
        (("full_grid_complete", True), ("duplicate_keys", 0),
         ("feature1_nan_unbound_warmup_keys", []), ("unexpected_warmup_keys", []),
         ("empty_required_denominator_sessions", []), ("blockers", []))
    )
    audit_complete = (
        isinstance(data_audit, Mapping)
        and all(data_audit.get(field) == expected for field, expected in audit_fields)
        and isinstance(parent_code_count, int) and not isinstance(parent_code_count, bool) and parent_code_count > 0
        and isinstance(parent_session_count, int) and not isinstance(parent_session_count, bool) and parent_session_count > 0
        and isinstance(parent_grid_rows, int) and not isinstance(parent_grid_rows, bool)
        and parent_grid_rows == parent_code_count * parent_session_count
        and isinstance(required_sessions, list) and bool(required_sessions)
        and all(isinstance(value, int) and not isinstance(value, bool) for value in required_sessions)
        and len(required_sessions) == len(set(required_sessions))
        and data_audit.get("parent_rows") == parent_grid_rows
        and data_audit.get("code_count") == parent_code_count
        and data_audit.get("session_count") == parent_session_count
        and data_audit.get("required_session_count") == len(required_sessions)
        and len(panel_records) == parent_code_count
    )
    breadth_by_session = receipt.get("breadth_by_session")
    breadth_complete = (
        isinstance(breadth_by_session, list)
        and isinstance(required_sessions, list)
        and len(breadth_by_session) == len(required_sessions)
        and all(
            isinstance(row, Mapping)
            and row.get("session_id") == required_sessions[index]
            and isinstance(row.get("positive_finite_count"), int)
            and not isinstance(row.get("positive_finite_count"), bool)
            and isinstance(row.get("finite_return_count"), int)
            and not isinstance(row.get("finite_return_count"), bool)
            and 0 <= row["positive_finite_count"] <= row["finite_return_count"]
            and row["finite_return_count"] > 0
            for index, row in enumerate(breadth_by_session)
        )
    )
    if (
        not isinstance(read_authorization, Mapping)
        or read_authorization.get("counted_inside_input_file_budget") is not True
        or not read_release_path_valid
        or not pre_binding_path_valid
        or binding.get("pre_admission_binding_sha256") != pre_admission_binding_sha
        or not audit_complete
        or not breadth_complete
        or read_record_names != expected_read_names
        or file_count != len(expected_read_names)
        or isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 1
        or not isinstance(release_record, Mapping) or not isinstance(binding_record, Mapping)
        or release_record.get("sha256") != read_release_sha
        or release_record.get("path") != read_authorization.get("path")
        or release_record.get("bytes") != read_authorization.get("bytes")
        or binding_record.get("sha256") != pre_admission_binding_sha
        or Path(str(binding_record.get("path", ""))).resolve() != pre_binding_path.resolve()
        or not isinstance(read_records.get("input_manifest"), Mapping)
        or read_records["input_manifest"].get("sha256") != expected_manifest
        or any(
            not isinstance(record, Mapping)
            or isinstance(record.get("bytes"), bool)
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] > max_file_bytes
            for record in read_records.values()
        )
    ):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_READ_LEDGER_BUDGET_OR_IDENTITY_MISMATCH")
    lineage = binding.get("source_binding")
    if not isinstance(lineage, Mapping):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_PROVENANCE_BINDING_MISSING")
    if observed_frozen_input:
        if (
            lineage.get("status") != "LINEAGE_UNAVAILABLE"
            or lineage.get("provenance_mode") != "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
            or receipt.get("provenance_mode") != "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
            or receipt.get("historical_producer_status") != "LINEAGE_UNAVAILABLE"
            or producer_evidence is not None
        ):
            raise ActionBudgetIdentityDrift("FROZEN_OBSERVED_LINEAGE_LIMITATION_MUST_REMAIN_EXPLICIT")
        if set(read_records) != expected_read_names or any(
            not isinstance(read_records.get(name), Mapping)
            for name in ("train_x64", "train_y", "eval_x64", "eval_meta", "pretruth_scores")
        ):
            raise ActionBudgetIdentityDrift("FROZEN_OBSERVED_REQUIRED_INPUT_IDENTITY_READS_MISSING")
        frozen_artifacts = binding.get("frozen_artifacts")
        if not isinstance(frozen_artifacts, Mapping):
            raise ActionBudgetIdentityDrift("FROZEN_OBSERVED_ARTIFACT_BINDING_MISSING")
        for name, descriptor in frozen_artifacts.items():
            record = read_records.get(name)
            if (
                not isinstance(descriptor, Mapping) or not isinstance(record, Mapping)
                or record.get("sha256") != descriptor.get("sha256")
                or str(Path(record.get("path", "")).resolve()) != str(Path(descriptor.get("path", "")).resolve())
            ):
                raise ActionBudgetIdentityDrift(f"FROZEN_OBSERVED_ARTIFACT_RECEIPT_MISMATCH:{name}")
    else:
        if lineage.get("status") != "PASS":
            raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_LINEAGE_BINDING_NOT_PASS")
        producer_file_hashes = {
            "producer_source": lineage.get("producer_sha256"),
            "producer_output_run_receipt": lineage.get("output_run_receipt_sha256"),
            "producer_environment_receipt": lineage.get("environment_receipt_sha256"),
            "full_grid_flag_join_receipt": lineage.get("full_grid_flag_join_receipt_sha256"),
        }
        if any(
            not isinstance(read_records.get(name), Mapping)
            or read_records[name].get("sha256") != digest
            or not _is_sha(digest)
            for name, digest in producer_file_hashes.items()
        ):
            raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_EVIDENCE_FILE_BINDING_MISMATCH")
        evidence_source = producer_evidence.get("source") if isinstance(producer_evidence, Mapping) else None
        evidence_output = producer_evidence.get("output_run_receipt") if isinstance(producer_evidence, Mapping) else None
        evidence_environment = producer_evidence.get("environment_receipt") if isinstance(producer_evidence, Mapping) else None
        evidence_grid = producer_evidence.get("full_grid_flag_join_receipt") if isinstance(producer_evidence, Mapping) else None
        if any(not isinstance(item, Mapping) for item in (evidence_source, evidence_output, evidence_environment, evidence_grid)):
            raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_PRODUCER_EVIDENCE_DETAILS_MISSING")
        if (
            evidence_source.get("sha256") != lineage.get("producer_sha256")
            or read_records["producer_source"].get("bytes") != evidence_source.get("bytes")
            or evidence_source.get("immutable_reference") != lineage.get("immutable_reference")
            or evidence_source.get("relative_source_path") != lineage.get("relative_source_path")
            or evidence_output.get("sha256") != lineage.get("output_run_receipt_sha256")
            or read_records["producer_output_run_receipt"].get("bytes") != evidence_output.get("bytes")
            or evidence_environment.get("sha256") != lineage.get("environment_receipt_sha256")
            or read_records["producer_environment_receipt"].get("bytes") != evidence_environment.get("bytes")
            or evidence_grid.get("sha256") != lineage.get("full_grid_flag_join_receipt_sha256")
            or read_records["full_grid_flag_join_receipt"].get("bytes") != evidence_grid.get("bytes")
            or producer_evidence.get("pandas_version") != lineage.get("pandas_version")
            or producer_evidence.get("fill_method") != lineage.get("fill_method")
            or producer_evidence.get("warmup_nan_keys") != lineage.get("verified_warmup_nan_keys")
        ):
            raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_LINEAGE_DETAIL_BINDING_MISMATCH")
    registry_execution_id = receipt.get("registry_execution_id")
    registry_start_sha = receipt.get("registry_start_event_sha256")
    if registry_execution_id == RECOVERY_EXECUTION_ID:
        expected_action_key = RECOVERY_ACTION_KEY
        expected_grant_id = RECOVERY_GRANT_ID
        expected_failed_execution_id = FAILED_ADMISSION_EXECUTION_ID
        expected_failed_start_sha = FAILED_ADMISSION_START_SHA256
        expected_failed_terminal_sha = FAILED_ADMISSION_TERMINAL_SHA256
    elif registry_execution_id == KEY_ALIGNMENT_EXECUTION_ID:
        expected_action_key = KEY_ALIGNMENT_ACTION_KEY
        expected_grant_id = KEY_ALIGNMENT_RECOVERY_GRANT_ID
        expected_failed_execution_id = KEY_ALIGNMENT_FAILED_EXECUTION_ID
        expected_failed_start_sha = KEY_ALIGNMENT_FAILED_START_SHA256
        expected_failed_terminal_sha = KEY_ALIGNMENT_FAILED_TERMINAL_SHA256
    elif registry_execution_id == TRAIN_LABEL_RECOVERY_EXECUTION_ID:
        expected_action_key = TRAIN_LABEL_RECOVERY_ACTION_KEY
        expected_grant_id = TRAIN_LABEL_RECOVERY_GRANT_ID
        expected_failed_execution_id = TRAIN_LABEL_FAILED_EXECUTION_ID
        expected_failed_start_sha = TRAIN_LABEL_FAILED_START_SHA256
        expected_failed_terminal_sha = TRAIN_LABEL_FAILED_TERMINAL_SHA256
    elif registry_execution_id == PANEL_HEADER_RECOVERY_EXECUTION_ID:
        expected_action_key = PANEL_HEADER_RECOVERY_ACTION_KEY
        expected_grant_id = PANEL_HEADER_RECOVERY_GRANT_ID
        expected_failed_execution_id = PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
        expected_failed_start_sha = PANEL_HEADER_R6_FAILED_START_SHA256
        expected_failed_terminal_sha = PANEL_HEADER_R6_FAILED_TERMINAL_SHA256
    else:
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_REGISTRY_EXECUTION_ID_UNRECOGNIZED")
    admission_contract_sha = receipt.get("contract_sha256")
    admission_binding_sha = receipt.get("pre_admission_binding_sha256")
    if (
        not isinstance(registry_execution_id, str)
        or not _is_sha(registry_start_sha)
        or not _is_sha(admission_contract_sha)
        or not _is_sha(admission_binding_sha)
        or admission_binding_sha != pre_admission_binding_sha
        or registry_adapter is None
        or not callable(getattr(registry_adapter, "list_events", None))
    ):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_REGISTRY_ADAPTER_INVALID")
    if registry_events is None:
        source_events = registry_adapter.list_events(EXPERIMENT_ID)
    else:
        # ``claim`` supplies the already validated registry snapshot while it
        # owns the registry lock. Reopening the adapter lock through
        # ``list_events`` here would deadlock on a second file descriptor.
        source_events = []
        for event in registry_events:
            if (
                event.get("experiment_id") != EXPERIMENT_ID
                or event.get("event_type") not in {"RUN_STARTED", "TERMINAL"}
            ):
                continue
            item = dict(event)
            metrics = event.get("deterministic_metrics")
            if isinstance(metrics, Mapping):
                for field in (
                    "execution_kind", "planned_real_fit_count", "real_fit_budget_debit",
                    "real_fit_returned_count", "fit_call_entered",
                ):
                    if field in metrics:
                        item[field] = metrics[field]
            identity = event.get("input_identity")
            if "input_binding_sha256" not in item and isinstance(identity, Mapping):
                if identity.get("input_binding_sha256"):
                    item["input_binding_sha256"] = identity["input_binding_sha256"]
            if event.get("event_type") == "TERMINAL":
                item["terminal_status"] = event.get("decision")
            source_events.append(item)
    lifecycle = [event for event in source_events if event.get("execution_id") == registry_execution_id]
    starts = [event for event in lifecycle if event.get("event_type") == "RUN_STARTED"]
    terminals = [event for event in lifecycle if event.get("event_type") == "TERMINAL"]
    start_metrics = starts[0].get("deterministic_metrics") if len(starts) == 1 else None
    terminal_metrics = terminals[0].get("deterministic_metrics") if len(terminals) == 1 else None
    resume_auth = (r7_resume_record or {}).get("authorization", {})
    resume_old_identity = resume_auth.get("original_r7_identity") if isinstance(resume_auth, Mapping) else None
    resume_failure = resume_auth.get("preserved_original_failure") if isinstance(resume_auth, Mapping) else None
    if (
        len(lifecycle) != 2 or len(starts) != 1 or len(terminals) != 1
        or starts[0].get("event_sha256") != registry_start_sha
        or starts[0].get("route_id") != ROUTE_ID
        or starts[0].get("execution_id") != registry_execution_id
        or starts[0].get("decision") != "RUNNING"
        or starts[0].get("contract_sha256") != (
            resume_old_identity.get("contract_sha256") if r7_resume_record else admission_contract_sha
        )
        or starts[0].get("input_binding_sha256") != (
            resume_old_identity.get("input_binding_sha256") if r7_resume_record else pre_admission_binding_sha
        )
        or starts[0].get("budget_action") != RECOVERY_ACTION
        or starts[0].get("budget_action_key") != expected_action_key
        or not isinstance(start_metrics, Mapping)
        or start_metrics.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY"
        or start_metrics.get("real_fit_budget_debit") != 0
        or start_metrics.get("budget_release_sha256") != (
            resume_old_identity.get("read_release_sha256") if r7_resume_record else read_release_sha
        )
        or start_metrics.get("recovery_grant_id") != expected_grant_id
        or start_metrics.get("linked_failed_execution_id") != expected_failed_execution_id
        or start_metrics.get("linked_failed_start_event_sha256") != expected_failed_start_sha
        or start_metrics.get("linked_failed_terminal_event_sha256") != expected_failed_terminal_sha
        or (
            registry_execution_id == PANEL_HEADER_RECOVERY_EXECUTION_ID
            and (
                receipt.get("linked_failed_execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
                or receipt.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or receipt.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
                or receipt.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or receipt.get("linked_r4_ancestor_failure_execution_id") != PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
                or receipt.get("linked_r4_ancestor_failure_receipt_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
                or receipt.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
                or receipt.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
                or start_metrics.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or start_metrics.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
                or start_metrics.get("linked_r5_ancestor_start_event_sha256") != PANEL_HEADER_R5_FAILED_START_SHA256
                or start_metrics.get("linked_r5_ancestor_terminal_event_sha256") != PANEL_HEADER_R5_FAILED_TERMINAL_SHA256
                or start_metrics.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or start_metrics.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
                or start_metrics.get("linked_r3_parent_header_failure_start_event_sha256") != PANEL_HEADER_FAILED_START_SHA256
                or start_metrics.get("linked_r3_parent_header_failure_terminal_event_sha256") != PANEL_HEADER_FAILED_TERMINAL_SHA256
                or start_metrics.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
                or start_metrics.get("panel_header_diagnostic_receipt_sha256") != PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256
                or start_metrics.get("panel_header_diagnostic_start_event_sha256") != PANEL_HEADER_DIAGNOSTIC_START_SHA256
                or start_metrics.get("panel_header_diagnostic_terminal_event_sha256") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
                or start_metrics.get("train_label_diagnostic_correction_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256
                or start_metrics.get("prior_panel_header_runtime_failure_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
                or start_metrics.get("prior_panel_header_r5_failure_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or start_metrics.get("prior_panel_header_r6_failure_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or start_metrics.get("controller_reauthorization_source") != "explicit parent follow-up authorizing one new linked admission recovery after the R6 control-validation NameError before frozen target data reads"
                or start_metrics.get("controller_reauthorization_task_id") != "546019360"
            )
        )
        or terminals[0].get("route_id") != ROUTE_ID
        or terminals[0].get("execution_id") != registry_execution_id
        or (
            terminals[0].get("started_event_sha256") is not None
            and terminals[0].get("started_event_sha256") != starts[0].get("event_sha256")
        )
        or terminals[0].get("contract_sha256") != (
            resume_old_identity.get("contract_sha256") if r7_resume_record else admission_contract_sha
        )
        or terminals[0].get("input_binding_sha256") != (
            resume_old_identity.get("input_binding_sha256") if r7_resume_record else pre_admission_binding_sha
        )
        or terminals[0].get("budget_action") != RECOVERY_ACTION
        or terminals[0].get("budget_action_key") != expected_action_key
        or terminals[0].get("decision") != (
            "CANNOT_CONFIRM_ACTION_FAILED" if r7_resume_record else "ENGINEERING_CANARY_ONLY"
        )
        or not isinstance(terminal_metrics, Mapping)
        or terminal_metrics.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY"
        or terminal_metrics.get("real_fit_budget_debit") != 0
        or terminal_metrics.get("fit_call_entered") is not False
        or terminal_metrics.get("real_fit_returned_count") != 0
        or terminal_metrics.get("recovery_grant_id") != expected_grant_id
        or terminal_metrics.get("linked_failed_execution_id") != expected_failed_execution_id
        or terminal_metrics.get("linked_failed_start_event_sha256") != expected_failed_start_sha
        or terminal_metrics.get("linked_failed_terminal_event_sha256") != expected_failed_terminal_sha
        or (r7_resume_record is not None and (
            not isinstance(resume_failure, Mapping)
            or terminals[0].get("event_sha256") != resume_failure.get("terminal_event_sha256")
            or terminals[0].get("registry_event_id") != resume_failure.get("terminal_event_id")
            or terminals[0].get("stop_reason") != "AdmissionBlocked"
            or resume_failure.get("error") != "INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH"
        ))
        or (
            registry_execution_id == PANEL_HEADER_RECOVERY_EXECUTION_ID
            and (
                receipt.get("linked_failed_execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
                or receipt.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or receipt.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
                or receipt.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or receipt.get("linked_r4_ancestor_failure_execution_id") != PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
                or receipt.get("linked_r4_ancestor_failure_receipt_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
                or receipt.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
                or receipt.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("linked_failed_receipt_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("linked_r5_ancestor_execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
                or terminal_metrics.get("linked_r5_ancestor_start_event_sha256") != PANEL_HEADER_R5_FAILED_START_SHA256
                or terminal_metrics.get("linked_r5_ancestor_terminal_event_sha256") != PANEL_HEADER_R5_FAILED_TERMINAL_SHA256
                or terminal_metrics.get("linked_r5_ancestor_receipt_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
                or terminal_metrics.get("linked_r3_parent_header_failure_start_event_sha256") != PANEL_HEADER_FAILED_START_SHA256
                or terminal_metrics.get("linked_r3_parent_header_failure_terminal_event_sha256") != PANEL_HEADER_FAILED_TERMINAL_SHA256
                or terminal_metrics.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("panel_header_diagnostic_receipt_sha256") != PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256
                or terminal_metrics.get("panel_header_diagnostic_start_event_sha256") != PANEL_HEADER_DIAGNOSTIC_START_SHA256
                or terminal_metrics.get("panel_header_diagnostic_terminal_event_sha256") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
                or terminal_metrics.get("train_label_diagnostic_correction_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256
                or terminal_metrics.get("prior_panel_header_runtime_failure_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
                or terminal_metrics.get("prior_panel_header_r5_failure_sha256") != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("prior_panel_header_r6_failure_sha256") != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256
                or terminal_metrics.get("controller_reauthorization_source") != "explicit parent follow-up authorizing one new linked admission recovery after the R6 control-validation NameError before frozen target data reads"
                or terminal_metrics.get("controller_reauthorization_task_id") != "546019360"
            )
        )
        or (
            registry_execution_id == PANEL_HEADER_RECOVERY_EXECUTION_ID
            and (
                not _valid_prior_train_label_diagnostic(receipt.get("prior_train_label_diagnostic"))
                or not _valid_prior_panel_header_diagnostic(receipt.get("prior_panel_header_diagnostic"))
                or not _valid_prior_panel_header_runtime_failure(receipt.get("prior_panel_header_runtime_failure"))
                or not _valid_prior_panel_header_r5_failure(receipt.get("prior_panel_header_r5_failure"))
                or not _valid_prior_panel_header_r6_failure(receipt.get("prior_panel_header_r6_failure"))
            )
        )
    ):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_OFFICIAL_REGISTRY_LIFECYCLE_MISMATCH")
    terminal_paths = terminals[0].get("artifact_path")
    terminal_shas = terminals[0].get("artifact_sha256")
    if not isinstance(terminal_paths, list) or not isinstance(terminal_shas, list) or len(terminal_paths) != len(terminal_shas):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_TERMINAL_ARTIFACT_BINDING_MISSING")
    if r7_resume_record is None:
        artifact_identities: dict[str, list[str]] = {}
        for artifact_path, artifact_sha in zip(terminal_paths, terminal_shas):
            if isinstance(artifact_path, str) and _is_sha(artifact_sha):
                artifact_identities.setdefault(str(Path(artifact_path).resolve()), []).append(artifact_sha)
        expected_terminal_artifacts = {
            str(path.resolve()): expected_sha,
            str(action_binding_path.resolve()): input_binding_sha256,
            str(read_release_path.resolve()): read_release_sha,
            str(PANEL_HEADER_R5_FAILED_RECEIPT_PATH.resolve()): PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
            str(PANEL_HEADER_R6_FAILED_RECEIPT_PATH.resolve()): PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
            str(PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_PATH.resolve()): PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
            str(PANEL_HEADER_FAILED_RECEIPT_PATH.resolve()): PANEL_HEADER_FAILED_RECEIPT_SHA256,
            str(PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH.resolve()): PANEL_HEADER_FAILED_REGISTRY_RECEIPT_SHA256,
            str(PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH.resolve()): PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
            str(TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH.resolve()): TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
        }
        if not observed_frozen_input:
            for evidence_name in (
                "producer_source", "producer_output_run_receipt",
                "producer_environment_receipt", "full_grid_flag_join_receipt",
            ):
                evidence_record = read_records[evidence_name]
                expected_terminal_artifacts[str(Path(evidence_record["path"]).resolve())] = evidence_record["sha256"]
        if any(artifact_identities.get(artifact_path) != [digest] for artifact_path, digest in expected_terminal_artifacts.items()):
            raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_TERMINAL_RECEIPT_RELEASE_OR_BINDING_NOT_PINNED")
    if (
        receipt.get("schema") != "F5_BREADTH1_INPUT_ADMISSION_RECEIPT_V1"
        or receipt.get("status") != "PASS"
        or receipt.get("decision") != "INPUT_ADMISSION_PASS"
        or receipt.get("real_input_accessed") is not True
        or receipt.get("contract_sha256") != contract_sha256
        or receipt.get("input_binding_sha256") != pre_admission_binding_sha
        or receipt.get("pre_admission_binding_sha256") != pre_admission_binding_sha
        or receipt.get("read_release_sha256") != read_release_sha
        or receipt.get("receipt_path") != str(path.resolve())
        or receipt.get("input_manifest_sha256") != expected_manifest
        or receipt.get("features_sha256") != expected_features
        or not audit_complete or not breadth_complete
        or (not observed_frozen_input and (not isinstance(producer_evidence, Mapping) or producer_evidence.get("status") != "PASS_VERIFIED_SNAPSHOT_CHAIN"))
        or not isinstance(actual_read, Mapping) or not isinstance(read_budget, Mapping)
        or not isinstance(read_authorization, Mapping) or read_authorization.get("sha256") != read_release_sha
        or isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 1
        or isinstance(total_bytes, bool) or not isinstance(total_bytes, int) or total_bytes < 1
        or isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1
        or isinstance(max_total_bytes, bool) or not isinstance(max_total_bytes, int) or max_total_bytes < 1
        or not read_records_valid
        or total_bytes != read_record_bytes
        or file_count > max_files
        or total_bytes > max_total_bytes
        or any(receipt.get(field) is not expected for field, expected in (
            ("research_only", True), ("production_allowed", False),
            ("buy_gate_updated", False), ("orders_sent", False),
        ))
        or any(receipt.get(field) != 0 for field in ("real_fit_calls", "real_predict_calls", "real_truth_decode_calls"))
    ):
        raise ActionBudgetIdentityDrift("REAL_INPUT_ADMISSION_RECEIPT_CONTENT_IDENTITY_MISMATCH")
    return receipt, actual, len(payload)


def _verify_prediction_seal_snapshot(
    release: Mapping[str, Any],
    *,
    contract_sha256: str,
    input_binding_sha256: str,
) -> dict[str, Any]:
    seal_binding = release.get("prediction_seal")
    if not isinstance(seal_binding, Mapping):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_BINDING_MISSING")
    seal_path_value = seal_binding.get("path")
    expected_sha = seal_binding.get("sha256")
    if not isinstance(seal_path_value, str) or not Path(seal_path_value).is_absolute() or not _is_sha(expected_sha):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_BINDING_INVALID")
    path = Path(seal_path_value)
    if path.is_symlink() or not path.is_file():
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_PATH_INVALID")
    try:
        path.resolve(strict=True).relative_to(BATCH_ROOT.resolve())
    except ValueError as exc:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_OUTSIDE_BATCH") from exc
    maximum = 4 * 1024 * 1024
    if path.stat().st_size > maximum:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_EXCEEDS_BOUND")
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_SHA_MISMATCH")
    seal = dict(_parse_json_object(payload, "PREDICTION_SEAL"))
    if (
        seal.get("schema") != "F5_BREADTH1_REAL_PREDICTION_SEAL_V1"
        or seal.get("status") != "PREDICTIONS_SEALED_AWAITING_TRUTH_RELEASE"
        or seal.get("contract_sha256") != contract_sha256
        or seal.get("input_binding_sha256") != input_binding_sha256
    ):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_PREDICTION_SEAL_CONTENT_MISMATCH")
    handoff = release.get("awaiting_truth_terminal")
    if not isinstance(handoff, Mapping):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_MISSING")
    handoff_path = Path(str(handoff.get("path", "")))
    handoff_sha = handoff.get("sha256")
    if not handoff_path.is_absolute() or not _is_sha(handoff_sha) or handoff_path.is_symlink() or not handoff_path.is_file():
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_INVALID")
    try:
        handoff_path.resolve(strict=True).relative_to(BATCH_ROOT.resolve())
    except ValueError as exc:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_OUTSIDE_BATCH") from exc
    if handoff_path.stat().st_size > 1024 * 1024:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_EXCEEDS_BOUND")
    handoff_payload = handoff_path.read_bytes()
    if hashlib.sha256(handoff_payload).hexdigest() != handoff_sha:
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_HANDOFF_SHA_MISMATCH")
    terminal = dict(_parse_json_object(handoff_payload, "AWAITING_TRUTH_TERMINAL"))
    if (
        terminal.get("schema") != "F5_BREADTH1_REAL_TERMINAL_RECEIPT_V1"
        or terminal.get("status") != "AWAITING_TRUTH_RELEASE"
        or terminal.get("decision") != "AWAITING_TRUTH_RELEASE"
        or terminal.get("prediction_seal_path") != str(path.resolve())
        or terminal.get("prediction_seal_sha256") != actual
        or terminal.get("real_truth_decode_calls") != 0
        or terminal.get("prior_action_terminals") != seal.get("prior_action_terminals")
        or release.get("prior_action_terminals") != seal.get("prior_action_terminals")
    ):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_AWAITING_TRUTH_TERMINAL_CONTENT_MISMATCH")
    sealed_artifacts = seal.get("candidate_artifacts")
    released_artifacts = release.get("candidate_artifacts")
    if not isinstance(sealed_artifacts, Mapping) or not isinstance(released_artifacts, Mapping):
        raise ActionBudgetIdentityDrift("TRUTH_RELEASE_CANDIDATE_ARTIFACTS_MISSING")
    for name in ("scoreable_prediction", "candidate_scores", "candidate_top3"):
        sealed = sealed_artifacts.get(name)
        released = released_artifacts.get(name)
        if (
            not isinstance(sealed, Mapping) or not isinstance(released, Mapping)
            or not isinstance(sealed.get("path"), str) or not isinstance(released.get("path"), str)
            or not _is_sha(sealed.get("sha256"))
            or sealed.get("sha256") != released.get("sha256")
            or Path(sealed["path"]).resolve() != Path(released["path"]).resolve()
        ):
            raise ActionBudgetIdentityDrift(f"TRUTH_RELEASE_SEAL_ARTIFACT_MISMATCH:{name}")
        artifact_path = Path(sealed["path"])
        try:
            artifact_path.resolve(strict=True).relative_to(BATCH_ROOT.resolve())
        except (OSError, ValueError) as exc:
            raise ActionBudgetIdentityDrift(f"TRUTH_RELEASE_SEAL_ARTIFACT_OUTSIDE_BATCH:{name}") from exc
        artifact_bytes = sealed.get("bytes")
        if (
            artifact_path.is_symlink()
            or not artifact_path.is_file()
            or isinstance(artifact_bytes, bool)
            or not isinstance(artifact_bytes, int)
            or artifact_bytes < 1
            or artifact_path.stat().st_size != artifact_bytes
            or sha256_file(artifact_path) != sealed.get("sha256")
        ):
            raise ActionBudgetIdentityDrift(f"TRUTH_RELEASE_SEAL_ARTIFACT_BYTES_CHANGED:{name}")
    return seal


class BREADTH1OfficialActionAdapter:
    """Atomically debit one fixed action key from the official append-only registry.

    The action key is ``route_id:candidate_id:action`` and does not include the
    input binding or execution ID.  Therefore neither a new process, a changed
    binding, nor a new caller-supplied ID can reset a consumed action.  The
    official registry itself is authoritative; this adapter creates no quota
    sidecar or alternate registry.
    """

    def __init__(
        self,
        official_adapter: Any,
        *,
        contract_sha256: str,
        input_binding_sha256: str,
        synthetic: bool = False,
        admission_only: bool = False,
    ) -> None:
        if type(synthetic) is not bool:
            raise ActionBudgetError("synthetic must be an explicit bool")
        if type(admission_only) is not bool or admission_only and synthetic:
            raise ActionBudgetError("admission_only must be an explicit real-only bool")
        self.official = official_adapter
        self.contract_sha256 = _require_sha(contract_sha256, "contract_sha256")
        self.input_binding_sha256 = _require_sha(input_binding_sha256, "input_binding_sha256")
        self.synthetic = synthetic
        self.admission_only = admission_only
        self._validate_bound_adapter()

    @property
    def input_binding_value(self) -> Mapping[str, Any]:
        """Return a freshly verified binding snapshot; never reuse constructor state."""
        _, binding, _ = self._read_contract_binding_snapshot()
        return dict(binding)

    @property
    def registry_path(self) -> Path:
        return Path(self.official.registry_path).resolve()

    def execute_once(
        self,
        action: str,
        callback: Callable[[], Any] | None = None,
        *,
        verified_context_callback: Callable[[VerifiedActionContext], Any] | None = None,
        release: VerifiedActionRelease | None = None,
        fit_call_entered: Callable[[], bool] | None = None,
        terminal_artifact_paths: Sequence[Path] = (),
    ) -> Any:
        """Claim durably, then open/call exactly once; a failed action stays spent."""

        if not callable(callback) and not callable(verified_context_callback):
            raise ActionBudgetError("action callback must be callable")
        claim = self.claim(action, release=release)
        callback_entered = False
        try:
            context = self._verify_action_boundary(claim, release)
            callback_entered = True
            if verified_context_callback is not None:
                if context is None:
                    raise ActionBudgetError("VERIFIED_CONTEXT_CALLBACK_REQUIRES_REAL_ACTION_CONTEXT")
                result = verified_context_callback(context)
            else:
                assert callback is not None
                result = callback()
        except BaseException as exc:
            entered_fit = bool(fit_call_entered()) if fit_call_entered is not None else claim.action == "fit" and callback_entered
            try:
                self.terminalize(
                    claim,
                    succeeded=False,
                    callback_entered=callback_entered,
                    fit_call_entered=entered_fit,
                    error_type=type(exc).__name__,
                    terminal_artifact_paths=terminal_artifact_paths,
                )
            except BaseException as terminal_error:
                raise ActionBudgetError(
                    f"ACTION_FAILED_AND_OFFICIAL_TERMINALIZATION_FAILED:{type(terminal_error).__name__}"
                ) from exc
            if not callback_entered and isinstance(exc, ActionBudgetError):
                raise ActionBudgetIdentityDrift(f"ACTION_BOUNDARY_REVALIDATION_FAILED:{type(exc).__name__}") from exc
            raise
        entered_fit = bool(fit_call_entered()) if fit_call_entered is not None else claim.action == "fit" and callback_entered
        self.terminalize(
            claim,
            succeeded=True,
            callback_entered=callback_entered,
            fit_call_entered=entered_fit,
            terminal_artifact_paths=terminal_artifact_paths,
        )
        return result

    def claim(
        self,
        action: str,
        *,
        release: VerifiedActionRelease | None = None,
    ) -> ActionBudgetClaim:
        action = _validate_action(action)
        if action == "input_admission":
            if release is not None:
                raise ActionBudgetError("INPUT_ADMISSION_ACTION_CANNOT_USE_EXECUTION_RELEASE")
            raise ActionBudgetError("INPUT_ADMISSION_REQUIRES_EXPECTED_READ_RELEASE_SHA")
        if action == RECOVERY_ACTION:
            raise ActionBudgetError("RECOVERY_ADMISSION_REQUIRES_FIXED_LOCKED_USER_GRANT")
        if self.synthetic:
            if release is not None:
                raise ActionBudgetError("synthetic action claims cannot use a real release")
            release_sha = "0" * 64
            sealed_status = "NOT_ENTERED"
        else:
            if release is None:
                raise ActionBudgetError("REAL_ACTION_BUDGET_RELEASE_REQUIRED")

        action_key = RECOVERY_ACTION_KEY if action == RECOVERY_ACTION else f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
        execution_id = f"{ROUTE_ID}_{CANDIDATE_ID}_{action.upper()}_ONE_SHOT"
        arm = f"BREADTH1_ACTION_{action.upper()}"
        with self.official._locked():
            raw, events = self.official._read_validated()
            contract, binding, admission_receipt_snapshot = self._read_contract_binding_snapshot(
                registry_events=events,
            )
            source_binding = binding.get("source_binding")
            verified_admission_execution_ids: set[str] = set()
            if (
                not self.synthetic
                and contract.get("status") == "DRAFT_NO_REAL_RUN"
                and isinstance(source_binding, Mapping)
                and source_binding.get("provenance_mode") == "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
            ):
                # The same frozen draft identity governs admission and all
                # later actions.  Ignore only exact earlier no-fit admission
                # lifecycles after revalidating their linked receipts/events.
                self._verify_linked_failed_admission_lifecycle(events)
                self._verify_linked_rejected_r1_admission(events)
                current_admission = (
                    admission_receipt_snapshot[0]
                    if isinstance(admission_receipt_snapshot, tuple)
                    and isinstance(admission_receipt_snapshot[0], Mapping)
                    else {}
                )
                if current_admission.get("registry_execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID:
                    raise ActionBudgetIdentityDrift("ADMISSION_GATED_ACTION_CURRENT_PANEL_HEADER_R5_LIFECYCLE_MISSING")
                self._verify_linked_panel_header_admission_failure(events)
                self._verify_linked_panel_header_runtime_failure(events)
                self._verify_linked_panel_header_r5_failure(events)
                self._verify_linked_panel_header_r6_failure(events)
                verified_admission_execution_ids = {
                    FAILED_ADMISSION_EXECUTION_ID,
                    KEY_ALIGNMENT_FAILED_EXECUTION_ID,
                    KEY_ALIGNMENT_EXECUTION_ID,
                    TRAIN_LABEL_FAILED_EXECUTION_ID,
                    TRAIN_LABEL_RECOVERY_EXECUTION_ID,
                    TRAIN_LABEL_DIAGNOSTIC_EXECUTION_ID,
                    PANEL_HEADER_RECOVERY_EXECUTION_ID,
                    PANEL_HEADER_R6_RECOVERY_EXECUTION_ID,
                    PANEL_HEADER_R5_RECOVERY_EXECUTION_ID,
                    PANEL_HEADER_R4_RECOVERY_EXECUTION_ID,
                    PANEL_HEADER_DIAGNOSTIC_EXECUTION_ID,
                }
            if self.synthetic:
                release_value: Mapping[str, Any] | None = None
            else:
                assert release is not None
                context = self._read_real_action_context(
                    release, contract=contract, binding=binding,
                    admission_receipt_snapshot=admission_receipt_snapshot,
                )
                release_value = context.release_value
                if action not in release_value.get("actions", {}):
                    raise ActionBudgetError(f"REAL_RELEASE_DOES_NOT_AUTHORIZE_ACTION:{action}")
                if release_value.get("input_admission_receipt_sha256") != binding.get("input_admission_receipt_sha256"):
                    raise ActionBudgetIdentityDrift("REAL_RELEASE_ADMISSION_RECEIPT_BINDING_MISMATCH")
                release_sha = context.release_sha256
                sealed_status = str(release_value["sealed_status"])
                if release_value["actions"][action]["max_calls"] != ACTION_CAP:
                    raise ActionBudgetError(f"REAL_RELEASE_{action.upper()}_CAP_MUST_EQUAL_ONE")
            if not self.synthetic and action == "truth_decode":
                _verify_prior_real_action_receipts(events, release_value)
            prior_candidate = [
                event for event in events
                if event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and isinstance(event.get("budget_action_key"), str)
            ]
            if any(event.get("execution_id") == FAILED_ADMISSION_EXECUTION_ID for event in prior_candidate):
                self._verify_linked_failed_admission_lifecycle(events)
            for event in prior_candidate:
                if event.get("execution_id") in verified_admission_execution_ids:
                    if (
                        event.get("budget_action") not in {"input_admission", RECOVERY_ACTION}
                        or event.get("event_type") not in {"RUN_STARTED", "TERMINAL", "CORRECTION"}
                    ):
                        raise ActionBudgetIdentityDrift("ADMISSION_GATED_ACTION_PRIOR_LIFECYCLE_NOT_NO_FIT")
                    continue
                if (
                    event.get("contract_sha256") != self.contract_sha256
                    or event.get("input_binding_sha256") != self.input_binding_sha256
                ):
                    raise ActionBudgetIdentityDrift(
                        "CANDIDATE_CONTRACT_OR_INPUT_BINDING_DRIFT_CANNOT_RESET_ACTION_BUDGET"
                    )
            if any(event.get("budget_action_key") == action_key for event in prior_candidate):
                raise ActionBudgetConsumed(f"fixed action key already consumed: {action_key}")
            if any(event.get("execution_id") == execution_id for event in events):
                raise ActionBudgetConsumed(f"official execution identity already exists: {execution_id}")
            debit_total = _real_fit_debit_total(events, EXPERIMENT_ID)
            if action == "fit" and debit_total + ACTION_CAP > ACTION_CAP:
                raise ActionBudgetConsumed("official real-fit debit cap already consumed")

            event = self._action_event_spec(
                action=action,
                event_type="RUN_STARTED",
                execution_id=execution_id,
                arm=arm,
                release_sha=release_sha,
                sealed_status=sealed_status,
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [
                item for item in appended
                if item.get("execution_id") == execution_id
                and item.get("event_type") == "RUN_STARTED"
                and item.get("budget_action_key") == action_key
            ]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_ACTION_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=action,
            action_key=action_key,
            execution_id=execution_id,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status=sealed_status,
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def claim_input_admission(self, *, read_release_sha256: str) -> ActionBudgetClaim:
        """Atomically spend the fixed first-pass audit before opening its release or inputs."""
        if not self.admission_only or self.synthetic:
            raise ActionBudgetError("INPUT_ADMISSION_REQUIRES_PENDING_REAL_ADMISSION_ADAPTER")
        release_sha = _require_sha(read_release_sha256, "read_release_sha256")
        action = "input_admission"
        action_key = RECOVERY_ACTION_KEY if action == RECOVERY_ACTION else f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
        execution_id = f"{ROUTE_ID}_{CANDIDATE_ID}_{action.upper()}_ONE_SHOT"
        arm = f"BREADTH1_ACTION_{action.upper()}"
        with self.official._locked():
            raw, events = self.official._read_validated()
            self._read_pending_admission_snapshot()
            prior_candidate = [
                event for event in events
                if event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and isinstance(event.get("budget_action_key"), str)
            ]
            for event in prior_candidate:
                if (
                    event.get("contract_sha256") != self.contract_sha256
                    or event.get("input_binding_sha256") != self.input_binding_sha256
                ):
                    raise ActionBudgetIdentityDrift(
                        "CANDIDATE_CONTRACT_OR_INPUT_BINDING_DRIFT_CANNOT_RESET_ACTION_BUDGET"
                    )
            if any(event.get("budget_action_key") == action_key for event in prior_candidate):
                raise ActionBudgetConsumed(f"fixed action key already consumed: {action_key}")
            if any(event.get("execution_id") == execution_id for event in events):
                raise ActionBudgetConsumed(f"official execution identity already exists: {execution_id}")
            event = self._action_event_spec(
                action=action,
                event_type="RUN_STARTED",
                execution_id=execution_id,
                arm=arm,
                release_sha=release_sha,
                sealed_status="NOT_CHECKED",
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [
                item for item in appended
                if item.get("execution_id") == execution_id
                and item.get("event_type") == "RUN_STARTED"
                and item.get("budget_action_key") == action_key
            ]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_INPUT_ADMISSION_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=action,
            action_key=action_key,
            execution_id=execution_id,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status="NOT_CHECKED",
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def claim_input_admission_recovery(self) -> ActionBudgetClaim:
        """Spend the one fixed user-authorized recovery check under the official lock."""
        if not self.admission_only or self.synthetic:
            raise ActionBudgetError("RECOVERY_ADMISSION_REQUIRES_PENDING_REAL_ADMISSION_ADAPTER")
        action = RECOVERY_ACTION
        action_key = RECOVERY_ACTION_KEY
        execution_id = RECOVERY_EXECUTION_ID
        arm = "BREADTH1_ACTION_INPUT_ADMISSION_RECOVERY"
        with self.official._locked():
            raw, events = self.official._read_validated()
            self._read_pending_admission_snapshot()
            grant_payload, grant = self._read_fixed_admission_recovery_grant()
            self._verify_linked_failed_admission_lifecycle(events)
            if any(
                event.get("budget_action_key") == action_key
                or event.get("execution_id") == execution_id
                for event in events
            ):
                raise ActionBudgetConsumed("fixed recovery grant/key already consumed")
            if any(
                event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action") in {"fit", "predict", "truth_decode"}
                for event in events
            ):
                raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_MUST_PRECEDE_ALL_MODEL_OR_TRUTH_ACTIONS")
            release_sha = _require_sha(grant.get("read_release_sha256"), "recovery_read_release_sha256")
            event = self._action_event_spec(
                action=action,
                event_type="RUN_STARTED",
                execution_id=execution_id,
                arm=arm,
                release_sha=release_sha,
                sealed_status="NOT_CHECKED",
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            recovery_metrics = {
                "recovery_grant_id": RECOVERY_GRANT_ID,
                "recovery_grant_sha256": hashlib.sha256(grant_payload).hexdigest(),
                "linked_failed_execution_id": FAILED_ADMISSION_EXECUTION_ID,
                "linked_failed_start_event_sha256": FAILED_ADMISSION_START_SHA256,
                "linked_failed_terminal_event_sha256": FAILED_ADMISSION_TERMINAL_SHA256,
                "user_authorization_text": grant["user_authorization_text"],
                "user_authorization_timestamp_utc": grant["user_authorization_timestamp_utc"],
                "user_authorization_source_item_id": grant["user_authorization_source_item_id"],
            }
            event["deterministic_metrics"].update(recovery_metrics)
            event["input_identity"].update(recovery_metrics)
            event["recovery_grant_id"] = RECOVERY_GRANT_ID
            event["linked_failed_execution_id"] = FAILED_ADMISSION_EXECUTION_ID
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [
                item for item in appended
                if item.get("execution_id") == execution_id
                and item.get("event_type") == "RUN_STARTED"
                and item.get("budget_action_key") == action_key
            ]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_RECOVERY_ADMISSION_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=action,
            action_key=action_key,
            execution_id=execution_id,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status="NOT_CHECKED",
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def claim_input_key_alignment_recovery(self) -> ActionBudgetClaim:
        """Spend one fixed key-alignment check linked to the rejected R1 receipt."""
        if not self.admission_only or self.synthetic:
            raise ActionBudgetError("KEY_ALIGNMENT_RECOVERY_REQUIRES_PENDING_REAL_ADMISSION_ADAPTER")
        with self.official._locked():
            raw, events = self.official._read_validated()
            self._read_pending_admission_snapshot()
            grant_payload, grant = self._read_fixed_key_alignment_recovery_grant()
            self._verify_linked_rejected_r1_admission(events)
            if any(
                event.get("budget_action_key") == KEY_ALIGNMENT_ACTION_KEY
                or event.get("execution_id") == KEY_ALIGNMENT_EXECUTION_ID
                for event in events
            ):
                raise ActionBudgetConsumed("fixed key-alignment recovery grant/key already consumed")
            if any(
                event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action") in {"fit", "predict", "truth_decode"}
                for event in events
            ):
                raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_RECOVERY_MUST_PRECEDE_MODEL_OR_TRUTH_ACTIONS")
            release_sha = _require_sha(grant.get("read_release_sha256"), "key_alignment_read_release_sha256")
            event = self._action_event_spec(
                action=RECOVERY_ACTION,
                event_type="RUN_STARTED",
                execution_id=KEY_ALIGNMENT_EXECUTION_ID,
                arm=f"BREADTH1_ACTION_{RECOVERY_ACTION.upper()}",
                release_sha=release_sha,
                sealed_status="NOT_CHECKED",
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            link = {
                "recovery_grant_id": KEY_ALIGNMENT_RECOVERY_GRANT_ID,
                "recovery_grant_sha256": hashlib.sha256(grant_payload).hexdigest(),
                "linked_failed_execution_id": KEY_ALIGNMENT_FAILED_EXECUTION_ID,
                "linked_failed_start_event_sha256": KEY_ALIGNMENT_FAILED_START_SHA256,
                "linked_failed_terminal_event_sha256": KEY_ALIGNMENT_FAILED_TERMINAL_SHA256,
                "linked_failed_receipt_sha256": KEY_ALIGNMENT_FAILED_RECEIPT_SHA256,
                "user_authorization_text": grant["user_authorization_text"],
                "user_authorization_timestamp_utc": grant["user_authorization_timestamp_utc"],
                "user_authorization_source_item_id": grant["user_authorization_source_item_id"],
            }
            event["budget_action_key"] = KEY_ALIGNMENT_ACTION_KEY
            event["deterministic_metrics"].update(link)
            event["deterministic_metrics"]["budget_action_key"] = KEY_ALIGNMENT_ACTION_KEY
            event["input_identity"].update(link)
            event["input_identity"]["budget_action_key"] = KEY_ALIGNMENT_ACTION_KEY
            event["recovery_grant_id"] = KEY_ALIGNMENT_RECOVERY_GRANT_ID
            event["linked_failed_execution_id"] = KEY_ALIGNMENT_FAILED_EXECUTION_ID
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [item for item in appended if item.get("execution_id") == KEY_ALIGNMENT_EXECUTION_ID and item.get("event_type") == "RUN_STARTED" and item.get("budget_action_key") == KEY_ALIGNMENT_ACTION_KEY]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_KEY_ALIGNMENT_RECOVERY_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=RECOVERY_ACTION,
            action_key=KEY_ALIGNMENT_ACTION_KEY,
            execution_id=KEY_ALIGNMENT_EXECUTION_ID,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status="NOT_CHECKED",
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def _read_fixed_key_alignment_recovery_grant(self) -> tuple[bytes, Mapping[str, Any]]:
        path = KEY_ALIGNMENT_RECOVERY_GRANT_PATH
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_RECOVERY_GRANT_PATH_OR_SIZE_INVALID")
        payload = path.read_bytes()
        grant = _parse_json_object(payload, "KEY_ALIGNMENT_RECOVERY_GRANT")
        expected = {
            "schema": "F5_BREADTH1_INPUT_KEY_ALIGNMENT_RECOVERY_GRANT_V1",
            "status": "AUTHORIZED_ONE_SHOT",
            "grant_id": KEY_ALIGNMENT_RECOVERY_GRANT_ID,
            "route_id": ROUTE_ID,
            "candidate_id": CANDIDATE_ID,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
            "budget_action_key": KEY_ALIGNMENT_ACTION_KEY,
            "execution_id": KEY_ALIGNMENT_EXECUTION_ID,
            "action_cap": ACTION_CAP,
            "failure_or_interruption_refund": False,
            "linked_failed_execution_id": KEY_ALIGNMENT_FAILED_EXECUTION_ID,
            "linked_failed_start_event_sha256": KEY_ALIGNMENT_FAILED_START_SHA256,
            "linked_failed_terminal_event_sha256": KEY_ALIGNMENT_FAILED_TERMINAL_SHA256,
            "linked_failed_attempt_receipt_path": str(KEY_ALIGNMENT_FAILED_RECEIPT_PATH),
            "linked_failed_attempt_receipt_sha256": KEY_ALIGNMENT_FAILED_RECEIPT_SHA256,
            "linked_failed_registry_receipt_path": str(KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH),
            "linked_failed_registry_receipt_sha256": KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_SHA256,
            "read_release_path": str(KEY_ALIGNMENT_READ_RELEASE_PATH),
            "read_plan_path": str(KEY_ALIGNMENT_READ_PLAN_PATH),
            "user_authorization_text": "就按唯一键对齐修正，原数据和模型参数不变。允许再做一次针对性检查，键集合一致就按原 X_eval 行序映射，然后直接训练一次、完整预测一次、封存评价一次。不要再找历史证据、重复合成测试或反复问我确认。",
            "user_authorization_timestamp_utc": "2026-10-11T05:12:27.693554Z",
            "user_authorization_source_item_id": "230095514",
            "authorized_scope": "one key-set diagnostic and alignment audit; when and only when eval_meta and pretruth key sets match, continue under the existing single-fit, single-full-predict, sealed-evaluation authorization",
            "prohibited_actions_in_this_grant": ["fit", "predict", "model_load", "truth_decode", "orders"],
        }
        if set(grant) != set(expected) | {"read_release_sha256", "read_plan_sha256"} or any(grant.get(name) != value for name, value in expected.items()):
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_RECOVERY_GRANT_IDENTITY_MISMATCH")
        _require_sha(grant.get("read_release_sha256"), "key_alignment_read_release_sha256")
        if not KEY_ALIGNMENT_READ_PLAN_PATH.is_file() or KEY_ALIGNMENT_READ_PLAN_PATH.is_symlink() or KEY_ALIGNMENT_READ_PLAN_PATH.stat().st_size > 1024 * 1024 or sha256_file(KEY_ALIGNMENT_READ_PLAN_PATH) != grant.get("read_plan_sha256"):
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_READ_PLAN_IDENTITY_MISMATCH")
        plan = _parse_json_object(KEY_ALIGNMENT_READ_PLAN_PATH.read_bytes(), "KEY_ALIGNMENT_READ_PLAN")
        if plan.get("contract_sha256") != self.contract_sha256 or plan.get("pre_admission_binding_sha256") != self.input_binding_sha256 or plan.get("recovery_grant_id") != KEY_ALIGNMENT_RECOVERY_GRANT_ID or plan.get("recovery_execution_id") != KEY_ALIGNMENT_EXECUTION_ID:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_READ_PLAN_BINDING_MISMATCH")
        return payload, grant

    def _verify_linked_rejected_r1_admission(self, events: Sequence[Mapping[str, Any]]) -> None:
        if not KEY_ALIGNMENT_FAILED_RECEIPT_PATH.is_file() or KEY_ALIGNMENT_FAILED_RECEIPT_PATH.is_symlink() or sha256_file(KEY_ALIGNMENT_FAILED_RECEIPT_PATH) != KEY_ALIGNMENT_FAILED_RECEIPT_SHA256:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(KEY_ALIGNMENT_FAILED_RECEIPT_PATH.read_bytes(), "KEY_ALIGNMENT_LINKED_R1_RECEIPT")
        actual = receipt.get("actual_read")
        counts = actual.get("file_count") if isinstance(actual, Mapping) else None
        bytes_read = actual.get("total_bytes") if isinstance(actual, Mapping) else None
        if receipt.get("status") != "INPUT_REJECTED" or receipt.get("error") != "A_PRETRUTH_IDENTITY_PROJECTION_DIFFERS_FROM_FROZEN_EVAL_KEYS" or counts != 10 or bytes_read != 195252655 or any(receipt.get(key) != 0 for key in ("real_fit_calls", "real_predict_calls", "real_truth_decode_calls")):
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_RECEIPT_STATE_MISMATCH")
        if not KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH.is_file() or KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH.is_symlink() or sha256_file(KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH) != KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_SHA256:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_REGISTRY_RECEIPT_IDENTITY_MISMATCH")
        registry_receipt = _parse_json_object(KEY_ALIGNMENT_FAILED_REGISTRY_RECEIPT_PATH.read_bytes(), "KEY_ALIGNMENT_LINKED_R1_REGISTRY_RECEIPT")
        if registry_receipt.get("input_admission_status") != "INPUT_REJECTED" or registry_receipt.get("input_admission_receipt_sha256") != KEY_ALIGNMENT_FAILED_RECEIPT_SHA256 or registry_receipt.get("route_lifecycle_count") != 2:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_REGISTRY_RECEIPT_STATE_MISMATCH")
        lifecycle = [event for event in events if event.get("execution_id") == KEY_ALIGNMENT_FAILED_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in lifecycle}
        if len(lifecycle) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if start.get("event_sha256") != KEY_ALIGNMENT_FAILED_START_SHA256 or start.get("budget_action_key") != RECOVERY_ACTION_KEY or start.get("budget_action_debit") != 1 or not isinstance(start_metrics, Mapping) or start_metrics.get("recovery_grant_id") != RECOVERY_GRANT_ID:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_START_IDENTITY_MISMATCH")
        if terminal.get("event_sha256") != KEY_ALIGNMENT_FAILED_TERMINAL_SHA256 or terminal.get("decision") != "ENGINEERING_CANARY_ONLY" or terminal.get("started_event_sha256") != KEY_ALIGNMENT_FAILED_START_SHA256 or not isinstance(terminal_metrics, Mapping) or terminal_metrics.get("real_fit_budget_debit") != 0:
            raise ActionBudgetIdentityDrift("KEY_ALIGNMENT_LINKED_R1_TERMINAL_IDENTITY_MISMATCH")

    def _verify_linked_train_label_admission_failure(
        self, events: Sequence[Mapping[str, Any]]
    ) -> None:
        """Pin the prior R2 failure and the exact one-read label diagnostic."""
        if (
            not TRAIN_LABEL_FAILED_RECEIPT_PATH.is_file()
            or TRAIN_LABEL_FAILED_RECEIPT_PATH.is_symlink()
            or sha256_file(TRAIN_LABEL_FAILED_RECEIPT_PATH) != TRAIN_LABEL_FAILED_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(TRAIN_LABEL_FAILED_RECEIPT_PATH.read_bytes(), "TRAIN_LABEL_LINKED_FAILED_RECEIPT")
        actual = receipt.get("actual_read")
        key_alignment = receipt.get("evaluation_key_alignment")
        if (
            receipt.get("status") != "INPUT_REJECTED"
            or receipt.get("error") != "FROZEN_TRAIN_LABEL_IDENTITY_MISMATCH"
            or not isinstance(actual, Mapping)
            or actual.get("file_count") != 10
            or actual.get("total_bytes") != 195253532
            or key_alignment != {}
            or any(receipt.get(key) != 0 for key in ("real_fit_calls", "real_predict_calls", "real_truth_decode_calls"))
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_RECEIPT_STATE_MISMATCH")
        if (
            not TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_PATH.is_file()
            or TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_PATH.is_symlink()
            or sha256_file(TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_PATH) != TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_REGISTRY_RECEIPT_IDENTITY_MISMATCH")
        registry_receipt = _parse_json_object(
            TRAIN_LABEL_FAILED_REGISTRY_RECEIPT_PATH.read_bytes(), "TRAIN_LABEL_LINKED_FAILED_REGISTRY_RECEIPT"
        )
        if (
            registry_receipt.get("input_admission_status") != "INPUT_REJECTED"
            or registry_receipt.get("input_admission_receipt_sha256") != TRAIN_LABEL_FAILED_RECEIPT_SHA256
            or registry_receipt.get("route_lifecycle_count") != 2
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_REGISTRY_RECEIPT_STATE_MISMATCH")
        lifecycle = [event for event in events if event.get("execution_id") == TRAIN_LABEL_FAILED_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in lifecycle}
        if len(lifecycle) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_sha256") != TRAIN_LABEL_FAILED_START_SHA256
            or start.get("contract_sha256") != TRAIN_LABEL_FAILED_CONTRACT_SHA256
            or start.get("input_binding_sha256") != TRAIN_LABEL_FAILED_BINDING_SHA256
            or start.get("route_id") != ROUTE_ID
            or start.get("candidate_id") != CANDIDATE_ID
            or start.get("experiment_id") != EXPERIMENT_ID
            or start.get("budget_action") != RECOVERY_ACTION
            or start.get("budget_action_key") != KEY_ALIGNMENT_ACTION_KEY
            or start.get("budget_action_debit") != 1
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("recovery_grant_id") != KEY_ALIGNMENT_RECOVERY_GRANT_ID
            or start_metrics.get("linked_failed_receipt_sha256") != KEY_ALIGNMENT_FAILED_RECEIPT_SHA256
            or terminal.get("event_sha256") != TRAIN_LABEL_FAILED_TERMINAL_SHA256
            or terminal.get("contract_sha256") != TRAIN_LABEL_FAILED_CONTRACT_SHA256
            or terminal.get("input_binding_sha256") != TRAIN_LABEL_FAILED_BINDING_SHA256
            or terminal.get("decision") != "ENGINEERING_CANARY_ONLY"
            or terminal.get("started_event_sha256") != TRAIN_LABEL_FAILED_START_SHA256
            or not isinstance(terminal_metrics, Mapping)
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
            or terminal_metrics.get("linked_failed_receipt_sha256") != KEY_ALIGNMENT_FAILED_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_LINKED_FAILED_LIFECYCLE_IDENTITY_MISMATCH")
        _verify_train_label_diagnostic(events)

    def _verify_linked_panel_header_admission_failure(
        self, events: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        """Pin the consumed R3 panel-header failure and its one-read diagnostic."""
        self._verify_linked_failed_admission_lifecycle(events)
        self._verify_linked_rejected_r1_admission(events)
        self._verify_linked_train_label_admission_failure(events)
        if (
            not PANEL_HEADER_FAILED_RECEIPT_PATH.is_file()
            or PANEL_HEADER_FAILED_RECEIPT_PATH.is_symlink()
            or sha256_file(PANEL_HEADER_FAILED_RECEIPT_PATH) != PANEL_HEADER_FAILED_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_FAILED_RECEIPT_IDENTITY_MISMATCH")
        failure = _parse_json_object(PANEL_HEADER_FAILED_RECEIPT_PATH.read_bytes(), "PANEL_HEADER_LINKED_FAILED_RECEIPT")
        actual = failure.get("actual_read")
        files = actual.get("files") if isinstance(actual, Mapping) else None
        panel = files.get("panel:HK.00001") if isinstance(files, Mapping) else None
        if (
            failure.get("status") != "CANNOT_CONFIRM_INPUT_ADMISSION"
            or failure.get("error") != "PARENT_PANEL_HK.00001_CSV_HEADER_INVALID"
            or not isinstance(actual, Mapping)
            or actual.get("file_count") != 11
            or actual.get("total_bytes") != 195792181
            or not isinstance(panel, Mapping)
            or panel.get("sha256") != "5303a9f7ad55cc438c200b260538d7265729af2a2c6c396c955211b9dd806902"
            or panel.get("bytes") != 534661
            or failure.get("registry_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
            or failure.get("registry_start_event_sha256") != PANEL_HEADER_FAILED_START_SHA256
            or not _valid_prior_train_label_diagnostic(failure.get("prior_train_label_diagnostic"))
            or any(failure.get(key) != 0 for key in ("real_fit_calls", "real_predict_calls", "real_truth_decode_calls"))
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_FAILED_RECEIPT_STATE_MISMATCH")
        if (
            not PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH.is_file()
            or PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH.is_symlink()
            or sha256_file(PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH) != PANEL_HEADER_FAILED_REGISTRY_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_REGISTRY_RECEIPT_IDENTITY_MISMATCH")
        registry_receipt = _parse_json_object(
            PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH.read_bytes(), "PANEL_HEADER_LINKED_REGISTRY_RECEIPT"
        )
        if (
            registry_receipt.get("execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
            or registry_receipt.get("input_admission_status") != "CANNOT_CONFIRM_INPUT_ADMISSION"
            or registry_receipt.get("input_admission_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
            or registry_receipt.get("route_lifecycle_count") != 2
            or registry_receipt.get("real_fit_calls") != 0
            or registry_receipt.get("real_predict_calls") != 0
            or registry_receipt.get("real_truth_decode_calls") != 0
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_REGISTRY_RECEIPT_STATE_MISMATCH")
        lifecycle = [event for event in events if event.get("execution_id") == PANEL_HEADER_FAILED_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in lifecycle}
        if len(lifecycle) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_FAILED_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_sha256") != PANEL_HEADER_FAILED_START_SHA256
            or start.get("contract_sha256") != "916a120f26b0a74cbe82d390d9d693934752f89648d7936666ba565a51cafb0f"
            or start.get("input_binding_sha256") != "e2f895d539ea291855436edb36a00fde07a08c3012ffb95a09599ee9582f7319"
            or start.get("route_id") != ROUTE_ID
            or start.get("candidate_id") != CANDIDATE_ID
            or start.get("experiment_id") != EXPERIMENT_ID
            or start.get("budget_action") != RECOVERY_ACTION
            or start.get("budget_action_key") != TRAIN_LABEL_RECOVERY_ACTION_KEY
            or start.get("budget_action_debit") != 1
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("recovery_grant_id") != TRAIN_LABEL_RECOVERY_GRANT_ID
            or terminal.get("event_sha256") != PANEL_HEADER_FAILED_TERMINAL_SHA256
            or terminal.get("contract_sha256") != "916a120f26b0a74cbe82d390d9d693934752f89648d7936666ba565a51cafb0f"
            or terminal.get("input_binding_sha256") != "e2f895d539ea291855436edb36a00fde07a08c3012ffb95a09599ee9582f7319"
            or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or terminal.get("started_event_sha256") != PANEL_HEADER_FAILED_START_SHA256
            or not isinstance(terminal_metrics, Mapping)
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_LINKED_FAILED_LIFECYCLE_IDENTITY_MISMATCH")
        return _verify_panel_header_diagnostic(events)

    def _verify_linked_panel_header_runtime_failure(
        self, events: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        """Verify the consumed R4 runtime failure without reopening target inputs."""
        path = PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_PATH
        if path.is_symlink() or not path.is_file() or sha256_file(path) != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(path.read_bytes(), "PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT")
        counts = receipt.get("action_counts")
        diagnostic = receipt.get("diagnostic_state")
        lifecycle = receipt.get("registry_lifecycle")
        expected_summary = _panel_header_runtime_failure_summary(receipt)
        if (
            receipt.get("schema") != "F5_BREADTH1_R4_ADMISSION_RUNTIME_FAILURE_RECEIPT_V1"
            or receipt.get("status") != "CANNOT_CONFIRM_ACTION_FAILED"
            or receipt.get("decision") != "NO_FIT_EFFECT_NOT_TESTED"
            or receipt.get("route_id") != ROUTE_ID
            or receipt.get("execution_id") != PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
            or receipt.get("recovery_grant_id") != PANEL_HEADER_R4_RECOVERY_GRANT_ID
            or receipt.get("contract_sha256") != PANEL_HEADER_R4_CONTRACT_SHA256
            or receipt.get("input_binding_sha256") != PANEL_HEADER_R4_BINDING_SHA256
            or receipt.get("read_release_sha256") != PANEL_HEADER_R4_READ_RELEASE_SHA256
            or receipt.get("error_type") != "AttributeError"
            or receipt.get("error") != "list object has no attribute map"
            or receipt.get("failure_location") != {
                "file": "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_inputs.py",
                "function": "_attach_parent_market_date",
                "line": 1853,
                "expression": "sessions.map(session_to_date)",
            }
            or not isinstance(counts, Mapping)
            or counts.get("real_input_accessed") is not True
            or any(counts.get(key) != 0 for key in (
                "real_fit_calls", "real_predict_calls", "real_model_load_calls", "real_truth_decode_calls",
            ))
            or not isinstance(diagnostic, Mapping)
            or diagnostic.get("input_bytes_read") is not None
            or diagnostic.get("physical_input_file_count") is not None
            or diagnostic.get("read_summary_status") != "CANNOT_CONFIRM"
            or diagnostic.get("key_alignment") != "COMPUTED_IN_MEMORY_NOT_PERSISTED"
            or diagnostic.get("train_label_identity") != "COMPUTED_IN_MEMORY_NOT_PERSISTED"
            or not isinstance(lifecycle, Mapping)
            or lifecycle.get("start_event_sha256") != PANEL_HEADER_R4_FAILED_START_SHA256
            or lifecycle.get("terminal_event_sha256") != PANEL_HEADER_R4_FAILED_TERMINAL_SHA256
            or lifecycle.get("terminal_decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or lifecycle.get("terminal_stop_reason") != "AttributeError"
            or not _valid_prior_panel_header_runtime_failure(expected_summary)
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_CONTENT_MISMATCH")
        prior_events = [event for event in events if event.get("execution_id") == PANEL_HEADER_R4_RECOVERY_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in prior_events}
        if len(prior_events) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R4_RUNTIME_FAILURE_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_sha256") != PANEL_HEADER_R4_FAILED_START_SHA256
            or start.get("route_id") != ROUTE_ID
            or start.get("candidate_id") != CANDIDATE_ID
            or start.get("experiment_id") != EXPERIMENT_ID
            or start.get("contract_sha256") != PANEL_HEADER_R4_CONTRACT_SHA256
            or start.get("input_binding_sha256") != PANEL_HEADER_R4_BINDING_SHA256
            or start.get("decision") != "RUNNING"
            or start.get("budget_action") != RECOVERY_ACTION
            or start.get("budget_action_key") != PANEL_HEADER_R4_RECOVERY_ACTION_KEY
            or start.get("budget_action_debit") != 1
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("budget_release_sha256") != PANEL_HEADER_R4_READ_RELEASE_SHA256
            or start_metrics.get("recovery_grant_id") != PANEL_HEADER_R4_RECOVERY_GRANT_ID
            or terminal.get("event_sha256") != PANEL_HEADER_R4_FAILED_TERMINAL_SHA256
            or terminal.get("route_id") != ROUTE_ID
            or terminal.get("candidate_id") != CANDIDATE_ID
            or terminal.get("contract_sha256") != PANEL_HEADER_R4_CONTRACT_SHA256
            or terminal.get("input_binding_sha256") != PANEL_HEADER_R4_BINDING_SHA256
            or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or terminal.get("started_event_sha256") != PANEL_HEADER_R4_FAILED_START_SHA256
            or not isinstance(terminal_metrics, Mapping)
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
            or terminal_metrics.get("real_fit_returned_count") != 0
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R4_RUNTIME_FAILURE_LIFECYCLE_MISMATCH")
        return expected_summary

    def _verify_linked_panel_header_r5_failure(
        self, events: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        """Verify the consumed R5 pre-read failure and its exact registry lifecycle."""
        path = PANEL_HEADER_R5_FAILED_RECEIPT_PATH
        if path.is_symlink() or not path.is_file() or sha256_file(path) != PANEL_HEADER_R5_FAILED_RECEIPT_SHA256:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(path.read_bytes(), "PANEL_HEADER_R5_PRECALL_FAILURE_RECEIPT")
        lifecycle = receipt.get("registry_lifecycle")
        summary = _panel_header_r5_precall_failure_summary()
        if (
            receipt.get("schema") != "F5_BREADTH1_INPUT_ADMISSION_PRECALL_FAILURE_RECEIPT_V1"
            or receipt.get("status") != summary["status"]
            or receipt.get("route_id") != ROUTE_ID
            or receipt.get("candidate_id") != CANDIDATE_ID
            or receipt.get("execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
            or receipt.get("recovery_grant_id") != PANEL_HEADER_R5_RECOVERY_GRANT_ID
            or receipt.get("budget_action_key") != PANEL_HEADER_R5_RECOVERY_ACTION_KEY
            or receipt.get("attempt_identity", {}).get("contract_sha256") != PANEL_HEADER_R5_CONTRACT_SHA256
            or receipt.get("attempt_identity", {}).get("input_binding_sha256") != PANEL_HEADER_R5_BINDING_SHA256
            or receipt.get("attempt_identity", {}).get("read_release_sha256") != PANEL_HEADER_R5_READ_RELEASE_SHA256
            or receipt.get("error_type") != "AdmissionBlocked"
            or receipt.get("error") != "INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH"
            or receipt.get("failed_stage") != "verified_read_release_binding"
            or receipt.get("data_read_ledger_status") != "NOT_CREATED_PRE_AUDIT"
            or receipt.get("target_input_files_opened") != 0
            or receipt.get("target_input_bytes_read") != 0
            or receipt.get("real_input_accessed") is not False
            or receipt.get("grant_consumed") is not True
            or receipt.get("failure_or_interruption_refund") is not False
            or any(receipt.get(name) != 0 for name in (
                "real_fit_calls", "real_predict_calls", "real_model_load_calls", "real_truth_decode_calls",
            ))
            or not isinstance(lifecycle, Mapping)
            or lifecycle.get("run_started_event_sha256") != PANEL_HEADER_R5_FAILED_START_SHA256
            or lifecycle.get("terminal_event_sha256") != PANEL_HEADER_R5_FAILED_TERMINAL_SHA256
            or lifecycle.get("terminal_decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or lifecycle.get("terminal_stop_reason") != "AdmissionBlocked"
            or _valid_prior_panel_header_r5_failure(summary) is not True
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_RECEIPT_CONTENT_MISMATCH")
        prior_events = [event for event in events if event.get("execution_id") == PANEL_HEADER_R5_RECOVERY_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in prior_events}
        if len(prior_events) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_sha256") != PANEL_HEADER_R5_FAILED_START_SHA256
            or start.get("route_id") != ROUTE_ID
            or start.get("candidate_id") != CANDIDATE_ID
            or start.get("execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
            or start.get("contract_sha256") != PANEL_HEADER_R5_CONTRACT_SHA256
            or start.get("input_binding_sha256") != PANEL_HEADER_R5_BINDING_SHA256
            or start.get("decision") != "RUNNING"
            or start.get("budget_action") != RECOVERY_ACTION
            or start.get("budget_action_key") != PANEL_HEADER_R5_RECOVERY_ACTION_KEY
            or start.get("budget_action_debit") != 1
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("budget_release_sha256") != PANEL_HEADER_R5_READ_RELEASE_SHA256
            or start_metrics.get("recovery_grant_id") != PANEL_HEADER_R5_RECOVERY_GRANT_ID
            or start_metrics.get("linked_failed_execution_id") != PANEL_HEADER_R4_RECOVERY_EXECUTION_ID
            or start_metrics.get("linked_failed_start_event_sha256") != PANEL_HEADER_R4_FAILED_START_SHA256
            or start_metrics.get("linked_failed_terminal_event_sha256") != PANEL_HEADER_R4_FAILED_TERMINAL_SHA256
            or start_metrics.get("linked_failed_receipt_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
            or start_metrics.get("linked_r3_parent_header_failure_execution_id") != PANEL_HEADER_FAILED_EXECUTION_ID
            or start_metrics.get("linked_r3_parent_header_failure_start_event_sha256") != PANEL_HEADER_FAILED_START_SHA256
            or start_metrics.get("linked_r3_parent_header_failure_terminal_event_sha256") != PANEL_HEADER_FAILED_TERMINAL_SHA256
            or start_metrics.get("linked_r3_parent_header_failure_receipt_sha256") != PANEL_HEADER_FAILED_RECEIPT_SHA256
            or start_metrics.get("panel_header_diagnostic_receipt_sha256") != PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256
            or start_metrics.get("panel_header_diagnostic_start_event_sha256") != PANEL_HEADER_DIAGNOSTIC_START_SHA256
            or start_metrics.get("panel_header_diagnostic_terminal_event_sha256") != PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256
            or start_metrics.get("train_label_diagnostic_correction_event_sha256") != TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256
            or start_metrics.get("prior_panel_header_runtime_failure_sha256") != PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256
            or terminal.get("event_sha256") != PANEL_HEADER_R5_FAILED_TERMINAL_SHA256
            or terminal.get("route_id") != ROUTE_ID
            or terminal.get("candidate_id") != CANDIDATE_ID
            or terminal.get("execution_id") != PANEL_HEADER_R5_RECOVERY_EXECUTION_ID
            or terminal.get("contract_sha256") != PANEL_HEADER_R5_CONTRACT_SHA256
            or terminal.get("input_binding_sha256") != PANEL_HEADER_R5_BINDING_SHA256
            or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or terminal.get("started_event_sha256") != PANEL_HEADER_R5_FAILED_START_SHA256
            or not isinstance(terminal_metrics, Mapping)
            or terminal.get("stop_reason") != "AdmissionBlocked"
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
            or terminal_metrics.get("real_fit_returned_count") != 0
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_LIFECYCLE_MISMATCH")
        inherited_links = {
            "linked_failed_execution_id": PANEL_HEADER_R4_RECOVERY_EXECUTION_ID,
            "linked_failed_start_event_sha256": PANEL_HEADER_R4_FAILED_START_SHA256,
            "linked_failed_terminal_event_sha256": PANEL_HEADER_R4_FAILED_TERMINAL_SHA256,
            "linked_failed_receipt_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
            "linked_r3_parent_header_failure_execution_id": PANEL_HEADER_FAILED_EXECUTION_ID,
            "linked_r3_parent_header_failure_start_event_sha256": PANEL_HEADER_FAILED_START_SHA256,
            "linked_r3_parent_header_failure_terminal_event_sha256": PANEL_HEADER_FAILED_TERMINAL_SHA256,
            "linked_r3_parent_header_failure_receipt_sha256": PANEL_HEADER_FAILED_RECEIPT_SHA256,
            "panel_header_diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
            "panel_header_diagnostic_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
            "panel_header_diagnostic_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
            "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
            "prior_panel_header_runtime_failure_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
        }
        if any(
            start_metrics.get(name) != value or terminal_metrics.get(name) != value
            for name, value in inherited_links.items()
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_ANCESTOR_LINK_MISMATCH")
        return summary

    def claim_train_label_recovery(self) -> ActionBudgetClaim:
        """Consume the single post-diagnostic label recovery check before target reads."""
        if not self.admission_only or self.synthetic:
            raise ActionBudgetError("TRAIN_LABEL_RECOVERY_REQUIRES_PENDING_REAL_ADMISSION_ADAPTER")
        with self.official._locked():
            raw, events = self.official._read_validated()
            _, pending_binding = self._read_pending_admission_snapshot()
            grant_payload, grant = self._read_fixed_train_label_recovery_grant()
            self._verify_linked_failed_admission_lifecycle(events)
            self._verify_linked_rejected_r1_admission(events)
            self._verify_linked_train_label_admission_failure(events)
            diagnostic = _verify_train_label_diagnostic(events)
            if pending_binding.get("prior_train_label_diagnostic") != _train_label_diagnostic_summary(diagnostic):
                raise ActionBudgetIdentityDrift("TRAIN_LABEL_DIAGNOSTIC_BINDING_SUMMARY_MISMATCH")
            if any(
                event.get("budget_action_key") == TRAIN_LABEL_RECOVERY_ACTION_KEY
                or event.get("execution_id") == TRAIN_LABEL_RECOVERY_EXECUTION_ID
                for event in events
            ):
                raise ActionBudgetConsumed("fixed train-label recovery grant/key already consumed")
            if any(
                event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action") in {"fit", "predict", "truth_decode"}
                for event in events
            ):
                raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_MUST_PRECEDE_MODEL_OR_TRUTH_ACTIONS")
            release_sha = _require_sha(grant.get("read_release_sha256"), "train_label_read_release_sha256")
            event = self._action_event_spec(
                action=RECOVERY_ACTION,
                event_type="RUN_STARTED",
                execution_id=TRAIN_LABEL_RECOVERY_EXECUTION_ID,
                arm=f"BREADTH1_ACTION_{RECOVERY_ACTION.upper()}",
                release_sha=release_sha,
                sealed_status="NOT_CHECKED",
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            link = {
                "recovery_grant_id": TRAIN_LABEL_RECOVERY_GRANT_ID,
                "recovery_grant_sha256": hashlib.sha256(grant_payload).hexdigest(),
                "linked_failed_execution_id": TRAIN_LABEL_FAILED_EXECUTION_ID,
                "linked_failed_start_event_sha256": TRAIN_LABEL_FAILED_START_SHA256,
                "linked_failed_terminal_event_sha256": TRAIN_LABEL_FAILED_TERMINAL_SHA256,
                "linked_failed_receipt_sha256": TRAIN_LABEL_FAILED_RECEIPT_SHA256,
                "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
                "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
                "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
                "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
                "user_authorization_text": grant["user_authorization_text"],
                "user_authorization_timestamp_utc": grant["user_authorization_timestamp_utc"],
                "user_authorization_source_item_id": grant["user_authorization_source_item_id"],
            }
            event["budget_action_key"] = TRAIN_LABEL_RECOVERY_ACTION_KEY
            event["deterministic_metrics"].update(link)
            event["deterministic_metrics"]["budget_action_key"] = TRAIN_LABEL_RECOVERY_ACTION_KEY
            event["input_identity"].update(link)
            event["input_identity"]["budget_action_key"] = TRAIN_LABEL_RECOVERY_ACTION_KEY
            event["recovery_grant_id"] = TRAIN_LABEL_RECOVERY_GRANT_ID
            event["linked_failed_execution_id"] = TRAIN_LABEL_FAILED_EXECUTION_ID
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [item for item in appended if item.get("execution_id") == TRAIN_LABEL_RECOVERY_EXECUTION_ID and item.get("event_type") == "RUN_STARTED" and item.get("budget_action_key") == TRAIN_LABEL_RECOVERY_ACTION_KEY]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_TRAIN_LABEL_RECOVERY_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=RECOVERY_ACTION,
            action_key=TRAIN_LABEL_RECOVERY_ACTION_KEY,
            execution_id=TRAIN_LABEL_RECOVERY_EXECUTION_ID,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status="NOT_CHECKED",
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def _verify_linked_panel_header_r6_failure(
        self, events: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        """Verify the consumed R6 NameError attempt before granting R7 access."""
        path = PANEL_HEADER_R6_FAILED_RECEIPT_PATH
        if path.is_symlink() or not path.is_file() or sha256_file(path) != PANEL_HEADER_R6_FAILED_RECEIPT_SHA256:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(path.read_bytes(), "PANEL_HEADER_R6_RUNTIME_FAILURE_RECEIPT")
        summary = _panel_header_r6_runtime_failure_summary()
        error = receipt.get("error")
        read_accounting = receipt.get("read_accounting")
        control_reads = read_accounting.get("control_document_reads") if isinstance(read_accounting, Mapping) else None
        target_reads = read_accounting.get("target_artifact_reads") if isinstance(read_accounting, Mapping) else None
        actions = receipt.get("actions")
        lifecycle_receipt = receipt.get("registry_lifecycle")
        if (
            receipt.get("schema") != "F5_BREADTH1_R6_ADMISSION_RUNTIME_FAILURE_RECEIPT_V1"
            or receipt.get("status") != summary["status"]
            or receipt.get("route_id") != ROUTE_ID
            or receipt.get("execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
            or receipt.get("recovery_grant_id") != PANEL_HEADER_R6_RECOVERY_GRANT_ID
            or receipt.get("contract_sha256") != PANEL_HEADER_R6_CONTRACT_SHA256
            or receipt.get("input_binding_sha256") != PANEL_HEADER_R6_BINDING_SHA256
            or receipt.get("read_release_sha256") != PANEL_HEADER_R6_READ_RELEASE_SHA256
            or receipt.get("recovery_grant_sha256") != PANEL_HEADER_R6_GRANT_SHA256
            or receipt.get("target_data_opened") is not False
            or receipt.get("fit_predict_model_load_truth") is not False
            or receipt.get("lineage_status") != "LINEAGE_UNAVAILABLE"
            or not isinstance(error, Mapping)
            or error.get("type") != "NameError"
            or error.get("message") != "name '_valid_prior_panel_header_r5_failure' is not defined"
            or error.get("function") != "audit_real_input_admission"
            or error.get("line") != 410
            or not isinstance(read_accounting, Mapping)
            or read_accounting.get("control_file_count") != 2
            or read_accounting.get("control_bytes_read") != 39673
            or read_accounting.get("actual_read_receipt_persisted") is not False
            or read_accounting.get("formal_audit_counter_status") != "CANNOT_CONFIRM"
            or not isinstance(control_reads, list)
            or [(item.get("name"), item.get("sha256"), item.get("bytes_read"), item.get("target_data"))
                for item in control_reads if isinstance(item, Mapping)]
            != [
                ("input_admission_read_release", PANEL_HEADER_R6_READ_RELEASE_SHA256, 12595, False),
                ("input_binding", PANEL_HEADER_R6_BINDING_SHA256, 27078, False),
            ]
            or not isinstance(target_reads, Mapping)
            or target_reads.get("files_opened") != 0
            or target_reads.get("bytes_read") != 0
            or target_reads.get("status") != "NONE_BEFORE_EXCEPTION"
            or not isinstance(actions, Mapping)
            or actions.get("real_input_admission_budget_debit") != 1
            or any(actions.get(name) != 0 for name in (
                "real_fit_calls", "real_predict_calls", "real_model_load_calls", "real_truth_decode_calls",
            ))
            or not isinstance(lifecycle_receipt, Mapping)
            or lifecycle_receipt.get("start_event_sha256") != PANEL_HEADER_R6_FAILED_START_SHA256
            or lifecycle_receipt.get("terminal_event_sha256") != PANEL_HEADER_R6_FAILED_TERMINAL_SHA256
            or lifecycle_receipt.get("terminal_decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or lifecycle_receipt.get("terminal_stop_reason") != "NameError"
            or lifecycle_receipt.get("start_budget_action_debit") != 1
            or lifecycle_receipt.get("terminal_budget_action_debit") != 0
            or lifecycle_receipt.get("official_registry_append_receipt_persisted") is not False
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_RECEIPT_CONTENT_MISMATCH")
        prior_events = [event for event in events if event.get("execution_id") == PANEL_HEADER_R6_RECOVERY_EXECUTION_ID]
        by_type = {event.get("event_type"): event for event in prior_events}
        if len(prior_events) != 2 or set(by_type) != {"RUN_STARTED", "TERMINAL"}:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_LIFECYCLE_NOT_EXACT")
        start, terminal = by_type["RUN_STARTED"], by_type["TERMINAL"]
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_sha256") != PANEL_HEADER_R6_FAILED_START_SHA256
            or start.get("route_id") != ROUTE_ID
            or start.get("candidate_id") != CANDIDATE_ID
            or start.get("execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
            or start.get("contract_sha256") != PANEL_HEADER_R6_CONTRACT_SHA256
            or start.get("input_binding_sha256") != PANEL_HEADER_R6_BINDING_SHA256
            or start.get("decision") != "RUNNING"
            or start.get("budget_action") != RECOVERY_ACTION
            or start.get("budget_action_key") != PANEL_HEADER_R6_RECOVERY_ACTION_KEY
            or start.get("budget_action_debit") != 1
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("budget_release_sha256") != PANEL_HEADER_R6_READ_RELEASE_SHA256
            or start_metrics.get("recovery_grant_id") != PANEL_HEADER_R6_RECOVERY_GRANT_ID
            or start_metrics.get("recovery_grant_sha256") != PANEL_HEADER_R6_GRANT_SHA256
            or terminal.get("event_sha256") != PANEL_HEADER_R6_FAILED_TERMINAL_SHA256
            or terminal.get("route_id") != ROUTE_ID
            or terminal.get("candidate_id") != CANDIDATE_ID
            or terminal.get("execution_id") != PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
            or terminal.get("contract_sha256") != PANEL_HEADER_R6_CONTRACT_SHA256
            or terminal.get("input_binding_sha256") != PANEL_HEADER_R6_BINDING_SHA256
            or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or terminal.get("stop_reason") != "NameError"
            or terminal.get("started_event_sha256") != PANEL_HEADER_R6_FAILED_START_SHA256
            or not isinstance(terminal_metrics, Mapping)
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
            or terminal_metrics.get("real_fit_returned_count") != 0
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_LIFECYCLE_MISMATCH")
        if not _valid_prior_panel_header_r6_failure(summary):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_SUMMARY_INVALID")
        return summary

    def claim_parent_panel_date_recovery(self) -> ActionBudgetClaim:
        """Spend the single R7 recovery linked to the consumed R6 pre-read failure."""
        if not self.admission_only or self.synthetic:
            raise ActionBudgetError("PANEL_HEADER_RECOVERY_REQUIRES_PENDING_REAL_ADMISSION_ADAPTER")
        with self.official._locked():
            raw, events = self.official._read_validated()
            _, pending_binding = self._read_pending_admission_snapshot()
            grant_payload, grant = self._read_fixed_panel_header_recovery_grant()
            header_summary = self._verify_linked_panel_header_admission_failure(events)
            runtime_failure_summary = self._verify_linked_panel_header_runtime_failure(events)
            r5_failure_summary = self._verify_linked_panel_header_r5_failure(events)
            r6_failure_summary = self._verify_linked_panel_header_r6_failure(events)
            if pending_binding.get("prior_train_label_diagnostic") != _train_label_diagnostic_summary(
                _verify_train_label_diagnostic(events)
            ):
                raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_TRAIN_LABEL_DIAGNOSTIC_BINDING_MISMATCH")
            if pending_binding.get("prior_panel_header_diagnostic") != header_summary:
                raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_DIAGNOSTIC_BINDING_SUMMARY_MISMATCH")
            if pending_binding.get("prior_panel_header_runtime_failure") != runtime_failure_summary:
                raise ActionBudgetIdentityDrift("PANEL_HEADER_R4_ANCESTOR_RUNTIME_FAILURE_BINDING_SUMMARY_MISMATCH")
            if pending_binding.get("prior_panel_header_r5_failure") != r5_failure_summary:
                raise ActionBudgetIdentityDrift("PANEL_HEADER_R5_PRECALL_FAILURE_BINDING_SUMMARY_MISMATCH")
            if pending_binding.get("prior_panel_header_r6_failure") != r6_failure_summary:
                raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_BINDING_SUMMARY_MISMATCH")
            if grant.get("prior_panel_header_r6_failure") != r6_failure_summary:
                raise ActionBudgetIdentityDrift("PANEL_HEADER_R6_RUNTIME_FAILURE_GRANT_SUMMARY_MISMATCH")
            if any(
                event.get("budget_action_key") == PANEL_HEADER_RECOVERY_ACTION_KEY
                or event.get("execution_id") == PANEL_HEADER_RECOVERY_EXECUTION_ID
                for event in events
            ):
                raise ActionBudgetConsumed("fixed parent-panel date recovery grant/key already consumed")
            if any(
                event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action") in {"fit", "predict", "truth_decode"}
                for event in events
            ):
                raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_MUST_PRECEDE_MODEL_OR_TRUTH_ACTIONS")
            release_sha = _require_sha(grant.get("read_release_sha256"), "panel_header_read_release_sha256")
            event = self._action_event_spec(
                action=RECOVERY_ACTION,
                event_type="RUN_STARTED",
                execution_id=PANEL_HEADER_RECOVERY_EXECUTION_ID,
                arm=f"BREADTH1_ACTION_{RECOVERY_ACTION.upper()}",
                release_sha=release_sha,
                sealed_status="NOT_CHECKED",
                callback_entered=False,
                fit_call_entered=False,
                real_fit_returned_count=0,
                succeeded=None,
                error_type=None,
            )
            link = {
                "recovery_grant_id": PANEL_HEADER_RECOVERY_GRANT_ID,
                "recovery_grant_sha256": hashlib.sha256(grant_payload).hexdigest(),
                "linked_failed_execution_id": PANEL_HEADER_R6_RECOVERY_EXECUTION_ID,
                "linked_failed_start_event_sha256": PANEL_HEADER_R6_FAILED_START_SHA256,
                "linked_failed_terminal_event_sha256": PANEL_HEADER_R6_FAILED_TERMINAL_SHA256,
                "linked_failed_receipt_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
                "linked_r5_ancestor_execution_id": PANEL_HEADER_R5_RECOVERY_EXECUTION_ID,
                "linked_r5_ancestor_start_event_sha256": PANEL_HEADER_R5_FAILED_START_SHA256,
                "linked_r5_ancestor_terminal_event_sha256": PANEL_HEADER_R5_FAILED_TERMINAL_SHA256,
                "linked_r5_ancestor_receipt_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
                "linked_r3_parent_header_failure_execution_id": PANEL_HEADER_FAILED_EXECUTION_ID,
                "linked_r3_parent_header_failure_start_event_sha256": PANEL_HEADER_FAILED_START_SHA256,
                "linked_r3_parent_header_failure_terminal_event_sha256": PANEL_HEADER_FAILED_TERMINAL_SHA256,
                "linked_r3_parent_header_failure_receipt_sha256": PANEL_HEADER_FAILED_RECEIPT_SHA256,
                "panel_header_diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
                "panel_header_diagnostic_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
                "panel_header_diagnostic_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
                "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
                "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
                "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
                "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
                "prior_panel_header_runtime_failure_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
                "prior_panel_header_r5_failure_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
                "prior_panel_header_r6_failure_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
                "controller_reauthorization_source": grant["controller_reauthorization_source"],
                "controller_reauthorization_task_id": grant["controller_reauthorization_task_id"],
                "user_authorization_text": grant["user_authorization_text"],
                "user_authorization_timestamp_utc": grant["user_authorization_timestamp_utc"],
                "user_authorization_source_item_id": grant["user_authorization_source_item_id"],
            }
            event["budget_action_key"] = PANEL_HEADER_RECOVERY_ACTION_KEY
            event["deterministic_metrics"].update(link)
            event["deterministic_metrics"]["budget_action_key"] = PANEL_HEADER_RECOVERY_ACTION_KEY
            event["input_identity"].update(link)
            event["input_identity"]["budget_action_key"] = PANEL_HEADER_RECOVERY_ACTION_KEY
            event["recovery_grant_id"] = PANEL_HEADER_RECOVERY_GRANT_ID
            event["linked_failed_execution_id"] = PANEL_HEADER_R6_RECOVERY_EXECUTION_ID
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [
                item for item in appended
                if item.get("execution_id") == PANEL_HEADER_RECOVERY_EXECUTION_ID
                and item.get("event_type") == "RUN_STARTED"
                and item.get("budget_action_key") == PANEL_HEADER_RECOVERY_ACTION_KEY
            ]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_PANEL_HEADER_R7_RECOVERY_START_NOT_UNIQUE_AFTER_APPEND")
            start = matches[0]
        return ActionBudgetClaim(
            route_id=ROUTE_ID,
            candidate_id=CANDIDATE_ID,
            action=RECOVERY_ACTION,
            action_key=PANEL_HEADER_RECOVERY_ACTION_KEY,
            execution_id=PANEL_HEADER_RECOVERY_EXECUTION_ID,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=release_sha,
            sealed_status="NOT_CHECKED",
            registry_event_id=str(start["registry_event_id"]),
            registry_event_sha256=str(start["event_sha256"]),
        )

    def _read_fixed_panel_header_recovery_grant(self) -> tuple[bytes, Mapping[str, Any]]:
        path = PANEL_HEADER_RECOVERY_GRANT_PATH
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_GRANT_PATH_OR_SIZE_INVALID")
        payload = path.read_bytes()
        grant = _parse_json_object(payload, "PANEL_HEADER_RECOVERY_GRANT")
        expected = {
            "schema": "F5_BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_GRANT_V1",
            "status": "AUTHORIZED_ONE_SHOT",
            "grant_id": PANEL_HEADER_RECOVERY_GRANT_ID,
            "route_id": ROUTE_ID,
            "candidate_id": CANDIDATE_ID,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
            "budget_action_key": PANEL_HEADER_RECOVERY_ACTION_KEY,
            "execution_id": PANEL_HEADER_RECOVERY_EXECUTION_ID,
            "action_cap": ACTION_CAP,
            "failure_or_interruption_refund": False,
            "linked_failed_execution_id": PANEL_HEADER_R6_RECOVERY_EXECUTION_ID,
            "linked_failed_start_event_sha256": PANEL_HEADER_R6_FAILED_START_SHA256,
            "linked_failed_terminal_event_sha256": PANEL_HEADER_R6_FAILED_TERMINAL_SHA256,
            "linked_failed_receipt_path": str(PANEL_HEADER_R6_FAILED_RECEIPT_PATH),
            "linked_failed_receipt_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
            "linked_r5_ancestor_execution_id": PANEL_HEADER_R5_RECOVERY_EXECUTION_ID,
            "linked_r5_ancestor_start_event_sha256": PANEL_HEADER_R5_FAILED_START_SHA256,
            "linked_r5_ancestor_terminal_event_sha256": PANEL_HEADER_R5_FAILED_TERMINAL_SHA256,
            "linked_r5_ancestor_receipt_path": str(PANEL_HEADER_R5_FAILED_RECEIPT_PATH),
            "linked_r5_ancestor_receipt_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
            "linked_r3_parent_header_failure_execution_id": PANEL_HEADER_FAILED_EXECUTION_ID,
            "linked_r3_parent_header_failure_start_event_sha256": PANEL_HEADER_FAILED_START_SHA256,
            "linked_r3_parent_header_failure_terminal_event_sha256": PANEL_HEADER_FAILED_TERMINAL_SHA256,
            "linked_r3_parent_header_failure_receipt_path": str(PANEL_HEADER_FAILED_RECEIPT_PATH),
            "linked_r3_parent_header_failure_receipt_sha256": PANEL_HEADER_FAILED_RECEIPT_SHA256,
            "linked_r3_parent_header_registry_receipt_path": str(PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH),
            "linked_r3_parent_header_registry_receipt_sha256": PANEL_HEADER_FAILED_REGISTRY_RECEIPT_SHA256,
            "panel_header_diagnostic_receipt_path": str(PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH),
            "panel_header_diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
            "panel_header_diagnostic_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
            "panel_header_diagnostic_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
            "train_label_diagnostic_receipt_path": str(TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH),
            "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
            "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
            "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
            "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
            "prior_panel_header_runtime_failure": {
                "status": "R4_ACTION_FAILED",
                "execution_id": PANEL_HEADER_R4_RECOVERY_EXECUTION_ID,
                "recovery_grant_id": PANEL_HEADER_R4_RECOVERY_GRANT_ID,
                "contract_sha256": PANEL_HEADER_R4_CONTRACT_SHA256,
                "input_binding_sha256": PANEL_HEADER_R4_BINDING_SHA256,
                "read_release_sha256": PANEL_HEADER_R4_READ_RELEASE_SHA256,
                "failure_receipt_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
                "registry_start_event_sha256": PANEL_HEADER_R4_FAILED_START_SHA256,
                "registry_terminal_event_sha256": PANEL_HEADER_R4_FAILED_TERMINAL_SHA256,
                "error_type": "AttributeError",
                "failure_location": "_attach_parent_market_date:sessions.map(session_to_date)",
                "physical_input_file_count": None,
                "input_bytes_read": None,
                "input_read_counts_status": "CANNOT_CONFIRM",
                "real_fit_calls": 0,
                "real_predict_calls": 0,
                "real_model_load_calls": 0,
                "real_truth_decode_calls": 0,
            },
            "prior_panel_header_r5_failure": _panel_header_r5_precall_failure_summary(),
            "prior_panel_header_r6_failure": _panel_header_r6_runtime_failure_summary(),
            "read_release_path": str(PANEL_HEADER_RECOVERY_READ_RELEASE_PATH),
            "read_plan_path": str(PANEL_HEADER_RECOVERY_READ_PLAN_PATH),
            "recovery_output_path": PANEL_HEADER_RECOVERY_OUTPUT_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "preserved_prior_failure_terminal_path": PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "preserved_prior_failure_terminal_sha256": PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256,
            "prior_failure_action_debit": PANEL_HEADER_RECOVERY_PRIOR_FAILURE_ACTION_DEBIT,
            "user_authorization_text": "就按唯一键对齐修正，原数据和模型参数不变。允许再做一次针对性检查，键集合一致就按原 X_eval 行序映射，然后直接训练一次、完整预测一次、封存评价一次。不要再找历史证据、重复合成测试或反复问我确认。",
            "user_authorization_timestamp_utc": "2026-10-11T05:12:27.693554Z",
            "user_authorization_source_item_id": "230095514",
            "controller_reauthorization_source": "explicit parent follow-up authorizing one new linked admission recovery after the R6 control-validation NameError before frozen target data reads",
            "controller_reauthorization_task_id": "546019360",
            "authorized_scope": "one fixed linked admission recovery after the R6 recorded control-validation NameError before frozen target data reads; if PASS, continue the existing single-fit, single-full-predict, immutable-seal, and single sealed-evaluation authorization",
            "prohibited_actions_in_this_grant": ["repeat_diagnostic", "fit_retry", "predict_retry", "model_reload_retry", "truth_retry", "orders"],
        }
        if set(grant) != set(expected) | {"read_release_sha256", "read_plan_sha256"} or any(
            grant.get(name) != value for name, value in expected.items()
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_GRANT_IDENTITY_MISMATCH")
        prior_failure_terminal = PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH
        if (
            prior_failure_terminal.is_symlink()
            or not prior_failure_terminal.is_file()
            or prior_failure_terminal.stat().st_size > 64 * 1024
            or sha256_file(prior_failure_terminal) != PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_IDENTITY_MISMATCH")
        _require_sha(grant.get("read_release_sha256"), "panel_header_read_release_sha256")
        if (
            not PANEL_HEADER_RECOVERY_READ_PLAN_PATH.is_file()
            or PANEL_HEADER_RECOVERY_READ_PLAN_PATH.is_symlink()
            or PANEL_HEADER_RECOVERY_READ_PLAN_PATH.stat().st_size > 1024 * 1024
            or sha256_file(PANEL_HEADER_RECOVERY_READ_PLAN_PATH) != grant.get("read_plan_sha256")
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_READ_PLAN_IDENTITY_MISMATCH")
        plan = _parse_json_object(PANEL_HEADER_RECOVERY_READ_PLAN_PATH.read_bytes(), "PANEL_HEADER_RECOVERY_READ_PLAN")
        if (
            plan.get("contract_sha256") != self.contract_sha256
            or plan.get("pre_admission_binding_sha256") != self.input_binding_sha256
            or plan.get("recovery_grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
            or plan.get("recovery_execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        ):
            raise ActionBudgetIdentityDrift("PANEL_HEADER_RECOVERY_READ_PLAN_BINDING_MISMATCH")
        return payload, grant

    def _read_fixed_train_label_recovery_grant(self) -> tuple[bytes, Mapping[str, Any]]:
        path = TRAIN_LABEL_RECOVERY_GRANT_PATH
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_GRANT_PATH_OR_SIZE_INVALID")
        payload = path.read_bytes()
        grant = _parse_json_object(payload, "TRAIN_LABEL_RECOVERY_GRANT")
        expected = {
            "schema": "F5_BREADTH1_TRAIN_LABEL_RECOVERY_GRANT_V1",
            "status": "AUTHORIZED_ONE_SHOT",
            "grant_id": TRAIN_LABEL_RECOVERY_GRANT_ID,
            "route_id": ROUTE_ID,
            "candidate_id": CANDIDATE_ID,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
            "budget_action_key": TRAIN_LABEL_RECOVERY_ACTION_KEY,
            "execution_id": TRAIN_LABEL_RECOVERY_EXECUTION_ID,
            "action_cap": ACTION_CAP,
            "failure_or_interruption_refund": False,
            "linked_failed_execution_id": TRAIN_LABEL_FAILED_EXECUTION_ID,
            "linked_failed_start_event_sha256": TRAIN_LABEL_FAILED_START_SHA256,
            "linked_failed_terminal_event_sha256": TRAIN_LABEL_FAILED_TERMINAL_SHA256,
            "linked_failed_receipt_path": str(TRAIN_LABEL_FAILED_RECEIPT_PATH),
            "linked_failed_receipt_sha256": TRAIN_LABEL_FAILED_RECEIPT_SHA256,
            "diagnostic_receipt_path": str(TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH),
            "diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
            "diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
            "diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
            "diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
            "positive_count_semantics": "899 positive rows in the frozen y_train array; 183 distinct positive episodes",
            "positive_count_basis_status": "LINEAGE_LOOKUP_RESULT_REPORTED",
            "positive_count_basis_refs": [
                "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_MAP_CLASSIFICATION_RECOVERY01_RESULT.json:7",
                "full64_xendcg_episode_eq_r1_20260925/evidence/EPISODE_WEIGHT_BUILD_GLOBAL01_RESULT.json:38",
            ],
            "read_release_path": str(TRAIN_LABEL_RECOVERY_READ_RELEASE_PATH),
            "read_plan_path": str(TRAIN_LABEL_RECOVERY_READ_PLAN_PATH),
            "user_authorization_text": "直接查清训练标签到底是哪项不符，把实际类型、取值范围、正例数和 899 这个要求的依据列出来。如果是检查代码写错就最小修复，原数据和模型参数不变；检查通过后继续一次训练、完整预测和封存评价，不要再反复问我确认。",
            "user_authorization_timestamp_utc": "2026-10-11T07:03:27.364443Z",
            "user_authorization_source_item_id": "218502263",
            "authorized_scope": "one fixed post-diagnostic full input-admission read; if PASS, continue under the existing single-fit, single-full-predict, sealed-evaluation authorization",
            "prohibited_actions_in_this_grant": ["repeat_diagnostic", "fit", "predict", "model_load", "truth_decode", "orders"],
        }
        if set(grant) != set(expected) | {"read_release_sha256", "read_plan_sha256"}:
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_GRANT_FIELD_SET_MISMATCH")
        if any(grant.get(name) != value for name, value in expected.items()):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_GRANT_IDENTITY_MISMATCH")
        _require_sha(grant.get("read_release_sha256"), "train_label_read_release_sha256")
        if (
            not TRAIN_LABEL_RECOVERY_READ_PLAN_PATH.is_file()
            or TRAIN_LABEL_RECOVERY_READ_PLAN_PATH.is_symlink()
            or TRAIN_LABEL_RECOVERY_READ_PLAN_PATH.stat().st_size > 1024 * 1024
            or sha256_file(TRAIN_LABEL_RECOVERY_READ_PLAN_PATH) != grant.get("read_plan_sha256")
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_READ_PLAN_IDENTITY_MISMATCH")
        plan = _parse_json_object(TRAIN_LABEL_RECOVERY_READ_PLAN_PATH.read_bytes(), "TRAIN_LABEL_RECOVERY_READ_PLAN")
        if (
            plan.get("contract_sha256") != self.contract_sha256
            or plan.get("pre_admission_binding_sha256") != self.input_binding_sha256
            or plan.get("recovery_grant_id") != TRAIN_LABEL_RECOVERY_GRANT_ID
            or plan.get("recovery_execution_id") != TRAIN_LABEL_RECOVERY_EXECUTION_ID
        ):
            raise ActionBudgetIdentityDrift("TRAIN_LABEL_RECOVERY_READ_PLAN_BINDING_MISMATCH")
        return payload, grant

    def _read_fixed_admission_recovery_grant(self) -> tuple[bytes, Mapping[str, Any]]:
        path = RECOVERY_GRANT_PATH
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_GRANT_PATH_OR_SIZE_INVALID")
        payload = path.read_bytes()
        grant = _parse_json_object(payload, "INPUT_ADMISSION_RECOVERY_GRANT")
        expected = {
            "schema": "F5_BREADTH1_INPUT_ADMISSION_RECOVERY_GRANT_V1",
            "status": "AUTHORIZED_ONE_SHOT",
            "grant_id": RECOVERY_GRANT_ID,
            "route_id": ROUTE_ID,
            "candidate_id": CANDIDATE_ID,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
            "budget_action_key": RECOVERY_ACTION_KEY,
            "execution_id": RECOVERY_EXECUTION_ID,
            "action_cap": ACTION_CAP,
            "failure_or_interruption_refund": False,
            "linked_failed_execution_id": FAILED_ADMISSION_EXECUTION_ID,
            "linked_failed_start_event_id": FAILED_ADMISSION_START_ID,
            "linked_failed_start_event_sha256": FAILED_ADMISSION_START_SHA256,
            "linked_failed_terminal_event_id": FAILED_ADMISSION_TERMINAL_ID,
            "linked_failed_terminal_event_sha256": FAILED_ADMISSION_TERMINAL_SHA256,
            "failed_attempt_receipt_path": str(FAILED_ADMISSION_RECEIPT_PATH),
            "failed_attempt_receipt_sha256": FAILED_ADMISSION_RECEIPT_SHA256,
            "read_release_path": str(RECOVERY_READ_RELEASE_PATH),
            "read_plan_path": str(RECOVERY_READ_PLAN_PATH),
            "user_authorization_text": "允许修复后重新启动一次",
            "user_authorization_timestamp_utc": "2026-10-11T03:59:36.040635Z",
            "user_authorization_source_item_id": "741497767",
            "authorized_scope": "one recovery input-admission read check only; if PASS, continue under the original one-fit, one-predict, sealed-evaluation authorization",
            "prohibited_actions_in_this_grant": ["fit", "predict", "model_load", "truth_decode", "orders"],
        }
        if set(grant) != set(expected) | {"read_release_sha256", "read_plan_sha256"}:
            raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_GRANT_FIELD_SET_MISMATCH")
        if any(grant.get(name) != value for name, value in expected.items()):
            raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_GRANT_IDENTITY_MISMATCH")
        _require_sha(grant.get("read_release_sha256"), "recovery_read_release_sha256")
        if (
            not RECOVERY_READ_PLAN_PATH.is_file()
            or RECOVERY_READ_PLAN_PATH.is_symlink()
            or RECOVERY_READ_PLAN_PATH.stat().st_size > 1024 * 1024
            or sha256_file(RECOVERY_READ_PLAN_PATH) != grant.get("read_plan_sha256")
        ):
            raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_READ_PLAN_IDENTITY_MISMATCH")
        plan = _parse_json_object(RECOVERY_READ_PLAN_PATH.read_bytes(), "RECOVERY_ADMISSION_READ_PLAN")
        if (
            plan.get("contract_sha256") != self.contract_sha256
            or plan.get("pre_admission_binding_sha256") != self.input_binding_sha256
            or plan.get("recovery_grant_id") != RECOVERY_GRANT_ID
            or plan.get("recovery_execution_id") != RECOVERY_EXECUTION_ID
        ):
            raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_READ_PLAN_BINDING_MISMATCH")
        return payload, grant

    def _verify_linked_failed_admission_lifecycle(
        self,
        events: Sequence[Mapping[str, Any]],
    ) -> None:
        """Allow only the exact zero-target-read failure explicitly linked by recovery."""
        if (
            not FAILED_ADMISSION_RECEIPT_PATH.is_file()
            or FAILED_ADMISSION_RECEIPT_PATH.is_symlink()
            or sha256_file(FAILED_ADMISSION_RECEIPT_PATH) != FAILED_ADMISSION_RECEIPT_SHA256
        ):
            raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_RECEIPT_IDENTITY_MISMATCH")
        receipt = _parse_json_object(FAILED_ADMISSION_RECEIPT_PATH.read_bytes(), "FAILED_ADMISSION_ATTEMPT_RECEIPT")
        counts = receipt.get("actual_operation_counts")
        if (
            receipt.get("schema") != "F5_BREADTH1_INPUT_ADMISSION_ATTEMPT_RECEIPT_V1"
            or receipt.get("status") != "CANNOT_CONFIRM_ACTION_FAILED"
            or receipt.get("execution_id") != FAILED_ADMISSION_EXECUTION_ID
            or not isinstance(counts, Mapping)
            or counts.get("logical_admission_check_debit") != 1
            or counts.get("authorized_read_release_files") != 1
            or counts.get("authorized_read_release_bytes") != 6201
            or counts.get("target_input_files_opened") != 0
            or counts.get("target_input_bytes_read") != 0
            or counts.get("parent_panel_files_opened") != 0
            or counts.get("fit_calls") != 0
            or counts.get("predict_calls") != 0
            or counts.get("model_loads") != 0
            or counts.get("truth_decode_calls") != 0
        ):
            raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_RECEIPT_NOT_ZERO_TARGET_READ")
        lifecycle = [event for event in events if event.get("execution_id") == FAILED_ADMISSION_EXECUTION_ID]
        by_id = {event.get("registry_event_id"): event for event in lifecycle}
        expected_correction_ids = {
            f"{FAILED_ADMISSION_START_ID}_CORRECTION_RUNTIME_PYTHON",
            f"{FAILED_ADMISSION_TERMINAL_ID}_CORRECTION_RUNTIME_PYTHON",
        }
        if (
            len(lifecycle) != 4
            or set(by_id) != {FAILED_ADMISSION_START_ID, FAILED_ADMISSION_TERMINAL_ID, *expected_correction_ids}
        ):
            raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_LIFECYCLE_NOT_EXACT")
        start = by_id[FAILED_ADMISSION_START_ID]
        terminal = by_id[FAILED_ADMISSION_TERMINAL_ID]
        for event, event_id, digest in (
            (start, FAILED_ADMISSION_START_ID, FAILED_ADMISSION_START_SHA256),
            (terminal, FAILED_ADMISSION_TERMINAL_ID, FAILED_ADMISSION_TERMINAL_SHA256),
        ):
            if (
                event.get("registry_event_id") != event_id
                or event.get("event_sha256") != digest
                or event.get("route_id") != ROUTE_ID
                or event.get("candidate_id") != CANDIDATE_ID
                or event.get("experiment_id") != EXPERIMENT_ID
                or event.get("budget_action") != "input_admission"
                or event.get("budget_action_key") != f"{ROUTE_ID}:{CANDIDATE_ID}:input_admission"
            ):
                raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_EVENT_IDENTITY_MISMATCH")
        start_metrics = start.get("deterministic_metrics")
        terminal_metrics = terminal.get("deterministic_metrics")
        if (
            start.get("event_type") != "RUN_STARTED"
            or start.get("decision") != "RUNNING"
            or not isinstance(start_metrics, Mapping)
            or start_metrics.get("budget_action_debit") != 1
            or start_metrics.get("budget_release_sha256") != "3a52370f4e7e96b94d0a9bef8b031cc43d4daed7a5ab488a63a1ec216db15cc3"
            or terminal.get("event_type") != "TERMINAL"
            or terminal.get("started_event_sha256") != FAILED_ADMISSION_START_SHA256
            or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
            or terminal.get("stop_reason") != "NameError"
            or not isinstance(terminal_metrics, Mapping)
            or terminal_metrics.get("real_fit_budget_debit") != 0
            or terminal_metrics.get("fit_call_entered") is not False
            or terminal_metrics.get("real_fit_returned_count") != 0
        ):
            raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_TERMINAL_STATE_MISMATCH")
        expected_corrections = {
            f"{FAILED_ADMISSION_START_ID}_CORRECTION_RUNTIME_PYTHON": (
                FAILED_ADMISSION_START_ID, FAILED_ADMISSION_START_SHA256,
                "029d5e6a234bdfd7026c2351745a96aa622ecb7295652553d78060b977046e15",
            ),
            f"{FAILED_ADMISSION_TERMINAL_ID}_CORRECTION_RUNTIME_PYTHON": (
                FAILED_ADMISSION_TERMINAL_ID, FAILED_ADMISSION_TERMINAL_SHA256,
                "d30813d903ae2f9da30f648d34397535aea1f90267f9dda8581e1ac1ee72a63a",
            ),
        }
        for correction_id, (target_id, target_sha, correction_sha) in expected_corrections.items():
            correction = by_id[correction_id]
            metrics = correction.get("deterministic_metrics")
            if (
                correction.get("event_type") != "CORRECTION"
                or correction.get("event_sha256") != correction_sha
                or correction.get("route_id") != ROUTE_ID
                or correction.get("execution_id") != FAILED_ADMISSION_EXECUTION_ID
                or correction.get("candidate_id") != CANDIDATE_ID
                or not isinstance(metrics, Mapping)
                or metrics.get("corrects_registry_event_id") != target_id
                or metrics.get("corrects_event_sha256") != target_sha
                or metrics.get("corrected_fields") != ["runtime.python"]
            ):
                raise ActionBudgetIdentityDrift("LINKED_FAILED_ADMISSION_CORRECTION_IDENTITY_MISMATCH")

    def verify_real_action_context(self, release: VerifiedActionRelease) -> VerifiedActionContext:
        """Verify contract, input, release, and every bound code file from fresh bytes."""
        if self.synthetic:
            raise ActionBudgetError("REAL_ACTION_CONTEXT_REQUIRES_REAL_ADAPTER")
        contract, binding, admission_receipt_snapshot = self._read_contract_binding_snapshot()
        return self._read_real_action_context(
            release, contract=contract, binding=binding,
            admission_receipt_snapshot=admission_receipt_snapshot,
        )

    def _read_contract_binding_snapshot(
        self,
        *,
        registry_events: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], tuple[dict[str, Any], str, int] | None]:
        contract_path = Path(self.official.contract_path)
        binding_path = Path(self.official.input_binding_path)
        contract_bytes = contract_path.read_bytes()
        binding_bytes = binding_path.read_bytes()
        contract_sha = hashlib.sha256(contract_bytes).hexdigest()
        binding_sha = hashlib.sha256(binding_bytes).hexdigest()
        if contract_sha != self.contract_sha256:
            raise ActionBudgetIdentityDrift("CONTRACT_FILE_SHA_MISMATCH")
        if binding_sha != self.input_binding_sha256:
            raise ActionBudgetIdentityDrift("INPUT_BINDING_FILE_SHA_MISMATCH")
        contract = _parse_json_object(contract_bytes, "CONTRACT")
        binding = _parse_json_object(binding_bytes, "INPUT_BINDING")
        if contract.get("route_id") != ROUTE_ID or contract.get("candidate_id") != CANDIDATE_ID:
            raise ActionBudgetIdentityDrift("CONTRACT_ROUTE_OR_CANDIDATE_MISMATCH")
        if binding.get("route_id") != ROUTE_ID or binding.get("candidate_id") != CANDIDATE_ID:
            raise ActionBudgetIdentityDrift("INPUT_BINDING_ROUTE_OR_CANDIDATE_MISMATCH")
        if binding.get("contract_sha256") != self.contract_sha256:
            raise ActionBudgetIdentityDrift("INPUT_BINDING_CONTRACT_SHA_MISMATCH")
        _verify_contract_code_hashes(contract, binding)
        if self.synthetic:
            if binding.get("schema") != "F5_BREADTH1_SYNTHETIC_INPUT_BINDING_V1" or binding.get("synthetic_only") is not True:
                raise ActionBudgetIdentityDrift("SYNTHETIC_ACTION_ADAPTER_REQUIRES_SYNTHETIC_BINDING")
        else:
            if (
                binding.get("status") != "PASS"
                or binding.get("synthetic_only") is not False
                or not _is_sha(binding.get("input_admission_receipt_sha256"))
            ):
                raise ActionBudgetIdentityDrift("REAL_ACTION_ADAPTER_REQUIRES_PASSED_REAL_ADMISSION_BINDING")
            admission_receipt_snapshot = _load_verified_admission_receipt(
                binding, contract, contract_sha, binding_sha, self.official,
                registry_events=registry_events,
            )
            _require_admission_gated_real_action(
                contract,
                binding,
                admission_receipt_snapshot,
                contract_sha256=contract_sha,
                input_binding_sha256=binding_sha,
            )
        if self.synthetic:
            admission_receipt_snapshot = None
        self._verify_official_component_identity()
        return contract, binding, admission_receipt_snapshot

    def _read_pending_admission_snapshot(self) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        """Check the exact frozen draft identity without requiring a real admission PASS."""
        contract_bytes = Path(self.official.contract_path).read_bytes()
        binding_bytes = Path(self.official.input_binding_path).read_bytes()
        if hashlib.sha256(contract_bytes).hexdigest() != self.contract_sha256:
            raise ActionBudgetIdentityDrift("CONTRACT_FILE_SHA_MISMATCH")
        if hashlib.sha256(binding_bytes).hexdigest() != self.input_binding_sha256:
            raise ActionBudgetIdentityDrift("INPUT_BINDING_FILE_SHA_MISMATCH")
        contract = _parse_json_object(contract_bytes, "CONTRACT")
        binding = _parse_json_object(binding_bytes, "INPUT_BINDING")
        if (
            contract.get("route_id") != ROUTE_ID
            or contract.get("candidate_id") != CANDIDATE_ID
            or contract.get("status") != "DRAFT_NO_REAL_RUN"
            or contract.get("is_execution_contract") is not False
            or contract.get("real_release_issued") is not False
            or contract.get("synthetic_only") is not False
        ):
            raise ActionBudgetIdentityDrift("INPUT_ADMISSION_REQUIRES_EXACT_FROZEN_DRAFT_CONTRACT")
        if (
            binding.get("route_id") != ROUTE_ID
            or binding.get("candidate_id") != CANDIDATE_ID
            or binding.get("status") != "ADMISSION_PENDING"
            or binding.get("synthetic_only") is not False
            or binding.get("contract_sha256") != self.contract_sha256
            or binding.get("provenance_mode") != "FROZEN_INPUT_AS_OBSERVED_RESEARCH"
        ):
            raise ActionBudgetIdentityDrift("INPUT_ADMISSION_REQUIRES_EXACT_PENDING_INPUT_BINDING")
        source_binding = binding.get("source_binding")
        if not isinstance(source_binding, Mapping) or source_binding.get("status") != "LINEAGE_UNAVAILABLE":
            raise ActionBudgetIdentityDrift("INPUT_ADMISSION_SOURCE_LIMITATION_IDENTITY_MISMATCH")
        _verify_contract_code_hashes(contract, binding)
        self._verify_official_component_identity()
        return contract, binding

    def _verify_official_component_identity(self) -> None:
        guard_path = OFFICIAL_GUARD_DIR / "execution_guard_core.py"
        adapter_path = OFFICIAL_GUARD_DIR / "registry_adapter.py"
        for filename, path in (
            ("execution_guard_core.py", guard_path),
            ("registry_adapter.py", adapter_path),
            ("build_experiment_registry_backfill_20260821.py", Path(self.official.builder_path)),
            ("validate_experiment_registry_append_compatibility_v1.py", Path(self.official.validator_path)),
        ):
            expected_sha = OFFICIAL_COMPONENT_SHA256[filename]
            if not path.is_file() or sha256_file(path) != expected_sha:
                raise OfficialActionCapabilityMissing(f"OFFICIAL_COMPONENT_SHA_MISMATCH:{filename}")
        if Path(self.official.builder_path).resolve() != OFFICIAL_BUILDER_PATH.resolve():
            raise OfficialActionCapabilityMissing("OFFICIAL_BUILDER_PATH_MISMATCH")
        if Path(self.official.validator_path).resolve() != OFFICIAL_VALIDATOR_PATH.resolve():
            raise OfficialActionCapabilityMissing("OFFICIAL_VALIDATOR_PATH_MISMATCH")

    def _read_real_action_context(
        self,
        release: VerifiedActionRelease,
        *,
        contract: Mapping[str, Any],
        binding: Mapping[str, Any],
        admission_receipt_snapshot: tuple[dict[str, Any], str, int] | None = None,
    ) -> VerifiedActionContext:
        payload = Path(release.path).read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != release.expected_sha256:
            raise ActionBudgetIdentityDrift("REAL_RELEASE_SHA_MISMATCH")
        value = _decode_verified_action_release(
            payload,
            release_sha256=actual,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            candidate_id=CANDIDATE_ID,
            contract_value=contract,
            input_binding_value=binding,
            admission_receipt_snapshot=admission_receipt_snapshot,
        )
        if value.get("input_admission_receipt_sha256") != binding.get("input_admission_receipt_sha256"):
            raise ActionBudgetIdentityDrift("REAL_RELEASE_ADMISSION_RECEIPT_BINDING_MISMATCH")
        if admission_receipt_snapshot is None:
            admission_receipt_snapshot = _load_verified_admission_receipt(
                binding, contract, self.contract_sha256, self.input_binding_sha256,
                self.official,
            )
        admission_receipt, admission_receipt_sha, admission_receipt_bytes = admission_receipt_snapshot
        if value.get("action_scope") == "SEALED_TRUTH_EVALUATION":
            _verify_prediction_seal_snapshot(value, contract_sha256=self.contract_sha256, input_binding_sha256=self.input_binding_sha256)
        return VerifiedActionContext(
            contract_value=dict(contract),
            input_binding_value=dict(binding),
            release_value=value,
            contract_sha256=self.contract_sha256,
            input_binding_sha256=self.input_binding_sha256,
            release_sha256=actual,
            input_admission_receipt_value=admission_receipt,
            input_admission_receipt_sha256=admission_receipt_sha,
            input_admission_receipt_bytes=admission_receipt_bytes,
        )

    def _verify_action_boundary(
        self,
        claim: ActionBudgetClaim,
        release: VerifiedActionRelease | None,
    ) -> VerifiedActionContext | None:
        self._validate_claim(claim)
        contract, binding, admission_receipt_snapshot = self._read_contract_binding_snapshot()
        if self.synthetic:
            if release is not None:
                raise ActionBudgetIdentityDrift("SYNTHETIC_ACTION_BOUNDARY_RECEIVED_REAL_RELEASE")
            return None
        if release is None:
            raise ActionBudgetIdentityDrift("REAL_ACTION_BOUNDARY_RELEASE_DISAPPEARED")
        context = self._read_real_action_context(
            release, contract=contract, binding=binding,
            admission_receipt_snapshot=admission_receipt_snapshot,
        )
        if (
            context.contract_sha256 != claim.contract_sha256
            or context.input_binding_sha256 != claim.input_binding_sha256
            or context.release_sha256 != claim.release_sha256
        ):
            raise ActionBudgetIdentityDrift("ACTION_BOUNDARY_IDENTITY_DIFFERS_FROM_DURABLE_CLAIM")
        return context

    def terminalize(
        self,
        claim: ActionBudgetClaim,
        *,
        succeeded: bool,
        callback_entered: bool,
        fit_call_entered: bool = False,
        error_type: str | None = None,
        terminal_artifact_paths: Sequence[Path] = (),
    ) -> str:
        if type(succeeded) is not bool or type(callback_entered) is not bool or type(fit_call_entered) is not bool:
            raise ActionBudgetError("terminal action flags must be bool")
        self._validate_claim(claim)
        if claim.action != "fit" and fit_call_entered:
            raise ActionBudgetError("only the fit action may enter fit")
        if claim.action == "fit" and succeeded and not fit_call_entered:
            raise ActionBudgetError("successful fit action terminal requires fit-call entry")
        if succeeded and not callback_entered:
            raise ActionBudgetError("successful action terminal requires callback entry")
        returned_fit_count = int(claim.action == "fit" and succeeded)
        action = claim.action
        with self.official._locked():
            raw, events = self.official._read_validated()
            starts = [
                event for event in events
                if event.get("event_type") == "RUN_STARTED"
                and event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action_key") == claim.action_key
            ]
            terminals = [
                event for event in events
                if event.get("event_type") == "TERMINAL"
                and event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
                and event.get("budget_action_key") == claim.action_key
            ]
            if len(starts) != 1 or terminals:
                raise ActionBudgetConsumed("action terminal requires one unmatched official start")
            start = starts[0]
            for field, expected in (
                ("execution_id", claim.execution_id),
                ("registry_event_id", claim.registry_event_id),
                ("event_sha256", claim.registry_event_sha256),
                ("contract_sha256", claim.contract_sha256),
                ("input_binding_sha256", claim.input_binding_sha256),
                ("arm", f"BREADTH1_ACTION_{action.upper()}"),
            ):
                if start.get(field) != expected:
                    raise ActionBudgetIdentityDrift(f"ACTION_START_{field.upper()}_MISMATCH")
            if action in {"input_admission", RECOVERY_ACTION}:
                start_metrics = start.get("deterministic_metrics")
                if (
                    not isinstance(start_metrics, Mapping)
                    or start_metrics.get("budget_release_sha256") != claim.release_sha256
                    or start.get("budget_action_debit") != 1
                ):
                    raise ActionBudgetIdentityDrift("INPUT_ADMISSION_START_RELEASE_OR_DEBIT_MISMATCH")
                if action == RECOVERY_ACTION:
                    expected_link = (
                        {"recovery_grant_id": PANEL_HEADER_RECOVERY_GRANT_ID,
                         "linked_failed_execution_id": PANEL_HEADER_R6_RECOVERY_EXECUTION_ID,
                         "linked_failed_start_event_sha256": PANEL_HEADER_R6_FAILED_START_SHA256,
                         "linked_failed_terminal_event_sha256": PANEL_HEADER_R6_FAILED_TERMINAL_SHA256,
                         "linked_failed_receipt_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
                         "linked_r5_ancestor_execution_id": PANEL_HEADER_R5_RECOVERY_EXECUTION_ID,
                         "linked_r5_ancestor_start_event_sha256": PANEL_HEADER_R5_FAILED_START_SHA256,
                         "linked_r5_ancestor_terminal_event_sha256": PANEL_HEADER_R5_FAILED_TERMINAL_SHA256,
                         "linked_r5_ancestor_receipt_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
                         "linked_r3_parent_header_failure_execution_id": PANEL_HEADER_FAILED_EXECUTION_ID,
                         "linked_r3_parent_header_failure_start_event_sha256": PANEL_HEADER_FAILED_START_SHA256,
                         "linked_r3_parent_header_failure_terminal_event_sha256": PANEL_HEADER_FAILED_TERMINAL_SHA256,
                         "linked_r3_parent_header_failure_receipt_sha256": PANEL_HEADER_FAILED_RECEIPT_SHA256,
                         "panel_header_diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
                         "panel_header_diagnostic_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
                         "panel_header_diagnostic_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
                         "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
                         "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
                         "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
                         "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256,
                         "prior_panel_header_runtime_failure_sha256": PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_SHA256,
                         "prior_panel_header_r5_failure_sha256": PANEL_HEADER_R5_FAILED_RECEIPT_SHA256,
                         "prior_panel_header_r6_failure_sha256": PANEL_HEADER_R6_FAILED_RECEIPT_SHA256,
                         "controller_reauthorization_source": "explicit parent follow-up authorizing one new linked admission recovery after the R6 control-validation NameError before frozen target data reads",
                         "controller_reauthorization_task_id": "546019360"}
                        if claim.action_key == PANEL_HEADER_RECOVERY_ACTION_KEY else
                        {"recovery_grant_id": RECOVERY_GRANT_ID,
                         "linked_failed_execution_id": FAILED_ADMISSION_EXECUTION_ID,
                         "linked_failed_start_event_sha256": FAILED_ADMISSION_START_SHA256,
                         "linked_failed_terminal_event_sha256": FAILED_ADMISSION_TERMINAL_SHA256}
                        if claim.action_key == RECOVERY_ACTION_KEY else
                        {"recovery_grant_id": KEY_ALIGNMENT_RECOVERY_GRANT_ID,
                         "linked_failed_execution_id": KEY_ALIGNMENT_FAILED_EXECUTION_ID,
                         "linked_failed_start_event_sha256": KEY_ALIGNMENT_FAILED_START_SHA256,
                         "linked_failed_terminal_event_sha256": KEY_ALIGNMENT_FAILED_TERMINAL_SHA256,
                         "linked_failed_receipt_sha256": KEY_ALIGNMENT_FAILED_RECEIPT_SHA256}
                        if claim.action_key == KEY_ALIGNMENT_ACTION_KEY else
                        {"recovery_grant_id": TRAIN_LABEL_RECOVERY_GRANT_ID,
                         "linked_failed_execution_id": TRAIN_LABEL_FAILED_EXECUTION_ID,
                         "linked_failed_start_event_sha256": TRAIN_LABEL_FAILED_START_SHA256,
                         "linked_failed_terminal_event_sha256": TRAIN_LABEL_FAILED_TERMINAL_SHA256,
                         "linked_failed_receipt_sha256": TRAIN_LABEL_FAILED_RECEIPT_SHA256,
                         "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
                         "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
                         "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
                         "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256}
                        if claim.action_key == TRAIN_LABEL_RECOVERY_ACTION_KEY else
                        {"recovery_grant_id": PANEL_HEADER_RECOVERY_GRANT_ID,
                         "linked_failed_execution_id": PANEL_HEADER_FAILED_EXECUTION_ID,
                         "linked_failed_start_event_sha256": PANEL_HEADER_FAILED_START_SHA256,
                         "linked_failed_terminal_event_sha256": PANEL_HEADER_FAILED_TERMINAL_SHA256,
                         "linked_failed_receipt_sha256": PANEL_HEADER_FAILED_RECEIPT_SHA256,
                         "panel_header_diagnostic_receipt_sha256": PANEL_HEADER_DIAGNOSTIC_RECEIPT_SHA256,
                         "panel_header_diagnostic_start_event_sha256": PANEL_HEADER_DIAGNOSTIC_START_SHA256,
                         "panel_header_diagnostic_terminal_event_sha256": PANEL_HEADER_DIAGNOSTIC_TERMINAL_SHA256,
                         "train_label_diagnostic_receipt_sha256": TRAIN_LABEL_DIAGNOSTIC_RECEIPT_SHA256,
                         "train_label_diagnostic_start_event_sha256": TRAIN_LABEL_DIAGNOSTIC_START_SHA256,
                         "train_label_diagnostic_terminal_event_sha256": TRAIN_LABEL_DIAGNOSTIC_TERMINAL_SHA256,
                         "train_label_diagnostic_correction_event_sha256": TRAIN_LABEL_DIAGNOSTIC_CORRECTION_SHA256}
                    )
                    if any(start_metrics.get(key) != value for key, value in expected_link.items()):
                        raise ActionBudgetIdentityDrift("RECOVERY_ADMISSION_START_GRANT_LINK_MISMATCH")
            event = self._action_event_spec(
                action=action,
                event_type="TERMINAL",
                execution_id=claim.execution_id,
                arm=f"BREADTH1_ACTION_{action.upper()}",
                release_sha=claim.release_sha256,
                sealed_status=claim.sealed_status,
                callback_entered=callback_entered,
                fit_call_entered=fit_call_entered,
                real_fit_returned_count=returned_fit_count,
                succeeded=succeeded,
                error_type=error_type,
                terminal_artifact_paths=terminal_artifact_paths,
            )
            event["budget_action_key"] = claim.action_key
            event["deterministic_metrics"]["budget_action_key"] = claim.action_key
            event["input_identity"]["budget_action_key"] = claim.action_key
            if action == RECOVERY_ACTION:
                start_metrics = start.get("deterministic_metrics")
                assert isinstance(start_metrics, Mapping)
                for field in (
                    "recovery_grant_id", "recovery_grant_sha256", "linked_failed_execution_id",
                    "linked_failed_start_event_sha256", "linked_failed_terminal_event_sha256",
                    "linked_r5_ancestor_execution_id", "linked_r5_ancestor_start_event_sha256",
                    "linked_r5_ancestor_terminal_event_sha256", "linked_r5_ancestor_receipt_sha256",
                    "train_label_diagnostic_receipt_sha256", "train_label_diagnostic_start_event_sha256",
                    "train_label_diagnostic_terminal_event_sha256", "train_label_diagnostic_correction_event_sha256",
                    "panel_header_diagnostic_receipt_sha256", "panel_header_diagnostic_start_event_sha256",
                    "panel_header_diagnostic_terminal_event_sha256",
                    "linked_r3_parent_header_failure_execution_id",
                    "linked_r3_parent_header_failure_start_event_sha256",
                    "linked_r3_parent_header_failure_terminal_event_sha256",
                    "linked_r3_parent_header_failure_receipt_sha256",
                    "prior_panel_header_runtime_failure_sha256",
                    "prior_panel_header_r5_failure_sha256",
                    "prior_panel_header_r6_failure_sha256",
                    "controller_reauthorization_source", "controller_reauthorization_task_id",
                    "user_authorization_text", "user_authorization_timestamp_utc",
                    "user_authorization_source_item_id",
                ):
                    if field in start_metrics:
                        event["deterministic_metrics"][field] = start_metrics[field]
                        event["input_identity"][field] = start_metrics[field]
                if "linked_failed_receipt_sha256" in start_metrics:
                    event["deterministic_metrics"]["linked_failed_receipt_sha256"] = start_metrics["linked_failed_receipt_sha256"]
                    event["input_identity"]["linked_failed_receipt_sha256"] = start_metrics["linked_failed_receipt_sha256"]
                event["recovery_grant_id"] = start_metrics["recovery_grant_id"]
                event["linked_failed_execution_id"] = start_metrics["linked_failed_execution_id"]
            event["started_event_sha256"] = claim.registry_event_sha256
            self.official._append_unlocked(raw, events, event)
            _, appended = self.official._read_validated()
            matches = [
                item for item in appended
                if item.get("execution_id") == claim.execution_id
                and item.get("event_type") == "TERMINAL"
                and item.get("budget_action_key") == claim.action_key
            ]
            if len(matches) != 1:
                raise ActionBudgetError("OFFICIAL_ACTION_TERMINAL_NOT_UNIQUE_AFTER_APPEND")
            return str(matches[0]["event_sha256"])

    def _action_event_spec(
        self,
        *,
        action: str,
        event_type: str,
        execution_id: str,
        arm: str,
        release_sha: str,
        sealed_status: str,
        callback_entered: bool,
        fit_call_entered: bool,
        real_fit_returned_count: int,
        succeeded: bool | None,
        error_type: str | None,
        terminal_artifact_paths: Sequence[Path] = (),
    ) -> dict[str, Any]:
        is_start = event_type == "RUN_STARTED"
        action_key = RECOVERY_ACTION_KEY if action == RECOVERY_ACTION else f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
        if self.synthetic:
            execution_kind = f"SYNTHETIC_{action.upper()}_ENGINEERING_CANARY"
        else:
            execution_kind = {
                "input_admission": "NO_FIT_ENGINEERING_CANARY",
                RECOVERY_ACTION: "NO_FIT_ENGINEERING_CANARY",
                "fit": "REAL_FIT",
                "predict": "REAL_PREDICT",
                "truth_decode": "REAL_TRUTH_DECODE",
            }[action]
        fit_debit = 1 if action == "fit" else 0
        occurred_field = "started_at" if is_start else "finished_at"
        now = _utc_now()
        guard_event = {
            "event_type": event_type,
            "experiment_id": EXPERIMENT_ID,
            "execution_id": execution_id,
            "arm": arm,
            occurred_field: now,
            "execution_kind": execution_kind,
            "planned_real_fit_count": fit_debit,
            "real_fit_budget_debit": fit_debit,
            "fit_call_entered": fit_call_entered,
            "real_fit_returned_count": real_fit_returned_count,
            "terminal_status": (
                "RUNNING" if is_start else
                ("ACTION_COMPLETED_RESEARCH_ONLY" if succeeded and not self.synthetic else
                 "ENGINEERING_CANARY_ONLY" if succeeded else "FAILED_ACTION_CONSUMED")
            ),
            "error_type": error_type,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
        }
        spec = self.official._event_spec(guard_event, event_type=event_type)
        existing_artifacts = [Path(path) for path in self.official.artifact_paths]
        extra_artifacts = [Path(path) for path in terminal_artifact_paths]
        artifact_paths = [self.official.contract_path, *existing_artifacts, *extra_artifacts]
        artifact_paths = [Path(path).resolve() for path in artifact_paths if path is not None]
        spec.update({
            "registry_event_id": f"{execution_id}_{event_type}",
            "execution_id": execution_id,
            "experiment_id": EXPERIMENT_ID,
            "arm": arm,
            "track_id": self.official.event_profile["track_id"],
            "route_id": ROUTE_ID,
            "registration_mode": "LIVE_EXECUTION",
            "stage": f"BREADTH1_{action.upper()}_{'STARTED' if is_start else 'TERMINAL'}",
            "event_type": event_type,
            "occurred_at": now,
            "occurred_at_reason": f"BREADTH1_{action.upper()}_ACTION_LIFECYCLE_UTC",
            "contract_sha256": self.contract_sha256,
            "input_sha256": self.input_binding_sha256,
            "input_binding_sha256": self.input_binding_sha256,
            "code_sha256": sha256_file(Path(__file__).resolve()),
            "config_sha256": self.contract_sha256,
            "candidate_id": CANDIDATE_ID,
            "budget_action": action,
            "budget_action_key": action_key,
            "budget_action_cap": ACTION_CAP,
            "budget_action_debit": 1 if is_start else 0,
            "truth_access": _truth_access(
                action,
                succeeded=succeeded,
                callback_entered=callback_entered,
                synthetic=self.synthetic,
                is_start=is_start,
            ),
            "sealed_status": (
                "NOT_CHECKED" if is_start and action in {"input_admission", RECOVERY_ACTION} else
                "NOT_ENTERED" if is_start else sealed_status
            ),
            "artifact_paths": [str(path) for path in artifact_paths],
            "artifact_path": [str(path) for path in artifact_paths],
            "signal_date_range": {"count": 0, "scope": "BREADTH1_ACTION_BOUND_BY_FROZEN_INPUT"},
            "target_date_range": {"count": 0, "scope": "BREADTH1_ACTION_BOUND_BY_FROZEN_INPUT"},
            "decision": (
                "RUNNING" if is_start else
                "ENGINEERING_CANARY_ONLY" if succeeded and (self.synthetic or action in {"input_admission", RECOVERY_ACTION}) else
                "ACTION_COMPLETED_RESEARCH_ONLY" if succeeded else "CANNOT_CONFIRM_ACTION_FAILED"
            ),
            "stop_reason": "NONE" if is_start or succeeded else str(error_type or "ACTION_FAILED"),
            "evidence_level": "ENGINEERING_CANARY_ONLY",
            "deterministic_metrics": {
                "truth_positive_denominator": None,
                "selection_slots": None,
                "execution_kind": execution_kind,
                "planned_real_fit_count": fit_debit,
                "real_fit_budget_debit": fit_debit,
                "fit_call_entered": fit_call_entered,
                "real_fit_returned_count": real_fit_returned_count,
                "candidate_id": CANDIDATE_ID,
                "budget_action": action,
                "budget_action_key": action_key,
                "budget_action_cap": ACTION_CAP,
                "budget_action_debit": 1 if is_start else 0,
                "action_callback_entered": callback_entered,
                "action_callback_returned": bool(succeeded),
                "budget_release_sha256": release_sha,
                "null_reasons": {
                    "deterministic_metrics.truth_positive_denominator": "ACTION_BUDGET_LIFECYCLE_NOT_EVALUATION",
                    "deterministic_metrics.selection_slots": "ACTION_BUDGET_LIFECYCLE_NOT_SELECTION",
                },
            },
            "input_identity": {
                "experiment_id": EXPERIMENT_ID,
                "candidate_id": CANDIDATE_ID,
                "budget_action": action,
                "budget_action_key": action_key,
                "contract_sha256": self.contract_sha256,
                "input_binding_sha256": self.input_binding_sha256,
                "null_reasons": {},
            },
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
        # Keep the complete action identity in both the source event and its
        # materialized metrics so a lock-held replay check does not rely on a
        # sidecar or the execution ID.
        if not is_start:
            spec["deterministic_metrics"]["sealed_status"] = sealed_status
        if action == RECOVERY_ACTION:
            recovery_link = {
                "recovery_grant_id": RECOVERY_GRANT_ID,
                "linked_failed_execution_id": FAILED_ADMISSION_EXECUTION_ID,
                "linked_failed_start_event_sha256": FAILED_ADMISSION_START_SHA256,
                "linked_failed_terminal_event_sha256": FAILED_ADMISSION_TERMINAL_SHA256,
            }
            spec["deterministic_metrics"].update(recovery_link)
            spec["input_identity"].update(recovery_link)
            spec["recovery_grant_id"] = RECOVERY_GRANT_ID
            spec["linked_failed_execution_id"] = FAILED_ADMISSION_EXECUTION_ID
        return spec

    def _validate_claim(self, claim: ActionBudgetClaim) -> None:
        if not isinstance(claim, ActionBudgetClaim):
            raise ActionBudgetError("action claim must be the adapter's frozen claim")
        action = _validate_action(claim.action)
        if action == RECOVERY_ACTION:
            identities = {
                (RECOVERY_ACTION_KEY, RECOVERY_EXECUTION_ID),
                (KEY_ALIGNMENT_ACTION_KEY, KEY_ALIGNMENT_EXECUTION_ID),
                (TRAIN_LABEL_RECOVERY_ACTION_KEY, TRAIN_LABEL_RECOVERY_EXECUTION_ID),
                (PANEL_HEADER_RECOVERY_ACTION_KEY, PANEL_HEADER_RECOVERY_EXECUTION_ID),
            }
            if (claim.action_key, claim.execution_id) not in identities:
                raise ActionBudgetIdentityDrift("ACTION_CLAIM_RECOVERY_IDENTITY_MISMATCH")
            action_key, execution_id = claim.action_key, claim.execution_id
        else:
            action_key = f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
            execution_id = f"{ROUTE_ID}_{CANDIDATE_ID}_{action.upper()}_ONE_SHOT"
        expected = {
            "route_id": ROUTE_ID,
            "candidate_id": CANDIDATE_ID,
            "action_key": action_key,
            "execution_id": execution_id,
            "contract_sha256": self.contract_sha256,
            "input_binding_sha256": self.input_binding_sha256,
        }
        for field, value in expected.items():
            if getattr(claim, field) != value:
                raise ActionBudgetIdentityDrift(f"ACTION_CLAIM_{field.upper()}_MISMATCH")

    def _validate_bound_adapter(self) -> None:
        required_methods = ("_locked", "_read_validated", "_append_unlocked", "_event_spec")
        missing = [name for name in required_methods if not callable(getattr(self.official, name, None))]
        if missing:
            raise OfficialActionCapabilityMissing(f"official adapter is missing narrow locked methods: {missing}")
        if not getattr(self.official, "contract_path", None) or not getattr(self.official, "input_binding_path", None):
            raise OfficialActionCapabilityMissing("official adapter must bind candidate contract and input")
        if self.official.event_profile.get("route_id") != ROUTE_ID or self.official.event_profile.get("track_id") != "HK_SPIKE_F5_FIXED_TOP20_RESEARCH":
            raise ActionBudgetIdentityDrift("OFFICIAL_ADAPTER_ROUTE_OR_TRACK_MISMATCH")
        expected_registry = OFFICIAL_REGISTRY_PATH.resolve()
        if self.synthetic:
            self._read_contract_binding_snapshot()
            if self.registry_path == expected_registry or not _is_relative_to(self.registry_path, BATCH_ROOT.resolve()):
                raise ActionBudgetIdentityDrift("SYNTHETIC_REGISTRY_MUST_BE_A_BATCH_FIXTURE")
        else:
            if self.registry_path != expected_registry:
                raise ActionBudgetIdentityDrift("REAL_ACTION_ADAPTER_MUST_USE_OFFICIAL_REGISTRY_PATH")
            if self.admission_only:
                self._read_pending_admission_snapshot()
            else:
                self._read_contract_binding_snapshot()


def _real_fit_debit_total(events: Sequence[Mapping[str, Any]], experiment_id: str) -> int:
    total = 0
    for event in events:
        if event.get("experiment_id") != experiment_id or event.get("event_type") != "RUN_STARTED":
            continue
        metrics = event.get("deterministic_metrics")
        debit = metrics.get("real_fit_budget_debit") if isinstance(metrics, Mapping) else None
        if debit is None:
            debit = event.get("real_fit_budget_debit", 0)
        if isinstance(debit, bool) or not isinstance(debit, int) or debit not in (0, 1):
            raise ActionBudgetError("OFFICIAL_REGISTRY_REAL_FIT_DEBIT_INVALID")
        total += debit
    return total


def _verify_prior_real_action_receipts(
    events: Sequence[Mapping[str, Any]],
    release: Mapping[str, Any] | None,
) -> None:
    if not isinstance(release, Mapping):
        raise ActionBudgetError("REAL_TRUTH_RELEASE_REQUIRED")
    if release.get("action_scope") != "SEALED_TRUTH_EVALUATION":
        raise ActionBudgetError("REAL_TRUTH_RELEASE_SCOPE_INVALID")
    prior_terminals = release.get("prior_action_terminals")
    if not isinstance(prior_terminals, Mapping):
        raise ActionBudgetError("REAL_TRUTH_RELEASE_PRIOR_TERMINALS_MISSING")
    terminal_events: dict[str, Mapping[str, Any]] = {}
    for action in ("fit", "predict"):
        action_key = f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
        starts = [
            event for event in events
            if event.get("route_id") == ROUTE_ID
            and event.get("candidate_id") == CANDIDATE_ID
            and event.get("budget_action_key") == action_key
            and event.get("event_type") == "RUN_STARTED"
        ]
        terminals = [
            event for event in events
            if event.get("route_id") == ROUTE_ID
            and event.get("candidate_id") == CANDIDATE_ID
            and event.get("budget_action_key") == action_key
            and event.get("event_type") == "TERMINAL"
        ]
        if len(starts) != 1 or len(terminals) != 1:
            raise ActionBudgetError(f"REAL_TRUTH_REQUIRES_ONE_COMPLETED_{action.upper()}_ACTION")
        terminal = terminals[0]
        if (
            terminal.get("execution_id") != starts[0].get("execution_id")
            or (
                terminal.get("started_event_sha256") is not None
                and terminal.get("started_event_sha256") != starts[0].get("event_sha256")
            )
            or terminal.get("decision") != "ACTION_COMPLETED_RESEARCH_ONLY"
            or terminal.get("truth_access") != "NOT_READ"
        ):
            raise ActionBudgetIdentityDrift(f"REAL_TRUTH_PRIOR_{action.upper()}_ACTION_NOT_SUCCESSFUL")
        if prior_terminals.get(action) != terminal.get("event_sha256"):
            raise ActionBudgetIdentityDrift(f"REAL_TRUTH_PRIOR_{action.upper()}_TERMINAL_RECEIPT_MISMATCH")
        terminal_events[action] = terminal

    candidate_artifacts = release.get("candidate_artifacts")
    if not isinstance(candidate_artifacts, Mapping):
        raise ActionBudgetError("REAL_TRUTH_CANDIDATE_SEAL_RECEIPT_MISSING")
    terminal = terminal_events["predict"]
    artifact_paths = terminal.get("artifact_path")
    artifact_sha256 = terminal.get("artifact_sha256")
    if not isinstance(artifact_paths, list) or not isinstance(artifact_sha256, list) or len(artifact_paths) != len(artifact_sha256):
        raise ActionBudgetError("REAL_PREDICT_TERMINAL_ARTIFACT_RECEIPT_INVALID")
    recorded = {
        Path(path).resolve(): digest
        for path, digest in zip(artifact_paths, artifact_sha256)
        if isinstance(path, str) and _is_sha(digest)
    }
    for name in ("scoreable_prediction", "candidate_scores", "candidate_top3"):
        item = candidate_artifacts.get(name)
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or not _is_sha(item.get("sha256")):
            raise ActionBudgetError(f"REAL_TRUTH_{name.upper()}_SEAL_RECEIPT_INVALID")
        if recorded.get(Path(item["path"]).resolve()) != item["sha256"]:
            raise ActionBudgetIdentityDrift(f"REAL_TRUTH_{name.upper()}_SEAL_DIFFERS_FROM_PREDICT_TERMINAL")


def _truth_access(
    action: str,
    *,
    succeeded: bool | None,
    callback_entered: bool,
    synthetic: bool,
    is_start: bool,
) -> str:
    if is_start or action != "truth_decode":
        return "NOT_READ"
    if synthetic:
        return "SYNTHETIC_FIXTURE_ONLY"
    if succeeded:
        return "OPENED_EXPOSED_HISTORY"
    return "UNKNOWN_AFTER_DECODER_ENTERED" if callback_entered else "NOT_READ"


def _validate_action(action: Any) -> str:
    if not isinstance(action, str) or action not in ACTION_SET:
        raise ActionBudgetError(f"action must be one of {sorted(ACTION_SET)}")
    return action


def _require_sha(value: Any, label: str) -> str:
    if not _is_sha(value):
        raise ActionBudgetError(f"{label} must be a lowercase SHA256")
    return value


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
