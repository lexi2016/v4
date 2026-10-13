"""C handoff HTTP fixtures captured from FastAPI's actual B router.

To update after an intentional router contract change:
    PYTHONPATH=. python tests/manager_workbench/runtime/test_http_contract_samples.py
Fixtures are synthetic, redacted and deterministic; not V4 production responses.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench.api import PREFIX,create_router
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import JobRecord,ReviewSummary,PlanSnapshot,seal_snapshot
from v4.manager_workbench.service import create_service
from v4.manager_workbench.store import StorageUnavailable

SAMPLES=Path(__file__).resolve().parents[1]/'contract_samples'


def _case(folder):
    config=WorkbenchConfig(state_root=folder/'state',legacy_root=folder/'legacy',model='SYNTHETIC_MODEL',
                           rules_version='SYNTHETIC_RULES',prompt_version='SYNTHETIC_PROMPT')
    service=create_service(config,{},object(),object())
    app=FastAPI();app.include_router(create_router(service))
    return service,TestClient(app)


def _result(response):
    return {'status':response.status_code,'body':response.json()}


def generate_http_samples():
    out={}
    with TemporaryDirectory(prefix='mwb-http-fixtures-') as temp:
        directory=Path(temp)
        empty_service,empty_http=_case(directory/'missing')
        try:
            out['http_empty.json']={
                'GET /days/{date}':_result(empty_http.get(PREFIX+'/days/20261013')),
                'GET /history':_result(empty_http.get(PREFIX+'/history',params={'date':'20261013'}))}
        finally:empty_service.jobs.stop()

        # Actual HTTP success after immutable store commit/readback.
        service,http=_case(directory/'ready')
        try:
            candidate=json.loads((SAMPLES/'normal.json').read_text())
            candidate['stocks'][0]['lane_decisions']={'ANNOUNCEMENT':[{
                'decision':'SELECTED','reason':'SYNTHETIC_ONLY','evidence_ids':['ev-1']}],
                'STAGE_REFERENCE':[{'decision':'OBSERVATION_ONLY','reason':'NO_FORMAL_ADMISSION'}]}
            snapshot=seal_snapshot(candidate)
            stored=service.store.commit_plan(snapshot)
            assert stored.product_sha256==snapshot.product_sha256
            review=ReviewSummary(target_date='20261013',plan_run_id=stored.run_id,
                    mode='SYNTHETIC_COMPLETE_CLOSE',ranking_date='20261013',
                    evaluation_scope_ref='synthetic:close:full',
                    top20_rows=[{'rank':i,'symbol':f'HK.{i:05d}',
                                 'strict_hit':i==1,'extended_hit':i==1} for i in range(1,21)],
                    strict_coverage={'covered':1,'denominator':20,'ratio':0.05,'intersection':['HK.00001']},
                    extended_coverage={'covered':1,'denominator':20,'ratio':0.05,'intersection':['HK.00001']},
                    selected_denominator=1,gaps=[])
            service.store.save_review(review)
            # Legacy schema is unknown; return one CANNOT_CONFIRM entry, not an overwritten conclusion.
            folder=service.config.legacy_root/'20261013';folder.mkdir(parents=True)
            (folder/'old.json').write_text('{"schema_version":"unknown.v0","run_id":"old-id"}',encoding='utf-8')
            out['http_success.json']={
                'GET /days/{date}':_result(http.get(PREFIX+'/days/20261013',params={'run_id':stored.run_id})),
                'GET /stocks/{symbol}':_result(http.get(PREFIX+'/stocks/HK.00001',params={'date':'20261013','run_id':stored.run_id})),
                'GET /history':_result(http.get(PREFIX+'/history',params={'date':'20261013'})),
                'GET /reviews/{date}':_result(http.get(PREFIX+'/reviews/20261013',params={'plan_run_id':stored.run_id}))}
            assert isinstance(out['http_success.json']['GET /stocks/{symbol}']['body']['data']['stock']['lane_decisions']['ANNOUNCEMENT'],list)
            assert out['http_success.json']['GET /stocks/{symbol}']['body']['data']['lane_details'][0]['evidence_refs']
            metric=out['http_success.json']['GET /reviews/{date}']['body']['data']['strict_coverage']
            assert metric=={'covered':1,'denominator':20,'ratio':0.05,'intersection':['HK.00001']}
        finally:service.jobs.stop()

        service,http=_case(directory/'partial')
        try:
            candidate=json.loads((SAMPLES/'partial.json').read_text())
            stored=service.store.commit_plan(PlanSnapshot.model_validate(candidate))
            out['http_partial.json']={
                'GET /days/{date}':_result(http.get(PREFIX+'/days/20261013',params={'run_id':stored.run_id})),
                'GET /reviews/{date}: no data':_result(http.get(PREFIX+'/reviews/20261013',params={'plan_run_id':stored.run_id}))}
        finally:service.jobs.stop()

        service,http=_case(directory/'failed')
        try:
            candidate=json.loads((SAMPLES/'failed_job.json').read_text())
            # Pinned fixture contains a FAILED attempt, independent of snapshot.
            job=JobRecord.model_validate(candidate)
            service.store.save_job(job)
            out['http_failed.json']={
                'GET /runs/{id}':_result(http.get(PREFIX+'/runs/'+job.job_id)),
                'POST /runs/{id}/retry (409)':_result(http.post(PREFIX+'/runs/'+job.job_id+'/retry'))}
            out['http_errors.json']={
                'GET malformed date (422)':_result(http.get(PREFIX+'/days/20260230')),
                'GET malformed symbol (422)':_result(http.get(PREFIX+'/stocks/HK.００００１',params={'date':'20261013','run_id':'sample-run'})),
                'GET unknown job (404)':_result(http.get(PREFIX+'/runs/missing')),
                'POST extra untrusted fields (422)':_result(http.post(PREFIX+'/runs',json={
                    'target_date':'20261013','phase':'MANUAL','rows':[]}))}
            original=service.store.get_job
            def unavailable(*args):raise StorageUnavailable('SYNTHETIC_NO_CHANNEL')
            service.store.get_job=unavailable
            out['http_errors.json']['GET channel unavailable (503)']=_result(http.get(PREFIX+'/runs/missing'))
            service.store.get_job=original
            assert out['http_errors.json']['GET channel unavailable (503)']['body']=={'detail':'STATE_CHANNEL_UNAVAILABLE'}
        finally:service.jobs.stop()
    return out


def test_actual_router_http_samples_match_frozen_c_handoff():
    for filename,expected in generate_http_samples().items():
        actual=json.loads((SAMPLES/filename).read_text(encoding='utf-8'))
        assert actual==expected, filename


def test_c_handoff_fields_errors_states_and_safety():
    out=generate_http_samples()
    success=out['http_success.json']
    day=success['GET /days/{date}']['body']
    assert day['state']=='READY' and len(day['data']['versions'])==1
    assert day['RESEARCH_ONLY'] is True and not day['production_allowed']
    assert day['data']['counts']['selected']==1
    history=success['GET /history']['body']['data']
    assert history['versions']==history['entries']
    assert len(history['versions'])==2 and history['versions'][1]['verification']=='CANNOT_CONFIRM'
    partial=out['http_partial.json']['GET /days/{date}']['body']
    assert partial['state']=='PARTIAL' and 'OVERSOLD_UNAVAILABLE' in partial['gaps']
    empty=out['http_empty.json']['GET /days/{date}']['body']
    assert empty['state']=='NOT_RUN' and empty['data']['counts'] is None
    assert out['http_failed.json']['POST /runs/{id}/retry (409)']['status']==409
    for key,value in out['http_errors.json'].items():
        assert isinstance(value['body']['detail'],(str,list)),key


if __name__=='__main__':
    for filename,content in generate_http_samples().items():
        (SAMPLES/filename).write_text(json.dumps(content,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        print(f'WROTE {filename}')
