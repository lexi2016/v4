"""Shared binding checks for checkpoint reuse and actual original daily children."""
import hashlib,json
from pathlib import Path
from source_prefix import json_sha,BASIS_KEYS


def runtime_identity(environment):
    # Installation paths are provenance, not numerical semantics.
    return {k:environment.get(k) for k in ('python_version','packages','platform')}


def check_resume(previous,job,config,code_binding):
    if previous.get('status')!='COMPLETE' or previous.get('symbol')!=job['symbol']:raise ValueError('RESUME_STATUS_SYMBOL')
    if previous.get('source_ref')!=job['continuation_ref']:raise ValueError('RESUME_ORIGINAL_SOURCE_BINDING')
    if previous.get('code_binding')!=code_binding:raise ValueError('RESUME_KERNEL_CODE_BINDING')
    if runtime_identity(previous.get('environment_binding',{}))!=runtime_identity(config['environment_binding']):raise ValueError('RESUME_RUNTIME_BINDING')
    # The guard/orchestration repair does not invalidate accepted initialized
    # states. Their original numerical initializer and source loader must match.
    for name in ('bootstrap.py','source_prefix.py'):
        if previous.get('driver_binding',{}).get(name)!=config['driver_binding'].get(name):raise ValueError('RESUME_INITIALIZER_BINDING:'+name)
    completed=previous.get('requested_advances',[]);requested=job.get('advance_refs',[])
    if requested[:len(completed)]!=completed:raise ValueError('RESUME_ADVANCE_CHAIN_CHANGED')
    saved=previous.get('states',[])
    if len(saved)!=len(completed)+1 or saved[0]['asof']!=config['target'] or saved[-1]['asof']!=previous['physical_asof']:raise ValueError('RESUME_SAVED_BOUNDARY')
    return len(completed)


def read_receipt(path,expected_sha=None):
    data=Path(path).read_bytes()
    if expected_sha and hashlib.sha256(data).hexdigest()!=expected_sha:raise ValueError('RESUME_RECEIPT_SHA')
    return json.loads(data)


def check_saved_hashes(receipt):
    for saved in receipt['states']:
        data=Path(saved['path']).read_bytes()
        if len(data)!=saved['bytes'] or hashlib.sha256(data).hexdigest()!=saved['sha256']:raise ValueError('RESUME_STATE_SHA')


def check_daily_parent(parent,child,symbol,parent_ref,expected_count):
    if child['symbol']!=symbol or parent['symbol']!=symbol or child['history_refs']['parent_continuation_ref']['sha256']!=parent_ref['sha256']:raise ValueError('ADVANCE_PARENT_IDENTITY')
    if child['state51'].get('parent_state_sha256')!=json_sha(parent['state51']):raise ValueError('ADVANCE_ORIGINAL51_PARENT_SHA')
    if child['state51']['count']!=parent['state51']['count']+1 or child['state51']['count']!=expected_count or child['component109']['count']!=expected_count:raise ValueError('ADVANCE_ORIGINAL_COUNT')
    day=str(child['daily51']['trade_date'])
    if not (day==child['asof']==str(child['state51']['last_date'])==child['component109']['last_date']) or day<=parent['asof']:raise ValueError('ADVANCE_ORIGINAL_ASOF')
    for key in BASIS_KEYS:
        if child['state51']['binding'].get(key)!=parent['state51']['binding'].get(key):raise ValueError('ADVANCE_SOURCE_BASIS_CHANGED:'+key)


def check_daily_result(state,child):
    count=child['state51']['count'];day=child['asof']
    if state['symbol']!=child['symbol'] or state['count']!=count or state['asof']!=day:raise ValueError('ADVANCE_RESULT_BOUNDARY')
    if state['native_state']['count']!=count or state['native_state']['last_date']!=day:raise ValueError('ADVANCE_NATIVE_RESULT_BOUNDARY')
    for component in (state['component109'],state['component109']['foundation'],state['component109']['n_score']):
        if component['count']!=count or component['last_date']!=day:raise ValueError('ADVANCE_COMPONENT_RESULT_BOUNDARY')
