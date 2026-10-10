"""Synthetic transport fixtures; Mac executes original validators and workspace."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.manager_plan import run_manager_plan

BASE=Path(__file__).resolve().parents[1]

class ArchiveWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();inputs={}
        for name in ('manager','materials','us','archives'):
            p=self.root/name;p.mkdir();inputs[name]={'root':str(p),'files':{}}
        output=self.root/'plans';output.mkdir();(output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        self.request=dict(target_date='20261009',now='2026-10-09T06:58:22.011193+00:00',action='read',view='dynamic',selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(output))
        # Field sets are the frozen contract, not a replacement validator.
        tree=ast.parse((BASE/'vendor/archive_reader_baseline/contracts/research.py').read_text())
        fields={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('_ARTICLE_FIELDS','_POOL_FIELDS','DEDUPE_KEY_FIELDS')}
        article={k:'' for k in fields['_ARTICLE_FIELDS']};article.update(article_id='a'*64,dedupe_key='b'*64,source_path_sha256='c'*64,archive_date='20261008',stock_code='00001.HK',stock_name='SYNTHETIC',source_title='Synthetic relation observation',theme='Optical',published_at='2026-10-08T08:00:00+08:00',collected_at='2026-10-08T09:00:00+08:00',first_seen_at='2026-10-08T09:00:00+08:00',recommendation_status='RESEARCH_ONLY',duplicate_evidence_count=1,source_dedup_keys=['synthetic'])
        pool={k:'' for k in fields['_POOL_FIELDS']};pool.update(stock_code='00001.HK',archive_date='20261008',first_seen_at=article['first_seen_at'],collected_at=article['collected_at'],recommendation_status='RESEARCH_ONLY',source_types=[],themes=[],top_catalysts=[])
        self.payload=dict(schema_version='v3_5.research_archive.v1',archive_date='20261008',status='READY',timezone='Asia/Shanghai',source_input_sha256='d'*64,source_schema_version='SYNTHETIC',source_generated_at=article['collected_at'],dedupe_key_fields=list(fields['DEDUPE_KEY_FIELDS']),article_count=1,stock_pool_count=1,source_counts={},articles=[article],stock_pool=[pool],cannot_confirm=['SYNTHETIC'],write_policy='read_only',recommendation_status='RESEARCH_ONLY',production_allowed=False,buy_gate_updated=False,orders_sent=False)
        self.relative='research/archives/20261008.json'
        self.receipt=dict(schema_version='v3_5.research_archive_receipt.v1',archive_date='20261008',payload_path=self.relative,payload_sha256=sha256_json(self.payload),source_input_sha256='d'*64,article_count=1,stock_pool_count=1,production_allowed=False,buy_gate_updated=False,orders_sent=False)
        self.put(self.relative,self.payload);self.put('receipts/'+self.relative,self.receipt);self.put('manifest.json',{self.relative:sha256_json(self.payload)})

    def put(self,name,value):
        raw=canonical_bytes(value);binding=self.request['inputs']['archives'];p=Path(binding['root'])/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);binding['files'][name]=hashlib.sha256(raw).hexdigest()

    def test_actual_workspace_uses_original_archive_binding_and_preserves_missing_acquisition_time(self):
        before={str(p):p.read_bytes() for p in (self.root/'archives').rglob('*') if p.is_file()}
        result=run_manager_plan(self.request);value=result['payload']
        self.assertTrue(value['existing_material_bindings'])
        self.assertEqual(value['existing_material_bindings'][0]['payload_sha256'],sha256_json(self.payload))
        self.assertIn('ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING',json.dumps(value))
        self.assertNotIn('RESEARCH_ARCHIVE_READER_NOT_BOUND',json.dumps(value))
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.root/'archives').rglob('*') if p.is_file()})
        again=run_manager_plan(self.request)
        self.assertEqual(value['input_identity'],again['payload']['input_identity'])

    def test_hash_bound_but_semantically_wrong_receipt_is_rejected_by_original_store(self):
        self.receipt['article_count']=99;self.put('receipts/'+self.relative,self.receipt)
        result=run_manager_plan(self.request)
        self.assertEqual(result['payload']['existing_material_bindings'],[])
        self.assertIn('RESEARCH_ARTIFACT_READ_FAILED:20261008:daily:ValueError',json.dumps(result))
        self.assertIn('research archive manifest or receipt mismatch',json.dumps(result['archive_readback']))

    def test_source_sha_mismatch_fails_before_workspace(self):
        (self.root/'archives'/self.relative).write_text('{}')
        with self.assertRaisesRegex(ValueError,'MANAGER_INPUT_SHA_OR_LIMIT'):run_manager_plan(self.request)

    def test_refresh_saves_same_run_and_independent_readback_with_archive_materials(self):
        self.request['action']='refresh';result=run_manager_plan(self.request)
        self.assertEqual(result['readback']['status'],'MATCHED')
        self.assertTrue(result['payload']['existing_material_bindings'])
        self.assertFalse(result['natural_verified'])

    def test_hourly_and_daily_use_original_independent_trios(self):
        relative='research/hourly/live/20261008/0830.json'
        receipt=dict(self.receipt,schema_version='v3_5.hourly_research_receipt.v1',slot='0830',mode='LIVE',payload_path=relative)
        self.put(relative,self.payload);self.put('receipts/'+relative,receipt)
        self.put('manifest.json',{self.relative:sha256_json(self.payload),relative:sha256_json(self.payload)})
        out=run_manager_plan(self.request)
        self.assertEqual(out['archive_readback']['validated_artifacts'],2)
        self.assertEqual({b['slot'] for b in out['payload']['existing_material_bindings']},{'', '0830'})

    def test_manifest_declared_missing_hourly_is_not_silent_empty(self):
        self.put('manifest.json',{self.relative:sha256_json(self.payload),'research/hourly/live/20261008/0830.json':'e'*64})
        out=run_manager_plan(self.request)
        self.assertIn('RESEARCH_SLOT_READ_FAILED:20261008:ValueError',json.dumps(out['payload']))
        self.assertIn('20261008',out['archive_readback']['rejected_slot_lists'])
        self.assertEqual(out['archive_readback']['validated_artifacts'],1)

    def test_archive_and_us_roots_cannot_overlap(self):
        self.request['inputs']['archives']['root']=self.request['inputs']['us']['root']
        with self.assertRaisesRegex(ValueError,'MANAGER_ARCHIVE_ROOT_OVERLAP'):run_manager_plan(self.request)

    def test_future_cutoff_remains_rejected_before_owner_execution(self):
        self.request['now']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'MANAGER_FUTURE_CUTOFF'):
            run_manager_plan(self.request)
