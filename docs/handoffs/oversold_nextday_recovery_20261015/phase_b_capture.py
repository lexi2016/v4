"""Invoke the existing shared daily owner; no independent producer or SDK install."""
import argparse, hashlib, importlib.abc, importlib.util, io, json, sys, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from upstreams.v3_shared_data.shared_data import hk_daily_supplement as owner
H=Path(__file__).resolve().parent

def digest(data):return hashlib.sha256(data).hexdigest()
class PinnedWheel(importlib.abc.MetaPathFinder,importlib.abc.Loader):
    def __init__(self,archive):self.archive=archive;self.names=set(archive.namelist())
    def find_spec(self,fullname,path=None,target=None):
        if fullname!='tdxpy' and not fullname.startswith('tdxpy.'):return None
        relative=fullname.replace('.','/');package=relative+'/__init__.py';module=relative+'.py'
        selected=package if package in self.names else module
        if selected not in self.names:return None
        spec=importlib.util.spec_from_loader(fullname,self,is_package=selected==package);spec.loader_state=selected;return spec
    def create_module(self,spec):return None
    def exec_module(self,module):
        member=module.__spec__.loader_state;module.__file__='pinned-memory-wheel:'+member
        exec(compile(self.archive.read(member),module.__file__,'exec'),module.__dict__)


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--full',action='store_true');args=ap.parse_args()
 name='full' if args.full else 'canary';receipt_path=H/f'phase_b_{name}_capture_r2.json'
 assert not receipt_path.exists(),'No blind repeat; inspect the existing receipt'
 config_path=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v9.json')
 config_raw=config_path.read_bytes();config=json.loads(config_raw);authority=Path(config['shared_root']).resolve()
 out=authority/'assets/hk_0_2/daily_supplements/tdxpy61'
 r=dict(stage='B',mode=name,started_at=datetime.now(timezone.utc).isoformat(),source_root=str(ROOT),config_path=str(config_path),config_sha256=digest(config_raw),
  authority_root=str(authority),owner_file=str(Path(owner.__file__)),owner_sha256=digest(Path(owner.__file__).read_bytes()),
  native_paths={k:str(out/k) for k in ['cache','catalogues','.capture.lock']},
  safety=owner.SAFETY,connections=[])
 loader=None
 try:
  metadata=json.load(urllib.request.urlopen('https://pypi.org/pypi/tdxpy/0.2.7/json',timeout=20))
  wheel=next(x for x in metadata['urls'] if x['filename'].endswith('.whl') and x['digests']['sha256']==owner.TDXPY_PROFILE['wheel_sha256'])
  raw=urllib.request.urlopen(wheel['url'],timeout=30).read();assert digest(raw)==owner.TDXPY_PROFILE['wheel_sha256']
  archive=zipfile.ZipFile(io.BytesIO(raw));parser='tdxpy/parser/ext/ex_get_instrument_bars.py';assert digest(archive.read(parser))==owner.TDXPY_PROFILE['parser_sha256']
  r['sdk']=dict(wheel_url=wheel['url'],wheel_sha256=digest(raw),parser_sha256=digest(archive.read(parser)),loaded_in_memory=True)
  assert not any(k=='tdxpy' or k.startswith('tdxpy.') for k in sys.modules)
  loader=PinnedWheel(archive);sys.meta_path.insert(0,loader)
  from tdxpy.exhq import TdxExHq_API
  def connector(endpoint):
   assert endpoint in owner.TDXPY_NODES
   host,port=endpoint.split(':');api=TdxExHq_API(heartbeat=False,auto_retry=False,raise_exception=True)
   okay=api.connect(host,int(port),time_out=3);r['connections'].append(dict(endpoint=endpoint,connected=bool(okay),observed_at=datetime.now(timezone.utc).isoformat()))
   if not okay:api.disconnect();raise ConnectionError('EXISTING_TDXPY_NODE_CONNECTION_FAILED')
   return api
  binding=dict(manifest_relative='assets/hk_0_2/panels/20261015-a562369dbc49/manifest.json',manifest_sha256='bf80f6869862c9363f132d8ca0b134e613d919bc0441b52550efcc417726fba0')
  if args.full:
   canary=json.loads((H/'phase_b_canary_capture_r2.json').read_bytes());assert canary['capture']['ready_count']==1 and canary['capture']['unassessed_count']==0
  r['capture']=owner.capture_tdxpy_window_supplement(authority,target_date='20261015',connector=connector,canary_codes=None if args.full else ['HK.00001'],panel_binding=binding)
  r['status']='CAPTURE_COMPLETE'
 except BaseException as exc:
  r.update(status='FAILED_NO_BLIND_RETRY',error_type=type(exc).__name__,error=str(exc));raise
 finally:
  if loader in sys.meta_path:sys.meta_path.remove(loader)
  r['finished_at']=datetime.now(timezone.utc).isoformat()
  with receipt_path.open('x') as stream:json.dump(r,stream,ensure_ascii=False,indent=2);stream.write('\n')
 print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__':main()
