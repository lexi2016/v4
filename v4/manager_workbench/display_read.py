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
