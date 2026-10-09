from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import errno
import os
import unittest
from daily_ledger_fixture import make_ledger_fixture
from v5_shadow.run_ledger import claim_run,finish_run

class RunLedgerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=make_ledger_fixture(self.addCleanup)
        self.root=self.fixture.root;self.identity=self.fixture.identity;self.success=self.fixture.success

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

    def test_first_lock_creation_avoids_darwin_create_or_open_race(self):
        original_open=os.open
        modes=[]
        def open_with_darwin_race(path, flags, *args, **kwargs):
            if path=='.lock':
                modes.append(flags)
                if flags & os.O_CREAT and not flags & os.O_EXCL:
                    raise FileNotFoundError(errno.ENOENT,'simulated Darwin first-create race',path)
            return original_open(path,flags,*args,**kwargs)
        with patch('v5_shadow.run_ledger.os.open',side_effect=open_with_darwin_race):
            self.assertEqual(claim_run(self.root,self.identity)['status'],'CLAIMED')
            self.assertEqual(claim_run(self.root,self.identity)['status'],'IN_PROGRESS_OR_OUTCOME_UNKNOWN')
        self.assertEqual(len(modes),3)  # create; EEXIST; existing-file open
        self.assertTrue(modes[0]&os.O_EXCL);self.assertTrue(modes[1]&os.O_EXCL)
        self.assertFalse(modes[2]&os.O_CREAT)

    def test_first_creation_four_threads_twenty_fresh_roots(self):
        # Every round races a new lane/day/lock, never a warmed existing lock.
        # All rounds must pass; no retry-until-green or ignored exceptions.
        for round_number in range(20):
            with self.subTest(round=round_number):
                fixture=make_ledger_fixture(self.addCleanup)
                barrier=Barrier(4,timeout=10)
                def claim(_):
                    barrier.wait()
                    return claim_run(fixture.root,fixture.identity)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    values=list(pool.map(claim,range(4)))
                self.assertEqual(sorted(v['status'] for v in values),
                    ['CLAIMED']+['IN_PROGRESS_OR_OUTCOME_UNKNOWN']*3)
                state=claim_run(fixture.root,fixture.identity)['state']
                self.assertEqual(len(state['attempts']),1)
                self.assertTrue(fixture.root.is_dir())

    def test_real_lock_open_enoent_propagates_without_retry(self):
        original_open=os.open
        attempts=[]
        def missing_lock(path, flags, *args, **kwargs):
            if path=='.lock':
                attempts.append(flags)
                raise FileNotFoundError(errno.ENOENT,'missing parent',path)
            return original_open(path,flags,*args,**kwargs)
        with patch('v5_shadow.run_ledger.os.open',side_effect=missing_lock):
            with self.assertRaises(FileNotFoundError):claim_run(self.root,self.identity)
        self.assertEqual(len(attempts),1)
