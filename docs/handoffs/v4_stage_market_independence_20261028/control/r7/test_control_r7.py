"""Owned-temp, fake launchd safety tests. No real labels, locks or data writes."""
from pathlib import Path
import copy,importlib.util,json,os,subprocess,sys,tempfile,threading,time,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import main_api_controller as c
P=c.load(HERE/'PLAN_REVIEW_ONLY_R7.json')

def handoff():
 now=time.time();result=dict(operation_id='a'*32,root_ack_dir='/private/var/tmp/v4-r7-nextspawn-'+'a'*32,plan_sha256=c.sha(c.canonical(P)),legitimate_daily_producer_complete=True,all_daily_descendants_absent=True,no_active_dependent_api_query=True,api_brief_new_connection_gap_coordinated=True,expires_epoch=now+240,observed_epoch=now,data_pins=[{'x':1}],data_stats=[{'x':1}],pdf_admission_disabled_by_existing_time_window=True,no_live_pdf_child=True,no_parallel_lifecycle_owner=True,all_current_main_children_and_jobs_finished=True,identities={r:dict(pid=P['expected_original_pids'][r],ps_sha256='f'*64,ps_text='old') for r in c.ROLES})
 result['role_observations']={r:dict(disposition='ORIGINAL_UNTOUCHED',checkpoint_phase='WAITING_ROOT_ACK',current_identity=i) for r,i in result['identities'].items()}
 return result

class Fake:
 def __init__(self):self.old=handoff()['identities']['main'];self.alive=True;self.child_alive=True;self.signals=0;self.bootouts=0;self.armed=True;self.guard_i=dict(pid=999,ps_sha256='g',ps_text='/bin/sleep 604800')
 def initial_main_idle(self,old):pass
 def protection(self,h):pass
 def ack(self,h):pass
 def pdf_boundary(self):pass
 def original(self,r,i):
  if i!=self.old or not self.alive:raise c.Stop('OWNER_CHANGED')
 def descendants(self,p):return {'42':{'pid':42,'ps_sha256':'child','ps_text':'child'}} if self.child_alive else {}
 def term(self,r,i):self.original(r,i);self.signals+=1
 def identity(self,p):
  if p==self.old['pid']:return self.old if self.alive else None
  if p==42:return {'pid':42,'ps_sha256':'child','ps_text':'child'} if self.child_alive else None
  if p==999:return self.guard_i if self.armed else None
 def service(self,r):return {'loaded':True,'pid':self.old['pid'] if self.alive else 999}
 def guard(self,r,old):
  if not self.armed:raise c.Stop('MISSING_GUARD')
  return self.guard_i
 def no_old_root_processes(self,r):pass
 def bootout_guard(self,r,g,old):
  if self.alive or self.child_alive:raise c.Stop('UNSAFE_BOOTOUT')
  self.bootouts+=1;self.armed=False
 def absent(self,r):
  if self.armed:raise c.Stop('GUARD_PRESENT')
 def cas(self,r):pass
 def bootstrap(self,r):pass
 def completed(self,r,expected):
  if self.new(r)!=expected:raise c.Stop('COMPLETED_OWNER_CHANGED')
  return expected
 def new(self,r):return {'pid':1000}
class Control(unittest.TestCase):
 def test_sealed_candidates_exact_and_plists_minimal(self):self.assertTrue(c.validate_plan(P))
 def test_handoff_rejects_running_daily_or_missing_api_coordination(self):
  for key in ('legitimate_daily_producer_complete','all_daily_descendants_absent','no_active_dependent_api_query','api_brief_new_connection_gap_coordinated','no_live_pdf_child','no_parallel_lifecycle_owner'):
   h=handoff();h[key]=False
   with self.subTest(key=key),self.assertRaises(c.Stop):c.require_handoff(P,h)
 def test_root_helper_only_fixed_debug_and_no_args(self):
  d=c.load(HERE/'ROOT_REQUEST_REVIEW_ONLY.json');raw=c.render_root_helper(P,d['identities'],d['operation_id'],d['expires_epoch'])
  self.assertEqual(raw,(HERE/'admin_arm_main_api_REVIEW_ONLY.sh').read_text());self.assertEqual(raw.count('/bin/launchctl debug '),2)
  for bad in ('sudo','kill ','bootout','bootstrap','disable','python','eval '):self.assertNotIn(bad,raw)
  self.assertEqual(subprocess.run(['/bin/sh','-n',str(HERE/'admin_arm_main_api_REVIEW_ONLY.sh')]).returncode,0)
 def test_generated_coordinator_guard_and_ack_shell_bytes(self):
  d=c.load(HERE/'ROOT_REQUEST_REVIEW_ONLY.json');raw=c.render_root_helper(P,d['identities'],d['operation_id'],d['expires_epoch'],{'pid':12345,'ps_sha256':'1'*64,'ready_sha256':'2'*64})
  self.assertIn('COORDINATOR_NOT_ALIVE',raw);self.assertIn('REQUEST_CHECKPOINT_DRIFT',raw)
  with tempfile.TemporaryDirectory() as t:
   script=Path(t)/'generated.sh';script.write_text(raw);self.assertEqual(subprocess.run(['/bin/sh','-n',str(script)]).returncode,0)
   target='/private/var/tmp/v4-r7-nextspawn-'+d['operation_id'];lines=[x.replace(target,t) for x in raw.splitlines() if x.startswith('printf ')];subprocess.run(['/bin/sh','-c','result=0\n'+'\n'.join(lines)],check=True)
   self.assertEqual((Path(t)/'main.rc').read_bytes(),b'0\n');self.assertEqual((Path(t)/'COMPLETE').read_bytes(),b'COMPLETE\n');self.assertEqual((Path(t)/'plan_sha256').read_text().strip(),c.sha(c.canonical(P)))
 def test_drain_preserves_accepted_child_and_one_term(self):
  with tempfile.TemporaryDirectory() as t:
   f=Fake();s={'phase':'ARMED','children':{}};r=c.Recipe(P,handoff(),f,s,Path(t)/'state.json');r.step('main');self.assertEqual(f.signals,1);r.step('main');self.assertEqual(s['phase'],'DRAINING');self.assertEqual(f.bootouts,0)
   f.alive=False;r.step('main');self.assertEqual(s['phase'],'DRAINING');self.assertEqual(f.bootouts,0)
   f.child_alive=False;r.step('main');self.assertEqual(s['phase'],'GUARD_CONFIRMED');r.step('main');self.assertEqual(f.bootouts,1)
   for _ in range(5):r.step('main')
   self.assertEqual(s['phase'],'DONE');self.assertEqual(f.signals,1)
 def test_unknown_term_intent_never_resignals(self):
  with tempfile.TemporaryDirectory() as t:
   f=Fake();r=c.Recipe(P,handoff(),f,{'phase':'TERM_INTENT','children':{}},Path(t)/'state.json')
   with self.assertRaises(c.Stop):r.step('main')
   self.assertEqual(f.signals,0);self.assertEqual(f.bootouts,0)
 def test_missing_guard_fail_closed(self):
  with tempfile.TemporaryDirectory() as t:
   f=Fake();f.alive=False;f.child_alive=False;f.armed=False;r=c.Recipe(P,handoff(),f,{'phase':'DRAINING','children':{}},Path(t)/'state.json')
   with self.assertRaises(c.Stop):r.step('main')
   self.assertEqual(f.bootouts,0)
 def test_unknown_bootstrap_never_retries(self):
  with tempfile.TemporaryDirectory() as t:
   f=Fake();r=c.Recipe(P,handoff(),f,{'phase':'BOOTSTRAP_INTENT','children':{}},Path(t)/'state.json')
   with self.assertRaises(c.Stop):r.step('main')
 def test_full_metadata_forward_inverse_cas_and_drift(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();p=root/'target.plist';p.write_bytes(b'before');p.chmod(0o640)
   # Set a real binary Darwin xattr on this owned file, then preserve every byte.
   fd=os.open(p,os.O_RDWR);md=c.metadata.snapshot_fd(fd);md['xattrs']['user.r7']={'base64':'AAH/','sha256':c.sha(b'\x00\x01\xff'),'bytes':3}
   c.metadata.apply_fd(fd,md);os.close(fd);before=root/'before';after=root/'after';before.write_bytes(b'before');after.write_bytes(b'after')
   row=dict(role='main',plist=str(p),before_file=str(before),after_file=str(after),before_sha256=c.sha(b'before'),after_sha256=c.sha(b'after'),plist_metadata=md)
   o=c.Live({'operations':[row]});o.absent=lambda r:None;o.cas('main');self.assertEqual(p.read_bytes(),b'after');self.assertEqual(c.metadata.snapshot(p),md);o.cas('main',reverse=True);self.assertEqual(p.read_bytes(),b'before');self.assertEqual(c.metadata.snapshot(p),md)
   p.chmod(0o600)
   with self.assertRaises(c.metadata.MetadataError):o.cas('main')
 def test_stage_template_cannot_execute(self):
  spec=importlib.util.spec_from_file_location('stage_r7',HERE/'stage_hourly_controller.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with self.assertRaises(m.Stop):m.scope(c.load(HERE/'STAGE_PLAN_TEMPLATE_R7.json'))
 def test_stage_binding_main_manifest_and_unchanged_r4_fixes(self):
  stage=P['releases'][2];d=c.load(Path(stage['candidate_app'])/'stage_center_tick_config.json');main=P['releases'][0]
  self.assertEqual(d['research_owner_binding'],{k:main[k] for k in ('app_root','release_id','manifest_sha256')});self.assertEqual(d['research_scheduler_ledger_root'],'/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher')
  base=c.load(stage['baseline_manifest']);old={x['path']:x['sha256'] for x in base['app_files']}
  for rel in ('stage_center/_runner_parts/slot_execution.py','stage_center/_runner_parts/row_evidence.py'):self.assertEqual(c.sha(c.read(Path(stage['candidate_app'])/rel)),old[rel])
 def test_exact_main_hook_join_then_pool_drain_under_tick_race(self):
  sys.path.insert(0,P['releases'][0]['candidate_app']);from v4.manager_workbench.supervisor import WorkbenchHook
  events=[];entered=threading.Event();release=threading.Event()
  hook=object.__new__(WorkbenchHook);hook.cancel=threading.Event()
  def tick():entered.set();release.wait();events.append('accepted_during_tick')
  hook.thread=threading.Thread(target=tick);hook.thread.start();entered.wait()
  class Service:
   def stop(self):events.append('pools_drained')
  hook.service=Service();stopper=threading.Thread(target=hook.stop);stopper.start();time.sleep(.03);self.assertEqual(events,[]);release.set();stopper.join(2);self.assertFalse(stopper.is_alive());self.assertEqual(events,['accepted_during_tick','pools_drained'])
 def test_exact_coordinator_queued_accepted_jobs_drain(self):
  sys.path.insert(0,P['releases'][0]['candidate_app']);from v4.manager_workbench import jobs
  from v4.manager_workbench.store import WorkbenchStore
  from v4.manager_workbench.contracts import RunContext,Phase,JobState
  with tempfile.TemporaryDirectory() as t,patch.object(jobs,'_graph_notify',lambda *a,**kw:None):
   store=WorkbenchStore(Path(t).resolve());q=jobs.JobCoordinator(store,workers=1);entered=threading.Event();release=threading.Event();done=[]
   def worker(j):entered.set();release.wait();done.append(j.job_id);return j.run_id,JobState.SUCCEEDED
   accepted=[]
   for n in range(2):accepted.append(q.submit(RunContext(target_date='20261028',phase=Phase.INTRADAY,cutoff='2026-10-28T17:00:00+08:00',trigger='MANUAL',rules_version='R7_TEST',scope_refs={'stage_run_id':str(n)}),worker))
   entered.wait();st=threading.Thread(target=q.stop);st.start();time.sleep(.03);self.assertTrue(st.is_alive());release.set();st.join(3);self.assertFalse(st.is_alive());self.assertEqual(set(done),{j.job_id for j in accepted});self.assertTrue(all(store.get_job(j.job_id).state==JobState.SUCCEEDED for j in accepted))
if __name__=='__main__':unittest.main(verbosity=2)
