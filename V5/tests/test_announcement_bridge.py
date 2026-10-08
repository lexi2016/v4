"""Mac-only integration fixture: copied original published announcement evidence."""
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

class AnnouncementBridgeTests(unittest.TestCase):
    def setUp(self):
        path=os.environ.get('V5_ANNOUNCEMENT_REQUEST_PATH')
        if not path:raise RuntimeError('V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP')
        self.request=json.loads(Path(path).read_bytes())
    def run_request(self,request):
        from v5_shadow.announcement_bridge import run_announcement_bridge
        return run_announcement_bridge(request)
    def copied(self,tmp):
        r=copy.deepcopy(self.request)
        for rootkey,filekey,name in [('manager_root','manager_files','manager'),('materials_root','material_files','materials')]:
            dest=Path(tmp)/name;dest.mkdir()
            for relative in r[filekey]:
                target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(Path(r[rootkey])/relative,target)
            r[rootkey]=str(dest)
        return r
    def analysis_path(self,r):
        token=r['publication_date'].replace('-','')
        return f"workspace_announcements/{r['target_date']}/eastmoney_date_catalog/{token}/analysis.v1.json"
    def test_original_reader_preserves_real_published_counts(self):
        r=copy.deepcopy(self.request);out=self.run_request(r)
        self.assertEqual(r,self.request)
        payload=out['payload'];self.assertEqual(payload['analysis']['status'],'VERIFIED')
        self.assertEqual(payload['publication_date'],'2026-10-07')
        selection=payload['analysis']['stock_selection']
        self.assertEqual(selection['selected_stock_count'],33)
        self.assertEqual(selection['conditional_watch_count'],54)
        self.assertEqual(selection['not_assessed_stock_count'],75)
        self.assertEqual(payload['owner_import_receipt']['status'],'VERIFIED')
        self.assertEqual(out['catalog']['readback']['derivation'],'REPARSED_FROM_SHARED_MATERIAL_STORE')
        self.assertEqual(set(out['original_reader_accesses']['materials']),set(r['material_files']))
        self.assertFalse(out['natural_verified']);self.assertFalse(out['source_origin_verified'])
        self.assertFalse(out['workspace_consumption_verified'])
        self.assertEqual(out['input_files'],{'manager':r['manager_files'],'materials':r['material_files']})
    def test_explicit_compact_publication_date_keeps_same_material_day(self):
        r=copy.deepcopy(self.request);r['publication_date']='20261007'
        out=self.run_request(r);self.assertEqual(out['payload']['publication_date'],'2026-10-07')
    def test_wrong_target_cannot_fall_back(self):
        r=copy.deepcopy(self.request);r['target_date']='20261009'
        with self.assertRaises(ValueError):self.run_request(r)
    def test_wrong_publication_date_cannot_fall_back(self):
        r=copy.deepcopy(self.request);r['publication_date']='2026-10-08'
        with self.assertRaises(ValueError):self.run_request(r)
    def test_changed_raw_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp);p=Path(r['manager_root'])/self.analysis_path(r)
            p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaises(ValueError):self.run_request(r)
    def test_broken_receipt_rejected_even_when_raw_pin_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp);name=self.analysis_path(r).replace('analysis.v1.json','owner_import_receipt.v1.json');p=Path(r['manager_root'])/name
            value=json.loads(p.read_bytes());value['product_sha256']='0'*64
            raw=json.dumps(value,ensure_ascii=False).encode();p.write_bytes(raw);r['manager_files'][name]=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):self.run_request(r)
    def test_missing_raw_material_not_recollected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp);name=next(k for k in r['material_files'] if k.startswith('blobs/'))
            (Path(r['materials_root'])/name).unlink()
            with self.assertRaises(ValueError):self.run_request(r)
    def test_symlink_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=copy.deepcopy(self.request);p=Path(tmp)/'linked';p.symlink_to(r['manager_root'],target_is_directory=True);r['manager_root']=str(p)
            with self.assertRaises(ValueError):self.run_request(r)
    def test_changed_index_with_updated_outer_pin_is_rejected_by_original_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp);name=next(k for k in r['material_files'] if k.startswith('index/'))
            p=Path(r['materials_root'])/name;value=json.loads(p.read_bytes());value['sha256']='0'*64
            raw=json.dumps(value,ensure_ascii=False).encode();p.write_bytes(raw);r['material_files'][name]=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):self.run_request(r)
    def test_default_publication_uses_original_hk_session_rule(self):
        r=copy.deepcopy(self.request);r['publication_date']=None
        out=self.run_request(r)
        self.assertEqual(out['payload']['publication_date'],'2026-10-07')
        self.assertEqual(out['payload']['date_selection_basis'],'PREVIOUS_HK_TRADING_SESSION')
    def _reseal_receipt(self,r,mutate):
        from v5_shadow.digests import sha256_json,canonical_bytes
        name=self.analysis_path(r).replace('analysis.v1.json','owner_import_receipt.v1.json');p=Path(r['manager_root'])/name
        value=json.loads(p.read_bytes());mutate(value)
        value['sha256']=sha256_json({k:v for k,v in value.items() if k!='sha256'})
        raw=canonical_bytes(value);p.write_bytes(raw);r['manager_files'][name]=hashlib.sha256(raw).hexdigest()
    def test_resealed_parent_mismatch_preserves_current_v4_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp)
            self._reseal_receipt(r,lambda v:v.update(parent_task_id='DIFFERENT_PARENT_TASK'))
            with self.assertRaises(ValueError):self.run_request(r)
    def test_partial_new_binding_group_preserves_current_v4_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.copied(tmp)
            def mutate(value):
                for key in ('evidence_run_id','handoff_manifest_sha256','agent_judgment_receipt_sha256'):value.pop(key,None)
                value['source_manifest_sha256']='a'*64
            self._reseal_receipt(r,mutate)
            with self.assertRaises(ValueError):self.run_request(r)
    def test_source_files_stay_byte_identical(self):
        r=self.request;self.run_request(r)
        for rootkey,filekey in [('manager_root','manager_files'),('materials_root','material_files')]:
            for name,digest in r[filekey].items():
                self.assertEqual(hashlib.sha256((Path(r[rootkey])/name).read_bytes()).hexdigest(),digest)

if __name__=='__main__':unittest.main()
