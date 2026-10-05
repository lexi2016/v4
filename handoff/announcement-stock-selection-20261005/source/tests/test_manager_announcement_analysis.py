"""Read-only and provenance checks for the reviewed HK announcement projection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research import announcement_analysis as analysis
from v4.manager_research import announcement_selection as selection


TARGET = "20260930"
PUBLICATION = "2026-09-29"


def _ref(url: str, suffix: int) -> dict[str, Any]:
    sha = f"{suffix:064x}"
    return {"request": {"url": url}, "blob_sha256": sha,
            "body_sha256": sha, "retrieved_at": "2026-10-05T00:00:00+00:00"}


def _fixtures() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    listings=[];semantic_rows=[];body_rows=[];derivative_shas={}
    codes=[f"AN20260929{index:010d}" for index in range(234)]
    for index,code in enumerate(codes):
        title=f"Reviewed notice {index}"
        listing_ref=_ref("https://np-anotice-stock.eastmoney.com/api/security/ann?page_index=1",index+1)
        listings.append({"art_code":code,"title":title,"page_index":1,"item_index":index,
            "notice_date":f"{PUBLICATION} 00:00:00","display_time":f"{PUBLICATION} 09:00:00:000",
            "raw_body_sha256":f"{index+1:064x}","source_ref":listing_ref})
        body_ref=_ref(f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={code}&page_index=1",index+1000)
        body={"art_code":code,"title":title,"content_page_count":1,
            "pages":[{"page_index":1,"text_sha256":f"{index+2000:064x}","source_ref":body_ref}]}
        record={"art_code":code,"title":title,"classification":"BUSINESS_EVENT",
            "classification_as_authored":"研究事件","security_scope":"测试样本",
            "factual_summary":f"Reviewed factual summary {index}","why_useful":"RESEARCH_CONTEXT",
            "issuer_codes":[{"code":f"HK.{index%140+1:05d}","name":"Issuer"}],
            "date_semantics":{"first_publication_timestamp":None,"available_at_for_target_cutoff":None},
            "cutoff_boundary":"CANNOT_CONFIRM","evidence":{"exact_excerpt":f"Exact quote {index}"}}
        if index < 207:
            body.update(body_status="COMPLETE_CONTENT_API_BODY",pdf_status="PDF_REF_MISSING")
        elif index < 229:
            sha=f"{index+1:064x}"
            derivative_shas[code]=sha
            record.update(pdf_physical_pages_reviewed=[2],quote_pdf_page=2,
                pdf_derivative={"derivative_sha256":sha,"full_text_sha256":f"{index+3000:064x}",
                    "page_count":5,"derivative_status":"PASS_LOCAL_FULL_PHYSICAL_PAGE_COVERAGE"})
            body.update(body_status="OVER_CONTENT_PAGE_LIMIT",pdf_status="VALID_PDF_BYTES",
                attachment_url=f"https://pdf.dfcfw.com/pdf/{code}.pdf")
        else:
            body.update(body_status="OVER_CONTENT_PAGE_LIMIT",pdf_status="CAPTURE_FAILED")
        semantic_rows.append(record);body_rows.append(body)
    catalog={"target_trade_date":TARGET,"publication_date":PUBLICATION,
        "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"COMPLETE",
        "hkex_first_publication_verified":False,"captured_row_count":744,
        "captured_page_count":39,"expected_data_page_count":38,"terminal_empty_seen":True,
        "manager_consumer_row_count":234,"manager_matched_master_codes":[f"HK.{i:05d}" for i in range(1,141)],
        "run_id":"a"*32,"sha256":"b"*64,"manager_consumer_rows":listings}
    catalog_read={"schema_version":"v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date":TARGET,"publication_date":PUBLICATION,"source_scope":"EASTMONEY_HK_DATE_CATALOG",
        "status":"COMPLETE","readback_status":"VERIFIED","catalog":catalog,"gaps":[]}
    semantic={"schema":"v4.announcement-semantic-catalog.v2",
        "status":"PASS_234_UNIQUE_ANNOUNCEMENTS_WITH_SOURCE_BOUND_READS_AND_EXPLICIT_GAPS",
        "target_notice_date":PUBLICATION,"target_research_date":"2026-09-30","row_count":234,
        "records":semantic_rows}
    body_corpus={"schema":"v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date":PUBLICATION,"article_count":234,"rows":body_rows}
    return semantic,body_corpus,catalog_read,derivative_shas


def _input_descriptors() -> list[dict[str, Any]]:
    return [{"name":name,"sha256":value["sha256"],"row_count":value["row_count"]}
            for name,value in analysis.EXPECTED_INPUTS.items()]


def _product() -> tuple[dict[str, Any], dict[str, Any]]:
    semantic,body,catalog_read,derivative_shas=_fixtures()
    product=analysis.build_product(semantic,body,catalog_read,
        semantic_sha256=analysis.EXPECTED_SEMANTIC_SHA256,
        body_sha256=analysis.EXPECTED_BODY_SHA256,
        verified_inputs=_input_descriptors(),pdf_derivative_sha256s=derivative_shas)
    return product,catalog_read["catalog"]


class _Store:
    def __init__(self,root:Path):self.root=root
    def _read(self,path:Path):
        if not path.exists():return None
        value=json.loads(path.read_bytes())
        if not isinstance(value,dict):raise ValueError("fixture expected object")
        return value


class _Service:
    def __init__(self,root:Path,catalog_read:dict[str,Any]):
        self.store=_Store(root);self.catalog_read=catalog_read
    def get_announcement_date_catalog(self,target:str,publication:str):
        if target==TARGET and publication==PUBLICATION:return self.catalog_read
        return {"schema_version":"v4.manager_research.eastmoney_hk_date_catalog_read.v1",
            "target_trade_date":target,"publication_date":publication,
            "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"NOT_RUN",
            "readback_status":"NOT_RUN","catalog":None,"gaps":["ANNOUNCEMENT_DATE_CATALOG_NOT_RUN"]}
    def get_announcement_analysis(self,target:str,publication:str|None=None):
        return analysis.read(self,target,publication)


def _client(service:_Service)->TestClient:
    app=FastAPI();app.include_router(create_manager_research_router(service));return TestClient(app)


def _write_product(service:_Service,product:dict[str,Any])->Path:
    path=analysis.product_path(service.store,TARGET,PUBLICATION);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(product,ensure_ascii=False))
    return path


def test_build_binds_all_234_rows_and_source_citations():
    product,catalog=_product()
    checked=analysis.validate_product(product,target_trade_date=TARGET,
        publication_date=PUBLICATION,catalog=catalog)
    assert len(checked["records"])==234
    assert {kind:sum(row["analysis_kind"]==kind for row in checked["records"])
        for kind in ("COMPLETE_API_BODY","LONG_PDF_KEY_SECTION_READ","TEXT_INSUFFICIENT_UNASSESSED")}=={
            "COMPLETE_API_BODY":207,"LONG_PDF_KEY_SECTION_READ":22,"TEXT_INSUFFICIENT_UNASSESSED":5}
    assert all(row["listing_source"]["source_ref"]["url"].startswith("https://np-anotice-stock.eastmoney.com/")
        for row in checked["records"])
    assert all(row["body_page_citations"] for row in checked["records"][:229])
    assert checked["source_manifest"]["point_in_time_status"]=="CANNOT_CONFIRM"
    assert checked["RESEARCH_ONLY"] is True and checked["production_allowed"] is False


def test_import_rejects_wrong_source_sha_and_wrong_input_set():
    semantic,body,catalog_read,derivative_shas=_fixtures()
    with pytest.raises(ValueError,match="SOURCE_SHA_MISMATCH"):
        analysis.build_product(semantic,body,catalog_read,semantic_sha256="0"*64,
            body_sha256=analysis.EXPECTED_BODY_SHA256,verified_inputs=_input_descriptors(),
            pdf_derivative_sha256s=derivative_shas)
    descriptors=_input_descriptors()[:-1]
    with pytest.raises(ValueError,match="INPUT_SET_MISMATCH"):
        analysis.build_product(semantic,body,catalog_read,
            semantic_sha256=analysis.EXPECTED_SEMANTIC_SHA256,
            body_sha256=analysis.EXPECTED_BODY_SHA256,verified_inputs=descriptors,
            pdf_derivative_sha256s=derivative_shas)


def test_product_cannot_be_rebound_to_another_target_date():
    product,catalog=_product()
    with pytest.raises(ValueError,match="DATE_NOT_SUPPORTED"):
        analysis.validate_product(product,target_trade_date="20261001",
            publication_date=PUBLICATION,catalog=catalog)


def test_default_date_reads_previous_hk_session_and_missing_other_date_is_not_zero(tmp_path:Path):
    product,catalog=_product();service=_Service(tmp_path,_fixtures()[2]);_write_product(service,product)
    with _client(service) as client:
        response=client.get("/api/v4/manager/research/announcements/analysis",params={"date":TARGET})
        assert response.status_code==200
        body=response.json()
        assert body["publication_date"]==PUBLICATION
        assert body["date_selection_basis"]=="PREVIOUS_HK_TRADING_SESSION"
        assert body["analysis"]["status"]=="VERIFIED"
        missing=client.get("/api/v4/manager/research/announcements/analysis",params={
            "date":TARGET,"publication_date":"2026-09-30"})
        assert missing.status_code==200
        missing_body=missing.json()
        assert missing_body["analysis"]["status"]=="NOT_IMPORTED"
        assert missing_body["source_catalog"]["directory_record_count"] is None
        assert missing_body["analysis"]["summary"] is None
        assert missing_body["analysis"]["records"]==[]
        assert missing_body["analysis"]["stock_selection"]["status"]=="NOT_ASSESSED"
        assert missing_body["analysis"]["stock_selection"]["selected_stock_count"] is None
        other_target=client.get("/api/v4/manager/research/announcements/analysis",params={"date":"20261001"})
        assert other_target.status_code==200
        other_body=other_target.json()
        assert other_body["target_trade_date"]=="20261001"
        assert other_body["analysis"]["status"]=="NOT_IMPORTED"
        assert other_body["analysis"]["summary"] is None
        assert other_body["analysis"]["records"]==[]


def test_same_analysis_product_can_read_deduplicated_stock_decisions(tmp_path:Path):
    product,catalog=_product()
    decisions=[]
    for index,record in enumerate(product["records"]):
        if index==0:
            disposition,basis,reason="SELECTED_EVENT","OPERATING_EVENT","Specific event included for study."
        elif index==1:
            disposition,basis,reason="CONDITIONAL_WATCH","CONDITIONAL_WATCH","Transaction remains conditional."
        elif record["analysis_kind"]=="TEXT_INSUFFICIENT_UNASSESSED":
            disposition,basis,reason="NOT_ASSESSED","NOT_ASSESSED","The body was insufficient."
        else:
            disposition,basis,reason="NOT_SELECTED","NOT_SELECTED","No qualifying evidence in this article."
        decisions.append({
            "art_code":record["art_code"],
            "issuer_codes":[issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope":record["security_scope"],
            "semantic_record_sha256":record["semantic_record_sha256"],
            "body_record_sha256":record["body_record_sha256"],
            "disposition":disposition,"selection_basis":basis,"reason":reason,"risk_notes":[],
        })
    extended=selection.attach_extension(product,selection.make_extension(product,decisions))
    service=_Service(tmp_path,_fixtures()[2]);_write_product(service,extended)
    checked=analysis.validate_product(extended,target_trade_date=TARGET,
        publication_date=PUBLICATION,catalog=catalog)
    projection=selection.read_projection(checked)
    assert projection["status"]=="VERIFIED"
    assert projection["stock_count"]==140
    assert projection["article_count"]==234
    assert projection["selected_stock_count"]==1
    assert projection["conditional_watch_count"]==1
    assert sum(row["status"]=="NOT_ASSESSED" for row in projection["stocks"])>0
    with _client(service) as client:
        response=client.get("/api/v4/manager/research/announcements/analysis",params={
            "date":TARGET,"publication_date":PUBLICATION})
    assert response.status_code==200
    body=response.json()
    assert body["analysis"]["stock_selection"]["status"]=="VERIFIED"
    assert body["analysis"]["stock_selection"]["article_count"]==234
    assert body["analysis"]["stock_selection"]["selected_stock_count"]==1
    assert len(body["analysis"]["stock_selection"]["stocks"])==140


def test_wrong_product_sha_is_rejected_by_read_only_route(tmp_path:Path):
    product, _catalog=_product();service=_Service(tmp_path,_fixtures()[2]);path=_write_product(service,product)
    mutated=json.loads(path.read_bytes());mutated["records"][0]["factual_summary"]="tampered"
    path.write_text(json.dumps(mutated,ensure_ascii=False))
    with _client(service) as client:
        response=client.get("/api/v4/manager/research/announcements/analysis",params={
            "date":TARGET,"publication_date":PUBLICATION})
    assert response.status_code==409
    assert response.json()["detail"]=="ANNOUNCEMENT_ANALYSIS_READBACK_REJECTED"


def test_invalid_selected_publication_date_is_rejected(tmp_path:Path):
    service=_Service(tmp_path,_fixtures()[2])
    with _client(service) as client:
        response=client.get("/api/v4/manager/research/announcements/analysis",params={
            "date":TARGET,"publication_date":"20260931"})
    assert response.status_code==422
