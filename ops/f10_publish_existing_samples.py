"""Prepare or publish only two already captured, SHA-verified F10 samples.

Prepare is isolated. Publish is for the controller after Main and API review;
it writes immutable files under the existing daily product owner and advances
only its F10 reference under that owner's lock and exact index/event CAS.
"""
from __future__ import annotations
import argparse,hashlib,json,os,plistlib,re,subprocess,sys
from pathlib import Path
from ops import research_panel_f10 as f10
from ops.research_panel_daily_product import SourceContext

EVIDENCE=Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/f10_daily_jinying_20261101_r1')
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist')
MAIN=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-daily-20261101-c94609b4e5fff848-main')
MANIFEST_SHA='3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388'
GATE_SHA='fc3c336cab03036bd3557f0fb7adcad5f03539fea90db7fcaa3dc5340d9938c0'
SAMPLE_SHA='83aebab519625dfc9583392e1374f47760ef811c08393c175acda595f2416f5b'
GENERATION='d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
INPUT='9eef2834994e6156561efc9666182a2528734adb2a086dfd602c7b7c5f4ef774'
SYMBOLS=('002865.SZ','301048.SZ');DATE='20261030';FLAGS=f10.FLAGS


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):
 p=Path(p).resolve(strict=True);return {'path':str(p),'sha256':sha(p)}
def read(ref_):return json.loads(f10._read_ref(ref_))
def save(p,value):
 raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 if Path(p).exists():
  if Path(p).read_bytes()!=raw:raise ValueError('F10_SAMPLE_IMMUTABLE_OUTPUT_CONFLICT')
  return ref(p)
 with Path(p).open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 return ref(p)

def context_and_inputs():
 if sha(MAIN/'release-manifest.json')!=MANIFEST_SHA or Path(f10.__file__).resolve()!=MAIN/'app/ops/research_panel_f10.py':
  raise ValueError('F10_SAMPLE_MAIN_CODE_IDENTITY_CONFLICT')
 manifest=json.loads((MAIN/'release-manifest.json').read_bytes())
 entries={entry['path']:entry.get('sha256') for entry in manifest['application_inventory']['entries'] if entry.get('kind')=='file'}
 for name in ('ops/research_panel_f10.py','ops/research_panel_daily_product.py','ops/research_panel_qfq.py',
              'ops/sync_stock_history_completion.py','infrastructure/scheduling/executor_registry.py'):
  path=MAIN/'app'/name
  if not path.is_file() or path.is_symlink() or entries.get(name)!=sha(path):raise ValueError('F10_SAMPLE_MAIN_MODULE_DRIFT:'+name)
 env=plistlib.loads(PLIST.read_bytes())['EnvironmentVariables']
 for name in ('V4_RESEARCH_DAILY_PRODUCT_CONFIG','V4_A_DAILY_TYPED_END_FACT_PATH','V4_A_DAILY_TYPED_END_FACT_SHA256'):
  if name in env:os.environ[name]=env[name]
 os.environ.pop('V4_SCHEDULER_LANE_FD',None)
 context=SourceContext(Path(env['V4_RESEARCH_PANEL_A_DATA_ROOT']),int(DATE))
 root=(Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share').resolve(strict=True)
 if (context.generation!=GENERATION or context.identity['input_sha256']!=INPUT or context.target!=int(DATE)):
  raise ValueError('F10_SAMPLE_CURRENT_SOURCE_CONFLICT')
 gate_ref={'path':str(EVIDENCE/'SOURCE_GATE_TWO_STOCK_R2.json'),'sha256':GATE_SHA};gate=read(gate_ref)
 if (gate.get('status')!='PASS_RELOCATED_SOURCE_GATE' or gate.get('canonical_input_sha256')!=INPUT
     or gate.get('snapshot')!=context.snapshot_ref or gate.get('target')!=int(DATE)):
  raise ValueError('F10_SAMPLE_SOURCE_GATE_CONFLICT')
 f10._read_ref(gate['relocation_ref'])
 sample_pointer=json.loads((EVIDENCE/'F10_TWO_STOCK_RECEIPT_REF.json').read_bytes())['receipt']
 if sample_pointer['sha256']!=SAMPLE_SHA:raise ValueError('F10_SAMPLE_RECEIPT_IDENTITY_CONFLICT')
 old=read(sample_pointer);checkpoint=read(old['checkpoint'])
 if (old.get('source_generation')!=GENERATION or old.get('data_date')!=DATE
     or old.get('selector_sha256')!=context.identity['selector_artifact_sha256'] or old.get('status')!='COMPLETE'
     or old.get('requested')!=2 or old.get('observed')!=2 or old.get('historical_PIT') is not False
     or any(old.get(k)!=v for k,v in FLAGS.items()) or set(checkpoint['items'])!=set(SYMBOLS)):
  raise ValueError('F10_SAMPLE_RECEIPT_SOURCE_CONFLICT')
 items={}
 for symbol in SYMBOLS:
  value=read(checkpoint['items'][symbol]);text=value.get('source_text')
  if (value.get('symbol')!=symbol or value.get('exchange')!='SZ' or value.get('status')!='OBSERVED'
      or value.get('historical_PIT') is not False or not isinstance(text,str)
      or hashlib.sha256(text.encode()).hexdigest()!=value.get('source_text_sha256')
      or any(value.get(k)!=v for k,v in FLAGS.items())):raise ValueError('F10_SAMPLE_STOCK_SOURCE_CONFLICT:'+symbol)
  items[symbol]=value
 index_ref=ref(root/'index.json');event_ref=ref(root/'events/latest.json');index=read(index_ref);event=read(event_ref)
 attempt=index.get('attempts',{}).get(DATE)
 if (attempt!=old['upstream_success_receipt'] or index.get('f10',{}).get(DATE) is not None
     or event.get('data_date')!=DATE or event.get('source_generation')!=GENERATION or event.get('input_sha256')!=INPUT
     or event.get('manifest')!=index.get('dates',{}).get(DATE)):
  raise ValueError('F10_SAMPLE_PRODUCT_INDEX_CONFLICT')
 read(attempt);context.unchanged()
 return context,root,gate_ref,sample_pointer,old,checkpoint,items,index_ref,event_ref,attempt

def fetch_from(items):
 def fetch(symbol,exchange):
  if symbol not in items or exchange!='SZ':raise ValueError('F10_SAMPLE_SYMBOL_OR_EXCHANGE_CONFLICT')
  return items[symbol]
 return fetch

def prepare():
 ctx,root,gate,sample,old,checkpoint,items,index,event,attempt=context_and_inputs()
 suffix=index['sha256'][:12]+'_'+event['sha256'][:12]+'_'+sha(__file__)[:12]
 isolated=EVIDENCE/('f10_publication_preflight_'+suffix);isolated.mkdir(exist_ok=True)
 result=f10.complete_f10(ctx,attempt,isolated,requested=SYMBOLS,workers=2,fetch=fetch_from(items))
 if result['status']!='COMPLETE' or result['observed']!=2:raise ValueError('F10_SAMPLE_ISOLATED_PREPARE_FAILED')
 plan={'schema':'v4.f10_two_sample_publication_plan.v1','status':'PREPARED_NOT_PUBLISHED','script_sha256':sha(__file__),
  'main_manifest':ref(MAIN/'release-manifest.json'),'adapter_sha256':sha(f10.__file__),'source_gate':gate,'sample_receipt':sample,
  'sample_items':checkpoint['items'],'data_date':DATE,'source_generation':GENERATION,'input_sha256':INPUT,'symbols':list(SYMBOLS),
  'product_root':str(root),'expected_index':index,'expected_event':event,'upstream_attempt':attempt,
  'isolated_receipt':result['receipt'],'historical_PIT':False,**FLAGS}
 path=EVIDENCE/('F10_INDEX_PUBLICATION_PLAN_'+suffix+'.json');result_ref=save(path,plan);print(json.dumps({'status':plan['status'],'plan':result_ref,'isolated_receipt':result['receipt']},ensure_ascii=False))

def assert_main_active():
 plist=plistlib.loads(PLIST.read_bytes());env=plist['EnvironmentVariables']
 if env.get('V4_APP_ROOT')!=str(MAIN/'app') or env.get('V4_RELEASE_MANIFEST_SHA256')!=MANIFEST_SHA:
  raise ValueError('F10_SAMPLE_EXPECTED_MAIN_NOT_ACTIVE')
 result=subprocess.run(['/bin/launchctl','print',f'gui/{os.getuid()}/com.lexi.v4.scheduler'],capture_output=True,text=True,timeout=10)
 match=re.search(r'^\s*pid = (\d+)\s*$',result.stdout,re.M)
 if result.returncode or not match:raise ValueError('F10_SAMPLE_MAIN_PROCESS_MISSING')
 cwd=subprocess.check_output(['lsof','-a','-p',match.group(1),'-d','cwd','-Fn'],text=True)
 if '\nn'+str(MAIN/'app')+'\n' not in cwd:raise ValueError('F10_SAMPLE_MAIN_PROCESS_ROOT_CONFLICT')

def publish(plan_path,plan_sha):
 plan=read({'path':str(Path(plan_path).resolve(strict=True)),'sha256':plan_sha})
 if (plan.get('schema')!='v4.f10_two_sample_publication_plan.v1' or plan.get('status')!='PREPARED_NOT_PUBLISHED'
     or plan.get('script_sha256')!=sha(__file__) or plan.get('adapter_sha256')!=sha(f10.__file__)
     or plan.get('main_manifest')!=ref(MAIN/'release-manifest.json') or plan.get('symbols')!=list(SYMBOLS)
     or plan.get('historical_PIT') is not False or any(plan.get(k)!=v for k,v in FLAGS.items())):
  raise ValueError('F10_SAMPLE_PLAN_IDENTITY_CONFLICT')
 assert_main_active();ctx,root,gate,sample,old,checkpoint,items,index,event,attempt=context_and_inputs()
 if any((plan['source_gate']!=gate,plan['sample_receipt']!=sample,plan['sample_items']!=checkpoint['items'],
         plan['product_root']!=str(root),plan['expected_index']!=index,plan['expected_event']!=event,plan['upstream_attempt']!=attempt)):
  raise ValueError('F10_SAMPLE_PLAN_BASELINE_DRIFT')
 out=root/'f10_sample_seed'/plan_sha[:16]
 result=f10.complete_f10(ctx,attempt,out,requested=SYMBOLS,workers=2,fetch=fetch_from(items))
 if result['status']!='COMPLETE' or result['observed']!=2:raise ValueError('F10_SAMPLE_PUBLICATION_INPUT_INCOMPLETE')
 assert_main_active()
 publication=f10.publish_f10_completion(ctx,root,result['receipt'],expected_index_sha256=index['sha256'],expected_event_sha256=event['sha256'])
 receipt={'schema':'v4.f10_two_sample_publication_receipt.v1','status':'PUBLISHED_VERIFIED',
  'plan':{'path':str(Path(plan_path).resolve()),'sha256':plan_sha},'f10':result,'publication':publication,
  'scope':'TWO_STOCKS_ONLY','historical_PIT':False,**FLAGS}
 path=EVIDENCE/('F10_INDEX_PUBLICATION_'+plan_sha[:16]+'.json');receipt_ref=save(path,receipt)
 print(json.dumps({'status':receipt['status'],'receipt':receipt_ref,'f10_receipt':result['receipt']},ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));p.add_argument('--plan');p.add_argument('--plan-sha256');a=p.parse_args()
 if a.action=='prepare':prepare()
 else:
  if not a.plan or not a.plan_sha256:raise ValueError('F10_SAMPLE_PLAN_ARGUMENTS_REQUIRED')
  publish(a.plan,a.plan_sha256)
