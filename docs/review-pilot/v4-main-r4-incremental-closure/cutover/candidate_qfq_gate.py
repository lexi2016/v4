"""Read-only evaluation of the frozen candidate's legacy-date classification."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sysconfig
from pathlib import Path
import sys


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject(reason: str) -> None:
    raise RuntimeError(reason)


QFQ_ENV_NAMES = (
    "V4_A_QFQ_COMPUTE_BACKEND", "V4_A_QFQ_SOURCE_REPAIR_DATE",
    "V4_A_QFQ_SOURCE_REPAIR_INPUT", "V4_A_QFQ_SOURCE_REPAIR_INPUT_SHA256",
    "V4_QFQ_CONVENTION_ACCEPTANCE_PATH", "V4_QFQ_CONVENTION_ACCEPTANCE_SHA256",
    "RESEARCH_PANEL_QFQ_REFRESH_FACTORS",
)
FLAG_NAMES = (
    "debug", "inspect", "optimize", "dont_write_bytecode", "no_user_site",
    "no_site", "ignore_environment", "isolated", "safe_path", "utf8_mode",
)


def environment_digest(environment: dict[str, str]) -> str:
    raw = "".join(f"{key}={environment[key]}\n" for key in sorted(environment)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalized_sys_path(values: list[str], cwd: Path) -> list[str]:
    """Normalize `-m` absolute cwd and `-c` empty sys.path[0] identically."""
    result = []
    for value in values:
        entry = Path(value or str(cwd)).absolute()
        result.append(str(entry))
    return result


def load_child_identity(path: Path, expected_sha: str) -> dict:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        reject("CHILD_IDENTITY_RECEIPT_PATH_INVALID")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        reject("CHILD_IDENTITY_RECEIPT_SHA_DRIFT")
    receipt = json.loads(raw)
    if (receipt.get("schema") != "v4.r4_daemon_a_qfq_identity_probe.v1"
            or receipt.get("status") != "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY"):
        reject("CHILD_IDENTITY_RECEIPT_NOT_PASS")
    if (receipt.get("natural_dispatch_status") != "NOT_RUN"
            or receipt.get("daemon_dispatch") != {
                "status": "NATURAL_DISPATCH_NOT_RUN", "task_key": None,
                "attempt_id": None, "run_id": None, "generation": None,
            }
            or receipt.get("claim_begin_called") is not False
            or receipt.get("admission_called") is not False
            or receipt.get("provider_invoked") is not False
            or receipt.get("production_registry_mutated") is not False
            or receipt.get("production_current_pointer_mutated") is not False
            or receipt.get("old_reservations_changed") is not False):
        reject("CHILD_IDENTITY_RECEIPT_SIDE_EFFECT_OR_DISPATCH_DRIFT")
    executor = (receipt.get("a_executor_fixture") or {}).get("captured_executor_run") or {}
    identity = receipt.get("qfq_child_identity")
    if (not isinstance(identity, dict)
            or executor.get("qfq_identity_probe") != identity
            or identity.get("production_owner_called") is not False
            or identity.get("claim_begin_called") is not False
            or identity.get("admission_called") is not False
            or identity.get("registry_mutated") is not False
            or identity.get("current_pointer_mutated") is not False
            or (receipt.get("a_executor_fixture") or {}).get("status") != "PASS_ACTUAL_A_EXECUTOR_RUN_CAPTURE"):
        reject("CHILD_IDENTITY_RECEIPT_DAEMON_TO_EXECUTOR_CHAIN_MISSING")
    return receipt


def verify_child_operation_key(receipt: dict, *, release: Path, target_date: str,
                               expected_key: str, expected_registry_sha: str,
                               expected_environment_sha: str, policy: dict,
                               module, kwargs: dict) -> dict:
    """Recompute the production operation key under the real A-child import shape."""
    identity = receipt["qfq_child_identity"]
    app = release / "app"
    runtime = release / "runtime"
    manifest_path = release / "release-manifest.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    executable = Path(sys.executable).resolve(strict=True)
    cwd = Path.cwd().resolve(strict=True)
    if cwd != app.resolve(strict=True):
        reject("CANDIDATE_CHILD_WORKING_DIRECTORY_DRIFT")
    if (receipt.get("release_id") != identity.get("release_id")
            or receipt.get("release_id") != json.loads(manifest_path.read_bytes()).get("release_id")
            or Path(receipt.get("release_root", "")).resolve(strict=True) != release
            or Path(receipt.get("app_root", "")).resolve(strict=True) != app
            or Path(receipt.get("runtime_root", "")).resolve(strict=True) != runtime):
        reject("CHILD_IDENTITY_RECEIPT_RELEASE_ROOT_DRIFT")
    release_record = identity.get("release_manifest") or {}
    if (release_record.get("status") != "READ_ONLY_STABLE"
            or release_record.get("sha256") != manifest_sha
            or release_record.get("expected_sha256") != manifest_sha
            or receipt.get("release_manifest_sha256") != manifest_sha):
        reject("CHILD_IDENTITY_RECEIPT_RELEASE_MANIFEST_DRIFT")
    if (Path(identity.get("executable", "")).resolve(strict=True) != executable
            or hashlib.sha256(executable.read_bytes()).hexdigest() != identity.get("executable_sha256")
            or Path(sys.base_prefix).resolve(strict=True) != Path(identity.get("base_prefix", "")).resolve(strict=True)
            or sys.version != identity.get("python")
            or sys.implementation.cache_tag != identity.get("cache_tag")
            or str(sys.pycache_prefix) != identity.get("pycache_prefix")
            or {name: getattr(sys.flags, name) for name in FLAG_NAMES} != identity.get("flags")):
        reject("CHILD_IDENTITY_RECEIPT_INTERPRETER_FLAGS_DRIFT")
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    if (Path(identity.get("stdlib_root", "")).resolve(strict=True) != stdlib
            or not stdlib.is_relative_to(runtime)):
        reject("CHILD_IDENTITY_RECEIPT_STDLIB_ROOT_DRIFT")
    observed_path = normalized_sys_path(sys.path, cwd)
    expected_path = normalized_sys_path(identity.get("effective_sys_path", []), cwd)
    if observed_path != expected_path:
        reject("CANDIDATE_CHILD_EFFECTIVE_SYS_PATH_DRIFT")
    for relative, row in (receipt.get("source_chain") or {}).items():
        source = app / relative
        if (not source.is_file() or source.resolve(strict=True) != source
                or source.is_relative_to(app) is False
                or hashlib.sha256(source.read_bytes()).hexdigest() != row.get("sha256")
                or Path(row.get("path", "")).resolve(strict=True) != source):
            reject("CHILD_IDENTITY_RECEIPT_SOURCE_CHAIN_DRIFT:" + relative)

    observed_qfq_environment = {name: os.environ.get(name) for name in QFQ_ENV_NAMES}
    if observed_qfq_environment != identity.get("qfq_environment_values"):
        reject("CANDIDATE_CHILD_QFQ_ENVIRONMENT_DRIFT")
    if expected_environment_sha != identity.get("environment_sha256"):
        reject("REVIEWED_CHILD_ENVIRONMENT_SHA_DRIFT")

    data_root = Path(policy["data_root"])
    return_root = Path(policy["run_root"])
    if (str(data_root) != identity.get("data_root")
            or str(return_root) != identity.get("return_root")
            or str(data_root) != receipt.get("data_root")
            or str(return_root) != receipt.get("return_root")):
        reject("CHILD_IDENTITY_RECEIPT_DATA_OR_RETURN_ROOT_DRIFT")
    registry_root = Path((policy.get("governance") or {}).get("registry_root", ""))
    registry_path = registry_root / "registry.json"
    if (str(registry_root) != identity.get("registry_root")
            or str(registry_path) != identity.get("registry_path")
            or str(registry_path) != receipt.get("registry_path")
            or identity.get("registry_sha256") != expected_registry_sha
            or receipt.get("registry_sha256") != expected_registry_sha):
        reject("CHILD_IDENTITY_RECEIPT_REGISTRY_BINDING_DRIFT")

    from ops.research_storage_retention import canonical
    from ops.research_qfq_dependency_identity import computation_dependencies
    from ops.research_storage_governance import qfq_invocation_key

    target = int(target_date)
    runtime_root = module.input_path(data_root).parent
    computation = computation_dependencies(module, dict(kwargs, target=target), runtime_root=runtime_root)
    computation_sha = canonical(computation)
    calculated_key = qfq_invocation_key(module, data_root, target, dict(kwargs, target=target))
    expected_child_key = (identity.get("qfq_operation_keys") or {}).get(target_date)
    if (expected_child_key != expected_key or calculated_key != expected_child_key
            or computation_sha != identity.get("computation_manifest_sha256")
            or receipt.get("qfq_operation_keys") != identity.get("qfq_operation_keys")
            or receipt.get("computation_manifest_sha256") != computation_sha):
        reject("CANDIDATE_CHILD_OPERATION_KEY_OR_COMPUTATION_MANIFEST_DRIFT")
    return {
        "status": "PASS_CANDIDATE_GATE_QFQ_CHILD_IDENTITY_PARITY",
        "target_date": target_date,
        "candidate_operation_key": calculated_key,
        "daemon_a_qfq_operation_key": expected_child_key,
        "operation_key_equal": calculated_key == expected_child_key,
        "computation_manifest_sha256": computation_sha,
        "daemon_computation_manifest_sha256": identity.get("computation_manifest_sha256"),
        "effective_sys_path": observed_path,
        "daemon_effective_sys_path": expected_path,
        "effective_sys_path_equal": observed_path == expected_path,
        "candidate_environment_sha256": environment_digest(dict(os.environ)),
        "daemon_qfq_environment_sha256": identity.get("environment_sha256"),
        "environment_scope": "COMPLETE_HASH_BOUND_TO_CAPTURED_CHILD; GATE_CHECKS_QFQ_ENVIRONMENT_FIELDS_AND_CALCULATION_KEY",
    }


def identity_parity_main() -> int:
    """Read-only parity mode for the frozen Mac child identity receipt."""
    if len(sys.argv) != 9:
        reject("IDENTITY_PARITY_ARGUMENT_COUNT")
    release = Path(sys.argv[2]).resolve(strict=True)
    identity_path = Path(sys.argv[3]).resolve(strict=True)
    identity_sha = sys.argv[4]
    target_date = sys.argv[5]
    expected_key = sys.argv[6]
    expected_registry_sha = sys.argv[7]
    expected_environment_sha = sys.argv[8]
    receipt = load_child_identity(identity_path, identity_sha)
    app = release / "app"
    module = importlib.import_module("ops.research_panel_qfq")
    if Path(module.__file__).resolve(strict=True) != app / "ops" / "research_panel_qfq.py":
        reject("CANDIDATE_QFQ_OWNER_IMPORT_DRIFT")
    env = os.environ
    data_root = Path(env["V4_RESEARCH_PANEL_A_DATA_ROOT"]).resolve()
    kwargs = {
        "driver_path": (app / "ops/vendor/data_layer_daily_formula_increment_update_v1.py").resolve(),
        "formula_path": Path(env["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"]).resolve(),
        "tdx_root": Path(env["V4_RESEARCH_PANEL_A_TDX_ROOT"]).resolve(),
        "data_root": data_root,
        "pointers": {
            "selector": Path(env["V4_RESEARCH_PANEL_A_SELECTOR_POINTER"]).absolute(),
            "backtest": Path(env["V4_RESEARCH_PANEL_A_BACKTEST_POINTER"]).absolute(),
        },
        "contract_csv": Path(env["V4_RESEARCH_PANEL_A_CONTRACT_CSV"]).resolve(),
        "return_root": Path(env["V4_RESEARCH_PANEL_A_RETURN_ROOT"]).resolve(),
        "target": int(target_date), "publish": True, "workers": None,
        "refresh_inputs": True, "storage_layout": "arrow_blocks_v1",
    }
    policy_path = Path(env["V4_RESEARCH_RETENTION_POLICY"])
    policy = load_candidate_policy_roots(release, env.get("V4_RESEARCH_RETENTION_POLICY_SHA256"))
    parity = verify_child_operation_key(
        receipt, release=release, target_date=target_date,
        expected_key=expected_key, expected_registry_sha=expected_registry_sha,
        expected_environment_sha=expected_environment_sha, policy=policy,
        module=module, kwargs=kwargs,
    )
    print(json.dumps(parity, sort_keys=True))
    return 0


def load_candidate_policy_roots(release: Path, expected_sha: str | None) -> dict:
    """Read policy/root bindings without claiming classification review."""
    release = release.resolve(strict=True)
    policy_path = release / "control" / "policy.json"
    configured_policy = Path(os.environ.get("V4_RESEARCH_RETENTION_POLICY", ""))
    if (configured_policy != policy_path or policy_path.resolve(strict=True) != policy_path
            or os.environ.get("V4_RESEARCH_RETENTION_POLICY_SHA256") != expected_sha
            or not isinstance(expected_sha, str) or sha(policy_path) != expected_sha):
        reject("CANDIDATE_POLICY_SHA_DRIFT")
    policy = json.loads(policy_path.read_bytes())
    data_root = Path(policy["data_root"])
    return_root = Path(policy["run_root"])
    daemon_data_root = Path(os.environ.get("V4_RESEARCH_PANEL_A_DATA_ROOT", ""))
    daemon_return_root = Path(os.environ.get("V4_RESEARCH_PANEL_A_RETURN_ROOT", ""))
    if (not daemon_data_root.is_absolute() or not daemon_return_root.is_absolute()
            or data_root != daemon_data_root or return_root != daemon_return_root):
        reject("CANDIDATE_POLICY_DAEMON_ROOT_BINDING_DRIFT")
    return policy


def load_reviewed_candidate_policy(release: Path, proof: dict) -> dict:
    """Read only the policy/classification actually loaded by the daemon."""
    release = release.resolve(strict=True)
    manifest = json.loads((release / "release-manifest.json").read_bytes())
    if manifest.get("release_id") != proof.get("release_id"):
        reject("CANDIDATE_RELEASE_ID_DRIFT")
    policy_ref_sha = proof.get("candidate_policy_sha256")
    policy = load_candidate_policy_roots(release, policy_ref_sha)
    governance = policy.get("governance") or {}
    reference = governance.get("qfq_legacy_classification")
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        reject("CANDIDATE_POLICY_CLASSIFICATION_REFERENCE_MISSING")
    classification_path = Path(reference["path"])
    control_root = release / "control"
    if (not classification_path.is_absolute() or classification_path.resolve(strict=True) != classification_path
            or control_root.resolve(strict=True) != control_root
            or not classification_path.is_relative_to(control_root)):
        reject("CANDIDATE_POLICY_CLASSIFICATION_PATH_INVALID")
    if (not isinstance(reference["sha256"], str) or sha(classification_path) != reference["sha256"]
            or proof.get("candidate_classification_sha256") != reference["sha256"]):
        reject("CANDIDATE_POLICY_CLASSIFICATION_SHA_DRIFT")
    classification = json.loads(classification_path.read_bytes())
    if (classification.get("schema") != "v4.qfq_legacy_task_scope.v1"
            or classification.get("status") != "REVIEWED_TASK_SCOPES"
            or classification.get("evidence_closed") is not True
            or not isinstance(classification.get("reviewer"), str)
            or not classification["reviewer"].strip()):
        reject("CANDIDATE_POLICY_CLASSIFICATION_REVIEW_REQUIRED")

    return policy


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--identity-parity":
        return identity_parity_main()
    if len(sys.argv) != 10:
        reject("CANDIDATE_GATE_ARGUMENT_COUNT")
    release = Path(sys.argv[1]).resolve(strict=True)
    proof_path = Path(sys.argv[2]).resolve(strict=True)
    proof_sha = sys.argv[3]
    identity_path = Path(sys.argv[4]).resolve(strict=True)
    identity_sha = sys.argv[5]
    target_date = sys.argv[6]
    expected_key = sys.argv[7]
    expected_registry_sha = sys.argv[8]
    expected_environment_sha = sys.argv[9]
    app = release / "app"
    sys.dont_write_bytecode = True

    if sha(proof_path) != proof_sha:
        reject("CLASSIFICATION_RECEIPT_SHA_DRIFT")
    proof = json.loads(proof_path.read_bytes())
    interpreter = Path(sys.executable).resolve(strict=True)
    if sha(interpreter) != proof.get("expected_child_python_sha256"):
        reject("ACTUAL_CHILD_PYTHON_SHA_DRIFT")
    if proof.get("status") != "PASS" or proof.get("evidence_closed") is not True:
        reject("CLASSIFICATION_NOT_REVIEWED_PASS")
    if proof.get("target_date") != target_date or proof.get("task_key") != expected_key:
        reject("CLASSIFICATION_TARGET_OR_TASK_KEY_DRIFT")
    if (proof.get("child_identity_receipt_path") != str(identity_path)
            or proof.get("child_identity_receipt_sha256") != identity_sha
            or proof.get("expected_child_environment_sha256") != expected_environment_sha):
        reject("CLASSIFICATION_DAEMON_QFQ_IDENTITY_REFERENCE_DRIFT")
    kwargs = proof.get("qfq_kwargs")
    if not isinstance(kwargs, dict):
        reject("EXPECTED_CHILD_ARGUMENTS_REQUIRED")

    module = importlib.import_module("ops.research_panel_qfq")
    from ops.research_storage_governance import Registry, configuration, qfq_invocation_key
    from ops.research_qfq_task_continuity import qfq_admission_context, unclassified_qfq_rows

    if Path(module.__file__).resolve(strict=True) != (app / "ops" / "research_panel_qfq.py"):
        reject("CANDIDATE_QFQ_OWNER_IMPORT_DRIFT")
    for name in ("ops.research_storage_governance", "ops.research_qfq_task_continuity"):
        if not Path(sys.modules[name].__file__).resolve(strict=True).is_relative_to(app):
            reject("CANDIDATE_QFQ_GUARD_IMPORT_DRIFT:" + name)

    policy = load_reviewed_candidate_policy(release, proof)
    manifest = json.loads((release / "release-manifest.json").read_bytes())
    data_root = Path(policy["data_root"])
    return_root = Path(policy["run_root"])
    target = int(target_date)
    receipt = load_child_identity(identity_path, identity_sha)
    parity = verify_child_operation_key(
        receipt, release=release, target_date=target_date,
        expected_key=expected_key, expected_registry_sha=expected_registry_sha,
        expected_environment_sha=expected_environment_sha, policy=policy,
        module=module, kwargs=kwargs,
    )
    calculated_key = parity["candidate_operation_key"]
    config = configuration(policy)
    if config is None:
        reject("QFQ_STORAGE_GOVERNANCE_DISABLED")
    registry = Registry(config, data_root)
    registry_raw = registry.path.read_bytes()
    if sha(registry.path) != expected_registry_sha:
        reject("REGISTRY_CHANGED_AFTER_REVIEW")
    state = registry.read()
    if expected_key in state["tasks"]:
        reject("TARGET_TASK_KEY_ALREADY_EXISTS")
    unknown = unclassified_qfq_rows(state, return_root, expected_key)
    if not unknown:
        reject("EXPECTED_LEGACY_ROWS_NOT_FOUND")
    required_legacy = proof.get("required_unclassified_task_keys")
    if (not isinstance(required_legacy, list) or len(required_legacy) < 2
            or not set(required_legacy).issubset(unknown)):
        reject("EXPECTED_D20_D11_LEGACY_ROWS_NOT_CLOSED")
    context = qfq_admission_context(module, policy, data_root, return_root, target, expected_key)
    if context.get("classified_rows") != unknown:
        reject("CLASSIFICATION_DOES_NOT_CLOSE_EVERY_UNCLASSIFIED_ROW")

    old_key = proof.get("old_task_key")
    old_row = state["tasks"].get(old_key)
    if not isinstance(old_row, dict):
        reject("OLD_RESERVATION_ROW_MISSING")
    canonical = hashlib.sha256(json.dumps(old_row, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode()).hexdigest()
    if canonical != proof.get("old_row_sha256"):
        reject("OLD_RESERVATION_ROW_SHA_DRIFT")
    category_remaining = old_row["reserved_bytes"] - old_row.get("logical_written_bytes", old_row.get("written_bytes", 0))
    physical_remaining = old_row["reserved_bytes"] - old_row.get("written_bytes", 0)
    if category_remaining != 51_350_585_740 or physical_remaining != 51_335_737_344:
        reject("OLD_RESERVATION_REMAINING_DRIFT")
    if old_row.get("state") not in {"FAILED_RECOVERABLE", "SPACE_BLOCKED"}:
        reject("OLD_RESERVATION_STATE_CHANGED")
    if sha(registry.path) != expected_registry_sha or registry.path.read_bytes() != registry_raw:
        reject("REGISTRY_CHANGED_DURING_READONLY_CLASSIFICATION")
    print(json.dumps({"status": "PASS_READONLY_REVIEWED_DISTINCT_DATE_SCOPE",
                      "release_id": manifest["release_id"], "target_date": target_date,
                      "task_key": calculated_key, "attempt": "NOT_CREATED",
                      "generation": "NOT_CREATED", "registry_sha256": expected_registry_sha,
                      "child_identity_receipt_sha256": identity_sha,
                      "child_operation_key_parity": parity,
                      "old_task_key": old_key, "old_row_sha256": canonical,
                      "old_category_remaining_bytes": category_remaining,
                      "old_physical_peak_remaining_bytes": physical_remaining,
                      "migration": "BLOCKED", "classified_rows": unknown,
                      "production_allowed": False, "registry_mutated": False},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}))
        raise SystemExit(2)
