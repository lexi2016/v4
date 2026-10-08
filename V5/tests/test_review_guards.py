"""Negative evidence for the independent shadow milestone review."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from test_shadow_store import result
import test_worker_pipeline as pipeline
from test_frozen_reader import SCRIPT
from v5_shadow.contracts import parse_manifest
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.health import module_code_digest, observe_runtime
from v5_shadow.cli import load_capsule
from v5_shadow.shadow_store import publish_shadow, read_shadow

class ReviewGuardsTests(unittest.TestCase):
    def setUp(self):
        self.case = pipeline.WorkerPipelineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.output
    def bind_fixture(self):
        digest = sha256_json(self.case.source_bytes())
        self.case.config['bindings']['rebound_shadow']['input_snapshot_sha256'] = digest
        self.case.config_path.write_bytes(canonical_bytes(self.case.config))
        self.case.req.update(input_snapshot_sha256=digest, composition_sha256=sha256_json(self.case.config))
        self.case.req_path.write_bytes(canonical_bytes(self.case.req))
    def test_forged_input_digest_rejected(self):
        self.case.fixture()
        self.case.config['bindings']['rebound_shadow']['input_snapshot_sha256'] = 'f'*64
        self.case.config_path.write_bytes(canonical_bytes(self.case.config))
        self.case.req.update(input_snapshot_sha256='f'*64, composition_sha256=sha256_json(self.case.config))
        self.case.req_path.write_bytes(canonical_bytes(self.case.req))
        code, data = self.case.run_shadow()
        self.assertEqual(code, 3, data)
        self.assertIn('INPUT_SNAPSHOT_MISMATCH', data['reason_codes'])
    def test_changed_input_not_reused(self):
        self.case.fixture()
        self.assertEqual(self.case.run_shadow()[0], 0)
        (self.case.source/'SYNTHETIC_INPUT.json').write_text('{"changed":true}')
        code, data = self.case.run_shadow()
        self.assertEqual(code, 3, data)
        self.assertIn('INPUT_SNAPSHOT_MISMATCH', data['reason_codes'])
    def test_actual_dependency_drift_not_attested_by_lock(self):
        import importlib.metadata
        original = importlib.metadata.version
        def version(name):
            return '0.0.0' if name == 'pandas' else original(name)
        with patch('importlib.metadata.version', side_effect=version):
            observed = observe_runtime(parse_manifest(self.case.config['modules']['rebound_shadow']), load_capsule(), {})
        self.assertNotEqual(observed.dependency_lock_sha256,
                            self.case.config['modules']['rebound_shadow']['dependency_lock_sha256'])
    def test_wrong_valid_index_rejected(self):
        one = result(); two = replace(result(), request=replace(one.request,input_snapshot_sha256='0'*64))
        a = publish_shadow(self.root, one); b = publish_shadow(self.root, two)
        pa = self.root/'index'/(a.idempotency_key+'.json'); pb = self.root/'index'/(b.idempotency_key+'.json')
        pa.write_bytes(pb.read_bytes())
        with self.assertRaises(ValueError):publish_shadow(self.root, one)
    def test_cli_wrong_valid_ref_rejected(self):
        one = result(); two = replace(result(), request=replace(one.request,input_snapshot_sha256='0'*64))
        a = publish_shadow(self.root, one); b = publish_shadow(self.root, two)
        (self.root/'refs'/(a.run_id+'.json')).write_bytes((self.root/'refs'/(b.run_id+'.json')).read_bytes())
        code, data = self.case.call('read-result','--output-root',str(self.root),'--target-date','20261008','--run-id',a.run_id)
        self.assertEqual(code, 3, data)
    def test_failure_does_not_hit_success_cache(self):
        good = result(); a = publish_shadow(self.root, good)
        bad = replace(result(), request=good.request, business_status='CANNOT_CONFIRM', evaluated_count=None)
        b = publish_shadow(self.root, bad)
        self.assertNotEqual(a.run_id,b.run_id)
        self.assertEqual(read_shadow(self.root,b).business_status,'CANNOT_CONFIRM')
        self.assertEqual(read_shadow(self.root,a),good)
    def test_failure_does_not_poison_success_cache(self):
        good = result()
        bad = replace(result(), request=good.request, business_status='CANNOT_CONFIRM', evaluated_count=None)
        a = publish_shadow(self.root,bad); b = publish_shadow(self.root,good)
        self.assertNotEqual(a.run_id,b.run_id)
        self.assertEqual(read_shadow(self.root,b),good)
    def test_future_master_rejected(self):
        script = SCRIPT.replace('publish_fixture(root,original)',
                                "publish_fixture(root,original,master_captured_at='2026-10-08T09:00:00+08:00')")
        p = subprocess.run([sys.executable,'-B','-c',script,str(self.case.app),str(self.case.source),'fixture'],
                           env=self.case.env,capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        self.bind_fixture()
        code,data=self.case.run_shadow()
        self.assertEqual(code,3,data)
        self.assertIn('MASTER_AFTER_CUTOFF',data['reason_codes'])
    def test_new_directory_parents_synced_before_index(self):
        import v5_shadow.shadow_store as store
        events=[];fds={};real_open=os.open;real_sync=os.fsync;real_write=store.atomic_bytes
        def opened(path,*args,**kwargs):
            fd=real_open(path,*args,**kwargs);fds[fd]=str(path);return fd
        def synced(fd):
            events.append(('sync',fds.get(fd)));return real_sync(fd)
        def written(path,payload):
            if path.parent.name=='index':events.append(('index',str(path)))
            return real_write(path,payload)
        data=result()
        with patch.object(store.os,'open',side_effect=opened),patch.object(store.os,'fsync',side_effect=synced),patch.object(store,'atomic_bytes',side_effect=written):
            publish_shadow(self.root,data)
        before=events[:next(i for i,e in enumerate(events) if e[0]=='index')]
        paths={p for kind,p in before if kind=='sync'}
        for p in (self.root,self.root/'runs',self.root/'runs/20261008'):
            self.assertIn(str(p),paths)
    def test_worker_ignores_timestamp_cached_old_source(self):
        self.case.fixture()
        path=self.case.app/'src/v5_shadow/legacy_adapter.py'
        st=path.stat();before=path.read_text()
        py_compile.compile(str(path),doraise=True,invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        after=before.replace("SCHEMA='v4.manager_research.rebound_v3_screen.v1'", "SCHEMA='v9.manager_research.rebound_v3_screen.v1'")
        self.assertNotEqual(before,after);self.assertEqual(len(before),len(after))
        path.write_text(after);os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.case.config['modules']['rebound_shadow']['code_manifest_sha256']=module_code_digest(self.case.app/'src/v5_shadow')
        self.case.config_path.write_bytes(canonical_bytes(self.case.config))
        self.case.req['composition_sha256']=sha256_json(self.case.config)
        self.case.req_path.write_bytes(canonical_bytes(self.case.req))
        code,data=self.case.run_shadow()
        self.assertEqual(code,3,data)
        self.assertIn('LEGACY_CONTRACT_MISMATCH',data['reason_codes'])

if __name__=='__main__':unittest.main()
