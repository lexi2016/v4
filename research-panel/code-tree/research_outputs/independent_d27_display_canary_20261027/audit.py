from pathlib import Path
import json,gzip,csv,io,hashlib,importlib.util,zipfile,datetime,struct
R=Path('/workspace/scratch/a0bba65e475b'); B=R/'panel_rebuild_20261023'; O=B/'daily_pipeline/manual_display_d27_20261027'; A=R/'research_outputs/independent_d27_display_canary_20261027'; S='002608.SZ'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_bytes())
def rows(p):return list(csv.DictReader(io.StringIO(gzip.decompress(p.read_bytes()).decode())))
def numeq(a,b):return float(a)==float(b)
spec=importlib.util.spec_from_file_location('audit_pipeline',B/'daily_pipeline/pipeline_v4.py');P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
bind=load(O/'CANARY002608_INPUT_BINDING.json');ev=load(O/'EVENTS_SOURCE_PREPARATION.json');rec=bind['baseline_record'];D=Path(bind['baseline_manifest']['path']).parent
files=[Path(bind[k]['path']) for k in ['baseline_manifest','baseline_sidecar','D26_events']]+[O/ev['events']['path'],Path(ev['source']['path']),Path(bind['G4_source']['path'])]
for key in ['baseline_manifest','baseline_sidecar','D26_events','G4_source']:assert sha(Path(bind[key]['path']))==bind[key]['sha256'],key
assert sha(O/ev['events']['path'])==ev['events']['sha256'];assert sha(Path(ev['source']['path']))==ev['source']['sha256']
for rel,h in bind['code_identity'].items():assert sha(B/rel)==h;files.append(B/rel)
assert P.code_identity()==load(D/'PLAN.json')['identity']['code']
assert sha(B/'cache/READ_INVALIDATIONS.json')==bind['live_policy_sha256'];assert S not in load(B/'cache/READ_INVALIDATIONS.json')['securities']
side=load(Path(bind['baseline_sidecar']['path']));assert side['manifest_sha256']==sha(Path(bind['baseline_manifest']['path']));risk=next(x for x in side['securities'] if x['symbol']==S);P.validate_risk(risk,set())
checkpoint=load(D/'checkpoints'/f'{S}.json');assert checkpoint['status']=='PASS' and checkpoint['last']==20261026
review=B/'daily_pipeline/daily_entry/independent_daily_audit_20261026/STAGE_OUTPUT_REVIEW.json';assert load(review)['decision']=='PASS_PARTIAL_STAGED_RESEARCH_ARTIFACTS_NOT_RELEASE';files.extend([review,D/'checkpoints'/f'{S}.json'])
de,fe,g4,guard=P.engines();constants=B/'data/gbbq_public_format_constants.bin';assert sha(constants)==ev['constants_sha256']
with zipfile.ZipFile(ev['source']['path']) as z:
 assert z.testzip() is None
 decoded=de.decode_gbbq(z.read('gbbq'),constants.read_bytes())
assert decoded==load(O/ev['events']['path'])
def selected(es,limit):return sorted([{k:v for k,v in e.items() if k!='record_index'} for e in es if e['code']=='002608' and e['market']==0 and 20210506<int(e['date'])<=limit],key=lambda e:json.dumps(e,sort_keys=True))
old=selected(load(Path(bind['D26_events']['path'])),20261026);new=selected(decoded,20261027);assert old==new;assert all(e['category']==1 for e in new)
daily=P.g4_snapshot(Path(bind['G4_source']['path']),'20261027',[S],g4)[S];assert daily==bind['D27_raw_G4'];P.VOLUME.validate_g4(daily)
out=O/'canary002608_output';rawold=rows(D/rec['raw']['path']);qold=rows(D/rec['qfq_candidate']['path']);rawnew=rows(out/'partitions/raw'/f'{S}.csv.gz');qnew=rows(out/'partitions/qfq_candidate'/f'{S}.csv.gz')
for k in ['raw','qfq_candidate']:
 assert sha(D/rec[k]['path'])==rec[k]['sha256'];files.append(D/rec[k]['path'])
assert len(rawold)==len(qold)==1327 and len(rawnew)==len(qnew)==1328
for oldrows,newrows in [(rawold,rawnew),(qold,qnew)]:
 assert all(all(numeq(a[k],b[k]) for k in a) for a,b in zip(oldrows,newrows[:-1]))
 assert len({r['trade_date'] for r in newrows})==1328
 assert all(a['trade_date']<b['trade_date'] for a,b in zip(newrows,newrows[1:]))
for k in ['open','high','low','close','vol','trade_date']:
 assert numeq(rawnew[-1][k],daily[k]) and numeq(qnew[-1][k],daily[k])
assert float(rawnew[-1]['amount'])==struct.unpack('<f',struct.pack('<f',float(daily['amount'])))[0]
assert rawnew[-1]['trade_date']=='20261027';assert rawold[-1]['trade_date']=='20261026'
# Independent full-prefix original engine recomputation, not writer process_symbol.
qinput=[dict(r,trade_date=int(r['trade_date'])) for r in qnew];computed=fe.json_ready(fe.compute(qinput,'prefix'))['rows'];actual=load_gz=lambda p:json.loads(gzip.decompress(p.read_bytes()))
writer=actual(out/'stocks'/S/'formula.json.gz');assert computed==writer['rows'];assert all(len(r['values'])==51 and len(r['drawings'])==22 for r in computed)
prior=actual(D/'stocks'/S/'formula.json.gz')['rows'];diff=[]
for a,b in zip(prior,computed[:-1]):
 fields=[k for k in a['values'] if a['values'][k]!=b['values'][k]]
 if fields or a['drawings']!=b['drawings']:diff.append({'date':a['trade_date'],'fields':fields,'drawings_changed':a['drawings']!=b['drawings']})
for f in load(O/'CANARY002608_PROCESS_RECEIPT.json')['files']:
 p=out/f['path'];assert sha(p)==f['sha256'] and p.stat().st_size==f['bytes'];files.append(p)
files.extend([O/'CANARY002608_INPUT_BINDING.json',O/'EVENTS_SOURCE_PREPARATION.json',constants,B/'cache/READ_INVALIDATIONS.json'])
report={'decision':'PASS_LIMITED_DISPLAY','scope':[S],'purpose':'D27 fixed-vintage NONPIT original-formula descriptive webpage display only','asof':'20261027','first':20210506,'rows':1328,'baseline_rows':1327,'fields':51,'drawings':22,'independent_formula_recompute_equal':True,'independent_gbbq_decode_equal':True,'effective_class1_events':len(new),'effective_event_change':False,'all_D26_raw_qfq_rows_preserved_numeric':True,'D27_raw_qfq_lastbar_equal':True,'history_formula_differences':diff,'source_raw_amount':daily['amount'],'stored_float32_amount':rawnew[-1]['amount'],'D27_ohlcv':computed[-1]['ohlcv'],'limitations':['Not production release or native QFQ semantic certification','Not historical PIT or original192/193 certification','Volume is inferred/numerically validated, not official vendor unit certification; no absolute-liquidity/training admission','Only 002608 normal domain; no special or other stocks admitted','No executable trading-price or fill guarantee','D26 as-of artifacts and scores remain immutable; any changed historical drawing is separate D27 as-of view'],'files':[{'path':str(p.relative_to(R)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'network_calls':0,'fit_calls':0,'formula_recompute_calls':1,'CURRENT_changed':False}
(A/'CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False,indent=2))
