"""Read-only frozen acceptance probe. Reviewer owns invocation and verdict.
Writes only specified independent_review directory; no full-market replay.
"""
import argparse,json,csv,sys,time
from pathlib import Path
from collections import Counter
import numpy as np
from registry_bridge import w,ROOT
from reference import Reference,scalar
from diagnose import OUT,PRIOR,DATES,HERE,readcsv,same,validate_fastbind,diagnose_task
import engine as e

def primitives(c):
 b=w.load(PRIOR/'EXECUTION_CONTRACT.json')['input_identity'];a=w.module(b['model_a'],'primitive_original');k=w.module(b['model_b'],'primitive_b')
 raw={'O':np.array([10.,10.,10.,10.,10.,10.]),'H':np.array([11.,11.,11.,11.,11.,11.]),'L':np.array([9.,9.,9.,9.,9.,9.]),'C':np.array([10.,10.,10.,10.,10.,10.]),'VOL':np.array([0.,1.,0.,1.,1.,0.]),'AMOUNT':np.ones(6)}
 expressions=['MA(C,3)','EMA(C,3)','SMA(C,3,1)','CROSS(VOL,0)','BARSLAST(VOL>2)','REF(C,2)','HHV(H,3)','LLV(L,3)','COUNT(VOL>0,3)','EVERY(VOL>0,3)','EXIST(VOL>0,3)','HHVBARS(VOL,3)','IF(C>0,1,0)','(C-C)/(C-C)']
 checked=[]
 for expr in expressions:
  node=a.Parser(expr).expression();z=a.evaluate((('XG',node),),raw,'000001.SZ')['XG'];ref=Reference([('XG',node)],raw,'A','000001.SZ').named('XG');assert np.allclose(z,ref,rtol=1e-10,atol=1e-8,equal_nan=True),expr;checked.append('A:'+expr)
 # B primitive NaN-init cases explicitly discriminate the two semantic policies.
 for name,args in [('EMA',[np.array([np.nan,1.,2.,3.]),np.full(4,3.)]),('SMA',[np.array([np.nan,1.,np.nan,3.]),np.full(4,3.),np.ones(4)]),('BARSLAST',[np.array([0.,0.,1.,0.])]),('CROSS',[np.array([np.nan,1.,2.,0.]),np.ones(4)]),('COUNT',[np.array([0.,1.,1.,0.]),np.array([0.,1.,2.,0.])]),('MA',[np.array([1.,2.,np.nan,4.]),np.full(4,3.)])]:
  eng=k.Engine({'C':np.ones(4),'H':np.ones(4),'L':np.ones(4),'VOL':np.ones(4)});z=eng.call(name,args);ref=Reference({},eng.raw,'B').call(name,args);assert np.allclose(z,ref,equal_nan=True),name;checked.append('B:'+name)
 # Explicit expected oracle values, separate from both interpreters.
 assert Reference({},raw,'A').call('BARSLAST',[np.zeros(6)]).tolist()==[1,2,3,4,5,6]
 assert np.isnan(Reference({},raw,'B').call('BARSLAST',[np.zeros(6)])).all()
 assert Reference({},raw,'A').call('MA',[np.arange(1.,7.),np.full(6,3.)])[:3].tolist()==[1,1.5,2]
 assert np.isnan(Reference({},raw,'B').call('MA',[np.arange(1.,7.),np.full(6,3.)])[:2]).all()
 return checked

def verify(out):
 start=time.monotonic();out.mkdir(parents=True,exist_ok=True);c=w.load(OUT/'DIAGNOSIS_CONTRACT_R2.json');validate_fastbind(c)
 for manifest in [OUT/'OUTPUT_MANIFEST.json',OUT/'presentation_r2/PRESENTATION_MANIFEST.json']:
  for p,h in w.load(manifest).items():assert w.sha(p)==h,'OUTPUT_DRIFT:'+p
 rows=[json.loads(x) for x in (OUT/'DETAILS.jsonl').read_text().splitlines()];original=readcsv(PRIOR/'comparison/COMMON_MISS_CONFIRMED.csv');csvrows=readcsv(OUT/'DIAGNOSIS_387.csv')
 keys=lambda rs:{(r['selection_date'],r['code']) for r in rs}
 assert len(rows)==len(keys(rows))==387 and keys(rows)==keys(original)==keys(csvrows)
 assert dict(Counter(x['selection_date'] for x in rows))==c['expected_daily_counts']
 expectedmap=dict((target,signal) for signal,target in DATES)
 by={}
 for r in rows:
  assert r['signal_asof']==expectedmap[r['selection_date']]
  assert all(r['archive_parity'].values()) and not r['archive_a_differences']
  p=r['signal'];assert p['a_candidate']==p['b_candidate']=='NO';assert len(p['a_all_terminal_values'])==255
  assert not p['reference']['a_differences'] and not p['reference']['b_differences']
  assert len(p['b_rules'])==10 and all(x['status']=='NOT_TRIGGERED' for x in p['b_rules'])
  assert len(r['input_audit']['fields'])==6 and r['input_audit']['exact_signal_bar']==r['signal_asof']
  assert all(d<=r['signal_asof'] for d in [x['date'] for x in r['input_audit']['events_le_signal']])
  assert r['input_audit']['historical_available_at'].startswith('CANNOT_CONFIRM')
  assert p['b_assignments']['B1']['expression']=='(((BBI > 白线) AND (白线 > 黄线)) AND (J <= 13))'
  by.setdefault(r['code'],[]).append(r['prior_row'])
 # Independent mapping replay from text using a different lexer/parser.
 from source_mapping import source_assignments,parse,normal
 b=w.load(PRIOR/'EXECUTION_CONTRACT.json')['input_identity'];sa=w.module(b['model_a'],'independent_review_map_a');sk=w.module(b['model_b'],'independent_review_map_b')
 for mode,path,prod,rev,norm in [('A',b['formula_a'],dict(sa.compile_original(b['formula_a'])),{},{}),('B',sk.FORMULA,sk.program()[0],sk.program()[2],{'CLOSE':'C','HIGH':'H','LOW':'L'})]:
  source=source_assignments(path,mode);assert [n for n,_ in source]==list(prod)
  for name,text in source:assert parse(text,norm)==normal(prod[name],rev),(mode,name)
 scope=w.load(OUT/'presentation_r2/SEMANTIC_SCOPE_EVIDENCE.json');assert scope['b_NOT_HHVBARS_unreachable']
 ats=[json.loads(x) for x in (OUT/'presentation_r2/ATOMIC_BLOCKERS.jsonl').read_text().splitlines()];assert keys(ats)==keys(rows) and len(ats)==387
 for r in ats:
  for atom in r['a_blockers']+r['b_false_routes']:
   if atom['lhs'] is not None and atom['rhs'] is not None:assert same(atom['numeric_margin_lhs_minus_rhs'],atom['lhs']-atom['rhs'])
  assert {a['root'] for a in r['b_false_routes']}==set(sk.RULES.values())
 # Fresh targeted reader/replay for source branches, BJ, and two role-blocked events.
 selected=[];branches=set()
 for r in rows:
  branch=r['input_audit']['source_branch']
  if branch not in branches:branches.add(branch);selected.append(r['code'])
 for code in ['301119.SZ','600838.SH',*[r['code'] for r in rows if r['code'].endswith('.BJ')][:2]]:
  if code not in selected:selected.append(code)
 selected=list(dict.fromkeys(selected))[:10]
 tasks=e.get_tasks(w.load(PRIOR/'EXECUTION_CONTRACT.json'),selected);fresh=0
 for task in tasks:
  result=diagnose_task((task,by[task[0]]))
  for r in result['rows']:
   old=next(x for x in rows if x['selection_date']==r['selection_date'] and x['code']==r['code'])
   assert r['signal']==old['signal'],'FRESH_SAMPLE_DRIFT';assert r['input_audit']==old['input_audit'];fresh+=1
 # Verify source text assignment order and AST mapping without importing a second formula.
 b=w.load(PRIOR/'EXECUTION_CONTRACT.json')['input_identity'];a=w.module(b['model_a'],'review_source_a');prog=a.compile_original(b['formula_a']);assert [x[0] for x in prog]==list(rows[0]['signal']['a_assignments'])
 k=w.module(b['model_b'],'review_source_b');nodes,aliases,rev=k.program();assert k.RULES=={'B1':'B1','B2':'B2','B3':'B3','BREAKOUT':'突破','BREAKOUT_DOJI':'突破接十字星','M2_MINUS':'零下二金','M2_PLUS':'零上二金','SINGLE_NEEDLE':'单针下20','THREE_QUARTER_YIN':'四分之三阴量线','BRICK_FANBAO':'BRICK_FANBAO'}
 receipt=dict(status='PROBE_PASS_REVIEWER_VERDICT_SEPARATE',rows=387,unique_codes=len(by),daily_counts=c['expected_daily_counts'],fresh_sample_codes=selected,fresh_sample_events=fresh,primitive_checks=primitives(c),source_mapping_A255_B50='INDEPENDENT_SHUNTING_YARD_STRUCTURE_PASS',b_NOT_HHVBARS='UNREACHABLE_NOT_VALIDATED_GENERIC_CAPABILITY',presentation_atoms_margin_checks=True,old_full5533_rerun=False,seconds=time.monotonic()-start,limitations=c['limitations'],**w.FLAGS)
 w.save(out/'VERIFIER_RECEIPT.json',receipt);print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();verify(Path(a.output))
