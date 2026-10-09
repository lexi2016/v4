"""Route adapter over the accepted F5 candidate owner and Guard lifecycle."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
BATCH = ROOT / "research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927"
CANDIDATE = BATCH / "candidate_01"
SRC = BATCH / "src"
ORIGINAL_BATCH = ROOT / "research/hk_burst_f5/batches/full64_xendcg_r1_20260924"
ORIGINAL_CANDIDATE = ORIGINAL_BATCH / "candidate_01"
ORIGINAL_ENTRY = ORIGINAL_CANDIDATE / "src/candidate_entry.py"
ORIGINAL_WORKER_SRC = ORIGINAL_CANDIDATE / "src"
ORIGINAL_RECOVERY = ORIGINAL_BATCH / "recovery_01"
ROUTE_ARM = "CANDIDATE_FIXED_RFF_RBF256_LOGISTIC_C1"
EXPECTED_LEGACY_ARM = "CANDIDATE_NATIVE_RANK_XENDCG_FULL_2024_RAW_SCORE"
FROZEN_CONTRACT_PATH = BATCH / "contracts/EXPERIMENT_CONTRACT.json"
FROZEN_CONTRACT_SHA256 = "e6c1509955730a032d183563d6ffcf2501a587dd5734426f35fc59b222491135"
FROZEN_SOURCE_PARENT_PLAN_PATH = ORIGINAL_BATCH / "input_refs/plan_package/TRAINING_PLAN.json"
FROZEN_SOURCE_PARENT_PLAN_SHA256 = "fd94cc4952efaed5341abe858da20a01118cb7adbdd4b7492826f321c7bf37fc"
FROZEN_PARENT_PLAN_PATH = BATCH / "contracts/F5_FULL64_RFF_TRAINING_PLAN_REVISION_R1_20260928.json"
FROZEN_PARENT_PLAN_SHA256 = "e52c506448b15369308d3d2dbee8f3cb300b4b45fc00255b3de20c1de5eaca95"
USER_RESTORE_SOURCE_PATH = ROOT / "handoffs/F5_RFF_RESUME_EXECUTION_20260928/authority/USER_RESTORE_SOURCE_VERIFIED.json"
USER_RESTORE_SOURCE_SHA256 = "4a67ced4954351f922cc676aff91000f027fb18dc885b16908a591c03dbb70de"
RESTORE_CONTINUATION_SOURCE_PATH = ROOT / "handoffs/F5_RFF_RESUME_EXECUTION_20260928/authority/CURRENT_RESTORE_CONTINUATION_REFERENCE.json"
RESTORE_CONTINUATION_SOURCE_SHA256 = "152c0cbd556b9f7618acef8bd5e51e449048a274cda59cf3df2d644069737652"
PARENT_AUTHORIZATION_RECEIPT_PATH = ROOT / "handoffs/F5_RFF_RESUME_EXECUTION_20260928/authority/PARENT_AUTHORIZATION_RECEIPT_NATIVE_ADAPTATION_R3.json"
PARENT_AUTHORIZATION_ID = "F5_RFF_RESUME_AUTH_20260928_02"


class RFFEntryError(RuntimeError):
    pass


def _bound_source_sha(path: Path, binding: Mapping[str, Any], label: str) -> str:
    """A hard-coded import path is not itself a reviewed source binding."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RFFEntryError(f"RFF_BOUND_IMPORT_PATH_INVALID:{label}")
    matches = [item for item in binding.get("code_files", {}).values()
               if isinstance(item, Mapping) and item.get("path") == str(path)]
    if not matches:
        raise RFFEntryError(f"RFF_IMPORT_SOURCE_NOT_BOUND:{label}")
    digest = _sha256_file(path)
    if any(item.get("sha256") != digest for item in matches):
        raise RFFEntryError(f"RFF_IMPORT_SOURCE_SHA_MISMATCH:{label}")
    return digest


def _load_module(path: Path, name: str, *, expected_sha256: str | None = None) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RFFEntryError(f"MODULE_LOAD_FAILED:{name}")
    raw = path.read_bytes()
    if expected_sha256 is not None and _sha256_bytes(raw) != expected_sha256:
        raise RFFEntryError(f"RFF_IMPORT_SOURCE_DRIFT:{name}")
    module = importlib.util.module_from_spec(spec)
    old = sys.modules.get(name)
    sys.modules[name] = module
    try:
        # Execute the same bytes just checked, not a potentially stale .pyc.
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        if old is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old
        raise
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(raw)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RFFEntryError(f"BOUND_JSON_OBJECT_REQUIRED:{Path(path).name}")
    return value


def _frozen_contract() -> dict[str, Any]:
    path = FROZEN_CONTRACT_PATH
    if path.is_symlink() or not path.is_file():
        raise RFFEntryError("RFF_FROZEN_CONTRACT_MISSING_OR_SYMLINK")
    raw = path.read_bytes()
    if _sha256_bytes(raw) != FROZEN_CONTRACT_SHA256:
        raise RFFEntryError("RFF_FROZEN_CONTRACT_SHA_MISMATCH")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RFFEntryError("RFF_FROZEN_CONTRACT_UNREADABLE") from exc
    if not isinstance(document, dict):
        raise RFFEntryError("RFF_FROZEN_CONTRACT_NOT_OBJECT")
    if document.get("route_id") != "F5_FULL64_RFF_LOGISTIC_R1_20260927":
        raise RFFEntryError("RFF_FROZEN_CONTRACT_ROUTE_MISMATCH")
    return document


def _validate_frozen_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    contract = _frozen_contract()
    prediction = contract["prediction_and_evaluation"]
    inputs = contract["input_identity"]
    model_definition = {
        "preprocessing": contract["preprocessing"],
        "random_fourier_features": contract["random_fourier_features"],
        "learner": contract["learner"],
    }
    evaluation_definition = {
        "scope": prediction["decision_scope"],
        "evaluator": prediction["evaluator"],
        "ranking_score": prediction["ranking_score"],
        "event_probability": prediction["event_probability"],
        "selection_slots_denominator": prediction["selection_slots_denominator"],
        "truth_positive_denominator": prediction["truth_positive_denominator"],
        "evaluation_fold": inputs["evaluation_fold"],
        "controls": inputs["controls"],
        "decision_gates": contract["decision_gates"],
    }
    if spec.get("route_id") != contract["route_id"]:
        raise RFFEntryError("RFF_SPEC_FROZEN_ROUTE_MISMATCH")
    if spec.get("baseline_id") != contract["baseline_id"]:
        raise RFFEntryError("RFF_SPEC_FROZEN_BASELINE_MISMATCH")
    if spec.get("one_variable") != contract["one_variable"]:
        raise RFFEntryError("RFF_SPEC_FROZEN_ONE_VARIABLE_MISMATCH")
    if spec.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256:
        raise RFFEntryError("RFF_SPEC_FROZEN_CONTRACT_SHA_MISMATCH")
    if spec.get("preprocessing") != contract["preprocessing"]:
        raise RFFEntryError("RFF_SPEC_FROZEN_PREPROCESSING_MISMATCH")
    frozen_rff = dict(contract["random_fourier_features"])
    frozen_rff.pop("chunking")
    frozen_rff["chunk_rows"] = 4096
    if spec.get("random_fourier_features") != frozen_rff:
        raise RFFEntryError("RFF_SPEC_FROZEN_RANDOM_FEATURES_MISMATCH")
    if spec.get("decision_gates") != contract["decision_gates"]:
        raise RFFEntryError("RFF_SPEC_FROZEN_DECISION_GATES_MISMATCH")
    if spec.get("evaluation_definition") != evaluation_definition:
        raise RFFEntryError("RFF_SPEC_FROZEN_EVALUATION_DEFINITION_MISMATCH")
    if spec.get("model_definition_sha256") != _canonical_sha256(model_definition):
        raise RFFEntryError("RFF_SPEC_FROZEN_MODEL_DEFINITION_SHA_MISMATCH")
    if spec.get("evaluation_definition_sha256") != _canonical_sha256(evaluation_definition):
        raise RFFEntryError("RFF_SPEC_FROZEN_EVALUATION_DEFINITION_SHA_MISMATCH")
    return contract


def _validate_resource_caps(contract: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the RFF-scoped resource revision against both frozen sources."""
    source_path = FROZEN_SOURCE_PARENT_PLAN_PATH
    if source_path.is_symlink() or not source_path.is_file():
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    source_raw = source_path.read_bytes()
    if _sha256_bytes(source_raw) != FROZEN_SOURCE_PARENT_PLAN_SHA256:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    try:
        parent_plan = json.loads(source_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT") from exc
    if not isinstance(parent_plan, dict):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    parent_authorization = parent_plan.get("authorization")
    contract_input = contract.get("input_identity")
    contract_learner = contract.get("learner")
    parent_learner = parent_plan.get("learner")
    parent_params = parent_learner.get("params") if isinstance(parent_learner, Mapping) else None
    if (not isinstance(parent_authorization, Mapping)
            or not isinstance(contract_input, Mapping)
            or not isinstance(contract_learner, Mapping)
            or not isinstance(parent_learner, Mapping)
            or not isinstance(parent_params, Mapping)
            or parent_plan.get("route_id") != "F5_FULL64_XENDCG_R1_20260924"
            or parent_learner.get("library") != "lightgbm"
            or parent_params.get("objective") != "rank_xendcg"
            or not isinstance(parent_plan.get("runtime"), Mapping)
            or parent_authorization.get("old_authorization_reusable") is not False
            or parent_authorization.get("parent_release_required") is not True):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")

    contract_resources = contract.get("resources")
    parent_runtime = parent_plan["runtime"]
    if (not isinstance(contract_resources, Mapping)
            or contract.get("route_id") != "F5_FULL64_RFF_LOGISTIC_R1_20260927"
            or contract.get("status") != "FROZEN_BEFORE_SOURCE_IMPLEMENTATION"
            or contract_input.get("parent_training_plan_path") != str(source_path)
            or contract_input.get("parent_training_plan_sha256") != FROZEN_SOURCE_PARENT_PLAN_SHA256):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    if contract_learner.get("family") != "binary logistic regression":
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    if (parent_runtime.get("cpu_threads") != 4
            or parent_runtime.get("aggregate_process_tree_rss_bytes_max") != 3221225472
            or parent_runtime.get("process_tree_wall_seconds_max") != 600):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    sample_interval = parent_runtime.get("sampling_interval_seconds")
    if (type(sample_interval) not in (int, float) or sample_interval != 0.05):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")

    revision_path = FROZEN_PARENT_PLAN_PATH
    if revision_path.is_symlink() or not revision_path.is_file():
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    revision_raw = revision_path.read_bytes()
    if _sha256_bytes(revision_raw) != FROZEN_PARENT_PLAN_SHA256:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    try:
        revision = json.loads(revision_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT") from exc
    if not isinstance(revision, Mapping):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    revision_parent = revision.get("derived_from_parent_plan")
    revision_parent_learner = revision_parent.get("learner") if isinstance(revision_parent, Mapping) else None
    revision_contract = revision.get("frozen_rff_contract")
    revision_runtime = revision.get("runtime")
    resolution = revision.get("resource_resolution")
    if (revision.get("schema") != "F5_FULL64_RFF_TRAINING_PLAN_REVISION_V1"
            or revision.get("revision_id") != "F5_FULL64_RFF_RESOURCE_REVISION_R1_20260928"
            or revision.get("document_status") != "CONTROLLED_ROUTE_LOCAL_DERIVATION_PENDING_OWNER_RELEASE"
            or revision.get("route_id") != contract.get("route_id")
            or not isinstance(revision_parent, Mapping)
            or revision_parent.get("path") != str(source_path)
            or revision_parent.get("sha256") != FROZEN_SOURCE_PARENT_PLAN_SHA256
            or revision_parent.get("route_id") != parent_plan.get("route_id")
            or not isinstance(revision_parent_learner, Mapping)
            or revision_parent_learner.get("library") != parent_learner["library"]
            or revision_parent_learner.get("objective") != parent_params["objective"]
            or revision_parent_learner.get("version") != parent_learner.get("version")
            or revision_parent.get("authorization") != {
                "real_data_execution_authorized_by_this_document": False,
                "parent_release_required": True,
                "old_authorization_reusable": False,
            }
            or not isinstance(revision_contract, Mapping)
            or revision_contract.get("path") != str(FROZEN_CONTRACT_PATH)
            or revision_contract.get("sha256") != FROZEN_CONTRACT_SHA256
            or revision_contract.get("route_id") != contract.get("route_id")
            or revision_contract.get("status") != contract.get("status")
            or revision_contract.get("parent_training_plan_path") != str(source_path)
            or revision_contract.get("parent_training_plan_sha256") != FROZEN_SOURCE_PARENT_PLAN_SHA256
            or revision_contract.get("resources") != {
                "cpu_threads": contract_resources.get("cpu_threads"),
                "aggregate_process_tree_rss_bytes_max": contract_resources.get("aggregate_process_tree_rss_bytes_max"),
                "wall_seconds_max": contract_resources.get("wall_seconds_max"),
                "monitor": contract_resources.get("monitor"),
            }
            or not isinstance(revision_runtime, Mapping)
            or not isinstance(resolution, Mapping)):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    expected_runtime = {
        "cpu_threads": 4,
        "aggregate_process_tree_rss_bytes_max": 3221225472,
        "process_tree_wall_seconds_max": 1800,
        "sampling_interval_seconds": sample_interval,
        "hard_peak_memory_guarantee": False,
    }
    if dict(revision_runtime) != expected_runtime:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    if dict(contract_resources) != {
        "cpu_threads": 4,
        "aggregate_process_tree_rss_bytes_max": 3221225472,
        "wall_seconds_max": 1800,
        "monitor": "existing sampled resource monitor; sampling is not a hard peak guarantee",
    }:
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
    if (dict(resolution) != {
            "scope": "Only the single F5 RFF candidate worker from first input read through durable artifact persistence; no control fit/predict or calibrator fit.",
            "effective_wall_seconds_max": 1800,
            "reason": "The referenced parent plan is route-specific to the old native XENDCG learner. Its 600-second cap does not transfer to the separately frozen RFF logistic route. The RFF contract froze 1800 seconds before source implementation. This revision applies that exact route-local cap while retaining the parent plan CPU, RSS, sample interval, and no-hard-peak-guarantee settings.",
            "parent_route_wall_limit_transferred": False,
            "rff_contract_limit_increased": False,
            "parent_route_authorization_reused": False,
            "old_parent_plan_preserved_unchanged": True,
            "new_parent_release_required": True,
        }
            or not isinstance(revision.get("user_restore_source_reference"), Mapping)
            or revision.get("user_restore_source_reference", {}).get("path") != str(USER_RESTORE_SOURCE_PATH)
            or revision.get("user_restore_source_reference", {}).get("sha256") != USER_RESTORE_SOURCE_SHA256
            or not isinstance(revision.get("current_restore_continuation_reference"), Mapping)
            or revision.get("current_restore_continuation_reference", {}).get("path") != str(RESTORE_CONTINUATION_SOURCE_PATH)
            or revision.get("current_restore_continuation_reference", {}).get("sha256") != RESTORE_CONTINUATION_SOURCE_SHA256):
        raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")

    for source_ref, expected_path, expected_sha, expected_schema in (
        (revision.get("user_restore_source_reference"), USER_RESTORE_SOURCE_PATH, USER_RESTORE_SOURCE_SHA256,
         "F5_USER_RESTORE_SOURCE_VERIFIED_V1"),
        (revision.get("current_restore_continuation_reference"), RESTORE_CONTINUATION_SOURCE_PATH,
         RESTORE_CONTINUATION_SOURCE_SHA256, "F5_RFF_RESUME_CHAIN_SOURCE_REFERENCE_V1"),
    ):
        if not isinstance(source_ref, Mapping) or expected_path.is_symlink() or not expected_path.is_file():
            raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")
        if (_sha256_file(expected_path) != expected_sha or source_ref.get("schema") != expected_schema
                or source_ref.get("not_a_release") is not True or source_ref.get("not_a_user_signature") is not True):
            raise RFFEntryError("RESOURCE_CONTRACT_CONFLICT")

    expected = {
        "cpu_threads": expected_runtime["cpu_threads"],
        "aggregate_process_tree_rss_bytes_max": expected_runtime["aggregate_process_tree_rss_bytes_max"],
        "wall_seconds_max": expected_runtime["process_tree_wall_seconds_max"],
        "sampling_interval_seconds": sample_interval,
    }
    bound = binding.get("resources")
    if (not isinstance(bound, Mapping) or set(bound) != set(expected)
            or any(type(bound.get(key)) is not type(value) or bound.get(key) != value
                   for key, value in expected.items())):
        raise RFFEntryError("RFF_RESOURCE_CAPS_FROZEN_CONTRACT_MISMATCH")
    if (binding.get("resource_plan_revision_path") != str(revision_path.resolve())
            or binding.get("resource_plan_revision_sha256") != FROZEN_PARENT_PLAN_SHA256
            or binding.get("source_parent_plan_path") != str(source_path.resolve())
            or binding.get("source_parent_plan_sha256") != FROZEN_SOURCE_PARENT_PLAN_SHA256
            or binding.get("experiment_contract_path") != str(FROZEN_CONTRACT_PATH.resolve())
            or binding.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256):
        raise RFFEntryError("RFF_RESOURCE_CAPS_FROZEN_CONTRACT_MISMATCH")
    return expected


def _source_manifest_sha(binding: Mapping[str, Any]) -> str:
    files = binding.get("code_files")
    if not isinstance(files, Mapping) or not files:
        raise RFFEntryError("RFF_CODE_FILE_BINDING_MISSING")
    raw = json.dumps(dict(files), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = _sha256_bytes(raw)
    if digest != binding.get("code_sha256"):
        raise RFFEntryError("RFF_CODE_MANIFEST_SHA_MISMATCH")
    for name, item in files.items():
        path = Path(str(item.get("path", "")))
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != item.get("sha256"):
            raise RFFEntryError(f"RFF_CODE_SOURCE_SHA_MISMATCH:{name}")
    return digest


def _validate_native_helper_bindings(binding: Mapping[str, Any]) -> None:
    """Verify the exact helper/reference bytes the reused owner will load.

    The accepted XENDCG owner loads ``native_runtime_path`` and then reads
    ``native_reference_contract_path`` directly.  Those paths therefore need
    an explicit, pre-claim binding; listing a SHA in an unrelated manifest is
    not enough unless it is checked against the actual files here.
    """
    helpers = binding.get("executable_helpers")
    if not isinstance(helpers, Mapping):
        raise RFFEntryError("RFF_NATIVE_HELPER_BINDINGS_MISSING")
    for name, path_key, sha_key in (
        ("native_runtime", "native_runtime_path", "native_runtime_sha256"),
        ("native_reference_contract", "native_reference_contract_path", "native_reference_contract_sha256"),
    ):
        item = helpers.get(name)
        if not isinstance(item, Mapping):
            raise RFFEntryError(f"RFF_NATIVE_HELPER_BINDING_MISSING:{name}")
        path_value = binding.get(path_key)
        sha_value = binding.get(sha_key)
        helper_path_value = item.get("path")
        helper_sha_value = item.get("sha256")
        if (not isinstance(path_value, str) or not path_value
                or not isinstance(helper_path_value, str) or not helper_path_value
                or path_value != helper_path_value):
            raise RFFEntryError(f"RFF_NATIVE_HELPER_PATH_BINDING_MISMATCH:{name}")
        if (not isinstance(sha_value, str) or len(sha_value) != 64
                or any(char not in "0123456789abcdef" for char in sha_value)
                or sha_value != helper_sha_value):
            raise RFFEntryError(f"RFF_NATIVE_HELPER_SHA_BINDING_MISMATCH:{name}")
        path = Path(path_value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RFFEntryError(f"RFF_NATIVE_HELPER_PATH_INVALID:{name}")
        if _sha256_file(path) != sha_value:
            raise RFFEntryError(f"RFF_NATIVE_HELPER_SHA_MISMATCH:{name}")


def _validate_parent_authorization_receipt(
    spec: Mapping[str, Any], binding: Mapping[str, Any], *, input_binding_path: Path,
    reviewer_agent: str, reviewer_transcript_path: Path, reviewer_transcript_sha256: str,
    resource_caps: Mapping[str, Any],
) -> tuple[Path, str, dict[str, Any]]:
    """Require the real controller receipt that binds the restored user scope."""
    if (binding.get("parent_authorization_id") != PARENT_AUTHORIZATION_ID
            or binding.get("authorization_source_path") != str(USER_RESTORE_SOURCE_PATH)
            or binding.get("authorization_source_sha256") != USER_RESTORE_SOURCE_SHA256
            or binding.get("restore_continuation_reference_path") != str(RESTORE_CONTINUATION_SOURCE_PATH)
            or binding.get("restore_continuation_reference_sha256") != RESTORE_CONTINUATION_SOURCE_SHA256
            or binding.get("parent_authorization_receipt_path") != str(PARENT_AUTHORIZATION_RECEIPT_PATH)):
        raise RFFEntryError("RFF_PARENT_AUTHORIZATION_SOURCE_BINDING_MISMATCH")
    for source_path, source_sha, expected_schema in (
        (USER_RESTORE_SOURCE_PATH, USER_RESTORE_SOURCE_SHA256, "F5_USER_RESTORE_SOURCE_VERIFIED_V1"),
        (RESTORE_CONTINUATION_SOURCE_PATH, RESTORE_CONTINUATION_SOURCE_SHA256,
         "F5_RFF_RESUME_CHAIN_SOURCE_REFERENCE_V1"),
    ):
        if source_path.is_symlink() or not source_path.is_file() or _sha256_file(source_path) != source_sha:
            raise RFFEntryError("RFF_PARENT_AUTHORIZATION_SOURCE_BINDING_MISMATCH")
        source_document = _json(source_path)
        if (source_document.get("schema") != expected_schema
                or source_document.get("not_a_release") is not True
                or source_document.get("not_a_user_signature") is not True):
            raise RFFEntryError("RFF_PARENT_AUTHORIZATION_SOURCE_BINDING_MISMATCH")

    primary_source = _json(USER_RESTORE_SOURCE_PATH)
    continuation_source = _json(RESTORE_CONTINUATION_SOURCE_PATH)
    expected_source_identity = {
        "source_thread_id": primary_source["source_thread_id"],
        "source_user_message_id": primary_source["source_user_message_id"],
        "restore_thread_id": continuation_source["source_thread_id"],
        "restore_user_message_id": continuation_source["source_user_message_id"],
    }
    if any(binding.get(key) != value for key, value in expected_source_identity.items()):
        raise RFFEntryError("RFF_PARENT_AUTHORIZATION_SOURCE_BINDING_MISMATCH")

    receipt_path = PARENT_AUTHORIZATION_RECEIPT_PATH
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise RFFEntryError("RFF_PARENT_AUTHORIZATION_RECEIPT_MISSING")
    receipt = _json(receipt_path)
    receipt_sha = _sha256_file(receipt_path)
    input_binding_sha = _sha256_file(input_binding_path)
    allowed_counts = {
        "candidate_fit_calls_authorized": 1,
        "candidate_predict_calls_authorized": 1,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "calibrator_fit_calls_authorized": 0,
        "evaluation_truth_decodes_authorized": 1,
        "candidate_model_load_authorized": False,
        "automatic_retry_after_real_start": False,
        "fit_entry_consumes_budget": True,
    }
    expected_receipt = {
        "schema": "F5_RFF_PARENT_AUTHORIZATION_RECEIPT_V1",
        "status": "ISSUED",
        "active": True,
        "issuer_agent": "/root",
        "issuer_role": "PRIMARY_CONTROLLER",
        "synthetic_only": False,
        "not_user_signature": True,
        "parent_authorization_id": PARENT_AUTHORIZATION_ID,
        "source_verification_path": str(USER_RESTORE_SOURCE_PATH),
        "source_verification_sha256": USER_RESTORE_SOURCE_SHA256,
        "source_thread_id": primary_source["source_thread_id"],
        "source_user_message_id": primary_source["source_user_message_id"],
        "restore_continuation_reference_path": str(RESTORE_CONTINUATION_SOURCE_PATH),
        "restore_continuation_reference_sha256": RESTORE_CONTINUATION_SOURCE_SHA256,
        "restore_thread_id": continuation_source["source_thread_id"],
        "restore_user_message_id": continuation_source["source_user_message_id"],
        "route_id": binding.get("route_id"),
        "execution_id": binding.get("execution_id"),
        "run_spec_path": binding.get("run_spec_path"),
        "run_spec_sha256": binding.get("run_spec_sha256"),
        "input_binding_path": str(input_binding_path.resolve()),
        "input_binding_sha256": input_binding_sha,
        "code_sha256": binding.get("code_sha256"),
        "experiment_contract_path": str(FROZEN_CONTRACT_PATH.resolve(strict=True)),
        "experiment_contract_sha256": FROZEN_CONTRACT_SHA256,
        "source_parent_plan_path": str(FROZEN_SOURCE_PARENT_PLAN_PATH.resolve(strict=True)),
        "source_parent_plan_sha256": FROZEN_SOURCE_PARENT_PLAN_SHA256,
        "resource_plan_revision_path": str(FROZEN_PARENT_PLAN_PATH.resolve(strict=True)),
        "resource_plan_revision_sha256": FROZEN_PARENT_PLAN_SHA256,
        "resource_caps": dict(resource_caps),
        "allowed_counts": allowed_counts,
        "reviewer_agent": reviewer_agent,
        "reviewer_verdict": "PASS",
        "reviewer_transcript_path": str(reviewer_transcript_path.resolve()),
        "reviewer_transcript_sha256": reviewer_transcript_sha256,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        mismatches = [key for key, value in expected_receipt.items() if receipt.get(key) != value]
        raise RFFEntryError(f"RFF_PARENT_AUTHORIZATION_RECEIPT_FIELD_MISMATCH:{','.join(mismatches)}")
    return receipt_path, receipt_sha, receipt


def _verify_rff_parent_release(
    spec: Mapping[str, Any], binding: Mapping[str, Any], release: Mapping[str, Any], *,
    input_binding_path: Path, release_path: Path, reviewer_transcript_path: Path,
) -> tuple[str, str]:
    """Check the exact RFF release and review before the original owner claims."""
    contract = _validate_frozen_spec(spec)
    resource_caps = _validate_resource_caps(contract, binding)
    authorization_id = binding.get("parent_authorization_id")
    if authorization_id != PARENT_AUTHORIZATION_ID:
        raise RFFEntryError("RFF_PARENT_AUTHORIZATION_ID_MISSING")
    release_sha = _sha256_file(release_path)
    review_sha = _sha256_file(reviewer_transcript_path)
    transcript = _json(reviewer_transcript_path)
    reviewer_agent = transcript.get("reviewer_agent")
    if not isinstance(reviewer_agent, str) or not reviewer_agent or reviewer_agent == "writer":
        raise RFFEntryError("RFF_INDEPENDENT_REVIEWER_ID_MISSING")
    primary_source = _json(USER_RESTORE_SOURCE_PATH)
    continuation_source = _json(RESTORE_CONTINUATION_SOURCE_PATH)
    if (transcript.get("reviewer_verdict") != "PASS"
            or transcript.get("reviewed_code_sha256") != binding.get("code_sha256")
            or transcript.get("route_id") != binding.get("route_id")
            or transcript.get("execution_id") != binding.get("execution_id")
            or transcript.get("run_spec_sha256") != binding.get("run_spec_sha256")
            or transcript.get("input_binding_sha256") != _sha256_file(input_binding_path)
            or transcript.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256
            or transcript.get("parent_authorization_id") != PARENT_AUTHORIZATION_ID
            or transcript.get("authorization_source_path") != str(USER_RESTORE_SOURCE_PATH)
            or transcript.get("authorization_source_sha256") != USER_RESTORE_SOURCE_SHA256
            or transcript.get("restore_continuation_reference_path") != str(RESTORE_CONTINUATION_SOURCE_PATH)
            or transcript.get("restore_continuation_reference_sha256") != RESTORE_CONTINUATION_SOURCE_SHA256
            or transcript.get("source_thread_id") != primary_source.get("source_thread_id")
            or transcript.get("source_user_message_id") != primary_source.get("source_user_message_id")
            or transcript.get("restore_thread_id") != continuation_source.get("source_thread_id")
            or transcript.get("restore_user_message_id") != continuation_source.get("source_user_message_id")
            or transcript.get("source_parent_plan_path") != str(FROZEN_SOURCE_PARENT_PLAN_PATH.resolve())
            or transcript.get("source_parent_plan_sha256") != FROZEN_SOURCE_PARENT_PLAN_SHA256
            or transcript.get("resource_plan_revision_path") != str(FROZEN_PARENT_PLAN_PATH.resolve())
            or transcript.get("resource_plan_revision_sha256") != FROZEN_PARENT_PLAN_SHA256
            or transcript.get("resource_caps") != resource_caps
            or transcript.get("allowed_counts") != {
                "candidate_fit_calls_authorized": 1,
                "candidate_predict_calls_authorized": 1,
                "control_fit_calls_authorized": 0,
                "control_predict_calls_authorized": 0,
                "calibrator_fit_calls_authorized": 0,
                "evaluation_truth_decodes_authorized": 1,
                "candidate_model_load_authorized": False,
                "automatic_retry_after_real_start": False,
                "fit_entry_consumes_budget": True,
            }):
        raise RFFEntryError("RFF_INDEPENDENT_REVIEW_NOT_BOUND_PASS")
    parent_auth_path, parent_auth_sha, _parent_auth = _validate_parent_authorization_receipt(
        spec, binding, input_binding_path=input_binding_path, reviewer_agent=reviewer_agent,
        reviewer_transcript_path=reviewer_transcript_path, reviewer_transcript_sha256=review_sha,
        resource_caps=resource_caps,
    )
    contract_path = str(FROZEN_CONTRACT_PATH.resolve(strict=True))
    expected = {
        "active": True,
        "route_id": binding["route_id"],
        "execution_id": binding["execution_id"],
        "run_spec_sha256": binding["run_spec_sha256"],
        "input_binding_sha256": _sha256_file(input_binding_path),
        "code_sha256": binding["code_sha256"],
        "official_registry_path": str(Path(binding["official_registry_path"]).resolve()),
        "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
        "expected_route_event_sha256_before_start": binding["expected_route_event_sha256_before_start"],
        "reviewer_agent": reviewer_agent,
        "reviewer_transcript_path": str(reviewer_transcript_path.resolve()),
        "reviewer_transcript_sha256": review_sha,
        "candidate_fit_calls_authorized": 1,
        "candidate_predict_calls_authorized": 1,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "calibrator_fit_calls_authorized": 0,
        "evaluation_truth_decodes_authorized": 1,
        "candidate_model_load_authorized": False,
        "automatic_retry_after_real_start": False,
        "model_definition_sha256": spec["model_definition_sha256"],
        "evaluation_definition_sha256": spec["evaluation_definition_sha256"],
        "experiment_contract_path": contract_path,
        "experiment_contract_sha256": FROZEN_CONTRACT_SHA256,
        "parent_authorization_id": authorization_id,
        "parent_authorization_receipt_path": str(parent_auth_path.resolve()),
        "parent_authorization_receipt_sha256": parent_auth_sha,
        "source_verification_path": str(USER_RESTORE_SOURCE_PATH),
        "source_verification_sha256": USER_RESTORE_SOURCE_SHA256,
        "source_thread_id": primary_source["source_thread_id"],
        "source_user_message_id": primary_source["source_user_message_id"],
        "restore_continuation_reference_path": str(RESTORE_CONTINUATION_SOURCE_PATH),
        "restore_continuation_reference_sha256": RESTORE_CONTINUATION_SOURCE_SHA256,
        "restore_thread_id": continuation_source["source_thread_id"],
        "restore_user_message_id": continuation_source["source_user_message_id"],
        "source_parent_plan_path": str(FROZEN_SOURCE_PARENT_PLAN_PATH.resolve(strict=True)),
        "source_parent_plan_sha256": FROZEN_SOURCE_PARENT_PLAN_SHA256,
        "resource_plan_revision_path": str(FROZEN_PARENT_PLAN_PATH.resolve(strict=True)),
        "resource_plan_revision_sha256": FROZEN_PARENT_PLAN_SHA256,
        "resource_caps": resource_caps,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    if release.get("schema") != "F5_FULL64_RFF_LOGISTIC_PARENT_RELEASE_V1":
        raise RFFEntryError("RFF_PARENT_RELEASE_SCHEMA_MISMATCH")
    if release.get("synthetic_only") is True or release.get("synthetic_fixture_only") is True:
        raise RFFEntryError("RFF_SYNTHETIC_PARENT_RELEASE_REJECTED")
    if not release.get("parent_authorization_id"):
        raise RFFEntryError("RFF_PARENT_AUTHORIZATION_ID_MISSING")
    if release.get("reviewer_agent") != reviewer_agent or release.get("reviewer_verdict") != "PASS":
        raise RFFEntryError("RFF_RELEASE_REVIEWER_IDENTITY_MISMATCH")
    if (release.get("route_id") != binding.get("route_id")
            or release.get("execution_id") != binding.get("execution_id")
            or release.get("run_spec_sha256") != binding.get("run_spec_sha256")
            or release.get("input_binding_sha256") != _sha256_file(input_binding_path)
            or release.get("reviewer_transcript_sha256") != review_sha):
        raise RFFEntryError("RFF_RELEASE_SOURCE_IDENTITY_MISMATCH")
    if release.get("release_path") != str(release_path.resolve()):
        raise RFFEntryError("RFF_PARENT_RELEASE_PATH_MISMATCH")
    if release.get("release_sha256") not in (None, release_sha):
        raise RFFEntryError("RFF_PARENT_RELEASE_SELF_SHA_MISMATCH")
    mismatches = [key for key, value in expected.items() if release.get(key) != value]
    if mismatches:
        raise RFFEntryError(f"RFF_PARENT_RELEASE_FIELD_MISMATCH:{','.join(mismatches)}")
    return release_sha, review_sha


def _adapt_owner(entry: Any, spec: Mapping[str, Any], binding: Mapping[str, Any]) -> Any:
    """Keep the old owner/Guard implementation; bind its route-specific labels."""
    entry.CANDIDATE_ROOT = CANDIDATE
    entry.BATCH_ROOT = ORIGINAL_BATCH
    entry.RECOVERY_ROOT = ORIGINAL_RECOVERY
    entry.READBACK_ROOT = ORIGINAL_RECOVERY / "readback_01"
    entry.PROJECT_ROOT = ROOT
    entry.SRC = SRC
    entry.RUN_SPEC_PATH = Path(binding["run_spec_path"])
    entry.INPUT_BINDING_PATH = Path(binding["input_binding_path"])
    entry.EXECUTION_ID = str(binding["execution_id"])
    entry._verify_parent_release = _verify_rff_parent_release

    # Spawn an identity-bound descriptor, not a pickled function reference.
    # A fresh process-local pycache prefix makes the child compile the same
    # source bytes whose SHA is in the immutable code binding.
    old_import_resource_tree = getattr(entry, "import_resource_tree", None)
    worker_record = binding.get("code_files", {}).get("rff_worker")
    if callable(old_import_resource_tree) and isinstance(worker_record, Mapping):
        worker_path = Path(str(worker_record.get("path", ""))).resolve(strict=True)
        worker_sha = str(worker_record.get("sha256", ""))

        def import_bound_resource_tree(path: Path, expected_sha: str):
            resource_module = old_import_resource_tree(path, expected_sha)
            resource_view = SimpleNamespace(**vars(resource_module))
            original_run_spawn = resource_module.run_spawn_monitored

            def run_spawn_monitored(target: Any, payload: Mapping[str, Any], **kwargs: Any):
                if (target is None or getattr(target, "__module__", None) != "rff_worker"
                        or getattr(target, "__name__", None) != "run_candidate_worker"):
                    raise RFFEntryError("RFF_SPAWN_TARGET_IDENTITY_MISMATCH")
                worker_module = sys.modules.get("rff_worker")
                if (worker_module is None or getattr(worker_module, "run_candidate_worker", None) is not target
                        or Path(str(getattr(worker_module, "__file__", ""))).resolve() != worker_path
                        or _sha256_file(worker_path) != worker_sha):
                    raise RFFEntryError("RFF_SPAWN_SOURCE_BINDING_MISMATCH")
                if "target_descriptor" in kwargs:
                    raise RFFEntryError("RFF_SPAWN_DESCRIPTOR_ALREADY_SUPPLIED")
                descriptor = {
                    "path": str(worker_path),
                    "sha256": worker_sha,
                    "module_name": "rff_worker",
                    "callable": "run_candidate_worker",
                }
                previous_prefix = os.environ.get("PYTHONPYCACHEPREFIX")
                with tempfile.TemporaryDirectory(prefix="f5-rff-pycache-") as fresh_prefix:
                    os.environ["PYTHONPYCACHEPREFIX"] = fresh_prefix
                    try:
                        return original_run_spawn(
                            None, payload, target_descriptor=descriptor, **kwargs,
                        )
                    finally:
                        if previous_prefix is None:
                            os.environ.pop("PYTHONPYCACHEPREFIX", None)
                        else:
                            os.environ["PYTHONPYCACHEPREFIX"] = previous_prefix

            resource_view.run_spawn_monitored = run_spawn_monitored
            return resource_view

        entry.import_resource_tree = import_bound_resource_tree

    old_make_adapter = entry._make_candidate_adapter

    def make_adapter(*args: Any, **kwargs: Any):
        adapter_class = old_make_adapter(*args, **kwargs)
        class RouteAdapter(adapter_class):
            def __init__(self, *init_args: Any, **init_kwargs: Any) -> None:
                profile = dict(init_kwargs.get("event_profile") or {})
                profile.update({
                    "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
                    "route_id": binding["route_id"],
                    "start_stage": "RFF_LOGISTIC_CANDIDATE_RUN_STARTED",
                    "terminal_stage": "RFF_LOGISTIC_CANDIDATE_TERMINAL",
                    "baseline_id": spec["baseline_id"],
                    "one_variable": spec["one_variable"],
                    "signal_scope": "ORIGINAL_2018_TO_2023_TRAINING_FOLD",
                    "target_scope": "EXPOSED_2024_FULL_GRID_AFTER_PREDICTION_SEAL",
                    "evidence_level": "DIRECTION_ONLY",
                })
                init_kwargs["event_profile"] = profile
                super().__init__(*init_args, **init_kwargs)

            def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
                result = super()._event_spec(event, event_type=event_type)
                # START never inherits terminal producer markers. Only a
                # complete, same-execution RFF receipt chain can be promoted.
                result["truth_access"] = "NOT_READ"
                result["sealed_status"] = "EXPOSED_2024_LABELS_NOT_DECODED"
                if event_type != "TERMINAL":
                    return result

                state, truth_access = self._truth_evidence(event)
                result["truth_access"] = truth_access
                if state == "COMPLETED" and event.get("terminal_status") == "COMPLETED":
                    result["sealed_status"] = "EXPOSED_2024_POST_SEAL_EVALUATION"
                    return result
                if state == "NOT_DECODED":
                    if event.get("terminal_status") == "COMPLETED":
                        result["sealed_status"] = "CANNOT_CONFIRM"
                        result["decision"] = "CANNOT_CONFIRM"
                        result["stop_reason"] = "RFF_POST_SEAL_PRODUCER_CHAIN_UNVERIFIED"
                    return result

                # A read-start receipt is evidence that evaluation truth was
                # reached even when the run later failed. Keep that fact while
                # refusing to label an incomplete/contradictory evaluation as
                # a completed sealed result.
                result["sealed_status"] = "CANNOT_CONFIRM"
                if event.get("terminal_status") == "COMPLETED":
                    result["decision"] = "CANNOT_CONFIRM"
                    result["stop_reason"] = "RFF_POST_SEAL_PRODUCER_CHAIN_UNVERIFIED"
                return result

            @staticmethod
            def _receipt(path: Path) -> tuple[dict[str, Any] | None, str | None]:
                if path.is_symlink():
                    return None, "invalid"
                if not path.exists():
                    return None, None
                if not path.is_file():
                    return None, "invalid"
                try:
                    raw = path.read_bytes()
                    value = json.loads(raw)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    return None, "invalid"
                if not isinstance(value, dict):
                    return None, "invalid"
                return value, _sha256_bytes(raw)

            @staticmethod
            def _sha256_text(value: Any) -> bool:
                return (isinstance(value, str) and len(value) == 64
                        and all(char in "0123456789abcdef" for char in value))

            def _truth_evidence(self, event: Mapping[str, Any]) -> tuple[str, str]:
                """Classify same-execution producer receipts without opening data artifacts."""
                route_id = str(binding.get("route_id", ""))
                execution_id = str(binding.get("execution_id", ""))
                if (not route_id or not execution_id
                        or event.get("experiment_id") != route_id
                        or event.get("execution_id") != execution_id):
                    return "UNCERTAIN", "CANNOT_CONFIRM"

                root_value = binding.get("output_root")
                if not isinstance(root_value, str) or not Path(root_value).is_absolute():
                    return "UNCERTAIN", "CANNOT_CONFIRM"
                root = Path(root_value)
                expected_names = {
                    "prediction_seal_path": "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json",
                    "eval_truth_read_path": "EVALUATION_TRUTH_READ_START.json",
                    "result_path": "CANDIDATE_RESULT_RECEIPT.json",
                }
                paths: dict[str, Path] = {}
                for key, name in expected_names.items():
                    raw_path = binding.get(key)
                    if not isinstance(raw_path, str):
                        return "UNCERTAIN", "CANNOT_CONFIRM"
                    path = Path(raw_path)
                    expected_path = root / name
                    if (path.resolve(strict=False) != expected_path.resolve(strict=False)
                            or path.is_symlink()):
                        return "UNCERTAIN", "CANNOT_CONFIRM"
                    paths[key] = path

                worker_path = root / "CANDIDATE_WORKER_STATUS.json"
                input_path = root / "CANDIDATE_INPUT_HASH_RECEIPT.json"
                if root.is_symlink():
                    return "UNCERTAIN", "CANNOT_CONFIRM"
                documents: dict[str, dict[str, Any] | None] = {}
                digests: dict[str, str | None] = {}
                errors: set[str] = set()
                for name, path in (
                    ("seal", paths["prediction_seal_path"]),
                    ("truth_read", paths["eval_truth_read_path"]),
                    ("result", paths["result_path"]),
                    ("worker", worker_path),
                    ("input", input_path),
                ):
                    document, digest = self._receipt(path)
                    if digest == "invalid":
                        errors.add(name)
                    documents[name] = document
                    digests[name] = digest
                if errors.intersection({"seal", "truth_read"}):
                    return "UNCERTAIN", "CANNOT_CONFIRM"

                seal = documents["seal"]
                truth_read = documents["truth_read"]
                result_doc = documents["result"]
                worker_doc = documents["worker"]
                input_doc = documents["input"]
                seal_sha = digests["seal"]
                seal_valid = bool(
                    isinstance(seal, Mapping)
                    and seal.get("schema") == "F5_FULL64_RFF_PREDICTION_SEAL_V1"
                    and seal.get("status") == "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ"
                    and seal.get("route_id") == route_id
                    and seal.get("execution_id") == execution_id
                    and seal.get("evaluation_label_values_decoded") is False
                    and self._sha256_text(seal.get("candidate_scores_sha256"))
                    and self._sha256_text(seal.get("candidate_raw_scores_sha256"))
                    and self._sha256_text(seal.get("candidate_top3_sha256"))
                )
                if seal is not None and not seal_valid:
                    return "UNCERTAIN", "CANNOT_CONFIRM"

                truth_valid = bool(
                    isinstance(truth_read, Mapping)
                    and truth_read.get("schema") == "F5_FULL64_RFF_EVAL_TRUTH_READ_START_V1"
                    and truth_read.get("route_id") == route_id
                    and truth_read.get("execution_id") == execution_id
                    and truth_read.get("first_eval_truth_decode_after_prediction_seal") is True
                    and self._sha256_text(seal_sha)
                    and truth_read.get("prediction_seal_sha256") == seal_sha
                    and seal_valid
                    and all(truth_read.get(field) == seal.get(field) for field in (
                        "candidate_scores_sha256", "candidate_raw_scores_sha256", "candidate_top3_sha256",
                    ))
                )
                if truth_read is not None and not truth_valid:
                    return "UNCERTAIN", "CANNOT_CONFIRM"

                decode_reported = False
                zero_decode_receipt = False
                if worker_doc is not None:
                    decode_count = worker_doc.get("evaluation_truth_decodes")
                    decode_flag = worker_doc.get("evaluation_label_values_decoded")
                    if type(decode_count) is not int or type(decode_flag) is not bool:
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"
                    if decode_count < 0 or decode_count > 1 or decode_flag != (decode_count == 1):
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"
                    worker_identity_valid = bool(
                        worker_doc.get("schema") == "F5_FULL64_RFF_WORKER_STATUS_V1"
                        and worker_doc.get("route_id") == route_id
                        and worker_doc.get("execution_id") == execution_id
                    )
                    synthetic_no_decode = bool(
                        worker_doc.get("synthetic_only") is True
                        and worker_doc.get("execution_id") == execution_id
                        and decode_count == 0 and decode_flag is False
                        and truth_read is None and result_doc is None
                    )
                    if not worker_identity_valid and not synthetic_no_decode:
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"
                    decode_reported = decode_flag
                    zero_decode_receipt = bool(
                        decode_count == 0 and decode_flag is False
                        and (worker_identity_valid or synthetic_no_decode)
                        and truth_read is None and result_doc is None
                        and worker_doc.get("status") in {
                            "FAILED", "STOP_OPTIMIZER_NOT_CONVERGED",
                        }
                    ) or synthetic_no_decode
                    if decode_reported != bool(truth_valid):
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"

                input_valid = False
                bound_input_files = binding.get("input_files")
                expected_input_sha: dict[str, str] = {}
                input_manifest_valid = bool(isinstance(bound_input_files, Mapping)
                                            and len(bound_input_files) == 6)
                if input_manifest_valid:
                    for name, item in bound_input_files.items():
                        if (not isinstance(name, str) or not isinstance(item, Mapping)
                                or not self._sha256_text(item.get("sha256"))):
                            input_manifest_valid = False
                            expected_input_sha = {}
                            break
                        expected_input_sha[name] = item["sha256"]
                if input_doc is not None:
                    input_valid = bool(
                        input_doc.get("schema") == "F5_FULL64_RFF_INPUT_HASH_RECEIPT_V1"
                        and input_doc.get("route_id") == route_id
                        and input_doc.get("execution_id") == execution_id
                        and input_manifest_valid
                        and input_doc.get("input_sha256") == expected_input_sha
                        and input_doc.get("all_six_frozen_inputs_verified") is True
                        and input_doc.get("eval_meta_pretruth_columns_only") == [
                            "code", "session_id", "market_date", "scoreable",
                        ]
                        and input_doc.get("evaluation_label_values_decoded") is False
                    )
                    if not input_valid:
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"

                if errors:
                    return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"

                completed = False
                if result_doc is not None or (worker_doc is not None and worker_doc.get("status") ==
                                              "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"):
                    expected_links = (
                        "candidate_scores_sha256", "candidate_raw_scores_sha256", "candidate_top3_sha256",
                    )
                    completed = bool(
                        seal_valid and truth_valid and isinstance(result_doc, Mapping)
                        and isinstance(worker_doc, Mapping)
                        and result_doc.get("schema") == "F5_FULL64_RFF_LOGISTIC_RESULT_V1"
                        and result_doc.get("status") == "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"
                        and worker_doc.get("status") == "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"
                        and result_doc.get("route_id") == route_id
                        and result_doc.get("execution_id") == execution_id
                        and result_doc.get("run_spec_sha256") == event.get("contract_sha256")
                        and result_doc.get("input_binding_sha256") == event.get("input_binding_sha256")
                        and result_doc.get("prediction_sealed_before_eval_truth_read") is True
                        and result_doc.get("prediction_seal_sha256") == seal_sha
                        and input_valid
                        and result_doc.get("input_sha256") == expected_input_sha
                        and result_doc.get("evaluation_truth_decodes") == 1
                        and result_doc.get("evaluation_label_values_decoded") is True
                        and all(result_doc.get(field) == seal.get(field) for field in expected_links)
                        and worker_doc.get("evaluation_truth_decodes") == 1
                        and worker_doc.get("evaluation_label_values_decoded") is True
                    )
                    if completed:
                        completed = bool(
                            event.get("terminal_status") == "COMPLETED"
                            and event.get("arm") == ROUTE_ARM
                            and event.get("contract_sha256") == binding.get("run_spec_sha256")
                            and result_doc.get("run_spec_sha256") == binding.get("run_spec_sha256")
                            and result_doc.get("source_code_sha256") == binding.get("code_sha256")
                        )
                    if not completed:
                        return "UNCERTAIN", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if truth_valid else "CANNOT_CONFIRM"
                    return "COMPLETED", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL"

                if truth_valid or decode_reported:
                    return "DECODED_INCOMPLETE", "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL"
                if zero_decode_receipt and seal_valid:
                    return "NOT_DECODED", "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED" if input_valid else "NO_INPUT_DECODE_MARKER"
                if zero_decode_receipt and input_valid:
                    return "NOT_DECODED", "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED"
                if zero_decode_receipt:
                    return "NOT_DECODED", "NO_INPUT_DECODE_MARKER"
                if any(document is not None for document in (seal, truth_read, result_doc, worker_doc, input_doc)):
                    return "UNCERTAIN", "CANNOT_CONFIRM"
                return "UNCERTAIN", "CANNOT_CONFIRM"

        return RouteAdapter

    entry._make_candidate_adapter = make_adapter
    old_load_official = entry._load_official_modules

    def load_official(binding_value: Mapping[str, Any]):
        adapter_module, guard_module = old_load_official(binding_value)
        original_guard = guard_module.ExecutionGuard

        class RouteExecutionGuard(original_guard):
            def claim(self, *, execution_id: str, arm: str, contract_sha256: str, input_binding_sha256: str):
                if arm != EXPECTED_LEGACY_ARM:
                    raise RFFEntryError("RFF_OWNER_LEGACY_ARM_CHANGED")
                return super().claim(
                    execution_id=execution_id,
                    arm=ROUTE_ARM,
                    contract_sha256=contract_sha256,
                    input_binding_sha256=input_binding_sha256,
                )

        # A route-local view leaves the accepted shared module/class untouched.
        guard_view = SimpleNamespace(**vars(guard_module))
        guard_view.ExecutionGuard = RouteExecutionGuard
        return adapter_module, guard_view

    entry._load_official_modules = load_official
    return entry


def run_candidate(
    *, run_spec_path: Path, input_binding_path: Path, release_path: Path,
    reviewer_transcript_path: Path,
) -> dict[str, Any]:
    """Invoke only the accepted owner entry with this route's worker target."""
    run_spec_path = Path(run_spec_path).resolve(strict=True)
    input_binding_path = Path(input_binding_path).resolve(strict=True)
    release_path = Path(release_path).resolve(strict=True)
    reviewer_transcript_path = Path(reviewer_transcript_path).resolve(strict=True)
    binding = _json(input_binding_path)
    for path in (SRC, ORIGINAL_WORKER_SRC, ORIGINAL_BATCH / "src", ORIGINAL_RECOVERY / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = _json(run_spec_path)
    if spec.get("route_id") != binding.get("route_id") or spec.get("execution_id") != binding.get("execution_id"):
        raise RFFEntryError("RFF_SPEC_BINDING_IDENTITY_MISMATCH")
    if binding.get("run_spec_path") != str(run_spec_path) or binding.get("input_binding_path") != str(input_binding_path):
        raise RFFEntryError("RFF_BOUND_CONTRACT_PATH_MISMATCH")
    if _sha256_file(run_spec_path) != binding.get("run_spec_sha256"):
        raise RFFEntryError("RFF_RUN_SPEC_SHA_MISMATCH")
    _source_manifest_sha(binding)
    _validate_native_helper_bindings(binding)
    # Validate every route-local target and the reused owner before any claim.
    owner_sha = _bound_source_sha(ORIGINAL_ENTRY, binding, "original_owner")
    worker_path = SRC / "rff_worker.py"
    completion_path = SRC / "rff_evaluation_completion.py"
    worker_sha = _bound_source_sha(worker_path, binding, "rff_worker")
    completion_sha = _bound_source_sha(completion_path, binding, "rff_completion")
    entry = _load_module(ORIGINAL_ENTRY, "f5_rff_reused_candidate_entry", expected_sha256=owner_sha)
    entry = _adapt_owner(entry, spec, binding)
    rff_worker = _load_module(worker_path, "rff_worker", expected_sha256=worker_sha)
    completion = _load_module(completion_path, "rff_evaluation_completion", expected_sha256=completion_sha)

    run_summary = entry._run_candidate(
        run_spec_path=run_spec_path,
        input_binding_path=input_binding_path,
        release_path=release_path,
        reviewer_transcript_path=reviewer_transcript_path,
        expected_execution_id=str(binding["execution_id"]),
        worker_target=rff_worker.run_candidate_worker,
    )
    run_doc = _json(Path(binding["run_receipt_path"])) if Path(binding["run_receipt_path"]).is_file() else None
    worker_status_path = Path(binding["output_root"]) / "CANDIDATE_WORKER_STATUS.json"
    worker = _json(worker_status_path) if worker_status_path.is_file() else None
    if run_summary.get("terminal_status") == "COMPLETED":
        try:
            run_summary["evaluation_completion"] = completion.write_completion_receipt(
                spec_path=run_spec_path, binding_path=input_binding_path, run_summary=run_summary,
            )
            run_summary["evaluation_completion_status"] = "EVALUATION_COMPLETED"
        except (completion.EvaluationCompletionError, OSError, ValueError, KeyError, TypeError) as exc:
            # The original TERMINAL and fit debit remain durable. Never rerun fit
            # because a subsequent, read-only completion verification failed.
            run_summary["evaluation_completion_status"] = "CANNOT_CONFIRM"
            run_summary["evaluation_completion_error"] = f"{type(exc).__name__}: {exc}"
            run_summary["automatic_retry_allowed"] = False
            run_summary["route_outcome"] = {"failure_phase": "EVALUATION_READBACK",
                                            "failure_class": "COMPLETION_VERIFICATION_FAILED"}
    else:
        run_summary["route_outcome"] = completion.classify_failure(run_doc, worker)
    return run_summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--input-binding", type=Path, required=True)
    parser.add_argument("--parent-release", type=Path, required=True)
    parser.add_argument("--reviewer-transcript", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_candidate(
        run_spec_path=args.run_spec,
        input_binding_path=args.input_binding,
        release_path=args.parent_release,
        reviewer_transcript_path=args.reviewer_transcript,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("terminal_status") == "COMPLETED" and result.get("evaluation_completion_status") == "EVALUATION_COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
