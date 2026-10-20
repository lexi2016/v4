"""Prepare a full real pipeline in an isolated store; publish only after reviewed continuation.

No provider, HTTP, old-job retry, active scheduler, or production coordinator is used.
The live publication path uses only existing WorkbenchStore immutable/save contracts.
"""
from pathlib import Path
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import socket
import subprocess
import sys
import time
import types

sys.dont_write_bytecode=True
DOC=Path(__file__).resolve().parent
LOCAL=DOC/'local_only/runtime'
STAGE=LOCAL/'pipeline-store'
CANDIDATE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-date-top20-api-20261020-r1')
LIVE_STATE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench')
SOURCE_RUN='52d6d87a1fe547a484b189448d0ddfb7'
SOURCE_INPUT='3f281b06fc2723809a57a4b42a04dc727d9cb9bc99cc8bc8800f84676fcc87c2'
REPLAY=Path('/tmp/v4-us-mapping-wiring-candidate-final-20261020/input.local-only.json')
REPLAY_SHA='ad43cb7d0d963e9d3c9aaca8d5bc916daeb03c19f9a1c9094a9f5f71749879f4'
BATCH_SHA='6b1f625cd98fa024c87a35aede2dbb6442659f3267c38078e6e5546a1bd55943'
CANDIDATE_RECEIPT_SHA='145d40406e698859a43d7766da3c67ccf1a579a994567bda1cc6b6fa203bb105'
MANIFEST_SHA='7bfd33c541b5bb19724f313e8df7deae1877b5ca96379215f3ebd61e723049b8'
RESULT_RECEIPT=DOC/'RUNTIME_RESULT_PREPARED.json'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def now():return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
def raw_sha(raw):return hashlib.sha256(raw).hexdigest()
def optional_sha(path):return sha(path) if path.exists() else None
def no_network(*args,**kwargs):raise RuntimeError('NETWORK_FORBIDDEN_WIRING_REPROCESSING')

def frozen_code():
    assert sha(DOC/'RUNTIME_BACKEND_PREPARED.json')=='5877b60482ffa577a67fa089ce2c971eff7d29a2e344bde90219fb5da8ca1a8e'
    assert sha(DOC/'RUNTIME_CANDIDATE_PREPARED.json')==CANDIDATE_RECEIPT_SHA
    assert sha(CANDIDATE/'release-manifest.json')==MANIFEST_SHA
    accepted=json.loads((DOC/'RUNTIME_BACKEND_PREPARED.json').read_bytes())
    for rel, hashes in accepted['source_sha256'].items():
        assert sha(CANDIDATE/'app'/rel)==hashes['after']

def imports():
    sys.path[:0]=[str(CANDIDATE/'app'),str(CANDIDATE/'app/upstreams')]
    socket.create_connection=no_network
    socket.socket=no_network
    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import RunContext, InputBatch, Lane, JobState, PlanSnapshot, JobRecord, canonical
    from v4.manager_workbench.inputs.validation import batch
    from v4.manager_workbench.service import ManagerService, validate_selected_evidence
    from v4.manager_workbench.store import WorkbenchStore
    from v4.manager_workbench import engines
    return locals()

def prepare():
    frozen_code()
    assert not RESULT_RECEIPT.exists() and not STAGE.exists(), 'NO_REPEATED_PIPELINE_PREPARE'
    assert sha(REPLAY)==REPLAY_SHA
    accepted_raw=REPLAY.read_bytes()
    frozen_replay=LOCAL/'accepted-master-input.local-only.json'
    assert not frozen_replay.exists()
    frozen_replay.write_bytes(accepted_raw)
    accepted=json.loads(accepted_raw)
    original_context=copy.deepcopy(accepted['context'])
    assert accepted['batch']['context']==original_context
    assert accepted['batch']['input_sha256']==BATCH_SHA
    assert original_context['cutoff']=='2026-10-20T05:44:00.587402+08:00'
    assert original_context['source_sessions']==dict(us='20261019',hk_price='20261016')
    assert original_context['scope_refs']['requested_lanes']==['US_MAPPING']
    live=LIVE_STATE/'manager_workbench'
    old_snapshot=live/'snapshots'/(SOURCE_RUN+'.json')
    old_input=live/'input_snapshots'/(SOURCE_INPUT+'.json')
    assert sha(old_input)==SOURCE_INPUT
    old_snapshot_sha=sha(old_snapshot)
    pointer=live/'pointers/20261020/NEXT_DAY.json'
    old_pointer_raw=pointer.read_bytes() if pointer.exists() else None
    env=imports()
    RunContext,InputBatch,Lane,JobState=(env[k] for k in ['RunContext','InputBatch','Lane','JobState'])
    batch,real=env['batch'],env['engines']
    context=RunContext.model_validate(original_context)
    context.trigger='MANUAL'
    # Trigger/cutoff/run IDs are deliberately excluded by the existing batch identity.
    # Assert rather than assume that exact business identity is retained.
    prebatch=InputBatch.model_validate(accepted['batch']).model_copy(update={'context':context},deep=True)
    sealed=batch(context,Lane.US_MAPPING,prebatch.records,prebatch.evidence_refs,prebatch.scope_description,
                 prebatch.coverage,prebatch.gaps,prebatch.universe_ref)
    assert sealed.input_sha256==BATCH_SHA
    calls={'load_inputs':0,'run_lanes':0,'merge_decisions':0,'semantic_executor':0}
    def load_inputs(ctx,adapter):
        assert ctx.scope_refs['requested_lanes']==['US_MAPPING']
        calls['load_inputs']+=1
        value=sealed.model_copy(update={'context':ctx},deep=True)
        check=batch(ctx,Lane.US_MAPPING,value.records,value.evidence_refs,value.scope_description,
                    value.coverage,value.gaps,value.universe_ref)
        assert check.input_sha256==BATCH_SHA
        return {Lane.US_MAPPING:value}
    def run_lanes(ctx,inputs,executor):
        assert list(inputs)==['US_MAPPING'] and ctx.scope_refs['requested_lanes']==['US_MAPPING']
        calls['run_lanes']+=1
        return real.run_lanes(ctx,inputs,executor)
    def merge_decisions(ctx,lanes):
        assert len(lanes)==1 and lanes[0].lane==Lane.US_MAPPING
        calls['merge_decisions']+=1
        return real.merge_decisions(ctx,lanes)
    class BlockedSemanticExecutor:
        def execute(self,*args,**kwargs):
            calls['semantic_executor']+=1
            raise RuntimeError('SEMANTIC_EXECUTOR_NOT_AUTHORIZED')
    facade=types.SimpleNamespace(__name__='v4.manager_workbench.engines.wiring_frozen_pipeline',
        load_inputs=load_inputs,run_lanes=run_lanes,merge_decisions=merge_decisions)
    config_path=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-industry-observed-api-20261018-r1.json')
    assert sha(config_path)=='75c1efbd5a092b7945fc5baed98c64b37a7165ccf7eafc6abb9c1d540917c5db'
    config=env['load_config'](config_path).model_copy(update={'state_root':STAGE,'scheduled_lanes':None,'capture_enabled':False},deep=True)
    started=now()
    service=env['ManagerService'](config,object(),facade,BlockedSemanticExecutor())
    try:
        job=service.jobs.submit(context,service._work)
        deadline=time.monotonic()+120
        while True:
            job=service.jobs.get(job.job_id)
            if job.state not in (JobState.QUEUED,JobState.RUNNING):break
            assert time.monotonic()<deadline, 'PIPELINE_COMPLETION_PENDING_DO_NOT_DUPLICATE'
            time.sleep(.1)
        assert job.state in (JobState.SUCCEEDED,JobState.PARTIAL), job.model_dump(mode='json')
        snapshot=service.store.read_plan(job.run_id)
        env['validate_selected_evidence'](snapshot)
    finally:
        service.stop()
    assert calls==dict(load_inputs=1,run_lanes=1,merge_decisions=1,semantic_executor=0)
    assert len(snapshot.lanes)==1 and snapshot.lanes[0].lane==Lane.US_MAPPING
    assert snapshot.lanes[0].input_sha256==BATCH_SHA
    daily=next(r['us_factor_summary']['single_day_mapping'] for r in snapshot.lanes[0].rows if 'us_factor_summary' in r)
    assert len(daily['rows'])==len({r['symbol'] for r in daily['rows']})==698
    assert len(daily['catalog_relation_dispositions'])==len({r['catalog_relation_id'] for r in daily['catalog_relation_dispositions']})==1003
    assert daily['counts']==json.loads((DOC/'RUNTIME_BACKEND_PREPARED.json').read_bytes())['replay']['candidate_existing_master']['counts']
    assert daily['strict_v1_status']=='PAUSED_NOT_EXECUTED' and daily['formal_target_eligibility']=='CANNOT_CONFIRM'
    assert snapshot.RESEARCH_ONLY and not any([snapshot.production_allowed,snapshot.buy_gate_updated,snapshot.orders_sent])
    # Verify original live records and the pointer remain entirely untouched by preparation.
    assert sha(old_input)==SOURCE_INPUT and sha(old_snapshot)==old_snapshot_sha
    assert (pointer.read_bytes() if pointer.exists() else None)==old_pointer_raw
    stage=STAGE/'manager_workbench'
    input_sha=snapshot.changes['input_snapshot_sha256']
    input_path=stage/'input_snapshots'/(input_sha+'.json')
    body=json.loads(input_path.read_bytes())
    assert body['context']['trigger']=='MANUAL'
    assert body['context']['scope_refs']['owner_bindings']==original_context['scope_refs']['owner_bindings']
    assert body['batches'][0]['records']==accepted['batch']['records']
    assert body['batches'][0]['evidence_refs']==accepted['batch']['evidence_refs']
    assert len(body['batches'])==1 and body['batches'][0]['input_sha256']==BATCH_SHA
    for key in ['run_id','mwb_run_id']:
        assert body['context']['scope_refs'][key]==job.run_id
    checkpoints=sorted((stage/'checkpoints'/job.job_id).glob('*.json'))
    files=[input_path,stage/'snapshots'/(job.run_id+'.json'),stage/'attempts'/(job.job_id+'.json'),*checkpoints]
    output=dict(state='FULL_PIPELINE_PREPARED_NOT_PUBLISHED',mode='PROCESSING_RECOVERY',
        helper_sha256=sha(Path(__file__)),candidate_receipt_sha256=CANDIDATE_RECEIPT_SHA,candidate_manifest_sha256=MANIFEST_SHA,
        source_prepared_sha256=sha(DOC/'RUNTIME_BACKEND_PREPARED.json'),source_run_id=SOURCE_RUN,source_snapshot_sha256=old_snapshot_sha,
        source_input_snapshot_sha256=SOURCE_INPUT,accepted_master_input_raw_sha256=REPLAY_SHA,
        new_run_id=job.run_id,new_job_id=job.job_id,new_job_state=job.state.value,
        lane_input_batch_sha256=BATCH_SHA,full_input_snapshot_sha256=input_sha,
        aggregate_plan_input_sha256=snapshot.input_sha256,product_sha256=snapshot.product_sha256,
        old_trigger=original_context['trigger'],new_trigger='MANUAL',phase='NEXT_DAY',source_cutoff=original_context['cutoff'],
        processing_started_at=started,processing_finished_at=now(),snapshot_cutoff=snapshot.context.cutoff,
        snapshot_generated_at=snapshot.generated_at,target_date='20261020',us_session='20261019',hk_price_session='20261016',
        context_delta=['trigger SCHEDULED -> MANUAL','scope_refs.run_id/mwb_run_id -> unique new execution IDs',
            'snapshot.cutoff advances at existing pipeline merge; source_cutoff retained; generated_at is actual processing time'],
        business_input_delta='Only reviewed HK16 master owner/identity/evidence, already sealed in accepted batch. Quotes and all original pins unchanged.',
        owner_bindings_unchanged_from_accepted_master_input=True,records_and_evidence_unchanged=True,
        pipeline_calls=calls,pipeline_files=[dict(path=str(p.relative_to(DOC)),sha256=sha(p),bytes=p.stat().st_size) for p in files],
        old_pointer_sha256=raw_sha(old_pointer_raw) if old_pointer_raw is not None else None,
        old_pointer_value=json.loads(old_pointer_raw) if old_pointer_raw else None,
        daily_counts=daily['counts'],monthly_stocks=698,catalog_relations=1003,strict='PAUSED_NOT_EXECUTED',
        safety=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False),
        provider_calls=0,business_posts=0,other_lane_executions=0,live_state_writes=0,publication='NOT_RUN',
        natural_verification='NOT_RUN',scheduler='PENDING_PARENT_DRIFT_NOT_DEPLOYED')
    RESULT_RECEIPT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:output[k] for k in ['state','new_run_id','lane_input_batch_sha256','full_input_snapshot_sha256','product_sha256','daily_counts']},ensure_ascii=False))
    print('result_receipt_sha256='+sha(RESULT_RECEIPT))

def verify(prepared_sha):
    assert prepared_sha and sha(RESULT_RECEIPT)==prepared_sha, 'RESULT_RECEIPT_NOT_BOUND_TO_REVIEWED_RAW_SHA'
    frozen_code()
    receipt=json.loads(RESULT_RECEIPT.read_bytes())
    assert receipt['helper_sha256']==sha(Path(__file__))
    assert receipt['candidate_receipt_sha256']==CANDIDATE_RECEIPT_SHA
    assert receipt['candidate_manifest_sha256']==MANIFEST_SHA
    assert receipt['lane_input_batch_sha256']==BATCH_SHA
    assert receipt['source_input_snapshot_sha256']==SOURCE_INPUT
    assert receipt['new_run_id']==receipt['new_job_id'] and receipt['new_run_id']!=SOURCE_RUN
    for item in receipt['pipeline_files']:
        p=DOC/item['path']
        assert p.resolve().is_relative_to(STAGE.resolve())
        assert sha(p)==item['sha256']
    env=imports()
    stage=STAGE/'manager_workbench'
    snap=env['PlanSnapshot'].model_validate(json.loads((stage/'snapshots'/(receipt['new_run_id']+'.json')).read_bytes()))
    job=env['JobRecord'].model_validate(json.loads((stage/'attempts'/(receipt['new_job_id']+'.json')).read_bytes()))
    assert snap.product_sha256==receipt['product_sha256'] and snap.input_sha256==receipt['aggregate_plan_input_sha256']
    assert snap.changes['input_snapshot_sha256']==receipt['full_input_snapshot_sha256']
    env['validate_selected_evidence'](snap)
    return receipt,env,snap,job

def publish(prepared_sha,do_publish):
    receipt,env,snap,job=verify(prepared_sha)
    live=LIVE_STATE/'manager_workbench'
    pointer=live/'pointers/20261020/NEXT_DAY.json'
    expected=receipt['old_pointer_sha256']
    expected_new=dict(run_id=snap.run_id,product_sha256=snap.product_sha256,generated_at=snap.generated_at)
    expected_new_sha=raw_sha(env['canonical'](expected_new))
    assert expected_new_sha=='985b91b19eaaf878f87295f02d8f191d2aaf4bcc2150911522a5e2a68823a248', 'FROZEN_NEW_POINTER_IDENTITY_MISMATCH'
    live_snapshot=live/'snapshots'/(snap.run_id+'.json')
    if live_snapshot.exists():
        existing=env['PlanSnapshot'].model_validate(json.loads(live_snapshot.read_bytes()))
        assert existing.product_sha256==snap.product_sha256, 'NEW_RUN_COLLISION'
        assert optional_sha(pointer)==expected_new_sha, 'PARTIAL_OR_TAMPERED_PUBLICATION_REQUIRES_OWNER_INSPECTION'
        print(json.dumps(dict(state='ALREADY_PUBLISHED_EXACT_NO_REPEAT',run_id=snap.run_id)))
        return
    assert optional_sha(pointer)==expected, 'LIVE_POINTER_DRIFT_NO_PUBLICATION'
    assert not (live/'attempts'/(receipt['new_job_id']+'.json')).exists(), 'NEW_JOB_ALREADY_EXISTS_INSPECT_NO_REPEAT'
    assert not (live/'checkpoints'/receipt['new_job_id']).exists(), 'NEW_CHECKPOINTS_ALREADY_EXIST_INSPECT_NO_REPEAT'
    assert sha(live/'input_snapshots'/(SOURCE_INPUT+'.json'))==SOURCE_INPUT
    assert sha(live/'snapshots'/(SOURCE_RUN+'.json'))==receipt['source_snapshot_sha256']
    if not do_publish:
        print(json.dumps(dict(state='CHECK_ONLY_READY_NO_LIVE_WRITES',run_id=snap.run_id)))
        return
    # Publication follows successful deployment, never merely prepared candidate bytes.
    active_plist=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
    assert sha(active_plist)=='fdc3e9536b892952fa404658e00fd6042c162f82df8302bbc1a6fe928db2f752', 'API_NOT_DEPLOYED_EXACT_PROPOSAL'
    active=plistlib.loads(active_plist.read_bytes())
    assert active['WorkingDirectory']==str(CANDIDATE/'app')
    launch=subprocess.run(['/bin/launchctl','print','gui/501/com.lexi.v35.api-only'],capture_output=True,text=True,timeout=10)
    assert launch.returncode==0 and '\tworking directory = '+str(CANDIDATE/'app')+'\n' in launch.stdout, 'API_RUNNING_IDENTITY_MISMATCH'
    assert re.search(r'^\s*state = running\s*$',launch.stdout,re.M), 'API_NOT_RUNNING'
    pid_match=re.search(r'^\s*pid = ([1-9][0-9]*)\s*$',launch.stdout,re.M)
    assert pid_match, 'API_RUNNING_PID_REQUIRED'
    cwd=subprocess.run(['/usr/sbin/lsof','-a','-p',pid_match.group(1),'-d','cwd','-Fn'],capture_output=True,text=True,timeout=10)
    assert cwd.returncode==0 and '\nn'+str(CANDIDATE/'app')+'\n' in '\n'+cwd.stdout, 'API_RUNNING_PID_CWD_MISMATCH'
    # Actual publication is forbidden until independent PASS plus controller continuation.
    # This wrapper guards the existing commit_plan pointer write under its own kernel lock.
    class PointerGuardStore(env['WorkbenchStore']):
        def _write(self,path,obj,*,immutable,collision_read_limit=64*1024*1024):
            if path==pointer:
                assert optional_sha(path)==expected, 'POINTER_DRIFT_INSIDE_EXISTING_PUBLISH_LOCK'
            return super()._write(path,obj,immutable=immutable,collision_read_limit=collision_read_limit)
    store=PointerGuardStore(LIVE_STATE)  # No JobCoordinator, orphan recovery or live executor.
    stage=STAGE/'manager_workbench'
    input_path=stage/'input_snapshots'/(receipt['full_input_snapshot_sha256']+'.json')
    store.save_input(receipt['full_input_snapshot_sha256'],json.loads(input_path.read_bytes()))
    for p in sorted((stage/'checkpoints'/job.job_id).glob('*.json')):
        store.save_checkpoint(job.job_id,p.stem,json.loads(p.read_bytes()))
    store.save_job(job)
    saved=store.commit_plan(snap)
    assert saved.product_sha256==receipt['product_sha256']
    assert sha(pointer)==expected_new_sha, 'PUBLISHED_POINTER_READBACK_MISMATCH'
    result=dict(state='PUBLISHED_PROCESSING_RECOVERY',at=now(),run_id=saved.run_id,
        product_sha256=saved.product_sha256,prepared_receipt_sha256=prepared_sha,
        actual_pointer_sha256=sha(pointer),provider_calls=0,business_posts=0,natural_verification='NOT_RUN')
    out=DOC/'RUNTIME_PUBLICATION_RECEIPT.json'
    assert not out.exists()
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

def rollback(prepared_sha):
    receipt,env,snap,job=verify(prepared_sha)
    publication=DOC/'RUNTIME_PUBLICATION_RECEIPT.json'
    result=json.loads(publication.read_bytes())
    assert result['prepared_receipt_sha256']==prepared_sha and result['run_id']==snap.run_id
    live=LIVE_STATE/'manager_workbench'
    pointer=live/'pointers/20261020/NEXT_DAY.json'
    expected_new=dict(run_id=snap.run_id,product_sha256=snap.product_sha256,generated_at=snap.generated_at)
    expected_new_sha=raw_sha(env['canonical'](expected_new))
    assert expected_new_sha=='985b91b19eaaf878f87295f02d8f191d2aaf4bcc2150911522a5e2a68823a248', 'FROZEN_NEW_POINTER_IDENTITY_MISMATCH'
    assert result['product_sha256']==snap.product_sha256, 'ROLLBACK_RECEIPT_PRODUCT_MISMATCH'
    assert result['actual_pointer_sha256']==expected_new_sha, 'ROLLBACK_RECEIPT_POINTER_MISMATCH'
    assert optional_sha(pointer)==expected_new_sha, 'ROLLBACK_POINTER_DRIFT'
    old_id=receipt['old_pointer_value']['run_id']
    old_path=live/'snapshots'/(old_id+'.json')
    old=env['PlanSnapshot'].model_validate(json.loads(old_path.read_bytes()))
    assert old.product_sha256==receipt['old_pointer_value']['product_sha256']
    class RollbackGuardStore(env['WorkbenchStore']):
        def _write(self,path,obj,*,immutable,collision_read_limit=64*1024*1024):
            if path==pointer:
                assert optional_sha(path)==expected_new_sha, 'ROLLBACK_POINTER_DRIFT_INSIDE_LOCK'
            return super()._write(path,obj,immutable=immutable,collision_read_limit=collision_read_limit)
    restored=RollbackGuardStore(LIVE_STATE).commit_plan(old)
    assert restored.run_id==old_id and sha(pointer)==receipt['old_pointer_sha256']
    out=DOC/'RUNTIME_PUBLICATION_ROLLBACK_RECEIPT.json'
    assert not out.exists()
    payload=dict(state='POINTER_RESTORED_HISTORY_RETAINED',at=now(),run_id=restored.run_id,
                 retained_reprocessing_run=snap.run_id,pointer_sha256=sha(pointer))
    out.write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps(payload))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true')
    mode.add_argument('--check-only',action='store_true')
    mode.add_argument('--publish',action='store_true')
    mode.add_argument('--rollback',action='store_true')
    parser.add_argument('--prepared-sha256')
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.rollback:rollback(args.prepared_sha256)
    else:publish(args.prepared_sha256,args.publish)
