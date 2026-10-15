"""Read-only candidate consumer validation with the existing frozen engine."""
import argparse, collections, hashlib, json, os, sys
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('MWB_CANDIDATE_SOURCE_ROOT',Path(__file__).resolve().parents[3]));sys.path.insert(0,str(ROOT));H=Path(__file__).resolve().parent;SUFFIX='_runtime' if os.environ.get('MWB_CANDIDATE_SOURCE_ROOT') else ''
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import HK, Lane, Phase, RunContext
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.engines.oversold import run_oversold, comparison_proven

def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--full',action='store_true');p.add_argument('--stdout-only',action='store_true');p.add_argument('--config',type=Path);a=p.parse_args();mode='full' if a.full else 'canary'
 source=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v9.json');raw=source.read_bytes();cfg=json.loads(raw)
 pin=json.loads((H/f'phase_b_{mode}_capture_r2.json').read_bytes())['capture']
 if a.config:
  candidate=json.loads(a.config.read_bytes());assert candidate['source_bindings']['hk_panel']['20261015']['tdxpy_history']==pin;cfg=candidate
 else:cfg['source_bindings'].setdefault('hk_panel',{}).setdefault('20261015',{})['tdxpy_history']=pin
 config=WorkbenchConfig.model_validate(cfg);adapter=NativeAdapters(config)
 ctx=adapter.prepare_context(RunContext(target_date='20261016',phase=Phase.MANUAL,cutoff=datetime.now(HK).isoformat(),trigger='MANUAL',rules_version=config.rules_version,scope_refs={'requested_lanes':['OVERSOLD']}))
 batch=adapter.load(Lane.OVERSOLD,ctx);result=run_oversold(ctx.model_dump(mode='json'),batch.model_dump(mode='json'))
 rows=result['stocks'] if 'stocks' in result else result['rows']
 proof=[r for r in batch.records if r.get('comparison_basis')]
 r=dict(mode=mode,context=ctx.model_dump(mode='json'),base_config_sha256=sha(raw),tdxpy_pin=pin,
  input_sha256=batch.input_sha256,scope_count=len(batch.records),comparison_records=len(proof),comparison_proven=sum(comparison_proven(r,ctx.model_dump(mode='json')) for r in proof),
  decisions=dict(collections.Counter(x['decision'] for x in rows)),reasons=dict(collections.Counter(x['reason'] for x in rows)),
  selected=[x for x in rows if x['decision']=='SELECTED'],canary=[x for x in rows if x['symbol']=='HK.00001'],batch_gaps=batch.gaps,
  source_sha256={x:sha((ROOT/x).read_bytes()) for x in ['upstreams/v3_shared_data/shared_data/hk_daily_supplement.py','v4/manager_workbench/inputs/native.py','v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/engines/oversold.py']})
 if not a.stdout_only:
  with (H/f'phase_b_{mode}_validation{SUFFIX}.json').open('x') as f:json.dump(r,f,ensure_ascii=False,indent=2);f.write('\n')
 print(json.dumps({**{k:r[k] for k in ['decisions','reasons','comparison_records','comparison_proven']},'selected_symbols':[x['symbol'] for x in r['selected']]},ensure_ascii=False))
if __name__=='__main__':main()
