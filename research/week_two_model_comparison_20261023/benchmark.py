"""Decode same-day research benchmark only after all frozen signal-file identities exist."""
import argparse,csv,json,math,time
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import weekly_compare as w
import engine

def readcsv(p):
 with Path(p).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def freeze():
 seal=w.load(w.OUT/'SIGNALS_SEALED.json');assert seal['all_signals_complete'] and seal['benchmark_decoded'] is False
 for p,h in seal['files'].items():assert w.sha(w.OUT/p)==h,'SIGNAL_DRIFT'
 cp=w.OUT/'EXECUTION_CONTRACT.json';w.register(cp,'TERMINAL','WEEK_SIGNALS_TERMINAL',[w.OUT/'SIGNALS_SEALED.json'],decision='FROZEN_SIGNALS_COMPLETE_PENDING_INDEPENDENT_REVIEW')
 c=w.load(cp);c.update(execution_id='A_SHARE_WEEK_TWO_MODEL_COMPARISON_20261023_03',truth_access='AFTER_SIGNALS_SEALED_DESCRIPTIVE_SAME_DATE_RESEARCH_TOP100',code_sha256=w.sha(__file__))
 dis=w.R/'final_market_event_delta_64/ORIGINAL318_DISPOSITION.json';c['input_identity']['source_dispositions']=str(dis);c['frozen_source_bindings'][str(dis)]=w.sha(dis)
 meta=w.OUT/'lineage_static/STATIC_INTAKE_RECEIPT.json';c['input_identity']['pointer_snapshot']=str(meta);c['frozen_source_bindings'][str(meta)]=w.sha(meta)
 supplement=w.OUT/'SOURCE_IDENTITY_SUPPLEMENT.json';c['frozen_source_bindings'][str(supplement)]=w.sha(supplement)
 c['input_identity']['signals_seal_path']=str(w.OUT/'SIGNALS_SEALED.json');c['input_identity']['signals_seal_sha256']=w.sha(w.OUT/'SIGNALS_SEALED.json');c['input_sha256']=w.digest(c['input_identity']);c['frozen_source_bindings'][str(Path(__file__).resolve())]=w.sha(__file__)
 c['metadata_intake_limitation']='Root independent lineage inspected footer/schema/stat only: source max trade_date=20261022; footer/schema only and zero rowgroup reads, but earlier manifest diagnostic display included nested price bars; not a blind prediction. Actual static intake registered BACKFILLED_FROM_ARTIFACT with null original time/code/model identity; no repeat inspection.'
 cp=w.OUT/'BENCHMARK_CONTRACT.json';w.save(cp,c);w.register(cp,'RUN_STARTED','WEEK_BENCHMARK_START',[w.OUT/'SIGNALS_SEALED.json'],decision='RUNNING_POSTHOC_RESEARCH_BENCHMARK')
 return cp

def main(cp):
 c=w.load(cp);b=c['input_identity'];seal=w.load(b['signals_seal_path']);assert w.sha(b['signals_seal_path'])==b['signals_seal_sha256']
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h,'SOURCE_DRIFT:'+p
 for p,h in seal['files'].items():assert w.sha(w.OUT/p)==h,'SIGNAL_DRIFT:'+p
 pointer_snapshot=w.load(b['pointer_snapshot']);source_max_date=max(r['footer']['trade_date_max_metadata'] for r in pointer_snapshot['pointer_observations']);assert all(r['footer']['trade_date_max_metadata'] for r in pointer_snapshot['pointer_observations'])
 benchmark_started=datetime.now(timezone.utc).isoformat();assert benchmark_started>seal['sealed_at']
 m=w.load(b['manifest']);codes=sorted(r['code'] for r in m['all_input_statuses']);tasks=engine.get_tasks(c,codes);rows={selection:[] for _,selection in w.DATES};exclusions=[];bindings=[]
 for code,spec,original,native,c56,_,reuse in tasks:
  if spec['status'] not in ['READY','READY_WITH_ROUTE_LEVEL_MISSING_FIELDS']:
   for signal,selection in w.DATES:exclusions.append(dict(selection_date=selection,code=code,reason='SOURCE_UNKNOWN',detail=spec.get('reason')))
   continue
  dates,raw,events,unsupported,provenance=engine.reconstruct(code,spec,original,native,c56)
  for signal,selection in w.DATES:
   common=dict(selection_date=selection,signal_asof=signal,code=code,name=spec.get('name',''),historical_qualification='CANNOT_CONFIRM',benchmark_scope='EXISTING_5533_RESEARCH_CODES_NOT_CERTIFIED_HISTORICAL_ALL_A')
   why=None
   if selection not in dates:why='EXACT_TARGET_BAR_MISSING_NO_DATE_SUBSTITUTION'
   elif signal not in dates:why='EXACT_PREVIOUS_MARKET_SESSION_BAR_MISSING_OR_IPO'
   else:
    i=dates.index(selection);j=dates.index(signal)
    if i!=j+1:why='PREVIOUS_MARKET_SESSION_KEY_MISMATCH'
    elif raw['volume'][i]<=0:why='ZERO_RAW_VOLUME_NO_TRADED_TARGET'
    elif any(signal<d<=selection for d in unsupported):why='UNSUPPORTED_SPLIT_EVENT_IN_REFERENCE_INTERVAL'
   if why:exclusions.append(dict(selection_date=selection,code=code,reason=why,detail=None));continue
   prev=float(raw['close'][j]);ref=prev;ev=[e for e in events if signal<e['date']<=selection]
   for e in ev:ref=ref*e['A']+e['B']
   close=float(raw['close'][i]);pct=(close/ref-1)*100 if math.isfinite(ref) and ref>0 else None
   if pct is None or not math.isfinite(pct):exclusions.append(dict(selection_date=selection,code=code,reason='REFERENCE_PRICE_INVALID',detail=None));continue
   rows[selection].append(dict(**common,pct_change=pct,raw_close=close,raw_previous_session_close=prev,event_adjusted_reference_close=ref,event_count=len(ev),reference_event_sha256=w.digest(ev),raw_volume=float(raw['volume'][i]),ranking_basis='RAW_CLOSE_OVER_SAME_SOURCE_EFFECTIVE_EVENT_ADJUSTED_PREVIOUS_MARKET_SESSION_CLOSE',source_input_sha256=spec['sha256']))
 out=w.OUT/'benchmarks';out.mkdir();comp=w.OUT/'comparison';comp.mkdir();daily=[];alltop=[];allcompare=[]
 dispositions=w.load(b['source_dispositions']);w.csvwrite(out/'EXISTING_SOURCE_KEY_DISPOSITIONS_318.csv',[{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in dispositions])
 for signal,selection in w.DATES:
  ledger=readcsv(w.OUT/'signals'/selection/'YES_NO_UNKNOWN.csv');by={(r['code'],r['model']):r for r in ledger};counts={model:Counter(r['candidate'] for r in ledger if r['model']==model) for model in ['a','b']}
  base=dict(selection_date=selection,signal_asof=signal,model_a_candidates=counts['a']['YES'],model_a_no=counts['a']['NO'],model_a_unknown=counts['a']['UNKNOWN'],model_b_candidates=counts['b']['YES'],model_b_no=counts['b']['NO'],model_b_unknown=counts['b']['UNKNOWN'])
  if not rows[selection]:
   reason='NO_D23_BENCHMARK' if selection=='20261023' and source_max_date<selection else 'NO_RANKABLE_BOUND_TARGET_ROWS'
   daily.append(dict(**base,benchmark_status='CANNOT_CONFIRM',benchmark_reason=reason,benchmark_eligible=None,top100_rows=0,model_a_top100_yes=None,model_b_top100_yes=None,model_a_top100_evaluable=None,model_b_top100_evaluable=None,model_a_top100_unknown=None,model_b_top100_unknown=None,common_hits=None,a_exclusive_confirmed_hits=None,b_exclusive_confirmed_hits=None,common_misses_confirmed=None,unknown_impact=None));continue
  eligible=sorted(rows[selection],key=lambda r:(-r['pct_change'],r['code']));assert len({r['code'] for r in eligible})==len(eligible)
  top=[dict(rank=i+1,**r) for i,r in enumerate(eligible[:100])]
  w.csvwrite(out/(selection+'_ELIGIBLE_RESEARCH_RANKING.csv'),[dict(rank=i+1,**r) for i,r in enumerate(eligible)])
  w.csvwrite(out/(selection+'_TOP100.csv'),top);alltop.extend(top if selection!='20261023' else []);joined=[]
  vals={r['code']:r['values'] for r in map(json.loads,(w.OUT/'signals'/selection/'MODEL_A_TERMINAL_VALUES.jsonl').read_text().splitlines())}
  for row in top:
   aa=by[(row['code'],'a')];bb=by[(row['code'],'b')];sa,sb=aa['candidate'],bb['candidate']
   category='UNKNOWN_IMPACT' if 'UNKNOWN' in [sa,sb] else 'COMMON_HIT' if sa==sb=='YES' else 'A_EXCLUSIVE_HIT' if sa=='YES' else 'B_EXCLUSIVE_HIT' if sb=='YES' else 'COMMON_MISS_CONFIRMED'
   v=vals[row['code']];gate={k:v.get(k) for k in ['ENTRYPOOL','B2ROLE','B3ROLE','XG','RISK0','FRESH','CONT0','FCON','CCON']}
   joined.append(dict(**row,model_a=sa,model_b=sb,comparison_category=category,model_a_hit_rules=aa['hit_rules'],model_b_hit_rules=bb['hit_rules'],model_a_unknown_reason=aa['reason'],model_b_unknown_rules=bb['unknown_rules'],model_a_original_final_gate_values=json.dumps(gate,ensure_ascii=False,separators=(',',':')),miss_reason_scope='ORIGINAL_FROZEN_RULE_OUTPUTS_ONLY_NO_POSTHOC_FILTER_OR_CAUSAL_CLAIM'))
  cats=Counter(r['comparison_category'] for r in joined);ca=Counter(r['model_a'] for r in joined);cb=Counter(r['model_b'] for r in joined)
  daily.append(dict(**base,benchmark_status='DERIVED_RESEARCH_POOL_TOP100' if len(top)==100 else 'CANNOT_CONFIRM',benchmark_reason=None if len(top)==100 else 'FEWER_THAN_100_RANKABLE_BOUND_ROWS_NO_OTHER_DATE_FILL',benchmark_eligible=len(eligible),top100_rows=len(top),model_a_top100_yes=ca['YES'],model_b_top100_yes=cb['YES'],model_a_top100_evaluable=ca['YES']+ca['NO'],model_b_top100_evaluable=cb['YES']+cb['NO'],model_a_top100_unknown=ca['UNKNOWN'],model_b_top100_unknown=cb['UNKNOWN'],common_hits=cats['COMMON_HIT'],a_exclusive_confirmed_hits=cats['A_EXCLUSIVE_HIT'],b_exclusive_confirmed_hits=cats['B_EXCLUSIVE_HIT'],common_misses_confirmed=cats['COMMON_MISS_CONFIRMED'],unknown_impact=cats['UNKNOWN_IMPACT']))
  w.csvwrite(comp/(selection+'_TOP100_COMPARISON.csv'),joined);allcompare.extend(joined if selection!='20261023' else [])
 top_fields=['rank','selection_date','signal_asof','code','name','historical_qualification','benchmark_scope','pct_change','raw_close','raw_previous_session_close','event_adjusted_reference_close','event_count','reference_event_sha256','raw_volume','ranking_basis','source_input_sha256']
 compare_fields=top_fields+['model_a','model_b','comparison_category','model_a_hit_rules','model_b_hit_rules','model_a_unknown_reason','model_b_unknown_rules','model_a_original_final_gate_values','miss_reason_scope']
 w.csvwrite(out/'FIVE_DAYS_TOP100_500.csv',alltop,top_fields);w.csvwrite(out/'BENCHMARK_EXCLUSIONS.csv',exclusions);w.csvwrite(comp/'DAILY_SUMMARY.csv',daily);w.csvwrite(comp/'TOP100_COMPARISON_500.csv',allcompare,compare_fields)
 for category in ['COMMON_HIT','A_EXCLUSIVE_HIT','B_EXCLUSIVE_HIT','COMMON_MISS_CONFIRMED','UNKNOWN_IMPACT']:
  w.csvwrite(comp/(category+'.csv'),[r for r in allcompare if r['comparison_category']==category],compare_fields)
 total={k:sum((r[k] or 0) for r in daily[:5]) for k in ['model_a_candidates','model_b_candidates','model_a_top100_yes','model_b_top100_yes','common_hits','a_exclusive_confirmed_hits','b_exclusive_confirmed_hits','common_misses_confirmed','unknown_impact']}
 files={str(p.relative_to(w.OUT)):w.sha(p) for d in [out,comp] for p in sorted(d.iterdir()) if p.is_file()}
 receipt=dict(status='IMPLEMENTED_DELIVERED_PENDING_INDEPENDENT_REVIEW',benchmark_started=benchmark_started,signals_seal_sha256=b['signals_seal_sha256'],daily=daily,totals=total,benchmark_files=files,signal_files=seal['files'],D23_benchmark={'status':daily[-1]['benchmark_status'],'reason':daily[-1]['benchmark_reason'],'bound_pointer_max_date':source_max_date,'snapshot_sha256':w.sha(b['pointer_snapshot'])},eligible_pool=5533,observed_main_benchmark_rows=len(alltop),requested_main_benchmark_rows=500,historical_full_A_qualification='CANNOT_CONFIRM',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 w.save(w.OUT/'RESULT_RECEIPT.json',receipt)
 report=['# 近一周两模型逐日选股与同日涨幅Top100比较','', '模型A：交付V192ORIG完整255行原文离线解释器；模型B：冻结主图10入口 OR。规则均未修改，无TopN、评分或额外门。', '', '主表日期为选股展示日/同日表现日；信号严格使用前一交易日。两个模型均使用相同既有完整计算前缀，原始价格及有效事件截至各signal，再以各signal为锚点作未舍入事件仿射/股本量投影；AMOUNT保持原native CNY值、不复权。', '', '|日期|信号截至|A候选|B候选|A命中Top100|B命中Top100|共同命中|A独有|B独有|确定共同漏选|未知影响|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
 for r in daily:
  keys=['selection_date','signal_asof','model_a_candidates','model_b_candidates','model_a_top100_yes','model_b_top100_yes','common_hits','a_exclusive_confirmed_hits','b_exclusive_confirmed_hits','common_misses_confirmed','unknown_impact'];report.append('|'+ '|'.join('—' if r[k] is None else str(r[k]) for k in keys)+'|')
 report += ['',f'五日共{len(alltop)}条榜单（逐日不足时保留实际行数，不搬日补位）；A命中{total["model_a_top100_yes"]}，B命中{total["model_b_top100_yes"]}。这只是固定研究池上的描述性对照，不设模型胜负/突破门。','', '榜单按同源RAW收盘价÷当日有效公司行为调整的前一市场交易日收盘参考价−1计算，涨幅降序、代码升序；已知旧OHLC冲突使原selector派生pct/preclose不能直接承接。无前一交易日价、目标日无bar、原始量为0或来源未知均单列排除；不搬日、不填0。', '', '这是现有5,533研究代码的派生榜，不能称已认证历史全A股排行榜。原318仍有34未解决及独立身份未知，历史资格/alias时点、事件公告可得性和完整PIT均CANNOT_CONFIRM。来源修复、当前全市场资格或供应商成交量/额单位不由本比较认证。', '', '300573/600866的RAW正价但部分历史事件仿射后非正，冻结解释器相关结果UNKNOWN；301139/603007来源UNKNOWN。未知不当NO，确定共同漏选要求两个模型都NO。每日报完整100条，不因模型未知删榜。', '', '10月23日附表的benchmark状态以已绑定pointer快照与实际可排名行数为准；本次max=D22，CANNOT_CONFIRM，原因NO_D23_BENCHMARK。B附表204只直接复用65/67同输入同解释器PASS；A为修复后同源离线重放。', '', '文件：signals/<日期>/MODEL_A_CANDIDATES.csv、MODEL_B_CANDIDATES.csv和YES_NO_UNKNOWN.csv；benchmarks/FIVE_DAYS_TOP100_500.csv；comparison/DAILY_SUMMARY.csv、TOP100_COMPARISON_500.csv、COMMON_MISS_CONFIRMED.csv及各独有/共同/未知分类。所有信号先以SIGNALS_SEALED.json封存，后验榜启动时间和文件SHA见RESULT_RECEIPT.json。', '', '外围静态盘点曾展示64 manifest内嵌诊断价格bar，因此本批属于OPENBOOK描述性比较，不宣称盲预测或历史PIT封存。该盘点原时间、代码SHA及模型身份未记录，已按BACKFILLED_FROM_ARTIFACT如实补登；未重复读取该诊断数据。', '', '状态：Writer交付，尚待独立Reviewer；未部署UI/API、未训练、未运行T2/T5、未交易。']
 (w.OUT/'report.md').write_text('\n'.join(report)+'\n')
 w.register(cp,'TERMINAL','WEEK_BENCHMARK_TERMINAL',[w.OUT/'RESULT_RECEIPT.json',w.OUT/'report.md'],total,decision='DELIVERED_RESEARCH_COMPARISON_PENDING_INDEPENDENT_REVIEW')
 print(json.dumps(receipt['daily'],ensure_ascii=False),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract');a=p.parse_args();main(Path(a.contract) if a.contract else freeze())
