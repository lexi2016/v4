"""Offline 194 reconstruction adapter over the already accepted research engines.

No producer writes, market collection, model fitting or registry ownership.
Caller must supply the persisted input-preparation START event SHA.
"""
from __future__ import annotations
import argparse, csv, hashlib, html, importlib.util, json, math, os, re
import resource, sys, time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
STATE = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state')
DATA = STATE / 'data'
OUT = ROOT / 'research/a_share_v194_20261023/inputs'
OLD = ROOT / 'worktrees/week_two_model_comparison_20261023/research/week_two_model_comparison_20261023'
CONTRACT = ROOT / 'research/week_two_model_comparison_20261023/CONTRACT.json'
START_SHA = '3c423c8a537f73087ace7bd9fbe28fc436e58df6882f2b8328cc9a34706839f7'
TECH = ['tech_192','B1','B2','B3','BREAKOUT','BREAKOUT_DOJI','M2_MINUS','M2_PLUS','SINGLE_NEEDLE','THREE_QUARTER_YIN','BRICK_FANBAO']
SOURCES = ['source_fupan','source_stage7','source_research']
FLAGS = dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
EXPOSED = {'20261016','20261019','20261020','20261021','20261022'}

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def writecsv(p,rows,fields):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def module(p,n):
    spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);sys.modules[n]=m;spec.loader.exec_module(m);return m
def iso(d):return d[:4]+'-'+d[4:6]+'-'+d[6:]
def aware(s):
    t=datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('TIMEZONE_UNPROVEN')
    return t
def norm(s):return re.sub(r'\s+','',html.unescape(re.sub(r'<[^>]*>','',str(s or ''))))
def full_text_bound(raw,content):
    text=norm(raw)
    return bool(text) and text in norm(content)
def status_binding(auth):
    fetched,status,measured_sha,historical_declared=auth
    return fetched,status,str(status['status_path']),measured_sha,historical_declared
def keycode(v):
    s=str(v or '').strip().upper();m=re.fullmatch(r'(?:A\.|SH\.|SZ\.|BJ\.)?(\d{6})(?:\.(SH|SZ|BJ))?',s)
    return m.group(1) if m else None

def start_gate(s):
    if s!=START_SHA:raise ValueError('INPUT_START_SHA_REQUIRED')
    found=False
    with (ROOT/'contracts/EXPERIMENT_REGISTRY.jsonl').open() as f:
        for line in f:
            e=json.loads(line)
            if e.get('event_sha256')==s:
                found=e.get('event_type')=='RUN_STARTED' and e.get('execution_id')=='A_SHARE_V194_SOURCE_RESONANCE_R1_20261023_INPUT_PREPARATION_V2_01'
                break
    if not found:raise ValueError('PERSISTED_INPUT_START_NOT_FOUND')

def freeze_date_policy(calendar, candidate_keys, truth_keys, expected_eligible_dates=None):
    """Exclude whole dates with unknown retained-candidate labels; keep all rows."""
    missing=Counter(dt for dt,code in set(candidate_keys)-set(truth_keys))
    counts=Counter(dt for dt,code in candidate_keys);result=[]
    for original in calendar:
        r=dict(original);dt=r['target_date'];unknown=missing[dt]
        r.update(candidate_rows=counts[dt],unknown_candidate_label_rows=unknown,
                 training_eligible=False,eligibility_exclusion_reason='')
        if r['cohort_role']=='unlabelled_prediction':r['eligibility_exclusion_reason']='UNLABELLED_TARGET_DATE'
        elif dt.replace('-','') in EXPOSED or r['cohort_role']=='diagnostic':
            r['cohort_role']='diagnostic';r['eligibility_exclusion_reason']='EXPOSED_DIAGNOSTIC_ONLY'+(';INCOMPLETE_CANDIDATE_TRUTH' if unknown else '')
        elif unknown:
            r['cohort_role']='excluded_incomplete_truth';r['eligibility_exclusion_reason']='INCOMPLETE_CANDIDATE_TRUTH_WHOLE_DATE_EXCLUDED'
        else:r['cohort_role']='eligible';r['training_eligible']=True
        result.append(r)
    eligible=sorted(r['target_date'] for r in result if r['training_eligible'])
    if expected_eligible_dates is not None and eligible!=expected_eligible_dates:raise ValueError('REVIEWER_FROZEN_DATE_ARRAY_MISMATCH')
    cut=len(eligible)//2;train=eligible[:cut];oof=eligible[cut:]
    policy=dict(schema='V194_COMPLETE_CANDIDATE_LABEL_DATE_POLICY_V1',
        completeness_scope='RETAINED_CANDIDATE_LABEL_KEYS_ONLY_NOT_ALL5533_PRICE_CERTIFICATION',
        eligible_target_dates=eligible,initial_train_target_dates=train,oof_target_dates=oof,
        oof_date_folds=[oof[i:i+5] for i in range(0,len(oof),5)],
        all_incomplete_target_dates=sorted(r['target_date'] for r in result if r['unknown_candidate_label_rows'] and r['cohort_role']!='unlabelled_prediction'),
        excluded_incomplete_target_dates=sorted(r['target_date'] for r in result if r['cohort_role']=='excluded_incomplete_truth'),
        exclusions=[dict(target_date=r['target_date'],reason=r['eligibility_exclusion_reason'],unknown_candidate_label_rows=r['unknown_candidate_label_rows'],training_eligible=False) for r in result if r['cohort_role']=='excluded_incomplete_truth'],
        diagnostic_target_dates=sorted(r['target_date'] for r in result if r['cohort_role']=='diagnostic'),
        unlabelled_target_dates=sorted(r['target_date'] for r in result if r['cohort_role']=='unlabelled_prediction'),
        minimum_total_eligible_dates=20,minimum_oof_dates_for_effect_pass=20,
        total_date_gate_met=len(eligible)>=20,effect_date_gate_met=len(oof)>=20,
        effect_acceptance_ceiling='DIRECTION_ONLY' if len(oof)>=20 else 'CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES',
        candidate_row_policy='KEEP_ALL_ORIGINAL_CANDIDATES_AND_UNKNOWN_LABEL_ROWS_NO_INDIVIDUAL_FUTURE_RESULT_SELECTION',
        target_volume_label_gate=False,**FLAGS)
    return result,policy

def materialize_date_policy():
    """Apply the two reviewed metadata fixes while reusing accepted bytes."""
    import copy
    oldpath=OUT/'MANIFEST_V3_PRICE_CLARIFIED.json';old=load(oldpath)
    def read(name):
        with Path(old['files'][name]['path']).open() as f:return list(csv.DictReader(f))
    candidates=read('candidates');truth=read('truth');calendar=read('calendar')
    verdictpath=ROOT/'research/a_share_v194_20261023/INPUT_V3_SEMANTIC_VERDICT.json';verdict=load(verdictpath)
    expected=next(r['complete_candidate_label_eligible_dates'] for r in verdict['required_fixes'] if r['id']=='V194-DATA-P1-002')
    revised,policy=freeze_date_policy(calendar,[(r['target_date'],r['code']) for r in candidates],{(r['target_date'],r['code']) for r in truth},expected)
    for name in ('candidates','truth'):
        assert sha(old['files'][name]['path'])==old['files'][name]['sha256'],'ACCEPTED_BYTES_DRIFT'
    policy.update(reused_input_manifest=dict(path=str(oldpath),sha256=sha(oldpath)),review_verdict=dict(path=str(verdictpath),sha256=sha(verdictpath)),volume_impact_audit=dict(path=str(OUT/'VOLUME_GATE_IMPACT_AUDIT.json'),sha256=sha(OUT/'VOLUME_GATE_IMPACT_AUDIT.json')))
    cp=OUT/'calendar_V4_COMPLETE_DATES_FINAL.csv';pp=OUT/'DATE_POLICY_V4_FINAL.json'
    writecsv(cp,revised,list(revised[0]));save(pp,policy)
    coverage=read('coverage');by={r['target_date']:r for r in revised};cover=[]
    for original in coverage:
        r=dict(original);r.update({k:by[r['target_date']][k] for k in ('cohort_role','unknown_candidate_label_rows','training_eligible','eligibility_exclusion_reason')});cover.append(r)
    covpath=OUT/'coverage_V4_COMPLETE_DATES_FINAL.csv';writecsv(covpath,cover,list(cover[0]))
    dictionary=load(old['files']['dictionary']['path']);dictionary.update(target_volume_label_gate=False,label_eligibility='Exact previous/target price keys and supported event-adjusted close ratio; no future target-volume eligibility filter',date_eligibility_policy=dict(path=str(pp),sha256=sha(pp)),candidate_label_gap_policy='Preserve95unknown rows; exclude complete target dates from train/OOF/refit; no0fill or individual-row deletion')
    dp=OUT/'DATA_DICTIONARY_V4_COMPLETE_DATES_FINAL.json';save(dp,dictionary)
    m=copy.deepcopy(old);m.update(previous_manifest=dict(path=str(oldpath),sha256=sha(oldpath)),policy_revision='V4_TWO_REVIEWED_MINIMAL_FIXES',eligible_dates=len(policy['eligible_target_dates']),eligible_target_dates=policy['eligible_target_dates'],initial_train_target_dates=policy['initial_train_target_dates'],oof_target_dates=policy['oof_target_dates'],excluded_incomplete_target_dates=policy['excluded_incomplete_target_dates'],all_incomplete_target_dates=policy['all_incomplete_target_dates'],target_volume_label_gate=False,label_definition='close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1; same-source same-target-D-anchor adjusted closes; Top100 return descending code ascending; exact previous session; target volume is not a label gate',lineage_review_pass=False,incremental_lineage_review_required=True,reused_content_verdict=dict(path=str(verdictpath),sha256=sha(verdictpath)),effect_acceptance_ceiling=policy['effect_acceptance_ceiling'],candidate_values_changed=False,truth_values_changed=False,semantic_ready=policy['total_date_gate_met'])
    m.update(exclusions=policy['exclusions'],clarification_only=False,date_eligibility_changed=True,incomplete_target_date_count=len(policy['all_incomplete_target_dates']),incomplete_diagnostic_target_dates=[r['target_date'] for r in revised if r['cohort_role']=='diagnostic' and r['unknown_candidate_label_rows']],source_coverage_reused_from_review=verdict['training_feasibility_after_fixes'])
    for name,path in [('calendar',cp),('coverage',covpath),('dictionary',dp),('date_policy',pp)]:m['files'][name]=dict(path=str(path),sha256=sha(path))
    m['files']['unknown_candidate_labels']=dict(path=str(OUT/'MISSING95_LABEL_COVERAGE.csv'),sha256=sha(OUT/'MISSING95_LABEL_COVERAGE.csv'))
    m['source_code_sha256'][str(Path(__file__))]=sha(__file__);m['input_sha256']=digest(m['files'])
    mp=OUT/'MANIFEST_V4_COMPLETE_DATES_FINAL.json';save(mp,m)
    receipt=dict(schema='V194_TWO_FIXES_WRITER_HANDOFF',manifest=dict(path=str(mp),sha256=sha(mp)),date_policy=dict(path=str(pp),sha256=sha(pp)),calendar=dict(path=str(cp),sha256=sha(cp)),dictionary=dict(path=str(dp),sha256=sha(dp)),adapter_sha256=sha(__file__),tests_sha256=sha(Path(__file__).with_name('test_data194.py')),eligible_dates=len(policy['eligible_target_dates']),initial_train_dates=len(policy['initial_train_target_dates']),oof_dates=len(policy['oof_target_dates']),all_incomplete_dates=len(policy['all_incomplete_target_dates']),excluded_formerly_eligible_dates=len(policy['excluded_incomplete_target_dates']),candidate_unchanged_sha256=m['files']['candidates']['sha256'],truth_unchanged_sha256=m['files']['truth']['sha256'],candidate_rows=len(candidates),unknown_historical_candidate_rows=sum(r['unknown_candidate_label_rows'] for r in revised if r['cohort_role']!='unlabelled_prediction'),unlabelled_prediction_candidate_rows=sum(r['unknown_candidate_label_rows'] for r in revised if r['cohort_role']=='unlabelled_prediction'),effect_acceptance_ceiling=policy['effect_acceptance_ceiling'],new_technical_formula_evaluations=0,new_label_computations=0,new_fit_count=0,**FLAGS)
    save(OUT/'TWO_FIXES_V4_FINAL_WRITER_RECEIPT.json',receipt);return receipt

def engines():
    if str(OLD) not in sys.path:sys.path.insert(0,str(OLD))
    import engine
    c=load(CONTRACT);b=c['input_identity']
    a=module(b['model_a'],'v194_original');k=module(b['model_b'],'v194_ten')
    assert list(k.RULES)==TECH[1:]
    return engine,c,a,k,a.compile_original(b['formula_a'])

def source_materialize():
    """Record historical V192 receipt chains and source hits, never infer absences."""
    refs={};hits=defaultdict(dict);issues=[];v192=[];slotrows=[];evidence=[]
    shared=STATE/'workspace/v3_shared_data/.runtime/data'
    for p in sorted((DATA/'preselection_pools').glob('20*/a_d1_premarket_pool.json')):
        x=load(p);d=x['trade_date'];record=dict(target_date=d,cache_path=str(p),cache_sha256=sha(p))
        try:
            ap=shared/x['source_path'];mp=ap.parent/'manifest.json';rp=ap.parent/'receipt.json';m=load(mp);r=load(rp)
            times=[aware(m['captured_at']),aware(r['started_at']),aware(r['finished_at'])]
            valid=(sha(ap)==x['source_sha256']==m['artifact_sha256']==r['artifact_sha256'] and digest(m)==r['manifest_sha256'] and r['status']=='READY' and max(times)<=aware(iso(d)+'T09:25:00+08:00'))
            record.update(valid=valid,artifact_path=str(ap),artifact_sha256=sha(ap),manifest_sha256=sha(mp),receipt_sha256=sha(rp),available_at=max(times).isoformat(),reason=None if valid else 'IDENTITY_OR_LATE')
        except Exception as e:record.update(valid=False,reason=type(e).__name__+':'+str(e))
        v192.append(record)
    for lane,pool in [('fupan','a_d1_fupan_watchlist_pool'),('stage7','a_d1_stage7_fenshi_review_pool')]:
        for p in sorted((DATA/'preselection_pools').glob('20*/'+pool+'.json')):
            x=load(p);d=x['trade_date'];ref=dict(target_date=d,lane=lane,path=str(p),sha256=sha(p))
            try:
                parts=x.get('source_path','').split('|')
                if len(parts)!=2:raise ValueError('LEGACY_SOURCE_PATH_NO_BOUND_MANIFEST_CSV')
                mp,cp=map(Path,parts);m=load(mp);at=aware(m['generated_at']);cut=aware(iso(d)+'T09:25:00+08:00')
                if hashlib.sha256((sha(mp)+sha(cp)).encode()).hexdigest()!=x['source_sha256']:raise ValueError('SOURCE_SHA_MISMATCH')
                if at>cut:raise ValueError('LATE_SOURCE')
                if m['target_date']!=d or m['row_count']!=len(x['rows']):raise ValueError('SOURCE_ROWS_DATE_MISMATCH')
                ref.update(manifest_path=str(mp),manifest_sha256=sha(mp),csv_path=str(cp),csv_sha256=sha(cp),available_at=at.isoformat(),status='VALID_HITS_PARTIAL_COVERAGE')
                for row in x['rows']:
                    code=keycode(row.get('symbol') or row.get('stock_code'))
                    if code:hits[(d,code)][lane]=dict(available_at=at.isoformat(),evidence_ref=digest(ref))
            except Exception as e:ref.update(status='EXCLUDED',reason=str(e))
            evidence.append(ref)
    sys.path.insert(0,'/Users/lexi/Desktop/学习/v4_app')
    from infrastructure.research_lane_source import ResearchLaneSource
    verifier=object.__new__(ResearchLaneSource);verifier.data_root=DATA
    # Dedup original topic identity within each target date, across all bound slots.
    dedup={}
    for p in sorted((DATA/'research/hourly/live').glob('20*/*.json')):
        if p.stem not in {'0700','0800','0830','0900'}:continue
        d=p.parent.name
        if not '20260730'<=d<='20261023':continue
        ref=dict(target_date=d,slot=p.stem,archive_path=str(p),archive_sha256=sha(p))
        try:
            archive=load(p);source=verifier._bound_source_input(archive,slot=p.stem)
            if not source:raise ValueError('SOURCE_UNBOUND')
            auth=verifier._bound_zsxq_status(source,archive_date=d,slot=p.stem)
            if not auth:raise ValueError('STATUS_UNVERIFIED')
            fetched,status,statuspath,statussha,historical_declared=status_binding(auth);fetch=aware(fetched);cut=aware(iso(d)+'T09:25:00+08:00')
            if fetch>cut:raise ValueError('FETCH_AFTER_DECISION')
            tp=DATA/status['paths']['run_dir']/'zsxq_recent_topics.json';topicpayload=load(tp)
            topics={str(t['topic_id']):t for t in topicpayload['topics_brief']}
            ref.update(incoming_path=str(DATA/'research/incoming'/d/(p.stem+'.json')),incoming_sha256=archive['source_input_sha256'],topics_path=str(tp),topics_sha256=sha(tp),status_path=str(statuspath),status_sha256=statussha,historical_receipt_sha_declared=historical_declared,status='BOUND_PUBLICATION_RECONSTRUCTION')
            for raw in source.get('raw_items',[]):
                if raw.get('source_type')!='zsxq':continue
                nested=raw.get('raw_payload') or {};tid=str(nested.get('topic_id') or '');t=topics.get(tid);code=keycode(nested.get('stock_code'));name=str(nested.get('stock_name') or '').strip()
                row=dict(target_date=d,slot=p.stem,topic_id=tid,code=code,name=name,evidence_ref=digest(ref))
                try:
                    if not t:raise ValueError('TOPIC_NOT_FOUND')
                    pub=aware(t['create_time']);claimed=aware(raw['published_at']);modified=aware(t['modify_time']) if t.get('modify_time') else pub
                    times=[pub,modified,fetch]
                    for obj in (raw,nested):
                        for field in ('crawl_time','first_seen_at','last_checked_at'):
                            if obj.get(field):times.append(aware(obj[field]))
                    if pub.replace(microsecond=0)!=claimed.replace(microsecond=0):raise ValueError('PUBLICATION_MISMATCH')
                    if pub>fetch or modified>fetch or max(times)>cut:raise ValueError('SOURCE_TIME_CONFLICT_OR_LATE')
                    content=str(t.get('content') or '');normalized=norm(content);rawnorm=norm(raw.get('raw_text'))
                    if not full_text_bound(raw.get('raw_text'),content):raise ValueError('FULL_RAW_TEXT_NOT_IN_ORIGINAL_CONTENT')
                    if not code or not (re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',content) or (len(name)>=2 and name in content)):raise ValueError('ENTITY_NOT_LITERAL_IN_FULL_CONTENT')
                    # Keep every full original body locally; no titles or current article backfill.
                    body=OUT/'source_content'/('topic_'+tid+'_'+hashlib.sha256(content.encode()).hexdigest()+'.txt')
                    if not body.exists():body.parent.mkdir(exist_ok=True,parents=True);body.write_text(content)
                    row.update(status='VALID',available_at=max(times).isoformat(),content_path=str(body),content_sha256=sha(body),normalized_content_sha256=hashlib.sha256(normalized.encode()).hexdigest(),full_raw_text_sha256=hashlib.sha256(str(raw.get('raw_text')).encode()).hexdigest(),parity='ENTIRE_NORMALIZED_RAW_TEXT_SUBSTRING_OF_ORIGINAL_FULL_CONTENT',historical_receipt_sha_declared=historical_declared)
                    identity=(d,tid,code)
                    if identity not in dedup or aware(row['available_at'])<aware(dedup[identity]['available_at']):dedup[identity]=row
                except Exception as e:row.update(status='EXCLUDED',reason=str(e));issues.append(row)
            slotrows.append(ref)
        except Exception as e:ref.update(status='EXCLUDED',reason=str(e));slotrows.append(ref)
    for (d,tid,code),row in sorted(dedup.items()):
        old=hits[(d,code)].get('research')
        if old is None:hits[(d,code)]['research']=dict(available_at=row['available_at'],evidence_ref=digest(row),topic_ids=[tid])
        else:old['topic_ids'].append(tid);old['available_at']=max(old['available_at'],row['available_at'])
    save(OUT/'V192_RECEIPT_BINDINGS.json',v192);save(OUT/'SOURCE_POOL_BINDINGS.json',evidence);save(OUT/'RESEARCH_SLOT_BINDINGS.json',slotrows);save(OUT/'SOURCE_EXCLUSIONS.json',issues);save(OUT/'TOPIC_ENTITY_BINDINGS.json',list(dedup.values()))
    serial=[dict(target_date=d,code=code,lanes=lanes) for (d,code),lanes in sorted(hits.items())]
    save(OUT/'SOURCE_HITS.json',serial)
    return dict(v192_valid_dates=[r['target_date'] for r in v192 if r['valid']],source_hit_keys=len(hits),distinct_date_topic_count=len({(d,t) for d,t,c in dedup}),topic_entity_keys=len(dedup),source_exclusion_count=len(issues),source_states_policy='HIT_IF_VALID_BOUND_RECORD_ELSE_UNKNOWN_NO_CONFIRMED_ABSENCE',**FLAGS)

def compute_stock(task):
    """Original per-date engines, full source warmup, no truth in feature arrays."""
    code,spec,original,native,c56,b,reuse,calendar=task
    import numpy as np
    engine,c,a,k,program=engines();result=[];truth=[];excluded=[]
    try:
        if spec['status'] not in {'READY','READY_WITH_ROUTE_LEVEL_MISSING_FIELDS'}:raise ValueError('SOURCE_UNKNOWN:'+str(spec.get('reason')))
        dates,raw,ev,unsupported,provenance=engine.reconstruct(code,spec,original,native,c56)
    except Exception as e:
        return dict(code=code,features=[],truth=[],exclusions=[dict(code=code,target_date=t,reason='RECONSTRUCT:'+str(e)) for s,t in calendar],binding=None)
    binding=dict(code=code,raw_sha256=digest({'dates':dates,'raw':{f:v.tolist() for f,v in raw.items()}}),events_sha256=digest(ev),provenance=provenance,history_start=dates[0],history_end=dates[-1],history_rows=len(dates))
    # Evaluate once per source-effective event regime. Original interpreters are
    # causal (nonnegative REF/rolling/EMA); canary compares exact per-day calls.
    groups=defaultdict(list)
    for signal,target in calendar:
        if signal in dates:groups[tuple(e['date'] for e in ev if e['date']<=signal)].append((signal,target))
        else:excluded.append(dict(code=code,target_date=target,reason='EXACT_SIGNAL_BAR_MISSING'))
    for regime,pairs in groups.items():
        end=max(s for s,t in pairs);n=dates.index(end)+1;dd=dates[:n];rr={f:raw[f][:n] for f in engine.FIELDS};ee=[e for e in ev if e['date']<=end];q=engine.project(dd,rr,ee,end)
        av=None;ke=None
        try:av=a.evaluate(program,{v:q[f] for v,f in [('O','open'),('H','high'),('L','low'),('C','close'),('VOL','volume'),('AMOUNT','amount')]},code)['XG']
        except Exception:pass
        try:
            columns={v:q[f].copy() for v,f in [('C','close'),('H','high'),('L','low'),('VOL','volume')]}
            for field,x in columns.items():x[(~np.isfinite(x))|(x<0 if field=='VOL' else x<=0)]=np.nan
            bad=np.isfinite(columns['C'])&np.isfinite(columns['H'])&np.isfinite(columns['L'])&((columns['H']<columns['C'])|(columns['L']>columns['C'])|(columns['H']<columns['L']))
            for field in ['C','H','L']:columns[field][bad]=np.nan
            ke=k.Engine(columns);kv={rid:ke.named(name) for rid,name in k.RULES.items() if rid!='BRICK_FANBAO'}
        except Exception:ke=None
        for signal,target in pairs:
            i=dates.index(signal);row=dict(target_date=target,signal_date=signal,code=code,name=spec.get('name',''),technical_evidence_ref=digest(binding),history_rows=i+1,history_start=dates[0]);flags={}
            why=None
            if any(dates[0]<d<=signal for d in unsupported):why='UNSUPPORTED_SPLIT_EVENT'
            elif av is None or ke is None or not np.isfinite(av[i]):why='TECHNICAL_192_OR_ENGINE_UNAVAILABLE'
            else:
                flags['tech_192']=int(av[i]!=0)
                for rid in k.RULES:
                    if rid=='BRICK_FANBAO':
                        if i+1<14 or not all(np.isfinite(columns[z][:i+1]).all() for z in ['C','H','L']):why='BRICK_HISTORY_UNAVAILABLE';break
                        env=k.brick_functions();bars=[k.SimpleNamespace(close=x,high=y,low=z) for x,y,z in zip(columns['C'][:i+1],columns['H'][:i+1],columns['L'][:i+1])];flags[rid]=int(env['detect_fanbao'](bars))
                    elif not np.isfinite(kv[rid][i]):why='TECHNICAL_ROUTE_UNAVAILABLE:'+rid;break
                    else:flags[rid]=int(kv[rid][i]!=0)
            if why:excluded.append(dict(code=code,target_date=target,reason=why))
            else:result.append({**row,**flags})
    # Truth is independent of candidates and includes every rankable research key.
    for signal,target in calendar:
        if signal not in dates or target not in dates:continue
        j=dates.index(signal);i=dates.index(target)
        if i!=j+1 or any(signal<d<=target for d in unsupported):continue
        ref=float(raw['close'][j])
        for e in ev:
            if signal<e['date']<=target:ref=ref*e['A']+e['B']
        ret=float(raw['close'][i])/ref-1 if ref>0 else float('nan')
        if math.isfinite(ret):truth.append(dict(target_date=target,code=code,**{'return':ret},raw_close=float(raw['close'][i]),reference_close=ref,binding_ref=digest(binding)))
    return dict(code=code,features=result,truth=truth,exclusions=excluded,binding=binding)

def prepare_tasks(codes=None):
    engine,c,a,k,program=engines();b=c['input_identity'];manifest=load(b['manifest']);statuses={r['code']:r for r in manifest['all_input_statuses']}
    import pyarrow.dataset as ds
    # FAST_BIND is inherited from accepted full-SHA plus unchanged identity stat.
    st=Path(b['raw_selector']['path']).stat();expected=b['raw_selector']['stat']
    assert (st.st_ino,st.st_mtime_ns,st.st_size)==(expected['inode'],expected['mtime_ns'],expected['size_bytes']),'RAW_SELECTOR_FAST_BIND_DRIFT'
    allcodes=sorted(statuses);wanted=allcodes if codes is None else codes
    frame=ds.dataset(b['raw_selector']['path'],format='parquet').scanner(columns=['ts_code','trade_date',*engine.FIELDS],filter=ds.field('ts_code').isin(wanted)&(ds.field('trade_date')<='20261022'),use_threads=False).to_table().to_pandas()
    # Existing research-panel sessions, not a fabricated weekday or official calendar.
    sessions=sorted(set(frame['trade_date'].astype(str)))
    calendar=[(sessions[i-1],d) for i,d in enumerate(sessions) if i and '20260730'<=d<='20261022']
    # D23 can be predicted from D22 but has no bound target truth and is separate.
    calendar.append(('20261022','20261023'))
    native=load(b['native_refs']);c56=load(engine.w.R/'event_aware_input_canary_56/CONTRACT.json');reuse={r['code']:r for r in map(json.loads,Path(b['reuse_b_D23']).read_text().splitlines())};groups=frame.groupby('ts_code',sort=False)
    tasks=[(code,statuses[code],groups.get_group(code).to_dict('records') if code in groups.groups else [],{code:native[code]} if code in native else {},c56,b,reuse[code],calendar) for code in wanted]
    return tasks,calendar,c

def run_technical(phase):
    start=time.monotonic();out=OUT/phase;out.mkdir(exist_ok=True,parents=True)
    codes=['000001.SZ','002335.SZ'] if phase=='canary' else None
    tasks,calendar,c=prepare_tasks(codes)
    if phase=='canary':tasks=[t[:-1]+([t[-1][0],t[-1][-1]],) for t in tasks]
    # Fixed two workers, immutable per-stock checkpoints, no duplicate work.
    pending=[t for t in tasks if not (out/(t[0]+'.json')).exists()]
    import multiprocessing
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        for r in pool.map(compute_stock,pending,chunksize=1):
            save(out/(r['code']+'.json'),r)
            if len(list(out.glob('*.SZ.json')))%100==0:print(json.dumps(dict(phase=phase,last_code=r['code'],elapsed=time.monotonic()-start)),flush=True)
    receipt=dict(phase=phase,codes=len(tasks),calendar_dates=len(calendar),elapsed_seconds=time.monotonic()-start,workers=2,parent_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**FLAGS)
    if phase=='canary':
        engine,c,a,k,program=engines();parity=[]
        for t in tasks:
            code,spec,original,native,c56,b,reuse,pairs=t;dates,raw,ev,unsupported,p=engine.reconstruct(code,spec,original,native,c56);r=load(out/(code+'.json'));by={x['target_date']:x for x in r['features']}
            for signal,target in pairs:
                n=dates.index(signal)+1;q=engine.project(dates[:n],{f:raw[f][:n] for f in engine.FIELDS},[e for e in ev if e['date']<=signal],signal)
                av=a.evaluate(program,{v:q[f] for v,f in [('O','open'),('H','high'),('L','low'),('C','close'),('VOL','volume'),('AMOUNT','amount')]},code)['XG'][-1];kb=k.evaluate_stock(code,dates[:n],{v:q[f] for v,f in [('C','close'),('H','high'),('L','low'),('VOL','volume')]},signal_date=signal)
                expected={'tech_192':int(av!=0),**{z['rule_id']:int(z['value']) for z in kb['rules'] if z['value'] is not None}}
                if target not in by or len(expected)!=11:raise ValueError('CANARY_INCOMPLETE_TECHNICAL_ROW')
                assert {f:by[target][f] for f in TECH}==expected,'REGIME_VECTORIZATION_PARITY_FAIL'
                parity.append(dict(code=code,target_date=target,flags=expected,status='EXACT_11_FLAG_PARITY'))
        receipt['per_day_original_engine_parity']=parity
    save(out/'RECEIPT.json',receipt);return receipt

def assemble():
    raw=[load(p) for p in sorted((OUT/'full').glob('*.json')) if p.name!='RECEIPT.json'];sources={(r['target_date'],r['code']):r['lanes'] for r in load(OUT/'SOURCE_HITS.json')};features=[];truth=[];exclusions=[];bindings=[]
    for r in raw:features.extend(r['features']);truth.extend(r['truth']);exclusions.extend(r['exclusions']);bindings.extend([r['binding']] if r['binding'] else [])
    dates=sorted({r['target_date'] for r in features}|{r['target_date'] for r in truth});ranked={};calendar=[]
    for d in dates:
        rows=sorted([r for r in truth if r['target_date']==d],key=lambda r:(-r['return'],r['code']));denom=min(100,len(rows));ranked[d]={r['code']:i for i,r in enumerate(rows,1)}
        for i,r in enumerate(rows,1):r.update(label=int(i<=100),label_end_at=iso(d)+'T15:00:00+08:00',label_available_at=iso(d)+'T15:00:00+08:00',label_maturity_basis='ECONOMIC_SESSION_CLOSE_RECONSTRUCTION_NOT_HISTORICAL_CAPTURE')
        calendar.append(dict(target_date=iso(d),signal_date=iso(next(r['signal_date'] for r in features if r['target_date']==d)),truth_positive_denominator=denom if rows else None,rankable_research_rows=len(rows),research_pool_size=len(raw),cohort_role='unlabelled_prediction' if not rows else 'diagnostic' if d in EXPOSED else 'eligible',label_available_at=iso(d)+'T15:00:00+08:00' if rows else None))
    candidates=[];technical_missing=len(exclusions)
    for r in features:
        d=r['target_date'];code=keycode(r['code']);lanes=sources.get((d,code),{});reasons=[f for f in TECH if r[f]]+[lane for lane in ('fupan','stage7','research') if lane in lanes]
        if not reasons:continue
        avail=[iso(r['signal_date'])+'T15:00:00+08:00']+[v['available_at'] for v in lanes.values()]
        available=max(avail,key=aware)
        assert aware(available)<=aware(iso(d)+'T09:25:00+08:00'),'LATE_CANDIDATE_DEPENDENCY'
        candidates.append(dict(target_date=iso(d),signal_date=iso(r['signal_date']),code=r['code'],decision_at=iso(d)+'T09:25:00+08:00',available_at=available,**{f:r[f] for f in TECH},**{'source_'+lane:'hit' if lane in lanes else 'unknown' for lane in ('fupan','stage7','research')},candidate_reasons='|'.join(reasons),evidence_refs=json.dumps(dict(technical=r['technical_evidence_ref'],sources=lanes),ensure_ascii=False,separators=(',',':'))))
    for r in truth:r['target_date']=iso(r['target_date'])
    candidates.sort(key=lambda r:(r['target_date'],r['code']));truth.sort(key=lambda r:(r['target_date'],r['code']))
    calendar,date_policy=freeze_date_policy(calendar,[(r['target_date'],r['code']) for r in candidates],{(r['target_date'],r['code']) for r in truth})
    save(OUT/'DATE_POLICY.json',date_policy)
    writecsv(OUT/'candidate.csv',candidates,['target_date','signal_date','code','decision_at','available_at',*TECH,*SOURCES,'candidate_reasons','evidence_refs'])
    writecsv(OUT/'truth.csv',truth,['target_date','code','return','raw_close','reference_close','binding_ref','label','label_end_at','label_available_at','label_maturity_basis'])
    writecsv(OUT/'calendar.csv',calendar,list(calendar[0]));save(OUT/'TECHNICAL_EXCLUSIONS.json',exclusions);save(OUT/'RAW_BINDINGS.json',bindings)
    coverage=[]
    for r in calendar:
        d=r['target_date'];cs=[x for x in candidates if x['target_date']==d];fcount=sum(iso(x['target_date'])==d for x in features)
        entry=dict(r);entry.update(technical_complete_rows=fcount,technical_missing_rows=len(raw)-fcount,candidate_rows=len(cs),candidate_labelled_rows=sum(x['code'] in ranked.get(d.replace('-',''),{}) for x in cs),**{lane+'_hit_rows':sum(x['source_'+lane]=='hit' for x in cs) for lane in ('fupan','stage7','research')},source_absence_confirmed_rows=0);coverage.append(entry)
    writecsv(OUT/'coverage.csv',coverage,list(coverage[0]))
    engine,c,a,k,program=engines();paths=[Path(__file__),CONTRACT,OLD/'engine.py',OLD/'weekly_compare.py',Path(c['input_identity']['model_a']),Path(c['input_identity']['formula_a']),Path(c['input_identity']['model_b']),k.HERE/'RULES.json',k.FORMULA,k.UPSTREAM/'core.py',k.UPSTREAM/'price_patterns/brick.py',k.UPSTREAM/'price_patterns/screener_helper.py']
    ruledefs=load(k.HERE/'RULES.json')
    definitions=[dict(column='tech_192',original_name='XG',definition_sha256=sha(c['input_identity']['formula_a']),definition='Original complete 255-assignment V192ORIG XG output')]+[dict(column=rid,original_name=name,definition_sha256=digest(next(z for z in ruledefs['rules'] if z['id']==rid)),definition=next(z for z in ruledefs['rules'] if z['id']==rid)) for rid,name in k.RULES.items()]
    save(OUT/'DATA_DICTIONARY.json',dict(row_key=['target_date','code'],technical_definitions=definitions,source_columns=SOURCES,source_states=['hit','confirmed_absent','unknown'],absence_policy='No confirmed absence in these incomplete source records',feature_time_basis='Previous session economic close and original aware source times; reconstruction timestamp is not historical capture',label_time_basis='Economic close maturity only, original collection timestamps unproven',label_price_series='close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1; both closes share the same target-D anchor, original source and original accepted unrounded event-affine adjustment',**FLAGS))
    files={name:dict(path=str(OUT/f),sha256=sha(OUT/f)) for name,f in [('candidates','candidate.csv'),('truth','truth.csv'),('calendar','calendar.csv'),('coverage','coverage.csv'),('dictionary','DATA_DICTIONARY.json'),('technical_exclusions','TECHNICAL_EXCLUSIONS.json'),('raw_bindings','RAW_BINDINGS.json'),('source_hits','SOURCE_HITS.json'),('source_topics','TOPIC_ENTITY_BINDINGS.json'),('source_slots','RESEARCH_SLOT_BINDINGS.json'),('source_pools','SOURCE_POOL_BINDINGS.json'),('v192_receipts','V192_RECEIPT_BINDINGS.json'),('source_exclusions','SOURCE_EXCLUSIONS.json')]}
    files['date_policy']=dict(path=str(OUT/'DATE_POLICY.json'),sha256=sha(OUT/'DATE_POLICY.json'))
    eligible=[r for r in calendar if r['cohort_role']=='eligible'];manifest=dict(schema='V194_DATASET_MANIFEST_V2',dataset_kind='SHARED_PRODUCER_DERIVED_VIEW',mode='PUBLICATION_TIME_RECONSTRUCTION',evidence_level='DIRECTION_ONLY',historical_availability_bound=False,historical_availability_reason='PRICE_AND_EVENT_HISTORICAL_VINTAGE_UNPROVEN_SOURCE_RECEIPT_SHA_UNDECLARED',semantic_ready=True,complete_ten_buy_points=True,feature_semantics_bound=True,label_maturity_bound=True,lineage_review_pass=False,design_review_pass=False,technical_features=TECH,source_state_columns=SOURCES,source_unknown='MASK_UNKNOWN_NEVER_CONFIRMED_ABSENT',files=files,calendar=[r['target_date'] for r in calendar],truth_positive_counts={r['target_date']:r['truth_positive_denominator'] for r in calendar},universe_scope='EXISTING_5533_RESEARCH_CODES_NOT_CERTIFIED_HISTORICAL_ALL_A',label_definition='Same-source RAW close / effective-event-adjusted previous market-session RAW close -1; Top100 return descending code ascending; exact prev-session keys',price_unit='INHERITED_ACCEPTED_SOURCE_NATIVE_CNY_PRICE_VOLUME_SOURCE_UNITS_AMOUNT_UNADJUSTED_NATIVE_CNY',warmup='COMPLETE_ACCEPTED_SOURCE_PREFIX_PER_STOCK_NO_TRUNCATION',producer_manifest_sha256=sha(c['input_identity']['manifest']),source_code_sha256={str(p):sha(p) for p in paths},candidate_rows=len(candidates),truth_rows=len(truth),eligible_dates=len(eligible),diagnostic_dates=sorted(iso(d) for d in EXPOSED),technical_exclusions=technical_missing,source_completeness='UNKNOWN_NO_ABSENCE_CERTIFICATION',label_maturity_limitation='Economic session-close reconstruction; actual historical collection timestamp not asserted',calendar_source='FULL_EXISTING_RESEARCH_PANEL_SESSION_KEYS',calendar_official_parity='CANNOT_CONFIRM',row_exclusion_policy='Missing any technical route excludes row and is reported; no false technical zero',start_event_sha256=START_SHA,**FLAGS)
    manifest.update(row_key=['target_date','code'],input_sha256=digest(files),config_sha256=sha(ROOT/'research/a_share_v194_20261023/INPUT_PREPARATION_V2_CONTRACT.json'),technical_definitions=definitions,active_v192_inventory=dict(path=str(OUT/'V192_ACTIVE_DATE_INVENTORY.json'),sha256=sha(OUT/'V192_ACTIVE_DATE_INVENTORY.json')),causal_regime_proof=dict(path=str(OUT/'CAUSAL_REGIME_PROOF.json'),sha256=sha(OUT/'CAUSAL_REGIME_PROOF.json')),full_technical_receipt=dict(path=str(OUT/'full/RECEIPT.json'),sha256=sha(OUT/'full/RECEIPT.json')))
    manifest.update(eligible_target_dates=[r['target_date'] for r in eligible],unlabelled_target_dates=[r['target_date'] for r in calendar if r['cohort_role']=='unlabelled_prediction'])
    manifest.update(initial_train_target_dates=date_policy['initial_train_target_dates'],oof_target_dates=date_policy['oof_target_dates'],excluded_incomplete_target_dates=date_policy['excluded_incomplete_target_dates'],all_incomplete_target_dates=date_policy['all_incomplete_target_dates'],target_volume_label_gate=False,effect_acceptance_ceiling=date_policy['effect_acceptance_ceiling'])
    manifest['exclusions']=date_policy['exclusions']
    manifest.update(label_definition='close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1; same-source same-target-D-anchor adjusted closes; Top100 return descending code ascending; exact previous session; target volume is not a label gate',label_equivalent_implementation='RAW close(D)/(RAW close(D-1) transformed only by original effective events with D-1<event_date<=D)-1; engine.project applies each affine transform only to bars strictly before its effective date',label_price_series_identity='ORIGINAL_ACCEPTED_WEEK_BENCHMARK_SAME_SOURCE_QFQ_ANCHOR_TARGET_D',label_historical_vintage='CANNOT_CONFIRM')
    manifest['semantic_ready']=bool(candidates) and len(eligible)>=20 and all(r['truth_positive_denominator']==100 for r in eligible)
    save(OUT/'MANIFEST.json',manifest);return {k:manifest[k] for k in ('candidate_rows','truth_rows','eligible_dates','technical_exclusions','semantic_ready')}

def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['sources','canary','full','assemble','date-policy']);p.add_argument('--start-event-sha',required=True);args=p.parse_args();start_gate(args.start_event_sha)
    if args.phase=='date-policy':r=materialize_date_policy()
    elif args.phase=='sources':r=source_materialize();save(OUT/'SOURCE_RECEIPT.json',r)
    elif args.phase in {'canary','full'}:r=run_technical(args.phase)
    else:r=assemble()
    print(json.dumps(r,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
