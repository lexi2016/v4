"""Real module/store/gateway HTTP capability; all records are synthetic."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from v5_shadow.api_gateway import MANAGER_WORKSPACE_PATH, create_gateway
from v5_shadow.digests import sha256_json
from v5_shadow.module_api import create_module_server
from v5_shadow.module_artifacts import publish_generation


class Module01ReadOnlyHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / '.v5-module-root').write_text('v5.module-root.v1:manager\n')
        self.query = {'date': '20261009', 'view': 'auto'}
        self.payload = {'label': 'SYNTHETIC_HTTP_CAPABILITY_RECORD',
                        'RESEARCH_ONLY': True, 'production_allowed': False,
                        'buy_gate_updated': False, 'orders_sent': False}
        self.config = dict(schema_version='v5.module_api.v1', module_id='manager',
                           release_id='module01-synthetic', data_root=str(root),
                           routes=[MANAGER_WORKSPACE_PATH])
        record = dict(schema_version='v5.module_response.v1', module_id='manager',
                      release_id=self.config['release_id'], path=MANAGER_WORKSPACE_PATH,
                      query=self.query, payload=self.payload,
                      payload_sha256=sha256_json(self.payload), source_input_sha256='a' * 64,
                      data_kind='SYNTHETIC', generated_at='2026-10-09T10:00:00+08:00',
                      status_code=200)
        publish_generation(self.config, [record], expected_generation=None)
        self.module = self.serve(create_module_server(self.config))

    def serve(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def gateway(self, methods=('GET',)):
        config = dict(schema_version='v5.api_gateway.v1',
                      modules={'manager': dict(port=self.module.server_port,
                          timeout_seconds=3, max_inflight=2, release_id=self.config['release_id'])},
                      routes=[dict(path=MANAGER_WORKSPACE_PATH, module_id='manager', methods=list(methods))])
        return self.serve(create_gateway(config))

    def request(self, server, *, method='GET', query='date=20261009&view=auto'):
        url = 'http://127.0.0.1:' + str(server.server_port) + MANAGER_WORKSPACE_PATH + '?' + query
        request = Request(url, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), json.load(response)

    def test_direct_module_reports_read_only_without_changing_saved_payload(self):
        status, headers, payload = self.request(self.module)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('X-V5-Workspace-Access'), 'READ_ONLY')
        self.assertEqual(payload, self.payload)

    def test_get_only_manager_gateway_reports_read_only(self):
        status, headers, payload = self.request(self.gateway())
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('X-V5-Workspace-Access'), 'READ_ONLY')
        self.assertEqual(payload, self.payload)

    def test_generic_post_capable_route_does_not_claim_get_only_capability(self):
        status, headers, payload = self.request(self.gateway(('GET', 'POST')))
        self.assertEqual(status, 200)
        self.assertNotIn('X-V5-Workspace-Access', headers)
        self.assertEqual(payload, self.payload)

    def test_separate_refresh_post_route_does_not_mark_workspace_read_only(self):
        # The legacy API writes on /workspace/refresh, not the GET path itself.
        # Exercise a real writable upstream so a false capability is observable.
        payload = self.payload
        class LegacyOwner(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self):
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            do_GET = reply
            do_POST = reply
        owner = self.serve(ThreadingHTTPServer(('127.0.0.1', 0), LegacyOwner))
        gateway = self.serve(create_gateway(dict(schema_version='v5.api_gateway.v1',
            modules={'manager': dict(port=owner.server_port, timeout_seconds=3,
                max_inflight=2, release_id='module01-synthetic-legacy')},
            routes=[dict(path=MANAGER_WORKSPACE_PATH, module_id='manager', methods=['GET']),
                dict(path=MANAGER_WORKSPACE_PATH + '/refresh', module_id='manager', methods=['POST'])])))
        status, headers, body = self.request(gateway)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.payload)
        self.assertNotIn('X-V5-Workspace-Access', headers)
        request = Request('http://127.0.0.1:' + str(gateway.server_port)
                          + MANAGER_WORKSPACE_PATH + '/refresh', method='POST')
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), self.payload)

    def test_module_and_get_only_gateway_keep_post_disabled(self):
        for server in (self.module, self.gateway()):
            with self.subTest(port=server.server_port):
                status, _, payload = self.request(server, method='POST')
                self.assertEqual(status, 405)
                self.assertEqual(payload['status'], 'CANNOT_CONFIRM')

    def test_missing_saved_query_stays_unconfirmed(self):
        status, _, payload = self.request(self.gateway(), query='date=20261008&view=auto')
        self.assertEqual(status, 503)
        self.assertEqual(payload['status'], 'CANNOT_CONFIRM')


if __name__ == '__main__':
    unittest.main()
