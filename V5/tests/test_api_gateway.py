import json
import tempfile
import hashlib
from pathlib import Path
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError

class GatewayTests(unittest.TestCase):
    def upstream(self,delay=0,body=None,entered=None,paths=None):
        payload=json.dumps(body or {'status':'READY','rows':[1]}).encode()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if paths is not None:paths.append(self.path)
                if entered is not None:entered.set()
                time.sleep(delay)
                try:
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server.server_address[1]
    def gateway(self,slow=0,entered=None,paths=None):
        from v5_shadow.api_gateway import create_gateway
        a=self.upstream(slow,entered=entered,paths=paths);b=self.upstream(body={'status':'READY','module':'b'})
        cfg=dict(schema_version='v5.api_gateway.v1',modules={
            'a':dict(port=a,timeout_seconds=0.2,max_inflight=1,release_id='a1'),
            'b':dict(port=b,timeout_seconds=1,max_inflight=1,release_id='b1')},
            routes=[dict(path='/api/v3/preselection-pools',module_id='a',methods=['GET']),
                    dict(path='/api/v3/review',module_id='b',methods=['GET'])])
        server=create_gateway(cfg,port=0);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_address[1])
    def read(self,url):
        try:
            with urlopen(url,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as error:
            with error:return error.code,json.load(error)
    def test_original_url_and_payload_preserved(self):
        paths=[];status,body=self.read(self.gateway(paths=paths)+'/api/v3/preselection-pools?date=20261008&limit=200&offset=0')
        self.assertEqual(paths,['/api/v3/preselection-pools?date=20261008&limit=200&offset=0'])
        self.assertEqual(status,200);self.assertEqual(body,{'status':'READY','rows':[1]})
    def test_one_module_timeout_does_not_block_other(self):
        entered=threading.Event();root=self.gateway(slow=0.5,entered=entered);answers=[]
        t=threading.Thread(target=lambda:answers.append(self.read(root+'/api/v3/preselection-pools')));t.start();self.assertTrue(entered.wait(2))
        self.assertEqual(self.read(root+'/api/v3/preselection-pools')[0],429)
        start=time.monotonic();status,body=self.read(root+'/api/v3/review');elapsed=time.monotonic()-start;t.join()
        self.assertEqual(status,200);self.assertEqual(body['module'],'b');self.assertLess(elapsed,0.4)
        self.assertEqual(answers[0][0],504);self.assertEqual(answers[0][1]['status'],'CANNOT_CONFIRM')
        self.assertEqual(self.read(root+'/api/v3/preselection-pools')[0],504)
    def test_unknown_route_does_not_fall_back_to_v4(self):
        self.assertEqual(self.read(self.gateway()+'/api/private/anything')[0],404)
    def test_upstream_host_cannot_be_external(self):
        from v5_shadow.api_gateway import create_gateway
        cfg=dict(schema_version='v5.api_gateway.v1',modules={'a':dict(port=1234,host='example.com',timeout_seconds=1,max_inflight=1,release_id='a')},routes=[])
        with self.assertRaises(ValueError):create_gateway(cfg,port=0)
    def test_readonly_default_rejects_post(self):
        from urllib.request import Request
        request=Request(self.gateway()+'/api/v3/review',data=b'{}',method='POST')
        with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=3)
        error=caught.exception
        try:self.assertEqual(error.code,405)
        finally:error.close()
    def test_loopback_only(self):
        from v5_shadow.api_gateway import create_gateway
        with self.assertRaisesRegex(ValueError,'LOOPBACK_ONLY'):create_gateway({},host='0.0.0.0')

    def raw_gateway(self,handler):
        from v5_shadow.api_gateway import create_gateway
        upstream=ThreadingHTTPServer(('127.0.0.1',0),handler);upstream.daemon_threads=True
        threading.Thread(target=upstream.serve_forever,daemon=True).start();self.addCleanup(upstream.server_close);self.addCleanup(upstream.shutdown)
        cfg=dict(schema_version='v5.api_gateway.v1',modules={'a':dict(port=upstream.server_address[1],timeout_seconds=0.2,max_inflight=1,release_id='r')},routes=[dict(path='/api/test',module_id='a',methods=['GET','POST'])])
        gateway=create_gateway(cfg);threading.Thread(target=gateway.serve_forever,daemon=True).start();self.addCleanup(gateway.server_close);self.addCleanup(gateway.shutdown)
        return 'http://127.0.0.1:'+str(gateway.server_address[1])+'/api/test'
    def test_truncated_json_is_not_success(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length','100');self.end_headers();self.wfile.write(b'{}');self.close_connection=True
        status,body=self.read(self.raw_gateway(Handler));self.assertEqual(status,502);self.assertIn('MODULE_RESPONSE_TRUNCATED',body['reason_codes'])
    def test_dripping_headers_hit_total_deadline(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                try:
                    for byte in b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}':
                        self.connection.sendall(bytes([byte]));time.sleep(0.03)
                except OSError:pass
        status,body=self.read(self.raw_gateway(Handler));self.assertEqual(status,504);self.assertIn('MODULE_TIMEOUT',body['reason_codes'])
    def test_post_bytes_and_header_allowlist(self):
        from urllib.request import Request
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                seen.append((self.rfile.read(int(self.headers['Content-Length'])),self.headers.get('Cookie'),self.headers.get('Authorization')))
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
        req=Request(self.raw_gateway(Handler),data=b'{"x": 1}',method='POST',headers={'Content-Type':'application/json','Cookie':'test=1','Authorization':'test'})
        with urlopen(req,timeout=3) as response:self.assertEqual(response.status,200)
        self.assertEqual(seen,[(b'{"x": 1}',None,None)])
    def test_wrong_origin_rejected(self):
        from urllib.request import Request
        request=Request(self.gateway()+'/api/v3/review',headers={'Origin':'https://example.com'})
        with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=3)
        error=caught.exception
        try:self.assertEqual(error.code,403)
        finally:error.close()

    def test_json_preallocation_limit(self):
        from v5_shadow.api_gateway import _precheck_json
        with self.assertRaisesRegex(ValueError,'MODULE_JSON_COMPLEXITY_LIMIT'):_precheck_json(b'['+b'0,'*200000+b'0]')
        with self.assertRaisesRegex(ValueError,'MODULE_JSON_COMPLEXITY_LIMIT'):_precheck_json(b'['*65+b'0'+b']'*65)
        _precheck_json(b'{"quoted": "[{}]", "escaped": "a\\\"b"}')

    def test_non_utf8_and_overflow_rejected(self):
        from v5_shadow.api_gateway import _parse_response
        with self.assertRaises(ValueError):_parse_response('{"x":1}'.encode('utf-16le'))
        with self.assertRaisesRegex(ValueError,'MODULE_JSON_NONFINITE'):_parse_response(b'{"x":1e999}')

    def test_original_frontend_bytes_served_without_api_fallback(self):
        from v5_shadow.api_gateway import create_gateway,load_frontend
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();data=b'<html>original frontend fixture</html>';(root/'index.html').write_bytes(data)
            frontend=load_frontend(root,{'index.html':hashlib.sha256(data).hexdigest()})
            server=create_gateway(dict(schema_version='v5.api_gateway.v1',modules={},routes=[]),frontend=frontend)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                url='http://127.0.0.1:'+str(server.server_address[1])
                with urlopen(url+'/',timeout=3) as response:self.assertEqual(response.read(),data)
                self.assertEqual(self.read(url+'/api/v3/preselection-pools?date=20261008')[0],404)
            finally:server.shutdown();server.server_close()
    def test_frontend_wrong_hash_rejected(self):
        from v5_shadow.api_gateway import load_frontend
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'index.html').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError,'FRONTEND_BYTES_MISMATCH'):load_frontend(root,{'index.html':'a'*64})

if __name__=='__main__':unittest.main()
