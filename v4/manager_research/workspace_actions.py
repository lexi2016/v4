"""Issuer-local research questions. Every action points to a retained proposition.

These are conditions to review, not predictions, positions or executable orders.
"""
from __future__ import annotations
from typing import Mapping, Any
import re
from .workspace_semantics import sanitize_cards
from .workspace_projection import digest

# Domain-specific review questions; no issuer names, tickers or market winners.
TEMPLATES = {
    'OWNERSHIP_CHANGE': (
        '核对本股交易主体、股份类别、数量及实际完成状态；计划不等于已完成。',
        '区分集团内部转让、拟议回购与实际市场承接。',
        '若同一交易被撤销、未完成或股份类别不符，撤销该项依据。'),
    'REGULATORY_OPINION': (
        '核对本品种CHMP意见的范围、适应症及后续欧洲委员会决定；积极意见不等于最终批准。',
        '监管后续决定、商业化安排与或有里程碑仍是独立事项，不按现金到账计。',
        '若后续决定否定或改变原意见范围、适应症或原公告被更正，撤销对应判断。'),
    'CLINICAL_MILESTONE': (
        '核对本公司所述临床阶段、试验终点与正式披露；区分研发预期与完成结果。',
        '本条临床进度可能延后，不能由同行进展推定本公司兑现。',
        '若本条对应的试验节点、终点结果被否定或更正，撤销该项依据。'),
    'LICENSING': (
        '核对本公司对应许可合同、授权范围、签约/完成状态；分列首付款和或有里程碑。',
        '合同上限或附条件金额不等于已到账现金或当期收入。',
        '若本条许可交易被撤销、对应条件未满足或原合同依据被更正，撤销该项依据。'),
    'INSURANCE_OPERATING': (
        '核对本股所述保险经营指标、统计期间及正式披露，比较同口径变化。',
        '保费、利润、投资收益及新业务价值并非同一指标；未披露的指标不代填。',
        '若本条经营指标被下修、更正或报告期不一致，撤销对应经营判断。'),
    'OPERATING_TREND': (
        '核对本公司所述经营指标、订单或需求的报告期与兑现情况，分清预测和披露值。',
        '经营预期或渠道调研不等于已实现收入、利润；需验证同口径基础。',
        '若本条对应指标、订单或需求判断被下修、取消或更正，撤销该项依据。'),
    'TECH_OR_PARTNERSHIP': (
        '核对本公司的直接技术/合作角色和本条所述交付节点，不用同行热度替代。',
        '技术展示或合作意向不等于订单收入；转载数不构成独立验证。',
        '若本条直接业务关联无法核实或对应交付/合作撤销，撤销该项依据。'),
    'DIGITAL_ASSET_EXPOSURE': (
        '核对本股当前业务/资产敞口及披露时点，再与同一窗口、同币种的币价变化配对。',
        '历史持仓不能当成当前持仓；缺同窗口币价或敞口证据时不建立方向性交易判断。',
        '若当前敞口不成立、被更正或窗口不匹配，撤销虚拟币向本股的映射。'),
    'POLICY_INFERENCE': (
        '核对报道与最终规则状态，以及本公司业务对相关条款的具体敞口。',
        '拟议规则及消息人士报道不等于规则已生效，也不是本公司新增合同。',
        '若最终条款改变适用范围或本公司敞口不成立，撤销该项产业推断。'),
    'ISSUER_RESEARCH': (
        '核对本条个股命题、原始披露和后续可验证节点。',
        '当前属于研究陈述，不以材料收录或转载证明事实已经兑现。',
        '若本条命题被更正、否认或不适用于该股份，撤销该项依据。'),
}



def proposition_conditions(prop: Mapping[str, Any]) -> tuple[str, str, str]:
    """Choose questions from the already AFFIRMED issuer action, not its name.

    These questions name missing observations; they never invent a business
    outcome, numerical trigger, filing deadline or a second issuer relationship.
    """
    text = str(prop.get('action_quote') or '')
    kind = str(prop.get('event_type') or 'ISSUER_RESEARCH')
    if re.search(r'MLCC', text, re.I) and re.search(r'上调|涨价|调价', text):
        return (
            '等待本条MLCC涨价通知的产品范围、执行日期与代理商执行反馈；目前未给出可核验涨幅。',
            '提价通知不等于已实现收入；只对同批产品核对实际成交价、订单和客户接受情况。',
            '若同一价格通知被撤回、代理商未执行或实际成交价未提高，撤销本条涨价依据。')
    if re.search(r'Q[1-4]|季度', text, re.I) and re.search(r'预计|预期|有望|看到|利润|增长', text):
        return (
            '等待对应报告期的正式业绩或预告，核对预测数值、利润/收入指标及环比基数；研究预测不当作已实现。',
            '对本条预测单独核验；口径、报告期或基数未明确前，不把预测增长用作业绩兑现信号。',
            '若同报告期实际披露低于该预测、预测被下修或比较基数错误，撤销本条业绩预期依据。')
    if re.search(r'mSAP', text, re.I) and re.search(r'订单|产能', text):
        return (
            '等待mSAP车间订单对应的产品、交付周期与产能利用率披露；订单饱满尚缺数量和执行周期。',
            '车间订单与全公司收入分开核对；不借其他事件的光模块产能或客户信息补本条订单证据。',
            '若本车间订单取消、交付延迟或利用率下修，撤销本条订单饱满依据。')
    if re.search(r'四大新品|新品', text) and re.search(r'平台|催化', text):
        return (
            '等待新品名称、对应平台导入/发布节点及客户验证；原文只称四大新品，不能代填具体产品或日期。',
            '平台催化属于预期；未见导入和交付证据前，不推定新品已放量。',
            '若对应平台导入或新品验证推迟、取消，或原研究命题被更正，撤销本条新品催化依据。')
    if kind == 'CLINICAL_MILESTONE':
        return (
            '等待管线名称、临床阶段/试验终点及启动或结果公告；同句BD另核合同与临床节点的对应关系。',
            '临床启动与成功结果分开；BD标题未提供授权地域、管线及款项结构，不能视为已到账收入。',
            '若本条管线试验延期、终点失败，或对应BD对临床推进的依据被否定，撤销本条临床/BD判断。')
    if kind == 'TECH_OR_PARTNERSHIP' and re.search(r'大模型|模型厂商', text):
        return (
            '等待合作方名称、双方合作范围与可验证交付节点；原文未给出合作方名称及交付日期。',
            '模型合作与商业订单分开；缺直接合同、验收或付款证据时不认定形成收入。',
            '若本条模型合作被否认、取消或约定交付未达成，撤销本条合作依据。')
    if re.search(r'大单品|新品牌', text) and re.search(r'升级|上市', text):
        return (
            '等待升级产品与新品牌的名称、上市渠道/日期和动销反馈；不把品牌上市直接当成销量增长。',
            '本条缺产品升级细节与销售验证；与其他公司的医药或模型合作事件无关。',
            '若本条产品升级/品牌上市取消、延迟或动销不支持原判断，撤销本条品牌催化依据。')
    if re.search(r'AIDD|体内验证', text, re.I):
        return (
            '等待双多抗/ADC或AIDD体内验证对应的客户、付费项目/订单与收入验证；需求爆发是报告判断，不等于已获订单。',
            '研究需求与本公司已签服务合同分开；缺服务范围、客户和收入确认口径时不认定兑现。',
            '若本条体内验证/分子服务需求判断被下修、对应订单取消或业务敞口不成立，撤销本条需求依据。')
    if re.search(r'潜在收入|potential revenue', text, re.I):
        return (
            '等待本条潜在收入测算对应的合同、订单数量和交付/确认期间；预测金额不是已实现收入。',
            '缺交易数量、单价或附条件条款时，无法重算本条潜在收入；不能拿其他订单标题补齐。',
            '若对应合同取消、测算基数被下修或收入确认范围不成立，撤销本条潜在收入依据。')
    if re.search(r'业绩补偿|补充协议', text):
        return (
            '等待本次补充协议的补偿触发条件、执行安排及生效/交割状态；条款简化不等于收购已完成。',
            '本条补偿义务与上市公司经营增长分开；需核具体条款变化是否改变保障范围。',
            '若同一补充协议撤销、未生效或补偿保障与原命题不符，撤销该项协议进展依据。')
    if re.search(r'集中采购|集采|招标', text):
        return (
            '等待本次招标范围、采购数量及中标/履约节点；采购方角色不等于取得销售订单。',
            '本次采购启动不等于已完成招标或形成收入，不能套用供应商的订单收益。',
            '若本次招标撤回、范围缩减或履约取消，撤销对应采购进度依据。')
    return TEMPLATES.get(kind, TEMPLATES['ISSUER_RESEARCH'])



def inference_conditions(link: Mapping[str, Any]) -> tuple[str, str, str]:
    """Questions about the admitted transmission mechanism, not a borrowed deal."""
    theme = str(link.get('theme') or '')
    scope = (link.get('mapping_admission') or {}).get('issuer_scope')
    if theme == 'PHARMA_CROSS_BORDER_POLICY':
        return TEMPLATES['POLICY_INFERENCE']
    if theme == 'PHARMA_INDUSTRY_PLAN' and scope == 'DRUG_RND_SERVICES':
        return (
            '等待规划AI4S/生命科学工具的适用条款与本股抗体发现/AIDD体内验证业务核对，再看对应付费项目、订单及收入。' +
            ('窗口前规划仅为历史背景，不是本期新催化。' if link.get('window_status')=='BACKGROUND_REFERENCE' else '政策传导尚未证明兑现。'),
            '这只是研发工具需求的产业推断；原报告观点、政策原文与本股业务须分别核验，不能认定政策收益或公司订单已兑现。',
            '若规划条款不适用于该类研发工具、业务敞口不成立或需求传导被否定，撤销本条政策适用推断。')
    if theme == 'PHARMA_INDUSTRY_PLAN':
        return (
            '等待规划中制造/装备支持条款与本股生产环节的适用证明，再核对应需求；不把规划发布当作已中标。',
            '具体政策工具、支持对象及本股受益方式未落实前，仍是制造需求研究而非公司订单。',
            '若条款适用范围排除本股生产环节、业务证据被更正或需求传导不成立，撤销该制造需求推断。')
    if theme == 'AI_DRUG_RND':
        return (
            '等待行业AI药研投入是否转化为本股已披露的抗体发现、体内验证或管线业务需求，核具体项目及付费证据；不是与主题公司签约。',
            '行业融资、同行技术进展和本股收入分开；缺本股对应业务需求证据时，不认定产业催化已兑现。',
            '若行业事件被否认、本股药研业务范围不匹配或需求传导不成立，撤销本条AI药研产业推断。')
    return (
        '等待主题所述变化是否传导到本股原文业务环节，以该环节的需求、订单或经营披露验证；不要求本股与主题公司存在合作。',
        '两段真实原文只能支持产业关联研究，不能替代本公司的直接合同、收入或同窗口行情。',
        '若主题事件被更正、本股具体业务敞口不成立或传导机制被否定，撤销本条产业推断。')

def proposition_actions(stock: Mapping[str, Any]) -> dict:
    clean,rejections=sanitize_cards(stock.get('evidence',[]))
    # The plan's outer stock is also a binding boundary, not merely a UI label.
    own=[]
    for row in clean:
        if row.get('symbol')!=stock.get('symbol'):
            rejections.append(dict(reason='ACTION_STOCK_SUBJECT_MISMATCH',symbol=stock.get('symbol'),
                evidence_symbol=row.get('symbol'),evidence_id=row.get('card_id') or row.get('material_id'),
                original_relation=row))
        else:own.append(row)
    clean=own
    actions=[];rules=[];seen=set()
    for row in clean:
        for prop in row['propositions']:
            key=(prop['symbol'],prop['quote'],prop['event_type'])
            if key in seen:continue
            seen.add(key)
            eid=prop['evidence_id'];pid=prop['proposition_id'];kind=prop['event_type']
            confirm,risk,invalid=proposition_conditions(prop)
            support=dict(evidence_id=eid,proposition_id=pid,symbol=prop['symbol'],quote=prop['quote'],
                         source_field=prop['source_field'],start=prop['start'],end=prop['end'])
            # Keep the subject/negation decision and its original context with
            # every review item. The display quote stays proposition-local.
            for key in ('action_subject','polarity','action_quote','action_start','action_end',
                        'subject_quote','subject_start','subject_end','subject_resolution',
                        'context_quote','context_start','context_end','parser_revision'):
                if key in prop:support[key]=prop[key]
            texts={
                'WATCH':f"{stock.get('name',stock['symbol'])}：原文「{prop['quote']}」（{prop['claim_status']}）；{confirm}",
                'WAIT':f"本条事实或适用范围未核实前保持观察；{risk}",
                'NO_CHASE':'即使本条依据成立，未验证同口径行情承接或高开远离可靠参考位时不追；不强制等待必然出现回踩。',
                'INVALIDATE':invalid,
            }
            for action_type,text in texts.items():
                actions.append(dict(action_id=digest([pid,action_type]),type=action_type,text=text,rule_id=kind,
                    evidence_ids=[eid],proposition_ids=[pid],supporting_quotes=[support],
                    assertion_type='RESEARCH_CONDITION_NOT_OBSERVED_FACT',orders_sent=False))
            rules.append(dict(rule_id=kind,evidence_ids=[eid],proposition_ids=[pid],supporting_quotes=[support]))
    return dict(actions=actions,evidence_rules=rules,clean_evidence=clean,rejected_relations=rejections)
