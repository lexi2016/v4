import test from 'node:test';
import assert from 'node:assert/strict';
import {REVIEW_SOURCE_DATE,REVIEW_SOURCE_LOCKS,reviewSampleRows,installReviewSampleGroups}
  from '../research-panel/workbench-host/review-sample-groups.mjs';

const first=['600000.SH','600519.SH','601318.SH','688981.SH','688496.SH','300206.SZ','002865.SZ','301048.SZ',
  '301686.SZ','000001.SZ','920201.BJ','920196.BJ','920298.BJ','920000.BJ','920001.BJ','600036.SH',
  '603281.SH','000020.SZ','000301.SZ','920187.BJ'];
const second=['600000.SH','300206.SZ','301048.SZ','688496.SH','301686.SZ','920196.BJ','000002.SZ','603848.SH',
  '603956.SH','603248.SH','002991.SZ','002581.SZ','000089.SZ','688160.SH','688208.SH','688781.SH',
  '300115.SZ','920642.BJ','920149.BJ','920455.BJ'];

test('two source-locked samples keep all 40 records and six repeat identities',()=>{
  const a=reviewSampleRows('first'),b=reviewSampleRows('second'),all=reviewSampleRows();
  assert.equal(REVIEW_SOURCE_DATE,'2026-10-30');assert.match(REVIEW_SOURCE_LOCKS.first,/^[a-f0-9]{64}$/);
  assert.match(REVIEW_SOURCE_LOCKS.second,/^[a-f0-9]{64}$/);
  assert.deepEqual(a.map(x=>x.symbol),first);assert.deepEqual(b.map(x=>x.symbol),second);
  assert.equal(all.length,34);assert.equal(new Set(all.map(x=>x.symbol)).size,34);
  assert.deepEqual(all.filter(x=>x.rounds.length===2).map(x=>x.symbol).sort(),
    ['300206.SZ','301048.SZ','301686.SZ','600000.SH','688496.SH','920196.BJ']);
  assert.equal(all.find(x=>x.symbol==='688496.SH').name,'*ST清越');
  assert.deepEqual(reviewSampleRows('unknown'),[]);
});

class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.style={};this.hidden=false;this.value='';this.attributes={};}
  append(...children){this.children.push(...children)}
  replaceChildren(...children){this.children=[...children]}
  setAttribute(key,value){this.attributes[key]=value}
}
const fakeDocument={createElement:tag=>new Element(tag)};

test('sidebar switches review rounds, opens the chosen normal or exception symbol, and guards date changes',()=>{
  const container=new Element('div'),calls=[];
  const group=installReviewSampleGroups({container,document:fakeDocument,openSymbol:(...args)=>calls.push(args)});
  const panel=container.children[0],summary=panel.children[0],source=panel.children[1];
  const selector=panel.children[2].children[0],count=panel.children[3],list=panel.children[4];
  assert.equal(panel.hidden,true);assert.match(summary.textContent,/34只.*40次/);
  assert.match(source.textContent,/仅为复查名单.*不代表数值入选或买点/);
  assert.equal(list.children.length,34);assert.match(count.textContent,/40次.*6只复验/);
  group.bindDay({source_date:'2026-10-30'});assert.equal(panel.hidden,false);
  list.children.find(x=>x.textContent.includes('600000.SH')).onclick();
  list.children.find(x=>x.textContent.includes('688496.SH')).onclick();
  assert.deepEqual(calls,[['600000.SH','浦发银行'],['688496.SH','*ST清越']]);
  selector.value='first';selector.onchange();assert.equal(list.children.length,20);
  selector.value='second';selector.onchange();assert.equal(list.children.length,20);
  assert.ok(list.children.some(x=>x.textContent.includes('000002.SZ')));
  group.bindDay({source_date:'2026-10-29'});assert.equal(panel.hidden,true);
  list.children[0].onclick();assert.equal(calls.length,2);
  group.bindDay({source_date:'2026-10-30'});group.unbindDay();list.children[0].onclick();assert.equal(calls.length,2);
});
