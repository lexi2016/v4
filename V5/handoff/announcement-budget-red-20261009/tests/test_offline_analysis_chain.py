"""Synthetic offline downstream contract candidates; never real classifications."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('analysis_partial_support',Path(__file__).with_name('test_failed_partial_pages.py'))
support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)
from ops import recover_announcement_evidence_offline as recovery
from ops.run_v5_offline_analysis import OfflineAnalysisOwner
from v4.manager_research import announcement_analysis as analysis
from v4.manager_research.workspace_projection import digest

def sha(raw):return hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n')

class OfflineAnalysisChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.partial=support.FailedPartialPageTests();cls.partial.setUp()
        cls.partial.test_full_terminal_validator_accepts_retained_failed_prefixes_without_rewriting_source()
        cls.seed=sys.modules['partial_capture_fixture'].OfflineRecoveryTests
        cls.run_id=cls.seed.run_id
        cls.prefix=Path('announcement_agent_runs')/cls.run_id/'evidence'

    @classmethod
    def tearDownClass(cls):cls.partial.doCleanups()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='offline-analysis-chain-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=self.root/'source';self.derived=self.root/'derived'
        shutil.copytree(self.partial.root/'60'/self.run_id/'evidence',self.source/self.prefix)
        source_identity=json.loads((self.seed.fixture.root/'v5_owner_identity.json').read_bytes())
        source_identity.update(private_root=str(self.source),private_parent=str(self.root))
        dump(self.source/'v5_owner_identity.json',source_identity)
        shutil.copyfile(self.seed.fixture.root/'transport_policy.json',self.source/'transport_policy.json')
        self.source_before={str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        app=support.support.APP
        with patch.object(recovery,'TRUSTED_SOURCE_APP_SHA256',sha((app/'V5_OWNER_APP_MANIFEST.json').read_bytes())):
            recovery.recover(self.source,self.derived,self.run_id,sha((self.source/'transport_policy.json').read_bytes()),
                sha((self.source/self.prefix/'body_batch/batch_receipt.json').read_bytes()),source_app=app,
                identity_sha256=sha((self.source/'v5_owner_identity.json').read_bytes()))
        self.recovery_sha=sha((self.derived/'recovery_receipt.json').read_bytes())
        self.owner=OfflineAnalysisOwner(self.derived,self.recovery_sha,adopt=True)
        self.policy=(self.derived/'transport_policy.json').read_bytes()
        evidence=self.derived/self.prefix;catalog=json.loads((evidence/'catalog_read.json').read_bytes())
        semantic={'schema':'v4.announcement-semantic-catalog.v2','status':'PASS_SYNTHETIC_TEST_ONLY',
            'target_research_date':'20261009','target_notice_date':'2026-10-08','row_count':2,
            'records':[{'art_code':row['art_code'],'title':row['title'],'issuer_codes':row['source_issuer_codes']}
                       for row in catalog['catalog']['manager_consumer_rows']]}
        self.semantic=self.derived/'semantic_catalog.json';dump(self.semantic,semantic)
        self.reviewer=self.derived/'reviewer_output.json'
        dump(self.reviewer,{'schema_version':'v4.manager_research.announcement_agent_review.v1','review_conclusion':'PASS',
            'target_trade_date':'20261009','publication_date':'2026-10-08','evidence_run_id':self.run_id,
            'decision_status':'NOT_ASSESSED','decision_payload_sha256':None,'reader_identity':'fixture-reader',
            'reviewer_identity':'fixture-independent-reviewer','reviewed_at':'2026-10-09T12:00:00+00:00',
            'catalog_product_sha256':catalog['catalog']['sha256'],'semantic_catalog_sha256':sha(self.semantic.read_bytes()),
            'body_corpus_sha256':sha((evidence/'body_corpus.json').read_bytes())})

    def tearDown(self):
        self.assertEqual((self.derived/'transport_policy.json').read_bytes(),self.policy)
        for name,raw in self.source_before.items():self.assertEqual((self.source/name).read_bytes(),raw)
        self.assertTrue((self.derived/'OFFLINE_RECOVERY.json').is_file())
        self.assertFalse((self.derived/'v5_owner_identity.json').exists())

    def register(self):
        return self.owner.execute(['register-handoff','--semantic-catalog',str(self.semantic),
            '--reviewer-output',str(self.reviewer),'--parent-task-id','synthetic-fixture-task',
            '--reader-identity','fixture-reader','--reviewer-identity','fixture-independent-reviewer'])

    def product(self):return json.loads((self.derived/self.prefix/'analysis_product.json').read_bytes())

    def test_prepare_verify_import_and_readback_keep_failed_pages_unassessed(self):
        prepared=self.owner.execute(['prepare','--semantic-catalog',str(self.semantic)])
        self.assertEqual(prepared['status'],'PREPARED_EXACT_INPUTS')
        self.assertEqual(prepared['body_capture_failed_article_count'],1)
        self.register();self.assertEqual(self.owner.execute(['verify'])['status'],'REGISTERED_HANDOFF_VERIFIED')
        imported=self.owner.execute(['import']);binding=imported['manager_binding']
        self.assertEqual(binding['status'],'PRIVATE_OWNER_READBACK_VERIFIED')
        self.assertFalse(binding['manager_ui_integrated'])
        readback=self.owner.execute(['readback'])
        self.assertEqual(readback['status'],'OWNER_READBACK_VERIFIED')
        product=self.product();failed=next(row for row in product['records'] if row['body_status']=='BODY_CAPTURE_FAILED')
        self.assertEqual(failed['selection_status'],'NOT_ASSESSED')
        self.assertEqual(failed['analysis_kind'],'TEXT_INSUFFICIENT_UNASSESSED')
        self.assertEqual(failed['body_page_citations'],[])
        self.assertIsNone(failed['exact_quote'])
        self.assertEqual(len(failed['body_capture_failure']['retained_pages']),60)
        self.assertEqual(failed['body_capture_failure']['expected_page_count'],108)
        self.assertEqual(failed['body_capture_failure']['error_code'],'BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN')
        self.assertEqual(sha((self.derived/binding['product_path']).read_bytes()),binding['product_file_sha256'])
        self.assertTrue((self.derived/binding['owner_import_receipt_path']).is_file())

    def test_import_without_registered_independent_review_is_rejected(self):
        with self.assertRaises((ValueError,FileNotFoundError)):self.owner.execute(['import'])
        self.assertFalse((self.derived/'manager_binding.v1.json').exists())

    def test_reader_and_reviewer_identity_cannot_match(self):
        data=json.loads(self.reviewer.read_bytes());data['reviewer_identity']='fixture-reader';dump(self.reviewer,data)
        with self.assertRaisesRegex(ValueError,'REVIEW_OUTPUT_INVALID'):
            self.owner.execute(['register-handoff','--semantic-catalog',str(self.semantic),'--reviewer-output',str(self.reviewer),
                '--parent-task-id','fixture','--reader-identity','fixture-reader','--reviewer-identity','fixture-reader'])

    def test_capture_and_foreign_date_or_api_override_are_rejected(self):
        for tokens in (['capture'],['readback','--target-date','20261012'],['import','--api-base','http://127.0.0.1:8873']):
            with self.subTest(tokens=tokens):
                with self.assertRaises(ValueError):self.owner.execute(tokens)
        with self.assertRaisesRegex(ValueError,'CAPTURE_FORBIDDEN'):self.owner.begin_capture('20261009','2026-10-08')

    def test_changed_retained_pages_fail_product_readback_validation(self):
        self.register();product=self.product()
        row=next(row for row in product['records'] if row['body_status']=='BODY_CAPTURE_FAILED')
        row['body_capture_failure']['retained_pages'][0]['text']+=' changed'
        product.pop('sha256');product['sha256']=digest(product)
        with self.assertRaisesRegex(ValueError,'FAILED_PAGES_BINDING_INVALID'):
            analysis.validate_product(product,target_trade_date='20261009',publication_date='2026-10-08',catalog=self.owner.catalog['catalog'])

    def test_failed_projection_cannot_be_promoted_to_assessed(self):
        self.register();product=self.product()
        row=next(row for row in product['records'] if row['body_status']=='BODY_CAPTURE_FAILED');row['selection_status']='SELECTED_EVENT'
        product.pop('sha256');product['sha256']=digest(product)
        with self.assertRaisesRegex(ValueError,'FAILURE_PROJECTION_INVALID'):
            analysis.validate_product(product,target_trade_date='20261009',publication_date='2026-10-08',catalog=self.owner.catalog['catalog'])

    def test_wrong_recovery_receipt_sha_blocks_adoption(self):
        with self.assertRaisesRegex(ValueError,'RECOVERY_SHA_MISMATCH'):OfflineAnalysisOwner(self.derived,'0'*64,adopt=True)

if __name__=='__main__':unittest.main(verbosity=2)
