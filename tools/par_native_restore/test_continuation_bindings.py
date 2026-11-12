"""Regression for independent review R1: reuse requests and daily parent bindings.
Uses real, already-PASS checkpoints as immutable fixtures; no formula recompute.
"""
import copy,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import batch_restore
from continuation_checks import check_resume,check_saved_hashes,check_daily_parent,check_daily_result
from environment import observed_environment
from native_state import decode
from source_prefix import Loader


def main(root):
    source=Path(__file__).parent;original=json.loads((root/'native_states/bulk_nov9/000002.SZ.receipt.json').read_bytes());proof=json.loads((root/'validation/closed_nov9/OPTIMIZED_BOOTSTRAP_AND_TRUE_DAILY.json').read_bytes())
    cfg=dict(target='20261109',environment_binding=observed_environment(),driver_binding={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('batch_restore.py','bootstrap.py','source_prefix.py','environment.py','continuation_checks.py')})
    loader=Loader(root/'inputs/par_code_supplement',root/'inputs/source_bindings/handoff/unified_candidate_20261102/SOURCE_BINDINGS_V2.json',root/'PHYSICAL_INPUT_INDEX.json');parent=loader.bundle(original['source_ref'])
    success_path=root/'inputs/recovered_par/restore_baseline_20261112/tree/handoff/recovery_owner_v2/runs/run_nov10_recovered_nov9_v2_20261112/stocks/000002.SZ/SUCCESS.json';success=json.loads(success_path.read_bytes());child_ref=success['continuation_ref'];child=loader.bundle(child_ref)
    job=dict(symbol='000002.SZ',event_date='20261109',continuation_ref=original['source_ref'],advance_refs=[child_ref])
    assert check_resume(original,job,cfg,original['code_binding'])==0  # must queue the new day
    assert check_resume(original,{**job,'advance_refs':[]},cfg,original['code_binding'])==0
    check_saved_hashes(original)
    relocated={**cfg,'environment_binding':{**cfg['environment_binding'],'PANEL_PYTHON':'/relocated/python','actual_python':'/relocated/python'}}
    assert check_resume(original,job,relocated,original['code_binding'])==0
    rejected=[]
    for label,mutate in [('kernel',lambda x:x.update(code_binding={})),('source',lambda x:x.update(source_ref={'sha256':'WRONG'})),('runtime',lambda x:x['environment_binding'].update(python_version='WRONG'))]:
        bad=copy.deepcopy(original);mutate(bad)
        try:check_resume(bad,job,cfg,original['code_binding']);raise AssertionError(label)
        except ValueError:rejected.append(label)
    check_daily_parent(parent,child,'000002.SZ',original['source_ref'],1338)
    for label,mutate in [('parent_sha',lambda x:x['state51'].update(parent_state_sha256='WRONG')),('count',lambda x:x['state51'].update(count=999)),('asof',lambda x:x.update(asof='20261111'))]:
        bad=copy.deepcopy(child);mutate(bad)
        try:check_daily_parent(parent,bad,'000002.SZ',original['source_ref'],1338);raise AssertionError(label)
        except ValueError:rejected.append(label)
    advanced=decode(Path(proof['advanced']['path']).read_bytes());check_daily_result(advanced,child)
    bad=copy.deepcopy(advanced);bad['asof']='20261109'
    try:check_daily_result(bad,child);raise AssertionError('result_boundary')
    except ValueError:rejected.append('result_boundary')
    # Execute the actual dispatcher extension path using cached accepted output
    # as the delegate result. Initializer is forbidden; exactly1 step is required.
    fixture=root/'implementation/review_r1_regression';fixture.mkdir(parents=True,exist_ok=True);cfg['states']=str(fixture);receipt_path=fixture/'000002.SZ.receipt.json';receipt_path.write_text(json.dumps(original,ensure_ascii=False,indent=2)+'\n');calls=[]
    def cached_step(state,row):
        assert state['asof']=='20261109' and row['event_date']=='20261110';calls.append('step');return advanced['latest109'],copy.deepcopy(advanced),{'historical_primitive_rows_recomputed':0}
    kernel=SimpleNamespace(code_binding=original['code_binding'],step=cached_step)
    batch_restore._WORKER=(kernel,loader,cfg)
    with patch.object(batch_restore,'initialize_from_original',side_effect=AssertionError('unexpected historical initialization')),patch.object(batch_restore,'save_state',return_value=proof['advanced']):
        result=batch_restore.work(job)
    assert result['status']=='COMPLETE' and result['physical_asof']=='20261110' and calls==['step'],result
    report=dict(status='PASS',scope='Two independent review blockers only; cached genuine checkpoint fixtures, no indicator re-execution',added_advance_enqueued=True,existing_initialization_reused=True,step_delegations=1,paths_do_not_define_runtime_semantics=True,rejected=rejected,production_allowed=False)
    (root/'validation/REVIEW_R1_BINDING_REGRESSION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main(Path(sys.argv[1]))
