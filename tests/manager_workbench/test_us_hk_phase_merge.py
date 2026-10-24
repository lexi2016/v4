from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from datetime import datetime
import pytest
from v4.manager_workbench import engines
from v4.manager_workbench.contracts import Lane, LaneResult, RunContext, Counts, seal_snapshot, digest
from v4.manager_workbench.service import ManagerService
from v4.manager_workbench.store import WorkbenchStore, StorageConflict


def snapshot(lane,run,*,session='20261022',cutoff='2026-10-23T06:00:00+08:00',merge=False):
    context=RunContext(target_date='20261023',phase='NEXT_DAY',trigger='SCHEDULED',cutoff=cutoff,
        source_sessions=dict(us=session,hk_price='20261022'),rules_version='POSITIVE_OPERATING_RESEARCH_V1',
        scope_refs=dict(requested_lanes=[lane],merge_phase_lanes=merge,source_cutoff=cutoff))
    result=LaneResult(lane=lane,state='READY_EMPTY',rows=[],coverage=dict(scope_count=0,observed_count=0,assessed_count=0,unassessed_count=0),input_sha256=digest(run),rules_version=context.rules_version,run_id=run)
    return seal_snapshot(dict(context=context.model_dump(mode='json'),run_id=run,input_sha256=digest(run),
        generated_at=cutoff,available_at=cutoff,lanes=[result.model_dump(mode='json')],stocks=[],
        counts=Counts(selected=0,watch=0,unassessed=0,not_selected=0,observation_only=0).model_dump(mode='json')))


def service(tmp_path):
    s=ManagerService.__new__(ManagerService);s.store=WorkbenchStore(tmp_path);s.engines=engines
    return s


@pytest.mark.parametrize('order',[('OVERSOLD','US_MAPPING'),('US_MAPPING','OVERSOLD')])
def test_same_target_nextday_keeps_both_lanes_without_us_caller_flag(tmp_path,order):
    s=service(tmp_path)
    for name in order:s._commit_plan(snapshot(name,name,merge=name=='OVERSOLD'))
    saved=s.store.get_plan('20261023','NEXT_DAY')
    assert {l.lane.value for l in saved.lanes}=={'OVERSOLD','US_MAPPING'}
    assert saved.changes['phase_lane_sources']=={'OVERSOLD':'OVERSOLD','US_MAPPING':'US_MAPPING'}


def test_concurrent_phase_publication_uses_existing_store_lock(tmp_path):
    s=service(tmp_path)
    plans=[snapshot('OVERSOLD','oversold',merge=True),snapshot('US_MAPPING','us')]
    with ThreadPoolExecutor(2) as pool:list(pool.map(s._commit_plan,plans))
    assert {l.lane.value for l in s.store.get_plan('20261023','NEXT_DAY').lanes}=={'OVERSOLD','US_MAPPING'}


def test_stale_us_source_cannot_replace_newer_source(tmp_path):
    s=service(tmp_path);s._commit_plan(snapshot('US_MAPPING','new',merge=True))
    with pytest.raises(StorageConflict,match='STALE_US_SOURCE_OVERWRITE'):
        s._commit_plan(snapshot('US_MAPPING','old',session='20261021',cutoff='2026-10-22T06:00:00+08:00',merge=True))
    assert s.store.get_plan('20261023','NEXT_DAY').run_id=='new'


def test_scheduled_handoff_keeps_original_source_cutoff_in_submitted_context(tmp_path):
    from test_us_close_handoff_scheduler import Service,Calendar,_pin,_succeed
    from v4.manager_workbench.scheduler import _us_close_handoff
    s=Service(tmp_path,_pin(),_succeed)
    try:
        receipts=_us_close_handoff(s,calendar=Calendar(),local=datetime.fromisoformat('2026-10-17T04:20:00+08:00'))
        assert len(receipts)==1
        ctx=s.jobs.get(receipts[0]['job_id']).context
        assert ctx.scope_refs['source_cutoff']==_pin()['capture_cutoff']
        assert ctx.scope_refs['merge_phase_lanes'] is True
        assert ctx.scope_refs['requested_lanes']==['US_MAPPING']
    finally:s.stop()


def test_pure_preopen_retains_candidate_and_all_stage_reasons_without_source_mutation(tmp_path):
    from test_us_hk_selection_closure import fixture_batch
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.service import project_preopen_lane
    c,b=fixture_batch(tmp_path);lane=LaneResult.model_validate(run_us_mapping(c,b));before=lane.model_dump(mode='json')
    projected=project_preopen_lane(lane,cutoff='2026-10-23T04:00:00+08:00')
    assert len(projected.selection.candidates)==1
    assert projected.selection.strict_decisions[0].decision=='PENDING'
    assert projected.selection.evaluation_complete is False
    assert 'PREOPEN_ROW_EVIDENCE_UNVERIFIED_OR_AFTER_CUTOFF' in projected.selection.strict_decisions[0].reasons
    assert lane.model_dump(mode='json')==before


def test_real_frozen_context_preserves_quote_cutoff_and_unknown_never_becomes_clock():
    import json
    from pathlib import Path
    from v4.manager_workbench.service import _publication_context
    path=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/input_snapshots/b80a8bc475f6aeb8976c706674ad4791c803720eb2e3134c09ad55a784c61b37.json')
    original=json.loads(path.read_bytes())['context'];context=RunContext.model_validate(original)
    original_source=context.scope_refs.get('source_cutoff')
    assert original_source and original_source!=context.cutoff
    after=_publication_context(context,'2026-10-24T00:00:00+08:00')
    assert after.scope_refs['source_cutoff']==original_source
    assert after.cutoff==context.cutoff==original['cutoff']
    assert after.scope_refs['source_execution_cutoff']==original['cutoff']
    assert after.scope_refs['processing_cutoff']=='2026-10-24T00:00:00+08:00'
    assert context.model_dump(mode='json')==original
    context.scope_refs.pop('source_cutoff')
    assert _publication_context(context,'2026-10-24T00:00:00+08:00').scope_refs['source_cutoff'] is None


def test_service_real_engine_certified_positive_keeps_original_asof(tmp_path):
    import time
    from copy import deepcopy
    from test_us_hk_selection_closure import fixture_batch
    from v4.manager_workbench.config import WorkbenchConfig
    from v4.manager_workbench.contracts import Coverage
    from v4.manager_workbench.inputs.validation import batch as input_batch
    from v4.manager_workbench.service import create_service
    from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
    c,b=fixture_batch(tmp_path)
    class Adapter:
        def prepare_context(self,ctx):
            ctx.source_sessions=dict(c['source_sessions'])
            ctx.scope_refs.update({k:v for k,v in c['scope_refs'].items() if k!='run_id'})
            ctx.scope_refs['source_cutoff']='2026-10-22T21:00:00+00:00'
            return ctx
        def load(self,lane,context):
            if lane!=Lane.US_MAPPING:raise KeyError(lane)
            return input_batch(context,lane,deepcopy(b['records']),b['evidence_refs'],b['scope_description'],Coverage(**b['coverage']),[],b['universe_ref'])
    s=create_service(WorkbenchConfig(state_root=tmp_path/'derived',rules_version=US_FACTOR_RULES_VERSION),Adapter(),engines,object())
    try:
        job=s.submit(c['target_date'],__import__('v4.manager_workbench.contracts',fromlist=['Phase']).Phase.RETROSPECTIVE,
            cutoff=datetime.fromisoformat(c['cutoff']),lanes=[Lane.US_MAPPING])
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            final=s.jobs.get(job.job_id)
            if final.state.value not in {'RUNNING','QUEUED'}:break
            time.sleep(.01)
        assert final.state.value in {'SUCCEEDED','PARTIAL'},final.failure_code
        saved=s.store.read_plan(final.run_id);lane=next(l for l in saved.lanes if l.lane==Lane.US_MAPPING)
        assert lane.selection.counts['selected']==1
        assert lane.selection.cutoff==saved.context.cutoff==c['cutoff']
        assert saved.context.scope_refs['source_cutoff']=='2026-10-22T21:00:00+00:00'
        assert saved.context.scope_refs['decision_input_cutoff']==c['cutoff']
        assert saved.context.scope_refs['source_execution_cutoff']==c['cutoff']
        assert saved.generated_at!=saved.context.cutoff
    finally:s.stop()


def test_policy_engine_change_invalidates_old_zero_cache_then_reuses_same_version(tmp_path,monkeypatch):
    from tests.manager_workbench.runtime.test_runtime import make,done,Engine
    from v4.manager_workbench.contracts import Phase
    s,e,_=make(tmp_path,Engine(count=0))
    try:
        monkeypatch.setattr('v4.manager_workbench.engines.strict_us_selection.engine_identity',lambda:'a'*64)
        first=done(s,s.submit('20261013',Phase.MANUAL,lanes=[Lane.US_MAPPING]))
        assert e.lane_runs==1
        monkeypatch.setattr('v4.manager_workbench.engines.strict_us_selection.engine_identity',lambda:'b'*64)
        second=done(s,s.submit('20261013',Phase.MANUAL,lanes=[Lane.US_MAPPING]))
        assert e.lane_runs==2 and first.run_id!=second.run_id
        third=done(s,s.submit('20261013',Phase.MANUAL,lanes=[Lane.US_MAPPING]))
        assert e.lane_runs==2 and third.run_id==second.run_id
    finally:s.stop()


@pytest.mark.parametrize('order',[('US_MAPPING','OVERSOLD'),('OVERSOLD','US_MAPPING')])
@pytest.mark.parametrize('member_time',['2026-10-23T05:00:00+08:00','2026-10-23T06:30:00+08:00'])
def test_repair_r1_nonempty_lanes_keep_own_asof_evidence_and_us_api_times(tmp_path,order,member_time):
    from copy import deepcopy
    from test_us_hk_selection_closure import fixture_batch
    from test_us_hk_compact import saved_result,client_for
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.service import validate_selected_evidence
    c,b=fixture_batch(tmp_path);us=run_us_mapping(c,b);c['phase']='NEXT_DAY'
    c['scope_refs'].update(source_cutoff='2026-10-23T05:00:00+08:00',source_execution_cutoff=c['cutoff'],processing_cutoff='2026-10-23T06:05:00+08:00')
    up=saved_result(c,us)
    oc=deepcopy(c);oc['cutoff']='2026-10-23T07:00:00+08:00'
    oc['scope_refs'].update(run_id='oversold',requested_lanes=['OVERSOLD'],source_cutoff=oc['cutoff'],merge_phase_lanes=True)
    for k in ['source_execution_cutoff','processing_cutoff']:oc['scope_refs'].pop(k)
    ov=deepcopy(us);ov.update(lane='OVERSOLD',selection=None,run_id='oversold',state='READY',gaps=[])
    ov['evidence_refs']=[dict(evidence_id='oversold_ref',owner='fixture',role='OVERSOLD_SOURCE',verification='VERIFIED',sha256='c'*64,artifact_ref='fixture',available_at='2026-10-23T06:30:00+08:00')]
    ov['rows']=[dict(market='HK_CONNECT',symbol='HK.00002',decision='SELECTED',reason='FROZEN_VALID_OVERSOLD',evidence_ids=['oversold_ref'],available_at='2026-10-23T06:30:00+08:00',membership=dict(verification='VERIFIED',owner='fixture',sha256='c'*64,eligible=True,effective_from='20261023',effective_through='20261023',available_at=member_time))]
    op=saved_result(oc,ov);before={p.run_id:p.model_dump(mode='json') for p in [up,op]}
    s=service(tmp_path/'store')
    for name in order:s._commit_plan(up if name=='US_MAPPING' else op)
    saved=s.store.get_plan('20261023','NEXT_DAY');validate_selected_evidence(saved)
    assert [(x.symbol,x.decision.value) for x in sorted(saved.stocks,key=lambda x:x.symbol)]==[('HK.00001','SELECTED'),('HK.00002','SELECTED')]
    assert saved.counts.selected==2
    assert saved.changes['phase_lane_contexts']['OVERSOLD']['cutoff']==oc['cutoff']
    assert saved.changes['phase_lane_contexts']['US_MAPPING']['cutoff']==c['cutoff']
    data=client_for(saved).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
    assert data['counts']['selected']==1
    assert data['lane_sources']['source_execution_cutoff']==c['cutoff']
    assert data['lane_sources']['processing_cutoff']=='2026-10-23T06:05:00+08:00'
    assert data['lane_sources']['source_cutoff']=='2026-10-23T05:00:00+08:00'
    assert all(p.model_dump(mode='json')==before[p.run_id] for p in [up,op])


@pytest.mark.parametrize('case',['etf_missing_ref','excluded_missing_ref'])
def test_repair_r1_actual_service_context_or_excluded_reference_cannot_veto(tmp_path,case):
    from copy import deepcopy
    import time
    from test_us_hk_selection_closure import fixture_batch,source
    from test_us_hk_compact import client_for
    from v4.manager_workbench.config import WorkbenchConfig
    from v4.manager_workbench.contracts import Coverage,Phase
    from v4.manager_workbench.inputs.validation import batch as input_batch
    from v4.manager_workbench.service import create_service,project_preopen_lane
    c,b=fixture_batch(tmp_path);extra=source(b,'SOXX' if case.startswith('etf') else 'AMD')
    extra['relations']=deepcopy(source(b)['relations']);extra['evidence_ids']=['missing_ref'];extra['relations'][0]['evidence_ids']=[]
    if case.startswith('excluded'):extra['relations'][0]['current_validity']='EXCLUDED_CURRENT'
    class Adapter:
        def prepare_context(self,ctx):
            ctx.source_sessions=dict(c['source_sessions']);ctx.scope_refs.update({k:v for k,v in c['scope_refs'].items() if k!='run_id'});return ctx
        def load(self,lane,context):return input_batch(context,lane,deepcopy(b['records']),b['evidence_refs'],b['scope_description'],Coverage(**b['coverage']),[],b['universe_ref'])
    s=create_service(WorkbenchConfig(state_root=tmp_path/'derived',rules_version=c['rules_version']),Adapter(),engines,object())
    try:
        job=s.submit(c['target_date'],Phase.RETROSPECTIVE,cutoff=datetime.fromisoformat(c['cutoff']),lanes=[Lane.US_MAPPING]);deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            final=s.jobs.get(job.job_id)
            if final.state.value not in {'QUEUED','RUNNING'}:break
            time.sleep(.01)
        assert final.state.value in {'SUCCEEDED','PARTIAL'},final.failure_code
        saved=s.store.read_plan(final.run_id);lane=saved.lanes[0];before=lane.model_dump(mode='json')
        assert saved.counts.selected==1 and lane.selection.strict_decisions[0].evidence_ids==['source']
        paths=lane.selection.candidates[0].paths
        assert any('missing_ref' in p.evidence_ids for p in paths)
        projected=project_preopen_lane(lane,cutoff='2026-10-23T07:00:00+08:00')
        assert projected.selection.counts['selected']==1 and lane.model_dump(mode='json')==before
        data=client_for(saved).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
        assert data['counts']['selected']==1
    finally:s.stop()


@pytest.mark.parametrize('order',[('US_MAPPING','OVERSOLD'),('OVERSOLD','US_MAPPING')])
def test_repair_r1_two_actual_jobs_keep_original_lane_input_context(tmp_path,monkeypatch,order):
    from copy import deepcopy
    import time
    from test_us_hk_selection_closure import fixture_batch
    from test_us_hk_compact import client_for
    from v4.manager_workbench.config import WorkbenchConfig
    from v4.manager_workbench.contracts import Coverage,Phase
    from v4.manager_workbench.inputs.validation import batch as input_batch
    from v4.manager_workbench.service import create_service
    c,b=fixture_batch(tmp_path)
    # NEXT_DAY's actual entry requires the full V3 48-symbol daily contract.
    import hashlib,json
    from v4.manager_workbench.inputs.us_universe import build_us_universe_contract
    universe=build_us_universe_contract();symbols=universe['symbols']
    original_symbols={r['us_symbol'] for r in b['records']}
    template=next(r for r in b['records'] if r['us_symbol']=='AMD')
    for symbol in symbols:
        if symbol in original_symbols:continue
        record=deepcopy(template);record['us_symbol']=symbol;record['quote']['symbol']=symbol;b['records'].append(record)
    scope=c['scope_refs']['US_MAPPING'];scope.update(configured_symbols=symbols,universe_version=universe['version'],universe_contract=universe,universe_contract_sha256=universe['contract_sha256'])
    scope['universe_ref']=b['universe_ref']='fixture:US_MAPPING_V3:20261023'
    b['coverage']=dict(scope_count=48,observed_count=48)
    contract=dict(schema_version='v4.manager_workbench.us_mapping_daily_run_contract.v1',state='VERIFIED',gaps=[],mode='NEXT_DAY',target_hk_date=c['target_date'],cutoff=c['cutoff'],us_source_session=c['source_sessions']['us'],
        universe=dict(version=universe['version'],symbol_count=48,contract_sha256=universe['contract_sha256'],symbols_sha256=hashlib.sha256(json.dumps(symbols).encode()).hexdigest()),
        owners=dict(quote=dict(owner='fixture',artifact_sha256='a'*64,receipt_sha256='a'*64,manifest_sha256='a'*64,available_at='2026-10-23T05:00:00+08:00'),connect=dict(target_eligibility='VERIFIED')))
    contract['contract_sha256']=hashlib.sha256(json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    c['scope_refs']['US_MAPPING_RUN_CONTRACT_V1']=contract
    ref=dict(evidence_id='oversold_ref',owner='fixture',role='OVERSOLD_SOURCE',verification='VERIFIED',sha256='c'*64,artifact_ref='fixture',available_at='2026-10-23T06:30:00+08:00')
    row=dict(market='HK_CONNECT',symbol='HK.00002',decision='SELECTED',reason='FROZEN_VALID_OVERSOLD',evidence_ids=['oversold_ref'],available_at=ref['available_at'],membership=dict(verification='VERIFIED',owner='fixture',sha256='c'*64,eligible=True,effective_from='20261023',effective_through='20261023',available_at=ref['available_at']))
    class Adapter:
        def prepare_context(self,ctx):
            ctx.source_sessions=dict(c['source_sessions']);wanted=ctx.scope_refs['requested_lanes']
            ctx.scope_refs.update({k:v for k,v in c['scope_refs'].items() if k not in {'run_id','requested_lanes'}})
            ctx.scope_refs.update(requested_lanes=wanted,merge_phase_lanes=True,source_cutoff='2026-10-23T05:00:00+08:00' if wanted==['US_MAPPING'] else ctx.cutoff)
            return ctx
        def load(self,lane,ctx):
            if lane==Lane.US_MAPPING:return input_batch(ctx,lane,deepcopy(b['records']),b['evidence_refs'],b['scope_description'],Coverage(**b['coverage']),[],b['universe_ref'])
            if lane==Lane.OVERSOLD:return input_batch(ctx,lane,[row],[ref],'frozen accepted lane',Coverage(scope_count=1,observed_count=1),[],'frozen:oversold')
            raise KeyError(lane)
    class FrozenEngine:
        __name__='v4.manager_workbench.engines.frozen_lane_test'
        load_inputs=staticmethod(engines.load_inputs)
        merge_decisions=staticmethod(engines.merge_decisions)
        def run_lanes(self,ctx,inputs,audit):
            if 'US_MAPPING' in inputs:return engines.run_lanes(ctx,inputs,audit)
            inp=inputs['OVERSOLD']
            return {'OVERSOLD':LaneResult(lane='OVERSOLD',state='READY',rows=[row],coverage=inp.coverage,evidence_refs=inp.evidence_refs,input_sha256=inp.input_sha256,rules_version=ctx.rules_version,run_id=ctx.scope_refs['run_id'])}
    monkeypatch.setattr('v4.manager_workbench.service.now',lambda:'2026-10-23T08:00:00+08:00')
    s=create_service(WorkbenchConfig(state_root=tmp_path/'derived',rules_version=c['rules_version']),Adapter(),FrozenEngine(),object())
    try:
        for name in order:
            at=c['cutoff'] if name=='US_MAPPING' else '2026-10-23T07:00:00+08:00'
            job=s.submit(c['target_date'],Phase.NEXT_DAY,cutoff=datetime.fromisoformat(at),lanes=[Lane(name)])
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                final=s.jobs.get(job.job_id)
                if final.state.value not in {'QUEUED','RUNNING'}:break
                time.sleep(.01)
            assert final.state.value in {'SUCCEEDED','PARTIAL'},final.failure_code
        saved=s.store.get_plan(c['target_date'],'NEXT_DAY')
        assert saved.counts.selected==2
        assert saved.changes['phase_lane_contexts']['OVERSOLD']['cutoff']=='2026-10-23T07:00:00+08:00'
        assert saved.changes['phase_lane_contexts']['US_MAPPING']['cutoff']==c['cutoff']
        data=client_for(saved).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
        assert data['counts']['selected']==1 and data['lane_sources']['source_execution_cutoff']==c['cutoff']
        assert data['lane_sources']['processing_cutoff']=='2026-10-23T08:00:00+08:00'
    finally:s.stop()
