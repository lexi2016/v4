import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from v5_shadow.run_ledger import MARKER,claim_run,finish_run

class RunLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        (self.root/'.v5-daily-run-ledger').write_bytes(MARKER)
        self.identity=dict(lane='us_mapping',target_date='20261009',research_cutoff='2026-10-09T00:00:00Z',
            input_sha256='a'*64,code_sha256='b'*64,config_sha256='c'*64,dependency_sha256='d'*64)
        self.success=dict(status='SUCCEEDED',product_reference={'artifact_sha256':'e'*64},readback_verified=True,retry_safe_without_external_effect=False,reason_codes=[])

    def test_concurrent_claim_only_one_owner_starts(self):
        with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(lambda _:claim_run(self.root,self.identity),range(4)))
        self.assertEqual(sum(v['status']=='CLAIMED' for v in values),1)

    def test_success_reused_and_stale_finish_rejected(self):
        claim=claim_run(self.root,self.identity);state=finish_run(self.root,claim,self.success)
        self.assertEqual(claim_run(self.root,self.identity)['status'],'REUSED_SUCCESS')
        self.assertEqual(state['latest_success']['product_reference'],self.success['product_reference'])
        with self.assertRaisesRegex(ValueError,'STALE_CLAIM'):finish_run(self.root,claim,self.success)

    def test_crash_or_unknown_outcome_never_auto_retries(self):
        claim_run(self.root,self.identity)
        self.assertEqual(claim_run(self.root,self.identity)['status'],'IN_PROGRESS_OR_OUTCOME_UNKNOWN')

    def test_no_effect_failure_retries_only_to_hard_bound(self):
        failure=dict(status='FAILED',product_reference=None,readback_verified=False,retry_safe_without_external_effect=True,reason_codes=['NO_REQUEST_SENT'])
        for _ in range(2):finish_run(self.root,claim_run(self.root,self.identity),failure)
        self.assertEqual(claim_run(self.root,self.identity)['status'],'RETRY_EXHAUSTED')
        with self.assertRaisesRegex(ValueError,'RETRY_BOUND'):claim_run(self.root,self.identity,max_attempts=4)

    def test_failure_with_uncertain_effect_is_not_retryable(self):
        failure=dict(self.success,status='FAILED',product_reference=None,readback_verified=False)
        finish_run(self.root,claim_run(self.root,self.identity),failure)
        self.assertEqual(claim_run(self.root,self.identity)['status'],'RETRY_BLOCKED')

    def test_changed_input_or_next_date_has_separate_record_old_success_preserved(self):
        finish_run(self.root,claim_run(self.root,self.identity),self.success)
        for change in ({'input_sha256':'f'*64},{'target_date':'20261012'}):
            self.assertEqual(claim_run(self.root,dict(self.identity,**change))['status'],'CLAIMED')
        self.assertEqual(claim_run(self.root,self.identity)['state']['latest_success']['product_reference'],self.success['product_reference'])

    def test_readback_required_before_success(self):
        claim=claim_run(self.root,self.identity)
        with self.assertRaisesRegex(ValueError,'READBACK_REQUIRED'):finish_run(self.root,claim,dict(self.success,readback_verified=False))
