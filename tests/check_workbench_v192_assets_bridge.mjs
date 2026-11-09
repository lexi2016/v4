// Integration over saved real ASGI responses; raw price/history responses stay
// outside Git. Use the accepted runtime's original projection decoder.
import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {makeStockBridge} from '../research/stock_panel_collab_20261030/mac-host/stock/stock-bridge.mjs';
const dir=process.env.V4_TEST_V192_TRANSPORT,root=process.env.V4_TEST_RESEARCH_PANEL_ROOT;
if(!dir||!root)throw Error('EXPLICIT_REAL_TRANSPORT_AND_RUNTIME_REQUIRED');
const m=JSON.parse(await fs.readFile(dir+'/MANIFEST.json','utf8'));
const {loadProjection}=await import(pathToFileURL(root+'/workbench-host/dot/src/projection-view.mjs'));
const frames=[],calls=[];
const container={ownerDocument:{createElement(){const frame={style:{},contentWindow:null};frames.push(frame);return frame}},appendChild(){}};
const fetcher=async url=>{const u=new URL(url),key=u.pathname+u.search;calls.push(key);const file=m.responses[key];if(!file)throw Error('UNEXPECTED_REAL_RESPONSE:'+key);return new Response(await fs.readFile(dir+'/'+file))};
const bridge=makeStockBridge({origin:m.origin,basePath:'/api/v4/research/a-share',fetcher,loadProjection,container});
const v=await bridge.open(m,{v192:m.v192,render:true});
if(v.projection.data.rows.length!==m.expected_rows||v.context.group!=='v192'||v.detail.row.groups!==''||!frames[0].src.includes('/v192-assets/'+m.symbol+'/html?')||v.eventCases.status!=='NOT_MATERIALIZED')throw Error('BRIDGE_CANARY_FAILED');
let rejected=false;try{await bridge.open({...m,generation:'e'.repeat(64)},{v192:m.v192,render:true})}catch{rejected=true}
if(!rejected||frames[0].src!=='about:blank'||!frames[0].hidden)throw Error('STALE_CLEAR_FAILED');
console.log(JSON.stringify({status:'PASS_REAL_API_BYTES_ORIGINAL_PROJECTION_BRIDGE',symbol:m.symbol,rows:v.projection.data.rows.length,values:51,drawings:22,groups:v.detail.row.groups,event_statistics:v.eventCases.status,wrong_generation_cleared:true}));
