import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {createFormulaF10Cards, formulaF10CardContent, formulaCompanyResearchCardContent, isFormulaF10Completion, validateFormulaCompanyResearch, validateFormulaF10} from '../../apps/web/public/research-panel/workbench-host/dot/shell/formula-f10.mjs';

const day = {source_date:'2026-11-13',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)};
const ref = {path:'/f10-snapshot',sha256:'c'.repeat(64)};
const response = (symbol, status, fields={}) => ({status,symbol,data_date:'20261113',source_generation:day.generation,
  input_sha256:day.input_sha256,receipt:ref,stock_ref:ref,historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,
  orders_sent:false,f10:{source_text_sha256:'d'.repeat(64),captured_at:'2026-11-13T09:25:09+00:00',source_updated_date:'2026-11-13',
    finance_updated_date:'20261026', industry:{tdx_finance_industry_code:9},concept_status:'OBSERVED',concepts:[{name:'测试概念'}],
    financials:{report_period:'2026-09-30',revenue_text:'2.1亿',net_profit_text:'1.1亿',holder_count:1234},
    source_detail:{main_business:'仪器研发。',shareholder_record_date:'2026-09-30'},...fields}});

const researchDay = {...day,source_date:'2026-11-19',observation_date:'2026-11-20',
  generation:'f'.repeat(64),input_sha256:'e'.repeat(64),numeric_manifest:{path:'/numeric/20261119',sha256:'1'.repeat(64)},
  formula_groups:{artifact:{sha256:'2'.repeat(64)}},rows:Array.from({length:29},()=>({}))};
function companyResearch(symbol,business) {
  const roster=researchDay.formula_groups.artifact.sha256, owner={path:`/owner/${symbol}`,sha256:'3'.repeat(64)};
  const scope={schema:'V4_FORMULA_GROUP_SCOPED_IMPORT_V1',source_date:'20261119',observation_date:'20261120',
    source_generation:researchDay.generation,input_sha256:researchDay.input_sha256,numeric_manifest:researchDay.numeric_manifest,
    roster_sha256:roster,candidate_count:29};
  const membership={symbol,source_date:'20261119',observation_date:'20261120',roster_sha256:roster,owner_row_ref:owner};
  return {schema:'V4_RECEIVED_COMPANY_VIEW_V1',symbol,source_date:researchDay.source_date,observation_date:researchDay.observation_date,
    generation:researchDay.generation,input_sha256:researchDay.input_sha256,numeric_manifest:researchDay.numeric_manifest,
    company_scope_status:'FORMULA_ROSTER_EXACT_MATCH',formula_roster_sha256:roster,RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,
    received_materials:{symbol,data_date:'20261119',
      source_generation:researchDay.generation,input_sha256:researchDay.input_sha256,numeric_manifest:researchDay.numeric_manifest,
      RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
      formula_group_scope:scope,formula_group_membership:membership,
      business_reported:{value:business,evidence_status:'RECEIVED_RESEARCH_NOT_FULLY_VERIFIED'},
      received_fundamentals:{status:'PARTIAL',evidence_status:'RECEIVED_RESEARCH_NOT_FULLY_VERIFIED',
        business,latest_financial_period:'2026Q3_YTD'},
      financials_reported:{latest_report_period:'2026Q3_YTD'},shareholders_reported:{},
      received_batch_summary:{package_id:'V4_A_FORMULA_D20261119_O20261120_CHAT_RESEARCH_V2'},source_refs:{fundamentals:owner}}};
}

test('F10 cards keep the source accounting labels and distinguish exact text from source gaps', () => {
  const value = response('603658.SH','OBSERVED');
  const content = formulaF10CardContent(validateFormulaF10(value,day,value.symbol).f10);
  assert.ok(content.company.includes('主营业务：仪器研发。'));
  assert.ok(content.company.includes('行业：通达信行业代码 9 · 名称未映射'));
  assert.ok(content.company.some(line => line.includes('2026-11-13 17:25 上海')));
  assert.ok(content.financial.includes('净利润：1.1亿'));
  assert.ok(content.financial.includes('股东人数：1,234 · 统计日 2026-09-30'));
  assert.ok(content.financial.every(line => !line.includes('归母')));
  assert.throws(() => validateFormulaF10(value,day,'300015.SZ'), /IDENTITY_CONFLICT/);
  assert.throws(() => validateFormulaF10({...value,data_date:'20261112'},day,value.symbol), /IDENTITY_CONFLICT/);
  assert.throws(() => validateFormulaF10({...value,input_sha256:'e'.repeat(64)},day,value.symbol), /IDENTITY_CONFLICT/);
  assert.ok(formulaF10CardContent({concepts:[{name:'概念文字',desc:'不转成主营'}]}).company[0].includes('未提供'));
});

test('the same-date exact 29-stock company return is visible with honest PARTIAL finance status', () => {
  const cases=[
    ['001328.SZ','牙膏、牙刷和口腔护理产品。'],
    ['688728.SH','CIS及显示驱动芯片研发和制造。'],
    ['000410.SZ','机床及高端装备制造。'],
  ];
  for (const [symbol,business] of cases) {
    const company=validateFormulaCompanyResearch(companyResearch(symbol,business),researchDay,symbol);
    const content=formulaCompanyResearchCardContent(company,'NOT_MATERIALIZED');
    assert.ok(content.company.some(line=>line===`研究回传主营：${business}`));
    assert.ok(content.company.some(line=>line.includes('PARTIAL')));
    assert.ok(content.company.some(line=>line.includes('V4_A_FORMULA_D20261119_O20261120_CHAT_RESEARCH_V2')));
    assert.ok(content.company.some(line=>line.includes('FORMULA_ROSTER_EXACT_MATCH · 29 只研究范围')));
    assert.ok(content.financial.some(line=>line.includes('未提供可确认数值')));
    assert.ok(content.financial.some(line=>line.includes('待核')));
  }
  const value=companyResearch('000410.SZ','机床及高端装备制造。');
  assert.throws(()=>validateFormulaCompanyResearch({...value,generation:'4'.repeat(64)},researchDay,'000410.SZ'),/IDENTITY_CONFLICT/);
  assert.throws(()=>validateFormulaCompanyResearch({...value,formula_roster_sha256:'5'.repeat(64)},researchDay,'000410.SZ'),/IDENTITY_CONFLICT/);
  assert.throws(()=>validateFormulaCompanyResearch({...value,received_materials:{...value.received_materials,source_generation:'6'.repeat(64)}},researchDay,'000410.SZ'),/IDENTITY_CONFLICT/);
});

function testDocument() {
  const records = new Map();
  const make = () => ({children:[], dataset:{}, removeAttribute(){delete this.dataset.companySymbol;},setAttribute(){},
    replaceChildren(...items){this.children=items;},after(item){records.set(item.id,item);},append(...items){this.children.push(...items);},before(){}});
  for (const id of ['companySummary','companyMetrics']) records.set(id,Object.assign(make(),{id}));
  const details = make();
  records.set('companyEvidence',{closest:()=>details});
  return {getElementById:id=>records.get(id),createElement:make};
}

test('a late previous-symbol F10 response cannot restore content that was cleared on switch', async () => {
  const document = testDocument();
  const requests = new Map();
  const cards = createFormulaF10Cards(document,(url,signal)=>new Promise(resolve=>requests.set(url,{signal,resolve})));
  cards.configure(true);
  const summary = document.getElementById('formulaCompanySummary');
  const previous = cards.show(day,'603658.SH','/f10/603658.SH');
  const gap = cards.show(day,'300015.SZ','/f10/300015.SZ');
  assert.equal(requests.get('/f10/603658.SH').signal.aborted,true);
  requests.get('/f10/300015.SZ').resolve(response('300015.SZ','CANNOT_CONFIRM_SOURCE_GAP'));
  await gap;
  requests.get('/f10/603658.SH').resolve(response('603658.SH','OBSERVED'));
  await previous;
  assert.equal(summary.dataset.companySymbol,'300015.SZ');
  assert.match(summary.children[0].textContent,/300015\.SZ.*缺少可用快照/);
  const next = cards.show(day,'000860.SZ','/f10/000860.SZ');
  assert.match(summary.children[0].textContent,/000860\.SZ.*正在读取/);
  requests.get('/f10/000860.SZ').resolve(response('000860.SZ','OBSERVED',{source_detail:{main_business:'酒类生产。'}}));
  await next;
  assert.equal(summary.children[0].textContent,'主营业务：酒类生产。');
  cards.configure(false);
  assert.equal(summary.hidden,true);
  assert.deepEqual(summary.children,[]);
});

test('bound company research fills the card while F10 loads, then observed F10 takes precedence', async () => {
  const document=testDocument(),requests=[];
  const cards=createFormulaF10Cards(document,(url,signal)=>new Promise(resolve=>requests.push({url,signal,resolve})));
  cards.configure(true);
  const summary=document.getElementById('formulaCompanySummary');
  const symbol='000410.SZ',business='机床及高端装备制造。';
  const pendingF10=cards.show(researchDay,symbol,'/f10/000410.SZ');
  cards.showResearch(researchDay,symbol,companyResearch(symbol,business));
  assert.ok(summary.children.some(item=>item.textContent===`研究回传主营：${business}`));
  assert.ok(summary.children.some(item=>item.textContent.includes('PARTIAL')));
  assert.ok(summary.children.some(item=>item.textContent.includes('本日 F10 正在读取')));
  assert.ok(!summary.children.some(item=>item.textContent==='主营业务：F10 实际描述。'));
  requests[0].resolve({...response(symbol,'OBSERVED',{source_detail:{main_business:'F10 实际描述。'}}),
    data_date:'20261119',source_generation:researchDay.generation,input_sha256:researchDay.input_sha256,
    numeric_manifest:researchDay.numeric_manifest});
  await pendingF10;
  assert.ok(summary.children.some(item=>item.textContent==='主营业务：F10 实际描述。'));
  assert.ok(!summary.children.some(item=>item.textContent===`研究回传主营：${business}`));
});


test('only an exact formula-day F10 completion can trigger a fresh read', () => {
  const bound={...day,observation_date:'2026-11-16',formula_groups:{},numeric_manifest:ref};
  const event={...bound,schema:'V4_WORKBENCH_VERSIONS_V1',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
    modules:{f10:'e'.repeat(64)}};
  assert.equal(isFormulaF10Completion(bound,event),true);
  assert.equal(isFormulaF10Completion({...bound,formula_groups:null},event),false);
  for (const [key,value] of Object.entries({source_date:'2026-11-12',observation_date:'2026-11-17',generation:'e'.repeat(64),
    input_sha256:'e'.repeat(64),numeric_manifest:{...ref,sha256:'e'.repeat(64)},modules:{company:'e'.repeat(64)},orders_sent:true})) {
    assert.equal(isFormulaF10Completion(bound,{...event,[key]:value}),false,key);
  }
});


test('an F10 refresh preserves the verified card on failure and replaces it with an accepted source gap', async () => {
  const document=testDocument(), requests=[];
  const cards=createFormulaF10Cards(document,(url,signal)=>new Promise((resolve,reject)=>requests.push({signal,resolve,reject})));
  cards.configure(true);
  const symbol='603658.SH', summary=document.getElementById('formulaCompanySummary');
  const values=()=>summary.children.map(node=>node.textContent);
  const initial=cards.show(day,symbol,'/f10');
  requests[0].resolve(response(symbol,'OBSERVED'));
  await initial;
  const failing=cards.refresh(day,symbol,'/f10');
  assert.ok(values().includes('主营业务：仪器研发。'));
  requests[1].reject(Error('HTTP 503'));
  await failing;
  assert.ok(values().includes('主营业务：仪器研发。'));
  assert.ok(values().includes('F10 更新待核 · 保留本股上次已校验资料'));

  const stale=cards.refresh(day,symbol,'/f10');
  const changed=cards.show(day,'000860.SZ','/f10/000860.SZ');
  assert.ok(requests[2].signal.aborted);
  assert.ok(!values().includes('主营业务：仪器研发。'));
  requests[2].resolve(response(symbol,'OBSERVED'));
  requests[3].resolve(response('000860.SZ','OBSERVED',{source_detail:{main_business:'酒类生产。'}}));
  await Promise.all([stale,changed]);
  assert.ok(values().includes('主营业务：酒类生产。'));

  const knownGap=cards.refresh(day,'000860.SZ','/f10/000860.SZ');
  requests[4].resolve(response('000860.SZ','CANNOT_CONFIRM_SOURCE_GAP'));
  await knownGap;
  assert.match(values()[0],/000860\.SZ.*缺少可用快照/);
  assert.ok(!values().includes('主营业务：酒类生产。'));
});
