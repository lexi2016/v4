// Adapter only: existing frozen rows are passed by reference to the original renderer.
export function adaptProjection(p,e){
 const need=(v,m)=>{if(!v)throw Error(m)},f=p?.formula_result,rows=f?.rows;
 need(p?.symbol===e.symbol&&String(p.data_date)===e.source_date.replaceAll('-',''),'PROJECTION_IDENTITY_DATE');
 need(p.source?.generation_id===e.generation&&p.source?.source_input_sha256===e.input_sha256,'PROJECTION_SOURCE');
 need(f?.formula_sha256===e.formula_sha256&&f.field_count===51&&f.drawing_count===22,'PROJECTION_FORMULA');
 need(p.RESEARCH_ONLY===true&&p.production_allowed===false&&p.buy_gate_updated===false&&p.orders_sent===false&&p.historical_PIT===false,'PROJECTION_BOUNDARY');
 need(Array.isArray(rows)&&rows.length===e.rows&&rows.length>0,'PROJECTION_ROWS');
 let previous=0;for(const r of rows){need(Number.isSafeInteger(r.trade_date)&&r.trade_date>previous&&r.ohlcv?.trade_date===r.trade_date,'PROJECTION_ORDER');previous=r.trade_date;need(r.values&&typeof r.values==='object'&&!Array.isArray(r.values)&&Object.keys(r.values).length===51&&Array.isArray(r.drawings)&&r.drawings.length===22,'PROJECTION_51_22');const d=String(r.trade_date),iso=d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6);need(/^\d{8}$/.test(d)&&Number.isFinite(Date.parse(iso+'T00:00:00Z'))&&new Date(iso+'T00:00:00Z').toISOString().slice(0,10)===iso,'PROJECTION_DATE');for(const k of ['open','high','low','close','vol'])need((typeof r.ohlcv[k]==='number'||typeof r.ohlcv[k]==='string'&&r.ohlcv[k].trim()!=='')&&Number.isFinite(Number(r.ohlcv[k])),'PROJECTION_OHLCV');need(Object.values(r.values).every(v=>v===null||typeof v==='string'||typeof v==='boolean'||typeof v==='number'&&Number.isFinite(v)),'PROJECTION_VALUES');r.drawings.forEach((v,i)=>need(v&&v.id===i+1&&['DRAWTEXT','DRAWICON'].includes(v.kind)&&[null,true,false].includes(v.condition)&&Array.isArray(v.styles)&&v.styles.every(x=>typeof x==='string')&&Object.hasOwn(v,'y')&&Object.hasOwn(v,'payload')&&(v.y===null||typeof v.y==='number'&&Number.isFinite(v.y)||typeof v.y==='string'&&v.y.trim()!==''&&Number.isFinite(Number(v.y)))&&(typeof v.payload==='string'||typeof v.payload==='number'&&Number.isFinite(v.payload))&&(v.kind!=='DRAWICON'||['1','2'].includes(String(v.payload))),'PROJECTION_DRAWING'));}
 need(String(previous)===String(p.data_date),'PROJECTION_TAIL');
 return {symbol:p.symbol,data:{rows},manifest:{formula_sha256:f.formula_sha256},provenance:{source:p.source,source_cache:p.source_cache,renderer_semantics:p.renderer_semantics}};
}
export async function loadProjection(ref,expected,{fetcher=fetch,origin=location.origin,signal}={}){
 const u=new URL(ref.projection_url,origin);if(u.origin!==origin||!['identity','gzip'].includes(ref.encoding)||!Number.isSafeInteger(ref.bytes)||ref.bytes<1||ref.bytes>(ref.encoding==='gzip'?8:32)*1024*1024)throw Error('PROJECTION_REFERENCE');
 async function bounded(response,max){if(!response.ok)throw Error('PROJECTION_HTTP');const reader=response.body.getReader(),parts=[];let n=0;try{while(true){const {done,value}=await reader.read();if(done)break;n+=value.length;if(n>max){await reader.cancel();throw Error('PROJECTION_SIZE')}parts.push(value)}}finally{reader.releaseLock()}const bytes=new Uint8Array(n);let off=0;for(const p of parts){bytes.set(p,off);off+=p.length}return bytes;}
 const raw=await bounded(await fetcher(u.href,{signal,credentials:'same-origin',redirect:'error'}),ref.bytes);if(raw.length!==ref.bytes)throw Error('PROJECTION_SIZE');
 const sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');if(sha!==ref.sha256)throw Error('PROJECTION_HASH');
 const bytes=ref.encoding==='gzip'?await bounded(new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))),64*1024*1024):raw;
 if(ref.decoded_bytes!==undefined&&bytes.length!==ref.decoded_bytes)throw Error('PROJECTION_DECODED_SIZE');
 return adaptProjection(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)),{...expected,rows:ref.row_count,formula_sha256:ref.formula_sha256});
}
