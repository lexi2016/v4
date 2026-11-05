import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {receivedView,renderReceivedResearch,safeSourceUrl,createReceivedCompanyRefresh} from '../research/stock_panel_collab_20261030/mac-host/received-research.mjs';

const flags={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
class Element{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.text='';this.dataset={};this.attributes={};}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(child=>child.textContent).join('');}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.text='';this.children=[...nodes];}
  setAttribute(key,value){this.attributes[key]=value;}
}
const documentFixture=()=>{const nodes=new Map(['companySummary','companyMetrics','companyEvidence'].map(key=>[key,new Element()]));return {createElement:tag=>new Element(tag),getElementById:key=>nodes.get(key)};};
function fixture(symbol='300149.SZ',role='technical_observe'){
  const generation='a'.repeat(64),input='b'.repeat(64);
  const summary={source_date:'20261104',target_date:'20261105',generation,input_sha256:input,scope_count:238,
    strict_full_chain_certified_count:0,technical_observe_count:3,wait_for_trigger_count:3,
    themes:[{theme:'医药',technical_observe:[{symbol:'300149.SZ',name:'睿智医药'}],wait_for_trigger:[{symbol:'688575.SH',name:'亚辉龙'}]},
      {theme:'消费',technical_observe:[{symbol:'300997.SZ',name:'欢乐家'}],wait_for_trigger:[{symbol:'300856.SZ',name:'科思股份'}]},
      {theme:'软件',technical_observe:[{symbol:'002777.SZ',name:'久远银海'}],wait_for_trigger:[{symbol:'688111.SH',name:'金山办公'}]}],
    original_producer_status_counts:{COMPLETED:232,PARTIAL:6},specified_primary_page_check_count:13,...flags};
  return {schema:'V4_RECEIVED_COMPANY_VIEW_V1',symbol,source_date:'2026-11-04',observation_date:'2026-11-05',generation,input_sha256:input,...flags,
    received_materials:{symbol,data_date:'20261104',source_generation:generation,input_sha256:input,...flags,received_batch_summary:summary,
      received_fundamentals:{business:'收到的业务<script>alert(1)</script>',profit_driver:'收到的利润原文',status:'PARTIAL',as_of:'2026-11-04T23:58:08+08:00',missing_inputs:['估值待核'],sources:[{title:'季报',url:'javascript:alert(1)'}]},
      secondary_screen:{source_date:'20261104',target_date:'20261105',status:'CANNOT_CONFIRM',role,errors:[],reference_fields:{volume_to_current_MA5:.8295,volume_to_prior_MA5:.9075},received_record:{full_chain_status:'CANNOT_CONFIRM',b1_status:'CANNOT_CONFIRM_DYNAMIC_REF_IMPLEMENTATION_DEFECT'}},
      daily_performance:{symbol,source_date:'20261104',target_date:'20261105',source_generation:generation,current_target_day_return_pct:null,current_target_day_performance_status:'NOT_MATERIALIZED_NOT_READ',close:8.9,day_return_pct:1.23,volume_to_current_MA5:.83,...flags}}};
}

test('three representative views render research roles, source day, canonical/P5 bases and strict zero',()=>{
  for(const [symbol,role]of [['300149.SZ','technical_observe'],['300856.SZ','wait_for_trigger'],['688111.SH','wait_for_trigger']]){
    const doc=documentFixture(),value=fixture(symbol,role);assert.equal(renderReceivedResearch(value,doc),true);
    const text=['companySummary','companyMetrics','companyEvidence'].map(id=>doc.getElementById(id).textContent).join('');
    for(const part of [symbol,'完整链0已确认','3技术观察 + 3候触发','行情截至11/04收盘 / 目标观察11/05','原包状态 PARTIAL','232','6','13','Canonical D量/含D近5交易日均量','P5 D量/此前5均量','目标11/05盘中未读取','CANNOT_CONFIRM','亚辉龙','科思股份','金山办公'])assert.ok(text.includes(part),part);
    assert.ok(text.includes(role==='technical_observe'?'技术观察':'候触发'));
    assert.ok(text.includes('<script>alert(1)</script>')); // literal text nodes, no HTML parsing.
    const walk=n=>[n,...n.children.flatMap(walk)];assert.equal(walk(doc.getElementById('companyEvidence')).some(n=>n.tagName==='a'),false);
  }
});
test('source URLs restrict protocol and credentials; identities reject stale target and false full-chain claims',()=>{
  assert.equal(safeSourceUrl('javascript:alert(1)'),null);assert.equal(safeSourceUrl('data:text/html,test'),null);assert.equal(safeSourceUrl('https://user:pass@example.org'),null);
  assert.equal(safeSourceUrl('https://example.org/report.pdf'),'https://example.org/report.pdf');
  for(const mutate of [v=>v.received_materials.received_batch_summary.target_date='20261106',v=>v.received_materials.secondary_screen.received_record.full_chain_status='PASS',v=>v.received_materials.daily_performance.current_target_day_return_pct=2]){
    const value=fixture();mutate(value);assert.throws(()=>receivedView(value),/IDENTITY_CONFLICT/);
  }
  assert.equal(receivedView({}),null);
});
test('company-material completion refresh rejects stale stock/day and later same-symbol request',async()=>{
  let context=fixture(),serial=0,applied=0,resolve;
  const refresh=createReceivedCompanyRefresh({getContext:()=>context,begin:()=>++serial,isCurrent:ticket=>ticket===serial,
    validate:()=>{},fetchCompany:()=>new Promise(done=>resolve=done),apply:()=>applied++});
  const event={company_materials:{sha256:'c'.repeat(64)},data_date:'20261104',source_generation:context.generation,input_sha256:context.input_sha256};
  let promise=refresh(event);context=fixture('300856.SZ');++serial;resolve(fixture());assert.equal(await promise,false);assert.equal(applied,0);
  context=fixture();promise=refresh(event);++serial;resolve(fixture());assert.equal(await promise,false); // away/back or newer shell request.
  promise=refresh(event);resolve(fixture());assert.equal(await promise,true);assert.equal(applied,1);
  context=fixture();context.source_date='2026-10-29';assert.equal(await refresh(event),false);assert.equal(applied,1);
});
test('current refresh failures clear LOADING or READY materials; stale failures preserve newer selection', {skip:!process.env.V4_COMPANY_LOCAL_MODULE},async()=>{
  const {beginCompanyRequest,isCurrentCompanyRequest,renderCompanyStatus,validateCompany}=await import(pathToFileURL(process.env.V4_COMPANY_LOCAL_MODULE).href);
  for(const state of ['LOADING','READY'])for(const failure of ['fetch','validate','missing-received']){
    const doc=documentFixture();let context=fixture(),reject,resolve;
    renderCompanyStatus(doc,state,context.symbol);
    if(state==='READY')for(const id of ['companySummary','companyMetrics','companyEvidence'])doc.getElementById(id).textContent='old material';
    const refresh=createReceivedCompanyRefresh({getContext:()=>context,begin:beginCompanyRequest,isCurrent:isCurrentCompanyRequest,
      validate:validateCompany,fetchCompany:()=>new Promise((done,fail)=>{resolve=done;reject=fail;}),apply:()=>assert.fail('must not apply failed response'),
      onError:identity=>renderCompanyStatus(doc,'ERROR',identity.symbol)});
    const event={company_materials:{sha256:'c'.repeat(64)},data_date:'20261104',source_generation:context.generation,input_sha256:context.input_sha256};
    const pending=refresh(event);
    if(failure==='fetch')reject(Error('network failure'));
    else if(failure==='validate'){const value=fixture();value.generation='wrong';resolve(value);}
    else{const value=fixture();delete value.received_materials;resolve(value);}
    assert.equal(await pending,false);
    for(const id of ['companySummary','companyMetrics']){
      assert.equal(doc.getElementById(id).dataset.companyState,'ERROR',state+'/'+failure);
      assert.ok(doc.getElementById(id).textContent.includes('CANNOT_CONFIRM'));
      assert.ok(!doc.getElementById(id).textContent.includes('old material'));
    }
    assert.equal(doc.getElementById('companyEvidence').textContent,'');
  }
  for(const change of ['stock','date','away-back']){
    const doc=documentFixture();let context=fixture(),reject;
    const refresh=createReceivedCompanyRefresh({getContext:()=>context,begin:beginCompanyRequest,isCurrent:isCurrentCompanyRequest,
      validate:validateCompany,fetchCompany:()=>new Promise((done,fail)=>reject=fail),apply:()=>assert.fail('stale apply'),
      onError:identity=>renderCompanyStatus(doc,'ERROR',identity.symbol)});
    const pending=refresh({company_materials:{},data_date:'20261104',source_generation:context.generation,input_sha256:context.input_sha256});
    context=fixture(change==='stock'?'300856.SZ':'300149.SZ');if(change==='date')context.source_date='2026-11-03';
    beginCompanyRequest(context);renderCompanyStatus(doc,'READY',context.symbol);
    for(const id of ['companySummary','companyMetrics','companyEvidence'])doc.getElementById(id).textContent='new selection material';
    reject(Error('late old failure'));assert.equal(await pending,false);
    for(const id of ['companySummary','companyMetrics','companyEvidence'])assert.equal(doc.getElementById(id).textContent,'new selection material',change);
    assert.equal(doc.getElementById('companySummary').dataset.companyState,'READY');
  }
});
test('actual staged 238 rows and 15+1 quarantines remain distinct from canonical quote', {skip:!process.env.V4_RECEIVED_STAGE},()=>{
  const plan=JSON.parse(fs.readFileSync(process.env.V4_RECEIVED_STAGE+'/PUBLICATION_PLAN.json','utf8'));
  const shards=Object.entries(plan.immutable_files).filter(([path])=>!path.endsWith('/index.json')).map(([,ref])=>JSON.parse(fs.readFileSync(ref.path,'utf8')));
  assert.equal(shards.length,238);assert.equal(plan.summary.strict_full_chain_certified_count,0);assert.equal(plan.summary.specified_primary_page_check_count,13);
  assert.equal(plan.summary.technical_observe_count,3);assert.equal(plan.summary.wait_for_trigger_count,3);
  assert.equal(shards.filter(row=>row.secondary_screen.errors.includes('D_CLOSE_MISMATCH_CANONICAL')).length,15);
  assert.equal(shards.filter(row=>row.secondary_screen.errors.includes('MISSING_D_KEY_FEATURE')).length,1);
  for(const material of shards){
    assert.equal(material.daily_performance.current_target_day_return_pct,null);
    assert.equal(material.secondary_screen.received_record.full_chain_status,'CANNOT_CONFIRM');
    if(material.secondary_screen.errors.length)assert.ok(Object.values(material.secondary_screen.reference_fields).every(value=>value===null));
    const value={schema:'V4_RECEIVED_COMPANY_VIEW_V1',symbol:material.symbol,source_date:'2026-11-04',observation_date:'2026-11-05',generation:material.source_generation,input_sha256:material.input_sha256,received_materials:material,...flags};
    assert.ok(receivedView(value));
    if(['300149.SZ','300856.SZ','688111.SH'].includes(material.symbol))assert.ok(renderReceivedResearch(value,documentFixture()));
  }
});
