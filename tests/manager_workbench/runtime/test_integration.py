import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import RunContext, Phase, Lane
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.source_bindings import resolve_bindings, US_SYMBOLS
from v4.manager_workbench.inputs.validation import owner_digest

ROOT=Path(__file__).resolve().parents[3]
HANDOFF=ROOT/'docs/handoff/manager-workbench-implementation-20261013/deployment-deltas'


def write(root,relative,value):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def config(tmp_path):
    return WorkbenchConfig(state_root=tmp_path/'derived',manager_root=tmp_path/'manager',shared_root=tmp_path/'shared',
        stage_root=tmp_path/'stage',us_root=tmp_path/'us',relation_root=tmp_path/'relations',dynamic_source_bindings=True)


def context(day='20261013',cutoff='2026-10-13T10:00:00+08:00'):
    return RunContext(target_date=day,phase=Phase.MANUAL,cutoff=cutoff,trigger='MANUAL',rules_version='POSITIVE_OPERATING_RESEARCH_V1')


def monthly(cfg,available='2026-10-12T19:00:00+08:00'):
    from v4.manager_workbench.inputs.source_bindings import OWNER
    directory='universes/20261012/HK_CONNECT_FULL_MARKET.authority/run'
    a='universes/20261012/HK_CONNECT_FULL_MARKET.json';c=directory+'/capture.json'
    capture=dict(codes=['HK.00001'],membership_source_payload={'fixture':'original-owner'},production_allowed=False)
    capture['membership_source_sha256']=owner_digest(capture['membership_source_payload'])
    capture['capture_sha256']=owner_digest(capture)
    csha=write(cfg.shared_root,c,capture)
    artifact=dict(codes=['HK.00001'],code_count=1,market='HK_CONNECT',production_allowed=False,orders_sent=False)
    asha=write(cfg.shared_root,a,artifact)
    current='universes/20261012/HK_CONNECT_FULL_MARKET.current.json';current_sha=write(cfg.shared_root,current,{'run_id':'run'})
    publication=dict(available_at=available,current_relative=current,current_sha256=current_sha)
    write(cfg.shared_root,directory+'/publication.json',publication)
    manifest=dict(effective_date='20261012',authority_role='HK_CONNECT_FULL_MARKET_AUTHORITY',status='READY',
        producer_owner={'workload_id':OWNER},artifact_relative=a,artifact_sha256=asha,capture_relative=c,
        capture_sha256=capture['capture_sha256'],production_allowed=False)
    msha=write(cfg.shared_root,directory+'/manifest.json',manifest)
    write(cfg.shared_root,directory+'/receipt.json',dict(manifest_sha256=msha,artifact_sha256=asha,capture_sha256=capture['capture_sha256'],production_allowed=False))
    assert csha!=capture['capture_sha256']
    return c


def panel(cfg,day):
    write(cfg.shared_root,f'assets/hk_0_2/panels/{day}-owner/manifest.json',dict(panel_max_date=day,
        manifest_prepared_at=day[:4]+'-'+day[4:6]+'-'+day[6:]+'T18:00:00+08:00'))


def us(cfg):
    session='20261012';relative=f'research/peripherals/{session}/external_finance.json'
    qsha=write(cfg.us_root,relative,dict(market_snapshot={'capture_session_date':session,'captured_at':'2026-10-13T05:00:00+08:00'}))
    write(cfg.us_root,'research/peripherals/manifest.json',{relative:qsha})
    write(cfg.us_root,f'receipts/research/peripherals/{session}/external_finance.json',{'payload_sha256':qsha})
    relation=dict(us_symbol='NVDA',hk_symbol='HK.00001',relationship_type='NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER',direction='INTEGRATION',available_at='2026-10-11T09:00:00+08:00')
    evidence=dict(relations=[relation]);evidence['artifact_sha256']=owner_digest(evidence)
    esha=write(cfg.relation_root,cfg.relation_evidence_relative,evidence)
    write(cfg.relation_root,cfg.relation_review_relative,dict(status='PASS',reviewed_at='2026-10-11T10:00:00+08:00',reviewer_identity='independent-fixture',
        evidence_file_sha256=esha,declared_artifact_sha256=evidence['artifact_sha256'],recomputed_artifact_sha256=evidence['artifact_sha256'],
        reviewed_pairs=[relation],safety={'production_allowed':False}))


def test_automatic_dates_monthly_raw_and_content_sha_and_cutoff(tmp_path):
    cfg=config(tmp_path);capture=monthly(cfg);panel(cfg,'20261012');panel(cfg,'20261013')
    adapter=NativeAdapters(cfg);ctx=adapter.prepare_context(context())
    assert ctx.source_sessions['hk_price']=='20261012'
    assert '20261012-owner' in ctx.scope_refs['owner_bindings']['hk_panel']['manifest_relative']
    assert adapter.membership(ctx)[0]=={'HK.00001'}
    nextday=adapter.prepare_context(context('20261014','2026-10-14T10:00:00+08:00'))
    assert '20261013-owner' in nextday.scope_refs['owner_bindings']['hk_panel']['manifest_relative']
    early=adapter.prepare_context(context(cutoff='2026-10-12T18:00:00+08:00'))
    assert 'membership' not in early.scope_refs['owner_bindings']
    assert 'membership' in early.scope_refs['owner_binding_gaps']
    nextmonth=adapter.prepare_context(context('20261102','2026-11-02T10:00:00+08:00'))
    assert 'membership' not in nextmonth.scope_refs['owner_bindings']
    # A date-bound job must fail if a source it froze is overwritten.
    (cfg.shared_root/capture).write_text('{}')
    assert adapter.membership(ctx)[0]==set()


def test_no_cross_date_latest_and_unknown_unit_preserved(tmp_path):
    cfg=config(tmp_path);panel(cfg,'20261013')
    ctx=NativeAdapters(cfg).prepare_context(context())
    assert 'hk_panel' not in ctx.scope_refs['owner_bindings']
    assert 'hk_panel' in ctx.scope_refs['owner_binding_gaps']


def test_us_exact_owner_manifest_review_pairs_fixed33_and_frozen_bytes(tmp_path):
    cfg=config(tmp_path);us(cfg);adapter=NativeAdapters(cfg);ctx=adapter.prepare_context(context())
    pin=ctx.scope_refs['owner_bindings']['us_mapping']
    assert tuple(pin['configured_symbols'])==US_SYMBOLS and len(US_SYMBOLS)==33
    assert pin['relation_projection']['cards'][0]['reviewer_identity']=='independent-fixture'
    assert pin['relation_projection']['cards'][0]['available_at']=='2026-10-11T10:00:00+08:00'
    write(cfg.relation_root,cfg.relation_review_relative,{'status':'PASS'})
    with pytest.raises(ValueError,match='OWNER_BOUND_BYTES_CHANGED'):adapter.us_mapping(ctx)


def test_stage_index_freezes_exactdate_entries(tmp_path):
    cfg=config(tmp_path)
    write(cfg.stage_root,'selection_latest.json',{'entries':{'old':{'trade_date':'20261012','market':'HK_CONNECT'},
        'actual':{'trade_date':'20261013','market':'HK_CONNECT','run_id':'one'}}})
    adapter=NativeAdapters(cfg);ctx=adapter.prepare_context(context())
    assert list(ctx.scope_refs['owner_bindings']['stage']['entries'])==['actual']
    write(cfg.stage_root,'selection_latest.json',{'entries':{}})
    assert list(ctx.scope_refs['owner_bindings']['stage']['entries'])==['actual']
    assert adapter.prepare_context(context()).scope_refs['owner_bindings']['stage']['entries']=={}


def load_deltas():
    spec=importlib.util.spec_from_file_location('mwb_deltas',HANDOFF/'prepare_manager_deltas.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def test_api_active_increment_preserves_parallel_stage_bytes():
    mod=load_deltas();relative='apps/api/v35_api/app.py'
    old=(HANDOFF/'api-active-before'/relative).read_text();new=(HANDOFF/'api-active-candidate'/relative).read_text()
    assert mod.api_patch(old)==new
    # Apart from the independently bounded manager patch, all R10 bytes survive.
    assert 'stage_center_research_binding_path' in new
    assert '_load_manager_research_components' not in new
    assert 'manager_research_router import' not in new
    assert 'ManagerResearchJobService' not in new
    assert 'manager_workbench_config' in new
    with pytest.raises(ValueError):mod.api_patch(new)


def test_scheduler_active_increment_preserves_other_hooks_and_excludes_old_owner():
    mod=load_deltas();relative='ops/run_v35_macos_scheduler_daemon.py'
    old=(HANDOFF/'scheduler-active-before'/relative).read_text();new=(HANDOFF/'scheduler-active-candidate'/relative).read_text()
    assert mod.scheduler_patch(old)==new
    assert old.replace('        announcement_hook = AnnouncementCycleHook.from_environment(clock=now)',
        new[new.index('        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH"'):new.index('    except DaemonConfigurationError as error:',new.index('V4_MANAGER_WORKBENCH_CONFIG_PATH'))].rstrip())==new
    # Execute the exact new owner dispatch branch, with a forbidden old hook.
    block=new[new.index('        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH"'):new.index('    except DaemonConfigurationError as error:',new.index('V4_MANAGER_WORKBENCH_CONFIG_PATH'))]
    import textwrap
    from unittest.mock import patch
    class Forbidden:
        @classmethod
        def from_environment(cls,**kwargs):raise AssertionError('old owner initialized')
    with patch.dict('os.environ',{'V4_MANAGER_WORKBENCH_CONFIG_PATH':'fixture'}), patch('v4.manager_workbench.supervisor.WorkbenchHook.from_environment',return_value='new'):
        namespace={'os':__import__('os'),'AnnouncementCycleHook':Forbidden,'now':lambda:None}
        exec(textwrap.dedent(block),namespace)
        assert namespace['announcement_hook']=='new'


def test_supervisor_has_no_child_wall_limit_and_shutdown_waits(tmp_path):
    from v4.manager_workbench.supervisor import WorkbenchHook
    from test_native_pipeline import fixture, wait
    from v4.manager_workbench import engines
    cfg=fixture(tmp_path,1)
    clock=lambda:datetime.fromisoformat('2026-10-13T08:00:00+08:00')
    binding=dict(adapters=NativeAdapters(cfg),engines=engines,executor=object(),calendar=SimpleNamespace(is_hk_session=lambda d:False),stage_feed=object())
    hook=WorkbenchHook(cfg,clock=clock,binding=binding)
    job=hook.service.submit('20261013',Phase.MANUAL,lanes=[Lane.OVERSOLD])
    assert wait(hook.service,job).state.value=='SUCCEEDED'
    assert hook.once()['state']=='NOT_APPLICABLE'
    assert hook.identity['old_manager_owner_excluded'] is True
    assert not hasattr(hook,'wall_seconds') and not hasattr(hook,'popen_factory')
    hook.stop()


def test_api_assembler_real_http_and_readonly_get(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from v4.manager_workbench.binding import assemble_api
    from test_native_pipeline import fixture
    cfg=fixture(tmp_path,1)
    monkeypatch.setenv('V4_MANAGER_WORKBENCH_CONFIG_PATH','')
    app=FastAPI()
    assemble_api(app,config=cfg)
    with TestClient(app) as client:
        response=client.get('/api/v4/manager-workbench/days/20261013')
        assert response.status_code==200
        assert response.json()['schema_version']=='v4.manager_workbench.v1'
        assert app.state.manager_workbench_old_owner_excluded
        assert client.post('/api/v4/manager-research/run',json={}).status_code==404
        paths=set(app.openapi()['paths'])
        assert '/api/v4/manager-workbench/runs' in paths
        assert not any('/manager-research' in path for path in paths)
        response=client.post('/api/v4/manager-workbench/runs',json={'target_date':'20261013','phase':'MANUAL','lanes':['OVERSOLD']})
        assert response.status_code==202
        from test_native_pipeline import wait
        job=app.state.manager_workbench_service.jobs.get(response.json()['data']['job_id'])
        assert wait(app.state.manager_workbench_service,job).state.value=='SUCCEEDED'


def test_calendar_next_session_and_stage_signature_ignore_other_market_pointer_changes():
    from v4.manager_workbench.binding import CalendarAdapter,StageFeed
    calendar=CalendarAdapter()
    assert calendar.is_hk_session('20261019') is False
    assert calendar.next_hk_session('20261016')=='20261020'
    adapter=SimpleNamespace(config=SimpleNamespace(rules_version='POSITIVE_OPERATING_RESEARCH_V1'),
        prepare_context=lambda c:c,
        stage=lambda c:SimpleNamespace(records=[{'stage_run_id':'actual-run','symbol':'HK.00001','evidence_ids':[]}],evidence_refs=[],input_sha256='a'*64))
    before=StageFeed(adapter).completed_runs('20261013')
    adapter.stage=lambda c:SimpleNamespace(records=[{'stage_run_id':'actual-run','symbol':'HK.00001','evidence_ids':[]}],evidence_refs=[],input_sha256='b'*64)
    assert StageFeed(adapter).completed_runs('20261013')==before
    adapter.stage=lambda c:SimpleNamespace(records=[{'stage_run_id':'actual-run','symbol':'HK.00002','evidence_ids':[]}],evidence_refs=[],input_sha256='b'*64)
    assert StageFeed(adapter).completed_runs('20261013')!=before


def test_new_dynamic_bindings_keep_local_roots_out_of_public_snapshot(tmp_path):
    from v4.manager_workbench.api import _public
    cfg=config(tmp_path);monthly(cfg);us(cfg)
    ctx=NativeAdapters(cfg).prepare_context(context())
    public=_public(ctx.model_dump(mode='json'))
    assert str(tmp_path) not in json.dumps(public)
    assert 'source_local_path' in ctx.scope_refs['owner_bindings']['membership']
    assert NativeAdapters(cfg).membership(ctx)[0]=={'HK.00001'}


def test_mixed_announcement_owner_matches_record_evidence_in_any_order(tmp_path):
    from v4.manager_workbench.inputs.validation import batch
    from v4.manager_workbench.contracts import EvidenceRef
    cfg=config(tmp_path);adapter=NativeAdapters(cfg);ctx=context()
    refs=[EvidenceRef(evidence_id=kind,owner=kind,role='ANNOUNCEMENT_CAPTURED_BODY',sha256=sha*64,
        available_at='2026-10-12T12:00:00+08:00',verification='VERIFIED') for kind,sha in [('EASTMONEY_MIRROR','a'),('HKEX_OFFICIAL','b')]]
    records=[dict(event_id=ref.owner,symbol='HK.00001',source_kind=ref.owner,source_sha256=ref.sha256,
        evidence_ids=[ref.evidence_id],pages=[],body_complete=False) for ref in refs]
    for source_order in [refs,refs[::-1]]:
        for record_order in [records,records[::-1]]:
            shaped=adapter._engine_shape(batch(ctx,Lane.ANNOUNCEMENT,record_order,source_order,'fixture'))
            for row in shaped.records:
                assert row['owner']==row['source_kind']
                assert row['source_sha256']==next(ref.sha256 for ref in refs if ref.owner==row['source_kind'])
    # A source SHA mismatch cannot borrow another article's owner.
    wrong={**records[1],'source_sha256':'c'*64}
    shaped=adapter._engine_shape(batch(ctx,Lane.ANNOUNCEMENT,[wrong],refs,'fixture'))
    assert shaped.records[0]['owner'] is None


def test_monthly_republication_isolates_invalid_old_pointer_and_respects_cutoff(tmp_path):
    from v4.manager_workbench.inputs.source_bindings import membership
    cfg=config(tmp_path);monthly(cfg)
    root=cfg.shared_root;old='universes/20261012/HK_CONNECT_FULL_MARKET.authority/run'
    new=old.rsplit('/',1)[0]+'/run2'
    # The existing producer republished the same month, updating the date pointer.
    current='universes/20261012/HK_CONNECT_FULL_MARKET.current.json'
    current_sha=write(root,current,{'run_id':'run2'})
    for name in ['manifest.json','receipt.json','publication.json']:
        value=json.loads((root/old/name).read_text())
        if name=='publication.json':value.update(current_sha256=current_sha,available_at='2026-10-13T09:00:00+08:00')
        write(root,new+'/'+name,value)
    # capture/artifact are original immutable bytes shared by both manifests.
    pin=membership(cfg,context())
    assert any(f['relative']==new+'/receipt.json' for f in pin['checked_files'])
    with pytest.raises(ValueError,match='MONTHLY_AUTHORITY_UNAVAILABLE_BEFORE_CUTOFF'):
        membership(cfg,context(cutoff='2026-10-13T08:00:00+08:00'))
    # If a prior candidate still has intact references, an independently
    # published but later-than-cutoff candidate cannot hide that prior version.
    write(root,current,{'run_id':'run'})
    future_current='universes/20261013/HK_CONNECT_FULL_MARKET.current.json'
    future_sha=write(root,future_current,{'run_id':'run2'})
    write(root,new+'/publication.json',dict(current_relative=future_current,current_sha256=future_sha,
        available_at='2026-10-13T11:00:00+08:00'))
    prior=membership(cfg,context())
    assert any(f['relative']==old+'/receipt.json' for f in prior['checked_files'])
    later=membership(cfg,context(cutoff='2026-10-13T12:00:00+08:00'))
    assert any(f['relative']==new+'/receipt.json' for f in later['checked_files'])
    # Do not relax SHA for the latest candidate either.
    (root/'universes/20261012/HK_CONNECT_FULL_MARKET.json').write_text('{}')
    with pytest.raises(ValueError,match='OWNER_SHA_MISMATCH'):membership(cfg,context())


def test_semantic_source_owner_refs_change_cache_identity_but_roles_share_base():
    from v4.manager_workbench.engines.announcement import _task
    executor=SimpleNamespace(models={'READER':'gpt-6-luna','REVIEWER':'gpt-6-luna'},reasoning_effort={'READER':'max','REVIEWER':'max'})
    article=dict(article_id='official:1',owner='HKEX_OFFICIAL',symbol='HK.00001',source_sha256='a'*64,
        body_sha256='b'*64,evidence_ids=['official-body-ref'],observed_at='2026-10-12T12:00:00+08:00',available_at='2026-10-12T12:00:00+08:00')
    reader=_task(executor,'READER',article=article,body='source body')
    review=_task(executor,'REVIEWER',article=article,body='source body',reader={'output':{'reason':'saved'},'output_sha256':'c'*64})
    assert reader['input_sha256']==review['input_sha256']
    assert reader['task_id']!=review['task_id']
    changed_output=_task(executor,'REVIEWER',article=article,body='source body',reader={'output':{'reason':'different'},'output_sha256':'d'*64})
    assert review['input_sha256']==changed_output['input_sha256'] and review['task_id']!=changed_output['task_id']
    for changed in [{**article,'owner':'EASTMONEY_MIRROR'},{**article,'evidence_ids':['different-source-ref']}]:
        task=_task(executor,'READER',article=changed,body='source body')
        assert task['input_sha256']!=reader['input_sha256'] and task['task_id']!=reader['task_id']


def test_actual_proxy_quote_whitespace_failure_stays_rejected():
    from v4.manager_workbench.engines.announcement import _validate_reader,READ_PROMPT,REVIEW_PROMPT
    # Mirrors the actual r3 failure shape without exporting real article text.
    body='A proxy form mentions Company 2026 year 10month 12day circular.'
    article={'source_sha256':'a'*64,'body_sha256':'b'*64}
    output=dict(disposition='NOT_SELECTED',selection_basis='NOT_SELECTED',direction='NEUTRAL',
        evidence_sufficiency='VERIFIED_EXISTING_FACTS',reason='Administrative form without operating evidence.',risk_notes=[],
        facts=[],changes=[],impact=[],confirmation_conditions=[],counter_evidence=[dict(claim='Separate circular',
            quote='Company 2026 year 10month12day circular',locator='body')],**article)
    with pytest.raises(ValueError,match='ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE'):_validate_reader(body,article,output)
    output['counter_evidence'][0]['quote']='Company 2026 year 10month 12day circular'
    _validate_reader(body,article,output)
    assert 'CONTINUOUS substring' in READ_PROMPT and 'CONTINUOUS substring' in REVIEW_PROMPT
