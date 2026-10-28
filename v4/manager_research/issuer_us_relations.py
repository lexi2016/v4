"""US/HK joins from existing native-issuer material propositions, never a stock map.

No I/O, issuer discovery, price signal, ticker beneficiary list, or acquisition
clock synthesis. The US event is the first source; an independently owned,
subject-bound HK business statement is the second. General theme-news articles
are not required as a third source. Existing theme mappings remain supported.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import canonical_symbol, digest, timestamp
from .workspace_semantics import prose_sources
from .evidence_identity import acquisition_is_within_window

# Business vocabulary only: never codes, company aliases or beneficiary lists.
BUSINESS_TAXONOMY = (
    ('BIOMEDICINE', r'生物医药|生物醫藥|生物制药|生物製藥|biopharmaceutical'),
    ('OIL', r'石油|原油|炼油|煉油|炼化|煉化|petroleum|crude\s+oil'),
    ('SOLAR', r'光伏(?:组件|电池|玻璃|设备|产品|业务)?|solar\s+(?:module|cell|glass)'),
    ('NEW_ENERGY', r'风电|风机|新能源(?:设备|业务|发电)|可再生能源'),
    ('SEMICONDUCTOR', r'半导体|晶圆|芯片制造|芯片设计|集成电路'),
    ('STORAGE', r'存储芯片|存储器|固态硬盘|nand\b|dram\b'),
    ('CPO', r'光互连|光模块|硅光|\bcpo\b|co-packaged\s+optics'),
    ('DATA_CENTER', r'数据中心|\baidc\b|data\s+cent(?:er|re)'),
    ('BANKING', r'商业银行|银行(?:贷款|存款|业务)|净息差'),
    ('GRID', r'电网|输配电|变压器'), ('COPPER', r'铜矿|铜冶炼|铜材|有色金属'),
    ('DEFENSE', r'军工(?:设备|产品|业务)|国防装备'),
    ('GOLD', r'黄金(?:矿|产量|产销|开采)|金矿'),
    ('CONSUMER', r'消费品|消费(?:产品|业务)|零售|家电'),
    ('SATELLITE', r'卫星(?:设备|制造|通信|产品|业务)|低轨卫星'),
    ('LITHIUM_BATTERY', r'锂电池|锂电(?:材料|业务)|动力电池'),
    ('ROBOTICS', r'工业机器人|人形机器人|协作机器人|具身智能'),
    ('AUTONOMOUS_DRIVING', r'自动驾驶|无人驾驶'),
    ('AI_COMPUTE', r'算力|\bgpu\b|人工智能服务器'),
    ('CLOUD', r'云计算|云服务'),
)
_COMPILED = [(key, re.compile(pattern, re.I)) for key,pattern in BUSINESS_TAXONOMY]
_BUSINESS = re.compile(r'业务|产品|设备|订单|收入|营收|生产|产量|产能|供货|供应|交付|研发|制造|销售|贷款|利润|签署|合作|许可', re.I)
_RELATION = re.compile(r'供货|供应|合作|签署|客户|采购|订单|合同|许可|授权|持有|投资|参股|收购|partner|supply|customer|contract|licens',re.I)
_US_CODE = re.compile(r'(?<![A-Za-z0-9])US\.([A-Z][A-Z0-9.-]{0,9})(?![A-Za-z0-9.-])|(?<![A-Za-z0-9])(?:NASDAQ|NYSE)\s*:\s*([A-Z][A-Z0-9.-]{0,9})(?![A-Za-z0-9.-])|\$([A-Z][A-Z0-9.-]{0,9})(?![A-Za-z0-9.-])')
_TICKER = re.compile(r'^[A-Z][A-Z0-9.-]{0,9}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


def _symbols(value: Mapping[str, Any]) -> set[str]:
    if not isinstance(value,Mapping):return set()
    out=set()
    for key in ('related_us_symbols','us_symbols','us_symbol'):
        values=value.get(key,[])
        if isinstance(values,str):values=[values]
        if isinstance(values,list):out.update(v.upper().strip() for v in values if isinstance(v,str) and _TICKER.fullmatch(v.upper().strip()))
    if isinstance(value.get('identity_pair_basis'),Mapping):out.update(_symbols(value['identity_pair_basis']))
    return out


def _anchored(card: Mapping[str,Any], prop: Mapping[str,Any]) -> bool:
    if (prop.get('symbol')!=card.get('symbol') or prop.get('action_subject')!=card.get('symbol')
            or prop.get('polarity')!='AFFIRMED' or prop.get('effect_scope')!='ISSUER_CLAIM_NOT_PRICE_CONFIRMATION'):
        return False
    field=prop.get('source_field');source=dict(prose_sources(card)).get(field)
    a,b=prop.get('start'),prop.get('end')
    return (isinstance(source,str) and type(a) is int and type(b) is int and 0<=a<b<=len(source)
            and source[a:b]==prop.get('quote') and isinstance(prop.get('action_quote'),str)
            and bool(prop['action_quote']) and prop['action_quote'] in source[a:b])


def _direction(quote: str) -> str:
    if re.search(r'下降|下调|亏损|承压|减少|终止|取消|减值',quote):return 'NEGATIVE_OR_RISK'
    if re.search(r'增长|增加|上调|获批|新增|中标',quote):return 'POSITIVE_SOURCE_STATEMENT'
    return 'EXPOSURE_ONLY_NOT_PRICE_DIRECTION'


def extract_issuer_business_relations(card: Mapping[str,Any]) -> list[dict]:
    """Extract only statements anchored by the existing native issuer parser.

    Structured upstream symbols are carried over only when the same symbol
    occurs in the same validated relation clause. Explicit US.* / exchange
    notation in that clause can also establish a symbol without a static map.
    This function does not admit clocks: the consumer validates all clocks.
    """
    source=card.get('original_source_row') or card.get('source_row') or {}
    mentioned=_symbols(source) if isinstance(source,Mapping) else set()
    result=[]
    cautions=[{'quote':p['quote'],'source_field':p['source_field'],'start':p['start'],'end':p['end'],
               'scope':'ISSUER_GENERAL_NOT_SPECIFIC_US_LINK'} for p in card.get('propositions') or []
              if isinstance(p,Mapping) and _anchored(card,p) and _direction(str(p['quote']))=='NEGATIVE_OR_RISK']
    for p in card.get('propositions') or []:
        if not isinstance(p,Mapping) or not _anchored(card,p):continue
        quote=str(p['quote']);action=str(p['action_quote'])
        themes=[theme for theme,pattern in _COMPILED if pattern.search(action) and _BUSINESS.search(action)]
        tickers=set()
        if _RELATION.search(action):
            tickers.update(next(g for g in m.groups() if g) for m in _US_CODE.finditer(action))
            tickers.update(t for t in mentioned if re.search(r'(?<![A-Za-z0-9])'+re.escape(t)+r'(?![A-Za-z0-9])',action))
        if not themes and not tickers:continue
        result.append({'proposition_id':p.get('proposition_id'),'symbol':card.get('symbol'),
            'issuer_quote':quote,'source_field':p['source_field'],'start':p['start'],'end':p['end'],
            'manager_themes':themes,'related_us_symbols':sorted(tickers),
            'direction':_direction(quote),'issuer_cautions':deepcopy(cautions),'effect_scope':p.get('effect_scope'),
            'claim_status':p.get('claim_status'),
            'basis':'NATIVE_ISSUER_SUBJECT_ACTION_SOURCE_SPAN'})
    return result


def _card_errors(card: Mapping[str,Any], cutoff: datetime | None) -> list[str]:
    """Report acquisition gaps separately; an old publication cannot hide them."""
    errors=[]
    if card.get('semantic_status')!='ACCEPTED':errors.append('ISSUER_SEMANTIC_NOT_ACCEPTED')
    symbol=card.get('symbol')
    if not isinstance(symbol,str) or canonical_symbol(symbol,card.get('market','HK'))!=symbol:
        errors.append('HK_SECURITY_IDENTITY_INVALID')
    identity=card.get('identity_source')
    if (not isinstance(identity,Mapping) or identity.get('status')!='OWNER_VERIFIED'
            or not _SHA.fullmatch(str(identity.get('artifact_sha256','')))):
        errors.append('NATIVE_ISSUER_IDENTITY_UNVERIFIED')
    refs=card.get('source_refs')
    if not isinstance(refs,list) or not refs or any(not isinstance(r,Mapping) or r.get('status')!='VERIFIED'
            or not _SHA.fullmatch(str(r.get('payload_sha256',''))) for r in refs):
        errors.append('ISSUER_SOURCE_LINEAGE_UNVERIFIED')
    from .announcement_materials import is_mirror, mirror_binding_valid
    if is_mirror(card) and not mirror_binding_valid(card):errors.append('MIRROR_ISSUER_SOURCE_BINDING_INVALID')
    pub=timestamp(card.get('mirror_observed_at') if is_mirror(card) else card.get('published_at'))
    available=timestamp(card.get('available_at'));retrieved=timestamp(card.get('retrieved_at'))
    if pub is None:errors.append('ISSUER_SOURCE_PUBLICATION_OR_MIRROR_TIME_MISSING')
    if available is None or retrieved is None:
        errors.append('ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID')
    elif cutoff is None or (pub is not None and pub>retrieved) or retrieved>available or available>cutoff:
        errors.append('ISSUER_ACQUISITION_TIME_OUTSIDE_WINDOW_OR_ORDER_INVALID')
    # These are additional original clocks, never fallback acquisitions.
    for key in ('first_seen_at','collected_at','archive_recorded_at'):
        if card.get(key) not in (None,''):
            stamp=timestamp(card[key])
            if stamp is None or cutoff is None or stamp>cutoff:
                errors.append('ISSUER_ADDITIONAL_CLOCK_INVALID_OR_AFTER_CUTOFF:'+key)
    return errors


def _standing_contract(card: Mapping[str,Any], claim: Mapping[str,Any], cutoff: datetime | None) -> tuple[dict | None,str | None]:
    """A source-owner supplied span contract; no side store or clock backfill.

    The contract must already be inside the original reader-verified payload.
    A statement-only metadata cache cannot supply or extend its validity.
    Validity is bounded to 366 days and never claims that an old relation is a
    new catalyst. The claim/body/source hash bindings are all rechecked here.
    """
    row=card.get('original_source_row')
    contract=row.get('business_relation_validity') if isinstance(row,Mapping) else None
    if not isinstance(contract,Mapping):return None,'ISSUER_PUBLICATION_OUTSIDE_WINDOW'
    a,b=claim.get('start'),claim.get('end');field=claim.get('source_field')
    body=dict(prose_sources(card)).get(field)
    def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
    refs=card.get('source_refs') or []
    if (contract.get('schema_version')!='v4.manager_research.business_relation_validity.v1'
            or contract.get('status')!='ACTIVE' or contract.get('issuer_symbol')!=card.get('symbol')
            or contract.get('validity_basis')!='ORIGINAL_SOURCE_OWNER_EXPLICIT_REVIEW_PERIOD_NOT_NEW_CAPTURE'
            or not isinstance(body,str) or contract.get('body_sha256')!=sha(body)
            or (contract.get('source_field'),contract.get('start'),contract.get('end'))!=(field,a,b)
            or contract.get('quote_sha256')!=sha(claim.get('issuer_quote',''))
            or contract.get('source_payload_sha256') not in {r.get('payload_sha256') for r in refs if isinstance(r,Mapping)}):
        return None,'STANDING_RELATION_SOURCE_SPAN_CONTRACT_INVALID'
    begin=timestamp(contract.get('valid_from'));end=timestamp(contract.get('valid_until'))
    confirmed=timestamp(contract.get('confirmed_at'))
    acquired=timestamp(card.get('available_at'));retrieved=timestamp(card.get('retrieved_at'))
    from .announcement_materials import is_mirror
    published=timestamp(card.get('mirror_observed_at') if is_mirror(card) else card.get('published_at'))
    if (not all((begin,end,confirmed,acquired,retrieved,published,cutoff))
            or not begin<=confirmed<=acquired<=cutoff<end or retrieved>acquired
            or not published<=confirmed or end-begin>timedelta(days=366)):
        return None,'STANDING_RELATION_VALIDITY_OR_CAPTURE_INVALID'
    if claim.get('claim_status')!='SOURCE_STATEMENT':return None,'STANDING_RELATION_NOT_SOURCE_STATEMENT'
    return deepcopy(dict(contract)),None


def _claim_time(card: Mapping[str,Any],claim: Mapping[str,Any],start: datetime | None,cutoff: datetime | None):
    from .announcement_materials import current_company_claim
    if current_company_claim(card,start,cutoff):return 'CURRENT_WINDOW_RELATION_EVIDENCE',None,None
    contract,error=_standing_contract(card,claim,cutoff)
    if error:return None,None,error
    return 'STANDING_RELATION_NOT_NEW_CATALYST',contract,None


def _card_error(card: Mapping[str,Any],start: datetime | None,cutoff: datetime | None) -> str | None:
    """Compatibility diagnostic only; per-claim standing admission is below."""
    errors=_card_errors(card,cutoff)
    if errors:return errors[0]
    from .announcement_materials import current_company_claim
    return None if current_company_claim(card,start,cutoff) else 'ISSUER_PUBLICATION_OUTSIDE_WINDOW'


def material_us_relations(cards: Sequence[Mapping[str,Any]] | None, start: datetime | None, cutoff: datetime | None):
    industries: dict[str,list[dict]]={};individuals: dict[str,list[dict]]={};audit=[];seen=set()
    for card in cards or []:
        if not isinstance(card,Mapping):continue
        claims=extract_issuer_business_relations(card)  # do not trust mutable cached extraction
        errors=_card_errors(card,cutoff)
        if not claims:
            audit.append({'symbol':card.get('symbol'),'card_id':card.get('card_id'),
                'reason':(errors or ['NO_SUBJECT_BOUND_BUSINESS_OR_US_RELATION'])[0],
                'rejection_reasons':[*errors,'NO_SUBJECT_BOUND_BUSINESS_OR_US_RELATION'],'manager_themes':[],
                'related_us_symbols':sorted(_symbols(card.get('original_source_row') or {})),
                'source_refs':deepcopy(card.get('source_refs') or [])})
        for claim in claims:
            role,contract,time_error=_claim_time(card,claim,start,cutoff)
            reasons=[*errors,*([time_error] if time_error else [])]
            if claim.get('claim_status') not in {'SOURCE_STATEMENT','REPORTED_CLAIM'}:
                reasons.append('ISSUER_RELATION_NOT_AFFIRMED_FACT_OR_ATTRIBUTED_REPORT')
            a={'symbol':card['symbol'],'card_id':card.get('card_id'),**claim,
               'reason':reasons[0] if reasons else 'ACCEPTED','rejection_reasons':reasons,
               'relation_temporal_role':role,'source_refs':deepcopy(card.get('source_refs') or [])}
            audit.append(a)
            if reasons:continue
            key=digest([card['symbol'],claim,card['source_refs']])
            if key in seen:continue
            seen.add(key)
            base={**claim,'symbol':card['symbol'],'name':card.get('name'),
                'semantic_status':'ACCEPTED',  # only after source/subject/PIT admission above
                'relation_temporal_role':role,'standing_validity':contract,
                'is_new_catalyst':False,
                'issuer_time_basis':card.get('time_basis','ORIGINAL_SOURCE_PUBLICATION'),
                'issuer_mirror_observed_at':card.get('mirror_observed_at'),
                'issuer_published_at':card.get('published_at'),'issuer_available_at':card.get('available_at'),
                'issuer_retrieved_at':card.get('retrieved_at'),'published_at':card.get('published_at'),
                **{k:card.get(k) for k in ('available_at','retrieved_at','first_seen_at','collected_at','archive_recorded_at')},
                'source_refs':deepcopy(card['source_refs']),'identity_source':deepcopy(card['identity_source']),
                'connect_eligibility':card.get('connect_eligibility','TARGET_DATE_NOT_CHECKED'),
                'relationship_type':'INDUSTRY_INFERENCE','relation_origin':'NATIVE_MATERIAL_PROPOSITION',
                'research_only':True,'not_a_beneficiary_or_buy_assertion':True,
                'relation_assertion_scope':('ATTRIBUTED_REPORT_NOT_INDEPENDENTLY_CONFIRMED'
                    if claim.get('claim_status')=='REPORTED_CLAIM' else 'SOURCE_STATEMENT_NOT_PRICE_PREDICTION')}
            for theme in claim['manager_themes']:
                industries.setdefault(card['symbol'],[]).append({**base,'manager_theme':theme})
            if claim['related_us_symbols']:
                individuals.setdefault(card['symbol'],[]).append({**base,'relationship_type':'EXPLICIT_US_ISSUER_RELATION'})
    return industries,individuals,audit
