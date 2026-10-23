"""Frozen offline weekly two-formula descriptive comparison; sole parent registrar."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,math,os,sys,time,struct,zipfile
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
sys.dont_write_bytecode=True
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
OUT=ROOT/'research/week_two_model_comparison_20261023'
R=ROOT/'research/today_selection_20261023/stale318_recovery/resolution_02'
OLD=ROOT/'worktrees/zge_local_selection_20261023/research/today_selection_20261023'
PYTHON='/Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python'
DATES=[('20261015','20261016'),('20261016','20261019'),('20261019','20261020'),('20261020','20261021'),('20261021','20261022'),('20261022','20261023')]
FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(p,x):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
def csvwrite(p,rows,fields=None):
 with Path(p).open('x',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def register(cp,event,stage,artifacts=(),metrics=None,decision='RUNNING'):
 c=load(cp)
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
 sys.path.insert(0,str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
 from registry_adapter import OfficialRegistryAdapter
 ad=OfficialRegistryAdapter()
 spec=dict(schema_version='1.0',registry_event_id=c['execution_id']+'_'+stage,registration_mode='LIVE_EXECUTION',route_id=c['route_id'],experiment_id=c['route_id'],execution_id=c['execution_id'],track_id=c['track_id'],stage=stage,event_type=event,occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='ACTUAL_LIVE_EVENT',contract_path=str(cp),input_sha256=c['input_sha256'],code_sha256=c['code_sha256'],config_sha256=sha(cp),input_identity=c['input_identity'],baseline_id=c['baseline_id'],one_variable=c['one_variable'],signal_date_range=c['signal_date_range'],target_date_range=c['target_date_range'],truth_access=c['truth_access'],sealed_status=c['sealed_status'],runtime=c['runtime'],device=c['device'],artifact_paths=[str(cp),*map(str,artifacts)],checkpoint_ref=None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision,stop_reason=decision if event=='TERMINAL' else 'NONE',evidence_level='RESEARCH_ARTIFACT_ONLY',**FLAGS)
 with ad._locked():
  raw,es=ad._read_validated();same=[e for e in es if e['execution_id']==c['execution_id']]
  assert (not same if event=='RUN_STARTED' else len([e for e in same if e['event_type']=='RUN_STARTED'])==1 and not any(e['event_type']=='TERMINAL' for e in same)),'LIFECYCLE'
  ad._append_unlocked(raw,es,spec);raw,es=ad._read_validated();sc=[e for e in es if e['route_id']==c['route_id']]
  count=lambda a:dict(routes=len({x['route_id'] for x in a}),events=len(a),executions=len({x['execution_id'] for x in a}),corrections=sum(x['event_type']=='CORRECTION' for x in a))
  receipt=dict(event_sha256=es[-1]['event_sha256'],registry_sha256=hashlib.sha256(raw).hexdigest(),registry_path=str(ad.registry_path),global_counts=count(es),scope_counts=count(sc),scope_unregistered_route_count=0,scope_contract_only_count=0,global_unregistered_route_count=None,global_contract_only_count=None,count_gap_reason='GLOBAL_DISCOVERY_NOT_IN_SCOPE',external_registry_persistence='CANNOT_CONFIRM',stage=stage,decision=decision,**FLAGS)
  for n in ['CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md']:
   with (ROOT/n).open('a') as f:f.write('\n<!-- WEEK_TWO_MODEL_COMPARISON_20261023 -->\n'+json.dumps(receipt,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  ip=ROOT/'contracts/ACTIVE_RESEARCH_INDEX.json';j=load(ip);j['week_two_model_comparison_20261023']=receipt;tmp=ip.with_suffix('.weekly.tmp');tmp.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,ip)
 save(OUT/(stage+'_REGISTRY_RECEIPT.json'),receipt);return receipt

def prepare():
 c60=load(R/'canonical_research_input_60/CONTRACT.json');binding=load(ROOT/'research/today_selection_20261023/MAC_INPUT_BINDING.json');c65=load(R/'same_input_ten_recall_65/CONTRACT.json')
 paths=[Path(__file__),R/'final_market_event_delta_64/INPUT_MANIFEST.json',R/'canonical_research_input_60/CONTRACT.json',R/'bound_prefix_repair_63/CONTRACT.json',R/'bound_prefix_repair_63/PREFIX_REPAIR_RECEIPT.json',R/'same_input_ten_recall_65/ALL_CANONICAL_RESULTS.jsonl',R/'same_input_ten_recall_65/CONTRACT.json',Path(binding['original_evaluator']['path']),Path(binding['delivered_formula']['path'])]
 paths += [Path(p) for p in c65['kernel_dependency_sha256']]
 b=dict(manifest=str(paths[1]),contract60=str(paths[2]),contract63=str(paths[3]),receipt63=str(paths[4]),reuse_b_D23=str(paths[5]),model_a=binding['original_evaluator']['path'],formula_a=binding['delivered_formula']['path'],model_b=c65['kernel_path'],raw_selector=c60['input_identity']['raw_selector'],archive=c60['input_identity']['archive'],native_refs=c60['input_identity']['native_refs'],event_refs=c60['input_identity']['event_refs'],dates=DATES)
 paths += [Path(b['native_refs']),Path(b['event_refs'])]
 contract=dict(GOAL='Five-day full existing research-pool selections and same-date Top100 descriptive overlap, plus D23 appendix',WRITER='weekly_writer',REVIEWER='root assigned independent reviewer',ALLOWED_PATHS=[str(OUT),str(Path(__file__).parent),'append-only root registry and minimum central summaries'],FORBIDDEN_PATHS=['original producers and sources','V3','pointers','services','UI','Windows','trading'],PASS_SIGNAL='Frozen signals before benchmark; complete dated candidates and tri-state ledgers; 5x100 benchmark or explicit gaps; reproducible overlap; independent reviewer verdict',STOP_RULE='No imputation/new data download; bound two evidenced repairs; preserve checkpoints',route_id='A_SHARE_WEEK_TWO_MODEL_COMPARISON_20261023',execution_id='A_SHARE_WEEK_TWO_MODEL_COMPARISON_20261023_01',track_id='A_SHARE_DESCRIPTIVE_TWO_FROZEN_FORMULA_COMPARISON',baseline_id='V192ORIG_255_VS_EXISTING_TEN_ROUTE_KERNEL',one_variable='Unchanged formula A versus unchanged formula B on common dated raw/event inputs',signal_date_range=['20261015','20261022'],target_date_range=['20261016','20261023'],truth_access='NOT_READ_UNTIL_ALL_SIGNAL_FILES_SEALED',sealed_status='OPENBOOK_DESCRIPTIVE_NOT_BREAKTHROUGH',runtime={'python_executable':PYTHON},device='MAC_LOCAL_CPU_CONFIGURABLE_2_CANARY_THEN_4_MAX',input_identity=b,input_sha256=digest(b),code_sha256=sha(__file__),frozen_source_bindings={str(p):sha(p) for p in dict.fromkeys(paths)},price_basis='EACH_SIGNAL_RAW_PREFIX_AND_EVENTS_LE_SIGNAL_UNROUNDED_AFFINE_SHARE_VOLUME',historical_PIT='CANNOT_CONFIRM_RETRIEVED20261023_NOT_ARCHIVED_VINTAGE',universe='5533 CURRENT_SOURCE_ELIGIBLE_RESEARCH_CODES_NOT_CERTIFIED_HISTORICAL_ALL_A',benchmark='Existing research pool; same-source close / event-adjusted previous-session close - 1; stable pct desc/code asc; no fills or daily substitutions',**FLAGS)
 save(OUT/'CONTRACT.json',contract);register(OUT/'CONTRACT.json','RUN_STARTED','WEEK_START',decision='RUNNING_STATIC_BIND_AND_CANARY');print(str(OUT/'CONTRACT.json'),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('phase');a=p.parse_args()
 if a.phase=='prepare':prepare()
