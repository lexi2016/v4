"""Pure mocks/AST only. Do not import executable wrapper or inspect live processes."""
import ast,datetime,json,re,sys,types,unittest
from pathlib import Path
W=Path(__file__).resolve().parent;OLD=W.parent/'event-wait-r2/event_wait_continuation.py';NEW=W/'event_wait_continuation.py'
class Stop(Exception):pass
class Driver:
    @staticmethod
    def require(ok,message):
        if not ok:raise Stop(message)
def load(name,values):
    tree=ast.parse(NEW.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);exec(compile(ast.Module(body=[node],type_ignores=[]),str(NEW),'exec'),values);return values[name]
class Tests(unittest.TestCase):
    def setUp(self):
        self.row={'path':'claims/live/20261023/2140/dispatch.claim.json','pid':42,'run_id':'exact-run','workload_id':None,'receipt_path':'receipts/live/20261023/2140/exact-run.dispatch-receipt.json','state':'ACTIVE_OR_UNCONFIRMED','sha256':'a'*64};self.state={};self.logged=[]
    def values(self):return {'datetime':datetime,'STATE':self.state,'log':lambda event,**kw:self.logged.append((event,kw)),'diagnostic_process_identity':lambda pid:{'pid':pid,'status':'PARTIAL_IDENTITY'}}
    def test_exact_offending_identity_fields(self):
        fn=load('log_other_owner_stop',self.values());fn(self.row);d=self.state['other_live_owner_stop_diagnostic'];self.assertEqual({k:d[k] for k in self.row if k!='state'},{k:v for k,v in self.row.items() if k!='state'});self.assertEqual(d['receipt_state'],self.row['state']);self.assertEqual(self.logged[0][0],'OTHER_LIVE_OWNER_STOP_DIAGNOSTIC')
    def test_identity_read_failure_does_not_mask_original_stop(self):
        v=self.values();v['diagnostic_process_identity']=lambda pid:(_ for _ in ()).throw(OSError('SECRET_DO_NOT_LOG'));load('log_other_owner_stop',v);fn=load('claims',dict(v,c=types.SimpleNamespace(claims_observation=lambda root,pid:[self.row]),ledger=Path('/owned'),oldpid=61106,ops=types.SimpleNamespace(pid_alive=lambda pid:True),driver=Driver))
        with self.assertRaisesRegex(Stop,'^other healthy live owner claim$'):fn()
        self.assertEqual(self.state['other_live_owner_stop_diagnostic']['process_identity'],{'status':'CANNOT_CONFIRM','error_type':'OSError'});self.assertNotIn('SECRET_DO_NOT_LOG',json.dumps(self.state))
    def test_logging_failure_does_not_mask_original_stop(self):
        v=self.values();v['log']=lambda *a,**kw:(_ for _ in ()).throw(OSError('log unavailable'));load('log_other_owner_stop',v);calls=[];fn=load('claims',dict(v,c=types.SimpleNamespace(claims_observation=lambda root,pid:[self.row]),ledger=Path('/owned'),oldpid=61106,ops=types.SimpleNamespace(pid_alive=lambda pid:calls.append(pid) or True),driver=Driver))
        with self.assertRaisesRegex(Stop,'^other healthy live owner claim$'):fn()
        self.assertEqual(calls,[42])
    def test_missing_pid_keeps_original_stop_and_cannot_confirm(self):
        row=dict(self.row,pid=None);seen=[];v=self.values();load('log_other_owner_stop',v);fn=load('claims',dict(v,c=types.SimpleNamespace(claims_observation=lambda root,pid:[row]),ledger=Path('/owned'),oldpid=61106,ops=types.SimpleNamespace(pid_alive=lambda pid:seen.append(pid) or True),driver=Driver))
        with self.assertRaisesRegex(Stop,'other healthy live owner claim'):fn()
        self.assertEqual(seen,[]);self.assertIsNone(self.state['other_live_owner_stop_diagnostic']['pid'])
    def process_fn(self,stdout,rc=0):
        calls=[];fake=types.SimpleNamespace(run=lambda cmd,**kw:calls.append((cmd,kw)) or types.SimpleNamespace(returncode=rc,stdout=stdout,stderr='SECRET_STDERR'))
        return load('diagnostic_process_identity',{'subprocess':fake,'re':re,'sys':types.SimpleNamespace(executable='/safe/python'),'Path':Path,'packet':{'runtime_root':'/owned/runtime'}}),calls
    def test_process_start_and_only_allowlisted_argv_prefix(self):
        fn,calls=self.process_fn('42 7 Fri Oct 23 22:54:07 2026 /safe/python -B -S -m ops.a_share_daily_sync --token SECRET_VALUE\n');d=fn(42);self.assertEqual(d['process_start'],'Fri Oct 23 22:54:07 2026');self.assertEqual(d['argv'],['/safe/python','-B','-S','-m','ops.a_share_daily_sync']);self.assertNotIn('SECRET',json.dumps(d));self.assertNotIn('env',calls[0][1]);self.assertEqual(calls[0][0],['ps','-p','42','-o','pid=,ppid=,lstart=,args='])
    def test_unlisted_or_unavailable_identity_remains_cannot_confirm(self):
        for stdout,rc in [('42 7 Fri Oct 23 22:54:07 2026 /unlisted/secret-executable SECRET\n',0),('',1),('bad-format SECRET\n',0)]:
            fn,_=self.process_fn(stdout,rc);d=fn(42);self.assertNotIn('SECRET',json.dumps(d));self.assertTrue(d.get('status')=='CANNOT_CONFIRM' or d.get('argv_status')=='CANNOT_CONFIRM_NOT_ALLOWLISTED')
    def test_entire_nondiagnostic_code_ast_identical(self):
        old=ast.parse(OLD.read_text());new=ast.parse(NEW.read_text());new.body=[n for n in new.body if not(isinstance(n,ast.FunctionDef) and n.name in {'diagnostic_process_identity','log_other_owner_stop'})]
        fn=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='claims');branch=next(n for n in fn.body if isinstance(n,ast.For)).body[0].orelse[0];self.assertIsInstance(branch,ast.If)
        original=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='claims');oldbranch=next(n for n in original.body if isinstance(n,ast.For)).body[0].orelse[0]
        predicate=branch.body[0].value;self.assertEqual(ast.dump(predicate,include_attributes=False),ast.dump(oldbranch.body[0].value.args[0],include_attributes=False));branch.body=oldbranch.body
        self.assertEqual(ast.dump(old,include_attributes=False),ast.dump(new,include_attributes=False));compile(ast.parse(NEW.read_text()),str(NEW),'exec')
if __name__=='__main__':unittest.main(verbosity=2)
