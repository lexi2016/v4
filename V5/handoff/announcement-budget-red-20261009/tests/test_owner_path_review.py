"""Offline review regression candidates; execute only in the Mac task."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('owner_review_support',Path(__file__).with_name('test_v5_private_owner.py'))
support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)
from ops import run_manager_daily_announcement as daily

class OwnerPathReview(unittest.TestCase):
    setUp=support.V5PrivateOwnerTests.setUp
    tearDown=support.V5PrivateOwnerTests.tearDown
    factory=support.V5PrivateOwnerTests.factory
    owner=support.V5PrivateOwnerTests.owner

    def capture(self,owner):
        return owner.execute(['capture','--target-date','20261009','--publication-date','2026-10-08'])

    def test_internal_derived_directory_link_rejected_before_capture(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        link=self.root/'announcement_agent_runs';link.symlink_to(self.v4,target_is_directory=True)
        with patch.object(daily,'_capture',side_effect=AssertionError('must reject before capture')):
            with self.assertRaisesRegex(ValueError,'SYMLINK_FORBIDDEN'):self.capture(owner)
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.root/'transport_policy.json').exists())

    def test_existing_nested_artifact_link_rejected_without_read_or_write(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        evidence=self.root/'announcement_agent_runs'/('a'*32)/'evidence';evidence.mkdir(parents=True)
        link=evidence/'capture_receipt.json';link.symlink_to(self.v4/'sentinel')
        with patch.object(daily,'_capture',side_effect=AssertionError('must reject before capture')):
            with self.assertRaisesRegex(ValueError,'SYMLINK_FORBIDDEN'):self.capture(owner)
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.root/'transport_policy.json').exists())

    def test_late_directory_link_cannot_redirect_original_capture_mkdir(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        link=self.root/'announcement_agent_runs'
        def capture(args):
            link.symlink_to(self.v4,target_is_directory=True)
            daily._mkdir(link/'derived'/'evidence')
        with patch.object(daily,'_capture',side_effect=capture):
            with self.assertRaises((ValueError,RuntimeError,OSError)):self.capture(owner)
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.v4/'derived').exists())

    def test_late_existing_artifact_link_is_not_followed_by_writer(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        link=self.root/'capture_receipt.json'
        def capture(args):
            link.symlink_to(self.v4/'sentinel')
            daily._write_exclusive(link,{'changed':True})
        with patch.object(daily,'_capture',side_effect=capture):
            with self.assertRaises((ValueError,RuntimeError,OSError)):self.capture(owner)
        self.assertTrue(link.is_symlink())

    def test_finished_target_cannot_change_publication_to_reset_budget(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        owner.begin_capture('20261009','2026-10-08');owner.finish_capture(True)
        with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
            self.owner(capture_enabled=True).begin_capture('20261009','2026-10-07')

    def test_date_round_trip_preserves_history_and_refuses_old_target(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        owner.begin_capture('20261009','2026-10-08');owner.finish_capture(True)
        replacement=self.owner(capture_enabled=True)
        replacement.begin_capture('20261012','2026-10-09');replacement.finish_capture(True)
        with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
            self.owner(capture_enabled=True).begin_capture('20261009','2026-10-07')
        history=replacement._read_policy()['history']
        self.assertEqual([x['target_trade_date'] for x in history],['20261009','20261012'])
        self.assertEqual([x['state'] for x in history],['FINISHED','FINISHED'])

    def test_publication_cannot_move_to_another_target_to_reset_budget(self):
        owner=self.owner(initialize=True,capture_enabled=True)
        owner.begin_capture('20261009','2026-10-08');owner.finish_capture(True)
        with self.assertRaisesRegex(ValueError,'PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW'):
            self.owner(capture_enabled=True).begin_capture('20261012','2026-10-08')

if __name__=='__main__':unittest.main(verbosity=2)
