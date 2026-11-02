import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {actionPresentation,signalSummary,chartEvents,signalExplanations,confirmedGapPresentation,brickCountPresentation,nStructurePresentation} from '../research-panel/workbench-host/kb-signal-view.mjs';
import {overlayMarkers} from '../research-panel/workbench-host/kb-chart-overlay.mjs';
import {financialLines,financialDisclosureText,visibleSingleHistoryGroups,decodeBoundGzip,singleSelectionHref} from '../research-panel/workbench-host/kb-single-stock.mjs';

test('single-stock route keeps source date separate from symbol and historical date',()=>{
  const base='http://127.0.0.1:8873/research-panel/workbench.html?date=2026-10-30&symbol=300206.SZ#chart';
  const historical=new URL(singleSelectionHref(base,'301048.SZ','2025-12-12'));
  assert.equal(historical.searchParams.get('date'),'2026-10-30');
  assert.equal(historical.searchParams.get('symbol'),'301048.SZ');
  assert.equal(historical.searchParams.get('stock_date'),'2025-12-12');
  assert.equal(historical.hash,'#chart');
  const latest=new URL(singleSelectionHref(historical.href,'002865.SZ'));
  assert.equal(latest.searchParams.get('symbol'),'002865.SZ');
  assert.equal(latest.searchParams.has('stock_date'),false);
  assert.equal(latest.searchParams.get('date'),'2026-10-30');
  const pinned=new URL(singleSelectionHref(base,'300206.SZ','2025-12-12',{key:'candidate_generation',value:'a'.repeat(64)}));
  assert.equal(pinned.searchParams.get('candidate_generation'),'a'.repeat(64));
  const same=new URL(singleSelectionHref(pinned.href,'300206.SZ','2025-12-15'));
  assert.equal(same.searchParams.get('candidate_generation'),'a'.repeat(64));
  const switched=new URL(singleSelectionHref(same.href,'301048.SZ'));
  assert.equal(switched.searchParams.has('candidate_generation'),false);
  const scoped=new URL(singleSelectionHref(switched.href,'000410.SZ',null,{key:'panel_generation',value:'b'.repeat(64)}));
  assert.equal(scoped.searchParams.get('panel_generation'),'b'.repeat(64));
  assert.equal(scoped.searchParams.has('candidate_generation'),false);
  assert.throws(()=>singleSelectionHref(base,'bad','2025-12-12'),/证券无效/);
  assert.throws(()=>singleSelectionHref(base,'301048.SZ','20251212'),/日期无效/);
  assert.throws(()=>singleSelectionHref(base,'300206.SZ',null,{key:'candidate_generation',value:'old'}),/版本无效/);
});

test('stored action values require the bound contract and are only formatted',()=>{
  const sha='a'.repeat(64),stored={kb_action_no_position:'等回调',kb_action_no_position_status:'OBSERVED_BLOCKER_CONDITIONAL',kb_action_with_position:'持有',kb_action_with_position_status:'CONFLICTING_OBSERVATIONS',kb_action_reasons:JSON.stringify(['已存条件']),kb_action_rule_sha256:sha};
  assert.deepEqual(actionPresentation(stored,sha),{flat:stored.kb_action_no_position,held:stored.kb_action_with_position,reasons:['已存条件']});
  assert.throws(()=>actionPresentation(stored,'b'.repeat(64)),/身份冲突/);
  assert.throws(()=>actionPresentation({...stored,kb_action_reasons:'[]x'},sha));
  assert.equal(actionPresentation({...stored,kb_action_with_position:null},sha).held,'待核');
  assert.throws(()=>actionPresentation({...stored,kb_action_no_position:'乱填'},sha),/枚举无效/);
});

test('financial values use the bound source units and period without duplicate unknown rows',()=>{
  const f10={financials:{report_period:'2026-09-30',revenue_text:'23.5136亿',net_profit_text:'1.7169亿'}};
  const gold=financialLines({},f10);
  assert.match(gold[0],/营业总收入.*TDX F10.*2026-09-30.*23\.5136亿元/);
  assert.match(gold[1],/^净利润.*1\.7169亿元/);assert.doesNotMatch(gold[1],/归母/);
  assert.match(gold[2],/经营现金流净额：待核.*口径.*单位.*报告期/);
  const official=financialLines({latest_revenue:5222744068.83,latest_net_profit_parent:-428296532.32},f10);
  assert.deepEqual(official.slice(0,2),['营业收入：52.23亿元','归母净利润：-4.28亿元']);
  assert.match(financialLines({}, {financials:{revenue_text:'bad'}})[0],/待核/);
  assert.match(financialDisclosureText({latest_period_kind:'三季报',latest_report_period:'2026-09-30',latest_disclosed_at:'2026-10-22',evidence_status:'OFFICIAL_FILING'}, {}, {official_quarterly:{available_date:'2026-10-22'}}),/披露 2026-10-22/);
  const goldTime=financialDisclosureText({latest_report_period:'2026-09-30',latest_disclosed_at:'20261027'}, {finance_updated_date:'20261027'});
  assert.match(goldTime,/披露 待核/);assert.match(goldTime,/F10更新 20261027/);
});

test('single-stock history hides only old B1/B2/B3 display and keeps original level signals',()=>{
  const groups=['original_level1','original_level2','original_b1','original_b2','original_b3','kb_b1','kb_b2','kb_b3'].map(group_id=>({group_id}));
  assert.deepEqual(visibleSingleHistoryGroups(groups).map(group=>group.group_id),['original_level1','original_level2','kb_b1','kb_b2','kb_b3']);
  assert.equal(groups.length,8);
});

test('only confirmed signals and readable states are chips; diagnostics and false are not',()=>{
  const fields=[{name:'kb_beidou',group:'量价',arrow_type:'bool'},
    {name:'kb_fanbao',group:'砖型',arrow_type:'bool'},
    {name:'kb_macd_veto',group:'MACD',arrow_type:'bool'},
    {name:'kb_breath_phase',group:'呼吸',arrow_type:'string'},
    {name:'kb_rebuild',group:'高级战法',arrow_type:'bool',unknown_reason:'上游缺陷'},
    {name:'kb_b2_volume_up',group:'组件/诊断',arrow_type:'bool'}];
  const result=signalSummary(fields,{kb_beidou:true,kb_fanbao:false,kb_macd_veto:true,kb_breath_phase:'exhale',kb_rebuild:null,kb_b2_volume_up:true},
    {user_v1_level1_buy_signal:1,user_v1_level2_buy_signal:0});
  assert.deepEqual(result.chips.map(item=>item.label),['原式一级买点','KB 倍量','KB MACD日线风险条件','KB 呼吸阶段 · 呼气']);
  assert.deepEqual(result.unknown.map(item=>item.key),['kb_rebuild','kb_s1','kb_s2','kb_s3']);
  const anomaly=signalSummary([],{}, {}, {},{kb_yidong_is:true,kb_yidong_type:'徐杰级'});
  assert.deepEqual(anomaly.chips.map(item=>item.label),['KB 异动 · 徐杰级']);
});

test('missing signals cite the right comparison and never reuse another day',()=>{
  const facts={'20261030':{volume_ratio:1.8734,prior_20_high:38.69,
    kb_b3_components:{anchor_date:'20261029',trading_bars_since_anchor:1,today_anchor_volume_ratio:1.8734},
    breakout_components:{close_above_previous_20_high:true,pct_chg:2.9},
    violence_k_python_components:{relative_previous_five_mean_volume:2.089,body_pct:2.874}}};
  const lines=signalExplanations({trade_date:20261030},facts).join(' ');
  assert.match(lines,/1\.87 倍/);assert.match(lines,/2\.09 倍/);assert.match(lines,/相距1个交易日/);
  assert.match(lines,/严格大于4%/);assert.match(lines,/MACD不属于持股评分/);
  assert.match(signalExplanations({trade_date:20251212},facts).join(' '),/不能套用其他日期/);
  assert.match(signalExplanations({trade_date:20251212,kb:{kb_macd_veto:false}},facts)[0],/本日状态：未触发/);
  assert.match(signalExplanations({trade_date:20251212,kb:{kb_macd_veto:null}},facts)[0],/本日状态：待核/);
  assert.match(signalExplanations({trade_date:20261030,kb:{kb_macd_veto:true}},facts)[0],/本日状态：触发/);
});

test('KB chart events use the matching candle x coordinate and preserve distinct definitions',()=>{
  const visible=[20251211,20251212,20251215].map(date=>({trade_date:date,ohlcv:{high:11,low:9},values:{BBI:10},drawings:[]}));
  const byDate=new Map([[20251212,{kb:{kb_b1:true,kb_violence_k:true,kb_fanbao:true,kb_macd_dif_positive:true}}]]);
  const state={visible,offset:20,geometry:{L:60,R:18,pw:300,step:100,w:378,h:405}};
  const marks=overlayMarkers(state,byDate);
  assert.deepEqual(marks.map(m=>m.key),['kb_b1','kb_violence_k','kb_fanbao']);
  assert.ok(marks.every(m=>m.date===20251212&&m.index===21&&m.x===210));
  assert.deepEqual(chartEvents({kb_b1:true,kb_sb1:true}).map(x=>x.label),['KB B1','KB SB1']);
  assert.deepEqual(chartEvents({kb_rebuild:true}).map(x=>x.label),['KB 灾后重建']);
});

test('confirmed gap display distinguishes warmup, non-events and reused bowl lines',()=>{
  const row={kb:{kb_brick_consecutive:4},confirmed_kb_fields:{kb_brick_trend:'RED',kb_brick_action_desc:null,
    kb_yidong_above_60d:true,kb_double_gun_vol1:null,kb_double_gun_vol2:null,kb_double_gun_gap_days:null,
    kb_violence_k_type:null,kb_violence_k_body:null},confirmed_kb_diagnostics:{kb_brick_count_reason:'BRICK_RUN_ORIGIN_IN_WARMUP',
    kb_brick_action_desc_reason:'BRICK_RUN_ORIGIN_IN_WARMUP',kb_double_gun_components_status:'NOT_APPLICABLE_NO_SIGNAL',
    kb_violence_k_components_status:'NOT_APPLICABLE_NO_SIGNAL',kb_bowl_components_status:'OBSERVED_SOURCE_LINES'},
    confirmed_kb_reused:{bowl_white:35.1524,bowl_yellow:40.0624}};
  const values=Object.fromEntries(confirmedGapPresentation(row).map(x=>[x.key,x.text]));
  assert.equal(values.kb_brick_trend,'红砖');assert.match(values.kb_double_gun_vol1,/不适用 · 当日未命中/);
  assert.equal(values.bowl_white,'35.15');assert.equal(values.bowl_yellow,'40.06');
  assert.match(brickCountPresentation(row),/预热期/);assert.equal(row.kb.kb_brick_consecutive,4);
  row.confirmed_kb_diagnostics.kb_bowl_components_status='INSUFFICIENT_HISTORY';
  assert.match(Object.fromEntries(confirmedGapPresentation(row).map(x=>[x.key,x.text])).bowl_white,/待核/);
});

test('N score distinguishes false and ambiguous unknown and dates confirmation',()=>{
  const n={L1:{price:32,event_date:'20261015',confirmed_at:'20261022'}};
  const row={hold_score:{kb_hold_trend_up:false,kb_hold_trend_up_reason:'STRUCTURE_NOT_RISING'},
             confirmed_kb_diagnostics:{kb_n_structure:n}};
  const lines=nStructurePresentation(row);
  assert.match(lines[0],/0分.*高点或低点未同时抬高/);
  assert.match(lines[1],/20261015 形成，20261022 确认/);
  row.hold_score={kb_hold_trend_up:null,kb_hold_trend_up_reason:'AMBIGUOUS_SAME_BAR_PIVOT'};
  assert.match(nStructurePresentation(row)[0],/待核.*先后次序待核/);
  assert.equal(nStructurePresentation({hold_score:{}}),null);
});

test('bounded gzip accepts the real-size long-history view and rejects size mismatch or overflow',async()=>{
  const length=24*1024*1024, compressed=gzipSync(Buffer.alloc(length,65));
  const decoded=await decodeBoundGzip(compressed,length);
  assert.equal(decoded.byteLength,length);assert.equal(decoded[0],65);assert.equal(decoded.at(-1),65);
  await assert.rejects(()=>decodeBoundGzip(compressed,length-1),/解压长度不符/);
  await assert.rejects(()=>decodeBoundGzip(compressed,length+1),/解压长度不符/);
  await assert.rejects(()=>decodeBoundGzip(compressed,32*1024*1024+1),/解压长度不符/);
});
