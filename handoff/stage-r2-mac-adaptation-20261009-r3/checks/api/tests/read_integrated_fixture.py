"""Read the control agent's offline runner fixture without altering its stores."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

lane=Path(__file__).resolve().parents[1]
fixture=Path(sys.argv[1]).resolve()
before={str(p.relative_to(fixture)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in fixture.rglob('*') if p.is_file()}
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module
reader_file=lane/'after/source/actual_api/stage_center/execution_evidence.py'
consumer_file=lane/'after/conditional_api/stage_center/consumer.py'
reader=load('stage_center.execution_evidence',reader_file)
consumer=load('stage_center.consumer',consumer_file)
original=json.loads((fixture/'runner_response.json').read_text())
date,stage=original['trade_date'],original['stage_id']
namespace=original['namespace']
# The existing API factory passes only selection_root. Verify that exact same
# construction finds the corresponding owner receipt without API business edits.
api_consumer=consumer.StageSelectionConsumer(Path(namespace['selection_root']))
assert api_consumer.execution_receipt_root==Path(namespace['receipt_root'])
out=api_consumer.get(date,stage)
hk=out['markets']['HK_CONNECT'];a=out['markets']['A_SHARE'];evidence=out['execution_evidence']
expected=original['markets']['HK_CONNECT']
for key in ['run_id','artifact_id','algorithm_sha256','raw_artifact_sha256','selected_rows','requested_rows','source_rows']:
    assert hk[key]==expected[key],key
assert hk['run_id']==expected['run_id']
assert hk['selected_rows']==len(hk['rows'])==10
assert hk['requested_rows']==hk['source_rows']==695
assert a['rows']==[] and a['run_id'] is None and a['artifact_id'] is None
assert evidence['selection_results']['A_SHARE']['status']=='NO_VERIFIED_RESULT'
assert evidence['selection_results']['HK_CONNECT']['status']=='RESULT_AVAILABLE'
assert evidence['selection_results']['HK_CONNECT']['quote_coverage_ratio']==1.0
assert evidence['receipt_history_binding']=='OWNER_HISTORY_SHA_BOUND'
bound=evidence['selection_artifact_bindings']['HK_CONNECT']
assert bound['status']=='BOUND_TO_VERIFIED_SELECTION_TRIO'
assert bound['artifact_bytes_sha256']==original['selection_artifacts']['HK_CONNECT']['artifact_bytes_sha256']
research=hk['research_source']
assert research['mode']=='CURRENT_DAY_RESEARCH_ONLY' and research['formal_d1_eligible'] is False
assert research['universe_as_of']=='20261008' and research['captured_at']=='2026-10-09T15:38:41+08:00'
assert research['stale_universe'] is True and research['hk_connect_membership_status']=='CANNOT_CONFIRM'
assert research['source_sha256']==original['input_bindings']['HK_CONNECT']['binding_bytes_sha256']
assert hk['source_evidence']==expected['source_evidence']
assert evidence['execution_origin']=='CURRENT_DAY_RESEARCH_REPLAY'
assert evidence['attempt_mode']=='RECOVERY'
assert evidence['natural_verified'] is evidence['execution_verified'] is False
for value in (out,evidence):
    assert value['RESEARCH_ONLY'] is True
    assert all(value[key] is False for key in ['production_allowed','buy_gate_updated','orders_sent'])
for relative,digest in before.items():
    assert hashlib.sha256((fixture/relative).read_bytes()).hexdigest()==digest,relative
projection_file=lane.parents[1]/'test_support/api_projection_reference.py'
projection=load('_available_api_projection_reference',projection_file)
workbench=projection.project_shared_selection(out,limit=10,ordinary_hk_display=True)
assert workbench['execution_evidence']==evidence
assert len(workbench['markets']['HK']['rows'])==10
assert workbench['markets']['HK']['display_mode']=='OBSERVATION_UNVERIFIED'
assert workbench['markets']['HK']['selected_rows'] is None
for key in ['run_id','artifact_id','algorithm_sha256','raw_artifact_sha256']:
    assert workbench['markets']['HK'][key]==hk[key],key
assert workbench['execution_evidence']['selection_results']['HK_CONNECT']['selected_rows']==10
report={'status':'PASS','scope':'OFFLINE_REAL_PRODUCTION_RUNNER_STORE_TO_CURRENT_CANDIDATE_READER_CONSUMER_EXTERNAL_PYTDX_IO_FIXTURE_NOT_MAC',
        'checked_at_utc':datetime.now(timezone.utc).isoformat(),'trade_date':date,'stage_id':stage,
        'market':'HK_CONNECT','run_id':hk['run_id'],'algorithm_sha256':hk['algorithm_sha256'],
        'raw_artifact_sha256':hk['raw_artifact_sha256'],'selection_artifact_bytes_sha256':bound['artifact_bytes_sha256'],
        'selected_rows':10,'requested_rows':695,'source_rows':695,'a_selection_status':a['status'],
        'a_borrowed_hk_identity':False,'input_files_unchanged':True,'checked_input_files':len(before),
        'receipt_history_binding':evidence['receipt_history_binding'],'selection_trio_binding':bound['status'],
        'execution_origin':evidence['execution_origin'],'attempt_mode':evidence['attempt_mode'],
        'execution_verified':False,'natural_verified':False,
        'api_projection_scope':'AVAILABLE_ORIGINAL_FUNCTIONS_NOT_CURRENT_HTTP_SERVICE',
        'api_constructor_scope':'ORIGINAL_SELECTION_ROOT_ONLY_EXACT_BACKFILL_RECEIPT_NAMESPACE',
        'api_projection_preserves_verified_result':True,
        'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (reader_file,consumer_file,projection_file)}}
(fixture/'consumer_response.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
(fixture/'workbench_response.json').write_text(json.dumps(workbench,ensure_ascii=False,indent=2)+'\n')
(fixture/'api_readback_assertions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
