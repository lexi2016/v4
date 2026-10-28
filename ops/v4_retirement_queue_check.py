"""Read-only rollback guard over the existing current-day queue observations."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from infrastructure.scheduling.queued_handover import recover_queued_jobs
from ops.run_v4_macos_scheduler_due import ALL_SLOTS, SHANGHAI, _slot_retry_deadline


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger-root',type=Path,required=True);p.add_argument('--now');a=p.parse_args()
    now=datetime.fromisoformat(a.now) if a.now else datetime.now(SHANGHAI)
    if now.tzinfo is None:p.error('--now requires a timezone')
    now=now.astimezone(SHANGHAI)
    jobs,blocked=recover_queued_jobs(a.ledger_root,now,slots=ALL_SLOTS,lane_for=lambda s:'A_LONG' if s=='1700' else 'DEFAULT',cutoff_for=_slot_retry_deadline)
    out={'status':'CLEAR' if not jobs and not blocked else 'PENDING_OR_CANNOT_CONFIRM','observed_at':now.isoformat(),'pending':[v for v in jobs.values()],'cannot_confirm':[{'business_date':d,'slot':s,'reason':r} for (d,s),r in blocked.items()],'write_performed':False,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out['status']=='CLEAR' else 2


if __name__=='__main__':raise SystemExit(main())
