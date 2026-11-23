"""Independent budgets and exact output decisions on the real owner entries."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ops import research_daily_capacity as capacity
from ops import research_storage_governance as governance
from ops import research_panel_daily_product as product
from test_product_write_budgets import make_plan, TraceClaim, daily_completion_fixture


def rebind_review(policy, *, scope='ISOLATED_FIXTURE'):
    config=policy['governance']['incremental_capacity']
    path=Path(config['reviewed_limits']['path'])
    path.write_bytes(capacity.encoded(dict(schema='v4.daily_incremental_limits_review.v1',status='PASS',
        phase_limits=config['phases'],consumer_limits=config.get('consumers'),
        downstream_outputs=config.get('downstream_outputs'),evidence_scope=scope,
        source_bindings=capacity.writer_sources())))
    config['reviewed_limits']['sha256']=capacity.file_reference(path)['sha256']


def independent_policy(tmp_path):
    _,policy=make_plan(tmp_path,scope=('000001.SZ',))
    data=tmp_path/'data';data.mkdir()
    native=tmp_path/'tdx/native';native.mkdir(parents=True)
    run=tmp_path/'runs';run.mkdir()
    product_base=tmp_path/'product-base'
    products=product_base/'daily_products/a_share';products.mkdir(parents=True)
    groups=tmp_path/'groups';groups.mkdir()
    receipts=tmp_path/'receipts'
    inputs=data/'runtime/cache/data_layer_daily_formula_increment_update_v1'
    roots=[str(inputs),str(native.parent/'adjustment_inputs/futu_rehab'),str(receipts/'a_sync_authority')]
    limits=copy.deepcopy(policy['governance']['incremental_capacity']['phases']['daily_product'])
    limits['fixed_bytes']=1260912640-limits['max_symbols']*limits['per_symbol_bytes']-limits['max_changed_rows']*limits['per_changed_row_bytes']
    policy.update(data_root=str(data),run_root=str(run),formal_roots={},pointers={})
    policy['governance'].update(enabled=True,pool_id='ISOLATED_ONLY',pool_identity_verified=True,
        registry_root=str(tmp_path/'ledger'),ordinary_peak_budget_bytes=261*1024**3,product_output_roots=[str(products)])
    policy['governance']['incremental_capacity'].update(consumers={
        'adjustment_snapshot':dict(peak_bytes=536870912,output_roots=roots),
        'formula_supplements':dict(peak_bytes=1260912640,mode='ENABLED',limits=limits,
            output_roots=[str(groups)],shared_product_roots=[str(products)])},
        downstream_outputs={'statistics':dict(mode='DISABLED',output_roots=[])})
    rebind_review(policy)
    from ops.research_panel_formula_groups_daily import FLAGS, FORMULA_SHA256
    binding=tmp_path/'host-binding.json'
    binding.write_bytes(capacity.encoded(dict(schema='V4_MAC_WORKBENCH_BINDING_V1',candidate_group_formula_sha256=FORMULA_SHA256,
        candidate_group_overrides={},formula_groups_root=str(groups),**FLAGS)))
    binding_ref=dict(path=str(binding),sha256=capacity.file_reference(binding)['sha256'])
    return policy,SimpleNamespace(native=native,inputs=inputs,receipts=receipts,products=products,groups=groups,
        product_base=product_base,binding_ref=binding_ref)


def probe(policy,roots):
    return capacity.locked_runtime_probe(policy,tdx_root=roots.native,receipt_root=roots.receipts,
        daily_product_root=roots.product_base,api_host_binding=roots.binding_ref)


@pytest.mark.parametrize('kind',['missing','malformed','tampered','unbound','wrong_cap','missing_formula_limits'])
def test_independent_evidence_fails_closed(tmp_path,kind):
    policy,roots=independent_policy(tmp_path)
    config=policy['governance']['incremental_capacity']
    if kind=='missing':
        del config['consumers'];del config['downstream_outputs'];rebind_review(policy,scope='PRODUCTION_REVIEWED')
    elif kind=='malformed':
        Path(config['reviewed_limits']['path']).write_text('{')
    elif kind=='tampered':
        Path(config['reviewed_limits']['path']).write_bytes(b'{}')
    elif kind=='unbound':
        config['consumers']['adjustment_snapshot']['peak_bytes']-=1
    elif kind=='wrong_cap':
        config['consumers']['adjustment_snapshot']['peak_bytes']-=1;rebind_review(policy)
    else:
        config['consumers']['formula_supplements']['limits']=None;rebind_review(policy)
    with pytest.raises(capacity.CapacityProofError,match='CONSUMER|REVIEW|LIMITS_INVALID'):
        capacity.phase_limits(policy,'qfq')
    assert not roots.inputs.exists() and not (tmp_path/'ledger').exists()


def test_real_snapshot_claim_uses_independent_budget_actual_roots_and_identity(tmp_path,monkeypatch):
    policy,roots=independent_policy(tmp_path)
    monkeypatch.setattr(governance,'configured_policy',lambda:policy)
    with governance.input_preflight(tdx_root=roots.native,receipt_root=roots.receipts,target=20261123,
                                   operation='adjustment_snapshot',output_root=roots.inputs) as claim:
        assert isinstance(claim,governance.Claim) and claim.predicted==536870912
        assert claim.directory==str(roots.inputs)
        assert set(map(str,claim.input_output_roots))==set(policy['governance']['incremental_capacity']['consumers']['adjustment_snapshot']['output_roots'])
        # Every source location is bound before the source is called or mkdirs.
        for root in claim.input_output_roots:claim.watch(root/'new.json')
        with pytest.raises(governance.RetentionError,match='OUTPUT_ROOT_NOT_APPROVED'):
            claim.watch(tmp_path/'unreviewed.json')
        key=claim.key
    state=json.loads((tmp_path/'ledger/registry.json').read_bytes())
    assert state['tasks'][key]['state']=='READY'
    assert state['tasks'][key]['result']['status']=='SOURCE_OPERATION_COMPLETED'
    assert state['tasks'][key]['directory']==str(roots.inputs)
    assert not roots.inputs.exists()
    with pytest.raises(capacity.CapacityProofError,match='OUTPUT_ROOT_BINDING'):
        with governance.input_preflight(tdx_root=roots.native,receipt_root=roots.receipts,target=20261124,
                                       operation='adjustment_snapshot',output_root=roots.inputs.parent):
            pytest.fail('wrong root reached owner')
    assert len(json.loads((tmp_path/'ledger/registry.json').read_bytes())['tasks'])==1


def test_locked_probe_exact_six_consumers_and_resident_roots(tmp_path,monkeypatch):
    policy,roots=independent_policy(tmp_path)
    ledger=tmp_path/'ledger';ledger.mkdir()
    path=ledger/'registry.json';path.write_bytes(capacity.encoded(dict(schema=governance.SCHEMA,pool_id='ISOLATED_ONLY',tasks={},resident_baseline_paths=[])))
    before=path.read_bytes()
    result=probe(policy,roots)
    components=result['consumer_peak_bytes']
    assert set(components)=={'native_input','adjustment_snapshot','qfq','daily_product','formula_supplements','top200'}
    assert components['adjustment_snapshot']==536870912
    assert components['formula_supplements']==1260912640
    assert result['predicted_peak_bytes']==sum(components.values())
    assert result['phase_peak_bytes']['input']==components['native_input']+536870912
    assert result['phase_peak_bytes']['daily_product']==components['daily_product']+1260912640
    config=governance.configuration(policy)
    all_roots=set(policy['governance']['incremental_capacity']['consumers']['adjustment_snapshot']['output_roots'])|{str(roots.products),str(roots.groups)}
    assert all_roots<=set(config['accounting_roots']['ordinary'])
    assert path.read_bytes()==before
    assert result['eligibility']=='PASS_ISOLATED_FIXTURE'
    # Plan2 P0 accepts the instrumented writers; limits/root/resident checks
    # still run before production eligibility is returned.
    rebind_review(policy,scope='PRODUCTION_REVIEWED')
    assert capacity.ACCEPTED_WRITER_PHASES==frozenset(capacity.PHASES)
    result=probe(policy,roots)
    assert result['eligibility']=='PASS' and result['unproven_writer_phases']==[]
    assert path.read_bytes()==before


def test_production_limit_config_is_not_an_external_approval_record(tmp_path,monkeypatch):
    policy,_=independent_policy(tmp_path)
    config=policy['governance']['incremental_capacity'];path=Path(config['reviewed_limits']['path'])
    value=json.loads(path.read_bytes());value.pop('source_bindings');value.pop('status')
    value['evidence_scope']='PRODUCTION_REVIEWED'
    path.write_bytes(capacity.encoded(value));config['reviewed_limits']['sha256']=capacity.file_reference(path)['sha256']
    monkeypatch.setattr(capacity,'writer_sources',lambda:pytest.fail('limits config inspected business sources'))
    assert capacity.phase_limits(policy,'qfq')==config['phases']['qfq']


def test_actual_formula_entry_owns_independent_phase_claim_and_roots(tmp_path,monkeypatch):
    from ops._formula_groups_daily_parts import workbench_supplements as supplements
    policy,roots=independent_policy(tmp_path)
    ref=product.save(tmp_path/'source.json',{'source':'bound'})
    context=SimpleNamespace(root=roots.products,target=20261123,scope=['000001.SZ'],identity={'generation':'fixture'},
        receipt_ref=ref,snapshot_ref=ref,config_ref=ref,reader_ref=ref,read=lambda symbol:([{}],None),unchanged=lambda:None)
    monkeypatch.setattr(governance,'configured_policy',lambda:policy)
    monkeypatch.setattr(supplements,'_numeric_product',lambda _:(ref,{}, {},{}))
    monkeypatch.setattr(supplements,'_group_identity',lambda *_:('2026-11-23',['000001.SZ'],'bound'))
    def owned(context,root,formula,receipt):
        writer=capacity.current_writer()
        assert writer.plan['phase']=='formula_supplements'
        assert writer.plan['limits']==policy['governance']['incremental_capacity']['consumers']['formula_supplements']['limits']
        assert writer.claim.predicted==writer.plan['predicted_bytes']==1260912640
        assert writer.plan['predicted_bytes']!=capacity.maximum_phase_bytes(policy)['daily_product']
        with pytest.raises(capacity.CapacityProofError,match='OUTSIDE_OWNED_ROOT'):
            product.save(tmp_path/'bad-root.json',{'bad':True})
        shared=product.save(roots.products/'f10/new.json',{'value':1})
        pointer=Path(root)/'2026-11-23/supplements/latest.json'
        pointer.parent.mkdir(parents=True,exist_ok=True)
        return dict(status='PARTIAL',pointer=supplements._atomic_pointer(pointer,{'shared':shared},'ABSENT'))
    monkeypatch.setattr(supplements,'_complete_owned',owned)
    with pytest.raises(capacity.CapacityProofError,match='ROOT_NOT_APPROVED'):
        supplements.complete(context,tmp_path/'wrong-root',ref,ref)
    unrelated_root=tmp_path/'unrelated-plan';unrelated_root.mkdir()
    unrelated,_=make_plan(unrelated_root)
    with capacity.writer_scope(unrelated,claim=TraceClaim(),roots=[roots.groups,roots.products]):
        with pytest.raises(capacity.CapacityProofError,match='INDEPENDENT_CLAIM_REQUIRED'):
            supplements.complete(context,roots.groups,ref,ref)
    result=supplements.complete(context,roots.groups,ref,ref)
    assert result['status']=='PARTIAL'
    rows=list(json.loads((tmp_path/'ledger/registry.json').read_bytes())['tasks'].values())
    assert len(rows)==1 and rows[0]['state']=='READY' and rows[0]['logical_written_bytes']>0
    choice=policy['governance']['incremental_capacity']['consumers']['formula_supplements']
    choice.update(mode='DISABLED',output_roots=[],shared_product_roots=[]);rebind_review(policy)
    monkeypatch.setattr(supplements,'_numeric_product',lambda _:pytest.fail('disabled source read'))
    assert supplements.complete(context,roots.groups,None,None)['status']=='NOT_RUN_POLICY_DISABLED'
    assert probe(policy,roots)['consumer_peak_bytes']['formula_supplements']==0


def test_statistics_disabled_skips_real_owner_environment_and_wrong_root_fails_early(tmp_path,monkeypatch):
    import ops.build_mac_workbench as workbench
    policy,roots=independent_policy(tmp_path)
    root=daily_completion_fixture(tmp_path,monkeypatch)
    stats=tmp_path/'unapproved-statistics'
    monkeypatch.setenv('V4_WORKBENCH_STATISTICS_ROOT',str(stats))
    monkeypatch.setattr(governance,'configured_policy',lambda:policy)
    monkeypatch.setattr(workbench,'materialize_statistics',lambda *_:pytest.fail('disabled statistics invoked'))
    plan_root=tmp_path/'writer-plan';plan_root.mkdir()
    plan,_=make_plan(plan_root)
    with capacity.writer_scope(plan,claim=TraceClaim(),roots=[root]):
        product.materialize_daily_product(data_root=tmp_path,target=20261123,original_charts=False)
    assert not stats.exists()
    policy['governance']['incremental_capacity']['downstream_outputs']['statistics']={'mode':'ENABLED','output_roots':[str(tmp_path/'approved-statistics')]}
    rebind_review(policy)
    with pytest.raises(capacity.CapacityProofError,match='STATISTICS_ENABLED_WRITER_NOT_REVIEWED'):
        capacity.downstream_root(policy,'statistics',str(stats))


def test_reviewed_roots_are_protected_before_first_output(tmp_path):
    from ops import research_storage_retention as retention
    policy,roots=independent_policy(tmp_path)
    source=tmp_path/'pin-source';source.write_text('source')
    pins=tmp_path/'pins.json'
    pins.write_bytes(capacity.encoded(dict(schema='v4_research_managed_pin_inventory_v1',status='COMPLETE_REVIEWED',
        consumer_scopes={name:'REVIEWED_NO_MANAGED_PINS' for name in retention.CONSUMER_SCOPES},
        pins=[],source_bindings=[dict(path=str(source),sha256=capacity.file_reference(source)['sha256'])],
        expected_main_app_root=str(tmp_path))))
    policy['managed_pin_inventory']=dict(path=str(pins),sha256=capacity.file_reference(pins)['sha256'])
    protected,_,_=retention.managed_runtime_projection(policy,[],[],[],{})
    consumers=policy['governance']['incremental_capacity']['consumers']
    expected={Path(root) for item in consumers.values() for root in item['output_roots']+item.get('shared_product_roots',[])}
    assert expected<=protected
    assert roots.inputs in protected and not roots.inputs.exists()


@pytest.mark.parametrize('bad',[{'start':-1,'filename':'f','length':1},{'start':0,'filename':None,'length':1}])
def test_f10_request_envelope_refuses_before_content(tmp_path,bad):
    from ops import research_panel_f10 as f10
    plan,_=make_plan(tmp_path)
    class Api:
        def connect(self,*_):return True
        def get_company_info_category(self,*_):return [bad]
        def get_company_info_content(self,*_):pytest.fail('malformed request reached content')
        def disconnect(self):pass
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[tmp_path]):
        with pytest.raises(capacity.CapacityProofError,match='CONTENT_REQUEST_BOUND'):
            f10.fetch_one('000001.SZ','SZ',api_factory=Api,vendor=(SimpleNamespace(),None))


def test_complete_f10_packet_bound_propagates_through_admitted_threads(tmp_path):
    from ops import research_panel_f10 as f10
    from concurrent.futures import ThreadPoolExecutor
    plan,_=make_plan(tmp_path,max_response_bytes=2048)
    class Api:
        def connect(self,*_):return True
        def get_company_info_category(self,*_):return [{'filename':'f','start':0,'length':1300}]
        def get_company_info_content(self,*_):return 'x'*1300
        def get_finance_info(self,*_):return {'code':'000001','market':0,'extra':'x'*1300}
        def disconnect(self):pass
    claim=TraceClaim();namespace=SimpleNamespace(ThreadPoolExecutor=ThreadPoolExecutor)
    token=governance._ACTIVE.set(claim)
    vendor=SimpleNamespace(grab=lambda *_:None)
    try:
        with capacity.writer_scope(plan,claim=claim,roots=[tmp_path]),governance.product_write_seams([namespace],claim):
            with pytest.raises(capacity.CapacityProofError,match='COMPLETE_PACKET_RESPONSE_BOUND'):
                with namespace.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(f10.fetch_one,'000001.SZ','SZ',api_factory=Api,vendor=(vendor,None)).result()
        assert not claim.observed
    finally:governance._ACTIVE.reset(token)


@pytest.mark.parametrize('kind',['adjustment_path','factor_path','receipt_path','product_path','formula_path','device','missing_receipt','missing_host','host_sha','host_identity'])
def test_probe_rejects_wrong_runtime_paths_devices_and_identity_without_writes(tmp_path,kind):
    policy,roots=independent_policy(tmp_path)
    incremental=policy['governance']['incremental_capacity']
    args=dict(tdx_root=roots.native,receipt_root=roots.receipts,daily_product_root=roots.product_base,
              api_host_binding=roots.binding_ref)
    if kind in {'adjustment_path','factor_path','receipt_path'}:
        index={'adjustment_path':0,'factor_path':1,'receipt_path':2}[kind]
        incremental['consumers']['adjustment_snapshot']['output_roots'][index]=str(tmp_path/('wrong-'+kind))
        rebind_review(policy)
    elif kind=='product_path':args['daily_product_root']=tmp_path/'wrong-product-base'
    elif kind=='formula_path':
        incremental['consumers']['formula_supplements']['output_roots']=[str(tmp_path/'wrong-groups')];rebind_review(policy)
    elif kind=='device':policy['governance']['pool_member_devices']=[Path(policy['data_root']).stat().st_dev+1]
    elif kind=='missing_receipt':args['receipt_root']=None
    elif kind=='missing_host':args['api_host_binding']=None
    elif kind=='host_sha':args['api_host_binding']=dict(roots.binding_ref,sha256='0'*64)
    else:
        binding=Path(roots.binding_ref['path']);payload=json.loads(binding.read_bytes())
        payload['production_allowed']=True;binding.write_bytes(capacity.encoded(payload))
        args['api_host_binding']=dict(path=str(binding),sha256=capacity.file_reference(binding)['sha256'])
    before={str(path):path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    with pytest.raises(capacity.CapacityProofError,match='ROOT|POOL|HOST_BINDING'):
        capacity.locked_runtime_probe(policy,**args)
    assert not (tmp_path/'ledger').exists()
    assert {str(path):path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}==before


def test_actual_formula_and_snapshot_reject_wrong_device_before_claim(tmp_path,monkeypatch):
    from ops._formula_groups_daily_parts import workbench_supplements as supplements
    policy,roots=independent_policy(tmp_path)
    policy['governance']['pool_member_devices']=[Path(policy['data_root']).stat().st_dev+1]
    monkeypatch.setattr(governance,'configured_policy',lambda:policy)
    with pytest.raises(capacity.CapacityProofError,match='OUTSIDE_VERIFIED_SHARED_POOL'):
        with governance.input_preflight(tdx_root=roots.native,receipt_root=roots.receipts,target=20261123,
                                       operation='adjustment_snapshot',output_root=roots.inputs):
            pytest.fail('wrong-device snapshot admitted')
    with pytest.raises(capacity.CapacityProofError,match='OUTSIDE_VERIFIED_SHARED_POOL'):
        supplements.complete(SimpleNamespace(target=20261123,root=roots.products),roots.groups,None,None)
    assert not (tmp_path/'ledger').exists()



def test_probe_rechecks_host_binding_after_root_walk(tmp_path,monkeypatch):
    policy,roots=independent_policy(tmp_path)
    ledger=tmp_path/'ledger';ledger.mkdir()
    registry=ledger/'registry.json'
    registry.write_bytes(capacity.encoded(dict(schema=governance.SCHEMA,pool_id='ISOLATED_ONLY',tasks={},resident_baseline_paths=[])))
    before=registry.read_bytes()
    original=governance.input_forecast
    def changed(root):
        binding=Path(roots.binding_ref['path'])
        payload=json.loads(binding.read_bytes());payload['changed_after_initial_check']=True
        binding.write_bytes(capacity.encoded(payload))
        return original(root)
    monkeypatch.setattr(governance,'input_forecast',changed)
    with pytest.raises(capacity.CapacityProofError,match='HOST_BINDING_SHA_DRIFT'):
        probe(policy,roots)
    assert registry.read_bytes()==before
