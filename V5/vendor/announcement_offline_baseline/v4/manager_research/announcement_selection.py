"""Validate and project explicit, source-bound announcement research decisions.

This module does not infer selection from announcement text, dates, codes, or
the original semantic classification. A separately authored article decision
block is bound to the exact reviewed analysis records and then deduplicated by
issuer code for display.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .workspace_projection import digest

SCHEMA = "v4.manager_research.announcement_stock_selection.v1"
READ_SCHEMA = "v4.manager_research.announcement_stock_selection_read.v1"
DISPOSITIONS = {
    "SELECTED_EVENT",
    "SELECTED_PERFORMANCE",
    "CONDITIONAL_WATCH",
    "NOT_SELECTED",
    "NOT_ASSESSED",
}
SELECTED = {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}


def _issuer_codes(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("issuer_codes")
    if not isinstance(raw, list) or not raw:
        raise ValueError("ANNOUNCEMENT_SELECTION_ISSUER_CODES_INVALID")
    result: list[str] = []
    for issuer in raw:
        if not isinstance(issuer, Mapping):
            raise ValueError("ANNOUNCEMENT_SELECTION_ISSUER_CODES_INVALID")
        code = issuer.get("code")
        if not isinstance(code, str) or not code or code in result:
            raise ValueError("ANNOUNCEMENT_SELECTION_ISSUER_CODES_INVALID")
        result.append(code)
    return result


def _text_list(value: Any, error: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(error)
    return value


def _binding_from_product(product: Mapping[str, Any]) -> dict[str, Any]:
    manifest = product.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_MANIFEST_MISSING")
    keys = (
        "target_trade_date", "publication_date", "source_scope", "catalog_run_id",
        "catalog_product_sha256", "semantic_catalog_sha256", "body_corpus_sha256",
    )
    binding = {key: manifest.get(key) for key in keys}
    if any(not isinstance(value, str) or not value for value in binding.values()):
        raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_BINDING_INVALID")
    return binding


def make_extension(base_product: Mapping[str, Any],
                   article_decisions: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Bind explicit decisions to every existing analysis record.

    ``article_decisions`` must contain one fully specified outcome per source
    article. This function validates and copies decisions; it never chooses an
    outcome or fills missing decisions.
    """
    if "stock_selection" in base_product:
        raise ValueError("ANNOUNCEMENT_SELECTION_BASE_ALREADY_EXTENDED")
    base_sha = base_product.get("sha256")
    without_sha = {key: value for key, value in base_product.items() if key != "sha256"}
    if not isinstance(base_sha, str) or base_sha != digest(without_sha):
        raise ValueError("ANNOUNCEMENT_SELECTION_BASE_PRODUCT_SHA_MISMATCH")
    records = base_product.get("records")
    if not isinstance(records, list):
        raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_RECORDS_MISSING")
    record_by_code: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("art_code"), str):
            raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_RECORD_INVALID")
        if record["art_code"] in record_by_code:
            raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_RECORD_DUPLICATE")
        record_by_code[record["art_code"]] = record
    if not isinstance(article_decisions, list) or len(article_decisions) != len(record_by_code):
        raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_COUNT_MISMATCH")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in article_decisions:
        if not isinstance(raw, Mapping):
            raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_INVALID")
        art_code = raw.get("art_code")
        if not isinstance(art_code, str) or art_code in seen or art_code not in record_by_code:
            raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_ARTICLE_MISMATCH")
        record = record_by_code[art_code]
        disposition = raw.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError("ANNOUNCEMENT_SELECTION_DISPOSITION_INVALID")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("ANNOUNCEMENT_SELECTION_REASON_MISSING")
        record_codes = _issuer_codes(record)
        if (raw.get("issuer_codes") != record_codes
                or raw.get("security_scope") != record.get("security_scope")
                or raw.get("semantic_record_sha256") != record.get("semantic_record_sha256")
                or raw.get("body_record_sha256") != record.get("body_record_sha256")):
            raise ValueError("ANNOUNCEMENT_SELECTION_ARTICLE_BINDING_MISMATCH")
        risks = _text_list(raw.get("risk_notes"), "ANNOUNCEMENT_SELECTION_RISK_NOTES_INVALID")
        if disposition in SELECTED and not raw.get("selection_basis") in {"OPERATING_EVENT", "PERFORMANCE_RESEARCH"}:
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition == "SELECTED_EVENT" and raw.get("selection_basis") != "OPERATING_EVENT":
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition == "SELECTED_PERFORMANCE" and raw.get("selection_basis") != "PERFORMANCE_RESEARCH":
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        if disposition not in SELECTED and raw.get("selection_basis") not in {
            "CONDITIONAL_WATCH", "NOT_SELECTED", "NOT_ASSESSED",
        }:
            raise ValueError("ANNOUNCEMENT_SELECTION_BASIS_INVALID")
        normalized.append({
            "art_code": art_code,
            "issuer_codes": record_codes,
            "security_scope": record.get("security_scope"),
            "semantic_record_sha256": record.get("semantic_record_sha256"),
            "body_record_sha256": record.get("body_record_sha256"),
            "disposition": disposition,
            "selection_basis": raw.get("selection_basis"),
            "reason": reason.strip(),
            "risk_notes": risks,
        })
        seen.add(art_code)
    if seen != set(record_by_code):
        raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_ARTICLE_SET_MISMATCH")
    normalized.sort(key=lambda row: row["art_code"])
    binding = _binding_from_product(base_product)
    source_manifest_sha = base_product.get("source_manifest_sha256")
    if not isinstance(source_manifest_sha, str):
        raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_MANIFEST_SHA_MISSING")
    extension: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "VERIFIED",
        "decision_unit": "ISSUER_CODE",
        "judgment_method": "EXPLICIT_ARTICLE_LEVEL_RESEARCH_DISPOSITION",
        "base_product_sha256": base_sha,
        "source_manifest_sha256": source_manifest_sha,
        "source_binding": binding,
        "article_count": len(normalized),
        "article_decisions": normalized,
    }
    extension["sha256"] = digest(extension)
    return extension


def attach_extension(base_product: Mapping[str, Any],
                     extension: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new candidate product with the decision extension attached."""
    if "stock_selection" in base_product:
        raise ValueError("ANNOUNCEMENT_SELECTION_BASE_ALREADY_EXTENDED")
    product = deepcopy(dict(base_product))
    product.pop("sha256", None)
    product["stock_selection"] = deepcopy(dict(extension))
    product["sha256"] = digest(product)
    return product


def _validate_extension(product: Mapping[str, Any]) -> Mapping[str, Any] | None:
    extension = product.get("stock_selection")
    if extension is None:
        return None
    if not isinstance(extension, Mapping):
        raise ValueError("ANNOUNCEMENT_SELECTION_EXTENSION_INVALID")
    if (extension.get("schema_version") != SCHEMA or extension.get("status") != "VERIFIED"
            or extension.get("decision_unit") != "ISSUER_CODE"):
        raise ValueError("ANNOUNCEMENT_SELECTION_EXTENSION_IDENTITY_INVALID")
    without_extension_sha = {key: value for key, value in extension.items() if key != "sha256"}
    if extension.get("sha256") != digest(without_extension_sha):
        raise ValueError("ANNOUNCEMENT_SELECTION_EXTENSION_SHA_MISMATCH")
    base = {key: value for key, value in product.items()
            if key not in {"sha256", "stock_selection"}}
    if extension.get("base_product_sha256") != digest(base):
        raise ValueError("ANNOUNCEMENT_SELECTION_BASE_PRODUCT_SHA_MISMATCH")
    if (extension.get("source_manifest_sha256") != product.get("source_manifest_sha256")
            or extension.get("source_binding") != _binding_from_product(product)):
        raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_BINDING_MISMATCH")
    records = product.get("records")
    decisions = extension.get("article_decisions")
    if (not isinstance(records, list) or not isinstance(decisions, list)
            or extension.get("article_count") != len(records)
            or len(decisions) != len(records)):
        raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_COUNT_MISMATCH")
    record_by_code: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("art_code"), str):
            raise ValueError("ANNOUNCEMENT_SELECTION_SOURCE_RECORD_INVALID")
        record_by_code[record["art_code"]] = record
    seen: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_INVALID")
        art_code = decision.get("art_code")
        record = record_by_code.get(art_code) if isinstance(art_code, str) else None
        if record is None or art_code in seen:
            raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_ARTICLE_MISMATCH")
        if (decision.get("issuer_codes") != _issuer_codes(record)
                or decision.get("security_scope") != record.get("security_scope")
                or decision.get("semantic_record_sha256") != record.get("semantic_record_sha256")
                or decision.get("body_record_sha256") != record.get("body_record_sha256")):
            raise ValueError("ANNOUNCEMENT_SELECTION_ARTICLE_BINDING_MISMATCH")
        disposition = decision.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError("ANNOUNCEMENT_SELECTION_DISPOSITION_INVALID")
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise ValueError("ANNOUNCEMENT_SELECTION_REASON_MISSING")
        _text_list(decision.get("risk_notes"), "ANNOUNCEMENT_SELECTION_RISK_NOTES_INVALID")
        seen.add(art_code)
    if seen != set(record_by_code):
        raise ValueError("ANNOUNCEMENT_SELECTION_DECISION_ARTICLE_SET_MISMATCH")
    return extension


def _stock_projection(records: list[Mapping[str, Any]],
                      decisions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    decisions_by_article = {row["art_code"]: row for row in decisions}
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        decision = decisions_by_article[record["art_code"]]
        disposition = decision["disposition"]
        for issuer in record["issuer_codes"]:
            code = issuer["code"]
            group = groups.setdefault(code, {
                "stock_code": code, "stock_name": issuer.get("name"), "articles": [],
                "selection_reasons": [], "risk_notes": [], "not_selected_reasons": [],
            })
            if group.get("stock_name") != issuer.get("name"):
                raise ValueError("ANNOUNCEMENT_SELECTION_ISSUER_NAME_CONFLICT")
            article = {
                "art_code": record["art_code"],
                "title": record.get("title"),
                "analysis_kind": record.get("analysis_kind"),
                "classification": record.get("classification"),
                "security_scope": record.get("security_scope"),
                "disposition": disposition,
                "reason": decision["reason"],
                "factual_summary": record.get("factual_summary"),
                "risk_notes": deepcopy(decision["risk_notes"]),
                "source_sha256": record.get("semantic_record_sha256"),
            }
            group["articles"].append(article)
            if disposition in SELECTED or disposition == "CONDITIONAL_WATCH":
                group["selection_reasons"].append({
                    "art_code": record["art_code"], "title": record.get("title"),
                    "disposition": disposition, "reason": decision["reason"],
                    "factual_summary": record.get("factual_summary"),
                })
            if disposition == "NOT_SELECTED":
                group["not_selected_reasons"].append({
                    "art_code": record["art_code"], "title": record.get("title"),
                    "reason": decision["reason"],
                })
            group["risk_notes"].extend(decision["risk_notes"])
    for group in groups.values():
        dispositions = {row["disposition"] for row in group["articles"]}
        if dispositions & SELECTED:
            status = "SELECTED"
        elif "CONDITIONAL_WATCH" in dispositions:
            status = "CONDITIONAL_WATCH"
        elif "NOT_ASSESSED" in dispositions:
            status = "NOT_ASSESSED"
        else:
            status = "NOT_SELECTED"
        group["status"] = status
        group["article_count"] = len(group["articles"])
        group["risk_notes"] = list(dict.fromkeys(group["risk_notes"]))
        group["articles"].sort(key=lambda row: row["art_code"])
    return sorted(groups.values(), key=lambda row: row["stock_code"])


def read_projection(product: Mapping[str, Any]) -> dict[str, Any]:
    """Return stock-level display data; old products remain explicitly unknown."""
    extension = _validate_extension(product)
    if extension is None:
        return {
            "schema_version": READ_SCHEMA,
            "status": "NOT_ASSESSED",
            "decision_unit": "ISSUER_CODE",
            "stock_count": None,
            "selected_stock_count": None,
            "conditional_watch_count": None,
            "not_selected_stock_count": None,
            "not_assessed_stock_count": None,
            "stocks": [],
            "article_decisions": [],
            "gaps": ["ANNOUNCEMENT_SELECTION_NOT_ASSESSED"],
        }
    records = product["records"]
    decisions = extension["article_decisions"]
    stocks = _stock_projection(records, decisions)
    counts = {
        "selected_stock_count": sum(row["status"] == "SELECTED" for row in stocks),
        "conditional_watch_count": sum(row["status"] == "CONDITIONAL_WATCH" for row in stocks),
        "not_selected_stock_count": sum(row["status"] == "NOT_SELECTED" for row in stocks),
        "not_assessed_stock_count": sum(row["status"] == "NOT_ASSESSED" for row in stocks),
    }
    return {
        "schema_version": READ_SCHEMA,
        "status": "VERIFIED",
        "decision_unit": "ISSUER_CODE",
        "stock_count": len(stocks),
        "article_count": len(decisions),
        **counts,
        "source_binding": deepcopy(extension["source_binding"]),
        "source_manifest_sha256": extension["source_manifest_sha256"],
        "base_product_sha256": extension["base_product_sha256"],
        "product_sha256": product.get("sha256"),
        "selection_sha256": extension.get("sha256"),
        "judgment_method": extension.get("judgment_method"),
        "stocks": stocks,
        "article_decisions": deepcopy(decisions),
        "gaps": [],
    }
