import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {render,primary,market,text,versions} from './ssr_harness.mjs';
const fixture=resolve(process.argv[2]);
const response=JSON.parse(readFileSync(resolve(fixture,'consumer_response.json'),'utf8'));
const evidence=response.execution_evidence;
const html=await render(evidence);const visible=primary(html);
const hk=market(visible,'HK_CONNECT');const a=market(visible,'A_SHARE');
assert.match(hk,/已计算 10 只/);
assert.match(hk,/行情 695 \/ 695 只，缺 0 只/);
assert.match(hk,/研究来源限制/);
assert.match(hk,/名单日期 20261008/);
assert.match(hk,/采集时间 2026-10-09T15:38:41\+08:00/);
assert.match(hk,/港股通资格待确认/);
assert.match(hk,/非正式 D1/);
assert.match(hk,/结果与原执行记录已绑定/);
assert.doesNotMatch(a,/已计算|695/);
assert.match(a,/选股结果待核对/);
assert.doesNotMatch(text(visible),/自然触发（NATURAL）/);
assert.match(text(visible),/补验 \/ 回放/);
assert.match(text(visible),/自然时段验收 尚未验证/);
const report={status:'PASS',scope:'REAL_VUE_SFC_COMPILE_SSR_OF_OFFLINE_FULL_CHAIN_CONSUMER_JSON',
  run_id:response.markets.HK_CONNECT.run_id,selected_rows:10,requested_rows:695,source_rows:695,
  api_run_sha_scope_assertions:'api_readback_assertions.json',a_borrowed_hk_rows:false,
  primary_hk_text:hk,primary_a_text:a,natural_label_displayed:false,node:process.version,packages:versions};
writeFileSync(resolve(fixture,'vue_readback_assertions.json'),JSON.stringify(report,null,2)+'\n');
writeFileSync(resolve(fixture,'vue_panel_ssr.html'),html+'\n');
console.log(JSON.stringify(report,null,2));
