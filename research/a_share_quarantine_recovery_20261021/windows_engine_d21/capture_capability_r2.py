"""One registered metadata retry, using the existing bounded PTY mDNS route."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import time
import traceback


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--start-receipt', required=True, type=Path)
    args = parser.parse_args()
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    if args.start_receipt.resolve() != Path(contract['start_receipt_path']).resolve():
        raise SystemExit('STOP_NONCANONICAL_START_RECEIPT_PATH')
    start = json.loads(args.start_receipt.read_text())
    if (start.get('event_type') != 'RUN_STARTED'
            or start.get('execution_id') != contract['execution_id']
            or start.get('contract_sha256') != sha(contract_bytes)
            or not re.fullmatch('[0-9a-f]{64}', start.get('event_sha256', ''))):
        raise SystemExit('STOP_INVALID_START_RECEIPT')
    script_bytes = Path(__file__).with_name('capability.ps1').read_bytes()
    if (sha(script_bytes) != contract['powershell_sha256']
            or sha(Path(__file__).read_bytes()) != contract['code_sha256']):
        raise SystemExit('STOP_SOURCE_DRIFT')
    out = Path(contract['output_path'])
    out.mkdir(parents=True, exist_ok=False)
    overall_deadline = time.monotonic() + 45
    receipt = dict(execution_id=contract['execution_id'],
                   started_at=datetime.now(timezone.utc).isoformat(),
                   contract_sha256=sha(contract_bytes),
                   powershell_sha256=sha(script_bytes),
                   start_event_sha256=start['event_sha256'],
                   sdk_import_count=0, init_connect_count=0, formula_call_count=0,
                   remote_stage_reached=False, exit_code=None, timed_out=False,
                   exception=None, research_only=True, production_allowed=False,
                   buy_gate_updated=False, orders_sent=False)
    stage = 'JOURNAL_STARTED_BEFORE_DNS'
    save(out / 'JOURNAL.json', dict(stage=stage, **receipt))
    try:
        stage = 'CURRENT_MDNS_PTY'
        dns_command = ['dns-sd', '-G', 'v4', 'huang1992.local']
        save(out / 'dns.command.json', dns_command)
        master, slave = pty.openpty()
        resolver = None
        captured = bytearray()
        deadline = min(time.monotonic() + 5, overall_deadline)
        try:
            resolver = subprocess.Popen(dns_command, stdout=slave, stderr=slave, close_fds=True)
            os.close(slave)
            slave = None
            while time.monotonic() < deadline:
                if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    captured.extend(chunk)
                    if re.search(rb'Add\s+\d+\s+\d+\s+huang1992\.local\.?\s+[0-9.]+', captured, re.I):
                        break
                if resolver.poll() is not None:
                    break
        finally:
            if slave is not None:
                os.close(slave)
            if resolver is not None:
                if resolver.poll() is None:
                    resolver.terminate()  # Only our short resolver.
                try:
                    resolver.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    resolver.kill()  # Only our short resolver, never an existing service.
                    resolver.wait(timeout=3)
            os.close(master)
            (out / 'dns.stdout').write_bytes(captured)
            (out / 'dns.stderr').write_text('stderr combined in PTY transcript\n')
            save(out / 'dns.exit.json', dict(exit_code=resolver.returncode if resolver else None,
                 deadline_reached=time.monotonic() >= deadline))
        addresses = re.findall(r'Add\s+\d+\s+\d+\s+huang1992\.local\.?\s+([0-9.]+)',
                               captured.decode('utf-8', errors='replace'), re.I)
        addresses = sorted(set(a for a in addresses if ipaddress.ip_address(a).version == 4))
        if len(addresses) > 1:
            raise RuntimeError('STOP_AMBIGUOUS_CURRENT_MDNS')
        if addresses:
            host, address_source = addresses[0], 'CURRENT_MDNS'
        else:
            fallback_bytes = Path(contract['fallback_receipt_path']).read_bytes()
            if sha(fallback_bytes) != contract['fallback_receipt_sha256']:
                raise RuntimeError('STOP_FALLBACK_RECEIPT_DRIFT')
            fallback = json.loads(fallback_bytes)
            if not (fallback['returncode'] == 0 and fallback['strict_host_key_checking'] is True
                    and fallback['hostkeyalias'] == '169.254.203.121'):
                raise RuntimeError('STOP_UNTRUSTED_FALLBACK')
            host = fallback['hostname']
            if ipaddress.ip_address(host).version != 4:
                raise RuntimeError('STOP_INVALID_FALLBACK_IP')
            address_source = 'RECENT_SAME_HOST_SUCCESS_RECEIPT'
        save(out / 'DNS.json', dict(selected_ipv4=host, address_source=address_source,
             fallback_receipt_sha256=contract['fallback_receipt_sha256'], scan=False))
        encoded = base64.b64encode(script_bytes.decode().encode('utf-16-le')).decode()
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=5', '-o', 'HostName=' + host,
                   '-o', 'HostKeyAlias=169.254.203.121', '-o',
                   'UserKnownHostsFile=/Users/lexi/.ssh/known_hosts', 'windows-wifi',
                   'powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
        save(out / 'command.json', command)
        stage = 'SSH_METADATA_CAPTURE'
        receipt['remote_stage_reached'] = True
        save(out / 'JOURNAL.json', dict(stage=stage, **receipt))
        try:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, 45)
            result = subprocess.run(command, capture_output=True, timeout=remaining)
            stdout, stderr = result.stdout, result.stderr
            receipt['exit_code'] = result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or b'', exc.stderr or b''
            receipt['timed_out'] = True
            raise
        finally:
            (out / 'capture.stdout').write_bytes(locals().get('stdout', b''))
            (out / 'capture.stderr').write_bytes(locals().get('stderr', b''))
        if receipt['exit_code'] != 0:
            raise RuntimeError('STOP_REMOTE_METADATA_ERROR')
        stage = 'PARSE_CAPTURE'
        payload = json.loads(stdout.decode('utf-8-sig'))
        save(out / 'CAPABILITY.json', payload)
        receipt['decision'] = 'METADATA_CAPTURED_NOT_SDK_EXECUTED'
    except BaseException as exc:
        receipt['exception'] = dict(type=type(exc).__name__, message=str(exc), stage=stage)
        receipt['decision'] = 'STOP_CAPTURE_FAILURE_NO_RETRY'
        (out / 'exception.txt').write_text(traceback.format_exc())
    finally:
        receipt['ended_at'] = datetime.now(timezone.utc).isoformat()
        receipt['terminal_stage'] = stage
        receipt['artifacts'] = {p.name: sha(p.read_bytes()) for p in out.iterdir()
                                if p.is_file() and p.name != 'receipt.json'}
        save(out / 'receipt.json', receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)
    return 1 if receipt['exception'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
