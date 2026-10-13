"""Issue #40 narrow regression: Codex private output schema vs A validator.

All executions here are synthetic. Real Luna Max and Mac binding are NOT_RUN.
"""
from __future__ import annotations

import jsonschema
import pytest

from test_announcement import FakeExecutor, article, batch, context, run_announcements
from v4.manager_workbench.engines import announcement as ann


class SchemaCheckingExecutor(FakeExecutor):
    """Exercise the actual private JSON schemas on BOTH role responses."""

    def execute(self, task):
        receipt = super().execute(task)
        jsonschema.Draft202012Validator(task["output_schema"]).validate(receipt["output"])
        return receipt


def _non_catalyst_reader(task, output, *, disposition="NOT_ASSESSED"):
    if task["role"] == "REVIEWER":
        return output
    neutral = disposition == "NOT_SELECTED"
    return dict(
        output,
        disposition=disposition,
        selection_basis=disposition,
        direction="NEUTRAL" if neutral else "UNKNOWN",
        evidence_sufficiency=(
            "VERIFIED_EXISTING_FACTS" if neutral else "INSUFFICIENT_EXISTING_FACTS"
        ),
        reason="股东大会投票代理表，不含可支持业绩或经营催化的新增事实。",
        facts=([dict(claim="会议代理投票", quote="代理投票表格", locator="正文")]
               if neutral else []),
        changes=[],
        impact=[],
        confirmation_conditions=[],
        counter_evidence=[],
        risk_notes=["无经营变化或业绩证据，不能据此推荐"],
    )


def test_private_schema_only_accepts_validator_enums_and_rejects_explanations():
    reader = ann.READER_SCHEMA["properties"]
    reviewer = ann.REVIEWER_SCHEMA["properties"]
    expectations = {
        "disposition": {"SELECTED_EVENT", "SELECTED_PERFORMANCE", "CONDITIONAL_WATCH", "NOT_SELECTED", "NOT_ASSESSED"},
        "selection_basis": {"OPERATING_EVENT", "PERFORMANCE_RESEARCH", "CONDITIONAL_WATCH", "NOT_SELECTED", "NOT_ASSESSED"},
        "direction": {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"},
        "evidence_sufficiency": {"VERIFIED_EXISTING_FACTS", "INSUFFICIENT_EXISTING_FACTS"},
    }
    for key, values in expectations.items():
        assert set(reader[key]["enum"]) == values
        if key != "selection_basis":
            assert set(reviewer[key]["enum"]) == values
    assert "enum" not in reader["reason"] and "enum" not in reviewer["reason"]
    assert "NOT_ASSESSED" not in reader["direction"]["enum"]
    jsonschema.Draft202012Validator.check_schema(ann.READER_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(ann.REVIEWER_SCHEMA)


def test_shareholder_proxy_unassessed_valid_schema_and_independent_reviewer_executed():
    notice = article("股东大会代理投票表格：股东可授权代表按议案投票。")
    executor = SchemaCheckingExecutor()
    executor.override = _non_catalyst_reader
    outcome = run_announcements(context(), batch([notice]), executor)
    item = outcome["rows"][0]
    assert item["decision"] == "UNASSESSED"
    assert item["reason"] == "ANNOUNCEMENT_NOT_ASSESSED"
    assert item["semantic"]["disposition"] == "NOT_ASSESSED"
    assert item["semantic"]["direction"] == "UNKNOWN"
    assert item["semantic"]["prompt_version"] == ann.PROMPT_VERSION
    assert item["semantic"]["body_sha256"] == notice["body_sha256"]
    assert item["semantic"]["source_sha256"] == notice["source_sha256"]
    assert [t["role"] for t in executor.tasks] == ["READER", "REVIEWER"]
    assert executor.tasks[0]["input_sha256"] == executor.tasks[1]["input_sha256"]
    assert outcome["coverage"]["scope_count"] == 1


def test_verified_neutral_proxy_can_be_not_selected_without_positive_upgrade():
    notice = article("股东大会代理投票表格：仅用于委托出席并表决议案。")
    executor = SchemaCheckingExecutor()
    executor.override = lambda t, o: _non_catalyst_reader(t, o, disposition="NOT_SELECTED")
    result = run_announcements(context(), batch([notice]), executor)
    assert result["rows"][0]["decision"] == "NOT_SELECTED"
    assert len(executor.tasks) == 2
    assert result["rows"][0]["semantic"]["facts"][0]["quote"] in notice["body"]


@pytest.mark.parametrize("field,value", [
    ("direction", "NOT_ASSESSED"),
    ("selection_basis", "Because this is not material business research"),
    ("evidence_sufficiency", "There are no meaningful operating changes"),
    ("disposition", "NO_OPERATING_CATALYST"),
])
def test_bad_reader_enum_rejected_by_json_schema_before_business_validation(field, value):
    notice = article("股东大会代理投票表格：没有业绩披露。")
    executor = SchemaCheckingExecutor()
    def override(task, output):
        modified = _non_catalyst_reader(task, output)
        if task["role"] == "READER":
            modified[field] = value
        return modified
    executor.override = override
    # Direct schema gate must reject before _validate_reader gets a chance.
    raw_receipt = FakeExecutor().execute(ann._task(executor, "READER", article=notice, body=notice["body"]))
    raw_invalid = _non_catalyst_reader({"role": "READER"}, raw_receipt["output"])
    raw_invalid[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw_invalid, ann.READER_SCHEMA)
    result = run_announcements(context(), batch([notice]), executor)
    assert result["rows"][0]["decision"] == "UNASSESSED"
    assert result["rows"][0]["reason"] == "ANNOUNCEMENT_READER_REVIEWER_NOT_VERIFIED"
    assert [task["role"] for task in executor.tasks] == ["READER"]


def test_existing_disposition_basis_mapping_remains_strict():
    notice = article("股东大会代理投票表格。")
    executor = SchemaCheckingExecutor()
    executor.override = lambda task, output: dict(
        _non_catalyst_reader(task, output),
        selection_basis="OPERATING_EVENT" if task["role"] == "READER" else output.get("selection_basis", "NOT_ASSESSED"),
    ) if task["role"] == "READER" else output
    result = run_announcements(context(), batch([notice]), executor)
    assert result["rows"][0]["reason"] == "ANNOUNCEMENT_READER_REVIEWER_NOT_VERIFIED"
    assert len(executor.tasks) == 1


def test_reviewer_rejection_preserves_failed_semantic_attempt_without_selection():
    notice = article("股东大会代理投票表格：常规授权投票。")
    executor = SchemaCheckingExecutor()
    def reject(task, output):
        out = _non_catalyst_reader(task, output)
        return dict(out, confirmed=False, reason="独立复核无法确认原文结论") if task["role"] == "REVIEWER" else out
    executor.override = reject
    result = run_announcements(context(), batch([notice]), executor)
    assert result["rows"][0]["decision"] == "UNASSESSED"
    assert result["rows"][0]["reason"] == "ANNOUNCEMENT_READER_REVIEWER_NOT_VERIFIED"
    assert len(executor.tasks) == 2


def test_private_prompts_explain_enum_mapping_unknown_direction_and_bump_cache_identity():
    assert ann.PROMPT_VERSION != "MWB_ANNOUNCEMENT_READER_REVIEWER_V1_20261013"
    for disposition, basis in ann._BASIS.items():
        assert f"{disposition} -> {basis}" in ann.READ_PROMPT
    for prompt in (ann.READ_PROMPT, ann.REVIEW_PROMPT):
        for field in ("disposition", "direction", "evidence_sufficiency", "reason"):
            assert field in prompt
        assert "NOT_ASSESSED" in prompt and "UNKNOWN" in prompt
        assert "ARTICLE_DATA" in prompt
    assert ann.PROMPT_VERSION not in ann.READ_PROMPT  # versioned through task identity


@pytest.mark.parametrize("field,value", [
    ("disposition", "NO_POSITIVE_CATALYST"),
    ("direction", "NOT_ASSESSED"),
    ("evidence_sufficiency", "Meeting proxy without earnings details"),
])
def test_reviewer_private_schema_refuses_free_form_classifier_labels(field, value):
    notice = article("股东大会代理投票表格：股东可授权投票。")
    executor = SchemaCheckingExecutor()
    executor.override = _non_catalyst_reader
    output = FakeExecutor().execute(ann._task(executor, "READER", article=notice, body=notice["body"]))["output"]
    prepared = _non_catalyst_reader({"role": "READER"}, output)
    reader_receipt = dict(output=prepared, output_sha256="f"*64)
    reviewer_task = ann._task(executor, "REVIEWER", article=notice, body=notice["body"],reader=reader_receipt)
    reviewer_output = FakeExecutor().execute(reviewer_task)["output"]
    reviewer_output[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(reviewer_output, ann.REVIEWER_SCHEMA)


def test_old_private_prompt_version_cannot_use_new_schema_or_cached_receipts():
    from types import SimpleNamespace
    notice = article("股东大会代理投票表格。")
    executor = SchemaCheckingExecutor()
    executor.config = SimpleNamespace(model="configured-luna-max",prompt_version="MWB_ANNOUNCEMENT_READER_REVIEWER_V1_20261013")
    result = run_announcements(context(),batch([notice]),executor)
    assert result["rows"][0]["reason"] == "ANNOUNCEMENT_READER_REVIEWER_NOT_VERIFIED"
    assert executor.tasks == []
