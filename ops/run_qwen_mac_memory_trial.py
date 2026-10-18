#!/usr/bin/env python3
"""Phase-B-gated runner for the frozen, serial Qwen residency canary.

No live inference, settings mutation, model load, or authenticated API call is
available during phase A. Phase-A commands are local checks and fake transport.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import ctypes.util
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
import sys
from typing import Any, Mapping


ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_QWEN_MAC_MEMORY_20261019_R1")
WRITER_ROOT = ROOT / "writer"
EVIDENCE_ROOT = ROOT / "evidence"
SAMPLES_ROOT = ROOT / "candidate" / "samples"
MANIFEST_PATH = ROOT / "candidate" / "sample-manifest.json"
SCOPE_PATH = ROOT / "ROOT_SCOPE.json"
MODEL_ID = "qwen3_8_flash_next"
TARGET_FIELD = "moe_expert_offload_resident_fraction"
TARGET_SETTING = f"models.{MODEL_ID}.{TARGET_FIELD}"
OMLX_BASE_URL = "http://127.0.0.1:8802"
ADMIN_MODELS_PATH = "/admin/api/models"
ADMIN_ACTIVITY_PATH = "/admin/api/activity"
ADMIN_SETTINGS_PATH = f"/admin/api/models/{MODEL_ID}/settings"
ADMIN_LOAD_PATH = f"/admin/api/models/{MODEL_ID}/load"
PHASE_A_SCOPE_SHA256 = "595751b4a4e36d9665336f443d855559014c68d5736b78ce82b44d7bb999e5a7"
PHASE_A_SCOPE_NAME = "A_UNFINISHED_AND_ACTIVITY_CORRECTION_ONLY"
MANIFEST_SHA256 = "828e26a84d5464b59d48dc91fbf12f92fc4f79b3c6f6b88a48c4cbe666ce0e88"
BASELINE_MODEL_SETTINGS_SHA256 = "7a98bb5d2b6687b808d72b8c7bb385a23c714e9753a067fab81407c4e9245b99"
BASELINE_RUNTIME_SETTINGS_SHA256 = "e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99"
BASELINE_NON_TARGET_SETTINGS_SHA256 = "150a8588ee3dec5b65c6f1e3a9b2b173bf2856de6f165327de8b91694c995116"
PHASE_B_AUTH_SCHEMA = "v4.qwen_mac_memory_tuning.phase_b_authorization.v1"
SAMPLE_ORDER = ("baseline_short_success", "baseline_table_success", "memory_rejection")
MEMORY_REJECTION_ORDER = ("memory_rejection",)
ALLOWED_FRACTIONS = (1.0, 0.9375, 0.875)
MIN_AVAILABLE_BYTES = 8_589_934_592
MAX_SEQUENCE_SWAP_GROWTH_BYTES = 536_870_912
MIN_GUARD_HEADROOM_BYTES = 2_147_483_648
MAX_WARM_LATENCY_RATIO = 1.25
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FROZEN_TRIAL_CRITERIA = {
    "workload": "three existing source/request-hash frozen stock-article samples, serial, 1.0 then 0.9375; 0.875 only after measured need and root signal",
    "memory_required": {
        "all_requests_finish_without_memory_rejection": True,
        "minimum_system_available_memory_bytes": MIN_AVAILABLE_BYTES,
        "maximum_swap_used_growth_bytes_per_three_sample_sequence": MAX_SEQUENCE_SWAP_GROWTH_BYTES,
    },
    "guard_telemetry": {
        "minimum_headroom_bytes_if_authoritatively_measurable": MIN_GUARD_HEADROOM_BYTES,
        "unavailable": "record CANNOT_CONFIRM for guard-specific headroom; do not invent it from a client RSS or static weight estimate",
    },
    "latency_required": {
        "maximum_warm_same_input_wall_ratio_to_successful_1_0": MAX_WARM_LATENCY_RATIO,
        "cold_load_measured_separately": True,
        "failed_baseline_is_not_a_latency_denominator": True,
    },
    "quality_required": "Independent source-fact comparison, no new material unsupported claims or material entity/date/amount/unit/table-attribution regressions; historical outputs are references only",
    "ssd_counter": "process-specific only when obtainable; UNKNOWN otherwise, with measured wall cost still required",
    "selection": "highest tested residency meeting required canary criteria; small canary is not a long-term stability, training-capacity, or financial-model acceptance claim",
}


class TrialError(RuntimeError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _assert_under_root(path: Path) -> None:
    resolved_root = ROOT.resolve(strict=True)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise TrialError("WRITE_OR_READ_PATH_OUTSIDE_R_ALLOWLIST") from None


def _read_regular(path: Path) -> bytes:
    _assert_under_root(path)
    if path.is_symlink() or not path.is_file():
        raise TrialError("FROZEN_ARTIFACT_MISSING_OR_UNSAFE")
    return path.read_bytes()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular(path))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TrialError("FROZEN_JSON_INVALID") from None
    if not isinstance(value, dict):
        raise TrialError("FROZEN_JSON_INVALID")
    return value


def _write_exclusive(path: Path, raw: bytes) -> None:
    _assert_under_root(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise TrialError("WRITE_PATH_SYMLINK")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise TrialError("EVIDENCE_ALREADY_EXISTS") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _write_json_exclusive(path: Path, value: Any) -> None:
    _write_exclusive(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")


def _append_jsonl(path: Path, value: Any) -> None:
    _assert_under_root(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise TrialError("WRITE_PATH_SYMLINK")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        raw = _canonical_json(value) + b"\n"
        os.write(fd, raw)
    finally:
        os.close(fd)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        return []
    rows = []
    for line in _read_regular(path).splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _current_scope(*, require_phase_a_hash: bool = False) -> tuple[dict[str, Any], str]:
    raw = _read_regular(SCOPE_PATH)
    digest = _sha256(raw)
    scope = _read_json(SCOPE_PATH)
    if scope.get("trial_criteria") != FROZEN_TRIAL_CRITERIA:
        raise TrialError("FROZEN_TRIAL_CRITERIA_CHANGED")
    if scope.get("candidate_order") != list(ALLOWED_FRACTIONS):
        raise TrialError("FROZEN_CANDIDATE_ORDER_CHANGED")
    if require_phase_a_hash and (digest != PHASE_A_SCOPE_SHA256 or scope.get("phase") != PHASE_A_SCOPE_NAME):
        raise TrialError("PHASE_A_SCOPE_BINDING_MISMATCH")
    return scope, digest


def _ensure_r_writer_helpers_on_path() -> None:
    writer_path = str(WRITER_ROOT)
    if writer_path not in sys.path:
        sys.path.insert(0, writer_path)


def _candidate_index() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if _sha256(_read_regular(MANIFEST_PATH)) != MANIFEST_SHA256:
        raise TrialError("CANDIDATE_MANIFEST_SHA_MISMATCH")
    try:
        _ensure_r_writer_helpers_on_path()
        from preparation_driver import _validate_candidate_manifest

        return _validate_candidate_manifest()
    except Exception as exc:
        code = getattr(exc, "code", None) or str(exc) or type(exc).__name__
        raise TrialError(f"CANDIDATE_INPUT_VALIDATION_FAILED:{str(code)[:80]}") from None


def _load_local_model() -> Any:
    repo_root = Path("/Users/lexi/Desktop/学习/v4_app")
    repo_text = str(repo_root)
    if repo_text not in os.sys.path:
        os.sys.path.insert(0, repo_text)
    try:
        import infrastructure.local_document_model as local_model
    except Exception as exc:
        raise TrialError(f"LOCAL_MODEL_HELPER_UNAVAILABLE:{type(exc).__name__}") from None
    local_model.require_runtime_python()
    local_model.PDF_EVIDENCE_ROOT = EVIDENCE_ROOT
    return local_model


def _binding_for(local_model: Any, schema: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, float, str]]:
    try:
        binding = local_model.build_request_material(schema)
        _ensure_r_writer_helpers_on_path()
        from preparation_driver import _settings_fingerprint

        fingerprint = _settings_fingerprint(Path(binding["model_settings_path"]))
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        raise TrialError(f"CURRENT_BINDING_UNAVAILABLE:{str(code)[:80]}") from None
    if binding.get("runtime_settings_sha256") != BASELINE_RUNTIME_SETTINGS_SHA256:
        raise TrialError("RUNTIME_SETTINGS_SHA_MISMATCH")
    if fingerprint[2] != BASELINE_NON_TARGET_SETTINGS_SHA256:
        raise TrialError("NON_TARGET_MODEL_SETTINGS_CHANGED")
    if fingerprint[1] not in ALLOWED_FRACTIONS:
        raise TrialError("RESIDENT_FRACTION_OUTSIDE_FROZEN_CANDIDATES")
    if fingerprint[1] == 1.0 and fingerprint[0] != BASELINE_MODEL_SETTINGS_SHA256:
        raise TrialError("BASELINE_MODEL_SETTINGS_SHA_MISMATCH")
    return binding, fingerprint


def _phase_a_check() -> dict[str, Any]:
    scope, scope_sha = _current_scope(require_phase_a_hash=True)
    manifest, indexed = _candidate_index()
    del scope
    local_model = _load_local_model()
    schema = indexed[SAMPLE_ORDER[0]]["request_input"]["structured_outputs"]["json"]
    binding, fingerprint = _binding_for(local_model, schema)
    if fingerprint[1] != 1.0:
        raise TrialError("PHASE_A_REQUIRES_SAVED_BASELINE_1_0")
    return {
        "status": "PASS_LIVE_RECIPE_PREFLIGHT",
        "phase": PHASE_A_SCOPE_NAME,
        "root_scope_sha256": scope_sha,
        "sample_manifest_sha256": MANIFEST_SHA256,
        "sample_ids_in_run_order": list(SAMPLE_ORDER),
        "model_id": MODEL_ID,
        "resident_fraction": fingerprint[1],
        "model_settings_sha256": fingerprint[0],
        "non_target_settings_sha256": fingerprint[2],
        "runtime_settings_sha256": binding["runtime_settings_sha256"],
        "evidence_root": str(EVIDENCE_ROOT),
        "live_inference": "NOT_RUN",
        "settings_write": "NOT_RUN",
        "service_action": "NOT_RUN",
        "credential_or_admin_probe": "NOT_RUN",
        "candidate_count": len(manifest["samples"]),
    }


def _extract_model_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = payload.get("models")
    row = None
    if isinstance(rows, list):
        row = next((item for item in rows if isinstance(item, dict) and item.get("id") == MODEL_ID), None)
    elif isinstance(rows, dict):
        candidate = rows.get(MODEL_ID)
        row = candidate if isinstance(candidate, dict) else None
    if not isinstance(row, dict):
        raise TrialError("ADMIN_MODEL_READBACK_MISSING")
    if type(row.get("loaded")) is not bool or type(row.get("is_loading")) is not bool:
        raise TrialError("ADMIN_MODEL_LOAD_STATE_UNAVAILABLE")
    settings = row.get("settings")
    fraction = settings.get(TARGET_FIELD) if isinstance(settings, dict) else row.get(TARGET_FIELD)
    if type(fraction) not in (int, float):
        raise TrialError("ADMIN_TARGET_FRACTION_UNAVAILABLE")
    return {
        "model_id": MODEL_ID,
        "loaded": row.get("loaded") is True,
        "is_loading": row.get("is_loading") is True,
        "pinned": row.get("pinned") is True,
        "saved_fraction": float(fraction),
    }


def _read_admin_models(client: Any) -> dict[str, Any]:
    response = client.get(ADMIN_MODELS_PATH, timeout=10.0)
    if response.status_code != 200:
        raise TrialError(f"ADMIN_MODELS_HTTP_{response.status_code}")
    try:
        payload = response.json()
    except Exception:
        raise TrialError("ADMIN_MODELS_RESPONSE_INVALID") from None
    if not isinstance(payload, dict):
        raise TrialError("ADMIN_MODELS_RESPONSE_INVALID")
    return _extract_model_row(payload)


def _read_admin_activity(client: Any) -> dict[str, Any]:
    response = client.get(ADMIN_ACTIVITY_PATH, timeout=10.0)
    if response.status_code != 200:
        raise TrialError(f"ADMIN_ACTIVITY_HTTP_{response.status_code}")
    try:
        payload = response.json()
    except Exception:
        raise TrialError("ADMIN_ACTIVITY_RESPONSE_INVALID") from None
    active = payload.get("active") if isinstance(payload, dict) else None
    waiting = payload.get("waiting") if isinstance(payload, dict) else None
    active_models = payload.get("active_models") if isinstance(payload, dict) else None
    if isinstance(active_models, dict):
        # Match the existing AdminSession.activity() wrapper's authoritative
        # nested counters; an invalid nested value stays unavailable.
        active = active_models.get("total_active_requests")
        waiting = active_models.get("total_waiting_requests")
    elif isinstance(payload, dict) and not any(key in payload for key in ("active", "waiting", "active_models")):
        # Preserve the old driver's accepted top-level total_* shape when no
        # established AdminSession.activity() fields are present.
        active = payload.get("total_active_requests")
        waiting = payload.get("total_waiting_requests")
    guard = payload.get("memory_pressure") if isinstance(payload, dict) else None
    metric: dict[str, Any] = {
        "active_requests": active if type(active) is int and active >= 0 else None,
        "waiting_requests": waiting if type(waiting) is int and waiting >= 0 else None,
        "activity_counts_status": (
            "MEASURED"
            if type(active) is int and active >= 0 and type(waiting) is int and waiting >= 0
            else "CANNOT_CONFIRM"
        ),
        "guard_status": "CANNOT_CONFIRM",
        "guard_enabled": None,
        "guard_current_bytes": None,
        "guard_hard_bytes": None,
        "guard_headroom_bytes": None,
    }
    if isinstance(guard, dict) and guard.get("enabled") is True:
        current = guard.get("current_bytes")
        hard = guard.get("hard_bytes")
        if type(current) is int and type(hard) is int and current >= 0 and hard > 0:
            metric.update({
                "guard_status": "MEASURED",
                "guard_enabled": True,
                "guard_current_bytes": current,
                "guard_hard_bytes": hard,
                "guard_headroom_bytes": hard - current,
            })
        else:
            metric["guard_enabled"] = True
    elif isinstance(guard, dict) and guard.get("enabled") is False:
        metric["guard_enabled"] = False
    return metric


class _RUsageInfoV4(ctypes.Structure):
    """Layout of the locally installed macOS SDK's private RUSAGE_INFO_V4."""

    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
        ("ri_cpu_time_qos_default", ctypes.c_uint64),
        ("ri_cpu_time_qos_maintenance", ctypes.c_uint64),
        ("ri_cpu_time_qos_background", ctypes.c_uint64),
        ("ri_cpu_time_qos_utility", ctypes.c_uint64),
        ("ri_cpu_time_qos_legacy", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_initiated", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_interactive", ctypes.c_uint64),
        ("ri_billed_system_time", ctypes.c_uint64),
        ("ri_serviced_system_time", ctypes.c_uint64),
        ("ri_logical_writes", ctypes.c_uint64),
        ("ri_lifetime_max_phys_footprint", ctypes.c_uint64),
        ("ri_instructions", ctypes.c_uint64),
        ("ri_cycles", ctypes.c_uint64),
        ("ri_billed_energy", ctypes.c_uint64),
        ("ri_serviced_energy", ctypes.c_uint64),
        ("ri_interval_max_phys_footprint", ctypes.c_uint64),
        ("ri_runnable_time", ctypes.c_uint64),
    ]


_RUSAGE_INFO_V4_BYTES = 296


def _read_proc_pid_rusage(pid: int) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise TrialError("PROC_PID_RUSAGE_REQUIRES_MACOS")
    if ctypes.sizeof(_RUsageInfoV4) != _RUSAGE_INFO_V4_BYTES:
        raise TrialError("RUSAGE_INFO_V4_LAYOUT_SIZE_MISMATCH")
    library_path = ctypes.util.find_library("proc")
    if not library_path:
        raise TrialError("LIBPROC_UNAVAILABLE")
    try:
        library = ctypes.CDLL(library_path, use_errno=True)
        function = library.proc_pid_rusage
    except Exception:
        raise TrialError("PROC_PID_RUSAGE_UNAVAILABLE") from None
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    function.restype = ctypes.c_int
    usage = _RUsageInfoV4()
    result = function(pid, 4, ctypes.byref(usage))
    if result != 0:
        error_number = ctypes.get_errno()
        raise TrialError(f"PROC_PID_RUSAGE_FAILED:{error_number}")
    return {
        "process_uuid": bytes(usage.ri_uuid).hex(),
        "process_resident_size_bytes": int(usage.ri_resident_size),
        "process_phys_footprint_bytes": int(usage.ri_phys_footprint),
        "process_diskio_bytesread_cumulative": int(usage.ri_diskio_bytesread),
    }


def _resolve_omlx_process() -> dict[str, Any]:
    """Bind telemetry to one same-UID omlx-server listening on the trial port."""
    if sys.platform != "darwin":
        return {"status": "CANNOT_CONFIRM", "reason": "NOT_MACOS"}
    try:
        import psutil

        current_uid = os.getuid()
        candidates = []
        for process in psutil.process_iter(["pid", "name", "uids", "create_time"]):
            try:
                info = process.info
                uids = info.get("uids")
                if (
                    info.get("name") == "omlx-server"
                    and uids is not None
                    and uids.real == current_uid
                ):
                    candidates.append({
                        "pid": int(info["pid"]),
                        "uid": int(uids.real),
                        "name": str(info["name"]),
                        "create_time": float(info["create_time"]),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError, ValueError):
                continue
        if len(candidates) != 1:
            return {"status": "CANNOT_CONFIRM", "reason": "SAME_UID_OMLX_PROCESS_NOT_UNIQUE"}
        identity = candidates[0]
        listeners = psutil.net_connections(kind="tcp")
        if not any(
            conn.pid == identity["pid"]
            and conn.status == psutil.CONN_LISTEN
            and getattr(conn.laddr, "port", None) == 8802
            for conn in listeners
        ):
            return {"status": "CANNOT_CONFIRM", "reason": "OMLX_PID_NOT_VERIFIED_AS_TRIAL_PORT_LISTENER"}
        usage = _read_proc_pid_rusage(identity["pid"])
        identity.update(usage)
        identity["status"] = "MEASURED"
        identity["rusage_flavor"] = "RUSAGE_INFO_V4"
        identity["process_identity_basis"] = "same UID, comm name, create time, and TCP listener on 127.0.0.1:8802; no command-line arguments read"
        return identity
    except Exception as exc:
        return {"status": "CANNOT_CONFIRM", "reason": type(exc).__name__}


def _sample_omlx_process(identity: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(identity, Mapping) or identity.get("status") != "MEASURED":
        return {"process_usage_status": "CANNOT_CONFIRM", "process_usage_reason": "PID_IDENTITY_UNAVAILABLE"}
    try:
        import psutil

        process = psutil.Process(int(identity["pid"]))
        if (
            process.name() != identity["name"]
            or process.uids().real != identity["uid"]
            or abs(process.create_time() - identity["create_time"]) > 0.01
        ):
            return {"process_usage_status": "CANNOT_CONFIRM", "process_usage_reason": "PID_IDENTITY_CHANGED"}
        usage = _read_proc_pid_rusage(int(identity["pid"]))
        if usage["process_uuid"] != identity["process_uuid"]:
            return {"process_usage_status": "CANNOT_CONFIRM", "process_usage_reason": "PID_REUSED_OR_PROCESS_CHANGED"}
        return {
            "process_usage_status": "MEASURED",
            "omlx_pid": int(identity["pid"]),
            "omlx_uid": int(identity["uid"]),
            "omlx_process_name": identity["name"],
            "process_uuid": usage["process_uuid"],
            "process_rusage_flavor": "RUSAGE_INFO_V4",
            "process_resident_size_bytes": usage["process_resident_size_bytes"],
            "process_phys_footprint_bytes": usage["process_phys_footprint_bytes"],
            "process_diskio_bytesread_cumulative": usage["process_diskio_bytesread_cumulative"],
            "process_diskio_counter_semantics": "cumulative process accounting; not attributed to this canary, a file, mmap page-ins, or physical SSD NAND",
        }
    except Exception as exc:
        return {"process_usage_status": "CANNOT_CONFIRM", "process_usage_reason": type(exc).__name__}


@contextmanager
def _exclusive_trial_lock() -> Any:
    lock_path = EVIDENCE_ROOT / "live-trials" / ".qwen-memory-trial.lock"
    _assert_under_root(lock_path)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if lock_path.is_symlink():
        raise TrialError("TRIAL_LOCK_PATH_UNSAFE")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TrialError("ANOTHER_TRIAL_DRIVER_IS_ACTIVE") from None
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class AdminAccess:
    """Use the existing in-memory helper login for Phase-B admin actions."""

    def __init__(self, *, client: Any, helper_session: Any | None, auth_source: str):
        self.client = client
        self.helper_session = helper_session
        self.auth_source = auth_source

    @classmethod
    def connect_after_phase_b(cls, local_model: Any) -> "AdminAccess":
        try:
            modules = local_model.load_shared_modules()
            api_key = modules.runner.load_local_api_key()
            helper_session = modules.canary.AdminSession(api_key)
            helper_session.login()
            # Do not print, persist, hash, or return api_key or the session cookie.
            _extract_model_row(helper_session._client.get(ADMIN_MODELS_PATH).json())
            return cls(
                client=helper_session._client,
                helper_session=helper_session,
                auth_source="EXISTING_ADMINSESSION_LOCAL_KEY_HELPER",
            )
        except Exception as exc:
            raise TrialError(f"ADMIN_HELPER_SESSION_UNAVAILABLE:{type(exc).__name__}") from None

    def close(self) -> None:
        if self.helper_session is not None:
            self.helper_session.close()
        else:
            self.client.close()


def _phase_b_auth(
    scope: Mapping[str, Any],
    *,
    action: str,
    fraction: float,
    from_fraction: float | None = None,
    sample_order: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if scope.get("phase") != "B_EXECUTE_AUTHORIZED":
        raise TrialError("ROOT_PHASE_B_SIGNAL_REQUIRED")
    auth = scope.get("phase_b_authorization")
    if not isinstance(auth, dict) or auth.get("schema") != PHASE_B_AUTH_SCHEMA or auth.get("status") != "AUTHORIZED":
        raise TrialError("ROOT_PHASE_B_SIGNAL_MISSING_OR_INVALID")
    if auth.get("phase_a_scope_sha256") != PHASE_A_SCOPE_SHA256:
        raise TrialError("PHASE_B_DOES_NOT_BIND_PHASE_A_SCOPE")
    reviewer_sha = auth.get("reviewer_receipt_sha256")
    if not isinstance(reviewer_sha, str) or not SHA256_RE.fullmatch(reviewer_sha):
        raise TrialError("INDEPENDENT_REVIEW_RECEIPT_NOT_BOUND")
    if not isinstance(auth.get("authorization_id"), str) or not auth["authorization_id"].strip():
        raise TrialError("PHASE_B_AUTHORIZATION_ID_MISSING")
    if action not in auth.get("authorized_actions", []):
        raise TrialError("PHASE_B_ACTION_NOT_AUTHORIZED")
    if fraction not in auth.get("authorized_fraction_values", []):
        raise TrialError("PHASE_B_FRACTION_NOT_AUTHORIZED")
    if action == "run_serial_sequence":
        expected_order = SAMPLE_ORDER if sample_order is None else sample_order
        if expected_order not in (SAMPLE_ORDER, MEMORY_REJECTION_ORDER):
            raise TrialError("PHASE_B_SAMPLE_ORDER_INVALID")
        if auth.get("authorized_sample_order") != list(expected_order):
            raise TrialError("PHASE_B_SAMPLE_ORDER_NOT_AUTHORIZED")
    if from_fraction is not None:
        transitions = auth.get("authorized_fraction_transitions", [])
        if not any(
            isinstance(row, dict)
            and row.get("from_fraction") == from_fraction
            and row.get("to_fraction") == fraction
            for row in transitions
        ):
            raise TrialError("PHASE_B_SETTING_TRANSITION_NOT_AUTHORIZED")
    stage = auth.get("stage")
    expected_stage = {1.0: "B1_BASELINE", 0.9375: "B2_0_9375", 0.875: "B3_0_875"}.get(fraction)
    if stage != expected_stage:
        # Rollback still belongs to the currently authorized candidate stage.
        if not (action == "set_target_fraction" and from_fraction is not None and fraction == 1.0 and stage in {"B2_0_9375", "B3_0_875"}):
            raise TrialError("PHASE_B_STAGE_FRACTION_MISMATCH")
    if fraction == 0.9375 or (fraction == 1.0 and from_fraction == 0.9375):
        _verify_predecessor_receipt(auth, key="baseline_sequence_receipt", expected_fraction=1.0, require_need=False)
    if fraction == 0.875 or (fraction == 1.0 and from_fraction == 0.875):
        _verify_predecessor_receipt(auth, key="previous_candidate_sequence_receipt", expected_fraction=0.9375, require_need=True)
        _verify_predecessor_receipt(auth, key="baseline_sequence_receipt", expected_fraction=1.0, require_need=False)
    return auth


def _verify_predecessor_receipt(auth: Mapping[str, Any], *, key: str, expected_fraction: float, require_need: bool) -> dict[str, Any]:
    item = auth.get(key)
    if not isinstance(item, dict):
        raise TrialError(f"PHASE_B_PREDECESSOR_RECEIPT_REQUIRED:{key}")
    relative = item.get("relative_path")
    expected_sha = item.get("sha256")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise TrialError("PHASE_B_PREDECESSOR_PATH_INVALID")
    path = ROOT / relative
    raw = _read_regular(path)
    if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha) or _sha256(raw) != expected_sha:
        raise TrialError("PHASE_B_PREDECESSOR_RECEIPT_SHA_MISMATCH")
    receipt = _read_json(path)
    if receipt.get("profile_fraction") != expected_fraction or receipt.get("sample_manifest_sha256") != MANIFEST_SHA256:
        raise TrialError("PHASE_B_PREDECESSOR_RECEIPT_SCOPE_MISMATCH")
    if require_need and receipt.get("acceptance", {}).get("need_for_lower_fraction") is not True:
        raise TrialError("NO_MEASURED_NEED_FOR_0_875")
    return receipt


def _set_fraction(fraction: float, expected_current: float) -> dict[str, Any]:
    scope, scope_sha = _current_scope()
    auth = _phase_b_auth(scope, action="set_target_fraction", fraction=fraction, from_fraction=expected_current)
    manifest, indexed = _candidate_index()
    del manifest
    local_model = _load_local_model()
    schema = indexed[SAMPLE_ORDER[0]]["request_input"]["structured_outputs"]["json"]
    binding, fingerprint = _binding_for(local_model, schema)
    if fingerprint[1] != expected_current:
        raise TrialError("EXPECTED_CURRENT_FRACTION_MISMATCH")
    with _exclusive_trial_lock():
        admin = AdminAccess.connect_after_phase_b(local_model)
        try:
            before_model = _read_admin_models(admin.client)
            if before_model["saved_fraction"] != expected_current:
                raise TrialError("ADMIN_AND_LOCAL_FRACTION_DISAGREE")
            activity = _read_admin_activity(admin.client)
            if activity["active_requests"] != 0 or activity["waiting_requests"] != 0:
                raise TrialError("MODEL_NOT_IDLE_FOR_SETTINGS_UPDATE")
            response = admin.client.put(ADMIN_SETTINGS_PATH, json={TARGET_FIELD: fraction}, timeout=20.0)
            if response.status_code != 200:
                raise TrialError(f"ADMIN_SETTINGS_HTTP_{response.status_code}")
            try:
                result = response.json()
            except Exception:
                raise TrialError("ADMIN_SETTINGS_RESPONSE_INVALID") from None
            if not isinstance(result, dict) or result.get("success") is not True:
                raise TrialError("ADMIN_SETTINGS_UPDATE_NOT_CONFIRMED")
            # The request body above contains exactly the single authorized target field.
            after_binding, after_fingerprint = _binding_for(local_model, schema)
            if after_fingerprint[1] != fraction or after_fingerprint[2] != BASELINE_NON_TARGET_SETTINGS_SHA256:
                raise TrialError("ONE_FIELD_SETTINGS_READBACK_MISMATCH")
            after_model = _read_admin_models(admin.client)
            if after_model["saved_fraction"] != fraction:
                raise TrialError("ADMIN_SETTINGS_READBACK_MISMATCH")
            response_settings = result.get("settings")
            route_fraction = response_settings.get(TARGET_FIELD) if isinstance(response_settings, dict) else None
            requires_reload_value = result.get("requires_reload")
            if type(requires_reload_value) is not bool:
                raise TrialError("SETTINGS_RELOAD_REQUIREMENT_UNAVAILABLE")
            requires_reload = requires_reload_value
            auto_reloaded = result.get("auto_reloaded") is True
            auto_unloaded = result.get("auto_unloaded") is True
            reload_deferred = result.get("reload_deferred") is True
            if requires_reload and type(result.get("reload_deferred")) is not bool:
                raise TrialError("ENGINE_RELOAD_DEFERRED_STATE_UNAVAILABLE")
            reload_action = _reload_action(
                requires_reload=requires_reload,
                auto_reloaded=auto_reloaded,
                reload_deferred=reload_deferred,
                model_state=after_model,
            )
            if reload_action == "AUTHORIZED_MANUAL_LOAD_REQUIRED":
                if "load_target_model" not in auth.get("authorized_actions", []):
                    raise TrialError("TARGET_MODEL_LOAD_NOT_AUTHORIZED_AFTER_SETTINGS_UPDATE")
                load_start = time.monotonic()
                load_response = admin.client.post(ADMIN_LOAD_PATH, timeout=30.0)
                if load_response.status_code not in (200, 202):
                    raise TrialError(f"ADMIN_MODEL_LOAD_HTTP_{load_response.status_code}")
                after_model = _wait_for_model_ready(admin.client, timeout_seconds=1200)
                reload_wall = time.monotonic() - load_start
                reload_action = "MANUAL_LOAD_VERIFIED_READY"
            else:
                reload_wall = None
            if requires_reload and (not after_model["loaded"] or after_model["is_loading"]):
                raise TrialError("ENGINE_RELOAD_STATE_NOT_READY")
            receipt = {
                "schema": "v4.qwen_mac_memory_tuning.settings_transition_receipt.v1",
                "status": "SETTINGS_TRANSITION_CLOSED_ACTIVE_FRACTION_CANNOT_CONFIRM",
                "phase": scope.get("phase"),
                "phase_b_authorization_id": auth.get("authorization_id"),
                "root_scope_sha256": scope_sha,
                "reviewer_receipt_sha256": auth.get("reviewer_receipt_sha256"),
                "model_id": MODEL_ID,
                "target_setting": TARGET_SETTING,
                "from_fraction": expected_current,
                "to_fraction": fraction,
                "before_model_settings_sha256": fingerprint[0],
                "after_model_settings_sha256": after_fingerprint[0],
                "non_target_settings_sha256": after_fingerprint[2],
                "runtime_settings_sha256": after_binding["runtime_settings_sha256"],
                "admin_route": ADMIN_SETTINGS_PATH,
                "admin_auth_source": admin.auth_source,
                "request_json_keys": [TARGET_FIELD],
                "response_fraction": route_fraction,
                "requires_reload": requires_reload,
                "auto_unloaded": auto_unloaded,
                "auto_reloaded": auto_reloaded,
                "reload_deferred": reload_deferred,
                "reload_action": reload_action,
                "model_readback": after_model,
                "manual_load_wall_seconds": reload_wall,
                "active_server_resident_fraction": "CANNOT_CONFIRM",
                "api_key_readback_endpoint_called": False,
                "credentials_or_cookie_saved": False,
                "created_at_utc": _now_utc(),
            }
            transition_id = uuid.uuid4().hex
            path = EVIDENCE_ROOT / "settings-transitions" / f"{transition_id}.json"
            _write_json_exclusive(path, receipt)
            return {"status": receipt["status"], "receipt_path": str(path), "receipt_sha256": _sha256(_read_regular(path))}
        finally:
            admin.close()


def _wait_for_model_ready(client: Any, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        row = _read_admin_models(client)
        if row["loaded"] and not row["is_loading"]:
            return row
        time.sleep(2.0)
    raise TrialError("TARGET_MODEL_LOAD_TIMEOUT")


def _reload_action(
    *,
    requires_reload: bool,
    auto_reloaded: bool,
    reload_deferred: bool,
    model_state: Mapping[str, Any],
) -> str:
    """Fail closed unless a load-time setting change has a closed reload path."""
    if not requires_reload:
        return "RELOAD_NOT_REQUIRED_BY_ROUTE"
    if reload_deferred:
        raise TrialError("ENGINE_RELOAD_DEFERRED")
    loaded = model_state.get("loaded") is True
    loading = model_state.get("is_loading") is True
    if auto_reloaded:
        if not loaded or loading:
            raise TrialError("AUTO_RELOAD_NOT_CONFIRMED_READY")
        return "AUTO_RELOAD_VERIFIED_READY"
    if loaded or loading:
        raise TrialError("ENGINE_RELOAD_NOT_CONFIRMED_OLD_ENGINE_POSSIBLE")
    return "AUTHORIZED_MANUAL_LOAD_REQUIRED"


def _write_candidate_outputs(attempt_dir: Path, final_text: str, schema: Mapping[str, Any], *, validate: bool) -> tuple[str, str | None]:
    raw_path = attempt_dir / "model-response.raw.json"
    _write_exclusive(raw_path, final_text.encode("utf-8"))
    validated_sha = None
    if validate:
        local_model = _load_local_model()
        modules = local_model.load_shared_modules()
        try:
            output = json.loads(final_text)
            modules.runner._validate_json_schema(output, schema)
        except Exception:
            raise TrialError("LIVE_RESPONSE_SCHEMA_REJECTED") from None
        output_path = attempt_dir / "validated-output.json"
        raw_output = json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        _write_exclusive(output_path, raw_output)
        validated_sha = _sha256(raw_output)
    return _sha256(_read_regular(raw_path)), validated_sha


def _loopback_transport(expected_input: Mapping[str, Any], *, delegate: Any, observer: dict[str, Any]) -> Any:
    import httpx
    from urllib.parse import urlsplit

    class GuardedLoopbackTransport(httpx.BaseTransport):
        def handle_request(self, request: Any) -> Any:
            parsed = urlsplit(str(request.url))
            if (
                request.method != "POST"
                or parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port != 8802
                or parsed.path != "/v1/chat/completions"
            ):
                raise TrialError("LIVE_TRANSPORT_OUTSIDE_LOOPBACK_ALLOWLIST")
            if not request.headers.get("authorization", "").startswith("Bearer "):
                raise TrialError("LOCAL_MODEL_AUTH_HEADER_MISSING")
            try:
                body = json.loads(request.content)
            except Exception:
                raise TrialError("LIVE_REQUEST_BODY_INVALID") from None
            if body != expected_input:
                raise TrialError("LIVE_REQUEST_BODY_NOT_BYTE_EQUIVALENT_TO_FROZEN_INPUT")
            observer["request_count"] = observer.get("request_count", 0) + 1
            observer["request_body_sha256"] = _sha256(request.content)
            return delegate.handle_request(request)

        def close(self) -> None:
            delegate.close()

    return GuardedLoopbackTransport()


def _fake_sequence(sample_order: tuple[str, ...] = SAMPLE_ORDER) -> dict[str, Any]:
    if sample_order not in (SAMPLE_ORDER, MEMORY_REJECTION_ORDER):
        raise TrialError("FAKE_SAMPLE_ORDER_INVALID")
    scope, scope_sha = _current_scope(require_phase_a_hash=True)
    del scope
    manifest, indexed = _candidate_index()
    local_model = _load_local_model()
    schema = indexed[sample_order[0]]["request_input"]["structured_outputs"]["json"]
    baseline_binding, fingerprint = _binding_for(local_model, schema)
    if fingerprint[1] != 1.0:
        raise TrialError("FAKE_SEQUENCE_REQUIRES_BASELINE_PROFILE")
    import httpx

    run_id = uuid.uuid4().hex
    run_dir = EVIDENCE_ROOT / "fake-live-trials" / f"1_0-{run_id}"
    _assert_under_root(run_dir)
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    sample_results = []
    fake_objects = 0
    for sample_id in sample_order:
        entry = indexed[sample_id]
        request_input = entry["request_input"]
        schema = request_input["structured_outputs"]["json"]
        key = hashlib.sha256(
            f"fake:{run_id}:{sample_id}:{entry['manifest']['source_pdf_sha256']}".encode("utf-8")
        ).hexdigest()
        attempt_dir = EVIDENCE_ROOT / "streams" / key / "attempt-0001"
        fake_object = {"analysis_markdown": "FAKE_TRANSPORT_ONLY"}
        fake_text = json.dumps(fake_object, ensure_ascii=False, separators=(",", ":"))
        event = {
            "id": "chatcmpl-phase-a-live-driver-fake",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": fake_text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        sse = b"data: " + json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n\ndata: [DONE]\n\n"
        observed: dict[str, Any] = {"request_count": 0, "request_body_sha256": None}

        def mock_handler(request: Any, *, body: bytes = sse) -> Any:
            if json.loads(request.content) != request_input:
                raise TrialError("FAKE_FROZEN_REQUEST_MISMATCH")
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

        transport = _loopback_transport(request_input, delegate=httpx.MockTransport(mock_handler), observer=observed)
        job = local_model.load_shared_modules().queue.QueueJob(
            idempotency_key=key,
            queue_id=key,
            model_id=MODEL_ID,
            identity={"sample_id": sample_id, "source_pdf_sha256": entry["manifest"]["source_pdf_sha256"]},
            payload={},
            attempt=1,
        )
        binding, current = _binding_for(local_model, schema)
        if current != fingerprint:
            raise TrialError("SETTINGS_CHANGED_DURING_FAKE_SEQUENCE")
        started = time.monotonic()
        final_text = local_model.request_document_analysis(
            job=job,
            messages=request_input["messages"],
            schema=schema,
            expected_binding=binding,
            api_key="phase-a-live-driver-fake-only",
            http_transport=transport,
        )
        elapsed = time.monotonic() - started
        if observed["request_count"] != 1 or final_text != fake_text:
            raise TrialError("FAKE_SEQUENCE_TRANSPORT_RESULT_MISMATCH")
        raw_sha, _ = _write_candidate_outputs(attempt_dir, final_text, schema, validate=False)
        files = {}
        for name in ("round-01.request-input.json", "round-01.raw.sse", "resource-samples.jsonl", "stream-receipt.json", "model-response.raw.json"):
            path = attempt_dir / name
            if path.is_file():
                files[name] = {"sha256": _sha256(_read_regular(path)), "bytes": path.stat().st_size}
        sample_results.append({
            "sample_id": sample_id,
            "status": "FAKE_TRANSPORT_PASS",
            "frozen_request_input_sha256": entry["manifest"]["request_input_sha256"],
            "observed_request_body_sha256": observed["request_body_sha256"],
            "idempotency_key": key,
            "wall_seconds": round(elapsed, 6),
            "fake_response_sha256": raw_sha,
            "evidence_path": str(attempt_dir),
            "files": files,
        })
        fake_objects += 1
    receipt = {
        "schema": "v4.qwen_mac_memory_tuning.live_driver_fake_sequence.v1",
        "status": "PASS_FAKE_SERIAL_REQUESTS",
        "phase": PHASE_A_SCOPE_NAME,
        "run_id": run_id,
        "root_scope_sha256": scope_sha,
        "sample_manifest_sha256": _sha256(_read_regular(MANIFEST_PATH)),
        "profile_fraction": fingerprint[1],
        "model_settings_sha256": fingerprint[0],
        "runtime_settings_sha256": baseline_binding["runtime_settings_sha256"],
        "sample_order": list(sample_order),
        "sample_count": fake_objects,
        "sample_results": sample_results,
        "real_model_calls": 0,
        "network_requests": 0,
        "settings_write": "NOT_RUN",
        "service_action": "NOT_RUN",
        "criteria_evaluation": "NOT_APPLICABLE_FAKE_ONLY",
        "created_at_utc": _now_utc(),
    }
    receipt_path = run_dir / "sequence-receipt.json"
    _write_json_exclusive(receipt_path, receipt)
    return {"status": receipt["status"], "receipt_path": str(receipt_path), "receipt_sha256": _sha256(_read_regular(receipt_path)), "samples": fake_objects, "network_requests": 0}


class LiveTelemetrySampler:
    def __init__(
        self,
        *,
        client: Any,
        output_path: Path,
        process_identity: Mapping[str, Any] | None,
        interval_seconds: float = 1.0,
    ):
        self.client = client
        self.output_path = output_path
        self.process_identity = process_identity
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.errors: list[str] = []
        self._context_lock = threading.Lock()
        self._sample_lock = threading.Lock()
        self._activity_context: tuple[str | None, str] = (None, "sequence_start")
        self.activity_failure_reason: str | None = None
        self.activity_cannot_reason: str | None = None

    def set_activity_context(self, sample_id: str | None, phase: str) -> None:
        with self._context_lock:
            self._activity_context = (sample_id, phase)

    def _record_activity_integrity(self, row: Mapping[str, Any]) -> None:
        phase = row.get("activity_phase")
        active = row.get("active_requests")
        waiting = row.get("waiting_requests")
        if row.get("activity_counts_status") != "MEASURED":
            self.activity_cannot_reason = self.activity_cannot_reason or "ACTIVITY_COUNTS_UNAVAILABLE"
            return
        if phase in {"sequence_start", "between_samples", "sequence_end"}:
            if active != 0 or waiting != 0:
                self.activity_failure_reason = self.activity_failure_reason or "NONZERO_ACTIVITY_OUTSIDE_REQUEST_WINDOW"
        elif phase == "request_in_flight":
            if type(active) is not int or active < 0 or type(waiting) is not int or waiting < 0:
                self.activity_cannot_reason = self.activity_cannot_reason or "ACTIVITY_COUNTS_INVALID"
            elif active + waiting > 1:
                self.activity_failure_reason = self.activity_failure_reason or "MULTIPLE_REQUESTS_DURING_SERIAL_CANARY"

    def sample_once(
        self,
        *,
        context: tuple[str | None, str] | None = None,
    ) -> dict[str, Any]:
        with self._sample_lock:
            if context is not None:
                self.set_activity_context(*context)
            with self._context_lock:
                sample_id, phase = self._activity_context
            row: dict[str, Any] = {
                "at_utc": _now_utc(),
                "activity_sample_id": sample_id,
                "activity_phase": phase,
                "activity_sampling_interval_seconds": self.interval_seconds,
            }
            try:
                import psutil

                memory = psutil.virtual_memory()
                swap = psutil.swap_memory()
                row.update({
                    "system_status": "SAMPLED",
                    "system_available_bytes": int(memory.available),
                    "swap_used_bytes": int(swap.used),
                    "process_rss_bytes": int(psutil.Process(os.getpid()).memory_info().rss),
                })
            except Exception as exc:
                row.update({"system_status": "CANNOT_CONFIRM", "system_error_type": type(exc).__name__})
            try:
                guard = _read_admin_activity(self.client)
                row.update(guard)
            except Exception as exc:
                self.errors.append(type(exc).__name__)
                row.update({
                    "activity_counts_status": "CANNOT_CONFIRM",
                    "guard_status": "CANNOT_CONFIRM",
                    "guard_error_type": type(exc).__name__,
                })
            self._record_activity_integrity(row)
            row.update(_sample_omlx_process(self.process_identity))
            _append_jsonl(self.output_path, row)
            return row

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self.sample_once()
            except Exception as exc:
                self.errors.append(type(exc).__name__)

    def start(self) -> dict[str, Any]:
        initial = self.sample_once(context=(None, "sequence_start"))
        self.thread = threading.Thread(target=self._run, name="qwen-trial-telemetry", daemon=True)
        self.thread.start()
        return initial

    def stop(self) -> None:
        self.set_activity_context(None, "sequence_end")
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=12.0)
            if self.thread.is_alive():
                self.errors.append("SAMPLER_THREAD_DID_NOT_STOP")
                return
        self.sample_once(context=(None, "sequence_end"))


def _activity_integrity_summary(
    rows: list[dict[str, Any]],
    sample_ids: list[str],
    *,
    require_sequence_end: bool = True,
) -> dict[str, Any]:
    boundary_rows = [
        row for row in rows
        if row.get("activity_phase") in {"sequence_start", "between_samples", "sequence_end"}
    ]
    in_flight_by_sample: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("activity_phase") == "request_in_flight" and isinstance(row.get("activity_sample_id"), str):
            in_flight_by_sample.setdefault(row["activity_sample_id"], []).append(row)
    fail_reasons: list[str] = []
    cannot_reasons: list[str] = []
    if not any(row.get("activity_phase") == "sequence_start" for row in rows):
        cannot_reasons.append("SEQUENCE_START_ACTIVITY_SAMPLE_MISSING")
    if require_sequence_end and not any(row.get("activity_phase") == "sequence_end" for row in rows):
        cannot_reasons.append("SEQUENCE_END_ACTIVITY_SAMPLE_MISSING")
    for row in boundary_rows:
        if row.get("activity_counts_status") != "MEASURED":
            cannot_reasons.append("BOUNDARY_ACTIVITY_COUNTS_UNAVAILABLE")
        elif row.get("active_requests") != 0 or row.get("waiting_requests") != 0:
            fail_reasons.append("NONZERO_ACTIVITY_OUTSIDE_REQUEST_WINDOW")
    observed_unassigned_active_samples: list[str] = []
    observed_unassigned_single_request_samples: list[str] = []
    for sample_id in sample_ids:
        inflight_rows = in_flight_by_sample.get(sample_id, [])
        if not inflight_rows:
            cannot_reasons.append(f"IN_FLIGHT_ACTIVITY_SAMPLE_MISSING:{sample_id}")
            continue
        for row in inflight_rows:
            if row.get("activity_counts_status") != "MEASURED":
                cannot_reasons.append(f"IN_FLIGHT_ACTIVITY_COUNTS_UNAVAILABLE:{sample_id}")
                continue
            active = row.get("active_requests")
            waiting = row.get("waiting_requests")
            if type(active) is not int or active < 0 or type(waiting) is not int or waiting < 0:
                cannot_reasons.append(f"IN_FLIGHT_ACTIVITY_COUNTS_INVALID:{sample_id}")
                continue
            if active + waiting > 1:
                fail_reasons.append(f"MULTIPLE_REQUESTS_DURING_SERIAL_CANARY:{sample_id}")
            elif active + waiting == 1:
                observed_unassigned_single_request_samples.append(sample_id)
            if active == 1:
                observed_unassigned_active_samples.append(sample_id)
    status = "FAIL" if fail_reasons else "CANNOT_CONFIRM" if cannot_reasons else "PASS_OBSERVED_SERIAL_COUNTS"
    return {
        "serial_activity_integrity_status": status,
        "serial_activity_fail_reasons": sorted(set(fail_reasons)),
        "serial_activity_cannot_confirm_reasons": sorted(set(cannot_reasons)),
        "in_flight_activity_samples_by_request": {key: len(value) for key, value in sorted(in_flight_by_sample.items())},
        "in_flight_active_one_observed_samples_unassigned": sorted(set(observed_unassigned_active_samples)),
        "in_flight_single_request_observed_samples_unassigned": sorted(set(observed_unassigned_single_request_samples)),
        "request_ownership": "CANNOT_CONFIRM_AGGREGATE_COUNTS_DO_NOT_IDENTIFY_REQUEST",
        "activity_counts_semantics": "aggregate process-wide active/waiting counts; no request ownership or exclusive resource attribution claim",
        "activity_sampling_interval_seconds": 1.0,
        "activity_sampling_limitations": "short-lived external activity between one-second polls may be missed",
    }


def _resource_summary(
    sample_results: list[dict[str, Any]],
    run_dir: Path,
    *,
    require_sequence_end: bool = False,
) -> dict[str, Any]:
    system_samples = _read_jsonl(run_dir / "environment-samples.jsonl")
    activity = _activity_integrity_summary(
        system_samples,
        [r["sample_id"] for r in sample_results if isinstance(r.get("sample_id"), str)],
        require_sequence_end=require_sequence_end,
    )
    available_values = [r["system_available_bytes"] for r in system_samples if r.get("system_status") == "SAMPLED" and type(r.get("system_available_bytes")) is int]
    swap_values = [r["swap_used_bytes"] for r in system_samples if r.get("system_status") == "SAMPLED" and type(r.get("swap_used_bytes")) is int]
    metric_rows_complete = bool(system_samples) and all(r.get("system_status") == "SAMPLED" for r in system_samples)
    for result in sample_results:
        for row in _read_jsonl(Path(result["evidence_path"]) / "resource-samples.jsonl"):
            if row.get("status") == "SAMPLED":
                available_values.append(row["system_available_bytes"])
                swap_values.append(row["swap_used_bytes"])
            else:
                metric_rows_complete = False
    start_swap = next((r.get("swap_used_bytes") for r in system_samples if r.get("system_status") == "SAMPLED" and type(r.get("swap_used_bytes")) is int), None)
    minimum_available = min(available_values) if available_values else None
    maximum_swap = max(swap_values) if swap_values else None
    swap_growth = max(0, maximum_swap - start_swap) if type(start_swap) is int and type(maximum_swap) is int else None
    guard_rows = [r for r in system_samples if r.get("guard_status") == "MEASURED" and type(r.get("guard_headroom_bytes")) is int]
    guard_complete = bool(system_samples) and all(r.get("guard_status") == "MEASURED" for r in system_samples)
    min_guard = min((r["guard_headroom_bytes"] for r in guard_rows), default=None)
    process_rows = [r for r in system_samples if "process_usage_status" in r]
    measured_process_rows = [r for r in process_rows if r.get("process_usage_status") == "MEASURED"]
    process_complete = bool(process_rows) and len(measured_process_rows) == len(process_rows)
    process_uuids = {r.get("process_uuid") for r in measured_process_rows}
    process_pids = {r.get("omlx_pid") for r in measured_process_rows}
    process_identity_stable = process_complete and len(process_uuids) == 1 and len(process_pids) == 1
    footprint_values = [r["process_phys_footprint_bytes"] for r in measured_process_rows if type(r.get("process_phys_footprint_bytes")) is int]
    resident_values = [r["process_resident_size_bytes"] for r in measured_process_rows if type(r.get("process_resident_size_bytes")) is int]
    read_values = [r["process_diskio_bytesread_cumulative"] for r in measured_process_rows if type(r.get("process_diskio_bytesread_cumulative")) is int]
    process_read_delta = None
    if process_identity_stable and len(read_values) == len(measured_process_rows) and len(read_values) >= 2 and read_values[-1] >= read_values[0]:
        process_read_delta = read_values[-1] - read_values[0]
    return {
        "system_sample_count": len(system_samples),
        "system_metrics_status": "MEASURED" if metric_rows_complete and minimum_available is not None and swap_growth is not None else "CANNOT_CONFIRM",
        "minimum_system_available_bytes": minimum_available,
        "minimum_system_available_threshold_bytes": MIN_AVAILABLE_BYTES,
        "minimum_system_available_status": (
            "PASS" if metric_rows_complete and minimum_available is not None and minimum_available >= MIN_AVAILABLE_BYTES
            else "FAIL" if minimum_available is not None and minimum_available < MIN_AVAILABLE_BYTES
            else "CANNOT_CONFIRM"
        ),
        "sequence_start_swap_used_bytes": start_swap,
        "sequence_max_swap_used_bytes": maximum_swap,
        "sequence_swap_used_growth_bytes": swap_growth,
        "sequence_swap_growth_threshold_bytes": MAX_SEQUENCE_SWAP_GROWTH_BYTES,
        "sequence_swap_growth_status": (
            "PASS" if metric_rows_complete and swap_growth is not None and swap_growth <= MAX_SEQUENCE_SWAP_GROWTH_BYTES
            else "FAIL" if swap_growth is not None and swap_growth > MAX_SEQUENCE_SWAP_GROWTH_BYTES
            else "CANNOT_CONFIRM"
        ),
        "guard_metric_sample_count": len(guard_rows),
        "guard_headroom_status": "MEASURED" if guard_complete and min_guard is not None else "CANNOT_CONFIRM",
        "minimum_guard_headroom_bytes": min_guard,
        "minimum_guard_headroom_threshold_bytes": MIN_GUARD_HEADROOM_BYTES,
        "guard_headroom_gate_status": (
            "PASS" if guard_complete and min_guard is not None and min_guard >= MIN_GUARD_HEADROOM_BYTES
            else "FAIL" if min_guard is not None and min_guard < MIN_GUARD_HEADROOM_BYTES
            else "CANNOT_CONFIRM"
        ),
        "omlx_process_usage_status": "MEASURED" if process_identity_stable else "CANNOT_CONFIRM",
        "omlx_process_pid": next(iter(process_pids)) if len(process_pids) == 1 else None,
        "omlx_process_sample_count": len(measured_process_rows),
        "omlx_sampled_peak_phys_footprint_bytes": max(footprint_values) if footprint_values else None,
        "omlx_sampled_peak_resident_size_bytes": max(resident_values) if resident_values else None,
        "process_memory_peak_semantics": "maximum across one-second RUSAGE_INFO_V4 samples; not a kernel lifetime or interval maximum",
        **activity,
        "process_diskio_bytesread_before_bytes": read_values[0] if process_identity_stable and read_values else None,
        "process_diskio_bytesread_after_bytes": read_values[-1] if process_identity_stable and read_values else None,
        "process_diskio_bytesread_delta_bytes": process_read_delta,
        "process_diskio_delta_status": "MEASURED" if process_read_delta is not None else "CANNOT_CONFIRM",
        "process_diskio_counter_semantics": "cumulative process accounting; not attributed to this canary, a file, mmap page-ins, or physical SSD NAND",
        "process_specific_ssd_bytes": "UNKNOWN",
        "process_specific_ssd_reason": "RUSAGE_INFO_V4 process read-byte delta is captured when available, but physical SSD NAND and per-file/mmap attribution are not established; retain wall time and leave physical SSD bytes UNKNOWN.",
    }


def _latency_comparison(profile: float, sample_results: list[dict[str, Any]], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if profile == 1.0:
        return {"status": "REFERENCE_BASELINE", "threshold_ratio": MAX_WARM_LATENCY_RATIO, "ratios": []}
    if baseline is None:
        return {"status": "CANNOT_CONFIRM_BASELINE_RECEIPT_MISSING", "threshold_ratio": MAX_WARM_LATENCY_RATIO, "ratios": []}
    base_rows = {r.get("sample_id"): r for r in baseline.get("sample_results", []) if isinstance(r, dict)}
    ratios = []
    for row in sample_results:
        previous = base_rows.get(row.get("sample_id"))
        if not previous or previous.get("status") != "SUCCEEDED" or type(previous.get("wall_seconds")) not in (int, float) or previous.get("wall_seconds", 0) <= 0:
            ratios.append({"sample_id": row.get("sample_id"), "status": "EXCLUDED_FAILED_OR_UNAVAILABLE_BASELINE_DENOMINATOR", "ratio": None})
            continue
        if row.get("status") != "SUCCEEDED" or type(row.get("wall_seconds")) not in (int, float):
            ratios.append({"sample_id": row.get("sample_id"), "status": "CANDIDATE_NOT_SUCCESSFUL", "ratio": None})
            continue
        ratio = row["wall_seconds"] / previous["wall_seconds"]
        ratios.append({"sample_id": row["sample_id"], "status": "MEASURED", "baseline_wall_seconds": previous["wall_seconds"], "candidate_wall_seconds": row["wall_seconds"], "ratio": round(ratio, 6)})
    measured = [r["ratio"] for r in ratios if r.get("status") == "MEASURED"]
    status = "PASS" if measured and all(value <= MAX_WARM_LATENCY_RATIO for value in measured) else "FAIL" if measured and any(value > MAX_WARM_LATENCY_RATIO for value in measured) else "CANNOT_CONFIRM"
    return {"status": status, "threshold_ratio": MAX_WARM_LATENCY_RATIO, "ratios": ratios, "cold_load_measured_separately": True}


def _idle_activity_status(row: Mapping[str, Any]) -> str:
    if row.get("activity_counts_status") != "MEASURED":
        return "CANNOT_CONFIRM"
    return "PASS" if row.get("active_requests") == 0 and row.get("waiting_requests") == 0 else "FAIL"


def _run_sequence(profile: float, sample_order: tuple[str, ...] = SAMPLE_ORDER) -> dict[str, Any]:
    if sample_order not in (SAMPLE_ORDER, MEMORY_REJECTION_ORDER):
        raise TrialError("PHASE_B_SAMPLE_ORDER_INVALID")
    scope, scope_sha = _current_scope()
    auth = _phase_b_auth(scope, action="run_serial_sequence", fraction=profile, sample_order=sample_order)
    manifest, indexed = _candidate_index()
    local_model = _load_local_model()
    schema = indexed[sample_order[0]]["request_input"]["structured_outputs"]["json"]
    binding, fingerprint = _binding_for(local_model, schema)
    if fingerprint[1] != profile:
        raise TrialError("SAVED_PROFILE_DOES_NOT_MATCH_AUTHORIZED_RUN_PROFILE")
    baseline_receipt = None
    if profile < 1.0:
        baseline_receipt = _verify_predecessor_receipt(auth, key="baseline_sequence_receipt", expected_fraction=1.0, require_need=False)
    run_id = uuid.uuid4().hex
    profile_tag = str(profile).replace(".", "_")
    run_dir = EVIDENCE_ROOT / "live-trials" / f"profile-{profile_tag}-{run_id}"
    _assert_under_root(run_dir)
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    with _exclusive_trial_lock():
        admin = AdminAccess.connect_after_phase_b(local_model)
        sampler = None
        try:
            model_state = _read_admin_models(admin.client)
            if model_state["saved_fraction"] != profile:
                raise TrialError("ADMIN_AND_LOCAL_FRACTION_DISAGREE")
            activity = _read_admin_activity(admin.client)
            if activity["active_requests"] != 0 or activity["waiting_requests"] != 0:
                raise TrialError("MODEL_NOT_IDLE_BEFORE_SEQUENCE")
            cold_load_wall = None
            if not model_state["loaded"] or model_state["is_loading"]:
                if "load_target_model" not in auth.get("authorized_actions", []):
                    raise TrialError("TARGET_MODEL_LOAD_NOT_AUTHORIZED")
                load_started = time.monotonic()
                load_response = admin.client.post(ADMIN_LOAD_PATH, timeout=30.0)
                if load_response.status_code not in (200, 202):
                    raise TrialError(f"ADMIN_MODEL_LOAD_HTTP_{load_response.status_code}")
                model_state = _wait_for_model_ready(admin.client, timeout_seconds=1200)
                cold_load_wall = time.monotonic() - load_started
            _write = run_dir / "environment-samples.jsonl"
            process_identity = _resolve_omlx_process()
            sampler = LiveTelemetrySampler(client=admin.client, output_path=_write, process_identity=process_identity)
            start_activity = sampler.start()
            sample_results: list[dict[str, Any]] = []
            stopped_reason = None
            start_idle_status = _idle_activity_status(start_activity)
            if start_idle_status == "FAIL":
                stopped_reason = "MODEL_NOT_IDLE_AT_SEQUENCE_START"
            elif start_idle_status == "CANNOT_CONFIRM":
                stopped_reason = "SEQUENCE_START_ACTIVITY_UNAVAILABLE"
            for sample_id in sample_order:
                if stopped_reason is not None:
                    break
                before_activity = sampler.sample_once(context=(sample_id, "between_samples"))
                before_idle_status = _idle_activity_status(before_activity)
                if before_idle_status == "FAIL":
                    stopped_reason = "MODEL_NOT_IDLE_BETWEEN_SERIAL_SAMPLES"
                    break
                if before_idle_status == "CANNOT_CONFIRM":
                    stopped_reason = "ACTIVITY_COUNTS_UNAVAILABLE_BETWEEN_SAMPLES"
                    break
                entry = indexed[sample_id]
                request_input = entry["request_input"]
                sample_schema = request_input["structured_outputs"]["json"]
                _, current_fingerprint = _binding_for(local_model, sample_schema)
                if current_fingerprint != fingerprint:
                    stopped_reason = "SETTINGS_BINDING_CHANGED_DURING_SEQUENCE"
                    break
                idempotency_key = hashlib.sha256(
                    _canonical_json({
                        "run_id": run_id,
                        "sample_id": sample_id,
                        "source_pdf_sha256": entry["manifest"]["source_pdf_sha256"],
                        "request_input_sha256": entry["manifest"]["request_input_sha256"],
                        "nonce": uuid.uuid4().hex,
                    })
                ).hexdigest()
                attempt_dir = EVIDENCE_ROOT / "streams" / idempotency_key / "attempt-0001"
                job = local_model.load_shared_modules().queue.QueueJob(
                    idempotency_key=idempotency_key,
                    queue_id=idempotency_key,
                    model_id=MODEL_ID,
                    identity={
                        "sample_id": sample_id,
                        "document_id": entry["manifest"]["document_id"],
                        "source_pdf_sha256": entry["manifest"]["source_pdf_sha256"],
                        "request_input_sha256": entry["manifest"]["request_input_sha256"],
                    },
                    payload={},
                    attempt=1,
                )
                binding, current_fingerprint = _binding_for(local_model, sample_schema)
                observer: dict[str, Any] = {"request_count": 0, "request_body_sha256": None}
                import httpx

                transport = _loopback_transport(request_input, delegate=httpx.HTTPTransport(retries=0), observer=observer)
                sampler.set_activity_context(sample_id, "request_in_flight")
                started = time.monotonic()
                try:
                    final_text = local_model.request_document_analysis(
                        job=job,
                        messages=request_input["messages"],
                        schema=sample_schema,
                        expected_binding=binding,
                        http_transport=transport,
                    )
                    wall_seconds = time.monotonic() - started
                    raw_sha, validated_sha = _write_candidate_outputs(attempt_dir, final_text, sample_schema, validate=True)
                    sample_status = "SUCCEEDED"
                    safe_error = None
                except Exception as exc:
                    wall_seconds = time.monotonic() - started
                    raw_sha = None
                    validated_sha = None
                    code = getattr(exc, "code", None) or type(exc).__name__
                    safe_error = str(code)[:96]
                    sample_status = "FAILED"
                sampler.set_activity_context(sample_id, "between_samples")
                stream_receipt_path = attempt_dir / "stream-receipt.json"
                stream_receipt = _read_json(stream_receipt_path) if stream_receipt_path.is_file() and not stream_receipt_path.is_symlink() else {}
                raw_sse_path = attempt_dir / "round-01.raw.sse"
                raw_sse = _read_regular(raw_sse_path) if raw_sse_path.is_file() and not raw_sse_path.is_symlink() else b""
                if b"PREFILL_MEMORY_EXCEEDED" in raw_sse.upper() or "PREFILL_MEMORY_EXCEEDED" in str(stream_receipt.get("failure_code", "")).upper():
                    sample_status = "MEMORY_REJECTED"
                    safe_error = "PREFILL_MEMORY_EXCEEDED"
                if observer.get("request_count") != 1 and sample_status == "SUCCEEDED":
                    sample_status = "FAILED"
                    safe_error = "REQUEST_TRANSPORT_COUNT_MISMATCH"
                files = {}
                for name in (
                    "round-01.request-input.json",
                    "round-01.raw.sse",
                    "resource-samples.jsonl",
                    "stream-receipt.json",
                    "model-response.raw.json",
                    "validated-output.json",
                ):
                    path = attempt_dir / name
                    if path.is_file() and not path.is_symlink():
                        files[name] = {"sha256": _sha256(_read_regular(path)), "bytes": path.stat().st_size}
                sample_result = {
                    "sample_id": sample_id,
                    "status": sample_status,
                    "failure_code": safe_error,
                    "historical_status": entry["manifest"].get("historical_status"),
                    "source_pdf_sha256": entry["manifest"]["source_pdf_sha256"],
                    "frozen_request_input_sha256": entry["manifest"]["request_input_sha256"],
                    "observed_request_body_sha256": observer.get("request_body_sha256"),
                    "idempotency_key": idempotency_key,
                    "wall_seconds": round(wall_seconds, 6),
                    "stream_receipt_status": stream_receipt.get("status", "CANNOT_CONFIRM"),
                    "stream_failure_code": stream_receipt.get("failure_code"),
                    "model_response_sha256": raw_sha,
                    "validated_output_sha256": validated_sha,
                    "evidence_path": str(attempt_dir),
                    "files": files,
                }
                sample_results.append(sample_result)
                environment_now = sampler.sample_once(context=(sample_id, "between_samples"))
                after_idle_status = _idle_activity_status(environment_now)
                if after_idle_status == "FAIL":
                    stopped_reason = "MODEL_NOT_IDLE_AFTER_SERIAL_SAMPLE"
                elif after_idle_status == "CANNOT_CONFIRM":
                    stopped_reason = "ACTIVITY_COUNTS_UNAVAILABLE_AFTER_SAMPLE"
                summary_now = _resource_summary(sample_results, run_dir)
                if summary_now["serial_activity_integrity_status"] == "FAIL":
                    stopped_reason = "SERIAL_ACTIVITY_INTEGRITY_FAIL"
                elif summary_now["serial_activity_integrity_status"] == "CANNOT_CONFIRM":
                    stopped_reason = "SERIAL_ACTIVITY_COVERAGE_UNCONFIRMED"
                if sampler.activity_failure_reason is not None:
                    stopped_reason = "SERIAL_ACTIVITY_INTEGRITY_FAIL"
                if stopped_reason is not None:
                    break
                if sample_status == "MEMORY_REJECTED":
                    stopped_reason = "PREFILL_MEMORY_EXCEEDED"
                    break
                if sample_status != "SUCCEEDED":
                    stopped_reason = "REQUEST_OR_OUTPUT_FAILURE"
                    break
                if summary_now["minimum_system_available_status"] == "FAIL":
                    stopped_reason = "SYSTEM_AVAILABLE_BELOW_8_GIB"
                    break
                if summary_now["sequence_swap_growth_status"] == "FAIL":
                    stopped_reason = "SEQUENCE_SWAP_GROWTH_OVER_512_MIB"
                    break
                if environment_now.get("guard_status") == "MEASURED" and environment_now.get("guard_headroom_bytes", MIN_GUARD_HEADROOM_BYTES) < MIN_GUARD_HEADROOM_BYTES:
                    stopped_reason = "GUARD_HEADROOM_BELOW_2_GIB"
                    break
            if sampler is not None:
                sampler.stop()
            summary = _resource_summary(sample_results, run_dir, require_sequence_end=True)
            all_finish = len(sample_results) == len(sample_order) and all(r["status"] == "SUCCEEDED" for r in sample_results)
            requests_status = "PASS" if all_finish else "FAIL" if any(r["status"] in {"FAILED", "MEMORY_REJECTED"} for r in sample_results) else "CANNOT_CONFIRM"
            latency = _latency_comparison(profile, sample_results, baseline_receipt)
            acceptance = {
                "all_requests_finish_without_memory_rejection": requests_status,
                "system_available": summary["minimum_system_available_status"],
                "swap_growth": summary["sequence_swap_growth_status"],
                "guard_headroom": summary["guard_headroom_gate_status"],
                "serial_activity_integrity": summary["serial_activity_integrity_status"],
                "warm_latency": latency["status"],
                "semantic_quality": "REVIEW_PENDING",
                "process_specific_ssd_bytes": "UNKNOWN",
                "need_for_lower_fraction": any(
                    value == "FAIL" for value in (
                        requests_status,
                        summary["minimum_system_available_status"],
                        summary["sequence_swap_growth_status"],
                        summary["guard_headroom_gate_status"],
                        latency["status"],
                    )
                ),
                "overall": "CANNOT_CONFIRM_SEMANTIC_REVIEW_PENDING",
            }
            if any(value == "FAIL" for key, value in acceptance.items() if key not in {"semantic_quality", "process_specific_ssd_bytes", "need_for_lower_fraction", "overall"}):
                acceptance["overall"] = "FAIL"
            elif any(value == "CANNOT_CONFIRM" for key, value in acceptance.items() if key not in {"semantic_quality", "process_specific_ssd_bytes", "need_for_lower_fraction", "overall"}):
                acceptance["overall"] = "CANNOT_CONFIRM_REQUIRED_TELEMETRY_OR_BASELINE"
            status = "SEQUENCE_COMPLETE" if all_finish and stopped_reason is None else "SEQUENCE_STOPPED"
            receipt = {
                "schema": "v4.qwen_mac_memory_tuning.live_sequence_receipt.v1",
                "status": status,
                "phase": scope.get("phase"),
                "phase_b_authorization_id": auth.get("authorization_id"),
                "reviewer_receipt_sha256": auth.get("reviewer_receipt_sha256"),
                "root_scope_sha256": scope_sha,
                "sample_manifest_sha256": _sha256(_read_regular(MANIFEST_PATH)),
                "run_id": run_id,
                "model_id": MODEL_ID,
                "profile_fraction": profile,
                "target_setting": TARGET_SETTING,
                "model_settings_sha256": fingerprint[0],
                "non_target_settings_sha256": fingerprint[2],
                "runtime_settings_sha256": binding["runtime_settings_sha256"],
                "sample_order": list(sample_order),
                "admin_models_route": ADMIN_MODELS_PATH,
                "admin_activity_route": ADMIN_ACTIVITY_PATH,
                "admin_auth_source": admin.auth_source,
                "model_state_before_sequence": model_state,
                "cold_load_wall_seconds_separate": cold_load_wall,
                "samples_attempted": len(sample_results),
                "samples_required": len(sample_order),
                "stopped_reason": stopped_reason,
                "sample_results": sample_results,
                "telemetry": summary,
                "latency_comparison": latency,
                "acceptance": acceptance,
                "raw_model_outputs_are_source_review_pending": True,
                "active_server_resident_fraction": "CANNOT_CONFIRM",
                "process_specific_ssd_bytes": "UNKNOWN",
                "credentials_or_cookies_saved": False,
                "settings_write_during_sequence": "NOT_RUN",
                "created_at_utc": _now_utc(),
            }
            receipt_path = run_dir / "sequence-receipt.json"
            _write_json_exclusive(receipt_path, receipt)
            return {"status": status, "receipt_path": str(receipt_path), "receipt_sha256": _sha256(_read_regular(receipt_path)), "samples_attempted": len(sample_results), "stopped_reason": stopped_reason, "acceptance": acceptance}
        finally:
            if sampler is not None:
                sampler.stop_event.set()
                if sampler.thread is not None and sampler.thread.is_alive():
                    sampler.thread.join(timeout=3.0)
            admin.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="offline Phase-A binding and frozen-input check")
    mode.add_argument("--fake-sequence", action="store_true", help="run all frozen requests through MockTransport only")
    mode.add_argument("--set-fraction", type=float, choices=ALLOWED_FRACTIONS, help="Phase-B-only one-field settings transition")
    mode.add_argument("--run-sequence", type=float, choices=ALLOWED_FRACTIONS, help="Phase-B-only serial real inference sequence")
    mode.add_argument("--run-memory-rejection", action="store_true", help="Phase-B-only single remaining frozen memory-rejection request")
    parser.add_argument("--expect-current", type=float, choices=ALLOWED_FRACTIONS, help="required current fraction for --set-fraction")
    args = parser.parse_args()
    if args.set_fraction is not None and args.expect_current is None:
        parser.error("--set-fraction requires --expect-current")
    if args.expect_current is not None and args.set_fraction is None:
        parser.error("--expect-current is only valid with --set-fraction")
    try:
        if args.check:
            result = _phase_a_check()
        elif args.fake_sequence:
            result = _fake_sequence()
        elif args.set_fraction is not None:
            result = _set_fraction(args.set_fraction, args.expect_current)
        elif args.run_memory_rejection:
            result = _run_sequence(1.0, sample_order=MEMORY_REJECTION_ORDER)
        else:
            scope, _ = _current_scope()
            _phase_b_auth(scope, action="run_serial_sequence", fraction=args.run_sequence)
            result = _run_sequence(args.run_sequence)
    except TrialError as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "code": str(exc)}, sort_keys=True))
        return 2
    except Exception as exc:
        # Error payloads and request headers may contain article text or secrets.
        print(json.dumps({"status": "FAIL_CLOSED", "code": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
