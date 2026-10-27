"""Isolated, fail-closed daily research pipeline V4 (stdlib; no network/fit/trades).
Core cache/data directories are read-only. New date support does not mean natural-run acceptance.
"""
import argparse,contextlib,math,csv,datetime,fcntl,gzip,hashlib,importlib.util,io,json,os,re,shutil,struct,sys,uuid,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent
REVIEW_ROOT=PROJECT/'review'
SCHEDULE={'timezone':'Asia/Shanghai','update':'15:40','retry_failed':['16:10','16:40'],'incomplete_alert':'17:00','enabled':False}
QUALIFICATION='FIXED_VINTAGE_QFQ_RESEARCH_CANDIDATE_NONPIT_NOT_CERTIFIED_ORIGINAL192'
FIELDS=['trade_date','open','high','low','close','amount','vol','reserved']

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def date_ok(s):
 if not re.fullmatch(r'\d{8}',str(s)):raise ValueError('INVALID_DATE')
 datetime.datetime.strptime(str(s),'%Y%m%d');return str(s)
def run_key(identity):return hashlib.sha256(canonical(identity)).hexdigest()
def safe_ancestors(p):
 p=Path(p)
 if '..' in p.parts:raise ValueError('PARENT_TRAVERSAL')
 p=p.absolute()
 if any(q.is_symlink() for q in [p,*p.parents]):raise ValueError('SYMLINK_PATH')
 return p

def safe_output(p):
 p=safe_ancestors(p)
 p=p.resolve();root=safe_ancestors(HERE).resolve()
 if not p.is_relative_to(root):raise ValueError('OUTPUT_OUTSIDE_DAILY_PIPELINE')
 return p

def atomic(p,data):
 p=safe_output(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
 with t.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
 fd=os.open(p.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def save(p,obj):atomic(p,canonical(obj))
def load(p):return json.loads(Path(p).read_bytes())
def pinned(spec):
 p=safe_ancestors(spec['path'])
 if sha(p)!=spec['sha256']:raise ValueError('ANCHOR_MISMATCH:'+str(p))
 return p

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

VOLUME=module('daily_volume_contract_v4',HERE/'volume_contract_v4.py')
LEGACY_RAW32_MANIFEST_SHA='f359156b51d3fd6082f96ea36b68df4bb16917e0498c97af46342ef7cb408eae'

def engines():
 return module('daily_data_engine',PROJECT/'data/data_engine.py'),module('daily_formula_engine',PROJECT/'formula/formula_engine.py'),module('daily_g4',PROJECT/'daily_update/g4.py'),module('daily_guard',PROJECT/'daily_update/guard.py')

def code_identity():
 paths=[Path(__file__),HERE/'volume_contract_v4.py',VOLUME.DECODER_PATH,VOLUME.REVIEW_PATH,PROJECT/'daily_update/guard.py',PROJECT/'daily_update/g4.py',PROJECT/'data/data_engine.py',PROJECT/'formula/formula_engine.py',PROJECT/'formula/USER_MAIN_CHART_FORMULA_MESSAGE_EXACT_UTF8.txt']
 return {str(p.relative_to(PROJECT)):sha(p) for p in paths}

def calendar_gate(calendar,date):
 date=date_ok(date)
 if not calendar or calendar.get('review_status')!='INDEPENDENTLY_VERIFIED' or not calendar.get('authority') or not calendar.get('evidence_url'):
  return {'status':'BLOCKED_CALENDAR_NOT_VERIFIED','publish_allowed':False}
 if not calendar['coverage_start']<=date<=calendar['coverage_end']:return {'status':'BLOCKED_CALENDAR_OUTSIDE_COVERAGE','publish_allowed':False}
 if date in calendar.get('extraordinary_closure_dates',[]):return {'status':'MARKET_EXTRAORDINARY_CLOSED_NO_UPDATE','publish_allowed':False}
 if date not in calendar['open_dates']:return {'status':'MARKET_CLOSED_NO_UPDATE','publish_allowed':False}
 return {'status':'VERIFIED_OPEN_DATE','publish_allowed':True}

def event_gate(previous,current,review):
 if not previous or not current:return {'status':'BLOCKED_EVENT_SOURCE_UNKNOWN','publish_allowed':False}
 if previous==current:return {'status':'SOURCE_BYTES_UNCHANGED_NOT_SEMANTIC_CERTIFICATION','publish_allowed':True}
 ok=bool(review and review.get('previous_sha256')==previous and review.get('current_sha256')==current and review.get('review_status')=='INDEPENDENTLY_VERIFIED')
 return {'status':'REVIEWED_EVENT_SOURCE_CHANGE' if ok else 'BLOCKED_EVENT_SOURCE_CHANGED','publish_allowed':ok}

def retry_scope(symbols,states):return [s for s in symbols if states.get(s,{}).get('status')!='PASS' or not states[s].get('bytes_current')]

def file_record(base,p):
 p=Path(p);return {'path':str(p.relative_to(base)),'bytes':p.stat().st_size,'sha256':sha(p)}

def check_files(base,files):
 for f in files:
  rel=Path(f['path']);p=safe_ancestors(Path(base)/rel)
  if rel.is_absolute() or '..' in rel.parts or not p.is_relative_to(Path(base).absolute()):raise ValueError('UNSAFE_ARTIFACT')
  if not p.is_file() or p.stat().st_size!=f['bytes'] or sha(p)!=f['sha256']:raise ValueError('ARTIFACT_HASH_MISMATCH:'+str(rel))

def backup_manifest(base,files):
 return {'schema':'DAILY_PANEL_BACKUP_OUTBOX_V1','remote_status':'PENDING_UPLOAD_NOT_VERIFIED','restorable_without_raw_download':False,'raw_market_downloads_excluded':True,'files':[file_record(base,Path(base)/f) for f in sorted(set(files))]}

def validate_risk(risk,allowed_categories):
 if not isinstance(risk,dict):raise ValueError('RISK_SCHEMA_OBJECT_REQUIRED')
 required={'non_class1_categories':list,'date_or_asof_violations':list,'negative_price_rows_preserved':int,'qfq_semantic_certified':bool,'PIT':bool,'raw_rows_verified':int,'qfq_rows_structure_verified':int}
 for name,kind in required.items():
  if name not in risk or type(risk[name]) is not kind:raise ValueError('RISK_SCHEMA_MISSING_OR_TYPE:'+name)
 if any(type(v)is not int for v in risk['non_class1_categories']):raise ValueError('RISK_SCHEMA_CATEGORY_TYPE')
 if any(risk[k]<0 for k in ('negative_price_rows_preserved','raw_rows_verified','qfq_rows_structure_verified')):raise ValueError('RISK_SCHEMA_NEGATIVE_COUNT')
 if risk['PIT'] is not False:raise ValueError('RISK_SCHEMA_UNSUPPORTED_PIT')
 if risk['date_or_asof_violations'] or risk['negative_price_rows_preserved'] or not set(risk['non_class1_categories'])<=allowed_categories:raise ValueError('SIDECAR_RISK_NOT_ALLOWED')

def artifact_identity(states):
 return run_key({s:r['files'] for s,r in sorted(states.items())})

def independent_release(release,identity,states):
 if not release or release.get('research_only') is not True or release.get('review_status')!='INDEPENDENTLY_VERIFIED' or release.get('identity_sha256')!=run_key(identity) or release.get('scope')!=identity['scope']:raise ValueError('INDEPENDENT_SNAPSHOT_RELEASE_MISSING')
 digest=artifact_identity(states)
 if release.get('artifact_sha256')!=digest:raise ValueError('RELEASE_ARTIFACT_BINDING_MISMATCH')
 evidence=release.get('reviewer_evidence')
 if not isinstance(evidence,dict):raise ValueError('REVIEWER_EVIDENCE_PIN_REQUIRED')
 ep=pinned(evidence).resolve()
 if not ep.is_relative_to(REVIEW_ROOT.resolve()):raise ValueError('REVIEWER_EVIDENCE_OUTSIDE_INDEPENDENT_REVIEW_ROOT')
 ev=load(ep)
 if ev.get('review_status')!='INDEPENDENTLY_VERIFIED' or ev.get('run_key')!=run_key(identity) or ev.get('artifact_sha256')!=digest or not ev.get('reviewer'):raise ValueError('INDEPENDENT_REVIEW_EVIDENCE_NOT_BOUND')
 return ep

def validate_promotion(out,version,receipt):
 disk=load(version/'RECEIPT.json');plan=load(version/'PLAN.json')
 if canonical(disk)!=canonical(receipt):raise ValueError('CALLER_RECEIPT_NOT_DISK_RECEIPT')
 if disk.get('schema')!='DAILY_PANEL_RUN_V4' or disk.get('mode')!='stage' or disk.get('status')!='READY_RESEARCH_SNAPSHOT' or disk.get('publish_allowed') is not True:raise ValueError('PUBLICATION_GATES_NOT_PASSED')
 identity=plan['identity'];key=run_key(identity)
 if key!=disk['run_key'] or plan['run_key']!=key or disk['scope']!=identity['scope'] or disk['target_date']!=identity['date'] or disk['actual_data_date']!=identity['date']:raise ValueError('PLAN_RECEIPT_BINDING_MISMATCH')
 if code_identity()!=identity['code']:raise ValueError('PROMOTE_CODE_CHANGED')
 bindings=plan['source_bindings']
 for name,expected in identity['inputs'].items():
  if bindings[name]['sha256']!=expected:raise ValueError('PROMOTE_INPUT_BINDING_MISMATCH')
  pinned(bindings[name])
 current_policy=load(pinned(bindings['live_read_policy']))
 configured_policy=load(pinned(bindings['read_policy']))
 invalid=set(current_policy['securities'])|set(configured_policy['securities'])
 if set(disk['scope'])&invalid:raise ValueError('PROMOTE_POLICY_INVALIDATED')
 calendar=load(pinned(bindings['calendar'])) if 'calendar'in bindings else None
 states=disk['stocks']
 if set(states)!=set(disk['scope']) or disk['counts']['passed']!=len(states) or disk['counts']['failed']!=0 or any(r['status']!='PASS' or str(r['last'])!=identity['date'] for r in states.values()):raise ValueError('PROMOTE_SCOPE_INCOMPLETE')
 # Verify every staged byte including raw files, not only backup-selected objects.
 for stock in states.values():check_files(version,stock['files'])
 release=load(pinned(plan['release_binding'])) if plan.get('release_binding') else None
 independent_release(release,identity,states)
 blockers=release_gate(release,identity,True,calendar,states)
 if blockers:raise ValueError('PROMOTE_GATES_CHANGED:'+','.join(blockers))
 source_manifest=load(pinned(bindings['manifest']));sidecar=load(pinned(bindings['sidecar']))
 recs={r['symbol']:r for r in source_manifest['securities']};risks={r['symbol']:r for r in sidecar['securities']}
 if sidecar['manifest_sha256']!=identity['inputs']['manifest']:raise ValueError('PROMOTE_SIDECAR_BINDING')
 for symbol in disk['scope']:
  validate_risk(risks.get(symbol),set(identity['allowed_categories']))
  for kind in ('raw','qfq_candidate'):read_rows(Path(bindings['manifest']['path']).parent,recs[symbol][kind])
 manifest=load(version/'BACKUP_MANIFEST.json');check_files(version,manifest['files'])
 outbox=load(version/'UPLOAD_OUTBOX.json')
 if outbox.get('manifest_path')!='BACKUP_MANIFEST.json' or outbox.get('manifest_sha256')!=sha(version/'BACKUP_MANIFEST.json'):raise ValueError('PORTABLE_OUTBOX_BINDING_MISMATCH')
 return disk

def promote(out,version,receipt):
 out=safe_output(out);version=safe_output(version)
 if not (version.is_relative_to(out/'versions') or version.is_relative_to(out/'staging')):raise ValueError('VERSION_OUTSIDE_OUTPUT')
 try:receipt=validate_promotion(out,version,receipt)
 except (FileNotFoundError,KeyError,TypeError) as e:raise ValueError('PUBLICATION_EVIDENCE_MISSING_OR_MALFORMED:'+str(e)) from e
 if version.is_relative_to(out/'staging'):
  final=out/'versions'/version.name;final.parent.mkdir(parents=True,exist_ok=True)
  if final.exists():raise ValueError('IMMUTABLE_VERSION_ALREADY_EXISTS')
  os.rename(version,final);version=final
 pointer={'version':str(version.relative_to(out)),'target_date':receipt['target_date'],'actual_data_date':receipt['actual_data_date'],'scope':receipt['scope'],'qualification':QUALIFICATION,'PIT':False,'run_key':receipt['run_key'],'receipt_sha256':sha(version/'RECEIPT.json')}
 save(out/'CURRENT.json',pointer);return pointer

def event_lists(path):
 out={}
 for e in load(path):
  market={0:'SZ',1:'SH',2:'BJ'}.get(e['market'])
  if market:out.setdefault(e['code']+'.'+market,[]).append(e)
 return out

def relevant_events(events,first,last):
 return sorted([{k:v for k,v in e.items() if k!='record_index'} for e in events if first<int(e['date'])<=last],key=lambda e:canonical(e))

def validate_events(events,symbol,first,last,allowed):
 if not isinstance(events,list):raise ValueError('EVENT_SCHEMA_LIST_REQUIRED')
 categories=set()
 for e in events:
  if not isinstance(e,dict) or type(e.get('category'))is not int or type(e.get('date'))is not int:raise ValueError('EVENT_SCHEMA_CATEGORY_DATE')
  date_ok(e['date'])
  if not first<e['date']<=last:raise ValueError('EVENT_DATE_OUTSIDE_REVIEW_SCOPE')
  cat=e['category']
  if cat!=1:
   categories.add(cat)
   if cat not in allowed:raise ValueError('EVENT_CATEGORY_NOT_ALLOWED:'+str(cat))
  for k in ('c1','c2','c3','c4'):
   if type(e.get(k))not in (int,float) or not math.isfinite(e[k]):raise ValueError('EVENT_SCHEMA_NUMERIC:'+k)
  code,market=symbol.split('.')
  if e.get('code',code)!=code or e.get('market',{'SZ':0,'SH':1}[market])!={'SZ':0,'SH':1}[market]:raise ValueError('EVENT_SECURITY_MISMATCH')
 return categories

def read_rows(root,spec):
 p=safe_ancestors(root/spec['path'])
 if not p.is_relative_to(root/'partitions') or p.stat().st_size!=spec['bytes'] or sha(p)!=spec['sha256']:raise ValueError('PARTITION_HASH_OR_PATH')
 with gzip.open(p,'rt') as f:rows=list(csv.DictReader(f))
 for r in rows:r['trade_date']=int(date_ok(r['trade_date']))
 if any(a['trade_date']>=b['trade_date'] for a,b in zip(rows,rows[1:])):raise ValueError('ROW_DATE_ORDER')
 return rows

def encode_rows(rows):
 text=io.StringIO(newline='');w=csv.DictWriter(text,fieldnames=FIELDS);w.writeheader();w.writerows(rows);return gzip.compress(text.getvalue().encode(),mtime=0)

def merge_daily(raw,daily,date,calendar):
 date=int(date_ok(date));last=raw[-1]['trade_date']
 if daily['trade_date']!=date:raise ValueError('DAILY_DATE_MISMATCH')
 row={k:daily[k] for k in FIELDS if k not in ('reserved',)};row['reserved']=0
 # .day amount has float32 precision; preserve equivalence to the historic raw format.
 row['amount']=struct.unpack('<f',struct.pack('<f',float(row['amount'])))[0]
 if date==last:
  for k in FIELDS:
   if k=='reserved':continue
   if float(raw[-1][k])!=float(row[k]):raise ValueError('SAME_DATE_RAW_MISMATCH:'+k)
  return raw,False
 if date<last:raise ValueError('TARGET_BEFORE_BASELINE')
 if calendar_gate(calendar,str(date))['status']!='VERIFIED_OPEN_DATE':raise ValueError('CALENDAR_REQUIRED_NEW_DATE')
 if calendar['coverage_start']>str(last):raise ValueError('CALENDAR_BASELINE_GAP_NOT_COVERED')
 opens=[int(d) for d in calendar['open_dates'] if last<int(d)<=date]
 if opens!=[date]:raise ValueError('MISSING_INTERMEDIATE_TRADING_DATES')
 return raw+[row],True

def g4_snapshot(path,date,symbols,g4):
 suffix=date_ok(date)[2:];out={}
 with zipfile.ZipFile(path) as z:
  names=z.namelist()
  if len(names)!=len(set(names)) or z.testzip() is not None:raise ValueError('BAD_G4_ARCHIVE')
  for market in {s.split('.')[1] for s in symbols}:
   cod=z.read(market.lower()+suffix+'.cod');md=z.read(market.lower()+suffix+'.md1')
   if len(cod)%150 or len(md)!=len(cod)//150*512:raise ValueError('G4_ALIGNMENT')
   requested={s.split('.')[0] for s in symbols if s.endswith('.'+market)}
   for i in range(len(cod)//150):
    c=cod[i*150:i*150+6].decode('ascii',errors='replace')
    if c not in requested:continue
    symbol=c+'.'+market
    if symbol in out:raise ValueError('DUPLICATE_G4_SYMBOL')
    try:out.update(g4.parse(cod[i*150:(i+1)*150],md[i*512:(i+1)*512],market,int(date)))
    except ValueError as e:out[symbol]={'error':str(e)}
 return out

def cached_rows(cache_roots,symbol,asof,rec,policy):
 # Pre-V4 cache was computed without a bound volume schema. It remains readable
 # via the legacy reader but is NOT an accepted cache for this upgraded version.
 if symbol in policy['securities']:raise ValueError('READ_POLICY_INVALIDATED:'+symbol)
 return None

def prepare(config):
 c=dict(config);date=date_ok(c['date']);vintage=date_ok(c['vintage'])
 if date!=vintage or c['g4_trade_date']!=date or c['events_vintage']!=date:raise ValueError('SOURCE_DATE_VINTAGE_MISMATCH')
 symbols=sorted(set(c['symbols']))
 if len(symbols)!=len(c['symbols']) or not symbols or any(not re.fullmatch(r'\d{6}\.(SH|SZ)',s) for s in symbols):raise ValueError('SCOPE_REQUIRES_UNIQUE_SH_SZ_SYMBOLS')
 paths={k:pinned(c[k]) for k in ('manifest','sidecar','daily','events','baseline_events','read_policy')}
 for k in ('calendar','release','event_reviews','source_receipt'):
  if c.get(k):paths[k]=pinned(c[k])
 paths['live_read_policy']=PROJECT/'cache/READ_INVALIDATIONS.json'
 m=load(paths['manifest']);sidecar=load(paths['sidecar']);records={r['symbol']:r for r in m['securities']}
 volume=m.get('volume_contract')
 if volume is None and c['manifest']['sha256']==LEGACY_RAW32_MANIFEST_SHA:volume={'volume_encoding':VOLUME.RAW_ENCODING}
 if not isinstance(volume,dict) or volume.get('volume_encoding') not in (VOLUME.RAW_ENCODING,VOLUME.DECODED_ENCODING,VOLUME.OUTPUT_ENCODING):raise ValueError('VOLUME_SCHEMA_UNKNOWN_OR_MISSING')
 if volume['volume_encoding']!=VOLUME.RAW_ENCODING and volume.get('decoder_sha256')!=VOLUME.DECODER_SHA:raise ValueError('VOLUME_SCHEMA_DECODER_VERSION_MISMATCH')
 for rec in records.values():
  rec['_volume_encoding']=volume['volume_encoding'];rec['_volume_decoder_sha256']=volume.get('decoder_sha256')
 if sidecar['manifest_sha256']!=c['manifest']['sha256']:raise ValueError('SIDECAR_MANIFEST_BINDING')
 if not set(symbols)<=records.keys():raise ValueError('SYMBOL_OUTSIDE_BASELINE')
 if int(date)<int(m['source_vintage']):raise ValueError('TARGET_BEFORE_SOURCE_VINTAGE')
 if int(date)>int(m['source_vintage']):
  provenance=load(paths['source_receipt']) if 'source_receipt'in paths else {}
  if provenance.get('date')!=date or provenance.get('daily_sha256')!=c['daily']['sha256'] or provenance.get('events_sha256')!=c['events']['sha256'] or not provenance.get('daily_source_url') or not provenance.get('events_source_url'):raise ValueError('NEW_DAY_SOURCE_RECEIPT_MISSING_OR_UNBOUND')
 policy=load(paths['read_policy']);policy['securities'].update(load(paths['live_read_policy'])['securities']);calendar=load(paths['calendar']) if 'calendar'in paths else None
 identity={'date':date,'vintage':vintage,'rule_version':c['rule_version'],'scope':symbols,'allowed_categories':sorted(c.get('allowed_categories',[])),'inputs':{k:sha(p) for k,p in paths.items() if k!='release'},'code':code_identity(),'source_volume_contract':VOLUME.contract()|{'input_volume_encoding':volume['volume_encoding']}}
 return c,paths,m,records,sidecar,policy,calendar,identity

def release_gate(release,identity,rows_ok,calendar,statuses):
 blockers=[]
 if not calendar_gate(calendar,identity['date'])['publish_allowed']:blockers.append(calendar_gate(calendar,identity['date'])['status'])
 if not rows_ok:blockers.append('INCOMPLETE_OR_QUARANTINED_SCOPE')
 if not calendar or calendar.get('extraordinary_checked_through','')<identity['date'] or not calendar.get('extraordinary_check_evidence'):blockers.append('BLOCKED_EXTRAORDINARY_CALENDAR_REFRESH_REQUIRED')
 try:independent_release(release,identity,statuses)
 except (ValueError,KeyError,FileNotFoundError,TypeError) as e:blockers.append(str(e))
 now=datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8)))
 if now.strftime('%Y%m%d')<identity['date'] or (now.strftime('%Y%m%d')==identity['date'] and now.strftime('%H:%M')<'15:00'):blockers.append('MARKET_DATE_NOT_CLOSED')
 return blockers

def process_symbol(symbol,records,data_root,daily,baseline_events,events,policy,reviews,calendar,date,cache_roots,engines_,stage,dry_run,allowed_categories=None):
 de,fe,_,_=engines_;rec=records[symbol]
 if symbol in policy['securities']:raise ValueError('READ_POLICY_INVALIDATED:'+symbol)
 if not rec.get('qfq_candidate') or rec['identity'] not in ('SH_A_CODE_CANDIDATE','SZ_A_CODE_CANDIDATE'):raise ValueError('NO_REVIEWABLE_QFQ_BASELINE')
 if symbol not in daily or 'error'in daily[symbol]:raise ValueError('MISSING_OR_INVALID_DAILY_BAR')
 raw=read_rows(data_root,rec['raw']);oldq=read_rows(data_root,rec['qfq_candidate'])
 if len(raw)!=rec['rows'] or len(oldq)!=len(raw) or any(x['trade_date']!=y['trade_date'] for x,y in zip(raw,oldq)):raise ValueError('BASELINE_ROW_COVERAGE')
 if raw[-1]['trade_date']!=rec['last']:raise ValueError('BASELINE_LAST_DATE')
 raw,oldq,volume_check=VOLUME.normalize_pair(raw,oldq,rec.get('_volume_encoding'),rec.get('_volume_decoder_sha256'))
 g4_check=VOLUME.validate_g4(daily[symbol])
 merged,appended=merge_daily(raw,daily[symbol],date,calendar)
 olde=relevant_events(baseline_events.get(symbol,[]),raw[0]['trade_date'],raw[-1]['trade_date'])
 newe=relevant_events(events.get(symbol,[]),raw[0]['trade_date'],int(date));changed=olde!=newe
 source_categories=validate_events(newe,symbol,raw[0]['trade_date'],int(date),set(allowed_categories or []));effective_categories=source_categories
 if changed:
  review=reviews.get(symbol)
  oldh=run_key(olde);newh=run_key(newe)
  if not review or review.get('baseline_events_sha256')!=oldh or review.get('source_events_sha256')!=newh or review.get('status')!='INDEPENDENTLY_VERIFIED' or not review.get('evidence_urls'):raise ValueError('EVENT_CHANGE_REQUIRES_STOCK_REVIEW')
  effective=review.get('effective_events',newe)
  # Effective events are explicit, hash-bound reviewed corrections, never silently guessed.
  if review.get('effective_events_sha256')!=run_key(effective):raise ValueError('EFFECTIVE_EVENTS_REVIEW_HASH')
  effective_categories=validate_events(effective,symbol,raw[0]['trade_date'],int(date),set(allowed_categories or []))
  q,reason=de.qfq_candidate([{**r,**{k:float(r[k]) for k in ('open','high','low','close')}} for r in merged],effective,int(date))
  if q is None:raise ValueError('QFQ_REBUILD_BLOCKED:'+','.join(reason))
  mode='EVENT_REBUILD_FULL_STOCK_HISTORY'
 else:q=oldq+([merged[-1]] if appended else []);mode='APPEND_WITH_UNCHANGED_EVENTS' if appended else 'SAME_DATE_REPLAY'
 if any(min(float(r[k]) for k in ('open','high','low','close'))<0 for r in q):raise ValueError('NEGATIVE_QFQ_REQUIRES_REVIEW')
 prior=cached_rows(cache_roots,symbol,int(date),rec,policy) if not appended and not changed else None
 receipt={'symbol':symbol,'status':'PASS','date':date,'rows':len(q),'first':q[0]['trade_date'],'last':q[-1]['trade_date'],'mode':mode,'event_changed':changed,'formula_action':'REUSE_VALIDATED_CACHE' if prior is not None else 'COMPUTE_FULL_PREFIX_FOR_THIS_STOCK','files':[],'qualification':QUALIFICATION,'PIT':False,'native_qfq_certified':False,'volume_unit_certified':False,'absolute_liquidity_eligible':False,'training_eligible':False,'volume_encoding':VOLUME.OUTPUT_ENCODING,'volume_decoder_sha256':VOLUME.DECODER_SHA,'volume_check':volume_check,'g4_volume_check':g4_check,'g4_volume_encoding':'G4_UINT64_OFFSET56_INFERRED_V1','risk':{'symbol':symbol,'non_class1_categories':sorted(source_categories|effective_categories),'non_class1_semantics':'UNVERIFIED' if source_categories|effective_categories else 'NOT_APPLICABLE','date_or_asof_violations':[],'negative_price_rows_preserved':0,'raw_rows_verified':len(merged),'qfq_rows_structure_verified':len(q),'qfq_semantic_certified':False,'PIT':False}}
 if dry_run:return receipt
 result={'schema':'DAILY_PANEL_STOCK_V4','symbol':symbol,'volume_contract':VOLUME.contract(),'source_vintage':date,'qualification':QUALIFICATION,'PIT':False,'rows':prior if prior is not None else fe.json_ready(fe.compute(q,'prefix'))['rows'],'field_count':51,'drawing_count':22}
 if len(result['rows'])!=len(q) or result['rows'][-1]['trade_date']!=int(date):raise ValueError('FORMULA_READBACK_DATE_COVERAGE')
 for label,content in [('raw.csv.gz',encode_rows(merged)),('qfq.csv.gz',encode_rows(q)),('formula.json.gz',gzip.compress(canonical(result),mtime=0))]:
  p=(stage/'partitions'/('raw' if label=='raw.csv.gz' else 'qfq_candidate')/(symbol+'.csv.gz')) if label!='formula.json.gz' else stage/'stocks'/symbol/label
  atomic(p,content);receipt['files'].append(file_record(stage,p))
 # Independent decompression/readback, preserving nulls rather than substituting false.
 reread=json.loads(gzip.decompress((stage/'stocks'/symbol/'formula.json.gz').read_bytes()))
 if reread!=result:raise ValueError('FORMULA_READBACK_MISMATCH')
 return receipt

def run(config,out,mode='dry-run',publish=False):
 c,paths,m,records,sidecar,policy,calendar,identity=prepare(config);out=safe_output(out);out.mkdir(parents=True,exist_ok=True)
 key=run_key(identity);stage=out/'staging'/(identity['date']+'_'+key[:20]);final=out/'versions'/stage.name
 release_anchor=c.get('release',{}).get('sha256')
 with (out/'RUN.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('ANOTHER_DAILY_RUN_OWNS_OUTPUT')
  if final.exists():
   check_files(final,load(final/'BACKUP_MANIFEST.json')['files'])
   r=load(final/'RECEIPT.json')
   if r['run_key']!=key:raise ValueError('FROZEN_VERSION_KEY_MISMATCH')
   for stock in r['stocks'].values():check_files(final,stock['files'])
   if publish:promote(out,final,r)
   return r|{'version_path':str(final),'idempotent_frozen_readback':True,'current_pointer_unchanged':not publish}
  stage.mkdir(parents=True,exist_ok=True)
  dry=mode=='dry-run';save(stage/'PLAN.json',{'identity':identity,'run_key':key,'schedule':SCHEDULE,'mode':mode,'source_bindings':{k:{'path':str(p),'sha256':sha(p)} for k,p in paths.items() if k!='release'},'release_binding':c.get('release')})
  en=engines();_,_,g4,guard=en
  # Reuse the existing path-safe sentinel; verify selected raw/QFQ bytes below before retries.
  guard.inputs(paths['manifest'].parent,paths['manifest'],c['manifest']['sha256'])
  daily=g4_snapshot(paths['daily'],identity['date'],identity['scope'],g4)
  oldevents=event_lists(paths['baseline_events']);events=event_lists(paths['events']);reviews=load(paths['event_reviews']).get('securities',{}) if 'event_reviews'in paths else {}
  riskmap={r['symbol']:r for r in sidecar['securities']}
  if len(riskmap)!=len(sidecar['securities']):raise ValueError('DUPLICATE_SIDECAR_STOCK')
  allowed_categories=set(c.get('allowed_categories',[]))
  if not allowed_categories<={2,3,5,9}:raise ValueError('UNREVIEWED_EVENT_CATEGORY_POLICY')
  counts={'passed':0,'failed':0,'processed':0,'reused_shards':0,'formula_compute_calls':0,'fit_calls':0};states={}
  for symbol in identity['scope']:
   cp=stage/'checkpoints'/(symbol+'.json');prior=load(cp) if cp.exists() else None
   try:
    risk=riskmap.get(symbol)
    if risk is None:raise ValueError('SIDECAR_STOCK_MISSING')
    validate_risk(risk,allowed_categories)
    # Always recheck source bytes and policy even if this shard already succeeded.
    preview=process_symbol(symbol,records,paths['manifest'].parent,daily,oldevents,events,policy,reviews,calendar,identity['date'],c.get('cache_roots',[]),en,stage,True,allowed_categories)
    if not dry and prior and prior.get('status')=='PASS' and prior.get('files'):
     check_files(stage,prior['files']);r=prior;counts['reused_shards']+=1
    elif dry:r=preview;counts['processed']+=1
    else:
     r=process_symbol(symbol,records,paths['manifest'].parent,daily,oldevents,events,policy,reviews,calendar,identity['date'],c.get('cache_roots',[]),en,stage,False,allowed_categories);counts['processed']+=1
     counts['formula_compute_calls']+=r['formula_action']=='COMPUTE_FULL_PREFIX_FOR_THIS_STOCK'
    counts['passed']+=1
   except Exception as e:r={'symbol':symbol,'status':'FAIL','reason':type(e).__name__+': '+str(e),'files':[]};counts['failed']+=1
   states[symbol]=r
   if not dry:save(cp,r)
  # Detect concurrent modifications of policy/code/source anchors before any release.
  for k,p in paths.items():
   if k!='release' and sha(p)!=identity['inputs'][k]:raise ValueError('INPUT_CHANGED_DURING_RUN:'+k)
  if code_identity()!=identity['code']:raise ValueError('CODE_CHANGED_DURING_RUN')
  if 'release'in paths and sha(paths['release'])!=release_anchor:raise ValueError('RELEASE_CHANGED_DURING_RUN')
  release=load(paths['release']) if 'release'in paths else None
  blockers=release_gate(release,identity,counts['failed']==0,calendar,states)
  if dry:blockers.append('DRY_RUN_NO_PUBLICATION')
  receipt={'schema':'DAILY_PANEL_RUN_V4','run_key':key,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'target_date':identity['date'],'actual_data_date':identity['date'] if not counts['failed'] else None,'scope':identity['scope'],'counts':counts,'stocks':states,'calendar':calendar_gate(calendar,identity['date']),'event_source':event_gate(c['baseline_events']['sha256'],c['events']['sha256'],None),'status':'READY_RESEARCH_SNAPSHOT' if not blockers else 'BLOCKED_PUBLICATION','publish_allowed':not blockers,'blockers':blockers,'mode':mode,'PIT':False,'qualification':QUALIFICATION,'training_eligible':False,'source_volume_contract':identity['source_volume_contract'],'natural_scheduled_run':'NOT_RUN','remote_backup':'PENDING_UPLOAD_NOT_VERIFIED','production_trading':'NOT_APPLICABLE'}
  save(stage/('DRY_RUN_RECEIPT.json' if dry else 'RECEIPT.json'),receipt)
  save(out/'LATEST_ATTEMPT.json',{'run_key':key,'target_date':identity['date'],'status':receipt['status'],'blockers':blockers,'counts':counts,'created_utc':receipt['created_utc'],'old_snapshot_retained':bool(blockers)})
  if not dry:
   next_records=[];next_risks=[];riskmap={r['symbol']:r for r in sidecar['securities']}
   for symbol,r in states.items():
    if r['status']!='PASS':
     next_records.append({'symbol':symbol,'status':'QUARANTINED_NOT_NO_SIGNAL','reason':r['reason']});continue
    nr={k:v for k,v in records[symbol].items() if k not in ('raw','qfq_candidate','rows','first','last','status','_volume_encoding','_volume_decoder_sha256')}
    nr.update(rows=r['rows'],first=r['first'],last=r['last'],status=[QUALIFICATION])
    for kind in ('raw','qfq_candidate'):
     f=file_record(stage,stage/'partitions'/kind/(symbol+'.csv.gz'));nr[kind]=f
    next_records.append(nr);next_risks.append(r['risk'])
   save(stage/'PARTITION_MANIFEST.json',{'source_vintage':identity['date'],'volume_contract':VOLUME.contract(),'formula_ready_certified':False,'PIT':False,'securities':next_records,'daily_pipeline_run_key':key,'partial_scope':True})
   save(stage/'PARTITION_AUDIT_SIDECAR.json',{'status':'DAILY_RESEARCH_CANDIDATE_NOT_SEMANTIC_CERTIFIED','manifest_sha256':sha(stage/'PARTITION_MANIFEST.json'),'securities':next_risks})
   for name,src in [('READ_INVALIDATIONS.json',paths['read_policy']),('SOURCE_MANIFEST.json',paths['manifest']),('SOURCE_SIDECAR.json',paths['sidecar'])]:atomic(stage/name,src.read_bytes())
   codefiles=[]
   for rel,h in identity['code'].items():
    src=PROJECT/rel;dst=stage/'code'/rel
    if sha(src)!=h:raise ValueError('CODE_CHANGED_BEFORE_BACKUP')
    atomic(dst,src.read_bytes());codefiles.append(str(dst.relative_to(stage)))
   receiptfiles=[]
   for label in ('calendar','release','event_reviews','source_receipt','live_read_policy'):
    if label in paths:
     dst=stage/'input_receipts'/(label+'.json');atomic(dst,paths[label].read_bytes());receiptfiles.append(str(dst.relative_to(stage)))
   files=codefiles+receiptfiles+['PARTITION_MANIFEST.json','PARTITION_AUDIT_SIDECAR.json','PLAN.json','RECEIPT.json','READ_INVALIDATIONS.json','SOURCE_MANIFEST.json','SOURCE_SIDECAR.json']
   files += [str(p.relative_to(stage)) for p in stage.glob('checkpoints/*.json')]
   files += [f['path'] for r in states.values() for f in r['files'] if not f['path'].startswith('partitions/raw/')]
   save(stage/'BACKUP_MANIFEST.json',backup_manifest(stage,files))
   save(stage/'UPLOAD_OUTBOX.json',{'manifest_path':'BACKUP_MANIFEST.json','path_base':'THIS_VERSION_DIRECTORY','manifest_sha256':sha(stage/'BACKUP_MANIFEST.json'),'status':'PENDING_EXPLICIT_UPLOADER_AND_REMOTE_READBACK','upload_executed':False})
  if publish:
   promote(out,stage,receipt);stage=final
  return receipt|{'version_path':str(stage),'current_pointer_unchanged':not publish}

def query_snapshot(out,symbol,asof):
 """Consumer boundary: only published immutable snapshots; dynamic all-date policy enforced."""
 if not re.fullmatch(r'\d{6}\.(SH|SZ)',symbol):raise ValueError('INVALID_SYMBOL')
 asof=int(date_ok(asof));out=safe_output(out);live=load(PROJECT/'cache/READ_INVALIDATIONS.json')
 answer={'symbol':symbol,'asof':asof,'row':None,'PIT':False,'qualification':QUALIFICATION,'research_consumption_allowed':False}
 if symbol in live['securities']:return answer|{'status':live['securities'][symbol]['status'],'invalidation':live['securities'][symbol]}
 pointer=load(out/'CURRENT.json');version=safe_output(out/pointer['version'])
 if not version.is_relative_to(out/'versions'):raise ValueError('UNSAFE_CURRENT_POINTER')
 if sha(version/'RECEIPT.json')!=pointer['receipt_sha256']:raise ValueError('PUBLISHED_RECEIPT_HASH')
 frozen=load(version/'READ_INVALIDATIONS.json')
 if symbol in frozen['securities']:return answer|{'status':'KNOWN_CORRECTION_REQUIRED'}
 receipt=load(version/'RECEIPT.json')
 if symbol not in receipt['scope']:return answer|{'status':'OUTSIDE_PUBLISHED_SCOPE'}
 stock=receipt['stocks'][symbol];check_files(version,stock['files'])
 result=json.loads(gzip.decompress((version/'stocks'/symbol/'formula.json.gz').read_bytes()))
 row=next((r for r in result['rows'] if r['trade_date']==asof),None)
 return answer|{'status':'CACHED_RESEARCH_CANDIDATE' if row else 'DATE_NOT_CACHED','row':row,'research_consumption_allowed':row is not None,'source_vintage':receipt['target_date'],'scope_is_all_A':False}


def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['dry-run','stage']);p.add_argument('--config',required=True);p.add_argument('--out',required=True);p.add_argument('--publish',action='store_true');a=p.parse_args()
 try:
  r=run(load(a.config),a.out,a.command,a.publish);print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['counts']['failed']==0 and not a.publish else (0 if r['publish_allowed'] else 2)
 except Exception as e:print(json.dumps({'status':'BLOCKED','error':type(e).__name__+': '+str(e),'previous_snapshot_preserved':True}));return 2
if __name__=='__main__':raise SystemExit(main())
