"""Serve-only isolated C9 candidate using the existing dashboard demo app; Root IAB owns UI."""
from pathlib import Path
import hashlib,importlib.abc,importlib.util,json,socket,sys,tempfile,threading,time
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;TASK=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/readable_stock_materials');P=B.parent.parent
C=json.loads((B/'CANDIDATES.json').read_text());API=Path(C['api']['release'])/'app'
class CandidateOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] not in {'apps','domains','infrastructure','contracts','ops','stage_center','shared_data','upstreams'}:return None
  relative=Path(*fullname.split('.'))
  for base in [API,API/'upstreams']:
   p=base/relative.with_suffix('.py');init=base/relative/'__init__.py'
   if p.is_file():return importlib.util.spec_from_file_location(fullname,p)
   if init.is_file():return importlib.util.spec_from_file_location(fullname,init,submodule_search_locations=[str(init.parent)])
   if (base/relative).is_dir():
    from importlib.machinery import ModuleSpec
    s=ModuleSpec(fullname,loader=None,is_package=True);s.submodule_search_locations=[str(base/relative)];return s
sys.meta_path.insert(0,CandidateOnly());sys.path[:0]=[str(API/'upstreams'),str(API)]
p=HERE.parent/'serve_daily_dashboard_demo.py';spec=importlib.util.spec_from_file_location('existing_c8_demo',p);demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
factory=demo.create_research_router
demo.create_research_router=lambda *args,**kwargs:factory(*args,**kwargs,a_share_daily_root=P/'today_full_r1',original_chart_artifact_root=P)
plan=json.loads((B/'PUBLICATION_PLAN.json').read_text());staged={Path(plan[k]['target']):Path(plan[k]['candidate']['path']).read_text() for k in ['index','event']};original=Path.read_text
def read(path,*args,**kwargs):return staged[path] if path in staged else original(path,*args,**kwargs)
import uvicorn
with tempfile.TemporaryDirectory(prefix='c9-demo-runtime-') as td,patch.object(Path,'read_text',read):
 app=demo.create_demo_app(P/'today_full_r1',Path(td),panel_root=Path(C['api']['release'])/'research-panel',report_data_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data'))
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False));thread=threading.Thread(target=server.run,daemon=True);thread.start()
 try:
  deadline=time.monotonic()+10
  while not server.started and time.monotonic()<deadline:time.sleep(.05)
  assert server.started
  print('C9_ISOLATED_URL=http://127.0.0.1:'+str(port)+'/research-panel/daily.html?date=2026-10-29#dailyNumeric283Panel',flush=True)
  print('Candidate API/static plus staged metadata; no live writes or browser automation. Root IAB owns UI.',flush=True)
  while thread.is_alive():time.sleep(1)

 finally:server.should_exit=True;thread.join(timeout=10);assert not thread.is_alive()
