"""Loopback route dispatcher; business modules own separate API processes."""
import argparse
import http.client
import json
import math
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from .contracts import exact_keys
from .digests import canonical_bytes,sha256_json

MAX_BODY=1024*1024
MAX_RESPONSE=16*1024*1024


def _precheck_json(data):
    depth=nodes=0;quoted=False;escaped=False;scalar=False
    for byte in data:
        if quoted:
            if escaped:escaped=False
            elif byte==92:escaped=True
            elif byte==34:quoted=False
            continue
        if byte==34:
            quoted=True;nodes+=1;scalar=False
        elif byte in (123,91):
            depth+=1;nodes+=1;scalar=False
        elif byte in (125,93):
            depth-=1;scalar=False
            if depth<0:raise ValueError('MODULE_JSON_INVALID')
        elif byte in (32,9,10,13,44,58):scalar=False
        elif not scalar:
            nodes+=1;scalar=True
        if depth>64 or nodes>200000:raise ValueError('MODULE_JSON_COMPLEXITY_LIMIT')


def _bounded_json(value):
    stack=[(iter((value,)),0)];nodes=0
    while stack:
        iterator,depth=stack[-1]
        try:item=next(iterator)
        except StopIteration:
            stack.pop();continue
        nodes+=1
        if isinstance(item,float) and not math.isfinite(item):raise ValueError('MODULE_JSON_NONFINITE')
        if depth>64 or nodes>200000:raise ValueError('MODULE_JSON_COMPLEXITY_LIMIT')
        if isinstance(item,dict):stack.append((iter(item.values()),depth+1))
        elif isinstance(item,list):stack.append((iter(item),depth+1))


def _invalid_constant(value):
    raise ValueError('MODULE_JSON_NONFINITE')


def _parse_response(data):
    text=data.decode('utf-8')
    _precheck_json(data)
    value=json.loads(text,parse_constant=_invalid_constant)
    _bounded_json(value)
    return value


def validate_config(value):
    exact_keys(value,('schema_version','modules','routes'))
    if value['schema_version']!='v5.api_gateway.v1' or not isinstance(value['modules'],dict) or not isinstance(value['routes'],list):raise ValueError('GATEWAY_CONFIG_INVALID')
    if len(value['modules'])>32 or len(value['routes'])>256:raise ValueError('GATEWAY_CONFIG_LIMIT')
    ports=set()
    for name,module in value['modules'].items():
        if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',name):raise ValueError('GATEWAY_MODULE_INVALID')
        exact_keys(module,('port','timeout_seconds','max_inflight','release_id'))
        if type(module['port']) is not int or not 1<=module['port']<=65535 or module['port'] in ports:raise ValueError('GATEWAY_MODULE_PORT_INVALID')
        ports.add(module['port'])
        if type(module['timeout_seconds']) not in (int,float) or not 0.05<=module['timeout_seconds']<=30:raise ValueError('GATEWAY_TIMEOUT_INVALID')
        if type(module['max_inflight']) is not int or not 1<=module['max_inflight']<=16:raise ValueError('GATEWAY_CAPACITY_INVALID')
        if not isinstance(module['release_id'],str) or not module['release_id']:raise ValueError('GATEWAY_RELEASE_REQUIRED')
    seen=set()
    for route in value['routes']:
        exact_keys(route,('path','module_id','methods'))
        path=route['path'];methods=route['methods']
        if not isinstance(path,str) or not re.fullmatch(r'/api/[A-Za-z0-9_/-]+',path) or '//' in path or path in seen:raise ValueError('GATEWAY_ROUTE_INVALID')
        if route['module_id'] not in value['modules']:raise ValueError('GATEWAY_MODULE_MISSING')
        if not isinstance(methods,list) or not methods or len(set(methods))!=len(methods) or set(methods)-{'GET','POST'}:raise ValueError('GATEWAY_METHODS_INVALID')
        seen.add(path)
    canonical_bytes(value)
    return json.loads(canonical_bytes(value))


def create_gateway(config,host='127.0.0.1',port=0):
    if host!='127.0.0.1':raise ValueError('LOOPBACK_ONLY')
    config=validate_config(config);routes={r['path']:r for r in config['routes']}
    capacities={k:threading.BoundedSemaphore(v['max_inflight']) for k,v in config['modules'].items()}
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)
            def expire_input():
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.input_watchdog=threading.Timer(5,expire_input)
            self.input_watchdog.daemon=True;self.input_watchdog.start()
        def finish(self):
            self.input_watchdog.cancel()
            super().finish()
        def log_message(self,*args):pass
        def reply(self,status,payload,raw=False):
            data=payload if raw else canonical_bytes(payload)
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
        def error(self,status,reason,module=None):
            self.reply(status,dict(status='CANNOT_CONFIRM',reason_codes=[reason],module_id=module,
                production_allowed=False,buy_gate_updated=False,orders_sent=False))
        def do_GET(self):self.dispatch()
        def do_POST(self):self.dispatch()
        def dispatch(self):
            hosts=('127.0.0.1:'+str(self.server.server_address[1]),'localhost:'+str(self.server.server_address[1]))
            if self.headers.get('Host') not in hosts:return self.error(403,'HOST_REJECTED')
            if self.headers.get('Origin') and self.headers['Origin'] not in ['http://'+h for h in hosts]:return self.error(403,'ORIGIN_REJECTED')
            if self.headers.get('Transfer-Encoding') or len(self.path)>8192:return self.error(400,'REQUEST_INVALID')
            try:parsed=urlsplit(self.path)
            except ValueError:return self.error(400,'REQUEST_INVALID')
            if parsed.scheme or parsed.netloc:return self.error(400,'REQUEST_INVALID')
            try:parse_qs(parsed.query,max_num_fields=128)
            except ValueError:return self.error(400,'QUERY_LIMIT')
            if parsed.path=='/__v5/health' and self.command=='GET':
                return self.reply(200,dict(status='GATEWAY_ONLY',config_sha256=sha256_json(config),
                    modules={k:dict(release_id=v['release_id'],upstream_health='NOT_PROBED') for k,v in config['modules'].items()}))
            route=routes.get(parsed.path)
            if route is None:return self.error(404,'ROUTE_NOT_CONFIGURED')
            name=route['module_id']
            if self.command not in route['methods']:return self.error(405,'METHOD_NOT_ALLOWED',name)
            if not capacities[name].acquire(blocking=False):return self.error(429,'MODULE_BUSY',name)
            body_ready=False
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=MAX_BODY:return self.error(413,'BODY_TOO_LARGE',name)
                if self.command=='GET' and length:return self.error(400,'GET_BODY_REJECTED',name)
                if length and self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':return self.error(415,'BODY_TYPE_UNSUPPORTED',name)
                body=self.rfile.read(length) if length else None
                if body is not None and len(body)!=length:return self.error(400,'BODY_INCOMPLETE',name)
                self.input_watchdog.cancel();body_ready=True
            except (ValueError,OSError):return self.error(400,'BODY_INVALID',name)
            finally:
                if not body_ready:capacities[name].release()
            module=config['modules'][name];connection=None;response=None;watchdog=None;expired=threading.Event()
            try:
                deadline=time.monotonic()+module['timeout_seconds']
                connection=http.client.HTTPConnection('127.0.0.1',module['port'],timeout=module['timeout_seconds'])
                connection.connect()
                transport=connection.sock
                def expire():
                    expired.set()
                    try:transport.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                watchdog=threading.Timer(max(0,deadline-time.monotonic()),expire)
                watchdog.daemon=True;watchdog.start()
                # No cookies, credentials, caller Host or hop-by-hop headers cross the boundary.
                headers={'Accept':'application/json'}
                if body is not None:headers['Content-Type']='application/json'
                connection.request(self.command,self.path,body=body,headers=headers)
                response=connection.getresponse()
                if 300<=response.status<400:return self.error(502,'MODULE_REDIRECT_REJECTED',name)
                if response.getheader('Content-Type','').split(';')[0].strip()!='application/json':return self.error(502,'MODULE_RESPONSE_TYPE_INVALID',name)
                declared=response.getheader('Content-Length')
                if declared is not None:
                    try:declared=int(declared)
                    except ValueError:return self.error(502,'MODULE_LENGTH_INVALID',name)
                    if not 0<=declared<=MAX_RESPONSE:return self.error(502,'MODULE_RESPONSE_TOO_LARGE',name)
                chunks=[];size=0
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError()
                    if connection.sock:connection.sock.settimeout(remaining)
                    chunk=response.read1(min(65536,MAX_RESPONSE+1-size))
                    if not chunk:break
                    size+=len(chunk)
                    if size>MAX_RESPONSE:return self.error(502,'MODULE_RESPONSE_TOO_LARGE',name)
                    chunks.append(chunk)
                if expired.is_set() or time.monotonic()>deadline:raise TimeoutError()
                if declared is not None and size!=declared:return self.error(502,'MODULE_RESPONSE_TRUNCATED',name)
                data=b''.join(chunks)
                _parse_response(data)
                self.reply(response.status,data,raw=True)
            except (TimeoutError,socket.timeout):self.error(504,'MODULE_TIMEOUT',name)
            except (OSError,http.client.HTTPException):self.error(504 if expired.is_set() else 502,'MODULE_TIMEOUT' if expired.is_set() else 'MODULE_UNAVAILABLE',name)
            except (ValueError,UnicodeError,RecursionError):self.error(502,'MODULE_RESPONSE_INVALID',name)
            finally:
                if watchdog:watchdog.cancel()
                if response:response.close()
                if connection:connection.close()
                capacities[name].release()
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        slots=threading.BoundedSemaphore(64)
        def process_request(self,request,address):
            if not self.slots.acquire(blocking=False):
                try:
                    body=b'{"status":"CANNOT_CONFIRM","reason_codes":["GATEWAY_BUSY"]}'
                    request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                except OSError:pass
                self.shutdown_request(request);return
            try:super().process_request(request,address)
            except Exception:
                self.slots.release();raise
        def process_request_thread(self,request,address):
            try:super().process_request_thread(request,address)
            finally:self.slots.release()
    server=Server((host,port),Handler)
    return server


def main(argv=None):
    parser=argparse.ArgumentParser(description='V5 independent module API dispatcher')
    parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,default=8896)
    args=parser.parse_args(argv)
    with open(args.config,encoding='utf-8') as stream:config=json.load(stream)
    server=create_gateway(config,port=args.port)
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':main()
