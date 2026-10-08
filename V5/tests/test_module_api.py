import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from v5_shadow.digests import canonical_bytes,sha256_json

class ModuleApiTests(unittest.TestCase):
    def setup_api(self,module='preselection'):
        from v5_shadow.module_api import create_module_server
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name).resolve()
        (root/'.v5-module-root').write_text('v5.module-root.v1:'+module+'\n')
        cfg=dict(schema_version='v5.module_api.v1',module_id=module,release_id='r1',data_root=str(root),routes=['/api/v3/preselection-pools'])
        server=create_module_server(cfg);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return root,'http://127.0.0.1:'+str(server.server_address[1])
    def record(self,root,payload=None):
        from v5_shadow.module_api import response_key
        query={'date':'20261008','limit':'200','offset':'0'}
        payload=payload if payload is not None else dict(schema_version='v3_preselection_pools.v1',trade_date='20261008',rows=[{'symbol':'A.000001'}],pagination=dict(offset=0,has_more=False))
        record=dict(schema_version='v5.module_response.v1',module_id='preselection',release_id='r1',path='/api/v3/preselection-pools',query=query,
                    payload=payload,payload_sha256=sha256_json(payload),source_input_sha256='a'*64,
                    data_kind='RECORDED_INPUT_REPLAY',generated_at='2026-10-08T13:00:00+08:00',status_code=200)
        path=root/'responses'/(response_key('preselection',record['path'],query)+'.json');path.parent.mkdir();path.write_bytes(canonical_bytes(record));return path
    def read(self,url):
        try:
            with urlopen(url,timeout=3) as r:return r.status,json.load(r),dict(r.headers)
        except HTTPError as error:
            with error:return error.code,json.load(error),dict(error.headers)
    def test_original_payload_and_identity_headers(self):
        root,url=self.setup_api();path=self.record(root)
        status,body,headers=self.read(url+'/api/v3/preselection-pools?offset=0&limit=200&date=20261008')
        self.assertEqual(status,200);self.assertEqual(body,json.loads(path.read_text())['payload'])
        self.assertEqual(headers['X-V5-Module'],'preselection');self.assertEqual(headers['X-V5-Release'],'r1')
    def test_missing_record_is_not_empty_success(self):
        root,url=self.setup_api();status,body,_=self.read(url+'/api/v3/preselection-pools?date=20261008')
        self.assertEqual(status,503);self.assertEqual(body['status'],'CANNOT_CONFIRM')
    def test_tamper_rejected(self):
        root,url=self.setup_api();path=self.record(root);record=json.loads(path.read_text());record['payload']['rows']=[];path.write_bytes(canonical_bytes(record))
        self.assertEqual(self.read(url+'/api/v3/preselection-pools?offset=0&limit=200&date=20261008')[0],409)
    def test_other_module_root_rejected(self):
        from v5_shadow.module_api import create_module_server
        root,url=self.setup_api()
        with self.assertRaisesRegex(ValueError,'MODULE_ROOT_IDENTITY'):
            create_module_server(dict(schema_version='v5.module_api.v1',module_id='manager',release_id='r1',data_root=str(root),routes=[]))
    def test_unconfigured_route_rejected(self):
        root,url=self.setup_api();self.assertEqual(self.read(url+'/api/v4/manager/research/workspace?date=20261008')[0],404)
    def test_duplicate_query_rejected(self):
        root,url=self.setup_api();self.assertEqual(self.read(url+'/api/v3/preselection-pools?date=20261008&date=20261007')[0],400)

    def test_fifo_record_rejected_without_waiting_for_writer(self):
        root,url=self.setup_api();path=self.record(root);path.unlink();os.mkfifo(path)
        self.assertEqual(self.read(url+'/api/v3/preselection-pools?offset=0&limit=200&date=20261008')[0],409)
    def test_symlink_response_directory_rejected(self):
        root,url=self.setup_api();self.record(root);source=root/'responses';moved=root/'saved';source.rename(moved);source.symlink_to(moved,target_is_directory=True)
        self.assertEqual(self.read(url+'/api/v3/preselection-pools?offset=0&limit=200&date=20261008')[0],409)
    def test_root_replacement_does_not_change_bound_directory(self):
        root,url=self.setup_api();self.record(root);moved=root.with_name(root.name+'-original');root.rename(moved);root.mkdir()
        self.addCleanup(lambda:__import__('shutil').rmtree(moved,ignore_errors=True))
        self.assertEqual(self.read(url+'/api/v3/preselection-pools?offset=0&limit=200&date=20261008')[0],200)
    def test_release_header_injection_rejected(self):
        from v5_shadow.module_api import create_module_server
        root,url=self.setup_api()
        for value in ('r1\r\nX-Bad:yes','中文','x'*129):
            with self.assertRaisesRegex(ValueError,'MODULE_RELEASE_REQUIRED'):
                create_module_server(dict(schema_version='v5.module_api.v1',module_id='preselection',release_id=value,data_root=str(root),routes=[]))
    def test_unsupported_methods_have_json_error(self):
        from urllib.request import Request
        root,url=self.setup_api()
        for method in ('PUT','DELETE','OPTIONS'):
            with self.assertRaises(HTTPError) as caught:urlopen(Request(url+'/api/v3/preselection-pools',method=method),timeout=3)
            error=caught.exception
            with error:
                self.assertEqual(error.code,405);self.assertEqual(json.load(error)['status'],'CANNOT_CONFIRM')

if __name__=='__main__':unittest.main()
