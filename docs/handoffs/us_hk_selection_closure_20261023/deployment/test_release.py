"""Hermetic release-scope/CAS tests; only own scratch fixtures are mutated."""
from __future__ import annotations

import argparse
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
REAL_RELEASE_GUARDS=activate.release_guards
LIVE_PATHS = [Path('/Users/lexi/Library/LaunchAgents') / (label + '.plist') for label in ('com.lexi.v35.api-only', 'com.lexi.v35.scheduler')]
LIVE_PATHS += [Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2') / name for name in ('panel_latest.json', 'history_resolution_latest.json')]


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

    def scheduler_with_child_fixture(self):
        runner=self.hk_child_fixture();child=prepare.prepare(self.scope_path,self.scope_sha(),self.prepared_path,runner=runner)
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
        helper_sha256={p.name:prepare.sha(p) for p in [Path(__file__),Path(prepare.__file__),Path(activate.__file__)]})
    prepare.write_new(output, prepare.json_bytes(receipt))
    print(json.dumps(dict(receipt=str(output), sha256=prepare.sha(output),tests=result.testsRun,passed=receipt['passed'],live_unchanged=receipt['live_unchanged'])))
    raise SystemExit(0 if result.wasSuccessful() and before==after else 1)


if __name__=='__main__': main()
