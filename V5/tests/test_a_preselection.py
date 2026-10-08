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
        with self.assertRaises(ValueError):self.run_lanes([lane])
        lane['paths']['pool']='../outside.csv'
        with self.assertRaises(ValueError):self.run_lanes([lane])
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

if __name__=='__main__':unittest.main()
