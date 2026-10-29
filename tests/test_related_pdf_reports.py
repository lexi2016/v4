from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.research_lane_router import create_research_lane_router
from domains.related_pdf_reports import read_related_pdf_reports


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

