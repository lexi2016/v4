"""Read-only evaluation of the frozen candidate's legacy-date classification."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject(reason: str) -> None:
    raise RuntimeError(reason)


def load_reviewed_candidate_policy(release: Path, proof: dict) -> dict:
    """Read only the policy/classification actually loaded by the daemon."""
    release = release.resolve(strict=True)
    manifest = json.loads((release / "release-manifest.json").read_bytes())
    if manifest.get("release_id") != proof.get("release_id"):
        reject("CANDIDATE_RELEASE_ID_DRIFT")
    policy_path = release / "control" / "policy.json"
    configured_policy = Path(os.environ.get("V4_RESEARCH_RETENTION_POLICY", ""))
    policy_ref_sha = proof.get("candidate_policy_sha256")
    configured_policy_sha = os.environ.get("V4_RESEARCH_RETENTION_POLICY_SHA256")
    if (configured_policy != policy_path or policy_path.resolve(strict=True) != policy_path
            or configured_policy_sha != policy_ref_sha
            or not isinstance(policy_ref_sha, str) or sha(policy_path) != policy_ref_sha):
        reject("CANDIDATE_POLICY_SHA_DRIFT")
    policy = json.loads(policy_path.read_bytes())
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

    data_root = Path(policy["data_root"])
    return_root = Path(policy["run_root"])
    daemon_data_root = Path(os.environ.get("V4_RESEARCH_PANEL_A_DATA_ROOT", ""))
    daemon_return_root = Path(os.environ.get("V4_RESEARCH_PANEL_A_RETURN_ROOT", ""))
    if (not daemon_data_root.is_absolute() or not daemon_return_root.is_absolute()
            or data_root != daemon_data_root or return_root != daemon_return_root):
        reject("CANDIDATE_POLICY_DAEMON_ROOT_BINDING_DRIFT")
    return policy


def main() -> int:
    release = Path(sys.argv[1]).resolve(strict=True)
    proof_path = Path(sys.argv[2]).resolve(strict=True)
    proof_sha = sys.argv[3]
    target_date = sys.argv[4]
    expected_key = sys.argv[5]
    expected_registry_sha = sys.argv[6]
    app = release / "app"
    runtime = release / "runtime" / "venvs" / "v4-mac"
    site = runtime / "lib" / "python3.14" / "site-packages"
    for item in (app, site):
        sys.path.insert(0, str(item))
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
    calculated_key = qfq_invocation_key(module, data_root, target, kwargs)
    if calculated_key != expected_key:
        reject("CANDIDATE_CHILD_OPERATION_KEY_DRIFT")
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
