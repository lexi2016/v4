import io,json,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from test_contracts import manifest,request
from v5_shadow.cli import main

class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'.v5-shadow-root').write_text('v5.shadow-root.v1\n')
        self.value=dict(schema_version='v5.composition.v1',revision=1,modules={'rebound_shadow':manifest()},bindings={'rebound_shadow':dict(authority_root=None,shadow_root=str(self.root),calendar_sha256='d'*64,source_capsule_sha256='e'*64,input_snapshot_sha256=None)})
        self.config=self.root/'composition.json';self.config.write_text(json.dumps(self.value))
    def call(self,args):
        out=io.StringIO()
        with redirect_stdout(out):code=main(args)
        return code,json.loads(out.getvalue())
    def test_check_is_not_business_success(self):
        code,value=self.call(['check','--composition',str(self.config)])
        self.assertEqual(code,0);self.assertEqual(value['status'],'CONFIGURATION_VALID')
        self.assertFalse(value['business_verified']);self.assertFalse(value['natural_verified'])
    def test_health_does_not_claim_expected_version_loaded(self):
        code,value=self.call(['health','--composition',str(self.config)])
        self.assertNotEqual(code,0);self.assertNotEqual(value['health']['identity_status'],'MATCH')
    def test_unknown_arguments_are_json_failure(self):
        code,value=self.call(['make-trades'])
        self.assertEqual(code,3);self.assertEqual(value['status'],'REJECTED')
    def test_missing_run_is_json_failure(self):
        code,value=self.call(['read-result','--output-root',str(self.root),'--target-date','20261008','--run-id','a'*32])
        self.assertEqual(code,3);self.assertEqual(value['status'],'REJECTED')
    def test_output_outside_binding_refused(self):
        req=self.root/'request.json';req.write_text(json.dumps(request()))
        code,value=self.call(['run-shadow','--composition',str(self.config),'--request',str(req),'--output-root',str(self.root/'elsewhere')])
        self.assertEqual(code,3)
if __name__=='__main__':unittest.main()
