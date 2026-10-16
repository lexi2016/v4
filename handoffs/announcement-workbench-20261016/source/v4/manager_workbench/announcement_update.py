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
from .contracts import HK, JobState, Phase, RunContext, digest, validate_date
from .jobs import JobConflict, StepFailure


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RUNNER_PYTHON = Path("/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python")
RUNNER_SCRIPT = Path(__file__).resolve().parents[2] / "ops/run_manager_flash_announcements.py"
PROGRESS_REF = "progress.json"
RESULT_REF = "result.json"


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
            context = RunContext(
                target_date=day, phase=Phase.MANUAL, cutoff=started.isoformat(), trigger="MANUAL",
                rules_version="V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1",
                scope_refs={"requested_lanes": [], "capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL",
                            "capture_input_sha256": slot_digest},
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
        for result in matching_results:
            view["stocks"] = _merge_stocks(view.get("stocks", []), result.get("stocks", []))
        if matching_results:
            latest_result = matching_results[-1]
            view["counts"]["displayed_stocks"] = len(view["stocks"])
            view["counts"]["incremental_candidate_stocks"] = latest_result.get("counts", {}).get("new_candidate_stocks")
            view["incremental"] = latest_result
            view["incremental_runs"] = [{"job_id": result.get("job_id"), "target_trade_date": result.get("target_trade_date"),
                                          "state": result.get("state"), "updated_at": result.get("updated_at"),
                                          "counts": result.get("counts")} for result in matching_results]
            view["target_trade_date"] = latest_result.get("target_trade_date")
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
                    "progress": {key: progress[key] for key in (
                        "queue_counts", "pending_body_gaps", "pending_context", "result_state") if progress and key in progress},
                }
                if result:
                    update["result_state"] = result.get("state")
                    update["counts"] = result.get("counts")
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

    def _work(self, job: Any) -> tuple[str, JobState]:
        from .inputs.capture import capture_window
        from .inputs.capture_store import OWNER, CaptureStore

        config = self.service.config
        if not config.capture_root or not config.capture_lease_root:
            raise StepFailure("CAPTURE_BINDING_UNAVAILABLE", retryable=False)
        capture_store = CaptureStore(config.capture_root, lease_root=config.capture_lease_root)
        granted = False
        session = None
        deadline = datetime.now(timezone.utc) + timedelta(minutes=55)
        try:
            self.service.jobs.update(job, step="ACQUIRE_TEMPORARY_SOURCE_LEASE")
            try:
                capture_store.grant(expires_at=deadline, owner=OWNER)
                granted = True
            except ValueError as exc:
                code = "CAPTURE_OWNER_BUSY" if "ALREADY_HELD" in str(exc) else "CAPTURE_LEASE_GRANT_FAILED"
                raise StepFailure(code, retryable=False) from exc
            import requests
            session = requests.Session()
            context = job.context.model_copy(deep=True)
            self.service.jobs.update(job, step="CAPTURE_ANNOUNCEMENTS")
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
            # The source product remains in CaptureStore's immutable cache. Only
            # its fixed artifact reference and hash cross into the model bridge.
            input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                           "job_id": job.job_id, "target_date": context.target_date,
                           "capture_product": saved_ref}
            self.service.store.io.write_bytes(self._job_ref(job.job_id, "input.json"), _canonical(input_value))
        except StepFailure:
            raise
        except Exception as exc:
            code = _safe_code(str(exc), "CAPTURE_FAILED")
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
                self.service.jobs.update(job, step=step)
            self.sleep(0.5)
        if process.returncode != 0:
            progress = self._read_job_artifact(job.job_id, PROGRESS_REF) or {}
            raise StepFailure(_safe_code(progress.get("failure_code"), "FLASH_PIPELINE_FAILED"), retryable=False)
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
