#!/usr/bin/env python3
"""Run the declared R2 tests using supplied read-side source in a temporary app.

This is NOT a full r9 runtime nor a Mac/API/UI acceptance. The original R1
business suite is not substituted or represented as having been rerun here.
"""
from pathlib import Path
import argparse
from datetime import datetime,timezone
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-dir',required=True,type=Path)
    a=p.parse_args();out=a.evidence_dir
    if not out.is_absolute() or '..' in out.parts or out.resolve()!=out or out.exists():
        p.error('Evidence directory must be a new, exact absolute path.')
    if out.is_relative_to(ROOT) or ROOT.is_relative_to(out):
        p.error('Evidence must be outside this package.')
    out.mkdir(parents=True,exist_ok=False)
    started=datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix='v4-r2-offline-') as temp:
        app=Path(temp)/'app'
        shutil.copytree(ROOT/'reference_only',app)
        shutil.copytree(ROOT/'after/api',app,dirs_exist_ok=True)
        code=('import sys; sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); '
              'import pytest; raise SystemExit(pytest.main(["-q","-p","no:cacheprovider",'
              'sys.argv[2],"--junitxml="+sys.argv[3]]))')
        command=[sys.executable,'-I','-c',code,str(app),str(ROOT/'tests'),str(out/'junit.xml')]
        r=subprocess.run(command,cwd=temp,capture_output=True,timeout=120)
    (out/'stdout.log').write_bytes(r.stdout);(out/'stderr.log').write_bytes(r.stderr)
    receipt=dict(scope='R2_BINDING_AND_READONLY_TOOL_SYNTHETIC_TESTS_ONLY',
        command=command,started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),
        exit_code=r.returncode,python=sys.version,
        stdout_sha256=hashlib.sha256(r.stdout).hexdigest(),stderr_sha256=hashlib.sha256(r.stderr).hexdigest(),
        full_r9_runtime=False,real_data=False,mac_api_ui_acceptance=False,independent_reviewer=False)
    (out/'command_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(r.stdout.decode(errors='replace'));print(r.stderr.decode(errors='replace'),file=sys.stderr)
    return r.returncode

if __name__=='__main__':raise SystemExit(main())
