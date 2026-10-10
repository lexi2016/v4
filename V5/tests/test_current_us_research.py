"""Mac-only candidates: current/future target with original calendar and owners."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
from v5_shadow.current_us_research import _context_at,run_current_research,coverage_paths
from v5_shadow.digests import canonical_bytes,sha256_json


class CurrentUsResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        for name in ('us','materials','usout','plans'):(self.root/name).mkdir()
        (self.root/'usout/.v5-us-mapping-root').write_bytes(b'v5.us-mapping-root.v1\n')
        (self.root/'plans/.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
        self.request=dict(target_date='20261012',us_data_root=str(self.root/'us'),
            us_files={name:'a'*64 for name in ('research/peripherals/manifest.json','research/peripherals/20261009/external_finance.json','receipts/research/peripherals/20261009/external_finance.json')},
            us_output_root=str(self.root/'usout'),manager_output_root=str(self.root/'plans'),
            materials=dict(root=str(self.root/'materials'),files={}),native_master=None)
        self.context=dict(target_date='20261012',observed_at='2026-10-10T01:00:00+00:00',
                          hk_reference_date='20261009',us_session_date='20261009')

    def test_original_weekend_context_uses_new_target_and_both_latest_completed_sessions(self):
        value=_context_at('20261012','2026-10-10T01:00:00+00:00')
        self.assertEqual(value['hk_reference_date'],'20261009');self.assertEqual(value['us_session_date'],'20261009')
        self.assertEqual(value['original_plan_context']['plan_trade_date'],'20261012')
        self.assertFalse(value['natural_verified'])

    def test_historical_target_cannot_be_relabelled_current(self):
        with patch('v5_shadow.current_us_research.subprocess.run') as child:
            with self.assertRaisesRegex(ValueError,'HISTORICAL_TARGET'):_context_at('20261009','2026-10-10T01:00:00+00:00')
        child.assert_not_called()

    def test_old_session_rejected_before_any_owner_runs(self):
        self.request['us_files']={key.replace('20261009','20261008'):value for key,value in self.request['us_files'].items()}
        with patch('v5_shadow.current_us_research.inspect_target',return_value=self.context),patch('v5_shadow.current_us_research.run_us_mapping') as owner:
            with self.assertRaisesRegex(ValueError,'EXACT_US_SESSION'):run_current_research(self.request)
        owner.assert_not_called()

    def test_nonempty_output_never_overwrites_previous_recovery(self):
        old=self.root/'plans/old-result.json';old.write_bytes(b'old')
        with patch('v5_shadow.current_us_research.inspect_target',return_value=self.context),patch('v5_shadow.current_us_research.run_us_mapping') as owner:
            with self.assertRaisesRegex(ValueError,'FRESH_MARKED_OUTPUT'):run_current_research(self.request)
        owner.assert_not_called();self.assertEqual(old.read_bytes(),b'old')

    def _exercise_archive_transport(self, use_import=False):
        def mapping(request):
            daily=dict(run_id='a'*32,status='VALID_EMPTY',target_trade_date='20261012')
            daily['artifact_sha256']=sha256_json(daily)
            day=Path(request['manager_output_root'])/'us_mapping_research/20261012';(day/'runs').mkdir(parents=True)
            (day/'runs'/('a'*32+'.json')).write_bytes(canonical_bytes(daily))
            (day/'latest.json').write_bytes(canonical_bytes(dict(run_id=daily['run_id'],artifact_sha256=daily['artifact_sha256'])))
            return dict(persisted_daily=daily,readback_status='MATCHED',execution_kind='MANUAL_RECOVERY')
        archives=self.root/'archives';archives.mkdir()
        binding=dict(root=str(archives),files={'manifest.json':sha256_json({})})
        if use_import:
            (archives/'.v5-archive-article-v2').write_bytes(b'v5.archive-article.v2\n')
            self.request['archive_import']=dict(capture_root=str(self.root/'us'),capture_files={},
                receipt={},archive_v1={},output_root=str(archives))
        else:
            (archives/'manifest.json').write_text('{}')
            self.request['archives']=binding
        response=dict(archive_readback={'validated_artifacts':1},readback={'run_id':'plan','plan_sha256':'b'*64},payload={'plan_product':{'run_id':'plan','sha256':'b'*64}})
        with patch('v5_shadow.current_us_research.inspect_target',return_value=self.context),patch('v5_shadow.current_us_research.run_us_mapping',side_effect=mapping),patch('v5_shadow.current_us_research.run_manager_plan',return_value=response) as manager,patch('v5_shadow.archive_article_v2.run_import',return_value={'archive_binding':binding,'readback':'MATCHED'}) as importer:
            result=run_current_research(self.request)
        self.assertEqual(manager.call_count,2)
        self.assertEqual([call.args[0]['action'] for call in manager.call_args_list],['refresh','read'])
        self.assertTrue(all(call.args[0]['view']=='dynamic' for call in manager.call_args_list))
        self.assertNotIn('native_master',result['manager_request']['inputs'])
        self.assertEqual(result['manager_request']['inputs']['archives'],binding)
        self.assertTrue(all(call.args[0]['inputs']['archives']==binding for call in manager.call_args_list))
        self.assertEqual(result['archive_readback'],{'validated_artifacts':1})
        self.assertFalse(result['native_master_bound']);self.assertFalse(result['historical_pit_claimed'])
        self.assertEqual(result['underlying_us_execution_kind'],'MANUAL_RECOVERY')
        if use_import:
            importer.assert_called_once_with(self.request['archive_import'])
            self.assertEqual(result['archive_import']['readback'],'MATCHED')
        else:
            importer.assert_not_called()

    def test_missing_native_master_does_not_block_existing_seed_owner_or_copy_old_binding(self):
        self._exercise_archive_transport()

    def test_new_archive_import_binding_reaches_refresh_and_independent_read(self):
        self._exercise_archive_transport(use_import=True)

    def test_archive_import_cannot_coexist_with_existing_archive_binding(self):
        self.request.update(archives={},archive_import={})
        with self.assertRaisesRegex(ValueError,'ARCHIVE_INPUT_EXCLUSIVE'):
            run_current_research(self.request)

    def test_three_scopes_keep_original_unknown_zero_and_rejections(self):
        import copy
        workspace={'us_market_attention':{'raw_industry_up':[{'label':'未扩展主题'}],
            'raw_individual_up':[{'symbol':'SYN_ETF'}],
            'mapping_diagnostics':{'assessment_state':'INSUFFICIENT',
                'assessment_reasons':['ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID'],
                'industry':[{'reason':'NO_MANAGER_THEME_TAXONOMY','accepted_mapping_count':0}],
                'individual':None}},
            'us_mapping_research':{'daily_run':{'status':'VALID_EMPTY'},'coverage_diagnostics':{'assessed_rising_symbol_count':0,'broader_relation_result':None}}}
        before=copy.deepcopy(workspace);value=coverage_paths(workspace)
        self.assertFalse(value['industry_material']['explicit_us_ticker_required'])
        self.assertTrue(value['individual_material']['explicit_us_ticker_required'])
        self.assertIsNone(value['individual_material']['original_diagnostics'])
        self.assertEqual(value['industry_material']['original_diagnostics'][0]['accepted_mapping_count'],0)
        self.assertEqual(value['reviewed_seed']['status'],'VALID_EMPTY')
        self.assertEqual(value['combined_material_assessment_state'],'INSUFFICIENT')
        self.assertEqual(value['material_assessment_reasons'],['ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID'])
        value['industry_material']['original_diagnostics'][0]['reason']='modified copy'
        self.assertEqual(workspace,before)

    def test_missing_diagnostics_do_not_become_assessed_zero(self):
        value=coverage_paths({})
        self.assertIsNone(value['combined_material_assessment_state'])
        self.assertIsNone(value['industry_material']['original_diagnostics'])
        self.assertIsNone(value['reviewed_seed']['coverage_diagnostics'])
        self.assertFalse(value['formal_eligible'])
