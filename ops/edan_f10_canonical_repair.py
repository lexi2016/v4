"""Repair F10 reference placement using the existing Main completion owner.

Only saved snapshots are used. Prepare writes new immutable F10 objects inside
its bound product root; check is read-only; publish remains a separate CAS.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import subprocess
import sys

HERE=Path(__file__).resolve();OWNER=HERE.with_name('edan_f10_owner_binding.py')
spec=importlib.util.spec_from_file_location('f10_existing_owner_guard',OWNER);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share')
E=guard.EVIDENCE/'canonical_repair_r1';PLAN=E/'CANONICAL_PUBLICATION_PLAN_R1.json'
API_PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist')
API_ROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/edan-single-20261102-b843699e8d3371ea/app')
PIN={'owner':'1967dfc045e63009c62f7281f1830cce9830dd37bbd839486e3ff0d44e846d45',
 'api_plist':'09baad3ed6870940d2747fb639a6b42df73895fcc41a3db5258b36c217ca5cd2',
 'api_manifest':'f10179c1b8028d088ae8e00e9de60d068550e9441a41febaa76569a5c2c2fcb1',
 'api_binding':'5b0c8a84bfb2ef7efe3ba5b7f0ff286c925a933c768b9d565992ac5e41edb557',
 'broken_index':'8ff01ee6db5f4df49ec9362088d9159654e01a4237f827c865719164e5c6fcf3',
 'broken_event':'78f8ceff8f22db79cb2216af4f2c893d73f228d29a95149492378bdf5ad4efd2',
 'isolated_owner':'bc81f7b82e77f8c9bfb906b929bba42c0dcb7ab843cf3409d6ae426041231faf',
 'isolated_consumer':'7435d9f7a03de5520c536c23dd1374a0d5db46b887ace4e8cb21cbd43c680e3b'}
FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):return {'path':str(path),'sha256':sha(path)}
def read(reference):
    path=Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path or sha(path)!=reference['sha256']:
        raise ValueError('F10_CANONICAL_REFERENCE_DRIFT')
    return json.loads(path.read_text())
def save_new(path,value):
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return ref(path)
def inside(reference,root=ROOT):
    path=Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path or not path.is_relative_to(root):
        raise ValueError('F10_CANONICAL_REFERENCE_OUTSIDE_ROOT')
    if sha(path)!=reference['sha256']:raise ValueError('F10_CANONICAL_REFERENCE_SHA_DRIFT')
    return path


def verify_runtime(code_sha):
    if not re.fullmatch('[0-9a-f]{64}',code_sha or '') or sha(HERE)!=code_sha or sha(OWNER)!=PIN['owner']:
        raise ValueError('F10_CANONICAL_CODE_IDENTITY_DRIFT')
    guard.verify_running_owner(guard.PIN['plan'])
    if sha(API_PLIST)!=PIN['api_plist']:raise ValueError('F10_CANONICAL_API_PLIST_DRIFT')
    payload=plistlib.loads(API_PLIST.read_bytes());env=payload['EnvironmentVariables']
    manifest=Path(env['V4_RELEASE_MANIFEST_PATH']);binding=Path(env['V4_WORKBENCH_HOST_BINDING'])
    if (payload.get('WorkingDirectory')!=str(API_ROOT) or env.get('V4_APP_ROOT')!=str(API_ROOT)
        or env.get('V4_RELEASE_MANIFEST_SHA256')!=PIN['api_manifest'] or sha(manifest)!=PIN['api_manifest']
        or env.get('V4_WORKBENCH_HOST_BINDING_SHA256')!=PIN['api_binding'] or sha(binding)!=PIN['api_binding']
        or Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT']).resolve()/'daily_products/a_share'!=ROOT
        or ROOT.resolve(strict=True)!=ROOT or ROOT.is_symlink()):raise ValueError('F10_CANONICAL_API_ROOT_DRIFT')
    listener=subprocess.check_output(['lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-t'],text=True).split()
    cwd=subprocess.check_output(['lsof','-a','-p','49683','-d','cwd','-Fn'],text=True).splitlines()
    if listener!=['49683'] or 'n'+str(API_ROOT) not in cwd:raise ValueError('F10_CANONICAL_API_PROCESS_DRIFT')
    return env


def verify_isolated():
    owner=read({'path':str(E/'ISOLATED_OWNER_PREP_R1.json'),'sha256':PIN['isolated_owner']})
    consumer=read({'path':str(E/'ISOLATED_CONSUMER_R1.json'),'sha256':PIN['isolated_consumer']})
    if (owner.get('status')!='PASS_ACTUAL_MAIN_OWNER_ISOLATED_ROOT'
        or consumer.get('status')!='PASS_INSTALLED_API_CONSUMER_ALL_THREE'
        or consumer.get('outside_root_negative')!='REJECTED' or consumer.get('product_rows')!=172
        or set(consumer.get('results',{}))!={'002865.SZ','301048.SZ','300206.SZ'}
        or any(item.get('status')!='OBSERVED' for item in consumer['results'].values())
        or owner.get('source_index_sha256')!=PIN['broken_index'] or owner.get('source_event_sha256')!=PIN['broken_event']):
        raise ValueError('F10_CANONICAL_ISOLATED_EVIDENCE_CONFLICT')
    return owner,consumer


def context_and_sources():
    modules=guard._load_bound_modules();f10=modules['ops.research_panel_f10']
    original=runpy.run_path(str(guard.SCRIPT),run_name='f10_canonical_original_context');ctx=original['context']()
    old=read(ref(guard.PLAN));bad=read(old['new_receipt']);checkpoint=read(bad['checkpoint'])
    if (set(checkpoint.get('items',{}))!={'002865.SZ','301048.SZ','300206.SZ'}
        or bad.get('source_generation')!=ctx.generation or bad.get('input_sha256')!=ctx.identity['input_sha256']):
        raise ValueError('F10_CANONICAL_SOURCE_COVERAGE_CONFLICT')
    captures={code:read(item) for code,item in checkpoint['items'].items()}
    for code,value in captures.items():
        if (value.get('symbol')!=code or value.get('exchange')!='SZ' or value.get('status')!='OBSERVED'
            or hashlib.sha256(value.get('source_text','').encode()).hexdigest()!=value.get('source_text_sha256')):
            raise ValueError('F10_CANONICAL_CAPTURE_CONFLICT:'+code)
    return f10,ctx,bad,checkpoint,captures


def prepare(code_sha):
    verify_runtime(code_sha);isolated,_=verify_isolated()
    if sha(ROOT/'index.json')!=PIN['broken_index'] or sha(ROOT/'events/latest.json')!=PIN['broken_event']:
        raise ValueError('F10_CANONICAL_EXPECTED_BROKEN_CAS_MOVED')
    f10,ctx,bad,oldcp,captures=context_and_sources()
    if {k:v['sha256'] for k,v in oldcp['items'].items()}!=isolated['captured_source_sha256']:
        raise ValueError('F10_CANONICAL_ISOLATED_CAPTURE_MISMATCH')
    path_key=hashlib.sha256((PIN['broken_index']+guard.PIN['plan']+PIN['isolated_consumer']).encode()).hexdigest()[:16]
    output=ROOT/'f10_canonical_repair_20261102'/path_key
    if output.exists():raise ValueError('F10_CANONICAL_OUTPUT_ALREADY_EXISTS')
    def captured(code,exchange):
        if code not in captures or exchange!='SZ':raise ValueError('F10_CAPTURE_SCOPE_CONFLICT')
        return copy.deepcopy(captures[code])
    result=f10.complete_f10(ctx,bad['upstream_success_receipt'],output,requested=sorted(captures),workers=1,fetch=captured)
    receipt=read(result['receipt']);checkpoint=read(receipt['checkpoint'])
    if result.get('status')!='COMPLETE' or result.get('observed')!=3 or set(checkpoint['items'])!=set(captures):
        raise ValueError('F10_CANONICAL_COMPLETION_INCOMPLETE')
    for value in [result['receipt'],receipt['checkpoint'],receipt['upstream_success_receipt'],*checkpoint['items'].values()]:inside(value)
    if any(checkpoint['items'][code]['sha256']!=oldcp['items'][code]['sha256'] for code in captures):
        raise ValueError('F10_CANONICAL_CAPTURE_BYTES_CHANGED')
    ctx.unchanged();verify_runtime(code_sha)
    if sha(ROOT/'index.json')!=PIN['broken_index'] or sha(ROOT/'events/latest.json')!=PIN['broken_event']:
        raise ValueError('F10_CANONICAL_INDEX_EVENT_MOVED_DURING_PREPARE')
    plan={'schema':'v4.f10_canonical_repair_plan.v1','status':'PREPARED_NOT_PUBLISHED','code_sha256':code_sha,
      'prior_plan':ref(guard.PLAN),'isolated_owner':ref(E/'ISOLATED_OWNER_PREP_R1.json'),
      'isolated_consumer':ref(E/'ISOLATED_CONSUMER_R1.json'),'index_before':ref(ROOT/'index.json'),
      'event_before':ref(ROOT/'events/latest.json'),'prior_bad_receipt':ref(Path(json.loads((ROOT/'index.json').read_text())['f10']['20261030']['path'])),
      'new_receipt':result['receipt'],'new_checkpoint':receipt['checkpoint'],'new_items':checkpoint['items'],
      'source_generation':ctx.generation,'input_sha256':ctx.identity['input_sha256'],'output_root':str(output),
      'historical_PIT':False,**FLAGS}
    if plan['prior_bad_receipt']!=oldcp_receipt_ref():raise ValueError('F10_CANONICAL_PRIOR_RECEIPT_CHANGED')
    print(json.dumps({'status':'PREPARED_NOT_PUBLISHED','plan':save_new(PLAN,plan),'new_receipt':result['receipt']},ensure_ascii=False),flush=True)


def oldcp_receipt_ref():return read(ref(guard.PLAN))['new_receipt']


def check(plan_sha,code_sha):
    verify_runtime(code_sha);verify_isolated()
    if not re.fullmatch('[0-9a-f]{64}',plan_sha or ''):raise ValueError('F10_CANONICAL_PLAN_SHA_REQUIRED')
    plan=read({'path':str(PLAN),'sha256':plan_sha});f10,ctx,bad,oldcp,captures=context_and_sources()
    if (plan.get('schema')!='v4.f10_canonical_repair_plan.v1' or plan.get('status')!='PREPARED_NOT_PUBLISHED'
        or plan.get('code_sha256')!=code_sha or plan.get('source_generation')!=ctx.generation
        or plan.get('input_sha256')!=ctx.identity['input_sha256'] or plan.get('prior_bad_receipt')!=oldcp_receipt_ref()
        or plan['index_before']!=ref(ROOT/'index.json') or plan['event_before']!=ref(ROOT/'events/latest.json')
        or plan['index_before']['sha256']!=PIN['broken_index'] or plan['event_before']['sha256']!=PIN['broken_event']
        or any(plan.get(k)!=v for k,v in FLAGS.items())):raise ValueError('F10_CANONICAL_PLAN_CAS_CONFLICT')
    receipt=read(plan['new_receipt']);checkpoint=read(receipt['checkpoint'])
    if (receipt.get('schema')!='v4.a_share.f10_daily_receipt.v1' or receipt.get('status')!='COMPLETE'
        or receipt.get('requested')!=3 or receipt.get('observed')!=3 or receipt.get('historical_PIT') is not False
        or receipt.get('source_generation')!=ctx.generation or receipt.get('input_sha256')!=ctx.identity['input_sha256']
        or receipt.get('upstream_success_receipt')!=bad['upstream_success_receipt']
        or receipt.get('checkpoint')!=plan['new_checkpoint'] or checkpoint.get('items')!=plan['new_items']
        or set(checkpoint.get('items',{}))!=set(captures)):
        raise ValueError('F10_CANONICAL_RECEIPT_IDENTITY_CONFLICT')
    for item in [plan['new_receipt'],receipt['checkpoint'],receipt['upstream_success_receipt'],*checkpoint['items'].values()]:inside(item)
    for code,item in checkpoint['items'].items():
        stock=read(item)
        if item['sha256']!=oldcp['items'][code]['sha256'] or stock!=captures[code]:raise ValueError('F10_CANONICAL_CAPTURE_BYTES_CHANGED:'+code)
    ctx.unchanged();verify_runtime(code_sha)
    print(json.dumps({'status':'F10_CANONICAL_CAS_CHECK_PASS','plan':ref(PLAN),'new_receipt':plan['new_receipt']},ensure_ascii=False),flush=True)
    return f10,ctx,plan


def publish(plan_sha,code_sha):
    f10,ctx,plan=check(plan_sha,code_sha);verify_runtime(code_sha)
    result=f10.publish_f10_completion(ctx,ROOT,plan['new_receipt'],
        expected_index_sha256=plan['index_before']['sha256'],expected_event_sha256=plan['event_before']['sha256'])
    index=json.loads((ROOT/'index.json').read_text());event=json.loads((ROOT/'events/latest.json').read_text())
    if index.get('f10',{}).get('20261030')!=plan['new_receipt'] or event.get('f10')!=plan['new_receipt']:
        raise ValueError('F10_CANONICAL_PUBLICATION_READBACK_CONFLICT')
    out=E/'CANONICAL_PUBLISHED_RECEIPT_R1.json'
    proof=save_new(out,{'status':'PUBLISHED_VERIFIED','plan':ref(PLAN),'publication':result,'historical_PIT':False,**FLAGS})
    print(json.dumps({'status':'PUBLISHED_VERIFIED','receipt':proof},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','check','publish'))
    parser.add_argument('--code-sha256',required=True);parser.add_argument('--plan-sha256');parser.add_argument('--verified-child',action='store_true',help=argparse.SUPPRESS);args=parser.parse_args()
    verify_runtime(args.code_sha256)
    if not args.verified_child:
        env=dict(os.environ);env.pop('PYTHONHOME',None);env['PYTHONPATH']=str(guard.MAIN);os.chdir(guard.MAIN)
        command=[sys.executable,'-B','-P',str(HERE),args.action,'--code-sha256',args.code_sha256,'--verified-child']
        if args.plan_sha256:command+=['--plan-sha256',args.plan_sha256]
        os.execve(sys.executable,command,env)
    if args.action=='prepare':prepare(args.code_sha256)
    elif args.action=='check':check(args.plan_sha256,args.code_sha256)
    else:publish(args.plan_sha256,args.code_sha256)

if __name__=='__main__':main()
