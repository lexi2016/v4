"""Dated four-group projection at the existing A producer completion boundary.

No acquisition or GET execution. Historical bootstrap is explicit and bounded;
the normal daily path evaluates only its target date and reuses validated history.
"""
from __future__ import annotations
import ast,csv,gzip,hashlib,importlib.util,io,json,math,os,re,struct,sys,time,urllib.parse,urllib.request,zipfile
from collections import Counter
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
GROUPS=('original','nav_smallk','nav_pullback','nav_breakout')
CHART_POOL_ID='a_share_chart_selection'
CHART_GROUP_LABELS={'original':'原公式','nav_smallk':'导航小K','nav_pullback':'导航回踩','nav_breakout':'导航突破'}
CONFIG=Path(__file__).resolve().parents[1]/'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json'
SCHEMA='v4.a_share.daily_product.v1'
A20_PUFA_PARENT_GENERATION='bfd455c86915918360d9f15c907b72e435b9e46cd8f931db3d6b8f6f7d67ab0b'
A20_PUFA_SOURCE_GENERATION='d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
A20_PUFA_SOURCE_INPUT='9eef2834994e6156561efc9666182a2528734adb2a086dfd602c7b7c5f4ef774'
A20_PUFA_OFFICIAL_PDF_SHA='ad5b1f547e6308db38c7b613e2b2c02595b43b6a03755304589a077e8af9a7fc'
A20_PUFA_OFFICIAL_EVIDENCE_SHA='2a89b96cfaf74a28659c7a23b875d9423a7a7aa607bf1933ea47c90b4795037b'

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=lambda x:str(x) if isinstance(x,Decimal) else (_ for _ in ()).throw(TypeError(type(x).__name__))).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def reference(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def prepared_reference(p,v):
 """Identity of the bytes this owner intends to write, independent of rereads."""
 return dict(path=str(Path(p).resolve()),sha256=hashlib.sha256(canonical(v)+b'\n').hexdigest())
def checked(r):
 p=Path(r['path'])
 if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p or sha(p)!=r['sha256']:raise ValueError('DAILY_SOURCE_PIN_DRIFT:'+str(p))
 return p
def save(p,v,immutable=False):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);raw=canonical(v)+b'\n'
 if immutable and p.exists():
  if p.read_bytes()!=raw:raise ValueError('DAILY_IMMUTABLE_CONFLICT:'+str(p))
  return reference(p)
 tmp=p.with_name('.'+p.name+f'.{os.getpid()}.pending')
 with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p);return reference(p)

def chart_preselection_from_completion(*,index_ref,event_ref,calendar_ref,archive_refs=None):
 """Project the original, bound daily completion into one dated A-share pool.

 The function reads existing materialized rows only.  It does not publish,
 collect data, evaluate formulas, or accept an unbound next-session date.
 """
 from contracts.a_share_instruments import a_share_instrument_rejection
 from contracts.trading_calendar import load_market_calendar,next_session
 def read(ref):
  path=checked(ref);raw=path.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('CHART_POOL_SOURCE_MOVED')
  value=json.loads(raw)
  if not isinstance(value,dict):raise ValueError('CHART_POOL_SOURCE_NOT_OBJECT')
  return value
 index,event=read(index_ref),read(event_ref)
 root=Path(index_ref['path']).parent
 if (Path(index_ref['path'])!=root/'index.json' or Path(event_ref['path'])!=root/'events/latest.json'
     or index.get('schema_version')!='v4.a_share.daily_product_index.v1'
     or event.get('schema_version')!='v4.a_share.daily_completion.v1'):
  raise ValueError('CHART_POOL_COMPLETION_IDENTITY_CONFLICT')
 day=str(event.get('data_date') or '')
 try:
  if datetime.strptime(day,'%Y%m%d').strftime('%Y%m%d')!=day:raise ValueError
 except ValueError:raise ValueError('CHART_POOL_SOURCE_DATE_INVALID') from None
 manifest_ref=event.get('manifest') or {};artifact_ref=event.get('artifact') or {}
 for ref in (manifest_ref,artifact_ref):
  if not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not Path(ref['path']).is_relative_to(root):
   raise ValueError('CHART_POOL_SOURCE_OUTSIDE_OWNER')
 manifest,product=read(manifest_ref),read(artifact_ref)
 if archive_refs is None:archive_refs={'index':index_ref,'completion':event_ref}
 if (not isinstance(archive_refs,dict) or set(archive_refs)!={'index','completion'}
     or any(not isinstance(archive_refs[k],dict) or archive_refs[k].get('sha256')!=live['sha256']
            or not isinstance(archive_refs[k].get('path'),str)
            or read(archive_refs[k])!=value
            for k,live,value in (('index',index_ref,index),('completion',event_ref,event)))):
  raise ValueError('CHART_POOL_ARCHIVE_BINDING_CONFLICT')
 generation=event.get('source_generation');source_input=event.get('input_sha256');identity=product.get('source_identity') or {}
 if (not isinstance(event.get('event_id'),str) or not re.fullmatch(r'[a-f0-9]{64}',event['event_id'])
     or not isinstance(generation,str) or not re.fullmatch(r'[a-f0-9]{64}',generation)
     or not isinstance(source_input,str) or not re.fullmatch(r'[a-f0-9]{64}',source_input)
     or index.get('dates',{}).get(day)!=manifest_ref or index.get('latest_date')!=day
     or index.get('latest')!=manifest_ref or manifest.get('artifact')!=artifact_ref
     or manifest.get('schema_version')!='v4.a_share.daily_product_manifest.v1' or product.get('schema_version')!=SCHEMA
     or manifest.get('data_date')!=day or product.get('data_date')!=day
     or manifest.get('source_generation')!=generation or product.get('source_generation')!=generation
     or identity.get('generation')!=generation or str(identity.get('asof'))!=day
     or manifest.get('input_sha256')!=source_input or identity.get('input_sha256')!=source_input
     or manifest.get('sample_only') is not False or product.get('sample_only') is not False
     or event.get('status') not in ('READY','PARTIAL_WITH_ROWS') or product.get('status')!=event.get('status')
     or manifest.get('status')!=product.get('status')
     or any(obj.get(k) is not value for obj in (event,manifest,product) for k,value in FLAGS.items())):
  raise ValueError('CHART_POOL_COMPLETION_BINDING_CONFLICT')
 processed=product.get('processed_count');universe=product.get('source_universe_count')
 if (type(processed) is not int or processed<1 or processed!=universe or event.get('processed_count')!=processed
     or event.get('source_universe_count')!=universe or manifest.get('processed_count')!=processed
     or manifest.get('source_universe_count')!=universe):raise ValueError('CHART_POOL_UNIVERSE_CONFLICT')
 checked(calendar_ref)
 target=next_session(load_market_calendar(Path(calendar_ref['path'])),day,market='a_share')
 if (sha(index_ref['path'])!=index_ref['sha256'] or sha(event_ref['path'])!=event_ref['sha256']
     or sha(calendar_ref['path'])!=calendar_ref['sha256']):
  raise ValueError('CHART_POOL_COMPLETION_MOVED')
 raw_rows=product.get('rows');group_counts=product.get('group_counts');unknown_count=product.get('unknown_count')
 if (not isinstance(raw_rows,list) or type(product.get('unique_count')) is not int or len(raw_rows)!=product['unique_count']
     or not isinstance(group_counts,dict) or set(group_counts)!=set(GROUPS) or type(unknown_count) is not int or unknown_count<0
     or event.get('unknown_count')!=unknown_count):raise ValueError('CHART_POOL_SCOPE_CONFLICT')
 rows=[];seen=set();seen_pool_codes=set();counts=Counter()
 for item in raw_rows:
  if not isinstance(item,dict):raise ValueError('CHART_POOL_ROW_INVALID')
  symbol=item.get('symbol');groups=item.get('groups');pending=item.get('pending_groups')
  if (not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol)
      or a_share_instrument_rejection(symbol,item) or symbol in seen or 'A.'+symbol[:6] in seen_pool_codes or item.get('data_date')!=day
      or not isinstance(groups,str) or not isinstance(pending,str)
      or item.get('display_name') is not None and not isinstance(item.get('display_name'),str)):
   raise ValueError('CHART_POOL_ROW_IDENTITY_CONFLICT')
  hit=groups.split('|') if groups else [];unknown=pending.split('|') if pending else []
  if (not hit or len(hit)!=len(set(hit)) or len(unknown)!=len(set(unknown)) or set(hit)&set(unknown)
      or not set(hit)<=set(GROUPS) or not set(unknown)<=set(GROUPS)):
   raise ValueError('CHART_POOL_GROUP_STATE_CONFLICT')
  hit=[g for g in GROUPS if g in hit];unknown=[g for g in GROUPS if g in unknown];counts.update(hit);seen.add(symbol);seen_pool_codes.add('A.'+symbol[:6])
  states={g:('TRUE' if g in hit else 'UNKNOWN' if g in unknown else 'FALSE') for g in GROUPS}
  hit_label='、'.join(CHART_GROUP_LABELS[g] for g in hit);unknown_label='、'.join(CHART_GROUP_LABELS[g] for g in unknown)
  rows.append(dict(symbol='A.'+symbol[:6],ts_code=symbol,market='A',pool_id=CHART_POOL_ID,
   stock_name=item.get('display_name') or symbol,signal_date=day,source_date=day,target_date=target,
   chart_groups=hit,chart_pending_groups=unknown,chart_group_states=states,chart_reasons=item.get('reasons') or '',
   chart_source_date=day,chart_source_generation=generation,chart_source_input_sha256=source_input,
   chart_source_manifest_sha256=manifest_ref['sha256'],
   source_tag='CHART_SELECTION',source_tags='（图）',source_lanes='research_panel_four_group',
   source_trace='图形选股：'+hit_label+('；待核：'+unknown_label if unknown else '')+'；来源日 '+day,
   recommendation_status='RESEARCH_ONLY',production_allowed=False,buy_gate_updated=False,orders_sent=False))
 if any(type(group_counts[g]) is not int or group_counts[g]!=counts[g] for g in GROUPS):
  raise ValueError('CHART_POOL_GROUP_COUNT_CONFLICT')
 reasons=['RESEARCH_ONLY_NO_BUY_GATE']
 if unknown_count:reasons.append('RESEARCH_ONLY_UNKNOWN_GROUP_MEMBERSHIP_COUNT:'+str(unknown_count))
 if product['status']!='READY':reasons.append('SOURCE_PANEL_'+product['status'])
 return dict(schema_version='v3_5.preselection_pool.v1',trade_date=target,pool_id=CHART_POOL_ID,display_name='图形选股',market='A',
  status='CHART_SELECTION_READY' if rows else 'CANNOT_CONFIRM',producer_id='v4_a_daily_product_chart_projection_v1',
  source_role='UPSTREAM_PRODUCER_ARTIFACT',source_path=artifact_ref['path'],source_sha256=artifact_ref['sha256'],
  source_artifact_sha256=artifact_ref['sha256'],source_manifest_sha256=manifest_ref['sha256'],source_receipt_sha256=event_ref['sha256'],
  source_run_id=generation,source_row_count=len(rows),signal_date=day,target_date=target,stage_selection_eligible=bool(rows),
  source_archive=dict(index=archive_refs['index'],completion=archive_refs['completion'],manifest=manifest_ref,
                      current_index_path=index_ref['path'],calendar=calendar_ref,input_sha256=source_input),
  coverage_evidence=dict(source_processed_count=processed,source_unknown_count=unknown_count,source_product_status=product['status'],group_counts=group_counts),
  rows=rows,cannot_confirm=reasons,production_allowed=False,buy_gate_updated=False,orders_sent=False)

def verify_chart_preselection_source(payload):
 """Fail a stale chart lane closed without affecting other preselection pools."""
 archive=payload.get('source_archive') or {}
 def read(ref):
  value=json.loads(checked(ref).read_bytes())
  if not isinstance(value,dict):raise ValueError('CHART_POOL_ARCHIVED_SOURCE_INVALID')
  return value
 try:
  index_path=Path(archive['current_index_path'])
  if not index_path.is_absolute() or index_path.name!='index.json' or index_path.is_symlink():
   raise ValueError('CHART_POOL_LIVE_INDEX_INVALID')
  root=index_path.parent.resolve(strict=True)
  if index_path.resolve(strict=True)!=index_path:raise ValueError('CHART_POOL_LIVE_INDEX_INVALID')
  if not Path(archive['manifest']['path']).is_relative_to(root):raise ValueError('CHART_POOL_SOURCE_OUTSIDE_OWNER')
  archived_index=read(archive['index']);event=read(archive['completion']);manifest=read(archive['manifest'])
  current=json.loads(index_path.read_bytes());day=payload['signal_date'];event_manifest=event['manifest']
  if (event.get('schema_version')!='v4.a_share.daily_completion.v1'
      or archived_index.get('schema_version')!='v4.a_share.daily_product_index.v1'
      or current.get('schema_version')!='v4.a_share.daily_product_index.v1'
      or event.get('data_date')!=day or archived_index.get('dates',{}).get(day)!=event_manifest
      or archive['manifest']!=event_manifest
      or event.get('source_generation')!=payload.get('source_run_id')
      or event.get('input_sha256')!=archive.get('input_sha256')
      or event_manifest.get('sha256')!=payload.get('source_manifest_sha256')
      or archive['completion'].get('sha256')!=payload.get('source_receipt_sha256')
      or event.get('artifact')!=manifest.get('artifact')
      or manifest.get('artifact',{}).get('sha256')!=payload.get('source_sha256')
      or manifest.get('artifact',{}).get('path')!=payload.get('source_path')):
   raise ValueError('CHART_POOL_CURRENT_SOURCE_CHANGED')
  checked(manifest['artifact']);checked(archive['calendar'])
  current_manifest_ref=current.get('dates',{}).get(day)
  if current_manifest_ref!=event_manifest:
   # History/auxiliary continuations can replace a numeric manifest without
   # changing the four groups.  Reuse only after a full semantic comparison
   # of the candidate rows and their source identity; never relabel the old
   # source SHA as the new one.
   if not isinstance(current_manifest_ref,dict) or not Path(current_manifest_ref['path']).is_relative_to(root):
    raise ValueError('CHART_POOL_CURRENT_SOURCE_CHANGED')
   current_manifest=read(current_manifest_ref);current_artifact=current_manifest.get('artifact') or {}
   if not isinstance(current_artifact.get('path'),str) or not Path(current_artifact['path']).is_relative_to(root):
    raise ValueError('CHART_POOL_CURRENT_SOURCE_CHANGED')
   previous_product=read(manifest['artifact']);current_product=read(current_artifact)
   identity=current_product.get('source_identity') or {}
   fields=('data_date','source_generation','sample_only','status','processed_count','source_universe_count',
           'unique_count','group_counts','unknown_count','rows')
   if (current_manifest.get('data_date')!=day or current_manifest.get('source_generation')!=event.get('source_generation')
       or current_manifest.get('input_sha256')!=event.get('input_sha256') or current_manifest.get('sample_only') is not False
       or identity.get('generation')!=event.get('source_generation') or identity.get('input_sha256')!=event.get('input_sha256')
       or str(identity.get('asof'))!=day or any(current_product.get(k)!=previous_product.get(k) for k in fields)
       or any(current_product.get(k) is not value or current_manifest.get(k) is not value for k,value in FLAGS.items())):
    raise ValueError('CHART_POOL_CURRENT_SOURCE_CHANGED')
 except (KeyError,TypeError,ValueError,OSError) as error:
  raise ValueError('CHART_POOL_SOURCE_CANNOT_CONFIRM:'+str(error)) from error

def publish_chart_preselection_from_completion(*,root,pool_root,calendar_ref,expected_index_ref,expected_event_ref,expected_identity):
 """Publish the chart lane under the current daily owner's completion lock.

 The caller is the original daily producer and already holds its A_LONG lane.
 The lock below is the same lock used by the existing completion publisher.
 Source copies are immutable lineage evidence; the financial inputs and the
 other preselection pools are never rewritten.
 """
 import fcntl
 from infrastructure.preselection_pool_store import PreselectionPoolStore
 root=Path(root).resolve(strict=True);pool_root=Path(pool_root).resolve(strict=True)
 lock=(root/'.stock-history-completion.lock').open('a+b')
 try:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  index_ref,event_ref=reference(root/'index.json'),reference(root/'events/latest.json')
  if index_ref!=expected_index_ref or event_ref!=expected_event_ref:
   raise ValueError('CHART_POOL_EXPECTED_COMPLETION_CHANGED')
  current_event=json.loads(checked(event_ref).read_bytes())
  if (not isinstance(expected_identity,dict) or set(expected_identity)!={'data_date','source_generation','input_sha256','manifest','artifact'}
      or any(current_event.get(k)!=v for k,v in expected_identity.items())):
   raise ValueError('CHART_POOL_EXPECTED_IDENTITY_CHANGED')
  refs=dict(index_ref=index_ref,event_ref=event_ref,calendar_ref=calendar_ref)
  projected=chart_preselection_from_completion(**refs)
  store=PreselectionPoolStore(pool_root)
  preimage=store.read_chart_selection_preimage(projected['target_date'])
  cas_keys=('artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256')
  old=preimage['artifact'] if preimage else None
  def comparable(value):return {k:v for k,v in value.items() if k not in ('source_receipt_sha256','source_archive')}
  reuse=False
  if old is not None and comparable(old)==comparable(projected):
   try:verify_chart_preselection_source(old);reuse=True
   except ValueError:pass
  if reuse:
   pool_sha=preimage['artifact_sha256'];pool_path=preimage['artifact_relative'];receipt_path=preimage['receipt_relative']
  else:
   index=json.loads(checked(index_ref).read_bytes());event=json.loads(checked(event_ref).read_bytes())
   archive=root/'chart_preselection_provenance'/projected['signal_date']/index_ref['sha256']/event_ref['sha256']
   archived_index=save(archive/'index.json',index,immutable=True)
   archived_event=save(archive/'completion.json',event,immutable=True)
   if (archived_index['sha256']!=index_ref['sha256'] or archived_event['sha256']!=event_ref['sha256']):
    raise ValueError('CHART_POOL_ARCHIVE_BYTE_MISMATCH')
   refs['archive_refs']={'index':archived_index,'completion':archived_event}
   projected=chart_preselection_from_completion(**refs)
   for attempt in range(2):
    expected={key:preimage[key] for key in cas_keys} if preimage else None
    try:
     result=store.materialize_chart_selection(projected,**refs,expected_previous=expected)
     break
    except ValueError as error:
     # A different pool can atomically change the shared manifest between
     # preimage and commit.  Re-read once; identity gates still run inside
     # the lock and a moving daily event is never retried as the old event.
     if str(error)!='CHART_POOL_PREIMAGE_MISMATCH' or attempt:raise
     preimage=store.read_chart_selection_preimage(projected['target_date'])
   pool_sha=result['sha256'];pool_path=result['artifact_path'];receipt_path=result['receipt_path']
  if sha(index_ref['path'])!=index_ref['sha256'] or sha(event_ref['path'])!=event_ref['sha256']:
   raise ValueError('CHART_POOL_COMPLETION_MOVED_BEFORE_NOTIFICATION')
  event=json.loads(checked(event_ref).read_bytes())
  details=dict(status='READY' if projected['rows'] else 'CANNOT_CONFIRM',pool_id=CHART_POOL_ID,
    target_date=projected['target_date'],source_date=projected['signal_date'],
    source_generation=projected['source_run_id'],source_manifest_sha256=projected['source_manifest_sha256'],
    artifact_path=pool_path,receipt_path=receipt_path,artifact_sha256=pool_sha,
    row_count=len(projected['rows']),unknown_count=projected['coverage_evidence']['source_unknown_count'])
  if event.get('chart_preselection')!=details:
   event['chart_preselection']=details
   event['event_id']=digest(dict(previous_event_id=event['event_id'],chart_preselection=details))
   save(root/'events/latest.json',event)
  return {**details,'reused':reuse}
 finally:
  lock.close()

def _a20_pufa_company_binding(candidate):
 """Reuse the existing score-child and its exact G2 origin as company identity."""
 identity=candidate.get('identity') or {};parent_ref=candidate.get('parent_index');wrapper_ref=candidate.get('parent_binding');origin_ref=candidate.get('origin_binding')
 index=json.loads(checked(parent_ref).read_text());wrapper=json.loads(checked(wrapper_ref).read_text());origin=json.loads(checked(origin_ref).read_text())
 if (candidate.get('schema')!='v4.workbench.a20_hold_score_candidate.v1' or identity.get('symbol')!='600000.SH'
     or identity.get('source_date')!='2026-10-30' or identity.get('parent_generation')!=A20_PUFA_PARENT_GENERATION
     or candidate.get('candidate_generation')!=digest(identity)
     or identity.get('parent_index_sha256')!=parent_ref.get('sha256') or identity.get('parent_binding_sha256')!=wrapper_ref.get('sha256')
     or identity.get('origin_binding_sha256')!=origin_ref.get('sha256')
     or index.get('candidate_generation')!=A20_PUFA_PARENT_GENERATION or index.get('source_generation')!=A20_PUFA_SOURCE_GENERATION
     or index.get('input_sha256')!=A20_PUFA_SOURCE_INPUT or index.get('source_date')!='2026-10-30' or index.get('observation_date')!='2026-11-02'
     or index.get('symbols',{}).get('600000.SH',{}).get('status')!='READY'
     or index['symbols']['600000.SH'].get('binding')!=wrapper_ref or wrapper.get('symbol')!='600000.SH'
     or wrapper.get('candidate_generation')!=A20_PUFA_PARENT_GENERATION or wrapper.get('origin_binding')!=origin_ref
     or origin.get('symbol')!='600000.SH' or origin.get('generation')!=index['source_generation']
     or origin.get('input_sha256')!=index['input_sha256'] or origin.get('numeric_manifest')!=index.get('numeric_manifest')
     or origin.get('source_date')!=index['source_date'] or origin.get('observation_date')!=index['observation_date']
     or any(v.get('historical_PIT') is not False or any(v.get(k) is not value for k,value in FLAGS.items()) for v in (candidate,index,origin))):
  raise ValueError('SINGLE_COMPANY_IDENTITY_CONFLICT')
 return dict(symbol='600000.SH',source_date=index['source_date'],observation_date=index['observation_date'],
             source_generation=index['source_generation'],source_input_sha256=index['input_sha256'],
             numeric_manifest=index['numeric_manifest'],candidate_generation=candidate['candidate_generation'],**FLAGS)


def _check_a20_pufa_official(received,sources):
 proof_ref=received.get('official_evidence') or {}
 if proof_ref.get('sha256')!=A20_PUFA_OFFICIAL_EVIDENCE_SHA:raise ValueError('SINGLE_PUFA_EVIDENCE_CONFLICT')
 proof=json.loads(checked(proof_ref).read_text());item=sources.get('official_quarterly') or {};finance=received.get('financials_reported') or {}
 values=proof.get('normalized_values_yuan') or {};original=proof.get('original_values_million_cny') or {}
 fields={'latest_revenue':'revenue','latest_net_profit_parent':'net_profit_parent','operating_cash_flow':'net_cash_flow_from_operating_activities'}
 if (proof.get('schema')!='v4.a20.official_quarterly_evidence.v1' or proof.get('status')!='ISSUER_SOURCE_VERIFIED_NOT_BOUND'
     or proof.get('symbol')!='600000.SH' or proof.get('report_period_end')!='2026-09-30' or proof.get('period_start')!='2026-01-01'
     or proof.get('statement_scope')!='CONSOLIDATED_GROUP' or proof.get('currency')!='CNY' or proof.get('original_unit')!='CNY_MILLION'
     or proof.get('operating_cash_flow_basis')!='NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES'
     or proof.get('availability_asof_20261030_market_close')!='CANNOT_CONFIRM'
     or proof.get('historical_PIT') is not False or any(proof.get(k) is not v for k,v in FLAGS.items())
     or item.get('kind')!='COMPANY_FILING' or item.get('file')!=proof.get('source') or item.get('url')!=proof.get('source_url')
     or item.get('file',{}).get('sha256')!=A20_PUFA_OFFICIAL_PDF_SHA or not str(item.get('url','')).startswith('https://')
     or finance.get('latest_report_period')!='2026-09-30' or finance.get('monetary_unit')!='元'
     or finance.get('operating_cash_flow_basis')!='NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES' or finance.get('evidence_status')!='OFFICIAL_FILING'
     or any(type(original.get(source)) is not int or values.get(target)!=original[source]*1000000 or finance.get(target)!=values[target]
            for target,source in fields.items())
     or proof.get('issuer_index',{}).get('display_date')!='2026-10-30'
     or proof.get('issuer_sse_notice',{}).get('stated_sse_disclosure_date')!='2026-10-31'):
  raise ValueError('SINGLE_PUFA_EVIDENCE_CONFLICT')
 if not checked(item['file']).read_bytes().startswith(b'%PDF-'):raise ValueError('SINGLE_PUFA_EVIDENCE_CONFLICT')
 checked(proof['issuer_index']['ref']);checked(proof['issuer_sse_notice']['ref'])
 return proof_ref


def materialize_bound_single_company(*, candidate_ref, received_ref, output_root):
 """Save received company facts for the admitted single stock, without publishing an index."""
 candidate=json.loads(checked(candidate_ref).read_text());is_pufa=candidate.get('schema')=='v4.workbench.a20_hold_score_candidate.v1'
 binding=_a20_pufa_company_binding(candidate) if is_pufa else json.loads(checked(candidate['binding']).read_text())
 received=json.loads(checked(received_ref).read_text())
 symbol=binding.get('symbol')
 if (symbol not in ({'600000.SH'} if is_pufa else {'002865.SZ','301048.SZ','300206.SZ'}) or binding.get('source_date')!='2026-10-30'
     or binding.get('observation_date')!='2026-11-02' or not is_pufa and not isinstance(binding.get('candidate_pool_member'),bool)
     or binding.get('candidate_generation')!=candidate.get('candidate_generation')
     or received.get('symbol')!=symbol or received.get('asof')!='2026-10-30'
     or any(binding.get(k)!=v for k,v in FLAGS.items())):raise ValueError('SINGLE_COMPANY_IDENTITY_CONFLICT')
 sources=received.get('sources',{})
 if 'tdx_f10' not in sources or set(sources)-{'official_quarterly','tdx_f10'}:raise ValueError('SINGLE_COMPANY_SOURCES_INCOMPLETE')
 f10=json.loads(checked(sources['tdx_f10']['file']).read_text())
 if (sources['tdx_f10'].get('kind')!='TDX_F10_CURRENT_SNAPSHOT' or f10.get('symbol')!=symbol
     or f10.get('status')!='OBSERVED' or f10.get('historical_PIT') is not False
     or any(f10.get(k)!=v for k,v in FLAGS.items())
     or hashlib.sha256(f10.get('source_text','').encode()).hexdigest()!=f10.get('source_text_sha256')):raise ValueError('SINGLE_F10_SOURCE_INVALID')
 proof_ref=_check_a20_pufa_official(received,sources) if is_pufa else None
 if 'official_quarterly' in sources and not is_pufa:
  item=sources['official_quarterly'];path=checked(item['file']);day=item.get('available_date','')
  if (item.get('kind')!='COMPANY_FILING' or not path.read_bytes().startswith(b'%PDF-')
      or not item.get('url','').startswith('https://') or len(day)!=10 or day>'2026-10-30' or day<'1900-01-01'):raise ValueError('SINGLE_COMPANY_SOURCE_INVALID')
  datetime.strptime(day,'%Y-%m-%d')
 shard=dict(schema_version='v4.a_share.company_materials.v1',symbol=symbol,data_date='20261030',
  observation_date='2026-11-02',source_generation=binding['source_generation'],input_sha256=binding['source_input_sha256'],
  numeric_manifest=binding['numeric_manifest'],source_candidate_generation=binding['candidate_generation'],
  source_candidate=candidate_ref,source_refs=sources,received_ref=received_ref,
  business_reported=received['business_reported'],financials_reported=received['financials_reported'],
  shareholders_reported=received['shareholders_reported'],report_catalog=received['report_catalog'],
  stored_report=received['stored_report'],f10={k:f10.get(k) for k in ('captured_at','source_updated_date','finance_updated_date','concepts','concept_status','industry','financials','source_text_sha256')},
  historical_PIT=False,producer_sha256=sha(__file__),**FLAGS)
 if is_pufa:shard['official_evidence']=proof_ref
 target=Path(output_root)/'daily_products/a_share/company_materials/20261030'/digest(shard)/(symbol+'.json')
 return save(target,shard,immutable=True)


def secondary_financial_page(symbols, page, *, output_root, observation_date, timeout=20):
 """Fetch one bounded provider page for the existing received-materials owner."""
 if (not isinstance(symbols,list) or not 1<=len(symbols)<=40 or len(set(symbols))!=len(symbols)
     or any(not isinstance(x,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',x) for x in symbols)
     or len({x[:6] for x in symbols})!=len(symbols) or type(page) is not int or page<1):
  raise ValueError('SECONDARY_FINANCIAL_REQUEST_SCOPE_INVALID')
 try:observed=datetime.strptime(observation_date,'%Y-%m-%d')
 except (TypeError,ValueError):raise ValueError('SECONDARY_FINANCIAL_OBSERVATION_DATE_INVALID') from None
 codes=','.join('"'+x[:6]+'"' for x in symbols)
 params={'reportName':'RPT_F10_FINANCE_MAINFINADATA','columns':'ALL',
         'filter':'(SECURITY_CODE in ('+codes+'))(REPORT_DATE>=\''+str(observed.year-3)+'-12-31\')',
         'pageSize':'5000','pageNumber':str(page),'sortColumns':'REPORT_DATE','sortTypes':'-1','source':'WEB','client':'WEB'}
 url='https://datacenter-web.eastmoney.com/api/data/v1/get?'+urllib.parse.urlencode(params)
 started=datetime.now(timezone.utc).isoformat()
 request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
 with urllib.request.urlopen(request,timeout=timeout) as response:
  if response.status!=200:raise ValueError('SECONDARY_FINANCIAL_HTTP_STATUS:'+str(response.status))
  raw=response.read(16*1024*1024+1)
 if len(raw)>16*1024*1024:raise ValueError('SECONDARY_FINANCIAL_RESPONSE_TOO_LARGE')
 digest_raw=hashlib.sha256(raw).hexdigest();root=Path(output_root).resolve(strict=True);target=root/(digest_raw+'.bin')
 try:
  with target.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
 except FileExistsError:
  if target.read_bytes()!=raw:raise ValueError('SECONDARY_FINANCIAL_RAW_CONFLICT')
 return {'page':page,'url':url,'symbols':symbols,'captured_at':started,
         'raw_ref':{'path':str(target),'sha256':digest_raw,'bytes':len(raw)}}


def normalize_secondary_financial_batch(symbols, pages, *, observation_date, normalizer_ref):
 """Read each provider page once and project each requested, source-bound stock."""
 if (not isinstance(symbols,list) or not symbols or len(set(symbols))!=len(symbols)
     or any(not isinstance(x,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',x) for x in symbols)):
  raise ValueError('SECONDARY_FINANCIAL_SYMBOL_INVALID')
 if normalizer_ref.get('sha256')!='fc3fd75cbbcb6d873726bb0d7ba5eebe3eeb5b46928bf51f33a0bef93cbc6e96':
  raise ValueError('SECONDARY_FINANCIAL_NORMALIZER_CONFLICT')
 checked(normalizer_ref)
 try:observation=datetime.strptime(observation_date,'%Y-%m-%d').date()
 except (TypeError,ValueError):raise ValueError('SECONDARY_FINANCIAL_OBSERVATION_DATE_INVALID') from None
 if not isinstance(pages,list) or not pages:raise ValueError('SECONDARY_FINANCIAL_PAGES_MISSING')
 def day(value):
  try:return datetime.strptime(str(value)[:10],'%Y-%m-%d').date()
  except (TypeError,ValueError):return None
 page_numbers=[];declared=None;declared_count=None;received_count=0;records={x:[] for x in symbols};request_scope=None
 for page in pages:
  number=page.get('page');raw_ref=page.get('raw_ref') or {};url=page.get('url') or ''
  parsed=urllib.parse.urlparse(url);params=urllib.parse.parse_qs(parsed.query)
  try:captured=datetime.fromisoformat(page.get('captured_at',''))
  except (TypeError,ValueError):captured=None
  page_symbols=page.get('symbols');codes=set(re.findall(r'"(\d{6})"',(params.get('filter') or [''])[0]))
  if (type(number) is not int or number<1 or not isinstance(page_symbols,list)
      or not set(symbols)<=set(page_symbols) or len(page_symbols)!=len(set(page_symbols))
      or codes!={x[:6] for x in page_symbols} or request_scope not in (None,set(page_symbols))
      or parsed.scheme!='https' or parsed.hostname!='datacenter-web.eastmoney.com'
      or params.get('reportName')!=['RPT_F10_FINANCE_MAINFINADATA'] or params.get('pageNumber')!=[str(number)]
      or not captured or captured.tzinfo is None or captured.utcoffset() is None):
   raise ValueError('SECONDARY_FINANCIAL_PAGE_IDENTITY_CONFLICT')
  request_scope=set(page_symbols)
  raw=checked(raw_ref).read_bytes();obj=json.loads(raw,parse_float=Decimal)
  result=obj.get('result')
  if obj.get('success') is not True:raise ValueError('SECONDARY_FINANCIAL_PROVIDER_FAILED')
  if result is None:result={'pages':1,'count':0,'data':[]}
  count=result.get('pages');total=result.get('count');data=result.get('data')
  if (type(count) is not int or count<1 or type(total) is not int or total<0 or not isinstance(data,list)
      or declared not in (None,count) or declared_count not in (None,total)):
   raise ValueError('SECONDARY_FINANCIAL_PAGINATION_CONFLICT')
  declared=count;declared_count=total;received_count+=len(data);page_numbers.append(number)
  for item in data:
   symbol=item.get('SECUCODE')
   if symbol not in request_scope:raise ValueError('SECONDARY_FINANCIAL_UNREQUESTED_SYMBOL')
   if str(item.get('SECURITY_CODE') or '')!=symbol[:6]:raise ValueError('SECONDARY_FINANCIAL_STOCK_CONFLICT')
   period=day(item.get('REPORT_DATE'))
   if symbol in records and period is not None and period<=observation:records[symbol].append((period,item,page))
 if sorted(page_numbers)!=list(range(1,declared+1)) or received_count!=declared_count:
  raise ValueError('SECONDARY_FINANCIAL_PAGES_INCOMPLETE')
 result={}
 for symbol in symbols:
  try:result[symbol]=_normalize_secondary_financial_rows(symbol,records[symbol],pages,normalizer_ref,day)
  except ValueError as error:result[symbol]={'symbol':symbol,'status':'CANNOT_CONFIRM','reason':str(error),
                                             'source_refs':[p['raw_ref'] for p in pages],'historical_PIT':False,**FLAGS}
 return result


def _normalize_secondary_financial_rows(symbol, records, pages, normalizer_ref, day):
 if not records:return {'symbol':symbol,'status':'NO_REPORTED_FINANCIALS','reason':'NO_MATCHED_PERIOD_IN_PROVIDER_RESPONSE',
                        'source_refs':[p['raw_ref'] for p in pages],'historical_PIT':False,**FLAGS}
 latest=max(x[0] for x in records);candidates=[x for x in records if x[0]==latest]
 fields=('TOTALOPERATEREVE','PARENTNETPROFIT','NETCASH_OPERATE_PK','CURRENCY','REPORT_TYPE')
 if len({canonical({k:item.get(k) for k in fields}) for _,item,_ in candidates})!=1:
  raise ValueError('SECONDARY_FINANCIAL_PERIOD_CONFLICT:'+symbol)
 _,row,page=candidates[0]
 def amount(key):
  value=row.get(key)
  if value is None:return None
  if isinstance(value,bool):raise ValueError('SECONDARY_FINANCIAL_NUMBER_INVALID:'+key)
  try:number=Decimal(str(value))
  except Exception:raise ValueError('SECONDARY_FINANCIAL_NUMBER_INVALID:'+key) from None
  if not number.is_finite():raise ValueError('SECONDARY_FINANCIAL_NUMBER_INVALID:'+key)
  return str(number)
 notices={str(day(item.get('NOTICE_DATE'))) for _,item,_ in candidates if day(item.get('NOTICE_DATE')) is not None}
 disclosed=next(iter(notices)) if len(notices)==1 else None
 finance={'evidence_status':'SECONDARY_REPORTED','latest_report_period':str(latest),'latest_period_kind':row.get('REPORT_TYPE'),
          'latest_disclosed_at':disclosed,'disclosure_date_precision':'DAY_PROVIDER_NOTICE_DATE_NOT_FIRST_PUBLICATION_CERTIFIED',
          'latest_revenue':amount('TOTALOPERATEREVE'),'latest_revenue_label':'营业总收入',
          'latest_net_profit_parent':amount('PARENTNETPROFIT'),'operating_cash_flow':amount('NETCASH_OPERATE_PK'),
          'operating_cash_flow_basis':'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES','monetary_unit':'元',
          'currency':row.get('CURRENCY') or None,'latest_financial_source_url':page['url'],
          'source_captured_at':page['captured_at'],'source_sha256':page['raw_ref']['sha256'],
          'source_field':'NETCASH_OPERATE_PK','field_semantics_ref':normalizer_ref,'historical_PIT':False}
 return {'symbol':symbol,'status':'OBSERVED','financials_reported':finance,
         'source_refs':{'secondary_finance':{'kind':'SECONDARY_PUBLIC_STRUCTURED','file':page['raw_ref'],'url':page['url']}},
         'source_pages':[{'page':p['page'],'raw_ref':p['raw_ref'],'url':p['url'],'captured_at':p['captured_at']} for p in pages],
         'historical_PIT':False,**FLAGS}


def normalize_secondary_financials(symbol, pages, *, observation_date, normalizer_ref):
 result=normalize_secondary_financial_batch([symbol],pages,observation_date=observation_date,normalizer_ref=normalizer_ref)[symbol]
 if result['status']=='CANNOT_CONFIRM':raise ValueError(result['reason'])
 return result


def _company_decimal(value):
 if isinstance(value,bool) or value is None:raise ValueError('COMPANY_REPORTED_NUMBER_INVALID')
 try:number=Decimal(str(value).replace(',',''))
 except Exception:raise ValueError('COMPANY_REPORTED_NUMBER_INVALID') from None
 if not number.is_finite():raise ValueError('COMPANY_REPORTED_NUMBER_INVALID')
 return number


def _legacy_company_observation(index,symbol,ref):
 """Rebind a prior-generation secondary card without claiming its raw response."""
 card=json.loads(checked(ref).read_bytes());finance=card.get('financials_reported') or {}
 if (card.get('schema_version')!='v4.a_share.company_materials.v1' or card.get('symbol')!=symbol
     or card.get('data_date')!=index.get('data_date') or card.get('source_generation')!=index.get('source_generation')
     or card.get('input_sha256')!=index.get('input_sha256') or card.get('numeric_manifest')!=index.get('source_numeric_manifest')
     or card.get('source_refs')!=index.get('source_refs') or any(card.get(k) is not v for k,v in FLAGS.items())):
  raise ValueError('COMPANY_LEGACY_CARD_IDENTITY_CONFLICT:'+symbol)
 period=finance.get('latest_report_period');periods=card.get('provenance_details',{}).get('financial_periods') or []
 matches=[x for x in periods if x.get('report_period')==period]
 metric=matches[0].get('metrics',{}).get('operating_cashflow') if len(matches)==1 else None
 if (not isinstance(metric,dict) or metric.get('evidence_status')!='SECONDARY_REPORTED'
     or metric.get('asof_date')!=period or metric.get('unit')!='元' or finance.get('monetary_unit')!='元'
     or _company_decimal(metric.get('value'))!=_company_decimal(finance.get('latest_operating_cashflow'))
     or not re.fullmatch(r'[a-f0-9]{64}',str(metric.get('source_sha256','')))
     or not isinstance(metric.get('source_url'),str) or not metric['source_url'].startswith('https://')
     or metric.get('source_url')!=finance.get('latest_financial_source_url')
     or 'NETCASH_OPERATE_PK' not in str(metric.get('page_or_section',''))):
  raise ValueError('COMPANY_LEGACY_FINANCIAL_PROVENANCE_CONFLICT:'+symbol)
 result={**finance,'evidence_status':'SECONDARY_REPORTED','operating_cash_flow':finance['latest_operating_cashflow'],
         'operating_cash_flow_basis':'PROVIDER_REPORTED_UNCONFIRMED_SCOPE','source_captured_at':metric.get('queried_at'),
         'source_sha256':metric['source_sha256'],'source_raw_status':'NOT_AVAILABLE_IN_BOUND_MATERIAL',
         'historical_PIT':False}
 for key,provenance_key in (('latest_revenue','revenue'),('latest_net_profit_parent','net_profit_parent')):
  evidence=matches[0].get('metrics',{}).get(provenance_key) or {};reported=finance.get(key)
  try:consistent=(reported is not None and evidence.get('asof_date')==period and evidence.get('unit')=='元'
                  and _company_decimal(evidence.get('value'))==_company_decimal(reported))
  except ValueError:consistent=False
  if not consistent:result[key]=None
  elif key=='latest_revenue':
   result['latest_revenue_label']=('营业总收入' if 'TOTALOPERATEREVE' in str(evidence.get('page_or_section',''))
                                    else '营收已报值（具体口径待核）')
 holders=card.get('shareholders_reported') or {};history=card.get('provenance_details',{}).get('shareholder_count_history') or []
 rows=[x for x in history if x.get('asof_date')==holders.get('holder_asof')]
 if holders.get('holder_count') is not None and len(rows)==1:
  evidence=rows[0].get('holder_count') or {}
  if (evidence.get('unit')=='户' and evidence.get('asof_date')==holders.get('holder_asof')
      and _company_decimal(evidence.get('value'))==_company_decimal(holders['holder_count'])
      and evidence.get('source_url')==holders.get('holder_source_url')):
   holders={**holders,'evidence_status':'SECONDARY_REPORTED','source_raw_status':'NOT_AVAILABLE_IN_BOUND_MATERIAL'}
  else:holders={}
 else:holders={}
 sources={'secondary_card':{'kind':'SECONDARY_CARD_REPORTED_RAW_UNAVAILABLE','file':ref,'url':metric['source_url']}}
 if holders:sources['secondary_holders']={'kind':'SECONDARY_CARD_REPORTED_RAW_UNAVAILABLE','file':ref,'url':holders['holder_source_url']}
 return result,holders,sources


def _official_company_observation(symbol,item):
 """Bind the captured filing and its independently extracted exact cash value."""
 source_ref=item.get('source_ref') or {};pdf=checked(source_ref).read_bytes()
 if not pdf.startswith(b'%PDF-') or not str(item.get('source_url','')).startswith('https://'):
  raise ValueError('COMPANY_OFFICIAL_SOURCE_INVALID:'+symbol)
 period=item.get('report_period_end');start=item.get('period_start');unit=item.get('original_unit')
 try:
  period_date=datetime.strptime(period,'%Y-%m-%d').date();start_date=datetime.strptime(start,'%Y-%m-%d').date()
 except (TypeError,ValueError):raise ValueError('COMPANY_OFFICIAL_PERIOD_INVALID:'+symbol) from None
 factors={'YUAN_AS_STATED':1,'CNY_YUAN':1,'CNY_THOUSAND':1000,'CNY_MILLION':1000000}
 if (item.get('symbol')!=symbol or item.get('statement_scope')!='CONSOLIDATED_GROUP' or unit not in factors
     or start_date!=period_date.replace(month=1,day=1) or item.get('historical_PIT') is not False
     or _company_decimal(item.get('original_value'))*factors[unit]!=_company_decimal(item.get('normalized_yuan_exact'))):
  raise ValueError('COMPANY_OFFICIAL_EVIDENCE_CONFLICT:'+symbol)
 facts_ref=item.get('facts_ref')
 if facts_ref:
  facts=json.loads(checked(facts_ref).read_bytes());values=facts.get('normalized_values_yuan') or {}
  if (facts.get('symbol')!=symbol or facts.get('source')!=source_ref or facts.get('report_period_end')!=period
      or facts.get('statement_scope')!='CONSOLIDATED_GROUP' or facts.get('original_unit')!=unit
      or facts.get('operating_cash_flow_basis')!='NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES'
      or _company_decimal(values.get('operating_cash_flow'))!=_company_decimal(item['normalized_yuan_exact'])):
   raise ValueError('COMPANY_OFFICIAL_FACTS_CONFLICT:'+symbol)
  revenue=values.get('latest_revenue');net=values.get('latest_net_profit_parent')
 else:
  received=json.loads(checked(item['existing_received_company_ref']).read_bytes());old=received.get('financials_reported') or {}
  if (received.get('symbol')!=symbol or old.get('latest_report_period')!=period
      or _company_decimal(old.get('operating_cash_flow'))!=_company_decimal(item['normalized_yuan_exact'])):
   raise ValueError('COMPANY_OFFICIAL_EXISTING_CONFLICT:'+symbol)
  revenue=old.get('latest_revenue');net=old.get('latest_net_profit_parent')
 finance={'evidence_status':'OFFICIAL_FILING','latest_report_period':period,'latest_period_kind':item.get('period_kind') or '官方财务报告',
          'latest_disclosed_at':item.get('disclosure_date'),'disclosure_date_precision':'SOURCE_INDEX_DATE_ONLY',
          'latest_revenue':revenue,'latest_net_profit_parent':net,'operating_cash_flow':item['normalized_yuan_exact'],
          'operating_cash_flow_basis':'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES','monetary_unit':'元',
          'currency':item.get('currency'),'latest_financial_source_url':item['source_url'],
          'source_captured_at':item.get('source_capture_at_utc') or item.get('original_capture_time'),
          'source_date_evidence':item.get('disclosure_date_evidence') or [],'historical_PIT':False}
 source={'kind':'COMPANY_FILING','file':source_ref,'url':item['source_url'],'available_date':item.get('disclosure_date')}
 return finance,source


def materialize_research_company_scope(context, *, listing_ref, exception_ref, secondary_checkpoint_ref,
                                       old_company_index_ref, official_batch_ref, output_root, requested=None):
 """Project verified received company observations through the existing daily owner."""
 from ops.research_panel_f10 import bound_research_universe
 context.unchanged()
 universe,scope=bound_research_universe(context,listing_ref=listing_ref,exception_ref=exception_ref)
 context.unchanged()
 root=Path(output_root).resolve(strict=True)
 if root.is_relative_to(context.data_root.resolve()):raise ValueError('COMPANY_RESEARCH_OUTPUT_NOT_ISOLATED')
 checkpoint=json.loads(checked(secondary_checkpoint_ref).read_bytes());run=checkpoint.get('identity') or {}
 if (run.get('source_scope')!=scope or run.get('old_company_index')!=old_company_index_ref
     or run.get('official_batch')!=official_batch_ref
     or run.get('source_date')!=datetime.strptime(str(context.target),'%Y%m%d').strftime('%Y-%m-%d')
     or not isinstance(checkpoint.get('items'),dict) or checkpoint.get('failures')):
  raise ValueError('COMPANY_RESEARCH_CHECKPOINT_CONFLICT')
 checked(run['owner']);normalizer_ref=run['normalizer'];checked(normalizer_ref)
 old=json.loads(checked(old_company_index_ref).read_bytes());batch=json.loads(checked(official_batch_ref).read_bytes())
 if (old.get('schema_version')!='v4.a_share.company_materials_index.v1' or not isinstance(old.get('items'),dict)
     or batch.get('schema')!='v4.a20.g02_bounded_official_evidence_batch.v1'
     or batch.get('historical_PIT') is not False or any(batch.get(k) is not v for k,v in FLAGS.items())):
  raise ValueError('COMPANY_RESEARCH_SOURCE_INDEX_CONFLICT')
 parent=json.loads(checked(scope['parent_index']).read_bytes());ready=set(universe)
 selected=ready if requested is None else set(requested)
 if not selected or not selected<=ready:raise ValueError('COMPANY_RESEARCH_REQUEST_OUTSIDE_SCOPE')
 matrix=list(csv.DictReader(io.StringIO(checked(run['source_matrix']).read_text(encoding='utf-8-sig'))))
 prior_symbols={row['symbol'] for row in matrix if row.get('company_status')=='READY'} & selected
 priors={}
 for symbol in prior_symbols:
  wrapper=json.loads(checked(parent['symbols'][symbol]['binding']).read_bytes())
  stock=json.loads(checked(wrapper['origin_binding']).read_bytes());detail=stock.get('details',{}).get('company') or {}
  asset=detail.get('asset') or {};compressed=checked(asset).read_bytes()
  if len(compressed)>2*1024*1024:raise ValueError('COMPANY_PRIOR_ASSET_TOO_LARGE')
  raw=gzip.decompress(compressed)
  if len(raw)>8*1024*1024 or len(raw)!=asset.get('decoded_bytes'):raise ValueError('COMPANY_PRIOR_ASSET_SIZE_CONFLICT')
  value=json.loads(raw)
  if (stock.get('symbol')!=symbol or detail.get('status')!='READY' or value.get('symbol')!=symbol
      or value.get('data_date')!=str(context.target) or value.get('source_generation')!=context.generation
      or value.get('input_sha256')!=context.identity['input_sha256'] or value.get('numeric_manifest')!=parent['numeric_manifest']
      or value.get('historical_PIT') is not False or any(value.get(k) is not v for k,v in FLAGS.items())):
   raise ValueError('COMPANY_PRIOR_ASSET_IDENTITY_CONFLICT:'+symbol)
  priors[symbol]=(value,detail.get('source_checks') or {},asset)
 official={x['symbol']:x for x in batch.get('data',[]) if x.get('source_ref') and x.get('symbol') in ready}
 old_symbols=set(old['items'])&ready;new=set(checkpoint['items'])
 if new!=(ready-old_symbols-set(official)):
  raise ValueError('COMPANY_RESEARCH_SOURCE_COVERAGE_CONFLICT')
 # Verify each shared provider response exactly once, then compare every saved projection.
 observations={};groups={};by_code={symbol[:6]:symbol for symbol in ready}
 if len(by_code)!=len(ready):raise ValueError('COMPANY_RESEARCH_DUPLICATE_CODE')
 for symbol,ref in checkpoint['items'].items():
  if symbol not in selected:continue
  value=json.loads(checked(ref).read_bytes());pages=value.get('source_pages') or []
  if value.get('symbol')!=symbol or not pages:raise ValueError('COMPANY_RESEARCH_OBSERVATION_INVALID:'+symbol)
  key=hashlib.sha256(canonical(pages)).hexdigest();groups.setdefault(key,{'pages':pages,'symbols':[]})['symbols'].append(symbol)
  observations[symbol]=value
 for group in groups.values():
  pages=[]
  for item in group['pages']:
   query=urllib.parse.parse_qs(urllib.parse.urlparse(item['url']).query)
   codes=re.findall(r'"(\d{6})"',(query.get('filter') or [''])[0])
   if not codes or any(code not in by_code for code in codes):raise ValueError('COMPANY_RESEARCH_QUERY_SCOPE_CONFLICT')
   pages.append({**item,'symbols':[by_code[code] for code in codes]})
  verified=normalize_secondary_financial_batch(group['symbols'],pages,observation_date=run['observation_date'],normalizer_ref=normalizer_ref)
  if any(canonical(verified[s])!=canonical(observations[s]) for s in group['symbols']):
   raise ValueError('COMPANY_RESEARCH_SOURCE_PROJECTION_CONFLICT')
 for ref in old.get('source_refs',{}).values():checked(ref)
 assets=root/'assets';assets.mkdir(exist_ok=True);entries={};issues={};counts=Counter()
 for symbol in sorted(selected):
  sources={};checks={};finance={};holders={};business={};stored=None;catalog=[]
  try:
   if symbol in priors:
    prior,prior_checks,prior_ref=priors[symbol];business=prior.get('business_reported') or {}
    holders=prior.get('shareholders_reported') or {};catalog=prior.get('report_catalog') or [];stored=prior.get('stored_report')
    for key,item in (prior.get('source_refs') or {}).items():
     try:checked(item['file']);sources[key]=item;checks[key]='VERIFIED' if prior_checks.get(key)=='VERIFIED' else 'UNKNOWN'
     except (KeyError,ValueError,OSError):checks[key]='UNKNOWN'
   if symbol in old_symbols:
    finance,old_holders,old_sources=_legacy_company_observation(old,symbol,old['items'][symbol])
    if old_holders:holders=old_holders
    sources.update(old_sources);checks.update({k:'VERIFIED' for k in old_sources})
   if symbol in observations:
    value=observations[symbol]
    if value.get('status')!='OBSERVED':raise ValueError('COMPANY_SECONDARY_NOT_OBSERVED')
    finance={**value['financials_reported'],'statement_scope':'PROVIDER_REPORTED_CONSOLIDATION_UNCONFIRMED'}
    sources.update(value['source_refs']);checks['secondary_finance']='VERIFIED'
   if symbol in official:
    verified,source=_official_company_observation(symbol,official[symbol])
    if finance and finance.get('latest_report_period')==verified['latest_report_period'] and finance.get('operating_cash_flow') is not None:
     if _company_decimal(finance['operating_cash_flow'])!=_company_decimal(verified['operating_cash_flow']):
      raise ValueError('COMPANY_OFFICIAL_SECONDARY_CONFLICT')
    finance=verified;sources['official_quarterly']=source;checks['official_quarterly']='VERIFIED'
   if not finance:raise ValueError('COMPANY_FINANCIAL_SOURCE_UNAVAILABLE')
   payload={'schema_version':'v4.a_share.company_materials.v1','symbol':symbol,'data_date':str(context.target),
       'observation_date':run['observation_date'],'source_generation':context.generation,
       'input_sha256':context.identity['input_sha256'],'numeric_manifest':parent['numeric_manifest'],
       'source_candidate_generation':parent['candidate_generation'],'business_reported':business,
       'financials_reported':finance,'shareholders_reported':holders,'report_catalog':catalog,'stored_report':stored,
       'f10':prior.get('f10') if symbol in priors else None,
       'source_refs':sources,'source_lineage':{'scope':scope,'secondary_checkpoint':secondary_checkpoint_ref,
            'prior_company_asset':prior_ref if symbol in priors else None,
            'old_company_index':old_company_index_ref if symbol in old_symbols else None,
            'official_batch':official_batch_ref if symbol in official else None},
       'historical_PIT':False,**FLAGS}
   raw=canonical(payload);compressed=gzip.compress(raw,mtime=0);digest_raw=hashlib.sha256(compressed).hexdigest()
   path=assets/(symbol+'_'+digest_raw[:16]+'.json.gz')
   if path.exists():
    if path.read_bytes()!=compressed:raise ValueError('COMPANY_IMMUTABLE_CONFLICT')
   else:
    with path.open('xb') as handle:handle.write(compressed);handle.flush();os.fsync(handle.fileno())
   asset={'path':str(path),'sha256':digest_raw,'bytes':len(compressed),'decoded_bytes':len(raw),'encoding':'gzip'}
   entries[symbol]={'status':'READY','asset':asset,'source_candidate_generation':parent['candidate_generation'],'source_checks':checks}
   counts[finance['evidence_status']]+=1
  except (ValueError,KeyError,TypeError,OSError) as error:
   entries[symbol]={'status':'UNKNOWN','reason':type(error).__name__+': '+str(error)};issues[symbol]=entries[symbol]['reason']
 index={'schema_version':'v4.a_share.company_materials_index.v1','status':'COMPLETE' if not issues else 'PARTIAL',
        'data_date':str(context.target),'source_generation':context.generation,'input_sha256':context.identity['input_sha256'],
        'numeric_manifest':parent['numeric_manifest'],'source_candidate_generation':parent['candidate_generation'],
        'scope_kind':'G2_RESEARCH_TARGET_READY' if requested is None else 'EXPLICIT_SYMBOLS_RESEARCH',
        'research_scope':scope,'secondary_checkpoint':secondary_checkpoint_ref,'old_company_index':old_company_index_ref,
        'official_batch':official_batch_ref,'items':entries,'counts':dict(counts),'issues':issues,
        'historical_PIT':False,**FLAGS}
 context.unchanged()
 producer=Path(__file__).resolve(strict=True);producer_raw=producer.read_bytes();producer_sha=hashlib.sha256(producer_raw).hexdigest()
 frozen=root/('COMPANY_DAILY_OWNER_'+producer_sha+'.py')
 if frozen.exists():
  if frozen.read_bytes()!=producer_raw:raise ValueError('COMPANY_RESEARCH_OWNER_CONFLICT')
 else:frozen.write_bytes(producer_raw)
 index['producer']={'path':str(frozen),'sha256':producer_sha}
 index_ref=save(root/'index.json',index,immutable=True)
 return {'status':index['status'],'index':index_ref,'ready':sum(x['status']=='READY' for x in entries.values()),
         'unknown':len(issues),'counts':dict(counts),'issues':issues}


def module(r,name):
 p=checked(r);raw=p.read_bytes();spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;exec(compile(raw,str(p),'exec'),m.__dict__);return m

def iso(d):return datetime.strptime(str(d),'%Y%m%d').strftime('%Y-%m-%d')
def tristate(v):return 'TRUE' if v is True else 'FALSE' if v is False else 'UNKNOWN'
def config():
 p=Path(os.environ.get('V4_RESEARCH_DAILY_PRODUCT_CONFIG') or CONFIG);v=json.loads(p.read_text())
 if v.get('schema')!='research_daily_product_sources.v1':raise ValueError('DAILY_SOURCE_CONFIG_SCHEMA')
 for k in ('engine','formula','tri_state_core','admission_helper','census'):checked(v[k])
 for ref in v.get('dated_g4_packages',{}).values():checked(ref)
 if v.get('future_calendar'):checked(v['future_calendar'])
 return v,reference(p)

def _census(r,asof,observation):
 p=checked(r);tree=ast.parse(p.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='analyze')
 class BindDate(ast.NodeTransformer):
  def visit_Constant(self,node):
   if type(node.value) is int and node.value in (20261027,20261028):return ast.copy_location(ast.Constant(asof if node.value==20261027 else observation),node)
   # Keep the reviewed R5 descriptor namespace stable; values carry actual dates.
   if isinstance(node.value,str):return ast.copy_location(ast.Constant(node.value.replace('D27','D28').replace('D26','D27')),node)
   return node
 env={'math':math};exec(compile(ast.fix_missing_locations(ast.Module(body=[BindDate().visit(fn)],type_ignores=[])),str(p),'exec'),env);return env['analyze']

class SourceContext:
 def __init__(self,data_root,target,*,source_config=None):
  from ops.research_panel_qfq import panel_contract
  self.data_root=Path(data_root).resolve();self.target=int(target);self.config,self.config_ref=(source_config if source_config else config());self.root=self.data_root/'daily_products/a_share'
  self.pointer=self.data_root/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';self.backpointer=self.data_root/'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt';self.pointer_bytes=self.pointer.read_bytes();self.back_bytes=self.backpointer.read_bytes()
  self.panel=Path(self.pointer_bytes.decode('utf-8-sig').strip());self.footer=panel_contract(self.panel);back=panel_contract(Path(self.back_bytes.decode('utf-8-sig').strip()))
  if self.footer.get('asof_date')!=self.target or self.footer.get('generation_id')!=back.get('generation_id'):raise ValueError('DAILY_PAIRED_GENERATION_OR_DATE_CONFLICT')
  self.generation=self.footer['generation_id'];self.receipt_ref=reference(Path(self.footer['generation_manifest_path']));self.receipt=json.loads(checked(self.receipt_ref).read_text());self.snapshot_ref=self.receipt['adjustment_snapshot'];self.snapshot=json.loads(checked(self.snapshot_ref).read_text());self.quarantine_ref=self.receipt['quarantine_manifest'];self.quarantine=json.loads(checked(self.quarantine_ref).read_text())
  if self.receipt.get('generation_id')!=self.generation or self.quarantine.get('generation_id')!=self.generation or self.snapshot.get('asof_date')!=self.target:raise ValueError('DAILY_RECEIPT_SNAPSHOT_IDENTITY_CONFLICT')
  if (self.footer.get('snapshot_file_sha256')!=self.snapshot_ref['sha256'] or self.receipt.get('snapshot_file_sha256')!=self.snapshot_ref['sha256'] or self.receipt['candidates']['selector']!=str(self.panel)):raise ValueError('DAILY_SNAPSHOT_SHA_CONFLICT')
  self.scope=sorted(self.snapshot.get('original_target_codes') or self.snapshot['symbols'])
  if len(self.scope)!=len(set(self.scope)) or not self.scope:raise ValueError('DAILY_PROCESSED_UNIVERSE_INVALID')
  self.panel_stat=self.panel.stat();self.identity=dict(generation=self.generation,input_sha256=self.footer['input_sha256'],snapshot=self.snapshot_ref,selector_artifact_sha256=self.receipt['candidate_sha256']['selector'],asof=self.target,basis=self.footer['market_basis']['A'],historical_PIT=False)
  self.helper=module(self.config['admission_helper'],'dated_original_admission');self.hash_cache={};original_read=self.helper.read_json;self.helper.read_json=lambda p:self.snapshot if Path(p)==Path(self.snapshot_ref['path']) else original_read(p);self.helper.sha256_file=self.cached_sha
  reader=self.pointer.with_name('DATA_LAYER_INTERFACE.py');self.reader_ref=reference(reader);self.reader=module(self.reader_ref,'dated_original_shared_reader');self._engine=None;self.calendars=self._calendars();self._g4={}
 def cached_sha(self,p):
  p=Path(p);s=p.stat();stamp=(s.st_size,s.st_mtime_ns,s.st_ino)
  if str(p) in self.hash_cache:
   old,h=self.hash_cache[str(p)]
   if old!=stamp:raise ValueError('DAILY_REFERENCE_CHANGED:'+str(p))
   return h
  h=sha(p);self.hash_cache[str(p)]=(stamp,h);return h
 def unchanged(self):
  s=self.panel.stat()
  if self.pointer.read_bytes()!=self.pointer_bytes or self.backpointer.read_bytes()!=self.back_bytes or (s.st_size,s.st_mtime_ns,s.st_ino)!=(self.panel_stat.st_size,self.panel_stat.st_mtime_ns,self.panel_stat.st_ino):raise ValueError('DAILY_GENERATION_CHANGED_DURING_PROJECTION')
 def _calendars(self):
  import pyarrow.parquet as pq
  dates={e:set() for e in ('SH','SZ','BJ')}
  for batch in pq.ParquetFile(self.panel).iter_batches(columns=['exchange','trade_date'],batch_size=131072):
   for e,d in zip(batch.column(0).to_pylist(),batch.column(1).to_pylist()):
    if e in dates and int(d)<=self.target:dates[e].add(int(d))
  if self.config.get('future_calendar'):
   pinned=json.loads(checked(self.config['future_calendar']).read_text());periods=pinned['markets']['a_share']['holiday_periods'];day=datetime.strptime(str(self.target),'%Y%m%d')+timedelta(days=1)
   while day.year==pinned['year']:
    if day.weekday()<5 and not any(v['start']<=day.strftime('%Y%m%d')<=v['end'] for v in periods):
     for values in dates.values():values.add(int(day.strftime('%Y%m%d')))
    day+=timedelta(days=1)
  return {e:sorted(v) for e,v in dates.items()}
 def qualify(self,symbol):return self.helper.verify_symbol_admission(symbol,str(self.target),self.footer,self.receipt,self.quarantine,self.generation,Path(self.quarantine_ref['path']))
 def read(self,symbol):
  frame=self.reader.load_selector_ready(columns=['ts_code','trade_date','name','market_type','exchange','open','high','low','close','volume'],filters=[('ts_code','=',symbol),('trade_date','<=',str(self.target))],panel_path=self.panel,profile=None).sort_values('trade_date',kind='stable')
  if frame.empty:return [],None
  if frame.trade_date.duplicated().any() or not frame.ts_code.eq(symbol).all() or not frame.exchange.astype(str).eq(symbol[-2:]).all() or not set(frame.market_type.astype(str))<={'A_SHARE','BJ'}:raise ValueError('DAILY_SYMBOL_PREFIX_CONFLICT:'+symbol)
  bars=[dict(trade_date=int(r.trade_date),open=str(r.open),high=str(r.high),low=str(r.low),close=str(r.close),vol=str(r.volume)) for r in frame.itertuples()]
  names=frame.name[frame.name.map(lambda value:isinstance(value,str) and bool(value.strip()))]
  name=names.iloc[-1].strip() if len(names) else None
  return bars,name
 def engine(self):
  if self._engine is None:self._engine=module(self.config['engine'],'dated_exact_original_engine');self.core=module(self.config['tri_state_core'],'dated_original_tristate')
  return self._engine
 def g4_reference(self,symbol,date,qualification):
  # Source is an existing bound dated package; never fetch in this projection.
  date=int(date);pin=self.config.get('dated_g4_packages',{}).get(str(date))
  if pin is None:
   syncpath=Path(os.environ.get('V4_RESEARCH_PANEL_RECEIPT_ROOT') or self.data_root.parent.parent/'research_panel_daily/receipts')/'a_sync_authority/official_daily'/str(date)/'input.json'
   if syncpath.is_file():pin=json.loads(syncpath.read_text()).get('package')
  if pin is None:return dict(date=date,correspondence_status='UNKNOWN',reason='RAW_G4_PREV_CLOSE_SOURCE_MISSING')
  if date not in self._g4:
   from ops._a_share_daily_sync_parts.official_daily_package import parse_package
   p=checked(pin);raw=p.read_bytes();parsed,_=parse_package(raw,date);values={}
   with zipfile.ZipFile(p) as z:
    blocks={name:z.read(name) for name in {lineage['md1_member']['name'] for _,lineage,_ in parsed.values()}}
    for (market,code),(bar,lineage,volume) in parsed.items():
     block=blocks[lineage['md1_member']['name']];previous=struct.unpack_from('<d',block,lineage['md1_byte_offset']+4)[0];values[code+'.'+{0:'SZ',1:'SH',2:'BJ'}[market]]=dict(date=date,close=bar['close'],prev_close=previous,ohlc={k:bar[k] for k in ('open','high','low','close')},source=pin)
   self._g4[date]=values
  value=self._g4[date].get(symbol)
  if value is None:return dict(date=date,correspondence_status='UNKNOWN',reason='RAW_G4_SYMBOL_ABSENT')
  matches=[]
  for r in qualification.get('verified_raw_sources',[]):
   raw=checked(r).read_bytes()
   for off in range(0,len(raw),32):
    if struct.unpack_from('<I',raw,off)[0]==date:
     prices=struct.unpack_from('<4I',raw,off+4);matches.append(all(Decimal(str(value['ohlc'][k])).quantize(Decimal('.01'))==Decimal(v)/100 for k,v in zip(('open','high','low','close'),prices)))
  return dict(value,correspondence_status='TRUE' if matches and all(matches) else 'UNKNOWN',reason=None if matches and all(matches) else 'RAW_G4_NATIVE_PARITY_UNCONFIRMED')

def source_inputs(context,symbol,bars,asof,qualification,*,retain=None):
 """Original formula/AST only; caller controls registered real computation."""
 engine=context.engine();result=engine.compute(bars,'prefix');
 if retain is not None:retain(result)
 rows=result['rows'];last=rows[-1];signals=context.core.signals(last['values']);breakout={r['trade_date']:tristate(engine.boolean(r['values'].get('突破'))) for r in rows}
 answer=dict(symbol=symbol,rows=rows,source_bar_exact={'amount':0},index_sha256=context.config_ref['sha256'])
 summary,_=_census(context.config['census'],asof,asof)(answer);stage=summary.get('stage','UNKNOWN');known=not stage.startswith('UNKNOWN')
 baseline=dict(original={'YES':'TRUE','NO':'FALSE','UNKNOWN':'UNKNOWN'}[signals['membership']],nav_pullback='UNKNOWN' if not known else 'TRUE' if stage in {'D28_RECOVERY_BELOW_KEY_HIGH','PULLBACK_SUPPORT_OBSERVATION_NOT_CONFIRMED'} else 'FALSE',nav_breakout='UNKNOWN' if not known else 'TRUE' if stage in {'D28_BREAKOUT','ABOVE_KEY_CONTINUATION_DISTANCE_DISCLOSED'} else 'FALSE')
 return dict(original_breakout_by_date=breakout,baseline_memberships=baseline,old_main_anchor_date=summary.get('main_anchor_date'),qualification_status=qualification['status'],raw_g4_reference=context.g4_reference(symbol,asof,qualification))

def compute_stock(context,symbol,*,evaluate=None,history_dates=(),chart_capture=None):
 from domains.research_daily_product import evaluate_daily_product
 from domains.research_daily_statistics import build_daily_event_statistics
 evaluate=evaluate or evaluate_daily_product;bars,name=context.read(symbol);q=context.qualify(symbol);target=context.target;calendar=context.calendars[symbol[-2:]];rule_sha=sha(Path(__file__).resolve().parents[1]/'domains/research_daily_product.py')
 if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' and (not bars or bars[-1]['trade_date']!=target or str(bars[0]['trade_date'])!=q['history_start_date']):q=dict(status='UNKNOWN',reason='ADMITTED_PREFIX_START_OR_TARGET_MISMATCH')
 captured=[]
 current_inputs=source_inputs(context,symbol,bars,target,q,**({'retain':captured.append} if chart_capture is not None else {})) if bars and q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
 current=evaluate(symbol=symbol,asof=target,fullprefix=bars,exchange_calendar=calendar,**current_inputs)
 history_root=context.root/'history'/rule_sha/symbol;cachefile=history_root/'checkpoint.json';cache=json.loads(cachefile.read_text()) if cachefile.is_file() else dict(rule_sha256=rule_sha,evaluations={},price_prefix_dates=[])
 rules_signature=digest(context.config)
 if cache.get('rules_signature',rules_signature)!=rules_signature or q['status']!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['rules_signature']=rules_signature
 old_end=max(map(int,cache['evaluations']),default=0);old_prefix=[b for b in bars if b['trade_date']<=old_end]
 if cache.get('prefix_sha256') and digest(old_prefix)!=cache['prefix_sha256']:cache=dict(rule_sha256=rule_sha,evaluations={},invalidated_previous_source=True)
 cache['evaluations'][str(target)]=dict(groups={g:current['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True)
 # Current admission authorizes this full prefix; each historical formula is
 # recomputed on its own slice. This is descriptive replay, never historical PIT.
 for day in history_dates:
  day=int(day)
  if day>=target or str(day) in cache['evaluations']:continue
  prefix=[b for b in bars if b['trade_date']<=day]
  if not prefix or prefix[-1]['trade_date']!=day:continue
  inputs=source_inputs(context,symbol,prefix,day,q) if q['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' else dict(original_breakout_by_date={},baseline_memberships={},old_main_anchor_date=None,qualification_status=q['status'],raw_g4_reference=None)
  earlier=evaluate(symbol=symbol,asof=day,fullprefix=prefix,exchange_calendar=calendar,**inputs)
  cache['evaluations'][str(day)]=dict(groups={g:earlier['groups'][g]['status'] for g in GROUPS},source_identity=context.identity,qualification=q,exact_full_conditions=True,historical_PIT=False,historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION')
 evaluated=sorted(map(int,cache['evaluations']));expected=[b['trade_date'] for b in bars];complete=set(expected)<=set(evaluated)
 cache['prefix_sha256']=digest(bars);cache['source_identity']=context.identity;cache['coverage']=dict(requested_start=bars[0]['trade_date'] if bars else None,requested_end=target,evaluated_dates=evaluated,evaluated_count=len(evaluated),available_prefix_dates=len(expected),known_full_history=complete,historical_PIT=False,maximum_claim='DIRECTION_ONLY',historical_qualification_basis='CURRENT_GENERATION_FULL_PREFIX_NOT_HISTORICAL_ASOF_CERTIFICATION',unknown_by_group={g:sum(r['groups'][g]=='UNKNOWN' for r in cache['evaluations'].values()) for g in GROUPS},missing=[] if complete else ['HISTORICAL_FULL_CONDITION_BOOTSTRAP'])
 identity=dict(generation=context.generation,input=context.identity['input_sha256'],formula=context.config['formula']['sha256'],rule_sha256=rule_sha,asof=iso(target),market=symbol[-2:],basis='QFQ_ASOF',pit_status='NONPIT')
 groups=[dict(group_id=g,event_dates=[iso(int(d)) for d,r in sorted(cache['evaluations'].items()) if r['groups'][g]=='TRUE'],rule_sha256=rule_sha,source_identity=identity) for g in GROUPS]
 statistics=build_daily_event_statistics(close_rows=[dict(date=iso(b['trade_date']),close=float(b['close']) if b['close'] is not None else None) for b in bars],market_calendar=[iso(d) for d in calendar],asof=iso(target),event_groups=groups)
 row=dict(symbol=symbol,display_name=name,data_date=str(target),groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='TRUE'),pending_groups='|'.join(g for g in GROUPS if current['groups'][g]['status']=='UNKNOWN'),latest_new_anchor=str(next((current['groups'][g].get('anchor_date') for g in GROUPS if current['groups'][g].get('anchor_date')), '') or ''),reasons='|'.join(sorted({s for g in GROUPS for s in current['groups'][g].get('reasons',[])})),risk_clear=current.get('risk',{}).get('status','UNKNOWN'),evaluation=current,statistics=statistics,historical_coverage=cache['coverage'],qualification=q)
 if chart_capture is not None and row['groups'] and captured:chart_capture(symbol,bars,captured[0])
 return row,cache,cachefile

def materialize_daily_product(*,data_root,target,formula_result=None,symbols=None,history_dates=(),evaluate=None,output_root=None,original_charts=True,chart_png_renderer=None):
 """Called once from original run_a; no historical loop in normal daily mode."""
 context=SourceContext(data_root,target)
 if output_root is not None:context.root=Path(output_root).resolve()
 root=context.root;context.unchanged()
 if formula_result and (str(context.panel)!=str(formula_result['selector']) or formula_result['selector_sha256']!=context.receipt['candidate_sha256']['selector']):raise ValueError('DAILY_FORMULA_COMPLETION_IDENTITY_CONFLICT')
 selected=sorted(symbols if symbols is not None else context.scope)
 if not set(selected)<=set(context.scope):raise ValueError('DAILY_PROJECTION_OUTSIDE_PROCESSED_UNIVERSE')
 rows=[];row_refs={};runkey=digest(dict(identity=context.identity,config=context.config_ref,symbols=selected,history_dates=list(history_dates)));parts=root/'checkpoints'/str(target)/runkey
 chart_gaps={}
 def capture(symbol,bars,result):
  try:
   from ops.render_original_formula_projection import retain_owner_result
   retain_owner_result(context,parts,symbol,bars,result)
  except Exception as error:chart_gaps[symbol]='RETAINED_RESULT_UNAVAILABLE:'+str(error)
 for i,symbol in enumerate(selected):
  checkpoint=parts/(symbol+'.json')
  if checkpoint.is_file():row=json.loads(checkpoint.read_text())
  else:
   try:
    row,cache,path=compute_stock(context,symbol,evaluate=evaluate,history_dates=history_dates,**({'chart_capture':capture} if original_charts else {}));save(path,cache)
   except (ValueError,KeyError,TypeError,OSError) as error:
    row=dict(symbol=symbol,display_name=None,data_date=str(target),groups='',pending_groups='|'.join(GROUPS),latest_new_anchor='',reasons='SOURCE_ISOLATED:'+str(error),risk_clear='UNKNOWN',evaluation={'groups':{g:{'status':'UNKNOWN','reasons':['SOURCE_ISOLATED:'+str(error)]} for g in GROUPS}},statistics=None,historical_coverage={'known_full_history':False,'evaluated_count':0,'missing':['SOURCE_ISOLATED']},qualification={'status':'UNKNOWN','reason':str(error)})
   row.update(FLAGS);save(checkpoint,row,immutable=True)
  rows.append(row);row_refs[symbol]=reference(checkpoint);save(parts/'progress.json',dict(completed=i+1,total=len(selected),target_date=target,generation=context.generation,**FLAGS))
 context.unchanged();counts={g:dict(Counter(r['evaluation']['groups'][g]['status'] for r in rows)) for g in GROUPS};candidates=[r for r in rows if r['groups']];unknown=sum(bool(r['pending_groups']) for r in rows)
 product=dict(schema_version=SCHEMA,status='PARTIAL_WITH_ROWS' if unknown else 'READY',data_date=str(target),observation_date=None,source_generation=context.generation,source_identity=context.identity,source_config=context.config_ref,processed_universe=selected,processed_count=len(rows),source_universe_count=len(context.scope),sample_only=symbols is not None,unique_count=len(candidates),group_counts={g:counts[g].get('TRUE',0) for g in GROUPS},three_value_counts=counts,unknown_count=unknown,rows=[{k:v for k,v in row.items() if k in ('symbol','display_name','data_date','groups','pending_groups','latest_new_anchor','reasons','risk_clear')} for row in candidates],row_refs=row_refs,history_status='PARTIAL_NEEDS_BOOTSTRAP',history_bootstrap_in_daily_path=False,**FLAGS)
 content_sha=digest(product);version=root/'versions'/str(target)/context.generation/content_sha
 artifact=prepared_reference(version/'product.json',product)
 if save(version/'product.json',product,immutable=True)!=artifact:raise ValueError('DAILY_ARTIFACT_CHANGED_ON_SAVE')
 manifest=dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],snapshot=context.snapshot_ref,artifact=artifact,processed_count=len(rows),source_universe_count=len(context.scope),counts=counts,status=product['status'],sample_only=symbols is not None,history_status=product['history_status'],**FLAGS)
 manifest_ref=prepared_reference(version/'manifest.json',manifest)
 if save(version/'manifest.json',manifest,immutable=True)!=manifest_ref:raise ValueError('DAILY_MANIFEST_CHANGED_ON_SAVE')
 chart_descriptor=None
 if original_charts:
  try:
   from ops.render_original_formula_projection import finalize_owner_charts
   chart_descriptor=finalize_owner_charts(context,parts,product,manifest_ref,artifact,gaps=chart_gaps,png_renderer=chart_png_renderer)
  except Exception as error:
   chart_descriptor=dict(status='CANNOT_CONFIRM',numeric_manifest=manifest_ref,reason='CHART_FINALIZATION_FAILED:'+str(error))
 try:context.unchanged()
 except Exception as error:
  save(parts/'publication_error.json',dict(status='CANNOT_CONFIRM',reason='SOURCE_CHANGED_BEFORE_PUBLICATION:'+str(error),manifest=manifest_ref,artifact=artifact,original_charts=chart_descriptor,**FLAGS))
  raise
 chart_preselection=None
 if symbols is None:
  indexfile=root/'index.json';index=json.loads(indexfile.read_text()) if indexfile.is_file() else dict(schema_version='v4.a_share.daily_product_index.v1',dates={})
  index['dates'][str(target)]=manifest_ref;index['latest_date']=max(index['dates']);index['latest']=index['dates'][index['latest_date']]
  if chart_descriptor is not None:index.setdefault('original_charts',{})[str(target)]=chart_descriptor
  index_ref=prepared_reference(indexfile,index);save(indexfile,index)
  event=dict(schema_version='v4.a_share.daily_completion.v1',event_id=digest(manifest),data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],artifact=artifact,manifest=manifest_ref,processed_count=len(rows),source_universe_count=len(context.scope),unknown_count=unknown,status=product['status'],**FLAGS)
  if chart_descriptor is not None:
   event['original_charts']=chart_descriptor;event['event_id']=digest(dict(numeric_manifest=manifest_ref,original_charts=chart_descriptor))
  # Publish the ordinary numeric completion with an explicitly unconfirmed
  # chart projection.  If the subsequent nonblocking lock cannot be acquired,
  # no competing event is overwritten to manufacture a failure notification.
  chart_calendar_ref=None;chart_target=None
  try:
   from contracts.trading_calendar import CALENDAR_PATH,load_market_calendar,next_session
   chart_calendar_ref=reference(CALENDAR_PATH)
   chart_target=next_session(load_market_calendar(Path(chart_calendar_ref['path'])),str(target),market='a_share')
  except (OSError,ValueError,KeyError,TypeError):pass
  event['chart_preselection']=dict(status='CANNOT_CONFIRM',reason='CHART_POOL_UPDATE_NOT_CONFIRMED',pool_id=CHART_POOL_ID,
    target_date=chart_target,source_date=str(target),source_generation=context.generation,source_manifest_sha256=manifest_ref['sha256'])
  event['event_id']=digest(dict(previous_event_id=event['event_id'],chart_preselection=event['chart_preselection']))
  event_ref=prepared_reference(root/'events/latest.json',event);save(root/'events/latest.json',event)
  # Reuse this completion and the existing preselection store; never derive
  # membership again or mistake the next target session for the signal date.
  try:
   pool_root=os.environ.get('V4_PRESELECTION_SOURCE_ROOT') or os.environ.get('V35_PRESELECTION_SOURCE_ROOT') or os.environ.get('V4_DATA_ROOT')
   if not pool_root or not Path(pool_root).is_absolute() or not Path(pool_root).is_dir():
    raise ValueError('PRESELECTION_DATA_ROOT_NOT_CONFIGURED')
   if chart_calendar_ref is None:raise ValueError('CHART_POOL_CALENDAR_CANNOT_CONFIRM')
   chart_preselection=publish_chart_preselection_from_completion(root=root,pool_root=pool_root,calendar_ref=chart_calendar_ref,
    expected_index_ref=index_ref,expected_event_ref=event_ref,
    expected_identity=dict(data_date=str(target),source_generation=context.generation,input_sha256=context.identity['input_sha256'],manifest=manifest_ref,artifact=artifact))
  except (OSError,ValueError,KeyError,TypeError) as error:
   # Preserve the completed numeric product; an unbound chart lane must be
   # observable as a gap rather than falsely claiming that it was updated.
   chart_preselection=dict(status='CANNOT_CONFIRM',reason=str(error),pool_id=CHART_POOL_ID,target_date=chart_target,
    source_date=str(target),source_generation=context.generation,source_manifest_sha256=manifest_ref['sha256'])
 return dict(manifest=manifest_ref,artifact=artifact,status=product['status'],data_date=str(target),source_generation=context.generation,processed_count=len(rows),unique_count=len(candidates),unknown_count=unknown,history_status=product['history_status'],chart_preselection=chart_preselection,**FLAGS)
