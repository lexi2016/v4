"""Reuse three existing snapshots through the existing F10 completion owner.

prepare/check only touch this isolated evidence directory. The explicit
publish action invokes the existing owner's index/event CAS and is reserved
for the controller after the API stage has passed independent review.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
from pathlib import Path

from ops import research_panel_f10 as f10
from ops.research_panel_daily_product import SourceContext

E=Path(__file__).resolve().parent
SINGLE=E.parent
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share')
GEN='d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
INPUT='9eef2834994e6156561efc9666182a2528734adb2a086dfd602c7b7c5f4ef774'
EXPECTED_OWNER='8c17e7905de4310d65e34589abd62cf32a0cc1a70ed6b3c5048d52707d7f6bd6'
PLAN=E/'THREE_F10_PUBLICATION_PLAN_R2.json'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):return {'path':str(Path(path).resolve(strict=True)),'sha256':sha(path)}
def read(reference):return json.loads(f10._read_ref(reference))
def save(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n')
    return ref(path)
def context():
    env=plistlib.loads(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist').read_bytes())['EnvironmentVariables']
    for name in ('V4_RESEARCH_DAILY_PRODUCT_CONFIG','V4_A_DAILY_TYPED_END_FACT_PATH','V4_A_DAILY_TYPED_END_FACT_SHA256'):
        if name in env:os.environ[name]=env[name]
    ctx=SourceContext(Path(env['V4_RESEARCH_PANEL_A_DATA_ROOT']),20261030)
    if ctx.generation!=GEN or ctx.identity['input_sha256']!=INPUT:raise ValueError('F10_SOURCE_IDENTITY_CONFLICT')
    if sha(Path(f10.__file__))!=EXPECTED_OWNER:raise ValueError('F10_OWNER_SHA_CHANGED')
    return ctx
def existing():
    index_ref=ref(ROOT/'index.json');event_ref=ref(ROOT/'events/latest.json')
    index,event=read(index_ref),read(event_ref);old_ref=index.get('f10',{}).get('20261030')
    if not old_ref or event.get('f10')!=old_ref:raise ValueError('F10_EXISTING_INDEX_EVENT_CONFLICT')
    old=read(old_ref);checkpoint=read(old['checkpoint']);items=checkpoint['items']
    if old.get('source_generation')!=GEN or old.get('input_sha256')!=INPUT or set(items)!={'002865.SZ','301048.SZ'}:
        raise ValueError('F10_EXISTING_STOCK_SET_CONFLICT')
    return index_ref,event_ref,old_ref,old,items
def prepare():
    ctx=context();index_ref,event_ref,old_ref,old,items=existing()
    single=read(ref(SINGLE/'F10_SINGLE_COMPLETION_R1.json'));single_receipt=read(single['receipt']);single_checkpoint=read(single_receipt['checkpoint'])
    third=single_checkpoint['items']['300206.SZ'];captures={**items,'300206.SZ':third}
    values={symbol:read(item) for symbol,item in captures.items()}
    for symbol,value in values.items():
        if (value.get('symbol')!=symbol or value.get('exchange')!='SZ' or value.get('status')!='OBSERVED'
            or hashlib.sha256(value.get('source_text','').encode()).hexdigest()!=value.get('source_text_sha256')):
            raise ValueError('F10_CAPTURE_MISMATCH:'+symbol)
        if ctx.qualify(symbol).get('status')!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
            raise ValueError('F10_STOCK_ADMISSION_FAILED:'+symbol)
    def use_capture(symbol,exchange):
        if symbol not in values or exchange!='SZ':raise ValueError('F10_CAPTURE_SCOPE_CONFLICT')
        return values[symbol]
    result=f10.complete_f10(ctx,old['upstream_success_receipt'],E/'isolated',requested=sorted(values),workers=1,fetch=use_capture)
    if result.get('status')!='COMPLETE' or result.get('observed')!=3:raise ValueError('F10_THREE_COMPLETION_FAILED')
    receipt=read(result['receipt']);checkpoint=read(receipt['checkpoint']);current=checkpoint['items']
    if set(current)!=set(captures) or any(current[k]['sha256']!=captures[k]['sha256'] for k in captures):
        raise ValueError('F10_CAPTURE_REUSE_BYTES_CHANGED')
    if ref(ROOT/'index.json')!=index_ref or ref(ROOT/'events/latest.json')!=event_ref:
        raise ValueError('F10_INDEX_EVENT_CHANGED_DURING_PREPARE')
    plan={'schema':'v4.f10_three_stock_publication_plan.v1','status':'PREPARED_NOT_PUBLISHED',
          'source_generation':GEN,'input_sha256':INPUT,'index_before':index_ref,'event_before':event_ref,
          'prior_receipt':old_ref,'prior_items':items,'third_source':third,'new_receipt':result['receipt'],
          'new_items':current,'owner_sha256':EXPECTED_OWNER,'script_sha256':sha(__file__),
          'requested':3,'observed':3,'historical_PIT':False,**f10.FLAGS}
    print(json.dumps({'status':plan['status'],'plan':save(PLAN,plan),'new_receipt':result['receipt']},ensure_ascii=False),flush=True)
def check(expected_sha):
    if not re.fullmatch('[0-9a-f]{64}',expected_sha or ''):raise ValueError('F10_PLAN_SHA_REQUIRED')
    ctx=context();plan=read({'path':str(PLAN),'sha256':expected_sha});index_ref,event_ref,old_ref,old,items=existing()
    if (plan['status']!='PREPARED_NOT_PUBLISHED' or plan['script_sha256']!=sha(__file__)
        or plan['owner_sha256']!=sha(Path(f10.__file__)) or plan['source_generation']!=ctx.generation
        or plan['input_sha256']!=ctx.identity['input_sha256'] or plan['index_before']!=index_ref
        or plan['event_before']!=event_ref or plan['prior_receipt']!=old_ref or plan['prior_items']!=items):
        raise ValueError('F10_PUBLICATION_PLAN_CAS_CHANGED')
    new=read(plan['new_receipt']);snapshot=read(new['checkpoint']);current=snapshot['items']
    if (new.get('schema')!='v4.a_share.f10_daily_receipt.v1' or new.get('data_date')!='20261030'
        or new.get('source_generation')!=GEN or new.get('input_sha256')!=INPUT
        or new.get('upstream_success_receipt')!=old.get('upstream_success_receipt')
        or new.get('historical_PIT') is not False or any(new.get(k)!=v for k,v in f10.FLAGS.items())
        or new['status']!='COMPLETE' or new['requested']!=3 or new['observed']!=3
        or set(current)!={'002865.SZ','301048.SZ','300206.SZ'} or current!=plan['new_items']
        or any(current[k]['sha256']!=items[k]['sha256'] for k in items)
        or current['300206.SZ']['sha256']!=plan['third_source']['sha256']):
        raise ValueError('F10_PUBLICATION_COVERAGE_OR_ITEMS_CONFLICT')
    for symbol,item in current.items():
        value=read(item)
        if (value.get('symbol')!=symbol or value.get('exchange')!='SZ' or value.get('status')!='OBSERVED'
            or hashlib.sha256(value.get('source_text','').encode()).hexdigest()!=value.get('source_text_sha256')):
            raise ValueError('F10_PUBLICATION_STOCK_DRIFT:'+symbol)
    ctx.unchanged()
    print(json.dumps({'status':'F10_THREE_CAS_CHECK_PASS','plan':ref(PLAN)},ensure_ascii=False),flush=True)
    return ctx,plan
def publish(expected_sha):
    ctx,plan=check(expected_sha)
    result=f10.publish_f10_completion(ctx,ROOT,plan['new_receipt'],
        expected_index_sha256=plan['index_before']['sha256'],expected_event_sha256=plan['event_before']['sha256'])
    proof=save(E/'THREE_F10_PUBLISHED_RECEIPT_R2.json',{'status':'PUBLISHED_VERIFIED','plan':ref(PLAN),
        'publication':result,'historical_PIT':False,**f10.FLAGS})
    print(json.dumps({'status':'PUBLISHED_VERIFIED','receipt':proof},ensure_ascii=False),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','check','publish'))
    parser.add_argument('--plan-sha256');args=parser.parse_args()
    if args.action=='prepare':prepare()
    else:{'check':check,'publish':publish}[args.action](args.plan_sha256)
