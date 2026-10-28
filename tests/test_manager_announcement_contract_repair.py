from __future__ import annotations

import hashlib
import importlib
import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from v4.manager_workbench import announcement_chunks as chunks


PROMPT = """你是公告 Reader。对本次输入的一篇完整公告独立作出研究判断。按 source_units 顺序阅读全文；它们完整、无损地重建正文。
先通读完整正文，再结合账本核对固定事实
- wire JSON 中 facts 必须输出空数组；程序会在保存原始模型响应后，从冻结账本生成 facts 字段及其精确引文。你负责经营/业绩判断及理由、风险、影响、条件、反面证据，并在 changes 中填写正文披露且符合既有标准的经营/业绩变化。每条 changes claim 必须完整原子化，其全部细节由所引用的连续正文范围支持；使用 start_source_unit_id/end_source_unit_id 标记端点。程序只投影范围、生成 quote/locator，不会从固定账本生成、删除、替换或改写 changes；其余模型判断字段保持原样。
仅输出一个符合下方严格结构的 JSON envelope。action=complete 时 lookup_request=null，reader_output 必须恰好包含原有全部 13 个字段；facts 必须为 []，由程序从冻结账本注入；changes 由模型依据完整正文填写，使用连续 source-unit 范围端点引证，没有符合既有 Reader 标准的有据变化时留空。action=lookup 时 reader_output=null。
"""


def _reader_schema() -> dict:
    return {"type": "object", "properties": {
        "facts": {"type": "array", "items": {"type": "object"}},
        "changes": {"type": "array", "items": {"type": "object"}},
    }}


def _fixed_fields(node: dict) -> dict:
    found = []

    def visit(value):
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and {"facts", "changes"}.issubset(properties):
                found.append(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(node)
    assert len(found) == 1
    return found[0]


def test_chunk_prompts_replace_full_day_changes_instruction_and_preserve_other_reader_rules():
    part = chunks.reader_task_system_prompt(PROMPT, "part")
    synthesis = chunks.reader_task_system_prompt(PROMPT, "synthesis")

    for prompt in (part, synthesis):
        assert "changes 中填写正文披露" not in prompt
        assert "changes 由模型依据完整正文填写" not in prompt
        assert "fixed_fact_ledger.reader_facts" in prompt
        assert "fixed_fact_ledger.reader_changes" in prompt
        assert "facts 和 changes 必须均为 []" in prompt
        assert "action=lookup 时 reader_output=null" in prompt
    assert "当前连续分片作局部证据记录" in part
    assert "全部有序分片证据综合" in synthesis


def test_fixed_field_schema_overlay_is_deep_copied_and_applies_to_direct_and_wrapped_reader_schemas():
    direct = _reader_schema()
    wrapped = {"type": "object", "properties": {"reader_output": {"anyOf": [
        _reader_schema(), {"type": "null"}]}}}

    direct_result = chunks.empty_reader_fixed_fields_schema(direct)
    wrapped_result = chunks.empty_reader_fixed_fields_schema(wrapped)

    assert _fixed_fields(direct_result)["facts"]["maxItems"] == 0
    assert _fixed_fields(direct_result)["changes"]["maxItems"] == 0
    assert _fixed_fields(wrapped_result)["facts"]["maxItems"] == 0
    assert _fixed_fields(wrapped_result)["changes"]["maxItems"] == 0
    assert "maxItems" not in direct["properties"]["facts"]
    assert "maxItems" not in wrapped["properties"]["reader_output"]["anyOf"][0]["properties"]["facts"]


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {"facts": {"type": "string"}, "changes": {"type": "array"}}},
    {"type": "object", "properties": {"facts": {"type": "array"}}},
    {"type": "object", "properties": {"reader_output": {"type": "null"}}},
])
def test_fixed_field_schema_overlay_fails_closed_for_unbound_schema(schema):
    with pytest.raises(ValueError, match="CHUNK_FIXED_FIELD_SCHEMA"):
        chunks.empty_reader_fixed_fields_schema(schema)


def test_part_repair_prompt_reaffirms_ledger_owned_empty_wire_fields():
    base = [{"role": "system", "content": "Reader prompt"}, {"role": "user", "content": "input"}]

    repair = chunks.part_repair_messages(base, "PART_FIXED_FIELDS_MUST_BE_EMPTY")

    assert "reader_output.facts、reader_output.changes 必须为 []" in repair[0]["content"]
    assert "fixed_fact_ledger.reader_changes" in repair[0]["content"]
    assert base == [{"role": "system", "content": "Reader prompt"}, {"role": "user", "content": "input"}]
    assert repair[1] == base[1]


@pytest.mark.parametrize("model_changes", ["empty", "valid", "cross_article", "unknown", "reversed"])
def test_ordinary_projection_preserves_model_changes_and_strict_source_ranges(monkeypatch, model_changes):
    bridge_path = Path(__file__).resolve().parents[1] / "ops/run_manager_flash_announcements.py"
    spec = importlib.util.spec_from_file_location("announcement_projection_bridge_test", bridge_path)
    assert spec is not None and spec.loader is not None
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    monkeypatch.syspath_prepend(str(bridge.PIPELINE_ROOT))
    runner = importlib.import_module("batch_runner")

    body = (
        "Company name: Synthetic Issuer Limited\nStock code: 01234\n\n"
        "Opening statement.\n\n| Field | Value |\n|---|---|\n| Status | proposed |\n\n"
        "Opening balance 100\nIncrease / decrease 0\nEnding statement."
    )
    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    article_id = "EASTMONEY:AN202610180000000001"
    product_shas = ("1" * 64, "2" * 64)
    metadata = {
        "publication_date": "2026-10-18", "title": "Synthetic announcement",
        "issuer_name": "Synthetic Issuer Limited", "symbol": "HK.01234",
        "observed_at": "2026-10-18T10:00:00+08:00",
        "available_at": "2026-10-18T10:00:00+08:00", "pit_status": "CANNOT_CONFIRM",
        "source_origins": [
            {"source_ref": "synthetic://listing/row/0", "source_product_sha256": product_shas[0],
             "source_row_index": 0, "row_fingerprint_sha256": "3" * 64},
            {"source_ref": "synthetic://body/row/0", "source_product_sha256": product_shas[1],
             "source_row_index": 0, "row_fingerprint_sha256": "4" * 64},
        ],
    }
    unit_map = runner.build_source_unit_map(body, body_sha256)
    ledger = runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, metadata)
    assert ledger["reader_changes"]
    article = {
        "article_id": article_id, "source_sha256": "5" * 64, "body_sha256": body_sha256,
        "article_body": body, "article_metadata": metadata, "fixed_fact_ledger": ledger,
    }
    batch = {
        "schema": runner.INPUT_SCHEMA, "batch_id": "ledger-projection-test", "expected_count": 1,
        "source_products": [
            {"source_ref": "synthetic://listing", "sha256": product_shas[0]},
            {"source_ref": "synthetic://body", "sha256": product_shas[1]},
        ],
        "articles": [article],
    }
    payload = {
        "article_id": article_id,
        "source_sha256": article["source_sha256"], "body_sha256": body_sha256,
        "article_body": body, "article_metadata": metadata, "fixed_fact_ledger": ledger,
        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
        "validated_article_batch": batch,
    }
    wire_reader = {
        "disposition": "NOT_ASSESSED", "selection_basis": "NOT_ASSESSED", "direction": "UNKNOWN",
        "evidence_sufficiency": "INSUFFICIENT_EXISTING_FACTS", "reason": "Synthetic projection test.",
        "risk_notes": [], "facts": [], "changes": [], "impact": [],
        "confirmation_conditions": [], "counter_evidence": [], "source_sha256": "", "body_sha256": "",
    }
    if model_changes != "empty":
        first = unit_map["units"][0]
        last = unit_map["units"][-1]
        start = f"{article_id}::{first['source_unit_id']}"
        end = start
        if model_changes == "cross_article":
            start = "OTHER_ARTICLE::" + first['source_unit_id']
        elif model_changes == "unknown":
            start = article_id + "::U999999"
        elif model_changes == "reversed":
            start, end = f"{article_id}::{last['source_unit_id']}", start
        wire_reader["changes"] = [{"claim":first["text"].strip(),
            "start_source_unit_id":start, "end_source_unit_id":end}]
    envelope = {"action": "complete", "lookup_request": None, "reader_output": wire_reader}

    class Rejection(ValueError):
        def __init__(self, message, *, code):
            super().__init__(message)
            self.code = code

    validate = bridge._validator(
        SimpleNamespace(ValidationRejected=Rejection), runner, runner.load_active_contract(),
        {"citation_protocol": runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL}, None,
    )
    original_wire = deepcopy(envelope)
    original_ledger = deepcopy(ledger)
    if model_changes in {"cross_article", "unknown", "reversed"}:
        with pytest.raises(Rejection, match="SIMPLE_WORKFLOW_SOURCE_RANGE_"):
            validate(SimpleNamespace(payload=payload), envelope)
    else:
        validated = validate(SimpleNamespace(payload=payload), envelope)
        final_reader = validated["results"][0]["reader_output"]
        assert [v["claim"] for v in final_reader["changes"]] == [v["claim"] for v in wire_reader["changes"]]
        assert all(v["quote"] in body and v["locator"].startswith("article_body[codepoint:") for v in final_reader["changes"])
        assert ledger["reader_changes"]  # No ledger fallback for ordinary model-owned changes.
    assert envelope == original_wire and ledger == original_ledger


def test_selected_optional_conditions_and_counter_do_not_remove_required_positive_evidence():
    from v4.manager_workbench.engines.announcement import _validate_reader
    body = 'Company achieved a new operating milestone.'
    article = {'source_sha256':'1'*64, 'body_sha256':hashlib.sha256(body.encode()).hexdigest()}
    citation = {'claim':'The milestone occurred.', 'quote':body, 'locator':'body'}
    output = {'disposition':'SELECTED_EVENT', 'selection_basis':'OPERATING_EVENT', 'direction':'POSITIVE',
        'evidence_sufficiency':'VERIFIED_EXISTING_FACTS', 'reason':'The confirmed event supports operations.',
        'risk_notes':[], 'facts':[citation], 'changes':[citation], 'impact':[citation],
        'confirmation_conditions':[], 'counter_evidence':[], **article}
    _validate_reader(body, article, output)
    for field in ('facts', 'changes', 'impact'):
        bad = deepcopy(output); bad[field] = []
        with pytest.raises(ValueError, match='ANNOUNCEMENT_EVIDENCE_INCOMPLETE'):
            _validate_reader(body, article, bad)
    for direction in ('NEGATIVE', 'UNKNOWN', 'MIXED', 'NEUTRAL'):
        with pytest.raises(ValueError, match='ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'):
            _validate_reader(body, article, {**output, 'direction':direction})
    with pytest.raises(ValueError, match='ANNOUNCEMENT_SELECTED_SEMANTICS_INCONSISTENT'):
        _validate_reader(body, article, {**output, 'evidence_sufficiency':'INSUFFICIENT_EXISTING_FACTS'})
    bad = deepcopy(output); bad['impact'][0] = {**citation, 'quote':'invented fact'}
    with pytest.raises(ValueError, match='ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE'):
        _validate_reader(body, article, bad)


@pytest.mark.parametrize('drift', ['prompt_version', 'read_prompt', 'reader_schema', 'source_missing'])
def test_owned_request_contract_fails_closed_without_using_old_contract(drift):
    from test_manager_announcement_flash_runner import _bridge_module
    bridge = _bridge_module()
    frozen = SimpleNamespace(prompt_version='v1',read_prompt='fixed prompt',reader_schema={'type':'object'},source_sha256='1'*64)
    owned = deepcopy(frozen);owned.source_sha256='2'*64
    if drift=='source_missing':
        owned.source_sha256=None
    else:
        setattr(owned,drift,{'type':'array'} if drift=='reader_schema' else 'changed')
    called=[]
    helper=SimpleNamespace(_full_day_request_material=lambda contract:called.append(contract) or {})
    expected='OWNED_READER_CONTRACT_SHA_INVALID' if drift=='source_missing' else 'OWNED_READER_WIRE_CONTRACT_DRIFT'
    with pytest.raises(bridge.FlashRunError,match=expected):
        bridge._owned_request_material(helper,SimpleNamespace(load_active_contract=lambda:frozen),owned)
    assert not called if drift!='source_missing' else called==[frozen]


def test_owned_request_identity_preserves_external_source_and_binds_actual_validator():
    from test_manager_announcement_flash_runner import _bridge_module
    bridge = _bridge_module()
    frozen = SimpleNamespace(prompt_version='v1',read_prompt='fixed prompt',reader_schema={'type':'object'},source_sha256='1'*64)
    owned = deepcopy(frozen);owned.source_sha256='2'*64
    material={'configuration_material':{'model_id':'same-model'},'configuration_sha256':'3'*64,
        'source_code_sha256':{'external_contract.py':'1'*64},'canonical_contract_sha256':'1'*64,
        'prompt':'unchanged prompt','schema':{'type':'object'}}
    before=deepcopy(material)
    helper=SimpleNamespace(_full_day_request_material=lambda contract:material if contract is frozen else pytest.fail('misidentified source'))
    result=bridge._owned_request_material(helper,SimpleNamespace(load_active_contract=lambda:frozen),owned)
    assert material==before
    assert result['canonical_contract_sha256']=='1'*64
    assert result['source_code_sha256']=={'external_contract.py':'1'*64,'v4/manager_workbench/engines/announcement.py':'2'*64}
    assert result['configuration_material']['validation_contract_sha256']=='2'*64
    assert result['configuration_sha256']==bridge.sha(bridge.canonical(result['configuration_material']))
    assert result['prompt']==before['prompt'] and result['schema']==before['schema']
