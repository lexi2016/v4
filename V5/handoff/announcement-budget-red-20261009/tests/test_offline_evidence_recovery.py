"""Offline byte-serialization and BLOCKED recovery candidates. Mac execution only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
spec=importlib.util.spec_from_file_location('recovery_owner_support',Path(__file__).with_name('test_v5_private_owner.py'))
support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)
from ops import run_manager_daily_announcement as daily
from ops.recover_announcement_evidence_offline import recover,prepare_recovered
from ops import recover_announcement_evidence_offline as recovery_module
from ops.run_v5_private_announcement import PrivateOwner
from v4.manager_research.workspace_announcements import validate_terminal_body_capture

def sha(raw):return hashlib.sha256(raw).hexdigest()
def snapshot(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}

class OfflineRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=support.V5PrivateOwnerTests();cls.fixture.setUp()
        rows=[{'art_code':'AN202610080000%04d'%i,'notice_date':'2026-10-08 00:00:00',
            'display_time':'2026-10-08 12:00:00:000','title':'离线 notice %d'%i,
            'codes':[{'market_code':'116','ann_type':'H','stock_code':'%05d'%i,'short_name':'Fixture'}]}
            for i in (1,2)]
        first_body_ready=threading.Event()
        cls.transport_trace=[]
        def transport(url,**kwargs):
            query=parse_qs(urlsplit(url).query)
            if urlsplit(url).path=='/api/security/ann':
                page=int(query['page_index'][0]);data={'list':rows if page==1 else [],'page_index':page,'page_size':20,'total_hits':2}
            else:
                art=query['art_code'][0];i=int(art[-4:])
                if i==2:
                    # Worker submission order is not request admission order.
                    # Do not close the shared gate until body 1 is in flight.
                    if not first_body_ready.wait(timeout=10):
                        cls.transport_trace.append('FIRST_BODY_NOT_ADMITTED')
                        raise AssertionError('FIXTURE_FIRST_BODY_NOT_ADMITTED')
                    cls.transport_trace.append('BODY_2_SYNTHETIC_FAILURE')
                    raise OSError('SYNTHETIC_UNKNOWN_CONSUMPTION')
                data={'art_code':art,'notice_title':rows[i-1]['title'],'notice_date':rows[i-1]['notice_date'],
                    'notice_content':'离线 body','page_size':1,'security':[{'market_uni':'116','stock':'%05d'%i}]}
            response=support.SourceResponse(url=url,final_url=url,status_code=200,body=json.dumps({'success':1,'data':data}).encode(),
                headers={'Content-Type':'application/json'},retrieved_at='2026-10-09T00:00:00+00:00')
            if urlsplit(url).path=='/api/content/ann':
                cls.transport_trace.append('BODY_1_VALID_RESPONSE_READY')
                first_body_ready.set()
            return response
        owner=cls.fixture.owner(transport,initialize=True,capture_enabled=True)
        cls.result=owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])
        cls.run_id=cls.result['evidence_run_id']
        cls.prefix=Path('announcement_agent_runs')/cls.run_id/'evidence'
        # Retain observable terminal identities/errors in assertion output even
        # when the temporary fixture is cleaned up after the Mac run.
        manifest=json.loads((cls.fixture.root/cls.prefix/'body_corpus_manifest.json').read_bytes())
        cls.fixture_receipts=manifest['article_receipts']

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDown();cls.fixture.doCleanups()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='offline-recovery-test-');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.source=self.base/'old';self.out=self.base/'recovery'
        shutil.copytree(self.fixture.root,self.source)
        # Test-only synthetic app trust anchor and fixture root rebinding.
        # Production pins the independently reconstructed 874 app manifest.
        self.source_app=support.APP
        self.trust=patch.object(recovery_module,'TRUSTED_SOURCE_APP_SHA256',
            sha((self.source_app/'V5_OWNER_APP_MANIFEST.json').read_bytes()))
        self.trust.start();self.addCleanup(self.trust.stop)
        identity_path=self.source/'v5_owner_identity.json'
        identity=json.loads(identity_path.read_bytes())
        identity.update(private_root=str(self.source),private_parent=str(self.base))
        identity_path.write_text(json.dumps(identity)+'\n')
        self.evidence=self.source/self.prefix
        # Reproduce the old CLI bug: same JSON values, different actual bytes.
        capture=json.loads((self.evidence/'capture_receipt.json').read_bytes())
        for name,key in [('body_corpus.json','body_corpus_file_sha256'),('body_corpus_manifest.json','body_corpus_manifest_file_sha256'),('body_batch_receipt.json','body_batch_receipt_sha256')]:
            raw=(json.dumps(json.loads((self.evidence/name).read_bytes()),ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
            (self.evidence/name).write_bytes(raw);capture[key]=sha(raw)
        (self.evidence/'capture_receipt.json').write_text(json.dumps(capture,indent=2)+'\n')
        self.policy_sha=sha((self.source/'transport_policy.json').read_bytes())
        self.batch_sha=sha((self.evidence/'body_batch/batch_receipt.json').read_bytes())
        self.original=snapshot(self.source)

    def recover(self):return recover(self.source,self.out,self.run_id,self.policy_sha,self.batch_sha,source_app=self.source_app,identity_sha256=sha((self.source/'v5_owner_identity.json').read_bytes()))

    def test_capture_publishes_exact_authoritative_batch_bytes(self):
        evidence=self.fixture.root/self.prefix
        for top,batch in [('body_corpus.json','body_corpus.json'),('body_corpus_manifest.json','body_corpus_manifest.json'),('body_batch_receipt.json','batch_receipt.json')]:
            self.assertEqual((evidence/top).read_bytes(),(evidence/'body_batch'/batch).read_bytes())
        result=validate_terminal_body_capture(evidence,json.loads((evidence/'catalog_read.json').read_bytes()),'20261009','2026-10-08',expected_run_id=self.run_id)
        self.assertEqual(result['status'],'PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS')
        statuses={row['art_code']:row['body_status'] for row in self.fixture_receipts}
        self.assertEqual(statuses,{'AN2026100800000001':'COMPLETE_CONTENT_API_BODY',
            'AN2026100800000002':'BODY_CAPTURE_FAILED'},self.fixture_receipts)
        self.assertEqual(self.transport_trace,['BODY_1_VALID_RESPONSE_READY','BODY_2_SYNTHETIC_FAILURE'])
        self.assertEqual(len(result['failed_articles']),1,{'receipts':self.fixture_receipts,'transport_trace':self.transport_trace})

    def test_serialization_only_recovery_keeps_originals_and_partial_status(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_BINDING_INVALID'):
            validate_terminal_body_capture(self.evidence,json.loads((self.evidence/'catalog_read.json').read_bytes()),'20261009','2026-10-08',expected_run_id=self.run_id)
        result=self.recover()
        self.assertEqual(result['terminal']['status'],'PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS')
        self.assertEqual(len(result['terminal']['failed_articles']),1,{'receipts':self.fixture_receipts,'transport_trace':self.transport_trace})
        self.assertEqual(snapshot(self.source),self.original)
        for name in result['original_files']:self.assertEqual((self.out/'original'/name).read_bytes(),self.original[name])
        self.assertEqual((self.out/'transport_policy.json').read_bytes(),self.original['transport_policy.json'])
        self.assertFalse((self.out/self.prefix/'semantic_catalog.json').exists())

    def test_authoritative_body_tampering_is_rejected(self):
        path=self.evidence/'body_batch/body_corpus.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'AUTHORITATIVE_BODY_SHA_MISMATCH'):self.recover()
        self.assertFalse(self.out.exists())

    def test_changed_top_level_json_cannot_be_hidden_as_serialization(self):
        path=self.evidence/'body_corpus.json';value=json.loads(path.read_bytes());value['article_count']=999
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'NOT_SERIALIZATION_ONLY'):self.recover()
        self.assertFalse(self.out.exists())

    def test_expected_blocked_policy_sha_is_mandatory(self):
        self.policy_sha='0'*64
        with self.assertRaisesRegex(ValueError,'POLICY_SHA_MISMATCH'):self.recover()
        self.assertFalse(self.out.exists())

    def test_recovery_root_and_descendants_cannot_initialize_network_owner(self):
        self.recover()
        for root in (self.out,self.out/'new-owner'):
            with self.assertRaisesRegex(ValueError,'OFFLINE_RECOVERY_NETWORK_FORBIDDEN'):
                PrivateOwner(root,self.base,[self.base/'v4'],initialize=True,capture_enabled=True)
        self.assertEqual(snapshot(self.source),self.original)

    def test_missing_real_reader_output_remains_missing(self):
        self.recover()
        with self.assertRaises(FileNotFoundError):prepare_recovered(self.out,self.out/'semantic_catalog.json')
        self.assertFalse((self.out/'semantic_catalog.json').exists())

    def test_wrong_source_identity_root_is_rejected(self):
        path=self.source/'v5_owner_identity.json';value=json.loads(path.read_bytes())
        value['private_root']=str(self.base/'other');path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'IDENTITY_ROOT_MISMATCH'):self.recover()
        self.assertFalse(self.out.exists())

    def test_wrong_identity_manifest_is_rejected(self):
        path=self.source/'v5_owner_identity.json';value=json.loads(path.read_bytes())
        value['app_manifest_sha256']='0'*64;path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'APP_MANIFEST_BINDING_INVALID'):self.recover()
        self.assertFalse(self.out.exists())

    def test_wrong_policy_manifest_is_rejected_even_with_updated_expected_policy_sha(self):
        path=self.source/'transport_policy.json';value=json.loads(path.read_bytes())
        value['app_manifest_sha256']='0'*64;path.write_text(json.dumps(value))
        self.policy_sha=sha(path.read_bytes())
        with self.assertRaisesRegex(ValueError,'APP_MANIFEST_BINDING_INVALID'):self.recover()
        self.assertFalse(self.out.exists())

    def test_forbidden_output_child_and_ancestor_are_rejected(self):
        path=self.source/'v5_owner_identity.json';value=json.loads(path.read_bytes())
        banned=self.base/'v4-output';value['forbidden_roots'].append(str(banned/'state'))
        path.write_text(json.dumps(value))
        for output in (banned,banned/'state'/'recovery'):
            with self.subTest(output=output):
                self.out=output
                with self.assertRaisesRegex(ValueError,'OUTPUT_FORBIDDEN_ROOT'):self.recover()
                self.assertFalse(output.exists())

    def test_source_app_manifest_bytes_must_match_trusted_874_anchor(self):
        self.source_app=self.base/'source-app';shutil.copytree(support.APP,self.source_app)
        path=self.source_app/'V5_OWNER_APP_MANIFEST.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'APP_MANIFEST_SHA_MISMATCH'):self.recover()
        self.assertFalse(self.out.exists())

    def test_source_app_file_must_match_manifest(self):
        self.source_app=self.base/'source-app';shutil.copytree(support.APP,self.source_app)
        path=self.source_app/'ops/run_v5_private_announcement.py';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'APP_FILE_SHA_MISMATCH'):self.recover()
        self.assertFalse(self.out.exists())

    def test_boolean_to_integer_change_is_not_serialization(self):
        # Preserve both Python equality and the old receipt SHA binding to prove
        # rejection comes from strict JSON types, not another guard.
        path=self.evidence/'body_corpus_manifest.json';value=json.loads(path.read_bytes())
        accounting=value['limits']['byte_accounting']
        self.assertIs(accounting['physical_network_bytes_verified'],False)
        accounting['physical_network_bytes_verified']=0
        authoritative=json.loads((self.evidence/'body_batch/body_corpus_manifest.json').read_bytes())
        self.assertEqual(value,authoritative,'ordinary Python equality misses this change')
        raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();path.write_bytes(raw)
        capture_path=self.evidence/'capture_receipt.json';capture=json.loads(capture_path.read_bytes())
        capture['body_corpus_manifest_file_sha256']=sha(raw);capture_path.write_text(json.dumps(capture))
        with self.assertRaisesRegex(ValueError,'NOT_SERIALIZATION_ONLY'):self.recover()
        self.assertFalse(self.out.exists())

    def test_nested_json_types_are_compared_strictly(self):
        same=recovery_module._same_json_structure
        self.assertFalse(same({'x':[False]},{'x':[0]}))
        self.assertFalse(same({'x':[True]},{'x':[1]}))
        self.assertFalse(same({'x':1},{'x':1.0}))
        self.assertTrue(same({'x':[False,1,None,'正文']},{'x':[False,1,None,'正文']}))

if __name__=='__main__':unittest.main(verbosity=2)
