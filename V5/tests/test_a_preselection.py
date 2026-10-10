"""Exercise frozen A pool builders in a source-only child, without V4 writes."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


def make_lane(root,kind='fupan',count=1,corrupt=False,target_date='20261008',signal_date='20260930'):
    root.mkdir()
    pool=root/'pool.csv';manifest=root/'manifest.json'
    with pool.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['ts_code','stock_name','signal_date','rank','pool_score'])
        writer.writeheader()
        for i in range(count):writer.writerow(dict(ts_code=f'{i+1:06}.SZ',stock_name='SYNTHETIC',signal_date=signal_date,rank=i+1,pool_score=10+i))
    value=dict(target_date=target_date,signal_date=signal_date,row_count=count,cannot_confirm=['SYNTHETIC_FIXTURE_ONLY'])
    if kind=='fupan':value.update(status='FUPAN_WATCHLIST_POOL_READY',fupan_pool_rule='AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW',source_paths=['SYNTHETIC_ONLY'])
    else:value.update(status='STAGE7_TAIL_POOL_READY',source_role='real_d1_stage7_tail_replay',upstream_manifest=dict(trade_date=signal_date,stage_id='STAGE_1445_1500',production_allowed=False,buy_gate_updated=False,orders_sent=False))
    if corrupt:value['row_count']=count+1
    manifest.write_text(json.dumps(value))
    return dict(kind=kind,input_root=str(root),paths=dict(pool='pool.csv',manifest='manifest.json'),
                files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (pool,manifest)})


def make_research_lane(root,*,preview=True,selector=True):
    root.mkdir()
    files={}
    for name,present in (('research_preview.json',preview),('selector.json',selector)):
        path=root/name
        if present:
            path.write_text('{}')
            files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            files[name]=None
    return dict(kind='research',input_root=str(root),
                paths=dict(preview='research_preview.json',selector='selector.json'),files=files)


def make_research_article(identity,archive_date,published_at):
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    return dict(article_id=digest('article:'+identity),dedupe_key=digest('dedupe:'+identity),
                archive_date=archive_date,stock_code='000001.SZ',stock_name='FIXTURE',
                source_type='FIXTURE',source_name='fixture',source_title=identity,
                source_path_sha256=digest('path:'+identity),url='https://example.invalid/'+identity,
                theme='fixture',catalyst='fixture',evidence_sentence='fixture evidence',
                evidence_level='MEDIUM',confidence=0.5,published_at=published_at,
                collected_at=archive_date[:4]+'-'+archive_date[4:6]+'-'+archive_date[6:]+'T23:59:00+08:00',
                first_seen_at=archive_date[:4]+'-'+archive_date[4:6]+'-'+archive_date[6:]+'T23:58:00+08:00',
                duplicate_evidence_count=1,source_dedup_keys=[],recommendation_status='RESEARCH_ONLY')


def make_research_payload(archive_date,slot,articles):
    day=archive_date[:4]+'-'+archive_date[4:6]+'-'+archive_date[6:]
    generated=day+'T'+slot[:2]+':'+slot[2:]+':00+08:00'
    stock=dict(stock_code='000001.SZ',stock_name='FIXTURE',archive_date=archive_date,
               research_score=1,research_status='READY',evidence_count=len(articles),source_count=1,
               strong_evidence_count=0,medium_evidence_count=len(articles),weak_evidence_count=0,
               source_types=['FIXTURE'],themes=['fixture'],top_catalysts=['fixture'],
               first_seen_at=generated,collected_at=generated,formal_overlap=False,stage_overlap=False,
               recommendation_status='RESEARCH_ONLY')
    return dict(schema_version='v3_5.research_archive.v1',archive_date=archive_date,status='READY',
                timezone='Asia/Shanghai',source_input_sha256=hashlib.sha256((archive_date+slot).encode()).hexdigest(),
                source_schema_version='fixture.v1',source_generated_at=generated,
                dedupe_key_fields=['stock_code','source_title','url','source_path','source_name','claim_type_or_evidence_level'],
                article_count=len(articles),stock_pool_count=1,source_counts={'FIXTURE':len(articles)},
                articles=articles,stock_pool=[stock],cannot_confirm=[],write_policy='read_only',
                recommendation_status='RESEARCH_ONLY',production_allowed=False,buy_gate_updated=False,orders_sent=False)


def research_hourly_item(archive_date,slot,articles):
    normalized=[make_research_article(identity,archive_date,published_at)
                for identity,published_at in articles]
    return dict(slot=slot,payload=make_research_payload(archive_date,slot,normalized))


def publish_frozen_hourly_fixture(root,payloads):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from infrastructure.research_store import HourlyResearchStore
root=Path(sys.argv[2]);store=HourlyResearchStore(root)
for item in json.loads(sys.argv[3]):store.publish(item['payload'],slot=item['slot'],mode='LIVE')
print('FROZEN_HOURLY_FIXTURE_PUBLISHED')
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),json.dumps(payloads)],
                              capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('frozen hourly fixture publisher failed: '+result.stderr)


def rewrite_frozen_hourly_schema(root,archive_date,slot,schema_version):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import hashlib,importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from infrastructure.research_store import HourlyResearchStore
from infrastructure.data_store import _sha256
root=Path(sys.argv[2]);archive_date=sys.argv[3];slot=sys.argv[4];schema_version=sys.argv[5]
store=HourlyResearchStore(root);relative=store._relative(archive_date,slot,'LIVE')
receipt_relative=store._receipt_relative(archive_date,slot,'LIVE')
payload=store._read(relative);payload['schema_version']=schema_version
digest=_sha256(payload);store._write(relative,payload)
manifest=store._manifest();manifest[relative]=digest;store._write_manifest(manifest)
store._write(receipt_relative,store._receipt(payload,digest,slot=slot,mode='LIVE'))
print('FROZEN_HOURLY_PAYLOAD_MANIFEST_RECEIPT_REBOUND '+digest)
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),
                               archive_date,slot,schema_version],capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('frozen hourly schema fixture rewrite failed: '+result.stderr)


def rewrite_frozen_hourly_payload_field(root,archive_date,slot,field,value):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from infrastructure.research_store import HourlyResearchStore
from infrastructure.data_store import _sha256
root=Path(sys.argv[2]);archive_date=sys.argv[3];slot=sys.argv[4];field=sys.argv[5];value=json.loads(sys.argv[6])
store=HourlyResearchStore(root);relative=store._relative(archive_date,slot,'LIVE')
receipt_relative=store._receipt_relative(archive_date,slot,'LIVE')
payload=store._read(relative);payload[field]=value;digest=_sha256(payload)
store._write(relative,payload);manifest=store._manifest();manifest[relative]=digest;store._write_manifest(manifest)
store._write(receipt_relative,store._receipt(payload,digest,slot=slot,mode='LIVE'))
print('FROZEN_HOURLY_FIELD_MANIFEST_RECEIPT_REBOUND '+digest)
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),
                               archive_date,slot,field,json.dumps(value)],capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('frozen hourly field fixture rewrite failed: '+result.stderr)


def rewrite_frozen_hourly_payload_root(root,archive_date,slot,payload):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from infrastructure.research_store import HourlyResearchStore
from infrastructure.data_store import _sha256
root=Path(sys.argv[2]);archive_date=sys.argv[3];slot=sys.argv[4];payload=json.loads(sys.argv[5])
store=HourlyResearchStore(root);relative=store._relative(archive_date,slot,'LIVE')
receipt_relative=store._receipt_relative(archive_date,slot,'LIVE');digest=_sha256(payload)
store._write(relative,payload);manifest=store._manifest();manifest[relative]=digest;store._write_manifest(manifest)
store._write(receipt_relative,{'schema_version':'v3_5.hourly_research_receipt.v1',
    'archive_date':archive_date,'slot':slot,'mode':'LIVE','payload_path':relative,
    'payload_sha256':digest,'source_input_sha256':'0'*64,'article_count':0,
    'stock_pool_count':0,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
print('FROZEN_HOURLY_ROOT_MANIFEST_RECEIPT_REBOUND '+digest)
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),
                               archive_date,slot,json.dumps(payload)],capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('frozen hourly root-shape fixture rewrite failed: '+result.stderr)


def frozen_hourly_owner_artifact(root,target_date):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from domains.preselection_materializer import build_hourly_research_pool
from v5_shadow.digests import canonical_bytes
print(canonical_bytes(build_hourly_research_pool(Path(sys.argv[2]),trade_date=sys.argv[3])).decode())
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),target_date],
                              capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('direct frozen owner failed: '+result.stderr)
    return json.loads(result.stdout)


def frozen_preview_owner_artifact(root,target_date):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    code=r'''import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
from domains.preselection_materializer import build_research_preview_pool
from v5_shadow.digests import canonical_bytes
root=Path(sys.argv[2])
artifact=build_research_preview_pool(root/'research_preview.json',root/'selector.json',sys.argv[3])
print(canonical_bytes(artifact).decode())
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),target_date],
                              capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('direct frozen preview owner failed: '+result.stderr)
    return json.loads(result.stdout)


def make_research_lane_from_root(root):
    root=Path(root).resolve();files={}
    for path in root.rglob('*'):
        if path.is_symlink():raise AssertionError('fixture unexpectedly contains a symlink')
        if path.is_file():files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('research_preview.json','selector.json'):
        files[name]=None
    return dict(kind='research',input_root=str(root),
                paths=dict(preview='research_preview.json',selector='selector.json'),files=files)


def make_v192_lane(root,target_date,signal_date):
    import subprocess,sys
    from v5_shadow import a_preselection as module
    root=Path(root).resolve();root.mkdir(parents=True)
    panel=root/'selector.parquet';panel.write_bytes(b'frozen-panel-fixture')
    row={'ts_code':'000661.SZ','stock_code':'000661','stock_name':'FIXTURE',
         'candidate_role':'TEST_ONLY_BUY_CANDIDATE','multi_head_final_role':'B2_FRESH_ENTRY','entry_pool':True,
         'review_rank_v19':1,'final_score':91.5,'fresh_b2_entry_score':80,'continuation_entry_score':0,
         'risk_chase_score':12,'rank_usage_boundary':'RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY',
         'formal_recommendation_allowed':False,'primary_buy_signal':1,'secondary_buy_signal':0,
         'gold_brick_context':'none','brick_resonance_context':0,'brick_buy':0,'brick_buy1_low_absorb':0,
         'brick_buy2_attack':0,'brick_resonance1':0,'brick_resonance2':0,'brick_resonance':0,
         'ref_hold_score':4,'B1':0,'B2':1,'B3':0,'BG':1,'amount':1500000000,
         'formula_source':'computed_main_chart_formula_20260515',
         'field_contract_version':'formula_signal_v2_reference_score'}
    code=r'''import importlib,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.a_preselection import _FrozenLoader,_source_bytes
sys.meta_path.insert(0,_FrozenLoader(_source_bytes()))
v=importlib.import_module('upstreams.v3_shared_data.shared_data.v192_selector')
v.publish_v192_rows(Path(sys.argv[2]),panel_path=Path(sys.argv[3]),signal_date=sys.argv[4],target_date=sys.argv[5],
                    rows=[__import__('json').loads(sys.argv[6])],oracle_sha256s=v.FROZEN_ORACLE_SHA256S)
'''
    with tempfile.TemporaryDirectory() as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                               '-c',code,str(Path(module.__file__).parents[1]),str(root),str(panel),
                               signal_date,target_date,json.dumps(row)],capture_output=True,text=True)
    if result.returncode:
        raise AssertionError('frozen v192 fixture publisher failed: '+result.stderr)
    files={}
    for path in root.rglob('*'):
        if path.is_symlink():raise AssertionError('fixture unexpectedly contains a symlink')
        if path.is_file():files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(kind='v192',input_root=str(root),paths={},files=files)


def make_wechat_lane(root,target_date,signal_date):
    root.mkdir();rows=root/'rows.csv';manifest=root/'manifest.json'
    rows.write_text('ts_code,stock_name,candidate_score,wechat_v3_preselect_rank,signal_date\n000001.SZ,FIXTURE,42,1,'+signal_date+'\n')
    value=dict(status='WECHAT_V3_PRESELECT_READY',effective_trade_date=target_date,
               target_validation={'status':'TARGET_DATE_CHECK_PASS'},
               boundary=dict(formal_pool_write=False,buy_gate_write=False),score_scope='wechat_pool_ts_codes_only',
               counts={'v3_matched_codes':1},signal_date=signal_date,article_publish_date=signal_date)
    manifest.write_text(json.dumps(value))
    return dict(kind='wechat',input_root=str(root),paths=dict(rows='rows.csv',manifest='manifest.json'),
                files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (rows,manifest)})


def make_baimao_lane(root,target_date):
    root.mkdir();path=root/'map.json'
    path.write_text(json.dumps(dict(trade_date=target_date,research_date=target_date,
                                    event_id='research:'+target_date+':fixture',opens_buy_gate=False,
                                    write_policy='RESEARCH_ONLY',candidates=[dict(state='RESEARCH_MAP',code='000001',
                                    name='FIXTURE',score=1)])))
    return dict(kind='baimao',input_root=str(root),paths={'data':'map.json'},
                files={'map.json':hashlib.sha256(path.read_bytes()).hexdigest()})


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
        self.assertTrue(_expected(ValueError('hourly research archive-date mismatch'),kind='research'))
        self.assertTrue(_expected(ValueError('hourly research manifest or receipt mismatch'),kind='research'))
        self.assertTrue(_expected(ValueError('invalid research archive schema'),kind='research'))
        self.assertTrue(_expected(ValueError('research stage evidence slot is invalid'),kind='research'))
        self.assertTrue(_expected(ValueError('invalid research article article_id'),kind='research'))
        self.assertTrue(_expected(KeyError('article_count'),kind='research'))
        self.assertFalse(_expected(KeyError('unrelated_payload_field'),kind='research'))
        self.assertTrue(_expected(AttributeError("'list' object has no attribute 'get'"),kind='research'))
        self.assertFalse(_expected(AttributeError("'dict' object has no attribute 'get'"),kind='research'))
        for payload in ([], '', 1, 1.0, None, True):
            with self.subTest(payload_root=type(payload).__name__):
                try:payload['archive_date']
                except TypeError as error:self.assertTrue(_expected(error,kind='research'))
        self.assertTrue(_expected(TypeError("'int' object is not iterable"),kind='research'))
        self.assertFalse(_expected(TypeError('unexpected programmer type error'),kind='research'))
        self.assertFalse(_expected(WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED'),kind='research'))
        self.assertFalse(_expected(ValueError('hourly research unexpected programmer error'),kind='research'))

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

    def test_research_lane_calls_hourly_owner_first_and_never_reads_preview_when_healthy(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from v5_shadow import a_preselection as module
        lane=make_research_lane(self.root/'research')
        expected=dict(pool_id='a_share_research_recommendation_pool',rows=[dict(pool_score=2,article_count=2)])
        owner=SimpleNamespace(build_hourly_research_pool=Mock(return_value=expected),
                              build_research_preview_pool=Mock(side_effect=AssertionError('preview was read')),
                              build_baimao_pool=Mock(side_effect=AssertionError('research lane fell through to baimao')))
        with patch.object(module,'_file_sha',side_effect=AssertionError('unused preview bytes were opened')) as file_sha:
            module._verify_lane(lane,verify_optional=False)
            file_sha.assert_not_called()
        result=module._build(owner,lane,'20261008','20260930')
        self.assertIs(result,expected)
        owner.build_hourly_research_pool.assert_called_once_with(Path(lane['input_root']),trade_date='20261008')
        owner.build_research_preview_pool.assert_not_called()

    def test_research_lane_falls_back_only_for_file_not_found_and_both_preview_inputs(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from v5_shadow.a_preselection import _build
        lane=make_research_lane(self.root/'research')
        expected=dict(pool_id='a_share_research_recommendation_pool',rows=[])
        owner=SimpleNamespace(build_hourly_research_pool=Mock(side_effect=FileNotFoundError('no verified hourly slots')),
                              build_research_preview_pool=Mock(return_value=expected),
                              build_baimao_pool=Mock(side_effect=AssertionError('research lane fell through to baimao')))
        self.assertIs(_build(owner,lane,'20261008','20260930'),expected)
        owner.build_hourly_research_pool.assert_called_once_with(Path(lane['input_root']),trade_date='20261008')
        owner.build_research_preview_pool.assert_called_once_with(Path(lane['input_root'])/'research_preview.json',
                                                                  Path(lane['input_root'])/'selector.json','20261008')

    def test_research_lane_does_not_fallback_on_corruption_or_wrong_identity(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from v5_shadow import a_preselection as module
        lane=make_research_lane(self.root/'research')
        for error in (ValueError('hourly research archive-date mismatch'),
                      ValueError('hourly research manifest or receipt mismatch'),
                      ValueError('invalid research archive schema'),
                      TypeError('list indices must be integers or slices, not str')):
            owner=SimpleNamespace(build_hourly_research_pool=Mock(side_effect=error),
                                  build_research_preview_pool=Mock(),
                                  build_baimao_pool=Mock(side_effect=AssertionError('research lane fell through to baimao')))
            with self.subTest(error=str(error)),self.assertRaises(type(error)):
                module._build(owner,lane,'20261008','20260930')
            owner.build_research_preview_pool.assert_not_called()
        wrong_identity=dict(pool_id='a_share_research_recommendation_pool',trade_date='20261007',market='A',rows=[])
        owner=SimpleNamespace(build_hourly_research_pool=Mock(return_value=wrong_identity),
                              build_research_preview_pool=Mock(),
                              build_baimao_pool=Mock(side_effect=AssertionError('research lane fell through to baimao')))
        self.assertIs(module._build(owner,lane,'20261008','20260930'),wrong_identity)
        owner.build_research_preview_pool.assert_not_called()

        lane['files']['research_preview.json']='0'*64
        owner=SimpleNamespace(build_hourly_research_pool=Mock(side_effect=FileNotFoundError('no verified slots')),
                              build_research_preview_pool=Mock(),
                              build_baimao_pool=Mock(side_effect=AssertionError('research lane fell through to baimao')))
        with self.assertRaisesRegex(module.InputEvidenceError,'INPUT_BYTES_MISMATCH'):
            module._build(owner,lane,'20261008','20260930')
        owner.build_research_preview_pool.assert_not_called()

    def test_research_lane_missing_preview_pair_is_cannot_confirm_not_a_fallback(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from v5_shadow.a_preselection import _build
        lane=make_research_lane(self.root/'research',selector=False)
        expected=dict(pool_id='a_share_research_recommendation_pool',status='CANNOT_CONFIRM',rows=[])
        owner=SimpleNamespace(build_hourly_research_pool=Mock(side_effect=FileNotFoundError('no verified slots')),
                              build_research_preview_pool=Mock(),
                              build_expected_missing_pool=Mock(return_value=expected))
        self.assertIs(_build(owner,lane,'20261008','20260930'),expected)
        owner.build_research_preview_pool.assert_not_called()
        owner.build_expected_missing_pool.assert_called_once_with(
            '20261008',pool_id='a_share_research_recommendation_pool',display_name='A股研报推荐股票池',
            market='A',reason='A_SELECTOR_PANEL_UNAVAILABLE')

    def test_research_lane_original_hourly_owner_empty_window_is_cannot_confirm(self):
        lane=make_research_lane(self.root/'research',preview=False,selector=False)
        lane['files']['manifest.json']=None
        result=self.run_lanes([lane])
        self.assertEqual(result['status'],'CANNOT_CONFIRM')
        self.assertIsNone(result['row_count'])
        self.assertEqual(result['lanes'][0]['kind'],'research')
        self.assertFalse(result['lanes'][0]['accepted'])
        self.assertEqual(result['lanes'][0]['artifact']['status'],'CANNOT_CONFIRM')
        self.assertEqual(result['lanes'][0]['artifact']['pool_id'],
                         'a_share_research_recommendation_pool')

    def test_research_lane_requires_preview_and_selector_as_one_combined_lane(self):
        from v5_shadow.a_preselection import _request
        research=make_research_lane(self.root/'research',selector=False)
        request=dict(target_date='20261008',signal_date='20260930',data_kind='SYNTHETIC',lanes=[research])
        self.assertEqual(_request(request),request)
        other_paths={'v192':{},'fupan':{'pool':'pool.csv','manifest':'manifest.json'},
                     'stage7':{'pool':'pool.csv','manifest':'manifest.json'},
                     'wechat':{'rows':'rows.csv','manifest':'manifest.json'},
                     'baimao':{'data':'data.json'}}
        other_lanes=[]
        for kind,paths in other_paths.items():
            root=self.root/kind;root.mkdir()
            other_lanes.append(dict(kind=kind,input_root=str(root),paths=paths,
                                    files={name:None for name in paths.values()} or {'latest.json':None}))
        six_lane_request=dict(request,lanes=other_lanes+[research])
        self.assertEqual(_request(six_lane_request),six_lane_request)
        duplicate=dict(request,lanes=[research,research])
        with self.assertRaisesRegex(ValueError,'A_LANE_INVALID_OR_DUPLICATE'):
            _request(duplicate)

    def test_frozen_hourly_store_uses_bounded_directory_fds(self):
        import subprocess,sys
        lane=make_research_lane(self.root/'research',preview=False,selector=False)
        root=Path(lane['input_root'])
        manifest=root/'manifest.json';manifest.write_text('{}')
        lane['files']['manifest.json']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        for relative in ('research/hourly/live/20261008/unseen.json',
                         'receipts/research/hourly/live/20261008/unseen.json'):
            (root/relative).parent.mkdir(parents=True,exist_ok=True)
            lane['files'][relative]=None
        unlisted=root/'unlisted.json';unlisted.write_text('{"private":"fixture"}')
        (root/'UTC').write_bytes(b'UNDECLARED_INPUT_ROOT_ZONEINFO_PAYLOAD')
        code=r'''import importlib,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow import a_preselection as v5
lane=json.loads(sys.argv[2])
sys.meta_path.insert(0,v5._FrozenLoader(v5._source_bytes()))
store_type=importlib.import_module('infrastructure.research_store').HourlyResearchStore
from v5_shadow.a_preselection import WorkerBoundaryViolation
select=v5._guard([lane]);select(lane)
store=store_type(Path(lane['input_root']))
assert store._manifest()=={}
assert store.list_slots('20261008',mode='LIVE')==[]
print('FROZEN_STORE_MANIFEST_AND_DIRECTORY_ENUMERATION_OK')
with store._io.directory() as root_fd:
    for label,operation in (
        ('UNDECLARED_RELATIVE_DIRFD_DENIED',lambda:os.open('unlisted.json',os.O_RDONLY,dir_fd=root_fd)),
        ('ODIRECTORY_FILE_SPOOF_DENIED',lambda:os.open('unlisted.json',os.O_RDONLY|os.O_DIRECTORY,dir_fd=root_fd)),
        ('ROOT_DIRECTORY_ENUMERATION_DENIED',lambda:os.listdir(root_fd)),
    ):
        try:fd=operation()
        except WorkerBoundaryViolation:print(label)
        else:
            if isinstance(fd,int):os.close(fd)
            raise AssertionError(label+' was allowed')
'''
        from v5_shadow import a_preselection as module
        with tempfile.TemporaryDirectory() as cache:
            result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                                   '-c',code,str(Path(module.__file__).parents[1]),json.dumps(lane)],
                                  capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ('FROZEN_STORE_MANIFEST_AND_DIRECTORY_ENUMERATION_OK',
                         'UNDECLARED_RELATIVE_DIRFD_DENIED','ODIRECTORY_FILE_SPOOF_DENIED',
                         'ROOT_DIRECTORY_ENUMERATION_DENIED'):
            self.assertIn(expected,result.stdout)

        spoof_code=r'''import json,sys,zoneinfo
sys.path.insert(0,sys.argv[1])
from v5_shadow import a_preselection as v5
from v5_shadow.a_preselection import WorkerBoundaryViolation
lane=json.loads(sys.argv[2]);select=v5._guard([lane]);select(lane)
zoneinfo.reset_tzpath()
try:zoneinfo.ZoneInfo.no_cache('UTC')
except WorkerBoundaryViolation:print('PYTHONTZPATH_INPUT_ROOT_DENIED')
else:raise AssertionError('unlisted input-root UTC payload was read')
'''
        import os
        with tempfile.TemporaryDirectory() as cache:
            result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),
                                   '-c',spoof_code,str(Path(module.__file__).parents[1]),json.dumps(lane)],
                                  capture_output=True,text=True,
                                  env={**os.environ,'PYTHONTZPATH':str(root)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('PYTHONTZPATH_INPUT_ROOT_DENIED',result.stdout)

    def test_frozen_hourly_owner_windows_and_dedup_match_full_artifact(self):
        from v5_shadow import a_preselection as module
        root=self.root/'hourly-window-fixture';root.mkdir()
        payloads=[
            research_hourly_item('20261008','0800',[('before-start','2026-10-08T08:29:59+08:00')]),
            research_hourly_item('20261008','0900',[
                ('before-start','2026-10-08T08:29:59+08:00'),
                ('workday-a','2026-10-08T08:30:00+08:00'),
                ('workday-b','2026-10-08T08:45:00+08:00')]),
            research_hourly_item('20261009','0800',[
                ('workday-a','2026-10-08T08:30:00+08:00'),
                ('workday-b','2026-10-08T08:45:00+08:00'),
                ('workday-c','2026-10-09T08:29:59+08:00')]),
            research_hourly_item('20261009','0830',[
                ('workday-a','2026-10-08T08:30:00+08:00'),
                ('workday-b','2026-10-08T08:45:00+08:00'),
                ('workday-c','2026-10-09T08:29:59+08:00'),
                ('at-workday-end','2026-10-09T08:30:00+08:00')]),
            research_hourly_item('20261009','0900',[
                ('monday-start','2026-10-09T00:00:00+08:00')]),
            research_hourly_item('20261009','1200',[
                ('monday-start','2026-10-09T00:00:00+08:00'),
                ('friday-midday','2026-10-09T12:00:00+08:00')]),
            research_hourly_item('20261010','0900',[
                ('monday-start','2026-10-09T00:00:00+08:00'),
                ('friday-midday','2026-10-09T12:00:00+08:00'),
                ('saturday','2026-10-10T09:00:00+08:00')]),
            research_hourly_item('20261012','0830',[
                ('monday-start','2026-10-09T00:00:00+08:00'),
                ('friday-midday','2026-10-09T12:00:00+08:00'),
                ('saturday','2026-10-10T09:00:00+08:00'),
                ('monday-before-end','2026-10-12T08:59:59+08:00')]),
            research_hourly_item('20261012','0900',[
                ('monday-start','2026-10-09T00:00:00+08:00'),
                ('friday-midday','2026-10-09T12:00:00+08:00'),
                ('saturday','2026-10-10T09:00:00+08:00'),
                ('monday-before-end','2026-10-12T08:59:59+08:00'),
                ('at-monday-end','2026-10-12T09:00:00+08:00')]),
        ]
        publish_frozen_hourly_fixture(root,payloads)
        (root/'research_preview.json').write_text('must never be opened by a healthy hourly owner')
        (root/'selector.json').write_text('must never be opened by a healthy hourly owner')
        lane=make_research_lane_from_root(root)
        self.assertIsNone(lane['files']['research_preview.json'])
        self.assertIsNone(lane['files']['selector.json'])
        self.assertEqual(sum(value is not None for value in lane['files'].values()),
                         sum(1 for path in root.rglob('*') if path.is_file())-2)

        for target,signal,expected_signal,expected_ids in (
            ('20261009','20261008','20261008',{'workday-a','workday-b','workday-c','monday-start'}),
            ('20261012','20261009','20261009',{'workday-c','at-workday-end','monday-start',
                                                'friday-midday','saturday','monday-before-end'}),
        ):
            with self.subTest(target=target):
                direct=frozen_hourly_owner_artifact(root,target)
                assembled=self.run_lanes([lane],target_date=target,signal_date=signal)
                result=assembled['lanes'][0]
                self.assertEqual(assembled['status'],'ASSEMBLED')
                self.assertTrue(result['accepted'])
                self.assertEqual(result['artifact'],direct)
                self.assertEqual(result['artifact']['pool_id'],'a_share_research_recommendation_pool')
                self.assertEqual(result['artifact']['source_role'],'VERIFIED_HOURLY_RESEARCH')
                self.assertEqual(result['artifact']['rows'][0]['signal_date'],expected_signal)
                row=result['artifact']['rows'][0]
                actual_ids={identity for identity in expected_ids
                            if hashlib.sha256(('article:'+identity).encode()).hexdigest() in row['source_article_ids']}
                self.assertEqual(actual_ids,expected_ids)
                self.assertEqual(row['pool_score'],len(expected_ids))
                self.assertEqual(row['article_count'],len(expected_ids))
                self.assertEqual(len(row['source_article_ids']),len(expected_ids))
                self.assertNotIn(hashlib.sha256(b'article:before-start').hexdigest(),row['source_article_ids'])
                self.assertNotIn(hashlib.sha256(b'article:at-monday-end').hexdigest(),row['source_article_ids'])
                if target=='20261009':
                    self.assertNotIn(hashlib.sha256(b'article:at-workday-end').hexdigest(),row['source_article_ids'])

    def test_bad_hourly_research_isolated_from_five_healthy_lanes(self):
        root=self.root/'corrupt-hourly';root.mkdir()
        publish_frozen_hourly_fixture(root,[research_hourly_item(
            '20261008','0900',[('research-row','2026-10-08T09:00:00+08:00')])])
        payload_path=root/'research/hourly/live/20261008/0900.json'
        payload=json.loads(payload_path.read_text())
        payload['articles'][0]['stock_name']='TAMPERED_AFTER_RECEIPT'
        payload_path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        research=make_research_lane_from_root(root)
        target,signal='20261009','20261008'
        healthy=[
            make_v192_lane(self.root/'healthy-v192',target,signal),
            make_lane(self.root/'healthy-fupan','fupan',target_date=target,signal_date=signal),
            make_lane(self.root/'healthy-stage7','stage7',target_date=target,signal_date=signal),
            make_wechat_lane(self.root/'healthy-wechat',target,signal),
            make_baimao_lane(self.root/'healthy-baimao',target),
        ]
        result=self.run_lanes([research,*healthy],target_date=target,signal_date=signal)
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['row_count'],5)
        self.assertEqual([lane['kind'] for lane in result['lanes']],
                         ['research','v192','fupan','stage7','wechat','baimao'])
        self.assertFalse(result['lanes'][0]['accepted'])
        self.assertIsNone(result['lanes'][0]['artifact'])
        self.assertEqual(result['lanes'][0]['reason'],
                         'ValueError:hourly research manifest or receipt mismatch')
        self.assertTrue(all(lane['accepted'] for lane in result['lanes'][1:]))

    def test_sha_bound_schema_invalid_hourly_isolated_from_five_healthy_lanes(self):
        root=self.root/'schema-invalid-hourly';root.mkdir()
        publish_frozen_hourly_fixture(root,[research_hourly_item(
            '20261008','0900',[('research-row','2026-10-08T09:00:00+08:00')])])
        rewrite_frozen_hourly_schema(root,'20261008','0900','fixture.invalid.schema')
        preview=root/'research_preview.json'
        preview.write_text(json.dumps({'high_priority_candidates':[{
            'source_name':'fixture研报','title':'测试研报','published_at':'2026-10-08T09:00:00+08:00',
            'symbols':['000001.SZ']}]}),encoding='utf-8')
        selector=root/'selector.json'
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.table({'ts_code':['000001.SZ'],'name':['FIXTURE'],'trade_date':['20261008']}),selector)
        lane=make_research_lane_from_root(root)
        lane['files']['research_preview.json']=hashlib.sha256(preview.read_bytes()).hexdigest()
        lane['files']['selector.json']=hashlib.sha256(selector.read_bytes()).hexdigest()
        preview_artifact=frozen_preview_owner_artifact(root,'20261009')
        self.assertEqual(preview_artifact['source_role'],'RAW_SOURCE')
        self.assertEqual(preview_artifact['pool_id'],'a_share_research_recommendation_pool')
        self.assertEqual(len(preview_artifact['rows']),1)

        healthy=[
            make_v192_lane(self.root/'schema-healthy-v192','20261009','20261008'),
            make_lane(self.root/'schema-healthy-fupan','fupan',target_date='20261009',signal_date='20261008'),
            make_lane(self.root/'schema-healthy-stage7','stage7',target_date='20261009',signal_date='20261008'),
            make_wechat_lane(self.root/'schema-healthy-wechat','20261009','20261008'),
            make_baimao_lane(self.root/'schema-healthy-baimao','20261009'),
        ]
        result=self.run_lanes([lane,*healthy],target_date='20261009',signal_date='20261008')
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['row_count'],5)
        self.assertFalse(result['lanes'][0]['accepted'])
        self.assertIsNone(result['lanes'][0]['artifact'])
        self.assertEqual(result['lanes'][0]['reason'],'ValueError:invalid research archive schema')
        self.assertTrue(all(item['accepted'] for item in result['lanes'][1:]))

        manifest=root/'manifest.json';manifest_bytes=manifest.read_bytes()
        relative='research/hourly/live/20261008/0900.json'
        manifest.write_text(json.dumps([relative]),encoding='utf-8')
        lane['files']['manifest.json']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        result=self.run_lanes([lane,*healthy],target_date='20261009',signal_date='20261008')
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['row_count'],5)
        self.assertEqual(result['lanes'][0]['reason'],"AttributeError:'list' object has no attribute 'get'")
        self.assertTrue(all(item['accepted'] for item in result['lanes'][1:]))

        manifest.write_bytes(manifest_bytes)
        lane['files']['manifest.json']=hashlib.sha256(manifest_bytes).hexdigest()
        receipt=root/'receipts/research/hourly/live/20261008/0900.json'
        receipt.write_text('[]',encoding='utf-8')
        lane['files']['receipts/research/hourly/live/20261008/0900.json']=hashlib.sha256(receipt.read_bytes()).hexdigest()
        result=self.run_lanes([lane,*healthy],target_date='20261009',signal_date='20261008')
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['row_count'],5)
        self.assertEqual(result['lanes'][0]['reason'],
                         'ValueError:hourly research manifest or receipt mismatch')
        self.assertTrue(all(item['accepted'] for item in result['lanes'][1:]))

    def test_sha_bound_hourly_json_root_shapes_isolated_from_five_healthy_lanes(self):
        from v5_shadow.a_preselection import _expected
        for name,shape,expected_reason in (
            ('list-root',('root',[]),"TypeError:list indices must be integers or slices, not str"),
            ('int-root',('root',17),"TypeError:'int' object is not subscriptable"),
            ('articles-map',('field','articles',{}),'ValueError:research archive requires articles'),
            ('stock-pool-map',('field','stock_pool',{}),'ValueError:research archive requires stock pool'),
            ('article-map-item',('field','articles',[{}]),'ValueError:invalid research article fields'),
            ('source-counts-list',('field','source_counts',[]),'ValueError:invalid research source counts'),
            ('dedupe-keys-int',('field','dedupe_key_fields',1),"TypeError:'int' object is not iterable"),
        ):
            with self.subTest(payload_shape=name):
                root=self.root/f'root-shape-{name}';root.mkdir()
                publish_frozen_hourly_fixture(root,[research_hourly_item(
                    '20261008','0900',[('research-row','2026-10-08T09:00:00+08:00')])])
                if shape[0]=='root':rewrite_frozen_hourly_payload_root(root,'20261008','0900',shape[1])
                else:rewrite_frozen_hourly_payload_field(root,'20261008','0900',shape[1],shape[2])
                preview=root/'research_preview.json'
                preview.write_text(json.dumps({'high_priority_candidates':[{
                    'source_name':'fixture研报','title':'测试研报','published_at':'2026-10-08T09:00:00+08:00',
                    'symbols':['000001.SZ']}]}),encoding='utf-8')
                selector=root/'selector.json'
                import pyarrow as pa
                import pyarrow.parquet as pq
                pq.write_table(pa.table({'ts_code':['000001.SZ'],'name':['FIXTURE'],'trade_date':['20261008']}),selector)
                lane=make_research_lane_from_root(root)
                lane['files']['research_preview.json']=hashlib.sha256(preview.read_bytes()).hexdigest()
                lane['files']['selector.json']=hashlib.sha256(selector.read_bytes()).hexdigest()
                preview_artifact=frozen_preview_owner_artifact(root,'20261009')
                self.assertEqual(preview_artifact['source_role'],'RAW_SOURCE')
                self.assertEqual(preview_artifact['pool_id'],'a_share_research_recommendation_pool')
                self.assertEqual(len(preview_artifact['rows']),1)
                healthy=[
                    make_v192_lane(self.root/f'root-{name}-healthy-v192','20261009','20261008'),
                    make_lane(self.root/f'root-{name}-healthy-fupan','fupan',target_date='20261009',signal_date='20261008'),
                    make_lane(self.root/f'root-{name}-healthy-stage7','stage7',target_date='20261009',signal_date='20261008'),
                    make_wechat_lane(self.root/f'root-{name}-healthy-wechat','20261009','20261008'),
                    make_baimao_lane(self.root/f'root-{name}-healthy-baimao','20261009'),
                ]
                result=self.run_lanes([lane,*healthy],target_date='20261009',signal_date='20261008')
                self.assertEqual(result['status'],'PARTIAL')
                self.assertEqual(result['row_count'],5)
                self.assertEqual(result['lanes'][0]['reason'],expected_reason)
                self.assertTrue(all(item['accepted'] for item in result['lanes'][1:]))
                error_type=TypeError if expected_reason.startswith('TypeError:') else ValueError
                self.assertTrue(_expected(error_type(expected_reason.split(':',1)[1]),kind='research'))

    def test_misfiled_hourly_archive_date_is_refused_without_preview_fallback(self):
        root=self.root/'misfiled-hourly';root.mkdir()
        publish_frozen_hourly_fixture(root,[research_hourly_item(
            '20261007','0900',[('wrong-date-row','2026-10-07T09:00:00+08:00')])])
        old_payload=root/'research/hourly/live/20261007/0900.json'
        new_payload=root/'research/hourly/live/20261008/0900.json'
        old_receipt=root/'receipts/research/hourly/live/20261007/0900.json'
        new_receipt=root/'receipts/research/hourly/live/20261008/0900.json'
        new_payload.parent.mkdir(parents=True)
        new_receipt.parent.mkdir(parents=True)
        old_payload.rename(new_payload)
        old_receipt.rename(new_receipt)
        manifest_path=root/'manifest.json'
        manifest=json.loads(manifest_path.read_text())
        old_key='research/hourly/live/20261007/0900.json'
        new_key='research/hourly/live/20261008/0900.json'
        manifest[new_key]=manifest.pop(old_key)
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        preview=root/'research_preview.json'
        preview.write_text(json.dumps({'high_priority_candidates':[{
            'source_name':'fixture研报','title':'测试研报','published_at':'2026-10-08T09:00:00+08:00',
            'symbols':['000001.SZ']}]}),encoding='utf-8')
        selector=root/'selector.json'
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.table({'ts_code':['000001.SZ'],'name':['FIXTURE'],'trade_date':['20261008']}),selector)
        lane=make_research_lane_from_root(root)
        lane['files']['research_preview.json']=hashlib.sha256(preview.read_bytes()).hexdigest()
        lane['files']['selector.json']=hashlib.sha256(selector.read_bytes()).hexdigest()
        preview_artifact=frozen_preview_owner_artifact(root,'20261009')
        self.assertEqual(preview_artifact['source_role'],'RAW_SOURCE')
        self.assertEqual(preview_artifact['pool_id'],'a_share_research_recommendation_pool')
        self.assertEqual(len(preview_artifact['rows']),1)

        result=self.run_lanes([lane],target_date='20261009',signal_date='20261008')

        self.assertEqual(result['status'],'CANNOT_CONFIRM')
        self.assertIsNone(result['row_count'])
        self.assertFalse(result['lanes'][0]['accepted'])
        self.assertIsNone(result['lanes'][0]['artifact'])
        self.assertEqual(result['lanes'][0]['reason'],
                         'ValueError:hourly research manifest or receipt mismatch')

if __name__=='__main__':unittest.main()
