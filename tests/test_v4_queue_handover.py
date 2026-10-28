from __future__ import annotations
from datetime import datetime,timedelta
from pathlib import Path
import json,os
from zoneinfo import ZoneInfo
import pytest
from infrastructure.scheduling.queued_handover import recover_queued_jobs,_digest

TZ=ZoneInfo('Asia/Shanghai')
NOW=datetime(2026,10,28,18,30,tzinfo=TZ)


def lane(slot):return 'A_LONG' if slot=='1700' else 'DEFAULT'
def cutoff(day,slot):return datetime.strptime(day+'2300','%Y%m%d%H%M').replace(tzinfo=TZ)


def observation(root,slot,*,status='QUEUED',order=1,changes=None):
    day='20261028';p=root/'scheduler_observations/live'/day/slot/(str(order)+'.observation.json');p.parent.mkdir(parents=True,exist_ok=True)
    d={'schema_version':'v4.scheduler_observation.v1','business_date':day,'slot':slot,'lane':lane(slot),'status':status,'planned_at':datetime.strptime(day+slot,'%Y%m%d%H%M').replace(tzinfo=TZ).isoformat(),'queued_at':datetime(2026,10,28,18,0,tzinfo=TZ).isoformat(),'observed_at':datetime(2026,10,28,18,1,tzinfo=TZ).isoformat(),'cutoff_at':cutoff(day,slot).isoformat(),'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    d.update(changes or {});d['ledger_sha256']=_digest(d);p.write_text(json.dumps(d));os.utime(p,ns=(order,order));return p,d


def recover(root,now=NOW):return recover_queued_jobs(root,now,slots=('1700','1720','1800'),lane_for=lane,cutoff_for=cutoff)


def test_original_job_identity_cutoff_and_backoff_survive_restart(tmp_path):
    _,d=observation(tmp_path,'1700');observation(tmp_path,'1720',status='CHILD_START_FAILED')
    jobs,blocked=recover(tmp_path);assert not blocked
    assert jobs[('20261028','1700')]=={k:d[k] for k in ['business_date','slot','planned_at','queued_at','cutoff_at']}
    assert jobs[('20261028','1720')]['next_start_at']=='2026-10-28T18:06:00+08:00'
    assert jobs[('20261028','1700')]['slot']=='1700' and NOW.strftime('%H%M')=='1830'


def test_newer_corrupt_record_blocks_only_that_job_without_old_queue_fallback(tmp_path):
    observation(tmp_path,'1700');p,_=observation(tmp_path,'1700',order=2);p.write_text('{bad');os.utime(p,ns=(2,2));observation(tmp_path,'1720')
    jobs,blocked=recover(tmp_path)
    assert ('20261028','1700') not in jobs and ('20261028','1700') in blocked
    assert ('20261028','1720') in jobs and ('20261028','1720') not in blocked


@pytest.mark.parametrize('state',['FINISHED','FINISHED_CANNOT_CONFIRM','EXPIRED','CLAIM_OR_RECEIPT_BLOCKED'])
def test_newer_terminal_observation_does_not_resurrect_old_queued_job(tmp_path,state):
    observation(tmp_path,'1700');observation(tmp_path,'1700',order=2,status=state)
    jobs,blocked=recover(tmp_path);assert not jobs and not blocked


def test_same_time_latest_is_ambiguous_and_keeps_other_lane(tmp_path):
    a,_=observation(tmp_path,'1700',order=1);b,_=observation(tmp_path,'1700',order=2);os.utime(a,ns=(2,2));observation(tmp_path,'1720')
    jobs,blocked=recover(tmp_path);assert blocked[('20261028','1700')]=='QUEUE_HANDOVER_LATEST_AMBIGUOUS';assert ('20261028','1720') in jobs


@pytest.mark.parametrize('changes',[{'lane':'DEFAULT'},{'business_date':'20261027'},{'cutoff_at':'2026-10-28T23:59:00+08:00'},{'observed_at':'2026-10-28T19:00:00+08:00'},{'production_allowed':True}])
def test_invalid_identity_cannot_create_a_recovery_job(tmp_path,changes):
    observation(tmp_path,'1700',changes=changes);jobs,blocked=recover(tmp_path)
    assert not jobs and ('20261028','1700') in blocked


def test_expired_original_cutoff_and_previous_day_do_not_restart(tmp_path):
    observation(tmp_path,'1700');jobs,blocked=recover(tmp_path,datetime(2026,10,28,23,1,tzinfo=TZ));assert not jobs and not blocked
    jobs,blocked=recover(tmp_path,datetime(2026,10,29,8,0,tzinfo=TZ));assert not jobs and not blocked
