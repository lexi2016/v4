"""Targeted offline binding verification; real unchanged strategy and scoring functions."""
import sys
sys.dont_write_bytecode=True
import ast, copy, dataclasses, hashlib, importlib.util, json, math, types, unittest
from datetime import datetime, timedelta
from pathlib import Path

P=Path(__file__).resolve().parent
Z=P.parent
OUT=Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True,exist_ok=True)
sys.argv=sys.argv[:1]

def load(name,path,package=False):
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)] if package else None)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def ns(name):
    m=types.ModuleType(name);m.__path__=[];sys.modules[name]=m;return m
def forbidden(*a,**kw): raise RuntimeError('FORBIDDEN_SQLITE_OR_PROVIDER')

offline=load('binding_original_offline_loader',Z/'offline_runner.py')
core,ind,_=offline.algorithms({}, {})
ns('modules.self_optimizer')
paths=types.ModuleType('modules.core.paths');paths.REGISTRY_DIR=OUT/'isolated_empty_registry';sys.modules[paths.__name__]=paths
load('modules.constants',P/'original/modules/constants.py')
load('modules.core.market_context',P/'original/modules/core/market_context.py')
params=load('modules.self_optimizer.param_registry',P/'original/modules/self_optimizer/param_registry.py')
assert params._ACTIVE_OVERRIDES=={}

# Execute the exact upstream converters without importing their provider-heavy module.
source=ast.parse((P/'original/modules/datasource.py').read_text())
functions=[x for x in source.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name in ('dict_to_daily','daily_to_dict')]
assert len(functions)==2
exec(compile(ast.Module(body=functions,type_ignores=[]),str(P/'original/modules/datasource.py'),'exec'),vars(sys.modules['modules.datasource']))
strategies=ns('modules.strategies')
load('modules.strategies.core',P/'original/modules/strategies/core.py')
for name in ['base_strategies','b1_b2','compound_strategies','sell_signals']:
    load('modules.strategies.'+name,P/'original/modules/strategies'/ (name+'.py'))
strategies=load('modules.strategies',P/'original/modules/strategies/__init__.py',True)
strategies.get_kline_data=forbidden
sys.modules['modules.strategies.core'].get_db_connection=forbidden
screener=ns('modules.screener');screener.StockScore=sys.modules['modules.screener.models'].StockScore;screener.analyze_stock=forbidden
sys.modules['modules.datasource'].get_datasource=forbidden
sim=load('modules.simulator',P/'original/modules/simulator/__init__.py',True)
for name in ['strategy_adapter','resonance_scorer','environment_weights']:
    load('modules.simulator.'+name,P/'original/modules/simulator'/ (name+'.py'))
binding=load('modules.simulator.input_binding',P/'patched/modules/simulator/input_binding.py')
fixed=load('modules.simulator.signal_filter',P/'patched/modules/simulator/signal_filter.py')
old=load('modules.simulator.signal_filter_original',P/'original/modules/simulator/signal_filter.py')
def fence(event,args):
    if event.startswith(('socket.','sqlite3.connect','subprocess.Popen','os.system')): forbidden()
sys.addaudithook(fence)

SOURCE=OUT/'SENTINEL_SOURCE_MANIFEST.json'
SOURCE.write_text(json.dumps({'kind':'SYNTHETIC_BINDING_SENTINEL','units':{'price':'CNY','volume':'SHARES','amount':'CNY','pct_chg':'PERCENT_POINTS'},'cutoff':'20261022'},sort_keys=True)+'\n')
SOURCE_SHA=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
CONFIG=sim.SimulationConfig(strategy_mode='resonance')
def bind(**kw):
    values=dict(source_manifest_path=str(SOURCE),source_manifest_sha256=SOURCE_SHA,signal_asof='20261022',selection_date='20261023',configuration_sha256=binding.configuration_identity(CONFIG),price_basis='RAW_UNADJUSTED',price_unit='CNY',volume_unit='SHARES',amount_unit='CNY',pct_chg_unit='PERCENT_POINTS')
    values.update(kw);return binding.ResonanceInputBinding(**values)
def bars(code='600000.SH',n=150):
    end=datetime(2026,10,22);rows=[]
    for i in range(n):
        close=10+i*.003+math.sin(i/5)*.05;volume=100000+(i%9)*1000
        rows.append(core.DailyData(ts_code=code,trade_date=(end-timedelta(days=n-i-1)).strftime('%Y%m%d'),open=close-.01,high=close+.03,low=close-.03,close=close,vol=volume,amount=close*volume,pct_chg=.1,prev_close=close-.01))
    return rows
def evaluate(rows,**kw):
    return fixed.evaluate_stock(rows[0].ts_code,'20261022',klines=rows,config=CONFIG,input_binding=kw.pop('input_binding',bind()),**kw)

class BindingTests(unittest.TestCase):
    def test_old_ignores_input_reproduced(self):
        with self.assertRaisesRegex(RuntimeError,'FORBIDDEN_SQLITE_OR_PROVIDER'):
            old.evaluate_stock('600000.SH','20261022',klines=bars(),config=CONFIG)

    def test_real_three_code_chain_dict_window_and_immutability(self):
        original=fixed.detect_all_strategies;observed=[]
        def traced(code,days=120,klines=None):
            self.assertIsNotNone(klines);self.assertTrue(all(type(x) is dict for x in klines))
            self.assertEqual(len(klines),120);self.assertEqual(klines[-1]['trade_date'],'20261022')
            self.assertTrue(all(x['ts_code']==code for x in klines));observed.append(code)
            return original(code,days=days,klines=klines)
        fixed.detect_all_strategies=traced
        try:
            for code in ['600000.SH','000001.SZ','920000.BJ']:
                rows=bars(code);before=copy.deepcopy(rows);result=evaluate(rows)
                self.assertEqual(rows,before);self.assertEqual(result.date,'20261022')
                self.assertEqual(result.input_binding['source_manifest_sha256'],SOURCE_SHA)
                self.assertEqual(result.input_binding['selection_date'],'20261023')
        finally: fixed.detect_all_strategies=original
        self.assertEqual(len(observed),3)

    def test_future_append_invariant_and_no_database(self):
        rows=bars();before=copy.deepcopy(rows);base=evaluate(rows)
        future=dataclasses.replace(rows[-1],trade_date='20261023',close=999999,high=999999,vol=999999999,amount=999999999)
        got=evaluate(rows+[future])
        self.assertEqual(dataclasses.asdict(base),dataclasses.asdict(got))
        self.assertEqual(base.input_binding,got.input_binding);self.assertEqual(rows,before)
        # Swapping the ambient SQL/provider lookup cannot affect an explicit-input call.
        calls=[]
        strategies.get_kline_data=lambda *a,**kw:calls.append('DATABASE_B') or []
        try: other=evaluate(rows)
        finally: strategies.get_kline_data=forbidden
        self.assertEqual(calls,[]);self.assertEqual(dataclasses.asdict(base),dataclasses.asdict(other))

    def test_explicit_rejections_before_detector(self):
        cases=[]
        cases.append(('empty',[],bind(),'20261022'))
        cases.append(('stale',bars()[:-1],bind(),'20261022'))
        wrong=bars();wrong[-1]=dataclasses.replace(wrong[-1],ts_code='000001.SZ');cases.append(('code',wrong,bind(),'20261022'))
        nan=bars();nan[-1]=dataclasses.replace(nan[-1],amount=float('nan'));cases.append(('nan',nan,bind(),'20261022'))
        duplicate=bars();duplicate[-1]=duplicate[-2];cases.append(('duplicate',duplicate,bind(),'20261022'))
        cases.append(('units',bars(),bind(volume_unit='LOTS'),'20261022'))
        cases.append(('basis',bars(),bind(price_basis='QFQ'),'20261022'))
        cases.append(('sha',bars(),bind(source_manifest_sha256='0'*64),'20261022'))
        cases.append(('config',bars(),bind(configuration_sha256='0'*64),'20261022'))
        cases.append(('selection_as_signal',bars(),bind(),'20261023'))
        cases.append(('missing_binding',bars(),None,'20261022'))
        missing=[dict(ts_code=x.ts_code,trade_date=x.trade_date,open=x.open,high=x.high,low=x.low,close=x.close,vol=x.vol,pct_chg=x.pct_chg) for x in bars()];cases.append(('missing_amount',missing,bind(),'20261022'))
        original=fixed.detect_all_strategies;fixed.detect_all_strategies=forbidden
        try:
            for name,rows,b,day in cases:
                with self.subTest(name=name),self.assertRaises(binding.InputBindingError):
                    fixed.evaluate_stock('600000.SH',day,klines=rows,config=CONFIG,input_binding=b)
        finally: fixed.detect_all_strategies=original

    def test_direct_caller_uses_signal_context_not_entry_context(self):
        rows=bars();asof=sim.MarketContext('20261022',sim.MarketRegime.NEUTRAL,50,0,50)
        future=sim.MarketContext('20261023',sim.MarketRegime.STRONG,100,1,100)
        got=binding.evaluate_signal_window('600000.SH',rows,'20261023',{'20261022':asof,'20261023':future},CONFIG,bind())
        expected=evaluate(rows,context=asof)
        self.assertEqual(dataclasses.asdict(got),dataclasses.asdict(expected))
        self.assertEqual(got.input_binding['context_availability'],'EXPLICIT_ASOF_CONTEXT')
        absent=binding.evaluate_signal_window('600000.SH',rows,'20261023',{'20261023':future},CONFIG,bind())
        self.assertEqual(absent.input_binding['context_availability'],'UNAVAILABLE_EXPLICIT_NEUTRAL')
        self.assertEqual(dataclasses.asdict(absent),dataclasses.asdict(evaluate(rows)))
        with self.assertRaises(binding.InputBindingError): evaluate(rows,context=future)

    def test_caller_patch_and_strategy_bytes_not_rewritten(self):
        source=(P/'patched/modules/simulator/simulator.py').read_text()
        self.assertIn('evaluate_signal_window(code, signal_window, date, market_contexts, config, binding)',source)
        self.assertIn('binding = input_bindings.get((code, signal_date, date))',source)
        tree=ast.parse(source);run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_simulation')
        # Execute only the early explicit-binding guard: this is not a simulation/backtest.
        nsrun={'SimulationConfig':sim.SimulationConfig,'InputBindingError':binding.InputBindingError,'get_datasource':forbidden}
        guard=[n for n in run.body if isinstance(n,(ast.Assign,ast.If))][:3]
        self.assertEqual(len(guard),3)
        for dsval in [None,object()]:
            nsrun.update(config=CONFIG,datasource=dsval,input_bindings=None)
            with self.assertRaises(binding.InputBindingError): exec(compile(ast.Module(body=guard,type_ignores=[]),'<actual_caller_guard>','exec'),nsrun)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(BindingTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps(dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),scope='ISOLATED_RESONANCE_INPUT_BINDING_ONLY',data='3_CODE_SYNTHETIC_SENTINEL_WITH_REAL_UNCHANGED_STRATEGY_DETECTOR',source_manifest_sha256=SOURCE_SHA,network_calls=0,sqlite_connections=0,full_pool_runs=0,backtests=0,b1_rule_modified=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)))
    sys.exit(0 if result.wasSuccessful() else 1)
