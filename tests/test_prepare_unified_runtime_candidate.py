"""Bounded reviewed-removal helper tests; never invokes prepare() or writes a candidate."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ops.prepare_unified_runtime_candidate import (
    MAIN_OVERRIDES, apply_api_registration, apply_main_overrides,
    apply_reviewed_removals, apply_runtime_test_overlay, apply_schedule_repair,
    apply_snapshots, apply_stage_transition_binding, load_snapshot_dir,
    role_baseline, validate_transition_binding_owner,
)

LIVE_R9_API_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/"
    "v4-task-status-date-20261102-r9-api/app/apps/api/v4_api/app.py"
)
F10_BINDING = {
    "app_root": "/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/"
                "f10-daily-20261101-c94609b4e5fff848-main/app",
    "release_id": "f10-daily-20261101-c94609b4e5fff848-main",
    "manifest_sha256": "3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388",
    "trade_date": "20261102",
}
NEW_MAIN_ENV = {"V4_APP_ROOT": "/new-main/app", "V4_RELEASE_ID": "r10-main",
                "V4_RELEASE_MANIFEST_SHA256": "a" * 64}


def sha(raw):return hashlib.sha256(raw).hexdigest()


class ReviewedRemovalTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()

    def test_removed_and_absent_cases_never_create(self):
        relative='ops/reviewed.py';raw=b'reviewed removal\n';target=self.app/relative
        target.parent.mkdir(parents=True);target.write_bytes(raw)
        removed,absent=apply_reviewed_removals(self.app,{relative:sha(raw),'ops/already-absent.py':'0'*64})
        self.assertEqual(removed,[relative]);self.assertEqual(absent,['ops/already-absent.py'])
        self.assertFalse(target.exists());self.assertFalse((self.app/'ops/already-absent.py').exists())

    def test_changed_bytes_are_rejected_without_unlink(self):
        relative='ops/reviewed.py';target=self.app/relative
        target.parent.mkdir(parents=True);target.write_bytes(b'changed bytes\n')
        with self.assertRaisesRegex(ValueError,'REVIEWED_REMOVAL_BYTES_CHANGED'):
            apply_reviewed_removals(self.app,{relative:'0'*64})
        self.assertTrue(target.exists())


class SnapshotAndOverrideTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def _write(path,raw):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

    def test_snapshot_dir_loads_present_roles_and_prefers_directory_api(self):
        snap=self.root/'snap';snap.mkdir()
        rows={'main':{'label':'m','environment':{'V4_APP_ROOT':'/snap-main','V4_RELEASE_MANIFEST_SHA256':'a'*64}},
              'stage':{'label':'s','environment':{'V4_APP_ROOT':'/snap-stage','V4_RELEASE_MANIFEST_SHA256':'b'*64}},
              'api':{'label':'a','environment':{'V4_APP_ROOT':'/snap-api','V4_RELEASE_MANIFEST_SHA256':'c'*64}}}
        for role,row in rows.items():(snap/(role+'.json')).write_text(json.dumps(row))
        (snap/'other.json').write_text('{"ignored":true}')
        loaded=load_snapshot_dir(snap)
        self.assertEqual(set(loaded),set(rows))
        self.assertEqual(load_snapshot_dir(self.root/'absent'),{})
        api_snapshot={'label':'a','environment':{'V4_APP_ROOT':'/old-api','V4_RELEASE_MANIFEST_SHA256':'d'*64}}
        actual={'main':{'environment':{'V4_APP_ROOT':'/base-main'}},
                'stage':{'environment':{'V4_APP_ROOT':'/base-stage'}},'api':api_snapshot}
        refreshed=apply_snapshots(actual,loaded)
        self.assertEqual(refreshed,set(rows))
        self.assertEqual(actual['api'],rows['api'])
        base={'roles':{'main':{'app_root':'/base-main-app','manifest_sha256':'e'*64},
                       'stage':{'app_root':'/base-stage-app','manifest_sha256':'f'*64},
                       'api':{'app_root':'/base-api-app','manifest_sha256':'1'*64}}}
        self.assertEqual(role_baseline(base,actual,'main',True),(Path('/snap-main'),'a'*64))
        self.assertEqual(role_baseline(base,actual,'stage',False),(Path('/base-stage-app'),'f'*64))

    def test_snapshot_dir_rejects_malformed_role_row(self):
        (self.root/'main.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_ROLE_INVALID:main'):
            load_snapshot_dir(self.root)

    def test_main_override_requires_live_preimage_and_frozen_asset(self):
        app=self.root/'app';source=self.root/'source';relative='ops/due.py'
        asset='docs/handoffs/x/due.r10.py';self._write(app/relative,b'live\n')
        self._write(source/asset,b'fixed\n')
        overrides={relative:(sha(b'live\n'),asset,sha(b'fixed\n'))}
        applied=apply_main_overrides(app,source,overrides)
        self.assertEqual((app/relative).read_bytes(),b'fixed\n')
        self.assertEqual(applied[relative]['before_sha256'],sha(b'live\n'))
        self.assertEqual(applied[relative]['asset'],asset)
        with self.assertRaisesRegex(ValueError,'MAIN_OVERRIDE_PREIMAGE_CHANGED'):
            apply_main_overrides(app,source,overrides)
        self._write(app/relative,b'live\n');self._write(source/asset,b'other\n')
        with self.assertRaisesRegex(ValueError,'MAIN_OVERRIDE_BYTES_CHANGED'):
            apply_main_overrides(app,source,overrides)

    def test_main_override_constant_names_live_and_artifact_bytes(self):
        before,asset,after=MAIN_OVERRIDES['ops/run_v4_macos_scheduler_due.py']
        self.assertEqual(before,'e6e18cefb9df37407be7770082d844988ed765a21c33567f1a18c88ad9c65ae7')
        self.assertEqual(after,'ff1130e6e5be64a48b2ac1c0afcd9e8e1b83fe3a8b584f1a225c555268c41fab')
        self.assertEqual(asset,'docs/handoffs/unified-release-20261102/run_v4_macos_scheduler_due.r10.py')


class IdempotencyModeTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def _write(path,raw):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

    def test_schedule_repair_accepts_preimage_or_already_applied(self):
        relative='ops/repair.py';before=self.root/'before';app=self.root/'app';source=self.root/'source'
        self._write(before/relative,b'old\n');self._write(source/relative,b'new\n')
        self.assertEqual(apply_schedule_repair(app,before,source,relative,sha(b'old\n')),'preimage')
        self.assertEqual((app/relative).read_bytes(),b'new\n')
        self._write(before/relative,b'new\n')
        self.assertEqual(apply_schedule_repair(app,before,source,relative,sha(b'old\n')),'already_applied')
        self._write(before/relative,b'unknown\n')
        with self.assertRaisesRegex(ValueError,'SCHEDULE_PREIMAGE_CHANGED'):
            apply_schedule_repair(app,before,source,relative,sha(b'old\n'))

    def test_runtime_test_overlay_accepts_before_after_or_absence(self):
        relative='tests/test_x.py';source=self.root/'source'
        self._write(source/relative,b'frozen\n');after=sha(b'frozen\n');before=sha(b'old\n')
        for name,raw,mode in (('absent',None,'absent'),('before',b'old\n','before'),('after',b'frozen\n','after')):
            app=self.root/name;app.mkdir()
            if raw is not None:self._write(app/relative,raw)
            self.assertEqual(apply_runtime_test_overlay(app,source,relative,before,after),mode)
            self.assertEqual((app/relative).read_bytes(),b'frozen\n')
        changed=self.root/'changed';self._write(changed/relative,b'other\n')
        with self.assertRaisesRegex(ValueError,'RUNTIME_TEST_PREIMAGE_CHANGED'):
            apply_runtime_test_overlay(changed,source,relative,before,after)
        wrong_source=self.root/'wrong-source';self._write(wrong_source/relative,b'not-frozen\n')
        with self.assertRaisesRegex(ValueError,'RUNTIME_TEST_OVERLAY_BYTES_CHANGED'):
            apply_runtime_test_overlay(changed,wrong_source,relative,before,after)

    def test_stage_transition_binding_preserves_real_frozen_owner(self):
        history=[{'app_root':'/old','release_id':'old','manifest_sha256':'b'*64}]
        cfg={'research_transition_owner_binding':dict(F10_BINDING),
             'research_historical_owner_bindings':history,
             'research_owner_binding':{'old':True}}
        before=json.dumps(cfg['research_transition_owner_binding'])
        binding,mode=apply_stage_transition_binding(cfg,NEW_MAIN_ENV,'20261102')
        self.assertEqual(mode,'preserved')
        self.assertEqual(binding,F10_BINDING)
        self.assertEqual(cfg['research_transition_owner_binding'],F10_BINDING)
        self.assertEqual(json.dumps(cfg['research_transition_owner_binding']),before)
        self.assertEqual(binding['release_id'],'f10-daily-20261101-c94609b4e5fff848-main')
        self.assertEqual(binding['trade_date'],'20261102')
        self.assertEqual(cfg['research_historical_owner_bindings'],history)
        self.assertEqual(cfg['research_owner_binding'],{'old':True})

    def test_stage_transition_binding_binds_when_absent(self):
        history=[{'app_root':'/old','release_id':'old','manifest_sha256':'b'*64}]
        cfg={'research_historical_owner_bindings':history,'research_owner_binding':{'old':True}}
        expected={'app_root':'/new-main/app','release_id':'r10-main',
                  'manifest_sha256':'a'*64,'trade_date':'20261101'}
        binding,mode=apply_stage_transition_binding(cfg,NEW_MAIN_ENV,'20261101')
        self.assertEqual(mode,'bound')
        self.assertEqual(binding,expected)
        self.assertEqual(cfg['research_transition_owner_binding'],expected)
        self.assertEqual(cfg['research_historical_owner_bindings'],history)
        self.assertEqual(cfg['research_owner_binding'],{'old':True})

    def test_stage_transition_binding_rejects_malformed_or_altered(self):
        def missing_key(binding):
            value=dict(binding);value.pop('release_id');return value
        cases=[
            ('extra_key',lambda b:{**b,'extra':'x'},'TRANSITION_BINDING_INVALID'),
            ('missing_key',missing_key,'TRANSITION_BINDING_INVALID'),
            ('wrong_type',lambda b:{**b,'app_root':123},'TRANSITION_BINDING_INVALID'),
            ('relative_root',lambda b:{**b,'app_root':'relative/app'},'TRANSITION_BINDING_INVALID'),
            ('empty_release',lambda b:{**b,'release_id':''},'TRANSITION_BINDING_INVALID'),
            ('bad_date',lambda b:{**b,'trade_date':'2026-11-02'},'TRANSITION_BINDING_INVALID'),
            ('altered_date',lambda b:{**b,'trade_date':'20261101'},'TRANSITION_BINDING_DRIFT'),
        ]
        for name,mutate,error in cases:
            with self.subTest(name):
                cfg={'research_transition_owner_binding':mutate(dict(F10_BINDING))}
                with self.assertRaisesRegex(ValueError,error):
                    apply_stage_transition_binding(cfg,NEW_MAIN_ENV,'20261102')

    def test_transition_owner_release_must_still_verify(self):
        root=self.root/'transition';app=root/'app';app.mkdir(parents=True)
        (root/'release-manifest.json').write_bytes(b'{}')
        binding={'app_root':str(app),'release_id':'f10-daily-20261101-c94609b4e5fff848-main',
                 'manifest_sha256':'0'*64,'trade_date':'20261102'}
        with self.assertRaisesRegex(ValueError,'BASE_MANIFEST_CAS_CHANGED'):
            validate_transition_binding_owner(binding,None)

    def test_api_registration_applies_once_and_accepts_applied_bytes(self):
        relative='apps/api/v4_api/app.py';app=self.root/'api'
        anchor='    app.include_router(create_baimao_router(store.root))\n'
        registration=('    from apps.api.v4_api.report_evidence_router import create_report_evidence_router\n'
                      '    app.include_router(create_report_evidence_router(resolved_research_root))\n')
        head='def build(app, store, resolved_research_root):\n'
        self._write(app/relative,(head+anchor+'    return app\n').encode())
        self.assertEqual(apply_api_registration(app),'anchor_applied')
        body=(app/relative).read_text();self.assertEqual(body.count(registration),1)
        self.assertEqual(apply_api_registration(app),'already_registered')
        self.assertEqual((app/relative).read_text(),body)
        partial=self.root/'partial';self._write(partial/relative,
            (head+registration.splitlines()[0]+'\n').encode())
        with self.assertRaisesRegex(ValueError,'API_REGISTRATION_PREIMAGE_CHANGED'):
            apply_api_registration(partial)
        duplicate=self.root/'duplicate';self._write(duplicate/relative,(head+anchor+registration+registration).encode())
        with self.assertRaisesRegex(ValueError,'API_REGISTRATION_PREIMAGE_CHANGED'):
            apply_api_registration(duplicate)
        missing=self.root/'missing';self._write(missing/relative,(head+'    return app\n').encode())
        with self.assertRaisesRegex(ValueError,'API_REGISTRATION_PREIMAGE_CHANGED'):
            apply_api_registration(missing)

    def test_api_registration_matches_real_live_r9_bytes(self):
        if not LIVE_R9_API_APP.is_file(): self.skipTest('live r9 API app unavailable')
        relative='apps/api/v4_api/app.py';app=self.root/'live-api';raw=LIVE_R9_API_APP.read_bytes()
        self._write(app/relative,raw)
        registration=('    from apps.api.v4_api.report_evidence_router import create_report_evidence_router\n'
                      '    app.include_router(create_report_evidence_router(resolved_research_root))\n')
        self.assertEqual(raw.count(registration.encode()),1)
        self.assertEqual(apply_api_registration(app),'already_registered')
        self.assertEqual((app/relative).read_bytes(),raw)


if __name__=='__main__':unittest.main()
