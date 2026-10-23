"""Read-only saved membership joins. No market/model/API producer or fit calls."""
import argparse,csv,hashlib,json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
DATES=['20261016','20261019','20261020','20261021','20261022']
FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def rows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rs,fields):
 with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
def code(x):
 s=str(x or '').upper().strip();s=s.replace('SHSE.','SH.').replace('SZSE.','SZ.')
 m=re.fullmatch(r'(SH|SZ|BJ)[.:]?(\d{6})',s)
 if m:s=m[2]+'.'+m[1]
 m=re.fullmatch(r'(\d{6})(?:\.(SH|SZ|BJ))?',s)
 if not m:return None
 n,ex=m.groups();expected='SH' if n.startswith('6') else 'SZ' if n.startswith(('0','3')) else 'BJ' if n.startswith(('4','8','92')) else None
 return n+'.'+expected if expected and (not ex or ex==expected) else None
def canonical_row(r):
 # Exact runtime _canonical_a_symbol membership semantics, then research-key suffix.
 if str(r.get('market') or '').strip().upper() in {'HK','HK_CONNECT','HKCONNECT','港股','港股通'}:return None
 candidates=set()
 for field in ('symbol','normalized_code','code','stock_code','ts_code'):
  v=str(r.get(field) or '').strip().upper()
  if v.startswith('A.'):v=v[2:]
  elif v.startswith('HK.'):continue
  if v.endswith(('.SH','.SZ','.BJ')):v=v[:-3]
  if re.fullmatch(r'\d{6}',v):candidates.add(v)
 if len(candidates)!=1:return None
 n=candidates.pop();return code(n) or n+'.A_UNMAPPED'
def getrows(e):
 if e.get('children'):
  allrows=[]
  for child in e['children']:
   for r in getrows(child):allrows.append({**r,'source_pool_ids':[child['pool_id']],'_source_pool_id':child['pool_id'],'_source_artifact_sha256':child['sha256'],'_source_membership_path':child['membership_path']})
  return allrows
 assert sha(e['membership_path'])==e['sha256'],'MEMBERSHIP_DRIFT:'+e['membership_path']
 if e.get('receipt_path'):
  assert sha(e['receipt_path'])==e['receipt_sha256'],'RECEIPT_DRIFT'
  rr=load(e['receipt_path']);assert rr['artifact_sha256']==e['sha256'] and rr['pool_id']==e['pool_id'] and rr['trade_date']==e['selection_date'] and rr['source_sha256']==e['source_sha256'],'RECEIPT_IDENTITY_MISMATCH'
 if e.get('format')=='csv':return rows(e['membership_path'])
 v=load(e['membership_path'])
 for k in e.get('rows_key','').split('.'):
  if k:v=v[k]
 assert isinstance(v,list),'MEMBERSHIP_NOT_LIST'
 return v
def entity_class(r,d,k,identities):
 if not k.endswith('.A_UNMAPPED'):return 'STOCK_CODE_RESOLVED'
 n=k.split('.')[0];entry=identities.get((d,n))
 if entry and str(r.get('stock_name') or '')==entry['source_name'] and 'ETF' in entry['source_name'].upper() and r.get('_source_artifact_sha256')==entry['snapshot_sha256']:
  return 'NON_STOCK_ETF'
 return 'CANNOT_CONFIRM_UNKNOWN_IDENTITY'
def sources(r,e):
 v=r.get(e.get('source_field','source_pool_ids')) or e.get('source_id') or e['pool_id']
 if isinstance(v,str):
  if v.startswith('['):v=json.loads(v)
  else:v=v.split('|')
 if isinstance(v,dict):v=list(v)
 return {str(x) for x in v if x is not None} if isinstance(v,list) else {str(v)}
def timing(e):
 if not e.get('complete',False):return 'CANNOT_CONFIRM_INCOMPLETE'
 status=e.get('timing_status','CANNOT_CONFIRM')
 if status!='PIT_CONFIRMED':return status
 assert e.get('historical_content_bound') is True,'PIT_REQUIRES_CONTENT_BINDING'
 t=datetime.fromisoformat(e['available_at'].replace('Z','+00:00'))
 assert t.tzinfo is not None,'NAIVE_AVAILABILITY'
 cutoff=datetime.strptime(e['selection_date']+'0925','%Y%m%d%H%M').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
 assert t<=cutoff,'POST_CUTOFF_PIT_CLAIM'
 return 'PIT_CONFIRMED'
def run(cp,out,only_date=None):
 c=load(cp);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'INPUT_DRIFT:'+p
 mf=load(c['pool_manifest']);entries=mf['entries'];old=Path(c['accepted_week_root'])
 identity_plan=load(c['identity_classification_path']);identities={(r['selection_date'],r['raw_code']):r for r in identity_plan['records']}
 truth=rows(c['benchmark']);assert len(truth)==500
 tops={d:{r['code']:r for r in truth if r['selection_date']==d} for d in DATES}
 assert all(len(v)==100 for v in tops.values())
 oldmiss=rows(c['old_misses']);mk={(r['selection_date'],r['code']) for r in oldmiss};assert len(mk)==387
 models={}
 for d in DATES:
  models[d]={m:{r['code'] for r in rows(old/'signals'/d/f'MODEL_{m}_CANDIDATES.csv')} for m in ['A','B']}
 daily=[];membership=[];raw_membership=[];excluded=[];source_stats=[];coverage={};invalid=[];pids=sorted(set(mf.get('pool_ids',[]))|{e['pool_id'] for e in entries});statuses={}
 selected=[e for e in entries if not only_date or e['selection_date']==only_date]
 assert len({(e['pool_id'],e['selection_date']) for e in selected})==len(selected),'DUPLICATE_POOL_DATE'
 for e in selected:
  d=e['selection_date'];assert d in DATES
  pid=e['pool_id'];status=timing(e);statuses[(pid,d)]=status
  cr={};rawcr={};classes={};raw=getrows(e)
  for i,r in enumerate(raw):
   k=canonical_row(r)
   if k is None:
    invalid.append(dict(pool_id=pid,selection_date=d,row_index=i,raw_code=r.get(e.get('code_field','code')),reason='NOT_VALID_A_SHARE_MARKET_CODE'));continue
   r={**r,'_source_artifact_sha256':r.get('_source_artifact_sha256',e.get('sha256')),'_source_membership_path':r.get('_source_membership_path',e.get('membership_path'))}
   ss=sources(r,e);rawcr.setdefault(k,set()).update(ss);cl=entity_class(r,d,k,identities)
   assert k not in classes or classes[k]==cl,'CONFLICTING_ENTITY_IDENTITY'
   classes[k]=cl
   if cl=='STOCK_CODE_RESOLVED':cr.setdefault(k,set()).update(ss)
   else:excluded.append(dict(pool_id=pid,selection_date=d,raw_code=k.split('.')[0],original_symbol=r.get('symbol'),original_name=r.get('stock_name'),classification=cl,reason='Frozen source name identifies ETF; controller excludes non-stock from stock metrics' if cl=='NON_STOCK_ETF' else 'No frozen stock/ETF identity binding; quarantined CANNOT_CONFIRM',source_pool_id=r.get('_source_pool_id',pid),source_article_ids=json.dumps(r.get('source_article_ids',[]),ensure_ascii=False,sort_keys=True),original_file_path=r['_source_membership_path'],original_file_sha256=r['_source_artifact_sha256']))
  coverage[(pid,d)]=set(cr)
  H=set(cr)&set(tops[d]);N=len(cr);new={k for k in cr if (d,k) in mk}
  daily.append(dict(pool_id=pid,selection_date=d,timing_status=status,pool_size=N,raw_entity_N=len(rawcr),excluded_non_stock_ETF=sum(v=='NON_STOCK_ETF' for v in classes.values()),unknown_identity_N=sum(v=='CANNOT_CONFIRM_UNKNOWN_IDENTITY' for v in classes.values()),top100_hits=len(H),precision=len(H)/N if N else None,recall=len(H)/100,truth_positive_denominator=100,selection_slots=N,old387_covered=len(new),raw_rows=len(raw),duplicate_a_rows=sum(canonical_row(r) is not None for r in raw)-len(rawcr),complete=e.get('complete',False),available_child_count=len(e.get('children',[])) if e.get('children') else None,missing_children='|'.join(e.get('missing_children',[])),reason=e.get('reason','')))
  for k,ss in sorted(rawcr.items()):raw_membership.append(dict(pool_id=pid,selection_date=d,raw_entity_key='A.'+k.split('.')[0],stock_code=k if classes[k]=='STOCK_CODE_RESOLVED' else '',classification=classes[k],stock_metric_eligible=classes[k]=='STOCK_CODE_RESOLVED',sources='|'.join(sorted(ss))))
  for k,ss in sorted(cr.items()):membership.append(dict(pool_id=pid,selection_date=d,code=k,timing_status=status,top100_hit=k in H,old387_covered=(d,k) in mk,model_a=k in models[d]['A'],model_b=k in models[d]['B'],sources='|'.join(sorted(ss))))
  for s in sorted(set().union(*cr.values()) if cr else set()):
   ks={k for k,v in cr.items() if s in v};unique={k for k in ks if cr[k]=={s}}
   source_stats.append(dict(pool_id=pid,selection_date=d,timing_status=status,source=s,N=len(ks),H=len(ks&set(tops[d])),unique_N=len(unique),unique_H=len(unique&set(tops[d])),old387_covered=sum((d,k) in mk for k in ks),unique_old387_covered=sum((d,k) in mk for k in unique)))
 summary=[];gaps=[]
 for pid in pids:
  for d in DATES:
   if (pid,d) not in coverage:gaps.append(dict(pool_id=pid,selection_date=d,status=mf.get('gap_reasons',{}).get(pid,{}).get(d,'CANNOT_CONFIRM_NO_SAVED_MEMBERSHIP')))
  for tier in ['PIT_CONFIRMED','RETROSPECTIVE_OR_UNCONFIRMED']:
   ds=[d for (p,d),s in statuses.items() if p==pid and (s=='PIT_CONFIRMED')==(tier=='PIT_CONFIRMED') and s!='CANNOT_CONFIRM_INCOMPLETE']
   rs=[r for r in daily if r['pool_id']==pid and r['selection_date'] in ds]
   n=sum(r['pool_size'] for r in rs);h=sum(r['top100_hits'] for r in rs)
   summary.append(dict(pool_id=pid,tier=tier,days=ds,valid_day_count=len(ds),N=n,raw_entity_N=sum(r['raw_entity_N'] for r in rs),excluded_non_stock_ETF=sum(r['excluded_non_stock_ETF'] for r in rs),unknown_identity_N=sum(r['unknown_identity_N'] for r in rs),H=h,precision=h/n if n else None,recall=h/(100*len(ds)) if ds else None,truth_positive_denominator=100*len(ds),selection_slots=n,old387_covered=sum(r['old387_covered'] for r in rs),model_comparators={m:dict(N=sum(len(models[d][m]) for d in ds),H=sum(len(models[d][m]&set(tops[d])) for d in ds),precision=(sum(len(models[d][m]&set(tops[d])) for d in ds)/sum(len(models[d][m]) for d in ds)) if ds and sum(len(models[d][m]) for d in ds) else None,recall=sum(len(models[d][m]&set(tops[d])) for d in ds)/(100*len(ds)) if ds else None) for m in ['A','B']}))
 covered=[]
 for r in oldmiss:
  d,k=r['selection_date'],r['code'];z=dict(selection_date=d,code=k,name=r.get('name',''))
  for pid in pids:z[pid]=('COVERED' if k in coverage[(pid,d)] else 'NOT_IN_SAVED_POOL')+'|'+statuses[(pid,d)] if (pid,d) in coverage else 'CANNOT_CONFIRM_NO_SAVED_MEMBERSHIP'
  covered.append(z)
 write(out/'DAILY_POOL_SUMMARY.csv',daily,list(daily[0]) if daily else ['pool_id','selection_date'])
 write(out/'FULL_MEMBERSHIP_HIT_MISS.csv',membership,list(membership[0]) if membership else ['pool_id','selection_date','code'])
 write(out/'RAW_ENTITY_MEMBERSHIP.csv',raw_membership,list(raw_membership[0]) if raw_membership else ['pool_id','selection_date','raw_entity_key'])
 write(out/'EXCLUDED_ENTITY_LEDGER.csv',excluded,list(excluded[0]) if excluded else ['pool_id','selection_date','raw_code','classification'])
 write(out/'SOURCE_CONTRIBUTION.csv',source_stats,list(source_stats[0]) if source_stats else ['pool_id','selection_date','source'])
 write(out/'OLD387_COVERAGE.csv',covered,['selection_date','code','name',*pids])
 write(out/'GAPS.csv',gaps,['pool_id','selection_date','status'])
 save(out/'INVALID_ROWS.json',invalid)
 result=dict(status='DESCRIPTIVE_OVERLAP_PENDING_INDEPENDENT_REVIEW',scope='Existing5533 research benchmark; no certified historical all-A ranking. Stock-code-resolvable subset excludes frozen ETF entities; raw entity denominators and excluded/unknown ledger retained. Unconfirmed snapshots give retrospective overlap only. Pool may include overnight information unavailable to prior-close models; no causal superiority.',summary=summary,gaps=gaps,membership_rows=len(membership),raw_entity_membership_rows=len(raw_membership),excluded_entity_rows=len(excluded),invalid_rows=len(invalid),**FLAGS)
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'INPUT_DRIFT_AFTER:'+p
 save(out/'RESULT.json',result);save(out/'OUTPUT_SHA256.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='OUTPUT_SHA256.json'})
 return result
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('contract');a.add_argument('out');a.add_argument('--only-date');x=a.parse_args();print(json.dumps(run(x.contract,x.out,x.only_date),ensure_ascii=False))
