"""Frozen repair scope: original authority facts and isolated event transport."""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from domains.runtime_graph_evidence import CurrentEvidenceReader
from infrastructure.runtime_graph import current

CASE = Path('/Users/lexi/Desktop/学习/agents调试/V4_RUNTIME_GRAPH_REPAIR_20261026')
COMPONENTS = Path(__file__).resolve().parents[3]
COLLECTOR = COMPONENTS / 'collector/app/infrastructure/runtime_graph/event_collector.py'
spec = importlib.util.spec_from_file_location('graph_event_collector_scoped', COLLECTOR)
collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)


@pytest.fixture
def cfg(tmp_path):
    return {'schema_version':'v4.runtime_graph_config.v1', '_sha256':'case-config',
            'main':{'app_root':'fixed-case', 'catalog_sha256':'c', 'registry_sha256':'r'},
            'graph_root':str(tmp_path / 'graph'), 'inbox':str(tmp_path / 'inbox'), 'monitor_enabled':False,
            **current.FLAGS}


def event(cfg, key, node='research_panel_daily_a', phase='COMMITTED', date='20261026', owner='MAIN'):
    payload = {'schema_version':'v4.runtime_graph_hint.v1','node_id':node,'owner':owner,
               'business_date':date,'phase':phase,'run_id':key,'observed_at':'2026-10-26T14:00:00+00:00',
               'pid':123,'source_path':'','production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    current.atomic_json(Path(cfg['inbox']) / (key+'.json'), payload)


def reader(cfg, calls, *, statuses=None, during=None):
    descriptors = [{'node_id':'research_panel_daily_a','owner':'a','kind':'MAIN'},
                   {'node_id':'zsxq_pdf','owner':'ZSXQ_PDF','kind':'INDEPENDENT'},
                   {'node_id':'hk_auction_0920','owner':'h','kind':'MAIN'}]
    def get(path):
        calls.append(path)
        if during:
            during()
        ids = path.split('&node_ids=')[1].split(',') if '&node_ids=' in path else [r['node_id'] for r in descriptors]
        return {'schema_version':'v4.runtime_graph_authority.v1', 'business_date':path.split('date=')[1].split('&')[0],
                'authority_identity':cfg['main'],'api_template_catalog_sha256':'different-api-template',
                'descriptors':descriptors,
                'nodes':[{'node_id':nid,'status':(statuses or {}).get(nid,'node_unknown'), **current.FLAGS} for nid in ids], **current.FLAGS}
    return get


def collect(cfg, get, **kwargs):
    return collector.collect_events(cfg,get,quiet_seconds=0,max_wait=0,business_date='20261026',**kwargs)


def test_original_three_trace_facts_and_partial_not_ready():
    config = current.load_config(CASE / 'writer/CANARY_CONFIG.json')
    dto = CurrentEvidenceReader(config).collect('20261026', ['hk_auction_0920','review_core_daily','research_panel_daily_a','fupan_video_check'])
    nodes = {n['node_id']:n for n in dto['nodes']}
    hk = nodes['hk_auction_0920']
    assert hk['execution_phase']=='COMPLETED' and hk['business_status']=='AUCTION_SECOND_FILTER_READY'
    assert hk['row_count']==20 and hk['page_status']=='CANNOT_CONFIRM'
    assert next(e for e in hk['evidence'] if e['kind']=='DISPATCH_RECEIPT')['sha256']=='8bec07f2657326d5d8562692592dc37311cca30802385571446200c8734203d2'
    daily = nodes['review_core_daily']
    assert daily['status']=='BLOCKED' and daily['reason']=='SELECTOR_NOT_READY'
    assert daily['selector_validation']['reason']=='SELECTOR_POINTER_METADATA_MISSING' and daily['asr_execution_count']==0
    a = nodes['research_panel_daily_a']
    assert a['status']=='PARTIAL' and a['coverage']['row_count']==5538 and a['coverage']['target_count']==5808
    assert a['pit_certified'] is False
    assert nodes['fupan_video_check']['business_status']=='ACTION_RAN_WITH_CANNOT_CONFIRM'
    assert nodes['fupan_video_check']['reason']=='CANNOT_CONFIRM'
    historical=nodes['fupan_video_check']['historical_action']
    assert historical['binding_status']=='HISTORICAL_DIAGNOSTIC_NO_RUN_LINK'
    assert 'exact-date current pointer missing' in historical['failure_layer']['cannot_confirm'][0]
    assert nodes['fupan_video_check']['current_upstream']['status']=='BLOCKED'
    assert dto['authority_identity']['catalog_sha256']=='7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef'
    assert dto['api_template_catalog_sha256'] != dto['authority_identity']['catalog_sha256']


@pytest.fixture
def daily(tmp_path):
    root=tmp_path/'receipts'; date=root/'20261026'; date.mkdir(parents=True)
    receipt={'schema_version':'review_core.macos_daily_receipt.v1','trade_date':'20261026',
             'run_id':'run1','attempt_id':'attempt1','origin':'natural_scheduler','finished_at':'2026-10-26T21:05:00+08:00',
             'status':'BLOCKED','reason':'SELECTOR_NOT_READY',**current.FLAGS}
    path=date/'attempt1.json'; current.atomic_json(path,receipt)
    pointer={'schema_version':'review_core.macos_daily_current.v1','trade_date':'20261026',
             **{k:receipt[k] for k in ('run_id','attempt_id','origin','finished_at')},
             'receipt_path':str(path),'receipt_sha256':current.sha(path.read_bytes()),**current.FLAGS}
    current.atomic_json(date/'current.json',pointer)
    return root,pointer,receipt


@pytest.mark.parametrize('mutation',['date','run','sha','safety_missing','safety_true','outside_root','symlink'])
def test_daily_mutations_fail_closed(daily,mutation,tmp_path):
    root,pointer,receipt=daily
    if mutation=='date': pointer['trade_date']='20261025'
    if mutation=='run': pointer['run_id']='other'
    if mutation=='sha': pointer['receipt_sha256']='0'*64
    if mutation=='safety_missing': del pointer['orders_sent']
    if mutation=='safety_true': pointer['orders_sent']=True
    if mutation=='outside_root':
        out=tmp_path/'out.json';current.atomic_json(out,receipt);pointer['receipt_path']=str(out)
    if mutation=='symlink':
        original=root/'20261026/attempt1.json';out=tmp_path/'original.json';original.rename(out);original.symlink_to(out)
    current.atomic_json(root/'20261026/current.json',pointer)
    assert CurrentEvidenceReader({'daily_receipt_root':str(root)})._daily('20261026')['status']=='CANNOT_CONFIRM'


@pytest.mark.parametrize('key',['catalog_sha256','registry_sha256'])
def test_actual_main_binding_drift_rejected_before_reads(key):
    config=current.load_config(CASE/'writer/CANARY_CONFIG.json');config['main'][key]='0'*64
    with pytest.raises(ValueError,match='DRIFT'):
        CurrentEvidenceReader(config).collect('20261026',['hk_auction_0920'])


def test_no_old_windows_nodes_in_current_catalog():
    cfg=current.load_config(CASE/'writer/CANARY_CONFIG.json')
    descriptors=CurrentEvidenceReader(cfg).descriptors()
    assert len([r for r in descriptors if r['kind']=='MAIN'])==24
    assert not any('legacy' in r['node_id'] or 'task_spec:' in r['node_id'] for r in descriptors)


def test_burst_coalesces_and_semantic_fail_acknowledged(cfg):
    event(cfg,'start',phase='EXECUTOR_ENTERED');event(cfg,'terminal')
    calls=[];out=collect(cfg,reader(cfg,calls,statuses={'research_panel_daily_a':'FAILED'}))
    assert len(calls)==1 and out['status']=='COLLECTED'
    assert not list(Path(cfg['inbox']).glob('*.json'))
    snapshot,_=current.read_json(current.state_root(cfg)/'snapshot.json')
    assert next(n for n in snapshot['nodes'] if n['node_id']=='research_panel_daily_a')['status']=='FAILED'
    assert len(list((current.state_root(cfg)/'events').glob('*.json')))==2


def test_pdf_event_does_not_read_a_or_every_api(cfg):
    calls=[];collect(cfg,reader(cfg,calls),initialize=True);calls.clear()
    event(cfg,'pdf','zsxq_pdf',owner='ZSXQ_PDF');collect(cfg,reader(cfg,calls))
    assert len(calls)==1 and calls[0].endswith('&node_ids=zsxq_pdf')


def test_arrival_during_collection_remains_pending(cfg):
    event(cfg,'first')
    calls=[]
    collect(cfg,reader(cfg,calls,during=lambda:event(cfg,'arrived-during')))
    assert [p.name for p in Path(cfg['inbox']).glob('*.json')]==['arrived-during.json']


@pytest.mark.parametrize('phase',['QUEUED','HEARTBEAT','TICK','RETURN','RAISED'])
def test_non_business_hint_rejected_without_collection(cfg,phase):
    calls=[];collect(cfg,reader(cfg,calls),initialize=True);calls.clear()
    event(cfg,'invalid',phase=phase);collect(cfg,reader(cfg,calls))
    assert calls==[] and not list(Path(cfg['inbox']).glob('*.json'))
    assert (current.state_root(cfg)/'rejected/invalid.json').is_file()


def test_read_failure_quarantines_without_hot_loop(cfg):
    event(cfg,'first')
    def failed(_): raise OSError('controlled unreadable')
    assert collect(cfg,failed)['status']=='FAILED'
    assert not list(Path(cfg['inbox']).glob('*.json'))
    assert (current.state_root(cfg)/'failed/first.json').exists()
    monitor,_=current.read_json(current.state_root(cfg)/'monitor.json'); assert monitor['state']=='FAILED'


def test_idle_does_not_refresh_generated_at_and_disabled_is_not_current(cfg):
    calls=[];collect(cfg,reader(cfg,calls),initialize=True)
    raw=(current.state_root(cfg)/'snapshot.json').read_bytes();calls.clear()
    assert collect(cfg,reader(cfg,calls))['status']=='IDLE' and calls==[]
    assert (current.state_root(cfg)/'snapshot.json').read_bytes()==raw
    value=current.read_snapshot(cfg)
    assert value['monitor']['state']=='STOPPED_PENDING_REPAIR' and value['is_current'] is False


def test_registration_failure_and_business_expiry_are_distinct(cfg,monkeypatch):
    calls=[];collect(cfg,reader(cfg,calls),initialize=True)
    p=current.state_root(cfg)/'snapshot.json';snap,_=current.read_json(p)
    observed=datetime.fromisoformat(snap['last_collection_at']);snap['nodes'][0]['valid_until']=(observed+timedelta(seconds=10)).isoformat();current.atomic_json(p,snap)
    cfg['monitor_enabled']=True;monkeypatch.setattr(current,'monitor_registration',lambda:'UNLOADED')
    value=current.read_snapshot(cfg,now=observed+timedelta(seconds=1000))
    assert value['monitor']['state']=='STOPPED_OR_UNCONFIRMED' and value['is_current'] is False
    assert value['nodes'][0]['evidence_freshness']=='EXPIRED' and value['last_collection_at']==snap['last_collection_at']


def test_source_notification_does_not_delay_actual_executor_at_100ms_cutoff(tmp_path):
    main=COMPONENTS/'main/app'
    script='''
import time, threading
from infrastructure.runtime_graph import notifications as n
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from contracts.runtime_tasks import DispatchRequest, DispatchMode
from types import SimpleNamespace
entered=threading.Event()
def slow(_):
    entered.set();time.sleep(.1)
n._persist=slow
registry=object.__new__(FixedExecutorRegistry)
start=time.monotonic();deadline=start+.05
def actual(request):
    assert time.monotonic()<deadline, 'notification crossed cutoff'
    return {'status':'SUCCEEDED'}
registry._hourly_research=actual
request=DispatchRequest('20261026','20261026','20261026','0915',DispatchMode.LIVE)
assert registry(SimpleNamespace(workload_id='hourly_research'),request)['status']=='SUCCEEDED'
assert time.monotonic()-start<.05
assert entered.wait(.5)
print('REAL_EXECUTOR_ENTRY_NOT_BLOCKED_BY_100MS_NOTIFIER')
'''
    env={**os.environ,'V4_RUNTIME_GRAPH_INBOX':str(tmp_path/'inbox'),'PYTHONDONTWRITEBYTECODE':'1'}
    env.pop('PYTHONPATH',None)
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=main,env=env,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
    assert 'REAL_EXECUTOR_ENTRY_NOT_BLOCKED' in result.stdout


def test_api_current_routes_use_bound_reader_and_keep_read_only(cfg,tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.runtime_graph_router import create_runtime_graph_router
    config_path=tmp_path/'config.json';current.atomic_json(config_path,{k:v for k,v in cfg.items() if k!='_sha256'})
    monkeypatch.setenv('V4_RUNTIME_GRAPH_CONFIG',str(config_path))
    monkeypatch.setenv('V35_RUNTIME_GRAPH_DATA_ROOT',cfg['graph_root'])
    monkeypatch.setattr(CurrentEvidenceReader,'collect',lambda self,date,node_ids=None:{'date':date,'ids':node_ids,'status':'node_unknown',**current.FLAGS})
    app=FastAPI();app.include_router(create_runtime_graph_router(tmp_path/'native_business_root'))
    client=TestClient(app)
    result=client.get('/api/v3/runtime-graph/authorities?date=20261026&node_ids=zsxq_pdf')
    assert result.status_code==200 and result.json()['ids']==['zsxq_pdf']
    assert result.headers['cache-control'].startswith('no-store')
    assert client.get('/api/v3/runtime-graph/authorities?date=20261026&node_ids=../bad').status_code==409
    stopped=client.get('/api/v3/runtime-graph/snapshot').json()
    assert stopped['is_current'] is False and stopped['monitor']['state']=='STOPPED_PENDING_REPAIR'
    assert client.post('/api/v3/runtime-graph/repair',json={}).status_code==409


def test_original_historical_running_is_not_current_liveness():
    asof=json.loads((CASE/'writer/HISTORICAL_RUNNING_ASOF.json').read_text())
    assert asof['evidence_kind']=='HISTORICAL_ASOF_OBSERVATION_NOT_CURRENT_RUNNING'
    assert asof['current_process_liveness']=='NOT_ASSERTED'
    assert [r['at'] for r in asof['observations']]==['2026-10-26T21:09:24.789911+08:00','2026-10-26T21:09:54.795248+08:00']
    assert all(r['child_pid']==48921 for r in asof['observations'])
    assert all(any('qfq_06d8818f0ad0cc8075c7' in p for p in r['progress']) for r in asof['observations'])


def test_stage_original_start_is_persisted_and_return_is_not_terminal(tmp_path):
    path=COMPONENTS/'stage/app/stage_center/attempt_evidence.py'
    spec=importlib.util.spec_from_file_location('scoped_stage_attempt',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    calls=[]
    def notified(*args,**kw):
        assert Path(kw['source_path']).is_file()
        calls.append((args,kw))
    mod._graph_notify=notified
    with mod.capture_attempt(tmp_path/'stage',trade_date='20261026',stage_id='STAGE_0925',attempt_number=1,
                             evaluated_at='2026-10-26T09:25:00+08:00',due_status='DUE') as journal:
        journal.finish({'status':'READY'})
    assert len(calls)==1 and calls[0][0][3]=='EXECUTOR_ENTERED'
    assert len(journal.paths)==2 and journal.paths[-1].endswith('_RETURN.json')


def test_daily_terminal_hint_after_both_original_commits(tmp_path):
    daily=COMPONENTS/'daily/app/components/review_daily/20260901T145725Z-review-core-selector-cutoff-v5/app'
    script='''
from review_core import macos_daily as m
from pathlib import Path
from types import SimpleNamespace
import json,sys,hashlib
root=Path(sys.argv[1]); calls=[]
def notified(*args,**kw):
    path=Path(kw['source_path']);p=json.loads((path.parent/'current.json').read_text())
    assert p['receipt_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    calls.append(args)
m._graph_notify=notified
paths=SimpleNamespace(receipt_root=root,data_root=root/'data',selector_path=None,public_source_root=None,tdx_root=None)
r=m._write_result('20261026',paths,{'trade_date':'20261026','status':'BLOCKED','reason':'CANARY'},skip_runtime_contract=True)
assert r['status']=='BLOCKED' and calls[0][3]=='COMMITTED'
print('DAILY_ORIGINAL_IMMUTABLE_AND_POINTER_COMMITTED_BEFORE_HINT')
'''
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'};env.pop('PYTHONPATH',None);env.pop('V4_RUNTIME_GRAPH_INBOX',None)
    result=subprocess.run([sys.executable,'-B','-c',script,str(tmp_path/'receipts')],cwd=daily,env=env,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr


def test_new_source_event_resolves_transport_failure_preserving_old_input(cfg):
    event(cfg,'failed-a')
    collect(cfg,lambda _:(_ for _ in ()).throw(OSError('read failure')))
    event(cfg,'new-source')
    calls=[];collect(cfg,reader(cfg,calls))
    assert not list((current.state_root(cfg)/'failed').glob('*.json'))
    assert (current.state_root(cfg)/'resolved_failures/failed-a.json').is_file()


def test_main_loaded_identity_missing_does_not_relabel_claim_as_executor(monkeypatch):
    from types import SimpleNamespace
    import domains.runtime_graph_evidence as evidence
    config=current.load_config(CASE/'writer/CANARY_CONFIG.json');config['runtime_binding_required']=True
    monkeypatch.setattr(evidence.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'pid = 123\n program = other-release'))
    dto=CurrentEvidenceReader(config).collect('20261026',['hk_auction_0920','review_core_daily'])
    assert dto['runtime_binding']['current_runtime_verified'] is False
    assert next(n for n in dto['nodes'] if n['node_id']=='hk_auction_0920')['status']=='node_unknown'
    assert next(n for n in dto['nodes'] if n['node_id']=='review_core_daily')['status']=='BLOCKED'


def test_notifier_full_or_failed_queue_never_raises(monkeypatch):
    from infrastructure.runtime_graph import notifications
    import queue
    class FullQueue:
        def put_nowait(self,value): raise queue.Full()
    monkeypatch.setenv('V4_RUNTIME_GRAPH_INBOX','/unused/not-written')
    monkeypatch.setattr(notifications,'_pending',FullQueue())
    assert notifications.notify('MAIN','hk_auction_0920','20261026','EXECUTOR_ENTERED') is False


def operator_module():
    spec=importlib.util.spec_from_file_location('scoped_graph_operator',CASE/'writer/operator.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def ready_observation(plan):
    operator=operator_module();config=operator.load(plan['config_path'])
    manifest=operator.load(plan['components']['api']['path'])
    module=next(f for f in manifest['app_files'] if f['path']=='domains/runtime_graph_evidence.py')
    now=datetime.now(timezone.utc)
    return {'api_pid':101,'main_pid':202,'api_plist_sha256':operator.op(plan,'api')['after_sha256'],
            'main_plist_sha256':operator.op(plan,'main')['after_sha256'],
            'api_manifest_sha256':plan['components']['api']['sha256'],'config_sha256':plan['config_sha256'],
            'proof':{'schema_version':'v4.runtime_graph_authority.v1','business_date':now.astimezone().strftime('%Y%m%d'),
                     'observed_at':now.isoformat(),'proof_runtime':{'pid':101,
                        'module_file':str(Path(plan['components']['api']['release_root'])/'app/domains/runtime_graph_evidence.py'),
                        'module_sha256':module['sha256']},'authority_identity':config['main'],
                     'config_sha256':plan['config_sha256'],
                     'runtime_binding':{'pid':202,'status':'VERIFIED','current_runtime_verified':True,
                         'launcher':str(Path(config['main']['app_root'])/'ops/launch_v35_macos_scheduler.sh')},
                     'reader_bindings':{k:config[k] for k in ('graph_root','ledger_root','opening_root','stage_selection_root','stage_receipt_root','daily_receipt_root')},**current.FLAGS}}


@pytest.mark.parametrize('mutation',['expired','missing_pid','pid_drift','plist_drift','manifest_drift','config_drift','module_path','module_sha','main_not_loaded','roots'])
def test_activation_gate_rejects_before_first_service_action(mutation,tmp_path,monkeypatch):
    operator=operator_module();plan=operator.load(CASE/'delivery/DEPLOYMENT_PLAN.json');observed=ready_observation(plan)
    graph=operator.op(plan,'collector');graph['plist']=str(tmp_path/'graph.plist');Path(graph['plist']).write_bytes(b'fixture');graph['after_sha256']=operator.sha(b'fixture')
    if mutation=='expired':observed['proof']['observed_at']=(datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat()
    if mutation=='missing_pid':del observed['proof']['proof_runtime']['pid']
    if mutation=='pid_drift':observed['api_pid']=999
    if mutation=='plist_drift':observed['api_plist_sha256']='x'
    if mutation=='manifest_drift':observed['api_manifest_sha256']='x'
    if mutation=='config_drift':observed['proof']['config_sha256']='x'
    if mutation=='module_path':observed['proof']['proof_runtime']['module_file']='/wrong/module.py'
    if mutation=='module_sha':observed['proof']['proof_runtime']['module_sha256']='x'
    if mutation=='main_not_loaded':observed['proof']['runtime_binding']['current_runtime_verified']=False
    if mutation=='roots':observed['proof']['reader_bindings']['graph_root']='/wrong/root'
    actions=[];monkeypatch.setattr(operator,'verify_release',lambda *a:None)
    with pytest.raises((ValueError,KeyError)):
        operator.activate_graph(plan,observe=lambda _:observed,command=lambda cmd:actions.append(cmd),state=lambda _:None)
    assert actions==[]


def test_graph_activation_retains_whole_gate_context_and_checks_twice(tmp_path,monkeypatch):
    from types import SimpleNamespace
    operator=operator_module();plan=operator.load(CASE/'delivery/DEPLOYMENT_PLAN.json');observed=ready_observation(plan)
    graph=operator.op(plan,'collector');graph['plist']=str(tmp_path/'graph.plist');Path(graph['plist']).write_bytes(b'fixture');graph['after_sha256']=operator.sha(b'fixture')
    actions=[];observations=[];monkeypatch.setattr(operator,'verify_release',lambda *a:None)
    def observe(full):
        assert operator.op(full,'api') and operator.op(full,'main')
        observations.append(True);return observed
    def command(args):actions.append(args);return SimpleNamespace(returncode=0)
    result=operator.activate_graph(plan,observe=observe,command=command,state=lambda _:None)
    assert result['status']=='GRAPH_BOOTSTRAPPED_PENDING_ACTUAL_READBACK'
    assert len(observations)==2 and [a[0] for a in actions]==['enable','bootstrap']
    assert all('runtime-graph' in str(a) or a[0]=='bootstrap' for a in actions)


def test_cas_install_backup_and_rollback_require_unloaded_label(tmp_path,monkeypatch):
    import plistlib
    operator=operator_module();p=tmp_path/'test.plist';raw=plistlib.dumps({'Label':'fixture','ProgramArguments':['/old/app/entry.py'],'EnvironmentVariables':{'UNCHANGED':'value'}});p.write_bytes(raw)
    row={'label':'fixture','plist':str(p),'before_sha256':operator.sha(raw),'replace_prefix':'/old/app','new_prefix':'/new/app','env_set':{'V4_RUNTIME_GRAPH_INBOX':'/new/inbox'},'set':{},'remove':[]}
    new=plistlib.loads(raw);new['ProgramArguments']=['/new/app/entry.py'];new['EnvironmentVariables'].update(row['env_set']);row['after_sha256']=operator.sha(plistlib.dumps(new,fmt=plistlib.FMT_XML,sort_keys=True))
    monkeypatch.setattr(operator,'label_state',lambda _:123)
    with pytest.raises(ValueError,match='WITHOUT_KILL'):operator.install_plist(row)
    assert p.read_bytes()==raw
    monkeypatch.setattr(operator,'label_state',lambda _:None)
    assert operator.install_plist(row)=='INSTALLED_UNLOADED'
    assert plistlib.loads(p.read_bytes())['EnvironmentVariables']['UNCHANGED']=='value'
    assert operator.install_plist(row)=='ALREADY_APPLIED'
    assert operator.install_plist(row,rollback=True)=='ROLLED_BACK' and p.read_bytes()==raw


def test_future_nodes_are_not_false_missing_receipts(tmp_path):
    config=current.load_config(CASE/'writer/CANARY_CONFIG.json');future=(datetime.now(timezone.utc)+timedelta(days=2)).strftime('%Y%m%d')
    config['ledger_root']=str(tmp_path/'ledger');config['daily_receipt_root']=str(tmp_path/'daily')
    rows=CurrentEvidenceReader(config).collect(future,['hk_auction_0920','review_core_daily','stage:STAGE_0925'])['nodes']
    assert all(n['status']=='PENDING_NOT_DUE' for n in rows)


@pytest.fixture
def entry_case(tmp_path):
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.runtime_graph.notifications import process_identity
    root=tmp_path/'ledger';ledger=ExecutionLedger(root)
    catalog=load_workload_catalog(COMPONENTS/'main/app/contracts/runtime_workloads.json')
    workload=next(w for w in catalog.workloads if w.workload_id=='hourly_research')
    request=DispatchRequest('20261026','20261026','20261026','1400',DispatchMode.LIVE)
    claim=ledger.try_claim_dispatch(request);ledger.try_claim_workload(request,workload,run_id=claim.run_id)
    module=COMPONENTS/'main/app/infrastructure/scheduling/executor_registry.py'
    config={'main':{'app_root':str(COMPONENTS/'main/app'),'registry_sha256':current.sha(module.read_bytes())},
            'inbox':str(tmp_path/'transport/inbox'),'ledger_root':str(root)}
    birth=process_identity(os.getpid());assert birth
    entry={'schema_version':'v4.runtime_execution_entry.v1','phase':'EXECUTOR_ENTERED','owner':'MAIN',
           'owner_id':workload.owner_id,'node_id':workload.workload_id,'business_date':'20261026','slot':'1400',
           'run_id':claim.run_id,'attempt':1,'pid':os.getpid(),'parent_pid':os.getppid(),
           'caller_file':str(module),'caller_function':'__call__','caller_sha256':current.sha(module.read_bytes()),
           'source_path':str(root/ledger.receipt_relative(request,run_id=claim.run_id)),
           'observed_at':datetime.now(timezone.utc).isoformat(),**birth,**current.FLAGS}
    path=Path(config['inbox']).parent/'entry_observations/20261026/MAIN/hourly_research/entry.json'
    current.atomic_json(path,entry)
    node={'node_id':workload.workload_id,'status':'PARTIAL','business_status':'PARTIAL','pit_certified':False,
          'execution_phase':'COMPLETED','evidence':[]}
    return config,ledger,workload,request,entry,path,node


def verify_entry(case):
    config,ledger,workload,request,entry,path,node=case
    CurrentEvidenceReader(config)._execution_entry(node,workload,'20261026',ledger,
        ledger.list_receipts('20261026',mode='LIVE'),{'current_runtime_verified':True,'pid':os.getppid()})
    return node


def test_durable_real_entry_claim_pid_source_proof_keeps_business_partial(entry_case):
    node=verify_entry(entry_case)
    assert node['execution_phase']=='RUNNING_VERIFIED_OBSERVATION',node.get('execution_observation')
    assert node['execution_observation']['claim_as_start'] is False
    assert node['business_status']=='PARTIAL' and node['pit_certified'] is False
    assert len(node['execution_observation']['evidence'])==3


@pytest.mark.parametrize('mutation',['wrong_date','wrong_run','wrong_owner','wrong_sha','wrong_attempt','wrong_birth','dead_pid','wrong_claim','wrong_terminal_path','terminal_present'])
def test_entry_mutations_cannot_confer_running(entry_case,mutation,monkeypatch):
    import domains.runtime_graph_evidence as evidence
    config,ledger,workload,request,entry,path,node=entry_case
    if mutation=='wrong_date':entry['business_date']='20261025'
    if mutation=='wrong_run':entry['run_id']='other'
    if mutation=='wrong_owner':entry['owner_id']='other'
    if mutation=='wrong_sha':entry['caller_sha256']='0'*64
    if mutation=='wrong_attempt':entry['attempt']=99
    if mutation=='wrong_birth':entry['process_start_token']='other incarnation'
    if mutation=='dead_pid':monkeypatch.setattr(evidence,'process_identity',lambda _:None)
    if mutation=='wrong_terminal_path':entry['source_path']='/outside/receipt.json'
    if mutation=='wrong_claim':
        cp=Path(ledger.root)/'workloads/live/20261026/1400/hourly_research.workload-claim.json';c=json.loads(cp.read_text());c['pid']=999999;cp.write_text(json.dumps(c))
    if mutation=='terminal_present':Path(entry['source_path']).parent.mkdir(parents=True,exist_ok=True);Path(entry['source_path']).write_text('{}')
    current.atomic_json(path,entry)
    node=verify_entry(entry_case)
    assert node['execution_phase']!='RUNNING_VERIFIED_OBSERVATION'
    assert node['business_status']=='PARTIAL' and node['pit_certified'] is False


def test_hint_and_claim_without_durable_entry_never_confer_running(entry_case):
    config,ledger,workload,request,entry,path,node=entry_case
    path.unlink();current.atomic_json(Path(config['inbox'])/'hint.json',{'phase':'EXECUTOR_ENTERED','pid':os.getpid(),'run_id':entry['run_id']})
    assert verify_entry(entry_case)['execution_phase']!='RUNNING_VERIFIED_OBSERVATION'


def test_cached_running_expires_on_pid_identity_without_fake_collection(entry_case,tmp_path,monkeypatch):
    from infrastructure.runtime_graph import notifications
    config,ledger,workload,request,entry,path,node=entry_case
    node=verify_entry(entry_case)
    config.update(graph_root=str(tmp_path/'graph'),_sha256='fixture',monitor_enabled=False)
    now=datetime.now(timezone.utc).isoformat()
    current.atomic_json(current.state_root(config)/'snapshot.json',{'schema_version':current.SCHEMA,
        'config_sha256':'fixture','business_date':'20261026','last_collection_at':now,'nodes':[node],**current.FLAGS})
    monkeypatch.setattr(notifications,'process_identity',lambda _:None)
    result=current.read_snapshot(config)
    assert result['nodes'][0]['execution_phase']=='NOT_RUNNING_PID_IDENTITY_UNCONFIRMED'
    assert result['last_collection_at']==now


def test_actual_dispatcher_context_before_receipt_definition_is_safe(tmp_path):
    main=COMPONENTS/'main/app'
    script='''
from dataclasses import replace
from pathlib import Path
import sys
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.runtime_graph.notifications import _context
catalog=load_workload_catalog();w=next(w for w in catalog.workloads if w.workload_id=='hourly_research')
catalog=replace(catalog,workloads=(w,))
calls=[]
def executor(w,r,d):
    ctx=_context.get()
    assert ctx['owner_id']==w.owner_id and ctx['slot']=='1400' and ctx['attempt']==1 and ctx['run_id']
    assert ctx['source_path'].endswith('/'+ctx['run_id']+'.dispatch-receipt.json')
    calls.append(w.workload_id);return {'status':'SUCCEEDED'}
r=dispatch_due(DispatchRequest('20261026','20261026','20261026','1400',DispatchMode.LIVE),catalog,executor,ledger=ExecutionLedger(Path(sys.argv[1])))
assert calls==['hourly_research'] and r.status=='SUCCEEDED',r
print('ACTUAL_DISPATCHER_CONTEXT_AND_COMMIT_CANARY_NO_SDK')
'''
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'};env.pop('PYTHONPATH',None);env.pop('V4_RUNTIME_GRAPH_INBOX',None)
    result=subprocess.run([sys.executable,'-B','-c',script,str(tmp_path/'ledger')],cwd=main,env=env,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr


def test_entry_observation_commits_before_wake_hint(tmp_path,monkeypatch):
    monkeypatch.setenv('V4_RUNTIME_GRAPH_INBOX',str(tmp_path/'transport/inbox'))
    source=COMPONENTS/'main/app/infrastructure/runtime_graph/notifications.py'
    spec=importlib.util.spec_from_file_location('entry_publisher_isolated',source)
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    publisher.set_context(run_id='case-run',slot='1400',owner_id='case-owner',attempt=1)
    assert publisher.notify('MAIN','hourly_research','20261026','EXECUTOR_ENTERED')
    assert publisher.flush(1)
    hint_path=next((tmp_path/'transport/inbox').glob('*.json'));hint=json.loads(hint_path.read_text())
    path=Path(hint['entry_observation_path']);entry=json.loads(path.read_text())
    assert current.sha(path.read_bytes())==hint['entry_observation_sha256']
    assert entry['schema_version']=='v4.runtime_execution_entry.v1' and entry['pid']==os.getpid()
    assert entry['caller_file']==str(Path(__file__).resolve())
    assert entry['caller_sha256']==current.sha(Path(__file__).read_bytes())
    assert entry['process_start_token'] and entry['attempt']==1
