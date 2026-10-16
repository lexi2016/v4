#!/usr/bin/env python3
"""Run captured announcements through the existing local Flash pipeline.

This entry point is called only by an explicit Manager Workbench POST. It
reuses the existing prompt, batch validator, gated oMLX transport and durable
SerialAnnouncementQueue. It never captures sources itself.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
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


def _json(raw: bytes, code: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlashRunError(code) from exc


def _write_json(root: SafeRoot, ref: str, value: Any) -> None:
    root.write_bytes(ref, canonical(value) + b"\n")


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
             capture_io: SafeRoot, runner: Any) -> dict[str, Any]:
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
        "article_membership_status": "CANNOT_CONFIRM",
        "source_issuer_membership": [],
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


def _admit_incremental_payloads(payloads: list[dict[str, Any]], queue: Any,
                                pinned_history: list[dict[str, Any]], queue_root: Path) -> dict[str, Any]:
    """Only newly-enqueued semantic identities may reach run_next on this click."""
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
        content = _content_key(identity)
        candidates = reviewed_index.get(content, []) if content else []
        if not candidates:
            candidates = semantic_index.get(semantic, [])
        if candidates:
            record = max(candidates, key=_history_priority)
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
        item = queue.enqueue(payload)
        key = item["idempotency_key"]
        status = item.get("status")
        if not was_persisted and status == "PENDING" and item.get("attempt_count") == 0:
            allowed_keys.add(key)
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
            articles_by_key[key] = {field: payload[field] for field in (
                "article_id", "source_sha256", "body_sha256", "article_body",
                "article_metadata", "fixed_fact_ledger")}
            historical_counts[f"new_{str(status or 'unknown').lower()}"] += 1

    return {"allowed_keys": allowed_keys, "articles_by_key": articles_by_key,
            "matched": matched, "duplicate_count": duplicate_count,
            "conflicts": conflicts, "historical_counts": historical_counts,
            "new_enqueued": len(articles_by_key)}


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


def _validator(queue_module: Any, runner: Any, contract: Any, request_material: dict[str, Any], length_canary: Any):
    def validate(job: Any, parsed: Any) -> dict[str, Any]:
        payload = job.payload
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


def _run(input_value: dict[str, Any], *, state_root: Path, capture_root: Path,
         job_id: str, progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
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
    queue_root = state_root / "announcement_flash" / "queue"
    queue = queue_module.SerialAnnouncementQueue(queue_root, QUEUE_ID, runner.MODEL_ID,
                                                 max_attempts=1, max_body_bytes=None)

    body_gaps: list[dict[str, Any]] = []
    excluded = 0
    payloads: list[dict[str, Any]] = []
    preflight_pending: list[dict[str, Any]] = []
    for index, row in enumerate(capture_product.get("rows", [])):
        if not isinstance(row, dict):
            body_gaps.append({"article_id": None, "failure_code": "CAPTURE_ROW_INVALID"})
            continue
        article_id = "EASTMONEY:" + str(row.get("art_code") or "")
        if row.get("window_consumption_status") == "EXCLUDED_OUTSIDE_WINDOW":
            excluded += 1
            continue
        if (row.get("body_complete") is not True or not isinstance(row.get("body_text"), str)
                or not row.get("body_text")):
            codes = [item for item in row.get("gaps", []) if isinstance(item, str)]
            body_gaps.append({"article_id": article_id, "symbol": None,
                              "title": row.get("title"), "failure_code": codes[0] if codes else "BODY_INCOMPLETE"})
            continue
        try:
            article = _article(row, index, capture_product, capture_ref, capture_io, runner)
            batch = length_canary.make_batch([article], "V4_FLASH_" + sha(article["article_id"].encode())[:16])
            messages = helper._messages_for_article(article, contract, request_material["prompt"], PROFILE)
            prompt_tokens = helper._token_count(tokenizer, messages)
            context_limit = request_material["runtime_limits"]["context_limit_tokens"]
            if prompt_tokens > context_limit:
                preflight_pending.append({"article_id": article_id, "symbol": article["article_metadata"]["symbol"],
                                          "title": article["article_metadata"]["title"],
                                          "queue_reason": "INPUT_EXCEEDS_CONTEXT",
                                          "prompt_tokens": prompt_tokens, "context_limit_tokens": context_limit})
                continue
            unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
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
            payloads.append(payload)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raw_code = getattr(exc, "code", None) or str(exc)
            code = raw_code if isinstance(raw_code, str) and SAFE_CODE_RE.fullmatch(raw_code) else "SOURCE_PREPARATION_FAILED"
            body_gaps.append({"article_id": article_id, "symbol": row.get("source_issuer_codes", [{}])[0].get("code")
                              if row.get("source_issuer_codes") else None,
                              "title": row.get("title"), "failure_code": code})

    pinned_history = _pinned_candidate_history()
    admission = _admit_incremental_payloads(payloads, queue, pinned_history, queue_root)
    allowed_keys: set[str] = admission["allowed_keys"]
    articles_by_key: dict[str, dict[str, Any]] = admission["articles_by_key"]
    matched_history: list[dict[str, Any]] = admission["matched"]
    body_gaps.extend(admission["conflicts"])

    def current_counts() -> Counter:
        state = queue._load_state()
        jobs = state.get("jobs", {})
        return Counter(jobs.get(key, {}).get("status", "MISSING") for key in articles_by_key)

    progress({"step": "FLASH_SELECTION", "completed": 0, "total": len(allowed_keys),
              "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
              "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})

    evidence_root = state_root / "announcement_flash" / "evidence"
    completed = 0
    system_stop: dict[str, Any] | None = None
    if allowed_keys:
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
            progress({"step": "FLASH_SELECTION", "completed": completed, "total": len(allowed_keys),
                      "current_article_id": job.payload.get("article_id"),
                      "current_title": job.payload.get("article_metadata", {}).get("title"),
                      "last_event_type": event.get("type") if isinstance(event.get("type"), str) else "MODEL_EVENT",
                      "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                      "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})

        executor = _transport_executor(queue_module, transport, runner, request_material, evidence_root, on_progress)
        validator = _validator(queue_module, runner, contract, request_material, length_canary)
        try:
            while allowed_keys:
                result = queue.run_next(executor, validator, idempotency_keys=allowed_keys)
                if result is None:
                    break
                completed += 1
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
                progress({"step": "FLASH_SELECTION", "completed": completed, "total": len(allowed_keys),
                          "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                          "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})
        finally:
            transport.close()

    snapshot = queue.snapshot()
    queue_items = {item["idempotency_key"]: item for item in snapshot["items"]}
    persisted_state = queue._load_state().get("jobs", {})
    selected_rows: list[dict[str, Any]] = []
    fresh_selected_rows: list[dict[str, Any]] = []
    reused_selected_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pending_queue: list[dict[str, Any]] = []
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
        if item.get("status") == "SUCCEEDED":
            input_raw = SafeRoot(queue_root).read_bytes(saved["input_path"], max_bytes=64 * 1024 * 1024)
            if sha(input_raw) != saved.get("payload_sha256"):
                raise FlashRunError("QUEUE_INPUT_SHA_MISMATCH")
            model_input = _json(input_raw, "QUEUE_INPUT_INVALID")
            if (model_input.get("article_id") != article_id
                    or model_input.get("source_sha256") != article["source_sha256"]
                    or model_input.get("body_sha256") != article["body_sha256"]):
                raise FlashRunError("QUEUE_INPUT_SOURCE_IDENTITY_MISMATCH")
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

    history_projection = _project_historical_matches(matched_history, capture_ref["sha256"])
    selected_rows.extend(history_projection["selected"])
    reused_selected_rows.extend(history_projection["selected"])
    failures.extend(history_projection["failures"])
    pending_queue.extend(history_projection["pending"])
    historical_outcomes = history_projection["outcomes"]
    current_capture_bindings = history_projection["current_capture_bindings"]

    counts = dict(current_status_counts)
    complete = (all(status == "SUCCEEDED" for status in current_status_counts.values())
                and not body_gaps and not preflight_pending and not failures and not pending_queue)
    queue_counts = {key.lower(): value for key, value in counts.items()}
    queue_counts.update({"new_enqueued": admission["new_enqueued"],
                         "new_model_calls_allowed": len(allowed_keys),
                         "same_capture_duplicates_skipped": admission["duplicate_count"]})
    for key in ("pinned_succeeded", "pinned_failed", "pinned_pending", "reviewed_succeeded",
                "incremental_succeeded", "incremental_failed", "incremental_pending",
                "incremental_running"):
        queue_counts[f"{key}_matched"] = admission["historical_counts"].get(key, 0)
    for key, value in admission["historical_counts"].items():
        queue_counts[f"{key}_matched"] = value
    fresh_stocks = _aggregate(fresh_selected_rows)
    reused_stocks = _aggregate(reused_selected_rows)
    pinned_receipt = next((item for item in pinned_history if item.get("candidate_manifest_sha256")), {})
    prior_receipt_sha = next((item.get("prior_reuse_receipt_sha256") for item in pinned_history
                              if item.get("prior_reuse_receipt_sha256")), None)
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
            "selected_model_articles": len(selected_rows),
            "new_selected_model_articles": len(fresh_selected_rows),
            "reused_selected_model_articles": len(reused_selected_rows),
            "new_candidate_stocks": len(fresh_stocks), "reused_candidate_stocks": len(reused_stocks),
            "body_gaps": len(body_gaps), "context_pending": len(preflight_pending),
            "queue_pending": len(pending_queue), "failed": len(failures),
        },
        "stocks": _aggregate(selected_rows), "failures": failures,
        "pending": [*pending_queue, *preflight_pending, *body_gaps],
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
                       "historical_outcomes": historical_outcomes,
                       "current_capture_bindings": current_capture_bindings},
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--job-id", required=True)
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
        def write_progress(value: dict[str, Any]) -> None:
            _write_json(state_io, base + "/progress.json", value)
        result = _run(input_value, state_root=state_root, capture_root=capture_root,
                      job_id=args.job_id, progress=write_progress)
        _write_json(state_io, base + "/result.json", result)
        write_progress({"step": "DONE", "completed": result["counts"]["queue"].get("succeeded", 0),
                        "total": result["counts"]["queue"].get("succeeded", 0) + result["counts"]["queue"].get("failed", 0)
                        + result["counts"]["queue"].get("pending", 0), "result_state": result["state"],
                        "updated_at": datetime.now(timezone.utc).isoformat()})
        return 0
    except FlashRunError as exc:
        write = {"step": "FAILED", "failure_code": exc.code,
                 "updated_at": datetime.now(timezone.utc).isoformat()}
        _write_json(state_io, base + "/progress.json", write)
        return 1
    except Exception as exc:
        failure_code, diagnostic = _safe_pipeline_failure_details(exc)
        _write_json(state_io, base + "/progress.json", {
            "step": "FAILED", "failure_code": failure_code,
            "diagnostic": diagnostic,
            "updated_at": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
