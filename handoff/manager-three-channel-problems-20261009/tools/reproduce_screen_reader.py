#!/usr/bin/env python3
"""Read-only invocation of the production HK security-master loader."""
import argparse,hashlib,json,os,sys
from pathlib import Path

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--app-root',required=True,help='application source root containing upstreams/')
 parser.add_argument('--authority-root',required=True,help='existing shared root; read only')
 parser.add_argument('--trade-date',required=True,help='exact YYYYMMDD session')
 args=parser.parse_args()
 app=Path(args.app_root).resolve(); root=Path(args.authority_root).resolve()
 sys.path.insert(0,str(app/'upstreams')); sys.path.insert(0,str(app))
 from v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
 latest_path=root/'assets'/'hk_security_master'/'latest.json'
 raw=latest_path.read_bytes(); latest=json.loads(raw)
 entries=latest.get('entries') if isinstance(latest,dict) else None
 result={'trade_date':args.trade_date,'authority_root':str(root),'latest_json_sha256':hashlib.sha256(raw).hexdigest(),'entry_count':len(entries) if isinstance(entries,dict) else None,'latest_entry_date':max(entries) if isinstance(entries,dict) and entries else None,'requested_entry_present':isinstance(entries,dict) and args.trade_date in entries,'writes':False}
 try:
  names,manifest=load_verified_hk_security_master(root,args.trade_date)
  result.update({'status':'READ_OK','name_count':len(names),'manifest_trade_date':manifest.get('trade_date')})
 except Exception as exc:
  result.update({'status':'READ_ERROR','exception_type':type(exc).__name__,'exception':str(exc)})
 print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
if __name__=='__main__':
 os.environ.setdefault('PYTHONDONTWRITEBYTECODE','1')
 raise SystemExit(main())
