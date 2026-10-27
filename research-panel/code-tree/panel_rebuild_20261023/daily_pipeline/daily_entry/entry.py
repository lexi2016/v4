"""Offline date-safe daily entry. Never fetch, upload, publish, train, or trade.
Only an explicitly supplied reviewed daily config may be staged. No pin rewriting.
"""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parent

def beijing_date(iso=None):
 now = datetime.datetime.fromisoformat(iso) if iso else datetime.datetime.now(datetime.timezone.utc)
 if now.tzinfo is None:
  raise ValueError('TIMEZONE_REQUIRED')
 return now.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')

def require_date(config, target):
 if any(config.get(k) != target for k in ('date', 'vintage', 'g4_trade_date', 'events_vintage')):
  raise ValueError('STALE_CONFIG_OR_INCOMPLETE_DATE_BINDING')

def exit_status(receipt):
 return 0 if receipt.get('status') == 'READY_RESEARCH_SNAPSHOT' and receipt.get('counts', {}).get('failed') == 0 else 2

def main():
 parser = argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--date', help='YYYYMMDD; default current Asia/Shanghai date; explicit historical date is replay only')
 parser.add_argument('--config', help='Reviewed local date-specific config; default daily_entry/incoming/YYYYMMDD.json')
 parser.add_argument('--out', default=str(PIPELINE/'daily_runs'))
 parser.add_argument('--mode', choices=['dry-run', 'stage'], default='dry-run')
 args = parser.parse_args()
 spec = importlib.util.spec_from_file_location('entry_pipeline_v4', PIPELINE/'pipeline_v4.py')
 pipeline = importlib.util.module_from_spec(spec)
 spec.loader.exec_module(pipeline)
 target = args.date or beijing_date()
 try:
  pipeline.date_ok(target)
  # Frozen reviewed calendar, not a mutable assumed weekday calendar. Out of
  # coverage/changed bytes block; a new reviewed version requires an entry update.
  calendar = pipeline.load(pipeline.pinned({'path':str(PIPELINE/'CALENDAR_20261023_1231_VERIFIED_V2.json'), 'sha256':'227e07683c91fe5bc6077f506daea0a3c2836d431f4c2767841147429053bc30'}))
  gate = pipeline.calendar_gate(calendar,target)
  if gate['status'] == 'MARKET_CLOSED_NO_UPDATE':
   print(json.dumps({'status':gate['status'],'target_date':target,'upload_executed':False}));return 0
  if not gate['publish_allowed']:
   raise ValueError(gate['status'])
  path = pipeline.safe_ancestors(args.config or HERE/'incoming'/(target+'.json'))
  if not path.is_file():
   result = {'status':'AWAITING_REVIEWED_DAILY_INPUTS','target_date':target,'config_path':str(path),'missing':['new-date G4 archive','current corporate-action/events snapshot and bound source receipt','reviewed date-specific config'],'fetch_executed':False,'upload_executed':False,'natural_scheduled_run':'NOT_RUN'}
   print(json.dumps(result, ensure_ascii=False, indent=2));return 2
  config = pipeline.load(path)
  require_date(config,target)
  prepared = pipeline.prepare(config)
  gate = pipeline.calendar_gate(prepared[6],target)
  if gate['status'] in ('MARKET_CLOSED_NO_UPDATE','MARKET_EXTRAORDINARY_CLOSED_NO_UPDATE'):
   print(json.dumps({'status':gate['status'],'target_date':target,'upload_executed':False}));return 0
  if not gate['publish_allowed']:
   raise ValueError(gate['status'])
  result = pipeline.run(config,args.out,args.mode,publish=False)
  result.update(entry_timezone='Asia/Shanghai', entry_invocation='EXPLICIT_DATE_REPLAY' if args.date else 'CURRENT_LOCAL_DATE', upload_executed=False)
  print(json.dumps(result,ensure_ascii=False,indent=2))
  return exit_status(result)
 except Exception as exc:
  print(json.dumps({'status':'BLOCKED','target_date':target,'error':type(exc).__name__+': '+str(exc),'previous_snapshot_preserved':True,'upload_executed':False},ensure_ascii=False));return 2

if __name__ == '__main__':
 raise SystemExit(main())
