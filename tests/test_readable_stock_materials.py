"""C9 bound read projections and initial-SSE race; no financial execution."""
import hashlib,json,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from infrastructure.research_lane_source import ResearchLaneSource
NODE='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'

def fixture(tmp_path):
    mf={'path':'numeric.json','sha256':'a'*64};stats={'asof':'2026-10-29','groups':[]}
    detail={'status':'READY','manifest':mf,'source_generation':'b'*64,'source_identity':{'input_sha256':'c'*64},'row':{'statistics':stats},'rows':[{'symbol':'002003.SZ'}]}
    identity=dict(data_date='20261029',numeric_manifest=mf,source_generation='b'*64,input_sha256='c'*64)
    materials=dict(schema_version='v4.a_share.company_materials.v1',symbol='002003.SZ',business_reported={'value':'钮扣与拉链'},**identity)
    mi=dict(schema_version='v4.a_share.company_materials_index.v1',items={'002003.SZ':{'path':'material'}},**identity)
    case=dict(schema_version='v4.a_share.event_cases.v1',symbol='002003.SZ',data_date='20261029',numeric_manifest=mf,statistics_sha256=hashlib.sha256(json.dumps(stats,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),projection={'sha256':'d'*64},groups={'original':{'d2':{'cases':[{'event_date':'20161129','classification':'NEGATIVE'},{'event_date':'20261029','classification':'NOT_MATURED'}]}}})
    ei=dict(schema_version='v4.a_share.event_cases_index.v1',items={'002003.SZ':{'path':'case'}},**identity)
    index=dict(company_materials={'20261029':{'path':'mi'}},event_cases={'20261029':{'path':'ei'}});(tmp_path/'index.json').write_text(json.dumps(index))
    objects=dict(material=materials,mi=mi,case=case,ei=ei)
    reader=SimpleNamespace(read_a_daily_product=lambda *args,**kw:detail,_a_product_root=lambda:tmp_path,_a_product_reference=lambda ref:objects[ref['path']])
    return reader,objects

def test_company_projection_keeps_received_fields_and_rejects_stale_or_old_statistics(tmp_path):
    source,objects=fixture(tmp_path)
    result=ResearchLaneSource.read_a_daily_company_materials(source,'20261029','002003.SZ',generation='b'*64,input_sha256='c'*64)
    assert result['status']=='PARTIAL_RECEIVED' and result['materials']['business_reported']['value']=='钮扣与拉链'
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY'):ResearchLaneSource.read_a_daily_company_materials(source,'20261029','002003.SZ',generation='0'*64)
    objects['mi']['numeric_manifest']={'path':'old','sha256':'a'*64}
    with pytest.raises(ValueError,match='BINDING_CONFLICT'):ResearchLaneSource.read_a_daily_company_materials(source,'20261029','002003.SZ')
    objects['mi']['numeric_manifest']=objects['material']['numeric_manifest'];objects['material']['same_event_returns']={}
    with pytest.raises(ValueError,match='SHARD_IDENTITY'):ResearchLaneSource.read_a_daily_company_materials(source,'20261029','002003.SZ')

def test_all_event_cases_keep_losses_and_immature_and_reject_stats_drift(tmp_path):
    source,objects=fixture(tmp_path)
    value=ResearchLaneSource.read_a_daily_event_cases(source,'20261029','002003.SZ')
    assert [v['classification'] for v in value['cases']]==['NEGATIVE','NOT_MATURED']
    objects['case']['statistics_sha256']='0'*64
    with pytest.raises(ValueError,match='SHARD_CONFLICT'):ResearchLaneSource.read_a_daily_event_cases(source,'20261029','002003.SZ')

def test_missing_event_shard_is_gap_not_zero_success_rate(tmp_path):
    source,objects=fixture(tmp_path);objects['ei']['items']={}
    value=ResearchLaneSource.read_a_daily_event_cases(source,'20261029','002003.SZ')
    assert value['status']=='NOT_MATERIALIZED' and 'positive_fraction' not in value

def test_initial_sse_retains_inflight_chart_binding_and_null_rates():
    script=r'''
const assert=require('assert'),p=require('./research-panel/numeric283-panel.js');
const x={data_date:'20261029',source_generation:'b'.repeat(64),source_identity:{input_sha256:'c'.repeat(64)},manifest:{path:'mf',sha256:'d'.repeat(64)},artifact:{path:'art',sha256:'e'.repeat(64)}};
assert.strictEqual(p.keepCurrentProductBinding(x,JSON.parse(JSON.stringify(x))),x);
const changed=JSON.parse(JSON.stringify(x));changed.manifest.sha256='f'.repeat(64);assert.strictEqual(p.keepCurrentProductBinding(x,changed),changed);
const view=p.statisticsPresentation({historical_coverage:{evaluated_count:5266,evaluated_dates:Array(5266).fill('20261029'),unknown_by_group:{original:1}}},x,'002003.SZ');
assert(view.coverageSummary.length<100);assert(!view.coverageSummary.includes('标签完整认证'));
assert(view.groups.every(g=>g.horizons.every(h=>h.rate==='数据不足')));assert.strictEqual(view.groups[0].summary,'数据不足');
'''
    subprocess.run([NODE,'-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)

def test_control_waits_for_real_absent_before_bootstrap(monkeypatch):
    import importlib.util
    p=Path(__file__).resolve().parents[1]/'docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/control_c9.py'
    spec=importlib.util.spec_from_file_location('control_c9',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    seen=iter([SimpleNamespace(returncode=0,stderr=''),SimpleNamespace(returncode=113,stderr='Could not find service')]);calls=[]
    def run(args,**kwargs):calls.append(args);return next(seen)
    monkeypatch.setattr(module.subprocess,'run',run);monkeypatch.setattr(module.time,'sleep',lambda _:None)
    module.wait_absent('gui/501/test',timeout=1)
    assert len(calls)==2 and all(c[:2]==['launchctl','print'] for c in calls)


def test_code_map_footer_creates_same_origin_http_link_and_keeps_scheme_guard():
    script=r'''
const assert=require('assert'),fs=require('fs');const source=fs.readFileSync('./research-panel/numeric283-panel.js','utf8');
const created=[],add=(host,tag,label)=>{const e={tag,label};created.push(e);return e};
const helper=source.split('\n').find(line=>line.includes('function link(host,url,label)'));
const link=new Function('add','return ('+helper.trim()+')')(add);
const footer={},windowObject={location:{origin:'http://127.0.0.1:61451'}};
const call=source.split('\n').find(line=>line.includes("'开发图谱'"));eval(call);
assert.strictEqual(created.length,1);assert.strictEqual(created[0].label,'开发图谱');
assert.strictEqual(created[0].href,'http://127.0.0.1:61451/research-panel/code-map/index.html');
assert.strictEqual(created[0].rel,'noopener');
for(const bad of ['javascript:alert(1)','//elsewhere.invalid/map','/\\elsewhere.invalid'])assert.strictEqual(link(footer,bad,'bad'),undefined);
assert.strictEqual(created.length,1);
'''
    subprocess.run([NODE,'-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)


def test_report_library_remains_connected_on_failed_unmaterialized_and_stale_material_loads():
    script=r'''
const assert=require('assert'),fs=require('fs');const source=fs.readFileSync('./research-panel/numeric283-panel.js','utf8');
const body=source.slice(source.indexOf('async function showCompanyMaterials('),source.indexOf('\n    function clearOriginalChart'));
class El{constructor(id){this.id=id;this.children=[];this.hidden=true;}appendChild(n){n.remove();this.children.push(n);n.parent=this;return n;}remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null;}}replaceChildren(){for(const n of [...this.children])n.remove();}set textContent(v){this.replaceChildren();this.text=v;}}
function harness(){const root=new El('root'),host=root.appendChild(new El('dailyCompanyMaterials')),reports=root.appendChild(new El('dailyReceivedReports')),library=reports.appendChild(new El('relatedReports'));const doc={getElementById(id){function find(n){return n.id===id?n:n.children.map(find).find(Boolean)}return find(root)}};const waiting=[];const fetch=()=>new Promise((resolve,reject)=>waiting.push({resolve,reject}));const add=(host,tag,text)=>{const n=new El('');n.text=text;return host.appendChild(n)};
const api=new Function('document','windowObject','add',`let chartRequest=1;const payloadMetadata={data_date:'20261029',source_generation:'b',source_identity:{input_sha256:'c'}},chartController={signal:null},sameRef=()=>true;${body};return {show:showCompanyMaterials,advance:()=>++chartRequest};`)(doc,{fetch},add);
return {api,waiting,doc,library,reports,assertConnected(){assert.strictEqual(doc.getElementById('relatedReports'),library);assert.strictEqual(library.parent,reports);assert.strictEqual(reports.hidden,false)}};}
(async()=>{
const failed=harness(),f=failed.api.show('002003.SZ',1);failed.assertConnected();failed.waiting[0].reject(new Error('GET failed'));await f;failed.assertConnected();
const missing=harness(),m=missing.api.show('002003.SZ',1);missing.assertConnected();missing.waiting[0].resolve({json:async()=>({status:'NOT_MATERIALIZED'})});await m;missing.assertConnected();
const rapid=harness(),a=rapid.api.show('002003.SZ',1);rapid.assertConnected();rapid.api.advance();const b=rapid.api.show('600025.SH',2);rapid.assertConnected();rapid.waiting[0].resolve({json:async()=>({status:'PARTIAL_RECEIVED'})});await a;rapid.assertConnected();rapid.waiting[1].reject(new Error('B failed'));await b;rapid.assertConnected();
})();
'''
    subprocess.run([NODE,'-e',script],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)


def _load_control_for_test():
    import importlib.util
    p=Path(__file__).resolve().parents[1]/'docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/control_c9.py'
    spec=importlib.util.spec_from_file_location('c9_control_delta',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_publisher_uses_sha_bound_existing_main_owner_not_api_profile(monkeypatch):
    module=_load_control_for_test();main='/fixture/C8-main/app/ops/research_panel_daily_product.py';calls=[];owner=SimpleNamespace()
    monkeypatch.setattr(module,'sha',lambda path:'a'*64 if str(path)==main else '0'*64)
    loader=SimpleNamespace(exec_module=lambda value:calls.append(('load',value)))
    monkeypatch.setattr(module.importlib.util,'spec_from_file_location',lambda name,path:(calls.append(('path',str(path))) or SimpleNamespace(loader=loader)))
    monkeypatch.setattr(module.importlib.util,'module_from_spec',lambda spec:owner)
    assert module.load_publisher({'owner_publisher':{'path':main,'sha256':'a'*64}}) is owner
    assert calls==[('path',main),('load',owner)]
    with pytest.raises(ValueError,match='MAIN_OWNER_SHA_DRIFT'):module.load_publisher({'owner_publisher':{'path':main,'sha256':'b'*64}})
    assert len(calls)==2


def test_only_rollback_may_restore_after_failed_bootout_when_service_is_really_absent(monkeypatch):
    module=_load_control_for_test();calls=[]
    absent=SimpleNamespace(returncode=113,stderr='Could not find service');present=SimpleNamespace(returncode=0,stderr='');stop_failed=SimpleNamespace(returncode=113,stderr='already absent')
    responses=iter([stop_failed,absent,absent])
    def run(args,**kwargs):calls.append(args);return next(responses)
    monkeypatch.setattr(module.subprocess,'run',run)
    module.stop_and_wait_absent('gui/501/test',True)
    assert [r[1] for r in calls]==['bootout','print','print']
    responses=iter([stop_failed]);calls.clear()
    with pytest.raises(RuntimeError,match='GRACEFUL_BOOTOUT'):module.stop_and_wait_absent('gui/501/test',False)
    assert [r[1] for r in calls]==['bootout']
    responses=iter([stop_failed,present]);calls.clear()
    with pytest.raises(RuntimeError,match='GRACEFUL_BOOTOUT'):module.stop_and_wait_absent('gui/501/test',True)
    assert [r[1] for r in calls]==['bootout','print']
