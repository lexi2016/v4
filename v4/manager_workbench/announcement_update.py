"""Explicit-click capture and local Flash job orchestration."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
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


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_code(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,96}", value) else fallback


def _merge_stocks(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(base)
    by_symbol = {item.get("symbol"): item for item in result if isinstance(item, dict)}
    for new in extra:
        symbol = new.get("symbol")
        if not isinstance(symbol, str):
            continue
        existing = by_symbol.get(symbol)
        if existing is None:
            cloned = deepcopy(new)
            result.append(cloned)
            by_symbol[symbol] = cloned
            continue
        prior_articles = {article.get("article_id") for article in existing.get("articles", []) if isinstance(article, dict)}
        for article in new.get("articles", []):
            if isinstance(article, dict) and article.get("article_id") not in prior_articles:
                existing.setdefault("articles", []).append(deepcopy(article))
                reason = article.get("reason")
                if isinstance(reason, str):
                    existing.setdefault("reasons", []).append(reason)
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
                                          check_latest: bool = True, capture_store: Any = None
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
                or not isinstance(scope_refs, dict)
                or scope_refs.get("capture_operation") != "ANNOUNCEMENT_FLASH_INCREMENTAL"
                or scope_refs.get("capture_input_sha256") != expected_source_input
                or scope_refs.get("announcement_recovery_parent") is not None
                or scope_refs.get("announcement_cached_product_recovery") is not None):
            raise ValueError("CACHE_RECOVERY_SOURCE_JOB_IDENTITY_INVALID")
        for basename, max_bytes in (("input.json", 1024 * 1024), (RESULT_REF, 64 * 1024 * 1024)):
            try:
                self.service.store.io.read_bytes(self._job_ref(failed_job_id, basename), max_bytes=max_bytes)
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                raise ValueError("CACHE_RECOVERY_SOURCE_ARTIFACT_UNVERIFIED") from None
            raise ValueError("CACHE_RECOVERY_SOURCE_ARTIFACT_EXISTS")
        if check_latest:
            latest = self.service.store.cursor("announcement_flash_latest")
            if (not isinstance(latest, dict)
                    or latest.get("job_id") != failed_job_id
                    or latest.get("target_date") != CACHED_PRODUCT_RECOVERY_TARGET_DATE
                    or latest.get("slot") != CACHED_PRODUCT_RECOVERY_CUTOFF):
                raise ValueError("CACHE_RECOVERY_LATEST_BINDING_INVALID")
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
                failed_job_id, product_sha256, check_latest=False)
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

    def _work(self, job: Any) -> tuple[str, JobState]:
        from .inputs.capture_store import OWNER, CaptureStore

        config = self.service.config
        context_scope_refs = getattr(job.context, "scope_refs", {})
        cached_recovery = (context_scope_refs.get("announcement_cached_product_recovery")
                           if isinstance(context_scope_refs, dict) else None)
        is_cached_recovery = (isinstance(context_scope_refs, dict)
                              and context_scope_refs.get("capture_operation") == CACHED_PRODUCT_RECOVERY_OPERATION)
        has_cached_recovery_binding = (isinstance(context_scope_refs, dict)
                                       and "announcement_cached_product_recovery" in context_scope_refs)
        if has_cached_recovery_binding and not is_cached_recovery:
            raise StepFailure("CACHE_RECOVERY_JOB_BINDING_INVALID", retryable=False)
        if not config.capture_root or (not is_cached_recovery and not config.capture_lease_root):
            raise StepFailure("CAPTURE_BINDING_UNAVAILABLE", retryable=False)
        capture_store = CaptureStore(config.capture_root, lease_root=config.capture_lease_root)
        granted = False
        session = None
        deadline = datetime.now(timezone.utc) + timedelta(minutes=55)
        try:
            context = job.context.model_copy(deep=True)
            recovery_lock = None
            if is_cached_recovery:
                if (not isinstance(cached_recovery, dict)
                        or context_scope_refs.get("announcement_recovery_parent") is not None):
                    raise StepFailure("CACHE_RECOVERY_JOB_BINDING_INVALID", retryable=False)
                self.service.jobs.update(job, step="LOAD_CACHED_CAPTURE_PRODUCT")
                try:
                    expected_recovery, saved_ref = self._validate_cached_product_recovery(
                        cached_recovery.get("source_job_id"), cached_recovery.get("capture_product_sha256"),
                        check_latest=False, capture_store=capture_store)
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
        shared_root = getattr(config, "shared_root", None)
        if shared_root:
            command.extend(["--shared-root", str(shared_root)])
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
