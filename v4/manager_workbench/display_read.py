"""Read-only presentation projection. Saved snapshot hashes describe original bytes."""
import csv,hashlib,io,json,re
from decimal import Decimal,InvalidOperation
from infrastructure.owned_io import SafeRoot
from .inputs.validation import before
from .engines.common import US_FACTOR_RULES_VERSION

FACTOR_ROW_SUBTYPES = {'US_DAILY_RETURN_FACTOR_CANDIDATE', 'HK_INDUSTRY_PROXY_FACTOR_CANDIDATE'}


def _catalog_observation(row):
 return isinstance(row, dict) and (row.get('record_role')=='CATALOG_OBSERVATION'
  or row.get('catalog_relation_id') is not None)

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


def _industry_directional_lists(lane_rows,industry_summary,source_session):
 """Build full-lane proxy direction views; never infer downside from NOT_SELECTED."""
 if not isinstance(industry_summary,dict):return None
 rows=[row for row in lane_rows if isinstance(row,dict)
  and row.get('subtype')=='HK_INDUSTRY_PROXY_FACTOR_CANDIDATE']
 if not rows:return None
 lists={key:[] for key in ('upside','downside','flat','unassessed')}
 path_counts={key:0 for key in ('upside','downside','flat','unassessed')}
 mixed_count=0
 for row in rows:
  research=row.get('research_membership') or {}
  formal=row.get('membership') or {}
  membership_ok=(research.get('status')=='VERIFIED_MONTHLY_OBSERVATION'
   and research.get('in_monthly_universe') is True and research.get('market')=='HK_CONNECT') or (
   formal.get('verification')=='VERIFIED' and formal.get('eligible') is True)
  identity_ok=row.get('identity_status')=='VERIFIED'
  source_paths=row.get('proxy_paths')
  source_paths=source_paths if isinstance(source_paths,list) else []
  normalized=[]
  for original in source_paths:
   if not isinstance(original,dict):continue
   path=dict(original)
   path_direction='UNASSESSED'
   try:
    value=Decimal(str(path.get('return_pct')))
    if not value.is_finite():raise InvalidOperation
    if (path.get('status')=='VERIFIED' and identity_ok and membership_ok
      and path.get('source_session')==source_session):
     actual='UPSIDE' if value>0 else 'DOWNSIDE' if value<0 else 'FLAT'
     if path.get('direction')==actual:path_direction=actual
   except (InvalidOperation,TypeError,ValueError):
    pass
   path['direction']=path_direction
   if path_direction=='UNASSESSED':path['status']='UNASSESSED'
   normalized.append(path)
  directions={path['direction'] for path in normalized}
  has_up='UPSIDE' in directions;has_down='DOWNSIDE' in directions
  has_flat='FLAT' in directions;has_unknown=('UNASSESSED' in directions or not normalized)
  if has_up and has_down:mixed_count+=1
  state=('MIXED_UPSIDE_DOWNSIDE' if has_up and has_down else
   'UPSIDE_WITH_UNASSESSED' if has_up and has_unknown else
   'DOWNSIDE_WITH_UNASSESSED' if has_down and has_unknown else
   'UPSIDE' if has_up else 'DOWNSIDE' if has_down else
   'FLAT_WITH_UNASSESSED' if has_flat and has_unknown else
   'FLAT' if has_flat else 'UNASSESSED')
  item=dict(symbol=row.get('symbol'),name=row.get('name'),source_industry=row.get('source_industry'),
   source_session=source_session,direction_state=state,reason=row.get('reason'),
   conditions=list(row.get('conditions') or []),mapping_version=row.get('mapping_version'),
   mapping_evidence=row.get('mapping_evidence'),source_owner=row.get('source_owner'),
   source_artifact_sha256=row.get('source_artifact_sha256'),source_response_sha256=row.get('source_response_sha256'),
   source_response_ref=row.get('source_response_ref'),source_row_sha256=row.get('source_row_sha256'),
   research_membership=dict(status=research.get('status'),source_date=research.get('source_date'),
    source_sha256=research.get('source_sha256'),codes_sha256=research.get('codes_sha256'),
    target_month=research.get('target_month')) if research else None,
   target_eligibility=dict(row.get('target_eligibility') or {}),proxy_paths=normalized)
  selected={
   'upside': [path for path in normalized if path['direction']=='UPSIDE'],
   'downside': [path for path in normalized if path['direction']=='DOWNSIDE'],
   'flat': [path for path in normalized if path['direction']=='FLAT'],
   'unassessed': [path for path in normalized if path['direction']=='UNASSESSED'],
  }
  for key,paths in selected.items():
   if paths or key=='unassessed' and not normalized:
    path_counts[key]+=len(paths) if paths else 1
    lists[key].append({**item,'proxy_paths':paths if key!='unassessed' else (paths or normalized)})
  # A stock with mixed signs appears in both directional lists. Per-stock path
  # state on each list retains the opposing path to make that explicit.
  for key in ('upside','downside'):
   if lists[key] and lists[key][-1]['symbol']==item['symbol']:
    lists[key][-1]['proxy_paths']=normalized
 return dict(display_only=True,source_session=source_session,
  target_date=industry_summary.get('target_date'),mapping_version=industry_summary.get('mapping_version'),
  monthly_observed_scope_count=industry_summary.get('monthly_research_code_count') or industry_summary.get('scope_count'),
  monthly_research_source_date=industry_summary.get('monthly_research_source_date'),
  monthly_research_source_sha256=industry_summary.get('monthly_research_source_sha256'),
  monthly_research_codes_sha256=industry_summary.get('monthly_research_codes_sha256'),
  formal_target_eligibility=industry_summary.get('formal_target_eligibility','CANNOT_CONFIRM'),
  historical_pit_verified=False,mixed_stock_count=mixed_count,
  upside_stock_count=len(lists['upside']),downside_stock_count=len(lists['downside']),
  flat_stock_count=len(lists['flat']),unassessed_stock_count=len(lists['unassessed']),
  upside_path_count=path_counts['upside'],downside_path_count=path_counts['downside'],
  flat_path_count=path_counts['flat'],unassessed_path_count=path_counts['unassessed'],
  lists=lists)


def us_summary(snapshot,names):
 lane=next((l for l in snapshot.lanes if l.lane.value=='US_MAPPING'),None)
 if lane is None:return None
 groups={};relations=[];catalog_rows=[]
 for original in lane.rows:
  row=dict(original);us=row.get('us_symbol')
  if _catalog_observation(row):
   catalog_rows.append(row);continue
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
 factor_summary=next((row.get('us_factor_summary') for row in lane.rows
  if isinstance(row.get('us_factor_summary'),dict)),None)
 source_row_count=sum(1 for row in lane.rows if not _catalog_observation(row)
  and row.get('subtype') not in FACTOR_ROW_SUBTYPES)
 catalog_summary=next((row.get('us_mapping_catalog_summary') for row in lane.rows
  if isinstance(row.get('us_mapping_catalog_summary'),dict)),{})
 run_contract=getattr(snapshot.context,'scope_refs',{}).get('US_MAPPING_RUN_CONTRACT_V1')
 context=snapshot.context.model_dump(mode='json') if hasattr(snapshot.context,'model_dump') else snapshot.context
 sessions=context.get('source_sessions') if isinstance(context,dict) else getattr(context,'source_sessions',{})
 source_session=(sessions or {}).get('us') or (sessions or {}).get('US')
 industry_summary=(factor_summary or {}).get('industry_summary') if isinstance(factor_summary,dict) else None
 directional_proxy_lists=_industry_directional_lists(lane.rows,industry_summary,source_session)
 return dict(display_only=True,plan_run_id=snapshot.run_id,coverage=lane.coverage.model_dump(mode='json'),
  source_symbol_count=len(groups),source_row_count=source_row_count,relation_row_count=len(relations),
  mapped_hk_count=len({r['symbol'] for r in relations}),source_decision_counts=counts,mixed_source_count=mixed,
  groups=out,gaps=lane.gaps,factor_summary=factor_summary,
  catalog_summary=dict(state=catalog_summary.get('state'),
   stock_count=catalog_summary.get('stock_count'),
   relation_count=catalog_summary.get('relation_count'),
   consumed_relation_count=catalog_summary.get('consumed_relation_count'),
   displayed_relation_count=len(catalog_rows)),
  run_contract=run_contract,directional_proxy_lists=directional_proxy_lists)


def lane_stock(snapshot,lane,index,names):
 """Present one original lane row; never inherit the merged stock decision."""
 row=lane.rows[index];symbol=row.get('symbol')
 if _catalog_observation(row):return None
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


_CANDIDATE_SUBTYPE_PRIORITY={'HK_INDUSTRY_PROXY_FACTOR_CANDIDATE':3,'US_DAILY_RETURN_FACTOR_CANDIDATE':2}


def _representatives_by_symbol(stocks):
 """Prefer the most specific candidate subtype, preserving first row on ties."""
 representatives={}
 for stock in stocks:
  previous=representatives.get(stock['symbol'])
  priority=_CANDIDATE_SUBTYPE_PRIORITY.get(stock.get('subtype'),1)
  previous_priority=_CANDIDATE_SUBTYPE_PRIORITY.get(previous.get('subtype'),1) if previous else 0
  if previous is None or priority>previous_priority:representatives[stock['symbol']]=stock
 return representatives


def _candidate_stock_counts(stocks):
 """Count one full-lane HK candidate decision per stock, with positive rows matching the recommendation view."""
 positive=[stock for stock in stocks if stock.get('decision') in {'SELECTED','CONDITIONAL_WATCH'}]
 representatives=_representatives_by_symbol(positive)
 # A positive recommendation row is the same representative the default list
 # exposes. For stocks without a positive row, use the strongest available
 # candidate subtype so unknown evidence is not hidden by a lower-priority row.
 fallback=[stock for stock in stocks if stock['symbol'] not in representatives]
 representatives.update(_representatives_by_symbol(fallback))
 counts={k:0 for k in ['selected','watch','unassessed','not_selected','observation_only']}
 keys=dict(SELECTED='selected',CONDITIONAL_WATCH='watch',UNASSESSED='unassessed',NOT_SELECTED='not_selected',OBSERVATION_ONLY='observation_only')
 for stock in representatives.values():
  key=keys.get(stock.get('decision'))
  if key:counts[key]+=1
 return counts,representatives


def lane_projection(snapshot,lane_name,names,decision=None,q=None):
 lane=next((l for l in snapshot.lanes if l.lane.value==lane_name),None)
 if lane is None:return None
 factor_rules=(lane_name=='US_MAPPING' and snapshot.context.rules_version==US_FACTOR_RULES_VERSION)
 industry_rows=[row for row in lane.rows if row.get('subtype')=='HK_INDUSTRY_PROXY_FACTOR_CANDIDATE'] if factor_rules else []
 catalog_rows=[row for row in lane.rows if _catalog_observation(row)] if lane_name=='US_MAPPING' else []
 legacy_rows=[row for row in lane.rows if not _catalog_observation(row)
  and row.get('subtype')!='HK_INDUSTRY_PROXY_FACTOR_CANDIDATE'] if factor_rules else [
   row for row in lane.rows if not _catalog_observation(row)]
 source_counts={k:0 for k in ['selected','watch','unassessed','not_selected','observation_only']}
 keys=dict(SELECTED='selected',CONDITIONAL_WATCH='watch',UNASSESSED='unassessed',NOT_SELECTED='not_selected',OBSERVATION_ONLY='observation_only')
 for row in legacy_rows:
  if row.get('decision') in keys:source_counts[keys[row['decision']]]+=1
 candidate_stocks=[value for i in range(len(lane.rows)) if not _catalog_observation(lane.rows[i])
  and (value:=lane_stock(snapshot,lane,i,names)) is not None]
 hk_count=len({s['symbol'] for s in candidate_stocks})
 candidate_counts,candidate_representatives=_candidate_stock_counts(candidate_stocks) if factor_rules else (None,{})
 counts=candidate_counts if factor_rules else source_counts
 # Default recommendations contain only positive saved lane decisions. Negative
 # and unknown classifications are explicit inspection views, never recommendations.
 wanted={decision} if decision else {'SELECTED','CONDITIONAL_WATCH'}
 stocks=[s for s in candidate_stocks if s['decision'] in wanted]
 if factor_rules:
  # The positive factor candidate can represent one HK row while all original
  # relationship/factor evidence remains available from the stock detail read.
  stocks=list(_representatives_by_symbol(stocks).values())
  factor_summary=next((row.get('us_factor_summary') for row in lane.rows
   if isinstance(row.get('us_factor_summary'),dict)),{})
  relation_count=sum(1 for row in legacy_rows if row.get('subtype') not in FACTOR_ROW_SUBTYPES
   and re.fullmatch(r'HK\.[0-9]{5}',str(row.get('symbol',''))))
  industry_candidate_row_count=len(industry_rows)
 else:
  factor_summary={}
  industry_candidate_row_count=0
  relation_count=sum(1 for row in legacy_rows if row.get('subtype') not in FACTOR_ROW_SUBTYPES
   and re.fullmatch(r'HK\.[0-9]{5}',str(row.get('symbol',''))))
 if q:
  term=q.casefold();stocks=[s for s in stocks if any(term in str(s.get(k) or '').casefold() for k in ['symbol','name','us_symbol','theme','source_industry'])]
 industry_summary=factor_summary.get('industry_summary') if factor_rules else None
 recommendation_projection=dict(display_only=True,snapshot_hash_basis='ORIGINAL_SAVED_SNAPSHOT',lane=lane_name,
   count_unit='SAVED_LANE_RESEARCH_ROWS',row_count=len(legacy_rows),
   hk_relation_row_count=relation_count,distinct_hk_count=hk_count,
   factor_stock_count=factor_summary.get('unique_factor_stock_count') if factor_rules else None,
   factor_path_count=factor_summary.get('factor_path_count') if factor_rules else None,
   source_only_row_count=len(legacy_rows)-relation_count-sum(1 for row in legacy_rows if row.get('subtype')=='US_DAILY_RETURN_FACTOR_CANDIDATE'),
   catalog_relation_row_count=len(catalog_rows),
   catalog_stock_count=len({row.get('symbol') for row in catalog_rows if re.fullmatch(r'HK\.[0-9]{5}',str(row.get('symbol','')))}),
   run_contract=getattr(snapshot.context,'scope_refs',{}).get('US_MAPPING_RUN_CONTRACT_V1') if lane_name=='US_MAPPING' else None,
   industry_candidate_row_count=industry_candidate_row_count,
   industry_candidate_stock_count=(industry_summary or {}).get('triggered_unique_stock_count'),
   industry_scope_count=(industry_summary or {}).get('scope_count'),
   coverage=lane.coverage.model_dump(mode='json'))
 if factor_rules:
  recommendation_projection.update(recommendation_count_unit='DEDUPLICATED_HK_CANDIDATE_STOCKS',
   candidate_stock_count=len(candidate_representatives),source_decision_counts=source_counts,
   source_decision_count_unit='SAVED_LANE_RESEARCH_ROWS')
 return dict(stocks=stocks,counts=counts,lane_state=lane.state.value,
  recommendation_projection=recommendation_projection)
