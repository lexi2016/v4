"""Mac-only boundary candidates: exact manager response budget, immutable publication."""
import json
import threading
import unittest
from urllib.request import urlopen
from v5_shadow.api_gateway import (_parse_response, _precheck_json, _manager_response,
    MANAGER_WORKSPACE_PATH, MAX_RESPONSE, create_gateway)
from v5_shadow.module_api import _parse_record, create_module_server
from v5_shadow.digests import canonical_bytes, sha256_json
from test_module_artifacts import ModuleArtifactTests


class ManagerResponseBudgetTests(unittest.TestCase):
    def setUp(self):
        fixture=ModuleArtifactTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture

    def record(self):
        record=self.fixture.record()
        record['data_kind']='OWNER_RESULT'
        record['payload']['materials']=[{'source_row':{}} for _ in range(84000)]
        record['payload_sha256']=sha256_json(record['payload'])
        return record

    def test_default_200000_exact_boundary(self):
        _parse_response(b'['+b'0,'*199998+b'0]')
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _parse_response(b'['+b'0,'*199999+b'0]')

    def test_manager_300000_exact_boundary(self):
        _precheck_json(b'['+b'0,'*299998+b'0]',manager_workspace=True)
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _precheck_json(b'['+b'0,'*299999+b'0]',manager_workspace=True)

    def test_manager_parsed_node_limit_stays_200000(self):
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _parse_response(b'['+b'0,'*199999+b'0]',manager_workspace=True)

    def test_field_names_still_count_toward_manager_lexical_limit(self):
        # One parsed value per key, but lexical budget counts both key and value.
        raw=canonical_bytes({str(i):None for i in range(150000)})
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _parse_response(raw,manager_workspace=True)

    def test_depth_and_byte_limits_unchanged(self):
        for manager in (False,True):
            with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
                _parse_response(b'['*65+b'0'+b']'*65,manager_workspace=manager)
            with self.assertRaisesRegex(ValueError,'TOO_LARGE'):
                _parse_response(b' '*(MAX_RESPONSE+1),manager_workspace=manager)
            with self.assertRaisesRegex(ValueError,'NONFINITE'):
                _parse_response(b'{"value":NaN}',manager_workspace=manager)

    def test_only_exact_manager_get_success_route(self):
        self.assertTrue(_manager_response('manager',MANAGER_WORKSPACE_PATH))
        for args in [('other',MANAGER_WORKSPACE_PATH),('manager',MANAGER_WORKSPACE_PATH+'/'),
                     ('manager',MANAGER_WORKSPACE_PATH,'POST'),('manager',MANAGER_WORKSPACE_PATH,'GET',500)]:
            self.assertFalse(_manager_response(*args))

    def test_no_record_metadata_escape_for_other_module_or_route(self):
        record=self.record();raw=canonical_bytes(record)
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _parse_record(raw,dict(self.fixture.config,module_id='other'))
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            _parse_record(raw,dict(self.fixture.config,routes=['/api/other']))
        for key,value in [('path','/api/other'),('module_id','other'),('data_kind','SYNTHETIC'),('status_code',500)]:
            changed=dict(record,**{key:value})
            with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
                _parse_record(canonical_bytes(changed),self.fixture.config)

    def test_large_publish_readback_next_generation_and_gateway_preserve_payload(self):
        record=self.record()
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):_precheck_json(canonical_bytes(record))
        first=self.fixture.publish([record])
        self.fixture.publish([self.fixture.record('20261009')],first)
        server=create_module_server(self.fixture.config)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        gateway=create_gateway(dict(schema_version='v5.api_gateway.v1',
            modules={'manager':dict(port=server.server_address[1],timeout_seconds=30,max_inflight=1,release_id='r1')},
            routes=[dict(path=MANAGER_WORKSPACE_PATH,module_id='manager',methods=['GET'])]))
        threading.Thread(target=gateway.serve_forever,daemon=True).start()
        self.addCleanup(gateway.server_close);self.addCleanup(gateway.shutdown)
        for port in (server.server_address[1],gateway.server_address[1]):
            with urlopen('http://127.0.0.1:'+str(port)+MANAGER_WORKSPACE_PATH+'?date=20261008',timeout=30) as response:
                self.assertEqual(json.load(response),record['payload'])

    def test_over_budget_publication_preserves_active_generation(self):
        first=self.fixture.publish([self.fixture.record()])
        before=(self.fixture.root/'active.json').read_bytes()
        record=self.record();record['payload']['materials']=[0]*300000
        record['payload_sha256']=sha256_json(record['payload'])
        with self.assertRaisesRegex(ValueError,'COMPLEXITY_LIMIT'):
            self.fixture.publish([record],first)
        self.assertEqual((self.fixture.root/'active.json').read_bytes(),before)
