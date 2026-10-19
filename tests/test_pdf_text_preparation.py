from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure import pdf_research, pdf_text_preparation as preparation
from ops import run_pdf_research_batch as batch


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _documents(count: int = 2209, *, page_count: int = 1) -> list[dict[str, object]]:
    return [
        {
            "document_id": f"{index:064x}",
            "pdf_sha256": f"{index:064x}",
            "local_pdf_path": f"/synthetic/{index}.pdf",
            "pdf_bytes": 123,
            "page_count": page_count,
        }
        for index in range(1, count + 1)
    ]


def _install_parent(monkeypatch: pytest.MonkeyPatch, documents: list[dict[str, object]]) -> str:
    parent_sha = "e" * 64
    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", parent_sha)
    monkeypatch.setattr(
        batch,
        "load_manifest",
        lambda _path: ({"schema": "test-frozen-inventory"}, parent_sha, documents),
    )
    monkeypatch.setattr(batch, "_candidate_page_count", lambda document: document.get("page_count"))
    monkeypatch.setattr(preparation, "_find_prior_successes", lambda *_args, **_kwargs: [])
    return parent_sha


def _page(number: int, total: int, text: str) -> pdf_research.PageText:
    return pdf_research.PageText(
        page_number=number,
        page_total=total,
        text=text,
        status="NATIVE_TEXT",
        text_sha256=_sha(text.encode("utf-8")),
        extraction_method="pypdf-6.10.0-native",
    )


def _good_source_row(page: pdf_research.PageText) -> dict[str, object]:
    return {
        "page_number": page.page_number,
        "selected": "PINNED_PYPDF_NATIVE",
        "preparation_gate": "READY",
        "preparation_quality": preparation.assess_text_quality(page.text),
        "page_status": page.status,
        "extraction_method": page.extraction_method,
    }


def _good_source(pages: list[pdf_research.PageText]) -> dict[str, object]:
    return {
        "page_count": len(pages),
        "page_extraction_status": "COMPLETE",
        "all_pages_nonempty": True,
        "selected_pages_complete": True,
        "source_repair_status": "NOT_REQUIRED",
        "source_page_text_sha256": _sha("".join(page.text for page in pages).encode("utf-8")),
        "page_extraction_sources": [_good_source_row(page) for page in pages],
        "source_text_acceptance": {"semantic_source_acceptance_status": "SOURCE_REVIEW_PENDING", "unreviewed_ocr_pages": []},
    }


def test_repeated_short_watermark_pages_need_context_and_distinct_cache_can_replace() -> None:
    watermark = "本报告仅供客户内部研究参考，请勿外传"  # short, repeated page furniture
    pages = [_page(number, 5, watermark) for number in range(1, 6)]
    assessments = preparation.assess_document_pages(pages)

    assert all(row["repeated_short_page"] is True for row in assessments.values())
    assert all(row["needs_context"] is True for row in assessments.values())
    native_quality = assessments[1]
    cached_text = "公司主营业务和行业变化：" + "收入增长、市场份额改善，" * 50
    cached_quality = preparation.assess_text_quality(cached_text)
    assert cached_quality["status"] == "PASS"
    assert preparation.cached_text_replaces_native(
        watermark,
        cached_text,
        native_assessment=native_quality,
        cached_assessment=cached_quality,
    ) is True
    assert preparation.cached_text_replaces_native(
        cached_text,
        cached_text + "補充文字" * 30,
        native_assessment=cached_quality,
        cached_assessment=preparation.assess_text_quality(cached_text + "補充文字" * 30),
    ) is False


def test_quality_qualified_cache_replaces_repeated_watermark_without_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "watermarked.pdf"
    pdf_raw = b"%PDF-1.4\nsynthetic watermark fixture\n"
    pdf_path.write_bytes(pdf_raw)
    cache_path = tmp_path / "cache.json"
    cache_raw = b'{"pages": []}\n'
    cache_path.write_bytes(cache_raw)
    watermark = "本报告仅供客户内部研究参考，请勿外传"
    native_pages = [_page(number, 2, watermark) for number in (1, 2)]
    cached_pages = [
        pdf_research.PageText(
            number,
            2,
            "公司主营业务和行业变化：" + f"第{number}页收入增长、市场份额改善。" * 30,
            "OCR_OK",
            None,
            "macOS Vision cache",
        )
        for number in (1, 2)
    ]
    monkeypatch.setattr(pdf_research, "_validate_pdf_path", lambda _path: pdf_path)
    monkeypatch.setattr(pdf_research, "extract_native_pdf_pages", lambda *_args: (native_pages, "COMPLETE"))
    monkeypatch.setattr(pdf_research, "load_page_cache", lambda **_kwargs: (cached_pages, {"status": "VALIDATED_CACHE"}))
    monkeypatch.setattr(
        batch,
        "_page_geometry",
        lambda *_args: [
            {"width_points": 600.0, "height_points": 800.0, "rotation_degrees": 0.0},
            {"width_points": 600.0, "height_points": 800.0, "rotation_degrees": 0.0},
        ],
    )
    monkeypatch.setattr(
        preparation,
        "inspect_page_images",
        lambda _path, *, page_numbers, **_kwargs: (pytest.fail("cache replacement needs no image probe") if page_numbers else {}),
    )
    monkeypatch.setattr(batch, "_perform_page_ocr", lambda *_args: pytest.fail("usable cache must avoid OCR"))
    document = {
        "document_id": _sha(pdf_raw),
        "pdf_sha256": _sha(pdf_raw),
        "pdf_bytes": len(pdf_raw),
        "local_pdf_path": str(pdf_path),
        "page_count": 2,
        "cache_candidates": [
            {
                "path": str(cache_path),
                "sha256": _sha(cache_raw),
                "page_count": 2,
                "coverage_status": "COMPLETE",
            }
        ],
    }

    pages, source = batch._load_pages(document, preparation_mode=True, repair_budget={"remaining": 2})

    assert [row["selected"] for row in source["page_extraction_sources"]] == [
        "EXISTING_CACHE_QUALITY_REPLACEMENT",
        "EXISTING_CACHE_QUALITY_REPLACEMENT",
    ]
    assert all(page.text.startswith("公司主营业务和行业变化") for page in pages)
    assert source["ocr_invoked"] is False


def test_prepare_only_has_no_model_binding_and_partial_scope_cannot_open_model_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    documents = _documents()
    parent_sha = _install_parent(monkeypatch, documents)
    document = documents[0]
    page = _page(1, 1, "公司主营业务和行业变化：" + "收入增长、市场份额改善，" * 40)
    source = _good_source([page])

    def fake_load_pages(_document, *, page_callback, **_kwargs):
        row = source["page_extraction_sources"][0]
        page_callback(page, row)
        return [page], source

    monkeypatch.setattr(batch, "_load_pages", fake_load_pages)
    for name in ("require_runtime_python", "build_request_material", "request_document_analysis"):
        monkeypatch.setattr(batch.local_model, name, lambda *_args, **_kwargs: pytest.fail(f"model path called: {name}"))

    run_root = tmp_path / "prepared"
    original_prepare_only = preparation.prepare_only
    monkeypatch.setattr(
        preparation,
        "prepare_only",
        lambda selected_batch, **kwargs: original_prepare_only(
            selected_batch,
            prepared_root=run_root,
            **kwargs,
        ),
    )
    exit_code = batch.main(
        [
            "--manifest",
            str(tmp_path / "parent.json"),
            "--prepare-text-only",
            "--prepare-run-id",
            "partial-quality-canary",
            "--document-id",
            str(document["document_id"]),
        ]
    )
    # The CLI writes beneath its configured PREPARED_ROOT; redirect it to the test root.
    # Re-run directly against the same deterministic implementation with an isolated root.
    captured = capsys.readouterr()
    assert exit_code == 0
    cli_result = json.loads(captured.out.strip())
    assert cli_result["status"] == "PARTIAL_SCOPE_COMPLETE"
    assert cli_result["model_requests"] == 0
    assert cli_result["full_manifest_created"] is False

    # An explicit small selection is never a full-cohort model input, even when complete.
    partial = cli_result
    assert partial["status"] == "PARTIAL_SCOPE_COMPLETE"
    assert partial["pending_full_cohort"] == 2208
    assert partial["prepared_text_manifest_path"] is None

    progress_path = Path(partial["progress_path"])
    with pytest.raises(preparation.PreparationError, match="PREPARED_MANIFEST_NOT_FULLY_TERMINAL"):
        preparation.verify_frozen_manifest(
            batch,
            progress_path,
            expected_sha256=str(partial["progress_sha256"]),
            expected_parent_sha256=parent_sha,
        )

    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: pytest.fail("partial stage reached runtime"))
    with pytest.raises(batch.BatchError, match="PREPARED_MANIFEST_NOT_FULLY_TERMINAL"):
        batch.run_batch(
            tmp_path / "parent.json",
            prepared_text_manifest_path=progress_path,
            prepared_text_manifest_sha256=str(partial["progress_sha256"]),
        )


def test_interrupted_preparation_resumes_from_existing_page_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = _documents(page_count=2)
    _install_parent(monkeypatch, documents)
    document = documents[0]
    pages = [
        _page(1, 2, "公司主营业务和行业变化：" + "第一页面，行业景气提升。" * 30),
        _page(2, 2, "公司风险及经营进展：" + "第二页面，订单增长。" * 30),
    ]
    calls: list[tuple[int, ...]] = []

    def fake_load_pages(_document, *, resume_pages, page_callback, **_kwargs):
        calls.append(tuple(sorted(resume_pages)))
        if not calls[-1]:
            page_callback(pages[0], _good_source_row(pages[0]))
            raise KeyboardInterrupt
        page_callback(pages[1], _good_source_row(pages[1]))
        return pages, _good_source(pages)

    monkeypatch.setattr(batch, "_load_pages", fake_load_pages)
    prepared_root = tmp_path / "prepared"
    with pytest.raises(KeyboardInterrupt):
        preparation.prepare_only(
            batch,
            manifest_path=tmp_path / "parent.json",
            run_id="resume-after-interrupt",
            document_ids=[str(document["document_id"])],
            prepared_root=prepared_root,
        )

    result = preparation.prepare_only(
        batch,
        manifest_path=tmp_path / "parent.json",
        run_id="resume-after-interrupt",
        document_ids=[str(document["document_id"])],
        prepared_root=prepared_root,
    )

    assert calls == [(), (1,)]
    assert result["status"] == "PARTIAL_SCOPE_COMPLETE"
    checkpoints = sorted((prepared_root / "resume-after-interrupt" / "documents" / str(document["document_id"]) / "pages").glob("page-*.json"))
    assert [path.name for path in checkpoints] == ["page-0001.json", "page-0002.json"]


def test_one_document_failure_is_recorded_and_next_selected_document_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = _documents()
    _install_parent(monkeypatch, documents)
    selected = [documents[0], documents[1]]
    good_page = _page(1, 1, "公司主营业务和行业变化：" + "收入增长，现金流改善。" * 40)
    calls: list[str] = []

    def fake_load_pages(document, *, page_callback, **_kwargs):
        document_id = str(document["document_id"])
        calls.append(document_id)
        if document_id == str(selected[0]["document_id"]):
            raise batch.BatchError("OCR_RECOGNITION_FAILED")
        source = _good_source([good_page])
        page_callback(good_page, source["page_extraction_sources"][0])
        return [good_page], source

    monkeypatch.setattr(batch, "_load_pages", fake_load_pages)
    result = preparation.prepare_only(
        batch,
        manifest_path=tmp_path / "parent.json",
        run_id="document-failure-isolated",
        document_ids=[str(row["document_id"]) for row in selected],
        prepared_root=tmp_path / "prepared",
    )

    assert calls == [str(row["document_id"]) for row in selected]
    assert result["status"] == "PARTIAL_SCOPE_COMPLETE"
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    statuses = {row["document_id"]: row["status"] for row in progress["documents"]}
    assert statuses[str(selected[0]["document_id"])] == "FAILED"
    assert statuses[str(selected[1]["document_id"])] == "READY"
    assert progress["model_requests"] == 0


def test_missing_page_text_is_quarantined_and_cannot_be_loaded_for_model_use() -> None:
    document = {
        "document_id": "1" * 64,
        "pdf_sha256": "1" * 64,
        "local_pdf_path": "/synthetic/1.pdf",
        "pdf_bytes": 123,
    }
    blank = pdf_research.PageText(1, 1, "", "TEXT_UNAVAILABLE", _sha(b""), None)
    checkpoint = preparation._page_checkpoint_value(
        run_id="missing-page-text",
        parent_sha256="e" * 64,
        document=document,
        page=blank,
        source_row={
            "page_number": 1,
            "selected": "TEXT_UNAVAILABLE",
            "preparation_gate": "QUARANTINED",
            "preparation_failure_code": "PAGE_TEXT_UNAVAILABLE",
            "preparation_quality": preparation.assess_text_quality(""),
        },
        extractor_sha256="f" * 64,
    )

    assert checkpoint["status"] == "QUARANTINED"
    assert checkpoint["text_sha256"] == _sha(b"")
    with pytest.raises(preparation.PreparationError, match="PREPARED_DOCUMENT_NOT_READY"):
        preparation.pages_from_frozen_manifest(
            {
                "manifest_sha256": "a" * 64,
                "documents": {
                    str(document["document_id"]): {
                        "manifest_row": {"status": "QUARANTINED"},
                    }
                },
            },
            str(document["document_id"]),
        )


def test_prepared_gate_rejects_partial_terminal_counts_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = _documents()
    _install_parent(monkeypatch, documents)
    partial = {
        "schema": preparation.MANIFEST_SCHEMA,
        "status": "FROZEN_COMPLETE",
        "run_id": "forged-partial",
        "parent_manifest_path": str(tmp_path / "parent.json"),
        "parent_manifest_sha256": "e" * 64,
        "parent_document_count": 2209,
        "extractor_identity_sha256": "f" * 64,
        "full_cohort": False,
        "counts": {"total": 1, "ready": 1, "quarantined": 0, "failed": 0, "pending": 0},
        "documents": [],
        "model_requests": 0,
        "model_stage": "NOT_RUN",
    }
    path = tmp_path / "forged-manifest.json"
    raw = preparation.canonical_json(partial) + b"\n"
    path.write_bytes(raw)
    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: pytest.fail("invalid gate reached runtime"))

    with pytest.raises(batch.BatchError, match="PREPARED_MANIFEST_NOT_FULLY_TERMINAL"):
        batch.run_batch(
            tmp_path / "parent.json",
            prepared_text_manifest_path=path,
            prepared_text_manifest_sha256=_sha(raw),
        )
