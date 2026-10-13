"""Operator entry into the EXISTING HK daily supplement owner, not a producer.

One explicit <=3-stock canary must precede a machine panel-gap subset run.
Full-master mode is retained only as the older backup entry; panel gaps are
prepared by prepare_panel_gaps.py and valid panel stocks are never requested. This script
performs reads on the two approved TDX nodes only when collect is requested.
prepare only binds the saved owner bytes; it does not change formal state_root.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,sys,zipfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sha=lambda b:hashlib.sha256(b).hexdigest()

def runtime():
 spec=importlib.util.spec_from_file_location('accepted_calendar_runtime',HERE/'recover_cached_full_date.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.install_runtime()

def sdk(output):
 from upstreams.v3_shared_data.shared_data.hk_daily_supplement import TDXPY_PROFILE
 wheel=HERE/'.tmp/tdxpy-official-source/tdxpy-0.2.7.whl'
 if sha(wheel.read_bytes())!=TDXPY_PROFILE['wheel_sha256']:raise ValueError('TDXPY_WHEEL_IDENTITY_CHANGED')
 with zipfile.ZipFile(wheel) as archive:
  if sha(archive.read('tdxpy/parser/ext/ex_get_instrument_bars.py'))!=TDXPY_PROFILE['parser_sha256']:raise ValueError('TDXPY_PARSER_IDENTITY_CHANGED')
  directory=output/'sdk'
  for name in archive.namelist():
   p=Path(name)
   if p.is_absolute() or '..' in p.parts:raise ValueError('TDXPY_ARCHIVE_PATH_INVALID')
   if name.endswith('/') or not name.startswith('tdxpy/') or not name.endswith('.py'):continue
   target=directory/p;data=archive.read(name)
   if target.exists() and target.read_bytes()!=data:raise ValueError('TDXPY_LOCAL_SDK_DRIFT')
   target.parent.mkdir(parents=True,exist_ok=True)
   if not target.exists():target.write_bytes(data)
 sys.path.insert(0,str(directory))
 from tdxpy.exhq import TdxExHq_API
 import tdxpy.exhq as loaded_sdk
 if not Path(loaded_sdk.__file__).resolve().is_relative_to(directory.resolve()):raise ValueError('TDXPY_LOADED_SDK_IDENTITY_DRIFT')
 def connector(endpoint):
  host,port=endpoint.split(':');api=TdxExHq_API(heartbeat=False,auto_retry=False,raise_exception=True)
  if not api.connect(host,int(port),time_out=2.0):
   api.disconnect();raise ConnectionError('TDXPY_APPROVED_NODE_CONNECTION_FAILED:'+endpoint)
  api.client.settimeout(2.0)
  return api
 return connector

def collect(args):
 from upstreams.v3_shared_data.shared_data.hk_daily_supplement import capture_tdxpy_window_supplement
 output=args.owner_root.resolve()
 if not output.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('ISOLATED_OWNER_OUTPUT_REQUIRED')
 if not args.full_master and not getattr(args,'gap_subset',False) and not args.canary_code:raise ValueError('EXPLICIT_CANARY_REQUIRED')
 gap_plan=None
 if getattr(args,'panel_gaps',None) or getattr(args,'panel_gaps_sha256',None):
  if not args.panel_gaps or not args.panel_gaps_sha256:raise ValueError('PANEL_GAP_PIN_REQUIRED')
  raw=args.panel_gaps.read_bytes()
  if sha(raw)!=args.panel_gaps_sha256:raise ValueError('PANEL_GAP_PIN_SHA_MISMATCH')
  gap_plan=json.loads(raw)
 if getattr(args,'gap_subset',False) and gap_plan is None:raise ValueError('PANEL_GAP_PIN_REQUIRED')
 if args.full_master or getattr(args,'gap_subset',False) and gap_plan.get('gap_codes'):
  # An independently checked saved canary is a mandatory operator pin.
  if not args.accepted_canary or not args.accepted_canary_sha256:raise ValueError('ACCEPTED_CANARY_PIN_REQUIRED')
  raw=args.accepted_canary.read_bytes()
  if sha(raw)!=args.accepted_canary_sha256:raise ValueError('ACCEPTED_CANARY_SHA_MISMATCH')
  accepted=json.loads(raw)
  if accepted.get('target_date')!=args.price_date or accepted.get('ready_count',0)<1 or accepted.get('master_scope_count')!=692:raise ValueError('ACCEPTED_CANARY_SCOPE_INVALID')
  if gap_plan is not None:
   from upstreams.v3_shared_data.shared_data.hk_daily_supplement import _sha,_canonical
   if accepted.get('panel_gap_plan_sha256')!=_sha(_canonical(gap_plan)):raise ValueError('ACCEPTED_CANARY_PANEL_GAPS_MISMATCH')
 loaded=[]
 def connector(endpoint):
  if not loaded:loaded.append(sdk(output))
  return loaded[0](endpoint)
 pin=capture_tdxpy_window_supplement(args.authority_root,target_date=args.price_date,
       connector=connector,output_root=output,canary_codes=None if args.full_master or getattr(args,"gap_subset",False) else args.canary_code,
       panel_binding=dict(manifest_relative=args.panel_manifest_relative,manifest_sha256=args.panel_manifest_sha256) if args.panel_manifest_relative or args.panel_manifest_sha256 else None, panel_gap_plan=gap_plan)
 if pin.get('status')=='NO_PANEL_GAPS':
  print(json.dumps(pin),flush=True);return
 result=output/('full-pin-'+pin['run_id']+'.json' if args.full_master or getattr(args,'gap_subset',False) else 'canary-pin-'+pin['run_id']+'.json')
 if result.exists():raise ValueError('IMMUTABLE_PIN_EXISTS')
 result.write_text(json.dumps(pin,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(status='CAPTURED',pin_path=str(result),pin_sha256=sha(result.read_bytes()),**pin),ensure_ascii=False),flush=True)

def prepare(args):
 from upstreams.v3_shared_data.shared_data.hk_daily_supplement import read_tdxpy_window_supplement,read_tdxpy_panel_identity,_read_master_identity
 raw=args.pin.read_bytes()
 if sha(raw)!=args.pin_sha256:raise ValueError('TDXPY_PIN_SHA_MISMATCH')
 pin=json.loads(raw);config=json.loads(args.base_config.read_bytes())
 root=Path(config['shared_root']);panel=read_tdxpy_panel_identity(root,pin,args.price_date);master,codes=_read_master_identity(root,args.price_date)
 manifest,records=read_tdxpy_window_supplement(pin,target_date=args.price_date,cutoff=args.cutoff,
   expected_panel_sha=panel['panel_sha256'],expected_master_sha=master['artifact_sha256'],expected_codes=codes,
   expected_panel_manifest_sha=panel['panel_manifest_sha256'],expected_master_manifest_sha=master['manifest_sha256'])
 out=args.output.resolve()
 if out.exists() or not out.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 original_state=config['state_root']
 config.setdefault('source_bindings',{}).setdefault('hk_panel',{}).setdefault(args.price_date,{})['tdxpy_history']=pin
 config.update(capture_enabled=False,capture_lease_token=None,scheduled_lanes=['US_MAPPING','OVERSOLD'])
 if config['state_root']!=original_state:raise ValueError('FORMAL_STATE_ROOT_CHANGED')
 out.mkdir(parents=True);p=out/'base-config.json';p.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
 proof=dict(status='PREPARED_NOT_RUN',target_date='20261013',price_date=args.price_date,config_path=str(p),config_sha256=sha(p.read_bytes()),
  state_root_preserved=original_state,full_master_scope_count=len(codes),owner_capture_scope=manifest['capture_scope'],
  owner_observed_count=len(records),owner_complete_61_count=manifest['ready_count'],owner_unknown_count=manifest['unassessed_count'],
  owner_pin_sha256=args.pin_sha256,owner_available_at=manifest['available_at'],cutoff=args.cutoff,network_calls=0,model_calls=0,formal_writes=0)
 (out/'receipt.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof),flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
 c=sub.add_parser('collect');c.add_argument('--authority-root',required=True,type=Path);c.add_argument('--owner-root',required=True,type=Path)
 group=c.add_mutually_exclusive_group(required=True);group.add_argument('--canary-code',action='append');group.add_argument('--full-master',action='store_true');group.add_argument('--gap-subset',action='store_true')
 c.add_argument('--panel-gaps',type=Path);c.add_argument('--panel-gaps-sha256')
 c.add_argument('--panel-manifest-relative');c.add_argument('--panel-manifest-sha256')
 c.add_argument('--accepted-canary',type=Path);c.add_argument('--accepted-canary-sha256')
 q=sub.add_parser('prepare');q.add_argument('--base-config',required=True,type=Path);q.add_argument('--pin',required=True,type=Path);q.add_argument('--pin-sha256',required=True)
 q.add_argument('--cutoff',required=True);q.add_argument('--output',required=True,type=Path)
 for parser in (c,q):parser.add_argument('--price-date',default='20261012')
 args=p.parse_args();runtime();collect(args) if args.mode=='collect' else prepare(args)
if __name__=='__main__':main()
