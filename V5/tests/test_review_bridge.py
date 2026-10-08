"""Readback bridge must preserve published results, dates, and evidence gaps."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from v5_shadow.digests import canonical_bytes, sha256_json

class ReviewBridgeTests(unittest.TestCase):
    def fixture(self, root):
        day='20261008'
        artifact=dict(schema_version='v3_5.close_review.v1',trade_date=day,
            status='MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE', reference_snapshot=False,
            evidence_mode='V3_5_NATIVE_PRODUCTION',close_source_sha256='a'*64,
            production_allowed=False,buy_gate_updated=False,orders_sent=False,
            write_policy='review_only_read_only',models={},stages={},stage_union={},kpi={},
            row_counts={'hkconnect_universe':698,'model':100,'stage':0},
            close_top20=[{'code':f'HK.{i:05}'} for i in range(1,21)],
            model_rows=[{'symbol':f'HK.{i:05}'} for i in range(1,101)],stage_rows=[],
            top20_attribution=[],missing_stages=['STAGE_0925','STAGE_0930_0935'],
            cannot_confirm=['STAGE_EVIDENCE_MISSING'])
        relative=f'close_reviews/{day}.json'; receipt=f'receipts/close_reviews/{day}.json'
        values={relative:artifact,receipt:dict(schema_version='v3_import_receipt.v1',payload_path=relative,
            source_sha256=sha256_json(artifact),trade_date=day),'manifest.json':{relative:sha256_json(artifact)}}
        hashes={}
        for name,value in values.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);data=canonical_bytes(value);path.write_bytes(data)
            hashes[name]=hashlib.sha256(data).hexdigest()
        return dict(target_date=day,input_root=str(root),input_files=hashes),artifact
    def invoke(self, request):
        from v5_shadow.review_bridge import run_review_bridge
        return run_review_bridge(request)
    def test_preserves_original_review_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,artifact=self.fixture(Path(tmp)); result=self.invoke(request)
            review=result['review']['market_reviews']['HK']['model_selection_review']
            for key in ('status','close_top20','model_rows','stage_rows','missing_stages','cannot_confirm'):
                self.assertEqual(review[key],artifact[key])
            self.assertEqual(result['review']['market_reviews']['A']['status'],'NOT_MATERIALIZED')
            self.assertFalse(result['natural_verified']);self.assertEqual(result['readback_kind'],'BOUND_REVIEW_ARTIFACT_READBACK')
            self.assertEqual(result['input_files'],request['input_files'])
            self.assertFalse(result['review']['v5_readback']['source_origin_verified'])
            self.assertNotIn('original_owner_result',result['review']['v5_readback'])
            for name,digest in request['input_files'].items():
                self.assertEqual(hashlib.sha256((Path(tmp)/name).read_bytes()).hexdigest(),digest)
    def test_catalog_only_claims_verified_review_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_=self.fixture(Path(tmp));catalog=self.invoke(request)['catalog']
            self.assertEqual(catalog['review_dates'],['20261008']);self.assertEqual(catalog['stage_dates'],[])
            self.assertEqual(catalog['navigation_date'],'20261008');self.assertEqual(catalog['runtime_identity']['application'],'V5')
            self.assertEqual(catalog['future_target_dates'],[])
    def test_changed_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_=self.fixture(Path(tmp));(Path(tmp)/'manifest.json').write_text('{}')
            with self.assertRaises(ValueError):self.invoke(request)
    def test_self_consistent_raw_hash_cannot_hide_bad_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_=self.fixture(Path(tmp));name='receipts/close_reviews/20261008.json';p=Path(tmp)/name
            value=json.loads(p.read_bytes());value['source_sha256']='b'*64;p.write_bytes(canonical_bytes(value))
            request['input_files'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):self.invoke(request)
    def test_wrong_day_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            request,_=self.fixture(Path(tmp));request['target_date']='20261009'
            with self.assertRaises(ValueError):self.invoke(request)
    def test_symlink_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'input';root.mkdir();request,_=self.fixture(root)
            p=root/'manifest.json';outside=Path(tmp)/'other.json';p.rename(outside);p.symlink_to(outside)
            with self.assertRaises(ValueError):self.invoke(request)

if __name__=='__main__':unittest.main()
