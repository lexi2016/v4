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
REPAIR = ROOT / 'research/a_share_v194_20261023/repair_r1_20261024'
REPAIR_OUT = REPAIR / 'inputs'
SOURCE_PACKET = ROOT / 'research/a_share_v194_20261023/diagnostics/source_effect_r1/source'
SOURCE_AUTHOR_SHA = 'fac18f24c3974764f525fd2898f46bc6189cd94cbaff064dbf667f95b7c53c2f'

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

def repair_start_gate(event_sha):
    """Require this repair START and its explicit DataWriter scope checkpoint."""
    events=[]
    with (ROOT/'contracts/EXPERIMENT_REGISTRY.jsonl').open() as f:
        for line in f:
            e=json.loads(line)
            if e.get('execution_id')=='A_SHARE_V194_SOURCE_RESONANCE_R1_20261023_DATA_BINDING_REPAIR_R1_20261024_01':events.append(e)
    assert any(e['event_sha256']==event_sha and e['event_type']=='RUN_STARTED' for e in events),'REPAIR_START_REQUIRED'
    assert any(e['event_sha256']=='0a2dd37286feb30e3517843ca7ba964e222638564acad97acf831c734fb3a8ca' for e in events),'DATAWRITER_SCOPE_CHECKPOINT_REQUIRED'
    assert sha(REPAIR/'DATAWRITER_SCOPE_ADDENDUM.json')=='c330cc1991571171b5af620cecca20e987b673d98462bf64637fffff0fe54ca1'

class RepairPacket:
    """Consume only the frozen diagnostic package; never search dispatchers."""
    def __init__(self):
        p=SOURCE_PACKET/'AUTHOR_RECEIPT.json';assert sha(p)==SOURCE_AUTHOR_SHA,'DIAGNOSTIC_AUTHOR_DRIFT'
        self.author=load(p);self.specs={Path(r['path']).name:r for r in self.author['artifact_manifest']};self.loaded={};self.verified={}
    def path(self,name):
        p=SOURCE_PACKET/name;expected=self.specs[name]['sha256']
        assert sha(p)==expected,'FROZEN_PACKET_DRIFT:'+name
        self.verified[str(p)]=expected;return p
    def get(self,name):
        if name not in self.loaded:
            p=self.path(name)
            if name.endswith('.gz'):
                import gzip
                self.loaded[name]=json.loads(gzip.decompress(p.read_bytes()))
            else:self.loaded[name]=load(p)
        return self.loaded[name]
    def resource_file(self,path,expected):
        p=Path(path)
        if not p.is_absolute():p=DATA/p
        if str(p) not in self.verified:
            assert expected and sha(p)==expected,'BOUND_ORIGINAL_RESOURCE_DRIFT:'+str(p)
            self.verified[str(p)]=expected
        else:assert self.verified[str(p)]==expected,'RESOURCE_SHA_CONFLICT'
        return p

def mapped_source_path(value):
    raw=str(value);path=raw.replace('\\','/')
    if re.match(r'^[A-Za-z]:/',path):
        if '/v3.5/.runtime/' in path:return STATE/path.split('/v3.5/.runtime/',1)[1]
        if '/学习/' in path:return ROOT.parent/path.split('/学习/',1)[1]
    p=Path(raw);return p if p.is_absolute() else DATA/p

def repaired_pool_binding(record,packet=None):
    """Parent actual UTC publication binds nonempty A bytes, independent of HK."""
    if not record.get('cache_rows'):return dict(state='unknown',reason='EMPTY_PLACEHOLDER_OR_CACHE_ABSENT')
    parent=record.get('earliest_preopen_exact_parent_receipt')
    if not parent or not record.get('cache_identity_ok'):return dict(state='unknown',reason='NO_EXACT_PREOPEN_PARENT_PUBLICATION')
    cut=aware(iso(record['target_date'])+'T09:25:00+08:00')
    if aware(parent['finished_at'])>cut:return dict(state='unknown',reason='PARENT_PUBLICATION_AFTER_DECISION')
    if parent['artifact_sha256']!=record['cache_canonical_sha256'] or parent.get('payload_trade_date')!=record['target_date']:return dict(state='unknown',reason='PARENT_ARTIFACT_IDENTITY_MISMATCH')
    if not record.get('mapped_source_sha_matches_cache'):return dict(state='unknown',reason='ORIGINAL_SOURCE_BYTES_NOT_BOUND')
    if packet:
        cache=load(packet.resource_file(record['cache_path'],record['cache_bytes_sha256']))
        assert digest(cache)==record['cache_canonical_sha256'],'CACHE_CANONICAL_DRIFT'
        packet.resource_file(record['cache_receipt_path'],record['cache_receipt_bytes_sha256'])
        packet.resource_file(parent['receipt_path'],parent['receipt_sha256'])
        mapped=record.get('mapped_source_paths',[])
        for ref in mapped:
            assert mapped_source_path(ref['original'])==Path(ref['local']),'LOCAL_PATH_MAPPING_PARITY'
            packet.resource_file(ref['local'],ref['sha256'])
    return dict(state='hit',available_at=parent['finished_at'],reason='EXACT_NONEMPTY_A_ARTIFACT_PREOPEN_PUBLICATION',parent_receipt=parent,
                historical_overall_status=parent.get('receipt_overall_status'),codes=record.get('valid_stock_codes_after_fieldwise_resolution',[]))

def research_record_gate(row,resource):
    """Reuse exact producer body/title proof; retain version and role axes."""
    cut=aware(iso(row['target_date'])+'T09:25:00+08:00')
    published=aware(row['published_at']);fetched=aware(resource['fetched_at']);modified=aware(row['modify_time']) if row.get('modify_time') else published
    available=aware(row['available_at'])
    if published>fetched or modified>fetched or max(published,modified,fetched,available)>cut:return 'SOURCE_TIME_CONFLICT_OR_LATE'
    if row['evidence_tier'] not in {'DECLARED_COLLECTOR_BYTES_EXACT_RECONSTRUCTION','UNDECLARED_COLLECTOR_COMPATIBILITY_ONLY'}:return 'UNRECOGNIZED_RECONSTRUCTION_TIER'
    if row['evidence_tier'].startswith('DECLARED') and not resource.get('historical_collector_source_sha256'):return 'DECLARED_VERSION_SHA_MISSING'
    if not re.fullmatch(r'\d{6}',row['code']):return 'ENTITY_CODE_UNCERTAIN'
    for field in ('original_full_body_sha256','raw_text_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}',str(resource.get(field) or '')):return 'ORIGINAL_BODY_OR_PRODUCER_PROOF_MISSING'
    # No subject eligibility or dated pool membership condition here.
    return None

def historical_compact(body,title,limit=5000):
    """Exact historical _compact definition, independently canaried against source."""
    return re.sub(r'\s+',' ', ' '.join(str(v or '') for v in (body,title))).strip()[:limit]

def verify_research_wrapper(row,resource,slot,packet):
    """Small canary only: replay original body plus company-bound title wrapper."""
    incoming=load(packet.resource_file(slot['incoming_path'],resource['incoming_sha256']))
    topics=load(packet.resource_file(resource['topics_path'],resource['topics_sha256']))
    summaries=load(packet.resource_file(resource['summary_path'],resource['summary_sha256']))
    topic=next(t for t in topics['topics_brief'] if str(t.get('topic_id') or t.get('id'))==row['topic_id'])
    summary=next(t for t in summaries['effective_topics'] if str(t['topic_id'])==row['topic_id'])
    body=str(topic.get('content') or topic.get('text') or topic.get('plain_text') or '')
    assert hashlib.sha256(body.encode()).hexdigest()==resource['original_full_body_sha256'],'ORIGINAL_BODY_DRIFT'
    assert re.search(r'(?<!\d)'+re.escape(row['code'])+r'(?!\d)',body) or len(row['name'])>=2 and row['name'] in body,'BODY_LITERAL_ENTITY_MISSING'
    raw=next(r for r in incoming['raw_items'] if hashlib.sha256(str(r.get('raw_text')).encode()).hexdigest()==resource['raw_text_sha256'] and str((r.get('raw_payload') or {}).get('stock_code'))==row['code'])
    nested=raw['raw_payload'];company=nested.get('source_report_binding')
    title=(('' if company.get('attachment_binding_status')=='NO_MATCH_UNCONFIRMED' else str(company.get('bound_source_title') or '')) if company is not None else str(summary.get('title') or summary.get('evidence') or '知识星球研报'))
    head=str(summary.get('content_head') or summary.get('evidence') or title);expected=historical_compact(head,title)
    assert str(nested['raw_text'])==expected and str(raw['raw_text'])==re.sub(r'\s+',' ',expected).strip()[:5000],'BODY_BOUND_TITLE_WRAPPER_PARITY'
    if resource.get('historical_collector_source_path'):
        import ast
        source=packet.resource_file(resource['historical_collector_source_path'],resource['historical_collector_source_sha256'])
        tree=ast.parse(source.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_compact');ns={'re':re,'Any':object}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns)
        assert ns['_compact'](head,title)==expected,'HISTORICAL_COMPACT_SOURCE_PARITY'
    return dict(target_date=row['target_date'],code=row['code'],topic_id=row['topic_id'],wrapper=resource['body_company_title_wrapper'],subject_eligible=row['original_research_subject_eligible'],tier=row['evidence_tier'],entire_wrapper_body_substring=full_text_bound(raw['raw_text'],body),producer_wrapper_parity=True,literal_entity=True)

def repair_canary():
    packet=RepairPacket();pool=packet.get('POOL_SOURCE_GATE_TRACE_V3.json');compact=packet.get('RESEARCH_RECOVERY_COMPACT.json.gz');rows=[dict(zip(compact['columns'],r)) for r in compact['rows']];slots={(r['target_date'],r['slot']):r for r in packet.get('RESEARCH_SLOT_GATES_V3.json')}
    checks=[]
    for lane in ('fupan','stage7'):
        record=next(r for r in pool if r['lane']==lane and r.get('membership_status')=='CONFIRMED_PREOPEN_MEMBERSHIP_FOR_VALID_MAPPED_ROWS')
        result=repaired_pool_binding(record,packet);assert result['state']=='hit';checks.append(dict(lane=lane,result=result['state'],overall_status=result['historical_overall_status']))
    legacy=next(r for r in pool if r['lane']=='fupan' and len((r.get('source_path') or '').split('|'))==1 and r.get('mapped_source_sha_matches_cache'))
    checks.append(dict(lane='legacy_fupan',mapped_paths=[str(mapped_source_path(p)) for p in legacy['source_path'].split('|')],result=repaired_pool_binding(legacy)['state'],reason='PATH_SCHEMA_SUPPORTED_BUT_NO_PARENT_TIME_MUST_STAY_UNKNOWN'))
    selected=[]
    for predicate in (lambda r:r['old_substring_false_rejection'] and r['evidence_tier'].startswith('DECLARED'),lambda r:r['original_research_subject_eligible'] is False,lambda r:r['evidence_tier'].startswith('UNDECLARED')):
        row=next(r for r in rows if predicate(r));resource=compact['resource_bindings'][row['resource_ref_sha256']]
        assert research_record_gate(row,resource) is None
        selected.append(verify_research_wrapper(row,resource,slots[(row['target_date'],row['slot'])],packet))
    result=dict(schema='V194_SOURCE_BINDING_REPAIR_CANARY',pool_checks=checks,research_checks=selected,subject_false_still_wide_admitted=True,unknown_never_zero=True,thread_limit=2,resource_rss_bytes=resource_module_rss(),real_fit_count=0,new_technical_formula_evaluations=0,**FLAGS)
    save(REPAIR_OUT/'CANARY_RECEIPT.json',result);return result

def resource_module_rss():return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

def repair_project():
    """Rebuild source OR views from frozen proofs and full existing11 projections."""
    import copy,shutil
    started=time.monotonic();packet=RepairPacket()
    assert load(REPAIR_OUT/'CANARY_RECEIPT.json')['subject_false_still_wide_admitted']
    assert load(REPAIR_OUT/'CANARY_COMPANY_TITLE_INCREMENT_RECEIPT.json')['producer_wrapper_parity']
    oldpath=OUT/'MANIFEST_V4_COMPLETE_DATES_FINAL.json';old=load(oldpath)
    def readcsv(path):
        with Path(path).open() as f:return list(csv.DictReader(f))
    calendar=readcsv(old['files']['calendar']['path']);date_rows={r['target_date'].replace('-',''):r for r in calendar};scope=set(date_rows)
    old_candidates=readcsv(old['files']['candidates']['path']);old_keys={(r['target_date'],r['code']) for r in old_candidates}
    truth=readcsv(old['files']['truth']['path']);truthkeys={(r['target_date'],r['code']) for r in truth}
    # Copy accepted labels byte-for-byte. No return/ranking/formula evaluator call.
    truthpath=REPAIR_OUT/'truth.csv';assert not truthpath.exists(),'REPAIR_OUTPUT_EXISTS'
    shutil.copyfile(old['files']['truth']['path'],truthpath)
    assert sha(truthpath)==old['files']['truth']['sha256'],'ACCEPTED_TRUTH_COPY_DRIFT'
    paths=sorted(p for p in (OUT/'full').glob('*.json') if p.name!='RECEIPT.json')
    universe={p.name[:-5][:6]:p.name[:-5] for p in paths};assert len(universe)==5533
    technical={};tech_union=set();names={};projection_bindings=[]
    for path in paths:
        obj=load(path);code=obj['code'];projection_bindings.append(dict(path=str(path),sha256=sha(path)))
        for r in obj['features']:
            if r['target_date'] not in scope:continue
            key=(r['target_date'],code[:6]);assert all(r[f] in (0,1) for f in TECH),'FROZEN_TECHNICAL_FLAG_DRIFT'
            technical[key]=r;names[code[:6]]=r.get('name','')
            if any(r[f] for f in TECH):tech_union.add(key)
    original_tech_exclusions=load(OUT/'TECHNICAL_EXCLUSIONS.json');tech_reasons={(r['target_date'],r['code'][:6]):r['reason'] for r in original_tech_exclusions}
    # hits[(date, six-digit code)][lane] is a positive observed source only.
    hits=defaultdict(dict);pool_bindings=[];source_exclusions=[]
    for record in packet.get('POOL_SOURCE_GATE_TRACE_V3.json'):
        if record['target_date'] not in scope:continue
        try:binding=repaired_pool_binding(record,packet)
        except ValueError as e:binding=dict(state='unknown',reason=str(e))
        out=dict(target_date=record['target_date'],lane=record['lane'],cache_path=record['cache_path'],cache_rows=record.get('cache_rows'),cache_canonical_sha256=record.get('cache_canonical_sha256'),mapped_source_paths=record.get('mapped_source_paths',[]),binding=binding)
        pool_bindings.append(out)
        if binding['state']!='hit':source_exclusions.append(dict(target_date=record['target_date'],source=record['lane'],reason=binding['reason'],count=record.get('cache_rows',0)));continue
        for code in binding['codes']:
            assert code in universe,'RECOVERED_POOL_OUTSIDE_RESEARCH_UNIVERSE'
            hits[(record['target_date'],code)][record['lane']]=dict(available_at=binding['available_at'],evidence_ref=digest(out),parent_receipt_sha256=binding['parent_receipt']['receipt_sha256'])
    compact=packet.get('RESEARCH_RECOVERY_COMPACT.json.gz');assert compact['historical_availability_bound'] is False
    resources=compact['resource_bindings'];slots={(r['target_date'],r['slot']):r for r in packet.get('RESEARCH_SLOT_GATES_V3.json')}
    snapshot={(r['target_date'],r['code']):r for r in packet.get('OLD77_AND_38_STOCK_DATE_KEY_ALIGNMENT.json')}
    research_rows=[];research_by_key=defaultdict(list)
    for values in compact['rows']:
        row=dict(zip(compact['columns'],values));dt=row['target_date'];code=row['code']
        if dt not in scope:continue
        ref=resources[row['resource_ref_sha256']];assert digest(ref)==row['resource_ref_sha256'],'RESOURCE_PROOF_SHA_DRIFT'
        try:reason=research_record_gate(row,ref)
        except (ValueError,TypeError) as e:reason=str(e)
        if code not in universe:reason='OUTSIDE_FROZEN5533_RESEARCH_SCOPE'
        if reason:source_exclusions.append(dict(target_date=dt,source='research',topic_id=row['topic_id'],code=code,reason=reason,count=1));continue
        slot=slots[(dt,row['slot'])]
        # All exact producer body/title/entity checks are the frozen diagnostic
        # proof, with current immutable input/source bytes SHA-bound once here.
        packet.resource_file(slot['incoming_path'],ref['incoming_sha256'])
        packet.resource_file(slot['archive_path'],slot['archive_sha256'])
        for prefix in ('status','summary','topics','fetch_result'):
            packet.resource_file(ref[prefix+'_path'],ref[prefix+'_sha256'])
        for prefix in ('historical_collector_source','historical_report_policy'):
            if ref.get(prefix+'_path'):packet.resource_file(ref[prefix+'_path'],ref[prefix+'_sha256'])
        known=snapshot.get((dt,code));row.update(raw_publication_reconstruction_state='hit',actual_pool_membership=known['dated_pool_stock_membership'] if known else 'UNKNOWN_NOT_BOUND_FOR_THIS_KEY',actual_pool_snapshot_not_decision_complete=True,actual_pool_snapshot_evidence=known.get('snapshot_asof_witness') if known else None,research_subject_evidence_qualification=row['original_research_subject_eligible'],subject_qualification_used_as_admission_filter=False,historical_availability_bound=False,proof_mode='REUSED_SHA_BOUND_EXACT_PRODUCER_DIAGNOSTIC_PROOF')
        research_rows.append(row);research_by_key[(dt,code)].append(row);names.setdefault(code,row['name'])
    for key,rows in research_by_key.items():
        hits[key]['research']=dict(available_at=min((r['available_at'] for r in rows),key=aware),evidence_ref=digest(sorted(r['resource_ref_sha256'] for r in rows)),topic_count=len({r['topic_id'] for r in rows}),declared_topic_count=sum(r['evidence_tier'].startswith('DECLARED') for r in rows),compatibility_topic_count=sum(r['evidence_tier'].startswith('UNDECLARED') for r in rows))
    # Preserve rejected source-gate evidence at the original slot/count scope.
    for slot in slots.values():
        if slot['target_date'] not in scope:continue
        for reason,count in slot.get('row_gate_counts',{}).items():
            if reason!='EXACT_PRODUCER_EQUIVALENT_BODY_TITLE_TIME_ENTITY_BOUND':source_exclusions.append(dict(target_date=slot['target_date'],source='research',slot=slot['slot'],reason=reason,count=count,evidence='FROZEN_DIAGNOSTIC_ROW_GATE_COUNTS'))
    wide_keys=tech_union|set(hits);rawrows=[];modelrows=[];excluded_technical=[];axes=[]
    for dt,code in sorted(wide_keys):
        tech=technical.get((dt,code));lanes=hits.get((dt,code),{});reason=tech_reasons.get((dt,code),'FROZEN_COMPLETE11_KEY_UNAVAILABLE') if tech is None else ''
        sourceflags={'source_'+lane:'hit' if lane in lanes else 'unknown' for lane in ('fupan','stage7','research')}
        triggers=[f for f in TECH if tech is not None and tech[f]]+['source_'+lane for lane in ('fupan','stage7','research') if lane in lanes]
        assert triggers,'EMPTY_BROAD_UNION_REASON'
        available=[v['available_at'] for v in lanes.values()]
        if tech:available.append(iso(tech['signal_date'])+'T15:00:00+08:00')
        at=max(available,key=aware);assert aware(at)<=aware(iso(dt)+'T09:25:00+08:00'),'REPAIR_CANDIDATE_AFTER_CUTOFF'
        row=dict(target_date=iso(dt),signal_date=date_rows[dt]['signal_date'],code=universe[code],decision_at=iso(dt)+'T09:25:00+08:00',available_at=at,**{f:tech[f] if tech else '' for f in TECH},**sourceflags,candidate_reasons='|'.join(triggers),evidence_refs=json.dumps(dict(technical=tech.get('technical_evidence_ref') if tech else None,sources=lanes),ensure_ascii=False,separators=(',',':')),technical_status='COMPLETE_11_FLAGS' if tech else 'UNKNOWN_TECHNICAL_DEPENDENCY',technical_exclusion_reason=reason)
        rawrows.append(row)
        if tech:modelrows.append({k:v for k,v in row.items() if k not in {'technical_status','technical_exclusion_reason'}})
        else:excluded_technical.append(dict(target_date=iso(dt),code=universe[code],reason=reason,source_flags=sourceflags,in_raw_candidate_union=True,excluded_only_from_model_view=True,unknown_never_zero=True))
        rs=research_by_key.get((dt,code),[]);known=snapshot.get((dt,code));roles=Counter('true' if r['original_research_subject_eligible'] is True else 'false' if r['original_research_subject_eligible'] is False else 'unknown' for r in rs)
        axes.append(dict(target_date=iso(dt),code=universe[code],source_fupan=sourceflags['source_fupan'],source_stage7=sourceflags['source_stage7'],raw_publication_reconstruction=sourceflags['source_research'],actual_pool_snapshot_membership=known['dated_pool_stock_membership'] if known else 'UNKNOWN_NOT_BOUND_FOR_THIS_KEY',subject_true_topics=roles['true'],subject_false_topics=roles['false'],subject_unknown_topics=roles['unknown'],role_used_as_filter=False,actual_pool_snapshot_not_decision_complete=True,declared_topics=sum(r['evidence_tier'].startswith('DECLARED') for r in rs),compatibility_topics=sum(r['evidence_tier'].startswith('UNDECLARED') for r in rs)))
    revised,policy=freeze_date_policy(calendar,[(r['target_date'],r['code']) for r in modelrows],truthkeys)
    policy.update(old_date_policy=dict(path=old['files']['date_policy']['path'],sha256=old['files']['date_policy']['sha256']),technical_row_policy='Unknowntechnical rows remain raw union plus exclusions; model view requires all11 known',unknown_labels_never_zero=True)
    model_keys={(r['target_date'],r['code']) for r in modelrows};raw_keys={(r['target_date'],r['code']) for r in rawrows};assert old_keys<=model_keys,'OLD_TECHNICAL_OR_WIDE_SOURCE_CANDIDATE_LOST'
    gap_old={(r['target_date'],r['code']):r['reason'] for r in load(OUT/'MISSING95_DIRECT_CAUSE_AUDIT.json')['rows']}
    missing=[]
    for row in rawrows:
        key=(row['target_date'],row['code'])
        if key not in truthkeys:missing.append(dict(target_date=key[0],code=key[1],in_model_view=key in model_keys,old_candidate=key in old_keys,reason='UNLABELLED_TARGET_NO_TRUTH_INPUT' if key[0] in old['unlabelled_target_dates'] else gap_old.get(key,'ACCEPTED_TRUTH_KEY_MISSING_REASON_NOT_RECHECKED'),label_value=None,not_filled_zero=True))
    rowfields=['target_date','signal_date','code','decision_at','available_at',*TECH,*SOURCES,'candidate_reasons','evidence_refs']
    writecsv(REPAIR_OUT/'candidate.csv',modelrows,rowfields);writecsv(REPAIR_OUT/'RAW_CANDIDATE_UNION.csv',rawrows,rowfields+['technical_status','technical_exclusion_reason'])
    writecsv(REPAIR_OUT/'calendar.csv',revised,list(revised[0]));writecsv(REPAIR_OUT/'RESEARCH_THREE_AXIS.csv',axes,list(axes[0]))
    save(REPAIR_OUT/'DATE_POLICY.json',policy);save(REPAIR_OUT/'TECHNICAL_EXCLUSIONS.json',excluded_technical);save(REPAIR_OUT/'UNKNOWN_LABEL_KEYS.json',missing);save(REPAIR_OUT/'POOL_SOURCE_BINDINGS.json',pool_bindings);save(REPAIR_OUT/'SOURCE_EXCLUSIONS.json',source_exclusions);save(REPAIR_OUT/'RESEARCH_TOPIC_ENTITY_BINDINGS.json',research_rows)
    save(REPAIR_OUT/'SOURCE_HITS.json',[dict(target_date=dt,code=universe[code],lanes=lanes) for (dt,code),lanes in sorted(hits.items())]);save(REPAIR_OUT/'REUSED_TECHNICAL_PROJECTIONS.json',projection_bindings);save(REPAIR_OUT/'BOUND_SOURCE_RESOURCES.json',packet.verified)
    coverage=[];date_changes=[];old_by_date=Counter(r['target_date'] for r in old_candidates);old_eligible=set(old['eligible_target_dates']);new_eligible=set(policy['eligible_target_dates'])
    for cal in revised:
        dt=cal['target_date'];rr=[r for r in rawrows if r['target_date']==dt];mm=[r for r in modelrows if r['target_date']==dt];ax=[r for r in axes if r['target_date']==dt]
        cov=dict(**cal,raw_candidate_union_rows=len(rr),model_candidate_rows=len(mm),raw_source_only_rows=sum(not any(r[f] for f in TECH if r[f]!='') for r in rr),unknown_technical_candidate_rows=len(rr)-len(mm),partial_technical_coverage=len(rr)!=len(mm),old_candidate_rows=old_by_date[dt],added_model_candidate_rows=len(mm)-old_by_date[dt],historical_availability_bound=False)
        for lane in SOURCES:cov[lane+'_raw_hit_rows']=sum(r[lane]=='hit' for r in rr);cov[lane+'_model_hit_rows']=sum(r[lane]=='hit' for r in mm)
        cov.update(research_declared_topic_entities=sum(r['declared_topics'] for r in ax),research_compatibility_topic_entities=sum(r['compatibility_topics'] for r in ax),research_subject_false_topics=sum(r['subject_false_topics'] for r in ax))
        coverage.append(cov);date_changes.append(dict(target_date=dt,old_eligible=dt in old_eligible,new_eligible=dt in new_eligible,old_candidate_rows=old_by_date[dt],new_raw_candidate_rows=len(rr),new_model_candidate_rows=len(mm),unknown_technical_rows=len(rr)-len(mm),unknown_label_model_rows=cal['unknown_candidate_label_rows'],new_cohort_role=cal['cohort_role'],reason=cal['eligibility_exclusion_reason']))
    writecsv(REPAIR_OUT/'coverage.csv',coverage,list(coverage[0]));writecsv(REPAIR_OUT/'OLD_TO_NEW_DATE_POLICY.csv',date_changes,list(date_changes[0]))
    dictionary=load(old['files']['dictionary']['path']);dictionary.update(source_repair='EXACT_PUBLISHED_A_POOLS_AND_DECLARED_OR_COMPATIBLE_PRODUCER_BODY_BOUND_TITLE',research_three_axes='Raw publication reconstruction is broad-in hit; exact original dated pool membership and original subject eligibility remain metadata only',subject_false_is_not_filter=True,three_axis_features_added_to_model=False,raw_and_model_views='RAW_CANDIDATE_UNION retains unknowntechnical keys; model candidate requires original11flag complete row gate',historical_availability_bound=False)
    save(REPAIR_OUT/'DATA_DICTIONARY.json',dictionary)
    filenames=dict(candidates='candidate.csv',raw_candidate_union='RAW_CANDIDATE_UNION.csv',truth='truth.csv',calendar='calendar.csv',coverage='coverage.csv',date_policy='DATE_POLICY.json',dictionary='DATA_DICTIONARY.json',technical_exclusions='TECHNICAL_EXCLUSIONS.json',unknown_labels='UNKNOWN_LABEL_KEYS.json',research_three_axis='RESEARCH_THREE_AXIS.csv',research_topic_entities='RESEARCH_TOPIC_ENTITY_BINDINGS.json',pool_bindings='POOL_SOURCE_BINDINGS.json',source_exclusions='SOURCE_EXCLUSIONS.json',source_hits='SOURCE_HITS.json',old_new_date_policy='OLD_TO_NEW_DATE_POLICY.csv',reused_technical='REUSED_TECHNICAL_PROJECTIONS.json',bound_resources='BOUND_SOURCE_RESOURCES.json')
    files={k:dict(path=str(REPAIR_OUT/v),sha256=sha(REPAIR_OUT/v)) for k,v in filenames.items()}
    manifest=copy.deepcopy(old);manifest.update(schema='V194_SOURCE_REPAIRED_DATASET_R1',files=files,input_sha256=digest(files),previous_manifest=dict(path=str(oldpath),sha256=sha(oldpath)),config_sha256=sha(REPAIR/'DATA_BINDING_REPAIR_CONTRACT.json'),policy_revision='REPAIRED_THREE_SOURCE_WIDE_IN_ORIGINAL_TECHNICAL_ROW_AND_LABEL_DATE_POLICY',candidate_rows=len(modelrows),raw_candidate_union_rows=len(rawrows),unknown_technical_candidate_rows=len(excluded_technical),truth_rows=len(truth),eligible_dates=len(new_eligible),eligible_target_dates=policy['eligible_target_dates'],initial_train_target_dates=policy['initial_train_target_dates'],oof_target_dates=policy['oof_target_dates'],excluded_incomplete_target_dates=policy['excluded_incomplete_target_dates'],all_incomplete_target_dates=policy['all_incomplete_target_dates'],exclusions=policy['exclusions'],effect_acceptance_ceiling=policy['effect_acceptance_ceiling'],semantic_ready=policy['total_date_gate_met'],training_data_gate='TOTAL_ELIGIBLE20_MET' if policy['total_date_gate_met'] else 'STOP_INSUFFICIENT_COMPLETE_TARGET_DATES',candidate_values_changed=True,truth_values_changed=False,date_eligibility_changed=old_eligible!=new_eligible,lineage_review_pass=False,design_review_pass=False,historical_availability_bound=False,source_unknown='UNKNOWN_NEVER_ZERO_EMPTY_PLACEHOLDERS_NOT_ABSENT',research_subject_eligibility_filter=False,research_pool_membership_is_raw_mention=False,research_three_axis_features_in_model=False,raw_union_partial_technical_coverage=bool(excluded_technical),source_coverage_reused_from_review=None,start_event_sha256='ea7d796d41ab1023324ce3f654109ed116df8af679c6603ec7460e584080114a',diagnostic_source_author=dict(path=str(SOURCE_PACKET/'AUTHOR_RECEIPT.json'),sha256=SOURCE_AUTHOR_SHA))
    manifest['source_code_sha256'][str(Path(__file__))]=sha(__file__)
    manifest['source_repair_frozen_package']=packet.verified
    save(REPAIR_OUT/'MANIFEST.json',manifest)
    receipt=dict(schema='V194_SOURCE_REPAIR_AUTHOR_RECEIPT',author='/root/v194_data_writer_sol',status='READY_FOR_INDEPENDENT_INPUT_REVIEW',manifest=dict(path=str(REPAIR_OUT/'MANIFEST.json'),sha256=sha(REPAIR_OUT/'MANIFEST.json')),adapter_sha256=sha(__file__),tests_sha256=sha(Path(__file__).with_name('test_data194.py')),raw_candidate_rows=len(rawrows),model_candidate_rows=len(modelrows),old_candidate_rows=len(old_candidates),added_model_candidate_rows=len(modelrows)-len(old_candidates),unknowntechnical_source_candidate_rows=len(excluded_technical),unknown_historical_model_candidate_labels=sum(r['in_model_view'] and r['target_date'] not in old['unlabelled_target_dates'] for r in missing),old_eligible_dates=len(old_eligible),new_eligible_dates=len(new_eligible),initial_train_dates=len(policy['initial_train_target_dates']),oof_dates=len(policy['oof_target_dates']),effect_acceptance_ceiling=policy['effect_acceptance_ceiling'],source_hit_model_rows={s:sum(r[s]=='hit' for r in modelrows) for s in SOURCES},declared_research_topic_entities=sum(r['evidence_tier'].startswith('DECLARED') for r in research_rows),compatible_research_topic_entities=sum(r['evidence_tier'].startswith('UNDECLARED') for r in research_rows),research_subject_false_kept=sum(r['original_research_subject_eligible'] is False for r in research_rows),truth_bytes_reused=True,truth_sha256=sha(truthpath),original_materials_unchanged=True,full11_formula_evaluations=0,new_market_or_article_fetches=0,real_fit_count=0,resource_rss_bytes=resource_module_rss(),thread_limit=2,elapsed_seconds=time.monotonic()-started,**FLAGS)
    save(REPAIR_OUT/'AUTHOR_RECEIPT.json',receipt);return repair_finalize_metadata(receipt)

def repair_finalize_metadata(receipt=None):
    """Freeze final counters and policy references without reprojecting sources."""
    import copy
    initial=load(REPAIR_OUT/'MANIFEST.json');m=copy.deepcopy(initial)
    receipt=copy.deepcopy(receipt or load(REPAIR_OUT/'AUTHOR_RECEIPT.json'))
    with (REPAIR_OUT/'calendar.csv').open() as f:calendar=list(csv.DictReader(f))
    dictionary=load(REPAIR_OUT/'DATA_DICTIONARY.json')
    dictionary.update(candidate_label_gap_policy='Keep all original and added UNKNOWN labels; apply whole-date label completeness only to retained complete11 modelcandidate rows',raw_unknowntechnical_policy='Keep every broad-union source-only unknowntechnical key in RAW_CANDIDATE_UNION and per-key exclusions; no zero imputation; retain original model row gate',source_role_limit='Subject qualification=false is metadata only and never a broad candidate or source-hit filter')
    dp=REPAIR_OUT/'DATA_DICTIONARY_FINAL.json';save(dp,dictionary)
    m['files']['dictionary']=dict(path=str(dp),sha256=sha(dp));m['input_sha256']=digest(m['files'])
    m.update(incomplete_target_date_count=len(m['all_incomplete_target_dates']),incomplete_diagnostic_target_dates=[r['target_date'] for r in calendar if r['cohort_role']=='diagnostic' and int(r['unknown_candidate_label_rows'])],technical_exclusions=receipt['unknowntechnical_source_candidate_rows'],original_full_projection_exclusions=dict(path=str(OUT/'TECHNICAL_EXCLUSIONS.json'),sha256=sha(OUT/'TECHNICAL_EXCLUSIONS.json'),row_count=initial['technical_exclusions']),original_source_projection_draft=dict(path=str(REPAIR_OUT/'MANIFEST.json'),sha256=sha(REPAIR_OUT/'MANIFEST.json')),unknown_historical_model_candidate_labels=receipt['unknown_historical_model_candidate_labels'],metadata_finalized_without_source_recompute=True)
    m['source_code_sha256'][str(Path(__file__))]=sha(__file__)
    m['methodology_clarifications']={str(REPAIR/name):sha(REPAIR/name) for name in ['DATAWRITER_SCOPE_ADDENDUM.json','DATE_POLICY_CLARIFICATION.json','TECHNICAL_ROW_POLICY_CLARIFICATION.json']}
    mp=REPAIR_OUT/'MANIFEST_FINAL.json';save(mp,m)
    receipt.update(manifest=dict(path=str(mp),sha256=sha(mp)),adapter_sha256=sha(__file__),dictionary=dict(path=str(dp),sha256=sha(dp)),final_source_data_changed=False,metadata_only_finalization=True)
    save(REPAIR_OUT/'AUTHOR_RECEIPT_FINAL.json',receipt);return receipt

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
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['sources','canary','full','assemble','date-policy','repair-canary','repair-project']);p.add_argument('--start-event-sha',required=True);args=p.parse_args()
    if args.phase.startswith('repair-'):repair_start_gate(args.start_event_sha)
    else:start_gate(args.start_event_sha)
    if args.phase=='repair-canary':r=repair_canary()
    elif args.phase=='repair-project':r=repair_project()
    elif args.phase=='date-policy':r=materialize_date_policy()
    elif args.phase=='sources':r=source_materialize();save(OUT/'SOURCE_RECEIPT.json',r)
    elif args.phase in {'canary','full'}:r=run_technical(args.phase)
    else:r=assemble()
    print(json.dumps(r,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
