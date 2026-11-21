"""Hash-bound Main-only forward switch using the reviewed V4 controller."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta


HERE = Path(__file__).resolve().parent
SCHEMA = "v4.main_only_cutover.v1"
CONTROLLER_SHA256 = "739146905b0ef53df95fc7b1a5189e4e4dd93b2d2d5f16803b5535f06f206cc0"
DEPENDENCY_SHAS = {
    "infrastructure/__init__.py": "46068d69d6783fdcd33b3428ae3c7e8e690d5149f4f00837f6b1d1184dd6f47b",
    "infrastructure/interprocess_lock.py": "9b0cb80a1fe1bcbdebb3936134c8f0bad258c9c9236356022551ff7753351df0",
    "infrastructure/owned_io.py": "9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0",
    "ops/api_release_integration.py": "4bcda4d0a2a26d15616ab0ba809ad86c0f874bfbcc7367cbc54cd1f77d56597d",
}
OLD_CATEGORY_REMAINING = 51_350_585_740
OLD_PHYSICAL_REMAINING = 51_335_737_344
RESERVATION_STATES = {"RUNNING", "VALIDATING", "FAILED_RECOVERABLE", "SPACE_BLOCKED"}


class CutoverBlocked(RuntimeError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def read_json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise CutoverBlocked("JSON_OBJECT_REQUIRED:" + path.name)
    return value


def read_regular_nofollow(path: Path) -> bytes:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise CutoverBlocked("EXACT_REGULAR_FILE_REQUIRED:" + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise CutoverBlocked("EXACT_REGULAR_FILE_REQUIRED:" + str(path))
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        visible = path.lstat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if identity(before) != identity(after) or identity(after) != identity(visible):
            raise CutoverBlocked("FILE_CHANGED_DURING_READ:" + str(path))
        return b"".join(chunks)
    finally:
        os.close(fd)


def exact_file(path: Path, expected_sha: str) -> bytes:
    raw = read_regular_nofollow(path)
    if digest(raw) != expected_sha:
        raise CutoverBlocked("SHA_DRIFT:" + str(path))
    return raw


def evidence(path_text: str, expected_sha: str) -> dict:
    path = Path(path_text)
    return read_json(path) if exact_file(path, expected_sha) else {}


def check_evidence(plan: dict, *, now: datetime | None = None) -> dict:
    """Require reviewed identity/classification and fresh, passing capacity evidence."""
    gates = plan.get("admission_evidence")
    if not isinstance(gates, dict) or set(gates) != {
        "old_task_unique_attribution", "new_date_reviewed_classification",
        "actual_capacity_preflight", "final_cache_negative",
    }:
        raise CutoverBlocked("ALL_FOUR_REVIEWED_GATES_REQUIRED")

    rows = {}
    for name, ref in gates.items():
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not is_sha256(ref["sha256"])):
            raise CutoverBlocked("GATE_REFERENCE_INVALID:" + name)
        payload = evidence(ref["path"], ref["sha256"])
        accepted_unknown_old = (name == "old_task_unique_attribution"
                                and payload.get("status") == "CANNOT_CONFIRM"
                                and payload.get("migration") == "BLOCKED")
        if ((payload.get("status") != "PASS" and not accepted_unknown_old)
                or (payload.get("evidence_closed") is not True and not accepted_unknown_old)):
            raise CutoverBlocked("GATE_NOT_PASSED:" + name)
        if not isinstance(payload.get("reviewer"), str) or not payload["reviewer"].strip():
            raise CutoverBlocked("INDEPENDENT_REVIEWER_REQUIRED:" + name)
        rows[name] = payload

    old = rows["old_task_unique_attribution"]
    for field in ("old_task_key", "old_target_date", "old_row_sha256"):
        if not isinstance(old.get(field), str) or not old[field]:
            raise CutoverBlocked("OLD_TASK_IDENTITY_INCOMPLETE:" + field)
    if not is_sha256(old["old_task_key"]) or not is_sha256(old["old_row_sha256"]):
        raise CutoverBlocked("OLD_TASK_IDENTITY_SHA_INVALID")
    try:
        datetime.strptime(old["old_target_date"], "%Y%m%d")
    except ValueError:
        raise CutoverBlocked("OLD_TASK_DATE_INVALID") from None
    if (old.get("old_category_remaining_bytes") != OLD_CATEGORY_REMAINING
            or old.get("old_physical_peak_remaining_bytes") != OLD_PHYSICAL_REMAINING):
        raise CutoverBlocked("OLD_RESERVATION_EVIDENCE_DRIFT")
    if old["status"] == "PASS":
        for field in ("attempt_id", "generation", "input_sha256"):
            if not isinstance(old.get(field), str) or not old[field]:
                raise CutoverBlocked("OLD_TASK_UNIQUE_BINDING_INCOMPLETE:" + field)
    elif old["status"] != "CANNOT_CONFIRM" or old.get("migration") != "BLOCKED":
        raise CutoverBlocked("OLD_TASK_UNIQUE_ATTRIBUTION_STATUS_INVALID")

    new = rows["new_date_reviewed_classification"]
    target_date = plan.get("target_date")
    for field in ("task_key", "expected_child_environment_sha256", "computation_identity_sha256",
                  "expected_child_python_sha256", "registry_sha256", "candidate_policy_sha256",
                  "candidate_classification_sha256", "release_id"):
        if not isinstance(new.get(field), str) or not new[field]:
            raise CutoverBlocked("NEW_TASK_IDENTITY_INCOMPLETE:" + field)
    if (any(not is_sha256(new[field]) for field in ("task_key", "computation_identity_sha256",
            "expected_child_environment_sha256", "expected_child_python_sha256", "registry_sha256",
            "candidate_policy_sha256", "candidate_classification_sha256"))
            or new.get("release_id") != plan.get("release_id")):
        raise CutoverBlocked("NEW_TASK_IDENTITY_SHA_OR_RELEASE_INVALID")
    try:
        datetime.strptime(str(target_date), "%Y%m%d")
    except ValueError:
        raise CutoverBlocked("TARGET_DATE_INVALID") from None
    if (new.get("target_date") != target_date or new.get("classification_basis") != "DISTINCT_DATE"
            or new.get("task_key") == old["old_task_key"] or new.get("old_task_key") != old["old_task_key"]
            or new.get("task_key") != new.get("computation_identity_sha256")
            or new.get("old_row_sha256") != old["old_row_sha256"]
            or new.get("target_date") == old["old_target_date"]):
        raise CutoverBlocked("NEW_DATE_CLASSIFICATION_BINDING_DRIFT")
    if not isinstance(new.get("qfq_kwargs"), dict):
        raise CutoverBlocked("NEW_QFQ_ARGUMENTS_REQUIRED")
    if (new.get("category") != "ordinary"
            or not isinstance(new.get("required_unclassified_task_keys"), list)
            or len(new["required_unclassified_task_keys"]) < 2
            or any(not is_sha256(key) for key in new["required_unclassified_task_keys"])
            or new["old_task_key"] not in new["required_unclassified_task_keys"]):
        raise CutoverBlocked("DISTINCT_DATE_LEGACY_SCOPE_BINDING_REQUIRED")
    if (new.get("old_category_remaining_bytes") != OLD_CATEGORY_REMAINING
            or new.get("old_physical_peak_remaining_bytes") != OLD_PHYSICAL_REMAINING
            or new.get("migration") != "BLOCKED"):
        raise CutoverBlocked("OLD_RESERVATION_PRESERVATION_BINDING_DRIFT")

    capacity = rows["actual_capacity_preflight"]
    if capacity.get("target_date") != target_date or capacity.get("task_key") != new["task_key"]:
        raise CutoverBlocked("CAPACITY_TARGET_IDENTITY_DRIFT")
    if (capacity.get("registry_sha256") != new.get("registry_sha256")
            or capacity.get("old_row_sha256") != old["old_row_sha256"]
            or capacity.get("old_category_remaining_bytes") != OLD_CATEGORY_REMAINING
            or capacity.get("old_physical_peak_remaining_bytes") != OLD_PHYSICAL_REMAINING):
        raise CutoverBlocked("CAPACITY_LEDGER_BINDING_DRIFT")
    timestamp = capacity.get("measured_at")
    try:
        measured_at = datetime.fromisoformat(timestamp)
        current = now or datetime.now().astimezone()
        if measured_at.tzinfo is None or current - measured_at > timedelta(minutes=5) or measured_at > current:
            raise ValueError
    except (TypeError, ValueError):
        raise CutoverBlocked("CAPACITY_PREFLIGHT_STALE_OR_UNDATED") from None

    if (rows["final_cache_negative"].get("runtime_release_id") != plan.get("release_id")
            or rows["final_cache_negative"].get("status") != "PASS"
            or rows["final_cache_negative"].get("evidence_closed") is not True):
        raise CutoverBlocked("CACHE_NEGATIVE_RELEASE_MISMATCH")
    return rows


def check_activation_authorization(plan: dict, plan_sha: str, approval: dict,
                                   chat_review: dict, chat_review_sha: str) -> None:
    required = {
        "schema": "v4.main_only_explicit_authorization.v1",
        "action": "ACTIVATE_MAIN_ONLY",
        "scope": "Main LaunchAgent plist CAS only",
        "plan_sha256": plan_sha,
        "release_id": plan.get("release_id"),
        "target_date": plan.get("target_date"),
        "migration": "BLOCKED",
        "stage_reload": False,
        "api_reload": False,
        "registry_write": False,
        "current_pointer_write": False,
        "reservation_release": False,
        "approved_by_user": True,
        "chat_review_sha256": chat_review_sha,
    }
    if any(approval.get(k) != v for k, v in required.items()):
        raise CutoverBlocked("EXACT_EXPLICIT_MAIN_ONLY_AUTHORIZATION_REQUIRED")
    check_user_approval_provenance(approval)
    proofs = plan["admission_evidence"]
    if approval.get("admission_evidence_sha256") != {k: v["sha256"] for k, v in proofs.items()}:
        raise CutoverBlocked("AUTHORIZATION_EVIDENCE_SET_DRIFT")
    if chat_review.get("verdict") != "PASS" or chat_review.get("package_sha256") != plan.get("release_package_sha256"):
        raise CutoverBlocked("CHAT_REVIEW_NOT_PASS_FOR_THIS_PLAN")


def check_rollback_authorization(plan: dict, plan_sha: str, approval: dict,
                                 chat_review: dict, chat_review_sha: str) -> None:
    role = plan["controller_plan"]["roles"][0]
    required = {
        "schema": "v4.main_only_explicit_authorization.v1",
        "action": "ROLLBACK_MAIN_ONLY",
        "scope": "Main LaunchAgent plist CAS only",
        "plan_sha256": plan_sha,
        "release_id": plan["release_id"],
        "target_date": plan["target_date"],
        "installed_candidate_plist_sha256": role["candidate_plist_sha256"],
        "restore_plist_sha256": role["current_plist_sha256"],
        "stage_reload": False,
        "api_reload": False,
        "registry_write": False,
        "current_pointer_write": False,
        "reservation_release": False,
        "approved_by_user": True,
        "chat_review_sha256": chat_review_sha,
    }
    if any(approval.get(k) != v for k, v in required.items()):
        raise CutoverBlocked("EXACT_EXPLICIT_MAIN_ONLY_ROLLBACK_AUTHORIZATION_REQUIRED")
    check_user_approval_provenance(approval)
    if (chat_review.get("verdict") != "PASS"
            or chat_review.get("package_sha256") != plan.get("release_package_sha256")):
        raise CutoverBlocked("CHAT_REVIEW_NOT_PASS_FOR_THIS_PACKAGE")


def check_user_approval_provenance(approval: dict) -> None:
    note = approval.get("approval_note")
    if (not isinstance(note, dict) or set(note) != {"path", "sha256"}
            or not is_sha256(note.get("sha256"))
            or approval.get("approval_note_sha256") != note.get("sha256")):
        raise CutoverBlocked("USER_APPROVAL_NOTE_BINDING_REQUIRED")
    raw = exact_file(Path(note["path"]), note["sha256"])
    try:
        if not raw.decode("utf-8").strip():
            raise ValueError
        approved_at = datetime.fromisoformat(approval.get("approved_at", ""))
        now = datetime.now().astimezone()
        if approved_at.tzinfo is None or approved_at > now:
            raise ValueError
    except (UnicodeDecodeError, TypeError, ValueError):
        raise CutoverBlocked("USER_APPROVAL_PROVENANCE_REQUIRED") from None


def validate_plan(plan: dict) -> None:
    if plan.get("schema") != SCHEMA or plan.get("scope") != "Main-only" or plan.get("migration") != "BLOCKED":
        raise CutoverBlocked("UNREVIEWED_MAIN_ONLY_PLAN")
    release_root = Path(plan.get("release_root", ""))
    candidate_parent = Path(plan.get("approved_candidate_parent", ""))
    if (not release_root.is_absolute() or not candidate_parent.is_absolute()
            or release_root.resolve(strict=True) != release_root
            or candidate_parent.resolve(strict=True) != candidate_parent
            or release_root.parent != candidate_parent):
        raise CutoverBlocked("CANDIDATE_ROOT_BINDING_INVALID")
    if plan.get("target_date") is None or len(str(plan["target_date"])) != 8:
        raise CutoverBlocked("TARGET_DATE_REQUIRED")
    role_plan = plan.get("controller_plan")
    if (not isinstance(role_plan, dict) or len(role_plan.get("roles", [])) != 1
            or role_plan["roles"][0].get("role") != "main"
            or role_plan.get("verification_command") is not None):
        raise CutoverBlocked("MAIN_ONLY_CONTROLLER_PLAN_REQUIRED")
    if role_plan["roles"][0].get("candidate_release_id") != plan["release_id"]:
        raise CutoverBlocked("CANDIDATE_RELEASE_ID_DRIFT")
    if role_plan["roles"][0].get("candidate_plist") != str(release_root / "launchd.plist"):
        raise CutoverBlocked("CANDIDATE_PLIST_OUTSIDE_RELEASE_ROOT")
    plist = plistlib.loads(Path(role_plan["roles"][0]["candidate_plist"]).read_bytes())
    env = plist.get("EnvironmentVariables", {})
    if (env.get("V4_RELEASE_ID") != plan["release_id"]
            or env.get("V4_APP_ROOT") != str(release_root / "app")
            or env.get("V4_RUNTIME_ROOT") != str(release_root / "runtime")
            or env.get("V4_RELEASE_MANIFEST_PATH") != str(release_root / "release-manifest.json")
            or env.get("V4_RELEASE_MANIFEST_SHA256") != role_plan["roles"][0].get("candidate_manifest_sha256")):
        raise CutoverBlocked("FINAL_CANDIDATE_RUNTIME_BINDING_MISMATCH")


def verify_controller_sources() -> tuple[Path, dict[str, Path]]:
    source = HERE / "switch_reviewed_roles.py"
    if digest(source.read_bytes()) != CONTROLLER_SHA256:
        raise CutoverBlocked("REVIEWED_CONTROLLER_SHA_DRIFT")
    repo = source.resolve(strict=True).parents[3]
    paths = {}
    for relative, expected in DEPENDENCY_SHAS.items():
        original = repo / relative
        frozen = HERE / "controller_dependencies" / relative
        if digest(original.read_bytes()) != expected or digest(frozen.read_bytes()) != expected:
            raise CutoverBlocked("REVIEWED_CONTROLLER_DEPENDENCY_SHA_DRIFT:" + relative)
        paths[relative] = original
    if os.path.lexists(repo / "ops/__init__.py"):
        raise CutoverBlocked("OPS_NAMESPACE_BOUNDARY_DRIFT")
    return source, paths


def load_controller():
    source, dependencies = verify_controller_sources()
    if any(name.split(".")[0] in {"infrastructure", "ops"} for name in sys.modules):
        raise CutoverBlocked("RELEASE_CONTROLLER_DEPENDENCY_PRELOADED")
    import importlib.util
    spec = importlib.util.spec_from_file_location("r4_reviewed_switch_controller", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for relative, path in dependencies.items():
        name = relative[:-3].replace("/", ".")
        if Path(sys.modules[name].__file__).resolve(strict=True) != path.resolve(strict=True):
            raise CutoverBlocked("RELEASE_CONTROLLER_IMPORTED_WRONG_DEPENDENCY:" + relative)
    return module


def check_candidate_source_bindings(plan: dict) -> dict:
    role = plan["controller_plan"]["roles"][0]
    root = Path(role["candidate_plist"]).parent
    pins_ref = plan.get("candidate_pins")
    if not isinstance(pins_ref, dict):
        raise CutoverBlocked("CANDIDATE_PINS_BINDING_REQUIRED")
    pins_path = Path(pins_ref["path"])
    pins_raw = exact_file(pins_path, pins_ref["sha256"])
    pins = json.loads(pins_raw)
    bindings = pins.get("source_bindings")
    if not isinstance(bindings, list) or len(bindings) != 95:
        raise CutoverBlocked("EXPECTED_95_SOURCE_BINDINGS")
    readbacks = []
    for row in bindings:
        path = Path(row["path"])
        raw = read_regular_nofollow(path)
        actual = digest(raw)
        if actual != row["sha256"]:
            raise CutoverBlocked("SOURCE_BINDING_DRIFT:" + str(path))
        readbacks.append({"path": str(path), "sha256": actual})
    if len({row["path"] for row in readbacks}) != 95:
        raise CutoverBlocked("SOURCE_BINDING_PATH_DUPLICATE")
    return {"verified": 95, "pins_sha256": digest(pins_raw), "readbacks": readbacks}


def check_source_inventory(pins_path: Path, expected_sha: str) -> dict:
    pins_raw = exact_file(pins_path, expected_sha)
    pins = json.loads(pins_raw)
    bindings = pins.get("source_bindings")
    if not isinstance(bindings, list) or len(bindings) != 95:
        raise CutoverBlocked("EXPECTED_95_SOURCE_BINDINGS")
    for row in bindings:
        path = Path(row["path"])
        raw = read_regular_nofollow(path)
        actual = digest(raw)
        if actual != row["sha256"]:
            raise CutoverBlocked("SOURCE_BINDING_DRIFT:" + str(path))
    return {"verified": 95, "pins_sha256": digest(pins_raw)}


def run_candidate_qfq_admission(plan: dict, evidence_rows: dict) -> dict:
    """Run the exact final v4-mac child import/admission guard without claim or writes."""
    release = Path(plan["release_root"])
    runtime = release / "runtime" / "venvs" / "v4-mac"
    python = runtime / "bin" / "python"
    proof_ref = plan["admission_evidence"]["new_date_reviewed_classification"]
    proof_path = Path(proof_ref["path"])
    new = evidence_rows["new_date_reviewed_classification"]
    role = plan["controller_plan"]["roles"][0]
    candidate = plistlib.loads(Path(role["candidate_plist"]).read_bytes())
    environment = dict(candidate.get("EnvironmentVariables", {}))
    environment_hash = digest(json.dumps(environment, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode())
    if environment_hash != new.get("expected_child_environment_sha256"):
        raise CutoverBlocked("CANDIDATE_CHILD_ENVIRONMENT_SHA_DRIFT")
    child_args = new.get("child_python_args")
    if (not isinstance(child_args, list) or not child_args or child_args[0] != "-B"
            or "-S" in child_args or any(not isinstance(v, str) for v in child_args)):
        raise CutoverBlocked("ACTUAL_CHILD_PYTHON_ARGS_REQUIRED")
    if digest(python.read_bytes()) != new.get("expected_child_python_sha256"):
        raise CutoverBlocked("ACTUAL_CHILD_PYTHON_SHA_DRIFT")
    command = [str(python), *child_args, str(HERE / "candidate_qfq_gate.py"), str(release),
               str(proof_path), proof_ref["sha256"], str(plan["target_date"]), new["task_key"],
               new["registry_sha256"]]
    result = subprocess.run(command, cwd=release / "app", env=environment,
                            capture_output=True, text=True, timeout=90)
    try:
        observed = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        observed = {"status": "BLOCKED", "reason": (result.stderr or result.stdout)[-1000:]}
    if (result.returncode != 0 or observed.get("status") != "PASS_READONLY_REVIEWED_DISTINCT_DATE_SCOPE"
            or observed.get("task_key") != new["task_key"] or observed.get("registry_sha256") != new["registry_sha256"]
            or observed.get("target_date") != plan["target_date"]):
        raise CutoverBlocked("CANDIDATE_CHILD_QFQ_ADMISSION_BLOCKED:" + str(observed.get("reason", observed.get("status"))))
    if (observed.get("old_task_key") != evidence_rows["old_task_unique_attribution"]["old_task_key"]
            or observed.get("old_row_sha256") != evidence_rows["old_task_unique_attribution"]["old_row_sha256"]
            or observed.get("old_category_remaining_bytes") != OLD_CATEGORY_REMAINING
            or observed.get("old_physical_peak_remaining_bytes") != OLD_PHYSICAL_REMAINING):
        raise CutoverBlocked("CANDIDATE_CHILD_OLD_RESERVATION_BINDING_DRIFT")
    return {"command": command, "return_code": result.returncode, "stdout": observed,
            "stderr": result.stderr, "python_sha256": digest(python.read_bytes())}


def check_current_capacity(plan: dict, admission: dict, controller) -> dict:
    """Recompute Registry.space physical/category gates without reserving or writing."""
    role = plan["controller_plan"]["roles"][0]
    old_plist = plistlib.loads(Path(role["rollback_plist"]).read_bytes())
    new_plist = plistlib.loads(Path(role["candidate_plist"]).read_bytes())
    old_env = old_plist["EnvironmentVariables"]
    new_env = new_plist["EnvironmentVariables"]
    policy_path = Path(new_env["V4_RESEARCH_RETENTION_POLICY"])
    policy_sha = new_env["V4_RESEARCH_RETENTION_POLICY_SHA256"]
    policy = json.loads(exact_file(policy_path, policy_sha))
    governance = policy["governance"]
    registry_path = Path(governance["registry_root"]) / "registry.json"
    registry_raw = registry_path.read_bytes()
    registry_sha = digest(registry_raw)
    state = json.loads(registry_raw)
    task_rows = state.get("tasks")
    if not isinstance(task_rows, dict):
        raise CutoverBlocked("REGISTRY_TASKS_REQUIRED")
    old_proof = admission["old_task_unique_attribution"]
    new_proof = admission["new_date_reviewed_classification"]
    old_key = old_proof["old_task_key"]
    target_key = new_proof["task_key"]
    old = task_rows.get(old_key)
    if not isinstance(old, dict) or digest(json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) != old_proof["old_row_sha256"]:
        raise CutoverBlocked("OLD_TASK_ROW_SHA_DRIFT")
    if old.get("state") not in {"FAILED_RECOVERABLE", "SPACE_BLOCKED"}:
        raise CutoverBlocked("OLD_TASK_STATE_CHANGED")
    if (old.get("reserved_bytes", 0) - old.get("logical_written_bytes", old.get("written_bytes", 0))
            != OLD_CATEGORY_REMAINING
            or old.get("reserved_bytes", 0) - old.get("written_bytes", 0) != OLD_PHYSICAL_REMAINING):
        raise CutoverBlocked("OLD_RESERVATION_REMAINING_DRIFT")
    if target_key in task_rows:
        raise CutoverBlocked("TARGET_TASK_ALREADY_IN_REGISTRY")
    if registry_sha != new_proof.get("registry_sha256"):
        raise CutoverBlocked("REGISTRY_CHANGED_AFTER_CAPACITY_REVIEW")
    if str(old_env.get("V4_RESEARCH_PANEL_A_DATA_ROOT")) != str(new_env.get("V4_RESEARCH_PANEL_A_DATA_ROOT")):
        raise CutoverBlocked("REGISTRY_DATA_ROOT_CHANGED")

    reserved_states = {"RUNNING", "VALIDATING", "FAILED_RECOVERABLE", "SPACE_BLOCKED"}
    physical_other = 0
    category_other = 0
    for key, row in task_rows.items():
        if key == target_key or row.get("state") not in reserved_states:
            continue
        physical_other += max(0, row.get("reserved_bytes", 0) - row.get("written_bytes", 0))
        if row.get("category") == new_proof.get("category"):
            category_other += max(0, row.get("reserved_bytes", 0)
                                  - row.get("logical_written_bytes", row.get("written_bytes", 0)))

    disk_root = Path(new_env["V4_RESEARCH_PANEL_A_DATA_ROOT"])
    disk = shutil.disk_usage(disk_root)
    target_peak = new_proof.get("predicted_peak_bytes")
    category_used = admission["actual_capacity_preflight"].get("category_used_bytes")
    budget = governance["ordinary_peak_budget_bytes"] if new_proof.get("category") == "ordinary" else governance["debug_budget_bytes"]
    for value in (target_peak, category_used, budget, governance["reserve_bytes"], governance["safety_bytes"]):
        if type(value) is not int or value < 0:
            raise CutoverBlocked("CAPACITY_NUMERIC_INPUT_INVALID")
    min_ratio = governance["minimum_free_ratio"]
    if type(min_ratio) not in (int, float) or min_ratio <= 0:
        raise CutoverBlocked("CAPACITY_RATIO_POLICY_INVALID")
    old_physical_in_other = max(0, old["reserved_bytes"] - old.get("written_bytes", 0))
    old_category_in_other = max(0, old["reserved_bytes"] - old.get("logical_written_bytes", old.get("written_bytes", 0)))
    if old_physical_in_other != OLD_PHYSICAL_REMAINING or old_category_in_other != OLD_CATEGORY_REMAINING:
        raise CutoverBlocked("OLD_RESERVATION_ACCOUNTING_DRIFT")
    # Registry.space() counts all active reservations except the requested task.
    physical_post = disk.free - physical_other - target_peak
    category_post = category_used + category_other + target_peak
    if disk.total <= 0 or disk.free / disk.total < min_ratio:
        raise CutoverBlocked("CAPACITY_MINIMUM_FREE_RATIO_BLOCKED")
    if physical_post < governance["reserve_bytes"] + governance["safety_bytes"]:
        raise CutoverBlocked("CAPACITY_PHYSICAL_RESERVATION_BLOCKED")
    if category_post > budget:
        raise CutoverBlocked("CAPACITY_CATEGORY_BUDGET_BLOCKED")
    reviewed = admission["actual_capacity_preflight"]
    if reviewed.get("category_other_remaining_bytes") != category_other:
        raise CutoverBlocked("CAPACITY_CATEGORY_LEDGER_MISMATCH")
    return {"registry_sha256": registry_sha, "old_category_remaining_bytes": old_category_in_other,
            "old_physical_peak_remaining_bytes": old_physical_in_other, "free_bytes": disk.free,
            "total_bytes": disk.total, "physical_other_remaining_bytes": physical_other,
            "target_peak_bytes": target_peak, "physical_after_bytes": physical_post,
            "physical_floor_bytes": governance["reserve_bytes"] + governance["safety_bytes"],
            "category_used_bytes": category_used, "category_other_remaining_bytes": category_other,
            "category_after_bytes": category_post, "category_budget_bytes": budget,
            "ratio_minimum": min_ratio, "ratio_current": disk.free / disk.total}


def _existing_regular_lock(path: Path) -> int:
    if path.is_symlink() or not path.is_file():
        raise CutoverBlocked("EXISTING_LOCK_FILE_REQUIRED:" + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise CutoverBlocked("LOCK_FILE_NOT_REGULAR:" + str(path))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise CutoverBlocked("SCHEDULER_LANE_BUSY:" + str(path)) from None
    return fd


def acquire_switch_locks(controller, role: dict, plan: dict, stack: ExitStack) -> None:
    label = role["label"]
    env = role["old_cfg"]["EnvironmentVariables"]
    dispatch_root = Path(env["V4_DISPATCH_LEDGER_ROOT"])
    lane_root = dispatch_root / "scheduler_lane_owners"
    for lane in ("A_LONG", "DEFAULT"):
        path = lane_root / f"{lane}.lock"
        fd = _existing_regular_lock(path)
        stack.callback(os.close, fd)
    # Hold other role release mutexes so their 95-source pins cannot change mid-CAS.
    for other_label in ("com.lexi.stage-center.scheduler", "com.lexi.v4.api"):
        other_prefix = controller.LAUNCH_AGENTS / f".{other_label}.release.lock"
        if not other_prefix.with_name(other_prefix.name + ".mutex").is_file():
            raise CutoverBlocked("EXISTING_PINNED_ROLE_MUTEX_MISSING:" + other_label)
        stack.enter_context(controller.owned_interprocess_lock(other_prefix, timeout_seconds=8,
            timeout_message="Pinned role release mutex busy: " + other_label))
    candidate_policy_path = Path(role["new_cfg"]["EnvironmentVariables"]["V4_RESEARCH_RETENTION_POLICY"])
    candidate_policy = read_json(candidate_policy_path)
    registry_root = Path(candidate_policy["governance"]["registry_root"])
    for name in ("pool-writer.lock", "registry.lock"):
        fd = _existing_regular_lock(registry_root / name)
        stack.callback(os.close, fd)


def activate_main(plan: dict, controller, *, lock_adapter=acquire_switch_locks,
                  qfq_adapter=None, preflight_adapter=None) -> dict:
    role_row = plan["controller_plan"]["roles"][0]
    review_ref = plan["controller_plan"]["review_approval"]
    review = evidence(review_ref["path"], review_ref["sha256"])
    if review.get("verdict") != "PASS" or set(review.get("roles", {})) != {"main"}:
        raise CutoverBlocked("MATCHING_MAIN_CHAT_REVIEW_REQUIRED")
    approved = review["roles"]["main"]
    controller.CANDIDATES = Path(plan["approved_candidate_parent"])
    controller_plan = dict(plan["controller_plan"])
    controller_plan.pop("plan_sha256", None)
    result = {"status": "PREFLIGHT", "scope": "Main-only", "roles": {"main": {}}}
    with ExitStack() as locks:
        main_prefix = controller.LAUNCH_AGENTS / f".{controller.LABELS['main']}.release.lock"
        if not main_prefix.with_name(main_prefix.name + ".mutex").is_file():
            raise CutoverBlocked("EXISTING_MAIN_RELEASE_MUTEX_MISSING")
        locks.enter_context(controller.owned_interprocess_lock(main_prefix, timeout_seconds=8,
            timeout_message="V4 Main release mutex busy"))
        # load_role performs the launchctl and original/candidate manifest checks under the Main release mutex.
        role = controller.load_role(role_row, approved)
        lock_adapter(controller, role, plan, locks)
        source_readback = check_candidate_source_bindings(plan)
        admission = check_evidence(plan)
        qfq_admission = (qfq_adapter(plan, admission) if qfq_adapter
                         else run_candidate_qfq_admission(plan, admission))
        capacity = (preflight_adapter(plan, admission, controller) if preflight_adapter
                    else check_current_capacity(plan, admission, controller))
        result["source_binding_readback"] = source_readback
        result["candidate_child_qfq_admission"] = qfq_admission
        result["admission_capacity"] = capacity
        result["roles"]["main"]["before"] = role["before"]
        # Invoke the exact reviewed controller transaction for one Main role.
        try:
            controller.activate([role], controller_plan, result)
        except Exception as error:
            # The frozen controller records its bounded rollback outcome in
            # `result`, then re-raises the triggering exception. Preserve that
            # structured outcome instead of letting the CLI replace it with a
            # generic BLOCKED receipt. Unknown exceptions still propagate.
            if result.get("status") not in {"ROLLED_BACK", "ROLLBACK_INCOMPLETE"}:
                raise
            result["controller_call_exception"] = f"{type(error).__name__}: {error}"
        if result.get("status") != "DEPLOYED":
            # Preserve the reviewed controller's bounded rollback outcome and
            # error evidence verbatim; replacing it with a generic exception
            # would erase whether old or candidate bytes are currently loaded.
            result.setdefault("forward_failure", "MAIN_CONTROLLER_DID_NOT_CONFIRM_DEPLOYED")
            return result
        result["status"] = "ACTIVATED_MAIN_ONLY"
        result["main_plist_sha256"] = digest(role["path"].read_bytes())
        return result


def rollback_main(plan: dict, controller, *, lock_adapter=acquire_switch_locks) -> dict:
    row = plan["controller_plan"]["roles"][0]
    if row.get("role") != "main":
        raise CutoverBlocked("MAIN_ONLY_ROLLBACK_REQUIRED")
    label = controller.LABELS["main"]
    live = controller.LAUNCH_AGENTS / f"{label}.plist"
    old_raw = exact_file(Path(row["rollback_plist"]), row["current_plist_sha256"])
    new_raw = exact_file(Path(row["candidate_plist"]), row["candidate_plist_sha256"])
    old_cfg = plistlib.loads(old_raw)
    new_cfg = plistlib.loads(new_raw)
    old_cwd = old_cfg["WorkingDirectory"]
    new_cwd = new_cfg["WorkingDirectory"]
    old_release = Path(old_cwd).parent
    old_controls = plan.get("old_main_release_controls")
    if not isinstance(old_controls, dict) or set(old_controls) != {"manifest", "policy", "pins"}:
        raise CutoverBlocked("FROZEN_OLD_MAIN_CONTROL_SET_REQUIRED")
    for name, rel in (("manifest", "release-manifest.json"), ("policy", "control/policy.json"),
                      ("pins", "control/managed-pins.json")):
        item = old_controls[name]
        path = old_release / rel
        raw = exact_file(path, item["sha256"])
        info = path.lstat()
        if format(stat.S_IMODE(info.st_mode), "04o") != item["mode"]:
            raise CutoverBlocked("OLD_MAIN_CONTROL_MODE_DRIFT:" + name)
    current_plan = dict(plan)
    role_stub = {"label": label, "path": live, "old": old_raw, "new": new_raw,
                 "old_cfg": old_cfg, "new_cfg": new_cfg, "old_cwd": old_cwd,
                 "new_cwd": new_cwd}
    result = {"status": "ROLLBACK_PREFLIGHT", "scope": "Main-only", "roles": {"main": {}}}
    with ExitStack() as locks:
        prefix = controller.LAUNCH_AGENTS / f".{label}.release.lock"
        if not prefix.with_name(prefix.name + ".mutex").is_file():
            raise CutoverBlocked("EXISTING_MAIN_RELEASE_MUTEX_MISSING")
        locks.enter_context(controller.owned_interprocess_lock(prefix, timeout_seconds=8,
            timeout_message="V4 Main release mutex busy"))
        if live.resolve(strict=True) != live or live.read_bytes() != new_raw:
            raise CutoverBlocked("LIVE_CANDIDATE_PLIST_CAS_MISMATCH")
        if format(stat.S_IMODE(live.stat().st_mode), "04o") != row.get("current_plist_mode"):
            raise CutoverBlocked("LIVE_CANDIDATE_PLIST_MODE_DRIFT")
        state = controller.loaded(label)
        if (not state or state["cwd"] != new_cwd or state["path"] != str(live)
                or state["loaded_manifest_sha256"] != row["candidate_manifest_sha256"] or not state["pid"]):
            raise CutoverBlocked("LOADED_CANDIDATE_IDENTITY_REQUIRED")
        lock_adapter(controller, role_stub, current_plan, locks)
        state = controller.loaded(label)
        if (not state or state["cwd"] != new_cwd or state["path"] != str(live)
                or state["loaded_manifest_sha256"] != row["candidate_manifest_sha256"] or not state["pid"]):
            raise CutoverBlocked("LOADED_CANDIDATE_IDENTITY_CHANGED_UNDER_LOCK")
        controller.scheduler_idle(state["pid"], new_cfg)
        old_pins = old_release / "control" / "managed-pins.json"
        old_pins_readback = check_source_inventory(old_pins, old_controls["pins"]["sha256"])
        try:
            controller.unload(role_stub)
            controller.write_atomic(live, old_raw, new_raw)
            controller.run_ctl("bootstrap", controller.DOMAIN, str(live))
            restored = controller.verify_loaded("main", old_cwd, live, row["current_manifest_sha256"])
            if live.read_bytes() != old_raw:
                raise CutoverBlocked("RESTORED_OLD_MAIN_PLIST_READBACK_FAILED")
            result.update(status="RESTORED_MAIN_ONLY", restored=restored,
                          plist_sha256=digest(live.read_bytes()), old_source_binding_readback=old_pins_readback,
                          registry_write=False, current_pointer_write=False, reservation_release=False)
        except Exception as error:
            result.update(status="ROLLBACK_INCOMPLETE", error=f"{type(error).__name__}:{error}")
            actual = live.read_bytes()
            current = controller.loaded(label)
            if actual in (old_raw, new_raw) and current is None:
                try:
                    controller.run_ctl("bootstrap", controller.DOMAIN, str(live))
                    expected_cwd, expected_manifest = ((old_cwd, row["current_manifest_sha256"])
                        if actual == old_raw else (new_cwd, row["candidate_manifest_sha256"]))
                    result["recovered_loaded_identity"] = controller.verify_loaded(
                        "main", expected_cwd, live, expected_manifest)
                    result["recovery_action"] = "BOOTSTRAPPED_CURRENT_CAS_BYTES"
                    result["status"] = "ROLLBACK_FAILED_CURRENT_CONFIGURATION_RESTORED"
                except Exception as recovery_error:
                    result["recovery_error"] = f"{type(recovery_error).__name__}:{recovery_error}"
            elif current and current["cwd"] in {old_cwd, new_cwd} and actual in (old_raw, new_raw):
                result["recovered_loaded_identity"] = current
                result["status"] = "ROLLBACK_FAILED_CURRENT_CONFIGURATION_STILL_LOADED"
            return result
        return result


def run(args) -> dict:
    plan_path = Path(args.plan)
    plan_raw = exact_file(plan_path, args.plan_sha256)
    plan = json.loads(plan_raw)
    validate_plan(plan)
    approval_raw = exact_file(Path(args.authorization), args.authorization_sha256)
    authorization = json.loads(approval_raw)
    review_raw = exact_file(Path(args.chat_review_receipt), args.chat_review_sha256)
    chat_review = json.loads(review_raw)
    controller = load_controller()
    if args.action == "activate":
        check_evidence(plan)
        check_activation_authorization(plan, args.plan_sha256, authorization, chat_review, args.chat_review_sha256)
        return activate_main(plan, controller)
    check_rollback_authorization(plan, args.plan_sha256, authorization, chat_review, args.chat_review_sha256)
    return rollback_main(plan, controller)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("activate", "rollback"))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--chat-review-receipt", required=True)
    parser.add_argument("--chat-review-sha256", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = Path(args.receipt)
    if (not receipt.is_absolute() or receipt.parent.resolve(strict=True) != receipt.parent
            or os.path.lexists(receipt)):
        raise SystemExit("RECEIPT_PATH_MUST_BE_ABSOLUTE_NEW_FILE")
    try:
        result = run(args)
    except Exception as exc:
        result = {"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
    payload = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CutoverBlocked("RECEIPT_PATH_NOT_REGULAR")
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"ACTIVATED_MAIN_ONLY", "RESTORED_MAIN_ONLY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
