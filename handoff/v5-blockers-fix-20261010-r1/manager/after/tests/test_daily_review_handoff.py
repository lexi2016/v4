"""Synthetic transport/structure regressions; never a real independent review."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daily_ledger_fixture import make_ledger_fixture
from v5_shadow.daily_tick import tick
from v5_shadow.daily_owner_adapters import blocked
from v5_shadow.digests import canonical_bytes, sha256_json


NOW = datetime(2026, 10, 9, 0, 10, tzinfo=timezone.utc)


class ReviewFixture:
    def __init__(self, root):
        self.root = root
        self.identities = dict(parent_task_id='synthetic-parent-task',
            reader_identity='synthetic-reader', reviewer_identity='synthetic-independent-reviewer')
        recovery = dict(source_run_id='1' * 32, derived_root=str(root))
        self.write('recovery_receipt.json', recovery)
        self.write('semantic.json', {'fixture': 'SYNTHETIC_NOT_BUSINESS'})
        self.write('decisions.json', {'article_decisions': [{'fixture': 'SYNTHETIC_NOT_BUSINESS'}]})
        self.binding = dict(revision_id='synthetic-r1', parent_product_sha256='a' * 64,
            parent_owner_receipt_file_sha256='b' * 64,
            source_recovery_receipt_sha256=self.hash('recovery_receipt.json'), source_run_id='1' * 32)
        self.reviewer = dict(schema_version='v4.manager_research.announcement_agent_review.v1',
            review_conclusion='PASS', target_trade_date='20261009', evidence_run_id='1' * 32,
            reader_identity=self.identities['reader_identity'], reviewer_identity=self.identities['reviewer_identity'],
            decision_revision=self.binding, decision_status='EXPLICIT_DISPOSITIONS',
            semantic_catalog_sha256=self.hash('semantic.json'),
            decision_payload_sha256=sha256_json([{'fixture': 'SYNTHETIC_NOT_BUSINESS'}]),
            reviewed_at='2026-10-09T00:05:00+00:00')
        self.write('reviewer.json', self.reviewer)
        self.create = dict(parent_root=str(root), recovery_sha256=self.hash('recovery_receipt.json'),
            revision_id='synthetic-r1', parent_product_sha256='a' * 64, parent_receipt_sha256='b' * 64,
            semantic_catalog=str(root/'semantic.json'), semantic_sha256=self.hash('semantic.json'),
            reviewer_output=str(root/'reviewer.json'), reviewer_sha256=self.hash('reviewer.json'),
            decisions=str(root/'decisions.json'), decisions_sha256=self.hash('decisions.json'))
        self.request = dict(target_date='20261009', revision_create=self.create,
            review_identities=self.identities)

    def write(self, name, value):
        (self.root/name).write_bytes(canonical_bytes(value))

    def hash(self, name):
        return hashlib.sha256((self.root/name).read_bytes()).hexdigest()

    def update_reviewer(self):
        self.write('reviewer.json', self.reviewer)
        self.create['reviewer_sha256'] = self.hash('reviewer.json')

    def task(self):
        return dict(schema_version='v5.announcement_review_task.v1', task_id='synthetic-review-task',
            channel_id='existing-host-channel', target_date='20261009', source_run_id='1' * 32,
            reader_identity=self.identities['reader_identity'], reviewer_identity=self.identities['reviewer_identity'],
            review_scope='REVISION_BINDING_ONLY', decision_revision=self.binding,
            input_files={key: dict(path=self.create[key], sha256=self.create[sha_key])
                for key, sha_key in (('semantic_catalog','semantic_sha256'),('decisions','decisions_sha256'))},
            created_at='2026-10-09T00:00:00+00:00', deadline='2026-10-09T00:30:00+00:00',
            heartbeat_timeout_seconds=300)

    def receipt(self, task, status='COMPLETED'):
        return dict(schema_version='v5.announcement_review_return.v1', task_id=task['task_id'],
            request_sha256=sha256_json(task), channel_id=task['channel_id'], source_run_id=task['source_run_id'],
            reader_identity=task['reader_identity'], reviewer_identity=task['reviewer_identity'],
            status=status, submitted_at='2026-10-09T00:00:01+00:00',
            heartbeat_at='2026-10-09T00:09:00+00:00', reason_codes=[],
            output_files={key: dict(path=self.create[key], sha256=self.create[sha_key])
                for key, sha_key in (('semantic_catalog','semantic_sha256'),('decisions','decisions_sha256'),
                    ('reviewer_output','reviewer_sha256'))} if status=='COMPLETED' else {})


class DailyReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.fixture=ReviewFixture(self.root)

    def _tick(self):
        ledger=make_ledger_fixture(self.addCleanup)
        bundles=ledger.root/'bundles';bundles.mkdir()
        (bundles/'.v5-daily-bundles').write_bytes(b'v5.daily-bundles.v1\n')
        (bundles/'20261009.json').write_bytes(canonical_bytes(dict(target_date='20261009',
            jobs=[dict(lane='announcement', owner_request=self.fixture.request)])))
        before={str(p.relative_to(ledger.root)):p.read_bytes() for p in ledger.root.rglob('*') if p.is_file()}
        with patch('v5_shadow.daily_tick.datetime') as clock, patch('v5_shadow.daily_dispatch.datetime') as dispatch_clock, \
                patch('v5_shadow.daily_tick.bind_us_owner', return_value={}), \
                patch('v5_shadow.daily_tick.read_announcement_owner', return_value=blocked(None,['SYNTHETIC'])) as owner:
            clock.now.return_value=dispatch_clock.now.return_value=NOW
            result=tick(dict(enabled=True,bundle_root=str(bundles),ledger_root=str(ledger.root)))
        after={str(p.relative_to(ledger.root)):p.read_bytes() for p in ledger.root.rglob('*') if p.is_file()}
        return result,owner.call_count,before,after

    def test_missing_binding_does_not_consume_attempt_even_when_files_exist(self):
        self.fixture.reviewer.pop('decision_revision');self.fixture.update_reviewer()
        result,calls,before,after=self._tick()
        self.assertEqual(calls,0,'invalid independent-review binding must block before owner claim')
        self.assertEqual(before,after)
        self.assertIn('REVISION_REVIEW_BINDING_INVALID',result['lanes'][0]['reason_codes'])

    def test_same_reader_reviewer_does_not_consume_attempt(self):
        self.fixture.identities['reviewer_identity']=self.fixture.identities['reader_identity']
        result,calls,before,after=self._tick()
        self.assertEqual(calls,0,'same reader/reviewer must block before owner claim')
        self.assertEqual(before,after)
        self.assertIn('DAILY_REVISION_DISTINCT_REVIEWER',result['lanes'][0]['reason_codes'])

    def test_reviewer_semantic_hash_mismatch_does_not_consume_attempt(self):
        self.fixture.reviewer['semantic_catalog_sha256']='0'*64;self.fixture.update_reviewer()
        result,calls,before,after=self._tick()
        self.assertEqual(calls,0,'known semantic source mismatch must block before owner claim')
        self.assertEqual(before,after)
        self.assertIn('REVISION_REVIEW_SEMANTIC_SHA_MISMATCH',result['lanes'][0]['reason_codes'])

    def test_input_removed_by_previous_lane_blocks_before_actual_claim(self):
        ledger=make_ledger_fixture(self.addCleanup)
        bundles=ledger.root/'bundles';bundles.mkdir()
        (bundles/'.v5-daily-bundles').write_bytes(b'v5.daily-bundles.v1\n')
        us_request=dict(target_date='20261009',now='2026-10-09T08:00:00+08:00')
        (bundles/'20261009.json').write_bytes(canonical_bytes(dict(target_date='20261009',jobs=[
            dict(lane='us_mapping',owner_request=us_request),
            dict(lane='announcement',owner_request=self.fixture.request)])))
        def run_us(*_args):
            (self.root/'reviewer.json').unlink()
            return ledger.success
        us_binding=dict(invoke=run_us,**{key:ledger.identity[key]
            for key in ('code_sha256','config_sha256','dependency_sha256')})
        with patch('v5_shadow.daily_tick.datetime') as clock, patch('v5_shadow.daily_dispatch.datetime') as dispatch_clock, \
                patch('v5_shadow.daily_tick.bind_us_owner',return_value=us_binding), \
                patch('v5_shadow.daily_tick.read_announcement_owner',return_value=blocked(None,['SYNTHETIC'])) as owner:
            clock.now.return_value=dispatch_clock.now.return_value=NOW
            result=tick(dict(enabled=True,bundle_root=str(bundles),ledger_root=str(ledger.root)))
        self.assertEqual(owner.call_count,0,'input waiting must be checked after prior lane and before claim')
        self.assertEqual(result['lanes'][0]['status'],'SUCCEEDED')
        self.assertEqual(result['lanes'][1]['status'],'BLOCKED_OWNER_PREFLIGHT')
        self.assertIn('WAITING_REAL_REVISION_INPUT_FILES',result['lanes'][1]['reason_codes'])
        states=[json.loads(p.read_bytes()) for p in ledger.root.rglob('*.json') if p.parent!=bundles]
        self.assertFalse(any(v.get('identity',{}).get('lane')=='announcement' for v in states))

    def preflight(self):
        from v5_shadow.daily_review_handoff import preflight_revision
        return preflight_revision(self.fixture.request,now=NOW)

    def test_valid_explicit_files_remain_supported_without_claiming_external_service(self):
        before={p:p.read_bytes() for p in self.root.iterdir()}
        result=self.preflight()
        self.assertEqual(result['status'],'READY_FOR_ORIGINAL_OWNER')
        self.assertFalse(result['original_owner_verified']);self.assertFalse(result['natural_verified'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.iterdir()})

    def test_each_binding_field_and_decision_digest_are_checked_readonly(self):
        for key in self.fixture.binding:
            with self.subTest(key=key):
                changed=copy.deepcopy(self.fixture.reviewer);changed['decision_revision'][key]='wrong'
                self.fixture.write('reviewer.json',changed);self.fixture.create['reviewer_sha256']=self.fixture.hash('reviewer.json')
                self.assertIn('REVISION_REVIEW_BINDING_INVALID',self.preflight()['reason_codes'])
        self.fixture.reviewer['decision_payload_sha256']='0'*64;self.fixture.update_reviewer()
        self.assertIn('REVISION_EXPLICIT_DECISIONS_REVIEW_REQUIRED',self.preflight()['reason_codes'])

    def test_output_hash_symlink_and_outside_parent_are_rejected(self):
        self.fixture.create['reviewer_sha256']='0'*64
        self.assertIn('REVISION_INPUT_SHA_MISMATCH',self.preflight()['reason_codes'])
        self.fixture.create['reviewer_sha256']=self.fixture.hash('reviewer.json')
        link=self.root/'linked.json';link.symlink_to(self.root/'reviewer.json')
        self.fixture.create['reviewer_output']=str(link)
        self.assertEqual(self.preflight()['status'],'BLOCKED')
        self.fixture.create['reviewer_output']='/outside.json'
        self.assertIn('REVISION_INPUT_OUTSIDE_PARENT_ROOT',self.preflight()['reason_codes'])

    def test_stale_review_output_identity_and_future_review_time_block(self):
        for key,value in (('reviewer_identity','other'),('review_conclusion','FAIL'),
                ('evidence_run_id','2'*32),('target_trade_date','20261008'),
                ('reviewed_at','2026-10-09T00:11:00+00:00')):
            with self.subTest(key=key):
                original=self.fixture.reviewer[key];self.fixture.reviewer[key]=value;self.fixture.update_reviewer()
                self.assertEqual(self.preflight()['status'],'BLOCKED')
                self.fixture.reviewer[key]=original

    def test_missing_channel_is_explicit_and_never_submits(self):
        from v5_shadow.daily_review_handoff import submit_review_task
        result=submit_review_task(self.fixture.task(),now=NOW)
        self.assertEqual(result['status'],'BLOCKED_REVIEW_CHANNEL_NOT_BOUND')
        self.assertFalse(result['retry_submission_automatically'])

    def test_bound_channel_submission_and_poll_reuse_exact_request(self):
        from v5_shadow.daily_review_handoff import submit_review_task,poll_review_task
        fixture=self.fixture;task=fixture.task()
        class ExistingChannel:
            channel_id='existing-host-channel'
            def __init__(self):self.submissions=[];self.polls=[]
            def submit(self,value):self.submissions.append(value);return fixture.receipt(value,'SUBMITTED')
            def poll(self,task_id,request_sha256):
                self.polls.append((task_id,request_sha256));return fixture.receipt(task)
        channel=ExistingChannel()
        submitted=submit_review_task(task,channel=channel,now=NOW)
        complete=poll_review_task(task,channel=channel,now=NOW)
        again=poll_review_task(task,channel=channel,now=NOW)
        self.assertEqual(submitted['status'],'SUBMITTED');self.assertEqual(complete['status'],'COMPLETED')
        self.assertEqual(complete,again);self.assertEqual(len(channel.submissions),1)
        self.assertEqual(channel.polls,[(task['task_id'],sha256_json(task))]*2)
        self.assertEqual(channel.submissions,[task])

    def test_submission_error_is_unknown_and_does_not_retry(self):
        from v5_shadow.daily_review_handoff import submit_review_task
        class ExistingChannel:
            channel_id='existing-host-channel'
            def __init__(self):self.calls=0
            def submit(self,value):self.calls+=1;raise TimeoutError('no receipt')
        channel=ExistingChannel();result=submit_review_task(self.fixture.task(),channel=channel,now=NOW)
        self.assertEqual(result['status'],'OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY')
        self.assertEqual(channel.calls,1);self.assertFalse(result['retry_submission_automatically'])

    def test_default_clock_accepts_receipt_generated_during_submit_and_poll(self):
        from v5_shadow.daily_review_handoff import submit_review_task,poll_review_task
        task=self.fixture.task();fixture=self.fixture
        receipt_time=NOW+timedelta(microseconds=1)
        class ExistingChannel:
            channel_id='existing-host-channel'
            def submit(self,value):
                receipt=fixture.receipt(value,'SUBMITTED')
                receipt['submitted_at']=receipt['heartbeat_at']=receipt_time.isoformat()
                return receipt
            def poll(self,*_args):return self.submit(task)
        for exchange in (submit_review_task,poll_review_task):
            with self.subTest(operation=exchange.__name__), patch('v5_shadow.daily_review_handoff.datetime') as clock:
                clock.now.side_effect=[NOW,NOW+timedelta(microseconds=2)]
                self.assertEqual(exchange(task,channel=ExistingChannel())['status'],'SUBMITTED')

    def test_wrong_request_identity_heartbeat_and_failed_return_do_not_admit(self):
        from v5_shadow.daily_review_handoff import validate_review_return
        task=self.fixture.task();original=self.fixture.receipt(task,'RUNNING')
        for key,value in (('task_id','wrong'),('request_sha256','0'*64),('source_run_id','2'*32),
                ('reader_identity','other'),('reviewer_identity','other'),('channel_id','other'),
                ('heartbeat_at','2026-10-09T00:01:00+00:00'),('heartbeat_at','2026-10-09T00:11:00+00:00')):
            with self.subTest(key=key,value=value):
                receipt=dict(original,**{key:value})
                with self.assertRaises(ValueError):validate_review_return(task,receipt,now=NOW)
        failed=self.fixture.receipt(task,'FAILED');failed['reason_codes']=['WORKER_FAILED']
        self.assertEqual(validate_review_return(task,failed,now=NOW)['status'],'FAILED')

    def test_terminal_return_must_bind_actual_output_bytes_and_original_decisions(self):
        task=self.fixture.task();receipt=self.fixture.receipt(task)
        self.fixture.request['review_handoff']=dict(task=task,receipt=receipt)
        self.assertEqual(self.preflight()['status'],'READY_FOR_ORIGINAL_OWNER')
        receipt['output_files']['decisions']['sha256']='0'*64
        self.assertIn('REVIEW_RETURN_OUTPUT_MISMATCH',self.preflight()['reason_codes'])
        receipt['output_files']['decisions']['sha256']=self.fixture.create['decisions_sha256']
        task['input_files']['decisions']['sha256']='0'*64;receipt['request_sha256']=sha256_json(task)
        self.assertIn('REVIEW_FROZEN_DECISIONS_CHANGED',self.preflight()['reason_codes'])


if __name__=='__main__':unittest.main()
