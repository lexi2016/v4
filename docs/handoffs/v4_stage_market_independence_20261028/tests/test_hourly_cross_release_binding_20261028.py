"""Two actual isolated releases; no attestation, archive or projection stubs.

The controller prepares isolated Main/Stage baseline copies and overlays only
this task's candidate files. Set V4_HOURLY_CROSS_RELEASE_TEST_ROOT to that root.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

import pytest

DAY = '20261028'
ROOT_VALUE = os.environ.get('V4_HOURLY_CROSS_RELEASE_TEST_ROOT')
pytestmark = pytest.mark.skipif(not ROOT_VALUE, reason='requires two frozen isolated release copies')


class LauncherEnv(dict):
    def __repr__(self):
        return '<launcher environment>'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def seal(app, release_id):
    entries = []
    for path in sorted(app.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            raw = path.read_bytes()
            entries.append({'path': path.relative_to(app).as_posix(), 'kind': 'file',
                            'mode': '0644', 'size': len(raw), 'sha256': sha(raw)})
    manifest = {'schema_version': 'v4.runtime_graph_repair_release.v1',
                'app_root': str(app), 'release_id': release_id,
                'RESEARCH_ONLY': True, 'production_allowed': False,
                'buy_gate_updated': False, 'orders_sent': False,
                'application_inventory': {'entries': entries, 'entry_count': len(entries),
                    'aggregate_sha256': sha(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())},
                'app_files': [{'path': item['path'], 'bytes': item['size'], 'sha256': item['sha256']} for item in entries]}
    path = app.parent / 'release-manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return sha(path.read_bytes())


MAIN_RUN = r'''
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json,sys
from ops import run_zsxq_hourly_delta as producer
from ops import collect_hourly_research_input as collector
from ops import run_hourly_research as runner
from infrastructure import research_source_evidence as evidence
from infrastructure import manager_input_attestation as attest
class Clock(datetime):
    current = datetime.fromisoformat('2026-10-28T09:00:00+08:00')
    @classmethod
    def now(cls,tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
for module in (producer,collector,runner,evidence,attest):module.datetime=Clock
root=Path(sys.argv[1])
topic={'topic_id':'12345678901234567','group_id':'g','create_time':'2026-10-28T08:59:00+08:00',
       'title':'平安银行研报','content_head':'平安银行业绩增长，只读研究资料。'*30,
       'companies':[{'code':'000001','name':'平安银行'}],'themes':[{'theme':'银行'}]}
producer.collect_paginated_topics=lambda **kw: {'topics':[topic],'bounded_has_more':True,'page_count':1,
    'group_results':[{'group_id':'g','source_has_more':True,'reached_since':False}]}
def analyzer(*args):
    Clock.current=datetime.fromisoformat('2026-10-28T09:01:00+08:00')
    return {'raw_topic_count':1,'effective_topic_count':1,'effective_topics':[topic]}
status=producer.materialize_zsxq_hourly_delta(data_root=root,trade_date='20261028',slot='0900',
    groups=[('g','fixture')],analyzer=analyzer,now=Clock.current)
source={}
Clock.current=datetime.fromisoformat('2026-10-28T09:01:30+08:00')
import io,contextlib,subprocess,os
from dataclasses import replace
from contracts.runtime_tasks import DispatchRequest,DispatchMode
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from infrastructure.scheduling import dispatcher,execution_ledger
from infrastructure.scheduling.execution_ledger import ExecutionLedger
# Original dispatcher/ledger implementations sample completion and persist the
# actual returned materializer record; only clocks and child transport are injected.
dispatcher.datetime=Clock;execution_ledger.datetime=Clock
ledger_root=Path(sys.argv[2]);ledger_root.mkdir(parents=True,exist_ok=True)
os.environ['V4_RUNTIME_GRAPH_INBOX']=str(ledger_root/'graph-inbox')
os.environ['V35_RELEASE_ID']='isolated-main'
def transport(command,**kwargs):
    module=command[2];args=command[3:]
    if module=='ops.materialize_research_peripherals':
        # Unrelated source transport boundary; it does not certify this work's inputs.
        return subprocess.CompletedProcess(command,0,stdout='{"status":"READY"}',stderr='')
    output=io.StringIO();old_argv=sys.argv
    sys.argv=[module,*args]
    try:
        with contextlib.redirect_stdout(output):
            if module=='ops.run_zsxq_hourly_delta':code=producer.main(args)
            elif module=='ops.collect_hourly_research_input':
                Clock.current=datetime.fromisoformat('2026-10-28T09:02:00+08:00')
                code=collector.main()
                source.update(json.loads(output.getvalue().strip().splitlines()[-1]))
                Clock.current=datetime.fromisoformat('2026-10-28T09:03:00+08:00')
                if os.environ.get('V4_TEST_REMOVE_INPUT_ATTESTATION')=='1':
                    (root/'research/incoming/20261028/0900.json.publication.json').unlink()
            elif module=='ops.refresh_research_preselection':
                from ops.refresh_research_preselection import main as refresh_main
                code=refresh_main(args)
            elif module=='ops.run_hourly_research':
                Clock.current=datetime.fromisoformat('2026-10-28T09:05:00+08:00')
                code=runner.main()
                Clock.current=datetime.fromisoformat('2026-10-28T09:05:30+08:00')
            else:raise AssertionError(module)
    finally:sys.argv=old_argv
    text=output.getvalue()
    if module=='ops.run_hourly_research' and os.environ.get('V4_TEST_SPOOF_PARTIAL_RESULT')=='1':
        corrupt=json.loads(text);corrupt['source_status']='READY';corrupt['hourly_artifact_status']='READY_WITH_RESEARCH_POOL';text=json.dumps(corrupt)
    return subprocess.CompletedProcess(command,code,stdout=text,stderr='')
catalog=load_workload_catalog();catalog=replace(catalog,workloads=tuple(w for w in catalog.workloads if w.workload_id=='hourly_research'))
ledger=ExecutionLedger(ledger_root)
request=DispatchRequest('20261028','20261028','20261028','0900',DispatchMode.LIVE)
receipt=dispatcher.dispatch_due(request,catalog,FixedExecutorRegistry(root,repo_root=Path.cwd(),runner=transport),ledger=ledger)
assert ledger.verify_receipt_chain('20261028',mode='LIVE')[0]
results=receipt.to_dict()['workload_results']
run=next((item.get('_authoritative_payload') for item in results if item.get('workload_id')=='hourly_research'),None)
print(json.dumps({'producer':status['status'],'source':source,'dispatch_status':receipt.status,
                  'dispatch_receipt_path':receipt.receipt_path,'materializer':run},ensure_ascii=False))

'''

STAGE_RUN = r'''
from pathlib import Path
import json,sys
from stage_center.research_context import load_research_context
try:
    value=load_research_context(Path(sys.argv[1]),trade_date='20261028',stage_cutoff=sys.argv[2])
    print(json.dumps({'ok':True,'slot':value.selected_slot,'codes':list(value.by_code),
                     'gaps':list(value.cannot_confirm),'evidence':list(value.source_evidence)}))
except Exception as error:
    print(json.dumps({'ok':False,'error':str(error),'type':type(error).__name__}))
'''


def run_code(app, script, args, env):
    result = subprocess.run([sys.executable, '-B', '-c', script, *map(str, args)],
        cwd=app, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def case(tmp_path,request):
    root = Path(ROOT_VALUE)
    main = root / 'main/app'
    stage = root / 'stage/app'
    env = LauncherEnv(os.environ)
    for key in ('PYTHONPATH', 'PYTHONPYCACHEPREFIX', 'V35_APP_ROOT', 'V35_RELEASE_ID',
                'V35_RELEASE_MANIFEST_PATH', 'V35_RELEASE_MANIFEST_SHA256', 'STAGE_CENTER_CONFIG'):
        env.pop(key, None)
    data = tmp_path / 'data';data.mkdir()
    ledger = tmp_path / 'dispatcher';ledger.mkdir()
    if getattr(request,'param',None)=='remove_input_attestation':env['V4_TEST_REMOVE_INPUT_ATTESTATION']='1'
    if getattr(request,'param',None)=='spoof_partial_result':env['V4_TEST_SPOOF_PARTIAL_RESULT']='1'
    protected = [main/'domains/research_hourly.py', main/'ops/collect_hourly_research_input.py',
                 main/'infrastructure/manager_input_attestation.py', main/'ops/run_zsxq_hourly_delta.py', stage/'stage_center/research_context.py']
    originals = {path:path.read_bytes() for path in protected}
    main_pin = seal(main, 'isolated-main')
    config = {'schema_version':'stage_center.tick_config.v1','v4_research_data_root':str(data),
              'research_scheduler_ledger_root':str(ledger),'research_owner_binding':{'app_root':str(main),'release_id':'isolated-main','manifest_sha256':main_pin}}
    config_path = stage/'stage_center_tick_config.json'
    config_path.write_text(json.dumps(config))
    stage_pin = seal(stage, 'isolated-stage')
    env.update(V35_APP_ROOT=str(stage), V35_RELEASE_ID='isolated-stage',
        V35_RELEASE_MANIFEST_PATH=str(stage.parent/'release-manifest.json'),
        V35_RELEASE_MANIFEST_SHA256=stage_pin, STAGE_CENTER_CONFIG=str(config_path))
    result = run_code(main, MAIN_RUN, [data,ledger], env)
    assert result['producer']=='PARTIAL'
    assert result['source']['status']=='PARTIAL_WITH_ROWS'
    if getattr(request,'param',None) not in {'remove_input_attestation','spoof_partial_result'}:
        assert result['dispatch_status']=='SUCCEEDED',result
        assert result['materializer']['hourly_artifact_status']=='PARTIAL_WITH_ROWS',result
    yield {'main':main,'stage':stage,'data':data,'env':env,'config':config,'main_result':result,'ledger':ledger}
    for path,raw in originals.items():path.write_bytes(raw)
    manifest=main.parent/'release-manifest.json'
    if manifest.is_symlink():manifest.unlink()


def stage_result(case, cutoff='09:06:00'):
    return run_code(case['stage'], STAGE_RUN, [case['data'],cutoff], case['env'])


def reseal_config(case):
    (case['stage']/'stage_center_tick_config.json').write_text(json.dumps(case['config']))
    case['env']['V35_RELEASE_MANIFEST_SHA256']=seal(case['stage'],'isolated-stage')


def test_true_main_to_stage_partial_projection(case):
    assert sha((case['main']/'domains/research_hourly.py').read_bytes()) != sha((case['stage']/'domains/research_hourly.py').read_bytes())
    result = stage_result(case)
    assert result['ok'], result
    assert result['slot']=='0900' and result['codes']==['A.000001']
    assert 'ZSXQ_SOURCE_PARTIAL_INCOMPLETE' in result['gaps']
    assert any(value.startswith('v4_research_owner_manifest_sha256=') for value in result['evidence'])


@pytest.mark.parametrize('fault', ['missing_launch_pin','wrong_launch_root','config_drift','config_path_escape',
    'missing_owner','wrong_owner_root','forged_owner_manifest','main_manifest_drift',
    'main_collector_drift','main_producer_drift','main_domain_drift','main_attestation_drift','stage_reader_drift',
    'main_root_symlink','main_manifest_symlink','owner_data_root_mismatch',
    'missing_input_publication','missing_archive_publication','source_tamper'])
def test_binding_and_publication_fail_closed(case, fault):
    env=case['env'];main=case['main'];stage=case['stage'];data=case['data']
    if fault=='missing_launch_pin':env.pop('V35_RELEASE_MANIFEST_SHA256')
    elif fault=='wrong_launch_root':env['V35_APP_ROOT']=str(main)
    elif fault=='config_drift':(stage/'stage_center_tick_config.json').write_text('{}')
    elif fault=='config_path_escape':env['STAGE_CENTER_CONFIG']=str(stage/'../app/stage_center_tick_config.json')
    elif fault=='missing_owner':case['config'].pop('research_owner_binding');reseal_config(case)
    elif fault=='wrong_owner_root':case['config']['research_owner_binding']['app_root']=str(stage);reseal_config(case)
    elif fault=='forged_owner_manifest':
        forged=data.parent/'forged/app';forged.mkdir(parents=True)
        (forged.parent/'release-manifest.json').write_text('{}')
        case['config']['research_owner_binding']['app_root']=str(forged);reseal_config(case)
    elif fault=='main_manifest_drift':(main.parent/'release-manifest.json').write_text('{}')
    elif fault in {'main_collector_drift','main_producer_drift','main_domain_drift','main_attestation_drift','stage_reader_drift'}:
        path={'main_producer_drift':main/'ops/run_zsxq_hourly_delta.py','main_collector_drift':main/'ops/collect_hourly_research_input.py',
              'main_domain_drift':main/'domains/research_hourly.py',
              'main_attestation_drift':main/'infrastructure/manager_input_attestation.py',
              'stage_reader_drift':stage/'stage_center/research_context.py'}[fault]
        path.write_bytes(path.read_bytes()+b'\n# injected drift\n')
    elif fault=='main_root_symlink':
        link=data.parent/'linked/app';link.parent.mkdir();link.symlink_to(main,target_is_directory=True)
        manifest=json.loads((main.parent/'release-manifest.json').read_bytes())
        manifest['app_root']=str(link)
        alias_manifest=link.parent/'release-manifest.json';alias_manifest.write_text(json.dumps(manifest))
        case['config']['research_owner_binding']['app_root']=str(link)
        case['config']['research_owner_binding']['manifest_sha256']=sha(alias_manifest.read_bytes())
        reseal_config(case)
    elif fault=='main_manifest_symlink':
        manifest=main.parent/'release-manifest.json';raw=manifest.read_bytes()
        target=main.parent/'other-manifest.json';target.write_bytes(raw);manifest.unlink();manifest.symlink_to(target)
    elif fault=='owner_data_root_mismatch':case['config']['v4_research_data_root']=str(data.parent);reseal_config(case)
    elif fault=='missing_input_publication':(data/'research/incoming/20261028/0900.json.publication.json').unlink()
    elif fault=='missing_archive_publication':(data/'research/hourly/publication/live/20261028/0900.json').unlink()
    else:(data/'research/incoming/20261028/0900.json').write_text('{}')
    result=stage_result(case)
    assert result['ok'] is False, (fault,result)


@pytest.mark.parametrize('cutoff',['09:01:59','09:02:30','09:05:15'])
def test_later_materialization_cannot_serve_prior_cutoff(case, cutoff):
    result=stage_result(case,cutoff)
    assert result['ok'] is False and 'PIT' in result['error'],result


def test_source_json_cannot_choose_an_unverified_producer(case):
    # A forged legacy-shaped source can be materialized by the legacy runner
    # path, but it cannot opt out of Stage's configured Main ownership gate.
    fake_data=case['data'].parent/'forged-data';fake_data.mkdir()
    original=case['data']/'research/incoming/20261028/0900.json'
    value=json.loads(original.read_bytes())
    value['source_manifest']['producer']='forged.external'
    value['source_manifest']['generated_at']='2026-10-28T09:00:00+08:00'
    value['source_manifest']['published_at']='2026-10-28T09:00:00+08:00'
    for collection in ('raw_items','research_items','stock_research_timeline','stock_research_daily'):
        value[collection]=json.loads(json.dumps(value.get(collection,[])).replace('T09:01:00','T08:59:00'))
    path=fake_data/'research/incoming/20261028/0900.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
    script="""
from pathlib import Path
import sys,json
from ops.run_hourly_research import run_hourly_research_file
value=run_hourly_research_file(data_root=Path(sys.argv[1]),source=None,business_date='20261028',target_date='20261028',slot='0900',mode='LIVE')
print(json.dumps({'status':value['status']}))
"""
    result=run_code(case['main'],script,[fake_data],case['env'])
    assert result['status']=='SUCCEEDED'
    case['data']=fake_data
    case['config']['v4_research_data_root']=str(fake_data);reseal_config(case)
    result=stage_result(case)
    assert result['ok'] is False and 'RESEARCH_SOURCE_OWNER_IDENTITY_INVALID' in result['error'],result


def test_reviewer_backdated_materialization_sidecar_is_rejected(case):
    path=case['data']/'research/hourly/publication/live/20261028/0900.json'
    value=json.loads(path.read_bytes());value['available_at']='2026-10-28T09:04:30.000000+08:00';path.write_text(json.dumps(value))
    result=stage_result(case,'09:04:45')
    assert result['ok'] is False and 'PUBLICATION_RECORD_MISMATCH' in result['error'],result


def test_original_scheduler_completion_missing_is_rejected(case):
    (case['ledger']/case['main_result']['dispatch_receipt_path']).unlink()
    result=stage_result(case)
    assert result['ok'] is False and 'WITNESS_MISSING' in result['error'],result


def test_scheduler_self_hash_tamper_is_rejected(case):
    path=case['ledger']/case['main_result']['dispatch_receipt_path']
    value=json.loads(path.read_bytes());value['finished_at']='2026-10-28T01:04:30Z';path.write_text(json.dumps(value))
    result=stage_result(case)
    assert result['ok'] is False and 'LEDGER_INVALID' in result['error'],result


@pytest.mark.parametrize('case',['remove_input_attestation'],indirect=True)
def test_real_executor_refuses_missing_attestation_before_materialization(case):
    assert case['main_result']['dispatch_status']=='FAILED'
    assert not (case['data']/'research/hourly/live/20261028/0900.json').exists()
    assert stage_result(case)['ok'] is False


@pytest.mark.parametrize('case',['spoof_partial_result'],indirect=True)
def test_real_executor_cannot_upgrade_partial_materializer_result(case):
    assert case['main_result']['dispatch_status']=='FAILED'
    assert (case['data']/'research/hourly/live/20261028/0900.json').exists()
    assert stage_result(case)['ok'] is False


@pytest.mark.parametrize('fault',['partial_dispatch_receipt','partial_materialization_payload','wrong_source_sha_with_valid_self_hash'])
def test_partial_write_and_exact_binding_refused(case,fault):
    receipt=case['ledger']/case['main_result']['dispatch_receipt_path']
    if fault=='partial_dispatch_receipt':receipt.write_text('{"schema_version":')
    elif fault=='partial_materialization_payload':(case['data']/'research/hourly/live/20261028/0900.json').write_text('{')
    else:
        value=json.loads(receipt.read_bytes())
        value['workload_results'][0]['_authoritative_payload']['external_source_sha256']='0'*64
        value['ledger_sha256']=sha(json.dumps({k:v for k,v in value.items() if k!='ledger_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        receipt.write_text(json.dumps(value))
    assert stage_result(case)['ok'] is False
