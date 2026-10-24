"""Exact active-base API overlay. Preparation never changes the live plist.

Activation/rollback are controller-only, retain both existing cutover locks,
and refuse a changed active release instead of restoring a stale baseline.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def emit(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


class Deployment:
    def __init__(self, root):
        self.root = root
        self.pre = json.loads((root / 'DEPLOYMENT_PRECONDITIONS.json').read_bytes())
        self.old = Path(self.pre['parent'])
        self.new = Path(self.pre['candidate'])
        self.plist = Path(self.pre['api_plist'])
        self.backup = root / 'current-r2-api.plist'
        self.proposal = root / 'candidate-api.plist'
        self.receipt = root / 'DEPLOYMENT_PREPARED.json'
        self.label = 'com.lexi.v35.api-only'
        if Path(sys.executable).resolve() != Path(self.pre['runtime_python']).resolve():
            raise RuntimeError('CURRENT_RUNTIME_PYTHON_REQUIRED')

    def helper(self):
        for path in reversed([str(self.old / 'app'), str(self.old / 'app/upstreams')]):
            if path not in sys.path:
                sys.path.insert(0, path)
        source = self.old / 'app/ops/api_release_integration.py'
        assert sha(source) == self.pre['helper_sha256'], 'INTEGRATION_HELPER_DRIFT'
        spec = importlib.util.spec_from_file_location('retained_hkex_release_integration', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = Path(self.pre['module_contract_path'])
        assert sha(contract) == self.pre['module_contract_sha256'], 'MODULE_CONTRACT_DRIFT'
        module.MODULE_CONTRACT_PATH = contract
        return module

    def source_guards(self):
        assert sha(self.old / 'release-manifest.json') == self.pre['parent_manifest_sha256'], 'PARENT_MANIFEST_DRIFT'
        assert sha(self.root / 'IMPLEMENTATION_SOURCE_MANIFEST.json') == self.pre['source_manifest_sha256'], 'SOURCE_MANIFEST_DRIFT'
        for row in self.pre['sources']:
            assert sha(Path(self.pre['source_worktree']) / row['path']) == row['after_sha256'], 'REVIEWED_SOURCE_DRIFT'
            path = self.old / 'app' / row['path']
            assert (sha(path) if path.exists() else None) == row['before_sha256'], 'ACTIVE_SOURCE_DRIFT'
        for path, expected in self.pre['external_guards'].items():
            assert sha(path) == expected, 'EXTERNAL_BINDING_DRIFT'

    def runtime(self, app, expected_pid=None):
        state = subprocess.run(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + self.label],
                               capture_output=True, text=True, check=True).stdout
        match = re.search(r'\n\s*pid = (\d+)', state)
        assert match, 'API_RUNNING_PID_MISSING'
        pid = int(match.group(1))
        assert expected_pid is None or pid == expected_pid, 'API_PID_CHANGED_REFREEZE_REQUIRED'
        cwd = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                             capture_output=True, text=True, check=True).stdout
        assert 'n' + str(app) in cwd.splitlines(), 'API_CWD_MISMATCH'
        return {'pid': pid, 'cwd': str(app)}

    def prepare(self):
        self.source_guards()
        assert not any(p.exists() for p in [self.new, self.receipt, self.backup, self.proposal]), 'PREPARATION_EXISTS_DO_NOT_OVERWRITE'
        module = self.helper()
        with module.shared_api_release_lock(self.plist, timeout_seconds=2), module.announcement_flash_cutover_guard(
                Path(self.pre['workbench_store_root']), timeout_seconds=2):
            assert sha(self.plist) == self.pre['api_plist_sha256'], 'ACTIVE_PLIST_DRIFT'
            running = self.runtime(self.old / 'app', self.pre['runtime_pid'])
            self.source_guards()
            active = module.read_active_release(self.plist)
            assert active['release_root'] == str(self.old), 'ACTIVE_RELEASE_CHANGED'
            assert active['release_manifest_sha256'] == self.pre['parent_manifest_sha256'], 'ACTIVE_MANIFEST_CHANGED'
            delta_root = self.root / 'deployment-delta-source'
            delta_root.mkdir()
            entries = []
            for row in sorted(self.pre['sources'], key=lambda row: row['path']):
                source = Path(self.pre['source_worktree']) / row['path']
                target = delta_root / row['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                before = self.old / 'app' / row['path']
                proof = module._diff_proof(before.read_bytes(), source.read_bytes()) if before.exists() else (None, None)
                entries.append(dict(path=row['path'], before_sha256=row['before_sha256'],
                    after_sha256=row['after_sha256'], unified_diff_sha256=proof[0], unified_diff_hunk_count=proof[1]))
            delta = self.root / 'deployment-delta-receipt.json'
            emit(delta, dict(schema_version=module.DELTA_SCHEMA_VERSION, base=module._base_binding(active), entries=entries))
            self.new.mkdir()
            integration = module.build_integrated_app(active_api_plist_path=self.plist, source_root=delta_root,
                candidate_root=self.new, delta_receipt_path=delta,
                explicit_untracked_paths=[row['path'] for row in entries if row['before_sha256'] is None])
            inventory = module.inventory_tree(self.new / 'app')
            old_manifest = active['manifest']
            identity = dict(old_manifest['candidate'], root=str(self.new), app_root=str(self.new / 'app'),
                            formal_release_root=str(self.new), release_id=self.new.name)
            manifest = dict(schema_version='v4.release_candidate.v1', candidate=identity,
                descriptor_status='IMMUTABLE_PREPARED_DESCRIPTOR_ACTIVATION_RECORDED_SEPARATELY', api_integration=integration,
                application_inventory=dict(entries=inventory, entry_count=len(inventory), aggregate_sha256=module.inventory_digest(inventory)),
                financial_safety=old_manifest.get('financial_safety'), manual_stage_binding=old_manifest.get('manual_stage_binding'),
                release_preparation=dict(state='PREPARED_NOT_ACTIVATED', parent_manifest_sha256=self.pre['parent_manifest_sha256'],
                    source_manifest_sha256=self.pre['source_manifest_sha256'], source_workspace_full_tree_copied=False,
                    scheduler_changed=False, business_data_changed=False))
            emit(self.new / 'release-manifest.json', manifest)
            raw = self.plist.read_bytes()
            self.backup.write_bytes(raw)
            self.backup.chmod(0o600)
            manifest_sha = sha(self.new / 'release-manifest.json')

            def rebind(value):
                if isinstance(value, str):
                    return value.replace(str(self.old), str(self.new)).replace(self.old.name, self.new.name).replace(self.pre['parent_manifest_sha256'], manifest_sha)
                if isinstance(value, list): return [rebind(x) for x in value]
                if isinstance(value, dict): return {key: rebind(x) for key, x in value.items()}
                return value

            original = plistlib.loads(raw)
            proposed = rebind(original)
            assert proposed['Label'] == original['Label'] == self.label
            assert proposed['WorkingDirectory'] == str(self.new / 'app')
            assert proposed.get('KeepAlive') == original.get('KeepAlive')
            assert proposed.get('RunAtLoad') == original.get('RunAtLoad')
            self.proposal.write_bytes(plistlib.dumps(proposed, sort_keys=False))
            self.proposal.chmod(0o600)
            verification = module.verify_api_release_candidate(candidate_root=self.new, active_api_plist_path=self.plist,
                expected_manifest_sha256=manifest_sha, active_pointer='base')
            assert set(verification['delta_paths']) == {row['path'] for row in entries}
            assert sha(self.plist) == self.pre['api_plist_sha256'], 'PLIST_CHANGED_DURING_PREPARE'
            emit(self.receipt, dict(state='PREPARED_NOT_ACTIVATED', candidate=str(self.new), parent=str(self.old),
                candidate_manifest_sha256=manifest_sha, original_plist_sha256=sha(self.backup),
                proposed_plist_sha256=sha(self.proposal), exact_delta=entries, verification=verification,
                runtime_before=running, source_manifest_sha256=self.pre['source_manifest_sha256'],
                activated=False, services_reloaded=0, business_posts=0))
        print('PREPARED_NOT_ACTIVATED ' + str(self.receipt))

    def verify(self, pointer='base'):
        self.source_guards()
        receipt = json.loads(self.receipt.read_bytes())
        assert sha(self.backup) == receipt['original_plist_sha256'] == self.pre['api_plist_sha256']
        assert sha(self.proposal) == receipt['proposed_plist_sha256']
        module = self.helper()
        result = module.verify_api_release_candidate(candidate_root=self.new, active_api_plist_path=self.plist,
            expected_manifest_sha256=receipt['candidate_manifest_sha256'], active_pointer=pointer)
        return module, receipt, result

    def atomic_plist(self, raw):
        staged = self.plist.with_name(self.plist.name + '.hkex-staged')
        assert not staged.exists(), 'STAGED_PLIST_EXISTS'
        mode = self.plist.stat().st_mode & 0o777
        with staged.open('xb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        staged.chmod(mode)
        os.replace(staged, self.plist)

    def reload(self):
        domain = 'gui/' + str(os.getuid())
        target = domain + '/' + self.label
        state = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, text=True)
        if state.returncode == 0 and 'state = SIGTERMed' not in state.stdout:
            subprocess.run(['/bin/launchctl', 'bootout', target], check=True)
        elif state.returncode not in (0, 113):
            raise RuntimeError('UNEXPECTED_API_LIFECYCLE')
        for _ in range(20):
            state = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, text=True)
            if state.returncode == 113: break
            if state.returncode != 0: raise RuntimeError('UNEXPECTED_API_UNLOAD_STATE')
            time.sleep(1)
        else: raise RuntimeError('API_UNLOAD_PENDING_DO_NOT_REPEAT_BOOTOUT')
        subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(self.plist)], check=True)
        subprocess.run(['/bin/launchctl', 'kickstart', target], check=True)

    def cutover(self, rollback=False):
        module, receipt, _ = self.verify('candidate' if rollback else 'base')
        if not rollback:
            gate = json.loads((self.root / 'DEPLOYMENT_APPROVAL.json').read_bytes())
            assert gate['controller_authorized'] is True
            assert gate['source_manifest_sha256'] == self.pre['source_manifest_sha256']
            assert gate['candidate_manifest_sha256'] == receipt['candidate_manifest_sha256']
            assert sha(gate['review_receipt']) == gate['review_receipt_sha256']
            assert json.loads(Path(gate['review_receipt']).read_bytes())['verdict'] == 'PASS'
        with module.shared_api_release_lock(self.plist, timeout_seconds=2), module.announcement_flash_cutover_guard(
                Path(self.pre['workbench_store_root']), timeout_seconds=2):
            expected = receipt['proposed_plist_sha256'] if rollback else self.pre['api_plist_sha256']
            assert sha(self.plist) == expected, 'PLIST_DRIFT_NO_OVERWRITE'
            self.verify('candidate' if rollback else 'base')
            self.runtime((self.new if rollback else self.old) / 'app',
                         None if rollback else self.pre['runtime_pid'])
            try:
                self.atomic_plist((self.backup if rollback else self.proposal).read_bytes())
                self.reload()
                for _ in range(15):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:8873/healthz', timeout=2) as response:
                            if json.load(response).get('status') == 'ok': break
                    except (OSError, ValueError): pass
                    time.sleep(1)
                else: raise RuntimeError('API_HEALTH_PENDING')
                self.verify('base' if rollback else 'candidate')
                running = self.runtime((self.old if rollback else self.new) / 'app')
            except Exception:
                if not rollback and sha(self.plist) == receipt['proposed_plist_sha256']:
                    self.atomic_plist(self.backup.read_bytes())
                    self.reload()
                    self.verify('base')
                    self.runtime(self.old / 'app')
                    emit(self.root / 'ACTIVATION_FAILED_ROLLED_BACK.json', dict(state='EXACT_R2_POINTER_RESTORED',
                        recovery_behavior='CANNOT_CONFIRM', business_posts=0))
                raise
            emit(self.root / ('ROLLED_BACK.json' if rollback else 'ACTIVATED.json'),
                dict(state='ROLLED_BACK_PENDING_BEHAVIOR' if rollback else 'ACTIVATED_PENDING_BEHAVIOR',
                     runtime=running, plist_sha256=sha(self.plist), scheduler_changed=False, business_posts=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'verify', 'activate', 'rollback'])
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--controller-authorized', action='store_true')
    args = parser.parse_args()
    if not args.evidence_root.is_absolute(): parser.error('absolute evidence root required')
    if args.action in ('activate', 'rollback') and not args.controller_authorized:
        parser.error('controller authorization required after independent review')
    deployment = Deployment(args.evidence_root)
    if args.action == 'prepare': deployment.prepare()
    elif args.action == 'verify': print(json.dumps(deployment.verify()[2], ensure_ascii=False))
    else: deployment.cutover(args.action == 'rollback')
