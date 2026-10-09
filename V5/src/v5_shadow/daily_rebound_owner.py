"""Call pinned separate rebound checkout; never copy its business algorithms."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import subprocess
from v5_shadow.digests import canonical_bytes, MAX_JSON_BYTES

PIN='2d8e38ec61792b3e75581f96318e9c284f72b7ba'


def verify_checkout(root):
    root=Path(root).resolve(strict=True)
    if not (root/'V5/src/v5_shadow/rebound_daily.py').is_file():raise ValueError('REBOUND_DAILY_CHECKOUT_MISSING')
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)
    if git('rev-parse','HEAD').decode().strip()!=PIN:raise ValueError('REBOUND_DAILY_CHECKOUT_PIN')
    # Include ignored files: an injected module must not shadow a pinned module.
    if git('status','--porcelain','--untracked-files=all','--ignored','--','V5/src','V5/vendor','V5/contracts'):
        raise ValueError('REBOUND_DAILY_CHECKOUT_DIRTY')
    return root


def run_rebound_owner(request,ledger_run_id):
    root=verify_checkout(request['owner_checkout'])
    worker=Path(__file__).resolve()
    child=subprocess.run([sys.executable,'-I','-B',str(worker),'--worker'],
        input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180,cwd=root)
    if child.returncode:raise ValueError('REBOUND_DAILY_OWNER_FAILED:'+child.stderr.decode(errors='replace')[-2000:])
    if len(child.stdout)>MAX_JSON_BYTES:raise ValueError('REBOUND_DAILY_RESPONSE_SIZE')
    value=json.loads(child.stdout)
    verify_checkout(root)
    from v5_shadow.daily_owner_adapters import rebound_receipt
    return rebound_receipt(request,ledger_run_id,value['result'],value['artifact'])


def worker(request):
    root=verify_checkout(request['owner_checkout'])
    # Current helper loaded v5_shadow for JSON contracts; switch the namespace
    # before importing the separate original owner and all its dependencies.
    for name in list(sys.modules):
        if name=='v5_shadow' or name.startswith('v5_shadow.'):del sys.modules[name]
    sys.path.insert(0,str(root/'V5/src'))
    from v5_shadow.rebound_daily import run_rebound_daily
    from v5_shadow.rebound_observation import read_rebound_observation
    result=run_rebound_daily(request['request'],request['output_root'])
    artifact=read_rebound_observation(request['output_root'],result['reference'])
    return dict(result=result,artifact=artifact)


if __name__=='__main__':
    if sys.argv[1:]!=['--worker']:raise SystemExit('worker invocation required')
    raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
    if len(raw)>MAX_JSON_BYTES:raise ValueError('REBOUND_DAILY_REQUEST_SIZE')
    sys.stdout.buffer.write(canonical_bytes(worker(json.loads(raw))))
