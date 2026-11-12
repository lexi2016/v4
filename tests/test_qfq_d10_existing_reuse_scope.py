"""Unit checks execute the actual owner source/scope tail, not a reimplementation.
The unchanged baseline/kernel/Arrow gates are checked by the effective-source AST proof.
"""
import ast,copy,hashlib,json,os
from pathlib import Path
import pytest
from ops import research_panel_qfq as q

pytestmark = pytest.mark.skipif(not os.environ.get('V4_TEST_QFQ_REUSE_SOURCE'),
    reason='requires the explicitly pinned effective Main source, absent from the older Git baseline')


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def run_tail(namespace):
    path=Path(os.environ['V4_TEST_QFQ_REUSE_SOURCE'])
    function=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_same_asof_price_reuse')
    start=next(i for i,n in enumerate(function.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='source' for t in n.targets))
    stub=ast.parse('def actual_owner_tail():\n    pass\n').body[0]
    stub.body=function.body[start:]
    code=ast.fix_missing_locations(ast.Module(body=[stub],type_ignores=[]))
    exec(compile(code,str(path),'exec'),namespace)
    return namespace['actual_owner_tail']()


@pytest.fixture
def scope(tmp_path):
    codes=['002623.SZ','605258.SH','601326.SH','000972.SZ','002827.SZ','300237.SZ','688496.SH','920202.BJ','301314.SZ']
    paths=[tmp_path/(c+'.day') for c in codes[:8]]
    refs=[write(p,b'original-native') for p in paths]
    expected=[dict(target_path=str(p),expected_after_sha256=r['sha256']) for p,r in zip(paths[:6],refs[:6])]
    facts=write(tmp_path/'facts.json',dict(rows=[dict(symbol='002717',target_date=20261110,target_has_no_current_bar=True,document_verified_status_dates=True)]))
    plan=dict(six_native_updates=expected,archive_688496=dict(source=dict(path=str(paths[6])),native_expected_after=refs[6]),native_920202=dict(target_path=str(paths[7]),source=refs[7]),seven_status_policy=dict(source_facts=facts))
    planref=write(tmp_path/'plan.json',plan)
    completion=write(tmp_path/'completion.json',dict(status='EIGHT_NATIVE_COMPLETE_NO_FORMULA_OR_PANEL_BUILD',source_mode='CAPTURE_REPLAY',executed=True,network_requests=0,target_date=20261110,RESEARCH_ONLY=True,items=[dict(path=str(p),after_sha256=r['sha256'],status='APPLIED_NATIVE_ONLY') for p,r in zip(paths,refs)]))
    raw=write(tmp_path/'healthy.day',b'healthy-unchanged')
    olditem=dict(raw_files=[raw],events=[],source_config='before')
    newitem=dict(olditem,source_config='after')
    cfg=write(tmp_path/'config.json',{})
    old301=dict(raw_files=[raw],events=[1,2,3,4])
    new301=dict(raw_files=[refs[0]],events=[1,2,3,4])
    fact=write(tmp_path/'301314fact.json',dict(raw_refs=old301['raw_files'],events=old301['events'],source_generation='baseline'))
    parity=write(tmp_path/'301314parity.json',dict(matched_prior_both_role_fact=True,rows=868,source_config=cfg,native=refs[0]))
    old=dict(symbols={'300556.SZ':olditem,'301314.SZ':old301})
    snapshot=dict(symbols={'300556.SZ':newitem,'301314.SZ':new301,'002623.SZ':dict(raw_files=[refs[1]],events=[])},history_retention_binding=dict(accepted_evidence=[fact],source_config=cfg))
    value=dict(source_admission=completion,native_execution_plan=planref,allowed_changed_codes=codes,metadata_only_301314_fact=fact,metadata_only_301314_parity=parity,baseline_roles={},baseline_snapshot={},factor_equivalence={})
    return dict(target=20261110,value=value,snapshot=snapshot,old=old,receipt=dict(generation_id='baseline'),policies=[{},dict(exact_no_current_bar_dispositions=[dict(symbol='002717.SZ',target_date=20261110,expected_native_sha256=raw['sha256'],evidence=facts)])],ref={},core=Path(__file__),QfqGateError=q.QfqGateError,_source=q._source,json=json,Path=Path,computation_kernel_sha=lambda p:'unchanged-kernel',_same_asof_stock_dependencies=lambda item:{k:v for k,v in item.items() if k not in {'source_config','accepted_evidence','provider_response_scope','source_method'}},root=tmp_path,healthy=raw)


def test_unchanged_arrow_members_and_metadata_only_301314_are_reused(scope):
    result=run_tail(scope)
    assert result['codes']=={'002623.SZ':dict(reason='CHANGED_OR_NEW_REAL_PRICE_DEPENDENCIES')}
    assert result['reused_codes']==['300556.SZ','301314.SZ']


@pytest.mark.parametrize('kind',['unapproved','scope','native_changed','fake_completion','metadata_changed'])
def test_d10_reuse_scope_fails_closed(scope,kind):
    if kind=='unapproved':scope['snapshot']['symbols']['600999.SH']=dict(raw_files=[scope['healthy']],events=[])
    if kind=='scope':scope['value']['allowed_changed_codes'].append('600999.SH')
    if kind=='native_changed':Path(scope['value']['source_admission']['path']).write_text('{}')
    if kind=='fake_completion':scope['value']['source_admission']=write(scope['root']/'fake.json',dict(technical_failure_count=0,failures=[],target_date=20261110,RESEARCH_ONLY=True))
    if kind=='metadata_changed':scope['snapshot']['symbols']['301314.SZ']['events']=[0]
    with pytest.raises(q.QfqGateError):run_tail(scope)


def test_additional_no_bar_change_requires_actual_snapshot_and_policy_evidence(scope):
    scope['old']['symbols']['002717.SZ']=dict(raw_files=[scope['healthy']],events=[])
    scope['snapshot']['original_quarantine_eligible']={'002717.SZ':dict(reason_code='EXPECTED_NO_CURRENT_BAR',path=scope['healthy']['path'],source_sha256_after=scope['healthy']['sha256'])}
    result=run_tail(scope)
    assert result['removed_codes']==['002717.SZ'] and result['derived_no_bar_changes']==['002717.SZ']


def test_d30_exact44_behavior_stays_closed_for_d10_scope(scope):
    scope['target']=20261030
    scope['value']['source_admission']=write(scope['root']/'d30.json',dict(target_date='20261030',technical_failure_count=0,failures=[],RESEARCH_ONLY=True))
    with pytest.raises(q.QfqGateError,match='EXACT44'):run_tail(scope)
