"""Compare the actual two freeze validators with the same synthetic records."""
import ast
from copy import deepcopy
from datetime import date, datetime, time
from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from zoneinfo import ZoneInfo

root=Path(__file__).resolve().parent
candidate=root/'candidate'
sys.path.insert(0,str(candidate))
from freeze_gate_candidate import validate, time_at
zip_path=next((root/'intake').glob('*R2_4*.zip'))
zip_digest=sha256(zip_path.read_bytes()).hexdigest()
assert zip_digest=='d3b644f0d49c97f39cb768bd0a54a313dcd6640decf22cab58a6a547bf76b7a6'
with ZipFile(zip_path) as z:
    assert z.testzip() is None
    spec_raw=z.read('P515_GEMINI_001219_V1_PROBABILITY_EXTENSION_MACHINE_SPEC_R2_4.json')
    peer_raw=z.read('run_r2_4_synthetic_prob_spec_tests.py')
spec_sha=sha256(spec_raw).hexdigest()
peer_sha=sha256(peer_raw).hexdigest()
assert spec_sha=='95b3a68b2e5250b5c831408dbb707bee94b2fca4e1a88a5842318b399027e27b'
assert peer_sha=='3d8e26f92e2aeb0cf7d0cf2714c6ee65d9513a95923c161f19774ad22c791be5'
spec=json.loads(spec_raw)
tree=ast.parse(peer_raw)
funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef)
       and n.name in {'_parse_iso_dt','validate_freeze_and_row_clocks'}]
assert {n.name for n in funcs}=={'_parse_iso_dt','validate_freeze_and_row_clocks'}
peer={'date':date,'datetime':datetime,'time':time,'SHANGHAI':ZoneInfo('Asia/Shanghai')}
exec(compile(ast.Module(body=funcs,type_ignores=[]),str(zip_path)+'::gemini_clock_validator','exec'),peer)
peer_validate=peer['validate_freeze_and_row_clocks']
source=candidate/'test_cf01_gemini_clock.py'
nodes=[]
for n in ast.parse(source.read_text()).body:
    if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BASE' for t in n.targets):
        break
    nodes.append(n)
env={'__file__':str(source)}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),env)
base=env['fixture']()
prep=env['record_prep']()
TS=env['TS']


def gemini_projection(record):
    """Project after Codex integrity validation in a real caller; no new timestamps."""
    out=deepcopy(record)
    for h in out['history_rows']:
        h['pb_mature_at']=h['result_pb']['mature_at']
        h['mother_mature_at']=h['result_mother']['mature_at']
        h['available_at']=max((h['available_at'],h['result_pb']['acquired_at'],
                               h['result_mother']['acquired_at']),key=time_at)
    for row in out['forward_rows']:
        if row['status']=='PAIRED_FROZEN':
            row['input']['generated_at']=row['generated_at']
            row['outputs']['frozen_at']=row['output_frozen_at']
    return out


def codex(record):
    try:
        return {'valid':validate(record),'reason':'OK'}
    except ValueError as e:
        return {'valid':False,'reason':str(e)}


def change(path,value,seal=False):
    record=deepcopy(base)
    item=record
    for key in path[:-1]:
        item=item[key]
    item[path[-1]]=value
    if seal:
        env['seal_history'](record)
        for arm in ('A','B'):
            record['forward_rows'][0]['outputs'][arm]['history_manifest_sha256']=record['history_manifest']['sha256']
    return record

cases=[
 ('preparation_null_F',prep,True),
 ('master_valid_synthetic_two_clock',base,True),
 ('model_freeze_equals_global_F',change(['actual_freezes','model','frozen_at'],base['global_F']),False),
 ('mother_formed_equals_global_F',change(['forward_rows',0,'mother_formed_at'],base['global_F']),False),
 ('output_equals_next_evaluation_bar',change(['forward_rows',0,'output_frozen_at'],base['forward_rows'][0]['first_evaluation_bar_at']),False),
 ('source_acquired_after_generation',change(['forward_rows',0,'input','available_at'],TS('25','17:21')),False),
 ('result_acquisition_after_seal',change(['history_rows',0,'result_pb','acquired_at'],TS('19','16:01'),True),False),
 ('historical_ref_missing',change(['forward_rows',0,'history_refs'],['SYN-NOT-SEALED']),False),
]
late=change(['history_rows',0,'result_mother','mature_at'],TS('23'))
late['history_rows'][0]['result_mother']['acquired_at']=TS('24')
env['seal_history'](late)
for arm in ('A','B'):
    late['forward_rows'][0]['outputs'][arm]['history_manifest_sha256']=late['history_manifest']['sha256']
cases.append(('CF01_parent_mature_after_seal_before_current_D',late,False))
results=[]
for name,record,expected in cases:
    lhs=codex(record)
    rhs=peer_validate(gemini_projection(record),spec=spec)
    assert lhs['valid'] is expected and rhs['valid'] is expected,(name,lhs,rhs)
    results.append({'test':name,'expected_accept':expected,'codex':lhs,'gemini_R2_4':rhs})
row=base['forward_rows'][0]
wire={'global_F':base['global_F'],'mother_formed_at':row['mother_formed_at'],
      'D_cutoff':row['D_cutoff'],'input_available_at':row['input']['available_at'],
      'generated_at':row['generated_at'],'output_frozen_at':row['output_frozen_at'],
      'first_evaluation_bar_at':row['first_evaluation_bar_at']}
peer_result=peer_validate(wire,spec=spec)
assert peer_result=={'valid':True,'reason':'OK_ROW_CLOCKS'}
results.append({'test':'explicit_two_clock_wire_row_gemini_entrypoint','expected_accept':True,'gemini_R2_4':peer_result})
receipt={'status':'PASS','tests_passed':len(results),'spec_drive_id':'16RkQawHzBwSuP0of81ckgITKqn6zJ3D1','spec_sha256':spec_sha,
         'peer_zip_drive_id':'1LIGkDdPbL-t2ohAcHRcX3IwpGv5QyrEL','peer_zip_sha256':zip_digest,'peer_function_sha256':peer_sha,
         'runner_gate_sha256':sha256((candidate/'freeze_gate_candidate.py').read_bytes()).hexdigest(),
         'peer_scope':'exact emitted Gemini clock validation function; not the probability/evaluation suite or operational integration',
         'projection':'nested generated_at and frozen_at aliases are derived from flat CODEX clocks; available_at is max(prefix/PB/mother acquisitions); Codex validates member/evidence hashes before interface',
         'new_fit_count':0,'new_prediction_count':0,'test_cases':results}
print(json.dumps(receipt,ensure_ascii=False,indent=2))
