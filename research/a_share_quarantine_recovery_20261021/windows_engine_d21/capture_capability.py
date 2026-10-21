"""Execute the frozen metadata-only Windows capture after registrar START.

No remote interpreter, SDK, DLL, formula, UI, group or account API is invoked.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--start-receipt', required=True, type=Path)
    args = parser.parse_args()
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    start = json.loads(args.start_receipt.read_text())
    if (start.get('event_type') != 'RUN_STARTED'
            or start.get('execution_id') != contract['execution_id']
            or start.get('contract_sha256') != sha(contract_bytes)
            or not re.fullmatch('[0-9a-f]{64}', start.get('event_sha256', ''))):
        raise SystemExit('STOP_INVALID_START_RECEIPT')
    script_path = Path(__file__).with_name('capability.ps1')
    script_bytes = script_path.read_bytes()
    if sha(script_bytes) != contract['powershell_sha256']:
        raise SystemExit('STOP_SCRIPT_DRIFT')
    out = Path(contract['output_path'])
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    dns = subprocess.run(['dscacheutil', '-q', 'host', '-a', 'name', 'huang1992.local'],
                         capture_output=True, timeout=10)
    (out / 'dns.stdout').write_bytes(dns.stdout)
    (out / 'dns.stderr').write_bytes(dns.stderr)
    addresses = re.findall(r'^ip_address:\s*(\S+)', dns.stdout.decode(), re.M)
    addresses = sorted(set(a for a in addresses if ipaddress.ip_address(a).version == 4))
    if dns.returncode != 0 or len(addresses) != 1:
        raise SystemExit('STOP_DNS_MISSING_OR_AMBIGUOUS')
    encoded = base64.b64encode(script_bytes.decode('utf-8').encode('utf-16-le')).decode()
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=5', '-o', 'HostName=' + addresses[0],
               '-o', 'HostKeyAlias=169.254.203.121', '-o',
               'UserKnownHostsFile=/Users/lexi/.ssh/known_hosts', 'windows-wifi',
               'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    (out / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    timed_out = False
    try:
        result = subprocess.run(command, capture_output=True, timeout=45)
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        # subprocess.run terminates only its own local ssh child, never TdxW.
        stdout, stderr, exit_code = exc.stdout or b'', exc.stderr or b'', None
        timed_out = True
    (out / 'capture.stdout').write_bytes(stdout)
    (out / 'capture.stderr').write_bytes(stderr)
    receipt = dict(execution_id=contract['execution_id'], started_at=started,
                   ended_at=datetime.now(timezone.utc).isoformat(), exit_code=exit_code,
                   timed_out=timed_out, contract_sha256=sha(contract_bytes),
                   powershell_sha256=sha(script_bytes), stdout_sha256=sha(stdout),
                   stderr_sha256=sha(stderr), start_event_sha256=start['event_sha256'],
                   sdk_import_count=0, init_connect_count=0, formula_call_count=0,
                   research_only=True, production_allowed=False,
                   buy_gate_updated=False, orders_sent=False)
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if timed_out or exit_code != 0:
        raise SystemExit('STOP_CAPTURE_TIMEOUT_OR_ERROR')
    payload = json.loads(stdout.decode('utf-8-sig'))
    (out / 'CAPABILITY.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
