"""Hermetic release-scope/CAS tests; only own scratch fixtures are mutated."""
from __future__ import annotations

import argparse
import ast
import base64
from copy import deepcopy
import csv
import stat
import struct
import zipfile
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import prepare_release as prepare
import activate_release as activate

WT = Path(__file__).resolve().parents[4]
SCRATCH = WT / '.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment'
INVENTORY = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hkex-announcements-api-20261023-r1/app/ops/api_release_integration.py')
INVENTORY_SHA = '2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'
RETAINED_STORE=INVENTORY.parent.parent/'v4/manager_workbench/store.py'
SDK_LOG_TEST_PYTHON=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260820T104322Z-v35-coordinated-recurrence/runtime/python/cpython-3.13.12-macos-aarch64-none/bin/python3.13')
REAL_RELEASE_GUARDS=activate.release_guards
LIVE_PATHS = [Path('/Users/lexi/Library/LaunchAgents') / (label + '.plist') for label in ('com.lexi.v35.api-only', 'com.lexi.v35.scheduler')]
LIVE_PATHS += [Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2') / name for name in ('panel_latest.json', 'history_resolution_latest.json')]


def fixture_log_policy(path,logger_sha):
    return dict(schema='v4.us_hk.sdk_log_policy.v1',home=os.environ['HOME'],date=prepare.HK_SDK_LOG_DATE,path=str(path),
        existing_only=True,max_handler_opens=1,max_append_bytes=65536,no_create=True,no_rotation=True,no_delete=True,
        mode='a',codex_home_present='CODEX_HOME' in os.environ,codex_home=os.environ.get('CODEX_HOME'),
        identities={str(p):prepare.sdk_log_identity(p) for p in [*reversed(path.parents),path]},sdk_logger_sha256=logger_sha)


def fixture_log_result(policy):
    st=Path(policy['path']).stat();snapshot=dict(policy['identities'][policy['path']],size=st.st_size,mtime_ns=st.st_mtime_ns)
    return dict(policy_sha256=prepare.digest(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()),
        path=policy['path'],date=policy['date'],before=snapshot,after=dict(snapshot),handler_opens=1,
        enforced_size_limit=st.st_size+65536,observed_size_delta=0,content_read=False,created=False,rotated=False,
        deleted=False,concurrent_growth_not_attributable=True,sdk_logger_sha256=policy['sdk_logger_sha256'])


class FakeSubprocess:
    def __init__(self,scope,*,fail_bootstrap=False,fail_bootout=False):
        self.scope=scope;self.running=True;self.pid=111;self.cwd=str(Path(scope['parent_root'])/'app')
        self.fail_bootstrap=fail_bootstrap;self.fail_bootout=fail_bootout;self.commands=[];self.command_options=[]
        self.alive_pids=set()
    def __call__(self,args,**kwargs):
        self.commands.append(args);self.command_options.append(kwargs);rc=0;out=''
        if '-c' in args:
            origins=json.loads(args[-1])
            out=json.dumps(dict(version=self.scope['runtime_probe']['python']['version'],origins=origins,
                module_sha256={name:prepare.sha(path) for name,path in origins.items()}))
            if self.scope.get('hk_sdk_artifact'):
                body=json.loads(out);body['sdk_canary']=dict(versions={name:value[0] for name,value in prepare.HK_SDK_DISTRIBUTIONS.items()},
                    simplejson_native=True,protobuf_backend='upb',aes_known_answer='66e94bd4ef8a2c3b884cfa59ca342b2e',provider_initialized=False)
                body['sdk_log_side_effect']=fixture_log_result(self.scope['runtime_probe']['sdk_log_policy']);out=json.dumps(body)
        elif args[:2]==['/bin/launchctl','print']:
            rc=0 if self.running else 113
            out=f'state = running\npid = {self.pid}\n' if self.running else ''
        elif args[:2]==['/bin/launchctl','bootout']:
            if self.fail_bootout:rc=5
            else:self.running=False
        elif args[:2]==['/bin/launchctl','bootstrap']:
            if self.fail_bootstrap:rc=5;self.fail_bootstrap=False
            else:
                self.running=True;self.pid+=1
                self.cwd=plistlib.loads(Path(self.scope['plist']['path']).read_bytes())['WorkingDirectory']
        elif args[0]=='/usr/sbin/lsof':out='n'+self.cwd+'\n'
        elif args[:3]==['/bin/ps','-axo','pid=,ppid=']:out=f'{self.pid} 1\n'
        elif args[0]=='/bin/ps' and args[-1]=='comm=':out=self.scope['runtime_probe']['python']['path']+'\n'
        elif args[0]=='/bin/ps' and args[-1]=='pid=':
            rc=0 if int(args[2]) in self.alive_pids else 1
            out=args[2]+'\n' if rc==0 else ''
        else:raise AssertionError('Unapproved fake subprocess:'+repr(args))
        return SimpleNamespace(returncode=rc,stdout=out,stderr='')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rehearsal-', dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.parent, self.source, self.evidence = [self.root / p for p in ('parent', 'source', 'evidence')]
        for p in (self.parent / 'app/v4/manager_workbench', self.parent / 'app/assets', self.source, self.evidence):
            p.mkdir(parents=True, exist_ok=True)
        self.target = 'v4/manager_workbench/engine.py'
        (self.parent / 'app' / self.target).write_bytes(b'old source\n')
        (self.parent / 'app/assets/old.js').write_bytes(b'old static\n')
        (self.parent / 'app/assets/link.js').symlink_to('old.js')
        # Seven unrelated announcement dependency bytes must survive exactly.
        self.preserved = []
        for index in range(7):
            p = self.parent / f'app/announcement_dependency_{index}.py'
            p.write_bytes(f'existing announcement {index}\n'.encode())
            self.preserved.append(dict(path=p.relative_to(self.parent / 'app').as_posix(), sha256=prepare.sha(p)))
        (self.source / 'engine.py').write_bytes(b'new reviewed source\n')
        self.candidate = self.root / 'candidate'
        self.plist = self.root / 'service.plist'
        self.old_bytes = plistlib.dumps(dict(Label='fixture', WorkingDirectory=str(self.parent / 'app'),
            EnvironmentVariables={'V35_APP_ROOT': str(self.parent / 'app'), 'UNCHANGED': 'original'},
            KeepAlive=True, RunAtLoad=False), sort_keys=False)
        self.plist.write_bytes(self.old_bytes)
        self.plist.chmod(0o644)
        self.tool_pin = dict(path=str(INVENTORY), sha256=INVENTORY_SHA)
        self.tool = prepare.inventory_tool(self.tool_pin)
        self.refresh_parent()
        self.review = self.root / 'review.json'
        self.review.write_bytes(prepare.json_bytes(dict(verdict='PASS', source_commit='a' * 40,
            files={self.target: prepare.sha(self.source / 'engine.py')})))
        self.scope = dict(schema=prepare.SCHEMA, state='READY', mode='REHEARSAL', role='api',
            rehearsal_root=str(self.root), source_root=str(self.source), evidence_root=str(self.evidence),
            parent_root=str(self.parent), candidate_root=str(self.candidate), source_commit='a' * 40,
            parent_manifest_sha256=prepare.sha(self.parent / 'release-manifest.json'), inventory_tool=self.tool_pin,
            review_receipts=[dict(path=str(self.review), sha256=prepare.sha(self.review))],
            overlays=[dict(source='engine.py', target=self.target,
                before_sha256=prepare.sha(self.parent / 'app' / self.target),
                sha256=prepare.sha(self.source / 'engine.py'), mode=0o644)],
            dependencies=[], preserved_app_files=self.preserved, data_pointer_changes=[],
            safety=dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False),
            plist=dict(path=str(self.plist), sha256=prepare.sha(self.plist), updates=[
                dict(keys=['WorkingDirectory'], before=str(self.parent / 'app'), after='{app}'),
                dict(keys=['EnvironmentVariables', 'V35_APP_ROOT'], before=str(self.parent / 'app'), after='{app}')]))
        self.scope_path = self.root / 'scope.json'
        self.prepared_path = self.evidence / 'PREPARED.json'
        self.activation_path = self.evidence / 'ACTIVATED.json'
        self.rollback_path = self.evidence / 'ROLLBACK.json'

    def refresh_parent(self):
        entries = self.tool.inventory_tree(self.parent / 'app')
        (self.parent / 'release-manifest.json').write_bytes(prepare.json_bytes(dict(
            application_inventory=dict(entries=entries, aggregate_sha256=self.tool.inventory_digest(entries)))))

    def scope_sha(self):
        self.scope_path.write_bytes(prepare.json_bytes(self.scope))
        return prepare.sha(self.scope_path)

    def run_prepare(self):
        return prepare.prepare(self.scope_path, self.scope_sha(), self.prepared_path)

    def run_transition(self, direction='activate', lifecycle=None):
        lifecycle = lifecycle or activate.FakeLifecycle(str(self.parent / 'app'))
        path = self.activation_path if direction == 'activate' else self.rollback_path
        return activate.transition(self.prepared_path, prepare.sha(self.prepared_path), direction, lifecycle, path)

    def test_prepare_activate_exact_byte_rollback(self):
        result = self.run_prepare()
        self.assertEqual(result['changed_paths'], [self.target])
        for pin in self.preserved:
            self.assertEqual(prepare.sha(self.candidate / 'app' / pin['path']), pin['sha256'])
        self.assertTrue((self.candidate / 'app/assets/link.js').is_symlink())
        lifecycle = activate.FakeLifecycle(str(self.parent / 'app'))
        active = self.run_transition(lifecycle=lifecycle)
        self.assertEqual(active['state'], 'ACTIVATED')
        self.assertEqual(plistlib.loads(self.plist.read_bytes())['EnvironmentVariables']['UNCHANGED'], 'original')
        back = self.run_transition('rollback', lifecycle)
        self.assertEqual(back['state'], 'ROLLED_BACK')
        self.assertEqual(self.plist.read_bytes(), self.old_bytes)
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o644)
        self.assertEqual(len(lifecycle.calls), 2)

    def test_scope_hash_drift(self):
        self.scope_sha()
        with self.assertRaisesRegex(prepare.Stop, 'FILE_SHA_DRIFT'):
            prepare.prepare(self.scope_path, '0' * 64, self.prepared_path)

    def test_stale_parent_manifest(self):
        self.scope['parent_manifest_sha256'] = '0' * 64
        with self.assertRaisesRegex(prepare.Stop, 'FILE_SHA_DRIFT'):
            self.run_prepare()
        self.assertFalse(self.candidate.exists())

    def test_stale_parent_inventory(self):
        (self.parent / 'app/assets/old.js').write_bytes(b'drift')
        with self.assertRaisesRegex(prepare.Stop, 'PARENT_INVENTORY_DRIFT'):
            self.run_prepare()

    def test_source_drift(self):
        (self.source / 'engine.py').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(prepare.Stop, 'SOURCE_DRIFT'):
            self.run_prepare()

    def test_candidate_collision(self):
        self.candidate.mkdir()
        with self.assertRaisesRegex(prepare.Stop, 'CANDIDATE_COLLISION'):
            self.run_prepare()

    def test_unreviewed_overlay(self):
        self.scope['overlays'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(prepare.Stop, 'UNREVIEWED_OVERLAY'):
            self.run_prepare()

    def test_failed_review(self):
        d = json.loads(self.review.read_bytes()); d['verdict'] = 'FAIL'
        self.review.write_bytes(prepare.json_bytes(d))
        self.scope['review_receipts'][0]['sha256'] = prepare.sha(self.review)
        with self.assertRaisesRegex(prepare.Stop, 'SOURCE_REVIEW_NOT_PASS'):
            self.run_prepare()

    def test_preserved_dependency_cannot_overlay(self):
        self.scope['preserved_app_files'].append(dict(path=self.target, sha256=self.scope['overlays'][0]['before_sha256']))
        with self.assertRaisesRegex(prepare.Stop, 'PRESERVED_DEPENDENCY_OVERLAY'):
            self.run_prepare()

    def test_symlink_target_rejected(self):
        target = self.parent / 'app' / self.target
        target.unlink(); target.symlink_to('../../assets/old.js')
        self.refresh_parent(); self.scope['parent_manifest_sha256'] = prepare.sha(self.parent / 'release-manifest.json')
        with self.assertRaisesRegex(prepare.Stop, 'SYMLINK_OR_ALIAS'):
            self.run_prepare()

    def test_path_escape(self):
        self.scope['candidate_root'] = str(self.root.parent / 'outside-candidate')
        with self.assertRaisesRegex(prepare.Stop, 'REHEARSAL_PATH_ESCAPE'):
            self.run_prepare()

    def test_data_promotion_rejected(self):
        self.scope['data_pointer_changes'] = ['panel_latest.json']
        with self.assertRaisesRegex(prepare.Stop, 'DATA_PROMOTION_FORBIDDEN'):
            self.run_prepare()

    def test_release_preparation_is_not_armed(self):
        self.scope['mode'] = 'RELEASE'
        with self.assertRaisesRegex(prepare.Stop, 'FINAL_CONTROLLER_CAPSULE_REQUIRED'):
            self.run_prepare()

    def test_unexpected_candidate_delta(self):
        inventory = self.tool.inventory_tree
        def altered(root):
            if root == self.candidate / 'app':
                (root / 'rogue.py').write_bytes(b'unexpected')
            return inventory(root)
        with patch.object(self.tool, 'inventory_tree', side_effect=altered), patch.object(prepare, 'inventory_tool', return_value=self.tool):
            with self.assertRaisesRegex(prepare.Stop, 'UNEXPECTED_CANDIDATE_DELTA'):
                self.run_prepare()
        self.assertFalse(self.prepared_path.exists())

    def test_partial_copy_is_not_success_or_reused(self):
        original = prepare.shutil.copytree
        def partial(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('fake partial copy')
        with patch.object(prepare.shutil, 'copytree', side_effect=partial):
            with self.assertRaises(OSError): self.run_prepare()
        self.assertTrue(self.candidate.exists())
        self.assertFalse(self.prepared_path.exists())
        with self.assertRaisesRegex(prepare.Stop, 'CANDIDATE_COLLISION'): self.run_prepare()

    def test_busy_work_stops_before_write(self):
        self.run_prepare()
        lifecycle = activate.FakeLifecycle(str(self.parent / 'app'), busy_work=['job-running'])
        with self.assertRaisesRegex(prepare.Stop, 'HEALTHY_WORK_IN_FLIGHT'): self.run_transition(lifecycle=lifecycle)
        self.assertEqual(self.plist.read_bytes(), self.old_bytes)
        self.assertEqual(lifecycle.calls, [])

    def test_idle_surface_is_not_busy_work(self):
        self.run_prepare()
        class Idle(activate.FakeLifecycle):
            def inspect(self): return dict(super().inspect(), idle_browser_keepalive=True, idle_scheduler_threads=True)
        lifecycle = Idle(str(self.parent / 'app'))
        self.assertEqual(self.run_transition(lifecycle=lifecycle)['state'], 'ACTIVATED')

    def test_stale_plist_stops_inside_cas(self):
        self.run_prepare(); self.plist.write_bytes(b'third party')
        with self.assertRaisesRegex(prepare.Stop, 'CURRENT_PLIST_CAS_DRIFT'): self.run_transition()
        self.assertEqual(self.plist.read_bytes(), b'third party')

    def test_candidate_tamper_stops(self):
        self.run_prepare(); (self.candidate / 'app/assets/old.js').write_bytes(b'tampered')
        with self.assertRaisesRegex(prepare.Stop, 'CANDIDATE_INVENTORY_DRIFT'): self.run_transition()

    def test_unknown_runtime_stops(self):
        self.run_prepare()
        with self.assertRaisesRegex(prepare.Stop, 'RUNTIME_IDENTITY_DRIFT'):
            self.run_transition(lifecycle=activate.FakeLifecycle(str(self.parent / 'app'), state='unknown'))

    def test_partial_reload_receipt_no_blind_retry(self):
        self.run_prepare(); lifecycle = activate.FakeLifecycle(str(self.parent / 'app'), fail=True)
        with self.assertRaisesRegex(prepare.Stop, 'PARTIAL_TRANSITION_REQUIRES_INSPECTION'): self.run_transition(lifecycle=lifecycle)
        self.assertEqual(json.loads(self.activation_path.read_bytes())['state'], 'FAILED_REQUIRES_INSPECTION')
        self.assertEqual(len(lifecycle.calls), 1)
        with self.assertRaisesRegex(prepare.Stop, 'TRANSITION_RECEIPT_COLLISION'): self.run_transition(lifecycle=lifecycle)
        self.assertEqual(len(lifecycle.calls), 1)

    def test_rollback_third_party_drift_preserved(self):
        self.run_prepare(); lifecycle = activate.FakeLifecycle(str(self.parent / 'app'))
        self.run_transition(lifecycle=lifecycle); self.plist.write_bytes(b'new owner bytes')
        with self.assertRaisesRegex(prepare.Stop, 'CURRENT_PLIST_CAS_DRIFT'): self.run_transition('rollback', lifecycle)
        self.assertEqual(self.plist.read_bytes(), b'new owner bytes')
        self.assertEqual(len(lifecycle.calls), 1)

    def test_live_activation_mode_rejected(self):
        self.run_prepare(); self.scope['mode'] = 'RELEASE'; self.scope_sha()
        d=json.loads(self.prepared_path.read_bytes()); d['scope_sha256']=prepare.sha(self.scope_path)
        self.prepared_path.write_bytes(prepare.json_bytes(d))
        with self.assertRaisesRegex(prepare.Stop, 'FINAL_CONTROLLER_CAPSULE_REQUIRED'): self.run_transition()

    def test_candidate_proposal_drift_rejected(self):
        result=self.run_prepare(); Path(result['candidate_plist']).write_bytes(b'mutable receipt cannot define its preimage')
        with self.assertRaisesRegex(prepare.Stop, 'PROPOSAL_DRIFT'): self.run_transition()

    def test_rehearsal_cannot_name_live_boundary(self):
        self.scope['rehearsal_root'] = '/Users/lexi'
        with self.assertRaisesRegex(prepare.Stop, 'REHEARSAL_BOUNDARY_INVALID'): self.run_prepare()

    def test_readonly_candidate_parents_preserved(self):
        paths=[self.parent/'app/v4',self.parent/'app/v4/manager_workbench']
        for p in paths:
            p.chmod(0o555)
            self.addCleanup(p.chmod,0o755)
        self.run_prepare()
        for p in paths:
            candidate_path=self.candidate/p.relative_to(self.parent)
            self.assertEqual(candidate_path.stat().st_mode & 0o777,0o555)
            self.addCleanup(candidate_path.chmod,0o755)

    def test_scope_drift_at_lock_boundary(self):
        self.run_prepare()
        @contextmanager
        def changed(_):
            self.scope_path.write_bytes(b'changed while waiting for lock')
            yield
        with patch.object(activate,'transition_lock',changed):
            with self.assertRaisesRegex(prepare.Stop,'SCOPE_CHANGED_DURING_TRANSITION'): self.run_transition()
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_prepared_drift_at_lock_boundary(self):
        self.run_prepare()
        @contextmanager
        def changed(_):
            self.prepared_path.write_bytes(b'changed while waiting for lock')
            yield
        with patch.object(activate,'transition_lock',changed):
            with self.assertRaisesRegex(prepare.Stop,'PREPARED_RECEIPT_CHANGED_DURING_TRANSITION'): self.run_transition()
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_proposal_changes_after_check(self):
        result=self.run_prepare()
        class ProposalDrift(activate.FakeLifecycle):
            def inspect(inner):
                p=Path(result['candidate_plist'])
                d=plistlib.loads(p.read_bytes());d['KeepAlive']=False
                p.write_bytes(plistlib.dumps(d,sort_keys=False))
                return super().inspect()
        lifecycle=ProposalDrift(str(self.parent/'app'))
        with self.assertRaisesRegex(prepare.Stop,'TARGET_PLIST_CHANGED_DURING_TRANSITION'): self.run_transition(lifecycle=lifecycle)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)
        self.assertEqual(lifecycle.calls,[])

    def test_copied_bytes_must_match_review(self):
        copy=prepare.shutil.copyfile
        def tamper(src,dst,*args,**kwargs):
            result=copy(src,dst,*args,**kwargs)
            if Path(dst)==self.candidate/'app'/self.target: Path(dst).write_bytes(b'copy changed bytes')
            return result
        with patch.object(prepare.shutil,'copyfile',side_effect=tamper):
            with self.assertRaisesRegex(prepare.Stop,'COPIED_SOURCE_SHA_MISMATCH'): self.run_prepare()
        self.assertFalse(self.prepared_path.exists())

    def release_fixture(self):
        self.scope.update(mode='RELEASE',role='scheduler',candidate_root=str(self.root/'us-hk-selection-scheduler-fixture'))
        self.candidate=Path(self.scope['candidate_root'])
        path=self.root/'com.lexi.v35.scheduler.plist';self.plist.rename(path);self.plist=path
        python=self.source/'python';python.write_bytes(b'fake interpreter, never executed')
        updater=self.source/'update_hk_0_2_panel.py';updater.write_bytes(b'fake reviewed updater')
        site=self.root/'site-packages';site.mkdir()
        (self.parent/'app/upstreams').mkdir()
        self.scope['runtime_probe']=dict(python=dict(path=str(python),resolved_path=str(python),sha256=prepare.sha(python),version='3.14.6'),
            site_packages=[str(site)],modules={'v4.manager_workbench.engine':self.target})
        self.scope['shared_updater']=dict(path=str(updater),sha256=prepare.sha(updater))
        launcher=self.parent/'app/ops/launch_v35_macos_scheduler.sh';launcher.parent.mkdir();launcher.write_bytes(b'fake existing launcher')
        self.refresh_parent();self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')
        old=plistlib.loads(self.old_bytes);old['Label']='com.lexi.v35.scheduler'
        old['ProgramArguments']=['/bin/bash',str(launcher)]
        env=old['EnvironmentVariables'];env.update(V35_RELEASE_ID='parent',V35_RELEASE_MANIFEST_PATH=str(self.parent/'release-manifest.json'),
            V35_RELEASE_MANIFEST_SHA256=self.scope['parent_manifest_sha256'],PYTHONPATH=str(self.parent/'app'),
            V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT='old-updater',V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT='old-child',
            V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE='old-wrapper',V35_SHARED_PACKAGE_ROOT='old-shared-root',V35_RUNTIME_ROOT='old-runtime')
        env.update(RESEARCH_ONLY='1',production_allowed='false',buy_gate_updated='false',orders_sent='false')
        self.old_bytes=plistlib.dumps(old,sort_keys=False);self.plist.write_bytes(self.old_bytes)
        updates=self.scope['plist']['updates']
        updates.append(dict(keys=['ProgramArguments',1],before=str(launcher),after='{app}/ops/launch_v35_macos_scheduler.sh'))
        for key,after in [('V35_RELEASE_ID','{release_id}'),('V35_RELEASE_MANIFEST_PATH','{manifest}'),
                          ('V35_RELEASE_MANIFEST_SHA256','{manifest_sha256}'),('PYTHONPATH','{app}'),
                          ('V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT',str(updater))]:
            updates.append(dict(keys=['EnvironmentVariables',key],before=env[key],after=after))
        self.scope['plist'].update(path=str(self.plist),sha256=prepare.sha(self.plist))
        wb=self.root/'state/manager_workbench';(wb/'attempts').mkdir(parents=True)
        data=self.root/'data';data.mkdir();dispatcher=self.root/'dispatcher';(dispatcher/'claims/live').mkdir(parents=True)
        self.scope['activity']=dict(expected_pid=111,uid=501,workbench_root=str(wb),data_root=str(data),dispatcher_root=str(dispatcher),
            existing_kernel_locks=[],release_lock_path=str(self.root/'.com.lexi.v35.scheduler.release.lock'))
        self.addCleanup(patch.stopall)
        patch.object(prepare,'WORKTREE',self.source).start();patch.object(prepare,'RELEASES',self.root).start()
        patch.object(prepare,'LAUNCHAGENTS',self.root).start()
        def guard(_):
            return activate.transition_lock(self.evidence)
        patch.object(activate,'release_guards',guard).start()
        capsule=self.root/'controller-capsule.json'
        capsule.write_bytes(prepare.json_bytes(dict(schema='v4.us_hk.execution_capsule.v1',verdict='PASS',
            authorized_actions=['prepare','activate','rollback'],scope_contract_sha256=prepare.contract_sha(self.scope),
            helper_sha256={name:prepare.sha(Path(__file__).with_name(name)) for name in ('prepare_release.py','activate_release.py')})))
        self.scope['execution_capsule']=dict(path=str(capsule),sha256=prepare.sha(capsule))
        fake=FakeSubprocess(self.scope)
        return fake

    def continuation_fixture(self, *, prepare_only=True):
        runner=self.release_fixture()
        token=dict(pid=111,start_sec=2,start_usec=3,status=2,
            audit_token=[os.getuid(),os.geteuid(),os.getegid(),os.getuid(),os.getgid(),111,100025,4],pid_version=4)
        self.scope['activity'].update(expected_owner=token,admission_files={'parent':{},'candidate':{}})
        capsule=Path(self.scope['execution_capsule']['path'])
        value=json.loads(capsule.read_bytes());value['scope_contract_sha256']=prepare.contract_sha(self.scope)
        if prepare_only:value['authorized_actions']=['prepare']
        capsule.write_bytes(prepare.json_bytes(value));self.scope['execution_capsule']['sha256']=prepare.sha(capsule)
        prepared=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        path=self.root/'activation-continuation.json'
        value=dict(schema='v4.us_hk.execution_capsule.v1',verdict='PASS',authorized_actions=['activate','rollback'],
            prepared_sha256=prepare.sha(self.prepared_path),scope_sha256=prepared['scope_sha256'],
            scope_contract_sha256=prepare.contract_sha(self.scope),
            helper_sha256={name:prepare.sha(Path(__file__).with_name(name)) for name in ('prepare_release.py','activate_release.py')})
        path.write_bytes(prepare.json_bytes(value));pin=dict(path=str(path),sha256=prepare.sha(path))
        return runner,prepared,pin

    def test_continuation_authorizes_immutable_prepare_only_product_both_directions(self):
        runner,prepared,pin=self.continuation_fixture()
        frozen={p:p.read_bytes() for p in (self.prepared_path,self.scope_path,self.candidate/'release-manifest.json')}
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'guarded_transition',return_value={'state':'FENCED_PATH_SELECTED'}) as guarded:
            for direction in ('activate','rollback'):
                result=activate.transition(self.prepared_path,prepare.sha(self.prepared_path),direction,lifecycle,
                    self.evidence/(direction+'-continuation.json'),continuation=pin)
                self.assertEqual(result['state'],'FENCED_PATH_SELECTED')
                self.assertEqual(guarded.call_args.args[-1],pin)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in frozen.items()))
        self.assertEqual(lifecycle.calls,[])
        self.assertEqual(json.loads(Path(self.scope['execution_capsule']['path']).read_bytes())['authorized_actions'],['prepare'])

    def test_continuation_rejects_wrong_product_scope_action_helper_and_pin(self):
        runner,prepared,pin=self.continuation_fixture();path=Path(pin['path']);original=json.loads(path.read_bytes())
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'guarded_transition') as guarded:
            for mutation in ('prepared','scope','action','contract','helper','sha','pinshape'):
                value=deepcopy(original);check=dict(pin)
                if mutation=='prepared':value['prepared_sha256']='0'*64
                elif mutation=='scope':value['scope_sha256']='0'*64
                elif mutation=='action':value['authorized_actions']=['rollback']
                elif mutation=='contract':value['scope_contract_sha256']='0'*64
                elif mutation=='helper':value['helper_sha256']['activate_release.py']='0'*64
                path.write_bytes(prepare.json_bytes(value));check['sha256']=prepare.sha(path)
                if mutation=='sha':check['sha256']='0'*64
                if mutation=='pinshape':check['extra']='unreviewed'
                with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):
                    activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=check)
            self.assertEqual(guarded.call_count,0)
        self.assertEqual(lifecycle.calls,[]);self.assertFalse(self.activation_path.exists())

    def test_continuation_keeps_prepare_only_refusal(self):
        runner,prepared,pin=self.continuation_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'guarded_transition') as guarded:
            with self.assertRaisesRegex(prepare.Stop,'CAPSULE_ACTION_OR_SCOPE_MISMATCH'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path)
            guarded.assert_not_called()

    def test_continuation_legacy_all_action_product_remains_compatible(self):
        runner,prepared,pin=self.continuation_fixture(prepare_only=False)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'guarded_transition',return_value={'state':'LEGACY_FENCED_PATH'}) as guarded:
            for direction in ('activate','rollback'):
                self.assertEqual(activate.transition(self.prepared_path,prepare.sha(self.prepared_path),direction,
                    lifecycle,self.evidence/(direction+'-legacy.json'))['state'],'LEGACY_FENCED_PATH')
                self.assertIsNone(guarded.call_args.args[-1])
        self.assertEqual(lifecycle.calls,[])

    def test_continuation_cli_propagates_complete_pin_without_rewrite(self):
        runner,prepared,pin=self.continuation_fixture()
        argv=['activate_release.py','activate','--prepared',str(self.prepared_path),
            '--prepared-sha256',prepare.sha(self.prepared_path),'--receipt',str(self.activation_path),
            '--continuation',pin['path'],'--continuation-sha256',pin['sha256']]
        with patch.object(sys,'argv',argv),patch.object(activate,'transition',return_value={'state':'CLI_WIRED','live_operations':0}) as transition:
            with patch.object(sys,'stdout',io.StringIO()):activate.main()
            self.assertEqual(transition.call_args.kwargs['continuation'],pin)
            self.assertIsNone(transition.call_args.kwargs['recovery_pin'])
        self.assertFalse(self.activation_path.exists())

    def test_continuation_guardian_intent_propagation_and_revalidation(self):
        runner,prepared,pin=self.continuation_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        token=self.scope['activity']['expected_owner'];captured={}
        def intercept(argv,**kwargs):
            captured.update(json.loads(Path(argv[-2]).read_bytes()))
            self.assertEqual(prepare.sha(argv[-2]),argv[-1]);raise RuntimeError('FAKE_GUARDIAN_SPAWN_INTERCEPTED')
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'signal_identity',return_value=token),patch.object(activate.subprocess,'Popen',side_effect=intercept):
            with self.assertRaisesRegex(RuntimeError,'FAKE_GUARDIAN_SPAWN_INTERCEPTED'):
                activate.guarded_transition(self.scope,prepared,self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,None,pin)
        self.assertEqual(captured['continuation'],pin);self.assertFalse(self.activation_path.exists())
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):
            ops=activate.RealGuardianOps(captured);ops.verify_before_freeze();ops.verify_commit()
            dropped=dict(captured);dropped.pop('continuation')
            with self.assertRaisesRegex(prepare.Stop,'CAPSULE_ACTION_OR_SCOPE_MISMATCH'):activate.RealGuardianOps(dropped)
            path=Path(pin['path']);raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):ops.verify_before_freeze()
            with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):ops.verify_commit()
        self.assertEqual(lifecycle.calls,[])

    def test_continuation_does_not_bypass_prepared_inventory_or_admission(self):
        runner,prepared,pin=self.continuation_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        path=self.candidate/'app'/self.target;raw=path.read_bytes();path.write_bytes(b'candidate drift')
        with patch.object(activate,'guarded_transition') as guarded:
            with self.assertRaisesRegex(prepare.Stop,'CANDIDATE_INVENTORY_DRIFT'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=pin)
            guarded.assert_not_called()
        path.write_bytes(raw)
        with patch.object(activate,'require_real_admission_protocol',side_effect=prepare.Stop('FROZEN_ADMISSION_REQUIRED')),patch.object(activate,'guarded_transition') as guarded:
            with self.assertRaisesRegex(prepare.Stop,'FROZEN_ADMISSION_REQUIRED'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=pin)
            guarded.assert_not_called()
        self.assertEqual(lifecycle.calls,[])

    def test_continuation_cli_requires_complete_pin_pair(self):
        for flags in (['--continuation','/missing'],['--continuation-sha256','0'*64]):
            argv=['activate_release.py','activate','--prepared','/must-not-read','--prepared-sha256','0'*64,'--receipt','/must-not-write',*flags]
            with patch.object(sys,'argv',argv),patch.object(activate,'read_json') as read:
                with self.assertRaisesRegex(prepare.Stop,'CONTINUATION_PIN_PAIR_REQUIRED'):activate.main()
                read.assert_not_called()

    def historical_continuation_fixture(self):
        """Model the accepted 476 preparation followed by a reviewed upgrade."""
        old_sha='47668870ff5e249ea30b46edae919861186a4e822ba54d500d179d239abaefb5'
        current_sha=prepare.sha
        def previous(path):
            return old_sha if Path(path)==Path(prepare.__file__) else current_sha(path)
        with patch.object(prepare,'sha',side_effect=previous):
            runner,prepared,pin=self.continuation_fixture()
        path=Path(pin['path']);value=json.loads(path.read_bytes())
        value['helper_sha256']={name:prepare.sha(Path(__file__).with_name(name))
                               for name in ('prepare_release.py','activate_release.py')}
        path.write_bytes(prepare.json_bytes(value));pin['sha256']=prepare.sha(path)
        self.assertEqual(prepared['helper_sha256'],old_sha)
        self.assertNotEqual(old_sha,prepare.sha(prepare.__file__))
        return runner,prepared,pin

    def test_historical_preparation_current_continuation_injected_guardian_both_directions(self):
        runner,prepared,pin=self.historical_continuation_fixture()
        frozen={p:p.read_bytes() for p in (self.prepared_path,self.scope_path,self.candidate/'release-manifest.json',
                                          Path(self.scope['execution_capsule']['path']))}
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        tokens={111:self.scope['activity']['expected_owner']}
        def identity(pid):
            if pid not in tokens:tokens[pid]=dict(tokens[111],pid=pid,pid_version=pid)
            return tokens[pid]
        statuses={111:2};signals=[]
        def fake_signal(token,signum):
            signals.append((token['pid'],signum));statuses[token['pid']]=4 if signum==signal.SIGSTOP else 5
        def guarded(scope,product,product_path,product_sha,direction,adapter,receipt,recovery,continuation):
            token=identity(runner.pid);statuses[token['pid']]=2
            intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='RELEASE',controller_pid=os.getpid(),
                owner_token=token,prepared={'path':str(product_path),'sha256':product_sha},direction=direction,
                recovery_pin=recovery,journal=str(self.evidence/(direction+'-historical-guardian.json')),
                receipt_path=str(receipt),helper_sha256=prepare.sha(activate.__file__),continuation=continuation)
            with patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):ops=activate.RealGuardianOps(intent)
            read_fd,write_fd=os.pipe()
            os.write(write_fd,b'{"action":"FREEZE"}\n{"action":"COMMIT"}\n{"action":"START"}\n');os.close(write_fd)
            with os.fdopen(read_fd) as control:
                activate.FreezeGuardian(ops,intent,control,io.StringIO()).run()
            return json.loads(receipt.read_bytes())
        # Synthetic owner identities, signals, admission closure and launchctl;
        # real product/capsule/inventory/precheck/CAS/guardian code is exercised.
        with patch.object(activate,'verify_activity_closure'), \
             patch.object(activate,'signal_identity',side_effect=identity), \
             patch.object(activate,'same_process',return_value=True), \
             patch.object(activate,'process_token',side_effect=lambda pid:dict(identity(pid),status=statuses.get(pid,2))), \
             patch.object(activate,'signal_exact_identity',side_effect=fake_signal), \
             patch.object(activate.signal,'pthread_sigmask',return_value=set()), \
             patch.object(activate,'guarded_transition',side_effect=guarded):
            activated=activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,
                self.activation_path,continuation=pin)
            recovery={'path':str(self.activation_path),'sha256':prepare.sha(self.activation_path)}
            rolled=activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'rollback',lifecycle,
                self.rollback_path,continuation=pin,recovery_pin=recovery)
        self.assertEqual((activated['state'],rolled['state']),('ACTIVATED','ROLLED_BACK'))
        self.assertEqual([c[1] for c in runner.commands if c[:1]==['/bin/launchctl'] and c[1]!='print'],
                         ['bootout','bootstrap','bootout','bootstrap'])
        self.assertEqual([s[1] for s in signals],[signal.SIGSTOP,signal.SIGKILL]*2)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in frozen.items()))

    def test_historical_preparation_rejects_original_capsule_and_helper_tamper(self):
        runner,prepared,pin=self.historical_continuation_fixture()
        capsule_path=Path(self.scope['execution_capsule']['path']);raw=capsule_path.read_bytes()
        capsule_path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):activate.verify_prepared(self.scope,prepared)
        capsule_path.write_bytes(raw)
        wrong=dict(prepared,helper_sha256='0'*64)
        with self.assertRaisesRegex(prepare.Stop,'PREPARE_HELPER_DRIFT'):activate.verify_prepared(self.scope,wrong)
        shadow=deepcopy(self.scope);shadow['execution_capsule']['sha256']='0'*64
        with self.assertRaisesRegex(prepare.Stop,'PREPARED_ORIGINAL_SCOPE_DRIFT'):activate.verify_prepared(shadow,prepared)
        for mutation in ('schema','verdict','action','contract','helper','missing_helper','malformed_helper'):
            capsule=json.loads(raw);scope=deepcopy(self.scope);product=deepcopy(prepared)
            if mutation=='schema':capsule['schema']='unknown'
            elif mutation=='verdict':capsule['verdict']='FAIL'
            elif mutation=='action':capsule['authorized_actions']=['activate','rollback']
            elif mutation=='contract':capsule['scope_contract_sha256']='0'*64
            elif mutation=='missing_helper':
                capsule['helper_sha256'].pop('prepare_release.py');product['helper_sha256']=None
            elif mutation=='malformed_helper':
                capsule['helper_sha256']['prepare_release.py']='unknown';product['helper_sha256']='unknown'
            else:capsule['helper_sha256']['prepare_release.py']='0'*64
            capsule_path.write_bytes(prepare.json_bytes(capsule));scope['execution_capsule']['sha256']=prepare.sha(capsule_path)
            self.scope_path.write_bytes(prepare.json_bytes(scope));product['scope_sha256']=prepare.sha(self.scope_path)
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):activate.verify_prepared(scope,product)
        self.assertFalse(self.activation_path.exists());self.assertEqual(runner.commands[1:],[])

    def test_historical_preparation_keeps_current_authority_inventory_and_admission(self):
        runner,prepared,pin=self.historical_continuation_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'guarded_transition') as guarded:
            with self.assertRaisesRegex(prepare.Stop,'CAPSULE_ACTION_OR_SCOPE_MISMATCH'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path)
            path=Path(pin['path']);raw=path.read_bytes();value=json.loads(raw)
            value['helper_sha256']['prepare_release.py']=prepared['helper_sha256'];path.write_bytes(prepare.json_bytes(value))
            with self.assertRaisesRegex(prepare.Stop,'UNREVIEWED_HELPER'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,
                    continuation={'path':str(path),'sha256':prepare.sha(path)})
            path.write_bytes(raw)
            target=self.candidate/'app'/self.target;original=target.read_bytes();target.write_bytes(b'drift')
            with self.assertRaisesRegex(prepare.Stop,'CANDIDATE_INVENTORY_DRIFT'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=pin)
            target.write_bytes(original)
            with patch.object(activate,'require_real_admission_protocol',side_effect=prepare.Stop('FROZEN_ADMISSION_REQUIRED')):
                with self.assertRaisesRegex(prepare.Stop,'FROZEN_ADMISSION_REQUIRED'):
                    activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=pin)
            guarded.assert_not_called()
        self.assertEqual(lifecycle.calls,[]);self.assertFalse(self.activation_path.exists())

    def test_release_prepare_import_with_role_runtime(self):
        runner=self.release_fixture()
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(result['mode'],'RELEASE')
        self.assertEqual(len(runner.commands),1)
        self.assertEqual(runner.commands[0][0],self.scope['runtime_probe']['python']['path'])
        self.assertIn('-I',runner.commands[0]);self.assertIn('-S',runner.commands[0]);self.assertIn('-B',runner.commands[0])

    def test_release_lifecycle_and_rollback_fake_subprocess(self):
        runner=self.release_fixture()
        prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner,sleeper=lambda _:None)
        # The former unfenced fake reload oracle was independently rejected.
        # No real transition may use that path without the guardian profile.
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):
            self.run_transition(lifecycle=lifecycle)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)
        self.assertEqual(lifecycle.calls,[])

    def test_release_capsule_hash_mismatch(self):
        runner=self.release_fixture();self.scope['source_commit']='b'*40
        with self.assertRaisesRegex(prepare.Stop,'CAPSULE_ACTION_OR_SCOPE_MISMATCH'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertFalse(self.candidate.exists());self.assertEqual(runner.commands,[])

    def test_release_interpreter_drift(self):
        runner=self.release_fixture();Path(self.scope['runtime_probe']['python']['path']).write_bytes(b'drift')
        with self.assertRaisesRegex(prepare.Stop,'ROLE_INTERPRETER_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertFalse(self.prepared_path.exists())

    def test_release_running_attempt_prevents_bootout(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        wb=Path(self.scope['activity']['workbench_root']);(wb/'attempts/job.json').write_text(json.dumps(dict(state='RUNNING')))
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        self.assertTrue(activate.activity_snapshot(self.scope,runner)['busy_work'])
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):self.run_transition(lifecycle=lifecycle)
        self.assertEqual(lifecycle.calls,[]);self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_release_pdf_processing_prevents_bootout(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        pdf=Path(self.scope['activity']['data_root'])/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json';pdf.parent.mkdir(parents=True)
        pdf.write_text(json.dumps(dict(schema_version='v4.zsxq_pdf_ingestion_index.v1',documents={'doc':dict(engine_runs={'engine':dict(status='PROCESSING')})})))
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        self.assertTrue(activate.activity_snapshot(self.scope,runner)['busy_work'])
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):self.run_transition(lifecycle=lifecycle)
        self.assertEqual(lifecycle.calls,[])

    def test_release_bootstrap_failure_explicit_partial_rollback(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        prepared=json.loads(self.prepared_path.read_bytes());pin=self.failed_activation_pin(prepared)
        activate.verify_recovery_pin(pin,prepared,prepare.sha(self.prepared_path))
        wrong=dict(pin,sha256='f'*64)
        with self.assertRaises(prepare.Stop):activate.verify_recovery_pin(wrong,prepared,prepare.sha(self.prepared_path))
        self.assertEqual(runner.commands[0][0],self.scope['runtime_probe']['python']['path'])
        self.assertFalse(any(c[0]=='/bin/launchctl' for c in runner.commands))

    def test_release_bootout_failure_restore_without_stopping_healthy_parent(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        prepared=json.loads(self.prepared_path.read_bytes());pin=self.failed_activation_pin(prepared)
        self.plist.write_bytes(Path(prepared['candidate_plist']).read_bytes())
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'process_token',return_value=dict(pid=111,start_sec=1,start_usec=1,status=2)), \
             patch.object(activate,'same_process',return_value=True):
            result=activate.restore_healthy_parent_binding(self.scope,prepared,prepare.sha(self.prepared_path),lifecycle,self.rollback_path,pin)
        self.assertEqual(result['state'],'ROLLED_BACK_BINDING_ONLY');self.assertEqual(self.plist.read_bytes(),self.old_bytes)
        self.assertEqual(lifecycle.calls,[]);self.assertFalse(any(c[0]=='/bin/launchctl' and c[1] in ('bootout','bootstrap') for c in runner.commands))

    def failed_activation_pin(self,prepared):
        self.activation_path.write_bytes(prepare.json_bytes(dict(state='FAILED_REQUIRES_INSPECTION',direction='activate',
            prepared_sha256=prepare.sha(self.prepared_path),after_plist_sha256=prepared['candidate_plist_sha256'],
            helper_sha256=prepare.sha(Path(activate.__file__)))))
        return dict(path=str(self.activation_path),sha256=prepare.sha(self.activation_path))

    def frontend_fixture(self,*,new_dependency=False):
        web=self.parent/'app/apps/web';web.mkdir(parents=True)
        package=dict(scripts={'build':'vite build'},dependencies={'vue':'3.5.40'})
        (web/'package.json').write_text(json.dumps(package));(web/'package-lock.json').write_text('{"lockfileVersion":3}')
        source_package=dict(package,scripts={'build':'vue-tsc && vite build'})
        if new_dependency:source_package['dependencies']={'vue':'different'}
        (self.source/'package.json').write_text(json.dumps(source_package))
        modules=self.root/'node_modules';(modules/'vite/bin').mkdir(parents=True)
        vite=modules/'vite/bin/vite.js';vite.write_bytes(b'fake vite')
        node=self.root/'node';node.write_bytes(b'fake node')
        output=self.evidence/'build-output';stage=self.evidence/'build-source'
        html=b'<script type="module" src="/assets/new.js"></script>'
        asset=b'console.log("new")'
        self.scope['frontend_build']=dict(stage_root=str(stage),output_root=str(output),
            node=dict(path=str(node),sha256=prepare.sha(node),version='v24.19.0'),
            vite=dict(path=str(vite),sha256=prepare.sha(vite),version='vite/7.3.6 fake'),node_modules=str(modules),
            package_lock_sha256=prepare.sha(web/'package-lock.json'),dependency_identity_files=[],
            source_files=[dict(source='package.json',target='package.json',sha256=prepare.sha(self.source/'package.json'))],
            outputs={'manager-selection/index.html':prepare.digest(html),'assets/new.js':prepare.digest(asset)})
        self.scope['overlays'] += [dict(origin='build',source=rel,target='apps/web/dist/'+rel,before_sha256=None,
            sha256=expected,mode=0o644) for rel,expected in self.scope['frontend_build']['outputs'].items()]
        review=json.loads(self.review.read_bytes());review['files']['apps/web/package.json']=prepare.sha(self.source/'package.json')
        review['files'].update({'apps/web/dist/'+rel:value for rel,value in self.scope['frontend_build']['outputs'].items()})
        self.review.write_bytes(prepare.json_bytes(review));self.scope['review_receipts'][0]['sha256']=prepare.sha(self.review)
        self.refresh_parent();self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')
        calls=[]
        def runner(args,**kwargs):
            calls.append(args)
            if args[-1]=='--version':
                text='v24.19.0' if len(args)==2 else 'vite/7.3.6 fake'
            else:
                (output/'manager-selection').mkdir(parents=True);(output/'assets').mkdir()
                (output/'manager-selection/index.html').write_bytes(html);(output/'assets/new.js').write_bytes(asset)
                text='fake build done'
            return SimpleNamespace(returncode=0,stdout=text,stderr='')
        return runner,calls

    def test_frontend_runtime_compatible_script_only_build(self):
        runner,calls=self.frontend_fixture()
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertIn('apps/web/dist/manager-selection/index.html',result['changed_paths'])
        self.assertEqual(len(calls),3)
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        self.assertTrue(manifest['task_overlay']['frontend_build']['package_scripts_changed'])
        self.assertTrue(manifest['task_overlay']['frontend_build']['dependency_sections_unchanged'])

    def test_frontend_new_dependency_requires_lock_reconciliation(self):
        runner,calls=self.frontend_fixture(new_dependency=True)
        with self.assertRaisesRegex(prepare.Stop,'FRONTEND_DEPENDENCY_CHANGE_REQUIRES_LOCK_RECONCILIATION'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[]);self.assertFalse(self.candidate.exists())

    def test_frontend_lock_drift_stops_before_build(self):
        runner,calls=self.frontend_fixture()
        (self.parent/'app/apps/web/package-lock.json').write_bytes(b'wrong lock')
        with self.assertRaisesRegex(prepare.Stop,'PARENT_INVENTORY_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[])

    def test_tampered_retained_vite_config_executes_zero_commands(self):
        runner,calls=self.frontend_fixture()
        config=self.parent/'app/apps/web/vite.config.ts';config.write_text('export default {}')
        self.refresh_parent();self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')
        config.write_text('throw new Error("unreviewed plugin must not execute")')
        with self.assertRaisesRegex(prepare.Stop,'PARENT_INVENTORY_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[])
        self.assertFalse(Path(self.scope['frontend_build']['stage_root']).exists())
        self.assertFalse(self.candidate.exists())

    def test_frontend_copy_race_cannot_execute_changed_config(self):
        runner,calls=self.frontend_fixture()
        config=self.parent/'app/apps/web/vite.config.ts';config.write_text('export default {}')
        self.refresh_parent();self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')
        copy=prepare.shutil.copytree
        def tampered_copy(source,target,**kwargs):
            result=copy(source,target,**kwargs)
            if Path(target)==Path(self.scope['frontend_build']['stage_root']):
                (Path(target)/'vite.config.ts').write_text('throw new Error("raced config")')
            return result
        with patch.object(prepare.shutil,'copytree',tampered_copy):
            with self.assertRaisesRegex(prepare.Stop,'BUILD_STAGE_INVENTORY_DRIFT'):
                prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[]);self.assertFalse(self.candidate.exists())

    def test_overlay_source_drift_stops_before_frontend_commands(self):
        runner,calls=self.frontend_fixture();(self.source/'engine.py').write_bytes(b'unreviewed overlay')
        with self.assertRaisesRegex(prepare.Stop,'SOURCE_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[])

    def test_dependency_drift_stops_before_frontend_commands(self):
        runner,calls=self.frontend_fixture();dependency=self.root/'retained-dependency.py';dependency.write_bytes(b'old pin')
        self.scope['dependencies']=[dict(path=str(dependency),sha256=prepare.sha(dependency))];dependency.write_bytes(b'drift')
        with self.assertRaisesRegex(prepare.Stop,'DEPENDENCY_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(calls,[])

    def test_release_activation_hard_refused_before_plist_or_lifecycle(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):
            self.run_transition(lifecycle=lifecycle)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes);self.assertFalse(lifecycle.calls)

    def test_direct_reload_hard_refused_even_with_idle_snapshot(self):
        runner=self.release_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):
            lifecycle.reload(str(self.candidate/'app'))
        self.assertFalse(lifecycle.calls);self.assertEqual(runner.commands,[])

    def guardian_fixture(self,**options):
        code=options.pop('actor_code','import time; time.sleep(120) # TASK6_GUARDIAN_DUMMY')
        initially_stopped=options.pop('initially_stopped',False)
        code="import sys;print('TASK6_GUARDIAN_DUMMY_READY',flush=True)\n"+code
        actor=subprocess.Popen([sys.executable,'-B','-c',code],
            cwd=self.root,start_new_session=True,stdout=subprocess.PIPE,text=True)
        self.assertEqual(actor.stdout.readline().strip(),'TASK6_GUARDIAN_DUMMY_READY')
        token=activate.signal_identity(actor.pid)
        if initially_stopped:
            os.kill(actor.pid,signal.SIGSTOP)
            deadline=time.monotonic()+5
            while activate.process_token(actor.pid)['status']!=4:
                self.assertLess(time.monotonic(),deadline);time.sleep(.01)
        activity=self.root/'guardian-activity.json';activity.write_bytes(prepare.json_bytes(dict(busy_work=[])))
        binding=self.root/'guardian-binding.json';binding.write_bytes(b'original binding bytes')
        intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='DUMMY_PROCESS_TEST',rehearsal_root=str(self.root),
            controller_pid=os.getpid(),owner_token=token,journal=str(self.root/'guardian-journal.json'),
            activity_path=str(activity),binding_path=str(binding))
        intent.update(options)
        path=self.root/'guardian-intent.json';path.write_bytes(prepare.json_bytes(intent))
        guardian=subprocess.Popen([sys.executable,'-B',str(Path(activate.__file__)),'_guardian',str(path),prepare.sha(path)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        def cleanup():
            if guardian.stdin and not guardian.stdin.closed:guardian.stdin.close()
            try:guardian.wait(timeout=8)
            finally:
                if activate.same_process(token):os.kill(actor.pid,signal.SIGKILL)
                actor.wait(timeout=5)
        self.addCleanup(cleanup)
        return actor,guardian,intent

    def guardian_send(self,guardian,action):
        self.assertTrue(activate.emit_control(guardian.stdin,dict(action=action)))

    def guardian_event(self,guardian,event):
        value=activate.read_control(guardian.stdout,8)
        self.assertIsNotNone(value,guardian.stderr.read() if guardian.poll() is not None else '')
        self.assertEqual(value['event'],event);return value

    def guardian_wait_phase(self,intent,phase):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            path=Path(intent['journal'])
            if path.exists():
                value=json.loads(path.read_bytes())
                if value['phase']==phase:return value
            time.sleep(.01)
        self.fail('guardian phase not reached: '+phase)

    def test_guardian_controller_exception_before_commit_resumes_exact_pid(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.assertEqual(activate.process_token(actor.pid)['status'],4)
        g.stdin.close();self.guardian_event(g,'ABORTED_PRECOMMIT');g.wait(timeout=5)
        self.assertTrue(activate.same_process(intent['owner_token']))
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def test_guardian_busy_accepted_job_resumes_without_bootout(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        Path(intent['activity_path']).write_bytes(prepare.json_bytes(dict(busy_work=['persisted healthy QUEUED job'])))
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'ABORTED_PRECOMMIT')
        value=self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')
        self.assertFalse(value['committed']);self.assertTrue(activate.same_process(intent['owner_token']))
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        self.assertEqual([c['signal'] for c in value['calls']],[signal.SIGSTOP,signal.SIGCONT])

    def test_guardian_partial_claim_is_unknown_and_resumes(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        Path(intent['activity_path']).write_bytes(b'{"busy_work":')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'ABORTED_PRECOMMIT')
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def test_guardian_no_handshake_request_never_stops_owner(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED');g.stdin.close()
        self.guardian_event(g,'ABORTED_PRECOMMIT')
        self.assertEqual(self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')['calls'],[])
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)

    def test_guardian_post_commit_controller_loss_never_resumes_or_bootstraps(self):
        actor,g,intent=self.guardian_fixture(bootout_mode='timeout');self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'BOOTOUT_COMMITTED');g.stdin.close()
        self.guardian_event(g,'OLD_OWNER_EXITED')
        value=self.guardian_wait_phase(intent,'STOPPED_AFTER_COMMIT_NO_BOOTSTRAP');g.wait(timeout=5)
        actor.wait(timeout=5);self.assertTrue(value['committed'])
        self.assertEqual([c['signal'] for c in value['calls']],[signal.SIGSTOP,signal.SIGKILL])
        self.assertFalse((self.root/'bootstrap-called.json').exists())

    def test_guardian_requires_explicit_start_after_confirmed_exit(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'BOOTOUT_COMMITTED')
        self.guardian_event(g,'OLD_OWNER_EXITED');self.assertFalse((self.root/'bootstrap-called.json').exists())
        self.guardian_send(g,'START');self.guardian_event(g,'FINISHED');g.wait(timeout=5)
        self.assertEqual(json.loads((self.root/'bootstrap-called.json').read_bytes()),dict(count=1))

    def test_guardian_bootout_timeout_preserves_restarted_new_pid(self):
        other=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(120) # TASK6_GUARDIAN_DUMMY'],cwd=self.root,start_new_session=True)
        self.addCleanup(lambda: (other.kill(),other.wait()) if other.poll() is None else None)
        token=activate.process_token(other.pid)
        actor,g,intent=self.guardian_fixture(bootout_mode='timeout',restarted_token=token)
        self.guardian_event(g,'OWNED');self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'BOOTOUT_COMMITTED')
        self.guardian_event(g,'INSPECTION_REQUIRED');g.wait(timeout=5)
        self.assertTrue(activate.same_process(token));self.assertNotEqual(activate.process_token(other.pid)['status'],4)
        self.assertFalse((self.root/'bootstrap-called.json').exists())

    def test_guardian_rechecks_frozen_state_before_committing(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        os.kill(actor.pid,signal.SIGCONT)
        deadline=time.monotonic()+2
        while activate.process_token(actor.pid)['status']==4 and time.monotonic()<deadline:time.sleep(.01)
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'ABORTED_PRECOMMIT')
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def test_guardian_survives_controller_sigkill_and_resumes_owner(self):
        # A separate controller owns both the dummy and the guardian pipe.
        # SIGKILL destroys that controller; its independent-session guardian
        # must still CONT the exact original process without a finally block.
        code='''import os,sys,json,subprocess,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import activate_release as a
import prepare_release as p
root=Path(sys.argv[2]);actor=subprocess.Popen([sys.executable,'-B','-c',"import time;print('TASK6_GUARDIAN_DUMMY_READY',flush=True);time.sleep(120)"],cwd=root,start_new_session=True,stdout=subprocess.PIPE,text=True)
assert actor.stdout.readline().strip()=='TASK6_GUARDIAN_DUMMY_READY'
activity=root/'death-activity.json';activity.write_bytes(p.json_bytes({'busy_work':[]}))
binding=root/'death-binding.json';binding.write_bytes(b'original')
intent={'schema':'v4.us_hk.guardian_intent.v1','mode':'DUMMY_PROCESS_TEST','rehearsal_root':str(root),'controller_pid':os.getpid(),'owner_token':a.signal_identity(actor.pid),'journal':str(root/'death-journal.json'),'activity_path':str(activity),'binding_path':str(binding)}
path=root/'death-intent.json';path.write_bytes(p.json_bytes(intent))
g=subprocess.Popen([sys.executable,'-B',a.__file__,'_guardian',str(path),p.sha(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
assert a.read_control(g.stdout,5)['event']=='OWNED'
a.emit_control(g.stdin,{'action':'FREEZE'})
assert a.read_control(g.stdout,5)['event']=='FROZEN_IDLE'
print(json.dumps({'intent':intent,'guardian_token':a.process_token(g.pid)}),flush=True)
time.sleep(120)
'''
        controller=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(activate.__file__).parent),str(self.root)],
            cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        self.addCleanup(lambda: (controller.kill(),controller.wait()) if controller.poll() is None else None)
        metadata=activate.read_control(controller.stdout,8);self.assertIsNotNone(metadata)
        intent=metadata['intent'];token=intent['owner_token']
        def cleanup():
            if activate.same_process(token):os.kill(token['pid'],signal.SIGKILL)
        self.addCleanup(cleanup)
        self.assertEqual(activate.process_token(token['pid'])['status'],4)
        controller.kill();controller.wait(timeout=5)
        value=self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')
        self.assertEqual([c['signal'] for c in value['calls']],[signal.SIGSTOP,signal.SIGCONT])
        self.assertTrue(activate.same_process(token));self.assertNotEqual(activate.process_token(token['pid'])['status'],4)
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original')

    def test_guardian_precommit_binding_exception_restores_before_resume(self):
        actor,g,intent=self.guardian_fixture(binding_error='after_write');self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'ABORTED_PRECOMMIT')
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        self.assertEqual(self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')['calls'][-1]['signal'],signal.SIGCONT)

    def retained_queue_fixture(self):
        runner=self.release_fixture();self.scope['role']='api'
        specs=[dict(kind=kind,root=str(self.root/('retained-'+kind))) for kind in
               ('manual_collection','manual_generation','hkex_announcements')]
        self.scope['activity']['retained_owner_queues']=specs
        return runner,{s['kind']:Path(s['root']) for s in specs}

    def test_retained_manual_and_hkex_accepted_jobs_are_busy(self):
        runner,roots=self.retained_queue_fixture()
        fixtures={
            'manual_collection':('jobs/job.json',dict(origin='CONTROLLED_MANUAL_COLLECTION',status='PENDING')),
            'manual_generation':('manual_generation/20261024.json',dict(schema_version='v4.manual_review_attempt.v1',status='RUNNING')),
            'hkex_announcements':('workspace_announcement_runs/20261024/issuer_subsets/scope/job.json',dict(
                schema_version='v4.manager_research.workspace_attempt.v1',state='RUNNING'))}
        for kind,(relative,value) in fixtures.items():
            with self.subTest(kind=kind):
                path=roots[kind]/relative;path.parent.mkdir(parents=True);path.write_bytes(prepare.json_bytes(value))
                self.assertIn(str(path),activate.activity_snapshot(self.scope,runner)['busy_work'])
                path.unlink()

    def test_retained_partial_or_unknown_owner_record_is_not_idle(self):
        runner,roots=self.retained_queue_fixture();path=roots['hkex_announcements']/'workspace_announcement_runs/20261024/job.json'
        path.parent.mkdir(parents=True);path.write_bytes(b'{"state":')
        with self.assertRaises(json.JSONDecodeError):activate.activity_snapshot(self.scope,runner)
        path.write_bytes(prepare.json_bytes(dict(schema_version='v4.manager_research.workspace_attempt.v1',state='PARTIAL')))
        self.assertIn(str(path),activate.activity_snapshot(self.scope,runner)['busy_work'])
        path.write_bytes(prepare.json_bytes(dict(schema_version='unknown',state='SUCCEEDED',finished_at='2026-10-24T00:00:00Z')))
        with self.assertRaisesRegex(prepare.Stop,'HKEX_ATTEMPT_STATE_UNKNOWN'):activate.activity_snapshot(self.scope,runner)

    def test_retained_terminal_owner_records_are_not_busy(self):
        runner,roots=self.retained_queue_fixture()
        fixtures={
            'manual_collection':('jobs/job.json',dict(origin='CONTROLLED_MANUAL_COLLECTION',status='READY',finished_at='2026-10-24T00:00:00Z')),
            'manual_generation':('manual_generation/20261024.json',dict(schema_version='v4.manual_review_attempt.v1',status='SUCCEEDED')),
            'hkex_announcements':('workspace_announcement_runs/20261024/job.json',dict(
                schema_version='v4.manager_research.workspace_attempt.v1',state='SUCCEEDED',finished_at='2026-10-24T00:00:00Z'))}
        for kind,(relative,value) in fixtures.items():
            if kind=='hkex_announcements':value['sha256']=prepare.digest(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
            path=roots[kind]/relative;path.parent.mkdir(parents=True);path.write_bytes(prepare.json_bytes(value))
        self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],[])

    def test_guardian_explicit_absent_recovery_sends_no_process_signal(self):
        actor,g,intent=self.guardian_fixture(owner_token=None,explicit_absent_recovery=True)
        self.guardian_event(g,'OWNED');self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'BOOTOUT_COMMITTED');self.guardian_event(g,'OLD_OWNER_EXITED')
        self.guardian_send(g,'START');self.guardian_event(g,'FINISHED');g.wait(timeout=5)
        value=self.guardian_wait_phase(intent,'FINISHED');self.assertEqual(value['calls'],[])
        self.assertIsNotNone(activate.process_token(actor.pid));self.assertNotEqual(activate.process_token(actor.pid)['status'],4)

    def test_guardian_freeze_prevents_late_owner_thread_from_starting_work(self):
        code='''# TASK6_GUARDIAN_DUMMY
import threading,time,json
from pathlib import Path
def work():
 while not Path('late.trigger').exists():time.sleep(.005)
 Path('guardian-activity.json').write_text(json.dumps({'busy_work':['healthy accepted job']}))
 Path('late.accepted').write_text('accepted before starting work')
 time.sleep(120)
threading.Thread(target=work,daemon=True).start()
time.sleep(120)
'''
        actor,g,intent=self.guardian_fixture(actor_code=code);self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        (self.root/'late.trigger').write_text('arrived after last idle observation')
        time.sleep(.06);self.assertFalse((self.root/'late.accepted').exists())
        self.guardian_send(g,'COMMIT');self.guardian_event(g,'BOOTOUT_COMMITTED');self.guardian_event(g,'OLD_OWNER_EXITED')
        g.stdin.close();g.wait(timeout=5);actor.wait(timeout=5)
        self.assertFalse((self.root/'late.accepted').exists());self.assertFalse((self.root/'bootstrap-called.json').exists())

    def test_guardian_ownership_handshake_failure_sends_no_stop(self):
        actor,g,intent=self.guardian_fixture(controller_pid=0)
        self.assertIsNone(activate.read_control(g.stdout,5));g.wait(timeout=5)
        self.assertNotEqual(g.returncode,0);self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        self.assertFalse(Path(intent['journal']).exists());self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def test_guardian_preserves_already_stopped_owner_without_claiming_it(self):
        actor,g,intent=self.guardian_fixture(initially_stopped=True);self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'ABORTED_PRECOMMIT');g.wait(timeout=5)
        value=self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')
        self.assertIn('ALREADY_STOPPED_OR_UNKNOWN',value['reason']);self.assertEqual(value['calls'],[])
        self.assertEqual(activate.process_token(actor.pid)['status'],4)
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def test_kernel_audit_identity_rejects_same_pid_wrong_version(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        real=intent['owner_token'];wrong=json.loads(json.dumps(real))
        # The SDK specifies audit-token PID-version accessors. Locate its word
        # through that accessor rather than assuming a private token layout.
        bsm=activate.ctypes.CDLL('/usr/lib/libbsm.dylib')
        bsm.audit_token_to_pidversion.argtypes=[activate._AuditToken]
        bsm.audit_token_to_pidversion.restype=activate.ctypes.c_int
        positions=[]
        for index in range(8):
            changed=list(real['audit_token']);changed[index]=(changed[index]+1)%2**32
            value=activate._AuditToken((activate.ctypes.c_uint32*8)(*changed))
            if bsm.audit_token_to_pidversion(value)!=real['pid_version']:positions.append(index)
        self.assertEqual(len(positions),1);index=positions[0]
        wrong['audit_token'][index]=(wrong['audit_token'][index]+1)%2**32
        for signum in (signal.SIGSTOP,signal.SIGKILL):
            with self.assertRaisesRegex(prepare.Stop,'SIGNAL_AUDIT_IDENTITY_REJECTED'):
                activate.signal_exact_identity(wrong,signum)
            self.assertTrue(activate.same_process(real));self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        with self.assertRaisesRegex(prepare.Stop,'SIGNAL_AUDIT_IDENTITY_REQUIRED'):
            activate.signal_exact_identity(activate.process_token(actor.pid),signal.SIGSTOP)
        g.stdin.close();self.guardian_event(g,'ABORTED_PRECOMMIT');g.wait(timeout=5)

    def test_guardian_sigterm_before_commit_resumes_exact_owner(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        g.terminate();self.guardian_event(g,'ABORTED_PRECOMMIT');g.wait(timeout=5)
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        value=self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')
        self.assertEqual([c['signal'] for c in value['calls']],[signal.SIGSTOP,signal.SIGCONT])
        self.assertEqual(Path(intent['binding_path']).read_bytes(),b'original binding bytes')

    def admission_profile_fixture(self):
        self.scope['role']='api'
        pins={}
        for relative in sorted(activate.ADMISSION_FILES['api']):
            path=self.parent/'app'/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(RETAINED_STORE.read_bytes() if relative=='v4/manager_workbench/store.py' else
                ('source-bound admission fixture '+relative).encode())
            pins[relative]=prepare.sha(path)
        self.scope['activity']={'admission_files':{'parent':pins,'candidate':pins}}
        config=self.root/'manager-config.json';manager=self.root/'manager-research';manager.mkdir()
        workbench=self.root/'state/manager_workbench';workbench.mkdir(parents=True,exist_ok=True)
        config.write_bytes(prepare.json_bytes({'manager_root':str(manager),'state_root':str(workbench)}))
        actual=activate.actual_store_root(self.parent/'app',workbench);(actual/'attempts').mkdir(parents=True)
        self.scope['activity']['workbench_root']=str(actual)
        self.scope['dependencies']=[dict(path=str(config),sha256=prepare.sha(config))]
        base=self.root/'close';review=self.root/'review-state/reviews'
        old=plistlib.loads(self.old_bytes);old['EnvironmentVariables'].update(
            V4_MANAGER_WORKBENCH_CONFIG_PATH=str(config),V35_REVIEW_CORE_CLOSE_ROOT=str(base),
            V4_DAILY_REVIEW_ROOT=str(review),V4_REVIEW_GENERATION_BINDINGS_PATH='retained-bindings',
            V4_REVIEW_GENERATION_BINDINGS_SHA256='f'*64)
        backup=self.evidence/'profile-original.plist';backup.write_bytes(plistlib.dumps(old))
        specs=[dict(kind='manual_collection',root=str(base.parent/'manual_collection')),
            dict(kind='manual_generation',root=str(review.parent)),dict(kind='hkex_announcements',root=str(manager))]
        self.scope['activity']['retained_owner_queues']=specs
        return dict(original_plist=str(backup),candidate_plist=str(backup))

    def test_admission_profile_binds_actual_manual_and_hkex_roots_both_directions(self):
        prepared=self.admission_profile_fixture()
        activate.verify_activity_closure(self.scope,prepared,'activate')
        self.scope['candidate_root']=self.scope['parent_root']
        activate.verify_activity_closure(self.scope,prepared,'rollback')
        self.scope['activity']['retained_owner_queues'][0]['root']=str(self.root/'wrong-manual-root')
        with self.assertRaisesRegex(prepare.Stop,'API_DURABLE_OWNER_QUEUE_CLOSURE_REQUIRED'):
            activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_real_retained_store_root_is_derived_without_constructing_store(self):
        proof=json.loads((SCRATCH/'helper-repair1-admission-source-proof.json').read_bytes())
        for role,owner in proof['roles'].items():
            with self.subTest(role=role):
                config=prepare.read_json(owner['config_path'],owner['config_sha256'])
                app=Path(owner['role_root'])/'app';source=app/'v4/manager_workbench/store.py'
                self.assertEqual(prepare.sha(source),owner['admission_files']['v4/manager_workbench/store.py'])
                self.assertEqual(activate.actual_store_root(app,config['state_root']),Path(config['state_root'])/'manager_workbench')

    def test_actual_nested_store_running_job_cannot_be_classified_idle(self):
        prepared=self.admission_profile_fixture();root=Path(self.scope['activity']['workbench_root'])
        self.assertEqual(root.name,root.parent.name)
        job=root/'attempts/healthy.json';job.write_bytes(prepare.json_bytes({'state':'RUNNING'}))
        activate.verify_activity_closure(self.scope,prepared,'activate')
        self.assertEqual(activate.activity_snapshot(self.scope,None)['busy_work'],[str(job)])
        self.scope['activity']['workbench_root']=str(root.parent)
        with self.assertRaisesRegex(prepare.Stop,'WORKBENCH_ACTIVITY_ROOT_NOT_OWNER_STORE'):
            activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_announcement_guard_requires_and_uses_actual_store_root(self):
        prepared=self.admission_profile_fixture();self.scope['plist']['path']=prepared['original_plist']
        seen=[]
        @contextmanager
        def lock(*args,**kwargs):yield
        @contextmanager
        def announcement(root,**kwargs):seen.append(str(root));yield
        tool=SimpleNamespace(shared_api_release_lock=lock,announcement_flash_cutover_guard=announcement)
        with patch.object(activate,'inventory_tool',return_value=tool):
            with REAL_RELEASE_GUARDS(self.scope):pass
            self.assertEqual(seen,[self.scope['activity']['workbench_root']])
            self.scope['activity']['workbench_root']=str(Path(self.scope['activity']['workbench_root']).parent)
            with self.assertRaisesRegex(prepare.Stop,'GUARD_ROOT_NOT_OWNER_STORE'):
                with REAL_RELEASE_GUARDS(self.scope):pass
        self.assertEqual(len(seen),1)

    def control_pipe(self):
        rd,wr=os.pipe();reader=os.fdopen(rd);writer=os.fdopen(wr,'wb',buffering=0)
        self.addCleanup(reader.close);self.addCleanup(writer.close);return reader,writer

    def test_protocol_reads_coalesced_frames_with_pipe_still_open(self):
        reader,writer=self.control_pipe()
        writer.write(b'{"event":"BOOTOUT_COMMITTED"}\n{"event":"OLD_OWNER_EXITED"}\n')
        self.assertEqual(activate.read_control(reader,.2)['event'],'BOOTOUT_COMMITTED')
        self.assertEqual(activate.read_control(reader,.2)['event'],'OLD_OWNER_EXITED')
        self.assertFalse(writer.closed)

    def test_protocol_accumulates_partial_utf8_without_resetting_deadline(self):
        reader,writer=self.control_pipe();frame=json.dumps({'event':'进度'},ensure_ascii=False).encode()+b'\n'
        cut=frame.index('进'.encode())+1;writer.write(frame[:cut]);first_read=threading.Event();raw_read=os.read
        def observed_read(fd,count):
            value=raw_read(fd,count)
            if fd==reader.fileno():first_read.set()
            return value
        def complete():
            if first_read.wait(1):writer.write(frame[cut:])
        thread=threading.Thread(target=complete);thread.start()
        with patch.object(activate.os,'read',observed_read):self.assertEqual(activate.read_control(reader,1),{'event':'进度'})
        thread.join(timeout=1);self.assertFalse(thread.is_alive())

    def test_protocol_partial_eof_timeout_malformed_and_size_are_not_events(self):
        reader,writer=self.control_pipe();writer.write(b'{"action":')
        with self.assertRaisesRegex(prepare.Stop,'GUARDIAN_CONTROL_TIMEOUT'):activate.read_control(reader,.02)
        writer.close()
        with self.assertRaisesRegex(prepare.Stop,'GUARDIAN_CONTROL_PARTIAL_EOF'):activate.read_control(reader,.2)
        reader,writer=self.control_pipe();writer.close();self.assertIsNone(activate.read_control(reader,.2))
        for raw,error in [(b'{bad}\n',json.JSONDecodeError),(b'\xff\n',UnicodeDecodeError),(b'[]\n',prepare.Stop)]:
            with self.subTest(raw=raw):
                reader,writer=self.control_pipe();writer.write(raw)
                with self.assertRaises(error):activate.read_control(reader,.2)
        reader,writer=self.control_pipe();writer.write(b'x'*33)
        with patch.object(activate,'MAX_CONTROL_BYTES',32):
            with self.assertRaisesRegex(prepare.Stop,'FRAME_TOO_LARGE'):activate.read_control(reader,.2)

    def test_protocol_deadline_is_total_across_dribbled_partial_bytes(self):
        reader,writer=self.control_pipe();waits=[]
        def readiness(readers,writers,errors,timeout):
            waits.append(timeout);return (readers,[],[]) if timeout>0 else ([],[],[])
        with patch.object(activate.time,'monotonic',side_effect=[0,.03,.06,.09,.12]), \
             patch.object(activate.select,'select',side_effect=readiness),patch.object(activate.os,'read',return_value=b' '):
            with self.assertRaisesRegex(prepare.Stop,'GUARDIAN_CONTROL_TIMEOUT'):activate.read_control(reader,.1)
        self.assertEqual(len(waits),4)
        for actual,expected in zip(waits,[.07,.04,.01,0]):self.assertAlmostEqual(actual,expected)

    def test_guardian_coalesced_commands_complete_without_stdin_eof(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        g.stdin.write('{"action":"FREEZE"}\n{"action":"COMMIT"}\n{"action":"START"}\n');g.stdin.flush()
        for event in ['FROZEN_IDLE','BOOTOUT_COMMITTED','OLD_OWNER_EXITED','FINISHED']:self.guardian_event(g,event)
        self.assertFalse(g.stdin.closed);g.wait(timeout=5);actor.wait(timeout=5)
        self.assertEqual(self.guardian_wait_phase(intent,'FINISHED')['phase'],'FINISHED')

    def test_guardian_partial_protocol_eof_before_commit_resumes_owner(self):
        actor,g,intent=self.guardian_fixture();self.guardian_event(g,'OWNED')
        self.guardian_send(g,'FREEZE');self.guardian_event(g,'FROZEN_IDLE')
        g.stdin.write('{"action":');g.stdin.flush();g.stdin.close()
        self.guardian_event(g,'ABORTED_PRECOMMIT');g.wait(timeout=5)
        self.assertNotEqual(activate.process_token(actor.pid)['status'],4)
        value=self.guardian_wait_phase(intent,'ABORTED_PRECOMMIT')
        self.assertIn('PARTIAL_EOF',value['reason']);self.assertEqual(value['calls'][-1]['signal'],signal.SIGCONT)

    def test_admission_profile_rejects_unpinned_config_and_source_drift(self):
        prepared=self.admission_profile_fixture();pin=self.scope['dependencies'].pop()
        with self.assertRaisesRegex(prepare.Stop,'API_OWNER_CONFIG_UNPINNED'):
            activate.verify_activity_closure(self.scope,prepared,'activate')
        self.scope['dependencies'].append(pin)
        relative=next(iter(self.scope['activity']['admission_files']['parent']))
        (self.parent/'app'/relative).write_bytes(b'unknown admission change')
        with self.assertRaisesRegex(prepare.Stop,'ADMISSION_SOURCE_DRIFT'):
            activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_unconfigured_manual_generation_requires_explicit_absence(self):
        prepared=self.admission_profile_fixture();path=Path(prepared['original_plist'])
        old=plistlib.loads(path.read_bytes());del old['EnvironmentVariables']['V4_REVIEW_GENERATION_BINDINGS_SHA256']
        path.write_bytes(plistlib.dumps(old))
        with self.assertRaisesRegex(prepare.Stop,'API_DURABLE_OWNER_QUEUE_CLOSURE_REQUIRED'):
            activate.verify_activity_closure(self.scope,prepared,'activate')
        self.scope['activity']['retained_owner_queues'][1]['root']=None
        activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_admission_profile_rejects_empty_workbench_substitute(self):
        prepared=self.admission_profile_fixture()
        self.scope['activity']['workbench_root']=str(self.root/'empty/manager_workbench')
        with self.assertRaisesRegex(prepare.Stop,'WORKBENCH_ACTIVITY_ROOT_NOT_OWNER_STORE'):
            activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_scheduler_activity_roots_are_bound_to_retained_launcher_environment(self):
        prepared=self.admission_profile_fixture();self.scope['role']='scheduler'
        pins={}
        for relative in sorted(activate.ADMISSION_FILES['scheduler']):
            path=self.parent/'app'/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(RETAINED_STORE.read_bytes() if relative=='v4/manager_workbench/store.py' else
                ('source-bound scheduler fixture '+relative).encode());pins[relative]=prepare.sha(path)
        self.scope['activity']['admission_files']={'parent':pins,'candidate':pins}
        self.scope['activity'].update(data_root=str(self.root/'data'),dispatcher_root=str(self.root/'dispatcher'))
        path=Path(prepared['original_plist']);old=plistlib.loads(path.read_bytes())
        old['EnvironmentVariables'].update(V35_DATA_ROOT=str(self.root/'data'),V35_DISPATCH_LEDGER_ROOT=str(self.root/'dispatcher'))
        path.write_bytes(plistlib.dumps(old));activate.verify_activity_closure(self.scope,prepared,'activate')
        self.scope['activity']['dispatcher_root']=str(self.root/'empty-ledger')
        with self.assertRaisesRegex(prepare.Stop,'SCHEDULER_ACTIVITY_ROOT_NOT_OWNER_ENV'):
            activate.verify_activity_closure(self.scope,prepared,'activate')

    def test_activation_owner_is_bound_to_capsule_start_and_audit_version(self):
        token=dict(pid=111,start_sec=1,start_usec=2,audit_token=[1]*8,pid_version=3,status=2)
        self.scope['activity']={'expected_owner':dict(token)}
        activate.verify_owner_binding(self.scope,{},'p','activate',token,None)
        for key,value in [('start_usec',7),('pid_version',9),('audit_token',[2]*8)]:
            with self.subTest(key=key):
                drift=dict(token,**{key:value})
                with self.assertRaisesRegex(prepare.Stop,'CURRENT_OWNER_NOT_FROZEN_CAPSULE_IDENTITY'):
                    activate.verify_owner_binding(self.scope,{},'p','activate',drift,None)

    def test_rollback_owner_requires_this_activation_receipt_exact_identity(self):
        token=dict(pid=112,start_sec=2,start_usec=3,audit_token=[2]*8,pid_version=4,status=2)
        prepared={'candidate_plist_sha256':'candidate'}
        path=self.evidence/'successful-activation.json'
        value=dict(state='ACTIVATED',direction='activate',prepared_sha256='p',after_plist_sha256='candidate',
            helper_sha256=prepare.sha(Path(activate.__file__)),runtime_kernel_identity=token,
            runtime_readback={'app_root':str(self.candidate/'app')})
        path.write_bytes(prepare.json_bytes(value));pin={'path':str(path),'sha256':prepare.sha(path)}
        activate.verify_owner_binding(self.scope,prepared,'p','rollback',token,pin)
        with self.assertRaisesRegex(prepare.Stop,'ROLLBACK_CURRENT_OWNER_RECEIPT_REQUIRED'):
            activate.verify_owner_binding(self.scope,prepared,'p','rollback',token,None)
        with self.assertRaisesRegex(prepare.Stop,'CURRENT_OWNER_NOT_FROZEN_CAPSULE_IDENTITY'):
            activate.verify_owner_binding(self.scope,prepared,'p','rollback',dict(token,start_usec=9),pin)
        with self.assertRaisesRegex(prepare.Stop,'ROLLBACK_OWNER_RECEIPT_MISMATCH'):
            activate.verify_owner_binding(self.scope,prepared,'other','rollback',token,pin)

    def test_real_adapter_fake_launchctl_complete_fenced_activation_and_rollback(self):
        runner=self.release_fixture();actors=[]
        def actor():
            process=subprocess.Popen([sys.executable,'-B','-c',
                "import time;print('TASK6_GUARDIAN_DUMMY_READY',flush=True);time.sleep(120)"],
                cwd=self.root,start_new_session=True,stdout=subprocess.PIPE,text=True)
            self.assertEqual(process.stdout.readline().strip(),'TASK6_GUARDIAN_DUMMY_READY')
            token=activate.signal_identity(process.pid);actors.append((process,token));return process,token
        def cleanup():
            for process,token in actors:
                if activate.same_process(token):activate.signal_exact_identity(token,signal.SIGKILL)
                process.wait(timeout=5)
        self.addCleanup(cleanup)
        old,old_token=actor();new,new_token=actor();restored,restored_token=actor()
        pins={}
        for relative in sorted(activate.ADMISSION_FILES['scheduler']):
            path=self.parent/'app'/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(RETAINED_STORE.read_bytes() if relative=='v4/manager_workbench/store.py' else
                ('source-bound real adapter fixture '+relative).encode());pins[relative]=prepare.sha(path)
        state_root=self.scope['activity']['workbench_root']
        self.scope['activity']['workbench_root']=str(activate.actual_store_root(self.parent/'app',state_root))
        (Path(self.scope['activity']['workbench_root'])/'attempts').mkdir(parents=True)
        config=self.root/'owner-config.json';config.write_bytes(prepare.json_bytes({'state_root':state_root}))
        self.scope['dependencies'].append({'path':str(config),'sha256':prepare.sha(config)})
        self.scope['activity'].update(expected_pid=old.pid,expected_owner=old_token,admission_files={'parent':pins,'candidate':pins})
        original=plistlib.loads(self.old_bytes);original['EnvironmentVariables'].update(
            V4_MANAGER_WORKBENCH_CONFIG_PATH=str(config),V35_DATA_ROOT=self.scope['activity']['data_root'],
            V35_DISPATCH_LEDGER_ROOT=self.scope['activity']['dispatcher_root'])
        self.old_bytes=plistlib.dumps(original,sort_keys=False);self.plist.write_bytes(self.old_bytes)
        self.scope['plist']['sha256']=prepare.sha(self.plist);self.refresh_parent()
        self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json');self.rearm_capsule('fenced-adapter-controller.json')
        prepared=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner);runner.pid=old.pid
        next_pids=iter([new.pid,restored.pid]);original_runner=runner.__call__
        def commands(args,**kwargs):
            result=original_runner(args,**kwargs)
            if args[:2]==['/bin/launchctl','bootstrap']:runner.pid=next(next_pids)
            return result
        lifecycle.runner=commands
        def run(direction,token,receipt,recovery_pin=None):
            intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='RELEASE',controller_pid=os.getpid(),
                owner_token=token,prepared={'path':str(self.prepared_path),'sha256':prepare.sha(self.prepared_path)},
                direction=direction,recovery_pin=recovery_pin,journal=str(self.evidence/(direction+'-guardian.json')),
                receipt_path=str(receipt),helper_sha256=prepare.sha(Path(activate.__file__)))
            with patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):ops=activate.RealGuardianOps(intent)
            read_fd,write_fd=os.pipe();os.write(write_fd,b'{"action":"FREEZE"}\n{"action":"COMMIT"}\n{"action":"START"}\n');os.close(write_fd)
            with os.fdopen(read_fd) as control,activate.release_guards(self.scope):
                activate.FreezeGuardian(ops,intent,control,io.StringIO()).run()
                ops.finish_journal(intent['journal'])
            value=json.loads(receipt.read_bytes());self.assertIn(value['state'],{'ACTIVATED','ROLLED_BACK'})
            self.assertEqual([s['signal'] for s in value['guardian_signals']],[signal.SIGSTOP,signal.SIGKILL])
            self.assertEqual([c[1] for c in value['lifecycle_calls']],['bootout','bootstrap']);return value
        activated=run('activate',old_token,self.activation_path)
        self.assertEqual(activated['runtime_kernel_identity']['audit_token'],new_token['audit_token'])
        pin={'path':str(self.activation_path),'sha256':prepare.sha(self.activation_path)}
        rolled=run('rollback',new_token,self.rollback_path,pin)
        self.assertEqual(rolled['runtime_kernel_identity']['audit_token'],restored_token['audit_token'])
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_api_dual_env_binding_rejects_stale_inline_root(self):
        runner=self.release_fixture()
        self.scope['role']='api'
        self.scope['plist']['updates']=[u for u in self.scope['plist']['updates'] if u['keys']!=['ProgramArguments',1]]
        old=plistlib.loads(self.old_bytes)
        old['ProgramArguments']=['/usr/bin/env','V35_APP_ROOT='+str(self.parent/'app')]
        with self.assertRaisesRegex(prepare.Stop,'PLIST_INLINE_IDENTITY_NOT_REBOUND'):
            prepare.proposed_plist(plistlib.dumps(old),self.scope,'a'*64)

    def test_release_stale_launcher_cannot_select_old_scheduler(self):
        runner=self.release_fixture()
        old=plistlib.loads(self.old_bytes);self.scope['plist']['updates']=[u for u in self.scope['plist']['updates'] if u['keys']!=['ProgramArguments',1]]
        with self.assertRaisesRegex(prepare.Stop,'SCHEDULER_LAUNCHER_NOT_REBOUND'):
            prepare.proposed_plist(plistlib.dumps(old),self.scope,'a'*64)

    def test_release_unsafe_flag_rejected(self):
        self.release_fixture();old=plistlib.loads(self.old_bytes);old['EnvironmentVariables']['orders_sent']='true'
        with self.assertRaisesRegex(prepare.Stop,'PLIST_UNSAFE_FLAG'):
            prepare.proposed_plist(plistlib.dumps(old),self.scope,'a'*64)

    def dispatcher_claim(self):
        ledger=Path(self.scope['activity']['dispatcher_root']);path=ledger/'claims/live/20261024/0415/dispatch.claim.json'
        path.parent.mkdir(parents=True)
        claim=dict(schema_version='v3_5.dispatch_claim.v1',mode='LIVE',pid=909,run_id='claim-run',business_date='20261024',
                   scheduled_date='20261024',target_date='20261026',slot='0415')
        path.write_text(json.dumps(claim));return ledger,claim

    def test_live_dispatcher_claim_blocks_cutover(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.dispatcher_claim();runner.alive_pids.add(909)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        self.assertTrue(activate.activity_snapshot(self.scope,runner)['busy_work'])
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):self.run_transition(lifecycle=lifecycle)
        self.assertEqual(lifecycle.calls,[])

    def test_completed_dispatcher_receipt_is_not_busy_process(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        ledger,claim=self.dispatcher_claim();runner.alive_pids.add(909)
        receipt={**claim,'schema_version':'v3_5.dispatch_receipt.v1','status':'SUCCEEDED','finished_at':'2026-10-24T04:16:00+08:00',
                 'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
        receipt['ledger_sha256']=prepare.digest(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        p=ledger/'receipts/live/20261024/0415/claim-run.dispatch-receipt.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(receipt))
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner,sleeper=lambda _:None)
        self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],[])
        with self.assertRaisesRegex(prepare.Stop,'REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL'):self.run_transition(lifecycle=lifecycle)

    def test_unknown_dispatcher_receipt_fails_closed(self):
        runner=self.release_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        ledger,claim=self.dispatcher_claim()
        p=ledger/'receipts/live/20261024/0415/claim-run.dispatch-receipt.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(claim))
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with self.assertRaisesRegex(prepare.Stop,'DISPATCH_RECEIPT_UNCONFIRMED'):activate.activity_snapshot(self.scope,runner)
        self.assertEqual(lifecycle.calls,[])

    def test_shared_package_clone_is_finite_no_service_or_extra_app(self):
        target='upstreams/v3_shared_data/shared_data/hk_0_2.py'
        old=self.parent/'app'/target;old.parent.mkdir(parents=True);old.write_bytes(b'old owner')
        src=self.source/'owner.py';src.write_bytes(b'new reviewed owner')
        self.refresh_parent();self.scope.update(role='shared',plist=None,clone_subtree='upstreams/v3_shared_data',
            shared_source_paths=[target],
            parent_manifest_sha256=prepare.sha(self.parent/'release-manifest.json'),preserved_app_files=[],
            overlays=[dict(source='owner.py',target=target,before_sha256=prepare.sha(old),sha256=prepare.sha(src),mode=0o644)])
        self.review.write_bytes(prepare.json_bytes(dict(verdict='PASS',source_commit='a'*40,files={target:prepare.sha(src)})))
        self.scope['review_receipts'][0]['sha256']=prepare.sha(self.review)
        result=self.run_prepare();self.assertEqual(result['changed_paths'],[target])
        self.assertFalse((self.candidate/'app/v4').exists());self.assertFalse((self.evidence/'candidate.plist').exists())

    def native_shared_observation(self):
        observation=json.loads((SCRATCH/'operation-draft/observations.json').read_bytes())['roles']['shared']
        manifest=prepare.read_json(Path(observation['parent_root'])/'release-manifest.json',prepare.SHARED_MANIFEST)
        inventory=prepare.read_json(observation['inventory']['path'],observation['inventory']['sha256'])['entries']
        scope={'role':'shared','parent_root':observation['parent_root']}
        return scope,manifest,inventory

    def test_actual_shared_native_manifest_validates_all_bytes_and_accounts_cache(self):
        scope,manifest,inventory=self.native_shared_observation()
        before,receipt=prepare.validated_parent_inventory(scope,self.tool,manifest,inventory)
        self.assertEqual(len(before),80);self.assertEqual(len(receipt['excluded_generated_cache']),18)
        self.assertEqual(receipt['native_aggregate_sha256'],manifest['shared_package_inventory']['candidate_aggregate_sha256'])
        self.assertNotIn('application_inventory',manifest)

    def test_shared_native_missing_mode_hash_extra_and_aggregate_drift_refused(self):
        scope,manifest,inventory=self.native_shared_observation()
        target=prepare.SHARED_PREFIX+'shared_data/hk_0_2.py'
        for kind in ('missing','mode','hash','extra','aggregate'):
            with self.subTest(kind=kind):
                rows=json.loads(json.dumps(inventory));native=json.loads(json.dumps(manifest))
                row=next(r for r in rows if r['path']==target)
                if kind=='missing':rows.remove(row)
                elif kind=='mode':row['mode']='0777'
                elif kind=='hash':row['sha256']='f'*64
                elif kind=='extra':rows.append(dict(row,path=prepare.SHARED_PREFIX+'scripts/unknown.py'))
                else:native['shared_package_inventory']['candidate_aggregate_sha256']='f'*64
                with self.assertRaises(prepare.Stop):prepare.validated_parent_inventory(scope,self.tool,native,rows)

    def native_shared_fixture(self):
        self.release_fixture();self.parent=self.root/'native-shared-parent';(self.parent/'app').mkdir(parents=True)
        added={prepare.SHARED_PREFIX+'shared_data/'+name+'.py' for name in ('hk_history_resolution','hk_panel_audit','hk_d1_evidence')}
        owner=prepare.SHARED_PREFIX+'shared_data/hk_0_2.py';overlays=[]
        for relative in sorted(prepare.SHARED_SOURCE_PATHS):
            old=self.parent/'app'/relative
            if relative not in added:
                old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(('retained '+relative).encode())
            if relative in added or relative==owner:
                source=self.source/Path(relative).name;source.write_bytes(('reviewed '+relative).encode())
                overlays.append(dict(source=source.name,target=relative,before_sha256=prepare.sha(old) if old.exists() else None,
                    sha256=prepare.sha(source),mode=0o644))
        excluded=[]
        for index in range(7):excluded.append('.runtime/data/frozen-'+str(index)+'.json')
        for index in range(8):excluded.extend(['tests/fixtures/frozen-'+str(index)+'.json','tests/test_old_'+str(index)+'.py'])
        excluded.append('scripts/acquire_unrelated.py')
        for relative in excluded:
            path=self.parent/'app'/prepare.SHARED_PREFIX/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'synthetic retained exclusion')
        entries=self.tool.inventory_tree(self.parent/'app')
        native=[dict(row,path=row['path'][len(prepare.SHARED_PREFIX):]) for row in entries]
        manifest=dict(shared_package_inventory=dict(algorithm='sha256(canonical JSON records; cache, bytecode and node_modules excluded)',
            candidate_entries=native,candidate_entry_count=len(native),candidate_aggregate_sha256=self.tool.inventory_digest(native)))
        (self.parent/'release-manifest.json').write_bytes(prepare.json_bytes(manifest))
        cache=self.parent/'app'/prepare.SHARED_PREFIX/'shared_data/__pycache__/hk_0_2.cpython-313.pyc'
        cache.parent.mkdir();cache.write_bytes(b'synthetic excluded generated cache')
        self.scope.update(role='shared',parent_root=str(self.parent),parent_manifest_sha256=prepare.sha(self.parent/'release-manifest.json'),
            candidate_root=str(self.root/'us-hk-selection-shared-fixture'),clone_subtree='upstreams/v3_shared_data',
            shared_source_paths=sorted(prepare.SHARED_SOURCE_PATHS),plist=None,preserved_app_files=[],overlays=overlays)
        self.candidate=Path(self.scope['candidate_root'])
        self.review.write_bytes(prepare.json_bytes(dict(verdict='PASS',source_commit='a'*40,files={r['target']:r['sha256'] for r in overlays})))
        self.scope['review_receipts']=[{'path':str(self.review),'sha256':prepare.sha(self.review)}]
        wrapper=self.root/'original-shared-wrapper';wrapper.write_bytes(b'retained wrapper identity')
        self.scope['runtime_probe'].update(modules={'shared_data.hk_0_2':owner},updater_relative=prepare.SHARED_PREFIX+'scripts/update_hk_0_2_panel.py',
            retained_search_roots=[],wrapper=dict(path=str(wrapper),sha256=prepare.sha(wrapper),runtime_root='retained-runtime',shared_package_root='retained-shared'))
        patch.object(prepare,'SHARED_PARENT',self.parent).start()
        patch.object(prepare,'SHARED_MANIFEST',self.scope['parent_manifest_sha256']).start()
        self.rearm_capsule('native-shared-controller.json')
        return FakeSubprocess(self.scope),excluded,cache

    def test_native_shared_candidate_is_exact_source_projection_with_exclusion_receipt(self):
        runner,excluded,cache=self.native_shared_fixture();original=(self.parent/'release-manifest.json').read_bytes()
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        entries=self.tool.inventory_tree(self.candidate/'app')
        self.assertEqual({r['path'] for r in entries},prepare.SHARED_SOURCE_PATHS)
        self.assertFalse((self.candidate/'app'/prepare.SHARED_PREFIX/'.runtime').exists())
        self.assertFalse((self.candidate/'app'/prepare.SHARED_PREFIX/'tests').exists())
        self.assertFalse((self.candidate/'app'/prepare.SHARED_PREFIX/'shared_data/__pycache__').exists())
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        receipt=manifest['task_overlay']['parent_inventory_reconciliation']
        self.assertEqual(len(receipt['excluded_native_entries']),len(excluded))
        self.assertEqual(len(receipt['excluded_generated_cache']),1)
        self.assertEqual((self.parent/'release-manifest.json').read_bytes(),original)
        self.assertTrue(manifest['task_overlay']['retained_projection_only']);self.assertIsNone(result['candidate_plist'])

    def test_shared_projection_rejects_non_source_or_unbound_closure(self):
        runner,_,_=self.native_shared_fixture();original=list(self.scope['shared_source_paths'])
        self.scope['shared_source_paths'].append(prepare.SHARED_PREFIX+'.runtime/data/frozen-0.json')
        self.rearm_capsule('non-source-shared-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'SHARED_EXACT_SOURCE_CLOSURE_REQUIRED'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(runner.commands,[]);self.assertFalse(self.candidate.exists())
        self.scope['shared_source_paths']=original[:-1];self.rearm_capsule('missing-source-shared-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'SHARED_EXACT_SOURCE_CLOSURE_REQUIRED'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)

    def scheduler_native_fixture(self):
        self.scope['role']='scheduler';entries=self.tool.inventory_tree(self.parent/'app')
        directories=[self.parent/'app',*[p for p in (self.parent/'app').rglob('*') if p.is_dir() and not p.is_symlink()]]
        rows=entries+[dict(path='.' if p==self.parent/'app' else p.relative_to(self.parent/'app').as_posix(),kind='directory',
            mode=format(p.stat().st_mode&0o7777,'04o')) for p in directories]
        rows.sort(key=lambda r:r['path'])
        (self.parent/'release-manifest.json').write_bytes(prepare.json_bytes(dict(application_inventory=dict(
            entries=rows,entry_count=len(rows),aggregate_sha256=self.tool.inventory_digest(rows)))))
        self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')

    def test_actual_scheduler_native_directory_schema_matches_without_manifest_rewrite(self):
        observation=json.loads((SCRATCH/'operation-draft/observations.json').read_bytes())['roles']['scheduler']
        manifest=prepare.read_json(Path(observation['parent_root'])/'release-manifest.json',observation['parent_manifest_sha256'])
        observed,caches=self.tool._inventory_tree_with_generated_cache(Path(observation['parent_root'])/'app')
        self.assertEqual(observed,prepare.read_json(observation['inventory']['path'],observation['inventory']['sha256'])['entries'])
        before,receipt=prepare.validated_parent_inventory({'role':'scheduler','parent_root':observation['parent_root']},self.tool,manifest,observed,caches)
        self.assertEqual(len(before),872);self.assertEqual(len(receipt['verified_directory_entries']),116)
        self.assertEqual(receipt['native_entry_count'],988)
        self.assertTrue(all(Path(path).name=='__pycache__' for path in receipt['excluded_generated_cache_directories']))

    def test_scheduler_native_schema_prepares_and_preserves_original_manifest(self):
        self.scheduler_native_fixture();original=(self.parent/'release-manifest.json').read_bytes()
        result=self.run_prepare();self.assertEqual(result['changed_paths'],[self.target])
        self.assertEqual((self.parent/'release-manifest.json').read_bytes(),original)
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        self.assertTrue(manifest['task_overlay']['parent_inventory_reconciliation']['verified_directory_entries'])

    def test_scheduler_native_directory_mode_type_extra_and_leaf_drift_refused(self):
        for kind in ('mode','type','extra','leaf'):
            with self.subTest(kind=kind):
                # Each subcase uses a fresh owned fixture to preserve its frozen preimage.
                self.scheduler_native_fixture();directory=self.parent/'app/assets';mode=directory.stat().st_mode&0o7777
                if kind=='mode':directory.chmod(0o700)
                elif kind=='type':directory.rename(self.parent/'app/held-assets');directory.write_bytes(b'not directory')
                elif kind=='extra':(self.parent/'app/new-empty-directory').mkdir()
                else:(self.parent/'app/assets/old.js').write_bytes(b'changed leaf')
                with self.assertRaises(prepare.Stop):self.run_prepare()
                if kind=='mode':directory.chmod(mode)
                elif kind=='type':directory.unlink();(self.parent/'app/held-assets').rename(directory)
                elif kind=='extra':(self.parent/'app/new-empty-directory').rmdir()
                else:(self.parent/'app/assets/old.js').write_bytes(b'old static\n')

    def test_scheduler_generated_cache_container_is_strictly_accounted(self):
        self.scheduler_native_fixture();directory=self.parent/'app/assets/__pycache__';directory.mkdir()
        cache=directory/'old.cpython-314.pyc';cache.write_bytes(b'generated cache')
        # A native .py source is required; a same-looking cache for old.js is not enough.
        with self.assertRaisesRegex(prepare.Stop,'PARENT_CACHE_SOURCE_UNDECLARED'):self.run_prepare()
        cache.unlink()
        with self.assertRaisesRegex(prepare.Stop,'PARENT_DIRECTORY_SET_DRIFT'):self.run_prepare()
        (directory/'unknown.py').write_bytes(b'unmanifested source')
        with self.assertRaisesRegex(prepare.Stop,'PARENT_DIRECTORY_SET_DRIFT'):self.run_prepare()

    def test_shared_package_cannot_overlay_unrelated_business(self):
        self.scope.update(role='shared',clone_subtree='upstreams/v3_shared_data')
        with self.assertRaisesRegex(prepare.Stop,'SHARED_OVERLAY_OUTSIDE_PACKAGE'):self.run_prepare()

    def test_shared_probe_uses_old_wrapper_and_non_main_updater(self):
        runner=self.release_fixture();app=self.root/'probe-app';script=app/'upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py'
        script.parent.mkdir(parents=True);script.write_bytes(b'probe fixture')
        owner=app/'upstreams/v3_shared_data/shared_data/hk_0_2.py';owner.parent.mkdir();owner.write_bytes(b'owner fixture')
        wrapper=self.root/'old-wrapper.sh';wrapper.write_bytes(b'old wrapper fixture')
        shared=self.root/'old-shared-package';shared.mkdir()
        probe=self.scope['runtime_probe'];probe.update(modules={'shared_data.hk_0_2':'upstreams/v3_shared_data/shared_data/hk_0_2.py'},
            updater_relative='upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py',retained_search_roots=[str(shared)],
            wrapper=dict(path=str(wrapper),sha256=prepare.sha(wrapper),runtime_root='old-runtime',shared_package_root=str(shared)))
        self.scope['candidate_root']=str(app.parent)
        # The direct probe app is supplied through a fresh fixture candidate/app.
        (self.root/'probe-candidate').mkdir();app.rename(self.root/'probe-candidate/app');self.scope['candidate_root']=str(self.root/'probe-candidate')
        result=prepare.runtime_probe(self.scope,runner)
        self.assertEqual(runner.commands[-1][0],str(wrapper))
        self.assertIn('_US_HK_OWNER_IMPORT_PROBE',runner.commands[-1][3])
        compile(runner.commands[-1][3],'<owner-import-probe>','exec')
        self.assertIn('subprocess.Popen=denied',runner.commands[-1][3])
        self.assertEqual(result['updater_run_name'],'_US_HK_OWNER_IMPORT_PROBE')

    def rearm_capsule(self,name):
        capsule=self.root/name
        capsule.write_bytes(prepare.json_bytes(dict(schema='v4.us_hk.execution_capsule.v1',verdict='PASS',
            authorized_actions=['prepare','activate','rollback'],scope_contract_sha256=prepare.contract_sha(self.scope),
            helper_sha256={n:prepare.sha(Path(__file__).with_name(n)) for n in ('prepare_release.py','activate_release.py')})))
        self.scope['execution_capsule']=dict(path=str(capsule),sha256=prepare.sha(capsule))

    def hk_child_fixture(self):
        self.release_fixture();self.scheduler_scope=json.loads(json.dumps(self.scope))
        module=self.parent/'app/ops/macos_research_panel_daily.py';module.write_bytes(b'old exact Futu child fixture')
        self.refresh_parent()
        patch.object(prepare,'HK_CHILD_PARENT',self.parent).start()
        patch.object(prepare,'HK_CHILD_MANIFEST',prepare.sha(self.parent/'release-manifest.json')).start()
        patch.object(prepare,'HK_CHILD_MODULE',prepare.sha(module)).start()
        self.candidate=self.root/prepare.HK_CHILD_NAME
        self.scope.update(role='hk-child',candidate_root=str(self.candidate),plist=None,
            parent_manifest_sha256=prepare.sha(self.parent/'release-manifest.json'),preserved_app_files=[])
        rows=[]
        for rel in sorted(prepare.CAPTURE_PATHS):
            source=self.source/Path(rel).name;source.write_bytes(('reviewed capture '+rel).encode())
            old=self.parent/'app'/rel
            rows.append(dict(source=source.name,target=rel,before_sha256=prepare.sha(old) if old.exists() else None,
                             sha256=prepare.sha(source),mode=0o644))
        self.scope['overlays']=rows
        review=self.root/'capture-review.json';review.write_bytes(prepare.json_bytes(dict(verdict='PASS',source_commit='a'*40,
            files={r['target']:r['sha256'] for r in rows})))
        self.scope['review_receipts']=[dict(path=str(review),sha256=prepare.sha(review))]
        wrapper=self.root/'retained-hk-wrapper.sh';wrapper.write_bytes(b'exact old wrapper fixture')
        self.scope['runtime_probe'].update(modules={'ops.macos_research_panel_daily':'ops/macos_research_panel_daily.py',
            'ops._hk_provider_capture':'ops/_hk_provider_capture.py'},wrapper=dict(path=str(wrapper),sha256=prepare.sha(wrapper),
            runtime_root='old-runtime',shared_package_root='old-shared-root'))
        self.rearm_capsule('child-controller.json')
        return FakeSubprocess(self.scope)

    def scheduler_with_child_fixture(self,*,sdk=False):
        runner=self.sdk_fixture() if sdk else self.hk_child_fixture()
        child=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        child_pin=dict(path=str(self.prepared_path),sha256=prepare.sha(self.prepared_path))
        self.scope=self.scheduler_scope;self.candidate=Path(self.scope['candidate_root'])
        self.scope['parent_manifest_sha256']=prepare.sha(self.parent/'release-manifest.json')
        self.scope['hk_child_prepared']=child_pin
        self.evidence=self.root/'scheduler-evidence';self.evidence.mkdir();self.scope['evidence_root']=str(self.evidence)
        self.scope_path=self.root/'scheduler-scope.json';self.prepared_path=self.evidence/'PREPARED.json'
        self.activation_path=self.evidence/'ACTIVATED.json';self.rollback_path=self.evidence/'ROLLBACK.json'
        original=plistlib.loads(self.old_bytes);env=original['EnvironmentVariables']
        prefix='V35_RESEARCH_PANEL_HK_CHILD_'
        env.update({prefix+'APP_ROOT':str(prepare.HK_CHILD_PARENT/'app'),prefix+'RELEASE_ID':prepare.HK_CHILD_PARENT.name,
            prefix+'RELEASE_MANIFEST_PATH':str(prepare.HK_CHILD_PARENT/'release-manifest.json'),
            prefix+'RELEASE_MANIFEST_SHA256':prepare.HK_CHILD_MANIFEST,prefix+'MODULE_SHA256':prepare.HK_CHILD_MODULE})
        env['V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE']=str(self.root/'retained-hk-wrapper.sh')
        for key,value in prepare.hk_child_binding(self.scope).items():
            env.setdefault(key,'old-child-'+key)
            self.scope['plist']['updates'].append(dict(keys=['EnvironmentVariables',key],before=env[key],after=value))
        self.old_bytes=plistlib.dumps(original,sort_keys=False);self.plist.write_bytes(self.old_bytes)
        self.scope['plist']['sha256']=prepare.sha(self.plist)
        self.rearm_capsule('scheduler-child-controller.json')
        return FakeSubprocess(self.scope),child

    def test_hk_child_exact_two_capture_files_and_retained_wrapper(self):
        runner=self.hk_child_fixture();result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(set(result['changed_paths']),prepare.CAPTURE_PATHS)
        self.assertEqual(runner.commands[0][0],self.scope['runtime_probe']['wrapper']['path'])
        self.assertEqual((self.candidate/'app'/self.target).read_bytes(),(self.parent/'app'/self.target).read_bytes())
        self.assertIsNone(result['candidate_plist']);self.assertEqual(len(runner.commands),1)
        self.assertEqual(runner.command_options[0]['env']['PYTHONPATH'],str(self.candidate/'app'))

    def test_hk_child_fixed_base_manifest_required(self):
        self.hk_child_fixture();self.scope['parent_manifest_sha256']='f'*64;self.rearm_capsule('wrong-base-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_FIXED_BASE_REQUIRED'):self.run_prepare()

    def test_hk_child_exact_fourth_root_required(self):
        self.hk_child_fixture();self.scope['candidate_root']=str(self.root/'us-hk-selection-hk-child-other')
        self.rearm_capsule('wrong-root-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_FIXED_BASE_REQUIRED'):self.run_prepare()

    def test_hk_child_extra_source_overlay_forbidden(self):
        self.hk_child_fixture();self.scope['overlays'].append(dict(self.scope['overlays'][0],target=self.target))
        self.rearm_capsule('wrong-overlay-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_EXACT_CAPTURE_OVERLAY_REQUIRED'):self.run_prepare()

    def test_capture_source_cannot_overwrite_api_or_main_scheduler(self):
        for role in ('api','scheduler'):
            with self.subTest(role=role):
                scope=dict(self.scope,role=role,overlays=[dict(self.scope['overlays'][0],target='ops/macos_research_panel_daily.py')])
                with self.assertRaisesRegex(prepare.Stop,'LEGACY_CAPTURE_CANNOT_OVERLAY_MODERN_ROLE'):prepare.precheck(scope,self.tool)

    def test_hk_child_cannot_create_or_reload_service(self):
        runner=self.hk_child_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        with self.assertRaisesRegex(prepare.Stop,'ROLE_HAS_NO_SERVICE'):activate.LaunchctlLifecycle(self.scope,runner=runner)
        self.scope['plist']=dict(path=str(self.plist));self.rearm_capsule('forbidden-plist-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_HAS_NO_SERVICE'):prepare.release_paths(self.scope)

    def test_scheduler_child_five_bindings_and_exact_rollback(self):
        runner,child=self.scheduler_with_child_fixture()
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        proposed=plistlib.loads(Path(result['candidate_plist']).read_bytes())['EnvironmentVariables']
        for key,value in prepare.hk_child_binding(self.scope).items():self.assertEqual(proposed[key],value)
        self.assertEqual(proposed['V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE'],str(self.root/'retained-hk-wrapper.sh'))
        self.assertEqual(Path(result['original_plist']).read_bytes(),self.old_bytes)
        pin=self.failed_activation_pin(result);self.plist.write_bytes(Path(result['candidate_plist']).read_bytes())
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with patch.object(activate,'process_token',return_value=dict(pid=111,start_sec=1,start_usec=1,status=2)), \
             patch.object(activate,'same_process',return_value=True):
            activate.restore_healthy_parent_binding(self.scope,result,prepare.sha(self.prepared_path),lifecycle,self.rollback_path,pin)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes);self.assertFalse(lifecycle.calls)

    def test_scheduler_child_missing_binding_fails_before_plist_write(self):
        runner,_=self.scheduler_with_child_fixture()
        self.scope['plist']['updates']=[u for u in self.scope['plist']['updates'] if u['keys']!=['EnvironmentVariables','V35_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256']]
        self.rearm_capsule('missing-binding-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_FIVE_BINDINGS_REQUIRED'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_scheduler_child_tamper_blocks_activation(self):
        runner,child=self.scheduler_with_child_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        (Path(child['candidate_root'])/'app/ops/_hk_provider_capture.py').write_bytes(b'third-party drift')
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_CANDIDATE_DRIFT'):self.run_transition(lifecycle=lifecycle)
        self.assertFalse(lifecycle.calls);self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_scheduler_child_probe_must_use_original_wrapper_env(self):
        runner,_=self.scheduler_with_child_fixture()
        original=plistlib.loads(self.old_bytes);original['EnvironmentVariables']['V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE']='different-wrapper'
        self.old_bytes=plistlib.dumps(original,sort_keys=False);self.plist.write_bytes(self.old_bytes)
        self.scope['plist']['sha256']=prepare.sha(self.plist);self.rearm_capsule('wrong-wrapper-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_PROBE_WRAPPER_ENV_MISMATCH'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_scheduler_child_unknown_original_binding_stops(self):
        runner,_=self.scheduler_with_child_fixture()
        original=plistlib.loads(self.old_bytes);key='V35_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256'
        original['EnvironmentVariables'][key]='f'*64
        for row in self.scope['plist']['updates']:
            if row['keys']==['EnvironmentVariables',key]:row['before']='f'*64
        self.old_bytes=plistlib.dumps(original,sort_keys=False);self.plist.write_bytes(self.old_bytes)
        self.scope['plist']['sha256']=prepare.sha(self.plist);self.rearm_capsule('unknown-child-controller.json')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_ORIGINAL_BINDING_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)

    def test_role_probe_does_not_inject_extra_shared_search_root(self):
        runner=self.release_fixture();result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        probe=manifest['task_overlay']['runtime_probe']
        self.assertNotIn(str(self.candidate/'app/upstreams/v3_shared_data'),probe['search_roots'])
        self.assertEqual(probe['module_sha256']['v4.manager_workbench.engine'],prepare.sha(self.source/'engine.py'))

    def sdk_fixture(self, *, cp314=False, empty_files=False, empty_native=False):
        """Tiny fake distributions only. No real SDK payload is copied/imported."""
        runner=self.hk_child_fixture();self.scope['runtime_probe']['python']['version']='3.13.12'
        self.scope['runtime_probe']['hk_sdk_canary']=True
        patch.object(prepare,'HK_SDK_PYTHON_SHA',self.scope['runtime_probe']['python']['sha256']).start()
        patch.object(prepare,'HK_SDK_WRAPPER_SHA',self.scope['runtime_probe']['wrapper']['sha256']).start()
        for key in ('HK_SDK_RELEASE_MAP','HK_SDK_RELEASE_COUNT','HK_SDK_RELEASE_BYTES'):
            patch.object(prepare,key,getattr(prepare,key)).start()
        self.sdk_site=self.root/'sdk-source';self.sdk_site.mkdir()
        self.sdk_manifest_path=self.source/'sdk-artifact.json';self.sdk_review=self.root/'sdk-artifact-review.json'
        self.sdk_archive=self.source/'simplejson-cp313.whl'
        native=struct.pack('<8I',0xfeedfacf,0x0100000c,0,6,0,0,0,0)
        if empty_native:native=b''
        speedups='simplejson/_speedups.cpython-'+('314' if cp314 else '313')+'-darwin.so'
        content={'futu_api':{'futu/__init__.py':b'FAKE SDK, not imported\n','futu/common/ft_logger.py':b'fake logger, never imported\n'},
                 'simplejson':{'simplejson/__init__.py':b'fake json\n',speedups:native},
                 'protobuf':{'google/protobuf/__init__.py':b'fake protobuf\n','google/_upb/_message.abi3.so':native},
                 'pycryptodome':{'Crypto/__init__.py':b'fake crypto\n','Crypto/Cipher/_raw_aes.abi3.so':native}}
        if empty_files:
            content['protobuf'].update({'google/protobuf/internal/__init__.py':b'',
                'google/protobuf/empty.pyi':b'','google/protobuf/py.typed':b''})
            content['simplejson']['simplejson/py.typed']=b''
        entries=[];distributions={}
        for name,(version,tag,package) in prepare.HK_SDK_DISTRIBUTIONS.items():
            prefix=name+'-'+version+'.dist-info/'
            metadata='Name: '+name+'\nVersion: '+version+'\n'
            if prepare.HK_SDK_REQUIRES_PYTHON[name]:metadata+='Requires-Python: '+prepare.HK_SDK_REQUIRES_PYTHON[name]+'\n'
            for dependency in prepare.HK_SDK_REQUIREMENTS[name]:metadata+='Requires-Dist: '+dependency+'\n'
            wheel='Wheel-Version: 1.0\nRoot-Is-Purelib: '+('true' if name=='futu_api' else 'false')+'\nTag: '+tag+'\n'
            files=dict(content[name]);files[prefix+'METADATA']=metadata.encode();files[prefix+'WHEEL']=wheel.encode()
            rows=[]
            for relative,raw in files.items():rows.append([relative,'sha256='+base64.urlsafe_b64encode(bytes.fromhex(prepare.digest(raw))).decode().rstrip('='),str(len(raw))])
            rows.append([prefix+'RECORD','','']);stream=io.StringIO();csv.writer(stream,lineterminator='\n').writerows(rows)
            files[prefix+'RECORD']=stream.getvalue().encode()
            dist=dict(name=name,version=version,kind='OFFICIAL_WHEEL' if name=='simplejson' else 'INSTALLED_RECORD',
                metadata_sha256=prepare.digest(files[prefix+'METADATA']),wheel_sha256=prepare.digest(files[prefix+'WHEEL']),
                record_sha256=prepare.digest(files[prefix+'RECORD']))
            if name=='simplejson':
                with zipfile.ZipFile(self.sdk_archive,'w') as z:
                    for relative,raw in files.items():
                        info=zipfile.ZipInfo(relative);info.external_attr=(stat.S_IFREG|(0o664 if relative.endswith('/RECORD') else 0o644))<<16;z.writestr(info,raw)
                dist['archive']=dict(path=str(self.sdk_archive),sha256=prepare.sha(self.sdk_archive))
            else:
                dist['site_root']=str(self.sdk_site)
                for relative,raw in files.items():
                    p=self.sdk_site/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);p.chmod(0o644)
            distributions[name]=dist
            for relative,raw in files.items():
                source=dict(distribution=name,version=version,record_sha256=dist['record_sha256'])
                if name=='simplejson':source.update(kind='OFFICIAL_MATCHING_WHEEL_MEMBER',wheel_path=str(self.sdk_archive),wheel_sha256=dist['archive']['sha256'],member=relative)
                else:source.update(kind='PINNED_EXISTING_DISTRIBUTION_RECORD',path=str(self.sdk_site/relative))
                entries.append(dict(target=relative,sha256=prepare.digest(raw),bytes=len(raw),
                    mode='0664' if name=='simplejson' and relative.endswith('/RECORD') else '0644',before_sha256=None,
                    source=source,artifact_class='DEPENDENCY_ARTIFACT',not_in_git_source_commit=True))
        preserved={}
        for name in ('pandas','numpy'):
            p=Path(self.scope['runtime_probe']['site_packages'][0])/name/'__init__.py';p.parent.mkdir();p.write_bytes(('existing '+name).encode())
            preserved[name]=dict(path=str(p),sha256=prepare.sha(p))
        log_temp=tempfile.TemporaryDirectory(prefix='sdk-log-',dir=SCRATCH);self.addCleanup(log_temp.cleanup)
        log_dir=Path(log_temp.name);log=log_dir/('py_'+prepare.HK_SDK_LOG_DATE.replace('-','_')+'.log');log.write_bytes(b'')
        patch.object(prepare,'HK_SDK_LOG_DIRECTORY',log_dir).start()
        self.scope['runtime_probe']['sdk_log_policy']=fixture_log_policy(log,
            next(r['sha256'] for r in entries if r['target']=='futu/common/ft_logger.py'))
        self.sdk_manifest=dict(schema='v4.us_hk.hk_sdk_artifact.v1',artifact_class='DEPENDENCY_ARTIFACT',not_in_git_source_commit=True,
            entries=entries,distributions=distributions,preserved_modules=preserved,runtime_binding=prepare.hk_sdk_runtime_binding(self.scope))
        self.sdk_resign();return runner

    def sdk_resign(self):
        m=self.sdk_manifest;m.update(entry_count=len(m['entries']),total_bytes=sum(r['bytes'] for r in m['entries']),
            artifact_map_sha256=prepare.sdk_map_sha(m['entries']))
        self.sdk_manifest_path.write_bytes(prepare.json_bytes(m))
        self.sdk_review.write_bytes(prepare.json_bytes(dict(schema='v4.us_hk.hk_sdk_artifact_review.v1',verdict='PASS',
            manifest_sha256=prepare.sha(self.sdk_manifest_path),artifact_map_sha256=m['artifact_map_sha256'],
            entry_count=m['entry_count'],total_bytes=m['total_bytes'],files={r['target']:r['sha256'] for r in m['entries']})))
        self.scope['hk_sdk_artifact']=dict(manifest=dict(path=str(self.sdk_manifest_path),sha256=prepare.sha(self.sdk_manifest_path)),
            review_receipt=dict(path=str(self.sdk_review),sha256=prepare.sha(self.sdk_review)))
        # Fixed production constants are patched solely inside private fake fixtures.
        prepare.HK_SDK_RELEASE_MAP=m['artifact_map_sha256'];prepare.HK_SDK_RELEASE_COUNT=m['entry_count'];prepare.HK_SDK_RELEASE_BYTES=m['total_bytes']
        self.rearm_capsule('sdk-controller.json')

    def test_sdk_exact_artifact_union_original_wrapper_and_canary(self):
        runner=self.sdk_fixture();result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(set(result['changed_paths']),prepare.CAPTURE_PATHS|{r['target'] for r in self.sdk_manifest['entries']})
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        self.assertEqual(len(manifest['task_overlay']['source_overlays']),2)
        self.assertEqual(stat.S_IMODE((self.candidate/'app/simplejson-4.1.1.dist-info/RECORD').stat().st_mode),0o664)
        self.assertEqual(manifest['task_overlay']['hk_sdk_artifact_map_sha256'],self.sdk_manifest['artifact_map_sha256'])
        self.assertEqual(runner.commands[0][0],self.scope['runtime_probe']['wrapper']['path'])
        self.assertEqual(runner.command_options[0]['env']['PYTHONPATH'],str(self.candidate/'app'))
        self.assertEqual(manifest['task_overlay']['runtime_probe']['sdk_canary']['protobuf_backend'],'upb')
        self.assertIn("(frame.f_globals.get('__name__') or '').startswith('futu.')",runner.commands[0][3])
        self.assertIn("frame.f_code.co_name=='__init__'",runner.commands[0][3])
        ast.parse(runner.commands[0][3])

    def test_sdk_group_write_only_exact_simplejson_record(self):
        self.sdk_fixture();row=next(r for r in self.sdk_manifest['entries'] if r['target']=='futu/__init__.py')
        row['mode']='0664';self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_FILE_SIZE_MODE'):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())

    def test_sdk_record_bound_empty_files_preserved_in_fake_candidate(self):
        runner=self.sdk_fixture(empty_files=True)
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(result['state'],'PREPARED')
        empty=[r for r in self.sdk_manifest['entries'] if r['bytes']==0];self.assertEqual(len(empty),4)
        for row in empty:
            target=self.candidate/'app'/row['target']
            self.assertEqual(target.read_bytes(),b'');self.assertEqual(prepare.sha(target),prepare.digest(b''))
            self.assertIn(row['target'],result['changed_paths'])

    def test_sdk_empty_size_hash_record_and_source_mismatch_still_rejected(self):
        self.sdk_fixture(empty_files=True)
        row=next(r for r in self.sdk_manifest['entries'] if r['target']=='google/protobuf/py.typed')
        original=deepcopy(row)
        for mutation in ('negative','size','hash','record','mode'):
            row.clear();row.update(deepcopy(original))
            if mutation=='negative':row['bytes']=-1
            elif mutation=='size':row['bytes']=1
            elif mutation=='hash':row['sha256']='0'*64
            elif mutation=='record':row['target']='google/protobuf/unrecorded.pyi'
            else:row['mode']='0664'
            self.sdk_resign()
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):prepare.hk_sdk_artifact(self.scope)
        row.clear();row.update(original);self.sdk_resign()
        Path(row['source']['path']).write_bytes(b'drift')
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_SOURCE_SIZE'):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())

    def test_sdk_record_bound_empty_native_still_rejected_before_candidate(self):
        runner=self.sdk_fixture(empty_native=True)
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_NATIVE_HEADER'):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists());self.assertEqual(runner.commands,[])

    def test_sdk_alias_metadata_rejected_before_runner(self):
        runner=self.sdk_fixture();site=Path(self.scope['runtime_probe']['site_packages'][0])
        alias=self.root/'retained-hk-site-alias';alias.symlink_to(site,target_is_directory=True)
        self.scope['runtime_probe']['site_packages']=[str(alias)]
        self.sdk_manifest['runtime_binding']=prepare.hk_sdk_runtime_binding(self.scope)
        for name,item in self.sdk_manifest['preserved_modules'].items():item['path']=str(alias/name/'__init__.py')
        self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'SYMLINK_OR_ALIAS'):prepare.hk_sdk_artifact(self.scope)
        with self.assertRaisesRegex(prepare.Stop,'SYMLINK_OR_ALIAS'):prepare.runtime_probe(self.scope,runner)
        self.assertEqual(runner.commands,[]);self.assertFalse(self.candidate.exists())

    def test_sdk_canonical_metadata_resolves_alias_without_relaxing_guards(self):
        runner=self.sdk_fixture();probe=self.scope['runtime_probe'];wrapper=deepcopy(probe['wrapper']);python=deepcopy(probe['python'])
        site=Path(probe['site_packages'][0]);alias=self.root/'retained-hk-site-alias';alias.symlink_to(site,target_is_directory=True)
        probe['search_roots']=[str(site),str(self.candidate/'app')]
        self.sdk_manifest['runtime_binding']=prepare.hk_sdk_runtime_binding(self.scope)
        self.sdk_manifest['runtime_binding']['site_packages']=[str(alias)];self.sdk_resign()
        # A scope-only correction cannot bypass the independently bound envelope.
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_RETAINED_RUNTIME_BINDING_DRIFT'):prepare.hk_sdk_artifact(self.scope)
        self.sdk_manifest['runtime_binding']=prepare.hk_sdk_runtime_binding(self.scope)
        for name,item in self.sdk_manifest['preserved_modules'].items():item['path']=str(alias/name/'__init__.py')
        self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_PANDAS_NUMPY_OWNER'):prepare.hk_sdk_artifact(self.scope)
        for name,item in self.sdk_manifest['preserved_modules'].items():item['path']=str((alias/name/'__init__.py').resolve(strict=True))
        self.sdk_manifest['provenance']={'runtime_alias_resolution':{'original_alias':str(alias),'resolved_path':str(site)}}
        self.sdk_resign();result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertEqual(result['state'],'PREPARED');self.assertEqual(probe['wrapper'],wrapper);self.assertEqual(probe['python'],python)
        self.assertEqual(runner.commands[0][0],wrapper['path'])
        expected=json.loads(runner.commands[0][-1])
        for name in ('pandas','numpy'):self.assertEqual(expected[name],str(site/name/'__init__.py'))
        manifest=json.loads((self.candidate/'release-manifest.json').read_bytes())
        self.assertEqual(manifest['task_overlay']['runtime_probe']['origins']['pandas'],str(site/'pandas/__init__.py'))

    def test_sdk_other_roles_rejected_without_candidate_or_commands(self):
        self.sdk_fixture()
        for role in ('api','scheduler','shared'):
            self.scope['role']=role
            with self.assertRaisesRegex(prepare.Stop,'HK_SDK_ONLY_CHILD_ROLE'):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())

    def test_sdk_independent_receipt_required(self):
        self.sdk_fixture();review=json.loads(self.sdk_review.read_bytes());review['verdict']='PENDING'
        self.sdk_review.write_bytes(prepare.json_bytes(review));self.scope['hk_sdk_artifact']['review_receipt']['sha256']=prepare.sha(self.sdk_review)
        with self.assertRaisesRegex(prepare.Stop,'INDEPENDENT_REVIEW'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_unknown_extra_and_shadow_targets_rejected(self):
        self.sdk_fixture();original=deepcopy(self.sdk_manifest)
        for target in ('pandas/__init__.py','numpy/__init__.py','pyarrow/__init__.py','futu/sitecustomize.py','futu/x.pth','futu/__pycache__/x.pyc','../outside.py'):
            self.sdk_manifest=deepcopy(original);row=deepcopy(self.sdk_manifest['entries'][0]);row['target']=target
            self.sdk_manifest['entries'].append(row);self.sdk_resign()
            with self.assertRaises(prepare.Stop):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())

    def test_sdk_missing_record_entry_rejected(self):
        self.sdk_fixture();self.sdk_manifest['entries'].pop(0);self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'INCOMPLETE_DISTRIBUTION'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_parent_empty_root_collision_rejected(self):
        self.sdk_fixture();(self.parent/'app/futu').mkdir()
        with self.assertRaisesRegex(prepare.Stop,'PARENT_ROOT_COLLISION'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_source_symlink_and_payload_drift_rejected(self):
        self.sdk_fixture();p=self.sdk_site/'futu/__init__.py';raw=p.read_bytes();p.write_bytes(b'tampered')
        with self.assertRaisesRegex(prepare.Stop,'SOURCE_SIZE|PAYLOAD_DRIFT'):prepare.hk_sdk_artifact(self.scope)
        p.unlink();other=self.root/'same-sdk.py';other.write_bytes(raw);p.symlink_to(other)
        with self.assertRaisesRegex(prepare.Stop,'SYMLINK_OR_ALIAS'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_cp314_native_and_unsupported_wheel_tag_rejected(self):
        self.sdk_fixture(cp314=True)
        with self.assertRaisesRegex(prepare.Stop,'NATIVE_ABI'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_cp314_distribution_tag_rejected(self):
        self.sdk_fixture();dist=self.sdk_manifest['distributions']['protobuf'];p=self.sdk_site/'protobuf-7.35.1.dist-info/WHEEL'
        p.write_text(p.read_text().replace('cp310-abi3','cp314-cp314'));dist['wheel_sha256']=prepare.sha(p);self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'WHEEL_ABI_TAG'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_requires_python_and_new_dependency_rejected(self):
        self.sdk_fixture();dist=self.sdk_manifest['distributions']['protobuf'];p=self.sdk_site/'protobuf-7.35.1.dist-info/METADATA';raw=p.read_bytes()
        p.write_text(p.read_text().replace('>=3.10','>=3.14'));dist['metadata_sha256']=prepare.sha(p);self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'REQUIRES_PYTHON'):prepare.hk_sdk_artifact(self.scope)
        p.write_bytes(raw+b'Requires-Dist: unapproved\n');dist['metadata_sha256']=prepare.sha(p);self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'NEW_DEPENDENCY'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_wrong_native_architecture_rejected_without_loading(self):
        with self.assertRaisesRegex(prepare.Stop,'ARM64_REQUIRED'):
            prepare.sdk_native_arm64(struct.pack('<8I',0xfeedfacf,0x01000007,0,6,0,0,0,0))

    def test_sdk_unknown_wheel_member_rejected(self):
        self.sdk_fixture()
        with zipfile.ZipFile(self.sdk_archive,'a') as z:z.writestr('unapproved.py',b'extra')
        value=prepare.sha(self.sdk_archive);self.sdk_manifest['distributions']['simplejson']['archive']['sha256']=value
        for row in self.sdk_manifest['entries']:
            if row['source']['distribution']=='simplejson':row['source']['wheel_sha256']=value
        self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'UNKNOWN_WHEEL_MEMBER'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_failed_native_canary_never_marks_prepared(self):
        fake=self.sdk_fixture()
        def runner(argv,**kwargs):
            value=fake(argv,**kwargs);body=json.loads(value.stdout);body['sdk_canary']['protobuf_backend']='python'
            value.stdout=json.dumps(body);return value
        with self.assertRaisesRegex(prepare.Stop,'NATIVE_CANARY_FAILURE'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertFalse(self.prepared_path.exists())

    def test_sdk_wrong_loaded_dependency_owner_rejected(self):
        fake=self.sdk_fixture()
        def runner(argv,**kwargs):
            value=fake(argv,**kwargs);body=json.loads(value.stdout);body['origins']['futu']='unapproved'
            value.stdout=json.dumps(body);return value
        with self.assertRaisesRegex(prepare.Stop,'ROLE_RUNTIME_PROBE_MISMATCH'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        self.assertFalse(self.prepared_path.exists())

    def test_sdk_pandas_numpy_are_pinned_to_retained_site(self):
        self.sdk_fixture();self.sdk_manifest['preserved_modules']['pandas']['path']=str(self.sdk_site/'futu/__init__.py');self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'PANDAS_NUMPY_OWNER'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_exact_release_map_cannot_be_replaced_by_source_review(self):
        self.sdk_fixture();prepare.HK_SDK_RELEASE_MAP='0'*64
        with self.assertRaisesRegex(prepare.Stop,'RELEASE_EXACT_ARTIFACT'):prepare.hk_sdk_artifact(self.scope)

    def test_sdk_candidate_artifact_tamper_blocks_scheduler_dependency(self):
        fake=self.sdk_fixture();child_scope=deepcopy(self.scope)
        prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        pin=dict(path=str(self.prepared_path),sha256=prepare.sha(self.prepared_path))
        (self.candidate/'app/futu/__init__.py').write_bytes(b'tampered candidate SDK')
        scheduler=dict(self.scheduler_scope,hk_child_prepared=pin)
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_CANDIDATE_DRIFT'):prepare.hk_child_binding(scheduler)

    def test_sdk_malformed_artifact_cannot_escape_hash_pin(self):
        self.sdk_fixture();self.sdk_manifest_path.write_bytes(b'{}')
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):prepare.hk_sdk_artifact(self.scope)


    def test_sdk_provider_and_thread_guard_with_fake_frames_only(self):
        fake=self.sdk_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        tree=ast.parse(fake.commands[0][3]);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sdk_profile')
        def denied():raise prepare.Stop('SDK_GUARD_DENIED')
        namespace={'denied':denied};exec(compile(ast.Module(body=[node],type_ignores=[]),'<pure-sdk-profile-guard>','exec'),namespace)
        for module,qualified,name in [('futu.quote.open_quote_context','OpenQuoteContext.__init__','__init__'),('threading','Thread.start','start')]:
            frame=SimpleNamespace(f_globals={'__name__':module},f_code=SimpleNamespace(co_qualname=qualified,co_name=name))
            with self.assertRaisesRegex(prepare.Stop,'SDK_GUARD_DENIED'):namespace['sdk_profile'](frame,'call',None)
        with self.assertRaisesRegex(prepare.Stop,'SDK_GUARD_DENIED'):
            namespace['sdk_profile'](None,'c_call',SimpleNamespace(__module__='_thread',__name__='start_new_thread'))

    def test_sdk_audit_guard_denies_write_network_process_without_operations(self):
        fake=self.sdk_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        tree=ast.parse(fake.commands[0][3]);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sdk_audit')
        def denied():raise prepare.Stop('SDK_GUARD_DENIED')
        namespace={'denied':denied,'os':os};exec(compile(ast.Module(body=[node],type_ignores=[]),'<pure-sdk-audit-guard>','exec'),namespace)
        for event,args in [('open',('unused','w',os.O_WRONLY)),('socket.connect',()),('socket.getaddrinfo',()),('socket.gethostbyname',()),('subprocess.Popen',()),('os.rename',())]:
            with self.assertRaisesRegex(prepare.Stop,'SDK_GUARD_DENIED'):namespace['sdk_audit'](event,args)
        namespace['sdk_audit']('open',('unused','r',os.O_RDONLY))
        namespace['sdk_audit']('os.listdir',())


    def test_sdk_copy_inventory_race_cannot_seal_unreviewed_bytes(self):
        fake=self.sdk_fixture();original=self.tool.inventory_tree;changed=[]
        def inventory(root):
            if Path(root)==self.candidate/'app' and not changed:
                (self.candidate/'app/futu/__init__.py').write_bytes(b'raced SDK bytes')
                changed.append(True)
            return original(root)
        with patch.object(prepare,'inventory_tool',return_value=self.tool),patch.object(self.tool,'inventory_tree',side_effect=inventory):
            with self.assertRaisesRegex(prepare.Stop,'HK_SDK_CANDIDATE_CONTENT_DRIFT'):
                prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        self.assertFalse(self.prepared_path.exists());self.assertEqual(fake.commands,[])

    def test_sdk_valid_native_closure_checked_before_candidate_creation(self):
        self.sdk_fixture();self.sdk_manifest['entries']=[r for r in self.sdk_manifest['entries'] if r['target']!='simplejson/_speedups.cpython-313-darwin.so']
        # Incomplete RECORD is already a stronger pre-copy refusal.
        self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'INCOMPLETE_DISTRIBUTION'):prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())


    def logger_guard_fixture(self):
        log_dir=self.root/'logger-fixture';log_dir.mkdir()
        log=log_dir/('py_'+prepare.HK_SDK_LOG_DATE.replace('-','_')+'.log');log.write_bytes(b'')
        source=self.root/'fixture-ft-logger.py'
        source.write_text("import logging,logging.handlers\nclass FTLog:\n def __init__(self):\n  self.fileHandler=logging.handlers.TimedRotatingFileHandler(log_path,when='H',interval=24,backupCount=20)\n  self.log=logging.getLogger('fixture');self.log.addHandler(self.fileHandler);self.log.setLevel(logging.INFO)\nlogger=FTLog()\n")
        policy=fixture_log_policy(log,prepare.sha(source))
        tree=ast.parse(Path(prepare.__file__).read_bytes());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='runtime_probe')
        literals={node.targets[0].id:ast.literal_eval(node.value) for node in function.body if isinstance(node,ast.Assign) and
            isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('script','sdk_guard')}
        return log,source,policy,literals

    def run_logger_guard(self,fixture,*,before='',action='',prefix='',policy=None):
        log,source,pin,literals=fixture;pin=pin if policy is None else policy
        script=prefix+'\n'+literals['script'].split('sys.path[:0]=')[0]
        script+='\n_log_policy=json.loads('+repr(json.dumps(pin))+');_log_source='+repr(str(source))+'\n'+prepare.SDK_LOG_GUARD
        script+='\n'+literals['sdk_guard']+'\n'+before
        script+="\nfrom types import ModuleType\nfixture=ModuleType('futu.common.ft_logger');fixture.log_path="+repr(str(log))+"\nsys.modules[fixture.__name__]=fixture\nexec(compile(old_open(_log_source,'rb').read(),_log_source,'exec'),fixture.__dict__)\n"
        script+=action+'\nprint(json.dumps(_sdk_log_result()))\n'
        self.assertEqual(prepare.sha(SDK_LOG_TEST_PYTHON),'95fb891ec36d4022bdf62172f9d3c757fb3c7b1669a274cacc87fe261a535b7e')
        result=subprocess.run([str(SDK_LOG_TEST_PYTHON),'-I','-S','-B','-c',script],cwd=self.root,capture_output=True,text=True,timeout=10)
        return result

    def test_sdk_logger_genuine_handler_exact_existing_append(self):
        fixture=self.logger_guard_fixture();before=dict(os.environ)
        result=self.run_logger_guard(fixture,action="fixture.logger.log.warning('fixture append')")
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stderr,'')
        receipt=json.loads(result.stdout);prepare.verify_sdk_log_result(fixture[2],receipt)
        self.assertEqual(receipt['handler_opens'],1);self.assertGreater(receipt['observed_size_delta'],0)
        self.assertLessEqual(receipt['after']['size'],65536);self.assertEqual(os.environ,before)

    def test_sdk_logger_wrong_date_path_mode_stack_and_reopen(self):
        fixture=self.logger_guard_fixture();log,source,policy,_=fixture
        wrong=deepcopy(policy);wrong['date']='2000-01-01'
        self.assertNotEqual(self.run_logger_guard(fixture,policy=wrong).returncode,0)
        for action in ("open(_log_policy['path'],'a')", "open(_log_policy['path'],'w')", "open(_log_policy['path'],'a+')",
                       "open(_log_policy['path'],'r+')", "open(_log_policy['path'],'ab')", "open(_log_policy['path'],'x')",
                       "open(_log_policy['path']+'.other','a')", "open(_log_policy['path'],'r')", "io.FileIO(_log_policy['path'],'a')",
                       "os.open(_log_policy['path'],os.O_WRONLY|os.O_APPEND)", "fixture.logger.fileHandler._open()",
                       "os.mkdir(_log_policy['path']+'.dir')", "os.rename(_log_policy['path'],_log_policy['path']+'.rotated')",
                       "os.unlink(_log_policy['path'])", "os.truncate(_log_policy['path'],0)", "fixture.logger.fileHandler.doRollover()"):
            with self.subTest(action=action):
                result=self.run_logger_guard(fixture,action=action)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertTrue(log.is_file());self.assertEqual(log.stat().st_size,0)
                self.assertFalse(Path(str(log)+'.other').exists());self.assertFalse(Path(str(log)+'.rotated').exists())
        # A first open from an ordinary caller has no original constructor stack.
        result=self.run_logger_guard(fixture,before="open(_log_policy['path'],'a')")
        self.assertNotEqual(result.returncode,0);self.assertIn('HK_SDK_LOG_GUARD_REFUSED',result.stderr)

    def test_sdk_logger_symlink_hardlink_mode_inode_and_parent_identity(self):
        fixture=self.logger_guard_fixture();log,source,policy,_=fixture
        for field in ('inode','uid','mode','nlink'):
            wrong=deepcopy(policy);wrong['identities'][str(log)][field]='0600' if field=='mode' else -1
            with self.subTest(field=field):self.assertNotEqual(self.run_logger_guard(fixture,policy=wrong).returncode,0)
        wrong=deepcopy(policy);wrong['identities'][str(log.parent)]['inode']=-1
        self.assertNotEqual(self.run_logger_guard(fixture,policy=wrong).returncode,0)
        linked=log.parent/'link';os.link(log,linked)
        self.assertNotEqual(self.run_logger_guard(fixture).returncode,0);linked.unlink()
        backup=log.parent/'real';log.rename(backup);log.symlink_to(backup)
        self.assertNotEqual(self.run_logger_guard(fixture).returncode,0);log.unlink();backup.rename(log)
        old_dir=log.parent;replacement=self.root/'moved-log-dir';old_dir.rename(replacement);old_dir.symlink_to(replacement,target_is_directory=True)
        self.assertNotEqual(self.run_logger_guard(fixture).returncode,0)
        old_dir.unlink();replacement.rename(old_dir)

    def test_sdk_logger_open_descriptor_swap_is_rejected_before_write(self):
        fixture=self.logger_guard_fixture();other=self.root/'other-log';other.write_bytes(b'')
        prefix='import os\n_racefd=os.open('+repr(str(other))+',os.O_WRONLY|os.O_APPEND)'
        before="""
_original_descriptor_open=old_os_open
def _raced_descriptor_open(path,flags,*args,**kwargs):
 fd=_original_descriptor_open(path,flags,*args,**kwargs)
 if path==_log_base and flags==_log_flags:
  os.close(fd);return os.dup(_racefd)
 return fd
old_os_open=_raced_descriptor_open
"""
        result=self.run_logger_guard(fixture,prefix=prefix,before=before)
        self.assertNotEqual(result.returncode,0);self.assertIn('HK_SDK_LOG_GUARD_REFUSED',result.stderr)
        self.assertEqual(other.stat().st_size,0);self.assertEqual(fixture[0].stat().st_size,0)

    def test_sdk_logger_missing_file_directory_and_first_unsafe_modes_never_create(self):
        fixture=self.logger_guard_fixture();log,source,policy,literals=fixture;original=source.read_text()
        for mode in ('w','x','a+','r+','ab'):
            source.write_text(original.replace("logging.handlers.TimedRotatingFileHandler(log_path,when='H',interval=24,backupCount=20)",
                'logging.FileHandler(log_path,mode='+repr(mode)+')'))
            changed=deepcopy(policy);changed['sdk_logger_sha256']=prepare.sha(source)
            with self.subTest(mode=mode):
                result=self.run_logger_guard(fixture,policy=changed)
                self.assertNotEqual(result.returncode,0);self.assertIn('HK_SDK_LOG_GUARD_REFUSED',result.stderr)
                self.assertEqual(log.stat().st_size,0)
        source.write_text(original);log.unlink()
        result=self.run_logger_guard(fixture)
        self.assertNotEqual(result.returncode,0);self.assertFalse(log.exists())
        log.parent.rmdir();result=self.run_logger_guard(fixture)
        self.assertNotEqual(result.returncode,0);self.assertFalse(log.parent.exists())

    def test_sdk_logger_cap_platform_failure_and_existing_guards(self):
        fixture=self.logger_guard_fixture()
        result=self.run_logger_guard(fixture,action="fixture.logger.log.warning('X'*100000)")
        self.assertTrue(result.returncode!=0 or result.stderr)
        self.assertLessEqual(fixture[0].stat().st_size,65536)
        # Subsequent limits bind the current baseline, never expand the 64KiB grant.
        result=self.run_logger_guard(fixture,prefix="import resource\ndef _no_limit(*a):raise OSError('FIXTURE_LIMIT_UNAVAILABLE')\nresource.setrlimit=_no_limit")
        self.assertNotEqual(result.returncode,0);self.assertIn('FIXTURE_LIMIT_UNAVAILABLE',result.stderr)
        for action in ("socket.create_connection(('127.0.0.1',1))", "socket.getaddrinfo('localhost',1)",
                       "subprocess.Popen(['unused'])", "import threading;threading.Thread(target=lambda:None).start()"):
            with self.subTest(action=action):self.assertNotEqual(self.run_logger_guard(fixture,action=action).returncode,0)
        provider="class OpenQuoteContext:\n def __init__(self):pass\nOpenQuoteContext()"
        result=self.run_logger_guard(fixture,action="exec(compile("+repr(provider)+",'<fake-provider>','exec'),{'__name__':'futu.quote.fixture'})")
        self.assertNotEqual(result.returncode,0);self.assertIn('IMPORT_PROBE_WRITE_OR_NETWORK_FORBIDDEN',result.stderr)

    def test_sdk_log_policy_envelope_and_probe_receipt(self):
        fake=self.sdk_fixture();policy=self.scope['runtime_probe']['sdk_log_policy']
        result=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        probe=json.loads((self.candidate/'release-manifest.json').read_bytes())['task_overlay']['runtime_probe']
        self.assertEqual(result['state'],'PREPARED');self.assertEqual(probe['command_kind'],'GUARDED_SDK_IMPORT_EXACT_EXISTING_LOG_APPEND_ONLY_NO_NETWORK')
        self.assertEqual(probe['sdk_log_side_effect']['observed_size_delta'],0)
        self.assertEqual(fake.command_options[0]['env']['HOME'],os.environ['HOME'])
        self.assertEqual(fake.command_options[0]['env'].get('CODEX_HOME'),os.environ.get('CODEX_HOME'))
        ast.parse(fake.commands[0][3]);self.assertEqual(self.sdk_manifest['runtime_binding']['sdk_log_policy'],policy)
        self.scope['runtime_probe']['sdk_log_policy']=dict(policy,max_append_bytes=65537)
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_RETAINED_RUNTIME_BINDING_DRIFT'):prepare.hk_sdk_artifact(self.scope)
        self.sdk_manifest['runtime_binding']=prepare.hk_sdk_runtime_binding(self.scope);self.sdk_resign()
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_LOG_POLICY_OUTSIDE_GRANT'):prepare.hk_sdk_artifact(self.scope)
        self.scope['runtime_probe']['sdk_log_policy']=policy
        for key,value in [('created',True),('created',0),('handler_opens',True),('handler_opens',2),('enforced_size_limit',65537),('sdk_logger_sha256','0'*64),('before',None)]:
            malformed=fixture_log_result(policy);malformed[key]=value
            with self.subTest(key=key),self.assertRaises(prepare.Stop):prepare.verify_sdk_log_result(policy,malformed)

    def test_sdk_log_probe_failure_stderr_and_stdout_saved_once(self):
        fake=self.sdk_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        for kind in ('nonzero','stderr','stdout','timeout','native','logreceipt'):
            evidence=self.evidence/kind;evidence.mkdir();scope=dict(self.scope,evidence_root=str(evidence))
            def runner(*args,**kwargs):
                if kind=='timeout':raise subprocess.TimeoutExpired(['not-recorded'],60,output=b'partial',stderr=b'timeout detail')
                value=fake(*args,**kwargs)
                if kind=='nonzero':value.returncode=1;value.stderr='E'*70000
                if kind=='stderr':value.stderr='unexpected logger error'
                if kind=='stdout':value.stdout='unexpected console line\n'+value.stdout
                if kind in ('native','logreceipt'):
                    body=json.loads(value.stdout)
                    if kind=='native':body['sdk_canary']['provider_initialized']=True
                    else:body['sdk_log_side_effect']['handler_opens']=2
                    value.stdout=json.dumps(body)
                return value
            with self.subTest(kind=kind),self.assertRaises((prepare.Stop,subprocess.TimeoutExpired)):
                prepare.runtime_probe(scope,runner)
            receipt=json.loads((evidence/'sdk-probe-failure.json').read_bytes())
            self.assertFalse(receipt['log_content_read']);self.assertFalse(receipt['retry_authorized'])
            self.assertLessEqual((evidence/'sdk-probe-stderr.txt').stat().st_size,65536)
            self.assertNotIn('argv',receipt);self.assertNotIn('environment',receipt)
        self.assertFalse((self.evidence/'nonzero/PREPARED.json').exists())

    def test_sdk_log_lifecycle_prepared_binding_ignores_mutable_log_state(self):
        fake=self.sdk_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        pin={'hk_child_prepared':{'path':str(self.prepared_path),'sha256':prepare.sha(self.prepared_path)}}
        baseline=prepare.hk_child_binding(pin);log=Path(self.scope['runtime_probe']['sdk_log_policy']['path'])
        frozen={p:p.read_bytes() for p in (self.prepared_path,self.scope_path,self.candidate/'release-manifest.json')}
        (log.parent/'py_2026_10_25.log').write_bytes(b'own fixture only')
        artifact=prepare.hk_sdk_artifact(self.scope)
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_LOG_IDENTITY_DRIFT'):
            prepare.sdk_log_policy(self.scope,artifact,live=True)
        with patch.object(prepare,'sdk_log_identity',side_effect=AssertionError('MUTABLE_LOG_READ_DURING_PREPARED_VERIFY')):
            self.assertEqual(prepare.hk_child_binding(pin),baseline)
        log.chmod(0o600)
        self.assertEqual(prepare.hk_child_binding(pin),baseline)
        log.unlink()
        self.assertEqual(prepare.hk_child_binding(pin),baseline)
        with patch.object(prepare,'sdk_log_identity',side_effect=prepare.Stop('LIVE_CHECK_REACHED')):
            with self.assertRaisesRegex(prepare.Stop,'LIVE_CHECK_REACHED'):prepare.runtime_probe(self.scope,fake)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in frozen.items()))

    def test_sdk_log_lifecycle_genuine_fixture_live_gate_remains_strict(self):
        fixture=self.logger_guard_fixture();log,source,policy,_=fixture
        scope={'role':'hk-child','runtime_probe':{'sdk_log_policy':policy}}
        artifact={'entries':[{'target':'futu/common/ft_logger.py','sha256':prepare.sha(source)}]}
        with patch.object(prepare,'HK_SDK_LOG_DIRECTORY',log.parent):
            prepare.sdk_log_policy(scope,artifact,live=True)
            result=self.run_logger_guard(fixture,action="fixture.logger.log.warning('lifecycle fixture')")
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stderr,'')
            sealed=json.loads(result.stdout)
            (log.parent/'unrelated-nextday.log').write_bytes(b'own fixture only')
            prepare.sdk_log_policy(scope,artifact);prepare.verify_sdk_log_result(policy,sealed)
            with self.assertRaisesRegex(prepare.Stop,'HK_SDK_LOG_IDENTITY_DRIFT'):
                prepare.sdk_log_policy(scope,artifact,live=True)
            future=SimpleNamespace(date=SimpleNamespace(today=lambda:SimpleNamespace(isoformat=lambda:'2026-10-25')))
            with patch.object(prepare,'datetime',future):
                prepare.sdk_log_policy(scope,artifact)
                with self.assertRaisesRegex(prepare.Stop,'LIVE_ENV_OR_DATE_DRIFT'):prepare.sdk_log_policy(scope,artifact,live=True)

    def test_sdk_log_lifecycle_fresh_prepare_cannot_skip_live_grant(self):
        fake=self.sdk_fixture();log=Path(self.scope['runtime_probe']['sdk_log_policy']['path'])
        (log.parent/'unrelated-nextday.log').write_bytes(b'own fixture only')
        with self.assertRaisesRegex(prepare.Stop,'HK_SDK_LOG_IDENTITY_DRIFT'):
            prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        self.assertFalse(self.candidate.exists());self.assertFalse(self.prepared_path.exists());self.assertEqual(fake.commands,[])

    def test_sdk_log_lifecycle_sealed_canary_and_immutable_tamper_rejected(self):
        fake=self.sdk_fixture();prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        pin={'hk_child_prepared':{'path':str(self.prepared_path),'sha256':prepare.sha(self.prepared_path)}}
        artifact=prepare.hk_sdk_artifact(self.scope);manifest_path=self.candidate/'release-manifest.json'
        manifest=json.loads(manifest_path.read_bytes());sealed=manifest['task_overlay']['runtime_probe']
        for mutation in ('absent','kind','map','native','policy','opens','origins','hashes'):
            receipt=deepcopy(sealed)
            if mutation=='absent':receipt=None
            elif mutation=='kind':receipt['command_kind']='READ_ONLY_IMPORT_NO_NETWORK'
            elif mutation=='map':receipt['hk_sdk_artifact_map_sha256']='0'*64
            elif mutation=='native':receipt['sdk_canary']['provider_initialized']=True
            elif mutation=='policy':receipt['sdk_log_side_effect']['policy_sha256']='0'*64
            elif mutation=='opens':receipt['sdk_log_side_effect']['handler_opens']=2
            elif mutation=='origins':receipt['origins']['futu']='wrong-owner'
            else:receipt['module_sha256']['futu']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):
                prepare.verify_prepared_sdk_probe(self.scope,artifact,receipt)
        source=prepare.source_file(self.scope,next(row for row in self.scope['overlays'] if row['target']=='ops/_hk_provider_capture.py'))
        targets=[manifest_path,self.candidate/'app/futu/common/ft_logger.py',source,
                 self.sdk_manifest_path,Path(self.scope['execution_capsule']['path'])]
        for target in targets:
            raw=target.read_bytes();target.write_bytes(raw+b' ')
            try:
                with self.subTest(path=str(target)),self.assertRaises(prepare.Stop):prepare.hk_child_binding(pin)
            finally:target.write_bytes(raw)
        self.assertTrue(prepare.hk_child_binding(pin))

    def test_sdk_log_lifecycle_scheduler_and_both_guardian_verifiers(self):
        fake,_=self.scheduler_with_child_fixture(sdk=True)
        prepared=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=fake)
        child=prepare.read_json(self.scope['hk_child_prepared']['path'],self.scope['hk_child_prepared']['sha256'])
        child_scope=prepare.read_json(child['scope_path'],child['scope_sha256'])
        log=Path(child_scope['runtime_probe']['sdk_log_policy']['path']);(log.parent/'benign.log').write_bytes(b'own fixture')
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=fake)
        with patch.object(prepare,'sdk_log_identity',side_effect=AssertionError('MUTABLE_LOG_READ_DURING_LIFECYCLE')), \
             patch.object(activate,'require_real_admission_protocol'),patch.object(activate,'verify_activity_closure'), \
             patch.object(activate,'verify_owner_binding'):
            activate.verify_prepared(self.scope,prepared)
            for direction in ('activate','rollback'):
                self.plist.write_bytes(Path(prepared['original_plist'] if direction=='activate' else prepared['candidate_plist']).read_bytes())
                fake.cwd=str(Path(self.scope['parent_root'] if direction=='activate' else self.scope['candidate_root'])/'app')
                intent=dict(direction=direction,prepared={'path':str(self.prepared_path),'sha256':prepare.sha(self.prepared_path)},
                    owner_token={'pid':111},journal=str(self.evidence/(direction+'-lifecycle.json')),
                    receipt_path=str(self.evidence/(direction+'-receipt.json')),helper_sha256=prepare.sha(activate.__file__))
                with patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):ops=activate.RealGuardianOps(intent)
                ops.verify_before_freeze();ops.verify_commit()
        self.assertEqual(lifecycle.calls,[])

    def activation_uid_scope_fixture(self):
        path=SCRATCH.parent/'operation-execution/api-r2/PREPARED.json'
        product=prepare.read_json(path,'16b9b1c965345054b9f3649a87de296f74c85c94fb4e0b40ee0c8b3b6b1e8fed')
        return prepare.read_json(product['scope_path'],product['scope_sha256']),product,path

    def test_activation_uid_actual_sealed_scope_derives_gui_uid_and_pid(self):
        scope,product,path=self.activation_uid_scope_fixture();original=deepcopy(scope)
        runner=SimpleNamespace(calls=[])
        def forbidden(*args,**kwargs):runner.calls.append(args);raise AssertionError('LIFECYCLE_OPERATION_FORBIDDEN')
        lifecycle=activate.LaunchctlLifecycle(scope,runner=forbidden)
        self.assertEqual(lifecycle.domain,'gui/501')
        self.assertEqual(activate.lifecycle_identity(scope),{'uid':501,'pid':scope['activity']['expected_owner']['pid']})
        self.assertNotIn('uid',scope['activity']);self.assertNotIn('expected_pid',scope['activity'])
        explicit=deepcopy(scope);explicit['activity'].update(uid=501,expected_pid=scope['activity']['expected_owner']['pid'])
        self.assertEqual(activate.LaunchctlLifecycle(explicit,runner=forbidden).domain,'gui/501')
        self.assertEqual(scope,original);self.assertEqual(runner.calls,[]);self.assertEqual(lifecycle.calls,[])

    def test_activation_uid_conflicts_and_invalid_frozen_identity_rejected(self):
        scope,_,_=self.activation_uid_scope_fixture()
        for field,values in [('uid',[None,True,'501',502]),('expected_pid',[None,True,'42989',42990])]:
            for value in values:
                changed=deepcopy(scope);changed['activity'][field]=value
                with self.subTest(field=field,value=value),self.assertRaises(prepare.Stop):activate.LaunchctlLifecycle(changed)
        for mutation in ('missing-owner','none-owner','short','bool-word','negative-word','overflow','uid','euid','ruid','pid','version','missing-version'):
            changed=deepcopy(scope);activity=changed['activity'];owner=activity['expected_owner'];words=owner['audit_token']
            if mutation=='missing-owner':activity.pop('expected_owner')
            elif mutation=='none-owner':activity['expected_owner']=None
            elif mutation=='short':owner['audit_token']=words[:-1]
            elif mutation=='bool-word':words[0]=True
            elif mutation=='negative-word':words[0]=-1
            elif mutation=='overflow':words[0]=2**32
            elif mutation=='uid':words[0]=502
            elif mutation=='euid':words[1]=502
            elif mutation=='ruid':words[3]=502
            elif mutation=='pid':owner['pid']+=1
            elif mutation=='version':owner['pid_version']+=1
            else:owner.pop('pid_version')
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):activate.LaunchctlLifecycle(changed)
        with patch.object(activate.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(prepare.Stop,'CURRENT_USER_INVALID'):activate.LaunchctlLifecycle(scope)

    def test_activation_uid_original_prepare_only_and_current_continuation(self):
        scope,product,path=self.activation_uid_scope_fixture();original=prepare.authorized_capsule(scope,'prepare')
        self.assertEqual(original['authorized_actions'],['prepare'])
        self.assertEqual(original['helper_sha256']['prepare_release.py'],prepare.sha(prepare.__file__))
        with self.assertRaisesRegex(prepare.Stop,'CAPSULE_ACTION_OR_SCOPE_MISMATCH'):
            activate.authorize_transition(scope,product,prepare.sha(path),'activate')
        capsule=dict(schema='v4.us_hk.execution_capsule.v1',verdict='PASS',authorized_actions=['activate','rollback'],
            scope_contract_sha256=prepare.contract_sha(scope),prepared_sha256=prepare.sha(path),scope_sha256=product['scope_sha256'],
            helper_sha256={'prepare_release.py':prepare.sha(prepare.__file__),'activate_release.py':prepare.sha(activate.__file__)})
        target=self.evidence/'uid-continuation.json';target.write_bytes(prepare.json_bytes(capsule));pin={'path':str(target),'sha256':prepare.sha(target)}
        for direction in ('activate','rollback'):
            self.assertEqual(activate.authorize_transition(scope,product,prepare.sha(path),direction,pin),capsule)
        for helper in ('prepare_release.py','activate_release.py'):
            changed=deepcopy(capsule);changed['helper_sha256'][helper]='0'*64;target.write_bytes(prepare.json_bytes(changed))
            with self.subTest(helper=helper),self.assertRaisesRegex(prepare.Stop,'UNREVIEWED_HELPER'):
                activate.authorize_transition(scope,product,prepare.sha(path),'activate',{'path':str(target),'sha256':prepare.sha(target)})

    def test_activation_uid_guardian_verifier_uses_same_frozen_pid(self):
        scope,product,path=self.activation_uid_scope_fixture();pointer=self.evidence/'uid-fixture.plist';pointer.write_bytes(b'fixture binding')
        owner=scope['activity']['expected_owner'];previous=str(Path(scope['parent_root'])/'app')
        ops=SimpleNamespace(scope=scope,prepared=product,direction='activate',intent=dict(prepared={'sha256':prepare.sha(path)},owner_token=owner),
            pointer=pointer,expected=prepare.sha(pointer),previous=previous,
            lifecycle=SimpleNamespace(identity=lambda:dict(state='running',app_root=previous,pid=owner['pid'])))
        with patch.object(activate,'authorize_transition'),patch.object(activate,'verify_prepared'):
            activate.RealGuardianOps.verify_before_freeze(ops)
            changed=deepcopy(scope);changed['activity']['expected_pid']=owner['pid']+1;ops.scope=changed
            with self.assertRaisesRegex(prepare.Stop,'EXPLICIT_IDENTITY_CONFLICT'):activate.RealGuardianOps.verify_before_freeze(ops)

    def test_sdk_wrong_python_wrapper_or_search_roots_cannot_fallback(self):
        self.sdk_fixture();original=deepcopy(self.scope['runtime_probe'])
        for mutation in ('python','wrapper','search_roots','site_packages','environment','updater_relative'):
            self.scope['runtime_probe']=deepcopy(original);probe=self.scope['runtime_probe']
            if mutation=='python':probe['python']['version']='3.14.6'
            elif mutation=='wrapper':probe['wrapper']['sha256']='0'*64
            elif mutation=='search_roots':probe['search_roots']=[str(self.source)]
            elif mutation=='site_packages':probe['site_packages'].append(str(self.source))
            elif mutation=='environment':probe['environment']={'V35_SHARED_PACKAGE_ROOT':'unapproved'}
            else:probe['updater_relative']='ops/macos_research_panel_daily.py'
            with self.assertRaisesRegex(prepare.Stop,'HK_SDK_RETAINED_HK_RUNTIME_REQUIRED|HK_SDK_RETAINED_RUNTIME_BINDING_DRIFT'):
                prepare.hk_sdk_artifact(self.scope)
        self.assertFalse(self.candidate.exists())



    def api_shared_lock_fixture(self):
        self.scope['role']='api'
        self.plist=self.root/'com.lexi.v35.api-only.plist';self.plist.write_bytes(self.old_bytes)
        self.scope['plist']['path']=str(self.plist)
        store=self.parent/'app/v4/manager_workbench/store.py';store.write_bytes(b'guard fixture store')
        root=self.root/'owner-store';root.mkdir()
        self.scope['activity']=dict(workbench_root=str(root),admission_files={'parent':{
            'v4/manager_workbench/store.py':prepare.sha(store)}})
        path=self.source/'deployment/api_module_contracts.json';path.parent.mkdir()
        path.write_bytes((WT/'deployment/api_module_contracts.json').read_bytes())
        return {'path':str(path),'sha256':prepare.sha(path)},root

    def test_guardian_shared_lock_pinned_metadata_uses_original_guard(self):
        pin,root=self.api_shared_lock_fixture();tool=prepare.inventory_tool(self.tool_pin);calls=[]
        @contextmanager
        def owned(path,**kwargs):
            calls.append((str(path),kwargs));yield SimpleNamespace(status='ACQUIRED')
        @contextmanager
        def announcement(path,**kwargs):
            self.assertEqual(path,root);calls.append(('announcement',kwargs));yield
        original=tool.shared_api_release_lock
        tool.announcement_flash_cutover_guard=announcement
        with patch.object(activate,'inventory_tool',return_value=tool),patch.object(activate,'pinned_owner_config',return_value={'state_root':str(root)}), \
             patch.object(activate,'actual_store_root',return_value=root),patch.dict(sys.modules,{'infrastructure.interprocess_lock':SimpleNamespace(owned_interprocess_lock=owned)}):
            with REAL_RELEASE_GUARDS(self.scope,api_shared_lock_contract=pin):calls.append(('body',{}))
        self.assertIs(tool.shared_api_release_lock,original)
        self.assertEqual(calls[0],(str(self.plist.with_name('.com.lexi.v35.api-only.release.lock')),
            {'timeout_seconds':2,'timeout_message':'API_RELEASE_SHARED_LOCK_BUSY'}))
        self.assertEqual([c[0] for c in calls[1:]],['announcement','body'])
        self.assertFalse(self.plist.with_name('.com.lexi.v35.api-only.release.lock').exists())
        # A fresh tool remains bound to its missing immutable-parent metadata.
        with self.assertRaises(FileNotFoundError):prepare.inventory_tool(self.tool_pin).module_role_contract()

    def test_guardian_shared_lock_bad_pin_metadata_and_busy_are_rejected(self):
        pin,root=self.api_shared_lock_fixture();path=Path(pin['path']);raw=path.read_bytes()
        for mutation in ('sha','shape','path','schema','label','plist_name','lock_name','host','port','role'):
            check=dict(pin);value=json.loads(raw);scope=deepcopy(self.scope)
            if mutation=='sha':check['sha256']='0'*64
            elif mutation=='shape':check['extra']=True
            elif mutation=='path':
                other=self.root/'unapproved-contract.json';other.write_bytes(raw);check['path']=str(other)
            elif mutation=='schema':value['schema_version']='wrong'
            elif mutation=='role':scope['role']='scheduler'
            else:value['roles']['gateway'][mutation]='wrong'
            path.write_bytes(prepare.json_bytes(value))
            if mutation not in ('sha','path'):check['sha256']=prepare.sha(path)
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):
                with REAL_RELEASE_GUARDS(scope,api_shared_lock_contract=check):self.fail('BAD_METADATA_ENTERED')
        path.write_bytes(raw);tool=prepare.inventory_tool(self.tool_pin)
        @contextmanager
        def busy(*args,**kwargs):raise RuntimeError('API_RELEASE_SHARED_LOCK_BUSY');yield
        with patch.object(activate,'inventory_tool',return_value=tool),patch.object(activate,'pinned_owner_config',return_value={'state_root':str(root)}), \
             patch.object(activate,'actual_store_root',return_value=root),patch.dict(sys.modules,{'infrastructure.interprocess_lock':SimpleNamespace(owned_interprocess_lock=busy)}):
            with self.assertRaisesRegex(RuntimeError,'API_RELEASE_SHARED_LOCK_BUSY'):
                with REAL_RELEASE_GUARDS(self.scope,api_shared_lock_contract=pin):self.fail('BUSY_ENTERED')

    def test_guardian_shared_lock_continuation_authority_reaches_guard(self):
        runner,prepared,pin=self.continuation_fixture();path=Path(pin['path']);value=json.loads(path.read_bytes())
        metadata={'path':str(self.source/'deployment/api_module_contracts.json'),'sha256':'a'*64}
        value['api_shared_lock_contract']=metadata;path.write_bytes(prepare.json_bytes(value));pin['sha256']=prepare.sha(path)
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        for direction in ('activate','rollback'):
            self.plist.write_bytes(Path(prepared['original_plist'] if direction=='activate' else prepared['candidate_plist']).read_bytes())
            intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='RELEASE',direction=direction,
                prepared={'path':str(self.prepared_path),'sha256':prepare.sha(self.prepared_path)},continuation=pin,
                owner_token={'pid':111},journal=str(self.evidence/(direction+'-metadata-journal.json')),
                receipt_path=str(self.evidence/(direction+'-metadata-receipt.json')),helper_sha256=prepare.sha(activate.__file__))
            with patch.object(activate,'verify_activity_closure'),patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):
                ops=activate.RealGuardianOps(intent)
            self.assertEqual(ops.authorization['api_shared_lock_contract'],metadata)
            intent_path=self.evidence/(direction+'-metadata-intent.json');intent_path.write_bytes(prepare.json_bytes(intent))
            @contextmanager
            def guard(scope,**kwargs):
                self.assertIs(scope,ops.scope);self.assertEqual(kwargs,{'api_shared_lock_contract':metadata});yield
            with patch.object(activate,'RealGuardianOps',return_value=ops),patch.object(activate.signal,'signal'), \
                 patch.object(activate,'release_guards',side_effect=guard),patch.object(activate,'FreezeGuardian') as frozen,patch.object(ops,'finish_journal'):
                activate.guardian_main(intent_path,prepare.sha(intent_path));frozen.return_value.run.assert_called_once()
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):
            activate.authorize_transition(self.scope,prepared,prepare.sha(self.prepared_path),'activate',pin)
        self.assertEqual(lifecycle.calls,[])

    def test_guardian_shared_lock_continuation_binding_recovery_keeps_authority(self):
        runner,prepared,pin=self.continuation_fixture();path=Path(pin['path']);value=json.loads(path.read_bytes())
        metadata={'path':str(self.source/'deployment/api_module_contracts.json'),'sha256':'a'*64}
        value['api_shared_lock_contract']=metadata;path.write_bytes(prepare.json_bytes(value));pin['sha256']=prepare.sha(path)
        recovery=self.failed_activation_pin(prepared);self.plist.write_bytes(Path(prepared['candidate_plist']).read_bytes())
        lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner);entered=[]
        @contextmanager
        def guard(scope,**kwargs):entered.append(kwargs);yield
        with patch.object(activate,'release_guards',side_effect=guard),patch.object(activate,'process_token',return_value={'pid':111}), \
             patch.object(activate,'same_process',return_value=True):
            result=activate.restore_healthy_parent_binding(self.scope,prepared,prepare.sha(self.prepared_path),lifecycle,self.rollback_path,recovery,pin)
        self.assertEqual(entered,[{'api_shared_lock_contract':metadata}]);self.assertEqual(result['state'],'ROLLED_BACK_BINDING_ONLY')
        self.assertEqual(self.plist.read_bytes(),self.old_bytes);self.assertEqual(lifecycle.calls,[])

    def test_guardian_startup_stderr_survives_eof_without_freeze(self):
        runner,prepared,pin=self.continuation_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=runner)
        token=self.scope['activity']['expected_owner'];fake=SimpleNamespace(pid=999,stdin=io.StringIO(),stdout=io.StringIO(),returncode=1)
        waits=[]
        def wait(**kwargs):waits.append(kwargs);return 1
        fake.wait=wait
        def spawn(argv,**kwargs):
            self.assertNotEqual(kwargs['stderr'],subprocess.PIPE)
            kwargs['stderr'].write(b'Traceback fixture: missing contract\n');kwargs['stderr'].flush();return fake
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'signal_identity',return_value=token), \
             patch.object(activate.subprocess,'Popen',side_effect=spawn),patch.object(activate,'read_control',return_value=None),patch.object(activate,'emit_control') as emit:
            with self.assertRaisesRegex(prepare.Stop,'GUARDIAN_TRANSITION_REQUIRES_INSPECTION:None:stderr='):
                activate.guarded_transition(self.scope,prepared,self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,None,pin)
            emit.assert_not_called()
        files=list(self.evidence.glob('guardian-stderr-*.txt'));self.assertEqual(len(files),1)
        self.assertEqual(files[0].read_bytes(),b'Traceback fixture: missing contract\n')
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode),0o600)
        self.assertEqual(waits,[{'timeout':20}]);self.assertTrue(fake.stdin.closed)
        self.assertFalse(list(self.evidence.glob('guardian-journal-*.json')));self.assertFalse(self.activation_path.exists())
        self.assertEqual(lifecycle.calls,[])

    def historical_child_authority_fixture(self):
        real_sha=prepare.sha
        def old_sha(path):
            path=Path(path)
            if path==Path(prepare.__file__):return 'a'*64
            if path==Path(activate.__file__):return 'b'*64
            return real_sha(path)
        with patch.object(prepare,'sha',side_effect=old_sha):runner,child=self.scheduler_with_child_fixture()
        self.rearm_capsule('current-outer-helpers.json')
        prepare.authorize(self.scope,'prepare')
        return runner,child

    def test_hk_child_historical_preparation_authority_preserves_sealed_product(self):
        _,child=self.historical_child_authority_fixture();pin=self.scope['hk_child_prepared']
        child_scope=prepare.read_json(child['scope_path'],child['scope_sha256'])
        paths=[Path(pin['path']),Path(child['scope_path']),Path(child_scope['execution_capsule']['path']),
               Path(child['candidate_root'])/'release-manifest.json']
        before={p:p.read_bytes() for p in paths}
        for _ in range(2):self.assertTrue(prepare.hk_child_binding(self.scope))
        self.assertEqual(child['helper_sha256'],'a'*64)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        # The original child cannot authorize a new operation with old helpers.
        with self.assertRaisesRegex(prepare.Stop,'UNREVIEWED_HELPER'):prepare.authorize(child_scope,'prepare')

    def test_hk_child_historical_authority_rejects_receipt_capsule_and_inventory_drift(self):
        _,child=self.historical_child_authority_fixture();pin=self.scope['hk_child_prepared'];path=Path(pin['path']);raw=path.read_bytes()
        value=json.loads(raw);value['helper_sha256']='c'*64;path.write_bytes(prepare.json_bytes(value));pin['sha256']=prepare.sha(path)
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_PREPARE_HELPER_DRIFT'):prepare.hk_child_binding(self.scope)
        path.write_bytes(raw);pin['sha256']=prepare.sha(path)
        child_scope=prepare.read_json(child['scope_path'],child['scope_sha256']);capsule=Path(child_scope['execution_capsule']['path']);capsule_raw=capsule.read_bytes()
        capsule.write_bytes(capsule_raw+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):prepare.hk_child_binding(self.scope)
        capsule.write_bytes(capsule_raw)
        target=Path(child['candidate_root'])/'app'/self.target;original=target.read_bytes();target.write_bytes(b'candidate drift')
        with self.assertRaisesRegex(prepare.Stop,'HK_CHILD_CANDIDATE_DRIFT'):prepare.hk_child_binding(self.scope)
        target.write_bytes(original);self.assertTrue(prepare.hk_child_binding(self.scope))


    def research_env_insert_fixture(self):
        runner=self.release_fixture()
        raw=plistlib.loads(self.old_bytes);env=raw['EnvironmentVariables'];env.pop('RESEARCH_ONLY')
        for key in ('production_allowed','buy_gate_updated','orders_sent'):env[key.upper()]='false'
        operation={'keys':['EnvironmentVariables','RESEARCH_ONLY'],'before_absent':True,'after':'1'}
        self.scope['plist']['updates'].append(operation)
        return raw,operation

    def test_research_env_insert_exact_absent_key_preserves_other_bindings(self):
        raw,operation=self.research_env_insert_fixture();before=deepcopy(raw)
        result=plistlib.loads(prepare.proposed_plist(plistlib.dumps(raw),self.scope,'a'*64))
        self.assertEqual(result['EnvironmentVariables']['RESEARCH_ONLY'],'1')
        expected=deepcopy(before)
        fields={'app':str(self.candidate/'app'),'release_id':self.candidate.name,
            'manifest':str(self.candidate/'release-manifest.json'),'manifest_sha256':'a'*64,'root':str(self.candidate)}
        for update in self.scope['plist']['updates'][:-1]:
            node=expected
            for key in update['keys'][:-1]:node=node[key]
            node[update['keys'][-1]]=update['after'].format(**fields)
        expected['EnvironmentVariables']['RESEARCH_ONLY']='1'
        self.assertEqual(result,expected);self.assertEqual(raw,before)
        self.assertFalse(self.candidate.exists())

    def test_research_env_insert_existing_key_and_null_are_not_absent(self):
        raw,operation=self.research_env_insert_fixture()
        for value in ('1','0','false','',None):
            check=deepcopy(raw);check['EnvironmentVariables']['RESEARCH_ONLY']=value
            # plist cannot encode None, so inject only the decoded fixture for
            # that case; the membership check must still reject an existing key.
            with self.subTest(value=value),self.assertRaisesRegex(prepare.Stop,'PLIST_FIELD_ALREADY_PRESENT'):
                if value is None:
                    with patch.object(prepare.plistlib,'loads',return_value=check):prepare.proposed_plist(b'fixture',self.scope,'a'*64)
                else:prepare.proposed_plist(plistlib.dumps(check),self.scope,'a'*64)

    def test_research_env_insert_only_one_literal_operation_is_allowed(self):
        raw,operation=self.research_env_insert_fixture();original=deepcopy(operation)
        for mutation in ('flag','lowercase','top','wholeenv','wrongvalue','template','false','integer','before','extra'):
            operation.clear();operation.update(deepcopy(original))
            if mutation=='flag':operation['keys']=['EnvironmentVariables','production_allowed']
            elif mutation=='lowercase':operation['keys']=['EnvironmentVariables','research_only']
            elif mutation=='top':operation['keys']=['RESEARCH_ONLY']
            elif mutation=='wholeenv':operation['keys']=['EnvironmentVariables'];operation['after']={'RESEARCH_ONLY':'1'}
            elif mutation=='wrongvalue':operation['after']='true'
            elif mutation=='template':operation['after']='{release_id}'
            elif mutation=='false':operation['before_absent']=False
            elif mutation=='integer':operation['before_absent']=1
            elif mutation=='before':operation['before']=None
            else:operation['allow_anything']=True
            with self.subTest(mutation=mutation),self.assertRaisesRegex(prepare.Stop,'PLIST_ABSENT_INSERT_NOT_ALLOWED'):
                prepare.proposed_plist(plistlib.dumps(raw),self.scope,'a'*64)
        operation.clear();operation.update(original)
        self.scope['plist']['updates'].append(deepcopy(operation))
        with self.assertRaisesRegex(prepare.Stop,'PLIST_UPDATE_DUPLICATE'):prepare.proposed_plist(plistlib.dumps(raw),self.scope,'a'*64)

    def test_research_env_insert_keeps_preimages_and_existing_safety_guards(self):
        raw,operation=self.research_env_insert_fixture();before=deepcopy(raw)
        first=self.scope['plist']['updates'][0];original=first['before'];first['before']='wrong preimage'
        with self.assertRaisesRegex(prepare.Stop,'PLIST_FIELD_DRIFT'):prepare.proposed_plist(plistlib.dumps(raw),self.scope,'a'*64)
        first['before']=original
        for key in ('production_allowed','PRODUCTION_ALLOWED','buy_gate_updated','BUY_GATE_UPDATED','orders_sent','ORDERS_SENT'):
            check=deepcopy(raw);check['EnvironmentVariables'][key]='true'
            with self.subTest(key=key),self.assertRaisesRegex(prepare.Stop,'PLIST_UNSAFE_FLAG'):
                prepare.proposed_plist(plistlib.dumps(check),self.scope,'a'*64)
        check=deepcopy(raw);check['ProgramArguments']=check['ProgramArguments']+['RESEARCH_ONLY=0']
        with self.assertRaisesRegex(prepare.Stop,'PLIST_RESEARCH_ONLY_REQUIRED'):
            prepare.proposed_plist(plistlib.dumps(check),self.scope,'a'*64)
        self.assertEqual(raw,before);self.assertFalse(self.candidate.exists())


    def activity_catalog_fixture(self):
        runner,roots=self.retained_queue_fixture();root=roots['hkex_announcements']
        run='f42f992f8705491492d065673bde9e9e';base=root/'workspace_announcement_runs/20260930/eastmoney_date_catalog/20260929'
        common=dict(run_id=run,target_trade_date='20260930',publication_date='2026-09-29',source_scope='EASTMONEY_HK_DATE_CATALOG')
        catalog=dict(common,schema_version='v4.manager_research.eastmoney_hk_date_catalog_attempt.v1',
            owner='ManagerResearchJobService.refresh_announcements',state='COMPLETE',finished_at='2026-10-05T02:15:52+00:00',
            input_coverage={'captured_page_count':1})
        marker=dict(common,schema_version='v4.manager_research.eastmoney_hk_page_attempt.v1',
            owner='ManagerResearchJobService.refresh_announcements',state='STARTED',started_at='2026-10-05T02:15:51+00:00',
            page_index=1,requested_url='https://fixture.invalid/catalog?page_index=1',disposition='REUSE_EXISTING_REFERENCE')
        marker_path=base/run/'pages/page-0001.attempt.json'
        receipt=dict(common,schema='v4.manager_research.eastmoney_hk_page_receipt.v1',page_index=1,
            requested_url=marker['requested_url'],capture_status='PASS',owner_attempt_path=marker_path.relative_to(root).as_posix())
        paths={'catalog':base/(run+'.json'),'latest':base/'latest.json','marker':marker_path,'receipt':base/run/'pages/page-0001.json'}
        rows={'catalog':catalog,'latest':catalog,'marker':marker,'receipt':receipt}
        def write():
            for key,path in paths.items():
                path.parent.mkdir(parents=True,exist_ok=True);row=deepcopy(rows[key])
                if key in ('catalog','latest'):
                    row.pop('sha256',None);row['sha256']=prepare.digest(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
                path.write_bytes(prepare.json_bytes(row))
        write();return runner,root,paths,rows,write

    def test_activity_catalog_terminal_children_and_all_finished_states_are_idle(self):
        runner,root,paths,rows,write=self.activity_catalog_fixture()
        for state,status in (('COMPLETE','PASS'),('COMPLETE_EMPTY','PASS'),('PARTIAL','PARTIAL'),('FAILED','FAILED')):
            rows['catalog']['state']=state;rows['receipt']['capture_status']=status;write()
            with self.subTest(state=state):self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],[])
        self.assertEqual(rows['marker']['state'],'STARTED');self.assertNotIn('finished_at',rows['marker'])

    def test_activity_catalog_missing_link_bad_seal_unknown_and_identity_are_rejected(self):
        runner,root,paths,rows,write=self.activity_catalog_fixture();original=deepcopy(rows)
        for mutation in ('catalog_missing','marker_missing','receipt_missing','bad_seal','unknown','bad_owner','run','date','page','url','owner_path','unexpected_path','count'):
            rows.clear();rows.update(deepcopy(original));write()
            if mutation.endswith('_missing'):paths[mutation[:-8]].unlink()
            elif mutation=='bad_seal':
                value=json.loads(paths['catalog'].read_bytes());value['sha256']='0'*64;paths['catalog'].write_bytes(prepare.json_bytes(value))
            elif mutation=='unknown':rows['receipt']['schema']='unknown';write()
            elif mutation=='bad_owner':rows['marker']['owner']='unknown';write()
            elif mutation=='run':rows['receipt']['run_id']='a'*32;write()
            elif mutation=='date':rows['receipt']['publication_date']='2026-09-28';write()
            elif mutation=='page':rows['receipt']['page_index']=2;write()
            elif mutation=='url':rows['receipt']['requested_url']='wrong';write()
            elif mutation=='owner_path':rows['receipt']['owner_attempt_path']='../elsewhere';write()
            elif mutation=='count':rows['catalog']['input_coverage']['captured_page_count']=2;write()
            else:
                extra=root/'workspace_announcement_runs/20260930/unrecognized.json';extra.write_bytes(paths['receipt'].read_bytes())
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):activate.activity_snapshot(self.scope,runner)
            if mutation=='unexpected_path':extra.unlink()
        rows.clear();rows.update(original);write();self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],[])

    def test_activity_catalog_running_and_three_original_hk_runs_remain_busy(self):
        runner,root,paths,rows,write=self.activity_catalog_fixture();rows['catalog'].update(state='RUNNING',finished_at=None);write()
        self.assertTrue(activate.activity_snapshot(self.scope,runner)['busy_work'])
        rows['catalog'].update(state='COMPLETE',finished_at='2026-10-05T02:15:52+00:00');write()
        running=[]
        for run in ('9d62509ee10449ec991fccf460fc86d8','e5d9be8bc3af419c93ea334f68064e3e','f3dfc878dcbc4686850a398ab5fb7730'):
            path=root/'workspace_announcement_runs/20261012'/(run+'.json');path.parent.mkdir(exist_ok=True)
            row=dict(schema_version='v4.manager_research.workspace_attempt.v1',state='RUNNING',run_id=run,
                target_trade_date='20261012',finished_at=None)
            row['sha256']=prepare.digest(json.dumps(row,sort_keys=True,separators=(',',':')).encode());path.write_bytes(prepare.json_bytes(row));running.append(str(path))
        self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],running)
        self.assertFalse(any(p.name=='candidate' for p in self.root.iterdir()))

    def test_activity_orphan_unknown_identity_without_finished_time_remains_busy(self):
        runner,roots=self.retained_queue_fixture();path=Path(self.scope['activity']['workbench_root'])/'attempts/07bfabf09f144360ab8869214aeecea8.json'
        row=dict(job_id=path.stem,state='INTERRUPTED',failure_code='PROCESS_IDENTITY_UNVERIFIED',retryable=True,
            finished_at=None,execution_refs=[{'kind':'host','pid':65614}],step='FLASH_SELECTION',failed_steps=['FLASH_SELECTION'])
        path.write_bytes(prepare.json_bytes(row));before=path.read_bytes()
        self.assertEqual(activate.activity_snapshot(self.scope,runner)['busy_work'],[str(path)])
        self.assertEqual(path.read_bytes(),before)
        for state,code,retry in (('SUCCEEDED','PROCESS_IDENTITY_UNVERIFIED',True),('INTERRUPTED','OTHER',True),('INTERRUPTED','PROCESS_IDENTITY_UNVERIFIED',False)):
            row.update(state=state,failure_code=code,retryable=retry);path.write_bytes(prepare.json_bytes(row))
            with self.subTest(state=state,code=code,retry=retry),self.assertRaisesRegex(prepare.Stop,'WORKBENCH_TERMINAL_ATTEMPT_INCOMPLETE'):
                activate.activity_snapshot(self.scope,runner)


    def authorized_four_fixture(self, *, recover=True, include_hk=True):
        import recover_legacy_activity as recovery
        runner,roots=self.retained_queue_fixture();self.scope['role']='scheduler'
        token=dict(pid=111,start_sec=2,start_usec=3,status=2,
            audit_token=[os.getuid(),os.geteuid(),os.getegid(),os.getuid(),os.getgid(),111,100025,4],pid_version=4)
        self.scope['activity'].update(expected_owner=token,admission_files={'parent':{},'candidate':{}})
        authority=json.loads(recovery.AUTHORIZATION_PATH.read_bytes());originals={}
        for record in authority['records']:
            original=Path(record['path']);raw=original.read_bytes()
            target=(roots['hkex_announcements']/'workspace_announcement_runs/20261012'/original.name if record['kind']=='HK_workspace'
                else Path(self.scope['activity']['workbench_root'])/'attempts'/original.name)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);record['path']=str(target);originals[str(target)]=raw
        if not include_hk:self.scope['activity'].pop('retained_owner_queues')
        path=self.root/'authority.json';path.write_bytes(prepare.json_bytes(authority))
        patch.object(recovery,'AUTHORIZATION_PATH',path).start();patch.object(recovery,'AUTHORIZATION_SHA256',prepare.sha(path)).start()
        cap=Path(self.scope['execution_capsule']['path']);value=json.loads(cap.read_bytes())
        value.update(authorized_actions=['prepare'],scope_contract_sha256=prepare.contract_sha(self.scope))
        cap.write_bytes(prepare.json_bytes(value));self.scope['execution_capsule']['sha256']=prepare.sha(cap)
        prepared=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
        api_scope=self.root/'api-product-scope.json';api_scope.write_bytes(prepare.json_bytes(dict(mode='RELEASE',role='api')))
        api_product=self.root/'api-product.json';api_product.write_bytes(prepare.json_bytes(dict(schema='v4.us_hk.release_prepared.v1',state='PREPARED',mode='RELEASE',scope_path=str(api_scope),scope_sha256=prepare.sha(api_scope))))
        products=[dict(path=str(api_product),sha256=prepare.sha(api_product)),dict(path=str(self.prepared_path),sha256=prepare.sha(self.prepared_path))]
        capsule=dict(schema='v4.us_hk.legacy_disposition_capsule.v1',verdict='PASS',authorized_actions=['administrative_disposition'],
            authority={'path':str(path),'sha256':prepare.sha(path)},prepared_products=products,private_root=str(self.root/'private-originals'),
            helper_sha256={n:prepare.sha(Path(__file__).with_name(n)) for n in ('recover_legacy_activity.py','activate_release.py')})
        cap=self.root/'disposition-capsule.json';cap.write_bytes(prepare.json_bytes(capsule));pin={'path':str(cap),'sha256':prepare.sha(cap)}
        receipt=recovery.recover(pin) if recover else None
        proof_path=Path(capsule['private_root'])/'DISPOSITION.json'
        proof={'path':str(proof_path),'sha256':prepare.sha(proof_path)} if recover else None
        continuation=dict(schema='v4.us_hk.execution_capsule.v1',verdict='PASS',authorized_actions=['activate','rollback'],
            prepared_sha256=products[1]['sha256'],scope_sha256=prepared['scope_sha256'],scope_contract_sha256=prepare.contract_sha(self.scope),
            helper_sha256={n:prepare.sha(Path(__file__).with_name(n)) for n in ('prepare_release.py','activate_release.py')},legacy_activity_disposition=proof)
        cont=self.root/'disposition-continuation.json';cont.write_bytes(prepare.json_bytes(continuation))
        activity_authority=dict(prepared=products[1],direction='activate',continuation=dict(path=str(cont),sha256=prepare.sha(cont)))
        return SimpleNamespace(recovery=recovery,runner=runner,roots=roots,authority=authority,originals=originals,prepared=prepared,
            capsule=capsule,capsule_pin=pin,receipt=receipt,proof=proof,continuation=continuation,activity_authority=activity_authority)

    def four_snapshot(self,f):
        return activate.activity_snapshot(self.scope,f.runner,activity_authority=f.activity_authority)

    def test_authorized_four_disposition_preserves_originals_and_rejects_unlisted_busy(self):
        f=self.authorized_four_fixture();r=f.recovery
        self.assertEqual(r.recover(f.capsule_pin),f.receipt)
        self.assertEqual(len(activate.activity_snapshot(self.scope,f.runner)['busy_work']),4)
        observed=self.four_snapshot(f)
        self.assertEqual(observed['busy_work'],[]);self.assertEqual(len(observed['administratively_disposed_work']),4)
        self.assertEqual(observed['legacy_execution_state'],'UNKNOWN');self.assertFalse(observed['completion_or_idle_proven'])
        self.assertEqual({k:Path(k).read_bytes() for k in f.originals},f.originals)
        for row in f.receipt['records']:self.assertEqual(Path(row['backup_path']).read_bytes(),f.originals[row['path']])
        self.assertEqual(sum(len(v) for v in f.originals.values()),5239)
        # This proves the old decision remains blocked when authority is absent.
        with self.assertRaises(prepare.Stop):activate.activity_snapshot(self.scope,f.runner,activity_authority={'legacy_activity_disposition':f.proof})
        extra=Path(self.scope['activity']['workbench_root'])/'attempts/unlisted.json'
        extra.write_bytes(prepare.json_bytes(dict(job_id='unlisted',state='RUNNING')))
        self.assertEqual(self.four_snapshot(f)['busy_work'],[str(extra)])
        # Identical content under another name never inherits the disposition.
        extra.write_bytes(next(iter(f.originals.values())))
        self.assertEqual(self.four_snapshot(f)['busy_work'],[str(extra)])

    def test_authorized_four_original_sha_id_path_missing_and_duplicate_fail_closed(self):
        f=self.authorized_four_fixture()
        for name,raw in f.originals.items():
            path=Path(name)
            with self.subTest(path=name):
                path.write_bytes(raw+b' ')
                with self.assertRaises(prepare.Stop):self.four_snapshot(f)
                path.write_bytes(raw.replace(path.stem.encode(),b'0'*32))
                with self.assertRaises(prepare.Stop):self.four_snapshot(f)
                path.unlink()
                with self.assertRaises((prepare.Stop,FileNotFoundError)):self.four_snapshot(f)
                path.write_bytes(raw)
        original=dict(f.activity_authority['prepared']);f.activity_authority['prepared']=dict(original,path=str(self.root/'other-product.json'))
        with self.assertRaises((prepare.Stop,FileNotFoundError)):self.four_snapshot(f)
        f.activity_authority['prepared']=original
        # Duplicate scans must not quietly subtract two sightings of one approved path.
        with patch.object(activate,'disposition_for_activity',return_value=(f.proof,f.receipt)):
            self.scope['activity']['retained_owner_queues'].append(dict(kind='hkex_announcements',root=str(f.roots['hkex_announcements'])))
            with self.assertRaisesRegex(prepare.Stop,'FOUR_ACTIVITY_RECORD_MISSING_OR_DUPLICATE'):self.four_snapshot(f)

    def test_authorized_four_receipt_requires_exact_human_operation_and_product(self):
        f=self.authorized_four_fixture();r=f.recovery;cap=Path(f.capsule_pin['path']);raw=cap.read_bytes()
        for mutation in ('authority_sha','authority_path','operation','helpers','product','extra','duplicate','private_root'):
            value=json.loads(raw)
            if mutation=='authority_sha':value['authority']['sha256']='0'*64
            elif mutation=='authority_path':value['authority']['path']=str(self.root/'other-authority.json')
            elif mutation=='operation':value['authorized_actions']=['activate']
            elif mutation=='helpers':value['helper_sha256']['activate_release.py']='0'*64
            elif mutation=='product':value['prepared_products'][1]['sha256']='0'*64
            elif mutation=='extra':value['prepared_products'].append(value['prepared_products'][0])
            elif mutation=='duplicate':value['prepared_products'][1]=value['prepared_products'][0]
            else:value['private_root']=str(self.root/'arbitrary')
            cap.write_bytes(prepare.json_bytes(value))
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):r.recover(dict(path=str(cap),sha256=prepare.sha(cap)))
        cap.write_bytes(raw)
        for product,scope in (('0'*64,f.prepared['scope_sha256']),(f.activity_authority['prepared']['sha256'],'0'*64)):
            with self.assertRaisesRegex(prepare.Stop,'FOUR_RECEIPT_OTHER_PRODUCT'):r.verify_disposition(f.proof,product,scope)
        for row in f.receipt['records']:
            backup=Path(row['backup_path']);before=backup.read_bytes();backup.write_bytes(b'wrong')
            with self.assertRaisesRegex(prepare.Stop,'FOUR_ORIGINAL_BACKUP_DRIFT'):self.four_snapshot(f)
            backup.write_bytes(before)
        receipt_path=Path(f.proof['path']);before=receipt_path.read_bytes();value=json.loads(before);value['execution_state']='COMPLETED'
        receipt_path.write_bytes(prepare.json_bytes(value))
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):self.four_snapshot(f)
        with self.assertRaisesRegex(prepare.Stop,'FOUR_RECEIPT_BINDING_MISMATCH'):
            r.verify_disposition(dict(path=str(receipt_path),sha256=prepare.sha(receipt_path)),f.activity_authority['prepared']['sha256'],f.prepared['scope_sha256'])

    def test_authorized_four_continuation_missing_unpinned_or_wrong_action_blocks(self):
        f=self.authorized_four_fixture();path=Path(f.activity_authority['continuation']['path']);raw=path.read_bytes()
        for mutation in ('missing','unpinned','wrong_action','receipt_pin','other_product'):
            value=json.loads(raw)
            if mutation=='missing':value.pop('legacy_activity_disposition')
            elif mutation=='unpinned':value['legacy_activity_disposition']=f.proof['path']
            elif mutation=='wrong_action':value['authorized_actions']=['prepare']
            elif mutation=='receipt_pin':value['legacy_activity_disposition']['sha256']='0'*64
            else:value['prepared_sha256']='0'*64
            path.write_bytes(prepare.json_bytes(value));f.activity_authority['continuation']['sha256']=prepare.sha(path)
            with self.subTest(mutation=mutation),self.assertRaises(prepare.Stop):self.four_snapshot(f)
        path.write_bytes(raw);f.activity_authority['continuation']['sha256']=prepare.sha(path)
        path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FILE_SHA_DRIFT'):self.four_snapshot(f)

    def test_authorized_four_recovery_partial_idempotent_no_overwrite_and_cas(self):
        f=self.authorized_four_fixture(recover=False);r=f.recovery;root=Path(f.capsule['private_root']);root.mkdir(mode=0o700)
        expected=r.expected_receipt(f.capsule_pin,f.capsule,f.authority,root);backup=Path(expected['records'][0]['backup_path'])
        backup.write_bytes(b'existing unrelated bytes');backup.chmod(0o600)
        with self.assertRaisesRegex(prepare.Stop,'FOUR_PRIVATE_COLLISION'):r.recover(f.capsule_pin)
        self.assertEqual(backup.read_bytes(),b'existing unrelated bytes');self.assertFalse((root/'DISPOSITION.json').exists())
        backup.write_bytes(f.originals[expected['records'][0]['path']])
        receipt=r.recover(f.capsule_pin);before={str(p):p.read_bytes() for p in root.iterdir()}
        self.assertEqual(r.recover(f.capsule_pin),receipt);self.assertEqual({str(p):p.read_bytes() for p in root.iterdir()},before)
        self.assertEqual(root.stat().st_mode & 0o777,0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777==0o600 for p in root.iterdir()))
        # A concurrent original change is never hidden by already preserved evidence.
        original=Path(expected['records'][0]['path']);raw=original.read_bytes();original.write_bytes(raw+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FOUR_ORIGINAL_SIZE_DRIFT'):r.recover(f.capsule_pin)
        self.assertEqual(backup.read_bytes(),raw)

    def test_authorized_four_guardian_propagates_pin_and_rechecks_at_commit(self):
        f=self.authorized_four_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=f.runner);captured={}
        token=self.scope['activity']['expected_owner']
        def intercept(argv,**kwargs):
            captured.update(json.loads(Path(argv[-2]).read_bytes()));raise RuntimeError('FIXTURE_GUARDIAN_INTERCEPTED')
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'signal_identity',return_value=token),patch.object(activate.subprocess,'Popen',side_effect=intercept):
            with self.assertRaisesRegex(RuntimeError,'FIXTURE_GUARDIAN_INTERCEPTED'):
                activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,continuation=f.activity_authority['continuation'])
        self.assertEqual(captured['legacy_activity_disposition'],f.proof)
        self.assertEqual(captured['continuation'],f.activity_authority['continuation'])
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):
            ops=activate.RealGuardianOps(captured);ops.verify_before_freeze();ops.verify_commit()
            value=ops.frozen_activity();self.assertEqual(value['busy_work'],[]);self.assertEqual(value['legacy_execution_state'],'UNKNOWN')
            guardian=activate.FreezeGuardian(ops,captured,io.StringIO(),io.StringIO());guardian.record('FROZEN_IDLE',activity=value)
            journal=json.loads(Path(captured['journal']).read_bytes());self.assertEqual(journal['legacy_activity_disposition'],f.proof)
            ops.finish_journal(captured['journal']);failure=json.loads(self.activation_path.read_bytes())
            self.assertEqual(failure['legacy_execution_state'],'UNKNOWN');self.assertEqual(failure['legacy_activity_disposition'],f.proof)
            missing=dict(captured);missing.pop('legacy_activity_disposition')
            with self.assertRaisesRegex(prepare.Stop,'FOUR_GUARDIAN_PIN_MISMATCH'):activate.RealGuardianOps(missing)
            original=next(iter(f.originals));Path(original).write_bytes(f.originals[original]+b' ')
            with self.assertRaisesRegex(prepare.Stop,'FOUR_ORIGINAL_SIZE_DRIFT'):ops.frozen_activity()
        self.assertEqual(lifecycle.calls,[]);self.assertEqual(self.plist.read_bytes(),self.old_bytes)



    def test_authorized_four_backup_cas_drift_never_commits_receipt(self):
        f=self.authorized_four_fixture(recover=False);r=f.recovery;real=r.private_file;calls=[]
        original=Path(next(iter(f.originals)));before=original.read_bytes()
        def changed(path,raw):
            real(path,raw);calls.append(path)
            if len(calls)==4:original.write_bytes(before+b' ')
        with patch.object(r,'private_file',side_effect=changed):
            with self.assertRaisesRegex(prepare.Stop,'FOUR_ORIGINAL_SIZE_DRIFT'):r.recover(f.capsule_pin)
        root=Path(f.capsule['private_root']);self.assertFalse((root/'DISPOSITION.json').exists())
        self.assertEqual(len(list(root.iterdir())),4)
        self.assertEqual(original.read_bytes(),before+b' ')  # Never overwrite a concurrent writer.
        original.write_bytes(before);r.recover(f.capsule_pin)
        extra=root/'unexpected';extra.write_bytes(b'untouched')
        with self.assertRaisesRegex(prepare.Stop,'FOUR_PRIVATE_ROOT_UNEXPECTED_FILE'):r.recover(f.capsule_pin)
        self.assertEqual(extra.read_bytes(),b'untouched')

    def test_authorized_four_injected_guardian_activation_and_rollback_retain_unknown(self):
        f=self.authorized_four_fixture();lifecycle=activate.LaunchctlLifecycle(self.scope,runner=f.runner)
        frozen={p:p.read_bytes() for p in (self.prepared_path,self.scope_path,self.candidate/'release-manifest.json')}
        tokens={111:self.scope['activity']['expected_owner']};statuses={111:2}
        def identity(pid):
            if pid not in tokens:tokens[pid]=dict(tokens[111],pid=pid,pid_version=pid)
            return tokens[pid]
        def fake_signal(token,signum):statuses[token['pid']]=4 if signum==signal.SIGSTOP else 5
        def guarded(scope,product,product_path,product_sha,direction,adapter,receipt,recovery,continuation):
            token=identity(f.runner.pid);statuses[token['pid']]=2
            intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='RELEASE',controller_pid=os.getpid(),
                owner_token=token,prepared={'path':str(product_path),'sha256':product_sha},direction=direction,
                recovery_pin=recovery,journal=str(self.evidence/(direction+'-four-guardian.json')),
                receipt_path=str(receipt),helper_sha256=prepare.sha(activate.__file__),continuation=continuation,
                legacy_activity_disposition=f.proof)
            with patch.object(activate,'LaunchctlLifecycle',return_value=lifecycle):ops=activate.RealGuardianOps(intent)
            with io.StringIO() as output:
                fd,write_fd=os.pipe();os.write(write_fd,b'UNDER_TEST');os.close(write_fd)
                # Pipe control is fixture-only; no subprocess or kernel signals occur.
                with os.fdopen(fd) as control,patch.object(activate,'read_control',side_effect=[{'action':'FREEZE'},{'action':'COMMIT'},{'action':'START'}]):
                    activate.FreezeGuardian(ops,intent,control,output).run()
            return json.loads(receipt.read_bytes())
        with patch.object(activate,'verify_activity_closure'),patch.object(activate,'signal_identity',side_effect=identity), \
             patch.object(activate,'same_process',return_value=True), \
             patch.object(activate,'process_token',side_effect=lambda pid:dict(identity(pid),status=statuses.get(pid,2))), \
             patch.object(activate,'signal_exact_identity',side_effect=fake_signal), \
             patch.object(activate.signal,'pthread_sigmask',return_value=set()),patch.object(activate,'guarded_transition',side_effect=guarded):
            activated=activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'activate',lifecycle,self.activation_path,
                continuation=f.activity_authority['continuation'])
            rolled=activate.transition(self.prepared_path,prepare.sha(self.prepared_path),'rollback',lifecycle,self.rollback_path,
                continuation=f.activity_authority['continuation'],recovery_pin={'path':str(self.activation_path),'sha256':prepare.sha(self.activation_path)})
        self.assertEqual((activated['state'],rolled['state']),('ACTIVATED','ROLLED_BACK'))
        for value in (activated,rolled):
            self.assertEqual(value['legacy_activity_disposition'],f.proof);self.assertEqual(value['legacy_execution_state'],'UNKNOWN')
            self.assertFalse(value['runtime_readback']['completion_or_idle_proven'])
        self.assertEqual(self.plist.read_bytes(),self.old_bytes)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in frozen.items()))
        self.assertEqual({p:Path(p).read_bytes() for p in f.originals},f.originals)


    def test_authorized_four_scheduler_partial_scan_still_pins_all_originals(self):
        f=self.authorized_four_fixture(include_hk=False)
        observed=self.four_snapshot(f)
        self.assertEqual(observed['busy_work'],[])
        self.assertEqual(observed['administratively_disposed_work'],[r['path'] for r in f.receipt['records'] if r['kind']=='Workbench'])
        # A role's smaller scan never weakens global exact-four evidence binding.
        path=Path(f.receipt['records'][0]['path']);path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(prepare.Stop,'FOUR_ORIGINAL_SIZE_DRIFT'):self.four_snapshot(f)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--cases', nargs='+', help='Run only new/affected cases after a bounded helper change')
    args=parser.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    output=Path(args.receipt).resolve()
    prepare.require(output.is_relative_to(SCRATCH.resolve()), 'TEST_RECEIPT_OUTSIDE_SCRATCH')
    before={str(p):prepare.sha(p) for p in LIVE_PATHS}
    suite=(unittest.TestSuite(ReleaseTests(name) for name in args.cases) if args.cases else
           unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    after={str(p):prepare.sha(p) for p in LIVE_PATHS}
    receipt=dict(schema='v4.us_hk.release_helper_tests.v1', tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        passed=result.wasSuccessful(), cases=args.cases or 'ALL', actual_live_hashes_before=before, actual_live_hashes_after=after,
        live_unchanged=before==after, lifecycle='FAKE_OR_MARKED_SCRATCH_DUMMY_ONLY', live_operations=0,
        helper_sha256={p.name:prepare.sha(p) for p in [Path(__file__),Path(prepare.__file__),Path(activate.__file__),Path(__file__).with_name('recover_legacy_activity.py')]})
    prepare.write_new(output, prepare.json_bytes(receipt))
    print(json.dumps(dict(receipt=str(output), sha256=prepare.sha(output),tests=result.testsRun,passed=receipt['passed'],live_unchanged=receipt['live_unchanged'])))
    raise SystemExit(0 if result.wasSuccessful() and before==after else 1)


if __name__=='__main__': main()
