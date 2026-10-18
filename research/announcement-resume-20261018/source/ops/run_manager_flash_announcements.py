#!/usr/bin/env python3
"""Run captured announcements through the existing local Flash pipeline.

This entry point is called only by an explicit Manager Workbench POST. It
reuses the existing prompt, batch validator, gated oMLX transport and durable
SerialAnnouncementQueue. It never captures sources itself.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from infrastructure.owned_io import SafeRoot


PIPELINE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary"
)
RUNTIME_PYTHON = Path(
    "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python"
)
PROFILE = "decision_simple_facts_unit_ranges_v2"
CANONICAL_HELPER_SHA256 = "43f70a0e57f81814a93f176079bfc5c20519dbda5b7a8f9e8062e3aa488c74b3"
QUEUE_ID = "v4-manager-flash-incremental"
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,96}$")


class FlashRunError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if SAFE_CODE_RE.fullmatch(code) else "FLASH_PIPELINE_FAILED"


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def queue_model_lock_busy(queue_root: Path, model_id: str) -> bool:
    """Read-only probe of the existing queue model lock; never creates its file."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise FlashRunError("RESUME_MODEL_ID_INVALID")
    lock_path = Path(queue_root) / "locks" / f"model-{sha(model_id.encode('utf-8'))}.lock"
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags)
    except FileNotFoundError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise FlashRunError("RESUME_MODEL_LOCK_INVALID")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
    finally:
        os.close(fd)


def _json(raw: bytes, code: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlashRunError(code) from exc


def _write_json(root: SafeRoot, ref: str, value: Any) -> None:
    root.write_bytes(ref, canonical(value) + b"\n")


def result_path_is_absent(root: SafeRoot, ref: str) -> bool:
    try:
        root.read_bytes(ref, max_bytes=64 * 1024 * 1024)
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    return False


def _safe_pipeline_failure_details(exc: Exception) -> tuple[str, dict[str, Any]]:
    """Return bounded traceback coordinates without exception text or frame locals."""
    raw_name = type(exc).__name__
    safe_name = "".join(char for char in raw_name if char.isascii() and (char.isalnum() or char == "_"))[:64]
    if not safe_name:
        safe_name = "UNKNOWN_EXCEPTION"

    frames: list[dict[str, Any]] = []
    current = exc.__traceback__
    while current is not None:
        code = current.tb_frame.f_code
        filename = Path(code.co_filename).name
        function = code.co_name
        if not filename or len(filename) > 160 or not filename.isascii():
            filename = "unknown"
        if not function or len(function) > 128 or not function.isascii():
            function = "unknown"
        frames.append({"file": filename, "function": function, "line": int(current.tb_lineno)})
        current = current.tb_next
    code = f"FLASH_PIPELINE_{safe_name.upper()}"
    if not SAFE_CODE_RE.fullmatch(code):
        code = "FLASH_PIPELINE_FAILED"
    return code, {
        "exception_type": safe_name,
        "stack_frames": frames[-16:],
    }


def _load_helper():
    if str(PIPELINE_ROOT) not in sys.path:
        sys.path.insert(0, str(PIPELINE_ROOT))
    helper_path = PIPELINE_ROOT / "evidence/recent-day-20261014/recent_day_freeze.py"
    if sha(helper_path.read_bytes()) != CANONICAL_HELPER_SHA256:
        raise FlashRunError("CANONICAL_FLASH_HELPER_SHA_MISMATCH")
    spec = importlib.util.spec_from_file_location("v4_manager_recent_day_freeze", helper_path)
    if spec is None or spec.loader is None:
        raise FlashRunError("CANONICAL_FLASH_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _capture_origin(row: dict[str, Any], capture_product: dict[str, Any], capture_ref: dict[str, str],
                    capture_io: SafeRoot, body_sha: str) -> list[dict[str, Any]]:
    """Bind source origins to bytes actually saved by CaptureStore."""
    body_ref = row.get("body_artifact_ref")
    if (not isinstance(body_ref, str) or not re.fullmatch(r"products/[0-9a-f]{64}\.json", body_ref)
            or row.get("source_sha256") != body_ref.removeprefix("products/").removesuffix(".json")):
        raise FlashRunError("BODY_PRODUCT_REFERENCE_INVALID")
    body_raw = capture_io.read_bytes(body_ref)
    if sha(body_raw) != row.get("source_sha256"):
        raise FlashRunError("BODY_PRODUCT_SHA_MISMATCH")
    body_product = _json(body_raw, "BODY_PRODUCT_JSON_INVALID")
    if (body_product.get("body_text") != row.get("body_text")
            or body_product.get("body_text_sha256") != body_sha
            or body_product.get("body_complete") is not True):
        raise FlashRunError("BODY_PRODUCT_CONTENT_MISMATCH")

    listing = row.get("listing_source_ref")
    if not isinstance(listing, dict):
        raise FlashRunError("LISTING_SOURCE_REFERENCE_MISSING")
    listing_ref = listing.get("artifact_ref")
    listing_sha = listing.get("sha256")
    if (not isinstance(listing_ref, str) or not re.fullmatch(r"objects/[0-9a-f]{64}\.bin", listing_ref)
            or not isinstance(listing_sha, str) or not SHA_RE.fullmatch(listing_sha)):
        raise FlashRunError("LISTING_SOURCE_REFERENCE_INVALID")
    listing_raw = capture_io.read_bytes(listing_ref)
    if sha(listing_raw) != listing_sha:
        raise FlashRunError("LISTING_SOURCE_SHA_MISMATCH")
    listing_page = _json(listing_raw, "LISTING_SOURCE_JSON_INVALID")
    listing_rows = (((listing_page.get("data") or {}).get("list")) if isinstance(listing_page, dict) else None)
    raw_row = row.get("raw_row")
    if not isinstance(listing_rows, list) or not isinstance(raw_row, dict):
        raise FlashRunError("LISTING_SOURCE_ROWS_INVALID")
    indexes = [index for index, value in enumerate(listing_rows) if value == raw_row]
    if len(indexes) != 1:
        raise FlashRunError("LISTING_SOURCE_ROW_NOT_UNIQUE")
    listing_index = indexes[0]

    capture_rows = capture_product.get("rows")
    if not isinstance(capture_rows, list) or not 0 <= capture_ref.get("row_index", -1) < len(capture_rows):
        raise FlashRunError("CAPTURE_PRODUCT_ROW_INDEX_INVALID")
    capture_row_index = capture_ref["row_index"]
    if capture_rows[capture_row_index] != row:
        raise FlashRunError("CAPTURE_PRODUCT_ROW_MISMATCH")
    capture_artifact = capture_ref["artifact_ref"]
    capture_sha = capture_ref["sha256"]
    return [
        {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
         "source_ref": f"{capture_artifact}#/rows/{capture_row_index}", "source_row_index": capture_row_index,
         "row_fingerprint_sha256": sha(canonical(row))},
        {"role": "FULL_DATE_DIRECTORY_PAGE", "source_product_sha256": listing_sha,
         "source_ref": f"{listing_ref}#data/list/{listing_index}", "source_row_index": listing_index,
         "row_fingerprint_sha256": sha(canonical(raw_row))},
        {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": body_sha256_from_ref(row),
         "source_ref": f"{body_ref}#notice", "source_row_index": 0,
         "row_fingerprint_sha256": sha(body_raw)},
    ]


def body_sha256_from_ref(row: dict[str, Any]) -> str:
    value = row.get("source_sha256")
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise FlashRunError("BODY_SOURCE_SHA_INVALID")
    return value


def _article(row: dict[str, Any], row_index: int, capture_product: dict[str, Any], capture_ref: dict[str, str],
             capture_io: SafeRoot, runner: Any, membership_gate: dict[str, Any]) -> dict[str, Any]:
    from v4.manager_workbench.announcement_membership import classify_capture_row

    body = row.get("body_text")
    body_sha = row.get("body_text_sha256")
    if (row.get("body_complete") is not True or not isinstance(body, str) or not body
            or not isinstance(body_sha, str) or not SHA_RE.fullmatch(body_sha)
            or sha(body.encode("utf-8")) != body_sha):
        raise FlashRunError("BODY_INCOMPLETE_OR_SHA_MISMATCH")
    code_rows = row.get("source_issuer_codes")
    if not isinstance(code_rows, list) or not code_rows:
        raise FlashRunError("SOURCE_ISSUER_CODES_MISSING")
    hk_codes = [item.get("code") for item in code_rows if isinstance(item, dict)
                and isinstance(item.get("code"), str) and re.fullmatch(r"HK\.[0-9]{5}", item["code"])]
    symbol = hk_codes[0] if len(set(hk_codes)) == 1 else "CANNOT_CONFIRM"
    membership = classify_capture_row(row, membership_gate)
    if membership.get("membership_status") != "IN" or len(set(hk_codes)) != 1:
        raise FlashRunError("ARTICLE_NOT_HK_CONNECT_MEMBER")
    name = next((item.get("name") for item in code_rows if isinstance(item, dict) and item.get("name")), symbol)
    origins = _capture_origin(row, capture_product, {**capture_ref, "row_index": row_index}, capture_io, body_sha)
    metadata = {
        "publication_date": row.get("publication_date"),
        "title": row.get("title"),
        "issuer_name": str(name),
        "symbol": symbol,
        "observed_at": row.get("available_at"),
        "available_at": row.get("available_at"),
        "pit_status": "CANNOT_CONFIRM",
        "pit_reason": "OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND",
        "first_hkex_publication_time": "CANNOT_CONFIRM",
        "article_membership_status": "IN",
        "source_issuer_membership": [{"code": membership["issuer_codes"][0],
                                       "membership_status": "IN", "market": "HK_CONNECT",
                                       "authority_sha256": membership_gate["authority_sha256"]}],
        "membership_authority_sha256": membership_gate["authority_sha256"],
        "source_issuer_codes": code_rows,
        "source_scope": "EASTMONEY_ONLY",
        "source_display_time": row.get("display_time"),
        "source_origins": origins,
    }
    article = {
        "article_id": "EASTMONEY:" + str(row.get("art_code")),
        "source_sha256": body_sha256_from_ref(row),
        "body_sha256": body_sha,
        "article_body": body,
        "article_metadata": metadata,
    }
    unit_map = runner.build_source_unit_map(body, body_sha)
    article["fixed_fact_ledger"] = runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, metadata)
    article["_source_unit_map"] = unit_map
    return article


def _public_article(article_id: str, article: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    meta = article["article_metadata"]
    return {
        "article_id": article_id,
        "title": meta["title"],
        "publication_date": meta["publication_date"],
        "symbol": meta["symbol"],
        "name": meta["issuer_name"],
        "disposition": output.get("disposition"),
        "direction": output.get("direction"),
        "selection_basis": output.get("selection_basis"),
        "reason": output.get("reason"),
        "impact": [item.get("claim") for item in output.get("impact", [])
                   if isinstance(item, dict) and isinstance(item.get("claim"), str)],
        "body_sha256": article["body_sha256"],
        "source_sha256": article["source_sha256"],
        "source_origins": [
            {"role": item["role"], "source_ref": item["source_ref"],
             "source_product_sha256": item["source_product_sha256"],
             "row_fingerprint_sha256": item["row_fingerprint_sha256"]}
            for item in meta["source_origins"]
        ],
        "review_status": "MODEL_CANDIDATE_UNREVIEWED",
        "reuse_status": None,
    }


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stocks: dict[str, dict[str, Any]] = {}
    for article in rows:
        symbol = article.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"HK\.[0-9]{5}", symbol):
            continue
        stock = stocks.setdefault(symbol, {"symbol": symbol, "name": article.get("name"), "reasons": [],
                                            "articles": [], "review_status": article.get("review_status") or "MODEL_CANDIDATE_UNREVIEWED",
                                            "reuse_status": article.get("reuse_status")})
        stock["articles"].append(article)
        stock["reasons"].append(article["reason"])
        if article.get("reuse_status"):
            stock["reuse_status"] = article["reuse_status"]
        if stock["review_status"] != article.get("review_status"):
            stock["review_status"] = "MIXED_MODEL_CANDIDATE_AND_PRIOR_REVIEWED"
    return list(stocks.values())


def _stable_queue_identity(queue: Any, payload: dict[str, Any]) -> str:
    material = queue._identity(payload)
    return hashlib.sha256(queue_module_bytes(material)).hexdigest()


_SEMANTIC_IDENTITY_FIELDS = (
    "date", "market", "article_id", "body_sha256", "prompt_sha256", "model_id",
    "configuration_sha256", "role",
)
_KNOWN_RULES_PREFIXES = {"recent_day_reader_v2", "announcement_capability_sample"}


def _rules_semantics(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    prefix, separator, rest = value.partition("+")
    # Stage labels differ between the frozen full-day and capability runs; the
    # suffix binds the actual profile, citation, unit map, ledger and settings.
    return rest if separator and prefix in _KNOWN_RULES_PREFIXES else value


def _content_identity(identity: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(identity, dict):
        return None
    values = {key: identity.get(key) for key in _SEMANTIC_IDENTITY_FIELDS}
    if any(not isinstance(value, str) or not value for value in values.values()):
        return None
    values["date"] = str(values["date"])
    values["rules"] = _rules_semantics(identity.get("rules"))
    if values["rules"] is None:
        return None
    return values


def _semantic_identity(identity: dict[str, Any]) -> str | None:
    values = _content_identity(identity)
    return hashlib.sha256(canonical(values)).hexdigest() if values is not None else None


def _has_existing_semantic_queue_job(queue: Any, payload: dict[str, Any]) -> bool:
    """Read-only check used to preserve already-persisted full-body inputs."""
    semantic = _semantic_identity(queue._identity(payload))
    if semantic is None:
        return False
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    return any(isinstance(job, dict) and isinstance(job.get("identity"), dict)
               and _semantic_identity(job["identity"]) == semantic for job in jobs.values())


def _needs_chunk_plan(prompt_tokens: int, *, part_target_tokens: int, hard_cap_tokens: int,
                      existing_standard_job: bool) -> bool:
    if (type(prompt_tokens) is not int or type(part_target_tokens) is not int
            or type(hard_cap_tokens) is not int or prompt_tokens < 0
            or part_target_tokens < 1 or hard_cap_tokens < part_target_tokens):
        raise FlashRunError("LONG_BODY_TOKEN_BUDGET_INVALID")
    # New requests above the conservative target are chunked. A previously
    # persisted standard request in the 64k-160k band keeps its exact input.
    return prompt_tokens > hard_cap_tokens or (prompt_tokens > part_target_tokens and not existing_standard_job)


def _is_final_candidate_task(task_kind: Any) -> bool:
    """Only ordinary Reader outputs and the all-parts synthesis can be candidates."""
    return task_kind in (None, "announcement_reader_synthesis")


def _content_key(identity: dict[str, Any]) -> str | None:
    values = _content_identity(identity)
    if values is None:
        return None
    values.pop("rules", None)
    return hashlib.sha256(canonical(values)).hexdigest()


def _read_json_file(path: Path, expected_sha256: str | None, code: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FlashRunError(code) from exc
    if expected_sha256 and sha(raw) != expected_sha256:
        raise FlashRunError("PINNED_PRIOR_RESULT_SHA_MISMATCH")
    return _json(raw, code)


def _queue_payload(queue_root: Path, job: dict[str, Any]) -> dict[str, Any]:
    identity = job.get("identity")
    if not isinstance(identity, dict):
        raise FlashRunError("PRIOR_QUEUE_IDENTITY_INVALID")
    input_rel = job.get("input_path")
    if not isinstance(input_rel, str):
        raise FlashRunError("PRIOR_QUEUE_RESULT_REFERENCE_INVALID")
    input_path = (queue_root / input_rel).resolve()
    root = queue_root.resolve()
    if not input_path.is_relative_to(root):
        raise FlashRunError("PRIOR_QUEUE_RESULT_REFERENCE_INVALID")
    input_raw = input_path.read_bytes()
    if sha(input_raw) != job.get("payload_sha256"):
        raise FlashRunError("PRIOR_QUEUE_INPUT_SHA_MISMATCH")
    payload = _json(input_raw, "PRIOR_QUEUE_INPUT_INVALID")
    if not isinstance(payload, dict) or payload.get("article_id") != identity.get("article_id"):
        raise FlashRunError("PRIOR_QUEUE_INPUT_IDENTITY_MISMATCH")
    if (payload.get("source_sha256") != identity.get("source_sha256")
            or payload.get("body_sha256") != identity.get("body_sha256")):
        raise FlashRunError("PRIOR_QUEUE_INPUT_SOURCE_MISMATCH")
    return payload


def _saved_orphan_result_state(queue_root: Path, job: dict[str, Any], payload: dict[str, Any]) -> str:
    """Distinguish no result from a complete or unreadable validator artifact."""
    key = job.get("idempotency_key")
    attempt_count = job.get("attempt_count")
    if not isinstance(key, str) or type(attempt_count) is not int or attempt_count < 1:
        return "UNVERIFIED"
    refs: list[tuple[str, str | None]] = []
    if job.get("validated_path") is not None or job.get("validated_sha256") is not None:
        ref = job.get("validated_path")
        if not isinstance(ref, str):
            return "UNVERIFIED"
        refs.append((ref, job.get("validated_sha256") if isinstance(job.get("validated_sha256"), str) else None))
    conventional = f"jobs/{key}/attempt-{attempt_count:04d}.validated.json"
    if conventional not in {ref for ref, _sha in refs}:
        refs.append((conventional, None))
    root = Path(queue_root).resolve()
    for ref, expected_sha in refs:
        candidate = Path(ref)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            return "UNVERIFIED"
        path = (root / candidate).resolve()
        if not path.is_relative_to(root):
            return "UNVERIFIED"
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            if expected_sha is not None:
                return "UNVERIFIED"
            continue
        except OSError:
            return "UNVERIFIED"
        if expected_sha is not None and sha(raw) != expected_sha:
            return "UNVERIFIED"
        try:
            result = _json(raw, "ORPHAN_VALIDATED_RESULT_INVALID")
            rows = result.get("results") if isinstance(result, dict) else None
            output = rows[0].get("reader_output") if isinstance(rows, list) and len(rows) == 1 else None
        except FlashRunError:
            return "UNVERIFIED"
        if (not isinstance(output, dict)
                or output.get("source_sha256") != payload.get("source_sha256")
                or output.get("body_sha256") != payload.get("body_sha256")
                or output.get("article_id") != payload.get("article_id")):
            return "UNVERIFIED"
        return "COMPLETE"
    return "NONE"


def _frozen_resume_orphans(long_body_specs: dict[str, dict[str, Any]], queue: Any,
                           queue_root: Path, *, target_date: str,
                           dry_run: bool) -> tuple[set[str], set[str], dict[str, str]]:
    """Recover only the single frozen orphan after proving the model owner is gone."""
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else None
    if not isinstance(jobs, dict):
        raise FlashRunError("FROZEN_RESUME_QUEUE_STATE_INVALID")
    payloads: dict[str, dict[str, Any]] = {}
    for spec in long_body_specs.values():
        for payload in spec.get("part_payloads", []):
            if isinstance(payload, dict):
                payloads[_stable_queue_identity(queue, payload)] = payload
    if not re.fullmatch(r"[0-9]{8}", str(target_date)):
        raise FlashRunError("FROZEN_RESUME_TARGET_DATE_INVALID")
    target_running = set()
    target_date_unmatched_running = set()
    for key, item in jobs.items():
        if (not isinstance(item, dict) or item.get("queue_id") != QUEUE_ID
                or item.get("status") != "RUNNING"):
            continue
        # Queue identity.date is the announcement's publication date. A
        # frozen job can contain earlier publications, so plan-key membership
        # is the task binding; date alone only catches an unbound same-day row.
        if key in payloads:
            target_running.add(key)
            continue
        identity = item.get("identity")
        item_date = identity.get("date") if isinstance(identity, dict) else None
        if isinstance(item_date, str) and item_date.replace("-", "") == target_date:
            target_date_unmatched_running.add(key)
    if target_date_unmatched_running:
        raise FlashRunError("FROZEN_RESUME_ORPHAN_IDENTITY_UNVERIFIED")
    same_model_running = {key for key, item in jobs.items()
                          if isinstance(item, dict) and item.get("model_id") == getattr(queue, "model_id", None)
                          and item.get("status") == "RUNNING"}
    recovered: set[str] = set()
    blocked: set[str] = set()
    candidates: dict[str, str] = {}
    for key in target_running:
        item = jobs[key]
        try:
            payload = _queue_payload(queue_root, item)
        except FlashRunError:
            blocked.add(key)
            candidates[key] = "INPUT_UNVERIFIED"
            continue
        result_state = _saved_orphan_result_state(queue_root, item, payload)
        candidates[key] = result_state
        if result_state != "NONE":
            blocked.add(key)
    if not target_running:
        if same_model_running or queue_model_lock_busy(queue_root, getattr(queue, "model_id", None)):
            raise FlashRunError("FROZEN_RESUME_MODEL_OWNER_ACTIVE")
        return recovered, blocked, candidates
    if (len(target_running) != 1 or not target_running.issubset(payloads)
            or same_model_running != target_running):
        raise FlashRunError("FROZEN_RESUME_ORPHAN_IDENTITY_UNVERIFIED")
    key = next(iter(target_running))
    if key in blocked:
        return recovered, blocked, candidates
    if queue_model_lock_busy(queue_root, getattr(queue, "model_id", None)):
        raise FlashRunError("FROZEN_RESUME_MODEL_OWNER_ACTIVE")
    if dry_run:
        candidates[key] = "OWNER_CLEAR_NO_RESULT"
        return recovered, blocked, candidates
    try:
        changed = queue.recover_interrupted(wait_for_model_slot=False)
    except Exception as exc:
        if "busy" in str(exc).lower():
            raise FlashRunError("FROZEN_RESUME_MODEL_LOCK_BUSY") from exc
        raise
    after = queue._load_state().get("jobs", {})
    recovered_item = after.get(key) if isinstance(after, dict) else None
    attempts = recovered_item.get("attempts") if isinstance(recovered_item, dict) else None
    last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else None
    error = last_attempt.get("error") if isinstance(last_attempt, dict) else None
    if (len(changed) != 1 or changed[0].get("idempotency_key") != key
            or not isinstance(recovered_item, dict) or recovered_item.get("status") != "FAILED"
            or recovered_item.get("attempt_count") != 1
            or not isinstance(last_attempt, dict) or last_attempt.get("status") != "INTERRUPTED"
            or not isinstance(error, dict) or error.get("code") != "PROCESS_INTERRUPTED"):
        raise FlashRunError("FROZEN_RESUME_ORPHAN_RECOVERY_UNVERIFIED")
    recovered.add(key)
    candidates[key] = "OWNER_CLEAR_NO_RESULT"
    return recovered, blocked, candidates


def _historical_success_part_conflict(payload: dict[str, Any], current_key: str,
                                      queue: Any, queue_root: Path) -> dict[str, Any] | None:
    """Do not recalculate a same-part prior success when provenance differs.

    This intentionally does not reuse the old answer: it preserves both source
    identities and reports CANNOT_CONFIRM until an approved provenance bridge
    exists.
    """
    descriptor = payload.get("part_descriptor")
    if not isinstance(descriptor, dict):
        return None
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    if not isinstance(jobs, dict):
        return {"verification": "CANNOT_CONFIRM_QUEUE_SCHEMA"}
    for key, candidate in jobs.items():
        if (key == current_key or not isinstance(candidate, dict)
                or candidate.get("status") != "SUCCEEDED"
                or candidate.get("queue_id") != QUEUE_ID):
            continue
        identity = candidate.get("identity")
        if (not isinstance(identity, dict)
                or candidate.get("idempotency_key") != key
                or identity.get("article_id") != payload.get("article_id")
                or identity.get("body_sha256") != payload.get("body_sha256")):
            continue
        try:
            prior = _queue_payload(queue_root, candidate)
        except FlashRunError:
            # The same article/body has a recorded success, but its provenance
            # cannot be checked; keep the current item out of the model queue.
            return {"prior_idempotency_key": key,
                    "prior_payload_sha256": candidate.get("payload_sha256"),
                    "prior_validated_sha256": candidate.get("validated_sha256"),
                    "verification": "CANNOT_CONFIRM_PRIOR_INPUT"}
        if (candidate.get("identity") != queue._identity(prior)
                or _stable_queue_identity(queue, prior) != key):
            return {"prior_idempotency_key": key,
                    "prior_payload_sha256": candidate.get("payload_sha256"),
                    "prior_validated_sha256": candidate.get("validated_sha256"),
                    "verification": "CANNOT_CONFIRM_PRIOR_INPUT"}
        prior_descriptor = prior.get("part_descriptor")
        same_part = (prior.get("queue_task_kind") == "announcement_reader_part"
                     and prior.get("source_unit_map_sha256") == payload.get("source_unit_map_sha256")
                     and isinstance(prior_descriptor, dict)
                     and prior_descriptor.get("part_sha256") == descriptor.get("part_sha256")
                     and prior_descriptor.get("part_index") == descriptor.get("part_index")
                     and prior_descriptor.get("part_count") == descriptor.get("part_count")
                     and prior_descriptor.get("source_unit_ids") == descriptor.get("source_unit_ids"))
        if not same_part:
            continue
        verification = "VERIFIED_PRIOR_RESULT"
        result_status = "VERIFIED_PRIOR_RESULT"
        try:
            result_ref = candidate.get("validated_path")
            result_sha = candidate.get("validated_sha256")
            if (not isinstance(result_ref, str) or Path(result_ref).is_absolute()
                    or any(part in {"", ".", ".."} for part in Path(result_ref).parts)
                    or not isinstance(result_sha, str) or not SHA_RE.fullmatch(result_sha)):
                raise FlashRunError("PRIOR_PART_RESULT_REFERENCE_INVALID")
            result_path = (Path(queue_root) / result_ref).resolve()
            if not result_path.is_relative_to(Path(queue_root).resolve()):
                raise FlashRunError("PRIOR_PART_RESULT_REFERENCE_INVALID")
            result = _read_json_file(result_path, result_sha, "PRIOR_PART_RESULT_INVALID")
            output = result.get("reader_output") if isinstance(result, dict) else None
            expected_result_fields = {
                "schema": "v4.manager_workbench.announcement_chunk_part_result.v1",
                "article_id": prior.get("article_id"),
                "source_sha256": prior.get("source_sha256"),
                "body_sha256": prior.get("body_sha256"),
                "plan_sha256": prior.get("chunk_plan_sha256"),
                "part_index": prior_descriptor.get("part_index"),
                "part_count": prior_descriptor.get("part_count"),
                "part_sha256": prior_descriptor.get("part_sha256"),
                "source_unit_map_sha256": prior.get("source_unit_map_sha256"),
            }
            if (not isinstance(result, dict)
                    or any(result.get(field) != value for field, value in expected_result_fields.items())
                    or not isinstance(result.get("citation_ranges"), list)
                    or not isinstance(output, dict)):
                raise FlashRunError("PRIOR_PART_RESULT_BINDING_UNVERIFIED")
        except (FlashRunError, OSError, TypeError, ValueError):
            verification = "CANNOT_CONFIRM_PRIOR_RESULT"
            result_status = "CANNOT_CONFIRM_PRIOR_RESULT"
        current_identity = queue._identity(payload)
        provenance_mismatch_fields = sorted(
            field for field in set(identity) | set(current_identity)
            if identity.get(field) != current_identity.get(field)
        )
        if prior.get("chunk_plan_sha256") != payload.get("chunk_plan_sha256"):
            provenance_mismatch_fields.append("chunk_plan_sha256")
        if verification == "VERIFIED_PRIOR_RESULT" and provenance_mismatch_fields:
            verification = "CANNOT_CONFIRM_PROVENANCE_BRIDGE"
        return {
            "prior_idempotency_key": key,
            "prior_source_sha256": identity.get("source_sha256"),
            "prior_chunk_plan_sha256": prior.get("chunk_plan_sha256"),
            "prior_source_unit_map_sha256": prior.get("source_unit_map_sha256"),
            "prior_part_sha256": prior_descriptor.get("part_sha256"),
            "prior_payload_sha256": candidate.get("payload_sha256"),
            "prior_validated_sha256": candidate.get("validated_sha256"),
            "historical_result_status": result_status,
            "provenance_mismatch_fields": provenance_mismatch_fields,
            "verification": verification,
        }
    return None


def _orphan_recovery_payload(payload: dict[str, Any], base_job: dict[str, Any], *,
                             source_job_id: str, source_input_sha256: str, source_key: str) -> dict[str, Any]:
    descriptor = payload.get("part_descriptor") if isinstance(payload.get("part_descriptor"), dict) else {}
    binding = {
        "schema": "v4.manager_workbench.announcement_flash_orphan_recovery.v1",
        "source_job_id": source_job_id,
        "source_input_sha256": source_input_sha256,
        "source_idempotency_key": source_key,
        "source_payload_sha256": base_job.get("payload_sha256"),
        "source_attempt_count": base_job.get("attempt_count"),
        "source_unit_map_sha256": payload.get("source_unit_map_sha256"),
        "chunk_plan_sha256": payload.get("chunk_plan_sha256"),
        "part_sha256": descriptor.get("part_sha256"),
    }
    return ({**payload,
             "rules": payload.get("rules", "") + "+explicit-orphan-resume:v1",
             "stage": "v4_manager_announcement_flash_long_body_part_orphan_resume_v1",
             "interrupted_attempt_recovery": binding})


def _prior_orphan_recovery(payload: dict[str, Any], base_key: str, base_job: dict[str, Any],
                           queue: Any, queue_root: Path, *, source_job_id: str | None,
                           source_input_sha256: str | None) -> tuple[str, dict[str, Any]] | None:
    if (not isinstance(source_job_id, str) or not JOB_ID_RE.fullmatch(source_job_id)
            or not isinstance(source_input_sha256, str) or not SHA_RE.fullmatch(source_input_sha256)):
        return None
    recovery_payload = _orphan_recovery_payload(payload, base_job, source_job_id=source_job_id,
                                                source_input_sha256=source_input_sha256, source_key=base_key)
    wanted_key = _stable_queue_identity(queue, recovery_payload)
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else None
    if not isinstance(jobs, dict):
        raise FlashRunError("FROZEN_RESUME_QUEUE_STATE_INVALID")
    prior = jobs.get(wanted_key)
    if not isinstance(prior, dict):
        return None
    if (prior.get("queue_id") != QUEUE_ID or prior.get("idempotency_key") != wanted_key
            or prior.get("identity") != queue._identity(recovery_payload)):
        raise FlashRunError("ORPHAN_RECOVERY_IDENTITY_CONFLICT")
    saved_payload = _queue_payload(queue_root, prior)
    if not _internal_payload_matches(saved_payload, recovery_payload):
        raise FlashRunError("ORPHAN_RECOVERY_PAYLOAD_CONFLICT")
    return wanted_key, prior


def _queue_result(queue_root: Path, job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = job.get("identity")
    if not isinstance(identity, dict):
        raise FlashRunError("PRIOR_QUEUE_IDENTITY_INVALID")
    payload = _queue_payload(queue_root, job)
    result_rel = job.get("validated_path")
    if not isinstance(result_rel, str):
        raise FlashRunError("PRIOR_QUEUE_RESULT_REFERENCE_INVALID")
    result_path = (queue_root / result_rel).resolve()
    if not result_path.is_relative_to(queue_root.resolve()):
        raise FlashRunError("PRIOR_QUEUE_RESULT_REFERENCE_INVALID")
    result = _read_json_file(result_path, job.get("validated_sha256"), "PRIOR_QUEUE_RESULT_INVALID")
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("article_id") != identity.get("article_id"):
        raise FlashRunError("PRIOR_QUEUE_RESULT_IDENTITY_INVALID")
    output = rows[0].get("reader_output")
    if (not isinstance(output, dict) or output.get("source_sha256") != identity.get("source_sha256")
            or output.get("body_sha256") != identity.get("body_sha256")):
        raise FlashRunError("PRIOR_QUEUE_RESULT_SOURCE_MISMATCH")
    return payload, output


def _pinned_candidate_history() -> list[dict[str, Any]]:
    """Verify and index the fixed C run plus its separately reviewed reuse."""
    try:
        from v4.manager_workbench import announcement_candidate as pinned
        # This verifies the pinned manifest, sidecar, validated batch, queue state,
        # every successful result SHA, the system-stop receipt and reviewed reuse.
        pinned.read_pinned_candidates()
        manifest = _read_json_file(pinned.CANDIDATE_ROOT / "candidate-manifest.json",
                                   pinned.CANDIDATE_MANIFEST_SHA256, "PINNED_CANDIDATE_MANIFEST_INVALID")
        batch = _read_json_file(pinned.CANDIDATE_ROOT / "validated-batch.json",
                                pinned.VALIDATED_BATCH_SHA256, "PINNED_CANDIDATE_BATCH_INVALID")
        queue_rel = f"queue-state/{pinned.QUEUE_ID}/queue-state.json"
        queue_state = _read_json_file(pinned.CANDIDATE_ROOT / queue_rel,
                                      pinned.QUEUE_STATE_SHA256, "PINNED_CANDIDATE_QUEUE_INVALID")
        articles = {item.get("article_id"): item for item in batch.get("articles", []) if isinstance(item, dict)}
        jobs = queue_state.get("jobs")
        if not isinstance(jobs, dict) or len(jobs) != 390 or manifest.get("candidate_id") != "76e8763179830e975f11":
            raise FlashRunError("PINNED_CANDIDATE_QUEUE_IDENTITY_INVALID")
        queue_root = pinned.CANDIDATE_ROOT / "queue-state" / pinned.QUEUE_ID
        history: list[dict[str, Any]] = []
        for job in jobs.values():
            identity = job.get("identity") if isinstance(job, dict) else None
            article_id = identity.get("article_id") if isinstance(identity, dict) else None
            article = articles.get(article_id)
            if (not isinstance(identity, dict) or not isinstance(article, dict)
                    or article.get("source_sha256") != identity.get("source_sha256")
                    or article.get("body_sha256") != identity.get("body_sha256")):
                raise FlashRunError("PINNED_CANDIDATE_BATCH_IDENTITY_MISMATCH")
            status = job.get("status")
            if status not in {"SUCCEEDED", "FAILED", "PENDING"}:
                raise FlashRunError("PINNED_CANDIDATE_QUEUE_STATUS_INVALID")
            output = None
            if status == "SUCCEEDED":
                _payload, output = _queue_result(queue_root, job)
            history.append({"source": "PINNED_CANDIDATE", "status": status,
                            "identity": identity, "article": article, "output": output,
                            "job": job, "queue_root": queue_root,
                            "candidate_manifest_sha256": pinned.CANDIDATE_MANIFEST_SHA256,
                            "candidate_validated_batch_sha256": pinned.VALIDATED_BATCH_SHA256,
                            "candidate_queue_state_sha256": pinned.QUEUE_STATE_SHA256,
                            "candidate_queue_id": pinned.QUEUE_ID})

        prior_receipt = _read_json_file(pinned.CANDIDATE_ROOT / "prior-result-reuse.json",
                                        pinned.PRIOR_REUSE_SHA256, "PINNED_PRIOR_REUSE_RECEIPT_INVALID")
        prior_batch = _read_json_file(pinned.PRIOR_CANDIDATE_ROOT / "validated-batch.json",
                                      pinned.PRIOR_VALIDATED_BATCH_SHA256, "PINNED_PRIOR_REUSE_BATCH_INVALID")
        prior_queue_root = pinned.PRIOR_CANDIDATE_ROOT / "queue-state" / prior_receipt["prior_queue_id"]
        prior_state = _read_json_file(prior_queue_root / "queue-state.json", None,
                                      "PINNED_PRIOR_REUSE_QUEUE_INVALID")
        prior_job = prior_state.get("jobs", {}).get(prior_receipt.get("prior_idempotency_key"))
        if not isinstance(prior_job, dict) or prior_job.get("status") != "SUCCEEDED":
            raise FlashRunError("PINNED_PRIOR_REUSE_JOB_INVALID")
        article = next((item for item in prior_batch.get("articles", [])
                        if item.get("article_id") == prior_receipt.get("article_id")), None)
        if not isinstance(article, dict):
            raise FlashRunError("PINNED_PRIOR_REUSE_ARTICLE_INVALID")
        prior_payload, output = _queue_result(prior_queue_root, prior_job)
        if (prior_payload.get("article_id") != prior_receipt.get("article_id")
                or prior_payload.get("body_sha256") != prior_receipt.get("body_sha256")
                or prior_job.get("validated_sha256") != prior_receipt.get("prior_validated_sha256", prior_job.get("validated_sha256"))
                or output.get("direction") != "POSITIVE"
                or output.get("disposition") not in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}):
            raise FlashRunError("PINNED_PRIOR_REUSE_RESULT_INVALID")
        history.append({"source": "PRIOR_REVIEWED_RESULT", "status": "SUCCEEDED",
                        "identity": prior_job["identity"], "article": article, "output": output,
                        "job": prior_job, "queue_root": prior_queue_root,
                        "prior_reuse_receipt_sha256": pinned.PRIOR_REUSE_SHA256,
                        "prior_review_status": "PRIOR_INDEPENDENT_REVIEW_PASS_WITH_LIMITATION"})
        return history
    except FlashRunError:
        raise
    except Exception as exc:
        raise FlashRunError("PINNED_CANDIDATE_HISTORY_UNAVAILABLE") from exc


def _history_priority(record: dict[str, Any]) -> tuple[int, int]:
    source = record.get("source")
    status = record.get("status")
    if source == "PRIOR_REVIEWED_RESULT":
        return (4, 0)
    if status == "SUCCEEDED":
        return (3, 1 if source == "INCREMENTAL_QUEUE" else 0)
    if source == "INCREMENTAL_QUEUE":
        return (2, 1 if status == "FAILED" else 0)
    return (1, 1 if status == "FAILED" else 0)


def _verified_pending_resume(record: dict[str, Any], current_payload: dict[str, Any],
                             queue: Any, queue_root: Path, semantic: str,
                             resume_cutoff: str | None) -> tuple[str, dict[str, Any]] | None:
    """Return an exact unattempted queue payload only when its current HK gate binding still matches."""
    job = record.get("job")
    if (record.get("source") != "INCREMENTAL_QUEUE" or record.get("status") != "PENDING"
            or not isinstance(job, dict) or type(job.get("attempt_count")) is not int
            or job.get("attempt_count") != 0 or job.get("queue_id") != QUEUE_ID
            or job.get("max_attempts") != 1):
        return None
    key = record.get("idempotency_key") or job.get("idempotency_key")
    if not isinstance(key, str) or key != job.get("idempotency_key"):
        return None
    stored_payload = _queue_payload(queue_root, job)
    if queue._identity(stored_payload) != job.get("identity"):
        raise FlashRunError("PENDING_RESUME_QUEUE_IDENTITY_MISMATCH")
    if (_semantic_identity(queue._identity(stored_payload)) != semantic
            or stored_payload.get("article_body") != current_payload.get("article_body")
            or stored_payload.get("fixed_fact_ledger") != current_payload.get("fixed_fact_ledger")
            or stored_payload.get("messages") != current_payload.get("messages")
            or stored_payload.get("structured_output_schema") != current_payload.get("structured_output_schema")
            or stored_payload.get("source_unit_map_sha256") != current_payload.get("source_unit_map_sha256")):
        return None
    old_meta = stored_payload.get("article_metadata")
    current_meta = current_payload.get("article_metadata")
    if not isinstance(old_meta, dict) or not isinstance(current_meta, dict):
        return None
    if not isinstance(resume_cutoff, str):
        return None
    try:
        cutoff = datetime.fromisoformat(resume_cutoff)
        old_available = datetime.fromisoformat(str(old_meta.get("available_at", "")))
        current_available = datetime.fromisoformat(str(current_meta.get("available_at", "")))
    except ValueError:
        return None
    if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or old_available.tzinfo is None or old_available.utcoffset() is None
            or current_available.tzinfo is None or current_available.utcoffset() is None
            or old_available > cutoff or current_available > cutoff):
        return None
    binding_fields = ("publication_date", "title", "symbol", "article_membership_status",
                      "membership_authority_sha256", "source_issuer_codes", "source_issuer_membership")
    if (any(old_meta.get(field) != current_meta.get(field) for field in binding_fields)
            or current_meta.get("article_membership_status") != "IN"
            or not SHA_RE.fullmatch(str(current_meta.get("membership_authority_sha256", "")))):
        return None
    issuer_membership = current_meta.get("source_issuer_membership")
    if (not isinstance(issuer_membership, list) or len(issuer_membership) != 1
            or not isinstance(issuer_membership[0], dict)
            or issuer_membership[0].get("membership_status") != "IN"
            or issuer_membership[0].get("market") != "HK_CONNECT"
            or issuer_membership[0].get("authority_sha256") != current_meta.get("membership_authority_sha256")):
        return None
    return key, stored_payload


def _current_recovery_payload_valid(payload: dict[str, Any], recovery_lock: Any,
                                    membership_gate: Any, resume_cutoff: str | None) -> bool:
    """Fail closed unless this payload is bound to the frozen current HK Connect recovery."""
    if not isinstance(recovery_lock, dict) or not isinstance(membership_gate, dict):
        return False
    metadata = payload.get("article_metadata")
    article_id = payload.get("article_id")
    if (recovery_lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
            or membership_gate.get("schema") != "v4.manager_workbench.announcement_connect_membership.v1"
            or membership_gate.get("status") != "VERIFIED"
            or membership_gate.get("market") != "HK_CONNECT"
            or membership_gate.get("target_date") != recovery_lock.get("target_date")
            or membership_gate.get("cutoff") != recovery_lock.get("cutoff")
            or resume_cutoff != recovery_lock.get("cutoff")
            or membership_gate.get("authority_sha256") != recovery_lock.get("membership_authority_sha256")
            or not isinstance(article_id, str)
            or article_id not in recovery_lock.get("eligible_article_ids", [])
            or recovery_lock.get("eligible_count") != len(recovery_lock.get("eligible_article_ids", []))
            or not isinstance(metadata, dict)):
        return False
    current_bodies = recovery_lock.get("current_body_sha256")
    expected_bodies = recovery_lock.get("expected_body_sha256")
    if not isinstance(current_bodies, dict) or not isinstance(expected_bodies, dict):
        return False
    body = payload.get("article_body")
    body_sha256 = payload.get("body_sha256")
    if (not isinstance(body, str) or not isinstance(body_sha256, str)
            or not SHA_RE.fullmatch(body_sha256) or sha(body.encode("utf-8")) != body_sha256
            or current_bodies.get(article_id) != body_sha256
            or expected_bodies.get(article_id, body_sha256) != body_sha256
            or not SHA_RE.fullmatch(str(recovery_lock.get("capture_product_sha256", "")))
            or not SHA_RE.fullmatch(str(recovery_lock.get("row_manifest_sha256", "")))
            or not SHA_RE.fullmatch(str(recovery_lock.get("eligible_article_ids_sha256", "")))):
        return False
    try:
        cutoff = datetime.fromisoformat(str(resume_cutoff))
        available_at = datetime.fromisoformat(str(metadata.get("available_at", "")))
        publication_date = datetime.fromisoformat(str(metadata.get("publication_date", ""))).date()
        target_date = datetime.strptime(str(recovery_lock.get("target_date", "")), "%Y%m%d").date()
    except ValueError:
        return False
    if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or available_at.tzinfo is None or available_at.utcoffset() is None
            or available_at > cutoff or publication_date > target_date
            or payload.get("date") != publication_date.isoformat() or payload.get("market") != "HK"):
        return False
    authority = metadata.get("membership_authority_sha256")
    if (metadata.get("article_membership_status") != "IN"
            or not isinstance(authority, str) or not SHA_RE.fullmatch(authority)
            or authority != membership_gate.get("authority_sha256")):
        return False
    issuer_membership = metadata.get("source_issuer_membership")
    issuer_codes = metadata.get("source_issuer_codes")
    gate_codes = membership_gate.get("codes")
    if (not isinstance(issuer_membership, list) or len(issuer_membership) != 1
            or not isinstance(issuer_membership[0], dict)
            or issuer_membership[0].get("membership_status") != "IN"
            or issuer_membership[0].get("market") != "HK_CONNECT"
            or issuer_membership[0].get("authority_sha256") != authority
            or not isinstance(issuer_membership[0].get("code"), str)
            or not isinstance(issuer_codes, list) or not isinstance(gate_codes, list)):
        return False
    issuer_code = issuer_membership[0]["code"]
    if (issuer_code not in gate_codes
            or not any(isinstance(item, dict) and item.get("code") == issuer_code for item in issuer_codes)):
        return False
    source_sha256 = payload.get("source_sha256")
    if not isinstance(source_sha256, str) or not SHA_RE.fullmatch(source_sha256):
        return False
    origins = metadata.get("source_origins")
    if (not isinstance(origins, list)
            or not any(isinstance(item, dict) and item.get("role") == "CAPTURE_WINDOW_PRODUCT_ROW"
                       and item.get("source_product_sha256") == recovery_lock.get("capture_product_sha256")
                       for item in origins)
            or not any(isinstance(item, dict) and item.get("role") == "VERIFIED_FULL_NOTICE_BODY_PRODUCT"
                       and item.get("source_product_sha256") == source_sha256 for item in origins)):
        return False
    return True


def _recovery_version_binding(record: dict[str, Any], current_payload: dict[str, Any],
                              queue: Any, queue_root: Path, recovery_lock: Any,
                              membership_gate: Any, resume_cutoff: str | None) -> dict[str, Any] | None:
    """Bind one frozen current payload to a preserved, unattempted pre-authority queue version."""
    job = record.get("job")
    if (record.get("source") != "INCREMENTAL_QUEUE" or record.get("status") != "PENDING"
            or not isinstance(job, dict) or job.get("status") != "PENDING"
            or type(job.get("attempt_count")) is not int or job.get("attempt_count") != 0
            or job.get("queue_id") != QUEUE_ID or job.get("max_attempts") != 1):
        return None
    old_key = record.get("idempotency_key") or job.get("idempotency_key")
    if (not isinstance(old_key, str) or old_key != job.get("idempotency_key")
            or not isinstance(job.get("payload_sha256"), str)
            or not SHA_RE.fullmatch(job["payload_sha256"])
            or not _current_recovery_payload_valid(current_payload, recovery_lock, membership_gate,
                                                   resume_cutoff)):
        return None
    old_payload = _queue_payload(queue_root, job)
    old_identity = queue._identity(old_payload)
    current_identity = queue._identity(current_payload)
    if old_identity != job.get("identity"):
        raise FlashRunError("PENDING_RESUME_QUEUE_IDENTITY_MISMATCH")
    identity_fields = ("date", "market", "article_id", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")
    if (any(old_identity.get(field) != current_identity.get(field) for field in identity_fields)
            or old_identity.get("source_sha256") == current_identity.get("source_sha256")
            or _semantic_identity(old_identity) != _semantic_identity(current_identity)):
        return None
    exact_source_fields = ("article_body", "body_sha256", "fixed_fact_ledger", "source_unit_map_sha256",
                           "structured_output_schema", "workflow_profile", "citation_protocol")
    if any(old_payload.get(field) != current_payload.get(field) for field in exact_source_fields):
        return None
    old_meta = old_payload.get("article_metadata")
    new_meta = current_payload.get("article_metadata")
    if (not isinstance(old_meta, dict) or not isinstance(new_meta, dict)
            or old_meta.get("article_membership_status") != "CANNOT_CONFIRM"
            or old_meta.get("membership_authority_sha256") not in (None, "")
            or old_meta.get("source_issuer_membership") not in (None, [])
            or any(old_meta.get(field) != new_meta.get(field) for field in ("publication_date", "title", "symbol"))):
        return None
    try:
        cutoff = datetime.fromisoformat(str(resume_cutoff))
        old_available = datetime.fromisoformat(str(old_meta.get("available_at", "")))
    except ValueError:
        return None
    if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or old_available.tzinfo is None or old_available.utcoffset() is None
            or old_available > cutoff):
        return None
    binding = {
        "schema": "v4.manager_workbench.announcement_flash_queue_version_binding.v1",
        "article_id": current_payload["article_id"],
        "target_date": recovery_lock["target_date"],
        "cutoff": recovery_lock["cutoff"],
        "root_batch_job_id": recovery_lock["root_batch_job_id"],
        "parent_job_id": recovery_lock["parent_job_id"],
        "parent_input_sha256": recovery_lock["parent_input_sha256"],
        "parent_result_sha256": recovery_lock["parent_result_sha256"],
        "row_manifest_sha256": recovery_lock["row_manifest_sha256"],
        "eligible_article_ids_sha256": recovery_lock["eligible_article_ids_sha256"],
        "capture_product_sha256": recovery_lock["capture_product_sha256"],
        "body_sha256": current_payload["body_sha256"],
        "source_unit_map_sha256": current_payload.get("source_unit_map_sha256"),
        "old_idempotency_key": old_key,
        "old_payload_sha256": job["payload_sha256"],
        "old_identity_sha256": sha(canonical(old_identity)),
        "old_source_sha256": old_identity["source_sha256"],
        "old_metadata_sha256": sha(canonical(old_meta)),
        "old_messages_sha256": sha(canonical(old_payload.get("messages"))),
        "new_idempotency_key": _stable_queue_identity(queue, current_payload),
        "new_current_payload_sha256": sha(canonical(current_payload)),
        "new_identity_sha256": sha(canonical(current_identity)),
        "new_source_sha256": current_identity["source_sha256"],
        "new_metadata_sha256": sha(canonical(new_meta)),
        "new_messages_sha256": sha(canonical(current_payload.get("messages"))),
        "membership_authority_sha256": new_meta["membership_authority_sha256"],
    }
    binding["binding_sha256"] = sha(canonical(binding))
    return binding


def _version_association_summary(binding: dict[str, Any], job: dict[str, Any],
                                 disposition: str) -> dict[str, Any]:
    return {"article_id": binding["article_id"], "disposition": disposition,
            "queue_status": job.get("status"), "attempt_count": job.get("attempt_count"),
            "old_idempotency_key": binding["old_idempotency_key"],
            "old_payload_sha256": binding["old_payload_sha256"],
            "new_idempotency_key": job.get("idempotency_key"),
            "new_payload_sha256": job.get("payload_sha256"),
            "new_source_sha256": binding["new_source_sha256"],
            "body_sha256": binding["body_sha256"],
            "membership_authority_sha256": binding["membership_authority_sha256"],
            "capture_product_sha256": binding["capture_product_sha256"],
            "binding_sha256": binding["binding_sha256"]}


def _version_payload_with_capture_provenance_normalized(
        payload: dict[str, Any], expected_capture_sha256: str) -> dict[str, Any] | None:
    """Normalize only the verified capture-row provenance in a saved Reader input."""
    if not isinstance(payload, dict) or not SHA_RE.fullmatch(str(expected_capture_sha256)):
        return None
    try:
        normalized = copy.deepcopy(payload)
        normalized.pop("recovery_version_binding", None)
        metadata = normalized.get("article_metadata")
        batch = normalized.get("validated_article_batch")
        batch_articles = batch.get("articles") if isinstance(batch, dict) else None
        if (not isinstance(metadata, dict) or not isinstance(batch, dict)
                or not isinstance(batch_articles, list) or len(batch_articles) != 1
                or not isinstance(batch_articles[0], dict)
                or canonical(batch_articles[0].get("article_metadata"))
                != canonical(payload.get("article_metadata"))):
            return None
        batch_metadata = copy.deepcopy(batch_articles[0]["article_metadata"])
        batch_articles[0]["article_metadata"] = batch_metadata

        def origins_for(value: Any) -> list[dict[str, Any]] | None:
            origins = value.get("source_origins") if isinstance(value, dict) else None
            if not isinstance(origins, list) or len(origins) < 2:
                return None
            first = origins[0]
            if (not isinstance(first, dict) or first.get("role") != "CAPTURE_WINDOW_PRODUCT_ROW"
                    or _capture_origin_metadata_sha(value) != expected_capture_sha256):
                return None
            return origins

        def products_from(origins: list[dict[str, Any]]) -> list[dict[str, str]] | None:
            products: dict[str, dict[str, str]] = {}
            for origin in origins:
                if (not isinstance(origin, dict)
                        or not isinstance(origin.get("source_product_sha256"), str)
                        or not isinstance(origin.get("source_ref"), str)):
                    return None
                product_sha = origin["source_product_sha256"]
                source_ref = origin["source_ref"]
                if source_ref.startswith("<capture-product-row-ref>"):
                    product_ref = "<capture-product-row-ref>"
                elif "#" in source_ref:
                    product_ref = source_ref.split("#", 1)[0]
                else:
                    return None
                products[product_sha] = {"source_ref": product_ref, "sha256": product_sha}
            return sorted(products.values(), key=lambda item: (item["source_ref"], item["sha256"]))

        original_origins = origins_for(payload.get("article_metadata"))
        if original_origins is None:
            return None
        expected_products = products_from(original_origins)
        if not isinstance(batch.get("source_products"), list) or batch.get("source_products") != expected_products:
            return None

        for target in (metadata, batch_metadata):
            origins = origins_for(target)
            if origins is None:
                return None
            capture_origin = origins[0]
            capture_origin["source_product_sha256"] = "<capture-product-sha256>"
            capture_origin["source_ref"] = "<capture-product-row-ref>"
            capture_origin["source_row_index"] = "<capture-row-index>"
            capture_origin["row_fingerprint_sha256"] = "<capture-row-fingerprint>"
        normalized_products = products_from(batch_metadata["source_origins"])
        if normalized_products is None:
            return None
        batch["source_products"] = normalized_products

        # Reader text excludes capture refs; keep it exact so any prompt/input
        # change outside the proven metadata projection fails closed.
        messages = normalized.get("messages")
        if (not isinstance(messages, list) or len(messages) != 2
                or not isinstance(messages[0], dict) or messages[0].get("role") != "system"
                or not isinstance(messages[1], dict) or messages[1].get("role") != "user"
                or not isinstance(messages[0].get("content"), str)
                or not isinstance(messages[1].get("content"), str)):
            return None
        return normalized
    except (KeyError, TypeError, ValueError):
        return None


def _current_capture_row_matches_payload(payload: dict[str, Any], capture_product: Any,
                                         capture_ref: Any, recovery_lock: Any) -> bool:
    """Bind the generated current payload to its exact immutable capture row."""
    metadata = payload.get("article_metadata") if isinstance(payload, dict) else None
    origins = metadata.get("source_origins") if isinstance(metadata, dict) else None
    rows = capture_product.get("rows") if isinstance(capture_product, dict) else None
    if (not isinstance(metadata, dict) or not isinstance(origins, list) or not origins
            or not isinstance(origins[0], dict) or not isinstance(rows, list)
            or not isinstance(capture_ref, dict) or not isinstance(recovery_lock, dict)):
        return False
    origin = origins[0]
    capture_sha = capture_ref.get("sha256")
    artifact_ref = capture_ref.get("artifact_ref")
    if (capture_sha != recovery_lock.get("capture_product_sha256")
            or not isinstance(capture_sha, str) or not SHA_RE.fullmatch(capture_sha)
            or not isinstance(artifact_ref, str)
            or artifact_ref != f"products/{capture_sha}.json"):
        return False
    if (_capture_origin_metadata_sha(metadata) != capture_sha
            or origin.get("source_ref") is None):
        return False
    row_index = origin.get("source_row_index")
    if type(row_index) is not int or not 0 <= row_index < len(rows):
        return False
    row = rows[row_index]
    article_id = payload.get("article_id")
    if (not isinstance(row, dict) or origin.get("source_ref") != f"{artifact_ref}#/rows/{row_index}"
            or origin.get("row_fingerprint_sha256") != sha(canonical(row))
            or article_id != "EASTMONEY:" + str(row.get("art_code") or "")
            or payload.get("article_body") != row.get("body_text")
            or payload.get("body_sha256") != row.get("body_text_sha256")
            or payload.get("source_sha256") != row.get("source_sha256")
            or metadata.get("publication_date") != row.get("publication_date")
            or metadata.get("title") != row.get("title")
            or metadata.get("available_at") != row.get("available_at")
            or metadata.get("observed_at") != row.get("available_at")
            or metadata.get("source_display_time") != row.get("display_time")
            or metadata.get("source_issuer_codes") != row.get("source_issuer_codes")):
        return False
    full_body_origins = [item for item in origins if isinstance(item, dict)
                         and item.get("role") == "VERIFIED_FULL_NOTICE_BODY_PRODUCT"]
    return (len(full_body_origins) == 1
            and full_body_origins[0].get("source_product_sha256") == payload.get("source_sha256")
            and full_body_origins[0].get("source_ref") ==
            f"products/{payload.get('source_sha256')}.json#notice"
            and full_body_origins[0].get("source_row_index") == 0
            and full_body_origins[0].get("row_fingerprint_sha256") == payload.get("source_sha256"))


def _saved_version_parent_binding_valid(state_root: Path, recovery_lock: dict[str, Any],
                                         binding: dict[str, Any]) -> bool:
    """Require the historical generation to be one exact parent edge in this frozen lineage."""
    parent_id = binding.get("parent_job_id")
    capture_sha = binding.get("capture_product_sha256")
    if not _repair_parent_is_in_verified_lineage(state_root, recovery_lock, parent_id, capture_sha):
        return False
    try:
        root = SafeRoot(state_root)
        input_raw = root.read_bytes(f"announcement_flash/jobs/{parent_id}/input.json", max_bytes=4 * 1024 * 1024)
        result_raw = root.read_bytes(f"announcement_flash/jobs/{parent_id}/result.json", max_bytes=64 * 1024 * 1024)
        if (sha(input_raw) != binding.get("parent_input_sha256")
                or sha(result_raw) != binding.get("parent_result_sha256")):
            return False
        parent_input = _json(input_raw, "VERSION_PARENT_INPUT_INVALID")
        parent_result = _json(result_raw, "VERSION_PARENT_RESULT_INVALID")
        parent_capture = parent_input.get("capture_product") if isinstance(parent_input, dict) else None
        parent_lock = parent_input.get("recovery_lock") if isinstance(parent_input, dict) else None
        # A saved version binding names the recovery parent and the capture
        # product used by that child generation. Those can be different nodes:
        # prove the job edge by exact input/result SHA, and prove the capture
        # independently via the full hash-linked lineage above.
        return (isinstance(parent_input, dict) and isinstance(parent_result, dict)
                and isinstance(parent_capture, dict) and isinstance(parent_lock, dict)
                and parent_input.get("job_id") == parent_id
                and SHA_RE.fullmatch(str(parent_capture.get("sha256", ""))) is not None
                and parent_lock.get("root_batch_job_id") == recovery_lock.get("root_batch_job_id")
                and parent_lock.get("target_date") == recovery_lock.get("target_date")
                and parent_lock.get("cutoff") == recovery_lock.get("cutoff")
                and parent_lock.get("membership_authority_sha256") ==
                recovery_lock.get("membership_authority_sha256")
                and parent_lock.get("row_manifest_sha256") == recovery_lock.get("row_manifest_sha256"))
    except (OSError, ValueError, FlashRunError):
        return False


def _persisted_recovery_version(current_key: str, current_job: dict[str, Any],
                                current_payload: dict[str, Any], queue: Any, queue_root: Path,
                                existing_jobs: dict[str, Any], recovery_lock: Any,
                                membership_gate: Any, resume_cutoff: str | None, *,
                                state_root: Path | None = None, capture_product: Any = None,
                                capture_ref: Any = None, validator: Callable[[Any, Any], dict[str, Any]] | None = None
                                ) -> tuple[dict[str, Any], dict[str, Any]] | None:
    stored_payload = _queue_payload(queue_root, current_job)
    binding = stored_payload.get("recovery_version_binding")
    if not isinstance(binding, dict):
        return None
    old_key = binding.get("old_idempotency_key")
    old_job = existing_jobs.get(old_key) if isinstance(old_key, str) else None
    if not isinstance(old_job, dict):
        return None
    old_record = {"source": "INCREMENTAL_QUEUE", "status": old_job.get("status"),
                  "identity": old_job.get("identity"), "job": old_job,
                  "queue_root": queue_root, "idempotency_key": old_key}
    expected = _recovery_version_binding(old_record, current_payload, queue, queue_root,
                                         recovery_lock, membership_gate, resume_cutoff)
    unbound_payload = {key: value for key, value in stored_payload.items()
                       if key != "recovery_version_binding"}
    check = dict(binding)
    check_sha = check.pop("binding_sha256", None)
    if (expected is None or check_sha != sha(canonical(check))
            or current_job.get("idempotency_key") != current_key
            or current_job.get("identity") != queue._identity(stored_payload)):
        return None
    exact_current = binding == expected and unbound_payload == current_payload
    if not exact_current:
        if (not isinstance(state_root, Path) or not isinstance(capture_product, dict)
                or not isinstance(capture_ref, dict) or validator is None
                or not _current_capture_row_matches_payload(current_payload, capture_product,
                                                            capture_ref, recovery_lock)
                or not _saved_version_parent_binding_valid(state_root, recovery_lock, binding)):
            return None
        static_binding_fields = (
            "schema", "article_id", "target_date", "cutoff", "root_batch_job_id",
            "row_manifest_sha256", "eligible_article_ids_sha256", "body_sha256",
            "source_unit_map_sha256", "old_idempotency_key", "old_payload_sha256",
            "old_identity_sha256", "old_source_sha256", "old_metadata_sha256",
            "old_messages_sha256", "new_idempotency_key", "new_identity_sha256",
            "new_source_sha256", "membership_authority_sha256",
        )
        if (any(binding.get(field) != expected.get(field) for field in static_binding_fields)
                or set(binding) != set(expected) | {"binding_sha256"}
                or binding.get("new_current_payload_sha256") != sha(canonical(unbound_payload))
                or binding.get("new_metadata_sha256") != sha(canonical(unbound_payload.get("article_metadata")))
                or binding.get("new_messages_sha256") != sha(canonical(unbound_payload.get("messages")))
                or binding.get("new_identity_sha256") != sha(canonical(queue._identity(unbound_payload)))):
            return None
        stored_capture_sha = binding.get("capture_product_sha256")
        current_capture_sha = recovery_lock.get("capture_product_sha256")
        stored_normalized = _version_payload_with_capture_provenance_normalized(
            unbound_payload, stored_capture_sha)
        current_normalized = _version_payload_with_capture_provenance_normalized(
            current_payload, current_capture_sha)
        if (stored_normalized is None or current_normalized is None
                or canonical(stored_normalized) != canonical(current_normalized)):
            return None
    status = current_job.get("status")
    if status == "PENDING":
        if (not exact_current or type(current_job.get("attempt_count")) is not int
                or current_job.get("attempt_count") != 0):
            return None
        return expected, stored_payload
    if (current_job.get("attempt_count") != 1 or current_job.get("max_attempts") != 1
            or current_job.get("queue_id") != QUEUE_ID):
        return None
    if status == "SUCCEEDED":
        if validator is None:
            return None
        try:
            saved_result, _validated_sha, raw_sha = _read_internal_validated_result(queue_root, current_job)
            raw_value = _read_json_file(queue_root / current_job["raw_path"], raw_sha,
                                        "RECOVERY_VERSION_RAW_RESPONSE_INVALID")
            projected = validator(SimpleNamespace(payload=current_payload), raw_value)
            if projected != saved_result:
                return None
        except Exception:
            return None
    elif status == "FAILED":
        attempts = current_job.get("attempts")
        last = attempts[-1] if isinstance(attempts, list) and attempts else None
        error = last.get("error") if isinstance(last, dict) else None
        attempt_number = last.get("number", last.get("attempt")) if isinstance(last, dict) else None
        if (not isinstance(error, dict) or not SAFE_CODE_RE.fullmatch(str(error.get("code", "")))
                or not isinstance(error.get("stage"), str)
                or attempt_number != 1):
            return None
        raw_ref, raw_sha = last.get("raw_path"), last.get("raw_sha256")
        if raw_ref is not None or raw_sha is not None:
            if (not isinstance(raw_ref, str) or not isinstance(raw_sha, str)
                    or not SHA_RE.fullmatch(raw_sha) or current_job.get("raw_path") != raw_ref
                    or current_job.get("raw_sha256") != raw_sha):
                return None
            try:
                raw_path = (queue_root / raw_ref).resolve()
                if not raw_path.is_relative_to(queue_root.resolve()) or sha(raw_path.read_bytes()) != raw_sha:
                    return None
            except OSError:
                return None
    else:
        return None
    return expected, stored_payload


def _admit_incremental_payloads(payloads: list[dict[str, Any]], queue: Any,
                                pinned_history: list[dict[str, Any]], queue_root: Path,
                                *, resume_same_batch_pending: bool = False,
                                resume_cutoff: str | None = None,
                                recovery_lock: dict[str, Any] | None = None,
                                membership_gate: dict[str, Any] | None = None,
                                allow_enqueue: bool = True,
                                state_root: Path | None = None, capture_product: Any = None,
                                capture_ref: Any = None,
                                validator: Callable[[Any, Any], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Admit new input; explicit recovery may also resume exact zero-attempt IN queue items."""
    state = queue._load_state()
    existing_jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    history = list(pinned_history)
    for key, job in existing_jobs.items():
        identity = job.get("identity") if isinstance(job, dict) else None
        if isinstance(identity, dict):
            history.append({"source": "INCREMENTAL_QUEUE", "status": job.get("status"),
                            "identity": identity, "job": job, "queue_root": queue_root,
                            "idempotency_key": key})
    semantic_index: dict[str, list[dict[str, Any]]] = {}
    reviewed_index: dict[str, list[dict[str, Any]]] = {}
    for record in history:
        semantic = _semantic_identity(record.get("identity", {}))
        if semantic:
            semantic_index.setdefault(semantic, []).append(record)
        if record.get("source") == "PRIOR_REVIEWED_RESULT":
            content = _content_key(record.get("identity", {}))
            if content:
                reviewed_index.setdefault(content, []).append(record)

    allowed_keys: set[str] = set()
    articles_by_key: dict[str, dict[str, Any]] = {}
    new_enqueued_keys: set[str] = set()
    resumed_payloads_by_key: dict[str, dict[str, Any]] = {}
    version_associations: list[dict[str, Any]] = []
    read_only_missing: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    duplicate_count = 0
    conflicts: list[dict[str, Any]] = []
    seen_articles: dict[str, str] = {}
    historical_counts: Counter[str] = Counter()
    for payload in payloads:
        identity = queue._identity(payload)
        semantic = _semantic_identity(identity)
        article_id = identity.get("article_id")
        if not semantic or not isinstance(article_id, str):
            conflicts.append({"article_id": article_id, "failure_code": "QUEUE_IDENTITY_INVALID"})
            continue
        if (resume_same_batch_pending and recovery_lock is not None
                and not _current_recovery_payload_valid(payload, recovery_lock, membership_gate, resume_cutoff)):
            conflicts.append({"article_id": article_id,
                              "failure_code": "RECOVERY_CURRENT_VERSION_BINDING_INVALID"})
            continue
        previous_semantic = seen_articles.get(article_id)
        if previous_semantic is not None:
            if previous_semantic == semantic:
                duplicate_count += 1
            else:
                conflicts.append({"article_id": article_id,
                                  "symbol": payload.get("article_metadata", {}).get("symbol"),
                                  "title": payload.get("article_metadata", {}).get("title"),
                                  "failure_code": "DUPLICATE_ARTICLE_IDENTITY_CONFLICT"})
            continue
        seen_articles[article_id] = semantic
        current_key = _stable_queue_identity(queue, payload)
        current_job = existing_jobs.get(current_key)
        if isinstance(current_job, dict):
            stored_current = _queue_payload(queue_root, current_job)
            if "recovery_version_binding" in stored_current:
                versioned = _persisted_recovery_version(
                    current_key, current_job, payload, queue, queue_root, existing_jobs,
                    recovery_lock, membership_gate, resume_cutoff,
                    state_root=state_root, capture_product=capture_product,
                    capture_ref=capture_ref, validator=validator,
                )
                if versioned is None:
                    conflicts.append({"article_id": article_id,
                                      "failure_code": "RECOVERY_VERSION_BINDING_INVALID"})
                    continue
                binding, _stored_payload = versioned
                status = current_job.get("status")
                can_resume = (resume_same_batch_pending and status == "PENDING"
                              and type(current_job.get("attempt_count")) is int
                              and current_job.get("attempt_count") == 0
                              and current_job.get("max_attempts") == 1
                              and current_job.get("queue_id") == QUEUE_ID)
                version_associations.append(_version_association_summary(
                    binding, current_job,
                    "CURRENT_VERSION_RESUMED" if can_resume else f"CURRENT_VERSION_{status or 'UNKNOWN'}_REUSED",
                ))
                if can_resume:
                    allowed_keys.add(current_key)
                    articles_by_key[current_key] = {field: payload[field] for field in (
                        "article_id", "source_sha256", "body_sha256", "article_body",
                        "article_metadata", "fixed_fact_ledger")}
                    resumed_payloads_by_key[current_key] = payload
                    historical_counts["recovery_versioned_pending_resumed"] += 1
                    continue
                matched.append({"record": {"source": "INCREMENTAL_QUEUE", "status": status,
                                            "identity": current_job.get("identity"), "job": current_job,
                                            "queue_root": queue_root, "idempotency_key": current_key},
                                "current_payload": payload, "rules_match": True})
                historical_counts[f"recovery_versioned_{str(status or 'unknown').lower()}_matched"] += 1
                continue
        content = _content_key(identity)
        candidates = reviewed_index.get(content, []) if content else []
        if not candidates:
            candidates = semantic_index.get(semantic, [])
        if candidates:
            record = max(candidates, key=_history_priority)
            if resume_same_batch_pending and record.get("status") == "PENDING":
                eligible_pending = [candidate for candidate in candidates
                                    if candidate.get("source") == "INCREMENTAL_QUEUE"
                                    and candidate.get("status") == "PENDING"
                                    and isinstance(candidate.get("job"), dict)
                                    and type(candidate["job"].get("attempt_count")) is int
                                    and candidate["job"].get("attempt_count") == 0]
                if len(eligible_pending) == 1:
                    resumed = _verified_pending_resume(eligible_pending[0], payload, queue, queue_root,
                                                      semantic, resume_cutoff)
                    if resumed is not None:
                        key, saved_payload = resumed
                        allowed_keys.add(key)
                        articles_by_key[key] = {field: saved_payload[field] for field in (
                            "article_id", "source_sha256", "body_sha256", "article_body",
                            "article_metadata", "fixed_fact_ledger")}
                        resumed_payloads_by_key[key] = payload
                        historical_counts["incremental_pending_resumed"] += 1
                        continue
                    if recovery_lock is not None and membership_gate is not None:
                        binding = _recovery_version_binding(
                            eligible_pending[0], payload, queue, queue_root,
                            recovery_lock, membership_gate, resume_cutoff,
                        )
                        if binding is not None:
                            versioned_payload = {**payload, "recovery_version_binding": binding}
                            version_key = _stable_queue_identity(queue, versioned_payload)
                            if (version_key != binding["new_idempotency_key"]
                                    or version_key == binding["old_idempotency_key"]
                                    or version_key in existing_jobs):
                                conflicts.append({"article_id": article_id,
                                                  "failure_code": "RECOVERY_VERSION_IDEMPOTENCY_CONFLICT"})
                                continue
                            if not allow_enqueue:
                                read_only_missing.append({"article_id": article_id,
                                                          "symbol": payload.get("article_metadata", {}).get("symbol"),
                                                          "title": payload.get("article_metadata", {}).get("title"),
                                                          "queue_reason": "SAVED_CURRENT_VERSION_NOT_PERSISTED"})
                                historical_counts["recovery_versioned_current_missing_read_only"] += 1
                                continue
                            item = queue.enqueue(versioned_payload)
                            if (item.get("idempotency_key") != version_key
                                    or item.get("identity") != queue._identity(versioned_payload)):
                                conflicts.append({"article_id": article_id,
                                                  "failure_code": "RECOVERY_VERSION_QUEUE_IDENTITY_INVALID"})
                                continue
                            status = item.get("status")
                            can_resume = (status == "PENDING" and item.get("attempt_count") == 0
                                          and item.get("max_attempts") == 1
                                          and item.get("queue_id") == QUEUE_ID)
                            version_associations.append(_version_association_summary(
                                binding, item,
                                "CURRENT_VERSION_ENQUEUED" if can_resume else
                                f"CURRENT_VERSION_{status or 'UNKNOWN'}_NOT_RUNNABLE",
                            ))
                            if can_resume:
                                allowed_keys.add(version_key)
                                new_enqueued_keys.add(version_key)
                                articles_by_key[version_key] = {field: payload[field] for field in (
                                    "article_id", "source_sha256", "body_sha256", "article_body",
                                    "article_metadata", "fixed_fact_ledger")}
                                historical_counts["recovery_versioned_current_admitted"] += 1
                                continue
                            matched.append({"record": {"source": "INCREMENTAL_QUEUE", "status": status,
                                                        "identity": item.get("identity"), "job": item,
                                                        "queue_root": queue_root, "idempotency_key": version_key},
                                            "current_payload": payload, "rules_match": True})
                            historical_counts[f"recovery_versioned_{str(status or 'unknown').lower()}_matched"] += 1
                            continue
            matched.append({"record": record, "current_payload": payload,
                            "rules_match": _semantic_identity(record.get("identity", {})) == semantic})
            prefix = "pinned" if record.get("source") == "PINNED_CANDIDATE" else (
                "reviewed" if record.get("source") == "PRIOR_REVIEWED_RESULT" else "incremental")
            historical_counts[f"{prefix}_{str(record.get('status', 'unknown')).lower()}"] += 1
            continue
        # A queue record present before this click is never made runnable, even
        # if enqueue would return that same attempt_count=0 PENDING item.
        queue_key = _stable_queue_identity(queue, payload)
        was_persisted = queue_key in existing_jobs
        if not allow_enqueue and not was_persisted:
            read_only_missing.append({"article_id": article_id,
                                      "symbol": payload.get("article_metadata", {}).get("symbol"),
                                      "title": payload.get("article_metadata", {}).get("title"),
                                      "queue_reason": "SAVED_QUEUE_ITEM_NOT_PERSISTED"})
            historical_counts["saved_queue_item_missing_read_only"] += 1
            continue
        if not allow_enqueue:
            item = existing_jobs.get(queue_key)
            if not isinstance(item, dict) or item.get("identity") != identity:
                conflicts.append({"article_id": article_id,
                                  "failure_code": "SAVED_QUEUE_ITEM_IDENTITY_MISMATCH"})
                continue
        else:
            item = queue.enqueue(payload)
        key = item["idempotency_key"]
        status = item.get("status")
        if not was_persisted and status == "PENDING" and item.get("attempt_count") == 0:
            allowed_keys.add(key)
            new_enqueued_keys.add(key)
            articles_by_key[key] = {field: payload[field] for field in (
                "article_id", "source_sha256", "body_sha256", "article_body",
                "article_metadata", "fixed_fact_ledger")}
        elif was_persisted:
            # Defensive race case: preserve it as a prior status, never run it
            # on this click. Its identity may be incomplete for semantic match.
            matched.append({"record": {"source": "INCREMENTAL_QUEUE", "status": status,
                                        "identity": item.get("identity", identity), "job": existing_jobs.get(key, item),
                                        "queue_root": queue_root, "idempotency_key": key},
                            "current_payload": payload, "rules_match": True})
            historical_counts[f"incremental_{str(status or 'unknown').lower()}"] += 1
        else:
            # MISSING_MATERIAL and OVERSIZE are durably visible but not model calls.
            if not was_persisted:
                new_enqueued_keys.add(key)
            articles_by_key[key] = {field: payload[field] for field in (
                "article_id", "source_sha256", "body_sha256", "article_body",
                "article_metadata", "fixed_fact_ledger")}
            historical_counts[f"new_{str(status or 'unknown').lower()}"] += 1

    return {"allowed_keys": allowed_keys, "articles_by_key": articles_by_key,
            "matched": matched, "duplicate_count": duplicate_count,
            "conflicts": conflicts, "historical_counts": historical_counts,
            "new_enqueued": len(new_enqueued_keys), "resumed_payloads_by_key": resumed_payloads_by_key,
            "resumed_pending": len(resumed_payloads_by_key),
            "version_associations": version_associations,
            "read_only_missing": read_only_missing}


def _history_payload_and_output(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if isinstance(record.get("article"), dict):
        article = record["article"]
        return article, record.get("output")
    job = record.get("job")
    root = record.get("queue_root")
    if not isinstance(job, dict) or not isinstance(root, Path):
        raise FlashRunError("PRIOR_QUEUE_HISTORY_INVALID")
    if record.get("status") == "SUCCEEDED":
        return _queue_result(root, job)
    return _queue_payload(root, job), None


def _history_failure_code(job: dict[str, Any]) -> str:
    error = job.get("last_error")
    if not isinstance(error, dict):
        attempts = job.get("attempts")
        error = attempts[-1].get("error") if isinstance(attempts, list) and attempts else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and SAFE_CODE_RE.fullmatch(code) else "PRIOR_ATTEMPT_FAILED"


def _current_capture_binding(payload: dict[str, Any], capture_product_sha256: str) -> dict[str, Any]:
    metadata = payload.get("article_metadata", {})
    return {"capture_product_sha256": capture_product_sha256,
            "source_sha256": payload.get("source_sha256"), "body_sha256": payload.get("body_sha256"),
            "source_origins": metadata.get("source_origins", []) if isinstance(metadata, dict) else []}


def _project_historical_matches(matches: list[dict[str, Any]], capture_product_sha256: str) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    capture_bindings: dict[str, dict[str, Any]] = {}
    for match in matches:
        record = match["record"]
        current_payload = match["current_payload"]
        identity = record.get("identity", {})
        article_id = identity.get("article_id")
        source = record.get("source", "PRIOR_QUEUE")
        status = record.get("status", "UNKNOWN")
        current_binding = _current_capture_binding(current_payload, capture_product_sha256)
        capture_bindings[str(article_id)] = current_binding
        prior_article, output = _history_payload_and_output(record)
        metadata = prior_article.get("article_metadata", {})
        title = metadata.get("title") if isinstance(metadata, dict) else None
        symbol = metadata.get("symbol") if isinstance(metadata, dict) else None
        rules_match = bool(match.get("rules_match"))
        outcome = {"article_id": article_id, "symbol": symbol, "title": title,
                   "source": source, "status": status,
                   "body_sha256": identity.get("body_sha256"),
                   "original_source_sha256": identity.get("source_sha256"),
                   "current_capture_source_sha256": current_payload.get("source_sha256"),
                   "rules_match": rules_match}
        if source == "PRIOR_REVIEWED_RESULT" and not rules_match:
            outcome.update(status="SKIPPED_RULES_MISMATCH", skip_reason="PRIOR_REVIEWED_RESULT_RULES_MISMATCH")
            outcomes.append(outcome)
            pending.append({"article_id": article_id, "symbol": symbol, "title": title,
                            "queue_status": "PRIOR_REVIEWED_RESULT",
                            "queue_reason": "PRIOR_REVIEWED_RESULT_RULES_MISMATCH"})
            continue
        if status == "SUCCEEDED":
            if not isinstance(output, dict):
                raise FlashRunError("PRIOR_QUEUE_READER_OUTPUT_MISSING")
            selected_result = (output.get("disposition") in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                               and output.get("direction") == "POSITIVE")
            reuse_status = ("REUSED_PRIOR_VERIFIED_RESULT" if source == "PRIOR_REVIEWED_RESULT"
                            else "REUSED_PINNED_CANDIDATE_RESULT" if source == "PINNED_CANDIDATE"
                            else "REUSED_INCREMENTAL_QUEUE_RESULT")
            if selected_result:
                projected_article = _public_article(str(article_id), prior_article, output)
                projected_article["reuse_status"] = reuse_status
                if source == "PRIOR_REVIEWED_RESULT":
                    projected_article["review_status"] = "PRIOR_INDEPENDENT_REVIEW_PASS_WITH_LIMITATION"
                projected_article["current_capture"] = current_binding
                selected.append(projected_article)
                outcome["skip_reason"] = "PRIOR_SELECTED_RESULT_REUSED_NO_MODEL_CALL"
            else:
                outcome["skip_reason"] = "PRIOR_SUCCEEDED_NONSELECTED_NO_MODEL_RETRY"
            outcome.update(disposition=output.get("disposition"), direction=output.get("direction"),
                           reuse_status=reuse_status)
            outcomes.append(outcome)
            continue
        job = record.get("job", {})
        if status in {"FAILED", "OVERSIZE", "MISSING_MATERIAL"}:
            code = _history_failure_code(job) if isinstance(job, dict) else "PRIOR_ATTEMPT_FAILED"
            failures.append({"article_id": article_id, "symbol": symbol, "title": title,
                             "failure_code": code, "prior_status": status,
                             "skip_reason": "PRIOR_FAILED_RESULT_NOT_RETRIED"})
            outcome.update(failure_code=code, skip_reason="PRIOR_FAILED_RESULT_NOT_RETRIED")
            outcomes.append(outcome)
            continue
        if status in {"PENDING", "RUNNING", "INTERRUPTED"}:
            reason = "PRIOR_INCREMENTAL_RUNNING" if status == "RUNNING" else "PRIOR_QUEUE_PENDING_NOT_RETRIED"
            pending.append({"article_id": article_id, "symbol": symbol, "title": title,
                            "queue_status": status, "queue_reason": reason,
                            "attempt_count": job.get("attempt_count") if isinstance(job, dict) else None})
            outcome.update(skip_reason=reason)
            outcomes.append(outcome)
            continue
        raise FlashRunError("PRIOR_QUEUE_STATUS_UNSUPPORTED")
    return {"selected": selected, "failures": failures, "pending": pending,
            "outcomes": outcomes, "current_capture_bindings": capture_bindings}


def queue_module_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _transport_executor(queue_module: Any, transport: Any, runner: Any, request_material: dict[str, Any],
                        evidence_root: Path,
                        on_progress: Callable[[Any, dict[str, Any]], None] | None = None) -> Callable[[Any], str | bytes]:
    def execute(job: Any) -> str:
        transport.begin_job(job)
        try:
            completion = transport.complete_batch(
                job.payload["messages"], on_event=lambda event: on_progress(job, event) if on_progress else None, tools=[],
                structured_outputs={"json": job.payload["structured_output_schema"]},
                workflow_profile=job.payload["workflow_profile"],
            )
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(exc, "error_code", None) or type(exc).__name__
            transport.finish_job(status="FAILED", code=str(code))
            trace_path = getattr(transport, "_attempt_dir", None)
            raw_paths = sorted(trace_path.glob("round-*.raw.sse")) if trace_path else []
            partial = raw_paths[-1].read_bytes() if raw_paths and raw_paths[-1].is_file() else None
            stable_code = str(code) if SAFE_CODE_RE.fullmatch(str(code)) else "MODEL_TRANSPORT_FAILED"
            raise queue_module.ExecutorFailure(stable_code, code=stable_code, raw_response=partial) from None
        transport.finish_job(status="RESPONSE_RECEIVED", completion=completion)
        if not completion.final_text:
            raise queue_module.ExecutorFailure("EMPTY_MODEL_OUTPUT", code="EMPTY_MODEL_OUTPUT", raw_response=b"")
        return completion.final_text
    return execute


def _part_prompt_hard_cap(payload: dict[str, Any], chunks: Any) -> int | None:
    context_limit = payload.get("context_limit_tokens")
    completion_reserve = payload.get("completion_reserve_tokens")
    safety_margin = payload.get("token_safety_margin")
    if (type(context_limit) is not int or context_limit < 1
            or type(completion_reserve) is not int or completion_reserve < 0
            or type(safety_margin) is not int or safety_margin != chunks.TOKEN_SAFETY_MARGIN):
        return None
    hard_cap = min(chunks.SYNTHESIS_TOKEN_CAP,
                   context_limit - completion_reserve - safety_margin)
    return hard_cap if hard_cap > 0 else None


def _part_prompt_token_preflight_valid(payload: dict[str, Any], chunks: Any) -> bool:
    """Keep the 64k chunk target while allowing a bound repair up to the true hard cap."""
    exact_tokens = payload.get("prompt_tokens_exact")
    target_cap = payload.get("prompt_token_cap")
    if (type(exact_tokens) is not int or exact_tokens < 0 or type(target_cap) is not int
            or target_cap < 1 or target_cap > chunks.PART_TARGET_TOKEN_CAP):
        return False
    hard_cap = _part_prompt_hard_cap(payload, chunks)
    if hard_cap is None or hard_cap < target_cap:
        return False
    binding = payload.get("part_repair_binding")
    repair_cap = payload.get("repair_prompt_hard_cap_tokens")
    if binding is None:
        return repair_cap is None and target_cap == min(chunks.PART_TARGET_TOKEN_CAP, hard_cap) \
            and exact_tokens <= target_cap
    if not isinstance(binding, dict):
        return False
    if (target_cap != min(chunks.PART_TARGET_TOKEN_CAP, hard_cap)
            or type(repair_cap) is not int or repair_cap != hard_cap or exact_tokens > hard_cap):
        return False

    descriptor = payload.get("part_descriptor")
    metadata = payload.get("article_metadata")
    if not isinstance(descriptor, dict) or not isinstance(metadata, dict):
        return False
    expected_binding = {
        "schema": "v4.manager_workbench.announcement_chunk_part_repair.v1",
        "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
        "article_id": payload.get("article_id"),
        "source_sha256": payload.get("source_sha256"),
        "body_sha256": payload.get("body_sha256"),
        "source_unit_map_sha256": payload.get("source_unit_map_sha256"),
        "chunk_plan_sha256": payload.get("chunk_plan_sha256"),
        "part_index": descriptor.get("part_index"),
        "part_count": descriptor.get("part_count"),
        "part_sha256": descriptor.get("part_sha256"),
        "part_target_token_cap": target_cap,
        "repair_prompt_hard_cap_tokens": hard_cap,
        "membership_authority_sha256": metadata.get("membership_authority_sha256"),
        "feedback_addendum_sha256": chunks.PART_REPAIR_ADDENDUM_SHA256,
    }
    if any(binding.get(name) != value for name, value in expected_binding.items()):
        return False
    binding_material = dict(binding)
    binding_sha256 = binding_material.pop("binding_sha256", None)
    return (isinstance(binding_sha256, str) and SHA_RE.fullmatch(binding_sha256) is not None
            and sha(canonical(binding_material)) == binding_sha256)


def _validator(queue_module: Any, runner: Any, contract: Any, request_material: dict[str, Any], length_canary: Any):
    def validate(job: Any, parsed: Any) -> dict[str, Any]:
        payload = job.payload
        task_kind = payload.get("queue_task_kind")
        if task_kind == "announcement_reader_part":
            from v4.manager_workbench import announcement_chunks as chunks

            article_id = payload["article_id"]
            if not _part_prompt_token_preflight_valid(payload, chunks):
                raise queue_module.ValidationRejected("PART_TOKEN_PREFLIGHT_INVALID",
                                                      code="PART_TOKEN_PREFLIGHT_INVALID")
            unit_map = runner.build_source_unit_map(payload["article_body"], payload["body_sha256"])
            if unit_map.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256"):
                raise queue_module.ValidationRejected("PART_SOURCE_UNIT_MAP_MISMATCH",
                                                      code="PART_SOURCE_UNIT_MAP_MISMATCH")
            try:
                result = chunks.validate_part_envelope(
                    parsed, article_id=article_id, source_sha256=payload["source_sha256"],
                    body_sha256=payload["body_sha256"], plan_sha256=payload["chunk_plan_sha256"],
                    part=payload["part_descriptor"], unit_map=unit_map, body=payload["article_body"],
                    validate_schema=lambda output: runner._validate_json_schema(
                        output, runner.build_simple_reader_wire_schema(
                            contract, request_material["citation_protocol"])),
                )
            except Exception as exc:
                code = str(exc) if isinstance(exc, ValueError) and SAFE_CODE_RE.fullmatch(str(exc)) else "PART_READER_VALIDATION_REJECTED"
                raise queue_module.ValidationRejected(code, code=code) from None
            return result
        if task_kind == "announcement_reader_synthesis":
            from v4.manager_workbench import announcement_chunks as chunks

            article_id = payload["article_id"]
            unit_map = runner.build_source_unit_map(payload["article_body"], payload["body_sha256"])
            if unit_map.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256"):
                raise queue_module.ValidationRejected("SYNTHESIS_SOURCE_UNIT_MAP_MISMATCH",
                                                      code="SYNTHESIS_SOURCE_UNIT_MAP_MISMATCH")
            try:
                synthesis_input = payload.get("synthesis_input")
                if (not isinstance(synthesis_input, dict)
                        or synthesis_input.get("schema") != chunks.SYNTHESIS_INPUT_SCHEMA
                        or synthesis_input.get("article_id") != article_id
                        or synthesis_input.get("source_sha256") != payload.get("source_sha256")
                        or synthesis_input.get("body_sha256") != payload.get("body_sha256")
                        or synthesis_input.get("plan_sha256") != payload.get("chunk_plan_sha256")
                        or synthesis_input.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")):
                    raise ValueError("SYNTHESIS_INPUT_BINDING_INVALID")
                unhashed_input = {key: value for key, value in synthesis_input.items()
                                  if key != "synthesis_input_sha256"}
                if (sha(canonical(unhashed_input)) != payload.get("synthesis_input_sha256")
                        or synthesis_input.get("synthesis_input_sha256") != payload.get("synthesis_input_sha256")):
                    raise ValueError("SYNTHESIS_INPUT_SHA_MISMATCH")
                reports = synthesis_input.get("part_reports")
                result_shas = [item.get("part_result_sha256") for item in reports
                               if isinstance(item, dict)] if isinstance(reports, list) else []
                if result_shas != payload.get("part_result_sha256s"):
                    raise ValueError("SYNTHESIS_PART_RESULT_SHA_LIST_MISMATCH")
                expected_intervals = chunks.synthesis_intervals_from_reports(
                    reports, article_id=article_id, unit_map=unit_map)
                if expected_intervals != payload.get("allowed_source_intervals"):
                    raise ValueError("SYNTHESIS_ALLOWED_INTERVALS_MISMATCH")
                exact_tokens = payload.get("prompt_tokens_exact")
                token_cap = payload.get("prompt_token_cap")
                context_limit = payload.get("context_limit_tokens")
                completion_reserve = payload.get("completion_reserve_tokens")
                safety_margin = payload.get("token_safety_margin")
                expected_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP,
                                         context_limit - completion_reserve - safety_margin)
                                     if type(context_limit) is int and type(completion_reserve) is int
                                     and type(safety_margin) is int else -1)
                if (type(exact_tokens) is not int or exact_tokens < 0 or type(token_cap) is not int
                        or type(completion_reserve) is not int or completion_reserve < 0
                        or safety_margin != chunks.TOKEN_SAFETY_MARGIN
                        or expected_hard_cap < 1 or token_cap != expected_hard_cap
                        or exact_tokens > token_cap or token_cap > chunks.SYNTHESIS_TOKEN_CAP):
                    raise ValueError("SYNTHESIS_TOKEN_PREFLIGHT_INVALID")
                chunks.validate_synthesis_citations(
                    parsed, article_id=article_id, unit_map=unit_map,
                    allowed_intervals=[tuple(item) for item in payload.get("allowed_source_intervals", [])],
                    source_sha256=payload["source_sha256"], body_sha256=payload["body_sha256"],
                    validate_schema=lambda output: runner._validate_json_schema(
                        output, runner.build_simple_reader_wire_schema(
                            contract, request_material["citation_protocol"])),
                )
            except Exception as exc:
                code = str(exc) if isinstance(exc, ValueError) and SAFE_CODE_RE.fullmatch(str(exc)) else "SYNTHESIS_READER_VALIDATION_REJECTED"
                raise queue_module.ValidationRejected(code, code=code) from None
        article = {key: payload[key] for key in (
            "article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")
        }
        batch = payload["validated_article_batch"]
        article_id = article["article_id"]
        try:
            projected, _receipt = runner.project_simple_workflow_output(
                parsed, batch, contract,
                expected_source_unit_map_sha256_by_article={article_id: payload["source_unit_map_sha256"]},
                citation_protocol=request_material["citation_protocol"], preserve_model_changes=True,
            )
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) else "SIMPLE_WORKFLOW_PROJECTION_FAILED"
            raise queue_module.ValidationRejected(code, code=code) from None
        raw_text = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        valid, errors = runner._validate_batch_output(raw_text, batch, contract)
        if errors or set(valid) != {article_id}:
            code = errors.get(article_id, "MODEL_OUTPUT_VALIDATION_REJECTED")
            raise queue_module.ValidationRejected(code, code=code)
        return projected
    return validate


def _validate_recovery_lock(input_value: dict[str, Any], capture_ref: dict[str, Any],
                            capture_product: dict[str, Any], membership_gate: dict[str, Any]) -> None:
    from v4.manager_workbench.announcement_membership import capture_recovery_manifest
    from v4.manager_workbench.contracts import digest as v4_digest

    recovery_lock = input_value.get("recovery_lock")
    if not isinstance(recovery_lock, dict):
        raise FlashRunError("RECOVERY_LOCK_REQUIRED")
    try:
        manifest = capture_recovery_manifest(capture_product.get("rows"), membership_gate)
    except (TypeError, ValueError, KeyError):
        raise FlashRunError("RECOVERY_CAPTURE_MANIFEST_INVALID") from None
    if (recovery_lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
            or not JOB_ID_RE.fullmatch(str(recovery_lock.get("root_batch_job_id", "")))
            or not JOB_ID_RE.fullmatch(str(recovery_lock.get("parent_job_id", "")))
            or not SHA_RE.fullmatch(str(recovery_lock.get("parent_input_sha256", "")))
            or not SHA_RE.fullmatch(str(recovery_lock.get("parent_result_sha256", "")))
            or not SHA_RE.fullmatch(str(recovery_lock.get("parent_capture_product_sha256", "")))
            or recovery_lock.get("target_date") != input_value.get("target_date")
            or recovery_lock.get("cutoff") != input_value.get("cutoff")
            or recovery_lock.get("membership_authority_sha256") != membership_gate.get("authority_sha256")
            or recovery_lock.get("capture_product_sha256") != capture_ref.get("sha256")
            or recovery_lock.get("row_count") != manifest.get("row_count")
            or recovery_lock.get("article_ids_sha256") != manifest.get("article_ids_sha256")
            or recovery_lock.get("row_manifest_sha256") != manifest.get("row_manifest_sha256")
            or recovery_lock.get("eligible_article_ids") != manifest.get("eligible_article_ids")
            or recovery_lock.get("eligible_article_ids_sha256") != manifest.get("eligible_article_ids_sha256")
            or recovery_lock.get("eligible_count") != manifest.get("eligible_count")):
        raise FlashRunError("RECOVERY_BATCH_BINDING_MISMATCH")
    expected_bodies = recovery_lock.get("expected_body_sha256")
    current_bodies = recovery_lock.get("current_body_sha256")
    expected_missing = recovery_lock.get("eligible_missing_body_article_ids")
    if (not isinstance(expected_bodies, dict) or not isinstance(current_bodies, dict)
            or not isinstance(expected_missing, list)
            or recovery_lock.get("current_body_sha256_digest") != v4_digest(current_bodies)):
        raise FlashRunError("RECOVERY_BODY_BINDING_INVALID")
    eligible_ids = set(manifest["eligible_article_ids"])
    actual_bodies = {article_id: body_sha for article_id, body_sha in manifest["body_sha256"].items()
                     if article_id in eligible_ids}
    if (current_bodies != actual_bodies
            or any(actual_bodies.get(key) != value for key, value in expected_bodies.items())):
        raise FlashRunError("RECOVERY_BODY_BINDING_MISMATCH")
    rows_by_id = {"EASTMONEY:" + str(row.get("art_code")): row
                  for row in capture_product.get("rows", []) if isinstance(row, dict)}
    try:
        cutoff = datetime.fromisoformat(input_value["cutoff"])
    except (TypeError, ValueError):
        raise FlashRunError("RECOVERY_CUTOFF_INVALID") from None
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise FlashRunError("RECOVERY_CUTOFF_INVALID")
    for article_id in eligible_ids:
        row = rows_by_id.get(article_id)
        pages = row.get("pages") if isinstance(row, dict) else None
        if (row is None or row.get("body_complete") is not True or not isinstance(pages, list)
                or not pages or row.get("content_page_count") != len(pages)):
            raise FlashRunError("RECOVERY_ELIGIBLE_BODY_INCOMPLETE")
        for page in pages:
            source_ref = page.get("source_ref") if isinstance(page, dict) else None
            if not isinstance(source_ref, dict):
                raise FlashRunError("RECOVERY_BODY_SOURCE_REFERENCE_INVALID")
            try:
                available_at = datetime.fromisoformat(source_ref.get("available_at", ""))
            except (TypeError, ValueError):
                raise FlashRunError("RECOVERY_BODY_SOURCE_TIME_INVALID") from None
            if (available_at.tzinfo is None or available_at.utcoffset() is None
                    or available_at > cutoff):
                raise FlashRunError("RECOVERY_BODY_SOURCE_AFTER_CUTOFF")
            if article_id in expected_missing and not isinstance(source_ref.get("reused_from"), dict):
                raise FlashRunError("RECOVERY_BODY_CACHE_PROVENANCE_MISSING")


def _internal_payload_matches(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    exact_fields = (
        "queue_task_kind", "chunk_plan_sha256", "part_descriptor", "synthesis_input_sha256",
        "synthesis_input", "part_result_sha256s", "allowed_source_intervals",
        "source_unit_map_sha256", "article_id", "source_sha256",
        "body_sha256", "article_body", "fixed_fact_ledger", "messages",
        "structured_output_schema", "workflow_profile", "citation_protocol",
        "input_schema", "prompt_tokens_exact", "prompt_token_cap", "context_limit_tokens",
        "completion_reserve_tokens", "token_safety_margin", "batch_binding_sha256",
        "repair_prompt_hard_cap_tokens",
        "part_repair_binding",
    )
    if any(stored.get(name) != current.get(name) for name in exact_fields):
        return False
    for name in ("date", "market", "prompt_sha256", "model_id", "configuration_sha256", "rules", "role", "stage"):
        if stored.get(name) != current.get(name):
            return False
    old_meta = stored.get("article_metadata")
    new_meta = current.get("article_metadata")
    if not isinstance(old_meta, dict) or not isinstance(new_meta, dict):
        return False
    stable_meta = ("publication_date", "title", "symbol", "observed_at", "available_at", "pit_status",
                   "pit_reason", "article_membership_status", "membership_authority_sha256",
                   "source_issuer_codes", "source_issuer_membership")
    return all(old_meta.get(name) == new_meta.get(name) for name in stable_meta)


def _part_repair_payload(payload: dict[str, Any], failed_job: dict[str, Any], queue_root: Path,
                         recovery_lock: Any, membership_gate: Any,
                         resume_cutoff: str | None,
                         hard_prompt_token_cap: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Make one source-complete validator-feedback version without changing the failed queue item."""
    from v4.manager_workbench import announcement_chunks as chunks

    if (failed_job.get("status") != "FAILED" or failed_job.get("attempt_count") != 1
            or failed_job.get("max_attempts") != 1 or failed_job.get("queue_id") != QUEUE_ID
            or type(hard_prompt_token_cap) is not int or hard_prompt_token_cap < 1
            or hard_prompt_token_cap > chunks.SYNTHESIS_TOKEN_CAP
            or _part_prompt_hard_cap(payload, chunks) != hard_prompt_token_cap
            or not _current_recovery_payload_valid(payload, recovery_lock, membership_gate, resume_cutoff)):
        return None
    part_target_token_cap = payload.get("prompt_token_cap")
    if (type(part_target_token_cap) is not int or part_target_token_cap < 1
            or part_target_token_cap > chunks.PART_TARGET_TOKEN_CAP
            or part_target_token_cap != min(chunks.PART_TARGET_TOKEN_CAP, hard_prompt_token_cap)):
        return None
    descriptor = payload.get("part_descriptor")
    if not isinstance(descriptor, dict):
        return None
    attempts = failed_job.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts else None
    error = last.get("error") if isinstance(last, dict) else None
    if (not isinstance(error, dict) or error.get("stage") != "validator"
            or error.get("code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"):
        return None
    raw_ref = last.get("raw_path")
    raw_sha256 = last.get("raw_sha256")
    if (not isinstance(raw_ref, str) or not isinstance(raw_sha256, str)
            or not SHA_RE.fullmatch(raw_sha256) or raw_ref != failed_job.get("raw_path")
            or raw_sha256 != failed_job.get("raw_sha256")):
        return None
    try:
        envelope = _read_json_file(queue_root / raw_ref, raw_sha256, "PART_REPAIR_RAW_RESPONSE_INVALID")
    except FlashRunError:
        return None
    if (not isinstance(envelope, dict) or set(envelope) != {"action", "lookup_request", "reader_output"}
            or envelope.get("action") != "complete" or envelope.get("lookup_request") is not None
            or not isinstance(envelope.get("reader_output"), dict)):
        return None
    output = envelope["reader_output"]
    violations = [name for name in ("facts", "changes") if output.get(name) != []]
    if not violations:
        return None
    old_key = failed_job.get("idempotency_key")
    binding = {
        "schema": "v4.manager_workbench.announcement_chunk_part_repair.v1",
        "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
        "failed_idempotency_key": old_key,
        "failed_payload_sha256": failed_job.get("payload_sha256"),
        "failed_raw_response_sha256": raw_sha256,
        "nonempty_fixed_fields": violations,
        "article_id": payload.get("article_id"),
        "source_sha256": payload.get("source_sha256"),
        "body_sha256": payload.get("body_sha256"),
        "source_unit_map_sha256": payload.get("source_unit_map_sha256"),
        "chunk_plan_sha256": payload.get("chunk_plan_sha256"),
        "part_index": descriptor.get("part_index"),
        "part_count": descriptor.get("part_count"),
        "part_sha256": descriptor.get("part_sha256"),
        "part_target_token_cap": part_target_token_cap,
        "repair_prompt_hard_cap_tokens": hard_prompt_token_cap,
        "target_date": recovery_lock.get("target_date"),
        "cutoff": recovery_lock.get("cutoff"),
        "root_batch_job_id": recovery_lock.get("root_batch_job_id"),
        "parent_job_id": recovery_lock.get("parent_job_id"),
        "row_manifest_sha256": recovery_lock.get("row_manifest_sha256"),
        "capture_product_sha256": recovery_lock.get("capture_product_sha256"),
        "membership_authority_sha256": membership_gate.get("authority_sha256"),
        "feedback_addendum_sha256": "",
    }
    binding["feedback_addendum_sha256"] = chunks.PART_REPAIR_ADDENDUM_SHA256
    binding["binding_sha256"] = sha(canonical(binding))
    try:
        repair_messages = chunks.part_repair_messages(payload.get("messages"), binding["failure_code"])
    except ValueError:
        return None
    prompt_sha256 = sha(repair_messages[0]["content"].encode("utf-8"))
    feedback_sha256 = sha(canonical({"failure_code": binding["failure_code"],
                                     "nonempty_fixed_fields": violations,
                                     "failed_raw_response_sha256": raw_sha256}))
    repair_payload = {
        **payload,
        "messages": repair_messages,
        "repair_prompt_hard_cap_tokens": hard_prompt_token_cap,
        "prompt_sha256": prompt_sha256,
        "rules": (f"{payload.get('rules', '')}+validator-feedback-repair:v1"
                  f"+prior:{old_key}+failure:{binding['failure_code']}"
                  f"+feedback:{feedback_sha256}+repair-prompt:{prompt_sha256}"
                  f"+repair-addendum:{chunks.PART_REPAIR_ADDENDUM_SHA256}"),
        "part_repair_binding": binding,
    }
    return repair_payload, binding


def _capture_origin_metadata_sha(metadata: Any) -> str | None:
    origins = metadata.get("source_origins") if isinstance(metadata, dict) else None
    origin = origins[0] if isinstance(origins, list) and origins else None
    if not isinstance(origin, dict) or origin.get("role") != "CAPTURE_WINDOW_PRODUCT_ROW":
        return None
    product_sha = origin.get("source_product_sha256")
    source_ref = origin.get("source_ref")
    match = re.fullmatch(r"products/([0-9a-f]{64})\.json#/rows/([0-9]+)", str(source_ref))
    if (not isinstance(product_sha, str) or not SHA_RE.fullmatch(product_sha)
            or match is None or match.group(1) != product_sha
            or origin.get("source_row_index") != int(match.group(2))
            or not isinstance(origin.get("row_fingerprint_sha256"), str)
            or not SHA_RE.fullmatch(origin["row_fingerprint_sha256"])):
        return None
    return product_sha


def _part_repair_payload_with_capture_provenance_normalized(
        payload: dict[str, Any], expected_capture_sha256: str) -> dict[str, Any] | None:
    """Normalize only the verified capture-row SHA/ref projection in a part input."""
    if not isinstance(payload, dict) or not SHA_RE.fullmatch(str(expected_capture_sha256)):
        return None
    try:
        normalized = copy.deepcopy(payload)

        def normalize_metadata(metadata: Any) -> bool:
            origins = metadata.get("source_origins") if isinstance(metadata, dict) else None
            if not isinstance(origins, list) or not origins:
                return False
            origin = origins[0]
            if _capture_origin_metadata_sha(metadata) != expected_capture_sha256:
                return False
            origin["source_product_sha256"] = "<capture-product-sha256>"
            origin["source_ref"] = "<capture-product-row-ref>"
            return True

        top_metadata = normalized.get("article_metadata")
        batch = normalized.get("validated_article_batch")
        batch_articles = batch.get("articles") if isinstance(batch, dict) else None
        if (not isinstance(batch, dict) or not isinstance(batch_articles, list) or len(batch_articles) != 1
                or not isinstance(batch_articles[0], dict)
                or canonical(batch_articles[0].get("article_metadata"))
                != canonical(payload.get("article_metadata"))):
            return None
        batch_metadata = copy.deepcopy(batch_articles[0]["article_metadata"])
        batch_articles[0]["article_metadata"] = batch_metadata

        def products_from_metadata(metadata: Any) -> list[dict[str, str]] | None:
            origins = metadata.get("source_origins") if isinstance(metadata, dict) else None
            if not isinstance(origins, list) or not origins:
                return None
            products: dict[str, dict[str, str]] = {}
            for origin in origins:
                if (not isinstance(origin, dict)
                        or not isinstance(origin.get("source_product_sha256"), str)
                        or not isinstance(origin.get("source_ref"), str)):
                    return None
                product_sha = origin["source_product_sha256"]
                source_ref = origin["source_ref"]
                if source_ref == "<capture-product-row-ref>":
                    product_ref = source_ref
                elif "#" in source_ref:
                    product_ref = source_ref.split("#", 1)[0]
                else:
                    return None
                products[product_sha] = {"source_ref": product_ref, "sha256": product_sha}
            return sorted(products.values(), key=lambda item: (item["source_ref"], item["sha256"]))

        if (not normalize_metadata(top_metadata) or not normalize_metadata(batch_metadata)
                or not isinstance(batch.get("source_products"), list)):
            return None
        expected_products = products_from_metadata(payload.get("article_metadata"))
        if expected_products is None or batch.get("source_products") != expected_products:
            return None
        normalized_products = products_from_metadata(batch_metadata)
        if normalized_products is None:
            return None
        batch["source_products"] = normalized_products

        # Keep the serialized Reader input byte-for-byte identical. Capture
        # provenance is carried in metadata/batch bindings, not the model text.
        normalized["part_repair_binding"] = "<verified-part-repair-binding>"
        return normalized
    except (KeyError, TypeError, ValueError, FlashRunError):
        return None


def _repair_parent_is_in_verified_lineage(state_root: Path | None, recovery_lock: Any,
                                          saved_parent_job_id: Any,
                                          saved_capture_product_sha256: Any) -> bool:
    """Follow every immutable edge to root and bind the old repair to that lineage."""
    if (not isinstance(state_root, Path) or not isinstance(recovery_lock, dict)
            or not isinstance(saved_parent_job_id, str) or not JOB_ID_RE.fullmatch(saved_parent_job_id)
            or not isinstance(saved_capture_product_sha256, str)
            or not SHA_RE.fullmatch(saved_capture_product_sha256)):
        return False
    root_id = recovery_lock.get("root_batch_job_id")
    target_date = recovery_lock.get("target_date")
    cutoff = recovery_lock.get("cutoff")
    authority_sha = recovery_lock.get("membership_authority_sha256")
    manifest_sha = recovery_lock.get("row_manifest_sha256")
    eligible_ids_sha = recovery_lock.get("eligible_article_ids_sha256")
    eligible_ids = recovery_lock.get("eligible_article_ids")
    current_bodies = recovery_lock.get("current_body_sha256")
    current_body_digest = recovery_lock.get("current_body_sha256_digest")
    cursor = recovery_lock.get("parent_job_id")
    expected_input_sha = recovery_lock.get("parent_input_sha256")
    expected_result_sha = recovery_lock.get("parent_result_sha256")
    if (not isinstance(root_id, str) or not JOB_ID_RE.fullmatch(root_id)
            or not isinstance(target_date, str) or not isinstance(cutoff, str)
            or not SHA_RE.fullmatch(str(authority_sha)) or not SHA_RE.fullmatch(str(manifest_sha))
            or not SHA_RE.fullmatch(str(eligible_ids_sha))
            or not isinstance(eligible_ids, list) or not isinstance(current_bodies, dict)
            or recovery_lock.get("eligible_count") != len(eligible_ids)
            or not isinstance(cursor, str) or not JOB_ID_RE.fullmatch(cursor)
            or not SHA_RE.fullmatch(str(expected_input_sha))
            or not SHA_RE.fullmatch(str(expected_result_sha))):
        return False
    from v4.manager_workbench.contracts import digest as v4_digest

    if current_body_digest != v4_digest(current_bodies):
        return False
    expected_capture_sha = recovery_lock.get("parent_capture_product_sha256")
    if not SHA_RE.fullmatch(str(expected_capture_sha)):
        return False
    try:
        root = SafeRoot(state_root)
        seen: set[str] = set()
        found_saved_parent = False
        found_saved_capture = False
        for _ in range(16):
            if cursor in seen:
                return False
            seen.add(cursor)
            input_ref = f"announcement_flash/jobs/{cursor}/input.json"
            result_ref = f"announcement_flash/jobs/{cursor}/result.json"
            input_raw = root.read_bytes(input_ref, max_bytes=4 * 1024 * 1024)
            result_raw = root.read_bytes(result_ref, max_bytes=64 * 1024 * 1024)
            if sha(input_raw) != expected_input_sha or sha(result_raw) != expected_result_sha:
                return False
            input_value = _json(input_raw, "REPAIR_LINEAGE_INPUT_INVALID")
            result_value = _json(result_raw, "REPAIR_LINEAGE_RESULT_INVALID")
            if (not isinstance(input_value, dict) or not isinstance(result_value, dict)
                    or input_value.get("job_id") != cursor or result_value.get("job_id") != cursor
                    or canonical(input_value) != input_raw
                    or input_value.get("target_date") != target_date
                    or input_value.get("cutoff") != cutoff
                    or result_value.get("target_trade_date") != target_date
                    or result_value.get("state") != "PARTIAL"):
                return False
            node_lock = input_value.get("recovery_lock")
            capture = input_value.get("capture_product")
            capture_sha = capture.get("sha256") if isinstance(capture, dict) else None
            if capture_sha != expected_capture_sha:
                return False
            gate = input_value.get("membership_gate")
            result_gate = result_value.get("membership_gate")
            if (not SHA_RE.fullmatch(str(capture_sha))
                    or not isinstance(gate, dict) or not isinstance(result_gate, dict)
                    or gate.get("status") != "VERIFIED" or result_gate.get("status") != "VERIFIED"
                    or gate.get("target_date") != target_date or result_gate.get("target_date") != target_date
                    or gate.get("cutoff") != cutoff or result_gate.get("cutoff") != cutoff
                    or gate.get("authority_sha256") != authority_sha
                    or result_gate.get("authority_sha256") != authority_sha):
                return False
            stop = result_value.get("system_stop")
            if stop is not None:
                try:
                    progress = _json(root.read_bytes(
                        f"announcement_flash/jobs/{cursor}/progress.json", max_bytes=1024 * 1024),
                        "REPAIR_LINEAGE_PROGRESS_INVALID")
                except (OSError, ValueError, FlashRunError):
                    return False
                counts = result_value.get("counts") if isinstance(result_value.get("counts"), dict) else {}
                queue_counts = counts.get("queue") if isinstance(counts.get("queue"), dict) else {}
                if (not isinstance(progress, dict) or progress.get("step") != "FAILED"
                        or progress.get("failure_code") != "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
                        or not isinstance(progress.get("updated_at"), str)
                        or stop != {"failure_code": "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
                                    "stage": "FLASH_SELECTION", "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                                    "failed_at": progress.get("updated_at")}
                        or type(counts.get("failed")) is not int or counts["failed"] <= 0
                        or type(counts.get("new_candidate_stocks")) is not int
                        or counts["new_candidate_stocks"] < 0
                        or queue_counts.get("new_enqueued") != 0
                        or queue_counts.get("new_model_calls_allowed") != 0):
                    return False
            if capture_sha == saved_capture_product_sha256:
                found_saved_capture = True
            if cursor == saved_parent_job_id:
                found_saved_parent = True
            if cursor == root_id:
                return node_lock is None and found_saved_parent and found_saved_capture
            expected_bodies = node_lock.get("expected_body_sha256") if isinstance(node_lock, dict) else None
            if (not isinstance(node_lock, dict)
                    or node_lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
                    or node_lock.get("root_batch_job_id") != root_id
                    or node_lock.get("target_date") != target_date
                    or node_lock.get("cutoff") != cutoff
                    or node_lock.get("membership_authority_sha256") != authority_sha
                    or node_lock.get("row_manifest_sha256") != manifest_sha
                    or node_lock.get("eligible_article_ids_sha256") != eligible_ids_sha
                    or node_lock.get("eligible_article_ids") != eligible_ids
                    or node_lock.get("eligible_count") != len(eligible_ids)
                    or node_lock.get("current_body_sha256_digest") != current_body_digest
                    or node_lock.get("current_body_sha256") != current_bodies
                    or not isinstance(expected_bodies, dict)
                    or not set(expected_bodies).issubset(current_bodies)
                    or any(current_bodies.get(key) != value for key, value in expected_bodies.items())
                    or node_lock.get("capture_product_sha256") != capture_sha):
                return False
            parent_id = node_lock.get("parent_job_id")
            parent_input_sha = node_lock.get("parent_input_sha256")
            parent_result_sha = node_lock.get("parent_result_sha256")
            parent_capture_sha = node_lock.get("parent_capture_product_sha256")
            cursor = parent_id
            expected_input_sha = parent_input_sha
            expected_result_sha = parent_result_sha
            expected_capture_sha = parent_capture_sha
            if (not isinstance(cursor, str) or not JOB_ID_RE.fullmatch(cursor)
                    or not SHA_RE.fullmatch(str(expected_input_sha))
                    or not SHA_RE.fullmatch(str(expected_result_sha))
                    or not SHA_RE.fullmatch(str(parent_capture_sha))):
                return False
    except (OSError, ValueError, FlashRunError):
        return False
    return False


def _part_repair_payload_matches_capture_provenance_drift(
        stored_payload: dict[str, Any], current_payload: dict[str, Any], *,
        recovery_lock: Any, membership_gate: Any, resume_cutoff: str | None,
        state_root: Path | None) -> bool:
    """Allow only a reverified capture-row and immediate-parent change on a saved repair."""
    if not _current_recovery_payload_valid(current_payload, recovery_lock, membership_gate, resume_cutoff):
        return False
    stored_binding = stored_payload.get("part_repair_binding")
    current_binding = current_payload.get("part_repair_binding")
    if not isinstance(stored_binding, dict) or not isinstance(current_binding, dict):
        return False
    old_binding_sha = stored_binding.get("binding_sha256")
    current_binding_sha = current_binding.get("binding_sha256")
    old_binding_material = {key: value for key, value in stored_binding.items() if key != "binding_sha256"}
    current_binding_material = {key: value for key, value in current_binding.items() if key != "binding_sha256"}
    if (not isinstance(old_binding_sha, str) or sha(canonical(old_binding_material)) != old_binding_sha
            or not isinstance(current_binding_sha, str)
            or sha(canonical(current_binding_material)) != current_binding_sha
            or stored_binding.get("capture_product_sha256")
            != _capture_origin_metadata_sha(stored_payload.get("article_metadata"))
            or current_binding.get("capture_product_sha256")
            != recovery_lock.get("capture_product_sha256")
            or stored_binding.get("root_batch_job_id") != recovery_lock.get("root_batch_job_id")
            or not _repair_parent_is_in_verified_lineage(
                state_root, recovery_lock, stored_binding.get("parent_job_id"),
                stored_binding.get("capture_product_sha256"))):
        return False
    old_comparable_binding = dict(stored_binding)
    current_comparable_binding = dict(current_binding)
    for binding in (old_comparable_binding, current_comparable_binding):
        for key in ("capture_product_sha256", "parent_job_id", "binding_sha256"):
            binding.pop(key, None)
    if old_comparable_binding != current_comparable_binding:
        return False
    old_capture_sha = stored_binding.get("capture_product_sha256")
    current_capture_sha = current_binding.get("capture_product_sha256")
    old_normalized = _part_repair_payload_with_capture_provenance_normalized(
        stored_payload, old_capture_sha)
    current_normalized = _part_repair_payload_with_capture_provenance_normalized(
        current_payload, current_capture_sha)
    return (old_normalized is not None and current_normalized is not None
            and canonical(old_normalized) == canonical(current_normalized))


def _reuse_succeeded_part_repair_after_capture_provenance_drift(
        payload: dict[str, Any], queue: Any, queue_root: Path, *, recovery_lock: Any,
        membership_gate: Any, resume_cutoff: str | None, hard_prompt_token_cap: int,
        count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
        state_root: Path | None) -> tuple[str, dict[str, Any], bool, bool] | None:
    """Return an immutable saved repair only when its capture provenance is the sole drift."""
    if not _current_recovery_payload_valid(payload, recovery_lock, membership_gate, resume_cutoff):
        return None
    key = _stable_queue_identity(queue, payload)
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    prior = jobs.get(key) if isinstance(jobs, dict) else None
    if (not isinstance(prior, dict) or prior.get("idempotency_key") != key
            or prior.get("status") != "SUCCEEDED" or prior.get("attempt_count") != 1
            or prior.get("max_attempts") != 1 or prior.get("queue_id") != QUEUE_ID
            or prior.get("identity") != queue._identity(payload)):
        return None
    try:
        stored = _queue_payload(queue_root, prior)
        stored_tokens = stored.get("prompt_tokens_exact")
        current_tokens = payload.get("prompt_tokens_exact")
        if (not _part_repair_payload_matches_capture_provenance_drift(
                stored, payload, recovery_lock=recovery_lock, membership_gate=membership_gate,
                resume_cutoff=resume_cutoff, state_root=state_root)
                or type(stored_tokens) is not int or stored_tokens != current_tokens
                or count_prompt_tokens(stored.get("messages")) != stored_tokens
                or count_prompt_tokens(payload.get("messages")) != current_tokens
                or stored.get("repair_prompt_hard_cap_tokens") != hard_prompt_token_cap):
            return None
        _saved_result, _validated_sha, _raw_sha = _read_internal_validated_result(queue_root, prior)
        return key, prior, False, False
    except Exception:
        return None


def _enqueue_long_body_parts(long_body_specs: dict[str, dict[str, Any]], queue: Any,
                             queue_root: Path, *, allow_same_batch_pending: bool,
                             recovery_lock: Any, membership_gate: Any,
                             resume_cutoff: str | None, prompt_token_cap: int,
                             hard_prompt_token_cap: int,
                             allow_multiple_new_repairs: bool = False,
                             allow_new_repairs: bool = True,
                             allow_enqueue: bool = True,
                             resume_frozen_batch: bool = False,
                             recovered_orphan_keys: set[str] | None = None,
                             blocked_orphan_keys: set[str] | None = None,
                             orphan_candidates: dict[str, str] | None = None,
                             source_job_id: str | None = None,
                             source_input_sha256: str | None = None,
                             state_root: Path | None = None,
                             count_prompt_tokens: Callable[[list[dict[str, Any]]], int]
                             ) -> tuple[set[str], list[dict[str, Any]]]:
    """Reuse unchanged part versions; multi-repair admission requires a verified canary."""
    if not long_body_specs:
        return set(), []
    from v4.manager_workbench import announcement_chunks as chunks

    if (type(prompt_token_cap) is not int or prompt_token_cap < 1
            or prompt_token_cap > chunks.PART_TARGET_TOKEN_CAP
            or type(hard_prompt_token_cap) is not int or hard_prompt_token_cap < prompt_token_cap
            or hard_prompt_token_cap > chunks.SYNTHESIS_TOKEN_CAP):
        raise FlashRunError("PART_PROMPT_BUDGET_INVALID")
    allowed_keys: set[str] = set()
    internal_records: list[dict[str, Any]] = []
    new_repair_admitted = False
    repair_gate_blocked = False
    recovered_orphan_keys = recovered_orphan_keys or set()
    blocked_orphan_keys = blocked_orphan_keys or set()
    orphan_candidates = orphan_candidates or {}
    for article_id, spec in long_body_specs.items():
        spec["part_keys"] = []
        spec["part_records"] = []
        for payload in spec["part_payloads"]:
            base_binding_failure = None
            base_key = _stable_queue_identity(queue, payload)
            before_state = queue._load_state()
            before_jobs = before_state.get("jobs", {}) if isinstance(before_state, dict) else {}
            saved_base = before_jobs.get(base_key) if isinstance(before_jobs, dict) else None
            historical_conflict = (_historical_success_part_conflict(payload, base_key, queue, queue_root)
                                   if resume_frozen_batch and isinstance(saved_base, dict)
                                   and saved_base.get("status") == "PENDING" else None)
            if historical_conflict is not None:
                base_job = saved_base
                base_created = base_runnable = False
                base_binding_failure = "HISTORICAL_SUCCESS_PROVENANCE_MISMATCH"
            else:
                try:
                    base_key, base_job, base_created, base_runnable = _enqueue_internal_payload(
                        payload, queue, queue_root,
                        allow_same_batch_pending=(allow_same_batch_pending
                                                  and (allow_new_repairs or resume_frozen_batch)),
                        allow_enqueue=allow_enqueue and allow_new_repairs and not resume_frozen_batch,
                    )
                except FlashRunError as exc:
                    if (resume_frozen_batch and exc.code in {
                            "SAVED_PARTIAL_QUEUE_ITEM_NOT_FOUND", "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"}):
                        base_key = _stable_queue_identity(queue, payload)
                        base_job = saved_base if isinstance(saved_base, dict) else {
                            "status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                        base_created = base_runnable = False
                        base_binding_failure = ("FROZEN_QUEUE_IDENTITY_CONFLICT" if exc.code ==
                                                "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT" else
                                                "FROZEN_QUEUE_ITEM_MISSING")
                    elif allow_new_repairs or exc.code != "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT":
                        raise
                    else:
                        base_key = _stable_queue_identity(queue, payload)
                        base_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                        base_created = base_runnable = False
                        base_binding_failure = exc.code
            selected_key, selected_job = base_key, base_job
            created, runnable = base_created, base_runnable
            repair_status = "NOT_REQUIRED" if base_job.get("status") != "FAILED" else "NOT_ELIGIBLE"
            repair_binding = None
            repair_failure_code = None
            orphan_recovery = None
            prior_orphan = None
            if (resume_frozen_batch and base_job.get("status") == "FAILED"
                    and base_key not in recovered_orphan_keys and base_key not in blocked_orphan_keys):
                try:
                    prior_orphan = _prior_orphan_recovery(
                        payload, base_key, base_job, queue, queue_root,
                        source_job_id=source_job_id, source_input_sha256=source_input_sha256,
                    )
                except FlashRunError as exc:
                    base_binding_failure = exc.code

            if base_binding_failure in {"ORPHAN_RECOVERY_IDENTITY_CONFLICT", "ORPHAN_RECOVERY_PAYLOAD_CONFLICT"}:
                selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                base_created = base_runnable = created = runnable = False
                repair_status = "ORPHAN_RECOVERY_BLOCKED"
            elif prior_orphan is not None:
                selected_key, selected_job = prior_orphan
                created = False
                runnable = (selected_job.get("status") == "PENDING"
                            and type(selected_job.get("attempt_count")) is int
                            and selected_job.get("attempt_count") == 0)
                orphan_recovery = {"status": selected_job.get("status", "UNKNOWN"),
                                   "idempotency_key": selected_key,
                                   "source_idempotency_key": base_key,
                                   "attempt_count": selected_job.get("attempt_count"),
                                   "reused": True}
                repair_status = "ORPHAN_RECOVERY_REUSED"
            elif base_key in blocked_orphan_keys:
                base_binding_failure = ("ORPHAN_COMPLETE_RESULT_CANNOT_CONFIRM"
                                        if orphan_candidates.get(base_key) == "COMPLETE" else
                                        "ORPHAN_RESULT_UNVERIFIED")
                base_created = base_runnable = created = runnable = False
                selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                repair_status = "ORPHAN_RECOVERY_BLOCKED"
            elif (resume_frozen_batch and base_key in recovered_orphan_keys
                  and base_job.get("status") == "FAILED"):
                attempts = base_job.get("attempts") if isinstance(base_job.get("attempts"), list) else []
                last_attempt = attempts[-1] if attempts else None
                last_error = last_attempt.get("error") if isinstance(last_attempt, dict) else None
                if (isinstance(last_attempt, dict) and last_attempt.get("status") == "INTERRUPTED"
                        and isinstance(last_error, dict) and last_error.get("code") == "PROCESS_INTERRUPTED"
                        and type(base_job.get("attempt_count")) is int and base_job.get("attempt_count") == 1
                        and isinstance(source_job_id, str) and JOB_ID_RE.fullmatch(source_job_id)
                        and isinstance(source_input_sha256, str) and SHA_RE.fullmatch(source_input_sha256)):
                    recovery_payload = _orphan_recovery_payload(
                        payload, base_job, source_job_id=source_job_id,
                        source_input_sha256=source_input_sha256, source_key=base_key,
                    )
                    binding = recovery_payload["interrupted_attempt_recovery"]
                    try:
                        selected_key, selected_job, created, runnable = _enqueue_internal_payload(
                            recovery_payload, queue, queue_root,
                            allow_same_batch_pending=allow_same_batch_pending,
                            allow_enqueue=allow_enqueue,
                        )
                    except FlashRunError as exc:
                        if exc.code not in {"INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
                                            "SAVED_PARTIAL_QUEUE_ITEM_NOT_FOUND"}:
                            raise
                        selected_key = _stable_queue_identity(queue, recovery_payload)
                        selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": selected_key}
                        created = runnable = False
                        base_binding_failure = "ORPHAN_RECOVERY_IDENTITY_CONFLICT"
                    else:
                        orphan_recovery = {
                            "status": "PENDING" if runnable else selected_job.get("status", "UNKNOWN"),
                            "idempotency_key": selected_key,
                            "source_idempotency_key": base_key,
                            "binding_sha256": sha(canonical(binding)),
                            "attempt_count": selected_job.get("attempt_count"),
                        }
                        repair_status = "ORPHAN_RECOVERY_PENDING" if runnable else "ORPHAN_RECOVERY_REUSED"
                else:
                    base_binding_failure = "ORPHAN_INTERRUPTION_BINDING_INVALID"
                    selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                    created = runnable = False
                    repair_status = "ORPHAN_RECOVERY_BLOCKED"
            elif (resume_frozen_batch and base_key in orphan_candidates
                  and base_job.get("status") == "RUNNING"):
                # A dry run only reports the candidate. The actual continuation
                # must acquire the queue's model lock and record interruption.
                orphan_recovery = {"status": orphan_candidates[base_key],
                                   "source_idempotency_key": base_key,
                                   "eligible": orphan_candidates[base_key] == "OWNER_CLEAR_NO_RESULT"}

            if base_job.get("status") == "FAILED" and not resume_frozen_batch:
                repair = _part_repair_payload(
                    payload, base_job, queue_root, recovery_lock, membership_gate, resume_cutoff,
                    hard_prompt_token_cap,
                )
                if repair is not None:
                    repair_payload, repair_binding = repair
                    try:
                        repair_tokens = int(count_prompt_tokens(repair_payload["messages"]))
                    except (TypeError, ValueError):
                        repair_tokens = hard_prompt_token_cap + 1
                    if repair_tokens <= hard_prompt_token_cap and not repair_gate_blocked:
                        repair_payload["prompt_tokens_exact"] = repair_tokens
                        repair_key = _stable_queue_identity(queue, repair_payload)
                        current_jobs = queue._load_state().get("jobs", {})
                        prior_repair = current_jobs.get(repair_key) if isinstance(current_jobs, dict) else None
                        if isinstance(prior_repair, dict):
                            try:
                                repair_key, prior_repair, repair_created, repair_runnable = _enqueue_internal_payload(
                                    repair_payload, queue, queue_root,
                                    allow_same_batch_pending=allow_same_batch_pending,
                                    allow_enqueue=allow_new_repairs,
                                )
                            except FlashRunError as exc:
                                if exc.code != "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT":
                                    raise
                                provenance_reuse = _reuse_succeeded_part_repair_after_capture_provenance_drift(
                                    repair_payload, queue, queue_root,
                                    recovery_lock=recovery_lock, membership_gate=membership_gate,
                                    resume_cutoff=resume_cutoff,
                                    hard_prompt_token_cap=hard_prompt_token_cap,
                                    count_prompt_tokens=count_prompt_tokens, state_root=state_root,
                                )
                                if provenance_reuse is not None:
                                    repair_key, prior_repair, repair_created, repair_runnable = provenance_reuse
                                elif allow_new_repairs:
                                    raise
                                else:
                                    repair_status = "REPAIR_SAVED_VERSION_CONFLICT"
                                    repair_failure_code = exc.code
                                    prior_repair = None
                        if isinstance(prior_repair, dict):
                            selected_key, selected_job = repair_key, prior_repair
                            created, runnable = repair_created, repair_runnable
                            repair_failure_code = "PART_FIXED_FIELDS_MUST_BE_EMPTY"
                            if selected_job.get("status") == "SUCCEEDED":
                                repair_status = ("REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED"
                                                 if not allow_new_repairs else "REPAIRED_SUCCESS_REUSED")
                                if not allow_multiple_new_repairs:
                                    new_repair_admitted = True
                                    repair_gate_blocked = True
                            elif selected_job.get("status") == "PENDING" and runnable:
                                repair_status = "REPAIR_PENDING_ALLOWED"
                                if not allow_multiple_new_repairs:
                                    new_repair_admitted = True
                                    repair_gate_blocked = True
                            elif selected_job.get("status") == "FAILED":
                                repair_status = "REPAIR_FAILED_TERMINAL"
                                repair_gate_blocked = True
                            else:
                                repair_status = "REPAIR_NOT_RUNNABLE"
                                repair_gate_blocked = True
                        elif not allow_new_repairs:
                            repair_status = (repair_status if repair_status == "REPAIR_SAVED_VERSION_CONFLICT"
                                             else "REPAIR_NOT_ADMITTED_READ_ONLY")
                        elif allow_multiple_new_repairs or not new_repair_admitted:
                            repair_key, selected_job, created, runnable = _enqueue_internal_payload(
                                repair_payload, queue, queue_root,
                                allow_same_batch_pending=allow_same_batch_pending,
                            )
                            selected_key = repair_key
                            repair_failure_code = "PART_FIXED_FIELDS_MUST_BE_EMPTY"
                            if created:
                                repair_status = ("REPAIR_AUTO_CONTINUATION_ENQUEUED"
                                                 if allow_multiple_new_repairs else "REPAIR_CANARY_ENQUEUED")
                                new_repair_admitted = True
                                if not allow_multiple_new_repairs:
                                    repair_gate_blocked = True
                            elif selected_job.get("status") == "PENDING" and runnable:
                                repair_status = ("REPAIR_AUTO_CONTINUATION_PENDING_ALLOWED"
                                                 if allow_multiple_new_repairs else "REPAIR_PENDING_ALLOWED")
                                new_repair_admitted = True
                                if not allow_multiple_new_repairs:
                                    repair_gate_blocked = True
                            elif selected_job.get("status") == "SUCCEEDED":
                                repair_status = "REPAIRED_SUCCESS_REUSED"
                                if not allow_multiple_new_repairs:
                                    new_repair_admitted = True
                                    repair_gate_blocked = True
                            elif selected_job.get("status") == "FAILED":
                                repair_status = "REPAIR_FAILED_TERMINAL"
                                repair_gate_blocked = True
                            else:
                                repair_status = "REPAIR_NOT_RUNNABLE"
                        else:
                            repair_status = "GATED_AFTER_ONE_NEW_REPAIR"
                    elif repair_tokens > hard_prompt_token_cap:
                        repair_status = "REPAIR_CONTEXT_PENDING"
                        if not allow_multiple_new_repairs:
                            repair_gate_blocked = True
                    else:
                        repair_status = "GATED_AFTER_ONE_NEW_REPAIR"

            spec["part_keys"].append(selected_key)
            part_record = {"base_key": base_key, "selected_key": selected_key,
                           "base_status": base_job.get("status"),
                           "base_failure_code": base_binding_failure,
                           "base_payload_sha256": base_job.get("payload_sha256"),
                           "repair_status": repair_status,
                           "historical_success_conflict": historical_conflict,
                           "orphan_recovery": orphan_recovery,
                           "repair_key": selected_key if selected_key != base_key and repair_status.startswith("REPAIR") else None,
                           "repair_binding_sha256": repair_binding.get("binding_sha256")
                           if isinstance(repair_binding, dict) else None,
                           "repair_failure_code": repair_failure_code}
            spec["part_records"].append(part_record)
            internal_records.append({"article_id": article_id, "kind": "part",
                                     "part_index": payload["part_descriptor"]["part_index"],
                                     "key": selected_key, "job": selected_job, "created": created,
                                     "runnable": runnable, "base_key": base_key,
                                     "base_status": base_job.get("status"),
                                     "base_failure_code": base_binding_failure,
                                     "historical_success_conflict": historical_conflict,
                                     "repair_status": repair_status,
                                     "orphan_recovery": orphan_recovery,
                                     "repair_binding_sha256": part_record["repair_binding_sha256"]})
            if runnable:
                allowed_keys.add(selected_key)
    return allowed_keys, internal_records


def _frozen_resume_canary(internal_records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick one zero-attempt frozen PENDING part before the sole orphan recovery."""
    ordinary = [record for record in internal_records
                if record.get("kind") == "part"
                and record.get("base_status") == "PENDING"
                and record.get("base_failure_code") is None
                and record.get("key") == record.get("base_key")
                and record.get("runnable") is True]
    selected = min(ordinary, key=lambda record: (
        str(record.get("article_id", "")), int(record.get("part_index", 0)),
        str(record.get("key", "")))) if ordinary else None
    if selected is not None:
        return selected
    orphan = [record for record in internal_records
              if record.get("kind") == "part"
              and isinstance(record.get("orphan_recovery"), dict)
              and record["orphan_recovery"].get("status") == "PENDING"
              and record.get("runnable") is True]
    return min(orphan, key=lambda record: (
        str(record.get("article_id", "")), int(record.get("part_index", 0)),
        str(record.get("key", "")))) if orphan else None


def _enqueue_internal_payload(payload: dict[str, Any], queue: Any, queue_root: Path,
                              *, allow_same_batch_pending: bool,
                              allow_enqueue: bool = True) -> tuple[str, dict[str, Any], bool, bool]:
    """Idempotently persist an internal part or synthesis; resume only explicit zero-attempt work."""
    identity = queue._identity(payload)
    key = sha(canonical(identity))
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    prior = jobs.get(key) if isinstance(jobs, dict) else None
    created = False
    if prior is None:
        if not allow_enqueue:
            raise FlashRunError("SAVED_PARTIAL_QUEUE_ITEM_NOT_FOUND")
        try:
            queue.enqueue(payload)
            created = True
        except Exception:
            raced_state = queue._load_state()
            raced_jobs = raced_state.get("jobs", {}) if isinstance(raced_state, dict) else {}
            prior = raced_jobs.get(key) if isinstance(raced_jobs, dict) else None
            if not isinstance(prior, dict):
                raise
    if prior is None:
        state = queue._load_state()
        jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        prior = jobs.get(key) if isinstance(jobs, dict) else None
    if not isinstance(prior, dict) or prior.get("identity") != identity:
        raise FlashRunError("INTERNAL_QUEUE_IDENTITY_INVALID")
    stored_payload = _queue_payload(queue_root, prior)
    if not _internal_payload_matches(stored_payload, payload):
        raise FlashRunError("INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT")
    status = prior.get("status")
    runnable = (status == "PENDING" and type(prior.get("attempt_count")) is int
                and prior.get("attempt_count") == 0 and (created or allow_same_batch_pending))
    return key, prior, created, runnable


def _admit_synthesis_if_within_budget(payload: dict[str, Any], prompt_tokens: int, token_cap: int,
                                      queue: Any, queue_root: Path, *,
                                      allow_same_batch_pending: bool,
                                      allow_enqueue: bool = True) -> tuple[str | None, dict[str, Any] | None,
                                                                               bool, bool]:
    """Do not persist or expose a synthesis request that failed exact token preflight."""
    from v4.manager_workbench import announcement_chunks as chunks

    context_limit = payload.get("context_limit_tokens")
    completion_reserve = payload.get("completion_reserve_tokens")
    safety_margin = payload.get("token_safety_margin")
    expected_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP,
                             context_limit - completion_reserve - safety_margin)
                         if type(context_limit) is int and type(completion_reserve) is int
                         and type(safety_margin) is int else -1)
    if (type(prompt_tokens) is not int or prompt_tokens < 0 or type(token_cap) is not int or token_cap < 1
            or expected_hard_cap < 1 or token_cap != expected_hard_cap
            or safety_margin != chunks.TOKEN_SAFETY_MARGIN
            or completion_reserve < 0 or token_cap > chunks.SYNTHESIS_TOKEN_CAP
            or payload.get("prompt_tokens_exact") != prompt_tokens):
        raise FlashRunError("SYNTHESIS_TOKEN_PREFLIGHT_INVALID")
    if prompt_tokens > token_cap:
        return None, None, False, False
    return _enqueue_internal_payload(payload, queue, queue_root,
                                     allow_same_batch_pending=allow_same_batch_pending,
                                     allow_enqueue=allow_enqueue)


def _read_internal_validated_result(queue_root: Path, job: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    if job.get("status") != "SUCCEEDED":
        raise FlashRunError("INTERNAL_QUEUE_RESULT_NOT_SUCCEEDED")
    validated_ref = job.get("validated_path")
    raw_ref = job.get("raw_path")
    if not isinstance(validated_ref, str) or not isinstance(raw_ref, str):
        raise FlashRunError("INTERNAL_QUEUE_RESULT_REFERENCE_INVALID")
    validated_path = (queue_root / validated_ref).resolve()
    raw_path = (queue_root / raw_ref).resolve()
    if (not validated_path.is_relative_to(queue_root.resolve())
            or not raw_path.is_relative_to(queue_root.resolve())):
        raise FlashRunError("INTERNAL_QUEUE_RESULT_REFERENCE_INVALID")
    validated_raw = validated_path.read_bytes()
    raw_response = raw_path.read_bytes()
    validated_sha = job.get("validated_sha256")
    raw_sha = job.get("raw_sha256")
    if (not isinstance(validated_sha, str) or not SHA_RE.fullmatch(validated_sha)
            or sha(validated_raw) != validated_sha or not isinstance(raw_sha, str)
            or not SHA_RE.fullmatch(raw_sha) or sha(raw_response) != raw_sha):
        raise FlashRunError("INTERNAL_QUEUE_RESULT_SHA_MISMATCH")
    value = _json(validated_raw, "INTERNAL_QUEUE_RESULT_JSON_INVALID")
    if not isinstance(value, dict):
        raise FlashRunError("INTERNAL_QUEUE_RESULT_JSON_INVALID")
    return value, validated_sha, raw_sha


def _synthesis_payload_with_capture_provenance_normalized(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize only the known capture-origin fields in a synthesis envelope."""
    if not isinstance(payload, dict):
        return None
    try:
        normalized = copy.deepcopy(payload)
        # The current synthesis may use the larger frozen hard cap after an
        # earlier successful synthesis was admitted under the old 64k target.
        # Reuse validates both cap declarations independently below.
        normalized.pop("prompt_token_cap", None)

        def normalize_metadata(metadata: Any) -> bool:
            if not isinstance(metadata, dict):
                return False
            origins = metadata.get("source_origins")
            if (not isinstance(origins, list) or not origins or not isinstance(origins[0], dict)
                    or origins[0].get("role") != "CAPTURE_WINDOW_PRODUCT_ROW"
                    or not SHA_RE.fullmatch(str(origins[0].get("source_product_sha256", "")))
                    or not isinstance(origins[0].get("source_ref"), str)
                    or not origins[0]["source_ref"]):
                return False
            origins[0]["source_product_sha256"] = "<capture-product-sha256>"
            origins[0]["source_ref"] = "<capture-product-row-ref>"
            return True

        top_metadata = normalized.get("article_metadata")
        batch = normalized.get("validated_article_batch")
        batch_articles = batch.get("articles") if isinstance(batch, dict) else None
        batch_metadata_value = batch_articles[0].get("article_metadata") if (
            isinstance(batch_articles, list) and len(batch_articles) == 1
            and isinstance(batch_articles[0], dict)) else None
        if (not isinstance(batch, dict) or not isinstance(batch_metadata_value, dict)
                or canonical(batch_metadata_value) != canonical(payload.get("article_metadata"))):
            return None
        # Detach from the article object, which is shared with the batch in the
        # live in-memory payload before it is serialized by the queue.
        batch_metadata = copy.deepcopy(batch_metadata_value)
        batch_articles[0]["article_metadata"] = batch_metadata

        def source_products(metadata: dict[str, Any]) -> list[dict[str, str]] | None:
            origins = metadata.get("source_origins")
            if not isinstance(origins, list) or not origins:
                return None
            products: dict[str, dict[str, str]] = {}
            for origin in origins:
                if (not isinstance(origin, dict)
                        or not isinstance(origin.get("source_product_sha256"), str)
                        or not isinstance(origin.get("source_ref"), str)):
                    return None
                product_sha = origin["source_product_sha256"]
                source_ref = origin["source_ref"]
                if source_ref == "<capture-product-row-ref>":
                    product_ref = source_ref
                elif "#" in source_ref:
                    product_ref = source_ref.split("#", 1)[0]
                else:
                    return None
                products[product_sha] = {"source_ref": product_ref, "sha256": product_sha}
            return sorted(products.values(), key=lambda item: (item["source_ref"], item["sha256"]))

        expected_products = source_products(payload.get("article_metadata"))
        stored_products = batch.get("source_products")
        if (expected_products is None or not isinstance(stored_products, list)
                or stored_products != expected_products or not normalize_metadata(top_metadata)
                or not normalize_metadata(batch_metadata)):
            return None
        # The batch product list is a deterministic projection of source_origins.
        # Rebuild it after normalizing the single capture-window origin because
        # changing that ref can reorder the sorted set of source products.
        normalized_products = source_products(batch_metadata)
        if normalized_products is None:
            return None
        batch["source_products"] = normalized_products
        messages = normalized.get("messages")
        if (not isinstance(messages, list) or len(messages) != 2
                or not isinstance(messages[0], dict) or not isinstance(messages[1], dict)
                or messages[0].get("role") != "system" or messages[1].get("role") != "user"
                or not isinstance(messages[1].get("content"), str)):
            return None
        prefix, suffix = "ARTICLE_SYNTHESIS_BEGIN\n", "\nARTICLE_SYNTHESIS_END"
        content = messages[1]["content"]
        if not content.startswith(prefix) or not content.endswith(suffix):
            return None
        try:
            envelope = json.loads(content[len(prefix):-len(suffix)])
        except json.JSONDecodeError:
            return None
        if (not isinstance(envelope, dict)
                or canonical(envelope.get("article_metadata")) != canonical(payload.get("article_metadata"))
                or not normalize_metadata(envelope.get("article_metadata"))):
            return None
        messages[1]["content"] = prefix + json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":")) + suffix
        # Token counts can legitimately diverge when capture provenance changes
        # serialized metadata. The reuse gate independently recounts each exact
        # message array and checks both declarations against the unchanged caps.
        normalized["prompt_tokens_exact"] = "<independently-recounted-provenance-token-count>"
        return normalized
    except (KeyError, TypeError, ValueError):
        return None


def _current_synthesis_recovery_binding_valid(payload: dict[str, Any], recovery_lock: Any,
                                               membership_gate: Any) -> bool:
    """Fail closed unless the current synthesis remains inside its frozen HK lock."""
    from v4.manager_workbench import announcement_chunks as chunks

    metadata = payload.get("article_metadata")
    synthesis_input = payload.get("synthesis_input")
    origins = metadata.get("source_origins") if isinstance(metadata, dict) else None
    eligible_ids = recovery_lock.get("eligible_article_ids") if isinstance(recovery_lock, dict) else None
    current_bodies = recovery_lock.get("current_body_sha256") if isinstance(recovery_lock, dict) else None
    expected_bodies = recovery_lock.get("expected_body_sha256") if isinstance(recovery_lock, dict) else None
    if (not isinstance(metadata, dict) or not isinstance(synthesis_input, dict)
            or not isinstance(origins, list) or not origins or not isinstance(origins[0], dict)
            or not isinstance(eligible_ids, list) or not isinstance(current_bodies, dict)
            or not isinstance(expected_bodies, dict)):
        return False
    if (not isinstance(recovery_lock, dict) or not isinstance(membership_gate, dict)
            or recovery_lock.get("schema") != "v4.manager_workbench.announcement_flash_recovery_lock.v1"
            or membership_gate.get("schema") != "v4.manager_workbench.announcement_connect_membership.v1"
            or membership_gate.get("status") != "VERIFIED"
            or recovery_lock.get("membership_authority_sha256") != membership_gate.get("authority_sha256")
            or recovery_lock.get("target_date") != synthesis_input.get("target_date")
            or membership_gate.get("target_date") != recovery_lock.get("target_date")
            or recovery_lock.get("cutoff") != synthesis_input.get("cutoff")
            or recovery_lock.get("row_manifest_sha256") != synthesis_input.get("frozen_recovery_manifest_sha256")
            or recovery_lock.get("root_batch_job_id") != synthesis_input.get("root_batch_job_id")
            or recovery_lock.get("membership_authority_sha256") != synthesis_input.get("membership_authority_sha256")
            or recovery_lock.get("capture_product_sha256") != origins[0].get("source_product_sha256")
            or origins[0].get("role") != "CAPTURE_WINDOW_PRODUCT_ROW"
            or not re.fullmatch(r"products/[0-9a-f]{64}\.json#/rows/[0-9]+",
                                str(origins[0].get("source_ref", "")))
            or payload.get("article_id") not in eligible_ids
            or current_bodies.get(payload.get("article_id")) != payload.get("body_sha256")
            or expected_bodies.get(payload.get("article_id")) != payload.get("body_sha256")
            or metadata.get("article_membership_status") != "IN"
            or metadata.get("membership_authority_sha256") != membership_gate.get("authority_sha256")):
        return False

    issuer_codes = metadata.get("source_issuer_codes")
    issuer_membership = metadata.get("source_issuer_membership")
    allowed_codes = membership_gate.get("codes")
    if not isinstance(issuer_codes, list) or not issuer_codes or not isinstance(issuer_membership, list) \
            or not isinstance(allowed_codes, list):
        return False
    code_values = [item.get("code") for item in issuer_codes if isinstance(item, dict)]
    member_values = [item.get("code") for item in issuer_membership if isinstance(item, dict)]
    if (len(code_values) != len(issuer_codes) or len(member_values) != len(issuer_membership)
            or set(code_values) != set(member_values) or not set(code_values).issubset(set(allowed_codes))
            or any(item.get("membership_status") != "IN" or item.get("market") != "HK_CONNECT"
                   or item.get("authority_sha256") != membership_gate.get("authority_sha256")
                   for item in issuer_membership)):
        return False

    reports = synthesis_input.get("part_reports")
    result_shas = payload.get("part_result_sha256s")
    if (synthesis_input.get("schema") != chunks.SYNTHESIS_INPUT_SCHEMA
            or synthesis_input.get("article_id") != payload.get("article_id")
            or synthesis_input.get("source_sha256") != payload.get("source_sha256")
            or synthesis_input.get("body_sha256") != payload.get("body_sha256")
            or synthesis_input.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or synthesis_input.get("plan_sha256") != payload.get("chunk_plan_sha256")
            or synthesis_input.get("batch_binding_sha256") != payload.get("batch_binding_sha256")
            or not isinstance(reports, list) or not reports or not isinstance(result_shas, list)
            or len(reports) != len(result_shas)
            or synthesis_input.get("part_count") != len(reports)):
        return False
    indexes = []
    report_shas = []
    for report in reports:
        descriptor = report.get("part_descriptor") if isinstance(report, dict) else None
        if (not isinstance(descriptor, dict) or type(report.get("part_index")) is not int
                or report.get("part_index") != descriptor.get("part_index")
                or report.get("part_count") != len(reports)
                or descriptor.get("part_count") != len(reports)):
            return False
        result_sha = report.get("part_result_sha256")
        raw_sha = report.get("part_raw_response_sha256")
        if (not isinstance(result_sha, str) or not SHA_RE.fullmatch(result_sha)
                or not isinstance(raw_sha, str) or not SHA_RE.fullmatch(raw_sha)):
            return False
        indexes.append(report["part_index"])
        report_shas.append(result_sha)
    if indexes != list(range(1, len(reports) + 1)) or report_shas != result_shas:
        return False
    synthesis_input_sha = payload.get("synthesis_input_sha256")
    unhashed = {key: value for key, value in synthesis_input.items() if key != "synthesis_input_sha256"}
    try:
        if (synthesis_input.get("synthesis_input_sha256") != synthesis_input_sha
                or not isinstance(synthesis_input_sha, str) or not SHA_RE.fullmatch(synthesis_input_sha)
                or sha(canonical(unhashed)) != synthesis_input_sha):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _reuse_succeeded_synthesis_after_provenance_drift(
        payload: dict[str, Any], queue: Any, queue_root: Path, *, recovery_lock: Any,
        membership_gate: Any, count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
        validator: Callable[[Any, Any], dict[str, Any]]) -> tuple[str, dict[str, Any], bool, bool] | None:
    """Reuse an immutable successful synthesis only for the diagnosed capture-origin delta."""
    if not _current_synthesis_recovery_binding_valid(payload, recovery_lock, membership_gate):
        return None
    key = _stable_queue_identity(queue, payload)
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
    prior = jobs.get(key) if isinstance(jobs, dict) else None
    if (not isinstance(prior, dict) or prior.get("idempotency_key") != key
            or prior.get("status") != "SUCCEEDED" or prior.get("attempt_count") != 1
            or prior.get("max_attempts") != 1 or prior.get("queue_id") != QUEUE_ID
            or prior.get("identity") != queue._identity(payload)):
        return None
    try:
        stored = _queue_payload(queue_root, prior)
        old_normalized = _synthesis_payload_with_capture_provenance_normalized(stored)
        current_normalized = _synthesis_payload_with_capture_provenance_normalized(payload)
        old_tokens, current_tokens = stored.get("prompt_tokens_exact"), payload.get("prompt_tokens_exact")
        cap_fields = ("prompt_token_cap", "context_limit_tokens",
                      "completion_reserve_tokens", "token_safety_margin")
        caps = [stored.get(field) for field in cap_fields]
        current_caps = [payload.get(field) for field in cap_fields]
        from v4.manager_workbench import announcement_chunks as chunks
        saved_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP, caps[1] - caps[2] - caps[3])
                          if all(type(value) is int for value in caps) else -1)
        current_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP, current_caps[1] - current_caps[2] - current_caps[3])
                            if all(type(value) is int for value in current_caps) else -1)
        if (old_normalized is None or current_normalized is None
                or canonical(old_normalized) != canonical(current_normalized)
                or type(old_tokens) is not int or old_tokens < 0
                or type(current_tokens) is not int or current_tokens < 0
                or any(type(value) is not int for value in caps)
                or any(type(value) is not int for value in current_caps)
                or caps[1:] != current_caps[1:]
                or caps[0] < 1 or caps[0] > saved_hard_cap
                or current_caps[0] < 1 or current_caps[0] != current_hard_cap
                or caps[0] > chunks.SYNTHESIS_TOKEN_CAP
                or caps[1] < 1 or caps[2] < 0 or caps[3] != chunks.TOKEN_SAFETY_MARGIN
                or old_tokens > caps[0] or current_tokens > current_caps[0]
                or old_tokens > saved_hard_cap or current_tokens > current_hard_cap
                or old_tokens + caps[2] + caps[3] > caps[1]
                or current_tokens + caps[2] + caps[3] > caps[1]
                or count_prompt_tokens(stored.get("messages")) != old_tokens
                or count_prompt_tokens(payload.get("messages")) != current_tokens):
            return None
        saved_result, _validated_sha, raw_sha = _read_internal_validated_result(queue_root, prior)
        raw_value = _read_json_file(queue_root / prior["raw_path"], raw_sha,
                                    "SAVED_SYNTHESIS_RAW_RESPONSE_INVALID")
        # Run the ordinary validator over the immutable raw response and current
        # source/plan/dependency payload; this is local validation, not inference.
        revalidated_result = validator(SimpleNamespace(payload=payload), raw_value)
        if revalidated_result != saved_result:
            return None
        return key, prior, False, False
    except Exception:
        # The caller retains the strict identity conflict. Any missing or changed
        # binding therefore remains CANNOT_CONFIRM instead of becoming a retry.
        return None


def _recover_failed_synthesis_from_saved_raw(
        payload: dict[str, Any], queue: Any, queue_root: Path, *, recovery_lock: Any,
        membership_gate: Any, count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
        validator: Callable[[Any, Any], dict[str, Any]]) -> dict[str, Any] | None:
    """Derive a candidate from one immutable citation-validation failure, without retrying it."""
    from v4.manager_workbench import announcement_chunks as chunks

    if not _current_synthesis_recovery_binding_valid(payload, recovery_lock, membership_gate):
        return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_CURRENT_BINDING_INVALID"}
    try:
        identity = queue._identity(payload)
        semantic = _semantic_identity(identity)
        state = queue._load_state()
        jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        if semantic is None or not isinstance(jobs, dict):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_QUEUE_IDENTITY_INVALID"}
        failed_candidates = [job for job in jobs.values()
                             if isinstance(job, dict) and job.get("status") == "FAILED"
                             and isinstance(job.get("identity"), dict)
                             and job["identity"].get("role") == "announcement_reader_synthesis"
                             and _semantic_identity(job["identity"]) == semantic]
        if not failed_candidates:
            return None
        if len(failed_candidates) != 1:
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_FAILURE_AMBIGUOUS"}
        prior = failed_candidates[0]
        key = _stable_queue_identity(queue, payload)
        if (prior.get("idempotency_key") != key or prior.get("identity") != identity
                or prior.get("queue_id") != QUEUE_ID or prior.get("status") != "FAILED"
                or prior.get("attempt_count") != 1 or prior.get("max_attempts") != 1):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_FAILURE_IDENTITY_INVALID"}
        attempts = prior.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 1 or not isinstance(attempts[0], dict):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_FAILURE_ATTEMPT_INVALID"}
        attempt = attempts[0]
        error = attempt.get("error")
        raw_ref = prior.get("raw_path")
        raw_sha = prior.get("raw_sha256")
        if (attempt.get("status") != "FAILED" or attempt.get("number") != 1
                or not isinstance(error, dict) or error.get("code") != "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
                or error.get("stage") != "validator"
                or not isinstance(raw_ref, str) or raw_ref != attempt.get("raw_path")
                or not isinstance(raw_sha, str) or not SHA_RE.fullmatch(raw_sha)
                or raw_sha != attempt.get("raw_sha256")
                or prior.get("validated_path") is not None or prior.get("validated_sha256") is not None
                or attempt.get("validated_path") is not None or attempt.get("validated_sha256") is not None):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_FAILURE_BINDING_INVALID"}

        stored = _queue_payload(queue_root, prior)
        if (stored.get("queue_task_kind") != "announcement_reader_synthesis"
                or stored.get("role") != "announcement_reader_synthesis"
                or stored.get("article_id") != payload.get("article_id")
                or stored.get("source_sha256") != payload.get("source_sha256")
                or stored.get("body_sha256") != payload.get("body_sha256")):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_INPUT_IDENTITY_INVALID"}
        old_normalized = _synthesis_payload_with_capture_provenance_normalized(stored)
        current_normalized = _synthesis_payload_with_capture_provenance_normalized(payload)
        if (old_normalized is None or current_normalized is None
                or canonical(old_normalized) != canonical(current_normalized)):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_INPUT_CHANGED"}

        cap_fields = ("prompt_token_cap", "context_limit_tokens",
                      "completion_reserve_tokens", "token_safety_margin")
        saved_caps = [stored.get(field) for field in cap_fields]
        current_caps = [payload.get(field) for field in cap_fields]
        saved_tokens, current_tokens = stored.get("prompt_tokens_exact"), payload.get("prompt_tokens_exact")
        saved_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP, saved_caps[1] - saved_caps[2] - saved_caps[3])
                          if all(type(value) is int for value in saved_caps) else -1)
        current_hard_cap = (min(chunks.SYNTHESIS_TOKEN_CAP,
                                current_caps[1] - current_caps[2] - current_caps[3])
                            if all(type(value) is int for value in current_caps) else -1)
        if (any(type(value) is not int for value in saved_caps + current_caps)
                or saved_caps[1:] != current_caps[1:]
                or saved_caps[0] < 1 or saved_caps[0] > saved_hard_cap
                or current_caps[0] < 1 or current_caps[0] != current_hard_cap
                or saved_caps[0] > chunks.SYNTHESIS_TOKEN_CAP
                or saved_caps[1] < 1 or saved_caps[2] < 0
                or saved_caps[3] != chunks.TOKEN_SAFETY_MARGIN
                or type(saved_tokens) is not int or type(current_tokens) is not int
                or saved_tokens < 0 or current_tokens < 0
                or saved_tokens > saved_caps[0] or current_tokens > current_caps[0]
                or saved_tokens + saved_caps[2] + saved_caps[3] > saved_caps[1]
                or current_tokens + current_caps[2] + current_caps[3] > current_caps[1]
                or count_prompt_tokens(stored.get("messages")) != saved_tokens
                or count_prompt_tokens(payload.get("messages")) != current_tokens):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_TOKEN_BINDING_INVALID"}

        raw_path = (queue_root / raw_ref).resolve()
        if not raw_path.is_relative_to(queue_root.resolve()):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_RAW_REFERENCE_INVALID"}
        raw_bytes = raw_path.read_bytes()
        if sha(raw_bytes) != raw_sha:
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_RAW_SHA_MISMATCH"}
        raw_value = _json(raw_bytes, "SAVED_SYNTHESIS_RAW_JSON_INVALID")
        synthesis_input = payload.get("synthesis_input")
        unit_map = None
        # Rebuild the exact source-unit map from the current full frozen body. The
        # normal validator repeats this check before it projects any reader fields.
        import batch_runner as runner
        unit_map = runner.build_source_unit_map(payload["article_body"], payload["body_sha256"])
        if unit_map.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256"):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_UNIT_MAP_INVALID"}
        normalized_raw, edits = chunks.normalize_synthesis_citation_ids(
            raw_value, article_id=payload["article_id"], unit_map=unit_map,
            part_reports=synthesis_input.get("part_reports") if isinstance(synthesis_input, dict) else None)
        if not edits:
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_RAW_HAS_NO_PROVABLE_NORMALIZATION"}
        # Citation normalization is a recovery-only derivation from this exact
        # failed raw response. Keep the ordinary queue validator strict and pass
        # only the detached, provenance-bound envelope through its checks.
        result = validator(SimpleNamespace(payload=payload), normalized_raw)
        if (not isinstance(result, dict) or not isinstance(result.get("results"), list)
                or len(result["results"]) != 1
                or result["results"][0].get("article_id") != payload.get("article_id")):
            return {"status": "BLOCKED", "failure_code": "SAVED_SYNTHESIS_DERIVED_RESULT_INVALID"}
        trace = {
            "status": "DERIVED_FROM_IMMUTABLE_FAILED_RAW",
            "failure_code": error["code"],
            "source_idempotency_key": key,
            "source_payload_sha256": prior.get("payload_sha256"),
            "source_raw_path": raw_ref,
            "source_raw_sha256": raw_sha,
            "normalized_envelope_sha256": sha(canonical(normalized_raw)),
            "normalization_edits_sha256": sha(canonical(edits)),
            "normalization_edits": edits,
            "derived_validated_result_sha256": sha(canonical(result)),
            "queue_status_preserved": "FAILED",
            "attempt_count_preserved": 1,
            "model_calls": 0,
        }
        return {"status": "RECOVERED", "key": key, "job": prior,
                "result": result, "trace": trace}
    except Exception as exc:
        code = str(exc) if isinstance(exc, (FlashRunError, ValueError)) and SAFE_CODE_RE.fullmatch(str(exc)) \
            else "SAVED_SYNTHESIS_RECOVERY_VALIDATION_FAILED"
        return {"status": "BLOCKED", "failure_code": code}


def _saved_raw_recovery_publication(article_id: str, recovered: dict[str, Any]
                                    ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a recovered validated result into the normal result/API audit surface."""
    trace = recovered.get("trace") if isinstance(recovered, dict) else None
    validated = recovered.get("result") if isinstance(recovered, dict) else None
    results = validated.get("results") if isinstance(validated, dict) else None
    if (not isinstance(trace, dict) or not isinstance(results, list) or len(results) != 1
            or not isinstance(results[0], dict) or results[0].get("article_id") != article_id
            or not isinstance(results[0].get("reader_output"), dict)):
        raise FlashRunError("SAVED_SYNTHESIS_PUBLICATION_RESULT_INVALID")
    validated_sha = sha(canonical(validated))
    if (trace.get("derived_validated_result_sha256") != validated_sha
            or trace.get("queue_status_preserved") != "FAILED"
            or trace.get("attempt_count_preserved") != 1
            or trace.get("model_calls") != 0):
        raise FlashRunError("SAVED_SYNTHESIS_PUBLICATION_BINDING_INVALID")
    output = results[0]["reader_output"]
    disposition = output.get("disposition")
    direction = output.get("direction")
    outcome_status = ("RECOVERED_NOT_SELECTED" if disposition == "NOT_SELECTED"
                      else "RECOVERED_FROM_SAVED_RAW")
    skip_reason = (f"{outcome_status}; disposition={disposition}; direction={direction}; "
                   f"validated_result_sha256={validated_sha}")
    publication = {
        "article_id": article_id,
        **trace,
        "publication_status": "VALIDATED_RESULT_INCLUDED_IN_RESULT_PAYLOAD",
        "validated_result_sha256": validated_sha,
        "validated_result": validated,
    }
    audit_outcome = {
        "article_id": article_id,
        "source": "SAVED_RAW_RECOVERY",
        "status": outcome_status,
        "skip_reason": skip_reason,
        "disposition": disposition,
        "direction": direction,
        "failure_code": trace.get("failure_code"),
        "original_queue_status": trace.get("queue_status_preserved"),
        "original_attempt_count": trace.get("attempt_count_preserved"),
        "source_queue_idempotency_key": trace.get("source_idempotency_key"),
        "source_payload_sha256": trace.get("source_payload_sha256"),
        "source_raw_sha256": trace.get("source_raw_sha256"),
        "validated_result_sha256": validated_sha,
    }
    return publication, audit_outcome


def _verify_completed_part_repair_canary(spec: dict[str, Any], part_record: dict[str, Any],
                                         queue: Any, queue_root: Path, *,
                                         recovery_lock: Any, membership_gate: Any,
                                         resume_cutoff: str | None,
                                         hard_prompt_token_cap: int,
                                         count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
                                         runner: Any, contract: Any, state_root: Path | None,
                                         request_material: dict[str, Any]) -> tuple[bool, str | None]:
    """Revalidate a successful repair against its failed input and full frozen source plan."""
    from v4.manager_workbench import announcement_chunks as chunks

    try:
        article = spec.get("article")
        unit_map = spec.get("unit_map")
        plan = spec.get("plan")
        parts = plan.get("parts") if isinstance(plan, dict) else None
        part_index = part_record.get("part_index")
        payloads = spec.get("part_payloads")
        if (not isinstance(article, dict) or not isinstance(unit_map, dict)
                or not isinstance(plan, dict) or not isinstance(parts, list)
                or type(part_index) is not int or not 1 <= part_index <= len(parts)
                or not isinstance(payloads, list) or len(payloads) != len(parts)):
            raise FlashRunError("REPAIR_CANARY_SOURCE_PLAN_INVALID")
        chunks.verify_part_coverage(article.get("article_body"), article.get("body_sha256"), unit_map, plan)
        rebuilt_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
        if rebuilt_map != unit_map:
            raise FlashRunError("REPAIR_CANARY_SOURCE_UNIT_MAP_CHANGED")

        base_key = part_record.get("base_key")
        repair_key = part_record.get("repair_key") or part_record.get("key")
        if (not isinstance(base_key, str) or not isinstance(repair_key, str)
                or part_record.get("selected_key", part_record.get("key")) != repair_key):
            raise FlashRunError("REPAIR_CANARY_KEY_BINDING_INVALID")
        state = queue._load_state()
        jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        base_job = jobs.get(base_key) if isinstance(jobs, dict) else None
        repair_job = jobs.get(repair_key) if isinstance(jobs, dict) else None
        if (not isinstance(base_job, dict) or base_job.get("status") != "FAILED"
                or base_job.get("idempotency_key") != base_key or base_job.get("attempt_count") != 1
                or base_job.get("max_attempts") != 1 or base_job.get("queue_id") != QUEUE_ID
                or not isinstance(repair_job, dict) or repair_job.get("status") != "SUCCEEDED"
                or repair_job.get("idempotency_key") != repair_key or repair_job.get("attempt_count") != 1
                or repair_job.get("max_attempts") != 1 or repair_job.get("queue_id") != QUEUE_ID):
            raise FlashRunError("REPAIR_CANARY_QUEUE_STATE_INVALID")

        expected_part = parts[part_index - 1]
        base_payload = _queue_payload(queue_root, base_job)
        current_part_payload = payloads[part_index - 1]
        if (base_payload.get("article_id") != article.get("article_id")
                or base_payload.get("source_sha256") != article.get("source_sha256")
                or base_payload.get("body_sha256") != article.get("body_sha256")
                or base_payload.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")
                or base_payload.get("chunk_plan_sha256") != plan.get("plan_sha256")
                or base_payload.get("part_descriptor") != expected_part
                or not _internal_payload_matches(base_payload, current_part_payload)):
            raise FlashRunError("REPAIR_CANARY_FAILED_SOURCE_BINDING_MISMATCH")
        # The failed base payload is immutable and may carry older capture-row
        # provenance. Its source/body/plan and messages were just compared with
        # the freshly rebuilt current part above; reconstruct the repair from
        # that current, authority-validated part input while retaining the base
        # key/payload/raw SHA in the validator-feedback binding.
        repair = _part_repair_payload(current_part_payload, base_job, queue_root, recovery_lock,
                                       membership_gate, resume_cutoff, hard_prompt_token_cap)
        if repair is None:
            raise FlashRunError("REPAIR_CANARY_REPAIR_VERSION_INVALID")
        expected_repair_payload, binding = repair
        exact_tokens = count_prompt_tokens(expected_repair_payload["messages"])
        if type(exact_tokens) is not int or exact_tokens > hard_prompt_token_cap:
            raise FlashRunError("REPAIR_CANARY_TOKEN_PREFLIGHT_INVALID")
        expected_repair_payload["prompt_tokens_exact"] = exact_tokens
        stored_repair_payload = _queue_payload(queue_root, repair_job)
        if (_stable_queue_identity(queue, expected_repair_payload) != repair_key
                or repair_job.get("identity") != queue._identity(expected_repair_payload)
                or not _part_repair_payload_matches_capture_provenance_drift(
                    stored_repair_payload, expected_repair_payload,
                    recovery_lock=recovery_lock, membership_gate=membership_gate,
                    resume_cutoff=resume_cutoff, state_root=state_root)
                or part_record.get("repair_binding_sha256") != binding.get("binding_sha256")):
            raise FlashRunError("REPAIR_CANARY_REPAIR_BINDING_MISMATCH")

        result, _result_sha, raw_sha = _read_internal_validated_result(queue_root, repair_job)
        raw_response = _read_json_file(queue_root / repair_job.get("raw_path"), raw_sha,
                                       "REPAIR_CANARY_RAW_RESPONSE_INVALID")
        validate_schema = lambda output: runner._validate_json_schema(
            output, runner.build_simple_reader_wire_schema(
                contract, request_material["citation_protocol"]))
        revalidated = chunks.validate_part_envelope(
            raw_response, article_id=article["article_id"], source_sha256=article["source_sha256"],
            body_sha256=article["body_sha256"], plan_sha256=plan["plan_sha256"],
            part=expected_part, unit_map=unit_map, body=article["article_body"],
            validate_schema=validate_schema,
        )
        if (revalidated != result or result.get("schema") != chunks.PART_RESULT_SCHEMA
                or result.get("article_id") != article["article_id"]
                or result.get("source_sha256") != article["source_sha256"]
                or result.get("body_sha256") != article["body_sha256"]
                or result.get("plan_sha256") != plan["plan_sha256"]
                or result.get("part_index") != part_index
                or result.get("part_count") != len(parts)
                or result.get("part_sha256") != expected_part.get("part_sha256")
                or result.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")):
            raise FlashRunError("REPAIR_CANARY_VALIDATED_RESULT_BINDING_MISMATCH")
        return True, None
    except (FlashRunError, OSError, KeyError, TypeError, ValueError) as exc:
        code = getattr(exc, "code", None)
        if not isinstance(code, str) and isinstance(exc, ValueError) and SAFE_CODE_RE.fullmatch(str(exc)):
            code = str(exc)
        return False, code if isinstance(code, str) and SAFE_CODE_RE.fullmatch(code) else "REPAIR_CANARY_VALIDATION_FAILED"


def _set_part_repair_status(spec: dict[str, Any], internal_record: dict[str, Any],
                            status: str, failure_code: str | None = None) -> None:
    internal_record["repair_status"] = status
    if failure_code is not None:
        internal_record["canary_failure_code"] = failure_code
    records = spec.get("part_records")
    if isinstance(records, list):
        for record in records:
            if (isinstance(record, dict) and record.get("base_key") == internal_record.get("base_key")
                    and record.get("selected_key") == internal_record.get("key", record.get("selected_key"))):
                record["repair_status"] = status
                if failure_code is not None:
                    record["canary_failure_code"] = failure_code
                break


def _continue_long_body_repairs_after_canary(long_body_specs: dict[str, dict[str, Any]],
                                              phase_a_records: list[dict[str, Any]], queue: Any,
                                              queue_root: Path, *,
                                              allow_same_batch_pending: bool,
                                              recovery_lock: Any, membership_gate: Any,
                                              resume_cutoff: str | None,
                                              prompt_token_cap: int,
                                              hard_prompt_token_cap: int,
                                              state_root: Path | None = None,
                                              count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
                                              runner: Any, contract: Any,
                                              request_material: dict[str, Any],
                                              run_queue_keys: Callable[[set[str]], None],
                                              system_stopped: Callable[[], bool]
                                              ) -> tuple[set[str], list[dict[str, Any]], dict[str, Any]]:
    """Continue all remaining one-time repairs only after phase-A repair proof passes."""
    candidate_statuses = {"REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED", "REPAIRED_SUCCESS_REUSED"}
    candidates = [record for record in phase_a_records
                  if record.get("kind") == "part" and record.get("repair_status") in candidate_statuses]
    if not candidates:
        return set(), [], {"status": "NO_REPAIR_CANARY"}

    active = [record for record in candidates
              if record.get("repair_status") in {"REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED"}]
    if len(active) > 1:
        for record in active:
            spec = long_body_specs.get(record.get("article_id"), {})
            _set_part_repair_status(spec, record, "REPAIR_CANARY_INVALID_STOP",
                                    "REPAIR_CANARY_MULTIPLE_ACTIVE")
        return set(), [], {"status": "STOPPED_INVALID_CANARY_COUNT", "candidate_count": len(active)}
    if system_stopped():
        for record in candidates:
            spec = long_body_specs.get(record.get("article_id"), {})
            _set_part_repair_status(spec, record, "REPAIR_CANARY_SYSTEM_STOP")
        return set(), [], {"status": "STOPPED_SYSTEM_FAILURE", "candidate_count": len(candidates)}

    verified_keys: set[str] = set()
    for record in candidates:
        spec = long_body_specs.get(record.get("article_id"))
        if not isinstance(spec, dict):
            ok, failure_code = False, "REPAIR_CANARY_SPEC_MISSING"
        else:
            ok, failure_code = _verify_completed_part_repair_canary(
                spec, record, queue, queue_root,
                recovery_lock=recovery_lock, membership_gate=membership_gate,
                resume_cutoff=resume_cutoff, hard_prompt_token_cap=hard_prompt_token_cap,
                count_prompt_tokens=count_prompt_tokens, runner=runner, contract=contract,
                state_root=state_root, request_material=request_material,
            )
        if not ok:
            job = queue._load_state().get("jobs", {}).get(record.get("key"), {})
            state = job.get("status") if isinstance(job, dict) else None
            status = ("REPAIR_CANARY_FAILED_STOP" if state == "FAILED" else
                      "REPAIR_CANARY_PENDING_STOP" if state == "PENDING" else
                      "REPAIR_CANARY_INVALID_STOP")
            _set_part_repair_status(spec or {}, record, status, failure_code)
            return set(), [], {"status": status, "failure_code": failure_code,
                               "article_id": record.get("article_id"),
                               "part_index": record.get("part_index")}
        verified_keys.add(record.get("key"))
        _set_part_repair_status(spec, record, "REPAIR_CANARY_VERIFIED")

    if system_stopped():
        for record in candidates:
            spec = long_body_specs.get(record.get("article_id"), {})
            _set_part_repair_status(spec, record, "REPAIR_CANARY_SYSTEM_STOP")
        return set(), [], {"status": "STOPPED_SYSTEM_FAILURE", "verified_canary_count": len(verified_keys)}

    phase_b_allowed, phase_b_records = _enqueue_long_body_parts(
        long_body_specs, queue, queue_root,
        allow_same_batch_pending=allow_same_batch_pending,
        recovery_lock=recovery_lock, membership_gate=membership_gate,
        resume_cutoff=resume_cutoff, prompt_token_cap=prompt_token_cap,
        hard_prompt_token_cap=hard_prompt_token_cap,
        state_root=state_root,
        allow_multiple_new_repairs=True, count_prompt_tokens=count_prompt_tokens,
    )
    if not phase_b_records:
        return phase_b_allowed, phase_b_records, {
            "status": "CANARY_VERIFIED_NO_REMAINING_PARTS", "verified_canary_count": len(verified_keys)}
    run_queue_keys(phase_b_allowed)
    jobs = queue._load_state().get("jobs", {})
    for record in phase_b_records:
        spec = long_body_specs.get(record.get("article_id"), {})
        if record.get("key") in verified_keys:
            status = "REPAIR_CANARY_VERIFIED"
            failure_code = None
        elif record.get("repair_status") in {
                "REPAIR_AUTO_CONTINUATION_ENQUEUED", "REPAIR_AUTO_CONTINUATION_PENDING_ALLOWED",
                "REPAIR_PENDING_ALLOWED",
        }:
            job = jobs.get(record.get("key"), {})
            job_status = job.get("status") if isinstance(job, dict) else None
            status = ("REPAIR_AUTO_CONTINUATION_SUCCEEDED" if job_status == "SUCCEEDED" else
                      "REPAIR_AUTO_CONTINUATION_FAILED" if job_status == "FAILED" else
                      "REPAIR_AUTO_CONTINUATION_PENDING")
            failure_code = None
        else:
            status = record.get("repair_status")
            failure_code = None
        _set_part_repair_status(spec, record, status, failure_code)
    return phase_b_allowed, phase_b_records, {
        "status": "AUTO_CONTINUATION_DISPATCHED" if not system_stopped() else "AUTO_CONTINUATION_STOPPED",
        "verified_canary_count": len(verified_keys),
        "phase_b_repair_count": sum(record.get("created") is True for record in phase_b_records),
        "phase_b_runnable_count": len(phase_b_allowed),
    }


def _reader_data_from_messages(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    if (not isinstance(messages, list) or len(messages) != 2
            or not isinstance(messages[1], dict) or not isinstance(messages[1].get("content"), str)):
        raise FlashRunError("CHUNK_BASE_MESSAGES_INVALID")
    content = messages[1]["content"]
    begin, end = "ARTICLE_DATA_BEGIN\n", "\nARTICLE_DATA_END"
    if not content.startswith(begin) or not content.endswith(end):
        raise FlashRunError("CHUNK_BASE_ENVELOPE_INVALID")
    try:
        value = json.loads(content[len(begin):-len(end)])
    except json.JSONDecodeError:
        raise FlashRunError("CHUNK_BASE_ENVELOPE_INVALID") from None
    if not isinstance(value, dict) or not isinstance(value.get("article"), dict):
        raise FlashRunError("CHUNK_BASE_ARTICLE_INVALID")
    return value, content


def _part_messages(base_messages: list[dict[str, Any]], *, system_prompt: str, article_id: str,
                   part: dict[str, Any], units: list[dict[str, Any]],
                   part_ledger: dict[str, Any], runner: Any, input_schema: str) -> list[dict[str, str]]:
    """Replace only the single article's units/ledger in the existing Reader envelope."""
    value, _content = _reader_data_from_messages(base_messages)
    article = value["article"]
    expected_ids = part.get("source_unit_ids")
    if (not isinstance(expected_ids, list) or [item.get("source_unit_id") for item in units] != expected_ids
            or article.get("article_id") != article_id):
        raise FlashRunError("CHUNK_PART_SOURCE_BINDING_INVALID")
    article["source_units"] = [
        {"source_unit_id": f"{article_id}::{unit['source_unit_id']}", "text": unit["text"]}
        for unit in units
    ]
    article["fixed_fact_ledger"] = runner._simple_model_fixed_fact_ledger_for_article(part_ledger, article_id)
    value["schema"] = input_schema
    value["reader_input_schema"] = runner.SIMPLE_WORKFLOW_RANGE_INPUT_SCHEMA
    value["chunk_part"] = {
        "part_index": part["part_index"], "part_count": part["part_count"],
        "start_source_unit_id": f"{article_id}::{part['start_source_unit_id']}",
        "end_source_unit_id": f"{article_id}::{part['end_source_unit_id']}",
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "ARTICLE_DATA_BEGIN\n" + json.dumps(
            value, ensure_ascii=False, separators=(",", ":")) + "\nARTICLE_DATA_END"},
    ]


def _synthesis_messages(*, system_prompt: str, article_id: str, article_metadata: dict[str, Any],
                        synthesis_input: dict[str, Any], input_schema: str) -> list[dict[str, str]]:
    if synthesis_input.get("schema") != input_schema or synthesis_input.get("article_id") != article_id:
        raise FlashRunError("SYNTHESIS_INPUT_ENVELOPE_INVALID")
    value = {
        "schema": input_schema,
        "article_id": article_id,
        "article_metadata": article_metadata,
        "synthesis_input": synthesis_input,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "ARTICLE_SYNTHESIS_BEGIN\n" + json.dumps(
            value, ensure_ascii=False, separators=(",", ":")) + "\nARTICLE_SYNTHESIS_END"},
    ]


def _require_frozen_resume_membership(membership_gate: Any, *, resume_frozen_batch: bool) -> None:
    """Stop frozen resume on the original membership failure before queue planning."""
    if not resume_frozen_batch:
        return
    if isinstance(membership_gate, dict) and membership_gate.get("status") == "VERIFIED":
        return
    failure_code = membership_gate.get("failure_code") if isinstance(membership_gate, dict) else None
    code = (failure_code if isinstance(failure_code, str) and SAFE_CODE_RE.fullmatch(failure_code)
            else "FROZEN_RESUME_MEMBERSHIP_GATE_UNVERIFIED")
    raise FlashRunError(code)


def _run(input_value: dict[str, Any], *, state_root: Path, capture_root: Path,
         job_id: str, progress: Callable[[dict[str, Any]], None],
         shared_root: Path | None = None,
         resume_same_batch_pending: bool = False,
         resume_frozen_batch: bool = False,
         max_model_calls: int | None = None,
         resume_source_job_id: str | None = None,
         resume_source_input_sha256: str | None = None,
         materialize_only: bool = False,
         materialization_failure: dict[str, Any] | None = None) -> dict[str, Any]:
    # _load_helper initializes PIPELINE_ROOT on sys.path. Do that before these
    # imports: the Flash queue and runtime modules live in that existing tree.
    helper = _load_helper()
    import announcement_queue as queue_module
    import automatic_canary_server as canary
    import batch_runner as runner
    import build_length_canary as length_canary
    from transformers import AutoTokenizer

    capture_ref = input_value.get("capture_product")
    if (not isinstance(capture_ref, dict)
            or not isinstance(capture_ref.get("artifact_ref"), str)
            or not re.fullmatch(r"products/[0-9a-f]{64}\.json", capture_ref["artifact_ref"])
            or not isinstance(capture_ref.get("sha256"), str)
            or not SHA_RE.fullmatch(capture_ref["sha256"])):
        raise FlashRunError("CAPTURE_PRODUCT_REFERENCE_INVALID")
    capture_io = SafeRoot(capture_root)
    capture_raw = capture_io.read_bytes(capture_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
    if sha(capture_raw) != capture_ref["sha256"]:
        raise FlashRunError("CAPTURE_PRODUCT_SHA_MISMATCH")
    capture_product = _json(capture_raw, "CAPTURE_PRODUCT_JSON_INVALID")
    if (capture_product.get("schema_version") != "mwb.capture.window.v1"
            or capture_product.get("owner") != "v4.manager_workbench.capture_announcements"
            or capture_product.get("source") != "EASTMONEY_HK"
            or capture_product.get("saved_ref") is not None):
        # The saved bytes are the exact immutable pre-saved product. saved_ref is
        # carried only in the separate internal input record.
        raise FlashRunError("CAPTURE_PRODUCT_IDENTITY_INVALID")

    from v4.manager_workbench.announcement_membership import (
        classify_capture_row, filter_payloads, public_gate, revalidate_membership_gate,
    )
    membership_input = input_value.get("membership_gate")
    if shared_root is not None:
        gate_cutoff = input_value.get("cutoff")
        membership_gate = revalidate_membership_gate(
            SimpleNamespace(shared_root=shared_root, source_bindings={}), membership_input,
            input_value["target_date"], gate_cutoff if isinstance(gate_cutoff, str) else "",
        )
    else:
        membership_gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
                           "status": "CANNOT_CONFIRM", "target_date": input_value["target_date"],
                           "market": "HK_CONNECT", "failure_code": "MEMBERSHIP_SHARED_ROOT_UNAVAILABLE",
                           "codes": []}
    _require_frozen_resume_membership(membership_gate, resume_frozen_batch=resume_frozen_batch)

    recovery_lock = input_value.get("recovery_lock")
    if (type(max_model_calls) is not int or max_model_calls < 1) and max_model_calls is not None:
        raise FlashRunError("RESUME_MAX_ITEMS_INVALID")
    if max_model_calls is not None and (not resume_frozen_batch or max_model_calls != 1):
        raise FlashRunError("RESUME_MAX_ITEMS_INVALID")
    if resume_same_batch_pending and resume_frozen_batch:
        raise FlashRunError("RESUME_MODE_AMBIGUOUS")
    if resume_same_batch_pending:
        _validate_recovery_lock(input_value, capture_ref, capture_product, membership_gate)
    elif resume_frozen_batch:
        if isinstance(recovery_lock, dict):
            raise FlashRunError("FROZEN_RESUME_RECOVERY_LOCK_UNSUPPORTED")
        if (not isinstance(resume_source_job_id, str) or not JOB_ID_RE.fullmatch(resume_source_job_id)
                or not isinstance(resume_source_input_sha256, str)
                or not SHA_RE.fullmatch(resume_source_input_sha256)):
            raise FlashRunError("FROZEN_RESUME_SOURCE_BINDING_INVALID")
    elif isinstance(recovery_lock, dict):
        raise FlashRunError("RECOVERY_CONTINUATION_FLAG_REQUIRED")

    contract = runner.load_active_contract()
    request_material = helper._full_day_request_material(contract)
    configuration_material = request_material.get("configuration_material", {})
    if (request_material.get("workflow_profile") != runner.SIMPLE_WORKFLOW_RANGE_PROFILE
            or request_material.get("citation_protocol") != runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
            or request_material.get("sampling_policy", {}).get("request_temperature") != 0.0
            or configuration_material.get("model_id") != runner.MODEL_ID
            or configuration_material.get("request_temperature") != 0.0
            or configuration_material.get("enable_thinking") is not False):
        raise FlashRunError("FLASH_REQUEST_PROFILE_INVALID")
    tokenizer = AutoTokenizer.from_pretrained(
        str(runner.OMLX_TOKENIZER_PATH), local_files_only=True, trust_remote_code=False, use_fast=True)
    from v4.manager_workbench import announcement_chunks as chunks

    context_limit = request_material["runtime_limits"]["context_limit_tokens"]
    completion_reserve = request_material.get("max_completion_tokens",
                                             configuration_material.get("max_completion_tokens"))
    if type(context_limit) is not int or type(completion_reserve) is not int or completion_reserve < 0:
        raise FlashRunError("FLASH_RUNTIME_TOKEN_BUDGET_INVALID")
    hard_prompt_token_cap = min(chunks.SYNTHESIS_TOKEN_CAP,
                                context_limit - completion_reserve - chunks.TOKEN_SAFETY_MARGIN)
    prompt_token_cap = min(chunks.PART_TARGET_TOKEN_CAP, hard_prompt_token_cap)
    synthesis_prompt_token_cap = hard_prompt_token_cap
    part_system_prompt = (chunks.reader_task_system_prompt(request_material["prompt"], "part")
                          + "\n\n" + chunks.PART_ADDENDUM)
    synthesis_system_prompt = (chunks.reader_task_system_prompt(request_material["prompt"], "synthesis")
                               + "\n\n" + chunks.SYNTHESIS_ADDENDUM)
    part_prompt_sha256 = sha(part_system_prompt.encode("utf-8"))
    synthesis_prompt_sha256 = sha(synthesis_system_prompt.encode("utf-8"))
    queue_root = state_root / "announcement_flash" / "queue"
    queue = queue_module.SerialAnnouncementQueue(queue_root, QUEUE_ID, runner.MODEL_ID,
                                                 max_attempts=1, max_body_bytes=None)
    count_prompt_tokens = lambda messages: helper._token_count(tokenizer, messages)
    validator = _validator(queue_module, runner, contract, request_material, length_canary)

    body_gaps: list[dict[str, Any]] = []
    excluded = 0
    payloads: list[dict[str, Any]] = []
    preflight_pending: list[dict[str, Any]] = []
    long_body_specs: dict[str, dict[str, Any]] = {}
    membership_exclusions: list[dict[str, Any]] = []
    membership_article_counts: Counter[str] = Counter()
    membership_stock_symbols: dict[str, str] = {}
    for index, row in enumerate(capture_product.get("rows", [])):
        if not isinstance(row, dict):
            body_gaps.append({"article_id": None, "failure_code": "CAPTURE_ROW_INVALID"})
            continue
        article_id = "EASTMONEY:" + str(row.get("art_code") or "")
        if row.get("window_consumption_status") == "EXCLUDED_OUTSIDE_WINDOW":
            excluded += 1
            continue
        member_record = classify_capture_row(row, membership_gate)
        status = member_record["membership_status"]
        membership_article_counts[status.lower()] += 1
        symbol_key = member_record.get("symbol") or member_record["article_id"]
        if status == "UNKNOWN" and symbol_key == "CANNOT_CONFIRM":
            symbol_key = member_record["article_id"]
        prior_status = membership_stock_symbols.get(symbol_key)
        membership_stock_symbols[symbol_key] = "UNKNOWN" if prior_status and prior_status != status else status
        if status != "IN":
            membership_exclusions.append(member_record)
            continue
        if (row.get("body_complete") is not True or not isinstance(row.get("body_text"), str)
                or not row.get("body_text")):
            codes = [item for item in row.get("gaps", []) if isinstance(item, str)]
            body_gaps.append({"article_id": article_id, "symbol": None,
                              "title": row.get("title"), "failure_code": codes[0] if codes else "BODY_INCOMPLETE"})
            continue
        try:
            article = _article(row, index, capture_product, capture_ref, capture_io, runner, membership_gate)
            unit_map = article.pop("_source_unit_map")
            batch = length_canary.make_batch([article], "V4_FLASH_" + sha(article["article_id"].encode())[:16])
            messages = helper._messages_for_article(article, contract, request_material["prompt"], PROFILE)
            prompt_tokens = helper._token_count(tokenizer, messages)
            if hard_prompt_token_cap < 1 or prompt_token_cap < 1:
                preflight_pending.append({"article_id": article_id, "symbol": article["article_metadata"]["symbol"],
                                          "title": article["article_metadata"]["title"],
                                          "queue_reason": "INPUT_EXCEEDS_CONTEXT",
                                          "prompt_tokens": prompt_tokens, "context_limit_tokens": context_limit,
                                          "hard_prompt_token_cap": hard_prompt_token_cap,
                                          "part_target_token_cap": prompt_token_cap,
                                          "completion_reserve_tokens": completion_reserve,
                                          "safety_margin_tokens": chunks.TOKEN_SAFETY_MARGIN})
                continue
            ledger = article["fixed_fact_ledger"]
            rules = (f"recent_day_reader_v2+profile:{PROFILE}+citation:{request_material['citation_protocol']}"
                     f"+unit-map:{unit_map['source_unit_map_sha256']}+fixed-ledger:{ledger['ledger_sha256']}"
                     f"+schema:{request_material['schema_sha256']}+temperature:0.0+thinking:off")
            payload = {
                **{key: article[key] for key in ("article_id", "source_sha256", "body_sha256", "article_body",
                                                 "article_metadata", "fixed_fact_ledger")},
                "date": article["article_metadata"]["publication_date"], "market": "HK",
                "prompt_sha256": request_material["prompt_sha256"], "model_id": runner.MODEL_ID,
                "configuration_sha256": request_material["configuration_sha256"], "rules": rules,
                "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental",
                "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                "validated_article_batch": batch, "messages": messages,
                "structured_output_schema": request_material["schema"],
                "workflow_profile": PROFILE, "citation_protocol": request_material["citation_protocol"],
                "prompt_tokens_exact": prompt_tokens, "context_limit_tokens": context_limit,
            }
            existing_standard_job = (_has_existing_semantic_queue_job(queue, payload)
                                     if prompt_tokens > prompt_token_cap else False)
            if _needs_chunk_plan(prompt_tokens, part_target_tokens=prompt_token_cap,
                                 hard_cap_tokens=hard_prompt_token_cap,
                                 existing_standard_job=existing_standard_job):
                article_id = article["article_id"]
                member_sha = article["article_metadata"].get("membership_authority_sha256")
                lock = input_value.get("recovery_lock")
                batch_binding = {
                    "root_batch_job_id": lock.get("root_batch_job_id") if isinstance(lock, dict) else None,
                    "recovery_row_manifest_sha256": lock.get("row_manifest_sha256") if isinstance(lock, dict) else None,
                    "target_date": input_value.get("target_date"),
                    "cutoff": input_value.get("cutoff"),
                    "membership_authority_sha256": member_sha,
                    "article_id": article_id,
                    "source_sha256": article["source_sha256"],
                    "body_sha256": article["body_sha256"],
                    "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                    "prompt_sha256": request_material["prompt_sha256"],
                    "configuration_sha256": request_material["configuration_sha256"],
                }
                batch_binding_sha256 = sha(canonical(batch_binding))
                def part_ledger_for(units_for_part: list[dict[str, Any]]) -> dict[str, Any]:
                    return chunks.project_part_ledger(
                        ledger, [unit["source_unit_id"] for unit in units_for_part],
                        lambda value: runner._simple_model_fixed_fact_ledger_for_article(value, article_id))

                def render_part(units_for_part: list[dict[str, Any]], part_index: int,
                                part_count: int) -> int:
                    if not units_for_part:
                        raise FlashRunError("CHUNK_EMPTY_PART")
                    descriptor = {
                        "part_index": part_index, "part_count": part_count,
                        "start_source_unit_id": units_for_part[0]["source_unit_id"],
                        "end_source_unit_id": units_for_part[-1]["source_unit_id"],
                        "source_unit_ids": [unit["source_unit_id"] for unit in units_for_part],
                    }
                    part_messages = _part_messages(
                        messages, system_prompt=part_system_prompt, article_id=article_id,
                        part=descriptor, units=units_for_part,
                        part_ledger=part_ledger_for(units_for_part), runner=runner,
                        input_schema=chunks.PART_INPUT_SCHEMA)
                    return helper._token_count(tokenizer, part_messages)

                def unit_tokens(text: str) -> int:
                    encoded = tokenizer.encode(text, add_special_tokens=False)
                    return len(encoded)

                plan = chunks.plan_parts(
                    article_id=article_id, source_sha256=article["source_sha256"],
                    body=article["article_body"], body_sha256=article["body_sha256"],
                    unit_map=unit_map, fixed_fact_ledger=ledger,
                    prompt_sha256=part_prompt_sha256, synthesis_prompt_sha256=synthesis_prompt_sha256,
                    configuration_sha256=request_material["configuration_sha256"],
                    batch_binding_sha256=batch_binding_sha256, token_cap=prompt_token_cap,
                    render_tokens=render_part, token_counter=unit_tokens,
                    model_ledger=lambda value: runner._simple_model_fixed_fact_ledger_for_article(value, article_id))
                chunks.verify_part_coverage(article["article_body"], article["body_sha256"], unit_map, plan)
                plan_root = state_root / "announcement_flash" / "jobs" / job_id
                plan_ref = f"long-body/{article_id.replace(':', '_')}-{plan['plan_sha256']}.json"
                if not materialize_only:
                    plan_root.mkdir(parents=True, exist_ok=True)
                    _write_json(SafeRoot(plan_root), plan_ref, plan)
                units = unit_map["units"]
                part_payloads = []
                for part in plan["parts"]:
                    part_units = units[part["unit_start_index"]:part["unit_end_index"]]
                    part_ledger = part_ledger_for(part_units)
                    part_messages = _part_messages(
                        messages, system_prompt=part_system_prompt, article_id=article_id,
                        part=part, units=part_units, part_ledger=part_ledger,
                        runner=runner, input_schema=chunks.PART_INPUT_SCHEMA)
                    exact_tokens = helper._token_count(tokenizer, part_messages)
                    if exact_tokens > prompt_token_cap or exact_tokens != part["prompt_tokens_exact"]:
                        raise FlashRunError("CHUNK_PART_TOKEN_PREFLIGHT_MISMATCH")
                    part_rules = (f"{rules}+long-body-part:v1+plan:{plan['plan_sha256']}"
                                  f"+part:{part['part_index']}/{part['part_count']}"
                                  f"+part-sha:{part['part_sha256']}+part-prompt:{part_prompt_sha256}"
                                  f"+part-addendum:{chunks.PART_ADDENDUM_SHA256}")
                    part_payloads.append({
                        **{key: article[key] for key in ("article_id", "source_sha256", "body_sha256",
                                                         "article_body", "article_metadata", "fixed_fact_ledger")},
                        "date": article["article_metadata"]["publication_date"], "market": "HK",
                        "prompt_sha256": part_prompt_sha256, "model_id": runner.MODEL_ID,
                        "configuration_sha256": request_material["configuration_sha256"],
                        "rules": part_rules, "role": "announcement_reader_part",
                        "stage": "v4_manager_announcement_flash_long_body_part_v1",
                        "queue_task_kind": "announcement_reader_part",
                        "chunk_plan_sha256": plan["plan_sha256"], "part_descriptor": part,
                        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                        "validated_article_batch": batch, "messages": part_messages,
                        "structured_output_schema": request_material["schema"],
                        "workflow_profile": PROFILE,
                        "citation_protocol": request_material["citation_protocol"],
                        "input_schema": chunks.PART_INPUT_SCHEMA,
                        "prompt_tokens_exact": exact_tokens, "prompt_token_cap": prompt_token_cap,
                        "context_limit_tokens": context_limit,
                        "completion_reserve_tokens": completion_reserve,
                        "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN,
                        "batch_binding_sha256": batch_binding_sha256,
                    })
                long_body_specs[article_id] = {
                    "article": {key: article[key] for key in ("article_id", "source_sha256", "body_sha256",
                                                                 "article_body", "article_metadata", "fixed_fact_ledger")},
                    "batch": batch, "unit_map": unit_map, "plan": plan, "plan_ref": plan_ref,
                    "part_payloads": part_payloads, "part_keys": [],
                    "batch_binding": batch_binding, "status": "PARTS_PENDING",
                }
                continue
            payloads.append(payload)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raw_code = getattr(exc, "code", None) or str(exc)
            code = raw_code if isinstance(raw_code, str) and SAFE_CODE_RE.fullmatch(raw_code) else "SOURCE_PREPARATION_FAILED"
            body_gaps.append({"article_id": article_id, "symbol": row.get("source_issuer_codes", [{}])[0].get("code")
                              if row.get("source_issuer_codes") else None,
                              "title": row.get("title"), "failure_code": code})

    admitted_payloads, admission_exclusions = filter_payloads(payloads, membership_gate)
    if admission_exclusions:
        membership_exclusions.extend(admission_exclusions)
        for record in admission_exclusions:
            membership_article_counts[str(record.get("membership_status", "UNKNOWN")).lower()] += 1
    if isinstance(recovery_lock, dict):
        expected_ids = set(recovery_lock.get("eligible_article_ids", []))
        represented_ids = {str(payload.get("article_id")) for payload in payloads}
        represented_ids.update(long_body_specs)
        represented_ids.update(str(item.get("article_id")) for item in preflight_pending if isinstance(item, dict))
        represented_ids.update(str(item.get("article_id")) for item in body_gaps if isinstance(item, dict))
        if represented_ids != expected_ids:
            raise FlashRunError("RECOVERY_ELIGIBLE_ARTICLE_COVERAGE_MISMATCH")
        if any(isinstance(item, dict) and item.get("article_id") in expected_ids for item in body_gaps):
            raise FlashRunError("RECOVERY_ELIGIBLE_SOURCE_PREPARATION_INCOMPLETE")
    recovered_orphan_keys: set[str] = set()
    blocked_orphan_keys: set[str] = set()
    orphan_candidates: dict[str, str] = {}
    frozen_original_counts: Counter[str] = Counter()
    frozen_part_keys: list[str] = []
    if resume_frozen_batch:
        pre_resume_jobs = queue._load_state().get("jobs", {})
        if not isinstance(pre_resume_jobs, dict):
            raise FlashRunError("FROZEN_RESUME_QUEUE_STATE_INVALID")
        for spec in long_body_specs.values():
            for payload in spec.get("part_payloads", []):
                key = _stable_queue_identity(queue, payload)
                frozen_part_keys.append(key)
                saved = pre_resume_jobs.get(key)
                frozen_original_counts[str(saved.get("status", "MISSING") if isinstance(saved, dict) else "MISSING")] += 1
        recovered_orphan_keys, blocked_orphan_keys, orphan_candidates = _frozen_resume_orphans(
            long_body_specs, queue, queue_root,
            target_date=str(input_value.get("target_date", "")), dry_run=materialize_only,
        )
    pinned_history = _pinned_candidate_history()
    admission = _admit_incremental_payloads(
        admitted_payloads, queue, pinned_history, queue_root,
        resume_same_batch_pending=resume_same_batch_pending,
        resume_cutoff=input_value.get("cutoff") if resume_same_batch_pending else None,
        recovery_lock=recovery_lock if resume_same_batch_pending else None,
        membership_gate=membership_gate if resume_same_batch_pending else None,
        allow_enqueue=not materialize_only and not resume_frozen_batch,
        state_root=state_root, capture_product=capture_product, capture_ref=capture_ref,
        validator=validator,
    )
    allowed_keys: set[str] = set(admission["allowed_keys"])
    articles_by_key: dict[str, dict[str, Any]] = admission["articles_by_key"]
    matched_history: list[dict[str, Any]] = admission["matched"]
    body_gaps.extend(admission["conflicts"])
    internal_records: list[dict[str, Any]] = []
    part_allowed, part_records = _enqueue_long_body_parts(
        long_body_specs, queue, queue_root,
        allow_same_batch_pending=resume_same_batch_pending or resume_frozen_batch,
        recovery_lock=recovery_lock if resume_same_batch_pending else None,
        membership_gate=membership_gate if resume_same_batch_pending else None,
        resume_cutoff=input_value.get("cutoff") if resume_same_batch_pending else None,
        prompt_token_cap=prompt_token_cap,
        hard_prompt_token_cap=hard_prompt_token_cap,
        state_root=state_root,
        allow_new_repairs=not materialize_only and not resume_frozen_batch,
        allow_enqueue=not materialize_only,
        resume_frozen_batch=resume_frozen_batch,
        recovered_orphan_keys=recovered_orphan_keys,
        blocked_orphan_keys=blocked_orphan_keys,
        orphan_candidates=orphan_candidates,
        source_job_id=resume_source_job_id,
        source_input_sha256=resume_source_input_sha256,
        count_prompt_tokens=count_prompt_tokens,
    )
    allowed_keys.update(part_allowed)
    internal_records.extend(part_records)

    tracked_keys: set[str] = set(allowed_keys) | set(articles_by_key)
    tracked_keys.update(record["key"] for record in internal_records)

    if resume_frozen_batch and max_model_calls == 1:
        selected = _frozen_resume_canary(internal_records)
        # The first frozen-resume request is one saved ordinary PENDING part
        # when possible. It leaves the interruption candidate and other
        # pending parts for the separate continuation click.
        allowed_keys = {selected["key"]} if selected else set()
    resume_canary_key = next(iter(allowed_keys)) if resume_frozen_batch and max_model_calls == 1 and allowed_keys else None

    def current_counts() -> Counter:
        state = queue._load_state()
        jobs = state.get("jobs", {})
        return Counter(jobs.get(key, {}).get("status", "MISSING") for key in tracked_keys)

    progress({"step": "FLASH_SELECTION", "completed": 0, "total": len(allowed_keys),
              "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
              "pending_context": len(preflight_pending),
              "membership": {"status": membership_gate.get("status"),
                             "articles": dict(membership_article_counts)},
              "updated_at": datetime.now(timezone.utc).isoformat()})

    evidence_root = state_root / "announcement_flash" / "evidence"
    completed = 0
    dispatched_keys: list[str] = []
    system_stop: dict[str, Any] | None = None
    if materialize_only:
        if (not isinstance(materialization_failure, dict)
                or not SAFE_CODE_RE.fullmatch(str(materialization_failure.get("failure_code", "")))):
            raise FlashRunError("SAVED_PARTIAL_FAILURE_BINDING_INVALID")
        system_stop = {"failure_code": materialization_failure["failure_code"],
                       "stage": materialization_failure.get("stage") or "FLASH_SELECTION",
                       "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                       "failed_at": materialization_failure.get("failed_at")}

    def run_queue_keys(keys: set[str]) -> None:
        nonlocal completed, system_stop
        if (materialize_only or not keys or system_stop
                or (max_model_calls is not None and completed >= max_model_calls)):
            return
        api_key = runner.load_local_api_key()
        transport = canary.GatedStreamingTransport(
            api_key, evidence_root,
            expected_runtime_settings_sha256=request_material["runtime_settings_sha256"],
            expected_model_settings_sha256=request_material["model_settings_sha256"],
        )

        last_progress_at = [0.0]
        def on_progress(job: Any, event: dict[str, Any]) -> None:
            current = time.monotonic()
            if current - last_progress_at[0] < 2.0:
                return
            last_progress_at[0] = current
            progress({"step": "FLASH_SELECTION", "completed": completed, "total": len(tracked_keys),
                      "current_article_id": job.payload.get("article_id"),
                      "current_title": job.payload.get("article_metadata", {}).get("title"),
                      "last_event_type": event.get("type") if isinstance(event.get("type"), str) else "MODEL_EVENT",
                      "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                      "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})

        executor = _transport_executor(queue_module, transport, runner, request_material, evidence_root, on_progress)
        try:
            while keys and not system_stop:
                if max_model_calls is not None and completed >= max_model_calls:
                    break
                result = queue.run_next(executor, validator, idempotency_keys=keys,
                                        wait_for_model_slot=False)
                if result is None:
                    break
                completed += 1
                if isinstance(result.get("idempotency_key"), str):
                    dispatched_keys.append(result["idempotency_key"])
                latest = queue._load_state().get("jobs", {}).get(result.get("idempotency_key"), {})
                attempt = (latest.get("attempts") or [{}])[-1]
                error = attempt.get("error") if isinstance(attempt, dict) else None
                stage = error.get("stage") if isinstance(error, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                raw_length = attempt.get("raw_length_bytes") if isinstance(attempt, dict) else None
                if result.get("status") == "FAILED" and (stage == "executor" or raw_length == 0):
                    system_stop = {"failure_code": code if isinstance(code, str) else "FLASH_SYSTEM_FAILURE",
                                   "stage": stage or "empty_response", "attempt": latest.get("attempt_count"),
                                   "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"}
                    break
                progress({"step": "FLASH_SELECTION", "completed": completed, "total": len(tracked_keys),
                          "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                          "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})
        finally:
            transport.close()

    run_queue_keys(set(allowed_keys))

    repair_continuation: dict[str, Any] = {"status": "NO_REPAIR_CANARY"}
    phase_b_allowed: set[str] = set()
    phase_b_records: list[dict[str, Any]] = []
    if any(record.get("repair_status") in {
            "REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED", "REPAIRED_SUCCESS_REUSED"
    } for record in part_records):
        if materialize_only:
            repair_continuation = {"status": "SAVED_RESULTS_ONLY_NO_REPAIR_DISPATCH"}
        else:
            phase_b_allowed, phase_b_records, repair_continuation = _continue_long_body_repairs_after_canary(
            long_body_specs, part_records, queue, queue_root,
            allow_same_batch_pending=resume_same_batch_pending,
            recovery_lock=recovery_lock if resume_same_batch_pending else None,
            membership_gate=membership_gate if resume_same_batch_pending else None,
            resume_cutoff=input_value.get("cutoff") if resume_same_batch_pending else None,
            prompt_token_cap=prompt_token_cap,
            hard_prompt_token_cap=hard_prompt_token_cap,
            state_root=state_root,
            count_prompt_tokens=count_prompt_tokens,
            runner=runner, contract=contract, request_material=request_material,
            run_queue_keys=run_queue_keys, system_stopped=lambda: system_stop is not None,
        )
    if phase_b_records:
        phase_a_by_part = {(record.get("article_id"), record.get("part_index"), record.get("base_key")): record
                           for record in part_records if record.get("kind") == "part"}
        for record in phase_b_records:
            previous = phase_a_by_part.get((record.get("article_id"), record.get("part_index"),
                                            record.get("base_key")), {})
            record["created"] = record.get("created") is True or previous.get("created") is True
            record["runnable"] = record.get("runnable") is True or previous.get("runnable") is True
        internal_records = [record for record in internal_records if record.get("kind") != "part"]
        internal_records.extend(phase_b_records)
        tracked_keys.update(record["key"] for record in phase_b_records)
        tracked_keys.update(phase_b_allowed)
        allowed_keys.update(phase_b_allowed)
        progress({"step": "FLASH_SELECTION", "completed": completed, "total": len(tracked_keys),
                  "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                  "pending_context": len(preflight_pending),
                  "long_body_repair_continuation": repair_continuation,
                  "updated_at": datetime.now(timezone.utc).isoformat()})

    # Synthesis is admitted only after every part has a SHA-verified persisted
    # validator result. Part dispositions remain local evidence and never enter
    # candidate projection.
    long_body_pending: list[dict[str, Any]] = []
    long_body_failures: list[dict[str, Any]] = []
    long_body_summaries: list[dict[str, Any]] = []
    long_body_synthesis_context: list[dict[str, Any]] = []
    recovered_synthesis_results: dict[str, dict[str, Any]] = {}
    saved_raw_recoveries: list[dict[str, Any]] = []
    saved_raw_recovery_outcomes: list[dict[str, Any]] = []
    synthesis_allowed: set[str] = set()
    for article_id, spec in long_body_specs.items():
        current_jobs = queue._load_state().get("jobs", {})
        part_jobs = [None if record.get("base_failure_code") else current_jobs.get(key)
                     for key, record in zip(spec["part_keys"], spec["part_records"])]
        if len(part_jobs) != len(spec["plan"]["parts"]):
            raise FlashRunError("LONG_BODY_PART_QUEUE_COVERAGE_INVALID")
        failed_parts = [job for job in part_jobs if isinstance(job, dict) and job.get("status") == "FAILED"]
        missing_parts = [index for index, job in enumerate(part_jobs) if not isinstance(job, dict)]
        pending_parts = [job for job in part_jobs if isinstance(job, dict)
                         and job.get("status") != "SUCCEEDED" and job.get("status") != "FAILED"]
        canary_integrity_blocked = any(record.get("repair_status") in {
            "REPAIR_CANARY_INVALID_STOP", "REPAIR_CANARY_SYSTEM_STOP",
            "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED",
        } for record in spec["part_records"])
        if materialize_only:
            current_jobs = queue._load_state().get("jobs", {})
            for part, part_record in zip(spec["plan"]["parts"], spec["part_records"]):
                base_job = current_jobs.get(part_record.get("base_key"))
                if isinstance(base_job, dict) and base_job.get("status") == "FAILED":
                    base_payload = _queue_payload(queue_root, base_job)
                    attempt = (base_job.get("attempts") or [{}])[-1]
                    error = attempt.get("error") if isinstance(attempt, dict) else None
                    code = error.get("code") if isinstance(error, dict) else None
                    long_body_failures.append({"article_id": article_id,
                                               "part_index": part["part_index"],
                                               "part_count": len(spec["plan"]["parts"]),
                                               "failure_code": code if isinstance(code, str)
                                               and SAFE_CODE_RE.fullmatch(code) else "LONG_BODY_PART_FAILED",
                                               "status": "FAILED"})
        elif failed_parts:
            for job in failed_parts:
                part_payload = _queue_payload(queue_root, job)
                attempt = (job.get("attempts") or [{}])[-1]
                error = attempt.get("error") if isinstance(attempt, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                long_body_failures.append({"article_id": article_id,
                                           "part_index": part_payload["part_descriptor"]["part_index"],
                                           "failure_code": code if isinstance(code, str) and SAFE_CODE_RE.fullmatch(code)
                                           else "LONG_BODY_PART_FAILED",
                                           "status": "FAILED"})
        for index, (part, part_record) in enumerate(zip(spec["plan"]["parts"], spec["part_records"])):
            if part_record.get("base_failure_code"):
                long_body_pending.append({"article_id": article_id, "part_index": part["part_index"],
                                          "part_count": len(spec["plan"]["parts"]),
                                          "queue_status": "CANNOT_CONFIRM",
                                          "queue_reason": "SAVED_PART_QUEUE_IDENTITY_CONFLICT",
                                          "failure_code": part_record["base_failure_code"]})
            if part_record.get("repair_status") in {
                    "GATED_AFTER_ONE_NEW_REPAIR", "REPAIR_CONTEXT_PENDING",
                    "REPAIR_CANARY_FAILED_STOP", "REPAIR_CANARY_PENDING_STOP",
                    "REPAIR_CANARY_INVALID_STOP", "REPAIR_CANARY_SYSTEM_STOP",
                    "REPAIR_SAVED_VERSION_CONFLICT", "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED",
            }:
                long_body_pending.append({"article_id": article_id, "part_index": part["part_index"],
                                          "part_count": len(spec["plan"]["parts"]),
                                          "queue_status": part_record.get("base_status"),
                                          "queue_reason": ("REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM"
                                                           if part_record.get("repair_status") ==
                                                           "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED"
                                                           else "LONG_BODY_PART_REPAIR_GATED"),
                                          "repair_status": part_record["repair_status"],
                                          "canary_failure_code": part_record.get("canary_failure_code"),
                                          "failure_code": part_record.get("repair_failure_code"),
                                          "failed_idempotency_key": part_record.get("base_key"),
                                          "failed_payload_sha256": part_record.get("base_payload_sha256")})
        if pending_parts:
            for job in pending_parts:
                part_payload = _queue_payload(queue_root, job)
                long_body_pending.append({"article_id": article_id,
                                          "part_index": part_payload["part_descriptor"]["part_index"],
                                          "part_count": len(spec["plan"]["parts"]),
                                          "queue_status": job.get("status"),
                                          "queue_reason": "LONG_BODY_PART_NOT_SUCCEEDED",
                                          "attempt_count": job.get("attempt_count")})
        if missing_parts:
            for index in missing_parts:
                part = spec["plan"]["parts"][index]
                if not spec["part_records"][index].get("base_failure_code"):
                    long_body_pending.append({"article_id": article_id, "part_index": part["part_index"],
                                              "part_count": len(spec["plan"]["parts"]),
                                              "queue_status": "MISSING",
                                              "queue_reason": "SAVED_PART_QUEUE_ITEM_NOT_FOUND"})
        if failed_parts or pending_parts or missing_parts or canary_integrity_blocked:
            active_repair_pending = any(record.get("repair_status") in {
                "REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED", "REPAIR_NOT_RUNNABLE",
                "REPAIR_CANARY_PENDING_STOP",
                "REPAIR_CANARY_INVALID_STOP", "REPAIR_CANARY_SYSTEM_STOP",
                "REPAIR_AUTO_CONTINUATION_PENDING",
            } for record in spec["part_records"])
            spec["status"] = "PART_REPAIR_PENDING" if active_repair_pending else (
                "PART_FAILED" if failed_parts else "PARTS_PENDING")
            long_body_summaries.append({"article_id": article_id, "plan_sha256": spec["plan"]["plan_sha256"],
                                        "plan_ref": spec["plan_ref"], "part_count": len(part_jobs),
                                        "parts_succeeded": sum(isinstance(job, dict) and job.get("status") == "SUCCEEDED"
                                                               for job in part_jobs),
                                        "status": spec["status"]})
            continue

        chunks.verify_part_coverage(spec["article"]["article_body"], spec["article"]["body_sha256"],
                                    spec["unit_map"], spec["plan"])
        reports = []
        allowed_intervals: list[list[int]] = []
        order = {unit["source_unit_id"]: index for index, unit in enumerate(spec["unit_map"]["units"])}
        part_result_shas = []
        for part, job in zip(spec["plan"]["parts"], part_jobs):
            result_value, result_sha, raw_sha = _read_internal_validated_result(queue_root, job)
            if (result_value.get("schema") != chunks.PART_RESULT_SCHEMA
                    or result_value.get("article_id") != article_id
                    or result_value.get("source_sha256") != spec["article"]["source_sha256"]
                    or result_value.get("body_sha256") != spec["article"]["body_sha256"]
                    or result_value.get("plan_sha256") != spec["plan"]["plan_sha256"]
                    or result_value.get("part_index") != part["part_index"]
                    or result_value.get("part_count") != part["part_count"]
                    or result_value.get("part_sha256") != part["part_sha256"]
                    or result_value.get("source_unit_map_sha256") != spec["unit_map"]["source_unit_map_sha256"]):
                raise FlashRunError("LONG_BODY_PART_RESULT_BINDING_MISMATCH")
            for cite in result_value.get("citation_ranges", []):
                if not isinstance(cite, dict):
                    raise FlashRunError("LONG_BODY_PART_CITATION_RANGE_INVALID")
                prefix = article_id + "::"
                start_wire, end_wire = cite.get("start_source_unit_id"), cite.get("end_source_unit_id")
                if (not isinstance(start_wire, str) or not isinstance(end_wire, str)
                        or not start_wire.startswith(prefix) or not end_wire.startswith(prefix)):
                    raise FlashRunError("LONG_BODY_PART_CITATION_RANGE_INVALID")
                start_id, end_id = start_wire[len(prefix):], end_wire[len(prefix):]
                if start_id not in order or end_id not in order or order[start_id] > order[end_id]:
                    raise FlashRunError("LONG_BODY_PART_CITATION_RANGE_INVALID")
                allowed_intervals.append([order[start_id], order[end_id]])
            part_result_shas.append(result_sha)
            reports.append({"part_index": part["part_index"], "part_count": part["part_count"],
                            "part_descriptor": part,
                            "part_sha256": part["part_sha256"], "part_result_sha256": result_sha,
                            "part_raw_response_sha256": raw_sha,
                            "reader_report": result_value["reader_output"],
                            "citation_ranges": result_value["citation_ranges"]})

        cross_ledger = chunks.cross_part_ledger(
            spec["article"]["fixed_fact_ledger"], spec["unit_map"], spec["plan"],
            model_ledger=lambda value: runner._simple_model_fixed_fact_ledger_for_article(value, article_id))
        lock = input_value.get("recovery_lock")
        synthesis_input = {
            "schema": chunks.SYNTHESIS_INPUT_SCHEMA,
            "article_id": article_id,
            "source_sha256": spec["article"]["source_sha256"],
            "body_sha256": spec["article"]["body_sha256"],
            "source_unit_map_sha256": spec["unit_map"]["source_unit_map_sha256"],
            "plan_sha256": spec["plan"]["plan_sha256"],
            "batch_binding_sha256": spec["plan"]["batch_binding_sha256"],
            "frozen_recovery_manifest_sha256": lock.get("row_manifest_sha256") if isinstance(lock, dict) else None,
            "root_batch_job_id": lock.get("root_batch_job_id") if isinstance(lock, dict) else None,
            "target_date": input_value.get("target_date"),
            "cutoff": input_value.get("cutoff"),
            "membership_authority_sha256": spec["article"]["article_metadata"].get("membership_authority_sha256"),
            "part_count": len(reports),
            "part_reports": reports,
            "cross_part_fixed_fact_ledger": cross_ledger,
        }
        synthesis_input_sha256 = sha(canonical(synthesis_input))
        synthesis_input["synthesis_input_sha256"] = synthesis_input_sha256
        synthesis_messages = _synthesis_messages(
            system_prompt=synthesis_system_prompt, article_id=article_id,
            article_metadata=spec["article"]["article_metadata"],
            synthesis_input=synthesis_input, input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)
        synthesis_tokens = helper._token_count(tokenizer, synthesis_messages)
        if chunks.synthesis_intervals_from_reports(
                reports, article_id=article_id, unit_map=spec["unit_map"]) != allowed_intervals:
            raise FlashRunError("LONG_BODY_CITATION_ALLOWLIST_RECONCILIATION_FAILED")
        synthesis_rules = (f"recent_day_reader_v2+profile:{PROFILE}+citation:{request_material['citation_protocol']}"
                           f"+unit-map:{spec['unit_map']['source_unit_map_sha256']}"
                           f"+fixed-ledger:{spec['article']['fixed_fact_ledger']['ledger_sha256']}"
                           f"+schema:{request_material['schema_sha256']}+temperature:0.0+thinking:off"
                           f"+long-body-synthesis:v1+plan:{spec['plan']['plan_sha256']}"
                           f"+synthesis-input:{synthesis_input_sha256}"
                           f"+part-results:{sha(canonical(part_result_shas))}"
                           f"+synthesis-prompt:{synthesis_prompt_sha256}"
                           f"+synthesis-addendum:{chunks.SYNTHESIS_ADDENDUM_SHA256}")
        synthesis_payload = {
            **spec["article"],
            "date": spec["article"]["article_metadata"]["publication_date"], "market": "HK",
            "prompt_sha256": synthesis_prompt_sha256, "model_id": runner.MODEL_ID,
            "configuration_sha256": request_material["configuration_sha256"],
            "rules": synthesis_rules, "role": "announcement_reader_synthesis",
            "stage": "v4_manager_announcement_flash_long_body_synthesis_v1",
            "queue_task_kind": "announcement_reader_synthesis",
            "chunk_plan_sha256": spec["plan"]["plan_sha256"],
            "synthesis_input_sha256": synthesis_input_sha256,
            "part_result_sha256s": part_result_shas,
            "synthesis_input": synthesis_input,
            "allowed_source_intervals": allowed_intervals,
            "source_unit_map_sha256": spec["unit_map"]["source_unit_map_sha256"],
            "validated_article_batch": spec["batch"],
            "messages": synthesis_messages,
            "structured_output_schema": request_material["schema"],
            "workflow_profile": PROFILE,
            "citation_protocol": request_material["citation_protocol"],
            "input_schema": chunks.SYNTHESIS_INPUT_SCHEMA,
            "prompt_tokens_exact": synthesis_tokens,
            "prompt_token_cap": synthesis_prompt_token_cap,
            "context_limit_tokens": context_limit,
            "completion_reserve_tokens": completion_reserve,
            "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN,
            "batch_binding_sha256": spec["plan"]["batch_binding_sha256"],
        }
        saved_raw_recovery = (_recover_failed_synthesis_from_saved_raw(
            synthesis_payload, queue, queue_root, recovery_lock=recovery_lock,
            membership_gate=membership_gate, count_prompt_tokens=count_prompt_tokens,
            validator=validator,
        ) if resume_same_batch_pending and not materialize_only else None)
        if isinstance(saved_raw_recovery, dict) and saved_raw_recovery.get("status") == "BLOCKED":
            spec["status"] = "SYNTHESIS_SAVED_RAW_RECOVERY_BLOCKED"
            failure_code = saved_raw_recovery.get("failure_code")
            long_body_pending.append({"article_id": article_id,
                                     "queue_reason": "SAVED_SYNTHESIS_RAW_RECOVERY_BLOCKED",
                                     "failure_code": failure_code,
                                     "part_count": len(reports),
                                     "synthesis_input_sha256": synthesis_input_sha256})
            long_body_failures.append({"article_id": article_id,
                                       "failure_code": failure_code,
                                       "stage": "saved_raw_recovery",
                                       "status": "FAILED"})
            long_body_summaries.append({"article_id": article_id,
                                        "plan_sha256": spec["plan"]["plan_sha256"],
                                        "plan_ref": spec["plan_ref"], "part_count": len(reports),
                                        "parts_succeeded": len(reports), "status": spec["status"],
                                        "synthesis_prompt_tokens": synthesis_tokens})
            continue
        if isinstance(saved_raw_recovery, dict) and saved_raw_recovery.get("status") == "RECOVERED":
            key = saved_raw_recovery["key"]
            job = saved_raw_recovery["job"]
            created = runnable = False
            recovered_synthesis_results[key] = saved_raw_recovery
            publication, audit_outcome = _saved_raw_recovery_publication(article_id, saved_raw_recovery)
            saved_raw_recoveries.append(publication)
            saved_raw_recovery_outcomes.append(audit_outcome)
            spec["saved_raw_recovery"] = saved_raw_recovery["trace"]
            spec["status"] = "SAVED_RAW_RECOVERED_ORIGINAL_FAILURE_PRESERVED"
            long_body_failures.append({"article_id": article_id,
                                       "failure_code": saved_raw_recovery["trace"]["failure_code"],
                                       "stage": "validator",
                                       "status": "FAILED",
                                       "resolution": "DERIVED_FROM_IMMUTABLE_SAVED_RAW"})
        else:
            try:
                key, job, created, runnable = _admit_synthesis_if_within_budget(
                    synthesis_payload, synthesis_tokens, synthesis_prompt_token_cap, queue, queue_root,
                    allow_same_batch_pending=resume_same_batch_pending and not materialize_only,
                    allow_enqueue=not materialize_only)
            except FlashRunError as exc:
                reused = None
                if (not materialize_only and resume_same_batch_pending
                        and exc.code == "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"):
                    reused = _reuse_succeeded_synthesis_after_provenance_drift(
                        synthesis_payload, queue, queue_root, recovery_lock=recovery_lock,
                        membership_gate=membership_gate, count_prompt_tokens=count_prompt_tokens,
                        validator=validator,
                    )
                if reused is not None:
                    key, job, created, runnable = reused
                else:
                    if not materialize_only or exc.code not in {
                            "SAVED_PARTIAL_QUEUE_ITEM_NOT_FOUND", "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"}:
                        raise
                    spec["status"] = ("SYNTHESIS_SAVED_IDENTITY_CONFLICT" if exc.code ==
                                       "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
                                       else "SYNTHESIS_NOT_SAVED_NOT_MATERIALIZED")
                    long_body_pending.append({"article_id": article_id,
                                             "queue_reason": ("SAVED_SYNTHESIS_IDENTITY_CONFLICT" if exc.code ==
                                                              "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
                                                              else "SAVED_SYNTHESIS_ITEM_NOT_FOUND"),
                                             "failure_code": exc.code if exc.code ==
                                             "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT" else None,
                                             "part_count": len(reports),
                                             "synthesis_input_sha256": synthesis_input_sha256})
                    long_body_summaries.append({"article_id": article_id,
                                                "plan_sha256": spec["plan"]["plan_sha256"],
                                                "plan_ref": spec["plan_ref"], "part_count": len(reports),
                                                "parts_succeeded": len(reports), "status": spec["status"],
                                                "synthesis_prompt_tokens": synthesis_tokens})
                    continue
        if key is None:
            spec["status"] = "CONTEXT_PENDING"
            long_body_synthesis_context.append({"article_id": article_id,
                                                "queue_reason": "LONG_BODY_SYNTHESIS_INPUT_EXCEEDS_TOKEN_CAP",
                                                "prompt_tokens": synthesis_tokens,
                                                "prompt_token_cap": synthesis_prompt_token_cap,
                                                "completion_reserve_tokens": completion_reserve,
                                                "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN,
                                                "part_count": len(reports),
                                                "synthesis_input_sha256": synthesis_input_sha256})
            long_body_summaries.append({"article_id": article_id,
                                        "plan_sha256": spec["plan"]["plan_sha256"],
                                        "plan_ref": spec["plan_ref"], "part_count": len(reports),
                                        "parts_succeeded": len(reports), "status": spec["status"],
                                        "synthesis_prompt_tokens": synthesis_tokens})
            continue
        articles_by_key[key] = {name: spec["article"][name] for name in (
            "article_id", "source_sha256", "body_sha256", "article_body",
            "article_metadata", "fixed_fact_ledger")}
        tracked_keys.add(key)
        if runnable:
            synthesis_allowed.add(key)
        internal_records.append({"article_id": article_id, "kind": "synthesis", "key": key,
                                 "job": job, "created": created,
                                 "runnable": runnable,
                                 "synthesis_input_sha256": synthesis_input_sha256,
                                 "prompt_tokens_exact": synthesis_tokens})
        spec["synthesis_key"] = key
        spec["synthesis_payload"] = synthesis_payload
        if spec.get("status") != "SAVED_RAW_RECOVERED_ORIGINAL_FAILURE_PRESERVED":
            spec["status"] = "SYNTHESIS_PENDING" if job.get("status") != "SUCCEEDED" else "SUCCEEDED"
        long_body_summaries.append({"article_id": article_id,
                                    "plan_sha256": spec["plan"]["plan_sha256"],
                                    "plan_ref": spec["plan_ref"], "part_count": len(reports),
                                    "parts_succeeded": len(reports), "status": spec["status"],
                                    "synthesis_prompt_tokens": synthesis_tokens,
                                    "synthesis_input_sha256": synthesis_input_sha256})

    tracked_keys.update(synthesis_allowed)
    run_queue_keys(synthesis_allowed)

    # Refresh long-body terminal summaries after synthesis execution. Only the
    # synthesis job is inserted into articles_by_key and therefore candidates.
    final_jobs = queue._load_state().get("jobs", {})
    for summary in long_body_summaries:
        if summary.get("status") == "SYNTHESIS_PENDING":
            spec = long_body_specs.get(summary["article_id"], {})
            synth_key = spec.get("synthesis_key")
            synth_job = final_jobs.get(synth_key) if synth_key else None
            if isinstance(synth_job, dict) and synth_job.get("status") == "SUCCEEDED":
                summary["status"] = "SUCCEEDED"
                spec["status"] = "SUCCEEDED"
            elif isinstance(synth_job, dict) and synth_job.get("status") == "FAILED":
                summary["status"] = "SYNTHESIS_FAILED"
                spec["status"] = "SYNTHESIS_FAILED"
                attempt = (synth_job.get("attempts") or [{}])[-1]
                error = attempt.get("error") if isinstance(attempt, dict) else None
                long_body_failures.append({"article_id": summary["article_id"],
                                           "failure_code": error.get("code") if isinstance(error, dict)
                                           and SAFE_CODE_RE.fullmatch(str(error.get("code", "")))
                                           else "LONG_BODY_SYNTHESIS_FAILED",
                                           "status": "FAILED"})
            else:
                summary["status"] = "SYNTHESIS_PENDING"
                spec["status"] = "SYNTHESIS_PENDING"

    snapshot = queue.snapshot()
    queue_items = {item["idempotency_key"]: item for item in snapshot["items"]}
    persisted_state = queue._load_state().get("jobs", {})
    selected_rows: list[dict[str, Any]] = []
    fresh_selected_rows: list[dict[str, Any]] = []
    reused_selected_rows: list[dict[str, Any]] = []
    recovered_selected_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pending_queue: list[dict[str, Any]] = []
    pending_queue.extend(admission.get("read_only_missing", []))
    current_status_counts: Counter[str] = Counter()
    historical_outcomes: list[dict[str, Any]] = []
    current_capture_bindings: dict[str, dict[str, Any]] = {}
    for key, article in articles_by_key.items():
        item = queue_items.get(key)
        saved = persisted_state.get(key)
        if item is None or saved is None:
            raise FlashRunError("CURRENT_QUEUE_ITEM_NOT_PERSISTED")
        current_status_counts[item.get("status", "MISSING")] += 1
        article_id = article["article_id"]
        if item.get("identity", {}).get("article_id") != article_id:
            raise FlashRunError("CURRENT_QUEUE_ARTICLE_IDENTITY_MISMATCH")
        recovered = recovered_synthesis_results.get(key)
        if recovered is not None:
            projected = recovered.get("result")
            results = projected.get("results") if isinstance(projected, dict) else None
            if (item.get("status") != "FAILED" or not isinstance(results, list) or len(results) != 1
                    or results[0].get("article_id") != article_id):
                raise FlashRunError("SAVED_SYNTHESIS_DERIVED_RESULT_IDENTITY_INVALID")
            output = results[0].get("reader_output", {})
            if (output.get("source_sha256") != article["source_sha256"]
                    or output.get("body_sha256") != article["body_sha256"]):
                raise FlashRunError("SAVED_SYNTHESIS_DERIVED_RESULT_SOURCE_MISMATCH")
            if (output.get("disposition") in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                    and output.get("direction") == "POSITIVE"):
                projected_article = _public_article(article_id, article, output)
                projected_article["candidate_origin"] = "SAVED_RAW_RECOVERY"
                current_payload = long_body_specs.get(article_id, {}).get("synthesis_payload")
                if current_payload is not None:
                    projected_article["current_capture"] = _current_capture_binding(
                        current_payload, capture_ref["sha256"])
                selected_rows.append(projected_article)
                recovered_selected_rows.append(projected_article)
        elif item.get("status") == "SUCCEEDED":
            input_raw = SafeRoot(queue_root).read_bytes(saved["input_path"], max_bytes=64 * 1024 * 1024)
            if sha(input_raw) != saved.get("payload_sha256"):
                raise FlashRunError("QUEUE_INPUT_SHA_MISMATCH")
            model_input = _json(input_raw, "QUEUE_INPUT_INVALID")
            if (model_input.get("article_id") != article_id
                    or model_input.get("source_sha256") != article["source_sha256"]
                    or model_input.get("body_sha256") != article["body_sha256"]):
                raise FlashRunError("QUEUE_INPUT_SOURCE_IDENTITY_MISMATCH")
            if not _is_final_candidate_task(model_input.get("queue_task_kind")):
                # Defensive candidate barrier: internal part reports are local
                # evidence even if a future admission path accidentally tracks one.
                continue
            source_article = {name: model_input[name] for name in (
                "article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")}
            if (source_article["article_body"] != article["article_body"]
                    or source_article["article_metadata"].get("source_origins") != article["article_metadata"].get("source_origins")):
                # A previously enqueued exact content identity keeps its original
                # immutable provenance and payload; use that source for display.
                if source_article["article_body"] != article["article_body"]:
                    raise FlashRunError("QUEUE_INPUT_BODY_CHANGED")
            result_path = Path(str(item.get("validated_path") or ""))
            if not result_path.is_absolute() or not result_path.resolve().is_relative_to(queue_root.resolve()):
                raise FlashRunError("VALIDATED_RESULT_REFERENCE_OUTSIDE_QUEUE")
            raw = result_path.read_bytes()
            if sha(raw) != item.get("validated_sha256"):
                raise FlashRunError("VALIDATED_RESULT_SHA_MISMATCH")
            projected = _json(raw, "VALIDATED_RESULT_JSON_INVALID")
            results = projected.get("results")
            if not isinstance(results, list) or len(results) != 1 or results[0].get("article_id") != article_id:
                raise FlashRunError("VALIDATED_RESULT_IDENTITY_INVALID")
            output = results[0].get("reader_output", {})
            if output.get("source_sha256") != source_article["source_sha256"] or output.get("body_sha256") != source_article["body_sha256"]:
                raise FlashRunError("VALIDATED_RESULT_SOURCE_IDENTITY_MISMATCH")
            if output.get("disposition") in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"} and output.get("direction") == "POSITIVE":
                projected_article = _public_article(article_id, source_article, output)
                current_payload = admission["resumed_payloads_by_key"].get(key)
                if current_payload is not None:
                    projected_article["current_capture"] = _current_capture_binding(
                        current_payload, capture_ref["sha256"])
                selected_rows.append(projected_article)
                fresh_selected_rows.append(projected_article)
        elif item.get("status") == "FAILED":
            attempt = (item.get("attempts") or [{}])[-1]
            error = attempt.get("error") if isinstance(attempt, dict) else None
            code = error.get("code") if isinstance(error, dict) and SAFE_CODE_RE.fullmatch(str(error.get("code", ""))) else "MODEL_ATTEMPT_FAILED"
            failures.append({"article_id": article_id, "symbol": article["article_metadata"].get("symbol"),
                             "title": article["article_metadata"].get("title"), "failure_code": code,
                             "stage": error.get("stage") if isinstance(error, dict) else None})
        elif item.get("status") == "PENDING":
            pending_queue.append({"article_id": article_id, "symbol": article["article_metadata"].get("symbol"),
                                  "title": article["article_metadata"].get("title"),
                                  "queue_reason": "STOPPED_AFTER_SYSTEM_FAILURE" if system_stop else "NOT_RUN"})
        else:
            continue

    failures.extend(long_body_failures)
    preflight_pending.extend(long_body_synthesis_context)

    history_projection = _project_historical_matches(matched_history, capture_ref["sha256"])
    current_version_article_ids = {record.get("article_id") for record in admission["version_associations"]
                                   if isinstance(record.get("article_id"), str)}
    current_batch_selected_rows = [row for row in history_projection["selected"]
                                   if row.get("article_id") in current_version_article_ids]
    current_batch_selected_stocks = _aggregate(current_batch_selected_rows)
    current_version_status_counts: Counter[str] = Counter(
        record.get("queue_status", "UNKNOWN") for record in admission["version_associations"])
    recovered_ids = {row.get("article_id") for row in recovered_selected_rows}
    history_selected = [row for row in history_projection["selected"]
                        if row.get("article_id") not in recovered_ids]
    selected_rows.extend(history_selected)
    reused_selected_rows.extend(history_selected)
    failures.extend(history_projection["failures"])
    pending_queue.extend(history_projection["pending"])
    historical_outcomes = history_projection["outcomes"]
    current_capture_bindings = history_projection["current_capture_bindings"]
    recovered_article_ids = {row["article_id"] for row in saved_raw_recovery_outcomes}
    if any(row.get("article_id") in recovered_article_ids for row in historical_outcomes
           if isinstance(row, dict)):
        raise FlashRunError("SAVED_RAW_RECOVERY_HISTORY_IDENTITY_CONFLICT")
    historical_outcomes.extend(saved_raw_recovery_outcomes)
    resumed_outcomes: list[dict[str, Any]] = []
    for key, current_payload in admission["resumed_payloads_by_key"].items():
        current_capture_bindings[current_payload["article_id"]] = _current_capture_binding(
            current_payload, capture_ref["sha256"])
        saved = persisted_state.get(key, {})
        resumed_outcomes.append({
            "article_id": current_payload["article_id"],
            "source": "INCREMENTAL_QUEUE",
            "status_before": "PENDING",
            "status_after": saved.get("status", "MISSING"),
            "attempt_count_before": 0,
            "attempt_count_after": saved.get("attempt_count"),
            "body_sha256": current_payload.get("body_sha256"),
            "original_source_sha256": admission["articles_by_key"][key].get("source_sha256"),
            "current_capture_source_sha256": current_payload.get("source_sha256"),
            "current_capture_product_sha256": capture_ref["sha256"],
            "membership_authority_sha256": current_payload.get("article_metadata", {}).get(
                "membership_authority_sha256"),
        })
    historical_outcomes.extend(resumed_outcomes)

    counts = dict(current_status_counts)
    complete = (all(status == "SUCCEEDED" for status in current_status_counts.values())
                and not body_gaps and not preflight_pending and not failures and not pending_queue
                and all(spec.get("status") == "SUCCEEDED" for spec in long_body_specs.values())
                and membership_gate.get("status") == "VERIFIED"
                and membership_article_counts.get("unknown", 0) == 0)
    queue_counts = {key.lower(): value for key, value in counts.items()}
    internal_new_enqueued = sum(record.get("created") is True for record in internal_records)
    internal_resumed = sum(record.get("created") is not True and record.get("runnable") is True
                           for record in internal_records)
    queue_counts.update({"new_enqueued": 0 if materialize_only else admission["new_enqueued"] + internal_new_enqueued,
                         "new_model_calls_allowed": 0 if materialize_only else len(allowed_keys | synthesis_allowed),
                         "resumed_pending_allowed": 0 if materialize_only else admission["resumed_pending"] + internal_resumed,
                         "saved_pending_not_dispatched": len(allowed_keys | synthesis_allowed) if materialize_only else 0,
                         "same_capture_duplicates_skipped": admission["duplicate_count"]})
    internal_state = queue._load_state().get("jobs", {})
    part_status_counts: Counter[str] = Counter()
    part_repair_counts: Counter[str] = Counter()
    for record in internal_records:
        if record.get("kind") == "part":
            base_saved = internal_state.get(record.get("base_key"), {})
            status = ("FAILED" if materialize_only and base_saved.get("status") == "FAILED"
                      else "CANNOT_CONFIRM" if materialize_only
                      and record.get("repair_status") == "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED"
                      else internal_state.get(record["key"], {}).get("status", "MISSING"))
            part_status_counts[status] += 1
            repair_status = record.get("repair_status")
            if isinstance(repair_status, str):
                part_repair_counts[repair_status] += 1
    queue_counts.update({f"long_body_parts_{name.lower()}": value
                         for name, value in part_status_counts.items()})
    queue_counts.update({f"long_body_part_repairs_{name.lower()}": value
                         for name, value in part_repair_counts.items()})
    queue_counts["long_body_parts_pending"] = sum(
        1 for item in long_body_pending
        if isinstance(item, dict) and item.get("part_index") is not None
        and item.get("queue_reason") != "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM"
        and item.get("queue_status") != "CANNOT_CONFIRM")
    queue_counts["long_body_parts_cannot_confirm"] = sum(
        1 for item in long_body_pending
        if isinstance(item, dict) and item.get("part_index") is not None
        and (item.get("queue_reason") == "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM"
             or item.get("queue_status") == "CANNOT_CONFIRM"))
    queue_counts["long_body_synthesis_pending"] = sum(
        1 for item in long_body_pending if isinstance(item, dict)
        and item.get("part_index") is None
        and isinstance(item.get("queue_reason"), str)
        and "SYNTHESIS" in item["queue_reason"])
    queue_counts["recovery_version_associations"] = len(admission["version_associations"])
    for key in ("pinned_succeeded", "pinned_failed", "pinned_pending", "reviewed_succeeded",
                "incremental_succeeded", "incremental_failed", "incremental_pending",
                "incremental_running"):
        queue_counts[f"{key}_matched"] = admission["historical_counts"].get(key, 0)
    for key, value in admission["historical_counts"].items():
        queue_counts[f"{key}_matched"] = value
    if admission["version_associations"]:
        queue_counts.update({
            "current_version_articles": len(admission["version_associations"]),
            "current_version_succeeded_matched": current_version_status_counts.get("SUCCEEDED", 0),
            "current_version_failed_matched": current_version_status_counts.get("FAILED", 0),
            "current_version_pending_matched": current_version_status_counts.get("PENDING", 0),
            "other_incremental_succeeded_matched": admission["historical_counts"].get("incremental_succeeded", 0),
            "incremental_succeeded_matched": current_version_status_counts.get("SUCCEEDED", 0),
            "incremental_failed_matched": current_version_status_counts.get("FAILED", 0),
            "incremental_pending_matched": current_version_status_counts.get("PENDING", 0),
        })
    fresh_stocks = _aggregate(fresh_selected_rows)
    reused_stocks = _aggregate(reused_selected_rows)
    recovered_stocks = _aggregate(recovered_selected_rows)
    pinned_receipt = next((item for item in pinned_history if item.get("candidate_manifest_sha256")), {})
    prior_receipt_sha = next((item.get("prior_reuse_receipt_sha256") for item in pinned_history
                              if item.get("prior_reuse_receipt_sha256")), None)
    long_body_public = []
    for article_id, spec in long_body_specs.items():
        part_items = []
        for part, key, part_record in zip(spec["plan"]["parts"], spec["part_keys"], spec["part_records"]):
            saved = internal_state.get(key, {})
            displayed_status = ("CANNOT_CONFIRM" if part_record.get("base_failure_code") or part_record.get(
                "repair_status") == "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED" else saved.get("status", "MISSING"))
            repair_key = part_record.get("repair_key")
            repair_job = internal_state.get(repair_key, {}) if repair_key else {}
            part_items.append({"part_index": part["part_index"], "part_count": part["part_count"],
                               "part_sha256": part["part_sha256"], "prompt_tokens_exact": part["prompt_tokens_exact"],
                               "status": displayed_status,
                               "attempt_count": saved.get("attempt_count"),
                               "validated_result_sha256": saved.get("validated_sha256"),
                               "original_idempotency_key": part_record.get("base_key"),
                               "original_payload_sha256": part_record.get("base_payload_sha256"),
                               "original_status": part_record.get("base_status"),
                               "repair": {"status": part_record.get("repair_status"),
                                          "failure_code": part_record.get("repair_failure_code"),
                                          "canary_failure_code": part_record.get("canary_failure_code"),
                                          "idempotency_key": repair_key,
                                          "payload_sha256": repair_job.get("payload_sha256"),
                                          "binding_sha256": part_record.get("repair_binding_sha256")}})
        synth_key = spec.get("synthesis_key")
        synth_job = internal_state.get(synth_key, {}) if synth_key else {}
        recovered_synthesis = recovered_synthesis_results.get(synth_key) if synth_key else None
        recovered_trace = (recovered_synthesis.get("trace")
                           if isinstance(recovered_synthesis, dict) else None)
        synthesis_public_status = ("RECOVERED_FROM_SAVED_RAW" if isinstance(recovered_trace, dict)
                                  else synth_job.get("status", "NOT_ENQUEUED"))
        synthesis_result_sha = (recovered_trace.get("derived_validated_result_sha256")
                                if isinstance(recovered_trace, dict)
                                else synth_job.get("validated_sha256"))
        long_body_public.append({"article_id": article_id, "status": spec.get("status"),
                                 "source_sha256": spec["article"]["source_sha256"],
                                 "body_sha256": spec["article"]["body_sha256"],
                                 "source_unit_map_sha256": spec["unit_map"]["source_unit_map_sha256"],
                                 "plan_sha256": spec["plan"]["plan_sha256"],
                                 "plan_ref": spec["plan_ref"], "part_count": len(part_items),
                                 "parts": part_items,
                                 "synthesis": {"status": synthesis_public_status,
                                               "queue_status": synth_job.get("status", "NOT_ENQUEUED"),
                                               "attempt_count": synth_job.get("attempt_count"),
                                               "validated_result_sha256": synthesis_result_sha,
                                               "queue_validated_result_sha256": synth_job.get("validated_sha256"),
                                               "input_sha256": spec.get("synthesis_payload", {}).get("synthesis_input_sha256"),
                                               "prompt_tokens_exact": spec.get("synthesis_payload", {}).get("prompt_tokens_exact"),
                                               "saved_raw_recovery": spec.get("saved_raw_recovery")}})
    result = {
        "schema": "v4.manager_workbench.announcement_flash_result.v1",
        "job_id": job_id,
        "state": "SUCCEEDED" if complete else "PARTIAL",
        "target_trade_date": input_value["target_date"],
        "source_window": capture_product.get("window"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": runner.MODEL_ID,
        "profile": PROFILE,
        "citation_protocol": request_material["citation_protocol"],
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
        "review_status": "MODEL_CANDIDATE_UNREVIEWED",
        "counts": {
            "capture_rows": len(capture_product.get("rows", [])), "excluded_outside_window": excluded,
            "queue": queue_counts,
            "selected_model_articles": len(current_batch_selected_rows) if admission["version_associations"]
            else len(selected_rows),
            "new_selected_model_articles": len(current_batch_selected_rows) if admission["version_associations"]
            else len(fresh_selected_rows),
            "reused_selected_model_articles": len(current_batch_selected_rows) if admission["version_associations"]
            else len(reused_selected_rows),
            "saved_raw_recovered_articles": len(recovered_selected_rows),
            "new_candidate_stocks": len(current_batch_selected_stocks) if admission["version_associations"]
            else len(fresh_stocks),
            "reused_candidate_stocks": len(reused_stocks),
            "saved_raw_recovered_candidate_stocks": len(recovered_stocks),
            "body_gaps": len(body_gaps), "context_pending": len(preflight_pending),
            "queue_pending": current_version_status_counts.get("PENDING", 0)
            if admission["version_associations"] else len(pending_queue),
            "failed": current_version_status_counts.get("FAILED", 0)
            if admission["version_associations"] else len(failures),
            "membership_articles": {key: membership_article_counts.get(key, 0) for key in ("in", "out", "unknown")},
            "membership_stocks": {key: sum(status == key.upper() for status in membership_stock_symbols.values())
                                  for key in ("in", "out", "unknown")},
        },
        "long_body_processing": {
            "protocol": chunks.PART_PLAN_SCHEMA,
            "prompt_token_cap": prompt_token_cap,
            "hard_prompt_token_cap": hard_prompt_token_cap,
            "part_target_prompt_tokens": chunks.PART_TARGET_TOKEN_CAP,
            "synthesis_target_prompt_tokens": synthesis_prompt_token_cap,
            "synthesis_prompt_token_cap": synthesis_prompt_token_cap,
            "completion_reserve_tokens": completion_reserve,
            "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN,
            "part_addendum_sha256": chunks.PART_ADDENDUM_SHA256,
            "part_repair_addendum_sha256": chunks.PART_REPAIR_ADDENDUM_SHA256,
            "synthesis_addendum_sha256": chunks.SYNTHESIS_ADDENDUM_SHA256,
            "part_repair_policy": {"max_new_repair_versions_per_part": 1,
                                    "max_new_repair_parts_before_canary": 1,
                                    "auto_continue_after_verified_canary": True,
                                    "retryable_failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                                    "failed_originals_preserved": True,
                                    "repair_input_is_source_complete": True},
            "repair_continuation": repair_continuation,
            "items": long_body_public,
        },
        "stocks": _aggregate(selected_rows), "failures": failures,
        "saved_raw_recoveries": saved_raw_recoveries,
        "pending": [*pending_queue, *preflight_pending, *long_body_pending, *body_gaps],
        "membership_gate": public_gate(membership_gate),
        "membership_exclusions": membership_exclusions,
        "gaps": [*body_gaps], "system_stop": system_stop,
        "provenance": {"capture_product_sha256": capture_ref["sha256"],
                       "queue_id": QUEUE_ID,
                       "prompt_sha256": request_material["prompt_sha256"],
                       "configuration_sha256": request_material["configuration_sha256"],
                       "source_code_sha256": request_material.get("source_code_sha256"),
                       "runtime_settings_sha256": request_material.get("runtime_settings_sha256"),
                       "model_settings_sha256": request_material.get("model_settings_sha256"),
                       "schema_sha256": request_material.get("schema_sha256"),
                       "parser_sha256": request_material.get("parser_sha256"),
                       "pinned_candidate_id": "76e8763179830e975f11",
                       "pinned_candidate_queue_id": pinned_receipt.get("candidate_queue_id"),
                       "pinned_candidate_manifest_sha256": pinned_receipt.get("candidate_manifest_sha256"),
                       "pinned_candidate_validated_batch_sha256": pinned_receipt.get("candidate_validated_batch_sha256"),
                       "pinned_candidate_queue_state_sha256": pinned_receipt.get("candidate_queue_state_sha256"),
                       "prior_reuse_receipt_sha256": prior_receipt_sha,
                       "membership_gate": public_gate(membership_gate),
                       "historical_outcomes": historical_outcomes,
                       "queue_version_associations": admission["version_associations"],
                       "current_capture_bindings": current_capture_bindings},
    }
    if admission["version_associations"]:
        result["current_batch"] = {
            "article_count": len(admission["version_associations"]),
            "article_status_counts": {status.lower(): current_version_status_counts.get(status, 0)
                                       for status in ("SUCCEEDED", "FAILED", "PENDING", "RUNNING")},
            "selected_articles": len(current_batch_selected_rows),
            "candidate_stocks": len(current_batch_selected_stocks),
            "selected_stock_symbols": [stock["symbol"] for stock in current_batch_selected_stocks],
        }
    if resume_frozen_batch:
        final_jobs = queue._load_state().get("jobs", {})
        canary_status = final_jobs.get(resume_canary_key, {}).get("status") if resume_canary_key else None
        prior_resume = input_value.get("resume_source") if isinstance(input_value.get("resume_source"), dict) else {}
        canary_passed = (prior_resume.get("canary_passed") is True
                         or (max_model_calls == 1 and canary_status == "SUCCEEDED"))
        base_status_counts = {name.lower(): count for name, count in sorted(frozen_original_counts.items())}
        historical_conflicts = sum(1 for record in internal_records
                                   if record.get("historical_success_conflict") is not None)
        eligible_pending = sum(1 for record in internal_records
                               if record.get("base_status") == "PENDING"
                               and record.get("base_failure_code") is None
                               and record.get("key") == record.get("base_key")
                               and record.get("runnable") is True)
        resume_orphans = [record.get("orphan_recovery") for record in internal_records
                          if isinstance(record.get("orphan_recovery"), dict)]
        recoverable_orphan_count = sum(
            1 for orphan in resume_orphans
            if orphan.get("status") == "OWNER_CLEAR_NO_RESULT" and orphan.get("eligible") is True
        )
        result["resume"] = {
            "mode": "FROZEN_BATCH",
            "source_job_id": resume_source_job_id,
            "source_input_sha256": resume_source_input_sha256,
            "source_input_sha256_binding": (input_value.get("resume_source", {}).get("source_input_sha256")
                                              if isinstance(input_value.get("resume_source"), dict) else
                                              resume_source_input_sha256),
            "initial_part_status_counts": base_status_counts,
            "initial_part_total": len(frozen_part_keys),
            "pending_eligible": eligible_pending,
            "failed_preserved": frozen_original_counts.get("FAILED", 0),
            "succeeded_preserved": frozen_original_counts.get("SUCCEEDED", 0),
            "historical_success_conflicts": historical_conflicts,
            "orphan_candidates": resume_orphans,
            "recoverable_orphan_count": recoverable_orphan_count,
            "max_model_calls": max_model_calls,
            "model_calls": completed,
            "canary_key": resume_canary_key,
            "canary_status": canary_status,
            "canary_passed": canary_passed,
            "continue_eligible": canary_passed and not complete,
            "dispatched_keys": dispatched_keys,
        }
    if materialize_only:
        result["materialization"] = {
            "mode": "SAVED_VALIDATED_QUEUE_ONLY",
            "failure_code": materialization_failure["failure_code"],
            "failed_at": materialization_failure.get("failed_at"),
            "queue_dispatches": 0,
            "model_calls": 0,
            "current_capture_bound_articles": len(current_capture_bindings),
            "saved_selected_articles": len(current_batch_selected_rows) if admission["version_associations"]
            else len(selected_rows),
            "candidate_stocks": len(current_batch_selected_stocks) if admission["version_associations"]
            else len(result["stocks"]),
            "status": "PARTIAL_PUBLISHED_WITH_ORIGINAL_FAILURE",
        }
    return result


def _verify_resume_source(state_io: SafeRoot, capture_root: Path, source_job_id: str,
                          target_date: str, expected_hashes: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not JOB_ID_RE.fullmatch(str(source_job_id)) or not re.fullmatch(r"[0-9]{8}", str(target_date)):
        raise FlashRunError("FROZEN_RESUME_SOURCE_IDENTITY_INVALID")
    base = f"announcement_flash/jobs/{source_job_id}"
    input_raw = state_io.read_bytes(base + "/input.json", max_bytes=1024 * 1024)
    progress_raw = state_io.read_bytes(base + "/progress.json", max_bytes=1024 * 1024)
    queue_raw = state_io.read_bytes("announcement_flash/queue/queue-state.json", max_bytes=64 * 1024 * 1024)
    hashes = {"source_input_sha256": sha(input_raw),
              "source_progress_sha256": sha(progress_raw),
              "source_queue_state_sha256": sha(queue_raw)}
    if any(expected_hashes.get(key) != value for key, value in hashes.items()):
        raise FlashRunError("FROZEN_RESUME_SOURCE_SHA_CHANGED")
    input_value = _json(input_raw, "FROZEN_RESUME_INPUT_INVALID")
    progress_value = _json(progress_raw, "FROZEN_RESUME_PROGRESS_INVALID")
    queue_value = _json(queue_raw, "FROZEN_RESUME_QUEUE_STATE_INVALID")
    if (not isinstance(input_value, dict)
            or input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
            or input_value.get("job_id") != source_job_id
            or input_value.get("target_date") != target_date
            or not isinstance(progress_value, dict)
            or not isinstance(queue_value, dict)
            or queue_value.get("schema") != "v4.announcement-engine-queue/v1"
            or not isinstance(queue_value.get("jobs"), dict)):
        raise FlashRunError("FROZEN_RESUME_SOURCE_ARTIFACTS_INVALID")
    result_raw = None
    try:
        result_raw = state_io.read_bytes(base + "/result.json", max_bytes=64 * 1024 * 1024)
    except FileNotFoundError:
        pass
    if result_raw is None:
        try:
            attempt_value = _json(state_io.read_bytes(f"attempts/{source_job_id}.json", max_bytes=8 * 1024 * 1024),
                                  "FROZEN_RESUME_ATTEMPT_INVALID")
        except FileNotFoundError as exc:
            raise FlashRunError("FROZEN_RESUME_ATTEMPT_MISSING") from exc
        if (not isinstance(attempt_value, dict)
                or attempt_value.get("state") not in {"FAILED", "INTERRUPTED", "PARTIAL"}):
            raise FlashRunError("FROZEN_RESUME_SOURCE_NOT_INTERRUPTED")
    else:
        result_value = _json(result_raw, "FROZEN_RESUME_RESULT_INVALID")
        resume_value = result_value.get("resume") if isinstance(result_value, dict) else None
        if (not isinstance(result_value, dict) or result_value.get("state") != "PARTIAL"
                or not isinstance(resume_value, dict) or resume_value.get("mode") != "FROZEN_BATCH"
                or resume_value.get("canary_passed") is not True):
            raise FlashRunError("FROZEN_RESUME_RESULT_NOT_ELIGIBLE")
    capture_ref = input_value.get("capture_product")
    if (not isinstance(capture_ref, dict)
            or not isinstance(capture_ref.get("artifact_ref"), str)
            or not re.fullmatch(r"products/[0-9a-f]{64}\.json", capture_ref["artifact_ref"])
            or not isinstance(capture_ref.get("sha256"), str)
            or not SHA_RE.fullmatch(capture_ref["sha256"])):
        raise FlashRunError("FROZEN_RESUME_CAPTURE_REFERENCE_INVALID")
    capture_raw = SafeRoot(capture_root).read_bytes(capture_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
    if sha(capture_raw) != capture_ref["sha256"]:
        raise FlashRunError("FROZEN_RESUME_CAPTURE_SHA_MISMATCH")
    return input_value, queue_value


def _resume_dry_run_report(result: dict[str, Any], *, source_job_id: str,
                           source_hashes: dict[str, str], queue_sha_after: str) -> dict[str, Any]:
    resume = result.get("resume") if isinstance(result.get("resume"), dict) else {}
    return {"schema": "v4.manager_workbench.announcement_flash_resume_dry_run.v1",
            "status": "READ_ONLY_PLAN",
            "source_job_id": source_job_id,
            "source_hashes": source_hashes,
            "queue_state_sha_after": queue_sha_after,
            "queue_state_unchanged": source_hashes.get("source_queue_state_sha256") == queue_sha_after,
            "initial_part_status_counts": resume.get("initial_part_status_counts"),
            "initial_part_total": resume.get("initial_part_total"),
            "succeeded_preserved": resume.get("succeeded_preserved"),
            "failed_preserved": resume.get("failed_preserved"),
            "pending_eligible": resume.get("pending_eligible"),
            "historical_success_conflicts": resume.get("historical_success_conflicts"),
            "orphan_candidates": resume.get("orphan_candidates"),
            "recoverable_orphan_count": resume.get("recoverable_orphan_count"),
            "max_model_calls": 1,
            "model_calls": 0,
            "canary_candidate": resume.get("canary_key"),
            "continue_eligible_after_canary": resume.get("continue_eligible")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--shared-root")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--resume-pending", action="store_true",
                        help="Run only this frozen input's verified eligible zero-attempt PENDING queue items.")
    parser.add_argument("--resume-frozen-batch", action="store_true",
                        help="Resume the exact frozen source input without capture or retrying failed items.")
    parser.add_argument("--resume-dry-run", action="store_true",
                        help="Print a read-only frozen-resume plan; never writes queue or job state.")
    parser.add_argument("--resume-source-job-id")
    parser.add_argument("--source-input-sha256")
    parser.add_argument("--source-progress-sha256")
    parser.add_argument("--source-queue-state-sha256")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--materialize-saved-partial", action="store_true",
                        help="Publish only hash-verified saved results after a recorded failed run; never dispatch queue work.")
    parser.add_argument("--failure-code", help="Exact failure code recorded in progress.json for saved-result materialization.")
    args = parser.parse_args(argv)
    if not JOB_ID_RE.fullmatch(args.job_id):
        return 2
    state_root = Path(args.state_root).expanduser().absolute()
    capture_root = Path(args.capture_root).expanduser().absolute()
    state_io = SafeRoot(state_root)
    base = f"announcement_flash/jobs/{args.job_id}"
    try:
        input_value = _json(state_io.read_bytes(base + "/input.json", max_bytes=1024 * 1024), "FLASH_INPUT_INVALID")
        if (input_value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
                or input_value.get("job_id") != args.job_id
                or not isinstance(input_value.get("target_date"), str)
                or not re.fullmatch(r"[0-9]{8}", input_value["target_date"])):
            raise FlashRunError("FLASH_INPUT_IDENTITY_INVALID")
        if args.resume_dry_run:
            if (not args.resume_frozen_batch or args.resume_pending or args.materialize_saved_partial
                    or args.max_model_calls not in {None, 1}
                    or not isinstance(args.resume_source_job_id, str)
                    or args.job_id != args.resume_source_job_id):
                raise FlashRunError("FROZEN_RESUME_DRY_RUN_ARGUMENTS_INVALID")
            source_hashes = {"source_input_sha256": args.source_input_sha256,
                             "source_progress_sha256": args.source_progress_sha256,
                             "source_queue_state_sha256": args.source_queue_state_sha256}
            if any(not isinstance(value, str) or not SHA_RE.fullmatch(value)
                   for value in source_hashes.values()):
                raise FlashRunError("FROZEN_RESUME_DRY_RUN_HASHES_INVALID")
            source_input, _source_queue = _verify_resume_source(
                state_io, capture_root, args.resume_source_job_id,
                input_value["target_date"], source_hashes,
            )
            before_queue = state_io.read_bytes("announcement_flash/queue/queue-state.json",
                                               max_bytes=64 * 1024 * 1024)
            result = _run(source_input, state_root=state_root, capture_root=capture_root,
                          job_id=args.resume_source_job_id, progress=lambda _value: None,
                          shared_root=Path(args.shared_root).expanduser().absolute() if args.shared_root else None,
                          resume_frozen_batch=True, max_model_calls=1,
                          resume_source_job_id=args.resume_source_job_id,
                          resume_source_input_sha256=source_hashes["source_input_sha256"],
                          materialize_only=True,
                          materialization_failure={"failure_code": "RESUME_DRY_RUN"})
            after_queue = state_io.read_bytes("announcement_flash/queue/queue-state.json",
                                              max_bytes=64 * 1024 * 1024)
            if sha(before_queue) != sha(after_queue):
                raise FlashRunError("FROZEN_RESUME_DRY_RUN_MUTATED_QUEUE")
            report = _resume_dry_run_report(result, source_job_id=args.resume_source_job_id,
                                            source_hashes=source_hashes, queue_sha_after=sha(after_queue))
            report["source_input_identity_valid"] = (source_input.get("job_id") == args.resume_source_job_id)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.resume_frozen_batch:
            if args.resume_pending or args.materialize_saved_partial:
                raise FlashRunError("FROZEN_RESUME_ARGUMENTS_INVALID")
            resume_source = input_value.get("resume_source")
            resume_root = input_value.get("resume_root")
            if (not isinstance(resume_source, dict)
                    or resume_source.get("schema") != "v4.manager_workbench.announcement_flash_resume.v1"
                    or resume_source.get("target_date") != input_value["target_date"]
                    or not isinstance(resume_root, dict)
                    or not JOB_ID_RE.fullmatch(str(resume_root.get("source_job_id", "")))
                    or not isinstance(resume_root.get("source_input_sha256"), str)
                    or not SHA_RE.fullmatch(resume_root["source_input_sha256"])):
                raise FlashRunError("FROZEN_RESUME_INPUT_BINDING_INVALID")
            source_hashes = {key: resume_source.get(key) for key in (
                "source_input_sha256", "source_progress_sha256", "source_queue_state_sha256")}
            if any(not isinstance(value, str) or not SHA_RE.fullmatch(value)
                   for value in source_hashes.values()):
                raise FlashRunError("FROZEN_RESUME_INPUT_HASHES_INVALID")
            if args.max_model_calls != resume_source.get("max_model_calls"):
                raise FlashRunError("FROZEN_RESUME_MODEL_CALL_LIMIT_MISMATCH")
            _verify_resume_source(state_io, capture_root, str(resume_source.get("source_job_id")),
                                  input_value["target_date"], source_hashes)
            source_job_id = resume_root["source_job_id"]
            source_input_sha256 = resume_root["source_input_sha256"]
        else:
            source_job_id = None
            source_input_sha256 = None
        if args.materialize_saved_partial:
            if args.resume_pending or not isinstance(args.failure_code, str) or not SAFE_CODE_RE.fullmatch(args.failure_code):
                raise FlashRunError("SAVED_PARTIAL_ARGUMENTS_INVALID")
            progress_value = _json(state_io.read_bytes(base + "/progress.json", max_bytes=1024 * 1024),
                                   "SAVED_PARTIAL_PROGRESS_INVALID")
            if (progress_value.get("step") != "FAILED"
                    or progress_value.get("failure_code") != args.failure_code
                    or not isinstance(progress_value.get("updated_at"), str)
                    or not result_path_is_absent(state_io, base + "/result.json")):
                raise FlashRunError("SAVED_PARTIAL_FAILURE_STATE_MISMATCH")
            materialization_failure = {"failure_code": args.failure_code,
                                       "stage": progress_value.get("failed_step") or "FLASH_SELECTION",
                                       "failed_at": progress_value.get("updated_at")}
            recovery = isinstance(input_value.get("recovery_lock"), dict)
            result = _run(input_value, state_root=state_root, capture_root=capture_root,
                          job_id=args.job_id, progress=lambda _value: None,
                          shared_root=Path(args.shared_root).expanduser().absolute() if args.shared_root else None,
                          resume_same_batch_pending=recovery, materialize_only=True,
                          materialization_failure=materialization_failure)
            if result.get("state") != "PARTIAL" or result.get("system_stop", {}).get("failure_code") != args.failure_code:
                raise FlashRunError("SAVED_PARTIAL_RESULT_FAILURE_BINDING_INVALID")
            _write_json(state_io, base + "/result.json", result)
            return 0
        last_progress: dict[str, Any] = {"value": {}}
        def write_progress(value: dict[str, Any]) -> None:
            _write_json(state_io, base + "/progress.json", value)
            last_progress["value"] = value
        result = _run(input_value, state_root=state_root, capture_root=capture_root,
                      job_id=args.job_id, progress=write_progress,
                      shared_root=Path(args.shared_root).expanduser().absolute() if args.shared_root else None,
                      resume_same_batch_pending=args.resume_pending,
                      resume_frozen_batch=args.resume_frozen_batch,
                      max_model_calls=args.max_model_calls if args.resume_frozen_batch else None,
                      resume_source_job_id=source_job_id,
                      resume_source_input_sha256=source_input_sha256)
        _write_json(state_io, base + "/result.json", result)
        write_progress({"step": "DONE", "completed": result["counts"]["queue"].get("succeeded", 0),
                        "total": result["counts"]["queue"].get("succeeded", 0) + result["counts"]["queue"].get("failed", 0)
                        + result["counts"]["queue"].get("pending", 0), "result_state": result["state"],
                        "membership": result.get("membership_gate"),
                        "updated_at": datetime.now(timezone.utc).isoformat()})
        return 0
    except FlashRunError as exc:
        if args.resume_dry_run:
            print(json.dumps({"schema": "v4.manager_workbench.announcement_flash_resume_dry_run.v1",
                              "status": "BLOCKED", "code": exc.code}, sort_keys=True), flush=True)
            return 1
        if args.materialize_saved_partial:
            return 1
        write = {"step": "FAILED", "failure_code": exc.code,
                 "failed_step": last_progress.get("value", {}).get("step") if "last_progress" in locals() else None,
                 "updated_at": datetime.now(timezone.utc).isoformat()}
        _write_json(state_io, base + "/progress.json", write)
        return 1
    except Exception as exc:
        if args.resume_dry_run:
            failure_code, diagnostic = _safe_pipeline_failure_details(exc)
            print(json.dumps({"schema": "v4.manager_workbench.announcement_flash_resume_dry_run.v1",
                              "status": "BLOCKED", "code": failure_code,
                              "diagnostic": diagnostic}, sort_keys=True), flush=True)
            return 1
        failure_code, diagnostic = _safe_pipeline_failure_details(exc)
        if args.materialize_saved_partial:
            return 1
        _write_json(state_io, base + "/progress.json", {
            "step": "FAILED", "failure_code": failure_code,
            "failed_step": last_progress.get("value", {}).get("step") if "last_progress" in locals() else None,
            "diagnostic": diagnostic,
            "updated_at": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
