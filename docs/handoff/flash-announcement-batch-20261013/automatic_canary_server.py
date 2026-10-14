#!/usr/bin/env python3
"""Visible, temporary loopback runner for the frozen Flash Next canary.

The server prepares and verifies inputs at startup but performs no model calls
until a same-origin UI Start action. It uses the existing batch prompt,
validator, web routes, and serial queue; it is a local experiment harness, not
a production endpoint.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

import announcement_queue as queue_module
import batch_runner as runner
import build_length_canary as length_canary


PIPELINE_DIR = Path(__file__).resolve().parent
EVIDENCE_ROOT = PIPELINE_DIR / "evidence" / "automatic-20261014"
SOURCE_DIR = PIPELINE_DIR / "evidence" / "decision-first-20261014" / "stress"
LENGTH_DIR = PIPELINE_DIR / "evidence" / "length-single-20261014"
LENGTH_MANIFEST = LENGTH_DIR / "length-canary-manifest.json"
MODEL_ID = "qwen3_8_flash_next"
PROFILE = "decision_grounded"
EXPECTED_SYSTEM_PROMPT_SHA256 = "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772"
PREVIOUS_PROFILE = "decision_first"
PREVIOUS_SYSTEM_PROMPT_SHA256 = "9b32e0b4d7d93384ab14b54a5b2f1a7a504c80baa8e13c319dbe4537f414f395"
MAX_COMPLETION_TOKENS = 32768
OUTPUT_RESERVE_TOKENS = 2048  # Admission estimate only; never sent as a cap.
MAX_ATTEMPTS = 2
NO_PROGRESS_TIMEOUT_SECONDS = 90.0
WEB_TIMEOUT_SECONDS = 120.0
IDLE_WAIT_SECONDS = 20.0
ARTICLE_RULES = "active_reader_v3+decision_grounded+single_article"
ARTICLE_ROLE = "announcement_reader"
ARTICLE_STAGE = "decision_grounded"
WEB_CONTRACT = re.compile(
    r"^MISSING_FACT:\s*(?P<fact>[^\r\n]{1,500})\r?\n"
    r"READER_FIELD:\s*(?P<field>[A-Za-z_][A-Za-z0-9_]*)\r?\n"
    r"QUERY:\s*(?P<query>.{1,300})$",
    re.DOTALL,
)
STABLE_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
PRESSURE_CONFIRMATION_PHRASE = "已独立核验，运行压力29"


class PlanError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stable_failure_code(exc: Exception, fallback: str) -> str:
    candidate = str(exc).split(":", 1)[0] if isinstance(exc, runner.TransportError) else getattr(exc, "code", None)
    if isinstance(candidate, str) and STABLE_FAILURE_CODE.fullmatch(candidate):
        return candidate
    return fallback


def canonical_json(value: Any) -> bytes:
    return runner.canonical_json_bytes(value)


def _private_dir(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existed:
        os.chmod(path, 0o700)
    if path.stat().st_mode & 0o077:
        raise PermissionError("PRIVATE_EVIDENCE_DIRECTORY_PERMISSIONS_INVALID")


def _write_private(path: Path, raw: bytes) -> None:
    _private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class FrozenPlan:
    records: tuple[dict[str, Any], ...]
    cohorts: Mapping[str, tuple[str, ...]]
    metadata: Mapping[str, Any]
    manifest_path: Path


def build_frozen_plan(
    *,
    source_dir: Path = SOURCE_DIR,
    length_manifest_path: Path = LENGTH_MANIFEST,
    output_root: Path = EVIDENCE_ROOT,
    runtime_limits: Mapping[str, Any] | None = None,
) -> FrozenPlan:
    """Load only the previously frozen full-body sources and build the two stages."""
    try:
        length_raw = length_manifest_path.read_bytes()
        length_manifest = json.loads(length_raw)
        contract = runner.load_active_contract()
    except Exception as exc:
        raise PlanError("FROZEN_PLAN_SOURCE_UNAVAILABLE") from exc
    if not isinstance(length_manifest, dict) or length_manifest.get("status") != "PREPARED_PENDING_INDEPENDENT_REVIEW":
        raise PlanError("LENGTH_MANIFEST_STATUS_INVALID")
    config = length_manifest.get("configuration", {})
    if config.get("model_id") != MODEL_ID or config.get("active_contract_source_sha256") != contract.source_sha256:
        raise PlanError("FROZEN_CONFIGURATION_MISMATCH")
    if config.get("runtime_limits", {}).get("completion_max_tokens") != MAX_COMPLETION_TOKENS:
        raise PlanError("FROZEN_COMPLETION_LIMIT_MISMATCH")
    limits = dict(runtime_limits) if runtime_limits is not None else runner.load_runtime_limits()
    if limits.get("completion_max_tokens") != MAX_COMPLETION_TOKENS:
        raise PlanError("LIVE_COMPLETION_LIMIT_MISMATCH")

    try:
        records, source_receipt = length_canary.load_source_population(source_dir, contract, expected_count=277)
    except Exception as exc:
        raise PlanError("FROZEN_SOURCE_INTEGRITY_FAILED") from exc
    source_by_id = {record.article["article_id"]: record.article for record in records}
    sample_cfg = length_manifest["canary_samples"]
    canary_ids = list(sample_cfg["A_paired"]["selected_article_ids"])
    canary_ids += list(sample_cfg["B_sealed_unmeasured"]["selected_article_ids"])
    if len(canary_ids) != 6 or len(set(canary_ids)) != 6:
        raise PlanError("CANARY_SAMPLE_SELECTION_INVALID")
    pressure_group = next(
        (group for group in source_receipt["groups"] if group.get("batch_number") == 3), None
    )
    if not isinstance(pressure_group, dict) or pressure_group.get("article_count") != 29:
        raise PlanError("PRESSURE_BATCH_03_INVALID")
    pressure_ids = list(pressure_group.get("article_ids", []))
    if len(pressure_ids) != 29 or len(set(pressure_ids)) != 29:
        raise PlanError("PRESSURE_BATCH_03_IDENTITY_INVALID")
    all_ids = canary_ids + pressure_ids
    if any(article_id not in source_by_id for article_id in all_ids):
        raise PlanError("FROZEN_ARTICLE_NOT_FOUND")

    prompt = runner.build_system_prompt(contract, PROFILE)
    prompt_sha = sha256(prompt.encode("utf-8"))
    if prompt_sha != EXPECTED_SYSTEM_PROMPT_SHA256:
        raise PlanError("FROZEN_SYSTEM_PROMPT_SHA_MISMATCH")
    config_sha = config.get("configuration_sha256")
    if not runner._is_sha(config_sha):
        raise PlanError("FROZEN_CONFIGURATION_SHA_INVALID")
    unique_ids = list(dict.fromkeys(all_ids))
    corpus_order = {record.article["article_id"]: index for index, record in enumerate(records)}
    unique_ids.sort(key=lambda article_id: (len(source_by_id[article_id]["article_body"].encode("utf-8")), corpus_order[article_id], article_id))
    cohort_map = {
        "canary_A_and_B_union": tuple(dict.fromkeys(canary_ids)),
        "pressure_batch_03": tuple(pressure_ids),
    }
    output_root = output_root.resolve()
    plan_path = output_root / "automatic-input-manifest.json"
    source_population = {
        "article_count": source_receipt["article_count"],
        "capture_failed_count": 26,
        "stress_manifest_path": source_receipt["manifest_path"],
        "stress_manifest_sha256": source_receipt["manifest_sha256"],
        "length_manifest_sha256": sha256(length_raw),
        "source_import_files": source_receipt["source_import_files"],
        "incomplete_capture_rows_imported": 0,
    }
    cohort_manifest = {
        name: {"article_ids": list(ids), "unique_count": len(ids)}
        for name, ids in cohort_map.items()
    }
    prior = None
    prior_raw = None
    prior_rows: dict[str, dict[str, Any]] = {}
    prior_static_matches = False
    prior_profile_migration = False
    if plan_path.exists():
        try:
            prior_raw = plan_path.read_bytes()
            prior = json.loads(prior_raw)
        except Exception as exc:
            raise PlanError("EXISTING_PLAN_MANIFEST_INVALID") from exc
        prior_static = {
            "source_population": source_population,
            "model_id": MODEL_ID,
            "prompt_profile": PROFILE,
            "system_prompt_sha256": prompt_sha,
            "active_contract_source_sha256": contract.source_sha256,
            "reader_schema_sha256": sha256(canonical_json(contract.reader_schema)),
            "tool_schema_sha256": sha256(canonical_json(runner.make_tool_schema())),
            "configuration_sha256": config_sha,
            "runtime_limits": limits,
            "cohorts": cohort_manifest,
            "deduped_union_count": len(unique_ids),
        }
        if (
            not isinstance(prior, dict)
            or prior.get("schema") != "qwen_flash_next.automatic_canary_input_manifest.v1"
            or prior.get("status") != "FROZEN_INPUTS_VERIFIED; INFERENCE_NOT_STARTED"
        ):
            raise PlanError("EXISTING_PLAN_MANIFEST_CONFLICT")
        if not isinstance(prior.get("articles"), list):
            raise PlanError("EXISTING_PLAN_ARTICLES_INVALID")
        prior_rows_all = {
            row.get("article_id"): row
            for row in prior["articles"]
            if isinstance(row, dict) and isinstance(row.get("article_id"), str)
        }
        if len(prior_rows_all) != len(prior["articles"]) or set(prior_rows_all) != set(unique_ids):
            raise PlanError("EXISTING_PLAN_ARTICLES_INVALID")
        prior_static_matches = all(prior.get(key) == value for key, value in prior_static.items())
        if prior_static_matches:
            prior_rows = prior_rows_all
        else:
            migration_static = {
                "source_population": source_population,
                "model_id": MODEL_ID,
                "active_contract_source_sha256": contract.source_sha256,
                "reader_schema_sha256": sha256(canonical_json(contract.reader_schema)),
                "configuration_sha256": config_sha,
                "runtime_limits": limits,
                "cohorts": cohort_manifest,
                "deduped_union_count": len(unique_ids),
            }
            if (
                prior.get("prompt_profile") != PREVIOUS_PROFILE
                or prior.get("system_prompt_sha256") != PREVIOUS_SYSTEM_PROMPT_SHA256
                or any(prior.get(key) != value for key, value in migration_static.items())
                or not runner._is_sha(prior.get("tool_schema_sha256"))
            ):
                raise PlanError("EXISTING_PLAN_MANIFEST_CONFLICT")
            prior_profile_migration = True
    plan_rows = []
    prepared_rejections = []
    for article_id in unique_ids:
        article = source_by_id[article_id]
        batch_id = "AUTO_" + sha256(article_id.encode("utf-8"))[:20]
        batch = length_canary.make_batch([article], batch_id)
        try:
            runner.validate_batch(batch)
            input_sha = runner._input_batch_sha(batch)
            old_row = prior_rows.get(article_id)
            if prior_static_matches:
                if (
                    old_row.get("batch_id") != batch_id
                    or old_row.get("source_sha256") != article["source_sha256"]
                    or old_row.get("body_sha256") != article["body_sha256"]
                    or old_row.get("body_length_bytes") != len(article["article_body"].encode("utf-8"))
                    or old_row.get("input_sha256") != input_sha
                    or old_row.get("context_limit_tokens") != limits.get("context_limit_tokens")
                    or type(old_row.get("prompt_tokens_exact")) is not int
                    or old_row["prompt_tokens_exact"] <= 0
                ):
                    raise PlanError("EXISTING_EXACT_TOKEN_COUNT_NOT_BOUND_TO_CURRENT_INPUT")
                exact_prompt_tokens = old_row["prompt_tokens_exact"]
                context_limit_tokens = old_row["context_limit_tokens"]
            else:
                prepared = runner.prepare_batch(batch, contract, prompt_profile=PROFILE, runtime_limits=limits)
                if prepared["input_sha256"] != input_sha:
                    raise PlanError("PREFLIGHT_INPUT_SHA_DIVERGED")
                exact_prompt_tokens = prepared["prompt_tokens_exact_initial_request"]
                context_limit_tokens = prepared["context_limit_tokens"]
        except PlanError:
            raise
        except Exception as exc:
            raise PlanError("ARTICLE_PREFLIGHT_FAILED") from exc
        required_tokens = exact_prompt_tokens + MAX_COMPLETION_TOKENS
        estimate_required_tokens = exact_prompt_tokens + OUTPUT_RESERVE_TOKENS
        fits = required_tokens <= context_limit_tokens
        row = {
            "article_id": article_id,
            "batch_id": batch_id,
            "source_sha256": article["source_sha256"],
            "body_sha256": article["body_sha256"],
            "body_length_bytes": len(article["article_body"].encode("utf-8")),
            "input_sha256": input_sha,
            "prompt_tokens_exact": exact_prompt_tokens,
            "output_reserve_estimate_tokens": OUTPUT_RESERVE_TOKENS,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "input_plus_max_completion_tokens": required_tokens,
            "context_limit_tokens": context_limit_tokens,
            "context_admission": "READY" if fits else "CONTEXT_ITEM_UNFIT",
            "output_reserve_estimate_admission": "READY" if estimate_required_tokens <= context_limit_tokens else "ESTIMATE_EXCEEDS_CONTEXT",
            "idempotency_key": None,
        }
        if not fits:
            prepared_rejections.append({"article_id": article_id, "code": "CONTEXT_ITEM_UNFIT"})
        plan_rows.append(row)

    for article in plan_rows:
        source_article = source_by_id[article["article_id"]]
        metadata = source_article["article_metadata"]
        identity = {
            "date": metadata.get("publication_date") or "CANNOT_CONFIRM",
            "market": "HK" if str(metadata.get("symbol", "")).startswith("HK.") else "A_SHARE",
            "article_id": article["article_id"],
            "source_sha256": article["source_sha256"],
            "body_sha256": article["body_sha256"],
            "prompt_sha256": prompt_sha,
            "model_id": MODEL_ID,
            "configuration_sha256": config_sha,
            "rules": ARTICLE_RULES,
            "role": ARTICLE_ROLE,
            "stage": ARTICLE_STAGE,
        }
        article["idempotency_key"] = sha256(canonical_json(identity))

    manifest = {
        "schema": "qwen_flash_next.automatic_canary_input_manifest.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "revision": 1,
        "status": "FROZEN_INPUTS_VERIFIED; INFERENCE_NOT_STARTED",
        "source_population": source_population,
        "model_id": MODEL_ID,
        "prompt_profile": PROFILE,
        "system_prompt_sha256": prompt_sha,
        "active_contract_source_sha256": contract.source_sha256,
        "reader_schema_sha256": sha256(canonical_json(contract.reader_schema)),
        "tool_schema_sha256": sha256(canonical_json(runner.make_tool_schema())),
        "configuration_sha256": config_sha,
        "runtime_limits": limits,
        "request_policy": {
            "one_article_per_request": True,
            "full_body_only": True,
            "body_truncation_allowed": False,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "thinking": "OFF per request",
            "web_tools": "existing oMLX routes only; gated by explicit fact/field/query contract",
            "context_admission_basis": "exact_input_tokens_plus_actual_max_completion_must_fit_effective_context",
            "context_output_reserve_estimate_tokens": OUTPUT_RESERVE_TOKENS,
        },
        "cohorts": cohort_manifest,
        "deduped_union_count": len(unique_ids),
        "context_rejections": prepared_rejections,
        "articles": plan_rows,
        "full_277_status": "NOT_RUN; only frozen A/B union and pressure batch 03 are scheduled",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if prior is not None and prior_raw is not None:
        manifest["created_at_utc"] = prior.get("created_at_utc", manifest["created_at_utc"])
        manifest["supersedes_manifest_sha256"] = prior.get("supersedes_manifest_sha256")
        if prior.get("articles") != manifest["articles"] or prior.get("request_policy") != manifest["request_policy"] or prior_profile_migration:
            old_sha = sha256(prior_raw)
            superseded_name = (
                "automatic-input-manifest-decision-first-superseded.json"
                if prior_profile_migration
                else "automatic-input-manifest-estimate-gate-superseded.json"
            )
            superseded_path = output_root / superseded_name
            if superseded_path.exists():
                if sha256(superseded_path.read_bytes()) != old_sha:
                    raise PlanError("SUPERSEDED_MANIFEST_ARCHIVE_CONFLICT")
            else:
                _write_private(superseded_path, prior_raw)
            manifest["revision"] = int(prior.get("revision", 0)) + 1
            manifest["revised_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            manifest["supersedes_manifest_sha256"] = old_sha
            raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        else:
            manifest["revision"] = prior.get("revision", 1)
            manifest["revised_at_utc"] = prior.get("revised_at_utc")
            manifest["supersedes_manifest_sha256"] = prior.get("supersedes_manifest_sha256")
            raw = prior_raw
    if prior is None:
        _write_private(plan_path, raw)
    elif raw != prior_raw:
        _write_private(plan_path, raw)

    # Keep the frozen plan deterministic for subsequent process restarts.
    final_raw = plan_path.read_bytes()

    expected_ready_keys = {row["idempotency_key"] for row in manifest["articles"] if row["context_admission"] == "READY"}
    queue_id = "automatic-20261014-" + sha256(final_raw)[:16]
    queue_state_root = output_root / "queue-state" / queue_id
    queue_state_path = queue_state_root / "queue-state.json"
    if queue_state_path.exists():
        try:
            queue_state = json.loads(queue_state_path.read_bytes())
            jobs = queue_state.get("jobs", {})
            existing_keys = set(jobs)
            existing_queue_ids = {
                str(value.get("queue_id"))
                for value in jobs.values()
                if isinstance(value, dict) and isinstance(value.get("queue_id"), str)
            }
            if existing_keys != expected_ready_keys or existing_queue_ids != {queue_id}:
                raise PlanError("EXISTING_QUEUE_STATE_CONFLICT")
        except PlanError:
            raise
        except Exception as exc:
            raise PlanError("EXISTING_QUEUE_STATE_INVALID") from exc
    queue = queue_module.SerialAnnouncementQueue(
        queue_state_root, queue_id, MODEL_ID, max_attempts=MAX_ATTEMPTS
    )
    for article in manifest["articles"]:
        if article["context_admission"] != "READY":
            continue
        frozen = source_by_id[article["article_id"]]
        metadata = frozen["article_metadata"]
        payload = {
            **{name: frozen[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
            "date": metadata.get("publication_date") or "CANNOT_CONFIRM",
            "market": "HK" if str(metadata.get("symbol", "")).startswith("HK.") else "A_SHARE",
            "prompt_sha256": prompt_sha,
            "model_id": MODEL_ID,
            "configuration_sha256": config_sha,
            "rules": ARTICLE_RULES,
            "role": ARTICLE_ROLE,
            "stage": ARTICLE_STAGE,
            "article_metadata": metadata,
        }
        item = queue.enqueue(payload)
        if item["idempotency_key"] != article["idempotency_key"]:
            raise PlanError("QUEUE_IDENTITY_DIVERGED_FROM_FROZEN_MANIFEST")
    metadata = dict(manifest)
    metadata["input_manifest_sha256"] = sha256(final_raw)
    metadata["population_failures"] = 26
    metadata["queue_id"] = queue_id
    return FrozenPlan(tuple(source_by_id[article["article_id"]] for article in manifest["articles"]), cohort_map, metadata, plan_path)


def _write_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    raw = canonical_json(value) + b"\n"
    _private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise


class RecordingResponse:
    """Record the SSE line stream incrementally while preserving parsed access."""

    def __init__(self, response: Any, path: Path):
        self._response = response
        self.status_code = response.status_code
        self.path = path
        _private_dir(path.parent)
        self._stream = path.open("ab", buffering=0)
        os.chmod(path, 0o600)

    def iter_lines(self):
        try:
            pending = bytearray()
            for chunk in self._response.iter_bytes():
                self._stream.write(chunk)
                self._stream.flush()
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, remainder = pending.partition(b"\n")
                    pending[:] = remainder
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    yield line.decode("utf-8", errors="replace")
            if pending:
                if pending.endswith(b"\r"):
                    pending = pending[:-1]
                yield pending.decode("utf-8", errors="replace")
        finally:
            self._stream.close()


class GatedStreamingTransport(runner.OmlxTransport):
    """Finite no-progress SSE client with a request-level web-source gate."""

    def __init__(self, api_key: str, evidence_root: Path, **kwargs: Any):
        super().__init__(api_key, timeout_seconds=NO_PROGRESS_TIMEOUT_SECONDS, **kwargs)
        self.evidence_root = evidence_root
        self._job: queue_module.QueueJob | None = None
        self._attempt_dir: Path | None = None
        self._round = 0
        self._web_denied = False
        self._web_failed = False
        self._web_contract: tuple[str, str] | None = None
        self._search_urls: set[str] = set()
        self._web_cache: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        self._tool_number = 0
        self._trace_meta: dict[str, Any] = {}

    def begin_job(self, job: queue_module.QueueJob) -> None:
        self._job = job
        self._attempt_dir = self.evidence_root / "streams" / job.idempotency_key / f"attempt-{job.attempt:04d}"
        _private_dir(self._attempt_dir)
        self._round = 0
        self._web_denied = False
        self._web_failed = False
        self._web_contract = None
        self._search_urls = set()
        self._web_cache = {}
        self._tool_number = 0
        self._trace_meta = {"idempotency_key": job.idempotency_key, "attempt": job.attempt, "rounds": [], "tool_receipts": []}

    def finish_job(self, *, status: str, code: str | None = None, completion: Any = None) -> None:
        if self._attempt_dir is None:
            return
        if completion is not None:
            self._trace_meta.update({
                "usage": completion.usage,
                "tool_receipts": completion.tool_receipts,
                "request_rounds": completion.request_rounds,
                "started_at": completion.started_at,
                "finished_at": completion.finished_at,
                "wall_seconds": completion.wall_seconds,
                "ttft_seconds": completion.ttft_seconds,
                "response_model": completion.response_model,
                "final_text_sha256": completion.final_text_sha256,
            })
        self._trace_meta.update({"status": status, "failure_code": code})
        _write_private(self._attempt_dir / "stream-receipt.json", json.dumps(self._trace_meta, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")

    def _stream_completion(self, messages, on_event):
        if self._job is None or self._attempt_dir is None:
            raise runner.TransportError("JOB_CONTEXT_MISSING")
        self._round += 1
        request_body = {
            "model": MODEL_ID,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "tools": runner.make_tool_schema(),
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_COMPLETION_TOKENS,
            "enable_thinking": False,
        }
        turn = runner._StreamTurn()
        trace_path = self._attempt_dir / f"round-{self._round:02d}.raw.sse"
        started = time.monotonic()
        try:
            timeout = self._httpx.Timeout(
                connect=10.0,
                read=NO_PROGRESS_TIMEOUT_SECONDS,
                write=30.0,
                pool=10.0,
            )
            with self._client.stream(
                "POST",
                self._base_url + "/v1/chat/completions",
                headers=self._headers(),
                json=request_body,
                timeout=timeout,
            ) as response:
                recording = RecordingResponse(response, trace_path)
                try:
                    if response.status_code < 200 or response.status_code >= 300:
                        for _line in recording.iter_lines():
                            pass
                        raise runner.TransportError(f"CHAT_HTTP_STATUS:{response.status_code}")
                    runner._parse_sse_stream(recording, turn, on_event)
                finally:
                    if not recording._stream.closed:
                        recording._stream.close()
        except runner.TransportError:
            raw = trace_path.read_bytes() if trace_path.exists() else b""
            self._trace_meta["rounds"].append({
                "round": self._round,
                "raw_sse_path": str(trace_path.relative_to(self.evidence_root)),
                "raw_sse_sha256": sha256(raw),
                "raw_sse_length_bytes": len(raw),
                "finish_reason": turn.finish_reason,
                "usage": turn.usage,
                "response_model": turn.response_model,
                "stream_seconds": round(time.monotonic() - started, 6),
                "status": "FAILED",
            })
            raise
        except Exception as exc:
            code = "CHAT_NO_PROGRESS_TIMEOUT" if isinstance(exc, self._httpx.TimeoutException) else "CHAT_STREAM_INTERRUPTED"
            raw = trace_path.read_bytes() if trace_path.exists() else b""
            self._trace_meta["rounds"].append({
                "round": self._round,
                "raw_sse_path": str(trace_path.relative_to(self.evidence_root)),
                "raw_sse_sha256": sha256(raw),
                "raw_sse_length_bytes": len(raw),
                "finish_reason": turn.finish_reason,
                "usage": turn.usage,
                "response_model": turn.response_model,
                "stream_seconds": round(time.monotonic() - started, 6),
                "status": "FAILED",
                "failure_code": code,
            })
            raise runner.TransportError(f"{code}:{type(exc).__name__}") from None
        elapsed = time.monotonic() - started
        self._trace_meta["rounds"].append({
            "round": self._round,
            "raw_sse_path": str(trace_path.relative_to(self.evidence_root)),
            "raw_sse_sha256": sha256(trace_path.read_bytes()),
            "raw_sse_length_bytes": trace_path.stat().st_size,
            "finish_reason": turn.finish_reason,
            "usage": turn.usage,
            "response_model": turn.response_model,
            "stream_seconds": round(elapsed, 6),
        })
        on_event({"type": "turn_complete", "finish_reason": turn.finish_reason, "usage": turn.usage, "round": self._round})
        return turn

    @staticmethod
    def _failed_tool(name: str, code: str, *, input_sha: str | None = None, status: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {"ok": False, "error": {"code": code}}
        receipt = {
            "name": name,
            "input_sha256": input_sha,
            "result_sha256": sha256(canonical_json(payload)),
            "status": "failed",
            "http_status": status,
            "elapsed_seconds": 0.0,
            "reused_cached_result": False,
            "suppressed_repeat_count": 0,
        }
        return payload, receipt

    def _call_web_tool(self, name: str, args: dict[str, Any], on_event):
        if self._job is None or self._attempt_dir is None:
            return self._failed_tool(name, "job_context_missing")
        if self._web_denied or self._web_failed:
            return self._failed_tool(name, "web_lookup_stopped_after_first_failure")
        clean_args: dict[str, str]
        normalized: str
        input_sha: str
        if name == "web_search":
            raw_query = args.get("query")
            if not isinstance(raw_query, str):
                payload, receipt = self._failed_tool(name, "web_lookup_contract_missing")
                self._web_denied = True
                on_event({"type": "tool_result", "receipt": receipt})
                return payload, receipt
            match = WEB_CONTRACT.fullmatch(raw_query.strip())
            allowed_fields = set(runner.load_active_contract().reader_schema.get("properties", {}))
            if not match or match.group("field") not in allowed_fields or not match.group("fact").strip() or not match.group("query").strip():
                payload, receipt = self._failed_tool(name, "web_lookup_contract_missing")
                self._web_denied = True
                on_event({"type": "tool_result", "receipt": receipt})
                return payload, receipt
            fact = match.group("fact").strip()
            field = match.group("field").strip()
            query = match.group("query").strip()
            self._web_contract = (fact, field)
            clean_args = {"query": query}
            normalized, input_sha = runner._safe_tool_key(name, clean_args)
        elif name == "fetch_url":
            url = args.get("url")
            if self._web_contract is None or not isinstance(url, str):
                payload, receipt = self._failed_tool(name, "web_fetch_without_qualified_search")
                self._web_denied = True
                on_event({"type": "tool_result", "receipt": receipt})
                return payload, receipt
            try:
                normalized, input_sha = runner._safe_tool_key(name, {"url": url})
            except runner.BatchError:
                payload, receipt = self._failed_tool(name, "web_fetch_url_invalid")
                self._web_denied = True
                on_event({"type": "tool_result", "receipt": receipt})
                return payload, receipt
            if normalized not in self._search_urls:
                payload, receipt = self._failed_tool(name, "web_fetch_url_not_from_qualified_search", input_sha=input_sha)
                self._web_denied = True
                on_event({"type": "tool_result", "receipt": receipt})
                return payload, receipt
            clean_args = {"url": url}
        else:
            payload, receipt = self._failed_tool(name, "web_tool_not_allowed")
            self._web_denied = True
            on_event({"type": "tool_result", "receipt": receipt})
            return payload, receipt

        cache_key = (name, normalized)
        if cache_key in self._web_cache:
            payload, old = self._web_cache[cache_key]
            receipt = dict(old)
            receipt["reused_cached_result"] = True
            receipt["suppressed_repeat_count"] = receipt.get("suppressed_repeat_count", 0) + 1
            on_event({"type": "tool_result", "receipt": receipt})
            return payload, receipt

        self._tool_number += 1
        on_event({"type": "tool_call", "name": name, "input_sha256": input_sha})
        started = time.monotonic()
        try:
            response = self._client.post(
                self._base_url + runner._tool_route(name),
                headers=self._headers(),
                json=clean_args,
                timeout=WEB_TIMEOUT_SECONDS,
            )
            raw = response.content
            raw_path = self._attempt_dir / f"tool-{self._tool_number:02d}.raw.json"
            _write_private(raw_path, raw)
            if response.status_code == 200:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = None
            else:
                parsed = None
            if response.status_code == 200 and isinstance(parsed, dict) and parsed.get("ok") is True:
                payload = parsed
                if name == "web_search":
                    self._search_urls.update(_extract_urls(payload))
            else:
                payload = {"ok": False, "error": {"code": "web_http_or_payload_error"}}
            http_status = response.status_code
        except Exception as exc:
            raw = canonical_json({"ok": False, "error": {"code": "transport_error", "kind": type(exc).__name__}})
            raw_path = self._attempt_dir / f"tool-{self._tool_number:02d}.raw.json"
            _write_private(raw_path, raw)
            payload = {"ok": False, "error": {"code": "transport_error", "kind": type(exc).__name__}}
            http_status = None
        elapsed = time.monotonic() - started
        if payload.get("ok") is not True:
            self._web_failed = True
        result_sha = sha256(canonical_json(payload))
        receipt = {
            "name": name,
            "input_sha256": input_sha,
            "result_sha256": result_sha,
            "raw_source_path": str(raw_path.relative_to(self.evidence_root)),
            "raw_source_sha256": sha256(raw),
            "status": "ok" if payload.get("ok") is True else "failed",
            "http_status": http_status,
            "elapsed_seconds": round(elapsed, 3),
            "reused_cached_result": False,
            "suppressed_repeat_count": 0,
            "qualified_missing_fact_sha256": sha256(self._web_contract[0].encode("utf-8")) if self._web_contract else None,
            "affected_reader_field": self._web_contract[1] if self._web_contract else None,
        }
        self._web_cache[cache_key] = (payload, receipt)
        self._trace_meta["tool_receipts"].append(receipt)
        on_event({"type": "tool_result", "receipt": receipt})
        return payload, receipt


def _extract_urls(value: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "source_url"} and isinstance(item, str):
                urls.add(item)
            else:
                urls.update(_extract_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.update(_extract_urls(item))
    return urls


class AdminSession:
    """Reads only authenticated activity/model health; credentials stay in memory."""

    def __init__(self, api_key: str, *, client: Any | None = None):
        try:
            import httpx
        except Exception as exc:
            raise PlanError("HTTPX_UNAVAILABLE") from exc
        self._httpx = httpx
        self._key = api_key
        self._client = client or httpx.Client(base_url=runner.OMLX_BASE_URL, timeout=5.0, trust_env=False)
        self._logged_in = False

    def login(self) -> None:
        response = self._client.post("/admin/api/login", json={"api_key": self._key})
        if response.status_code != 200:
            raise PlanError("ADMIN_SESSION_LOGIN_FAILED")
        self._logged_in = True

    def _json(self, path: str) -> dict[str, Any]:
        if not self._logged_in:
            self.login()
        response = self._client.get(path)
        if response.status_code != 200:
            raise PlanError("ADMIN_PREFLIGHT_HTTP_ERROR")
        value = response.json()
        if not isinstance(value, dict):
            raise PlanError("ADMIN_PREFLIGHT_RESPONSE_INVALID")
        return value

    def activity(self) -> tuple[int, int]:
        value = self._json("/admin/api/activity")
        active, waiting = value.get("active"), value.get("waiting")
        active_models = value.get("active_models")
        if isinstance(active_models, dict):
            active = active_models.get("total_active_requests")
            waiting = active_models.get("total_waiting_requests")
        if type(active) is not int or type(waiting) is not int or active < 0 or waiting < 0:
            raise PlanError("ACTIVITY_STATE_UNVERIFIABLE")
        return active, waiting

    def model_ready(self) -> bool:
        value = self._json("/admin/api/models")
        models = value.get("models")
        if isinstance(models, dict):
            entry = models.get(MODEL_ID)
            return isinstance(entry, dict) and entry.get("loaded") is True and entry.get("is_loading") is False
        if isinstance(models, list):
            for entry in models:
                if isinstance(entry, dict) and entry.get("id", entry.get("model_id")) == MODEL_ID:
                    return entry.get("loaded") is True and entry.get("is_loading") is False
        return False

    def close(self) -> None:
        self._client.close()


class AutomaticCanaryController:
    def __init__(
        self,
        plan: FrozenPlan,
        *,
        queue: Any,
        activity_probe: Callable[[], tuple[int, int]],
        model_ready_probe: Callable[[], bool],
        api_key: str,
        transport_factory: Callable[[str, Path], GatedStreamingTransport] | None = None,
        idle_timeout_seconds: float = IDLE_WAIT_SECONDS,
    ):
        self.plan = plan
        self.evidence_root = plan.manifest_path.parent.resolve()
        self.queue = queue
        self.activity_probe = activity_probe
        self.model_ready_probe = model_ready_probe
        self._api_key = api_key
        self.transport_factory = transport_factory or (
            lambda key, root: GatedStreamingTransport(key, root)
        )
        self.idle_timeout_seconds = idle_timeout_seconds
        self._lock = threading.RLock()
        self._started = False
        self._finished = True
        self._launching = False
        self._stop_requested = False
        self._worker: threading.Thread | None = None
        self._phase = "CANARY_NOT_STARTED"
        self._phase_states = {name: "NOT_STARTED" for name in plan.cohorts}
        self._active_phase: str | None = None
        self._pressure_gate: dict[str, Any] | None = None
        self._state_path = Path(queue.state_root).resolve() / "controller-state.json"
        self._stop_code: str | None = None
        self._current: dict[str, Any] | None = None
        self._metrics: dict[str, dict[str, Any]] = {}
        self._started_at: str | None = None
        self._last_error: str | None = None
        self._load_controller_state()

    def _persist_state_locked(self) -> None:
        state = {
            "schema": "qwen_flash_next.automatic_canary_controller_state.v1",
            "queue_id": getattr(self.queue, "queue_id", self.plan.metadata.get("queue_id")),
            "input_manifest_sha256": self.plan.metadata["input_manifest_sha256"],
            "state": self._phase,
            "phases": dict(self._phase_states),
            "active_phase": self._active_phase,
            "pressure_gate": self._pressure_gate,
            "stop_code": self._stop_code,
            "started_at_utc": self._started_at,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        _write_private(self._state_path, json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")

    def _load_controller_state(self) -> None:
        if not self._state_path.exists():
            with self._lock:
                self._persist_state_locked()
            return
        try:
            state = json.loads(self._state_path.read_bytes())
        except Exception as exc:
            raise PlanError("CONTROLLER_STATE_INVALID") from exc
        expected_phases = set(self.plan.cohorts)
        phases = state.get("phases") if isinstance(state, dict) else None
        if (
            not isinstance(state, dict)
            or state.get("schema") != "qwen_flash_next.automatic_canary_controller_state.v1"
            or state.get("input_manifest_sha256") != self.plan.metadata["input_manifest_sha256"]
            or not isinstance(phases, dict)
            or set(phases) != expected_phases
        ):
            raise PlanError("CONTROLLER_STATE_MISMATCH")
        if getattr(self.queue, "queue_id", state.get("queue_id")) != state.get("queue_id"):
            raise PlanError("CONTROLLER_QUEUE_ID_MISMATCH")
        gate = state.get("pressure_gate")
        if gate is not None and (
            not isinstance(gate, dict)
            or gate.get("accepted") is not True
            or gate.get("confirmation") != PRESSURE_CONFIRMATION_PHRASE
            or gate.get("automated_semantic_review") is not False
        ):
            raise PlanError("PRESSURE_GATE_STATE_INVALID")
        active_phase = state.get("active_phase")
        if active_phase not in {None, *expected_phases}:
            raise PlanError("CONTROLLER_ACTIVE_PHASE_INVALID")
        with self._lock:
            self._phase_states = dict(phases)
            self._active_phase = active_phase
            self._pressure_gate = gate
            self._phase = state.get("state", "CANARY_NOT_STARTED")
            self._stop_code = state.get("stop_code")
            self._started_at = state.get("started_at_utc")
            if self._phase in {"CANARY_RUNNING", "PRESSURE_RUNNING", "BOUNDED_RETRY_RUNNING"}:
                if not active_phase:
                    raise PlanError("CONTROLLER_ACTIVE_PHASE_MISSING")
                interrupted = "CANARY" if active_phase == "canary_A_and_B_union" else "PRESSURE"
                self._phase = f"{interrupted}_INTERRUPTED_AWAITING_RESUME"
                self._phase_states[active_phase] = "INTERRUPTED_AWAITING_RESUME"
            self._started = False
            self._finished = True
            self._stop_requested = False
            self._persist_state_locked()

    def _phase_progress(self, phase_name: str, queue_items: list[dict[str, Any]]) -> dict[str, int]:
        article_ids = set(self.plan.cohorts[phase_name])
        keys = {
            row["idempotency_key"]
            for row in self.plan.metadata["articles"]
            if row["article_id"] in article_ids
        }
        selected = [item for item in queue_items if item.get("idempotency_key") in keys]
        succeeded = sum(item.get("status") == "SUCCEEDED" for item in selected)
        failed = sum(item.get("status") in {"FAILED", "OVERSIZE", "MISSING_MATERIAL"} for item in selected)
        running = sum(item.get("status") == "RUNNING" for item in selected)
        overlap_ids = set(self.plan.cohorts.get("canary_A_and_B_union", ())) & set(self.plan.cohorts.get("pressure_batch_03", ()))
        overlap_keys = {
            row["idempotency_key"]
            for row in self.plan.metadata["articles"]
            if row["article_id"] in overlap_ids
        }
        return {
            "total": len(article_ids),
            "succeeded": succeeded,
            "failed": failed,
            "running": running,
            "remaining": max(0, len(article_ids) - succeeded - failed - running),
            "reused_successes": sum(
                item.get("idempotency_key") in overlap_keys and item.get("status") == "SUCCEEDED"
                for item in selected
            ) if phase_name == "pressure_batch_03" else 0,
        }

    def _canary_gate_ready(self) -> bool:
        queue_items = self.queue.snapshot()["items"]
        progress = self._phase_progress("canary_A_and_B_union", queue_items)
        return (
            self._phase_states.get("canary_A_and_B_union") == "WAITING_QUALITY_REVIEW"
            and progress["total"] == 6
            and progress["succeeded"] == 6
            and progress["failed"] == 0
            and progress["remaining"] == 0
        )

    def _preflight(self) -> bool:
        if not self._wait_idle(timeout=0.0):
            return False
        try:
            if not self.model_ready_probe():
                self._stop_code = "FLASH_MODEL_NOT_LOADED"
                return False
        except Exception:
            self._stop_code = "MODEL_READY_STATE_UNVERIFIABLE"
            return False
        return True

    def _launch_phase(self, phase_name: str, *, retry_keys: set[str] | None = None) -> None:
        self._started = True
        self._finished = False
        self._stop_requested = False
        self._stop_code = None
        self._active_phase = phase_name
        self._phase = "CANARY_RUNNING" if phase_name == "canary_A_and_B_union" else "PRESSURE_RUNNING"
        self._phase_states[phase_name] = "RUNNING"
        self._started_at = self._started_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self._persist_state_locked()
        _write_jsonl(self.evidence_root / "ui-phase-trigger-events.jsonl", {
            "schema": "qwen_flash_next.automatic_canary_phase_trigger.v1",
            "trigger": "same_origin_visible_ui_phase_action",
            "phase": phase_name,
            "input_manifest_sha256": self.plan.metadata["input_manifest_sha256"],
            "at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "retry_key_sha256": sha256(canonical_json(sorted(retry_keys))) if retry_keys is not None else None,
            "inference_started_before_trigger": False,
        })
        self._worker = threading.Thread(
            target=self._run,
            kwargs={"phase_name": phase_name, "retry_keys": retry_keys},
            name=f"flash-next-{phase_name}",
            daemon=True,
        )
        self._worker.start()

    def _wait_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        first_check = True
        while first_check or time.monotonic() <= deadline:
            first_check = False
            try:
                active, waiting = self.activity_probe()
            except Exception:
                self._stop_code = "ACTIVITY_STATE_UNVERIFIABLE"
                return False
            if active == 0 and waiting == 0:
                return True
            if time.monotonic() > deadline:
                break
            time.sleep(0.5)
        self._stop_code = "EXTERNAL_OR_STUCK_ACTIVITY_PRESENT"
        return False

    def start(self) -> bool:
        with self._lock:
            if self._started or self._launching:
                return False
            if self._active_phase == "pressure_batch_03" and self._pressure_gate:
                phase_name = "pressure_batch_03"
                allowed_states = {"PRESSURE_INTERRUPTED_AWAITING_RESUME", "PRESSURE_STOPPED_AFTER_CURRENT", "PAUSED_ACTIVITY_UNVERIFIED"}
            else:
                phase_name = "canary_A_and_B_union"
                allowed_states = {"CANARY_NOT_STARTED", "CANARY_INTERRUPTED_AWAITING_RESUME", "CANARY_STOPPED_AFTER_CURRENT"}
                if self._phase == "PAUSED_ACTIVITY_UNVERIFIED" and self._active_phase == phase_name:
                    allowed_states.add("PAUSED_ACTIVITY_UNVERIFIED")
            if self._phase not in allowed_states:
                self._stop_code = "PHASE_NOT_READY_FOR_START"
                self._persist_state_locked()
                return False
            self._launching = True
        if not self._preflight():
            with self._lock:
                self._launching = False
                self._persist_state_locked()
            return False
        with self._lock:
            if self._started or self._phase not in allowed_states:
                self._launching = False
                self._stop_code = "PHASE_STATE_CHANGED_DURING_START"
                self._persist_state_locked()
                return False
            self._launch_phase(phase_name)
            self._launching = False
        return True

    def authorize_pressure(self, confirmation: str) -> bool:
        with self._lock:
            if self._started or self._launching or self._pressure_gate is not None or confirmation != PRESSURE_CONFIRMATION_PHRASE:
                self._stop_code = "PRESSURE_GATE_CONFIRMATION_INVALID_OR_ALREADY_USED"
                self._persist_state_locked()
                return False
            if not self._canary_gate_ready():
                self._stop_code = "CANARY_NOT_COMPLETE_OR_FAILED"
                self._persist_state_locked()
                return False
            self._launching = True
        if not self._preflight():
            with self._lock:
                self._launching = False
                self._persist_state_locked()
            return False
        with self._lock:
            if self._started or self._pressure_gate is not None or not self._canary_gate_ready():
                self._launching = False
                self._stop_code = "PRESSURE_GATE_STATE_CHANGED"
                self._persist_state_locked()
                return False
            accepted_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            canary_progress = self._phase_progress("canary_A_and_B_union", self.queue.snapshot()["items"])
            self._pressure_gate = {
                "accepted": True,
                "gate_kind": "explicit_user_ui_confirmation",
                "confirmation": PRESSURE_CONFIRMATION_PHRASE,
                "accepted_at_utc": accepted_at,
                "canary_succeeded_count": canary_progress["succeeded"],
                "canary_failed_count": canary_progress["failed"],
                "automated_semantic_review": False,
            }
            _write_jsonl(self.evidence_root / "ui-pressure-gate-events.jsonl", {
                "schema": "qwen_flash_next.automatic_canary_pressure_gate.v1",
                **self._pressure_gate,
                "input_manifest_sha256": self.plan.metadata["input_manifest_sha256"],
            })
            self._launch_phase("pressure_batch_03")
            self._launching = False
        return True

    def stop(self) -> bool:
        with self._lock:
            if not self._started or self._finished:
                return False
            self._stop_requested = True
            self._persist_state_locked()
            return True

    def resume_failed(self) -> bool:
        with self._lock:
            if self._started or self._launching:
                return False
            if self._pressure_gate is not None:
                phase_name = "pressure_batch_03"
            else:
                phase_name = "canary_A_and_B_union"
            self._launching = True
        if not self._preflight():
            with self._lock:
                self._launching = False
                self._persist_state_locked()
            return False
        phase_ids = set(self.plan.cohorts[phase_name])
        frozen_keys = {
            row["idempotency_key"]
            for row in self.plan.metadata["articles"]
            if row["article_id"] in phase_ids
        }
        keys = [
            item["idempotency_key"]
            for item in self.queue.snapshot()["items"]
            if item["idempotency_key"] in frozen_keys and item["status"] == "FAILED"
        ]
        retry_keys = self.queue.retry_failed(keys)
        if not retry_keys:
            with self._lock:
                self._launching = False
            return False
        with self._lock:
            _write_jsonl(self.evidence_root / "ui-retry-events.jsonl", {
                "schema": "qwen_flash_next.automatic_canary_retry_trigger.v1",
                "at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "retryable_count": len(retry_keys),
                "retry_key_sha256": sha256(canonical_json(sorted(retry_keys))),
                "trigger": "same_origin_visible_ui_bounded_retry",
            })
            self._launch_phase(phase_name, retry_keys=set(retry_keys))
            self._launching = False
        return True

    def _on_event(self, key: str, started: float, event: Mapping[str, Any]) -> None:
        with self._lock:
            metrics = self._metrics.setdefault(key, {"partial_text": "", "tool_receipts": [], "rounds": []})
            if event.get("type") == "first_event" and metrics.get("ttft_seconds") is None:
                metrics["ttft_seconds"] = round(time.monotonic() - started, 3)
            elif event.get("type") == "answer_chunk":
                text = event.get("text")
                if isinstance(text, str):
                    metrics["partial_text"] += text
            elif event.get("type") == "tool_result" and isinstance(event.get("receipt"), dict):
                metrics["tool_receipts"].append(dict(event["receipt"]))
            elif event.get("type") == "turn_complete":
                metrics["rounds"].append({"finish_reason": event.get("finish_reason"), "usage": event.get("usage")})

    def _execute(self, transport: GatedStreamingTransport, job: queue_module.QueueJob) -> str:
        transport.begin_job(job)
        article = {
            "article_id": job.payload["article_id"],
            "source_sha256": job.payload["source_sha256"],
            "body_sha256": job.payload["body_sha256"],
            "article_body": job.payload["article_body"],
            "article_metadata": job.payload["article_metadata"],
        }
        batch_id = "AUTO_" + sha256(article["article_id"].encode("utf-8"))[:20]
        batch = length_canary.make_batch([article], batch_id)
        frozen_row = next((row for row in self.plan.metadata["articles"] if row["article_id"] == article["article_id"]), None)
        if frozen_row is None or runner._input_batch_sha(batch) != frozen_row["input_sha256"]:
            raise queue_module.ExecutorFailure("INPUT_MANIFEST_DIVERGED", code="INPUT_MANIFEST_DIVERGED", raw_response=b"")
        messages = runner.build_messages(batch, runner.load_active_contract(), PROFILE)
        started = time.monotonic()
        with self._lock:
            self._current = {"article_id": article["article_id"], "title": article["article_metadata"].get("title"), "status": "RUNNING", "started_monotonic": started}
        try:
            completion = transport.complete_batch(messages, on_event=lambda event: self._on_event(job.idempotency_key, started, event))
        except Exception as exc:
            code = _stable_failure_code(exc, "MODEL_REQUEST_FAILED")
            stream_paths = sorted((transport._attempt_dir or Path()).glob("round-*.raw.sse")) if transport._attempt_dir else []
            partial = stream_paths[-1].read_bytes() if stream_paths and stream_paths[-1].exists() else None
            transport.finish_job(status="FAILED", code=code)
            raise queue_module.ExecutorFailure(code, code=code, raw_response=partial) from None
        transport.finish_job(status="RESPONSE_RECEIVED", completion=completion)
        metrics = self._metrics.setdefault(job.idempotency_key, {})
        metrics.update({
            "ttft_seconds": completion.ttft_seconds,
            "wall_seconds": completion.wall_seconds,
            "usage": completion.usage,
            "response_model": completion.response_model,
            "finish_reason": transport._trace_meta.get("rounds", [{}])[-1].get("finish_reason"),
            "completion_tps_estimate": None,
        })
        usage = completion.usage or {}
        token_count = usage.get("completion_tokens")
        generation_seconds = sum(float(row.get("stream_seconds", 0)) for row in transport._trace_meta.get("rounds", []))
        if isinstance(token_count, int) and generation_seconds > 0:
            metrics["completion_tps_estimate"] = round(token_count / generation_seconds, 3)
        if not completion.final_text:
            raise queue_module.ExecutorFailure("EMPTY_MODEL_OUTPUT", code="EMPTY_MODEL_OUTPUT", raw_response=b"")
        return completion.final_text

    def _validate(self, job: queue_module.QueueJob, parsed: Any) -> Any:
        batch = length_canary.make_batch([
            {name: job.payload[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body", "article_metadata")}
        ], "AUTO_" + sha256(job.payload["article_id"].encode("utf-8"))[:20])
        raw_text = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        valid, errors = runner._validate_batch_output(raw_text, batch, runner.load_active_contract())
        article_id = job.payload["article_id"]
        if errors or set(valid) != {article_id}:
            code = errors.get(article_id, "MODEL_OUTPUT_VALIDATION_REJECTED")
            raise queue_module.ValidationRejected(code, code=code)
        return {"article_id": article_id, "reader_output": valid[article_id]}

    def _run_phase(self, transport: GatedStreamingTransport, phase_name: str, article_ids: tuple[str, ...], restrict: set[str] | None) -> bool:
        keys = {article["idempotency_key"] for article in self.plan.metadata["articles"] if article["article_id"] in set(article_ids)}
        if restrict is not None:
            keys &= restrict
        with self._lock:
            if not keys:
                self._phase_states[phase_name] = "NO_RETRYABLE_FAILURES"
                self._persist_state_locked()
                return True
            self._phase_states[phase_name] = "RUNNING"
            self._active_phase = phase_name
            self._phase = "CANARY_RUNNING" if phase_name == "canary_A_and_B_union" else "PRESSURE_RUNNING"
            self._persist_state_locked()
        while not self._stop_requested:
            if not self._wait_idle(self.idle_timeout_seconds):
                with self._lock:
                    self._phase_states[phase_name] = "PAUSED_ACTIVITY_UNVERIFIED"
                    self._phase = "PAUSED_ACTIVITY_UNVERIFIED"
                    self._persist_state_locked()
                return False
            result = self.queue.run_next(
                lambda job: self._execute(transport, job),
                self._validate,
                wait_for_model_slot=False,
                idempotency_keys=keys,
            )
            if result is None:
                break
            with self._lock:
                key = result["idempotency_key"]
                metric = self._metrics.get(key, {})
                metric["status"] = result["status"]
                metric["attempt_count"] = result["attempt_count"]
                metric["error_code"] = (result.get("last_error") or {}).get("code")
                metric["raw_sha256"] = result.get("raw_sha256")
                metric["validated_sha256"] = result.get("validated_sha256")
                metric["wall_seconds"] = metric.get("wall_seconds") or (result.get("attempts") or [{}])[-1].get("duration_seconds")
                self._metrics[key] = metric
                self._current = None
            # The request has ended from the client's view. Verify oMLX is idle
            # before the next article; this also closes the timeout/disconnect ambiguity.
            if not self._wait_idle(self.idle_timeout_seconds):
                with self._lock:
                    self._phase_states[phase_name] = "PAUSED_ACTIVITY_UNVERIFIED"
                    self._phase = "PAUSED_ACTIVITY_UNVERIFIED"
                    self._persist_state_locked()
                return False
            if self._stop_requested:
                break
        with self._lock:
            if self._stop_requested:
                self._phase_states[phase_name] = "STOPPED_AFTER_CURRENT"
                self._phase = "CANARY_STOPPED_AFTER_CURRENT" if phase_name == "canary_A_and_B_union" else "PRESSURE_STOPPED_AFTER_CURRENT"
            else:
                progress = self._phase_progress(phase_name, self.queue.snapshot()["items"])
                if phase_name == "canary_A_and_B_union":
                    if progress["total"] == 6 and progress["succeeded"] == 6 and progress["failed"] == 0 and progress["remaining"] == 0:
                        self._phase_states[phase_name] = "WAITING_QUALITY_REVIEW"
                        self._phase = "WAITING_QUALITY_REVIEW"
                    else:
                        self._phase_states[phase_name] = "FAILED_WAITING_REVIEW"
                        self._phase = "CANARY_FAILED_WAITING_REVIEW"
                elif progress["succeeded"] == progress["total"] and progress["failed"] == 0 and progress["remaining"] == 0:
                    self._phase_states[phase_name] = "QUEUE_DRAINED"
                    self._phase = "PRESSURE_FINISHED"
                else:
                    self._phase_states[phase_name] = "FAILED"
                    self._phase = "PRESSURE_FAILED"
            self._persist_state_locked()
        return not self._stop_requested

    def _run(self, *, phase_name: str, retry_keys: set[str] | None = None) -> None:
        transport = None
        try:
            transport = self.transport_factory(self._api_key, self.evidence_root)
            self._run_phase(transport, phase_name, self.plan.cohorts[phase_name], retry_keys)
        except Exception as exc:
            code = _stable_failure_code(exc, "AUTOMATION_RUNNER_ERROR")
            with self._lock:
                self._stop_code = code
                self._last_error = code
                if self._phase_states.get(phase_name) == "RUNNING":
                    self._phase_states[phase_name] = "FAILED_WAITING_REVIEW" if phase_name == "canary_A_and_B_union" else "FAILED"
                    self._phase = "CANARY_FAILED_WAITING_REVIEW" if phase_name == "canary_A_and_B_union" else "PRESSURE_FAILED"
                self._persist_state_locked()
        finally:
            if transport is not None:
                transport.close()
            with self._lock:
                self._finished = True
                self._started = False
                queue_snapshot = self.queue.snapshot()
                receipt = {
                    "schema": "qwen_flash_next.automatic_canary_run_receipt.v1",
                    "status": self._phase,
                    "stop_code": self._stop_code,
                    "started_at_utc": self._started_at,
                    "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "model_id": MODEL_ID,
                    "prompt_profile": PROFILE,
                    "input_manifest_sha256": self.plan.metadata["input_manifest_sha256"],
                    "source_population_count": 277,
                    "capture_failure_count": 26,
                    "scheduled_unique_count": len(self.plan.records),
                "queue_ready_count": sum(1 for row in self.plan.metadata["articles"] if row["context_admission"] == "READY"),
                    "queue_status_counts": queue_snapshot["status_counts"],
                    "phases": dict(self._phase_states),
                    "pressure_gate": self._pressure_gate,
                    "pressure_gate_accepted": self._pressure_gate is not None,
                    "semantic_quality": "NOT_ASSESSED_BY_AUTOMATION",
                    "research_only": True,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
                _write_private(self.evidence_root / "automatic-run-receipt.json", json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
                self._persist_state_locked()

    def snapshot(self) -> dict[str, Any]:
        queue_snapshot = self.queue.snapshot()
        queue_items = {item["idempotency_key"]: item for item in queue_snapshot["items"]}
        article_meta = {row["idempotency_key"]: row for row in self.plan.metadata["articles"]}
        items = []
        for key, frozen in article_meta.items():
            queued = queue_items.get(key, {})
            metric = self._metrics.get(key, {})
            items.append({
                "idempotency_key": key,
                "article_id": frozen["article_id"],
                "title": next((article["article_metadata"].get("title") for article in self.plan.records if article["article_id"] == frozen["article_id"]), None),
                "cohorts": [name for name, ids in self.plan.cohorts.items() if frozen["article_id"] in ids],
                "context_admission": frozen["context_admission"],
                "prompt_tokens_exact": frozen["prompt_tokens_exact"],
                "status": queued.get("status", frozen["context_admission"]),
                "attempt_count": queued.get("attempt_count", 0),
                "max_attempts": queued.get("max_attempts", MAX_ATTEMPTS),
                "error_code": ((queued.get("last_error") or {}).get("code") or metric.get("error_code")),
                "wall_seconds": metric.get("wall_seconds"),
                "ttft_seconds": metric.get("ttft_seconds"),
                "completion_tps_estimate": metric.get("completion_tps_estimate"),
                "usage": metric.get("usage"),
                "raw_sha256": queued.get("raw_sha256"),
                "raw_available": bool(queued.get("raw_path")),
                "validated_sha256": queued.get("validated_sha256"),
                "finish_reason": metric.get("finish_reason"),
            })
        counts = {status: 0 for status in queue_module.STATUSES}
        for item in queue_snapshot["items"]:
            counts[item["status"]] += 1
        with self._lock:
            phase_progress = {
                name: self._phase_progress(name, queue_snapshot["items"])
                for name in self.plan.cohorts
            }
            canary_ready = self._canary_gate_ready()
            state = {
                "schema": "qwen_flash_next.automatic_canary_status.v1",
                "state": self._phase,
                "started": self._started,
                "finished": self._finished,
                "stop_code": self._stop_code,
                "started_at_utc": self._started_at,
                "source_population_count": 277,
                "capture_failure_count": 26,
                "scheduled_unique_count": len(self.plan.records),
                "queue_ready_count": sum(1 for row in self.plan.metadata["articles"] if row["context_admission"] == "READY"),
                "context_unfit_count": len(self.plan.metadata.get("context_rejections", [])),
                "queue_status_counts": counts,
                "phases": dict(self._phase_states),
                "phase_progress": phase_progress,
                "pressure_gate_accepted": self._pressure_gate is not None,
                "pressure_gate_available": canary_ready and not self._started and self._pressure_gate is None,
                "pressure_gate": self._pressure_gate,
                "input_manifest_sha256": self.plan.metadata["input_manifest_sha256"],
                "items": items,
                "cohort_overlap_count": len(set(self.plan.cohorts["canary_A_and_B_union"]) & set(self.plan.cohorts["pressure_batch_03"])),
                "current": ({
                    "article_id": self._current.get("article_id"),
                    "title": self._current.get("title"),
                    "status": self._current.get("status"),
                    "elapsed_seconds": round(time.monotonic() - self._current["started_monotonic"], 3),
                    "ttft_seconds": self._metrics.get(next((k for k, row in article_meta.items() if row["article_id"] == self._current.get("article_id")), ""), {}).get("ttft_seconds"),
                    "partial_text": self._metrics.get(next((k for k, row in article_meta.items() if row["article_id"] == self._current.get("article_id")), ""), {}).get("partial_text", ""),
                    "completion_tps_estimate": self._metrics.get(next((k for k, row in article_meta.items() if row["article_id"] == self._current.get("article_id")), ""), {}).get("completion_tps_estimate"),
                } if self._current else None),
                "raw_output_is_original": True,
                "semantic_quality": "NOT_ASSESSED_BY_AUTOMATION",
                "external_model_clients_serialized": False,
            }
        return state

    def raw_result(self, key: str) -> bytes | None:
        item = next((x for x in self.queue.snapshot()["items"] if x["idempotency_key"] == key), None)
        if not item or not item.get("raw_path"):
            return None
        root = self.queue.state_root.resolve()
        path = Path(item["raw_path"]).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path.read_bytes()


HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-__NONCE__'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"><title>Flash Next 临时自动化测试</title><style>body{font:15px system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#15202b}button{margin:0 .5rem .8rem 0;padding:.55rem 1rem}button:disabled{opacity:.45}.phase{border:1px solid #ccd5de;padding:.7rem;margin:.5rem 0}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #d9e0e7;padding:.4rem;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:28rem;overflow:auto;background:#f2f5f7;padding:.75rem}</style></head><body><h1>Flash Next 临时自动化测试</h1><p><b>研究测试 / 未正式接入。</b>先运行6篇 canary。全部成功后停在独立质量复核门；只有明确点击“已独立核验，运行压力29”才会启动压力 batch 03。两阶段重叠1篇按文章身份复用成功结果，最多新增28篇请求。此按钮记录人的确认，不代表自动语义审核。完整277篇只作来源覆盖统计，另有26篇正文采集失败。</p><p>进度按阶段展示已成功、失败和剩余数。进程重启后保留当前阶段和门状态；需要可见点击继续，启动时不会自动推理。本进程只串行化自己的本地队列，运行期间请勿从其他客户端提交模型请求。</p><div id="status">正在读取队列状态…</div><div id="progress"></div><div id="current"></div><p><button id="start">Start：运行 / 继续当前阶段</button><button id="gate">已独立核验，运行压力29</button><button id="stop">停止后续排队（当前请求结束后生效）</button><button id="retry">有界重试失败项</button></p><h2>队列进度</h2><table><thead><tr><th>文章 / 阶段</th><th>状态</th><th>用时 / 首流事件（非首字） / tok/s估计</th><th>失败码 / 原始结果</th></tr></thead><tbody id="items"></tbody></table><div id="raw"></div><script nonce="__NONCE__">const csrf="__CSRF__";const phrase="已独立核验，运行压力29";async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...(opts.headers||{}),...(opts.method?{"X-Canary-CSRF":csrf,"Content-Type":"application/json"}:{})}});const j=await r.json();if(!r.ok)throw new Error(j.code||"request_failed");return j}function fmt(v){return v==null?"—":String(v)}function render(s){document.getElementById('status').textContent=`${s.state} · ${s.scheduled_unique_count}篇唯一文章 / 可运行${s.queue_ready_count}篇 / 不适配${s.context_unfit_count}篇 · 全量来源277完整、26失败 · 队列 ${JSON.stringify(s.queue_status_counts)} · 停止码 ${s.stop_code||'—'}`;const progress=document.getElementById('progress');progress.replaceChildren();for(const [name,x] of Object.entries(s.phase_progress||{})){const p=document.createElement('p');p.textContent=`${name}: ${s.phases[name]} · 完成 ${x.succeeded}/${x.total} · 失败 ${x.failed} · 运行 ${x.running} · 剩余 ${x.remaining}${x.reused_successes?` · 复用重叠成功 ${x.reused_successes}`:''}`;progress.appendChild(p)}document.getElementById('gate').disabled=!s.pressure_gate_available;document.getElementById('start').disabled=s.started||['WAITING_QUALITY_REVIEW','CANARY_FAILED_WAITING_REVIEW','PRESSURE_FINISHED','PRESSURE_FAILED'].includes(s.state);const cur=document.getElementById('current');cur.replaceChildren();if(s.current){const h=document.createElement('p');h.textContent=`当前：${s.current.title||s.current.article_id} · ${s.current.article_id} · ${s.current.status} · ${fmt(s.current.elapsed_seconds)}s / 首流事件（非首字） ${fmt(s.current.ttft_seconds)}s / tok/s ${fmt(s.current.completion_tps_estimate)}`;const pre=document.createElement('pre');pre.textContent=s.current.partial_text||'';cur.append(h,pre)}const body=document.getElementById('items');body.replaceChildren();for(const x of s.items){const tr=document.createElement('tr');const first=document.createElement('td');first.textContent=`${x.title||x.article_id} · ${x.article_id} · ${(x.cohorts||[]).join(', ')}`;const second=document.createElement('td');second.textContent=`${x.status} · ${x.attempt_count}/${x.max_attempts} · ${x.prompt_tokens_exact||0} prompt tokens`;const third=document.createElement('td');third.textContent=`${fmt(x.wall_seconds)}s / ${fmt(x.ttft_seconds)}s / ${fmt(x.completion_tps_estimate)}`;const fourth=document.createElement('td');fourth.textContent=x.error_code||'';if(x.raw_available){const b=document.createElement('button');b.textContent='查看原始结果';b.onclick=async()=>{const r=await fetch('/api/raw?key='+encodeURIComponent(x.idempotency_key));const t=await r.text();const box=document.createElement('pre');box.textContent=t;document.getElementById('raw').replaceChildren(box)};fourth.appendChild(b)}tr.append(first,second,third,fourth);body.appendChild(tr)}}async function refresh(){try{render(await api('/api/status'))}catch(e){document.getElementById('status').textContent='状态读取失败：'+String(e.message)}}document.getElementById('start').onclick=async()=>{try{await api('/api/start',{method:'POST',body:'{}'});await refresh()}catch(e){alert(String(e.message))}};document.getElementById('gate').onclick=async()=>{try{await api('/api/approve-pressure',{method:'POST',body:JSON.stringify({confirmation:phrase})});await refresh()}catch(e){alert(String(e.message))}};document.getElementById('stop').onclick=async()=>{try{await api('/api/stop',{method:'POST',body:'{}'});await refresh()}catch(e){alert(String(e.message))}};document.getElementById('retry').onclick=async()=>{try{await api('/api/retry',{method:'POST',body:'{}'});await refresh()}catch(e){alert(String(e.message))}};refresh();setInterval(refresh,1500);</script></body></html>"""


def make_handler(controller: AutomaticCanaryController, csrf_token: str):
    expected_origin = None

    class Handler(BaseHTTPRequestHandler):
        server_version = "FlashNextTemporaryCanary/1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Do not log request bodies, query values, or credentials.
            return

        def _send(self, status: int, content_type: str, raw: bytes, *, extra: Mapping[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(raw)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def _json(self, status: int, value: Mapping[str, Any]) -> None:
            self._send(status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                nonce = secrets.token_urlsafe(18)
                page = HTML.replace("__NONCE__", nonce).replace("__CSRF__", csrf_token).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", page)
                return
            if parsed.path == "/api/status":
                self._json(200, controller.snapshot())
                return
            if parsed.path == "/api/raw":
                query = parse_qs(parsed.query)
                key = query.get("key", [""])[0]
                raw = controller.raw_result(key)
                if raw is None:
                    self._json(404, {"code": "RAW_RESULT_NOT_FOUND"})
                else:
                    self._send(200, "text/plain; charset=utf-8", raw)
                return
            self._json(404, {"code": "NOT_FOUND"})

        def do_POST(self) -> None:
            parsed = urlsplit(self.path)
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            expected = f"http://{host}"
            if not host.startswith("127.0.0.1:") or origin != expected:
                self._json(403, {"code": "SAME_ORIGIN_REQUIRED"})
                return
            if self.headers.get("X-Canary-CSRF") != csrf_token:
                self._json(403, {"code": "CSRF_TOKEN_INVALID"})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"code": "JSON_REQUIRED"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0 or length > 1024:
                self._json(413, {"code": "REQUEST_TOO_LARGE"})
                return
            body_raw = self.rfile.read(length)
            if parsed.path == "/api/start":
                accepted = controller.start()
                self._json(202 if accepted else 409, {"accepted": accepted, "code": None if accepted else controller.snapshot().get("stop_code") or "START_ALREADY_CONSUMED_OR_PREFLIGHT_FAILED"})
            elif parsed.path == "/api/approve-pressure":
                try:
                    body = json.loads(body_raw or b"{}")
                except (UnicodeError, json.JSONDecodeError):
                    body = None
                confirmation = body.get("confirmation") if isinstance(body, dict) else None
                accepted = controller.authorize_pressure(confirmation)
                self._json(202 if accepted else 409, {"accepted": accepted, "code": None if accepted else controller.snapshot().get("stop_code") or "PRESSURE_GATE_NOT_READY"})
            elif parsed.path == "/api/stop":
                accepted = controller.stop()
                self._json(202 if accepted else 409, {"accepted": accepted, "code": None if accepted else "QUEUE_NOT_RUNNING"})
            elif parsed.path == "/api/retry":
                accepted = controller.resume_failed()
                self._json(202 if accepted else 409, {"accepted": accepted, "code": None if accepted else "NO_RETRYABLE_FAILURES_OR_ACTIVITY_PRESENT"})
            else:
                self._json(404, {"code": "NOT_FOUND"})

    return Handler


def create_server(controller: AutomaticCanaryController, *, port: int = 0) -> ThreadingHTTPServer:
    if not isinstance(port, int) or port < 0 or port > 65535:
        raise ValueError("port must be in 0..65535")
    csrf_token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(controller, csrf_token))
    server.daemon_threads = True
    server.canary_csrf_token = csrf_token
    return server


def _build_controller(output_root: Path = EVIDENCE_ROOT) -> tuple[AutomaticCanaryController, AdminSession]:
    plan = build_frozen_plan(output_root=output_root)
    api_key = runner.load_local_api_key()
    admin = AdminSession(api_key)
    queue = queue_module.SerialAnnouncementQueue(
        output_root / "queue-state" / plan.metadata["queue_id"],
        plan.metadata["queue_id"],
        MODEL_ID,
        max_attempts=MAX_ATTEMPTS,
    )
    for article in plan.metadata["articles"]:
        if article["context_admission"] == "READY":
            # build_frozen_plan already enqueued and bound this identity.
            pass
    controller = AutomaticCanaryController(plan, queue=queue, activity_probe=admin.activity, model_ready_probe=admin.model_ready, api_key=api_key)
    return controller, admin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="loopback port; 0 chooses a free port")
    args = parser.parse_args(argv)
    controller, admin = _build_controller()
    server = create_server(controller, port=args.port)
    host, port = server.server_address[:2]
    print(f"TEMPORARY_TEST_ONLY=true\nUI_URL=http://{host}:{port}/\nMODEL_ID={MODEL_ID}\nINFERENCE_STARTED=false", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        worker = controller._worker
        if worker is not None and worker.is_alive():
            worker.join()
        server.server_close()
        admin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
