"""Verified, read-only projection of the pinned 2026-10-15 Flash run."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re
from typing import Any


PIPELINE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary"
)
CANDIDATE_ROOT = PIPELINE_ROOT / "evidence/announcement-full-day-20261015/candidate-20261015-full-04"
CANDIDATE_MANIFEST_SHA256 = "15de0845513f21cdadd98162a7720d8963bde3290b2839765d1794dce11bd121"
VALIDATED_BATCH_SHA256 = "31a477f09ef3ba9e5114ed7ba2d37640378369ef4153538488a5b63a5f42c23d"
QUEUE_ID = "recent-day-20261015-full-day-76e8763179830e975f11"
QUEUE_STATE_SHA256 = "f1aed8465d4a0d78be35c48b60a6addfbbb4dcd8ef99298ab2e7f0d63c54e318"
PRIOR_REUSE_SHA256 = "b2826e87cb395af2ec9dc782418d5e3aa9deb7944c35819de6aafef08e51a9bc"
PRIOR_CANDIDATE_ROOT = PIPELINE_ROOT / "evidence/announcement-screening-capability-20261016/capability-sample-v1/unseen-nonroutine-candidate-20261016-03"
PRIOR_CANDIDATE_MANIFEST_SHA256 = "3da874d0897f9c4344a7f9fe3684190da62a3de6a4c16d04e2edfca889639f51"
PRIOR_VALIDATED_BATCH_SHA256 = "116a88ab377d8aa3437aee9438e3048e93f44678333232857477984f8170ec7a"
PRIOR_REVIEW_SHA256 = "a21bb31476b1d7f7d4c140cbd235d1b83b65e619b5cbb3f86c65d56e46112253"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^HK\.[0-9]{5}$")
_SELECTED = {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}


class CandidateEvidenceError(ValueError):
    """The pinned candidate evidence is absent or no longer matches its receipt."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(root: Path, relative: str, expected_sha256: str | None = None) -> Any:
    path = root / relative
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CandidateEvidenceError("PINNED_EVIDENCE_UNAVAILABLE") from exc
    if expected_sha256 and _sha(raw) != expected_sha256:
        raise CandidateEvidenceError("PINNED_EVIDENCE_SHA_MISMATCH")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateEvidenceError("PINNED_EVIDENCE_INVALID_JSON") from exc


def _source_article(article_id: str, batch_articles: dict[str, dict]) -> dict:
    article = batch_articles.get(article_id)
    if not isinstance(article, dict):
        raise CandidateEvidenceError("ARTICLE_NOT_IN_VALIDATED_BATCH")
    meta = article.get("article_metadata")
    if not isinstance(meta, dict):
        raise CandidateEvidenceError("ARTICLE_METADATA_MISSING")
    return article


def _failure_code(job: dict) -> str:
    error = job.get("last_error")
    if not isinstance(error, dict):
        attempts = job.get("attempts")
        error = attempts[-1].get("error") if isinstance(attempts, list) and attempts else None
    code = error.get("code") if isinstance(error, dict) else None
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,96}", code):
        return "FAILURE_CODE_UNAVAILABLE"
    return code


def _candidate_article(article_id: str, article: dict, job: dict, output: dict) -> dict:
    meta = article["article_metadata"]
    symbol = meta.get("symbol")
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise CandidateEvidenceError("SELECTED_ARTICLE_SYMBOL_INVALID")
    if output.get("body_sha256") != job.get("identity", {}).get("body_sha256"):
        raise CandidateEvidenceError("SELECTED_ARTICLE_BODY_IDENTITY_MISMATCH")
    if output.get("source_sha256") != job.get("identity", {}).get("source_sha256"):
        raise CandidateEvidenceError("SELECTED_ARTICLE_SOURCE_IDENTITY_MISMATCH")
    reason = output.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise CandidateEvidenceError("SELECTED_ARTICLE_REASON_MISSING")
    origins = meta.get("source_origins")
    if not isinstance(origins, list) or len(origins) < 2:
        raise CandidateEvidenceError("SELECTED_ARTICLE_PROVENANCE_INCOMPLETE")
    return {
        "article_id": article_id,
        "title": meta.get("title") or "公告标题未知",
        "publication_date": meta.get("publication_date"),
        "symbol": symbol,
        "name": meta.get("issuer_name") or symbol,
        "disposition": output.get("disposition"),
        "direction": output.get("direction"),
        "selection_basis": output.get("selection_basis"),
        "reason": reason.strip(),
        "impact": [item.get("claim") for item in output.get("impact", [])
                   if isinstance(item, dict) and isinstance(item.get("claim"), str)],
        "body_sha256": job["identity"]["body_sha256"],
        "source_sha256": job["identity"]["source_sha256"],
        "source_origins": [
            {"role": origin.get("role"), "source_ref": origin.get("source_ref"),
             "source_product_sha256": origin.get("source_product_sha256"),
             "row_fingerprint_sha256": origin.get("row_fingerprint_sha256")}
            for origin in origins if isinstance(origin, dict)
        ],
        "review_status": "MODEL_CANDIDATE_UNREVIEWED",
        "reuse_status": None,
    }


def _aggregate_selected(selected_articles: list[dict]) -> list[dict]:
    stocks: dict[str, dict] = {}
    for article in selected_articles:
        row = stocks.setdefault(article["symbol"], {
            "symbol": article["symbol"], "name": article["name"], "reasons": [],
            "articles": [], "review_status": "MODEL_CANDIDATE_UNREVIEWED",
            "reuse_status": None,
        })
        reason = article["reason"]
        if not any(existing["article_id"] == article["article_id"] for existing in row["articles"]):
            row["articles"].append(article)
            row["reasons"].append(reason)
        if row["name"] in (None, "", row["symbol"]) and article["name"]:
            row["name"] = article["name"]
    return list(stocks.values())


def _prior_reused_candidate() -> dict:
    reuse = _read(CANDIDATE_ROOT, "prior-result-reuse.json", PRIOR_REUSE_SHA256)
    if (reuse.get("status") != "REUSED_PRIOR_VERIFIED_RESULT"
            or reuse.get("prior_independent_review") != "PASS_WITH_LIMITATION"
            or reuse.get("workflow_profile") != "decision_simple_facts_unit_ranges_v2"
            or reuse.get("model_id") != "qwen3_8_flash_next"):
        raise CandidateEvidenceError("PRIOR_RESULT_REUSE_RECEIPT_INVALID")
    prior_manifest = _read(PRIOR_CANDIDATE_ROOT, "candidate-manifest.json", PRIOR_CANDIDATE_MANIFEST_SHA256)
    _read(PRIOR_CANDIDATE_ROOT, "validated-batch.json", PRIOR_VALIDATED_BATCH_SHA256)
    review_root = PIPELINE_ROOT / "evidence/announcement-screening-capability-20261016"
    _read(review_root, "INDEPENDENT_REVIEW.json", PRIOR_REVIEW_SHA256)
    queue_rel = f"queue-state/{reuse['prior_queue_id']}/queue-state.json"
    queue = _read(PRIOR_CANDIDATE_ROOT, queue_rel)
    job = queue.get("jobs", {}).get(reuse.get("prior_idempotency_key"))
    if not isinstance(job, dict) or job.get("status") != "SUCCEEDED":
        raise CandidateEvidenceError("PRIOR_RESULT_JOB_NOT_SUCCEEDED")
    if job.get("validated_sha256") != reuse.get("prior_validated_sha256", job.get("validated_sha256")):
        raise CandidateEvidenceError("PRIOR_RESULT_VALIDATED_IDENTITY_MISMATCH")
    result = _read(PRIOR_CANDIDATE_ROOT / "queue-state" / reuse["prior_queue_id"], job["validated_path"], job["validated_sha256"])
    if not isinstance(result.get("results"), list) or len(result["results"]) != 1:
        raise CandidateEvidenceError("PRIOR_RESULT_SCHEMA_INVALID")
    output = result["results"][0].get("reader_output", {})
    if (result["results"][0].get("article_id") != reuse.get("article_id")
            or output.get("disposition") not in _SELECTED or output.get("direction") != "POSITIVE"
            or output.get("source_sha256") != reuse.get("source_sha256")
            or output.get("body_sha256") != reuse.get("body_sha256")):
        raise CandidateEvidenceError("PRIOR_RESULT_CONTENT_IDENTITY_MISMATCH")
    batch = _read(PRIOR_CANDIDATE_ROOT, "validated-batch.json", PRIOR_VALIDATED_BATCH_SHA256)
    article = next((a for a in batch.get("articles", []) if a.get("article_id") == reuse["article_id"]), None)
    if not isinstance(article, dict):
        raise CandidateEvidenceError("PRIOR_RESULT_ARTICLE_NOT_IN_BATCH")
    source = article.get("article_metadata", {})
    symbol = source.get("symbol")
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise CandidateEvidenceError("PRIOR_RESULT_SYMBOL_INVALID")
    if output.get("body_sha256") != article.get("body_sha256") or output.get("source_sha256") != article.get("source_sha256"):
        raise CandidateEvidenceError("PRIOR_RESULT_BATCH_IDENTITY_MISMATCH")
    return {
        "symbol": symbol, "name": source.get("issuer_name") or symbol,
        "reasons": [output["reason"]], "review_status": "PRIOR_INDEPENDENT_REVIEW_PASS_WITH_LIMITATION",
        "reuse_status": "REUSED_PRIOR_VERIFIED_RESULT", "articles": [{
            "article_id": reuse["article_id"], "title": source.get("title") or "公告标题未知",
            "publication_date": source.get("publication_date"), "symbol": symbol,
            "name": source.get("issuer_name") or symbol,
            "disposition": output.get("disposition"), "direction": output.get("direction"),
            "selection_basis": output.get("selection_basis"), "reason": output.get("reason"),
            "impact": [item.get("claim") for item in output.get("impact", []) if isinstance(item, dict)],
            "body_sha256": reuse["body_sha256"], "source_sha256": reuse["source_sha256"],
            "source_origins": source.get("source_origins", []),
            "review_status": "PRIOR_INDEPENDENT_REVIEW_PASS_WITH_LIMITATION",
            "reuse_status": "REUSED_PRIOR_VERIFIED_RESULT",
        }],
    }


@lru_cache(maxsize=1)
def _load_pinned_candidates() -> dict[str, Any]:
    """Verify fixed receipts and project only model-positive research candidates."""
    manifest = _read(CANDIDATE_ROOT, "candidate-manifest.json", CANDIDATE_MANIFEST_SHA256)
    sidecar = (CANDIDATE_ROOT / "candidate-manifest.sha256").read_text(encoding="ascii").strip().split()
    if not sidecar or sidecar[0] != CANDIDATE_MANIFEST_SHA256:
        raise CandidateEvidenceError("CANDIDATE_MANIFEST_SIDECAR_MISMATCH")
    if manifest.get("candidate_id") != "76e8763179830e975f11":
        raise CandidateEvidenceError("CANDIDATE_MANIFEST_ID_MISMATCH")
    batch = _read(CANDIDATE_ROOT, "validated-batch.json", VALIDATED_BATCH_SHA256)
    queue_rel = f"queue-state/{QUEUE_ID}/queue-state.json"
    queue = _read(CANDIDATE_ROOT, queue_rel, QUEUE_STATE_SHA256)
    articles = batch.get("articles")
    jobs = queue.get("jobs")
    if not isinstance(articles, list) or not isinstance(jobs, dict):
        raise CandidateEvidenceError("CANDIDATE_QUEUE_SCHEMA_INVALID")
    batch_articles = {item.get("article_id"): item for item in articles if isinstance(item, dict)}
    selected_articles: list[dict] = []
    failures: list[dict] = []
    pending: list[dict] = []
    status_counts = Counter()
    article_manifest = {item.get("article_id"): item for item in manifest.get("articles", []) if isinstance(item, dict)}
    for key, job in jobs.items():
        if not isinstance(job, dict):
            raise CandidateEvidenceError("CANDIDATE_JOB_SCHEMA_INVALID")
        status = job.get("status")
        status_counts[status] += 1
        identity = job.get("identity", {})
        article_id = identity.get("article_id")
        if status == "SUCCEEDED":
            if not _HASH.fullmatch(str(job.get("validated_sha256", ""))) or not isinstance(job.get("validated_path"), str):
                raise CandidateEvidenceError("VALIDATED_RESULT_REFERENCE_INVALID")
            result = _read(CANDIDATE_ROOT / "queue-state" / QUEUE_ID, job["validated_path"], job["validated_sha256"])
            results = result.get("results")
            if not isinstance(results, list) or len(results) != 1 or results[0].get("article_id") != article_id:
                raise CandidateEvidenceError("VALIDATED_RESULT_ARTICLE_MISMATCH")
            output = results[0].get("reader_output")
            if not isinstance(output, dict):
                raise CandidateEvidenceError("VALIDATED_READER_OUTPUT_MISSING")
            if output.get("source_sha256") != identity.get("source_sha256") or output.get("body_sha256") != identity.get("body_sha256"):
                raise CandidateEvidenceError("VALIDATED_RESULT_SOURCE_IDENTITY_MISMATCH")
            if output.get("disposition") in _SELECTED and output.get("direction") == "POSITIVE":
                article = _source_article(article_id, batch_articles)
                selected_articles.append(_candidate_article(article_id, article, job, output))
        elif status == "FAILED":
            article = _source_article(article_id, batch_articles)
            meta = article["article_metadata"]
            failures.append({"article_id": article_id, "symbol": meta.get("symbol"), "title": meta.get("title"),
                             "failure_code": _failure_code(job), "attempt_count": job.get("attempt_count")})
        elif status == "PENDING":
            article = _source_article(article_id, batch_articles)
            meta = article["article_metadata"]
            preflight = article_manifest.get(article_id, {})
            pending.append({"article_id": article_id, "symbol": meta.get("symbol"), "title": meta.get("title"),
                            "queue_status": "PENDING", "queue_reason": "STOPPED_AFTER_SYSTEM_FAILURE",
                            "context_admission": preflight.get("context_admission"),
                            "execution_admission": preflight.get("execution_admission")})
        else:
            raise CandidateEvidenceError("CANDIDATE_QUEUE_STATUS_UNKNOWN")

    stock_map = {stock["symbol"]: stock for stock in _aggregate_selected(selected_articles)}
    reused = _prior_reused_candidate()
    prior_stock = stock_map.get(reused["symbol"])
    if prior_stock:
        prior_stock["reasons"].extend(reused["reasons"])
        prior_stock["articles"].extend(reused["articles"])
        prior_stock["reuse_status"] = reused["reuse_status"]
        prior_stock["review_status"] = "MIXED_MODEL_CANDIDATE_AND_PRIOR_REVIEWED"
    else:
        stock_map[reused["symbol"]] = reused

    # The pre-existing receipt records one excluded body gap; the known source reason
    # is retained alongside the explicit page-cap boundary for operators.
    source_population = manifest.get("source_population", {})
    gap_codes = source_population.get("gap_code_counts", {})
    if source_population.get("body_gap_count") != 1 or gap_codes != {"CAPTURE_TRANSPORT_NOT_BOUND": 1}:
        raise CandidateEvidenceError("CANDIDATE_BODY_GAP_RECEIPT_CHANGED")
    counts = manifest.get("counts", {})
    if (status_counts != Counter({"SUCCEEDED": 367, "FAILED": 18, "PENDING": 5})
            or len(selected_articles) != 21 or len(stock_map) != 20
            or counts.get("source_catalogue_articles") != 392
            or counts.get("body_gap_articles_excluded") != 1):
        raise CandidateEvidenceError("CANDIDATE_POPULATION_COUNTS_CHANGED")
    system_stop = _read(CANDIDATE_ROOT, "system-failure-stop.json")
    stop_error = system_stop.get("error", {})
    stop_code = stop_error.get("code") if isinstance(stop_error, dict) else None
    if stop_code != "prefill_memory_exceeded" or system_stop.get("queue_id") != QUEUE_ID:
        raise CandidateEvidenceError("SYSTEM_FAILURE_STOP_RECEIPT_INVALID")
    return {
        "state": "PARTIAL",
        "source_date": manifest.get("source_window", {}).get("source_date") or "2026-10-15",
        "target_trade_date": "CANNOT_CONFIRM",
        "updated_at": manifest.get("created_at_utc"),
        "candidate_id": manifest.get("candidate_id"),
        "model_id": "qwen3_8_flash_next",
        "profile": "decision_simple_facts_unit_ranges_v2",
        "citation_protocol": "source_unit_contiguous_ranges_v2",
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
        "review_status": "MODEL_CANDIDATE_UNREVIEWED",
        "counts": {
            "source_catalogue_articles": 392,
            "model_succeeded": status_counts["SUCCEEDED"],
            "selected_model_articles": len(selected_articles),
            "model_candidate_stocks": len(stock_map) - 1,
            "reused_reviewed_stocks": 1,
            "failed": status_counts["FAILED"],
            "pending": status_counts["PENDING"],
            "body_gaps": 1,
            "displayed_stocks": len(stock_map),
        },
        "stocks": list(stock_map.values()),
        "failures": failures,
        "pending": pending,
        "gaps": [{"code": "CAPTURE_TRANSPORT_NOT_BOUND", "count": 1,
                  "detail": "1条公告正文有缺口；记录为158页，超过现有单篇150页采集上限。"}],
        "system_stop": {"failure_code": "PREFILL_MEMORY_EXCEEDED", "attempt": system_stop.get("attempt"),
                        "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"},
        "provenance": {
            "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
            "validated_batch_sha256": VALIDATED_BATCH_SHA256,
            "queue_state_sha256": QUEUE_STATE_SHA256,
            "prior_reuse_receipt_sha256": PRIOR_REUSE_SHA256,
            "prior_independent_review_sha256": PRIOR_REVIEW_SHA256,
        },
    }


def read_pinned_candidates() -> dict[str, Any]:
    """Return a detached copy so API projections cannot alter the verified base."""
    return deepcopy(_load_pinned_candidates())
