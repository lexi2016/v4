"""Read-only source/parent/idle guard. It never stops a process or changes a claim."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from prepare_candidate import guard, PLIST
import plistlib


def main():
    scope,parent,_,_,_=guard()
    plist=plistlib.loads(PLIST.read_bytes())
    target=f"gui/{os.getuid()}/{plist['Label']}"
    status=subprocess.run(['launchctl','print',target],capture_output=True,text=True,check=True).stdout
    pid=int(re.search(r'^\s*pid = (\d+)\s*$',status,re.M).group(1))
    assert pid==scope['scheduler_pid_at_freeze'], 'SCHEDULER_PID_DRIFT_REQUIRES_READBACK'
    cwd=subprocess.run(['lsof','-a','-p',str(pid),'-d','cwd','-Fn'],capture_output=True,text=True,check=True).stdout
    assert 'n'+str(parent) in cwd.splitlines(), 'SCHEDULER_CWD_DRIFT'
    processes=subprocess.run(['ps','-axo','pid=,ppid='],capture_output=True,text=True,check=True).stdout
    children=[int(line.split()[0]) for line in processes.splitlines() if len(line.split())==2 and int(line.split()[1])==pid]
    assert not children, 'SCHEDULER_HAS_ACTIVE_CHILDREN:' + repr(children)
    sockets=subprocess.run(['lsof','-a','-p',str(pid),'-iTCP','-sTCP:ESTABLISHED','-Fn'],capture_output=True,text=True)
    assert sockets.returncode in (0,1)
    assert not sockets.stdout.strip(), 'SCHEDULER_HAS_ESTABLISHED_SOCKET'
    config=json.loads(Path(scope['config']).read_bytes())
    state=Path(config['state_root'])/'manager_workbench'
    busy=[]
    for file in (state/'attempts').glob('*.json'):
        job=json.loads(file.read_bytes())
        if job.get('state') in ('QUEUED','RUNNING'):
            busy.append(dict(job_id=job.get('job_id'),state=job['state']))
    assert not busy, 'WORKBENCH_ACTIVE_ATTEMPTS:' + repr(busy)
    ledger=Path(plist['EnvironmentVariables']['V35_DISPATCH_LEDGER_ROOT'])
    day=datetime.now(ZoneInfo('Asia/Hong_Kong')).strftime('%Y%m%d')
    checked=0
    for mode in ('live','backfill'):
        for file in (ledger/'claims'/mode/day).rglob('dispatch.claim.json'):
            claim=json.loads(file.read_bytes())
            receipt=ledger/'receipts'/mode/day/file.parent.name/(claim['run_id']+'.dispatch-receipt.json')
            assert receipt.is_file(), 'DISPATCH_CLAIM_WITHOUT_TERMINAL_RECEIPT:'+str(file)
            value=json.loads(receipt.read_bytes())
            assert value.get('run_id')==claim['run_id'] and value.get('finished_at'), 'DISPATCH_NOT_FINISHED'
            assert value.get('status') not in (None,'RUNNING','QUEUED','PENDING'), 'DISPATCH_NONTERMINAL'
            checked+=1
    guard()
    print(json.dumps(dict(state='PREACTIVATION_GUARD_PASS',pid=pid,cwd=str(parent),
        dispatcher_claims_checked=checked,active_workbench_attempts=0,active_children=0,
        established_sockets=0,read_only=True,
        limitation='Point-in-time guard; activate immediately after approval or rerun only at actual activation. No service action performed.'),indent=2))


if __name__=='__main__':main()
