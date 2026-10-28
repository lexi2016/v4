"""Real GET pure-projection regression; does not stand in for service tests.
Run with MANAGER_UX_REAL_INPUT pointing at the supplied current_workspace.json.
"""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import types
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_decision_ux_real_source'
namespace = types.ModuleType(PACKAGE)
namespace.__path__ = [str(ROOT / 'v4/manager_research')]
sys.modules[PACKAGE] = namespace
modules = {name: importlib.import_module(f'{PACKAGE}.workspace_{name}')
           for name in ('projection', 'semantics', 'actions', 'plan', 'briefing')}

@pytest.fixture(scope='module')
def actual():
    path = os.environ.get('MANAGER_UX_REAL_INPUT')
    if not path:
        pytest.skip('Supply MANAGER_UX_REAL_INPUT: no substitute input is fabricated')
    return json.loads(Path(path).read_text())

@pytest.fixture(scope='module')
def projected(actual):
    value = copy.deepcopy(actual)
    for s in value['stocks']:
        s['plan'] = modules['plan'].stock_plan(s, value['plan_context'])
    value.update(modules['briefing'].build_briefing(value['materials'], value['stocks'], value['plan_context']))
    return value

def stock(value, symbol):
    return next(s for s in value['stocks'] if s['symbol'] == symbol)

def action_for(value, symbol, quote_part, kind='WATCH'):
    return next(a for a in stock(value,symbol)['plan']['actions']
                if a['type']==kind and a['assertion_type']!='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT'
                and any(quote_part in q['quote'] for q in a['supporting_quotes']))

def test_real_mlcc_price_and_profit_outlook_have_different_nodes(projected):
    price = action_for(projected, 'HK.06951','MLCC')
    outlook = action_for(projected, 'HK.06951','Q3利润')
    assert '执行日期' in price['text'] and '涨价' in price['text']
    assert '报告期' in outlook['text'] and '预测' in outlook['text']
    assert price['proposition_ids'] != outlook['proposition_ids']
    assert '价格通知' in action_for(projected,'HK.06951','MLCC','INVALIDATE')['text']

def test_real_insilico_clinical_and_model_cooperation_remain_local(projected):
    clinical=action_for(projected,'HK.03696','关键临床')
    model=action_for(projected,'HK.03696','基础大模型')
    assert '管线名称' in clinical['text'] and '临床' in clinical['text']
    assert '合作方名称' in model['text'] and '交付节点' in model['text']
    assert '临床' not in model['text'] and '模型' not in clinical['text']
    assert clinical['proposition_ids'] != model['proposition_ids']

def test_real_four_company_reasons_are_not_stage_membership(projected):
    for symbol, expected in [('HK.01989','Q3'),('HK.02476','mSAP'),('HK.06809','四大新品'),('HK.06951','MLCC')]:
        assert expected in stock(projected,symbol)['why_watch'][0]
        assert '进入原Stage' not in stock(projected,symbol)['why_watch'][0]

def test_hengrui_generic_name_and_old_cash_do_not_admit_policy(projected):
    s=stock(projected,'HK.01276')
    assert not any(m['theme']=='PHARMA_INDUSTRY_PLAN' for m in s['material_relations'])
    assert s['is_focus'] is False
    t=next(t for t in projected['themes'] if t['theme']=='PHARMA_INDUSTRY_PLAN')
    gap=next(g for g in t['company_mapping_gaps'] if g['symbol']=='HK.01276')
    assert gap['status']=='CANNOT_CONFIRM' and gap['evidence_ids']
    assert '药物' in gap['missing'] or '业务' in gap['missing']

def test_cross_border_gaps_are_company_specific_and_not_fake_mapping(projected):
    t=next(t for t in projected['themes'] if t['theme']=='PHARMA_CROSS_BORDER_POLICY')
    assert not t['mapped_symbols']
    gaps={g['symbol']:g for g in t['company_mapping_gaps']}
    assert 'HK.03696' in gaps and 'HK.02315' in gaps
    assert gaps['HK.03696']['missing'] != gaps['HK.02315']['missing']
    assert all(g['owner'] and g['evidence_ids'] for g in gaps.values())

def test_real_pharma_plan_background_link_uses_aidd_business_not_company_name(projected):
    t=next(t for t in projected['themes'] if t['theme']=='PHARMA_INDUSTRY_PLAN')
    m=next(m for m in t['mappings'] if m['symbol']=='HK.02315')
    assert m['window_status']=='BACKGROUND_REFERENCE'
    assert m['mapping_admission']['status']=='PASS'
    assert 'AIDD' in m['issuer_quote'] and 'AI4S' in m['theme_quote']
    assert len(m['supporting_quotes'])==2

def test_future_availability_and_pre_focus_material_are_not_current(actual):
    ctx=actual['plan_context']
    # SYNTHETIC temporal negatives, not new real materials.
    assert not modules['briefing']._recent({'published_at':'2026-09-21T10:00:00+08:00',
        'available_at':'2026-09-22T10:00:00+08:00'}, ctx)
    assert not modules['briefing']._recent({'published_at':'2026-09-18T11:16:31+08:00'},ctx)

def test_stage_safety_quotes_and_original_input_remain_unchanged(actual,projected):
    for s in projected['stocks']:
        old=stock(actual,s['symbol'])
        assert s['stage_observation']==old['stage_observation']
        assert s['evidence']==old['evidence']
        assert s['plan']['trigger_price'] is None and s['plan']['invalidation_price'] is None
        assert s['plan']['RESEARCH_ONLY'] is True and s['plan']['orders_sent'] is False
        assert s['plan']['production_allowed'] is False and s['plan']['buy_gate_updated'] is False
    assert projected['plan_context']==actual['plan_context']
    assert projected['market_screen']==actual['market_screen']

def test_other_real_business_nodes_are_not_generic_renamed_templates(projected):
    checks=[('HK.02145','大单品','品牌'),('HK.02315','AIDD','体内验证'),
            ('HK.02338','4.41','潜在收入'),('HK.09611','业绩补偿','补偿')]
    for symbol,quote,node in checks:
        a=action_for(projected,symbol,quote)
        assert node in a['text'].split('）；')[-1]
        assert '核对本公司所述经营指标、订单或需求的报告期与兑现情况' not in a['text']

def test_future_collected_policy_never_appears_as_background_mapping(actual):
    # SYNTHETIC acquired-after-cutoff copy of a real policy article.
    material=next(m for m in actual['materials'] if '医药工业' in str(m) and '十五五' in str(m))
    material=copy.deepcopy(material)
    material['collected_at']='2026-09-22T20:00:00+08:00'
    assert modules['briefing']._theme_fragments(material,actual['plan_context']) == []

def test_real_policy_mapping_uses_policy_business_conditions_not_partnership(projected):
    s=stock(projected,'HK.02315')
    a=next(a for a in s['plan']['actions'] if a['rule_id']=='INDUSTRY_INFERENCE_PHARMA_INDUSTRY_PLAN' and a['type']=='WATCH')
    condition=a['text'].split('不宣称本股与主题公司存在新合同或合作。')[-1]
    assert 'AI4S' in condition and '体内验证' in condition
    assert '合作角色' not in condition and '交付节点' not in condition
    b=next(a for a in s['plan']['actions'] if a['rule_id']=='INDUSTRY_INFERENCE_PHARMA_INDUSTRY_PLAN' and a['type']=='INVALIDATE')
    assert '适用' in b['text'] and b['proposition_ids']==a['proposition_ids']

def test_future_company_evidence_is_not_used_even_in_diagnostic_gap(actual):
    s=copy.deepcopy(stock(actual,'HK.03696'))
    for e in s['evidence']: e['available_at']='2026-09-22T10:00:00+08:00'
    assert modules['briefing']._company_mapping_gaps('PHARMA_CROSS_BORDER_POLICY',[s],[],actual['plan_context'])==[]
