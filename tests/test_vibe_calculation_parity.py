"""Actual frozen source calculations on fixed raw rows, with effect boundaries isolated.

The reference harness extracts selected functions by AST to avoid executing the
legacy package initializer/HOME/socket effects. It does NOT replace V4's graph,
functions or IO. Counts distinguish fixture raw requests from SDK-internal HTTP.
"""
from __future__ import annotations
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import pandas as pd
import pytest

from test_vibe_data_owner import DATE,RAW_ZT,make_owner,RawTransport


def reference_root():
    root=Path(__file__).resolve().parents[2]
    a=root/'vibe_reference/duanxian'
    if not a.exists():a=root/'input/vibe_reference/duanxian'
    assert a.is_dir(),'frozen reference files are required, not downloaded substitutes'
    return a


def functions(module,names,extra=None):
    tree=ast.parse((reference_root()/(module+'.py')).read_text())
    chosen=[deepcopy(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert {n.name for n in chosen}==set(names)
    # Only the original raw SDK import is an effect seam in fetch_zt_pool.
    for n in chosen:
        n.body=[x for x in n.body if not (isinstance(x,ast.Import) and any(a.name=='akshare' for a in x.names))]
    ns={'Optional':Optional,'pd':pd,**(extra or {})}
    exec(compile(ast.fix_missing_locations(ast.Module(body=chosen,type_ignores=[])),str(reference_root()/(module+'.py')),'exec'),ns)
    return ns


def test_original_pool_and_sentiment_outputs_equal_actual_owned_code(tmp_path):
    from domains.research_review_generation.data_core import data,fetchers
    old_transport=RawTransport()
    ak=SimpleNamespace(**{n:(lambda n=n,**kw:old_transport.ak(n,**kw)) for n in
                         ('stock_zt_pool_em','stock_zt_pool_zbgc_em','stock_zt_pool_dtgc_em')})
    f=functions('fetchers',{'fetch_zt_pool'},{'ak':ak})['fetch_zt_pool']
    old=functions('data',{'_ymd','_degrade_msg','_degrade','get_sentiment_data'},
                  {'dr':SimpleNamespace(fetch_zt_pool=f)})
    owner,transport=make_owner(tmp_path)
    assert old['get_sentiment_data'](DATE)==data.get_sentiment_data(DATE,ctx=owner)
    old_pool=f('20260911');new_pool=fetchers.fetch_zt_pool('20260911',ctx=owner)
    pd.testing.assert_frame_equal(old_pool.pop('zt'),new_pool.pop('zt'))
    assert old_pool==new_pool
    assert sum(transport.calls.values())==3
    assert sum(old_transport.calls.values())==6  # two independent legacy facade calls


@pytest.mark.parametrize('code,name', [('000001','测试'),('300001','ST测试'),('688001','测试'),('920001','测试'),('600001','ST测试')])
def test_original_board_and_price_limit_rules_unchanged(code,name):
    from domains.research_review_generation.data_core import market_facts
    old=functions('market_facts',{'board_of','limit_pct','is_limit_up'},
                  {'_LIMIT_PCT':{'主板ST':5.,'北交所':30.,'20cm':20.,'20cm(ST)':20.,'10cm':10.}})
    assert old['board_of'](code,name)==market_facts.board_of(code,name)
    assert old['limit_pct'](code,name)==market_facts.limit_pct(code,name)
    for ret in (-10,0,4.8,9.9,19.8,29.9):
        assert old['is_limit_up'](ret,code,name)==market_facts.is_limit_up(ret,code,name)


def test_original_seal_quality_calculation_equal_from_fixed_raw(tmp_path):
    from domains.research_review_generation.data_core import market_facts
    owner,_=make_owner(tmp_path)
    pools=market_facts.pools(DATE,ctx=owner)
    old=functions('market_facts',{'_hhmmss','seal_quality'}, {'pools':lambda d:deepcopy(pools)})
    assert old['seal_quality'](DATE)==market_facts.seal_quality(DATE,ctx=owner)


def test_pure_and_context_only_calculation_ast_parity():
    """The function list is measured, and includes all seven original modules."""
    from domains.research_review_generation import data_core
    dst=Path(data_core.__file__).parent
    class StripOwner(ast.NodeTransformer):
        def visit_FunctionDef(self,node):
            node=self.generic_visit(node)
            pairs=[(a,d) for a,d in zip(node.args.kwonlyargs,node.args.kw_defaults) if a.arg!='ctx']
            node.args.kwonlyargs=[a for a,_ in pairs];node.args.kw_defaults=[d for _,d in pairs]
            return node
        def visit_Call(self,node):
            node=self.generic_visit(node)
            node.keywords=[k for k in node.keywords if not (k.arg=='ctx' and isinstance(k.value,ast.Name) and k.value.id=='ctx')]
            return node
    result={}
    for name in ('data','market_facts','emotion_metrics','breadth','stats_context','theme_tree','trade_calendar'):
        old={n.name:n for n in ast.parse((reference_root()/(name+'.py')).read_text()).body if isinstance(n,ast.FunctionDef)}
        new={n.name:n for n in ast.parse((dst/(name+'.py')).read_text()).body if isinstance(n,ast.FunctionDef)}
        same=[k for k in old.keys()&new.keys() if ast.dump(old[k],include_attributes=False)==ast.dump(StripOwner().visit(deepcopy(new[k])),include_attributes=False)]
        result[name]=same
    assert all(result.values())
    assert {'get_sentiment_data','get_emotion_metrics','get_market_facts','get_capital_data','get_macro_sector_data','get_theme_reasons','get_dragon_tiger_data'}<=set(result['data'])
    assert {'seal_quality','loss_effect','feedback_matrix','theme_structure','event_ledger','by_board'}<=set(result['market_facts'])
    assert sum(map(len,result.values()))>=60
