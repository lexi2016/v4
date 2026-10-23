import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import activation_driver as d
import control_prepare as c


class FakeOps:
    def __init__(self, *, exit=True, respawn=False, child=False, invalid_claim=False, bootstrap_fail=False):
        self.events=[];self.pid=10;self.enabled='enabled';self.exit=exit;self.respawn=respawn;self.child=child;self.invalid_claim=invalid_claim;self.bootstrap_fail=bootstrap_fail
    def override(self):return self.enabled
    def set_override(self,v):self.events.append(('override',v));self.enabled=v
    def registration(self,*a,**kw):return self.pid
    def pid_alive(self,p):return self.pid==p
    def claims(self,p):
        if self.invalid_claim:raise d.Stop('invalid receipt')
        return [{'run_id':'actual'}]
    def terminal(self,claims):self.events.append(('terminal',claims))
    def manager_terminal(self,p):self.events.append(('manager_terminal',p))
    def pdf_clear(self,p):
        if self.child:raise d.Stop('healthy child STOP')
    def term_and_wait(self,p,seconds,*,send):
        self.events.append(('term' if send else 'wait',p))
        if self.exit:self.pid=11 if self.respawn else None
        return self.exit
    def bootout_nonrunning(self,expected):
        d.require(self.pid is None,'bootout forbidden while running');self.events.append(('bootout',None))
    def install_pointer(self,raw):self.events.append(('pointer',raw));c.PLIST.write_bytes(raw)
    def bootstrap(self,expected):
        self.events.append(('bootstrap',expected))
        if self.bootstrap_fail:raise d.Stop('bootstrap failed')
        self.pid=20;return self.pid
    def verify_protected(self,refs):pass
    def verify_inventory(self):pass
    def verify_published(self):pass
    def install_release(self):self.events.append(('install_release',None))
    def runtime(self,path):return {'verified':True}


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=c.OWNER);self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        self.old=root/'old.plist';self.new=root/'new.plist';self.live=root/'live.plist'
        self.old.write_bytes(plistlib.dumps({'identity':'old'}));self.new.write_bytes(plistlib.dumps({'identity':'new'}));self.live.write_bytes(self.old.read_bytes())
        self.patch=patch.object(c,'PLIST',self.live);self.patch.start();self.addCleanup(self.patch.stop)
        self.cap={'drain_wait_seconds':1,'expected_start_pid':10,'protected_bindings':[]};self.packet={'original_plist':str(self.old),'candidate_plist':str(self.new)}
    def driver(self,ops):
        state={'phase':'PREFLIGHT'};return d.Driver(self.cap,self.packet,ops,state,lambda data:None)
    def test_activation_transition_order(self):
        ops=FakeOps();state=self.driver(ops).execute('activate');self.assertEqual(state['phase'],'ACTIVATED')
        names=[x[0] for x in ops.events]
        self.assertLess(names.index('term'),names.index('bootout'));self.assertLess(names.index('terminal'),names.index('bootout'));self.assertLess(names.index('bootout'),names.index('pointer'));self.assertEqual(ops.enabled,'enabled')
        self.assertEqual([x for x in ops.events if x[0]=='term'],[('term',10)])
    def test_pending_drain_preserves_disabled_process_no_bootout(self):
        ops=FakeOps(exit=False);driver=self.driver(ops)
        with self.assertRaises(d.Pending):driver.execute('activate')
        self.assertEqual(driver.state['phase'],'DRAIN_PENDING');self.assertEqual(ops.enabled,'disabled');self.assertEqual(ops.pid,10)
        self.assertFalse(any(x[0] in {'bootout','pointer','bootstrap'} for x in ops.events))
    def test_resume_does_not_signal_twice(self):
        ops=FakeOps(exit=False);driver=self.driver(ops)
        with self.assertRaises(d.Pending):driver.execute('activate')
        ops.exit=True;driver.execute('activate',resume=True)
        self.assertEqual(len([x for x in ops.events if x[0]=='term']),1);self.assertEqual(len([x for x in ops.events if x[0]=='wait']),1)
    def test_unexpected_respawn_never_bootout_or_pointer(self):
        ops=FakeOps(respawn=True);driver=self.driver(ops)
        with self.assertRaisesRegex(d.Stop,'respawn'):driver.execute('activate')
        self.assertEqual(ops.pid,11);self.assertEqual(ops.enabled,'enabled');self.assertFalse(any(x[0] in {'bootout','pointer'} for x in ops.events))
    def test_healthy_child_rejected_before_any_mutation(self):
        ops=FakeOps(child=True)
        with self.assertRaisesRegex(d.Stop,'healthy child'):self.driver(ops).execute('activate')
        self.assertEqual(ops.events,[])
    def test_bad_original_receipt_rejected_before_any_mutation(self):
        ops=FakeOps(invalid_claim=True)
        with self.assertRaisesRegex(d.Stop,'invalid receipt'):self.driver(ops).execute('activate')
        self.assertEqual(ops.events,[])
    def test_rollback_live_candidate_uses_same_protocol(self):
        self.live.write_bytes(self.new.read_bytes());ops=FakeOps();driver=self.driver(ops);result=driver.execute('rollback')
        self.assertEqual(result['phase'],'ROLLED_BACK');self.assertEqual(self.live.read_bytes(),self.old.read_bytes())
        self.assertIn(('term',10),ops.events);self.assertIn(('bootout',None),ops.events);self.assertEqual(ops.enabled,'enabled')
    def test_pending_rollback_never_kills_candidate(self):
        self.live.write_bytes(self.new.read_bytes());ops=FakeOps(exit=False);driver=self.driver(ops)
        with self.assertRaises(d.Pending):driver.execute('rollback')
        self.assertEqual(ops.pid,10);self.assertEqual(ops.enabled,'disabled');self.assertEqual(self.live.read_bytes(),self.new.read_bytes())
    def test_wrong_original_override_rejected_before_publication(self):
        ops=FakeOps();ops.enabled='disabled'
        with self.assertRaisesRegex(d.Stop,'override changed'):self.driver(ops).execute('activate')
        self.assertEqual(ops.events,[])
    def test_active_cycle_outside_scope_rejected(self):
        ops=object.__new__(d.RealOps);ops.p={'ledger_root':self.temp.name}
        p=Path(self.temp.name)/'claim.json';p.write_text(json.dumps({'schema_version':'v3_5.dispatch_claim.v1','mode':'LIVE','business_date':'20261023','slot':'1800','run_id':'r'}))
        with patch.object(c,'claims_observation',return_value=[{'path':'claim.json','pid':10,'state':'ACTIVE_OR_UNCONFIRMED'}]):
            with self.assertRaisesRegex(d.Stop,'outside reviewed'):ops.claims(10)
    def test_active_pdf_enqueuing_workload_rejected(self):
        ops=object.__new__(d.RealOps);ops.p={'ledger_root':self.temp.name}
        p=Path(self.temp.name)/'claim.json';p.write_text(json.dumps({'schema_version':'v3_5.workload_claim.v1','mode':'LIVE','business_date':'20261023','slot':'1730','run_id':'r','workload_id':'hourly_research'}))
        with patch.object(c,'claims_observation',return_value=[{'path':'claim.json','pid':10,'state':'ACTIVE_OR_UNCONFIRMED'}]):
            with self.assertRaisesRegex(d.Stop,'enqueue PDF'):ops.claims(10)
    def test_kqueue_closes_and_only_positive_exact_pid_term(self):
        class Queue:
            closed=False
            def control(self,*args):return []
            def close(self):self.closed=True
        q=Queue();ops=object.__new__(d.RealOps);ops.pid_tokens={10:'same process'};ops.pid_alive=lambda pid:True;ops.run=lambda command:'same process'
        with patch.object(d.select,'kqueue',return_value=q),patch.object(d.os,'kill') as kill:
            self.assertFalse(ops.term_and_wait(10,1,send=True));kill.assert_called_once_with(10,d.signal.SIGTERM)
        self.assertTrue(q.closed)
    def test_kqueue_closes_when_pid_identity_drift_blocks_signal(self):
        class Queue:
            closed=False
            def control(self,*args):return []
            def close(self):self.closed=True
        q=Queue();ops=object.__new__(d.RealOps);ops.pid_tokens={10:'original'};ops.pid_alive=lambda pid:True;ops.run=lambda command:'new process'
        with patch.object(d.select,'kqueue',return_value=q),patch.object(d.os,'kill') as kill:
            with self.assertRaisesRegex(d.Stop,'identity changed'):ops.term_and_wait(10,1,send=True)
            kill.assert_not_called()
        self.assertTrue(q.closed)
    def test_wrong_initial_pid_never_signals(self):
        ops=FakeOps();self.cap['expected_start_pid']=999
        with self.assertRaisesRegex(d.Stop,'PID differs'):self.driver(ops).execute('activate')
        self.assertFalse(any(x[0] in {'term','bootout','pointer'} for x in ops.events))
    def test_missing_external_capsule_pin_rejected(self):
        with self.assertRaisesRegex(d.Stop,'external capsule'):d.load_capsule(self.old,'','activate')
    def test_template_rejected(self):
        p=Path(self.temp.name)/'capsule.json';p.write_text(json.dumps({'status':'TEMPLATE_NOT_AUTHORIZATION'}))
        with self.assertRaisesRegex(d.Stop,'not authorization'):d.load_capsule(p,c.sha(p),'activate')
    def test_only_atomic_restore_bytes_and_mode(self):
        self.live.chmod(0o600);d.atomic_replace(self.live,self.new.read_bytes());self.assertEqual(self.live.read_bytes(),self.new.read_bytes());self.assertEqual(self.live.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()
