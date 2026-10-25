"""Pure, per-job display projection of already verified delivery/semantic inputs.

The existing semantic verifier owns receipt validation. This module neither
reads evidence nor turns mechanical success or resume eligibility into approval.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = ("article_id", "source_sha256", "body_sha256", "queue_key", "result_sha256", "symbol")


def validate_delivery_structure(delivery: Mapping[str, Any]) -> None:
    """Reject malformed containers before any nested article/source access."""
    articles = delivery.get("articles")
    if not isinstance(articles, list) or any(not isinstance(a, dict) for a in articles):
        raise ValueError("DELIVERY_ARTICLES_INVALID")
    stocks = delivery.get("stocks")
    if not isinstance(stocks, list):
        raise ValueError("DELIVERY_STOCK_ARTICLES_INVALID")
    for stock in stocks:
        if (not isinstance(stock, dict) or not isinstance(stock.get("articles"), list)
                or not stock["articles"] or any(not isinstance(a, dict) for a in stock["articles"])):
            raise ValueError("DELIVERY_STOCK_ARTICLES_INVALID")


def semantic_project_stocks(stocks, quarantined):
    """Apply the original exact queue/result quarantine before merging stocks."""
    blocked = {(e["queue_key"], e["result_sha256"]) for e in quarantined}
    projected = []
    for stock in stocks:
        articles = stock.get("articles", [])
        kept = [a for a in articles if (a.get("queue_key"), a.get("result_sha256")) not in blocked]
        if len(kept) == len(articles):
            projected.append(deepcopy(stock))
        elif kept:
            projected.append({**deepcopy(stock), "articles": deepcopy(kept),
                              "reasons": [a["reason"] for a in kept]})
    return projected


def project_delivery_contribution(delivery: Mapping[str, Any],
                                  semantic_review: Mapping[str, Any]) -> dict[str, Any]:
    """Return legal stocks separately from unreviewed diagnostics and conflicts.

    A valid receipt is represented only by the original verifier's bound
    snapshot. Optional missing fields never inherit authentication from delivery.
    """
    raw = json.dumps(dict(delivery), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    delivery_sha = hashlib.sha256(raw).hexdigest()
    result = {"job_id": delivery.get("job_id"), "target_trade_date": delivery.get("target_trade_date"),
              "delivery_sha256": delivery_sha,
              "report_sha256": delivery.get("preprocessing_report_sha256"),
              "capture_product": deepcopy(delivery.get("capture_product")),
              "semantic_review_sha256": semantic_review.get("semantic_review_sha256"),
              "availability": "ISOLATED", "stocks": [], "diagnostic_stocks": []}
    try:
        validate_delivery_structure(delivery)
        if (delivery.get("schema") != "v4.manager_workbench.announcement_delivery.v1"
                or not re.fullmatch(r"[0-9a-f]{32}", str(result["job_id"]))
                or not _SHA.fullmatch(str(result["report_sha256"]))
                or not isinstance(delivery.get("articles"), list)
                or not isinstance(delivery.get("stocks"), list)):
            raise ValueError("DELIVERY_CONTRIBUTION_IDENTITY_INVALID")
        expected = {"job_id": result["job_id"], "target_date": result["target_trade_date"],
                    "report_sha256": result["report_sha256"], "delivery_sha256": delivery_sha}
        if any(key in semantic_review and semantic_review[key] != value for key, value in expected.items()):
            raise ValueError("SEMANTIC_CONTRIBUTION_BINDING_CHANGED")
        entries = {tuple(a.get(key) for key in _IDENTITY): a for a in delivery["articles"]
                   if isinstance(a, dict)}
        for stock in delivery["stocks"]:
            for article in stock["articles"]:
                entry = entries.get(tuple(article.get(key) for key in _IDENTITY))
                if (entry is None or entry.get("state") != "SUCCEEDED"
                        or entry.get("source_coverage") not in {"COMPLETE_ARTICLE", "COMPLETE_SYNTHESIS"}
                        or entry.get("disposition") not in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                        or entry.get("direction") != "POSITIVE" or article.get("symbol") != stock.get("symbol")
                        or any(not _SHA.fullmatch(str(article.get(key, "")))
                               for key in ("source_sha256", "body_sha256", "queue_key", "result_sha256"))
                        or article.get("reason") != entry.get("reason")):
                    raise ValueError("DELIVERY_ARTICLE_SOURCE_BINDING_CHANGED")
        quarantined = semantic_review.get("quarantined_results", [])
        if (not isinstance(quarantined, list) or any(not isinstance(a, dict)
                or any(not _SHA.fullmatch(str(a.get(key, ""))) for key in ("queue_key", "result_sha256"))
                for a in quarantined)):
            raise ValueError("SEMANTIC_QUARANTINE_INVALID")
        stocks = semantic_project_stocks(delivery["stocks"], quarantined)
        # Always derive reasons from the remaining contribution articles. A
        # rejected reason must not survive in a stock-level cached reason list.
        for stock in stocks:
            stock["reasons"] = [a["reason"] for a in stock["articles"]]
        result["quarantined_results"] = deepcopy(quarantined)
        bound = all(semantic_review.get(key) == value for key, value in expected.items())
        reviewed = (bound and semantic_review.get("checkpoint_state") == "SUCCEEDED"
                    and _SHA.fullmatch(str(semantic_review.get("semantic_review_sha256", ""))))
        if reviewed:
            result.update(availability="AVAILABLE", stocks=stocks)
        else:
            for stock in stocks:
                stock["review_status"] = "MODEL_CANDIDATE_UNREVIEWED"
                for article in stock["articles"]:
                    article["review_status"] = "MODEL_CANDIDATE_UNREVIEWED"
            result.update(availability="UNREVIEWED", diagnostic_stocks=stocks,
                          reason=semantic_review.get("reason") or "SEMANTIC_REVIEW_NOT_VERIFIED")
    except (ValueError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
    return result
