"""Run the real Main F10 owner against isolated index/event and saved captures."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import shutil
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('f10_owner_guard',ROOT/'ops/edan_f10_owner_binding.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
guard.verify_running_owner(guard.PIN['plan']);modules=guard._load_bound_modules()
f10=modules['ops.research_panel_f10'];sync=modules['ops.sync_stock_history_completion']
E=guard.EVIDENCE/'canonical_repair_r1';base=E/'isolated_owner_r1';assert not base.exists();root=base/'daily_products/a_share';(root/'events').mkdir(parents=True)
plan=json.loads(guard.PLAN.read_text());real=Path(plan['index_before']['path']).parent
expected_index='8ff01ee6db5f4df49ec9362088d9159654e01a4237f827c865719164e5c6fcf3';expected_event='78f8ceff8f22db79cb2216af4f2c893d73f228d29a95149492378bdf5ad4efd2'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def read(r):
 p=Path(r['path']);assert p.is_file() and sha(p)==r['sha256'];return json.loads(p.read_text())
assert sha(real/'index.json')==expected_index and sha(real/'events/latest.json')==expected_event
shutil.copyfile(real/'index.json',root/'index.json');shutil.copyfile(real/'events/latest.json',root/'events/latest.json')
old=runpy.run_path(str(guard.SCRIPT),run_name='f10_original_context_for_isolated_test');ctx=old['context']();bad=read(plan['new_receipt']);oldcp=read(bad['checkpoint']);captures={k:read(v) for k,v in oldcp['items'].items()}
assert set(captures)=={'002865.SZ','301048.SZ','300206.SZ'}
for code,value in captures.items():
 assert value['symbol']==code and value['status']=='OBSERVED' and hashlib.sha256(value['source_text'].encode()).hexdigest()==value['source_text_sha256']
def captured(code,exchange):
 if code not in captures or exchange!='SZ':raise ValueError('F10_CAPTURE_SCOPE_CONFLICT')
 return copy.deepcopy(captures[code])
started=time.monotonic();result=f10.complete_f10(ctx,bad['upstream_success_receipt'],root,requested=sorted(captures),workers=1,fetch=captured)
receipt=read(result['receipt']);checkpoint=read(receipt['checkpoint']);assert result['status']=='COMPLETE' and result['observed']==3
for code,oldref in oldcp['items'].items():assert checkpoint['items'][code]['sha256']==oldref['sha256']
for r in [result['receipt'],receipt['checkpoint'],*checkpoint['items'].values()]:
 p=Path(r['path']);assert p.is_relative_to(root) and p.resolve(strict=True)==p and not p.is_symlink() and sha(p)==r['sha256']
lock=base/'A_LONG.lock';lock.touch();sync.DEFAULT_OWNER_LOCK=lock
publication=f10.publish_f10_completion(ctx,root,result['receipt'],expected_index_sha256=expected_index,expected_event_sha256=expected_event)
assert publication['status']=='PUBLISHED_F10_COMPLETION'
assert sha(real/'index.json')==expected_index and sha(real/'events/latest.json')==expected_event
out=E/'ISOLATED_OWNER_PREP_R1.json';assert not out.exists();value={'status':'PASS_ACTUAL_MAIN_OWNER_ISOLATED_ROOT','isolated_base':str(base),'isolated_product_root':str(root),'receipt':result['receipt'],'checkpoint':receipt['checkpoint'],'stocks':checkpoint['items'],'isolated_publication':publication,'source_index_sha256':expected_index,'source_event_sha256':expected_event,'captured_source_sha256':{k:v['sha256'] for k,v in oldcp['items'].items()},'seconds':round(time.monotonic()-started,3),'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
out.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps({'status':value['status'],'receipt':ref(out),'rows':len(captures)},ensure_ascii=False),flush=True)
