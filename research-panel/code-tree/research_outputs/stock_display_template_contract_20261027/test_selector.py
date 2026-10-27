import importlib.util,json,pathlib,tempfile,hashlib
ROOT=pathlib.Path('/workspace/scratch/a0bba65e475b')
p=ROOT/'zge_resources/adapter/skill/scripts/stock_display_bundle.py'
spec=importlib.util.spec_from_file_location('selector',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks=[]
def ok(label,truth):
 assert truth,label
 checks.append(label)
def fails(label,fn,reason):
 try:fn()
 except m.BundleError as e:ok(label,str(e)==reason)
 else:raise AssertionError(label)
a=m.select('000592','20261027');b=m.select('301686.SZ','20261027')
ok('A then B identity independent',a['symbol']=='000592.SZ' and b['symbol']=='301686.SZ' and a['chart']['symbol']!=b['chart']['symbol'])
fails('unknown after B no fallback',lambda:m.select('999999','20261027'),'UNKNOWN_OR_AMBIGUOUS_SYMBOL')
fails('wrong analysis date no nearest',lambda:m.select('301686','20261026'),'DATE_NOT_PACKAGED')
fails('invalid calendar date',lambda:m.select('301686','20260230'),'INVALID_DATE')
ok('null preserved not zero',any(r['values']['BBI'] is None for r in b['chart']['chartRows']))
ok('short history honest',len(b['chart']['chartRows'])==19)
ok('no quote/report hallucination',b['quote'] is None and b['research_report'] is None)
manifest=json.loads(m.DEFAULT.read_text());records=json.loads((ROOT/manifest['chart_manifest']['path']).read_text())['records']
for r in records:
 d=m.select(r['symbol'],'20261027');ok('frozen identity '+r['symbol'],d['chart']['symbol']==r['symbol'])
with tempfile.TemporaryDirectory() as td:
 t=pathlib.Path(td)
 fake={'records':[{'symbol':'000592.SZ','path':'missing.json','sha256':'0'*64}]}
 src=t/'source.json';src.write_text(json.dumps(fake));manifest['chart_manifest']={'path':'source.json','sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
 target=t/'manifest.json';target.write_text(json.dumps(manifest))
 fails('missing package no example fallback',lambda:m.select('000592','20261027',target,t),'PACKAGE_MISSING')
 fake['records'].append(fake['records'][0]);src.write_text(json.dumps(fake));manifest['chart_manifest']['sha256']=hashlib.sha256(src.read_bytes()).hexdigest();target.write_text(json.dumps(manifest))
 fails('duplicate identity rejected',lambda:m.select('000592','20261027',target,t),'DUPLICATE_IDENTITY')
 src.write_text('{}');fails('corrupt manifest binding rejected',lambda:m.select('000592','20261027',target,t),'HASH_MISMATCH')
with tempfile.TemporaryDirectory() as td:
 t=pathlib.Path(td)
 original=m.select('301686','20261027')['chart']
 def bound_case(data):
  pack=t/'pack.json';pack.write_text(json.dumps(data))
  source={'records':[{'symbol':'301686.SZ','path':'pack.json','sha256':hashlib.sha256(pack.read_bytes()).hexdigest(),'bars':19,'last':20261026}]}
  src=t/'source.json';src.write_text(json.dumps(source))
  mm=json.loads(m.DEFAULT.read_text());mm['chart_manifest']={'path':'source.json','sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
  target=t/'manifest.json';target.write_text(json.dumps(mm));return target
 data=json.loads(json.dumps(original));data['symbol']='000592.SZ'
 target=bound_case(data);fails('mislabeled package rejected',lambda:m.select('301686','20261027',target,t),'IDENTITY_MISMATCH')
 data=json.loads(json.dumps(original));data['chartRows'][-1]['date']=20261028;data['source']['dailyCutoff']=20261028
 target=bound_case(data);fails('future daily data rejected',lambda:m.select('301686','20261027',target,t),'DATE_MISMATCH')
result={'status':'PASS','checks':len(checks),'cases':checks,'scope':'Pure local frozen-chart selector only. UI browser and host discovery NOT_RUN.'}
(ROOT/'research_outputs/stock_display_template_contract_20261027/CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'PASS','checks':len(checks)}))
