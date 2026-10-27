from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import json,shutil
import pytest
import controller as c
from test_stage_resume_r3 import resume_fixture


def fixture(tmp_path,monkeypatch):
 p,first,first_events=resume_fixture(tmp_path,monkeypatch)
 comp=Path(p['lifecycle_component']['target']);comp.mkdir();(comp/'readme').write_text('immutable')
 manifest=comp/'release-manifest.json';manifest.write_text(json.dumps({'files':{'readme':c.sha(comp/'readme')}}));source=tmp_path/'component-source';shutil.copytree(comp,source)
 p['lifecycle_component'].update(source=str(source),manifest_sha256=c.sha(manifest))
 for name,meta in p['components'].items():
  root=Path(meta['release_root']);(root/'app').mkdir(parents=True);m=root/'release-manifest.json';m.write_text(json.dumps({'app_files':[],'symlinks':[]}));meta.update(sha256=c.sha(m),path=str(m))
 p['config_target']=str(Path(p['components']['collector']['release_root'])/'config.json');Path(p['config_target']).write_text('{}');p['config_sha256']=c.sha(p['config_target'])
 identity={'deployment_plan_sha256':'r3-plan','controller_sha256':'r3-controller','case_manifest_sha256':'r3-case','materialized_entry_probe_sha256':'r3-old-probe'}
 review=tmp_path/'r3-review.json';review.write_text(json.dumps({'verdict':'PASS',**identity}));api=Path(p['components']['api']['release_root']);meta=p['components']['api']
 events=[{'at':'then','event':'ROOT_PRESTAGE_RESUME_R1_STARTED','plan_sha256':'r3-plan','pre_service_only_proof':True,'prior_failure':first['failure'],'prior_journal_sha256':c.PRESTAGE_R1_JOURNAL_SHA,'prior_review':first['accepted_prior_review'],'review_sha256':c.sha(review)},
 {'at':'then','event':'PRIOR_BEFORE_HTTP_REUSED_NO_REFETCH','codes':['601198.SH','601059.SH'],'prior_journal_sha256':c.PRESTAGE_R1_JOURNAL_SHA},{'at':'then','event':'ORIGINAL_GRAPH_ACTIVE_TREE_VERIFIED_NO_SCHEMA_ADAPTER'},
 {'at':'then','event':'ORIGINAL_API_DISPATCHER_MATERIALIZED','exit_code':0,'stderr':'','stdout':json.dumps({'app_root':str(api/'app'),'release_id':api.name,'release_manifest_path':str(api/'release-manifest.json'),'release_manifest_sha256':meta['sha256']})},
 {'at':'then','event':'MATERIALIZED_ORIGINAL_LOADER_PROBE','exit_code':1,'stdout':'','stderr':"KeyError: 'ops._a_share_daily_sync_parts.sync_workflow'"}]
 prior=tmp_path/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl';prior.write_text(''.join(json.dumps(e)+'\n' for e in events));monkeypatch.setattr(c,'MATERIALIZED_R3_JOURNAL_SHA',c.sha(prior))
 targets={p['lifecycle_component']['target']:p['lifecycle_component']['manifest_sha256'],**{m['release_root']:m['sha256'] for m in p['components'].values()}}
 f=tmp_path/'ROOT_MATERIALIZED_PROBE_FAILURE_R1.json';f.write_text(json.dumps({'status':'FAILED_MATERIALIZED_ENTRY_PROBE_PRE_SERVICE','prior_journal_sha256':c.MATERIALIZED_R3_JOURNAL_SHA,'service_actions':0,'error':'KeyError: ops._a_share_daily_sync_parts.sync_workflow','event_names':[e['event'] for e in events],'new_release_roots':{s:True for s in targets},'materialized_manifest_sha256':{Path(s).name:h for s,h in targets.items()},'before_plist_sha256':{r['label']:r['before_sha256'] for r in p['operations']}}))
 probe=tmp_path/'probe_materialized_entry.py';probe.write_text('corrected read only probe');stderr=tmp_path/'probe.stderr';stderr.write_text('');result=tmp_path/'probe-result.json'
 component=comp/'a_sync';main=Path(p['components']['main']['release_root'])/'app'
 result.write_text(json.dumps({'status':'MATERIALIZED_ORIGINAL_STRICT_LOADER_PASS','caller':str(main/'ops/macos_research_panel_daily_authority.py'),'entry':str(component/'app/ops/a_share_daily_sync.py'),'facade':str(component/'component/ops/a_share_daily_sync.py'),'workflow':str(component/'component/ops/_a_share_daily_sync_parts/sync_workflow.py'),'seed_path':str(component/'component/seed-evidence-descriptor.json'),'pins':15,'component_manifest_sha256':'67d3abe86e6035a4b2461941b07a57aee096e6be05c95d32f498c8e90fe7c1ef','provider_calls':0,'network_calls':0,'business_execution':False}))
 def ref(path):return {'path':str(path),'sha256':c.sha(path)}
 b={'scope':'FIXED_FULLY_MATERIALIZED_R3_PROBE_FAILURE_ONLY','first_journal':first['prior_journal'],'materialized_journal':ref(prior),'failure':ref(f),'accepted_prior_review':ref(review),'snapshot_map':first['snapshot_map'],'prior_identity':identity,'before_http':first['before_http'],'expected_current_bindings':first['expected_current_bindings'],'corrected_probe':ref(probe),'corrected_probe_result':ref(result),'corrected_probe_stderr':ref(stderr),'new_journal_path':str(tmp_path/'ROOT_EXECUTION_MATERIALIZED_RESUME_R3.jsonl')}
 binding=tmp_path/'materialized-binding.json';binding.write_text(json.dumps(b));p['resume_materialized_r3']=ref(binding)
 return p,b,events


def test_fixed_materialized_checkpoint_reuses_evidence_without_copy_or_dispatcher(tmp_path,monkeypatch):
 p,b,e=fixture(tmp_path,monkeypatch);x=c.Capsule.__new__(c.Capsule);x.p=p
 x.compare=lambda:None;x.observe_service_binding=lambda name:b['expected_current_bindings'][name];x.graph_disabled=lambda:False;x.g=SimpleNamespace(initial_old=lambda pid:{'pid':pid});x.op=SimpleNamespace(verify_release=lambda *a:None)
 x.stage=lambda:pytest.fail('must not copy/stage again');x.dispatcher=lambda:pytest.fail('dispatcher PASS must be reused');x.materialized_entry_probe=lambda:pytest.fail('actual corrected PASS must be reused');x.history_http=lambda *a:pytest.fail('before HTTP must be reused')
 @contextmanager
 def no_lock():raise RuntimeError('STOP_BEFORE_ANY_LOCK');yield
 x.original_main_control_owner=no_lock;monkeypatch.setattr(c,'approve',lambda *a:None);(tmp_path/'PLAN.json').write_text(json.dumps(p))
 with pytest.raises(RuntimeError,match='STOP_BEFORE_ANY_LOCK'):x.execute(tmp_path/'review','sha',11,resume_materialized_r3=True)
 x.j.stream.close();events=[json.loads(line) for line in Path(b['new_journal_path']).read_text().splitlines()]
 assert events[0]['first_journal_sha256']==c.PRESTAGE_R1_JOURNAL_SHA and events[0]['prior_journal_sha256']==c.MATERIALIZED_R3_JOURNAL_SHA
 assert events[-1]['event']=='IMMUTABLE_TARGETS_DISPATCHER_AND_CORRECTED_PROBE_REUSED_NO_COPY'
 with pytest.raises(c.Stop,match='PRIOR_EXECUTION_PRESERVED'):c.Journal()
 with pytest.raises(c.Stop,match='ALREADY_ATTEMPTED'):c.validate_materialized_r3_files(b,p)

@pytest.mark.parametrize('problem',['service_event','dispatcher_failure','wrong_probe_error','manifest_drift','before_http_drift','before_plist_drift','probe_result_drift','new_journal_exists'])
def test_materialized_checkpoint_refuses_drift_or_unknown_actions(tmp_path,monkeypatch,problem):
 p,b,e=fixture(tmp_path,monkeypatch)
 if problem in {'service_event','dispatcher_failure','wrong_probe_error'}:
  if problem=='service_event':e.append({'event':'COMMAND_INTENT','args':['bootout']})
  elif problem=='dispatcher_failure':e[3]['exit_code']=1
  else:e[4]['stderr']='another error'
  prior=Path(b['materialized_journal']['path']);prior.write_text(''.join(json.dumps(v)+'\n' for v in e));b['materialized_journal']['sha256']=c.sha(prior);monkeypatch.setattr(c,'MATERIALIZED_R3_JOURNAL_SHA',c.sha(prior))
  f=Path(b['failure']['path']);v=json.loads(f.read_text());v['prior_journal_sha256']=c.sha(prior);f.write_text(json.dumps(v));b['failure']['sha256']=c.sha(f)
 elif problem=='manifest_drift':(Path(p['components']['api']['release_root'])/'release-manifest.json').write_text('changed')
 elif problem=='before_http_drift':Path(b['before_http'][0]['path']).write_text('changed')
 elif problem=='before_plist_drift':Path(p['operations'][0]['plist']).write_text('changed')
 elif problem=='probe_result_drift':Path(b['corrected_probe_result']['path']).write_text('{}')
 else:Path(b['new_journal_path']).write_text('previous attempt')
 with pytest.raises(c.Stop):c.validate_materialized_r3_files(b,p)
 if problem!='new_journal_exists':assert not Path(b['new_journal_path']).exists()


def test_materialized_full_inventory_rejects_extra_object_before_journal(tmp_path,monkeypatch):
 p,b,e=fixture(tmp_path,monkeypatch);(Path(p['components']['main']['release_root'])/'app/extra').write_text('extra')
 x=c.Capsule.__new__(c.Capsule);x.p=p;x.op=SimpleNamespace(verify_release=lambda *a:None)
 with pytest.raises(c.Stop,match='INVENTORY_SET'):x.verify_materialized_r3_targets()
 assert not Path(b['new_journal_path']).exists()
