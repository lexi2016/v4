"""Preparation and read-only oracles only. No service/claim/lock mutations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

OWNER = Path(__file__).resolve().parent
E = OWNER.parents[1]
PUBLISHER = Path('/Users/lexi/Desktop/学习/agents调试/V4_STAGE_INPUT_RECOVERY_20261023/writer/publication.py')
PUBLISHER_SHA = '661df7124e70af580be2804a230f9c1f2277c32e8f7f64e9957a8a2b2a32860a'
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')
PLIST_SHA = '6849321a75d23d90604f70491ad97088cc03ffe9824d1e3b11b3b86c0cd20345'
LABEL = 'com.lexi.v35.scheduler'
TERMINAL = {'SUCCEEDED', 'FAILED', 'DUPLICATE_WORKLOAD_SKIPPED', 'NO_DUE_WORKLOADS', 'NON_TRADING_DAY_CADENCE', 'NON_TRADING_DAY', 'NO_ELIGIBLE_WORKLOADS'}
SAFETY = ('production_allowed', 'buy_gate_updated', 'orders_sent')
IDENTITY = ('run_id', 'business_date', 'scheduled_date', 'target_date', 'slot', 'mode')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    path = Path(path)
    if not path.is_relative_to(OWNER):
        raise ValueError('owner output only')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def helper():
    if sha(PUBLISHER) != PUBLISHER_SHA:
        raise ValueError('prior accepted publisher drift')
    return runpy.run_path(str(PUBLISHER))


def receipt_state(claim, receipt):
    """FAILED is terminal too; successful workload claims persist after mixed failure."""
    if not isinstance(receipt, dict):
        return 'ACTIVE_OR_UNCONFIRMED'
    body = {k: v for k, v in receipt.items() if k != 'ledger_sha256'}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if receipt.get('ledger_sha256') != digest:
        return 'INVALID_RECEIPT_STOP'
    if any(receipt.get(k) != claim.get(k) for k in IDENTITY):
        return 'IDENTITY_MISMATCH_STOP'
    if any(receipt.get(k) is not False for k in SAFETY):
        return 'UNSAFE_RECEIPT_STOP'
    if receipt.get('status') not in TERMINAL or not receipt.get('finished_at'):
        return 'NONTERMINAL_RECEIPT_STOP'
    if claim.get('workload_id'):
        rows = [r for r in receipt.get('workload_results', []) if r.get('workload_id') == claim['workload_id']]
        if len(rows) != 1 or rows[0].get('status') not in {'SUCCEEDED', 'ALREADY_EXISTS', 'FAILED'}:
            return 'WORKLOAD_RESULT_UNCONFIRMED_STOP'
        if any(rows[0].get(k) is not False for k in SAFETY):
            return 'UNSAFE_WORKLOAD_STOP'
    return 'TERMINAL_MATCH'


def claims_observation(root, pid):
    rows = []
    for kind, pattern in [('claims', '*/*/dispatch.claim.json'), ('workloads', '*/*/*.workload-claim.json')]:
        for p in sorted((root / kind / 'live').glob(pattern)):
            try:
                if p.is_symlink():
                    raise ValueError('symlink claim')
                claim = json.loads(p.read_bytes())
                # Own PID across all dates plus today's owners; historical other owners are unrelated.
                today = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
                if claim.get('pid') != pid and claim.get('business_date') != today:
                    continue
                relative = Path('receipts/live') / str(claim['business_date']) / str(claim['slot']) / (str(claim['run_id']) + '.dispatch-receipt.json')
                r = root / relative
                if '..' in relative.parts or r.resolve() != r:
                    raise ValueError('receipt path not exact')
                receipt = json.loads(r.read_bytes()) if r.is_file() else None
                state = receipt_state(claim, receipt)
                rows.append({'path': str(p.relative_to(root)), 'sha256': sha(p), 'pid': claim.get('pid'), 'current_daemon': claim.get('pid') == pid, 'run_id': claim.get('run_id'), 'workload_id': claim.get('workload_id'), 'receipt_path': str(relative), 'receipt_sha256': sha(r) if r.is_file() else None, 'state': state})
            except Exception as exc:
                rows.append({'path': str(p.relative_to(root)), 'state': 'UNREADABLE_STOP', 'error': type(exc).__name__})
    return rows


def descendants(pid, process_rows):
    found = {pid}
    while True:
        more = {p for p, pp in process_rows if pp in found} - found
        if not more:
            return sorted(found - {pid})
        found |= more


def inspect_live():
    if sha(PLIST) != PLIST_SHA:
        raise ValueError('baseline plist drift')
    config = plistlib.loads(PLIST.read_bytes())
    readback = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{LABEL}'], capture_output=True, text=True, timeout=5, check=True).stdout
    match = re.search(r'(?m)^\s*pid = (\d+)$', readback)
    if not match:
        raise ValueError('no live daemon pid')
    pid = int(match.group(1))
    table = subprocess.run(['ps', '-axo', 'pid=,ppid='], capture_output=True, text=True, timeout=5, check=True).stdout
    children = descendants(pid, [tuple(map(int, row.split())) for row in table.splitlines()])
    claims = claims_observation(Path(config['EnvironmentVariables']['V35_DISPATCH_LEDGER_ROOT']), pid)
    return {'pid': pid, 'children': children, 'claims': claims,
            'observed_dispatch_idle': not children and all(x['state'] == 'TERMINAL_MATCH' for x in claims),
            'atomic_idle_proven': False, 'safe_to_activate': False,
            'reason': 'NO_GLOBAL_COOPERATIVE_RELEASE_LOCK; in-process pre-dispatch and manager hook invisible to dispatch claims; observation/admission race remains'}


def runtime_oracle(plist_path, expected_sources):
    config = plistlib.loads(Path(plist_path).read_bytes())
    env = dict(os.environ, **config['EnvironmentVariables'])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    root = Path(env['V35_APP_ROOT'])
    python = Path(env['V35_RUNTIME_ROOT']) / 'venvs/v3.5-mac/bin/python'
    site = Path(env['V35_RUNTIME_ROOT']) / 'venvs/v3.5-mac/lib/python3.14/site-packages'
    env['PYTHONPATH'] = ':'.join([str(root), str(site), env.get('PYTHONPATH', '')])
    code = '''import hashlib,importlib,json,os,pathlib,sys
root=pathlib.Path(os.environ['V35_APP_ROOT']).resolve()
sys.path.insert(0,str(root))
from ops import run_v35_macos_scheduler_daemon as daemon
out={'oracle':'daemon._release_identity([])','release_id':daemon._release_identity([]),'python':sys.executable,'modules':{},'native_six_file_validator_claimed':False}
for rel in json.loads(sys.argv[1]):
 module=importlib.import_module(rel[:-3].replace('/','.'))
 path=pathlib.Path(module.__file__).resolve()
 assert path == root/rel,(rel,str(path))
 out['modules'][rel]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
print(json.dumps(out,sort_keys=True))'''
    run = subprocess.run([str(python), '-B', '-c', code, json.dumps(sorted(expected_sources))], env=env, cwd=root, capture_output=True, text=True, timeout=45)
    if run.returncode:
        return {'exit_code': run.returncode, 'stderr': run.stderr, 'stdout': run.stdout, 'verified': False}
    out = json.loads(run.stdout.strip().splitlines()[-1])
    if out['release_id'] != env['V35_RELEASE_ID']:
        raise ValueError('release identity mismatch')
    for rel, want in expected_sources.items():
        if out['modules'][rel]['sha256'] != want:
            raise ValueError('actual runtime import SHA mismatch: ' + rel)
    return {'exit_code': 0, 'verified': True, 'output': out, 'stderr': run.stderr}


def verify_candidate_packet(packet_path):
    """Reviewed candidate only; no access to changing Writer output before follow-up."""
    packet = json.loads(Path(packet_path).read_bytes())
    if packet.get('independent_review') != 'PASS' or not packet.get('candidate_inventory'):
        raise ValueError('reviewed packet required')
    h = helper()
    if h['inventory'](Path(packet['candidate_app'])) != packet['candidate_inventory']:
        raise ValueError('candidate full inventory drift')
    for key in ('release_manifest', 'candidate_plist', 'original_plist'):
        if sha(packet[key]) != packet[key + '_sha256']:
            raise ValueError(key + ' drift')
    if packet['original_plist_sha256'] != PLIST_SHA:
        raise ValueError('wrong baseline plist')
    manifest = json.loads(Path(packet['release_manifest']).read_bytes())
    entries = manifest['application_inventory']['entries']
    manifest_inventory = {x['path']: {k:v for k,v in x.items() if k != 'path'} for x in entries}
    if manifest_inventory != packet['candidate_inventory'] or manifest['application_inventory']['entry_count'] != len(entries):
        raise ValueError('manifest inventory differs from reviewed candidate')
    if manifest['candidate'] != {'app_root': packet['target_app'], 'release_id': packet['release_id']}:
        raise ValueError('manifest release identity mismatch')
    aggregate = hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
    if aggregate != manifest['application_inventory']['aggregate_sha256']:
        raise ValueError('manifest aggregate drift')
    want = h['candidate_plist'](Path(packet['original_plist']).read_bytes(), packet['baseline_app'], packet['target_app'], packet['release_id'], packet['target_manifest'], packet['release_manifest_sha256'])
    if plistlib.loads(want) != plistlib.loads(Path(packet['candidate_plist']).read_bytes()):
        raise ValueError('candidate plist has unrelated environment/args/schedule edits')
    baseline = h['inventory'](Path(packet['baseline_app']))
    candidate = packet['candidate_inventory']
    changed = sorted(k for k in baseline.keys() | candidate.keys() if baseline.get(k) != candidate.get(k))
    if changed != sorted(packet['changed_paths']) or not set(changed) <= set(json.loads((E/'ledger/scope.json').read_bytes())['runtime_source_allowlist']):
        raise ValueError('unreviewed source/dependency delta')
    return {'verified': True, 'changed_paths': changed, 'safe_to_activate': False, 'atomic_idle_proven': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'baseline-oracle', 'verify-packet'])
    parser.add_argument('--packet', type=Path)
    args = parser.parse_args()
    if args.action == 'inspect':
        result = inspect_live()
    elif args.action == 'baseline-oracle':
        binding = json.loads((E/'baseline/runtime-source-binding.json').read_bytes())
        sources = {x['path']: x['runtime_before_sha256'] for x in binding['source_before'] if x['runtime_before_sha256']}
        result = runtime_oracle(PLIST, sources)
    else:
        result = verify_candidate_packet(args.packet)
    dump(OWNER/(args.action + '.json'), result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['claims','output']}, ensure_ascii=False))
