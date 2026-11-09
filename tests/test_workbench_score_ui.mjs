import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {actionPresentation,HOLD_ITEMS,HOLD_REASONS} from '../research/stock_panel_collab_20261030/mac-host/kb-signal-view.mjs';
const source=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/kb-single-stock.mjs',import.meta.url),'utf8');
class Element{
 constructor(){this.children=[];this.hidden=false;this.text=''}
 set textContent(v){this.text=String(v);this.children=[]}
 get textContent(){return this.text+this.children.map(x=>x.textContent).join('')}
 append(...n){this.children.push(...n)}
 replaceChildren(...n){this.text='';this.children=[...n]}
}
function harness(symbol='002047.SZ'){
 const nodes=new Map(),el=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
 const host=el('host');host.querySelector=el;
 const body=el('body');body.children=[new Element(),new Element(),new Element()];
 const classes=new Set(),ctx={symbol,host,body,frame:el('frame'),status:el('status'),active:null,
   day:{source_date:'2026-11-09'},document:{body:{classList:{remove:x=>classes.delete(x),add:x=>classes.add(x)}}},
   $:el,node:(tag,text)=>{const n=new Element();if(text!==undefined)n.textContent=text;return n},
   actionPresentation,HOLD_ITEMS,HOLD_REASONS,sha64:x=>/^[a-f0-9]{64}$/.test(x),label:x=>x??'待核'};
 vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('  function dailyMode('),source.indexOf('  async function open(){')),ctx);
 return {ctx,el,classes};
}
function fixture(symbol){const sha='a'.repeat(64),bound={source_date:'2026-11-09',generation:'b'.repeat(64),input_sha256:'c'.repeat(64),numeric_manifest:{sha256:'d'.repeat(64),path:'/numeric'}};
 return {bound,meta:{schema:'v4.workbench.daily_kb_research.v1',status:'MATERIALIZED',symbol,...bound,historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,score_row_sha256:'e'.repeat(64),action_contract_sha256:sha,
   row:{trade_date:'20261109',cache_identity:{rules:{'a_share_kb_action_v1.json':sha}},kb:{kb_b1:true,kb_b1_j:65},n_structure:{state:'TREND_UP'},hold_score:{...Object.fromEntries(HOLD_ITEMS.map(([key])=>[key,true])),kb_hold_score:5,kb_hold_score_min:5,kb_hold_score_max:5},
   action:{kb_action_no_position:'等回调',kb_action_with_position:'持有',kb_action_no_position_status:'UNKNOWN_BUY_FILTERS',kb_action_with_position_status:'OBSERVED_SCORE_HOLD_CONDITIONAL',kb_action_reasons:JSON.stringify(['原规则依据']),kb_action_rule_sha256:sha}}}};
}
test('real daily painter shows all five components and both positions without hiding normal content',()=>{
 for(const symbol of ['002047.SZ','300856.SZ','688718.SH']){
  const {ctx,el,classes}=harness(symbol),{bound,meta}=fixture(symbol);
  ctx.paintDaily(meta,bound);
  assert.equal(classes.has('kb-single-focus'),false);
  assert.equal(ctx.host.hidden,false);assert.equal(ctx.body.hidden,false);
  assert.match(el('kbSingleScore').textContent,/5\/5/);
  for(const [key,title] of HOLD_ITEMS)assert.ok(el('kbSingleScoreItems').textContent.includes(title));
  assert.match(el('kbSingleActions').textContent,/无持仓：等回调有持仓：持有/);
  assert.equal(ctx.frame.hidden,true); // existing main chart stays in #content.
  assert.ok(!source.slice(source.indexOf('  function dailyMode('),source.indexOf('  async function open(){')).includes("$('content')"));
 }
});
test('missing dated material stays explicit and wrong generation is rejected',()=>{
 const {ctx,el}=harness(),{bound,meta}=fixture('002047.SZ');
 ctx.paintDaily({...meta,status:'UNKNOWN',row:null,reason:'SCORE_NOT_MATERIALIZED_FOR_DATE'},bound);
 assert.match(el('kbSingleScore').textContent,/待核/);assert.match(el('kbSingleActions').textContent,/无持仓：待核有持仓：待核/);
 assert.throws(()=>ctx.paintDaily({...meta,generation:'f'.repeat(64)},bound),/身份冲突/);
 assert.ok(source.includes('host.hidden=!value?.source_date'));
});

test('historical volume key labels the confirmed candle rule',()=>{assert.equal(HOLD_ITEMS.find(([key])=>key==='kb_hold_volume_ok')[1],'阳线得分（收盘>开盘）')});
