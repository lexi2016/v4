from pathlib import Path
import copy,json,os,plistlib,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import api_only_controller as c
P=c.load(HERE/'PLAN.json')
class Identity(unittest.TestCase):
 def test_exact_api_identity_bindings_and_effective_env_frontend_identity(self):
  self.assertTrue(c.scope(P));results=[]
  code="import os,json; from apps.api.v35_api.runtime_graph_router import _frontend_build_identity; print(json.dumps({'effective_id':os.environ.get('V35_RELEASE_ID'),'effective_sha':os.environ.get('V35_RELEASE_MANIFEST_SHA256'),'frontend':_frontend_build_identity()}))"
  for name in ('before','after'):
   d=plistlib.loads(c.read(HERE/('api.'+name+'.plist')));args=d['ProgramArguments'];tokens=[]
   for item in args[1:]:
    if '=' not in item:break
    tokens.append(item)
   env={**os.environ,**d['EnvironmentVariables'],'PYTHONDONTWRITEBYTECODE':'1'}
   out=subprocess.run(['/usr/bin/env',*tokens,sys.executable,'-B','-c',code],env=env,cwd=d['WorkingDirectory'],capture_output=True,text=True,check=True);results.append(json.loads(out.stdout))
  self.assertEqual(results[0]['effective_id'],'mac-panel-r5-rebound-20261028-r1-api');self.assertEqual(results[0]['frontend'],{'status':'CANNOT_CONFIRM','reason':'API_RELEASE_IDENTITY_UNBOUND'})
  after=results[1];self.assertEqual(after['effective_id'],P['releases'][0]['release_id']);self.assertEqual(after['effective_sha'],P['releases'][0]['manifest_sha256']);self.assertEqual(after['frontend']['status'],'VERIFIED')
  for key,value in P['frontend_expected'].items():self.assertEqual(after['frontend'][key],value)
  c.save(HERE/'EFFECTIVE_ENV_TEST_RESULT.json',{'status':'PASS','before':results[0],'after':after,'scope':'Actual/usr/bin/env inlineprecedence and installed frontend identity function; isolated process only, no APIserver/lifecycle/datawrites'})
 def test_api_only_helper_one_debug_and_ack_bytes(self):
  h={'operation_id':'a'*32,'root_ack_dir':'/private/var/tmp/v4-api-id-r3-'+'a'*32,'expires_epoch':int(time.time()+240)};owner={'pid':12345,'ps_sha256':'1'*64};raw=c.root_helper(P,h,owner,'2'*64)
  self.assertEqual(raw.count('/bin/launchctl debug '),1);self.assertIn('debug gui/501/com.lexi.v35.api-only',raw)
  for forbidden in ('gui/501/com.lexi.v35.scheduler','kill ','bootout','bootstrap','disable','sudo','python','eval '):self.assertNotIn(forbidden,raw)
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'helper.sh';p.write_text(raw);subprocess.run(['/bin/sh','-n',str(p)],check=True);lines=[line.replace(h['root_ack_dir'],t) for line in raw.splitlines() if line.startswith('printf ')];subprocess.run(['/bin/sh','-c','result=0\n'+'\n'.join(lines)],check=True);self.assertEqual((Path(t)/'api.rc').read_bytes(),b'0\n');self.assertEqual((Path(t)/'COMPLETE').read_bytes(),b'COMPLETE\n')
 def test_main_lifecycle_and_other_api_pid_forbidden(self):
  ops=c.ApiLive(P)
  with self.assertRaises(c.Stop):ops.cmd(['/bin/launchctl','bootout','gui/501/com.lexi.v35.scheduler'])
  with self.assertRaises(c.Stop):ops.term('main',P['protected_main_identity'])
  with self.assertRaises(c.Stop):ops.term('api',{'pid':123})
 def test_single_api_recipe_uses_only_api_term_and_base_drain(self):
  class Fake:
   def __init__(self):self.alive=True;self.terms=0;self.bootouts=0;self.guard_i={'pid':777,'ps_text':'/bin/sleep604800'};self.new_i={'pid':888}
   def protection(self,h):pass
   def ack(self,h):pass
   def original(self,r,i):assert r=='api' and i==P['expected_api_identity']
   def descendants(self,p):return {}
   def term(self,r,i):self.terms+=1;self.alive=False
   def identity(self,p):return P['expected_api_identity'] if self.alive and p==67002 else None
   def service(self,r):return {'loaded':True,'pid':67002 if self.alive else 777}
   def guard(self,r,old):return self.guard_i
   def no_old_root_processes(self,r):pass
   def bootout_guard(self,r,g,old):assert not self.alive;self.bootouts+=1
   def absent(self,r):pass
   def cas(self,r):assert r=='api'
   def bootstrap(self,r):assert r=='api'
   def new(self,r):return self.new_i
   def completed(self,r,i):assert i==self.new_i
  h={'identities':{'api':P['expected_api_identity']}};o=Fake();state={'phase':'ARMED','children':{}}
  with tempfile.TemporaryDirectory() as t,patch.object(c,'handoff',lambda *a:True):
   r=c.ApiRecipe(P,h,o,state,Path(t)/'checkpoint.json')
   for _ in range(12):
    if r.step('api'):break
   self.assertEqual(state['phase'],'DONE');self.assertEqual(o.terms,1);self.assertEqual(o.bootouts,1)
if __name__=='__main__':unittest.main(verbosity=2)
