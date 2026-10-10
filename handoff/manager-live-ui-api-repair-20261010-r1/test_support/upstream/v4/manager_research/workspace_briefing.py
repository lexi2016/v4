"""Explain research mechanisms and attention order; never a market/Stage score.

Only already-read original prose and issuer-local propositions are consumed.
No price fetch, external admission, sector universe or forecast is fabricated.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import digest, event_groups, timestamp
from .workspace_semantics import prose_sources, mechanism, evidence_id

LABELS = {
    'PHARMA_CROSS_BORDER_POLICY':'创新药跨境许可：拟议规则变化（非最终规则）',
    'AI_DRUG_RND':'AI药物研发产业事件（与跨境许可政策分列）',
    'REGULATORY_OPINION':'公司监管节点：CHMP意见（非最终批准）',
    'PHARMA_INDUSTRY_PLAN':'医药工业规划与研发／制造产业观察',
    'DIGITAL_ASSET_EXPOSURE':'数字资产关联：须核当前敞口与同窗口币价',
    'DRUG_DEVELOPMENT':'公司临床研发节点',
    'PHARMA_COMPANY_LICENSING':'公司许可交易节点',
    'ROBOTICS':'机器人产品、订单及交付研究',
    'AI_COMPUTE':'算力相关产品、订单及交付研究',
    'AI_APPLICATION':'AI应用相关产品及合作研究',
}

def _recent(e: Mapping[str,Any], context: Mapping[str,Any]) -> bool:
    # Use the same exact material cutoff and focus window as the plan owner.
    # Day-only comparisons incorrectly promoted pre-16:00 Friday background
    # and material acquired after the frozen cutoff.
    from .announcement_materials import current_company_claim
    return current_company_claim(e,timestamp(context.get('focus_window_start')),timestamp(context.get('research_cutoff')))



def _theme_fragments(material: Mapping[str,Any], context: Mapping[str,Any]) -> list[dict]:
    """Do not use title or broad upstream theme tags as thematic propositions."""
    from .workspace_plan import temporal_role
    from .announcement_materials import is_mirror
    if is_mirror(material):
        return []  # Company disclosure is not a sector-wide publication or third-party catalyst.
    if temporal_role(material, context) == 'AFTER_CUTOFF_EXCLUDED':
        return []  # Not even a historical reference was available at this cutoff.
    out=[]
    for field,body in prose_sources(material):
        # Enumerated topic headings are clause boundaries even when the upstream
        # extractor flattened paragraph newlines. Offsets remain in raw body.
        boundaries=[0,*[m.start() for m in re.finditer(r'(?<![\u4e00-\u9fff])(?:[一二三四五六七八九十]|[1-9])[、．]\s*',body)],len(body)]
        units=[]
        for left,right in zip(sorted(set(boundaries)),sorted(set(boundaries))[1:]):
            for m in re.finditer(r'[^\n。！？；;]+',body[left:right]):units.append((left,m))
        for offset,match in units:
            quote=match[0].strip();start=offset+match.start()+len(match[0])-len(match[0].lstrip())
            if len(quote)<12 or len(quote)>1600:continue
            theme=mechanism(quote)
            if not theme or theme in {'REGULATORY_OPINION','DRUG_DEVELOPMENT','PHARMA_COMPANY_LICENSING'}:continue
            # Require an actual industrial action/claim, not a list of tags.
            if not re.search(r'合作|融资|完成|启动|发布|推出|交付|订单|研发|临床|授权|许可|规划|持有|交易|上涨|下跌|意见|量产|增长|下调|上调|adopted|licens|partner|launch',quote,re.I):continue
            eid=evidence_id(material)
            out.append(dict(theme=theme,evidence_id=eid,proposition_id=digest([eid,field,start,quote]),
                quote=quote,source_field=field,start=start,end=start+len(quote),
                published_at=material.get('published_at'),retrieved_at=material.get('retrieved_at'),
                available_at=material.get('available_at'),source_refs=deepcopy(material.get('source_refs',[])),
                source_url=material.get('source_url'),title=material.get('title'),
                event_id=material.get('original_article_id') or material.get('event_id'),
                temporal_role='NEW_PLAN_PUBLICATION' if _recent(material,context) else 'BACKGROUND_OR_PUBLICATION_UNKNOWN',
                claim_type=material.get('claim_type','RESEARCH_OPINION'),
                provenance_scope='ORIGINAL_READER_PROJECTION_NOT_RAW_STORE_REVALIDATION'))
    return out


def _market_gap() -> dict:
    return dict(status='UNVERIFIED',full_market_rank=None,breadth=None,turnover_hkd=None,
        relative_index_return_pct=None,universe_coverage=None,as_of=None,
        reason='缺同窗口、可核验主题成员范围／全港股通行情及指数对照；盘前收盘与24符号时点样本均不能替代。')


def _exposure(theme: str, p: Mapping[str,Any]) -> bool:
    """Coarse candidate filter; generic AI still needs pairwise admission below."""
    text=p['quote']
    if theme in {'REGULATORY_OPINION','DRUG_DEVELOPMENT','PHARMA_COMPANY_LICENSING'}:
        return False  # a named company's event is not a sector-wide event
    if theme=='PHARMA_CROSS_BORDER_POLICY':
        return bool(re.search(r'授权|许可|BD|licens',text,re.I) and re.search(r'海外|对外|美国|跨境|全球|全球化|global|overseas',text,re.I))
    if theme=='AI_DRUG_RND':return p.get('theme')=='AI_DRUG_RND'
    if theme=='PHARMA_INDUSTRY_PLAN':return bool(_pharma_scope(p))
    if theme=='DIGITAL_ASSET_EXPOSURE':return False  # current exposure AND matched price owner absent
    return p.get('theme')==theme


# Bounded application scopes, not issuer/sector membership. Generic AI, model,
# partnership and company names are deliberately insufficient. Unknown or mixed
# scopes remain research-only until the original evidence is more specific.
_APPLICATION_SCOPE_PATTERNS = {
    'AUTOMOTIVE_COCKPIT': r'座舱|车机|车载(?:助手|语音|交互|系统)|\bcockpit\b|in.vehicle assistant',
    'AUTONOMOUS_DRIVING': r'自动驾驶|辅助驾驶|智驾|autonomous driving|driver assistance',
    'DRUG_DISCOVERY': r'药物研发|药物发现|药研|制药|抗体发现|分子设计|体内验证|(?<![a-z])aidd(?![a-z])|drug discovery',
    'INSURANCE_OPERATIONS': r'保险理赔|智能理赔|核保|保单|保费|insurance claims|underwriting',
    'RETAIL_COMMERCE': r'电商|零售|商品推荐|网店|e.commerce|retail',
    'INDUSTRIAL_INSPECTION': r'工业质检|制造质检|生产线(?:检测|质检)|缺陷检测|industrial inspection',
}
_APPLICATION_SCOPE_RULE = '20260921.application-mapping.r3.1.1.v1'


def _application_anchors(p: Mapping[str,Any], *, issuer: bool) -> tuple[list[dict], bool]:
    """Bind literal anchors to this proposition, never its title/ambient context.

    Issuer anchors must lie in the R3.1 affirmed, subject-bound action span.
    This excludes industry-looking issuer names without re-parsing subjects.
    """
    quote,start,end=p.get('quote'),p.get('start'),p.get('end')
    if (not isinstance(quote,str) or type(start) is not int or type(end) is not int
            or start<0 or end-start!=len(quote)):
        return [],False
    if issuer:
        action,left,right=p.get('action_quote'),p.get('action_start'),p.get('action_end')
        if (p.get('polarity')!='AFFIRMED' or not p.get('symbol')
                or p.get('action_subject')!=p['symbol'] or not isinstance(action,str)
                or type(left) is not int or type(right) is not int
                or not start<=left<right<=end or quote[left-start:right-start]!=action):
            return [],False
        quote,start=action,left
    anchors=[]
    for domain,pattern in _APPLICATION_SCOPE_PATTERNS.items():
        for match in re.finditer(pattern,quote,re.I):
            anchors.append(dict(domain=domain,quote=match[0],start=start+match.start(),end=start+match.end(),
                evidence_id=p['evidence_id'],proposition_id=p['proposition_id'],source_field=p['source_field']))
    return anchors,True


def _application_admission(p: Mapping[str,Any], support: Mapping[str,Any]) -> dict:
    """A shared AI_APPLICATION enum is a candidate filter, not an admission."""
    issuer,issuer_bound=_application_anchors(p,issuer=True)
    theme,theme_bound=_application_anchors(support,issuer=False)
    issuer_domains=sorted({a['domain'] for a in issuer});theme_domains=sorted({a['domain'] for a in theme})
    shared=sorted(set(issuer_domains)&set(theme_domains))
    if not issuer_bound or not theme_bound:
        code='APPLICATION_PROPOSITION_BINDING_INVALID';status='CANNOT_CONFIRM'
    elif not issuer_domains:
        code='ISSUER_APPLICATION_ANCHOR_MISSING';status='CANNOT_CONFIRM'
    elif not theme_domains:
        code='THEME_APPLICATION_ANCHOR_MISSING';status='CANNOT_CONFIRM'
    elif len(issuer_domains)!=1 or len(theme_domains)!=1:
        code='APPLICATION_SCOPE_AMBIGUOUS';status='CANNOT_CONFIRM'
    elif not shared:
        code='APPLICATION_DOMAIN_MISMATCH';status='REJECTED'
    else:
        code='SHARED_CONCRETE_APPLICATION';status='PASS'
    return dict(rule_version=_APPLICATION_SCOPE_RULE,status=status,reason_code=code,
        issuer_domains=issuer_domains,theme_domains=theme_domains,shared_domains=shared,
        issuer_anchors=issuer,theme_anchors=theme,
        scope='PROPOSITION_LOCAL_APPLICATION_COMPATIBILITY_NOT_COMPANY_CONTRACT_OR_MARKET_CONFIRMATION')



def _pharma_scope(p: Mapping[str,Any]) -> str | None:
    # Reuse the exact AFFIRMED action-span boundary; issuer names never qualify.
    _, bound = _application_anchors(p, issuer=True)
    if not bound:
        return None
    text = p['action_quote']
    if re.search(r'AIDD|抗体发现|体内验证|分子设计|药物发现', text, re.I):
        return 'DRUG_RND_SERVICES'
    if re.search(r'临床|管线', text) and re.search(r'BD|药物|试验|临床', text, re.I):
        return 'CLINICAL_PIPELINE'
    if re.search(r'药品生产|制药装备|原料药|医药制造', text):
        return 'DRUG_MANUFACTURING'
    return None


def _pharma_admission(key: str, p: Mapping[str,Any], support: Mapping[str,Any]) -> dict:
    scope = _pharma_scope(p)
    text = p.get('action_quote', '')
    theme_text = support['quote']
    passed = False
    reason = 'ISSUER_CONCRETE_DRUG_BUSINESS_MISSING'
    mechanism_text = ''
    if key == 'PHARMA_INDUSTRY_PLAN':
        if scope == 'DRUG_RND_SERVICES' and re.search(r'AI4S|生命科学工具|CXO', theme_text, re.I):
            passed = True
            mechanism_text = '报告所述规划关注AI4S/生命科学工具；本股命题明确AIDD体内验证或抗体发现业务，故可研究研发工具需求。未证明新增订单或政策收益已兑现。'
        elif scope == 'DRUG_MANUFACTURING' and re.search(r'制药装备|医药制造', theme_text):
            passed = True
            mechanism_text = '规划与本股正文均涉及制药生产环节；仅研究设备/制造需求传导，尚非新增订单。'
        elif scope:
            reason = 'POLICY_CLAUSE_TO_SPECIFIC_BUSINESS_NOT_PROVEN'
    elif key == 'PHARMA_CROSS_BORDER_POLICY':
        if scope and re.search(r'授权|许可|licens', text, re.I) and re.search(r'美国|美方|U\.S\.', text, re.I):
            passed = True
            mechanism_text = '本股已绑定命题同时给出药研业务、许可行为及美国范围；拟议条款可能影响该许可适用性，仍须核最终规则和具体合同。'
        else:
            reason = 'US_LICENSE_ROLE_AND_TERRITORY_NOT_PROVEN'
    return dict(status='PASS' if passed else 'CANNOT_CONFIRM', reason_code='SHARED_DRUG_BUSINESS_MECHANISM' if passed else reason,
                rule_version='20260921.pharma-action-scope.ux1', issuer_scope=scope,
                mechanism=mechanism_text, scope='INDUSTRY_INFERENCE_NOT_NEW_COMPANY_EVENT')


def _company_mapping_gaps(key: str, stocks: list[dict], links: list[dict], context: Mapping[str,Any]) -> list[dict]:
    """Diagnostic candidates are not admitted relations or a hidden drug list."""
    if key not in {'PHARMA_CROSS_BORDER_POLICY','PHARMA_INDUSTRY_PLAN'}:
        return []
    from .workspace_plan import temporal_role
    mapped = {m['symbol'] for m in links}
    out = []
    for stock in stocks:
        if stock['symbol'] in mapped:
            continue
        props = [p for e in stock['evidence'] if temporal_role(e,context)!='AFTER_CUTOFF_EXCLUDED'
                 for p in e.get('propositions', [])]
        scoped = [p for p in props if _pharma_scope(p)]
        # Generic internationalization language warrants an explicit gap, not
        # membership. The match is in the affirmed action, never the company name.
        generic = [p for p in props if _application_anchors(p, issuer=True)[1]
                   and re.search(r'研发.*国际化|国际化.*研发', p.get('action_quote',''))]
        relevant = scoped or generic
        if not relevant:
            continue
        if key == 'PHARMA_CROSS_BORDER_POLICY':
            if any(_pharma_scope(p)=='CLINICAL_PIPELINE' for p in relevant):
                missing = '临床/BD陈述缺具体授权管线、美国交易对手/地域与许可类型；不能据BD标题断言适用美国拟议规则。'
            elif any(_pharma_scope(p)=='DRUG_RND_SERVICES' for p in relevant):
                missing = '抗体发现/AIDD体内验证业务不等于跨境许可；缺本股美国许可合同、对手及业务角色。'
            else:
                missing = '研发与国际化标题缺具体药物业务、许可行为、美国地域和适用条款，不能由公司名补足。'
        else:
            missing = ('原文临床/BD节点未指向规划中的具体支持条款，缺管线业务与条款的可核适用关系。' if scoped else
                       '研发与国际化仅是概括；缺具体药物业务/产品或制造环节与规划条款，旧使用自有资金公告不能替代。')
        out.append(dict(symbol=stock['symbol'],name=stock['name'],status='CANNOT_CONFIRM',
            diagnostic_only=True,not_a_stock_mapping=True,missing=missing,
            evidence_ids=sorted({p['evidence_id'] for p in relevant}),
            proposition_ids=sorted({p['proposition_id'] for p in relevant}),
            issuer_quotes=list(dict.fromkeys(p['quote'] for p in relevant)),
            owner='ResearchArchiveStore / HourlyResearchStore / Vibe original readers → read_existing_materials → workspace_discovery',
            required_fields=['issuer-bound business quote','policy clause and rule status','source_url','published_at','available_at','source_refs/SHA'],
            remedy='由原reader补出该公司原文业务/合同和政策原文及时间凭证；经原主体准入后再投影，不手填证券名单。'))
    return out


def _event_reading_key(pair: tuple[Mapping[str,Any], Mapping[str,Any]]) -> tuple:
    """Within one stock: substantive reported action before forecasts/headlines.
    Never used as a stock score, Stage rank or buy gate.
    """
    e,p = pair
    quote = str(p.get('action_quote') or p.get('quote') or '')
    substantive = bool(re.search(r'上调.*价格|mSAP.*订单|达成.*合作|签署.*协议|启动.*招标', quote, re.I))
    generic = p.get('event_type') in {'ISSUER_RESEARCH','VALUATION_OPINION'} or bool(re.search(r'细节保密', quote))
    when=timestamp(e.get('published_at'))
    return (0 if substantive else 2 if generic else 1, -(when.timestamp() if when else 0), p['proposition_id'])


def build_briefing(materials: Sequence[Mapping[str,Any]],stocks: list[dict],context: Mapping[str,Any]) -> dict:
    from .workspace_plan import temporal_role
    by_theme=defaultdict(list)
    for material in materials:
        for frag in _theme_fragments(material,context):by_theme[frag['theme']].append(frag)
    # Valid official issuer propositions may not be in archive materials.
    for stock in stocks:
        for evidence in stock['evidence']:
            if temporal_role(evidence,context)=='AFTER_CUTOFF_EXCLUDED':continue
            for p in evidence.get('propositions',[]):
                if p.get('theme') and p.get('subject_role')=='ISSUER_EVENT':
                    by_theme[p['theme']].append({**deepcopy(p),'published_at':evidence.get('published_at'),
                        'title':evidence.get('title'),'source_refs':deepcopy(evidence.get('source_refs',[])),
                        'source_url':evidence.get('source_url'),'event_id':evidence.get('event_id'),
                        'temporal_role':'NEW_PLAN_PUBLICATION' if _recent(evidence,context) else 'BACKGROUND_OR_PUBLICATION_UNKNOWN',
                        'provenance_scope':'VERIFIED_ISSUER_BODY_PROJECTION'})
    rows=[]
    for key in sorted(by_theme):
        frags=sorted({(f['evidence_id'],f['source_field'],f['start'],f['quote']):f for f in by_theme[key]}.values(),
                     key=lambda f:(str(f.get('published_at') or ''),f['evidence_id'],f['start']))
        recent=[f for f in frags if f['temporal_role']=='NEW_PLAN_PUBLICATION']
        links=[];mapping_rejections=[]
        from .workspace_plan import temporal_role
        usable_background=[f for f in frags if timestamp(f.get('published_at')) and temporal_role(f,context)!='AFTER_CUTOFF_EXCLUDED']
        mapping_sources=recent or (usable_background if key=='PHARMA_INDUSTRY_PLAN' else [])
        for stock in stocks:
            for e in stock['evidence']:
                for p in e.get('propositions',[]):
                    if not _exposure(key,p) or not mapping_sources:continue
                    if temporal_role(e,context)=='AFTER_CUTOFF_EXCLUDED':continue
                    # Firm business role may be background; explicitly label it.
                    # A historical quantified holding is never current exposure.
                    external=[f for f in mapping_sources if f['evidence_id'] not in {p['evidence_id'],e.get('material_id')}]
                    if not external:continue
                    admission=None
                    if key=='AI_APPLICATION':
                        compatible=[]
                        for candidate in external:
                            check=_application_admission(p,candidate)
                            if check['status']=='PASS':
                                compatible.append((candidate,check))
                            else:
                                mapping_rejections.append(dict(symbol=stock['symbol'],theme=key,
                                    issuer_evidence_id=p['evidence_id'],issuer_proposition_id=p['proposition_id'],
                                    issuer_quote=p['quote'],theme_evidence_id=candidate['evidence_id'],
                                    theme_proposition_id=candidate['proposition_id'],theme_quote=candidate['quote'],
                                    issuer_published_at=e.get('published_at'),theme_published_at=candidate.get('published_at'),
                                    disposition='THEME_RETAINED_NO_STOCK_LINK_OR_INFERENCE_ACTION',
                                    supporting_quotes=[{**{k:item[k] for k in ('evidence_id','proposition_id','quote','source_field','start','end')},
                                        'symbol':item.get('symbol') if role=='ISSUER_PROPOSITION' else None,
                                        'support_kind':role,'application_anchors':deepcopy(anchors)}
                                        for item,role,anchors in ((p,'ISSUER_PROPOSITION',check['issuer_anchors']),
                                                                 (candidate,'THEME_PROPOSITION',check['theme_anchors']))],
                                    mapping_admission=check))
                        if not compatible:continue
                        support,admission=compatible[0]
                    elif key in {'PHARMA_INDUSTRY_PLAN','PHARMA_CROSS_BORDER_POLICY'}:
                        compatible=[(f,_pharma_admission(key,p,f)) for f in external]
                        compatible=[item for item in compatible if item[1]['status']=='PASS']
                        if not compatible:continue
                        support,admission=compatible[0]
                    else:
                        support=external[0]
                    links.append(dict(symbol=stock['symbol'],relationship_type='INDUSTRY_INFERENCE',
                        issuer_evidence_id=p['evidence_id'],issuer_proposition_id=p['proposition_id'],
                        issuer_quote=p['quote'],issuer_published_at=e.get('published_at'),
                        issuer_available_at=(e.get('available_at') or e.get('retrieved_at')
                                             or e.get('first_seen_at') or e.get('collected_at')),
                        theme_evidence_id=support['evidence_id'],theme_proposition_id=support['proposition_id'],
                        theme_quote=support['quote'],theme_published_at=support.get('published_at'),
                        supporting_quotes=[{**{k:p[k] for k in ('evidence_id','proposition_id','symbol','quote','source_field','start','end')},'support_kind':'ISSUER_PROPOSITION'},
                            {**{k:support[k] for k in ('evidence_id','proposition_id','quote','source_field','start','end')},'symbol':None,'support_kind':'THEME_PROPOSITION'}],
                        theme=key,window_status='CURRENT_WINDOW_RESEARCH' if support in recent else 'BACKGROUND_REFERENCE',
                        source_refs=[*deepcopy(e.get('source_refs',[])),*deepcopy(support.get('source_refs',[]))],
                        reason='当前窗口产业命题与本股原文业务命题分别成立才建立研究映射；不证明本股新增合作、订单或收入。'))
                    if admission is not None:
                        links[-1]['mapping_admission']=admission
                        if admission.get('mechanism'):links[-1]['reason']=admission['mechanism']
                    if admission is not None and key=='AI_APPLICATION':
                        for item,anchors in zip(links[-1]['supporting_quotes'],
                                                (admission['issuer_anchors'],admission['theme_anchors'])):
                            item['application_anchors']=deepcopy(anchors)
        links=sorted({(l['symbol'],l['issuer_proposition_id']):l for l in links}.values(),key=lambda l:(l['symbol'],l['issuer_proposition_id']))
        groups=event_groups([{**f,'event_id':f.get('event_id') or f['evidence_id']} for f in frags])
        gaps=['CURRENT_MARKET_BREADTH_AMOUNT_INDEX_OWNER_INPUT_MISSING']
        if key=='DIGITAL_ASSET_EXPOSURE':gaps.append('CURRENT_EXPOSURE_AND_SAME_WINDOW_CRYPTO_PRICE_MISSING')
        if key=='PHARMA_CROSS_BORDER_POLICY':gaps.append('PRIMARY_REUTERS_MATERIALSTORE_ADMISSION_NOT_PROVEN')
        official=any(f.get('provenance_scope')=='VERIFIED_ISSUER_BODY_PROJECTION' for f in frags)
        state=('REPORTED_PROPOSAL_NOT_FINAL' if key=='PHARMA_CROSS_BORDER_POLICY' else
            'REGULATORY_OPINION_NOT_FINAL_APPROVAL' if key=='REGULATORY_OPINION' else
            'EXPOSURE_AND_PRICE_UNVERIFIED' if key=='DIGITAL_ASSET_EXPOSURE' else 'RESEARCH_CLAIM_REQUIRES_PRIMARY_CHECK')
        rows.append(dict(theme=key,label=LABELS.get(key,key),evidence_ids=sorted({f['evidence_id'] for f in frags}),
            evidence=frags,material_group_count=len(groups),evidence_count=len(frags),new_catalyst_count=0,
            mapped_symbols=sorted({l['symbol'] for l in links}),mapped_stock_count=len({l['symbol'] for l in links}),
            mappings=links,source_days=sorted({str(f['published_at'])[:10] for f in frags if f.get('published_at')}),
            status='MAPPED_RESEARCH' if links else 'THEME_ONLY_MAPPING_REQUIRED',claim_state=state,
            window_status='CURRENT_WINDOW_RESEARCH' if recent else 'BACKGROUND_OR_TIME_UNKNOWN',
            priority_reason=('当前窗口有具体正文命题；尚未被同窗口行情确认。' if recent else '只有窗口前背景或缺精确发布时间；不升为当日强主线。'),
            display_group='CURRENT_RESEARCH' if recent else 'BACKGROUND',
            official_admission_status='ISSUER_BODY_VALIDATED' if official else 'NOT_ESTABLISHED_FROM_READER_PROJECTION',
            market_confirmation=_market_gap(),gaps=gaps,
            company_mapping_gaps=_company_mapping_gaps(key,stocks,links,context)))
        if key=='AI_APPLICATION':
            rows[-1]['mapping_rejections']=mapping_rejections
            rows[-1]['mapping_rule_version']=_APPLICATION_SCOPE_RULE
    # Stable research reading order, NOT an economic-strength ranking. No raw
    # counts, stock returns or handpicked issuer identities enter this key.
    group_order={'OFFICIAL_COMPANY_EVENT':0,'RULE_STATUS_VERIFICATION':1,'MAPPED_INDUSTRY_MECHANISM':2,
                 'UNMAPPED_RESEARCH':3,'BACKGROUND':4,'EXPOSURE_PRICE_MISSING':5}
    for theme in rows:
        group=('BACKGROUND' if theme['display_group']=='BACKGROUND' else
               'OFFICIAL_COMPANY_EVENT' if theme['official_admission_status']=='ISSUER_BODY_VALIDATED' else
               'RULE_STATUS_VERIFICATION' if theme['claim_state']=='REPORTED_PROPOSAL_NOT_FINAL' else
               'EXPOSURE_PRICE_MISSING' if theme['claim_state']=='EXPOSURE_AND_PRICE_UNVERIFIED' else
               'MAPPED_INDUSTRY_MECHANISM' if theme['mapped_symbols'] else 'UNMAPPED_RESEARCH')
        theme['review_priority']=dict(group=group,market_strength_rank=None,
            reason='先核直接公告与影响适用范围的规则状态，再核双证据行业映射；这是核验次序，不是政策评价、市场强弱或股票收益排名。')
    rows.sort(key=lambda t:(group_order[t['review_priority']['group']],t['theme']))
    company_events=[]
    for stock in stocks:
        own=[];mapped=[]
        for e in stock['evidence']:
            for p in e.get('propositions',[]):
                if (_recent(e,context) and p.get('event_type') not in {'ISSUER_RESEARCH','VALUATION_OPINION'}
                        and (not p.get('event_date_claim') or p['event_date_claim']>=str(context.get('market_session')))
                        and p.get('claim_status')!='UNCONFIRMED_REPORT' and p.get('theme')!='DIGITAL_ASSET_EXPOSURE'):
                    own.append((e,p))
        for theme in rows:
            mapped.extend(l for l in theme['mappings'] if l['symbol']==stock['symbol'])
        active_mapped=[m for m in mapped if m.get('window_status')=='CURRENT_WINDOW_RESEARCH']
        direct=any(p['subject_role']=='ISSUER_EVENT' for _,p in own)
        # Direct event evidence, company research, industry inference, background
        # remain distinct. Eligibility/market confirmation are separate gates.
        group='DIRECT_COMPANY_EVENT' if direct else ('COMPANY_RESEARCH' if own else ('INDUSTRY_INFERENCE' if active_mapped else 'BACKGROUND_OR_PRICE_ONLY'))
        stock['is_focus']=bool(own or active_mapped)
        stock['attention_priority']='FOCUS_REVIEW' if stock['is_focus'] else 'RESEARCH_WATCH'
        stock['priority_basis']=dict(group=group,formal_rank_unchanged=True,market_strength_confirmed=False,
            method='EVIDENCE_ROLE_THEN_TIME_WINDOW_NO_COUNT_SCORE',
            evidence_ids=sorted({p['evidence_id'] for _,p in own}|{l['issuer_evidence_id'] for l in active_mapped}|{l['theme_evidence_id'] for l in active_mapped}),
            reason=('公司当前窗口直接事件正文；市场承接仍待验证。' if direct else '当前窗口有本股具体命题，属于研究陈述而非正式买入确认。' if own else
                '当前窗口主题与本股原文业务证据有可审查关联；仅产业推断，未证明新增公司事件。' if active_mapped else
                '只有背景、缺时点或原量价观察，没有足够依据升为重点。'))
        stock['material_relations']=mapped
        if mapped:
            from .workspace_actions import inference_conditions
            for link in mapped:
                confirm,risk,invalid=inference_conditions(link)
                explanation=f"产业推断：主题原文「{link['theme_quote']}」；本股业务原文「{link['issuer_quote']}」。不宣称本股与主题公司存在新合同或合作。"
                for kind,text in (('WATCH',explanation+confirm),('WAIT',risk),('INVALIDATE',invalid)):
                    pid=digest([link['issuer_proposition_id'],link['theme_proposition_id'],kind])
                    stock['plan']['actions'].append(dict(action_id=pid,type=kind,text=text,
                        rule_id='INDUSTRY_INFERENCE_'+link['theme'],
                        evidence_ids=[link['issuer_evidence_id'],link['theme_evidence_id']],
                        proposition_ids=[link['issuer_proposition_id'],link['theme_proposition_id']],
                        supporting_quotes=deepcopy(link['supporting_quotes']),
                        assertion_type='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT',orders_sent=False))
            acts=list({a['action_id']:a for a in stock['plan']['actions']}.values())
            stock['plan'].update(actions=acts,evidence_ids=sorted({eid for a in acts for eid in a['evidence_ids']}),
                next_observation=list(dict.fromkeys(a['text'] for a in acts if a['type']=='WATCH')),
                wait_conditions=list(dict.fromkeys(a['text'] for a in acts if a['type'] in {'WAIT','NO_CHASE'})),
                key_risks=list(dict.fromkeys(a['text'] for a in acts if a['type']=='WAIT')),
                invalidation_conditions=list(dict.fromkeys(a['text'] for a in acts if a['type']=='INVALIDATE')))
        # Preserve the Stage row, but do not use its membership as a catalyst.
        if own:
            ordered_own=sorted(own,key=_event_reading_key)
            reasons=[f"原文研究命题：{p['quote']}" for _,p in ordered_own]
        elif active_mapped:
            reasons=[f"产业推断：{m['issuer_quote']}；{m['reason']}" for m in active_mapped]
        else:
            reasons=[stock['priority_basis']['reason']]
        stock['why_watch']=list(dict.fromkeys(reasons))
        # No more old misleading promotion label based solely on new IDs/counts.
        if stock.get('change',{}).get('status')=='UPGRADED' and not stock['is_focus']:
            stock['change'].update(status='UNCHANGED',reasons=['新增记录未形成有效当前窗口本股命题，不升档。'])
        for e,p in own:
            company_events.append(dict(symbol=stock['symbol'],name=stock['name'],group=group,
                evidence_id=p['evidence_id'],proposition_id=p['proposition_id'],quote=p['quote'],
                published_at=e.get('published_at'),available_at=e.get('available_at'),retrieved_at=e.get('retrieved_at'),
                mirror_observed_at=e.get('mirror_observed_at'),time_basis=e.get('time_basis','SOURCE_PUBLICATION'),
                publication_status=e.get('publication_status'),source_refs=deepcopy(e.get('source_refs',[])),
                body_sha256=e.get('body_sha256'),art_code=e.get('art_code'),
                claim_status=p['claim_status'],event_type=p['event_type']))
    order={'DIRECT_COMPANY_EVENT':0,'COMPANY_RESEARCH':1,'INDUSTRY_INFERENCE':2,'BACKGROUND_OR_PRICE_ONLY':3}
    stocks.sort(key=lambda s:(order[s['priority_basis']['group']],s['symbol']))
    company_events=sorted({(e['symbol'],e['quote'],e['event_type']):e for e in company_events}.values(),
                          key=lambda e:(order[e['group']],e['symbol'],e['proposition_id']))
    return dict(themes=rows,company_events=company_events,focus_symbols=[s['symbol'] for s in stocks if s['is_focus']],
        briefing=dict(business_status='PARTIAL_RESEARCH_NOT_MARKET_CONFIRMED',market_scope='NOT_VERIFIED_FULL_MARKET',
            headline='先核当前窗口产业命题和公司事件，再核本股证据；强弱尚缺同窗口行情确认。',
            ordering_explanation='主题按直接公告／规则待核／双证据产业映射顺序核验，不等于强弱排名。股票按证据角色和时间窗展示；同级按证券代码稳定排列，不按转载数、泛化词频或涨幅，不是正式排名。',
            focus_count=sum(s['is_focus'] for s in stocks),not_a_full_market_sector_ranking=True,
            gaps=['CURRENT_MARKET_BREADTH_AMOUNT_INDEX_OWNER_INPUT_MISSING']))
