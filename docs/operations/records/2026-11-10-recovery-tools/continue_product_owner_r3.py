"""Reviewed one-off continuation of original D10 product/derivative owners.

No raw capture or formula entry is imported or invoked. --check-only validates
frozen READY inputs without calling any producer or writing business receipts.
"""
from pathlib import Path
import argparse
import datetime
import errno
import fcntl
import hashlib
import json
import os
import plistlib
import sys
from zoneinfo import ZoneInfo

BASE=Path('/Users/lexi/Desktop/学习/agents调试/v4_daily_storage_recovery_20261110')
PLAN=BASE/'PRODUCT_OWNER_R3_CALL.json'
REVIEW=BASE/'INDEPENDENT_REVIEW_BUDGET_R3.json'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def checked_json(ref):
    path=Path(ref['path'])
    if path.is_symlink() or path.resolve()!=path or digest(path)!=ref['sha256']:
        raise RuntimeError('FROZEN_INPUT_CHANGED:'+str(path))
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_inputs(plan):
    import pyarrow.parquet as pq
    from ops.research_storage_pair import META
    formula=checked_json(plan['formula_result'])
    stage=checked_json(plan['stage_status'])
    producer=checked_json(plan['candidate_receipt'])
    current=checked_json(plan['paired_current'])
    manifest=checked_json(plan['paired_manifest'])
    sync=checked_json(plan['source_receipt'])
    accepted=checked_json(plan['accepted_input_manifest'])
    if formula.get('status')!='READY' or stage.get('status')!='READY':
        raise RuntimeError('EXISTING_FORMULA_NOT_READY')
    if str(formula.get('target_date'))!='20261110' or str(sync.get('target_date'))!='20261110':
        raise RuntimeError('ORIGINAL_SOURCE_DATE_CHANGED')
    if sync.get('status')!='READY' or sync.get('formula_input_mode')!='ACCEPTED_ONLY':
        raise RuntimeError('RAW_AUTHORITY_NOT_READY_ACCEPTED_ONLY')
    if str(accepted.get('target_date'))!='20261110' or len(accepted.get('files',[]))!=5533:
        raise RuntimeError('ACCEPTED_SCOPE_CHANGED')
    if current['current'] != plan['paired_manifest'] or manifest['id']!=plan['paired_id']:
        raise RuntimeError('PAIRED_CURRENT_CHANGED')
    for key,value in plan['formula_identity'].items():
        if formula.get(key)!=value or stage.get(key)!=value:
            raise RuntimeError('FORMULA_STAGE_IDENTITY_CHANGED:'+key)
    for key in ('generation_id','input_sha256','snapshot_file_sha256','asof_date'):
        if manifest['identity'].get(key)!=formula.get(key):
            raise RuntimeError('PAIRED_INPUT_IDENTITY_CHANGED:'+key)
    data=Path(os.environ['V4_RESEARCH_PANEL_A_DATA_ROOT'])
    pointers={'selector':Path(os.environ['V4_RESEARCH_PANEL_A_SELECTOR_POINTER']),
              'backtest':Path(os.environ['V4_RESEARCH_PANEL_A_BACKTEST_POINTER'])}
    for role,record in manifest['roles'].items():
        path=Path(record['path']);st=path.stat()
        stat=dict(size=st.st_size,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns,device=st.st_dev,inode=st.st_ino)
        if stat!=record['stat'] or pointers[role].read_text().strip()!=str(path):
            raise RuntimeError('CURRENT_PANEL_STAT_OR_POINTER_CHANGED:'+role)
        if (str(path)!=formula['candidates'][role] or record['sha256']!=formula['candidate_sha256'][role]
                or producer['candidate_sha256'][role]!=record['sha256']):
            raise RuntimeError('PAIRED_RECORDED_SHA_CHANGED:'+role)
        contract=json.loads(pq.read_schema(path).metadata[META])
        for key in ('generation_id','input_sha256','snapshot_file_sha256','asof_date'):
            if contract.get(key)!=formula.get(key):raise RuntimeError('PANEL_FOOTER_IDENTITY_CHANGED:'+role+':'+key)
    for source in (formula,sync,accepted):
        for key in ('production_allowed','buy_gate_updated','orders_sent'):
            if source.get(key) is not False:raise RuntimeError('RESEARCH_SAFETY_CHANGED:'+key)
    return sync,formula,data


def release_lane_for_original_derivatives(lane):
    fd=lane.fileno();held=os.fstat(fd)
    fcntl.flock(lane,fcntl.LOCK_UN)
    lane.close()
    try:os.fstat(fd)
    except OSError as error:
        if error.errno!=errno.EBADF:raise
    else:raise RuntimeError('MANUAL_LANE_FD_STILL_OPEN')
    return dict(released_fd=fd,fd_closed=True,device=held.st_dev,inode=held.st_ino,
        manual_a_long_held=False,derivative_lock_owner='ORIGINAL_PUBLISHERS')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
    plan=json.loads(PLAN.read_text())
    plist_path=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist')
    plist=plistlib.loads(plist_path.read_bytes());env=plist['EnvironmentVariables']
    expected_python=str(Path(env['V4_RUNTIME_ROOT'])/'venvs/v4-mac/bin/python')
    if sys.executable!=expected_python or os.getcwd()!=plist['WorkingDirectory']:
        raise RuntimeError('ORIGINAL_MAIN_EXECUTION_IDENTITY_CHANGED')
    if env['V4_APP_ROOT']!=plan['main_app_root'] or env['V4_RELEASE_MANIFEST_SHA256']!=plan['main_manifest']['sha256']:
        raise RuntimeError('ORIGINAL_MAIN_RELEASE_CHANGED')
    checked_json(plan['main_manifest'])
    for key,value in env.items():
        if os.environ.get(key)!=value:raise RuntimeError('MAIN_ENVIRONMENT_NOT_INHERITED:'+key)
    if any(os.environ.get(key) is not None for key in ('V4_SCHEDULER_LANE_FD','V4_SCHEDULER_LANE_NAME','V4_SCHEDULER_RESOLVED_DATE','V4_SCHEDULER_RESOLVED_SLOT')):
        raise RuntimeError('MANUAL_RECOVERY_MUST_NOT_INHERIT_SCHEDULED_SLOT_METADATA')
    policy=checked_json(dict(path=env['V4_RESEARCH_RETENTION_POLICY'],sha256=env['V4_RESEARCH_RETENTION_POLICY_SHA256']))
    if not args.check_only:
        review=json.loads(REVIEW.read_text())
        if (review.get('verdict') not in {'PASS','REVIEWED/PASS'}
                or review.get('packet_sha256')!=plan['packet']['sha256']
                or review.get('continuation_sha256')!=digest(PLAN)
                or review.get('continuation_script_sha256')!=digest(__file__)):
            raise RuntimeError('INDEPENDENT_REVIEW_BINDING_REQUIRED')
        checked_json(plan['packet'])
        if (env['V4_RESEARCH_RETENTION_POLICY']!=plan['policy']['path']
                or env['V4_RESEARCH_RETENTION_POLICY_SHA256']!=plan['policy']['sha256']
                or policy['governance']['ordinary_peak_budget_bytes']!=261*1024**3):
            raise RuntimeError('REVIEWED_R3_POLICY_NOT_ACTIVE')
    # This script lives in process evidence; bind imports to the original Main
    # app rather than the script directory or a legacy PYTHONPATH segment.
    sys.path.insert(0,env['V4_APP_ROOT'])
    lane_path=Path(plan['lane_lock'])
    with lane_path.open('a+') as lane:
        fcntl.flock(lane,fcntl.LOCK_EX|fcntl.LOCK_NB)
        sync,formula,data_root=validate_inputs(plan)
        if args.check_only:
            print(json.dumps(dict(status='CHECKED_INPUTS_ONLY_NO_PRODUCER',generation_id=formula['generation_id'],raw_capture_repeated=False,formula_recomputed=False)))
            return 0
        state=dict(classification='MANUAL_RECOVERY_NOT_NATURAL_OR_PIT',pid=os.getpid(),
            raw_capture_repeated=False,formula_recomputed=False,history=[],source_date='20261110')
        def checkpoint(phase,**values):
            state.update(phase=phase,**values)
            state['history'].append(dict(phase=phase,at=datetime.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()))
            pending=BASE/'RECOVERY_R3_RUN.json.pending';pending.write_text(json.dumps(state,ensure_ascii=False,indent=2,default=str));pending.replace(BASE/'RECOVERY_R3_RUN.json')
            print(json.dumps(dict(phase=phase,**values),ensure_ascii=False,default=str),flush=True)
        def save(name,value):(BASE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str))
        try:
            from ops.macos_research_panel_daily_receipts import build_a_lane_outcome
            from ops.macos_research_panel_daily_gate import run_scheduled_lanes
            from ops.research_panel_daily_product import materialize_daily_product
            from ops.research_storage_governance import governed_product
            from ops.research_panel_top200 import complete_daily_derivatives
            product_root=Path(os.environ['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share'
            receipt_root=Path(os.environ['V4_RESEARCH_PANEL_RECEIPT_ROOT'])
            product=None
            def original_a_continuation(target):
                nonlocal product
                if target!='20261110':raise RuntimeError('DATE_CHANGED')
                checkpoint('ORIGINAL_DAILY_MATERIALIZER_RUNNING')
                try:product=governed_product(materialize_daily_product,data_root=data_root,target=20261110,formula_result=formula,output_root=product_root)
                except Exception as error:product=dict(status='CANNOT_CONFIRM',data_date=target,reason=type(error).__name__+':'+str(error))
                save('RECOVERY_R3_PRODUCT_RESULT.json',product)
                checkpoint('ORIGINAL_DAILY_MATERIALIZER_RETURNED',product_status=product.get('status'),product_reason=product.get('reason'))
                outcome=build_a_lane_outcome(sync,formula,target,None);outcome['daily_product']=product
                return outcome
            def no_hk(target):raise RuntimeError('HK_NOT_AUTHORIZED')
            result=run_scheduled_lanes(target_date='20261110',receipt_root=receipt_root,a_runner=original_a_continuation,hk_runner=no_hk,lane='A')
            save('RECOVERY_R3_LANE_RESULT.json',result)
            lane_result=result.get('lanes',{}).get('A',{})
            checkpoint('ORIGINAL_A_RECEIPT_WRITTEN',lane_status=lane_result.get('status'))
            if lane_result.get('status') not in {'READY','PARTIAL','PARTIAL_WITH_ROWS'}:
                checkpoint('STOPPED_ORIGINAL_RECEIPT_FAILURE',status='FAILED');return 1
            if not product or product.get('status') not in {'READY','PARTIAL_WITH_ROWS'} or product.get('processed_count',0)<=0:
                checkpoint('STOPPED_PRODUCT_MISSING_OR_FAILED',status='FAILED');return 1
            manifest=checked_json(product['manifest']);artifact=checked_json(product['artifact'])
            if (manifest['source_generation']!=formula['generation_id'] or artifact['source_generation']!=formula['generation_id']
                    or str(manifest['data_date'])!='20261110' or str(artifact['data_date'])!='20261110'):
                raise RuntimeError('PRODUCT_PUBLICATION_IDENTITY_MISMATCH')
            checkpoint('A_LONG_HANDOFF_BEGIN',held_fd=lane.fileno(),manual_a_long_held=True)
            handoff=release_lane_for_original_derivatives(lane)
            checkpoint('A_LONG_RELEASED_AND_FD_CLOSED',**handoff)
            # Original derivative publishers acquire A_LONG themselves. Holding
            # this manual FD would deadlock their new open description; never
            # fabricate a scheduled slot/FD to bypass that original contract.
            validate_inputs(plan)
            checked_json(product['manifest']);checked_json(product['artifact'])
            checkpoint('ORIGINAL_DERIVATIVES_RUNNING',manual_a_long_held=False)
            from ops.research_storage_pair import request_binding
            with request_binding(data_root) as binding:
                identity=binding.manifest['identity']
                if any(identity.get(key)!=formula[key] for key in ('generation_id','input_sha256','snapshot_file_sha256','asof_date')):
                    raise RuntimeError('DERIVATIVE_PAIR_IDENTITY_CHANGED_AT_BINDING')
                derivatives=governed_product(complete_daily_derivatives,data_root,20261110,product_root,receipt_root,Path(os.environ['V4_WORKBENCH_CLASSIFICATION_ROOT']))
            save('RECOVERY_R3_DERIVATIVES_RESULT.json',derivatives)
            checkpoint('ORIGINAL_DERIVATIVES_RETURNED',derivatives_status=derivatives.get('status'),derivatives_reason=derivatives.get('reason'),derivatives_error=derivatives.get('error'))
            checkpoint('OWNER_CONTINUATION_RETURNED',status='REQUIRES_ARTIFACT_API_UI_ACCEPTANCE',source_status=lane_result.get('status'),product_status=product['status'],derivatives_status=derivatives.get('status'))
            return 0 if derivatives.get('status')=='COMPLETE_DESCRIPTIVE_NONPIT' else 1
        except BaseException as error:
            checkpoint('STOPPED_NEW_FAILURE',status='FAILED',error=type(error).__name__+':'+str(error));raise


if __name__=='__main__':raise SystemExit(main())
