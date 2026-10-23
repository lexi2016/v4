#!/usr/bin/env python3
"""Exact capsule-bound producer activation. PREPARE artifact; never run unbound."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

import control_prepare as c

BASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
OLD_MANIFEST_SHA = '9cf6171a2347db117b4442f1742fc8be0bd39a713fa2e7bab8679c99b9c86631'
SAFETY = {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


class Stop(RuntimeError):
    pass


class Pending(Stop):
    pass


def require(ok, message):
    if not ok:
        raise Stop(message)


def atomic_replace(path, payload):
    """Prior accepted same-directory fsync/replace recipe; no external caller paths."""
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.codex-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_capsule(path, expected_sha, action):
    require(re.fullmatch('[0-9a-f]{64}', expected_sha or ''), 'exact external capsule SHA required')
    require(c.sha(path) == expected_sha, 'capsule drift')
    cap = json.loads(Path(path).read_bytes())
    require(cap.get('status') == 'PARENT_REVIEWED_ACTION_CAPSULE', 'template is not authorization')
    require(cap.get('label') == c.LABEL and cap.get('safety') == SAFETY, 'surface/safety mismatch')
    require(cap.get('recover_failed_1800') is False and cap.get('recovery_command') is None, '1800 recovery forbidden: invalid PIT source')
    require(cap.get('successful_work_rerun_allowed') is False and cap.get('healthy_task_cancellation_allowed') is False, 'healthy work boundary')
    require(cap.get('original_launchd_override') == 'enabled', 'only exact original explicit enabled override supported')
    require(cap.get('disabled_keepalive_semantics_review_accepted') is True, 'disable/KeepAlive inference not reviewed')
    require(cap.get('activate_current_v35_scheduler' if action == 'activate' else 'rollback_current_v35_scheduler') is True, 'exact action not authorized')
    require(cap.get('pdf_readonly_sha256') == c.sha(c.OWNER/'pdf_readonly.py'), 'PDF read-only oracle code drift')
    require(isinstance(cap.get('expected_start_pid'),int) and not isinstance(cap['expected_start_pid'],bool) and cap['expected_start_pid']>0, 'exact initial PID required')
    require(cap.get('driver_sha256') == c.sha(__file__) and cap.get('control_prepare_sha256') == c.sha(c.__file__), 'control code drift')
    require(1 <= cap.get('drain_wait_seconds', 0) <= 60, 'bounded event wait must be1..60 seconds')
    require(re.fullmatch('[A-Za-z0-9_-]{1,100}', cap.get('operation_id', '')), 'invalid operation id')
    for key in ('independent_source_review', 'independent_control_review'):
        ref = cap[key]
        require(ref.get('verdict') == 'PASS' and c.sha(ref['path']) == ref['sha256'], key + ' pin/verdict')
        review = json.loads(Path(ref['path']).read_bytes())
        require(review.get('verdict') == 'PASS' or review.get('status') in {'PASS', 'REVIEWED/PASS'}, key + ' receipt not PASS')
    require(c.sha(cap['prepared_packet_path']) == cap['prepared_packet_sha256'], 'packet drift')
    c.verify_candidate_packet(cap['prepared_packet_path'])
    packet=json.loads(Path(cap['prepared_packet_path']).read_bytes())
    require(json.loads(Path(packet['release_manifest']).read_bytes()).get('financial_safety')==SAFETY,'candidate manifest safety mismatch')
    require(cap.get('source_binding_sha256') == c.sha(c.BINDING), 'approved source binding drift')
    binding=c.binding_config()
    require(packet['source_sha256'] == binding['source_sha256'], 'exact approved source pins required')
    for rel,want in packet['source_sha256'].items():
        require(packet['candidate_inventory'].get(rel,{}).get('sha256') == want, 'source SHA not bound to inventory')
    require(cap['protected_bindings'][0]['path'] == str(c.BASELINE_E/'baseline/protected-successes.json'), 'original protected baseline required first')
    require(len(cap['protected_bindings']) >= 2, 'verified natural update supplement required')
    return cap, packet


class RealOps:
    def __init__(self, packet):
        self.p = packet; self.h = c.helper(); self.target = f'gui/{os.getuid()}/{c.LABEL}'; self.pid_tokens = {}

    def run(self, command):
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=True).stdout

    def override(self):
        text = self.run(['launchctl', 'print-disabled', f'gui/{os.getuid()}'])
        match = re.search(r'"' + re.escape(c.LABEL) + r'"\s*=>\s*(enabled|disabled)\b', text)
        require(match is not None, 'explicit override unavailable')
        return match.group(1)

    def set_override(self, value):
        require(value in {'enabled', 'disabled'}, 'invalid override')
        self.run(['launchctl', 'enable' if value == 'enabled' else 'disable', self.target])
        require(self.override() == value, 'override readback mismatch')

    def registration(self, expected, *, allow_absent=False, require_process=True):
        text = self.h['service_readback'](c.LABEL)
        if text is None:
            require(allow_absent, 'service absent'); return None
        args = re.search(r'(?ms)^\s*arguments = \{\n(.*?)^\s*\}', text)
        actual = [s.strip() for s in args.group(1).splitlines() if s.strip()] if args else []
        require(actual == expected['ProgramArguments'], 'registered arguments mismatch')
        require(re.search(r'(?m)^\s*working directory = ' + re.escape(expected['WorkingDirectory']) + r'$', text), 'registered cwd mismatch')
        for key, value in expected['EnvironmentVariables'].items():
            require(re.search(r'(?m)^\s*' + re.escape(key) + ' => ' + re.escape(value) + '$', text), 'registered environment mismatch: ' + key)
        match = re.search(r'(?m)^\s*pid = (\d+)$', text)
        pid = int(match.group(1)) if match else None
        if require_process:
            require(pid is not None, 'registered process missing')
            command = self.run(['ps', '-p', str(pid), '-o', 'lstart=,command='])
            if pid in self.pid_tokens:
                require(self.pid_tokens[pid] == command, 'PID process identity changed/reused')
            else:
                self.pid_tokens[pid] = command
            require('-m ops.run_v35_macos_scheduler_daemon' in command, 'process has not reached expected daemon')
            cwd = self.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'])
            require('n' + expected['WorkingDirectory'] in cwd.splitlines(), 'actual PID cwd mismatch')
        return pid

    def pid_alive(self, pid):
        run = subprocess.run(['ps', '-p', str(pid), '-o', 'pid='], capture_output=True, text=True, timeout=5)
        return run.returncode == 0 and run.stdout.strip() == str(pid)

    def claims(self, pid):
        root = Path(self.p['ledger_root'])
        rows = c.claims_observation(root, pid); raw = []
        for row in rows:
            if row.get('pid') == pid:
                require(row['state'] in {'TERMINAL_MATCH', 'ACTIVE_OR_UNCONFIRMED'}, 'invalid current owner claim receipt')
                claim=json.loads((root/row['path']).read_bytes())
                require(claim.get('schema_version') in {'v3_5.dispatch_claim.v1','v3_5.workload_claim.v1'} and claim.get('mode')=='LIVE','current claim schema/mode invalid')
                if row['state'] == 'ACTIVE_OR_UNCONFIRMED':
                    require(claim['business_date']=='20261023' and claim['slot']=='1730', 'active cycle outside reviewed no-PDF-enqueue scope')
                    require(claim.get('workload_id') in {None,'preselection_pools','research_panel_runtime_evidence'}, 'active producer could enqueue PDF work; natural completion required')
                raw.append(claim)
            elif row['state'] != 'TERMINAL_MATCH':
                require(row.get('pid') and not self.pid_alive(row['pid']), 'unconfirmed other live owner')
        return raw

    def terminal(self, claims):
        root = Path(self.p['ledger_root'])
        for claim in claims:
            path = root/'receipts/live'/claim['business_date']/claim['slot']/(claim['run_id']+'.dispatch-receipt.json')
            require(path.is_file(), 'drained claim missing genuine terminal receipt')
            require(c.receipt_state(claim, json.loads(path.read_bytes())) == 'TERMINAL_MATCH', 'drained claim receipt invalid')

    def pdf_clear(self, pid):
        # Reject ALL descendants before signalling; a new empty-queue tick is harmless,
        # but an observed child is allowed to finish naturally, never cancelled.
        table = self.run(['ps', '-axo', 'pid=,ppid='])
        require(not c.descendants(pid, [tuple(map(int,x.split())) for x in table.splitlines()]), 'healthy descendant STOP')
        python = Path(self.p['runtime_root'])/'venvs/v3.5-mac/bin/python'
        self.run([str(python), '-B', str(c.OWNER/'pdf_readonly.py')])
        report = json.loads((c.OWNER/'pdf_readonly.json').read_bytes())
        require(report['stable_during_read'] and report['verified_retryable_task_count'] == 0 and report['processing_document_count'] == 0, 'healthy/pending PDF work STOP')

    def manager_terminal(self, pid):
        root = Path(self.p['manager_store_root'])
        for p in (root/'attempts').glob('*.json'):
            d = json.loads(p.read_bytes())
            if any(r.get('kind') == 'host' and r.get('pid') == pid for r in d.get('execution_refs', [])):
                require(d.get('state') not in {'QUEUED', 'RUNNING'}, 'manager task not drained')
        for p in (root/'cursors').glob('oversold_daily_*.json'):
            d = json.loads(p.read_bytes())
            require(not(d.get('pid') == pid and d.get('state') == 'RUNNING'), 'oversold producer not drained')

    def term_and_wait(self, pid, seconds, *, send):
        queue = select.kqueue()
        try:
            try:
                queue.control([select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD|select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)], 0, 0)
            except ProcessLookupError:
                require(not send, 'PID exited before exact signal; recheck lifecycle')
                return True
            if send:
                require(self.pid_alive(pid), 'PID vanished before signal')
                require(pid > 0 and pid in self.pid_tokens, 'exact positive PID identity missing')
                require(self.run(['ps','-p',str(pid),'-o','lstart=,command=']) == self.pid_tokens[pid], 'PID identity changed before signal')
                os.kill(pid, signal.SIGTERM)  # exact positive PID only; never process groups
            queue.control(None, 1, seconds)
            return not self.pid_alive(pid)
        finally:
            queue.close()

    def bootout_nonrunning(self, expected):
        pid = self.registration(expected, allow_absent=True, require_process=False)
        require(pid is None, 'unexpected respawn STOP: no bootout allowed')
        if self.h['service_readback'](c.LABEL) is not None:
            self.run(['launchctl', 'bootout', self.target])
        self.h['wait_service_absent'](c.LABEL, timeout=30)

    def install_pointer(self, raw):
        atomic_replace(c.PLIST, raw)
        require(c.PLIST.read_bytes() == raw, 'atomic plist byte readback mismatch')

    def bootstrap(self, expected):
        self.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(c.PLIST)])
        self.h['wait_service_identity'](c.LABEL, expected, timeout=30)
        return self.registration(expected)

    def verify_protected(self, refs):
        expected = {}
        for ref in refs:
            require(c.sha(ref['path']) == ref['sha256'], 'protected binding receipt drift')
            doc = json.loads(Path(ref['path']).read_bytes())
            expected.update(doc['protected_files'])
            expected.update(doc.get('protected_replacement', {}))
        for path, want in expected.items():
            require(c.sha(path) == want, 'protected success drift: ' + path)

    def verify_inventory(self):
        p = self.p
        require(all(not Path(p[k]).is_symlink() for k in ['baseline_app','frozen_baseline_app','candidate_app']), 'app root symlink STOP')
        require(self.h['inventory'](Path(p['baseline_app'])) == self.h['inventory'](Path(p['frozen_baseline_app'])), 'actual baseline full inventory drift')
        require(c.sha(Path(p['baseline_app']).parent/'release-manifest.json') == OLD_MANIFEST_SHA, 'baseline manifest drift')
        require(self.h['inventory'](Path(p['candidate_app'])) == p['candidate_inventory'], 'candidate inventory drift')

    def verify_published(self):
        target=Path(self.p['target_app'])
        require(not target.is_symlink() and self.h['inventory'](target)==self.p['candidate_inventory'], 'published app drift')
        require(c.sha(self.p['target_manifest'])==self.p['release_manifest_sha256'], 'published manifest drift')

    def install_release(self):
        p = self.p; target = Path(p['target_app']).parent
        require(target.parent == BASE and target.name == c.binding_config()['release_id'], 'unexpected release target')
        require(Path(p['target_app']) == target/'app' and Path(p['target_manifest']) == target/'release-manifest.json', 'target identity layout')
        if target.exists():
            require(p.get('reuse_exact_inactive_release') is True, 'existing release needs reviewed reuse authorization')
            require(not target.is_symlink() and not (target/'app').is_symlink() and not (target/'release-manifest.json').is_symlink() and {x.name for x in target.iterdir()} == {'app','release-manifest.json'}, 'existing release drift')
        else:
            target.mkdir()
            shutil.copytree(p['candidate_app'], target/'app', symlinks=True)
            shutil.copy2(p['release_manifest'], target/'release-manifest.json')
        require(self.h['inventory'](target/'app') == p['candidate_inventory'] and c.sha(target/'release-manifest.json') == p['release_manifest_sha256'], 'installed release drift')

    def runtime(self, plist_path):
        env=plistlib.loads(Path(plist_path).read_bytes())['EnvironmentVariables']
        expected=self.p['source_sha256']
        if env['V35_APP_ROOT']==self.p['baseline_app']:
            binding=json.loads(Path(self.p['frozen_baseline_binding_path']).read_bytes())
            expected={x['path']:x['runtime_before_sha256'] for x in binding['source_before'] if x['runtime_before_sha256']}
        result = c.runtime_oracle(plist_path, expected)
        require(result.get('verified') is True, 'actual candidate import/identity oracle failed')
        return result


class Driver:
    def __init__(self, cap, packet, ops, state, save):
        self.cap=cap;self.p=packet;self.ops=ops;self.state=state;self.save=save
        self.original=plistlib.loads(Path(packet['original_plist']).read_bytes())
        self.candidate=plistlib.loads(Path(packet['candidate_plist']).read_bytes())

    def mark(self, phase, **data):
        self.state.update(phase=phase, **data);self.save(self.state)

    def drain(self, expected, *, resume=False):
        o=self.ops
        if not resume:
            require(o.override() == 'enabled', 'original explicit override changed')
            pid=o.registration(expected);require(pid==self.cap['expected_start_pid'],'initial registered PID differs from capsule');claims=o.claims(pid);o.pdf_clear(pid)
            self.mark('PRE_DISABLE', draining_pid=pid, claims=claims, original_override='enabled')
            o.set_override('disabled');self.mark('DISABLED',live_mutated=True,disabled_preserved=True)
            require(o.registration(expected) == pid, 'PID changed during disable')
            o.pdf_clear(pid)
            require(o.registration(expected) == pid and o.override() == 'disabled', 'exact signal identity drift')
            self.mark('SIGNAL_INTENT')
            exited=o.term_and_wait(pid,self.cap['drain_wait_seconds'],send=True)
        else:
            require(self.state.get('phase') == 'DRAIN_PENDING', 'resume only known pending cooperative drain')
            require(o.override() == 'disabled', 'pending drain override changed')
            pid=self.state['draining_pid'];claims=self.state['claims']
            seen=o.registration(expected,allow_absent=True,require_process=False)
            require(seen in {None,pid}, 'unexpected respawn during drain')
            exited=not o.pid_alive(pid) or o.term_and_wait(pid,self.cap['drain_wait_seconds'],send=False)
        if not exited:
            self.mark('DRAIN_PENDING', disabled_preserved=True, healthy_process_preserved=True)
            raise Pending('healthy process draining; no bootout, timeout kill, restore/restart or duplicate signal')
        self.mark('OLD_PID_EXITED')
        require(not o.pid_alive(pid), 'old PID still alive')
        require(o.registration(expected,allow_absent=True,require_process=False) is None, 'unexpected respawn STOP')
        o.terminal(claims+o.claims(pid));o.manager_terminal(pid)
        o.bootout_nonrunning(expected);self.mark('SERVICE_ABSENT')

    def execute(self, action, *, resume=False):
        o=self.ops;p=self.p;cap=self.cap
        expected=self.original if action=='activate' else self.candidate
        target=self.candidate if action=='activate' else self.original
        raw=Path(p['candidate_plist'] if action=='activate' else p['original_plist']).read_bytes()
        o.verify_inventory();o.verify_protected(cap['protected_bindings'])
        require(c.PLIST.read_bytes() == Path(p['original_plist'] if action=='activate' else p['candidate_plist']).read_bytes(), 'live plist drift')
        if not resume:
            require(o.override()=='enabled','original explicit override changed before publication')
            observed_pid=o.registration(expected);o.claims(observed_pid);o.pdf_clear(observed_pid)
        if action=='activate':
            o.install_release();self.mark('RELEASE_INSTALLED' if not resume else self.state['phase'])
            self.state['offline_candidate_runtime']=o.runtime(p['candidate_plist']);self.save(self.state)
        try:
            self.drain(expected,resume=resume)
            # Successful outputs made while draining must NOT be reverted. Existing
            # protected immutable pins still hold; mutable drift requires rebind.
            o.verify_protected(cap['protected_bindings']);o.verify_inventory();o.verify_published()
            o.install_pointer(raw);self.mark('POINTER_INSTALLED')
            o.set_override('enabled');self.mark('ENABLED')
            new_pid=o.bootstrap(target);self.mark('BOOTSTRAPPED',new_pid=new_pid)
            self.state['actual_candidate_runtime' if action=='activate' else 'actual_restored_runtime']=o.runtime(p['candidate_plist'] if action=='activate' else p['original_plist'])
            o.verify_protected(cap['protected_bindings']);o.verify_inventory();o.verify_published()
            require(o.override() == 'enabled', 'original enabled state not restored')
            self.mark('ACTIVATED' if action=='activate' else 'ROLLED_BACK', live_mutated=True, recovery_called=False)
            return self.state
        except Pending:
            raise
        except Exception as error:
            self.state['primary_error']=f'{type(error).__name__}: {error}'
            # No blind rollback against a live candidate/new PID. Same drain
            # protocol is available via separately capsule-authorized rollback.
            phase=self.state.get('phase')
            if phase in {'PRE_DISABLE','DISABLED'}:
                o.set_override('enabled');self.mark('STOPPED_BEFORE_SIGNAL', original_override_restored=True)
            elif phase == 'OLD_PID_EXITED':
                o.set_override('enabled');self.mark('STOPPED_AFTER_EXIT', original_override_restored=True, healthy_process_preserved=True)
            elif phase in {'SERVICE_ABSENT','POINTER_INSTALLED','ENABLED'}:
                try:
                    require(o.registration(target,allow_absent=True,require_process=False) is None, 'live candidate/new PID blocks absent rollback')
                    o.install_pointer(Path(p['original_plist']).read_bytes())
                    o.set_override('enabled');o.bootstrap(self.original)
                    self.mark('ORIGINAL_RESTORED_AFTER_ABSENT_FAILURE')
                except Exception as rollback_error:
                    self.mark('ROLLBACK_REQUIRED', rollback_error=f'{type(rollback_error).__name__}: {rollback_error}')
            else:
                self.mark('ROLLBACK_REQUIRED', healthy_process_preserved=True)
            raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capsule',type=Path,required=True);parser.add_argument('--capsule-sha256',required=True);parser.add_argument('--action',choices=['activate','rollback'],required=True);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    cap,packet=load_capsule(args.capsule,args.capsule_sha256,args.action)
    original=plistlib.loads(Path(packet['original_plist']).read_bytes())
    env=original['EnvironmentVariables']
    for key,want in [('ledger_root',env['V35_DISPATCH_LEDGER_ROOT']),('runtime_root',env['V35_RUNTIME_ROOT'])]:require(packet[key]==want,'packet owned root mismatch: '+key)
    require(packet['manager_config_path']==env['V4_MANAGER_WORKBENCH_CONFIG_PATH'] and c.sha(packet['manager_config_path'])==packet['manager_config_sha256'],'manager config drift')
    cfg=json.loads(Path(env['V4_MANAGER_WORKBENCH_CONFIG_PATH']).read_bytes());require(packet['manager_store_root']==str(Path(cfg['state_root'])/'manager_workbench'),'manager owned root mismatch')
    require(Path(packet['baseline_app'])==Path(env['V35_APP_ROOT']), 'baseline app mismatch')
    require(c.sha(packet['frozen_baseline_binding_path'])==packet['frozen_baseline_binding_sha256'],'frozen binding drift')
    binding=json.loads(Path(packet['frozen_baseline_binding_path']).read_bytes());require(packet['frozen_baseline_app']==binding['frozen_baseline_app'],'wrong frozen baseline')
    state_path=c.OWNER/(cap['operation_id']+'-'+args.action+'.json')
    if args.resume:
        if state_path.exists():
            state=json.loads(state_path.read_bytes());require(state.get('capsule_sha256')==args.capsule_sha256,'resume capsule changed')
        else:
            ref=cap.get('resume_from_state',{});prior=Path(ref.get('path','/invalid'))
            require(prior.is_relative_to(c.OWNER) and c.sha(prior)==ref.get('sha256'),'exact prior pending state pin required')
            state=json.loads(prior.read_bytes())
            require(state.get('phase')=='DRAIN_PENDING' and state.get('action')==args.action and state.get('capsule_sha256')==ref.get('prior_capsule_sha256'),'prior drain lifecycle mismatch')
            require(state.get('draining_pid')==cap['expected_start_pid'],'prior drain PID mismatch')
            state.update(resumed_from_state=ref,capsule_sha256=args.capsule_sha256)
    else:
        require(not state_path.exists(),'operation already exists; explicit pending resume only')
        state={'schema':'v4.producer_activation_control.v1','action':args.action,'capsule_sha256':args.capsule_sha256,'phase':'PREFLIGHT','live_mutated':False,'recovery_called':False,'events':[]}
    def save(data):
        data['events'].append({'phase':data['phase'],'at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
        c.dump(state_path,data)
    try:
        Driver(cap,packet,RealOps(packet),state,save).execute(args.action,resume=args.resume)
        print(json.dumps({'status':state['phase'],'receipt':str(state_path)}));return 0
    except Pending as error:
        print(json.dumps({'status':'DRAIN_PENDING','error':str(error),'receipt':str(state_path)}));return 3
    except Exception as error:
        state['terminal_error']=f'{type(error).__name__}: {error}';save(state)
        print(json.dumps({'status':state['phase'],'error':state['terminal_error'],'receipt':str(state_path)}));return 2


if __name__=='__main__':raise SystemExit(main())
