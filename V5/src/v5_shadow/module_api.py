"""One independent, read-only API process for one module's immutable responses."""
import argparse
import fcntl
import time
import hashlib
import json
import os
import re
import socket
import stat
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from .composition import no_symlinks
from .contracts import exact_keys,aware,sha
from .digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from .api_gateway import _parse_response


def response_key(module_id,path,query):
    return sha256_json(dict(module_id=module_id,path=path,query=query))


def _open_directory(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('MODULE_ROOT_PATH')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        return fd
    except Exception:
        os.close(fd);raise


def _read_regular(fd,limit):
    before=os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise ValueError('MODULE_RECORD_SIZE_OR_TYPE')
    chunks=[];size=0
    while block:=os.read(fd,min(65536,limit+1-size)):
        chunks.append(block);size+=len(block)
        if size>limit:raise ValueError('MODULE_RECORD_SIZE')
    after=os.fstat(fd)
    if tuple(getattr(before,k) for k in ('st_ino','st_dev','st_size','st_mtime_ns','st_ctime_ns'))!=tuple(getattr(after,k) for k in ('st_ino','st_dev','st_size','st_mtime_ns','st_ctime_ns')) or size!=before.st_size:raise ValueError('MODULE_RECORD_CHANGED')
    return b''.join(chunks)


def _config(value):
    exact_keys(value,('schema_version','module_id','release_id','data_root','routes'))
    if value['schema_version']!='v5.module_api.v1' or not isinstance(value['module_id'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',value['module_id']):raise ValueError('MODULE_CONFIG_INVALID')
    if not isinstance(value['release_id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value['release_id']):raise ValueError('MODULE_RELEASE_REQUIRED')
    if not isinstance(value['routes'],list) or len(value['routes'])>100 or any(not isinstance(v,str) for v in value['routes']) or len(set(value['routes']))!=len(value['routes']):raise ValueError('MODULE_ROUTES_INVALID')
    if any(not isinstance(p,str) or not re.fullmatch(r'/api/[A-Za-z0-9_/-]+',p) for p in value['routes']):raise ValueError('MODULE_ROUTES_INVALID')
    root_fd=_open_directory(value['data_root'])
    try:
        marker_fd=os.open('.v5-module-root',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root_fd)
        try:marker=_read_regular(marker_fd,256)
        finally:os.close(marker_fd)
        if marker!=('v5.module-root.v1:'+value['module_id']+'\n').encode():raise ValueError('MODULE_ROOT_IDENTITY')
        canonical_bytes(value)
        return json.loads(canonical_bytes(value)),root_fd
    except Exception:
        os.close(root_fd);raise


def _read_at(root_fd,directory,name):
    parent=root_fd if directory is None else os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd)
    try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    finally:
        if directory is not None:os.close(parent)
    try:return _read_regular(fd,MAX_JSON_BYTES)
    finally:os.close(fd)


def _generation_head(root_fd,config,*,publication_locked=False):
    try:data=_read_at(root_fd,None,'active.json')
    except FileNotFoundError:
        try:mode=_read_at(root_fd,None,'.v5-generation-mode')
        except FileNotFoundError:return None
        expected=canonical_bytes(dict(schema_version='v5.generation_mode.v1',module_id=config['module_id'],release_id=config['release_id']))
        if mode!=expected:raise ValueError('MODULE_GENERATION_MODE_IDENTITY')
        lock=None
        try:
            if not publication_locked:
                lock=os.open('.publication.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root_fd)
                if not stat.S_ISREG(os.fstat(lock).st_mode):raise ValueError('MODULE_PUBLICATION_LOCK')
                deadline=time.monotonic()+1
                while True:
                    try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB);break
                    except BlockingIOError:
                        if time.monotonic()>=deadline:raise ValueError('MODULE_PUBLICATION_BUSY')
                        time.sleep(0.005)
            # Re-read while protected: the first publisher may have installed
            # the pointer after our initial ENOENT but before the mode read.
            data=_read_at(root_fd,None,'active.json')
        except FileNotFoundError as error:raise ValueError('MODULE_ACTIVE_MISSING') from error
        finally:
            if lock is not None:os.close(lock)
    value=_parse_response(data)
    exact_keys(value,('schema_version','module_id','release_id','generation_sha256'))
    if (value['schema_version']!='v5.module_active.v1' or value['module_id']!=config['module_id']
            or value['release_id']!=config['release_id']):raise ValueError('MODULE_ACTIVE_IDENTITY')
    return sha(value['generation_sha256'])


def _load_generation(root_fd,config,generation):
    sha(generation)
    try:data=_read_at(root_fd,'generations',generation+'.json')
    except FileNotFoundError as error:raise ValueError('MODULE_GENERATION_MISSING') from error
    if hashlib.sha256(data).hexdigest()!=generation:raise ValueError('MODULE_GENERATION_DIGEST')
    value=_parse_response(data)
    exact_keys(value,('schema_version','module_id','release_id','records'))
    if (value['schema_version']!='v5.module_generation.v1' or value['module_id']!=config['module_id']
            or value['release_id']!=config['release_id']):raise ValueError('MODULE_GENERATION_IDENTITY')
    refs=value['records']
    if not isinstance(refs,dict) or not 1<=len(refs)<=10000:raise ValueError('MODULE_GENERATION_RECORDS')
    for key,digest in refs.items():sha(key);sha(digest)
    return value


def _read_object(root_fd,digest):
    sha(digest)
    try:data=_read_at(root_fd,'objects',digest+'.json')
    except FileNotFoundError as error:raise ValueError('MODULE_OBJECT_MISSING') from error
    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('MODULE_OBJECT_DIGEST')
    return _parse_response(data),data


def _read_record(root_fd,key,config):
    generation=_generation_head(root_fd,config)
    if generation is None:
        data=_read_at(root_fd,'responses',key+'.json')
        return _parse_response(data),hashlib.sha256(data).hexdigest()
    refs=_load_generation(root_fd,config,generation)['records']
    if key not in refs:raise FileNotFoundError('MODULE_RESULT_NOT_AVAILABLE')
    record,data=_read_object(root_fd,refs[key])
    return record,hashlib.sha256(data).hexdigest()


def _validate_record(config,record,path,query):
    exact_keys(record,('schema_version','module_id','release_id','path','query','payload','payload_sha256','source_input_sha256','data_kind','generated_at','status_code'))
    if (record['schema_version']!='v5.module_response.v1' or record['module_id']!=config['module_id']
        or record['release_id']!=config['release_id'] or record['path']!=path or record['query']!=query):raise ValueError('MODULE_RECORD_IDENTITY')
    if path not in config['routes']:raise ValueError('MODULE_ROUTE_NOT_CONFIGURED')
    if (not isinstance(query,dict) or len(query)>128 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in query.items())):raise ValueError('MODULE_QUERY_INVALID')
    if record['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY','OWNER_RESULT'):raise ValueError('MODULE_DATA_KIND')
    if type(record['status_code']) is not int or record['status_code'] not in (200,400,404,409,422,429,499,500,502,503,504):raise ValueError('MODULE_HTTP_STATUS')
    aware(record['generated_at']);sha(record['source_input_sha256']);sha(record['payload_sha256'])
    if not isinstance(record['payload'],dict) or sha256_json(record['payload'])!=record['payload_sha256']:raise ValueError('MODULE_PAYLOAD_DIGEST')
    return record


def read_response(config,root,path,query):
    record,digest=_read_record(root,response_key(config['module_id'],path,query),config)
    return _validate_record(config,record,path,query),digest


def create_module_server(value,host='127.0.0.1',port=0):
    if host!='127.0.0.1':raise ValueError('LOOPBACK_ONLY')
    config,root=_config(value)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)
            def expire():
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.timer=threading.Timer(5,expire);self.timer.daemon=True;self.timer.start()
        def finish(self):
            self.timer.cancel();super().finish()
        def log_message(self,*args):pass
        def reply(self,status,payload,digest=None):
            data=canonical_bytes(payload);self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-V5-Module',config['module_id']);self.send_header('X-V5-Release',config['release_id'])
            if digest:self.send_header('X-V5-Record-SHA256',digest)
            self.end_headers()
            try:
                if getattr(self,'command',None)!='HEAD':self.wfile.write(data)
            except OSError:pass
        def error(self,status,reason):self.reply(status,dict(status='CANNOT_CONFIRM',reason_codes=[reason],module_id=config['module_id']))
        def do_POST(self):self.error(405,'MODULE_READ_ONLY')
        do_PUT=do_POST
        do_DELETE=do_POST
        do_OPTIONS=do_POST
        do_PATCH=do_POST
        do_TRACE=do_POST
        do_HEAD=do_POST
        def send_error(self,code,message=None,explain=None):
            self.error(405 if code==501 else code,'MODULE_READ_ONLY' if code==501 else 'MODULE_REQUEST_INVALID')
        def do_GET(self):
            hosts=('127.0.0.1:'+str(self.server.server_address[1]),'localhost:'+str(self.server.server_address[1]))
            if len(self.headers.get_all('Host',[]))!=1 or len(self.headers.get_all('Origin',[]))>1:return self.error(400,'MODULE_HEADERS_INVALID')
            if self.headers.get('Host') not in hosts:return self.error(403,'HOST_REJECTED')
            if self.headers.get('Origin') and self.headers['Origin'] not in ['http://'+h for h in hosts]:return self.error(403,'ORIGIN_REJECTED')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length','0')!='0' or len(self.path)>8192:return self.error(400,'MODULE_REQUEST_INVALID')
            try:
                parsed=urlsplit(self.path)
                if parsed.scheme or parsed.netloc:raise ValueError('MODULE_REQUEST_INVALID')
                multi=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=128)
                if any(len(v)!=1 for v in multi.values()):raise ValueError('MODULE_QUERY_INVALID')
                query={k:v[0] for k,v in multi.items()};self.timer.cancel()
            except ValueError:return self.error(400,'MODULE_QUERY_INVALID')
            if parsed.path=='/__v5/module-health':
                return self.reply(200,dict(status='READ_ONLY_RESPONSE_SERVICE',module_id=config['module_id'],release_id=config['release_id'],pid=os.getpid(),
                    implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),config_sha256=sha256_json(config),source_provenance_verified=False))
            if parsed.path not in config['routes']:return self.error(404,'MODULE_ROUTE_NOT_CONFIGURED')
            try:
                record,digest=read_response(config,root,parsed.path,query);self.reply(record['status_code'],record['payload'],digest)
            except FileNotFoundError:self.error(503,'MODULE_RESULT_NOT_AVAILABLE')
            except ValueError as error:
                self.error(503,'MODULE_BUSY') if str(error)=='MODULE_PUBLICATION_BUSY' else self.error(409,'MODULE_RESULT_INVALID')
            except (TypeError,KeyError,OSError,RecursionError):self.error(409,'MODULE_RESULT_INVALID')
    class Server(ThreadingHTTPServer):
        daemon_threads=False
        block_on_close=True
        slots=threading.BoundedSemaphore(8)
        def process_request(self,request,address):
            if not self.slots.acquire(blocking=False):
                try:
                    body=b'{"status":"CANNOT_CONFIRM","reason_codes":["MODULE_BUSY"]}'
                    request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                except OSError:pass
                self.shutdown_request(request);return
            try:super().process_request(request,address)
            except Exception:
                self.slots.release();raise
        def process_request_thread(self,request,address):
            try:super().process_request_thread(request,address)
            finally:self.slots.release()
        def server_close(self):
            try:super().server_close()
            finally:
                if getattr(self,'root_fd',None) is not None:
                    os.close(self.root_fd);self.root_fd=None
    try:server=Server((host,port),Handler)
    except Exception:
        os.close(root);raise
    server.root_fd=root
    return server


def main(argv=None):
    parser=argparse.ArgumentParser(description='One V5 module, one read-only API process')
    parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args(argv)
    with open(args.config,encoding='utf-8') as stream:config=json.load(stream)
    server=create_module_server(config,port=args.port)
    print('http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':main()
