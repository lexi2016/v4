import hashlib
import json
import pytest
from infrastructure import pdf_research_protocol as protocol
from infrastructure.pdf_research import PageText, _schema_error


def test_v2_is_explicit_and_short_aliases_only_cover_provided_sources(monkeypatch):
    from infrastructure import pdf_research_claims as claims
    assert protocol.PROTOCOL_VERSION == 'pdf-card-evidence-v1'
    for key in ('PROTOCOL_VERSION', 'SEMANTIC_PIPELINE_VERSION', 'PROMPT', 'SCHEMA', 'PROTOCOL_SHA256'):
        monkeypatch.setattr(protocol, key, getattr(protocol, key))
    protocol.enable_claims_v2()
    text = '公司收入超过6亿元。\n预计未来增长。'
    page = PageText(1, 1, text, 'OCR_OK', hashlib.sha256(text.encode()).hexdigest())
    spans = protocol.evidence_spans([page])
    request = json.loads(protocol.request_messages(spans, {})[1]['content'])
    assert request['source_spans'] == [{'evidence_id': 'S1', 'page_number': 1, 'text': text}]
    assert protocol.SCHEMA == claims.SCHEMA
    assert set(protocol.SCHEMA['properties']) == {'claims', 'unknowns'}


def test_prompt_refinement_keeps_general_source_and_field_contracts():
    for instruction in ('所有必要片段', '系统提示', '相应列表为空', '当前研发', '未来判断分别处理',
                        'comparison_operator', '为EQ', '为GE', '为GT', '为LE', '为LT', '为APPROX', '为RANGE',
                        '真正的JSON null', '不自动等于发言者或作者', 'inferences必须为空'):
        assert instruction in protocol.PROMPT
    assert all(not character.isdigit() for character in protocol.PROMPT)
    assert protocol.request_messages([], {})[0] == {'role': 'system', 'content': protocol.PROMPT}


def test_schema_directly_constrains_pdf_card_and_evidence_ids():
    assert 'analysis_markdown' not in protocol.SCHEMA['properties']
    assert set(protocol.SCHEMA['required']) == set(protocol.SCHEMA['properties'])
    assert protocol.SCHEMA['properties']['inferences']['maxItems'] == 0
    assert _schema_error({'analysis_markdown': '{}'}, protocol.SCHEMA)
    evidence = protocol.SCHEMA['properties']['facts']['items']['properties']['evidence']['items']
    assert set(evidence['properties']) == {'evidence_id'}
    for field in ('facts', 'forecasts'):
        assert 'maxItems' not in protocol.SCHEMA['properties'][field]


def test_long_table_and_mixed_page_spans_cover_exact_original_text_without_truncation():
    texts = ['公司\t收入\t利润\n甲\t10\t3\n' * 800, '原文称公司扩产。\n预计未来增长。' * 500]
    pages = [PageText(n, 2, text, 'NATIVE_TEXT' if n == 1 else 'OCR_OK', hashlib.sha256(text.encode()).hexdigest(), 'native' if n == 1 else 'Vision') for n, text in enumerate(texts, 1)]
    spans = protocol.evidence_spans(pages)
    groups = protocol.chunk_spans(spans, {'source_document_date': None})
    assert len(groups) > 1
    assert [x for group in groups for x in group] == list(spans)
    assert spans == protocol.evidence_spans(pages)
    for page in pages:
        relevant = [x for x in spans if x.page_number == page.page_number]
        assert ''.join(x.text for x in relevant) == page.text
        assert relevant[0].start == 0 and relevant[-1].end == len(page.text)
        assert all(a.end == b.start for a, b in zip(relevant, relevant[1:]))
    for group in groups:
        envelope = protocol.request_envelope(protocol.request_messages(group, {'source_document_date': None}))
        assert len(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) <= 32768
        assert envelope['structured_outputs']['json'] == protocol.SCHEMA
        assert 'tools' not in envelope
