"""Only R7 independent-review P2 recovery regression; owned temp/fake lifecycle."""
from pathlib import Path
import copy,json,sys,tempfile,time,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import main_api_controller as c
P=c.load(HERE/'PLAN_REVIEW_ONLY_R7.json')
def identity(pid,text):return dict(pid=pid,ps_sha256=c.sha(text.encode()),ps_text=text)
def handoff():
 now=time.time();ids={r:identity(P['expected_original_pids'][r],r+' original start command') for r in c.ROLES}
 return dict(operation_id='a'*32,root_ack_dir='/private/var/tmp/v4-r7-nextspawn-'+'a'*32,plan_sha256=c.sha(c.canonical(P)),legitimate_daily_producer_complete=True,all_daily_descendants_absent=True,no_active_dependent_api_query=True,api_brief_new_connection_gap_coordinated=True,expires_epoch=now+240,observed_epoch=now,data_pins=[{'path':'owned'}],data_stats=[{'path':'owned'}],pdf_admission_disabled_by_existing_time_window=True,no_live_pdf_child=True,no_parallel_lifecycle_owner=True,all_current_main_children_and_jobs_finished=True,identities=ids,role_observations={r:dict(disposition='ORIGINAL_UNTOUCHED',checkpoint_phase='WAITING_ROOT_ACK',current_identity=i) for r,i in ids.items()})
class Fake:
 def __init__(self,h):
  self.old=h['identities'];self.current=copy.deepcopy(self.old);self.guards={r:identity(1000+n,'/bin/sleep 604800') for n,r in enumerate(c.ROLES)};self.newids={r:identity(2000+n,r+' replacement start command') for n,r in enumerate(c.ROLES)};self.term_count={r:0 for r in c.ROLES};self.root_calls=0;self.events=[]
 def original(self,r,i):
  if i!=self.old[r] or self.current[r]!=i:raise c.Stop('ORIGINAL_DRIFT')
 def protection(self,h):pass
 def ack(self,h):self.events.append('ack')
 def pdf_boundary(self):pass
 def initial_main_idle(self,old):pass
 def descendants(self,pid):return {}
 def term(self,r,i):self.original(r,i);self.term_count[r]+=1;self.events.append('TERM_'+r);self.current[r]=self.guards[r]
 def identity(self,pid):return next((x for x in self.current.values() if x and x['pid']==pid),None)
 def service(self,r):return dict(loaded=self.current[r] is not None,pid=self.current[r]['pid'] if self.current[r] else None)
 def no_old_root_processes(self,r):pass
 def guard(self,r,old):
  if self.current[r]!=self.guards[r]:raise c.Stop('GUARD_DRIFT')
  return self.current[r]
 def bootout_guard(self,r,g,old):self.guard(r,old);self.current[r]=None
 def absent(self,r):
  if self.current[r] is not None:raise c.Stop('NOT_ABSENT')
 def cas(self,r):self.absent(r)
 def bootstrap(self,r):self.absent(r);self.current[r]=self.newids[r]
 def new(self,r):return self.current[r]
 def completed(self,r,expected):
  self.events.append('DONE_READBACK_'+r)
  if self.current[r]!=expected:raise c.Stop('COMPLETED_OWNER_CHANGED')
  return expected

def refresh(h,states,ops):
 result=copy.deepcopy(h);result['observed_epoch']=time.time();result['expires_epoch']=time.time()+240
 for r,s in states.items():
  phase=s['phase'];disposition='COMPLETED' if phase=='DONE' else ('ORIGINAL_UNTOUCHED' if phase in ('WAITING_ROOT_ACK','ARMED') else 'IN_PROGRESS')
  result['role_observations'][r]=dict(disposition=disposition,checkpoint_phase=phase,current_identity=ops.current[r])
 return result

def run_role(p,h,o,state,root,role):
 recipe=c.Recipe(p,h,o,state,c.checkpoint_path(root,role))
 for _ in range(20):
  if recipe.step(role):return
 raise AssertionError('FAKE_RECIPE_DID_NOT_FINISH')
class Recovery(unittest.TestCase):
 def test_interrupted_main_has_precreated_api_and_refresh_resumes_both_once(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();h=handoff();o=Fake(h);states=c.prepare_role_checkpoints(P,h,o,root)
   self.assertEqual({r:c.load(c.checkpoint_path(root,r))['phase'] for r in c.ROLES},{r:'WAITING_ROOT_ACK' for r in c.ROLES})
   recipe=c.Recipe(P,h,o,states['main'],c.checkpoint_path(root,'main'));recipe.step('main');recipe.step('main')
   self.assertEqual(states['main']['phase'],'DRAINING');self.assertTrue(c.checkpoint_path(root,'api').exists());self.assertEqual(c.load(c.checkpoint_path(root,'api'))['phase'],'WAITING_ROOT_ACK')
   fresh=refresh(h,states,o);self.assertTrue(c.require_handoff(P,fresh));restored=c.resume_role_checkpoints(P,fresh,o,root)
   for r in c.ROLES:run_role(P,fresh,o,restored[r],root,r)
   self.assertEqual(o.term_count,{'main':1,'api':1});self.assertEqual(o.root_calls,0);self.assertTrue(all(s['phase']=='DONE' for s in restored.values()))
 def test_completed_main_resume_readback_before_untouched_api_without_reterm(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();h=handoff();o=Fake(h);states=c.prepare_role_checkpoints(P,h,o,root);run_role(P,h,o,states['main'],root,'main');fresh=refresh(h,states,o)
   self.assertEqual(fresh['identities']['main'],h['identities']['main']);self.assertNotEqual(fresh['role_observations']['main']['current_identity'],h['identities']['main'])
   restored=c.resume_role_checkpoints(P,fresh,o,root)
   for r in c.ROLES:run_role(P,fresh,o,restored[r],root,r)
   self.assertLess(o.events.index('DONE_READBACK_main'),o.events.index('TERM_api'));self.assertEqual(o.term_count,{'main':1,'api':1});self.assertEqual(o.root_calls,0)
 def test_completed_owner_drift_prevents_api_and_never_signals_done(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();h=handoff();o=Fake(h);states=c.prepare_role_checkpoints(P,h,o,root);run_role(P,h,o,states['main'],root,'main');fresh=refresh(h,states,o);restored=c.resume_role_checkpoints(P,fresh,o,root);o.current['main']=identity(9876,'unexpected replacement')
   with self.assertRaises(c.Stop):
    for r in c.ROLES:run_role(P,fresh,o,restored[r],root,r)
   self.assertEqual(o.term_count,{'main':1,'api':0});self.assertEqual(o.root_calls,0)
 def test_missing_or_ambiguous_untouched_checkpoint_rejected_before_actions(self):
  for defect in ('missing','prior_intent','changed_original','wrong_disposition'):
   with self.subTest(defect=defect),tempfile.TemporaryDirectory() as t:
    root=Path(t).resolve();h=handoff();o=Fake(h);states=c.prepare_role_checkpoints(P,h,o,root)
    if defect=='missing':c.checkpoint_path(root,'api').unlink()
    elif defect=='prior_intent':states['api']['term_sent']=True;c.save(c.checkpoint_path(root,'api'),states['api'])
    elif defect=='changed_original':h['identities']['api']=identity(93643,'changed original command')
    else:h['role_observations']['api']['disposition']='COMPLETED'
    with self.assertRaises(c.Stop):c.resume_role_checkpoints(P,h,o,root)
    self.assertEqual(o.term_count,{'main':0,'api':0});self.assertEqual(o.root_calls,0)
 def test_cli_interrupt_during_main_and_same_operation_refresh_resume(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t).resolve();p=copy.deepcopy(P);p['releases']=[];lock=root/'owned.lock';lock.write_text('owned test lock');st=lock.stat();p['owner_guard']={'path':str(lock),'device':st.st_dev,'inode':st.st_ino};c.save(root/'PLAN_REVIEW_ONLY_R7.json',p)
   h=handoff();h['plan_sha256']=c.sha(c.canonical(p));o=Fake(h);original_identity=o.identity
   o.identity=lambda pid:identity(pid,'owned test coordinator') if pid==__import__('os').getpid() else original_identity(pid)
   hp=root/'handoff.json';c.save(hp,h);args=['controller','--execute-reviewed','--handoff',str(hp),'--handoff-sha256',c.sha(c.read(hp)),'--review',str(root/'review.json'),'--review-sha256','unused']
   path_exists=Path.exists;ack_complete=Path(h['root_ack_dir'])/'COMPLETE';step=c.Recipe.step;render_calls=[]
   def interrupted_step(recipe,role):
    result=step(recipe,role)
    if role=='main' and recipe.s['phase']=='DRAINING':raise KeyboardInterrupt('owned interruption after original Main TERM')
    return result
   def render(*a,**kw):
    self.assertTrue(all(c.checkpoint_path(root,r).exists() for r in c.ROLES));render_calls.append(1);return '# owned fake helper, never executed\n'
   with patch.object(c,'HERE',root),patch.object(c,'Live',lambda _:o),patch.object(c,'validate_plan',lambda _:True),patch.object(c,'verify_review',lambda *a:None),patch.object(c.time,'sleep',lambda _:None),patch.object(sys,'argv',args):
    with patch.object(c,'render_root_helper',render),patch.object(Path,'exists',lambda self:True if self==ack_complete else path_exists(self)),patch.object(c.Recipe,'step',interrupted_step):
     with self.assertRaises(KeyboardInterrupt):c.cli()
    states={r:c.load(c.checkpoint_path(root,r)) for r in c.ROLES};self.assertEqual(states['api']['phase'],'WAITING_ROOT_ACK');fresh=refresh(h,states,o);c.save(hp,fresh);args[args.index('--handoff-sha256')+1]=c.sha(c.read(hp));args.append('--resume')
    with patch.object(c,'render_root_helper',side_effect=AssertionError('ROOT_HELPER_MUST_NOT_REPEAT')):c.cli()
   self.assertEqual(o.term_count,{'main':1,'api':1});self.assertEqual(render_calls,[1]);self.assertEqual(o.root_calls,0);self.assertTrue(all(c.load(c.checkpoint_path(root,r))['phase']=='DONE' for r in c.ROLES))
 def test_done_exact_after_plist_metadata_and_new_identity_revalidation(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve()/'after.plist';p.write_bytes(b'after');p.chmod(0o640);md=c.metadata.snapshot(p);row=dict(role='main',plist=str(p),after_sha256=c.sha(b'after'),plist_metadata=md);o=c.Live({'operations':[row]});expected=identity(123,'replacement start command');o.new=lambda r:expected
   self.assertEqual(o.completed('main',expected),expected)
   for wrong in (identity(124,'replacement start command'),identity(123,'changed start or command')):
    o.new=lambda r:wrong
    with self.assertRaises(c.Stop):o.completed('main',expected)
   o.new=lambda r:expected;p.chmod(0o600)
   with self.assertRaises(c.metadata.MetadataError):o.completed('main',expected)
   p.chmod(0o640);p.write_bytes(b'drift')
   with self.assertRaises(c.Stop):o.completed('main',expected)
 def test_explicit_observation_required_and_original_history_immutable(self):
  h=handoff();self.assertTrue(c.require_handoff(P,h));h.pop('role_observations')
  with self.assertRaises(c.Stop):c.require_handoff(P,h)
if __name__=='__main__':unittest.main(verbosity=2)
