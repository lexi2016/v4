"""Synthetic candidate tests. Execute independently on Mac, never cloud product tests."""
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from v5_shadow.registry_observation import decode
from v5_shadow.manager_plan import run_manager_plan
from test_manager_plan import ManagerPlanAdapterTests


class RegistryObservationTests(unittest.TestCase):
    def setUp(self):
        fixture = ManagerPlanAdapterTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        root = fixture.root/'registry'; root.mkdir()
        self.raw = b'code,name\n00700,Tencent\n'
        (root/'names.csv').write_bytes(self.raw)
        self.binding = dict(root=str(root), files={'names.csv':hashlib.sha256(self.raw).hexdigest()},
                            source_date='20261008', source_label='SYNTHETIC_PANEL', format='CSV_CODE_NAME')

    def test_no_market_cap_or_share_count_required(self):
        self.assertEqual(decode(self.raw,self.binding), {'00700':{'code':'00700','name':'Tencent'}})

    def test_raw_sha_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,'REGISTRY_RAW_SHA'):
            decode(self.raw+b' ',self.binding)

    def test_duplicate_code_and_noncanonical_code_rejected(self):
        for raw in (b'code,name\n700,Tencent\n', b'code,name\n00700,Tencent\n00700,Other\n'):
            binding=copy.deepcopy(self.binding);binding['files']['names.csv']=hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError,'REGISTRY_CODE_NAME_ROW'):decode(raw,binding)

    def test_observation_has_actual_receipt_without_formal_effect(self):
        request=copy.deepcopy(self.fixture.request)
        before=run_manager_plan(request)
        request['registry_observation']=self.binding
        after=run_manager_plan(request)
        payload=after['payload'];observation=payload.pop('registry_research_observation')
        self.assertEqual(payload,before['payload'])
        self.assertTrue(observation['read_receipt']['before_after_raw_sha256_stable'])
        self.assertLessEqual(observation['read_receipt']['observed_started_at'],observation['read_receipt']['observed_finished_at'])
        self.assertIsNone(observation['registry']['original_retrieved_at'])
        self.assertIsNone(observation['registry']['original_available_at'])
        self.assertFalse(observation['formal_eligible'])
        self.assertIn('ARCHIVE_READER_NOT_BOUND',observation['reason_codes'])

    def test_bad_source_is_isolated_observation_gap(self):
        self.binding['files']['names.csv']='0'*64
        request=dict(self.fixture.request,registry_observation=self.binding)
        result=run_manager_plan(request)
        self.assertIn('MANAGER_INPUT_SHA_OR_LIMIT',result['payload']['registry_research_observation']['reason_codes'])
        self.assertIn('daily_channels',result['payload'])

    def test_output_overlap_rejected(self):
        binding=dict(self.binding,root=str(self.fixture.output))
        with self.assertRaisesRegex(ValueError,'REGISTRY_ROOT_OVERLAP'):
            run_manager_plan(dict(self.fixture.request,registry_observation=binding))

    def project_fixture(self, names, body):
        script = """
import json,sys
from v5_shadow.manager_plan import load_owner
load_owner()
from v5_shadow.registry_observation import project,clock
names,body=json.loads(sys.stdin.read())
rows={code:dict(code=code,name=name) for code,name in names.items()}
article=dict(article_id='original-1',source_title=body,body=body,published_at='2026-09-01T00:00:00Z')
payload=dict(archive_date='20261008',articles=[article])
binding=dict(status='VERIFIED',payload_path='20261008/archive.json',payload_sha256='a'*64)
archives=dict(records={'20261008/daily':dict(payload=payload,binding=binding)})
registry=dict(source_label='SYNTHETIC',source_date='20261008',files={'names.csv':'b'*64})
print(json.dumps(project(rows,registry,archives,clock())))
"""
        result=subprocess.run([sys.executable,'-c',script],input=json.dumps([names,body]),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_missing_a_h_pair_keeps_original_rejection(self):
        result=self.project_fixture({'00700':'腾讯控股'},'腾讯控股（600000）推出人工智能大模型产品。')
        self.assertIn('NAME_CODE_PAIR_UNVERIFIED',json.dumps(result))
        material=result['clues'][0]['material']
        self.assertEqual(material['original_article_id'],'original-1')
        self.assertEqual(material['published_at'],'2026-09-01T00:00:00Z')
        self.assertIsNone(material['retrieved_at'])
        self.assertIsNone(material['available_at'])
        self.assertFalse(result['fresh_catalyst_eligible'])

    def test_duplicate_name_does_not_pick_arbitrary_code(self):
        result=self.project_fixture({'00700':'腾讯控股','00701':'腾讯控股'},'腾讯控股推出人工智能大模型产品。')
        self.assertEqual(result['clues'],[])

    def test_subject_propositions_remain_observation_only(self):
        result=self.project_fixture({'00700':'腾讯控股'},'腾讯控股推出人工智能大模型产品。')
        self.assertEqual(len(result['clues']),1)
        self.assertTrue(result['clues'][0]['propositions'])
        self.assertFalse(result['clues'][0]['formal_eligible'])
