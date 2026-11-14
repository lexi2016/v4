import assert from 'node:assert/strict';
import test from 'node:test';

import {
 historyRate,historyRateGroups,historyRateNote,permitsRateSort,rateLabel,sortHistoryRates
} from '../../apps/web/public/research-panel/workbench-host/rate-sort.mjs';

const counts=(positive,valid,not_matured,total=valid+not_matured)=>({
 positive,valid,not_matured,total,positive_fraction:valid?positive/valid:null
});
const row=(symbol,stats,otherStats)=>({
 symbol,group_states:{nav_pullback:'TRUE',nav_smallk:otherStats?'TRUE':'FALSE',original:'UNKNOWN',nav_breakout:'FALSE'},
 history_rates:{nav_pullback:stats,nav_smallk:otherStats}
});
const get=(r,h='d2')=>rateLabel(historyRate(r,'nav_pullback',h));

test('candidate cutoff and observation date show distinct ST京机 maturity counts',()=>{
 const earlier=row('000821.SZ',{d2:counts(1,1,1),d5:counts(0,0,2)});
 const later=row('000821.SZ',{d2:counts(1,1,2),d5:counts(0,1,2)});
 assert.match(historyRateNote({source_date:'2026-11-12',observation_date:'2026-11-13'},'all'),/统计截止 2026-11-12 收盘 · 观察 2026-11-13/);
 assert.match(historyRateNote({source_date:'2026-11-13',observation_date:'2026-11-16'},'nav_pullback'),/统计截止 2026-11-13 收盘 · 观察 2026-11-16.*排序分组 回踩/);
 assert.deepEqual(get(earlier),{summary:'100.0% · 1/1',counts:['未成熟 1','已到期无效 0'],lowSample:true});
 assert.deepEqual(get(earlier,'d5'),{summary:'0/0 无有效样本',counts:['未成熟 2','已到期无效 0'],lowSample:false});
 assert.deepEqual(get(later),{summary:'100.0% · 1/1',counts:['未成熟 2','已到期无效 0'],lowSample:true});
 assert.deepEqual(get(later,'d5'),{summary:'0.0% · 0/1',counts:['未成熟 2','已到期无效 0'],lowSample:true});
});

test('counts preserve known zero and distinguish matured invalid from missing coverage',()=>{
 const invalid=row('invalid',{d2:counts(0,0,1,3)});
 const missing=row('missing',{});
 assert.deepEqual(get(invalid).counts,['未成熟 1','已到期无效 2']);
 assert.match(get(missing).summary,/待核\/待核/);
 assert.deepEqual(get(missing).counts,['未成熟 待核','已到期无效 待核']);
 assert.deepEqual(get(row('large',{d2:counts(1234,2345,9999,13578)})).counts,['未成熟 9999','已到期无效 1234']);
 const inconsistent=row('inconsistent',{d2:counts(2,1,0)});
 assert.match(get(inconsistent).summary,/待核\/待核/);
});

test('all candidates show every current TRUE group and explicit group views show only that group',()=>{
 const multi=row('multi',{d2:counts(1,1,2)},{d2:counts(1,3,1)});
 assert.deepEqual(historyRateGroups(multi,'all'),['nav_smallk','nav_pullback']);
 assert.deepEqual(historyRateGroups(multi,'fifth'),['nav_smallk','nav_pullback']);
 assert.deepEqual(historyRateGroups(multi,'nav_pullback'),['nav_pullback']);
 assert.deepEqual(historyRateGroups(multi,'original'),[]);
 assert.notEqual(historyRate(multi,'nav_smallk','d2').value,historyRate(multi,'nav_pullback','d2').value);
 assert.equal(historyRate(multi,'all','d2').value,null);
 assert.equal(permitsRateSort('all'),false);
 assert.equal(permitsRateSort('v192'),false);
 assert.equal(permitsRateSort('nav_smallk','ZGE_SKILL_DAILY_CANDIDATES_R2'),false);
 assert.equal(permitsRateSort('nav_smallk'),true);
});

test('sort compares only the chosen group and puts small samples last in either direction',()=>{
 const tiny=row('tiny',{d2:counts(1,1,1)},{d2:counts(7,8,0)});
 const robust=row('robust',{d2:counts(3,5,0)},{d2:counts(0,0,2)});
 const bigZero=row('bigZero',{d2:counts(0,5,0)});
 const four=row('four',{d2:counts(0,4,0)});
 const zero=row('zero',{d2:counts(0,0,2)});
 const missing=row('missing',{});
 const source=[tiny,zero,missing,robust,bigZero,four];
 const names=(group,mode)=>sortHistoryRates(source,group,mode).map(r=>r.symbol);
 assert.deepEqual(names('nav_pullback','d2_desc'),['robust','bigZero','four','tiny','zero','missing']);
 assert.deepEqual(names('nav_pullback','d2_asc'),['bigZero','robust','four','tiny','zero','missing']);
 assert.deepEqual(names('nav_smallk','d2_desc'),['tiny','robust','zero','missing','bigZero','four']);
 assert.equal(sortHistoryRates(source,'all','d2_desc'),source);
});
