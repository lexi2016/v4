import copy
import hashlib
import json
import pytest
from infrastructure.pdf_research import PageText
from infrastructure import pdf_research_protocol as p, pdf_research_validation as v


def specimen(text='原文称2026年收入超过10亿元。'):
    page = PageText(1, 1, text, 'OCR_OK', hashlib.sha256(text.encode()).hexdigest(), 'Vision')
    spans = p.evidence_spans([page])
    ev = [{'evidence_id': spans[0].evidence_id}]
    card = {'material_type': '研究材料', 'event_or_meeting_object': 'UNKNOWN',
        'speaker_and_source_attribution': [], 'date': {'value': None, 'basis': 'UNKNOWN', 'evidence': []},
        'facts': [{'claim': '原文称收入增长', 'attribution': 'UNKNOWN', 'period': '2026年', 'unit': 'UNKNOWN', 'evidence': ev}],
        'forecasts': [], 'inferences': [], 'numeric_values': [{'value_as_source': '10', 'sign': 'UNKNOWN',
            'unit': '亿元', 'currency': 'UNKNOWN', 'period': '2026年', 'actual_or_forecast': 'ACTUAL',
            'comparison_operator': 'GT', 'measure_kind': 'revenue', 'evidence': copy.deepcopy(ev)}],
        'related_entities': [], 'unknowns': [], 'source_usage_limits': [], 'risks': []}
    return card, spans, [page]


def test_valid_card_gets_program_owned_contiguous_quotes_and_pending_semantics():
    card, spans, pages = specimen()
    output = v.validate_protocol_card(json.dumps(card), spans, pages)
    bound = output['card']['facts'][0]['evidence'][0]
    assert bound['excerpt'] == pages[0].text[bound['start']:bound['end']]
    assert bound['excerpt_sha256'] == hashlib.sha256(bound['excerpt'].encode()).hexdigest()
    assert output['semantic_review'] == 'PENDING_INDEPENDENT_REVIEW'
    assert output['production_allowed'] is False


@pytest.mark.parametrize('case,code', [('quote', 'SCHEMA'), ('foreign', 'FOREIGN'), ('comparator', 'BOUND_LOST'),
    ('unit', 'UNIT_UNLINKED'), ('currency', 'CURRENCY_UNLINKED'), ('period', 'PERIOD_UNLINKED'),
    ('date', 'DATE_NOT_IN_EVIDENCE'), ('role', 'SPEAKER_AUTHOR'), ('inference', 'SCHEMA'), ('number', 'NUMBER_NOT_IN_EVIDENCE')])
def test_forbidden_evidence_and_numeric_linkages_fail(case, code):
    card, spans, pages = specimen()
    if case == 'quote': card['facts'][0]['evidence'][0]['excerpt'] = 'stitched quotation'
    if case == 'foreign': card['facts'][0]['evidence'][0]['evidence_id'] = 'f' * 64
    if case == 'comparator': card['numeric_values'][0]['comparison_operator'] = 'EQ'
    if case == 'unit': card['numeric_values'][0]['unit'] = '万元'
    if case == 'currency': card['numeric_values'][0]['currency'] = 'USD'
    if case == 'period': card['numeric_values'][0]['period'] = '2025年'
    if case == 'date': card['date'] = {'value': '2026-10-23', 'basis': '原文', 'evidence': card['facts'][0]['evidence']}
    if case == 'role': card['speaker_and_source_attribution'] = [{'entity': '原文', 'role': 'speaker', 'evidence': card['facts'][0]['evidence']}]
    if case == 'inference': card['inferences'] = card['facts']
    if case == 'number': card['facts'][0]['claim'] = '原文称利润999亿元'
    raw = json.dumps(card, ensure_ascii=False)
    with pytest.raises(v.CardValidationError, match=code): v.validate_protocol_card(raw, spans, pages)
    assert json.loads(raw) == card


def test_future_statement_cannot_be_made_historical_fact():
    card, spans, pages = specimen('原文预计2026年收入超过10亿元。')
    card['facts'][0]['claim'] = '预计收入增长'
    with pytest.raises(v.CardValidationError, match='FORECAST_CLASSIFIED|FORECAST_CLASSIFIED_AS_FACT'):
        v.validate_protocol_card(json.dumps(card), spans, pages)


def test_source_use_restriction_must_remain_bound():
    card, spans, pages = specimen('原文称2026年收入超过10亿元。不构成投资建议。')
    with pytest.raises(v.CardValidationError, match='SOURCE_USE_LIMIT_OMITTED'):
        v.validate_protocol_card(json.dumps(card), spans, pages)
    card['source_usage_limits'] = [{'limitation': '不构成投资建议', 'evidence': [{'evidence_id': spans[-1].evidence_id}]}]
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'


@pytest.mark.parametrize('glyph,sign', [('-', 'NEGATIVE'), ('+', 'POSITIVE')])
def test_source_numeric_sign_cannot_be_lost_when_magnitude_is_retained(glyph, sign):
    card, spans, pages = specimen(f'原文称2026年收入{glyph}10亿元。')
    card['numeric_values'][0]['comparison_operator'] = 'EQ'
    with pytest.raises(v.CardValidationError, match='SIGN_LOST'):
        v.validate_protocol_card(json.dumps(card), spans, pages)
    card['numeric_values'][0]['sign'] = sign
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'


@pytest.mark.parametrize('source,wrong', [('10', '1'), ('101', '10'), ('1.25', '1.2'),
    ('.5', '5'), ('1,000', '000'), ('1e3', '1'), ('-10', '1'), ('+10', '1')])
def test_numeric_value_cannot_borrow_an_adjacent_decimal_or_signed_subtoken(source, wrong):
    card, spans, pages = specimen(f'原文称2026年收入{source}亿元。')
    card['numeric_values'][0].update(value_as_source=wrong, comparison_operator='EQ')
    with pytest.raises(v.CardValidationError, match='NUMERIC_VALUE_NOT_IN_EVIDENCE'):
        v.validate_protocol_card(json.dumps(card), spans, pages)


@pytest.mark.parametrize('source', ['10', '1.25', '.5', '1,000', '1e3'])
def test_complete_numeric_token_and_existing_context_remain_usable(source):
    card, spans, pages = specimen(f'原文称2026年收入{source}亿元。')
    card['numeric_values'][0].update(value_as_source=source, comparison_operator='EQ')
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'


def test_claim_magnitude_and_sign_are_bound_independently_of_numeric_table():
    card, spans, pages = specimen('原文称2026年收入-10亿元。')
    card['numeric_values'][0].update(sign='NEGATIVE', comparison_operator='EQ')
    for claim in ('原文称2026年收入1亿元', '原文称2026年收入10亿元'):
        card['facts'][0]['claim'] = claim
        with pytest.raises(v.CardValidationError, match='CLAIM_NUMBER_NOT_IN_EVIDENCE'):
            v.validate_protocol_card(json.dumps(card), spans, pages)
    card['facts'][0]['claim'] = '原文称2026年收入-10亿元'
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'


@pytest.mark.parametrize('source,sign', [('- 10', 'NEGATIVE'), ('＋10', 'POSITIVE'), ('－10', 'NEGATIVE')])
def test_source_sign_glyph_and_spacing_do_not_authenticate_unsigned_unknown(source, sign):
    card, spans, pages = specimen(f'原文称2026年收入{source}亿元。')
    card['numeric_values'][0]['comparison_operator'] = 'EQ'
    with pytest.raises(v.CardValidationError, match='SIGN_LOST'):
        v.validate_protocol_card(json.dumps(card), spans, pages)
    card['numeric_values'][0]['sign'] = sign
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'


@pytest.mark.parametrize('value', ['166.0', '10.40'])
def test_decimal_layout_break_requires_both_exact_adjacent_cited_spans(value):
    left, right = value.split('.')
    card, spans, pages = specimen(f'原文称2026年收入{left}.\n{right}亿元。')
    original_excerpts = [span.text for span in spans]
    card['numeric_values'][0].update(value_as_source=value, comparison_operator='EQ',
        evidence=[{'evidence_id': span.evidence_id} for span in spans])
    result = v.validate_protocol_card(json.dumps(card), spans, pages)
    assert [ev['excerpt'] for ev in result['card']['numeric_values'][0]['evidence']] == original_excerpts
    card['numeric_values'][0]['evidence'].pop()
    with pytest.raises(v.CardValidationError, match='VALUE_NOT_IN_QUOTE'):
        v.validate_protocol_card(json.dumps(card), spans, pages)


@pytest.mark.parametrize('case', ['nonadjacent', 'cross_page', 'foreign', 'duplicate', 'reverse', 'integer_rows'])
def test_numeric_fragments_cannot_join_unproven_source_boundaries(case):
    text = '原文称2026年收入166.\n' + ('无关段落。\n' if case == 'nonadjacent' else '') + '0亿元。'
    if case == 'integer_rows':
        text = '原文称2026年收入16\n60亿元。'
    card, spans, pages = specimen(text)
    if case == 'cross_page':
        texts = ['原文称2026年收入166.\n', '0亿元。']
        pages = [PageText(i, 2, txt, 'OCR_OK', hashlib.sha256(txt.encode()).hexdigest(), 'Vision') for i, txt in enumerate(texts, 1)]
        spans = p.evidence_spans(pages)
    evidence = [{'evidence_id': spans[0].evidence_id}, {'evidence_id': spans[-1].evidence_id}]
    if case == 'foreign': evidence[-1]['evidence_id'] = 'f' * 64
    if case == 'duplicate': evidence.append(copy.deepcopy(evidence[0]))
    if case == 'reverse': evidence.reverse()
    card['numeric_values'][0].update(value_as_source='1660' if case == 'integer_rows' else '166.0',
        comparison_operator='EQ', evidence=evidence)
    with pytest.raises(v.CardValidationError, match='VALUE_NOT_IN_QUOTE|FOREIGN'):
        v.validate_protocol_card(json.dumps(card), spans, pages)


@pytest.mark.parametrize('change,code', [('comparison_operator', 'BOUND_LOST'), ('sign', 'SIGN_LOST'),
    ('unit', 'UNIT_UNLINKED'), ('period', 'PERIOD_UNLINKED'), ('actual_or_forecast', 'FORECAST_NUMBER')])
def test_contiguous_decimal_keeps_other_numeric_gates(change, code):
    forecast = change == 'actual_or_forecast'
    card, spans, pages = specimen('原文' + ('预计' if forecast else '称') + '2026年收入超过-166.\n0亿元。')
    if forecast:
        card['forecasts'], card['facts'] = card['facts'], []
    card['numeric_values'][0].update(value_as_source='-166.0', comparison_operator='GT', sign='NEGATIVE',
        evidence=[{'evidence_id': span.evidence_id} for span in spans])
    card['numeric_values'][0][change] = {'comparison_operator': 'EQ', 'sign': 'UNKNOWN',
        'unit': '万元', 'period': '2025年', 'actual_or_forecast': 'ACTUAL'}[change]
    with pytest.raises(v.CardValidationError, match=code):
        v.validate_protocol_card(json.dumps(card), spans, pages)


def test_more_than_five_facts_and_forecasts_and_current_source_move():
    card, spans, pages = specimen()
    card['facts'] *= 8
    card['forecasts'] = copy.deepcopy(card['facts'])
    assert v.validate_protocol_card(json.dumps(card), spans, pages)['deterministic_status'] == 'PASS'
    projected = v.validate_protocol_card(json.dumps(card), spans, pages)['card']
    legacy = {key: value for key, value in projected.items() if key != 'risks'}
    for field in ('facts', 'forecasts', 'numeric_values'):
        for row in legacy[field]:
            row['evidence'] = [{key: ev[key] for key in ('page_number', 'text_sha256', 'excerpt')} for ev in row['evidence']]
    legacy['numeric_values'] = []
    for row in legacy['forecasts']:
        row.update(claim='目前公司收入增长', period='目前')
    source = '目前公司收入增长。'
    page_rows = [{'page_number': 1, 'text': source, 'text_sha256': hashlib.sha256(source.encode()).hexdigest()}]
    for row in legacy['forecasts']:
        row['evidence'] = [{'page_number': 1, 'text_sha256': page_rows[0]['text_sha256'], 'excerpt': source}]
    audit = []
    v.normalize_source_constraints(legacy, page_rows, audit, raw_inner_sha256='a' * 64)
    assert len(legacy['facts']) == 16 and not legacy['forecasts']


@pytest.mark.parametrize('field', ['facts', 'forecasts'])
@pytest.mark.parametrize('value', ['166.0', '10.40'])
def test_claim_decimal_continuity_uses_only_its_exact_cited_adjacent_spans(field, value):
    left, right = value.split('.')
    card, spans, pages = specimen(f'原文称2026年收入{left}.\n{right}亿元。')
    claim = card['facts'][0]
    claim.update(claim=f'原文称2026年收入{value}亿元',
        evidence=[{'evidence_id': span.evidence_id} for span in spans])
    card['numeric_values'] = []
    if field == 'forecasts':
        card['forecasts'], card['facts'] = card['facts'], []
    result = v.validate_protocol_card(json.dumps(card), spans, pages)
    assert [ev['excerpt'] for ev in result['card'][field][0]['evidence']] == [span.text for span in spans]
    claim['evidence'].pop()
    with pytest.raises(v.CardValidationError, match='CLAIM_NUMBER_NOT_IN_EVIDENCE'):
        v.validate_protocol_card(json.dumps(card), spans, pages)


@pytest.mark.parametrize('case', ['nonadjacent', 'cross_page', 'foreign', 'duplicate', 'reverse',
    'integer_rows', 'missing_period', 'lost_sign', 'uncited_prefix'])
def test_claim_decimal_reconstruction_preserves_other_source_linkages(case):
    text = '原文称2026年收入166.\n' + ('无关段落。\n' if case == 'nonadjacent' else '') + '0亿元。'
    if case == 'integer_rows': text = '原文称2026年收入16\n60亿元。'
    if case == 'lost_sign': text = '原文称2026年收入-166.\n0亿元。'
    if case == 'uncited_prefix': text = '原文称3.2\nT相关产品研发推进。'
    card, spans, pages = specimen(text)
    if case == 'cross_page':
        texts = ['原文称2026年收入166.\n', '0亿元。']
        pages = [PageText(i, 2, txt, 'OCR_OK', hashlib.sha256(txt.encode()).hexdigest(), 'Vision') for i, txt in enumerate(texts, 1)]
        spans = p.evidence_spans(pages)
    evidence = [{'evidence_id': spans[0].evidence_id}, {'evidence_id': spans[-1].evidence_id}]
    if case == 'foreign': evidence[-1]['evidence_id'] = 'f' * 64
    if case == 'duplicate': evidence.append(copy.deepcopy(evidence[0]))
    if case == 'reverse': evidence.reverse()
    claim = card['facts'][0]
    claim.update(claim='原文称收入' + ('1660' if case == 'integer_rows' else '166.0') + '亿元',
        period='8月' if case == 'missing_period' else 'UNKNOWN', evidence=evidence)
    if case == 'uncited_prefix':
        claim.update(claim='3.2T相关产品研发推进', evidence=[evidence[-1]], unit='UNKNOWN')
    card['numeric_values'] = []
    with pytest.raises(v.CardValidationError, match='CLAIM_NUMBER_NOT_IN_EVIDENCE|FOREIGN|CLAIM_PERIOD_UNLINKED'):
        v.validate_protocol_card(json.dumps(card), spans, pages)
