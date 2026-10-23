"""Incremental real three-symbol binding checks; do not rerun the old six fixtures."""
import sys
sys.dont_write_bytecode=True
import copy,dataclasses,hashlib,importlib.util,json
from pathlib import Path
P=Path(__file__).resolve().parent
cp=Path(sys.argv[1]);c=json.loads(cp.read_text());out=Path(c['output_directory']);out.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
def load(name,path,package=False):
 spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)] if package else None);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
sys.argv=[str(P.parent/'test_binding.py'),str(out/'loader_scope')]
s=load('r2_original_dependency_loader',P.parent/'test_binding.py')
sim=load('modules.simulator',P/'patched/modules/simulator/__init__.py',True)
for name in ['strategy_adapter','resonance_scorer','environment_weights']:load('modules.simulator.'+name,P.parent/'original/modules/simulator'/(name+'.py'))
helper=load('modules.simulator.input_binding',P/'patched/modules/simulator/input_binding.py')
fixed=load('modules.simulator.signal_filter',P/'patched/modules/simulator/signal_filter.py')
manifest_path=Path(c['manifest_path']);sample_path=Path(c['sample_path']);assert sha(manifest_path)==c['input_sha256'];assert sha(sample_path)==c['sample_sha256']
manifest=json.loads(manifest_path.read_text());samples=json.loads(sample_path.read_text());cfg=sim.SimulationConfig(strategy_mode='resonance');native=s.strategies.detect_all_strategies
def bind(path=manifest_path,**kw):
 x=dict(source_manifest_path=str(path),source_manifest_sha256=sha(path),signal_asof='20261022',selection_date='20261023',configuration_sha256=helper.configuration_identity(cfg),price_basis='RAW_UNADJUSTED',price_unit='CNY',volume_unit='SHARES',amount_unit='CNY',pct_chg_unit='PERCENT_POINTS');x.update(kw);return helper.ResonanceInputBinding(**x)
def evaluate(code,rows,b=None,context=None):return fixed.evaluate_stock(code,'20261022',klines=rows,config=cfg,context=context,input_binding=b or bind())
reports=[];checks=[]
for code in ['600000.SH','000001.SZ','920000.BJ']:
 rows=samples[code];before=helper.digest(rows);seen=[]
 def observed(ts_code,days=120,klines=None):
  assert ts_code==code and days==120 and len(klines)==120 and all(type(r) is dict for r in klines)
  assert klines[-1]['trade_date']=='20261022' and helper.digest(klines)==before
  raw=native(ts_code,days=days,klines=klines);seen.append(helper.digest([dataclasses.asdict(v) for v in raw]));return raw
 fixed.detect_all_strategies=observed
 got=evaluate(code,rows);baseline=native(code,days=120,klines=copy.deepcopy(rows))
 assert seen==[helper.digest([dataclasses.asdict(v) for v in baseline])],'NATIVE_EXPLICIT_WINDOW_PARITY'
 assert helper.digest(rows)==before,'CALLER_INPUT_MUTATED'
 serialized=json.loads(json.dumps(dataclasses.asdict(got),default=lambda value:value.value))
 assert serialized['input_binding']==got.input_binding and serialized['input_binding']['producer_expected_window']['sha256']==before,'BINDING_SERIALIZATION_LOST'
 future=copy.deepcopy(rows[-1]);future['trade_date']='20261023';future.update(close=999999.,high=999999.,amount=999999999.,vol=999999999.)
 augmented=evaluate(code,rows+[future]);assert dataclasses.asdict(got)==dataclasses.asdict(augmented),'FUTURE_APPEND_CHANGED_RESULT'
 calls=[];s.strategies.get_kline_data=lambda *a,**kw:calls.append('AMBIENT_SQL_B') or []
 try:alternate=evaluate(code,rows)
 finally:s.strategies.get_kline_data=s.forbidden
 assert not calls and dataclasses.asdict(alternate)==dataclasses.asdict(got),'AMBIENT_SOURCE_AFFECTED_RESULT'
 reports.append(dict(ts_code=code,input_rows=120,last_date=rows[-1]['trade_date'],window_sha256=before,native_signals=len(baseline),native_signals_sha256=seen[0],explicit_detector_parity=True,caller_input_unchanged=True,serialized_binding=serialized['input_binding']))
fixed.detect_all_strategies=native
code='600000.SH';rows=samples[code]
def rejects(label,values,b=None,context=None,expected=None):
 calls=[]
 def no_detector(*a,**kw):calls.append(1);raise AssertionError('DETECTOR_REACHED_BEFORE_REJECTION')
 fixed.detect_all_strategies=no_detector
 try:
  try:evaluate(code,values,b,context)
  except helper.InputBindingError as exc:
   assert expected is None or expected in str(exc),(label,str(exc));checks.append(dict(case=label,error=str(exc),before_detector=True))
  else:raise AssertionError('INVALID_BOUND_INPUT_ACCEPTED:'+label)
  assert not calls
 finally:fixed.detect_all_strategies=native
changed=copy.deepcopy(rows)
for key in ['open','high','low','close']:changed[-1][key]+=.001
rejects('changed_current_price_same_manifest',changed,expected='PRODUCER_WINDOW_SHA')
changed=copy.deepcopy(rows)
for row in changed:
 for key in ['open','high','low','close']:row[key]*=2
rejects('different_price_series_same_manifest',changed,expected='PRODUCER_WINDOW_SHA')
rejects('empty',[]);rejects('stale',rows[:-1])
changed=copy.deepcopy(rows);changed[-1]['ts_code']='000001.SZ';rejects('wrong_code',changed)
changed=copy.deepcopy(rows);changed[-1]['amount']=float('nan');rejects('nonfinite_amount',changed)
changed=copy.deepcopy(rows);del changed[-1]['amount'];rejects('missing_amount',changed)
rejects('wrong_units',rows,bind(volume_unit='LOTS'));rejects('wrong_cutoff',rows,bind(signal_asof='20261021'))
future_context=sim.MarketContext('20261023',sim.MarketRegime.STRONG,100,1,100);rejects('future_context',rows,context=future_context)
for label,mutator in [
 ('wrong_expected_hash',lambda x:x['windows'][0].update(sha256='0'*64)),
 ('duplicate_key',lambda x:x['windows'].append(copy.deepcopy(x['windows'][0]))),
 ('wrong_manifest_units',lambda x:x['units'].update(volume='LOTS')),
 ('wrong_manifest_selection',lambda x:x.update(selection_date='20261024')),
 ('wrong_owner_sha',lambda x:x['source_identity'].update(sha256='0'*64)),
]:
 altered=copy.deepcopy(manifest);mutator(altered);path=out/(label+'.json');save(path,altered);rejects(label,rows,bind(path))
asof_context=sim.MarketContext('20261022',sim.MarketRegime.NEUTRAL,50,0,50)
called=helper.evaluate_signal_window(code,rows,'20261023',{'20261022':asof_context,'20261023':future_context},cfg,bind());assert called.input_binding['context_availability']=='EXPLICIT_ASOF_CONTEXT'
absent=helper.evaluate_signal_window(code,rows,'20261023',{'20261023':future_context},cfg,bind());assert absent.input_binding['context_availability']=='UNAVAILABLE_EXPLICIT_NEUTRAL'
summary=dict(status='PASS',scope='ISOLATED_RESONANCE_SOURCE_WINDOW_BINDING_AND_SERIALIZATION',real_symbols=reports,rejection_cases=checks,source_manifest_sha256=sha(manifest_path),sample_artifact_sha256=sha(sample_path),synthetic_six_tests_rerun=0,network_calls=0,sqlite_connections=0,backtests=0,full_pool_runs=0,b1_rule_modified=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
save(out/'REAL_VERIFY_RECEIPT.json',summary)
print(json.dumps(summary,ensure_ascii=False),flush=True)
