"""Risk regression tests. Synthetic source text is never vector acceptance evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from domains.report_evidence import ReportEvidenceService
from infrastructure.report_evidence_index import ReportIndex, digest, structure_chunks
from infrastructure.report_evidence_sidecar import on_stage_completed, sidecar_key

class Tokens:
    def encode(self,text):
        class E:pass
        e=E();e.ids=list(range(len(text)));e.offsets=[(i,i+1) for i in range(len(text))];return e
    def count(self,text):return len(text)+2

class Owner:
    def __init__(self,root):self.root=root;self.docs={};self.denied=set()
    def verified(self,doc,day):
        if doc in self.denied:raise PermissionError('revoked')
        d=self.docs[doc]
        if d['research_date']!=day:raise ValueError('date')
        return copy.deepcopy(d)

def detail(doc,title='券商证券-目标公司(301216)测试.pdf',date='20261027',available='2026-10-28T12:00:00+08:00',text=None,pdf=None):
    texts=text or ['测试全文 2026年 营业收入 百万元 123 风险提示']
    return dict(document_id=doc,status='READY',research_date=date,
        source=dict(original_filename=title,group_name='verified-group',source_fetched_at=available,pdf_published_at=None,source_run_id='source1'),
        processing=dict(available_at=available,completed_at=available,pit_status='NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT'),
        receipt=dict(verified_pdf_sha256=pdf or digest(doc),sha256=digest('receipt'+doc),path='existing/receipt.json',integrity='SOURCE_PDF_AND_PAGE_HASHES_VERIFIED'),
        pages=[dict(page_number=i,text=t,text_sha256=digest(t)) for i,t in enumerate(texts,1)])

class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();r=Path(self.temp.name).resolve();self.owner=Owner(r/'source')
        self.index=ReportIndex(r/'index',self.owner);self.index.initialize();self.service=ReportEvidenceService(self.index)
        self.add(detail('a'*64))
    def tearDown(self):self.temp.cleanup()
    def add(self,d):self.owner.docs[d['document_id']]=d;self.index.upsert(d,Tokens())

    async def test_filter_before_native_scope_and_entity_role(self):
        self.add(detail('b'*64,title='券商证券-另一个公司(600000)测试.pdf'))
        with self.index.connect(True) as db:
            for row in db.execute('SELECT id,document_id FROM chunks').fetchall():
                db.execute('UPDATE chunks SET uri=? WHERE id=?',('viking://resources/v4-report-evidence-20261102/'+row['document_id']+'/'+row['id']+'.md',row['id']))
        class Spy:
            async def find(self,q,uris,limit):self.uris=uris;return []
        spy=Spy();self.service.native=spy
        r=await self.service.search('测试',security='301216',market='A')
        self.assertTrue(r['hits']);self.assertTrue(all('a'*64 in u for u in spy.uris))
        self.assertEqual((await self.service.search('测试',security='HK.00301',market='HK'))['hits'],[])
        self.assertEqual((await self.service.search('测试',security='601211'))['hits'],[])

    async def test_history_unknown_and_future(self):
        self.assertEqual((await self.service.search('测试',mode='historical_evidence',as_of='2026-10-28T11:00:00+08:00'))['hits'],[])
        self.add(detail('c'*64,available=None))
        r=await self.service.search('测试',mode='historical_evidence',as_of='2026-10-28T13:00:00+08:00')
        self.assertEqual({h['document_id'] for h in r['hits']},{'a'*64})
        with self.assertRaises(ValueError):await self.service.search('测试',mode='historical_evidence')
        with self.assertRaises(ValueError):await self.service.search('测试',mode='historical_evidence',as_of='2026-10-28')

    async def test_owner_sha_drift_and_permission_revocation(self):
        self.owner.docs['a'*64]['receipt']['sha256']=digest('changed')
        r=await self.service.search('测试');self.assertEqual(r['hits'],[])
        self.assertIn('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED',r['gaps'])
        self.owner.docs['a'*64]['receipt']['sha256']=digest('receipt'+'a'*64)
        first=(await self.service.search('测试'))['hits'][0]
        self.owner.denied.add('a'*64)
        with self.assertRaises(ValueError):self.service.read(first['chunk_id'])
        self.assertEqual((await self.service.search('测试'))['hits'],[])

    async def test_no_writes_in_query_and_exact_short_chinese(self):
        before=self.index.path.read_bytes();r=await self.service.search('风险',strategy='keyword')
        self.assertTrue(r['hits']);self.assertEqual(before,self.index.path.read_bytes())
        with self.assertRaises(ValueError):self.service.read('../../outside.pdf')
        self.assertEqual((await self.service.search('" OR * ; DROP TABLE documents',strategy='keyword'))['hits'],[])

    async def test_vector_failure_is_explicit_keyword_only(self):
        class Broken:
            async def find(self,*args):raise RuntimeError('offline')
        with self.index.connect(True) as db:db.execute("UPDATE chunks SET uri='viking://resources/v4-report-evidence-20261102/x/body.md'")
        self.service.native=Broken();r=await self.service.search('测试')
        self.assertEqual(r['search_mode'],'keyword_only');self.assertIn('VECTOR_FIND_FAILED_KEYWORD_ONLY',r['gaps'])
        self.assertTrue(r['hits'])

    async def test_same_pdf_dedup_limit_and_retraction(self):
        pdf=digest('shared');self.add(detail('d'*64,pdf=pdf,text=['测试'+str(i) for i in range(8)]))
        self.add(detail('e'*64,pdf=pdf,text=['测试'+str(i) for i in range(8)]))
        r=await self.service.search('测试',strategy='keyword',limit=20)
        self.assertLessEqual(sum(h['pdf_sha256']==pdf for h in r['hits']),3)
        self.index.record_gap('a'*64,'RETRACTED')
        self.assertNotIn('a'*64,{h['document_id'] for h in (await self.service.search('测试'))['hits']})

    def test_checkpoint_reuse_and_root_boundary(self):
        before=self.index.coverage();self.assertEqual(self.index.upsert(self.owner.docs['a'*64],Tokens()),'REUSED');self.assertEqual(before,self.index.coverage())
        with self.assertRaises(ValueError):ReportIndex(self.owner.root/'nested',self.owner)
        with self.assertRaises(ValueError):ReportIndex(self.owner.root.parent,self.owner)
        self.assertEqual(on_stage_completed(config={},trade_date='',stage_id='',receipt={})['status'],'DISABLED')
        with self.assertRaises(ValueError):sidecar_key('20261027','../../x','run-a','A_SHARE')

    def test_structure_limits_original_spans_and_table_headers(self):
        text='财务摘要（百万元）\n|项目|2026E|2027E|\n|---|---|---|\n'+''.join('|收入'+str(i)+'|123|234|\n' for i in range(100))
        chunks=list(structure_chunks(text,Tokens()));self.assertGreater(len(chunks),1)
        for c in chunks:
            self.assertEqual(c['source_text'],text[c['start']:c['end']]);self.assertLessEqual(c['tokens'],1024)
            self.assertIn('百万元',c['text']);self.assertIn('2026E',c['text'])

if __name__=='__main__':unittest.main()
