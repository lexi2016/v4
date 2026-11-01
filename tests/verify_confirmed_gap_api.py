"""Exercise the existing workbench routes against two isolated candidate bindings."""
import argparse
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.request import ProxyHandler, build_opener

from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure import research_workbench_host as wb


def read_ref(path, digest):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('CANDIDATE_SHA_CHANGED')
    value=json.loads(raw)
    return value,{'path':str(path),'sha256':digest}


def live_day():
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8873/api/v4/research/workbench/days/2026-10-30',timeout=5) as response:
        return json.load(response)


def rows_sha(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def verify(candidates):
    day=live_day();pool_hash=rows_sha(day['rows'])
    if day.get('scope_count')!=172 or len(day['rows'])!=172:raise ValueError('LIVE_POOL_NOT_172')
    stocks={};refs={}
    for code,(path,digest) in candidates.items():
        candidate,_=read_ref(path,digest);binding=wb.checked(candidate['binding'])
        if binding['symbol']!=code or binding['source_generation']!=day['generation'] or binding['source_input_sha256']!=day['input_sha256']:
            raise ValueError('ISOLATED_BINDING_SOURCE_CONFLICT:'+code)
        stocks[code]=binding;refs[code]=candidate['binding']
    host=wb.ResearchWorkbenchHost.__new__(wb.ResearchWorkbenchHost)
    host.binding={'single_stock_research_by_symbol':refs,'single_stock_research':refs['002865.SZ']}
    host._view=lambda date,revision=None:{'source_generation':day['generation'],
        'source_identity':{'input_sha256':day['input_sha256']},'manifest':day['numeric_manifest'],'rows':day['rows']}
    host._observation_date=lambda date:day['observation_date']
    host.classifications=SimpleNamespace(close=lambda:None)
    original=wb.ResearchWorkbenchHost;results={}
    try:
        with tempfile.TemporaryDirectory(prefix='kb-gap-api-test-') as scratch:
            dummy=Path(scratch).resolve()/'binding.json';dummy.write_bytes(b'{}')
            os.environ['V4_WORKBENCH_HOST_BINDING']=str(dummy)
            os.environ['V4_WORKBENCH_HOST_BINDING_SHA256']=hashlib.sha256(dummy.read_bytes()).hexdigest()
            wb.ResearchWorkbenchHost=lambda source,binding:host
            app=FastAPI();app.include_router(wb.create_workbench_router(object()),prefix='/api/v4/research')
            with TestClient(app) as client:
                for code in ('301048.SZ','002865.SZ','301048.SZ'):
                    url=f'/api/v4/research/workbench/days/2026-10-30/single-research/{code}'
                    response=client.get(url,params={'revision':day['generation']});assert response.status_code==200,response.text
                    meta=response.json();assert meta['status']=='READY_FOR_RESEARCH_REVIEW' and meta['confirmed_gap']
                    assert meta['rows']==stocks[code]['rows'] and meta['field_inventory']['total_derived_fields']==107
                    ref=meta['assets']['kb'];asset=client.get(ref['url']);assert asset.status_code==200
                    assert hashlib.sha256(asset.content).hexdigest()==ref['sha256']
                    view=json.loads(gzip.decompress(asset.content));last=view['rows'][-1]
                    assert view['candidate_generation']==meta['candidate_generation']
                    assert view['confirmed_gap_diagnostics_sha256']==meta['confirmed_gap']['diagnostics_sha256']
                    n_contract=meta['confirmed_gap'].get('n_structure_contract_sha256')
                    assert len(last['confirmed_kb_fields'])==8 and len(last['confirmed_kb_diagnostics'])==(25 if n_contract else 24)
                    if n_contract:
                        assert view['n_structure_contract_sha256']==n_contract
                        n=last['confirmed_kb_diagnostics']['kb_n_structure'];score=last['hold_score']
                        assert n['rule_sha256']==n_contract
                        if code=='002865.SZ':
                            assert score['kb_hold_score']==score['kb_hold_score_min']==score['kb_hold_score_max']==4
                            assert score['kb_hold_trend_up'] is False and n['state']=='STRUCTURE_NOT_RISING'
                        else:
                            assert score['kb_hold_score'] is None and (score['kb_hold_score_min'],score['kb_hold_score_max'])==(1,2)
                            assert score['kb_hold_trend_up'] is None and n['state']=='AMBIGUOUS_SAME_BAR_PIVOT'
                    assert last['kb']['kb_rebuild'] is (code=='301048.SZ')
                    if code=='002865.SZ':
                        warm=next(x for x in view['rows'] if x['trade_date']==20170515)
                        assert warm['kb']['kb_brick_consecutive']==2
                        assert warm['confirmed_kb_diagnostics']['kb_brick_count_reason']=='BRICK_RUN_ORIGIN_IN_WARMUP'
                    results[code]={'candidate_generation':meta['candidate_generation'],'rows':meta['rows'],
                        'candidate_pool_member':meta['candidate_pool_member'],'kb_asset_sha256':ref['sha256'],
                        'latest_rebuild':last['kb']['kb_rebuild'],'latest_confirmed_fields':last['confirmed_kb_fields'],
                        'n_structure_contract_sha256':n_contract,'latest_hold_score':last['hold_score']}
    finally:
        wb.ResearchWorkbenchHost=original
    after=live_day()
    if rows_sha(after['rows'])!=pool_hash:raise ValueError('LIVE_POOL_MOVED_DURING_ISOLATED_TEST')
    return {'status':'PASS_ISOLATED_WORKBENCH_ROUTES','source_date':day['source_date'],'observation_date':day['observation_date'],
        'pool_count':len(day['rows']),'live_pool_sha256':pool_hash,'pool_unchanged':True,'switch_sequence':['301048.SZ','002865.SZ','301048.SZ'],
        'stocks':results,'runtime_8873_modified':False,'global_pointer_updated':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--junda',type=Path,required=True);p.add_argument('--junda-sha256',required=True)
    p.add_argument('--jinying',type=Path,required=True);p.add_argument('--jinying-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=verify({'002865.SZ':(a.junda.resolve(strict=True),a.junda_sha256),
                                    '301048.SZ':(a.jinying.resolve(strict=True),a.jinying_sha256)})
    with a.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(result,ensure_ascii=False))
