"""Selected-group and existing async guards, executed from the actual UI source."""
from pathlib import Path
import subprocess

NODE = '/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'


def run(script):
    subprocess.run([NODE, '-e', script], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True)


def test_sidebar_group_selects_same_stock_rate_and_unavailable_group_falls_back():
    run(r'''
const assert=require('assert'),fs=require('fs'),source=fs.readFileSync('research-panel/numeric283-panel.js','utf8');
const binding=source.slice(source.indexOf('function loadChart(symbol, name) {'),source.indexOf('const token = ++chartRequest;',source.indexOf('function loadChart(symbol, name) {'))).split('\n').slice(1).join('\n');
const choose=new Function('requested',`let selectedSymbol,activeGroup,currentStatistics={}; const symbol='001328.SZ',currentRows=[{symbol,groups:'nav_smallk|nav_pullback'}],groupSelect={value:requested},search={value:''},groupTokens=v=>typeof v==='string'?v.split('|').filter(Boolean):[],filterRows=()=>[],refreshReaderList=()=>{};${binding};return {activeGroup,currentStatistics};`);
assert.deepStrictEqual(choose('nav_pullback'),{activeGroup:'nav_pullback',currentStatistics:null});
assert.strictEqual(choose('all').activeGroup,'nav_smallk');assert.strictEqual(choose('nav_breakout').activeGroup,'nav_smallk');assert.strictEqual(choose('invalid').activeGroup,'nav_smallk');
const render=source.slice(source.indexOf('function renderStatistics(symbol)'),source.indexOf('\n    async function loadConditionalSummaries'));
assert(render.includes('`${selected.label} · ${h.label} 历史总体成功率`'));
''')


def test_selected_group_is_sent_to_case_api_and_stale_async_reply_cannot_replace_it():
    run(r'''
const assert=require('assert'),fs=require('fs'),source=fs.readFileSync('research-panel/numeric283-panel.js','utf8');
const body=source.slice(source.indexOf('async function loadConditionalSummaries('),source.indexOf('\n    function sourceLink'));
const waiting=[],urls=[],fetch=url=>{urls.push(url);return new Promise(resolve=>waiting.push(resolve));};
const api=new Function('windowObject',`let chartRequest=1,activeGroup='nav_pullback',currentStatistics={},renders=0;const payloadMetadata={data_date:'20261029',manifest:{sha256:'bound'}},chartController={signal:null},caseReplies=new Map(),sameRef=(a,b)=>a?.sha256===b.sha256,renderStatistics=()=>++renders;${body};return {load:loadConditionalSummaries,advance(){++chartRequest;activeGroup='nav_smallk';},state:()=>({renders,stats:currentStatistics,cacheSize:caseReplies.size})};`)({fetch});
(async()=>{
const p=api.load('001328.SZ','nav_pullback',1);assert(urls.every(u=>new URL(u,'http://local').searchParams.get('group')==='nav_pullback'));
for(const resolve of waiting.splice(0))resolve({json:async()=>({status:'READY',numeric_manifest:{sha256:'bound'},conditional:{valid:18,positive:12}})});
await p;assert.strictEqual(api.state().stats.conditional.d2.valid,18);assert.strictEqual(api.state().renders,1);
const stale=api.load('001328.SZ','nav_pullback',1);api.advance();for(const resolve of waiting.splice(0))resolve({json:async()=>({status:'READY',numeric_manifest:{sha256:'bound'},conditional:{valid:0,positive:0}})});await stale;
assert.strictEqual(api.state().renders,1);assert.strictEqual(api.state().stats.conditional.d2.valid,18);
})().catch(e=>{console.error(e);process.exitCode=1});
''')
