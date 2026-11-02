"""Offline release-switch regressions; all launchctl/service calls are mocked."""
import contextlib
import importlib.util
import io
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "activate_release.py"
spec = importlib.util.spec_from_file_location("supplement_activation", SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def plist(release_id, root=Path('/old'), digest='old-manifest'):
    return plistlib.dumps({'Label': a.LABEL, 'WorkingDirectory': str(root / 'app'),
                          'EnvironmentVariables': {'V4_APP_ROOT': str(root / 'app'),
                            'V4_RELEASE_ID': release_id, 'V4_RELEASE_MANIFEST_SHA256': digest,
                            'V4_RELEASE_MANIFEST_PATH': str(root / 'release-manifest.json')}})


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.live = self.root / 'live.plist'
        self.previous = plist('actual-old')
        self.live.write_bytes(self.previous)
        self.addCleanup(patch.stopall)
        patch.object(a, 'LIVE_PLIST', self.live).start()
        self.old_process = {'pid': '101', 'last_exit': '0'}
        self.new_process = {'pid': '102', 'last_exit': '0'}

    def candidate(self):
        c = self.root / 'candidate'
        (c / 'config').mkdir(parents=True)
        # Deliberately wrong base id: rollback must use the actual old plist.
        manifest = {'release_id': 'new', 'base_candidate': {'release_id': 'wrong-base'}}
        m = json.dumps(manifest).encode()
        desired = plist('new', c, a.sha256_bytes(m))
        (c / 'release-manifest.json').write_bytes(m)
        (c / 'config/com.lexi.v4.api.plist').write_bytes(desired)
        preparation = {'activation_status': 'NOT_ACTIVATED',
                       'before_plist_sha256': a.sha256_bytes(self.previous),
                       'candidate_plist_sha256': a.sha256_bytes(desired),
                       'candidate_manifest_sha256': a.sha256_bytes(m)}
        (c / 'preparation.json').write_text(json.dumps(preparation))
        (c / 'activation-attempt.json').write_text('previous-failure-evidence')
        return c, desired

    def test_wait_verified_retries_old_identity_then_new(self):
        with patch.object(a, 'verify_release', side_effect=[{'ok': False, 'identity': 'old'}, {'ok': True}]) as v, \
             patch.object(a.time, 'sleep'), patch.object(a.time, 'time', side_effect=AssertionError('wall clock deadline')):
            self.assertTrue(a.wait_verified('new', seconds=2)['ok'])
            self.assertEqual(v.call_count, 2)

    def test_bootstrap_retries_old_identity_then_new(self):
        with patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, '', '')) as lc, \
             patch.object(a, 'process_info', return_value=self.new_process), \
             patch.object(a, 'verify_release', side_effect=[{'ok': False}, {'ok': True}]) as v, \
             patch.object(a.time, 'sleep'), patch.object(a.time, 'time', side_effect=AssertionError('wall clock deadline')):
            tracking = {}
            self.assertTrue(a.bootstrap_and_verify(plist('new'), a.MARKER, tracking)['ok'])
            self.assertEqual(v.call_count, 2)
            self.assertEqual(tracking['process'], self.new_process)
            lc.assert_called_once_with('bootstrap', a.DOMAIN, str(self.live))

    def test_unload_absent_job_still_waits_for_socket(self):
        absent = subprocess.CompletedProcess([], 113, '', 'Could not find service')
        with patch.object(a, 'launchctl', return_value=absent) as lc, \
             patch.object(a, 'port_listening', side_effect=[True, True, False]) as listener, \
             patch.object(a.time, 'sleep'):
            a.unload()
            self.assertEqual(listener.call_count, 3)
            self.assertTrue(all(call.args[0] == 'print' for call in lc.call_args_list))

    def test_absent_but_socket_timeout_cannot_bootstrap(self):
        c, _ = self.candidate()
        absent = subprocess.CompletedProcess([], 113, '', 'Could not find service')
        with patch.object(a, 'process_info', return_value=self.old_process), \
             patch.object(a, 'wait_verified', return_value={'ok': True}), \
             patch.object(a, 'launchctl', return_value=absent) as lc, \
             patch.object(a, 'port_listening', return_value=True), \
             patch.object(a.time, 'monotonic', side_effect=[0, 21]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.activate_locked(c), 2)
            self.assertFalse(any(call.args[0] == 'bootstrap' for call in lc.call_args_list))
            self.assertEqual(self.live.read_bytes(), self.previous)

    def test_failed_activation_restores_actual_old_plist_identity(self):
        c, desired = self.candidate()
        seen = []
        def bootstrap(raw, marker, tracking=None):
            seen.append(a.plist_identity(raw)['V4_RELEASE_ID'])
            if raw == desired:
                tracking['process'] = self.new_process
                raise RuntimeError('READINESS_TIMEOUT')
            return {'ok': True, 'identity': {'release_id': 'actual-old'}}
        with patch.object(a, 'process_info', return_value=self.old_process), \
             patch.object(a, 'wait_verified', return_value={'ok': True}), \
             patch.object(a, 'unload') as unload, \
             patch.object(a, 'service_state', side_effect=[('running', self.new_process), ('stopped', None)]), \
             patch.object(a, 'bootstrap_and_verify', side_effect=bootstrap), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.activate_locked(c), 2)
            self.assertEqual(seen, ['new', 'actual-old'])
            self.assertEqual(self.live.read_bytes(), self.previous)
            self.assertEqual(unload.call_count, 2)
        self.assertEqual((c / 'activation-attempt.json').read_text(), 'previous-failure-evidence')
        records = list(c.glob('activation-attempt-*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['status'], 'ROLLED_BACK_AFTER_FAILED_ACTIVATION')

    def test_live_drift_before_bootout_stops_without_touching_job(self):
        c, _ = self.candidate()
        foreign = plist('concurrent-owner')
        def baseline(*args, **kwargs):
            self.live.write_bytes(foreign)
            return {'ok': True}
        with patch.object(a, 'process_info', return_value=self.old_process), \
             patch.object(a, 'wait_verified', side_effect=baseline), patch.object(a, 'unload') as unload:
            with self.assertRaisesRegex(ValueError, 'CAS_CHANGED'):
                a.activate_locked(c)
            unload.assert_not_called()
            self.assertEqual(self.live.read_bytes(), foreign)

    def test_live_drift_after_unload_is_never_overwritten_by_recovery(self):
        c, _ = self.candidate()
        foreign = plist('concurrent-owner')
        with patch.object(a, 'process_info', return_value=self.old_process), \
             patch.object(a, 'wait_verified', return_value={'ok': True}), \
             patch.object(a, 'unload', side_effect=lambda: self.live.write_bytes(foreign)) as unload, \
             patch.object(a, 'bootstrap_and_verify') as bootstrap, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.activate_locked(c), 2)
            self.assertEqual(self.live.read_bytes(), foreign)
            unload.assert_called_once()
            bootstrap.assert_not_called()
        record = json.loads(next(c.glob('activation-attempt-*.json')).read_text())
        self.assertEqual(record['rollback_error'], 'RECOVERY_PLIST_CAS_CONFLICT')

    def test_atomic_plist_rechecks_cas_immediately_before_replace(self):
        foreign = plist('concurrent-owner')
        real_fsync = a.os.fsync
        def drift(fd):
            real_fsync(fd)
            self.live.write_bytes(foreign)
        with patch.object(a.os, 'fsync', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'CAS_CHANGED'):
                a.atomic_plist(plist('new'), expected_sha=a.sha256_bytes(self.previous))
        self.assertEqual(self.live.read_bytes(), foreign)

    def test_recovery_refuses_unknown_process(self):
        desired = plist('new')
        self.live.write_bytes(desired)
        with patch.object(a, 'service_state', return_value=('running', {'pid': '999', 'last_exit': '0'})), \
             patch.object(a, 'unload') as unload:
            with self.assertRaisesRegex(ValueError, 'DESIRED_PROCESS_UNCONFIRMED'):
                a.recover_previous(self.previous, desired, self.old_process, {'process': self.new_process})
            unload.assert_not_called()
            self.assertEqual(self.live.read_bytes(), desired)

    def crashed_candidate(self):
        value = plistlib.loads(plist('new', self.root / 'new', 'new-manifest'))
        value['ProgramArguments'] = ['/runtime/python', '-B', '-m', 'apps.api.v4_api.run', '--port', '8873']
        value['EnvironmentVariables']['EMPTY_PROXY'] = ''
        return plistlib.dumps(value)

    def loaded_job_print(self, raw):
        value = plistlib.loads(raw)
        lines = [a.JOB + ' = {', '\tpath = ' + str(self.live), '\ttype = LaunchAgent',
                 '\tstate = not running', '\tprogram = ' + value['ProgramArguments'][0], '\targuments = {']
        lines += ['\t\t' + item for item in value['ProgramArguments']]
        lines += ['\t}', '\tworking directory = ' + value['WorkingDirectory'],
                  '\tinherited environment = {', '\t\tV4_RELEASE_ID => ignored-inherited', '\t}',
                  '\tenvironment = {']
        lines += ['\t\t' + key + ' => ' + item for key, item in value['EnvironmentVariables'].items()]
        lines += ['\t}', '\tlast exit code = 1', '}']
        return '\n'.join(lines) + '\n'

    def test_bootstrap_immediate_exit_proves_loaded_job_and_recovers_old_release(self):
        desired = self.crashed_candidate()
        self.live.write_bytes(desired)
        crashed = {'pid': '-', 'last_exit': '1'}
        tracking = {}
        with patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             patch.object(a, 'process_info', return_value=crashed), \
             patch.object(a.time, 'monotonic', side_effect=[0, 0.1, 61]), patch.object(a.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'READINESS_TIMEOUT'):
                a.bootstrap_and_verify(desired, a.MARKER, tracking)
        self.assertNotIn('process', tracking)
        self.assertEqual(tracking['bootstrapped_plist_sha256'], a.sha256_bytes(desired))
        with patch.object(a, 'service_state', side_effect=[('running', crashed), ('stopped', None)]), \
             patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, self.loaded_job_print(desired), '')), \
             patch.object(a, 'process_info', return_value=crashed), patch.object(a, 'port_listening', return_value=False), \
             patch.object(a, 'unload') as unload, \
             patch.object(a, 'bootstrap_and_verify', return_value={'ok': True}) as bootstrap:
            self.assertTrue(a.recover_previous(self.previous, desired, self.old_process, tracking)['ok'])
            unload.assert_called_once()
            bootstrap.assert_called_once_with(self.previous, None)
        self.assertEqual(self.live.read_bytes(), self.previous)

    def test_captured_candidate_pid_then_exit_recovers_owned_loaded_job(self):
        desired = self.crashed_candidate()
        self.live.write_bytes(desired)
        crashed = {'pid': '-', 'last_exit': '1'}
        tracking = {'process': self.new_process, 'bootstrapped_plist_sha256': a.sha256_bytes(desired)}
        with patch.object(a, 'service_state', side_effect=[('running', crashed), ('stopped', None)]), \
             patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, self.loaded_job_print(desired), '')), \
             patch.object(a, 'process_info', return_value=crashed), patch.object(a, 'port_listening', return_value=False), \
             patch.object(a, 'unload') as unload, patch.object(a, 'bootstrap_and_verify', return_value={'ok': True}):
            self.assertTrue(a.recover_previous(self.previous, desired, self.old_process, tracking)['ok'])
            unload.assert_called_once()
        self.assertEqual(self.live.read_bytes(), self.previous)

    def test_loaded_no_pid_without_successful_bootstrap_proof_is_refused(self):
        desired = self.crashed_candidate()
        self.live.write_bytes(desired)
        with patch.object(a, 'service_state', return_value=('running', {'pid': '-', 'last_exit': '1'})), \
             patch.object(a, 'unload') as unload:
            with self.assertRaisesRegex(ValueError, 'LOADED_JOB_OWNERSHIP_UNCONFIRMED'):
                a.recover_previous(self.previous, desired, self.old_process, {})
            unload.assert_not_called()
        self.assertEqual(self.live.read_bytes(), desired)

    def test_loaded_no_pid_foreign_loaded_config_is_refused(self):
        desired = self.crashed_candidate()
        self.live.write_bytes(desired)
        printed = self.loaded_job_print(desired)
        foreign_configs = [
            printed.replace('\tworking directory = ' + str(self.root / 'new/app'), '\tworking directory = /foreign/app'),
            printed.replace('V4_RELEASE_ID => new', 'V4_RELEASE_ID => foreign'),
            printed.replace('V4_RELEASE_MANIFEST_SHA256 => new-manifest', 'V4_RELEASE_MANIFEST_SHA256 => foreign'),
            printed.replace('\t\tapps.api.v4_api.run', '\t\tforeign.module'),
            printed.replace('\tpath = ' + str(self.live), '\tpath = /foreign.plist'),
            printed.replace('\tlast exit code = 1', '\tpid = 999\n\tlast exit code = 1'),
            printed.replace('\tenvironment = {', '\tother environment = {'),
        ]
        crashed = {'pid': '-', 'last_exit': '1'}
        for output in foreign_configs:
            with self.subTest(output=output), \
                 patch.object(a, 'service_state', return_value=('running', crashed)), \
                 patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, output, '')), \
                 patch.object(a, 'unload') as unload, patch.object(a, 'bootstrap_and_verify') as bootstrap:
                with self.assertRaisesRegex(ValueError, 'LOADED_JOB_CONFIG_CONFLICT'):
                    a.recover_previous(self.previous, desired, self.old_process,
                                       {'bootstrapped_plist_sha256': a.sha256_bytes(desired)})
                unload.assert_not_called()
                bootstrap.assert_not_called()
                self.assertEqual(self.live.read_bytes(), desired)

    def test_loaded_no_pid_process_appearing_during_print_is_refused(self):
        desired = self.crashed_candidate()
        self.live.write_bytes(desired)
        crashed = {'pid': '-', 'last_exit': '1'}
        with patch.object(a, 'service_state', return_value=('running', crashed)), \
             patch.object(a, 'launchctl', return_value=subprocess.CompletedProcess([], 0, self.loaded_job_print(desired), '')), \
             patch.object(a, 'process_info', return_value={'pid': '999', 'last_exit': '0'}), \
             patch.object(a, 'unload') as unload:
            with self.assertRaisesRegex(ValueError, 'LOADED_JOB_PROCESS_CHANGED'):
                a.recover_previous(self.previous, desired, self.old_process,
                                   {'bootstrapped_plist_sha256': a.sha256_bytes(desired)})
            unload.assert_not_called()
        self.assertEqual(self.live.read_bytes(), desired)

    def test_candidate_wrong_working_directory_rejected_before_bootout(self):
        c, desired = self.candidate()
        value = plistlib.loads(desired)
        value['WorkingDirectory'] = '/old/app'
        with self.assertRaisesRegex(ValueError, 'LAUNCH_CONFIG_MISMATCH'):
            a.candidate_config(plistlib.dumps(value), c, {'release_id': 'new'},
                               value['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256'])

    def test_real_edan_shared_lock_rejects_concurrent_writer(self):
        # Real existing lock implementation, isolated path; no launchctl calls.
        with a.release_lock():
            with self.assertRaisesRegex(ValueError, 'API_RELEASE_SHARED_LOCK_BUSY'):
                with a.release_lock():
                    self.fail('concurrent release lock acquired')

    def test_packaging_moves_cwd_and_only_declared_identity_fields(self):
        spec = importlib.util.spec_from_file_location('package_supplement', SCRIPT.with_name('package_release.py'))
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        before = plistlib.loads(self.previous)
        before['ProgramArguments'] = ['python', '-m', 'apps.api.v4_api.run', '--port', '8873']
        before['EnvironmentVariables'].update(RESEARCH_ONLY='1', ORDERS_SENT='false', SHARED_BINDING='/unchanged')
        after = package.candidate_launch_plist(plistlib.dumps(before), Path('/new/app'), 'new',
                                              Path('/new/release-manifest.json'), 'new-sha')
        self.assertEqual(after['WorkingDirectory'], '/new/app')
        self.assertEqual(after['ProgramArguments'], before['ProgramArguments'])
        expected = dict(before['EnvironmentVariables'], V4_APP_ROOT='/new/app', V4_RELEASE_ID='new',
                        V4_RELEASE_MANIFEST_PATH='/new/release-manifest.json', V4_RELEASE_MANIFEST_SHA256='new-sha')
        self.assertEqual(after['EnvironmentVariables'], expected)
        self.assertEqual(set(after), set(before))

    def test_activate_uses_shared_lock(self):
        events = []
        @contextlib.contextmanager
        def lock():
            events.append('enter')
            yield
            events.append('exit')
        with patch.object(a, 'release_lock', lock), patch.object(a, 'activate_locked', side_effect=lambda c: events.append('activate') or 0):
            self.assertEqual(a.activate(self.root), 0)
        self.assertEqual(events, ['enter', 'activate', 'exit'])


if __name__ == '__main__':
    unittest.main()
