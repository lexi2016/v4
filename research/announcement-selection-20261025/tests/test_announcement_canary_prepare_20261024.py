"""Task8b public CLI only; original planner/report, controlled runtime dependencies."""
from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace

import pytest
from ops import run_manager_flash_announcements as owner
from v4.manager_workbench import announcement_classification as classification

MODEL='qwen3_8_flash_next'
JOB='e'*32
DAY='20261021'
VENDOR=Path('/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/announcement_queue.py')


def raw(value):return owner.canonical(value)+b'\n'
def sha(value):return hashlib.sha256(value).hexdigest()
def snapshot(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*a,**k):pytest.fail('Task8b attempted network')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect_ex',forbidden)


@pytest.fixture
def case(tmp_path,monkeypatch):
    assert sha(VENDOR.read_bytes())=='5e8158fc578c2e005204b984a95ada4429c15750f81a9c2fa58baa906cabc7b7'
    spec=importlib.util.spec_from_file_location('task8b_frozen_vendor_queue',VENDOR)
    vendor=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,vendor);spec.loader.exec_module(vendor)
    for name in ('run_next','recover_interrupted','enqueue','_claim_next_locked'):
        monkeypatch.setattr(vendor.SerialAnnouncementQueue,name,lambda *a,**k:pytest.fail('preparation reached queue mutation/dispatch'))
    roots={k:tmp_path/k for k in ('state','capture','shared','config')}
    for p in roots.values():p.mkdir()
    legacy=tmp_path/'original-legacy';lock=legacy/'locks'/('model-'+sha(MODEL.encode())+'.lock')
    lock.parent.mkdir(parents=True);lock.write_bytes(b'original controlled gate')
    settings=roots['config']/'runtime.json';settings.write_bytes(raw({'fixture':'runtime'}))
    model_settings=roots['config']/'model.json';model_settings.write_bytes(raw({'fixture':'model'}))
    body='Controlled complete source: operating revenue increased, subject to disclosed conditions.'
    row={'art_code':'CONTROLLED','body_text':body,'body_complete':True,'body_text_sha256':sha(body.encode()),
        'source_sha256':'b'*64,'source_issuer_codes':[{'code':'HK.00001','name':'Controlled issuer'}],
        'title':'经营事项公告','publication_date':'2026-10-20','available_at':'2026-10-20T18:30:00+08:00'}
    capture={'schema_version':'mwb.capture.window.v1','owner':'v4.manager_workbench.capture_announcements',
        'source':'EASTMONEY_HK','saved_ref':None,'rows':[row]}
    cap_raw=raw(capture);cap_ref='products/'+sha(cap_raw)+'.json';cap_path=roots['capture']/cap_ref
    cap_path.parent.mkdir();cap_path.write_bytes(cap_raw)
    inp={'schema':'v4.manager_workbench.announcement_flash_input.v1','job_id':JOB,'target_date':DAY,
        'cutoff':'2026-10-21T09:00:00+08:00','capture_product':{'artifact_ref':cap_ref,'sha256':sha(cap_raw)},
        'daily_workflow':'P23','classification_policy':classification.policy()}
    inp_path=roots['state']/('announcement_flash/jobs/'+JOB+'/input.json');inp_path.parent.mkdir(parents=True);inp_path.write_bytes(raw(inp))
    from test_announcement_semantic_authority_20261024 import genuine_material
    material=genuine_material(runtime_sha=sha(settings.read_bytes()),model_sha=sha(model_settings.read_bytes()))
    calls={'tokenizer':0,'history':0,'queue_roots':[],'guards':0}
    runner=SimpleNamespace(MODEL_ID=MODEL,SIMPLE_WORKFLOW_RANGE_PROFILE=owner.PROFILE,
        SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL=material['citation_protocol'],OMLX_TOKENIZER_PATH=roots['config']/'cached-cpu-tokenizer',
        OMLX_SETTINGS_PATH=settings,OMLX_MODEL_SETTINGS_PATH=model_settings,
        load_active_contract=lambda *a:SimpleNamespace(source_sha256='f'*64),
        build_source_unit_map=lambda body,digest:{'source_unit_map_sha256':'1'*64,'units':[]},
        simple_fixed_facts=SimpleNamespace(extract_fixed_facts=lambda *a:{'ledger_sha256':'2'*64}))
    helper=SimpleNamespace(_messages_for_article=lambda *a:[{'role':'user','content':body}],_token_count=lambda *a:100)
    modules={'announcement_queue':vendor,'batch_runner':runner,'automatic_canary_server':SimpleNamespace(),
        'build_length_canary':SimpleNamespace(make_batch=lambda *a:{'controlled_batch':True})}
    for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
    class Tokenizer:
        @staticmethod
        def from_pretrained(path,**kwargs):
            assert path==str(runner.OMLX_TOKENIZER_PATH)
            assert kwargs==dict(local_files_only=True,trust_remote_code=False,use_fast=True)
            calls['tokenizer']+=1;return object()
    monkeypatch.setitem(sys.modules,'transformers',SimpleNamespace(AutoTokenizer=Tokenizer))
    monkeypatch.setattr(owner,'_load_helper',lambda:helper)
    monkeypatch.setattr(owner,'_owned_request_material',lambda *a,**k:deepcopy(material))
    def guard_factory(*a):
        def guard():calls['guards']+=1
        return guard
    monkeypatch.setattr(owner,'_announcement_execution_guard',guard_factory)
    monkeypatch.setattr(owner,'_capture_origin',lambda *a:[{'role':'CONTROLLED_SOURCE_AUTHORITY','source_product_sha256':sha(cap_raw)}])
    from v4.manager_workbench import announcement_membership as membership
    gate={'status':'VERIFIED','codes':['HK.00001'],'authority_sha256':'3'*64,'target_date':DAY}
    monkeypatch.setattr(membership,'revalidate_membership_gate',lambda *a:deepcopy(gate))
    def history():
        calls['history']+=1
        return [{'identity':{'article_id':'CONTROLLED:UNRELATED','body_sha256':'4'*64},'status':'SUCCEEDED'}]
    monkeypatch.setattr(owner,'_pinned_candidate_history',history)
    original_queue=owner._new_only_queue
    def observe_queue(*a,**kw):
        q=original_queue(*a,**kw);calls['queue_roots'].append((q.state_root,q._model_lock_path));return q
    monkeypatch.setattr(owner,'_new_only_queue',observe_queue)
    source_refs=['ops/run_manager_flash_announcements.py','infrastructure/model_execution_gate.py',
        'v4/manager_workbench/announcement_preprocessing.py','v4/manager_workbench/announcement_classification.py',
        'v4/manager_workbench/announcement_membership.py','v4/manager_workbench/engines/announcement.py']
    files={str(owner.REPO_ROOT/ref):sha((owner.REPO_ROOT/ref).read_bytes()) for ref in source_refs}
    files.update({str(p):sha(p.read_bytes()) for p in (inp_path,cap_path,settings,model_settings)})
    request_identity={k:deepcopy(material[k]) for k in ('configuration_sha256','prompt_sha256','schema_sha256',
        'runtime_settings_sha256','model_settings_sha256','runtime_limits')}
    request_identity['model_id']=material['configuration_material']['model_id']
    request_identity['max_completion_tokens']=material['configuration_material']['max_completion_tokens']
    marker={'schema':'v4.manager_workbench.announcement_isolated_preparation.v1','mode':'PREPARE_ONLY',
        'test_run_id':'task8b-controlled','job_id':JOB,'target_date':DAY,'input_sha256':sha(inp_path.read_bytes()),
        'roots':{'isolation':str(tmp_path),**{k:str(v) for k,v in roots.items()}},
        'frozen_files':files,'frozen_files_sha256':sha(owner.canonical(files)),
        'request_identity':request_identity,'settings_paths':{'runtime':str(settings),'model':str(model_settings)}}
    st=lock.stat();binding={'legacy_queue_root':str(legacy),'device':st.st_dev,'inode':st.st_ino,
        'sha256':sha(lock.read_bytes()),'code_identity':{ref:files[str(owner.REPO_ROOT/ref)] for ref in source_refs},
        'isolated_preparation':marker}
    binding_path=roots['config']/'binding.json'
    def seal():binding_path.write_bytes(raw(binding));return sha(binding_path.read_bytes())
    def argv(extra=(),marked=True):
        pin=seal()
        args=['--state-root',str(roots['state']),'--capture-root',str(roots['capture']),'--shared-root',str(roots['shared']),
            '--job-id',JOB,'--legacy-gate-binding',str(binding_path),'--legacy-gate-binding-sha256',pin]
        return args+(['--preprocess-only'] if marked else [])+list(extra)
    return SimpleNamespace(root=tmp_path,roots=roots,legacy=legacy,lock=lock,binding=binding,marker=marker,
        binding_path=binding_path,seal=seal,argv=argv,input=inp,input_path=inp_path,capture=capture,capture_path=cap_path,
        material=material,calls=calls,runner=runner,vendor=vendor,
        report=roots['state']/('announcement_flash/jobs/'+JOB+'/preprocessing-report.json'))


def test_marked_public_cli_uses_original_builder_zero_dispatch_even_busy_gate(case,monkeypatch,capsys):
    # A busy owner is preserved; no preparation path may acquire any flock.
    with case.lock.open('rb') as owned:
        fcntl.flock(owned,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=snapshot(case.legacy)
        def no_flock(*a,**k):pytest.fail('preparation acquired a physical or queue lock')
        monkeypatch.setattr(fcntl,'flock',no_flock)
        assert owner.main(case.argv())==0
        assert snapshot(case.legacy)==before
    payload=json.loads(capsys.readouterr().out)
    report=json.loads(case.report.read_bytes())
    assert payload['state']=='PREPROCESSING_COMPLETE'
    assert payload['report']==report
    assert report['schema']=='v4.manager_workbench.announcement_preprocessing.v1'
    assert report['first_article_id']=='EASTMONEY:CONTROLLED'
    assert report['counts']['model_required_articles']==report['counts']['expected_model_requests']==1
    assert report['model_requests']==report['queue_claims']==0
    assert report['history_context']==[]  # Only unrelated authenticated fixture history existed.
    assert case.calls['history']==case.calls['tokenizer']==1
    assert case.calls['queue_roots']==[(case.roots['state']/'announcement_flash/queue',case.lock)]
    assert not (case.roots['state']/'announcement_flash/queue/queue-state.json').exists()
    assert not list(case.roots['state'].rglob('attempt-*'))


def assert_rejected_without_writes(case,monkeypatch,args):
    before=snapshot(case.root)
    monkeypatch.setattr(owner,'_run',lambda *a,**k:pytest.fail('invalid preparation entered producer'))
    assert owner.main(args)==2
    assert snapshot(case.root)==before
    assert case.calls['history']==case.calls['tokenizer']==0


@pytest.mark.parametrize('extra',[
    ['--execute-preprocessed-report-sha256','a'*64,'--execution-phase','FIRST'],
    ['--execution-phase','CONTINUE'],['--extension-sha256','a'*64],
    ['--resume-pending'],['--resume-frozen-batch'],['--resume-action','CANARY'],
    ['--resume-dry-run'],['--resume-source-job-id',JOB],['--source-input-sha256','a'*64],
    ['--source-progress-sha256','a'*64],['--source-queue-state-sha256','a'*64],
    ['--max-model-calls','1'],['--materialize-saved-partial'],['--failure-code','CONTROLLED']])
def test_preparation_mode_is_closed_before_writes(case,monkeypatch,extra):
    assert_rejected_without_writes(case,monkeypatch,case.argv(extra))


@pytest.mark.parametrize('omit',['preprocess','shared-root'])
def test_marker_cannot_enter_default_or_missing_shared_mode(case,monkeypatch,omit):
    args=case.argv()
    if omit=='preprocess':args.remove('--preprocess-only')
    else:
        index=args.index('--shared-root');del args[index:index+2]
    assert_rejected_without_writes(case,monkeypatch,args)


@pytest.mark.parametrize('kind',['input','capture','runtime','model','code','gate-content','gate-inode',
    'gate-missing','binding-sha','inventory-omitted','self-cycle','job','date','roots-overlap',
    'production-root','symlink-root','symlink-source','request-model','bad-roots','bad-identity','bad-capture'])
def test_frozen_identity_drift_before_any_write(case,monkeypatch,kind):
    args=case.argv()
    if kind in ('input','capture','runtime','model'):
        path={'input':case.input_path,'capture':case.capture_path,
            'runtime':case.runner.OMLX_SETTINGS_PATH,'model':case.runner.OMLX_MODEL_SETTINGS_PATH}[kind]
        path.write_bytes(path.read_bytes()+b' ')
    elif kind=='code':
        ref='ops/run_manager_flash_announcements.py'
        case.binding['code_identity'][ref]='0'*64
        args=case.argv()
    elif kind=='gate-content':case.lock.write_bytes(b'drift')
    elif kind=='gate-inode':
        replacement=case.lock.with_suffix('.replacement');replacement.write_bytes(case.lock.read_bytes());replacement.replace(case.lock)
    elif kind=='gate-missing':case.lock.unlink()
    elif kind=='binding-sha':case.binding_path.write_bytes(case.binding_path.read_bytes()+b' ')
    else:
        if kind=='inventory-omitted':case.marker['frozen_files'].pop(str(case.capture_path))
        elif kind=='self-cycle':case.marker['frozen_files'][str(case.binding_path)]='a'*64
        elif kind=='job':case.marker['job_id']='f'*32
        elif kind=='date':case.marker['target_date']='20261022'
        elif kind=='roots-overlap':case.marker['roots']['shared']=str(case.roots['state'])
        elif kind=='production-root':case.marker['roots']['state']='/Users/lexi/Desktop/学习/v4_app/runtime'
        elif kind=='symlink-root':
            link=case.root/'state-alias';link.symlink_to(case.roots['state'],target_is_directory=True)
            case.marker['roots']['state']=str(link)
        elif kind=='symlink-source':
            path=case.root/'source-alias';path.symlink_to(case.capture_path)
            case.marker['frozen_files'][str(path)]=sha(case.capture_path.read_bytes())
        elif kind=='request-model':case.marker['request_identity']['model_id']='default_model'
        elif kind=='bad-roots':case.marker['roots']=list(case.marker['roots'])
        elif kind=='bad-identity':case.marker['request_identity']=list(case.marker['request_identity'])
        elif kind=='bad-capture':
            case.input['capture_product']=[];case.input_path.write_bytes(raw(case.input))
            case.marker['input_sha256']=sha(case.input_path.read_bytes())
            case.marker['frozen_files'][str(case.input_path)]=case.marker['input_sha256']
        case.marker['frozen_files_sha256']=sha(owner.canonical(case.marker['frozen_files']))
        args=case.argv()
    assert_rejected_without_writes(case,monkeypatch,args)


@pytest.mark.parametrize('policy',[None,{},dict(schema='unsupported')])
def test_missing_or_invalid_policy_cannot_enter_producer(case,monkeypatch,policy):
    case.input['classification_policy']=policy;case.input_path.write_bytes(raw(case.input))
    case.marker['input_sha256']=sha(case.input_path.read_bytes())
    case.marker['frozen_files'][str(case.input_path)]=case.marker['input_sha256']
    case.marker['frozen_files_sha256']=sha(owner.canonical(case.marker['frozen_files']))
    assert_rejected_without_writes(case,monkeypatch,case.argv())


@pytest.mark.parametrize('change',['request-identity','profile','model','runtime-guard'])
def test_runtime_identity_and_original_guards_precede_plan_writes(case,monkeypatch,change):
    if change=='request-identity':case.material['prompt_sha256']='0'*64
    elif change=='profile':case.material['workflow_profile']='unsupported'
    elif change=='model':case.runner.MODEL_ID='default_model'
    else:
        def factory(*a):
            def guard():raise owner.FlashRunError('CONTROLLED_ORIGINAL_GUARD_DRIFT')
            return guard
        monkeypatch.setattr(owner,'_announcement_execution_guard',factory)
    args=case.argv();before=snapshot(case.root)
    assert owner.main(args)==2
    assert snapshot(case.root)==before
    assert case.calls['tokenizer']==case.calls['history']==0


def test_mandatory_history_failure_cannot_create_report_or_dispatch(case,monkeypatch):
    def unavailable():raise owner.FlashRunError('CONTROLLED_HISTORY_UNAVAILABLE')
    monkeypatch.setattr(owner,'_pinned_candidate_history',unavailable)
    assert owner.main(case.argv())==2
    assert not case.report.exists()
    assert not (case.roots['state']/'announcement_flash/queue/queue-state.json').exists()
    assert not list(case.roots['state'].rglob('attempt-*'))


def test_unmarked_legacy_preprocess_remains_rejected(case,monkeypatch):
    case.binding.pop('isolated_preparation')
    assert_rejected_without_writes(case,monkeypatch,case.argv())


def test_normal_unmarked_first_reaches_original_admission_using_same_gate(case,monkeypatch,capsys):
    assert owner.main(case.argv())==0
    capsys.readouterr()
    report_raw=case.report.read_bytes();report=json.loads(report_raw)
    # A separately sealed, unmarked binding authorizes only the old FIRST predicate.
    case.binding.pop('isolated_preparation')
    class ReachedOriginalEnqueue(BaseException):pass
    reached=[]
    def controlled_enqueue(queue,payload):
        reached.append(payload)
        assert queue.queue_id==owner.QUEUE_ID
        assert queue._model_lock_path==case.lock
        queue.binding_guard()
        assert payload['article_id']==report['first_article_id']
        assert payload['bounded_execution']=={'job_id':JOB,'report_sha256':sha(report_raw)}
        raise ReachedOriginalEnqueue
    # Original admission and stable dedup logic run; only final queue mutation is intercepted.
    monkeypatch.setattr(case.vendor.SerialAnnouncementQueue,'enqueue',controlled_enqueue)
    with pytest.raises(ReachedOriginalEnqueue):
        owner.main(case.argv(['--execute-preprocessed-report-sha256',sha(report_raw),'--execution-phase','FIRST'],marked=False))
    assert len(reached)==1
    assert case.calls['queue_roots'][-1]==(case.roots['state']/'announcement_flash/queue',case.lock)
    assert case.report.read_bytes()==report_raw
    assert not (case.roots['state']/'announcement_flash/queue/queue-state.json').exists()


def test_genuine_full_envelope_new_preparation_identity_only(case):
    from test_announcement_semantic_authority_20261024 import genuine_material
    material=genuine_material(runtime_sha=sha(case.runner.OMLX_SETTINGS_PATH.read_bytes()),
        model_sha=sha(case.runner.OMLX_MODEL_SETTINGS_PATH.read_bytes()))
    case.material.clear();case.material.update(material)
    case.marker['request_identity']={k:deepcopy(material[k]) for k in ('configuration_sha256','prompt_sha256','schema_sha256',
        'runtime_settings_sha256','model_settings_sha256','runtime_limits')}
    case.marker['request_identity'].update(model_id=material['configuration_material']['model_id'],
        max_completion_tokens=material['configuration_material']['max_completion_tokens'])
    pin=case.seal()
    fields=('execute_preprocessed_report_sha256','execution_phase','extension_sha256','resume_pending',
        'resume_frozen_batch','resume_action','resume_dry_run','resume_source_job_id','source_input_sha256',
        'source_progress_sha256','source_queue_state_sha256','materialize_saved_partial','failure_code','max_model_calls')
    args=SimpleNamespace(**dict.fromkeys(fields),preprocess_only=True,shared_root=str(case.roots['shared']),
        state_root=str(case.roots['state']),capture_root=str(case.roots['capture']),job_id=JOB)
    before=snapshot(case.root)
    guard=owner._isolated_preparation_guard(args,case.binding,case.binding_path,pin)
    guard(material,case.runner)
    assert snapshot(case.root)==before
    assert case.calls['tokenizer']==case.calls['history']==0


@pytest.mark.parametrize('variant', __import__('test_announcement_semantic_authority_20261024').ENVELOPE_DRIFTS)
def test_original_envelope_drift_in_new_prep_guard_rejects_before_any_write(case,variant):
    from test_announcement_semantic_authority_20261024 import drift_envelope
    drift_envelope(case.material,variant)
    args=case.argv();before=snapshot(case.root)
    assert owner.main(args)==2
    assert snapshot(case.root)==before
    assert case.calls['tokenizer']==case.calls['history']==0


def test_original_report_none_budget_retains_strict_effective_nested_budget(case,capsys):
    assert 'model_id' not in case.material and 'max_completion_tokens' not in case.material
    assert type(case.material['configuration_material']['max_completion_tokens']) is int
    assert case.material['configuration_material']['max_completion_tokens']==32768
    assert owner.main(case.argv())==0
    report=json.loads(case.report.read_bytes())
    assert report['processing_contract']==owner._classification_contract(case.material,case.runner)
    assert report['processing_contract']['max_completion_tokens'] is None
    assert report['processing_contract']['model_id']==MODEL
    assert report['model_requests']==report['queue_claims']==0
