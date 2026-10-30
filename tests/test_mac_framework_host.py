"""Local Dot host contract tests; no market collection or historical evaluation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from infrastructure.research_workbench_host import ResearchWorkbenchHost
from ops.build_mac_workbench import build

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
G='a'*64;I='b'*64


def reference(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def host_fixture(tmp_path):
    root=tmp_path/'products';root.mkdir()
    mf=dict(path=str(root/'manifest.json'),sha256='c'*64)
    product=dict(data_date='20261029',source_generation=G,source_identity={'input_sha256':I},source_config={},manifest=mf,artifact={},processed_count=5808,source_universe_count=5808,status='PARTIAL_WITH_ROWS',rows=[dict(symbol='001328.SZ',display_name='小K回踩',groups='nav_smallk|nav_pullback',pending_groups=''),dict(symbol='002003.SZ',display_name='原式',groups='original',pending_groups='nav_breakout')])
    image=reference(root/'image.json',{})
    charts=dict(samples={r['symbol']:dict(rows=861,html=image,PNG=image,projection=image) for r in product['rows']},**FLAGS)
    chart_ref=reference(root/'charts.json',charts);receipt_ref=reference(root/'receipt.json',dict(errors=[],**FLAGS))
    product['original_charts']=dict(numeric_manifest=mf,manifest=chart_ref,receipt=receipt_ref)
    reference(root/'index.json',{'dates':{'20261029':mf}})
    authority=reference(root/'date-binding.json',dict(source_date='2026-10-29',observation_date='2026-10-30'))
    plan=reference(root/'plan.json',dict(stages=[dict(id=1,name='已确认计划',time_bjt='01:00—02:00',action='计划不等于执行')]))
    materials=dict(business_reported={'value':None,'source_url':'https://example.test/statement'},financials_reported={'latest_report_period':'20260930','latest_period_kind':'YTD','monetary_unit':'元','latest_revenue':None,'latest_net_profit_parent':20},shareholders_reported={'holder_count':None},report_catalog=[])
    class Source:
        reads=0;chart_reads=0
        original_chart_artifact_root=root
        def _a_product_root(self):return root
        def read_a_daily_product(self,date,**kwargs):
            assert date=='20261029' and 'symbol' not in kwargs
            self.reads+=1
            return copy.deepcopy(product)
        def _original_chart_bytes(self,ref,**kwargs):
            self.chart_reads+=1
            return Path(ref['path']).read_bytes()
        def read_a_daily_company_materials(self,date,symbol,**kwargs):
            return dict(status='PARTIAL_RECEIVED',numeric_manifest=mf,materials=materials,material_ref=image)
    source=Source();binding=dict(schema='V4_MAC_WORKBENCH_BINDING_V1',observation_dates={'2026-10-29':{'date':'2026-10-30','authority':authority}},workflow_plan=plan,**FLAGS)
    host=ResearchWorkbenchHost(source,binding)
    return SimpleNamespace(host=host,source=source,product=product,root=root,binding=binding,materials=materials,mf=mf)


def test_catalog_day_and_same_manifest_reuse_compact_summary_not5808_histories(host_fixture):
    f=host_fixture
    assert f.host.history()['days'][0]['observation_date']=='2026-10-30'
    day=f.host.day('2026-10-29',G)
    assert day['scope_count']==2 and day['original_processed_count']==5808
    assert day['row_scope']=='FROZEN_CANDIDATE_UNION_ONLY_NOT_FULL_POOL'
    assert day['rows'][0]['group_states']['nav_pullback']=='TRUE'
    assert day['rows'][1]['group_states']['nav_breakout']=='UNKNOWN'
    f.host.day('2026-10-29',G)
    assert f.source.reads==1
    assert 'row_refs' not in next(iter(f.host._cache.values()))


def test_changed_manifest_refreshes_summary_but_wrong_revision_or_missing_date_fails(host_fixture):
    f=host_fixture;first=f.host.day('2026-10-29',G)
    new={**f.mf,'sha256':'d'*64};reference(f.root/'index.json',{'dates':{'20261029':new}});f.product['manifest']=new
    second=f.host.day('2026-10-29',G);assert f.source.reads==2
    assert first['rows'][0] is second['rows'][0]
    with pytest.raises(ValueError,match='REVISION_CONFLICT'):f.host.day('2026-10-29','0'*64)
    with pytest.raises(KeyError):f.host.day('2026-10-28',G)
    with pytest.raises(ValueError):f.host.day('20261029',G)


def test_observation_date_is_explicit_and_missing_quotes_are_unknown_not_close_prices(host_fixture):
    f=host_fixture;answer=f.host.observations('2026-10-29','2026-10-30',G)
    assert answer['latest'] is None and answer['status'].startswith('UNKNOWN')
    with pytest.raises(ValueError,match='OBSERVATION_DATE_CONFLICT'):f.host.observations('2026-10-29','2026-10-29',G)
    f.host.binding['observation_dates']={}
    assert f.host.history()['days'][0]['observation_date'] is None
    with pytest.raises(ValueError,match='OBSERVATION_DATE_UNBOUND'):f.host.day('2026-10-29',G)


def test_chart_and_projection_metadata_reuse_without_ohlcv_reads(host_fixture):
    f=host_fixture;a=f.host.chart_views('2026-10-29',G);b=f.host.chart_views('2026-10-29',G)
    assert a is b and f.source.chart_reads==2
    assert len(a['projections']['rows'])==2
    row=a['projections']['rows'][0]
    assert row['bytes']==(f.root/'image.json').stat().st_size
    assert row['row_count']==861 and 'raw_prices' not in row
    assert 'input_sha256='+I in row['projection_url']


def test_company_keeps_null_period_units_source_and_rejects_revision_mix(host_fixture):
    f=host_fixture;v=f.host.company('2026-10-29','001328.SZ',G)
    assert v['received_materials']==f.materials
    assert v['latest_financial']==dict(report_period='20260930',period_kind='YTD')
    assert v['facts'][0][1]['value'] is None and v['facts'][0][1]['unit']=='元'
    assert v['facts'][2][1]['value'] is None and v['facts'][2][1]['unit']=='户'
    assert v['business']['summary']['source_url']=='https://example.test/statement'
    f.source.read_a_daily_company_materials=lambda *a,**k:dict(status='PARTIAL_RECEIVED',numeric_manifest={'sha256':'0'*64})
    with pytest.raises(ValueError,match='COMPANY_REVISION_MOVED'):f.host.company('2026-10-29','001328.SZ',G)


def test_unbound_overseas_keeps_unknown_and_source_date_conflict_is_rejected(host_fixture):
    f=host_fixture;value=f.host.source_context('2026-10-29',G)
    assert all(v['status']=='UNKNOWN' for v in value['markets'].values())
    assert value['generation']==G and value['input_sha256']==I
    packet=reference(f.root/'wrong-overseas.json',dict(A_date='20261029',**FLAGS))
    f.host.binding['overseas']={'2026-10-30':packet}
    with pytest.raises(ValueError,match='OVERSEAS_DATE_CONFLICT'):f.host.source_context('2026-10-29',G)


def test_local_company_validator_requires_explicit_same_stock_date_context():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="""import assert from 'node:assert/strict';import {setCompanyContext,validateCompany,explanationFacts} from './research/stock_panel_collab_20261030/mac-host/company-local.mjs';const c={symbol:'001328.SZ',source_date:'2026-10-29',observation_date:'2026-10-30',generation:'g',input_sha256:'i'},x={...c,schema:'V4_RECEIVED_COMPANY_VIEW_V1',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,business:{summary:{value:null}},facts:[['营收',{value:null,unit:'元'}]]};assert.throws(()=>validateCompany(x,c.symbol));setCompanyContext(c);assert.strictEqual(validateCompany(x,c.symbol),x);assert.strictEqual(explanationFacts(x)[1][1].value,null);setCompanyContext({...c,source_date:'2026-10-28'});assert.throws(()=>validateCompany(x,c.symbol));"""
    subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)


def test_fixed_dot_builder_preserves_original46_and_minimal_host_seams(tmp_path):
    import os
    w=Path(__file__).resolve().parents[1]
    dot=Path(os.environ.get('DOT_FRAMEWORK_SOURCE_ROOT',w/'research/dashboard_framework_collab_20261030'))
    receipt=w/'research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json'
    if not dot.is_dir():pytest.skip('fixed46 source must be supplied explicitly')
    result=build(dot,tmp_path,receipt)
    for item in json.loads(receipt.read_text())['entries']:
        relative=Path(item['path']).relative_to('research/dashboard_framework_collab_20261030')
        assert (tmp_path/'workbench-host/dot'/relative).read_bytes()==(dot/relative).read_bytes()
    local=(tmp_path/'workbench-host/dot/shell/workbench.local.mjs').read_text()
    assert 'window.StockPanelHost.open(day,r,group)' in local
    assert 'loadInteractive(selected,++stockToken)' in local
    assert "from '../../company-local.mjs'" in local
    assert '/api/v4/research/workbench' in (tmp_path/'workbench.html').read_text()
    assert result['vendor_bytes_unchanged'] is True


def test_missing_chart_binding_returns_standard_empty_views_not_router500(host_fixture):
    f=host_fixture;f.product['original_charts']=None
    answer=f.host.chart_views('2026-10-29',G)
    assert answer['charts']['rows']==[] and answer['projections']['rows']==[]
    assert answer['charts']['status']=='UNKNOWN_CHART_BINDING'


def test_actual_bootstrap_completion_classification_refresh_clear_and_old_reply_guard():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=r"""import assert from 'node:assert/strict';import fs from 'node:fs';import {completionAction} from './research/stock_panel_collab_20261030/mac-host/completion-action.mjs';
const source=fs.readFileSync('research/stock_panel_collab_20261030/mac-host/bootstrap.mjs','utf8'),body=source.slice(source.indexOf("events.addEventListener('a_share_daily_completed'"),source.indexOf("\nwindow.addEventListener('pagehide'"));
const calls=[],events={addEventListener:(name,fn)=>events.receive=fn},context={source_date:'2026-10-29',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)},status={};let serial=1;const window={OriginalFullChart:{clear(){++serial;calls.push('clear')}}},completionCallback={refresh:()=>calls.push('refresh'),sourceChanged:()=>calls.push('rebind')},el=()=>status;
new Function('events','context','window','completionCallback','el','completionAction',body)(events,context,window,completionCallback,el,completionAction);
const e={schema_version:'v4.a_share.daily_completion.v1',status:'PARTIAL_WITH_ROWS',data_date:'20261029',source_generation:context.generation,input_sha256:context.input_sha256,event_id:'c'.repeat(64),manifest:{path:'mf',sha256:'d'.repeat(64)},artifact:{path:'art',sha256:'e'.repeat(64)},RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
events.receive({data:JSON.stringify(e)});assert.deepEqual(calls,['refresh']);const oldSerial=serial;events.receive({data:JSON.stringify({...e,source_generation:'f'.repeat(64)})});assert.deepEqual(calls,['refresh','clear','rebind']);assert.notEqual(serial,oldSerial);let oldRestored=false;if(serial===oldSerial)oldRestored=true;assert.equal(oldRestored,false);
events.receive({data:JSON.stringify({...e,data_date:'20261030'})});assert.equal(calls.length,3);events.receive({data:JSON.stringify({...e,input_sha256:null})});assert(status.textContent.includes('来源字段待核'));assert.equal(calls.length,3);
"""
    result=subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_mjs_static_service_still_requires_exact_path_and_hash_and_keeps_daily(tmp_path):
    import importlib.util
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    path=Path(__file__).resolve().parents[1]/'docs/handoffs/mac_framework_integration_20261030/deployed_api/research_panel_mount.py'
    spec=importlib.util.spec_from_file_location('mac_bound_static_profile',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'daily.html').write_text('accepted individual page');(tmp_path/'host.mjs').write_text('export const bound=true;');(tmp_path/'unlisted.mjs').write_text('not exported');
    items=[dict(path=name,sha256=hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()) for name in ['daily.html','host.mjs']]
    reference(tmp_path/'assets.json',dict(schema_version='research_panel.assets.v1',files=items))
    app=FastAPI();app.include_router(module.create_research_panel_router(tmp_path,tmp_path/'assets.json'));client=TestClient(app)
    result=client.get('/research-panel/host.mjs');assert result.status_code==200 and result.headers['content-type'].startswith('text/javascript')
    assert client.get('/research-panel/daily.html').text=='accepted individual page'
    assert client.get('/research-panel/unlisted.mjs').status_code==404
    (tmp_path/'host.mjs').write_text('changed');assert client.get('/research-panel/host.mjs').status_code==409


def test_projection_only_list_rates_and_review_enum_are_valid(host_fixture):
    f=host_fixture
    # A source exposing detail APIs must still never be called per stock by GET.
    f.source._a_daily_checkpoint_binding=lambda *a: (_ for _ in ()).throw(AssertionError('GET must not touch checkpoints'))
    rates={r['symbol']:{'original':{'d2':{'valid':3,'positive_fraction':0.0,'not_matured':1}}} for r in f.product['rows']}
    f.host.binding['statistics']={'2026-10-29':reference(f.root/'summary.json',dict(schema='V4_WORKBENCH_STATISTICS_V1',source_date='2026-10-29',generation=G,input_sha256=I,numeric_manifest=f.mf,rows=rates,**FLAGS))}
    answer=f.host.day('2026-10-29',G)
    assert answer['chart_review']=='UNKNOWN_NOT_REVIEWED' and answer['execution_status']=='DEFERRED_USER'
    assert answer['rows'][0]['history_rates']['original']['d2']['positive_fraction']==0
    f.host.day('2026-10-29',G)
    assert f.source.reads==1


def test_workflow_bad_node_is_isolated_and_clock_never_completes_missing_nodes(host_fixture):
    f=host_fixture
    f.host.binding['workflow_plan']=reference(f.root/'twenty.json',dict(stages=[dict(id=i,name=str(i),time_bjt='01:00',action='see evidence') for i in range(1,21)]))
    bad=reference(f.root/'bad.json',{});Path(bad['path']).write_text('drift')
    f.host.binding['workflow_execution']=reference(f.root/'executions.json',dict(observation_date='2026-10-30',nodes={'1':{'status':'PARTIAL'},'2':{'status':'COMPLETED','evidence':[bad]}},**FLAGS))
    answer=f.host.workflow('2026-10-29')['time_contract']['nodes']
    assert len(answer)==20 and answer[0]['execution_status']=='PARTIAL'
    assert answer[1]['execution_status']=='CANNOT_CONFIRM_BAD_RECEIPT'
    assert answer[2]['execution_status']=='DEFERRED_USER'
    assert answer[19]['execution_status']=='CANNOT_CONFIRM_NO_RECEIPT'


def test_same_day_module_versions_advance_independently(host_fixture):
    f=host_fixture;a=f.host.versions('2026-10-29',G)
    f.host.binding['japan']={'2026-10-30':reference(f.root/'jp.json',{'value':'new'})}
    b=f.host.versions('2026-10-29',G)
    assert b['modules']['context']!=a['modules']['context']
    assert all(b['modules'][k]==a['modules'][k] for k in ('list','statistics','observations','workflow'))
    f.host.binding['workflow_execution']=reference(f.root/'exec.json',dict(nodes={}))
    c=f.host.versions('2026-10-29',G)
    assert c['modules']['workflow']!=b['modules']['workflow']


def test_unique_anchors_fail_closed_and_build_is_byte_reproducible(tmp_path):
    import os
    from ops.build_mac_workbench import replace_once,replace_block
    with pytest.raises(ValueError,match='ANCHOR_COUNT'):replace_once('aa','a','b')
    with pytest.raises(ValueError,match='ANCHOR_COUNT'):replace_once('xx','a','b')
    with pytest.raises(ValueError,match='ANCHOR_ORDER'):replace_block('end start','start','end','x')
    dot=Path(os.environ['DOT_FRAMEWORK_SOURCE_ROOT']);receipt=Path(__file__).resolve().parents[1]/'research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json'
    one=tmp_path/'one';two=tmp_path/'two';build(dot,one,receipt);build(dot,two,receipt)
    before={str(p.relative_to(one)):p.read_bytes() for p in one.rglob('*') if p.is_file()}
    assert before=={str(p.relative_to(two)):p.read_bytes() for p in two.rglob('*') if p.is_file()}
    html=(one/'workbench.html').read_text();local=(one/'workbench-host/dot/shell/workbench.local.mjs').read_text()
    assert '<select id="stockSort" hidden' in html and 'data-stock-sort="d5"' in html
    assert 'pollStoredObservations' not in local
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    subprocess.run([node,'--check',str(one/'workbench-host/dot/shell/workbench.local.mjs')],check=True,capture_output=True)


def test_rate_sort_zero_unknown_n_and_group_selection():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="""import assert from 'node:assert/strict';import {sortHistoryRates,historyRate} from './research/stock_panel_collab_20261030/mac-host/rate-sort.mjs';const r=(symbol,value,n=2)=>({symbol,group_states:{original:'TRUE'},history_rates:{original:{d2:{valid:n,positive_fraction:value}}}}),rows=[r('missing',null),r('zero',0),r('half',.5),r('immature',0,0)];assert.deepEqual(sortHistoryRates(rows,'all','d2_asc').map(r=>r.symbol),['zero','half','missing','immature']);assert.deepEqual(sortHistoryRates(rows,'all','d2_desc').map(r=>r.symbol),['half','zero','missing','immature']);assert.equal(historyRate(rows[2],'nav_smallk','d2').valid,false);"""
    subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)


def test_workflow_future_date_does_not_reuse_other_day_receipts_and_not_due_expires(host_fixture):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    f=host_fixture
    f.host._clock=lambda:datetime(2026,10,30,17,0,tzinfo=ZoneInfo('Asia/Shanghai'))
    f.host.binding['workflow_plan']=reference(f.root/'plan.json',dict(stages=[dict(id=19,name='delivery',time_bjt='16:00',action='actual receipt required')]))
    f.host.binding['workflow_execution']=reference(f.root/'exec.json',dict(observation_date='2026-10-30',nodes={'19':{'status':'NOT_DUE','materials':[{'label':'original','url':'https://example.test/original'}]}}))
    assert f.host.workflow('2026-10-29')['time_contract']['nodes'][0]['execution_status']=='CANNOT_CONFIRM_OVERDUE'
    f.host.binding['observation_dates']['2026-10-29']={'date':'2026-11-02','authority':reference(f.root/'future-date.json',dict(source_date='2026-10-29',observation_date='2026-11-02'))}
    future=f.host.workflow('2026-10-29')['time_contract']['nodes'][0]
    assert future['execution_status']=='CANNOT_CONFIRM_BAD_RECEIPT' and future['materials']==[]


def test_actual_original_owner_failure_updates_workflow_version_and_never_claims_retry(host_fixture):
    f=host_fixture
    f.host.binding['workflow_plan']=reference(f.root/'plan.json',dict(stages=[dict(id=15,name='A day',time_bjt='15:40',action='original owner')]))
    receipts=f.root/'owner';receipts.mkdir()
    f.host.binding['workflow_receipt_sources']={'15':{'kind':'A_DAILY_PANEL_RECEIPT','root':str(receipts)}}
    a=f.host.versions('2026-10-29',G)
    reference(receipts/'a-20261030.json',dict(schema_version='v3.macos.research_panel_receipt.v1',target_date='20261030',lane='A',status='FAILED',error='SOP_REBIND_REQUIRED:000016.SZ',exit_code=1,production_allowed=False,buy_gate_updated=False,orders_sent=False))
    b=f.host.versions('2026-10-29',G);node=f.host.workflow('2026-10-29')['time_contract']['nodes'][0]
    assert a['modules']['workflow']!=b['modules']['workflow']
    assert node['execution_status']=='BLOCKED' and node['recorded_at'] is None and 'SOP_REBIND' in node['error']


def test_readonly_workbench_router_schema_and_source_date_query(host_fixture,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from infrastructure.research_workbench_host import create_workbench_router
    f=host_fixture;binding=reference(f.root/'binding.json',f.host.binding)
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',binding['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',binding['sha256'])
    app=FastAPI();app.include_router(create_workbench_router(f.source),prefix='/api/v4/research');client=TestClient(app)
    assert client.get('/api/v4/research/workbench/days/2026-10-29/versions').status_code==200
    assert client.get('/api/v4/research/workbench/workflow-contract?source_date=2026-10-29').json()['observation_date']=='2026-10-30'
    assert client.post('/api/v4/research/workbench/days/2026-10-29').status_code==405
    spec=app.openapi()['paths']['/api/v4/research/workbench/days/{source_date}/events']['get']
    assert [p['name'] for p in spec['parameters']]==['source_date']


def test_workflow_generic_evidence_bytes_pass_but_bad_sha_isolated(host_fixture):
    f=host_fixture
    f.host.binding['workflow_plan']=reference(f.root/'plan.json',dict(stages=[dict(id=i,name=str(i),time_bjt='01:00',action='generic attachments') for i in (1,2,4)]))
    refs=[]
    for name,raw in [('notes.md','已保存研究说明'.encode()),('archive.zip',b'PK\x03\x04\xff\xfe\x00\x81'),('bad.csv',b'code,value\na,1\n')]:
        path=f.root/name;path.write_bytes(raw);refs.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))
    Path(refs[-1]['path']).write_bytes(b'changed')
    f.host.binding['workflow_execution']=reference(f.root/'execution.json',dict(observation_date='2026-10-30',nodes={str(i):dict(status='PARTIAL',evidence=[r]) for i,r in zip((1,2,4),refs)}))
    nodes=f.host.workflow('2026-10-29')['time_contract']['nodes']
    assert [n['execution_status'] for n in nodes]==['PARTIAL','PARTIAL','CANNOT_CONFIRM_BAD_RECEIPT']
    assert 'SHA_DRIFT' in nodes[-1]['error'] and all(n['error'] is None for n in nodes[:2])


def test_actual_shared_scroll_geometry_at_1440_694_390(tmp_path):
    import os
    dot=Path(os.environ['DOT_FRAMEWORK_SOURCE_ROOT']);root=Path(__file__).resolve().parents[1]
    build(dot,tmp_path,root/'research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json')
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=r"""const {chromium}=require('/Users/lexi/.codex/skills/playwright-skill/node_modules/playwright');const fs=require('node:fs');const assert=require('node:assert/strict');const {pathToFileURL}=require('node:url');
const root=process.argv[1],html=fs.readFileSync(root+'/workbench.html','utf8').replace(/<script type="module" src="workbench-host\/bootstrap.mjs"><\/script>/,''),local=fs.readFileSync(root+'/workbench-host/dot/shell/workbench.local.mjs','utf8');fs.writeFileSync(root+'/geometry-fixture.html',html);
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--disable-background-networking']});try{const page=await browser.newPage();for(const width of [1440,694,390]){await page.setViewportSize({width,height:900});await page.goto(pathToFileURL(root+'/geometry-fixture.html').href);await page.evaluate(()=>{const list=document.getElementById('stockList');for(let i=0;i<20;i++){const row=document.createElement('button');row.className='stock-item stock-grid-row';for(const [j,text]of ['名称 002003','12.52','1.4%','1.7亿','50% n=2','25% n=4'].entries()){const cell=document.createElement('span');cell.textContent=text;cell.className=j===0?'stock-grid-name':j>3?'grid-rate':'';row.append(cell)}list.append(row)}window.rateClicks=[];for(const b of document.querySelectorAll('[data-stock-sort]'))b.onclick=()=>window.rateClicks.push(b.dataset.stockSort);});
await page.evaluate(code=>new Function('$',code)(id=>document.getElementById(id)),local.slice(local.indexOf("const stockGridViewport=$('stockGridViewport');")));
await page.locator('#stockGridViewport').hover();await page.mouse.wheel(350,0);await page.waitForFunction(()=>document.getElementById('stockGridViewport').scrollLeft>0);
let m=await page.evaluate(()=>{const viewport=document.getElementById('stockGridViewport'),d2=document.querySelector('[data-stock-sort=d2]').getBoundingClientRect(),row=document.querySelector('#stockList .grid-rate').getBoundingClientRect();return {offset:viewport.scrollLeft,innerOffset:document.getElementById('stockList').scrollLeft,headerX:d2.x,rowX:row.x}});assert(m.offset>0);assert.equal(m.innerOffset,0);assert(Math.abs(m.headerX-m.rowX)<1,JSON.stringify({width,...m}));
await page.locator('#showStockRates').click();await page.waitForFunction(()=>{const e=document.getElementById('stockGridViewport');return Math.abs(e.scrollLeft-(e.scrollWidth-e.clientWidth))<1});for(const h of ['d2','d5']){const box=await page.locator('[data-stock-sort='+h+']').boundingBox(),vp=await page.locator('#stockGridViewport').boundingBox();assert(box.x>=vp.x&&box.x+box.width<=vp.x+vp.width+1,JSON.stringify({width,h,box,vp}));await page.mouse.click(box.x+box.width/2,box.y+box.height/2)}assert.deepEqual(await page.evaluate(()=>window.rateClicks),['d2','d5']);await page.locator('#showStockNames').click();await page.waitForFunction(()=>document.getElementById('stockGridViewport').scrollLeft===0);assert.equal(await page.locator('[data-stock-sort=name]').isVisible(),true);console.log(JSON.stringify({width,...m,clicks:['d2','d5'],nameReturn:true}));}await page.close();}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});"""
    result=subprocess.run([node,'-e',script,str(tmp_path)],cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert all(f'"width":{w}' in result.stdout for w in (1440,694,390))


def test_actual_context_failure_identity_and_stale_response_clear_only_current_cards():
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script=r"""import assert from 'node:assert/strict';import fs from 'node:fs';
const raw=fs.readFileSync('research/stock_panel_collab_20261030/mac-host/bootstrap.mjs','utf8'),body=raw.slice(raw.indexOf('function sourceContext('),raw.indexOf('\nfunction showStatistics('));
const node=(value='')=>({value,children:[],get textContent(){return this.value+this.children.map(c=>c.textContent).join('')},set textContent(v){this.value=v;this.children=[]},replaceChildren(){this.value='';this.children=[]}});const pending=[],cards=node('OLD_ACCEPTED_JP'),el=()=>cards,add=(p,t,text)=>{const n=node(text??'');p.children.push(n);return n};
const day={source_date:'2026-10-29',observation_date:'2026-10-30',generation:'a',input_sha256:'b'},good={...day,markets:{JP:{summary:'NEW_ACCEPTED_JP',status:'DATED'},KR:{summary:'NEW_ACCEPTED_KR',status:'DATED'}}};
const factory=new Function('fetch','el','add',`let context=null,activeDay=${JSON.stringify(day)},contextSerial=0,contextReply=${JSON.stringify(good)};${body};return {read:sourceContext,show(v){contextReply=v;paintContext()},setDay(v){activeDay=v},reply(){return contextReply}}`);
const host=factory(()=>new Promise((resolve,reject)=>pending.push({resolve,reject})),el,add);host.show(good);assert(cards.textContent.includes('NEW_ACCEPTED_JP'));
let p=host.read(day,true);pending.shift().resolve({ok:false,status:409});await p;assert(cards.textContent.includes('CANNOT_CONFIRM'));assert(!cards.textContent.includes('NEW_ACCEPTED_JP'));assert.equal(host.reply(),null);
host.show(good);p=host.read(day,true);pending.shift().resolve({ok:true,json:async()=>({...good,observation_date:'2026-10-29'})});await p;assert(cards.textContent.includes('SOURCE_CONTEXT_IDENTITY_CONFLICT'));assert(!cards.textContent.includes('NEW_ACCEPTED_JP'));
// An older failed request must not erase a later successful response.
const older=host.read(day,true),oldRequest=pending.shift(),newer=host.read(day,true),newRequest=pending.shift();newRequest.resolve({ok:true,json:async()=>good});await newer;oldRequest.resolve({ok:false,status:409});await older;assert(cards.textContent.includes('NEW_ACCEPTED_JP'));
// An old identity-mismatched response is also harmless after newer success.
const stale=host.read(day,true),staleRequest=pending.shift(),fresh=host.read(day,true),freshRequest=pending.shift();freshRequest.resolve({ok:true,json:async()=>good});await fresh;staleRequest.resolve({ok:true,json:async()=>({...good,generation:'wrong'})});await stale;assert(cards.textContent.includes('NEW_ACCEPTED_JP'));
// A changed active date is an independent guard, even without another fetch.
p=host.read(day,true);const switched=pending.shift();host.setDay({...day,source_date:'2026-10-30'});cards.textContent='OTHER_DAY_CURRENT_CARDS';switched.reject(Error('old request failed'));await p;assert.equal(cards.textContent,'OTHER_DAY_CURRENT_CARDS');
"""
    result=subprocess.run([node,'--input-type=module','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
