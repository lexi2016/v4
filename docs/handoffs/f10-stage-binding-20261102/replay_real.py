#!/usr/bin/env python3
"""Read-only replay of three original retained-release hourly publications."""
import os,sys,json,hashlib
from pathlib import Path
from datetime import datetime
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.candidate
receipt=json.loads((root/'candidate_receipt.json').read_bytes()); env=receipt['proposed_environment']['stage'];os.environ.update(env)
app=Path(env['V4_APP_ROOT']);sys.path.insert(0,str(app))
from infrastructure import manager_input_attestation as m
m._release_manifest(app, env['V4_RELEASE_ID'], env['V4_RELEASE_MANIFEST_SHA256'], m._STAGE_RESEARCH_FILES)
results={'candidate_stage_identity':'PASS_FIXED_STAGE_MANIFEST_RESEARCH_EXECUTION_FILES','samples':[]}
cfg=json.loads((app/'stage_center_tick_config.json').read_bytes());data=Path(cfg['v4_research_data_root'])
# Exact publication + original full dispatch witness for each retained historical identity.
for date,slot in [('20261101','2300'),('20261030','1000'),('20261029','2300')]:
 item={'date':date,'slot':slot,'reads':{}}
 orig=Path.read_bytes
 def audit(path):
  raw=orig(path)
  if path.is_relative_to(data) or path.is_relative_to(Path(cfg['research_scheduler_ledger_root'])):item['reads'][str(path)]=hashlib.sha256(raw).hexdigest()
  return raw
 Path.read_bytes=audit
 try:
  value,evidence=m.read_stage_hourly_attestation(stage_app=app,data_root=data,date=date,slot=slot,mode='LIVE',as_of=datetime.fromisoformat(f'{date[:4]}-{date[4:6]}-{date[6:]}T23:59:59+08:00'))
  item.update(status='PASS_READ_ONLY_HISTORICAL_REPLAY',completion_witness=value['completion_witness'],evidence=evidence)
 except Exception as e:item.update(status='FAIL',error=str(e),error_type=type(e).__name__)
 finally:Path.read_bytes=orig
 results['samples'].append(item)
args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
