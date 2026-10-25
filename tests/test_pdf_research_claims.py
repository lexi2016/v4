import dataclasses
import json

import pytest

from infrastructure import pdf_research_claims as c
from infrastructure import pdf_research_protocol as p
from infrastructure.pdf_research import PageText
from infrastructure.pdf_research_validation import CardValidationError


def pages_of(*texts):
    return [PageText(n, len(texts), text, 'OCR_OK', c.sha(text.encode()), 'existing OCR')
            for n, text in enumerate(texts, 1)]


def answer(statement, ids=('S1',), subject='UNKNOWN', attribution='UNKNOWN', kind='FACT'):
    return json.dumps({'claims': [{'statement': statement, 'kind': kind, 'subject': subject,
        'attribution': attribution, 'evidence': [{'evidence_id': x} for x in ids]}],
        'unknowns': []}, ensure_ascii=False)


def test_coherent_blocks_preserve_every_source_character_and_table_boundary():
    pages = pages_of('甲公司\n当前收入接近10亿元，两项业务均大幅增长。\n预计后续扩产。',
        '公司\t实际\t预测\n甲\t1 2\t500 +\n' * 100)
    spans = c.evidence_spans(pages)
    assert len([s for s in spans if s.page_number == 1]) == 1
    for page in pages:
        selected = [s for s in spans if s.page_number == page.page_number]
        assert ''.join(s.text for s in selected) == page.text
        assert selected[0].start == 0 and selected[-1].end == len(page.text)
        assert all(a.end == b.start for a, b in zip(selected, selected[1:]))
    value = c.validate(answer('当前收入接近10亿元，两项业务均大幅增长。',
        subject='甲公司'), spans[:1], pages)
    assert value['card']['claims'][0]['evidence'][0]['excerpt'] == pages[0].text
    assert value['semantic_review'] == 'PENDING_INDEPENDENT_REVIEW'
    assert value['normalization_audit'] == []


@pytest.mark.parametrize('source,changed', [('1 2', '12'), ('1\t2', '12'), ('1\n2', '12'),
    ('166.\n0', '166.0'), ('500 +', '500+'), ('接近10亿元', '10.0亿元'), ('-2.19%', '2.19%')])
def test_no_whitespace_or_numeric_repair(source, changed):
    pages = pages_of(source)
    spans = c.evidence_spans(pages)
    with pytest.raises(CardValidationError, match='STATEMENT_NOT_IN_CITED_RUN'):
        c.validate(answer(changed), spans, pages)
    assert c.validate(answer(source), spans, pages)['deterministic_status'] == 'PASS'


def test_only_same_page_adjacent_in_order_spans_may_form_a_run():
    pages = pages_of('甲公司收入500+，预计未来增长。甲公司目前持续研发。')
    spans = c.evidence_spans(pages, maximum=8)
    assert len(spans) > 2
    statement = spans[0].text + spans[1].text
    assert c.validate(answer(statement, ('S1', 'S2')), spans, pages)['deterministic_status'] == 'PASS'
    for statement, ids in [(spans[0].text + spans[2].text, ('S1', 'S3')),
                           (spans[1].text + spans[0].text, ('S2', 'S1'))]:
        with pytest.raises(CardValidationError, match='STATEMENT_NOT_IN_CITED_RUN'):
            c.validate(answer(statement, ids), spans, pages)
    pages = pages_of('1', '2')
    with pytest.raises(CardValidationError, match='STATEMENT_NOT_IN_CITED_RUN'):
        c.validate(answer('12', ('S1', 'S2')), c.evidence_spans(pages), pages)


def test_subject_and_attribution_are_bound_only_to_cited_source_not_full_pages():
    pages = pages_of('国盛证券认为甲公司收入超过6亿元。', '其他公司的收入增长。')
    spans = c.evidence_spans(pages)
    value = c.validate(answer('甲公司收入超过6亿元。', subject='甲公司', attribution='国盛证券'), spans, pages)
    claim = value['card']['claims'][0]
    assert claim['attribution'] == '国盛证券' and 'source_author' not in claim
    assert claim['claim_id'] and len(claim['evidence'][0]['evidence_id']) == 64
    with pytest.raises(CardValidationError, match='ATTRIBUTION_UNLINKED'):
        c.validate(answer('其他公司的收入增长。', ('S2',), attribution='国盛证券'), spans, pages)
    with pytest.raises(CardValidationError, match='MODEL_EVIDENCE_UNKNOWN'):
        c.validate(answer('收入', ('S999',)), spans, pages)


def test_local_integrity_errors_are_never_content_errors():
    pages = pages_of('原文业务增长。')
    spans = c.evidence_spans(pages)
    for broken, code in [([spans[0], spans[0]], 'PDF_DUPLICATE_EVIDENCE_ID'),
                         ([dataclasses.replace(spans[0], end=2)], 'PDF_EVIDENCE_INPUT_SHA_MISMATCH')]:
        with pytest.raises(CardValidationError) as exc:
            c.validate(answer('原文业务增长。'), broken, pages)
        assert exc.value.code == code
        assert code not in c.CONTENT_ERRORS


def test_chunk_primary_coverage_and_overlap_are_exact(monkeypatch):
    for key in ('PROTOCOL_VERSION', 'SEMANTIC_PIPELINE_VERSION', 'PROMPT', 'SCHEMA', 'PROTOCOL_SHA256'):
        monkeypatch.setattr(p, key, getattr(p, key))
    p.enable_claims_v2()
    pages = pages_of(*[f'第{n}页公司当前有业务。' * 65 for n in range(12)])
    spans = p.evidence_spans(pages)
    groups = p.chunk_spans(spans, {})
    rows = c.coverage(groups)
    assert len(groups) > 1 and any(row['overlap'] for row in rows)
    assert [x['evidence_id'] for r in rows for x in r['primary']] == [s.evidence_id for s in spans]
    for group in groups:
        request = p.request_envelope(p.request_messages(group, {}))
        assert len(canonical_json(request)) <= 32768
        assert sum(len(s.text) for s in group) <= 8000


from infrastructure.pdf_research_identity import canonical_json


def test_compatibility_reasoning_repetition_is_not_independent_thinking():
    from ops.run_pdf_flow_repair_trial import stream_diagnostic
    frames = [dict(id='response-1', choices=[dict(delta={'content': '{"claims":[]}',
        'reasoning_content': '{"claims":[]}'}, finish_reason='stop')], usage={'completion_tokens': 8})]
    raw = b''.join(b'data: ' + json.dumps(frame).encode() + b'\n\n' for frame in frames) + b'data: [DONE]\n\n'
    result = stream_diagnostic(raw)
    assert result['reasoning_status'] == 'COMPATIBILITY_REASONING_EQUALS_FINAL'
    assert result['independent_reasoning'] == 'NOT_PROVEN'
    assert result['done'] and result['finish_reasons'] == ['stop']
