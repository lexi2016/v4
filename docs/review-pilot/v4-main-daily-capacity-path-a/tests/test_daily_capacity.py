import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ops import research_daily_capacity as capacity


@pytest.fixture
def setup_plan(tmp_path):
    source = tmp_path/'source'
    source.write_bytes(b'original')
    # Synthetic enforceable ceilings only. This does not approve production caps.
    limits = dict(fixed_bytes=64*1024**2,per_symbol_bytes=8192,per_changed_row_bytes=4096,
                  max_file_bytes=64*1024**2,max_symbols=6000,max_changed_rows=12000,max_revised_symbols=2)
    phases = {phase:dict(limits) for phase in capacity.PHASES}
    review = tmp_path/'review.json'
    review.write_bytes(capacity.encoded(dict(schema='v4.daily_incremental_limits_review.v1',status='PASS',phase_limits=phases)))
    policy = dict(governance=dict(incremental_capacity=dict(schema=capacity.SCHEMA,enabled=True,phases=phases,
                         reviewed_limits=dict(path=str(review),sha256=capacity.file_reference(review)['sha256']))))
    args = dict(target=20261123,scope=['000001.SZ'],source_identity={'raw':'same'},
                references=[capacity.file_reference(source)],changed_rows=1,
                classifications={'000001.SZ':'APPEND'})
    return policy,args,source


def test_automatic_scope_deterministic_exact_sha_and_input_change(setup_plan):
    policy,args,source = setup_plan
    first = capacity.build_plan(policy,'qfq',**args)
    assert first == capacity.build_plan(policy,'qfq',**args)
    assert first['predicted_bytes'] == 64*1024**2+8192+4096
    capacity.validate_plan(first,policy=policy,phase='qfq',target=20261123)
    source.write_bytes(b'changed')
    with pytest.raises(capacity.CapacityProofError,match='INPUT_CHANGED'):
        capacity.validate_plan(first,policy=policy)


def test_one_byte_write_boundary_before_effect(setup_plan):
    policy,args,source = setup_plan
    plan = capacity.build_plan(policy,'qfq',**args)
    limit = plan['limits']['max_file_bytes']
    with capacity.write_scope(plan):
        assert capacity.incoming_bytes(limit) == limit
        assert capacity.incoming_bytes(limit-1) == limit
        with pytest.raises(capacity.CapacityProofError,match='SINGLE_WRITE_BOUND'):
            capacity.incoming_bytes(limit+1)
    assert source.read_bytes() == b'original'


@pytest.mark.parametrize('kind',['RULE_REVISION','NEW_OR_MISSING_HISTORY'])
def test_large_scope_rejected_without_any_output(setup_plan,kind):
    policy,args,source = setup_plan
    args['classifications'] = {'000001.SZ':kind}
    before = set(source.parent.iterdir())
    with pytest.raises(capacity.CapacityProofError,match='FULL_REBUILD_REQUIRED'):
        capacity.build_plan(policy,'qfq',**args)
    assert set(source.parent.iterdir()) == before


def test_revised_limit_cannot_silently_expand_claim(setup_plan):
    policy,args,_ = setup_plan
    args['revised_symbols'] = 3
    with pytest.raises(capacity.CapacityProofError,match='FULL_REBUILD_REQUIRED'):
        capacity.build_plan(policy,'qfq',**args)


def test_plan_tamper_and_policy_change_fail_closed(setup_plan):
    policy,args,_ = setup_plan
    plan = capacity.build_plan(policy,'qfq',**args)
    bad = copy.deepcopy(plan);bad['predicted_bytes'] -= 1
    with pytest.raises(capacity.CapacityProofError,match='DIGEST_CONFLICT'):
        capacity.validate_plan(bad)
    changed = copy.deepcopy(policy);changed['extra'] = True
    with pytest.raises(capacity.CapacityProofError,match='POLICY_CONFLICT'):
        capacity.validate_plan(plan,policy=changed)


def test_missing_review_cannot_enable_smaller_forecast(setup_plan):
    policy,args,_ = setup_plan
    del policy['governance']['incremental_capacity']['reviewed_limits']
    with pytest.raises(capacity.CapacityProofError,match='LIMIT_REVIEW_REQUIRED'):
        capacity.build_plan(policy,'qfq',**args)


def test_product_unknown_writer_refused_before_reader_or_admission(setup_plan):
    policy,_,_ = setup_plan
    context = SimpleNamespace(unchanged=lambda:pytest.fail('must fail before Reader scan'))
    for phase in ('daily_product','top200'):
        with pytest.raises(capacity.CapacityProofError,match='WRITER_COVERAGE_NOT_PROVEN'):
            capacity.product_plan(policy,context,phase)


def test_bootstrap_refused_before_reader_scan(setup_plan):
    policy,_,_ = setup_plan
    with pytest.raises(capacity.CapacityProofError,match='BOOTSTRAP'):
        capacity.product_plan(policy,None,'daily_product',history_dates=['20261120'])


def test_resident_same_roots_and_inode_dedup(tmp_path):
    from ops import research_storage_governance as governance
    root=tmp_path/'owned';root.mkdir();file=root/'one';file.write_bytes(b'a'*4097)
    duplicate=root/'two';duplicate.hardlink_to(file)
    state={'resident_baseline_paths':[str(root)],'tasks':{'old':dict(category='ordinary',billing_paths=[str(root),str(file)])}}
    config={'accounting_roots':{'ordinary':[str(root)]}}
    # Actual root discovery is separate and gets its own production dependency checks.
    original=governance.ordinary_resident_paths
    governance.ordinary_resident_paths=lambda config:[]
    try:
        assert capacity.ordinary_resident_bytes(governance,config,state)==governance.billing_bytes(file)
    finally:governance.ordinary_resident_paths=original


def test_begin_creation_after_claim_checks_before_write(monkeypatch,tmp_path):
    from ops import research_storage_retention as retention
    root=tmp_path/'run';root.mkdir();formal=tmp_path/'formal';formal.mkdir();owned=tmp_path/'owned'
    policy={'future_reclamation':True,'run_root':str(root),'formal_roots':{'selector':str(formal)},'activation':'fixture'}
    monkeypatch.setattr(retention,'_ownership_root',lambda p:owned)
    monkeypatch.setattr(retention,'pointer_state',lambda p:{'selector':'fixture'})
    writes=[]
    monkeypatch.setattr(retention,'atomic_json',lambda *a:writes.append(a))
    class Claim:
        def watch(self,path):pass
        def checkpoint(self,*,incoming):
            assert incoming>0
            raise retention.RetentionError('SPACE_BLOCKED')
        def observe(self,path):pytest.fail('must not observe unwritten bytes')
    with pytest.raises(retention.RetentionError,match='SPACE_BLOCKED'):
        retention.begin_creation(policy,claim=Claim())
    assert not writes and not owned.exists()


def test_locked_probe_reads_real_registry_without_reacquiring_or_writing(setup_plan,tmp_path,monkeypatch):
    from ops import research_storage_governance as governance
    policy,_,_=setup_plan
    run=tmp_path/'run';run.mkdir();native=tmp_path/'native';native.mkdir();(native/'one.day').write_bytes(b'x'*32)
    ledger=tmp_path/'ledger';ledger.mkdir()
    policy.update(data_root=str(tmp_path),run_root=str(run))
    policy['governance'].update(enabled=True,pool_id='isolated',pool_identity_verified=True,registry_root=str(ledger))
    old={str(index):dict(state='SPACE_BLOCKED',category='ordinary',reserved_bytes=1024*1024,
        written_bytes=0,directory=str(run/f'old-{index}')) for index in range(8)}
    path=ledger/'registry.json';path.write_bytes(capacity.encoded(dict(schema=governance.SCHEMA,pool_id='isolated',tasks=old,resident_baseline_paths=[])))
    before=path.read_bytes();files=set(tmp_path.rglob('*'))
    monkeypatch.setattr(governance.Registry,'transaction',lambda self:pytest.fail('read probe cannot acquire held registry lock'))
    result=capacity.locked_runtime_probe(policy,tdx_root=native)
    assert result['phase_peak_bytes']['input']==64*1024**2+64
    assert result['predicted_peak_bytes']==sum(result['phase_peak_bytes'].values())
    assert result['eligibility']=='CANNOT_CONFIRM'
    assert result['unproven_writer_phases']==['daily_product','qfq','top200']
    assert result['reservation_write'] is False and result['reservation_release'] is False
    assert path.read_bytes()==before and set(tmp_path.rglob('*'))==files
    assert len(json.loads(path.read_bytes())['tasks'])==8


def test_raw_identity_change_same_classification_and_count_rejected(monkeypatch,tmp_path):
    import pandas as pd
    import pyarrow as pa
    from ops import research_panel_delta as delta
    code='000001.SZ'
    raw=pd.DataFrame(dict(trade_date=[1,2,3],open=[1.,2.,3.],high=[2.,3.,4.],low=[0.,1.,2.],close=[1.,2.,3.],vol=[1.,1.,1.],amount=[1.,2.,3.]))
    oldraw=raw.iloc[:2].copy()
    old={'asof_date':2,'symbols':{code:{'events':[]}}}
    current=tmp_path/'baseline';current.write_bytes(b'baseline')
    semantics={key:'same' for key in ('driver_sha256','formula_sha256','field_contract_sha256','user_formula_sha256')}
    c=dict(snapshot={'symbols':{code:{'events':[]}}},target=3,driver=SimpleNamespace(),run_dir=tmp_path,
           currents={'selector':current},contracts={'selector':semantics},
           baseline_hashes={'selector':capacity.file_reference(current)['sha256']})
    q=dict(resolved_raw_history=lambda *args:raw.copy(),QfqGateError=ValueError,
           canonical_sha=capacity.digest,sha=lambda path:capacity.file_reference(path)['sha256'])
    frames={'selector':{code:pa.table({'ts_code':[code,code],'trade_date':[1,2]})}}
    schemas={'selector':frames['selector'][code].schema}
    monkeypatch.setattr(delta,'baseline_raw_history',lambda *args:(oldraw.copy(),[]))
    first=delta.classify_delta_scope(q,c,frames,old,schemas,semantics,[code])[code]
    assert first['kind']=='APPEND' and first['changed_rows']==1
    c['capacity_plan']={'classifications':{code:'APPEND'},'source_identity':{
        'changed_rows_by_symbol':{code:1},'classification_dependencies':{code:first['classification_sha256']}}}
    raw.loc[2,'close']=30.
    with pytest.raises(ValueError,match='CLASSIFICATION_CHANGED_BEFORE_WRITE'):
        delta._prepare(q,c,code,frames,old,schemas,semantics)
    assert set(tmp_path.iterdir())=={current}


def test_snapshot_input_parquet_exact_bytes_guarded_before_write(tmp_path,monkeypatch):
    import pandas as pd
    from ops import research_storage_governance as governance
    from ops import research_panel_tdx_adjustment_inputs as tdx
    frame=pd.DataFrame({'code':['000001'],'value':[123.]})
    expected=frame.to_parquet(None,index=False)
    output=tmp_path/'parsed.parquet'
    class Parser:
        def get_df(self,path):return frame
    def original(root,codes,target,**kwargs):
        return kwargs['parser_factory']().get_df('fixture').to_parquet(output,index=False)
    monkeypatch.setattr(tdx,'build_fallback',original)
    class Claim:
        input_exact_serialization=True
        limit=capacity.incoming_bytes(len(expected))-1
        def watch(self,path):pass
        def checkpoint(self,*,incoming):
            assert incoming==capacity.incoming_bytes(len(expected))
            if incoming>self.limit:raise governance.SpaceBlocked('ONE_BYTE_SHORT')
        def observe(self,path):assert path.read_bytes()==expected
    claim=Claim();token=governance._ACTIVE.set(claim)
    try:
        with governance.input_write_seams(claim):
            with pytest.raises(governance.SpaceBlocked,match='ONE_BYTE_SHORT'):
                tdx.build_fallback(tmp_path,[],20261123,parser_factory=Parser)
            assert not output.exists()
            claim.limit+=1
            tdx.build_fallback(tmp_path,[],20261123,parser_factory=Parser)
            assert output.read_bytes()==expected
    finally:governance._ACTIVE.reset(token)


def test_snapshot_three_clone_allocations_sum_per_file_before_any_write(tmp_path):
    import sys
    if sys.platform!='darwin':pytest.skip('actual accepted publisher requires APFS clone syscall')
    from ops import research_storage_governance as governance
    from ops import research_panel_adjustment_inputs as inputs
    payload={'x':'a'}
    raw=(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    aggregate=3*capacity.incoming_bytes(len(raw))
    assert aggregate==3*4096
    current=tmp_path/'qfq_adjustment_input.json'
    class Claim:
        input_exact_serialization=True
        limit=aggregate-1
        def watch(self,path):pass
        def checkpoint(self,*,incoming):
            assert incoming==aggregate
            if incoming>self.limit:raise governance.SpaceBlocked('THREE_CLONES_ONE_BYTE_SHORT')
        def observe(self,path):assert path.is_file()
    claim=Claim();token=governance._ACTIVE.set(claim)
    try:
        with governance.input_write_seams(claim):
            with pytest.raises(governance.SpaceBlocked,match='THREE_CLONES_ONE_BYTE_SHORT'):
                inputs.publish_adjustment_snapshot(current,payload)
            assert not list(tmp_path.rglob('*'))
            claim.limit+=1
            inputs.publish_adjustment_snapshot(current,payload)
            files=[path for path in tmp_path.rglob('*') if path.is_file()]
            assert len(files)==3
            assert all(path.read_bytes()==raw for path in files)
            assert sum(path.stat().st_blocks*512 for path in files)==aggregate
            assert sum(governance.billing_bytes(path) for path in files)==3*len(raw)
    finally:governance._ACTIVE.reset(token)
