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


def _rebound_authority_root(tmp_path):
    root=tmp_path/'rebound-authority'
    (root/'assets/hk_0_2').mkdir(parents=True)
    (root/'assets/hk_security_master').mkdir(parents=True)
    # These are the two existing owner pointer paths. Empty JSON cannot
    # establish verified rebound history, so downstream evidence stays fail-closed.
    (root/'assets/hk_0_2/panel_latest.json').write_text('{}')
    (root/'assets/hk_security_master/latest.json').write_text('{}')
    return root


def _publish_synthetic_rebound_owner_sources(root,date):
    import pandas as pd
    from v3_shared_data.shared_data.hk_security_master import (LATEST_SCHEMA_VERSION,
        publish_hk_security_master,load_verified_hk_security_master)
    from v4.manager_research.workspace_plan import rebound_history_sessions,_read_hk02_panel_witness,read_rebound_history
    sessions=rebound_history_sessions(date)
    frame=pd.DataFrame([{'trade_date_compact':day,'code_norm':'HK.00001','high':12.0,'trade':1000}
        for day in sessions['prior60']])
    panel_relative='panels/rebound_history.parquet'
    panel_path=root/'assets/hk_0_2'/panel_relative
    panel_path.parent.mkdir(parents=True,exist_ok=True)
    frame.to_parquet(panel_path,index=False)
    manifest={
        'asset_schema_version':'v3_shared_data.hk_0_2_panel_asset.v2',
        'panel_max_date':sessions['panel_session'],'panel_relative':panel_relative,
        'panel_sha256':hashlib.sha256(panel_path.read_bytes()).hexdigest(),
        'panel_code_count':1,'panel_rows':len(frame),
        'source_contract':'tdx_vipdoc_71_day+verified_zero_trade_repairs',
        'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
    }
    manifest_path=root/'assets/hk_0_2/panels/manifest.json'
    manifest_path.write_text(json.dumps(manifest,sort_keys=True))
    (root/'assets/hk_0_2/panel_latest.json').write_text(json.dumps({'manifest_relative':'panels/manifest.json'}))
    panel_witness,panel_gaps=_read_hk02_panel_witness(root,sessions['panel_session'])
    assert panel_witness is not None and not panel_gaps
    (root/'assets/hk_security_master/latest.json').write_text(json.dumps(
        {'schema_version':LATEST_SCHEMA_VERSION,'entries':{}}))
    published=publish_hk_security_master(root,trade_date=date,
        rows=[{'code':'HK.00001','name':'SIMULATED issuer','outstanding_shares':1000,
            'circular_market_val':10000,'listing_date':'2020-01-01','lot_size':100,
            'stock_owner':'SIMULATED','stock_child_type':'SIMULATED','sec_status':'NORMAL'}],
        universe_codes_sha256='a'*64,captured_at='2026-09-18T15:29:00+08:00')
    names,master=load_verified_hk_security_master(root,date)
    assert published['status']=='READY' and 'HK.00001' in names and master['trade_date']==date
    history=read_rebound_history(root,date,['HK.00001'],now=AS_OF)
    assert history['status']=='PARTIAL' and len(history['source_files'])==4
    assert history['symbols']['HK.00001']['prior60_count']==60
    assert history['symbols']['HK.00001']['previous5_count']==5
    return history


def inputs(tmp_path):
    universe(tmp_path/'universe')
    make_news(tmp_path/'data')
    return dict(data_root=tmp_path/'data',universe_root=tmp_path/'universe',futu_python=Path(sys.executable),trade_date=DATE,manager_state_root=tmp_path/'state',news_owner_root=APP,app_root=APP,rebound_authority_root=_rebound_authority_root(tmp_path),clock=lambda:AS_OF)


def fingerprint(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_single_bridge_call_actual_artifact_and_full_app_asgi_consumption(tmp_path,monkeypatch):
    args=inputs(tmp_path);calls=[]
    monkeypatch.setenv('V4_CLOSE_REBOUND_AUTHORITY_ROOT',str(args['rebound_authority_root']))
    def fetch(*args,**kwargs): calls.append((args,kwargs)); return [row()],[]
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
            candidate=body['candidates'][0]
            predicates={p['predicate_id']:p['value'] for p in candidate['predicates']}
            assert predicates=={
                'amount_100m_lt_le_200m_hkd':True,
                'oversold_le_80pct_prior60_high':'unknown',
                'volume_ge_1_5_previous5_full_days':'unknown',
                'last_price_ge_1_03_low_so_far':'unknown',
                'final_close_confirmation':'unknown',
            }
            # The legacy fourth catalyst condition remains independently verified;
            # the REBOUND_V3 contract adds a fifth, still-unknown same-day close gate.
            assert candidate['catalyst']['status']=='CONFIRMED_PIT'
            assert candidate['qualified'] is None
            assert body['RESEARCH_ONLY'] is True and body['orders_sent'] is False
    asyncio.run(get());assert fingerprint(tmp_path)==before and len(calls)==1


def test_bridge_failure_publishes_empty_failed_not_zero_candidates_success(tmp_path):
    args=inputs(tmp_path)
    def fetch(*a,**kwargs): raise RuntimeError('SIMULATED provider outage')
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
    args=inputs(tmp_path);calls=[];provider_returned={'late':False}
    def clock():
        return AS_OF.replace(minute=32) if provider_returned['late'] else AS_OF
    def fetch(*a,**kwargs):
        calls.append((a,kwargs))
        provider_returned['late']=True
        return [row()],[]
    args['clock']=clock
    out=m.materialize(**args,snapshot_fetcher=fetch)
    assert len(calls)==1
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
    owner_history=_publish_synthetic_rebound_owner_sources(args['rebound_authority_root'],DATE)
    assert owner_history['symbols']['HK.00001']['gaps']==[]
    raw=(APP/'tests/fixtures/manager_workbench_b1_simulated.json').read_text()
    for a,b in [('20260917','20260916'),('2026-09-17','2026-09-16'),('20260918','20260917'),('2026-09-18','2026-09-17')]:raw=raw.replace(a,b)
    prior=json.loads(raw);prior['candidates'][0].update(symbol='HK.00001',research_priority=None,catalyst=None)
    path=tmp_path/'state/workbench_research/20260917/1530.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(prior))
    assert read_prior_evidence(tmp_path/'state',expected_date='20260917',as_of=AS_OF) is not None
    result=m.materialize(**args,snapshot_fetcher=lambda *a,**kwargs:([row()],[]))
    assert result['status']=='MATERIALIZED'
    artifact=json.loads((tmp_path/'state/workbench_research/20260918/1530.json').read_text())
    c=artifact['candidates'][0]
    # The pinned _decorate implementation in domains/manager_close_rebound.py
    # replaces the prior priority with one of the REBOUND_V3 classifications;
    # UPGRADED_WATCH is unreachable here.  Preserve the nullable prior level
    # and assert that missing unit/finality evidence cannot promote the row.
    assert 'CONTINUOUS_TRACKING' in c['source_lanes']
    assert c['research_priority']['previous_level'] is None
    assert c['research_priority']['level']=='PENDING_EVIDENCE'
    assert c['research_priority']['formal_rank_changed'] is False
    assert c['research_priority']['buy_gate_changed'] is False
    assert c['data_status']=='PENDING_EVIDENCE'
    predicates={p['predicate_id']:p['value'] for p in c['predicates']}
    assert predicates=={
        'amount_100m_lt_le_200m_hkd':True,
        'oversold_le_80pct_prior60_high':'unknown',
        'volume_ge_1_5_previous5_full_days':'unknown',
        'last_price_ge_1_03_low_so_far':'unknown',
        'final_close_confirmation':'unknown',
    }
    assert c['qualified'] is None
    assert c['position']['rebound_v3']['final_close'] is None
    assert c['position']['rebound_v3']['close_confirmation']=='unknown'
    assert c['volume_comparison']['ratio'] is None
    assert c['volume_comparison']['raw_provider_ratio']==2.0
    assert artifact['RESEARCH_ONLY'] is True
    assert artifact['production_allowed'] is False
    assert artifact['buy_gate_updated'] is False
    assert artifact['orders_sent'] is False
