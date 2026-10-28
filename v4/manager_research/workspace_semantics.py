"""Conservative issuer/proposition attribution over already-read evidence.

No fetching, security-master replacement, or material admission. Absence of a
local subject/action is a REVIEW GAP, not permission to spread a paragraph's
keywords to every mentioned issuer. Rules are role/grammar based, never ticker
allowlists or broker blacklists. Rejected relationships retain their lineage.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import canonical_symbol, digest

SEMANTIC_VERSION = '20260921.manager-semantic.r3.v1'  # R3 wire/fixture contract unchanged
PARSER_REVISION = '20260930.subject-action.mirror-bound.r1'
# Only fields carried through an original reader are used. No filename is
# opened and no text is manufactured when an exported row lacks a body.
BODY_FIELDS = ('transcript', 'body_text', 'content_text', 'body', 'text',
               'evidence_sentence', 'summary')
FILE_RE = re.compile(r'\.(?:mp3|mp4|wav|m4a|pdf|docx?|pptx?)(?:\b|$)', re.I)
SPECULATION_RE = re.compile(r'动的时候|名字.{0,8}(?:相似|相同)|同名|名字带|谐音|玄学|蹭.{0,6}名字|炒作.{0,15}名字')
_VARIANTS = str.maketrans({'機':'机','產':'产','術':'术','購':'购','獲':'获','簽':'签','協':'协','議':'议','訂':'订',
    '單':'单','長':'长','貨':'货','臨':'临','試':'试','驗':'验','營':'营','許':'许','權':'权','發':'发','藥':'药','淨':'净','潤':'润','億':'亿','減':'减','團':'团','資':'资','業':'业','務':'务','銷':'销'})
ACTION_RE = re.compile(
    r'簽署|達成|獲批|訂單|交付|營收|淨利|產能|量產|研發|增長|購回|回購|授權|許可|'
    r'参股|入股|投资于|收购|公告|回购|增持|分红|签署|达成|完成|启动|启动|获批|提交|批准|积极意见|正面意见|CHMP|'
    r'产量|毛利率|利润率|临床|保费|收入|营收|净利|盈利|订单|交付|销量|产能|量产|推出|发布|合作|授权|许可|'
    r'研发|研究|增长|下降|提高|下调|上调|亏损|需求|价格|渠道|新品|持有|减值|融资|'
    r'\b(?:announced|reported|repurchase|revenue|profit|license|licensing|trial|delivery|contract|adopted)\b', re.I)
AUTHOR_RE = re.compile(r'研究|前瞻|策略|证券分析师|分析师|周观点|行业报告|电话会|研报|证券研报|research|analyst', re.I)
SELF_ACTION_RE = re.compile(r'回购|分红|增持|配股|净利润|营收|本公司|董事会|业绩公告|自身|注销股份|repurchase|our company', re.I)
PEER_RE = re.compile(r'包括|例如|比如|建议关注|推荐关注|看好|受益标的|标的包括|同行|对标|参考')


def alias_of(name: str) -> str:
    return re.sub(r'-(?:SW|SS|W|B|P|R)$', '', name.strip(), flags=re.I)


def is_file_locator(text: str) -> bool:
    """A sequence of tags/filename lines is not prose, even with industry words."""
    if not FILE_RE.search(text):
        return False
    # Text after a filename can be actual transcript. Require an independently
    # delimited substantive clause, not the descriptive filename before .pdf.
    for piece in re.split(r'[\n。；;]', text):
        if not piece.strip() or FILE_RE.search(piece):
            continue
        clean = re.sub(r'#[^#]*#|[【\[（(].*?[】\]）)]', '', piece).strip()
        if len(clean) >= 12 and ACTION_RE.search(clean):
            return False
    return True


def prose_sources(value: Mapping[str, Any]) -> list[tuple[str, str]]:
    row = value.get('source_row') or value.get('original_source_row') or {}
    sources: list[tuple[str, str]] = []
    if isinstance(row, Mapping):
        # Full body/transcript takes precedence over an extractor's filename.
        for key in BODY_FIELDS:
            body = row.get(key)
            if isinstance(body, str) and body.strip() and not is_file_locator(body):
                sources.append(('source_row.' + key, body))
                if key in BODY_FIELDS[:5]:
                    return sources
        if sources:
            return sources
        if any(isinstance(row.get(k), str) and row[k].strip() for k in BODY_FIELDS):
            return []
    # Admitted event/official body excerpts have no archive source_row. They
    # are still re-attributed, rather than trusted based on old mapping_reason.
    for key in ('relation_quote', 'evidence_quote', 'source_excerpt'):
        body = value.get(key)
        if isinstance(body, str) and body.strip() and not is_file_locator(body):
            return [(key, body)]
    return []


def evidence_id(value: Mapping[str, Any]) -> str:
    return str(value.get('card_id') or value.get('material_id') or value.get('event_id') or digest(value))


def mechanism(text: str) -> str | None:
    """Narrow mechanisms, not the upstream concatenated theme tag list."""
    t = text.translate(_VARIANTS).casefold()
    if (re.search(r'美国|\bus\b|\bu\.s\.|treasury', t)
            and re.search(r'许可|授权|licens', t)
            and re.search(r'药|pharma|drug|biotech', t)
            and re.search(r'拟|规则|政策|限制|起草|allow|weigh|rules?|restric|propos', t)):
        return 'PHARMA_CROSS_BORDER_POLICY'
    if re.search(r'chmp', t) and re.search(r'positive|积极|正面|意见|opinion', t):
        return 'REGULATORY_OPINION'
    if re.search(r'医药工业|药.*十五五|十五五.*药', t) and re.search(r'规划|部门|工信', t):
        return 'PHARMA_INDUSTRY_PLAN'
    if (re.search(r'\bai\b|ai4s|aidd|人工智能|anthropic|ai制药|ai医药', t)
            and re.search(r'药|临床|抗体|体内验证|drug|pharma|laborator|实验室', t)):
        return 'AI_DRUG_RND'
    if re.search(r'以太坊|比特币|数字资产|虚拟币|加密货币|ethereum|bitcoin|\beth\b|\bbtc\b', t):
        return 'DIGITAL_ASSET_EXPOSURE'
    if re.search(r'临床|试验终点|clinical|phase\s*(?:iii|ii|3|2)', t):
        return 'DRUG_DEVELOPMENT'
    if re.search(r'授权|许可|\bbd\b|licens', t) and re.search(r'药|管线|pharma|drug', t):
        return 'PHARMA_COMPANY_LICENSING'
    if re.search(r'人形机器人|协作机器人|工业机器人|具身智能|机器人.{0,16}(?:订单|量产|发布会|审厂|供应链|产品)|robotics|optimus', t):
        return 'ROBOTICS'
    if re.search(r'算力|数据中心|gpu|aidc|服务器', t):
        return 'AI_COMPUTE'
    if re.search(r'大模型|agent|人工智能|\bai\b', t):
        return 'AI_APPLICATION'
    return None


def event_type(text: str) -> str:
    text=text.translate(_VARIANTS)
    theme = mechanism(text)
    if theme == 'REGULATORY_OPINION':
        return 'REGULATORY_OPINION'
    if theme == 'PHARMA_CROSS_BORDER_POLICY':
        return 'POLICY_INFERENCE'
    if re.search(r'股价|估值|强推|低估',text) and not re.search(r'(?:营收|收入|净利|利润|订单|销量).{0,15}\d|公告|签署|完成',text):
        return 'VALUATION_OPINION'
    if re.search(r'参股|入股|回购|增持|分红|股份收购|repurchase', text, re.I):
        return 'OWNERSHIP_CHANGE'
    if re.search(r'临床|试验终点|clinical|phase\s*(?:iii|ii|3|2)', text, re.I):
        return 'CLINICAL_MILESTONE'
    if re.search(r'许可|授权|\bBD\b|licens', text, re.I) and re.search(r'药|管线|pharma|drug|获得|取得|签署|对外|完成|\bBD\b', text, re.I):
        return 'LICENSING'
    if theme == 'DIGITAL_ASSET_EXPOSURE':
        return 'DIGITAL_ASSET_EXPOSURE'
    if re.search(r'保费|保险|偿付能力|新业务价值', text):
        return 'INSURANCE_OPERATING'
    if re.search(r'产量|毛利率|利润率|盈利|净利|营收|收入|订单|销量|业绩|增长|下降|需求|渠道|新品|通知.{0,8}上调|价格.{0,8}执行', text):
        return 'OPERATING_TREND'
    if re.search(r'模型|AI|人工智能|合作|机器人|技术|产品|交付|发布|推出', text, re.I):
        return 'TECH_OR_PARTNERSHIP'
    return 'ISSUER_RESEARCH'


def _publisher(text: str, start: int, end: int, alias: str, title: str) -> bool:
    before, after = text[max(0, start-25):start], text[end:end+85]
    # Explicit issuer disclosure wins over author metadata only for this
    # occurrence; a second publisher occurrence is still rejected separately.
    if re.match(r'\s*(?:[】\]]\s*)?(?:公告|宣布|披露|董事会)', after) and SELF_ACTION_RE.search(after):
        return False
    if re.match(r'\s*(?:发布|发表|出具).{0,14}(?:行业|研究|研报|报告)', after):
        return True
    if re.match(r'\s*(?:研究|前瞻|策略|分析师)', after):
        return True
    if ('【' in before or '[' in before or '】' in after[:20]) and re.search(r'】|\]', after[:25]):
        # Author signature [issuer sector] is not the subject of the report.
        return not bool(SELF_ACTION_RE.search(after.split('】',1)[0].split(']',1)[0]))
    if re.match(r'\s*[-—｜|]', after) and re.search(r'行业|研报|报告|周报|展望|回顾', after):
        return True
    if re.match(r'\s*(?:表示|认为|指出|预计|建议|研报称|称)', after):
        return not bool(re.match(r'\s*(?:表示|称).{0,12}(?:本公司|自身|本集团)', after))
    return False


def _context_role_issue(text: str, start: int, end: int) -> str | None:
    before,after=text[max(0,start-100):start],text[end:]
    if re.match(r"\s*、",after):
        return 'MENTIONED_PEER_LIST_NOT_SUBJECT'
    if re.search(r"(?:赛道|领域|行业|版|下一个|下一个可能是).{0,8}[“\"]$|的[“\"]$",before):
        return 'METAPHOR_OR_PEER_COMPARISON_NOT_SUBJECT'
    if re.search(r"(?:到访|拜访|走访|审厂第一站.{0,8}为).{0,6}$",before):
        return 'COUNTERPARTY_OR_VISIT_TARGET_NOT_SUBJECT'
    if re.search(r"(?:获得|获取|取得).{0,70}$",before) and re.match(r".{0,20}(?:批量)?订单",after):
        return 'CUSTOMER_NAME_NOT_ORDER_RECIPIENT'
    return None


def _paired_code_issue(text: str, end: int, symbol: str, identity_row: Mapping[str, Any]) -> str | None:
    match = re.match(r'\s*[（(]\s*((?:HK\.)?\d{1,6}(?:\.HK)?)\s*[）)]', text[end:], re.I)
    if not match:
        return None
    code = match[1].upper()
    if re.fullmatch(r'\d{6}', code):
        # A/H equivalence needs the original identity owner, not a guessed
        # conversion of a stock_pool extraction label.
        expected = str(identity_row.get('a_share_code') or '')
        if expected == code:
            return None
        return 'NAME_CODE_CONFLICT' if expected else 'NAME_CODE_PAIR_UNVERIFIED'
    return None if canonical_symbol(code) == symbol else 'NAME_CODE_CONFLICT'


@lru_cache(maxsize=4096)
def _cached_issuer_pattern(pattern: str) -> re.Pattern[str]:
    """Compiled syntax only; no text, issuer decision, or source verdict cached.

    _spans limits cache keys to 512 characters. Larger patterns use the same
    uncached compilation path; they are not rejected or truncated.
    """
    return re.compile(pattern, re.I)


def _spans(text: str, names: Mapping[str, str]) -> list[tuple[int,int,str]]:
    candidates=[]
    for symbol,name in names.items():
        alias=alias_of(name)
        if len(alias)<2:continue
        pattern=re.escape(alias)
        if alias.isascii():pattern=r'(?<![A-Za-z0-9])'+pattern+r'(?![A-Za-z0-9])'
        compiled = (_cached_issuer_pattern(pattern) if len(pattern) <= 512
                    else re.compile(pattern, re.I))
        for found in compiled.finditer(text):
            candidates.append((found.start(),found.end(),symbol))
    # Longest-contained name wins; duplicate aliases remain ambiguous.
    out=[]
    for a,b,s in candidates:
        if any(c<=a and b<=d and (d-c>b-a or (a==c and b==d and s!=t)) for c,d,t in candidates):continue
        out.append((a,b,s))
    return sorted(set(out))



# Scope repair, not a general coreference model. Only sentence-local explicit
# pairs or a sole antecedent may donate an omitted/pronominal subject. Anonymous
# counterparties are retained as UNRESOLVED entities; they never become HK codes.
_CLAUSE_BREAK = re.compile(r'，|(?<!\d),(?!\d)|(?<!不)但是|(?<!不)但|然而|不过|而且|并且|而(?!后|今|言)|(?=前者|后者)')
_REFERENCE = re.compile(r'\s*(?:(?:公告|披露|表示|正文显示|报告指出)[：:\s]*)?(前者|后者|本公司|该公司|本集团|本集團|该集团|公司|其(?!他|余))')
_ANONYMOUS = re.compile(r'(?:某(?:一?家)?|一家|另一家|被投|未上市|非上市)[\u3400-\u9fffA-Za-z0-9]{0,10}?(?:公司|企业|药企|银行|集团|主体|厂商|供应商)')
_RELATION = re.compile(r'\s*(?:与|和|及|同|参股|入股|投资(?:于)?|控股|收购)\s*')
_INVESTMENT = re.compile(r'\s*(?:参股|入股|投资(?:于)?|控股|收购)\s*$')
_NOT_YET = re.compile(r'尚未|还未|仍未|暂未|未获|未经|待.{0,4}批准')
_NEGATION = re.compile(r'沒有|並未|並非|否認|否认|否定|并非|并不|并未|并无|不存在|不是|从未|未曾|未能|没有|不曾|不涉及|不参与|不属于|不持有|不开展|不承担|不从事|不进行|不生产|不经营|不提供|未(?!来|知)')
_CONTINUATION = re.compile(r'(?:(?:目前|累计|已经|继续|仍|也|再|将|并|已|现|预计|有望|同时|关键|相关|单季|本期|同比|环比)\s*)*(?:完成|实现|达成|签署|推出|发布|启动|交付|增长|下降|上调|下调|新增|取得|获得|临床|订单|保费|营收|收入|净利|盈利|销量|产量|毛利率|利润率|产能)')
_EMBEDDED_SUBJECT = re.compile(r'\s*(?:(?:公告|披露|表示|宣布|报告)(?:称)?[：:\s]*)?(?:其)?(?:(?:参股|控股|被投)(?:公司|企业|药企)|旗下.{0,12}?(?:公司|企业|药企)|子公司|附属公司)')
_REPORT = re.compile(r'(?:行业)?研究报告|行业报告|研报|调研纪要|会议纪要|研究纪要|年度报告|报告')


def _clause_ranges(text: str) -> list[tuple[int,int]]:
    """Split at unquoted clause boundaries, preserving original coordinates."""
    protected=set();stack=[];pairs={'（':'）','(' : ')','【':'】','[':']','“':'”','「':'」','『':'』','"':'"'}
    for i,char in enumerate(text):
        if stack:
            protected.add(i)
            if char==stack[-1]:stack.pop();continue
        if char in pairs:stack.append(pairs[char]);protected.add(i)
    ranges=[];left=0
    for m in _CLAUSE_BREAK.finditer(text):
        if m.start() in protected:continue
        if m.start()>left:ranges.append((left,m.start()))
        left=m.end()
    if left<len(text):ranges.append((left,len(text)))
    return [(a+len(text[a:b])-len(text[a:b].lstrip()),b-len(text[a:b])+len(text[a:b].rstrip()))
            for a,b in ranges if text[a:b].strip()]


def _polarity(text: str) -> str:
    # Multiple/nested operators are NOT algebraically simplified into a fact.
    operators=list(_NEGATION.finditer(text))
    if len(operators)>1:return 'UNCERTAIN'
    if _NOT_YET.search(text):return 'NOT_YET'
    if operators:return 'NEGATED'
    if re.search(r'是否|有无|尚待核|待核实|不能确认|无法确认',text):return 'UNCERTAIN'
    return 'AFFIRMED'


def _report_locator(text: str) -> bool:
    if not _REPORT.search(text):return False
    # A predicate inside the TITLE of a report is not an assertion by its body.
    if re.search(r'(?:发布|发表|出具|关于).*(?:报告|研报|纪要)[》」】\s]*$',text):return True
    if re.search(r'(?:研究报告|行业报告|研报|研究纪要)[》」】\s]*$',text):return True
    return False


def _referents(text: str, names: Mapping[str,str]) -> list[dict]:
    spans=_spans(text,names)
    out=[dict(start=a,end=b,symbol=code,eligible=not (SPECULATION_RE.search(text) or _context_role_issue(text,a,b))) for a,b,code in spans
         if not _publisher(text,a,b,alias_of(names[code]),'')]
    for match in _ANONYMOUS.finditer(text):
        if not any(a<match.end() and match.start()<b for a,b,_ in spans):
            out.append(dict(start=match.start(),end=match.end(),symbol=None))
    # A relation to a non-master name must obstruct singular inheritance even
    # without a marker such as 某. We do not attempt to identify that object.
    for a,b,code in spans:
        match=re.match(r'\s*(?:参股|入股|投资于|控股|收购)\s*([^，,。；;：:]+)',text[b:])
        if match:
            left=b+match.start(1);right=b+match.end(1)
            if not any(e['start']<right and left<e['end'] for e in out):
                out.append(dict(start=left,end=right,symbol=None))
    return sorted(out,key=lambda e:(e['start'],e['end']))


def _claim_frames(text: str, names: Mapping[str,str]) -> list[dict]:
    """Frames carry action span, original actor anchor and auditable scope."""
    frames=[];history=[];previous_right=0;previous_polarity='AFFIRMED'
    for left,right in _clause_ranges(text):
        clause=text[left:right];spans=_spans(clause,names)
        boundary=text[previous_right:left];coordination_uncertain=False
        refs=_referents(clause,names)
        absolute=[{**e,'start':left+e['start'],'end':left+e['end']} for e in refs]
        # Exactly two named parties with an explicitly shared cooperation
        # predicate may retain that fact; a peer list may not share predicates.
        joint=False
        if len(spans)==2 and len(refs)==2:
            a,b,first=spans[0];c,d,second=spans[1]
            joint=bool(re.fullmatch(r'\s*(?:与|和|同)\s*',clause[b:c]) and
                re.match(r'\s*(?:合作|联合|共同|签署.{0,8}(?:合作|协议))',clause[d:]))
        for index,(a,b,code) in enumerate(spans):
            end=spans[index+1][0] if index+1<len(spans) else len(clause)
            reason=None;context_left=left+a;action_left=left+b
            quote_left=left+a;quote_right=left+end
            resolution='EXPLICIT_SUBJECT'
            before=clause[:a]
            if _INVESTMENT.search(before):reason='INVESTEE_NOT_ACTION_SUBJECT'
            if index+1<len(spans) and _INVESTMENT.fullmatch(clause[b:spans[index+1][0]]):
                # Keep the investment fact, not an unpunctuated investee action.
                quote_right=left+spans[index+1][1]
            if joint:
                quote_left=left+spans[0][0];quote_right=right
                context_left=quote_left;action_left=left+spans[-1][1]
                resolution='EXPLICIT_JOINT_COOPERATION'
            frames.append(dict(symbol=code,start=quote_left,end=quote_right,
                action_start=action_left,action_end=quote_right,subject_start=left+a,subject_end=left+b,
                subject_resolution=resolution,context_start=context_left,context_end=quote_right,
                clause_start=left,clause_end=right,role_reason=reason))
        if not spans and ACTION_RE.search(clause):
            reference=_REFERENCE.match(clause)
            token=reference[1] if reference else None
            unique=[]
            for e in history:
                key=e['symbol'] or ('UNRESOLVED',text[e['start']:e['end']])
                if key not in [x[0] for x in unique]:unique.append((key,e))
            antecedents=[e for _,e in unique]
            selected=None;resolution='SOLE_ANTECEDENT_CONTINUATION'
            if token in {'前者','后者'}:
                if len(antecedents)==2:
                    one,two=antecedents
                    if _RELATION.fullmatch(text[one['end']:two['start']]):
                        selected=one if token=='前者' else two
                        resolution='FORMER_OF_EXPLICIT_PAIR' if token=='前者' else 'LATTER_OF_EXPLICIT_PAIR'
            elif len(antecedents)==1 and not refs and (token or _CONTINUATION.match(clause)) and not re.match(r'行业|板块|市场|同行|客户|被投|其他|另[一外]|某',clause):
                selected=antecedents[0]
                resolution='SOLE_ANTECEDENT_PRONOUN' if token else resolution
            resolved=selected is not None and selected['symbol'] is not None and selected.get('eligible',False)
            coordination_uncertain=bool(previous_polarity!='AFFIRMED' and
                not re.search(r'但|然而|不过|而(?!且)',boundary) and
                (re.match(r'\s*(?:并|且|也|同时|还)',clause) or re.search(r'并且|而且',boundary)))
            if coordination_uncertain:resolved=False
            frames.append(dict(symbol=selected['symbol'] if resolved else None,start=left,end=right,
                action_start=left+(reference.end() if reference else 0),action_end=right,
                subject_start=selected['start'] if resolved else left,
                subject_end=selected['end'] if resolved else left,
                subject_resolution=resolution if resolved else 'UNRESOLVED_REFERENT',
                context_start=min((e['start'] for e in antecedents),default=left),context_end=right,
                clause_start=left,clause_end=right,
                role_reason=('NEGATION_COORDINATION_SCOPE_UNRESOLVED' if coordination_uncertain else
                    None if resolved else 'ACTION_REFERENT_UNRESOLVED'),
                forced_polarity='UNCERTAIN' if coordination_uncertain else 'UNRESOLVED',reference=token))
        history.extend(absolute)
        previous_right=right
        previous_polarity='UNCERTAIN' if coordination_uncertain else _polarity(clause)
    return frames


def assess(value: Mapping[str, Any], name: str, symbol: str, *,
           names: Mapping[str, str] | None = None,
           identity_row: Mapping[str, Any] | None = None) -> dict:
    """Return only local propositions plus an audit entry for every rejection."""
    catalogue=dict(names or {});catalogue[symbol]=name
    alias=alias_of(name);eid=evidence_id(value)
    propositions=[];rejected=[]
    def reject(reason: str, field: str, quote: str, start: int = 0, end: int | None = None):
        rejected.append(dict(evidence_id=eid,symbol=symbol,name=name,reason=reason,source_field=field,
            quote=quote,start=start,end=len(quote) if end is None else end,
            material_id=value.get('material_id'),source_refs=deepcopy(value.get('source_refs',[])),
            published_at=value.get('published_at'),title=value.get('title'),semantic_version=SEMANTIC_VERSION))
    sources=prose_sources(value)
    from .announcement_materials import is_mirror, mirror_binding_valid, substantive_propositions
    bound_document=(is_mirror(value) and mirror_binding_valid(value) and value.get('document_issuer_symbol')==symbol)
    if not sources:
        reject('FILE_LOCATOR_OR_BODY_MISSING','title',str(value.get('title') or ''))
        return dict(propositions=[],rejected=rejected)
    for field,body in sources:
        units=list(re.finditer(r'[^\n。！？；;]+',body))
        matched=False
        for unit in units:
            text=unit[0];spans=_spans(text,catalogue)
            offset=unit.start()
            frames=_claim_frames(text,catalogue)
            if (bound_document and not spans
                    and not re.search(r'(?:合作方|客户|客戶|供应商|供應商|第三方|分析师|分析師|媒体|媒體|报道|報道).*(?:称|稱|表示|指出|认为|認為)',text)
                    and not re.search(r'[“”\"「」『』]|引用|摘录|摘錄|转载|轉載|子公司|附属|附屬',text)):
                for frame in frames:
                    if (frame.get('role_reason')=='ACTION_REFERENT_UNRESOLVED'
                            and frame.get('reference') in {'本公司','本集团','本集團'}
                            and frame['context_start']==frame['clause_start']):
                        clause=text[frame['clause_start']:frame['clause_end']]
                        subject=_REFERENCE.match(clause)
                        frame.update(symbol=symbol,role_reason=None,subject_resolution='DOCUMENT_BOUND_FIRST_PERSON',
                            subject_start=frame['clause_start']+subject.start(1),
                            subject_end=frame['clause_start']+subject.end(1))
            for frame in frames:
                if frame['symbol'] not in {symbol,None}:continue
                if frame['symbol'] is None and not any(code==symbol for _,_,code in spans):continue
                matched=True
                start,end=frame['subject_start'],frame['subject_end']
                left,right=frame['start'],frame['end']
                local=text[left:right].rstrip('，,、 与和及')
                right=left+len(local)
                context_start=offset+frame['context_start'];context_end=offset+frame['context_end']
                clause=text[frame['clause_start']:frame['clause_end']]
                action=text[frame['action_start']:right]
                def scoped_reject(reason, disposition='RESEARCH_REVIEW_REQUIRED', polarity='UNRESOLVED'):
                    reject(reason,field,local,offset+left,offset+right)
                    rejected[-1].update(disposition=disposition,polarity=polarity,
                        action_subject=frame['symbol'],action_quote=action,
                        action_start=offset+frame['action_start'],action_end=offset+right,
                        subject_quote=text[start:end],subject_start=offset+start,subject_end=offset+end,
                        subject_resolution=frame['subject_resolution'],
                        context_quote=body[context_start:context_end],context_start=context_start,context_end=context_end,
                        parser_revision=PARSER_REVISION)
                if frame['role_reason']:
                    scoped_reject(frame['role_reason'],polarity=frame.get('forced_polarity','UNRESOLVED'));continue
                if SPECULATION_RE.search(clause):
                    scoped_reject('SPECULATIVE_ASSOCIATION_ONLY');continue
                if frame['subject_resolution']=='EXPLICIT_SUBJECT':
                    a=start-frame['clause_start'];b=end-frame['clause_start']
                    if _publisher(clause,a,b,alias,str(value.get('title') or '')):
                        scoped_reject('PUBLISHER_OR_ANALYST_NOT_SUBJECT','MATERIAL_INDEX_ONLY','NOT_A_CLAIM');continue
                    role_issue=_context_role_issue(clause,a,b)
                    if role_issue:
                        scoped_reject(role_issue);continue
                issue=_paired_code_issue(text,end,symbol,identity_row or {})
                if issue:
                    scoped_reject(issue);continue
                if _report_locator(local) or _report_locator(clause):
                    scoped_reject('REPORT_LOCATOR_WITHOUT_ASSERTED_BUSINESS_FACT','MATERIAL_INDEX_ONLY','NOT_A_CLAIM');continue
                # Negation and uncertainty are scoped to this atomic clause,
                # never to subsequent independent/contrast clauses.
                polarity=_polarity(clause)
                if polarity!='AFFIRMED':
                    disposition='CLARIFICATION_EVIDENCE' if polarity in {'NEGATED','NOT_YET'} else 'RESEARCH_REVIEW_REQUIRED'
                    scoped_reject('ACTION_'+polarity,disposition,polarity);continue
                if (re.search(r'大会|会议|纪要|反馈',local) and
                        not re.search(r'营收|收入|净利|保费|订单|需求|销量|临床|回购|交付|产能|量产|产品',local)):
                    scoped_reject('REPORT_OR_MEETING_LOCATOR_NOT_BUSINESS_CLAIM','MATERIAL_INDEX_ONLY','NOT_A_CLAIM');continue
                if re.search(r'(?:公告|报告)(?:整理|摘要|汇总)\s*$',local) and not re.search(r'已完成|已实施|已回购|[0-9].{0,8}(?:股|万元|亿元|%)',local):
                    scoped_reject('DOCUMENT_SUMMARY_HEADING_NOT_EVENT','MATERIAL_INDEX_ONLY','NOT_A_CLAIM');continue
                if not ACTION_RE.search(action):
                    scoped_reject('NO_SUBJECT_LOCAL_ACTION_OR_RESEARCH_CLAIM');continue
                if _EMBEDDED_SUBJECT.match(action):
                    scoped_reject('EMBEDDED_COMPANY_ACTION_SUBJECT_UNRESOLVED');continue
                if FILE_RE.search(local):
                    scoped_reject('FILE_LOCATOR_OR_BODY_MISSING','MATERIAL_INDEX_ONLY','NOT_A_CLAIM');continue
                # Event classification sees the action, never the issuer name
                # (e.g. an insurer cooperating is not an insurance metric).
                kind=event_type(action)
                role='RESEARCH_SUBJECT'
                official=(value.get('body_parsed') is True and value.get('event_relevant') is True
                    and value.get('source_kind')=='HKEX_OFFICIAL_ANNOUNCEMENT')
                if official:role='ISSUER_EVENT'
                claim='REPORTED_CLAIM' if value.get('claim_type')=='RESEARCH_OPINION' else 'SOURCE_STATEMENT'
                if re.search(r'預計|預期|認為|擬|预计|预期|期待|认为|有望|看好|推荐|可能|或将|拟|潜在|potential|expected|proposed',text[frame['clause_start']:right],re.I):
                    claim='EXPECTATION_OR_PROPOSAL'
                    context_start=offset+frame['clause_start']
                if re.search(r'传闻|消息称|据称',clause):claim='UNCONFIRMED_REPORT'
                support_start=offset+left;support_end=offset+right
                declared_date=re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',local)
                event_date_claim=('%s%02d%02d'%(declared_date[1],int(declared_date[2]),int(declared_date[3]))) if declared_date else None
                p=dict(evidence_id=eid,proposition_id=digest([PARSER_REVISION,eid,symbol,field,support_start,support_end,local]),
                    symbol=symbol,name=name,quote=local,source_field=field,start=support_start,end=support_end,
                    subject_role=role,event_type=kind,claim_status=claim,polarity=polarity,action_subject=symbol,
                    action_quote=action,action_start=offset+frame['action_start'],action_end=support_end,
                    subject_quote=text[start:end],subject_start=offset+start,subject_end=offset+end,
                    subject_resolution=frame['subject_resolution'],context_quote=body[context_start:context_end],
                    context_start=context_start,context_end=context_end,parser_revision=PARSER_REVISION,
                    theme=mechanism(action),event_date_claim=event_date_claim,
                    effect_scope='A_SHARE_CAPITAL_ACTION_NOT_H_SHARE_FLOW' if kind=='OWNERSHIP_CHANGE' and 'A股' in local else 'ISSUER_CLAIM_NOT_PRICE_CONFIRMATION',
                    semantic_version=SEMANTIC_VERSION)
                propositions.append(p)
        if not matched:
            # Official parser issuer association may use "the Company". It
            # is accepted only with the original official issuer binding, not
            # from any arbitrary paragraph saying "company".
            if (value.get('source_kind')=='HKEX_OFFICIAL_ANNOUNCEMENT' and value.get('body_parsed') is True
                    and value.get('event_relevant') is True and value.get('issuer_code')==symbol
                    and value.get('event_kind')=='REGULATORY_OPINION' and 'CHMP' in body.upper()):
                p=dict(evidence_id=eid,proposition_id=digest([eid,symbol,body]),symbol=symbol,name=name,
                    quote=body,source_field=field,start=0,end=len(body),subject_role='ISSUER_EVENT',
                    event_type='REGULATORY_OPINION',claim_status='SOURCE_STATEMENT',theme='REGULATORY_OPINION',
                    semantic_version=SEMANTIC_VERSION)
                propositions.append(p)
            else:reject('SUBJECT_NOT_IN_BODY',field,body)
    if is_mirror(value):
        propositions,selection_rejected=substantive_propositions(value,propositions)
        rejected.extend(selection_rejected)
    unique={p['proposition_id']:p for p in propositions}
    return dict(propositions=list(unique.values()),rejected=rejected)


def sanitize_cards(cards: Sequence[Mapping[str, Any]], *, names: Mapping[str,str] | None = None) -> tuple[list[dict],list[dict]]:
    catalogue=dict(names or {str(c.get('symbol')):str(c.get('name')) for c in cards if c.get('symbol') and c.get('name')})
    # Carry the originally encountered native subjects into a single-stock
    # recheck; otherwise a later plan pass could borrow a following peer clause.
    for card in cards:
        for code, name in (card.get('subject_scope') or {}).items():
            if canonical_symbol(code) == code and isinstance(name,str) and name.strip():
                catalogue.setdefault(code,name)
    accepted=[];rejections=[]
    for original in cards:
        row=deepcopy(dict(original));symbol=canonical_symbol(row.get('symbol'),row.get('market','HK'))
        if not symbol or not row.get('source_refs'):
            rejections.append(dict(evidence_id=evidence_id(row),symbol=row.get('symbol'),reason='IDENTITY_OR_SOURCE_REFS_MISSING',original_relation=row));continue
        result=assess(row,str(row.get('name') or symbol),symbol,names=catalogue,
            identity_row=row.get('identity_pair_basis') or {})
        rejections.extend(result['rejected'])
        if not result['propositions']:continue
        row['propositions']=result['propositions'];row['semantic_version']=SEMANTIC_VERSION
        body='\n'.join(text for _,text in prose_sources(row))
        row['subject_scope']={code:catalogue[code] for _,_,code in _spans(body,catalogue)}
        row['subject_role']=result['propositions'][0]['subject_role'];row['semantic_status']='ACCEPTED'
        row['relation_quote']='。'.join(p['quote'] for p in result['propositions'])
        row['evidence_quote']=row['relation_quote']
        row['themes']=sorted({p['theme'] for p in result['propositions'] if p.get('theme')})
        row['mapping_reason']=f"{row.get('name',symbol)}的原文命题：{row['relation_quote']}。来源陈述与已兑现事实分列；不推定港股通资格。"
        accepted.append(row)
    return accepted,rejections
