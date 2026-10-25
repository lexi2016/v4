"""Task7 offline context/API boundary; no sockets, live queue, or model."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from v4.manager_workbench.announcement_test import TestContext, create_app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def forbidden(*_a,**_k):pytest.fail('Task7 attempted socket access')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect_ex',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True)+"\n").encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def frozen(tmp_path):
    material = tmp_path / "materials"
    material.mkdir()
    fixture = {"state": "PARTIAL", "source_date": "20261021", "target_trade_date": "20261021",
               "stocks": [], "failures": [], "pending": [], "gaps": [], "counts": {"model_succeeded": 14, "pending": 201}}
    raw = encode(fixture)
    (material / "fixture.json").write_bytes(raw)
    manifest = {"files": [{"root": "fixture", "artifact_ref": "fixture.json", "sha256": sha(raw)}]}
    manifest_raw = encode(manifest)
    (material / "manifest.json").write_bytes(manifest_raw)
    from v4.manager_workbench import announcement_test
    context = {"test_run_id": "task7-fixture", "target_date": "20261021", "mode": "fixture",
        "source_manifest": {"path": str(material / "manifest.json"), "sha256": sha(manifest_raw)},
        "read_only_material_roots": {"fixture": str(material)},
        "independent_state_root": str(tmp_path / "state"),
        "code_identity": {"v4/manager_workbench/announcement_test.py": sha(Path(announcement_test.__file__).read_bytes())},
        "config_identity": "a"*64, "model_identity": {"model_id": "FIXTURE_NO_MODEL", "configuration_sha256": "b"*64}}
    path = tmp_path / "context.json"
    path.write_bytes(encode(context))
    return tmp_path, path, context


def load(frozen):
    root, path, _ = frozen
    return TestContext.load(path, sha(path.read_bytes()), allowed_test_root=root)


def bytes_snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_get_reads_fixture_zero_writes_and_all_production_controls_404(frozen):
    context = load(frozen)
    before = bytes_snapshot(frozen[0])
    with TestClient(create_app(context)) as client:
        r = client.get("/api/v4/announcement-test/context")
        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "fixture"
        r = client.get("/api/v4/announcement-test/announcement-flash", params={"test_run_id": "task7-fixture", "target_date": "20261021"})
        assert r.status_code == 200
        body = r.json()
        assert body["RESEARCH_ONLY"] is True and body["orders_sent"] is False
        assert body["data"]["test_evidence_kind"] == "FIXTURE_NOT_PRODUCTION_EVIDENCE"
        assert body["data"]["counts"]["model_succeeded"] == 14
        for suffix in ("update", "resume", "a"*32+"/stop", "a"*32+"/execute-preprocessed"):
            assert client.post("/api/v4/manager-workbench/announcement-flash/"+suffix).status_code == 404
        assert client.post("/api/v4/announcement-test/canary", json={"test_run_id": "task7-fixture"}).status_code == 409
    assert bytes_snapshot(frozen[0]) == before
    assert not (frozen[0] / "state").exists()


def test_wrong_context_date_and_run_fail_closed(frozen):
    with TestClient(create_app(load(frozen))) as client:
        for params in ({"test_run_id":"other", "target_date":"20261021"}, {"test_run_id":"task7-fixture", "target_date":"20261022"}):
            assert client.get("/api/v4/announcement-test/announcement-flash", params=params).status_code == 409


@pytest.mark.parametrize("field", ["independent_state_root", "material"])
def test_symlink_escape_rejected_without_creating_state(frozen, field):
    root,path,value=frozen
    outside=root.parent / (root.name+"-outside")
    outside.mkdir()
    link=root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    if field == "material": value["read_only_material_roots"]["fixture"] = str(link)
    else: value[field] = str(link / "state")
    path.write_bytes(encode(value))
    with pytest.raises(ValueError): load(frozen)
    assert not (outside/"state").exists()


@pytest.mark.parametrize("root", ["/Users/lexi/Library/Application Support/com.lexi.v4.local/state", "/Users/lexi/Desktop/学习/v4_app", "/Users/lexi/Library/Application Support/com.lexi.v35.local/state"])
def test_production_root_rejected_before_write(frozen, root):
    _,path,value=frozen
    value["independent_state_root"]=root
    path.write_bytes(encode(value))
    with pytest.raises(ValueError): load(frozen)


def test_manifest_and_source_drift_rejected(frozen):
    context=load(frozen)
    (frozen[0]/"materials/fixture.json").write_text("{}")
    with pytest.raises(ValueError): context.read_flash()


def test_context_hash_code_identity_and_overlapping_state_rejected(frozen):
    root,path,value=frozen
    with pytest.raises(ValueError): TestContext.load(path,"0"*64,allowed_test_root=root)
    value["independent_state_root"] = value["read_only_material_roots"]["fixture"]+"/state"
    path.write_bytes(encode(value))
    with pytest.raises(ValueError): load(frozen)


def test_reader_default_late_binding_and_explicit_semantic_injection(monkeypatch):
    from v4.manager_workbench import announcement_update as owner
    from types import SimpleNamespace
    calls=[]
    def default_pin():
        calls.append('late-default')
        raise owner.CandidateEvidenceError('TEST_PIN')
    monkeypatch.setattr(owner,'read_pinned_candidates',default_pin)
    reader=owner.AnnouncementUpdate(SimpleNamespace())
    # Late module binding preserves legacy test adapters and formal defaults.
    assert reader._pinned_reader is None
    assert (reader._pinned_reader or owner.read_pinned_candidates) is default_pin
    injected=owner.AnnouncementUpdate(SimpleNamespace(),semantic_reader=lambda j,s: {'job_id':j,'report_sha256':s,'status':'UNREVIEWED'})
    assert injected.semantic_recovery_snapshot('job','sha')['status']=='UNREVIEWED'
    assert calls==[]


def real_context(frozen, *, mode='readonly'):
    root,path,value=frozen
    material=root/'materials'
    roots={role:material/role for role in ('state','capture','shared','config')}
    for p in roots.values():p.mkdir()
    from v4.manager_workbench import announcement_test as module
    value['mode']=mode
    value['read_only_material_roots']={k:str(v) for k,v in roots.items()}
    value['source_manifest']['path']=str(roots['config']/'manifest.json')
    required=['v4/manager_workbench/announcement_test.py','v4/manager_workbench/announcement_update.py',
        'v4/manager_workbench/announcement_projection.py','v4/manager_workbench/announcement_delivery.py',
        'ops/run_manager_flash_announcements.py','infrastructure/model_execution_gate.py']
    value['code_identity']={ref:sha((module.REPO/ref).read_bytes()) for ref in required}
    value['model_identity']={'model_id':'qwen3_8_flash_next','configuration_sha256':'b'*64}
    config=encode({'model_identity':value['model_identity']})
    (roots['config']/'config.json').write_bytes(config)
    value['config_identity']=sha(config)
    return root,path,value,roots


def seal_context(path,value,roots):
    files=[]
    for role,root in roots.items():
        for p in root.rglob('*'):
            if p.is_file():files.append({'root':role,'artifact_ref':p.relative_to(root).as_posix(),'sha256':sha(p.read_bytes())})
    manifest=Path(value['source_manifest']['path']);raw=encode({'files':files});manifest.write_bytes(raw)
    value['source_manifest']['sha256']=sha(raw);path.write_bytes(encode(value))
    return TestContext.load(path,sha(path.read_bytes()),allowed_test_root=path.parent)


def test_readonly_factory_never_falls_back_to_live_pinned_or_semantic(frozen,monkeypatch):
    from v4.manager_workbench import announcement_update as owner
    def forbidden(*a,**k):pytest.fail('live authority called')
    monkeypatch.setattr(owner,'read_pinned_candidates',forbidden)
    # The context factory must bypass the live implementation with its explicit
    # unbound authority, even when a future semantic hook changes internals.
    import ops.run_manager_flash_announcements as runner
    monkeypatch.setattr(runner,'_extension_plan',forbidden)
    root,path,value,roots=real_context(frozen)
    context=seal_context(path,value,roots)
    before=bytes_snapshot(root)
    result=context.read_flash()
    assert result['stocks']==[]
    assert result['historical_candidates']['availability']=='UNAVAILABLE'
    assert bytes_snapshot(root)==before
    assert not (root/'state').exists()


def test_real_canary_entry_uses_existing_runner_parameters_once_without_real_execution(frozen):
    from types import SimpleNamespace
    root,path,value,roots=real_context(frozen,mode='canary')
    job='a'*32; aid='EASTMONEY:OFFLINE_SINGLE'
    report={'job_id':job,'target_date':value['target_date'],'first_article_id':aid,
        'processing_contract':value['model_identity'],
        'execution_manifest':[{'article_id':aid,'body_sha256':'c'*64}],
        'counts':{'expected_model_requests':1,'model_required_articles':1},
        'catalogue':[{'article_id':aid,'source_sha256':'d'*64,'body_sha256':'c'*64}]}
    prefix=roots['state']/'announcement_flash/jobs'/job;prefix.mkdir(parents=True)
    input_raw=encode({'job_id':job,'target_date':value['target_date']})
    report_raw=encode(report)
    (prefix/'input.json').write_bytes(input_raw);(prefix/'preprocessing-report.json').write_bytes(report_raw)
    legacy=root/'controlled-legacy/locks';legacy.mkdir(parents=True)
    lock=legacy/('model-'+sha(b'qwen3_8_flash_next')+'.lock');lock.write_bytes(b'')
    st=lock.stat()
    gate={'legacy_queue_root':str(legacy.parent),'device':st.st_dev,'inode':st.st_ino,'sha256':sha(b''),
        'code_identity':value['code_identity']}
    (roots['config']/'gate.json').write_bytes(encode(gate))
    value['canary']={'approval_stage':'TASK8_FROZEN_SINGLE_ARTICLE','job_id':job,'article_id':aid,
        'input_sha256':sha(input_raw),'report_sha256':sha(report_raw),'body_sha256':'c'*64,'source_sha256':'d'*64,
        'legacy_gate_binding_ref':'gate.json'}
    context=seal_context(path,value,roots)
    commands=[]
    def controlled(command,**kwargs):commands.append(command);return SimpleNamespace(returncode=0)
    before=bytes_snapshot(roots['state'])
    result=context.execute_canary(execute=controlled)
    assert result['state']=='FAILED'  # A mock process return alone is not delivery.
    assert result['semantic_status']=='UNREVIEWED'
    assert len(commands)==1
    command=commands[0]
    assert command[2].endswith('/ops/run_manager_flash_announcements.py')
    assert command[command.index('--state-root')+1]==str(root/'state')
    assert command[command.index('--execution-phase')+1]=='FIRST'
    assert command[command.index('--legacy-gate-binding')+1]==str(roots['config']/'gate.json')
    assert bytes_snapshot(roots['state'])==before
    assert context.read_flash()['current_job']['state']=='FAILED'
    assert context.public()['canary_allowed'] is False
    with pytest.raises(FileExistsError):context.execute_canary(execute=controlled)
    assert len(commands)==1


def test_isolated_queue_shares_frozen_busy_legacy_gate_and_drift_fails_before_claim(tmp_path):
    import fcntl
    import importlib.util
    import sys
    from ops import run_manager_flash_announcements as runner
    source=Path('/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/announcement_queue.py')
    assert sha(source.read_bytes())=='5e8158fc578c2e005204b984a95ada4429c15750f81a9c2fa58baa906cabc7b7'
    spec=importlib.util.spec_from_file_location('task7_vendor_queue',source)
    vendor=importlib.util.module_from_spec(spec);sys.modules[spec.name]=vendor;spec.loader.exec_module(vendor)
    legacy=tmp_path/'legacy';lock=legacy/'locks'/('model-'+sha(b'qwen3_8_flash_next')+'.lock')
    lock.parent.mkdir(parents=True);lock.write_bytes(b'');st=lock.stat()
    binding={'legacy_queue_root':str(legacy),'device':st.st_dev,'inode':st.st_ino,'sha256':sha(b''),
        'code_identity':{ref:sha((runner.REPO_ROOT/ref).read_bytes()) for ref in
            ('ops/run_manager_flash_announcements.py','infrastructure/model_execution_gate.py')}}
    state=tmp_path/'isolated';calls=[]
    queue=runner._new_only_queue(vendor,state,'qwen3_8_flash_next',binding_guard=lambda:None,legacy_gate=binding)
    assert queue._model_lock_path==lock
    from infrastructure import zsxq_pdf_local as pdf
    payload=pdf._make_classification_payload(import_date='20261024',document_id='task7-isolated',
        pdf_sha256='a'*64,text='[PAGE 1]\ncontrolled fixture',page_count=1,text_truncated=False)
    item=queue.enqueue(payload)
    before=(state/'queue-state.json').read_bytes()
    with lock.open('rb') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(Exception):queue.run_next(lambda j:calls.append(j),lambda *a:True,wait_for_model_slot=False)
        fcntl.flock(handle,fcntl.LOCK_UN)
    assert calls==[]
    assert (state/'queue-state.json').read_bytes()==before
    queue_state=json.loads((state/'queue-state.json').read_bytes())
    assert queue_state['jobs'][item['idempotency_key']]['attempt_count']==0
    lock.unlink();lock.write_bytes(b'replacement')
    with pytest.raises(Exception):queue.run_next(lambda j:calls.append(j),lambda *a:True,wait_for_model_slot=False)
    assert calls==[]
    missing=tmp_path/'never-created'
    with pytest.raises(runner.FlashRunError):runner._new_only_queue(vendor,missing,'qwen3_8_flash_next',legacy_gate=binding)
    assert not missing.exists()


def test_each_contribution_analysis_binds_own_delivery_and_bad_neighbor_does_not_mask_good(tmp_path, monkeypatch):
    import importlib.util
    from v4.manager_workbench import announcement_delivery as deliveries
    source=Path(__file__).with_name('test_announcement_projection_20261024.py')
    assert sha(source.read_bytes())=='392188220100341e0a60b96e7c2998e6854c55fd8ebf63b733defee3f2a50198'
    spec=importlib.util.spec_from_file_location('task7_projection_fixture',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    case=module.case.__wrapped__(tmp_path,monkeypatch)
    old=module.OLD;current=module.CURRENT
    case.add(old)
    delivered,binding,_=case.add(current,symbol='HK.00002')
    article=delivered['articles'][0]
    reader={k:article[k] for k in ('source_sha256','body_sha256','disposition','direction','reason')}
    reader.update(selection_basis='controlled full analysis',evidence_sufficiency='SOURCE_TEXT',
        facts=[{'claim':'claim','quote':'quoted source','locator':'L1'}],changes=[],impact=[],
        confirmation_conditions=[],counter_evidence=[],risk_notes=['synthetic fixture'])
    result_raw=encode({'results':[{'article_id':article['article_id'],'reader_output':reader}]})
    ref='jobs/'+article['queue_key']+'/attempt-0001.validated.json'
    case.io.write_bytes('announcement_flash/queue/'+ref,result_raw)
    article.update(result_ref=ref,result_sha256=sha(result_raw),selection_basis=reader['selection_basis'])
    binding=deliveries.publish(case.io,current,delivered)
    case.semantics[current]['delivery_sha256']=binding['sha256']
    case.latest()
    value=case.update.read(module.DAY)
    rows={item['job_id']:item for item in value['day_summary']['contributions']}
    assert set(rows)=={old,current}
    assert rows[old]['daily_analysis']['articles'][0]['analysis_state']=='UNAVAILABLE'
    good=rows[current]['daily_analysis']
    assert good['delivery_sha256']==rows[current]['delivery_sha256']==binding['sha256']
    assert good['articles'][0]['reader_output']['facts'][0]['quote']=='quoted source'
    assert rows[old]['daily_analysis']['delivery_sha256']!=good['delivery_sha256']
    assert value['dedupe_evidence'][0]['basis']=='SYMBOL_ARTICLE_BODY_SHA'


def test_readonly_context_actual_material_keeps_unbound_semantic_unreviewed(frozen,monkeypatch):
    from v4.manager_workbench import announcement_update as owner, announcement_delivery as delivery
    from infrastructure.owned_io import SafeRoot
    import ops.run_manager_flash_announcements as runner
    root,path,value,roots=real_context(frozen)
    def forbidden(*a,**k):pytest.fail('live authority called')
    monkeypatch.setattr(owner,'read_pinned_candidates',forbidden)
    monkeypatch.setattr(runner,'_extension_plan',forbidden)
    job='f'*32
    report={'job_id':job,'target_date':value['target_date'],'accounting_closed':True,
        'catalogue':[],'capture_product':{'artifact_ref':'products/x.json','sha256':'d'*64}}
    raw=encode(report);io=SafeRoot(roots['state'])
    io.write_bytes('announcement_flash/jobs/'+job+'/preprocessing-report.json',raw)
    delivered={'schema':delivery.SCHEMA,'job_id':job,'target_trade_date':value['target_date'],
        'preprocessing_report_sha256':sha(raw),'capture_product':report['capture_product'],'articles':[],
        'stocks':[],'state':'PARTIAL','counts':{}}
    delivery.publish(io,job,delivered)
    io.write_bytes('cursors/announcement_flash_delivery_index.json',encode({'items':[{'job_id':job,'target_date':value['target_date']}]}))
    context=seal_context(path,value,roots)
    before=bytes_snapshot(root);data=context.read_flash()
    assert data['day_summary']['contribution_count']==0
    assert data['unreviewed_contributions'][0]['job_id']==job
    assert data['unreviewed_contributions'][0]['reason']=='TEST_SEMANTIC_AUTHORITY_UNBOUND'
    assert bytes_snapshot(root)==before


def test_fixture_full_bound_canary_still_rejected_without_writes(frozen):
    context=load(frozen);before=bytes_snapshot(frozen[0])
    with TestClient(create_app(context)) as client:
        public=context.public()
        body={k:public[k] for k in ('test_run_id','target_date','source_manifest_sha256')}
        assert client.post('/api/v4/announcement-test/canary',json=body).status_code==409
    assert bytes_snapshot(frozen[0])==before
    assert not (frozen[0]/'state').exists()


def test_nonfixture_default_model_fallback_rejected(frozen):
    root,path,value,roots=real_context(frozen)
    value['model_identity']['model_id']='qwen3_8_27b'
    raw=encode({'model_identity':value['model_identity']});(roots['config']/'config.json').write_bytes(raw)
    value['config_identity']=sha(raw)
    with pytest.raises(ValueError,match='TEST_EXPLICIT_FLASH_MODEL_REQUIRED'):seal_context(path,value,roots)


def test_gate_code_drift_rejected_before_isolated_work(tmp_path):
    from ops import run_manager_flash_announcements as runner
    binding={'legacy_queue_root':str(tmp_path/'legacy'),'device':0,'inode':0,'sha256':'0'*64,
        'code_identity':{'ops/run_manager_flash_announcements.py':'0'*64,'infrastructure/model_execution_gate.py':'0'*64}}
    with pytest.raises(runner.FlashRunError,match='TEST_LEGACY_GATE_BINDING_CHANGED'):
        runner._test_legacy_gate(binding,'qwen3_8_flash_next')
    assert list(tmp_path.iterdir())==[]


def test_first_authority_context_uses_real_shared_verifier_and_append_only_output(tmp_path, monkeypatch):
    """Synthetic bindings only: this test issues no business-semantic verdict."""
    from test_announcement_semantic_authority_20261024 import SyntheticCase
    from v4.manager_workbench import announcement_test as module
    from v4.manager_workbench import announcement_delivery as delivery
    import ops.run_manager_flash_announcements as runner
    from infrastructure.owned_io import SafeRoot
    case=SyntheticCase(tmp_path.resolve())
    def forbidden(*a, **k):pytest.fail('FIRST test fell back to production recovery')
    monkeypatch.setattr(runner,'_extension_plan',forbidden)
    prepared=tmp_path/'prepared';prepared.mkdir()
    for ref in ('input.json','preprocessing-report.json'):
        p=prepared/case.prefix/ref;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(case.state.read_bytes(case.prefix+'/'+ref))
    shared=tmp_path/'shared';shared.mkdir()
    codes=dict(case.contract['code_identity'])
    codes.update({ref:sha((module.REPO/ref).read_bytes()) for ref in
        ('v4/manager_workbench/announcement_projection.py','v4/manager_workbench/announcement_delivery.py',
         'infrastructure/model_execution_gate.py')})
    config=encode({'model_identity':{'model_id':case.material['configuration_material']['model_id'],
        'configuration_sha256':case.material['configuration_sha256']}})
    case.config.write_bytes('config.json',config)
    roots={'state':prepared,'capture':case.capture.root,'shared':shared,'config':case.config.root}
    manifest=case.config.root/'manifest.json'
    value={'test_run_id':'SYNTHETIC_FIRST_RUN','target_date':case.day,'mode':'canary',
        'independent_state_root':str(case.state.root),'read_only_material_roots':{k:str(v) for k,v in roots.items()},
        'source_manifest':{'path':str(manifest)},'code_identity':codes,'config_identity':sha(config),
        'model_identity':json.loads(config)['model_identity'],'first_semantic_authority':case.descriptor}
    path=tmp_path/'context.json';context=seal_context(path,value,roots)
    case.context_binding={'run_id':value['test_run_id'],'context_sha256':context.expected_sha256,
        'source_manifest_sha256':value['source_manifest']['sha256']}
    case.execute_synthetic_files()
    case.state.write_bytes('test-canary-attempt.json',encode({'test_run_id':value['test_run_id'],
        'source_manifest_sha256':value['source_manifest']['sha256']}))
    case.state.write_bytes('cursors/announcement_flash_delivery_index.json',encode({'items':[
        {'job_id':case.job,'target_date':case.day}]}))
    assert context.read_flash()['unreviewed_contributions'][0]['job_id']==case.job
    immutable=bytes_snapshot(prepared),bytes_snapshot(case.config.root),path.read_bytes()
    case.append_synthetic_review()
    before=bytes_snapshot(tmp_path)
    result=context.read_flash()
    assert result['day_summary']['contribution_count']==1
    contribution=result['day_summary']['contributions'][0]
    assert contribution['availability']=='AVAILABLE'
    assert contribution['daily_analysis']['articles'][0]['analysis_state']=='AVAILABLE'
    # Structural semantic authority does not manufacture missing membership.
    assert result['stocks']==[]
    assert bytes_snapshot(tmp_path)==before
    assert immutable==(bytes_snapshot(prepared),bytes_snapshot(case.config.root),path.read_bytes())
    # Bad neighbor is isolated by the actual reader, not a global authority gate.
    bad='f'*32
    case.state.write_bytes('announcement_flash/jobs/'+bad+'/preprocessing-report.json',encode({
        **case.report,'job_id':bad,'catalogue':[]}))
    bad_report=case.state.read_bytes('announcement_flash/jobs/'+bad+'/preprocessing-report.json')
    bad_delivery={**case.delivered,'job_id':bad,'preprocessing_report_sha256':sha(bad_report)}
    delivery.publish(case.state,bad,bad_delivery)
    case.state.write_bytes('cursors/announcement_flash_delivery_index.json',encode({'items':[
        {'job_id':case.job,'target_date':case.day},{'job_id':bad,'target_date':case.day}]}))
    result=context.read_flash()
    assert result['day_summary']['contribution_count']==1
    assert result['isolated_contributions'][0]['job_id']==bad
    assert result['day_summary']['contributions'][0]['job_id']==case.job
