"""Frozen saved-set overlap only. No prices, models, APIs, filters or pool production."""
import argparse,csv,hashlib,json
from collections import Counter
from pathlib import Path
DAYS=['20261016','20261019','20261020','20261021','20261022']
U_ID='RECOVERABLE_A_SUBPOOL_UNION_RETROSPECTIVE'
CHILDREN=['a_d1_premarket_pool','a_d1_fupan_watchlist_pool','a_d1_stage7_fenshi_review_pool','a_share_research_recommendation_pool']
FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def read(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def write(p,rr,fields=None):
 with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rr[0]));w.writeheader();w.writerows(rr)
def ratio(h,n):return h/n if n else None
def pair(label,left,right,truth,days):
 common=left&right;lo=left-right;ro=right-left;un=left|right
 z=dict(pair=label,selection_date='ALL' if len(days)>1 else days[0],days=len(days),truth_denominator=100*len(days))
 for name,ss in [('left',left),('right',right),('common',common),('left_only',lo),('right_only',ro),('union',un)]:
  n=len(ss);h=len(ss&truth);z.update({name+'_N':n,name+'_H':h,name+'_precision':ratio(h,n),name+'_recall':h/(100*len(days))})
 z['left_extra_non_hits']=len(lo-truth);z['left_extra_candidates_per_new_hit']=ratio(len(lo),len(lo&truth))
 assert z['left_N']==z['common_N']+z['left_only_N'] and z['right_N']==z['common_N']+z['right_only_N']
 assert z['union_H']==z['common_H']+z['left_only_H']+z['right_only_H']
 return z

def run(cp,out,slim):
 c=load(cp);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 for p,h in c['input_bindings'].items():assert sha(p)==h,'INPUT_DRIFT:'+p
 trows=read(c['benchmark']);T={(r['selection_date'],r['code']) for r in trows};assert len(trows)==len(T)==500
 assert all(sum(k[0]==d for k in T)==100 for d in DAYS)
 meta={(r['selection_date'],r['code']):r for r in trows}
 sets={m:set() for m in ['A','B','U']}
 for d in DAYS:
  for m in ['A','B']:
   rr=read(Path(c['weekly_root'])/'signals'/d/f'MODEL_{m}_CANDIDATES.csv');ss={(d,r['code']) for r in rr};assert len(rr)==len(ss)
   sets[m]|=ss
 rows=read(c['membership']);source={p:set() for p in CHILDREN}
 for r in rows:
  k=(r['selection_date'],r['code'])
  if r['pool_id']==U_ID:sets['U'].add(k)
  elif r['pool_id'] in source:source[r['pool_id']].add(k)
 assert all('.A_UNMAPPED' not in r['code'] for r in rows)
 A,B,U=[sets[x] for x in ['A','B','U']];AB=A|B
 assert [(len(s),len(s&T)) for s in [A,B,U]]==[(299,17),(3894,113),(1627,95)]
 assert U==set().union(*source.values()),'CHILD_UNION_DRIFT'
 new=U&T-AB;oldnew=read(c['old_new387']);assert new=={(r['selection_date'],r['code']) for r in oldnew} and len(new)==49
 manifest=load(c['pool_manifest']);available={(e['pool_id'],e['selection_date']) for e in manifest['entries'] if e['pool_id'] in CHILDREN}
 complete_days=[d for d in DAYS if all((p,d) in available for p in CHILDREN)]
 cats=[];detail=[]
 for k in sorted(T):
  bits=''.join(str(int(k in s)) for s in [A,B,U]);r=meta[k]
  detail.append(dict(selection_date=k[0],code=k[1],name=r.get('name',''),rank=r['rank'],A=int(k in A),B=int(k in B),U=int(k in U),category_ABU=bits))
 for d in [*DAYS,'ALL']:
  co=Counter(r['category_ABU'] for r in detail if d=='ALL' or r['selection_date']==d)
  for n in range(8):
   bits=f'{n:03b}';cats.append(dict(selection_date=d,category_ABU=bits,hits=co[bits],truth_denominator=500 if d=='ALL' else 100))
  assert sum(co.values())==(500 if d=='ALL' else 100)
 pair_defs=[('A__B',A,B),('U__A',U,A),('U__B',U,B),('U__A_OR_B',U,AB)]
 pairs=[];pair_detail=[]
 for label,lft,rgt in pair_defs:
  for d in [*DAYS,'ALL']:
   ds=DAYS if d=='ALL' else [d];ll={k for k in lft if k[0] in ds};rr={k for k in rgt if k[0] in ds};tt={k for k in T if k[0] in ds}
   pairs.append(pair(label,ll,rr,tt,ds))
  for k in sorted(lft|rgt):pair_detail.append(dict(pair=label,selection_date=k[0],code=k[1],membership='COMMON' if k in lft&rgt else 'LEFT_ONLY' if k in lft else 'RIGHT_ONLY',top100_hit=k in T))
 sd=[];st=[];nd=[]
 for p in CHILDREN:
  observed=[]
  for d in DAYS:
   av=(p,d) in available;others=[q for q in CHILDREN if q!=p and (q,d) in available];all_present=d in complete_days
   ss={k for k in source[p] if k[0]==d} if av else set();incr=ss&T-AB;unique=incr-set().union(*(source[q] for q in others))
   row=dict(source=p,selection_date=d,available=av,all_four_children_observed=all_present,N=len(ss) if av else None,H=len(ss&T) if av else None,new_vs_A_OR_B=len(incr) if av else None,unique_among_observed_children=len(unique) if av else None,unique_among_all_four_children=len(unique) if av and all_present else None,new_on_incomplete_coverage_date=len(incr) if av and not all_present else None,missing_children='|'.join(q for q in CHILDREN if (q,d) not in available),interpretation='OBSERVED_FOUR_CHILD_COMPARISON' if all_present else 'OTHER_CHILDREN_CANNOT_CONFIRM_NOT_ABSENT')
   sd.append(row)
   if av:observed.append(row)
  st.append(dict(source=p,observed_days=len(observed),N=sum(r['N'] for r in observed),H=sum(r['H'] for r in observed),new_vs_A_OR_B=sum(r['new_vs_A_OR_B'] for r in observed),unique_among_observed_children=sum(r['unique_among_observed_children'] for r in observed),unique_complete_four_child_dates=sum(r['unique_among_all_four_children'] or 0 for r in observed),new_incomplete_coverage_dates=sum(r['new_on_incomplete_coverage_date'] or 0 for r in observed),complete_four_child_dates='|'.join(complete_days),incomplete_interpretation='Observed-only unique may include dates where other children are unobserved; never evidence of full-source exclusivity'))
 for k in sorted(new):
  ss=[p for p in CHILDREN if k in source[p]];missing=[p for p in CHILDREN if (p,k[0]) not in available]
  nd.append(dict(selection_date=k[0],code=k[1],name=meta[k].get('name',''),sources='|'.join(ss),source_count=len(ss),observed_only_unique=len(ss)==1,all_four_children_observed=not missing,unique_among_all_four_children=(len(ss)==1) if not missing else None,missing_children='|'.join(missing),interpretation='FOUR_CHILD_UNIQUE' if not missing and len(ss)==1 else 'SHARED_AMONG_OBSERVED_CHILDREN' if not missing else 'ONLY_RESEARCH_OBSERVED_OTHER_CHILDREN_CANNOT_CONFIRM'))
 oldagg={r['source']:r for r in read(c['old_source_aggregate'])}
 for r in st:
  assert r['new_vs_A_OR_B']==int(oldagg[r['source']]['old387_covered'])
  assert r['unique_among_observed_children']==int(oldagg[r['source']]['unique_old387_covered'])
 assert len(nd)==49 and sum(r['all_four_children_observed'] is False for r in nd)==8
 totals=[r for r in pairs if r['selection_date']=='ALL'];counts={r['category_ABU']:r['hits'] for r in cats if r['selection_date']=='ALL'}
 assert counts['001']==49 and sum(counts.values())==500
 result=dict(status='DESCRIPTIVE_OVERLAP_ADDENDUM_PENDING_INDEPENDENT_REVIEW',categories_ABU=counts,pairwise_totals=totals,source_totals=st,complete_four_child_dates=complete_days,incomplete_dates=[d for d in DAYS if d not in complete_days],new_vs_A_OR_B=len(new),new_on_incomplete_coverage_date=8,top100_rows=len(detail),candidate_detail_rows=len(pair_detail),scope='Fixed accepted stock-code-resolvable memberships; existing5533 research Top100; retrospective only; PIT-comparable days0; D20 other three children unobserved, not absent',**FLAGS)
 write(out/'TOP100_ABU_DETAIL_500.csv',detail);write(out/'CATEGORY_DAILY_TOTAL.csv',cats);write(out/'PAIRWISE_DAILY_TOTAL.csv',pairs);write(out/'PAIRWISE_CANDIDATE_DETAIL.csv',pair_detail);write(out/'SOURCE_INCREMENT_DAILY.csv',sd);write(out/'SOURCE_INCREMENT_TOTAL.csv',st);write(out/'NEW49_SOURCE_DETAIL.csv',nd)
 save(out/'RESULT.json',result);save(slim,result)
 pB=next(r for r in totals if r['pair']=='U__B');pA=next(r for r in totals if r['pair']=='U__A');pAB=next(r for r in totals if r['pair']=='U__A_OR_B')
 lines=['# A/B/U命中交集与双向增量','',f"A=原192，B=主图十路，U=可恢复子池并集的股票代码子集。U的95次命中中，与B共同{pB['common_H']}次，U补B {pB['left_only_H']}次；B反过来补U {pB['right_only_H']}次。U与A共同{pA['common_H']}次，U补A {pA['left_only_H']}次，A反过来补U {pA['right_only_H']}次。",'',f"A∪B共命中{pAB['right_H']}次，U再补{pAB['left_only_H']}次，合并命中{pAB['union_H']}/500={pAB['union_recall']:.1%}；这49次不是已被原模型命中的重复计数。",'', '| A/B/U三位命中 | 股票×日数 |','|---|---:|']
 for bits,n in counts.items():lines.append(f'| {bits} | {n} |')
 lines += ['', '三位顺序为192/主图/U。000为三者均未命中，001为只有U命中。逐日八格及500个股票×日期见CATEGORY_DAILY_TOTAL.csv、TOP100_ABU_DETAIL_500.csv。','', '| 比较（左→右） | 共同候选N/H | 左独有N/H/precision | 右独有N/H/precision | 合并命中/Recall |','|---|---:|---:|---:|---:|']
 def percent(v):return 'NA' if v is None else f'{v:.2%}'
 for r in totals:lines.append(f"| {r['pair']} | {r['common_N']}/{r['common_H']} | {r['left_only_N']}/{r['left_only_H']}/{percent(r['left_only_precision'])} | {r['right_only_N']}/{r['right_only_H']}/{percent(r['right_only_precision'])} | {r['union_H']}/{r['union_recall']:.1%} |")
 lines += ['',f"以B为已有名单，加入U额外增加{pB['left_only_N']}个候选×日，其中新增命中{pB['left_only_H']}、非Top100 {pB['left_extra_non_hits']}，新增部分precision={pB['left_only_precision']:.2%}。这是候选数量开销，未折算交易成本，未加过滤或优化。",'', '| 子池 | 可观察日期 | 总命中 | 相对A∪B新增 | 仅在当天已观察子池间独有 | 四子池均有文件日期的独有 | 缺覆盖日新增 |','|---|---:|---:|---:|---:|---:|---:|']
 for r in st:lines.append(f"| {r['source']} | {r['observed_days']} | {r['H']} | {r['new_vs_A_OR_B']} | {r['unique_among_observed_children']} | {r['unique_complete_four_child_dates']} | {r['new_incomplete_coverage_dates']} |")
 lines += ['', '来源贡献有重叠，不能把35+22+1+0直接累加成新增数；逐股来源见NEW49_SOURCE_DETAIL.csv。研报旧observed-only unique=26包含10/20其他三子池未观察时的8条；四个现存可分析子池均有文件的4日中，研报独有18条。10/20的8条只能说研报可观察，其他子池CANNOT_CONFIRM，不能说它们选不到。这里四子池间独有也不等于全部历史来源独有。','', '限制沿用原接受范围：09:25历史可用性未证实，PIT可比日0；5533研究池Top100并非认证历史全A榜单；U是离线可恢复子池投影，不是已保存canonical V4汇总池；研报是文章实体的股票代码子集，正式研报选股仍NOT_MATERIALIZED。数据/公式/模型/筛选条件未重算或调整；不支持盘前优越、因果或生产结论。','', 'research_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false。','']
 (out/'REPORT.md').write_text('\n'.join(lines))
 for p,h in c['input_bindings'].items():assert sha(p)==h,'INPUT_DRIFT_AFTER:'+p
 save(out/'OUTPUT_SHA256.json',{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='OUTPUT_SHA256.json'})
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('contract');p.add_argument('out');p.add_argument('slim');a=p.parse_args();print(json.dumps(run(a.contract,a.out,a.slim),ensure_ascii=False))
