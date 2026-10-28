"""SIMULATED parity and bounded compiled-pattern reuse, not source admission."""
from __future__ import annotations
import cProfile
import random
import re
from copy import deepcopy
from datetime import datetime
import pytest
from v4.manager_research import workspace_semantics as semantics
from v4.manager_research import workspace_discovery as discovery
from v4.manager_research.workspace_plan import plan_context


def original_spans(text, names):
    # Exact original _spans algorithm, retained as comparison oracle.
    candidates=[]
    for symbol,name in names.items():
        alias=semantics.alias_of(name)
        if len(alias)<2:continue
        pattern=re.escape(alias)
        if alias.isascii():pattern=r'(?<![A-Za-z0-9])'+pattern+r'(?![A-Za-z0-9])'
        for found in re.finditer(pattern,text,re.I):
            candidates.append((found.start(),found.end(),symbol))
    out=[]
    for a,b,s in candidates:
        if any(c<=a and b<=d and (d-c>b-a or (a==c and b==d and s!=t)) for c,d,t in candidates):continue
        out.append((a,b,s))
    return sorted(set(out))


def test_repeated_catalogue_does_not_recompile_all_patterns():
    names={f'HK.{i:05d}':f'合成名称{i:05d}' for i in range(650)}
    re.purge()
    cache=getattr(semantics,'_cached_issuer_pattern',None)
    if cache: cache.cache_clear()
    p=cProfile.Profile();p.enable()
    semantics._spans('合成名称00600临床研究。',names)
    semantics._spans('合成名称00600否认合作。',names)
    p.disable()
    compilations=sum(e.callcount for e in p.getstats()
        if not isinstance(e.code,str) and e.code.co_name=='compile'
        and e.code.co_filename.replace('\\','/').endswith('/re/_compiler.py'))
    assert compilations<=len(names)+4, {'actual_compilations':compilations,'catalogue':len(names)}


@pytest.mark.parametrize('body',[
    '甲公司与乙公司合作开发药物，前者完成临床；后者尚未获批。',
    '周大福创建收购项目，周大福公告回购。',
    'Alpha.A宣布研发，XAlpha.AY不应匹配；alpha.a回购。',
    '重名公司发布消息，另一个重名公司不应消除歧义。',
    'AB公告、ABC公告与abcXYZ。',
    '海光芯正没有量产，示例制药关键临床节点需确认。',
    '大金重工首次覆盖予增持评级。',
    '示例制药-B公布临床研究，示例制药-R公告。',
    '公司+(A)完成订单，甲[乙]公告、甲*乙公告、甲\\乙公告。',
])
def test_span_coordinates_exactly_match_original(body):
    names={'HK.00001':'甲公司','HK.00002':'乙公司','HK.00003':'周大福',
        'HK.00004':'周大福创建','HK.00005':'Alpha.A','HK.00006':'重名公司-B',
        'HK.00007':'重名公司-W','HK.00008':'AB','HK.00009':'ABC',
        'HK.00010':'海光芯正','HK.00011':'示例制药-B','HK.00012':'大金重工',
        'HK.00013':'公司+(A)','HK.00014':'甲[乙]','HK.00015':'甲*乙','HK.00016':'甲\\乙'}
    assert semantics._spans(body,names)==original_spans(body,names)


def test_deterministic_unicode_and_overlap_parity():
    rng=random.Random(20260923)
    vocabulary=['甲公司','甲公司控股','示例制药-B','ALPHA','alphaX','A.B','公司(甲)',
                '甲[乙]','甲*乙','甲+乙','甲?乙','ßtest','İTEST','国药','公司-W','ÅBC']
    for _ in range(80):
        names={f'HK.{i:05d}':rng.choice(vocabulary) for i in range(18)}
        text='。'.join(rng.choices(vocabulary+['否认','研究','x','甲'],k=8))
        assert semantics._spans(text,names)==original_spans(text,names)


def test_full_projection_preserves_propositions_rejections_and_identity(monkeypatch):
    context=plan_context('20260922',now=datetime.fromisoformat('2026-09-22T08:40:00+08:00'))
    when=context['focus_window_start']
    names={'HK.00001':'甲制药-B','HK.00002':'乙制药','HK.00003':'周大福','HK.00004':'周大福创建'}
    master={code:{'code':code,'name':name} for code,name in names.items()}
    identity={'status':'OWNER_VERIFIED','source_date':context['market_session'],'artifact_sha256':'a'*64}
    bodies=['甲制药关键临床节点需确认。','甲制药否认与乙制药合作。','甲制药与乙制药签署药物合作，前者已完成临床。',
            '周大福创建公告收购，周大福宣布回购100万股。','甲制药研究报告.pdf','乙制药暂未获批，甲制药收入增长10%。']
    rows=[dict(material_id=str(i),title=body,source_row={'body':body},verification='OWNER_VERIFIED',
               source_refs=[{'payload_sha256':'b'*64}],published_at=when,available_at=when,retrieved_at=when,
               source_url='https://example.invalid/SIMULATED') for i,body in enumerate(bodies)]
    rejection_new=[]
    new=discovery.project_material_discovery(rows,master,identity,context,rejection_audit=rejection_new)
    with monkeypatch.context() as m:
        m.setattr(semantics,'_spans',original_spans)
        rejection_old=[]
        old=discovery.project_material_discovery(rows,master,identity,context,rejection_audit=rejection_old)
    assert new==old and rejection_new==rejection_old
    assert rejection_new, 'must exercise rejection preservation'


def test_compiled_pattern_cache_has_entry_and_key_length_bounds():
    cache=semantics._cached_issuer_pattern
    cache.cache_clear()
    for i in range(4100): semantics._spans('',{'HK.00001':f'界限{i:05d}'})
    assert cache.cache_info().maxsize==4096 and cache.cache_info().currsize==4096
    before=cache.cache_info()
    long_name='长'*600
    assert semantics._spans(long_name,{'HK.00001':long_name})==[(0,600,'HK.00001')]
    after=cache.cache_info()
    assert before==after, 'oversized regex must not enter the cache'
    cache.cache_clear()


def test_master_name_change_and_duplicate_alias_do_not_reuse_entity_decisions():
    assert semantics._spans('甲公司',{'HK.00001':'甲公司'})==[(0,3,'HK.00001')]
    assert semantics._spans('甲公司',{'HK.00001':'乙公司'})==[]
    assert semantics._spans('甲公司',{'HK.00001':'甲公司','HK.00002':'甲公司'})==[]
