"""One-off original-owner recovery. Default is read-only preflight.

The controller may run --execute only after the independent review. No pointer
or manifest is edited here: publication is through the original producer/CAS.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
FIELDS=('ts_code','date8','entry_pool','candidate_role','multi_head_final_role','final_score',
    'risk_chase_score','fresh_b2_entry_score','continuation_entry_score','hold_through_main_wave_score',
    'multi_entry_score','multi_entry_risk_adjusted_score','B1','B2','B3','BG','gold_brick_context',
    'brick_resonance_context','brick_buy','brick_buy1_low_absorb','brick_buy2_attack',
    'primary_buy_signal','secondary_buy_signal','fresh_b2_entry_window','late_extension_flag',
    'risk_hard_stop_flag','risk_warning_flag','dist_white_pct','dist_bbi_pct',
    'low20_to_close','ret_pre20','upper_shadow_pct')
STORE=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with p.open('x')as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--day',choices=['20261111','20261112'],required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--native-only',action='store_true');parser.add_argument('--review-file',type=Path);args=parser.parse_args()
    plan=json.loads((HERE/'INACTIVE_CANDIDATES_R3.json').read_bytes());identities=json.loads((HERE/'SOURCE_IDENTITIES.json').read_bytes())
    bound=plan['roles']['main']['binding'];app=Path(bound['app_root']);shared=Path(plan['shared_package_root'])
    assert sha(bound['manifest_path'])==bound['manifest_sha256']
    sys.path.insert(0,str(app))
    from infrastructure.formula_generation import read_selector_source_binding
    from infrastructure.isolated_package_loader import load_isolated_package_module
    from ops import materialize_shared_v192_preselection as wrapper
    actual=read_selector_source_binding(identities[args.day]['path'],expected_signal_date=args.day)
    assert actual=={k:v for k,v in identities[args.day].items()if k!='status'}
    target={'20261111':'20261112','20261112':'20261113'}[args.day]
    owner=load_isolated_package_module(shared,package_directory='shared_data',module_leaf='v192_selector',namespace_prefix='reviewed_v192_recovery')
    argv=['--signal-date',args.day,'--target-date',target,'--source-panel',actual['path']]
    if args.day=='20261112':argv+=['--historical-backfill','--expected-previous-json',str(HERE/'D12_EXPECTED_PREVIOUS.json')]
    plan_ref=dict(mode='BACKFILL_NOT_NATURAL',signal_date=args.day,target_date=target,source_panel=actual,
        producer=dict(path=str(Path(owner.__file__)),sha256=sha(owner.__file__)),wrapper=dict(path=str(Path(wrapper.__file__)),sha256=sha(wrapper.__file__)),
        original_oracle_sha256s=owner.verify_oracle_sources(),store_root=str(STORE),argv=argv,**FLAGS)
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    native_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
    native_store=PreselectionPoolStore(native_root)
    preimage_path=HERE/(args.day+'_NATIVE_PREIMAGE.json')
    if not args.execute:
        try:
            snapshot=native_store.read_pool_snapshot(target,'a_d1_premarket_pool')
            preimage=dict(status='PRESENT',expected_previous={k:snapshot[k]for k in
                ['artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256']},
                source_run_id=snapshot['artifact'].get('source_run_id'))
        except FileNotFoundError:
            preimage=dict(status='MISSING')
        if preimage_path.exists():assert json.loads(preimage_path.read_bytes())==preimage
        else:save(preimage_path,preimage)
        print(json.dumps(dict(status='PREFLIGHT_ONLY_NO_PUBLICATION',**plan_ref),ensure_ascii=False,indent=2));return
    assert args.review_file is not None,'EXACT_INDEPENDENT_REVIEW_REQUIRED'
    review=json.loads(args.review_file.read_bytes())
    assert review['verdict']=='REVIEWED/PASS' and review['frozen_scope_sha256']==sha(HERE/'FROZEN_HANDOFF.json')
    frozen=json.loads((HERE/'FROZEN_HANDOFF.json').read_bytes())
    for reference in frozen['evidence_files']:
        assert sha(reference['path'])==reference['sha256'],'REVIEWED_FILE_DRIFT:'+reference['path']
    preimage=json.loads(preimage_path.read_bytes())
    def publish_native():
        from domains.preselection_materializer import build_shared_v192_premarket_pool
        payload=build_shared_v192_premarket_pool(STORE,trade_date=target,signal_date=args.day,shared_package_root=shared)
        try:
            snapshot=native_store.read_pool_snapshot(target,'a_d1_premarket_pool')
        except FileNotFoundError:
            if preimage['status']!='MISSING':raise ValueError('NATIVE_PREIMAGE_UNEXPECTED_ABSENCE')
            result=native_store.materialize(payload)
        else:
            if snapshot['artifact']==payload:
                return dict(status='ALREADY_CURRENT',artifact_sha256=snapshot['artifact_sha256'])
            if preimage['status']!='PRESENT':raise ValueError('NATIVE_PREIMAGE_UNEXPECTED_EXISTENCE')
            result=native_store.refresh_verified_v192_source(payload,expected_previous=preimage['expected_previous'],
                shared_root=STORE,shared_package_root=shared,selector_panel=Path(actual['path']),signal_date=args.day)
        check=native_store.read_pool(target,'a_d1_premarket_pool')
        if check!=payload:raise ValueError('NATIVE_ORIGINAL_BUILDER_POSTCHECK_FAILED')
        return dict(status='PUBLISHED',result=result,count=len(payload['rows']),source_run_id=payload['source_run_id'],
            source_manifest_sha256=payload['source_manifest_sha256'],source_receipt_sha256=payload['source_receipt_sha256'])
    result_path=HERE/(args.day+'_RECOVERY.json')
    if result_path.exists():raise ValueError('RECOVERY_RECEIPT_EXISTS_REUSE_AND_INSPECT_DO_NOT_RECOMPUTE')
    # Observe only the already-computed target-day frame at the frozen role
    # call. Return the original result object; never alter selection or scores.
    original_load=owner._load_module;captured=[]
    def observe_load(name,path):
        module=original_load(name,path)
        if name=='v3sd_v192_role_oracle':
            original=module.base_fmla04_role
            def observe(day):
                result=original(day)
                if captured:raise ValueError('UNEXPECTED_SECOND_ROLE_EVALUATION')
                frame=day.loc[day['date8'].astype(str).eq(args.day)].copy()
                frame['candidate_role']=result.loc[frame.index]
                available=[key for key in FIELDS if key in frame.columns]
                output=HERE/(args.day+'_V192_DAY_DIAGNOSTIC.csv')
                if output.exists():raise ValueError('DIAGNOSTIC_EXISTS_INSPECT_BEFORE_RETRY')
                frame[available].to_csv(output,index=False)
                captured.append(dict(path=str(output),sha256=sha(output),row_count=len(frame),columns=available,
                                     unavailable_columns=[key for key in FIELDS if key not in available]))
                return result
            module.base_fmla04_role=observe
        return module
    owner._load_module=observe_load
    def same_owner(package,**kwargs):
        assert Path(package).resolve()==shared.resolve() and kwargs['module_leaf']=='v192_selector'
        return owner
    wrapper.load_isolated_package_module=same_owner
    os.environ['V4_SHARED_PACKAGE_ROOT']=str(shared);os.environ['V3_SHARED_DATA_STORE_ROOT']=str(STORE)
    from contextlib import redirect_stdout
    import io
    output=io.StringIO()
    try:
        if args.native_only:
            existing=owner.read_verified_v192_pool(STORE,target_date=target,expected_signal_date=args.day)
            if existing.run.manifest['provenance']['panel_sha256']!=actual['sha256']:raise ValueError('NATIVE_ONLY_SHARED_SOURCE_CONFLICT')
            code=0;outcome=dict(ok=True,status=existing.run.receipt['status'],already_exists=True,**existing.run.verification)
        else:
            with redirect_stdout(output):code=wrapper.main(argv)
            outcome=json.loads(output.getvalue())
        if code:raise ValueError('SHARED_SOURCE_RECOVERY_FAILED:'+str(outcome))
        native=publish_native()
        receipt=dict(at=datetime.now(timezone.utc).isoformat(),exit_code=code,outcome=outcome,
                     diagnostics=captured,native=native,**plan_ref)
        save(result_path,receipt)
        print(json.dumps(receipt,ensure_ascii=False,indent=2))
        raise SystemExit(code)
    except Exception as error:
        save(HERE/(args.day+'_RECOVERY_FAILURE.json'),dict(at=datetime.now(timezone.utc).isoformat(),
             error=repr(error),stdout=output.getvalue(),diagnostics=captured,**plan_ref))
        raise
if __name__=='__main__':main()
