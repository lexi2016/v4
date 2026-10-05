"""SIMULATED end-to-end materializer -> full app -> read-only API tests."""
import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path
import httpx
import pytest
from test_manager_r2_rework import AS_OF,DATE,APP,universe,row,make_news
from ops import materialize_manager_close_discovery as m
from apps.api.v35_api.app import create_app
from apps.api.v35_api import manager_workbench_router as reader
from domains.manager_catalyst_tracking import prior_workbench_candidates, read_prior_evidence
from infrastructure.manager_close_attempt import write_attempt


def inputs(tmp_path):
    universe(tmp_path/'universe')
    make_news(tmp_path/'data')
    return dict(data_root=tmp_path/'data',universe_root=tmp_path/'universe',futu_python=Path(sys.executable),trade_date=DATE,manager_state_root=tmp_path/'state',news_owner_root=APP,app_root=APP,clock=lambda:AS_OF)


def fingerprint(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_single_bridge_call_actual_artifact_and_full_app_asgi_consumption(tmp_path):
    args=inputs(tmp_path);calls=[]
    def fetch(*args): calls.append(args); return [row()],[]
    result=m.materialize(**args,snapshot_fetcher=fetch)
    assert result['status']=='MATERIALIZED' and len(calls)==1
    assert result['qualified_count']==0 and result['observation_count']==1
    second=m.materialize(**args,snapshot_fetcher=fetch)
    assert second['status']=='ALREADY_EXISTS' and len(calls)==1
    app=create_app(data_root=tmp_path/'data',shared_data_root=tmp_path/'universe',ledger_root=tmp_path/'ledger',stage_center_selection_root=tmp_path/'stage',manager_research_state_root=tmp_path/'state',current_date=DATE)
    assert '/api/v4/manager/workbench-research' in app.openapi()['paths']
    before=fingerprint(tmp_path)
    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://SIMULATED') as client:
            r=await client.get('/api/v4/manager/workbench-research',params={'date':DATE,'market':'HK_CONNECT','slot':'1530'})
            assert r.status_code==200
            body=r.json();assert body['status']=='PARTIAL' and len(body['candidates'])==1
            assert [p['value'] for p in body['candidates'][0]['predicates']]==[True,'unknown','unknown',True]
            assert body['candidates'][0]['qualified'] is None
            assert body['RESEARCH_ONLY'] is True and body['orders_sent'] is False
    asyncio.run(get());assert fingerprint(tmp_path)==before and len(calls)==1


def test_bridge_failure_publishes_empty_failed_not_zero_candidates_success(tmp_path):
    args=inputs(tmp_path)
    def fetch(*a): raise RuntimeError('SIMULATED provider outage')
    out=m.materialize(**args,snapshot_fetcher=fetch)
    assert out['status']=='FAILED'
    status=json.loads((tmp_path/'state'/f'workbench_research/{DATE}/1530.status.json').read_text())
    assert status['status']=='FAILED' and status['candidates']==[]
    assert not (tmp_path/'state'/f'workbench_research/{DATE}/1530.json').exists()


def test_late_call_does_not_fetch_or_backfill(tmp_path):
    args=inputs(tmp_path);args['clock']=lambda:AS_OF.replace(minute=32)
    out=m.materialize(**args,snapshot_fetcher=lambda *a:pytest.fail('late quote fetch forbidden'))
    assert out['status']=='INPUT_MISSING' and out['reason']=='EXACT_1530_SNAPSHOT_WINDOW_MISSED'


def test_late_provider_return_never_used_as_1530(tmp_path):
    args=inputs(tmp_path);calls=0
    times=iter([AS_OF,AS_OF,AS_OF,AS_OF.replace(minute=32),AS_OF.replace(minute=32)])
    args['clock']=lambda:next(times)
    out=m.materialize(**args,snapshot_fetcher=lambda *a:([row()],[]))
    assert out['status']=='INPUT_MISSING'
    assert not (tmp_path/'state'/f'workbench_research/{DATE}/1530.json').exists()


def test_wrong_date_no_historical_materialization(tmp_path):
    args=inputs(tmp_path);args['trade_date']='20260917'
    with pytest.raises(ValueError):m.materialize(**args,snapshot_fetcher=lambda *a:pytest.fail('no historical fetch'))


def test_output_root_and_app_origin_are_mandatory(tmp_path):
    args=inputs(tmp_path);args['manager_state_root']=None
    with pytest.raises(ValueError):m.materialize(**args)
    args['manager_state_root']=tmp_path/'state';args['app_root']=tmp_path/'other'
    with pytest.raises(ValueError):m.materialize(**args)


def _prior(tmp_path,change=None):
    payload=json.loads((APP/'tests/fixtures/manager_workbench_b1_simulated.json').read_text())
    if change:change(payload)
    p=tmp_path/'workbench_research'/DATE/'1530.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(payload))
    return p


def test_prior_reuses_full_b1_validator_not_symbol_json(tmp_path):
    p=_prior(tmp_path)
    prior=read_prior_evidence(tmp_path,expected_date=DATE,as_of=AS_OF.replace(day=21))
    assert prior and len(prior.rows)==1
    assert prior.source['sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    assert prior.source['source_date']==DATE


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(slot='1500'),lambda p:p.update(market='A_SHARE'),
    lambda p:p.update(orders_sent=True),lambda p:p.update(run_id=None),
    lambda p:p.update(as_of='2026-09-18T15:29:00+08:00'),
    lambda p:p.update(generated_at='2026-09-19T15:30:00+08:00'),
    lambda p:p['candidates'][0]['sources'][0].update(reason=None),
    lambda p:p['candidates'][0]['sources'][0].update(source_date='20260919'),
])
def test_prior_rejects_wrong_identity_time_and_lineage(tmp_path,mutation):
    p=_prior(tmp_path,mutation)
    assert prior_workbench_candidates(p,expected_date=DATE,as_of=AS_OF.replace(day=21))=={}

def test_verified_prior_with_nullable_research_fields_is_safe(tmp_path):
    args=inputs(tmp_path)
    raw=(APP/'tests/fixtures/manager_workbench_b1_simulated.json').read_text()
    for a,b in [('20260917','20260916'),('2026-09-17','2026-09-16'),('20260918','20260917'),('2026-09-18','2026-09-17')]:raw=raw.replace(a,b)
    prior=json.loads(raw);prior['candidates'][0].update(symbol='HK.00001',research_priority=None,catalyst=None)
    path=tmp_path/'state/workbench_research/20260917/1530.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(prior))
    assert read_prior_evidence(tmp_path/'state',expected_date='20260917',as_of=AS_OF) is not None
    result=m.materialize(**args,snapshot_fetcher=lambda *a:([row()],[]))
    assert result['status']=='MATERIALIZED'
    c=json.loads((tmp_path/'state/workbench_research/20260918/1530.json').read_text())['candidates'][0]
    assert 'CONTINUOUS_TRACKING' in c['source_lanes'] and c['research_priority']['level']=='UPGRADED_WATCH'
    assert c['qualified'] is None
