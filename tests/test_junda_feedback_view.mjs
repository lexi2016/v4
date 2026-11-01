import test from 'node:test';
import assert from 'node:assert/strict';
import {actionPresentation,signalSummary,chartEvents,signalExplanations} from '../research-panel/workbench-host/kb-signal-view.mjs';
import {overlayMarkers} from '../research-panel/workbench-host/kb-chart-overlay.mjs';
import {financialLines,financialDisclosureText,visibleSingleHistoryGroups} from '../research-panel/workbench-host/kb-single-stock.mjs';

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
  assert.equal(gold[2],'经营现金流净额：待核');
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
});
