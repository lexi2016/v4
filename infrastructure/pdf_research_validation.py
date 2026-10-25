"""PDF structure/evidence checks; semantic acceptance remains independent.

The legacy LIGHT comparator/format functions below retain their verified scope.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence
from infrastructure import pdf_text_source

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

def fail(code: str) -> None:
    raise pdf_text_source.BatchError(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _compact(text:str) -> str:
    return ''.join(c for c in text if not c.isspace())


def source_limit_quotes(pages:Sequence[Mapping[str,Any]]) -> list[dict[str,Any]]:
    found=[];seen=set()
    patterns=(r'调研内容[^。]{0,350}?不构成[^。]{0,350}?为准[。]?',r'不构成投资建议[^。]{0,250}[。]?')
    for page in pages:
        for pattern in patterns:
            for match in re.finditer(pattern,page['text']):
                quote=match.group();key=(page['page_number'],_compact(quote))
                if key in seen:continue
                seen.add(key);found.append({'page_number':page['page_number'],'text_sha256':page['text_sha256'],'excerpt':quote})
    return found


def canonicalize_citations(raw_inner:str,pages:Sequence[Mapping[str,Any]],*,audit_sink:list[dict[str,Any]]|None=None) -> tuple[dict[str,Any],list[dict[str,Any]]]:
    card=json.loads(raw_inner);result=copy.deepcopy(card);page_map={p['page_number']:p for p in pages};audit=[] if audit_sink is None else audit_sink
    normalize_evidence_shape(result,pages,audit,raw_inner_sha256=sha(raw_inner.encode()))
    def visit(value:Any,path:str) -> None:
        if isinstance(value,dict):
            if set(value)=={'page_number','text_sha256','excerpt'}:
                if type(value['page_number']) is not int or not isinstance(value['text_sha256'],str):fail('FULL_CITATION_INVALID')
                page=page_map.get(value['page_number']);quote=value['excerpt']
                if not page or page['text_sha256']!=value['text_sha256'] or not isinstance(quote,str) or not 1<=len(quote)<=300:fail('FULL_CITATION_NOT_EXACT_SOURCE')
                if quote in page['text']:return
                compact=_compact(quote);flat=_compact(page['text'])
                if not compact:fail('FULL_CITATION_NOT_EXACT_SOURCE')
                hits=[];offset=0
                while True:
                    index=flat.find(compact,offset)
                    if index<0:break
                    hits.append(index);offset=index+1
                if len(hits)!=1:fail('FULL_CITATION_WHITESPACE_SPAN_NOT_UNIQUE')
                indexes=[i for i,c in enumerate(page['text']) if not c.isspace()]
                start=indexes[hits[0]];end=indexes[hits[0]+len(compact)-1]+1;actual=page['text'][start:end]
                if _compact(actual)!=compact or len(actual)>300:fail('FULL_CITATION_NOT_EXACT_SOURCE')
                audit.append({'path':path,'transformation':'UNIQUE_WHITESPACE_EQUIVALENT_SOURCE_SPAN','page_number':page['page_number'],'page_text_sha256':page['text_sha256'],'raw_inner_sha256':sha(raw_inner.encode()),'original_excerpt':quote,'original_excerpt_sha256':sha(quote.encode()),'source_start_character':start,'source_end_character':end,'source_excerpt':actual,'source_excerpt_sha256':sha(actual.encode())})
                value['excerpt']=actual;return
            for key,item in value.items():visit(item,path+'.'+key)
        elif isinstance(value,list):
            for i,item in enumerate(value):visit(item,f'{path}[{i}]')
    visit(result,'card')
    # UNKNOWN is a schema sentinel, never a guessed source entity/name.
    roles=result.get('speaker_and_source_attribution',[]) if isinstance(result,dict) else []
    if isinstance(roles,list):
        for index,item in enumerate(roles):
            if isinstance(item,dict) and item.get('role')=='UNKNOWN' and isinstance(item.get('entity'),str) and item['entity'].casefold()=='unknown' and item['entity']!='UNKNOWN':
                audit.append({'path':f'card.speaker_and_source_attribution[{index}].entity','transformation':'SCHEMA_UNKNOWN_SENTINEL_CASE_NORMALIZATION','rule_version':'LIGHT_SOURCE_CONSTRAINTS_V1','source_page_sha256':{str(p['page_number']):p['text_sha256'] for p in pages},'before_path':f'card.speaker_and_source_attribution[{index}].entity','after_path':f'card.speaker_and_source_attribution[{index}].entity','raw_inner_sha256':sha(raw_inner.encode()),'original_value':item['entity'],'canonical_value':'UNKNOWN','role':'UNKNOWN','no_source_entity_identity_inferred':True})
                item['entity']='UNKNOWN'
    normalize_source_constraints(result,pages,audit,raw_inner_sha256=sha(raw_inner.encode()))
    normalize_percent_value_glyph(result,pages,audit,raw_inner_sha256=sha(raw_inner.encode()))
    return result,audit


def normalize_evidence_shape(card:Any,pages:Sequence[Mapping[str,Any]],audit:list[dict[str,Any]],*,raw_inner_sha256:str) -> None:
    """Only a fully typed evidence object at a known field may become one list item."""
    if not isinstance(card,dict):return
    holders=[]
    if isinstance(card.get('date'),dict):holders.append(('card.date',card['date']))
    for field in ['facts','forecasts','inferences','numeric_values','speaker_and_source_attribution','source_usage_limits']:
        if isinstance(card.get(field),list):
            holders.extend((f'card.{field}[{i}]',item) for i,item in enumerate(card[field]) if isinstance(item,dict))
    for path,item in holders:
        ev=item.get('evidence')
        if (not isinstance(ev,dict) or set(ev)!={'page_number','text_sha256','excerpt'}
                or type(ev['page_number']) is not int or not isinstance(ev['text_sha256'],str)
                or not SHA256_RE.fullmatch(ev['text_sha256']) or not isinstance(ev['excerpt'],str) or not 1<=len(ev['excerpt'])<=300):continue
        original=copy.deepcopy(ev);item['evidence']=[ev]
        audit.append({'transformation':'TYPED_EVIDENCE_SINGLETON_LIST','rule_version':'LIGHT_FORMAT_COMPATIBILITY_V1',
                      'before_path':path+'.evidence','after_path':path+'.evidence','original_value':original,'canonical_value':[copy.deepcopy(ev)],
                      'raw_inner_sha256':raw_inner_sha256,'source_page_sha256':{str(p['page_number']):p['text_sha256'] for p in pages},
                      'semantic_acceptance':'NOT_GRANTED_BY_SHAPE_NORMALIZATION'})


def normalize_percent_value_glyph(card:Any,pages:Sequence[Mapping[str,Any]],audit:list[dict[str,Any]],*,raw_inner_sha256:str) -> None:
    """Copy only a percent glyph variant from an already exact bound quote."""
    if not isinstance(card,dict) or not isinstance(card.get('numeric_values'),list):return
    page_map={p['page_number']:p for p in pages}
    for index,item in enumerate(card['numeric_values']):
        if not isinstance(item,dict) or not isinstance(item.get('value_as_source'),str) or not isinstance(item.get('evidence'),list):continue
        value=item['value_as_source'];evs=item['evidence']
        if not any(c in value for c in '%％') or any(isinstance(e,dict) and isinstance(e.get('excerpt'),str) and value in e['excerpt'] for e in evs):continue
        alternate=value.translate(str.maketrans({'%':'％','％':'%'}));bound=[]
        for ev in evs:
            if not isinstance(ev,dict) or set(ev)!={'page_number','text_sha256','excerpt'} or type(ev['page_number']) is not int:continue
            page=page_map.get(ev['page_number']);quote=ev['excerpt']
            if page and ev['text_sha256']==page['text_sha256'] and isinstance(quote,str) and quote in page['text'] and re.search(r'(?<![\d.,+＋－-])'+re.escape(alternate)+r'(?![\d.,])',quote):
                start=page['text'].find(quote);bound.append({**ev,'source_start_character':start,'source_end_character':start+len(quote)})
        if not bound:continue
        item['value_as_source']=alternate
        path=f'card.numeric_values[{index}].value_as_source'
        audit.append({'transformation':'EXACT_SOURCE_PERCENT_GLYPH','rule_version':'LIGHT_FORMAT_COMPATIBILITY_V1','before_path':path,'after_path':path,
                      'original_value':value,'canonical_value':alternate,'source_spans':bound,'raw_inner_sha256':raw_inner_sha256,
                      'source_page_sha256':{str(p['page_number']):p['text_sha256'] for p in pages},'magnitude_sign_unit_period_unchanged':True})


def normalize_source_constraints(card:Any,pages:Sequence[Mapping[str,Any]],audit:list[dict[str,Any]],*,raw_inner_sha256:str) -> None:
    if not isinstance(card,dict):return  # The strict schema validator owns malformed outer fields.
    page_map={p['page_number']:p for p in pages}
    future=re.compile(r'未来|预计|预测|有望|后续|将|计划|目标|情景|假设|展望|拟|可能|\d{4}E|\b(?:will|expect|forecast|scenario|target|next)\b',re.I)
    base={'rule_version':'LIGHT_SOURCE_CONSTRAINTS_V1','raw_inner_sha256':raw_inner_sha256,'source_page_sha256':{str(p['page_number']):p['text_sha256'] for p in pages}}
    def spans(item:Mapping[str,Any]) -> list[dict[str,Any]]:
        evidence=item.get('evidence')
        if not isinstance(evidence,list) or not evidence:fail('FULL_CITATION_REQUIRED')
        found=[]
        for ev in evidence:
            if not isinstance(ev,dict) or set(ev)!={'page_number','text_sha256','excerpt'} or type(ev['page_number']) is not int or not isinstance(ev['text_sha256'],str):fail('FULL_CITATION_INVALID')
            page=page_map.get(ev['page_number']);quote=ev['excerpt']
            if not page or ev['text_sha256']!=page['text_sha256'] or not isinstance(quote,str) or not 1<=len(quote)<=300 or quote not in page['text']:fail('FULL_CITATION_NOT_EXACT_SOURCE')
            start=page['text'].find(quote)
            found.append({**ev,'source_start_character':start,'source_end_character':start+len(quote),'unique_source_span':page['text'].find(quote,start+1)<0})
        return found
    facts=card.get('facts');forecasts=card.get('forecasts')
    if isinstance(facts,list) and isinstance(forecasts,list):
        kept=[]
        for index,item in enumerate(forecasts):
            if isinstance(item,dict) and isinstance(item.get('period'),str) and item['period'].strip() in {'当前','目前','现在'} and isinstance(item.get('claim'),str):
                bound=spans(item);token=item['period'].strip()
                if not any(token in e['excerpt'] for e in bound) or future.search(item['claim']+' '+''.join(e['excerpt'] for e in bound)):fail('FULL_CURRENT_TEMPORAL_EVIDENCE_AMBIGUOUS')
                audit.append({**base,'transformation':'EXPLICIT_CURRENT_SOURCE_STATEMENT','before_path':f'card.forecasts[{index}]','after_path':f'card.facts[{len(facts)}]','original_value':copy.deepcopy(item),'canonical_value':copy.deepcopy(item),'source_spans':bound,'reason':'EXPLICIT_CURRENT_SOURCE_ATTRIBUTION_NO_FUTURE_MARKER'})
                facts.append(item);continue
            kept.append(item)
        card['forecasts']=kept
    numbers=card.get('numeric_values')
    if isinstance(numbers,list):
        kept=[]
        for index,item in enumerate(numbers):
            if isinstance(item,dict) and item.get('measure_kind')=='price_return' and isinstance(item.get('period'),str) and item['period'].strip()=='UNKNOWN':
                bound=spans(item)
                tail=all(e['unique_source_span'] and not re.search(r'产能|产量|年产|收入|利润|capacity|revenue|profit',e['excerpt'],re.I) and not page_map[e['page_number']]['text'][e['source_end_character']:].strip() and re.fullmatch(r'[^\n。;；]{0,60}[-+＋－]\d+(?:[.,]\d+)*\s*[%％]',e['excerpt'].strip()) for e in bound)
                if tail:
                    audit.append({**base,'transformation':'UNPERIODIZED_FOOTER_RETURN_EXCLUDED','before_path':f'card.numeric_values[{index}]','after_path':None,'original_value':copy.deepcopy(item),'canonical_value':None,'source_spans':bound,'reason':'NONCORE_PAGE_TAIL_PRICE_RETURN_WITHOUT_TIME_BASIS_NO_PERIOD_INFERRED'});continue
            kept.append(item)
        card['numeric_values']=kept
    unknowns=card.get('unknowns')
    if isinstance(unknowns,list):
        kept=[];excluded=False
        for index,item in enumerate(unknowns):
            if isinstance(item,str) and re.search(r'(?:19|20)\d{2}',item) and re.search(r'推测|猜测|推断|估计|可能为|推定|推算',item) and re.search(r'年份|日期|事件年|调研.{0,8}年',item):
                audit.append({**base,'transformation':'UNSUPPORTED_DATE_GUESS_NOT_ADOPTED','before_path':f'card.unknowns[{index}]','after_path':'card.unknowns','original_value':item,'canonical_value':'模型对事件年份的猜测未被采用；原文未明示的事件年份保持UNKNOWN，不依据发布日期补齐。','reason':'EXPLICIT_DATE_GUESS_WITH_PROPOSED_YEAR_NOT_ACCEPTED_RESEARCH_CONTENT'});excluded=True
            else:kept.append(item)
        if excluded:kept.append('模型对事件年份的猜测未被采用；原文未明示的事件年份保持UNKNOWN，不依据发布日期补齐。')
        card['unknowns']=kept


def _source_comparator(value:str,evidences:Sequence[Mapping[str,Any]]) -> str|None:
    if re.fullmatch(r'\s*[-+]?\d+(?:[.,]\d+)*\s*[-~～–—至]\s*[-+]?\d+(?:[.,]\d+)*\s*',value) and any(value in e['excerpt'] for e in evidences):return 'RANGE'
    number=re.search(r'[-+]?\d+(?:[.,]\d+)*',value)
    if number is None:return None
    operators=[]
    patterns=[('GE',r'(?:不少于|不低于|不小于|至少|≥|>=)\s*$'),('LE',r'(?:不超过|不超|不高于|不大于|至多|≤|<=)\s*$'),('GT',r'(?:超过|超|高于|大于|>)\s*$'),('LT',r'(?:少于|低于|小于|<)\s*$'),('APPROX',r'(?:接近|约为|大约|约)\s*$')]
    for evidence in evidences:
        quote=evidence['excerpt']
        for match in re.finditer(r'(?<![\d.,])'+re.escape(number.group())+r'(?![\d.,])',quote):
            prefix=quote[max(0,match.start()-12):match.start()]
            operator=next((op for op,pattern in patterns if re.search(pattern,prefix)),'EQ')
            if re.match(r'\s*\+',quote[match.end():]):
                if operator=='EQ':operator='GE'
                elif operator!='GE':return None  # e.g. 约60+ has both approximation and a bound; do not invent one exact operator.
            operators.append(operator)
    return operators[0] if operators and len(set(operators))==1 else None


def validate_card(card:Any,pages:Sequence[Mapping[str,Any]],*,required_limits:Sequence[Mapping[str,Any]]|None=None,
                  _numeric_quote_runs:Sequence[Sequence[str]]|None=None) -> dict[str,Any]:
    fields={'material_type','event_or_meeting_object','speaker_and_source_attribution','date','facts','forecasts','inferences','numeric_values','related_entities','unknowns','source_usage_limits'}
    if not isinstance(card,dict) or set(card)!=fields or not isinstance(card['material_type'],str) or not isinstance(card['event_or_meeting_object'],str):fail('FULL_CARD_SCHEMA_INVALID')
    page_map={p['page_number']:p for p in pages}
    def evidence(rows:Any,required:bool=True) -> None:
        if not isinstance(rows,list) or required and not rows:fail('FULL_CITATION_REQUIRED')
        for item in rows:
            if not isinstance(item,dict) or set(item)!={'page_number','text_sha256','excerpt'}:fail('FULL_CITATION_INVALID')
            if type(item['page_number']) is not int or not isinstance(item['text_sha256'],str):fail('FULL_CITATION_INVALID')
            page=page_map.get(item['page_number']);quote=item['excerpt']
            if not page or item['text_sha256']!=page['text_sha256'] or not isinstance(quote,str) or not 1<=len(quote)<=300 or quote not in page['text']:fail('FULL_CITATION_NOT_EXACT_SOURCE')
    date=card['date']
    if not isinstance(date,dict) or set(date)!={'value','basis','evidence'} or not isinstance(date['basis'],str) or date['value'] is not None and not isinstance(date['value'],str):fail('FULL_DATE_INVALID')
    evidence(date['evidence'],date['value'] is not None)
    if card['inferences']!=[]:fail('FULL_LIGHT_MODEL_INFERENCE_FORBIDDEN')
    future=re.compile(r'预计|预测|有望|后续.{0,18}(?:增长|驱动|业绩)|将于|计划于|\d{4}E')
    for field in ('facts','forecasts'):
        rows=card[field]
        if not isinstance(rows,list):fail('FULL_CLAIM_LIMIT_INVALID')
        for item in rows:
            if not isinstance(item,dict) or set(item)!={'claim','attribution','period','unit','evidence'} or any(not isinstance(item[k],str) or not item[k].strip() for k in ['claim','attribution','period','unit']):fail('FULL_CLAIM_SCHEMA_INVALID')
            evidence(item['evidence'])
            if field=='facts' and future.search(item['claim']+' '+''.join(e['excerpt'] for e in item['evidence'])):fail('FULL_SOURCE_FORECAST_CLASSIFIED_AS_FACT')
    if not isinstance(card['numeric_values'],list) or len(card['numeric_values'])>30:fail('FULL_NUMERIC_SCHEMA_INVALID')
    for index,item in enumerate(card['numeric_values']):
        fields_n={'value_as_source','sign','unit','period','actual_or_forecast','comparison_operator','measure_kind','evidence'}
        if not isinstance(item,dict) or set(item)!=fields_n or any(not isinstance(item[k],str) or not item[k].strip() for k in fields_n-{'evidence'}):fail('FULL_NUMERIC_SCHEMA_INVALID')
        evidence(item['evidence']);quotes=' '.join(e['excerpt'] for e in item['evidence'])
        numeric_evidence = item['evidence'] if _numeric_quote_runs is None else [
            {'excerpt': quote} for quote in _numeric_quote_runs[index]]
        if not any(item['value_as_source'] in e['excerpt'] for e in numeric_evidence):fail('FULL_NUMERIC_VALUE_NOT_IN_QUOTE')
        if item['comparison_operator'] not in {'EQ','GE','GT','LE','LT','APPROX','RANGE','UNKNOWN'} or item['measure_kind'] not in {'annual_capacity','capacity','actual_output','revenue','price_return','date','other','UNKNOWN'}:fail('FULL_NUMERIC_SEMANTICS_INVALID')
        expected=_source_comparator(item['value_as_source'],numeric_evidence)
        if expected is not None and item['comparison_operator']!=expected:fail('FULL_NUMERIC_BOUND_LOST')
        if '产能' in quotes and '产量' not in quotes:
            if item['measure_kind']!=('annual_capacity' if '年产' in quotes else 'capacity') or item['actual_or_forecast'] not in {'REPORTED_CAPACITY_NOT_OUTPUT','FORECAST_CAPACITY_NOT_OUTPUT'}:fail('FULL_CAPACITY_MISCLASSIFIED_AS_OUTPUT')
        if '产量' in quotes and '产能' not in quotes and item['measure_kind']!='actual_output':fail('FULL_OUTPUT_MEASURE_MISMATCH')
    roles=card['speaker_and_source_attribution']
    if not isinstance(roles,list):fail('FULL_ATTRIBUTION_ROLE_INVALID')
    for item in roles:
        if not isinstance(item,dict) or set(item)!={'entity','role','evidence'} or not isinstance(item['entity'],str) or not item['entity'] or not isinstance(item['role'],str) or item['role'] not in {'publisher','respondent','visitor','speaker','source_author','UNKNOWN'}:fail('FULL_ATTRIBUTION_ROLE_INVALID')
        evidence(item['evidence'],not (item['entity']=='UNKNOWN' and item['role']=='UNKNOWN'))
        if item['entity']!='UNKNOWN' and not any(item['entity'] in e['excerpt'] for e in item['evidence']):fail('FULL_ATTRIBUTION_ENTITY_UNSUPPORTED')
        if item['role'] in {'speaker','source_author'} and not any(re.search(r'发言|主讲|作者|分析师|研究员|撰写',e['excerpt']) for e in item['evidence']):fail('FULL_SPEAKER_AUTHOR_NOT_IDENTIFIED')
    for field in ['related_entities','unknowns']:
        if not isinstance(card[field],list) or any(not isinstance(x,str) or not x.strip() for x in card[field]):fail('FULL_CARD_LIST_INVALID')
    if any(x['role'] in {'respondent','visitor'} for x in roles) and not any(x['role'] in {'speaker','source_author'} for x in roles) and not any(re.search(r'发言|作者',x) for x in card['unknowns']):fail('FULL_UNNAMED_SPEAKER_LIMIT_REQUIRED')
    limits=card['source_usage_limits']
    if not isinstance(limits,list):fail('FULL_SOURCE_USE_LIMIT_INVALID')
    for item in limits:
        if not isinstance(item,dict) or set(item)!={'limitation','evidence'} or not isinstance(item['limitation'],str) or not item['limitation'].strip():fail('FULL_SOURCE_USE_LIMIT_INVALID')
        evidence(item['evidence'])
    for required in source_limit_quotes(pages) if required_limits is None else required_limits:
        if not any(any(e['page_number']==required['page_number'] and _compact(required['excerpt']) in _compact(e['excerpt']) for e in item['evidence']) for item in limits):fail('FULL_SOURCE_USE_LIMIT_OMITTED')
    if not card['facts'] and not card['forecasts']:fail('FULL_CARD_NO_RESEARCH_CONTENT')
    return card



class CardValidationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _numeric_tokens(text):
    """Maximal source tokens; glyph equivalence never changes their value."""
    normalized = unicodedata.normalize('NFKC', text).replace('−', '-')
    return [''.join(token.split()) for token in re.findall(
        r'[+-]?\s*(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][+-]?\d+)?%?', normalized)]


def _numeric_value_matches(item, quotes):
    values, source = _numeric_tokens(item['value_as_source']), _numeric_tokens(quotes)
    if not values:
        raise CardValidationError('PDF_NUMERIC_VALUE_NOT_IN_EVIDENCE')

    def parts(token):
        sign = token[0] if token[0] in '+-' else ''
        body = token[len(sign):]
        return sign, body.removesuffix('%'), body.endswith('%')

    def magnitude_matches(value, actual):
        _, number, percent = parts(value)
        _, source_number, source_percent = parts(actual)
        return (number == source_number and (percent == source_percent
            or not percent and source_percent and item['unit'] in {'%', '％'}))

    candidates = [source[i:i + len(values)] for i in range(len(source) - len(values) + 1)
        if all(magnitude_matches(value, actual) for value, actual in zip(values, source[i:i + len(values)]))]
    if not candidates:
        raise CardValidationError('PDF_NUMERIC_VALUE_NOT_IN_EVIDENCE')
    # A range retains its exact source representation and comparator in the
    # legacy gate above; its '-' separator is not a single-value sign field.
    if len(values) != 1:
        if not any(values == candidate for candidate in candidates):
            raise CardValidationError('PDF_NUMERIC_SIGN_LOST')
        return
    signs = {parts(candidate[0])[0] for candidate in candidates}
    declared = item['sign']
    value_sign = parts(values[0])[0]
    if '-' in signs and signs - {'-'}:
        raise CardValidationError('PDF_NUMERIC_SIGN_AMBIGUOUS')
    if (value_sign == '-' and declared not in {'-', 'NEGATIVE'}
            or value_sign == '+' and declared not in {'+', 'POSITIVE'}):
        raise CardValidationError('PDF_NUMERIC_SIGN_LOST')
    if (signs == {'-'} and declared not in {'-', 'NEGATIVE'}
            or '+' in signs and declared not in {'+', 'POSITIVE'}
            or declared in {'-', 'NEGATIVE'} and signs != {'-'}
            or declared in {'+', 'POSITIVE'} and '-' in signs
            or declared == 'ZERO' and re.search(r'[1-9]', parts(values[0])[1])):
        raise CardValidationError('PDF_NUMERIC_SIGN_LOST')


def _contiguous_numeric_quotes(evidence):
    """Numeric-only view of already resolved, same-page adjacent source spans.

    Excerpts remain untouched. Only a decimal point/comma followed by a layout
    newline at a cited span boundary may lose whitespace. Other boundaries,
    including integer table rows, keep their original whitespace.
    """
    if len({item['evidence_id'] for item in evidence}) != len(evidence):
        return [item['excerpt'] for item in evidence]
    runs = []
    previous = None
    seen = set()
    for item in evidence:
        duplicate = item['evidence_id'] in seen
        adjacent = (previous is not None and not duplicate
            and previous['evidence_id'] != item['evidence_id']
            and previous['page_number'] == item['page_number']
            and previous['text_sha256'] == item['text_sha256']
            and previous['end'] == item['start'])
        if adjacent:
            left, right = runs[-1], item['excerpt']
            boundary = re.search(r'(?<=\d[.,])[^\S\r\n]*\r?\n[^\S\r\n]*$', left)
            if boundary and re.match(r'[^\S\r\n]*\d', right):
                left = left[:boundary.start()]
                right = right.lstrip(' \t')
            runs[-1] = left + right
        else:
            runs.append(item['excerpt'])
        seen.add(item['evidence_id'])
        previous = None if duplicate else item
    return runs


def validate_protocol_card(raw_text, spans, pages):
    """Resolve only program evidence IDs, then validate without semantic repair."""
    from infrastructure import pdf_research_protocol as protocol
    if protocol.PROTOCOL_VERSION == 'pdf-claims-source-v2':
        from infrastructure import pdf_research_claims as claims
        return claims.validate(raw_text, spans, pages)
    from infrastructure.pdf_research import _schema_error
    try:
        card = json.loads(raw_text)
    except (ValueError, TypeError):
        raise CardValidationError('PDF_CARD_JSON_INVALID') from None
    error = _schema_error(card, protocol.SCHEMA)
    if error:
        raise CardValidationError('PDF_CARD_SCHEMA_INVALID:' + error)
    page_map = {p.page_number: p for p in pages}
    span_map = {}
    for span in spans:
        page = page_map.get(span.page_number)
        if (not page or sha(page.text.encode()) != span.page_sha256
                or page.text[span.start:span.end] != span.text
                or sha(span.text.encode()) != span.text_sha256):
            raise CardValidationError('PDF_EVIDENCE_INPUT_SHA_MISMATCH')
        if span.evidence_id in span_map:
            raise CardValidationError('PDF_DUPLICATE_EVIDENCE_ID')
        span_map[span.evidence_id] = span
    bound = copy.deepcopy(card)

    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {'evidence_id'}:
                span = span_map.get(value['evidence_id'])
                if span is None:
                    raise CardValidationError('PDF_EVIDENCE_FOREIGN_OR_UNKNOWN')
                value.update(page_number=span.page_number, start=span.start, end=span.end,
                    text_sha256=span.page_sha256, excerpt_sha256=span.text_sha256, excerpt=span.text)
                return
            for item in value.values():
                resolve(item)
        elif isinstance(value, list):
            for item in value:
                resolve(item)
    resolve(bound)

    def legacy(value):
        if isinstance(value, dict):
            if 'evidence_id' in value:
                return {key: value[key] for key in ('page_number', 'text_sha256', 'excerpt')}
            return {key: legacy(item) for key, item in value.items()}
        if isinstance(value, list):
            return [legacy(x) for x in value]
        return value
    projection = legacy(bound)
    projection.pop('risks')
    for item in projection['numeric_values']:
        item.pop('currency')
    page_rows = [{'page_number': p.page_number, 'text_sha256': sha(p.text.encode()), 'text': p.text} for p in pages]
    audit = []
    normalize_percent_value_glyph(projection, page_rows, audit, raw_inner_sha256=sha(raw_text.encode()))
    # Only this already accepted glyph-equivalence transformation is reused.
    # No forecasts, claims, dates or unsupported evidence are repaired.
    for original, normalized in zip(bound['numeric_values'], projection['numeric_values'], strict=True):
        original['value_as_source'] = normalized['value_as_source']
    required = source_limit_quotes([{'page_number': s.page_number, 'text_sha256': s.page_sha256, 'text': s.text} for s in spans])
    try:
        validate_card(projection, page_rows, required_limits=required,
            _numeric_quote_runs=[_contiguous_numeric_quotes(item['evidence']) for item in bound['numeric_values']])
    except pdf_text_source.BatchError as exc:
        raise CardValidationError(exc.code) from None
    future = re.compile(r'未来|预计|预测|有望|后续|将于|计划于|目标|情景|假设|展望|拟|\d{4}E|\b(?:will|expect|forecast|scenario|target)\b', re.I)
    for fact in bound['facts']:
        if future.search(fact['claim'] + ' ' + ' '.join(e['excerpt'] for e in fact['evidence'])):
            raise CardValidationError('PDF_FORECAST_CLASSIFIED_AS_FACT')
    for field in ('facts', 'forecasts'):
        for item in bound[field]:
            quotes = ' '.join(e['excerpt'] for e in item['evidence'])
            source_numbers = set(_numeric_tokens(' '.join(_contiguous_numeric_quotes(item['evidence']))))
            for number in _numeric_tokens(item['claim']):
                if number not in source_numbers:
                    raise CardValidationError('PDF_CLAIM_NUMBER_NOT_IN_EVIDENCE')
            for name in ('period', 'unit'):
                if item[name] != 'UNKNOWN' and item[name] not in quotes:
                    raise CardValidationError('PDF_CLAIM_' + name.upper() + '_UNLINKED')
    for item in bound['numeric_values']:
        quotes = ' '.join(e['excerpt'] for e in item['evidence'])
        for name in ('unit', 'currency', 'period'):
            value = item[name]
            annual_unit = name == 'unit' and value.endswith('/年') and '年产' in quotes and value[:-2] in quotes
            if value != 'UNKNOWN' and value not in quotes and not annual_unit:
                raise CardValidationError('PDF_NUMERIC_' + name.upper() + '_UNLINKED')
        if future.search(quotes) and item['actual_or_forecast'] in {'ACTUAL', 'REPORTED_CAPACITY_NOT_OUTPUT'}:
            raise CardValidationError('PDF_FORECAST_NUMBER_CLASSIFIED_AS_ACTUAL')
        _numeric_value_matches(item, ' '.join(_contiguous_numeric_quotes(item['evidence'])))
    date = bound['date']
    if date['value'] is not None and not any(date['value'] in e['excerpt'] for e in date['evidence']):
        raise CardValidationError('PDF_DATE_NOT_IN_EVIDENCE')
    used_limits = {e['evidence_id'] for row in bound['source_usage_limits'] for e in row['evidence']}
    if any(re.search(r'不构成|仅供.{0,10}(?:交流|参考)|以.{0,30}为准', s.text) and s.evidence_id not in used_limits for s in spans):
        raise CardValidationError('PDF_SOURCE_USE_LIMIT_OMITTED')
    return {'card': bound, 'normalization_audit': audit, 'deterministic_status': 'PASS',
        'semantic_review': 'PENDING_INDEPENDENT_REVIEW', 'research_only': True,
        'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


def replay_legacy_failure(raw_text, pages, *, original_code):
    """Version-appropriate deterministic replay never promotes a historical FAIL."""
    raw_sha = sha(raw_text.encode())
    try:
        projected, audit = canonicalize_citations(raw_text, pages)
        validate_card(projected, pages)
        current, code = 'LEGACY_DETERMINISTIC_PASS_ONLY', None
    except (ValueError, pdf_text_source.BatchError) as exc:
        current, code, audit = 'LEGACY_DETERMINISTIC_FAIL', getattr(exc, 'code', 'LEGACY_JSON_INVALID'), []
    return {'raw_sha256': raw_sha, 'original_code': original_code, 'original_status': 'FAIL_PRESERVED',
        'legacy_replay_status': current, 'legacy_replay_code': code,
        'normalization_count': len(audit), 'semantic_acceptance': 'NOT_GRANTED', 'model_posts': 0}
