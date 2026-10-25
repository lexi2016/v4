"""Offline physical-page and retained-partial-body contracts for Task3 only."""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import socket
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

from announcement_autorun_fixtures import pdf_bytes
from ops import manager_announcement_body_batch as batch
from v4.manager_research import pdf_parser, workspace_announcements as owner
from v4.manager_research.announcement_source import capture as capture_official, capture_eastmoney
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse

TARGET, PUBLICATION = "20261023", "2026-10-23"
FAILED, GOOD = "AN20261023000001", "AN20261023000002"
RUN_ID = "d" * 32


@pytest.fixture(scope="session", autouse=True)
def worktree_binding():
    root = Path(__file__).resolve().parents[1]
    assert root == Path("/Users/lexi/.codex/worktrees/announcement-isolated-page-20261023/v4_app")
    assert Path.cwd() == root
    for module in (batch, pdf_parser, owner):
        assert Path(module.__file__).resolve().is_relative_to(root)
    print("TASK3_BINDING", json.dumps({"cwd": str(Path.cwd()), "python": sys.executable,
        "test_file": str(Path(__file__).resolve()),
        "modules": {module.__name__: str(Path(module.__file__).resolve())
            for module in (batch, pdf_parser, owner)}}, sort_keys=True))


@pytest.fixture(autouse=True)
def offline_transport_only(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("TASK3_REAL_NETWORK_FORBIDDEN")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(batch, "REQUEST_INTERVAL_SECONDS", 0)


def _fail_physical_page_two(monkeypatch):
    reader = pdf_parser._load_pdf_reader()
    page_type = type(reader(__import__("io").BytesIO(pdf_bytes(pages=3))).pages[0])
    original = page_type.extract_text
    def extract(self, *args, **kwargs):
        if self.indirect_reference.idnum == 6:
            raise ValueError("synthetic physical page 2 extraction failure")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(page_type, "extract_text", extract)


def _hkex_variant(tmp_path, raw):
    ref = {"body_sha256": batch.digest(raw), "http_status": 200,
        "retrieved_at": "2026-10-23T08:00:00+08:00", "request": {"url":
        "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1023/fixture.pdf"}}
    directory_raw = b"synthetic directory fixture"
    directory = {"body_sha256": batch.digest(directory_raw)}
    api = batch.imports()
    api["read_response"] = lambda _store, value: raw if value == ref else directory_raw
    return batch._capture_hkex_variant(api, None, None, None, {
        "news_id": "12345678", "symbol": "HK.02665", "title": "Fixture",
        "source_url": ref["request"]["url"], "source_refs": [ref],
        "directory_ref": directory, "body_status": "BODY_CAPTURED_UNASSESSED",
    }, tmp_path, TARGET, PUBLICATION)


def test_failed_physical_page_is_not_renumbered_or_complete(monkeypatch, tmp_path):
    _fail_physical_page_two(monkeypatch)
    result = _hkex_variant(tmp_path, pdf_bytes(pages=3))
    print("F7 actual writer outcome:", result["body_status"], result.get("diagnostic_pages", result["pages"]))
    assert result["body_status"] != "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
    diagnostics = result["diagnostic_pages"]
    assert result["pages"] == []
    assert [page["page_index"] for page in diagnostics] == [1, 2, 3]
    assert [page["page_total"] for page in diagnostics] == [3, 3, 3]
    assert diagnostics[1]["extraction_status"] == "EXTRACTION_FAILED"
    assert diagnostics[1]["error_code"] == "PDF_PAGE_EXTRACTION_FAILED"
    assert batch.read_json(tmp_path / result["body_artifact"])["pages"] == diagnostics
    assert result["body_text"] is None and result["body_text_sha256"] is None


def test_generic_parser_compatibility_retains_original_sparse_contract(monkeypatch):
    _fail_physical_page_two(monkeypatch)
    pages = pdf_parser.extract_pdf_pages(pdf_bytes(pages=3))
    assert [p["page"] for p in pages] == [1, 3]
    assert all(set(p) == {"page", "text"} for p in pages)
    assert pdf_parser.extract_pdf_pages(b"not a PDF") == []


def test_real_blank_page_is_distinct_from_extraction_failure(tmp_path):
    pdf_parser._load_pdf_reader()
    pypdf = sys.modules["pypdf"]
    writer = pypdf.PdfWriter()
    reader = pypdf.PdfReader(BytesIO(pdf_bytes()))
    writer.add_page(reader.pages[0])
    writer.add_blank_page(width=612, height=792)
    writer.add_page(reader.pages[0])
    raw = BytesIO()
    writer.write(raw)
    result = _hkex_variant(tmp_path, raw.getvalue())
    assert result["body_status"] == "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
    assert [(p["page_index"], p["page_total"]) for p in result["diagnostic_pages"]] == [(1, 3), (2, 3), (3, 3)]
    assert result["diagnostic_pages"][1]["extraction_status"] == "EMPTY_TEXT"
    assert result["diagnostic_pages"][1]["error_code"] == "PDF_PAGE_TEXT_EMPTY"
    assert result["body_text"] is None
    assert [p["page"] for p in pdf_parser.extract_pdf_pages(raw.getvalue())] == [1, 3]


def test_unavailable_physical_page_is_retained_and_not_complete(monkeypatch, tmp_path):
    reader = pdf_parser._load_pdf_reader()
    page_list_type = type(reader(BytesIO(pdf_bytes(pages=3))).pages)
    original = page_list_type.__getitem__
    def get_page(self, index):
        if index == 1:
            raise ValueError("synthetic unavailable physical page")
        return original(self, index)
    monkeypatch.setattr(page_list_type, "__getitem__", get_page)
    result = _hkex_variant(tmp_path, pdf_bytes(pages=3))
    assert result["body_status"] == "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
    assert [p["page_index"] for p in result["diagnostic_pages"]] == [1, 2, 3]
    assert result["diagnostic_pages"][1]["extraction_status"] == "PAGE_UNAVAILABLE"
    assert result["diagnostic_pages"][1]["error_code"] == "PDF_PAGE_UNAVAILABLE"


def test_all_unextractable_pages_have_physical_diagnostics(monkeypatch, tmp_path):
    reader = pdf_parser._load_pdf_reader()
    page_type = type(reader(BytesIO(pdf_bytes())).pages[0])
    def fail(*_a, **_k):
        raise ValueError("synthetic extraction failure")
    monkeypatch.setattr(page_type, "extract_text", fail)
    result = _hkex_variant(tmp_path, pdf_bytes(pages=3))
    assert result["body_status"] == "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
    assert len(result["diagnostic_pages"]) == 3
    assert {p["extraction_status"] for p in result["diagnostic_pages"]} == {"EXTRACTION_FAILED"}
    assert result["body_text"] is None


def test_complete_physical_pdf_retains_all_pages_and_generic_contract(tmp_path):
    raw = pdf_bytes(pages=3)
    result = _hkex_variant(tmp_path, raw)
    assert result["body_status"] == "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
    assert [(p["page_index"], p["page_total"]) for p in result["pages"]] == [(1, 3), (2, 3), (3, 3)]
    assert result["body_text"] == "\n\n".join(p["text"] for p in result["pages"])
    assert result["body_text_sha256"] == batch.digest(result["body_text"].encode())
    assert pdf_parser.extract_pdf_text(raw)[1] == ["PDF page 1", "PDF page 2", "PDF page 3"]
    for strict in (False, True):
        with pytest.raises(pdf_parser.PdfParseError, match="PDF_PAGE_BUDGET_EXCEEDED"):
            pdf_parser.extract_pdf_pages(raw, max_pages=2, preserve_physical_pages=strict)


class _ContentTransport:
    def __init__(self):
        self.calls = []
        self.rows = [{"art_code": code, "notice_date": PUBLICATION,
            "title": "Fixture " + code} for code in (FAILED, GOOD)]

    def __call__(self, url, *, timeout, **_kwargs):
        self.calls.append(url)
        query = parse_qs(urlsplit(url).query)
        if "art_code" in query:
            code = query["art_code"][0]
            page = int(query["page_index"][0])
            if code == FAILED and page == 2:
                raise OSError("synthetic later-page transport failure")
            payload = {"success": 1, "data": {"art_code": code,
                "notice_title": "Fixture " + code, "notice_date": PUBLICATION,
                "page_size": 2 if code == FAILED else 1,
                "security": [{"market_uni": "116", "stock": "02665"}],
                "notice_content": f"Synthetic source text {code} page {page}"}}
        else:
            payload = {"data": {"list": self.rows if query.get("page_index") == ["1"] else []}}
        return SourceResponse(url, 200, batch.json_bytes(payload), {},
            "2026-10-23T08:00:00+08:00", url)


def _multi_source_inputs(tmp_path, monkeypatch):
    authority = tmp_path / "monthly-authority"
    authority.mkdir()
    refs = {key: key + ".json" for key in ("artifact_ref", "manifest_ref", "receipt_ref",
        "current_ref", "capture_ref", "publication_ref")}
    hashes = {}
    for key, relative in refs.items():
        raw = ("synthetic-authority:" + key).encode()
        (authority / relative).write_bytes(raw)
        hashes[key] = batch.digest(raw)
    monthly = {"schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2", "month": "202610",
        "target_trade_date": TARGET, "source_date": "20261001",
        "capture_cutoff_at": "2026-10-23T08:00:00+08:00",
        "source": {"market": "HK_CONNECT", "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
            "source_date": "20261001", "available_at": "2026-10-01T09:00:00+08:00",
            **refs, "sha256": "1" * 64, "capture_sha256": "2" * 64, "source_sha256": "3" * 64},
        "authority_file_sha256s": hashes, "code_count": 1, "codes": ["HK.02665"],
        "codes_sha256": owner.digest(["HK.02665"]), "invalid_newer_candidates": [], **owner.FLAGS}
    monthly["identity_sha256"] = owner.digest(monthly)
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(authority))
    run_id = "f" * 32
    hkex = {"target_trade_date": TARGET, "daily_publication_date": TARGET,
        "publication_timezone": "Asia/Hong_Kong", "official_documents": [],
        "coverage": {"market_directory_products": [{
            "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "from_date": TARGET,
            "to_date": TARGET, "window_mode": "HK_CALENDAR_DAY_V1", "status": "COMPLETE",
            "directory_exhaustion": "VERIFIED", "record_count": 0, "loaded_record": 0,
            "captured_row_count": 0, "unique_news_id_count": 0,
            "product_run_id": run_id, "product_sha256": "a" * 64}]}}
    return hkex, monthly


def _capture_fixture(tmp_path, monkeypatch, *, multi_source=False, hkex_pdf=None):
    evidence = tmp_path / "state" / "announcement_agent_runs" / RUN_ID / "evidence"
    evidence.mkdir(parents=True)
    materials = MaterialStore(tmp_path / "state" / "materials")
    transport = _ContentTransport()
    official_url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1023/fixture.pdf"
    directory_url = "https://www1.hkexnews.hk/search/titleSearchServlet.do?fixture=task3"
    def official_transport(url, **_kwargs):
        assert hkex_pdf is not None and url in (official_url, directory_url)
        return SourceResponse(url, 200, hkex_pdf if url == official_url else b"synthetic directory",
            {}, "2026-10-23T08:00:00+08:00", url)
    provider = HkexOfficialProvider(material_store=materials, eastmoney_transport=transport,
        transport=official_transport)
    api = batch.imports()
    receipts, rows = [], []
    for index in (1, 2):
        url = api["date_scoped_url"](PUBLICATION, index)
        ref = capture_eastmoney(provider, url)
        raw = api["read_eastmoney_response"](materials, ref)
        receipts.append({"page_index": index, "capture_status": "PASS", "source_ref": ref,
            "requested_url": url, "raw_body_sha256": batch.digest(raw),
            "row_count": 2 if index == 1 else 0})
        if index == 1:
            for raw_row in transport.rows:
                rows.append({"art_code": raw_row["art_code"], "title": raw_row["title"],
                    "notice_date": PUBLICATION, "page_index": 1, "raw_row": raw_row,
                    "source_ref": ref, "raw_body_sha256": batch.digest(raw),
                    "source_issuer_codes": [{"code": "HK.02665", "source_stock_code": "02665",
                        "market_code": "116", "ann_type": "H"}]})
    catalog = {"target_trade_date": TARGET, "publication_date": PUBLICATION,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "connect_eligibility_status": "NOT_ASSESSED", "hkex_first_publication_verified": False,
        "run_id": "c" * 32, "sha256": "e" * 64, "manager_consumer_rows": rows,
        "manager_consumer_row_count": 2, "page_receipts": receipts, "captured_page_count": 2,
        "expected_data_page_count": 1, "expected_terminal_page_index": 2,
        "terminal_empty_seen": True, "captured_row_count": 2, "total_hits": 2, **owner.FLAGS}
    catalog_read = {"schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "readback_status": "VERIFIED", "catalog": catalog}
    output = evidence / "body_batch"
    kwargs = {}
    if multi_source:
        hkex, monthly = _multi_source_inputs(tmp_path, monkeypatch)
        if hkex_pdf is not None:
            directory_ref = capture_official(provider, {"url": directory_url, "method": "GET"})
            body_ref = capture_official(provider, {"url": official_url, "method": "GET"})
            product = hkex["coverage"]["market_directory_products"][0]
            product.update(record_count=1, loaded_record=1, captured_row_count=1, unique_news_id_count=1)
            hkex["official_documents"] = [{"source": "HKEX_OFFICIAL",
                "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
                "news_id": "12345678", "symbol": "HK.02665", "name": "Fixture",
                "title": "Synthetic official fixture", "event_id": "fixture-event",
                "capture_run_id": "f" * 32, "capture_trade_date": TARGET,
                "target_trade_date": TARGET, "publication_date": TARGET,
                "published_at": "2026-10-23T07:30:00+08:00", "source_url": official_url,
                "directory_ref": directory_ref, "source_refs": [body_ref],
                "body_status": "BODY_CAPTURED_UNASSESSED"}]
        kwargs.update(hkex_directory_readback=hkex, monthly_connect_eligibility=monthly)
        batch.atomic_json(evidence / "hkex_directory_read.json", hkex)
        batch.atomic_json(evidence / "monthly_connect_eligibility.json", monthly)
    result = batch.run_capture(catalog_read, materials.root, output, TARGET, PUBLICATION,
        api_overrides={"HkexOfficialProvider": lambda **_kwargs: provider}, **kwargs)
    batch.atomic_json(evidence / "catalog_read.json", catalog_read)
    for src, dst in [("body_corpus.json", "body_corpus.json"),
                     ("body_corpus_manifest.json", "body_corpus_manifest.json"),
                     ("batch_receipt.json", "body_batch_receipt.json")]:
        shutil.copyfile(output / src, evidence / dst)
    capture = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": result["status"], "evidence_run_id": RUN_ID, "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "catalog_run_id": catalog["run_id"],
        "catalog_product_sha256": catalog["sha256"], **owner.FLAGS}
    for key, filename in {"catalog_read_file_sha256": "catalog_read.json",
        "body_corpus_file_sha256": "body_corpus.json",
        "body_corpus_manifest_file_sha256": "body_corpus_manifest.json",
        "body_batch_receipt_sha256": "body_batch_receipt.json"}.items():
        capture[key] = batch.digest((evidence / filename).read_bytes())
    if multi_source:
        capture.update(hkex_directory_read_file_sha256=batch.digest((evidence / "hkex_directory_read.json").read_bytes()),
            hkex_directory_readback_sha256=batch.digest(batch.json_bytes(hkex)),
            hkex_directory_run_ids=["f" * 32], hkex_directory_capture_mode="FRESH_OWNER_CAPTURE",
            hkex_prior_directory_run_ids=[], hkex_fresh_directory_run_id="f" * 32,
            hkex_directory_document_count=len(hkex["official_documents"]),
            hkex_eligible_document_count=len(hkex["official_documents"]),
            hkex_excluded_document_count=0, hkex_unresolved_document_count=0,
            hkex_body_coverage_status=result["hkex_official_supplement"]["body_coverage_status"],
            monthly_connect_eligibility_file_sha256=batch.digest((evidence / "monthly_connect_eligibility.json").read_bytes()),
            monthly_connect_eligibility_identity_sha256=monthly["identity_sha256"],
            monthly_connect_source_date=monthly["source_date"],
            monthly_connect_authority_file_sha256s=monthly["authority_file_sha256s"],
            eastmoney_directory_coverage=result["eastmoney_directory_coverage"])
    batch.atomic_json(evidence / "capture_receipt.json", capture)
    return evidence, catalog_read, result, transport


@pytest.mark.parametrize("multi_source", [False, True])
def test_later_page_failure_preserves_diagnostics_and_valid_neighbor(monkeypatch, tmp_path, multi_source):
    evidence, catalog, result, transport = _capture_fixture(tmp_path, monkeypatch, multi_source=multi_source)
    original_path = evidence / "body_batch" / "bodies" / f"{FAILED}.json"
    original_bytes = original_path.read_bytes()
    original = json.loads(original_bytes)
    assert len(original["content_api_pages"]) == 1
    assert original["content_api_pages"][0]["page_total"] == 2
    assert any("page_index=2" in url for url in transport.calls)
    # Actual producer output enters the strict terminal consumer, without a
    # stubbed parser, article capture, body projection or terminal validator.
    terminal = owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION,
        expected_run_id=RUN_ID)
    assert terminal["body_status_counts"] == {"BODY_CAPTURE_FAILED": 1, "COMPLETE_CONTENT_API_BODY": 1}
    assert [item["art_code"] for item in terminal["failed_articles"]] == [FAILED]
    corpus = batch.read_json(evidence / "body_corpus.json")
    failed, good = corpus["rows"]
    assert failed["pages"] == [] and failed["content_page_count"] is None
    assert failed["body_text"] is None and failed["body_text_sha256"] is None
    assert failed["diagnostic_pages"] == original["content_api_pages"]
    assert good["body_status"] == "COMPLETE_CONTENT_API_BODY" and len(good["pages"]) == 1
    assert result["status"] == "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    assert original_path.read_bytes() == original_bytes


def _reseal_evidence(evidence, body, manifest, receipt):
    """Keep outer hashes valid so corruption tests reach the inner contract."""
    manifest_sha = batch.atomic_json(evidence / "body_corpus_manifest.json", manifest)
    body["source_manifest_sha256"] = manifest_sha
    body_sha = batch.atomic_json(evidence / "body_corpus.json", body)
    receipt.update(body_corpus_manifest_sha256=manifest_sha, body_corpus_sha256=body_sha)
    receipt_sha = batch.atomic_json(evidence / "body_batch_receipt.json", receipt)
    capture_receipt = batch.read_json(evidence / "capture_receipt.json")
    capture_receipt.update(body_corpus_manifest_file_sha256=manifest_sha,
        body_corpus_file_sha256=body_sha, body_batch_receipt_sha256=receipt_sha)
    batch.atomic_json(evidence / "capture_receipt.json", capture_receipt)


@pytest.mark.parametrize("multi_source", [False, True])
def test_terminal_rejects_dropped_partial_diagnostics(monkeypatch, tmp_path, multi_source):
    evidence, catalog, _, _ = _capture_fixture(tmp_path, monkeypatch, multi_source=multi_source)
    body = batch.read_json(evidence / "body_corpus.json")
    body["rows"][0]["diagnostic_pages"] = []
    _reseal_evidence(evidence, body, batch.read_json(evidence / "body_corpus_manifest.json"),
        batch.read_json(evidence / "body_batch_receipt.json"))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_FAILURE_DIAGNOSTICS_INVALID"):
        owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION, expected_run_id=RUN_ID)


@pytest.mark.parametrize("multi_source", [False, True])
def test_terminal_rejects_diagnostic_text_with_resealed_artifact_hashes(monkeypatch, tmp_path, multi_source):
    evidence, catalog, _, _ = _capture_fixture(tmp_path, monkeypatch, multi_source=multi_source)
    body = batch.read_json(evidence / "body_corpus.json")
    manifest = batch.read_json(evidence / "body_corpus_manifest.json")
    row = body["rows"][0]
    original_path = evidence / "body_batch" / "bodies" / f"{FAILED}.json"
    original = batch.read_json(original_path)
    page = original["content_api_pages"][0]
    page["text"] = "Rewritten diagnostic text absent from source bytes"
    page["text_sha256"] = batch.digest(page["text"].encode())
    row["diagnostic_pages"] = original["content_api_pages"]
    artifact_sha = batch.atomic_json(original_path, original)
    row["capture_receipt_sha256"] = artifact_sha
    manifest["article_receipts"][0]["body_file_sha256"] = artifact_sha
    _reseal_evidence(evidence, body, manifest, batch.read_json(evidence / "body_batch_receipt.json"))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_FAILURE_DIAGNOSTIC_SOURCE_INVALID"):
        owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION, expected_run_id=RUN_ID)


@pytest.mark.parametrize("page_failure", [False, True])
def test_official_physical_coverage_reaches_terminal_and_analysis_contracts(monkeypatch, tmp_path, page_failure):
    if page_failure:
        _fail_physical_page_two(monkeypatch)
    evidence, catalog, _, _ = _capture_fixture(tmp_path, monkeypatch,
        multi_source=True, hkex_pdf=pdf_bytes(pages=3))
    terminal = owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION,
        expected_run_id=RUN_ID)
    body = batch.read_json(evidence / "body_corpus.json")
    variant = body["source_variants"][0]
    from v4.manager_research.announcement_analysis import _verify_hkex_variant_body
    _verify_hkex_variant_body(variant, PUBLICATION)
    if page_failure:
        assert variant["body_status"] == "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
        assert variant["pages"] == [] and len(variant["diagnostic_pages"]) == 3
        assert [page["page_index"] for page in variant["diagnostic_pages"]] == [1, 2, 3]
        assert [page["page_total"] for page in variant["diagnostic_pages"]] == [3, 3, 3]
        assert variant["diagnostic_pages"][1]["extraction_status"] == "EXTRACTION_FAILED"
        assert variant["diagnostic_pages"][1]["error_code"] == "PDF_PAGE_EXTRACTION_FAILED"
        assert terminal["hkex_body_coverage_status"] == "PARTIAL"
    else:
        assert variant["body_status"] == "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
        assert len(variant["pages"]) == 3
        assert terminal["hkex_body_coverage_status"] == "COMPLETE"


def test_terminal_rejects_legacy_renumbered_complete_claim(monkeypatch, tmp_path):
    _fail_physical_page_two(monkeypatch)
    evidence, catalog, _, _ = _capture_fixture(tmp_path, monkeypatch,
        multi_source=True, hkex_pdf=pdf_bytes(pages=3))
    body = batch.read_json(evidence / "body_corpus.json")
    manifest = batch.read_json(evidence / "body_corpus_manifest.json")
    receipt = batch.read_json(evidence / "body_batch_receipt.json")
    variant = body["source_variants"][0]
    retained = [p for p in variant["diagnostic_pages"] if p["text"]]
    pages = [{key: value for key, value in p.items() if key not in ("extraction_status", "error_code")}
        for p in retained]
    for index, page in enumerate(pages, 1):
        page.update(page_index=index, page_total=2)
    text = "\n\n".join(p["text"] for p in pages)
    variant.update(body_status="COMPLETE_HKEX_OFFICIAL_PDF_BODY", pages=pages,
        diagnostic_pages=[], body_text=text, body_text_sha256=batch.digest(text.encode()))
    original_path = evidence / "body_batch" / variant["body_artifact"]
    original = batch.read_json(original_path)
    original.update({key: variant[key] for key in ("body_status", "pages", "body_text", "body_text_sha256")})
    variant["body_artifact_sha256"] = batch.atomic_json(original_path, original)
    manifest["hkex_official_supplement"]["body_variants"][0].update(
        body_status=variant["body_status"], body_artifact_sha256=variant["body_artifact_sha256"])
    for supplement in (manifest["hkex_official_supplement"], receipt["hkex_official_supplement"]):
        supplement["body_status_counts"] = {variant["body_status"]: 1}
    receipt["hkex_official_supplement"]["body_coverage_status"] = "COMPLETE"
    _reseal_evidence(evidence, body, manifest, receipt)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_HKEX_PDF_COVERAGE_INVALID"):
        owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION, expected_run_id=RUN_ID)


@pytest.mark.parametrize("tamper", ["clear", "remove_failed_page", "rewrite"])
def test_task3_r1_rejects_resealed_hkex_failed_diagnostics(monkeypatch, tmp_path, tamper):
    _fail_physical_page_two(monkeypatch)
    raw_pdf = pdf_bytes(pages=3)
    expected_pdf_sha = "8ff9c3f3045160a3fc47dff1b8b9cc81e600465715292e7adcf37f1ecab89479"
    assert batch.digest(raw_pdf) == expected_pdf_sha
    evidence, catalog, _, _ = _capture_fixture(tmp_path, monkeypatch,
        multi_source=True, hkex_pdf=raw_pdf)
    body = batch.read_json(evidence / "body_corpus.json")
    manifest = batch.read_json(evidence / "body_corpus_manifest.json")
    receipt = batch.read_json(evidence / "body_batch_receipt.json")
    variant = body["source_variants"][0]
    assert variant["body_status"] == "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
    assert variant["pages"] == [] and variant["body_text"] is None
    assert variant["body_source_ref"]["body_sha256"] == expected_pdf_sha
    original_path = evidence / "body_batch" / variant["body_artifact"]
    original = batch.read_json(original_path)
    diagnostics = original["pages"]
    assert len(diagnostics) == 3 and diagnostics[1]["extraction_status"] == "EXTRACTION_FAILED"
    if tamper == "clear":
        diagnostics = []
    elif tamper == "remove_failed_page":
        diagnostics = [diagnostics[0], diagnostics[2]]
    else:
        diagnostics[0]["text"] = "Rewritten HKEX diagnostics absent from the stored PDF"
        diagnostics[0]["text_sha256"] = batch.digest(diagnostics[0]["text"].encode())
        diagnostics[1]["extraction_status"] = "EMPTY_TEXT"
        diagnostics[1]["error_code"] = "PDF_PAGE_TEXT_EMPTY"
    original["pages"] = diagnostics
    variant["diagnostic_pages"] = diagnostics
    variant["body_artifact_sha256"] = batch.atomic_json(original_path, original)
    manifest["hkex_official_supplement"]["body_variants"][0]["body_artifact_sha256"] = variant["body_artifact_sha256"]
    _reseal_evidence(evidence, body, manifest, receipt)
    # All artifact/manifest/corpus/batch/capture SHA bindings agree; only the
    # stored PDF can establish that the retained physical diagnostics are false.
    api = batch.imports()
    store = MaterialStore(evidence.parent.parent.parent / "materials")
    assert batch.digest(api["read_response"](store, variant["body_source_ref"])) == expected_pdf_sha
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_HKEX_FAILURE_DIAGNOSTICS_INVALID"):
        owner.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION,
            expected_run_id=RUN_ID)
