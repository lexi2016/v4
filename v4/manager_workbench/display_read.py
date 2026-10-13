"""Read-only presentation projection. Saved snapshot hashes describe original bytes."""
import csv,hashlib,io,json,re
from infrastructure.owned_io import SafeRoot
from .inputs.validation import before

def checked_time(value,cutoff):
 if not before(value,cutoff):raise ValueError('DISPLAY_SOURCE_TIME_UNKNOWN_OR_LATE')


def saved_names(snapshot,root):
 if root is None:return {}
 try:
  pin=snapshot.context.scope_refs.get('owner_bindings',{}).get('security_master',{})
  io_root=SafeRoot(root);raw=io_root.read_bytes(pin['manifest_relative'])
  if hashlib.sha256(raw).hexdigest()!=pin['manifest_sha256']:return {}
  manifest=json.loads(raw);day=snapshot.context.source_sessions['hk_price']
  checked_time(manifest['captured_at'],snapshot.context.cutoff)
  if manifest['trade_date']!=day or manifest['schema_version']!='v3_shared_data.hk_security_master_manifest.v1':return {}
  for checked in pin.get('checked_files',[]):
   raw_receipt=io_root.read_bytes(checked['relative'])
   if hashlib.sha256(raw_receipt).hexdigest()!=checked['sha256']:return {}
   receipt=json.loads(raw_receipt)
   if receipt.get('manifest_sha256')!=pin['manifest_sha256']:return {}
  refs={e.artifact_ref:e for lane in snapshot.lanes for e in lane.evidence_refs if e.role=='HK_SECURITY_MASTER' and e.verification.value=='VERIFIED'}
  relative='assets/hk_security_master/'+manifest['artifact_relative'];ref=refs.get(relative)
  if ref is None or ref.sha256!=manifest['artifact_sha256'] or ref.source_session!=day or ref.manifest_ref!=pin['manifest_relative']:return {}
  checked_time(ref.available_at,snapshot.context.cutoff)
  raw=io_root.read_bytes(relative)
  if hashlib.sha256(raw).hexdigest()!=ref.sha256:return {}
  rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
  if len(rows)!=manifest['row_count'] or len({r['code'] for r in rows})!=len(rows):return {}
  out={}
  for r in rows:
   name=r.get('name','').strip();symbol=r['code']
   if re.fullmatch(r'HK\.[0-9]{5}',symbol) and name and name.lower() not in {'nan','null','none'}:
    out[symbol]=dict(name=name,name_source=dict(kind='SAVED_RUN_SECURITY_MASTER',owner=ref.owner,source_date=day,
      sha256=ref.sha256,manifest_sha256=pin['manifest_sha256'],artifact_ref=relative,available_at=ref.available_at,display_only=True))
  return out
 except (OSError,ValueError,KeyError,TypeError):return {}


def display_stock(stock,names):
 value=stock.model_dump(mode='json') if hasattr(stock,'model_dump') else dict(stock)
 if not value.get('name') and value.get('symbol') in names:value.update(names[value['symbol']])
 return value


def us_summary(snapshot,names):
 lane=next((l for l in snapshot.lanes if l.lane.value=='US_MAPPING'),None)
 if lane is None:return None
 groups={};relations=[]
 for original in lane.rows:
  row=dict(original);us=row.get('us_symbol')
  if not isinstance(us,str) or not us:continue
  if re.fullmatch(r'HK\.[0-9]{5}',str(row.get('symbol',''))):
   row=display_stock(row,names);relations.append(row)
  groups.setdefault(us,[]).append(row)
 out=[];counts={d:0 for d in ['SELECTED','CONDITIONAL_WATCH','NOT_SELECTED','UNASSESSED','OBSERVATION_ONLY']}
 mixed=0
 for us,rows in groups.items():
  decisions=list(dict.fromkeys(r.get('decision') for r in rows))
  if len(decisions)==1 and decisions[0] in counts:counts[decisions[0]]+=1
  else:mixed+=1
  out.append(dict(us_symbol=us,decisions=decisions,rows=rows))
 return dict(display_only=True,plan_run_id=snapshot.run_id,coverage=lane.coverage.model_dump(mode='json'),
  source_symbol_count=len(groups),source_row_count=len(lane.rows),relation_row_count=len(relations),
  mapped_hk_count=len({r['symbol'] for r in relations}),source_decision_counts=counts,mixed_source_count=mixed,groups=out,gaps=lane.gaps)


def lane_stock(snapshot,lane,index,names):
 """Present one original lane row; never inherit the merged stock decision."""
 row=lane.rows[index];symbol=row.get('symbol')
 if not re.fullmatch(r'HK\.[0-9]{5}',str(symbol)):return None
 value=display_stock(row,names)
 old=next((s for s in snapshot.stocks if s.symbol==symbol),None)
 if not value.get('name') and old is not None:value['name']=old.name
 member=row.get('membership') or {}
 value.update(market='HK_CONNECT',row_id=f'{lane.lane.value}:{index}',
  lane_decisions={lane.lane.value:[dict(row)]},reasons=[row.get('reason') or ''],
  conditions=list(row.get('conditions') or []),invalidation_conditions=list(row.get('invalidation_conditions') or []),
  risks=list(row.get('risks') or []),evidence_ids=list(row.get('evidence_ids') or []),
  membership_status='VERIFIED' if member.get('eligible') is True else 'CANNOT_CONFIRM',
  recommendation_lane=lane.lane.value,display_only=True)
 return value


def lane_projection(snapshot,lane_name,names,decision=None,q=None):
 lane=next((l for l in snapshot.lanes if l.lane.value==lane_name),None)
 if lane is None:return None
 counts={k:0 for k in ['selected','watch','unassessed','not_selected','observation_only']}
 keys=dict(SELECTED='selected',CONDITIONAL_WATCH='watch',UNASSESSED='unassessed',NOT_SELECTED='not_selected',OBSERVATION_ONLY='observation_only')
 for row in lane.rows:
  if row.get('decision') in keys:counts[keys[row['decision']]]+=1
 stocks=[value for i in range(len(lane.rows)) if (value:=lane_stock(snapshot,lane,i,names)) is not None]
 hk_count=len({s['symbol'] for s in stocks});relation_count=len(stocks)
 # Default recommendations contain only positive saved lane decisions. Negative
 # and unknown classifications are explicit inspection views, never recommendations.
 wanted={decision} if decision else {'SELECTED','CONDITIONAL_WATCH'}
 stocks=[s for s in stocks if s['decision'] in wanted]
 if q:
  term=q.casefold();stocks=[s for s in stocks if any(term in str(s.get(k) or '').casefold() for k in ['symbol','name','us_symbol'])]
 return dict(stocks=stocks,counts=counts,lane_state=lane.state.value,
  recommendation_projection=dict(display_only=True,snapshot_hash_basis='ORIGINAL_SAVED_SNAPSHOT',lane=lane_name,
   count_unit='SAVED_LANE_RESEARCH_ROWS',row_count=len(lane.rows),hk_relation_row_count=relation_count,
   distinct_hk_count=hk_count,source_only_row_count=len(lane.rows)-relation_count,coverage=lane.coverage.model_dump(mode='json')))
