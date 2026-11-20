import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {renderDailyChart,validateDailyChart,verifiedOriginalMarks} from '../../apps/web/public/research-panel/workbench-host/dot/shell/formula-daily-chart.mjs';

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

test('original formula lines require exact full-window decimal points and keep legacy marks compatible', () => {
    const marker={trade_date:bar.trade_date,id:1,kind:'DRAWTEXT',payload:'守线',styles:['COLORFFFFFF'],y:'37.53728'};
    const point=(y,trade_date=bar.trade_date)=>({trade_date,y});
    const original={...chart,schema:'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1',status:'READY',
        formula_sha256:'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac',
        engine_sha256:'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c',
        sidecar:{sha256:'f'.repeat(64)},marks:[marker],unresolved_conditions:0};
    assert.equal(verifiedOriginalMarks({...chart,original_marks:original}),original);
    const withLines={...original,lines:{'白线':[point('13.58671489947057447652402281')],'黄线':[point(null)]}};
    assert.equal(verifiedOriginalMarks({...chart,original_marks:withLines}),withLines);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...withLines,lines:{...withLines.lines,'白线':[point('13.5','20261112')]}}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...withLines,lines:{...withLines.lines,'黄线':[]}}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...withLines,lines:{...withLines.lines,'黄线':[point('Infinity')]}}}),null);
    assert.equal(verifiedOriginalMarks({...chart,original_marks:{...withLines,lines:{...withLines.lines,'白线':[point('1e-999999999')]}}}),null);
});

test('canvas draws the original white and yellow series, breaks null gaps, and reindexes the 60 bar window', () => {
    const records=[];
    let path=[];
    const ctx={
        save(){},restore(){},scale(){},beginPath(){path=[];},rect(){},clip(){},closePath(){},
        moveTo(x,y){path.push([x,y]);},lineTo(x,y){path.push([x,y]);},
        stroke(){records.push({color:this.strokeStyle,width:this.lineWidth,points:path.slice()});},
        fill(){},fillRect(){},arc(){},strokeText(){},fillText(){},measureText(text){return {width:String(text).length*6};},
        setTransform(){},
    };
    class Element {
        constructor(tag){this.tag=tag;this.children=[];this.style={};this.dataset={};this.attributes={};this.clientWidth=900;this.clientHeight=340;}
        append(...items){this.children.push(...items);}
        add(item){this.children.push(item);}
        replaceChildren(...items){this.children=items;}
        setAttribute(name,value){this.attributes[name]=value;}
        getContext(){return ctx;}
    }
    const prior={document:globalThis.document,Option:globalThis.Option,ResizeObserver:globalThis.ResizeObserver,window:globalThis.window};
    globalThis.document={createElement:tag=>new Element(tag)};
    globalThis.Option=class {constructor(text,value){this.text=text;this.value=value;}};
    globalThis.ResizeObserver=class {observe(){} disconnect(){}};
    globalThis.window={devicePixelRatio:1};
    try {
        const dates=[];
        const day=new Date(Date.UTC(2026,6,1));
        while(dates.length<120){
            if(day.getUTCDay()!==0&&day.getUTCDay()!==6){
                dates.push(`${day.getUTCFullYear()}${String(day.getUTCMonth()+1).padStart(2,'0')}${String(day.getUTCDate()).padStart(2,'0')}`);
            }
            day.setUTCDate(day.getUTCDate()+1);
        }
        const rows=dates.map((trade_date,index)=>({trade_date,open:10.5,high:12,low:9,close:11,volume:100+index}));
        const wide={...chart,source_date:`${dates.at(-1).slice(0,4)}-${dates.at(-1).slice(4,6)}-${dates.at(-1).slice(6)}`,rows};
        const original={...wide,schema:'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1',status:'READY',
            formula_sha256:'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac',
            engine_sha256:'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c',
            sidecar:{sha256:'f'.repeat(64)},marks:[],unresolved_conditions:0,
            lines:{
                '白线':rows.map((row,index)=>({trade_date:row.trade_date,y:(13.1+index/1000).toFixed(3)})),
                '黄线':rows.map((row,index)=>({trade_date:row.trade_date,y:index===50?null:(13.4+index/1000).toFixed(3)})),
            }};
        wide.original_marks=original;
        const host=new Element('div');
        const dispose=renderDailyChart(host,wide);
        const lineStrokes=()=>records.filter(item=>['#FFFFFF','#FBCD2D'].includes(item.color)&&item.width===2);
        const initial=lineStrokes();
        assert.equal(initial.filter(item=>item.color==='#FFFFFF').length,1);
        assert.equal(initial.find(item=>item.color==='#FFFFFF').points.length,120);
        assert.ok(initial.find(item=>item.color==='#FFFFFF').points.every(([,y])=>y>=3&&y<=340*0.74-9));
        assert.equal(initial.filter(item=>item.color==='#FBCD2D').length,2);
        assert.deepEqual(initial.filter(item=>item.color==='#FBCD2D').map(item=>item.points.length),[50,69]);
        assert.ok(initial.filter(item=>item.color==='#FBCD2D').every(stroke=>stroke.points.every(([,y])=>y>=3&&y<=340*0.74-9)));
        assert.match(host.children[3].textContent,/白线/);
        assert.match(host.children[3].textContent,/黄线/);

        records.length=0;
        host.children[0].children[0].onclick();
        const recent=lineStrokes();
        assert.equal(recent.filter(item=>item.color==='#FFFFFF').length,1);
        assert.equal(recent.find(item=>item.color==='#FFFFFF').points.length,60);
        assert.equal(recent.filter(item=>item.color==='#FBCD2D').length,1);
        assert.equal(recent.find(item=>item.color==='#FBCD2D').points.length,60);

        records.length=0;
        wide.original_marks={...original};
        delete wide.original_marks.lines;
        const legacyHost=new Element('div');
        const disposeLegacy=renderDailyChart(legacyHost,wide);
        assert.equal(lineStrokes().length,0);
        disposeLegacy();
        dispose();
    } finally {
        globalThis.document=prior.document;
        globalThis.Option=prior.Option;
        globalThis.ResizeObserver=prior.ResizeObserver;
        globalThis.window=prior.window;
    }
});
