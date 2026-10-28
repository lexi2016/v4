"""Regression tests for announcement evidence-array completeness semantics."""
from __future__ import annotations

import hashlib

import pytest

from v4.manager_workbench.engines import announcement


BODY = (
    "The company announced a new operating event.\n"
    "Revenue increased from 10 to 12.\n"
    "Completion still requires regulator approval.\n"
    "No further counter-evidence was disclosed.\n"
)
SOURCE_SHA256 = "a" * 64
BODY_SHA256 = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
ARTICLE = {"source_sha256": SOURCE_SHA256, "body_sha256": BODY_SHA256}


def _citation(claim: str, quote: str, locator: str = "paragraph 1") -> dict[str, str]:
    return {"claim": claim, "quote": quote, "locator": locator}


def _selected_output() -> dict:
    return {
        "disposition": "SELECTED_EVENT",
        "selection_basis": "OPERATING_EVENT",
        "direction": "POSITIVE",
        "evidence_sufficiency": "VERIFIED_EXISTING_FACTS",
        "reason": "The source identifies an operating event.",
        "risk_notes": [],
        "facts": [_citation("The source identifies an operating event.", "The company announced a new operating event.")],
        "changes": [_citation("The event is newly announced.", "The company announced a new operating event.")],
        "impact": [],
        "confirmation_conditions": [],
        "counter_evidence": [],
        "source_sha256": SOURCE_SHA256,
        "body_sha256": BODY_SHA256,
    }


def _assert_reader_valid(output: dict) -> None:
    announcement._validate_reader(BODY, ARTICLE, output)


def test_selected_output_accepts_empty_optional_evidence_arrays():
    _assert_reader_valid(_selected_output())


def test_selected_output_still_validates_every_provided_optional_citation():
    output = _selected_output()
    output["impact"] = [_citation("Revenue increased.", "Revenue increased from 10 to 12.", "paragraph 2")]
    output["confirmation_conditions"] = [
        _citation("Approval is required.", "Completion still requires regulator approval.", "paragraph 3")
    ]
    output["counter_evidence"] = [
        _citation("No further counter-evidence was disclosed.", "No further counter-evidence was disclosed.", "paragraph 4")
    ]
    _assert_reader_valid(output)


@pytest.mark.parametrize("field", ["facts", "changes"])
def test_selected_output_requires_facts_and_a_change_source_claim(field: str):
    output = _selected_output()
    output[field] = []
    with pytest.raises(ValueError, match="ANNOUNCEMENT_EVIDENCE_INCOMPLETE"):
        _assert_reader_valid(output)


def test_conditional_watch_requires_an_explicit_condition():
    output = _selected_output()
    output.update(
        disposition="CONDITIONAL_WATCH",
        selection_basis="CONDITIONAL_WATCH",
        direction="MIXED",
        facts=[],
        changes=[],
    )
    with pytest.raises(ValueError, match="ANNOUNCEMENT_EVIDENCE_INCOMPLETE"):
        _assert_reader_valid(output)


def test_conditional_watch_accepts_a_cited_explicit_condition():
    output = _selected_output()
    output.update(
        disposition="CONDITIONAL_WATCH",
        selection_basis="CONDITIONAL_WATCH",
        direction="MIXED",
        facts=[],
        changes=[],
        confirmation_conditions=[
            _citation("Completion requires regulator approval.", "Completion still requires regulator approval.", "paragraph 3")
        ],
    )
    _assert_reader_valid(output)


@pytest.mark.parametrize("field", ["facts", "changes", "impact", "confirmation_conditions", "counter_evidence"])
def test_every_evidence_field_must_remain_an_array(field: str):
    output = _selected_output()
    output[field] = None
    with pytest.raises(ValueError, match="ANNOUNCEMENT_EVIDENCE_INCOMPLETE"):
        _assert_reader_valid(output)


@pytest.mark.parametrize("identity_field", ["source_sha256", "body_sha256"])
def test_reader_identity_sha_must_match_article(identity_field: str):
    output = _selected_output()
    output[identity_field] = "b" * 64
    with pytest.raises(ValueError, match="ANNOUNCEMENT_READER_SOURCE_MISMATCH"):
        _assert_reader_valid(output)


@pytest.mark.parametrize(
    ("citation", "error"),
    [
        (_citation("unsupported", "This quote is not in the source."), "ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE"),
        (_citation("missing locator", "Revenue increased from 10 to 12.", " "), "ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE"),
    ],
)
def test_provided_citations_require_exact_source_text_and_locator(citation: dict, error: str):
    output = _selected_output()
    output["impact"] = [citation]
    with pytest.raises(ValueError, match=error):
        _assert_reader_valid(output)


def test_selected_direction_and_sufficiency_gates_remain_strict():
    output = _selected_output()
    output["direction"] = "UNKNOWN"
    with pytest.raises(ValueError, match="ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT"):
        _assert_reader_valid(output)


def test_independent_reviewer_identity_gate_remains_strict():
    output = _selected_output()
    reader = {
        "output": output,
        "output_sha256": "c" * 64,
        "execution_identity": "same-runtime",
        "execution_id": "reader-execution",
    }
    review = {
        "output": {
            "confirmed": True,
            "reason": "Confirmed.",
            "source_sha256": SOURCE_SHA256,
            "body_sha256": BODY_SHA256,
            "reader_output_sha256": reader["output_sha256"],
            "disposition": output["disposition"],
            "direction": output["direction"],
            "evidence_sufficiency": output["evidence_sufficiency"],
        },
        "execution_identity": "same-runtime",
        "execution_id": "reviewer-execution",
    }
    with pytest.raises(ValueError, match="ANNOUNCEMENT_REVIEWER_NOT_INDEPENDENT"):
        announcement._validate_review(ARTICLE, reader, review)
