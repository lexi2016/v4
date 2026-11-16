import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {validateDailyChart,verifiedOriginalMarks} from '../../apps/web/public/research-panel/workbench-host/dot/shell/formula-daily-chart.mjs';

const selector = {path:'/selector',sha256:'a'.repeat(64)};
const snapshot = {path:'/snapshot',sha256:'b'.repeat(64)};
const day = {source_date:'2026-11-13',generation:'c'.repeat(64),input_sha256:'d'.repeat(64),
    numeric_manifest:{path:'/numeric',sha256:'e'.repeat(64)},source_selector_sha256:selector.sha256,
    source_close_reference:{selector,snapshot},formula_groups:{artifact:{sha256:'f'.repeat(64)}}};
const bar = {trade_date:'20261113',open:10,high:12,low:9,close:11,volume:100};
const chart = {...day,schema:'V4_WORKBENCH_DAILY_K_V1',symbol:'002667.SZ',selector,snapshot,
    formula_group_sha256:day.formula_groups.artifact.sha256,price_basis:'QFQ_ASOF_20261113',volume_basis:'QFQ_EVENT_VOLUME',
    historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,rows:[bar]};

test('daily chart accepts only the bound stock, generation, snapshot and date', () => {
    assert.equal(validateDailyChart(chart,day,'002667.SZ'),chart);
    assert.throws(() => validateDailyChart(chart,day,'920970.BJ'));
    assert.throws(() => validateDailyChart({...chart,generation:'1'.repeat(64)},day,chart.symbol));
    assert.throws(() => validateDailyChart({...chart,snapshot:{...snapshot,sha256:'1'.repeat(64)}},day,chart.symbol));
    assert.throws(() => validateDailyChart({...chart,rows:[{...bar,trade_date:'20261112'}]},day,chart.symbol));
});

test('daily chart refuses invalid numeric bars and duplicated sessions', () => {
    assert.throws(() => validateDailyChart({...chart,rows:[bar,bar]},day,chart.symbol));
    assert.throws(() => validateDailyChart({...chart,rows:[{...bar,low:13}]},day,chart.symbol));
    assert.throws(() => validateDailyChart({...chart,rows:[{...bar,volume:'100'}]},day,chart.symbol));
});


test('original drawings are consumed only from the same stock and chart window', () => {
    const marker={trade_date:bar.trade_date,id:1,kind:'DRAWTEXT',payload:'守线',styles:['COLORFFFFFF'],y:'37.53728'};
    const original={...chart,schema:'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1',status:'READY',
        formula_sha256:'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac',
        engine_sha256:'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c',
        sidecar:{sha256:'f'.repeat(64)},marks:[marker],unresolved_conditions:0};
    assert.equal(verifiedOriginalMarks({...chart,original_marks:original}),original);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...original,symbol:'920970.BJ'}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...original,marks:[{...marker,trade_date:'20261112'}]}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...original,marks:[marker,marker]}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{status:'CANNOT_CONFIRM'}}),null);
});
