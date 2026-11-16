import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {createFormulaF10Cards, formulaF10CardContent, isFormulaF10Completion, validateFormulaF10} from '../../apps/web/public/research-panel/workbench-host/dot/shell/formula-f10.mjs';

const day = {source_date:'2026-11-13',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)};
const ref = {path:'/f10-snapshot',sha256:'c'.repeat(64)};
const response = (symbol, status, fields={}) => ({status,symbol,data_date:'20261113',source_generation:day.generation,
  input_sha256:day.input_sha256,receipt:ref,stock_ref:ref,historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,
  orders_sent:false,f10:{source_text_sha256:'d'.repeat(64),captured_at:'2026-11-13T09:25:09+00:00',source_updated_date:'2026-11-13',
    finance_updated_date:'20261026', industry:{tdx_finance_industry_code:9},concept_status:'OBSERVED',concepts:[{name:'测试概念'}],
    financials:{report_period:'2026-09-30',revenue_text:'2.1亿',net_profit_text:'1.1亿',holder_count:1234},
    source_detail:{main_business:'仪器研发。',shareholder_record_date:'2026-09-30'},...fields}});

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
