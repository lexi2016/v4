#!/usr/bin/env python3
"""Task-local R6, fail-closed API + existing scheduler publication adapter.

The normal commands are read-only. ``template`` snapshots current preimages
under the task staging root; ``prepare`` pins an enabled pair produced by the
unchanged original stage helper after a fresh target-20261013 canary;
``check`` revalidates the pair and CAS preimages. ``execute`` exists for the
main-owned later cutover only and was not run by the writer. ``self-test`` uses
temporary plist-named files only and fault-injects both pair-write and
post-write/readback failure recovery.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
import types
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

sys.dont_write_bytecode = True

TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1")
RELEASE_ROOT = TASK_ROOT / "E/integrated_release/issue35-manager-autocontinue-20261012-r6-integrated"
APP_ROOT = RELEASE_ROOT / "app"
MANIFEST_SHA256 = "a63b80727953068d123f768ab608c5a6cf45758aa3ca234c71a8c8892d7cfaf7"
INVENTORY_SHA256 = "5244040fa11b2721a84b92d30d6189f4da83b2d3f8eb99259ba60f3e7d993b5d"
API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
API_LABEL = "com.lexi.v35.api-only"
SCHEDULER_LABEL = "com.lexi.v35.scheduler"
CANONICAL_INTEGRATOR = Path("/Users/lexi/Desktop/学习/v4_app/ops/api_release_integration.py")
CANONICAL_INTEGRATOR_SHA256 = "718dfd1ba18facfb4204e30c557a330bc3a6a45b1636a18ff95a76263e697c9c"
ORIGINAL_OBSERVER = Path("/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/local_fix/r4_mac_fix_20261010_r5/test_support/publication/api_only_cutover_issue32_r4.py")
ORIGINAL_OBSERVER_SHA256 = "864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25"
ACTIVATION_COMMON = TASK_ROOT / "E/tools/issue35_phase4_common.py"
ACTIVATION_COMMON_SHA256 = "d5e8c8aaf591d10df2343dfe1d870019ee431ad708d6478b0863c9cd53a0fa84"
ORIGINAL_PREPARE = TASK_ROOT / "E/tools/issue35_phase4_prepare.py"
ORIGINAL_PREPARE_SHA256 = "4fd235e44a8ed4c4019ece257d5a7c9e9cf2964b1654a9315a3943ceec99e410"
ORIGINAL_CANARY = TASK_ROOT / "E/tools/phase6-r6/issue35_phase6_r6_canary.py"
ORIGINAL_CANARY_SHA256 = "642b81a3f50b54dd1fa7ac688d87162004a01c08cb494c8a402fe55e168e7c5e"
TARGET_DATE = "20261013"
R4B_CANARY_SOURCE = TASK_ROOT / "E/tools/issue35_phase4_canary.py"
R4B_CANARY_SOURCE_SHA256 = "8567287bee4c8920880694855b5ed1420623220801ec2d5bb44b2595eb49c703"
R6_TRANSPORT_TEST = TASK_ROOT / "E/tools/phase6-r6/test_issue35_phase6_r6_transport.py"
DEFAULT_PAIR_DIR = TASK_ROOT / "E/staged_config/phase6-r6/after-canary/pair-r6"
BEFORE_NAMES = {"api": "api-before.plist", "scheduler": "scheduler-before.plist",
                "binding": "manager-binding-before.json"}
AFTER_NAMES = {"api": "api-after.enabled.plist", "scheduler": "scheduler-after.enabled.plist",
               "binding": "manager-plan-binding.json"}
EXPECTED_SAFETY = {"research_only": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False}
EXPECTED_API_ENV_DELTA = {
    "PYTHONPATH", "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256", "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
}
EXPECTED_SCHEDULER_ENV_DELTA = {
    "V4_MANAGER_ANNOUNCEMENT_APP_ROOT", "V4_MANAGER_ANNOUNCEMENT_BINDING",
    "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256", "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256",
}
EXPECTED_SCHEDULER_NOOP_DELTA = EXPECTED_SCHEDULER_ENV_DELTA - {"V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256"}
CYCLE_SHA_ENV_KEY = "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256"
EXISTING_CANARY_PATH = TASK_ROOT / "E/receipts/plan_canary_runs/20261013/execution-03/plan-canary.json"
EXISTING_CANARY_SHA256 = "PENDING_PARENT_R6_CANARY_AND_INDEPENDENT_REVIEW"
EXISTING_STAGE_DIR = TASK_ROOT / "E/staged_config/phase6-r6/after-canary"
EXISTING_STAGE_RECEIPT = EXISTING_STAGE_DIR / "activation-stage-receipt.json"
EXISTING_STAGE_SHA256 = {
    "api": "PENDING_PARENT_ORIGINAL_PREPARE_AND_INDEPENDENT_REVIEW",
    "scheduler": "PENDING_PARENT_ORIGINAL_PREPARE_AND_INDEPENDENT_REVIEW",
    "binding": "PENDING_PARENT_ORIGINAL_PREPARE_AND_INDEPENDENT_REVIEW",
    "receipt": "PENDING_PARENT_ORIGINAL_PREPARE_AND_INDEPENDENT_REVIEW",
}
PUBLICATION_PENDING_PINS = TASK_ROOT / "E/tools/phase6-r6/publication-pending-pins.json"
PUBLICATION_PENDING_PINS_SHA256 = "75809c1385ebac711340729b59e275efeca272b91afa751c2cead2cf7229b861"
ROOT_CAUSE_RECEIPT = TASK_ROOT / "E/receipts/phase4-issue35-target13/pair-env-rootcause.json"
ROOT_CAUSE_RECEIPT_SHA256 = "358d22cd6408d0a5b3e041d02c3e439e9d3fe6e40abdb8e9d70815c9f312c1e9"
ENV_NOOP_SCOPE_SHA256 = "90cc4c8fa9c00ccbcc82766cec17ba664a1326be5d9fb3aa65fadd46583b7435"
PREVIOUS_ADAPTER = TASK_ROOT / "E/tools/issue35_phase4_pair_publication_adapter_r3_noop.py"
PREVIOUS_ADAPTER_SHA256 = "7971552107f2da3365af208a766cbc39822c7164ab911610138e9273a6b65b9e"
SERVICE_OBSERVER_SCOPE_SHA256 = "04e0b3fa85c000b73baf13041c65c78758b0f7e2e8d93afcd82e803fc7a694ba"
SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT = TASK_ROOT / "E/receipts/phase4-issue35-target13/service-observer-rootcause.json"
SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT_SHA256 = "0d89662f6db5b918066185ea2ba1b9eaf800d5be701a901599475ce18ca1097c"
SERVICE_OBSERVER_FIX_SCOPE = TASK_ROOT / "E/PHASE4_SERVICE_OBSERVER_FIX_SCOPE.md"
CANDIDATE_SOURCE_FILES = {
    "cycle": "ops/run_manager_announcement_cycle.py",
    "supervisor": "infrastructure/scheduling/manager_announcement_supervisor.py",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def publication_adapter_identity() -> dict[str, str]:
    path = Path(__file__).resolve(strict=True)
    return {"path": str(path), "sha256": sha(exact_bytes(path, "PUBLICATION_ADAPTER"))}


def validate_scheduler_env_delta(before_env: Mapping[str, str], staged_env: Mapping[str, str],
                                 candidate_cycle_sha256: str) -> set[str]:
    """Allow only the exact legacy delta or the proven candidate-matching cycle no-op."""
    delta = {key for key in set(before_env) | set(staged_env)
             if before_env.get(key) != staged_env.get(key)}
    if delta == EXPECTED_SCHEDULER_ENV_DELTA:
        if staged_env.get(CYCLE_SHA_ENV_KEY) != candidate_cycle_sha256:
            raise ValueError("STAGED_CYCLE_SHA_MISMATCH")
        return delta
    if delta == EXPECTED_SCHEDULER_NOOP_DELTA:
        if (before_env.get(CYCLE_SHA_ENV_KEY) != candidate_cycle_sha256
                or staged_env.get(CYCLE_SHA_ENV_KEY) != candidate_cycle_sha256):
            raise ValueError("UNCHANGED_STAGED_CYCLE_SHA_MISMATCH")
        return delta
    raise ValueError("STAGED_ENV_DELTA_OUT_OF_SCOPE")


def exact_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_REGULAR_FILE")
    return path.read_bytes()


def verify_r6_transport_pins() -> dict[str, Any]:
    """Require the immutable R6 transport record and pending canary/stage pins."""
    raw = exact_bytes(PUBLICATION_PENDING_PINS, "R6_PUBLICATION_PENDING_PINS")
    if sha(raw) != PUBLICATION_PENDING_PINS_SHA256:
        raise ValueError("R6_PUBLICATION_PENDING_PINS_SHA_MISMATCH")
    try:
        pins = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("R6_PUBLICATION_PENDING_PINS_INVALID") from exc
    if not isinstance(pins, dict):
        raise ValueError("R6_PUBLICATION_PENDING_PINS_INVALID")
    candidate = pins.get("candidate", {})
    transport = pins.get("r6_transport", {})
    pending = pins.get("pending_stage", {})
    wrapper = transport.get("canary_wrapper", {}) if isinstance(transport, dict) else {}
    original = transport.get("r4b_canary_source", {}) if isinstance(transport, dict) else {}
    test = transport.get("temp_transport_test", {}) if isinstance(transport, dict) else {}
    if (candidate.get("release_root") != str(RELEASE_ROOT)
            or candidate.get("app_root") != str(APP_ROOT)
            or candidate.get("release_id") != "issue35-manager-autocontinue-20261012-r6-integrated"
            or candidate.get("manifest_sha256") != MANIFEST_SHA256
            or candidate.get("inventory_sha256") != INVENTORY_SHA256
            or transport.get("status") != "READY_FOR_REVIEW_PENDING_R6_CANARY_AND_STAGE"
            or wrapper.get("path") != str(ORIGINAL_CANARY)
            or wrapper.get("sha256") != ORIGINAL_CANARY_SHA256
            or sha(exact_bytes(ORIGINAL_CANARY, "R6_CANARY_WRAPPER")) != ORIGINAL_CANARY_SHA256
            or original.get("path") != str(R4B_CANARY_SOURCE)
            or original.get("sha256") != R4B_CANARY_SOURCE_SHA256
            or sha(exact_bytes(R4B_CANARY_SOURCE, "R4B_CANARY_SOURCE")) != R4B_CANARY_SOURCE_SHA256
            or transport.get("publication_adapter", {}).get("path") != str(Path(__file__).resolve())
            or test.get("path") != str(R6_TRANSPORT_TEST)
            or sha(exact_bytes(R6_TRANSPORT_TEST, "R6_TRANSPORT_TEST")) != test.get("sha256")
            or pending.get("status") != "ROLLBACK_PREIMAGES_ONLY_NO_ENABLED_AFTER_FILES"
            or pending.get("dir") != str(EXISTING_STAGE_DIR)
            or pending.get("canary_path") != str(EXISTING_CANARY_PATH)
            or pending.get("canary_sha256") != EXISTING_CANARY_SHA256
            or pending.get("enabled_stage_sha256") != EXISTING_STAGE_SHA256
            or not isinstance(EXISTING_CANARY_SHA256, str)
            or not EXISTING_CANARY_SHA256.startswith("PENDING_")
            or not all(isinstance(value, str) and value.startswith("PENDING_")
                       for value in EXISTING_STAGE_SHA256.values())):
        raise ValueError("R6_PUBLICATION_TRANSPORT_PINS_MISMATCH")
    return pins


def write_exclusive(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    write_exclusive(path, json_bytes(value))


def import_pinned(path: Path, expected_sha: str, module_name: str) -> types.ModuleType:
    raw = exact_bytes(path, module_name.upper())
    if sha(raw) != expected_sha:
        raise ValueError(module_name.upper() + "_SHA_MISMATCH")
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    sys.modules[module_name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def load_integrator() -> types.ModuleType:
    if str(CANONICAL_INTEGRATOR.parents[1]) not in sys.path:
        sys.path.insert(0, str(CANONICAL_INTEGRATOR.parents[1]))
    if CANONICAL_INTEGRATOR.is_symlink() or not CANONICAL_INTEGRATOR.is_file():
        raise ValueError("CANONICAL_INTEGRATOR_MISSING")
    if sha(exact_bytes(CANONICAL_INTEGRATOR, "CANONICAL_INTEGRATOR")) != CANONICAL_INTEGRATOR_SHA256:
        raise ValueError("CANONICAL_INTEGRATOR_SHA_MISMATCH")
    import ops.api_release_integration as helper
    if Path(helper.__file__).resolve() != CANONICAL_INTEGRATOR or sha(exact_bytes(CANONICAL_INTEGRATOR, "CANONICAL_INTEGRATOR")) != CANONICAL_INTEGRATOR_SHA256:
        raise ValueError("CANONICAL_INTEGRATOR_IDENTITY_MISMATCH")
    required = ("shared_api_release_lock", "assert_api_release_lock", "verify_api_release_candidate",
                "api_release_lock_path")
    if any(not callable(getattr(helper, name, None)) for name in required):
        raise ValueError("CANONICAL_INTEGRATOR_INTERFACE_INVALID")
    return helper


def load_common() -> types.ModuleType:
    return import_pinned(ACTIVATION_COMMON, ACTIVATION_COMMON_SHA256, "issue35_phase4_common")


def load_observer() -> types.ModuleType:
    observer = import_pinned(ORIGINAL_OBSERVER, ORIGINAL_OBSERVER_SHA256, "issue35_phase4_original_observer")
    return observer


def _scheduler_observation_from_output(label: str, output: str) -> dict[str, Any]:
    """Apply the scheduler contract without demanding API-only V35 identity keys."""
    if label != SCHEDULER_LABEL:
        raise ValueError("PAIR_SCHEDULER_OBSERVER_LABEL_NOT_ALLOWED")
    state = re.search(r"(?m)^\s*state\s*=\s*(\S+)", output)
    pid = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", output)
    if not state:
        return {"state": "UNKNOWN", "identity": None,
                "error": "SCHEDULER_LAUNCHCTL_STATE_MISSING", "label": label}
    if state.group(1) != "running":
        return {"state": "UNKNOWN", "identity": None,
                "reported_state": state.group(1), "error": "SCHEDULER_NOT_RUNNING", "label": label}
    if not pid:
        return {"state": "UNKNOWN", "identity": None,
                "reported_state": state.group(1), "error": "SCHEDULER_PID_MISSING", "label": label}
    return {"state": "LOADED", "identity": {"state": "running", "pid": pid.group(1)},
            "label": label, "observer_contract": "EXACT_LABEL_RUNNING_PID"}


def _observe_pair_service(observer: Any, label: str) -> dict[str, Any]:
    """Observe a known pair label using its own fail-closed runtime contract."""
    if label not in {API_LABEL, SCHEDULER_LABEL}:
        raise ValueError("PAIR_SERVICE_OBSERVER_LABEL_NOT_ALLOWED")
    observer.LABEL = label
    if label == API_LABEL:
        # Preserve the pinned original observer's complete API release identity gate.
        try:
            observed = observer._observe_loaded()
        except Exception as exc:
            return {"state": "UNKNOWN", "identity": None,
                    "error": "API_OBSERVER_FAILED:" + type(exc).__name__}
        if not isinstance(observed, Mapping):
            return {"state": "UNKNOWN", "identity": None, "error": "API_OBSERVER_RESULT_INVALID"}
        if observed.get("state") == "LOADED":
            identity = observed.get("identity")
            required = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")
            if not isinstance(identity, Mapping) or any(key not in identity for key in required):
                return {"state": "UNKNOWN", "identity": None,
                        "error": "API_OBSERVER_IDENTITY_INCOMPLETE"}
        return dict(observed)
    try:
        output = observer._launchctl_print()
    except Exception as exc:
        message = str(exc)
        if message.startswith("API_ONLY_LAUNCH_AGENT_NOT_LOADED:"):
            return {"state": "NOT_LOADED", "identity": None, "label": label}
        # Do not turn launchctl errors into an unloaded result or retain raw details.
        return {"state": "UNKNOWN", "identity": None,
                "error": "SCHEDULER_LAUNCHCTL_QUERY_FAILED:" + type(exc).__name__, "label": label}
    return _scheduler_observation_from_output(label, output)


def _recovery_service_observation(observer: Any, label: str) -> dict[str, Any]:
    """Refuse recovery bootout decisions when either service state is ambiguous."""
    observed = _observe_pair_service(observer, label)
    if observed.get("state") not in {"LOADED", "NOT_LOADED"}:
        raise ValueError("PAIR_RECOVERY_REFUSES_UNKNOWN_SERVICE_STATE:" + label)
    return observed


def _observe_original_pair(observer: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require the original API identity and the scheduler's own loaded contract."""
    api = _observe_pair_service(observer, API_LABEL)
    scheduler = _observe_pair_service(observer, SCHEDULER_LABEL)
    if api.get("state") != "LOADED" or scheduler.get("state") != "LOADED":
        raise ValueError("BOTH_ORIGINAL_SERVICES_MUST_BE_LOADED_BEFORE_PAIR_SWITCH")
    return api, scheduler


def env_from_plist(value: Mapping[str, Any]) -> dict[str, str]:
    """Use the exact original helper's environment decoder."""
    common = load_common()
    return common.env_from_plist(dict(value))


def target_metadata(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError("PLIST_PATH_INVALID:" + str(path))
    info = path.stat(follow_symlinks=False)
    if getattr(info, "st_flags", 0) != 0:
        raise ValueError("PLIST_FILE_FLAGS_UNSUPPORTED:" + str(path))
    attrs: dict[str, str] = {}
    if hasattr(os, "listxattr"):
        for name in os.listxattr(path, follow_symlinks=False):
            attrs[name] = sha(os.getxattr(path, name, follow_symlinks=False))
    return {"uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
            "flags": getattr(info, "st_flags", 0), "mtime_ns": info.st_mtime_ns,
            "xattr_sha256": attrs}


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cas_replace(path: Path, raw: bytes, expected_current_sha: str,
                integrator: Any, lease: object, *, fault_after_replace: bool = False) -> dict[str, Any]:
    """Atomic same-directory replacement with per-file SHA and inode CAS."""
    integrator.assert_api_release_lock(lease, API_PLIST)
    before_raw = exact_bytes(path, "CAS_TARGET")
    if sha(before_raw) != expected_current_sha:
        raise ValueError("PAIR_CAS_PREIMAGE_SHA_MISMATCH:" + path.name)
    before_info = path.stat(follow_symlinks=False)
    metadata = target_metadata(path)
    temp = path.with_name("." + path.name + ".issue35-" + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, metadata["uid"], metadata["gid"], follow_symlinks=False)
        os.chmod(temp, metadata["mode"], follow_symlinks=False)
        if hasattr(os, "listxattr"):
            for name in os.listxattr(path, follow_symlinks=False):
                value = os.getxattr(path, name, follow_symlinks=False)
                os.setxattr(temp, name, value, follow_symlinks=False)
        os.utime(temp, ns=(before_info.st_atime_ns, metadata["mtime_ns"]), follow_symlinks=False)
        current_info = path.stat(follow_symlinks=False)
        if ((current_info.st_dev, current_info.st_ino) != (before_info.st_dev, before_info.st_ino)
                or sha(exact_bytes(path, "CAS_TARGET_RECHECK")) != expected_current_sha):
            raise ValueError("PAIR_CAS_PREIMAGE_CHANGED:" + path.name)
        integrator.assert_api_release_lock(lease, API_PLIST)
        os.replace(temp, path)
        fsync_dir(path.parent)
        if fault_after_replace:
            raise OSError("FAULT_INJECTED_AFTER_ATOMIC_REPLACE")
        if sha(exact_bytes(path, "CAS_POSTIMAGE")) != sha(raw):
            raise ValueError("PAIR_CAS_POSTIMAGE_SHA_MISMATCH:" + path.name)
        observed = target_metadata(path)
        if observed != metadata:
            raise ValueError("PAIR_CAS_POSTIMAGE_METADATA_MISMATCH:" + path.name)
        return {"path": str(path), "before_sha256": expected_current_sha,
                "after_sha256": sha(raw), "metadata_preserved": True}
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def pair_state(api_sha: str, scheduler_sha: str, before: Mapping[str, str],
               after: Mapping[str, str]) -> str:
    if api_sha == before["api"] and scheduler_sha == before["scheduler"]:
        return "BEFORE_BOTH"
    if api_sha == after["api"] and scheduler_sha == before["scheduler"]:
        return "API_AFTER_SCHEDULER_BEFORE"
    if api_sha == after["api"] and scheduler_sha == after["scheduler"]:
        return "AFTER_BOTH"
    return "UNEXPECTED_BYTES"


def guarded_recover(api_path: Path, scheduler_path: Path, before_raw: Mapping[str, bytes],
                    after_raw: Mapping[str, bytes], integrator: Any | None, lease: object | None,
                    replace: Callable[[Path, bytes, str], Any]) -> dict[str, Any]:
    """Restore only exact adapter-owned candidate bytes to exact before bytes.

    Allowed states are before/before, API-after + scheduler-before, and
    after/after. Any other pair is an unconditional stop without a write.
    Scheduler is restored first from after/after so an interrupted rollback
    lands in the known API-after + scheduler-before state.
    """
    before = {k: sha(v) for k, v in before_raw.items()}
    after = {k: sha(v) for k, v in after_raw.items()}
    observed = {"api": sha(exact_bytes(api_path, "RECOVERY_API")),
                "scheduler": sha(exact_bytes(scheduler_path, "RECOVERY_SCHEDULER"))}
    state = pair_state(observed["api"], observed["scheduler"], before, after)
    if state == "UNEXPECTED_BYTES":
        raise ValueError("PAIR_RECOVERY_STOP_UNEXPECTED_BYTES:" + json.dumps(observed, sort_keys=True))
    if state == "BEFORE_BOTH":
        return {"status": "ALREADY_BEFORE", "pair_state": state, "writes": []}
    if state == "AFTER_BOTH":
        replace(scheduler_path, before_raw["scheduler"], after["scheduler"])
        observed_mid = {"api": sha(exact_bytes(api_path, "RECOVERY_API")),
                        "scheduler": sha(exact_bytes(scheduler_path, "RECOVERY_SCHEDULER"))}
        if pair_state(observed_mid["api"], observed_mid["scheduler"], before, after) != "API_AFTER_SCHEDULER_BEFORE":
            raise ValueError("PAIR_RECOVERY_STOP_AFTER_SCHEDULER_RESTORE")
        state = "API_AFTER_SCHEDULER_BEFORE"
    if state == "API_AFTER_SCHEDULER_BEFORE":
        replace(api_path, before_raw["api"], after["api"])
        final = {"api": sha(exact_bytes(api_path, "RECOVERY_API")),
                 "scheduler": sha(exact_bytes(scheduler_path, "RECOVERY_SCHEDULER"))}
        if final != before:
            raise ValueError("PAIR_RECOVERY_BEFORE_READBACK_MISMATCH")
        return {"status": "RESTORED_EXACT_PREIMAGES", "pair_state": state,
                "before_sha256": before, "after_sha256": after,
                "final_sha256": final, "writes": ["scheduler-if-after", "api-if-after"]}
    raise ValueError("PAIR_RECOVERY_STATE_NOT_HANDLED:" + state)


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(exact_bytes(path, "JSON_INPUT"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON_INPUT_INVALID:" + str(path)) from exc
    if not isinstance(value, dict):
        raise ValueError("JSON_INPUT_OBJECT_REQUIRED:" + str(path))
    return value


def observe_live(out_path: Path) -> dict[str, Any]:
    """Capture read-only active pair/health via the pinned original observer."""
    observer = load_observer()
    common = load_common()
    plists = common.current_plists(API_PLIST, SCHEDULER_PLIST)
    identity = common.current_identity(APP_ROOT, live=plists)

    def observe_label(label: str) -> dict[str, Any]:
        observer.LABEL = label
        raw = observer._launchctl_print()
        state = re.search(r"(?m)^\s*state\s*=\s*(\S+)", raw)
        pid = re.search(r"(?m)^\s*pid\s*=\s*(\d+)", raw)
        allow = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256",
                 "V4_MANAGER_RESEARCH_STATE_ROOT", "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
                 "V4_MANAGER_ANNOUNCEMENT_APP_ROOT", "V4_MANAGER_ANNOUNCEMENT_BINDING",
                 "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256", "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256")
        env: dict[str, str] = {}
        for key in allow:
            match = re.search(rf"(?m)^\s*{re.escape(key)}=([^\r\n]+)", raw)
            if match:
                env[key] = match.group(1)
        if label == API_LABEL:
            try:
                parsed = observer._loaded_identity(raw)
            except Exception as exc:
                parsed = {"status": "CANNOT_CONFIRM", "error": type(exc).__name__ + ":" + str(exc)}
        else:
            parsed = _scheduler_observation_from_output(label, raw)
        return {"state": state.group(1) if state else "CANNOT_CONFIRM",
                "pid": pid.group(1) if pid else None,
                "standard_identity": parsed, "allowlisted_environment": env}

    api_loaded = observe_label(API_LABEL)
    scheduler_loaded = observe_label(SCHEDULER_LABEL)
    observer.LABEL = API_LABEL
    openapi = observer._verify_openapi(require_manager_route=True)
    health: dict[str, Any] = {"openapi": openapi}
    for route in ("/healthz", "/readyz"):
        status, raw = observer._http_get(route)
        summary: dict[str, Any] = {"http_status": status, "body_sha256": sha(raw), "body_bytes": len(raw)}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                for key in ("status", "ready", "ok", "RESEARCH_ONLY", "production_allowed",
                            "buy_gate_updated", "orders_sent"):
                    if isinstance(payload.get(key), (str, bool, int, float, type(None))):
                        summary[key] = payload[key]
        except Exception:
            summary["body_json"] = "UNPARSEABLE"
        health[route] = summary
    binding_api = Path(plists["api_env"]["V4_MANAGER_PLAN_OWNER_BINDING_PATH"])
    binding_scheduler = Path(plists["scheduler_env"]["V4_MANAGER_ANNOUNCEMENT_BINDING"])
    receipt = {
        "schema_version": "v4.issue35.phase4.live_observer.v1", "status": "READ_ONLY_OBSERVER_CAPTURE",
        "observer": {"path": str(ORIGINAL_OBSERVER), "sha256": ORIGINAL_OBSERVER_SHA256,
                     "functions": ["_launchctl_print", "_loaded_identity", "_verify_openapi", "_http_get"]},
        "loaded": {"api": api_loaded, "scheduler": scheduler_loaded}, "health": health,
        "plists": {"api_path": str(API_PLIST), "api_sha256": plists["api_sha256"],
                    "scheduler_path": str(SCHEDULER_PLIST), "scheduler_sha256": plists["scheduler_sha256"],
                    "api_working_directory": plists["api"].get("WorkingDirectory"),
                    "scheduler_working_directory": plists["scheduler"].get("WorkingDirectory"),
                    "scheduler_program_arguments_sha256": sha(json.dumps(plists["scheduler"].get("ProgramArguments"),
                        ensure_ascii=False, separators=(",", ":")).encode()),
                    "api_env": {k: plists["api_env"].get(k) for k in (
                        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
                        "V35_RELEASE_MANIFEST_SHA256", "V4_MANAGER_RESEARCH_STATE_ROOT",
                        "V4_MANAGER_PLAN_OWNER_BINDING_PATH")},
                    "scheduler_env": {k: plists["scheduler_env"].get(k) for k in (
                        "V35_APP_ROOT", "V4_MANAGER_RESEARCH_STATE_ROOT", "V4_MANAGER_ANNOUNCEMENT_APP_ROOT",
                        "V4_MANAGER_ANNOUNCEMENT_BINDING", "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256",
                        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256")} },
        "binding": {"api_path": str(binding_api), "api_sha256": sha(exact_bytes(binding_api, "API_BINDING")),
                    "scheduler_path": str(binding_scheduler), "scheduler_sha256": sha(exact_bytes(binding_scheduler, "SCHEDULER_BINDING")),
                    "api_enabled": identity["api_binding"].get("enabled"),
                    "scheduler_enabled": identity["scheduler_binding"].get("enabled"),
                    "announcement_collection_enabled": identity["api_binding"].get("announcement_collection_enabled"),
                    "research_only": identity["api_binding"].get("research_only"),
                    "production_allowed": identity["api_binding"].get("production_allowed"),
                    "buy_gate_updated": identity["api_binding"].get("buy_gate_updated"),
                    "orders_sent": identity["api_binding"].get("orders_sent"),
                    "manager_state_root": str(identity["state_root"]),
                    "security_master_root": str(identity["master_root"])},
        "actions": {"http_posts": 0, "live_config_writes": 0,
                    "launchctl_mutations": 0, "manager_state_writes": 0},
    }
    write_json_exclusive(out_path, receipt)
    return receipt


def template(pair_dir: Path, observer_receipt: Path) -> dict[str, Any]:
    verify_r6_transport_pins()
    if pair_dir != DEFAULT_PAIR_DIR or TASK_ROOT / "E/staged_config" not in pair_dir.parents:
        raise ValueError("PAIR_TEMPLATE_PATH_OUTSIDE_PHASE4_SCOPE")
    if pair_dir.exists() or pair_dir.is_symlink():
        raise FileExistsError("PHASE4_PAIR_DIR_ALREADY_EXISTS:" + str(pair_dir))
    common = load_common()
    observed = _json_file(observer_receipt)
    current = common.current_plists(API_PLIST, SCHEDULER_PLIST)
    if observed.get("plists", {}).get("api_sha256") != current["api_sha256"] or observed.get("plists", {}).get("scheduler_sha256") != current["scheduler_sha256"]:
        raise ValueError("LIVE_PLIST_PREIMAGES_CHANGED_SINCE_OBSERVER")
    candidate = load_integrator().verify_api_release_candidate(
        candidate_root=RELEASE_ROOT, active_api_plist_path=API_PLIST,
        expected_manifest_sha256=MANIFEST_SHA256, active_pointer="base")
    canary_raw = exact_bytes(EXISTING_CANARY_PATH, "PINNED_CURRENT13_CANARY")
    if sha(canary_raw) != EXISTING_CANARY_SHA256:
        raise ValueError("PINNED_CURRENT13_CANARY_SHA_MISMATCH")
    canary_value = json.loads(canary_raw)
    if canary_value.get("status") != "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING" or canary_value.get("target_trade_date") != TARGET_DATE:
        raise ValueError("PINNED_CURRENT13_CANARY_IDENTITY_MISMATCH")
    stage_paths = {
        "api": EXISTING_STAGE_DIR / "com.lexi.v35.api-only.plist",
        "scheduler": EXISTING_STAGE_DIR / "com.lexi.v35.scheduler.plist",
        "binding": EXISTING_STAGE_DIR / AFTER_NAMES["binding"],
        "receipt": EXISTING_STAGE_RECEIPT,
    }
    stage_hashes = {key: sha(exact_bytes(path, "PINNED_ENABLED_STAGE_" + key.upper()))
                    for key, path in stage_paths.items()}
    if stage_hashes != EXISTING_STAGE_SHA256:
        raise ValueError("PINNED_ENABLED_STAGE_SHA_MISMATCH")
    if sha(exact_bytes(ROOT_CAUSE_RECEIPT, "ENV_NOOP_ROOT_CAUSE")) != ROOT_CAUSE_RECEIPT_SHA256:
        raise ValueError("ENV_NOOP_ROOT_CAUSE_SHA_MISMATCH")
    if (sha(exact_bytes(SERVICE_OBSERVER_FIX_SCOPE, "SERVICE_OBSERVER_FIX_SCOPE"))
            != SERVICE_OBSERVER_SCOPE_SHA256):
        raise ValueError("SERVICE_OBSERVER_FIX_SCOPE_SHA_MISMATCH")
    if (sha(exact_bytes(SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT, "SERVICE_OBSERVER_ROOT_CAUSE"))
            != SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT_SHA256):
        raise ValueError("SERVICE_OBSERVER_ROOT_CAUSE_SHA_MISMATCH")
    if sha(exact_bytes(PREVIOUS_ADAPTER, "PREVIOUS_R3_ADAPTER")) != PREVIOUS_ADAPTER_SHA256:
        raise ValueError("PREVIOUS_R3_ADAPTER_SHA_MISMATCH")
    candidate_source_files = {
        key: {"path": str(APP_ROOT / relative),
              "sha256": sha(exact_bytes(APP_ROOT / relative, "PINNED_CANDIDATE_SOURCE_" + key.upper()))}
        for key, relative in CANDIDATE_SOURCE_FILES.items()
    }
    pair_dir.mkdir(parents=True, exist_ok=False)
    before_raw = {"api": current["api_raw"], "scheduler": current["scheduler_raw"]}
    api_binding_path = Path(current["api_env"]["V4_MANAGER_PLAN_OWNER_BINDING_PATH"])
    binding_raw = exact_bytes(api_binding_path, "CURRENT_MANAGER_BINDING")
    files = {"api": pair_dir / BEFORE_NAMES["api"],
             "scheduler": pair_dir / BEFORE_NAMES["scheduler"],
             "binding": pair_dir / BEFORE_NAMES["binding"]}
    for key, raw in (("api", before_raw["api"]), ("scheduler", before_raw["scheduler"]), ("binding", binding_raw)):
        write_exclusive(files[key], raw)
    value = {
        "schema_version": "v4.issue35.phase4.pair_plan_template.v1",
        "status": "WAITING_FOR_TARGET13_CANARY_AND_ORIGINAL_ENABLED_STAGE",
        "publication_adapter": publication_adapter_identity(),
        "fix_basis": {"scope_sha256": ENV_NOOP_SCOPE_SHA256,
                      "root_cause_receipt": str(ROOT_CAUSE_RECEIPT),
                      "root_cause_receipt_sha256": ROOT_CAUSE_RECEIPT_SHA256,
                      "accepted_scheduler_delta": sorted(EXPECTED_SCHEDULER_NOOP_DELTA),
                      "unchanged_cycle_sha_must_equal_candidate": True},
        "service_observer_fix": {
            "scope_path": str(SERVICE_OBSERVER_FIX_SCOPE),
            "scope_sha256": SERVICE_OBSERVER_SCOPE_SHA256,
            "root_cause_receipt": str(SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT),
            "root_cause_receipt_sha256": SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT_SHA256,
            "previous_adapter_path": str(PREVIOUS_ADAPTER),
            "previous_adapter_sha256": PREVIOUS_ADAPTER_SHA256,
            "api_observer_contract": "PINNED_ORIGINAL_API_RELEASE_IDENTITY",
            "scheduler_observer_contract": "EXACT_LABEL_LAUNCHCTL_RUNNING_STATE_AND_NUMERIC_PID",
        },
        "candidate_source_files": candidate_source_files,
        "target13_canary": {"path": str(EXISTING_CANARY_PATH),
                             "sha256": sha(canary_raw),
                             "run_id": canary_value.get("run_id"),
                             "product_sha256": canary_value.get("product_sha256"),
                             "input_identity": canary_value.get("input_identity"),
                             "status": canary_value.get("status")},
        "original_enabled_stage": {"dir": str(EXISTING_STAGE_DIR),
                                   "sha256": stage_hashes},
        "target_trade_date": TARGET_DATE,
        "candidate": {"release_root": str(RELEASE_ROOT), "app_root": str(APP_ROOT),
                      "release_id": "issue35-manager-autocontinue-20261012-r6-integrated",
                      "manifest_path": str(RELEASE_ROOT / "release-manifest.json"),
                      "manifest_sha256": MANIFEST_SHA256,
                      "inventory_sha256": candidate["candidate"]["application_inventory_sha256"]},
        "canonical_integrator": {"path": str(CANONICAL_INTEGRATOR), "sha256": CANONICAL_INTEGRATOR_SHA256,
                                 "functions": ["verify_api_release_candidate", "shared_api_release_lock",
                                               "assert_api_release_lock", "api_release_lock_path"]},
        "original_observer": {"path": str(ORIGINAL_OBSERVER), "sha256": ORIGINAL_OBSERVER_SHA256},
        "original_helpers": {"activation_common": {"path": str(ACTIVATION_COMMON), "sha256": ACTIVATION_COMMON_SHA256},
                             "prepare": {"path": str(ORIGINAL_PREPARE), "sha256": ORIGINAL_PREPARE_SHA256},
                             "canary": {"path": str(ORIGINAL_CANARY), "sha256": ORIGINAL_CANARY_SHA256}},
        "lock_path": str(load_integrator().api_release_lock_path(API_PLIST)),
        "service_labels": {"api": API_LABEL, "scheduler": SCHEDULER_LABEL},
        "files": {k: {"path": str(files[k]), "sha256": sha(exact_bytes(files[k], "PINNED_BEFORE"))}
                  for k in files},
        "pair_cas": {
            "api": {"live_path": str(API_PLIST), "before_sha256": sha(before_raw["api"]),
                    "after_path": "UNAVAILABLE_UNTIL_ORIGINAL_STAGE_ENABLED",
                    "after_sha256": "CANNOT_CONFIRM_UNTIL_FRESH_TARGET13_CANARY"},
            "scheduler": {"live_path": str(SCHEDULER_PLIST), "before_sha256": sha(before_raw["scheduler"]),
                          "after_path": "UNAVAILABLE_UNTIL_ORIGINAL_STAGE_ENABLED",
                          "after_sha256": "CANNOT_CONFIRM_UNTIL_FRESH_TARGET13_CANARY"},
        },
        "protocol": {
            "lock": "Acquire canonical shared_api_release_lock(API_PLIST); assert before and immediately before each pointer CAS.",
            "preflight": "Require both live before hashes, exact enabled-stage output hashes, matching release verifier and binding/canary pins.",
            "write_order": ["API after exact CAS", "read back API after", "scheduler after exact CAS", "read back both after"],
            "reload_gate": "Do not bootout/bootstrap/reload either service until BOTH plist byte hashes read back as their pinned after hashes.",
            "reload_both": ["bootout API and existing scheduler", "bootstrap API", "verify API loaded identity+health/safety", "bootstrap existing scheduler", "verify scheduler process state and preserved HK root/argv + loaded env when exposed"],
            "rollback_states": {
                "api_after_scheduler_before": "Only restore API after->exact before if scheduler still equals exact before; else STOP without write.",
                "both_after": "On reload/readback failure, restore scheduler after->before first, read back recognized api_after_scheduler_before state, then API after->before.",
                "reload_failure": "After both after bytes read back, bootout only observed candidate-loaded labels, restore pair under same lock and exact CAS, then bootstrap exact original loaded services and verify.",
                "unexpected_bytes": "STOP; do not overwrite any plist. Preserve evidence and request root adjudication.",
            },
            "rollback_owner_boundary": "Main-owned later operation only; adapter execute is not run in writer phase.",
        },
        "current13_owner_acceptance": {
            "mode": "R6_TARGET13_CANARY_PINNED_NO_RERUN",
            "canary_path": str(EXISTING_CANARY_PATH),
            "canary_sha256": sha(canary_raw),
            "accepted_run_id": canary_value.get("run_id"),
            "accepted_product_sha256": canary_value.get("product_sha256"),
            "accepted_input_identity": canary_value.get("input_identity"),
            "accepted_status": canary_value.get("status"),
            "root_cause_receipt": str(ROOT_CAUSE_RECEIPT),
            "root_cause_receipt_sha256": ROOT_CAUSE_RECEIPT_SHA256,
            "parent_execute_command": None,
            "execute_preflight": "The exact execution-03 R6 canary must already be present and independently accepted; do not repeat owner POST/GET or write target13 state in this adapter phase.",
            "writer_template_side_effects": {"http_calls": 0, "owner_state_writes": 0, "launchctl_calls": 0},
        },
        "old_phase2_preview": {"path": str(TASK_ROOT / "E/staged_config/issue35-manager-autocontinue-20261012-r3-pending-r4"),
                                "status": "NOT_ACTIVATABLE", "reason": "disabled preview plists point at unstaged manager-plan-binding.json"},
        "safety": EXPECTED_SAFETY,
    }
    plan_path = pair_dir / "pair-plan.template.json"
    write_json_exclusive(plan_path, value)
    return {"status": value["status"], "pair_dir": str(pair_dir), "plan_path": str(plan_path),
            "plan_sha256": sha(exact_bytes(plan_path, "PAIR_TEMPLATE")),
            "before_sha256": {k: sha(v) for k, v in before_raw.items()},
            "after_sha256": "CANNOT_CONFIRM_UNTIL_FRESH_TARGET13_CANARY", "candidate_status": candidate["status"]}


def validate_stage_pair(stage_dir: Path, prep_receipt_path: Path,
                        canary_path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    verify_r6_transport_pins()
    if (stage_dir != EXISTING_STAGE_DIR or prep_receipt_path != EXISTING_STAGE_RECEIPT
            or canary_path != EXISTING_CANARY_PATH):
        raise ValueError("EXISTING_TARGET13_STAGE_AND_CANARY_PATHS_REQUIRED")
    common = load_common()
    stage = {"api": stage_dir / AFTER_NAMES["api"],
             "scheduler": stage_dir / AFTER_NAMES["scheduler"],
             "binding": stage_dir / AFTER_NAMES["binding"]}
    # Original helper writes named API/scheduler files with these exact names.
    stage["api"] = stage_dir / "com.lexi.v35.api-only.plist"
    stage["scheduler"] = stage_dir / "com.lexi.v35.scheduler.plist"
    prep = _json_file(prep_receipt_path)
    if prep.get("schema_version") != "v4.us_daily_chain.activation_stage.v1" or prep.get("status") != "PREPARED_NOT_ACTIVATED":
        raise ValueError("ORIGINAL_ENABLED_PREP_RECEIPT_REQUIRED")
    if prep.get("target_trade_date") != TARGET_DATE or prep.get("release_manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("ORIGINAL_ENABLED_PREP_IDENTITY_MISMATCH")
    canary_raw = exact_bytes(canary_path, "FRESH_CANARY")
    canary_sha = sha(canary_raw)
    if canary_sha != EXISTING_CANARY_SHA256:
        raise ValueError("PINNED_CURRENT13_CANARY_SHA_MISMATCH")
    if prep.get("canary_path") != str(canary_path) or prep.get("canary_sha256") != canary_sha:
        raise ValueError("ORIGINAL_PREP_CANARY_PIN_MISMATCH")
    if prep.get("launchctl_called") is not False or prep.get("live_plists_modified") is not False:
        raise ValueError("ORIGINAL_PREP_HELPER_SIDE_EFFECT_CLAIM_INVALID")
    binding = _json_file(stage_dir / AFTER_NAMES["binding"])
    if binding.get("enabled") is not True or binding.get("plan_material_refresh_only") is not True:
        raise ValueError("ENABLED_PLAN_BINDING_REQUIRED")
    if binding.get("announcement_collection_enabled") is not False:
        raise ValueError("ANNOUNCEMENT_COLLECTION_MUST_REMAIN_DISABLED")
    safety = {"research_only": binding.get("research_only"),
              "production_allowed": binding.get("production_allowed"),
              "buy_gate_updated": binding.get("buy_gate_updated"),
              "orders_sent": binding.get("orders_sent")}
    if safety != EXPECTED_SAFETY:
        raise ValueError("ENABLED_BINDING_SAFETY_MISMATCH")
    if binding.get("app_root") != str(APP_ROOT) or binding.get("manager_state_root") != prep.get("manager_state_root"):
        raise ValueError("ENABLED_BINDING_ROOT_MISMATCH")
    activation = binding.get("plan_activation_receipt")
    if not isinstance(activation, dict) or activation.get("path") != str(canary_path) or activation.get("sha256") != canary_sha:
        raise ValueError("ENABLED_BINDING_CANARY_RECEIPT_MISMATCH")
    if binding.get("plan_owner", {}).get("app_root") != str(APP_ROOT):
        raise ValueError("ENABLED_BINDING_OWNER_ROOT_MISMATCH")
    raw = {key: exact_bytes(path, "STAGED_" + key.upper()) for key, path in stage.items()}
    stage_hashes = {key: sha(raw[key]) for key in raw}
    stage_hashes["receipt"] = sha(exact_bytes(prep_receipt_path, "STAGED_RECEIPT"))
    if stage_hashes != EXISTING_STAGE_SHA256:
        raise ValueError("PINNED_ENABLED_STAGE_SHA_MISMATCH")
    parsed = {key: plistlib.loads(raw[key]) for key in ("api", "scheduler")}
    before = load_common().current_plists(API_PLIST, SCHEDULER_PLIST)
    before_identity = common.current_identity(APP_ROOT, live=before)
    api_env = common.env_from_plist(parsed["api"])
    sched_env = common.env_from_plist(parsed["scheduler"])
    if parsed["api"].get("WorkingDirectory") != str(APP_ROOT):
        raise ValueError("STAGED_API_WORKING_DIRECTORY_MISMATCH")
    if parsed["scheduler"].get("WorkingDirectory") != before["scheduler"].get("WorkingDirectory") or parsed["scheduler"].get("ProgramArguments") != before["scheduler"].get("ProgramArguments"):
        raise ValueError("STAGED_SCHEDULER_LAUNCH_SHAPE_CHANGED")
    if sched_env.get("V35_APP_ROOT") != before["scheduler_env"].get("V35_APP_ROOT"):
        raise ValueError("STAGED_SCHEDULER_HK_APP_ROOT_CHANGED")
    required_api = {"V35_APP_ROOT": str(APP_ROOT), "V35_RELEASE_ID": "issue35-manager-autocontinue-20261012-r4b",
                    "V35_RELEASE_MANIFEST_PATH": str(RELEASE_ROOT / "release-manifest.json"),
                    "V35_RELEASE_MANIFEST_SHA256": MANIFEST_SHA256,
                    "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(stage_dir / AFTER_NAMES["binding"])}
    if any(api_env.get(k) != v for k, v in required_api.items()):
        raise ValueError("STAGED_API_ENV_IDENTITY_MISMATCH")
    if (sched_env.get("V4_MANAGER_ANNOUNCEMENT_APP_ROOT") != str(APP_ROOT)
            or sched_env.get("V4_MANAGER_ANNOUNCEMENT_BINDING") != str(stage_dir / AFTER_NAMES["binding"])
            or sched_env.get("V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256") != canary_sha):
        raise ValueError("STAGED_SCHEDULER_MANAGER_ENV_MISMATCH")
    api_delta = {k for k in set(before["api_env"]) | set(api_env) if before["api_env"].get(k) != api_env.get(k)}
    candidate_cycle_sha = sha(exact_bytes(APP_ROOT / CANDIDATE_SOURCE_FILES["cycle"], "CANDIDATE_CYCLE_SCRIPT"))
    scheduler_delta = validate_scheduler_env_delta(before["scheduler_env"], sched_env, candidate_cycle_sha)
    if api_delta != EXPECTED_API_ENV_DELTA:
        raise ValueError("STAGED_ENV_DELTA_OUT_OF_SCOPE")
    if before_identity["state_root"] != Path(prep.get("manager_state_root", "")):
        raise ValueError("MANAGER_STATE_ROOT_CHANGED_SINCE_CANARY")
    return {"prep": prep, "canary_sha256": canary_sha, "binding_sha256": sha(raw["binding"]),
            "api_sha256": sha(raw["api"]), "scheduler_sha256": sha(raw["scheduler"]),
            "api_env_delta": sorted(api_delta), "scheduler_env_delta": sorted(scheduler_delta),
            "scheduler_cycle_sha_mode": ("NOOP_MATCHES_CANDIDATE" if CYCLE_SHA_ENV_KEY not in scheduler_delta
                                         else "CHANGED_TO_CANDIDATE"),
            "candidate_cycle_sha256": candidate_cycle_sha,
            "before_api_sha256": before["api_sha256"], "before_scheduler_sha256": before["scheduler_sha256"]}, raw


def verify_pair_pins(value: Mapping[str, Any]) -> None:
    verify_r6_transport_pins()
    if value.get("publication_adapter") != publication_adapter_identity():
        raise ValueError("PAIR_PUBLICATION_ADAPTER_PIN_MISMATCH")
    fix_basis = value.get("fix_basis", {})
    if (fix_basis.get("scope_sha256") != ENV_NOOP_SCOPE_SHA256
            or fix_basis.get("root_cause_receipt") != str(ROOT_CAUSE_RECEIPT)
            or fix_basis.get("root_cause_receipt_sha256") != ROOT_CAUSE_RECEIPT_SHA256):
        raise ValueError("PAIR_ENV_NOOP_BASIS_PIN_MISMATCH")
    if sha(exact_bytes(ROOT_CAUSE_RECEIPT, "ENV_NOOP_ROOT_CAUSE")) != ROOT_CAUSE_RECEIPT_SHA256:
        raise ValueError("ENV_NOOP_ROOT_CAUSE_SHA_MISMATCH")
    service_fix = value.get("service_observer_fix", {})
    expected_service_fix = {
        "scope_path": str(SERVICE_OBSERVER_FIX_SCOPE),
        "scope_sha256": SERVICE_OBSERVER_SCOPE_SHA256,
        "root_cause_receipt": str(SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT),
        "root_cause_receipt_sha256": SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT_SHA256,
        "previous_adapter_path": str(PREVIOUS_ADAPTER),
        "previous_adapter_sha256": PREVIOUS_ADAPTER_SHA256,
        "api_observer_contract": "PINNED_ORIGINAL_API_RELEASE_IDENTITY",
        "scheduler_observer_contract": "EXACT_LABEL_LAUNCHCTL_RUNNING_STATE_AND_NUMERIC_PID",
    }
    if service_fix != expected_service_fix:
        raise ValueError("PAIR_SERVICE_OBSERVER_FIX_BASIS_PIN_MISMATCH")
    if (sha(exact_bytes(SERVICE_OBSERVER_FIX_SCOPE, "SERVICE_OBSERVER_FIX_SCOPE"))
            != SERVICE_OBSERVER_SCOPE_SHA256):
        raise ValueError("SERVICE_OBSERVER_FIX_SCOPE_SHA_MISMATCH")
    if (sha(exact_bytes(SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT, "SERVICE_OBSERVER_ROOT_CAUSE"))
            != SERVICE_OBSERVER_ROOT_CAUSE_RECEIPT_SHA256):
        raise ValueError("SERVICE_OBSERVER_ROOT_CAUSE_SHA_MISMATCH")
    if sha(exact_bytes(PREVIOUS_ADAPTER, "PREVIOUS_R3_ADAPTER")) != PREVIOUS_ADAPTER_SHA256:
        raise ValueError("PREVIOUS_R3_ADAPTER_SHA_MISMATCH")
    source_files = value.get("candidate_source_files")
    if not isinstance(source_files, dict) or set(source_files) != set(CANDIDATE_SOURCE_FILES):
        raise ValueError("PAIR_CANDIDATE_SOURCE_PIN_SET_MISMATCH")
    for key, relative in CANDIDATE_SOURCE_FILES.items():
        record = source_files[key]
        path = APP_ROOT / relative
        if record.get("path") != str(path) or record.get("sha256") != sha(exact_bytes(path, "PINNED_CANDIDATE_SOURCE_" + key.upper())):
            raise ValueError("PAIR_CANDIDATE_SOURCE_PIN_MISMATCH:" + key)
    canary = value.get("target13_canary", {})
    if canary.get("path") != str(EXISTING_CANARY_PATH) or canary.get("sha256") != sha(exact_bytes(EXISTING_CANARY_PATH, "PINNED_CURRENT13_CANARY")):
        raise ValueError("PAIR_CURRENT13_CANARY_PIN_MISMATCH")
    if canary.get("sha256") != EXISTING_CANARY_SHA256:
        raise ValueError("PAIR_CURRENT13_CANARY_EXPECTED_SHA_MISMATCH")
    stage = value.get("original_enabled_stage", {})
    if stage.get("dir") != str(EXISTING_STAGE_DIR) or stage.get("sha256") != EXISTING_STAGE_SHA256:
        raise ValueError("PAIR_ENABLED_STAGE_PIN_MISMATCH")
    stage_paths = {
        "api": EXISTING_STAGE_DIR / "com.lexi.v35.api-only.plist",
        "scheduler": EXISTING_STAGE_DIR / "com.lexi.v35.scheduler.plist",
        "binding": EXISTING_STAGE_DIR / AFTER_NAMES["binding"],
        "receipt": EXISTING_STAGE_RECEIPT,
    }
    observed = {key: sha(exact_bytes(path, "PINNED_ENABLED_STAGE_" + key.upper()))
                for key, path in stage_paths.items()}
    if observed != EXISTING_STAGE_SHA256:
        raise ValueError("PINNED_ENABLED_STAGE_SHA_MISMATCH")


def prepare_pair(pair_dir: Path, stage_dir: Path, prep_receipt: Path, canary_path: Path) -> dict[str, Any]:
    if pair_dir != DEFAULT_PAIR_DIR:
        raise ValueError("PAIR_OUTPUT_PATH_NOT_PINNED")
    template_path = pair_dir / "pair-plan.template.json"
    template_value = _json_file(template_path)
    if template_value.get("status") != "WAITING_FOR_TARGET13_CANARY_AND_ORIGINAL_ENABLED_STAGE":
        raise ValueError("PAIR_TEMPLATE_STATUS_INVALID")
    verify_pair_pins(template_value)
    details, staged_raw = validate_stage_pair(stage_dir, prep_receipt, canary_path)
    if (template_value.get("target13_canary", {}).get("sha256") != details["canary_sha256"]
            or template_value.get("original_enabled_stage", {}).get("sha256") != EXISTING_STAGE_SHA256):
        raise ValueError("PAIR_SAVED_INPUT_PINS_DO_NOT_MATCH_STAGE")
    common = load_common()
    live = common.current_plists(API_PLIST, SCHEDULER_PLIST)
    expected_before = {"api": template_value["pair_cas"]["api"]["before_sha256"],
                       "scheduler": template_value["pair_cas"]["scheduler"]["before_sha256"]}
    if live["api_sha256"] != expected_before["api"] or live["scheduler_sha256"] != expected_before["scheduler"]:
        raise ValueError("LIVE_PAIR_PREIMAGE_CHANGED_SINCE_TEMPLATE")
    result = dict(template_value)
    result["schema_version"] = "v4.issue35.phase4.pair_plan.v1"
    result["status"] = "PREPARED_CHECK_ONLY_NOT_PUBLISHED"
    result["enabled_stage"] = {"dir": str(stage_dir), "prep_receipt_path": str(prep_receipt),
                               "canary_path": str(canary_path), **details}
    result["files"].update({"after_api": {"path": str(stage_dir / "com.lexi.v35.api-only.plist"), "sha256": details["api_sha256"]},
                            "after_scheduler": {"path": str(stage_dir / "com.lexi.v35.scheduler.plist"), "sha256": details["scheduler_sha256"]},
                            "after_binding": {"path": str(stage_dir / AFTER_NAMES["binding"]), "sha256": details["binding_sha256"]}})
    result["pair_cas"] = {"api": {"live_path": str(API_PLIST), "before_sha256": expected_before["api"],
                                  "after_path": str(stage_dir / "com.lexi.v35.api-only.plist"), "after_sha256": details["api_sha256"]},
                          "scheduler": {"live_path": str(SCHEDULER_PLIST), "before_sha256": expected_before["scheduler"],
                                         "after_path": str(stage_dir / "com.lexi.v35.scheduler.plist"), "after_sha256": details["scheduler_sha256"]}}
    result["required_confirmation"] = "ISSUE35_PAIR_20261013_" + sha(json_bytes(result))[:16]
    result["operator_commands"] = {
        "check_only": f"{sys.executable} -B {TASK_ROOT}/E/tools/phase6-r6/issue35_phase6_r6_publication_adapter.py check --pair-dir {pair_dir}",
        "execute_main_owned_only": f"{sys.executable} -B {TASK_ROOT}/E/tools/phase6-r6/issue35_phase6_r6_publication_adapter.py execute --pair-dir {pair_dir} --confirm {result['required_confirmation']}",
        "rollback_main_owned_only": f"{sys.executable} -B {TASK_ROOT}/E/tools/phase6-r6/issue35_phase6_r6_publication_adapter.py rollback --pair-dir {pair_dir} --confirm {result['required_confirmation']} --expected-current pair-after",
    }
    complete_path = pair_dir / "pair-plan.json"
    write_json_exclusive(complete_path, result)
    return {"status": result["status"], "pair_plan_path": str(complete_path),
            "pair_plan_sha256": sha(exact_bytes(complete_path, "PAIR_PLAN")),
            "api_cas": result["pair_cas"]["api"], "scheduler_cas": result["pair_cas"]["scheduler"],
            "required_confirmation": result["required_confirmation"]}


def check_plan(pair_dir: Path, *, expect: str = "before") -> dict[str, Any]:
    plan = _json_file(pair_dir / "pair-plan.json")
    verify_pair_pins(plan)
    if plan.get("schema_version") != "v4.issue35.phase4.pair_plan.v1" or plan.get("status") != "PREPARED_CHECK_ONLY_NOT_PUBLISHED":
        raise ValueError("PAIR_PLAN_NOT_PREPARED")
    before = {"api": plan["pair_cas"]["api"]["before_sha256"],
              "scheduler": plan["pair_cas"]["scheduler"]["before_sha256"]}
    after = {"api": plan["pair_cas"]["api"]["after_sha256"],
             "scheduler": plan["pair_cas"]["scheduler"]["after_sha256"]}
    observed = {"api": sha(exact_bytes(API_PLIST, "LIVE_API_PLIST")),
                "scheduler": sha(exact_bytes(SCHEDULER_PLIST, "LIVE_SCHEDULER_PLIST"))}
    expected = before if expect == "before" else after
    if observed != expected:
        raise ValueError("LIVE_PAIR_STATE_MISMATCH:" + json.dumps(observed, sort_keys=True))
    # Revalidate immutable candidate, using canonical shared verifier against the expected current pointer.
    integrator = load_integrator()
    if expect == "before":
        verification = integrator.verify_api_release_candidate(
            candidate_root=RELEASE_ROOT, active_api_plist_path=API_PLIST,
            expected_manifest_sha256=MANIFEST_SHA256, active_pointer="base")
    else:
        verification = integrator.verify_api_release_candidate(
            candidate_root=RELEASE_ROOT, active_api_plist_path=API_PLIST,
            expected_manifest_sha256=MANIFEST_SHA256, active_pointer="candidate")
    for key, path_key in (("api", "after_api"), ("scheduler", "after_scheduler"), ("binding", "after_binding")):
        staged = plan["files"][path_key]
        if sha(exact_bytes(Path(staged["path"]), "STAGED_" + key.upper())) != staged["sha256"]:
            raise ValueError("STAGED_PAIR_BYTES_CHANGED:" + key)
    return {"status": "PASS_CHECK_ONLY", "expected_state": expect, "live_pair_sha256": observed,
            "candidate_verification": verification, "lock_path": plan["lock_path"],
            "services_mutated": False, "http_posts": 0}


def _load_original_observer() -> types.ModuleType:
    return load_observer()


def _launch_action(observer: Any, label: str, plist_path: Path, action: str) -> None:
    observer.LABEL = label
    observer.ACTIVE_API_PLIST = plist_path
    observer._launchctl_action(action)


def _wait_label(observer: Any, label: str, expected_loaded: bool, timeout: float = 30.0) -> dict[str, Any]:
    if label not in {API_LABEL, SCHEDULER_LABEL}:
        raise ValueError("PAIR_SERVICE_OBSERVER_LABEL_NOT_ALLOWED")
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {"state": "UNKNOWN", "error": "NO_OBSERVATION"}
    while time.monotonic() < deadline:
        latest = _observe_pair_service(observer, label)
        if expected_loaded and latest.get("state") == "LOADED":
            identity = latest.get("identity")
            pid = identity.get("pid") if isinstance(identity, Mapping) else None
            return {"present": True, "state": "running", "pid": pid}
        if not expected_loaded and latest.get("state") == "NOT_LOADED":
            return {"present": False, "error": "SERVICE_NOT_LOADED"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.25, remaining))
    identity = latest.get("identity")
    pid = identity.get("pid") if isinstance(identity, Mapping) else None
    summary = {"observer_state": latest.get("state"), "reported_state": latest.get("reported_state"),
               "pid": pid, "error": latest.get("error")}
    raise ValueError("LAUNCHCTL_STATE_TIMEOUT:" + label + ":" + json.dumps(summary, sort_keys=True))


def execute_or_rollback(pair_dir: Path, action: str, confirmation: str,
                        expected_current: str | None = None) -> dict[str, Any]:
    """Later main-owned transaction. The writer never invokes this entrypoint."""
    plan = _json_file(pair_dir / "pair-plan.json")
    if confirmation != plan.get("required_confirmation"):
        raise ValueError("PAIR_PUBLICATION_CONFIRMATION_MISMATCH")
    if action not in {"execute", "rollback"}:
        raise ValueError("PAIR_ACTION_INVALID")
    if action == "rollback" and expected_current != "pair-after":
        raise ValueError("PAIR_ROLLBACK_EXPECTED_CURRENT_REQUIRED")
    check_plan(pair_dir, expect="before" if action == "execute" else "after")
    integrator = load_integrator()
    observer = _load_original_observer()
    common = load_common()
    with integrator.shared_api_release_lock(API_PLIST) as lease:
        integrator.assert_api_release_lock(lease, API_PLIST)
        live = common.current_plists(API_PLIST, SCHEDULER_PLIST)
        before_raw = {"api": live["api_raw"], "scheduler": live["scheduler_raw"]}
        if action == "execute":
            if {"api": live["api_sha256"], "scheduler": live["scheduler_sha256"]} != {
                "api": plan["pair_cas"]["api"]["before_sha256"],
                "scheduler": plan["pair_cas"]["scheduler"]["before_sha256"]}:
                raise ValueError("PAIR_LIVE_PREIMAGE_CAS_MISMATCH")
            integrator.verify_api_release_candidate(candidate_root=RELEASE_ROOT,
                active_api_plist_path=API_PLIST, expected_manifest_sha256=MANIFEST_SHA256,
                active_pointer="base", lock_lease=lease, require_shared_lock=True)
            after_raw = {"api": exact_bytes(Path(plan["pair_cas"]["api"]["after_path"]), "STAGED_API"),
                         "scheduler": exact_bytes(Path(plan["pair_cas"]["scheduler"]["after_path"]), "STAGED_SCHEDULER")}
            if {k: sha(v) for k, v in after_raw.items()} != {
                "api": plan["pair_cas"]["api"]["after_sha256"],
                "scheduler": plan["pair_cas"]["scheduler"]["after_sha256"]}:
                raise ValueError("PAIR_STAGED_POSTIMAGE_SHA_MISMATCH")
        else:
            before_raw = {"api": exact_bytes(Path(plan["files"]["api"]["path"]), "BEFORE_API"),
                          "scheduler": exact_bytes(Path(plan["files"]["scheduler"]["path"]), "BEFORE_SCHEDULER")}
            after_raw = {"api": exact_bytes(Path(plan["pair_cas"]["api"]["after_path"]), "AFTER_API"),
                         "scheduler": exact_bytes(Path(plan["pair_cas"]["scheduler"]["after_path"]), "AFTER_SCHEDULER")}
        original_api_loaded, scheduler_loaded = _observe_original_pair(observer)
        operation = {"schema_version": "v4.issue35.phase4.pair_operation.v1",
                     "action": action, "target_trade_date": TARGET_DATE,
                     "plan_sha256": sha(exact_bytes(pair_dir / "pair-plan.json", "PAIR_PLAN")),
                     "before_sha256": {k: sha(v) for k, v in before_raw.items()},
                     "after_sha256": {k: sha(v) for k, v in after_raw.items()},
                     "observer_before": {"api": original_api_loaded, "scheduler": scheduler_loaded},
                     "service_actions": [], "cas_actions": [], "status": "IN_PROGRESS"}
        operation_path = TASK_ROOT / "E/receipts/phase4-issue35-target13/service-observer-fix" / ("pair-" + action + "-operation.json")
        if operation_path.exists() or operation_path.is_symlink():
            raise FileExistsError("PAIR_OPERATION_RECEIPT_EXISTS:" + str(operation_path))
        write_json_exclusive(operation_path, operation)
        primary_error: str | None = None
        stopped = []
        try:
            for label, plist in ((API_LABEL, API_PLIST), (SCHEDULER_LABEL, SCHEDULER_PLIST)):
                integrator.assert_api_release_lock(lease, API_PLIST)
                _launch_action(observer, label, plist, "bootout")
                stopped.append((label, plist))
                _wait_label(observer, label, False)
                operation["service_actions"].append({"label": label, "action": "bootout", "readback": "UNLOADED"})
            if action == "execute":
                writes = []
                writes.append(cas_replace(API_PLIST, after_raw["api"], sha(before_raw["api"]), integrator, lease))
                if sha(exact_bytes(API_PLIST, "API_AFTER_READBACK")) != sha(after_raw["api"]):
                    raise ValueError("API_AFTER_READBACK_BEFORE_SCHEDULER_CAS")
                writes.append(cas_replace(SCHEDULER_PLIST, after_raw["scheduler"], sha(before_raw["scheduler"]), integrator, lease))
                operation["cas_actions"] = writes
                if sha(exact_bytes(API_PLIST, "API_AFTER")) != sha(after_raw["api"]) or sha(exact_bytes(SCHEDULER_PLIST, "SCHEDULER_AFTER")) != sha(after_raw["scheduler"]):
                    raise ValueError("BOTH_AFTER_READBACK_REQUIRED_BEFORE_RELOAD")
                integrator.verify_api_release_candidate(candidate_root=RELEASE_ROOT,
                    active_api_plist_path=API_PLIST, expected_manifest_sha256=MANIFEST_SHA256,
                    active_pointer="candidate", lock_lease=lease, require_shared_lock=True)
            else:
                recovery = guarded_recover(API_PLIST, SCHEDULER_PLIST, before_raw, after_raw, integrator, lease,
                    lambda path, raw, expected: cas_replace(path, raw, expected, integrator, lease))
                operation["cas_actions"] = [recovery]
            # The pair has been verified before either service is bootstrapped.
            for label, plist in ((API_LABEL, API_PLIST), (SCHEDULER_LABEL, SCHEDULER_PLIST)):
                integrator.assert_api_release_lock(lease, API_PLIST)
                _launch_action(observer, label, plist, "bootstrap")
                loaded = _wait_label(observer, label, True)
                operation["service_actions"].append({"label": label, "action": "bootstrap", "readback": loaded})
            if action == "execute":
                observer.LABEL = API_LABEL
                runtime_api = observer._observe_loaded()
                health = observer._verify_openapi(require_manager_route=True)
                operation["runtime_verification"] = {"api_loaded": runtime_api, "openapi": health}
                if runtime_api.get("identity", {}).get("V35_RELEASE_ID") != "issue35-manager-autocontinue-20261012-r4b":
                    raise ValueError("PAIR_RELOADED_API_RELEASE_IDENTITY_MISMATCH")
                operation["status"] = "PUBLISHED_AND_BOTH_LABELS_RELOADED"
            else:
                operation["status"] = "ROLLED_BACK_TO_EXACT_PREIMAGES"
        except Exception as exc:
            primary_error = type(exc).__name__ + ":" + str(exc)
            operation["error"] = primary_error
            # For a failed publication/reload, recover only recognized adapter-owned states.
            if action == "execute":
                try:
                    recovery = guarded_recover(API_PLIST, SCHEDULER_PLIST, before_raw, after_raw, integrator, lease,
                        lambda path, raw, expected: cas_replace(path, raw, expected, integrator, lease))
                    operation["recovery"] = recovery
                    # Any candidate labels still loaded must be stopped before loading originals.
                    for label, plist in ((API_LABEL, API_PLIST), (SCHEDULER_LABEL, SCHEDULER_PLIST)):
                        state = _recovery_service_observation(observer, label)
                        if state.get("state") == "LOADED":
                            _launch_action(observer, label, plist, "bootout")
                            _wait_label(observer, label, False)
                    for label, plist in ((API_LABEL, API_PLIST), (SCHEDULER_LABEL, SCHEDULER_PLIST)):
                        _launch_action(observer, label, plist, "bootstrap")
                        _wait_label(observer, label, True)
                    operation["status"] = "FAILED_CANDIDATE_PAIR_RECOVERED_AND_ORIGINAL_LABELS_RELOADED"
                except Exception as recover_exc:
                    operation["status"] = "RECOVERY_BLOCKED_STOP_NO_UNKNOWN_OVERWRITE"
                    operation["recovery_error"] = type(recover_exc).__name__ + ":" + str(recover_exc)
            else:
                operation["status"] = "ROLLBACK_FAILED_STOP"
            # Preserve operation log even on failure; atomic replacement uses its fixed path only once.
            raise
        finally:
            operation["primary_error"] = primary_error
            temp_receipt = operation_path.with_name(operation_path.name + ".final.tmp")
            raw = json_bytes(operation)
            fd = os.open(temp_receipt, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp_receipt, operation_path)
            fsync_dir(operation_path.parent)
        return operation


def self_test() -> dict[str, Any]:
    """Fault-inject partial CAS and reload failure; every touched file is temp-only."""
    with tempfile.TemporaryDirectory(prefix="issue35-pair-cas-") as temp_text:
        base = Path(temp_text).resolve()
        api = base / "api.plist"
        scheduler = base / "scheduler.plist"
        before = {"api": plistlib.dumps({"Label": "test.api", "Generation": 1}),
                  "scheduler": plistlib.dumps({"Label": "test.scheduler", "Generation": 1})}
        after = {"api": plistlib.dumps({"Label": "test.api", "Generation": 2}),
                 "scheduler": plistlib.dumps({"Label": "test.scheduler", "Generation": 2})}
        api.write_bytes(before["api"]); scheduler.write_bytes(before["scheduler"])
        def replace(path: Path, raw: bytes, expected: str) -> None:
            if path.parent != base:
                raise AssertionError("SELF_TEST_NON_TEMP_PATH")
            if sha(path.read_bytes()) != expected:
                raise ValueError("SELF_TEST_CAS_MISMATCH")
            path.write_bytes(raw)
        # Fault after API pointer CAS: recovery must restore only that exact candidate file.
        replace(api, after["api"], sha(before["api"]))
        state = pair_state(sha(api.read_bytes()), sha(scheduler.read_bytes()),
                           {k: sha(v) for k, v in before.items()}, {k: sha(v) for k, v in after.items()})
        if state != "API_AFTER_SCHEDULER_BEFORE":
            raise AssertionError("SELF_TEST_PARTIAL_FORWARD_STATE_NOT_RECOGNIZED")
        recover1 = guarded_recover(api, scheduler, before, after, None, None, replace)
        if api.read_bytes() != before["api"] or scheduler.read_bytes() != before["scheduler"]:
            raise AssertionError("SELF_TEST_PARTIAL_FORWARD_RECOVERY_FAILED")
        # Simulated reload failure after both candidate pointers read back: restore scheduler then API.
        replace(api, after["api"], sha(before["api"]))
        replace(scheduler, after["scheduler"], sha(before["scheduler"]))
        recover2 = guarded_recover(api, scheduler, before, after, None, None, replace)
        if api.read_bytes() != before["api"] or scheduler.read_bytes() != before["scheduler"]:
            raise AssertionError("SELF_TEST_RELOAD_FAILURE_RECOVERY_FAILED")
        # Unrecognized bytes must stop without touching either side.
        replace(api, after["api"], sha(before["api"]))
        unexpected = plistlib.dumps({"Label": "test.scheduler", "Generation": 999})
        scheduler.write_bytes(unexpected)
        snapshot = (api.read_bytes(), scheduler.read_bytes())
        try:
            guarded_recover(api, scheduler, before, after, None, None, replace)
            raise AssertionError("SELF_TEST_UNEXPECTED_BYTES_DID_NOT_STOP")
        except ValueError as exc:
            if "PAIR_RECOVERY_STOP_UNEXPECTED_BYTES" not in str(exc):
                raise
        if snapshot != (api.read_bytes(), scheduler.read_bytes()):
            raise AssertionError("SELF_TEST_UNEXPECTED_STATE_WAS_OVERWRITTEN")
        return {"status": "PASS_TEMP_PLIST_FAULT_INJECTION", "temp_root": str(base),
                "scenarios": ["API CAS landed then scheduler preimage retained; exact API rollback",
                              "both candidate plists installed then simulated reload failure; scheduler then API rollback",
                              "unexpected scheduler bytes; stop with zero overwrites"],
                "recovery_receipts": [recover1, recover2], "live_paths_touched": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    template_parser = sub.add_parser("template")
    template_parser.add_argument("--observer-receipt", type=Path, required=True)
    template_parser.add_argument("--pair-dir", type=Path, default=DEFAULT_PAIR_DIR)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--pair-dir", type=Path, default=DEFAULT_PAIR_DIR)
    prepare_parser.add_argument("--stage-dir", type=Path, required=True)
    prepare_parser.add_argument("--prep-receipt", type=Path, required=True)
    prepare_parser.add_argument("--canary", type=Path, required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--pair-dir", type=Path, default=DEFAULT_PAIR_DIR)
    check_parser.add_argument("--expect", choices=("before", "after"), default="before")
    run_parser = sub.add_parser("execute", help="main-owned future publication only; NOT used by writer")
    run_parser.add_argument("--pair-dir", type=Path, default=DEFAULT_PAIR_DIR)
    run_parser.add_argument("--confirm", required=True)
    rollback_parser = sub.add_parser("rollback", help="main-owned exact pair rollback only")
    rollback_parser.add_argument("--pair-dir", type=Path, default=DEFAULT_PAIR_DIR)
    rollback_parser.add_argument("--confirm", required=True)
    rollback_parser.add_argument("--expected-current", choices=("pair-after",), required=True)
    obs_parser = sub.add_parser("observe", help="read-only original API/scheduler observer snapshot")
    obs_parser.add_argument("--out", type=Path, required=True)
    sub.add_parser("self-test", help="temp-plist-only partial-CAS and recovery fault injection")
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            result = template(args.pair_dir, args.observer_receipt)
        elif args.command == "prepare":
            result = prepare_pair(args.pair_dir, args.stage_dir, args.prep_receipt, args.canary)
        elif args.command == "check":
            result = check_plan(args.pair_dir, expect=args.expect)
        elif args.command in {"execute", "rollback"}:
            result = execute_or_rollback(args.pair_dir, args.command, args.confirm,
                                         getattr(args, "expected_current", None))
        elif args.command == "observe":
            result = observe_live(args.out)
        else:
            result = self_test()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__ + ":" + str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
