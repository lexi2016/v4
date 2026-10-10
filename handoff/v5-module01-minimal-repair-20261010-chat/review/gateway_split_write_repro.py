"""Final-review capability repro; synthetic loopback owner, no production write.

Execute from work/V5 using the project's original .venv/bin/python. The only
POST is against an ephemeral in-memory HTTP fixture which returns JSON.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from v5_shadow.api_gateway import MANAGER_WORKSPACE_PATH, create_gateway


class WritableOwner(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self):
        raw = b'{"label":"SYNTHETIC_CAPABILITY_REVIEW","production_allowed":false}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.reply()

    def do_POST(self):
        self.reply()


owner = ThreadingHTTPServer(('127.0.0.1', 0), WritableOwner)
gateway = create_gateway(dict(
    schema_version='v5.api_gateway.v1',
    modules={'manager': dict(port=owner.server_port, timeout_seconds=3,
                            max_inflight=2, release_id='synthetic-final-review')},
    routes=[dict(path=MANAGER_WORKSPACE_PATH, module_id='manager', methods=['GET']),
            dict(path=MANAGER_WORKSPACE_PATH + '/refresh', module_id='manager', methods=['POST'])],
))
for server in (owner, gateway):
    threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    results = []
    for suffix, method in (('', 'GET'), ('/refresh', 'POST')):
        request = Request(
            f'http://127.0.0.1:{gateway.server_port}{MANAGER_WORKSPACE_PATH}{suffix}?date=20261009',
            method=method,
        )
        with urlopen(request, timeout=5) as response:
            results.append(dict(method=method, path=MANAGER_WORKSPACE_PATH + suffix,
                                status=response.status,
                                workspace_access=response.headers.get('X-V5-Workspace-Access')))
            response.read()
    print(json.dumps(results, indent=2))
finally:
    for server in (gateway, owner):
        server.shutdown()
        server.server_close()
