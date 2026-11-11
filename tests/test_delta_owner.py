import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from ops import research_panel_qfq as owner
from ops import research_panel_logical as logical
from ops.research_panel_delta import run_delta


def write(path,value):
    owner._json(path,value)
    return dict(path=str(path),sha256=owner.sha(path))


@pytest.fixture
def fixture(tmp_path):
    schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.int64()),('close',pa.float64()),
        ('signal',pa.int8()),('name',pa.string())])
    codes=['000001.SZ','002152.SZ','002717.SZ','688053.SH']
    def raw(code,last):
        days=list(range(1,last+1));close=np.array(days,dtype=float)+10
        return pd.DataFrame(dict(ts_code=code,trade_date=days,open=close,high=close+.2,
            low=close-.2,close=close,vol=np.ones(len(days))*100,amount=np.ones(len(days))*1000))
    oldraw={c:raw(c,2) for c in codes[:-1]}
    newraw={c:raw(c,2 if c=='002717.SZ' else 3) for c in codes}
    def numerical(code,item,target,driver):
        frame=newraw[code]
        cash=.1 if code=='002152.SZ' else 0
        return pd.DataFrame(dict(ts_code=code,trade_date=frame.trade_date,close=frame.close-np.where(frame.trade_date.lt(3),cash,0),signal=(frame.trade_date%2).astype('int8'),name=None))
    snapshot=dict(asof_date=3,convention='fixture',symbols={c:dict(raw_kind='new',raw_files=[],events=([dict(ex_date=3,a=1.,b=-.1,volume_a=1.)] if c=='002152.SZ' else []),publish_roles=['selector','backtest']) for c in codes},accepted_target_date_floor=2)
    old_snapshot=dict(asof_date=2,symbols={c:dict(raw_kind='old',events=[],publish_roles=['selector','backtest']) for c in oldraw})
    old_ref=write(tmp_path/'old_snapshot.json',old_snapshot)
    snapshot_ref=write(tmp_path/'new_snapshot.json',snapshot)
    old_meta=dict(adjustment_snapshot=old_ref,generation_id='old',generation_manifest_path=str(tmp_path/'old_receipt.json'),driver_sha256='driver',formula_sha256='formula',user_formula_sha256='user',field_contract_sha256='contract')
    write(tmp_path/'old_receipt.json',{'status':'READY'})
    oldrows=[dict(ts_code=c,trade_date=d,close=float(d+10),signal=d%2,name=None) for c in oldraw for d in [1,2]]
    oldrows.append(dict(ts_code='00005.HK',trade_date=2,close=None,signal=None,name='HK'))
    oldtable=pa.Table.from_pylist(oldrows,schema=schema).replace_schema_metadata({logical.META:json.dumps(old_meta).encode()})
    currents={r:tmp_path/f'old_{r}.parquet' for r in ['selector','backtest']}
    pointers={r:tmp_path/f'{r}.txt' for r in currents}
    for role,p in currents.items():
        logical.physical.write_table(oldtable,p,row_group_size=3);pointers[role].write_text(str(p)+'\n')
    baseline={r:owner.sha(p) for r,p in currents.items()}
    identity=dict(input_sha256=owner.canonical_sha(snapshot),driver_sha256='driver',formula_sha256='formula',user_formula_sha256='user',field_contract_sha256='contract',turnover_input_sha256='turnover')
    run=tmp_path/'qfq_new';run.mkdir()
    meta=dict(generation_id='new',generation_manifest_path=str(run/'candidate_receipt.json'),adjustment_snapshot=snapshot_ref,asof_date=3,baseline_panel_sha256=baseline,**identity,**owner.FLAGS)
    driver=SimpleNamespace(CONTRACT_PROVENANCE_FIELD_DEFAULTS={'field_contract_version':'fixture'},
        validate_new_selector_rows=lambda *a:{'status':'PASS'},
        build_table_for_schema=lambda f,s,r:(pa.Table.from_pandas(f[s.names],schema=s,preserve_index=False),[]))
    q=dict(vars(owner));calls=[]
    q['resolved_raw_history']=lambda code,item,*args: (oldraw if item['raw_kind']=='old' else newraw)[code].copy()
    def compute(*args):calls.append(args[0]);return numerical(*args)
    q['rebuild_symbol']=compute
    q['generation_identity']=lambda s,*a:{**{k:v for k,v in identity.items() if k!='turnover_input_sha256'},'input_sha256':owner.canonical_sha(s)}
    q['load_snapshot']=lambda *a:copy.deepcopy(snapshot)
    q['turnover_watch_unchanged']=lambda *a:True
    q['factor_cache_identity']=lambda *a:'fixture factor'
    q['verify_release_gate']=lambda *a:None  # Publication mechanics fixture, not a release-acceptance claim.
    c=dict(target=3,snapshot=snapshot,meta=meta,currents=currents,schemas={r:schema for r in currents},
        run_dir=run,driver=driver,data_root=tmp_path,contracts={r:old_meta for r in currents},
        old_symbols={r:set(oldtable['ts_code'].to_pylist()) for r in currents},baseline_hashes=baseline,
        candidates={r:tmp_path/r/'current.logical' for r in currents},retained_history=None,retained_history_codes=set(),
        turnover=SimpleNamespace(apply_target=lambda code,frame:frame,verify_binding=lambda:None),workers=2,
        run_id='new',snapshot_file=Path(snapshot_ref['path']),driver_path=tmp_path/'driver.py',formula_path=tmp_path/'formula.py',
        contract_csv=tmp_path/'contract.csv',identity=identity,pointers=pointers,frozen_baseline=owner.baseline_binding(pointers),
        inherited_quarantine={},publish=False,baseline_file=tmp_path/'baseline.json',readiness=dict(turnover_watch=['fixture'],factor_cache_identity='fixture factor'),
        expected={r:p.read_bytes() for r,p in pointers.items()},journal=tmp_path/'journal.json')
    return SimpleNamespace(q=q,c=c,raw=newraw,compute=numerical,calls=calls,schema=schema,pointers=pointers,tmp=tmp_path)


def test_original_owner_writes_only_delta_and_idempotent_resume(fixture):
    f=fixture;result=run_delta(f.q,f.c)
    assert result['status']=='CANDIDATE_READY'
    assert sorted(f.calls)==['000001.SZ','002152.SZ','688053.SH']
    assert result['dependency_classifications']['002717.SZ']=='UNCHANGED'
    for role,path in f.c['candidates'].items():
        table=logical.parquet.read_table(path)
        assert len(table)==12
        expected=[]
        for code in f.raw:expected.extend(f.compute(code,None,3,None).to_dict('records'))
        expected.append(dict(ts_code='00005.HK',trade_date=2,close=None,signal=None,name='HK'))
        expected=pa.Table.from_pylist(expected,schema=f.schema)
        left=table.to_pandas().sort_values(['ts_code','trade_date']).reset_index(drop=True)
        right=expected.to_pandas().sort_values(['ts_code','trade_date']).reset_index(drop=True)
        pd.testing.assert_frame_equal(left,right,check_exact=True)
        assert result['counts'][role]['appended_rows']==5
        assert result['counts'][role]['revised_rows']==2
        blocks=logical.closure(path)
        assert blocks[0]['path']==str(f.c['currents'][role])
        assert sum(block['rows'] for block in blocks[1:])==7
        assert not (f.c['run_dir']/('current_'+role+'_buckets')).exists()
    before={p:owner.sha(p) for p in f.tmp.rglob('*.parquet')}
    calls=list(f.calls)
    again=run_delta(f.q,f.c)
    assert f.calls==calls and again['new_delta_file_bytes']==0
    assert before=={p:owner.sha(p) for p in f.tmp.rglob('*.parquet')}
    assert not (f.c['run_dir']/'symbol_checkpoints').exists()


def test_one_role_failure_never_changes_current_and_resumes(fixture):
    f=fixture;before={r:p.read_bytes() for r,p in f.pointers.items()};original=f.q['_write']
    def fail(path,payload):
        if Path(path)==f.c['candidates']['backtest']:raise OSError('injected second-role failure')
        return original(path,payload)
    f.q['_write']=fail;f.c['publish']=True
    with pytest.raises(OSError,match='second-role'):run_delta(f.q,f.c)
    assert before=={r:p.read_bytes() for r,p in f.pointers.items()}
    assert json.loads((f.c['run_dir']/'stage_status.json').read_text())['status']=='FAILED'
    f.q['_write']=original;f.c['publish']=False
    result=run_delta(f.q,f.c)
    assert result['new_delta_file_bytes']==0


@pytest.mark.parametrize('kind',['source','baseline'])
def test_source_or_baseline_drift_refuses_publication(fixture,kind):
    f=fixture;f.c['publish']=True;original=f.q['check_baseline']
    if kind=='source':f.q['load_snapshot']=lambda *a:{'changed':True}
    else:f.q['check_baseline']=lambda *a:(_ for _ in ()).throw(ValueError('CAS_CONFLICT'))
    before={r:p.read_bytes() for r,p in f.pointers.items()}
    with pytest.raises(ValueError):run_delta(f.q,f.c)
    assert before=={r:p.read_bytes() for r,p in f.pointers.items()}


def test_delta_resume_rejects_tampered_descriptor_and_counts(fixture):
    f=fixture;run_delta(f.q,f.c)
    path=next((f.c['run_dir']/'delta_checkpoints').glob('000001.SZ.*.json'))
    saved=json.loads(path.read_text());saved['logical_rows']['selector']+=1;path.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='LOGICAL_COUNTS'):run_delta(f.q,f.c)


def test_existing_original_partial_is_read_without_copy(fixture):
    f=fixture;code='000001.SZ';path=f.tmp/'original_partial.parquet'
    table=pa.Table.from_pandas(f.compute(code,None,3,None),preserve_index=False)
    logical.physical.write_table(table,path);before=path.read_bytes()
    f.c['recovered']={code:dict(artifact=dict(path=str(path),sha256=owner.sha(path)))}
    run_delta(f.q,f.c)
    assert code not in f.calls and path.read_bytes()==before
    assert not (f.c['run_dir']/'symbol_checkpoints').exists()


def test_new_stock_respects_original_role_start(fixture):
    f=fixture;f.c['role_start']={role:2 for role in f.c['currents']};run_delta(f.q,f.c)
    table=logical.parquet.read_table(f.c['candidates']['selector'],filters=[('ts_code','=','688053.SH')])
    assert table['trade_date'].to_pylist()==[2,3]


def test_actual_pair_lease_and_single_generation_pin_closure(fixture):
    from ops import research_storage_pair as pair
    from ops import research_storage_retention as retention
    f=fixture;data=f.tmp
    ps=pair.pointers(data)
    for role,p in ps.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(f.c['expected'][role])
    f.c.update(pointers=ps,expected={r:p.read_bytes()for r,p in ps.items()},frozen_baseline=owner.baseline_binding(ps),publish=True,
        journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json')
    f.c['meta'].update(schema='a_share_qfq_panel_v1',snapshot_file_sha256=f.c['meta']['adjustment_snapshot']['sha256'],price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',convention='fixture')
    result=run_delta(f.q,f.c);assert result['status']=='READY'
    root=data/'paired';manifest=pair.commit(root,data,f.c['candidates'],keep_completed=1)
    assert json.loads((root/'current.json').read_text())['rollback'] is None
    source=write(data/'pinned_source.py',{'small':'fixture'})
    inv=write(data/'pins.json',dict(schema='v4_research_managed_pin_inventory_v1',status='COMPLETE_REVIEWED',
        consumer_scopes={name:'REVIEWED_NO_MANAGED_PINS'for name in retention.CONSUMER_SCOPES},pins=[],source_bindings=[source],expected_main_app_root=str(data)))
    policy=dict(managed_pin_inventory=inv,data_root=str(data),pointers={r:str(p)for r,p in ps.items()},keep_completed=1)
    protected,_,_=retention.managed_runtime_projection(policy,[],[],[dict(run=f.c['run_dir'],status=result)],{})
    for path in f.c['candidates'].values():
        for block in logical.closure(path):
            assert Path(block['path']) in protected
            assert all(Path(ref['path'])in protected for ref in block.get('metadata_refs',[]))
    with pair.acquire(root) as binding:
        assert binding.paths==f.c['candidates'];binding.assert_open()
        base=f.c['currents']['selector'];base.write_bytes(base.read_bytes()+b'drift')
        with pytest.raises(ValueError,match='LOGICAL_BLOCK_CHANGED'):binding.assert_open()


def test_factor_provenance_changes_do_not_invalidate_unchanged_math(fixture):
    from ops.research_panel_delta import _prepare
    f=fixture;code='002717.SZ';old=json.loads(Path(next(iter(f.c['contracts'].values()))['adjustment_snapshot']['path']).read_bytes())
    event=dict(ex_date=1,a=1.,b=0.,volume_a=1.)
    old['symbols'][code]['events']=[{**event,'receipt':'old'}]
    f.c['snapshot']['symbols'][code]['events']=[{**event,'receipt':'new'}]
    frames={role:{code:logical.physical.read_table(path,filters=[('ts_code','=',code)])}for role,path in f.c['currents'].items()}
    rules={key:f.c['meta'][key] for key in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    value=_prepare(f.q,f.c,code,frames,old,f.c['schemas'],rules)
    assert value['kind']=='UNCHANGED' and value['computed'] is None and not f.calls


def test_actual_rule_revision_never_reuses_suspended_old_math(fixture):
    from ops.research_panel_delta import _prepare
    f=fixture;code='002717.SZ';old=json.loads(Path(next(iter(f.c['contracts'].values()))['adjustment_snapshot']['path']).read_bytes())
    frames={role:{code:logical.physical.read_table(path,filters=[('ts_code','=',code)])}for role,path in f.c['currents'].items()}
    rules={key:f.c['meta'][key] for key in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')};rules['formula_sha256']='actual_new_rule'
    value=_prepare(f.q,f.c,code,frames,old,f.c['schemas'],rules)
    assert value['kind']=='RULE_REVISION' and value['computed'] is not None and f.calls==[code]


def test_original_authority_target_date_audit_reads_logical_panel(fixture):
    import ast
    source=Path(owner.__file__).with_name('macos_research_panel_daily_authority.py')
    node=next(n for n in ast.parse(source.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='_parquet_max_date')
    namespace=dict(Path=Path,SnapshotGateError=RuntimeError)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
    f=fixture;run_delta(f.q,f.c)
    assert namespace['_parquet_max_date'](f.c['candidates']['selector'])==3


@pytest.mark.parametrize('changed',['factor','turnover','quarantine','recovery'])
def test_original_final_source_revalidation_refuses_before_any_pointer(fixture,changed):
    f=fixture;f.c['publish']=True;before={r:p.read_bytes()for r,p in f.pointers.items()}
    f.c['readiness']=dict(turnover_watch=['bound'],factor_cache_identity='bound-factor')
    f.q['turnover_watch_unchanged']=lambda *a:changed!='turnover'
    f.q['factor_cache_identity']=lambda *a:'CHANGED'if changed=='factor'else'bound-factor'
    artifact=write(f.tmp/'frozen-source.json',dict(bound=True))
    if changed=='quarantine':f.c['inherited_quarantine']={artifact['path']:artifact}
    if changed=='recovery':
        cp=f.tmp/'partial.parquet';logical.physical.write_table(pa.Table.from_pandas(f.compute('000001.SZ',None,3,None),preserve_index=False),cp)
        f.c['checkpoint_resume']=write(f.tmp/'recovery.json',dict(source_core=artifact,original_snapshot=dict(path=str(f.c['snapshot_file']),sha256=owner.sha(f.c['snapshot_file']))))
        f.c['recovered']={'000001.SZ':dict(read_only_original=True,artifact=dict(path=str(cp),sha256=owner.sha(cp)))}
        f.q['_partial_checkpoint_file']=lambda item:cp
    original=f.q['rebuild_symbol']
    def compute(*args):
        value=original(*args)
        if changed in ['quarantine','recovery']:Path(artifact['path']).write_text('drift')
        return value
    f.q['rebuild_symbol']=compute
    with pytest.raises((ValueError,owner.QfqGateError)):
        run_delta(f.q,f.c)
    assert {r:p.read_bytes()for r,p in f.pointers.items()}==before
    assert json.loads((f.c['run_dir']/'stage_status.json').read_text())['status']=='FAILED'
    assert not f.c['journal'].exists()


def test_cooperative_stop_drains_and_seals_submitted_results(fixture):
    f=fixture;f.c['workers']=1;original=f.q['rebuild_symbol']
    def compute(*args):
        (f.c['run_dir']/'STOP_REQUESTED').touch()
        return original(*args)
    f.q['rebuild_symbol']=compute
    before={r:p.read_bytes()for r,p in f.pointers.items()}
    with pytest.raises(InterruptedError,match='STOP_REQUESTED_DRAINED'):run_delta(f.q,f.c)
    checkpoints=list((f.c['run_dir']/'delta_checkpoints').glob('*.json'))
    assert checkpoints
    for path in checkpoints:
        record=json.loads(path.read_bytes())
        for value in record['roles'].values():assert owner.sha(Path(value['artifact']['path']))==value['artifact']['sha256']
    progress=json.loads((f.c['run_dir']/'progress.json').read_bytes())
    assert progress['stage']=='DRAINED' and progress['completed']==len(checkpoints)and progress['maximum_inflight']<=2
    assert before=={r:p.read_bytes()for r,p in f.pointers.items()}
