"""Run existing native runner in fresh evidence-only stores; no actual stage writes."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,hashlib,json,os,socket,subprocess,sys
from cached_source import audit_cache, cached_collector, sha, require
HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path);args=ap.parse_args()
E=args.out.resolve();require(E.is_relative_to(HERE),'isolated output escaped scope');E.mkdir(exist_ok=False)
pins=json.loads((HERE/'operator_capsule_pins.json').read_text())
r=Path(pins['expected_runtime_root'])
for p,h in pins['input_pins'].items():require(sha(p)==h,'input changed: '+p)
for p,h in pins['dependency_pins'].items():require(sha(r/p)==h,'dependency changed: '+p)
d,target=audit_cache(pins)
coverage={'capture_path':pins['capture_path'],'capture_sha256':pins['capture_sha256'],'capture_time':d['captured_at'],
    'source_method':'OpenQuoteContext.get_cur_kline K_1M AuType.NONE num_bars=1000',
    'source_stage':'STAGE_0935_0940','target_stage':'STAGE_0930_0935','target_date':'20261021',
    'timezone':'Asia/Hong_Kong (provider naive local time; inherited HK route semantics)',
    'strict_window':'(09:30:00,09:35:00]','target_rows':len(target),'target_codes':len({x['code'] for x in target}),
    'missing':sorted(set(pins['expected_codes'])-{x['code'] for x in target}),
    'extra':sorted({x['code'] for x in target}-set(pins['expected_codes'])),
    'target_rows_sha256':hashlib.sha256(json.dumps(target,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
    'natural_time_capture':'CANNOT_CONFIRM','pit_safe':False,'formal_stage_eligibility':'CANNOT_CONFIRM',
    'original_window_orderbook':'CANNOT_CONFIRM','provider_network_requests':0}
require(json.loads((E/'cache_coverage.json').read_text()) == coverage, 'coverage changed') if (E/'cache_coverage.json').exists() else (E/'cache_coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2))

def deny(*a,**kw):raise RuntimeError('EXTERNAL_IO_FORBIDDEN_IN_ISOLATED_CACHE_REPLAY')
socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny;subprocess.Popen=deny;os.system=deny
sys.path.insert(0,str(r))
from ops import run_stage_center_nodes as nodes
from stage_center import runner as rm,live_collectors as lc
from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
from recover_hk_0930_reviewed import a_snapshot,OneShotScope
cfg=json.loads(Path(pins['expected_config_path']).read_text())
before=a_snapshot(cfg)
box=E/'isolated_run'
box.mkdir(exist_ok=False)
for key,leaf in [('raw_root','raw'),('selection_root','selection'),('receipt_root','receipts')]:cfg[key]=str(box/leaf)
# The native scope verifies its preserved sibling when assembling the bundle.
# Copy only the exact A raw trio + pointer into the isolated stores.
import shutil
actual_raw=Path(pins['expected_config']['raw_root'])
raw_index=json.loads((actual_raw/'latest.json').read_text())
entry=raw_index['entries']['20261021/STAGE_0930_0935/A_SHARE']
source_dir=(actual_raw/entry['artifact_relative']).parent
for f in source_dir.iterdir():
    if f.is_file():
        destination=Path(cfg['raw_root'])/f.relative_to(actual_raw)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(f,destination)
raw_index['entries']={'20261021/STAGE_0930_0935/A_SHARE':entry}
(Path(cfg['raw_root'])/'latest.json').write_text(json.dumps(raw_index))
prior_raw=Path(pins['original_receipt_path']).read_bytes();prior=json.loads(prior_raw)
rp=Path(cfg['receipt_root'])/'20261021/STAGE_0930_0935/receipt.json';rp.parent.mkdir(parents=True);rp.write_bytes(prior_raw)
original=nodes._build_runner(cfg)
require(not original.config.injected_test_mode,'native validation disabled')
observed={}
original.collectors={'HK_CONNECT':cached_collector(r,original.config,pins,observed)}
factory=lc.production_selection_builders
hk_builder=factory('STAGE_0930_0935')['HK_CONNECT']
def builder(source,plan,raw):
    observed['selector_input_codes']=[x['code'] for x in source.rows]
    result=hk_builder(source,plan,raw)
    observed['selector_output_codes']=[x['code'] for x in result.get('rows',[])]
    observed['selector_trade_statuses']=sorted({x.get('trade_status') for x in result.get('rows',[])})
    return result
lc.production_selection_builders=lambda stage_id,**kw:{'HK_CONNECT':builder}
now=datetime.now(ZoneInfo('Asia/Shanghai'));decision=next(x for x in original.due_decisions('20261021',now) if x.stage_id=='STAGE_0930_0935')
decision.same_day_late_observation_recovery=True
lock=rm.SlotLock(rm._slot_lock_path(original.config,'20261021','STAGE_0930_0935'))
require(lock.acquire(),'isolated lock unavailable')
try:
    scoped=scoped_recovery_runner(original,markets=('HK_CONNECT',),prior_receipt=prior,attempt_count=2,origin='HK_AUTHORIZED_ONE_SHOT_OPERATOR_RECOVERY')
    scoped._execution_scope=OneShotScope(scoped._execution_scope)
    result=scoped._run_one(decision)
finally:lock.release()
require(a_snapshot(pins['expected_config'])==before,'actual A changed')
require(sha(pins['original_receipt_path'])==pins['original_receipt_sha256'],'actual owner changed')
with (E/'isolated_result.json').open('x') as f:json.dump({'result':result,'observed':observed,'A_PRESERVED':True,'actual_owner_unchanged':True},f,ensure_ascii=False,indent=2)
print(json.dumps({'status':result['status'],'HK':result['markets']['HK_CONNECT'],'observed':observed},ensure_ascii=False))
require(result['markets']['HK_CONNECT'].get('selected_rows')==10,'native selected10 absent')
require(set(observed['selector_input_codes'])==set(pins['expected_codes']) and len(observed['selector_input_codes'])==100,'native selector input100 absent')
require(result['markets']['A_SHARE']==prior['markets']['A_SHARE'],'A lane object changed')
