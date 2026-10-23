"""Exact-key merge of accepted technical rows and completed catalyst evidence.
No market reads, formula replay, news lookup, imputation, or causal promotion.
"""
import argparse,csv,json
from collections import Counter
from pathlib import Path
from registry_bridge import w,register
from diagnose import OUT,HERE,readcsv
CP=OUT/'MERGE_CONTRACT.json'
NOTE='技术逻辑阻断与公开报道背景为两个独立证据轴；缺证据不等于无公告，报道背景不证明上涨因果或公式漏选原因。'
def key(x):return x['selection_date'],x['code']
def jsonrows(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def cell(v):return json.dumps(v,ensure_ascii=False,separators=(',',':')) if isinstance(v,(dict,list)) else v

def main():
 c=w.load(CP)
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h,'MERGE_INPUT_DRIFT:'+p
 tech=readcsv(OUT/'presentation_r2/USER_EXPLANATIONS_387.csv');cat=jsonrows(OUT/'catalyst/CATALYST_ROWS_387.jsonl');tm={key(r):r for r in tech};cm={key(r):r for r in cat};assert len(tech)==len(cat)==len(tm)==len(cm)==387 and set(tm)==set(cm),'ONE_TO_ONE_KEY_MISMATCH'
 details=[];flat=[]
 for k in sorted(tm):
  t,z=tm[k],cm[k];assert t['signal_asof']==z['signal_asof'],'SIGNAL_DATE_MISMATCH'
  assert t['a_candidate']==t['b_candidate']=='NO';assert z['research_only'] and not any(z[x] for x in ['production_allowed','buy_gate_updated','orders_sent'])
  details.append(dict(selection_date=k[0],code=k[1],technical=t,catalyst=z,two_axis_note_zh=NOTE))
  # Preserve all technical columns and all catalyst fields, including original
  # catalyst code/signal/name and unknown values. Never silently reconcile names.
  extra={(n if n.startswith('catalyst_') else 'catalyst_'+n):cell(v) for n,v in z.items()}
  assert not set(t)&set(extra),'COLUMN_COLLISION'
  flat.append({**t,**extra,'two_axis_note_zh':NOTE})
 assert dict(Counter(x['selection_date'] for x in flat))==c['expected_daily_counts']
 with (OUT/'FINAL_DIAGNOSIS_387.jsonl').open('x') as f:
  for x in details:f.write(json.dumps(x,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
 w.csvwrite(OUT/'FINAL_DIAGNOSIS_387.csv',flat)
 for d in sorted(c['expected_daily_counts']):w.csvwrite(OUT/('FINAL_DIAGNOSIS_'+d+'.csv'),[r for r in flat if r['selection_date']==d])
 counts=dict(Counter(r['catalyst_label'] for r in cat));assert counts=={'TIMING_UNKNOWN':172,'SOURCE_NOT_COVERED':136,'PUBLIC_REPORTED_ATTRIBUTION':79}
 summary=dict(schema='MISS387_MERGED_TWO_AXIS_SUMMARY_V1',status='MERGED_PENDING_CATALYST_AND_MERGE_INCREMENTAL_REVIEW',rows=387,codes=len({x['code'] for x in flat}),daily_counts=c['expected_daily_counts'],technical_primary_reason_counts=dict(Counter(r['primary_reason'] for r in tech)),catalyst_label_counts=counts,main_window_report_context_rows=63,known_before_signal_report_context_rows=22,context_overlap_rows=6,source_queries=729,technical_acceptance=str(OUT/'TECHNICAL_FINAL_ACCEPTANCE.json'),technical_probe_replayed=False,news_query_replayed=False,two_axis_note_zh=NOTE,**w.FLAGS);w.save(OUT/'FINAL_MERGE_SUMMARY.json',summary)
 text='''# 387条共同漏选：最终阅读入口\n\n打开FINAL_DIAGNOSIS_387.csv可逐条查看；另有FINAL_DIAGNOSIS_20261016/19/20/21/22.csv。行数分别92/76/64/65/90，共387条、342只代码，按(date,code)一对一合并，没有删行、重复、补值或重跑模型/新闻。\n\n每行保留两个证据轴：技术栏列原公式逻辑阻断及数值；catalyst_栏列公开报道背景、URL/发布时间、查询范围及未知。技术主因是385条A入口未触发、2条角色分数/路由未过。B十路的每项真实条件与未知值在技术表/ATOMIC_BLOCKERS中保留；不能只用“均未触发”代替解释。\n\n催化轴：79条有原文及epoch核验的公开报道背景，其中63条位于主时间窗、22条为信号前已知背景，交集6条；其余172条时点未知、136条来源覆盖不足。79不代表79条突发公告、利好、可提前获知或上涨原因。公司PDF内容核验不等于首次发布时间/available_at已核实。缺证据不等于没有公告/题材。历史名称/资格/PIT、穷尽新闻覆盖、缓存无时区时点与市场因果仍CANNOT_CONFIRM。\n\nB1具体条件按387事件：BBI>白线274假/113真；白线>黄线245假/139真/3未知；J<=13为251假/136真。条件重叠；3个未知不是白<=黄。类型覆盖J387仅指某路由存在J类失败约束，不指全部J>13。\n\n数值复现与独立源文AST核验已获技术限定PASS（TECHNICAL_FINAL_ACCEPTANCE.json）；原生客户端全公式一致性、历史PIT与跨商量额单位仍CANNOT_CONFIRM。催化和本次合并的独立增量验收以FINAL_ACCEPTANCE.json为准；本文件不自授PASS。D当日触发A71/B256仅后验。\n\n完整证据入口：presentation_r2/READ_FIRST.md、DETAILS.jsonl、presentation_r2/ATOMIC_BLOCKERS.jsonl、catalyst/CATALYST_REPORT_ZH.md、catalyst/VERIFIED_EVIDENCE.json。所有源引用留在本地工件；完整报道/行情/387运行工件不上传GitHub。\n\nRESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。\n'''
 (OUT/'READ_FIRST_FINAL.md').write_text(text)
 files=[OUT/'FINAL_DIAGNOSIS_387.csv',OUT/'FINAL_DIAGNOSIS_387.jsonl',OUT/'FINAL_MERGE_SUMMARY.json',OUT/'READ_FIRST_FINAL.md',*[OUT/('FINAL_DIAGNOSIS_'+d+'.csv') for d in sorted(c['expected_daily_counts'])]]
 w.save(OUT/'FINAL_MERGE_MANIFEST.json',{str(p):w.sha(p) for p in files});register(CP,'TERMINAL','MERGE_TERMINAL',[OUT/'FINAL_MERGE_SUMMARY.json',OUT/'FINAL_MERGE_MANIFEST.json'],{'merged_rows':387,'merged_unique_codes':342,'technical_replays':0,'news_requeries':0},'MERGED_TWO_AXES_PENDING_INDEPENDENT_INCREMENTAL_REVIEW');print(json.dumps(summary,ensure_ascii=False))

def verify(output):
 """Independent invocation checks exact set and full value parity, not models."""
 c=w.load(CP)
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h
 for p,h in w.load(OUT/'FINAL_MERGE_MANIFEST.json').items():assert w.sha(p)==h
 tech={key(r):r for r in readcsv(OUT/'presentation_r2/USER_EXPLANATIONS_387.csv')};cat={key(r):r for r in jsonrows(OUT/'catalyst/CATALYST_ROWS_387.jsonl')};merged=jsonrows(OUT/'FINAL_DIAGNOSIS_387.jsonl');flat=readcsv(OUT/'FINAL_DIAGNOSIS_387.csv');assert len(merged)==len(flat)==387
 assert {key(r) for r in merged}=={key(r) for r in flat}==set(tech)==set(cat)
 for r in merged:
  assert r['technical']==tech[key(r)] and r['catalyst']==cat[key(r)] and r['two_axis_note_zh']==NOTE
 for row in flat:
  for n,v in tech[key(row)].items():assert row[n]==v
  for n,v in cat[key(row)].items():
   target=n if n.startswith('catalyst_') else 'catalyst_'+n;cv=cell(v);expected='' if cv is None else str(cv)
   assert row[target]==expected,(key(row),target)
 for d,n in c['expected_daily_counts'].items():
  rs=readcsv(OUT/('FINAL_DIAGNOSIS_'+d+'.csv'));assert len(rs)==n and rs==[r for r in flat if r['selection_date']==d]
 result=dict(status='MERGE_CHECK_PASS_REVIEWER_VERDICT_SEPARATE',rows=387,unique_codes=342,all_technical_and_catalyst_values_preserved=True,daily_counts=c['expected_daily_counts'],technical_replays=0,news_requeries=0,**w.FLAGS);w.save(Path(output),result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['merge','verify']);p.add_argument('--output');a=p.parse_args()
 if a.phase=='merge':main()
 else:assert a.output;verify(a.output)
