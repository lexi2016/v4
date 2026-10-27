from pathlib import Path
from types import SimpleNamespace
import json,os
import pytest
import controller as c

def file_row(root,relative):
 p=root/relative;return {'path':relative,'bytes':p.stat().st_size,'sha256':c.sha(p)}

def link_fixture(tmp_path):
 root=tmp_path/'app';root.mkdir();(root/'kept.py').write_text('source')
 authority=tmp_path/'authority';authority.mkdir();(authority/'do_not_read_or_copy').write_text('not app inventory')
 (root/'dependency').symlink_to(authority,target_is_directory=True);(root/'alias').symlink_to('dependency',target_is_directory=True)
 return root,[file_row(root,'kept.py')],[{'path':'dependency','target':str(authority)},{'path':'alias','target':'dependency'}]

def test_exact_declared_absolute_and_relative_links_are_opaque(tmp_path):
 root,files,links=link_fixture(tmp_path);x=c.Capsule.__new__(c.Capsule);x.exact_inventory(root,files,links)
 assert not (root/'do_not_read_or_copy').exists()

def test_declared_link_target_drift_is_rejected(tmp_path):
 root,files,links=link_fixture(tmp_path);(root/'alias').unlink();(root/'alias').symlink_to('elsewhere')
 with pytest.raises(c.Stop,match='CHANGED_SYMLINK'):c.Capsule.__new__(c.Capsule).exact_inventory(root,files,links)

def test_declared_link_replaced_by_regular_file_is_rejected(tmp_path):
 root,files,links=link_fixture(tmp_path);(root/'alias').unlink();(root/'alias').write_text('dependency')
 with pytest.raises(c.Stop,match='LINK_TYPE_DRIFT'):c.Capsule.__new__(c.Capsule).exact_inventory(root,files,links)

@pytest.mark.parametrize('kind',['file','link','fifo'])
def test_undeclared_extra_objects_are_rejected(tmp_path,kind):
 root,files,links=link_fixture(tmp_path);extra=root/'undeclared'
 if kind=='file':extra.write_text('extra')
 elif kind=='link':extra.symlink_to(tmp_path/'authority')
 else:os.mkfifo(extra)
 with pytest.raises(c.Stop):c.Capsule.__new__(c.Capsule).exact_inventory(root,files,links)


def resume_fixture(tmp_path,monkeypatch):
 monkeypatch.setattr(c,'D',tmp_path)
 paths={name:str(tmp_path/('target-'+name)) for name in c.LABELS};component=str(tmp_path/'target-component')
 plan={'components':{name:{'release_root':path} for name,path in paths.items()},'lifecycle_component':{'target':component},'operations':[]}
 for name,label in c.LABELS.items():
  p=tmp_path/(name+'.plist');p.write_text('old '+name);plan['operations'].append({'label':label,'plist':str(p),'before_sha256':c.sha(p)})
 identity={'deployment_plan_sha256':'old-plan','controller_sha256':'old-controller','case_manifest_sha256':'old-case'}
 review=tmp_path/'prior-review.json';review.write_text(json.dumps({'verdict':'PASS',**identity}))
 events=[{'at':'2026-10-27T08:31:14+08:00','event':'ROOT_DEPLOYMENT_STARTED','plan_sha256':'old-plan','review_sha256':c.sha(review)}];refs=[]
 for code in ('601198.SH','601059.SH'):
  p=tmp_path/('ROOT_HTTP_before_'+code+'.json');p.write_text(json.dumps({'ts_code':code,'start_date':'20261019','end_date':'20261026','cannot_confirm':['original']}));ref={'code':code,'path':str(p),'sha256':c.sha(p)};refs.append(ref);events.append({'at':'2026-10-27T08:31:20+08:00','event':'ROOT_BOUNDED_HTTP_READ','phase':'before',**ref})
 prior=tmp_path/'ROOT_EXECUTION.jsonl';prior.write_text(''.join(json.dumps(row)+'\n' for row in events));digest=c.sha(prior);monkeypatch.setattr(c,'PRESTAGE_R1_JOURNAL_SHA',digest)
 failure=tmp_path/'ROOT_STAGE_FAILURE_R1.json';failure.write_text(json.dumps({'status':'FAILED_PRE_SERVICE_OLD_TREE_DECLARED_SYMLINK_REJECTED','journal_sha256':digest,'exit_code':1,'service_actions_in_journal':[],'error':'Stop: UNEXPECTED_SYMLINK:app/v3_shared_data','new_release_roots':{p:False for p in [component,*paths.values()]},'plist_sha256':{r['label']:r['before_sha256'] for r in plan['operations']}}))
 snapshot=tmp_path/'snapshot-map.json';snapshot.write_text('{}')
 def ref(p):return {'path':str(p),'sha256':c.sha(p)}
 expected={name:{'kind':'LOADED','file_version':'OLD','loaded_version':'OLD','pid':0 if name=='collector' else 11 if name=='main' else 12,'identity':None if name=='collector' else {'pid':11 if name=='main' else 12,'start':'old'},'plist_sha256':'old-'+name} for name in c.LABELS}
 binding={'scope':'FIXED_PRE_SERVICE_STAGE_FAILURE_R1_ONLY','prior_journal':ref(prior),'failure':ref(failure),'accepted_prior_review':ref(review),'snapshot_map':ref(snapshot),'prior_identity':identity,'before_http':refs,'expected_current_bindings':expected,'new_journal_path':str(tmp_path/'ROOT_EXECUTION_PRESTAGE_RESUME_R1.jsonl')}
 return plan,binding,events


def test_fixed_resume_accepts_exact_three_events_and_reuses_before_http(tmp_path,monkeypatch):
 plan,binding,_=resume_fixture(tmp_path,monkeypatch);raw=Path(binding['prior_journal']['path']).read_bytes();data=c.validate_prestage_resume_r1_files(binding,plan)
 assert list(data)==['601198.SH','601059.SH'];j=c.PrestageResumeR1Journal(binding);j.record('ROOT_PRESTAGE_RESUME_R1_STARTED',prior_journal_sha256=c.PRESTAGE_R1_JOURNAL_SHA);j.stream.close()
 assert Path(binding['prior_journal']['path']).read_bytes()==raw
 with pytest.raises(c.Stop,match='ALREADY_ATTEMPTED'):c.validate_prestage_resume_r1_files(binding,plan)
 with pytest.raises(c.Stop,match='PRIOR_EXECUTION_PRESERVED'):c.Journal()

@pytest.mark.parametrize('problem',['journal_drift','command_event','four_events','wrong_http_phase','http_drift','existing_target','dangling_target','plist_drift','failure_service_action','review_identity','existing_new_journal'])
def test_fixed_resume_rejects_non_pre_service_or_drift_before_new_journal(tmp_path,monkeypatch,problem):
 plan,binding,events=resume_fixture(tmp_path,monkeypatch);prior=Path(binding['prior_journal']['path'])
 if problem=='journal_drift':prior.write_text(prior.read_text()+'{}\n')
 elif problem in {'command_event','four_events','wrong_http_phase'}:
  if problem=='command_event':events[2]={'at':'now','event':'COMMAND_INTENT','args':['bootout']}
  elif problem=='four_events':events.append({'event':'STAGED_ALL_IMMUTABLE_RELEASES_VERIFIED'})
  else:events[2]['phase']='after'
  prior.write_text(''.join(json.dumps(e)+'\n' for e in events));binding['prior_journal']['sha256']=c.sha(prior);monkeypatch.setattr(c,'PRESTAGE_R1_JOURNAL_SHA',c.sha(prior))
  p=Path(binding['failure']['path']);f=json.loads(p.read_text());f['journal_sha256']=c.sha(prior);p.write_text(json.dumps(f));binding['failure']['sha256']=c.sha(p)
 elif problem=='http_drift':Path(binding['before_http'][0]['path']).write_text('changed')
 elif problem in {'existing_target','dangling_target'}:
  p=Path(plan['lifecycle_component']['target'])
  if problem=='existing_target':p.mkdir()
  else:p.symlink_to('missing')
 elif problem=='plist_drift':Path(plan['operations'][0]['plist']).write_text('changed')
 elif problem=='failure_service_action':
  p=Path(binding['failure']['path']);f=json.loads(p.read_text());f['service_actions_in_journal']=['bootout'];p.write_text(json.dumps(f));binding['failure']['sha256']=c.sha(p)
 elif problem=='review_identity':binding['prior_identity']['controller_sha256']='other'
 else:Path(binding['new_journal_path']).write_text('prior attempt')
 with pytest.raises(c.Stop):c.validate_prestage_resume_r1_files(binding,plan)
 if problem!='existing_new_journal':assert not Path(binding['new_journal_path']).exists()


def test_resume_current_loaded_identity_drift_rejects_without_journal(tmp_path,monkeypatch):
 plan,binding,_=resume_fixture(tmp_path,monkeypatch);p=tmp_path/'binding.json';p.write_text(json.dumps(binding));plan['prestage_resume_r1']={'path':str(p),'sha256':c.sha(p)}
 x=c.Capsule.__new__(c.Capsule);x.p=plan;x.compare=lambda:None;x.graph_disabled=lambda:False;x.g=SimpleNamespace(initial_old=lambda pid:None)
 x.observe_service_binding=lambda name:{**binding['expected_current_bindings'][name],'pid':999} if name=='api' else binding['expected_current_bindings'][name]
 with pytest.raises(c.Stop,match='IDENTITY_DRIFT'):x.validate_prestage_resume_r1(11)
 assert not Path(binding['new_journal_path']).exists()


def test_resume_file_validation_precedes_journal_open_and_no_before_refetch(tmp_path,monkeypatch):
 # Execute only through stage sentinel, with real fixed-resume files and
 # current identity check. Any before HTTP invocation or service call fails.
 plan,binding,_=resume_fixture(tmp_path,monkeypatch);p=tmp_path/'binding.json';p.write_text(json.dumps(binding));plan['prestage_resume_r1']={'path':str(p),'sha256':c.sha(p)};plan['old_api_app']='/old/api'
 (tmp_path/'PLAN.json').write_text(json.dumps(plan))
 monkeypatch.setattr(c,'approve',lambda *a:None)
 x=c.Capsule.__new__(c.Capsule);x.p=plan;x.compare=lambda:None;x.graph_disabled=lambda:False;x.g=SimpleNamespace(initial_old=lambda pid:{'pid':pid});x.observe_service_binding=lambda name:binding['expected_current_bindings'][name]
 x.history_http=lambda *a:pytest.fail('prior before HTTP must never be fetched again')
 def stage():assert x.baseline_http['601198.SH']['cannot_confirm']==['original'];raise RuntimeError('STOP_AT_STAGE_NO_RUNTIME_ACTION')
 x.stage=stage
 with pytest.raises(RuntimeError,match='STOP_AT_STAGE'):x.execute(tmp_path/'review','sha',11,resume_prestage_r1=True)
 x.j.stream.close();events=[json.loads(line) for line in Path(binding['new_journal_path']).read_text().splitlines()]
 assert [e['event'] for e in events]==['ROOT_PRESTAGE_RESUME_R1_STARTED','PRIOR_BEFORE_HTTP_REUSED_NO_REFETCH']
 assert events[0]['prior_journal_sha256']==c.PRESTAGE_R1_JOURNAL_SHA
