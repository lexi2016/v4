"""One ephemeral loopback API process; close only the process started here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','evidence','index','data-root','sidecars','bridge'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();args.evidence.mkdir(parents=True,exist_ok=False)
    candidate=json.loads((args.candidate/'candidate_receipt.json').read_bytes());role=candidate['roles']['api'];app=Path(role['app_root'])
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(app/'upstreams'),'V4_APP_ROOT':str(app),'V4_RELEASE_ID':role['release_id'],
        'V4_RELEASE_MANIFEST_PATH':str(app.parent/'release-manifest.json'),'V4_RELEASE_MANIFEST_SHA256':role['manifest_sha256'],
        'V4_RESEARCH_DATA_ROOT':str(args.data_root),'V4_RUNTIME_GRAPH_INBOX':'','V4_REPORT_EVIDENCE_INDEX_ROOT':str(args.index),
        'V4_REPORT_EVIDENCE_LOCAL_BRIDGE':str(args.bridge),'V4_REPORT_EVIDENCE_SIDECAR_ROOT':str(args.sidecars),
        'V4_DATA_ROOT':str(args.evidence/'data'),'V4_MANAGER_RESEARCH_STATE_ROOT':str(args.evidence/'manager')}
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    code="from pathlib import Path;import uvicorn;from apps.api.v4_api.app import create_app;uvicorn.run(create_app(data_root=Path("+repr(str(args.evidence/'data'))+")),host='127.0.0.1',port="+str(port)+",log_level='warning')"
    result={'candidate':str(args.candidate),'release_id':role['release_id'],'manifest_sha256':role['manifest_sha256'],'port':port,'host':'127.0.0.1','status':'FAIL'}
    with (args.evidence/'http.log').open('ab') as log:
        child=subprocess.Popen([sys.executable,'-B','-c',code],cwd=app,env=env,stdout=log,stderr=log)
        result['pid']=child.pid
        try:
            with httpx.Client(trust_env=False,timeout=30) as client:
                base='http://127.0.0.1:'+str(port)
                for _ in range(60):
                    if child.poll() is not None:raise RuntimeError('ISOLATED_API_EXITED')
                    try:
                        if client.get(base+'/healthz').status_code==200:break
                    except httpx.ConnectError:pass
                    time.sleep(.25)
                else:raise RuntimeError('ISOLATED_API_NOT_READY')
                ready=client.get(base+'/readyz');assert ready.status_code==200 and ready.json()=={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
                identity=client.get(base+'/api/v1/runs/date-list').json()['runtime_identity']
                assert identity['release_id']==role['release_id'] and identity['manifest_sha256']==role['manifest_sha256'] and identity['status']=='MANIFEST_EXECUTION_FILES_VERIFIED',identity
                search=client.get(base+'/api/v4/research/evidence-search',params={'text':'2026-2028年EPS','security':'301216','market':'A'})
                assert search.status_code==200 and search.json()['vector_succeeded'] and search.json()['hits'],search.text
                result.update(status='PASS_ISOLATED_TCP_MANIFEST_AND_RETRIEVAL',runtime_identity=identity,search_mode=search.json()['search_mode'],
                    hits=len(search.json()['hits']),generation=search.json()['index_generation'],scope='frozen 3-PDF native index; isolated TCP only')
        finally:
            child.terminate();child.wait(timeout=20)
            result['own_http_process_closed']=child.poll() is not None
            with socket.socket() as sock:sock.settimeout(.2);result['own_port_closed']=sock.connect_ex(('127.0.0.1',port))!=0
            result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            (args.evidence/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
