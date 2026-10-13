from datetime import datetime
import pytest
from pydantic import ValidationError
from test_runtime import config,Engine,Calendar,Stages,done
from v4.manager_workbench.contracts import Lane,Phase
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.service import create_service
from v4.manager_workbench.scheduler import tick


def test_two_scheduled_lanes_pause_announcement_and_capture(tmp_path):
    cfg=config(tmp_path);cfg.scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD]
    s=create_service(cfg,object(),Engine(),None)
    try:
        # Guard a capture-enabled host as well as the current disabled one.
        s.capture_jobs=object()
        s.request_capture=lambda context: pytest.fail('paused announcement capture enqueued')
        result=tick(s,calendar=Calendar(),stage_feed=Stages(),at=datetime.fromisoformat('2026-10-13T16:30:00+08:00'))
        for item in result['jobs']:
            if 'job_id' not in item:continue
            job=done(s,s.jobs.get(item['job_id']))
            assert job.context.scope_refs['requested_lanes']==['US_MAPPING','OVERSOLD']
            assert {l.lane for l in s.store.get_plan(job.context.target_date,run_id=job.run_id).lanes}=={Lane.US_MAPPING,Lane.OVERSOLD}
        assert tick(s,calendar=Calendar(),stage_feed=Stages(),at=datetime.fromisoformat('2026-10-13T16:31:00+08:00'))['jobs']==[]
        s.capture_jobs=None
        explicit=done(s,s.submit('20261013',Phase.MANUAL,lanes=[Lane.ANNOUNCEMENT]))
        assert explicit.context.scope_refs['requested_lanes']==['ANNOUNCEMENT']
        default=done(s,s.submit('20261013',Phase.MANUAL))
        assert default.context.scope_refs['requested_lanes']==[l.value for l in Lane]
    finally:s.capture_jobs=None;s.stop()


def test_configured_scope_does_not_retry_old_all_lane_claim(tmp_path):
    cfg=config(tmp_path);s=create_service(cfg,object(),Engine(),None)
    try:
        first=tick(s,calendar=Calendar(),stage_feed=Stages(),at=datetime.fromisoformat('2026-10-13T16:30:00+08:00'))
        for j in first['jobs']:
            if j.get('job_id'):done(s,s.jobs.get(j['job_id']))
        cfg.scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD]
        second=tick(s,calendar=Calendar(),stage_feed=Stages(),at=datetime.fromisoformat('2026-10-13T16:31:00+08:00'))
        assert {j['phase'] for j in second['jobs']}=={'INTRADAY','NEXT_DAY'}
        for j in second['jobs']:
            job=done(s,s.jobs.get(j['job_id']))
            assert job.context.scope_refs['requested_lanes']==['US_MAPPING','OVERSOLD']
    finally:s.stop()


@pytest.mark.parametrize('lanes',[[],['OVERSOLD','OVERSOLD'],['UNKNOWN']])
def test_invalid_scheduled_scope_rejected(tmp_path,lanes):
    with pytest.raises(ValidationError):WorkbenchConfig(state_root=tmp_path,scheduled_lanes=lanes)
