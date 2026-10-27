"""Facts from current V4 authority readers; never invokes a producer or repair."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import ast
import os
import re
import subprocess

from domains.task_status import build_task_status, _latest_receipt
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from infrastructure.runtime_graph.current import FLAGS, read_json, safe, sha
from infrastructure.runtime_graph.notifications import process_identity
from stage_center.consumer import StageSelectionConsumer


def proof(path, root, *, kind):
    # The original A receipt is 104,229,542 bytes (full reconciliation).
    # Only this native receipt gets a finite 128MiB limit; DTOs remain tiny.
    value, raw = read_json(path, root, max_bytes=128*1024*1024 if kind == 'A_RECEIPT' else 64*1024*1024 if kind in {'MANAGER_JOB','PDF_INDEX'} else 16*1024*1024)
    safe(value)
    if kind in {'DISPATCH_RECEIPT', 'DAILY_CURRENT', 'DAILY_RECEIPT', 'STAGE_RECEIPT', 'A_RECEIPT'} and any(value.get(k) is not False for k in FLAGS):
        raise ValueError('EVIDENCE_SAFETY_FIELDS_MISSING')
    return value, {'kind': kind, 'path': str(path), 'sha256': sha(raw)}


def compact_authorities(payload):
    """Optional transport projection; immutable authority refs remain authoritative."""
    def summary(value):
        if not isinstance(value,dict):return value
        result={k:v for k,v in value.items() if isinstance(v,(str,int,float,bool)) or v is None}
        for key in ('cannot_confirm','missing_symbols'):
            if isinstance(value.get(key),list):
                result[key]=value[key][:1]
                result[key+'_count']=len(value[key])
        return result
    nodes=[]
    for node in payload.get('nodes',[]):
        item=summary(node)
        for key in ('evidence','dependencies','execution_observation','coverage','date_roles','historical_action','last_lifecycle_hint','source_status_counts','last_completed_result'):
            if key in node:item[key]=node[key]
        for key in ('task_status','timeline','deadline','end_to_end_deadline','executor_result','authoritative_business'):
            if key in node:item[key]=summary(node[key])
        selection=node.get('selection')
        if isinstance(selection,dict):
            item['selection']=summary(selection)
            item['selection']['stage']=summary(selection.get('stage',{}))
            item['selection']['markets']={k:summary(v) for k,v in selection.get('markets',{}).items()}
            item['selection']['execution_evidence']=summary(selection.get('execution_evidence',{}))
        item['detail_api']='/api/v3/runtime-graph/authorities?date='+payload['business_date']+'&node_ids='+node['node_id']
        item['observed_full_node_sha256']=sha(json.dumps(node,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        nodes.append(item)
    return {**{k:v for k,v in payload.items() if k!='nodes'},'nodes':nodes,'projection':'v4.runtime_graph_authority.compact.v1'}


class CurrentEvidenceReader:
    def __init__(self, config):
        self.config = config

    def _catalog(self):
        bound = self.config['main']
        app = Path(bound['app_root'])
        paths = {'catalog_sha256': app / 'contracts/runtime_workloads.json',
                 'registry_sha256': app / 'infrastructure/scheduling/executor_registry.py'}
        for key, path in paths.items():
            if path.is_symlink() or path.resolve(strict=True) != path or sha(path.read_bytes()) != bound[key]:
                raise ValueError('CURRENT_MAIN_' + key.upper() + '_DRIFT')
        return load_workload_catalog(paths['catalog_sha256'])

    def _runtime_binding(self):
        if self.config.get('runtime_binding_required') is not True:
            return {'status':'SOURCE_ONLY_CANARY', 'current_runtime_verified':False}
        identity = 'gui/' + str(os.getuid()) + '/com.lexi.v35.scheduler'
        expected = str(Path(self.config['main']['app_root']) / 'ops/launch_v35_macos_scheduler.sh')
        try:
            result = subprocess.run(['/bin/launchctl','print',identity], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,timeout=1,check=False)
            text = result.stdout.decode('utf-8',errors='replace')
            pid = re.search(r'(?m)^\s*pid = (\d+)\s*$',text)
            arguments = re.search(r'(?ms)^\s*arguments = \{\s*(.*?)^\s*\}', text)
            actual_args = [line.strip() for line in arguments.group(1).splitlines() if line.strip()] if arguments else []
            if result.returncode or expected not in actual_args or not pid:
                raise ValueError('ACTUAL_MAIN_LOADED_OWNER_UNCONFIRMED')
            return {'status':'VERIFIED', 'current_runtime_verified':True, 'label':identity,
                    'pid':int(pid.group(1)), 'launcher':expected,
                    'observed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {'status':'CANNOT_CONFIRM','current_runtime_verified':False, 'reason':str(exc), 'label':identity}

    def descriptors(self):
        catalog = self._catalog()
        source = Path(self.config['main']['app_root']) / 'infrastructure/scheduling/executor_registry.py'
        registry = set()
        close_nodes = {}
        for assignment in ast.parse(source.read_text()).body:
            if isinstance(assignment, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ALLOWED_WORKLOAD_IDS' for t in assignment.targets):
                if isinstance(assignment.value, ast.Call) and isinstance(assignment.value.func, ast.Name) and assignment.value.func.id == 'frozenset':
                    registry = set(ast.literal_eval(assignment.value.args[0]))
            if isinstance(assignment, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CLOSE_NODE_BY_WORKLOAD' for t in assignment.targets):
                close_nodes = ast.literal_eval(assignment.value)
        result = [{'node_id': w.workload_id, 'owner': w.owner_id, 'kind': 'MAIN',
                   'enabled': w.enabled, 'executor_status': 'REGISTERED' if w.workload_id in registry else 'node_unknown',
                   'business_node_id':close_nodes.get(w.workload_id),
                   'date_roles': {'scheduled': w.scheduled_date_role, 'signal': w.signal_date_role, 'target': w.target_date_role}}
                  for w in catalog.workloads]
        result += [{'node_id': 'stage:' + sid, 'owner': 'STAGE_CENTER', 'kind': 'STAGE', 'enabled': True}
                   for sid in self.config.get('stage_ids', [])]
        result.append({'node_id': 'review_core_daily', 'owner': 'REVIEW_CORE_DAILY', 'kind': 'DAILY', 'enabled': True})
        result += list(self.config.get('independent_owners', []))
        return result

    def collect(self, date, node_ids=None, *, compact=False):
        datetime.strptime(date, '%Y%m%d')
        catalog = self._catalog()
        descriptors = self.descriptors()
        known = {row['node_id']: row for row in descriptors}
        selected = set(node_ids) if node_ids is not None else set(known)
        # IDs are fixed owners, never arbitrary paths or historical aliases.
        nodes = []
        main_ids = {w.workload_id: w for w in catalog.workloads}
        main_selected = selected.intersection(main_ids)
        runtime = self._runtime_binding()
        if main_selected:
            ledger = ExecutionLedger(Path(self.config['ledger_root']))
            receipts = ledger.list_receipts(date, mode='LIVE')
            verified, chain_reason = ledger.verify_receipt_chain(date, mode='LIVE')
            # One existing authority projection, restricted again below. Its
            # business meanings and date-role resolution remain unchanged.
            if main_selected == set(main_ids) and not compact:
                dto = build_task_status(catalog, ledger, date,
                    data_root=Path(self.config['task_evidence_root']),
                    stage_selection_root=Path(self.config['stage_selection_root']))
            else:
                # Compact graph transport needs only these original TaskStatus
                # projections. Full build_task_status also reads every Stage
                # timeline, duplicated again by _stage below, plus unrelated
                # registration/scheduler detail absent from the compact DTO.
                from domains.task_status import _logical_row, _timeline_receipt
                from contracts.close_timeline import CLOSE_TIMELINE
                now = datetime.now(ZoneInfo('Asia/Shanghai'))
                dto = {'groups': {'logical': [_logical_row(main_ids[n], _latest_receipt(main_ids[n], receipts, date), date, now) for n in sorted(main_selected)]},
                       'timeline_nodes': [_timeline_receipt(item, catalog=catalog, ledger=ledger,
                           receipts=receipts, business_date=date, data_root=Path(self.config['task_evidence_root']),
                           stage_selection_root=Path(self.config['stage_selection_root']), now=now, chain_verified=verified)
                           for item in CLOSE_TIMELINE if item.get('workload_id') in main_selected]}
                if main_selected == set(main_ids):
                    # Preserve the full TaskStatus current-slot/last-result
                    # distinction while omitting only its unrelated DTOs.
                    from domains.task_status import _load_scheduler_slot_observations, _apply_scheduler_slot_observation
                    slots = _load_scheduler_slot_observations(ledger, catalog, date, now)
                    dto['groups']['logical'] = [
                        _apply_scheduler_slot_observation(row, main_ids[row['workload_id']], slots,
                            ledger, date, receipts, now) for row in dto['groups']['logical']]
                    dto['timeline_nodes'] = [
                        _apply_scheduler_slot_observation(row, main_ids[row['workload_id']], slots,
                            ledger, date, receipts, now, timeline=True)
                        if int(row['position']) > 8 and row.get('workload_id') in main_ids else row
                        for row in dto['timeline_nodes']]
            logical = {r['workload_id']: r for r in dto['groups']['logical']}
            timelines = {r.get('workload_id'): r for r in dto['timeline_nodes'] if r.get('workload_id')}
            for nid in sorted(main_selected):
                row = dict(logical[nid])
                receipt = _latest_receipt(main_ids[nid], receipts, date)
                node = {**known[nid], 'status': row['status'], 'reason': row.get('result_code'),
                        'execution_phase': row.get('scheduler_state', row['status']),
                        'business_status': row.get('business_status', 'CANNOT_CONFIRM'),
                        'task_status': row, 'evidence': [], 'dependencies': [],
                        'page_status': 'CANNOT_CONFIRM', 'page_reason': 'PAGE_PROOF_NOT_BOUND',
                        'evidence_status': 'CANNOT_CONFIRM', **FLAGS}
                if nid in timelines:
                    node['timeline'] = timelines[nid]
                    if timelines[nid].get('stage_id'):
                        node['dependencies'] = ['stage:' + timelines[nid]['stage_id']]
                if not main_ids[nid].enabled:
                    nodes.append(node)
                    continue
                if known[nid]['executor_status'] != 'REGISTERED':
                    node.update(status='node_unknown', reason='ACTUAL_EXECUTOR_NOT_REGISTERED')
                    nodes.append(node)
                    continue
                if self.config.get('runtime_binding_required') is True and not runtime['current_runtime_verified']:
                    node.update(status='node_unknown', reason=runtime.get('reason','ACTUAL_MAIN_LOADED_OWNER_UNCONFIRMED'))
                    nodes.append(node)
                    continue
                if receipt is not None:
                    path = Path(self.config['ledger_root']) / str(receipt.get('receipt_path', ''))
                    try:
                        original, ref = proof(path, self.config['ledger_root'], kind='DISPATCH_RECEIPT')
                        if not verified or not original.get('run_id') or original.get('business_date') != date or str(original.get('mode')).upper() != 'LIVE':
                            raise ValueError('DISPATCH_CHAIN_DATE_RUN_UNVERIFIED:' + str(chain_reason))
                        if original.get('run_id') != receipt.get('run_id'):
                            raise ValueError('DISPATCH_RUN_MISMATCH')
                        matches = [r for r in original.get('workload_results', []) if r.get('workload_id') == nid]
                        if len(matches) != 1 or nid not in original.get('selected_workload_ids', []):
                            raise ValueError('DISPATCH_WORKLOAD_RESULT_MISSING')
                        node.update(run_id=original['run_id'], evidence_status='VERIFIED',
                                    status=str(matches[0].get('status', 'CANNOT_CONFIRM')),
                                    execution_phase='COMPLETED', observed_at=original.get('finished_at'))
                        node['evidence'].append(ref)
                        node['executor_result'] = {k:matches[0].get(k) for k in ('status','lane_status','row_count','reason','target_date') if k in matches[0]}
                        # Safe fact-only payload: no promotion of pit_certified,
                        # aggregate success, or partial underlying business.
                        authority = matches[0].get('_authoritative_payload')
                        if isinstance(authority, dict):
                            safe(authority)
                            node['authoritative_business'] = {k: authority[k] for k in
                                ('status', 'reason', 'trade_date', 'target_date', 'run_id', 'pit_certified',
                                 'first_failed_layer', 'blocked_layer', 'artifact_path', 'receipt_path', 'receipt_sha256') if k in authority}
                            node['business_status'] = str(authority.get('status', node['business_status']))
                            node['status'] = node['business_status']
                            if authority.get('reason'):
                                node['reason'] = authority['reason']
                            if known[nid].get('business_node_id'):
                                self._historical_action(node, authority, date, known[nid]['business_node_id'])
                        if nid == 'research_panel_daily_a':
                            self._a_receipt(node, date, matches[0])
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        node.update(status='CANNOT_CONFIRM', evidence_status='CANNOT_CONFIRM', reason=str(exc))
                if nid == 'hk_auction_0920':
                    if receipt is None and row['status']=='PENDING_NOT_DUE':
                        node['business_status']='NOT_DUE'
                    else:
                        self._opening(node, date)
                if nid == 'fupan_video_check':
                    node['dependencies'] = ['review_core_daily']
                    node['current_upstream'] = self._daily(date)
                node['dependency_status'] = 'DECLARED' if node['dependencies'] else 'NOT_DECLARED_BY_AUTHORITY'
                self._execution_entry(node, main_ids[nid], date, ledger, receipts, runtime)
                nodes.append(node)
        for nid in sorted(selected - main_selected):
            if nid == 'review_core_daily':
                daily=self._daily(date); self._observation_only(daily,date,'REVIEW_CORE_DAILY');nodes.append(daily)
            elif nid in known and known[nid]['kind'] == 'STAGE':
                stage=self._stage(date,nid,known[nid]);self._observation_only(stage,date,'STAGE_CENTER',nid.removeprefix('stage:'));nodes.append(stage)
            else:
                unknown=self._independent(date,known.get(nid,{'node_id':nid,'owner':'UNKNOWN'}),compact=compact)
                self._observation_only(unknown,date,unknown['owner']);nodes.append(unknown)
        return {'schema_version': 'v4.runtime_graph_authority.v1', 'business_date': date,
                'observed_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'proof_runtime':{'pid':os.getpid(), 'module_file':str(Path(__file__).resolve()),
                                 'module_sha256':sha(Path(__file__).read_bytes())},
                'authority_identity': self.config['main'],
                'runtime_binding':runtime,
                'config_sha256':self.config.get('_sha256'),
                'reader_bindings':{**{k:self.config[k] for k in ('graph_root','ledger_root','opening_root','stage_selection_root','stage_receipt_root','daily_receipt_root')},'native_reader_roots':self.config.get('native_reader_roots',{})},
                'api_template_catalog_sha256': sha((Path(__file__).resolve().parents[1] / 'contracts/runtime_workloads.json').read_bytes()),
                'descriptors': descriptors, 'nodes': nodes, **FLAGS}

    def _independent(self, date, descriptor, *, compact=False):
        """Read only existing native contracts; entry hints never grant business READY."""
        node={**descriptor,'status':'CANNOT_CONFIRM','business_status':'CANNOT_CONFIRM',
              'execution_phase':'CANNOT_CONFIRM','evidence':[],'page_status':'CANNOT_CONFIRM',**FLAGS}
        roots=self.config.get('native_reader_roots',{})
        nid=descriptor['node_id']
        def root(key):
            path=Path(roots[key])
            if not path.is_absolute() or path.resolve(strict=True)!=path or not path.is_dir():
                raise ValueError('NATIVE_READER_ROOT_UNSAFE:'+key)
            return path
        try:
            if nid=='PREP_0915':
                source=root('stage_candidate_root')
                from infrastructure.stage_acquisition_universe_commit import StageAcquisitionUniverseCommit
                value=StageAcquisitionUniverseCommit(source).read_current(date)
                receipt=value['receipt']
                for kind,key in (('CANDIDATE_ARTIFACT','artifact_path'),('CANDIDATE_MANIFEST','manifest_path'),('CANDIDATE_RECEIPT','receipt_path')):
                    _,ref=proof(value[key],source,kind=kind);node['evidence'].append(ref)
                node.update(status=receipt['status'],business_status=receipt['status'],execution_phase='COMPLETED_OWNER_RECEIPT',
                            run_id=value['run_id'],row_count=receipt['row_count'],reason='CANDIDATE_UNIVERSE_ONLY_NOT_SELECTION')
            elif descriptor.get('owner')=='STAGE_PRECAPTURE':
                sid=descriptor['business_stage_id']
                if nid=='PRECAPTURE_A_0925':
                    source=root('stage_a_opening_root');folder=source/'native_opening'/date/'STAGE_0925'/'attempts'
                else:
                    source=Path(self.config['stage_receipt_root']);folder=source/date/sid/'precapture_attempts'
                records=[]
                for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:128]:
                    body,ref=proof(path,source,kind='PRECAPTURE_DIAGNOSTIC')
                    if any(body.get(k) is not False for k in FLAGS) or body.get('trade_date')!=date:
                        raise ValueError('PRECAPTURE_DATE_OR_SAFETY_MISMATCH')
                    if nid=='PRECAPTURE_A_0925':
                        if body.get('stage_id')!='STAGE_0925' or body.get('attempt_id')!=path.stem or body.get('authorizes_selection') is not False:
                            raise ValueError('A_PRECAPTURE_IDENTITY_MISMATCH')
                        observed=body['finished_at'];detail=body.get('payload') or {}
                    else:
                        if (body.get('schema')!='stage_center.hk_precapture_diagnostic.v1' or body.get('stage_id')!=sid
                                or body.get('node_id')!=nid or body.get('attempt_id')!=path.stem
                                or body.get('authorizes_selection') is not False or body.get('grants_retry') is not False):
                            raise ValueError('HK_PRECAPTURE_IDENTITY_MISMATCH')
                        observed=body['evaluated_at'];detail=next(iter(body.get('pre_captures') or [{}]))
                    if not isinstance(detail,dict):raise ValueError('PRECAPTURE_DETAIL_NOT_OBJECT')
                    instant=datetime.fromisoformat(observed)
                    if instant.tzinfo is None or instant.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')!=date:
                        raise ValueError('PRECAPTURE_CLOCK_UNBOUND')
                    records.append((instant,body,detail,ref))
                if not records:raise ValueError('EXACT_DATE_PRECAPTURE_DIAGNOSTIC_MISSING')
                _,body,detail,ref=max(records,key=lambda row:row[0]);node['evidence']=[ref]
                node.update(status='OBSERVED',source_status=body.get('status'),execution_phase='COMPLETED_OWNER_DIAGNOSTIC',
                    run_id=body['attempt_id'],reason=body.get('error') or next(iter(detail.get('cannot_confirm') or []),'PRECAPTURE_ONLY_NOT_SELECTION'),
                    authorizes_selection=False,requested_rows=detail.get('requested_rows') or len(detail.get('requested_symbols') or []),
                    returned_rows=detail.get('returned_rows') if 'returned_rows' in detail else len(detail.get('rows') or []))
            elif nid in {'manager_workbench','manager_workbench_api'}:
                source=root('manager_main_state_root' if nid=='manager_workbench' else 'manager_api_state_root')/'manager_workbench'
                from v4.manager_workbench.contracts import JobRecord
                records=[]
                for path in sorted((source/'attempts').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:128]:
                    node['expected_artifact_path']=str(path)
                    body,ref=proof(path,source,kind='MANAGER_JOB');job=JobRecord.model_validate(body)
                    if job.context.target_date!=date:continue
                    if job.job_id!=path.stem:raise ValueError('MANAGER_JOB_PATH_ID_MISMATCH')
                    observed=job.finished_at or job.last_progress_at or job.started_at
                    if not observed:continue
                    instant=datetime.fromisoformat(observed)
                    if instant.tzinfo is None:raise ValueError('MANAGER_JOB_CLOCK_UNBOUND')
                    records.append((instant,job,ref))
                    break  # Original mutable attempts: latest modified exact-date job, not a PIT ordering claim.
                if not records:raise ValueError('EXACT_DATE_MANAGER_JOB_MISSING')
                _,job,ref=max(records,key=lambda row:row[0]);node['evidence']=[ref]
                terminal=job.state.value in {'SUCCEEDED','PARTIAL','FAILED','CANCELLED','INTERRUPTED','USER_STOPPED'}
                node.update(status=job.state.value if terminal and job.finished_at else 'CANNOT_CONFIRM',
                    execution_phase='COMPLETED_OWNER_JOB' if terminal and job.finished_at else 'CURRENT_PROCESS_NOT_PROVEN',
                    source_status=job.state.value,run_id=job.run_id,job_id=job.job_id,reason=job.failure_code or 'JOB_STATE_ONLY_NOT_PLAN_OR_PIT_ACCEPTANCE',
                    completed_count=job.completed_count,total_count=job.total_count,
                    job_selection_scope='LATEST_MODIFIED_EXACT_DATE_NATIVE_ATTEMPT',
                    producer_owner_scope='SHARED_NATIVE_STORE_EXECUTOR_NOT_ATTRIBUTED')
            elif nid=='us_market_digest_independent':
                source=root('us_ledger_root');ledger=ExecutionLedger(source)
                verified,reason=ledger.verify_receipt_chain(date,mode='LIVE')
                if not verified:raise ValueError('US_INDEPENDENT_LEDGER_CHAIN:'+str(reason))
                workload=next(w for w in self._catalog().workloads if w.workload_id=='us_market_digest')
                receipt=_latest_receipt(workload,ledger.list_receipts(date,mode='LIVE'),date)
                if receipt is None:raise ValueError('US_EXACT_DATE_DISPATCH_RECEIPT_MISSING')
                body,ref=proof(source/receipt['receipt_path'],source,kind='DISPATCH_RECEIPT')
                if body.get('business_date')!=date or str(body.get('mode')).upper()!='LIVE' or body.get('run_id')!=receipt.get('run_id'):
                    raise ValueError('US_INDEPENDENT_DISPATCH_IDENTITY')
                matches=[r for r in body.get('workload_results',[]) if r.get('workload_id')=='us_market_digest']
                if len(matches)!=1 or 'us_market_digest' not in body.get('selected_workload_ids',[]):raise ValueError('US_INDEPENDENT_WORKLOAD_MISSING')
                result=matches[0];node['evidence']=[ref]
                node.update(status=result.get('status','CANNOT_CONFIRM'),execution_phase='COMPLETED',run_id=body['run_id'],
                    reason=result.get('reason') or result.get('result_code'),source_status=result.get('status'))
            elif nid=='zsxq_pdf':
                source=root('pdf_data_root')
                # Reuse original metadata readers only. Full document proof stays
                # in the original research detail API, never in the graph path.
                from infrastructure.zsxq_pdf_ingestion import STATE_RELATIVE,_read_index,_latest_engine_run
                from infrastructure.data_store import NativeDataStore
                index=_read_index(NativeDataStore(source));counts={}
                for row in index['documents'].values():
                    if not isinstance(row,dict) or not isinstance(row.get('source'),dict) or row['source'].get('trade_date')!=date:continue
                    latest=_latest_engine_run(row);status=str((latest[1] if latest else {}).get('status') or 'PENDING')
                    counts[status]=counts.get(status,0)+1
                value={'schema_version':'v4.zsxq_pdf_ingestion_projection.v1','research_date':date,
                       'status':'CANNOT_CONFIRM','cannot_confirm':['NATIVE_QUEUE_INDEX_ONLY_COMPLETION_NOT_VERIFIED'],
                       'total_count':sum(counts.values()),'source_status_counts':counts,**FLAGS}
                node['source_status_counts']=counts
                safe(value)
                if value.get('schema_version')!='v4.zsxq_pdf_ingestion_projection.v1' or value.get('research_date')!=date:
                    raise ValueError('PDF_NATIVE_PROJECTION_IDENTITY')
                if (source/STATE_RELATIVE).is_file():
                    _,ref=proof(source/STATE_RELATIVE,source,kind='PDF_INDEX');node['evidence']=[ref]
                node.update({k:value[k] for k in ('status','completed_count','done_count','partial_count','failed_count','pending_count','cannot_confirm_count','total_count') if k in value})
                node.update(business_status=value.get('status'),reason=next(iter(value.get('cannot_confirm') or []),'PDF_ORIGINAL_READ_ONLY_PROJECTION'),
                            execution_phase='QUEUE_PROJECTION_ONLY_NOT_PROCESS_STATE')
            else:raise ValueError('AUTHORITY_READER_NOT_BOUND')
            node['reader_status']='BOUND_NATIVE_READ_ONLY'
        except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:
            node.update(status='CANNOT_CONFIRM',reason=str(exc),reader_status='NATIVE_EVIDENCE_MISSING_OR_UNVERIFIED')
        return node

    def _entry_records(self,date,owner,node_id):
        folder=Path(self.config['inbox']).parent/'entry_observations'/date/owner/node_id
        paths=sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:128] if folder.is_dir() else []
        records=[]
        for path in paths:
            try:
                body,ref=proof(path,folder,kind='EXECUTOR_ENTRY')
                if (body.get('schema_version')!='v4.runtime_execution_entry.v1' or body.get('phase')!='EXECUTOR_ENTERED'
                        or body.get('owner')!=owner or body.get('node_id')!=node_id or body.get('business_date')!=date
                        or any(body.get(k) is not False for k in FLAGS)):
                    raise ValueError('ENTRY_OWNER_NODE_DATE_MISMATCH')
                records.append((body,ref))
            except (OSError,ValueError,KeyError,TypeError):
                continue
        return sorted(records,key=lambda pair:pair[0]['observed_at'],reverse=True)

    def _execution_entry(self,node,workload,date,ledger,receipts,runtime):
        from domains.task_status import _observation_process_state, _observation_time
        for entry,ref in self._entry_records(date,'MAIN',workload.workload_id):
            try:
                expected=Path(self.config['main']['app_root'])/'infrastructure/scheduling/executor_registry.py'
                if (entry.get('caller_file')!=str(expected) or entry.get('caller_sha256')!=self.config['main']['registry_sha256']
                        or entry.get('caller_function')!='__call__' or entry.get('owner_id')!=workload.owner_id
                        or type(entry.get('attempt')) is not int or entry['attempt']<=0
                        or entry.get('slot') not in workload.slots
                        or not re.fullmatch(r'[A-Za-z0-9_.-]+',entry.get('run_id',''))):
                    raise ValueError('ENTRY_CALLER_OR_CATALOG_IDENTITY_MISMATCH')
                birth=process_identity(entry.get('pid'))
                if not birth or any(entry.get(k)!=birth[k] for k in birth):
                    raise ValueError('ENTRY_PID_ENDED_OR_REUSED')
                now=datetime.now(ZoneInfo('Asia/Shanghai'))
                entered=_observation_time(entry['observed_at'])
                if not _observation_time(entry['process_started_at'])<=entered<=now:
                    raise ValueError('ENTRY_TIME_MISMATCH')
                native={'status':'RUNNING','pid':entry['pid'],'slot':entry['slot'],
                        'actual_started_at':entry['process_started_at'],'observed_at':entry['observed_at']}
                state,run_id,binding=_observation_process_state(native,workload,ledger,date,receipts,now)
                if state!='RUNNING' or run_id!=entry['run_id']:
                    raise ValueError('ENTRY_NATIVE_CLAIM_OR_TERMINAL_MISMATCH:'+binding)
                if runtime.get('current_runtime_verified') is not True or not (entry['pid']==runtime.get('pid') or entry.get('parent_pid')==runtime.get('pid')):
                    raise ValueError('ENTRY_CURRENT_MAIN_PARENT_UNCONFIRMED')
                refs=[]
                for relative in (f"claims/live/{date}/{entry['slot']}/dispatch.claim.json",
                                 f"workloads/live/{date}/{entry['slot']}/{workload.workload_id}.workload-claim.json"):
                    claim,cref=proof(Path(ledger.root)/relative,ledger.root,kind='NATIVE_CLAIM')
                    if not _observation_time(claim['created_at'])<=entered:
                        raise ValueError('ENTRY_PREDATES_NATIVE_CLAIM')
                    refs.append(cref)
                prior=sum(1 for r in receipts if r.get('slot')==entry['slot'])
                if entry['attempt']!=prior+1:
                    raise ValueError('ENTRY_ATTEMPT_MISMATCH')
                terminal=Path(ledger.root)/f"receipts/live/{date}/{entry['slot']}/{run_id}.dispatch-receipt.json"
                if str(terminal)!=entry.get('source_path') or terminal.exists():
                    raise ValueError('ENTRY_TERMINAL_PRESENT_OR_PATH_MISMATCH')
                node['last_completed_execution_phase']=node.get('execution_phase')
                node['last_completed_result']={key:node.get(key) for key in ('run_id','status','business_status','reason','observed_at')} if node.get('run_id') else None
                node['result_scope']='LAST_COMPLETED_RESULT_CURRENT_RUN_IN_PROGRESS' if node.get('run_id') else 'NO_TERMINAL_FOR_CURRENT_RUN'

                node['execution_phase']='RUNNING_VERIFIED_OBSERVATION'
                node['execution_observation']={
                    'state':'RUNNING_VERIFIED_OBSERVATION','run_id':run_id,'attempt':entry['attempt'],
                    'pid':entry['pid'],'process_start_token':entry['process_start_token'],
                    'observed_at':entry['observed_at'],'caller_sha256':entry['caller_sha256'],
                    'terminal_receipt_path':str(terminal),'claim_as_start':False,
                    'native_binding':binding,'evidence':[ref,*refs]}
                return
            except (OSError,ValueError,TypeError,KeyError) as exc:
                node['execution_observation']={'state':'CANNOT_CONFIRM','reason':str(exc),'evidence':[ref]}

    def _observation_only(self,node,date,owner,entry_id=None):
        records=self._entry_records(date,owner,entry_id or node['node_id'])
        if records:
            body,ref=records[0]
            source=self.config.get('entry_sources',{}).get(owner,{})
            birth=process_identity(body.get('pid'))
            identity=bool(source and body.get('caller_file')==source.get('module_file')
                          and body.get('caller_sha256')==source.get('module_sha256')
                          and birth and body.get('process_start_token')==birth['process_start_token'])
            node['execution_observation']={'state':'OBSERVATION_ONLY' if identity else 'CANNOT_CONFIRM',
                'reason':'NATIVE_RUN_CLAIM_TERMINAL_BINDING_NOT_PROVEN_FOR_THIS_OWNER',
                'business_readiness_granted':False,'evidence':[ref]}

    def _opening(self, node, date):
        root = Path(self.config['opening_root'])
        try:
            payload = OpeningSecondFilterStore(root).read(date)
            if payload is None:
                raise ValueError('OPENING_EXACT_DATE_MISSING')
            for kind, path in [('OPENING_ARTIFACT', root / f'opening_second_filter/{date}/STAGE_0925.json'),
                               ('OPENING_RECEIPT', root / f'receipts/opening_second_filter/{date}/STAGE_0925.json'),
                               ('OPENING_MANIFEST', root / 'manifest.json')]:
                _, ref = proof(path, root, kind=kind); node['evidence'].append(ref)
            node['business_status'] = payload['status']
            node['row_count'] = payload['row_count']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            node['status'] = 'CANNOT_CONFIRM'
            node['business_status'] = 'CANNOT_CONFIRM'; node['business_reason'] = str(exc)

    def _historical_action(self, node, authority, date, declared_node):
        # Current registry declares this exact node, never a widened alias.
        # Old actions lack run IDs. Their diagnostics remain explicitly
        # historical and cannot establish business READY or a page PASS.
        try:
            if authority.get('node_id') != declared_node:
                raise ValueError('ACTION_REGISTRY_NODE_MISMATCH')
            body, ref = proof(Path(authority['node_receipt_path']),self.config['task_evidence_root'],kind='HISTORICAL_ACTION')
            if (body.get('schema_version')!='v3_5_close_review_node_receipt.v1'
                    or body.get('node_id')!=declared_node
                    or any(body.get(k)!=date for k in ('date','business_date','trade_date'))
                    or any(body.get(k) is not False for k in FLAGS)
                    or body.get('completed_at')!=authority.get('completed_at')):
                raise ValueError('HISTORICAL_ACTION_IDENTITY_MISMATCH')
            ref['binding_status']='HISTORICAL_DIAGNOSTIC_NO_RUN_LINK'
            node['evidence'].append(ref)
            detail = body.get('details')
            if isinstance(detail,str) and len(detail)<=65536:
                detail=json.loads(detail)
            safe(detail)
            layer=detail.get('layer',{}) if isinstance(detail,dict) else {}
            node['historical_action']={
                'binding_status':'HISTORICAL_DIAGNOSTIC_NO_RUN_LINK',
                'status':body['status'],'reason':body.get('reason'),'completed_at':body['completed_at'],
                'failure_layer':{k:layer.get(k) for k in ('status','cannot_confirm','trade_date','target_trade_date','asr_segment_count') if k in layer},
                'is_current_upstream_observation':False,
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            node['historical_action']={'binding_status':'CANNOT_CONFIRM','reason':str(exc)}

    def _a_receipt(self, node, date, result):
        root = Path(self.config['research_receipt_root'])
        receipt, ref = proof(root / ('a-' + date + '.json'), root, kind='A_RECEIPT')
        lane = result.get('_authoritative_payload', {}).get('lanes', {}).get('A', {})
        if (receipt.get('schema_version') != 'v3.macos.research_panel_receipt.v1'
                or receipt.get('target_date') != date or receipt.get('lane') != 'A'
                or not lane.get('sha256') or lane['sha256'] != receipt.get('sha256')
                or lane.get('row_count') != receipt.get('row_count') or lane.get('status') != receipt.get('status')):
            raise ValueError('A_RECEIPT_DISPATCH_BINDING_MISMATCH')
        node['evidence'].append(ref)
        node['business_status'] = receipt['status']
        node['status'] = receipt['status']
        node['business_reason'] = receipt.get('reason')
        node['reason'] = receipt.get('reason')
        node['coverage'] = {k:receipt.get(k) for k in ('row_count','target_count','accepted_count','quarantine_count')}
        node['pit_certified'] = receipt.get('formula', {}).get('pit_certified')
        node['generation_id'] = receipt.get('formula', {}).get('generation_id')

    def _daily(self, date):
        node = {'node_id': 'review_core_daily', 'owner': 'REVIEW_CORE_DAILY', 'status': 'CANNOT_CONFIRM',
                'evidence': [], 'dependencies': [], 'page_status': 'CANNOT_CONFIRM', **FLAGS}
        root = Path(self.config['daily_receipt_root'])
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        if (date > now.strftime('%Y%m%d') or (date == now.strftime('%Y%m%d')
                and self.config.get('daily_slots') and now.strftime('%H%M') < min(self.config['daily_slots']))):
            if not (root / date / 'current.json').exists():
                return {**node, 'status':'PENDING_NOT_DUE','reason':'DAILY_FIRST_SLOT_NOT_REACHED'}
        try:
            pointer, pref = proof(root / date / 'current.json', root, kind='DAILY_CURRENT')
            if pointer.get('schema_version') != 'review_core.macos_daily_current.v1' or pointer.get('trade_date') != date:
                raise ValueError('DAILY_POINTER_IDENTITY_MISMATCH')
            path = Path(pointer['receipt_path'])
            receipt, ref = proof(path, root / date, kind='DAILY_RECEIPT')
            if ref['sha256'] != pointer.get('receipt_sha256') or receipt.get('schema_version') != 'review_core.macos_daily_receipt.v1':
                raise ValueError('DAILY_RECEIPT_SHA_OR_SCHEMA_MISMATCH')
            if (receipt.get('trade_date') != date or not receipt.get('run_id')
                    or any(pointer.get(k) != receipt.get(k) for k in ('run_id', 'attempt_id', 'origin', 'finished_at'))
                    or not receipt.get('attempt_id')):
                raise ValueError('DAILY_RECEIPT_DATE_RUN_ATTEMPT_MISMATCH')
            node.update(status=receipt.get('status', 'CANNOT_CONFIRM'), business_status=receipt.get('status'),
                        reason=receipt.get('reason'), run_id=receipt['run_id'], attempt_id=receipt['attempt_id'],
                        observed_at=receipt.get('finished_at'), execution_phase='COMMITTED', evidence_status='VERIFIED',
                        selector_validation=receipt.get('selector_validation'),
                        network_used=receipt.get('network_used'), asr_execution_count=receipt.get('asr_execution_count'),
                        evidence=[pref, ref])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            node['reason'] = str(exc)
        return node

    def _stage(self, date, nid, descriptor):
        node = {**descriptor, 'status': 'CANNOT_CONFIRM', 'evidence': [], 'page_status': 'CANNOT_CONFIRM',
                'dependency_status':'SEE_ORIGINAL_CONSUMER_EXECUTION_EVIDENCE', **FLAGS}
        try:
            sid = nid.removeprefix('stage:')
            from domains.task_status import _timeline_not_due
            from stage_center.contracts import STAGE_BY_ID
            spec = STAGE_BY_ID[sid]
            if _timeline_not_due({'planned_slot':spec.cutoff.replace(':','')[:4]},date,datetime.now(ZoneInfo('Asia/Shanghai'))):
                return {**node,'status':'PENDING_NOT_DUE','reason':'NOT_DUE'}
            consumer = StageSelectionConsumer(self.config['stage_selection_root'],
                execution_receipt_root=self.config['stage_receipt_root'],
                a_name_pool_root=self.config.get('stage_a_name_pool_root'))
            response = consumer.get(date, sid)
            safe(response)
            node.update(status=response.get('status', 'CANNOT_CONFIRM'), business_status=response.get('status'),
                        selection=response, reason=(response.get('cannot_confirm') or [''])[0])
            path = Path(self.config['stage_receipt_root']) / date / sid / 'receipt.json'
            receipt, ref = proof(path, self.config['stage_receipt_root'], kind='STAGE_RECEIPT')
            if receipt.get('trade_date') != date or receipt.get('stage_id') != sid:
                raise ValueError('STAGE_RECEIPT_IDENTITY_MISMATCH')
            node['evidence'].append(ref)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            node['reason'] = str(exc)
        return node
