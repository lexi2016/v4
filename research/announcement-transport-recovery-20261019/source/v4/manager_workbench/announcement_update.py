"""Explicit-click capture and local Flash job orchestration."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import fcntl
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from .announcement_candidate import CandidateEvidenceError, read_pinned_candidates
from .announcement_membership import capture_recovery_manifest
from .contracts import HK, JobState, Phase, RunContext, digest, validate_date
from .jobs import JobConflict, StepFailure


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RUNNER_PYTHON = Path("/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python")
RUNNER_SCRIPT = Path(__file__).resolve().parents[2] / "ops/run_manager_flash_announcements.py"
PROGRESS_REF = "progress.json"
RESULT_REF = "result.json"
CACHED_PRODUCT_RECOVERY_SOURCE_JOB_ID = "e20cf0d93ea843a885b090173b6eab55"
CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256 = "d3eae78873057330f85b1e75d0f0b5ca7e35ba9b5aca807e251ae5487657e53b"
CACHED_PRODUCT_RECOVERY_TARGET_DATE = "20261016"
CACHED_PRODUCT_RECOVERY_CUTOFF = "2026-10-17T23:00:00+08:00"
CACHED_PRODUCT_RECOVERY_FAILURE_CODE = "OWNED_FILE_TOO_LARGE"
CACHED_PRODUCT_RECOVERY_FAILURE_STEP = "CAPTURE_ANNOUNCEMENTS"
CACHED_PRODUCT_RECOVERY_OPERATION = "ANNOUNCEMENT_FLASH_CACHED_PRODUCT_RECOVERY"
CACHED_PRODUCT_RECOVERY_SCHEMA = "v4.manager_workbench.announcement_flash_cached_product_recovery.v1"
FROZEN_RESUME_OPERATION = "ANNOUNCEMENT_FLASH_RESUME"
FROZEN_RESUME_SCHEMA = "v4.manager_workbench.announcement_flash_resume.v1"
TRANSPORT_RECOVERY_SCHEMA = "v4.manager_workbench.announcement_flash_transport_recovery.v1"
FLASH_QUEUE_ID = "v4-manager-flash-incremental"
FLASH_QUEUE_IDENTITY_FIELDS = (
    "date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
    "model_id", "configuration_sha256", "rules", "role", "stage",
)
FLASH_PART_STAGE = "v4_manager_announcement_flash_long_body_part_v1"
FAILED_CANARY_REENTRY_JOB_ID = "4ac1419b17bd48dd9e1440f2bfdbcf3e"
FAILED_CANARY_REENTRY_SOURCE_JOB_ID = "29983573dff34359bfd34f054641a1d6"
FAILED_CANARY_REENTRY_CONTRACT = "NAMEERROR_PRE_DISPATCH_R4_V1"
FAILED_CANARY_REENTRY_INPUT_SHA256 = "8c551503248b4a74bdef4a59a4ac6a288a98263cb84211a357699cb343f75141"
FAILED_CANARY_REENTRY_PROGRESS_SHA256 = "89cf6e3c8fd7e10e0be5281099a81df4cbd5dae6f0848d74a3eea5f9b83f559e"
FAILED_CANARY_REENTRY_ATTEMPT_SHA256 = "8603ffaa9a3dea0d30338ebeccfa22aee1cf113ed2ea769af261a9a1d5301b86"
FAILED_CANARY_REENTRY_STACK = [
    {"file": "run_manager_flash_announcements.py", "function": "main", "line": 6080},
    {"file": "run_manager_flash_announcements.py", "function": "_run", "line": 4405},
]
FAILED_DISPATCH_CANARY_REENTRY_JOB_ID = "c03940f67a3945809524bf697fca0c1a"
FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID = "29983573dff34359bfd34f054641a1d6"
FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID = "07bfabf09f144360ab8869214aeecea8"
FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256 = "81dfeb15906527a64fb4ad521ea0edb5048068694b29b9191d72ce49da37264b"
FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256 = "16892521ce88b611f339c327677fd567b8315a023f28964675860c58b098316f"
FAILED_DISPATCH_CANARY_REENTRY_RESULT_SHA256 = "ed6ca1e00f6eaf4f9f7a8d7a429adfa639f969e9de313205dc057146ae4beaa9"
FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256 = "7bda625be8723f64a3271628fb325735446e846edf7abde0665c033470dfeecd"
FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256 = "adad120b70fccdefabc6f81110051bd241647cc0aa3e66fbaed02054afc16dc2"
FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT = "2026-10-18T14:25:58.803223+08:00"
FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID = "v4-zsxq-pdf-classification"
FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256 = "84328bf71967f6ae2303efd40df7cc35ff6b9ac6d4edeee8432f1bbf4830a0b3"
FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256 = "c6a04c88dd1b27845b3a7c9672de2a3c9da1f5d11c0aafa010c4859942e6f723"
FAILED_DISPATCH_CANARY_REENTRY_PARENT_RESULT_SHA256 = "6d625e297e5a62ed23de2367bc7c80f1c5c1dc5741d269a2b699195b3c655eda"
FAILED_DISPATCH_CANARY_REENTRY_PARENT_QUEUE_SHA256 = "7c8efb86c00ebc735420a5c89f0df9a87482cf7ce38ac75c4242b1cde48656c4"
FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256 = "8b7e3d6a2c7feda69859bb2574053fcb2a15e80959c1e8f2012c832f0913987f"
FAILED_DISPATCH_CANARY_REENTRY_KEY = "46f17ce94f7417fdb55bd68a01f074ebcde0e751e9aa532ee22aa1e57b1748c2"
FAILED_DISPATCH_CANARY_REENTRY_SOURCE_PART_KEY = "53bb028986b0ed9016fb3e7e56909edddc97e4d189eca40b53ece08dee952254"
FAILED_DISPATCH_CANARY_REENTRY_PART_INDEX = 17
FAILED_DISPATCH_CANARY_REENTRY_PART_COUNT = 22
FAILED_DISPATCH_CANARY_REENTRY_CANARY_PAYLOAD_SHA256 = "10057a64f17742be2f92e863009b6325716fac0fbb30eb540897101a5c55cb24"
FAILED_DISPATCH_CANARY_REENTRY_CANARY_RAW_SHA256 = "47b0f2573eba60ff2355942016fff88ca63e43be1b93c398698c921fd378a534"
FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY = "d2564a4f3035550c78a1106914f18bdf3cba4f789ad3e77a1db7261ea346ee8c"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256 = "adac10aa1db02ffb7eee7887b922bbea87f16438125074c0d104df4a4f180148"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256 = "27a2f417eba7e18e968714119460963e077d6f6942b7021e28ea9e576a68726f"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256 = "fa66d4d9cd13a4c449688463ef7db959f5d4f7c6a5da160eeedf2f410a599e5a"
FAILED_DISPATCH_CANARY_REENTRY_CONTRACT = "PRESERVE_C039_SYNTHESIS_R5_V1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_code(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,96}", value) else fallback


def _queue_model_lock_busy(queue_root: Path, model_id: str) -> bool:
    if not isinstance(model_id, str) or not model_id.strip():
        return True
    lock_name = hashlib.sha256(model_id.encode("utf-8")).hexdigest()
    lock_path = Path(queue_root) / "locks" / f"model-{lock_name}.lock"
    try:
        fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        if not os.path.isfile(lock_path) or lock_path.is_symlink():
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _merge_source_origins(*origin_lists: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[bytes] = set()
    for origins in origin_lists:
        if not isinstance(origins, list):
            continue
        for origin in origins:
            identity = _canonical(origin)
            if identity not in seen:
                seen.add(identity)
                merged.append(deepcopy(origin))
    return merged


def _merge_stocks(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(base)
    by_symbol = {item.get("symbol"): item for item in result if isinstance(item, dict)}
    for new in extra:
        symbol = new.get("symbol")
        if not isinstance(symbol, str):
            continue
        existing = by_symbol.get(symbol)
        new_stock = existing is None
        if existing is None:
            cloned = deepcopy(new)
            cloned["articles"] = []
            result.append(cloned)
            by_symbol[symbol] = cloned
            existing = cloned
        prior_articles = {article.get("article_id"): article for article in existing.get("articles", [])
                          if isinstance(article, dict)}
        for article in new.get("articles", []):
            if not isinstance(article, dict):
                continue
            article_id = article.get("article_id")
            prior = prior_articles.get(article_id)
            if prior is None:
                cloned = deepcopy(article)
                existing.setdefault("articles", []).append(cloned)
                prior_articles[article_id] = cloned
                reason = article.get("reason")
                if isinstance(reason, str) and not new_stock:
                    existing.setdefault("reasons", []).append(reason)
            elif isinstance(prior.get("source_origins"), list) or isinstance(article.get("source_origins"), list):
                prior["source_origins"] = _merge_source_origins(
                    prior.get("source_origins"), article.get("source_origins"))
        if new.get("reuse_status"):
            existing["reuse_status"] = new["reuse_status"]
        if existing.get("review_status") != new.get("review_status"):
            existing["review_status"] = "MIXED_MODEL_CANDIDATE_AND_PRIOR_REVIEWED"
    return result


class AnnouncementUpdate:
    """Owns one durable, serialized manual capture-to-Flash operation."""

    def __init__(self, service: Any, *, clock: Callable[[], datetime] | None = None,
                 popen: Callable[..., Any] = subprocess.Popen,
                 sleep: Callable[[float], None] = time.sleep):
        self.service = service
        self.clock = clock or (lambda: datetime.now(HK))
        self.popen = popen
        self.sleep = sleep

    def _active_flash_attempts(self, *, ignore_job_id: str | None = None) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for name in self.service.store.io.files("attempts"):
            if not name.endswith(".json"):
                continue
            try:
                value = json.loads(self.service.store.io.read_bytes(
                    "attempts/" + name, max_bytes=64 * 1024 * 1024))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("ANNOUNCEMENT_FLASH_ATTEMPT_SCAN_UNVERIFIED") from exc
            if not isinstance(value, dict):
                raise JobConflict("ANNOUNCEMENT_FLASH_ATTEMPT_SCHEMA_INVALID")
            context = value.get("context")
            scope = context.get("scope_refs") if isinstance(context, dict) else None
            operation = scope.get("capture_operation") if isinstance(scope, dict) else None
            job_id = value.get("job_id") or name[:-5]
            if (job_id != ignore_job_id and isinstance(operation, str) and operation.startswith("ANNOUNCEMENT_FLASH")
                    and value.get("state") in {"QUEUED", "RUNNING"}):
                active.append({"job_id": job_id,
                               "target_date": context.get("target_date") if isinstance(context, dict) else None,
                               "state": value.get("state")})
        return active

    def _failed_canary_reentry_request(self, wrapper_job_id: str, target_date: str) -> dict[str, Any]:
        """Reopen only the recorded 4ac pre-dispatch crash, bound to its accepted 2998 source."""
        if (wrapper_job_id != FAILED_CANARY_REENTRY_JOB_ID
                or not JOB_ID_RE.fullmatch(str(wrapper_job_id))):
            raise JobConflict("RESUME_FAILED_WRAPPER_ID_UNVERIFIED")
        try:
            job = self.service.jobs.get(wrapper_job_id)
            input_raw = self.service.store.io.read_bytes(self._job_ref(wrapper_job_id, "input.json"),
                                                         max_bytes=1024 * 1024)
            progress_raw = self.service.store.io.read_bytes(self._job_ref(wrapper_job_id, PROGRESS_REF),
                                                            max_bytes=1024 * 1024)
            attempt_raw = self.service.store.io.read_bytes(f"attempts/{wrapper_job_id}.json",
                                                           max_bytes=8 * 1024 * 1024)
        except (KeyError, OSError, ValueError) as exc:
            raise JobConflict("RESUME_FAILED_WRAPPER_ARTIFACT_UNAVAILABLE") from exc
        if (_sha(input_raw) != FAILED_CANARY_REENTRY_INPUT_SHA256
                or _sha(progress_raw) != FAILED_CANARY_REENTRY_PROGRESS_SHA256
                or _sha(attempt_raw) != FAILED_CANARY_REENTRY_ATTEMPT_SHA256):
            raise JobConflict("RESUME_FAILED_WRAPPER_EVIDENCE_SHA_CHANGED")
        try:
            input_value = json.loads(input_raw)
            progress_value = json.loads(progress_raw)
            attempt = json.loads(attempt_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_FAILED_WRAPPER_ARTIFACT_INVALID") from exc

        context = getattr(job, "context", None)
        scope = getattr(context, "scope_refs", {})
        operation = scope.get("capture_operation") if isinstance(scope, dict) else None
        if operation != FROZEN_RESUME_OPERATION:
            raise JobConflict("RESUME_FAILED_WRAPPER_OPERATION_INVALID")
        request = scope.get("announcement_flash_resume_request")
        binding = scope.get("announcement_flash_resume")
        expected_request_keys = {
            "source_job_id", "target_date", "resume_action", "source_input_sha256",
            "source_progress_sha256", "source_queue_state_sha256",
        }
        expected_binding_source_keys = (
            "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
            "source_progress_sha256", "source_queue_state_sha256", "capture_product_sha256",
            "source_result_sha256", "canary_passed", "canary_key", "canary_status",
            "canary_model_calls", "canary_validation", "legacy_failed_canary", "resume_action",
            "max_model_calls", "queue_status_counts",
        )
        if (not isinstance(request, dict) or set(request) != expected_request_keys
                or request.get("source_job_id") != FAILED_CANARY_REENTRY_SOURCE_JOB_ID
                or request.get("target_date") != target_date or request.get("resume_action") != "CANARY"
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(request.get(key, "")))
                       for key in ("source_input_sha256", "source_progress_sha256", "source_queue_state_sha256"))
                or not isinstance(binding, dict)
                or binding.get("schema") != FROZEN_RESUME_SCHEMA
                or binding.get("mode") != "INITIAL_CANARY"
                or binding.get("source_job_id") != request.get("source_job_id")
                or binding.get("target_date") != target_date
                or binding.get("resume_action") != "CANARY"
                or binding.get("source_input_sha256") != request.get("source_input_sha256")
                or binding.get("source_progress_sha256") != request.get("source_progress_sha256")
                or binding.get("source_queue_state_sha256") != request.get("source_queue_state_sha256")
                or binding.get("canary_passed") is not False
                or binding.get("canary_status") != "FAILED"
                or binding.get("canary_model_calls") != 1 or binding.get("max_model_calls") != 1
                or not isinstance(binding.get("canary_key"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", binding["canary_key"])
                or not isinstance(binding.get("resume_root"), dict)
                or not JOB_ID_RE.fullmatch(str(binding["resume_root"].get("source_job_id", "")))
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    str(binding["resume_root"].get("source_input_sha256", "")))
                or scope.get("capture_input_sha256") != digest(binding)):
            raise JobConflict("RESUME_FAILED_WRAPPER_BINDING_UNVERIFIED")
        legacy = binding.get("legacy_failed_canary")
        canary_validation = binding.get("canary_validation")
        if (not isinstance(legacy, dict) or legacy.get("key") != binding.get("canary_key")
                or legacy.get("source_job_id") != FAILED_CANARY_REENTRY_SOURCE_JOB_ID
                or legacy.get("root_job_id") != binding["resume_root"].get("source_job_id")
                or legacy.get("root_input_sha256") != binding["resume_root"].get("source_input_sha256")
                or not isinstance(canary_validation, dict)
                or canary_validation.get("failure_code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"):
            raise JobConflict("RESUME_FAILED_WRAPPER_CANARY_BINDING_UNVERIFIED")

        state_value = getattr(job, "state", None)
        state = getattr(state_value, "value", state_value)
        attempt_context = attempt.get("context") if isinstance(attempt, dict) else None
        attempt_scope = attempt_context.get("scope_refs") if isinstance(attempt_context, dict) else None
        input_capture_product = input_value.get("capture_product") if isinstance(input_value, dict) else None
        try:
            input_canonical = _canonical(input_value)
        except (TypeError, ValueError):
            raise JobConflict("RESUME_FAILED_WRAPPER_INPUT_INVALID") from None
        progress_diagnostic = progress_value.get("diagnostic") if isinstance(progress_value, dict) else None
        if (state != "FAILED" or getattr(job, "step", None) != "FLASH_SELECTION"
                or getattr(job, "failure_code", None) != "FLASH_PIPELINE_NAMEERROR"
                or getattr(job, "failed_steps", None) != ["FLASH_SELECTION"]
                or getattr(job, "retryable", None) is not False
                or getattr(job, "completed_count", None) != 0
                or not isinstance(attempt, dict) or attempt.get("job_id") != wrapper_job_id
                or attempt.get("state") != "FAILED" or attempt.get("step") != "FLASH_SELECTION"
                or attempt.get("failure_code") != "FLASH_PIPELINE_NAMEERROR"
                or attempt.get("failed_steps") != ["FLASH_SELECTION"]
                or attempt.get("retryable") is not False or attempt.get("completed_count") != 0
                or not isinstance(attempt_context, dict)
                or attempt_context.get("target_date") != target_date
                or attempt_context.get("cutoff") != getattr(context, "cutoff", None)
                or attempt_scope != scope
                or not isinstance(input_value, dict)
                or input_canonical != input_raw
                or set(input_value) != {"schema", "job_id", "target_date", "cutoff", "capture_product",
                                        "membership_gate", "resume_root", "resume_source"}
                or input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != wrapper_job_id
                or input_value.get("target_date") != target_date
                or input_value.get("cutoff") != getattr(context, "cutoff", None)
                or input_value.get("resume_root") != binding.get("resume_root")
                or not isinstance(input_capture_product, dict)
                or input_capture_product.get("sha256") != binding.get("capture_product_sha256")
                or input_value.get("resume_source") != {key: binding.get(key)
                    for key in expected_binding_source_keys}
                or not isinstance(progress_value, dict)
                or progress_value.get("step") != "FAILED"
                or progress_value.get("failure_code") != "FLASH_PIPELINE_NAMEERROR"
                or not isinstance(progress_diagnostic, dict)
                or progress_diagnostic.get("exception_type") != "NameError"
                or progress_diagnostic.get("stack_frames") != FAILED_CANARY_REENTRY_STACK):
            raise JobConflict("RESUME_FAILED_WRAPPER_NOT_PRE_DISPATCH_CRASH")

        source_input_raw = self.service.store.io.read_bytes(
            self._job_ref(FAILED_CANARY_REENTRY_SOURCE_JOB_ID, "input.json"), max_bytes=1024 * 1024)
        try:
            source_input = json.loads(source_input_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_FAILED_WRAPPER_SOURCE_INPUT_INVALID") from exc
        if (_sha(source_input_raw) != request.get("source_input_sha256")
                or not isinstance(source_input, dict)
                or input_value.get("capture_product") != source_input.get("capture_product")
                or input_value.get("membership_gate") != source_input.get("membership_gate")
                or input_value.get("cutoff") != source_input.get("cutoff")):
            raise JobConflict("RESUME_FAILED_WRAPPER_SOURCE_BINDING_UNVERIFIED")
        try:
            self.service.store.io.read_bytes(self._job_ref(wrapper_job_id, RESULT_REF), max_bytes=64 * 1024 * 1024)
        except FileNotFoundError:
            evidence = {"job_id": wrapper_job_id, "input_sha256": _sha(input_raw),
                        "progress_sha256": _sha(progress_raw), "attempt_sha256": _sha(attempt_raw),
                        "failure_code": "FLASH_PIPELINE_NAMEERROR", "completed_count": 0}
            return {**request, "_reentry_evidence_sha256": _sha(_canonical(evidence))}
        except OSError as exc:
            raise JobConflict("RESUME_FAILED_WRAPPER_RESULT_UNVERIFIED") from exc
        raise JobConflict("RESUME_FAILED_WRAPPER_HAS_RESULT")

    def _transport_recovery_payload_matches(self, payload: Any, item: dict[str, Any],
                                            capture_row: dict[str, Any], input_value: dict[str, Any],
                                            target_date: str) -> bool:
        identity = item.get("identity")
        metadata = payload.get("article_metadata") if isinstance(payload, dict) else None
        gate = input_value.get("membership_gate")
        capture = input_value.get("capture_product")
        if (not isinstance(identity, dict) or set(identity) != set(FLASH_QUEUE_IDENTITY_FIELDS)
                or not isinstance(payload, dict) or not isinstance(metadata, dict)
                or not isinstance(gate, dict) or not isinstance(capture, dict)):
            return False
        body = payload.get("article_body")
        body_sha = identity.get("body_sha256")
        source_sha = identity.get("source_sha256")
        capture_sha = capture.get("sha256")
        authority = gate.get("authority_sha256")
        issuer_codes = metadata.get("source_issuer_codes")
        issuer_membership = metadata.get("source_issuer_membership")
        gate_codes = gate.get("codes")
        origins = metadata.get("source_origins")
        if (gate.get("schema") != "v4.manager_workbench.announcement_connect_membership.v1"
                or gate.get("status") != "VERIFIED" or gate.get("market") != "HK_CONNECT"
                or gate.get("target_date") != target_date or gate.get("cutoff") != input_value.get("cutoff")
                or not isinstance(authority, str) or not re.fullmatch(r"[0-9a-f]{64}", authority)
                or not isinstance(capture_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", capture_sha)
                or not isinstance(body, str) or not isinstance(body_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", body_sha)
                or _sha(body.encode("utf-8")) != body_sha
                or payload.get("market") != "HK" or payload.get("role") != "announcement_reader"
                or payload.get("stage") != "v4_manager_announcement_flash_incremental"
                or identity.get("market") != "HK" or identity.get("role") != "announcement_reader"
                or identity.get("stage") != "v4_manager_announcement_flash_incremental"
                or capture_row.get("body_complete") is not True
                or capture_row.get("source_sha256") != source_sha
                or capture_row.get("body_text_sha256") != body_sha
                or capture_row.get("body_artifact_ref") != f"products/{source_sha}.json"
                or capture_row.get("body_text") != body
                or metadata.get("publication_date") != capture_row.get("publication_date")
                or identity.get("date") != capture_row.get("publication_date")
                or metadata.get("article_membership_status") != "IN"
                or metadata.get("membership_authority_sha256") != authority
                or not isinstance(gate_codes, list) or not isinstance(issuer_codes, list)
                or not isinstance(issuer_membership, list) or len(issuer_codes) < 1
                or len(issuer_membership) != len(issuer_codes)
                or not isinstance(origins, list)
                or not any(isinstance(origin, dict)
                           and origin.get("role") == "CAPTURE_WINDOW_PRODUCT_ROW"
                           and origin.get("source_product_sha256") == capture_sha for origin in origins)
                or not any(isinstance(origin, dict)
                           and origin.get("role") == "VERIFIED_FULL_NOTICE_BODY_PRODUCT"
                           and origin.get("source_product_sha256") == source_sha for origin in origins)):
            return False
        codes = [row.get("code") for row in issuer_codes if isinstance(row, dict)]
        members = [row.get("code") for row in issuer_membership if isinstance(row, dict)]
        if (len(codes) != len(issuer_codes) or set(codes) != set(members)
                or not set(codes).issubset(set(gate_codes))):
            return False
        for member in issuer_membership:
            if (not isinstance(member, dict) or member.get("membership_status") != "IN"
                    or member.get("market") != "HK_CONNECT" or member.get("authority_sha256") != authority):
                return False
        try:
            cutoff = datetime.fromisoformat(str(input_value.get("cutoff", "")))
            available = datetime.fromisoformat(str(metadata.get("available_at", "")))
            publication = datetime.fromisoformat(str(metadata.get("publication_date", "")))
            target = datetime.strptime(target_date, "%Y%m%d").date()
        except ValueError:
            return False
        return (cutoff.tzinfo is not None and cutoff.utcoffset() is not None
                and available.tzinfo is not None and available.utcoffset() is not None
                and available <= cutoff and publication.date() <= target
                and item.get("queue_id") == FLASH_QUEUE_ID
                and item.get("idempotency_key") == _sha(_canonical(identity))
                and {field: payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS} == identity)

    def _transport_recovery_plan(self, source_job_id: str, target_date: str,
                                 input_value: dict[str, Any], progress_value: dict[str, Any],
                                 result_value: dict[str, Any], result_raw: bytes,
                                 queue_value: dict[str, Any], hashes: dict[str, str],
                                 capture_value: dict[str, Any]) -> dict[str, Any]:
        system_stop = result_value.get("system_stop")
        progress_counts = result_value.get("counts", {}).get("queue") if isinstance(result_value.get("counts"), dict) else None
        failures = result_value.get("failures")
        pending = result_value.get("pending")
        queue_jobs = queue_value.get("jobs")
        if (result_value.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result_value.get("job_id") != source_job_id
                or result_value.get("target_trade_date") != target_date
                or result_value.get("state") != "PARTIAL"
                or not isinstance(system_stop, dict)
                or system_stop.get("stage") != "executor"
                or system_stop.get("failure_code") != "TransportError"
                or system_stop.get("queue_action") != "STOPPED_NO_AUTOMATIC_RETRY"
                or system_stop.get("attempt") != 1
                or progress_value.get("step") != "DONE"
                or progress_value.get("result_state") != "PARTIAL"
                or not isinstance(progress_counts, dict)
                or not isinstance(failures, list) or not isinstance(pending, list)
                or not isinstance(queue_jobs, dict)):
            raise JobConflict("RESUME_TRANSPORT_SYSTEM_STOP_NOT_EXACT")
        failed_rows = [row for row in failures if isinstance(row, dict)
                       and row.get("stage") == "executor"
                       and row.get("failure_code") == "TransportError"]
        if len(failed_rows) != 1:
            raise JobConflict("RESUME_TRANSPORT_FAILURE_NOT_UNIQUE")
        article_id = failed_rows[0].get("article_id")
        if not isinstance(article_id, str) or not article_id.startswith("EASTMONEY:"):
            raise JobConflict("RESUME_TRANSPORT_FAILURE_IDENTITY_INVALID")
        capture_rows = capture_value.get("rows")
        if not isinstance(capture_rows, list):
            raise JobConflict("RESUME_TRANSPORT_CAPTURE_INVALID")
        rows_by_article: dict[str, dict[str, Any]] = {}
        for row in capture_rows:
            if not isinstance(row, dict):
                raise JobConflict("RESUME_TRANSPORT_CAPTURE_ROW_INVALID")
            art_code = row.get("art_code")
            if isinstance(art_code, str) and art_code:
                key = "EASTMONEY:" + art_code
                if key in rows_by_article:
                    raise JobConflict("RESUME_TRANSPORT_CAPTURE_DUPLICATE")
                rows_by_article[key] = row
        failed_capture_row = rows_by_article.get(article_id)
        if not isinstance(failed_capture_row, dict):
            raise JobConflict("RESUME_TRANSPORT_CAPTURE_BINDING_UNVERIFIED")

        def matching_items(wanted_article_id: str, wanted_status: str) -> list[tuple[str, dict[str, Any]]]:
            matches = []
            row = rows_by_article.get(wanted_article_id)
            for key, item in queue_jobs.items():
                identity = item.get("identity") if isinstance(item, dict) else None
                if (not isinstance(item, dict) or not isinstance(identity, dict)
                        or identity.get("article_id") != wanted_article_id
                        or identity.get("date") != (row.get("publication_date") if isinstance(row, dict) else None)
                        or identity.get("source_sha256") != (row.get("source_sha256") if isinstance(row, dict) else None)
                        or identity.get("body_sha256") != (row.get("body_text_sha256") if isinstance(row, dict) else None)
                        or identity.get("market") != "HK" or identity.get("role") != "announcement_reader"
                        or identity.get("stage") != "v4_manager_announcement_flash_incremental"
                        or item.get("queue_id") != FLASH_QUEUE_ID or item.get("status") != wanted_status):
                    continue
                matches.append((key, item))
            return matches

        failed_matches = matching_items(article_id, "FAILED")
        if len(failed_matches) != 1:
            raise JobConflict("RESUME_TRANSPORT_QUEUE_FAILURE_NOT_UNIQUE")
        failed_key, failed_item = failed_matches[0]
        attempts = failed_item.get("attempts")
        attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
        error = attempt.get("error") if isinstance(attempt, dict) else None
        payload_ref = failed_item.get("input_path")
        if (failed_item.get("idempotency_key") != failed_key or failed_item.get("attempt_count") != 1
                or failed_item.get("max_attempts") != 1 or _sha(_canonical(failed_item.get("identity"))) != failed_key
                or not isinstance(attempt, dict) or attempt.get("status") != "FAILED"
                or attempt.get("number") != 1 or not isinstance(error, dict)
                or error.get("stage") != "executor" or error.get("code") != "TransportError"
                or payload_ref != f"jobs/{failed_key}/input.json"):
            raise JobConflict("RESUME_TRANSPORT_QUEUE_FAILURE_NOT_EXACT")
        try:
            payload_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + payload_ref, max_bytes=64 * 1024 * 1024)
            failed_payload = json.loads(payload_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_TRANSPORT_QUEUE_PAYLOAD_UNAVAILABLE") from exc
        if (_sha(payload_raw) != failed_item.get("payload_sha256")
                or not self._transport_recovery_payload_matches(
                    failed_payload, failed_item, failed_capture_row, input_value, target_date)):
            raise JobConflict("RESUME_TRANSPORT_QUEUE_PAYLOAD_UNVERIFIED")

        pending_rows = [row for row in pending if isinstance(row, dict)
                        and row.get("queue_reason") == "STOPPED_AFTER_SYSTEM_FAILURE"
                        and "part_index" not in row and "part_count" not in row]
        if (not pending_rows or len({row.get("article_id") for row in pending_rows}) != len(pending_rows)
                or any(not isinstance(row.get("article_id"), str) for row in pending_rows)):
            raise JobConflict("RESUME_TRANSPORT_PENDING_PLAN_INVALID")
        pending_tasks = []
        seen_pending_keys: set[str] = set()
        for row in pending_rows:
            pending_article_id = row["article_id"]
            capture_row = rows_by_article.get(pending_article_id)
            matches = matching_items(pending_article_id, "PENDING")
            if len(matches) != 1 or not isinstance(capture_row, dict):
                raise JobConflict("RESUME_TRANSPORT_PENDING_QUEUE_NOT_UNIQUE")
            key, item = matches[0]
            if (item.get("idempotency_key") != key or item.get("attempt_count") != 0
                    or item.get("max_attempts") != 1 or _sha(_canonical(item.get("identity"))) != key
                    or item.get("input_path") != f"jobs/{key}/input.json"):
                raise JobConflict("RESUME_TRANSPORT_PENDING_QUEUE_NOT_ELIGIBLE")
            try:
                raw = self.service.store.io.read_bytes(
                    "announcement_flash/queue/" + item["input_path"], max_bytes=64 * 1024 * 1024)
                payload = json.loads(raw)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_TRANSPORT_PENDING_PAYLOAD_UNAVAILABLE") from exc
            if (_sha(raw) != item.get("payload_sha256")
                    or not self._transport_recovery_payload_matches(payload, item, capture_row,
                                                                    input_value, target_date)):
                raise JobConflict("RESUME_TRANSPORT_PENDING_PAYLOAD_UNVERIFIED")
            if key in seen_pending_keys:
                raise JobConflict("RESUME_TRANSPORT_PENDING_PLAN_DUPLICATE")
            seen_pending_keys.add(key)
            pending_tasks.append({"key": key, "payload_sha256": item["payload_sha256"],
                                  "identity_sha256": _sha(_canonical(item["identity"]))})
        pending_tasks.sort(key=lambda row: row["key"])
        succeeded = progress_counts.get("succeeded")
        failed = progress_counts.get("failed")
        pending_count = progress_counts.get("pending")
        completed = progress_value.get("completed")
        total = progress_value.get("total")
        if (any(type(value) is not int or value < 0 for value in (succeeded, failed, pending_count, completed, total))
                or pending_count != len(pending_tasks) or failed < 1 or succeeded != completed
                or total != succeeded + failed + pending_count or progress_value.get("queue_counts") is not None):
            raise JobConflict("RESUME_TRANSPORT_PROGRESS_COUNTS_UNVERIFIED")
        return {
            "schema": TRANSPORT_RECOVERY_SCHEMA,
            "source_job_id": source_job_id,
            "source_input_sha256": hashes["source_input_sha256"],
            "source_progress_sha256": hashes["source_progress_sha256"],
            "source_result_sha256": _sha(result_raw),
            "source_queue_state_sha256": hashes["source_queue_state_sha256"],
            "capture_product_sha256": input_value["capture_product"]["sha256"],
            "failed_task": {"article_id": article_id, "key": failed_key,
                            "payload_sha256": failed_item["payload_sha256"],
                            "identity_sha256": _sha(_canonical(failed_item["identity"])),
                            "attempt_sha256": _sha(_canonical(attempt))},
            "pending_tasks": pending_tasks,
            "pending_manifest_sha256": _sha(_canonical(pending_tasks)),
            "queue_status_counts": {"SUCCEEDED": succeeded, "FAILED": failed, "PENDING": pending_count},
        }

    def _resume_source_artifacts(self, source_job_id: str, target_date: str,
                                 expected: dict[str, str] | None = None,
                                 ignore_active_job_id: str | None = None) -> dict[str, Any]:
        if not JOB_ID_RE.fullmatch(str(source_job_id)):
            raise ValueError("RESUME_SOURCE_JOB_ID_INVALID")
        from infrastructure.owned_io import SafeRoot

        source_job = self.service.jobs.get(source_job_id)
        if getattr(source_job.context, "target_date", None) != target_date:
            raise JobConflict("RESUME_SOURCE_TARGET_MISMATCH")
        source_scope = getattr(source_job.context, "scope_refs", {})
        operation = source_scope.get("capture_operation") if isinstance(source_scope, dict) else None
        if not (isinstance(operation, str) and operation.startswith("ANNOUNCEMENT_FLASH")):
            raise JobConflict("RESUME_SOURCE_OPERATION_INVALID")
        source_root = self.service.store.root
        input_ref = self._job_ref(source_job_id, "input.json")
        progress_ref = self._job_ref(source_job_id, PROGRESS_REF)
        queue_ref = "announcement_flash/queue/queue-state.json"
        input_raw = self.service.store.io.read_bytes(input_ref, max_bytes=1024 * 1024)
        progress_raw = self.service.store.io.read_bytes(progress_ref, max_bytes=1024 * 1024)
        queue_raw = self.service.store.io.read_bytes(queue_ref, max_bytes=64 * 1024 * 1024)
        hashes = {"source_input_sha256": _sha(input_raw),
                  "source_progress_sha256": _sha(progress_raw),
                  "source_queue_state_sha256": _sha(queue_raw)}
        if expected is not None and any(expected.get(key) != value for key, value in hashes.items()):
            raise JobConflict("RESUME_SOURCE_SHA_CHANGED")
        input_value = json.loads(input_raw)
        progress_value = json.loads(progress_raw)
        queue_value = json.loads(queue_raw)
        if (not isinstance(input_value, dict)
                or input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != source_job_id
                or input_value.get("target_date") != target_date
                or not isinstance(input_value.get("capture_product"), dict)
                or not isinstance(progress_value, dict)
                or not isinstance(queue_value, dict)
                or queue_value.get("schema") != "v4.announcement-engine-queue/v1"
                or not isinstance(queue_value.get("jobs"), dict)):
            raise JobConflict("RESUME_SOURCE_ARTIFACTS_INVALID")
        if (not re.fullmatch(r"products/[0-9a-f]{64}\.json",
                             str(input_value["capture_product"].get("artifact_ref", "")))
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    str(input_value["capture_product"].get("sha256", "")))):
            raise JobConflict("RESUME_CAPTURE_REFERENCE_INVALID")
        capture_root = getattr(self.service.config, "capture_root", None)
        if not capture_root:
            raise JobConflict("RESUME_CAPTURE_ROOT_UNAVAILABLE")
        capture_io = SafeRoot(capture_root)
        capture_raw = capture_io.read_bytes(input_value["capture_product"]["artifact_ref"], max_bytes=256 * 1024 * 1024)
        if _sha(capture_raw) != input_value["capture_product"]["sha256"]:
            raise JobConflict("RESUME_CAPTURE_PRODUCT_SHA_MISMATCH")
        capture_value = json.loads(capture_raw)
        if not isinstance(capture_value, dict) or not isinstance(capture_value.get("rows"), list):
            raise JobConflict("RESUME_CAPTURE_PRODUCT_INVALID")
        try:
            result_raw = self.service.store.io.read_bytes(self._job_ref(source_job_id, RESULT_REF),
                                                          max_bytes=64 * 1024 * 1024)
            result_value = json.loads(result_raw)
            result_absent = False
        except FileNotFoundError:
            result_raw, result_value, result_absent = None, None, True
        queue_reconstruction = None
        transport_recovery = None
        if result_absent:
            if getattr(source_job.state, "value", source_job.state) not in {"FAILED", "INTERRUPTED", "PARTIAL"}:
                raise JobConflict("RESUME_SOURCE_NOT_INTERRUPTED")
            mode = "INITIAL_CANARY"
            canary_passed = False
            canary_key = None
            canary_status = None
            canary_model_calls = 0
            canary_validation = None
            legacy_failed_canary = None
        else:
            if isinstance(result_value, dict) and isinstance(result_value.get("system_stop"), dict):
                if getattr(source_job.state, "value", source_job.state) != "PARTIAL":
                    raise JobConflict("RESUME_TRANSPORT_SOURCE_STATE_INVALID")
                transport_recovery = self._transport_recovery_plan(
                    source_job_id, target_date, input_value, progress_value, result_value,
                    result_raw, queue_value, hashes, capture_value)
                completed = {"mode": "INITIAL_CANARY", "canary_passed": False,
                             "canary_key": None, "canary_status": None, "canary_model_calls": 0,
                             "canary_validation": None, "legacy_failed_canary": None,
                             "transport_recovery": transport_recovery}
            else:
                completed = self._completed_resume_canary(source_job_id, target_date, input_value,
                                                           result_value, queue_value, hashes, source_root)
            queue_reconstruction = completed.get("queue_reconstruction")
            mode = completed["mode"]
            canary_passed = completed["canary_passed"]
            canary_key = completed["canary_key"]
            canary_status = completed["canary_status"]
            canary_model_calls = completed["canary_model_calls"]
            canary_validation = completed["canary_validation"]
            legacy_failed_canary = completed["legacy_failed_canary"]
            transport_recovery = completed.get("transport_recovery", transport_recovery)

        jobs = queue_value["jobs"]
        date_items = self._resume_plan_queue_items(source_job_id, target_date, capture_value, jobs)
        if isinstance(legacy_failed_canary, dict):
            matching_legacy_parts = []
            expected_part = legacy_failed_canary.get("part_descriptor")
            for entry in date_items:
                source_item = entry["item"]
                if source_item.get("status") != "FAILED":
                    continue
                source_ref = source_item.get("input_path")
                if not isinstance(source_ref, str) or source_ref != f"jobs/{entry['key']}/input.json":
                    continue
                try:
                    source_payload_raw = self.service.store.io.read_bytes(
                        "announcement_flash/queue/" + source_ref, max_bytes=64 * 1024 * 1024)
                    source_payload = json.loads(source_payload_raw)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise JobConflict("RESUME_LEGACY_CANARY_PLAN_SOURCE_UNAVAILABLE") from exc
                if (not isinstance(source_payload, dict)
                        or _sha(source_payload_raw) != source_item.get("payload_sha256")
                        or source_payload.get("article_id") != legacy_failed_canary.get("article_id")
                        or source_payload.get("source_sha256") != legacy_failed_canary.get("source_sha256")
                        or source_payload.get("body_sha256") != legacy_failed_canary.get("body_sha256")
                        or source_payload.get("chunk_plan_sha256") != legacy_failed_canary.get("chunk_plan_sha256")
                        or source_payload.get("source_unit_map_sha256")
                        != legacy_failed_canary.get("source_unit_map_sha256")
                        or source_payload.get("part_descriptor") != expected_part):
                    continue
                matching_legacy_parts.append(entry)
            if len(matching_legacy_parts) != 1:
                raise JobConflict("RESUME_LEGACY_CANARY_PLAN_BINDING_UNVERIFIED")
            legacy_failed_canary["source_part_key"] = matching_legacy_parts[0]["key"]
        model_ids = {entry["item"].get("model_id") for entry in date_items
                     if isinstance(entry["item"].get("model_id"), str)}
        counts: dict[str, int] = {}
        for entry in date_items:
            status = entry["item"].get("status")
            counts[str(status)] = counts.get(str(status), 0) + 1
        observed_date_counts = dict(counts)
        running = [entry for entry in date_items if entry["item"].get("status") == "RUNNING"]
        queue_root = source_root / "announcement_flash" / "queue"
        running_results: list[str] = []
        for entry in running:
            item = entry["item"]
            result_status = self._queue_orphan_result_state(queue_root, entry["key"], item)
            running_results.append(result_status)
        planned_keys = {entry["key"] for entry in date_items}
        for key, item in jobs.items():
            if (not isinstance(item, dict) or item.get("queue_id") != FLASH_QUEUE_ID
                    or item.get("status") != "RUNNING"):
                continue
            identity = item.get("identity")
            item_date = identity.get("date") if isinstance(identity, dict) else None
            if (key not in planned_keys and isinstance(item_date, str)
                    and item_date.replace("-", "") == target_date):
                raise JobConflict("RESUME_ORPHAN_IDENTITY_UNVERIFIED")
        same_model_running = {key for key, item in jobs.items()
                              if isinstance(item, dict) and item.get("queue_id") == FLASH_QUEUE_ID
                              and item.get("model_id") in model_ids and item.get("status") == "RUNNING"}
        planned_running = {entry["key"] for entry in running}
        if same_model_running != planned_running:
            raise JobConflict("RESUME_MODEL_OWNER_ACTIVE")
        model_busy = any(_queue_model_lock_busy(queue_root, model_id) for model_id in model_ids)
        active = self._active_flash_attempts(ignore_job_id=ignore_active_job_id)
        if active:
            raise JobConflict("ANNOUNCEMENT_FLASH_BUSY_ALL_TARGET_DATES")
        if model_busy:
            raise JobConflict("RESUME_MODEL_OWNER_ACTIVE")
        if mode == "INITIAL_CANARY":
            if transport_recovery is not None:
                if running:
                    raise JobConflict("RESUME_TRANSPORT_HAS_ACTIVE_PART")
                if not transport_recovery.get("pending_tasks"):
                    raise JobConflict("RESUME_PENDING_ITEMS_MISSING")
            elif legacy_failed_canary is not None:
                if running:
                    raise JobConflict("RESUME_LEGACY_CANARY_HAS_ACTIVE_PART")
                if counts.get("PENDING", 0) < 1:
                    raise JobConflict("RESUME_PENDING_ITEMS_MISSING")
            elif len(running) != 1 or running_results != ["NONE"]:
                raise JobConflict("RESUME_ORPHAN_NOT_ELIGIBLE")
            if transport_recovery is None and legacy_failed_canary is None:
                progress_counts = progress_value.get("queue_counts") if isinstance(progress_value.get("queue_counts"), dict) else {}
                progress_status_counts = {key: progress_counts.get(key, 0)
                                          for key in ("SUCCEEDED", "FAILED", "PENDING", "RUNNING")}
                progress_total = progress_value.get("total")
                if (any(type(value) is not int or value < 0 for value in progress_status_counts.values())
                        or type(progress_total) is not int
                        or sum(progress_status_counts.values()) != progress_total
                        or progress_status_counts != {status: counts.get(status, 0)
                                                      for status in ("SUCCEEDED", "FAILED", "PENDING", "RUNNING")}
                        or progress_status_counts.get("PENDING", 0) < 1
                        or progress_status_counts.get("RUNNING", 0) != 1):
                    raise JobConflict("RESUME_PROGRESS_QUEUE_COUNTS_UNVERIFIED")
                if counts.get("PENDING", 0) < 1:
                    raise JobConflict("RESUME_PENDING_ITEMS_MISSING")
        else:
            if len(running) > 1 or (running and running_results != ["NONE"]):
                raise JobConflict("RESUME_ORPHAN_NOT_ELIGIBLE")
            pending_count = counts.get("PENDING", 0)
            if pending_count < 1:
                raise JobConflict("RESUME_PENDING_ITEMS_MISSING")
        return {"schema": FROZEN_RESUME_SCHEMA,
                "status": "ELIGIBLE",
                "eligible": True,
                "mode": mode,
                "source_job_id": source_job_id,
                "target_date": target_date,
                **hashes,
                "capture_product_sha256": input_value["capture_product"]["sha256"],
                "queue_status_counts": counts,
                "target_date_queue_observed_counts": observed_date_counts,
                "orphan_count": len(running),
                "recoverable_orphan_count": (1 if mode in {"INITIAL_CANARY", "CONTINUE_AFTER_CANARY"}
                                             and len(running) == 1 and running_results == ["NONE"] else 0),
                "orphan_result_status": running_results,
                "canary_passed": canary_passed,
                "canary_key": canary_key,
                "canary_status": canary_status,
                "canary_model_calls": canary_model_calls,
                "canary_validation": canary_validation,
                "legacy_failed_canary": legacy_failed_canary,
                **({"queue_reconstruction": queue_reconstruction}
                   if isinstance(queue_reconstruction, dict) else {}),
                **({"transport_recovery": transport_recovery}
                   if isinstance(transport_recovery, dict) else {}),
                "resume_action": "CANARY" if mode == "INITIAL_CANARY" else "CONTINUE",
                "max_model_calls": 1 if not canary_passed else None,
                "source_input": input_value,
                "source_result_sha256": _sha(result_raw) if result_raw is not None else None,
                "source_cutoff": getattr(source_job.context, "cutoff", None)}

    def _resume_plan_queue_items(self, source_job_id: str, target_date: str,
                                 capture_product: dict[str, Any],
                                 queue_jobs: dict[str, Any]) -> list[dict[str, Any]]:
        """Bind queue rows to this frozen capture and saved long-body plan.

        Announcement identity.date is the source publication date, which can
        precede the workbench target date. The job-local plan and exact queue
        payload/key are the ownership proof for its part rows.
        """
        if capture_product.get("source") != "EASTMONEY_HK":
            raise JobConflict("RESUME_CAPTURE_SOURCE_UNSUPPORTED")
        if str(capture_product.get("target_trade_date", "")).replace("-", "") != target_date:
            raise JobConflict("RESUME_CAPTURE_TARGET_MISMATCH")
        capture_rows: dict[str, dict[str, Any]] = {}
        for row in capture_product.get("rows", []):
            if not isinstance(row, dict):
                raise JobConflict("RESUME_CAPTURE_ROW_INVALID")
            art_code = row.get("art_code")
            if not isinstance(art_code, str) or not art_code:
                continue
            article_id = "EASTMONEY:" + art_code
            if article_id in capture_rows:
                raise JobConflict("RESUME_CAPTURE_ARTICLE_DUPLICATE")
            capture_rows[article_id] = row

        plan_prefix = f"announcement_flash/jobs/{source_job_id}/long-body"
        try:
            plan_names = self.service.store.io.files(plan_prefix)
        except (OSError, ValueError) as exc:
            raise JobConflict("RESUME_PLAN_ARTIFACTS_UNAVAILABLE") from exc
        if not plan_names:
            raise JobConflict("RESUME_PLAN_ARTIFACTS_MISSING")

        expected_parts: list[dict[str, Any]] = []
        sha_re = re.compile(r"^[0-9a-f]{64}$")
        for name in plan_names:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+-[0-9a-f]{64}\.json", name):
                raise JobConflict("RESUME_PLAN_REFERENCE_INVALID")
            try:
                raw = self.service.store.io.read_bytes(f"{plan_prefix}/{name}", max_bytes=64 * 1024 * 1024)
                plan = json.loads(raw)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_PLAN_ARTIFACT_INVALID") from exc
            if not isinstance(plan, dict) or plan.get("schema") != "v4.manager_workbench.announcement_chunk_plan.v1":
                raise JobConflict("RESUME_PLAN_ARTIFACT_INVALID")
            plan_sha = plan.get("plan_sha256")
            article_id = plan.get("article_id")
            parts = plan.get("parts")
            material = {key: value for key, value in plan.items() if key != "plan_sha256"}
            if (not isinstance(plan_sha, str) or not sha_re.fullmatch(plan_sha)
                    or _sha(_canonical(material)) != plan_sha
                    or not isinstance(article_id, str)
                    or not re.fullmatch(r"EASTMONEY:[A-Za-z0-9_-]{1,128}", article_id)
                    or name != f"{article_id.replace(':', '_')}-{plan_sha}.json"
                    or not isinstance(parts, list) or not parts):
                raise JobConflict("RESUME_PLAN_IDENTITY_INVALID")
            capture_row = capture_rows.get(article_id)
            publication_date = capture_row.get("publication_date") if isinstance(capture_row, dict) else None
            if (not isinstance(capture_row, dict) or capture_row.get("body_complete") is not True
                    or capture_row.get("source_sha256") != plan.get("source_sha256")
                    or capture_row.get("body_text_sha256") != plan.get("body_sha256")
                    or capture_row.get("body_artifact_ref") != f"products/{plan.get('source_sha256')}.json"
                    or not isinstance(publication_date, str)
                    or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", publication_date)):
                raise JobConflict("RESUME_PLAN_CAPTURE_BINDING_UNVERIFIED")
            if any(not isinstance(plan.get(field), str) or not sha_re.fullmatch(plan[field])
                   for field in ("source_sha256", "body_sha256", "prompt_sha256", "configuration_sha256",
                                 "source_unit_map_sha256", "fixed_fact_ledger_sha256", "part_addendum_sha256")):
                raise JobConflict("RESUME_PLAN_IDENTITY_INVALID")
            part_count = len(parts)
            indexes: set[int] = set()
            for part in parts:
                if not isinstance(part, dict):
                    raise JobConflict("RESUME_PLAN_PART_INVALID")
                part_index = part.get("part_index")
                part_sha = part.get("part_sha256")
                if (type(part_index) is not int or not 1 <= part_index <= part_count
                        or part.get("part_count") != part_count
                        or not isinstance(part_sha, str) or not sha_re.fullmatch(part_sha)
                        or part_index in indexes):
                    raise JobConflict("RESUME_PLAN_PART_INVALID")
                indexes.add(part_index)
                rules_suffix = (f"+long-body-part:v1+plan:{plan_sha}+part:{part_index}/{part_count}"
                                f"+part-sha:{part_sha}+part-prompt:{plan['prompt_sha256']}"
                                f"+part-addendum:{plan['part_addendum_sha256']}")
                expected_parts.append({"date": publication_date, "article_id": article_id,
                                       "source_sha256": plan["source_sha256"],
                                       "body_sha256": plan["body_sha256"],
                                       "prompt_sha256": plan["prompt_sha256"],
                                       "configuration_sha256": plan["configuration_sha256"],
                                       "source_unit_map_sha256": plan["source_unit_map_sha256"],
                                       "fixed_fact_ledger_sha256": plan["fixed_fact_ledger_sha256"],
                                       "plan_sha256": plan_sha, "part": part,
                                       "rules_suffix": rules_suffix})
            if indexes != set(range(1, part_count + 1)):
                raise JobConflict("RESUME_PLAN_PART_COVERAGE_INVALID")

        if not expected_parts:
            raise JobConflict("RESUME_PLAN_ARTIFACTS_MISSING")
        bound: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for expected in expected_parts:
            matches: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            part = expected["part"]
            for key, item in queue_jobs.items():
                if not isinstance(item, dict) or item.get("queue_id") != FLASH_QUEUE_ID:
                    continue
                identity = item.get("identity")
                if not isinstance(identity, dict):
                    continue
                rules = identity.get("rules")
                if not isinstance(rules, str) or not rules.endswith(expected["rules_suffix"]):
                    continue
                if (f"+unit-map:{expected['source_unit_map_sha256']}+" not in rules
                        or f"+fixed-ledger:{expected['fixed_fact_ledger_sha256']}+" not in rules):
                    continue
                expected_identity = {
                    "date": expected["date"], "market": "HK", "article_id": expected["article_id"],
                    "source_sha256": expected["source_sha256"], "body_sha256": expected["body_sha256"],
                    "prompt_sha256": expected["prompt_sha256"],
                    "model_id": identity.get("model_id"),
                    "configuration_sha256": expected["configuration_sha256"],
                    "rules": rules, "role": "announcement_reader_part", "stage": FLASH_PART_STAGE,
                }
                if (set(identity) != set(FLASH_QUEUE_IDENTITY_FIELDS)
                        or any(identity.get(field) != value for field, value in expected_identity.items())
                        or not isinstance(expected_identity["model_id"], str)
                        or item.get("model_id") != expected_identity["model_id"]):
                    continue
                if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                        or item.get("idempotency_key") != key or _sha(_canonical(identity)) != key):
                    raise JobConflict("RESUME_QUEUE_IDENTITY_INVALID")
                input_ref = f"jobs/{key}/input.json"
                if item.get("input_path") != input_ref or not isinstance(item.get("payload_sha256"), str):
                    raise JobConflict("RESUME_QUEUE_PAYLOAD_REFERENCE_INVALID")
                try:
                    payload_raw = self.service.store.io.read_bytes(
                        "announcement_flash/queue/" + input_ref, max_bytes=64 * 1024 * 1024)
                    payload = json.loads(payload_raw)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise JobConflict("RESUME_QUEUE_PAYLOAD_UNAVAILABLE") from exc
                metadata = payload.get("article_metadata") if isinstance(payload, dict) else None
                descriptor = payload.get("part_descriptor") if isinstance(payload, dict) else None
                ledger = payload.get("fixed_fact_ledger") if isinstance(payload, dict) else None
                if (_sha(payload_raw) != item.get("payload_sha256") or not isinstance(payload, dict)
                        or {field: payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS} != identity
                        or payload.get("chunk_plan_sha256") != expected["plan_sha256"]
                        or payload.get("source_unit_map_sha256") != expected["source_unit_map_sha256"]
                        or not isinstance(payload.get("article_body"), str)
                        or _sha(payload["article_body"].encode("utf-8")) != expected["body_sha256"]
                        or not isinstance(metadata, dict) or metadata.get("publication_date") != expected["date"]
                        or not isinstance(descriptor, dict) or _canonical(descriptor) != _canonical(part)
                        or not isinstance(ledger, dict)
                        or ledger.get("ledger_sha256") != expected["fixed_fact_ledger_sha256"]):
                    raise JobConflict("RESUME_QUEUE_PAYLOAD_PLAN_BINDING_UNVERIFIED")
                matches.append((key, item, identity))
            if len(matches) != 1:
                raise JobConflict("RESUME_QUEUE_PLAN_BINDING_UNVERIFIED")
            key, item, _identity = matches[0]
            if key in seen_keys:
                raise JobConflict("RESUME_QUEUE_PLAN_DUPLICATE_KEY")
            seen_keys.add(key)
            bound.append({"key": key, "item": item})
        return bound

    def _queue_orphan_result_state(self, queue_root: Path, key: str, item: dict[str, Any]) -> str:
        refs: list[tuple[str, str | None]] = []
        validated_ref = item.get("validated_path")
        validated_sha = item.get("validated_sha256")
        if validated_ref is not None or validated_sha is not None:
            if not isinstance(validated_ref, str):
                return "UNVERIFIED"
            refs.append((validated_ref, validated_sha if isinstance(validated_sha, str) else None))
        attempt_count = item.get("attempt_count")
        if type(attempt_count) is not int or attempt_count < 1:
            return "UNVERIFIED"
        conventional = f"jobs/{key}/attempt-{attempt_count:04d}.validated.json"
        if conventional not in {ref for ref, _sha in refs}:
            refs.append((conventional, None))
        for ref, expected_sha in refs:
            parts = ref.split("/")
            if ref.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                return "UNVERIFIED"
            try:
                raw = self.service.store.io.read_bytes("announcement_flash/queue/" + ref,
                                                       max_bytes=64 * 1024 * 1024)
            except FileNotFoundError:
                if expected_sha is not None:
                    return "UNVERIFIED"
                continue
            except (OSError, ValueError):
                return "UNVERIFIED"
            if expected_sha is not None and _sha(raw) != expected_sha:
                return "UNVERIFIED"
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return "UNVERIFIED"
            rows = value.get("results") if isinstance(value, dict) else None
            output = rows[0].get("reader_output") if isinstance(rows, list) and len(rows) == 1 else None
            identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
            if (not isinstance(output, dict)
                    or output.get("source_sha256") != identity.get("source_sha256")
                    or output.get("body_sha256") != identity.get("body_sha256")
                    or output.get("article_id") != identity.get("article_id")):
                return "UNVERIFIED"
            return "COMPLETE"
        return "NONE"

    def _c039_queue_reconstruction(self, queue_raw: bytes,
                                   queue_value: dict[str, Any]) -> dict[str, Any]:
        """Prove that only post-c039, non-announcement queue additions sit beside the frozen queue."""
        if (_sha(queue_raw) != _sha(_canonical(queue_value))
                or set(queue_value) != {"schema", "created_at", "jobs", "events"}
                or queue_value.get("schema") != "v4.announcement-engine-queue/v1"
                or not isinstance(queue_value.get("jobs"), dict)
                or not isinstance(queue_value.get("events"), list)):
            raise JobConflict("RESUME_C039_QUEUE_SERIALIZATION_UNVERIFIED")
        try:
            attempt_raw = self.service.store.io.read_bytes(
                f"attempts/{FAILED_DISPATCH_CANARY_REENTRY_JOB_ID}.json", max_bytes=8 * 1024 * 1024)
            attempt_value = json.loads(attempt_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_C039_ATTEMPT_UNAVAILABLE") from exc
        if (_sha(attempt_raw) != FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256
                or not isinstance(attempt_value, dict)
                or attempt_value.get("job_id") != FAILED_DISPATCH_CANARY_REENTRY_JOB_ID
                or attempt_value.get("state") != "PARTIAL"
                or attempt_value.get("step") != "DONE"
                or attempt_value.get("retryable") is not False
                or attempt_value.get("finished_at") != FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT):
            raise JobConflict("RESUME_C039_ATTEMPT_BINDING_UNVERIFIED")

        finished_at = datetime.fromisoformat(FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT)

        def after_attempt(value: Any) -> bool:
            if not isinstance(value, str):
                return False
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return False
            return parsed.tzinfo is not None and parsed > finished_at

        jobs = queue_value["jobs"]
        extension_keys = []
        for key, item in jobs.items():
            if not isinstance(item, dict):
                raise JobConflict("RESUME_C039_QUEUE_RECORD_INVALID")
            if item.get("queue_id") != FLASH_QUEUE_ID:
                extension_keys.append(key)
        extension_keys.sort()
        if _sha(queue_raw) == FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256 and not extension_keys:
            return {"schema": "v4.manager_workbench.announcement_queue_reconstruction.v1",
                    "baseline_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
                    "reconstructed_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
                    "current_sha256": _sha(queue_raw),
                    "source_attempt_sha256": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256,
                    "source_attempt_finished_at": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT,
                    "excluded_jobs": []}
        if not extension_keys:
            raise JobConflict("RESUME_C039_QUEUE_BASE_SHA_MISMATCH")

        extension_set = set(extension_keys)
        extension_events = [event for event in queue_value["events"]
                            if isinstance(event, dict) and event.get("idempotency_key") in extension_set]
        if any(not isinstance(event, dict) for event in queue_value["events"]):
            raise JobConflict("RESUME_C039_QUEUE_EVENT_INVALID")
        event_keys = {event.get("idempotency_key") for event in extension_events}
        if event_keys != extension_set:
            raise JobConflict("RESUME_C039_QUEUE_EXTENSION_EVENTS_UNVERIFIED")

        excluded_jobs = []
        identity_fields = set(FLASH_QUEUE_IDENTITY_FIELDS)
        for key in extension_keys:
            item = jobs[key]
            identity = item.get("identity")
            if (item.get("queue_id") != FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
                    or item.get("idempotency_key") != key
                    or not isinstance(identity, dict) or set(identity) != identity_fields
                    or _sha(_canonical(identity)) != key
                    or item.get("queue_ids") != [FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID]
                    or item.get("status") != "FAILED" or item.get("attempt_count") != 1
                    or item.get("max_attempts") != 1
                    or item.get("input_path") != f"jobs/{key}/input.json"
                    or not isinstance(item.get("payload_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["payload_sha256"])
                    or item.get("raw_path") is not None or item.get("raw_sha256") is not None
                    or item.get("validated_path") is not None or item.get("validated_sha256") is not None
                    or not after_attempt(item.get("created_at"))
                    or not after_attempt(item.get("updated_at"))):
                raise JobConflict("RESUME_C039_QUEUE_EXTENSION_RECORD_UNVERIFIED")
            try:
                payload_raw = self.service.store.io.read_bytes(
                    "announcement_flash/queue/" + item["input_path"], max_bytes=64 * 1024 * 1024)
                payload = json.loads(payload_raw)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_C039_QUEUE_EXTENSION_PAYLOAD_UNAVAILABLE") from exc
            if (_sha(payload_raw) != item["payload_sha256"] or not isinstance(payload, dict)
                    or {field: payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS} != identity
                    or not isinstance(payload.get("article_body"), str)
                    or _sha(payload["article_body"].encode("utf-8")) != identity.get("body_sha256")
                    or item.get("body_length_bytes") != len(payload["article_body"].encode("utf-8"))
                    or payload.get("market") != "PDF"
                    or payload.get("stage") != "local_pdf_classification"
                    or payload.get("role") != "document_classifier"
                    or payload.get("rules") != "v4_zsxq_pdf_local_classification_v1"):
                raise JobConflict("RESUME_C039_QUEUE_EXTENSION_PAYLOAD_UNVERIFIED")
            events = [event for event in extension_events if event.get("idempotency_key") == key]
            events.sort(key=lambda event: event.get("at", ""))
            expected_events = (("item_enqueued", "PENDING", 0),
                               ("attempt_started", "RUNNING", 1),
                               ("attempt_failed", "FAILED", 1))
            if (len(events) != len(expected_events)
                    or any(event.get("queue_id") != FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
                           or event.get("model_id") != item.get("model_id")
                           or not after_attempt(event.get("at")) for event in events)
                    or tuple((event.get("event"), event.get("status"), event.get("attempt"))
                             for event in events) != expected_events):
                raise JobConflict("RESUME_C039_QUEUE_EXTENSION_EVENTS_UNVERIFIED")
            attempts = item.get("attempts")
            attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
            error = attempt.get("error") if isinstance(attempt, dict) else None
            if (not isinstance(attempt, dict) or attempt.get("number") != 1
                    or attempt.get("status") != "FAILED"
                    or attempt.get("consumer_queue_id") != FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
                    or not after_attempt(attempt.get("started_at"))
                    or not after_attempt(attempt.get("finished_at"))
                    or not isinstance(error, dict)
                    or error.get("code") != "MODEL_TRANSPORT_FAILED"):
                raise JobConflict("RESUME_C039_QUEUE_EXTENSION_ATTEMPT_UNVERIFIED")
            excluded_jobs.append({"key": key, "queue_id": item["queue_id"],
                                  "record_sha256": _sha(_canonical(item)),
                                  "payload_sha256": item["payload_sha256"],
                                  "events_sha256": _sha(_canonical(events)),
                                  "event_count": len(events)})

        reconstructed = deepcopy(queue_value)
        for key in extension_keys:
            reconstructed["jobs"].pop(key)
        reconstructed["events"] = [event for event in reconstructed["events"]
                                   if event.get("idempotency_key") not in extension_set]
        reconstructed_sha = _sha(_canonical(reconstructed))
        if reconstructed_sha != FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256:
            raise JobConflict("RESUME_C039_QUEUE_BASE_SHA_MISMATCH")
        return {"schema": "v4.manager_workbench.announcement_queue_reconstruction.v1",
                "baseline_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
                "reconstructed_sha256": reconstructed_sha,
                "current_sha256": _sha(queue_raw),
                "source_attempt_sha256": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256,
                "source_attempt_finished_at": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT,
                "excluded_jobs": excluded_jobs}

    def _failed_dispatch_canary_reentry(self, source_job_id: str, target_date: str,
                                        input_value: dict[str, Any], result_value: Any,
                                        queue_value: dict[str, Any], hashes: dict[str, str],
                                        source_root: Path) -> dict[str, Any]:
        """Reopen only c039's failed target canary, retaining its unrelated saved synthesis success."""
        if (source_job_id != FAILED_DISPATCH_CANARY_REENTRY_JOB_ID
                or target_date != "20261016"
                or hashes.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256
                or hashes.get("source_progress_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256):
            raise JobConflict("RESUME_C039_REENTRY_EVIDENCE_CHANGED")
        try:
            input_raw = self.service.store.io.read_bytes(
                self._job_ref(source_job_id, "input.json"), max_bytes=1024 * 1024)
            progress_raw = self.service.store.io.read_bytes(
                self._job_ref(source_job_id, PROGRESS_REF), max_bytes=1024 * 1024)
            result_raw = self.service.store.io.read_bytes(
                self._job_ref(source_job_id, RESULT_REF), max_bytes=64 * 1024 * 1024)
        except (OSError, ValueError) as exc:
            raise JobConflict("RESUME_C039_REENTRY_ARTIFACT_UNAVAILABLE") from exc
        if (_sha(input_raw) != FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256
                or _sha(progress_raw) != FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256
                or _sha(result_raw) != FAILED_DISPATCH_CANARY_REENTRY_RESULT_SHA256
                or _canonical(input_value) != input_raw):
            raise JobConflict("RESUME_C039_REENTRY_EVIDENCE_CHANGED")
        try:
            queue_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/queue-state.json", max_bytes=64 * 1024 * 1024)
        except (OSError, ValueError) as exc:
            raise JobConflict("RESUME_C039_QUEUE_STATE_UNAVAILABLE") from exc
        if _sha(queue_raw) != hashes.get("source_queue_state_sha256"):
            raise JobConflict("RESUME_C039_QUEUE_STATE_CHANGED")
        queue_reconstruction = self._c039_queue_reconstruction(queue_raw, queue_value)

        root = input_value.get("resume_root")
        binding = input_value.get("resume_source")
        expected_root = {"source_job_id": FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID,
                         "source_input_sha256": FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256}
        expected_binding_keys = {
            "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
            "source_progress_sha256", "source_queue_state_sha256", "source_result_sha256",
            "capture_product_sha256", "canary_passed", "canary_key", "canary_status",
            "canary_model_calls", "canary_validation", "legacy_failed_canary",
            "resume_action", "max_model_calls", "queue_status_counts",
        }
        if (root != expected_root or not isinstance(binding, dict)
                or set(binding) != expected_binding_keys
                or binding.get("schema") != FROZEN_RESUME_SCHEMA
                or binding.get("mode") != "INITIAL_CANARY"
                or binding.get("source_job_id") != FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
                or binding.get("target_date") != target_date
                or binding.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256
                or binding.get("source_progress_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256
                or binding.get("source_queue_state_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_QUEUE_SHA256
                or binding.get("source_result_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_RESULT_SHA256
                or binding.get("capture_product_sha256") != input_value.get("capture_product", {}).get("sha256")
                or binding.get("canary_passed") is not False
                or binding.get("canary_key") != FAILED_DISPATCH_CANARY_REENTRY_KEY
                or binding.get("canary_status") != "FAILED"
                or binding.get("canary_model_calls") != 1
                or binding.get("max_model_calls") != 1
                or binding.get("resume_action") != "CANARY"
                or binding.get("queue_status_counts") != {"FAILED": 16, "PENDING": 5, "SUCCEEDED": 24}
                or binding.get("canary_validation") != {
                    "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                    "key": FAILED_DISPATCH_CANARY_REENTRY_KEY,
                    "payload_sha256": FAILED_DISPATCH_CANARY_REENTRY_CANARY_PAYLOAD_SHA256,
                    "raw_sha256": FAILED_DISPATCH_CANARY_REENTRY_CANARY_RAW_SHA256,
                    "status": "LEGACY_FAILED_FIXED_FIELDS"}):
            raise JobConflict("RESUME_C039_REENTRY_SOURCE_BINDING_UNVERIFIED")

        result_resume = result_value.get("resume") if isinstance(result_value, dict) else None
        if (not isinstance(result_value, dict)
                or result_value.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result_value.get("job_id") != source_job_id
                or result_value.get("target_trade_date") != target_date
                or result_value.get("state") != "PARTIAL"
                or not isinstance(result_resume, dict)
                or result_resume.get("mode") != "FROZEN_BATCH"
                or result_resume.get("resume_action") != "CANARY"
                or result_resume.get("canary_passed") is not False
                or result_resume.get("canary_key") is not None
                or result_resume.get("canary_status") is not None
                or result_resume.get("canary_model_calls") != 0
                or result_resume.get("canary_validation") != {
                    "failure_code": "FROZEN_RESUME_CANARY_NOT_SUCCEEDED",
                    "key": None, "status": "FAIL"}
                or result_resume.get("max_model_calls") != 1
                or result_resume.get("model_calls") != 1
                or result_resume.get("dispatched_keys") != [
                    FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY]
                or result_resume.get("source_job_id") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID
                or result_resume.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256
                or result_resume.get("source_input_sha256_binding")
                != FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256
                or result_resume.get("initial_part_status_counts")
                != {"failed": 16, "pending": 5, "succeeded": 24}
                or result_resume.get("initial_part_total") != 45
                or result_resume.get("failed_preserved") != 16
                or result_resume.get("succeeded_preserved") != 24
                or result_resume.get("pending_eligible") != 0
                or result_resume.get("recoverable_orphan_count") != 0
                or result_resume.get("continue_eligible") is not False):
            raise JobConflict("RESUME_C039_REENTRY_RESULT_UNVERIFIED")

        # Re-evaluate 2998 against the current queue and saved 07bf root artifacts. The
        # reconstruction above binds the unchanged frozen announcement queue while allowing
        # only verified, post-c039 PDF queue additions; the full current SHA remains bound.
        parent_snapshot = self._resume_source_artifacts(
            FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID, target_date,
            {"source_input_sha256": FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256,
             "source_progress_sha256": FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256,
             "source_queue_state_sha256": hashes["source_queue_state_sha256"]})
        for field in ("mode", "source_job_id", "target_date", "source_input_sha256",
                      "source_progress_sha256", "source_result_sha256", "capture_product_sha256",
                      "canary_key", "canary_status", "canary_passed", "canary_model_calls",
                      "queue_status_counts"):
            if binding.get(field) != parent_snapshot.get(field):
                raise JobConflict("RESUME_C039_REENTRY_PARENT_CHAIN_UNVERIFIED")
        if (parent_snapshot.get("legacy_failed_canary") != binding.get("legacy_failed_canary")
                or parent_snapshot.get("legacy_failed_canary", {}).get("key")
                != FAILED_DISPATCH_CANARY_REENTRY_KEY
                or parent_snapshot.get("legacy_failed_canary", {}).get("source_part_key")
                != FAILED_DISPATCH_CANARY_REENTRY_SOURCE_PART_KEY
                or parent_snapshot.get("legacy_failed_canary", {}).get("part_descriptor", {}).get("part_index")
                != FAILED_DISPATCH_CANARY_REENTRY_PART_INDEX
                or parent_snapshot.get("legacy_failed_canary", {}).get("part_descriptor", {}).get("part_count")
                != FAILED_DISPATCH_CANARY_REENTRY_PART_COUNT):
            raise JobConflict("RESUME_C039_REENTRY_TARGET_UNVERIFIED")

        jobs = queue_value.get("jobs") if isinstance(queue_value, dict) else None
        synthesis = jobs.get(FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY) \
            if isinstance(jobs, dict) else None
        if (not isinstance(synthesis, dict)
                or synthesis.get("queue_id") != FLASH_QUEUE_ID
                or synthesis.get("idempotency_key") != FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY
                or synthesis.get("status") != "SUCCEEDED"
                or synthesis.get("attempt_count") != 1 or synthesis.get("max_attempts") != 1
                or synthesis.get("payload_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256
                or synthesis.get("validated_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256
                or synthesis.get("raw_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256
                or synthesis.get("input_path") != f"jobs/{FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY}/input.json"
                or synthesis.get("validated_path")
                != f"jobs/{FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY}/attempt-0001.validated.json"
                or synthesis.get("raw_path")
                != f"jobs/{FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY}/attempt-0001.raw"):
            raise JobConflict("RESUME_C039_PRESERVED_SYNTHESIS_BINDING_UNVERIFIED")
        try:
            payload_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + synthesis["input_path"], max_bytes=64 * 1024 * 1024)
            validated_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + synthesis["validated_path"], max_bytes=64 * 1024 * 1024)
            raw_response = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + synthesis["raw_path"], max_bytes=8 * 1024 * 1024)
            payload = json.loads(payload_raw)
            validated = json.loads(validated_raw)
            response = json.loads(raw_response)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_C039_PRESERVED_SYNTHESIS_ARTIFACT_UNAVAILABLE") from exc
        identity = synthesis.get("identity")
        validated_rows = validated.get("results") if isinstance(validated, dict) else None
        validated_row = validated_rows[0] if isinstance(validated_rows, list) and len(validated_rows) == 1 else None
        validated_output = validated_row.get("reader_output") if isinstance(validated_row, dict) else None
        response_output = response.get("reader_output") if isinstance(response, dict) else None
        if (not isinstance(identity, dict) or _sha(_canonical(identity)) != FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY
                or _sha(payload_raw) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256
                or _sha(validated_raw) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256
                or _sha(raw_response) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256
                or {field: payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS} != identity
                or payload.get("queue_task_kind") != "announcement_reader_synthesis"
                or payload.get("stage") != "v4_manager_announcement_flash_long_body_synthesis_v1"
                or not isinstance(validated_row, dict)
                or validated_row.get("article_id") != identity.get("article_id")
                or not isinstance(validated_output, dict)
                or validated_output.get("source_sha256") != identity.get("source_sha256")
                or validated_output.get("body_sha256") != identity.get("body_sha256")
                or not isinstance(response, dict) or response.get("action") != "complete"
                or response.get("lookup_request") is not None
                or not isinstance(response_output, dict)):
            raise JobConflict("RESUME_C039_PRESERVED_SYNTHESIS_ARTIFACT_UNVERIFIED")

        return {"mode": "INITIAL_CANARY", "canary_passed": False,
                "canary_key": parent_snapshot["canary_key"],
                "canary_status": parent_snapshot["canary_status"],
                "canary_model_calls": parent_snapshot["canary_model_calls"],
                "canary_validation": parent_snapshot["canary_validation"],
                "legacy_failed_canary": parent_snapshot["legacy_failed_canary"],
                "queue_reconstruction": queue_reconstruction}

    def _transport_canary_binding(self, plan: dict[str, Any]) -> dict[str, Any]:
        failure = plan.get("failed_task")
        if not isinstance(failure, dict):
            raise JobConflict("RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
        material = {
            "schema": TRANSPORT_RECOVERY_SCHEMA,
            "source_job_id": plan.get("source_job_id"),
            "source_input_sha256": plan.get("source_input_sha256"),
            "source_result_sha256": plan.get("source_result_sha256"),
            "source_queue_state_sha256": plan.get("source_queue_state_sha256"),
            "failed_idempotency_key": failure.get("key"),
            "failed_payload_sha256": failure.get("payload_sha256"),
            "failed_identity_sha256": failure.get("identity_sha256"),
            "failed_attempt_sha256": failure.get("attempt_sha256"),
            "pending_manifest_sha256": plan.get("pending_manifest_sha256"),
        }
        return {**material, "binding_sha256": _sha(_canonical(material))}

    def _completed_transport_canary(self, source_job_id: str, target_date: str,
                                    input_value: dict[str, Any], result_value: dict[str, Any],
                                    queue_value: dict[str, Any], hashes: dict[str, str],
                                    source_root: Path, transport_recovery: Any) -> dict[str, Any]:
        from infrastructure.owned_io import SafeRoot

        resume_value = result_value.get("resume")
        validation = resume_value.get("canary_validation") if isinstance(resume_value, dict) else None
        plan = transport_recovery
        source = input_value.get("resume_source")
        root = input_value.get("resume_root")
        failure = plan.get("failed_task") if isinstance(plan, dict) else None
        pending = plan.get("pending_tasks") if isinstance(plan, dict) else None
        exact_plan_shape = (isinstance(plan, dict)
            and set(plan) == {"schema", "source_job_id", "source_input_sha256", "source_progress_sha256",
                              "source_result_sha256", "source_queue_state_sha256", "capture_product_sha256",
                              "failed_task", "pending_tasks", "pending_manifest_sha256", "queue_status_counts"}
            and plan.get("schema") == TRANSPORT_RECOVERY_SCHEMA
            and plan.get("source_job_id") == (root.get("source_job_id") if isinstance(root, dict) else None)
            and plan.get("source_input_sha256") == (root.get("source_input_sha256") if isinstance(root, dict) else None)
            and isinstance(failure, dict)
            and set(failure) == {"article_id", "key", "payload_sha256", "identity_sha256", "attempt_sha256"}
            and isinstance(pending, list) and pending
            and plan.get("pending_manifest_sha256") == _sha(_canonical(pending))
            and all(isinstance(row, dict) and set(row) == {"key", "payload_sha256", "identity_sha256"}
                    and all(re.fullmatch(r"[0-9a-f]{64}", str(row.get(field, "")))
                            for field in ("key", "payload_sha256", "identity_sha256"))
                    for row in pending)
            and pending == sorted(pending, key=lambda row: row["key"])
            and len({row["key"] for row in pending}) == len(pending)
            and isinstance(source, dict) and source.get("transport_recovery") == plan
            and source.get("source_job_id") == plan.get("source_job_id")
            and source.get("source_input_sha256") == plan.get("source_input_sha256")
            and source.get("source_progress_sha256") == plan.get("source_progress_sha256")
            and source.get("source_result_sha256") == plan.get("source_result_sha256")
            and source.get("source_queue_state_sha256") == plan.get("source_queue_state_sha256")
            and source.get("capture_product_sha256") == plan.get("capture_product_sha256"))
        if (not exact_plan_shape or source_job_id == plan.get("source_job_id")
                or result_value.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result_value.get("job_id") != source_job_id
                or result_value.get("target_trade_date") != target_date
                or result_value.get("state") != "PARTIAL"
                or not isinstance(resume_value, dict)
                or resume_value.get("mode") != "FROZEN_BATCH"
                or resume_value.get("resume_action") != "CANARY"
                or resume_value.get("source_job_id") != plan.get("source_job_id")
                or resume_value.get("transport_recovery") != plan
                or resume_value.get("canary_model_calls") != 1
                or resume_value.get("max_model_calls") != 1
                or resume_value.get("canary_passed") is not True
                or resume_value.get("canary_status") != "SUCCEEDED"
                or not isinstance(validation, dict) or validation.get("status") != "PASS"
                or validation.get("key") != resume_value.get("canary_key")
                or (isinstance(source, dict) and source.get("resume_action") == "CONTINUE")):
            raise JobConflict("RESUME_TRANSPORT_CANARY_RESULT_NOT_ELIGIBLE")
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(plan.get(field, "")))
               for field in ("source_input_sha256", "source_progress_sha256", "source_result_sha256",
                             "source_queue_state_sha256", "capture_product_sha256")):
            raise JobConflict("RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
        source_input_raw = self.service.store.io.read_bytes(
            self._job_ref(plan["source_job_id"], "input.json"), max_bytes=1024 * 1024)
        source_progress_raw = self.service.store.io.read_bytes(
            self._job_ref(plan["source_job_id"], PROGRESS_REF), max_bytes=1024 * 1024)
        source_result_raw = self.service.store.io.read_bytes(
            self._job_ref(plan["source_job_id"], RESULT_REF), max_bytes=64 * 1024 * 1024)
        try:
            original_input = json.loads(source_input_raw)
            original_result = json.loads(source_result_raw)
            capture_raw = SafeRoot(getattr(self.service.config, "capture_root", None)).read_bytes(
                input_value["capture_product"]["artifact_ref"], max_bytes=256 * 1024 * 1024)
            capture_value = json.loads(capture_raw)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_TRANSPORT_CANARY_SOURCE_UNAVAILABLE") from exc
        if (_sha(source_input_raw) != plan["source_input_sha256"]
                or _sha(source_progress_raw) != plan["source_progress_sha256"]
                or _sha(source_result_raw) != plan["source_result_sha256"]
                or _sha(capture_raw) != plan["capture_product_sha256"]
                or not isinstance(original_input, dict)
                or original_input.get("target_date") != target_date
                or original_input.get("capture_product") != input_value.get("capture_product")
                or original_input.get("membership_gate") != input_value.get("membership_gate")
                or not isinstance(original_result, dict)
                or original_result.get("system_stop", {}).get("failure_code") != "TransportError"
                or source.get("source_queue_state_sha256") != plan.get("source_queue_state_sha256")):
            raise JobConflict("RESUME_TRANSPORT_CANARY_SOURCE_BINDING_UNVERIFIED")
        jobs = queue_value.get("jobs") if isinstance(queue_value, dict) else None
        if not isinstance(jobs, dict):
            raise JobConflict("RESUME_TRANSPORT_CANARY_QUEUE_INVALID")
        failed_key = failure.get("key")
        failed_item = jobs.get(failed_key)
        if (not isinstance(failed_item, dict) or failed_item.get("status") != "FAILED"
                or failed_item.get("idempotency_key") != failed_key
                or failed_item.get("attempt_count") != 1 or failed_item.get("max_attempts") != 1
                or failed_item.get("payload_sha256") != failure.get("payload_sha256")
                or _sha(_canonical(failed_item.get("identity"))) != failure.get("identity_sha256")
                or failed_item.get("input_path") != f"jobs/{failed_key}/input.json"):
            raise JobConflict("RESUME_TRANSPORT_CANARY_FAILED_SOURCE_INVALID")
        attempts = failed_item.get("attempts")
        failed_attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
        if (not isinstance(failed_attempt, dict) or _sha(_canonical(failed_attempt)) != failure.get("attempt_sha256")
                or failed_attempt.get("status") != "FAILED" or failed_attempt.get("number") != 1
                or failed_attempt.get("error", {}).get("stage") != "executor"
                or failed_attempt.get("error", {}).get("code") != "TransportError"):
            raise JobConflict("RESUME_TRANSPORT_CANARY_FAILED_ATTEMPT_INVALID")
        capture_rows = capture_value.get("rows") if isinstance(capture_value, dict) else None
        failed_capture_row = None
        if isinstance(capture_rows, list):
            matches = [row for row in capture_rows if isinstance(row, dict)
                       and "EASTMONEY:" + str(row.get("art_code", "")) == failure.get("article_id")]
            failed_capture_row = matches[0] if len(matches) == 1 else None
        if not isinstance(failed_capture_row, dict):
            raise JobConflict("RESUME_TRANSPORT_CANARY_FAILED_CAPTURE_INVALID")
        try:
            failed_payload_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + failed_item["input_path"], max_bytes=64 * 1024 * 1024)
            failed_payload = json.loads(failed_payload_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_TRANSPORT_CANARY_FAILED_PAYLOAD_UNAVAILABLE") from exc
        if (_sha(failed_payload_raw) != failure.get("payload_sha256")
                or not self._transport_recovery_payload_matches(
                    failed_payload, failed_item, failed_capture_row, input_value, target_date)):
            raise JobConflict("RESUME_TRANSPORT_CANARY_FAILED_PAYLOAD_INVALID")
        for entry in pending:
            item = jobs.get(entry["key"])
            if (not isinstance(item, dict) or item.get("status") != "PENDING"
                    or item.get("attempt_count") != 0 or item.get("max_attempts") != 1
                    or item.get("payload_sha256") != entry["payload_sha256"]
                    or _sha(_canonical(item.get("identity"))) != entry["identity_sha256"]
                    or item.get("input_path") != f"jobs/{entry['key']}/input.json"):
                raise JobConflict("RESUME_TRANSPORT_CANARY_PENDING_TASK_CHANGED")

        canary_key = resume_value.get("canary_key")
        canary_job = jobs.get(canary_key) if isinstance(canary_key, str) else None
        if (not isinstance(canary_key, str) or not re.fullmatch(r"[0-9a-f]{64}", canary_key)
                or not isinstance(canary_job, dict) or canary_job.get("idempotency_key") != canary_key
                or canary_job.get("queue_id") != FLASH_QUEUE_ID or canary_job.get("status") != "SUCCEEDED"
                or canary_job.get("attempt_count") != 1 or canary_job.get("max_attempts") != 1
                or not isinstance(canary_job.get("identity"), dict)
                or _sha(_canonical(canary_job["identity"])) != canary_key
                or validation.get("validated_sha256") != canary_job.get("validated_sha256")
                or validation.get("raw_sha256") != canary_job.get("raw_sha256")):
            raise JobConflict("RESUME_TRANSPORT_CANARY_QUEUE_STATE_INVALID")
        canary_payload_ref = canary_job.get("input_path")
        if canary_payload_ref != f"jobs/{canary_key}/input.json":
            raise JobConflict("RESUME_TRANSPORT_CANARY_PAYLOAD_REFERENCE_INVALID")
        try:
            canary_payload_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/" + canary_payload_ref, max_bytes=64 * 1024 * 1024)
            canary_payload = json.loads(canary_payload_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_TRANSPORT_CANARY_PAYLOAD_UNAVAILABLE") from exc
        root_binding = {"source_job_id": plan["source_job_id"],
                        "source_input_sha256": plan["source_input_sha256"],
                        "target_date": target_date, "cutoff": input_value.get("cutoff"),
                        "capture_product_sha256": input_value["capture_product"]["sha256"],
                        "membership_authority_sha256": input_value.get("membership_gate", {}).get("authority_sha256")}
        expected_payload = {**failed_payload,
                            "rules": failed_payload.get("rules", "") + "+explicit-transport-resume:v1",
                            "transport_recovery_binding": self._transport_canary_binding(plan),
                            "frozen_resume_binding": root_binding}
        if (_sha(canary_payload_raw) != canary_job.get("payload_sha256")
                or _canonical(canary_payload) != _canonical(expected_payload)
                or {field: canary_payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS}
                != canary_job.get("identity")
                or validation.get("key") != canary_key
                or not re.fullmatch(r"[0-9a-f]{64}", str(validation.get("raw_sha256", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(validation.get("validated_sha256", "")))):
            raise JobConflict("RESUME_TRANSPORT_CANARY_RESULT_BINDING_UNVERIFIED")
        if self._queue_orphan_result_state(source_root / "announcement_flash" / "queue",
                                           canary_key, canary_job) != "COMPLETE":
            raise JobConflict("RESUME_TRANSPORT_CANARY_VALIDATED_RESULT_UNVERIFIED")
        return {"mode": "CONTINUE_AFTER_CANARY", "canary_passed": True,
                "canary_key": canary_key, "canary_status": "SUCCEEDED", "canary_model_calls": 1,
                "canary_validation": validation, "legacy_failed_canary": None,
                "transport_recovery": plan}

    def _completed_resume_canary(self, source_job_id: str, target_date: str,
                                 input_value: dict[str, Any], result_value: Any,
                                 queue_value: dict[str, Any], hashes: dict[str, str],
                                 source_root: Path) -> dict[str, Any]:
        """Accept a prior PASS, or bind the one legacy B5 fixed-field failure for a new contract canary."""
        from .announcement_chunks import PART_FIXED_FIELDS_CONTRACT_VERSION

        if source_job_id == FAILED_DISPATCH_CANARY_REENTRY_JOB_ID:
            return self._failed_dispatch_canary_reentry(
                source_job_id, target_date, input_value, result_value, queue_value, hashes, source_root)

        resume_value = result_value.get("resume") if isinstance(result_value, dict) else None
        validation = resume_value.get("canary_validation") if isinstance(resume_value, dict) else None
        canary_key = resume_value.get("canary_key") if isinstance(resume_value, dict) else None
        transport_recovery = resume_value.get("transport_recovery") if isinstance(resume_value, dict) else None
        if isinstance(transport_recovery, dict):
            return self._completed_transport_canary(
                source_job_id, target_date, input_value, result_value, queue_value, hashes,
                source_root, transport_recovery)
        root = input_value.get("resume_root") if isinstance(input_value, dict) else None
        root_id = root.get("source_job_id") if isinstance(root, dict) else None
        root_input_sha = root.get("source_input_sha256") if isinstance(root, dict) else None
        legacy_source = input_value.get("resume_source") if isinstance(input_value, dict) else None
        legacy_resume_keys = {
            "canary_key", "canary_passed", "canary_status", "continue_eligible", "dispatched_keys",
            "failed_preserved", "historical_success_conflicts", "initial_part_status_counts",
            "initial_part_total", "max_model_calls", "mode", "model_calls", "orphan_candidates",
            "pending_eligible", "recoverable_orphan_count", "source_input_sha256",
            "source_input_sha256_binding", "source_job_id", "succeeded_preserved",
        }
        legacy_source_keys = {
            "schema", "mode", "source_job_id", "source_input_sha256", "source_progress_sha256",
            "source_queue_state_sha256", "source_result_sha256", "capture_product_sha256",
            "queue_status_counts", "canary_passed", "max_model_calls", "target_date",
        }
        legacy_result_shape = (
            isinstance(result_value, dict)
            and result_value.get("schema") == "v4.manager_workbench.announcement_flash_result.v1"
            and result_value.get("job_id") == source_job_id
            and result_value.get("target_trade_date") == target_date
            and result_value.get("state") == "PARTIAL"
            and isinstance(resume_value, dict)
            and set(resume_value) == legacy_resume_keys
            and resume_value.get("mode") == "FROZEN_BATCH"
            and "resume_action" not in resume_value
            and "canary_model_calls" not in resume_value
            and "canary_validation" not in resume_value
            and resume_value.get("canary_passed") is False
            and resume_value.get("canary_status") == "FAILED"
            and resume_value.get("model_calls") == 1
            and resume_value.get("max_model_calls") == 1
            and resume_value.get("source_job_id") == root_id
            and resume_value.get("source_input_sha256") == root_input_sha
            and resume_value.get("source_input_sha256_binding") == root_input_sha
            and isinstance(canary_key, str) and re.fullmatch(r"[0-9a-f]{64}", canary_key)
            and resume_value.get("dispatched_keys") == [canary_key]
            and resume_value.get("initial_part_status_counts") == {
                "failed": 15, "pending": 5, "running": 1, "succeeded": 24}
            and resume_value.get("initial_part_total") == 45
            and resume_value.get("succeeded_preserved") == 24
            and resume_value.get("failed_preserved") == 15
            and resume_value.get("pending_eligible") == 0
            and resume_value.get("recoverable_orphan_count") == 0
            and resume_value.get("continue_eligible") is False
            and type(resume_value.get("historical_success_conflicts")) is int
            and resume_value.get("historical_success_conflicts") >= 0
            and isinstance(resume_value.get("orphan_candidates"), list)
            and len(resume_value["orphan_candidates"]) == 1
            and isinstance(resume_value["orphan_candidates"][0], dict)
            and set(resume_value["orphan_candidates"][0]) == {
                "attempt_count", "binding_sha256", "idempotency_key", "source_idempotency_key", "status"}
            and resume_value["orphan_candidates"][0].get("idempotency_key") == canary_key
            and resume_value["orphan_candidates"][0].get("attempt_count") == 0
            and resume_value["orphan_candidates"][0].get("status") == "PENDING"
            and re.fullmatch(r"[0-9a-f]{64}", str(
                resume_value["orphan_candidates"][0].get("source_idempotency_key", "")))
            and re.fullmatch(r"[0-9a-f]{64}", str(
                resume_value["orphan_candidates"][0].get("binding_sha256", "")))
            and isinstance(legacy_source, dict)
            and set(legacy_source) == legacy_source_keys
            and legacy_source.get("schema") == FROZEN_RESUME_SCHEMA
            and legacy_source.get("mode") == "INITIAL_CANARY"
            and legacy_source.get("source_job_id") == root_id
            and legacy_source.get("source_input_sha256") == root_input_sha
            and legacy_source.get("target_date") == target_date
            and legacy_source.get("source_result_sha256") is None
            and legacy_source.get("canary_passed") is False
            and legacy_source.get("max_model_calls") == 1
            and legacy_source.get("queue_status_counts") == {
                "FAILED": 15, "PENDING": 5, "RUNNING": 1, "SUCCEEDED": 24}
            and all(re.fullmatch(r"[0-9a-f]{64}", str(legacy_source.get(field, "")))
                    for field in ("source_input_sha256", "source_progress_sha256",
                                  "source_queue_state_sha256", "capture_product_sha256"))
            and legacy_source.get("source_input_sha256") == root_input_sha
            and isinstance(root_id, str) and re.fullmatch(r"[0-9a-f]{32}", root_id)
            and isinstance(root_input_sha, str) and re.fullmatch(r"[0-9a-f]{64}", root_input_sha)
        )
        canonical_result_shape = (
            isinstance(result_value, dict) and result_value.get("state") == "PARTIAL"
            and isinstance(resume_value, dict) and resume_value.get("mode") == "FROZEN_BATCH"
            and resume_value.get("resume_action") == "CANARY"
            and resume_value.get("canary_model_calls") == 1
            and resume_value.get("max_model_calls") == 1
            and isinstance(canary_key, str) and re.fullmatch(r"[0-9a-f]{64}", canary_key)
            and isinstance(validation, dict) and validation.get("key") == canary_key
        )
        if not canonical_result_shape and not legacy_result_shape:
            raise JobConflict("RESUME_COMPLETED_RESULT_NOT_ELIGIBLE")
        if legacy_result_shape:
            validation = {"status": "FAIL", "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                          "key": canary_key}
        prior_resume_input = input_value.get("resume_source")
        if isinstance(prior_resume_input, dict) and prior_resume_input.get("resume_action") == "CONTINUE":
            raise JobConflict("RESUME_CONTINUATION_ALREADY_ATTEMPTED")
        jobs = queue_value.get("jobs")
        canary_job = jobs.get(canary_key) if isinstance(jobs, dict) else None
        if not isinstance(canary_job, dict):
            raise JobConflict("RESUME_CANARY_QUEUE_STATE_UNVERIFIED")
        if resume_value.get("canary_passed") is True:
            if (resume_value.get("canary_status") != "SUCCEEDED" or validation.get("status") != "PASS"
                    or canary_job.get("idempotency_key") != canary_key
                    or canary_job.get("queue_id") != FLASH_QUEUE_ID
                    or canary_job.get("status") != "SUCCEEDED"
                    or canary_job.get("attempt_count") != 1 or canary_job.get("max_attempts") != 1
                    or not isinstance(canary_job.get("identity"), dict)
                    or _sha(_canonical(canary_job["identity"])) != canary_key):
                raise JobConflict("RESUME_CANARY_QUEUE_STATE_UNVERIFIED")
            canary_payload_ref = canary_job.get("input_path")
            if (canary_payload_ref != f"jobs/{canary_key}/input.json"
                    or not re.fullmatch(r"[0-9a-f]{64}", str(canary_job.get("payload_sha256", "")))):
                raise JobConflict("RESUME_CANARY_PAYLOAD_REFERENCE_INVALID")
            try:
                canary_payload_raw = self.service.store.io.read_bytes(
                    "announcement_flash/queue/" + canary_payload_ref, max_bytes=64 * 1024 * 1024)
                canary_payload = json.loads(canary_payload_raw)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_CANARY_PAYLOAD_UNAVAILABLE") from exc
            canary_binding = canary_payload.get("part_repair_binding") if isinstance(canary_payload, dict) else None
            root = input_value.get("resume_root")
            if (not isinstance(canary_payload, dict)
                    or _sha(canary_payload_raw) != canary_job.get("payload_sha256")
                    or {field: canary_payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS}
                    != canary_job.get("identity")
                    or canary_payload.get("queue_task_kind") != "announcement_reader_part"
                    or not isinstance(canary_binding, dict)
                    or canary_binding.get("failure_code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"
                    or canary_binding.get("binding_sha256") != validation.get("binding_sha256")
                    or canary_payload.get("frozen_resume_binding", {}).get("source_job_id")
                    != (root.get("source_job_id") if isinstance(root, dict) else source_job_id)
                    or canary_payload.get("frozen_resume_binding", {}).get("source_input_sha256")
                    != (root.get("source_input_sha256") if isinstance(root, dict) else hashes["source_input_sha256"])
                    or validation.get("validated_sha256") != canary_job.get("validated_sha256")
                    or validation.get("raw_sha256") != canary_job.get("raw_sha256")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(validation.get("validated_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(validation.get("raw_sha256", "")))):
                raise JobConflict("RESUME_CANARY_RESULT_BINDING_UNVERIFIED")
            if self._queue_orphan_result_state(source_root / "announcement_flash" / "queue",
                                               canary_key, canary_job) != "COMPLETE":
                raise JobConflict("RESUME_CANARY_VALIDATED_RESULT_UNVERIFIED")
            return {"mode": "CONTINUE_AFTER_CANARY", "canary_passed": True,
                    "canary_key": canary_key, "canary_status": "SUCCEEDED",
                    "canary_model_calls": 1, "canary_validation": validation,
                    "legacy_failed_canary": None}

        if (resume_value.get("canary_passed") is not False
                or resume_value.get("canary_status") != "FAILED"
                or validation.get("status") != "FAIL"
                or validation.get("failure_code") not in {"FROZEN_RESUME_CANARY_NOT_SUCCEEDED",
                                                            "CANARY_TEST_FAILURE",
                                                            "PART_FIXED_FIELDS_MUST_BE_EMPTY"}
                or not isinstance(legacy_source, dict)
                or legacy_source.get("mode") != "INITIAL_CANARY"
                or ((legacy_source.get("resume_action") != "CANARY")
                    and not (legacy_result_shape and "resume_action" not in legacy_source))
                or legacy_source.get("source_job_id") != root_id
                or legacy_source.get("source_input_sha256") != root_input_sha
                or (not legacy_result_shape and legacy_source.get("legacy_failed_canary") is not None)
                or not isinstance(root_id, str) or root_id == source_job_id
                or not re.fullmatch(r"[0-9a-f]{32}", root_id)
                or not re.fullmatch(r"[0-9a-f]{64}", str(root_input_sha))):
            raise JobConflict("RESUME_COMPLETED_RESULT_NOT_ELIGIBLE")
        try:
            root_input_raw = self.service.store.io.read_bytes(
                self._job_ref(root_id, "input.json"), max_bytes=1024 * 1024)
            root_input = json.loads(root_input_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_LEGACY_ROOT_INPUT_UNAVAILABLE") from exc
        if (not isinstance(root_input, dict) or _sha(root_input_raw) != root_input_sha
                or _canonical(root_input) != root_input_raw
                or root_input.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or root_input.get("job_id") != root_id or root_input.get("target_date") != target_date
                or root_input.get("capture_product") != input_value.get("capture_product")
                or root_input.get("membership_gate") != input_value.get("membership_gate")
                or isinstance(root_input.get("recovery_lock"), dict)):
            raise JobConflict("RESUME_LEGACY_ROOT_INPUT_BINDING_UNVERIFIED")
        if legacy_result_shape:
            progress_ref = self._job_ref(root_id, PROGRESS_REF)
            try:
                root_progress_raw = self.service.store.io.read_bytes(progress_ref, max_bytes=1024 * 1024)
            except (OSError, ValueError) as exc:
                raise JobConflict("RESUME_LEGACY_ROOT_PROGRESS_UNAVAILABLE") from exc
            if (_sha(root_progress_raw) != legacy_source.get("source_progress_sha256")
                    or legacy_source.get("capture_product_sha256")
                    != root_input.get("capture_product", {}).get("sha256")):
                raise JobConflict("RESUME_LEGACY_ROOT_SNAPSHOT_BINDING_UNVERIFIED")
        if (canary_job.get("idempotency_key") != canary_key
                or canary_job.get("queue_id") != FLASH_QUEUE_ID
                or canary_job.get("status") != "FAILED"
                or canary_job.get("attempt_count") != 1 or canary_job.get("max_attempts") != 1
                or not isinstance(canary_job.get("identity"), dict)
                or _sha(_canonical(canary_job["identity"])) != canary_key):
            raise JobConflict("RESUME_LEGACY_CANARY_QUEUE_STATE_UNVERIFIED")
        payload_ref = canary_job.get("input_path")
        payload_sha = canary_job.get("payload_sha256")
        raw_ref = canary_job.get("raw_path")
        raw_sha = canary_job.get("raw_sha256")
        attempts = canary_job.get("attempts")
        attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
        error = attempt.get("error") if isinstance(attempt, dict) else None
        if (payload_ref != f"jobs/{canary_key}/input.json"
                or raw_ref != f"jobs/{canary_key}/attempt-0001.raw"
                or not re.fullmatch(r"[0-9a-f]{64}", str(payload_sha))
                or not re.fullmatch(r"[0-9a-f]{64}", str(raw_sha))
                or not isinstance(attempt, dict) or attempt.get("status") != "FAILED"
                or attempt.get("raw_path") != raw_ref
                or attempt.get("raw_sha256") != raw_sha
                or not isinstance(error, dict) or error.get("stage") != "validator"
                or error.get("code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"):
            raise JobConflict("RESUME_LEGACY_CANARY_FAILURE_NOT_EXACT")
        try:
            payload_raw = self.service.store.io.read_bytes("announcement_flash/queue/" + payload_ref,
                                                           max_bytes=64 * 1024 * 1024)
            raw_response = self.service.store.io.read_bytes("announcement_flash/queue/" + raw_ref,
                                                           max_bytes=8 * 1024 * 1024)
            payload = json.loads(payload_raw)
            envelope = json.loads(raw_response)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise JobConflict("RESUME_LEGACY_CANARY_ARTIFACT_UNAVAILABLE") from exc
        expected_root = {"source_job_id": root_id, "source_input_sha256": root_input_sha}
        fixed = envelope.get("reader_output") if isinstance(envelope, dict) else None
        legacy_source_part_key = None
        if legacy_result_shape:
            recovery = payload.get("interrupted_attempt_recovery") if isinstance(payload, dict) else None
            source_part_key = (resume_value["orphan_candidates"][0].get("source_idempotency_key")
                               if isinstance(resume_value.get("orphan_candidates"), list)
                               and len(resume_value["orphan_candidates"]) == 1
                               and isinstance(resume_value["orphan_candidates"][0], dict) else None)
            source_jobs = jobs if isinstance(jobs, dict) else {}
            source_item = source_jobs.get(source_part_key) if isinstance(source_part_key, str) else None
            if (not isinstance(recovery, dict)
                    or set(recovery) != {"schema", "source_idempotency_key", "source_job_id",
                                         "source_input_sha256", "source_payload_sha256",
                                         "source_attempt_count", "chunk_plan_sha256", "part_sha256",
                                         "source_unit_map_sha256"}
                    or recovery.get("schema") != "v4.manager_workbench.announcement_flash_orphan_recovery.v1"
                    or recovery.get("source_idempotency_key") != source_part_key
                    or recovery.get("source_job_id") != root_id
                    or recovery.get("source_input_sha256") != root_input_sha
                    or type(recovery.get("source_attempt_count")) is not int
                    or recovery.get("source_attempt_count") != 1
                    or not isinstance(source_item, dict)
                    or source_item.get("idempotency_key") != source_part_key
                    or source_item.get("queue_id") != FLASH_QUEUE_ID
                    or source_item.get("status") != "FAILED"
                    or source_item.get("attempt_count") != 1 or source_item.get("max_attempts") != 1
                    or not isinstance(source_item.get("identity"), dict)
                    or _sha(_canonical(source_item["identity"])) != source_part_key):
                raise JobConflict("RESUME_LEGACY_ORPHAN_SOURCE_BINDING_UNVERIFIED")
            source_attempts = source_item.get("attempts")
            source_attempt = source_attempts[0] if isinstance(source_attempts, list) and len(source_attempts) == 1 else None
            source_error = source_attempt.get("error") if isinstance(source_attempt, dict) else None
            source_payload_ref = source_item.get("input_path")
            if (not isinstance(source_attempt, dict) or source_attempt.get("status") != "INTERRUPTED"
                    or source_attempt.get("number") != 1
                    or not isinstance(source_error, dict) or source_error.get("stage") != "recovery"
                    or source_error.get("code") != "PROCESS_INTERRUPTED"
                    or source_item.get("raw_path") is not None or source_item.get("raw_sha256") is not None
                    or source_payload_ref != f"jobs/{source_part_key}/input.json"
                    or source_item.get("payload_sha256") != recovery.get("source_payload_sha256")):
                raise JobConflict("RESUME_LEGACY_ORPHAN_SOURCE_BINDING_UNVERIFIED")
            try:
                source_payload_raw = self.service.store.io.read_bytes(
                    "announcement_flash/queue/" + source_payload_ref, max_bytes=64 * 1024 * 1024)
                source_payload = json.loads(source_payload_raw)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_LEGACY_ORPHAN_SOURCE_UNAVAILABLE") from exc
            source_identity = source_item.get("identity")
            expected_orphan_payload = dict(source_payload) if isinstance(source_payload, dict) else {}
            if isinstance(source_payload, dict):
                expected_orphan_payload["rules"] = source_payload.get("rules", "") + "+explicit-orphan-resume:v1"
                expected_orphan_payload["stage"] = "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"
                expected_orphan_payload["interrupted_attempt_recovery"] = recovery
            plan_sha = payload.get("chunk_plan_sha256") if isinstance(payload, dict) else None
            article_id = payload.get("article_id") if isinstance(payload, dict) else None
            plan_ref = (f"announcement_flash/jobs/{root_id}/long-body/"
                        f"{article_id.replace(':', '_')}-{plan_sha}.json"
                        if isinstance(article_id, str) and isinstance(plan_sha, str) else None)
            try:
                plan_raw = (self.service.store.io.read_bytes(plan_ref, max_bytes=64 * 1024 * 1024)
                            if isinstance(plan_ref, str) else b"")
                plan = json.loads(plan_raw)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_LEGACY_ROOT_PLAN_UNAVAILABLE") from exc
            part = payload.get("part_descriptor") if isinstance(payload, dict) else None
            plan_material = {key: value for key, value in plan.items() if key != "plan_sha256"} \
                if isinstance(plan, dict) else {}
            plan_matches = [item for item in plan.get("parts", [])
                            if isinstance(item, dict) and item == part] if isinstance(plan, dict) else []
            capture_ref = root_input.get("capture_product") if isinstance(root_input, dict) else None
            try:
                from infrastructure.owned_io import SafeRoot
                capture_root = getattr(self.service.config, "capture_root", None)
                capture_io = SafeRoot(capture_root) if capture_root else None
                capture_raw = (capture_io.read_bytes(capture_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
                               if capture_io is not None and isinstance(capture_ref, dict) else b"")
                capture_value = json.loads(capture_raw)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise JobConflict("RESUME_LEGACY_ROOT_CAPTURE_UNAVAILABLE") from exc
            capture_rows = capture_value.get("rows") if isinstance(capture_value, dict) else None
            capture_matches = [row for row in capture_rows if isinstance(row, dict)
                               and "EASTMONEY:" + str(row.get("art_code", "")) == article_id
                               and row.get("body_complete") is True
                               and row.get("source_sha256") == payload.get("source_sha256")
                               and row.get("body_text_sha256") == payload.get("body_sha256")
                               and row.get("body_artifact_ref") == f"products/{payload.get('source_sha256')}.json"
                               and row.get("publication_date") == payload.get("date")] \
                if isinstance(capture_rows, list) else []
            if (not isinstance(source_payload, dict) or _sha(source_payload_raw) != source_item.get("payload_sha256")
                    or {field: source_payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS} != source_identity
                    or source_payload.get("stage") != FLASH_PART_STAGE
                    or source_payload.get("queue_task_kind") != "announcement_reader_part"
                    or source_payload.get("article_id") != payload.get("article_id")
                    or source_payload.get("source_sha256") != payload.get("source_sha256")
                    or source_payload.get("body_sha256") != payload.get("body_sha256")
                    or source_payload.get("chunk_plan_sha256") != payload.get("chunk_plan_sha256")
                    or source_payload.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
                    or source_payload.get("part_descriptor") != part
                    or _sha(payload_raw) != payload_sha
                    or {key: value for key, value in payload.items() if key != "interrupted_attempt_recovery"}
                    != {key: value for key, value in expected_orphan_payload.items()
                        if key != "interrupted_attempt_recovery"}
                    or recovery.get("chunk_plan_sha256") != plan_sha
                    or recovery.get("part_sha256") != (part.get("part_sha256") if isinstance(part, dict) else None)
                    or recovery.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
                    or resume_value["orphan_candidates"][0].get("binding_sha256")
                    != _sha(_canonical(recovery))
                    or not isinstance(plan, dict)
                    or plan.get("schema") != "v4.manager_workbench.announcement_chunk_plan.v1"
                    or plan.get("plan_sha256") != plan_sha
                    or _sha(_canonical(plan_material)) != plan_sha
                    or plan.get("article_id") != article_id
                    or plan.get("source_sha256") != payload.get("source_sha256")
                    or plan.get("body_sha256") != payload.get("body_sha256")
                    or plan.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
                    or plan_ref != f"announcement_flash/jobs/{root_id}/long-body/"
                    f"{str(article_id).replace(':', '_')}-{plan_sha}.json"
                    or len(plan_matches) != 1
                    or not isinstance(capture_ref, dict)
                    or _sha(capture_raw) != capture_ref.get("sha256")
                    or capture_value.get("source") != "EASTMONEY_HK"
                    or str(capture_value.get("target_trade_date", "")).replace("-", "") != target_date
                    or len(capture_matches) != 1):
                raise JobConflict("RESUME_LEGACY_ORPHAN_SOURCE_BINDING_UNVERIFIED")
            legacy_source_part_key = source_part_key
        if (not isinstance(payload, dict) or _sha(payload_raw) != payload_sha
                or {field: payload.get(field) for field in FLASH_QUEUE_IDENTITY_FIELDS}
                != canary_job.get("identity")
                or payload.get("queue_task_kind") != "announcement_reader_part"
                or payload.get("stage") not in {"v4_manager_announcement_flash_long_body_part_v1",
                                                 "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"}
                or f"+fixed-fields-contract:{PART_FIXED_FIELDS_CONTRACT_VERSION}" in str(payload.get("rules", ""))
                or (not legacy_result_shape and (
                    payload.get("frozen_resume_binding", {}).get("source_job_id") != root_id
                    or payload.get("frozen_resume_binding", {}).get("source_input_sha256") != root_input_sha))
                or (legacy_result_shape and (payload.get("stage") !=
                    "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"
                    or payload.get("frozen_resume_binding") is not None))
                or not isinstance(fixed, dict)
                or envelope.get("action") != "complete" or envelope.get("lookup_request") is not None
                or not isinstance(fixed.get("facts"), list) or not isinstance(fixed.get("changes"), list)
                or (fixed.get("facts") == [] and fixed.get("changes") == [])
                or _sha(raw_response) != raw_sha):
            raise JobConflict("RESUME_LEGACY_CANARY_SOURCE_BINDING_UNVERIFIED")
        return {"mode": "INITIAL_CANARY", "canary_passed": False,
                "canary_key": canary_key, "canary_status": "FAILED", "canary_model_calls": 1,
                "canary_validation": {"status": "LEGACY_FAILED_FIXED_FIELDS",
                                      "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                                      "key": canary_key, "payload_sha256": payload_sha,
                                      "raw_sha256": raw_sha},
                "legacy_failed_canary": {"key": canary_key, "payload_sha256": payload_sha,
                                          "raw_sha256": raw_sha, "source_job_id": source_job_id,
                                          "source_input_sha256": hashes["source_input_sha256"],
                                          "root_job_id": root_id, "root_input_sha256": root_input_sha,
                                          "article_id": payload.get("article_id"),
                                          "source_sha256": payload.get("source_sha256"),
                                          "body_sha256": payload.get("body_sha256"),
                                          "chunk_plan_sha256": payload.get("chunk_plan_sha256"),
                                          "source_unit_map_sha256": payload.get("source_unit_map_sha256"),
                                          "part_descriptor": payload.get("part_descriptor"),
                                          **({"source_part_key": legacy_source_part_key}
                                             if isinstance(legacy_source_part_key, str) else {})}}

    def resume_snapshot(self, target_date: str) -> dict[str, Any]:
        day = validate_date(target_date)
        latest = self.service.store.cursor("announcement_flash_latest")
        if (not isinstance(latest, dict) or latest.get("target_date") != day
                or not isinstance(latest.get("job_id"), str)
                or not JOB_ID_RE.fullmatch(latest["job_id"])):
            return {"schema": FROZEN_RESUME_SCHEMA, "status": "UNAVAILABLE", "eligible": False,
                    "reason": "LATEST_ANNOUNCEMENT_JOB_MISSING"}
        source_job_id = latest["job_id"]
        expected = None
        ignore_active_job_id = None
        try:
            if source_job_id == FAILED_CANARY_REENTRY_JOB_ID:
                failed_request = self._failed_canary_reentry_request(source_job_id, day)
                source_job_id = failed_request["source_job_id"]
                expected = {key: failed_request[key] for key in
                            ("source_input_sha256", "source_progress_sha256", "source_queue_state_sha256")}
                ignore_active_job_id = FAILED_CANARY_REENTRY_JOB_ID
            snapshot = self._resume_source_artifacts(source_job_id, day, expected,
                                                     ignore_active_job_id=ignore_active_job_id)
            if expected is not None:
                wrapper_job = self.service.jobs.get(FAILED_CANARY_REENTRY_JOB_ID)
                binding = wrapper_job.context.scope_refs["announcement_flash_resume"]
                for key in ("mode", "source_job_id", "target_date", "capture_product_sha256",
                            "source_result_sha256", "canary_key", "canary_status", "canary_model_calls",
                            "canary_passed", "canary_validation", "legacy_failed_canary", "resume_action",
                            "max_model_calls", "queue_status_counts"):
                    if snapshot.get(key) != binding.get(key):
                        raise JobConflict("RESUME_FAILED_WRAPPER_SOURCE_BINDING_UNVERIFIED")
            snapshot.pop("source_input", None)
            return snapshot
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, JobConflict) as exc:
            code = _safe_code(str(exc), "RESUME_SOURCE_UNAVAILABLE")
            return {"schema": FROZEN_RESUME_SCHEMA, "status": "BLOCKED", "eligible": False,
                    "source_job_id": source_job_id, "target_date": day, "reason": code}

    def start_resume(self, target_date: str, source_job_id: str,
                     source_input_sha256: str, source_progress_sha256: str,
                     source_queue_state_sha256: str, resume_action: str):
        day = validate_date(target_date)
        if resume_action not in {"CANARY", "CONTINUE"}:
            raise ValueError("RESUME_ACTION_INVALID")
        expected = {"source_input_sha256": source_input_sha256,
                    "source_progress_sha256": source_progress_sha256,
                    "source_queue_state_sha256": source_queue_state_sha256}
        if (not JOB_ID_RE.fullmatch(str(source_job_id))
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in expected.values())):
            raise ValueError("RESUME_REQUEST_BINDING_INVALID")
        base_request_binding = {"source_job_id": source_job_id, "target_date": day,
                                "resume_action": resume_action, **expected}
        with self.service.store.lock("announcement_flash_submit"):
            latest = self.service.store.cursor("announcement_flash_latest")
            if (not isinstance(latest, dict) or latest.get("target_date") != day
                    or not isinstance(latest.get("job_id"), str)
                    or not JOB_ID_RE.fullmatch(latest["job_id"])):
                raise JobConflict("RESUME_SOURCE_NOT_LATEST")

            request_binding = base_request_binding
            reentry_from_job_id = None
            latest_job_id = latest["job_id"]
            if latest_job_id == FAILED_CANARY_REENTRY_JOB_ID:
                failed_request = self._failed_canary_reentry_request(latest_job_id, day)
                original_request = {key: value for key, value in failed_request.items()
                                    if not key.startswith("_")}
                if original_request != base_request_binding or resume_action != "CANARY":
                    raise JobConflict("RESUME_FAILED_WRAPPER_REQUEST_MISMATCH")
                reentry_from_job_id = latest_job_id
                request_binding = {**base_request_binding,
                                   "reentry_from_job_id": reentry_from_job_id,
                                   "reentry_contract": FAILED_CANARY_REENTRY_CONTRACT,
                                   "reentry_evidence_sha256": failed_request["_reentry_evidence_sha256"]}
            elif latest_job_id != source_job_id:
                try:
                    latest_job = self.service.jobs.get(latest_job_id)
                except (KeyError, OSError, ValueError):
                    raise JobConflict("RESUME_LATEST_JOB_UNAVAILABLE") from None
                latest_context = getattr(latest_job, "context", None)
                latest_scope = getattr(latest_context, "scope_refs", {})
                latest_request = (latest_scope.get("announcement_flash_resume_request")
                                  if isinstance(latest_scope, dict) else None)
                base_keys = set(base_request_binding)
                reentry_keys = {"reentry_from_job_id", "reentry_contract", "reentry_evidence_sha256"}
                if (not isinstance(latest_scope, dict)
                        or latest_scope.get("capture_operation") != FROZEN_RESUME_OPERATION
                        or getattr(latest_context, "target_date", None) != day
                        or not isinstance(latest_request, dict)
                        or frozenset(latest_request) not in {frozenset(base_keys),
                                                            frozenset(base_keys | reentry_keys)}
                        or any(latest_request.get(key) != value for key, value in base_request_binding.items())):
                    raise JobConflict("RESUME_SOURCE_NOT_LATEST")
                marker = latest_request.get("reentry_from_job_id")
                if marker is not None:
                    failed_request = self._failed_canary_reentry_request(FAILED_CANARY_REENTRY_JOB_ID, day)
                    if (marker != FAILED_CANARY_REENTRY_JOB_ID
                            or latest_request.get("reentry_contract") != FAILED_CANARY_REENTRY_CONTRACT
                            or latest_request.get("reentry_evidence_sha256")
                            != failed_request.get("_reentry_evidence_sha256")):
                        raise JobConflict("RESUME_REENTRY_MARKER_UNVERIFIED")
                    reentry_from_job_id = marker
                    request_binding = dict(latest_request)

            slot_key = "announcement_flash_resume_" + digest(request_binding)
            prior = self.service.store.cursor(slot_key)
            if prior is not None:
                if (not isinstance(prior, dict) or not isinstance(prior.get("job_id"), str)
                        or not JOB_ID_RE.fullmatch(prior["job_id"])):
                    raise JobConflict("RESUME_CURSOR_INVALID")
                try:
                    prior_job = self.service.jobs.get(prior["job_id"])
                except (KeyError, OSError, ValueError):
                    raise JobConflict("RESUME_CURSOR_JOB_MISSING") from None
                prior_scope = getattr(prior_job.context, "scope_refs", {})
                if (not isinstance(prior_scope, dict)
                        or prior_scope.get("capture_operation") != FROZEN_RESUME_OPERATION
                        or prior_scope.get("announcement_flash_resume_request") != request_binding
                        or getattr(prior_job.context, "target_date", None) != day):
                    raise JobConflict("RESUME_CURSOR_IDENTITY_INVALID")
                return prior_job

            if latest_job_id != source_job_id and reentry_from_job_id is None:
                raise JobConflict("RESUME_SOURCE_NOT_LATEST")
            artifacts = self._resume_source_artifacts(
                source_job_id, day, expected,
                ignore_active_job_id=FAILED_CANARY_REENTRY_JOB_ID if reentry_from_job_id else None)
            if artifacts.get("resume_action") != resume_action:
                raise JobConflict("RESUME_ACTION_NOT_ELIGIBLE")
            if self._active_flash_attempts(
                    ignore_job_id=FAILED_CANARY_REENTRY_JOB_ID if reentry_from_job_id else None):
                raise JobConflict("ANNOUNCEMENT_FLASH_BUSY_ALL_TARGET_DATES")
            source_input = artifacts["source_input"]
            cutoff = artifacts.get("source_cutoff")
            if not isinstance(cutoff, str) or not cutoff:
                cutoff = source_input.get("cutoff")
            if not isinstance(cutoff, str) or not cutoff:
                raise JobConflict("RESUME_SOURCE_CUTOFF_UNAVAILABLE")
            prior_root = source_input.get("resume_root")
            if (isinstance(prior_root, dict)
                    and isinstance(prior_root.get("source_job_id"), str)
                    and JOB_ID_RE.fullmatch(prior_root["source_job_id"])
                    and isinstance(prior_root.get("source_input_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", prior_root["source_input_sha256"])):
                resume_root = deepcopy(prior_root)
            else:
                resume_root = {"source_job_id": source_job_id,
                               "source_input_sha256": artifacts["source_input_sha256"]}
            binding = {key: value for key, value in artifacts.items()
                       if key in {"schema", "mode", "source_job_id", "target_date", "source_input_sha256",
                                  "source_progress_sha256", "source_queue_state_sha256",
                                  "capture_product_sha256", "source_result_sha256", "canary_passed",
                                  "canary_key", "canary_status", "canary_model_calls", "canary_validation",
                                  "legacy_failed_canary", "queue_reconstruction", "resume_action",
                                  "max_model_calls", "queue_status_counts", "transport_recovery"}}
            binding["resume_root"] = resume_root
            binding["source_result_sha256"] = artifacts.get("source_result_sha256")
            context = RunContext(
                target_date=day, phase=Phase.MANUAL, cutoff=cutoff, trigger="MANUAL",
                rules_version="V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1",
                scope_refs={"requested_lanes": [],
                            "capture_operation": FROZEN_RESUME_OPERATION,
                            "capture_input_sha256": digest(binding),
                            "announcement_flash_resume": binding,
                            "announcement_flash_resume_request": request_binding},
            )
            job = self.service.jobs.submit(context, self._work)
            if job.job_id == source_job_id:
                raise JobConflict("RESUME_NEW_JOB_REQUIRED")
            cursor = {"job_id": job.job_id, "target_date": day, "slot": cutoff,
                      "state": job.state.value, "source_job_id": source_job_id,
                      "resume_mode": artifacts["mode"],
                      "resume_action": resume_action,
                      "source_input_sha256": source_input_sha256,
                      "source_progress_sha256": source_progress_sha256,
                      "source_queue_state_sha256": source_queue_state_sha256}
            self.service.store.set_cursor(slot_key, cursor)
            self.service.store.set_cursor("announcement_flash_latest", cursor)
            return job

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ANNOUNCEMENT_UPDATE_CLOCK_MUST_BE_AWARE")
        return value.astimezone(HK)

    def _queue_identity_failed_partial_progress_sha(self, job_id: str, target_date: str, cutoff: str,
                                                     job: Any, input_raw: bytes, input_value: dict[str, Any],
                                                     result_raw: bytes, result: dict[str, Any],
                                                     parent_hint: Any) -> str | None:
        """Verify the exact published queue-identity stop before offering same-cutoff recovery."""
        failure_code = "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
        context = getattr(job, "context", None)
        scope_refs = getattr(context, "scope_refs", {})
        failed_steps = getattr(job, "failed_steps", None)
        if (getattr(job, "state", None) != JobState.FAILED
                or getattr(job, "step", None) != "FLASH_SELECTION"
                or getattr(job, "failure_code", None) != failure_code
                or not isinstance(failed_steps, list) or "FLASH_SELECTION" not in failed_steps
                or getattr(context, "target_date", None) != target_date
                or getattr(context, "cutoff", None) != cutoff
                or not isinstance(scope_refs, dict)
                or scope_refs.get("capture_operation") != "ANNOUNCEMENT_FLASH_RECOVERY"
                or not isinstance(parent_hint, dict)
                or _canonical(input_value) != input_raw
                or input_value.get("job_id") != job_id
                or input_value.get("target_date") != target_date
                or input_value.get("cutoff") != cutoff
                or result.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result.get("job_id") != job_id or result.get("target_trade_date") != target_date
                or result.get("state") != "PARTIAL"):
            return None

        stop = result.get("system_stop")
        try:
            progress_raw = self.service.store.io.read_bytes(self._job_ref(job_id, PROGRESS_REF),
                                                            max_bytes=1024 * 1024)
            progress = json.loads(progress_raw)
        except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (not isinstance(progress, dict)
                or progress.get("step") != "FAILED" or progress.get("failure_code") != failure_code
                or not isinstance(progress.get("updated_at"), str)
                or stop != {"failure_code": failure_code, "stage": "FLASH_SELECTION",
                            "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                            "failed_at": progress.get("updated_at")}):
            return None

        lock = input_value.get("recovery_lock")
        gate = input_value.get("membership_gate")
        result_gate = result.get("membership_gate")
        if (not isinstance(lock, dict) or not isinstance(gate, dict) or not isinstance(result_gate, dict)
                or gate.get("status") != "VERIFIED" or result_gate.get("status") != "VERIFIED"
                or gate.get("target_date") != target_date or result_gate.get("target_date") != target_date
                or gate.get("cutoff") != cutoff or result_gate.get("cutoff") != cutoff
                or gate.get("authority_sha256") != result_gate.get("authority_sha256")
                or lock.get("membership_authority_sha256") != gate.get("authority_sha256")
                or not self._failed_body_binding_input_matches(input_value, job_id, target_date, cutoff,
                                                               parent_hint)):
            return None
        eligible_ids = lock.get("eligible_article_ids")
        current_bodies = lock.get("current_body_sha256")
        if (not isinstance(eligible_ids, list) or not isinstance(current_bodies, dict)
                or lock.get("eligible_article_ids_sha256") != hashlib.sha256(_canonical(eligible_ids)).hexdigest()
                or lock.get("current_body_sha256_digest") != digest(current_bodies)
                or not isinstance(lock.get("row_manifest_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", lock["row_manifest_sha256"])):
            return None
        scope_capture = parent_hint.get("capture_product")
        scope_capture = scope_capture if isinstance(scope_capture, dict) else {}
        capture_identity = {
            "recovery_parent_job_id": parent_hint.get("job_id"),
            "recovery_parent_input_sha256": parent_hint.get("input_sha256"),
            "recovery_parent_result_sha256": parent_hint.get("result_sha256"),
            "capture_product_sha256": scope_capture.get("sha256"),
            "target_date": target_date,
            "cutoff": parent_hint.get("cutoff"),
        }
        if (scope_refs.get("capture_input_sha256") != digest(capture_identity)
                or parent_hint.get("job_id") != lock.get("parent_job_id")
                or parent_hint.get("root_batch_job_id") != lock.get("root_batch_job_id")
                or parent_hint.get("input_sha256") != lock.get("parent_input_sha256")
                or parent_hint.get("result_sha256") != lock.get("parent_result_sha256")
                or parent_hint.get("membership_authority_sha256") != lock.get("membership_authority_sha256")
                or parent_hint.get("cutoff") != cutoff or parent_hint.get("target_date") != target_date
                or parent_hint.get("schema") != "v4.manager_workbench.announcement_flash_recovery_parent.v1"):
            return None

        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        queue_counts = counts.get("queue") if isinstance(counts.get("queue"), dict) else {}
        if (type(counts.get("failed")) is not int or counts["failed"] <= 0
                or type(counts.get("new_candidate_stocks")) is not int or counts["new_candidate_stocks"] < 0
                or queue_counts.get("new_enqueued") != 0 or queue_counts.get("new_model_calls_allowed") != 0):
            return None

        # Prove the whole hash-linked recovery ancestry. Saved batches can have
        # more than one continuation between the current job and the frozen root.
        try:
            previous_input_raw = self.service.store.io.read_bytes(
                self._job_ref(parent_hint["job_id"], "input.json"), max_bytes=1024 * 1024)
            previous_result_raw = self.service.store.io.read_bytes(
                self._job_ref(parent_hint["job_id"], RESULT_REF), max_bytes=64 * 1024 * 1024)
            previous_input, previous_result = json.loads(previous_input_raw), json.loads(previous_result_raw)
        except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
            return None
        previous_lock = previous_input.get("recovery_lock") if isinstance(previous_input, dict) else None
        previous_gate = previous_input.get("membership_gate") if isinstance(previous_input, dict) else None
        previous_result_gate = previous_result.get("membership_gate") if isinstance(previous_result, dict) else None
        if (not isinstance(previous_lock, dict) or not isinstance(previous_gate, dict)
                or not isinstance(previous_result_gate, dict)
                or _sha(previous_input_raw) != parent_hint.get("input_sha256")
                or _sha(previous_result_raw) != parent_hint.get("result_sha256")
                or _canonical(previous_input) != previous_input_raw
                or previous_input.get("job_id") != parent_hint.get("job_id")
                or previous_input.get("target_date") != target_date
                or previous_input.get("cutoff") != cutoff
                or previous_input.get("capture_product") != parent_hint.get("capture_product")
                or previous_result.get("job_id") != parent_hint.get("job_id")
                or previous_result.get("target_trade_date") != target_date
                or previous_result.get("state") != "PARTIAL"
                or previous_gate.get("status") != "VERIFIED"
                or previous_result_gate.get("status") != "VERIFIED"
                or previous_gate.get("authority_sha256") != lock.get("membership_authority_sha256")
                or previous_result_gate.get("authority_sha256") != lock.get("membership_authority_sha256")
                or previous_lock.get("root_batch_job_id") != lock.get("root_batch_job_id")
                or previous_lock.get("row_manifest_sha256") != lock.get("row_manifest_sha256")
                or previous_lock.get("eligible_article_ids_sha256") != lock.get("eligible_article_ids_sha256")
                or previous_lock.get("cutoff") != cutoff
                or previous_lock.get("membership_authority_sha256") != lock.get("membership_authority_sha256")
                or previous_lock.get("current_body_sha256_digest") != lock.get("current_body_sha256_digest")
                or previous_lock.get("current_body_sha256") != current_bodies
                or previous_lock.get("eligible_article_ids") != eligible_ids):
            return None
        root_id = lock.get("root_batch_job_id")
        if not isinstance(root_id, str) or not JOB_ID_RE.fullmatch(root_id):
            return None

        def same_frozen_lock(candidate: Any) -> bool:
            expected_bodies = candidate.get("expected_body_sha256") if isinstance(candidate, dict) else None
            return (isinstance(candidate, dict)
                    and candidate.get("root_batch_job_id") == root_id
                    and candidate.get("cutoff") == cutoff
                    and candidate.get("membership_authority_sha256") == lock.get("membership_authority_sha256")
                    and candidate.get("row_manifest_sha256") == lock.get("row_manifest_sha256")
                    and candidate.get("eligible_article_ids_sha256") == lock.get("eligible_article_ids_sha256")
                    and candidate.get("eligible_article_ids") == eligible_ids
                    and candidate.get("current_body_sha256_digest") == lock.get("current_body_sha256_digest")
                    and candidate.get("current_body_sha256") == current_bodies
                    and isinstance(expected_bodies, dict)
                    and set(expected_bodies).issubset(current_bodies)
                    and all(current_bodies.get(article_id) == body_sha
                            for article_id, body_sha in expected_bodies.items()))

        def valid_saved_stop(node_id: str, node_result: dict[str, Any]) -> bool:
            node_stop = node_result.get("system_stop")
            if node_stop is None:
                return True
            try:
                node_progress_raw = self.service.store.io.read_bytes(
                    self._job_ref(node_id, PROGRESS_REF), max_bytes=1024 * 1024)
                node_progress = json.loads(node_progress_raw)
            except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                return False
            node_counts = node_result.get("counts") if isinstance(node_result.get("counts"), dict) else {}
            node_queue = node_counts.get("queue") if isinstance(node_counts.get("queue"), dict) else {}
            return (isinstance(node_progress, dict)
                    and node_progress.get("step") == "FAILED"
                    and node_progress.get("failure_code") == failure_code
                    and isinstance(node_progress.get("updated_at"), str)
                    and node_stop == {"failure_code": failure_code, "stage": "FLASH_SELECTION",
                                      "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                                      "failed_at": node_progress.get("updated_at")}
                    and type(node_counts.get("failed")) is int and node_counts["failed"] > 0
                    and type(node_counts.get("new_candidate_stocks")) is int
                    and node_counts["new_candidate_stocks"] >= 0
                    and node_queue.get("new_enqueued") == 0
                    and node_queue.get("new_model_calls_allowed") == 0)

        lineage_id = parent_hint["job_id"]
        lineage_input = previous_input
        lineage_result = previous_result
        lineage_lock = previous_lock
        seen = {job_id}
        reached_root = False
        for _depth in range(16):
            if lineage_id in seen:
                return None
            seen.add(lineage_id)
            if (not isinstance(lineage_input, dict) or not isinstance(lineage_result, dict)
                    or lineage_input.get("job_id") != lineage_id
                    or lineage_input.get("target_date") != target_date
                    or lineage_input.get("cutoff") != cutoff
                    or lineage_result.get("job_id") != lineage_id
                    or lineage_result.get("target_trade_date") != target_date
                    or lineage_result.get("state") != "PARTIAL"
                    or not valid_saved_stop(lineage_id, lineage_result)):
                return None
            lineage_gate = lineage_input.get("membership_gate")
            lineage_result_gate = lineage_result.get("membership_gate")
            if (not isinstance(lineage_gate, dict) or not isinstance(lineage_result_gate, dict)
                    or lineage_gate.get("status") != "VERIFIED"
                    or lineage_result_gate.get("status") != "VERIFIED"
                    or lineage_gate.get("target_date") != target_date
                    or lineage_result_gate.get("target_date") != target_date
                    or lineage_gate.get("cutoff") != cutoff
                    or lineage_result_gate.get("cutoff") != cutoff
                    or lineage_gate.get("authority_sha256") != lock.get("membership_authority_sha256")
                    or lineage_result_gate.get("authority_sha256") != lock.get("membership_authority_sha256")):
                return None
            if lineage_id == root_id:
                if lineage_lock is not None:
                    return None
                reached_root = True
                break
            if not same_frozen_lock(lineage_lock):
                return None
            parent_id = lineage_lock.get("parent_job_id")
            if not isinstance(parent_id, str) or not JOB_ID_RE.fullmatch(parent_id):
                return None
            try:
                ancestor_input_raw = self.service.store.io.read_bytes(
                    self._job_ref(parent_id, "input.json"), max_bytes=1024 * 1024)
                ancestor_result_raw = self.service.store.io.read_bytes(
                    self._job_ref(parent_id, RESULT_REF), max_bytes=64 * 1024 * 1024)
                ancestor_input = json.loads(ancestor_input_raw)
                ancestor_result = json.loads(ancestor_result_raw)
            except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
                return None
            ancestor_capture = ancestor_input.get("capture_product") if isinstance(ancestor_input, dict) else None
            ancestor_capture_sha = ancestor_capture.get("sha256") if isinstance(ancestor_capture, dict) else None
            if (lineage_lock.get("parent_input_sha256") != _sha(ancestor_input_raw)
                    or lineage_lock.get("parent_result_sha256") != _sha(ancestor_result_raw)
                    or lineage_lock.get("parent_capture_product_sha256") != ancestor_capture_sha
                    or _canonical(ancestor_input) != ancestor_input_raw
                    or not isinstance(ancestor_input, dict)
                    or ancestor_input.get("job_id") != parent_id
                    or ancestor_input.get("target_date") != target_date
                    or ancestor_input.get("cutoff") != cutoff
                    or not isinstance(ancestor_result, dict)
                    or ancestor_result.get("job_id") != parent_id
                    or ancestor_result.get("target_trade_date") != target_date
                    or ancestor_result.get("state") != "PARTIAL"):
                return None
            lineage_id = parent_id
            lineage_input = ancestor_input
            lineage_result = ancestor_result
            lineage_lock = ancestor_input.get("recovery_lock")
        if not reached_root:
            return None
        return _sha(progress_raw)

    def _saved_raw_synthesis_failure_parent(self, job_id: str, target_date: str, latest: dict[str, Any],
                                            job: Any, input_raw: bytes, input_value: dict[str, Any],
                                            result_raw: bytes, result: dict[str, Any]
                                            ) -> dict[str, Any] | None:
        """Recognize one saved validator failure that the runner can recover without inference.

        This deliberately derives the binding from the indexed parent artifacts and queue
        evidence instead of treating a particular job or digest as a permanent exception.
        The runner still performs the actual citation normalization and full validation.
        """
        context = getattr(job, "context", None)
        active = getattr(self.service.jobs, "_active", None)
        scope_refs = getattr(context, "scope_refs", {})
        if (getattr(job, "state", None) != JobState.PARTIAL
                or getattr(job, "step", None) != "DONE"
                or not isinstance(active, dict) or job_id in active.values()
                or getattr(context, "target_date", None) != target_date
                or getattr(context, "cutoff", None) != input_value.get("cutoff")
                or not isinstance(scope_refs, dict)
                or scope_refs.get("capture_operation") != "ANNOUNCEMENT_FLASH_RECOVERY"
                or not isinstance(scope_refs.get("capture_input_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", scope_refs["capture_input_sha256"])
                or _canonical(input_value) != input_raw
                or input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != job_id
                or input_value.get("target_date") != target_date
                or not isinstance(input_value.get("cutoff"), str)
                or latest.get("state") not in {JobState.RUNNING.value, JobState.PARTIAL.value}
                or latest.get("result_sha256") != _sha(result_raw)):
            return None

        lock = input_value.get("recovery_lock")
        gate = input_value.get("membership_gate")
        result_gate = result.get("membership_gate")
        capture_ref = input_value.get("capture_product")
        if (not isinstance(lock, dict)
                or lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
                or lock.get("target_date") != target_date
                or lock.get("cutoff") != input_value.get("cutoff")
                or not isinstance(lock.get("root_batch_job_id"), str)
                or not JOB_ID_RE.fullmatch(lock["root_batch_job_id"])
                or not isinstance(lock.get("parent_job_id"), str)
                or not JOB_ID_RE.fullmatch(lock["parent_job_id"])
                or not isinstance(lock.get("membership_authority_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", lock["membership_authority_sha256"])
                or not isinstance(gate, dict) or gate.get("status") != "VERIFIED"
                or gate.get("target_date") != target_date
                or gate.get("cutoff") != input_value.get("cutoff")
                or gate.get("authority_sha256") != lock.get("membership_authority_sha256")
                or not isinstance(result_gate, dict) or result_gate.get("status") != "VERIFIED"
                or result_gate.get("target_date") != target_date
                or result_gate.get("cutoff") != input_value.get("cutoff")
                or result_gate.get("authority_sha256") != lock.get("membership_authority_sha256")
                or not isinstance(capture_ref, dict)
                or capture_ref.get("sha256") != lock.get("capture_product_sha256")
                or not isinstance(capture_ref.get("artifact_ref"), str)
                or capture_ref.get("artifact_ref") != f"products/{capture_ref.get('sha256')}.json"):
            return None

        parent_hint = scope_refs.get("announcement_recovery_parent")
        hinted_capture = parent_hint.get("capture_product") if isinstance(parent_hint, dict) else None
        if (not isinstance(parent_hint, dict)
                or parent_hint.get("schema") != "v4.manager_workbench.announcement_flash_recovery_parent.v1"
                or parent_hint.get("job_id") != lock.get("parent_job_id")
                or parent_hint.get("root_batch_job_id") != lock.get("root_batch_job_id")
                or parent_hint.get("input_sha256") != lock.get("parent_input_sha256")
                or parent_hint.get("result_sha256") != lock.get("parent_result_sha256")
                or parent_hint.get("target_date") != target_date
                or parent_hint.get("cutoff") != input_value.get("cutoff")
                or parent_hint.get("membership_authority_sha256") != lock.get("membership_authority_sha256")
                or not isinstance(hinted_capture, dict)
                or hinted_capture.get("sha256") != lock.get("parent_capture_product_sha256")):
            return None
        capture_identity = {
            "recovery_parent_job_id": parent_hint["job_id"],
            "recovery_parent_input_sha256": parent_hint["input_sha256"],
            "recovery_parent_result_sha256": parent_hint["result_sha256"],
            "capture_product_sha256": hinted_capture["sha256"],
            "target_date": target_date,
            "cutoff": input_value["cutoff"],
        }
        if scope_refs.get("capture_input_sha256") != digest(capture_identity):
            return None

        try:
            progress_raw = self.service.store.io.read_bytes(self._job_ref(job_id, PROGRESS_REF),
                                                            max_bytes=1024 * 1024)
            progress = json.loads(progress_raw)
            queue_state_raw = self.service.store.io.read_bytes(
                "announcement_flash/queue/queue-state.json", max_bytes=64 * 1024 * 1024)
            queue_state = json.loads(queue_state_raw)
        except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (not isinstance(progress, dict) or progress.get("step") != "DONE"
                or progress.get("result_state") != "PARTIAL"
                or not isinstance(progress.get("updated_at"), str)
                or not isinstance(queue_state, dict) or not isinstance(queue_state.get("jobs"), dict)):
            return None
        try:
            progress_updated_at = datetime.fromisoformat(progress["updated_at"])
            result_updated_at = datetime.fromisoformat(str(result.get("updated_at", "")))
        except ValueError:
            return None
        if (progress_updated_at.tzinfo is None or result_updated_at.tzinfo is None
                or result_updated_at > progress_updated_at
                or progress_updated_at - result_updated_at > timedelta(seconds=60)):
            return None

        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        membership_counts = counts.get("membership_articles") if isinstance(counts.get("membership_articles"), dict) else {}
        queue_counts = counts.get("queue") if isinstance(counts.get("queue"), dict) else {}
        if (result.get("state") != "PARTIAL"
                or result.get("system_stop") is not None
                or ("saved_raw_recoveries" in result
                    and not isinstance(result.get("saved_raw_recoveries"), list))
                or result.get("job_id") != job_id
                or result.get("target_trade_date") != target_date
                or type(lock.get("eligible_count")) is not int
                or membership_counts.get("in") != lock["eligible_count"]
                or queue_counts.get("failed") != 1
                or counts.get("queue_pending") != 0
                or counts.get("context_pending") != 0
                or queue_counts.get("long_body_synthesis_pending") != 0):
            return None

        long_body = result.get("long_body_processing")
        long_items = long_body.get("items") if isinstance(long_body, dict) else None
        if not isinstance(long_items, list):
            return None
        failed_syntheses = [item for item in long_items if isinstance(item, dict)
                            and item.get("status") in {"SYNTHESIS_FAILED",
                                                       "SAVED_RAW_RECOVERED_ORIGINAL_FAILURE_PRESERVED"}
                            and isinstance(item.get("synthesis"), dict)
                            and item["synthesis"].get("status") == "FAILED"]
        if len(failed_syntheses) != 1:
            return None
        summary = failed_syntheses[0]
        article_id = summary.get("article_id")
        synthesis = summary.get("synthesis")
        synthesis_input_sha = synthesis.get("input_sha256")
        if (not isinstance(article_id, str) or not article_id
                or not isinstance(synthesis_input_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", synthesis_input_sha)):
            return None

        saved_rows = result.get("saved_raw_recoveries", [])
        trace_row = None
        if saved_rows:
            if len(saved_rows) != 1 or summary.get("status") != "SAVED_RAW_RECOVERED_ORIGINAL_FAILURE_PRESERVED":
                return None
            trace_row = saved_rows[0]
            if (not isinstance(trace_row, dict) or trace_row.get("article_id") != article_id
                    or "validated_result" in trace_row
                    or "validated_result_sha256" in trace_row
                    or "publication_status" in trace_row
                    or synthesis.get("status") != "FAILED"
                    or synthesis.get("validated_result_sha256") is not None
                    or synthesis.get("queue_validated_result_sha256") is not None
                    or synthesis.get("publication_status") is not None):
                return None
            nested_trace = synthesis.get("saved_raw_recovery")
            outer_trace = {key: value for key, value in trace_row.items() if key != "article_id"}
            if not isinstance(nested_trace, dict) or _canonical(nested_trace) != _canonical(outer_trace):
                return None
            published_outcomes = result.get("provenance", {}).get("historical_outcomes", []) \
                if isinstance(result.get("provenance"), dict) else []
            if (not isinstance(published_outcomes, list)
                    or any(isinstance(row, dict) and row.get("article_id") == article_id
                           and row.get("source") == "SAVED_RAW_RECOVERY" for row in published_outcomes)):
                return None
        elif summary.get("status") != "SYNTHESIS_FAILED":
            return None

        failure_rows = [row for row in result.get("failures", []) if isinstance(row, dict)
                        and row.get("article_id") == article_id
                        and row.get("failure_code") == "SYNTHESIS_CITATION_ARTICLE_MISMATCH"]
        if trace_row is not None:
            if (len(failure_rows) != 1 or failure_rows[0].get("stage") != "validator"
                    or failure_rows[0].get("status") != "FAILED"
                    or failure_rows[0].get("resolution") != "DERIVED_FROM_IMMUTABLE_SAVED_RAW"):
                return None
        elif (len(failure_rows) != 2
              or sum(row.get("stage") == "validator" for row in failure_rows) != 1
              or sum(row.get("status") == "FAILED" for row in failure_rows) != 1):
            return None

        matching: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for queue_key, row in queue_state["jobs"].items():
            if not isinstance(queue_key, str) or not isinstance(row, dict) or row.get("status") != "FAILED":
                continue
            attempts = row.get("attempts")
            if (not isinstance(attempts, list) or len(attempts) != 1
                    or not isinstance(attempts[0], dict)
                    or attempts[0].get("number") != 1
                    or attempts[0].get("status") != "FAILED"
                    or not isinstance(attempts[0].get("error"), dict)
                    or attempts[0]["error"].get("code") != "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
                    or attempts[0]["error"].get("stage") != "validator"
                    or attempts[0]["error"].get("type") != "ValidationRejected"
                    or row.get("attempt_count") != 1 or row.get("max_attempts") != 1
                    or row.get("validated_path") is not None or row.get("validated_sha256") is not None):
                continue
            expected_input_path = f"jobs/{queue_key}/input.json"
            expected_raw_path = f"jobs/{queue_key}/attempt-0001.raw"
            if (row.get("input_path") != expected_input_path
                    or row.get("raw_path") != expected_raw_path
                    or attempts[0].get("raw_path") != expected_raw_path
                    or row.get("raw_sha256") != attempts[0].get("raw_sha256")
                    or not isinstance(row.get("payload_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", row["payload_sha256"])
                    or not isinstance(row.get("raw_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", row["raw_sha256"])):
                continue
            try:
                payload_raw = self.service.store.io.read_bytes(
                    f"announcement_flash/queue/{expected_input_path}", max_bytes=32 * 1024 * 1024)
                raw_bytes = self.service.store.io.read_bytes(
                    f"announcement_flash/queue/{expected_raw_path}", max_bytes=8 * 1024 * 1024)
                payload = json.loads(payload_raw)
            except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (not isinstance(payload, dict) or _sha(payload_raw) != row["payload_sha256"]
                    or _canonical(payload) != payload_raw or _sha(raw_bytes) != row["raw_sha256"]):
                continue
            synthesis_input = payload.get("synthesis_input")
            from .announcement_chunks import SYNTHESIS_TOKEN_CAP, TOKEN_SAFETY_MARGIN
            context_limit = payload.get("context_limit_tokens")
            completion_reserve = payload.get("completion_reserve_tokens")
            safety_margin = payload.get("token_safety_margin")
            token_cap = payload.get("prompt_token_cap")
            expected_token_cap = (min(SYNTHESIS_TOKEN_CAP, context_limit - completion_reserve - safety_margin)
                                  if type(context_limit) is int and type(completion_reserve) is int
                                  and type(safety_margin) is int else -1)
            if (payload.get("queue_task_kind") != "announcement_reader_synthesis"
                    or payload.get("role") != "announcement_reader_synthesis"
                    or payload.get("article_id") != article_id
                    or payload.get("source_sha256") != summary.get("source_sha256")
                    or payload.get("body_sha256") != summary.get("body_sha256")
                    or payload.get("chunk_plan_sha256") != summary.get("plan_sha256")
                    or payload.get("source_unit_map_sha256") != summary.get("source_unit_map_sha256")
                    or payload.get("synthesis_input_sha256") != synthesis_input_sha
                    or (payload.get("prompt_tokens_exact") != synthesis.get("prompt_tokens_exact")
                        and trace_row is None)
                    or type(payload.get("prompt_tokens_exact")) is not int
                    or type(synthesis.get("prompt_tokens_exact")) is not int
                    or payload.get("prompt_tokens_exact", -1) < 0
                    or synthesis.get("prompt_tokens_exact", -1) < 0
                    or type(payload.get("prompt_token_cap")) is not int
                    or type(context_limit) is not int or context_limit < 1
                    or type(completion_reserve) is not int or completion_reserve < 0
                    or safety_margin != TOKEN_SAFETY_MARGIN
                    or expected_token_cap < 1 or token_cap != expected_token_cap
                    or payload.get("prompt_token_cap") != (long_body.get("synthesis_prompt_token_cap")
                                                              if isinstance(long_body, dict) else None)
                    or payload.get("prompt_token_cap") != (long_body.get("hard_prompt_token_cap")
                                                              if isinstance(long_body, dict) else None)
                    or payload.get("prompt_tokens_exact", 0) > payload.get("prompt_token_cap", -1)
                    or synthesis.get("prompt_tokens_exact", 0) > payload.get("prompt_token_cap", -1)
                    or not isinstance(synthesis_input, dict)
                    or synthesis_input.get("article_id") != article_id
                    or synthesis_input.get("synthesis_input_sha256") != synthesis_input_sha
                    or synthesis_input.get("part_count") != summary.get("part_count")):
                continue
            matching.append((queue_key, row, payload))

        if len(matching) != 1:
            return None
        queue_key, row, payload = matching[0]
        if trace_row is not None:
            edits = trace_row.get("normalization_edits")
            if (trace_row.get("status") != "DERIVED_FROM_IMMUTABLE_FAILED_RAW"
                    or trace_row.get("failure_code") != "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
                    or trace_row.get("source_idempotency_key") != queue_key
                    or trace_row.get("source_payload_sha256") != row.get("payload_sha256")
                    or trace_row.get("source_raw_path") != row.get("raw_path")
                    or trace_row.get("source_raw_sha256") != row.get("raw_sha256")
                    or trace_row.get("queue_status_preserved") != "FAILED"
                    or trace_row.get("attempt_count_preserved") != 1
                    or trace_row.get("model_calls") != 0
                    or not isinstance(edits, list) or not edits
                    or trace_row.get("normalization_edits_sha256") != _sha(_canonical(edits))
                    or any(not isinstance(trace_row.get(field), str)
                           or not re.fullmatch(r"[0-9a-f]{64}", trace_row[field])
                           for field in ("normalized_envelope_sha256", "normalization_edits_sha256",
                                         "derived_validated_result_sha256"))):
                return None
        return {
            "schema": "v4.manager_workbench.announcement_flash_saved_raw_recovery_parent.v1",
            "article_id": article_id,
            "idempotency_key": queue_key,
            "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
            "payload_sha256": row["payload_sha256"],
            "raw_sha256": row["raw_sha256"],
            "synthesis_input_sha256": payload["synthesis_input_sha256"],
        }

    def _recovery_parent(self, target_date: str) -> dict[str, Any] | None:
        """Bind a new explicit click to the latest verified partial batch, if resumable."""
        latest = self.service.store.cursor("announcement_flash_latest")
        if (not isinstance(latest, dict) or latest.get("target_date") != target_date
                or not isinstance(latest.get("job_id"), str)
                or not JOB_ID_RE.fullmatch(latest["job_id"])):
            return None
        latest_job_id = latest["job_id"]
        job_id = latest_job_id
        failed_recovery_parent = None
        try:
            latest_job = self.service.jobs.get(latest_job_id)
        except (KeyError, OSError, ValueError):
            latest_job = None
        context = getattr(latest_job, "context", None)
        scope_refs = getattr(context, "scope_refs", {})
        parent_hint = scope_refs.get("announcement_recovery_parent") if isinstance(scope_refs, dict) else None
        failed_steps = getattr(latest_job, "failed_steps", None)
        failure_code = getattr(latest_job, "failure_code", None)
        failure_step = getattr(latest_job, "step", None)
        if (latest_job is not None
                and getattr(latest_job, "state", None) == JobState.FAILED
                and (failure_code, failure_step) in {
                    ("RECOVERY_PARENT_IDENTITY_MISMATCH", "ACQUIRE_TEMPORARY_SOURCE_LEASE"),
                    ("RECOVERY_BODY_BINDING_INVALID", "FLASH_SELECTION"),
                }
                and isinstance(failed_steps, list)
                and failure_step in failed_steps
                and getattr(context, "target_date", None) == target_date
                and getattr(context, "cutoff", None)
                and isinstance(scope_refs, dict)
                and scope_refs.get("capture_operation") == "ANNOUNCEMENT_FLASH_RECOVERY"
                and isinstance(parent_hint, dict)):
            hinted_capture = parent_hint.get("capture_product")
            if (parent_hint.get("schema") == "v4.manager_workbench.announcement_flash_recovery_parent.v1"
                    and isinstance(parent_hint.get("job_id"), str)
                    and JOB_ID_RE.fullmatch(parent_hint["job_id"])
                    and isinstance(parent_hint.get("root_batch_job_id"), str)
                    and JOB_ID_RE.fullmatch(parent_hint["root_batch_job_id"])
                    and parent_hint.get("target_date") == target_date
                    and parent_hint.get("cutoff") == context.cutoff
                    and all(isinstance(parent_hint.get(key), str)
                            and re.fullmatch(r"[0-9a-f]{64}", parent_hint[key])
                            for key in ("input_sha256", "result_sha256", "membership_authority_sha256"))
                    and isinstance(hinted_capture, dict)
                    and isinstance(hinted_capture.get("artifact_ref"), str)
                    and re.fullmatch(r"products/[0-9a-f]{64}\.json", hinted_capture["artifact_ref"])
                    and isinstance(hinted_capture.get("sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", hinted_capture["sha256"])):
                capture_identity = {
                    "recovery_parent_job_id": parent_hint["job_id"],
                    "recovery_parent_input_sha256": parent_hint["input_sha256"],
                    "recovery_parent_result_sha256": parent_hint["result_sha256"],
                    "capture_product_sha256": hinted_capture["sha256"],
                    "target_date": target_date,
                    "cutoff": parent_hint["cutoff"],
                }
                identity_matches = scope_refs.get("capture_input_sha256") == digest(capture_identity)
                if identity_matches and failure_code == "RECOVERY_PARENT_IDENTITY_MISMATCH":
                    child_artifacts_absent = True
                    for basename in ("input.json", RESULT_REF):
                        try:
                            self.service.store.io.read_bytes(self._job_ref(latest_job_id, basename),
                                                             max_bytes=64 * 1024 * 1024)
                        except FileNotFoundError:
                            continue
                        except (OSError, ValueError):
                            child_artifacts_absent = False
                            break
                        else:
                            child_artifacts_absent = False
                            break
                    if child_artifacts_absent:
                        failed_recovery_parent = parent_hint
                        job_id = parent_hint["job_id"]
                elif identity_matches and failure_code == "RECOVERY_BODY_BINDING_INVALID":
                    try:
                        child_input_raw = self.service.store.io.read_bytes(
                            self._job_ref(latest_job_id, "input.json"), max_bytes=64 * 1024 * 1024)
                        progress_raw = self.service.store.io.read_bytes(
                            self._job_ref(latest_job_id, PROGRESS_REF), max_bytes=1024 * 1024)
                    except (FileNotFoundError, OSError, ValueError):
                        child_input_raw = progress_raw = None
                    if child_input_raw is not None and progress_raw is not None:
                        try:
                            self.service.store.io.read_bytes(self._job_ref(latest_job_id, RESULT_REF),
                                                             max_bytes=64 * 1024 * 1024)
                        except FileNotFoundError:
                            child_result_absent = True
                        except (OSError, ValueError):
                            child_result_absent = False
                        else:
                            child_result_absent = False
                        try:
                            child_input = json.loads(child_input_raw)
                            progress = json.loads(progress_raw)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            child_input = progress = None
                        if (child_result_absent and isinstance(child_input, dict)
                                and _canonical(child_input) == child_input_raw
                                and isinstance(progress, dict)
                                and progress.get("step") == "FAILED"
                                and progress.get("failure_code") == "RECOVERY_BODY_BINDING_INVALID"
                                and self._failed_body_binding_input_matches(
                                    child_input, latest_job_id, target_date, context.cutoff, parent_hint)):
                            failed_recovery_parent = parent_hint
                            job_id = parent_hint["job_id"]
        try:
            input_raw = self.service.store.io.read_bytes(self._job_ref(job_id, "input.json"),
                                                         max_bytes=1024 * 1024)
            result_raw = self.service.store.io.read_bytes(self._job_ref(job_id, RESULT_REF),
                                                          max_bytes=64 * 1024 * 1024)
        except (FileNotFoundError, OSError, ValueError):
            return None
        result_sha = _sha(result_raw)
        indexed = self.service.store.cursor("announcement_flash_result_index") or {"items": []}
        if not any(isinstance(item, dict) and item.get("job_id") == job_id
                   and item.get("target_date") == target_date
                   and item.get("result_sha256") == result_sha
                   for item in indexed.get("items", [])):
            return None
        try:
            input_value = json.loads(input_raw)
            result = json.loads(result_raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(input_value, dict) or not isinstance(result, dict):
            return None
        recoverable_system_stop_code = None
        failure_progress_sha256 = None
        queue_identity_failure = "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
        result_stop = result.get("system_stop")
        try:
            selected_job = (latest_job if job_id == latest_job_id else self.service.jobs.get(job_id))
        except (KeyError, OSError, ValueError):
            selected_job = None
        selected_context = getattr(selected_job, "context", None)
        selected_scope_refs = getattr(selected_context, "scope_refs", {})
        selected_parent_hint = (selected_scope_refs.get("announcement_recovery_parent")
                                if isinstance(selected_scope_refs, dict) else None)
        is_queue_identity_failure = (
            (selected_job is not None and getattr(selected_job, "state", None) == JobState.FAILED
             and getattr(selected_job, "failure_code", None) == queue_identity_failure)
            or (isinstance(result_stop, dict) and result_stop.get("failure_code") == queue_identity_failure)
        )
        if is_queue_identity_failure:
            if failed_recovery_parent is None:
                if (job_id != latest_job_id or latest.get("state") != "FAILED"
                        or latest.get("result_state") != "PARTIAL"
                        or latest.get("result_sha256") != result_sha):
                    raise JobConflict("ANNOUNCEMENT_FLASH_RECOVERY_PARENT_UNVERIFIED")
            elif (failed_recovery_parent.get("job_id") != job_id
                  or failed_recovery_parent.get("recoverable_system_stop_code") != queue_identity_failure
                  or not isinstance(failed_recovery_parent.get("failure_progress_sha256"), str)
                  or not re.fullmatch(r"[0-9a-f]{64}", failed_recovery_parent["failure_progress_sha256"])):
                raise JobConflict("ANNOUNCEMENT_FLASH_RECOVERY_PARENT_UNVERIFIED")
            failure_progress_sha256 = self._queue_identity_failed_partial_progress_sha(
                job_id, target_date, getattr(selected_context, "cutoff", ""), selected_job,
                input_raw, input_value, result_raw, result, selected_parent_hint)
            if failure_progress_sha256 is None:
                raise JobConflict("ANNOUNCEMENT_FLASH_RECOVERY_PARENT_UNVERIFIED")
            if (failed_recovery_parent is not None
                    and failure_progress_sha256 != failed_recovery_parent.get("failure_progress_sha256")):
                raise JobConflict("ANNOUNCEMENT_FLASH_RECOVERY_PARENT_UNVERIFIED")
            recoverable_system_stop_code = queue_identity_failure
        capture_ref = input_value.get("capture_product")
        if failed_recovery_parent is not None:
            hinted_capture = failed_recovery_parent["capture_product"]
            prior_lock = input_value.get("recovery_lock")
            root_batch_job_id = (prior_lock.get("root_batch_job_id")
                                 if isinstance(prior_lock, dict)
                                 and isinstance(prior_lock.get("root_batch_job_id"), str) else job_id)
            gate = input_value.get("membership_gate")
            full_capture_keys = {"artifact_ref", "owner", "sha256", "source"}
            legacy_capture_keys = {"artifact_ref", "sha256"}
            capture_hint_matches = (
                isinstance(capture_ref, dict)
                and set(capture_ref) == full_capture_keys
                and isinstance(hinted_capture, dict)
                and (
                    (set(hinted_capture) == full_capture_keys and hinted_capture == capture_ref)
                    or (set(hinted_capture) == legacy_capture_keys
                        and hinted_capture == {"artifact_ref": capture_ref.get("artifact_ref"),
                                               "sha256": capture_ref.get("sha256")})
                )
            )
            if (failed_recovery_parent.get("input_sha256") != _sha(input_raw)
                    or failed_recovery_parent.get("result_sha256") != result_sha
                    or failed_recovery_parent.get("job_id") != job_id
                    or failed_recovery_parent.get("root_batch_job_id") != root_batch_job_id
                    or failed_recovery_parent.get("target_date") != target_date
                    or failed_recovery_parent.get("cutoff") != input_value.get("cutoff")
                    or failed_recovery_parent.get("membership_authority_sha256")
                    != (gate.get("authority_sha256") if isinstance(gate, dict) else None)
                    or not capture_hint_matches):
                return None
        if (input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != job_id or input_value.get("target_date") != target_date
                or result.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result.get("job_id") != job_id or result.get("target_trade_date") != target_date
                or result.get("state") != "PARTIAL"
                or (result.get("system_stop") is not None and recoverable_system_stop_code is None)):
            return None
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        has_pending = any(type(counts.get(key)) is int and counts[key] > 0
                          for key in ("queue_pending", "context_pending"))
        saved_raw_recovery = self._saved_raw_synthesis_failure_parent(
            job_id, target_date, latest, selected_job, input_raw, input_value, result_raw, result)
        has_saved_queue_failure = (recoverable_system_stop_code is not None
                                   and type(counts.get("failed")) is int and counts["failed"] > 0)
        has_saved_raw_recovery = isinstance(saved_raw_recovery, dict)
        if not (has_pending or has_saved_queue_failure or has_saved_raw_recovery):
            return None
        cutoff = input_value.get("cutoff")
        gate = input_value.get("membership_gate")
        result_gate = result.get("membership_gate")
        capture_ref = input_value.get("capture_product")
        if (not isinstance(cutoff, str) or not isinstance(gate, dict) or not isinstance(result_gate, dict)
                or gate.get("status") != "VERIFIED" or result_gate.get("status") != "VERIFIED"
                or gate.get("target_date") != target_date or gate.get("cutoff") != cutoff
                or result_gate.get("target_date") != target_date or result_gate.get("cutoff") != cutoff
                or gate.get("authority_sha256") != result_gate.get("authority_sha256")
                or not isinstance(capture_ref, dict)
                or not isinstance(capture_ref.get("artifact_ref"), str)
                or not re.fullmatch(r"products/[0-9a-f]{64}\.json", capture_ref["artifact_ref"])
                or not isinstance(capture_ref.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", capture_ref["sha256"])):
            return None
        prior_lock = input_value.get("recovery_lock")
        root_job_id = (prior_lock.get("root_batch_job_id")
                       if isinstance(prior_lock, dict) and isinstance(prior_lock.get("root_batch_job_id"), str)
                       else job_id)
        return {
            "schema": "v4.manager_workbench.announcement_flash_recovery_parent.v1",
            "job_id": job_id,
            "root_batch_job_id": root_job_id,
            "input_sha256": _sha(input_raw),
            "result_sha256": result_sha,
            "capture_product": dict(capture_ref),
            "target_date": target_date,
            "cutoff": cutoff,
            "membership_authority_sha256": gate["authority_sha256"],
            **({"saved_raw_recovery": saved_raw_recovery} if has_saved_raw_recovery else {}),
            **({"recoverable_system_stop_code": recoverable_system_stop_code,
                "failure_progress_sha256": failure_progress_sha256}
               if recoverable_system_stop_code is not None else {}),
        }

    @staticmethod
    def _failed_body_binding_input_matches(input_value: dict[str, Any], child_job_id: str,
                                           target_date: str, cutoff: str,
                                           parent_hint: dict[str, Any]) -> bool:
        """Accept only the saved recovery input whose unique pre-queue binding check failed."""
        lock = input_value.get("recovery_lock")
        capture_ref = input_value.get("capture_product")
        gate = input_value.get("membership_gate")
        hinted_capture = parent_hint.get("capture_product")
        if (input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != child_job_id
                or input_value.get("target_date") != target_date
                or input_value.get("cutoff") != cutoff
                or not isinstance(lock, dict)
                or lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
                or not isinstance(capture_ref, dict)
                or set(capture_ref) != {"artifact_ref", "owner", "sha256", "source"}
                or capture_ref.get("owner") != "v4.manager_workbench.capture_announcements"
                or capture_ref.get("source") != "EASTMONEY_HK"
                or not isinstance(capture_ref.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", capture_ref["sha256"])
                or capture_ref.get("artifact_ref") != f"products/{capture_ref['sha256']}.json"
                or not isinstance(hinted_capture, dict)
                or lock.get("parent_job_id") != parent_hint.get("job_id")
                or lock.get("root_batch_job_id") != parent_hint.get("root_batch_job_id")
                or lock.get("parent_input_sha256") != parent_hint.get("input_sha256")
                or lock.get("parent_result_sha256") != parent_hint.get("result_sha256")
                or lock.get("parent_capture_product_sha256") != hinted_capture.get("sha256")
                or lock.get("target_date") != target_date
                or lock.get("cutoff") != cutoff
                or lock.get("membership_authority_sha256") != parent_hint.get("membership_authority_sha256")
                or lock.get("capture_product_sha256") != capture_ref.get("sha256")
                or not isinstance(gate, dict)
                or gate.get("status") != "VERIFIED"
                or gate.get("target_date") != target_date
                or gate.get("cutoff") != cutoff
                or gate.get("authority_sha256") != parent_hint.get("membership_authority_sha256")):
            return False

        eligible_ids = lock.get("eligible_article_ids")
        current_bodies = lock.get("current_body_sha256")
        expected_bodies = lock.get("expected_body_sha256")
        missing_ids = lock.get("eligible_missing_body_article_ids")
        if (not isinstance(eligible_ids, list) or not eligible_ids
                or any(not isinstance(article_id, str) for article_id in eligible_ids)
                or len(set(eligible_ids)) != len(eligible_ids)
                or type(lock.get("eligible_count")) is not int
                or lock["eligible_count"] != len(eligible_ids)
                or not isinstance(current_bodies, dict)
                or set(current_bodies) != set(eligible_ids)
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in current_bodies.values())
                or not isinstance(expected_bodies, dict)
                or any(article_id not in current_bodies or current_bodies[article_id] != body_sha
                       for article_id, body_sha in expected_bodies.items())
                or not isinstance(missing_ids, list)
                or any(not isinstance(article_id, str) for article_id in missing_ids)
                or any(article_id not in set(eligible_ids) for article_id in missing_ids)
                or len(missing_ids) != len(set(missing_ids))
                or lock.get("current_body_sha256_digest") != digest(current_bodies)):
            return False
        return True

    def _read_cached_product_recovery(self, product_sha256: str, *, capture_store: Any = None
                                      ) -> dict[str, Any]:
        from .inputs.capture_store import OWNER, PRODUCT_MAX_BYTES, CaptureStore

        if not self.service.config.capture_root:
            raise ValueError("CACHE_RECOVERY_CAPTURE_ROOT_UNAVAILABLE")
        artifact_ref = f"products/{product_sha256}.json"
        if not re.fullmatch(r"products/[0-9a-f]{64}\.json", artifact_ref):
            raise ValueError("CACHE_RECOVERY_PRODUCT_REFERENCE_INVALID")
        store = capture_store or CaptureStore(self.service.config.capture_root)
        try:
            raw = store.io.read_bytes(artifact_ref, max_bytes=PRODUCT_MAX_BYTES)
        except (FileNotFoundError, OSError, ValueError):
            raise ValueError("CACHE_RECOVERY_PRODUCT_UNAVAILABLE") from None
        if not isinstance(raw, bytes) or len(raw) > PRODUCT_MAX_BYTES:
            raise ValueError("CACHE_RECOVERY_PRODUCT_SIZE_INVALID")
        if _sha(raw) != product_sha256:
            raise ValueError("CACHE_RECOVERY_PRODUCT_SHA_MISMATCH")
        try:
            product = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("CACHE_RECOVERY_PRODUCT_JSON_INVALID") from None
        if (not isinstance(product, dict)
                or product.get("schema_version") != "mwb.capture.window.v1"
                or product.get("owner") != OWNER
                or product.get("source") != "EASTMONEY_HK"
                or product.get("saved_ref") is not None
                or product.get("target_trade_date") != CACHED_PRODUCT_RECOVERY_TARGET_DATE
                or not isinstance(product.get("window"), dict)
                or product["window"].get("research_cutoff") != CACHED_PRODUCT_RECOVERY_CUTOFF):
            raise ValueError("CACHE_RECOVERY_PRODUCT_IDENTITY_INVALID")
        saved_ref = {"artifact_ref": artifact_ref, "sha256": product_sha256,
                     "owner": OWNER, "source": "EASTMONEY_HK"}
        return saved_ref

    def _validate_cached_product_recovery(self, failed_job_id: str, product_sha256: str, *,
                                          capture_store: Any = None
                                          ) -> tuple[dict[str, Any], dict[str, Any]]:
        if (failed_job_id != CACHED_PRODUCT_RECOVERY_SOURCE_JOB_ID
                or product_sha256 != CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256
                or not JOB_ID_RE.fullmatch(str(failed_job_id))
                or not re.fullmatch(r"[0-9a-f]{64}", str(product_sha256))):
            raise ValueError("CACHE_RECOVERY_REQUEST_BINDING_INVALID")
        try:
            failed_job = self.service.jobs.get(failed_job_id)
        except (KeyError, OSError, ValueError):
            raise ValueError("CACHE_RECOVERY_SOURCE_JOB_UNAVAILABLE") from None
        context = getattr(failed_job, "context", None)
        scope_refs = getattr(context, "scope_refs", {})
        failed_steps = getattr(failed_job, "failed_steps", None)
        phase = getattr(getattr(context, "phase", None), "value", getattr(context, "phase", None))
        state = getattr(getattr(failed_job, "state", None), "value", getattr(failed_job, "state", None))
        expected_source_input = digest({"target_date": CACHED_PRODUCT_RECOVERY_TARGET_DATE,
                                        "manual_slot": CACHED_PRODUCT_RECOVERY_CUTOFF})
        if (getattr(failed_job, "job_id", None) != failed_job_id
                or state != JobState.FAILED.value
                or getattr(failed_job, "failure_code", None) != CACHED_PRODUCT_RECOVERY_FAILURE_CODE
                or getattr(failed_job, "retryable", None) is not False
                or getattr(failed_job, "step", None) != CACHED_PRODUCT_RECOVERY_FAILURE_STEP
                or not isinstance(failed_steps, list)
                or CACHED_PRODUCT_RECOVERY_FAILURE_STEP not in failed_steps
                or getattr(context, "target_date", None) != CACHED_PRODUCT_RECOVERY_TARGET_DATE
                or getattr(context, "cutoff", None) != CACHED_PRODUCT_RECOVERY_CUTOFF
                or phase != Phase.MANUAL.value
                or getattr(getattr(context, "trigger", None), "value", getattr(context, "trigger", None)) != "MANUAL"
                or getattr(context, "rules_version", None) != "V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1"
                or not isinstance(scope_refs, dict)
                or scope_refs.get("capture_operation") != "ANNOUNCEMENT_FLASH_INCREMENTAL"
                or scope_refs.get("capture_input_sha256") != expected_source_input
                or scope_refs.get("announcement_recovery_parent") is not None
                or scope_refs.get("announcement_cached_product_recovery") is not None):
            raise ValueError("CACHE_RECOVERY_SOURCE_JOB_IDENTITY_INVALID")
        for basename, max_bytes in (("input.json", 1024 * 1024), (PROGRESS_REF, 1024 * 1024),
                                    (RESULT_REF, 64 * 1024 * 1024),
                                    ("capture-product.json", 256 * 1024 * 1024)):
            try:
                self.service.store.io.read_bytes(self._job_ref(failed_job_id, basename), max_bytes=max_bytes)
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                raise ValueError("CACHE_RECOVERY_SOURCE_ARTIFACT_UNVERIFIED") from None
            raise ValueError("CACHE_RECOVERY_SOURCE_ARTIFACT_EXISTS")
        saved_ref = self._read_cached_product_recovery(product_sha256, capture_store=capture_store)
        recovery = {"schema": CACHED_PRODUCT_RECOVERY_SCHEMA,
                    "source_job_id": failed_job_id,
                    "source_failure_code": CACHED_PRODUCT_RECOVERY_FAILURE_CODE,
                    "source_failure_step": CACHED_PRODUCT_RECOVERY_FAILURE_STEP,
                    "capture_product_sha256": product_sha256,
                    "target_date": CACHED_PRODUCT_RECOVERY_TARGET_DATE,
                    "cutoff": CACHED_PRODUCT_RECOVERY_CUTOFF}
        return recovery, saved_ref

    def start_cached_product_recovery(self, failed_job_id: str, product_sha256: str):
        with self.service.store.lock("announcement_flash_submit"):
            recovery, _saved_ref = self._validate_cached_product_recovery(
                failed_job_id, product_sha256)
            slot_key = "announcement_flash_cached_recovery_" + digest(recovery)
            prior = self.service.store.cursor(slot_key)
            if prior is not None:
                if (not isinstance(prior, dict) or not isinstance(prior.get("job_id"), str)
                        or not JOB_ID_RE.fullmatch(prior["job_id"])):
                    raise JobConflict("CACHE_RECOVERY_CURSOR_INVALID")
                try:
                    prior_job = self.service.jobs.get(prior["job_id"])
                except (KeyError, OSError, ValueError):
                    raise JobConflict("CACHE_RECOVERY_CURSOR_JOB_MISSING") from None
                prior_context = getattr(prior_job, "context", None)
                prior_scope = getattr(prior_context, "scope_refs", {})
                if (not isinstance(prior_scope, dict)
                        or prior_scope.get("capture_operation") != CACHED_PRODUCT_RECOVERY_OPERATION
                        or prior_scope.get("capture_input_sha256") != digest(recovery)
                        or prior_scope.get("announcement_cached_product_recovery") != recovery
                        or getattr(prior_context, "target_date", None) != recovery["target_date"]
                        or getattr(prior_context, "cutoff", None) != recovery["cutoff"]):
                    raise JobConflict("CACHE_RECOVERY_CURSOR_JOB_IDENTITY_INVALID")
                return prior_job
            active = self._active_flash_attempts()
            if active:
                busy = active[0]
                busy_day = re.sub(r"[^0-9]", "", str(busy.get("target_date")))
                raise JobConflict(f"ANNOUNCEMENT_FLASH_BUSY_TARGET_{busy_day or 'UNKNOWN'}")
            latest = self.service.store.cursor("announcement_flash_latest")
            if (not isinstance(latest, dict)
                    or latest.get("job_id") != failed_job_id
                    or latest.get("target_date") != recovery["target_date"]
                    or latest.get("slot") != recovery["cutoff"]):
                raise ValueError("CACHE_RECOVERY_LATEST_BINDING_INVALID")
            context = RunContext(
                target_date=recovery["target_date"], phase=Phase.MANUAL, cutoff=recovery["cutoff"],
                trigger="MANUAL", rules_version="V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1",
                scope_refs={"requested_lanes": [],
                            "capture_operation": CACHED_PRODUCT_RECOVERY_OPERATION,
                            "capture_input_sha256": digest(recovery),
                            "announcement_cached_product_recovery": recovery},
            )
            job = self.service.jobs.submit(context, self._work)
            if job.job_id == failed_job_id:
                raise JobConflict("CACHE_RECOVERY_NEW_JOB_REQUIRED")
            cursor = {"job_id": job.job_id, "target_date": recovery["target_date"],
                      "slot": recovery["cutoff"], "state": job.state.value,
                      "source_job_id": failed_job_id,
                      "capture_product_sha256": product_sha256}
            self.service.store.set_cursor(slot_key, cursor)
            self.service.store.set_cursor("announcement_flash_latest", cursor)
            return job

    def start(self, target_date: str):
        day = validate_date(target_date)
        if not (self.service.config.capture_root and self.service.config.capture_lease_root):
            raise ValueError("CAPTURE_BINDING_UNAVAILABLE")
        started = self._now().replace(second=0, microsecond=0)
        slot_digest = digest({"target_date": day, "manual_slot": started.isoformat()})
        slot_key = "announcement_flash_slot_" + slot_digest
        with self.service.store.lock("announcement_flash_submit"):
            prior_slot = self.service.store.cursor(slot_key)
            if prior_slot and isinstance(prior_slot.get("job_id"), str):
                return self.service.jobs.get(prior_slot["job_id"])
            active = self._active_flash_attempts()
            if active:
                same_target = next((item for item in active if item.get("target_date") == day), None)
                if same_target and isinstance(same_target.get("job_id"), str):
                    return self.service.jobs.get(same_target["job_id"])
                busy = active[0]
                busy_day = re.sub(r"[^0-9]", "", str(busy.get("target_date")))
                raise JobConflict(f"ANNOUNCEMENT_FLASH_BUSY_TARGET_{busy_day or 'UNKNOWN'}")
            latest = self.service.store.cursor("announcement_flash_latest")
            if latest and isinstance(latest.get("job_id"), str):
                try:
                    previous = self.service.jobs.get(latest["job_id"])
                except KeyError:
                    previous = None
                if previous and previous.state in (JobState.QUEUED, JobState.RUNNING):
                    if previous.context.target_date == day:
                        return previous
                    busy_day = re.sub(r"[^0-9]", "", str(previous.context.target_date))
                    raise JobConflict(f"ANNOUNCEMENT_FLASH_BUSY_TARGET_{busy_day or 'UNKNOWN'}")
            recovery_parent = self._recovery_parent(day)
            cutoff = recovery_parent["cutoff"] if recovery_parent else started.isoformat()
            capture_identity = ({"recovery_parent_job_id": recovery_parent["job_id"],
                                "recovery_parent_input_sha256": recovery_parent["input_sha256"],
                                "recovery_parent_result_sha256": recovery_parent["result_sha256"],
                                "capture_product_sha256": recovery_parent["capture_product"]["sha256"],
                                "target_date": day, "cutoff": cutoff}
                               if recovery_parent else {"target_date": day, "manual_slot": started.isoformat()})
            context = RunContext(
                target_date=day, phase=Phase.MANUAL, cutoff=cutoff, trigger="MANUAL",
                rules_version="V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1",
                scope_refs={"requested_lanes": [],
                            "capture_operation": ("ANNOUNCEMENT_FLASH_RECOVERY" if recovery_parent
                                                  else "ANNOUNCEMENT_FLASH_INCREMENTAL"),
                            "capture_input_sha256": digest(capture_identity),
                            **({"announcement_recovery_parent": recovery_parent} if recovery_parent else {})},
            )
            job = self.service.jobs.submit(context, self._work)
            cursor = {"job_id": job.job_id, "target_date": day, "slot": started.isoformat(),
                      "state": job.state.value}
            self.service.store.set_cursor(slot_key, cursor)
            self.service.store.set_cursor("announcement_flash_latest", cursor)
            return job

    def read(self, target_date: str | None = None) -> dict[str, Any]:
        if target_date is not None:
            target_date = validate_date(target_date)
        try:
            view = read_pinned_candidates()
        except CandidateEvidenceError as exc:
            return {"state": "UNAVAILABLE", "source_date": "CANNOT_CONFIRM",
                    "target_trade_date": "CANNOT_CONFIRM", "updated_at": None,
                    "stocks": [], "failures": [], "pending": [],
                    "gaps": [{"code": str(exc), "count": None, "detail": "固定候选证据未通过完整性校验。"}],
                    "counts": {"source_catalogue_articles": None, "model_succeeded": None,
                               "selected_model_articles": None, "model_candidate_stocks": None,
                               "reused_reviewed_stocks": None, "failed": None, "pending": None,
                               "body_gaps": None, "displayed_stocks": None},
                    "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                               "buy_gate_updated": False, "orders_sent": False}}
        latest = self.service.store.cursor("announcement_flash_latest")
        update = None
        active_target = target_date or (latest.get("target_date") if latest else None)
        result_index = self.service.store.cursor("announcement_flash_result_index") or {"items": []}
        matching_results: list[dict[str, Any]] = []
        for item in result_index.get("items", []):
            if (not isinstance(item, dict) or not JOB_ID_RE.fullmatch(str(item.get("job_id", "")))
                    or (active_target and item.get("target_date") != active_target)):
                continue
            stored = self._read_job_artifact(item["job_id"], RESULT_REF, item.get("result_sha256"))
            if (stored and stored.get("schema") == "v4.manager_workbench.announcement_flash_result.v1"
                    and stored.get("job_id") == item["job_id"]):
                matching_results.append(stored)
        membership_cutoff = None
        for result in reversed(matching_results):
            provenance = result.get("provenance")
            candidate_gate = result.get("membership_gate")
            if not isinstance(candidate_gate, dict) and isinstance(provenance, dict):
                candidate_gate = provenance.get("membership_gate")
            if (isinstance(candidate_gate, dict) and candidate_gate.get("target_date") == active_target
                    and isinstance(candidate_gate.get("cutoff"), str)):
                membership_cutoff = candidate_gate["cutoff"]
                break
        if membership_cutoff is None and latest and isinstance(latest.get("job_id"), str):
            latest_input = self._read_job_artifact(latest["job_id"], "input.json")
            candidate_gate = latest_input.get("membership_gate") if isinstance(latest_input, dict) else None
            if (isinstance(candidate_gate, dict) and candidate_gate.get("target_date") == active_target
                    and isinstance(candidate_gate.get("cutoff"), str)):
                membership_cutoff = candidate_gate["cutoff"]
        from .announcement_membership import (
            project_status_rows, project_stocks, public_gate, resolve_membership_gate,
        )
        if active_target:
            gate = resolve_membership_gate(self.service.config, active_target,
                                           membership_cutoff or self._now().isoformat())
        else:
            gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
                    "status": "CANNOT_CONFIRM", "failure_code": "TARGET_DATE_UNAVAILABLE"}

        projected_results: list[dict[str, Any]] = []
        membership_excluded_articles: list[dict[str, Any]] = []
        membership_unknown_articles: list[dict[str, Any]] = []
        for raw_result in matching_results:
            result = deepcopy(raw_result)
            eligible, excluded, unknown = project_stocks(result.get("stocks", []), gate)
            result["stocks"] = eligible
            failed, failed_out, failed_unknown = project_status_rows(result.get("failures", []), gate)
            pending, pending_out, pending_unknown = project_status_rows(result.get("pending", []), gate)
            result["failures"] = failed
            result["pending"] = pending
            result["membership_excluded_stocks"] = excluded
            result["membership_unknown_stocks"] = unknown
            result["membership"] = public_gate(gate)
            membership_excluded_articles.extend(failed_out + pending_out)
            membership_unknown_articles.extend(failed_unknown + pending_unknown)
            for record in raw_result.get("membership_exclusions", []):
                if not isinstance(record, dict):
                    continue
                if record.get("membership_status") == "OUT":
                    membership_excluded_articles.append(deepcopy(record))
                else:
                    membership_unknown_articles.append(deepcopy(record))
            counts = result.setdefault("counts", {})
            counts["membership_eligible_stocks"] = len(eligible)
            counts["membership_excluded_stocks"] = len(excluded)
            counts["membership_unknown_stocks"] = len(unknown)
            projected_results.append(result)
        for result in projected_results:
            view["stocks"] = _merge_stocks(view.get("stocks", []), result.get("stocks", []))

        # A newly indexed run supersedes stale placeholder rows from the pinned
        # candidate set for articles bound to this capture. Keep the pinned stock
        # history, while taking completion/failure/pending status from this run.
        current_version_article_ids: set[str] = set()
        if projected_results:
            latest_provenance = projected_results[-1].get("provenance")
            associations = (latest_provenance.get("queue_version_associations")
                            if isinstance(latest_provenance, dict) else None)
            if isinstance(associations, list):
                current_version_article_ids.update(
                    item["article_id"] for item in associations
                    if isinstance(item, dict) and isinstance(item.get("article_id"), str))
        if not current_version_article_ids and projected_results:
            latest_provenance = projected_results[-1].get("provenance")
            bindings = latest_provenance.get("current_capture_bindings") if isinstance(latest_provenance, dict) else None
            if isinstance(bindings, dict):
                current_version_article_ids.update(key for key in bindings if isinstance(key, str))
        if current_version_article_ids:
            view["failures"] = [record for record in view.get("failures", [])
                                if not isinstance(record, dict)
                                or record.get("article_id") not in current_version_article_ids]
            view["pending"] = [record for record in view.get("pending", [])
                               if not isinstance(record, dict)
                               or record.get("article_id") not in current_version_article_ids]
        for index, result in enumerate(projected_results):
            is_latest = index == len(projected_results) - 1
            for field in ("failures", "pending"):
                rows = result.get(field, [])
                if current_version_article_ids and not is_latest:
                    rows = [record for record in rows if not isinstance(record, dict)
                            or record.get("article_id") not in current_version_article_ids]
                view.setdefault(field, []).extend(deepcopy(rows))

        base_stocks, base_excluded, base_unknown = project_stocks(view.get("stocks", []), gate)
        view["stocks"] = base_stocks
        base_failures, base_failed_out, base_failed_unknown = project_status_rows(view.get("failures", []), gate)
        base_pending, base_pending_out, base_pending_unknown = project_status_rows(view.get("pending", []), gate)
        view["failures"] = base_failures
        view["pending"] = base_pending
        membership_excluded_articles.extend(base_failed_out + base_pending_out)
        membership_unknown_articles.extend(base_failed_unknown + base_pending_unknown)
        view["membership"] = public_gate(gate)
        view["membership_excluded_stocks"] = base_excluded
        view["membership_unknown_stocks"] = base_unknown
        view["membership_excluded_articles"] = membership_excluded_articles
        view["membership_unknown_articles"] = membership_unknown_articles
        view["counts"]["failed"] = len(view["failures"])
        view["counts"]["pending"] = len(view["pending"])
        view["counts"]["membership_eligible_stocks"] = len(base_stocks)
        view["counts"]["membership_excluded_stocks"] = len(base_excluded)
        view["counts"]["membership_unknown_stocks"] = len(base_unknown)
        view["counts"]["membership_excluded_articles"] = len(membership_excluded_articles)
        view["counts"]["membership_unknown_articles"] = len(membership_unknown_articles)
        view["counts"]["displayed_stocks"] = len(view["stocks"])
        if matching_results:
            latest_result = projected_results[-1]
            current_batch = latest_result.get("current_batch", {})
            current_status_counts = current_batch.get("article_status_counts", {})
            result_counts = latest_result.get("counts", {})
            queue_counts = result_counts.get("queue", {}) if isinstance(result_counts, dict) else {}
            current_candidate_stocks = current_batch.get(
                "candidate_stocks", result_counts.get("membership_eligible_stocks"))
            view["counts"]["incremental_candidate_stocks"] = current_candidate_stocks
            view["incremental"] = latest_result
            view["state"] = latest_result.get("state", view.get("state"))
            view["target_trade_date"] = active_target
            view["updated_at"] = latest_result.get("updated_at", view.get("updated_at"))
            view["system_stop"] = deepcopy(latest_result.get("system_stop"))
            # Keep the workbench's existing article/status counts, while naming
            # long-body part failures separately from failed announcement rows.
            view["counts"].update({
                "source_catalogue_articles": result_counts.get("capture_rows", view["counts"].get("source_catalogue_articles")),
                "model_succeeded": current_status_counts.get("succeeded", queue_counts.get("incremental_succeeded_matched",
                                                  queue_counts.get("succeeded", view["counts"].get("model_succeeded")))),
                "selected_model_articles": current_batch.get("selected_articles", result_counts.get(
                    "selected_model_articles", view["counts"].get("selected_model_articles"))),
                "body_gaps": result_counts.get("body_gaps", view["counts"].get("body_gaps")),
                "model_failed_articles": current_status_counts.get("failed", queue_counts.get("incremental_failed_matched", 0)),
                "model_pending_articles": current_status_counts.get("pending", queue_counts.get("incremental_pending_matched", 0)),
                "long_body_part_failed": queue_counts.get("long_body_parts_failed", 0),
                "long_body_part_pending": queue_counts.get("long_body_parts_pending", 0),
                "long_body_part_cannot_confirm": queue_counts.get("long_body_parts_cannot_confirm", 0),
                "long_body_synthesis_pending": queue_counts.get("long_body_synthesis_pending", 0),
                "current_batch_candidate_stocks": current_candidate_stocks or 0,
            })
            view["counts"]["failure_rows"] = len(view["failures"])
            view["counts"]["pending_rows"] = len(view["pending"])
            if current_status_counts:
                view["counts"]["failed"] = current_status_counts.get("failed", 0)
                view["counts"]["pending"] = current_status_counts.get("pending", 0)
            view["incremental_runs"] = [{"job_id": result.get("job_id"), "target_trade_date": result.get("target_trade_date"),
                                          "state": result.get("state"), "updated_at": result.get("updated_at"),
                                          "counts": result.get("counts")} for result in projected_results]
        if latest and isinstance(latest.get("job_id"), str) and JOB_ID_RE.fullmatch(latest["job_id"]):
            job_id = latest["job_id"]
            try:
                job = self.service.jobs.get(job_id)
            except KeyError:
                job = None
            progress = self._read_job_artifact(job_id, PROGRESS_REF)
            result = next((value for value in matching_results if value.get("job_id") == job_id), None)
            if job:
                update = {
                    "job_id": job.job_id,
                    "target_date": job.context.target_date,
                    "state": job.state.value,
                    "step": job.step,
                    "completed_count": job.completed_count,
                    "total_count": job.total_count,
                    "failure_code": _safe_code(job.failure_code, "") if job.failure_code else None,
                    "last_progress_at": job.last_progress_at,
                    "finished_at": getattr(job, "finished_at", None),
                    "failed_steps": list(getattr(job, "failed_steps", [])),
                    "progress": {key: progress[key] for key in (
                        "queue_counts", "pending_body_gaps", "pending_context", "membership", "result_state") if progress and key in progress},
                }
                if result:
                    update["result_state"] = result.get("state")
                    update["counts"] = result.get("counts")
                    update["system_stop"] = deepcopy(result.get("system_stop"))
                if active_target and active_target != job.context.target_date:
                    update = None
        view["job"] = update
        view["requested_target_date"] = target_date
        if active_target:
            view["resume"] = self.resume_snapshot(active_target)
        return view

    def _job_ref(self, job_id: str, basename: str) -> str:
        if not JOB_ID_RE.fullmatch(job_id) or basename not in {"input.json", PROGRESS_REF, RESULT_REF, "capture-product.json"}:
            raise ValueError("ANNOUNCEMENT_JOB_REFERENCE_INVALID")
        return f"announcement_flash/jobs/{job_id}/{basename}"

    def _read_job_artifact(self, job_id: str, basename: str, expected_sha256: str | None = None) -> dict[str, Any] | None:
        try:
            raw = self.service.store.io.read_bytes(self._job_ref(job_id, basename), max_bytes=64 * 1024 * 1024)
            if expected_sha256 and _sha(raw) != expected_sha256:
                return None
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None

    def _index_saved_partial(self, job_id: str, target_date: str, result: dict[str, Any],
                             result_raw: bytes, *, failure_code: str) -> None:
        if (result.get("job_id") != job_id or result.get("target_trade_date") != target_date
                or result.get("state") != "PARTIAL"
                or not isinstance(result.get("materialization"), dict)
                or result["materialization"].get("mode") != "SAVED_VALIDATED_QUEUE_ONLY"
                or result["materialization"].get("failure_code") != failure_code
                or result.get("system_stop", {}).get("failure_code") != failure_code
                or result["materialization"].get("queue_dispatches") != 0
                or result["materialization"].get("model_calls") != 0
                or _sha(result_raw) != _sha(_canonical(result) + b"\n")):
            raise StepFailure("SAVED_PARTIAL_RESULT_INVALID", retryable=False)
        result_sha = _sha(result_raw)
        with self.service.store.lock("announcement_flash_result_index"):
            index = self.service.store.cursor("announcement_flash_result_index") or {"items": []}
            items = list(index.get("items", []))
            existing = [item for item in items if isinstance(item, dict) and item.get("job_id") == job_id]
            if existing and any(item.get("result_sha256") != result_sha for item in existing):
                raise StepFailure("SAVED_PARTIAL_RESULT_INDEX_CONFLICT", retryable=False)
            if not existing:
                items.append({"job_id": job_id, "target_date": target_date, "result_sha256": result_sha})
                self.service.store.set_cursor("announcement_flash_result_index", {"items": items})
        latest = self.service.store.cursor("announcement_flash_latest") or {}
        if latest.get("job_id") == job_id and latest.get("target_date") == target_date:
            self.service.store.set_cursor("announcement_flash_latest", {
                **latest, "state": JobState.FAILED.value, "result_state": "PARTIAL",
                "result_sha256": result_sha,
            })

    def _materialize_saved_partial(self, job: Any, failure_code: str) -> dict[str, Any]:
        if (not JOB_ID_RE.fullmatch(str(getattr(job, "job_id", "")))
                or not re.fullmatch(r"[A-Za-z0-9_]{1,96}", str(failure_code))):
            raise StepFailure("SAVED_PARTIAL_IDENTITY_INVALID", retryable=False)
        config = self.service.config
        if not config.capture_root:
            raise StepFailure("SAVED_PARTIAL_CAPTURE_ROOT_UNAVAILABLE", retryable=False)
        progress = self._read_job_artifact(job.job_id, PROGRESS_REF)
        input_value = self._read_job_artifact(job.job_id, "input.json")
        if (not isinstance(progress, dict) or progress.get("step") != "FAILED"
                or progress.get("failure_code") != failure_code
                or not isinstance(progress.get("updated_at"), str)
                or not isinstance(input_value, dict)
                or input_value.get("job_id") != job.job_id
                or input_value.get("target_date") != job.context.target_date):
            raise StepFailure("SAVED_PARTIAL_FAILURE_STATE_MISMATCH", retryable=False)
        existing_result = self._read_job_artifact(job.job_id, RESULT_REF)
        if existing_result is not None:
            result_raw = self.service.store.io.read_bytes(self._job_ref(job.job_id, RESULT_REF),
                                                          max_bytes=64 * 1024 * 1024)
            self._index_saved_partial(job.job_id, job.context.target_date, existing_result,
                                      result_raw, failure_code=failure_code)
            return existing_result

        command = [str(RUNNER_PYTHON), "-B", str(RUNNER_SCRIPT), "--state-root", str(self.service.store.root),
                   "--capture-root", str(config.capture_root), "--job-id", job.job_id,
                   "--materialize-saved-partial", "--failure-code", failure_code]
        shared_root = getattr(config, "shared_root", None)
        if shared_root:
            command.extend(["--shared-root", str(shared_root)])
        try:
            process = self.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        except OSError as exc:
            raise StepFailure("SAVED_PARTIAL_RUNTIME_UNAVAILABLE", retryable=False) from exc
        while process.poll() is None:
            self.sleep(0.5)
        if process.returncode != 0:
            raise StepFailure("SAVED_PARTIAL_MATERIALIZATION_FAILED", retryable=False)
        result_raw = self.service.store.io.read_bytes(self._job_ref(job.job_id, RESULT_REF),
                                                      max_bytes=64 * 1024 * 1024)
        result = self._read_job_artifact(job.job_id, RESULT_REF, _sha(result_raw))
        if not isinstance(result, dict):
            raise StepFailure("SAVED_PARTIAL_RESULT_READBACK_FAILED", retryable=False)
        self._index_saved_partial(job.job_id, job.context.target_date, result, result_raw,
                                  failure_code=failure_code)
        return result

    def materialize_failed_partial(self, job_id: str) -> dict[str, Any]:
        """Publish saved validated results for an already failed job without changing its job state."""
        try:
            job = self.service.jobs.get(job_id)
        except KeyError:
            raise StepFailure("JOB_NOT_FOUND", retryable=False) from None
        if job.state != JobState.FAILED or not isinstance(job.failure_code, str):
            raise StepFailure("SAVED_PARTIAL_JOB_NOT_FAILED", retryable=False)
        if job.step not in {"FLASH_SELECTION", "FAILED"} and "FLASH_SELECTION" not in job.failed_steps:
            raise StepFailure("SAVED_PARTIAL_JOB_STAGE_INVALID", retryable=False)
        return self._materialize_saved_partial(job, job.failure_code)

    def _prepare_recovery_lock(self, job: Any, parent: Any, capture_store: Any) -> dict[str, Any]:
        if (not isinstance(parent, dict)
                or parent.get("schema") != "v4.manager_workbench.announcement_flash_recovery_parent.v1"
                or not JOB_ID_RE.fullmatch(str(parent.get("job_id", "")))
                or parent.get("target_date") != job.context.target_date
                or parent.get("cutoff") != job.context.cutoff):
            raise StepFailure("RECOVERY_PARENT_BINDING_INVALID", retryable=False)
        try:
            input_raw = self.service.store.io.read_bytes(self._job_ref(parent["job_id"], "input.json"),
                                                         max_bytes=1024 * 1024)
            result_raw = self.service.store.io.read_bytes(self._job_ref(parent["job_id"], RESULT_REF),
                                                          max_bytes=64 * 1024 * 1024)
            capture_raw = capture_store.io.read_bytes(parent["capture_product"]["artifact_ref"],
                                                       max_bytes=256 * 1024 * 1024)
            parent_input = json.loads(input_raw)
            parent_result = json.loads(result_raw)
            original_capture = json.loads(capture_raw)
        except (FileNotFoundError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
            raise StepFailure("RECOVERY_PARENT_ARTIFACT_UNAVAILABLE", retryable=False) from None
        capture_ref = parent.get("capture_product")
        recoverable_system_stop_code = parent.get("recoverable_system_stop_code")
        if recoverable_system_stop_code is not None:
            try:
                failed_parent_job = self.service.jobs.get(parent["job_id"])
            except (KeyError, OSError, ValueError):
                failed_parent_job = None
            progress_sha256 = self._queue_identity_failed_partial_progress_sha(
                parent["job_id"], job.context.target_date, job.context.cutoff, failed_parent_job,
                input_raw, parent_input, result_raw, parent_result,
                getattr(getattr(failed_parent_job, "context", None), "scope_refs", {}).get(
                    "announcement_recovery_parent")
                if isinstance(getattr(getattr(failed_parent_job, "context", None), "scope_refs", None), dict)
                else None)
            if (recoverable_system_stop_code != "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
                    or progress_sha256 is None
                    or progress_sha256 != parent.get("failure_progress_sha256")):
                raise StepFailure("RECOVERY_PARENT_SYSTEM_STOP_UNVERIFIED", retryable=False)
        elif parent.get("failure_progress_sha256") is not None or parent_result.get("system_stop") is not None:
            raise StepFailure("RECOVERY_PARENT_SYSTEM_STOP_UNVERIFIED", retryable=False)
        if (not isinstance(capture_ref, dict) or _sha(input_raw) != parent.get("input_sha256")
                or _sha(result_raw) != parent.get("result_sha256")
                or _sha(capture_raw) != capture_ref.get("sha256")
                or not isinstance(parent_input, dict) or not isinstance(parent_result, dict)
                or parent_input.get("job_id") != parent.get("job_id")
                or parent_input.get("target_date") != job.context.target_date
                or parent_input.get("cutoff") != job.context.cutoff
                or parent_input.get("capture_product") != capture_ref
                or parent_result.get("job_id") != parent.get("job_id")
                or parent_result.get("target_trade_date") != job.context.target_date
                or parent_result.get("state") != "PARTIAL"
                or (parent_result.get("system_stop") is not None
                    and recoverable_system_stop_code != "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT")
                or not isinstance(original_capture, dict)
                or original_capture.get("schema_version") != "mwb.capture.window.v1"
                or original_capture.get("source") != "EASTMONEY_HK"
                or original_capture.get("target_trade_date") != job.context.target_date
                or not isinstance(original_capture.get("window"), dict)
                or original_capture.get("window", {}).get("research_cutoff") != job.context.cutoff):
            raise StepFailure("RECOVERY_PARENT_IDENTITY_MISMATCH", retryable=False)
        old_gate = parent_input.get("membership_gate")
        result_gate = parent_result.get("membership_gate")
        if (not isinstance(old_gate, dict) or not isinstance(result_gate, dict)
                or old_gate.get("status") != "VERIFIED" or result_gate.get("status") != "VERIFIED"
                or old_gate.get("target_date") != job.context.target_date
                or old_gate.get("cutoff") != job.context.cutoff
                or result_gate.get("target_date") != job.context.target_date
                or result_gate.get("cutoff") != job.context.cutoff
                or old_gate.get("authority_sha256") != parent.get("membership_authority_sha256")
                or result_gate.get("authority_sha256") != parent.get("membership_authority_sha256")):
            raise StepFailure("RECOVERY_MEMBERSHIP_BINDING_INVALID", retryable=False)
        from .announcement_membership import revalidate_membership_gate
        fresh_gate = revalidate_membership_gate(self.service.config, old_gate,
                                                job.context.target_date, job.context.cutoff)
        if (fresh_gate.get("status") != "VERIFIED"
                or fresh_gate.get("authority_sha256") != parent.get("membership_authority_sha256")):
            raise StepFailure("RECOVERY_MEMBERSHIP_AUTHORITY_CHANGED", retryable=False)
        try:
            manifest = capture_recovery_manifest(original_capture.get("rows"), fresh_gate)
        except (TypeError, ValueError, KeyError):
            raise StepFailure("RECOVERY_SOURCE_MANIFEST_INVALID", retryable=False) from None
        eligible = set(manifest["eligible_article_ids"])
        expected_body_sha = {article_id: body_sha for article_id, body_sha in manifest["body_sha256"].items()
                             if article_id in eligible}
        prior_lock = parent_input.get("recovery_lock")
        root_batch_job_id = (prior_lock.get("root_batch_job_id")
                             if isinstance(prior_lock, dict) and isinstance(prior_lock.get("root_batch_job_id"), str)
                             else parent["job_id"])
        return {
            "schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
            "root_batch_job_id": root_batch_job_id,
            "parent_job_id": parent["job_id"],
            "parent_input_sha256": parent["input_sha256"],
            "parent_result_sha256": parent["result_sha256"],
            "parent_capture_product_sha256": capture_ref["sha256"],
            "target_date": job.context.target_date,
            "cutoff": job.context.cutoff,
            "membership_authority_sha256": fresh_gate["authority_sha256"],
            "row_count": manifest["row_count"],
            "article_ids_sha256": manifest["article_ids_sha256"],
            "row_manifest_sha256": manifest["row_manifest_sha256"],
            "eligible_article_ids": manifest["eligible_article_ids"],
            "eligible_article_ids_sha256": manifest["eligible_article_ids_sha256"],
            "eligible_count": manifest["eligible_count"],
            "expected_body_sha256": expected_body_sha,
            "eligible_missing_body_article_ids": manifest["eligible_missing_body_article_ids"],
        }, fresh_gate

    @staticmethod
    def _verify_recovery_capture(capture_product: dict[str, Any], saved_ref: dict[str, Any],
                                 recovery_lock: dict[str, Any], gate: dict[str, Any],
                                 cutoff: str) -> dict[str, Any]:
        from datetime import datetime

        if (capture_product.get("schema_version") != "mwb.capture.window.v1"
                or capture_product.get("source") != "EASTMONEY_HK"
                or capture_product.get("target_trade_date") != recovery_lock.get("target_date")
                or capture_product.get("window", {}).get("research_cutoff") != cutoff
                or not isinstance(saved_ref.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", saved_ref["sha256"])):
            raise StepFailure("RECOVERY_CAPTURE_IDENTITY_INVALID", retryable=False)
        try:
            manifest = capture_recovery_manifest(capture_product.get("rows"), gate)
        except (TypeError, ValueError, KeyError):
            raise StepFailure("RECOVERY_CAPTURE_MANIFEST_INVALID", retryable=False) from None
        if (manifest.get("row_count") != recovery_lock.get("row_count")
                or manifest.get("article_ids_sha256") != recovery_lock.get("article_ids_sha256")
                or manifest.get("row_manifest_sha256") != recovery_lock.get("row_manifest_sha256")
                or manifest.get("eligible_article_ids") != recovery_lock.get("eligible_article_ids")
                or manifest.get("eligible_article_ids_sha256") != recovery_lock.get("eligible_article_ids_sha256")
                or manifest.get("eligible_count") != recovery_lock.get("eligible_count")):
            raise StepFailure("RECOVERY_CAPTURE_SCOPE_CHANGED", retryable=False)
        expected_bodies = recovery_lock.get("expected_body_sha256")
        current_bodies = manifest.get("body_sha256")
        if not isinstance(expected_bodies, dict) or not isinstance(current_bodies, dict):
            raise StepFailure("RECOVERY_BODY_MANIFEST_INVALID", retryable=False)
        for article_id, body_sha in expected_bodies.items():
            if current_bodies.get(article_id) != body_sha:
                raise StepFailure("RECOVERY_EXISTING_BODY_CHANGED", retryable=False)
        eligible_ids = set(recovery_lock["eligible_article_ids"])
        rows_by_id = {"EASTMONEY:" + str(row.get("art_code")): row
                      for row in capture_product.get("rows", []) if isinstance(row, dict)}
        body_bindings: dict[str, str] = {}
        cutoff_at = datetime.fromisoformat(cutoff)
        for article_id in eligible_ids:
            row = rows_by_id.get(article_id)
            if not isinstance(row, dict) or row.get("body_complete") is not True:
                raise StepFailure("RECOVERY_ELIGIBLE_BODY_UNAVAILABLE", retryable=False)
            body_bindings[article_id] = current_bodies.get(article_id)
            pages = row.get("pages")
            if (not isinstance(pages, list) or not pages or row.get("content_page_count") != len(pages)):
                raise StepFailure("RECOVERY_BODY_PAGE_COVERAGE_INVALID", retryable=False)
            for page in pages:
                source_ref = page.get("source_ref") if isinstance(page, dict) else None
                available_at = source_ref.get("available_at") if isinstance(source_ref, dict) else None
                try:
                    source_time = datetime.fromisoformat(available_at)
                except (TypeError, ValueError):
                    raise StepFailure("RECOVERY_BODY_SOURCE_TIME_UNVERIFIED", retryable=False) from None
                if (source_time.tzinfo is None or source_time.utcoffset() is None
                        or cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None
                        or source_time > cutoff_at):
                    raise StepFailure("RECOVERY_BODY_SOURCE_AFTER_CUTOFF", retryable=False)
                if article_id in recovery_lock.get("eligible_missing_body_article_ids", []) and not isinstance(
                        source_ref.get("reused_from"), dict):
                    raise StepFailure("RECOVERY_BODY_CACHE_PROVENANCE_MISSING", retryable=False)
        checked_lock = dict(recovery_lock)
        checked_lock["capture_product_sha256"] = saved_ref.get("sha256")
        checked_lock["current_body_sha256"] = body_bindings
        checked_lock["current_body_sha256_digest"] = digest(body_bindings)
        return checked_lock

    def _runner_shared_root_args(self, config: Any, *, frozen_resume: bool,
                                 membership_gate: Any = None,
                                 target_date: str | None = None,
                                 cutoff: str | None = None) -> list[str]:
        """Bind frozen resume revalidation to the source input's pinned authority root."""
        shared_root = getattr(config, "shared_root", None)
        if frozen_resume:
            pin = membership_gate.get("authority_pin") if isinstance(membership_gate, dict) else None
            source_root = pin.get("source_local_path") if isinstance(pin, dict) else None
            checked_files = pin.get("checked_files") if isinstance(pin, dict) else None
            if (not isinstance(membership_gate, dict)
                    or membership_gate.get("status") != "VERIFIED"
                    or membership_gate.get("target_date") != target_date
                    or membership_gate.get("cutoff") != cutoff
                    or not isinstance(source_root, str) or not source_root
                    or not isinstance(checked_files, list) or not checked_files
                    or any(not isinstance(row, dict) or row.get("source_local_path") != source_root
                           for row in checked_files)):
                raise StepFailure("FROZEN_RESUME_MEMBERSHIP_BINDING_INVALID", retryable=False)
            pinned_root = Path(source_root).expanduser()
            if not pinned_root.is_absolute() or not pinned_root.is_dir():
                raise StepFailure("FROZEN_RESUME_MEMBERSHIP_SOURCE_ROOT_UNAVAILABLE", retryable=False)
            # The input.json hash pins this original source binding. The runner
            # still performs the full normal authority and member revalidation.
            shared_root = source_root
        return ["--shared-root", str(shared_root)] if shared_root else []

    def _work(self, job: Any) -> tuple[str, JobState]:
        from .inputs.capture_store import OWNER, CaptureStore

        config = self.service.config
        context_scope_refs = getattr(job.context, "scope_refs", {})
        cached_recovery = (context_scope_refs.get("announcement_cached_product_recovery")
                           if isinstance(context_scope_refs, dict) else None)
        is_cached_recovery = (isinstance(context_scope_refs, dict)
                              and context_scope_refs.get("capture_operation") == CACHED_PRODUCT_RECOVERY_OPERATION)
        resume_binding = (context_scope_refs.get("announcement_flash_resume")
                          if isinstance(context_scope_refs, dict) else None)
        is_frozen_resume = (isinstance(context_scope_refs, dict)
                            and context_scope_refs.get("capture_operation") == FROZEN_RESUME_OPERATION)
        has_resume_binding = (isinstance(context_scope_refs, dict)
                             and "announcement_flash_resume" in context_scope_refs)
        has_cached_recovery_binding = (isinstance(context_scope_refs, dict)
                                       and "announcement_cached_product_recovery" in context_scope_refs)
        if has_resume_binding and not is_frozen_resume:
            raise StepFailure("FROZEN_RESUME_JOB_BINDING_INVALID", retryable=False)
        if is_frozen_resume and not isinstance(resume_binding, dict):
            raise StepFailure("FROZEN_RESUME_JOB_BINDING_INVALID", retryable=False)
        if has_cached_recovery_binding and not is_cached_recovery:
            raise StepFailure("CACHE_RECOVERY_JOB_BINDING_INVALID", retryable=False)
        if not config.capture_root or (not is_cached_recovery and not is_frozen_resume
                                       and not config.capture_lease_root):
            raise StepFailure("CAPTURE_BINDING_UNAVAILABLE", retryable=False)
        capture_store = CaptureStore(config.capture_root, lease_root=config.capture_lease_root)
        granted = False
        session = None
        deadline = datetime.now(timezone.utc) + timedelta(minutes=55)
        try:
            context = job.context.model_copy(deep=True)
            recovery_lock = None
            resume_source: dict[str, Any] | None = None
            resume_root: dict[str, Any] | None = None
            if is_frozen_resume:
                self.service.jobs.update(job, step="VERIFY_FROZEN_RESUME_BINDING")
                request_binding = context_scope_refs.get("announcement_flash_resume_request")
                expected = {key: resume_binding.get(key) for key in (
                    "source_input_sha256", "source_progress_sha256", "source_queue_state_sha256")}
                if (resume_binding.get("schema") != FROZEN_RESUME_SCHEMA
                        or not isinstance(request_binding, dict)
                        or request_binding.get("source_job_id") != resume_binding.get("source_job_id")
                        or request_binding.get("resume_action") != resume_binding.get("resume_action")
                        or resume_binding.get("resume_action") not in {"CANARY", "CONTINUE"}
                        or request_binding.get("target_date") != context.target_date
                        or any(request_binding.get(key) != value for key, value in expected.items())
                        or context_scope_refs.get("capture_input_sha256") != digest(resume_binding)):
                    raise StepFailure("FROZEN_RESUME_JOB_BINDING_INVALID", retryable=False)
                try:
                    artifacts = self._resume_source_artifacts(
                        resume_binding.get("source_job_id"), context.target_date, expected,
                        ignore_active_job_id=job.job_id,
                    )
                except (OSError, ValueError, KeyError, TypeError, JobConflict) as exc:
                    code = _safe_code(str(exc), "FROZEN_RESUME_SOURCE_UNAVAILABLE")
                    raise StepFailure(code, retryable=False) from exc
                if (artifacts.get("mode") != resume_binding.get("mode")
                        or artifacts.get("capture_product_sha256") != resume_binding.get("capture_product_sha256")
                        or artifacts.get("source_result_sha256") != resume_binding.get("source_result_sha256")
                        or artifacts.get("canary_passed") != resume_binding.get("canary_passed")
                        or artifacts.get("canary_key") != resume_binding.get("canary_key")
                        or artifacts.get("canary_status") != resume_binding.get("canary_status")
                        or artifacts.get("canary_model_calls") != resume_binding.get("canary_model_calls")
                        or artifacts.get("canary_validation") != resume_binding.get("canary_validation")
                        or artifacts.get("legacy_failed_canary") != resume_binding.get("legacy_failed_canary")
                        or artifacts.get("queue_reconstruction") != resume_binding.get("queue_reconstruction")
                        or artifacts.get("transport_recovery") != resume_binding.get("transport_recovery")
                        or artifacts.get("resume_action") != resume_binding.get("resume_action")
                        or artifacts.get("max_model_calls") != resume_binding.get("max_model_calls")):
                    raise StepFailure("FROZEN_RESUME_SOURCE_BINDING_CHANGED", retryable=False)
                source_input = artifacts.get("source_input")
                resume_root = resume_binding.get("resume_root")
                if (not isinstance(source_input, dict) or "recovery_lock" in source_input
                        or not isinstance(resume_root, dict)
                        or not JOB_ID_RE.fullmatch(str(resume_root.get("source_job_id", "")))
                        or not re.fullmatch(r"[0-9a-f]{64}", str(resume_root.get("source_input_sha256", "")))):
                    raise StepFailure("FROZEN_RESUME_INPUT_CONTRACT_INVALID", retryable=False)
                saved_ref = source_input.get("capture_product")
                membership_gate = source_input.get("membership_gate")
                if not isinstance(saved_ref, dict) or not isinstance(membership_gate, dict):
                    raise StepFailure("FROZEN_RESUME_INPUT_CONTRACT_INVALID", retryable=False)
                resume_source = {key: resume_binding.get(key) for key in (
                    "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
                    "source_progress_sha256", "source_queue_state_sha256", "capture_product_sha256",
                    "source_result_sha256", "canary_passed", "canary_key", "canary_status",
                    "canary_model_calls", "canary_validation", "legacy_failed_canary",
                    "queue_reconstruction", "resume_action", "max_model_calls", "queue_status_counts",
                    "transport_recovery")
                                 if key in resume_binding}
                # _run records the immutable root input in every continuation so
                # the single recovered orphan keeps the same queue identity.
            elif is_cached_recovery:
                if (not isinstance(cached_recovery, dict)
                        or context_scope_refs.get("announcement_recovery_parent") is not None):
                    raise StepFailure("CACHE_RECOVERY_JOB_BINDING_INVALID", retryable=False)
                self.service.jobs.update(job, step="LOAD_CACHED_CAPTURE_PRODUCT")
                try:
                    expected_recovery, saved_ref = self._validate_cached_product_recovery(
                        cached_recovery.get("source_job_id"), cached_recovery.get("capture_product_sha256"),
                        capture_store=capture_store)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    code = _safe_code(str(exc), "CACHE_RECOVERY_PRODUCT_INVALID")
                    raise StepFailure(code, retryable=False) from exc
                if cached_recovery != expected_recovery:
                    raise StepFailure("CACHE_RECOVERY_JOB_BINDING_INVALID", retryable=False)
                from .announcement_membership import resolve_membership_gate
                membership_gate = resolve_membership_gate(config, context.target_date, context.cutoff)
            else:
                self.service.jobs.update(job, step="ACQUIRE_TEMPORARY_SOURCE_LEASE")
                try:
                    capture_store.grant(expires_at=deadline, owner=OWNER)
                    granted = True
                except ValueError as exc:
                    code = "CAPTURE_OWNER_BUSY" if "ALREADY_HELD" in str(exc) else "CAPTURE_LEASE_GRANT_FAILED"
                    raise StepFailure(code, retryable=False) from exc
                import requests
                session = requests.Session()
                context_scope_refs = getattr(context, "scope_refs", {})
                recovery_parent = context_scope_refs.get("announcement_recovery_parent") if isinstance(context_scope_refs, dict) else None
                recovery_gate = None
                if recovery_parent is not None:
                    recovery_lock, recovery_gate = self._prepare_recovery_lock(job, recovery_parent, capture_store)
                self.service.jobs.update(job, step="CAPTURE_ANNOUNCEMENTS")
                from .inputs.capture import capture_window
                try:
                    captured = capture_window(context, {"transport": session}, capture_store)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    code = _safe_code(str(exc), "CAPTURE_FAILED")
                    raise StepFailure(code, retryable=False) from exc
                saved_ref = captured.get("saved_ref")
                if (not isinstance(saved_ref, dict) or not isinstance(saved_ref.get("artifact_ref"), str)
                        or not re.fullmatch(r"products/[0-9a-f]{64}\.json", saved_ref["artifact_ref"])
                        or not isinstance(saved_ref.get("sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", saved_ref["sha256"])):
                    raise StepFailure("CAPTURE_PRODUCT_REFERENCE_INVALID", retryable=False)
                product_raw = capture_store.io.read_bytes(saved_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
                if _sha(product_raw) != saved_ref["sha256"]:
                    raise StepFailure("CAPTURE_PRODUCT_SHA_MISMATCH", retryable=False)
                if recovery_lock is not None:
                    try:
                        recovered_product = json.loads(product_raw)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise StepFailure("RECOVERY_CAPTURE_PRODUCT_INVALID", retryable=False) from None
                    recovery_lock = self._verify_recovery_capture(
                        recovered_product, saved_ref, recovery_lock, recovery_gate, context.cutoff)
                    membership_gate = recovery_gate
                else:
                    from .announcement_membership import resolve_membership_gate
                    membership_gate = resolve_membership_gate(config, context.target_date, context.cutoff)
            # The source product remains in CaptureStore's immutable cache. Only
            # its fixed artifact reference and hash cross into the model bridge.
            input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                           "job_id": job.job_id, "target_date": context.target_date, "cutoff": context.cutoff,
                           "capture_product": saved_ref}
            input_value["membership_gate"] = membership_gate
            if recovery_lock is not None:
                input_value["recovery_lock"] = recovery_lock
            if is_frozen_resume:
                input_value["resume_source"] = resume_source
                input_value["resume_root"] = resume_root
            self.service.store.io.write_bytes(self._job_ref(job.job_id, "input.json"), _canonical(input_value))
        except StepFailure:
            raise
        except Exception as exc:
            code = _safe_code(str(exc), "CACHE_RECOVERY_FAILED" if is_cached_recovery else "CAPTURE_FAILED")
            raise StepFailure(code, retryable=False) from exc
        finally:
            if session is not None:
                session.close()
            if granted:
                try:
                    capture_store.revoke()
                except ValueError:
                    # The lease is time-bounded and owner-checked. If it expired
                    # or ownership moved, do not touch the current lease record.
                    if datetime.now(timezone.utc) < deadline:
                        raise StepFailure("CAPTURE_OWN_LEASE_REVOCATION_UNCONFIRMED", retryable=False)

        self.service.jobs.update(job, step="FLASH_SELECTION")
        progress_ref = self._job_ref(job.job_id, PROGRESS_REF)
        result_ref = self._job_ref(job.job_id, RESULT_REF)
        command = [str(RUNNER_PYTHON), "-B", str(RUNNER_SCRIPT), "--state-root", str(self.service.store.root),
                   "--capture-root", str(config.capture_root), "--job-id", job.job_id]
        job_scope_refs = getattr(job.context, "scope_refs", {})
        recovery = job_scope_refs.get("announcement_recovery_parent") if isinstance(job_scope_refs, dict) else None
        if isinstance(recovery, dict):
            command.append("--resume-pending")
        frozen_resume = (job_scope_refs.get("announcement_flash_resume")
                         if isinstance(job_scope_refs, dict) else None)
        if isinstance(frozen_resume, dict):
            command.append("--resume-frozen-batch")
            command.extend(["--resume-action", str(frozen_resume.get("resume_action", ""))])
            if type(frozen_resume.get("max_model_calls")) is int:
                command.extend(["--max-model-calls", str(frozen_resume["max_model_calls"])])
        command.extend(self._runner_shared_root_args(
            config, frozen_resume=is_frozen_resume,
            membership_gate=input_value.get("membership_gate") if is_frozen_resume else None,
            target_date=context.target_date, cutoff=context.cutoff,
        ))
        try:
            process = self.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        except OSError as exc:
            raise StepFailure("FLASH_RUNTIME_UNAVAILABLE", retryable=False) from exc
        last_progress = None
        while process.poll() is None:
            progress = self._read_job_artifact(job.job_id, PROGRESS_REF)
            if progress and progress != last_progress:
                last_progress = progress
                job.completed_count = max(0, int(progress.get("completed", 0) or 0))
                total = progress.get("total")
                job.total_count = int(total) if isinstance(total, int) and total >= 0 else None
                step = _safe_code(progress.get("step"), "FLASH_SELECTION")
                if step == "FAILED":
                    failed_step = progress.get("failed_step")
                    step = _safe_code(failed_step, job.step if job.step != "FAILED" else "FLASH_SELECTION")
                self.service.jobs.update(job, step=step)
            self.sleep(0.5)
        if process.returncode != 0:
            progress = self._read_job_artifact(job.job_id, PROGRESS_REF) or {}
            failure_code = _safe_code(progress.get("failure_code"), "FLASH_PIPELINE_FAILED")
            if (progress.get("step") == "FAILED" and job.step == "FLASH_SELECTION"
                    and self._read_job_artifact(job.job_id, "input.json") is not None
                    and self._read_job_artifact(job.job_id, RESULT_REF) is None):
                try:
                    self._materialize_saved_partial(job, failure_code)
                except StepFailure:
                    # Preserve the original runner failure as the job terminal
                    # state; a failed publication attempt remains visible in logs.
                    pass
            raise StepFailure(failure_code, retryable=False)
        result = self._read_job_artifact(job.job_id, RESULT_REF)
        if (not result or result.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
                or result.get("job_id") != job.job_id):
            raise StepFailure("FLASH_RESULT_INVALID", retryable=False)
        result_raw = self.service.store.io.read_bytes(result_ref, max_bytes=64 * 1024 * 1024)
        if _sha(result_raw) != _sha(_canonical(result) + b"\n"):
            raise StepFailure("FLASH_RESULT_READBACK_MISMATCH", retryable=False)
        job.completed_count = int(result.get("counts", {}).get("queue", {}).get("succeeded", 0))
        job.total_count = sum(int(result.get("counts", {}).get("queue", {}).get(key, 0) or 0)
                              for key in ("succeeded", "failed", "pending"))
        job.retryable = False
        job.execution_refs.append({"kind": "announcement_flash_result", "result_sha256": _sha(result_raw),
                                   "candidate_count": int(result.get("counts", {}).get("new_candidate_stocks", 0) or 0)})
        with self.service.store.lock("announcement_flash_result_index"):
            index = self.service.store.cursor("announcement_flash_result_index") or {"items": []}
            items = list(index.get("items", []))
            if not any(isinstance(item, dict) and item.get("job_id") == job.job_id for item in items):
                items.append({"job_id": job.job_id, "target_date": job.context.target_date,
                              "result_sha256": _sha(result_raw)})
            self.service.store.set_cursor("announcement_flash_result_index", {"items": items})
        cursor = self.service.store.cursor("announcement_flash_latest") or {}
        if cursor.get("job_id") == job.job_id:
            self.service.store.set_cursor("announcement_flash_latest", {**cursor, "result_sha256": _sha(result_raw)})
        state = JobState.SUCCEEDED if result.get("state") == "SUCCEEDED" else JobState.PARTIAL
        return job.job_id, state
