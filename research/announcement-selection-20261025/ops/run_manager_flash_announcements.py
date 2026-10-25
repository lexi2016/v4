#!/usr/bin/env python3
"""Run captured announcements through the existing local Flash pipeline.

This entry point is called only by an explicit Manager Workbench POST. It
reuses the existing prompt, batch validator, gated oMLX transport and durable
SerialAnnouncementQueue. It never captures sources itself.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
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
TRANSPORT_RECOVERY_SCHEMA = "v4.manager_workbench.announcement_flash_transport_recovery.v1"
CANONICAL_HELPER_SHA256 = "43f70a0e57f81814a93f176079bfc5c20519dbda5b7a8f9e8062e3aa488c74b3"
QUEUE_ID = "v4-manager-flash-incremental"
QUEUE_IDENTITY_FIELDS = ("date", "market", "article_id", "source_sha256", "body_sha256",
                         "prompt_sha256", "model_id", "configuration_sha256", "rules", "role", "stage")
# One explicitly authorized resource-only transition; this is not a general configuration override.
MEMORY_TRANSITION_REF = "announcement_flash/runtime-memory-transition.json"
MEMORY_IDENTITY_TRANSITION = {'schema': 'v4.manager_workbench.authorized_memory_identity_transition.v1',
 'status': 'APPLIED_HEALTH_CEILING_VERIFIED',
 'source_job_id': '542d858cefce4f3a8e3bf9914137be68',
 'source_input_sha256': '3aea3e70130d253bc01bcf5366de5eaa17f0468b7806b01aa075943297270eaa',
 'source_result_sha256': 'fc4b53da3640cf1efc185c39f3371f8b813bcdb54ecef98eae7499afa3511cce',
 'failed_key': '9e29e0ddf85f8c19bca79b71115d1467ab6a45188ae91f4d1c1bd19dcb19e344',
 'failed_payload_sha256': '73b711f7adb5d7d39cb2d5e800e5f2b529aa0a6ccbc9a3427899bf1b54fddcec',
 'failed_attempt_sha256': 'd2b25af2f10feefaa172e963600889c1fef9facb2890833f6190d17c13b7fa8d',
 'settings_before_sha256': 'e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99',
 'settings_after_sha256': '2713eb73ceb66ee77fbfb58c52b17211305d72774b5e9412073171854ba3e631',
 'non_memory_settings_sha256': 'e577d5f3b802eb29a6cee6955e16b81c4cc603d297298208512724a28fd6b287',
 'identity_configuration_sha256': 'ff0dede69789db93f7873615987fdf16baa75a17eefa94a270223a934d8822ef',
 'execution_configuration_sha256': '366496cbccf54d21c35aa35c4d327d17a60879cc80c1a3cead145a128f55ee4c',
 'launcher_sha256': '538d1d9c7a975acbd2a043232780a0e740b5ec9dcf956839eddcbfdc1da9b4e1',
 'memory_before': {'prefill_memory_guard': True,
                   'memory_guard_tier': 'balanced',
                   'memory_guard_custom_ceiling_gb': 0.0,
                   'soft_threshold': 0.85,
                   'hard_threshold': 0.95,
                   'prefill_safe_zone_ratio': 0.8,
                   'prefill_min_chunk_tokens': 32},
 'memory_after': {'prefill_memory_guard': True,
                  'memory_guard_tier': 'custom',
                  'memory_guard_custom_ceiling_gb': 96.0,
                  'soft_threshold': 0.85,
                  'hard_threshold': 0.95,
                  'prefill_safe_zone_ratio': 0.8,
                  'prefill_min_chunk_tokens': 32},
 'effective_ceiling_bytes': 103079215104}
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
FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY = "d2564a4f3035550c78a1106914f18bdf3cba4f789ad3e77a1db7261ea346ee8c"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256 = "adac10aa1db02ffb7eee7887b922bbea87f16438125074c0d104df4a4f180148"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256 = "27a2f417eba7e18e968714119460963e077d6f6942b7021e28ea9e576a68726f"
FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256 = "fa66d4d9cd13a4c449688463ef7db959f5d4f7c6a5da160eeedf2f410a599e5a"
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,96}$")


class FlashRunError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if SAFE_CODE_RE.fullmatch(code) else "FLASH_PIPELINE_FAILED"


@contextmanager
def _cooperative_stop_signals():
    """A signal requests a boundary stop; it never interrupts a durable attempt."""
    requested = []
    previous = {}
    def request(signum, _frame):
        requested.append(signum)
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request)
        yield requested
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class _UserStop:
    def __init__(self, state_io: SafeRoot, job_id: str, signalled: list[int]):
        self.io, self.job_id, self.signalled = state_io, job_id, signalled
        self.ref = f"announcement_flash/jobs/{job_id}/stop-request.json"

    def __call__(self) -> bool:
        try:
            value = _json(self.io.read_bytes(self.ref, max_bytes=4096), "USER_STOP_REQUEST_INVALID")
        except FileNotFoundError:
            if not self.signalled:
                return False
            value = {"schema": "v4.manager_workbench.announcement_flash_stop.v1",
                     "job_id": self.job_id, "reason": "USER_REQUEST",
                     "requested_at": datetime.now(timezone.utc).isoformat()}
            _write_json(self.io, self.ref, value)
        if (not isinstance(value, dict)
                or value.get("schema") != "v4.manager_workbench.announcement_flash_stop.v1"
                or value.get("job_id") != self.job_id or value.get("reason") != "USER_REQUEST"
                or not isinstance(value.get("requested_at"), str)):
            raise FlashRunError("USER_STOP_REQUEST_INVALID")
        return True


def _user_stop_receipt() -> dict[str, str]:
    return {"failure_code": "USER_STOPPED", "stage": "USER_REQUEST",
            "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"}


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


def _source_article(row: dict[str, Any], row_index: int, capture_product: dict[str, Any], capture_ref: dict[str, str],
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
    return article


def _article(row: dict[str, Any], row_index: int, capture_product: dict[str, Any], capture_ref: dict[str, str],
             capture_io: SafeRoot, runner: Any, membership_gate: dict[str, Any]) -> dict[str, Any]:
    article = _source_article(row, row_index, capture_product, capture_ref, capture_io, runner, membership_gate)
    body, body_sha, metadata = article['article_body'], article['body_sha256'], article['article_metadata']
    unit_map = runner.build_source_unit_map(body, body_sha)
    article['fixed_fact_ledger'] = runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, metadata)
    article['_source_unit_map'] = unit_map
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


def _verify_transport_original_root(state_io: SafeRoot, input_value: dict[str, Any],
                                    plan: dict[str, Any]) -> dict[str, Any]:
    """Prove the transport origin inherits the same original root as this child."""
    try:
        root = input_value.get("resume_root")
        if not isinstance(root, dict) or set(root) != {"source_job_id", "source_input_sha256"}:
            raise ValueError("root shape")
        origin_id, origin_sha = plan.get("source_job_id"), plan.get("source_input_sha256")
        if not JOB_ID_RE.fullmatch(str(origin_id)) or not SHA_RE.fullmatch(str(origin_sha)):
            raise ValueError("origin shape")
        origin_raw = state_io.read_bytes(f"announcement_flash/jobs/{origin_id}/input.json", max_bytes=1024 * 1024)
        origin = _json(origin_raw, "FROZEN_RESUME_TRANSPORT_INPUT_BINDING_INVALID")
        expected_root = origin.get("resume_root") if isinstance(origin, dict) else None
        if expected_root is None:
            expected_root = {"source_job_id": origin_id, "source_input_sha256": origin_sha}
        if (sha(origin_raw) != origin_sha or not isinstance(origin, dict)
                or origin.get("job_id") != origin_id or root != expected_root
                or any(origin.get(field) != input_value.get(field)
                       for field in ("target_date", "cutoff", "capture_product", "membership_gate"))):
            raise ValueError("origin/root mismatch")
        original = _verify_resume_root_input(state_io, root["source_job_id"], root["source_input_sha256"],
                                               input_value["target_date"], input_value)
        if original.get("cutoff") != input_value.get("cutoff"):
            raise ValueError("cutoff mismatch")
        return origin
    except Exception as exc:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_INPUT_BINDING_INVALID") from exc


def _request_material_with_memory_identity(material: dict[str, Any], state_root: Path,
                                            plan: Any, settings_path: Path | None) -> dict[str, Any]:
    """Keep frozen request identity only for the exact authorized memory-only transition.

    Execution settings/configuration remain separately recorded and the transport
    still checks the current physical settings SHA. No queue payload is rewritten.
    """
    expected = MEMORY_IDENTITY_TRANSITION
    if not isinstance(plan, dict) or plan.get("source_job_id") != expected["source_job_id"]:
        return material
    try:
        failure = plan.get("failed_task")
        if (plan.get("source_input_sha256") != expected["source_input_sha256"]
                or plan.get("source_result_sha256") != expected["source_result_sha256"]
                or not isinstance(failure, dict) or failure.get("key") != expected["failed_key"]
                or failure.get("payload_sha256") != expected["failed_payload_sha256"]
                or failure.get("attempt_sha256") != expected["failed_attempt_sha256"]):
            raise ValueError("source binding")
        state_io = SafeRoot(state_root)
        receipt_raw = state_io.read_bytes(MEMORY_TRANSITION_REF, max_bytes=16384)
        if receipt_raw != canonical(expected) + b"\n":
            raise ValueError("authorization receipt")
        source_id = expected["source_job_id"]
        source_input_raw = state_io.read_bytes(f"announcement_flash/jobs/{source_id}/input.json", max_bytes=1024 * 1024)
        source_result_raw = state_io.read_bytes(f"announcement_flash/jobs/{source_id}/result.json", max_bytes=64 * 1024 * 1024)
        if (sha(source_input_raw) != expected["source_input_sha256"]
                or sha(source_result_raw) != expected["source_result_sha256"]):
            raise ValueError("immutable source")
        provenance = _json(source_result_raw, "MEMORY_TRANSITION_SOURCE_INVALID").get("provenance")
        if not isinstance(provenance, dict) or any(material.get(field) != provenance.get(field) for field in (
                "prompt_sha256", "model_settings_sha256", "schema_sha256", "parser_sha256", "source_code_sha256")):
            raise ValueError("non-memory request drift")
        if settings_path is None:
            raise ValueError("settings unavailable")
        settings_path = Path(settings_path)
        settings_raw = settings_path.read_bytes()
        settings = _json(settings_raw, "MEMORY_TRANSITION_SETTINGS_INVALID")
        if (sha(settings_raw) != expected["settings_after_sha256"]
                or material.get("runtime_settings_sha256") != expected["settings_after_sha256"]
                or settings.get("memory") != expected["memory_after"]
                or sha(canonical({key: value for key, value in settings.items() if key != "memory"}))
                != expected["non_memory_settings_sha256"]
                or sha((settings_path.parent.parent / "start_omlx.sh").read_bytes()) != expected["launcher_sha256"]):
            raise ValueError("physical settings drift")
        execution_material = material.get("configuration_material")
        if (not isinstance(execution_material, dict)
                or execution_material.get("runtime_settings_sha256") != expected["settings_after_sha256"]
                or material.get("configuration_sha256") != expected["execution_configuration_sha256"]
                or sha(canonical(execution_material)) != expected["execution_configuration_sha256"]
                or provenance.get("runtime_settings_sha256") != expected["settings_before_sha256"]
                or provenance.get("configuration_sha256") != expected["identity_configuration_sha256"]):
            raise ValueError("configuration fingerprint")
        identity_material = {**execution_material, "runtime_settings_sha256": expected["settings_before_sha256"]}
        if sha(canonical(identity_material)) != expected["identity_configuration_sha256"]:
            raise ValueError("inference configuration drift")
        binding = {"schema": expected["schema"], "receipt_sha256": sha(receipt_raw),
                   "source_job_id": source_id, "failed_key": expected["failed_key"],
                   "identity_runtime_settings_sha256": expected["settings_before_sha256"],
                   "execution_runtime_settings_sha256": expected["settings_after_sha256"],
                   "identity_configuration_sha256": expected["identity_configuration_sha256"],
                   "execution_configuration_sha256": expected["execution_configuration_sha256"]}
        return {**material, "configuration_sha256": expected["identity_configuration_sha256"],
                "configuration_material": identity_material,
                "execution_configuration_sha256": expected["execution_configuration_sha256"],
                "execution_configuration_material": execution_material,
                "runtime_memory_transition": binding}
    except Exception as exc:
        raise FlashRunError("AUTHORIZED_MEMORY_TRANSITION_UNVERIFIED") from exc


def _current_transport_request_material(state_root: Path, plan: Any) -> dict[str, Any]:
    helper = _load_helper()
    import batch_runner as runner
    material = _owned_request_material(helper, runner, runner.load_active_contract(
        REPO_ROOT / "v4/manager_workbench/engines/announcement.py"))
    return _request_material_with_memory_identity(material, state_root, plan,
                                                  getattr(runner, "OMLX_SETTINGS_PATH", None))


def _test_legacy_gate(binding: dict[str, Any], model_id: str) -> Path:
    """Verify an explicitly frozen, existing physical gate; never create one."""
    try:
        codes = binding.get('code_identity')
        if (not isinstance(codes, dict) or not {'ops/run_manager_flash_announcements.py',
                'infrastructure/model_execution_gate.py'}.issubset(codes)):
            raise ValueError('code identity')
        code_io = SafeRoot(REPO_ROOT)
        for ref, expected in codes.items():
            if not SHA_RE.fullmatch(str(expected)) or sha(code_io.read_bytes(ref)) != expected:
                raise ValueError('code drift')
        root = Path(binding['legacy_queue_root'])
        if not root.is_absolute() or '..' in root.parts:
            raise ValueError('path')
        lock = root / 'locks' / ('model-' + sha(model_id.encode()) + '.lock')
        if any(p.is_symlink() for p in (lock, *lock.parents)):
            raise ValueError('symlink')
        meta = lock.stat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_dev != binding['device']
                or meta.st_ino != binding['inode'] or sha(lock.read_bytes()) != binding['sha256']):
            raise ValueError('identity')
        return root
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FlashRunError('TEST_LEGACY_GATE_BINDING_CHANGED') from exc


def _new_only_queue(queue_module: Any, queue_root: Path, model_id: str, *,
                    binding_guard: Callable[[], None] | None = None, recover_running: bool = False,
                    legacy_gate: dict[str, Any] | None = None):
    from infrastructure.model_execution_gate import create_business_queue, frozen_file_guard
    guard = binding_guard or frozen_file_guard({Path(__file__): sha(Path(__file__).read_bytes())})
    legacy_root = queue_root
    if legacy_gate is not None:
        legacy_root = _test_legacy_gate(legacy_gate, model_id)
        original_guard = guard
        def guard():
            _test_legacy_gate(legacy_gate, model_id)
            original_guard()
    return create_business_queue(queue_module, queue_root, QUEUE_ID, model_id,
                                 legacy_queue_root=legacy_root, binding_guard=guard,
                                 recover_running=recover_running)


def _isolated_preparation_guard(args: Any, binding: dict[str, Any], path: Path, binding_sha: str):
    """A closed, read-only authorization for the existing preprocessing branch.

    The binding is sealed after its file inventory (which excludes the binding
    itself). It authorizes no execution, resume, model lock or alternate producer.
    """
    marker = binding['isolated_preparation']
    if (not args.preprocess_only or any((args.execute_preprocessed_report_sha256, args.execution_phase,
            args.extension_sha256, args.resume_pending, args.resume_frozen_batch, args.resume_action,
            args.resume_dry_run, args.resume_source_job_id, args.source_input_sha256,
            args.source_progress_sha256, args.source_queue_state_sha256, args.materialize_saved_partial,
            args.failure_code)) or args.max_model_calls is not None or not args.shared_root):
        raise FlashRunError('ISOLATED_PREPARATION_MODE_INVALID')
    if (not isinstance(marker, dict) or marker.get('schema') != 'v4.manager_workbench.announcement_isolated_preparation.v1'
            or marker.get('mode') != 'PREPARE_ONLY'
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(marker.get('test_run_id', '')))):
        raise FlashRunError('ISOLATED_PREPARATION_BINDING_INVALID')

    def normalized(value):
        p = Path(value)
        if (not p.is_absolute() or str(p) != str(value) or '..' in p.parts
                or any(part.is_symlink() for part in (p, *p.parents))):
            raise FlashRunError('ISOLATED_PREPARATION_PATH_INVALID')
        return p

    roots = marker['roots']
    if not isinstance(roots, dict) or set(roots) != {'isolation', 'state', 'capture', 'shared', 'config'}:
        raise FlashRunError('ISOLATED_PREPARATION_ROOTS_INVALID')
    frozen = marker['frozen_files']
    identity = marker['request_identity']
    fields = {'model_id', 'configuration_sha256', 'prompt_sha256', 'schema_sha256',
              'runtime_settings_sha256', 'model_settings_sha256', 'runtime_limits', 'max_completion_tokens'}
    if (not isinstance(identity, dict) or set(identity) != fields or identity['model_id'] != 'qwen3_8_flash_next'
            or not isinstance(frozen, dict) or not frozen or str(path) in frozen
            or sha(canonical(frozen)) != marker['frozen_files_sha256']):
        raise FlashRunError('ISOLATED_PREPARATION_INVENTORY_INVALID')

    def verify(material=None, runtime=None):
        binding_path = normalized(path)
        if sha(SafeRoot(binding_path.parent).read_bytes(binding_path.name)) != binding_sha:
            raise FlashRunError('ISOLATED_PREPARATION_BINDING_CHANGED')
        paths = {role: normalized(value) for role, value in roots.items()}
        protected = (Path('/Users/lexi/Desktop/学习/v4_app'), Path('/Users/lexi/Desktop/学习/v3_system'),
            Path('/Users/lexi/Library/Application Support/com.lexi.v4.local'),
            Path('/Users/lexi/Library/Application Support/com.lexi.v35.local'))
        if any(p == q or p in q.parents or q in p.parents for p in paths.values() for q in protected):
            raise FlashRunError('ISOLATED_PREPARATION_PRODUCTION_ROOT')
        data_roots = [paths[k] for k in ('state', 'capture', 'shared', 'config')]
        legacy = normalized(binding['legacy_queue_root'])
        if (any(paths['isolation'] not in p.parents for p in data_roots)
                or any(p == q or p in q.parents or q in p.parents for i, p in enumerate(data_roots) for q in data_roots[i+1:])
                or any(p == legacy or p in legacy.parents or legacy in p.parents for p in data_roots)
                or any(str(paths[k]) != getattr(args, k + '_root') for k in ('state', 'capture', 'shared'))):
            raise FlashRunError('ISOLATED_PREPARATION_ROOTS_INVALID')
        for filename, expected in frozen.items():
            source = normalized(filename)
            if not SHA_RE.fullmatch(str(expected)) or sha(SafeRoot(source.parent).read_bytes(source.name, max_bytes=256*1024*1024)) != expected:
                raise FlashRunError('ISOLATED_PREPARATION_SOURCE_CHANGED')
        _test_legacy_gate(binding, 'qwen3_8_flash_next')
        input_path = paths['state'] / f'announcement_flash/jobs/{args.job_id}/input.json'
        input_raw = SafeRoot(input_path.parent).read_bytes(input_path.name, max_bytes=1024*1024)
        value = _json(input_raw, 'FLASH_INPUT_INVALID')
        if (not JOB_ID_RE.fullmatch(args.job_id) or marker['job_id'] != args.job_id
                or value.get('schema') != 'v4.manager_workbench.announcement_flash_input.v1'
                or value.get('job_id') != args.job_id or marker['target_date'] != value.get('target_date')
                or not re.fullmatch(r'\d{8}', str(marker['target_date'])) or sha(input_raw) != marker['input_sha256']):
            raise FlashRunError('ISOLATED_PREPARATION_INPUT_CHANGED')
        from v4.manager_workbench.announcement_classification import frozen_policy
        if frozen_policy(value) is None:
            raise FlashRunError('CLASSIFICATION_POLICY_REQUIRED_FOR_NEW_ENTRY')
        capture = value['capture_product']
        if not isinstance(capture, dict) or not re.fullmatch(r'products/[a-f0-9]{64}\.json', str(capture.get('artifact_ref', ''))):
            raise FlashRunError('CAPTURE_PRODUCT_REFERENCE_INVALID')
        required = {str(input_path): marker['input_sha256'],
                    str(paths['capture'] / capture['artifact_ref']): capture['sha256']}
        required.update({str(REPO_ROOT / ref): digest for ref, digest in binding['code_identity'].items()})
        for role, key in (('runtime', 'runtime_settings_sha256'), ('model', 'model_settings_sha256')):
            required[str(normalized(marker['settings_paths'][role]))] = identity[key]
        if any(frozen.get(ref) != expected for ref, expected in required.items()):
            raise FlashRunError('ISOLATED_PREPARATION_INVENTORY_INCOMPLETE')
        if material is not None:
            config = material.get('configuration_material')
            if (not isinstance(config, dict) or sha(canonical(config)) != material.get('configuration_sha256')
                    or config.get('model_id') != runtime.MODEL_ID or runtime.MODEL_ID != 'qwen3_8_flash_next'
                    or type(config.get('max_completion_tokens')) is not int or config['max_completion_tokens'] != 32768
                    or any(key in material and (type(material[key]) is not type(config[key]) or material[key] != config[key])
                           for key in ('model_id', 'max_completion_tokens'))
                    or canonical(config.get('runtime_limits')) != canonical(material.get('runtime_limits'))
                    or not isinstance(config.get('runtime_limits'), dict)
                    or type(config['runtime_limits'].get('completion_max_tokens')) is not int
                    or config['runtime_limits']['completion_max_tokens'] != config['max_completion_tokens']
                    or any(config.get(key) != material.get(key) for key in ('runtime_settings_sha256', 'model_settings_sha256'))
                    or config['runtime_limits'].get('model_settings_sha256') != material.get('model_settings_sha256')
                    or sha(material['prompt'].encode()) != material.get('prompt_sha256')
                    or sha(canonical(material['schema'])) != material.get('schema_sha256')
                    or material['schema_sha256'] != config.get('request_schema_sha256')
                    or sha(canonical({'json': material['schema']})) != material.get('schema_wrapper_sha256')
                    or material['schema_wrapper_sha256'] != config.get('request_schema_wrapper_sha256')):
                raise FlashRunError('ISOLATED_PREPARATION_REQUEST_CHANGED')
            observed = {key: material.get(key) for key in fields - {'model_id', 'max_completion_tokens'}}
            observed.update(model_id=config['model_id'], max_completion_tokens=config['max_completion_tokens'])
            if (canonical(observed) != canonical(identity) or str(runtime.OMLX_SETTINGS_PATH) != marker['settings_paths']['runtime']
                    or str(runtime.OMLX_MODEL_SETTINGS_PATH) != marker['settings_paths']['model']):
                raise FlashRunError('ISOLATED_PREPARATION_REQUEST_CHANGED')
    verify()
    return verify


def _announcement_execution_guard(runner: Any, request_material: dict[str, Any]) -> Callable[[], None]:
    from infrastructure.local_document_model import PINNED_SOURCE_SHA256
    from infrastructure.model_execution_gate import frozen_file_guard
    files = {(PIPELINE_ROOT / name if name != 'recent_day_freeze.py' else
              PIPELINE_ROOT / 'evidence/recent-day-20261014/recent_day_freeze.py'): digest
             for name, digest in PINNED_SOURCE_SHA256.items()}
    files.update({Path(runner.OMLX_SETTINGS_PATH): request_material['runtime_settings_sha256'],
                  Path(runner.OMLX_MODEL_SETTINGS_PATH): request_material['model_settings_sha256']})
    for name, digest in request_material['source_code_sha256'].items():
        path = (PIPELINE_ROOT / 'evidence/recent-day-20261014/recent_day_freeze.py'
                if name == 'recent_day_freeze.py' else
                REPO_ROOT / name if '/' in name else PIPELINE_ROOT / name)
        files[path] = digest
    for path in (Path(__file__), REPO_ROOT / 'infrastructure/model_execution_gate.py'):
        files[path] = sha(path.read_bytes())
    return frozen_file_guard(files)


def _owned_request_material(helper: Any, runner: Any, contract: Any, *, semantic_contract: bool = True) -> dict[str, Any]:
    """Reuse the frozen request builder without relabeling its canonical source.

    The external builder pins its own canonical prompt/schema source. The owned
    validator is a separate dependency and must have the same wire contract;
    its real SHA participates in new processing identity, never a forged SHA.
    """
    request_contract = runner.load_active_contract()
    for field in ("prompt_version", "read_prompt", "reader_schema"):
        if getattr(request_contract, field, None) != getattr(contract, field, None):
            raise FlashRunError("OWNED_READER_WIRE_CONTRACT_DRIFT")
    material = helper._full_day_request_material(request_contract)
    validation_sha = getattr(contract, "source_sha256", None)
    if not SHA_RE.fullmatch(str(validation_sha)):
        raise FlashRunError("OWNED_READER_CONTRACT_SHA_INVALID")
    config = {**material["configuration_material"], "validation_contract_sha256": validation_sha}
    if semantic_contract:
        from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
        prompt = material["prompt"] + "\n\n" + SEMANTIC_CONTRACT
        config = {**config, "semantic_contract_version": SEMANTIC_CONTRACT_VERSION,
                  "base_prompt_sha256": material["prompt_sha256"], "system_prompt_sha256": sha(prompt.encode())}
        material = {**material, "prompt": prompt, "prompt_sha256": sha(prompt.encode())}
    return {**material, "configuration_material": config,
            "configuration_sha256": sha(canonical(config)),
            "validation_contract_sha256": validation_sha,
            "source_code_sha256": {**material["source_code_sha256"],
                                   "v4/manager_workbench/engines/announcement.py": validation_sha}}


def _transport_canary_receipt_candidate(resume: Any, plan: dict[str, Any],
                                       jobs: dict[str, Any]) -> dict[str, Any] | None:
    """Recognize only the saved one-call success or its ordinary-readback failure."""
    if (not isinstance(resume, dict) or not isinstance(jobs, dict)
            or not isinstance(plan.get("failed_task"), dict)):
        return None
    key = resume.get("canary_key")
    if (not isinstance(key, str) or not SHA_RE.fullmatch(key)
            or resume.get("model_calls") != 1 or resume.get("canary_model_calls") != 1
            or resume.get("max_model_calls") != 1 or resume.get("dispatched_keys") != [key]
            or resume.get("canary_status") != "SUCCEEDED"):
        return None
    validation = resume.get("canary_validation")
    if (resume.get("canary_passed") is True and isinstance(validation, dict)
            and validation.get("status") == "PASS" and validation.get("key") == key):
        return validation
    if (resume.get("canary_passed") is not False or resume.get("continue_eligible") is not False
            or validation != {"status": "FAIL", "key": key,
                              "failure_code": "FROZEN_RESUME_TRANSPORT_CANARY_RESULT_UNVERIFIED"}):
        return None
    job = jobs.get(key)
    if not isinstance(job, dict):
        return None
    return {"status": "PASS", "key": key,
            "binding_sha256": _transport_recovery_canary_binding(plan)["binding_sha256"],
            "validated_sha256": job.get("validated_sha256"), "raw_sha256": job.get("raw_sha256")}


def _validated_transport_canary_result(queue_root: Path, job: dict[str, Any],
                                       payload: dict[str, Any], plan: dict[str, Any], *,
                                       validator: Callable[[Any, Any], dict[str, Any]] | None = None
                                       ) -> dict[str, Any]:
    """Read and strictly replay an ordinary canary; never dispatch or persist anything."""
    try:
        key = job.get("idempotency_key")
        attempts = job.get("attempts")
        attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
        if (not isinstance(key, str) or not SHA_RE.fullmatch(key)
                or job.get("status") != "SUCCEEDED" or job.get("queue_id") != QUEUE_ID
                or job.get("attempt_count") != 1 or job.get("max_attempts") != 1
                or payload.get("queue_task_kind") is not None
                or payload.get("role") != "announcement_reader"
                or job.get("identity") != {field: payload.get(field) for field in QUEUE_IDENTITY_FIELDS}
                or sha(canonical(job.get("identity"))) != key
                or _queue_payload(queue_root, job) != payload
                or not isinstance(attempt, dict) or attempt.get("status") != "SUCCEEDED"
                or attempt.get("number") != 1 or attempt.get("error") is not None):
            raise ValueError("binding")
        for role, suffix in (("raw", "raw"), ("validated", "validated.json")):
            ref = f"jobs/{key}/attempt-0001.{suffix}"
            if (job.get(role + "_path") != ref or attempt.get(role + "_path") != ref
                    or attempt.get(role + "_sha256") != job.get(role + "_sha256")):
                raise ValueError("reference")
        saved, validated_sha, raw_sha = _read_internal_validated_result(queue_root, job)
        raw_bytes = (queue_root / job["raw_path"]).read_bytes()
        if sha(raw_bytes) != raw_sha or attempt.get("raw_length_bytes") != len(raw_bytes):
            raise ValueError("length")
        rows = saved.get("results")
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        output = row.get("reader_output") if isinstance(row, dict) else None
        if (not isinstance(output, dict) or row.get("article_id") != payload.get("article_id")
                or output.get("source_sha256") != payload.get("source_sha256")
                or output.get("body_sha256") != payload.get("body_sha256")
                or payload.get("transport_recovery_binding") != _transport_recovery_canary_binding(plan)):
            raise ValueError("ordinary result")
        if validator is None:
            helper = _load_helper()
            import announcement_queue as queue_module
            import batch_runner as runner
            import build_length_canary as length_canary
            contract = runner.load_active_contract(REPO_ROOT / "v4/manager_workbench/engines/announcement.py")
            material = _owned_request_material(helper, runner, contract)
            material = _request_material_with_memory_identity(
                material, queue_root.parent.parent, plan, getattr(runner, "OMLX_SETTINGS_PATH", None))
            if any(payload.get(field) != material.get(field) for field in (
                    "prompt_sha256", "configuration_sha256", "workflow_profile", "citation_protocol")):
                raise ValueError("configuration drift")
            validator = _validator(queue_module, runner, contract, material, length_canary)
        projected = validator(SimpleNamespace(payload=payload, idempotency_key=key),
                              _json(raw_bytes, "TRANSPORT_CANARY_RAW_INVALID"))
        if sha(canonical(projected)) != validated_sha:
            raise ValueError("strict replay")
        return {"status": "PASS", "key": key,
                "binding_sha256": _transport_recovery_canary_binding(plan)["binding_sha256"],
                "validated_sha256": validated_sha, "raw_sha256": raw_sha}
    except Exception as exc:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_RESULT_UNVERIFIED") from exc


def _load_frozen_resume_plan(state_root: Path, root_job_id: str, article: dict[str, Any],
                            unit_map: dict[str, Any], chunks: Any) -> tuple[dict[str, Any], str]:
    """Load the original immutable part plan so a prompt/schema repair keeps its part identities."""
    article_id = article.get("article_id") if isinstance(article, dict) else None
    if (not isinstance(root_job_id, str) or not JOB_ID_RE.fullmatch(root_job_id)
            or not isinstance(article_id, str)
            or not re.fullmatch(r"EASTMONEY:[A-Za-z0-9_-]{1,128}", article_id)):
        raise FlashRunError("FROZEN_RESUME_PLAN_BINDING_INVALID")
    plan_root = (state_root / "announcement_flash" / "jobs" / root_job_id / "long-body").resolve()
    state_base = state_root.resolve()
    if not plan_root.is_relative_to(state_base) or not plan_root.is_dir():
        raise FlashRunError("FROZEN_RESUME_PLAN_ARTIFACTS_MISSING")
    prefix = article_id.replace(":", "_") + "-"
    plan_paths = sorted(path for path in plan_root.iterdir()
                        if path.is_file() and path.name.startswith(prefix) and path.name.endswith(".json"))
    if len(plan_paths) != 1:
        raise FlashRunError("FROZEN_RESUME_PLAN_ARTIFACTS_AMBIGUOUS")
    try:
        raw = plan_paths[0].read_bytes()
        plan = _json(raw, "FROZEN_RESUME_PLAN_ARTIFACT_INVALID")
    except (OSError, FlashRunError) as exc:
        raise FlashRunError("FROZEN_RESUME_PLAN_ARTIFACT_INVALID") from exc
    ledger = article.get("fixed_fact_ledger")
    if (not isinstance(plan, dict) or plan.get("schema") != chunks.PART_PLAN_SCHEMA
            or plan.get("article_id") != article_id
            or plan.get("source_sha256") != article.get("source_sha256")
            or plan.get("body_sha256") != article.get("body_sha256")
            or plan.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")
            or not isinstance(ledger, dict)
            or plan.get("fixed_fact_ledger_sha256") != ledger.get("ledger_sha256")
            or plan_paths[0].name != f"{article_id.replace(':', '_')}-{plan.get('plan_sha256')}.json"):
        raise FlashRunError("FROZEN_RESUME_PLAN_BINDING_INVALID")
    try:
        chunks.verify_part_coverage(article.get("article_body"), article.get("body_sha256"), unit_map, plan)
    except (TypeError, ValueError) as exc:
        raise FlashRunError("FROZEN_RESUME_PLAN_COVERAGE_INVALID") from exc
    return plan, f"long-body/{plan_paths[0].name}"


def _find_frozen_source_part(payload: dict[str, Any], queue: Any, queue_root: Path
                             ) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """Find one exact saved source-plan part; never infer ownership from article/date alone."""
    descriptor = payload.get("part_descriptor")
    source_rules_suffix = payload.get("frozen_source_rules_suffix")
    if (not isinstance(descriptor, dict) or not isinstance(source_rules_suffix, str)
            or not re.fullmatch(
                r"\+long-body-part:v1\+plan:[0-9a-f]{64}\+part:[0-9]+/[0-9]+"
                r"\+part-sha:[0-9a-f]{64}\+part-prompt:[0-9a-f]{64}"
                r"\+part-addendum:[0-9a-f]{64}", source_rules_suffix)):
        raise FlashRunError("FROZEN_RESUME_PART_BINDING_INVALID")
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else None
    if not isinstance(jobs, dict):
        raise FlashRunError("FROZEN_RESUME_QUEUE_STATE_INVALID")
    matches = []
    for key, item in jobs.items():
        if (not isinstance(item, dict) or item.get("queue_id") != QUEUE_ID
                or item.get("idempotency_key") != key or not isinstance(item.get("identity"), dict)):
            continue
        identity = item["identity"]
        if (identity.get("article_id") != payload.get("article_id")
                or identity.get("source_sha256") != payload.get("source_sha256")
                or identity.get("body_sha256") != payload.get("body_sha256")):
            continue
        try:
            saved_payload = _queue_payload(queue_root, item)
        except FlashRunError:
            continue
        saved_descriptor = saved_payload.get("part_descriptor")
        if (saved_payload.get("queue_task_kind") == "announcement_reader_part"
                and saved_payload.get("stage") == payload.get("stage")
                and saved_payload.get("article_id") == payload.get("article_id")
                and saved_payload.get("source_sha256") == payload.get("source_sha256")
                and saved_payload.get("body_sha256") == payload.get("body_sha256")
                and isinstance(saved_payload.get("rules"), str)
                and saved_payload["rules"].endswith(source_rules_suffix)
                and saved_payload.get("source_unit_map_sha256") == payload.get("source_unit_map_sha256")
                and saved_payload.get("chunk_plan_sha256") == payload.get("chunk_plan_sha256")
                and isinstance(saved_descriptor, dict)
                and all(saved_descriptor.get(field) == descriptor.get(field) for field in (
                    "part_index", "part_count", "part_sha256", "start_source_unit_id",
                    "end_source_unit_id", "source_unit_ids", "unit_start_index", "unit_end_index"))):
            matches.append((key, item, saved_payload))
    if len(matches) > 1:
        raise FlashRunError("FROZEN_RESUME_PART_IDENTITY_AMBIGUOUS")
    return matches[0] if matches else None


def _frozen_resume_orphans(long_body_specs: dict[str, dict[str, Any]], queue: Any,
                           queue_root: Path, *, target_date: str,
                           dry_run: bool, recover_orphans: bool = True
                           ) -> tuple[set[str], set[str], dict[str, str]]:
    """Recover only the single frozen orphan after proving the model owner is gone."""
    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else None
    if not isinstance(jobs, dict):
        raise FlashRunError("FROZEN_RESUME_QUEUE_STATE_INVALID")
    payloads: dict[str, dict[str, Any]] = {}
    for spec in long_body_specs.values():
        for payload in spec.get("part_payloads", []):
            if isinstance(payload, dict):
                saved = _find_frozen_source_part(payload, queue, queue_root)
                if saved is not None:
                    payloads[saved[0]] = payload
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
    if not recover_orphans:
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


def _current_frozen_resume_payload_valid(payload: dict[str, Any], membership_gate: Any,
                                         frozen_resume_binding: Any) -> bool:
    """Apply frozen cutoff, authority, capture-origin and issuer checks to a saved-plan repair."""
    if not isinstance(frozen_resume_binding, dict) or not isinstance(membership_gate, dict):
        return False
    metadata = payload.get("article_metadata")
    target_text = frozen_resume_binding.get("target_date")
    cutoff_text = frozen_resume_binding.get("cutoff")
    authority = membership_gate.get("authority_sha256")
    if (membership_gate.get("schema") != "v4.manager_workbench.announcement_connect_membership.v1"
            or membership_gate.get("status") != "VERIFIED"
            or membership_gate.get("market") != "HK_CONNECT"
            or membership_gate.get("target_date") != target_text
            or membership_gate.get("cutoff") != cutoff_text
            or not isinstance(target_text, str) or not re.fullmatch(r"[0-9]{8}", target_text)
            or not isinstance(cutoff_text, str)
            or not JOB_ID_RE.fullmatch(str(frozen_resume_binding.get("source_job_id", "")))
            or not SHA_RE.fullmatch(str(frozen_resume_binding.get("source_input_sha256", "")))
            or not SHA_RE.fullmatch(str(authority))
            or frozen_resume_binding.get("membership_authority_sha256") != authority
            or not isinstance(metadata, dict)):
        return False
    body = payload.get("article_body")
    body_sha = payload.get("body_sha256")
    source_sha = payload.get("source_sha256")
    if (not isinstance(body, str) or not body
            or not isinstance(body_sha, str) or not SHA_RE.fullmatch(body_sha)
            or sha(body.encode("utf-8")) != body_sha
            or not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha)
            or payload.get("market") != "HK"):
        return False
    try:
        cutoff = datetime.fromisoformat(cutoff_text)
        target = datetime.strptime(target_text, "%Y%m%d").date()
        available = datetime.fromisoformat(str(metadata.get("available_at", "")))
        publication = datetime.fromisoformat(str(metadata.get("publication_date", ""))).date()
    except ValueError:
        return False
    if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or available.tzinfo is None or available.utcoffset() is None
            or available > cutoff or publication > target
            or payload.get("date") != publication.isoformat()):
        return False
    capture_sha = frozen_resume_binding.get("capture_product_sha256")
    if (metadata.get("article_membership_status") != "IN"
            or metadata.get("membership_authority_sha256") != authority
            or not SHA_RE.fullmatch(str(capture_sha))
            or _capture_origin_metadata_sha(metadata) != capture_sha):
        return False
    gate_codes = membership_gate.get("codes")
    issuer_codes = metadata.get("source_issuer_codes")
    issuer_membership = metadata.get("source_issuer_membership")
    if (not isinstance(gate_codes, list) or not isinstance(issuer_codes, list) or not issuer_codes
            or not isinstance(issuer_membership, list) or len(issuer_membership) != len(issuer_codes)):
        return False
    codes = [row.get("code") for row in issuer_codes if isinstance(row, dict)]
    members = [row.get("code") for row in issuer_membership if isinstance(row, dict)]
    if (len(codes) != len(issuer_codes) or set(codes) != set(members)
            or not set(codes).issubset(set(gate_codes))
            or any(row.get("membership_status") != "IN" or row.get("market") != "HK_CONNECT"
                   or row.get("authority_sha256") != authority for row in issuer_membership)):
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
                                validator: Callable[[Any, Any], dict[str, Any]] | None = None,
                                source_bound_versions: bool = False) -> dict[str, Any]:
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
        seen_key = (article_id, identity.get("source_sha256"), identity.get("body_sha256")) if source_bound_versions else article_id
        previous_semantic = seen_articles.get(seen_key)
        if previous_semantic is not None:
            if previous_semantic == semantic:
                duplicate_count += 1
            else:
                conflicts.append({"article_id": article_id,
                                  "symbol": payload.get("article_metadata", {}).get("symbol"),
                                  "title": payload.get("article_metadata", {}).get("title"),
                                  "failure_code": "DUPLICATE_ARTICLE_IDENTITY_CONFLICT"})
            continue
        seen_articles[seen_key] = semantic
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
            # A completed HTTP request rejected for this input does not mean the
            # model service is unavailable. Keep authentication/5xx/network errors global.
            http_rejection = re.fullmatch(r"CHAT_HTTP_STATUS:(400|413|422)", str(exc))
            if isinstance(exc, runner.TransportError) and http_rejection:
                stable_code = "REQUEST_HTTP_" + http_rejection.group(1)
                if partial:
                    try:
                        response = json.loads(partial)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        response = None
                    error = response.get("error") if isinstance(response, dict) else None
                    if isinstance(error, dict):
                        if error.get("code") in {"invalid_api_key", "authentication_error", "unauthorized", "permission_denied"}:
                            stable_code = "MODEL_AUTHENTICATION_FAILED"
                        elif (error.get("code") == "prefill_memory_exceeded"
                              and http_rejection.group(1) == "400"):
                            stable_code = "PREFILL_MEMORY_EXCEEDED"
            raise queue_module.ExecutorFailure(stable_code, code=stable_code, raw_response=partial) from None
        transport.finish_job(status="RESPONSE_RECEIVED", completion=completion)
        if not completion.final_text:
            raise queue_module.ExecutorFailure("EMPTY_MODEL_OUTPUT", code="EMPTY_MODEL_OUTPUT", raw_response=b"")
        return completion.final_text
    return execute


_SINGLE_REQUEST_EXECUTOR_FAILURES = {
    "REQUEST_HTTP_400", "REQUEST_HTTP_413", "REQUEST_HTTP_422",
    "PREFILL_MEMORY_EXCEEDED", "EMPTY_MODEL_OUTPUT",
}


_QUEUE_INTEGRITY_FAILURE_STAGES = {"input_read", "raw_contract", "raw_persist", "result_persist", "validator_output"}
_QUEUE_INTEGRITY_FAILURE_CODES = {
    "INPUT_READ_ERROR", "RAW_RESPONSE_REQUIRED", "RAW_PERSIST_ERROR",
    "RESULT_PERSIST_ERROR", "INVALID_VALIDATOR_OUTPUT",
}


def _dispatch_pending_queue_keys(queue: Any, executor: Any, validator: Any, keys: set[str], *,
                                  completed: int, max_model_calls: int | None,
                                  dispatched_keys: list[str], on_result: Callable[[int], None],
                                  stop_requested: Callable[[], bool] = lambda: False
                                  ) -> tuple[int, dict[str, Any] | None]:
    """Advance past failed inputs once; stop only when execution itself is unavailable."""
    while keys:
        if stop_requested():
            return completed, _user_stop_receipt()
        if max_model_calls is not None and completed >= max_model_calls:
            break
        result = queue.run_next(executor, validator, idempotency_keys=keys, wait_for_model_slot=False)
        if result is None:
            break
        completed += 1
        key = result.get("idempotency_key")
        if isinstance(key, str):
            dispatched_keys.append(key)
        latest = queue._load_state().get("jobs", {}).get(key, {})
        attempt = (latest.get("attempts") or [{}])[-1]
        error = attempt.get("error") if isinstance(attempt, dict) else None
        stage = error.get("stage") if isinstance(error, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if (result.get("status") == "FAILED"
                and (stage in _QUEUE_INTEGRITY_FAILURE_STAGES or code in _QUEUE_INTEGRITY_FAILURE_CODES
                     or (stage == "executor" and code not in _SINGLE_REQUEST_EXECUTOR_FAILURES))):
            return completed, {"failure_code": code if isinstance(code, str) else "FLASH_SYSTEM_FAILURE",
                               "stage": stage, "attempt": latest.get("attempt_count"),
                               "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"}
        on_result(completed)
        if stop_requested():
            return completed, _user_stop_receipt()
    return completed, None


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
    root_job_id = binding.get("resume_root_job_id")
    root_input_sha256 = binding.get("resume_root_input_sha256")
    if (root_job_id is not None or root_input_sha256 is not None):
        if (not isinstance(root_job_id, str) or not JOB_ID_RE.fullmatch(root_job_id)
                or not isinstance(root_input_sha256, str) or not SHA_RE.fullmatch(root_input_sha256)
                or binding.get("root_batch_job_id") != root_job_id):
            return False
    binding_material = dict(binding)
    binding_sha256 = binding_material.pop("binding_sha256", None)
    return (isinstance(binding_sha256, str) and SHA_RE.fullmatch(binding_sha256) is not None
            and sha(canonical(binding_material)) == binding_sha256)


def _validator(queue_module: Any, runner: Any, contract: Any, request_material: dict[str, Any], length_canary: Any):
    def validate(job: Any, parsed: Any) -> dict[str, Any]:
        payload = job.payload
        try:
            _risk_extract_guard(payload, parsed, request_material, runner)
        except FlashRunError as exc:
            raise queue_module.ValidationRejected(exc.code, code=exc.code) from None
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
                        output, chunks.empty_reader_fixed_fields_schema(
                            runner.build_simple_reader_wire_schema(
                                contract, request_material["citation_protocol"]))),
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
                        output, chunks.empty_reader_fixed_fields_schema(
                            runner.build_simple_reader_wire_schema(
                                contract, request_material["citation_protocol"]))),
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
                citation_protocol=request_material["citation_protocol"],
                preserve_model_changes=task_kind != "announcement_reader_synthesis",
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
        "frozen_resume_binding",
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
                         hard_prompt_token_cap: int,
                         frozen_resume_binding: dict[str, Any] | None = None
                         ) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Make one source-complete validator-feedback version without changing the failed queue item."""
    from v4.manager_workbench import announcement_chunks as chunks

    if (failed_job.get("status") != "FAILED" or failed_job.get("attempt_count") != 1
            or failed_job.get("max_attempts") != 1 or failed_job.get("queue_id") != QUEUE_ID
            or type(hard_prompt_token_cap) is not int or hard_prompt_token_cap < 1
            or hard_prompt_token_cap > chunks.SYNTHESIS_TOKEN_CAP
            or _part_prompt_hard_cap(payload, chunks) != hard_prompt_token_cap
            or not (_current_frozen_resume_payload_valid(payload, membership_gate, frozen_resume_binding)
                    if frozen_resume_binding is not None else
                    _current_recovery_payload_valid(payload, recovery_lock, membership_gate, resume_cutoff))):
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
    frozen_resume_binding = frozen_resume_binding or {}
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
        "target_date": (frozen_resume_binding.get("target_date") if frozen_resume_binding else
                        recovery_lock.get("target_date")),
        "cutoff": (frozen_resume_binding.get("cutoff") if frozen_resume_binding else
                   recovery_lock.get("cutoff")),
        "root_batch_job_id": (frozen_resume_binding.get("source_job_id") if frozen_resume_binding else
                              recovery_lock.get("root_batch_job_id")),
        "parent_job_id": recovery_lock.get("parent_job_id") if isinstance(recovery_lock, dict) else None,
        "row_manifest_sha256": recovery_lock.get("row_manifest_sha256") if isinstance(recovery_lock, dict) else None,
        "capture_product_sha256": (frozen_resume_binding.get("capture_product_sha256") if frozen_resume_binding else
                                   recovery_lock.get("capture_product_sha256")),
        "resume_root_job_id": frozen_resume_binding.get("source_job_id") if frozen_resume_binding else None,
        "resume_root_input_sha256": (frozen_resume_binding.get("source_input_sha256")
                                      if frozen_resume_binding else None),
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
        "structured_output_schema": chunks.empty_reader_fixed_fields_schema(
            payload.get("structured_output_schema")),
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
                             runner: Any = None, contract: Any = None,
                             request_material: dict[str, Any] | None = None,
                             resume_action: str | None = None,
                             legacy_failed_canary: dict[str, Any] | None = None,
                             saved_canary_key: str | None = None,
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
    saved_canary_job = None
    saved_canary_payload = None
    if resume_frozen_batch and resume_action == "CONTINUE":
        state = queue._load_state()
        jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        saved_canary_job = jobs.get(saved_canary_key) if isinstance(jobs, dict) else None
        if (not isinstance(saved_canary_key, str) or not SHA_RE.fullmatch(saved_canary_key)
                or not isinstance(saved_canary_job, dict)
                or saved_canary_job.get("status") != "SUCCEEDED"):
            raise FlashRunError("FROZEN_RESUME_CANARY_QUEUE_STATE_INVALID")
        saved_canary_payload = _queue_payload(queue_root, saved_canary_job)
    for article_id, spec in long_body_specs.items():
        spec["part_keys"] = []
        spec["part_records"] = []
        for payload in spec["part_payloads"]:
            base_binding_failure = None
            source_part = _find_frozen_source_part(payload, queue, queue_root) if resume_frozen_batch else None
            if resume_frozen_batch and source_part is not None:
                base_key, saved_base, frozen_source_payload = source_part
            else:
                base_key = _stable_queue_identity(queue, payload)
                before_state = queue._load_state()
                before_jobs = before_state.get("jobs", {}) if isinstance(before_state, dict) else {}
                saved_base = before_jobs.get(base_key) if isinstance(before_jobs, dict) else None
                frozen_source_payload = None
            descriptor = payload.get("part_descriptor") if isinstance(payload.get("part_descriptor"), dict) else {}
            canary_descriptor = (saved_canary_payload.get("part_descriptor")
                                 if isinstance(saved_canary_payload, dict) else None)
            canary_part_reused = bool(
                isinstance(saved_canary_payload, dict) and isinstance(canary_descriptor, dict)
                and saved_canary_payload.get("article_id") == payload.get("article_id")
                and saved_canary_payload.get("source_sha256") == payload.get("source_sha256")
                and saved_canary_payload.get("body_sha256") == payload.get("body_sha256")
                and saved_canary_payload.get("source_unit_map_sha256") == payload.get("source_unit_map_sha256")
                and saved_canary_payload.get("chunk_plan_sha256") == payload.get("chunk_plan_sha256")
                and all(canary_descriptor.get(field) == descriptor.get(field) for field in (
                    "part_index", "part_count", "part_sha256", "start_source_unit_id",
                    "end_source_unit_id", "source_unit_ids", "unit_start_index", "unit_end_index"))
                and saved_canary_payload.get("frozen_resume_binding") == spec.get("frozen_resume_binding"))
            historical_conflict = (_historical_success_part_conflict(payload, base_key, queue, queue_root)
                                   if resume_frozen_batch and isinstance(saved_base, dict)
                                   and saved_base.get("status") in {"PENDING", "FAILED"}
                                   and not canary_part_reused else None)
            if resume_frozen_batch and source_part is None:
                base_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                base_created = base_runnable = False
                base_binding_failure = "FROZEN_SOURCE_PART_IDENTITY_UNVERIFIED"
            elif historical_conflict is not None:
                base_job = saved_base
                base_created = base_runnable = False
                base_binding_failure = "HISTORICAL_SUCCESS_PROVENANCE_MISMATCH"
            elif resume_frozen_batch and isinstance(saved_base, dict) and saved_base.get("status") == "SUCCEEDED":
                try:
                    if runner is None or contract is None or not isinstance(request_material, dict):
                        raise FlashRunError("FROZEN_RESUME_REVALIDATOR_UNAVAILABLE")
                    _verify_frozen_saved_success(
                        payload, saved_base, queue_root, runner=runner, contract=contract,
                        citation_protocol=request_material["citation_protocol"])
                except (FlashRunError, OSError, KeyError, TypeError, ValueError) as exc:
                    base_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                    base_created = base_runnable = False
                    code = getattr(exc, "code", None) or str(exc)
                    base_binding_failure = (code if isinstance(code, str) and SAFE_CODE_RE.fullmatch(code)
                                            else "FROZEN_RESUME_SAVED_SUCCESS_UNVERIFIED")
                else:
                    base_job = saved_base
                    base_created = base_runnable = False
            elif resume_frozen_batch and isinstance(saved_base, dict):
                # Keep the saved source row immutable. New contract versions are
                # admitted separately below only for eligible pending/failed parts.
                base_job = saved_base
                base_created = base_runnable = False
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
            repair_source_key = base_key
            continuation_canary_source_key = None
            if canary_part_reused:
                canary_repair_binding = saved_canary_payload.get("part_repair_binding")
                continuation_canary_source_key = (canary_repair_binding.get("failed_idempotency_key")
                                                  if isinstance(canary_repair_binding, dict) else None)
                if (not isinstance(continuation_canary_source_key, str)
                        or not SHA_RE.fullmatch(continuation_canary_source_key)):
                    raise FlashRunError("FROZEN_RESUME_CANARY_FAILED_SOURCE_INVALID")
                selected_key, selected_job = saved_canary_key, saved_canary_job
                created = runnable = False
                repair_status = "REPAIR_CANARY_VERIFIED_REUSED"
                repair_binding = canary_repair_binding
                repair_source_key = continuation_canary_source_key

            legacy_source_job = None
            legacy_source_payload = None
            legacy_part_target = (resume_frozen_batch and resume_action == "CANARY"
                                  and isinstance(legacy_failed_canary, dict)
                                  and legacy_failed_canary.get("source_part_key") == base_key)
            if legacy_part_target:
                legacy_key = legacy_failed_canary.get("key")
                current_jobs = queue._load_state().get("jobs", {})
                legacy_source_job = current_jobs.get(legacy_key) if isinstance(current_jobs, dict) else None
                try:
                    legacy_source_payload = _queue_payload(queue_root, legacy_source_job)
                except FlashRunError:
                    legacy_source_payload = None
                legacy_binding_matches = (
                    isinstance(legacy_source_payload, dict)
                    and legacy_source_payload.get("frozen_resume_binding") == spec.get("frozen_resume_binding")
                    and _current_frozen_resume_payload_valid(
                        legacy_source_payload, membership_gate, spec.get("frozen_resume_binding")))
                legacy_orphan_matches = False
                if (isinstance(frozen_source_payload, dict) and isinstance(saved_base, dict)
                        and isinstance(legacy_source_job, dict)
                        and isinstance(legacy_failed_canary.get("source_job_id"), str)
                        and isinstance(legacy_failed_canary.get("source_input_sha256"), str)):
                    expected_orphan = _orphan_recovery_payload(
                        frozen_source_payload, saved_base,
                        source_job_id=legacy_failed_canary["source_job_id"],
                        source_input_sha256=legacy_failed_canary["source_input_sha256"],
                        source_key=base_key,
                    )
                    legacy_orphan_matches = (isinstance(legacy_source_payload, dict)
                                             and canonical(legacy_source_payload) == canonical(expected_orphan)
                                             and legacy_source_job.get("identity") == queue._identity(expected_orphan)
                                             and _stable_queue_identity(queue, expected_orphan) == legacy_key)
                exact_legacy_part = (
                    isinstance(legacy_source_job, dict) and legacy_source_job.get("status") == "FAILED"
                    and legacy_source_job.get("attempt_count") == 1
                    and legacy_source_job.get("max_attempts") == 1
                    and legacy_source_job.get("queue_id") == QUEUE_ID
                    and isinstance(legacy_source_payload, dict)
                    and legacy_source_job.get("idempotency_key") == legacy_key
                    and legacy_source_payload.get("article_id") == payload.get("article_id")
                    and legacy_source_payload.get("source_sha256") == payload.get("source_sha256")
                    and legacy_source_payload.get("body_sha256") == payload.get("body_sha256")
                    and legacy_source_payload.get("source_unit_map_sha256") == payload.get("source_unit_map_sha256")
                    and legacy_source_payload.get("chunk_plan_sha256") == payload.get("chunk_plan_sha256")
                    and legacy_source_payload.get("part_descriptor") == descriptor
                    and legacy_source_job.get("payload_sha256") == legacy_failed_canary.get("payload_sha256")
                    and legacy_source_job.get("raw_sha256") == legacy_failed_canary.get("raw_sha256")
                    and (legacy_binding_matches or legacy_orphan_matches))
                if not exact_legacy_part:
                    base_binding_failure = "FROZEN_RESUME_LEGACY_CANARY_PLAN_BINDING_UNVERIFIED"
                    selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                    created = runnable = False
                    repair_status = "LEGACY_CANARY_SOURCE_UNVERIFIED"
                else:
                    repair_source_key = legacy_key
            elif (resume_frozen_batch and resume_action == "CANARY"
                  and isinstance(legacy_failed_canary, dict) and base_job.get("status") == "FAILED"):
                repair_status = "LEGACY_CANARY_PART_DEFERRED"
            orphan_recovery = None
            prior_orphan = None
            if (not canary_part_reused and not legacy_part_target
                    and resume_frozen_batch and base_job.get("status") == "FAILED"
                    and base_key not in recovered_orphan_keys and base_key not in blocked_orphan_keys):
                try:
                    prior_orphan = _prior_orphan_recovery(
                        payload, base_key, base_job, queue, queue_root,
                        source_job_id=source_job_id, source_input_sha256=source_input_sha256,
                    )
                except FlashRunError as exc:
                    base_binding_failure = exc.code

            if (not canary_part_reused
                    and base_binding_failure in {"ORPHAN_RECOVERY_IDENTITY_CONFLICT", "ORPHAN_RECOVERY_PAYLOAD_CONFLICT"}):
                selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                base_created = base_runnable = created = runnable = False
                repair_status = "ORPHAN_RECOVERY_BLOCKED"
            elif not canary_part_reused and prior_orphan is not None:
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
            elif not canary_part_reused and base_key in blocked_orphan_keys:
                base_binding_failure = ("ORPHAN_COMPLETE_RESULT_CANNOT_CONFIRM"
                                        if orphan_candidates.get(base_key) == "COMPLETE" else
                                        "ORPHAN_RESULT_UNVERIFIED")
                base_created = base_runnable = created = runnable = False
                selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                repair_status = "ORPHAN_RECOVERY_BLOCKED"
            elif (not canary_part_reused and resume_frozen_batch and base_key in recovered_orphan_keys
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
            elif (not canary_part_reused and resume_frozen_batch and base_key in orphan_candidates
                  and base_job.get("status") == "RUNNING"):
                # A dry run only reports the candidate. The actual continuation
                # must acquire the queue's model lock and record interruption.
                orphan_recovery = {"status": orphan_candidates[base_key],
                                   "source_idempotency_key": base_key,
                                   "eligible": orphan_candidates[base_key] == "OWNER_CLEAR_NO_RESULT"}

            if (not canary_part_reused and resume_frozen_batch and base_job.get("status") == "PENDING"
                    and historical_conflict is None and base_binding_failure is None):
                if resume_action == "CONTINUE":
                    pending_payload = copy.deepcopy(payload)
                    root_binding = spec.get("frozen_resume_binding")
                    if not isinstance(root_binding, dict):
                        base_binding_failure = "FROZEN_RESUME_ROOT_BINDING_INVALID"
                        selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": base_key}
                        created = runnable = False
                    else:
                        pending_payload["rules"] = (
                            f"{payload.get('rules', '')}+frozen-resume-contract:v1"
                            f"+root:{root_binding.get('source_job_id')}:{root_binding.get('source_input_sha256')}"
                        )
                        try:
                            selected_key, selected_job, created, runnable = _enqueue_internal_payload(
                                pending_payload, queue, queue_root,
                                allow_same_batch_pending=True, allow_enqueue=allow_enqueue,
                            )
                        except FlashRunError as exc:
                            if exc.code not in {"INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
                                                "SAVED_PARTIAL_QUEUE_ITEM_NOT_FOUND"}:
                                raise
                            base_binding_failure = "FROZEN_PENDING_VERSION_CONFLICT"
                            selected_key = _stable_queue_identity(queue, pending_payload)
                            selected_job = {"status": "CANNOT_CONFIRM", "idempotency_key": selected_key}
                            created = runnable = False
                        repair_status = ("FROZEN_PENDING_VERSION_ENQUEUED" if created else
                                         "FROZEN_PENDING_VERSION_ALLOWED" if runnable else
                                         "FROZEN_PENDING_VERSION_TERMINAL")
                else:
                    repair_status = "FROZEN_PENDING_DEFERRED_TO_CONTINUATION"

            if (not canary_part_reused and base_job.get("status") == "FAILED"
                    and (not resume_frozen_batch or resume_action in {"CANARY", "CONTINUE"})
                    and (legacy_failed_canary is None or legacy_part_target)
                    and base_binding_failure is None):
                failed_repair_source = legacy_source_job if legacy_part_target else base_job
                repair = _part_repair_payload(
                    payload, failed_repair_source, queue_root, recovery_lock, membership_gate, resume_cutoff,
                    hard_prompt_token_cap,
                    frozen_resume_binding=(spec.get("frozen_resume_binding")
                                           if resume_frozen_batch else None),
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
                           "repair_source_key": repair_source_key,
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
                                     "repair_source_key": repair_source_key,
                                     "orphan_recovery": orphan_recovery,
                                     "repair_binding_sha256": part_record["repair_binding_sha256"]})
            if runnable:
                allowed_keys.add(selected_key)
    return allowed_keys, internal_records


def _frozen_resume_canary(internal_records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick only one exact validator-failed part repair as the frozen contract canary."""
    candidates = [record for record in internal_records
                if record.get("kind") == "part"
                and record.get("base_status") == "FAILED"
                and record.get("repair_status") in {"REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED",
                                                     "REPAIRED_SUCCESS_REUSED"}
                and record.get("runnable") is True]
    candidates = [record for record in candidates
                 if record.get("runnable") is True
                 or (isinstance(record.get("job"), dict) and record["job"].get("status") == "SUCCEEDED")]
    return min(candidates, key=lambda record: (
        str(record.get("article_id", "")), int(record.get("part_index", 0)),
        str(record.get("key", "")))) if candidates else None


def _frozen_resume_legacy_canary_target(
        long_body_specs: dict[str, dict[str, Any]], legacy: Any, queue: Any,
        queue_root: Path, *, root_job_id: str, root_input_sha256: str,
        membership_gate: Any, hard_prompt_token_cap: int,
        count_prompt_tokens: Callable[[list[dict[str, Any]]], int]
        ) -> dict[str, Any]:
    """Prove one failed legacy orphan wrapper maps to one reparable frozen source part."""
    if not isinstance(legacy, dict):
        raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_MISSING")
    source_key = legacy.get("source_part_key")
    legacy_key = legacy.get("key")
    if (not isinstance(source_key, str) or not SHA_RE.fullmatch(source_key)
            or not isinstance(legacy_key, str) or not SHA_RE.fullmatch(legacy_key)
            or legacy.get("root_job_id") != root_job_id
            or legacy.get("root_input_sha256") != root_input_sha256
            or not isinstance(legacy.get("source_job_id"), str)
            or not JOB_ID_RE.fullmatch(legacy["source_job_id"])
            or not isinstance(legacy.get("source_input_sha256"), str)
            or not SHA_RE.fullmatch(legacy["source_input_sha256"])):
        raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_BINDING_INVALID")

    matches: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any],
                         dict[str, Any], dict[str, Any]]] = []
    for article_id, spec in long_body_specs.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("part_payloads"), list):
            continue
        for payload in spec["part_payloads"]:
            if not isinstance(payload, dict):
                continue
            source_part = _find_frozen_source_part(payload, queue, queue_root)
            if source_part is not None and source_part[0] == source_key:
                matches.append((article_id, spec, payload, *source_part))
    if len(matches) != 1:
        raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_NOT_UNIQUE")
    article_id, spec, payload, base_key, base_job, frozen_source_payload = matches[0]
    descriptor = payload.get("part_descriptor")
    if (base_key != source_key or base_job.get("status") != "FAILED"
            or base_job.get("attempt_count") != 1
            or legacy.get("article_id") != article_id
            or legacy.get("source_sha256") != payload.get("source_sha256")
            or legacy.get("body_sha256") != payload.get("body_sha256")
            or legacy.get("chunk_plan_sha256") != payload.get("chunk_plan_sha256")
            or legacy.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or legacy.get("part_descriptor") != descriptor):
        raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_BINDING_INVALID")

    state = queue._load_state()
    jobs = state.get("jobs", {}) if isinstance(state, dict) else None
    legacy_job = jobs.get(legacy_key) if isinstance(jobs, dict) else None
    if (not isinstance(legacy_job, dict) or legacy_job.get("queue_id") != QUEUE_ID
            or legacy_job.get("idempotency_key") != legacy_key
            or legacy_job.get("status") != "FAILED" or legacy_job.get("attempt_count") != 1
            or legacy_job.get("max_attempts") != 1
            or legacy_job.get("payload_sha256") != legacy.get("payload_sha256")
            or legacy_job.get("raw_sha256") != legacy.get("raw_sha256")):
        raise FlashRunError("FROZEN_RESUME_CANARY_SOURCE_INVALID")
    legacy_payload = _queue_payload(queue_root, legacy_job)
    expected_orphan = _orphan_recovery_payload(
        frozen_source_payload, base_job, source_job_id=legacy["source_job_id"],
        source_input_sha256=legacy["source_input_sha256"], source_key=base_key,
    )
    if (canonical(legacy_payload) != canonical(expected_orphan)
            or legacy_job.get("identity") != queue._identity(expected_orphan)
            or _stable_queue_identity(queue, expected_orphan) != legacy_key):
        raise FlashRunError("FROZEN_RESUME_CANARY_ORPHAN_SOURCE_MISMATCH")

    repair = _part_repair_payload(
        payload, legacy_job, queue_root, None, membership_gate, None,
        hard_prompt_token_cap,
        frozen_resume_binding=spec.get("frozen_resume_binding"),
    )
    if repair is None:
        raise FlashRunError("FROZEN_RESUME_CANARY_REPAIR_PAYLOAD_INVALID")
    repair_payload, repair_binding = repair
    try:
        repair_tokens = count_prompt_tokens(repair_payload["messages"])
    except (KeyError, TypeError, ValueError):
        raise FlashRunError("FROZEN_RESUME_CANARY_REPAIR_BUDGET_INVALID") from None
    if (type(repair_tokens) is not int or repair_tokens > hard_prompt_token_cap
            or repair_binding.get("failed_idempotency_key") != legacy_key):
        raise FlashRunError("FROZEN_RESUME_CANARY_REPAIR_BUDGET_INVALID")
    return {"article_id": article_id, "part_index": descriptor.get("part_index"),
            "base_key": base_key, "legacy_key": legacy_key}


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


def _verify_frozen_saved_success(payload: dict[str, Any], job: dict[str, Any], queue_root: Path, *,
                                runner: Any, contract: Any, citation_protocol: str) -> dict[str, Any]:
    """Revalidate a source-bound saved success under the stricter empty-array schema without dispatch."""
    from v4.manager_workbench import announcement_chunks as chunks

    if (job.get("status") != "SUCCEEDED" or job.get("attempt_count") != 1
            or job.get("max_attempts") != 1 or job.get("queue_id") != QUEUE_ID
            or not isinstance(job.get("identity"), dict)
            or job["identity"].get("article_id") != payload.get("article_id")
            or job["identity"].get("source_sha256") != payload.get("source_sha256")
            or job["identity"].get("body_sha256") != payload.get("body_sha256")):
        raise FlashRunError("FROZEN_RESUME_SAVED_SUCCESS_BINDING_INVALID")
    stored_payload = _queue_payload(queue_root, job)
    descriptor = payload.get("part_descriptor")
    stored_descriptor = stored_payload.get("part_descriptor")
    if (stored_payload.get("queue_task_kind") != "announcement_reader_part"
            or stored_payload.get("source_sha256") != payload.get("source_sha256")
            or stored_payload.get("body_sha256") != payload.get("body_sha256")
            or stored_payload.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or stored_payload.get("chunk_plan_sha256") != payload.get("chunk_plan_sha256")
            or not isinstance(descriptor, dict) or not isinstance(stored_descriptor, dict)
            or any(stored_descriptor.get(field) != descriptor.get(field) for field in (
                "part_index", "part_count", "part_sha256", "start_source_unit_id",
                "end_source_unit_id", "source_unit_ids", "unit_start_index", "unit_end_index"))):
        raise FlashRunError("FROZEN_RESUME_SAVED_SUCCESS_SOURCE_MISMATCH")
    saved_result, _result_sha, raw_sha = _read_internal_validated_result(queue_root, job)
    raw_response = _read_json_file(queue_root / job["raw_path"], raw_sha,
                                   "FROZEN_RESUME_SAVED_SUCCESS_RAW_INVALID")
    unit_map = runner.build_source_unit_map(payload["article_body"], payload["body_sha256"])
    if unit_map.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256"):
        raise FlashRunError("FROZEN_RESUME_SAVED_SUCCESS_UNIT_MAP_MISMATCH")
    validate_schema = lambda output: runner._validate_json_schema(
        output, chunks.empty_reader_fixed_fields_schema(
            runner.build_simple_reader_wire_schema(contract, citation_protocol)))
    validated = chunks.validate_part_envelope(
        raw_response, article_id=payload["article_id"], source_sha256=payload["source_sha256"],
        body_sha256=payload["body_sha256"], plan_sha256=payload["chunk_plan_sha256"],
        part=descriptor, unit_map=unit_map, body=payload["article_body"], validate_schema=validate_schema,
    )
    if validated != saved_result:
        raise FlashRunError("FROZEN_RESUME_SAVED_SUCCESS_REVALIDATION_MISMATCH")
    return saved_result


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
                                         request_material: dict[str, Any],
                                         frozen_resume_binding: dict[str, Any] | None = None
                                         ) -> tuple[bool, str | None]:
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
        repair_source_key = part_record.get("repair_source_key") or base_key
        if (not isinstance(base_key, str) or not isinstance(repair_key, str)
                or not isinstance(repair_source_key, str)
                or part_record.get("selected_key", part_record.get("key")) != repair_key):
            raise FlashRunError("REPAIR_CANARY_KEY_BINDING_INVALID")
        state = queue._load_state()
        jobs = state.get("jobs", {}) if isinstance(state, dict) else {}
        base_job = jobs.get(base_key) if isinstance(jobs, dict) else None
        repair_source_job = jobs.get(repair_source_key) if isinstance(jobs, dict) else None
        repair_job = jobs.get(repair_key) if isinstance(jobs, dict) else None
        if (not isinstance(base_job, dict) or base_job.get("status") != "FAILED"
                or base_job.get("idempotency_key") != base_key or base_job.get("attempt_count") != 1
                or base_job.get("max_attempts") != 1 or base_job.get("queue_id") != QUEUE_ID
                or not isinstance(repair_source_job, dict) or repair_source_job.get("status") != "FAILED"
                or repair_source_job.get("idempotency_key") != repair_source_key
                or repair_source_job.get("attempt_count") != 1
                or repair_source_job.get("max_attempts") != 1
                or repair_source_job.get("queue_id") != QUEUE_ID
                or not isinstance(repair_job, dict) or repair_job.get("status") != "SUCCEEDED"
                or repair_job.get("idempotency_key") != repair_key or repair_job.get("attempt_count") != 1
                or repair_job.get("max_attempts") != 1 or repair_job.get("queue_id") != QUEUE_ID):
            raise FlashRunError("REPAIR_CANARY_QUEUE_STATE_INVALID")

        expected_part = parts[part_index - 1]
        base_payload = _queue_payload(queue_root, base_job)
        repair_source_payload = _queue_payload(queue_root, repair_source_job)
        current_part_payload = payloads[part_index - 1]
        base_source_matches = (
            base_payload.get("article_id") == article.get("article_id")
            and base_payload.get("source_sha256") == article.get("source_sha256")
            and base_payload.get("body_sha256") == article.get("body_sha256")
            and base_payload.get("source_unit_map_sha256") == unit_map.get("source_unit_map_sha256")
            and base_payload.get("chunk_plan_sha256") == plan.get("plan_sha256")
            and base_payload.get("part_descriptor") == expected_part
        )
        if (not base_source_matches
                or (frozen_resume_binding is not None
                    and not _current_frozen_resume_payload_valid(
                        base_payload, membership_gate, frozen_resume_binding))
                or (frozen_resume_binding is None and (
                    not _internal_payload_matches(base_payload, current_part_payload)
                ))):
            raise FlashRunError("REPAIR_CANARY_FAILED_SOURCE_BINDING_MISMATCH")
        if (repair_source_key != base_key
                and (repair_source_payload.get("article_id") != article.get("article_id")
                     or repair_source_payload.get("source_sha256") != article.get("source_sha256")
                     or repair_source_payload.get("body_sha256") != article.get("body_sha256")
                     or repair_source_payload.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")
                     or repair_source_payload.get("chunk_plan_sha256") != plan.get("plan_sha256")
                     or repair_source_payload.get("part_descriptor") != expected_part
                     or repair_source_payload.get("frozen_resume_binding") != frozen_resume_binding
                     or (frozen_resume_binding is not None
                         and not _current_frozen_resume_payload_valid(
                             repair_source_payload, membership_gate, frozen_resume_binding)))):
            raise FlashRunError("REPAIR_CANARY_FAILED_SOURCE_BINDING_MISMATCH")
        if (base_payload.get("article_id") != article.get("article_id")
                or base_payload.get("source_sha256") != article.get("source_sha256")
                or base_payload.get("body_sha256") != article.get("body_sha256")
                or base_payload.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")
                or base_payload.get("chunk_plan_sha256") != plan.get("plan_sha256")
                or base_payload.get("part_descriptor") != expected_part):
            raise FlashRunError("REPAIR_CANARY_FAILED_SOURCE_BINDING_MISMATCH")
        # The failed base payload is immutable and may carry older capture-row
        # provenance. Its source/body/plan and messages were just compared with
        # the freshly rebuilt current part above; reconstruct the repair from
        # that current, authority-validated part input while retaining the base
        # key/payload/raw SHA in the validator-feedback binding.
        repair = _part_repair_payload(current_part_payload, repair_source_job, queue_root, recovery_lock,
                                       membership_gate, resume_cutoff, hard_prompt_token_cap,
                                       frozen_resume_binding=frozen_resume_binding)
        if repair is None:
            raise FlashRunError("REPAIR_CANARY_REPAIR_VERSION_INVALID")
        expected_repair_payload, binding = repair
        exact_tokens = count_prompt_tokens(expected_repair_payload["messages"])
        if type(exact_tokens) is not int or exact_tokens > hard_prompt_token_cap:
            raise FlashRunError("REPAIR_CANARY_TOKEN_PREFLIGHT_INVALID")
        expected_repair_payload["prompt_tokens_exact"] = exact_tokens
        stored_repair_payload = _queue_payload(queue_root, repair_job)
        stored_repair_matches = (
            _internal_payload_matches(stored_repair_payload, expected_repair_payload)
            if frozen_resume_binding is not None else
            _part_repair_payload_matches_capture_provenance_drift(
                stored_repair_payload, expected_repair_payload,
                recovery_lock=recovery_lock, membership_gate=membership_gate,
                resume_cutoff=resume_cutoff, state_root=state_root)
        )
        if (_stable_queue_identity(queue, expected_repair_payload) != repair_key
                or repair_job.get("identity") != queue._identity(expected_repair_payload)
                or not stored_repair_matches
                or part_record.get("repair_binding_sha256") != binding.get("binding_sha256")):
            raise FlashRunError("REPAIR_CANARY_REPAIR_BINDING_MISMATCH")

        result, _result_sha, raw_sha = _read_internal_validated_result(queue_root, repair_job)
        raw_response = _read_json_file(queue_root / repair_job.get("raw_path"), raw_sha,
                                       "REPAIR_CANARY_RAW_RESPONSE_INVALID")
        validate_schema = lambda output: runner._validate_json_schema(
            output, chunks.empty_reader_fixed_fields_schema(
                runner.build_simple_reader_wire_schema(
                    contract, request_material["citation_protocol"])))
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


def _verify_saved_frozen_resume_canary(long_body_specs: dict[str, dict[str, Any]],
                                      resume_source: Any, queue: Any, queue_root: Path, *,
                                      prompt_token_cap: int, hard_prompt_token_cap: int,
                                      membership_gate: Any,
                                      count_prompt_tokens: Callable[[list[dict[str, Any]]], int],
                                      runner: Any, contract: Any, state_root: Path,
                                      request_material: dict[str, Any]
                                      ) -> tuple[bool, str | None]:
    """Revalidate the saved UI canary before any continuation queue mutation or dispatch."""
    from v4.manager_workbench import announcement_chunks as chunks

    receipt = resume_source.get("canary_validation") if isinstance(resume_source, dict) else None
    if (not isinstance(resume_source, dict) or resume_source.get("resume_action") != "CONTINUE"
            or resume_source.get("canary_passed") is not True
            or resume_source.get("canary_status") != "SUCCEEDED"
            or resume_source.get("canary_model_calls") != 1
            or not isinstance(receipt, dict) or receipt.get("status") != "PASS"):
        return False, "FROZEN_RESUME_CANARY_RECEIPT_INVALID"
    canary_key = resume_source.get("canary_key")
    if not isinstance(canary_key, str) or not SHA_RE.fullmatch(canary_key):
        return False, "FROZEN_RESUME_CANARY_KEY_INVALID"
    jobs = queue._load_state().get("jobs", {})
    canary_job = jobs.get(canary_key) if isinstance(jobs, dict) else None
    if (not isinstance(canary_job, dict) or canary_job.get("idempotency_key") != canary_key
            or canary_job.get("status") != "SUCCEEDED" or canary_job.get("attempt_count") != 1
            or canary_job.get("max_attempts") != 1 or canary_job.get("queue_id") != QUEUE_ID):
        return False, "FROZEN_RESUME_CANARY_QUEUE_STATE_INVALID"
    try:
        stored_canary_payload = _queue_payload(queue_root, canary_job)
    except FlashRunError:
        return False, "FROZEN_RESUME_CANARY_PAYLOAD_INVALID"
    if (stored_canary_payload.get("queue_task_kind") != "announcement_reader_part"
            or stored_canary_payload.get("part_repair_binding", {}).get("failure_code")
            != "PART_FIXED_FIELDS_MUST_BE_EMPTY"
            or stored_canary_payload.get("part_repair_binding", {}).get("binding_sha256")
            != receipt.get("binding_sha256")
            or canary_job.get("validated_sha256") != receipt.get("validated_sha256")
            or canary_job.get("raw_sha256") != receipt.get("raw_sha256")):
        return False, "FROZEN_RESUME_CANARY_NOT_FAILED_PART_REPAIR"
    repair_binding = stored_canary_payload.get("part_repair_binding")
    failed_source_key = repair_binding.get("failed_idempotency_key") if isinstance(repair_binding, dict) else None
    failed_source_job = jobs.get(failed_source_key) if isinstance(jobs, dict) else None
    if (not isinstance(failed_source_key, str) or not SHA_RE.fullmatch(failed_source_key)
            or not isinstance(failed_source_job, dict) or failed_source_job.get("status") != "FAILED"
            or failed_source_job.get("idempotency_key") != failed_source_key
            or failed_source_job.get("attempt_count") != 1 or failed_source_job.get("max_attempts") != 1
            or failed_source_job.get("queue_id") != QUEUE_ID
            or failed_source_job.get("payload_sha256") != repair_binding.get("failed_payload_sha256")
            or failed_source_job.get("raw_sha256") != repair_binding.get("failed_raw_response_sha256")):
        return False, "FROZEN_RESUME_CANARY_FAILED_SOURCE_INVALID"
    try:
        failed_source_payload = _queue_payload(queue_root, failed_source_job)
    except FlashRunError:
        return False, "FROZEN_RESUME_CANARY_FAILED_SOURCE_PAYLOAD_INVALID"
    matches = []
    for article_id, spec in long_body_specs.items():
        binding = spec.get("frozen_resume_binding")
        for payload in spec.get("part_payloads", []):
            source = _find_frozen_source_part(payload, queue, queue_root)
            if source is None:
                continue
            base_key, base_job, _source_payload = source
            if base_job.get("status") != "FAILED":
                continue
            descriptor = payload.get("part_descriptor")
            if (failed_source_payload.get("article_id") != payload.get("article_id")
                    or failed_source_payload.get("source_sha256") != payload.get("source_sha256")
                    or failed_source_payload.get("body_sha256") != payload.get("body_sha256")
                    or failed_source_payload.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
                    or failed_source_payload.get("chunk_plan_sha256") != payload.get("chunk_plan_sha256")
                    or failed_source_payload.get("part_descriptor") != descriptor
                    or failed_source_payload.get("frozen_resume_binding") != binding
                    or not _current_frozen_resume_payload_valid(
                        failed_source_payload, membership_gate, binding)):
                continue
            repair = _part_repair_payload(
                payload, failed_source_job, queue_root, None, membership_gate,
                None, hard_prompt_token_cap, frozen_resume_binding=binding,
            )
            if repair is None:
                continue
            repair_payload, repair_binding = repair
            exact_tokens = count_prompt_tokens(repair_payload.get("messages"))
            if type(exact_tokens) is not int or exact_tokens > hard_prompt_token_cap:
                continue
            repair_payload["prompt_tokens_exact"] = exact_tokens
            if _stable_queue_identity(queue, repair_payload) != canary_key:
                continue
            record = {"article_id": article_id, "part_index": descriptor.get("part_index")
                      if isinstance(descriptor, dict) else None,
                      "base_key": base_key, "repair_key": canary_key, "selected_key": canary_key,
                      "repair_source_key": failed_source_key,
                      "key": canary_key, "repair_binding_sha256": repair_binding.get("binding_sha256")}
            ok, failure_code = _verify_completed_part_repair_canary(
                spec, record, queue, queue_root, recovery_lock=None,
                membership_gate=membership_gate, resume_cutoff=None,
                hard_prompt_token_cap=hard_prompt_token_cap,
                count_prompt_tokens=count_prompt_tokens, runner=runner, contract=contract,
                state_root=state_root, request_material=request_material,
                frozen_resume_binding=binding,
            )
            matches.append((ok, failure_code))
    if len(matches) != 1:
        return False, "FROZEN_RESUME_CANARY_PLAN_MATCH_MISSING"
    return matches[0]


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


def _classification_contract(request_material: dict[str, Any], runner: Any) -> dict[str, Any]:
    return {"model_id": runner.MODEL_ID, **{key:request_material.get(key) for key in (
        "prompt_sha256", "configuration_sha256", "schema_sha256", "citation_protocol", "source_code_sha256",
        "runtime_limits", "max_completion_tokens", "runtime_settings_sha256", "model_settings_sha256", "parser_sha256")},
        "workflow_profile": PROFILE}


def _classification_history(row: dict[str, Any], article: dict[str, Any], jobs: dict[str, Any],
                            queue_root: Path, runner: Any, request_material: dict[str, Any]) -> tuple[str, Any]:
    """Identify exact content history before checking whether its result is reusable."""
    candidates = []
    for key, job in jobs.items():
        identity = job.get('identity', {}) if isinstance(job, dict) else {}
        if (job.get('queue_id') != QUEUE_ID or identity.get('article_id') != article['article_id']
                or identity.get('source_sha256') != article['source_sha256']
                or identity.get('body_sha256') != article['body_sha256']
                or identity.get('date') != article['article_metadata'].get('publication_date')
                or identity.get('market') != 'HK'
                or identity.get('role') not in {'announcement_reader', 'announcement_reader_synthesis'}):
            continue
        candidates.append((key, job))
    if not candidates:
        return 'NEW_INPUT', None
    # Success takes precedence, then a recorded failed/pending item. A historic
    # attempt is never retried just because a new batch/classifier is started.
    candidates.sort(key=lambda item: (item[1].get('status') != 'SUCCEEDED', item[0]))
    fallback = None
    for key, job in candidates:
        if fallback is not None and candidates[0][1].get('status') == 'SUCCEEDED' and job.get('status') != 'SUCCEEDED':
            break
        disposition, receipt = _classification_history_candidate(
            key, job, article, queue_root, runner, request_material)
        if fallback is None:
            fallback = disposition, receipt
        if disposition == 'REUSED_SUCCESS':
            return disposition, receipt
        # Success protection also takes precedence over compatible failed/pending
        # receipts. Only another verified compatible success may supersede it.
        if job.get('status') != 'SUCCEEDED':
            break
    return fallback


def _classification_history_candidate(key: str, job: dict[str, Any], article: dict[str, Any],
                                      queue_root: Path, runner: Any,
                                      request_material: dict[str, Any]) -> tuple[str, Any]:
    payload = _queue_payload(queue_root, job)
    if payload.get('article_body') != article['article_body']:
        raise FlashRunError('CLASSIFICATION_HISTORY_BODY_CONFLICT')
    receipt = {'key':key, 'status':job.get('status'), 'payload_sha256':job.get('payload_sha256'),
        'validated_sha256':job.get('validated_sha256'), 'identity_sha256':sha(canonical(job['identity']))}
    expected = {'model_id':runner.MODEL_ID,
        'configuration_sha256':request_material['configuration_sha256'],
        'prompt_sha256':request_material['prompt_sha256']}
    mismatches = [name for name, value in expected.items() if job['identity'].get(name) != value]
    if mismatches:
        # Contract drift cannot erase successful, failed, or pending processing.
        # Preserve its source-bound receipt without constructing new model work.
        return 'HISTORICAL_INCOMPATIBLE_PRESERVED', {**receipt, 'compatibility_mismatches':mismatches}
    unit_map = runner.build_source_unit_map(article['article_body'], article['body_sha256'])
    ledger = runner.simple_fixed_facts.extract_fixed_facts(article['article_body'], unit_map, article['article_metadata'])
    rules = str(payload.get('rules', ''))
    required = (f"profile:{PROFILE}", f"citation:{request_material['citation_protocol']}",
                f"unit-map:{unit_map['source_unit_map_sha256']}", f"fixed-ledger:{ledger['ledger_sha256']}",
                f"schema:{request_material['schema_sha256']}")
    if not all(rules.split('+').count(item) == 1 for item in required):
        # The old result remains visible and preserved. Incompatible material is
        # visible as a pending compatibility question, not an automatic rerun.
        return 'HISTORICAL_INCOMPATIBLE_PRESERVED', {**receipt, 'compatibility_mismatches':['rules']}
    if job.get('status') == 'SUCCEEDED':
        _queue_result(queue_root, job)
        disposition = 'REUSED_SUCCESS'
    else:
        disposition = 'HISTORICAL_STATUS_PRESERVED'
    return disposition, receipt


def _reusable_classifications(state_io: SafeRoot, enabled: dict[str, Any], contract: dict[str, Any]) -> dict[tuple[Any, ...], Any]:
    """Read only the existing committed result index; no parallel state producer."""
    try:
        raw=state_io.read_bytes('cursors/announcement_flash_result_index.json',max_bytes=64*1024*1024)
    except FileNotFoundError:
        return {}
    index=_json(raw,'CLASSIFICATION_RESULT_INDEX_INVALID')
    cache={}
    for entry in index.get('items',[]):
        jid=entry.get('job_id') if isinstance(entry,dict) else None
        if not JOB_ID_RE.fullmatch(str(jid)) or not SHA_RE.fullmatch(str(entry.get('result_sha256',''))):
            continue
        result_raw=state_io.read_bytes(f'announcement_flash/jobs/{jid}/result.json',max_bytes=64*1024*1024)
        if sha(result_raw)!=entry['result_sha256']:
            raise FlashRunError('CLASSIFICATION_PRIOR_RESULT_SHA_CHANGED')
        result=_json(result_raw,'CLASSIFICATION_PRIOR_RESULT_INVALID')
        if result.get('schema')!='v4.manager_workbench.announcement_flash_result.v1' or result.get('job_id')!=jid:
            raise FlashRunError('CLASSIFICATION_PRIOR_RESULT_IDENTITY_INVALID')
        binding=result.get('classification_plan')
        if not isinstance(binding,dict):continue
        if binding.get('artifact_ref')!=f'announcement_flash/jobs/{jid}/classification-plan.json':continue
        plan_raw=state_io.read_bytes(binding['artifact_ref'],max_bytes=64*1024*1024)
        if sha(plan_raw)!=binding.get('sha256'):
            raise FlashRunError('CLASSIFICATION_PRIOR_PLAN_SHA_CHANGED')
        plan=_json(plan_raw,'CLASSIFICATION_PRIOR_PLAN_INVALID')
        from v4.manager_workbench.announcement_classification import PLAN_SCHEMA
        if plan.get('schema')!=PLAN_SCHEMA or plan.get('policy')!=enabled or plan.get('processing_contract')!=contract:continue
        for item in plan.get('items',[]):
            if (item.get('membership_status')=='IN' and item.get('route_group') in {'A','B'}
                    and item.get('processing_disposition') in {'NEW_INPUT','REUSED_CLASSIFICATION'}):
                key=(item['article_id'],item['source_sha256'],item['body_sha256'],item.get('source_date'))
                cache[key]={'classification':item['classification'],'receipt':{'source_job_id':jid,
                    'classification_plan_sha256':binding['sha256'],'source_row_index':item['row_index'],
                    'result_sha256':entry['result_sha256']}}
    return cache


def _prepare_classification_plan(input_value: dict[str, Any], *, capture_product: dict[str, Any],
                                 capture_ref: dict[str, Any], capture_io: SafeRoot,
                                 state_root: Path, job_id: str, membership_gate: dict[str, Any],
                                 runner: Any, request_material: dict[str, Any],
                                 resume: bool, materialize_only: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    from v4.manager_workbench.announcement_classification import (
        PLAN_SCHEMA, MODEL, QUARANTINE, classify, frozen_policy, seal_plan,
    )
    from v4.manager_workbench.announcement_membership import classify_capture_row
    enabled = frozen_policy(input_value, allow_replay=True)
    root = input_value.get('resume_root') if resume else None
    recovery = input_value.get('recovery_lock') if resume else None
    owner_id = (root.get('source_job_id') if isinstance(root,dict) else
                recovery.get('parent_job_id') if isinstance(recovery,dict) else job_id)
    if not JOB_ID_RE.fullmatch(str(owner_id)):
        raise FlashRunError('CLASSIFICATION_PLAN_OWNER_INVALID')
    prefix = f'announcement_flash/jobs/{owner_id}'
    plan_ref, binding_ref = prefix+'/classification-plan.json', prefix+'/classification-plan-binding.json'
    state_io = SafeRoot(state_root)
    try:
        binding_raw = state_io.read_bytes(binding_ref, max_bytes=1024*1024)
    except FileNotFoundError:
        binding_raw = None
    contract = _classification_contract(request_material, runner)
    rows = capture_product.get('rows', [])
    if binding_raw is not None:
        binding = _json(binding_raw, 'CLASSIFICATION_PLAN_BINDING_INVALID')
        if resume and input_value.get('classification_plan') != binding:
            raise FlashRunError('CLASSIFICATION_EXPECTED_PLAN_SHA_CHANGED')
        if (binding.get('artifact_ref') != plan_ref or not SHA_RE.fullmatch(str(binding.get('sha256','')))):
            raise FlashRunError('CLASSIFICATION_PLAN_BINDING_INVALID')
        raw = state_io.read_bytes(plan_ref, max_bytes=64*1024*1024)
        if sha(raw) != binding['sha256']:
            raise FlashRunError('CLASSIFICATION_PLAN_SHA_CHANGED')
        plan = _json(raw, 'CLASSIFICATION_PLAN_INVALID')
        if (plan.get('schema') != PLAN_SCHEMA or plan.get('policy') != enabled
                or plan.get('capture_product') != capture_ref
                or plan.get('target_date') != input_value.get('target_date')
                or plan.get('cutoff') != input_value.get('cutoff')
                or plan.get('membership_gate_sha256') != sha(canonical(membership_gate))
                or plan.get('processing_contract') != contract
                or len(plan.get('items', [])) != len(rows)
                or any(item.get('row_index') != index or item.get('capture_row_sha256') != sha(canonical(row))
                       for index,(item,row) in enumerate(zip(plan['items'],rows)))):
            raise FlashRunError('CLASSIFICATION_PLAN_INPUT_CHANGED')
        for item,row in zip(plan['items'], rows):
            if item['route_group'] != 'D':
                if (not isinstance(row,dict) or sha(str(row.get('body_text','')).encode()) != item['body_sha256']):
                    raise FlashRunError('CLASSIFICATION_REPLAY_SOURCE_CHANGED')
                _capture_origin(row,capture_product,{**capture_ref,'row_index':item['row_index']},capture_io,item['body_sha256'])
        return plan, binding
    if resume or materialize_only:
        raise FlashRunError('CLASSIFICATION_FROZEN_PLAN_MISSING')
    # No stored plan means new classification. A different code version may not
    # silently recompute a formerly frozen decision.
    frozen_policy(input_value)
    queue_root = state_root/'announcement_flash'/'queue'
    if (queue_root/'queue-state.json').exists():
        queue_value = _json(SafeRoot(queue_root).read_bytes('queue-state.json',max_bytes=64*1024*1024), 'CLASSIFICATION_HISTORY_INVALID')
        jobs = queue_value.get('jobs',{})
    else:
        jobs = {}
    reused_classifications = _reusable_classifications(state_io,enabled,contract)
    catalogue, seen = [], {}
    for index, row in enumerate(rows):
        aid = 'EASTMONEY:'+str(row.get('art_code') or '') if isinstance(row,dict) else 'INVALID_ROW:'+str(index)
        member = classify_capture_row(row, membership_gate) if isinstance(row,dict) else {'membership_status':'UNKNOWN'}
        status = member['membership_status']
        base = {'article_id':aid,'source_sha256':row.get('source_sha256') if isinstance(row,dict) else None,
                'body_sha256':row.get('body_text_sha256') if isinstance(row,dict) else None,
                'article_body':row.get('body_text') if isinstance(row,dict) and row.get('body_complete') is True else None,
                'article_metadata':{'title':row.get('title') if isinstance(row,dict) else None,
                    'publication_date':row.get('publication_date') if isinstance(row,dict) else None,
                    'symbol':member.get('symbol'), 'issuer_name': next((code.get('name') for code in row.get('source_issuer_codes',[])
                        if isinstance(code,dict) and code.get('name')),None) if isinstance(row,dict) else None}}
        problem = None
        try:
            if base['article_body'] is None:
                raise FlashRunError('BODY_INCOMPLETE')
            if sha(base['article_body'].encode()) != base['body_sha256']:
                raise FlashRunError('BODY_SHA_MISMATCH')
            origins = _capture_origin(row,capture_product,{**capture_ref,'row_index':index},capture_io,base['body_sha256'])
            base['article_metadata']['source_origins'] = origins
            base['article_metadata']['pit_status'] = 'CANNOT_CONFIRM'
            if status == 'IN':
                base = _source_article(row,index,capture_product,capture_ref,capture_io,runner,membership_gate)
        except (OSError, ValueError, KeyError, TypeError, FlashRunError) as exc:
            problem = getattr(exc,'code',None) or (str(exc) if SAFE_CODE_RE.fullmatch(str(exc)) else 'SOURCE_BINDING_FAILED')
        from v4.manager_workbench.announcement_classification import source_gap_reason
        # Dispose exact prior processing before classifying a new input. Model
        # outputs never provide the document category or a rule truth label.
        disposition, history, reused_classification = 'NEW_INPUT', None, None
        identity = (aid,base.get('source_sha256'),base.get('body_sha256'))
        history_problem = False
        if isinstance(row,dict) and row.get('window_consumption_status') == 'EXCLUDED_OUTSIDE_WINDOW':
            disposition = 'OUTSIDE_WINDOW'
        elif status != 'IN':
            disposition = 'MEMBERSHIP_'+status
        elif identity in seen:
            disposition = 'DUPLICATE_EXACT_SOURCE'
        else:
            seen[identity]=index
            if not problem and not source_gap_reason(base.get('article_body')):
                cached = reused_classifications.get((*identity,base['article_metadata'].get('publication_date')))
                if cached:
                    disposition,history,reused_classification = 'REUSED_CLASSIFICATION',cached['receipt'],cached['classification']
                else:
                    try:
                        disposition,history = _classification_history(row,base,jobs,queue_root,runner,request_material)
                    except (OSError,ValueError,KeyError,TypeError,FlashRunError):
                        disposition,history_problem = 'HISTORY_INTEGRITY_QUARANTINE',True
        if reused_classification is not None:
            classification=copy.deepcopy(reused_classification)
            classification['classification_reuse_receipt']=history
        elif disposition in {'REUSED_SUCCESS','HISTORICAL_STATUS_PRESERVED','HISTORICAL_INCOMPATIBLE_PRESERVED'}:
            classification=classify(base,enabled_policy=None)
            classification['analysis_status']='PRIOR_PROCESSING_RECEIPT_PRESERVED'
            classification['reason_codes']=['SOURCE_BOUND_PRIOR_PROCESSING_NOT_RECLASSIFIED']
        else:
            classification=classify({**base,'article_body':None} if problem else base,enabled_policy=enabled)
        if problem:classification['reason_codes']=[problem]
        if history_problem:
            classification.update(route=QUARANTINE,route_group='D',analysis_status=QUARANTINE,
                reason_codes=['HISTORICAL_RECEIPT_INTEGRITY_UNCONFIRMED'])
        classification['capture_source']={**capture_ref,'row_index':index}
        classification['source_body_ref']=row.get('body_artifact_ref') if isinstance(row,dict) else None
        catalogue.append({'row_index':index,'capture_row_sha256':sha(canonical(row)),'article_id':aid,
            'source_sha256':base.get('source_sha256'),'body_sha256':base.get('body_sha256'),
            'source_date':base['article_metadata'].get('publication_date'),'membership_status':status,
            'membership_evidence':member,'processing_disposition':disposition,
            'duplicate_of_row':seen.get(identity) if disposition=='DUPLICATE_EXACT_SOURCE' else None,
            'route_group':classification['route_group'],'classification':classification,'history_receipt':history})
    plan = seal_plan(catalogue,capture_product=capture_ref,target_date=input_value['target_date'],
        cutoff=input_value.get('cutoff'),membership_gate=membership_gate,processing_contract=contract,enabled_policy=enabled)
    raw = canonical(plan)+b'\n'
    binding={'schema':'v4.manager_workbench.announcement_classification_plan_binding.v2',
             'artifact_ref':plan_ref,'sha256':sha(raw),'policy':enabled,'capture_product_sha256':capture_ref['sha256']}
    # A partial/orphan plan is not overwritten after interruption.
    if not result_path_is_absent(state_io,plan_ref):
        saved=state_io.read_bytes(plan_ref,max_bytes=64*1024*1024)
        if saved != raw:raise FlashRunError('CLASSIFICATION_ORPHAN_PLAN_CONFLICT')
    else:
        state_io.write_bytes(plan_ref,raw)
    _write_json(state_io,binding_ref,binding)
    return plan,binding


def _classification_history_matches(plan: dict[str, Any], *, capture_product: dict[str, Any],
                                    capture_ref: dict[str, Any], capture_io: SafeRoot,
                                    state_root: Path, runner: Any, membership_gate: dict[str, Any]) -> list[dict[str, Any]]:
    queue_root=state_root/'announcement_flash'/'queue'
    receipts=[item for item in plan['items'] if item['processing_disposition'] in {'REUSED_SUCCESS','HISTORICAL_STATUS_PRESERVED'}]
    if not receipts:return []
    jobs=_json(SafeRoot(queue_root).read_bytes('queue-state.json',max_bytes=64*1024*1024),'CLASSIFICATION_HISTORY_INVALID').get('jobs',{})
    matches=[]
    for item in receipts:
        receipt=item['history_receipt'];job=jobs.get(receipt['key'])
        if (not isinstance(job,dict) or job.get('payload_sha256') != receipt['payload_sha256']
            or job.get('validated_sha256') != receipt.get('validated_sha256')
            or job.get('status') != receipt['status'] or sha(canonical(job.get('identity'))) != receipt['identity_sha256']):
            raise FlashRunError('CLASSIFICATION_HISTORY_RECEIPT_CHANGED')
        article=_source_article(capture_product['rows'][item['row_index']],item['row_index'],capture_product,
                                capture_ref,capture_io,runner,membership_gate)
        matches.append({'record':{'source':'INCREMENTAL_QUEUE','status':job['status'],'identity':job['identity'],
            'job':job,'queue_root':queue_root,'idempotency_key':receipt['key']},'current_payload':article,'rules_match':True})
    return matches


# This is the single independently rejected live canary, not a retry-success policy.
SEMANTIC_REPAIR_EVIDENCE_ROOT = Path('/Users/lexi/Desktop/学习/agents调试/助手/announcement-semantic-recovery-20261021')
SEMANTIC_REPAIR = {
    'job_id': 'c2fddbf07be044978b5b01e448899b35',
    'report_sha256': 'fbfbb264752820e1337e2880578d25282d244f10b23f5d267e4fd5d64e17d1f2',
    'predecessor_sha256': '91dcdfda52ea2fdf55c61f45b9abc9493d252574a234429906a2baaf7fcb30dd',
    'review_sha256': '030843790194142c117a91051fb6cf32d350bb266e6dfebe57ef53077b0ae2d1',
    'queue_key': 'e6593b3354234aba23b81d6c7fbef002daaf202416d817c2bc828001a22354a9',
    'queue_record_sha256': '8e4466a6a89ac926376b54370d1628cb219803f2648bfc7dd0f248f33a02e2bd',
    'payload_sha256': '78a5e2bacc0ad81dae9f2d806d11aae33d984cc011df520cd9b7b8f5c9c15698',
    'raw_sha256': '2f101ce634eecf7c8d40dca19e22994082656da3bb7d159a1acc21c6a8c192e5',
    'validated_sha256': '73b8fae4f29bbd7ec1d7eb487e5e4d276fd415452daa5b498e56c164bdd922d3',
    'request_sha256': 'e8b9ec09682c3be95f3ba46de90aa255dc1a6584083bca607fad924b48ad470c',
    'stream_sha256': '13db1165a5ba7be3d2993e54e1e64cf30860364b702b5722a5f4805c6db87027',
    'sse_sha256': '63b2192bd54418a894f909a380ebb1c4afdeafc351d66455e28af4668b4eebc2',
}
SEMANTIC_ACCEPTANCE_REF = 'semantic-fix-live-review/receipt.json'


def _risk_extract_guard(payload, parsed, request_material, runner):
    """New wire identity only: reject the whole raw, never normalize its output."""
    from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT, SEMANTIC_CONTRACT_VERSION
    system = payload.get('messages', [{}])[0].get('content', '')
    marker = payload.get('semantic_contract_version')
    new_config = (request_material.get('configuration_material', {}).get('semantic_contract_version') == SEMANTIC_CONTRACT_VERSION
                  and payload.get('configuration_sha256') == request_material['configuration_sha256'])
    if not (marker is not None or SEMANTIC_CONTRACT_VERSION in system
            or SEMANTIC_CONTRACT_VERSION in payload.get('rules','') or new_config):
        return # Historical success replay keeps its original contract.
    if (marker not in (None, SEMANTIC_CONTRACT_VERSION) or SEMANTIC_CONTRACT not in system or not new_config
            or payload.get('prompt_sha256') != sha(system.encode())):
        raise FlashRunError('RISK_EXTRACT_CONTRACT_IDENTITY_INVALID')
    reader = parsed.get('reader_output') if isinstance(parsed, dict) else None
    notes = reader.get('risk_notes') if isinstance(reader, dict) else None
    if not isinstance(notes, list):
        raise FlashRunError('RISK_EXTRACT_SOURCE_UNSUPPORTED')
    if not notes:
        return
    body = payload['article_body']
    kind = payload.get('queue_task_kind')
    intervals = None
    sources = [body]
    if kind in {'announcement_reader_part', 'announcement_reader_synthesis'}:
        units = runner.build_source_unit_map(body, payload['body_sha256'])['units']
        if kind == 'announcement_reader_part':
            part = payload['part_descriptor']
            index = {u['source_unit_id']: i for i, u in enumerate(units)}
            start, end = part['start_source_unit_id'], part['end_source_unit_id']
            if not isinstance(start, str) or not isinstance(end, str):
                raise FlashRunError('RISK_EXTRACT_SOURCE_INTERVAL_INVALID')
            intervals = [(index.get(start.split('::')[-1]), index.get(end.split('::')[-1]))]
        else:
            # synthesis_intervals_from_reports returns inclusive zero-based unit
            # indices. The existing synthesis validator rechecks their report binding.
            intervals = payload['allowed_source_intervals']
        if not isinstance(intervals, (list, tuple)):
            raise FlashRunError('RISK_EXTRACT_SOURCE_INTERVAL_INVALID')
        allowed = set()
        for interval in intervals:
            if (not isinstance(interval, (list, tuple)) or len(interval) != 2
                    or any(type(i) is not int for i in interval)):
                raise FlashRunError('RISK_EXTRACT_SOURCE_INTERVAL_INVALID')
            start, end = interval
            if not 0 <= start <= end < len(units):
                raise FlashRunError('RISK_EXTRACT_SOURCE_INTERVAL_INVALID')
            allowed.update(range(start, end + 1))
        # Follow the same unit-union allowance as validate_synthesis_citations;
        # never join across an unseen source unit.
        spans = []
        for position in sorted(allowed):
            if spans and position == spans[-1][1] + 1:spans[-1][1] = position
            else:spans.append([position, position])
        sources = [body[units[start]['start_cp']:units[end]['end_cp']] for start, end in spans]
    normalize = lambda text: re.sub(r'\s+', '', text)
    sources = [normalize(text) for text in sources]
    if any(not isinstance(note, str) or not normalize(note)
           or not any(normalize(note) in source for source in sources) for note in notes):
        raise FlashRunError('RISK_EXTRACT_SOURCE_UNSUPPORTED')


def _single_http_canary_transport(canary, runner, *args, **kwargs):
    class OneRequest(canary.GatedStreamingTransport):
        def _stream_completion(self, *a, **kw):
            if self._round >= 1:
                raise runner.TransportError('SEMANTIC_CANARY_ONE_HTTP_LIMIT')
            return super()._stream_completion(*a, **kw)

        def _call_simple_workflow_lookup(self, *a, **kw):
            raise runner.TransportError('SEMANTIC_CANARY_ONE_HTTP_LIMIT')
    return OneRequest(*args, **kwargs)


def _semantic_repair_seed(state_root, job_id, report_sha256):
    if job_id != SEMANTIC_REPAIR['job_id']:
        return None
    if report_sha256 != SEMANTIC_REPAIR['report_sha256']:
        raise FlashRunError('SEMANTIC_REPAIR_REPORT_CHANGED')
    io = SafeRoot(state_root)
    prefix = f'announcement_flash/jobs/{job_id}/execution-extensions/'
    old_raw = io.read_bytes(prefix + SEMANTIC_REPAIR['predecessor_sha256'] + '.json')
    if sha(old_raw) != SEMANTIC_REPAIR['predecessor_sha256']:
        raise FlashRunError('SEMANTIC_REPAIR_PREDECESSOR_CHANGED')
    old_plan = _json(old_raw, 'SEMANTIC_REPAIR_PREDECESSOR_INVALID')
    review_raw = SafeRoot(SEMANTIC_REPAIR_EVIDENCE_ROOT).read_bytes('live-review/receipt.json')
    if sha(review_raw) != SEMANTIC_REPAIR['review_sha256']:
        raise FlashRunError('SEMANTIC_REPAIR_REVIEW_CHANGED')
    review = _json(review_raw, 'SEMANTIC_REPAIR_REVIEW_INVALID')
    binding = review.get('identity_binding', {})
    calls = review.get('actual_calls', {})
    if (review.get('status') != 'LIVE_RECOVERY_SEMANTIC_FAIL' or not isinstance(calls,dict)
            or any(calls.get(f)!=1 for f in ('new_queue_jobs','physical_new_attempts','request_rounds'))
            or calls.get('logical_attempt')!=2 or calls.get('new_key')!=SEMANTIC_REPAIR['queue_key']
            or review.get('job_id') != job_id or review.get('source_report_sha256') != report_sha256
            or review.get('execution_extension_sha256') != SEMANTIC_REPAIR['predecessor_sha256']
            or binding.get('new_key') != SEMANTIC_REPAIR['queue_key']):
        raise FlashRunError('SEMANTIC_REPAIR_REVIEW_BINDING_INVALID')
    root = state_root / 'announcement_flash/queue'
    jobs = _json(SafeRoot(root).read_bytes('queue-state.json'), 'SEMANTIC_REPAIR_QUEUE_INVALID')['jobs']
    item = jobs.get(SEMANTIC_REPAIR['queue_key'])
    if (not isinstance(item, dict) or sha(canonical(item)) != SEMANTIC_REPAIR['queue_record_sha256']
            or item.get('status') != 'SUCCEEDED' or item.get('attempt_count') != 1 or item.get('max_attempts') != 1):
        raise FlashRunError('SEMANTIC_REPAIR_SAVED_SUCCESS_CHANGED')
    refs = [('announcement_flash/queue/' + item['input_path'], 'payload_sha256'),
            ('announcement_flash/queue/' + item['raw_path'], 'raw_sha256'),
            ('announcement_flash/queue/' + item['validated_path'], 'validated_sha256')]
    trace = f"announcement_flash/evidence/streams/{SEMANTIC_REPAIR['queue_key']}/attempt-0001/"
    refs += [(trace + 'round-01.request-input.json', 'request_sha256'),
             (trace + 'stream-receipt.json', 'stream_sha256'), (trace + 'round-01.raw.sse', 'sse_sha256')]
    artifacts = []
    for ref, field in refs:
        if sha(io.read_bytes(ref)) != SEMANTIC_REPAIR[field]:
            raise FlashRunError('SEMANTIC_REPAIR_SAVED_ARTIFACT_CHANGED')
        artifacts.append({'root': 'state', 'artifact_ref': ref, 'sha256': SEMANTIC_REPAIR[field]})
    payload = _queue_payload(root, item)
    if (payload.get('execution_extension_sha256') != SEMANTIC_REPAIR['predecessor_sha256']
            or payload.get('recovery_of') != old_plan['failed']
            or any(payload.get(f) != old_plan['failed'][f] for f in ('article_id', 'source_sha256', 'body_sha256'))):
        raise FlashRunError('SEMANTIC_REPAIR_SOURCE_BINDING_INVALID')
    return {**SEMANTIC_REPAIR, 'logical_attempt': 3, 'max_canary_model_http_requests': 1,
            'acceptance_ref': SEMANTIC_ACCEPTANCE_REF}, old_plan, artifacts


def _semantic_canary_review(state_root, plan, extension_sha, key, item):
    """A mechanically successful third attempt still needs bound independent evidence."""
    if not plan.get('semantic_repair'):
        return 'PASS', None
    root = state_root / 'announcement_flash/queue'
    payload = _queue_payload(root, item)
    if (payload.get('execution_extension_sha256')!=extension_sha
            or payload.get('semantic_recovery_of')!=plan['semantic_repair']
            or payload.get('recovery_of')!=plan['failed']):
        raise FlashRunError('SEMANTIC_REVIEW_CANARY_IDENTITY_CHANGED')
    trace = f'announcement_flash/evidence/streams/{key}/attempt-0001/'
    io = SafeRoot(state_root)
    request_raw = io.read_bytes(trace + 'round-01.request-input.json')
    request = _json(request_raw, 'SEMANTIC_REVIEW_REQUEST_INVALID')
    stream = _json(io.read_bytes(trace + 'stream-receipt.json'), 'SEMANTIC_REVIEW_STREAM_INVALID')
    if (item.get('attempt_count') != 1 or len(stream.get('rounds', [])) != 1
            or request.get('messages') != payload.get('messages')
            or request.get('structured_outputs', {}).get('json') != payload.get('structured_output_schema')):
        raise FlashRunError('SEMANTIC_REVIEW_ACTUAL_REQUEST_CHANGED')
    try:
        raw = SafeRoot(SEMANTIC_REPAIR_EVIDENCE_ROOT).read_bytes(plan['semantic_repair']['acceptance_ref'])
    except FileNotFoundError:
        return 'PENDING', None
    receipt = _json(raw, 'SEMANTIC_REVIEW_INVALID')
    expected = {'schema': 'v4.manager_workbench.semantic_canary_acceptance.v1',
        'job_id': plan['job_id'], 'queue_key': key, 'report_sha256': plan['report_sha256'],
        'capture_sha256': plan['capture_product']['sha256'], 'extension_sha256': extension_sha,
        'payload_sha256': item['payload_sha256'], 'raw_sha256': item['raw_sha256'],
        'validated_sha256': item['validated_sha256'], 'request_sha256': sha(request_raw),
        **{f: payload[f] for f in ('article_id', 'source_sha256', 'body_sha256', 'prompt_sha256', 'configuration_sha256')},
        'actual_calls': 1}
    if any(receipt.get(f) != v for f, v in expected.items()) or not receipt.get('reviewer'):
        raise FlashRunError('SEMANTIC_REVIEW_BINDING_CHANGED')
    if receipt.get('verdict') == 'FAIL':
        return 'FAIL', sha(raw)
    if receipt.get('verdict') != 'PASS' or receipt.get('source_faithfulness') != 'PASS':
        raise FlashRunError('SEMANTIC_REVIEW_VERDICT_INVALID')
    return 'PASS', sha(raw)


def _semantic_quarantined_results(state_root, plan, checkpoint):
    if not plan.get('semantic_repair'):
        return []
    repair = plan['semantic_repair']
    result = [{'queue_key': repair['queue_key'], 'result_sha256': repair['validated_sha256']}]
    if checkpoint and checkpoint[1] != 'SUCCEEDED':
        jobs = _json(SafeRoot(state_root / 'announcement_flash/queue').read_bytes('queue-state.json'), 'SEMANTIC_QUEUE_INVALID')['jobs']
        item = jobs[checkpoint[0]]
        if item.get('status') == 'SUCCEEDED':
            result.append({'queue_key': checkpoint[0], 'result_sha256': item['validated_sha256']})
    return result


def _extension_plan(state_root: Path, capture_root: Path, job_id: str,
                    report_sha256: str, extension_sha256: str | None = None):
    """Read-only plan/verification; persistence belongs to the existing submit owner."""
    from v4.manager_workbench.announcement_preprocessing import build_extension, extension_entries
    from v4.manager_workbench.announcement_delivery import read as read_delivery
    if not JOB_ID_RE.fullmatch(job_id) or not SHA_RE.fullmatch(report_sha256):
        raise FlashRunError("EXTENSION_IDENTITY_INVALID")
    io=SafeRoot(state_root);prefix=f'announcement_flash/jobs/{job_id}'
    report_raw=io.read_bytes(prefix+'/preprocessing-report.json',max_bytes=64*1024*1024)
    if sha(report_raw)!=report_sha256:raise FlashRunError('EXTENSION_REPORT_CHANGED')
    report=_json(report_raw,'EXTENSION_REPORT_INVALID');extension_entries(report)
    if report['job_id']!=job_id:raise FlashRunError('EXTENSION_JOB_CHANGED')
    saved=None
    if extension_sha256 is None:
        try:extension_sha256=_json(io.read_bytes(prefix+'/execution-extensions/latest.json',max_bytes=4096),'EXTENSION_POINTER_INVALID')['sha256']
        except FileNotFoundError:pass
    if extension_sha256 is not None:
        if not SHA_RE.fullmatch(str(extension_sha256)):raise FlashRunError('EXTENSION_REFERENCE_INVALID')
        raw=io.read_bytes(prefix+'/execution-extensions/'+extension_sha256+'.json',max_bytes=64*1024*1024)
        if sha(raw)!=extension_sha256:raise FlashRunError('EXTENSION_SHA_CHANGED')
        saved=_json(raw,'EXTENSION_INVALID')
    successor=_semantic_repair_seed(state_root,job_id,report_sha256)
    original_saved=saved
    if successor:
        repair,old_plan,repair_artifacts=successor
        saved=old_plan
    jobs=_json(io.read_bytes('announcement_flash/queue/queue-state.json',max_bytes=64*1024*1024),'EXTENSION_QUEUE_INVALID')['jobs']
    if saved:
        failed=saved['failed'];old=jobs.get(failed['queue_key'])
        if not isinstance(old,dict) or sha(canonical(old))!=failed['queue_record_sha256']:
            raise FlashRunError('EXTENSION_ORIGINAL_FAILURE_CHANGED')
        artifacts=saved['source_artifacts']
    else:
        delivery,binding=read_delivery(io,job_id)
        failed_rows=[e for e in (delivery or {}).get('articles',[]) if e.get('article_id')==report['first_article_id'] and e.get('state')=='FAILED']
        if len(failed_rows)!=1:raise FlashRunError('EXTENSION_FAILED_FIRST_REQUIRED')
        key=failed_rows[0]['queue_key'];old=jobs.get(key)
        if (not isinstance(old,dict) or old.get('status')!='FAILED' or old.get('attempt_count')!=1
                or old.get('max_attempts')!=1 or old.get('last_error',{}).get('code')!='ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'):
            raise FlashRunError('EXTENSION_FAILURE_NOT_ELIGIBLE')
        payload=_queue_payload(state_root/'announcement_flash/queue',old)
        if (old.get('raw_path')!=f'jobs/{key}/attempt-0001.raw' or old.get('input_path')!=f'jobs/{key}/input.json'
                or len(old.get('attempts',[]))!=1 or old['attempts'][0].get('raw_sha256')!=old.get('raw_sha256')
                or sha(io.read_bytes('announcement_flash/queue/'+old['raw_path'],max_bytes=64*1024*1024))!=old.get('raw_sha256')):
            raise FlashRunError('EXTENSION_ORIGINAL_RAW_CHANGED')
        if payload.get('bounded_execution')!={'job_id':job_id,'report_sha256':report_sha256}:
            raise FlashRunError('EXTENSION_FAILURE_JOB_UNVERIFIED')
        failed={**{f:payload[f] for f in ('article_id','source_sha256','body_sha256')},
            'queue_key':key,'queue_record_sha256':sha(canonical(old)),'raw_sha256':old['raw_sha256'],
            'payload_sha256':old['payload_sha256'],'failure_code':old['last_error']['code'],'logical_attempt':2}
        trace_request=_json(io.read_bytes(f'announcement_flash/evidence/streams/{key}/attempt-0001/round-01.request-input.json',max_bytes=64*1024*1024),'EXTENSION_REQUEST_TRACE_INVALID')
        if trace_request.get('messages')!=payload.get('messages') or trace_request.get('structured_outputs',{}).get('json')!=payload.get('structured_output_schema'):
            raise FlashRunError('EXTENSION_REQUEST_TRACE_BINDING_CHANGED')
        artifacts=[]
        refs=[prefix+'/'+name for name in ('input.json','preprocessing-report.json','classification.json','classification-plan.json','classification-plan-binding.json','classification-model-plan.json','execution-request.json')]
        refs += [prefix+'/long-body/'+name for name in io.files(prefix+'/long-body')]
        refs += [binding['artifact_ref'],'announcement_flash/queue/'+old['input_path'],'announcement_flash/queue/'+old['raw_path']]
        trace=f'announcement_flash/evidence/streams/{key}/attempt-0001/'
        for name in ('round-01.request-input.json','round-01.raw.sse','stream-receipt.json'):
            try:io.read_bytes(trace+name,max_bytes=64*1024*1024)
            except FileNotFoundError:raise FlashRunError('EXTENSION_REQUEST_TRACE_MISSING')
            else:refs.append(trace+name)
        for ref in refs:
            raw=io.read_bytes(ref,max_bytes=64*1024*1024);artifacts.append({'root':'state','artifact_ref':ref,'sha256':sha(raw)})
        capture_ref=report['capture_product'];raw=SafeRoot(capture_root).read_bytes(capture_ref['artifact_ref'],max_bytes=256*1024*1024)
        if sha(raw)!=capture_ref['sha256']:raise FlashRunError('EXTENSION_CAPTURE_CHANGED')
        artifacts.append({'root':'capture',**capture_ref})
    if successor:
        artifacts=[*artifacts,*repair_artifacts]
        failed={**failed,'logical_attempt':3}
    for artifact in artifacts:
        root=io if artifact['root']=='state' else SafeRoot(capture_root)
        raw=root.read_bytes(artifact['artifact_ref'],max_bytes=256*1024*1024)
        if sha(raw)!=artifact['sha256']:raise FlashRunError('EXTENSION_SOURCE_ARTIFACT_CHANGED')
    helper=_load_helper();import batch_runner as runner
    contract=runner.load_active_contract(REPO_ROOT/'v4/manager_workbench/engines/announcement.py')
    material=_owned_request_material(helper,runner,contract)
    execution_contract={f:material[f] for f in ('prompt_sha256','configuration_sha256','schema_sha256','runtime_settings_sha256','model_settings_sha256')}
    execution_contract.update(validator_sha256=contract.source_sha256,
        implementation_sha256=sha(Path(__file__).read_bytes()),
        extension_contract_sha256=sha((REPO_ROOT/'v4/manager_workbench/announcement_preprocessing.py').read_bytes()),
        request_budget_sha256=sha((REPO_ROOT/'v4/manager_workbench/announcement_request_budget.py').read_bytes()),
        resume_contract_sha256=sha((REPO_ROOT/'v4/manager_workbench/announcement_resume.py').read_bytes()))
    plan=build_extension(report,report_sha256=report_sha256,source_artifacts=artifacts,failed=failed,execution_contract=execution_contract)
    if successor:
        plan['semantic_repair']=repair
    plan_sha=sha(canonical(plan)+b'\n')
    if successor:
        if original_saved is not None and extension_sha256!=repair['predecessor_sha256'] and (original_saved!=plan or extension_sha256!=plan_sha):
            raise FlashRunError('EXTENSION_CONTRACT_CHANGED')
    elif saved is not None and (saved!=plan or extension_sha256!=plan_sha):raise FlashRunError('EXTENSION_CONTRACT_CHANGED')
    return plan,plan_sha


def _extension_checkpoint(state_root: Path, plan: dict[str, Any], extension_sha: str):
    helper=_load_helper();import batch_runner as runner
    import announcement_queue as queue_module
    import build_length_canary as length_canary
    contract=runner.load_active_contract(REPO_ROOT/'v4/manager_workbench/engines/announcement.py')
    material=_owned_request_material(helper,runner,contract)
    validator=_validator(queue_module,runner,contract,material,length_canary)
    root=state_root/'announcement_flash/queue'
    jobs=_json(SafeRoot(root).read_bytes('queue-state.json',max_bytes=64*1024*1024),'EXTENSION_QUEUE_INVALID')['jobs']
    matches=[]
    for key,item in jobs.items():
        if item.get('identity',{}).get('article_id')!=plan['failed']['article_id']:continue
        payload=_queue_payload(root,item)
        if payload.get('execution_extension_sha256')!=extension_sha:continue
        if (payload.get('recovery_of')!=plan['failed'] or item.get('queue_id')!=QUEUE_ID
                or any(payload.get(f)!=plan['failed'][f] for f in ('source_sha256','body_sha256'))
                or queue_module.SerialAnnouncementQueue._identity(payload)!=item.get('identity')
                or sha(canonical(item['identity']))!=key):
            raise FlashRunError('EXTENSION_CHECKPOINT_INVALID')
        if item.get('status')=='PENDING' and item.get('attempt_count')!=0:raise FlashRunError('EXTENSION_PENDING_ATTEMPT_CONFLICT')
        if item.get('status')=='SUCCEEDED':
            result,_v,raw_sha=_read_internal_validated_result(root,item)
            raw=_read_json_file(root/item['raw_path'],raw_sha,'EXTENSION_SAVED_RAW_CHANGED')
            if validator(SimpleNamespace(payload=payload),raw)!=result:raise FlashRunError('EXTENSION_CHECKPOINT_REPLAY_CHANGED')
        status=item['status']
        if status=='SUCCEEDED' and plan.get('semantic_repair'):
            try:
                review,_receipt_sha=_semantic_canary_review(state_root,plan,extension_sha,key,item)
            except (OSError,KeyError,TypeError,ValueError,FlashRunError) as exc:
                # Source/identity/raw replay above already proved this exact result.
                # Invalid approval evidence must not erase its display quarantine.
                blocked=FlashRunError(getattr(exc,'code','SEMANTIC_REVIEW_EVIDENCE_INVALID'))
                blocked.quarantined_results=_semantic_quarantined_results(state_root,plan,(key,'AWAITING_SEMANTIC_REVIEW'))
                raise blocked from None
            status={'PENDING':'AWAITING_SEMANTIC_REVIEW','FAIL':'SEMANTIC_REVIEW_FAILED','PASS':'SUCCEEDED'}[review]
        matches.append((key,status))
    if len(matches)>1:raise FlashRunError('EXTENSION_CHECKPOINT_AMBIGUOUS')
    return matches[0] if matches else None


def _extension_saved_task(payload, queue, queue_root, validator, *, failed_key, extension_sha256, semantic_repair=None):
    """Identity-based reuse across prompt versions, with full raw replay."""
    matches=[]
    for key,item in queue._load_state()['jobs'].items():
        identity=item.get('identity',{})
        if (item.get('queue_id')!=QUEUE_ID or any(identity.get(f)!=payload.get(f) for f in ('article_id','source_sha256','body_sha256','date','market','model_id'))):continue
        stored=_queue_payload(queue_root,item)
        if (stored.get('article_body')!=payload.get('article_body')
                or stored.get('article_metadata',{}).get('symbol')!=payload['article_metadata'].get('symbol')):
            raise FlashRunError('EXTENSION_ISSUER_CONFLICT')
        kind=payload.get('queue_task_kind');stored_kind=stored.get('queue_task_kind')
        # A complete synthesis/ordinary result may cover the same full source;
        # part reuse always requires the exact frozen part and plan.
        if kind=='announcement_reader_part':
            if stored_kind!=kind or stored.get('chunk_plan_sha256')!=payload.get('chunk_plan_sha256') or stored.get('part_descriptor')!=payload.get('part_descriptor'):continue
        elif stored_kind=='announcement_reader_part':continue
        if _stable_queue_identity(queue,stored)!=key or queue._identity(stored)!=identity:
            raise FlashRunError('EXTENSION_SAVED_IDENTITY_CHANGED')
        if semantic_repair and key==semantic_repair['queue_key']:
            if (sha(canonical(item))!=semantic_repair['queue_record_sha256']
                    or item.get('raw_sha256')!=semantic_repair['raw_sha256']
                    or item.get('validated_sha256')!=semantic_repair['validated_sha256']):
                raise FlashRunError('SEMANTIC_REPAIR_SAVED_SUCCESS_CHANGED')
            continue # This exact independent FAIL is the sole success-reuse exception.
        if item.get('status')=='SUCCEEDED':
            result,_result_sha,raw_sha=_read_internal_validated_result(queue_root,item)
            raw=_read_json_file(queue_root/item['raw_path'],raw_sha,'EXTENSION_SAVED_RAW_CHANGED')
            if validator(SimpleNamespace(payload=stored),raw)!=result:
                raise FlashRunError('EXTENSION_SAVED_RESULT_REPLAY_CHANGED')
            matches.append((key,item))
        elif payload.get('_complete_probe'):
            continue
        elif key==failed_key:
            continue # Only this immutable original failure has a repair mandate.
        elif stored.get('execution_extension_sha256')==extension_sha256:
            if canonical(stored)!=canonical(payload):raise FlashRunError('EXTENSION_PAYLOAD_CHANGED')
            matches.append((key,item))
        else:
            raise FlashRunError('EXTENSION_OTHER_PRIOR_STATUS_PRESERVED')
    succeeded=[m for m in matches if m[1]['status']=='SUCCEEDED']
    if succeeded:
        outputs=[_read_internal_validated_result(queue_root,item)[0] for _key,item in succeeded]
        if any(output!=outputs[0] for output in outputs[1:]):raise FlashRunError('EXTENSION_SAVED_SUCCESS_CONFLICT')
        # Never enqueue a new prompt-version key over a valid saved full result.
        return sorted(succeeded,key=lambda m:m[0])[0]
    if len(matches)>1:raise FlashRunError('EXTENSION_TASK_AMBIGUOUS')
    return matches[0] if matches else None


def _extension_payload(payload, material, extension, extension_sha, count_tokens, cap):
    """Compatibility facade; final construction/preflight belongs to its module."""
    from v4.manager_workbench.announcement_request_budget import extension_payload, RequestBudgetError
    try:
        return extension_payload(payload, material, extension, extension_sha, count_tokens, cap)
    except RequestBudgetError as exc:
        failure = FlashRunError(exc.code)
        failure.budget_error = exc
        raise failure from None


def _extension_prepared_subset(entries, payloads, long_specs):
    """Select frozen eligible versions, then require complete, exact coverage.

    Source preparation also retains historical and USER_STOPPED versions. They
    are not execution work. A missing/drifted eligible identity still fails.
    """
    expected={(e['article_id'],e['source_sha256'],e['body_sha256'],e['source_date'],e['symbol']):e for e in entries}
    def identity(article):
        metadata=article.get('article_metadata',{})
        return (article.get('article_id'),article.get('source_sha256'),article.get('body_sha256'),
                article.get('date',metadata.get('publication_date')),metadata.get('symbol'))
    ordinary=[p for p in payloads if identity(p) in expected]
    long={aid:spec for aid,spec in long_specs.items() if identity(spec['article']) in expected}
    short_ids={identity(p) for p in ordinary};long_ids={identity(s['article']) for s in long.values()}
    expected_short={key for key,e in expected.items() if e['primary_disposition']=='MODEL_ORDINARY'}
    expected_long={key for key,e in expected.items() if e['primary_disposition']=='MODEL_LONG'}
    if (len(expected)!=len(entries) or short_ids!=expected_short or long_ids!=expected_long
            or len(ordinary)+len(long)!=len(entries)
            or any(p['article_metadata'].get('publication_date')!=p.get('date') for p in ordinary)
            or any(aid!=spec['article']['article_id'] or len(spec['part_payloads'])!=expected[identity(spec['article'])]['part_count']
                or any(identity(p)!=identity(spec['article']) or p['article_metadata'].get('publication_date')!=p.get('date') for p in spec['part_payloads'])
                for aid,spec in long.items())):
        raise FlashRunError('EXTENSION_PREPARED_COVERAGE_CHANGED')
    return ordinary,long


def _execute_extension(input_value, *, state_root, capture_root, job_id, report, report_sha256,
                       extension_sha256, phase, payloads, long_specs, queue, helper, runner,
                       contract, canary, queue_module, length_canary, count_tokens, progress, stop_requested):
    """Additional phases of the same source-preparation/queue/delivery pipeline."""
    from v4.manager_workbench import announcement_chunks as chunks
    from v4.manager_workbench.announcement_delivery import read as read_delivery, publish
    from v4.manager_workbench.announcement_request_budget import preflight, finalize_extension_payload, RequestBudgetError
    from v4.manager_workbench.announcement_resume import request_usage, recovery_description, budget_failure, budget_identity
    extension,actual_sha=_extension_plan(state_root,capture_root,job_id,report_sha256,extension_sha256)
    if actual_sha!=extension_sha256 or phase not in {'RECOVER_FAILED','CONTINUE_REMAINING'}:
        raise FlashRunError('EXTENSION_EXECUTION_BINDING_INVALID')
    material=_owned_request_material(helper,runner,contract)
    validator=_validator(queue_module,runner,contract,material,length_canary)
    io=SafeRoot(state_root);queue_root=state_root/'announcement_flash/queue'
    delivered,_binding=read_delivery(io,job_id)
    if not delivered or delivered['preprocessing_report_sha256']!=report_sha256:raise FlashRunError('EXTENSION_DELIVERY_CHANGED')
    entries=extension['entries'];versions={(e['article_id'],e['source_sha256'],e['body_sha256']) for e in entries}
    payloads,long_specs=_extension_prepared_subset(entries,payloads,long_specs)
    by_identity={(e['article_id'],e.get('body_sha256')):copy.deepcopy(e) for e in delivered['articles']}
    failed=extension['failed'];failed_id=failed['article_id'];completed=0;dispatched=[];system_stop=None
    context=material['runtime_limits']['context_limit_tokens'];reserve=material['configuration_material']['max_completion_tokens']
    if type(context) is not int or type(reserve) is not int or reserve < 0:
        raise FlashRunError('FLASH_RUNTIME_TOKEN_BUDGET_INVALID')
    hard=min(chunks.SYNTHESIS_TOKEN_CAP,context-reserve-chunks.TOKEN_SAFETY_MARGIN)
    if hard < 1:raise FlashRunError('FLASH_RUNTIME_TOKEN_BUDGET_INVALID')
    part_cap=min(chunks.PART_TARGET_TOKEN_CAP,hard)
    def saved(p):return _extension_saved_task(p,queue,queue_root,validator,failed_key=failed['queue_key'],extension_sha256=extension_sha256,semantic_repair=extension.get('semantic_repair'))
    def usage():return request_usage(extension,queue._load_state()['jobs'],queue_id=QUEUE_ID)
    def check_known_failure(p,cap,code):
        old=by_identity[(p['article_id'],p['body_sha256'])]
        identity=budget_identity(extension,p,code=code,cap=cap)
        for failure in old.get('request_budget_failures',[]):
            if failure['identity']==identity:
                raise RequestBudgetError(code,{**p,'prompt_tokens_exact':failure['prompt_tokens_exact']},cap)
    def prepare(base,cap):
        final=finalize_extension_payload(base,material,extension,extension_sha256)
        check_known_failure(final,cap,'EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED')
        return _extension_payload(base,material,extension,extension_sha256,count_tokens,cap)
    def isolate(exc):
        p=exc.payload;ident=(p['article_id'],p['body_sha256']);old=by_identity[ident]
        failure=budget_failure(extension,p,phase=phase,usage=usage(),code=exc.code,cap=exc.cap)
        history=copy.deepcopy(old.get('request_budget_failures',[]))
        previous=next((f for f in history if f['fingerprint']==failure['fingerprint']),None)
        if previous is None:history.append(failure)
        else:failure=previous
        by_identity[ident]={**old,'state':'FAILED','failure_code':exc.code,
            'request_budget_failure':failure,'request_budget_failures':history}
    def publish_progress(step='EXTENSION_PROGRESS',current=None):
        articles=list(by_identity.values());counts=dict(Counter(e['state'] for e in articles))
        model=[e for e in articles if (e['article_id'],e.get('source_sha256'),e.get('body_sha256')) in versions]
        model_counts=dict(Counter(e['state'] for e in model))
        selected=[e for e in articles if e.get('state')=='SUCCEEDED' and e.get('disposition') in {'SELECTED_EVENT','SELECTED_PERFORMANCE'} and e.get('direction')=='POSITIVE']
        state='USER_STOPPED' if (system_stop or {}).get('failure_code')=='USER_STOPPED' else 'PARTIAL' if system_stop or any(e['state'] in {'FAILED','PENDING','DEFERRED'} for e in model) else 'SUCCEEDED'
        binding=publish(io,job_id,{**delivered,'state':state,'articles':articles,'counts':counts,
            'stocks':_aggregate(selected),'pending':[e for e in model if e['state'] in {'PENDING','DEFERRED'}],
            'failures':[e for e in model if e['state']=='FAILED'],'execution_extension_sha256':extension_sha256,
            'model_progress':{'total':len(entries),'counts':model_counts,'current_article_id':current},
            'model_requests_this_invocation':completed,'system_stop':system_stop,
            'recovery':recovery_description(extension,phase=phase,usage=usage())})
        progress({'step':step,'preprocessing':{'sha256':report_sha256},'delivery':binding,'execution_extension_sha256':extension_sha256,
            'completed':model_counts.get('SUCCEEDED',0),'total':len(entries),'failed':model_counts.get('FAILED',0),
            'current_article_id':current,'updated_at':datetime.now(timezone.utc).isoformat()})
    def task(p):
        nonlocal completed,system_stop
        if phase=='CONTINUE_REMAINING' and extension.get('semantic_repair'):
            review,current_approval=_semantic_canary_review(state_root,extension,extension_sha256,*recovered)
            if review!='PASS' or current_approval!=approval_sha:raise FlashRunError('EXTENSION_SEMANTIC_APPROVAL_CHANGED')
        prior=saved(p)
        if prior is None or prior[1]['status']=='PENDING':
            preflight(p,count_tokens,part_cap if p.get('queue_task_kind')=='announcement_reader_part' else hard,
                code='EXTENSION_SYNTHESIS_TOKEN_CAP_EXCEEDED' if p.get('queue_task_kind')=='announcement_reader_synthesis' else 'EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED')
            if usage()['remaining_model_requests']==0:
                system_stop={'failure_code':'EXTENSION_REQUEST_BUDGET_EXHAUSTED','queue_action':'DEFERRED_NO_ATTEMPT'}
                return None
        if prior is None:
            if system_stop or stop_requested():system_stop=system_stop or _user_stop_receipt();return None
            item=queue.enqueue(p);key=item['idempotency_key']
        else:key,item=prior
        if item['status']=='RUNNING':raise FlashRunError('EXTENSION_ACTIVE_TASK_OWNER')
        if item['status']=='PENDING':
            if item.get('attempt_count')!=0:raise FlashRunError('EXTENSION_PENDING_ATTEMPT_CONFLICT')
            transport_factory=(lambda *a,**kw:_single_http_canary_transport(canary,runner,*a,**kw)) if extension.get('semantic_repair') and phase=='RECOVER_FAILED' else canary.GatedStreamingTransport
            transport=transport_factory(runner.load_local_api_key(),state_root/'announcement_flash/evidence',
                expected_runtime_settings_sha256=material['runtime_settings_sha256'],expected_model_settings_sha256=material['model_settings_sha256'])
            try:
                executor=_transport_executor(queue_module,transport,runner,material,state_root/'announcement_flash/evidence',lambda _j,_e:None)
                before=completed
                publish_progress('EXTENSION_MODEL_REQUEST',p['article_id'])
                try:
                    completed,system_stop=_dispatch_pending_queue_keys(queue,executor,validator,{key},completed=completed,
                        max_model_calls=completed+1,dispatched_keys=dispatched,on_result=lambda _n:None,stop_requested=stop_requested)
                except queue_module.ModelSlotBusy:
                    system_stop={'failure_code':'MODEL_LOCK_BUSY','queue_action':'DEFERRED_NO_ATTEMPT'}
                if completed==before and system_stop is None:
                    system_stop={'failure_code':'MODEL_LOCK_BUSY','queue_action':'DEFERRED_NO_ATTEMPT'}
            finally:transport.close()
            item=queue._load_state()['jobs'][key]
        return key,item
    def record(p,outcome):
        if outcome is None:return
        key,item=outcome;ident=(p['article_id'],p['body_sha256']);old=by_identity[ident]
        if item['status']=='SUCCEEDED':
            stored,reader=_queue_result(queue_root,item)
            by_identity[ident]={**old,**_public_article(p['article_id'],stored,reader),'state':'SUCCEEDED','queue_key':key,
                'result_ref':item['validated_path'],'result_sha256':item['validated_sha256'],
                'source_coverage':'COMPLETE_SYNTHESIS' if stored.get('queue_task_kind')=='announcement_reader_synthesis' else 'COMPLETE_ARTICLE',
                'processing_identity':copy.deepcopy(item['identity'])}
        elif item['status']=='FAILED':
            by_identity[ident]={**old,'state':'FAILED','queue_key':key,'failure_code':item.get('last_error',{}).get('code','MODEL_ATTEMPT_FAILED')}
        else:by_identity[ident]={**old,'state':'PENDING','queue_key':key}
    prepared={p['article_id']:p for p in payloads}
    # Replaying an already attempted recovery is read-only and idempotent.
    recovered=saved({**prepared[failed_id],'_complete_probe':True})
    if phase=='CONTINUE_REMAINING' and (not recovered or recovered[1]['status']!='SUCCEEDED'):
        raise FlashRunError('EXTENSION_RECOVERY_CANARY_NOT_SUCCEEDED')
    if phase=='CONTINUE_REMAINING' and extension.get('semantic_repair'):
        review,approval_sha=_semantic_canary_review(state_root,extension,extension_sha256,*recovered)
        if review!='PASS':raise FlashRunError('EXTENSION_SEMANTIC_CANARY_NOT_ACCEPTED')
        request_binding=_json(io.read_bytes(f'announcement_flash/jobs/{job_id}/extension-request.json'),'EXTENSION_REQUEST_INVALID')
        if request_binding.get('artifact_ref')!=f"announcement_flash/jobs/{job_id}/extension-requests/{request_binding.get('sha256')}.json":
            raise FlashRunError('EXTENSION_REQUEST_REFERENCE_INVALID')
        request_raw=io.read_bytes(request_binding['artifact_ref'])
        request=_json(request_raw,'EXTENSION_REQUEST_INVALID')
        if (sha(request_raw)!=request_binding.get('sha256') or request.get('phase')!=phase
                or request.get('report_sha256')!=report_sha256 or request.get('extension_sha256')!=extension_sha256
                or request.get('semantic_review_sha256')!=approval_sha):
            raise FlashRunError('EXTENSION_SEMANTIC_APPROVAL_CHANGED')
    ordered=[e for e in entries if e['article_id']==failed_id] if phase=='RECOVER_FAILED' else entries
    for e in ordered:
        aid=e['article_id'];ident=(aid,e['body_sha256'])
        if stop_requested():system_stop=_user_stop_receipt();break
        if system_stop:break
        try:
            if aid in prepared:
                complete=saved({**prepared[aid],'_complete_probe':True})
                if complete and complete[1]['status']=='SUCCEEDED':
                    record(prepared[aid],complete);publish_progress(current=aid);continue
                p=prepare(prepared[aid],hard)
                record(p,task(p));publish_progress(current=aid)
                continue
            spec=long_specs[aid]
            # Reuse a complete saved synthesis before scheduling any part.
            probe={**spec['article'],'date':spec['article']['article_metadata']['publication_date'],'market':'HK',
                   'model_id':runner.MODEL_ID,'queue_task_kind':'announcement_reader_synthesis','_complete_probe':True}
            complete=saved(probe)
            if complete and complete[1]['status']=='SUCCEEDED':record(probe,complete);publish_progress(current=aid);continue
            reports=[];part_shas=[];part_failed=False
            for part,base in zip(spec['plan']['parts'],spec['part_payloads']):
                outcome=saved({**base,'_complete_probe':True})
                if not outcome or outcome[1]['status']!='SUCCEEDED':
                    p=prepare(base,part_cap)
                    outcome=task(p)
                if outcome is None or outcome[1]['status']!='SUCCEEDED':
                    if outcome and outcome[1]['status']=='FAILED':
                        by_identity[ident]={**by_identity[ident],'state':'FAILED','failure_code':outcome[1].get('last_error',{}).get('code'),'queue_key':outcome[0]};part_failed=True
                    break
                item=outcome[1];result,result_sha,raw_sha=_read_internal_validated_result(queue_root,item)
                reports.append({'part_index':part['part_index'],'part_count':part['part_count'],'part_descriptor':part,
                    'part_sha256':part['part_sha256'],'part_result_sha256':result_sha,'part_raw_response_sha256':raw_sha,
                    'reader_report':result['reader_output'],'citation_ranges':result['citation_ranges']});part_shas.append(result_sha)
                by_identity[ident]={**by_identity[ident],'state':'PENDING','parts_complete':len(reports),'parts_total':len(spec['plan']['parts'])}
                publish_progress(current=aid)
            if len(reports)!=len(spec['plan']['parts']):
                if not part_failed:by_identity[ident]={**by_identity[ident],'state':'PENDING'}
                publish_progress(current=aid);continue
            synthesis_input={'schema':chunks.SYNTHESIS_INPUT_SCHEMA,'article_id':aid,'source_sha256':e['source_sha256'],
                'body_sha256':e['body_sha256'],'source_unit_map_sha256':spec['unit_map']['source_unit_map_sha256'],
                'plan_sha256':spec['plan']['plan_sha256'],'batch_binding_sha256':spec['plan']['batch_binding_sha256'],
                'frozen_recovery_manifest_sha256':None,'root_batch_job_id':None,'target_date':input_value['target_date'],
                'cutoff':input_value['cutoff'],'membership_authority_sha256':spec['article']['article_metadata'].get('membership_authority_sha256'),
                'part_count':len(reports),'part_reports':reports,'cross_part_fixed_fact_ledger':chunks.cross_part_ledger(
                    spec['article']['fixed_fact_ledger'],spec['unit_map'],spec['plan'],model_ledger=lambda v:runner._simple_model_fixed_fact_ledger_for_article(v,aid))}
            input_sha=sha(canonical(synthesis_input));synthesis_input['synthesis_input_sha256']=input_sha
            system=chunks.reader_task_system_prompt(material['prompt'],'synthesis')+'\n\n'+chunks.SYNTHESIS_ADDENDUM
            messages=_synthesis_messages(system_prompt=system,article_id=aid,article_metadata=spec['article']['article_metadata'],synthesis_input=synthesis_input,input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)
            p={**spec['article'],'date':spec['article']['article_metadata']['publication_date'],'market':'HK','model_id':runner.MODEL_ID,
                'prompt_sha256':sha(system.encode()),'configuration_sha256':material['configuration_sha256'],
                'rules':f'execution-extension:{extension_sha256}+synthesis:{input_sha}','role':'announcement_reader_synthesis',
                'stage':'v4_manager_announcement_flash_long_body_synthesis_v1','queue_task_kind':'announcement_reader_synthesis',
                'chunk_plan_sha256':spec['plan']['plan_sha256'],'synthesis_input_sha256':input_sha,'part_result_sha256s':part_shas,
                'synthesis_input':synthesis_input,'allowed_source_intervals':chunks.synthesis_intervals_from_reports(reports,article_id=aid,unit_map=spec['unit_map']),
                'source_unit_map_sha256':spec['unit_map']['source_unit_map_sha256'],'validated_article_batch':spec['batch'],
                'messages':messages,'structured_output_schema':chunks.empty_reader_fixed_fields_schema(material['schema']),
                'workflow_profile':PROFILE,'citation_protocol':material['citation_protocol'],'input_schema':chunks.SYNTHESIS_INPUT_SCHEMA,
                'prompt_token_cap':hard,'context_limit_tokens':context,
                'completion_reserve_tokens':reserve,'token_safety_margin':chunks.TOKEN_SAFETY_MARGIN,
                'batch_binding_sha256':spec['plan']['batch_binding_sha256'],'execution_extension_sha256':extension_sha256,
                'semantic_contract_version':material['configuration_material']['semantic_contract_version']}
            check_known_failure(p,hard,'EXTENSION_SYNTHESIS_TOKEN_CAP_EXCEEDED')
            p=preflight(p,count_tokens,hard,code='EXTENSION_SYNTHESIS_TOKEN_CAP_EXCEEDED')
            record(p,task(p));publish_progress(current=aid)
        except (RequestBudgetError,FlashRunError) as exc:
            budget=exc if isinstance(exc,RequestBudgetError) else getattr(exc,'budget_error',None)
            if budget is None:raise
            isolate(budget);publish_progress(current=aid)
    publish_progress('EXTENSION_DONE')
    model=[by_identity[(e['article_id'],e['body_sha256'])] for e in entries];counts=Counter(e['state'] for e in model)
    return {'state':'USER_STOPPED' if (system_stop or {}).get('failure_code')=='USER_STOPPED' else 'PARTIAL' if system_stop or counts['FAILED'] or counts['PENDING'] or counts['DEFERRED'] else 'SUCCEEDED',
        'execution_phase':phase,'execution_extension_sha256':extension_sha256,'preprocessing':{'sha256':report_sha256},
        'system_stop':system_stop,'dispatched_keys':dispatched,'model_requests':completed,
        'counts':{'queue':{'succeeded':counts['SUCCEEDED'],'failed':counts['FAILED'],'pending':counts['PENDING']+counts['DEFERRED']}}}


def _run(input_value: dict[str, Any], *, state_root: Path, capture_root: Path,
         job_id: str, progress: Callable[[dict[str, Any]], None],
         shared_root: Path | None = None,
         resume_same_batch_pending: bool = False,
         resume_frozen_batch: bool = False,
         resume_action: str | None = None,
         max_model_calls: int | None = None,
         resume_source_job_id: str | None = None,
         resume_source_input_sha256: str | None = None,
         materialize_only: bool = False,
         materialization_failure: dict[str, Any] | None = None,
         require_classification_policy: bool = False,
         stop_requested: Callable[[], bool] = lambda: False,
         preprocess_only: bool = False, execute_report_sha256: str | None = None,
         execution_phase: str | None = None, extension_sha256: str | None = None,
         legacy_gate: dict[str, Any] | None = None,
         preparation_guard: Callable[..., None] | None = None) -> dict[str, Any]:
    if preparation_guard is not None:
        if (not preprocess_only or not require_classification_policy or any((resume_same_batch_pending,
                resume_frozen_batch, resume_action, materialize_only, execute_report_sha256,
                execution_phase, extension_sha256)) or max_model_calls is not None):
            raise FlashRunError('ISOLATED_PREPARATION_MODE_INVALID')
        preparation_guard()
    if legacy_gate is not None:
        _test_legacy_gate(legacy_gate, 'qwen3_8_flash_next')
    from v4.manager_workbench.announcement_classification import (
        MODEL, QUARANTINE, ROUTINE, STRUCTURED, classify, frozen_policy,
    )
    classification_policy = frozen_policy(input_value, allow_replay=True)
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

    if require_classification_policy and classification_policy is None:
        raise FlashRunError('CLASSIFICATION_POLICY_REQUIRED_FOR_NEW_ENTRY')

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
    if resume_frozen_batch and resume_action not in {"CANARY", "CONTINUE"}:
        raise FlashRunError("FROZEN_RESUME_ACTION_INVALID")
    if not resume_frozen_batch and resume_action is not None:
        raise FlashRunError("FROZEN_RESUME_ACTION_INVALID")
    if resume_frozen_batch and ((resume_action == "CANARY" and max_model_calls != 1)
                                or (resume_action == "CONTINUE" and max_model_calls is not None)):
        raise FlashRunError("FROZEN_RESUME_ACTION_CALL_LIMIT_MISMATCH")
    if resume_same_batch_pending and resume_frozen_batch:
        raise FlashRunError("RESUME_MODE_AMBIGUOUS")
    if resume_same_batch_pending:
        _validate_recovery_lock(input_value, capture_ref, capture_product, membership_gate)
        parent_raw = SafeRoot(state_root).read_bytes(
            f"announcement_flash/jobs/{recovery_lock['parent_job_id']}/input.json", max_bytes=1024 * 1024)
        frozen_policy(input_value, _json(parent_raw, "RECOVERY_PARENT_INPUT_INVALID"))
    elif resume_frozen_batch:
        if isinstance(recovery_lock, dict):
            raise FlashRunError("FROZEN_RESUME_RECOVERY_LOCK_UNSUPPORTED")
        if (not isinstance(resume_source_job_id, str) or not JOB_ID_RE.fullmatch(resume_source_job_id)
                or not isinstance(resume_source_input_sha256, str)
                or not SHA_RE.fullmatch(resume_source_input_sha256)):
            raise FlashRunError("FROZEN_RESUME_SOURCE_BINDING_INVALID")
        resume_source = input_value.get("resume_source")
        if resume_action == "CONTINUE" and (
                not isinstance(resume_source, dict)
                or resume_source.get("resume_action") != "CONTINUE"
                or resume_source.get("canary_passed") is not True
                or resume_source.get("legacy_failed_canary") is not None):
            raise FlashRunError("FROZEN_RESUME_CANARY_NOT_PASSED")
        if resume_action == "CANARY" and isinstance(resume_source, dict):
            legacy = resume_source.get("legacy_failed_canary")
            if legacy is not None:
                root = input_value.get("resume_root")
                if (not isinstance(legacy, dict)
                        or legacy.get("key") != resume_source.get("canary_key")
                        or legacy.get("source_job_id") != resume_source.get("source_job_id")
                        or legacy.get("source_input_sha256") != resume_source.get("source_input_sha256")
                        or legacy.get("root_job_id") != (root.get("source_job_id") if isinstance(root, dict) else None)
                        or legacy.get("root_input_sha256") != (
                            root.get("source_input_sha256") if isinstance(root, dict) else None)
                        or resume_source.get("canary_status") != "FAILED"
                        or resume_source.get("canary_passed") is not False):
                    raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_BINDING_INVALID")
    elif isinstance(recovery_lock, dict):
        raise FlashRunError("RECOVERY_CONTINUATION_FLAG_REQUIRED")

    contract = runner.load_active_contract(REPO_ROOT / "v4/manager_workbench/engines/announcement.py")
    request_material = _owned_request_material(helper, runner, contract)
    if execute_report_sha256 is not None:
        frozen_bytes=SafeRoot(state_root).read_bytes(f"announcement_flash/jobs/{job_id}/preprocessing-report.json",max_bytes=64*1024*1024)
        if sha(frozen_bytes)!=execute_report_sha256:raise FlashRunError("PREPROCESSING_REPORT_SHA_CHANGED")
        frozen=_json(frozen_bytes,"PREPROCESSING_REPORT_INVALID")
        if frozen["processing_contract"]["prompt_sha256"] != request_material["prompt_sha256"]:
            # Replay the original frozen preparation identity; new execution is
            # separately versioned below, never written over the original report.
            request_material = _owned_request_material(helper, runner, contract, semantic_contract=False)
    configuration_material = request_material.get("configuration_material", {})
    if (request_material.get("workflow_profile") != runner.SIMPLE_WORKFLOW_RANGE_PROFILE
            or request_material.get("citation_protocol") != runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
            or request_material.get("sampling_policy", {}).get("request_temperature") != 0.0
            or configuration_material.get("model_id") != runner.MODEL_ID
            or configuration_material.get("request_temperature") != 0.0
            or configuration_material.get("enable_thinking") is not False):
        raise FlashRunError("FLASH_REQUEST_PROFILE_INVALID")
    resume_root = input_value.get("resume_root") if resume_frozen_batch else None
    frozen_root_job_id = None
    frozen_root_input_sha256 = None
    frozen_root_input = None
    frozen_resume_binding = None
    prior_resume = (input_value.get("resume_source")
                    if resume_frozen_batch and isinstance(input_value.get("resume_source"), dict) else {})
    transport_recovery_plan = (prior_resume.get("transport_recovery")
                               if isinstance(prior_resume, dict) else None)
    if resume_frozen_batch:
        if (not isinstance(resume_root, dict)
                or not isinstance(resume_root.get("source_job_id"), str)
                or not isinstance(resume_root.get("source_input_sha256"), str)):
            raise FlashRunError("FROZEN_RESUME_ROOT_BINDING_INVALID")
        frozen_root_job_id = resume_root["source_job_id"]
        frozen_root_input_sha256 = resume_root["source_input_sha256"]
        frozen_root_input = _verify_resume_root_input(
            SafeRoot(state_root), frozen_root_job_id, frozen_root_input_sha256,
            str(input_value.get("target_date", "")), input_value)
        capture_binding = input_value.get("capture_product")
        gate_binding = input_value.get("membership_gate")
        if not isinstance(capture_binding, dict) or not isinstance(gate_binding, dict):
            raise FlashRunError("FROZEN_RESUME_INPUT_CONTRACT_INVALID")
        frozen_resume_binding = {
            "source_job_id": frozen_root_job_id,
            "source_input_sha256": frozen_root_input_sha256,
            "target_date": input_value.get("target_date"),
            "cutoff": input_value.get("cutoff"),
            "capture_product_sha256": capture_binding.get("sha256"),
            "membership_authority_sha256": gate_binding.get("authority_sha256"),
        }
        if transport_recovery_plan is not None:
            if (not isinstance(transport_recovery_plan, dict)
                    or transport_recovery_plan.get("schema") != TRANSPORT_RECOVERY_SCHEMA
                    or prior_resume.get("source_job_id") != resume_source_job_id
                    or prior_resume.get("source_input_sha256") != resume_source_input_sha256):
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_INPUT_BINDING_INVALID")
            _verify_transport_original_root(SafeRoot(state_root), input_value, transport_recovery_plan)
            _verify_resume_source(
                SafeRoot(state_root), capture_root, str(resume_source_job_id), input_value["target_date"],
                {field: prior_resume.get(field) for field in (
                    "source_input_sha256", "source_progress_sha256", "source_queue_state_sha256")},
                expected_transport_recovery=transport_recovery_plan)
    request_material = _request_material_with_memory_identity(
        request_material, state_root, transport_recovery_plan, getattr(runner, "OMLX_SETTINGS_PATH", None))
    configuration_material = request_material.get("configuration_material", {})
    classification_plan, classification_binding = None, None
    if preparation_guard is not None:
        preparation_guard(request_material, runner)
        _announcement_execution_guard(runner, request_material)()
    if classification_policy is not None:
        classification_plan, classification_binding = _prepare_classification_plan(
            input_value,capture_product=capture_product,capture_ref=capture_ref,capture_io=capture_io,
            state_root=state_root,job_id=job_id,membership_gate=membership_gate,runner=runner,
            request_material=request_material,resume=resume_frozen_batch or resume_same_batch_pending,
            materialize_only=materialize_only)
        progress({'step':'CLASSIFICATION_FROZEN','classification_preview':classification_plan['preview'],
                  'classification_plan':classification_binding,'completed':0,'total':0})
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
    queue = _new_only_queue(queue_module, queue_root, runner.MODEL_ID,
                            binding_guard=_announcement_execution_guard(runner, request_material),
                            recover_running=not (preprocess_only or execute_report_sha256 is not None),
                            **({'legacy_gate': legacy_gate} if legacy_gate is not None else {}))
    count_prompt_tokens = lambda messages: helper._token_count(tokenizer, messages)
    validator = _validator(queue_module, runner, contract, request_material, length_canary)

    classifications: list[dict[str, Any]] = ([copy.deepcopy(item['classification']) for item in classification_plan['items']]
        if classification_plan is not None else [])
    classifications_by_index = {item['row_index']:item for item in classification_plan['items']} if classification_plan else {}
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
        planned = classifications_by_index.get(index)
        if planned is not None:
            if planned['processing_disposition'] != 'NEW_INPUT':
                continue
            if planned['route_group'] in {'A','B'}:
                continue
            if planned['route_group'] == 'D':
                body_gaps.append({'article_id':article_id,'symbol':member_record.get('symbol'),
                    'title':row.get('title'),'failure_code':planned['classification']['reason_codes'][0]})
                continue
        if (row.get("body_complete") is not True or not isinstance(row.get("body_text"), str)
                or not row.get("body_text")):
            if classification_policy is not None:
                gap_record = classify({"article_id": article_id, "source_sha256": row.get("source_sha256"),
                    "body_sha256": row.get("body_text_sha256"), "article_body": None,
                    "article_metadata": {"title": row.get("title"), "publication_date": row.get("publication_date")}},
                    enabled_policy=classification_policy)
                gap_record["capture_source"] = {**capture_ref, "row_index": index}
                classifications.append(gap_record)
            codes = [item for item in row.get("gaps", []) if isinstance(item, str)]
            body_gaps.append({"article_id": article_id, "symbol": None,
                              "title": row.get("title"), "failure_code": codes[0] if codes else "BODY_INCOMPLETE"})
            continue
        try:
            article = _article(row, index, capture_product, capture_ref, capture_io, runner, membership_gate)
            classification = copy.deepcopy(planned['classification']) if planned is not None else classify(article, enabled_policy=classification_policy)
            classification["capture_source"] = {**capture_ref, "row_index": index}
            classification["source_body_ref"] = row.get("body_artifact_ref")
            if planned is None:
                classifications.append(classification)
            if classification["route"] in {ROUTINE, STRUCTURED}:
                continue
            if classification["route"] == QUARANTINE:
                body_gaps.append({"article_id": article_id, "title": row.get("title"),
                                  "failure_code": "CLASSIFICATION_SOURCE_INCOMPLETE"})
                continue
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

                if resume_frozen_batch or extension_sha256:
                    plan, plan_ref = _load_frozen_resume_plan(
                        state_root, str(frozen_root_job_id) if resume_frozen_batch else job_id, article, unit_map, chunks)
                else:
                    plan = chunks.plan_parts(
                        article_id=article_id, source_sha256=article["source_sha256"],
                        body=article["article_body"], body_sha256=article["body_sha256"],
                        unit_map=unit_map, fixed_fact_ledger=ledger,
                        prompt_sha256=part_prompt_sha256, synthesis_prompt_sha256=synthesis_prompt_sha256,
                        configuration_sha256=request_material["configuration_sha256"],
                        batch_binding_sha256=batch_binding_sha256, token_cap=prompt_token_cap,
                        render_tokens=render_part, token_counter=unit_tokens,
                        model_ledger=lambda value: runner._simple_model_fixed_fact_ledger_for_article(value, article_id))
                    plan_ref = f"long-body/{article_id.replace(':', '_')}-{plan['plan_sha256']}.json"
                chunks.verify_part_coverage(article["article_body"], article["body_sha256"], unit_map, plan)
                plan_root = state_root / "announcement_flash" / "jobs" / job_id
                if not materialize_only and not extension_sha256:
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
                    if (exact_tokens > prompt_token_cap
                            or (not resume_frozen_batch and exact_tokens != part["prompt_tokens_exact"])):
                        raise FlashRunError("CHUNK_PART_TOKEN_PREFLIGHT_MISMATCH")
                    part_rules = (f"{rules}+fixed-fields-contract:{chunks.PART_FIXED_FIELDS_CONTRACT_VERSION}"
                                  f"+long-body-part:v1+plan:{plan['plan_sha256']}"
                                  f"+part:{part['part_index']}/{part['part_count']}"
                                  f"+part-sha:{part['part_sha256']}+part-prompt:{part_prompt_sha256}"
                                  f"+part-addendum:{chunks.PART_ADDENDUM_SHA256}")
                    frozen_source_rules_suffix = (
                        f"+long-body-part:v1+plan:{plan['plan_sha256']}"
                        f"+part:{part['part_index']}/{part['part_count']}"
                        f"+part-sha:{part['part_sha256']}+part-prompt:{plan['prompt_sha256']}"
                        f"+part-addendum:{plan['part_addendum_sha256']}")
                    part_payloads.append({
                        **{key: article[key] for key in ("article_id", "source_sha256", "body_sha256",
                                                         "article_body", "article_metadata", "fixed_fact_ledger")},
                        "date": article["article_metadata"]["publication_date"], "market": "HK",
                        "prompt_sha256": part_prompt_sha256, "model_id": runner.MODEL_ID,
                        "configuration_sha256": request_material["configuration_sha256"],
                        "rules": part_rules, "role": "announcement_reader_part",
                        "stage": "v4_manager_announcement_flash_long_body_part_v1",
                        "queue_task_kind": "announcement_reader_part",
                        "frozen_resume_binding": copy.deepcopy(frozen_resume_binding),
                        "chunk_plan_sha256": plan["plan_sha256"], "part_descriptor": part,
                        "frozen_source_rules_suffix": frozen_source_rules_suffix,
                        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
                        "validated_article_batch": batch, "messages": part_messages,
                        "structured_output_schema": chunks.empty_reader_fixed_fields_schema(request_material["schema"]),
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
                    "frozen_resume_binding": copy.deepcopy(frozen_resume_binding),
                }
                continue
            payloads.append(payload)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raw_code = getattr(exc, "code", None) or str(exc)
            code = raw_code if isinstance(raw_code, str) and SAFE_CODE_RE.fullmatch(raw_code) else "SOURCE_PREPARATION_FAILED"
            body_gaps.append({"article_id": article_id, "symbol": row.get("source_issuer_codes", [{}])[0].get("code")
                              if row.get("source_issuer_codes") else None,
                              "title": row.get("title"), "failure_code": code})

    classification_artifact = {
        "schema": "v4.manager_workbench.announcement_classifications.v1",
        "policy": classification_policy, "capture_product": capture_ref,
        "items": classifications,
        "route_counts": dict(Counter(item["route"] for item in classifications)),
    }
    classification_raw = canonical(classification_artifact) + b"\n"
    classification_ref = f"announcement_flash/jobs/{job_id}/classification.json"
    if classification_policy is not None and not materialize_only and not extension_sha256:
        _write_json(SafeRoot(state_root), classification_ref, classification_artifact)
    classification_model_plan = None
    if classification_plan is not None:
        classification_model_plan = {
            'schema':'v4.manager_workbench.announcement_model_planning.v2',
            'classification_plan_sha256':classification_binding['sha256'],
            'standard_articles':len(payloads), 'long_articles':len(long_body_specs),
            'planned_parts':sum(len(spec['plan']['parts']) for spec in long_body_specs.values()),
            'planned_syntheses':len(long_body_specs),
            'request_estimate_before_final_history_admission':len(payloads)+sum(len(spec['plan']['parts'])+1 for spec in long_body_specs.values()),
            'estimated_completion_repairs':0, 'estimate_is_actual_calls':False,
            'model_prompt_tokens_planned':sum(item['prompt_tokens_exact'] for item in payloads)+sum(
                part['prompt_tokens_exact'] for spec in long_body_specs.values() for part in spec['part_payloads']),
            'synthesis_tokens':'UNKNOWN_UNTIL_PART_REPORTS',
        }
        if not materialize_only and not extension_sha256:
            _write_json(SafeRoot(state_root),f'announcement_flash/jobs/{job_id}/classification-model-plan.json',classification_model_plan)
        progress({'step':'MODEL_PLANNING_FROZEN','classification_model_plan':classification_model_plan,
                  'classification_preview':classification_plan['preview'],'classification_plan':classification_binding,
                  'completed':0,'total':classification_model_plan['request_estimate_before_final_history_admission']})
    preprocessing_report = None
    execution_article_ids = None
    if preprocess_only or execute_report_sha256 is not None:
        from v4.manager_workbench.announcement_preprocessing import build_report, execution_subset
        if classification_plan is None or resume_frozen_batch or resume_same_batch_pending or materialize_only:
            raise FlashRunError("PREPROCESSING_NEW_INPUT_REQUIRED")
        report_ref = f"announcement_flash/jobs/{job_id}/preprocessing-report.json"
        if execute_report_sha256 is not None:
            frozen_raw = SafeRoot(state_root).read_bytes(report_ref, max_bytes=64*1024*1024)
            if sha(frozen_raw) != execute_report_sha256:
                raise FlashRunError("PREPROCESSING_REPORT_SHA_CHANGED")
            history_context = _json(frozen_raw, "PREPROCESSING_REPORT_INVALID").get("history_context", [])
        else:
            history_context = [{"article_id": item.get("identity", {}).get("article_id"),
                                "body_sha256": item.get("identity", {}).get("body_sha256"),
                                "status": item.get("status")} for item in queue._load_state().get("jobs", {}).values()
                               if item.get("queue_id") == QUEUE_ID]
            history_context.extend({"article_id": item.get("identity", {}).get("article_id"),
                                    "body_sha256": item.get("identity", {}).get("body_sha256"),
                                    "status": item.get("status")} for item in _pinned_candidate_history())
            relevant_ids = {e["article_id"] for e in classification_plan["items"]}
            history_context = [e for e in history_context if e["article_id"] in relevant_ids]
        if preparation_guard is not None:
            preparation_guard(request_material, runner)
        preprocessing_report = build_report(
            classification_plan, job_id=job_id, capture=capture_product, ordinary=payloads,
            long_specs=long_body_specs, preparation_pending=[*preflight_pending, *body_gaps],
            blocked_article_ids={"EASTMONEY:AN202610191830690060", "EASTMONEY:AN202610191830690361",
                                 "EASTMONEY:AN202610151830523030"},
            workers=input_value.get("preprocessing_workers", 1), history_context=history_context)
        report_ref = f"announcement_flash/jobs/{job_id}/preprocessing-report.json"
        report_raw = canonical(preprocessing_report) + b"\n"
        report_sha = sha(report_raw)
        state_io = SafeRoot(state_root)
        if preprocess_only:
            if preparation_guard is not None:
                preparation_guard(request_material, runner)
            try:
                previous = state_io.read_bytes(report_ref, max_bytes=64*1024*1024)
            except FileNotFoundError:
                state_io.write_bytes(report_ref, report_raw, require_absent=True)
            else:
                if previous != report_raw:
                    raise FlashRunError("PREPROCESSING_REPORT_ALREADY_FROZEN")
            binding = {"artifact_ref": report_ref, "sha256": report_sha}
            progress({"step": "PREPROCESSING_COMPLETE", "preprocessing": binding,
                      "preprocessing_counts": preprocessing_report["counts"], "completed": 0,
                      "total": preprocessing_report["counts"]["expected_model_requests"],
                      "model_requests": 0, "queue_claims": 0})
            return {"state": "PREPROCESSING_COMPLETE", "preprocessing": binding,
                    "report": preprocessing_report}
        saved_raw = state_io.read_bytes(report_ref, max_bytes=64*1024*1024)
        if sha(saved_raw) != execute_report_sha256 or saved_raw != report_raw:
            raise FlashRunError("PREPROCESSING_SOURCE_OR_REPORT_CHANGED")
        if not preprocessing_report.get("first_article_id"):
            raise FlashRunError("CANNOT_CONFIRM_NEW_INPUT_UNAVAILABLE")
        if extension_sha256:
            return _execute_extension(input_value, state_root=state_root, capture_root=capture_root,
                job_id=job_id, report=preprocessing_report, report_sha256=execute_report_sha256,
                extension_sha256=extension_sha256, phase=execution_phase, payloads=payloads,
                long_specs=long_body_specs, queue=queue, helper=helper, runner=runner, contract=contract,
                canary=canary, queue_module=queue_module, length_canary=length_canary,
                count_tokens=count_prompt_tokens, progress=progress, stop_requested=stop_requested)
        execution_article_ids = execution_subset(preprocessing_report, str(execution_phase))
        phase_entries = preprocessing_report["execution_manifest"][:1] if execution_phase == "FIRST" else preprocessing_report["execution_manifest"]
        execution_versions = {(e["article_id"], e["source_sha256"], e["body_sha256"]) for e in phase_entries}
        payloads = [p for p in payloads if (p["article_id"], p["source_sha256"], p["body_sha256"]) in execution_versions]
        long_body_specs = {aid: spec for aid,spec in long_body_specs.items()
            if (aid,spec["article"]["source_sha256"],spec["article"]["body_sha256"]) in execution_versions}
        # No retries/repairs are admitted by this new-only canary. The full report
        # remains frozen even though this invocation executes only its subset.
        if execution_phase == "CONTINUE":
            from v4.manager_workbench.announcement_delivery import read as read_delivery
            delivered, _binding = read_delivery(state_io, job_id)
            first_id = preprocessing_report["first_article_id"]
            if not delivered or not any(e.get("article_id") == first_id and e.get("body_sha256") == preprocessing_report["execution_manifest"][0]["body_sha256"] and e.get("state") == "SUCCEEDED"
                                        for e in delivered.get("articles", [])):
                raise FlashRunError("PREPROCESSING_FIRST_ARTICLE_NOT_COMPLETE")
        for payload in payloads:
            payload["bounded_execution"] = {"job_id": job_id, "report_sha256": report_sha}
        for spec in long_body_specs.values():
            for payload in spec["part_payloads"]:
                payload["bounded_execution"] = {"job_id": job_id, "report_sha256": report_sha}
        prior_jobs = queue._load_state().get("jobs", {})
        selected_ids = {e["article_id"] for e in preprocessing_report["execution_manifest"]}
        selected_bodies = {(e["article_id"], e["body_sha256"]) for e in preprocessing_report["execution_manifest"]}
        for item in prior_jobs.values():
            identity = item.get("identity", {})
            if (item.get("queue_id") == QUEUE_ID and
                    (identity.get("article_id"), identity.get("body_sha256")) in selected_bodies
                    and _queue_payload(queue_root, item).get("bounded_execution") !=
                    {"job_id": job_id, "report_sha256": execute_report_sha256}):
                raise FlashRunError("NEW_ONLY_HISTORY_APPEARED_AFTER_PREPROCESSING")
        prior_attempts = sum(j.get("attempt_count", 0) for j in prior_jobs.values()
                             if j.get("queue_id") == QUEUE_ID and j.get("identity", {}).get("article_id") in selected_ids
                             and _queue_payload(queue_root, j).get("bounded_execution") ==
                             {"job_id": job_id, "report_sha256": report_sha})
        max_model_calls = max(0, preprocessing_report["limits"]["max_model_requests"] - prior_attempts)

    admitted_payloads, admission_exclusions = filter_payloads(payloads, membership_gate)
    if admission_exclusions:
        membership_exclusions.extend(admission_exclusions)
        for record in admission_exclusions:
            membership_article_counts[str(record.get("membership_status", "UNKNOWN")).lower()] += 1
    if isinstance(recovery_lock, dict):
        expected_ids = set(recovery_lock.get("eligible_article_ids", []))
        represented_ids = {str(payload.get("article_id")) for payload in payloads}
        represented_ids.update(long_body_specs)
        represented_ids.update(str(item["article_id"]) for item in classifications
                               if item["route"] in {ROUTINE, STRUCTURED})
        if classification_plan is not None:
            represented_ids.update(item['article_id'] for item in classification_plan['items']
                                   if item['membership_status']=='IN')
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
                source_part = _find_frozen_source_part(payload, queue, queue_root)
                key = source_part[0] if source_part is not None else _stable_queue_identity(queue, payload)
                frozen_part_keys.append(key)
                saved = pre_resume_jobs.get(key)
                frozen_original_counts[str(saved.get("status", "MISSING") if isinstance(saved, dict) else "MISSING")] += 1
        legacy_canary_target = None
        if resume_action == "CANARY" and prior_resume.get("legacy_failed_canary") is not None:
            legacy_canary_target = _frozen_resume_legacy_canary_target(
                long_body_specs, prior_resume.get("legacy_failed_canary"), queue, queue_root,
                root_job_id=str(frozen_root_job_id), root_input_sha256=str(frozen_root_input_sha256),
                membership_gate=membership_gate, hard_prompt_token_cap=hard_prompt_token_cap,
                count_prompt_tokens=count_prompt_tokens,
            )
        if resume_action == "CONTINUE":
            if transport_recovery_plan is None:
                canary_ok, canary_failure = _verify_saved_frozen_resume_canary(
                    long_body_specs, prior_resume, queue, queue_root,
                    prompt_token_cap=prompt_token_cap, hard_prompt_token_cap=hard_prompt_token_cap,
                    membership_gate=membership_gate, count_prompt_tokens=count_prompt_tokens,
                    runner=runner, contract=contract, state_root=state_root,
                    request_material=request_material,
                )
                if not canary_ok:
                    raise FlashRunError(canary_failure or "FROZEN_RESUME_CANARY_REVALIDATION_FAILED")
        recovered_orphan_keys, blocked_orphan_keys, orphan_candidates = _frozen_resume_orphans(
            long_body_specs, queue, queue_root,
            target_date=str(input_value.get("target_date", "")), dry_run=materialize_only,
            recover_orphans=(resume_action == "CONTINUE" and not materialize_only
                             and transport_recovery_plan is None),
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
        validator=validator, source_bound_versions=execute_report_sha256 is not None,
    )
    allowed_keys: set[str] = set() if resume_frozen_batch else set(admission["allowed_keys"])
    articles_by_key: dict[str, dict[str, Any]] = admission["articles_by_key"]
    matched_history: list[dict[str, Any]] = admission["matched"]
    if classification_plan is not None:
        preclassified_history = _classification_history_matches(classification_plan,capture_product=capture_product,
            capture_ref=capture_ref,capture_io=capture_io,state_root=state_root,runner=runner,membership_gate=membership_gate)
        matched_history.extend(preclassified_history)
        for match in preclassified_history:
            admission['historical_counts']['incremental_'+str(match['record']['status']).lower()] += 1
    body_gaps.extend(admission["conflicts"])
    if (resume_frozen_batch and resume_action == "CANARY"
            and isinstance(transport_recovery_plan, dict)):
        failed_task = transport_recovery_plan.get("failed_task")
        failed_key = failed_task.get("key") if isinstance(failed_task, dict) else None
        failed_jobs = queue._load_state().get("jobs", {})
        failed_job = failed_jobs.get(failed_key) if isinstance(failed_jobs, dict) else None
        capture_rows = capture_product.get("rows")
        failed_rows = [row for row in capture_rows
                       if isinstance(row, dict)
                       and "EASTMONEY:" + str(row.get("art_code", ""))
                       == (failed_task.get("article_id") if isinstance(failed_task, dict) else None)] \
            if isinstance(capture_rows, list) else []
        if (not isinstance(failed_task, dict) or not isinstance(failed_key, str)
                or not SHA_RE.fullmatch(failed_key) or len(failed_rows) != 1
                or not isinstance(failed_job, dict) or failed_job.get("status") != "FAILED"
                or failed_job.get("idempotency_key") != failed_key
                or failed_job.get("queue_id") != QUEUE_ID
                or failed_job.get("payload_sha256") != failed_task.get("payload_sha256")
                or sha(canonical(failed_job.get("identity"))) != failed_task.get("identity_sha256")):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
        failed_payload = _queue_payload(queue_root, failed_job)
        if not _transport_recovery_payload_matches(
                failed_payload, failed_job, failed_rows[0], frozen_root_input,
                str(frozen_root_job_id), str(frozen_root_input_sha256)):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_SOURCE_INVALID")

        current_payloads_by_key: dict[str, dict[str, Any]] = {}
        for current_payload in admitted_payloads:
            current_key = _stable_queue_identity(queue, current_payload)
            if current_key in current_payloads_by_key:
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_CURRENT_PAYLOAD_AMBIGUOUS")
            current_payloads_by_key[current_key] = current_payload
        rebuilt_payload = current_payloads_by_key.get(failed_key)
        if not isinstance(rebuilt_payload, dict):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_CURRENT_PAYLOAD_MISSING")
        request_bindings = {
            "prompt_sha256": request_material.get("prompt_sha256"),
            "configuration_sha256": request_material.get("configuration_sha256"),
            "structured_output_schema": request_material.get("schema"),
            "workflow_profile": request_material.get("workflow_profile"),
            "citation_protocol": request_material.get("citation_protocol"),
        }
        try:
            current_prompt_tokens = count_prompt_tokens(rebuilt_payload.get("messages"))
        except Exception as exc:
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_PREFLIGHT_UNVERIFIED") from exc
        stored_prompt_tokens = failed_payload.get("prompt_tokens_exact")
        if (canonical(rebuilt_payload) != canonical(failed_payload)
                or any(rebuilt_payload.get(field) != value for field, value in request_bindings.items())
                or type(stored_prompt_tokens) is not int or stored_prompt_tokens < 0
                or rebuilt_payload.get("prompt_tokens_exact") != stored_prompt_tokens
                or current_prompt_tokens != stored_prompt_tokens
                or current_prompt_tokens > hard_prompt_token_cap
                or current_prompt_tokens + completion_reserve + chunks.TOKEN_SAFETY_MARGIN > context_limit):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_CURRENT_PAYLOAD_CHANGED")
    internal_records: list[dict[str, Any]] = []
    part_allowed, part_records = _enqueue_long_body_parts(
        long_body_specs, queue, queue_root,
        allow_same_batch_pending=resume_same_batch_pending or resume_frozen_batch,
        recovery_lock=recovery_lock if resume_same_batch_pending else None,
        membership_gate=membership_gate if (resume_same_batch_pending or resume_frozen_batch) else None,
        resume_cutoff=input_value.get("cutoff") if (resume_same_batch_pending or resume_frozen_batch) else None,
        prompt_token_cap=prompt_token_cap,
        hard_prompt_token_cap=hard_prompt_token_cap,
        state_root=state_root,
        allow_new_repairs=not materialize_only and transport_recovery_plan is None,
        allow_multiple_new_repairs=(resume_frozen_batch and resume_action == "CONTINUE"
                                    and transport_recovery_plan is None),
        allow_enqueue=not materialize_only,
        resume_frozen_batch=resume_frozen_batch,
        resume_action=resume_action,
        recovered_orphan_keys=recovered_orphan_keys,
        blocked_orphan_keys=blocked_orphan_keys,
        orphan_candidates=orphan_candidates,
        source_job_id=resume_source_job_id,
        source_input_sha256=resume_source_input_sha256,
        runner=runner, contract=contract, request_material=request_material,
        legacy_failed_canary=(prior_resume.get("legacy_failed_canary")
                              if resume_frozen_batch and isinstance(prior_resume, dict) else None),
        saved_canary_key=(prior_resume.get("canary_key")
                          if resume_frozen_batch and resume_action == "CONTINUE"
                          and isinstance(prior_resume, dict) else None),
        count_prompt_tokens=count_prompt_tokens,
    )
    allowed_keys.update(part_allowed)
    internal_records.extend(part_records)
    if execute_report_sha256 is not None:
        saved_jobs = queue._load_state().get("jobs", {})
        for payload in admitted_payloads:
            key = _stable_queue_identity(queue, payload)
            item = saved_jobs.get(key)
            if (isinstance(item, dict) and item.get("status") == "PENDING" and item.get("attempt_count") == 0
                    and _queue_payload(queue_root, item) == payload
                    and payload.get("bounded_execution") == {"job_id": job_id, "report_sha256": execute_report_sha256}):
                allowed_keys.add(key)
                articles_by_key[key] = {name: payload[name] for name in (
                    "article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")}

    transport_canary_key = None
    if isinstance(transport_recovery_plan, dict):
        failed_task = transport_recovery_plan.get("failed_task")
        pending_plan = transport_recovery_plan.get("pending_tasks")
        if (not isinstance(failed_task, dict) or not isinstance(pending_plan, list)
                or not isinstance(frozen_root_input, dict)):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PLAN_INVALID")
        jobs = queue._load_state().get("jobs", {})
        if not isinstance(jobs, dict):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_STATE_INVALID")
        capture_rows = capture_product.get("rows")
        rows_by_article = {"EASTMONEY:" + str(row.get("art_code")): row for row in capture_rows
                           if isinstance(row, dict) and isinstance(row.get("art_code"), str)} \
            if isinstance(capture_rows, list) else {}
        failed_key = failed_task.get("key")
        failed_job = jobs.get(failed_key) if isinstance(failed_key, str) else None
        failed_row = rows_by_article.get(failed_task.get("article_id"))
        if (not isinstance(failed_job, dict) or failed_job.get("status") != "FAILED"
                or failed_job.get("payload_sha256") != failed_task.get("payload_sha256")
                or sha(canonical(failed_job.get("identity"))) != failed_task.get("identity_sha256")
                or not isinstance(failed_row, dict)):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_SOURCE_CHANGED")
        failed_payload = _queue_payload(queue_root, failed_job)
        if not _transport_recovery_payload_matches(
                failed_payload, failed_job, failed_row, frozen_root_input,
                str(frozen_root_job_id), str(frozen_root_input_sha256)):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_PAYLOAD_CHANGED")

        if resume_action == "CANARY":
            canary_payload = {
                **failed_payload,
                "rules": failed_payload.get("rules", "") + "+explicit-transport-resume:v1",
                "transport_recovery_binding": _transport_recovery_canary_binding(transport_recovery_plan),
                "frozen_resume_binding": copy.deepcopy(frozen_resume_binding),
            }
            transport_canary_key = _stable_queue_identity(queue, canary_payload)
            if transport_canary_key == failed_key:
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_IDENTITY_UNCHANGED")
            canary_job = jobs.get(transport_canary_key)
            if canary_job is None and not materialize_only:
                queue.enqueue(canary_payload)
                jobs = queue._load_state().get("jobs", {})
                canary_job = jobs.get(transport_canary_key)
            if materialize_only:
                canary_job = {"idempotency_key": transport_canary_key,
                              "identity": queue._identity(canary_payload), "status": "PENDING",
                              "attempt_count": 0, "max_attempts": 1,
                              "payload_sha256": sha(canonical(canary_payload))}
            if (not isinstance(canary_job, dict)
                    or canary_job.get("idempotency_key") != transport_canary_key
                    or canary_job.get("queue_id") not in {None, QUEUE_ID}
                    or canary_job.get("identity") != queue._identity(canary_payload)):
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_QUEUE_CONFLICT")
            if not materialize_only:
                stored_canary_payload = _queue_payload(queue_root, canary_job)
                if canonical(stored_canary_payload) != canonical(canary_payload):
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_PAYLOAD_CONFLICT")
            status = canary_job.get("status")
            attempt_count = canary_job.get("attempt_count")
            if status == "PENDING" and attempt_count == 0 and not materialize_only:
                allowed_keys = {transport_canary_key}
                runnable = True
            elif status in {"SUCCEEDED", "FAILED"} and attempt_count == 1:
                runnable = False
            elif materialize_only:
                runnable = False
            else:
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_STATUS_INVALID")
            internal_records.append({"article_id": failed_task.get("article_id"),
                                     "kind": "transport_canary", "key": transport_canary_key,
                                     "base_key": failed_key, "base_status": "FAILED",
                                     "job": canary_job, "runnable": runnable})
        elif resume_action == "CONTINUE":
            payloads_by_key: dict[str, dict[str, Any]] = {}
            for payload in admitted_payloads:
                key = _stable_queue_identity(queue, payload)
                if key in payloads_by_key:
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_CURRENT_PAYLOAD_DUPLICATE")
                payloads_by_key[key] = payload
            if (transport_recovery_plan.get("pending_manifest_sha256")
                    != sha(canonical(pending_plan))
                    or not pending_plan):
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_MANIFEST_INVALID")
            seen_pending = set()
            for entry in pending_plan:
                if (not isinstance(entry, dict)
                        or set(entry) != {"key", "payload_sha256", "identity_sha256"}
                        or entry.get("key") in seen_pending):
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_ENTRY_INVALID")
                key = entry["key"]
                seen_pending.add(key)
                job = jobs.get(key)
                current_payload = payloads_by_key.get(key)
                capture_row = rows_by_article.get(job.get("identity", {}).get("article_id")) \
                    if isinstance(job, dict) else None
                if (not isinstance(job, dict) or job.get("status") != "PENDING"
                        or job.get("attempt_count") != 0 or job.get("max_attempts") != 1
                        or job.get("queue_id") != QUEUE_ID
                        or job.get("payload_sha256") != entry.get("payload_sha256")
                        or sha(canonical(job.get("identity"))) != entry.get("identity_sha256")
                        or not isinstance(current_payload, dict) or not isinstance(capture_row, dict)):
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_TASK_CHANGED")
                stored_payload = _queue_payload(queue_root, job)
                if (canonical(stored_payload) != canonical(current_payload)
                        or not _transport_recovery_payload_matches(
                            stored_payload, job, capture_row, frozen_root_input,
                            str(frozen_root_job_id), str(frozen_root_input_sha256))):
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PAYLOAD_CHANGED")
                allowed_keys.add(key)
                articles_by_key[key] = {field: current_payload[field] for field in (
                    "article_id", "source_sha256", "body_sha256", "article_body",
                    "article_metadata", "fixed_fact_ledger")}
                admission["resumed_payloads_by_key"][key] = current_payload
                internal_records.append({"article_id": current_payload["article_id"],
                                         "kind": "transport_pending", "key": key,
                                         "base_key": key, "base_status": "PENDING",
                                         "base_failure_code": None, "job": job, "runnable": True})
        else:
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_ACTION_INVALID")

    tracked_keys: set[str] = set(allowed_keys) | set(articles_by_key)
    tracked_keys.update(record["key"] for record in internal_records)

    if resume_frozen_batch and max_model_calls == 1:
        if transport_canary_key is not None:
            selected = next((record for record in internal_records
                             if record.get("kind") == "transport_canary"
                             and record.get("key") == transport_canary_key), None)
            if not isinstance(selected, dict):
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_NOT_ADMITTED")
            allowed_keys = {transport_canary_key} if selected.get("runnable") is True else set()
        elif legacy_canary_target is not None:
            candidates = [record for record in internal_records
                          if record.get("kind") == "part"
                          and record.get("base_key") == legacy_canary_target["base_key"]
                          and record.get("repair_source_key") == legacy_canary_target["legacy_key"]
                          and record.get("repair_status") in {"REPAIR_CANARY_ENQUEUED",
                                                               "REPAIR_PENDING_ALLOWED"}
                          and record.get("runnable") is True]
            if (len(candidates) != 1
                    or candidates[0].get("article_id") != legacy_canary_target["article_id"]
                    or candidates[0].get("part_index") != legacy_canary_target["part_index"]):
                raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_NOT_ADMITTED")
            selected = candidates[0]
        else:
            selected = _frozen_resume_canary(internal_records)
        # A CANARY with a verified legacy target can dispatch only its exact
        # source-bound part repair. Ordinary initial canaries retain their
        # existing one-part selection contract.
        allowed_keys = {selected["key"]} if selected else set()
        if legacy_canary_target is not None and not allowed_keys:
            raise FlashRunError("FROZEN_RESUME_CANARY_TARGET_NOT_ADMITTED")
    resume_canary_key = (transport_canary_key if transport_canary_key is not None else
                         (next(iter(allowed_keys)) if resume_frozen_batch and max_model_calls == 1
                          and allowed_keys else None))

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

    long_body_pending = []
    long_body_failures = []
    long_body_summaries = []
    long_body_synthesis_context = []
    recovered_synthesis_results = {}
    saved_raw_recoveries = []
    saved_raw_recovery_outcomes = []

    def admit_ready_syntheses() -> set[str]:
        nonlocal long_body_pending, long_body_failures, long_body_summaries, long_body_synthesis_context
        nonlocal recovered_synthesis_results, saved_raw_recoveries, saved_raw_recovery_outcomes
        long_body_pending = []
        long_body_failures = []
        long_body_summaries = []
        long_body_synthesis_context = []
        recovered_synthesis_results = {}
        saved_raw_recoveries = []
        saved_raw_recovery_outcomes = []
        synthesis_allowed: set[str] = set()
        for article_id, spec in long_body_specs.items():
            current_jobs = queue._load_state().get("jobs", {})
            if spec.get("synthesis_key"):
                key = spec["synthesis_key"]
                job = current_jobs.get(key, {})
                spec["status"] = "SUCCEEDED" if job.get("status") == "SUCCEEDED" else (
                    "SYNTHESIS_FAILED" if job.get("status") == "FAILED" else "SYNTHESIS_PENDING")
                if job.get("status") == "PENDING" and spec.get("synthesis_authorized"):
                    synthesis_allowed.add(key)
                long_body_summaries.append({"article_id": article_id, "plan_sha256": spec["plan"]["plan_sha256"],
                    "plan_ref": spec["plan_ref"], "part_count": len(spec["plan"]["parts"]),
                    "parts_succeeded": len(spec["plan"]["parts"]), "status": spec["status"]})
                continue
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

            if resume_frozen_batch and resume_action == "CANARY":
                spec["status"] = "CANARY_ONLY_NO_SYNTHESIS"
                long_body_pending.append({"article_id": article_id,
                                          "queue_reason": "FROZEN_CANARY_STOPS_BEFORE_SYNTHESIS",
                                          "part_count": len(part_jobs)})
                long_body_summaries.append({"article_id": article_id,
                                            "plan_sha256": spec["plan"]["plan_sha256"],
                                            "plan_ref": spec["plan_ref"],
                                            "part_count": len(part_jobs),
                                            "parts_succeeded": len(part_jobs),
                                            "status": spec["status"]})
                continue

            if execute_report_sha256 is not None and system_stop:
                spec["status"] = "READY_AWAITING_SYNTHESIS"
                long_body_pending.append({"article_id": article_id, "queue_reason": "STOPPED_BEFORE_SYNTHESIS"})
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
                "structured_output_schema": chunks.empty_reader_fixed_fields_schema(request_material["schema"]),
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
            if execute_report_sha256 is not None:
                synthesis_payload["bounded_execution"] = {"job_id": job_id, "report_sha256": execute_report_sha256}
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
            spec["synthesis_authorized"] = runnable
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

        return synthesis_allowed

    def publish_current_delivery() -> None:
        if execute_report_sha256 is None:
            return
        from v4.manager_workbench.announcement_delivery import SCHEMA, publish, read
        io = SafeRoot(state_root)
        old, _binding = read(io, job_id)
        if old and old.get("preprocessing_report_sha256") != execute_report_sha256:
            raise FlashRunError("DELIVERY_REPORT_BINDING_CHANGED")
        by_identity = {(e["article_id"], e.get("body_sha256")): e for e in (old or {}).get("articles", [])}
        for entry in preprocessing_report["catalogue"]:
            if entry["primary_disposition"] == "EXACT_DUPLICATE":
                continue
            identity = (entry["article_id"], entry.get("body_sha256"))
            if identity not in by_identity:
                by_identity[identity] = {**entry, "state": ("PENDING" if (entry["article_id"],entry.get("source_sha256"),entry.get("body_sha256")) in execution_versions
                    else "DEFERRED") if entry["primary_disposition"].startswith("MODEL_")
                    else entry["primary_disposition"]}
        jobs = queue._load_state().get("jobs", {})
        for key, article in articles_by_key.items():
            job = jobs.get(key, {})
            payload = _queue_payload(queue_root, job)
            if not _is_final_candidate_task(payload.get("queue_task_kind")):
                continue
            identity = (article["article_id"], article["body_sha256"])
            if job.get("status") == "SUCCEEDED":
                saved_payload, output = _queue_result(queue_root, job)
                public = _public_article(article["article_id"], saved_payload, output)
                by_identity[identity] = {**public, "state": "SUCCEEDED", "queue_key": key,
                    "result_sha256": job["validated_sha256"], "result_ref": job["validated_path"],
                    "source_coverage": "COMPLETE_SYNTHESIS" if payload.get("queue_task_kind") == "announcement_reader_synthesis"
                    else "COMPLETE_ARTICLE"}
            elif job.get("status") == "FAILED":
                attempt = (job.get("attempts") or [{}])[-1]
                error = attempt.get("error") or {}
                by_identity[identity] = {**by_identity.get(identity, {}), "article_id": article["article_id"],
                    "body_sha256": article["body_sha256"], "state": "FAILED", "queue_key": key,
                    "failure_code": error.get("code", "MODEL_ATTEMPT_FAILED")}
        for aid, spec in long_body_specs.items():
            if spec.get("status") in {"PART_FAILED", "PARTS_PENDING", "PART_REPAIR_PENDING", "CONTEXT_PENDING"}:
                identity = (aid, spec["article"]["body_sha256"])
                if by_identity.get(identity, {}).get("state") != "SUCCEEDED":
                    by_identity[identity] = {**by_identity.get(identity, {}), "state": "FAILED" if spec["status"] == "PART_FAILED" else "PENDING",
                        "queue_reason": spec["status"], "source_coverage": "INCOMPLETE_PARTS",
                        "parts_complete": sum(jobs.get(key, {}).get("status") == "SUCCEEDED" for key in spec["part_keys"]),
                        "parts_total": len(spec["plan"]["parts"])}
        articles = list(by_identity.values())
        selected = [e for e in articles if e.get("state") == "SUCCEEDED"
                    and e.get("disposition") in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"} and e.get("direction") == "POSITIVE"]
        snapshot = {"schema": SCHEMA, "job_id": job_id, "target_trade_date": input_value["target_date"],
            "capture_product": capture_ref, "preprocessing_report_sha256": execute_report_sha256,
            "state": "USER_STOPPED" if (system_stop or {}).get("failure_code") == "USER_STOPPED" else "PARTIAL",
            "articles": articles, "stocks": _aggregate(selected),
            "counts": dict(Counter(e["state"] for e in articles)),
            "pending": [e for e in articles if e["state"] in {"PENDING", "DEFERRED", "SOURCE_GAP", "PREPARATION_PENDING"}],
            "failures": [e for e in articles if e["state"] == "FAILED"],
            "model_requests_this_invocation": completed, "safety": {"RESEARCH_ONLY": True,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}}
        binding = publish(io, job_id, snapshot)
        progress({"step": "ARTICLE_DELIVERED", "delivery": binding, "completed": completed,
                  "total": preprocessing_report["counts"]["bounded_model_requests"],
                  "queue_counts": dict(current_counts())})

    def run_queue_keys(keys: set[str]) -> None:
        nonlocal completed, system_stop
        if not system_stop and stop_requested():
            system_stop = _user_stop_receipt()
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
            def report_result(completed_count: int) -> None:
                progress({"step": "FLASH_SELECTION", "completed": completed_count, "total": len(tracked_keys),
                          "queue_counts": dict(current_counts()), "pending_body_gaps": len(body_gaps),
                          "pending_context": len(preflight_pending), "updated_at": datetime.now(timezone.utc).isoformat()})

            if execute_report_sha256 is None:
                completed, system_stop = _dispatch_pending_queue_keys(
                    queue, executor, validator, keys, completed=completed, max_model_calls=max_model_calls,
                    dispatched_keys=dispatched_keys, on_result=report_result, stop_requested=stop_requested)
            else:
                keys = set(keys)
                turn = 0
                while keys and not system_stop and (max_model_calls is None or completed < max_model_calls):
                    ready_jobs = queue._load_state().get("jobs", {})
                    pending = [key for key in keys if ready_jobs.get(key, {}).get("status") == "PENDING"]
                    if not pending:
                        break
                    def priority(key):
                        payload = _queue_payload(queue_root, ready_jobs[key])
                        synth = payload.get("queue_task_kind") == "announcement_reader_synthesis"
                        return (0 if synth and turn % 4 != 3 else 1,
                                payload.get("date", ""), payload.get("article_id", ""),
                                payload.get("part_descriptor", {}).get("part_index", 0), key)
                    key = min(pending, key=priority)
                    before = completed
                    completed, system_stop = _dispatch_pending_queue_keys(
                        queue, executor, validator, {key}, completed=completed,
                        max_model_calls=min(max_model_calls, completed+1),
                        dispatched_keys=dispatched_keys, on_result=report_result, stop_requested=stop_requested)
                    if completed == before:
                        break  # Busy/deferred: do not consume an attempt or spin.
                    turn += 1
                    keys.update(admit_ready_syntheses())
                    publish_current_delivery()
        finally:
            transport.close()

    run_queue_keys(set(allowed_keys))

    frozen_canary_validation: dict[str, Any] | None = None
    if resume_frozen_batch and resume_action == "CANARY":
        candidate = next((record for record in internal_records
                          if record.get("key") == resume_canary_key), None)
        current_jobs = queue._load_state().get("jobs", {})
        canary_job = current_jobs.get(resume_canary_key, {}) if isinstance(current_jobs, dict) else {}
        if (transport_recovery_plan is not None and isinstance(candidate, dict)
                and candidate.get("kind") == "transport_canary"
                and isinstance(canary_job, dict) and canary_job.get("status") == "SUCCEEDED"):
            try:
                stored_payload = _queue_payload(queue_root, canary_job)
                binding = stored_payload.get("transport_recovery_binding")
                _validated_transport_canary_result(
                    queue_root, canary_job, stored_payload, transport_recovery_plan, validator=validator)
                result_state = "COMPLETE"
            except FlashRunError:
                binding, result_state = None, "UNVERIFIED"
            expected_binding = _transport_recovery_canary_binding(transport_recovery_plan)
            if (canary_job.get("attempt_count") == 1 and canary_job.get("max_attempts") == 1
                    and canary_job.get("queue_id") == QUEUE_ID
                    and canary_job.get("idempotency_key") == resume_canary_key
                    and binding == expected_binding and result_state == "COMPLETE"
                    and isinstance(canary_job.get("validated_sha256"), str)
                    and SHA_RE.fullmatch(canary_job["validated_sha256"])
                    and isinstance(canary_job.get("raw_sha256"), str)
                    and SHA_RE.fullmatch(canary_job["raw_sha256"])):
                frozen_canary_validation = {
                    "status": "PASS", "key": resume_canary_key,
                    "binding_sha256": expected_binding["binding_sha256"],
                    "validated_sha256": canary_job.get("validated_sha256"),
                    "raw_sha256": canary_job.get("raw_sha256"),
                }
            else:
                frozen_canary_validation = {"status": "FAIL", "key": resume_canary_key,
                                            "failure_code": "FROZEN_RESUME_TRANSPORT_CANARY_RESULT_UNVERIFIED"}
        elif isinstance(candidate, dict) and isinstance(canary_job, dict) and canary_job.get("status") == "SUCCEEDED":
            spec = long_body_specs.get(candidate.get("article_id"), {})
            ok, failure_code = _verify_completed_part_repair_canary(
                spec, candidate, queue, queue_root,
                recovery_lock=None, membership_gate=membership_gate, resume_cutoff=None,
                hard_prompt_token_cap=hard_prompt_token_cap,
                count_prompt_tokens=count_prompt_tokens, runner=runner, contract=contract,
                state_root=state_root, request_material=request_material,
                frozen_resume_binding=(spec.get("frozen_resume_binding")
                                       if isinstance(spec, dict) else None),
            )
            if ok:
                _set_part_repair_status(spec, candidate, "REPAIR_CANARY_VERIFIED")
                stored_repair_payload = _queue_payload(queue_root, canary_job)
                repair_binding = stored_repair_payload.get("part_repair_binding")
                frozen_canary_validation = {
                    "status": "PASS", "key": resume_canary_key,
                    "binding_sha256": (repair_binding.get("binding_sha256")
                                       if isinstance(repair_binding, dict) else None),
                    "validated_sha256": canary_job.get("validated_sha256"),
                    "raw_sha256": canary_job.get("raw_sha256"),
                    "part_index": candidate.get("part_index"),
                }
            else:
                _set_part_repair_status(spec, candidate, "REPAIR_CANARY_INVALID_STOP", failure_code)
                frozen_canary_validation = {"status": "FAIL", "key": resume_canary_key,
                                            "failure_code": failure_code or "REPAIR_CANARY_VALIDATION_FAILED"}
        else:
            frozen_canary_validation = {"status": "FAIL", "key": resume_canary_key,
                                        "failure_code": (system_stop or {}).get("failure_code")
                                        or "FROZEN_RESUME_CANARY_NOT_SUCCEEDED"}

    repair_continuation: dict[str, Any] = {"status": "NO_REPAIR_CANARY"}
    phase_b_allowed: set[str] = set()
    phase_b_records: list[dict[str, Any]] = []
    if (not resume_frozen_batch and any(record.get("repair_status") in {
            "REPAIR_CANARY_ENQUEUED", "REPAIR_PENDING_ALLOWED", "REPAIRED_SUCCESS_REUSED"
    } for record in part_records)):
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
    synthesis_allowed = admit_ready_syntheses()
    tracked_keys.update(synthesis_allowed)
    run_queue_keys(synthesis_allowed)
    publish_current_delivery()

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
                                  "queue_reason": ("USER_STOPPED_NOT_DISPATCHED"
                                                   if (system_stop or {}).get("failure_code") == "USER_STOPPED"
                                                   else ("STOPPED_AFTER_SYSTEM_FAILURE" if system_stop else "NOT_RUN"))})
        else:
            continue

    failures.extend(long_body_failures)
    preflight_pending.extend(long_body_synthesis_context)

    if classification_plan is not None:
        for item in classification_plan['items']:
            if item['processing_disposition'] in {'HISTORICAL_INCOMPATIBLE_PRESERVED','HISTORY_INTEGRITY_QUARANTINE'}:
                preflight_pending.append({'article_id':item['article_id'],
                    'queue_reason':item['processing_disposition'],'history_receipt':item.get('history_receipt')})
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
    complete = (all(status == "SUCCEEDED" for status in current_status_counts)
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
    classification_execution = None
    if classification_plan is not None:
        saved_jobs=queue._load_state().get('jobs',{})
        execution_rows=[]
        for item in classification_plan['items']:
            keys=[key for key,job in saved_jobs.items() if isinstance(job,dict) and job.get('queue_id')==QUEUE_ID
                  and job.get('identity',{}).get('article_id')==item['article_id']
                  and job.get('identity',{}).get('source_sha256')==item['source_sha256']
                  and job.get('identity',{}).get('body_sha256')==item['body_sha256']]
            execution_rows.append({'row_index':item['row_index'],'article_id':item['article_id'],
                'processing_disposition':item['processing_disposition'],'route_group':item['route_group'],
                'associated_model_keys':keys,'dispatched_model_keys':[key for key in keys if key in dispatched_keys]})
        classification_execution={'classification_plan_sha256':classification_binding['sha256'],'items':execution_rows,
            'queue_dispatches_observed':completed,'transport_calls_measured':False}
    result = {
        "schema": "v4.manager_workbench.announcement_flash_result.v1",
        "job_id": job_id,
        "state": "USER_STOPPED" if (system_stop or {}).get("failure_code") == "USER_STOPPED"
        else ("SUCCEEDED" if complete else "PARTIAL"),
        "target_trade_date": input_value["target_date"],
        "source_window": capture_product.get("window"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": runner.MODEL_ID,
        "profile": PROFILE,
        "citation_protocol": request_material["citation_protocol"],
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
        "review_status": "MODEL_CANDIDATE_UNREVIEWED",
        "classification_model_plan": classification_model_plan,
        "classification_execution": classification_execution,
        "classification_plan": classification_binding,
        "classification_preview": classification_plan['preview'] if classification_plan else None,
        "classification_catalogue": classification_plan['items'] if classification_plan else None,
        "classification": {**classification_artifact,
                           "artifact_ref": classification_ref if classification_policy is not None else None,
                           "sha256": sha(classification_raw),
                           "model_analysis_claim": False},
        "counts": {
            "rule_archived_articles": classification_plan['preview']['new_input_route_counts']['A'] if classification_plan else sum(item["route"] == ROUTINE for item in classifications),
            "structured_event_articles": classification_plan['preview']['new_input_route_counts']['B'] if classification_plan else sum(item["route"] == STRUCTURED for item in classifications),
            "model_review_required_articles": classification_plan['preview']['new_input_route_counts']['C'] if classification_plan else sum(item["route"] == MODEL for item in classifications),
            "classification_quarantined_articles": classification_plan['preview']['new_input_route_counts']['D'] if classification_plan else sum(item["route"] == QUARANTINE for item in classifications),
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
                                    "auto_continue_after_verified_canary": not resume_frozen_batch,
                                    "frozen_resume_requires_explicit_continue": resume_frozen_batch,
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
                       **({"execution_configuration_sha256": request_material["execution_configuration_sha256"],
                           "runtime_memory_transition": request_material["runtime_memory_transition"]}
                          if "runtime_memory_transition" in request_material else {}),
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
        prior_resume = input_value.get("resume_source") if isinstance(input_value.get("resume_source"), dict) else {}
        if resume_action == "CANARY":
            canary_key = resume_canary_key
            canary_status = final_jobs.get(canary_key, {}).get("status") if canary_key else None
            canary_passed = (isinstance(frozen_canary_validation, dict)
                             and frozen_canary_validation.get("status") == "PASS")
            canary_validation = frozen_canary_validation
            canary_model_calls = (final_jobs.get(canary_key, {}).get("attempt_count")
                                  if canary_key and isinstance(final_jobs.get(canary_key), dict) else 0)
        else:
            canary_key = prior_resume.get("canary_key")
            canary_status = prior_resume.get("canary_status")
            canary_passed = prior_resume.get("canary_passed") is True
            canary_validation = prior_resume.get("canary_validation")
            canary_model_calls = prior_resume.get("canary_model_calls")
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
            "resume_action": resume_action,
            "canary_key": canary_key,
            "canary_status": canary_status,
            "canary_model_calls": canary_model_calls,
            "canary_validation": canary_validation,
            "canary_passed": canary_passed,
            "continue_eligible": canary_passed and resume_action == "CANARY" and not complete,
            "dispatched_keys": dispatched_keys,
            **({"transport_recovery": transport_recovery_plan}
               if isinstance(transport_recovery_plan, dict) else {}),
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
    if preprocessing_report is not None:
        result["preprocessing"] = {"artifact_ref": f"announcement_flash/jobs/{job_id}/preprocessing-report.json",
                                   "sha256": execute_report_sha256}
        result["execution_phase"] = execution_phase
        if result["state"] == "SUCCEEDED" and (execution_phase == "FIRST" or preprocessing_report["counts"]["deferred_model_articles"]):
            result["state"] = "PARTIAL"
    return result


def _legacy_orphan_recovery_source_part(source_input: dict[str, Any], payload: dict[str, Any],
                                        queue_value: dict[str, Any], state_io: SafeRoot,
                                        capture_root: Path, root_job_id: str,
                                        root_input_sha256: str, expected_source_part_key: str,
                                        expected_recovery_binding_sha256: str) -> str:
    """Bind the old orphan-resume request to one interrupted source part and root plan."""
    recovery = payload.get("interrupted_attempt_recovery")
    root_input_raw = state_io.read_bytes(f"announcement_flash/jobs/{root_job_id}/input.json",
                                         max_bytes=1024 * 1024)
    root_input = _json(root_input_raw, "FROZEN_RESUME_LEGACY_ROOT_INPUT_INVALID")
    root_progress_raw = state_io.read_bytes(f"announcement_flash/jobs/{root_job_id}/progress.json",
                                            max_bytes=1024 * 1024)
    parent = source_input.get("resume_source")
    capture_ref = root_input.get("capture_product") if isinstance(root_input, dict) else None
    if (not isinstance(recovery, dict)
            or set(recovery) != {"schema", "source_idempotency_key", "source_job_id",
                                 "source_input_sha256", "source_payload_sha256", "source_attempt_count",
                                 "chunk_plan_sha256", "part_sha256", "source_unit_map_sha256"}
            or recovery.get("schema") != "v4.manager_workbench.announcement_flash_orphan_recovery.v1"
            or recovery.get("source_job_id") != root_job_id
            or recovery.get("source_input_sha256") != root_input_sha256
            or sha(canonical(recovery)) != expected_recovery_binding_sha256
            or recovery.get("source_attempt_count") != 1
            or not isinstance(parent, dict)
            or not isinstance(capture_ref, dict)
            or not isinstance(capture_ref.get("artifact_ref"), str)
            or not isinstance(capture_ref.get("sha256"), str)
            or not SHA_RE.fullmatch(capture_ref["sha256"])
            or sha(root_input_raw) != root_input_sha256 or canonical(root_input) != root_input_raw
            or not isinstance(root_input, dict)
            or root_input.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
            or root_input.get("job_id") != root_job_id
            or root_input.get("target_date") != source_input.get("target_date")
            or root_input.get("capture_product") != source_input.get("capture_product")
            or root_input.get("membership_gate") != source_input.get("membership_gate")
            or isinstance(root_input.get("recovery_lock"), dict)
            or sha(root_progress_raw) != parent.get("source_progress_sha256")
            or parent.get("capture_product_sha256") != capture_ref.get("sha256")
            or parent.get("queue_status_counts") != {
                "FAILED": 15, "PENDING": 5, "RUNNING": 1, "SUCCEEDED": 24}):
        raise FlashRunError("FROZEN_RESUME_LEGACY_ROOT_INPUT_BINDING_INVALID")
    source_key = recovery.get("source_idempotency_key")
    if (not isinstance(source_key, str) or not SHA_RE.fullmatch(source_key)
            or source_key != expected_source_part_key):
        raise FlashRunError("FROZEN_RESUME_LEGACY_ORPHAN_SOURCE_KEY_INVALID")
    jobs = queue_value.get("jobs")
    source_item = jobs.get(source_key) if isinstance(jobs, dict) else None
    attempts = source_item.get("attempts") if isinstance(source_item, dict) else None
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    error = attempt.get("error") if isinstance(attempt, dict) else None
    source_ref = source_item.get("input_path") if isinstance(source_item, dict) else None
    if (not isinstance(source_item, dict) or source_item.get("idempotency_key") != source_key
            or source_item.get("queue_id") != QUEUE_ID or source_item.get("status") != "FAILED"
            or source_item.get("attempt_count") != 1 or source_item.get("max_attempts") != 1
            or not isinstance(source_item.get("identity"), dict)
            or set(source_item["identity"]) != set(QUEUE_IDENTITY_FIELDS)
            or sha(canonical(source_item["identity"])) != source_key
            or not isinstance(attempt, dict) or attempt.get("status") != "INTERRUPTED"
            or attempt.get("number") != 1 or not isinstance(error, dict)
            or error.get("stage") != "recovery" or error.get("code") != "PROCESS_INTERRUPTED"
            or source_item.get("raw_path") is not None or source_item.get("raw_sha256") is not None
            or source_ref != f"jobs/{source_key}/input.json"
            or source_item.get("payload_sha256") != recovery.get("source_payload_sha256")):
        raise FlashRunError("FROZEN_RESUME_LEGACY_ORPHAN_SOURCE_QUEUE_INVALID")
    source_raw = state_io.read_bytes("announcement_flash/queue/" + source_ref, max_bytes=64 * 1024 * 1024)
    source_payload = _json(source_raw, "FROZEN_RESUME_LEGACY_ORPHAN_SOURCE_PAYLOAD_INVALID")
    plan_sha = payload.get("chunk_plan_sha256")
    article_id = payload.get("article_id")
    part = payload.get("part_descriptor")
    if (not isinstance(plan_sha, str) or not SHA_RE.fullmatch(plan_sha)
            or not isinstance(article_id, str) or not isinstance(part, dict)):
        raise FlashRunError("FROZEN_RESUME_LEGACY_ROOT_PLAN_INVALID")
    plan_ref = (f"announcement_flash/jobs/{root_job_id}/long-body/"
                f"{article_id.replace(':', '_')}-{plan_sha}.json")
    plan_raw = state_io.read_bytes(plan_ref, max_bytes=64 * 1024 * 1024)
    plan = _json(plan_raw, "FROZEN_RESUME_LEGACY_ROOT_PLAN_INVALID")
    plan_material = {name: value for name, value in plan.items() if name != "plan_sha256"} \
        if isinstance(plan, dict) else {}
    matching_parts = [item for item in plan.get("parts", [])
                      if isinstance(item, dict) and item == part] if isinstance(plan, dict) else []
    capture_io = SafeRoot(capture_root)
    capture_raw = capture_io.read_bytes(capture_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
    capture_value = _json(capture_raw, "FROZEN_RESUME_LEGACY_ROOT_CAPTURE_INVALID")
    capture_rows = capture_value.get("rows") if isinstance(capture_value, dict) else None
    capture_matches = [row for row in capture_rows if isinstance(row, dict)
                       and "EASTMONEY:" + str(row.get("art_code", "")) == article_id
                       and row.get("body_complete") is True
                       and row.get("source_sha256") == payload.get("source_sha256")
                       and row.get("body_text_sha256") == payload.get("body_sha256")
                       and row.get("body_artifact_ref") == f"products/{payload.get('source_sha256')}.json"
                       and row.get("publication_date") == payload.get("date")] \
        if isinstance(capture_rows, list) else []
    expected_orphan = dict(source_payload) if isinstance(source_payload, dict) else {}
    if isinstance(source_payload, dict):
        expected_orphan["rules"] = source_payload.get("rules", "") + "+explicit-orphan-resume:v1"
        expected_orphan["stage"] = "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"
        expected_orphan["interrupted_attempt_recovery"] = recovery
    if (not isinstance(source_payload, dict) or sha(source_raw) != source_item.get("payload_sha256")
            or {field: source_payload.get(field) for field in QUEUE_IDENTITY_FIELDS} != source_item.get("identity")
            or source_payload.get("stage") != "v4_manager_announcement_flash_long_body_part_v1"
            or source_payload.get("queue_task_kind") != "announcement_reader_part"
            or source_payload.get("article_id") != article_id
            or source_payload.get("source_sha256") != payload.get("source_sha256")
            or source_payload.get("body_sha256") != payload.get("body_sha256")
            or source_payload.get("chunk_plan_sha256") != plan_sha
            or source_payload.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or source_payload.get("part_descriptor") != part
            or {name: value for name, value in payload.items() if name != "interrupted_attempt_recovery"}
            != {name: value for name, value in expected_orphan.items()
                if name != "interrupted_attempt_recovery"}
            or recovery.get("chunk_plan_sha256") != plan_sha
            or recovery.get("part_sha256") != part.get("part_sha256")
            or recovery.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or not isinstance(plan, dict)
            or plan.get("schema") != "v4.manager_workbench.announcement_chunk_plan.v1"
            or plan.get("plan_sha256") != plan_sha or sha(canonical(plan_material)) != plan_sha
            or plan.get("article_id") != article_id or plan.get("source_sha256") != payload.get("source_sha256")
            or plan.get("body_sha256") != payload.get("body_sha256")
            or plan.get("source_unit_map_sha256") != payload.get("source_unit_map_sha256")
            or len(matching_parts) != 1 or not isinstance(capture_ref, dict)
            or sha(capture_raw) != capture_ref.get("sha256")
            or capture_value.get("source") != "EASTMONEY_HK"
            or str(capture_value.get("target_trade_date", "")).replace("-", "")
            != source_input.get("target_date") or len(capture_matches) != 1):
        raise FlashRunError("FROZEN_RESUME_LEGACY_ORPHAN_SOURCE_BINDING_INVALID")
    return source_key


def _legacy_failed_canary_source_binding(source_job_id: str, source_input_sha256: str,
                                        source_input: dict[str, Any], source_result: Any,
                                        queue_value: dict[str, Any], queue_root: Path,
                                        state_io: SafeRoot, capture_root: Path
                                        ) -> dict[str, Any]:
    """Reprove the one exact pre-contract failed canary from its immutable artifacts."""
    from v4.manager_workbench import announcement_chunks as chunks

    resume = source_result.get("resume") if isinstance(source_result, dict) else None
    validation = resume.get("canary_validation") if isinstance(resume, dict) else None
    key = resume.get("canary_key") if isinstance(resume, dict) else None
    root = source_input.get("resume_root")
    parent = source_input.get("resume_source")
    root_job_id = root.get("source_job_id") if isinstance(root, dict) else None
    root_input_sha256 = root.get("source_input_sha256") if isinstance(root, dict) else None
    legacy_resume_keys = {
        "canary_key", "canary_passed", "canary_status", "continue_eligible", "dispatched_keys",
        "failed_preserved", "historical_success_conflicts", "initial_part_status_counts",
        "initial_part_total", "max_model_calls", "mode", "model_calls", "orphan_candidates",
        "pending_eligible", "recoverable_orphan_count", "source_input_sha256",
        "source_input_sha256_binding", "source_job_id", "succeeded_preserved",
    }
    legacy_parent_keys = {
        "schema", "mode", "source_job_id", "source_input_sha256", "source_progress_sha256",
        "source_queue_state_sha256", "source_result_sha256", "capture_product_sha256",
        "queue_status_counts", "canary_passed", "max_model_calls", "target_date",
    }
    legacy_result_shape = (
        isinstance(source_result, dict)
        and source_result.get("schema") == "v4.manager_workbench.announcement_flash_result.v1"
        and source_result.get("job_id") == source_job_id
        and source_result.get("target_trade_date") == source_input.get("target_date")
        and source_result.get("state") == "PARTIAL"
        and isinstance(resume, dict) and set(resume) == legacy_resume_keys
        and resume.get("mode") == "FROZEN_BATCH"
        and "resume_action" not in resume and "canary_model_calls" not in resume
        and "canary_validation" not in resume
        and resume.get("canary_passed") is False and resume.get("canary_status") == "FAILED"
        and resume.get("model_calls") == 1 and resume.get("max_model_calls") == 1
        and resume.get("source_job_id") == root_job_id
        and resume.get("source_input_sha256") == root_input_sha256
        and resume.get("source_input_sha256_binding") == root_input_sha256
        and isinstance(key, str) and SHA_RE.fullmatch(key)
        and resume.get("dispatched_keys") == [key]
        and resume.get("initial_part_status_counts") == {
            "failed": 15, "pending": 5, "running": 1, "succeeded": 24}
        and resume.get("initial_part_total") == 45
        and resume.get("succeeded_preserved") == 24 and resume.get("failed_preserved") == 15
        and resume.get("pending_eligible") == 0 and resume.get("recoverable_orphan_count") == 0
        and resume.get("continue_eligible") is False
        and type(resume.get("historical_success_conflicts")) is int
        and resume.get("historical_success_conflicts") >= 0
        and isinstance(resume.get("orphan_candidates"), list) and len(resume["orphan_candidates"]) == 1
        and isinstance(resume["orphan_candidates"][0], dict)
        and set(resume["orphan_candidates"][0]) == {
            "attempt_count", "binding_sha256", "idempotency_key", "source_idempotency_key", "status"}
        and resume["orphan_candidates"][0].get("idempotency_key") == key
        and resume["orphan_candidates"][0].get("attempt_count") == 0
        and resume["orphan_candidates"][0].get("status") == "PENDING"
        and SHA_RE.fullmatch(str(resume["orphan_candidates"][0].get("source_idempotency_key", "")))
        and SHA_RE.fullmatch(str(resume["orphan_candidates"][0].get("binding_sha256", "")))
        and isinstance(parent, dict) and set(parent) == legacy_parent_keys
        and parent.get("schema") == "v4.manager_workbench.announcement_flash_resume.v1"
        and parent.get("mode") == "INITIAL_CANARY"
        and parent.get("source_job_id") == root_job_id
        and parent.get("source_input_sha256") == root_input_sha256
        and parent.get("target_date") == source_input.get("target_date")
        and parent.get("source_result_sha256") is None
        and parent.get("canary_passed") is False and parent.get("max_model_calls") == 1
        and parent.get("queue_status_counts") == {
            "FAILED": 15, "PENDING": 5, "RUNNING": 1, "SUCCEEDED": 24}
        and all(SHA_RE.fullmatch(str(parent.get(field, ""))) for field in (
            "source_input_sha256", "source_progress_sha256", "source_queue_state_sha256",
            "capture_product_sha256"))
        and parent.get("source_input_sha256") == root_input_sha256
        and isinstance(root_job_id, str) and JOB_ID_RE.fullmatch(root_job_id)
        and isinstance(root_input_sha256, str) and SHA_RE.fullmatch(root_input_sha256)
    )
    canonical_result_shape = (
        isinstance(source_result, dict) and source_result.get("state") == "PARTIAL"
        and isinstance(resume, dict) and resume.get("mode") == "FROZEN_BATCH"
        and resume.get("resume_action") == "CANARY" and resume.get("canary_passed") is False
        and resume.get("canary_status") == "FAILED" and resume.get("canary_model_calls") == 1
        and resume.get("max_model_calls") == 1 and isinstance(validation, dict)
        and validation.get("status") == "FAIL" and validation.get("key") == key
        and validation.get("failure_code") in {
            "FROZEN_RESUME_CANARY_NOT_SUCCEEDED", "CANARY_TEST_FAILURE",
            "PART_FIXED_FIELDS_MUST_BE_EMPTY"}
        and isinstance(key, str) and SHA_RE.fullmatch(key)
        and isinstance(parent, dict) and parent.get("mode") == "INITIAL_CANARY"
        and parent.get("resume_action") == "CANARY"
        and parent.get("source_job_id") == root_job_id
        and parent.get("source_input_sha256") == root_input_sha256
        and parent.get("legacy_failed_canary") is None
        and isinstance(root_job_id, str) and JOB_ID_RE.fullmatch(root_job_id)
        and isinstance(root_input_sha256, str) and SHA_RE.fullmatch(root_input_sha256)
    )
    if not legacy_result_shape and not canonical_result_shape:
        raise FlashRunError("FROZEN_RESUME_RESULT_NOT_ELIGIBLE")
    if legacy_result_shape:
        validation = {"status": "FAIL", "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY", "key": key}
    jobs = queue_value.get("jobs")
    failed = jobs.get(key) if isinstance(jobs, dict) else None
    if (not isinstance(failed, dict) or failed.get("idempotency_key") != key
            or failed.get("queue_id") != QUEUE_ID or failed.get("status") != "FAILED"
            or failed.get("attempt_count") != 1 or failed.get("max_attempts") != 1
            or not isinstance(failed.get("identity"), dict)
            or set(failed["identity"]) != set(QUEUE_IDENTITY_FIELDS)
            or sha(canonical(failed["identity"])) != key):
        raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_QUEUE_INVALID")
    payload_ref = failed.get("input_path")
    raw_ref = failed.get("raw_path")
    payload_sha = failed.get("payload_sha256")
    raw_sha = failed.get("raw_sha256")
    attempts = failed.get("attempts")
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    error = attempt.get("error") if isinstance(attempt, dict) else None
    if (payload_ref != f"jobs/{key}/input.json" or raw_ref != f"jobs/{key}/attempt-0001.raw"
            or not isinstance(payload_sha, str) or not SHA_RE.fullmatch(payload_sha)
            or not isinstance(raw_sha, str) or not SHA_RE.fullmatch(raw_sha)
            or not isinstance(attempt, dict) or attempt.get("status") != "FAILED"
            or attempt.get("raw_path") != raw_ref or attempt.get("raw_sha256") != raw_sha
            or not isinstance(error, dict) or error.get("stage") != "validator"
            or error.get("code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"):
        raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_FAILURE_NOT_EXACT")
    payload_raw = (queue_root / payload_ref).read_bytes()
    raw_response = (queue_root / raw_ref).read_bytes()
    payload = _json(payload_raw, "FROZEN_RESUME_LEGACY_CANARY_PAYLOAD_INVALID")
    envelope = _json(raw_response, "FROZEN_RESUME_LEGACY_CANARY_RAW_INVALID")
    fixed = envelope.get("reader_output") if isinstance(envelope, dict) else None
    root_binding = payload.get("frozen_resume_binding") if isinstance(payload, dict) else None
    legacy_source_part_key = None
    if legacy_result_shape:
        legacy_source_part_key = _legacy_orphan_recovery_source_part(
            source_input, payload, queue_value, state_io, capture_root, root_job_id,
            root_input_sha256, resume["orphan_candidates"][0]["source_idempotency_key"],
            resume["orphan_candidates"][0]["binding_sha256"])
    if (not isinstance(payload, dict) or sha(payload_raw) != payload_sha
            or {field: payload.get(field) for field in QUEUE_IDENTITY_FIELDS} != failed.get("identity")
            or payload.get("queue_task_kind") != "announcement_reader_part"
            or payload.get("stage") not in {"v4_manager_announcement_flash_long_body_part_v1",
                                             "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"}
            or f"+fixed-fields-contract:{chunks.PART_FIXED_FIELDS_CONTRACT_VERSION}" in str(payload.get("rules", ""))
            or (not legacy_result_shape and (
                not isinstance(root_binding, dict) or root_binding.get("source_job_id") != root_job_id
                or root_binding.get("source_input_sha256") != root_input_sha256))
            or (legacy_result_shape and (payload.get("stage") !=
                "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"
                or payload.get("frozen_resume_binding") is not None))
            or not isinstance(envelope, dict) or set(envelope) != {"action", "lookup_request", "reader_output"}
            or envelope.get("action") != "complete" or envelope.get("lookup_request") is not None
            or not isinstance(fixed, dict) or not isinstance(fixed.get("facts"), list)
            or not isinstance(fixed.get("changes"), list)
            or (fixed.get("facts") == [] and fixed.get("changes") == [])
            or sha(raw_response) != raw_sha):
        raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_SOURCE_BINDING_INVALID")
    return {"key": key, "payload_sha256": payload_sha, "raw_sha256": raw_sha,
            "source_job_id": source_job_id, "source_input_sha256": source_input_sha256,
            "root_job_id": root_job_id, "root_input_sha256": root_input_sha256,
            "article_id": payload.get("article_id"), "source_sha256": payload.get("source_sha256"),
            "body_sha256": payload.get("body_sha256"),
            "chunk_plan_sha256": payload.get("chunk_plan_sha256"),
            "source_unit_map_sha256": payload.get("source_unit_map_sha256"),
            "part_descriptor": payload.get("part_descriptor"),
            **({"source_part_key": legacy_source_part_key}
               if isinstance(legacy_source_part_key, str) else {})}


def _verify_preserved_synthesis_success(state_io: SafeRoot, queue_value: dict[str, Any]) -> None:
    key = FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY
    jobs = queue_value.get("jobs") if isinstance(queue_value, dict) else None
    item = jobs.get(key) if isinstance(jobs, dict) else None
    if (not isinstance(item, dict) or item.get("queue_id") != QUEUE_ID
            or item.get("idempotency_key") != key or item.get("status") != "SUCCEEDED"
            or item.get("attempt_count") != 1 or item.get("max_attempts") != 1
            or item.get("payload_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256
            or item.get("validated_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256
            or item.get("raw_sha256") != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256
            or item.get("input_path") != f"jobs/{key}/input.json"
            or item.get("validated_path") != f"jobs/{key}/attempt-0001.validated.json"
            or item.get("raw_path") != f"jobs/{key}/attempt-0001.raw"):
        raise FlashRunError("FROZEN_RESUME_PRESERVED_SYNTHESIS_BINDING_INVALID")
    try:
        payload_raw = state_io.read_bytes("announcement_flash/queue/" + item["input_path"],
                                          max_bytes=64 * 1024 * 1024)
        validated_raw = state_io.read_bytes("announcement_flash/queue/" + item["validated_path"],
                                            max_bytes=64 * 1024 * 1024)
        response_raw = state_io.read_bytes("announcement_flash/queue/" + item["raw_path"],
                                           max_bytes=8 * 1024 * 1024)
    except (OSError, ValueError) as exc:
        raise FlashRunError("FROZEN_RESUME_PRESERVED_SYNTHESIS_ARTIFACT_UNAVAILABLE") from exc
    payload = _json(payload_raw, "FROZEN_RESUME_PRESERVED_SYNTHESIS_PAYLOAD_INVALID")
    validated = _json(validated_raw, "FROZEN_RESUME_PRESERVED_SYNTHESIS_VALIDATED_INVALID")
    response = _json(response_raw, "FROZEN_RESUME_PRESERVED_SYNTHESIS_RAW_INVALID")
    identity = item.get("identity")
    rows = validated.get("results") if isinstance(validated, dict) else None
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    output = row.get("reader_output") if isinstance(row, dict) else None
    response_output = response.get("reader_output") if isinstance(response, dict) else None
    if (not isinstance(identity, dict) or sha(canonical(identity)) != key
            or sha(payload_raw) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256
            or sha(validated_raw) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256
            or sha(response_raw) != FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256
            or {field: payload.get(field) for field in QUEUE_IDENTITY_FIELDS} != identity
            or payload.get("queue_task_kind") != "announcement_reader_synthesis"
            or payload.get("stage") != "v4_manager_announcement_flash_long_body_synthesis_v1"
            or not isinstance(row, dict) or row.get("article_id") != identity.get("article_id")
            or not isinstance(output, dict)
            or output.get("source_sha256") != identity.get("source_sha256")
            or output.get("body_sha256") != identity.get("body_sha256")
            or not isinstance(response, dict) or response.get("action") != "complete"
            or response.get("lookup_request") is not None or not isinstance(response_output, dict)):
        raise FlashRunError("FROZEN_RESUME_PRESERVED_SYNTHESIS_ARTIFACT_INVALID")


def _verify_c039_queue_reconstruction(state_io: SafeRoot, queue_raw: bytes,
                                      queue_value: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the frozen announcement queue after removing only verified post-c039 PDF jobs."""
    if (sha(queue_raw) != sha(canonical(queue_value))
            or set(queue_value) != {"schema", "created_at", "jobs", "events"}
            or queue_value.get("schema") != "v4.announcement-engine-queue/v1"
            or not isinstance(queue_value.get("jobs"), dict)
            or not isinstance(queue_value.get("events"), list)):
        raise FlashRunError("FROZEN_RESUME_C039_QUEUE_SERIALIZATION_INVALID")
    try:
        attempt_raw = state_io.read_bytes(
            f"attempts/{FAILED_DISPATCH_CANARY_REENTRY_JOB_ID}.json", max_bytes=8 * 1024 * 1024)
    except (OSError, ValueError) as exc:
        raise FlashRunError("FROZEN_RESUME_C039_ATTEMPT_UNAVAILABLE") from exc
    attempt_value = _json(attempt_raw, "FROZEN_RESUME_C039_ATTEMPT_INVALID")
    if (not isinstance(attempt_value, dict)
            or sha(attempt_raw) != FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256
            or attempt_value.get("job_id") != FAILED_DISPATCH_CANARY_REENTRY_JOB_ID
            or attempt_value.get("state") != "PARTIAL"
            or attempt_value.get("step") != "DONE"
            or attempt_value.get("retryable") is not False
            or attempt_value.get("finished_at") != FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT):
        raise FlashRunError("FROZEN_RESUME_C039_ATTEMPT_BINDING_INVALID")
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
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_RECORD_INVALID")
        if item.get("queue_id") != QUEUE_ID:
            extension_keys.append(key)
    extension_keys.sort()
    if sha(queue_raw) == FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256 and not extension_keys:
        return {"schema": "v4.manager_workbench.announcement_queue_reconstruction.v1",
                "baseline_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
                "reconstructed_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
                "current_sha256": sha(queue_raw),
                "source_attempt_sha256": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256,
                "source_attempt_finished_at": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT,
                "excluded_jobs": []}
    if not extension_keys:
        raise FlashRunError("FROZEN_RESUME_C039_QUEUE_BASE_SHA_MISMATCH")

    extension_set = set(extension_keys)
    if any(not isinstance(event, dict) for event in queue_value["events"]):
        raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EVENT_INVALID")
    extension_events = [event for event in queue_value["events"]
                        if event.get("idempotency_key") in extension_set]
    if {event.get("idempotency_key") for event in extension_events} != extension_set:
        raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_EVENTS_INVALID")

    excluded_jobs = []
    identity_fields = set(QUEUE_IDENTITY_FIELDS)
    for key in extension_keys:
        item = jobs[key]
        identity = item.get("identity")
        if (item.get("queue_id") != FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
                or item.get("idempotency_key") != key
                or not isinstance(identity, dict) or set(identity) != identity_fields
                or sha(canonical(identity)) != key
                or item.get("queue_ids") != [FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID]
                or item.get("status") != "FAILED" or item.get("attempt_count") != 1
                or item.get("max_attempts") != 1
                or item.get("input_path") != f"jobs/{key}/input.json"
                or not isinstance(item.get("payload_sha256"), str) or not SHA_RE.fullmatch(item["payload_sha256"])
                or item.get("raw_path") is not None or item.get("raw_sha256") is not None
                or item.get("validated_path") is not None or item.get("validated_sha256") is not None
                or not after_attempt(item.get("created_at")) or not after_attempt(item.get("updated_at"))):
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_RECORD_INVALID")
        try:
            payload_raw = state_io.read_bytes(
                f"announcement_flash/queue/{item['input_path']}", max_bytes=64 * 1024 * 1024)
        except (OSError, ValueError) as exc:
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_PAYLOAD_UNAVAILABLE") from exc
        payload = _json(payload_raw, "FROZEN_RESUME_C039_QUEUE_EXTENSION_PAYLOAD_INVALID")
        if (sha(payload_raw) != item["payload_sha256"] or not isinstance(payload, dict)
                or {field: payload.get(field) for field in QUEUE_IDENTITY_FIELDS} != identity
                or not isinstance(payload.get("article_body"), str)
                or sha(payload["article_body"].encode("utf-8")) != identity.get("body_sha256")
                or item.get("body_length_bytes") != len(payload["article_body"].encode("utf-8"))
                or payload.get("market") != "PDF"
                or payload.get("stage") != "local_pdf_classification"
                or payload.get("role") != "document_classifier"
                or payload.get("rules") != "v4_zsxq_pdf_local_classification_v1"):
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_PAYLOAD_INVALID")
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
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_EVENTS_INVALID")
        attempts = item.get("attempts")
        attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
        error = attempt.get("error") if isinstance(attempt, dict) else None
        if (not isinstance(attempt, dict) or attempt.get("number") != 1
                or attempt.get("status") != "FAILED"
                or attempt.get("consumer_queue_id") != FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
                or not after_attempt(attempt.get("started_at")) or not after_attempt(attempt.get("finished_at"))
                or not isinstance(error, dict) or error.get("code") != "MODEL_TRANSPORT_FAILED"):
            raise FlashRunError("FROZEN_RESUME_C039_QUEUE_EXTENSION_ATTEMPT_INVALID")
        excluded_jobs.append({"key": key, "queue_id": item["queue_id"],
                              "record_sha256": sha(canonical(item)),
                              "payload_sha256": item["payload_sha256"],
                              "events_sha256": sha(canonical(events)), "event_count": len(events)})

    reconstructed = copy.deepcopy(queue_value)
    for key in extension_keys:
        reconstructed["jobs"].pop(key)
    reconstructed["events"] = [event for event in reconstructed["events"]
                               if event.get("idempotency_key") not in extension_set]
    reconstructed_sha = sha(canonical(reconstructed))
    if reconstructed_sha != FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256:
        raise FlashRunError("FROZEN_RESUME_C039_QUEUE_BASE_SHA_MISMATCH")
    return {"schema": "v4.manager_workbench.announcement_queue_reconstruction.v1",
            "baseline_sha256": FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256,
            "reconstructed_sha256": reconstructed_sha,
            "current_sha256": sha(queue_raw),
            "source_attempt_sha256": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256,
            "source_attempt_finished_at": FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT,
            "excluded_jobs": excluded_jobs}


def _verify_failed_dispatch_canary_resume(state_io: SafeRoot, capture_root: Path,
                                         source_job_id: str, target_date: str,
                                         source_hashes: dict[str, str], result_raw: bytes,
                                         source_input: dict[str, Any], result_value: dict[str, Any],
                                          queue_value: dict[str, Any],
                                          queue_reconstruction: dict[str, Any]) -> dict[str, Any]:
    if (source_job_id != FAILED_DISPATCH_CANARY_REENTRY_JOB_ID or target_date != "20261016"
            or source_hashes.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256
            or source_hashes.get("source_progress_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256
            or not isinstance(queue_reconstruction, dict)
            or queue_reconstruction.get("baseline_sha256") != FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256
            or queue_reconstruction.get("reconstructed_sha256") != FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256
            or queue_reconstruction.get("current_sha256") != source_hashes.get("source_queue_state_sha256")
            or sha(result_raw) != FAILED_DISPATCH_CANARY_REENTRY_RESULT_SHA256):
        raise FlashRunError("FROZEN_RESUME_C039_REENTRY_EVIDENCE_CHANGED")
    root = source_input.get("resume_root")
    parent = source_input.get("resume_source")
    if (root != {"source_job_id": FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID,
                 "source_input_sha256": FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256}
            or not isinstance(parent, dict)
            or parent.get("schema") != "v4.manager_workbench.announcement_flash_resume.v1"
            or parent.get("mode") != "INITIAL_CANARY"
            or parent.get("source_job_id") != FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
            or parent.get("target_date") != target_date
            or parent.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256
            or parent.get("source_progress_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256
            or parent.get("source_queue_state_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_QUEUE_SHA256
            or parent.get("source_result_sha256") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_RESULT_SHA256
            or parent.get("canary_key") != FAILED_DISPATCH_CANARY_REENTRY_KEY
            or parent.get("canary_status") != "FAILED" or parent.get("canary_passed") is not False
            or parent.get("resume_action") != "CANARY" or parent.get("max_model_calls") != 1
            or parent.get("queue_status_counts") != {"FAILED": 16, "PENDING": 5, "SUCCEEDED": 24}
            or not isinstance(parent.get("legacy_failed_canary"), dict)):
        raise FlashRunError("FROZEN_RESUME_C039_PARENT_BINDING_INVALID")
    resume = result_value.get("resume") if isinstance(result_value, dict) else None
    if (not isinstance(resume, dict) or result_value.get("state") != "PARTIAL"
            or result_value.get("job_id") != source_job_id
            or result_value.get("target_trade_date") != target_date
            or resume.get("mode") != "FROZEN_BATCH" or resume.get("resume_action") != "CANARY"
            or resume.get("canary_passed") is not False or resume.get("canary_key") is not None
            or resume.get("canary_status") is not None or resume.get("canary_model_calls") != 0
            or resume.get("canary_validation") != {
                "failure_code": "FROZEN_RESUME_CANARY_NOT_SUCCEEDED", "key": None, "status": "FAIL"}
            or resume.get("max_model_calls") != 1 or resume.get("model_calls") != 1
            or resume.get("dispatched_keys") != [FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY]
            or resume.get("source_job_id") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID
            or resume.get("source_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256
            or resume.get("source_input_sha256_binding") != FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256
            or resume.get("initial_part_status_counts") != {"failed": 16, "pending": 5, "succeeded": 24}
            or resume.get("initial_part_total") != 45 or resume.get("failed_preserved") != 16
            or resume.get("succeeded_preserved") != 24 or resume.get("pending_eligible") != 0
            or resume.get("recoverable_orphan_count") != 0 or resume.get("continue_eligible") is not False):
        raise FlashRunError("FROZEN_RESUME_C039_FAILED_CANARY_RESULT_INVALID")

    parent_id = FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
    try:
        parent_input_raw = state_io.read_bytes(f"announcement_flash/jobs/{parent_id}/input.json",
                                               max_bytes=1024 * 1024)
        parent_progress_raw = state_io.read_bytes(f"announcement_flash/jobs/{parent_id}/progress.json",
                                                  max_bytes=1024 * 1024)
        parent_result_raw = state_io.read_bytes(f"announcement_flash/jobs/{parent_id}/result.json",
                                                max_bytes=64 * 1024 * 1024)
    except (OSError, ValueError) as exc:
        raise FlashRunError("FROZEN_RESUME_C039_PARENT_ARTIFACT_UNAVAILABLE") from exc
    if (sha(parent_input_raw) != FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256
            or sha(parent_progress_raw) != FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256
            or sha(parent_result_raw) != FAILED_DISPATCH_CANARY_REENTRY_PARENT_RESULT_SHA256):
        raise FlashRunError("FROZEN_RESUME_C039_PARENT_ARTIFACT_CHANGED")
    parent_input = _json(parent_input_raw, "FROZEN_RESUME_C039_PARENT_INPUT_INVALID")
    parent_result = _json(parent_result_raw, "FROZEN_RESUME_C039_PARENT_RESULT_INVALID")
    root_input = _verify_resume_root_input(
        state_io, FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID,
        FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256, target_date, source_input)
    if (parent_input.get("resume_root") != root
            or parent_input.get("capture_product") != source_input.get("capture_product")
            or parent_input.get("membership_gate") != source_input.get("membership_gate")
            or root_input.get("capture_product") != source_input.get("capture_product")):
        raise FlashRunError("FROZEN_RESUME_C039_ROOT_CHAIN_INVALID")
    queue_root = state_io.root / "announcement_flash" / "queue"
    legacy = _legacy_failed_canary_source_binding(
        parent_id, FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256,
        parent_input, parent_result, queue_value, queue_root, state_io, capture_root)
    if (legacy != parent.get("legacy_failed_canary")
            or legacy.get("key") != FAILED_DISPATCH_CANARY_REENTRY_KEY
            or legacy.get("source_part_key") != FAILED_DISPATCH_CANARY_REENTRY_SOURCE_PART_KEY
            or legacy.get("root_job_id") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID
            or legacy.get("root_input_sha256") != FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256
            or legacy.get("part_descriptor", {}).get("part_index") != FAILED_DISPATCH_CANARY_REENTRY_PART_INDEX
            or legacy.get("part_descriptor", {}).get("part_count") != FAILED_DISPATCH_CANARY_REENTRY_PART_COUNT):
        raise FlashRunError("FROZEN_RESUME_C039_TARGET_CHAIN_INVALID")
    _verify_preserved_synthesis_success(state_io, queue_value)
    return legacy


def _transport_recovery_payload_matches(payload: Any, item: dict[str, Any],
                                        capture_row: dict[str, Any], source_input: dict[str, Any],
                                        source_job_id: str, source_input_sha256: str) -> bool:
    identity = item.get("identity")
    metadata = payload.get("article_metadata") if isinstance(payload, dict) else None
    capture_ref = source_input.get("capture_product")
    gate = source_input.get("membership_gate")
    if (not isinstance(identity, dict) or set(identity) != set(QUEUE_IDENTITY_FIELDS)
            or not isinstance(payload, dict) or not isinstance(metadata, dict)
            or not isinstance(capture_ref, dict) or not isinstance(gate, dict)):
        return False
    frozen_binding = {
        "source_job_id": source_job_id,
        "source_input_sha256": source_input_sha256,
        "target_date": source_input.get("target_date"),
        "cutoff": source_input.get("cutoff"),
        "capture_product_sha256": capture_ref.get("sha256"),
        "membership_authority_sha256": gate.get("authority_sha256"),
    }
    body = payload.get("article_body")
    body_sha = identity.get("body_sha256")
    source_sha = identity.get("source_sha256")
    return bool(
        isinstance(body, str) and isinstance(body_sha, str) and SHA_RE.fullmatch(body_sha)
        and sha(body.encode("utf-8")) == body_sha
        and payload.get("market") == "HK" and payload.get("role") == "announcement_reader"
        and payload.get("stage") == "v4_manager_announcement_flash_incremental"
        and identity.get("market") == "HK" and identity.get("role") == "announcement_reader"
        and identity.get("stage") == "v4_manager_announcement_flash_incremental"
        and capture_row.get("body_complete") is True
        and capture_row.get("source_sha256") == source_sha
        and capture_row.get("body_text_sha256") == body_sha
        and capture_row.get("body_artifact_ref") == f"products/{source_sha}.json"
        and capture_row.get("body_text") == body
        and metadata.get("publication_date") == capture_row.get("publication_date")
        and identity.get("date") == capture_row.get("publication_date")
        and _current_frozen_resume_payload_valid(payload, gate, frozen_binding)
        and {field: payload.get(field) for field in QUEUE_IDENTITY_FIELDS} == identity
        and item.get("queue_id") == QUEUE_ID and item.get("idempotency_key") == sha(canonical(identity))
    )


def _build_transport_recovery_plan(source_job_id: str, target_date: str,
                                   source_input: dict[str, Any], progress_value: dict[str, Any],
                                   result_value: dict[str, Any], result_raw: bytes,
                                   queue_value: dict[str, Any], hashes: dict[str, str],
                                   capture_product: dict[str, Any], queue_root: Path) -> dict[str, Any]:
    system_stop = result_value.get("system_stop")
    queue_counts = result_value.get("counts", {}).get("queue") if isinstance(result_value.get("counts"), dict) else None
    failures = result_value.get("failures")
    pending = result_value.get("pending")
    jobs = queue_value.get("jobs")
    if (result_value.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
            or result_value.get("job_id") != source_job_id
            or result_value.get("target_trade_date") != target_date
            or result_value.get("state") != "PARTIAL"
            or not isinstance(system_stop, dict) or system_stop.get("stage") != "executor"
            or system_stop.get("failure_code") != "TransportError"
            or system_stop.get("queue_action") != "STOPPED_NO_AUTOMATIC_RETRY"
            or system_stop.get("attempt") != 1
            or progress_value.get("step") != "DONE" or progress_value.get("result_state") != "PARTIAL"
            or not isinstance(queue_counts, dict) or not isinstance(failures, list)
            or not isinstance(pending, list) or not isinstance(jobs, dict)):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_SYSTEM_STOP_NOT_EXACT")
    failure_rows = [row for row in failures if isinstance(row, dict)
                    and row.get("stage") == "executor" and row.get("failure_code") == "TransportError"]
    if len(failure_rows) != 1:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILURE_NOT_UNIQUE")
    failed_article_id = failure_rows[0].get("article_id")
    if not isinstance(failed_article_id, str) or not failed_article_id.startswith("EASTMONEY:"):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILURE_IDENTITY_INVALID")
    rows = capture_product.get("rows")
    if not isinstance(rows, list):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CAPTURE_INVALID")
    rows_by_article: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CAPTURE_ROW_INVALID")
        code = row.get("art_code")
        if isinstance(code, str) and code:
            key = "EASTMONEY:" + code
            if key in rows_by_article:
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_CAPTURE_DUPLICATE")
            rows_by_article[key] = row

    def matching(article_id: str, status: str) -> list[tuple[str, dict[str, Any]]]:
        row = rows_by_article.get(article_id)
        matches = []
        for key, item in jobs.items():
            identity = item.get("identity") if isinstance(item, dict) else None
            if (not isinstance(item, dict) or not isinstance(identity, dict)
                    or identity.get("article_id") != article_id
                    or not isinstance(row, dict)
                    or identity.get("date") != row.get("publication_date")
                    or identity.get("source_sha256") != row.get("source_sha256")
                    or identity.get("body_sha256") != row.get("body_text_sha256")
                    or identity.get("market") != "HK" or identity.get("role") != "announcement_reader"
                    or identity.get("stage") != "v4_manager_announcement_flash_incremental"
                    or item.get("queue_id") != QUEUE_ID or item.get("status") != status):
                continue
            matches.append((key, item))
        return matches

    failed_row = rows_by_article.get(failed_article_id)
    failed_matches = matching(failed_article_id, "FAILED")
    if not isinstance(failed_row, dict) or len(failed_matches) != 1:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_FAILURE_NOT_UNIQUE")
    failed_key, failed_item = failed_matches[0]
    attempts = failed_item.get("attempts")
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    error = attempt.get("error") if isinstance(attempt, dict) else None
    if (failed_item.get("idempotency_key") != failed_key or failed_item.get("attempt_count") != 1
            or failed_item.get("max_attempts") != 1 or sha(canonical(failed_item.get("identity"))) != failed_key
            or failed_item.get("input_path") != f"jobs/{failed_key}/input.json"
            or not isinstance(attempt, dict) or attempt.get("status") != "FAILED" or attempt.get("number") != 1
            or not isinstance(error, dict) or error.get("stage") != "executor"
            or error.get("code") != "TransportError"):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_FAILURE_NOT_EXACT")
    try:
        failed_payload = _queue_payload(queue_root, failed_item)
    except FlashRunError as exc:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_PAYLOAD_UNAVAILABLE") from exc
    if not _transport_recovery_payload_matches(failed_payload, failed_item, failed_row,
                                              source_input, source_job_id, hashes["source_input_sha256"]):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_PAYLOAD_UNVERIFIED")

    pending_rows = [row for row in pending if isinstance(row, dict)
                    and row.get("queue_reason") == "STOPPED_AFTER_SYSTEM_FAILURE"
                    and "part_index" not in row and "part_count" not in row]
    if (not pending_rows or len({row.get("article_id") for row in pending_rows}) != len(pending_rows)
            or any(not isinstance(row.get("article_id"), str) for row in pending_rows)):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PLAN_INVALID")
    pending_tasks = []
    for row in pending_rows:
        article_id = row["article_id"]
        capture_row = rows_by_article.get(article_id)
        candidates = matching(article_id, "PENDING")
        if not isinstance(capture_row, dict) or len(candidates) != 1:
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_QUEUE_NOT_UNIQUE")
        key, item = candidates[0]
        if (item.get("idempotency_key") != key or item.get("attempt_count") != 0
                or item.get("max_attempts") != 1 or sha(canonical(item.get("identity"))) != key
                or item.get("input_path") != f"jobs/{key}/input.json"):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_QUEUE_NOT_ELIGIBLE")
        try:
            payload = _queue_payload(queue_root, item)
        except FlashRunError as exc:
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PAYLOAD_UNAVAILABLE") from exc
        if not _transport_recovery_payload_matches(payload, item, capture_row,
                                                   source_input, source_job_id, hashes["source_input_sha256"]):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PAYLOAD_UNVERIFIED")
        pending_tasks.append({"key": key, "payload_sha256": item["payload_sha256"],
                              "identity_sha256": sha(canonical(item["identity"]))})
    pending_tasks.sort(key=lambda row: row["key"])
    completed, total = progress_value.get("completed"), progress_value.get("total")
    succeeded, failed, pending_count = (queue_counts.get("succeeded"), queue_counts.get("failed"),
                                        queue_counts.get("pending"))
    if (any(type(value) is not int or value < 0
            for value in (completed, total, succeeded, failed, pending_count))
            or completed != succeeded or total != succeeded + failed + pending_count
            or pending_count != len(pending_tasks) or failed < 1 or progress_value.get("queue_counts") is not None):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_PROGRESS_COUNTS_UNVERIFIED")
    return {
        "schema": TRANSPORT_RECOVERY_SCHEMA, "source_job_id": source_job_id,
        "source_input_sha256": hashes["source_input_sha256"],
        "source_progress_sha256": hashes["source_progress_sha256"],
        "source_result_sha256": sha(result_raw),
        "source_queue_state_sha256": hashes["source_queue_state_sha256"],
        "capture_product_sha256": source_input["capture_product"]["sha256"],
        "failed_task": {"article_id": failed_article_id, "key": failed_key,
                        "payload_sha256": failed_item["payload_sha256"],
                        "identity_sha256": sha(canonical(failed_item["identity"])),
                        "attempt_sha256": sha(canonical(attempt))},
        "pending_tasks": pending_tasks,
        "pending_manifest_sha256": sha(canonical(pending_tasks)),
        "queue_status_counts": {"SUCCEEDED": succeeded, "FAILED": failed, "PENDING": pending_count},
    }


def _transport_recovery_canary_binding(plan: dict[str, Any]) -> dict[str, Any]:
    failure = plan.get("failed_task")
    if not isinstance(failure, dict):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
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
    return {**material, "binding_sha256": sha(canonical(material))}


def _verify_saved_transport_canary(state_io: SafeRoot, capture_root: Path, source_job_id: str,
                                   target_date: str, source_input: dict[str, Any],
                                   result_value: dict[str, Any], queue_value: dict[str, Any],
                                   plan: Any) -> None:
    resume = result_value.get("resume")
    validation = (_transport_canary_receipt_candidate(resume, plan, queue_value.get("jobs", {}))
                  if isinstance(plan, dict) and isinstance(queue_value, dict) else None)
    root = source_input.get("resume_root")
    nested = source_input.get("resume_source")
    if (not isinstance(plan, dict)
            or set(plan) != {"schema", "source_job_id", "source_input_sha256", "source_progress_sha256",
                             "source_result_sha256", "source_queue_state_sha256", "capture_product_sha256",
                             "failed_task", "pending_tasks", "pending_manifest_sha256", "queue_status_counts"}
            or plan.get("schema") != TRANSPORT_RECOVERY_SCHEMA
            or not isinstance(resume, dict) or resume.get("mode") != "FROZEN_BATCH"
            or resume.get("resume_action") != "CANARY" or resume.get("transport_recovery") != plan
            or result_value.get("schema") != "v4.manager_workbench.announcement_flash_result.v1"
            or result_value.get("job_id") != source_job_id
            or result_value.get("target_trade_date") != target_date
            or result_value.get("state") != "PARTIAL"
            or resume.get("canary_model_calls") != 1 or resume.get("max_model_calls") != 1
            or validation is None or resume.get("canary_status") != "SUCCEEDED"
            or source_job_id == plan.get("source_job_id")
            or not isinstance(root, dict)
            or not isinstance(nested, dict) or nested.get("transport_recovery") != plan
            or nested.get("source_job_id") != plan.get("source_job_id")
            or nested.get("source_input_sha256") != plan.get("source_input_sha256")
            or nested.get("source_progress_sha256") != plan.get("source_progress_sha256")
            or nested.get("source_result_sha256") != plan.get("source_result_sha256")
            or nested.get("source_queue_state_sha256") != plan.get("source_queue_state_sha256")
            or nested.get("capture_product_sha256") != plan.get("capture_product_sha256")
            or resume.get("source_job_id") != plan.get("source_job_id")
            or resume.get("source_input_sha256") != plan.get("source_input_sha256")
            or resume.get("source_input_sha256_binding") != nested.get("source_input_sha256")
            or not isinstance(plan.get("pending_tasks"), list) or not plan["pending_tasks"]
            or plan.get("pending_manifest_sha256") != sha(canonical(plan["pending_tasks"]))
            or plan["pending_tasks"] != sorted(plan["pending_tasks"], key=lambda row: row.get("key", ""))
            or len({row.get("key") for row in plan["pending_tasks"] if isinstance(row, dict)})
            != len(plan["pending_tasks"])):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_RESULT_NOT_ELIGIBLE")
    _verify_transport_original_root(state_io, source_input, plan)
    failure = plan.get("failed_task")
    if (not isinstance(failure, dict)
            or set(failure) != {"article_id", "key", "payload_sha256", "identity_sha256", "attempt_sha256"}
            or not all(isinstance(failure.get(field), str) and SHA_RE.fullmatch(failure[field])
                       for field in ("key", "payload_sha256", "identity_sha256", "attempt_sha256"))):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
    for field in ("source_input_sha256", "source_progress_sha256", "source_result_sha256",
                  "source_queue_state_sha256", "capture_product_sha256"):
        if not isinstance(plan.get(field), str) or not SHA_RE.fullmatch(plan[field]):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_SOURCE_INVALID")
    if any(not isinstance(row, dict) or set(row) != {"key", "payload_sha256", "identity_sha256"}
           or any(not isinstance(row.get(field), str) or not SHA_RE.fullmatch(row[field])
                  for field in ("key", "payload_sha256", "identity_sha256"))
           for row in plan["pending_tasks"]):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PLAN_INVALID")
    source_id = plan["source_job_id"]
    try:
        source_input_raw = state_io.read_bytes(f"announcement_flash/jobs/{source_id}/input.json",
                                               max_bytes=1024 * 1024)
        source_progress_raw = state_io.read_bytes(f"announcement_flash/jobs/{source_id}/progress.json",
                                                  max_bytes=1024 * 1024)
        source_result_raw = state_io.read_bytes(f"announcement_flash/jobs/{source_id}/result.json",
                                                max_bytes=64 * 1024 * 1024)
        root_input = _json(source_input_raw, "FROZEN_RESUME_TRANSPORT_ROOT_INPUT_INVALID")
        root_result = _json(source_result_raw, "FROZEN_RESUME_TRANSPORT_ROOT_RESULT_INVALID")
        capture_ref = source_input.get("capture_product")
        capture_raw = SafeRoot(capture_root).read_bytes(capture_ref["artifact_ref"], max_bytes=256 * 1024 * 1024)
        capture_product = _json(capture_raw, "FROZEN_RESUME_TRANSPORT_CAPTURE_INVALID")
    except (OSError, KeyError, TypeError) as exc:
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_SOURCE_UNAVAILABLE") from exc
    if (sha(source_input_raw) != plan["source_input_sha256"]
            or sha(source_progress_raw) != plan["source_progress_sha256"]
            or sha(source_result_raw) != plan["source_result_sha256"]
            or sha(capture_raw) != plan["capture_product_sha256"]
            or not isinstance(root_input, dict) or root_input.get("target_date") != target_date
            or root_input.get("capture_product") != source_input.get("capture_product")
            or root_input.get("membership_gate") != source_input.get("membership_gate")
            or not isinstance(root_result, dict)
            or root_result.get("system_stop", {}).get("failure_code") != "TransportError"):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_SOURCE_BINDING_UNVERIFIED")
    capture_rows = capture_product.get("rows") if isinstance(capture_product, dict) else None
    rows_by_article = {"EASTMONEY:" + str(row.get("art_code")): row for row in capture_rows
                       if isinstance(row, dict) and isinstance(row.get("art_code"), str)} \
        if isinstance(capture_rows, list) else {}
    jobs = queue_value.get("jobs") if isinstance(queue_value, dict) else None
    if not isinstance(jobs, dict):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_QUEUE_INVALID")
    failure_item = jobs.get(failure["key"])
    if (not isinstance(failure_item, dict) or failure_item.get("status") != "FAILED"
            or failure_item.get("idempotency_key") != failure["key"]
            or failure_item.get("attempt_count") != 1 or failure_item.get("max_attempts") != 1
            or failure_item.get("payload_sha256") != failure["payload_sha256"]
            or sha(canonical(failure_item.get("identity"))) != failure["identity_sha256"]
            or failure_item.get("input_path") != f"jobs/{failure['key']}/input.json"):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_SOURCE_INVALID")
    attempts = failure_item.get("attempts")
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    if (not isinstance(attempt, dict) or sha(canonical(attempt)) != failure["attempt_sha256"]
            or attempt.get("status") != "FAILED" or attempt.get("number") != 1
            or attempt.get("error", {}).get("stage") != "executor"
            or attempt.get("error", {}).get("code") != "TransportError"):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_ATTEMPT_INVALID")
    capture_row = rows_by_article.get(failure.get("article_id"))
    if not isinstance(capture_row, dict):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_CAPTURE_INVALID")
    failed_payload = _queue_payload(state_io.root / "announcement_flash" / "queue", failure_item)
    if not _transport_recovery_payload_matches(failed_payload, failure_item, capture_row,
                                               root_input, source_id, plan["source_input_sha256"]):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_FAILED_PAYLOAD_INVALID")
    for entry in plan["pending_tasks"]:
        item = jobs.get(entry["key"])
        if (not isinstance(item, dict) or item.get("status") != "PENDING"
                or item.get("attempt_count") != 0 or item.get("max_attempts") != 1
                or item.get("payload_sha256") != entry["payload_sha256"]
                or sha(canonical(item.get("identity"))) != entry["identity_sha256"]
                or item.get("input_path") != f"jobs/{entry['key']}/input.json"):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_TASK_CHANGED")
        pending_payload = _queue_payload(state_io.root / "announcement_flash" / "queue", item)
        pending_capture_row = rows_by_article.get(item.get("identity", {}).get("article_id"))
        if (not isinstance(pending_capture_row, dict)
                or not _transport_recovery_payload_matches(pending_payload, item, pending_capture_row,
                                                           root_input, source_id, plan["source_input_sha256"])):
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_PENDING_PAYLOAD_INVALID")
    canary_key = resume.get("canary_key")
    canary_job = jobs.get(canary_key) if isinstance(canary_key, str) else None
    if (not isinstance(canary_key, str) or not SHA_RE.fullmatch(canary_key)
            or not isinstance(canary_job, dict) or canary_job.get("queue_id") != QUEUE_ID
            or canary_job.get("status") != "SUCCEEDED" or canary_job.get("attempt_count") != 1
            or canary_job.get("max_attempts") != 1 or canary_job.get("idempotency_key") != canary_key
            or not isinstance(validation, dict) or validation.get("key") != canary_key
            or validation.get("validated_sha256") != canary_job.get("validated_sha256")
            or validation.get("raw_sha256") != canary_job.get("raw_sha256")):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_QUEUE_STATE_INVALID")
    canary_payload = _queue_payload(state_io.root / "announcement_flash" / "queue", canary_job)
    frozen_binding = {"source_job_id": root["source_job_id"], "source_input_sha256": root["source_input_sha256"],
                      "target_date": target_date, "cutoff": source_input.get("cutoff"),
                      "capture_product_sha256": source_input["capture_product"]["sha256"],
                      "membership_authority_sha256": source_input.get("membership_gate", {}).get("authority_sha256")}
    expected_payload = {**failed_payload,
                        "rules": failed_payload.get("rules", "") + "+explicit-transport-resume:v1",
                        "transport_recovery_binding": _transport_recovery_canary_binding(plan),
                        "frozen_resume_binding": frozen_binding}
    if (canonical(canary_payload) != canonical(expected_payload)
            or {field: canary_payload.get(field) for field in QUEUE_IDENTITY_FIELDS} != canary_job.get("identity")
            or _validated_transport_canary_result(
                state_io.root / "announcement_flash" / "queue", canary_job, canary_payload, plan) != validation):
        raise FlashRunError("FROZEN_RESUME_TRANSPORT_CANARY_RESULT_UNVERIFIED")


def _verify_resume_source(state_io: SafeRoot, capture_root: Path, source_job_id: str,
                          target_date: str, expected_hashes: dict[str, str],
                          expected_queue_reconstruction: dict[str, Any] | None = None,
                          expected_transport_recovery: dict[str, Any] | None = None
                          ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
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
    capture_product = _json(capture_raw, "FROZEN_RESUME_CAPTURE_INVALID")
    result_raw = None
    try:
        result_raw = state_io.read_bytes(base + "/result.json", max_bytes=64 * 1024 * 1024)
    except FileNotFoundError:
        pass
    if result_raw is None:
        if expected_transport_recovery is not None:
            raise FlashRunError("FROZEN_RESUME_TRANSPORT_SOURCE_RESULT_MISSING")
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
        legacy_failed_canary = None
        queue_reconstruction = None
        verified_transport_recovery = False
        if source_job_id == FAILED_DISPATCH_CANARY_REENTRY_JOB_ID:
            queue_reconstruction = _verify_c039_queue_reconstruction(state_io, queue_raw, queue_value)
            if (expected_queue_reconstruction is not None
                    and expected_queue_reconstruction != queue_reconstruction):
                raise FlashRunError("FROZEN_RESUME_C039_QUEUE_RECONSTRUCTION_BINDING_CHANGED")
            legacy_failed_canary = _verify_failed_dispatch_canary_resume(
                state_io, capture_root, source_job_id, target_date, hashes, result_raw,
                input_value, result_value, queue_value, queue_reconstruction)
        elif expected_queue_reconstruction is not None:
            raise FlashRunError("FROZEN_RESUME_QUEUE_RECONSTRUCTION_UNEXPECTED")
        if legacy_failed_canary is None:
            if isinstance(result_value, dict) and isinstance(result_value.get("system_stop"), dict):
                if expected_transport_recovery is None:
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_BINDING_MISSING")
                plan = _build_transport_recovery_plan(
                    source_job_id, target_date, input_value, progress_value, result_value,
                    result_raw, queue_value, hashes, capture_product,
                    state_io.root / "announcement_flash" / "queue")
                if plan != expected_transport_recovery:
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_BINDING_CHANGED")
                verified_transport_recovery = True
            elif isinstance(resume_value, dict) and isinstance(resume_value.get("transport_recovery"), dict):
                plan = resume_value.get("transport_recovery")
                if expected_transport_recovery != plan:
                    raise FlashRunError("FROZEN_RESUME_TRANSPORT_BINDING_CHANGED")
                _verify_saved_transport_canary(state_io, capture_root, source_job_id, target_date,
                                               input_value, result_value, queue_value, plan)
                verified_transport_recovery = True
            elif expected_transport_recovery is not None:
                raise FlashRunError("FROZEN_RESUME_TRANSPORT_BINDING_UNEXPECTED")
            elif (isinstance(result_value, dict) and result_value.get("state") == "PARTIAL"
                    and isinstance(resume_value, dict) and resume_value.get("mode") == "FROZEN_BATCH"
                    and resume_value.get("canary_passed") is False):
                legacy_failed_canary = _legacy_failed_canary_source_binding(
                    source_job_id, hashes["source_input_sha256"], input_value, result_value,
                    queue_value, state_io.root / "announcement_flash" / "queue", state_io, capture_root)
        if legacy_failed_canary is None and not verified_transport_recovery:
            if (not isinstance(result_value, dict) or result_value.get("state") != "PARTIAL"
                    or not isinstance(resume_value, dict) or resume_value.get("mode") != "FROZEN_BATCH"
                    or resume_value.get("resume_action") != "CANARY"
                    or resume_value.get("canary_passed") is not True
                    or resume_value.get("canary_status") != "SUCCEEDED"
                    or resume_value.get("canary_model_calls") != 1
                    or resume_value.get("max_model_calls") != 1
                    or not isinstance(resume_value.get("canary_validation"), dict)
                    or resume_value["canary_validation"].get("status") != "PASS"):
                raise FlashRunError("FROZEN_RESUME_RESULT_NOT_ELIGIBLE")
            canary_key = resume_value.get("canary_key")
            validation = resume_value.get("canary_validation")
            if not isinstance(canary_key, str) or not SHA_RE.fullmatch(canary_key):
                raise FlashRunError("FROZEN_RESUME_CANARY_KEY_INVALID")
            canary_job = queue_value["jobs"].get(canary_key)
            if (not isinstance(canary_job, dict) or canary_job.get("idempotency_key") != canary_key
                    or canary_job.get("queue_id") != QUEUE_ID or canary_job.get("status") != "SUCCEEDED"
                    or canary_job.get("attempt_count") != 1 or canary_job.get("max_attempts") != 1
                    or not isinstance(canary_job.get("identity"), dict)
                    or sha(canonical(canary_job["identity"])) != canary_key):
                raise FlashRunError("FROZEN_RESUME_CANARY_QUEUE_STATE_INVALID")
            canary_payload_ref = canary_job.get("input_path")
            canary_payload_sha = canary_job.get("payload_sha256")
            if (canary_payload_ref != f"jobs/{canary_key}/input.json"
                    or not isinstance(canary_payload_sha, str) or not SHA_RE.fullmatch(canary_payload_sha)):
                raise FlashRunError("FROZEN_RESUME_CANARY_PAYLOAD_REFERENCE_INVALID")
            canary_payload_raw = state_io.read_bytes(
                "announcement_flash/queue/" + canary_payload_ref, max_bytes=64 * 1024 * 1024)
            canary_payload = _json(canary_payload_raw, "FROZEN_RESUME_CANARY_PAYLOAD_INVALID")
            binding = canary_payload.get("part_repair_binding") if isinstance(canary_payload, dict) else None
            root = input_value.get("resume_root")
            expected_root_job = root.get("source_job_id") if isinstance(root, dict) else source_job_id
            expected_root_input = root.get("source_input_sha256") if isinstance(root, dict) else hashes["source_input_sha256"]
            frozen_binding = canary_payload.get("frozen_resume_binding") if isinstance(canary_payload, dict) else None
            if (sha(canary_payload_raw) != canary_payload_sha
                    or set(canary_job["identity"]) != set(QUEUE_IDENTITY_FIELDS)
                    or {field: canary_payload.get(field) for field in QUEUE_IDENTITY_FIELDS}
                    != canary_job.get("identity")
                    or canary_payload.get("queue_task_kind") != "announcement_reader_part"
                    or not isinstance(binding, dict)
                    or binding.get("failure_code") != "PART_FIXED_FIELDS_MUST_BE_EMPTY"
                    or binding.get("binding_sha256") != validation.get("binding_sha256")
                    or not isinstance(frozen_binding, dict)
                    or frozen_binding.get("source_job_id") != expected_root_job
                    or frozen_binding.get("source_input_sha256") != expected_root_input
                    or validation.get("key") != canary_key
                    or validation.get("validated_sha256") != canary_job.get("validated_sha256")
                    or validation.get("raw_sha256") != canary_job.get("raw_sha256")):
                raise FlashRunError("FROZEN_RESUME_CANARY_SOURCE_BINDING_INVALID")
            queue_root = state_io.root / "announcement_flash" / "queue"
            if _saved_orphan_result_state(queue_root, canary_job, canary_payload) != "COMPLETE":
                raise FlashRunError("FROZEN_RESUME_CANARY_RESULT_UNVERIFIED")
    return input_value, queue_value, legacy_failed_canary if result_raw is not None else None


def _verify_resume_root_input(state_io: SafeRoot, root_job_id: str, root_input_sha256: str,
                              target_date: str, current_input: dict[str, Any]) -> dict[str, Any]:
    if (not JOB_ID_RE.fullmatch(str(root_job_id)) or not SHA_RE.fullmatch(str(root_input_sha256))
            or not re.fullmatch(r"[0-9]{8}", str(target_date))):
        raise FlashRunError("FROZEN_RESUME_ROOT_BINDING_INVALID")
    raw = state_io.read_bytes(f"announcement_flash/jobs/{root_job_id}/input.json", max_bytes=1024 * 1024)
    if sha(raw) != root_input_sha256:
        raise FlashRunError("FROZEN_RESUME_ROOT_INPUT_SHA_CHANGED")
    value = _json(raw, "FROZEN_RESUME_ROOT_INPUT_INVALID")
    if (not isinstance(value, dict) or canonical(value) != raw
            or value.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
            or value.get("job_id") != root_job_id or value.get("target_date") != target_date
            or value.get("capture_product") != current_input.get("capture_product")
            or value.get("membership_gate") != current_input.get("membership_gate")
            or value.get("classification_policy") != current_input.get("classification_policy")):
        raise FlashRunError("FROZEN_RESUME_ROOT_INPUT_BINDING_INVALID")
    return value


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


def _main(argv: list[str] | None = None, *, signalled: list[int]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--shared-root")
    parser.add_argument("--legacy-gate-binding")
    parser.add_argument("--legacy-gate-binding-sha256")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--resume-pending", action="store_true",
                        help="Run only this frozen input's verified eligible zero-attempt PENDING queue items.")
    parser.add_argument("--resume-frozen-batch", action="store_true",
                        help="Resume the exact frozen source input without capture or retrying failed items.")
    parser.add_argument("--resume-action", choices=("CANARY", "CONTINUE"))
    parser.add_argument("--resume-dry-run", action="store_true",
                        help="Print a read-only frozen-resume plan; never writes queue or job state.")
    parser.add_argument("--resume-source-job-id")
    parser.add_argument("--source-input-sha256")
    parser.add_argument("--source-progress-sha256")
    parser.add_argument("--source-queue-state-sha256")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--preprocess-only", action="store_true")
    parser.add_argument("--execute-preprocessed-report-sha256")
    parser.add_argument("--execution-phase", choices=("FIRST", "CONTINUE", "RECOVER_FAILED", "CONTINUE_REMAINING"))
    parser.add_argument("--extension-sha256")
    parser.add_argument("--materialize-saved-partial", action="store_true",
                        help="Publish only hash-verified saved results after a recorded failed run; never dispatch queue work.")
    parser.add_argument("--failure-code", help="Exact failure code recorded in progress.json for saved-result materialization.")
    args = parser.parse_args(argv)
    legacy_gate = None
    preparation_guard = None
    if args.legacy_gate_binding or args.legacy_gate_binding_sha256:
        try:
            path = Path(args.legacy_gate_binding)
            if any(p.is_symlink() for p in (path, *path.parents)):
                return 2
            raw = path.read_bytes()
            if sha(raw) != args.legacy_gate_binding_sha256:
                return 2
            legacy_gate = json.loads(raw)
            _test_legacy_gate(legacy_gate, 'qwen3_8_flash_next')
            if 'isolated_preparation' in legacy_gate:
                preparation_guard = _isolated_preparation_guard(args, legacy_gate, path, args.legacy_gate_binding_sha256)
            elif (not args.execute_preprocessed_report_sha256 or args.execution_phase != 'FIRST'
                    or args.resume_pending or args.resume_frozen_batch or args.preprocess_only
                    or args.materialize_saved_partial or args.resume_dry_run):
                return 2
        except (OSError, ValueError, TypeError, KeyError, FlashRunError) as exc:
            if isinstance(legacy_gate, dict) and 'isolated_preparation' in legacy_gate:
                print(json.dumps({'state': 'BLOCKED', 'code': getattr(exc, 'code', 'ISOLATED_PREPARATION_BINDING_INVALID')}), flush=True)
            return 2
    if not JOB_ID_RE.fullmatch(args.job_id):
        return 2
    state_root = Path(args.state_root).expanduser().absolute()
    capture_root = Path(args.capture_root).expanduser().absolute()
    state_io = SafeRoot(state_root)
    base = f"announcement_flash/jobs/{args.job_id}"
    user_stop = _UserStop(state_io, args.job_id, signalled)
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
            source_input, _source_queue, verified_legacy_failed_canary = _verify_resume_source(
                state_io, capture_root, args.resume_source_job_id,
                input_value["target_date"], source_hashes,
            )
            before_queue = state_io.read_bytes("announcement_flash/queue/queue-state.json",
                                               max_bytes=64 * 1024 * 1024)
            result = _run(source_input, state_root=state_root, capture_root=capture_root,
                          job_id=args.resume_source_job_id, progress=lambda _value: None,
                          shared_root=Path(args.shared_root).expanduser().absolute() if args.shared_root else None,
                          resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
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
            if args.resume_pending or args.materialize_saved_partial or args.resume_action not in {"CANARY", "CONTINUE"}:
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
            if args.resume_action != resume_source.get("resume_action"):
                raise FlashRunError("FROZEN_RESUME_ACTION_BINDING_MISMATCH")
            expected_queue_reconstruction = resume_source.get("queue_reconstruction")
            if (resume_source.get("source_job_id") == FAILED_DISPATCH_CANARY_REENTRY_JOB_ID
                    and not isinstance(expected_queue_reconstruction, dict)):
                raise FlashRunError("FROZEN_RESUME_C039_QUEUE_RECONSTRUCTION_MISSING")
            expected_transport_recovery = resume_source.get("transport_recovery")
            verified_source_input, _source_queue, verified_legacy_failed_canary = _verify_resume_source(
                state_io, capture_root, str(resume_source.get("source_job_id")),
                input_value["target_date"], source_hashes,
                expected_queue_reconstruction=expected_queue_reconstruction,
                expected_transport_recovery=expected_transport_recovery)
            input_legacy_failed_canary = resume_source.get("legacy_failed_canary")
            if (verified_legacy_failed_canary is None) != (input_legacy_failed_canary is None):
                raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_BINDING_MISMATCH")
            if isinstance(verified_legacy_failed_canary, dict):
                compare_fields = tuple(verified_legacy_failed_canary)
                if (not isinstance(input_legacy_failed_canary, dict)
                        or any(input_legacy_failed_canary.get(field) != verified_legacy_failed_canary.get(field)
                               for field in compare_fields)
                        or not isinstance(input_legacy_failed_canary.get("source_part_key"), str)
                        or not SHA_RE.fullmatch(input_legacy_failed_canary["source_part_key"])):
                    raise FlashRunError("FROZEN_RESUME_LEGACY_CANARY_BINDING_MISMATCH")
            if isinstance(expected_transport_recovery, dict):
                # Transport recovery verifies the direct source separately from
                # the inherited original root used by part plans and payloads.
                source_job_id = resume_source["source_job_id"]
                source_input_sha256 = source_hashes["source_input_sha256"]
            else:
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
            if preparation_guard is not None:
                preparation_guard()
            value = dict(value)
            for key in ('classification_plan','classification_preview','classification_model_plan'):
                if key not in value and key in last_progress['value']:
                    value[key] = copy.deepcopy(last_progress['value'][key])
            _write_json(state_io, base + "/progress.json", value)
            last_progress["value"] = value
        if user_stop():
            try:
                prior = _json(state_io.read_bytes(base + "/progress.json", max_bytes=1024 * 1024),
                              "FLASH_PROGRESS_INVALID")
            except FileNotFoundError:
                prior = {}
            write_progress({**prior, "step": "USER_STOPPED", "result_state": "USER_STOPPED",
                            "updated_at": datetime.now(timezone.utc).isoformat()})
            return 0
        if input_value.get("daily_workflow") == "P23" and not (args.preprocess_only or args.execute_preprocessed_report_sha256):
            raise FlashRunError("PREPROCESSING_CHECKPOINT_REQUIRED")
        if args.execute_preprocessed_report_sha256 and (args.preprocess_only or not args.execution_phase
                or not SHA_RE.fullmatch(args.execute_preprocessed_report_sha256)):
            raise FlashRunError("PREPROCESSING_EXECUTION_ARGUMENTS_INVALID")
        result = _run(input_value, state_root=state_root, capture_root=capture_root,
                      job_id=args.job_id, progress=write_progress,
                      shared_root=Path(args.shared_root).expanduser().absolute() if args.shared_root else None,
                      resume_same_batch_pending=args.resume_pending,
                      resume_frozen_batch=args.resume_frozen_batch,
                      resume_action=args.resume_action if args.resume_frozen_batch else None,
                      max_model_calls=args.max_model_calls if args.resume_frozen_batch else None,
                      resume_source_job_id=source_job_id,
                      resume_source_input_sha256=source_input_sha256,
                      require_classification_policy=not args.resume_frozen_batch and not args.resume_pending,
                      stop_requested=user_stop, preprocess_only=args.preprocess_only,
                      execute_report_sha256=args.execute_preprocessed_report_sha256,
                      execution_phase=args.execution_phase, extension_sha256=args.extension_sha256,
                      **({'legacy_gate': legacy_gate} if legacy_gate is not None else {}),
                      **({'preparation_guard': preparation_guard} if preparation_guard is not None else {}))
        if result.get("state") == "PREPROCESSING_COMPLETE":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if user_stop() and result.get("system_stop") is None:
            result = {**result, "state": "USER_STOPPED", "system_stop": _user_stop_receipt()}
        if args.execute_preprocessed_report_sha256:
            if result["state"] == "USER_STOPPED":
                from v4.manager_workbench.announcement_delivery import read as read_delivery, publish as publish_delivery
                delivered, _binding = read_delivery(state_io, args.job_id)
                if delivered and delivered.get("state") != "USER_STOPPED":
                    publish_delivery(state_io, args.job_id, {**delivered, "state": "USER_STOPPED"})
            result_raw = canonical(result) + b"\n"
            result_sha = sha(result_raw)
            summary_ref = base + "/execution-summaries/" + result_sha + ".json"
            if result_path_is_absent(state_io, summary_ref):
                state_io.write_bytes(summary_ref, result_raw, require_absent=True)
            write_progress({"step": "USER_STOPPED" if result["state"] == "USER_STOPPED" else "DAILY_INVOCATION_DONE",
                            "daily_workflow": "P23", "execution_phase": args.execution_phase,
                            "execution_summary": {"artifact_ref": summary_ref, "sha256": result_sha},
                            "preprocessing": result.get("preprocessing"), "result_state": result["state"],
                            "completed": result["counts"]["queue"].get("succeeded", 0),
                            "total": result["counts"]["queue"].get("succeeded", 0) + result["counts"]["queue"].get("failed", 0)
                            + result["counts"]["queue"].get("pending", 0)})
            return 0
        _write_json(state_io, base + "/result.json", result)
        write_progress({"step": "USER_STOPPED" if result["state"] == "USER_STOPPED" else "DONE",
                        "completed": result["counts"]["queue"].get("succeeded", 0),
                        "total": result["counts"]["queue"].get("succeeded", 0) + result["counts"]["queue"].get("failed", 0)
                        + result["counts"]["queue"].get("pending", 0), "result_state": result["state"],
                        "membership": result.get("membership_gate"),
                        "updated_at": datetime.now(timezone.utc).isoformat()})
        return 0
    except FlashRunError as exc:
        if preparation_guard is not None:
            print(json.dumps({'state': 'BLOCKED', 'code': exc.code}), flush=True)
            return 2
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
        if preparation_guard is not None:
            print(json.dumps({'state': 'BLOCKED', 'code': 'ISOLATED_PREPARATION_FAILED', 'error_type': type(exc).__name__}), flush=True)
            return 2
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


def main(argv: list[str] | None = None) -> int:
    with _cooperative_stop_signals() as signalled:
        return _main(argv, signalled=signalled)


if __name__ == "__main__":
    raise SystemExit(main())
