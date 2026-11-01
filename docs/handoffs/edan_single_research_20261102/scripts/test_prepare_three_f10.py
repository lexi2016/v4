"""Isolated tests for the thin three-stock owner/CAS wrapper."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

PATH=Path(__file__).with_name('prepare_three_f10.py')
SPEC=importlib.util.spec_from_file_location('three_f10_test',PATH)
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)

@pytest.fixture
def bound(monkeypatch,tmp_path):
    monkeypatch.setattr(module,'E',tmp_path);monkeypatch.setattr(module,'PLAN',tmp_path/'plan.json')
    ctx=SimpleNamespace(generation=module.GEN,identity={'input_sha256':module.INPUT},unchanged=lambda:None)
    monkeypatch.setattr(module,'context',lambda:ctx)
    items={}
    for symbol in ('002865.SZ','301048.SZ','300206.SZ'):
        raw='snapshot:'+symbol
        path=tmp_path/(symbol+'.json')
        path.write_text(json.dumps({'symbol':symbol,'exchange':'SZ','status':'OBSERVED',
                                    'source_text':raw,'source_text_sha256':__import__('hashlib').sha256(raw.encode()).hexdigest()}))
        items[symbol]=module.ref(path)
    prior_items={key:items[key] for key in ('002865.SZ','301048.SZ')}
    cp=tmp_path/'checkpoint.json';cp.write_text(json.dumps({'items':items}));cp_ref=module.ref(cp)
    new=tmp_path/'receipt.json';new.write_text(json.dumps({'schema':'v4.a_share.f10_daily_receipt.v1',
        'data_date':'20261030','source_generation':module.GEN,'input_sha256':module.INPUT,
        'upstream_success_receipt':{},'historical_PIT':False,**module.f10.FLAGS,
        'status':'COMPLETE','requested':3,'observed':3,'checkpoint':cp_ref}))
    index={'path':'index','sha256':'1'*64};event={'path':'event','sha256':'2'*64};old={'path':'prior','sha256':'3'*64}
    prior={'upstream_success_receipt':{}}
    current=[index,event,old,prior,prior_items]
    monkeypatch.setattr(module,'existing',lambda:tuple(current))
    plan={'status':'PREPARED_NOT_PUBLISHED','script_sha256':module.sha(PATH),'owner_sha256':module.sha(module.f10.__file__),
          'source_generation':module.GEN,'input_sha256':module.INPUT,'index_before':index,'event_before':event,
          'prior_receipt':old,'prior_items':prior_items,'new_receipt':module.ref(new),'new_items':items,
          'third_source':items['300206.SZ']}
    module.PLAN.write_text(json.dumps(plan))
    return ctx,plan,current

def test_check_accepts_same_coverage_and_exact_cas(bound):
    ctx,plan,_=bound
    assert module.check(module.sha(module.PLAN))==(ctx,plan)

@pytest.mark.parametrize('position',[0,1])
def test_check_refuses_changed_index_or_event(bound,position):
    _,_,current=bound
    current[position]={**current[position],'sha256':'f'*64}
    with pytest.raises(ValueError,match='F10_PUBLICATION_PLAN_CAS_CHANGED'):module.check(module.sha(module.PLAN))

def test_check_rejects_unpinned_plan_and_changed_stock(bound):
    with pytest.raises(ValueError,match='F10_PLAN_SHA_REQUIRED'):module.check(None)
    with pytest.raises(ValueError,match='F10_REFERENCE_SHA_DRIFT'):module.check('f'*64)
    _,plan,_=bound
    Path(plan['new_items']['300206.SZ']['path']).write_text('{}')
    with pytest.raises(ValueError,match='F10_REFERENCE_SHA_DRIFT'):module.check(module.sha(module.PLAN))

def test_publish_calls_existing_owner_with_frozen_cas(monkeypatch,bound):
    ctx,plan,_=bound;calls=[]
    def publish_owner(context,root,receipt_ref,**kwargs):
        calls.append((context,root,receipt_ref,kwargs));return {'status':'PUBLISHED_F10_COMPLETION'}
    monkeypatch.setattr(module.f10,'publish_f10_completion',publish_owner)
    module.publish(module.sha(module.PLAN))
    assert calls==[(ctx,module.ROOT,plan['new_receipt'],{'expected_index_sha256':'1'*64,'expected_event_sha256':'2'*64})]
    assert json.loads((module.E/'THREE_F10_PUBLISHED_RECEIPT_R2.json').read_text())['status']=='PUBLISHED_VERIFIED'
