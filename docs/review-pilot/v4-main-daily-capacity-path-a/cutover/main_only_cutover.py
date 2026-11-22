"""Hash-bound Main-only forward switch using the reviewed V4 controller."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from contextvars import ContextVar
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
_LOCKED_CAPACITY_ROOT = ContextVar("v4_path_a_locked_capacity_root", default=None)
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
LOCK_LABELS = ("com.lexi.v4.scheduler", "com.lexi.stage-center.scheduler", "com.lexi.v4.api")
PYTHON_CACHE_PREFIX = "/dev/null/v4-main-r4-incremental-closure-20261122"
HISTORICAL_PREIMAGE_DIR = HERE / "preimages" / "historical_release_readiness"
HISTORICAL_PREIMAGE_SHAS = {
    "plist.preimage": "860eda6943afe89fa5d53db9ad111721ec64a2797e9d4c0a08880bee007c7c69",
    "manifest.preimage": "3df5eb5c4ef3794293518fe658b93d7369eeb762d559b4b2f62e3356bc52312d",
    "policy.preimage": "5cd95809b4287f67078004d21a5f073740c42caceed6cbdf2166b2415d965d61",
    "pins.preimage": "3f0dd502210cd73d179fe01d96df690cbc64206ae7e6dc10d23d132738ecc6d8",
    "stage-old.plist": "5fa7a95418c7527d2cb35bfbd4d35e6f6cf3ecb97a72141b3718bd55166e88bb",
    "stage-current.plist": "11f46b979350d5a577340e07f628417fdf03ef6a1a73565d964bb795e29becf5",
    "api-old.plist": "23ccf6771a4d7c5234ff3b5be4608308386e980f5417bbbc978cd8c863394400",
    "api-current.plist": "26ab9dc0cf0e8c0b8e494c153d015126d93cf8b119b520809d2a303cb02d1932",
}
HISTORICAL_PREIMAGE_INDEX_SHA256 = "cf7c14555d63bff955a8f9b63c50ec055d6b171d1fdb478509ac6462a8470fd0"
HISTORICAL_PIN_SHA256 = HISTORICAL_PREIMAGE_SHAS["pins.preimage"]
HISTORICAL_PIN_EXCEPTIONS = {
    "/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist":
        HISTORICAL_PREIMAGE_SHAS["stage-old.plist"],
    "/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist":
        HISTORICAL_PREIMAGE_SHAS["api-old.plist"],
}
HISTORICAL_MAIN_CONTROL_SHAS = {
    "plist": HISTORICAL_PREIMAGE_SHAS["plist.preimage"],
    "manifest": HISTORICAL_PREIMAGE_SHAS["manifest.preimage"],
    "policy": HISTORICAL_PREIMAGE_SHAS["policy.preimage"],
    "pins": HISTORICAL_PIN_SHA256,
}


class CutoverBlocked(RuntimeError):
    pass


class ResultExitStack(ExitStack):
    """Keep transaction facts when a context release raises after the body ends."""
    def __init__(self, result: dict):
        super().__init__()
        self.result = result

    def __exit__(self, exc_type, error, traceback):
        try:
            return super().__exit__(exc_type, error, traceback)
        except BaseException as release_error:
            self.result.setdefault("lock_release_errors", []).append(
                f"{type(release_error).__name__}:{release_error}")
            has_result = isinstance(error, BaseException) and getattr(error, "v4_cutover_result", None) is self.result
            is_interruption = isinstance(error, BaseException) and not isinstance(error, Exception)
            primary = error if has_result or is_interruption else release_error
            if not isinstance(primary, Exception):
                if getattr(primary, "v4_cutover_result", None) is not self.result:
                    interrupt_result(primary, self.result, "LOCK_RELEASE")
            else:
                primary.v4_cutover_result = self.result
            raise primary


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def interrupt_result(error: BaseException, result: dict, phase: str) -> None:
    """Carry the original transaction facts through the CLI persistence boundary."""
    result["interruption"] = {"type": type(error).__name__, "message": str(error), "phase": phase}
    error.v4_cutover_result = result


def final_main_state(controller, label: str, live: Path, old_raw: bytes, new_raw: bytes,
                     old_cwd: str, new_cwd: str, old_manifest: str, new_manifest: str,
                     interruptions: list | None = None) -> dict:
    """Perform one bounded, read-only observation of bytes, mode and loaded identity."""
    observed = {"plist_identity": "UNKNOWN", "loaded_identity": "UNKNOWN"}
    try:
        raw = read_regular_nofollow(live)
        mode = format(stat.S_IMODE(live.lstat().st_mode), "04o")
        observed.update(plist_sha256=digest(raw), plist_mode=mode)
        if mode == "0644":
            observed["plist_identity"] = "OLD" if raw == old_raw else "CANDIDATE" if raw == new_raw else "OTHER"
    except BaseException as error:
        observed["plist_read_error"] = f"{type(error).__name__}:{error}"
        if not isinstance(error, Exception) and interruptions is not None:
            interruptions.append(error)
    try:
        state = controller.loaded(label)
        observed["loaded"] = state
        if state is None:
            observed["loaded_identity"] = "ABSENT"
        elif (state.get("path") == str(live) and state.get("pid")
              and state.get("cwd") in {old_cwd, new_cwd}):
            if state["cwd"] == old_cwd and state.get("loaded_manifest_sha256") == old_manifest:
                observed["loaded_identity"] = "OLD"
            elif state["cwd"] == new_cwd and state.get("loaded_manifest_sha256") == new_manifest:
                observed["loaded_identity"] = "CANDIDATE"
    except BaseException as error:
        observed["loaded_read_error"] = f"{type(error).__name__}:{error}"
        if not isinstance(error, Exception) and interruptions is not None:
            interruptions.append(error)
    return observed


def environment_digest(environment: dict[str, str]) -> str:
    raw = "".join(f"{key}={environment[key]}\n" for key in sorted(environment)).encode("utf-8")
    return digest(raw)


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def expected_lock_protocol(launch_agents_root: Path | None = None) -> dict:
    root = launch_agents_root or (Path.home() / "Library" / "LaunchAgents")
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise CutoverBlocked("LOCK_PROTOCOL_ROOT_NOT_CANONICAL")
    owners = [str(root / f".{label}.release.lock") for label in LOCK_LABELS]
    return {
        "schema": "v4.main_cutover_owner_lock_protocol.v1",
        "launch_agents_root": str(root),
        "owner_record_paths": owners,
        "owner_record_operation": "CREATE_OWN_UNLINK_SAME_RECORD",
        "dead_owner_cleanup": "MAY_UNLINK_ONLY_AFTER_DECODED_PID_PROVEN_DEAD",
        "persistent_mutex_paths": [path + ".mutex" for path in owners],
        "persistent_mutex_files_must_preexist": True,
        "persistent_mutex_bytes_or_inode_change": False,
        "stage_api_service_reload": False,
    }


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
                  "candidate_classification_sha256", "release_id", "child_identity_receipt_path",
                  "child_identity_receipt_sha256"):
        if not isinstance(new.get(field), str) or not new[field]:
            raise CutoverBlocked("NEW_TASK_IDENTITY_INCOMPLETE:" + field)
    if (any(not is_sha256(new[field]) for field in ("task_key", "computation_identity_sha256",
            "expected_child_environment_sha256", "expected_child_python_sha256", "registry_sha256",
            "candidate_policy_sha256", "candidate_classification_sha256", "child_identity_receipt_sha256"))
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
    child_args = new.get("child_python_args")
    if not isinstance(child_args, list) or any(not isinstance(item, str) for item in child_args):
        raise CutoverBlocked("CAPTURED_A_EXECUTOR_ARG_PREFIX_REQUIRED")
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
    if capacity.get("schema") == "v4.daily_capacity_runtime_contract.v1":
        # Approval pins the measurement contract, not a stale free-space number.
        # Numeric capacity is re-read after every writer/role lock is held.
        if (capacity.get("measurement") != "LOCKED_AT_EXECUTION"
                or capacity.get("live_recheck_required") is not True
                or capacity.get("controller_sha256") != digest(read_regular_nofollow(Path(__file__).resolve()))
                or not is_sha256(capacity.get("policy_sha256"))
                or not is_sha256(capacity.get("helper_sha256"))):
            raise CutoverBlocked("LOCKED_CAPACITY_CONTRACT_INVALID")
    else:
        # Preserve the previously reviewed legacy contract unchanged.
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
        "lock_protocol": plan.get("lock_protocol"),
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
    validate_historical_exception_contract(plan.get("rollback_source_binding_exceptions"))
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
        "lock_protocol": plan.get("lock_protocol"),
        "historical_source_binding_exceptions_sha256": digest(json.dumps(
            plan.get("rollback_source_binding_exceptions"), ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()),
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
    if plan.get("lock_protocol") != expected_lock_protocol():
        raise CutoverBlocked("EXACT_TRANSIENT_OWNER_LOCK_AUTHORIZATION_CONTRACT_REQUIRED")
    role_plan = plan.get("controller_plan")
    if (not isinstance(role_plan, dict) or len(role_plan.get("roles", [])) != 1
            or role_plan["roles"][0].get("role") != "main"
            or role_plan.get("verification_command") is not None):
        raise CutoverBlocked("MAIN_ONLY_CONTROLLER_PLAN_REQUIRED")
    if role_plan["roles"][0].get("candidate_release_id") != plan["release_id"]:
        raise CutoverBlocked("CANDIDATE_RELEASE_ID_DRIFT")
    if role_plan["roles"][0].get("candidate_plist") != str(release_root / "launchd.plist"):
        raise CutoverBlocked("CANDIDATE_PLIST_OUTSIDE_RELEASE_ROOT")
    validate_historical_exception_contract(plan.get("rollback_source_binding_exceptions"))
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
    if digest(read_regular_nofollow(source)) != CONTROLLER_SHA256:
        raise CutoverBlocked("REVIEWED_CONTROLLER_SHA_DRIFT")
    repo = source.resolve(strict=True).parents[3]
    paths = {}
    for relative, expected in DEPENDENCY_SHAS.items():
        original = repo / relative
        frozen = HERE / "controller_dependencies" / relative
        if (digest(read_regular_nofollow(original)) != expected
                or digest(read_regular_nofollow(frozen)) != expected):
            raise CutoverBlocked("REVIEWED_CONTROLLER_DEPENDENCY_SHA_DRIFT:" + relative)
        paths[relative] = original
    if os.path.lexists(repo / "ops/__init__.py"):
        raise CutoverBlocked("OPS_NAMESPACE_BOUNDARY_DRIFT")
    return source, paths


def _verify_controller_import_context() -> None:
    flags = sys.flags
    if not (flags.ignore_environment == 1 and flags.no_site == 1 and flags.dont_write_bytecode == 1):
        raise CutoverBlocked("CONTROLLER_ISOLATED_STARTUP_FLAGS_REQUIRED")
    if sys.pycache_prefix != PYTHON_CACHE_PREFIX:
        raise CutoverBlocked("CONTROLLER_INERT_PYCACHE_PREFIX_REQUIRED")
    if [repr(finder) for finder in sys.meta_path] != [
            "<class '_frozen_importlib.BuiltinImporter'>",
            "<class '_frozen_importlib.FrozenImporter'>",
            "<class '_frozen_importlib_external.PathFinder'>"]:
        raise CutoverBlocked("CONTROLLER_IMPORT_FINDER_SET_INVALID")
    try:
        null_info = os.stat("/dev/null", follow_symlinks=False)
    except OSError:
        raise CutoverBlocked("CONTROLLER_INERT_PYCACHE_DEVICE_REQUIRED") from None
    if not stat.S_ISCHR(null_info.st_mode):
        raise CutoverBlocked("CONTROLLER_INERT_PYCACHE_DEVICE_REQUIRED")


def _module_origin(module, expected_path: Path, relative: str) -> bool:
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    module_file = getattr(module, "__file__", None)
    if origin != str(expected_path) or module_file != str(expected_path):
        return False
    if relative == "infrastructure/__init__.py":
        locations = getattr(spec, "submodule_search_locations", None)
        return locations is not None and list(locations) == [str(expected_path.parent)]
    return True


def load_controller():
    _verify_controller_import_context()
    source, dependencies = verify_controller_sources()
    if any(name.split(".")[0] in {"infrastructure", "ops"} for name in sys.modules):
        raise CutoverBlocked("RELEASE_CONTROLLER_DEPENDENCY_PRELOADED")
    import importlib.util
    spec = importlib.util.spec_from_file_location("r4_reviewed_switch_controller", source)
    if spec is None or spec.loader is None:
        raise CutoverBlocked("REVIEWED_CONTROLLER_SOURCE_SPEC_INVALID")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if (module.__file__ != str(source.resolve(strict=True))
            or getattr(module.__spec__, "origin", None) != str(source.resolve(strict=True))
            or digest(read_regular_nofollow(source)) != CONTROLLER_SHA256):
        raise CutoverBlocked("REVIEWED_CONTROLLER_IMPORTED_WRONG_SOURCE")
    for relative, path in dependencies.items():
        name = ("infrastructure" if relative == "infrastructure/__init__.py"
                else relative[:-3].replace("/", "."))
        imported = sys.modules.get(name)
        if imported is None or not _module_origin(imported, path.resolve(strict=True), relative):
            raise CutoverBlocked("RELEASE_CONTROLLER_IMPORTED_WRONG_DEPENDENCY:" + relative)
        if digest(read_regular_nofollow(path)) != DEPENDENCY_SHAS[relative]:
            raise CutoverBlocked("RELEASE_CONTROLLER_DEPENDENCY_CHANGED_DURING_IMPORT:" + relative)
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


def historical_preimage(name: str) -> bytes:
    if name not in HISTORICAL_PREIMAGE_SHAS:
        raise CutoverBlocked("UNKNOWN_HISTORICAL_PREIMAGE:" + str(name))
    return exact_file(HISTORICAL_PREIMAGE_DIR / name, HISTORICAL_PREIMAGE_SHAS[name])


def verify_historical_preimage_bundle() -> dict:
    index_raw = exact_file(HISTORICAL_PREIMAGE_DIR / "PREIMAGE_INDEX.json",
                           HISTORICAL_PREIMAGE_INDEX_SHA256)
    index = json.loads(index_raw)
    if (index.get("schema") != "v4.main_r4_incremental_historical_preimages.v1"
            or index.get("production_write") is not False):
        raise CutoverBlocked("HISTORICAL_PREIMAGE_INDEX_SCHEMA_INVALID")
    index_rows = index.get("files", [])
    indexed = {row.get("name"): row.get("sha256") for row in index_rows if isinstance(row, dict)}
    if len(index_rows) != len(HISTORICAL_PREIMAGE_SHAS) or indexed != HISTORICAL_PREIMAGE_SHAS:
        raise CutoverBlocked("HISTORICAL_PREIMAGE_INDEX_BINDING_DRIFT")
    for name in HISTORICAL_PREIMAGE_SHAS:
        historical_preimage(name)
    pins = json.loads(historical_preimage("pins.preimage"))
    bindings = pins.get("source_bindings")
    if not isinstance(bindings, list) or len(bindings) != 95:
        raise CutoverBlocked("HISTORICAL_PIN_PREIMAGE_NOT_95_ROWS")
    by_path = {row.get("path"): row.get("sha256") for row in bindings if isinstance(row, dict)}
    if len(by_path) != 95 or any(by_path.get(path) != sha_value
            for path, sha_value in HISTORICAL_PIN_EXCEPTIONS.items()):
        raise CutoverBlocked("HISTORICAL_EXCEPTION_SET_NOT_EXACT")
    for label, name in (("com.lexi.stage-center.scheduler", "stage-old.plist"),
                        ("com.lexi.v4.api", "api-old.plist"),
                        ("com.lexi.stage-center.scheduler", "stage-current.plist"),
                        ("com.lexi.v4.api", "api-current.plist")):
        cfg = plistlib.loads(historical_preimage(name))
        if cfg.get("Label") != label:
            raise CutoverBlocked("HISTORICAL_ROLE_LABEL_MISMATCH:" + label)
    return {"status": "PASS_HISTORICAL_ARCHIVE_ONLY", "pins_sha256": HISTORICAL_PIN_SHA256,
            "source_bindings": 95, "exception_paths": sorted(HISTORICAL_PIN_EXCEPTIONS),
            "r4_stage_api_current_snapshot_not_live": {
                "stage_sha256": HISTORICAL_PREIMAGE_SHAS["stage-current.plist"],
                "api_sha256": HISTORICAL_PREIMAGE_SHAS["api-current.plist"]}}


def validate_historical_exception_contract(contract) -> dict:
    if (not isinstance(contract, dict)
            or set(contract) != {"schema", "historical_pins_sha256", "exceptions", "preimage_receipt"}
            or contract.get("schema") != "v4.main_historical_rollback_binding_exceptions.v1"
            or not is_sha256(contract.get("historical_pins_sha256"))):
        raise CutoverBlocked("EXACT_HISTORICAL_ROLLBACK_EXCEPTION_CONTRACT_REQUIRED")
    exceptions = contract.get("exceptions")
    if not isinstance(exceptions, list) or len(exceptions) != 2:
        raise CutoverBlocked("EXACT_TWO_HISTORICAL_SOURCE_EXCEPTIONS_REQUIRED")
    normalized = {}
    for row in exceptions:
        if (not isinstance(row, dict) or set(row) != {"path", "historical_sha256", "current_sha256"}
                or not isinstance(row.get("path"), str)
                or not is_sha256(row.get("historical_sha256"))
                or not is_sha256(row.get("current_sha256"))
                or row["path"] in normalized):
            raise CutoverBlocked("HISTORICAL_ROLLBACK_EXCEPTION_ROW_INVALID")
        normalized[row["path"]] = row
    if set(normalized) != set(HISTORICAL_PIN_EXCEPTIONS):
        raise CutoverBlocked("HISTORICAL_ROLLBACK_EXCEPTION_SET_DRIFT")
    for path, historical_sha in HISTORICAL_PIN_EXCEPTIONS.items():
        if normalized[path]["historical_sha256"] != historical_sha:
            raise CutoverBlocked("HISTORICAL_ROLLBACK_EXCEPTION_SHA_DRIFT:" + path)
    preimage_ref = contract.get("preimage_receipt")
    if (not isinstance(preimage_ref, dict) or set(preimage_ref) != {"path", "sha256"}
            or not isinstance(preimage_ref.get("path"), str) or not is_sha256(preimage_ref.get("sha256"))):
        raise CutoverBlocked("CUTOVER_TIME_STAGE_API_PREIMAGE_RECEIPT_REQUIRED")
    preimage_path = Path(preimage_ref["path"])
    preimage_raw = exact_file(preimage_path, preimage_ref["sha256"])
    preimage = json.loads(preimage_raw)
    rows = preimage.get("current_preimages")
    if (preimage.get("scope") != "source readback only; not an authorization or change to live plist"
            or not isinstance(rows, dict)
            or set(rows) != {"main.plist", "stage.plist", "api.plist", "manifest.json", "policy.json", "pins.json"}):
        raise CutoverBlocked("CUTOVER_TIME_STAGE_API_PREIMAGE_RECEIPT_INVALID")
    original_paths = {}
    captured_paths = {}
    sampled_shas = {}
    for filename, expected_original in (
            ("main.plist", None),
            ("stage.plist", "/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist"),
            ("api.plist", "/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist"),
            ("manifest.json", None), ("policy.json", None), ("pins.json", None)):
        item = rows.get(filename)
        original_path = item.get("original_path") if isinstance(item, dict) else None
        if (not isinstance(item, dict) or set(item) != {"original_path", "captured_copy", "sha256",
                                                       "size", "original_mode", "copy_mode"}
                or not isinstance(original_path, str) or not Path(original_path).is_absolute()
                or (expected_original is not None and original_path != expected_original)
                or not is_sha256(item.get("sha256"))
                or item.get("original_mode") != "0644" or item.get("copy_mode") != "0400"):
            raise CutoverBlocked("CUTOVER_TIME_STAGE_API_PREIMAGE_IDENTITY_INVALID:" + filename)
        captured_copy = Path(item.get("captured_copy", ""))
        raw = exact_file(captured_copy, item["sha256"])
        if (len(raw) != item.get("size") or format(stat.S_IMODE(captured_copy.stat().st_mode), "04o") != "0400"):
            raise CutoverBlocked("CUTOVER_TIME_STAGE_API_PREIMAGE_COPY_DRIFT:" + filename)
        original_paths[filename] = original_path
        captured_paths[filename] = str(captured_copy)
        sampled_shas[filename] = item["sha256"]
    for filename, original_path in (("stage.plist", "/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist"),
                                    ("api.plist", "/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist")):
        if normalized[original_path]["current_sha256"] != sampled_shas[filename]:
            raise CutoverBlocked("CUTOVER_TIME_EXCEPTION_DIFFERS_FROM_SAMPLED_PREIMAGE:" + filename)
    normalized["__sampled_preimage_receipt__"] = {"path": str(preimage_path),
                                                   "sha256": preimage_ref["sha256"],
                                                   "original_paths": original_paths,
                                                   "captured_paths": captured_paths,
                                                   "sha256_by_name": sampled_shas}
    return normalized


def check_source_inventory(pins_path: Path, expected_sha: str,
                           exception_contract: dict) -> dict:
    archive = verify_historical_preimage_bundle()
    validated_exceptions = validate_historical_exception_contract(exception_contract)
    sampled_preimage_receipt = validated_exceptions.pop("__sampled_preimage_receipt__")
    exceptions = {path: validated_exceptions[path] for path in HISTORICAL_PIN_EXCEPTIONS}
    if expected_sha != exception_contract["historical_pins_sha256"]:
        raise CutoverBlocked("ROLLBACK_HISTORICAL_PINS_PLAN_BINDING_DRIFT")
    pins_raw = exact_file(pins_path, expected_sha)
    pins = json.loads(pins_raw)
    bindings = pins.get("source_bindings")
    if not isinstance(bindings, list) or len(bindings) != 95:
        raise CutoverBlocked("EXPECTED_95_SOURCE_BINDINGS")
    strict_count = 0
    exception_count = 0
    readbacks = []
    seen = set()
    for row in bindings:
        path = Path(row["path"])
        raw = read_regular_nofollow(path)
        actual = digest(raw)
        path_text = str(path)
        if path_text in seen:
            raise CutoverBlocked("SOURCE_BINDING_PATH_DUPLICATE")
        seen.add(path_text)
        if path_text in exceptions:
            exception = exceptions[path_text]
            if row["sha256"] != exception["historical_sha256"] or actual != exception["current_sha256"]:
                raise CutoverBlocked("HISTORICAL_SOURCE_EXCEPTION_CURRENT_SHA_DRIFT:" + path_text)
            expected_label = ("com.lexi.stage-center.scheduler" if path_text.endswith("stage-center.scheduler.plist")
                              else "com.lexi.v4.api")
            if plistlib.loads(raw).get("Label") != expected_label:
                raise CutoverBlocked("HISTORICAL_SOURCE_EXCEPTION_LABEL_DRIFT:" + path_text)
            exception_count += 1
            readbacks.append({"path": path_text, "historical_sha256": row["sha256"],
                              "current_sha256": actual, "classification": "EXACT_REVIEWED_CURRENT_EXCEPTION"})
        else:
            if actual != row["sha256"]:
                raise CutoverBlocked("SOURCE_BINDING_DRIFT:" + str(path))
            strict_count += 1
    if strict_count != 93 or exception_count != 2 or len(seen) != 95:
        raise CutoverBlocked("HISTORICAL_93_PLUS_2_BINDING_COUNT_DRIFT")
    return {"verified_historical_rows": 95, "historical_strict_matches": 93,
            "exact_current_exceptions": 2, "historical_pins_sha256": digest(pins_raw),
            "classification": "93_HISTORICAL_STRICT_PLUS_2_EXACT_CURRENT_EXCEPTIONS",
            "archive_snapshot": archive, "sampled_preimage_receipt": sampled_preimage_receipt,
            "exception_readbacks": readbacks}


def _candidate_qfq_gate_context(release: Path, candidate_plist_path: Path,
                                identity_path: Path, identity_sha: str,
                                child_args: list[str] | None) -> dict:
    """Recreate the read-only runtime child's interpreter/path environment."""
    release = release.resolve(strict=True)
    app = release / "app"
    runtime = release / "runtime"
    candidate_plist_path = candidate_plist_path.resolve(strict=True)
    if candidate_plist_path != release / "launchd.plist":
        raise CutoverBlocked("CANDIDATE_LAUNCHD_PATH_NOT_RELEASE_BOUND")
    candidate_raw = candidate_plist_path.read_bytes()
    candidate = plistlib.loads(candidate_raw)
    if candidate.get("WorkingDirectory") != str(app):
        raise CutoverBlocked("CANDIDATE_LAUNCHD_CWD_DRIFT")
    candidate_environment = dict(candidate.get("EnvironmentVariables", {}))
    for key, expected in (("V4_APP_ROOT", str(app)), ("V4_RUNTIME_ROOT", str(runtime)),
                          ("V4_RELEASE_ID", release.name)):
        if candidate_environment.get(key) != expected:
            raise CutoverBlocked("CANDIDATE_LAUNCHD_ROOT_BINDING_DRIFT:" + key)
    if not identity_path.is_absolute() or identity_path.resolve(strict=True) != identity_path:
        raise CutoverBlocked("CHILD_IDENTITY_RECEIPT_PATH_INVALID")
    identity_raw = identity_path.read_bytes()
    if digest(identity_raw) != identity_sha:
        raise CutoverBlocked("CHILD_IDENTITY_RECEIPT_SHA_DRIFT")
    receipt = json.loads(identity_raw)
    identity = receipt.get("qfq_child_identity")
    if (receipt.get("schema") != "v4.r4_daemon_a_qfq_identity_probe.v1"
            or receipt.get("status") != "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY"
            or not isinstance(identity, dict)
            or receipt.get("release_id") != release.name
            or receipt.get("release_root") != str(release)
            or receipt.get("app_root") != str(app)
            or receipt.get("runtime_root") != str(runtime)):
        raise CutoverBlocked("CHILD_IDENTITY_RECEIPT_RELEASE_BINDING_DRIFT")
    expected_identity_path = release.parent / "verification" / "CHILD_IDENTITY_RECEIPT.json"
    if identity_path != expected_identity_path:
        raise CutoverBlocked("CHILD_IDENTITY_RECEIPT_NOT_FROZEN_CANDIDATE_ARTIFACT")

    python = runtime / "venvs" / "v4-mac" / "bin" / "python"
    site = runtime / "venvs" / "v4-mac" / "lib" / "python3.14" / "site-packages"
    if not python.is_file() or not site.is_dir():
        raise CutoverBlocked("CANDIDATE_MAC_PYTHON_OR_SITE_MISSING")
    executor_command = (((receipt.get("a_executor_fixture") or {}).get("captured_executor_run") or {}).get("command"))
    if (not isinstance(executor_command, list) or not executor_command
            or str(executor_command[0]) != str(python)):
        raise CutoverBlocked("CAPTURED_A_EXECUTOR_INTERPRETER_DRIFT")
    try:
        module_index = executor_command.index("-m")
    except ValueError:
        raise CutoverBlocked("CAPTURED_A_EXECUTOR_MODULE_FORM_MISSING") from None
    if (module_index < 1 or module_index + 1 >= len(executor_command)
            or executor_command[module_index + 1] != "ops.macos_research_panel_daily"):
        raise CutoverBlocked("CAPTURED_A_EXECUTOR_MODULE_DRIFT")
    captured_child_args = executor_command[1:module_index]
    if child_args is not None and child_args != captured_child_args:
        raise CutoverBlocked("REVIEWED_A_EXECUTOR_ARG_PREFIX_DRIFT")
    child_args = captured_child_args
    inherited_pythonpath = candidate_environment.get("PYTHONPATH", "")
    pythonpath_entries = [str(app), str(site), *(item for item in inherited_pythonpath.split(os.pathsep) if item)]
    captured_sys_path = identity.get("effective_sys_path")
    stdlib = Path(identity.get("stdlib_root", "")).resolve(strict=True)
    expected_stdlib_tail = [str(stdlib.parent / "python314.zip"), str(stdlib), str(stdlib / "lib-dynload")]
    if (not isinstance(captured_sys_path, list) or len(captured_sys_path) < 4
            or captured_sys_path[0] != str(app)
            or captured_sys_path[1:-3] != pythonpath_entries
            or captured_sys_path[-3:] != expected_stdlib_tail):
        raise CutoverBlocked("DAEMON_QFQ_SYS_PATH_NOT_RECONSTRUCTIBLE_FROM_CANDIDATE")

    # Preserve the captured dispatch ledger string after its fixture directory
    # has been removed. This gate never opens or recreates that path.
    fixture_root = (release.parent / "verification").resolve(strict=True)
    fixture_ledger = Path(receipt.get("fixture_ledger_root", ""))
    canonical_fixture_ledger = fixture_ledger.resolve(strict=False)
    if (not fixture_ledger.is_absolute() or canonical_fixture_ledger != fixture_ledger
            or canonical_fixture_ledger.name != "dispatch-ledger"
            or canonical_fixture_ledger.parent.parent != fixture_root
            or not canonical_fixture_ledger.parent.name.startswith("daemon-child-identity-")):
        raise CutoverBlocked("IDENTITY_FIXTURE_LEDGER_ROOT_INVALID")

    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ.get("HOME", "/Users/lexi"),
        "LANG": "en_US.UTF-8",
        "TZ": "Asia/Shanghai",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if os.environ.get("__CF_USER_TEXT_ENCODING") is not None:
        environment["__CF_USER_TEXT_ENCODING"] = os.environ["__CF_USER_TEXT_ENCODING"]
    environment.update(candidate_environment)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    overlays = {
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": identity.get("pycache_prefix"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
        "V3_SHARED_HK_TDX_ROOT": candidate_environment.get("V4_RESEARCH_PANEL_HK_TDX_ROOT", ""),
        "V4_DISPATCH_LEDGER_ROOT": str(canonical_fixture_ledger),
    }
    for name, value in overlays.items():
        current = environment.get(name)
        if current is not None and current != value and name != "V4_DISPATCH_LEDGER_ROOT":
            raise CutoverBlocked("CANDIDATE_RUNTIME_ENVIRONMENT_OVERLAY_DRIFT:" + name)
        if value is None:
            raise CutoverBlocked("CHILD_IDENTITY_RUNTIME_ENVIRONMENT_FIELD_MISSING:" + name)
        environment[name] = value
    if any(not isinstance(item, str) for item in child_args):
        raise CutoverBlocked("CAPTURED_A_EXECUTOR_ARG_PREFIX_INVALID")

    qfq_env_names = (
        "V4_A_QFQ_COMPUTE_BACKEND", "V4_A_QFQ_SOURCE_REPAIR_DATE",
        "V4_A_QFQ_SOURCE_REPAIR_INPUT", "V4_A_QFQ_SOURCE_REPAIR_INPUT_SHA256",
        "V4_QFQ_CONVENTION_ACCEPTANCE_PATH", "V4_QFQ_CONVENTION_ACCEPTANCE_SHA256",
        "RESEARCH_PANEL_QFQ_REFRESH_FACTORS",
    )
    if {key: environment.get(key) for key in qfq_env_names} != identity.get("qfq_environment_values"):
        raise CutoverBlocked("CANDIDATE_CHILD_QFQ_ENVIRONMENT_DRIFT")
    return {"release": release, "app": app, "runtime": runtime, "python": python,
            "site": site, "environment": environment, "identity_receipt": receipt,
            "identity": identity, "child_args": child_args,
            "candidate_plist_sha256": digest(candidate_raw),
            "child_environment_sha256": environment_digest(environment)}


def _candidate_gate_bootstrap() -> str:
    """SHA-check external gate bytes and match `python -m` cwd path semantics."""
    return (
        "import hashlib,os,sys\n"
        "args=sys.argv[1:]\n"
        "path,expected,*rest=args\n"
        "raw=open(path,'rb').read()\n"
        "if hashlib.sha256(raw).hexdigest()!=expected: raise SystemExit('CANDIDATE_GATE_SOURCE_SHA_DRIFT')\n"
        "if not sys.path or sys.path[0] not in ('',os.getcwd()): raise SystemExit('CANDIDATE_CHILD_SYS_PATH_ZERO_DRIFT')\n"
        "sys.path[0]=os.getcwd()\n"
        "sys.argv=[path,*rest]\n"
        "scope={'__name__':'__main__','__file__':path,'__package__':None}\n"
        "exec(compile(raw,path,'exec'),scope)\n"
    )


def run_candidate_qfq_identity_parity(release: Path, candidate_plist_path: Path,
                                      identity_path: Path, identity_sha: str,
                                      target_date: str, task_key: str,
                                      registry_sha: str, environment_sha: str,
                                      *, child_args: list[str] | None = None) -> dict:
    """Compare candidate gate key and sys.path to the captured daemon A child."""
    context = _candidate_qfq_gate_context(release, candidate_plist_path,
                                           identity_path, identity_sha, child_args)
    gate_source = HERE / "candidate_qfq_gate.py"
    gate_sha = digest(gate_source.read_bytes())
    command = [str(context["python"]), *child_args, "-c", _candidate_gate_bootstrap(),
               str(gate_source), gate_sha, "--identity-parity", str(context["release"]),
               str(identity_path), identity_sha, target_date, task_key, registry_sha, environment_sha]
    result = subprocess.run(command, cwd=context["app"], env=context["environment"],
                            capture_output=True, text=True, timeout=180)
    try:
        observed = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        observed = {"status": "BLOCKED", "reason": (result.stderr or result.stdout)[-2000:]}
    if (result.returncode != 0
            or observed.get("status") != "PASS_CANDIDATE_GATE_QFQ_CHILD_IDENTITY_PARITY"
            or observed.get("candidate_operation_key") != task_key
            or observed.get("daemon_a_qfq_operation_key") != task_key
            or observed.get("operation_key_equal") is not True
            or observed.get("effective_sys_path_equal") is not True):
        raise CutoverBlocked("CANDIDATE_QFQ_IDENTITY_PARITY_BLOCKED:" + str(observed.get("reason", observed.get("status"))))
    return {"command": command, "return_code": result.returncode,
            "parity": observed, "stderr": result.stderr,
            "candidate_python_sha256": digest(context["python"].read_bytes()),
            "candidate_plist_sha256": context["candidate_plist_sha256"],
            "candidate_gate_source_sha256": gate_sha,
            "child_identity_receipt_sha256": identity_sha,
            "captured_qfq_child_environment_sha256": environment_sha,
            "candidate_gate_environment_sha256": context["child_environment_sha256"],
            "full_environment_sha_equal": environment_sha == context["child_environment_sha256"],
            "captured_a_executor_environment_sha256": context["identity_receipt"]["a_executor_fixture"]["captured_executor_run"]["environment_sha256"],
            "identity_fixture_ledger_exists": Path(context["identity_receipt"]["fixture_ledger_root"]).exists()}


def run_candidate_qfq_admission(plan: dict, evidence_rows: dict) -> dict:
    """Run the candidate QFQ classifier after real child identity parity."""
    release = Path(plan["release_root"]).resolve(strict=True)
    proof_ref = plan["admission_evidence"]["new_date_reviewed_classification"]
    proof_path = Path(proof_ref["path"])
    new = evidence_rows["new_date_reviewed_classification"]
    role = plan["controller_plan"]["roles"][0]
    identity_path = Path(new["child_identity_receipt_path"])
    child_args = new.get("child_python_args")
    context = _candidate_qfq_gate_context(release, Path(role["candidate_plist"]),
                                           identity_path, new["child_identity_receipt_sha256"],
                                           child_args)
    identity = context["identity"]
    if (identity.get("executable_sha256") != new.get("expected_child_python_sha256")
            or identity.get("environment_sha256") != new.get("expected_child_environment_sha256")
            or identity.get("qfq_operation_keys", {}).get(str(plan["target_date"])) != new.get("task_key")
            or identity.get("registry_sha256") != new.get("registry_sha256")):
        raise CutoverBlocked("DAEMON_QFQ_IDENTITY_RECEIPT_REVIEW_BINDING_DRIFT")
    python = context["python"]
    app = context["app"]
    gate_source = HERE / "candidate_qfq_gate.py"
    gate_sha = digest(gate_source.read_bytes())
    command = [str(python), *child_args, "-c", _candidate_gate_bootstrap(),
               str(gate_source), gate_sha, str(release), str(proof_path), proof_ref["sha256"],
               str(identity_path), new["child_identity_receipt_sha256"],
               str(plan["target_date"]), new["task_key"], new["registry_sha256"],
               new["expected_child_environment_sha256"]]
    result = subprocess.run(command, cwd=app, env=context["environment"],
                            capture_output=True, text=True, timeout=180)
    try:
        observed = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        observed = {"status": "BLOCKED", "reason": (result.stderr or result.stdout)[-1000:]}
    if (result.returncode != 0 or observed.get("status") != "PASS_READONLY_REVIEWED_DISTINCT_DATE_SCOPE"
            or observed.get("task_key") != new["task_key"] or observed.get("registry_sha256") != new["registry_sha256"]
            or observed.get("target_date") != plan["target_date"]
            or observed.get("child_operation_key_parity", {}).get("operation_key_equal") is not True
            or observed.get("child_operation_key_parity", {}).get("effective_sys_path_equal") is not True):
        raise CutoverBlocked("CANDIDATE_CHILD_QFQ_ADMISSION_BLOCKED:" + str(observed.get("reason", observed.get("status"))))
    if (observed.get("old_task_key") != evidence_rows["old_task_unique_attribution"]["old_task_key"]
            or observed.get("old_row_sha256") != evidence_rows["old_task_unique_attribution"]["old_row_sha256"]
            or observed.get("old_category_remaining_bytes") != OLD_CATEGORY_REMAINING
            or observed.get("old_physical_peak_remaining_bytes") != OLD_PHYSICAL_REMAINING):
        raise CutoverBlocked("CANDIDATE_CHILD_OLD_RESERVATION_BINDING_DRIFT")
    return {"command": command, "return_code": result.returncode, "stdout": observed,
            "stderr": result.stderr, "python_sha256": digest(python.read_bytes()),
            "child_identity_receipt_sha256": new["child_identity_receipt_sha256"],
            "gate_source_sha256": gate_sha,
            "candidate_gate_environment_sha256": context["child_environment_sha256"],
            "captured_qfq_child_environment_sha256": identity["environment_sha256"],
            "full_environment_sha_equal": context["child_environment_sha256"] == identity["environment_sha256"],
            "identity_fixture_ledger_exists": Path(context["identity_receipt"]["fixture_ledger_root"]).exists()}


def locked_capacity_probe(plan: dict, environment: dict, policy_sha: str, registry_sha: str, *, tdx_root: str, helper_sha: str) -> dict:
    """Execute only the approved candidate helper; no registry lock reacquisition.

    activate_main invokes this after acquire_switch_locks. The child uses the
    approved interpreter/source and performs Registry.read, not transaction.
    """
    policy = json.loads(exact_file(Path(environment["V4_RESEARCH_RETENTION_POLICY"]), policy_sha))
    if _LOCKED_CAPACITY_ROOT.get() != policy["governance"]["registry_root"]:
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_REQUIRES_ALL_SWITCH_LOCKS")
    release = Path(plan["release_root"])
    app = release / "app"
    python = release / "runtime/venvs/v4-mac/bin/python"
    site = release / "runtime/venvs/v4-mac/lib/python3.14/site-packages"
    helper = app / "ops/research_daily_capacity.py"
    if any(not path.exists() for path in (python, site, helper)):
        raise CutoverBlocked("APPROVED_CAPACITY_HELPER_MISSING")
    if not is_sha256(helper_sha):
        raise CutoverBlocked("APPROVED_CAPACITY_HELPER_SHA_REQUIRED")
    exact_file(helper, helper_sha)
    code = ("import sys,runpy;sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)];"
            "runpy.run_module('ops.research_daily_capacity',run_name='__main__')")
    command = [str(python), "-B", "-S", "-c", code, str(app), str(site),
               "--policy", environment["V4_RESEARCH_RETENTION_POLICY"],
               "--policy-sha256", policy_sha,
               "--tdx-root", tdx_root,
               "--caller-holds-locks"]
    child_environment = dict(environment)
    child_environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=PYTHON_CACHE_PREFIX)
    result = subprocess.run(command, cwd=app, env=child_environment, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_FAILED:" + result.stderr[-1024:])
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_RESPONSE_INVALID") from None
    if (payload.get("schema") != "v4.daily_capacity_locked_probe.v1"
            or payload.get("registry_sha256") != registry_sha
            or payload.get("reservation_write") is not False
            or payload.get("reservation_release") is not False):
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_BINDING_DRIFT")
    # Probe policy uses semantic SHA as the immutable runtime plan does. The
    # file's exact byte SHA was separately checked before child execution.
    policy = json.loads(exact_file(Path(environment["V4_RESEARCH_RETENTION_POLICY"]), policy_sha))
    semantic_sha = digest(json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    if payload.get("policy_sha256") != semantic_sha:
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_POLICY_DRIFT")
    if payload.get('evidence_scope') != 'PRODUCTION_REVIEWED':
        raise CutoverBlocked('LOCKED_CAPACITY_PRODUCTION_REVIEW_REQUIRED')
    if payload.get("eligibility") != "PASS":
        raise CutoverBlocked("LOCKED_CAPACITY_PROBE_CANNOT_CONFIRM:" + str(payload.get("unproven_writer_phases")))
    peaks = payload.get("phase_peak_bytes")
    if (not isinstance(peaks, dict) or set(peaks) != {"input", "qfq", "daily_product", "top200"}
            or any(type(value) is not int or value <= 0 for value in peaks.values())
            or payload.get("predicted_peak_bytes") != sum(peaks.values())):
        raise CutoverBlocked("LOCKED_CAPACITY_PHASE_BOUNDS_INVALID")
    return payload


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
    reviewed = admission["actual_capacity_preflight"]
    dynamic = reviewed.get("schema") == "v4.daily_capacity_runtime_contract.v1"
    if dynamic:
        if reviewed.get("policy_sha256") != policy_sha:
            raise CutoverBlocked("LOCKED_CAPACITY_CONTRACT_POLICY_DRIFT")
        actual = locked_capacity_probe(plan, new_env, policy_sha, registry_sha,
            tdx_root=new_proof["qfq_kwargs"]["tdx_root"], helper_sha=reviewed.get("helper_sha256"))
        target_peak = actual["predicted_peak_bytes"]
        category_used = actual["category_used_bytes"]
    else:
        actual = None
        target_peak = new_proof.get("predicted_peak_bytes")
        category_used = reviewed.get("category_used_bytes")
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
    if not dynamic and reviewed.get("category_other_remaining_bytes") != category_other:
        raise CutoverBlocked("CAPACITY_CATEGORY_LEDGER_MISMATCH")
    return {"measurement": "LOCKED_AT_EXECUTION" if dynamic else "LEGACY_FRESH_EVIDENCE",
            "locked_probe": actual,
            "registry_sha256": registry_sha, "old_category_remaining_bytes": old_category_in_other,
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
    token = _LOCKED_CAPACITY_ROOT.set(str(registry_root))
    stack.callback(_LOCKED_CAPACITY_ROOT.reset, token)


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
    with ResultExitStack(result) as locks:
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
        except BaseException as error:
            # The frozen controller records its bounded rollback outcome in
            # `result`, then re-raises the triggering exception. Preserve that
            # structured outcome instead of letting the CLI replace it with a
            # generic BLOCKED receipt. Unknown exceptions still propagate.
            if not isinstance(error, Exception):
                if all(name in role for name in ("old", "new", "old_cwd", "new_cwd")):
                    result["final_state"] = final_main_state(
                        controller, role["label"], role["path"], role["old"], role["new"],
                        role["old_cwd"], role["new_cwd"],
                        role["old_cfg"].get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256"),
                        role["new_cfg"].get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256"))
                if result.get("status") not in {"ROLLED_BACK", "ROLLBACK_INCOMPLETE", "DEPLOYED"}:
                    result["status"] = "INTERRUPTED"
                interrupt_result(error, result, "FORWARD_CONTROLLER")
                raise
            if result.get("status") not in {"ROLLED_BACK", "ROLLBACK_INCOMPLETE"}:
                raise
            result["controller_call_exception"] = f"{type(error).__name__}: {error}"
        if result.get("status") != "DEPLOYED":
            # Preserve the reviewed controller's bounded rollback outcome and
            # error evidence verbatim; replacing it with a generic exception
            # would erase whether old or candidate bytes are currently loaded.
            result.setdefault("forward_failure", "MAIN_CONTROLLER_DID_NOT_CONFIRM_DEPLOYED")
            return result
        result["controller_status"] = result["status"]
        result["phase"] = "FORWARD_FINAL_PLIST_READBACK"
        result["final_plist_readback"] = {"status": "PENDING"}
        try:
            result["main_plist_sha256"] = digest(role["path"].read_bytes())
        except BaseException as error:
            result["status"] = "FORWARD_FINAL_PLIST_READBACK_INCOMPLETE"
            result["final_plist_readback"] = {
                "status": "INCOMPLETE",
                "error": f"{type(error).__name__}:{error}",
            }
            error.v4_cutover_result = result
            if not isinstance(error, Exception):
                interrupt_result(error, result, result["phase"])
            raise
        result["final_plist_readback"] = {
            "status": "VERIFIED",
            "sha256": result["main_plist_sha256"],
        }
        result["status"] = "ACTIVATED_MAIN_ONLY"
        return result


def rollback_main(plan: dict, controller, *, lock_adapter=acquire_switch_locks) -> dict:
    row = plan["controller_plan"]["roles"][0]
    if row.get("role") != "main":
        raise CutoverBlocked("MAIN_ONLY_ROLLBACK_REQUIRED")
    label = controller.LABELS["main"]
    live = controller.LAUNCH_AGENTS / f"{label}.plist"
    old_raw = exact_file(Path(row["rollback_plist"]), row["current_plist_sha256"])
    new_raw = exact_file(Path(row["candidate_plist"]), row["candidate_plist_sha256"])
    archive_reference = verify_historical_preimage_bundle()
    if row.get("current_plist_mode") != "0644":
        raise CutoverBlocked("ROLLBACK_OLD_MAIN_PLIST_MODE_BINDING_REQUIRED")
    exception_contract = plan.get("rollback_source_binding_exceptions")
    validated_exception_contract = validate_historical_exception_contract(exception_contract)
    old_cfg = plistlib.loads(old_raw)
    new_cfg = plistlib.loads(new_raw)
    old_cwd = old_cfg["WorkingDirectory"]
    new_cwd = new_cfg["WorkingDirectory"]
    old_env = old_cfg.get("EnvironmentVariables", {})
    if (old_cfg.get("Label") != label or not Path(old_cwd).is_absolute()
            or Path(old_cwd).resolve(strict=True) != Path(old_cwd)
            or old_env.get("V4_RELEASE_MANIFEST_SHA256") != row.get("current_manifest_sha256")
            or not is_sha256(row.get("current_manifest_sha256"))):
        raise CutoverBlocked("PLAN_BOUND_OLD_MAIN_PREIMAGE_IDENTITY_REQUIRED")
    old_release = Path(old_cwd).parent
    old_controls = plan.get("old_main_release_controls")
    if not isinstance(old_controls, dict) or set(old_controls) != {"manifest", "policy", "pins"}:
        raise CutoverBlocked("FROZEN_OLD_MAIN_CONTROL_SET_REQUIRED")
    for name, rel in (("manifest", "release-manifest.json"), ("policy", "control/policy.json"),
                      ("pins", "control/managed-pins.json")):
        item = old_controls[name]
        if (not isinstance(item, dict) or set(item) != {"sha256", "mode"}
                or not is_sha256(item.get("sha256")) or item.get("mode") != "0644"):
            raise CutoverBlocked("EXACT_OLD_MAIN_CONTROL_BINDING_REQUIRED:" + name)
        path = old_release / rel
        raw = exact_file(path, item["sha256"])
        info = path.lstat()
        if format(stat.S_IMODE(info.st_mode), "04o") != item["mode"]:
            raise CutoverBlocked("OLD_MAIN_CONTROL_MODE_DRIFT:" + name)
    if (old_env.get("V4_RELEASE_MANIFEST_PATH") != str(old_release / "release-manifest.json")
            or old_env.get("V4_RELEASE_MANIFEST_SHA256") != old_controls["manifest"]["sha256"]
            or old_env.get("V4_RESEARCH_RETENTION_POLICY") != str(old_release / "control" / "policy.json")
            or old_env.get("V4_RESEARCH_RETENTION_POLICY_SHA256") != old_controls["policy"]["sha256"]
            or exception_contract.get("historical_pins_sha256") != old_controls["pins"]["sha256"]):
        raise CutoverBlocked("OLD_MAIN_CONTROL_PATH_OR_SHA_BINDING_DRIFT")
    sampled = validated_exception_contract["__sampled_preimage_receipt__"]
    sampled_expected = {"main.plist": row["current_plist_sha256"],
                        "manifest.json": old_controls["manifest"]["sha256"],
                        "policy.json": old_controls["policy"]["sha256"],
                        "pins.json": old_controls["pins"]["sha256"]}
    sampled_paths = {"main.plist": str(live),
                     "manifest.json": str(old_release / "release-manifest.json"),
                     "policy.json": str(old_release / "control" / "policy.json"),
                     "pins.json": str(old_release / "control" / "managed-pins.json")}
    if any(sampled["sha256_by_name"].get(name) != expected_sha
           or sampled["original_paths"].get(name) != sampled_paths[name]
           for name, expected_sha in sampled_expected.items()):
        raise CutoverBlocked("SAMPLED_OLD_MAIN_PREIMAGE_DOES_NOT_MATCH_ROLLBACK_PLAN")
    if sampled["captured_paths"].get("main.plist") != row["rollback_plist"]:
        raise CutoverBlocked("SAMPLED_OLD_MAIN_PLIST_COPY_PATH_DRIFT")
    current_plan = dict(plan)
    role_stub = {"label": label, "path": live, "old": old_raw, "new": new_raw,
                 "old_cfg": old_cfg, "new_cfg": new_cfg, "old_cwd": old_cwd,
                 "new_cwd": new_cwd}
    result = {"status": "ROLLBACK_PREFLIGHT", "scope": "Main-only", "roles": {"main": {}}}
    with ResultExitStack(result) as locks:
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
        old_pins_readback = check_source_inventory(old_pins, old_controls["pins"]["sha256"],
                                                   exception_contract)
        result["old_source_binding_readback"] = old_pins_readback
        result["historical_preimage_archive_reference"] = archive_reference
        try:
            result["phase"] = "UNLOADING_MAIN"
            controller.unload(role_stub)
            result["phase"] = "RESTORING_MAIN_PLIST"
            controller.write_atomic(live, old_raw, new_raw)
            result["phase"] = "BOOTSTRAPPING_MAIN"
            controller.run_ctl("bootstrap", controller.DOMAIN, str(live))
            result["phase"] = "VERIFYING_MAIN"
            restored = controller.verify_loaded("main", old_cwd, live, row["current_manifest_sha256"])
            if live.read_bytes() != old_raw:
                raise CutoverBlocked("RESTORED_OLD_MAIN_PLIST_READBACK_FAILED")
            result.update(status="RESTORED_MAIN_ONLY", restored=restored,
                          plist_sha256=digest(live.read_bytes()),
                          historical_source_binding_summary={
                              "historical_rows": old_pins_readback["verified_historical_rows"],
                              "historical_strict_matches": old_pins_readback["historical_strict_matches"],
                              "exact_current_exceptions": old_pins_readback["exact_current_exceptions"],
                              "classification": old_pins_readback["classification"]},
                          stage_reload=False, api_reload=False, registry_write=False,
                          current_pointer_write=False, reservation_release=False)
        except BaseException as error:
            interrupted = error if not isinstance(error, Exception) else None
            failure_phase = result["phase"]
            interruption_phase = failure_phase if interrupted is not None else None
            readback_interruptions = []
            result.update(status="ROLLBACK_INCOMPLETE", error=f"{type(error).__name__}:{error}",
                          failure_phase=failure_phase)
            observed = final_main_state(controller, label, live, old_raw, new_raw,
                                        old_cwd, new_cwd, row["current_manifest_sha256"],
                                        row["candidate_manifest_sha256"], readback_interruptions)
            result["state_before_recovery"] = observed
            if interrupted is None and readback_interruptions:
                interrupted = readback_interruptions[0]
                interruption_phase = "ROLLBACK_INITIAL_READBACK"
            if (observed["plist_identity"] in {"OLD", "CANDIDATE"}
                    and observed["loaded_identity"] == "ABSENT"):
                try:
                    controller.run_ctl("bootstrap", controller.DOMAIN, str(live))
                    expected_cwd, expected_manifest = ((old_cwd, row["current_manifest_sha256"])
                        if observed["plist_identity"] == "OLD" else (new_cwd, row["candidate_manifest_sha256"]))
                    result["recovered_loaded_identity"] = controller.verify_loaded(
                        "main", expected_cwd, live, expected_manifest)
                    result["recovery_action"] = "BOOTSTRAPPED_CURRENT_CAS_BYTES"
                    result["status"] = "ROLLBACK_FAILED_CURRENT_CONFIGURATION_RESTORED"
                except BaseException as recovery_error:
                    result["recovery_error"] = f"{type(recovery_error).__name__}:{recovery_error}"
                    if interrupted is None and not isinstance(recovery_error, Exception):
                        interrupted = recovery_error
                        interruption_phase = "ROLLBACK_RECOVERY_BOOTSTRAP"
            elif (observed["plist_identity"] in {"OLD", "CANDIDATE"}
                    and observed["loaded_identity"] == observed["plist_identity"]):
                result["recovered_loaded_identity"] = observed["loaded"]
                result["status"] = "ROLLBACK_FAILED_CURRENT_CONFIGURATION_STILL_LOADED"
            result["status_before_final_readback"] = result["status"]
            result["phase"] = "ROLLBACK_FINAL_READBACK"
            result["final_state"] = final_main_state(controller, label, live, old_raw, new_raw,
                                                    old_cwd, new_cwd, row["current_manifest_sha256"],
                                                    row["candidate_manifest_sha256"], readback_interruptions)
            if (result["status"].startswith("ROLLBACK_FAILED_CURRENT_CONFIGURATION_")
                    and not (result["final_state"]["plist_identity"] in {"OLD", "CANDIDATE"}
                             and result["final_state"]["plist_identity"] == result["final_state"]["loaded_identity"])):
                result["status"] = "ROLLBACK_INCOMPLETE"
                result["final_readback_mismatch"] = True
            if interrupted is None and readback_interruptions:
                interrupted = readback_interruptions[0]
                interruption_phase = "ROLLBACK_FINAL_READBACK"
            if interrupted is not None:
                interrupt_result(interrupted, result, interruption_phase)
                raise interrupted
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
    interruption = None
    operation_failed = False
    try:
        result = run(args)
    except Exception as exc:
        operation_failed = True
        result = getattr(exc, "v4_cutover_result", None)
        if not isinstance(result, dict):
            result = {"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
        else:
            result["cli_failure"] = f"{type(exc).__name__}:{exc}"
    except BaseException as exc:
        interruption = exc
        result = getattr(exc, "v4_cutover_result", None)
        if not isinstance(result, dict):
            result = {"status": "INTERRUPTED", "scope": "Main-only"}
            interrupt_result(exc, result, "CLI_OR_PREFLIGHT")
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            result.setdefault("interruption", {}).update(original_exit_code=exc.code, effective_exit_code=2)
            exc.code = 2
    try:
        payload = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise CutoverBlocked("RECEIPT_PATH_NOT_REGULAR")
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("RECEIPT_WRITE_MADE_NO_PROGRESS")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException as write_error:
        if interruption is None:
            raise
        note = f"RECEIPT_WRITE_FAILED:{type(write_error).__name__}:{write_error}"
        interruption.add_note(note)
        try:
            print(json.dumps({"receipt_path": str(receipt), "receipt_write_error": note,
                              "transaction_result": result}, ensure_ascii=False), file=sys.stderr)
        except BaseException as notice_error:
            interruption.add_note(f"RECEIPT_FAILURE_NOTICE_FAILED:{type(notice_error).__name__}:{notice_error}")
        raise interruption
    if interruption is not None:
        raise interruption
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not operation_failed and result.get("status") in {"ACTIVATED_MAIN_ONLY", "RESTORED_MAIN_ONLY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
