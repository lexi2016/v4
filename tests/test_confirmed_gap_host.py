import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infrastructure import research_workbench_host as host
from ops.kb_confirmed_gap import CONTRACT, FIELD_TYPES


def ref(path, data):
    path.write_bytes(data)
    return {'path':str(path), 'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)}


def test_host_binds_paired_gap_rows_and_rejects_cross_role_values(tmp_path):
    policy=json.loads(CONTRACT.read_text());policy_ref=ref(tmp_path/'policy.json',CONTRACT.read_bytes())
    source_contracts={name:ref(tmp_path/Path(name).name,(Path(__file__).resolve().parents[1]/name).read_bytes())
                      for name in policy['source_contracts']}
    sources={name:ref(tmp_path/(name+'.json'),b'{}') for name in ('rebuild','components')}
    receipts={name:ref(tmp_path/(name+'_receipt.json'),b'{}') for name in ('rebuild','components','diagnostics')}
    original_diagnostics=ref(tmp_path/'original_diag',b'original')
    gen='a'*64;input_sha='b'*64;snapshot='c'*64;symbol='002865.SZ'
    old_gate=ref(tmp_path/'old_gate.json',json.dumps({'status':'PASS_RELOCATED_SOURCE_GATE'}).encode())
    relocation=ref(tmp_path/'relocation.json',b'{}')
    required={'ops/research_panel_qfq.py','ops/kb_signal_authority.py','ops/kb_confirmed_gap.py',
              'ops/kb_panel_rebuild_brick.py','ops/kb_panel_signal_components.py'}
    code_refs={name:{'sha256':'9'*64} for name in required}
    new_gate=ref(tmp_path/'new_gate.json',json.dumps({'status':'PASS_RELOCATED_SOURCE_GATE','matches_frozen_input_sha256':True,
        'prior_source_gate':old_gate,'canonical_input_sha256':input_sha,'snapshot':{'sha256':snapshot},
        'relocation_ref':relocation,'source_code_refs':code_refs}).encode())
    meta={'candidate_generation':gen,'symbol':symbol,'confirmed_gap_contract_sha256':policy_ref['sha256'],
          'source_generation':'d'*64,'source_input_sha256':input_sha,'freeze_snapshot_sha256':snapshot,
          'calendar_sha256':None,'calendar_status':'CANNOT_CONFIRM','diagnostic_keys':policy['diagnostic_keys']}
    diag=json.dumps(dict.fromkeys(policy['diagnostic_keys']))
    sidecar=pa.table({'ts_code':[symbol,symbol],'trade_date':['20261029','20261030'],
        'diagnostics_json':[diag,diag],'prefix_input_sha256':['e'*64,'f'*64]}).replace_schema_metadata(
        {b'v4.a_share.kb_gap_diagnostics.v1':json.dumps(meta).encode()})
    sink=pa.BufferOutputStream();pq.write_table(sidecar,sink);sidecar_ref=ref(tmp_path/'sidecar.parquet',sink.getvalue().to_pybytes())
    types={'string':pa.string(),'bool':pa.bool_(),'double':pa.float64(),'int32':pa.int32()}
    def role(name, changed=False):
        columns={'ts_code':pa.array([symbol,symbol]),'trade_date':pa.array(['20261029','20261030'] if name=='selector' else [20261029,20261030]),
                 'kb_rebuild':pa.array([None,True],type=pa.bool_())}
        for field,kind in FIELD_TYPES.items():
            values=[None,None]
            if field=='kb_brick_trend':values=[None,'GREEN' if changed else 'RED']
            columns[field]=pa.array(values,type=types[kind])
        sink=pa.BufferOutputStream();pq.write_table(pa.table(columns),sink)
        return ref(tmp_path/(name+'.parquet'),sink.getvalue().to_pybytes())
    roles={name:{'source_full':role(name)} for name in ('selector','backtest')}
    gap={'contract':policy_ref,'source_contracts':source_contracts,'diagnostics':sidecar_ref,'source_diagnostics':original_diagnostics,
         'source_candidates':sources,'source_receipts':receipts,'prior_source_gate':old_gate,'calendar_status':'CANNOT_CONFIRM','calendar_sha256':None}
    binding={'symbol':symbol,'rows':2,'candidate_generation':gen,'source_generation':'d'*64,'source_input_sha256':input_sha,
             'confirmed_gap':gap,'display_projection':{'roles':roles},'source_gate_receipt':new_gate,'source_relocation':relocation}
    identity={'confirmed_gap_contract_sha256':policy_ref['sha256'],'snapshot_sha256':snapshot,
        'source_sha256':{**{name:value['sha256'] for name,value in source_contracts.items()},**{name:'9'*64 for name in required}},
        'confirmed_gap_source_sha256':{'rebuild':sources['rebuild']['sha256'],'components':sources['components']['sha256'],
                                        'diagnostics':original_diagnostics['sha256']}}
    assert host.checked_confirmed_gap(binding,identity)['diagnostics_sha256']==sidecar_ref['sha256']
    roles['backtest']['source_full']=role('backtest',changed=True)
    with pytest.raises(ValueError,match='ROLE_VALUES_CONFLICT:kb_brick_trend'):
        host.checked_confirmed_gap(binding,identity)
