import test from 'node:test';
import assert from 'node:assert/strict';
import {signalSummary,chartEvents} from '../research-panel/workbench-host/kb-signal-view.mjs';
import {overlayMarkers} from '../research-panel/workbench-host/kb-chart-overlay.mjs';

test('only confirmed signals and readable states are chips; diagnostics and false are not',()=>{
  const fields=[{name:'kb_beidou',group:'量价',arrow_type:'bool'},
    {name:'kb_fanbao',group:'砖型',arrow_type:'bool'},
    {name:'kb_macd_veto',group:'MACD',arrow_type:'bool'},
    {name:'kb_breath_phase',group:'呼吸',arrow_type:'string'},
    {name:'kb_rebuild',group:'高级战法',arrow_type:'bool',unknown_reason:'上游缺陷'},
    {name:'kb_b2_volume_up',group:'组件/诊断',arrow_type:'bool'}];
  const result=signalSummary(fields,{kb_beidou:true,kb_fanbao:false,kb_macd_veto:true,kb_breath_phase:'exhale',kb_rebuild:null,kb_b2_volume_up:true},
    {user_v1_level1_buy_signal:1,user_v1_level2_buy_signal:0});
  assert.deepEqual(result.chips.map(item=>item.label),['原式一级买点','KB 倍量','KB MACD风险否决','KB 呼吸阶段 · 呼气']);
  assert.deepEqual(result.unknown.map(item=>item.key),['kb_rebuild','kb_s1','kb_s2','kb_s3','kb_didi_1455']);
  assert.match(result.unknown.at(-1).reason,/分钟行情/);
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
