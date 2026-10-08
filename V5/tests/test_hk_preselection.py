import tempfile
import unittest
from pathlib import Path
from fixtures.hk_pool_factory import create_hk_reader_fixture

class HKPreselectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
    def request(self,**fixture_changes):
        files=create_hk_reader_fixture(self.root,**fixture_changes)
        target=fixture_changes.get('target','20261008')
        return dict(target_date=target,signal_date=fixture_changes.get('signal','20261007'),
                    eligibility_source_date=fixture_changes.get('eligibility','20260930'),
                    research_cutoff=f'{target[:4]}-{target[4:6]}-{target[6:]}T09:20:00+08:00',
                    data_kind='SYNTHETIC',input_root=str(self.root),files=files)
    def run_request(self,request):
        from v5_shadow.hk_preselection import run_hk_preselection
        return run_hk_preselection(request)
    def test_real_reader_projects_all_top100_and_preserves_three_dates(self):
        result=self.run_request(self.request())
        self.assertEqual(result['status'],'ASSEMBLED');self.assertEqual(len(result['artifact']['rows']),100)
        self.assertEqual(result['artifact']['rows'][0]['pool_rank'],1)
        self.assertEqual(result['signal_date'],'20261007');self.assertEqual(result['eligibility_source_date'],'20260930')
        self.assertEqual(result['artifact']['historical_provenance']['eligibility_source_date'],'20260930')
        self.assertFalse(result['model_weights_reverified']);self.assertFalse(result['formal_eligibility_verified'])
    def test_hk_open_connect_closed_is_independently_reported(self):
        result=self.run_request(self.request(target='20261007',signal='20261006'))
        self.assertEqual(result['status'],'ASSEMBLED')
        self.assertEqual(result['market_states']['hk_securities'],'FULL_TRADING_DAY')
        self.assertEqual(result['market_states']['hk_connect'],'NON_TRADING_DAY')
        self.assertFalse(result['formal_eligibility_verified'])
    def test_same_signal_and_eligibility_dates_supported(self):
        result=self.run_request(self.request(eligibility='20261007'))
        self.assertEqual(result['status'],'ASSEMBLED');self.assertEqual(result['eligibility_source_date'],'20261007')
    def test_cannot_confirm_with100_rows_not_upgraded_to_ready(self):
        result=self.run_request(self.request(status='CANNOT_CONFIRM'))
        self.assertEqual(result['status'],'CANNOT_CONFIRM');self.assertIsNone(result['artifact'])
        self.assertIn('HK_SOURCE_NOT_READY',result['reason'])
    def test_99_rows_and_wrong_model_hash_rejected(self):
        for changes in ({'count':99},{'model_sha':'a'*64}):
            result=self.run_request(self.request(**changes))
            self.assertEqual(result['status'],'CANNOT_CONFIRM');self.assertIsNone(result['artifact'])
    def test_pool_member_absent_from_master_rejected(self):
        result=self.run_request(self.request(unknown_member=True))
        self.assertEqual(result['status'],'CANNOT_CONFIRM');self.assertIn('HK_MEMBER_NOT_IN_SOURCE_MASTER',result['reason'])
    def test_a_previous_day_not_used_as_hk_price_day(self):
        request=self.request();request['signal_date']='20260930'
        with self.assertRaises(ValueError):self.run_request(request)
    def test_nondefault_unsupported_arguments_are_not_silently_dropped(self):
        for extra in ({'research_name_supplement':True},{'eligibility_universe_root':'/some/other/root'}):
            request=self.request();request.update(extra)
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_LEGACY_READER_ARGUMENT'):self.run_request(request)
    def test_late_receipt_and_bad_input_hash_rejected(self):
        request=self.request();request['research_cutoff']='2026-10-08T07:00:00+08:00'
        result=self.run_request(request);self.assertEqual(result['status'],'CANNOT_CONFIRM')
        request=self.request();request['files']['latest.json']='a'*64
        result=self.run_request(request);self.assertEqual(result['status'],'CANNOT_CONFIRM')
    def test_no_model_or_panel_files_are_read(self):
        request=self.request();self.assertEqual(len(request['files']),8)
        self.assertFalse(any('joblib' in name or 'parquet' in name for name in request['files']))
        self.assertEqual(self.run_request(request)['status'],'ASSEMBLED')

    def test_target_day_master_before_pool_capture_allowed(self):
        result=self.run_request(self.request(eligibility='20261008',master_capture_time='07:30:00'))
        self.assertEqual(result['status'],'ASSEMBLED')
    def test_pool_capture_after_cutoff_or_finish_rejected(self):
        for value in ('09:30:00','08:10:00'):
            result=self.run_request(self.request(pool_capture_time=value))
            self.assertEqual(result['status'],'CANNOT_CONFIRM')
    def test_invalid_probabilities_fail_closed(self):
        for value in ('nan','inf','1.2'):
            result=self.run_request(self.request(score_override=value))
            self.assertEqual(result['status'],'CANNOT_CONFIRM')
    def test_ready_but_temporal_false_rejected(self):
        self.assertEqual(self.run_request(self.request(temporal=False))['status'],'CANNOT_CONFIRM')
    def test_all100_ranks_and_symbols_preserved(self):
        rows=self.run_request(self.request())['artifact']['rows']
        self.assertEqual([r['pool_rank'] for r in rows],list(range(1,101)))
        self.assertEqual([r['symbol'] for r in rows],[f'HK.{i:05}' for i in range(1,101)])
        self.assertEqual([r['pool_score'] for r in rows],[1-i/1000 for i in range(1,101)])

if __name__=='__main__':unittest.main()
