"""NOT_RUN: archive builder identity repair candidates for independent Mac execution.

Collector acceptance fixtures use the real bound owner and builder. Handwritten
complete sources are used only by isolated original-builder contract tests;
they are never admitted as acquisition-owner output. No test has run here.
"""
import base64
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_archive_article_v2 as chain_tests
import test_manager_archive_reader as legacy_tests
from v5_shadow.archive_reader import read_private
from v5_shadow.digests import canonical_bytes

BASE = Path(__file__).resolve().parents[1]


def isolated_builder(source, original=None, *, source_raw=None):
    """Execute original imports only in a child, preserving parent module cache."""
    script = """
import base64,hashlib,json,sys
sys.path.insert(0,sys.argv[1])
from v5_shadow.archive_builder_v1 import load_owner,verify_archive
from v5_shadow.digests import canonical_bytes
request=json.loads(sys.stdin.buffer.read())
source=request['source']
raw=(base64.b64decode(request['source_raw_base64'],validate=True)
     if 'source_raw_base64' in request else canonical_bytes(source))
if canonical_bytes(json.loads(raw)) != canonical_bytes(source):
    raise ValueError('SYNTHETIC_SOURCE_RAW_JSON_MISMATCH')
sha=hashlib.sha256(raw).hexdigest()
collector,hourly,builder=load_owner()
payload=builder.build_research_archive(source,source_input_sha256=sha)
try:
    verify_archive(request.get('original',payload),source,sha)
except ValueError as exc:
    print(json.dumps({'archive_v1':payload,'source_sha256':sha,'reason':str(exc)}))
else:
    print(json.dumps({'archive_v1':payload,'source_sha256':sha,'verified':True}))
"""
    request = {'source':source}
    if source_raw is not None:
        request['source_raw_base64'] = base64.b64encode(source_raw).decode('ascii')
    if original is not None:
        request['original'] = original
    process = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(BASE/'src')],
        input=canonical_bytes(request), capture_output=True, timeout=120)
    if process.returncode:
        raise AssertionError('ORIGINAL_BUILDER_CHILD_FAILED:' + process.stderr.decode(errors='replace'))
    return json.loads(process.stdout)


class BoundArchiveBuilderIdentityTests(unittest.TestCase):
    """NOT_RUN: fresh original-owner fixture per case, no inherited test expansion."""
    @classmethod
    def setUpClass(cls):
        chain_tests.ArticleV2ChainTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        chain_tests.ArticleV2ChainTests.tearDownClass.__func__(cls)

    def setUp(self):
        self.fixture = chain_tests.ArticleV2ChainTests(
            'test_real_producer_original_store_independent_reader_workspace_and_same_run_plan')
        self.fixture.owner = self.owner
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def receipt_value(self):
        f = self.fixture
        return json.loads((f.capture_root/f.builder_receipt['path']).read_bytes())

    def replace_bound(self, ref, value, *, raw=None):
        """Explicit attack helper; it only rewrites the named ref and outer SHA."""
        f = self.fixture
        raw = canonical_bytes(value) if raw is None else raw
        self.assertEqual(canonical_bytes(json.loads(raw)), canonical_bytes(value))
        (f.capture_root/ref['path']).write_bytes(raw)
        ref.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        f.files[ref['path']] = ref['sha256']

    def replace_builder_receipt(self, value):
        self.replace_bound(self.fixture.builder_receipt, value)

    def test_control_real_collector_full_builder_and_independent_reader_are_accepted(self):
        f = self.fixture
        source_raw = (f.capture_root/f.builder_source['path']).read_bytes()
        source = json.loads(source_raw)
        self.assertEqual(hashlib.sha256(source_raw).hexdigest(), f.builder_source['sha256'])
        self.assertEqual(f.original['source_input_sha256'], f.builder_source['sha256'])
        for key in ('stock_research_timeline', 'stock_research_daily', 'source_manifest',
                    'raw_items', 'research_items', 'research_pool_bridge', 'hourly_research'):
            self.assertIn(key, source)
        receipt = self.receipt_value()
        self.assertEqual(receipt['builder_source'], f.builder_source)
        self.assertEqual(receipt['status'], f.status_ref)
        self.assertEqual(receipt['capture_receipt'], f.ref)
        self.assertEqual(receipt['trade_date'], f.day)
        self.assertEqual([call['module'] for call in receipt['clock_calls']],
                         ['domains.research_hourly', 'domains.research_hourly',
                          'ops.collect_hourly_research_input'])
        self.assertEqual([call['timezone'] for call in receipt['clock_calls']],
                         [None, None, 'Asia/Shanghai'])
        self.assertTrue(all(type(call['utc_offset_seconds']) is int
                            for call in receipt['clock_calls']))
        self.assertFalse(receipt['natural_verified'])
        self.assertFalse(receipt['production_allowed'])
        self.assertFalse(receipt['buy_gate_updated'])
        self.assertFalse(receipt['orders_sent'])
        result = f.publish()
        payload = read_private(f.output, result['archive_binding'])['records'][f.day+'/']['payload']
        self.assertEqual(payload['builder_source'], f.builder_source)
        self.assertEqual(payload['builder_receipt'], f.builder_receipt)
        self.assertEqual(payload['articles'][0]['article_id'], f.original['articles'][0]['article_id'])
        self.assertEqual(payload['articles'][0]['dedupe_key'], f.original['articles'][0]['dedupe_key'])

    def test_article_id_64hex_mutation_must_be_rejected(self):
        f = self.fixture
        article = f.original['articles'][0]
        article['article_id'] = ('0' if article['article_id'][0] != '0' else '1') + article['article_id'][1:]
        self.assertRegex(article['article_id'], r'^[0-9a-f]{64}$')
        f.rejected('BUILDER_V1_ARCHIVE_MISMATCH')

    def test_dedupe_key_64hex_mutation_must_be_rejected(self):
        f = self.fixture
        article = f.original['articles'][0]
        article['dedupe_key'] = ('0' if article['dedupe_key'][0] != '0' else '1') + article['dedupe_key'][1:]
        self.assertRegex(article['dedupe_key'], r'^[0-9a-f]{64}$')
        f.rejected('BUILDER_V1_ARCHIVE_MISMATCH')

    def test_missing_builder_source_has_no_legacy_v2_fallback(self):
        f = self.fixture
        del f.request['builder_source']
        f.rejected('ARTICLE_V2_BUILDER_SOURCE_REQUIRED')

    def test_missing_builder_receipt_has_no_legacy_v2_fallback(self):
        f = self.fixture
        del f.request['builder_receipt']
        f.rejected('ARTICLE_V2_BUILDER_SOURCE_REQUIRED')

    def test_source_byte_mutation_is_rejected_by_outer_capture_sha(self):
        f = self.fixture
        path = f.capture_root/f.builder_source['path']
        path.write_bytes(path.read_bytes() + b' ')
        f.rejected('ARTICLE_V2_CAPTURE_SHA')

    def test_outer_source_sha_update_cannot_hide_bound_ref_sha_mismatch(self):
        f = self.fixture
        path = f.capture_root/f.builder_source['path']
        path.write_bytes(path.read_bytes() + b' ')
        f.files[f.builder_source['path']] = hashlib.sha256(path.read_bytes()).hexdigest()
        f.rejected('ARTICLE_V2_FILE_SHA')

    def test_source_file_missing_is_rejected_without_success_manifest(self):
        f = self.fixture
        (f.capture_root/f.builder_source['path']).unlink()
        f.rejected('FileNotFoundError')

    def test_owner_receipt_file_missing_is_rejected_without_success_manifest(self):
        f = self.fixture
        (f.capture_root/f.builder_receipt['path']).unlink()
        f.rejected('FileNotFoundError')

    def test_original_source_bytes_must_equal_full_source_witness(self):
        f = self.fixture
        receipt = self.receipt_value()
        original_ref = receipt['source_original']
        source = json.loads((f.capture_root/original_ref['path']).read_bytes())
        source['unexpected_source_field'] = 'synthetic mismatching original witness'
        self.replace_bound(original_ref, source)
        receipt['files'][original_ref['path']] = {
            key:original_ref[key] for key in ('sha256', 'bytes')}
        self.replace_builder_receipt(receipt)
        f.rejected('BUILDER_V1_SOURCE_SHA')

    def test_owner_receipt_run_mismatch_is_rejected_before_publication(self):
        value = self.receipt_value()
        value['run_id'] = '00000000_090000_000000000000'
        self.replace_builder_receipt(value)
        self.fixture.rejected('BUILDER_V1_DATE_RUN_BINDING')

    def test_owner_receipt_date_mismatch_is_rejected_before_publication(self):
        f = self.fixture
        value = self.receipt_value()
        value['trade_date'] = (f.base-timedelta(days=1)).strftime('%Y%m%d')
        self.replace_builder_receipt(value)
        f.rejected('BUILDER_V1_DATE_RUN_BINDING')

    def test_owner_identity_mismatch_is_rejected_even_if_receipt_is_rehashed(self):
        value = self.receipt_value()
        value['owner_source_sha256'] = 'f'*64
        self.replace_builder_receipt(value)
        self.fixture.rejected('BUILDER_V1_OWNER_IDENTITY')

    def test_recorded_original_clock_transcript_is_required(self):
        value = self.receipt_value()
        value['clock_calls'] = value['clock_calls'][:-1]
        self.replace_builder_receipt(value)
        self.fixture.rejected('BUILDER_V1_CLOCK_TRANSCRIPT')

    def test_recorded_naive_owner_clock_cannot_be_relabelled_shanghai(self):
        value = self.receipt_value()
        self.assertIsNone(value['clock_calls'][0]['timezone'])
        value['clock_calls'][0]['timezone'] = 'Asia/Shanghai'
        self.replace_builder_receipt(value)
        self.fixture.rejected('BUILDER_V1_CLOCK_TRANSCRIPT')

    def test_source_and_archive_whole_payload_mismatch_in_stock_pool_is_rejected(self):
        # Existing body/time/url/status checks all remain valid. Rebuilding only
        # identities would miss this changed aggregate from the complete source.
        f = self.fixture
        f.original['stock_pool'][0]['research_score'] += 1
        f.rejected('BUILDER_V1_ARCHIVE_MISMATCH')

    def test_mutually_consistent_forged_source_and_archive_fail_original_owner_replay(self):
        f = self.fixture
        receipt = self.receipt_value()
        old_ref = copy.deepcopy(f.builder_source)
        real_raw = (f.capture_root/old_ref['path']).read_bytes()
        real_source = json.loads(real_raw)
        # Confirm both the original source bytes and serialization control
        # before changing semantics. Indent/order/newline differences must not
        # create a misleading replay failure for the forged-claim candidate.
        owner_serialized = json.dumps(real_source, ensure_ascii=False,
                                      indent=2, sort_keys=True).encode('utf-8')
        self.assertEqual(real_raw, owner_serialized)
        control = isolated_builder(real_source, f.original, source_raw=real_raw)
        self.assertTrue(control['verified'])
        self.assertEqual(control['source_sha256'], old_ref['sha256'])
        self.assertEqual(canonical_bytes(control['archive_v1']), canonical_bytes(f.original))
        source = copy.deepcopy(real_source)
        source['stock_research_timeline'][0]['claim_type'] = 'SYNTHETIC_FORGED_CLAIM'
        restored = copy.deepcopy(source)
        if 'claim_type' in real_source['stock_research_timeline'][0]:
            restored['stock_research_timeline'][0]['claim_type'] = real_source['stock_research_timeline'][0]['claim_type']
        else:
            del restored['stock_research_timeline'][0]['claim_type']
        self.assertEqual(json.dumps(restored, ensure_ascii=False,
                                    indent=2, sort_keys=True).encode('utf-8'), real_raw)
        raw = json.dumps(source, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8')
        built = isolated_builder(source, source_raw=raw)
        self.assertTrue(built['verified'])  # pairs are truly builder-consistent
        source_sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual(source_sha, built['source_sha256'])
        new_path = 'research/hourly/source/' + source_sha + '.json'
        (f.capture_root/new_path).write_bytes(raw)
        del f.files[old_ref['path']]
        f.builder_source.update(path=new_path, sha256=source_sha, bytes=len(raw))
        f.files[new_path] = source_sha
        del receipt['files'][old_ref['path']]
        receipt['builder_source'] = copy.deepcopy(f.builder_source)
        receipt['files'][new_path] = dict(sha256=source_sha, bytes=len(raw))
        # Update every source witness, owner_result and enclosing ref. Failure
        # must come from replay, never an unrelated stale byte binding.
        self.replace_bound(receipt['source_original'], source, raw=raw)
        receipt['files'][receipt['source_original']['path']] = {
            key:receipt['source_original'][key] for key in ('sha256', 'bytes')}
        owner_result = json.loads((f.capture_root/receipt['owner_result']['path']).read_bytes())
        owner_result['source_sha256'] = source_sha
        self.replace_bound(receipt['owner_result'], owner_result)
        receipt['files'][receipt['owner_result']['path']] = {
            key:receipt['owner_result'][key] for key in ('sha256', 'bytes')}
        self.replace_builder_receipt(receipt)
        f.original = built['archive_v1']
        f.request['archive_v1'] = f.original
        f.rejected('BUILDER_V1_SOURCE_REPLAY_MISMATCH')

    def test_reader_rejects_equal_boolean_article_count_after_all_outer_shas_are_rehashed(self):
        f = self.fixture
        result = f.publish(); binding = result['archive_binding']
        payload = json.loads((f.output/('research/archives/'+f.day+'.json')).read_bytes())
        before = copy.deepcopy(payload)
        self.assertIs(type(payload['article_count']), int)
        self.assertEqual(payload['article_count'], 1)
        payload['article_count'] = True
        self.assertEqual(payload, before, 'attack exposes Python bool/int equality')
        self.assertNotEqual(canonical_bytes(payload), canonical_bytes(before))
        f.rewrite_published_payload(binding, payload)
        checked = read_private(f.output, binding)
        self.assertIn('ARTICLE_V2_ARTICLE_OR_PAYLOAD_CHANGED',
                      checked['records'][f.day+'/']['error']['message'])

    def test_reader_rejects_equal_numeric_pool_score_type_after_all_outer_shas_are_rehashed(self):
        f = self.fixture
        result = f.publish(); binding = result['archive_binding']
        payload = json.loads((f.output/('research/archives/'+f.day+'.json')).read_bytes())
        before = copy.deepcopy(payload)
        score = payload['stock_pool'][0]['research_score']
        self.assertIn(type(score), (int, float))
        # Original _number normally emits a float; use the opposite equal
        # numeric representation so this still tests actual fixture bytes.
        changed = float(score) if type(score) is int else int(score)
        self.assertEqual(changed, score, 'fixture score must be exactly representable both ways')
        self.assertIsNot(type(changed), type(score))
        payload['stock_pool'][0]['research_score'] = changed
        self.assertEqual(payload, before, 'attack exposes Python int/float equality')
        self.assertNotEqual(canonical_bytes(payload), canonical_bytes(before))
        f.rewrite_published_payload(binding, payload)
        checked = read_private(f.output, binding)
        self.assertIn('ARTICLE_V2_ARTICLE_OR_PAYLOAD_CHANGED',
                      checked['records'][f.day+'/']['error']['message'])

    def test_reader_rejects_v2_generation_backfilled_before_original_owner_completed(self):
        f = self.fixture
        result = f.publish(); binding = result['archive_binding']
        payload = json.loads((f.output/('research/archives/'+f.day+'.json')).read_bytes())
        receipt = self.receipt_value()
        capture = json.loads((f.capture_root/f.ref['path']).read_bytes())
        captured_available = datetime.fromisoformat(capture['source_payloads_available_at'])
        owner_completed = datetime.fromisoformat(receipt['owner_completed_at'])
        source_available = datetime.fromisoformat(receipt['source_available_at'])
        self.assertLess(captured_available, owner_completed)
        backfilled = captured_available + (owner_completed-captured_available)/2
        self.assertLessEqual(captured_available, backfilled)
        self.assertLess(backfilled, owner_completed)
        self.assertLess(backfilled, source_available)
        self.assertLessEqual(source_available, datetime.fromisoformat(payload['source_generated_at']))
        payload['source_generated_at'] = backfilled.isoformat()
        # Source/owner/capture refs stay untouched. Only archive, store receipt,
        # manifest and declared outer SHAs are updated to reach the time gate.
        f.rewrite_published_payload(binding, payload)
        checked = read_private(f.output, binding)
        self.assertIn('ARTICLE_V2_IMPORT_CLOCK',
                      checked['records'][f.day+'/']['error']['message'])

    def test_reader_requires_declared_source_and_receipt_even_when_files_still_exist(self):
        f = self.fixture
        result = f.publish()
        for ref in (f.builder_source, f.builder_receipt):
            with self.subTest(path=ref['path']):
                binding = copy.deepcopy(result['archive_binding'])
                del binding['files'][ref['path']]
                checked = read_private(f.output, binding)
                self.assertIn('ARTICLE_V2_UNDECLARED_FILE',
                              checked['records'][f.day+'/']['error']['message'])

    def test_reader_v1_dispatch_preserves_old_payload_without_builder_source(self):
        helper = legacy_tests.ArchiveWiringTests('test_source_sha_mismatch_fails_before_workspace')
        helper.setUp(); self.addCleanup(helper.doCleanups)
        binding = helper.request['inputs']['archives']
        checked = read_private(Path(binding['root']), binding)
        payload = checked['records']['20261008/']['payload']
        self.assertEqual(payload, helper.payload)
        self.assertEqual(payload['schema_version'], 'v3_5.research_archive.v1')
        self.assertNotIn('builder_source', payload)
        self.assertNotIn('builder_receipt', payload)


class OriginalOwnerBoundIOTests(unittest.TestCase):
    """NOT_RUN: actual original owner and SafeRoot, synthetic local bytes only."""
    def isolated_io(self, mode):
        script = """
import hashlib,json,os,sys,tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,sys.argv[1])
from v5_shadow.archive_builder_v1 import load_owner,_invoke_owner
load_owner()
from infrastructure.owned_io import SafeRoot
mode=sys.argv[2]
with tempfile.TemporaryDirectory() as temporary:
    scratch=Path(temporary).resolve()
    root=scratch/'bound'; root.mkdir()
    sentinel=scratch/'outside_bound_sentinel.bin'
    sentinel.write_bytes(b'SYNTHETIC-SENTINEL-MUST-REMAIN-UNCHANGED')
    sentinel_before=sentinel.read_bytes()
    day=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    slot='0900'; run=day+'_090000_000000000000'
    destination=root/'research/incoming'/day/(slot+'.json')
    destination.parent.mkdir(parents=True)
    legacy_tmp=destination.with_name('.'+destination.name+'.'+str(os.getpid())+'.tmp')
    poisoned=legacy_tmp if mode=='legacy_tmp' else destination
    poisoned.symlink_to(sentinel)
    link_before=os.readlink(poisoned)
    status_ref={'path':'research_module/runtime_outputs/zsxq_hourly/'+day+'/'+slot+
                       '/v35_zsxq_hourly_status_'+day+'_'+slot+'.json'}
    observed=datetime.strptime(day,'%Y%m%d').replace(hour=8,tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()
    published=datetime.strptime(day,'%Y%m%d').replace(hour=7,minute=30,
                        tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()
    status={'status':'READY','latest_run_id':run,'slot':slot,'fetched_at':observed,
            'paths':{'summary':'explicit-bound-summary'},'cannot_confirm':[]}
    body='合成科技签署光模块产品供货合同。'+'仅为独立IO测试合成正文。'*25
    summary={'effective_topics':[{'topic_id':'12345678901234567','group_id':'123',
        'create_time':published,'title':'合成IO标题','content_head':body[:240],'evidence':body,
        'companies':[{'code':'00001','name':'合成科技'}],'themes':[{'theme':'Optical'}]}]}
    io=SafeRoot(root)
    try:
        result,calls=_invoke_owner(root,status_ref,status,summary,day,slot,io=io)
    except (OSError,ValueError) as exc:
        if mode!='destination':
            raise
        print(json.dumps({'rejected':True,'reason':type(exc).__name__+':'+str(exc),
            'sentinel_unchanged':sentinel.read_bytes()==sentinel_before,
            'symlink_unchanged':poisoned.is_symlink() and os.readlink(poisoned)==link_before}))
    else:
        if mode=='destination':
            raise AssertionError('PREEXISTING_DESTINATION_SYMLINK_UNEXPECTEDLY_ACCEPTED')
        raw=io.read_bytes(result['source_path'])
        source=json.loads(raw)
        source_sha=hashlib.sha256(raw).hexdigest()
        replay_result,_=_invoke_owner('/v5-bound-owner',status_ref,status,summary,day,slot,
                                     replay=calls,source_raw=raw)
        print(json.dumps({'rejected':False,
            'sentinel_unchanged':sentinel.read_bytes()==sentinel_before,
            'symlink_unchanged':poisoned.is_symlink() and os.readlink(poisoned)==link_before,
            'source_path':result['source_path'],'expected_path':'research/incoming/'+day+'/'+slot+'.json',
            'source_sha256':source_sha,'owner_source_sha256':result['source_sha256'],
            'source_is_symlink':destination.is_symlink(),
            'owner_serialization_matched':raw==json.dumps(source,ensure_ascii=False,
                                             indent=2,sort_keys=True).encode('utf-8'),
            'source_date_matched':source['trade_date']==day,
            'source_has_one_evidence':len(source['stock_research_timeline'])==1,
            'body_binding_matched':source['stock_research_timeline'][0]['evidence_sentence'] in body,
            'readonly_replay_matched':replay_result==result}))
"""
        process = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(BASE/'src'), mode],
            capture_output=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        return json.loads(process.stdout)

    def test_old_collector_temporary_symlink_is_untouched_by_bound_owner_publication(self):
        result = self.isolated_io('legacy_tmp')
        self.assertFalse(result['rejected'])
        self.assertTrue(result['sentinel_unchanged'])
        self.assertTrue(result['symlink_unchanged'])
        self.assertEqual(result['source_path'], result['expected_path'])
        self.assertEqual(result['source_sha256'], result['owner_source_sha256'])
        self.assertFalse(result['source_is_symlink'])
        self.assertTrue(result['owner_serialization_matched'])
        self.assertTrue(result['source_date_matched'])
        self.assertTrue(result['source_has_one_evidence'])
        self.assertTrue(result['body_binding_matched'])
        self.assertTrue(result['readonly_replay_matched'])

    def test_bound_owner_refuses_preexisting_destination_symlink_without_touching_sentinel(self):
        result = self.isolated_io('destination')
        self.assertTrue(result['rejected'])
        self.assertTrue(result['reason'])
        self.assertTrue(result['sentinel_unchanged'])
        self.assertTrue(result['symlink_unchanged'])


class OriginalBuilderCompleteSourceContractTests(unittest.TestCase):
    """NOT_RUN: original-builder contracts, never collector provenance positives."""
    def setUp(self):
        self.day = '20261010'
        self.event = '2026-10-10T08:15:00+08:00'
        self.row = dict(stock_code='00001', stock_name='合成科技', source_title='合成研究标题',
            source_path='synthetic/complete/source.json', url='https://example.invalid/complete',
            source_type='zsxq', source_name='知识星球', claim_type='SUPPLY_CONTRACT',
            evidence_level='L3_STRONG', confidence='HIGH', evidence_sentence='合成科技签署供货合同。',
            theme='Optical', catalyst='供货合同', event_time=self.event,
            source_published_at=self.event, first_seen_at=self.event, last_checked_at=self.event,
            dedup_key='synthetic-evidence-first')
        self.source = dict(schema_version='v3_research_lane.v2', trade_date=self.day,
            stock_research_timeline=[self.row],
            stock_research_daily=[dict(stock_code='00001', stock_name='合成科技', research_score=35,
                research_status='WATCH', evidence_count=1, source_count=1, strong_evidence_count=1,
                medium_evidence_count=0, weak_evidence_count=0, source_types=['zsxq'],
                themes=['Optical'], top_catalysts=['供货合同'], first_seen_time=self.event,
                last_seen_time=self.event)],
            source_manifest=dict(trade_date=self.day, hourly_slot='0900',
                generated_at=self.event, published_at=self.event, producer='SYNTHETIC_CONTRACT_ONLY',
                complete_input_witness={'optional_nullable':None, 'retained':True}),
            research_pool_bridge=[dict(stock_code='00001', formal_overlap=False, stage_overlap=False)],
            raw_items=[dict(raw_id='synthetic-raw', raw_payload={'retained_field':'full-source'})],
            research_items=[dict(item_id='synthetic-item', quality_flags=[], cannot_confirm=[])],
            hourly_research=dict(trade_date=self.day, latest_slot='0900'),
            cannot_confirm=[{'reason':'SYNTHETIC_CONTRACT_ONLY'}])

    def build(self, original=None):
        before = {name:module for name,module in sys.modules.items()
                  if name == 'domains' or name.startswith(('domains.', 'contracts.', 'infrastructure.'))}
        result = isolated_builder(self.source, original)
        after = {name:module for name,module in sys.modules.items()
                 if name == 'domains' or name.startswith(('domains.', 'contracts.', 'infrastructure.'))}
        self.assertEqual(before, after, 'original owner module cache must remain in child')
        return result

    def assert_identity(self, article, key_parts):
        canonical_key = '\x1f'.join(part.strip().lower() for part in key_parts)
        self.assertEqual(article['dedupe_key'], hashlib.sha256(canonical_key.encode()).hexdigest())
        self.assertEqual(article['article_id'],
            hashlib.sha256((self.day+'\x1e'+canonical_key).encode()).hexdigest())

    def test_claim_type_not_evidence_level_uses_original_identity_and_complete_source(self):
        result = self.build()
        self.assertTrue(result['verified'])
        archive = result['archive_v1']; article = archive['articles'][0]
        self.assert_identity(article, ['00001', '合成研究标题', 'https://example.invalid/complete',
                                      'synthetic/complete/source.json', '知识星球', 'SUPPLY_CONTRACT'])
        self.assertNotIn('claim_type', article)
        self.assertEqual(article['evidence_level'], 'L3_STRONG')
        changed = copy.deepcopy(self.source)
        changed['stock_research_timeline'][0]['claim_type'] = 'L3_STRONG'
        different = isolated_builder(changed)['archive_v1']['articles'][0]
        self.assertNotEqual(article['article_id'], different['article_id'])
        self.assertNotEqual(article['dedupe_key'], different['dedupe_key'])
        self.assertEqual(archive['source_input_sha256'], result['source_sha256'])
        self.assertIsNone(self.source['source_manifest']['complete_input_witness']['optional_nullable'])

    def test_fallback_fields_and_strip_lower_are_rebuilt_by_original_builder(self):
        self.row.update(stock_code='', code=' 00001 ', source_title='', title=' FALLBACK TITLE ',
            url='', source_url=' HTTPS://EXAMPLE.INVALID/FALLBACK ', source_path=' synthetic/FALLBACK.json ',
            source_name='', source_type=' ZSXQ ', claim_type='', evidence_level=' L2_MEDIUM ')
        result = self.build(); self.assertTrue(result['verified'])
        article = result['archive_v1']['articles'][0]
        self.assert_identity(article, ['00001', 'fallback title', 'https://example.invalid/fallback',
                                      'synthetic/fallback.json', 'zsxq', 'l2_medium'])
        self.assertEqual(article['stock_code'], '00001')
        self.assertEqual(article['source_title'], 'FALLBACK TITLE')
        self.assertEqual(article['url'], 'HTTPS://EXAMPLE.INVALID/FALLBACK')
        self.assertEqual(article['source_name'], 'ZSXQ')

    def test_duplicate_inputs_remain_in_full_source_and_original_merge_is_preserved(self):
        duplicate = copy.deepcopy(self.row)
        duplicate.update(evidence_sentence='合成科技签署更完整的供货合同证据说明。',
                         event_time='2026-10-10T08:20:00+08:00', dedup_key='synthetic-evidence-second')
        self.source['stock_research_timeline'].append(duplicate)
        result = self.build(); self.assertTrue(result['verified'])
        archive = result['archive_v1']; article = archive['articles'][0]
        self.assertEqual(len(self.source['stock_research_timeline']), 2)
        self.assertEqual(archive['article_count'], 1)
        self.assertEqual(article['duplicate_evidence_count'], 2)
        self.assertEqual(article['source_dedup_keys'],
                         ['synthetic-evidence-first', 'synthetic-evidence-second'])
        self.assertEqual(article['evidence_sentence'], duplicate['evidence_sentence'])
        self.assert_identity(article, ['00001', '合成研究标题', 'https://example.invalid/complete',
                                      'synthetic/complete/source.json', '知识星球', 'SUPPLY_CONTRACT'])

    def test_full_dictionary_comparison_rejects_nonidentity_aggregate_mutation(self):
        result = self.build(); self.assertTrue(result['verified'])
        archive = copy.deepcopy(result['archive_v1'])
        archive['stock_pool'][0]['research_score'] += 1
        failed = self.build(archive)
        self.assertEqual(failed['reason'], 'BUILDER_V1_ARCHIVE_MISMATCH')
        self.assertNotIn('verified', failed)
