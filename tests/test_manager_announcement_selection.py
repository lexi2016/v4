"""Source binding and stock deduplication for announcement research decisions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from v4.manager_research.announcement_selection import (
    attach_extension,
    make_extension,
    read_projection,
)
from v4.manager_research.workspace_projection import digest


def _base() -> dict[str, Any]:
    manifest = {
        "target_trade_date": "20260930",
        "publication_date": "2026-09-29",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "catalog_run_id": "c" * 32,
        "catalog_product_sha256": "d" * 64,
        "semantic_catalog_sha256": "e" * 64,
        "body_corpus_sha256": "f" * 64,
    }
    records = [
        {"art_code": "AN000001", "title": "Event", "issuer_codes": [{"code": "HK.00001", "name": "One"}],
         "security_scope": "Issuer-level", "classification": "BUSINESS_EVENT", "analysis_kind": "COMPLETE_API_BODY",
         "factual_summary": "A disclosed event", "semantic_record_sha256": "1" * 64, "body_record_sha256": "2" * 64},
        {"art_code": "AN000002", "title": "Routine", "issuer_codes": [{"code": "HK.00001", "name": "One"}],
         "security_scope": "Issuer-level", "classification": "ROUTINE", "analysis_kind": "COMPLETE_API_BODY",
         "factual_summary": "Routine notice", "semantic_record_sha256": "3" * 64, "body_record_sha256": "4" * 64},
        {"art_code": "AN000003", "title": "Watch", "issuer_codes": [{"code": "HK.00002", "name": "Two"}],
         "security_scope": "A/H unspecified", "classification": "MIXED", "analysis_kind": "COMPLETE_API_BODY",
         "factual_summary": "Conditional transaction", "semantic_record_sha256": "5" * 64, "body_record_sha256": "6" * 64},
        {"art_code": "AN000004", "title": "Missing", "issuer_codes": [{"code": "HK.00003", "name": "Three"}],
         "security_scope": "Issuer-level", "classification": "UNASSESSED_MISSING_TEXT", "analysis_kind": "TEXT_INSUFFICIENT_UNASSESSED",
         "factual_summary": "CANNOT_CONFIRM", "semantic_record_sha256": "7" * 64, "body_record_sha256": "8" * 64},
        {"art_code": "AN000005", "title": "No evidence", "issuer_codes": [{"code": "HK.00004", "name": "Four"}],
         "security_scope": "Issuer-level", "classification": "CAPITAL_ACTION", "analysis_kind": "COMPLETE_API_BODY",
         "factual_summary": "Capital action", "semantic_record_sha256": "9" * 64, "body_record_sha256": "a" * 64},
    ]
    product: dict[str, Any] = {
        "schema_version": "test.analysis.v1", "status": "VERIFIED",
        "target_trade_date": "20260930", "publication_date": "2026-09-29",
        "source_manifest": manifest, "source_manifest_sha256": digest(manifest),
        "records": records,
    }
    product["sha256"] = digest(product)
    return product


def _decisions(product: dict[str, Any]) -> list[dict[str, Any]]:
    outcomes = {
        "AN000001": ("SELECTED_EVENT", "OPERATING_EVENT", "The event is disclosed.", ["Early-stage risk."]),
        "AN000002": ("NOT_SELECTED", "NOT_SELECTED", "Routine notice; no new operating evidence.", []),
        "AN000003": ("CONDITIONAL_WATCH", "CONDITIONAL_WATCH", "The transaction still has conditions.", ["Completion is unconfirmed."]),
        "AN000004": ("NOT_ASSESSED", "NOT_ASSESSED", "Text is insufficient; no inference is made.", []),
        "AN000005": ("NOT_SELECTED", "NOT_SELECTED", "Capital action alone does not establish operating improvement.", []),
    }
    out = []
    for record in product["records"]:
        disposition, basis, reason, risks = outcomes[record["art_code"]]
        out.append({
            "art_code": record["art_code"],
            "issuer_codes": [issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope": record["security_scope"],
            "semantic_record_sha256": record["semantic_record_sha256"],
            "body_record_sha256": record["body_record_sha256"],
            "disposition": disposition,
            "selection_basis": basis,
            "reason": reason,
            "risk_notes": risks,
        })
    return out


def test_extension_deduplicates_stocks_and_keeps_each_article_reason():
    base = _base()
    extension = make_extension(base, _decisions(base))
    product = attach_extension(base, extension)
    projection = read_projection(product)

    assert projection["status"] == "VERIFIED"
    assert projection["stock_count"] == 4
    assert projection["selected_stock_count"] == 1
    assert projection["conditional_watch_count"] == 1
    assert projection["not_selected_stock_count"] == 1
    assert projection["not_assessed_stock_count"] == 1
    one = next(stock for stock in projection["stocks"] if stock["stock_code"] == "HK.00001")
    assert one["status"] == "SELECTED"
    assert one["article_count"] == 2
    assert {row["disposition"] for row in one["articles"]} == {"SELECTED_EVENT", "NOT_SELECTED"}
    assert one["selection_reasons"][0]["art_code"] == "AN000001"
    assert one["not_selected_reasons"][0]["art_code"] == "AN000002"
    assert one["risk_notes"] == ["Early-stage risk."]


def test_missing_extension_is_not_assessed_not_zero_selected():
    projection = read_projection(_base())
    assert projection["status"] == "NOT_ASSESSED"
    assert projection["selected_stock_count"] is None
    assert projection["stock_count"] is None
    assert projection["stocks"] == []
    assert projection["gaps"] == ["ANNOUNCEMENT_SELECTION_NOT_ASSESSED"]


def test_wrong_issuer_binding_and_missing_article_decision_are_rejected():
    base = _base()
    decisions = _decisions(base)
    decisions[0]["issuer_codes"] = ["HK.99999"]
    with pytest.raises(ValueError, match="ARTICLE_BINDING_MISMATCH"):
        make_extension(base, decisions)

    with pytest.raises(ValueError, match="DECISION_COUNT_MISMATCH"):
        make_extension(base, _decisions(base)[:-1])


def test_wrong_semantic_or_body_sha_cannot_bind_decision():
    base = _base()
    decisions = _decisions(base)
    decisions[0]["body_record_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="ARTICLE_BINDING_MISMATCH"):
        make_extension(base, decisions)


def test_modified_source_record_invalidates_attached_extension():
    base = _base()
    product = attach_extension(base, make_extension(base, _decisions(base)))
    tampered = deepcopy(product)
    tampered["records"][0]["issuer_codes"][0]["code"] = "HK.99999"
    # Recompute only the outer digest so the article-to-stock binding is the
    # failing layer rather than the generic product digest.
    tampered["sha256"] = digest({key: value for key, value in tampered.items() if key != "sha256"})
    with pytest.raises(ValueError, match="BASE_PRODUCT_SHA_MISMATCH"):
        read_projection(tampered)


def test_hkex_source_variant_decisions_keep_the_official_id_without_art_code_join():
    manifest = {
        "target_trade_date": "20261012", "publication_date": "2026-10-12",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "catalog_run_id": "a" * 32,
        "catalog_product_sha256": "b" * 64, "semantic_catalog_sha256": "c" * 64,
        "body_corpus_sha256": "d" * 64, "hkex_directory_readback_sha256": "e" * 64,
        "monthly_connect_eligibility_identity_sha256": "f" * 64,
        "monthly_connect_source_date": "20261005",
        "additional_source_scopes": ["HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"],
    }
    base = {"schema_version": "test.analysis.v2", "status": "VERIFIED",
        "target_trade_date": "20261012", "publication_date": "2026-10-12",
        "source_manifest": manifest, "source_manifest_sha256": digest(manifest),
        "records": [{"source_variant_id": "HKEX:12345678", "title": "Official notice",
            "issuer_codes": [{"code": "HK.02665", "name": "Fixture Issuer"}],
            "security_scope": "Issuer-level", "classification": "BUSINESS_EVENT",
            "analysis_kind": "COMPLETE_HKEX_OFFICIAL_PDF_BODY", "factual_summary": "Reviewed fact",
            "semantic_record_sha256": "1" * 64, "body_record_sha256": "2" * 64}]}
    base["sha256"] = digest(base)
    decision = {"source_variant_id": "HKEX:12345678", "issuer_codes": ["HK.02665"],
        "security_scope": "Issuer-level", "semantic_record_sha256": "1" * 64,
        "body_record_sha256": "2" * 64, "disposition": "SELECTED_EVENT",
        "selection_basis": "OPERATING_EVENT", "reason": "Independent reviewed disposition.",
        "risk_notes": []}

    projection = read_projection(attach_extension(base, make_extension(base, [decision])))

    assert projection["selected_stock_count"] == 1
    article = projection["stocks"][0]["articles"][0]
    assert article["source_variant_id"] == "HKEX:12345678"
    assert "art_code" not in article
    assert projection["stocks"][0]["selection_reasons"][0]["source_variant_id"] == "HKEX:12345678"
    fake_join = dict(decision, art_code="AN202610120001")
    with pytest.raises(ValueError, match="DECISION_ARTICLE_MISMATCH"):
        make_extension(base, [fake_join])
