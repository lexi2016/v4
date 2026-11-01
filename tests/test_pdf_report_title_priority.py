"""Bounded regression coverage for ordering the owner's indexed PDF candidates."""
import base64
from collections import defaultdict

import pytest

from domains.related_pdf_cursor import CursorStore
from domains.related_pdf_reports import read_related_pdf_reports
from infrastructure import zsxq_pdf_ingestion as owner
from infrastructure import zsxq_pdf_search_index as search
from infrastructure.data_store import NativeDataStore


@pytest.fixture
def indexed_documents(tmp_path, monkeypatch):
    """Two older exact metadata hits share a PDF; newer Bloom hits are noise."""
    records = [
        ("a", "20261023", "华泰-钧达股份(002865).pdf", "研究", "b"),
        ("b", "20261024", "华泰-钧达股份(002865).pdf", "研究", "b"),
        ("f", "20261027", "ordinary.pdf", "研究", "f"),
        ("e", "20261027", "fake-1002865x.pdf", "研究", "e"),
        ("d", "20261027", "short-HK-02-AI-12元-000001.SZ.pdf", "研究", "d"),
        ("c", "20261027", "ordinary-c.pdf", "研究", "c"),
        ("9", "20261026", "ordinary-9.pdf", "金鹰纪要", "9"),
    ]
    index = {"documents": {}, "sources": {}}
    for digit, day, filename, title, digest in records:
        doc_id, run = digit * 64, f"run_{digit}"
        source = {"document_key": doc_id, "trade_date": day, "source_run_id": run,
                  "original_filename": filename, "topic_title": title}
        artifact = {"status": "READY", "pdf_size": 100}
        index["documents"][doc_id] = {"source": source, "engine_runs": {"1" * 64: artifact}}
        index["sources"][run] = {}

    days = defaultdict(dict)
    for digit, day, filename, title, digest in records:
        doc_id = digit * 64
        fingerprint, _, _ = search._fingerprint(index, doc_id)
        # The contiguous code ensures a Bloom candidate but is not itself
        # evidence returned by the fake owner detail for noise records.
        ocr = "002865 ordinary OCR" + (" 理邦仪器" if digit == "c" else "")
        bloom = search._text_bits([filename, title, ocr])
        days[day][doc_id] = {
            "fingerprint": fingerprint,
            "verified_pdf_sha256": digest * 64,
            "verified_pdf_size": 100,
            "verified_pages_size": 50,
            "receipt_sha256": digit * 64,
            "page_count": 1,
            "bloom": base64.b64encode(bloom).decode("ascii"),
        }
    store = NativeDataStore(tmp_path)
    for day, entries in days.items():
        search._write_day(store, {"schema_version": search.SCHEMA, "research_date": day,
                                  "entries": entries, "last_update_status": "READY"})
    monkeypatch.setattr(owner, "_read_index", lambda _store: index)
    monkeypatch.setattr(owner, "read_pdf_index_scope",
                        lambda _root: {"gaps": [], "source_bindings": {}}, raising=False)
    return tmp_path, index


def test_exact_filename_priority_preserves_stable_order_and_ignores_short_noise(indexed_documents):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["002865", "钧达股份", "HK", "02", "AI"]})
    assert [row["document_id"][0] for row in result["candidates"]] == ["b", "a", "f", "e", "d", "c", "9"]


def test_no_full_metadata_match_keeps_original_date_and_id_order(indexed_documents):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["02", "HK", "AI", "12元", "000001.SZ"]})
    assert [row["document_id"][0] for row in result["candidates"]] == ["f", "e", "d", "c", "9", "b", "a"]


def test_name_bloom_priority_follows_exact_metadata_without_claiming_a_match(indexed_documents):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["002865", "理邦仪器"]})
    assert [row["document_id"][0] for row in result["candidates"]] == ["b", "a", "c", "f", "e", "d", "9"]


def test_code_only_query_has_no_name_bloom_priority(indexed_documents):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["002865"]})
    assert [row["document_id"][0] for row in result["candidates"]] == ["b", "a", "f", "e", "d", "c", "9"]


def test_exact_topic_title_accepts_two_character_chinese_name(indexed_documents):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["002865", "金鹰"]})
    assert [row["document_id"][0] for row in result["candidates"]] == ["9", "b", "a", "f", "e", "d", "c"]


def test_checkpoint_invalidates_a_cursor_from_the_old_order(indexed_documents, monkeypatch):
    root, _ = indexed_documents
    result = search.query(root, {"A.002865": ["002865", "钧达股份"]})
    assert result["checkpoint_sha256"] == search.query(root, {})["checkpoint_sha256"]
    checkpoint_inputs = {
        "ledgers": result["day_sha256"], "inventory": result["inventory_sha256"],
        "source_bindings": result["source_bindings_sha256"],
    }
    cursors = CursorStore()
    for old_inputs in (checkpoint_inputs, {**checkpoint_inputs, "candidate_order": "EXACT_SOURCE_TERM_V1"}):
        old_cursor = cursors.issue(search._sha(search._canonical(old_inputs)), "fixture-signature", 1, ())
        with pytest.raises(ValueError, match="SEARCH_CURSOR_STALE"):
            cursors.resolve(old_cursor, result["checkpoint_sha256"], "fixture-signature", len(result["candidates"]))
    monkeypatch.setattr(search, "METADATA_PRIORITY_SORT_VERSION", "future-test-order")
    changed = search.query(root, {"A.002865": ["002865", "钧达股份"]})
    assert changed["checkpoint_sha256"] != result["checkpoint_sha256"]


def test_prioritized_candidates_still_pass_owner_verification_and_pdf_dedup(indexed_documents):
    root, index = indexed_documents

    class Reader:
        def query_pdf_search_index(self, data_root, terms):
            return search.query(data_root, terms)

        def read_pdf_document_detail(self, _root, doc_id, day):
            source = index["documents"][doc_id]["source"]
            pdf_sha = "b" * 64 if doc_id[0] in {"a", "b"} else doc_id
            return {"schema_version": "v4.zsxq_pdf_document_detail.v1", "status": "READY",
                    "document_id": doc_id, "research_date": day, "source": source,
                    "receipt": {"integrity": "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED",
                                "verified_pdf_sha256": pdf_sha, "sha256": doc_id},
                    "processing": {"verified_pdf_size": 100, "verified_pages_size": 50},
                    "pages": [{"page_number": 1, "text": "unrelated"}],
                    "research_only": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False}

    result = read_related_pdf_reports(root, None, identity_date="20261030", symbols=["002865.SZ"],
                                     hints=["002865.SZ:钧达股份"], max_documents=5, reader=Reader(),
                                     identity_reader=lambda *_: {"status": "CANNOT_CONFIRM", "name": None,
                                                                 "reason": "EXACT_DATE_IDENTITY_NOT_AVAILABLE"})
    reports = result["stocks"][0]["reports"]
    assert len(reports) == 1
    assert reports[0]["verified_pdf_sha256"] == "b" * 64
    assert {source["document_id"][0] for source in reports[0]["sources"]} == {"a", "b"}
    assert all(source["text_match_in_source"] for source in reports[0]["sources"])
    assert result["coverage"]["pagination_required"]
