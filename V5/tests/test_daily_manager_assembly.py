import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from daily_ledger_fixture import make_ledger_fixture
from v5_shadow.daily_manager_assembly import assemble_manager_request
from v5_shadow.daily_tick import default_slots
from v5_shadow.daily_announcement_revision import run_revision
from v5_shadow.announcement_offline_reader import sources,REVISION_APP,REVISION_PIN
from v5_shadow.run_ledger import claim_run,finish_run,read_run
from v5_shadow.digests import sha256_json,canonical_bytes


class DailyManagerAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=make_ledger_fixture(self.addCleanup)
        self.registration={k:self.fixture.identity[k] for k in ('code_sha256','config_sha256','dependency_sha256')}
        self.source=self.fixture.root/'source';self.source.mkdir()
        self.template=dict(target_date='20261009',now='2026-10-09T00:00:00Z',
            inputs={'manager':{'root':str(self.source),'files':{}}},rebound=None,
            manager_output_root=str(self.fixture.root/'separate-output'))
        self.clock=patch('v5_shadow.daily_manager_assembly.datetime');self.mock=self.clock.start();self.addCleanup(self.clock.stop)
        self.mock.now.return_value=datetime(2026,10,9,0,45,5,tzinfo=timezone.utc)

    def assemble(self,lanes):
        return assemble_manager_request(self.template,lanes,self.fixture.root,self.registration)

    def row(self,lane,ref):
        return dict(lane=lane,state={'attempts':[{'readback_verified':True,'product_reference':ref}]})

    def test_sealed_real_cutoff_reused_not_new_plan_every_tick(self):
        first=self.assemble([])
        self.mock.now.return_value=datetime(2026,10,9,0,50,tzinfo=timezone.utc)
        second=self.assemble([])
        self.assertEqual(first,second);self.assertEqual(first['now'],'2026-10-09T00:45:05+00:00')

    def test_rebound_reference_and_new_revision_binding_assembled(self):
        revision=dict(root='/revision',binding_sha256='a'*64,target_date='20261009',
            publication_date='2026-10-08',revision_manifest_sha256='b'*64)
        reference={'run_id':'a'*32,'artifact_sha256':'b'*64,'manifest_sha256':'c'*64,'receipt_sha256':'d'*64}
        result=self.assemble([self.row('announcement',{'binding':revision}),self.row('rebound',{'root':'/observation','reference':reference})])
        self.assertEqual(result['announcement_offline_owner'],revision)
        self.assertEqual(result['rebound_observation']['reference'],reference)

    def test_stale_template_us_and_observation_not_silently_reused(self):
        path='us_mapping_research/20261008/latest.json';p=self.source/path;p.parent.mkdir(parents=True);p.write_bytes(b'{}')
        self.template['inputs']['manager']['files'][path]=hashlib.sha256(b'{}').hexdigest()
        self.template['rebound_observation']={'root':'/old','reference':{}}
        result=self.assemble([])
        self.assertEqual(result['inputs']['manager']['files'],{});self.assertNotIn('rebound_observation',result)

    def test_us_exact_run_bytes_copied_and_changed_pointer_rejected(self):
        run='a'*32;day=self.source/'us_mapping_research/20261009';(day/'runs').mkdir(parents=True)
        daily=dict(run_id=run,target_trade_date='20261009',status='VALID_EMPTY')
        daily['artifact_sha256']=sha256_json(daily)
        raw=canonical_bytes(daily);(day/'runs'/f'{run}.json').write_bytes(raw)
        (day/'latest.json').write_bytes(canonical_bytes(dict(run_id=run,artifact_sha256=daily['artifact_sha256'])))
        row=self.row('us_mapping',dict(target_date='20261009',run_id=run,artifact_sha256=daily['artifact_sha256'],manager_output_root=str(self.source)))
        result=self.assemble([row]);relative=f'us_mapping_research/20261009/runs/{run}.json'
        self.assertEqual((Path(result['inputs']['manager']['root'])/relative).read_bytes(),raw)
        self.assertEqual(result['inputs']['manager']['files'][relative],hashlib.sha256(raw).hexdigest())
        (day/'latest.json').write_bytes(canonical_bytes(dict(run_id='b'*32,artifact_sha256=daily['artifact_sha256'])))
        with self.assertRaisesRegex(ValueError,'HEAD_CHANGED'):self.assemble([row])

    def test_closed_execution_window_can_read_existing_ledger_without_claim(self):
        claim=claim_run(self.fixture.root,self.fixture.identity)
        finish_run(self.fixture.root,claim,self.fixture.success)
        before=list(self.fixture.root.rglob('*'))
        state=read_run(self.fixture.root,self.fixture.identity)
        self.assertEqual(len(state['attempts']),1);self.assertEqual(state['latest_success']['product_reference'],self.fixture.success['product_reference'])
        self.assertEqual(before,list(self.fixture.root.rglob('*')))

    def test_new_defaults_are_explicit_hk_slots_not_legacy_claim(self):
        value=default_slots('20261009')
        self.assertTrue(value['scheduled_at'].endswith('08:00:00+08:00'))
        self.assertTrue(value['plan_at'].endswith('08:45:00+08:00'))
        self.assertEqual(value['schedule_basis'],'NEW_V5_DEFAULT_NOT_VERIFIED_V4_SCHEDULE')

    def test_missing_real_revision_inputs_do_not_invoke_model_or_owner(self):
        with patch('v5_shadow.daily_announcement_revision.subprocess.run') as owner:
            receipt=run_revision({'revision_create':{},'review_identities':None},'attempt')
        owner.assert_not_called();self.assertEqual(receipt['status'],'BLOCKED')

    def test_revision_capsule_is_exact_fixed_assembly(self):
        sources(REVISION_APP,REVISION_PIN)
        self.assertEqual(hashlib.sha256((REVISION_APP/'V5_OWNER_APP_MANIFEST.json').read_bytes()).hexdigest(),REVISION_PIN)
