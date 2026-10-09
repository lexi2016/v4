"""Portable synthetic owner regressions; no Mac deployment or natural-run claim."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import sys

import pytest

from v4.manager_research import workspace as w
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS

DAY = '20261008'
NOW = datetime.fromisoformat('2026-10-08T09:28:00+08:00')
END = datetime.fromisoformat('2026-10-08T09:30:00+08:00')


def current():
    return dict(target_trade_date=DAY, input_identity='a'*64, semantic_version='fixture',
                plan_context={'research_cutoff':NOW.isoformat()}, gaps=[], stocks=[],
                existing_material_coverage={}, summary={}, lanes=[], **FLAGS)


def owner(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'manager')
    svc = SimpleNamespace(store=store)
    monkeypatch.setattr(w, 'get_workspace', lambda *args, **kwargs: current())
    monkeypatch.setattr(w, '_now', lambda:'2026-10-08T01:28:01+00:00')
    return svc


@pytest.fixture
def assessed_owner(tmp_path, monkeypatch):
    """Explicit R3 owner calls need actual assessed input, even for zero picks."""
    from test_manager_announcement_parity_20261008 import _FixtureService, _client, _fixture, _import, consumer, api
    class ImportClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    service = _FixtureService(tmp_path / 'assessed-manager')
    monkeypatch.setattr(api, 'datetime', ImportClock)
    monkeypatch.setattr(consumer, '_now', lambda: NOW.isoformat())
    try:
        with _client(service) as client:
            _, registration = _fixture(service, disposition='NOT_SELECTED')
            _import(client, registration)
        yield service
    finally:
        service.close()


def test_manual_saved_plan_never_becomes_scheduled_by_fast_path(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    manual=w.refresh_workspace_plan(svc, DAY)
    scheduled=w.refresh_workspace_plan(svc, DAY, execution_kind='SCHEDULED_PREOPEN',now=NOW,deadline=END)
    assert scheduled['plan_product']['run_id'] != manual['plan_product']['run_id']
    assert scheduled['plan_product']['execution_kind']=='SCHEDULED_PREOPEN'
    assert scheduled['workspace_plan_attempt']['run_id']==scheduled['plan_product']['run_id']
    assert scheduled['workspace_plan_attempt']['execution_kind']=='SCHEDULED_PREOPEN'


def test_duplicate_scheduled_owner_returns_same_sealed_attempt(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    first=w.refresh_workspace_plan(svc,DAY,execution_kind='SCHEDULED_PREOPEN',now=NOW,deadline=END)
    second=w.refresh_workspace_plan(svc,DAY,execution_kind='SCHEDULED_PREOPEN',now=NOW+timedelta(seconds=2),deadline=END)
    assert second['plan_product']['status']=='ALREADY_MATERIALIZED'
    assert second['plan_product']['run_id']==first['plan_product']['run_id']
    assert second['plan_product']['execution_kind']=='SCHEDULED_PREOPEN'
    assert second['plan_product']['consumed'] is True
    assert second['workspace_plan_attempt']==first['workspace_plan_attempt']
    assert second['daily_channels']['channels'][1]['execution_kind']=='SCHEDULED_PREOPEN'
    assert second['daily_channels']['channels'][1]['run_id']==first['plan_product']['run_id']
    assert first['plan_product']['run_readback']['status']=='VERIFIED'
    assert first['plan_product']['run_readback']['owner_attempt_run_id']==first['plan_product']['run_id']
    assert 'RESEARCH_ONLY' not in first['plan_product']['run_readback']
    assert second['plan_product']['run_readback']['run_id']==first['plan_product']['run_readback']['run_id']
    assert second['plan_product']['run_readback']['owner_attempt_sha256']==first['plan_product']['run_readback']['owner_attempt_sha256']


def test_saved_plan_readback_stays_separate_from_a_later_failed_attempt(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    first=w.refresh_workspace_plan(svc,DAY)
    saved_run=first['plan_product']['run_id']
    latest_path=svc.store.root/'workspace_plan_runs'/DAY/'latest.json'
    latest=svc.store._read(latest_path)
    failed=w.seal_attempt({**latest,'run_id':'9'*32,'state':'FAILED',
        'started_at':'2026-10-08T01:30:00+00:00','finished_at':'2026-10-08T01:30:01+00:00',
        'failure_reasons':['SYNTHETIC_LATER_FAILURE']})
    svc.store._write_atomic(latest_path,failed)
    current_value=current()
    read=w._readback_plan(svc.store,DAY,current_value)
    product=read['plan_product'];attempt=read['workspace_plan_attempt']
    assert product['run_readback']['status']=='VERIFIED'
    assert product['run_readback']['run_id']==saved_run
    assert product['run_readback']['owner_attempt_run_id']==saved_run
    assert product['run_readback']['artifact_sha256']==product['sha256']
    assert attempt['state']=='FAILED' and attempt['run_id']=='9'*32


def test_late_catchup_plan_preserves_server_execution_context(assessed_owner, monkeypatch):
    svc=assessed_owner
    started=datetime.fromisoformat('2026-10-08T10:00:00+08:00')
    finished='2026-10-08T02:00:01+00:00'
    monkeypatch.setattr(w,'_now',lambda:finished)
    context={'trigger_kind':'SCHEDULED','timing':'LATE_CATCHUP',
        'scheduled_for':'2026-10-08T10:00:00+08:00','natural_run_verified':False}
    result=w.refresh_workspace_plan(svc,DAY,execution_kind='MANUAL_REFRESH',now=started,
        execution_context=context)
    assert result['plan_product']['status']=='CURRENT',result.get('failure_reasons')
    saved=svc.store._read(svc.store.root/'workspace_plans'/DAY/'latest.json')
    attempt=svc.store._read(svc.store.root/'workspace_plan_runs'/DAY/(saved['run_id']+'.json'))
    assert saved['execution_context']=={
        **context,'started_at':started.isoformat(timespec='microseconds'),'finished_at':finished}
    assert attempt['execution_context']==saved['execution_context']
    assert result['plan_product']['execution_context']==saved['execution_context']


def test_same_plan_us_attempt_overlay_keeps_saved_matches_and_exposes_late_failure():
    saved={'us_mapping_research':{'daily_run':{'status':'COMPLETED','run_id':'old',
        'generated_at':'2026-10-08T06:00:00+08:00','matches':[{'us_symbol':'NVDA'}]}}}
    current={'us_mapping_research':{'daily_run':{'status':'FAILED','run_id':'old',
        'generated_at':'2026-10-08T06:00:00+08:00','matches':[{'us_symbol':'NVDA'}],
        'latest_attempt':{'status':'FAILED','trigger_id':'a'*64,
            'finished_at':'2026-10-08T10:00:00+08:00','execution_context':{'trigger_id':'a'*64}}}}}
    merged=w._overlay_us_mapping_attempt(saved,current,'2026-10-08T09:30:00+08:00')
    assert merged['daily_run']['matches']==[{'us_symbol':'NVDA'}]
    assert merged['daily_run']['latest_attempt']['trigger_id']=='a'*64
    assert merged['daily_run']['latest_attempt_after_plan_cutoff'] is True
    assert merged['daily_run']['latest_attempt_affects_saved_plan'] is False


def test_saved_plan_attempt_overlay_uses_saved_cutoff_not_current_get_cutoff(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    saved_cutoff='2026-10-08T09:00:00+08:00'
    current_cutoff='2026-10-08T10:00:00+08:00'
    saved_at=datetime.fromisoformat(saved_cutoff)
    def read_at(_service,date,*,include_saved,now,**kwargs):
        value=current()
        value['plan_context']={'research_cutoff':saved_cutoff if now==saved_at else current_cutoff}
        value['us_mapping_research']={'daily_run':{'status':'COMPLETED','run_id':'1'*32,
            'generated_at':'2026-10-08T08:00:00+08:00','artifact_sha256':'2'*64,
            'matches':[{'us_symbol':'NVDA'}], 'latest_attempt':{
                'status':'FAILED','trigger_id':'3'*64,
                'finished_at':'2026-10-08T09:30:00+08:00',
                'execution_context':{'trigger_id':'3'*64}}}}
        return value
    monkeypatch.setattr(w,'get_workspace',read_at)
    monkeypatch.setattr(w,'_now',lambda:'2026-10-08T01:00:01+00:00')
    w.refresh_workspace_plan(svc,DAY,execution_kind='MANUAL_REFRESH',now=saved_at)
    latest=read_at(svc,DAY,include_saved=False,now=datetime.fromisoformat(current_cutoff))
    result=w._readback_plan(svc.store,DAY,latest)
    daily=result['us_mapping_research']['daily_run']
    assert daily['latest_attempt_after_plan_cutoff'] is True
    assert daily['latest_attempt_affects_saved_plan'] is False


def test_retrospective_plan_keeps_real_read_and_generation_time_explicit(assessed_owner, monkeypatch):
    svc=assessed_owner
    actual=datetime.fromisoformat('2026-10-09T10:00:00+08:00')
    observed=[]
    original_read=w.get_workspace
    def capture_read(service,date,*,include_saved,now,**kwargs):
        observed.append(now)
        return original_read(service,date,include_saved=include_saved,now=now,**kwargs)
    monkeypatch.setattr(w,'get_workspace',capture_read)
    monkeypatch.setattr(w,'_now',lambda:'2026-10-09T02:00:01+00:00')
    result=w.refresh_workspace_plan(svc,'20261008',execution_kind='MANUAL_REFRESH',now=actual,
        execution_context={'trigger_kind':'MANUAL','timing':'RETROSPECTIVE',
            'scheduled_for':None,'natural_run_verified':False})
    assert result['plan_product']['status']=='CURRENT',result.get('failure_reasons')
    cutoff=datetime.fromisoformat(result['plan_context']['research_cutoff'])
    generated=datetime.fromisoformat(result['plan_product']['generated_at'].replace('Z','+00:00'))
    assert observed==[actual]
    assert cutoff==actual
    assert generated>=actual.astimezone(generated.tzinfo)
    assert result['plan_product']['execution_context']['research_cutoff_policy']==\
        'ACTUAL_OWNER_EXECUTION_CUTOFF_RETROSPECTIVE'


def test_timeout_suppression_is_request_scoped_and_skips_second_us_reader_call(monkeypatch):
    class Reader:
        def __init__(self): self.calls = 0
        def read_exact_session(self, session_date):
            self.calls += 1
            raise AssertionError('timed-out reader must not be entered by plan projection')

    reader = Reader()
    service = SimpleNamespace(_workspace_us_market_reader=reader)
    request = {
        'target_trade_date': DAY,
        'execution_status': 'US_MAPPING_OWNER_READ_TIMEOUT',
        'bypass_reader': True,
    }
    result = w._project_us_market_attention(service, DAY,
        {'research_cutoff': '2026-10-08T08:00:00+08:00'},
        us_market_request_context=request)
    assert reader.calls == 0
    assert result['status'] == 'SOURCE_FAILED'
    assert result['gaps'] == ['US_MARKET_DAILY_OWNER_NOT_RETRIED:US_MAPPING_OWNER_READ_TIMEOUT']
    assert result['bounded_owner_execution_status'] == 'US_MAPPING_OWNER_READ_TIMEOUT'


def test_workspace_us_projection_skips_reader_busy_in_bounded_owner_lane(monkeypatch):
    import threading
    from v4.manager_research import us_mapping_research

    class Reader:
        def __init__(self): self.calls = 0
        def read_exact_session(self, session_date):
            self.calls += 1
            raise AssertionError('reader already held by bounded US owner lane')

    reader = Reader()
    active = SimpleNamespace(
        service=SimpleNamespace(_workspace_us_market_reader=reader),
        done=threading.Event())
    monkeypatch.setattr(us_mapping_research, '_ACTIVE_BUILD', active)
    service = SimpleNamespace(_workspace_us_market_reader=reader)
    result = w._project_us_market_attention(service, DAY,
        {'research_cutoff': '2026-10-08T08:00:00+08:00'})
    assert reader.calls == 0
    assert result['status'] == 'SOURCE_FAILED'
    assert result['gaps'] == ['US_MARKET_DAILY_OWNER_NOT_RETRIED:US_MAPPING_OWNER_READ_BUSY']
    assert result['bounded_owner_execution_status'] == 'US_MAPPING_OWNER_READ_BUSY'


def test_saved_plan_wrong_owner_is_rejected_even_with_consistent_hash(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    w.refresh_workspace_plan(svc,DAY)
    path=svc.store.root/'workspace_plans'/DAY/'latest.json'
    product=svc.store._read(path);product['owner']='DifferentOwner'
    product['sha256']=w.digest({k:v for k,v in product.items() if k!='sha256'})
    svc.store._write_atomic(path,product)
    with pytest.raises(ValueError,match='WORKSPACE_STORED_PLAN_INVALID'):
        w._read_plan(svc.store,DAY)


def test_future_saved_generation_is_not_reused_at_an_earlier_scheduled_clock(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    monkeypatch.setattr(w,'_now',lambda:'2026-10-08T01:29:00+00:00')
    first=w.refresh_workspace_plan(svc,DAY,execution_kind='SCHEDULED_PREOPEN',now=NOW,deadline=END)
    monkeypatch.setattr(w,'_now',lambda:'2026-10-08T01:28:03+00:00')
    second=w.refresh_workspace_plan(svc,DAY,execution_kind='SCHEDULED_PREOPEN',now=NOW+timedelta(seconds=2),deadline=END)
    assert second['plan_product']['run_id']!=first['plan_product']['run_id']
    assert second['plan_product']['status']=='CURRENT'


@pytest.mark.parametrize('kind,begin,end', [
    ('SCHEDULED_PREOPEN','2026-10-08T09:28:00+08:00','2026-10-08T09:30:00+08:00'),
    ('SCHEDULED_MORNING','2026-10-08T08:00:00+08:00','2026-10-08T09:25:00+08:00'),
])
def test_terminal_deadline_failure_survives_regular_readback(tmp_path, monkeypatch, kind, begin, end):
    svc=owner(tmp_path,monkeypatch)
    deadline=datetime.fromisoformat(end)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:dict(current(),plan_context={'research_cutoff':begin}))
    clocks=iter([(deadline-timedelta(seconds=1)).isoformat(),(deadline+timedelta(seconds=1)).isoformat()])
    last=(deadline+timedelta(seconds=2)).isoformat()
    monkeypatch.setattr(w,'_now',lambda:next(clocks,last))
    with pytest.raises(TimeoutError,match='WORKSPACE_PLAN_SCHEDULED_TERMINAL_DEADLINE_EXCEEDED'):
        w.refresh_workspace_plan(svc,DAY,execution_kind=kind,now=datetime.fromisoformat(begin),deadline=deadline)
    latest=svc.store._read(svc.store.root/'workspace_plan_runs'/DAY/'latest.json')
    assert latest['state']=='FAILED'
    value=w._readback_plan(svc.store,DAY,dict(current(),plan_context={'research_cutoff':end}))
    assert value['plan_product']['consumed'] is False
    assert value['plan_product']['status']=='OWNER_ATTEMPT_UNVERIFIED'
    assert value['workspace_plan_attempt']['state']=='FAILED'


@pytest.mark.parametrize('kind,begin,end', [
    ('SCHEDULED_PREOPEN','2026-10-08T09:28:00+08:00','2026-10-08T09:30:00+08:00'),
    ('SCHEDULED_MORNING','2026-10-08T08:00:00+08:00','2026-10-08T09:25:00+08:00'),
])
def test_slow_terminal_journal_cannot_cross_boundary_and_leave_success(tmp_path,monkeypatch,kind,begin,end):
    svc=owner(tmp_path,monkeypatch);deadline=datetime.fromisoformat(end)
    clock={'now':deadline-timedelta(seconds=2)}
    monkeypatch.setattr(w,'_now',lambda:clock['now'].isoformat())
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:dict(current(),plan_context={'research_cutoff':begin}))
    original_write=svc.store._write_atomic
    def slow_terminal(path,value):
        result=original_write(path,value)
        if value.get('state')=='SUCCEEDED_EMPTY':
            clock['now']=deadline+timedelta(seconds=2)
        return result
    monkeypatch.setattr(svc.store,'_write_atomic',slow_terminal)
    with pytest.raises(TimeoutError,match='WORKSPACE_PLAN_SCHEDULED_TERMINAL_DEADLINE_EXCEEDED'):
        w.refresh_workspace_plan(svc,DAY,execution_kind=kind,now=datetime.fromisoformat(begin),deadline=deadline)
    result=w._readback_plan(svc.store,DAY,dict(current(),plan_context={'research_cutoff':end}))
    assert result['plan_product']['consumed'] is False
    assert result['workspace_plan_attempt']['state']=='FAILED'


@pytest.mark.parametrize('kind,begin,end', [
    ('SCHEDULED_MORNING','2026-10-08T08:00:00+08:00','2026-10-08T09:25:00+08:00'),
    ('SCHEDULED_PREOPEN','2026-10-08T09:28:00+08:00','2026-10-08T09:30:00+08:00'),
])
def test_scheduled_plan_and_same_attempt_survive_next_day_history(tmp_path,monkeypatch,kind,begin,end):
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'real_history'),None,None)
    monkeypatch.setattr(w,'_now',lambda:(datetime.fromisoformat(begin)+timedelta(seconds=1)).isoformat())
    try:
        saved=service.refresh_workspace_plan(DAY,execution_kind=kind,now=datetime.fromisoformat(begin),deadline=datetime.fromisoformat(end))
        result=service.get_workspace(DAY,view='historical',now=datetime.fromisoformat('2026-10-09T12:00:00+08:00'))
        assert result['plan_product']['status']=='CURRENT',result['read_context']
        assert result['plan_product']['execution_kind']==kind
        assert result['workspace_plan_attempt']==saved['workspace_plan_attempt']
        assert result['daily_channels']['channels'][1]['run_id']==saved['plan_product']['run_id']
        assert result['daily_channels']['channels'][1]['natural_run_verified'] is False
        run_path=service.store.root/'workspace_plan_runs'/DAY/(saved['plan_product']['run_id']+'.json')
        attempt=service.store._read(run_path);attempt['run_id']='0'*32
        service.store._write_atomic(run_path,w.seal_attempt(attempt))
        rejected=service.get_workspace(DAY,view='historical',now=datetime.fromisoformat('2026-10-09T12:00:00+08:00'))
        assert rejected['plan_product']['consumed'] is False
        assert rejected['read_context']['status']=='SOURCE_FAILED'
    finally:
        service.close()


def test_morning_owner_without_us_reader_keeps_other_lanes(tmp_path, monkeypatch):
    svc=owner(tmp_path,monkeypatch)
    clock=datetime.fromisoformat('2026-10-08T08:00:00+08:00')
    end=datetime.fromisoformat('2026-10-08T09:25:00+08:00')
    monkeypatch.setattr(w,'_now',lambda:'2026-10-08T00:00:01+00:00')
    value=w.refresh_workspace_plan(svc,DAY,execution_kind='SCHEDULED_MORNING',now=clock,deadline=end)
    assert value['plan_product']['consumed'] is True
    assert value['workspace_plan_attempt']['execution_kind']=='SCHEDULED_MORNING'


def test_missing_us_mapping_module_is_only_a_reference_gap(monkeypatch):
    monkeypatch.setitem(sys.modules,'v4.manager_research.us_mapping_research',None)
    read, reference, identities=w._daily_mapping_plan_reference(SimpleNamespace(),DAY,current()['plan_context'])
    assert read['mapping']['status']=='NOT_EVALUATED'
    assert read['daily_run']['status']=='CANNOT_CONFIRM'
    assert read['daily_run']['coverage']['matched_hk_relation_count'] is None
    assert reference['status']=='NOT_CONSUMED'
    assert identities==[]
    assert reference['reason'].startswith('US_MAPPING_READER_UNAVAILABLE:')


def test_service_delegates_original_analysis_and_catalog_owners(monkeypatch):
    from v4.manager_research import announcement_analysis as analysis
    from v4.manager_research import workspace_announcements as announcements
    service=object.__new__(ManagerResearchJobService)
    calls=[]
    monkeypatch.setattr(analysis,'read',lambda owner,target,publication: calls.append(('read',owner,target,publication)) or {'ok':'read'})
    monkeypatch.setattr(analysis,'import_product',lambda owner,product: calls.append(('import',owner,product)) or {'ok':'import'})
    monkeypatch.setattr(announcements,'read_date_catalog',lambda owner,target,publication: calls.append(('catalog',owner,target,publication)) or {'ok':'catalog'})
    assert service.get_announcement_analysis(DAY,'2026-10-07')=={'ok':'read'}
    assert service.import_announcement_analysis({'a':1})=={'ok':'import'}
    assert service.get_announcement_date_catalog(DAY,'2026-10-07')=={'ok':'catalog'}
    assert all(call[1] is service for call in calls)


def test_publication_date_reaches_original_capture_owner(monkeypatch):
    from v4.manager_research import workspace_announcements as announcements
    service=object.__new__(ManagerResearchJobService)
    monkeypatch.setattr(announcements,'refresh',lambda owner,target,**kwargs: kwargs)
    result=service.refresh_announcements(DAY,source_scope='EASTMONEY_HK_DATE_CATALOG',publication_date='2026-10-07')
    assert result['publication_date']=='2026-10-07'


def test_three_independent_dates_reach_workspace_context(monkeypatch):
    seen=[]
    monkeypatch.setattr(w,'_compute_workspace',lambda service,date,**kwargs: seen.append(kwargs['context']) or {
        'target_trade_date':date,'plan_context':kwargs['context'],'gaps':[],'stocks':[]})
    result=w.get_workspace(SimpleNamespace(),DAY,now=NOW,include_saved=False,
        selection_date='20261007',announcement_date='20261006')
    assert seen[0]['plan_trade_date']=='20261008'
    assert seen[0]['announcement_publication_date']=='2026-10-06'
    assert result['date_bindings']==dict(selection_date='20261007',announcement_date='20261006',plan_date='20261008')


def test_read_coalescing_separates_publication_dates(monkeypatch):
    class Reads:
        def __init__(self): self.keys=[]
        def run(self,key,func,**kwargs):self.keys.append(key);return func()
    service=object.__new__(ManagerResearchJobService);service._workspace_reads=Reads()
    monkeypatch.setattr(w,'get_workspace',lambda owner,target,**kwargs:kwargs)
    a=service.get_workspace(DAY,announcement_date='20261006',selection_date='20261007')
    b=service.get_workspace(DAY,announcement_date='20261007',selection_date='20261007')
    assert a['announcement_date']!=b['announcement_date']
    assert service._workspace_reads.keys[0]!=service._workspace_reads.keys[1]
