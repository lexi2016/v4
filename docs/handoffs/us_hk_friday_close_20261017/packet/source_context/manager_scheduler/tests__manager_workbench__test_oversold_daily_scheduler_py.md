## Source excerpt: `tests/manager_workbench/test_oversold_daily_scheduler.py`

Original source path: `/Users/lexi/Desktop/学习/v4_app/tests/manager_workbench/test_oversold_daily_scheduler.py`

Original full-file SHA-256: `73ff736afd9d8ad959c3edc3e6811218cf9135fa7cde81215d3812c8af80eab4`

Release/worktree group: `manager_scheduler`

Current repository test for 16:30 next-day scheduling and Saturday NOT_APPLICABLE. Not present in loaded r3 release tests.

### Full-source lines 115-178

```python

def test_nextday_other_lane_runs_at_1630_and_oversold_waits_separately():
    class Calendar:
        def is_hk_session(self,day):return day in {SOURCE,TARGET}
        def next_hk_session(self,day):return TARGET
        def session_state(self,day):return "HALF_TRADING_DAY_AM"

    class Store:
        def __init__(self):self.values={}
        def get_plan(self,*args):return None
        def cursor(self,key):return self.values.get(key)
        def set_cursor(self,key,value):self.values[key]=dict(value)

    class Driver:
        def __init__(self):self.calls=[]
        def tick(self,**kwargs):self.calls.append(kwargs);return {"state":"WAITING_FOR_PANEL_MASTER"}

    class Service:
        def __init__(self):
            self.config=SimpleNamespace(scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD])
            self.store=Store();self.oversold_daily=Driver();self.submissions=[];self.capture_jobs=None
        def freeze_preopen(self,*args,**kwargs):return SimpleNamespace(run_id="preopen")
        def submit(self,target,phase,**kwargs):
            self.submissions.append((target,phase,kwargs))
            return SimpleNamespace(run_id="us-run",job_id="us-job")

    service=Service()
    instant=datetime(2026,10,16,16,30,tzinfo=HK)
    result=tick(service,calendar=Calendar(),stage_feed=SimpleNamespace(completed_runs=lambda day:[]),at=instant)
    assert service.submissions[0][0:2]==(TARGET,Phase.NEXT_DAY)
    assert service.submissions[0][2]["lanes"]==[Lane.US_MAPPING]
    assert service.submissions[0][2]["scope_refs"]["merge_phase_lanes"] is True
    assert service.submissions[0][2]["cutoff"]==instant
    assert service.oversold_daily.calls==[{"source_day":SOURCE,"target_date":TARGET,"at":instant}]
    assert any(item.get("lane")=="OVERSOLD" and item.get("state")=="WAITING_FOR_PANEL_MASTER"
               for item in result["jobs"])


def test_scheduler_holiday_skips_and_weekend_next_session_is_calendar_owned():
    class Calendar:
        def is_hk_session(self,day):return day in {"20261016",TARGET}
        def next_hk_session(self,day):return TARGET
        def session_state(self,day):return "HALF_TRADING_DAY_AM"

    class Store:
        def get_plan(self,*args):return object()
        def cursor(self,key):return None
        def set_cursor(self,key,value):pass

    class Service:
        config=SimpleNamespace(scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD])
        store=Store();submissions=[];capture_jobs=None;oversold_daily=None
        def submit(self,target,phase,**kwargs):
            self.submissions.append((target,phase,kwargs));return SimpleNamespace(run_id="run",job_id="job")

    service=Service()
    calendar=Calendar()
    weekend=tick(service,calendar=calendar,stage_feed=SimpleNamespace(completed_runs=lambda day:[]),
        at=datetime(2026,10,17,16,30,tzinfo=HK))
    assert weekend["state"]=="NOT_APPLICABLE" and not service.submissions
    friday=tick(service,calendar=calendar,stage_feed=SimpleNamespace(completed_runs=lambda day:[]),
        at=datetime(2026,10,16,16,30,tzinfo=HK))
    assert friday["date"]=="20261016"
    assert service.submissions[0][0]==TARGET  # The authoritative calendar skips the weekend.


```
