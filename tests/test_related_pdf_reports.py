from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.research_lane_router import create_research_lane_router
from domains.related_pdf_reports import read_related_pdf_reports
from infrastructure import zsxq_pdf_ingestion as owner
from infrastructure.data_store import NativeDataStore


def _stored_owner_fixture(root):
    """Real owner artifact verification; isolate the unrelated source resolver."""
    day, run, engine = "20261015", "fixture_run", "e" * 64
    store = NativeDataStore(root)
    index = {"documents": {}, "sources": {}}
    candidates, paths = [], {}
    for digit in ("a", "b"):
        doc_id = digit * 64
        prefix = f"external_sources/zsxq_hourly/pdfproc_{run}_{'c' * 12}_{engine[:12]}"
        pdf_path = f"{prefix}/pdfs/{doc_id}.pdf"
        pages_path = f"{prefix}/pages/{doc_id}_{engine[:16]}.json"
        receipt_path = f"{prefix}/receipts/{doc_id}_{engine[:16]}.json"
        pdf = b"%PDF-1.7\n" + digit.encode() + b"\n%%EOF\n"
        pages = [{"page_number": 1, "status": "OCR_OK", "method": "fixture", "text": "600025.SH 原文证据"}]
        pages_raw = json.dumps(pages, ensure_ascii=False).encode()
        source = {"document_key": doc_id, "trade_date": day, "source_run_id": run,
                  "topic_title": "研究原文", "original_filename": digit + ".pdf",
                  "pdf_published_at": None, "late_processing": True,
                  "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT"}
        artifact = {"status": "READY", "pdf_path": pdf_path, "pages_path": pages_path,
                    "receipt_path": receipt_path, "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "pdf_size": len(pdf), "pages_file_sha256": hashlib.sha256(pages_raw).hexdigest(), "page_count": 1}
        receipt = {**source, **artifact, "schema_version": "v4.zsxq_pdf_document_receipt.v1",
                   "engine_identity": engine, "real_pdf_path": str(root / pdf_path),
                   "pages": [{"page_number": 1, "status": "OCR_OK", "method": "fixture",
                              "text_sha256": hashlib.sha256(pages[0]["text"].encode()).hexdigest()}],
                   "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        receipt_raw = json.dumps(receipt, ensure_ascii=False).encode()
        for path, raw in ((pdf_path, pdf), (pages_path, pages_raw), (receipt_path, receipt_raw)):
            owner._store_io(store).write_bytes(path, raw)
        index["documents"][doc_id] = {"source": source, "engine_runs": {engine: artifact}}
        paths[doc_id] = {"pdf": pdf_path, "pages": pages_path, "receipt": receipt_path}
        candidates.append({"document_id": doc_id, "research_date": day, "verified_pdf_sha256": artifact["pdf_sha256"],
                           "verified_pdf_size": len(pdf), "verified_pages_size": len(pages_raw)})

    def source_row(_store, _index, doc_id):
        row = index["documents"][doc_id]
        return row["source"], row

    class Reader:
        def query_pdf_search_index(self, _root, _terms):
            return {"status": "READY", "candidates": candidates, "checkpoint_sha256": "f" * 64,
                    "coverage": {"indexed_documents": 2, "gaps": []}}

        def read_pdf_document_detail(self, _root, doc_id, research_date):
            return owner.read_pdf_document_detail(root, doc_id, research_date)

    return store, index, candidates, paths, source_row, Reader()


def _fixture_relations(root, reader, cursor=None):
    return read_related_pdf_reports(root, None, identity_date="20261029", symbols=["600025.SH"],
                                    max_documents=1, cursor=cursor, reader=reader)


class ActualOwnerMetadataContractTests(unittest.TestCase):
    def test_unverified_pdf_does_not_claim_verified_pdf_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            store, index, candidates, _, source_row, _ = _stored_owner_fixture(root)
            with patch.object(owner, "_source_row_for_document", side_effect=source_row):
                detail = owner._verified_document_detail(store, index, candidates[0]["document_id"], verify_pdf=False)
            self.assertIsNone(detail["receipt"]["verified_pdf_sha256"])
            self.assertIsNone(detail["processing"]["verified_pdf_size"])
            self.assertEqual(detail["processing"]["verified_pages_size"], candidates[0]["verified_pages_size"])
            self.assertEqual(detail["receipt"]["integrity"], "SOURCE_AND_PAGE_HASHES_VERIFIED")

    def test_real_verifier_metadata_reaches_relations_and_cursor_prior_revalidation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _, index, candidates, _, source_row, reader = _stored_owner_fixture(root)
            with patch.object(owner, "_read_index", return_value=index), patch.object(owner, "_source_row_for_document", side_effect=source_row):
                detail = reader.read_pdf_document_detail(root, candidates[0]["document_id"], "20261015")
                self.assertEqual(detail["receipt"].get("verified_pdf_sha256"), candidates[0]["verified_pdf_sha256"])
                self.assertEqual(detail["processing"].get("verified_pdf_size"), candidates[0]["verified_pdf_size"])
                self.assertEqual(detail["processing"].get("verified_pages_size"), candidates[0]["verified_pages_size"])
                first = _fixture_relations(root, reader)
                self.assertEqual(first["coverage"]["verified_documents"], 1)
                self.assertEqual(len(first["stocks"][0]["reports"]), 1)
                self.assertTrue(first["next_cursor"])
                second = _fixture_relations(root, reader, first["next_cursor"])
                self.assertEqual(second["coverage"]["verified_documents"], 1)
                self.assertEqual(second["coverage"]["prior_revalidated"], 1)
                self.assertEqual(len(second["stocks"][0]["reports"]), 1)

    def test_tampered_pdf_pages_and_source_never_emit_reports(self):
        for kind in ("pdf", "pages", "source"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                store, index, candidates, paths, source_row, reader = _stored_owner_fixture(root)
                if kind in ("pdf", "pages"):
                    path = paths[candidates[0]["document_id"]][kind]
                    raw = owner._store_io(store).read_bytes(path)
                    owner._store_io(store).write_bytes(path, raw.replace(b"600025", b"000410") if kind == "pages" else b"X" + raw[1:])
                else:
                    source_row = lambda *_: (_ for _ in ()).throw(owner.ZsxqPdfError("SOURCE_INPUT_SHA256_MISMATCH"))
                with patch.object(owner, "_read_index", return_value=index), patch.object(owner, "_source_row_for_document", side_effect=source_row):
                    result = _fixture_relations(root, reader)
                self.assertEqual(result["coverage"]["verified_documents"], 0)
                self.assertEqual(result["stocks"][0]["reports"], [])

    def test_mismatched_index_metadata_never_emits_reports(self):
        for field in ("verified_pdf_sha256", "verified_pdf_size", "verified_pages_size"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                _, index, candidates, _, source_row, reader = _stored_owner_fixture(root)
                candidates[0][field] = "0" * 64 if field.endswith("sha256") else candidates[0][field] + 1
                with patch.object(owner, "_read_index", return_value=index), patch.object(owner, "_source_row_for_document", side_effect=source_row):
                    result = _fixture_relations(root, reader)
                self.assertEqual(result["coverage"]["verified_documents"], 0)
                self.assertEqual(result["stocks"][0]["reports"], [])

    def test_cursor_rejects_prior_artifact_or_source_drift(self):
        for kind in ("pdf", "pages", "source", "receipt"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                store, index, candidates, paths, source_row, reader = _stored_owner_fixture(root)
                with patch.object(owner, "_read_index", return_value=index), patch.object(owner, "_source_row_for_document", side_effect=source_row):
                    first = _fixture_relations(root, reader)
                    self.assertTrue(first["next_cursor"])
                    prior_id = candidates[0]["document_id"]
                    if kind in ("pdf", "pages"):
                        path = paths[prior_id][kind]
                        raw = owner._store_io(store).read_bytes(path)
                        owner._store_io(store).write_bytes(path, b"X" + raw[1:])
                    elif kind == "receipt":
                        path = paths[prior_id]["receipt"]
                        value = json.loads(owner._store_io(store).read_bytes(path))
                        value["fixture_revision"] = 2
                        owner._store_io(store).write_bytes(path, json.dumps(value, ensure_ascii=False).encode())
                    else:
                        index["documents"][prior_id]["source"]["topic_title"] = "changed source"
                    with self.assertRaisesRegex(ValueError, "SEARCH_CURSOR_STALE"):
                        _fixture_relations(root, reader, first["next_cursor"])


class ExistingReportIndexOnlyTests(unittest.TestCase):
    def test_real_missing_derived_index_returns_before_owner_inventory_read(self):
        from infrastructure import zsxq_pdf_ingestion as owner
        from infrastructure import zsxq_pdf_search_index as search

        with tempfile.TemporaryDirectory() as td:
            for empty_directory in (False, True):
                with self.subTest(empty_directory=empty_directory):
                    if empty_directory:
                        (Path(td) / search.INDEX_ROOT / "days").mkdir(parents=True)
                    with patch.object(owner, "_read_index", side_effect=AssertionError("must not load owner inventory")), \
                         patch.object(search, "_fingerprint", side_effect=AssertionError("must not fingerprint inventory")), \
                         patch.object(owner, "read_pdf_index_scope", side_effect=AssertionError("must not enumerate owner scope")):
                        result = search.query(td, {"A.600025": ["600025"]})
                    self.assertEqual(result["status"], "NOT_MATERIALIZED")
                    self.assertEqual(result["candidates"], [])
                    self.assertEqual(result["coverage"]["dates_scanned"], [])
                    self.assertIn({"reason": "SEARCH_INDEX_NOT_MATERIALIZED"}, result["coverage"]["gaps"])

    def test_missing_search_index_does_not_scan_ingestion_index_or_open_ocr(self):
        class Reader:
            ZsxqPdfError = RuntimeError

            def query_pdf_search_index(self, root, terms):
                return {"status": "NOT_MATERIALIZED", "coverage": {"gaps": [{"reason": "SEARCH_INDEX_NOT_MATERIALIZED"}]}}

            def read_pdf_index_scope(self, root):
                raise AssertionError("GET must not enumerate the ingestion index as a fallback")

            def read_pdf_ingestion_projection(self, root, day):
                raise AssertionError("GET must not run excerpt scanning as a fallback")

            def read_pdf_document_detail(self, root, document_id, day):
                raise AssertionError("GET must not open OCR details without an indexed candidate")

        def identity_reader(root, day, symbol):
            return {"status": "CANNOT_CONFIRM", "name": None, "exchange": symbol.get("exchange"),
                    "witnesses": [], "reason": "EXACT_DATE_IDENTITY_NOT_AVAILABLE", "pit_certified": False}

        result = read_related_pdf_reports("/unused", None, identity_date="20261029", symbols=["600025.SH"],
                                          identity_reader=identity_reader, reader=Reader())
        self.assertEqual(result["status"], "NOT_MATERIALIZED")
        self.assertEqual(result["search_mode"], "NOT_MATERIALIZED")
        self.assertEqual(result["coverage"]["detail_attempts"], 0)
        self.assertEqual(result["coverage"]["dates_scanned"], [])
        self.assertEqual(result["stocks"][0]["reports"], [])
        self.assertTrue(result["research_only"])

    def test_v4_reports_endpoint_returns_not_materialized_without_index_build(self):
        with tempfile.TemporaryDirectory() as td:
            app = FastAPI()
            app.include_router(create_research_lane_router(Path(td)))
            response = TestClient(app).get(
                "/api/v4/research/pdf-relations",
                params={"identity_date": "20261029", "symbols": "600025.SH", "max_dates": 1, "max_documents": 5},
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "NOT_MATERIALIZED")
        self.assertEqual(result["search_mode"], "NOT_MATERIALIZED")
        self.assertEqual(result["coverage"]["detail_attempts"], 0)
        self.assertEqual(result["coverage"]["dates_scanned"], [])
        self.assertEqual(result["stocks"][0]["symbol"], "A.600025")
        self.assertEqual(result["stocks"][0]["reports"], [])

