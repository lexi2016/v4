from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import threading
import time

import pytest

from infrastructure import local_document_model as local_model
from infrastructure import pdf_research as pdf


def _minimal_model_output(unit: pdf.SourceUnit) -> dict:
    evidence = {"source_unit_id": unit.source_unit_id}
    subject = "Example Energy Co."
    return {
        "document_assessment": {
            "document_type": "research report",
            "scope_summary": "A synthetic source-grounded example.",
            "main_subjects": [subject],
            "unknowns": [],
        },
        "entities": [
            {
                "raw_name": subject,
                "normalized_name": None,
                "raw_code": None,
                "market_as_stated": None,
                "entity_role": "REPORT_SUBJECT",
                "relationship_basis": "Named as the report subject.",
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "facts": [
            {
                "subject_raw_name": subject,
                "claim": "The report states a synthetic forward-looking figure.",
                "indicator_or_event": "reported figure",
                "raw_value_text": "3.2%",
                "numeric_value": 3.2,
                "unit": "%",
                "currency": None,
                "period": "2026",
                "comparison_basis": None,
                "direction": "UNKNOWN",
                "claim_nature": "ANALYST_OR_REPORT_FORECAST",
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "important_changes": [
            {
                "subject_raw_name": subject,
                "change": "The report frames the 2026 figure as a forward-looking item.",
                "business_impact_path": None,
                "claim_nature": "ANALYST_OR_REPORT_FORECAST",
                "supporting_fact_indices": [0],
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "risks_and_counterevidence": [
            {
                "subject_raw_name": subject,
                "risk_or_counterevidence": "The evidence is a forecast, not a realized result.",
                "kind": "REPORTED_RISK",
                "claim_nature": "ANALYST_OR_REPORT_FORECAST",
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "research_hypotheses": [
            {
                "subject_raw_name": subject,
                "hypothesis": "The forward-looking figure may matter if later verified.",
                "causal_impact_path": None,
                "preconditions": [],
                "supporting_fact_indices": [0],
                "counter_fact_indices": [],
                "next_verification_event": "Check the reported period after publication.",
                "failure_condition": None,
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "verification_events": [
            {
                "subject_raw_name": subject,
                "event_or_metric": "reported 2026 figure",
                "timing_or_trigger": "after the report period",
                "required_verification_source": "an authoritative later report",
                "linked_hypothesis_indices": [0],
                "evidence": [dict(evidence)],
                "uncertainty_notes": [],
            }
        ],
        "unknowns": [],
    }


def test_long_text_chunking_reconstructs_exact_source_and_page_ranges() -> None:
    pages = [
        pdf.PageText(1, 3, "A" * 4500 + "Example Energy Co. reported 3.2% in 2026", "OCR_OK", None, "cached OCR"),
        pdf.PageText(2, 3, "", "BLANK", None, "cached OCR"),
        pdf.PageText(3, 3, "Z" * 5100, "NATIVE_TEXT", None, "pypdf"),
    ]
    chunks = pdf.build_source_chunks(
        "S01",
        pages,
        max_characters=4096,
        token_counter=lambda units: sum(len(unit.text) for unit in units),
        max_prompt_tokens=3000,
    )
    assert len(chunks) >= 4
    assert pdf.verify_chunk_reconstruction(pages, chunks)
    units = {unit.source_unit_id: unit for chunk in chunks for unit in chunk.units}
    target = next(unit for unit in units.values() if "3.2% in 2026" in unit.text)
    output = _minimal_model_output(target)
    validated = pdf._validate_chunk_output(
        output,
        pdf.SourceChunk("S01", 1, 1, (target,), "c" * 64),
        schema_sha256="d" * 64,
        source_pages=pages,
    )
    assert validated["facts"][0]["evidence"][0]["page_number"] == target.page_number
    assert validated["facts"][0]["evidence"][0]["page_offset_start"] == target.page_offset_start
    assert validated["facts"][0]["evidence"][0]["page_offset_end"] == target.page_offset_end
    assert validated["facts"][0]["evidence"][0]["quote"] == target.text
    broken = list(chunks)
    broken[0] = pdf.SourceChunk(
        broken[0].document_id,
        broken[0].chunk_index,
        broken[0].chunk_total,
        broken[0].units[:-1],
        broken[0].chunk_sha256,
    )
    assert not pdf.verify_chunk_reconstruction(pages, broken)


def test_default_chunking_bounds_s01_sized_aggregate_and_reconstructs_exact_text() -> None:
    page_lengths = [4013, 5911, 2538, 2312, 2549, 6038, 3590, 10687, 9155, 1299]
    pages = [
        pdf.PageText(index, len(page_lengths), chr(64 + index) * length, "NATIVE_TEXT", None, "pypdf")
        for index, length in enumerate(page_lengths, start=1)
    ]

    chunks = pdf.build_source_chunks("S01", pages)

    assert len(chunks) > 1
    assert all(sum(len(unit.text) for unit in chunk.units) <= 8_000 for chunk in chunks)
    assert pdf.verify_chunk_reconstruction(pages, chunks)


def test_oversized_source_unit_is_split_to_aggregate_limit() -> None:
    page = pdf.PageText(1, 1, "甲乙丙丁戊己庚辛壬癸" * 2_000, "NATIVE_TEXT", None, "pypdf")

    chunks = pdf.build_source_chunks(
        "S01",
        [page],
        max_characters=20_000,
        max_source_characters=8_000,
    )

    assert all(sum(len(unit.text) for unit in chunk.units) <= 8_000 for chunk in chunks)
    assert pdf.verify_chunk_reconstruction([page], chunks)


def _three_chunk_native_pages() -> tuple[list[pdf.PageText], dict[str, object]]:
    pages = [
        pdf.PageText(1, 3, "A" * 8_000, "NATIVE_TEXT", None, "pypdf"),
        pdf.PageText(2, 3, "B" * 8_000, "NATIVE_TEXT", None, "pypdf"),
        pdf.PageText(3, 3, "C" * 4_000, "NATIVE_TEXT", None, "pypdf"),
    ]
    return pages, {"page_count": len(pages), "source_page_text_sha256": "a" * 64}


def _validated_chunk_for_last_payload(queue: object, _key: str) -> dict:
    payload = queue.payloads[-1]
    return {
        "chunk_id": f"{payload['article_id']}:{payload['chunk_sha256']}",
        "chunk_index": payload["chunk_index"],
        "chunk_total": payload["chunk_total"],
        "chunk_sha256": payload["chunk_sha256"],
    }


def _empty_model_output() -> dict:
    return {
        "document_assessment": {
            "document_type": "synthetic report",
            "scope_summary": "No supported claims in this synthetic chunk.",
            "main_subjects": [],
            "unknowns": [],
        },
        "entities": [],
        "facts": [],
        "important_changes": [],
        "risks_and_counterevidence": [],
        "research_hypotheses": [],
        "verification_events": [],
        "unknowns": [],
    }


class _StoredSuccessQueue:
    def __init__(self, root: Path) -> None:
        self.state_root = root
        self.jobs_root = root / "jobs"
        self._state_lock_path = root / "locks" / "queue-state.lock"
        self.queue_id = pdf.QUEUE_ID
        self.model_id = local_model.MODEL_ID
        self.max_body_bytes = None
        self.state: dict = {"jobs": {}}
        self.payloads: list[dict] = []
        self.run_count = 0
        self.jobs_root.mkdir(parents=True)
        self._state_lock_path.parent.mkdir(parents=True)
        self._state_lock_path.touch()

    def _load_state(self) -> dict:
        return self.state

    def enqueue(self, payload: dict) -> dict:
        key, _payload_sha = pdf._queue_identity_and_payload_sha256(self, payload)
        self.payloads.append(payload)
        return {"idempotency_key": key}

    def run_next(self, executor, _validator, **_kwargs) -> dict:
        self.run_count += 1
        executor(object())
        return {"status": "SUCCEEDED"}


def _seed_accepted_chunk(queue: _StoredSuccessQueue, document: dict, chunk: pdf.SourceChunk, pages: list[pdf.PageText], binding: dict) -> dict:
    messages = pdf.build_messages(str(document["document_id"]), chunk)
    payload = pdf._queue_payload(document=document, chunk=chunk, messages=messages, binding=binding)
    key, payload_sha = pdf._queue_identity_and_payload_sha256(queue, payload)
    raw_output = _empty_model_output()
    raw_response = local_model.canonical_json(raw_output)
    schema_sha = local_model.sha256_bytes(local_model.canonical_json(pdf.V3_OUTPUT_SCHEMA))
    validated = pdf._validate_chunk_output(
        raw_output,
        chunk,
        schema_sha256=schema_sha,
        source_pages=pages,
    )
    validated_raw = local_model.canonical_json(validated)
    raw_sha = local_model.sha256_bytes(raw_response)
    validated_sha = local_model.sha256_bytes(validated_raw)
    job_dir = queue.jobs_root / key
    job_dir.mkdir()
    input_path = job_dir / "input.json"
    raw_path = job_dir / "attempt-0001.raw"
    validated_path = job_dir / "attempt-0001.validated.json"
    input_path.write_bytes(local_model.canonical_json(payload))
    raw_path.write_bytes(raw_response)
    validated_path.write_bytes(validated_raw)
    queue.state["jobs"][key] = {
        "idempotency_key": key,
        "payload_sha256": payload_sha,
        "queue_id": queue.queue_id,
        "queue_ids": [queue.queue_id],
        "model_id": queue.model_id,
        "attempt_count": 1,
        "max_attempts": 1,
        "queue_policy": {"max_attempts": 1, "max_body_bytes": None},
        "status": "SUCCEEDED",
        "input_path": str(input_path.relative_to(queue.state_root)),
        "raw_path": str(raw_path.relative_to(queue.state_root)),
        "raw_sha256": raw_sha,
        "validated_path": str(validated_path.relative_to(queue.state_root)),
        "validated_sha256": validated_sha,
        "attempts": [
            {
                "number": 1,
                "status": "SUCCEEDED",
                "consumer_queue_id": queue.queue_id,
                "raw_path": str(raw_path.relative_to(queue.state_root)),
                "raw_sha256": raw_sha,
                "validated_path": str(validated_path.relative_to(queue.state_root)),
                "validated_sha256": validated_sha,
            }
        ],
    }
    acceptance = {
        "idempotency_key": key,
        "payload_sha256": payload_sha,
        "raw_sha256": raw_sha,
        "validated_sha256": validated_sha,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "chunk_sha256": chunk.chunk_sha256,
        "request_schema_sha256": schema_sha,
        "source_sha256": payload["source_sha256"],
    }
    return acceptance


class _RequestOutcomeQueue:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.run_count = 0

    def enqueue(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"idempotency_key": f"{len(self.payloads):064x}"}

    def run_next(self, executor, _validator, **_kwargs) -> dict:
        self.run_count += 1
        try:
            executor(object())
        except RuntimeError as exc:
            return {"status": "FAILED", "last_error": {"code": str(exc)}}
        return {"status": "SUCCEEDED"}


def test_default_analyze_enforces_and_records_serialized_envelope_for_s01_size(monkeypatch) -> None:
    page_lengths = [4013, 5911, 2538, 2312, 2549, 6038, 3590, 10687, 9155, 1299]
    pages = [
        pdf.PageText(index, len(page_lengths), chr(64 + index) * length, "NATIVE_TEXT", None, "pypdf")
        for index, length in enumerate(page_lengths, start=1)
    ]
    source = {"page_count": len(pages), "source_page_text_sha256": "a" * 64}
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))

    queue = _RequestOutcomeQueue()
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        model_request=lambda **_kwargs: "offline-success-stub",
    )

    chunks = []
    for payload in queue.payloads:
        units = tuple(pdf.SourceUnit(**item) for item in payload["source_units"])
        chunk = pdf.SourceChunk("S01", payload["chunk_index"], payload["chunk_total"], units, payload["chunk_sha256"])
        chunks.append(chunk)
        messages = pdf.build_messages("S01", chunk)
        envelope = pdf.serialize_request_envelope(messages)
        assert sum(len(unit.text) for unit in units) <= pdf.MAX_SOURCE_CHARACTERS_PER_CHUNK
        assert payload["request_envelope_byte_count"] == len(envelope)
        assert payload["request_envelope_sha256"] == local_model.sha256_bytes(envelope)
        assert len(envelope) <= pdf.MAX_SERIALIZED_REQUEST_ENVELOPE_BYTES

    assert len(queue.payloads) > 1
    assert result["coverage"]["chunk_count"] == len(queue.payloads)
    assert pdf.verify_chunk_reconstruction(pages, chunks)
    execution = result["coverage"]["chunk_execution"]
    assert execution["status"] == "COMPLETE"
    assert execution["completed_chunk_count"] == execution["total_chunk_count"]
    assert execution["failed_chunk_count"] == execution["unrun_chunk_count"] == 0


def test_analyze_stops_after_first_systemic_failure_and_marks_remaining_chunks_unrun(monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    queue = _RequestOutcomeQueue()
    request_calls = 0

    def fail_systemically(**_kwargs) -> str:
        nonlocal request_calls
        request_calls += 1
        raise RuntimeError("TEST_SYSTEMIC_OFFLINE")

    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        maximum_model_calls=16,
        model_request=fail_systemically,
    )

    assert queue.run_count == request_calls == 1
    assert len(queue.payloads) == 1
    execution = result["coverage"]["chunk_execution"]
    assert result["document_status"] == "PARTIAL"
    assert result["coverage"]["full_analysis_complete"] is False
    assert execution["status"] == "STOPPED_INCOMPLETE"
    assert execution["completed_chunk_count"] == 0
    assert execution["failed_chunk_count"] == 1
    assert execution["unrun_chunk_count"] == 2
    assert execution["failed_chunk_ids"] == [execution["failed_chunks"][0]["chunk_id"]]
    assert execution["unrun_chunk_ids"] == [item["chunk_id"] for item in execution["unrun_chunks"]]
    assert all(item["status"] == "NOT_RUN" for item in execution["unrun_chunks"])
    assert execution["failed_chunks"][0]["failure_code"] == "TEST_SYSTEMIC_OFFLINE"


def test_analyze_stops_after_succeeded_outcome_without_validated_result(monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", lambda _queue, _key: None)

    class MissingValidatedQueue(_RequestOutcomeQueue):
        def run_next(self, *_args, **_kwargs) -> dict:
            self.run_count += 1
            return {"status": "SUCCEEDED"}

    queue = MissingValidatedQueue()
    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        maximum_model_calls=16,
        model_request=lambda **_kwargs: pytest.fail("fake queue must not call the model"),
    )

    execution = result["coverage"]["chunk_execution"]
    assert queue.run_count == len(queue.payloads) == 1
    assert execution["completed_chunk_count"] == 0
    assert execution["failed_chunk_count"] == 1
    assert execution["failed_chunks"][0]["status"] == "RESULT_READBACK_FAILED"
    assert execution["unrun_chunk_count"] == 2
    assert result["document_status"] == "PARTIAL"
    assert result["coverage"]["full_analysis_complete"] is False


def test_analyze_preserves_success_and_stops_after_midstream_systemic_failure(monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    queue = _RequestOutcomeQueue()
    request_calls = 0

    def fail_on_second_request(**_kwargs) -> str:
        nonlocal request_calls
        request_calls += 1
        if request_calls == 2:
            raise RuntimeError("TEST_SYSTEMIC_MEMORY_FAILURE")
        return "offline-success-stub"

    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        maximum_model_calls=16,
        model_request=fail_on_second_request,
    )

    assert queue.run_count == request_calls == 2
    assert len(queue.payloads) == 2
    execution = result["coverage"]["chunk_execution"]
    assert result["document_status"] == "PARTIAL"
    assert result["coverage"]["full_analysis_complete"] is False
    assert execution["status"] == "STOPPED_INCOMPLETE"
    assert execution["completed_chunk_count"] == 1
    assert execution["completed_chunk_ids"] == [result["chunk_results"][0]["chunk_id"]]
    assert execution["failed_chunk_count"] == 1
    assert execution["failed_chunks"][0]["failure_code"] == "TEST_SYSTEMIC_MEMORY_FAILURE"
    assert execution["unrun_chunk_count"] == 1
    assert execution["unrun_chunks"][0]["status"] == "NOT_RUN"
    assert result["chunk_results"][0]["chunk_id"] in execution["completed_chunk_ids"]


def test_analyze_preserves_completed_result_when_binding_guard_stops_before_next_enqueue(monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    queue = _RequestOutcomeQueue()
    guard_calls = 0

    def binding_guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise pdf.PdfResearchError("TEST_RUNTIME_CONFIG_DRIFT")

    request_calls = 0

    def offline_success(**_kwargs) -> str:
        nonlocal request_calls
        request_calls += 1
        return "offline-success-stub"

    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        maximum_model_calls=16,
        binding_guard=binding_guard,
        model_request=offline_success,
    )

    execution = result["coverage"]["chunk_execution"]
    assert len(queue.payloads) == queue.run_count == request_calls == 1
    assert execution["completed_chunk_count"] == 1
    assert execution["failed_chunk_count"] == 0
    assert execution["unrun_chunk_count"] == 2
    assert execution["stop_reason"] == {
        "failure_stage": "binding_guard",
        "failure_code": "TEST_RUNTIME_CONFIG_DRIFT",
        "before_chunk_id": execution["unrun_chunks"][0]["chunk_id"],
    }
    assert result["chunk_results"][0]["chunk_id"] == execution["completed_chunk_ids"][0]


def test_model_call_budget_fails_before_first_queue_mutation(monkeypatch) -> None:
    pages = [pdf.PageText(1, 1, "source text " * 2_000, "NATIVE_TEXT", None, "pypdf")]
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, {"page_count": 1}))

    class NoWriteQueue:
        def enqueue(self, _payload):
            pytest.fail("call budget must be checked before queue mutation")

    with pytest.raises(pdf.PdfResearchError, match="MODEL_CALL_BUDGET_EXCEEDED"):
        pdf.analyze_document(
            {"document_id": "S01", "pdf_sha256": "a" * 64, "page_count": 1},
            queue=NoWriteQueue(),
            binding={"configuration_sha256": "b" * 64, "request_schema_sha256": "c" * 64},
            maximum_model_calls=1,
        )


def test_legacy_model_supplied_evidence_text_and_offsets_are_rejected() -> None:
    page = pdf.PageText(1, 1, "Example Energy Co. reported 3.2% in 2026", "COMPLETE", None)
    chunk = pdf.build_source_chunks("S01", [page])[0]
    output = _minimal_model_output(chunk.units[0])
    output["facts"][0]["evidence"][0]["quote"] = "3.2 in 2026"
    output["facts"][0]["evidence"][0]["page_number"] = 1
    output["facts"][0]["evidence"][0]["unit_offset_start"] = 0
    output["facts"][0]["evidence"][0]["unit_offset_end"] = 4
    with pytest.raises(pdf.PdfResearchError, match="MODEL_OUTPUT_SCHEMA_MISMATCH"):
        pdf._validate_chunk_output(output, chunk, schema_sha256="d" * 64, source_pages=[page])


def _unit_reference_model_output(unit: pdf.SourceUnit) -> dict:
    reference = {"source_unit_id": unit.source_unit_id}
    subject = "Example Energy Co."
    return {
        "document_assessment": {
            "document_type": "research report",
            "scope_summary": "Synthetic source-grounded example.",
            "main_subjects": [subject],
            "unknowns": [],
        },
        "entities": [
            {
                "raw_name": name,
                "normalized_name": None,
                "raw_code": None,
                "market_as_stated": None,
                "entity_role": role,
                "relationship_basis": basis,
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            }
            for name, role, basis in (
                (subject, "REPORT_SUBJECT", "The document explicitly discusses this subject."),
                ("Example Components Ltd.", "SUPPLIER", "The document explicitly calls it a supplier."),
                ("Example Retail Ltd.", "CUSTOMER", "The document explicitly calls it a customer."),
                ("Research House", "AUTHOR_OR_INSTITUTION", "The document names it as publisher."),
            )
        ],
        "facts": [
            {
                "subject_raw_name": subject,
                "claim": "The report states a historical result.",
                "indicator_or_event": "reported units",
                "raw_value_text": "12",
                "numeric_value": 12,
                "unit": "units",
                "currency": None,
                "period": "FY2025",
                "comparison_basis": None,
                "direction": "UNKNOWN",
                "claim_nature": "REALIZED_ACTUAL",
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            },
            {
                "subject_raw_name": subject,
                "claim": "The report describes a current status.",
                "indicator_or_event": "current backlog",
                "raw_value_text": "6",
                "numeric_value": 6,
                "unit": "units",
                "currency": None,
                "period": "as of 2026-01",
                "comparison_basis": None,
                "direction": "UNKNOWN",
                "claim_nature": "CURRENT_STATUS_OR_OBSERVATION",
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            },
            {
                "subject_raw_name": subject,
                "claim": "The report gives a third-party target price opinion.",
                "indicator_or_event": "target price",
                "raw_value_text": "42",
                "numeric_value": 42,
                "unit": None,
                "currency": None,
                "period": None,
                "comparison_basis": None,
                "direction": "UNKNOWN",
                "claim_nature": "THIRD_PARTY_VIEW",
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            },
            {
                "subject_raw_name": subject,
                "claim": "The report contains an analyst forecast.",
                "indicator_or_event": "expected units",
                "raw_value_text": "14",
                "numeric_value": 14,
                "unit": "units",
                "currency": None,
                "period": "FY2026",
                "comparison_basis": None,
                "direction": "UNKNOWN",
                "claim_nature": "ANALYST_OR_REPORT_FORECAST",
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            },
        ],
        "important_changes": [],
        "risks_and_counterevidence": [],
        "research_hypotheses": [],
        "verification_events": [
            {
                "subject_raw_name": subject,
                "event_or_metric": "scheduled review meeting",
                "timing_or_trigger": "2027-03",
                "required_verification_source": None,
                "linked_hypothesis_indices": [],
                "evidence": [dict(reference)],
                "uncertainty_notes": [],
            }
        ],
        "unknowns": [],
    }


def test_model_evidence_references_only_source_units_and_derives_exact_quote_offsets_and_hash() -> None:
    page = pdf.PageText(
        1,
        1,
        "Example Energy Co. reported 12 units in FY2025; current backlog is 6 units as of 2026-01; target price 42; forecast 14 units in FY2026; scheduled review meeting 2027-03; supplier Example Components Ltd.; customer Example Retail Ltd.; published by Research House.",
        "NATIVE_TEXT",
        None,
        "pypdf",
    )
    chunk = pdf.build_source_chunks("SYNTH-01", [page])[0]
    output = _unit_reference_model_output(chunk.units[0])

    validated = pdf._validate_chunk_output(
        output,
        chunk,
        schema_sha256="d" * 64,
        source_pages=[page],
    )

    evidence = validated["facts"][0]["evidence"][0]
    assert set(pdf.EVIDENCE_SCHEMA["properties"]) == {"source_unit_id"}
    assert evidence["source_unit_id"] == chunk.units[0].source_unit_id
    assert evidence["page_number"] == 1
    assert evidence["page_offset_start"] == 0
    assert evidence["page_offset_end"] == len(page.text)
    assert evidence["quote"] == page.text
    assert evidence["quote_sha256"] == hashlib.sha256(page.text.encode("utf-8")).hexdigest()


def test_model_evidence_rejects_unknown_foreign_and_legacy_text_offset_references() -> None:
    page = pdf.PageText(1, 1, "Example Energy Co. reported 12 units in FY2025.", "NATIVE_TEXT", None, "pypdf")
    other_page = pdf.PageText(2, 2, "Foreign page text.", "NATIVE_TEXT", None, "pypdf")
    pages = [page, other_page]
    chunks = pdf.build_source_chunks("SYNTH-01", pages, max_characters=20, max_source_characters=20)
    output = _unit_reference_model_output(chunks[0].units[0])
    output["entities"] = []

    output["facts"][0]["evidence"][0]["source_unit_id"] = chunks[1].units[0].source_unit_id
    with pytest.raises(pdf.PdfResearchError, match="MODEL_EVIDENCE_SOURCE_UNIT_UNKNOWN"):
        pdf._validate_chunk_output(output, chunks[0], schema_sha256="d" * 64, source_pages=pages)

    output = _unit_reference_model_output(chunks[0].units[0])
    output["entities"] = []
    output["facts"][0]["evidence"][0]["source_unit_id"] = " " + chunks[0].units[0].source_unit_id
    with pytest.raises(pdf.PdfResearchError, match="MODEL_EVIDENCE_SOURCE_UNIT_UNKNOWN"):
        pdf._validate_chunk_output(output, chunks[0], schema_sha256="d" * 64, source_pages=pages)

    output = _unit_reference_model_output(chunks[0].units[0])
    output["entities"] = []
    output["facts"][0]["evidence"][0]["quote"] = "Example Energy Co. reported 12 units in FY2025."
    output["facts"][0]["evidence"][0]["page_number"] = 1
    output["facts"][0]["evidence"][0]["unit_offset_start"] = 0
    output["facts"][0]["evidence"][0]["unit_offset_end"] = 10
    with pytest.raises(pdf.PdfResearchError, match="MODEL_OUTPUT_SCHEMA_MISMATCH"):
        pdf._validate_chunk_output(output, chunks[0], schema_sha256="d" * 64, source_pages=pages)

    original_unit = chunks[0].units[0]
    tampered_unit = replace(original_unit, text=original_unit.text + " ")
    tampered_chunk = pdf.SourceChunk(
        chunks[0].document_id,
        chunks[0].chunk_index,
        chunks[0].chunk_total,
        (tampered_unit,),
        chunks[0].chunk_sha256,
    )
    output = _unit_reference_model_output(tampered_unit)
    output["entities"] = []
    with pytest.raises(pdf.PdfResearchError, match="MODEL_EVIDENCE_SOURCE_SLICE_MISMATCH"):
        pdf._validate_chunk_output(output, tampered_chunk, schema_sha256="d" * 64, source_pages=pages)


def test_document_role_and_fact_nature_are_independent_taxonomies() -> None:
    page = pdf.PageText(
        1,
        1,
        "Example Energy Co. reported 12 units in FY2025; current backlog is 6 units as of 2026-01; target price 42; forecast 14 units in FY2026; scheduled review meeting 2027-03; supplier Example Components Ltd.; customer Example Retail Ltd.; published by Research House.",
        "NATIVE_TEXT",
        None,
        "pypdf",
    )
    chunk = pdf.build_source_chunks("SYNTH-01", [page])[0]
    output = _unit_reference_model_output(chunk.units[0])
    validated = pdf._validate_chunk_output(output, chunk, schema_sha256="d" * 64, source_pages=[page])
    roles = {item["entity_role"] for item in validated["entities"]}
    natures = {item["claim_nature"] for item in output["facts"]}

    assert {"REPORT_SUBJECT", "SUPPLIER", "CUSTOMER", "AUTHOR_OR_INSTITUTION"}.issubset(
        set(pdf.ENTITY_SCHEMA["properties"]["entity_role"]["enum"])
    )
    assert {"REALIZED_ACTUAL", "CURRENT_STATUS_OR_OBSERVATION", "THIRD_PARTY_VIEW", "ANALYST_OR_REPORT_FORECAST"}.issubset(
        set(pdf.FACT_SCHEMA["properties"]["claim_nature"]["enum"])
    )
    assert roles == {"REPORT_SUBJECT", "SUPPLIER", "CUSTOMER", "AUTHOR_OR_INSTITUTION"}
    assert natures == {
        "REALIZED_ACTUAL",
        "CURRENT_STATUS_OR_OBSERVATION",
        "THIRD_PARTY_VIEW",
        "ANALYST_OR_REPORT_FORECAST",
    }
    assert "scheduled review meeting" in {row["event_or_metric"] for row in output["verification_events"]}
    system = pdf.build_messages("SYNTH-01", chunk)[0]["content"]
    assert "报告主体" in system and "供应商" in system and "发布机构" in system
    assert "目标价" in system and "scheduled review meeting" not in system


@pytest.mark.parametrize("separator", ["\t", "\n", "\u00a0"])
def test_raw_value_presence_allows_only_collapsed_unicode_whitespace_and_keeps_quote_exact(separator: str) -> None:
    source_value = f"RMB 12tr{separator}/{separator}USD 3bn"
    model_value = "RMB 12tr / USD 3bn"
    page = pdf.PageText(
        1,
        1,
        f"Example Energy Co. revenue was {source_value}.",
        "NATIVE_TEXT",
        None,
        "pypdf",
    )
    chunk = pdf.build_source_chunks("SYNTH-VALUE", [page])[0]
    output = _minimal_model_output(chunk.units[0])
    fact = output["facts"][0]
    fact.update(
        raw_value_text=model_value,
        numeric_value=None,
        unit=None,
        currency=None,
        period=None,
        comparison_basis=None,
    )

    validated = pdf._validate_chunk_output(
        output,
        chunk,
        schema_sha256="d" * 64,
        source_pages=[page],
    )

    evidence = validated["facts"][0]["evidence"][0]
    assert validated["facts"][0]["raw_value_text"] == model_value
    assert evidence["quote"] == page.text
    assert evidence["page_offset_start"] == 0
    assert evidence["page_offset_end"] == len(page.text)
    assert evidence["quote_sha256"] == hashlib.sha256(page.text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("source_value", "model_value"),
    [
        ("RMB 12 34", "RMB 1234"),
        ("+12%", "-12%"),
        ("RMB 12", "USD 12"),
        ("12 tonnes", "12 tons"),
        ("12,5", "12.5"),
        ("12", "13"),
    ],
)
def test_raw_value_presence_does_not_normalize_numbers_signs_units_currency_or_punctuation(
    source_value: str,
    model_value: str,
) -> None:
    page = pdf.PageText(
        1,
        1,
        f"Example Energy Co. revenue was {source_value}.",
        "NATIVE_TEXT",
        None,
        "pypdf",
    )
    chunk = pdf.build_source_chunks("SYNTH-VALUE", [page])[0]
    output = _minimal_model_output(chunk.units[0])
    output["facts"][0].update(
        raw_value_text=model_value,
        numeric_value=None,
        unit=None,
        currency=None,
        period=None,
        comparison_basis=None,
    )

    with pytest.raises(pdf.PdfResearchError, match="MODEL_VALUE_NOT_IN_EVIDENCE"):
        pdf._validate_chunk_output(
            output,
            chunk,
            schema_sha256="d" * 64,
            source_pages=[page],
        )


def test_generic_prompt_covers_mixed_periods_comparators_and_semantic_fact_links() -> None:
    page = pdf.PageText(
        1,
        1,
        "Example Energy Co. synthetic table: FY2025 Actual 12 units; FY2026E 14 units; revenue 8% yoy and 3% qoq; margin rose from 10% to 12%.",
        "NATIVE_TEXT",
        None,
        "pypdf",
    )
    chunk = pdf.build_source_chunks("SYNTH-PROMPT", [page])[0]

    system = pdf.build_messages("SYNTH-PROMPT", chunk)[0]["content"]

    assert "每个单元格" in system or "逐列" in system
    assert "报告日期" in system and "表头" in system and "A/E" in system
    assert "报告类型本身不决定事实性质" in system and "UNKNOWN" in system
    assert "过去期间" in system and "不能证明" in system
    assert "同比" in system and "环比" in system and "前后值" in system and "区间" in system
    assert "描述式" in system and "指标" in system and "期间" in system
    assert "supporting_fact_indices" in system and "counter_fact_indices" in system
    assert "存在某个索引或位置相邻都不是支持依据" in system


def test_selected_chunk_scope_runs_only_authorized_chunk_and_records_other_chunks_not_run(monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    queue = _RequestOutcomeQueue()

    result = pdf.analyze_document(
        {"document_id": "S01", "pdf_sha256": "b" * 64, "page_count": len(pages)},
        queue=queue,
        binding={"configuration_sha256": "c" * 64, "request_schema_sha256": "d" * 64},
        maximum_model_calls=1,
        selected_chunk_indices=[1],
        model_request=lambda **_kwargs: "offline-success-stub",
    )

    execution = result["coverage"]["chunk_execution"]
    assert len(queue.payloads) == queue.run_count == 1
    assert result["document_status"] == "PARTIAL"
    assert result["coverage"]["full_analysis_complete"] is False
    assert execution["selected_chunk_indices"] == [1]
    assert "selected_chunk_indices" not in queue.payloads[0]
    assert execution["unrun_chunk_count"] == 2
    assert [row["status"] for row in execution["unrun_chunks"]] == ["NOT_RUN", "NOT_RUN"]


def test_continuation_reuses_exact_accepted_success_without_resubmitting_it(tmp_path, monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    document = {
        "document_id": "S01",
        "report_date": "2026-10-17",
        "pdf_sha256": "b" * 64,
        "page_count": len(pages),
    }
    schema_sha = local_model.sha256_bytes(local_model.canonical_json(pdf.V3_OUTPUT_SCHEMA))
    binding = {"configuration_sha256": "c" * 64, "request_schema_sha256": schema_sha}
    chunks = pdf.build_source_chunks("S01", pages)
    queue = _StoredSuccessQueue(tmp_path / "queue")
    acceptance = _seed_accepted_chunk(queue, document, chunks[0], pages, binding)
    expected_messages = pdf.build_messages("S01", chunks[0])
    expected_payload = pdf._queue_payload(document=document, chunk=chunks[0], messages=expected_messages, binding=binding)
    assert acceptance["payload_sha256"] == local_model.sha256_bytes(local_model.canonical_json(expected_payload))
    assert "selected_chunk_indices" not in expected_payload
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    monkeypatch.setattr(pdf, "_read_validated_result", _validated_chunk_for_last_payload)
    model_calls: list[bool] = []

    result = pdf.analyze_document(
        document,
        queue=queue,
        binding=binding,
        maximum_model_calls=2,
        selected_chunk_indices=[2, 3],
        accepted_prior_chunks={1: acceptance},
        model_request=lambda **_kwargs: model_calls.append(True) or "offline-success-stub",
    )

    execution = result["coverage"]["chunk_execution"]
    assert len(queue.payloads) == queue.run_count == len(model_calls) == 2
    assert [payload["chunk_index"] for payload in queue.payloads] == [2, 3]
    assert execution["selected_chunk_indices"] == [2, 3]
    assert execution["reused_chunk_indices"] == [1]
    assert execution["completed_chunk_count"] == 3
    assert execution["unrun_chunk_count"] == 0
    assert result["document_status"] == "COMPLETE"
    assert result["coverage"]["full_analysis_complete"] is True


def test_continuation_stops_before_new_request_when_accepted_prior_result_does_not_match(tmp_path, monkeypatch) -> None:
    pages, source = _three_chunk_native_pages()
    document = {
        "document_id": "S01",
        "report_date": "2026-10-17",
        "pdf_sha256": "b" * 64,
        "page_count": len(pages),
    }
    schema_sha = local_model.sha256_bytes(local_model.canonical_json(pdf.V3_OUTPUT_SCHEMA))
    binding = {"configuration_sha256": "c" * 64, "request_schema_sha256": schema_sha}
    chunks = pdf.build_source_chunks("S01", pages)
    queue = _StoredSuccessQueue(tmp_path / "queue")
    acceptance = _seed_accepted_chunk(queue, document, chunks[0], pages, binding)
    acceptance["payload_sha256"] = "e" * 64
    monkeypatch.setattr(pdf, "load_document_pages", lambda _document: (pages, source))
    request_calls: list[bool] = []

    result = pdf.analyze_document(
        document,
        queue=queue,
        binding=binding,
        maximum_model_calls=2,
        selected_chunk_indices=[2, 3],
        accepted_prior_chunks={1: acceptance},
        model_request=lambda **_kwargs: request_calls.append(True) or "must-not-run",
    )

    execution = result["coverage"]["chunk_execution"]
    assert queue.payloads == []
    assert queue.run_count == 0
    assert request_calls == []
    assert execution["failed_chunk_count"] == 1
    assert execution["failed_chunks"][0]["failure_stage"] == "accepted_result_reuse"
    assert execution["unrun_chunk_count"] == 2
    assert result["document_status"] == "PARTIAL"
    assert result["coverage"]["full_analysis_complete"] is False


def test_numeric_and_security_code_mentions_preserve_literal_values() -> None:
    pages = [pdf.PageText(1, 1, "宁德时代（300750.SZ）收入3.2%，另有港股代码：00700，金额为人民币", "OCR_OK", None)]
    codes = pdf.parse_security_code_mentions(pages)
    assert [item["raw_code"] for item in codes] == ["300750.SZ", "00700"]
    assert all(item["master_validation_status"] == "NOT_CHECKED_NO_MASTER_INPUT" for item in codes)
    assert codes[0]["currency_as_stated"] == "人民币"
    assert codes[0]["currency_attribution_status"] == "LOCAL_QUOTE_ONLY_NOT_ATTRIBUTED"
    values = pdf.parse_numeric_mentions(pages)
    percent = next(item for item in values if item["raw_value_text"] == "3.2%")
    assert percent["numeric_value_unscaled"] == "3.2"
    assert percent["percent_marker_present"] is True
    assert percent["unit_conversion"] == "NOT_PERFORMED"
    assert percent["page_number"] == 1


def test_conflicting_source_codes_remain_unresolved_with_all_page_evidence() -> None:
    pages = [
        pdf.PageText(1, 2, "宁德时代（300750.SZ）", "NATIVE_TEXT", None, "pypdf"),
        pdf.PageText(2, 2, "宁德时代（300750.SH）", "NATIVE_TEXT", None, "pypdf"),
    ]
    mentions = pdf.parse_security_code_mentions(pages)
    entities, conflicts, relationships = pdf.resolve_entity_code_mentions(
        [{"raw_name": "宁德时代", "raw_code": "300750.SZ", "market_as_stated": "A-share"}],
        mentions,
    )
    assert [item["raw_code"] for item in mentions] == ["300750.SZ", "300750.SH"]
    assert [item["page_number"] for item in mentions] == [1, 2]
    assert entities[0]["raw_code"] is None
    assert entities[0]["model_raw_code"] == "300750.SZ"
    assert entities[0]["code_resolution_status"] == "UNRESOLVED"
    assert entities[0]["identity_status"] == "CANNOT_CONFIRM_CONFLICTING_CODES_WITHIN_MARKET"
    assert [(item["raw_code"], item["page_number"]) for item in entities[0]["raw_code_candidates"]] == [
        ("300750.SZ", 1), ("300750.SH", 2)
    ]
    assert conflicts[0]["status"] == "UNRESOLVED"
    assert conflicts[0]["confirmation_status"] == "CANNOT_CONFIRM"
    assert conflicts[0]["identity_status"] == "CANNOT_CONFIRM_CONFLICTING_CODES_WITHIN_MARKET"
    assert relationships == []


def test_a_share_and_hk_codes_are_never_merged() -> None:
    mentions = pdf.parse_security_code_mentions(
        [pdf.PageText(1, 1, "公司甲（300750.SZ）；公司甲（00700.HK）", "NATIVE_TEXT", None)]
    )
    assert [(item["raw_code"], item["market_as_stated"]) for item in mentions] == [
        ("300750.SZ", "A_SHARE_AS_STATED"),
        ("00700.HK", "HK_AS_STATED"),
    ]
    entities, conflicts, relationships = pdf.resolve_entity_code_mentions(
        [{"raw_name": "公司甲", "raw_code": None}], mentions
    )
    assert not conflicts
    assert entities[0]["raw_code"] is None
    assert entities[0]["code_resolution_status"] == "UNRESOLVED"
    assert entities[0]["relationship_status"] == "CANNOT_CONFIRM_NO_AUTHORITATIVE_CROSS_MARKET_MAP"
    assert [item["market_as_stated"] for item in entities[0]["raw_code_candidates"]] == [
        "A_SHARE_AS_STATED", "HK_AS_STATED"
    ]
    assert len(relationships) == 1
    assert relationships[0]["confirmation_status"] == "CANNOT_CONFIRM"


def test_neighboring_company_code_pairs_are_not_cross_associated() -> None:
    mentions = pdf.parse_security_code_mentions(
        [pdf.PageText(1, 1, "公司甲（300750.SZ）；公司乙（600000.SH）", "NATIVE_TEXT", None)]
    )
    entities, conflicts, relationships = pdf.resolve_entity_code_mentions(
        [
            {"raw_name": "公司甲", "raw_code": "300750.SZ"},
            {"raw_name": "公司乙", "raw_code": "600000.SH"},
        ],
        mentions,
    )
    assert [item["raw_code"] for item in entities] == ["300750.SZ", "600000.SH"]
    assert [[item["raw_code"] for item in entity["raw_code_candidates"]] for entity in entities] == [
        ["300750.SZ"], ["600000.SH"]
    ]
    assert not conflicts and not relationships


def test_cache_and_native_first_selection_are_hash_bound_and_never_run_ocr(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    pdf_path = data_root / "pdfs" / "sample.pdf"
    cache_path = data_root / "external_sources" / "zsxq_hourly" / "cache.json"
    pdf_path.parent.mkdir(parents=True)
    cache_path.parent.mkdir(parents=True)
    pdf_bytes = b"%PDF-fake bytes for mocked native extractor"
    pdf_path.write_bytes(pdf_bytes)
    cache_value = [
        {"page_number": 1, "page_total": 2, "status": "OCR_OK", "method": "cached OCR", "text": "OCR page one"},
        {"page_number": 2, "page_total": 2, "status": "OCR_OK", "method": "cached OCR", "text": "OCR page two"},
    ]
    cache_bytes = json.dumps(cache_value, ensure_ascii=False).encode()
    cache_path.write_bytes(cache_bytes)
    monkeypatch.setattr(pdf, "AUTHORITATIVE_DATA_ROOT", data_root)
    monkeypatch.setattr(
        pdf,
        "extract_native_pdf_pages",
        lambda path, count: ([
            pdf.PageText(1, 2, "Native page one", "NATIVE_TEXT", None, "pypdf"),
            pdf.PageText(2, 2, "", "BLANK", None, "pypdf"),
        ], "PARTIAL_OR_BLANK"),
    )
    document = {
        "document_id": "S01",
        "pdf_path": str(pdf_path),
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "page_count": 2,
        "pages_cache_path": str(cache_path),
        "pages_cache_sha256": hashlib.sha256(cache_bytes).hexdigest(),
        "pages_cache_pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
    }
    pages, source = pdf.load_document_pages(document)
    assert [page.text for page in pages] == ["Native page one", "OCR page two"]
    assert source["selected_native_page_count"] == 1
    assert source["selected_cache_page_count"] == 1
    assert source["cache_embedded_pdf_sha256_status"] == "CANNOT_CONFIRM_NOT_EMBEDDED"
    assert source["page_extraction_sources"][1]["extraction_method"] == "cached OCR"
    assert source["page_extraction_status"] == "COMPLETE"
    assert source["cached_ocr_visual_quality_status"] == "CANNOT_CONFIRM_NOT_VISUALLY_REVIEWED"


def test_sample_manifest_is_whitelisted_and_canary_never_selects_more_than_s01() -> None:
    def sample(sample_id: str) -> dict:
        digest = hashlib.sha256(sample_id.encode()).hexdigest()
        return {
            "sample_id": sample_id,
            "local_pdf_path": f"/Users/lexi/Desktop/学习/知识星球/{sample_id}.pdf",
            "pdf_sha256": digest,
            "page_count": 2,
            "cache_path": f"/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/{sample_id}.json",
            "cache_sha256": hashlib.sha256((sample_id + "cache").encode()).hexdigest(),
            "tags": ["must-not-prompt"],
            "expected": {"must_not_prompt": True},
            "source": {
                "source_hash_raw": digest,
                "document_key": f"doc-{sample_id}",
                "original_filename": f"{sample_id}.pdf",
                "pit_status": "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT",
                "source_run_id": "run-1",
                "source_fetched_at": "2026-10-15T23:00:00+08:00",
            },
        }

    manifest = {
        "schema_version": "v4.pdf_research_frozen_sample.v1",
        "status": "FROZEN",
        "first_canary_sample_id": "S01",
        "sample_count": 20,
        "max_documents": 20,
        "samples": [sample(f"S{index:02d}") for index in range(1, 21)],
        "selection_notes_not_model_input": "must-not-prompt",
    }
    canary = pdf.validate_sample_manifest(manifest, phase="CANARY")
    all_samples = pdf.validate_sample_manifest(manifest, phase="SAMPLE")
    assert [doc["document_id"] for doc in canary] == ["S01"]
    assert len(all_samples) == 20
    assert "tags" not in canary[0] and "expected" not in canary[0]
    assert "selection_notes_not_model_input" not in canary[0]
    assert set(canary[0]["source_identity"]) <= {
        "data_role", "document_key", "original_filename", "pdf_published_at", "source_fetched_at",
        "source_hash_algorithm", "source_hash_raw", "source_run_id", "source_topic_published_at",
        "topic_id", "topic_title", "trade_date", "pit_status",
    }


def test_queue_payload_body_hash_covers_exact_prompt_body() -> None:
    page = pdf.PageText(1, 1, "宁德时代 3.2% in 2026", "COMPLETE", None)
    chunk = pdf.build_source_chunks("S01", [page])[0]
    messages = pdf.build_messages("S01", chunk)
    binding = {
        "configuration_sha256": "c" * 64,
        "request_schema_sha256": local_model.sha256_bytes(local_model.canonical_json(pdf.V3_OUTPUT_SCHEMA)),
        "runtime_limits": {"context_length": 32768},
        "request_policy": {"sampling": "fixed"},
        "evidence_root": "/tmp/receipts",
    }
    payload = pdf._queue_payload(
        document={"document_id": "S01", "pdf_sha256": "a" * 64},
        chunk=chunk,
        messages=messages,
        binding=binding,
    )
    assert payload["body_sha256"] == hashlib.sha256(payload["article_body"].encode()).hexdigest()
    assert payload["chunk_sha256"] == chunk.chunk_sha256
    assert payload["model_binding"]["runtime_limits"] == binding["runtime_limits"]
    assert payload["model_binding"]["request_policy"] == binding["request_policy"]
    assert "selection_notes" not in payload and "tags" not in payload


def test_two_pdf_queues_share_one_model_lock_without_nested_lock_or_announcement_state(tmp_path, monkeypatch) -> None:
    research_root = tmp_path / "pdf_research"
    announcement_root = tmp_path / "announcement_queue"
    lock_path = announcement_root / "locks" / f"model-{hashlib.sha256(local_model.MODEL_ID.encode()).hexdigest()}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.touch()
    monkeypatch.setattr(pdf, "PDF_RESEARCH_STATE_ROOT", research_root)
    monkeypatch.setattr(pdf, "ANNOUNCEMENT_QUEUE_ROOT", announcement_root)
    monkeypatch.setattr(pdf, "GLOBAL_MODEL_LOCK_PATH", lock_path)
    q1 = pdf.create_pdf_queue(research_root / "queue-a")
    q2 = pdf.create_pdf_queue(research_root / "queue-b")
    assert q1._model_lock_path == q2._model_lock_path == lock_path
    assert q1.state_root != q2.state_root
    assert q1._state_lock_path != q2._state_lock_path
    assert q1._state_lock_path != lock_path
    assert q2._state_lock_path != lock_path

    def queue_payload(article_id: str) -> dict:
        body = f"body {article_id}"
        return {
            "date": "UNKNOWN",
            "market": "PDF_RESEARCH",
            "article_id": article_id,
            "source_sha256": "a" * 64,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "prompt_sha256": "b" * 64,
            "model_id": local_model.MODEL_ID,
            "configuration_sha256": "c" * 64,
            "rules": "pdf-v3-test",
            "role": "pdf_research_analyst",
            "stage": "document_chunk_v3",
            "article_body": body,
        }

    q1.enqueue(queue_payload("one"))
    q2.enqueue(queue_payload("two"))
    entered_first = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    outcomes: list[dict] = []

    def first_worker(job):
        entered_first.set()
        assert release_first.wait(3)
        return json.dumps({"ok": True})

    def run_first():
        outcomes.append(q1.run_next(first_worker, lambda _job, parsed: parsed))

    def run_second():
        second_started.set()
        outcome = q2.run_next(lambda _job: json.dumps({"ok": True}), lambda _job, parsed: parsed)
        outcomes.append(outcome)
        second_finished.set()

    thread1 = threading.Thread(target=run_first)
    thread2 = threading.Thread(target=run_second)
    thread1.start()
    assert entered_first.wait(2)
    thread2.start()
    assert second_started.wait(2)
    time.sleep(0.1)
    assert not second_finished.is_set()
    release_first.set()
    thread1.join(4)
    thread2.join(4)
    assert not thread1.is_alive() and not thread2.is_alive()
    assert len(outcomes) == 2 and all(item["status"] == "SUCCEEDED" for item in outcomes)
    assert len({item["idempotency_key"] for item in outcomes}) == 2
    assert not (announcement_root / "queue-state.json").exists()
    assert sorted(path.relative_to(announcement_root).as_posix() for path in announcement_root.rglob("*") if path.is_file()) == [
        "locks/" + lock_path.name
    ]
    result = pdf._read_validated_result(q1, q1.enqueue(queue_payload("one"))["idempotency_key"])
    assert result == {"ok": True}
