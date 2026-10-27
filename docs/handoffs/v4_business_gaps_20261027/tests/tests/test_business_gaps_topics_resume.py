from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pytest
from ops.run_zsxq_hourly_delta import collect_paginated_topics, materialize_zsxq_hourly_delta, _previous_success_time

TZ=ZoneInfo('Asia/Shanghai');GROUPS=(('g1','incomplete'),('g2','complete'))
SINCE=datetime(2026,10,23,8,30,59,tzinfo=TZ);CUTOFF=datetime(2026,10,27,8,30,59,tzinfo=TZ)


def topic(key,time,group='g1'):
    return {'topic_id':key,'create_time':time,'group':{'group_id':group,'name':dict(GROUPS)[group]}}


def successful_page(command,**kwargs):
    assert '--end-time' in command and command[command.index('--end-time')+1]=='2026-10-24T12:00:00+08:00'
    assert command[command.index('--group-id')+1]=='g1'
    return subprocess.CompletedProcess(command,0,json.dumps({'topics':[topic('oldest','2026-10-23T09:00:00+08:00'),topic('outside','2026-10-23T08:00:00+08:00')],'has_more':True}),'')


def legacy_run(tmp_path):
    status={'trade_date':'20261027','slot':'0830','latest_run_id':'original','status':'READY','fetch_ok':True,
        'fetched_at':'2026-10-27T08:31:00+08:00','source_since':SINCE.isoformat(),'source_cutoff':CUTOFF.isoformat(),
        'cannot_confirm':['ZSXQ_PAGINATION_BOUNDED_HAS_MORE'],'paths':{'run_dir':'external_sources/zsxq_hourly/original'},
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    root=tmp_path/'external_sources/zsxq_hourly/original';root.mkdir(parents=True)
    topics=[topic('a','2026-10-24T12:00:00+08:00'),topic('b','2026-10-25T12:00:00+08:00'),topic('c','2026-10-25T12:00:00+08:00','g2')]
    files={root/'zsxq_recent_topics.json':{'topics_brief':topics},root/'zsxq_recent_topics_fetch_result.json':{'groups':[
        {'group_id':'g1','group_name':'incomplete','page_count':20,'deduped_count':2,'source_has_more':True,'reached_since':False},
        {'group_id':'g2','group_name':'complete','page_count':1,'deduped_count':1,'source_has_more':False,'reached_since':True}]}}
    path=tmp_path/'research_module/runtime_outputs/zsxq_hourly/20261027/0830/v35_zsxq_hourly_status_20261027_0830.json'
    files[path]=status
    for p,value in files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
    return path,{p:p.read_bytes() for p in files if p!=path}


def test_legacy_resume_preserves_original_window_and_successful_files_and_skips_complete_group(tmp_path):
    status,original=legacy_run(tmp_path)
    result=materialize_zsxq_hourly_delta(data_root=tmp_path,trade_date='20261027',slot='0830',groups=GROUPS,
        resume_source_run_id='original',process_runner=successful_page,analyzer=lambda *a:{'effective_topic_count':4},
        now=datetime(2026,10,27,16,30,tzinfo=TZ))
    assert result['status']=='READY' and result['topic_count']==4
    assert result['source_since']==SINCE.isoformat() and result['source_cutoff']==CUTOFF.isoformat()
    assert result['resume_observed_at']=='2026-10-27T16:30:00+08:00'
    assert result['original_source_fetched_at']=='2026-10-27T08:31:00+08:00'
    assert result['collection_timing']=='RESUMED_AFTER_ORIGINAL_WINDOW'
    assert all(result[k] is False for k in ('original_window_completeness_certified','natural_verified','pit_certified'))
    assert all(p.read_bytes()==raw for p,raw in original.items())
    fetch=json.loads(Path(result['paths']['fetch_result']).read_text())
    assert fetch['groups'][0]['cursor_origin']=='DERIVED_OWNED_LEGACY_TOPIC_MIN_TIME'
    assert fetch['groups'][0]['reached_since'] is True and fetch['groups'][1]['new_page_count']==0
    assert _previous_success_time(tmp_path,'20261027','1700')==CUTOFF


def test_known_provider_failure_keeps_successful_page_and_cursor_as_partial():
    calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        if len(calls)==1:return subprocess.CompletedProcess(command,0,json.dumps({'topics':[topic('a','2026-10-24T12:00:00+08:00')],'has_more':True}),'')
        return subprocess.CompletedProcess(command,1,'','original provider failure')
    result=collect_paginated_topics(cli=Path('/fixture'),groups=GROUPS[:1],as_of=CUTOFF,since=SINCE,process_runner=runner)
    assert len(result['topics'])==1 and result['bounded_has_more'] is True
    assert result['group_results'][0]['next_cursor']=='2026-10-24T12:00:00+08:00'
    assert 'original provider failure' in result['group_results'][0]['error']


def test_partial_reuse_never_refetches_or_advances_success_time(tmp_path):
    legacy_run(tmp_path)
    result=materialize_zsxq_hourly_delta(data_root=tmp_path,trade_date='20261027',slot='0830',
        process_runner=lambda *a,**k:pytest.fail('partial source silently refetched'))
    assert result['reused'] is True and result['status']=='PARTIAL'
    assert _previous_success_time(tmp_path,'20261027','1700') is None


@pytest.mark.parametrize('defect',['run','group','window'])
def test_resume_identity_drift_stops_before_fetch(tmp_path,defect):
    path,_=legacy_run(tmp_path);status=json.loads(path.read_text())
    if defect=='window':status['source_cutoff']='2026-10-28T08:30:59+08:00';path.write_text(json.dumps(status))
    with pytest.raises(ValueError):
        materialize_zsxq_hourly_delta(data_root=tmp_path,trade_date='20261027',slot='0830',
            groups=(('other','wrong'),) if defect=='group' else GROUPS,resume_source_run_id='wrong' if defect=='run' else 'original',
            process_runner=lambda *a,**k:pytest.fail('drift reached provider'))
