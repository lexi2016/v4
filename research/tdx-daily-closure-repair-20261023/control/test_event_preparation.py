"""AST/pure mocks only: never imports the executable wrapper or touches live state."""
import ast,hashlib,json,re,tempfile,unittest
from pathlib import Path
W=Path(__file__).resolve().parent
OLD=Path('/Users/lexi/Desktop/学习/agents调试/V4_PRESELECTION_PROVENANCE_REPAIR_20261023/live/owner/wait-r3/event_wait_continuation.py')
NEW=W/'event_wait_continuation.py'
class Guard:
    @staticmethod
    def require(ok,message):
        if not ok:raise RuntimeError(message)

def function(tree,name,values):
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(NEW),'exec'),values)
    return values[name]

class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.old=ast.parse(OLD.read_text());cls.new=ast.parse(NEW.read_text());compile(cls.new,str(NEW),'exec')

    def test_original_guard_functions_ast_identical(self):
        for name in ['identity','children','pdf','claims','admissible']:
            a=next(n for n in self.old.body if isinstance(n,ast.FunctionDef) and n.name==name);b=next(n for n in self.new.body if isinstance(n,ast.FunctionDef) and n.name==name)
            with self.subTest(name=name):self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False))

    def test_new_active_cycles_remain_wait_conditions(self):
        fn=function(self.new,'admissible',{})
        def state(slot,workload):return {'children':[],'pdf':{'retryable':0,'processing':0},'active_claims':[{'path':'claims/live/20261023/'+slot+'/dispatch.claim.json','workload_id':workload}]}
        self.assertFalse(fn(state('2140','daily_materialize')));self.assertFalse(fn(state('2200','hourly_research')));self.assertFalse(fn(state('1800','preselection_pools')))
        self.assertTrue(fn(state('1730','preselection_pools')));self.assertFalse(fn(state('1730','daily_materialize')))

    def test_exact_dynamic_claim_and_receipt_subscription(self):
        watched=[];calls=[];values={'Path':Path,'driver':Guard,'ledger':Path('/owned/ledger'),'watched':watched,'watch_path':calls.append};fn=function(self.new,'subscribe_claim_paths',values)
        row={'path':'claims/live/20261023/2140/dispatch.claim.json','receipt_path':'receipts/live/20261023/2140/run.dispatch-receipt.json'};fn([row]);self.assertEqual(set(watched),{Path('/owned/ledger')/row[k] for k in row}|{(Path('/owned/ledger')/row[k]).parent for k in row});fn([row]);self.assertEqual(len(watched),4)
        with self.assertRaises(RuntimeError):fn([{'path':'../escape','receipt_path':row['receipt_path']}])

    def test_initial_and_new_slot_parent_subscription(self):
        with tempfile.TemporaryDirectory(dir=W) as folder:
            root=Path(folder);day=root/'claims/live/20261023';(day/'2140').mkdir(parents=True);watched=[];calls=[]
            fn=function(self.new,'subscribe_slot_parents',{'claim_days':[day],'re':re,'watched':watched,'watch_path':calls.append})
            fn();self.assertIn(day/'2140',watched);(day/'2225').mkdir();fn();self.assertIn(day/'2225',watched)
            (day/'linked').symlink_to(day/'2140');(day/'not-a-slot').mkdir();fn();self.assertNotIn(day/'linked',watched);self.assertNotIn(day/'not-a-slot',watched)

    def test_single_driver_call_outside_event_loop(self):
        calls=[n for n in ast.walk(self.new) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Popen'];self.assertEqual(len(calls),1)
        loops=[n for n in ast.walk(self.new) if isinstance(n,ast.While)];self.assertEqual(len(loops),1)
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Popen' for n in ast.walk(loops[0])))
        self.assertIn("STATE['driver_invocations']=1",NEW.read_text());self.assertIn("not (W/'activation.started').exists()",NEW.read_text())

    def test_bounded_event_only_wait_and_no_business_actions(self):
        source=NEW.read_text();self.assertIn('REMAINING=600',source);self.assertIn('queue.control(None,64,min(60,remaining))',source)
        for token in ['time.sleep(',"['launchctl'",'os.kill(','.tick(',"'baseline-oracle'"]:
            self.assertNotIn(token,source)
        loop=next(n for n in ast.walk(self.new) if isinstance(n,ast.While));first=loop.body[:5];self.assertTrue(any('queue.control' in ast.unparse(n) for n in first))

    def test_source_authority_drift_stops(self):
        values={'authority_pins':{'/owned/a':'a','/owned/b':'b'},'sha':lambda p:{'/owned/a':'a','/owned/b':'b'}[p],'driver':Guard};fn=function(self.new,'source_authority_identity',values);fn();values['sha']=lambda p:'changed'
        with self.assertRaisesRegex(RuntimeError,'source/config/authority drift'):fn()

    def test_capsule_rebind_is_operation_id_only(self):
        data=json.loads((W/'capsule-rebind.json').read_bytes());self.assertEqual(set(data['delta']),{'operation_id'});self.assertEqual(data['sha256'],'ecda86a7d4abbb6326066742c8c5cca7378f703d7d815d848e7a7533e79c4e46')

if __name__=='__main__':unittest.main(verbosity=2)
