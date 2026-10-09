"""Isolated V5 owner smoke/integration candidate; no real source or V4 writes."""
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def deny(event,args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind','socket.sendto','subprocess.Popen','os.system'}:
        raise RuntimeError('OFFLINE_OWNER_TEST_NETWORK_FORBIDDEN')
sys.addaudithook(deny)
spec=importlib.util.spec_from_file_location('owner_assembler',ROOT/'tools/assemble_owner_app.py')
assembler=importlib.util.module_from_spec(spec);spec.loader.exec_module(assembler)
APP_TMP=tempfile.TemporaryDirectory(prefix='v5-owner-app-test-')
APP=Path(APP_TMP.name)/'app'
assembler.assemble(APP)
sys.path.insert(0,str(APP))
from ops.run_v5_private_announcement import PrivateOwner,SENTINEL_BASE
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.ports import SourceResponse


def tearDownModule():
    APP_TMP.cleanup()


class V5PrivateOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='v5-owner-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve()
        self.parent=self.base/'v5';self.parent.mkdir()
        self.v4=self.base/'v4';self.v4.mkdir()
        (self.v4/'sentinel').write_bytes(b'V4_UNTOUCHED')
        self.root=self.parent/'state'
        self.calls=[]

    def tearDown(self):
        self.assertEqual(sorted(p.name for p in self.v4.iterdir()),['sentinel'])
        self.assertEqual((self.v4/'sentinel').read_bytes(),b'V4_UNTOUCHED')

    def factory(self,transport):
        def make(**kwargs):
            return HkexOfficialProvider(transport=lambda *a,**kw:None,
                eastmoney_transport=transport,**kwargs)
        return make

    def owner(self,transport=None,**kwargs):
        def forbidden(*args,**kwargs):
            raise AssertionError('unexpected synthetic transport call')
        return PrivateOwner(self.root,self.parent,[self.v4],
            provider_factory=self.factory(transport or forbidden),**kwargs)

    def test_v4_root_and_symlink_are_rejected_before_creation(self):
        with self.assertRaisesRegex(ValueError,'V4_ROOT_FORBIDDEN'):
            PrivateOwner(self.v4/'new',self.v4,[self.v4],initialize=True)
        alias=self.parent/'alias';alias.symlink_to(self.v4,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'SYMLINK_FORBIDDEN'):
            PrivateOwner(alias/'new',self.parent,[self.v4],initialize=True)
        self.assertFalse((self.v4/'new').exists())

    def test_8873_and_bound_argument_overrides_are_rejected(self):
        owner=self.owner(initialize=True)
        with self.assertRaisesRegex(ValueError,'EXTERNAL_API_FORBIDDEN'):
            owner.request('http://127.0.0.1:8873','/api/v4/manager/research/announcements/refresh',method='POST')
        with self.assertRaisesRegex(ValueError,'BOUND_ARGUMENT_OVERRIDE_FORBIDDEN'):
            owner.execute(['capture','--api-base=http://127.0.0.1:8873'])
        with self.assertRaisesRegex(ValueError,'ARTIFACT_OUTSIDE_PRIVATE_ROOT'):
            owner.execute(['build-reviewed','--target-date','20261009','--publication-date','2026-10-08',
                '--catalog-read',str(self.root/'catalog'),'--semantic-catalog',str(self.root/'semantic'),
                '--body-corpus',str(self.root/'body'),'--review-receipt',str(self.root/'review'),
                '--out',str(self.v4/'bad.json')])

    def test_capture_requires_explicit_enable(self):
        owner=self.owner(initialize=True)
        with self.assertRaisesRegex(ValueError,'CAPTURE_NOT_ENABLED'):
            owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])
        self.assertFalse((self.root/'transport_policy.json').exists())

    def test_started_capture_cannot_be_reset_by_a_new_instance_or_date(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        with owner.exclusive():owner.begin_capture('20261009','2026-10-08')
        replacement=self.owner(capture_enabled=True)
        with replacement.exclusive():
            with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
                replacement.begin_capture('20261012','2026-10-09')
        self.assertEqual(json.loads((self.root/'transport_policy.json').read_text())['state'],'STARTED')

    def test_403_is_persisted_and_blocks_a_new_instance(self):
        def transport(url,**kwargs):
            self.calls.append(url)
            return SourceResponse(url=url,final_url=url,status_code=403,body=b'{}',
                headers={'Retry-After':'1'},retrieved_at='2026-10-09T00:00:00+00:00')
        owner=self.owner(transport,initialize=True,capture_enabled=True)
        with self.assertRaises(ValueError):
            owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])
        state=json.loads((self.root/'transport_policy.json').read_text())
        self.assertEqual(state['state'],'BLOCKED')
        self.assertEqual(state['accounting']['http_policy']['status_code'],403)
        self.assertEqual(state['accounting']['http_policy']['action'],'STOP')
        replacement=self.owner(transport,capture_enabled=True)
        with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
            replacement.execute(['capture','--target-date','20261012','--publication-date','2026-10-09'])
        self.assertEqual(len(self.calls),1)

    def test_complete_catalog_and_all_21_bodies_share_one_budget(self):
        rows=[{'art_code':'AN202610080000%04d'%i,'notice_date':'2026-10-08 00:00:00',
            'display_time':'2026-10-08 12:00:00:000','title':'Offline notice %d'%i,
            'codes':[{'market_code':'116','ann_type':'H','stock_code':'%05d'%i,'short_name':'Fixture %d'%i}]}
            for i in range(1,22)]
        def transport(url,**kwargs):
            query=parse_qs(urlsplit(url).query)
            if urlsplit(url).path=='/api/security/ann':
                page=int(query['page_index'][0])
                data={'list':rows[(page-1)*20:page*20],'page_index':page,'page_size':20,'total_hits':21}
            else:
                art=query['art_code'][0];index=int(art[-4:]);row=rows[index-1]
                data={'art_code':art,'notice_title':row['title'],'notice_date':row['notice_date'],
                    'notice_content':'Offline body %d'%index,'page_size':1,
                    'security':[{'market_uni':'116','stock':'%05d'%index}]}
            raw=json.dumps({'success':1,'data':data}).encode()
            self.calls.append((url,len(raw)))
            return SourceResponse(url=url,final_url=url,status_code=200,body=raw,
                headers={'Content-Type':'application/json'},retrieved_at='2026-10-09T00:00:00+00:00')
        owner=self.owner(transport,initialize=True,capture_enabled=True)
        result=owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])
        self.assertEqual(result['status'],'PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS')
        catalog=owner.get_announcement_date_catalog('20261009','2026-10-08')
        self.assertEqual(catalog['readback_status'],'VERIFIED')
        self.assertEqual(catalog['catalog']['manager_consumer_row_count'],21)
        self.assertEqual(catalog['catalog']['captured_page_count'],3)
        self.assertTrue(catalog['catalog']['terminal_empty_seen'])
        evidence=self.root/'announcement_agent_runs'/result['evidence_run_id']/'evidence'
        corpus=json.loads((evidence/'body_corpus.json').read_text())
        self.assertEqual(len(corpus['rows']),21)
        self.assertEqual(corpus['transport_complete_body_count'],21)
        self.assertEqual(len(self.calls),24)
        self.assertEqual(owner.gate.requests,24)
        self.assertEqual(owner.gate.response_bytes,sum(size for _,size in self.calls))
        state=json.loads((self.root/'transport_policy.json').read_text())
        self.assertEqual(state['state'],'FINISHED')
        self.assertEqual(state['requests'],24)
        with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
            owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])
        self.assertEqual(len(self.calls),24)

    def test_import_cannot_bypass_registered_reader_and_reviewer_artifacts(self):
        owner=self.owner(initialize=True)
        envelope={'schema_version':'v4.manager_research.announcement_analysis_import_ref.v1',
            'evidence_run_id':'0'*32,'handoff_manifest_sha256':'0'*64,'product_sha256':'0'*64}
        with patch.object(owner,'import_announcement_analysis',side_effect=AssertionError('must validate before import')):
            with self.assertRaises((ValueError,FileNotFoundError)):
                owner.request(SENTINEL_BASE,'/api/v4/manager/research/announcements/analysis/import',
                    method='POST',payload=json.dumps(envelope).encode())


if __name__=='__main__':
    unittest.main(verbosity=2)
