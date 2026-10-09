"""Package orchestration against real release guard and real synthetic R3 stores.

Only npm output/command receipts and external dependency discovery are fixture
boundaries. Research binding revalidation runs the real reader in a child, with
its approved fixture manifest substituted only in this test's temporary source.
No fixture switch exists in the delivered preparation command.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import sys
from types import SimpleNamespace

import pytest


WORK = Path(__file__).resolve().parents[2]
TOOLS = Path(os.environ.get('R4_TOOL_ROOT', WORK/'integration/tools'))
API = Path(os.environ.get('R4_API_WORK_ROOT', WORK/'api'))
API_TESTS = Path(os.environ.get('R4_API_TEST_ROOT', API/'tests'))
API_BEFORE = Path(os.environ.get('R4_API_BEFORE_ROOT', API/'before'))
API_TOOLS = Path(os.environ.get('R4_API_TOOL_ROOT', API/'tools'))
RELEASE = Path(os.environ.get('R4_RELEASE_TOOL_ROOT', WORK/'release/candidate_run/ops'))
UI = ['apps/web/src/App.vue', 'apps/web/src/contracts/runtime.ts',
      'apps/web/src/components/review/StageExecutionEvidencePanel.vue']
API_PATHS = ['apps/api/v35_api/app.py', 'stage_center/consumer.py',
             'stage_center/execution_evidence.py', 'stage_center/research_read_binding.py']
FLAGS = {'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
DIST = 'apps/web/dist'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name,path,monkeypatch):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,name,module)
    spec.loader.exec_module(module)
    return module


def write(path,raw,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def dump(path,value):
    write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())


def inventory(root):
    return {str(p.relative_to(root)):(sha(p.read_bytes()),stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def case(tmp_path,monkeypatch):
    # Reuse the API team's original R3 SelectionStore / receipt writer fixture.
    api_fixture=load('_orchestration_api_fixture',API_TESTS/'conftest.py',monkeypatch)
    research=api_fixture.case.__wrapped__(monkeypatch,tmp_path)
    package=tmp_path/'package';package.mkdir()
    api_after=package/'after/api';shutil.copytree(research.api_root,api_after)
    helper=api_after/'stage_center/research_read_binding.py'
    text=re.sub(r'APPROVED_RESEARCH_RUN = \{.*?\n\}\nR3_READER_SHA256',
                'APPROVED_RESEARCH_RUN = '+repr(research.binding_module.APPROVED_RESEARCH_RUN)+'\nR3_READER_SHA256',
                helper.read_text(),count=1,flags=re.S)
    helper.write_text(text)
    after_app=api_after/'apps/api/v35_api/app.py'
    after_app.write_text(re.sub(r'_STAGE_RESEARCH_READER_SHA256 = "[0-9a-f]{64}"',
        '_STAGE_RESEARCH_READER_SHA256 = "'+sha(helper.read_bytes())+'"',after_app.read_text(),count=1))
    release_root=tmp_path/'active-release';app=release_root/'app'
    shutil.copytree(api_fixture.R3/'test_support/stage_base_app',app)
    for rel in API_PATHS[:3]:
        write(app/rel,(API_BEFORE/rel).read_bytes())
    for rel in UI:
        write(app/rel,b'// ORIGINAL LIVE UI\n')
        write(package/'after/ui'/rel,b'// REVIEWED STAGE UI\n')
    write(app/'apps/web/src/manager.ts',b'export const ISSUE32_MANAGER = true;\n')
    write(app/'apps/web/package.json',b'{"name":"synthetic-fixture","scripts":{"build":"vite build"}}\n')
    write(app/'apps/web/package-lock.json',b'{"lockfileVersion":3}\n')
    write(app/DIST/'index.html',b'<script src="/assets/old.js"></script>\n')
    write(app/DIST/'manager-selection/index.html',b'<script src="../assets/old.js"></script>\n')
    write(app/DIST/'assets/old.js',b'old live bundle\n')
    write(app/'ops/launch_v35_macos_scheduler.sh',b'#!/bin/bash\nexit 0\n',0o755)
    write(app/'v4/manager_research/keep.py',b'ISSUE32 = True\n')
    (package/'release_tools/after/ops').mkdir(parents=True)
    for path in RELEASE.glob('*.py'):
        shutil.copyfile(path,package/'release_tools/after/ops'/path.name)
    (package/'tools').mkdir()
    for name in ('canary_sources.py','prepare_canary.py','build_stage_ui.py'):
        shutil.copyfile(TOOLS/name,package/'tools'/name)
    shutil.copyfile(API_TOOLS/'prepare_research_binding.py',package/'tools/prepare_research_binding.py')
    guard=load('_orchestration_fixture_guard',RELEASE/'api_release_integration.py',monkeypatch)
    entries=guard.inventory_tree(app)
    manifest=release_root/'release-manifest.json'
    dump(manifest,{'schema_version':'v4.release_candidate.v1','activation_status':'NOT_ACTIVATED',
        'candidate':{'root':str(release_root),'app_root':str(app),'release_id':release_root.name},
        'application_inventory':{'entry_count':len(entries),'entries':entries,'aggregate_sha256':guard.inventory_digest(entries)}})
    manager=tmp_path/'manager_state';manager.mkdir()
    write(manager/'preserve.json',b'{"existing_manager_history":true}\n',0o444)
    pointer=tmp_path/'LaunchAgents/com.lexi.v35.api-only.plist'
    write(pointer,plistlib.dumps({'Label':'com.lexi.v35.api-only','ProgramArguments':[
        '/usr/bin/env','RESEARCH_ONLY=1','production_allowed=false','PRODUCTION_ALLOWED=false',
        'buy_gate_updated=false','BUY_GATE_UPDATED=false','orders_sent=false','ORDERS_SENT=false',
        'V35_APP_ROOT='+str(app),'V35_RELEASE_ID='+release_root.name,
        'V35_RELEASE_MANIFEST_PATH='+str(manifest),'V35_RELEASE_MANIFEST_SHA256='+sha(manifest.read_bytes()),
        'V4_MANAGER_RESEARCH_STATE_ROOT='+str(manager),'PYTHONPATH='+str(app),str(Path(sys.executable)),
        '-B','-m','apps.api.v35_api.run','--stage-selection-root',str(research.history.root)],'WorkingDirectory':str(app),
        'EnvironmentVariables':{'V4_MANAGER_RESEARCH_STATE_ROOT':str(manager),'RESEARCH_ONLY':'1',
            'PRODUCTION_ALLOWED':'false','V4_PRESERVED_SETTING':'current-value'}}))
    scheduler=tmp_path/'scheduler.plist'
    write(scheduler,plistlib.dumps({'Label':'com.lexi.v35.scheduler',
        'ProgramArguments':['/bin/bash',str(app/'ops/launch_v35_macos_scheduler.sh')],
        'EnvironmentVariables':{'V35_APP_ROOT':str(app),'RESEARCH_ONLY':'1',
            'production_allowed':'false','buy_gate_updated':'false','orders_sent':'false'}}))
    policy={'schema_version':'V4_CANARY_SOURCE_POLICY_V1','groups':{'ui':{'copy_roots':['apps/web']}}}
    dump(package/'CANARY_SOURCE_POLICY.json',policy)
    rows=[]
    for group,paths in [('api',API_PATHS),('ui',UI)]:
        for rel in paths:
            old=app/rel;after=package/'after'/group/rel
            if old.exists():write(package/'before'/group/rel,old.read_bytes())
            rows.append({'group':group,'relative_path':rel,'after_path':'after/'+group+'/'+rel,
                'after_sha256':sha(after.read_bytes()),'after_bytes':after.stat().st_size,
                'before_path':'before/'+group+'/'+rel if old.exists() else None,
                'before_sha256':sha(old.read_bytes()) if old.exists() else None,
                'accepted_before_sha256':[sha(old.read_bytes())] if old.exists() else [],
                'operation':'modify' if old.exists() else 'add'})
    mapping={'files':rows,'canary_source_policy_sha256':sha((package/'CANARY_SOURCE_POLICY.json').read_bytes()),**FLAGS}
    dump(package/'SOURCE_MAP.json',mapping)
    prepare=load('_orchestration_prepare_canary',package/'tools/prepare_canary.py',monkeypatch)
    prepared=tmp_path/'prepared_ui'
    assert prepare.prepare(package,'ui',app,prepared)['status']=='CANARY_PREPARED'
    sources=prepare.sources
    pol=sources.load_policy(package,mapping,'ui',sources.IGNORED)
    observed=sources.snapshot(prepared,pol,candidate=True)
    build=tmp_path/'build';build.mkdir(mode=0o700)
    nondist={p:r for p,r in observed['entries'].items() if p!=DIST and not p.startswith(DIST+'/')}
    for rel,row in sorted(nondist.items()):
        if rel=='.':continue
        if row['type']=='directory':(build/rel).mkdir(parents=True,exist_ok=True);(build/rel).chmod(0o755)
        else:write(build/rel,(prepared/rel).read_bytes(),row['mode']|stat.S_IWUSR)
    write(build/DIST/'index.html',b'<script src="/assets/new.js"></script>\n')
    write(build/DIST/'manager-selection/index.html',b'<script src="../assets/new.js"></script>\n')
    write(build/DIST/'assets/new.js',b'// synthetic npm fixture, not real compilation\n')
    static=[dict(row,path=DIST+'/'+row['path']) for row in guard.inventory_tree(build/DIST)]
    build_entries=sources.snapshot(build,pol,candidate=True)['entries']
    build_nondist={p:r for p,r in build_entries.items() if p!=DIST and not p.startswith(DIST+'/')}
    provenance=json.loads((prepared/'CANARY_SOURCE_MANIFEST.json').read_text())
    receipt={'schema_version':'V4_STAGE_UI_BUILD_V1','status':'UI_BUILD_PREPARED','package':str(package),
        'prepared_ui':str(prepared),'destination':str(build),'built_dist_root':str(build/DIST),
        'write_performed':True,'source_map_sha256':sha((package/'SOURCE_MAP.json').read_bytes()),
        'prepared_source_manifest_sha256':sha((prepared/'CANARY_SOURCE_MANIFEST.json').read_bytes()),
        'prepared_source_tree_sha256':sources.tree_id(observed['entries']),
        'prepared_source_root':str(app),'lock_sha256':sha((prepared/'apps/web/package-lock.json').read_bytes()),
        'build_source_tree_sha256':sources.tree_id(build_nondist),'static_inventory':static,
        'static_inventory_sha256':guard.inventory_digest(static),'retained_html_entries':['index.html','manager-selection/index.html'],
        'source_bytes_and_modes_unchanged':True,'build_source_bytes_unchanged':True,'errors':[],
        'commands':[{'command':['npm','ci'],'cwd':str(build/'apps/web'),'exit_code':0},
                    {'command':['npm','run','build'],'cwd':str(build/'apps/web'),'exit_code':0}],
        'scope':'SYNTHETIC_NPM_RECEIPT_FOR_ORCHESTRATION_TEST_ONLY',**FLAGS}
    dump(build/'BUILD_RECEIPT.json',receipt)
    prep=load('_orchestration_binding_generator',package/'tools/prepare_research_binding.py',monkeypatch)
    monkeypatch.setattr(prep,'REVIEWED_AFTER_SHA256',{rel:sha((api_after/rel).read_bytes()) for rel in API_PATHS})
    binding=prep.prepare_research_read_binding(manifest_path=research.manifest_path,history_root=research.history.root,
        api_after_root=api_after,api_source_root=app,output_root=tmp_path/'binding')
    target=TOOLS/'prepare_live_release.py'
    tool=load('_live_release_preparation_under_test',target,monkeypatch) if target.exists() else SimpleNamespace()
    if hasattr(tool,'_load_release_tools'):
        actual_loader=tool._load_release_tools
        def load_with_synthetic_dependency_observation(*args,**kwargs):
            value=actual_loader(*args,**kwargs)
            # Original builder gates are exercised; external runtime discovery
            # is a synthetic boundary, since this is not the Mac venv.
            value.builder.dependency_probe=lambda *args,**kwargs:{'status':'OBSERVED_RESOLVED','fixture_only':True}
            return value
        monkeypatch.setattr(tool,'_load_release_tools',load_with_synthetic_dependency_observation)
    args={'package':package,'active_api_plist':pointer,'scheduler_plist':scheduler,'prepared_ui':prepared,
          'ui_build_receipt':build/'BUILD_RECEIPT.json','binding_proof':Path(binding['proof_path']),
          'destination':tmp_path/'prepared_release','python':Path(sys.executable),'release_id':'stage-r4-test-candidate'}
    return SimpleNamespace(root=tmp_path,package=package,app=app,pointer=pointer,prepared=prepared,build=build,
        binding=Path(binding['output_root']),research=research,tool=tool,args=args,guard=guard,sources=sources,policy=pol,
        active_before=guard._inventory_snapshot(app),pointer_before=pointer.read_bytes(),manager=manager,
        manager_before=inventory(manager),mapping=mapping,
        prepared_manifest=provenance,build_receipt=receipt)


def prepare(case):
    assert callable(getattr(case.tool,'prepare_live_release',None)), 'Concrete live-release preparation command is missing'
    return case.tool.prepare_live_release(**case.args)


def test_preparation_builds_concrete_verified_candidate_and_preserves_active_history(case):
    result=prepare(case)
    assert result['status']=='CANDIDATE_READY_NOT_DEPLOYED'
    assert result['deployed'] is False and result['automatic_activation'] is False
    root=Path(result['candidate_root'])
    assert root.is_dir() and Path(result['source_root']).is_dir()
    assert (Path(result['source_root'])/'.git').is_dir()
    assert (root/'app/v4/manager_research/keep.py').read_bytes()==b'ISSUE32 = True\n'
    assert (root/'app/stage_center/approved_research_read.json').read_bytes()==(case.binding/'stage_center/approved_research_read.json').read_bytes()
    assert result['verification']['status']=='PASS'
    assert result['history_root']==str(case.research.history.root)
    assert len(result['verify_command'])>4 and 'SOURCE_ROOT' not in json.dumps(result)
    assert case.guard._inventory_snapshot(case.app)==case.active_before
    assert case.pointer.read_bytes()==case.pointer_before
    assert json.loads(Path(result['receipt_path']).read_text())==result


def test_publication_handoff_preserves_current_manager_and_history_roots(case):
    result=prepare(case)
    plan_path=Path(result['prepared_plan_path'])
    assert plan_path==case.args['destination']/'stage-publication/api-only-preserved-plan.json'
    assert sha(plan_path.read_bytes())==result['prepared_plan_sha256']
    plan=json.loads(plan_path.read_text())
    assert plan['schema_version']=='V4_STAGE_PRESERVED_API_PREPARATION_V1'
    assert plan['status']=='PREPARED_NOT_DEPLOYED' and plan['launchctl_called'] is False
    assert plan['manager_state']=={'current_root':str(case.manager),'candidate_root':str(case.manager),
        'root_preserved':True,'state_copied':False}
    assert plan['history']=={'root':str(case.research.history.root),'root_preserved':True}
    staged_path=Path(result['staged_api_plist_path'])
    assert plan['candidate_plist']=={'path':str(staged_path),'sha256':sha(staged_path.read_bytes())}
    assert result['staged_api_plist_sha256']==sha(staged_path.read_bytes())
    original=plistlib.loads(case.pointer_before);staged=plistlib.loads(staged_path.read_bytes())
    allowed={'V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256','PYTHONPATH'}
    strip=lambda values:[item for item in values if item.split('=',1)[0] not in allowed]
    assert strip(staged['ProgramArguments'])==strip(original['ProgramArguments'])
    assert staged['EnvironmentVariables']==original['EnvironmentVariables']
    assert staged['WorkingDirectory']==str(Path(result['candidate_root'])/'app')
    assert {key:value for key,value in original.items() if key not in {'WorkingDirectory','ProgramArguments'}}=={
        key:value for key,value in staged.items() if key not in {'WorkingDirectory','ProgramArguments'}}
    assert plan['source_plist']['sha256']==sha(case.pointer_before)
    assert plan['candidate_manifest']=={'path':result['manifest_path'],'sha256':result['manifest_sha256']}
    assert plan['source_inputs']['binding_proof']['sha256']==sha(case.args['binding_proof'].read_bytes())
    assert result['builder_only_cutover_plan']['publication_eligible'] is False
    assert result['builder_only_cutover_plan']['reason']=='MANAGER_ROOT_ISOLATED'
    assert Path(result['builder_only_cutover_plan']['path']).is_file()
    assert inventory(case.manager)==case.manager_before
    assert case.pointer.read_bytes()==case.pointer_before
    assert case.guard._inventory_snapshot(case.app)==case.active_before


@pytest.mark.parametrize('fault',['wrong_ui_graph','build_source_graph','prepared_root','forged_receipt',
    'static_bytes','static_sha','package_after','missing_pair','binding_sha','binding_proof_after',
    'binding_manifest','existing_destination','guard_bytes','unsafe_flag','missing_html_dependency'])
def test_preparation_refuses_bad_inputs_before_any_destination_write(case,fault):
    if fault=='wrong_ui_graph':
        path=case.prepared/'apps/web/src/manager.ts';write(path,b'CANONICAL_STALE_MANAGER\n')
        value=json.loads((case.prepared/'CANARY_SOURCE_MANIFEST.json').read_text())
        value['candidate_tree_sha256']=case.sources.tree_id(case.sources.snapshot(case.prepared,case.policy,candidate=True)['entries'])
        dump(case.prepared/'CANARY_SOURCE_MANIFEST.json',value)
        receipt=case.build_receipt
        receipt['prepared_source_manifest_sha256']=sha((case.prepared/'CANARY_SOURCE_MANIFEST.json').read_bytes())
        receipt['prepared_source_tree_sha256']=value['candidate_tree_sha256']
        dump(case.args['ui_build_receipt'],receipt)
    if fault=='build_source_graph':
        write(case.build/'apps/web/src/manager.ts',b'CANONICAL_STALE_MANAGER\n')
        rows=case.sources.snapshot(case.build,case.policy,candidate=True)['entries']
        rows={p:r for p,r in rows.items() if p!=DIST and not p.startswith(DIST+'/')}
        receipt=case.build_receipt;receipt['build_source_tree_sha256']=case.sources.tree_id(rows)
        dump(case.args['ui_build_receipt'],receipt)
    if fault=='prepared_root':
        value=json.loads((case.prepared/'CANARY_SOURCE_MANIFEST.json').read_text());value['source_root']=str(case.root/'old-canonical')
        dump(case.prepared/'CANARY_SOURCE_MANIFEST.json',value)
    if fault=='forged_receipt':
        receipt=case.build_receipt;receipt['prepared_source_manifest_sha256']='f'*64;dump(case.args['ui_build_receipt'],receipt)
    if fault=='static_bytes':write(case.build/DIST/'assets/new.js',b'UNREVIEWED_BUNDLE\n')
    if fault=='static_sha':
        receipt=case.build_receipt;receipt['static_inventory_sha256']='f'*64;dump(case.args['ui_build_receipt'],receipt)
    if fault=='package_after':write(case.package/'after/api/stage_center/consumer.py',b'UNREVIEWED_CONSUMER\n')
    if fault=='missing_pair':(case.binding/'stage_center/approved_research_read.sha256').unlink()
    if fault=='binding_sha':write(case.binding/'stage_center/approved_research_read.json',b'{}\n')
    if fault=='binding_proof_after':
        proof=json.loads(case.args['binding_proof'].read_text());proof['reviewed_api_after_sha256'][API_PATHS[0]]='f'*64
        dump(case.args['binding_proof'],proof)
    if fault=='binding_manifest':case.research.manifest_path.write_bytes(case.research.manifest_path.read_bytes()+b'\n')
    if fault=='existing_destination':case.args['destination'].mkdir();write(case.args['destination']/'keep',b'KEEP\n')
    if fault=='guard_bytes':
        path=case.package/'release_tools/after/ops/api_release_integration.py';write(path,path.read_bytes()+b'\n')
    if fault=='unsafe_flag':
        receipt=case.build_receipt;receipt['production_allowed']=True;dump(case.args['ui_build_receipt'],receipt)
    if fault=='missing_html_dependency':
        write(case.build/DIST/'index.html',b'<script src="/assets/missing.js"></script>\n')
        rows=[dict(row,path=DIST+'/'+row['path']) for row in case.guard.inventory_tree(case.build/DIST)]
        receipt=case.build_receipt;receipt['static_inventory']=rows;receipt['static_inventory_sha256']=case.guard.inventory_digest(rows)
        dump(case.args['ui_build_receipt'],receipt)
    with pytest.raises((ValueError,OSError)):
        prepare(case)
    if fault=='existing_destination':assert (case.args['destination']/'keep').read_bytes()==b'KEEP\n'
    else:assert not case.args['destination'].exists()
    assert case.guard._inventory_snapshot(case.app)==case.active_before
    assert case.pointer.read_bytes()==case.pointer_before


def test_partial_builder_failure_is_preserved_and_never_claimed_ready(case,monkeypatch):
    assert callable(getattr(case.tool,'prepare_live_release',None)), 'Concrete live-release preparation command is missing'
    actual=case.tool._load_release_tools
    def broken_builder(*args,**kwargs):
        tools=actual(*args,**kwargs)
        def fail(**kwargs):
            kwargs['candidate_root'].mkdir()
            write(kwargs['candidate_root']/'.candidate-build-in-progress',b'EXPECTED_PARTIAL_FAILURE\n')
            raise ValueError('FIXTURE_BUILDER_FAILURE')
        tools.builder.build_candidate=fail
        return tools
    monkeypatch.setattr(case.tool,'_load_release_tools',broken_builder)
    with pytest.raises(ValueError,match='FIXTURE_BUILDER_FAILURE'):
        prepare(case)
    assert case.args['destination'].is_dir()
    receipt=json.loads((case.args['destination']/'PREPARATION_RECEIPT.json').read_text())
    assert receipt['status']=='PREPARATION_FAILED'
    assert receipt['deployed'] is False
    assert list(case.args['destination'].rglob('.candidate-build-in-progress'))
    assert case.guard._inventory_snapshot(case.app)==case.active_before
