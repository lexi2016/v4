"""Frozen dated US_MAPPING -> new manual RETROSPECTIVE immutable result only.

No JobCoordinator, source adapter, capture, model executor or business POST.
Preparation writes isolated state; publication/rollback require a separate
hash-bound continuation capsule and the existing store publication lock.
"""
from __future__ import annotations
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from activate_release import actual_store_root

from prepare_release import (WORKTREE, REHEARSAL_BASE, Stop, authorize, child,
    digest, exact, json_bytes, python_pin, read_json, require, sha, write_new)

SOURCE_RUN='173530a9ac4b4105b41094337907b801'
SOURCE_INPUT='b80a8bc475f6aeb8976c706674ad4791c803720eb2e3134c09ad55a784c61b37'
SOURCE_BATCH='5b37816a699a7dab7ab4a76e504fd5146831b76cbb31eb6d436fc37d724ff064'
SOURCE_CUTOFF='2026-10-21T20:15:04Z'
EXECUTION_CUTOFF='2026-10-22T04:17:00.341182+08:00'
LIVE_STATE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench')
API_PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
API_CONFIG=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-industry-observed-api-20261018-r1.json')
API_CONFIG_SHA='75c1efbd5a092b7945fc5baed98c64b37a7165ccf7eafc6abb9c1d540917c5db'
HELPER=Path(__file__).resolve()


def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def optional_sha(path):return sha(path) if path.exists() else None


@contextmanager
def no_external_execution():
    def denied(*a,**k):raise Stop('NETWORK_CAPTURE_OR_PROCESS_EXECUTION_FORBIDDEN')
    saved=[]
    for obj,key in [(socket,'create_connection'),(subprocess,'Popen')]+[(socket.socket,key) for key in
            ('connect','connect_ex','bind','listen','send','sendall','sendto')]:
        saved.append((obj,key,getattr(obj,key)));setattr(obj,key,denied)
    try:yield
    finally:
        for obj,key,value in saved:setattr(obj,key,value)


def live_store_root(scope):
    """Exact API config argument plus the pinned existing Store constructor."""
    if scope['mode']!='RELEASE':return exact(Path(scope['live_state_root'])/'manager_workbench',exists=False)
    pin=scope['active_api'];plist=exact(pin['plist'])
    require(plist==API_PLIST and sha(plist)==pin['plist_sha256'],'PUBLICATION_API_PLIST_DRIFT')
    binding=plistlib.loads(plist.read_bytes());require(binding['WorkingDirectory']==pin['app_root'],'PUBLICATION_API_ROOT_MISMATCH')
    config_pin=pin.get('config')
    require(isinstance(config_pin,dict) and config_pin.get('path')==str(API_CONFIG) and
            config_pin.get('sha256')==API_CONFIG_SHA,'PUBLICATION_CONFIG_PIN_REQUIRED')
    config=read_json(config_pin['path'],config_pin['sha256'])
    key='V4_MANAGER_WORKBENCH_CONFIG_PATH'
    refs=([binding.get('EnvironmentVariables',{})[key]] if key in binding.get('EnvironmentVariables',{}) else [])
    refs += [arg.split('=',1)[1] for arg in binding.get('ProgramArguments',[]) if isinstance(arg,str) and arg.startswith(key+'=')]
    require(refs and all(value==config_pin['path'] for value in refs),'PUBLICATION_API_CONFIG_BINDING_DRIFT')
    require(config.get('state_root')==scope['live_state_root']==str(LIVE_STATE),'PUBLICATION_CONFIG_STATE_ROOT_MISMATCH')
    relative='v4/manager_workbench/store.py';expected=scope['source_files'].get(relative)
    require(expected and scope['deployed_files'].get(relative)==expected and
            sha(child(pin['app_root'],relative))==expected,'PUBLICATION_STORE_SOURCE_DRIFT')
    return actual_store_root(pin['app_root'],exact(config['state_root']))


def frozen_source_row(scope,inventory):
    rows=[row for row in inventory['runs'] if row['run_id']==scope['source_run_id']]
    require(len(rows)==1,'SOURCE_RUN_INPUT_MISMATCH');row=rows[0]
    require(row.get('input_snapshot_sha256')==scope['source_input']['sha256'],'SOURCE_RUN_INPUT_MISMATCH')
    require(row.get('target_date')==scope['target_date'] and row.get('phase')=='NEXT_DAY' and
            row['snapshot']['path']==scope['source_snapshot']['path'] and
            row['snapshot']['sha256']==scope['source_snapshot']['sha256'] and
            inventory['inputs'][row['input_snapshot_sha256']]['path']==scope['source_input']['path'],
            'FROZEN_SOURCE_REFERENCE_MISMATCH')
    if scope['schema'].endswith('.v2'):
        context=row.get('input_context',{});session=scope.get('source_us_session')
        require(digest(canonical(row))==scope.get('source_row_sha256') and
                row.get('exact_saved_input_replayable') is True and
                row.get('us_batch_input_sha256')==scope['source_batch_sha256'] and
                context.get('market')=='HK_CONNECT' and context.get('target_date')==scope['target_date'] and
                context.get('phase')=='NEXT_DAY' and context.get('cutoff')==scope['source_execution_cutoff'] and
                context.get('source_cutoff')==scope['source_cutoff'], 'FROZEN_DATED_ROW_MISMATCH')
        require(isinstance(session,str) and re.fullmatch(r'[0-9]{8}',session) and session<scope['target_date'] and
                context.get('source_sessions',{}).get('us')==session and
                context.get('us_session_date',session)==session and
                context.get('us_mapping_scope',{}).get('source_session',session)==session and
                context.get('run_contract',{}).get('us_source_session',session)==session,
                'FROZEN_SOURCE_SESSION_MISMATCH')
    return row


def scope_load(path,expected,action,continuation=None):
    scope=read_json(path,expected)
    require(scope.get('schema') in ('v4.us_hk.replay_publication_scope.v1','v4.us_hk.replay_publication_scope.v2') and scope.get('state')=='READY','PUBLICATION_SCOPE_NOT_READY')
    require(scope.get('mode') in ('REHEARSAL','RELEASE') and
            isinstance(scope.get('target_date'),str) and re.fullmatch(r'[0-9]{8}',scope['target_date']) and
            isinstance(scope.get('source_run_id'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',scope['source_run_id']) and
            scope.get('phase')=='RETROSPECTIVE' and
            scope.get('trigger')=='MANUAL' and scope.get('data_pointer_changes')==[] and
            scope.get('result_pointer_relative')==f"pointers/{scope['target_date']}/RETROSPECTIVE.json", 'PUBLICATION_BOUNDARY_INVALID')
    if scope['schema'].endswith('.v1'):
        require(scope['source_run_id']==SOURCE_RUN and scope['target_date']=='20261022','PUBLICATION_BOUNDARY_INVALID')
        require(scope['source_cutoff']==SOURCE_CUTOFF and scope['source_execution_cutoff']==EXECUTION_CUTOFF,'ORIGINAL_CUTOFF_MISMATCH')
    require(scope.get('safety')==dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False), 'SAFETY_BOUNDARY_INVALID')
    evidence=exact(scope['evidence_root']);stage=exact(scope['stage_root'],exists=False)
    require(stage.is_relative_to(evidence) and stage!=evidence,'STAGE_OUTSIDE_EVIDENCE')
    if scope['mode']=='RELEASE':
        require(exact(scope['source_root'])==exact(WORKTREE),'PUBLICATION_ROOT_OUTSIDE_GRANT')
        live_store_root(scope)
        require(evidence.is_relative_to(exact(REHEARSAL_BASE)),'PUBLICATION_EVIDENCE_OUTSIDE_GRANT')
        checked=dict(scope,execution_capsule=continuation or scope.get('execution_capsule'))
        capsule=authorize(checked,action)
        require(capsule.get('helper_sha256',{}).get('publish_replay.py')==sha(HELPER),'UNREVIEWED_PUBLICATION_HELPER')
        if scope['schema'].endswith('.v1'):
            require(scope['source_input']['sha256']==SOURCE_INPUT and scope['source_batch_sha256']==SOURCE_BATCH,'NOT_FROZEN22_REAL_INPUT')
    else:
        boundary=exact(scope['rehearsal_root'])
        require(boundary.name.startswith('rehearsal-') and boundary.is_relative_to(exact(REHEARSAL_BASE)),'REHEARSAL_BOUNDARY_INVALID')
        for root in (evidence,stage,exact(scope['live_state_root']),exact(scope['source_root'])):
            require(root.is_relative_to(boundary) and root!=boundary,'REHEARSAL_PATH_ESCAPE')
    for key in ('source_input','source_snapshot','inventory'):
        read_json(scope[key]['path'],scope[key]['sha256'])
    if scope['schema'].endswith('.v2'):
        frozen_source_row(scope,read_json(scope['inventory']['path'],scope['inventory']['sha256']))
    for rel,expected_sha in scope['source_files'].items():
        require(sha(child(scope['source_root'],rel))==expected_sha,'REPLAY_SOURCE_DRIFT')
    return scope


def load_backend(scope):
    runtime=scope['runtime'];python_pin(runtime['python'])
    require(Path(sys.executable).resolve()==Path(runtime['python']['resolved_path']), 'RUN_WITH_EXACT_ROLE_INTERPRETER')
    require('.'.join(str(v) for v in sys.version_info[:3])==runtime['python']['version'],'ROLE_PYTHON_VERSION_DRIFT')
    root=Path(scope['source_root']);sys.dont_write_bytecode=True
    sys.path[:0]=[str(root),str(root/'upstreams'),str(root/'upstreams/v3_shared_data'),*[str(exact(p)) for p in runtime['site_packages']]]
    from v4.manager_workbench import contracts as c, engines
    from v4.manager_workbench import service
    from v4.manager_workbench.store import WorkbenchStore
    from v4.manager_workbench import us_mapping_replay as replay
    for name in ('contracts','engines','service','store','us_mapping_replay'):
        module=importlib.import_module('v4.manager_workbench.'+name)
        require(Path(module.__file__).resolve().is_relative_to(root),'WRONG_REPLAY_MODULE_ORIGIN')
    require(set(replay.ENGINE_FILES+replay.REPLAY_FILES)|{'v4/manager_workbench/store.py','v4/manager_workbench/service.py'} <= set(scope['source_files']), 'REPLAY_SOURCE_CLOSURE_INCOMPLETE')
    return SimpleNamespace(c=c,engines=engines,service=service,Store=WorkbenchStore,replay=replay)


def protected(scope):
    return {scope[k]['path']:sha(scope[k]['path']) for k in ('source_input','source_snapshot')}


def unchanged(before):
    require(all(sha(p)==value for p,value in before.items()),'ORIGINAL_INPUT_OR_SNAPSHOT_CHANGED')


def active_api(scope,runner=None):
    if scope['mode']!='RELEASE':return
    live_store_root(scope)
    runner=runner or subprocess.run;pin=scope['active_api']
    plist=exact(pin['plist']);require(plist==API_PLIST and sha(plist)==pin['plist_sha256'],'PUBLICATION_API_PLIST_DRIFT')
    data=plistlib.loads(plist.read_bytes());require(data['WorkingDirectory']==pin['app_root'],'PUBLICATION_API_ROOT_MISMATCH')
    require(sha(exact(pin['manifest']))==pin['manifest_sha256'],'PUBLICATION_API_MANIFEST_DRIFT')
    for rel,expected in scope['deployed_files'].items():
        require(expected==scope['source_files'].get(rel) and sha(child(pin['app_root'],rel))==expected,'PUBLICATION_ENGINE_NOT_DEPLOYED')
    require({'v4/manager_workbench/engines/us_mapping.py','v4/manager_workbench/engines/strict_us_selection.py',
             'v4/manager_workbench/contracts.py','v4/manager_workbench/store.py'}<=set(scope['deployed_files']),'DEPLOYED_ENGINE_COVERAGE_INCOMPLETE')
    status=runner(['/bin/launchctl','print','gui/501/com.lexi.v35.api-only'],capture_output=True,text=True,timeout=10)
    match=re.search(r'^\s*pid = ([1-9][0-9]*)\s*$',status.stdout,re.M)
    require(status.returncode==0 and re.search(r'^\s*state = running\s*$',status.stdout,re.M) and match,'PUBLICATION_API_NOT_RUNNING')
    cwd=runner(['/usr/sbin/lsof','-a','-p',match.group(1),'-d','cwd','-Fn'],capture_output=True,text=True,timeout=10)
    require(cwd.returncode==0 and [s[1:] for s in cwd.stdout.splitlines() if s.startswith('n')]==[pin['app_root']],'PUBLICATION_API_PROCESS_CWD_DRIFT')


def prepare_replay(scope_path,scope_sha,receipt_path,*,backend=None,clock=None,new_id=None):
    scope=scope_load(scope_path,scope_sha,'prepare_replay')
    require(scope['mode']=='REHEARSAL' or (backend is None and clock is None and new_id is None),'REAL_REPLAY_INJECTION_FORBIDDEN')
    source_run=scope['source_run_id'];source_cutoff=scope['source_cutoff'];execution_cutoff=scope['source_execution_cutoff']
    env=backend or load_backend(scope);before=protected(scope)
    stage=Path(scope['stage_root']);receipt=exact(receipt_path,exists=False)
    require(receipt.is_relative_to(scope['evidence_root']) and not receipt.exists() and not stage.exists(),'REPLAY_PREPARATION_COLLISION')
    with no_external_execution():
        inventory=env.replay.load_inventory(scope['inventory']['path'],scope['inventory']['sha256'])
        row=frozen_source_row(scope,inventory)
        original,batch,_=env.replay.load_case(inventory,row)
        require(original['cutoff']==execution_cutoff and original.get('scope_refs',{}).get('source_cutoff')==source_cutoff and
                batch['input_sha256']==scope['source_batch_sha256'],'FROZEN_SOURCE_CONTEXT_MISMATCH')
        session=scope.get('source_us_session','20261021')
        refs=original.get('scope_refs',{})
        require(original.get('target_date')==scope['target_date'] and original.get('phase')=='NEXT_DAY' and
                original.get('source_sessions',{}).get('us')==session and refs.get('us_session_date',session)==session and
                refs.get('US_MAPPING',{}).get('source_session',session)==session and
                refs.get('US_MAPPING_RUN_CONTRACT_V1',{}).get('us_source_session',session)==session,
                'FROZEN_SOURCE_SESSION_MISMATCH')
        frozen_raw=canonical(dict(context=original,batch=batch))
        run_id=new_id or uuid4().hex
        require(run_id!=source_run and len(run_id)==32 and all(v in '0123456789abcdef' for v in run_id),'NEW_RUN_ID_INVALID')
        processing_at=(clock() if clock else datetime.now(timezone.utc)).isoformat()
        require(datetime.fromisoformat(processing_at)>datetime.fromisoformat(execution_cutoff),'PROCESSING_CLOCK_NOT_NEW')
        if scope['schema'].endswith('.v2'):
            require(datetime.fromisoformat(processing_at)>datetime.fromisoformat(row['generated_at']), 'PROCESSING_CLOCK_NOT_NEW')
        engine_context=copy.deepcopy(original);engine_context['scope_refs'].update(run_id=run_id,mwb_run_id=run_id)
        engine_batch=copy.deepcopy(batch);engine_batch['context']=engine_context
        require(env.replay.input_batch_sha(engine_batch)==batch['input_sha256'],'FROZEN_BATCH_IDENTITY_CHANGED')
        lane=env.c.LaneResult.model_validate(env.replay.actual_engine(engine_context,engine_batch))
        require(lane.lane.value=='US_MAPPING' and lane.run_id==run_id and lane.input_sha256==batch['input_sha256'],'REPLAY_LANE_IDENTITY_MISMATCH')
        require(lane.selection is not None and lane.selection.cutoff==execution_cutoff,'REPLAY_SELECTION_CUTOFF_DRIFT')
        processing=copy.deepcopy(engine_context)
        processing.update(phase='RETROSPECTIVE',trigger='MANUAL',cutoff=processing_at)
        processing['scope_refs'].update(source_run_id=source_run,source_cutoff=source_cutoff,
            source_execution_cutoff=execution_cutoff,requested_lanes=['US_MAPPING'],replay_kind='RETROSPECTIVE')
        ctx=env.c.RunContext.model_validate(processing)
        stocks=[env.c.StockDecision.model_validate(value) for value in env.engines.merge_decisions(ctx,[lane])]
        stocks=env.service.sort_stocks(stocks,[lane])
        partial=lane.state.value in {'NOT_RUN','RUNNING','PARTIAL','INPUT_MISSING','FAILED'}
        gaps=list(lane.gaps)
        if partial and not gaps:gaps=['LANE_PARTIAL']
        body=dict(derivative=True,authority='ORIGINAL_OWNERS_ONLY',context=engine_context,batches=[engine_batch],
            processing_context=processing,source_run_id=source_run,source_input_snapshot_sha256=scope['source_input']['sha256'])
        input_sha=digest(canonical(body))
        snapshot=env.c.seal_snapshot(dict(context=processing,run_id=run_id,input_sha256=env.c.digest(
            dict(source_run_id=source_run,batch_input_sha256=batch['input_sha256'],policy=lane.selection.policy_sha256)),
            generated_at=processing_at,available_at=processing_at,lanes=[lane.model_dump(mode='json')],
            stocks=[s.model_dump(mode='json') for s in stocks],
            counts=(env.c.Counts() if not stocks and partial else env.service.count_rows(stocks)).model_dump(mode='json'),
            changes=dict(source_run_id=source_run,source_input_snapshot_sha256=scope['source_input']['sha256'],
                input_snapshot_sha256=input_sha,source_cutoff=source_cutoff,source_execution_cutoff=execution_cutoff,
                processing_mode='RETROSPECTIVE_MANUAL',replay_helper_sha256=sha(HELPER)),gaps=gaps))
        env.service.validate_selected_evidence(snapshot)
        job=env.c.JobRecord(job_id=run_id,run_id=run_id,context=ctx,
            state=env.c.JobState.PARTIAL if gaps else env.c.JobState.SUCCEEDED,step='PUBLISH',
            started_at=processing_at,finished_at=processing_at,last_progress_at=processing_at,completed_count=1,total_count=1)
        store=env.Store(stage)
        store.save_input(input_sha,body);store.save_checkpoint(run_id,'LOAD_INPUTS',body)
        store.save_checkpoint(run_id,'PUBLISH',snapshot.model_dump(mode='json'));store.save_job(job)
        saved=store.commit_plan(snapshot)
        require(saved.product_sha256==snapshot.product_sha256,'STAGED_PRODUCT_READBACK_MISMATCH')
        require(canonical(dict(context=original,batch=batch))==frozen_raw,'ENGINE_MUTATED_FROZEN_SOURCE')
    unchanged(before)
    relative=[f'input_snapshots/{input_sha}.json',f'attempts/{run_id}.json',f'checkpoints/{run_id}/LOAD_INPUTS.json',
              f'checkpoints/{run_id}/PUBLISH.json',f'snapshots/{run_id}.json',f"catalog/{scope['target_date']}/RETROSPECTIVE/{run_id}.json"]
    files=[dict(relative=p,sha256=sha(stage/'manager_workbench'/p)) for p in relative]
    pointer=live_store_root(scope)/scope['result_pointer_relative']
    old=pointer.read_bytes() if pointer.exists() else None
    if old is not None:require(old==canonical(json.loads(old)),'NONCANONICAL_OLD_POINTER')
    old_backup=Path(scope['evidence_root'])/'original-retrospective-pointer.json'
    if old is not None:write_new(old_backup,old)
    next_pointer=canonical(dict(run_id=run_id,product_sha256=snapshot.product_sha256,generated_at=snapshot.generated_at))
    result=dict(schema='v4.us_hk.replay_publication_prepared.v1',state='PREPARED_NOT_PUBLISHED',mode=scope['mode'],
        scope_path=str(exact(scope_path)),scope_sha256=scope_sha,helper_sha256=sha(HELPER),
        source_run_id=source_run,target_date=scope['target_date'],source_cutoff=source_cutoff,source_execution_cutoff=execution_cutoff,
        processing_at=processing_at,new_run_id=run_id,input_snapshot_sha256=input_sha,product_sha256=snapshot.product_sha256,
        files=files,pointer_relative=scope['result_pointer_relative'],expected_old_pointer_sha256=digest(old) if old else None,
        old_pointer_backup=str(old_backup) if old else None,new_pointer_sha256=digest(next_pointer),
        protected_original_files=before,pipeline=dict(engine_calls=1,merge_calls=1,capture_calls=0,model_calls=0,network_calls=0),
        live_writes=0,authority_pointer_changes=[])
    if scope['schema'].endswith('.v2'):
        result.update(source_row_sha256=scope['source_row_sha256'],source_us_session=scope['source_us_session'])
    write_new(receipt,json_bytes(result));return result


def verify_product(prepared_path,prepared_sha,action,continuation,backend):
    prepared=read_json(prepared_path,prepared_sha)
    scope=scope_load(prepared['scope_path'],prepared['scope_sha256'],action,continuation)
    source_run=scope['source_run_id'];source_cutoff=scope['source_cutoff'];execution_cutoff=scope['source_execution_cutoff']
    require(prepared.get('schema')=='v4.us_hk.replay_publication_prepared.v1' and prepared.get('state')=='PREPARED_NOT_PUBLISHED' and
            prepared['helper_sha256']==sha(HELPER) and prepared['source_run_id']==source_run and
            prepared['source_cutoff']==source_cutoff and prepared['source_execution_cutoff']==execution_cutoff,'PUBLICATION_PREPARED_DRIFT')
    if scope['schema'].endswith('.v2'):
        require(prepared.get('target_date')==scope['target_date'] and
                prepared.get('source_row_sha256')==scope['source_row_sha256'] and
                prepared.get('source_us_session')==scope['source_us_session'],'PUBLICATION_PREPARED_DRIFT')
    if scope['mode']=='RELEASE':
        capsule=read_json(continuation['path'],continuation['sha256'])
        require(capsule.get('prepared_sha256')==prepared_sha and backend is None,'PUBLICATION_NOT_REVIEWED_OR_INJECTED')
    env=backend or load_backend(scope);stage=Path(scope['stage_root'])/'manager_workbench'
    run_id=prepared['new_run_id'];input_sha=prepared['input_snapshot_sha256']
    expected_files={f'input_snapshots/{input_sha}.json',f'attempts/{run_id}.json',f'checkpoints/{run_id}/LOAD_INPUTS.json',
                    f'checkpoints/{run_id}/PUBLISH.json',f'snapshots/{run_id}.json',f"catalog/{scope['target_date']}/RETROSPECTIVE/{run_id}.json"}
    require(len(prepared['files'])==6 and {ref['relative'] for ref in prepared['files']}==expected_files and
            prepared['pointer_relative']==scope['result_pointer_relative'],'PUBLICATION_FILE_SCOPE_NOT_DERIVED_FROM_PRODUCT')
    for ref in prepared['files']:require(sha(child(stage,ref['relative']))==ref['sha256'],'PREPARED_PRODUCT_FILE_DRIFT')
    snap=env.c.PlanSnapshot.model_validate(json.loads(child(stage,f"snapshots/{prepared['new_run_id']}.json").read_bytes()))
    require(snap.context.target_date==scope['target_date'] and snap.context.phase.value=='RETROSPECTIVE' and snap.context.trigger=='MANUAL' and
            snap.context.scope_refs.get('source_run_id')==source_run and snap.context.scope_refs.get('source_cutoff')==source_cutoff and
            snap.context.scope_refs.get('source_execution_cutoff')==execution_cutoff and
            snap.run_id==prepared['new_run_id'] and snap.product_sha256==prepared['product_sha256'] and
            snap.changes.get('input_snapshot_sha256')==prepared['input_snapshot_sha256'],'PUBLICATION_PRODUCT_BINDING_MISMATCH')
    expected=canonical(dict(run_id=snap.run_id,product_sha256=snap.product_sha256,generated_at=snap.generated_at))
    require(digest(expected)==prepared['new_pointer_sha256'],'POINTER_NOT_DERIVED_FROM_FROZEN_PRODUCT')
    env.service.validate_selected_evidence(snap);unchanged(prepared['protected_original_files'])
    body=json.loads(child(stage,f'input_snapshots/{input_sha}.json').read_bytes())
    require(digest(canonical(body))==input_sha and body.get('source_run_id')==source_run and
            body.get('processing_context')==snap.context.model_dump(mode='json') and len(body.get('batches',[]))==1 and
            body['batches'][0]['input_sha256']==scope['source_batch_sha256'] and
            body['context']['cutoff']==execution_cutoff and body['context']['scope_refs'].get('source_cutoff')==source_cutoff,
            'PUBLICATION_INPUT_CONTEXT_IDENTITY_MISMATCH')
    job=env.c.JobRecord.model_validate(json.loads(child(stage,f'attempts/{run_id}.json').read_bytes()))
    require(job.job_id==job.run_id==snap.run_id and job.context==snap.context and
            job.state.value in {'SUCCEEDED','PARTIAL'},'PUBLICATION_TERMINAL_JOB_MISMATCH')
    return prepared,scope,env,snap,expected


def publish(prepared_path,prepared_sha,receipt_path,*,continuation=None,backend=None,before_commit=None):
    prepared,scope,env,snap,new_pointer=verify_product(prepared_path,prepared_sha,'publish_replay',continuation,backend)
    require(scope['mode']=='REHEARSAL' or before_commit is None,'REAL_COMMIT_CALLBACK_FORBIDDEN')
    active_api(scope)
    receipt=exact(receipt_path,exists=False);require(receipt.is_relative_to(scope['evidence_root']) and not receipt.exists(),'PUBLICATION_RECEIPT_COLLISION_OR_ESCAPE')
    stage=Path(scope['stage_root'])/'manager_workbench';root=live_store_root(scope)
    require(root.is_dir(),'LIVE_STORE_MUST_EXIST')
    allowed={ref['relative']:ref['sha256'] for ref in prepared['files']};pointer=root/prepared['pointer_relative']
    pubkey=f"publish:{scope['target_date']}:RETROSPECTIVE"
    class GuardStore(env.Store):
        held=False
        @contextmanager
        def lock(self,key):
            if self.held and key==pubkey:yield
            else:
                with super().lock(key):yield
        def _write(self,path,obj,*,immutable,collision_read_limit=64*1024*1024):
            relative=path.relative_to(self.root).as_posix()
            require(self.held,'PUBLICATION_LOCK_NOT_HELD')
            if path==pointer:
                require(optional_sha(pointer)==prepared['expected_old_pointer_sha256'],'POINTER_CAS_DRIFT_INSIDE_STORE_LOCK')
                require(canonical(obj)==new_pointer,'UNEXPECTED_POINTER_VALUE')
            else:require(relative in allowed and digest(canonical(obj))==allowed[relative],'WRITE_OUTSIDE_EXACT_PUBLICATION_DELTA')
            return super()._write(path,obj,immutable=immutable,collision_read_limit=collision_read_limit)
    store=GuardStore(scope['live_state_root'])
    require(store.root==root,'PUBLICATION_STORE_ROOT_MISMATCH')
    with env.Store.lock(store,pubkey):
        store.held=True
        require(sha(prepared_path)==prepared_sha,'PREPARED_CHANGED_AT_PUBLICATION_LOCK')
        require(optional_sha(pointer)==prepared['expected_old_pointer_sha256'],'POINTER_CAS_DRIFT_NO_PUBLICATION')
        for relative in allowed:require(not (root/relative).exists(),'NEW_RUN_COLLISION_OR_PARTIAL_PUBLICATION_INSPECT')
        unchanged(prepared['protected_original_files'])
        active_api(scope)
        for relative in allowed:
            require(sha(child(stage,relative))==allowed[relative],'STAGED_FILE_CHANGED_AT_PUBLICATION_LOCK')
        if before_commit:before_commit()
        try:
            with no_external_execution():
                body=json.loads((stage/f"input_snapshots/{prepared['input_snapshot_sha256']}.json").read_bytes())
                store.save_input(prepared['input_snapshot_sha256'],body)
                for step in ('LOAD_INPUTS','PUBLISH'):
                    store.save_checkpoint(snap.run_id,step,json.loads((stage/f'checkpoints/{snap.run_id}/{step}.json').read_bytes()))
                job=env.c.JobRecord.model_validate(json.loads((stage/f'attempts/{snap.run_id}.json').read_bytes()))
                store.save_job(job);store.commit_plan(snap)
        except Exception as error:
            write_new(receipt,json_bytes(dict(state='PARTIAL_REQUIRES_INSPECTION',prepared_sha256=prepared_sha,
                current_pointer_sha256=optional_sha(pointer),error_type=type(error).__name__,retry_permitted=False)))
            raise
        require(optional_sha(pointer)==prepared['new_pointer_sha256'],'PUBLICATION_POINTER_READBACK')
        for relative,expected in allowed.items():require(sha(root/relative)==expected,'PUBLICATION_FILE_READBACK')
        unchanged(prepared['protected_original_files'])
    result=dict(state='PUBLISHED_RETROSPECTIVE_MANUAL',prepared_sha256=prepared_sha,run_id=snap.run_id,
                pointer_sha256=prepared['new_pointer_sha256'],source_run_id=scope['source_run_id'],
                source_cutoff=scope['source_cutoff'],source_execution_cutoff=scope['source_execution_cutoff'],
                authority_pointer_changes=[],natural_verification='NOT_RUN')
    write_new(receipt,json_bytes(result));return result


def rollback(prepared_path,prepared_sha,publication_pin,receipt_path,*,continuation=None,backend=None):
    prepared,scope,env,snap,_=verify_product(prepared_path,prepared_sha,'rollback_replay',continuation,backend)
    publication=read_json(publication_pin['path'],publication_pin['sha256'])
    require(publication.get('state')=='PUBLISHED_RETROSPECTIVE_MANUAL' and publication.get('prepared_sha256')==prepared_sha and
            publication.get('pointer_sha256')==prepared['new_pointer_sha256'],'ROLLBACK_PUBLICATION_RECEIPT_MISMATCH')
    receipt=exact(receipt_path,exists=False);require(receipt.is_relative_to(scope['evidence_root']) and not receipt.exists(),'ROLLBACK_RECEIPT_COLLISION_OR_ESCAPE')
    active_api(scope);root=live_store_root(scope);require(root.is_dir(),'LIVE_STORE_MUST_EXIST')
    store=env.Store(scope['live_state_root']);require(store.root==root,'PUBLICATION_STORE_ROOT_MISMATCH')
    pointer=root/prepared['pointer_relative']
    with store.lock(f"publish:{scope['target_date']}:RETROSPECTIVE"):
        active_api(scope)
        require(optional_sha(pointer)==prepared['new_pointer_sha256'],'ROLLBACK_POINTER_CAS_DRIFT')
        unchanged(prepared['protected_original_files'])
        old=prepared['old_pointer_backup']
        if old:
            raw=exact(old).read_bytes();require(digest(raw)==prepared['expected_old_pointer_sha256'],'ROLLBACK_BACKUP_DRIFT')
            # Existing store writer under its existing publication kernel lock.
            store._write(pointer,json.loads(raw),immutable=False)
        else:
            require(prepared['expected_old_pointer_sha256'] is None,'ROLLBACK_ABSENCE_MISMATCH')
            store.io.unlink_if_same(prepared['pointer_relative'],pointer.read_bytes())
        require(optional_sha(pointer)==prepared['expected_old_pointer_sha256'],'ROLLBACK_POINTER_READBACK')
    result=dict(state='RETROSPECTIVE_POINTER_RESTORED_HISTORY_RETAINED',prepared_sha256=prepared_sha,
                retained_run_id=snap.run_id,authority_pointer_changes=[])
    write_new(receipt,json_bytes(result));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','publish','rollback'])
    parser.add_argument('--scope');parser.add_argument('--scope-sha256')
    parser.add_argument('--prepared');parser.add_argument('--prepared-sha256')
    parser.add_argument('--continuation');parser.add_argument('--continuation-sha256')
    parser.add_argument('--publication');parser.add_argument('--publication-sha256')
    parser.add_argument('--receipt',required=True)
    args=parser.parse_args();continuation=dict(path=args.continuation,sha256=args.continuation_sha256) if args.continuation else None
    if args.action=='prepare':result=prepare_replay(args.scope,args.scope_sha256,args.receipt)
    elif args.action=='publish':result=publish(args.prepared,args.prepared_sha256,args.receipt,continuation=continuation)
    else:result=rollback(args.prepared,args.prepared_sha256,dict(path=args.publication,sha256=args.publication_sha256),args.receipt,continuation=continuation)
    print(json.dumps(result))


if __name__=='__main__':main()
