import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
import time

import pytest


def fetcher():
    path=Path(__file__).parents[1]/'stage_center/hk_stage8/rtdata.py'
    tree=ast.parse(path.read_text());names={'_fetch_hk_stage8_rtdata','_rt_data_records'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    namespace=dict(Any=Any,Callable=Callable,Mapping=Mapping,Sequence=Sequence,time=time,
        _STAGE8_RT_DATA_BATCH_SIZE=30,_canonical_snapshot_codes=lambda codes:tuple(sorted(set(codes))),_canonical_hk_code=lambda code:code)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['_fetch_hk_stage8_rtdata']


def test_short_subscription_cleanup_never_waits_or_drops_success_and_keeps_failed_batch_message():
    class Context:
        def __init__(self):self.batches=[];self.closed=False
        def subscribe(self,batch,*args,**kwargs):
            self.batches.append(batch)
            return (0,None) if len(self.batches)<4 else (-1,'original provider fixture detail')
        def get_rt_data(self,code):return 0,[{'code':code}]
        def unsubscribe(self,*args):pytest.fail('invalid under60s unsubscribe')
        def close(self):self.closed=True
    ctx=Context();codes=[f'HK.{i:05d}' for i in range(1,101)]
    result=fetcher()(codes,quote_context_factory=lambda **k:ctx,futu_module=SimpleNamespace(RET_OK=0),clock=lambda:0)
    assert result['completed_code_count']==90 and result['missing_codes']==tuple(codes[90:])
    assert result['errors']==('HK_STAGE8_RTDATA_SUBSCRIBE_FAILED:batch=4',)
    diagnostic=next(d for d in result['provider_diagnostics'] if d.get('batch')==4 and d['operation']=='subscribe')
    assert diagnostic['return_code']=='-1' and diagnostic['message']=='original provider fixture detail'
    assert len([d for d in result['provider_diagnostics'] if d.get('status')=='DEFERRED_TO_CONTEXT_CLOSE'])==3
    assert ctx.closed and all(len(b)<=30 for b in ctx.batches)


def test_mature_subscription_uses_original_unsubscribe_and_retains_real_failure():
    clock=[0]
    class Context:
        def subscribe(self,*a,**k):return 0,None
        def get_rt_data(self,code):clock[0]=61;return 0,[{'code':code}]
        def unsubscribe(self,*args):return -1,'cleanup original message'
        def close(self):pass
    result=fetcher()(['HK.09903'],quote_context_factory=lambda **k:Context(),futu_module=SimpleNamespace(RET_OK=0),clock=lambda:clock[0])
    assert result['completed_code_count']==1
    assert result['cleanup_warnings']==('HK_STAGE8_RTDATA_UNSUBSCRIBE_FAILED:batch=1',)
    assert any('cleanup original message' in d.get('return_value','') for d in result['provider_diagnostics'])


def test_cleanup_does_not_suppress_base_exception_or_retry_get():
    events=[]
    class Context:
        def subscribe(self,*a,**k):return 0,None
        def get_rt_data(self,code):events.append('get');raise KeyboardInterrupt()
        def close(self):events.append('close')
    with pytest.raises(KeyboardInterrupt):
        fetcher()(['HK.09903'],quote_context_factory=lambda **k:Context(),futu_module=SimpleNamespace(RET_OK=0),clock=lambda:0)
    assert events==['get','close']
