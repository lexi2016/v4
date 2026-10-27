from __future__ import annotations
import gc,hashlib,importlib.util,json,os,plistlib,subprocess,sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
import prepare as prep
import controller as ctl


def hashed(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):return {'path':str(path),'sha256':hashed(path)}
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path


def test_missing_handoff_blocks_before_candidate_or_any_live_action(tmp_path,monkeypatch):
    path=write(tmp_path/'handoff.json',{'schema_version':'v4.ui_pdf_publication_handoff.v1','status':'IN_PROGRESS'})
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('prepare invoked subprocess'))
    with pytest.raises(RuntimeError,match='PENDING_EXPLICIT'):
        prep.prepare(tmp_path/'never',handoff_path=path,handoff_sha=hashed(path))
    assert not (tmp_path/'never').exists()


def test_main_launcher_is_rewritten_not_only_env_and_workingdirectory():
    old=Path('/fixture/releases/old/app');new=Path('/fixture/releases/new/app')
    before={'Label':prep.LABELS['main'],'WorkingDirectory':str(old),'EnvironmentVariables':{'V35_APP_ROOT':str(old),'V35_RELEASE_ID':'old','PYTHONPATH':str(old)+':/independent/dependency'},
            'ProgramArguments':['/usr/bin/env','V35_APP_ROOT='+str(old),'/bin/bash',str(old/'ops/launch_v35_macos_scheduler.sh')]}
    result=prep.rewrite_owner(before,old,new,'a'*64,main=True)
    assert result['ProgramArguments'][-1]==str(new/'ops/launch_v35_macos_scheduler.sh')
    assert result['WorkingDirectory']==str(new)
    assert prep.environment(result)['PYTHONPATH']==str(new)+':/independent/dependency'
    assert before['ProgramArguments'][-1]==str(old/'ops/launch_v35_macos_scheduler.sh')
    wrong={**result,'ProgramArguments':before['ProgramArguments']}
    with pytest.raises(ValueError,match='LAUNCHER'):prep.require_main_launcher(wrong,new)


def test_us_ledger_env_is_equal_in_both_forms_and_main_ledger_preserved():
    before={'ProgramArguments':['/usr/bin/env','V4_TASK_STATUS_LEDGER_ROOT=MAIN','V4_TASK_STATUS_US_LEDGER_ROOT=OLD','/python'],
            'EnvironmentVariables':{'V4_TASK_STATUS_LEDGER_ROOT':'MAIN','V4_TASK_STATUS_US_LEDGER_ROOT':'OLD'}}
    result=prep.env_both(before,{'V4_TASK_STATUS_US_LEDGER_ROOT':'US'})
    assert result['EnvironmentVariables']['V4_TASK_STATUS_US_LEDGER_ROOT']=='US'
    assert result['ProgramArguments'].count('V4_TASK_STATUS_US_LEDGER_ROOT=US')==1
    assert prep.environment(result)['V4_TASK_STATUS_LEDGER_ROOT']=='MAIN'
    conflict={**result,'EnvironmentVariables':{**result['EnvironmentVariables'],'V4_TASK_STATUS_US_LEDGER_ROOT':'OTHER'}}
    with pytest.raises(ValueError,match='DISAGREE'):prep.environment(conflict)


@pytest.mark.parametrize('value,ready',[
    ('2026-10-27T12:54:59+08:00',True),('2026-10-27T12:55:00+08:00',False),
    ('2026-10-27T13:00:00+08:00',False),('2026-10-27T13:01:00+08:00',True),
    ('2026-10-27T13:09:00+08:00',False),('2026-10-27T13:16:59+08:00',False),
    ('2026-10-27T13:17:00+08:00',True),('2026-10-27T05:14:00+00:00',False)])
def test_control_windows_shanghai_and_utc(value,ready):
    assert ctl.boundary(datetime.fromisoformat(value),[['1300','1300'],['1314','1316']])['ready'] is ready


def test_existing_child_blocks_but_post_admission_lock_unadmitted_tick_does_not():
    rows={1:{'ppid':0,'command':'main'},2:{'ppid':1,'command':'python -m ops.run_zsxq_hourly_delta --pdf-queue-tick'}}
    assert not ctl.idle_facts(rows,1,{1,2},True,[])['ready']
    assert ctl.idle_facts(rows,1,{1},True,[])['unadmitted_post_lock_pdf_children']==[2]
    rows[2]['command']='python -m another_business'
    assert not ctl.idle_facts(rows,1,{1},True,[])['ready']
    assert not ctl.idle_facts({1:rows[1]},1,{1},True,[{'unfinished':True}])['ready']


def test_original_flock_inode_busy_and_fd_cleanup(tmp_path):
    import fcntl
    path=tmp_path/'original.lock';path.write_text('keep');st=path.stat();row={'path':str(path),'device':st.st_dev,'inode':st.st_ino}
    with ctl.same_inode_guard(row):
        with pytest.raises(RuntimeError,match='BUSY'):
            with ctl.same_inode_guard(row):pass
    assert path.stat().st_ino==st.st_ino and path.read_text()=='keep'
    with pytest.raises(RuntimeError,match='INODE_DRIFT'):
        with ctl.same_inode_guard({**row,'inode':st.st_ino+1}):pass


def test_journal_closes_on_success_and_failure_without_resource_warning(tmp_path):
    instance=object.__new__(ctl.Controller)
    for failure in (False,True):
        path=tmp_path/('journal'+str(failure));instance.journal=None
        def work(*args):
            instance.journal=path.open('x');instance.journal.write('persisted')
            if failure:raise RuntimeError('fixture failure')
        instance._execute=work
        if failure:
            with pytest.raises(RuntimeError):instance.execute(None,None)
        else:instance.execute(None,None)
        assert instance.journal.closed
    gc.collect()


def test_unknown_service_result_is_not_blindly_retried_and_pipes_are_closed():
    instance=object.__new__(ctl.Controller);instance.p={'operations':[{'plist':str(Path.home()/'Library/LaunchAgents'/(label+'.plist'))} for label in prep.LABELS.values()]}
    instance.phase='FORWARD';instance.attempted=set();instance.uncertain=False;instance.record=lambda *a,**k:None
    calls=[]
    def unknown(args):calls.append(args);raise subprocess.TimeoutExpired(args,15)
    instance.read_command=unknown
    args=['bootout',f'gui/{os.getuid()}/'+prep.LABELS['main']]
    with pytest.raises(subprocess.TimeoutExpired):instance.command(args)
    assert instance.uncertain
    with pytest.raises(RuntimeError,match='UNKNOWN_PRIOR'):instance.command(args)
    assert len(calls)==1
    with pytest.raises(RuntimeError,match='OUTSIDE_FIXED'):instance.command(['debug','arbitrary'])


def test_cas_refuses_drift_before_any_service_call(tmp_path):
    path=tmp_path/'plist';path.write_text('base');marker=write(tmp_path/'marker',{'phase':'DONE'})
    instance=object.__new__(ctl.Controller);instance.p={'operations':[{'plist':str(path),'before_sha256':hashed(path),'after_sha256':'new'}],
        'locks':{'owner':{'marker':str(marker),'marker_sha256':hashed(marker)}},'frozen_inputs':{},'prior_plan':str(marker),'prior_plan_sha256':hashed(marker),'config_path':str(marker),'config_sha256':hashed(marker)}
    instance.p['frozen_inputs']={'api_overlay':ref(write(tmp_path/'api',{'entries':[]})),'main_overlay':ref(write(tmp_path/'main',{'entries':[]}))}
    instance.cas();path.write_text('changed')
    with pytest.raises(ValueError,match='PIN_DRIFT'):instance.cas()


def test_reverse_cas_skips_unchanged_old_services_and_reuses_original_installer():
    instance=object.__new__(ctl.Controller);instance.p={'operations':[]};instance.phase='FORWARD'
    old={'original':'old'};states={'main':{'loaded':True,'version':'OLD','disk':'OLD'},'api':{'loaded':False,'disk':'NEW'},'collector':{'loaded':False,'disk':'NEW'}}
    events=[];loaded={prep.LABELS['main']:10,prep.LABELS['api']:None,prep.LABELS['collector']:None}
    instance.binding=lambda key,old:states[key];instance.unload=lambda key:events.append(('unload',key))
    instance.row=lambda key:{'component':key,'label':prep.LABELS[key]};instance.record=lambda *a,**k:None
    def install(row,rollback=False):assert rollback;events.append(('reverse_cas',row['component']))
    instance.op=SimpleNamespace(install_plist=install,label_state=lambda label:loaded[label],activate_graph=lambda *a,**k:events.append(('graph','old')))
    instance.op.observe_api=lambda p:None
    instance.bootstrap=lambda key:events.append(('bootstrap',key));instance.wait_verify=lambda p:None;instance.cas=lambda **k:None;instance.verify=lambda p:{'old':True};instance.verify_graph=lambda p:None
    instance.command=lambda args:None
    assert instance.rollback(old)=={'old':True}
    assert not any(event[1]=='main' for event in events)
    assert ('reverse_cas','api') in events and ('reverse_cas','collector') in events


def fixture_case(tmp_path,monkeypatch):
    actual=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-api-r2/app')
    helper=prep.module('fixture_real_integration',actual/'ops/api_release_integration.py')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('prepare invoked live subprocess'))
    home=tmp_path/'home';monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    case=tmp_path/'case';out=case/'controller/publication_control_r2';out.mkdir(parents=True)
    monkeypatch.setattr(prep,'OUTPUT_ROOT',out)
    releases=tmp_path/'releases';components={};values={}
    def old_manifest(root,key):
        items=helper.inventory_tree(root/'app');return {'schema_version':'v4.release_candidate.v1',
            'candidate':{'root':str(root),'app_root':str(root/'app'),'release_id':root.name,'module_role':'gateway'},
            'application_inventory':{'entries':items,'aggregate_sha256':helper.inventory_digest(items)},
            'app_files':[{'path':r['path'],'bytes':r['size'],'sha256':r['sha256']} for r in items if r['kind']=='file'],'symlinks':[]}
    for key,label in prep.LABELS.items():
        root=releases/('old-'+key);app=root/'app';app.mkdir(parents=True)
        for rel in ('ops/launch_v35_macos_scheduler.sh','ops/collect_runtime_graph.py','infrastructure/scheduling/executor_registry.py','v4/manager_workbench/jobs.py'):
            p=app/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('keep Root21 and Root76 '+rel)
        values[key]={'Label':label,'WorkingDirectory':str(app),'EnvironmentVariables':{},'ProgramArguments':['/usr/bin/env','/python']}
        components[key]={'app_root':str(app),'manifest':str(root/'release-manifest.json'),'pid':100}
    source=case/'source';source.mkdir();overlays={}
    for key,count in [('main',2),('api',14)]:
        rows=[];app=Path(components[key]['app_root'])
        for index in range(count):
            rel=f'deltas/{key}_{index}.txt';base=app/rel;base.parent.mkdir(exist_ok=True);base.write_text('original')
            after=source/(key+str(index));after.write_text('reviewed delta')
            rows.append({'path':rel,'source_path':str(after),'before_sha256':hashed(base),'after_sha256':hashed(after),'kind':'built_frontend' if key=='api' and index>=12 else 'business_source'})
        overlays[key]=write(case/(key+'_overlay.json'),{'entries':rows})
    for key,row in components.items():
        root=Path(row['app_root']).parent;m=write(Path(row['manifest']),old_manifest(root,key));row['manifest_sha256']=hashed(m);row['application_inventory_sha256']=helper.inventory_digest(helper.inventory_tree(root/'app'))
        env={'PRODUCTION_ALLOWED':'false','BUY_GATE_UPDATED':'false','ORDERS_SENT':'false','V35_APP_ROOT':row['app_root'],'V35_RELEASE_ID':root.name,'V35_RELEASE_MANIFEST_PATH':str(m),'V35_RELEASE_MANIFEST_SHA256':hashed(m),'PYTHONPATH':row['app_root']}
        values[key]['EnvironmentVariables']=env
        if key=='main':values[key]['ProgramArguments']=['/bin/bash',str(root/'app/ops/launch_v35_macos_scheduler.sh')]
        elif key=='api':values[key]['ProgramArguments']=['/usr/bin/env',*[k+'='+v for k,v in env.items()],'/python','-m','apps.api.v35_api.run']
        else:values[key]['ProgramArguments']=['/python','-B',str(root/'app/ops/collect_runtime_graph.py'),'--config',str(root/'runtime-graph-config.json')]
        plist=home/'Library/LaunchAgents'/(prep.LABELS[key]+'.plist');plist.parent.mkdir(parents=True,exist_ok=True);plist.write_bytes(plistlib.dumps(values[key]));row.update(plist=str(plist),plist_sha256=hashed(plist))
    config=write(Path(components['collector']['app_root']).parent/'runtime-graph-config.json',{
        'main':{'app_root':components['main']['app_root'],'registry_sha256':'preserved'},'graph_root':'unchanged-state',
        'entry_sources':{'MAIN':{'module_file':components['main']['app_root']+'/infrastructure/scheduling/executor_registry.py','module_sha256':'old'},
                         'API':{'module_file':components['api']['app_root']+'/v4/manager_workbench/jobs.py','module_sha256':'old'}}})
    fake_guard=tmp_path/'guard.py';fake_guard.write_text('# no execution')
    catalog=write(tmp_path/'catalog',{'workloads':[{'slots':['1300','1700']}]});freeze=write(tmp_path/'freeze',{'api_overlay_sha256':hashed(overlays['api']),'pdf_main_overlay_sha256':hashed(overlays['main']),'business_files':prep.load(overlays['main'])['entries']+prep.load(overlays['api'])['entries'][:12]})
    business=write(tmp_path/'business',{'review_receipt':{'verdict':'REVIEWED/PASS','combined_source_freeze_sha256':hashed(freeze),'api_overlay_sha256':hashed(overlays['api']),'pdf_main_overlay_sha256':hashed(overlays['main'])}})
    contract=write(tmp_path/'module-contract.json',{'schema_version':'v4.api_module_contracts.v1','roles':{'gateway':{'plist_name':prep.LABELS['api']+'.plist','label':prep.LABELS['api'],'port':8873},'stage':{},'manager':{}}})
    h={'schema_version':'v4.ui_pdf_publication_handoff.v1','status':'HANDED_OFF','guards_released':True,'owner_active':False,'receiver_scope':prep.SCOPE,
       'helpers':{'integration':ref(actual/'ops/api_release_integration.py'),'rewrite':ref(actual/'ops/prepare_api_only_cutover.py'),
                  'operator':ref(Path('/Users/lexi/Desktop/学习/agents调试/V4_RUNTIME_GRAPH_REPAIR_20261026/OPERATOR_STAGE_CACHE_R1/operator.py')),'main_guard':ref(fake_guard)},
       'api_module_contract':ref(contract),'components':components,'api_overlay':ref(overlays['api']),'main_overlay':ref(overlays['main']),
       'source_freeze':ref(freeze),'business_review':ref(business),'graph_config':ref(config),'schedule_catalog':ref(catalog),
       'locks':{},'main_guard_parameters':{'service':'gui/501/com.lexi.v35.scheduler','domain':'gui/501','guard_program':'/bin/sleep','guard_seconds':604800,
           'ledger_root':str(tmp_path/'ledger'),'log_path':str(tmp_path/'main.log'),'expected_python':'/python','expected_python_resolved':'/python','expected_python_binary_sha256':'fixture'},
       'workbench_root':str(tmp_path/'workbench'),'us_ledger_root':prep.EXPECTED_US_LEDGER_ROOT}
    for key in ('owner','lane_A_LONG','lane_DEFAULT','pdf_ingestion','collector'):
        lock=tmp_path/(key+'.lock');lock.write_bytes(b'');info=lock.stat()
        h['locks'][key]={'path':str(lock),'device':info.st_dev,'inode':info.st_ino}
    marker=write(tmp_path/'owner.json',{'active':False,'phase':'DONE'})
    h['locks']['owner'].update(marker=str(marker),marker_sha256=hashed(marker))
    path=write(case/'HANDOFF.json',h);return path,out/'candidate',components


def test_prepare_builds_fresh_only_local_candidates_preserving_all_non_delta_bytes(tmp_path,monkeypatch):
    handoff,out,before=fixture_case(tmp_path,monkeypatch)
    p=prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    assert p['scope']==prep.SCOPE and len(p['operations'])==3
    for key,row in p['components'].items():
        assert not Path(row['release_root']).exists()  # no formal materialization or launchctl
        copied=Path(row['candidate_app'])
        assert (copied/'v4/manager_workbench/jobs.py').read_bytes()==(Path(before[key]['app_root'])/'v4/manager_workbench/jobs.py').read_bytes()
    assert p['proofs']['main']['non_delta_count']>=4 and p['proofs']['api']['non_delta_count']>=4
    main=next(r for r in p['operations'] if r['component']=='main');staged=plistlib.loads(Path(main['template_path']).read_bytes())
    prep.require_main_launcher(staged,str(Path(p['components']['main']['release_root'])/'app'))
    api=next(r for r in p['operations'] if r['component']=='api');staged=plistlib.loads(Path(api['template_path']).read_bytes())
    assert prep.environment(staged)['V4_TASK_STATUS_US_LEDGER_ROOT']==prep.EXPECTED_US_LEDGER_ROOT
    assert '1314' in str(p['protected_windows'])
    config=prep.load(p['config_path']);assert config['graph_root']=='unchanged-state'
    assert config['main']['registry_sha256']=='preserved'
    assert config['main']['app_root']==str(Path(p['components']['main']['release_root'])/'app')


def test_prepare_refuses_overlap_before_any_formal_or_active_changes(tmp_path,monkeypatch):
    handoff,out,before=fixture_case(tmp_path,monkeypatch)
    target=Path(before['main']['app_root'])/'deltas/main_0.txt';target.write_text('Root new overlapping change')
    # Standard base inventory itself now rejects drift, before an overlay can mask it.
    with pytest.raises(ValueError):prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    assert target.read_text()=='Root new overlapping change'


@pytest.mark.parametrize('defect',['inode','active','readback'])
def test_prepare_rejects_incomplete_or_changed_handoff_before_candidate(tmp_path,monkeypatch,defect):
    handoff,out,_=fixture_case(tmp_path,monkeypatch);value=prep.load(handoff)
    if defect=='inode':value['locks']['owner']['inode']+=1
    elif defect=='active':
        marker=Path(value['locks']['owner']['marker']);write(marker,{'active':True,'phase':'DRAINING'})
        value['locks']['owner']['marker_sha256']=hashed(marker)
    else:value['main_guard_parameters'].pop('expected_python_binary_sha256')
    write(handoff,value)
    with pytest.raises((ValueError,RuntimeError)):prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    assert not out.exists()


def test_r5_wrong_loaded_launcher_is_rejected_even_with_correct_cwd(tmp_path):
    instance=object.__new__(ctl.Controller);root=tmp_path/'new/app'
    plan={'components':{'main':{'release_root':str(root.parent)}},'operations':[{'component':'main','plist':'unused'}]}
    instance.op=SimpleNamespace(op=lambda p,k:p['operations'][0])
    instance.g=SimpleNamespace(service=lambda:{'pid':11,'text':'/old/app/ops/launch_v35_macos_scheduler.sh'},
        identity=lambda pid:{'pid':pid,'command':'python -m ops.run_v35_macos_scheduler_daemon'},cwd=lambda pid:str(root))
    with pytest.raises(RuntimeError,match='LOADED_LAUNCHER'):instance.verify_main(plan)


def test_old_unused_controller_plan_never_runs_under_r2():
    with pytest.raises(ValueError,match='OLD_DRAFT_NOT_EXECUTABLE'):
        ctl.require_scope({'scope':'API_AND_GRAPH_ONLY_MAIN_VALIDATION_ONLY'})


def test_bounded_original_subprocess_result_is_normalized_without_leaking_handles():
    instance=object.__new__(ctl.Controller);calls=[]
    def original(args,**kwargs):
        calls.append((args,kwargs));return subprocess.CompletedProcess(args,0,'text','')
    instance.g=SimpleNamespace(command=original)
    result=instance.read_command(['print','fixed-service'])
    assert result.stdout==b'text' and calls[0][1]['timeout']==15 and calls[0][1]['allow_missing'] is True


def test_guard_contexts_survive_unknown_outcome_and_close_after_explicit_recovery(tmp_path,monkeypatch):
    from contextlib import contextmanager
    import io
    instance=object.__new__(ctl.Controller);instance.journal=None
    held=[]
    @contextmanager
    def guard(row,**kwargs):
        if row['name']=='pdf_ingestion':assert kwargs['wait_seconds']==180 and callable(kwargs['check_window'])
        else:assert not kwargs
        held.append(row['name'])
        try:yield object()
        finally:held.remove(row['name'])
    @contextmanager
    def api_guard(*a,**k):
        held.append('api_guard')
        try:yield object()
        finally:held.remove('api_guard')
    monkeypatch.setattr(ctl,'same_inode_guard',guard)
    marker=write(tmp_path/'marker',{'active':False,'phase':'DONE'})
    owner={'name':'owner','marker':str(marker),'marker_sha256':hashed(marker)}
    prior=write(tmp_path/'prior',{})
    target=tmp_path/'api-target';target.mkdir();source=tmp_path/'candidate/delta';source.parent.mkdir();source.write_text('{}')
    # The same bytes are already privately staged in this isolated fixture.
    (target/'delta').write_text('{}')
    instance.p={'handoff':{'path':'handoff','sha256':'h'},'prepare_sha256':'prepare',
        'locks':{'owner':owner,**{key:{'name':key} for key in ('lane_A_LONG','lane_DEFAULT','pdf_ingestion','collector')}},
        'workbench_root':str(tmp_path),'prior_plan':str(prior),'components':{'api':{'path':str(source),'release_root':str(target),'sha256':'manifest'}},
        'base':{'main':{'pid':10}},'operations':[{'component':'api','plist':'fixed-api'}]}
    instance.path=write(tmp_path/'PLAN.json',instance.p)
    review=write(tmp_path/'review',{'verdict':'PASS','deployment_plan_sha256':hashed(instance.path),'controller_sha256':hashed(ctl.__file__),'prepare_sha256':'prepare'})
    monkeypatch.setattr(prep,'handoff_ready',lambda *a:{})
    instance.window=lambda:None;instance.cas=lambda **k:None;instance.verify=lambda p:{};instance.verify_graph=lambda p:None;instance.verify_inventory=lambda *a,**k:None
    instance.g=SimpleNamespace(processes=lambda:{10:{}},initial_old=lambda pid:{'pid':pid})
    instance.integration=SimpleNamespace(announcement_flash_cutover_guard=api_guard,shared_api_release_lock=api_guard,
        DELTA_RECEIPT_NAME='delta',verify_api_release_candidate=lambda **k:None)
    instance.op=SimpleNamespace(stage=lambda p:None,op=lambda p,key:{'plist':'fixed-api'},label_state=lambda label:0)
    instance.idle=lambda old:{'ready':True};events=[]
    def record(event,**fields):
        events.append(event)
        if event in {'FAILURE_GUARDS_RETAINED','READONLY_RECONCILIATION','OLD_BINDINGS_VERIFIED'}:assert len(held)==7
    instance.record=record
    def failed(key):raise RuntimeError('uncertain service result')
    instance.unload=failed;instance.rollback=lambda p:{'restored':True};instance.binding=lambda k,p:{'known':True};instance.verify_api_candidate=lambda **k:None
    monkeypatch.setattr(ctl.sys,'stdin',io.StringIO('RECONCILE\nROLLBACK\n'))
    instance.execute(review,hashed(review))
    assert instance.journal.closed and not held
    assert events.index('FAILURE_GUARDS_RETAINED')<events.index('READONLY_RECONCILIATION')<events.index('OLD_BINDINGS_VERIFIED')<events.index('GUARDS_RELEASED')


@pytest.mark.parametrize('flag',['PRODUCTION_ALLOWED','BUY_GATE_UPDATED','ORDERS_SENT'])
def test_service_safety_flags_cannot_be_missing_or_true(flag):
    env={'PRODUCTION_ALLOWED':'false','BUY_GATE_UPDATED':'false','ORDERS_SENT':'false'}
    prep.assert_safety({'EnvironmentVariables':env,'ProgramArguments':['/program']})
    with pytest.raises(ValueError,match='UNSAFE'):
        prep.assert_safety({'EnvironmentVariables':{**env,flag:'true'},'ProgramArguments':['/program']})
    env.pop(flag)
    with pytest.raises(ValueError,match='MISSING'):
        prep.assert_safety({'EnvironmentVariables':env,'ProgramArguments':['/program']})


def test_old_pid_exit_is_observed_without_repeating_service_command(monkeypatch):
    instance=object.__new__(ctl.Controller);old={'pid':12,'start':'same','command':'old'};states=[old,old,None]
    instance.g=SimpleNamespace(identity=lambda pid:states.pop(0))
    monkeypatch.setattr(ctl.time,'sleep',lambda value:None)
    instance.wait_exit(old)
    assert not states


def test_reused_pid_never_becomes_an_exit_or_signal_target():
    instance=object.__new__(ctl.Controller);old={'pid':12,'start':'old','command':'old'}
    instance.g=SimpleNamespace(identity=lambda pid:{'pid':12,'start':'different','command':'new'})
    with pytest.raises(RuntimeError,match='PID_REUSED'):instance.wait_exit(old)


@pytest.mark.parametrize('component',['main','api','collector'])
@pytest.mark.parametrize('where',['candidate','staged'])
def test_complete_inventory_rejects_extra_file_before_service_actions(tmp_path,monkeypatch,component,where):
    handoff,out,_=fixture_case(tmp_path,monkeypatch)
    p=prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    instance=object.__new__(ctl.Controller);instance.p=p
    instance.integration=prep.module('inventory_original',p['helpers']['integration']['path'])
    operator=prep.module('inventory_operator',p['helpers']['operator']['path']);calls=[]
    def stage(plan):
        calls.append('stage');operator.stage(plan)
        if where=='staged':(Path(p['components'][component]['release_root'])/'app/unmanifested_module.py').write_text('unreviewed')
    instance.op=SimpleNamespace(stage=stage)
    instance.command=lambda *a:pytest.fail('integrity failure reached service action')
    if where=='candidate':(Path(p['components'][component]['candidate_app'])/'unmanifested_module.py').write_text('unreviewed')
    with pytest.raises(RuntimeError,match='COMPLETE_INVENTORY_DRIFT:'+component):instance.stage_verified()
    assert calls==([] if where=='candidate' else ['stage'])


def real_business_handoff():
    case=Path('/Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027')
    return {key:ref(case/relative) for key,relative in [('business_review','review/SOL_REVIEW_R2.json'),('source_freeze','COMBINED_SOURCE_FREEZE.json'),('api_overlay','deployment/OVERLAY.json'),('main_overlay','pdf_night/OVERLAY.json')]}


@pytest.mark.parametrize('component',['main','collector'])
def test_final_readback_rechecks_complete_staged_inventory(tmp_path,monkeypatch,component):
    handoff,out,_=fixture_case(tmp_path,monkeypatch);p=prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    instance=object.__new__(ctl.Controller);instance.p=p
    instance.integration=prep.module('final_inventory_original',p['helpers']['integration']['path'])
    instance.op=prep.module('final_inventory_operator',p['helpers']['operator']['path'])
    instance.stage_verified()
    (Path(p['components'][component]['release_root'])/'app/late_unmanifested.py').write_text('late drift')
    instance.verify_main=lambda *a:pytest.fail('readback continued after complete inventory drift')
    with pytest.raises(RuntimeError,match='COMPLETE_INVENTORY_DRIFT:'+component):instance.verify(p)


def test_actual_retained_business_receipt_shape_and_hash_bindings():
    prep.verify_business_review(real_business_handoff())


@pytest.mark.parametrize('defect',['FAIL','top_level_only','combined_source_freeze_sha256','api_overlay_sha256','pdf_main_overlay_sha256'])
def test_business_receipt_fail_or_wrong_binding_is_rejected(tmp_path,defect):
    h=real_business_handoff();value=prep.load(h['business_review']['path'])
    if defect=='top_level_only':value={'verdict':'PASS'}
    elif defect=='FAIL':value['review_receipt']['verdict']='REVIEWED/FAIL'
    else:value['review_receipt'][defect]='0'*64
    h['business_review']=ref(write(tmp_path/'receipt.json',value))
    with pytest.raises(ValueError):prep.verify_business_review(h)


@pytest.mark.parametrize('domain',[None,'gui/999'])
def test_missing_or_inconsistent_main_domain_rejected_before_prepare(tmp_path,monkeypatch,domain):
    handoff,out,_=fixture_case(tmp_path,monkeypatch);value=prep.load(handoff)
    if domain is None:value['main_guard_parameters'].pop('domain')
    else:value['main_guard_parameters']['domain']=domain
    write(handoff,value)
    with pytest.raises(ValueError,match='MAIN_READBACK_DOMAIN'):prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    assert not out.exists()


def test_actual_main_helper_domain_interface_without_live_commands(tmp_path,monkeypatch):
    handoff,_,_=fixture_case(tmp_path,monkeypatch);value=prep.load(handoff)
    prep.validate_handoff_descriptors(value)
    path=Path('/Users/lexi/Desktop/学习/agents调试/V4_SCHEDULE_REMEDIATION_IMPLEMENT_20261026/case/control_writer/main_guard_r5/guard_recipe.py')
    module=prep.module('actual_guard_domain_fixture',path);params=value['main_guard_parameters']
    root=tmp_path/'main';source=root/'ops/run_v35_macos_scheduler_daemon.py';source.parent.mkdir(parents=True);source.write_text('frozen')
    params.update(old_root=str(root),old_daemon_sha256=hashed(source));ops=module.LiveOps(params);calls=[]
    def command(args,**kwargs):
        calls.append(args);assert args==['/bin/launchctl','print-disabled','gui/501']
        return subprocess.CompletedProcess(args,0,'"com.lexi.v35.scheduler" => false','')
    ops.command=command
    ops.service=lambda:{'pid':42,'text':'properties = keepalive\n'+str(root/'ops/launch_v35_macos_scheduler.sh')}
    ops.processes=lambda:{42:{'pid':42,'ppid':1,'pgid':42,'start':'fixture','command':'python -m ops.run_v35_macos_scheduler_daemon'}}
    ops.cwd=lambda pid:str(root)
    assert ops.initial_old(42)['pid']==42 and calls


def test_actual_main_legacy_manifest_projects_only_two_frozen_pdf_deltas(tmp_path,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('legacy projection invoked live subprocess'))
    base=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-main-r2')
    assert hashed(base/'release-manifest.json')=='2ed2da9abc77280da40f0f6f2cf9f0401759d517b7272b30c6ea3f5053cef031'
    actual=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-api-r2/app')
    helper=prep.module('main_legacy_original_helper',actual/'ops/api_release_integration.py')
    rows=prep.load(prep.CASE/'pdf_night/OVERLAY.json')['entries'];candidate=tmp_path/'candidate/app'
    entries,proof=prep.apply_overlay(helper,base/'app',candidate,rows)
    before=prep.load(base/'release-manifest.json');after=prep.manifest(helper,candidate,tmp_path/'future',before,component='main')
    changed={key for key in before['files'] if before['files'][key]!=after['files'][key]}
    assert changed=={'app/'+row['path'] for row in rows} and len(changed)==2
    assert set(after['files'])==set(before['files']) and len(after['files'])==881
    assert after['files']=={'app/'+row['path']:row['sha256'] for row in after['app_files']}
    for key,digest in after['files'].items():assert hashed(candidate/key[4:])==digest
    for key in ('external_a_clean_binding_files','external_a_clean_component_sources','a_source_review_pass','c_r2_independent_review'):
        assert after[key]==before[key]
    assert proof['non_delta_count']==len(helper.inventory_tree(base/'app'))-2


@pytest.mark.parametrize('defect',['escape','absolute','outside_app','bad_sha','inconsistent_sha','api','collector'])
def test_main_legacy_manifest_unknown_contract_and_other_components_rejected(tmp_path,defect):
    actual=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-api-r2/app')
    helper=prep.module('legacy_rejection_original',actual/'ops/api_release_integration.py')
    app=tmp_path/'app';app.mkdir();file=app/'known.py';file.write_text('known')
    digest=hashed(file);base={'app_files':[{'path':'known.py','sha256':digest}],'files':{'app/known.py':digest}}
    component='main'
    if defect in ('api','collector'):component=defect
    elif defect=='inconsistent_sha':base['files']['app/known.py']='0'*64
    elif defect=='bad_sha':base['files']['app/known.py']='not_sha'
    else:
        path={'escape':'app/../known.py','absolute':'/app/known.py','outside_app':'external/known.py'}[defect]
        base['files']={path:digest}
    with pytest.raises(ValueError):prep.manifest(helper,app,tmp_path/'future',base,component=component)


def test_actual_legacy_api_shape_full_prepare_candidate_and_reverse_identity(tmp_path,monkeypatch):
    import copy,shutil
    fixture_handoff,out,_=fixture_case(tmp_path,monkeypatch);fixture=prep.load(fixture_handoff)
    actual_handoff=prep.CASE/'controller/publication_control_r2/FRESH_HANDOFF_R1.json'
    assert hashed(actual_handoff)=='e8b94bdfc72247a18f5788f49f666742b7aaa7967ff82eaad8a2b0f8b3ae29a2'
    h=prep.load(actual_handoff);h['locks']=fixture['locks']
    helper=prep.module('real_legacy_fixture_integration',h['helpers']['integration']['path']);helper.MODULE_CONTRACT_PATH=Path(h['api_module_contract']['path'])
    replacements={row['app_root']:str(tmp_path/'actual-shape-releases'/Path(row['app_root']).parent.name/'app') for row in h['components'].values()}
    def rebind(value):
        if isinstance(value,str):
            for old,new in replacements.items():value=value.replace(str(Path(old).parent),str(Path(new).parent))
            return value
        if isinstance(value,list):return [rebind(v) for v in value]
        if isinstance(value,dict):return {k:rebind(v) for k,v in value.items()}
        return value
    for key,row in h['components'].items():
        old=Path(row['app_root']);app=Path(replacements[str(old)]);app.parent.mkdir(parents=True)
        shutil.copytree(old,app,symlinks=True)
        manifest=prep.load(row['manifest']);manifest['app_root']=str(app)
        manifest_path=write(app.parent/'release-manifest.json',manifest)
        value=rebind(plistlib.loads(Path(row['plist']).read_bytes()))
        value=prep.env_both(value,{'V35_RELEASE_MANIFEST_SHA256':hashed(manifest_path)})
        plist=Path(fixture['components'][key]['plist']);plist.write_bytes(plistlib.dumps(value))
        row.update(app_root=str(app),manifest=str(manifest_path),manifest_sha256=hashed(manifest_path),
                   plist=str(plist),plist_sha256=hashed(plist),application_inventory_sha256=helper.inventory_digest(helper.inventory_tree(app)))
    config=write(tmp_path/'actual-graph-config.json',rebind(prep.load(h['graph_config']['path'])))
    h['graph_config']=ref(config);h['schedule_catalog']=ref(Path(h['components']['main']['app_root'])/'contracts/runtime_workloads.json')
    handoff=write(tmp_path/'actual-shape-handoff.json',h)
    p=prep.prepare(out,handoff_path=handoff,handoff_sha=hashed(handoff))
    assert p['api_baseline']['release_manifest_sha256']==h['components']['api']['manifest_sha256']
    assert prep.load(h['components']['api']['manifest'])['schema_version']=='v4.runtime_graph_repair_release.v1'
    api_manifest=prep.load(p['components']['api']['path'])
    assert api_manifest['schema_version']=='v4.release_candidate.v1'
    assert api_manifest['application_inventory']['entry_count']==1320
    assert api_manifest['external_module_contract']==h['api_module_contract']
    assert p['proofs']['api']['non_delta_count']==1306
    assert p['proofs']['main']['non_delta_count']==879
    original=helper._release_identity
    with pytest.raises(ValueError,match='SCHEMA_UNSUPPORTED'):helper.read_active_release(Path(h['components']['api']['plist']))
    with prep.api_identity_scope(helper,h['components']['api'],h['api_module_contract']):
        actual=helper.read_active_release(Path(h['components']['api']['plist']))
        assert actual['manifest']['schema_version']=='v4.runtime_graph_repair_release.v1'
        assert actual['release_manifest_sha256']==p['api_baseline']['release_manifest_sha256']
    assert helper._release_identity is original
    operator=prep.module('actual_legacy_stage_operator',p['helpers']['operator']['path']);operator.stage(p)
    api=p['components']['api'];shutil.copy2(Path(api['path']).parent/helper.DELTA_RECEIPT_NAME,Path(api['release_root'])/helper.DELTA_RECEIPT_NAME)
    instance=object.__new__(ctl.Controller);instance.p=p;instance.integration=helper;instance.op=operator
    assert instance.verify_api_candidate(active_pointer='base')['status']=='PASS'
    plist=Path(h['components']['api']['plist']);old=plist.read_bytes()
    proposal=next(r for r in p['operations'] if r['component']=='api')
    plist.write_bytes(Path(proposal['template_path']).read_bytes())
    assert instance.verify_api_candidate(active_pointer='candidate')['status']=='PASS'
    plist.write_bytes(old)
    prior=prep.load(p['prior_plan']);assert instance.verify_api_binding(prior)['release_manifest_sha256']==p['api_baseline']['release_manifest_sha256']
    bad=copy.deepcopy(h['components']['api']);bad['application_inventory_sha256']='0'*64
    with prep.api_identity_scope(helper,bad,h['api_module_contract']):
        with pytest.raises(ValueError,match='INVENTORY_BINDING'):helper.read_active_release(plist)
    extra=Path(h['components']['api']['app_root'])/'unmanifested.py';extra.write_text('unreviewed')
    with prep.api_identity_scope(helper,h['components']['api'],h['api_module_contract']):
        with pytest.raises(ValueError,match='COMPLETE_INVENTORY_DRIFT'):helper.read_active_release(plist)
    assert helper._release_identity is original


@pytest.mark.parametrize('defect',['schema','identity','module_contract','manifest_sha'])
def test_actual_legacy_api_shape_invalid_bindings_rejected(tmp_path,monkeypatch,defect):
    import copy
    h=prep.load(prep.CASE/'controller/publication_control_r2/FRESH_HANDOFF_R1.json');base=copy.deepcopy(h['components']['api'])
    helper=prep.module('invalid_legacy_original',h['helpers']['integration']['path']);helper.MODULE_CONTRACT_PATH=Path(h['api_module_contract']['path'])
    original=helper._release_identity
    m=prep.load(base['manifest'])
    if defect=='schema':m['schema_version']='unrecognized'
    if defect=='identity':m['app_root']='/wrong/app'
    if defect in ('schema','identity'):
        p=write(tmp_path/'release-manifest.json',m);base.update(manifest=str(p),manifest_sha256=hashed(p))
    if defect=='manifest_sha':base['manifest_sha256']='0'*64
    contract=copy.deepcopy(h['api_module_contract'])
    if defect=='module_contract':contract['sha256']='0'*64
    kwargs={'release_root':Path(base['app_root']).parent,'app_root':Path(base['app_root']),'release_id':Path(base['app_root']).parent.name,
            'manifest_path':Path(base['manifest']),'manifest_sha256':base['manifest_sha256']}
    with pytest.raises(ValueError):
        with prep.api_identity_scope(helper,base,contract):helper._release_identity(**kwargs)
    assert helper._release_identity is original


def temporary_pdf_lock(tmp_path):
    path=tmp_path/'original-pdf.lock';path.write_text('preserve');info=path.stat()
    return {'path':str(path),'device':info.st_dev,'inode':info.st_ino}


def test_pdf_lock_wait_obtains_same_inode_after_natural_release(tmp_path,monkeypatch):
    row=temporary_pdf_lock(tmp_path);held=os.open(row['path'],os.O_RDWR);ctl.fcntl.flock(held,ctl.fcntl.LOCK_EX)
    sleeps=[];checks=[]
    def natural_finish(delay):sleeps.append(delay);os.close(held)
    monkeypatch.setattr(ctl.time,'sleep',natural_finish)
    with ctl.same_inode_guard(row,wait_seconds=180,check_window=lambda:checks.append('window')) as fd:
        assert os.fstat(fd).st_ino==row['inode'] and sleeps==[0.25] and len(checks)==3
    assert Path(row['path']).read_text()=='preserve'
    with ctl.same_inode_guard(row):pass


def test_pdf_lock_wait_budget_releases_own_fd_and_keeps_holder(tmp_path,monkeypatch):
    row=temporary_pdf_lock(tmp_path);held=os.open(row['path'],os.O_RDWR);ctl.fcntl.flock(held,ctl.fcntl.LOCK_EX)
    clock=[0.0];sleeps=[]
    monkeypatch.setattr(ctl.time,'monotonic',lambda:clock[0])
    def wait(delay):sleeps.append(delay);clock[0]+=delay
    monkeypatch.setattr(ctl.time,'sleep',wait)
    try:
        with pytest.raises(RuntimeError,match='PENDING_ORIGINAL_LOCK_BUSY'):
            with ctl.same_inode_guard(row,wait_seconds=0.5,check_window=lambda:None):pytest.fail('budget admitted busy lock')
        assert sum(sleeps)==0.5
        with pytest.raises(RuntimeError,match='BUSY'):
            with ctl.same_inode_guard(row):pass
    finally:os.close(held)
    with ctl.same_inode_guard(row):pass


def test_pdf_lock_wait_stops_at_protected_window_without_touching_holder(tmp_path,monkeypatch):
    row=temporary_pdf_lock(tmp_path);held=os.open(row['path'],os.O_RDWR);ctl.fcntl.flock(held,ctl.fcntl.LOCK_EX)
    checks=[]
    def window():
        checks.append('check')
        if len(checks)==2:raise RuntimeError('PENDING_PROTECTED_BUSINESS_WINDOW')
    monkeypatch.setattr(ctl.time,'sleep',lambda delay:None)
    try:
        with pytest.raises(RuntimeError,match='PROTECTED_BUSINESS_WINDOW'):
            with ctl.same_inode_guard(row,wait_seconds=180,check_window=window):pytest.fail('window admitted lock')
        assert len(checks)==2
        with pytest.raises(RuntimeError,match='BUSY'):
            with ctl.same_inode_guard(row):pass
    finally:os.close(held)
    with ctl.same_inode_guard(row):pass


def test_pdf_lock_yield_exception_never_retries_acquisition(tmp_path,monkeypatch):
    row=temporary_pdf_lock(tmp_path);flock=ctl.fcntl.flock;calls=[]
    def observed(*args):calls.append(args);return flock(*args)
    monkeypatch.setattr(ctl.fcntl,'flock',observed)
    monkeypatch.setattr(ctl.time,'sleep',lambda delay:pytest.fail('yield error retried lock'))
    with pytest.raises(RuntimeError,match='EXECUTION_FAIL'):
        with ctl.same_inode_guard(row,wait_seconds=180,check_window=lambda:None):raise RuntimeError('EXECUTION_FAIL')
    assert len(calls)==1
    with ctl.same_inode_guard(row):pass


def test_pdf_lock_wait_does_not_retry_other_fcntl_errors(tmp_path,monkeypatch):
    row=temporary_pdf_lock(tmp_path);calls=[]
    def denied(*args):calls.append(args);raise PermissionError('fixture denied')
    monkeypatch.setattr(ctl.fcntl,'flock',denied)
    monkeypatch.setattr(ctl.time,'sleep',lambda delay:pytest.fail('nonblocking error masked'))
    with pytest.raises(PermissionError):
        with ctl.same_inode_guard(row,wait_seconds=180,check_window=lambda:None):pass
    assert len(calls)==1
