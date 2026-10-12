"""Read-only and provenance checks for the reviewed HK announcement projection."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research import announcement_analysis as analysis
from v4.manager_research import announcement_selection as selection
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import digest


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


def _dynamic_fixture(target="20261007",publication="2026-10-06",*,summary="Source-bound research summary"):
    art="AN202610061234567890"
    listing_ref=_ref("https://np-anotice-stock.eastmoney.com/api/security/ann?begin_time=2026-10-06&page_index=1",31)
    listing={"art_code":art,"title":"Reviewed target-date notice","page_index":1,"item_index":1,
        "notice_date":f"{publication} 00:00:00","display_time":f"{publication} 09:00:00:000",
        "raw_body_sha256":listing_ref["body_sha256"],"source_ref":listing_ref,
        "source_issuer_codes":[{"code":"HK.00001","source_stock_code":"00001",
            "market_code":"116","ann_type":"H","name":"Fixture One"}]}
    catalog={"target_trade_date":target,"publication_date":publication,
        "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"COMPLETE",
        "hkex_first_publication_verified":False,"captured_row_count":1,"captured_page_count":2,
        "expected_data_page_count":1,"terminal_empty_seen":True,"manager_consumer_row_count":1,
        "manager_source_identity_count":1,"manager_source_codes":["HK.00001"],
        "manager_matched_master_codes":[],"run_id":"c"*32,"sha256":"d"*64,
        "connect_eligibility_status":"NOT_ASSESSED","manager_consumer_rows":[listing]}
    catalog_read={"schema_version":"v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date":target,"publication_date":publication,
        "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"COMPLETE",
        "readback_status":"VERIFIED","catalog":catalog,"gaps":[]}
    content_ref=_ref(f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art}&client_source=web&page_index=1",32)
    semantic={"schema":"v4.announcement-semantic-catalog.v2","status":"PASS_SOURCE_BOUND_REVIEWED_SEMANTIC_RECORDS",
        "target_notice_date":publication,"target_research_date":target,"row_count":1,
        "records":[{"art_code":art,"title":listing["title"],"classification":"BUSINESS_EVENT",
            "classification_as_authored":"研究事件","security_scope":"HK issuer-level",
            "factual_summary":summary,"why_useful":"RESEARCH_CONTEXT","research_priority":"NORMAL",
            "issuer_codes":[{"code":"HK.00001"}],
            "date_semantics":{"first_publication_timestamp":None,"available_at_for_target_cutoff":None},
            "cutoff_boundary":"CANNOT_CONFIRM","evidence":{"exact_excerpt":"Source quote"}}]}
    page_text="Verified source-bound content"
    page_text_sha=sha256(page_text.encode("utf-8")).hexdigest()
    body_text_sha=sha256(page_text.encode("utf-8")).hexdigest()
    body={"schema":"v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date":publication,"article_count":1,"rows":[{"art_code":art,
            "title":listing["title"],"body_status":"COMPLETE_CONTENT_API_BODY","pdf_status":"PDF_REF_MISSING",
            "content_page_count":1,"body_text":page_text,"body_text_sha256":body_text_sha,
            "pages":[{"page_index":1,"notice_date":f"{publication} 00:00:00",
                "text":page_text,"blob_sha256":content_ref["blob_sha256"],
                "raw_body_sha256":content_ref["body_sha256"],"text_sha256":page_text_sha,
                "source_ref":content_ref}]}]}
    def raw_sha(value):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        return sha256(raw).hexdigest()
    descriptors=[
        {"name":"semantic_catalog","sha256":raw_sha(semantic),"canonical_sha256":digest(semantic),"row_count":1},
        {"name":"body_corpus","sha256":raw_sha(body),"canonical_sha256":digest(body),"row_count":1},
    ]
    product=analysis.build_product(semantic,body,catalog_read,semantic_sha256=descriptors[0]["sha256"],
        body_sha256=descriptors[1]["sha256"],verified_inputs=descriptors,
        target_trade_date=target,publication_date=publication)
    return product,catalog_read,semantic,body,descriptors


def _reseal_dynamic_descriptors(semantic, body):
    def raw_sha(value):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        return sha256(raw).hexdigest()
    return [
        {"name":"semantic_catalog","sha256":raw_sha(semantic),"canonical_sha256":digest(semantic),"row_count":1},
        {"name":"body_corpus","sha256":raw_sha(body),"canonical_sha256":digest(body),"row_count":1},
    ]


def test_dynamic_import_rejects_stale_input_mixed_date_and_tampered_body():
    product,catalog_read,semantic,body,descriptors=_dynamic_fixture()
    with pytest.raises(ValueError,match="INPUT_SHA_OR_COUNT_MISMATCH"):
        analysis.build_product(semantic,body,catalog_read,semantic_sha256="0"*64,
            body_sha256=descriptors[1]["sha256"],verified_inputs=descriptors,
            target_trade_date="20261007",publication_date="2026-10-06")
    mixed=dict(semantic,target_research_date="20261008")
    with pytest.raises(ValueError,match="CORPUS_TARGET_MISMATCH|CORPUS_IDENTITY_INVALID"):
        analysis.build_product(mixed,body,catalog_read,semantic_sha256=descriptors[0]["sha256"],
            body_sha256=descriptors[1]["sha256"],verified_inputs=descriptors,
            target_trade_date="20261007",publication_date="2026-10-06")
    tampered=json.loads(json.dumps(body));tampered["rows"][0]["pages"][0]["notice_date"]="2026-10-05 23:59:00"
    with pytest.raises(ValueError,match="BODY_PAGE_DATE_MISMATCH|CANONICAL_SHA_MISMATCH"):
        analysis.build_product(semantic,tampered,catalog_read,semantic_sha256=descriptors[0]["sha256"],
            body_sha256=descriptors[1]["sha256"],verified_inputs=descriptors,
            target_trade_date="20261007",publication_date="2026-10-06")
    assert product["target_trade_date"]=="20261007"


@pytest.mark.parametrize("mutation,error", [
    ("missing_page_index_query", "BODY_PAGE_SOURCE_BINDING_MISMATCH"),
    ("missing_page_raw_sha", "BODY_PAGE_SOURCE_INVALID"),
    ("missing_source_blob_sha", "BODY_SOURCE_MISSING|BODY_PAGE_SOURCE_INVALID"),
    ("missing_text_sha", "BODY_PAGE_SOURCE_INVALID"),
    ("tampered_page_text", "BODY_PAGE_TEXT_SHA_MISMATCH"),
    ("tampered_body_text", "BODY_TEXT_SHA_MISMATCH"),
])
def test_dynamic_body_source_binding_requires_query_hashes_and_matching_text(mutation,error):
    _product,catalog_read,semantic,body,_descriptors=_dynamic_fixture()
    body=json.loads(json.dumps(body))
    page=body["rows"][0]["pages"][0]
    if mutation=="missing_page_index_query":
        page["source_ref"]["request"]["url"] = page["source_ref"]["request"]["url"].replace("&page_index=1", "")
    elif mutation=="missing_page_raw_sha":
        page.pop("raw_body_sha256")
    elif mutation=="missing_source_blob_sha":
        page["source_ref"].pop("blob_sha256")
    elif mutation=="missing_text_sha":
        page.pop("text_sha256")
    elif mutation=="tampered_page_text":
        page["text"] += " tampered"
    elif mutation=="tampered_body_text":
        body["rows"][0]["body_text"] += " tampered"
    descriptors=_reseal_dynamic_descriptors(semantic,body)
    with pytest.raises(ValueError,match=error):
        analysis.build_product(semantic,body,catalog_read,
            semantic_sha256=descriptors[0]["sha256"],body_sha256=descriptors[1]["sha256"],
            verified_inputs=descriptors,target_trade_date="20261007",publication_date="2026-10-06")


def test_dynamic_identity_counts_are_codes_and_associations_not_issuers():
    product,catalog_read,_semantic,_body,_descriptors=_dynamic_fixture()
    checked=analysis.validate_product(product,target_trade_date="20261007",
        publication_date="2026-10-06",catalog=catalog_read["catalog"])
    assert checked["source_manifest"]["manager_source_identity_association_count"]==1
    assert checked["source_manifest"]["distinct_manager_source_code_count"]==1
    assert checked["source_manifest"]["manager_issuer_count"] is None
    assert checked["source_manifest"]["unknown_issuer_count"] is None
    assert checked["source_manifest"]["issuer_count_status"]=="CANNOT_CONFIRM"
    broken=json.loads(json.dumps(product))
    broken["summary"]["manager_issuer_count"]=1
    broken["sha256"]=digest({key:value for key,value in broken.items() if key!="sha256"})
    with pytest.raises(ValueError,match="SOURCE_IDENTITY_SUMMARY_MISMATCH"):
        analysis.validate_product(broken,target_trade_date="20261007",
            publication_date="2026-10-06",catalog=catalog_read["catalog"])


def _multi_source_fixture():
    target="20261012";publication="2026-10-12"
    art="AN2026101200000001";news_id="12345678";variant_id="HKEX:"+news_id
    listing_ref=_ref("https://np-anotice-stock.eastmoney.com/api/security/ann?begin_time=2026-10-12&page_index=1",41)
    listing={"art_code":art,"title":"Eastmoney reviewed notice","page_index":1,"item_index":1,
        "notice_date":publication+" 00:00:00","display_time":publication+" 09:00:00:000",
        "raw_body_sha256":listing_ref["body_sha256"],"source_ref":listing_ref,
        "source_issuer_codes":[{"code":"HK.02665","source_stock_code":"02665",
            "market_code":"116","ann_type":"H","name":"Fixture HK issuer"}]}
    catalog={"target_trade_date":target,"publication_date":publication,
        "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"COMPLETE",
        "hkex_first_publication_verified":False,"captured_row_count":2,"captured_page_count":2,
        "expected_data_page_count":1,"terminal_empty_seen":True,"manager_consumer_row_count":1,
        "manager_source_identity_count":1,"manager_source_codes":["HK.02665"],
        "manager_matched_master_codes":[],"run_id":"a"*32,"sha256":"b"*64,
        "connect_eligibility_status":"NOT_ASSESSED","manager_consumer_rows":[listing]}
    catalog_read={"schema_version":"v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date":target,"publication_date":publication,
        "source_scope":"EASTMONEY_HK_DATE_CATALOG","status":"COMPLETE",
        "readback_status":"VERIFIED","catalog":catalog,"gaps":[]}
    body_ref=_ref(f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art}&page_index=1",42)
    em_text="Exact Eastmoney page text";em_text_sha=sha256(em_text.encode()).hexdigest()
    em_body={"art_code":art,"title":listing["title"],"body_status":"COMPLETE_CONTENT_API_BODY",
        "content_page_count":1,"body_text":em_text,"body_text_sha256":em_text_sha,
        "pages":[{"page_index":1,"notice_date":publication+" 08:00:00",
            "text":em_text,"text_sha256":em_text_sha,"raw_body_sha256":body_ref["body_sha256"],
            "blob_sha256":body_ref["blob_sha256"],"source_ref":body_ref}]}
    official_dir_ref=_ref("https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012",43)
    official_body_ref=_ref("https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/02665-example.pdf",44)
    official_text="Exact HKEX PDF extracted text";official_text_sha=sha256(official_text.encode()).hexdigest()
    monthly_source={"source_date":"20261005","market":"HK_CONNECT",
        "role":"HK_CONNECT_FULL_MARKET_AUTHORITY","available_at":"2026-10-05T09:00:00+08:00",
        "artifact_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.json",
        "manifest_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/manifest.json",
        "receipt_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/receipt.json",
        "current_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.authority/current.json",
        "capture_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/capture.json",
        "publication_ref":"universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/publication.json",
        "sha256":"1"*64,"capture_sha256":"2"*64,"source_sha256":"3"*64}
    ref_keys=("artifact_ref","manifest_ref","receipt_ref","current_ref","capture_ref","publication_ref")
    monthly={"schema_version":"v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status":"VERIFIED","policy":"CALENDAR_MONTH_LATEST_VERIFIED_V2","month":"202610",
        "target_trade_date":target,"source_date":"20261005",
        "capture_cutoff_at":"2026-10-12T10:00:00+08:00","source":monthly_source,
        "authority_file_sha256s":{key:"4"*64 for key in ref_keys},"code_count":1,
        "codes_sha256":digest(["HK.02665"]),"codes":["HK.02665"],"invalid_newer_candidates":[],
        "RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
    monthly["identity_sha256"]=digest(monthly)
    variant={"source_variant_id":variant_id,"source":"HKEX_OFFICIAL",
        "source_scope":"HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1","news_id":news_id,
        "symbol":"HK.02665","name":"Fixture HK issuer","title":"Official HKEX annual results",
        "publication_date":"20261012","published_at":"2026-10-12T08:00:00+08:00",
        "available_at":"2026-10-12T00:01:00+00:00",
        "source_url":official_body_ref["request"]["url"],
        "directory_source_ref":official_dir_ref,"directory_raw_body_sha256":official_dir_ref["body_sha256"],
        "body_source_ref":official_body_ref,"body_status":"COMPLETE_HKEX_OFFICIAL_PDF_BODY",
        "body_text":official_text,"body_text_sha256":official_text_sha,
        "pages":[{"page_index":1,"text":official_text,"text_sha256":official_text_sha,
            "raw_body_sha256":official_body_ref["body_sha256"],"source_ref":official_body_ref}],
        "body_artifact":"official_variants/"+news_id+".json","body_artifact_sha256":"5"*64,
        "cross_source_link_status":"NOT_ASSESSED","connect_eligibility_status":"ELIGIBLE",
        "matched_connect_codes":["HK.02665"],"connect_eligibility_identity_sha256":monthly["identity_sha256"]}
    em_semantic={"art_code":art,"title":listing["title"],"classification":"BUSINESS_EVENT",
        "security_scope":"Issuer-level","factual_summary":"Reviewed Eastmoney fact",
        "why_useful":"RESEARCH_CONTEXT","issuer_codes":[{"code":"HK.02665"}],
        "date_semantics":{"first_publication_timestamp":None,"available_at_for_target_cutoff":None},
        "cutoff_boundary":"CANNOT_CONFIRM","evidence":{"exact_excerpt":"Eastmoney excerpt"}}
    hkex_semantic={"source_variant_id":variant_id,"source_scope":"HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "title":variant["title"],"classification":"BUSINESS_EVENT","security_scope":"Issuer-level",
        "factual_summary":"Reviewed official filing fact","why_useful":"RESEARCH_CONTEXT",
        "issuer_codes":[{"code":"HK.02665"}],
        "date_semantics":{"first_publication_timestamp":None,"available_at_for_target_cutoff":None},
        "cutoff_boundary":"CANNOT_CONFIRM","evidence":{"exact_excerpt":"Official filing excerpt"}}
    semantic={"schema":"v4.announcement-semantic-catalog.v2","status":"PASS_SOURCE_BOUND_REVIEWED_SEMANTIC_RECORDS",
        "target_notice_date":publication,"target_research_date":target,"row_count":2,
        "records":[em_semantic,hkex_semantic]}
    body_manifest_sha="6"*64;input_identity="7"*64
    body={"schema":"v4.manager_research.eastmoney_hk_multi_source_announcement_body_corpus.v1",
        "target_notice_date":publication,"target_trade_date":target,"publication_date":publication,
        "article_count":1,"eastmoney_article_count":1,"source_variant_count":1,"combined_document_count":2,
        "rows":[em_body],"source_variants":[variant],"monthly_connect_eligibility":monthly,
        "input_identity_sha256":input_identity,"source_manifest_sha256":body_manifest_sha,
        "hkex_directory_readback_sha256":"8"*64,"hkex_directory_product_run_ids":["9"*32],
        "hkex_directory_document_count":1,"hkex_eligible_document_count":1,
        "hkex_excluded_document_count":0,"hkex_unresolved_document_count":0,
        "hkex_cross_source_link_status":"NOT_ASSESSED"}
    terminal_variant={"source_variant_id":variant_id,"news_id":news_id,"title":variant["title"],
        "symbol":variant["symbol"],"name":variant["name"],"body_status":variant["body_status"],
        "body_file_sha256":variant["body_artifact_sha256"],"body_record_sha256":digest(variant),
        "directory_source_ref":analysis._source_ref(official_dir_ref),
        "body_source_ref":analysis._source_ref(official_body_ref)}
    terminal={"schema_version":"v4.manager_research.announcement_terminal_body_capture.v1",
        "status":"PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS","input_identity_sha256":input_identity,
        "article_count":1,"body_status_counts":{"COMPLETE_CONTENT_API_BODY":1},
        "body_corpus_sha256":"f"*64,"body_corpus_manifest_sha256":body_manifest_sha,
        "body_batch_receipt_sha256":"b"*64,"capture_receipt_sha256":"c"*64,
        "failed_articles":[],
        "hkex_directory_readback_sha256":"8"*64,"hkex_directory_run_ids":["9"*32],
        "hkex_directory_document_count":1,"hkex_eligible_document_count":1,
        "hkex_excluded_document_count":0,"hkex_unresolved_document_count":0,
        "hkex_body_coverage_status":"COMPLETE","hkex_variant_records":[terminal_variant],
        "monthly_connect_eligibility_file_sha256":"d"*64,
        "monthly_connect_eligibility_identity_sha256":monthly["identity_sha256"],
        "monthly_connect_source_date":"20261005","monthly_connect_eligibility":monthly}
    body["source_manifest_sha256"]=body_manifest_sha
    semantic_sha="e"*64;body_sha="f"*64
    descriptors=[{"name":"semantic_catalog","sha256":semantic_sha,
        "canonical_sha256":digest(semantic),"row_count":2},
        {"name":"body_corpus","sha256":body_sha,"canonical_sha256":digest(body),"row_count":1}]
    product=analysis.build_product(semantic,body,catalog_read,semantic_sha256=semantic_sha,
        body_sha256=body_sha,verified_inputs=descriptors,target_trade_date=target,
        publication_date=publication,terminal_body_capture=terminal)
    return product,catalog_read,semantic,body,terminal,descriptors


def test_multi_source_import_keeps_hkex_ids_and_selection_without_art_code_join():
    product,catalog_read,semantic,body,terminal,descriptors=_multi_source_fixture()
    checked=analysis.validate_product(product,target_trade_date="20261012",
        publication_date="2026-10-12",catalog=catalog_read["catalog"])
    official=next(row for row in checked["records"] if row.get("source_variant_id"))
    assert official["source_variant_id"]=="HKEX:12345678"
    assert "art_code" not in official
    assert official["source_scope"]=="HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
    assert checked["source_manifest"]["monthly_connect_source_date"]=="20261005"
    assert checked["source_manifest"]["hkex_cross_source_link_status"]=="NOT_ASSESSED"

    decisions=[]
    for record in checked["records"]:
        key={"source_variant_id":record["source_variant_id"]} if "source_variant_id" in record else {"art_code":record["art_code"]}
        official_record="source_variant_id" in record
        decisions.append({**key,"issuer_codes":[issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope":record["security_scope"],
            "semantic_record_sha256":record["semantic_record_sha256"],
            "body_record_sha256":record["body_record_sha256"],
            "disposition":"SELECTED_EVENT" if official_record else "NOT_SELECTED",
            "selection_basis":"OPERATING_EVENT" if official_record else "NOT_SELECTED",
            "reason":"Reviewed official filing added to research." if official_record else "Reviewed EM notice excluded.",
            "risk_notes":[]})
    extended=selection.attach_extension(checked,selection.make_extension(checked,decisions))
    selected=analysis.validate_product(extended,target_trade_date="20261012",
        publication_date="2026-10-12",catalog=catalog_read["catalog"])
    projection=selection.read_projection(selected)
    assert projection["selected_stock_count"]==1
    official_article=next(article for article in projection["stocks"][0]["articles"]
        if article.get("source_variant_id"))
    assert official_article["source_variant_id"]=="HKEX:12345678"
    assert "art_code" not in official_article
    fake_join={**decisions[1],"art_code":"AN2026101200099999"}
    with pytest.raises(ValueError,match="DECISION_ARTICLE_MISMATCH"):
        selection.make_extension(checked,[decisions[0],fake_join])


def test_dynamic_product_import_is_idempotent_and_failed_import_does_not_clobber(tmp_path:Path):
    product,catalog_read,_semantic,_body,_descriptors=_dynamic_fixture()
    decisions=[]
    for record in product["records"]:
        decisions.append({"art_code":record["art_code"],
            "issuer_codes":[issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope":record["security_scope"],
            "semantic_record_sha256":record["semantic_record_sha256"],
            "body_record_sha256":record["body_record_sha256"],
            "disposition":"NOT_SELECTED","selection_basis":"NOT_SELECTED",
            "reason":"No qualifying evidence in this reviewed item.","risk_notes":[]})
    product=selection.attach_extension(product,selection.make_extension(product,decisions))

    class Owner:
        def __init__(self):
            self.store=ManagerResearchStore(tmp_path/"owner")
        def get_announcement_date_catalog(self,target,publication):
            return catalog_read if (target,publication)==("20261007","2026-10-06") else {}
        def get_announcement_analysis(self,target,publication=None):
            return analysis.read(self,target,publication)

    owner=Owner()
    first=analysis.import_product(owner,product)
    path=analysis.product_path(owner.store,"20261007","2026-10-06")
    first_bytes=path.read_bytes()
    assert first["import_status"]=="IMPORTED"
    assert first["analysis"]["stock_selection"]["status"]=="VERIFIED"
    second=analysis.import_product(owner,product)
    assert second["import_status"]=="ALREADY_IMPORTED"
    assert path.read_bytes()==first_bytes
    broken=json.loads(json.dumps(product));broken["records"][0]["factual_summary"]="tampered"
    with pytest.raises(ValueError,match="PRODUCT_SHA_MISMATCH"):
        analysis.import_product(owner,broken)
    assert path.read_bytes()==first_bytes
    with _client(owner) as client:
        response=client.get("/api/v4/manager/research/announcements/analysis",params={
            "date":"20261007","publication_date":"2026-10-06"})
    assert response.status_code==200
    assert response.json()["analysis"]["stock_selection"]["status"]=="VERIFIED"
