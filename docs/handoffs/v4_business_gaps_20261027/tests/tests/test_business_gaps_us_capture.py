import ast
from copy import deepcopy
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pytest


def consumer():
    # Execute the actual pure consumer functions without importing unrelated
    # API/PDF runtime dependencies from this mixed source worktree.
    path=Path(__file__).parents[1]/'apps/api/v35_api/research_lane_router.py'
    tree=ast.parse(path.read_text())
    names={'_is_late_capture_identity','_bound_capture_for_snapshot'}
    fields={'LATE_CAPTURE_MODE','LATE_CAPTURE_REASON','_CAPTURE_IDENTITY_FIELDS'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names or
           isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in fields for t in n.targets)]
    namespace=dict(Any=Any,Mapping=Mapping,datetime=datetime,time=time,timedelta=timedelta,ZoneInfo=ZoneInfo)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['_bound_capture_for_snapshot']


def original():
    capture={'capture_id':'bb134e4f411ac97293977dcb','capture_origin':'ORIGINAL_TIME_CAPTURE',
        'capture_phase':'POST_CLOSE','capture_window_end':'2026-10-26T16:20:00-04:00',
        'capture_window_start':'2026-10-26T16:15:00-04:00','captured_at':'2026-10-26T20:15:03Z',
        'original_time_capture':True,'run_id':'us-rss:20261026:POST_CLOSE:bb134e4f411ac97293977dcb',
        'session_timezone':'America/New_York','us_session_date':'20261026'}
    snapshot={'capture_phase':'POST_CLOSE','capture_session_date':'20261026','provider_session_dates':['20261026'],
        'captured_at':'2026-10-26T20:15:03Z','provider_receipt':{'http_status':200},'source_response_sha256':'a'*64}
    return {'trade_date':'20261027','us_session_captures':[capture]},snapshot


def test_original_natural_us_session_is_next_shanghai_research_day_without_late_relabel():
    p,s=original();before=deepcopy((p,s));result,error=consumer()(payload=p,snapshot=s,research_date='20261027')
    assert error is None and result==p['us_session_captures'][0]
    assert (p,s)==before and 'late' not in result


@pytest.mark.parametrize('defect',['target','future','ambiguous','snapshot_clock','timezone','before_close','holiday','bad_window'])
def test_cross_date_identity_clock_calendar_and_ambiguity_stay_fail_closed(defect):
    p,s=original();c=p['us_session_captures'][0]
    if defect=='target':p['trade_date']='20261028'
    elif defect=='future':c['captured_at']='2026-10-27T20:15:03Z';s['captured_at']=c['captured_at']
    elif defect=='ambiguous':p['us_session_captures'].append(deepcopy(c))
    elif defect=='snapshot_clock':s['captured_at']='2026-10-26T20:16:03Z'
    elif defect=='timezone':c['session_timezone']='Asia/Shanghai'
    elif defect=='before_close':c['captured_at']='2026-10-26T19:59:59Z';s['captured_at']=c['captured_at']
    elif defect=='holiday':
        c['us_session_date']='20261025';s['capture_session_date']='20261025';s['provider_session_dates']=['20261025']
    else:c['capture_window_start']='2026-10-26T16:20:00-04:00'
    assert consumer()(payload=p,snapshot=s,research_date='20261027')[1] is not None


def test_actual_frozen_24_board_source_binds_without_rewriting_original_capture():
    import json,hashlib
    path=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/research/peripherals/20261027/external_finance.json')
    if not path.is_file():pytest.skip('external original authority is not in source capsule')
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()=='bdc1c90989d05300bc216d8fbbd66906b17a23d654eb5e72238da4c6db80240a'
    payload=json.loads(raw);snapshot=payload['market_snapshot'];capture,error=consumer()(payload=payload,snapshot=snapshot,research_date='20261027')
    assert error is None and capture['capture_id']=='bb134e4f411ac97293977dcb'
    assert capture['original_time_capture'] is True and capture['us_session_date']=='20261026'
    assert snapshot['futu_board_snapshot']['status']=='PARTIAL'
    assert path.read_bytes()==raw


def test_natural_cross_day_capture_keeps_original_ny_dst_offset():
    p,s=original();c=p['us_session_captures'][0]
    p['trade_date']='20261103';c.update(us_session_date='20261102',captured_at='2026-11-02T21:15:03Z',
        capture_window_start='2026-11-02T16:15:00-05:00',capture_window_end='2026-11-02T16:20:00-05:00')
    s.update(capture_session_date='20261102',provider_session_dates=['20261102'],captured_at=c['captured_at'])
    assert consumer()(payload=p,snapshot=s,research_date='20261103')[1] is None
