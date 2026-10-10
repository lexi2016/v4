"""Real worker guard: only the platform UTC alias, never a zoneinfo directory."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from v5_shadow.a_preselection import _guard, WorkerBoundaryViolation
root=pathlib.Path(sys.argv[2]);alias=root/'utc-link'
lane=dict(kind='v192',input_root=str(root),paths={},files={})
select=_guard([lane]);select(lane)
out={}
for name in ['/usr/share/zoneinfo/UTC','/usr/share/zoneinfo/America/New_York',str(alias),'/etc/passwd']:
 try:
  with open(name,'rb') as stream:out[name]=stream.read(4).decode('ascii')
 except WorkerBoundaryViolation as error:out[name]=str(error)
print(json.dumps(out))
'''

class PlatformUtcGuardTests(unittest.TestCase):
    def test_trusted_utc_works_but_other_zone_and_caller_symlink_stay_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();inputs=root/'inputs';inputs.mkdir()
            (inputs/'utc-link').symlink_to('/usr/share/zoneinfo/UTC')
            p=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(root/'cache'),
                '-c',SCRIPT,str(BASE/'src'),str(inputs)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            import json
            out=json.loads(p.stdout)
            self.assertEqual(out['/usr/share/zoneinfo/UTC'],'TZif')
            for path in ['/usr/share/zoneinfo/America/New_York',str(inputs/'utc-link'),'/etc/passwd']:
                self.assertEqual(out[path],'A_INPUT_PATH_NOT_DECLARED',path)
