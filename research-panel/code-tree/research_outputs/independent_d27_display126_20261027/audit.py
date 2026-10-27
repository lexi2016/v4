from pathlib import Path
import json,gzip,csv,io,hashlib,importlib.util,datetime,struct,math,collections
R=Path('/workspace/scratch/a0bba65e475b');B=R/'panel_rebuild_20261023';O=B/'daily_pipeline/manual_display_d27_20261027/normal126_20261027T094950Z';A=R/'research_outputs/independent_d27_display126_20261027'
def load(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):return list(csv.DictReader(io.StringIO(gzip.decompress(p.read_bytes()).decode())))
def gz(p):return json.loads(gzip.decompress(p.read_bytes()))
def eq(a,b):return float(a)==float(b)
assert (O/'SUMMARY.json').exists(),'WAIT_WRITER_FREEZE'
spec=importlib.util.spec_from_file_location('audit126_pipeline',B/'daily_pipeline/pipeline_v4.py');P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
bind=load(O/'INPUT_BINDINGS.json');manifest=load(O/'MANIFEST126.json');summary=load(O/'SUMMARY.json');orig=load(A/'ORIGINAL_SCOPE_BINDING.json');scope=[s for v in orig['scope'].values() for s in v];assert len(scope)==len(set(scope))==126;assert set(bind['scope'])==set(scope);assert len(manifest)==126 and {r['symbol'] for r in manifest}==set(scope)
anchors=[]
for p,h in orig['source_sha256'].items():assert sha(R/p)==h;anchors.append(R/p)
for k in ['D26_manifest','D26_sidecar','D26_events','D27_events','G4_source','original_index','canary_independent_check']:
 p=Path(bind[k]['path']);assert sha(p)==bind[k]['sha256'],k;anchors.append(p)
D=Path(bind['D26_manifest']['path']).parent;m={r['symbol']:r for r in load(Path(bind['D26_manifest']['path']))['securities']};risks={r['symbol']:r for r in load(Path(bind['D26_sidecar']['path']))['securities']};plan=load(D/'PLAN.json');review=load(B/'daily_pipeline/daily_entry/independent_daily_audit_20261026/STAGE_OUTPUT_REVIEW.json');assert sha(D/'PLAN.json')==review['plan']['sha256'];allowed=plan['identity']['allowed_categories'];assert allowed==[2,3,5,9]==bind['allowed_categories_preserved_not_upgraded'];assert P.code_identity()==plan['identity']['code']==bind['code_identity']
config_review=load(B/'daily_pipeline/daily_entry/independent_daily_audit_20261026/REVIEW.json');assert sha(Path(config_review['config_binding']['path']))==config_review['config_binding']['sha256'];assert load(Path(config_review['config_binding']['path']))['allowed_categories']==allowed
policy=load(B/'cache/READ_INVALIDATIONS.json');assert sha(B/'cache/READ_INVALIDATIONS.json')==bind['live_policy_sha256']
old=P.event_lists(Path(bind['D26_events']['path']));new=P.event_lists(Path(bind['D27_events']['path']));en=P.engines();daily=P.g4_snapshot(Path(bind['G4_source']['path']),'20261027',scope,en[2]);cal=load(B/'daily_pipeline/CALENDAR_20261023_1231_VERIFIED_V2.json');assert P.calendar_gate(cal,'20261027')['status']=='VERIFIED_OPEN_DATE';assert [d for d in cal['open_dates'] if '20261026'<d<='20261027']==['20261027']
samples={'001388.SZ','600698.SH','600785.SH','301686.SZ','000700.SZ'};checked=[];unknown=[];outputfiles=[];historydiff=[];catcounts=collections.Counter();allrows=0
for x in manifest:
 s=x['symbol']
 if x['status']=='UNKNOWN_SPECIAL_CONTINUATION_NOT_ADMITTED':
  assert s in {'002086.SZ','002249.SZ','688306.SH'} and x['indicator_date']==20261026 and not x.get('formula_path');unknown.append({'symbol':s,'status':x['status'],'reason':x['reason'],'indicator_date':20261026});continue
 assert x['status']=='CANDIDATE_D27_COMPUTED_PENDING_INDEPENDENT_REVIEW',(s,x['status'])
 rec=m[s];assert rec==x['baseline_record'];assert s not in policy['securities'];P.validate_risk(risks[s],set(allowed));assert x['baseline_risk']==risks[s]
 cp=load(D/'checkpoints'/f'{s}.json');assert cp['status']=='PASS' and cp['last']==20261026
 eold=P.relevant_events(old.get(s,[]),rec['first'],20261026);enew=P.relevant_events(new.get(s,[]),rec['first'],20261027);assert eold==enew and P.run_key(enew)==x['effective_event_sha256'];cats=P.validate_events(enew,s,rec['first'],20261027,set(allowed));catcounts[str(sorted(cats))]+=1
 assert daily[s]==x['D27_source_bar'];P.VOLUME.validate_g4(daily[s]);root=Path(x['output_root']);assert root.is_relative_to(B/'daily_pipeline/manual_display_d27_20261027')
 for f in x['process_receipt']['files']:
  p=root/f['path'];assert sha(p)==f['sha256'] and p.stat().st_size==f['bytes'];outputfiles.append({'symbol':s,'path':str(p.relative_to(R)),'sha256':f['sha256'],'bytes':f['bytes']})
 rawold=P.read_rows(D,rec['raw']);qold=P.read_rows(D,rec['qfq_candidate']);raw=rows(root/'partitions/raw'/f'{s}.csv.gz');q=rows(root/'partitions/qfq_candidate'/f'{s}.csv.gz');assert len(raw)==len(q)==rec['rows']+1
 for aa,bb in [(rawold,raw),(qold,q)]:
  assert all(all(eq(a[k],b[k]) for k in a) for a,b in zip(aa,bb[:-1])),s+' prefix'
  assert all(int(a['trade_date'])<int(b['trade_date']) for a,b in zip(bb,bb[1:]))
 for k in ['open','high','low','close','vol','trade_date']:assert eq(q[-1][k],daily[s][k]) and eq(raw[-1][k],daily[s][k])
 assert float(raw[-1]['amount'])==struct.unpack('<f',struct.pack('<f',float(daily[s]['amount'])))[0]
 fp=Path(x['formula_path']);assert sha(fp)==x['formula_sha256'];data=gz(fp);rr=data['rows'];assert data['symbol']==s and len(rr)==len(q) and rr[-1]['trade_date']==20261027 and rr[0]['trade_date']==rec['first'];assert data['field_count']==51 and data['drawing_count']==22
 for a,b in zip(rr,q):
  assert len(a['values'])==51 and len(a['drawings'])==22 and a['trade_date']==int(b['trade_date'])
  for k in ['open','high','low','close','vol']:assert eq(a['ohlcv'][k],b[k])
  for v in a['values'].values():assert v is None or isinstance(v,bool) or math.isfinite(float(v))
  assert [d['id'] for d in a['drawings']]==list(range(1,23))
 prior=gz(D/'stocks'/s/'formula.json.gz')['rows'];diff=sum(a!=b for a,b in zip(prior,rr[:-1]));
 if diff:historydiff.append({'symbol':s,'changed_historical_rows':diff})
 recomputed=False
 if s in samples:
  compare=en[1].json_ready(en[1].compute([dict(r,trade_date=int(r['trade_date'])) for r in q],'prefix'))['rows'];assert compare==rr,s+' recompute';recomputed=True
 assert x['process_receipt']['risk']['non_class1_categories']==sorted(cats);assert not x['process_receipt']['native_qfq_certified'] and not x['process_receipt']['PIT'] and not x['process_receipt']['training_eligible'];assert x['process_receipt']['risk']['non_class1_semantics']==('UNVERIFIED' if cats else 'NOT_APPLICABLE')
 checked.append({'symbol':s,'display_status':'PASS_LIMITED_DISPLAY','indicator_date':20261027,'rows':len(rr),'formula_sha256':sha(fp),'formula_path':str(fp.relative_to(R)),'full_prefix_preserved':True,'event_changed':False,'non_class1_categories':sorted(cats),'native_qfq_certified':False,'independently_recomputed':recomputed,'D27_source_amount_exact':daily[s]['amount'],'pipeline_amount_float32':raw[-1]['amount']});allrows+=len(rr)
assert len(checked)==123 and len(unknown)==3 and sum(r['independently_recomputed'] for r in checked)==5
for p,h in orig['source_sha256'].items():assert sha(R/p)==h
assert P.code_identity()==bind['code_identity'] and sha(B/'cache/READ_INVALIDATIONS.json')==bind['live_policy_sha256']
for p in [O/'INPUT_BINDINGS.json',O/'MANIFEST126.json',O/'SUMMARY.json',O/'PREFLIGHT126.json',D/'PLAN.json',B/'daily_pipeline/daily_entry/independent_daily_audit_20261026/STAGE_OUTPUT_REVIEW.json',B/'daily_pipeline/daily_entry/independent_daily_audit_20261026/REVIEW.json']:anchors.append(p)
report={'decision':'PASS_LIMITED_DISPLAY_PARTIAL_SCOPE','scope_count':126,'display_D27_count':123,'retained_D26_UNKNOWN_count':3,'scope_not_deleted':True,'new_independent_recompute_count':5,'new_independent_recompute_symbols':sorted(samples),'prior_canary_recompute':'002608.SZ separately hash-bound','all_output_rows_read':allrows,'all_123_full_raw_qfq_prefix_checked':True,'all_123_OHLCV_formula_input_alignment_checked':True,'all_123_51_22_structure_finite_or_null_checked':True,'all_123_formula_fields_independently_recomputed':False,'allowed_categories_source':'D26 independently bound unchanged PLAN/config, not newly loosened','nonclass1_category_distribution':dict(catcounts),'historical_formula_asof_differences':historydiff,'display_symbols':[r['symbol'] for r in checked],'unknown':unknown,'qualifications':['Fixed-vintage NONPIT mathematical/descriptive display only','Non-class1 historical semantics remain UNVERIFIED; no native QFQ or executable raw support-line certification','No production/CURRENT/all-A/192/193 or training admission','Official precise source amount is separately provided; float32 pipeline amount must not replace it','Original 85+41 membership and D26 snapshots preserved; this does not rewrite historical selection scores','Numeric formula equality independently recomputed for five new samples only, plus prior one-stock canary; remaining stocks structurally/source checked'],'inputs':[{'path':str(p.relative_to(R)),'sha256':sha(p),'bytes':p.stat().st_size} for p in anchors],'network_calls':0,'fit_calls':0,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(A/'DISPLAY_ADMISSION126.json').write_text(json.dumps({'display':checked,'unknown':unknown},ensure_ascii=False,indent=2));(A/'OUTPUT_HASHES.json').write_text(json.dumps(outputfiles,ensure_ascii=False,indent=2));report['admission_sha256']=sha(A/'DISPLAY_ADMISSION126.json');report['output_hashes_sha256']=sha(A/'OUTPUT_HASHES.json');(A/'CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['inputs','display_symbols']},ensure_ascii=False,indent=2))
