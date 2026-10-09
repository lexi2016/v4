"""Offline retained-failure-page contract candidates; never remote capture."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import shutil
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('partial_owner_support',Path(__file__).with_name('test_v5_private_owner.py'))
support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)
from v4.manager_research.workspace_announcements import _validate_failed_body_pages

def sha(raw):return hashlib.sha256(raw).hexdigest()

class FailedPartialPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='failed-prefix-fixture-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();(self.root/'receipts').mkdir();(self.root/'article_receipts').mkdir()

    def fixture(self,count,total,code='AN202610081830210432',error='BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN',title='Offline retained partial notice',stock='00001.HK'):
        pages=[]
        for index in range(1,count+1):
            text='Offline fixture page %d'%index
            url='https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=%s&client_source=web&page_index=%d'%(code,index)
            raw_sha=sha(('raw fixture %s page %d'%(code,index)).encode())
            ref={'request':{'source':'EASTMONEY_HK','method':'GET','url':url},
                 'blob_sha256':sha(('envelope %s page %d'%(code,index)).encode()),'body_sha256':raw_sha,
                 'retrieved_at':'2026-10-09T00:00:00+00:00'}
            page={'page_index':index,'page_total':total,'source_ref':ref,'raw_body_sha256':raw_sha,
                  'retrieved_at':ref['retrieved_at'],'notice_date':'2026-10-08 00:00:00',
                  'notice_title':title,'text':text,'text_sha256':sha(text.encode()),'source_stock_codes_matched':[stock]}
            metadata={'art_code':code,'notice_title':title,'notice_date':page['notice_date'],
                'page_index':index,'page_total':total,'text_characters':len(text),'text_sha256':page['text_sha256'],
                'matched_source_issuer_codes':[stock]}
            request={'status':'CAPTURED','art_code':code,'kind':'body','page_index':index,'request_url':url,
                'source_ref':ref,'raw_body_sha256':raw_sha,'retrieved_at':ref['retrieved_at'],'content_metadata':metadata}
            (self.root/'receipts'/(sha(url.encode())+'.json')).write_text(json.dumps(request))
            pages.append(page)
        body={'body_status':'BODY_CAPTURE_FAILED','content_page_count':total if count else None,
              'pages':pages,'body_text':None,'body_text_sha256':None}
        original={'body_status':'BODY_CAPTURE_FAILED','content_api_pages':copy.deepcopy(pages)}
        receipt={'art_code':code,'body_status':'BODY_CAPTURE_FAILED','content_api_pages_captured':count,
            'error_code':error,'body_file_sha256':sha(b'fixture body artifact')}
        article={**receipt,'status':'BODY_CAPTURE_FAILED','page_count':count}
        (self.root/'article_receipts'/(code+'.json')).write_text(json.dumps(article))
        listing={'title':title,'source_issuer_codes':[{'code':stock}]}
        return body,original,receipt,listing

    def validate(self,values):return _validate_failed_body_pages(*values,'2026-10-08',self.root)

    def test_real_retained_page_count_shapes_remain_failed(self):
        for count,total,code,error in [(60,108,'AN202610081830210432','BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN'),
                                      (27,86,'AN202610081830209405','BODY_CAPTURE_FAILED:ValueError')]:
            with self.subTest(code=code):
                values=self.fixture(count,total,code,error);before=copy.deepcopy(values)
                self.assertEqual(self.validate(values),(count,total))
                self.assertEqual(values,before)
                self.assertEqual(values[0]['body_status'],'BODY_CAPTURE_FAILED')
                self.assertIsNone(values[0]['body_text'])
                self.assertEqual(values[2]['error_code'],error)

    def test_missing_middle_page_is_rejected(self):
        values=self.fixture(4,8);values[0]['pages'].pop(1);values[1]['content_api_pages']=copy.deepcopy(values[0]['pages']);values[2]['content_api_pages_captured']=3
        with self.assertRaisesRegex(ValueError,'PAGE_SEQUENCE_INVALID'):self.validate(values)

    def test_out_of_order_pages_are_rejected(self):
        values=self.fixture(3,8);values[0]['pages'].reverse();values[1]['content_api_pages']=copy.deepcopy(values[0]['pages'])
        with self.assertRaisesRegex(ValueError,'PAGE_SEQUENCE_INVALID'):self.validate(values)

    def test_page_text_sha_mismatch_is_rejected(self):
        values=self.fixture(2,8);values[0]['pages'][0]['text']+=' changed';values[1]['content_api_pages']=copy.deepcopy(values[0]['pages'])
        with self.assertRaisesRegex(ValueError,'TEXT_SHA_MISMATCH'):self.validate(values)

    def test_page_source_sha_mismatch_is_rejected(self):
        values=self.fixture(2,8);values[0]['pages'][0]['source_ref']['body_sha256']='0'*64;values[1]['content_api_pages']=copy.deepcopy(values[0]['pages'])
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING_MISMATCH'):self.validate(values)

    def test_page_total_drift_is_rejected(self):
        values=self.fixture(2,8);values[0]['pages'][1]['page_total']=9;values[1]['content_api_pages']=copy.deepcopy(values[0]['pages'])
        with self.assertRaisesRegex(ValueError,'FAILED_PAGE_IDENTITY_INVALID'):self.validate(values)

    def test_original_page_disagreement_is_rejected(self):
        values=self.fixture(2,8);values[1]['content_api_pages'].pop()
        with self.assertRaisesRegex(ValueError,'FAILED_PAGE_BINDING_INVALID'):self.validate(values)

    def test_original_error_cannot_be_replaced(self):
        values=self.fixture(2,8);values[2]['error_code']='OTHER_FAILURE'
        with self.assertRaisesRegex(ValueError,'FAILED_ARTICLE_RECEIPT_MISMATCH'):self.validate(values)

    def test_failed_pages_cannot_be_promoted_to_complete(self):
        values=self.fixture(2,8);values[0]['body_status']='COMPLETE_CONTENT_API_BODY'
        with self.assertRaisesRegex(ValueError,'FAILED_PAGE_BINDING_INVALID'):self.validate(values)

    def test_request_receipt_source_binding_is_required(self):
        values=self.fixture(2,8);url=values[0]['pages'][0]['source_ref']['request']['url']
        path=self.root/'receipts'/(sha(url.encode())+'.json');data=json.loads(path.read_text());data['source_ref']['blob_sha256']='0'*64;path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'FAILED_PAGE_RECEIPT_MISMATCH'):self.validate(values)

    def test_full_terminal_validator_accepts_retained_failed_prefixes_without_rewriting_source(self):
        spec=importlib.util.spec_from_file_location('partial_capture_fixture',Path(__file__).with_name('test_offline_evidence_recovery.py'))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        base=module.OfflineRecoveryTests
        base.setUpClass()
        self.addCleanup(base.tearDownClass)
        from v4.manager_research.workspace_announcements import validate_terminal_body_capture
        for count,total,error in [(60,108,'BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN'),(27,86,'BODY_CAPTURE_FAILED:ValueError')]:
            with self.subTest(count=count):
                evidence=self.root/str(count)/base.run_id/'evidence'
                shutil.copytree(base.fixture.root/base.prefix,evidence)
                catalog=json.loads((evidence/'catalog_read.json').read_bytes())
                listing=catalog['catalog']['manager_consumer_rows'][1];code=listing['art_code']
                values=self.fixture(count,total,code,error,listing['title'],listing['source_issuer_codes'][0]['code'])
                body_root=evidence/'body_batch'
                for path in (self.root/'receipts').iterdir():shutil.copyfile(path,body_root/'receipts'/path.name)
                original=json.loads((body_root/'bodies'/(code+'.json')).read_bytes())
                original['content_api_pages']=values[0]['pages']
                raw=(json.dumps(original,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
                (body_root/'bodies'/(code+'.json')).write_bytes(raw);body_sha=sha(raw)
                article={**values[2],'status':'BODY_CAPTURE_FAILED','page_count':count,'body_file_sha256':body_sha}
                (body_root/'article_receipts'/(code+'.json')).write_text(json.dumps(article))
                manifest=json.loads((evidence/'body_corpus_manifest.json').read_bytes())
                manifest['article_receipts'][1].update(content_api_pages_captured=count,error_code=error,body_file_sha256=body_sha)
                def write_pair(name,value):
                    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
                    (body_root/name).write_bytes(raw);(evidence/name).write_bytes(raw);return sha(raw)
                manifest_sha=write_pair('body_corpus_manifest.json',manifest)
                corpus=json.loads((evidence/'body_corpus.json').read_bytes())
                corpus['rows'][1].update(pages=values[0]['pages'],content_page_count=total,capture_receipt_sha256=body_sha)
                corpus['source_manifest_sha256']=manifest_sha;corpus_sha=write_pair('body_corpus.json',corpus)
                batch=json.loads((body_root/'batch_receipt.json').read_bytes())
                batch.update(body_corpus_sha256=corpus_sha,body_corpus_manifest_sha256=manifest_sha)
                batch_raw=json.dumps(batch).encode();(body_root/'batch_receipt.json').write_bytes(batch_raw);(evidence/'body_batch_receipt.json').write_bytes(batch_raw)
                capture=json.loads((evidence/'capture_receipt.json').read_bytes())
                capture.update(body_corpus_file_sha256=corpus_sha,body_corpus_manifest_file_sha256=manifest_sha,body_batch_receipt_sha256=sha(batch_raw))
                (evidence/'capture_receipt.json').write_text(json.dumps(capture))
                before=module.snapshot(evidence)
                result=validate_terminal_body_capture(evidence,catalog,'20261009','2026-10-08',expected_run_id=base.run_id)
                self.assertEqual(result['status'],'PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS')
                self.assertEqual(len(result['failed_articles']),1)
                self.assertEqual(result['failed_articles'][0]['captured_page_count'],count)
                self.assertEqual(result['failed_articles'][0]['expected_page_count'],total)
                self.assertEqual(result['failed_articles'][0]['error_code'],error)
                self.assertEqual(module.snapshot(evidence),before)

if __name__=='__main__':unittest.main(verbosity=2)
