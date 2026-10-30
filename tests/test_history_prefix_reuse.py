"""C6 source-only synthetic series. No real prices, labels or bootstrap run."""
import copy
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/history_prefix_reuse_source'
FIELDS=('B1','B2','B3','突破','突破接十字星','零上二金','零下二金','一级买点','二级买点')


@pytest.fixture(scope='module')
def producer(tmp_path_factory):
    v=json.loads((HERE/'OVERLAY_INVENTORY.json').read_text());name='ops/research_panel_daily_product.py'
    raw=subprocess.run(['git','show',v['C4_commit']+':'+name],cwd=ROOT,check=True,capture_output=True).stdout
    temp=tmp_path_factory.mktemp('C6-composition');p=temp/name;p.parent.mkdir();p.write_bytes(raw)
    allpatch=(ROOT/v['C5_overlay_path']).read_bytes();assert hashlib.sha256(allpatch).hexdigest()==v['C5_overlay_sha256']
    text=allpatch.decode();start=text.index('--- a/'+name+'\n');end=text.find('\n--- a/',start+1);segment=text[start:] if end<0 else text[start:end+1]
    subprocess.run(['git','apply','-'],cwd=temp,input=segment.encode(),check=True,capture_output=True)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==v['C5_producer_sha256']
    subprocess.run(['git','apply','--check',str(HERE/'C6_OVERLAY.patch')],cwd=temp,check=True,capture_output=True)
    subprocess.run(['git','apply',str(HERE/'C6_OVERLAY.patch')],cwd=temp,check=True,capture_output=True)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==v['C6_producer_sha256']
    assert p.read_text().count('CACHE_ONLY_NO_RECOMPUTE')==2
    rule=(ROOT/'domains/research_daily_product.py').read_bytes();assert hashlib.sha256(rule).hexdigest()=='48cccee9eb4c77d2d09965a3e25354580278d14605e835d28833998a327c39e3'
    rule_path=temp/'domains/research_daily_product.py';rule_path.parent.mkdir();rule_path.write_bytes(rule)
    spec=importlib.util.spec_from_file_location('c6_synthetic_producer',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    yield module


def context(producer,tmp_path):
    config=json.loads((ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json').read_text())
    config={k:config[k] for k in ('formula','engine','tri_state_core','census')}
    config_path=tmp_path/'synthetic_config.json';config_path.write_text(json.dumps(config))
    engine=producer.module(config['engine'],'c6_unit_engine_'+tmp_path.name)
    core=producer.module(config['tri_state_core'],'c6_unit_core_'+tmp_path.name)
    days=[];day=datetime(2026,1,1)
    while len(days)<160:
        if day.weekday()<5:days.append(int(day.strftime('%Y%m%d')))
        day+=timedelta(days=1)
    bars=[];previous=Decimal('10');changes=['.012','-.008','.006','.072','-.025','.002','-.005']
    for i,date in enumerate(days):
        op=previous*(1+Decimal(i%3-1)/500);close=previous*(1+Decimal(changes[i%len(changes)]))
        bars.append(dict(trade_date=date,open=str(op),high=str(max(op,close)*Decimal('1.01')),low=str(min(op,close)*Decimal('.99')),close=str(close),vol=str(Decimal(3000 if i%7==3 else 1000)+(i%5)*100)));previous=close
    calls={'compute':0,'g4':[]};original=engine.compute
    def counted(*args,**kwargs):calls['compute']+=1;return original(*args,**kwargs)
    engine.compute=counted
    def g4(symbol,asof,q):
        calls['g4'].append((symbol,asof,q['status']))
        return dict(date=asof,correspondence_status='UNKNOWN',reason='SYNTHETIC_G4_MISSING_NO_FILL')
    cfg=SimpleNamespace(root=tmp_path/'synthetic_output',target=days[-1],scope=['999999.SH'],generation='a'*64,
        identity=dict(generation='a'*64,input_sha256='b'*64,asof=days[-1],basis={'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME'},historical_PIT=False),
        config=config,config_ref=producer.reference(config_path),engine=lambda:engine,core=core,
        calendars={'SH':days},read=lambda s:(copy.deepcopy(bars),'SYNTHETIC_ONLY'),
        qualify=lambda s:dict(status='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',history_start_date=str(days[0])),
        g4_reference=g4,cached_sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest())
    return cfg,bars,calls


def evaluate(**kwargs):
    # Source-input parity oracle only; no strategy/risk/return rule is altered.
    baseline=kwargs['baseline_memberships']
    return {'groups':{g:{'status':baseline.get(g,'UNKNOWN'),'reasons':['SYNTHETIC_SOURCE_INPUT_ONLY']} for g in ('original','nav_smallk','nav_pullback','nav_breakout')},'risk':{'status':'UNKNOWN'}}


def execute(producer,cfg,dates,enabled):
    return producer.compute_stock(cfg,'999999.SH',evaluate=evaluate,history_dates=dates,reuse_history_prefix=enabled)


def test_opt_in_history_one_engine_call_matches_legacy_inputs_unknown_and_cache(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path);dates=[bars[i]['trade_date'] for i in (0,13,60)]
    baseline=execute(producer,cfg,dates,False);legacy_g4=list(calls['g4']);assert calls['compute']==4
    calls.update(compute=0,g4=[])
    reused=execute(producer,cfg,dates,True)
    assert calls['compute']==1 and calls['g4']==legacy_g4
    assert baseline[:2]==reused[:2]
    assert any(r['groups']['original']=='UNKNOWN' for r in reused[1]['evaluations'].values())
    assert all(not r.get('historical_PIT',False) for r in reused[1]['evaluations'].values())


def test_normal_daily_behavior_stays_one_compute_and_identical(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path)
    baseline=execute(producer,cfg,[],False);assert calls['compute']==1
    calls['compute']=0
    same=execute(producer,cfg,[],True);assert calls['compute']==1 and baseline[:2]==same[:2]


def witness(producer,cfg,bars):
    seen=[];original=producer.source_inputs
    def observing(*args,**kwargs):
        if kwargs.get('prefix_reuse') is not None:seen.append(kwargs['prefix_reuse'])
        return original(*args,**kwargs)
    with patch.object(producer,'source_inputs',observing):execute(producer,cfg,[bars[13]['trade_date']],True)
    return seen[0],bars[:14],cfg.qualify('999999.SH')


@pytest.mark.parametrize('case',['symbol','generation','input','config','prefix','cutoff','start','qualification'])
def test_mismatched_identity_or_prefix_is_typed_cannot_confirm(producer,tmp_path,case):
    cfg,bars,calls=context(producer,tmp_path);bound,prefix,q=witness(producer,cfg,bars);calls['compute']=0;symbol='999999.SH';asof=prefix[-1]['trade_date']
    if case=='symbol':symbol='999998.SH'
    elif case=='generation':cfg.generation='c'*64
    elif case=='input':cfg.identity['input_sha256']='c'*64
    elif case=='config':cfg.config_ref={**cfg.config_ref,'sha256':'0'*64}
    elif case=='prefix':prefix=copy.deepcopy(prefix);prefix[-1]['close']='999'
    elif case=='cutoff':asof=prefix[-2]['trade_date']
    elif case=='qualification':q={**q,'status':'UNKNOWN'}
    else:prefix=prefix[1:]
    with pytest.raises(ValueError,match='CANNOT_CONFIRM_PREFIX'):
        producer.source_inputs(cfg,symbol,prefix,asof,q,prefix_reuse=bound)
    assert calls['compute']==0


@pytest.mark.parametrize('key',['formula','engine','tri_state_core','census'])
def test_unbound_causality_pin_is_rejected(producer,tmp_path,key):
    cfg,bars,calls=context(producer,tmp_path);bound,prefix,q=witness(producer,cfg,bars);calls['compute']=0
    cfg.config[key]={**cfg.config[key],'sha256':'0'*64}
    with pytest.raises(ValueError,match='CANNOT_CONFIRM_PREFIX_CAUSALITY_PINS'):
        producer.source_inputs(cfg,'999999.SH',prefix,prefix[-1]['trade_date'],q,prefix_reuse=bound)
    assert calls['compute']==0


def test_noncausal_dependency_and_requested_drawing_field_are_rejected(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path);bound,prefix,q=witness(producer,cfg,bars);calls['compute']=0
    bad={**bound,'fields':(*FIELDS,'今天')}
    with pytest.raises(ValueError,match='CONSUMED_FIELDS'):
        producer.source_inputs(cfg,'999999.SH',prefix,prefix[-1]['trade_date'],q,prefix_reuse=bad)
    engine=cfg.engine();inventory=copy.deepcopy(engine.inventory());next(a for a in inventory['assignments'] if a['name']=='一级买点')['expression']='CURRBARSCOUNT=1'
    cfg._history_prefix_causal_proof=None
    with patch.object(engine,'inventory',return_value=inventory):
        with pytest.raises(ValueError,match='NONCAUSAL_VARIABLE:CURRBARSCOUNT'):
            producer.source_inputs(cfg,'999999.SH',prefix,prefix[-1]['trade_date'],q,prefix_reuse=bound)
    assert calls['compute']==0


def test_frozen_borrowed_rows_cannot_mutate_original_and_export_no_drawings(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path);bound,prefix,q=witness(producer,cfg,bars)
    assert set(bound['rows'][0]['values'])==set(FIELDS) and 'drawings' not in bound['rows'][0]
    with pytest.raises(TypeError):bound['rows'][0]['values']['一级买点']=True
    with pytest.raises(ValueError,match='CONSUMED_FIELDS'):
        producer.source_inputs(cfg,'999999.SH',prefix,prefix[-1]['trade_date'],q,prefix_reuse=bound,retain=lambda r:None)


def test_unknown_qualification_stays_unknown_without_any_engine_or_g4_call(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path)
    cfg.qualify=lambda s:{'status':'UNKNOWN','reason':'SYNTHETIC_UNQUALIFIED_NO_FILL'}
    dates=[bars[13]['trade_date']]
    old=execute(producer,cfg,dates,False);same=execute(producer,cfg,dates,True)
    assert old[:2]==same[:2] and calls['compute']==0 and calls['g4']==[]
    assert all(value['groups']['original']=='UNKNOWN' for value in same[1]['evaluations'].values())


def test_actual_temporary_pin_byte_drift_is_rejected_without_touching_original(producer,tmp_path):
    cfg,bars,calls=context(producer,tmp_path)
    # Only copied immutable source bytes are changed for this negative fixture.
    for key,ref in list(cfg.config.items()):
        target=tmp_path/'copied_pins'/key/Path(ref['path']).name;target.parent.mkdir(parents=True);target.write_bytes(Path(ref['path']).read_bytes())
        cfg.config[key]={**ref,'path':str(target)}
    config_path=tmp_path/'copied_config.json';config_path.write_text(json.dumps(cfg.config));cfg.config_ref=producer.reference(config_path)
    bound,prefix,q=witness(producer,cfg,bars);calls['compute']=0
    Path(cfg.config['tri_state_core']['path']).write_bytes(b'changed_fixture_only')
    with pytest.raises(ValueError,match='CANNOT_CONFIRM_PREFIX_CAUSALITY_PINS'):
        producer.source_inputs(cfg,'999999.SH',prefix,prefix[-1]['trade_date'],q,prefix_reuse=bound)
    assert calls['compute']==0
