"""Exercise frozen A pool builders in a source-only child, without V4 writes."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


def make_lane(root,kind='fupan',count=1,corrupt=False):
    root.mkdir()
    pool=root/'pool.csv';manifest=root/'manifest.json'
    with pool.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['ts_code','stock_name','signal_date','rank','pool_score'])
        writer.writeheader()
        for i in range(count):writer.writerow(dict(ts_code=f'{i+1:06}.SZ',stock_name='SYNTHETIC',signal_date='20260930',rank=i+1,pool_score=10+i))
    value=dict(target_date='20261008',signal_date='20260930',row_count=count,cannot_confirm=['SYNTHETIC_FIXTURE_ONLY'])
    if kind=='fupan':value.update(status='FUPAN_WATCHLIST_POOL_READY',fupan_pool_rule='AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW',source_paths=['SYNTHETIC_ONLY'])
    else:value.update(status='STAGE7_TAIL_POOL_READY',source_role='real_d1_stage7_tail_replay',upstream_manifest=dict(trade_date='20260930',stage_id='STAGE_1445_1500',production_allowed=False,buy_gate_updated=False,orders_sent=False))
    if corrupt:value['row_count']=count+1
    manifest.write_text(json.dumps(value))
    return dict(kind=kind,input_root=str(root),paths=dict(pool='pool.csv',manifest='manifest.json'),
                files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (pool,manifest)})


class APreselectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
    def run_lanes(self,lanes,**changes):
        from v5_shadow.a_preselection import run_a_preselection
        request=dict(target_date='20261008',signal_date='20260930',data_kind='SYNTHETIC',lanes=lanes)
        request.update(changes);return run_a_preselection(request)
    def test_original_fupan_keeps_all_rows_over_ui_page_size(self):
        lane=make_lane(self.root/'fupan',count=250)
        result=self.run_lanes([lane]);self.assertEqual(result['status'],'ASSEMBLED')
        self.assertEqual(len(result['lanes'][0]['artifact']['rows']),250)
        self.assertEqual(result['lanes'][0]['artifact']['rows'][-1]['pool_rank'],250)
        self.assertEqual(result['lanes'][0]['artifact']['rows'][-1]['pool_score'],259)
        self.assertEqual(result['row_count'],250);self.assertFalse(result['natural_verified'])
    def test_bad_optional_lane_does_not_remove_valid_lane(self):
        result=self.run_lanes([make_lane(self.root/'good'),make_lane(self.root/'bad','stage7',corrupt=True)])
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['row_count'],1)
        self.assertTrue(result['lanes'][0]['accepted']);self.assertFalse(result['lanes'][1]['accepted'])
    def test_original_stage7_metadata_and_source_rows_retained(self):
        result=self.run_lanes([make_lane(self.root/'stage7','stage7')])
        artifact=result['lanes'][0]['artifact']
        self.assertEqual(artifact['source_role'],'VERIFIED_D1_STAGE7_REPLAY')
        self.assertEqual(artifact['rows'][0]['signal_date'],'20260930')
        self.assertEqual(artifact['rows'][0]['target_date'],'20261008')
    def test_a_calendar_not_hk_previous_day(self):
        lane=make_lane(self.root/'fupan')
        for changes in ({'signal_date':'20261007'},{'target_date':'20261007'}):
            with self.assertRaises(ValueError):self.run_lanes([lane],**changes)
    def test_all_invalid_is_unknown_not_zero_selection(self):
        result=self.run_lanes([make_lane(self.root/'bad',corrupt=True)])
        self.assertEqual(result['status'],'CANNOT_CONFIRM');self.assertIsNone(result['row_count'])
    def test_source_hash_mismatch_quarantines_lane(self):
        lane=make_lane(self.root/'bad');lane['files']['pool.csv']='a'*64
        result=self.run_lanes([lane]);self.assertEqual(result['status'],'CANNOT_CONFIRM')
        self.assertIn('INPUT_BYTES_MISMATCH',result['lanes'][0]['reason'])
    def test_declared_missing_input_remains_missing(self):
        folder=self.root/'missing';folder.mkdir()
        lane=dict(kind='fupan',input_root=str(folder),paths=dict(pool='pool.csv',manifest='manifest.json'),files={'pool.csv':None,'manifest.json':None})
        result=self.run_lanes([lane]);self.assertIsNone(result['row_count'])
        self.assertFalse(result['lanes'][0]['accepted'])
    def test_symlink_and_path_traversal_rejected(self):
        lane=make_lane(self.root/'source');outside=self.root/'outside.csv';outside.write_text('do not read')
        (Path(lane['input_root'])/'pool.csv').unlink();(Path(lane['input_root'])/'pool.csv').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'SYMLINK_REJECTED'):self.run_lanes([lane])
        (Path(lane['input_root'])/'pool.csv').unlink()
        (Path(lane['input_root'])/'pool.csv').write_text('fixture for path rejection')
        lane['files']['pool.csv']=hashlib.sha256((Path(lane['input_root'])/'pool.csv').read_bytes()).hexdigest()
        lane['paths']['pool']='../outside.csv'
        with self.assertRaisesRegex(ValueError,'INPUT_PATH_INVALID'):self.run_lanes([lane])
    def test_baimao_keeps_research_only_role(self):
        root=self.root/'baimao';root.mkdir();path=root/'map.json'
        path.write_text(json.dumps(dict(trade_date='20261008',research_date='20261008',event_id='research:20261008:synthetic',opens_buy_gate=False,write_policy='RESEARCH_ONLY',candidates=[dict(state='RESEARCH_MAP',code='000001',name='SYNTHETIC',score=1)])))
        lane=dict(kind='baimao',input_root=str(root),paths={'data':'map.json'},files={'map.json':hashlib.sha256(path.read_bytes()).hexdigest()})
        result=self.run_lanes([lane]);artifact=result['lanes'][0]['artifact']
        self.assertEqual(artifact['status'],'BAIMAO_RESEARCH_MAP_READY')
        self.assertFalse(artifact['rows'][0]['buy_gate_updated'])
    def test_unknown_lane_and_duplicates_rejected(self):
        lane=make_lane(self.root/'fupan')
        with self.assertRaises(ValueError):self.run_lanes([lane,lane])
        lane['kind']='arbitrary_function'
        with self.assertRaises(ValueError):self.run_lanes([lane])

    def test_worker_boundary_violation_is_never_optional_input_error(self):
        from v5_shadow.a_preselection import WorkerBoundaryViolation,_expected
        self.assertFalse(_expected(WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')))
        self.assertFalse(_expected(RuntimeError('unexpected bug')))
        self.assertFalse(_expected(ValueError('unexpected programming error')))
        self.assertTrue(_expected(FileNotFoundError('missing input')))

    def test_parent_rejects_wrong_worker_date_or_safety(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from v5_shadow import a_preselection as module
        from v5_shadow.digests import canonical_bytes,sha256_json
        lane=make_lane(self.root/'fupan')
        request=dict(target_date='20261008',signal_date='20260930',data_kind='SYNTHETIC',lanes=[lane])
        response=dict(schema_version='v5.a_preselection_assembly.v1',status='ASSEMBLED',
                      target_date='20261008',signal_date='20260930',data_kind='SYNTHETIC',
                      lanes=[dict(kind='fupan')],request_sha256=sha256_json(request),
                      implementation_sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
                      source_capsule_sha256=module.DESCRIPTOR_SHA256,**module.SAFETY)
        for changes,reason in (({'target_date':'20261009'},'A_WORKER_CONTRACT_MISMATCH'),
                               ({'production_allowed':True},'A_WORKER_SAFETY_MISMATCH')):
            fake=SimpleNamespace(returncode=0,stdout=canonical_bytes(dict(response,**changes)),stderr=b'')
            with patch.object(module.subprocess,'run',return_value=fake):
                with self.assertRaisesRegex(ValueError,reason):module.run_a_preselection(request)

    def test_nonfinite_bad_lane_does_not_erase_healthy_lane(self):
        bad=make_lane(self.root/'bad');pool=Path(bad['input_root'])/'pool.csv'
        with pool.open(newline='') as handle:
            reader=csv.DictReader(handle);fields=reader.fieldnames;rows=list(reader)
        rows[0]['pool_score']='nan'
        with pool.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        bad['files']['pool.csv']=hashlib.sha256(pool.read_bytes()).hexdigest()
        result=self.run_lanes([bad,make_lane(self.root/'good','stage7')])
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['row_count'],1)
        self.assertFalse(result['lanes'][0]['accepted']);self.assertTrue(result['lanes'][1]['accepted'])
    def test_read_guard_uses_current_lane_not_union(self):
        import subprocess,sys
        first=make_lane(self.root/'first');second=make_lane(self.root/'second','stage7')
        from v5_shadow import a_preselection as module
        code="import sys,json; sys.path.insert(0,sys.argv[1]); from v5_shadow.a_preselection import _guard,WorkerBoundaryViolation; from pathlib import Path; lanes=json.loads(sys.argv[2]); select=_guard(lanes); select(lanes[0]); Path(lanes[0]['input_root'],'pool.csv').read_bytes();\ntry: Path(lanes[1]['input_root'],'pool.csv').read_bytes()\nexcept WorkerBoundaryViolation: print('EXPECTED_DENIAL')\nelse: raise AssertionError('cross-lane read was allowed')"
        with tempfile.TemporaryDirectory() as cache:
            result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),'-c',code,
                                   str(Path(module.__file__).parents[1]),json.dumps([first,second])],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('EXPECTED_DENIAL',result.stdout)

    def test_wechat_preserves_article_date_and_source_scope(self):
        root=self.root/'wechat';root.mkdir();rows=root/'rows.csv';manifest=root/'manifest.json'
        rows.write_text('ts_code,stock_name,candidate_score,wechat_v3_preselect_rank,signal_date\n000001.SZ,SYNTHETIC,42,1,20261007\n')
        value=dict(status='WECHAT_V3_PRESELECT_READY',effective_trade_date='20261008',
                   target_validation={'status':'TARGET_DATE_CHECK_PASS'},
                   boundary=dict(formal_pool_write=False,buy_gate_write=False),score_scope='wechat_pool_ts_codes_only',
                   counts={'v3_matched_codes':1},signal_date='20261007',article_publish_date='20261007')
        manifest.write_text(json.dumps(value))
        lane=dict(kind='wechat',input_root=str(root),paths=dict(rows='rows.csv',manifest='manifest.json'),
                  files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (rows,manifest)})
        result=self.run_lanes([lane]);artifact=result['lanes'][0]['artifact']
        self.assertEqual(artifact['source_role'],'VERIFIED_WECHAT_RESEARCH')
        self.assertEqual(artifact['rows'][0]['article_publish_date'],'20261007')
        self.assertEqual(artifact['rows'][0]['pool_score'],42)
        value['score_scope']='all_stocks';manifest.write_text(json.dumps(value))
        lane['files']['manifest.json']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        self.assertEqual(self.run_lanes([lane])['status'],'CANNOT_CONFIRM')
    def test_real_v192_reader_missing_pointer_does_not_block_good_lane(self):
        root=self.root/'v192';root.mkdir()
        lane=dict(kind='v192',input_root=str(root),paths={},files={'latest.json':None})
        result=self.run_lanes([lane,make_lane(self.root/'good')])
        self.assertEqual(result['status'],'PARTIAL')
        self.assertFalse(result['lanes'][0]['accepted']);self.assertTrue(result['lanes'][1]['accepted'])
        self.assertIn('StoreError',result['lanes'][0]['reason'])

    def test_total_budget_omits_only_rejected_diagnostics(self):
        from unittest.mock import patch
        from v5_shadow.a_preselection import _bound_result
        good_rows=[dict(symbol='A.000001',evidence='g'*200)]
        value=dict(lanes=[dict(accepted=True,artifact={'rows':good_rows}),
                          dict(accepted=False,reason='INVALID_SOURCE',rejected_artifact={'detail':'b'*400})])
        with patch('v5_shadow.digests.MAX_JSON_BYTES',512):
            result=_bound_result(value)
        self.assertEqual(result['lanes'][0]['artifact']['rows'],good_rows)
        self.assertEqual(result['lanes'][1]['reason'],'INVALID_SOURCE')
        self.assertNotIn('rejected_artifact',result['lanes'][1])

if __name__=='__main__':unittest.main()
