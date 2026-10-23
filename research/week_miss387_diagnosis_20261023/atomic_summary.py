"""Count saved concrete B1 predicates and logical blocking witnesses; no replay."""
import json
from collections import Counter,defaultdict
from diagnose import OUT
from registry_bridge import w

def main():
 rows=[json.loads(x) for x in (OUT/'DETAILS.jsonl').read_text().splitlines()];atoms=[json.loads(x) for x in (OUT/'presentation_r2/ATOMIC_BLOCKERS.jsonl').read_text().splitlines()];counts=defaultdict(Counter);daily=defaultdict(lambda:defaultdict(Counter));combinations=Counter();byroute=defaultdict(Counter)
 for r in rows:
  v={k:x['value'] for k,x in r['signal']['b_assignments'].items()};conditions={'BBI>白线':None if v['BBI'] is None or v['白线'] is None else v['BBI']>v['白线'],'白线>黄线':None if v['白线'] is None or v['黄线'] is None else v['白线']>v['黄线'],'J<=13':None if v['J'] is None else v['J']<=13};failed=[]
  for name,value in conditions.items():
   state='UNKNOWN' if value is None else 'TRUE' if value else 'FALSE';counts[name][state]+=1;daily[r['selection_date']][name][state]+=1
   if state=='FALSE':failed.append(name)
  combinations[' AND '.join(failed)]+=1
 for row in atoms:
  for root in {x['root'] for x in row['b_false_routes']}:
   predicates={(x['owner'],x['expression'],str(x['value'])) for x in row['b_false_routes'] if x['root']==root}
   byroute[root].update(predicates)
 result={'schema':'SAVED_ATOMIC_EXPRESSION_COUNTS_V1','rows':387,'B1_exact_conditions':dict(counts),'daily_B1_exact_conditions':{d:dict(x) for d,x in daily.items()},'B1_false_condition_combination_counts':dict(combinations),'B_route_saved_blocking_predicates':{route:[{'owner':k[0],'expression':k[1],'value':k[2],'event_count':n} for k,n in counter.most_common()] for route,counter in byroute.items()},'note':'B1 counts are exact per-condition terminal comparisons from saved model-B values. Other predicates count distinct dated events with a saved logical witness under that false route. Multilabel overlap is allowed; no market or marginal causality, no numeric model replay. Type-category J387 is not J>13 count.',**w.FLAGS}
 w.save(OUT/'presentation_r2/EXACT_EXPRESSION_COUNTS.json',result);print(json.dumps({'B1_exact_conditions':result['B1_exact_conditions'],'B1_false_combinations':result['B1_false_condition_combination_counts']},ensure_ascii=False))
if __name__=='__main__':main()
