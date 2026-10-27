import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def compact():
    path=Path(__file__).parents[1]/'domains/runtime_graph_evidence.py'
    fn=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='compact_authorities')
    ns=dict(json=json,sha=lambda raw:hashlib.sha256(raw).hexdigest())
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
    return ns['compact_authorities']


def test_compact_keeps_authority_states_first_failure_counts_refs_and_terminal_process_split():
    payload={'business_date':'20261027','schema_version':'v4.runtime_graph_authority.v1','authority_identity':{'root':'exact'},
        'descriptors':[{'node_id':'stage:test'}],'nodes':[{'node_id':'stage:test','status':'PARTIAL_WITH_ROWS',
        'reason':'HK_STAGE8_RTDATA_SUBSCRIBE_FAILED:batch=4','execution_phase':'COMPLETED',
        'execution_observation':{'state':'CANNOT_CONFIRM','reason':'PID_ENDED'},'evidence':[{'path':'original','sha256':'a'*64}],
        'selection':{'status':'PARTIAL_WITH_ROWS','selected_hk_rows':10,'markets':{'HK':{'source_rows':90,'requested_rows':100}},
        'unified_rows':[{'raw':'x'*1000}]*10000}}]}
    before=deepcopy(payload);result=compact()(payload)
    node=result['nodes'][0]
    assert payload==before and len(json.dumps(result).encode())<4*1024*1024
    for key in ('status','reason','execution_phase','execution_observation','evidence'):assert node[key]==before['nodes'][0][key]
    assert node['selection']['markets']['HK']=={'source_rows':90,'requested_rows':100}
    assert 'unified_rows' not in node['selection']
    assert result['authority_identity']==before['authority_identity'] and node['detail_api'].endswith('node_ids=stage:test')


def test_actual_8297919_byte_authorities_fit_original_4mib_client_without_source_mutation():
    # Raw actual response is external evidence, excluded from the source capsule.
    path=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027/baseline/ACTUAL_AUTHORITIES_FULL.json')
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()=='8089e88e3236c6e4d61d8e2252c4b7ad8662819ec7e6da04c55558411da97051'
    payload=json.loads(raw);result=compact()(payload);encoded=json.dumps(result,ensure_ascii=False).encode()
    assert len(encoded)<4*1024*1024
    assert len(result['nodes'])==len(payload['nodes'])==46
    for old,new in zip(payload['nodes'],result['nodes']):
        for key in ('node_id','status','reason','business_status','execution_phase','evidence','execution_observation'):
            if key in old:assert new[key]==old[key]
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='8089e88e3236c6e4d61d8e2252c4b7ad8662819ec7e6da04c55558411da97051'
