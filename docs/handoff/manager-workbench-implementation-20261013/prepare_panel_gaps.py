"""Read the verified shared panel and prepare only its machine-proven gaps.

No acquisition, model call, formal write, new producer, or threshold change.
The existing supplement owner consumes this immutable parent/gap identity.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json
HERE=Path(__file__).resolve().parent

def prepare(args):
 from v4.manager_workbench.config import WorkbenchConfig
 from v4.manager_workbench.contracts import RunContext,Phase
 from v4.manager_workbench.inputs.native import NativeAdapters
 from v4.manager_workbench.inputs.source_bindings import hk_panel
 config=WorkbenchConfig.model_validate(json.loads(args.base_config.read_bytes()))
 adapter=NativeAdapters(config)
 context=adapter.prepare_context(RunContext(target_date=args.target_date,phase=Phase.RETROSPECTIVE,
     trigger='MANUAL',cutoff=args.cutoff,rules_version=config.rules_version))
 # The default entry is the actual verified shared panel, never the history pin.
 pin=hk_panel(config,context)
 context.scope_refs.setdefault('owner_bindings',{})['hk_panel']=pin
 plan=adapter.panel_gap_plan(context)
 output=args.output.resolve()
 if output.exists() or not output.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('NEW_ISOLATED_HANDOFF_OUTPUT_REQUIRED')
 output.mkdir(parents=True)
 path=output/'panel-gaps.json';path.write_text(json.dumps(plan,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 projection=config.model_dump(mode='json')
 projection.setdefault('source_bindings',{}).setdefault('hk_panel',{})[plan['price_date']]=pin
 base=output/'base-config.json';base.write_text(json.dumps(projection,ensure_ascii=False,indent=2)+'\n')
 receipt=dict(status='PANEL_GAPS_PREPARED_NOT_CAPTURED',panel_gap_path=str(path),
     panel_gap_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),config_path=str(base),
     config_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),target_date=plan['target_date'],price_date=plan['price_date'],
     master_scope_count=plan['master_scope_count'],panel_valid_count=plan['panel_valid_count'],gap_count=len(plan['gap_codes']),
     actual_panel_identity=plan['panel_identity'],cutoff=plan['cutoff'],
     network_calls=0,model_calls=0,formal_writes=0)
 (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(receipt,ensure_ascii=False),flush=True)
 return receipt

def main():
 spec=importlib.util.spec_from_file_location('accepted_calendar_runtime',HERE/'recover_cached_full_date.py')
 runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime);runtime.install_runtime()
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--base-config',required=True,type=Path);p.add_argument('--target-date',default='20261013')
 p.add_argument('--cutoff',required=True);p.add_argument('--output',required=True,type=Path)
 prepare(p.parse_args())
if __name__=='__main__':main()
