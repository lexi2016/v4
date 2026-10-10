"""NOT_RUN: Mac-only closed-chain candidates; no real provider or production root.

Every positive v2 archive comes from the original collector and full builder.
Only the bounded external acquisition response and analyzer are synthetic.
"""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import test_archive_acquisition_producer as producer_tests
from v5_shadow.archive_builder_v1 import run_build
from v5_shadow.archive_article_v2 import SCHEMA
from v5_shadow.archive_reader import read_private
from v5_shadow.digests import canonical_bytes
from v5_shadow.manager_plan import run_manager_plan

BASE = Path(__file__).resolve().parents[1]


class ArticleV2ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        producer_tests.ArchiveAcquisitionProducerTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        producer_tests.ArchiveAcquisitionProducerTests.tearDownClass.__func__(cls)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.capture_root = self.root/'capture'; self.capture_root.mkdir()
        (self.capture_root/'.v5-archive-acquisition').write_bytes(b'v5.archive-acquisition.v2\n')
        self.output = self.root/'archive'; self.output.mkdir()
        (self.output/'.v5-archive-article-v2').write_bytes(b'v5.archive-article.v2\n')
        # Current-day synthetic acquisition; deliberately old publication stays old.
        self.base = datetime.now(ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0)
        self.day = self.base.strftime('%Y%m%d')
        self.published = (self.base - timedelta(hours=1)).replace(microsecond=123456).isoformat()
        self.times = [(self.base + timedelta(microseconds=i+1)).isoformat() for i in range(4)]
        self.topic_id = '12345678901234567'
        self.body = self.synthetic_body(direct=True)
        self.build_capture(self.capture_root, self.body)

    @staticmethod
    def synthetic_body(direct):
        clause = ('合成科技与 NASDAQ:AVGO 签署光模块供货协议并交付光互连设备。'
                  if direct else '合成科技签署光模块产品供货合同并交付光互连设备。')
        # The real collector appends title to content_head, the normalizer keeps
        # 280 characters, and evidence_sentence selects the issuer's first
        # sentence. A long body keeps every excerpt within the acquired prose.
        return clause + '此处仅为独立测试合成正文，没有真实业务含义。' * 20

    def build_capture(self, capture_root, body):
        """Produce a fresh immutable positive run; never called by invoke()."""
        self.capture_root = capture_root
        self.body = body
        self.raw_topic = dict(topic_id=self.topic_id, create_time=self.published, content=body)
        self.summary_topic = dict(topic_id=self.topic_id, create_time=self.published, title='合成研究标题',
            content_head=body[:240], evidence=body, companies=[dict(code='00001', name='合成科技')],
            themes=[dict(theme='Optical')])
        completed = subprocess.CompletedProcess([], 0,
            json.dumps({'topics':[self.raw_topic], 'has_more':False}), '')
        # REAL pagination/materialize; only the external process and analyzer
        # are substitutes. The original collector/builder runs in its own CLI.
        with patch.object(self.owner, '_acquisition_clock', side_effect=self.times):
            status = self.owner.materialize_zsxq_hourly_delta(data_root=capture_root,
                trade_date=self.day, slot='0900', now=self.base, groups=[('123', 'synthetic')],
                process_runner=lambda *a, **k: completed,
                analyzer=lambda *a: {'effective_topic_count':1, 'effective_topics':[self.summary_topic]})
        receipt = {k:status['acquisition_evidence_v2'][k] for k in ('path','sha256','bytes')}
        files = {str(p.relative_to(capture_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (capture_root/'external_sources').rglob('*') if p.is_file()}
        status_raw = (capture_root/status['status_path']).read_bytes()
        self.status_ref = dict(path=status['status_path'],
            sha256=hashlib.sha256(status_raw).hexdigest(), bytes=len(status_raw))
        files[self.status_ref['path']] = self.status_ref['sha256']
        built = run_build(dict(capture_root=str(capture_root), capture_files=files,
            receipt=receipt, status=self.status_ref))
        self.assertFalse(built['natural_verified'])
        self.assertEqual(built['capture_root'], str(capture_root))
        self.assertEqual(built['receipt'], receipt)
        self.files = built['capture_files']
        self.ref = built['receipt']
        self.builder_source = built['builder_source']
        self.builder_receipt = built['builder_receipt']
        self.original = built['archive_v1']
        self.assertEqual(len(self.original['articles']), 1)
        self.assertIn(self.original['articles'][0]['evidence_sentence'], body)
        self.request = {key:built[key] for key in (
            'capture_root', 'capture_files', 'receipt', 'builder_source', 'builder_receipt')}
        self.request.update(archive_v1=self.original, output_root=str(self.output))

    def invoke(self, request=None):
        process = subprocess.run([sys.executable, '-I', '-B', str(BASE/'src/v5_shadow/archive_article_v2.py')],
            input=canonical_bytes(request or self.request), capture_output=True, timeout=120)
        return process, json.loads(process.stdout)

    def publish(self):
        process, value = self.invoke()
        self.assertEqual(process.returncode, 0, (value, process.stderr.decode()))
        self.assertEqual(value['readback'], 'MATCHED')
        self.assertFalse(value['natural_verified'])
        return value

    def rejected(self, reason):
        process, value = self.invoke()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(reason, value['reason'])
        self.assertFalse((self.output/'manifest.json').exists())

    def manager_request(self, binding):
        inputs = {'archives':binding}
        for name in ('manager', 'materials', 'us'):
            root = self.root/name; root.mkdir(exist_ok=True)
            inputs[name] = dict(root=str(root), files={})
        output = self.root/'plans'; output.mkdir(exist_ok=True)
        (output/'.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
        from v5_shadow.current_us_research import _context_at
        now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        for offset in range(15):
            target=(self.base+timedelta(days=offset)).strftime('%Y%m%d')
            try:
                _context_at(target,now)
                break
            except ValueError as exc:
                if 'PLAN_TARGET_NOT_VERIFIED_HK_TRADING_SESSION' not in str(exc):raise
        else:raise AssertionError('NO_NATIVE_HK_TARGET_IN_15_DAYS')
        return dict(target_date=target, now=now,
            action='refresh', view='dynamic', selection_date=None, announcement_date=None,
            inputs=inputs, rebound=None, manager_output_root=str(output))

    def bind_native_identity(self, request):
        from v5_shadow.current_us_research import _context_at
        context=_context_at(request['target_date'],request['now'])
        day=context['hk_reference_date']
        native=self.root/'native';native.mkdir()
        script="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.hk_preselection import _source_bytes,_HKLoader
sys.meta_path.insert(0,_HKLoader(_source_bytes()))
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
publish_hk_security_master(Path(sys.argv[2]),trade_date=sys.argv[3],
 rows=[{'code':'HK.00001','name':'合成科技'}],universe_codes_sha256='a'*64,captured_at=sys.argv[4])
"""
        captured=datetime.strptime(day,'%Y%m%d').replace(tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(BASE/'src'),str(native),day,captured],
            capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        request['inputs']['native_master']=dict(root=str(native),files={
            str(p.relative_to(native)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in native.rglob('*') if p.is_file()})

    def test_real_producer_original_store_independent_reader_workspace_and_same_run_plan(self):
        before = {p:p.read_bytes() for p in self.capture_root.rglob('*') if p.is_file()}
        result = self.publish(); binding = result['archive_binding']
        checked = read_private(self.output, binding)
        payload = checked['records'][self.day+'/']['payload']
        for ref in (self.builder_source, self.builder_receipt):
            self.assertIn(ref['path'], binding['files'])
            self.assertEqual(binding['files'][ref['path']], ref['sha256'])
            self.assertEqual((self.output/ref['path']).read_bytes(), before[self.capture_root/ref['path']])
        self.assertEqual(payload['schema_version'], SCHEMA)
        article = payload['articles'][0]
        self.assertEqual(article['retrieved_at'], self.times[1])  # page end, not batch start
        self.assertEqual(article['available_at'], self.times[3])
        self.assertEqual(article['body_text'], self.body)
        self.assertEqual(article['published_at'], self.published)
        request = self.manager_request(binding)
        self.bind_native_identity(request)
        saved = run_manager_plan(request)
        self.assertEqual(saved['readback']['status'], 'MATCHED')
        self.assertEqual(saved['archive_readback']['validated_artifacts'], 1)
        materials = saved['payload']['materials']
        material = next(m for m in materials if m.get('original_article_id') == article['article_id'])
        self.assertEqual(material['source_row']['body_text'], self.body)
        self.assertEqual(material['retrieved_at'], self.times[1])
        self.assertNotIn('ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING', json.dumps(saved))
        # Native identity is supplied by the original owner with synthetic rows.
        # The US source remains missing: an accepted material is not a US match.
        diagnostics=saved['payload']['us_market_attention']['mapping_diagnostics']
        self.assertGreater(diagnostics['source_material_card_count'],0)
        self.assertTrue(any(row.get('reason')=='ACCEPTED' for row in diagnostics['material_relation_audit']),diagnostics)
        self.assertEqual(diagnostics['assessment_state'],'NOT_EVALUATED')
        self.assertIsNone(diagnostics['accepted_hk_mapping_count'])
        self.assertFalse(saved['natural_verified'])
        read = run_manager_plan({**request, 'action':'read'})
        self.assertEqual(read['payload']['plan_product']['run_id'], saved['readback']['run_id'])
        self.assertEqual(read['payload']['plan_product']['sha256'], saved['readback']['plan_sha256'])
        self.assertEqual(before, {p:p.read_bytes() for p in self.capture_root.rglob('*') if p.is_file()})

    def test_old_archive_date_is_rejected_without_rewrite(self):
        old = (self.base-timedelta(days=1)).strftime('%Y%m%d')
        self.original['archive_date'] = old
        for row in self.original['articles'] + self.original['stock_pool']: row['archive_date'] = old
        self.rejected('NEW_CAPTURE_DATE_REQUIRED')

    def test_file_mutation_rejected_even_when_payload_would_parse(self):
        path = self.capture_root/next(name for name in self.files if '/pages/' in name)
        path.write_bytes(path.read_bytes()+b' ')
        self.rejected('CAPTURE_SHA')

    def test_old_batch_only_receipt_cannot_admit_article(self):
        path = self.capture_root/self.ref['path']; value=json.loads(path.read_bytes())
        value['schema_version']='v5.zsxq_acquisition_receipt.v2'
        self.replace_receipt(value)
        self.rejected('NEW_PRODUCER_REQUIRED')

    def replace_receipt(self, value):
        raw=canonical_bytes(value); (self.capture_root/self.ref['path']).write_bytes(raw)
        self.ref.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        self.files[self.ref['path']]=self.ref['sha256']

    def test_missing_page_evidence_is_not_batch_time_fallback(self):
        value=json.loads((self.capture_root/self.ref['path']).read_bytes());value['pages']=[]
        self.replace_receipt(value);self.rejected('PAGE_EVIDENCE_MISSING')

    def test_wrong_body_does_not_bind_by_stock_code_or_topic_title(self):
        self.original['articles'][0]['evidence_sentence']='另一篇正文，标题和股票相同也不能接受'
        self.rejected('ISSUER_BODY_BINDING')

    def test_wrong_issuer_does_not_bind_to_other_company_body(self):
        self.original['articles'][0]['stock_name']='另一家公司'
        self.rejected('ISSUER_BODY_BINDING')

    def test_source_url_mismatch_is_not_guessed(self):
        self.original['articles'][0]['url']='https://example.invalid/topic/'+self.topic_id
        self.rejected('TOPIC_URL_REQUIRED')

    def test_publication_time_mismatch_is_not_replaced(self):
        self.original['articles'][0]['published_at']=self.times[0]
        self.rejected('TOPIC_BINDING_NOT_UNIQUE')

    def test_page_clock_before_acquisition_is_rejected(self):
        value=json.loads((self.capture_root/self.ref['path']).read_bytes())
        value['pages'][0]['retrieved_at']=self.published
        self.replace_receipt(value);self.rejected('PAGE_CLOCK')

    def test_existing_archive_root_is_never_rewritten(self):
        self.publish()
        before={p:p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        process,value=self.invoke()
        self.assertNotEqual(process.returncode,0);self.assertIn('OUTPUT_NOT_FRESH',value['reason'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def rewrite_published_payload(self, binding, payload):
        """Explicit reader attack: rehash all three original store outer files."""
        name='research/archives/'+self.day+'.json'; receipt_name='receipts/'+name
        raw=canonical_bytes(payload); (self.output/name).write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest()
        receipt=json.loads((self.output/receipt_name).read_bytes())
        receipt['payload_sha256']=digest
        # Original ResearchArchiveStore._receipt copies these three fields.
        # Recreate them from the attacked payload to keep its receipt exact.
        for field in ('source_input_sha256', 'article_count', 'stock_pool_count'):
            receipt[field]=payload[field]
        (self.output/receipt_name).write_bytes(canonical_bytes(receipt))
        manifest=json.loads((self.output/'manifest.json').read_bytes())
        manifest[name]=digest
        (self.output/'manifest.json').write_bytes(canonical_bytes(manifest))
        for changed in (name, receipt_name, 'manifest.json'):
            binding['files'][changed]=hashlib.sha256((self.output/changed).read_bytes()).hexdigest()
        # The attack must reach rebuilt v2 comparison with valid outer
        # hashes and the receipt shape produced by the original store.
        self.assertEqual(receipt['payload_sha256'], digest)
        self.assertEqual(manifest[name], digest)

    def test_consumer_revalidates_article_fields_even_if_archive_receipt_rehashed(self):
        value=self.publish(); binding=value['archive_binding']
        name='research/archives/'+self.day+'.json'
        payload=json.loads((self.output/name).read_bytes()); payload['articles'][0]['body_text']='替换正文'
        self.rewrite_published_payload(binding, payload)
        result=read_private(self.output,binding)
        self.assertIn('ARTICLE_OR_PAYLOAD_CHANGED',result['records'][self.day+'/']['error']['message'])

    def test_cutoff_before_durable_availability_excludes_new_article(self):
        value=self.publish();request=self.manager_request(value['archive_binding'])
        request.update(action='read',now=self.times[2])
        result=run_manager_plan(request)
        self.assertFalse(any(m.get('original_article_id')==self.original['articles'][0]['article_id']
                             for m in result['payload']['materials']))
        self.assertIn('MATERIAL_RECORDS_AFTER_ACTUAL_CUTOFF_EXCLUDED',json.dumps(result))

    def test_updated_outer_sha_cannot_hide_page_receipt_mismatch(self):
        name=next(name for name in self.files if '/pages/' in name)
        path=self.capture_root/name
        raw=path.read_bytes()+b' '
        path.write_bytes(raw);self.files[name]=hashlib.sha256(raw).hexdigest()
        self.rejected('FILE_SHA')

    def test_duplicate_topic_identity_cannot_select_a_convenient_body(self):
        name=next(name for name in self.files if '/pages/' in name)
        payload=json.loads((self.capture_root/name).read_bytes())
        payload['topics'].append(copy.deepcopy(payload['topics'][0]))
        raw=canonical_bytes(payload);(self.capture_root/name).write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest();self.files[name]=sha
        receipt=json.loads((self.capture_root/self.ref['path']).read_bytes())
        receipt['pages'][0].update(sha256=sha,bytes=len(raw))
        self.replace_receipt(receipt);self.rejected('TOPIC_BINDING_NOT_UNIQUE')

    def test_reader_rejects_page_not_declared_in_manager_binding(self):
        result=self.publish();binding=result['archive_binding']
        name=next(name for name in binding['files'] if '/pages/' in name)
        del binding['files'][name]
        read=read_private(self.output,binding)
        self.assertIn('UNDECLARED_FILE',read['records'][self.day+'/']['error']['message'])

    def test_fractional_source_time_survives_original_collector_truncation(self):
        result=self.publish()
        payload=read_private(self.output,result['archive_binding'])['records'][self.day+'/']['payload']
        self.assertNotEqual(self.original['articles'][0]['published_at'],self.published)
        self.assertEqual(payload['articles'][0]['published_at'],self.published)

    def test_source_path_hash_must_identify_this_original_status(self):
        self.original['articles'][0]['source_path_sha256']='f'*64
        self.rejected('SOURCE_PATH_BINDING')

    def _rewrite_capture_payload(self, name, value):
        raw=canonical_bytes(value);(self.capture_root/name).write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest();self.files[name]=digest
        receipt=json.loads((self.capture_root/self.ref['path']).read_bytes())
        if name in receipt['files']:
            receipt['files'][name]=dict(sha256=digest,bytes=len(raw))
        else:
            page=next(p for p in receipt['pages'] if p['path']==name)
            page.update(sha256=digest,bytes=len(raw))
        self.replace_receipt(receipt)

    def test_explicit_nested_response_group_cannot_be_overwritten(self):
        name=next(name for name in self.files if '/pages/' in name)
        value=json.loads((self.capture_root/name).read_bytes())
        value['topics'][0]['group']={'group_id':'999'}
        self._rewrite_capture_payload(name,value)
        # recent retains the request group 123, exactly as original producer does.
        self.rejected('RESPONSE_GROUP_MISMATCH')

    def test_explicit_top_level_response_group_must_match_request(self):
        for name in [n for n in self.files if '/pages/' in n or n.endswith('/zsxq_recent_topics.json')]:
            value=json.loads((self.capture_root/name).read_bytes())
            (value.get('topics') or value.get('topics_brief'))[0]['group_id']='999'
            self._rewrite_capture_payload(name,value)
        self.rejected('RESPONSE_GROUP_MISMATCH')

    def bind_synthetic_us_owner(self, request, session=None):
        from v5_shadow.current_us_research import _context_at
        context=_context_at(request['target_date'],request['now'])
        root=Path(request['inputs']['us']['root'])
        session = session or context['us_session_date']
        captured=datetime.strptime(session,'%Y%m%d').replace(
            hour=16,minute=17,tzinfo=ZoneInfo('America/New_York'))
        self.assertLessEqual(captured,datetime.fromisoformat(request['now']),
            'Synthetic POST_CLOSE fixture requires this session window to have elapsed')
        script="""
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,sys.argv[1])
from v5_shadow.manager_plan import load_owner
load_owner()
from ops.us_market_digest import build_us_market_snapshot,GLOBAL_INDUSTRY_PROXY_MAP
from infrastructure.research_peripheral_store import ResearchPeripheralStore
session=sys.argv[3];captured=sys.argv[4]
capture_time=datetime.fromisoformat(captured)
capture=dict(us_session_date=session,capture_phase='POST_CLOSE',session_timezone='America/New_York',
 capture_window_start=capture_time.replace(minute=15).isoformat(),
 capture_window_end=capture_time.replace(minute=20).isoformat(),
 capture_id='SYNTHETIC-POST-CLOSE',run_id='SYNTHETIC-US-OWNER',captured_at=captured,
 capture_origin='ORIGINAL_TIME_CAPTURE',original_time_capture=True,raw_item_count=0,item_count=0)
quotes={s:dict(last=101.0,previous_close=100.0,change_pct=1.0,session_date=session,session_time='16:00:00')
        for row in GLOBAL_INDUSTRY_PROXY_MAP for s in row['proxy_symbols']}
snapshot=build_us_market_snapshot(session,capture_phase='POST_CLOSE',captured_at=captured,
                                 fetch_quotes=lambda *a,**k:quotes)
payload=dict(schema_version='v3_5.research_peripheral.v1',trade_date=session,source='external_finance',
 status='READY_EMPTY',source_url='https://example.invalid/synthetic',fetched_at=captured,raw_item_count=0,item_count=0,
 overview=[],details=[],items=[],cannot_confirm=[],write_policy='read_only',recommendation_status='RESEARCH_ONLY',
 production_allowed=False,buy_gate_updated=False,orders_sent=False,
 market_snapshot=snapshot,market_snapshot_status=snapshot['status'],us_session_captures=[capture])
ResearchPeripheralStore(Path(sys.argv[2])).publish(payload)
"""
        process=subprocess.run([sys.executable,'-I','-B','-c',script,str(BASE/'src'),str(root),
            session,captured.isoformat()],capture_output=True,text=True,timeout=60)
        self.assertEqual(process.returncode,0,process.stderr)
        names=['research/peripherals/manifest.json','research/peripherals/'+session+'/external_finance.json',
               'receipts/research/peripherals/'+session+'/external_finance.json']
        request['inputs']['us']['files']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}

    def _assert_original_mapping_roundtrip(self, direct):
        imported=self.publish();request=self.manager_request(imported['archive_binding'])
        self.bind_native_identity(request);self.bind_synthetic_us_owner(request)
        saved=run_manager_plan(request)
        diag=saved['payload']['us_market_attention']['mapping_diagnostics']
        self.assertTrue(any(row['accepted_mapping_count']>0 for row in diag['industry']),diag)
        self.assertEqual(any(row['accepted_mapping_count']>0 for row in diag['individual']),direct,diag)
        if direct:
            self.assertTrue(any(row['symbol']=='AVGO' and row['accepted_mapping_count']>0 for row in diag['individual']),diag)
        self.assertEqual(diag['assessment_state'],'ASSESSED_WITH_RELATIONS')
        read=run_manager_plan({**request,'action':'read'})
        self.assertEqual(saved['readback']['run_id'],read['payload']['plan_product']['run_id'])
        self.assertEqual(saved['readback']['plan_sha256'],read['payload']['plan_product']['sha256'])
        self.assertEqual(diag,read['payload']['us_market_attention']['mapping_diagnostics'])
        self.assertFalse(saved['natural_verified'])
        return diag

    def test_industry_material_mapping_needs_no_explicit_us_or_etf_ticker(self):
        before = {p:p.read_bytes() for p in self.capture_root.rglob('*') if p.is_file()}
        fresh = self.root/'industry_capture'; fresh.mkdir()
        (fresh/'.v5-archive-acquisition').write_bytes(b'v5.archive-acquisition.v2\n')
        self.build_capture(fresh, self.synthetic_body(direct=False))
        self.assertNotIn('AVGO', self.body)
        self._assert_original_mapping_roundtrip(direct=False)
        self.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))

    def test_old_us_session_remains_input_missing_with_valid_new_archive(self):
        imported = self.publish(); request = self.manager_request(imported['archive_binding'])
        self.bind_native_identity(request)
        from v5_shadow.current_us_research import _context_at
        expected = _context_at(request['target_date'], request['now'])['us_session_date']
        # This is a real original owner artifact for a distinct old session;
        # publishing a valid archive cannot make that artifact current.
        old = (datetime.strptime(expected, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
        self.bind_synthetic_us_owner(request, session=old)
        saved = run_manager_plan(request)
        self.assertEqual(saved['payload']['us_market_attention']['status'], 'INPUT_MISSING')
        self.assertEqual(saved['archive_readback']['validated_artifacts'], 1)
        read = run_manager_plan({**request, 'action':'read'})
        self.assertEqual(read['payload']['us_market_attention']['status'], 'INPUT_MISSING')
        self.assertEqual(saved['readback']['run_id'], read['payload']['plan_product']['run_id'])
        self.assertEqual(saved['readback']['plan_sha256'], read['payload']['plan_product']['sha256'])
        self.assertFalse(saved['natural_verified'])

    def test_explicit_us_relation_reaches_original_direct_mapping_and_same_run(self):
        self._assert_original_mapping_roundtrip(direct=True)

    def test_symbol_in_following_clause_is_not_attributed_to_hk_issuer(self):
        before = {p:p.read_bytes() for p in self.capture_root.rglob('*') if p.is_file()}
        fresh = self.root/'cross_clause_capture'; fresh.mkdir()
        (fresh/'.v5-archive-acquisition').write_bytes(b'v5.archive-acquisition.v2\n')
        body = ('合成科技签署光模块产品供货合同，向 NASDAQ:AVGO 供应光互连设备。' +
                '此处仅为独立测试合成正文，没有真实业务含义。' * 20)
        self.build_capture(fresh, body)
        self.assertIn('NASDAQ:AVGO', self.body)
        diag = self._assert_original_mapping_roundtrip(direct=False)
        avgo = next(row for row in diag['individual'] if row['symbol'] == 'AVGO')
        self.assertEqual(avgo['accepted_mapping_count'], 0, diag)
        self.assertEqual(avgo['reason'], 'NO_STRUCTURED_HK_US_RELATION', diag)
        self.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))
