"""Frozen mapper checks: source mismatch rejects, absent stages stay absent."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ops.build_a_share_pool_top200 import canonical_symbol, project_date


class FrozenDetailsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root / 'stage.csv'
        self.stage.write_text('code\nSH.600001\n')
        self.top = self.root / 'top.json'
        self.top.write_text(json.dumps(dict(data_date='20261104', top200=[dict(rank=1, symbol='600001.SH', name='测试甲', change_pct=10.0), dict(rank=2, symbol='000001.SZ', name='测试乙', change_pct=5.0)])))
        self.ref = dict(path=str(self.top), sha256=self.sha(self.top))
        self.entry = dict(date='20261104', a_pool=dict(selected_count=1, hit_count=1, api_input_fingerprint='frozen', pools=[dict(pool_id='a_d1_premarket_pool', materialized=True, selected_count=1, hit_count=1, source_sha256='pool-sha')]), top200=dict(source='STORED_TOP200_ARTIFACT', source_sha256=self.ref['sha256'], top_count=2, min_change_pct=5.0), seven_stage=dict(selected_count=1, hit_count=1, stages={'STAGE_0930_0935': dict(status='READY', row_count=1, unique_codes=1, hit_count=1, artifact_relative='stage.csv', artifact_sha256=self.sha(self.stage)), 'STAGE_0925': dict(status='NOT_MATERIALIZED', hit_count=None)}))
        self.pages = [dict(trade_date='20261104', input_fingerprint='frozen', a_all_pool_rows=[dict(symbol='A.600001')], pools=[dict(pool_id='a_d1_premarket_pool', source_sha256='pool-sha', rows=[dict(symbol='A.600001')])])]

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_maps_frozen_rows_without_using_later_stages(self):
        (self.root / 'later-0925.csv').write_text('code\nSZ.000001\n')
        result = project_date(self.entry, self.ref, self.pages, self.root)
        self.assertEqual(result['detail_evidence']['counts'], dict(rows=2, pool_hits=1, stage_hits=1))
        self.assertEqual(result['stocks'][0]['stage_memberships'], ['STAGE_0930_0935'])
        self.assertEqual(result['stocks'][1]['stage_memberships'], [])
        self.assertEqual(result['seven_stage'], self.entry['seven_stage'])
        self.assertNotIn('stocks', self.entry)

    def test_rejects_drifted_pool_fingerprint_and_source(self):
        for field in ['input_fingerprint', 'source_sha256']:
            pages = copy.deepcopy(self.pages)
            target = pages[0] if field == 'input_fingerprint' else pages[0]['pools'][0]
            target[field] = 'changed'
            with self.assertRaisesRegex(ValueError, 'MISMATCH'):
                project_date(self.entry, self.ref, pages, self.root)

    def test_rejects_drifted_top_and_stage_bytes(self):
        for path in [self.top, self.stage]:
            old = path.read_bytes()
            path.write_bytes(old + b'\n')
            with self.assertRaisesRegex(ValueError, 'SHA_MISMATCH'):
                project_date(self.entry, self.ref, self.pages, self.root)
            path.write_bytes(old)

    def test_normalizes_existing_symbol_forms(self):
        self.assertEqual(canonical_symbol('SH.600001'), '600001.SH')
        self.assertEqual(canonical_symbol('A.000001'), '000001.SZ')
        self.assertEqual(canonical_symbol('920001.BJ'), '920001.BJ')
        self.assertIsNone(canonical_symbol('HK.00700'))

    def test_delivered_rows_reconcile_all_frozen_aggregate_counts(self):
        path = Path(__file__).resolve().parents[1] / 'apps/web/public/top200-hit.json'
        doc = json.loads(path.read_bytes())
        for entry in doc['dates']:
            if entry.get('detail_status') != 'SAME_SNAPSHOT_RECONCILED':
                continue
            rows = entry['stocks']
            self.assertEqual(len(rows), entry['top200']['top_count'])
            self.assertEqual([r['rank'] for r in rows], list(range(1, len(rows) + 1)))
            self.assertEqual(sum(r['pool_hit'] for r in rows), entry['a_pool']['hit_count'])
            self.assertEqual(sum(bool(r['stage_memberships']) for r in rows), entry['seven_stage']['hit_count'])
            for pool in entry['a_pool']['pools']:
                if pool['materialized']:
                    self.assertEqual(sum(pool['pool_id'] in r['pool_memberships'] for r in rows), pool['hit_count'])




class DailyProjectionTest(FrozenDetailsTest):
    def daily_root(self):
        from ops.build_a_share_pool_top200 import read_daily_projection
        self.top.write_text(json.dumps(dict(schema='V4_A_SHARE_TOP200_V1',data_date='20261104',top200_count=2,top200=[dict(rank=1,symbol='600001.SH',name='甲',change_pct=10.),dict(rank=2,symbol='000001.SZ',name='乙',change_pct=5.)],source_generation='generation',input_sha256='input',numeric_manifest={},RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)))
        product=self.root/'product.json';product.write_text(json.dumps(dict(source_generation='generation',source_identity={'input_sha256':'input'})))
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps({'artifact':dict(path=str(product),sha256=self.sha(product))}))
        numeric=dict(path=str(manifest),sha256=self.sha(manifest));top=json.loads(self.top.read_text());top['numeric_manifest']=numeric;self.top.write_text(json.dumps(top));top_ref=dict(path=str(self.top),sha256=self.sha(self.top))
        (self.root/'index.json').write_text(json.dumps(dict(dates={'20261104':numeric},top200={'20261104':top_ref})))
        legacy=self.root/'legacy.json';legacy.write_text(json.dumps(dict(schema_version='v4.research.a_share_pool_top200.v1',generated_at='old',available_dates=[],dates=[])))
        pages=copy.deepcopy(self.pages);page=pages[0];page.update(ok=True,recommendation_status='WATCH_ONLY_BACKTEST_GATED',write_policy='read_only',production_allowed=False,buy_gate_updated=False,orders_sent=False,a_all_pool_row_count=1);page['pools'][0].update(pool_size=1,status='READY')
        return read_daily_projection,legacy,pages

    def test_new_date_is_discovered_from_current_index_not_static_dates(self):
        project,legacy,pages=self.daily_root();before=(self.root/'index.json').read_bytes()
        result=project('20261104',lambda *args,**kwargs:pages[0],self.root,self.root,legacy)
        row=result['dates'][0];self.assertEqual(result['requested_date'],'20261104');self.assertEqual(row['a_pool']['selected_count'],1);self.assertEqual(row['a_pool']['hit_count'],1);self.assertEqual(len(row['stocks']),2);self.assertEqual(row['seven_stage']['hit_count'],None)
        self.assertEqual((self.root/'index.json').read_bytes(),before)

    def test_wrong_pool_date_and_numeric_generation_are_rejected(self):
        project,legacy,pages=self.daily_root();pages[0]['trade_date']='20261105'
        with self.assertRaisesRegex(ValueError,'POOL_DATE'):project('20261104',lambda *args,**kwargs:pages[0],self.root,self.root,legacy)
        top=json.loads(self.top.read_text());top['source_generation']='wrong';self.top.write_text(json.dumps(top));index=json.loads((self.root/'index.json').read_text());index['top200']['20261104']['sha256']=self.sha(self.top);(self.root/'index.json').write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError,'NUMERIC_IDENTITY'):project('20261104',lambda *args,**kwargs:pages[0],self.root,self.root,legacy)

    def test_unknown_date_does_not_substitute_existing_top200(self):
        project,legacy,pages=self.daily_root();result=project('20261105',lambda *args,**kwargs:self.fail('no source date should not fetch another pool'),self.root,self.root,legacy)
        self.assertEqual(result['requested_date'],'20261105');self.assertEqual(result['dates'],[]);self.assertEqual(result['selected_source_status'],'NOT_MATERIALIZED')

    def test_complete_pagination_and_one_bad_stage_are_isolated(self):
        from ops.build_a_share_pool_top200 import _complete_pages
        project,legacy,pages=self.daily_root();first=pages[0];first['a_all_pool_row_count']=2;first['pools'][0]['pool_size']=2;second=copy.deepcopy(first);second['a_all_pool_rows']=[{'symbol':'A.000001'}];second['pools'][0]['rows']=[{'symbol':'A.000001'}]
        calls=[]
        def page(date,limit,offset=0):calls.append(offset);return first if offset==0 else second
        gathered,sets,union=_complete_pages('20261104',page);self.assertEqual(calls,[0,300]);self.assertEqual(len(union),2)
        second['input_fingerprint']='drift'
        with self.assertRaisesRegex(ValueError,'FINGERPRINT'):_complete_pages('20261104',page)
        first['a_all_pool_row_count']=1;first['pools'][0]['pool_size']=1
        (self.root/'selection_latest.json').write_text(json.dumps({'entries':{'20261104/STAGE_0925/A_SHARE':{'artifact_relative':'selection_runs/20261103/wrong.csv','artifact_sha256':'bad'}}}))
        row=project('20261104',lambda *args,**kwargs:first,self.root,self.root,legacy)['dates'][0]
        self.assertEqual(row['a_pool']['hit_count'],1);self.assertEqual(row['seven_stage']['stages']['STAGE_0925']['status'],'CANNOT_CONFIRM');self.assertIsNone(row['seven_stage']['hit_count'])



class StageIdentityRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.date='20261105';self.stage='STAGE_0940_0945'
    def artifact(self,stage,market='A_SHARE',code='SH.600001',run='run-test'):
        role=market+'_SELECTION_'+stage;relative='/'.join(('selection_runs',self.date,role,run,'artifact.csv'));path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('code\n'+code+'\n')
        return dict(market=market,stage_id=stage,trade_date=self.date,role=role,run_id=run,artifact_relative=relative,artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def project(self,bad,good=None):
        from ops.build_a_share_pool_top200 import _stage_projection
        entries={self.date+'/'+self.stage+'/A_SHARE':bad}
        if good:entries[self.date+'/STAGE_0930_0935/A_SHARE']=good
        (self.root/'selection_latest.json').write_text(json.dumps({'entries':entries}))
        return _stage_projection(self.date,self.root,{'600001.SH'})
    def test_same_date_hk_entry_under_a_key_is_unknown_and_valid_a_survives(self):
        hk=self.artifact(self.stage,'HK_CONNECT','HK.00700');good=self.artifact('STAGE_0930_0935')
        seven,coverage,_=self.project(hk,good)
        self.assertEqual(coverage['available'],1);self.assertEqual(seven['selected_count'],1);self.assertEqual(seven['hit_count'],1)
        rejected=seven['stages'][self.stage];self.assertEqual(rejected['status'],'CANNOT_CONFIRM');self.assertIsNone(rejected['hit_count']);self.assertIn('MARKET_DATE_STAGE_ROLE_CONFLICT',rejected['error'])
        seven,coverage,_=self.project(hk);self.assertEqual(coverage['available'],0);self.assertIsNone(seven['selected_count']);self.assertIsNone(seven['hit_count'])
    def test_metadata_and_run_path_conflicts_cannot_become_ready(self):
        valid=self.artifact(self.stage);good=self.artifact('STAGE_0930_0935')
        for key,value in [('market','HK_CONNECT'),('trade_date','20261104'),('stage_id','STAGE_UNKNOWN'),('role','UNKNOWN_ROLE'),('run_id','run-other'),('artifact_relative','selection_runs/20261105/UNKNOWN/run-test/artifact.csv')]:
            with self.subTest(field=key):
                bad=copy.deepcopy(valid);bad[key]=value;seven,coverage,_=self.project(bad,good)
                self.assertEqual(coverage['available'],1);self.assertEqual(seven['hit_count'],1);self.assertEqual(seven['stages'][self.stage]['status'],'CANNOT_CONFIRM');self.assertIsNone(seven['stages'][self.stage]['hit_count'])
        malformed=self.artifact(self.stage,run='run-bad'+chr(92)+'path');seven,coverage,_=self.project(malformed,good)
        self.assertEqual(coverage['available'],1);self.assertEqual(seven['stages'][self.stage]['status'],'CANNOT_CONFIRM')
        for bad in [{},'not-metadata']:
            seven,coverage,_=self.project(bad,good);self.assertEqual(coverage['available'],1);self.assertEqual(seven['stages'][self.stage]['status'],'CANNOT_CONFIRM')
    def test_hk_csv_cannot_become_zero_even_with_a_metadata(self):
        bad=self.artifact(self.stage,code='HK.00700');seven,coverage,_=self.project(bad)
        self.assertEqual(coverage['available'],0);self.assertIsNone(seven['hit_count']);self.assertIn('ROW_MARKET_IDENTITY_CONFLICT',seven['stages'][self.stage]['error'])

if __name__ == '__main__':
    unittest.main()
