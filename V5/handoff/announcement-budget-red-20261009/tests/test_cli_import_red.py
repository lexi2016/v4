"""Mac offline RED: direct ops CLI import bootstrap without inherited app path."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Do not import the earlier harness: it inserts pinned into sys.path and would
# mask this regression. Verify source bytes as data, then run a clean child.
for manifest in ('SOURCE_MANIFEST.json', 'CANDIDATE_MANIFEST.json'):
    for entry in json.loads((ROOT/manifest).read_text())['entries']:
        path=ROOT/entry['candidate_path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise RuntimeError('SOURCE_SHA_MISMATCH: '+entry['candidate_path'])

CHILD = r'''
import sys, runpy
from pathlib import Path
def deny(event, args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo',
                 'socket.bind','subprocess.Popen','os.system'}:
        raise RuntimeError('OFFLINE_CLI_NETWORK_OR_PROCESS_FORBIDDEN')
sys.addaudithook(deny)
script=Path(sys.argv[1]).resolve()
sys.argv=sys.argv[1:]
# -I removed inherited paths; a direct script normally adds only its ops dir.
sys.path.insert(0,str(script.parent))
runpy.run_path(str(script),run_name='__main__')
'''


class StandaloneCliBootstrapRed(unittest.TestCase):
    def test_cli_reaches_local_argument_validation_without_pythonpath(self):
        with tempfile.TemporaryDirectory(prefix='announcement-cli-red-') as tmp:
            root=Path(tmp)
            app=root/'app'
            (app/'ops').mkdir(parents=True)
            (app/'infrastructure').mkdir()
            script=app/'ops/manager_announcement_body_batch.py'
            shutil.copy2(ROOT/'candidate/ops/manager_announcement_body_batch.py',script)
            for name in ('__init__.py','owned_io.py'):
                shutil.copy2(ROOT/'pinned/infrastructure'/name,app/'infrastructure'/name)
            fixture=root/'catalog.json'
            fixture.write_text('{}\n')
            env={key:value for key,value in os.environ.items()
                 if key not in {'PYTHONPATH','PYTHONHOME'}}
            # Invalid date must stop before imports()/catalog access/transport.
            # The child denies every network and further process launch anyway.
            result=subprocess.run([sys.executable,'-B','-I','-c',CHILD,str(script),
                '--catalog-read',str(fixture),'--material-root',str(root/'materials'),
                '--output-root',str(root/'output'),'--target-date','INVALID',
                '--publication-date','2026-10-08'],cwd=root,env=env,
                capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertIn('BODY_BATCH_TARGET_DATE_INVALID',result.stderr,
                'standalone CLI must locate app infrastructure before entering local validation')
            self.assertNotIn('ModuleNotFoundError',result.stderr)
            self.assertNotIn('OFFLINE_CLI_NETWORK_OR_PROCESS_FORBIDDEN',result.stderr)
            self.assertFalse((root/'materials').exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
