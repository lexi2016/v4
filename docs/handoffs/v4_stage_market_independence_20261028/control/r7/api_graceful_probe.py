"""Actual installed uvicorn + exact API assemble_api lifespan; temp loopback only."""
from pathlib import Path
import asyncio,concurrent.futures,hashlib,json,os,signal,socket,subprocess,sys,tempfile,threading,time,urllib.request
HERE=Path(__file__).resolve().parent
if len(sys.argv)>1 and sys.argv[1]=='child':
 root=Path(sys.argv[2]);port=int(sys.argv[3]);api=sys.argv[4];sys.path.insert(0,api)
 import uvicorn
 from fastapi import FastAPI,APIRouter
 from v4.manager_workbench import binding,service,api as api_module
 from v4.manager_workbench.config import WorkbenchConfig
 def event(name):
  with (root/'events.jsonl').open('a') as f:f.write(json.dumps({'event':name,'epoch':time.time()})+'\n');f.flush();os.fsync(f.fileno())
 class IsolatedService:
  def __init__(self):self.pool=concurrent.futures.ThreadPoolExecutor(1)
  def stop(self):event('EXACT_API_LIFESPAN_STOP_ENTER');self.pool.shutdown(wait=True);event('JOBS_DRAINED')
 owner=IsolatedService();service.create_service=lambda *a,**kw:owner;api_module.create_router=lambda svc:APIRouter()
 app=FastAPI();binding.assemble_api(app,config=WorkbenchConfig(state_root=root/'state'),binding={'adapters':None,'engines':None,'executor':None})
 def work():event('JOB_ACCEPTED');time.sleep(6.2);event('JOB_COMPLETED')
 @app.get('/accepted')
 async def accepted():owner.pool.submit(work);return {'accepted':True}
 @app.get('/slow')
 async def slow():event('HTTP_ACCEPTED');await asyncio.sleep(1);event('HTTP_RESPONSE_FINISHED');return {'finished':True}
 @app.get('/health')
 async def health():return {'ok':True}
 uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning');event('PROCESS_RETURNED');raise SystemExit(0)
def main():
 plan=json.loads((HERE/'PLAN_REVIEW_ONLY_R7.json').read_text());api=plan['releases'][1]['candidate_app']
 with tempfile.TemporaryDirectory(prefix='v4-r7-api-drain-') as t:
  root=Path(t).resolve();sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
  log=(root/'stderr.txt').open('w');p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'child',str(root),str(port),api],stdout=log,stderr=log,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
  def get(path):
   with urllib.request.urlopen(f'http://127.0.0.1:{port}'+path,timeout=10) as r:return r.status,r.read()
  try:
   deadline=time.monotonic()+12
   while True:
    try:get('/health');break
    except OSError:
     if p.poll() is not None or time.monotonic()>deadline:raise RuntimeError('ISOLATED_SERVER_START_FAILED')
     time.sleep(.05)
   assert get('/accepted')[0]==200;responses=[];thread=threading.Thread(target=lambda:responses.append(get('/slow')));thread.start()
   while not (root/'events.jsonl').exists() or 'HTTP_ACCEPTED' not in (root/'events.jsonl').read_text():time.sleep(.01)
   started=time.monotonic();p.send_signal(signal.SIGTERM);thread.join(8);rc=p.wait(timeout=12);elapsed=time.monotonic()-started
   events=[json.loads(x) for x in (root/'events.jsonl').read_text().splitlines()];names=[x['event'] for x in events]
   assert rc==-signal.SIGTERM and responses[0][0]==200 and elapsed>5
   assert names.index('HTTP_RESPONSE_FINISHED')<names.index('EXACT_API_LIFESPAN_STOP_ENTER')<names.index('JOB_COMPLETED')<names.index('JOBS_DRAINED')
   result=dict(status='PASS',scope='Owned isolated HTTP and detached job preserved under one SIGTERM through installed uvicorn0.52.1 and exact API binding lifespan; no real8873/launchctl/root/data use',exit_code=rc,seconds_after_sigterm=elapsed,events=events,http_status=responses[0][0],new_connection_gap='EXPECTED_NOT_ZERO_DOWNTIME')
   (HERE/'API_GRACEFUL_PROBE_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
  except Exception as error:
   (HERE/'API_GRACEFUL_PROBE_FAILURE.txt').write_text(json.dumps({'error':str(error),'rc':p.poll(),'events':(root/'events.jsonl').read_text() if (root/'events.jsonl').exists() else '', 'stderr':(root/'stderr.txt').read_text()},indent=2));raise
  finally:
   if p.poll() is None:
    # Only own failed temp probe, never a real service. Preserve diagnostics first.
    (HERE/'API_GRACEFUL_PROBE_FAILURE.txt').write_text((root/'stderr.txt').read_text());p.kill();p.wait()
   log.close()
if __name__=='__main__':main()
