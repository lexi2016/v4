// Individual-stock seam only. The host explicitly supplies endpoint/context and
// the pinned framework loadProjection; this file performs GETs and no writes.
export const FRAMEWORK_COMMIT='0ae4a66d90c12a0d0335b5f7f65b528879c5e9cf';
export const FORMULA_SHA='d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac';
const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const sameRef=(a,b)=>typeof a?.path==='string'&&a.path===b?.path&&sha(a.sha256)&&a.sha256===b?.sha256;
export function compactDate(value){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))throw Error('ISO_SOURCE_DATE_REQUIRED');
  const parsed=new Date(value+'T00:00:00Z');
  if(!Number.isFinite(parsed.valueOf())||parsed.toISOString().slice(0,10)!==value)throw Error('INVALID_SOURCE_DATE');
  return value.replaceAll('-','');
}
function context(value){
  compactDate(value?.source_date);compactDate(value?.observation_date);
  if(!/^\d{6}\.(?:SH|SZ|BJ)$/.test(value?.symbol)||!sha(value?.generation)||!sha(value?.input_sha256))throw Error('EXPLICIT_STOCK_IDENTITY_REQUIRED');
  if(value.numeric_manifest&&!sameRef(value.numeric_manifest,value.numeric_manifest))throw Error('INVALID_NUMERIC_REVISION');
  return Object.freeze({...value});
}
async function bounded(response,maxBytes){
  if(!response.ok)throw Error('STOCK_SOURCE_UNAVAILABLE');
  const reader=response.body.getReader(),parts=[];let n=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;n+=value.length;if(n>maxBytes){await reader.cancel();throw Error('STOCK_SOURCE_TOO_LARGE')}parts.push(value)}}finally{reader.releaseLock()}
  const bytes=new Uint8Array(n);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length}return bytes;
}
export function makeStockBridge({origin,basePath,fetcher,loadProjection,container=null,eventTarget=null}){
  if(!origin||typeof fetcher!=='function'||typeof loadProjection!=='function'||!basePath?.startsWith('/')||basePath.startsWith('//'))throw Error('EXPLICIT_HOST_DEPENDENCIES_REQUIRED');
  const host=new URL(origin);if(!['http:','https:'].includes(host.protocol)||host.origin!==origin)throw Error('INVALID_HOST_ORIGIN');
  const root=new URL(basePath.replace(/\/$/,'')+'/',origin);if(root.origin!==origin)throw Error('SAME_ORIGIN_REQUIRED');
  let serial=0,controller=null,current=null,frame=null,rendererBinding=null;
  function scoped(path){const u=new URL(path,root);if(u.origin!==origin||!u.pathname.startsWith(root.pathname))throw Error('OUTSIDE_STOCK_SCOPE');return u}
  async function get(path,signal,max=2*1024*1024){const u=scoped(path);const raw=await bounded(await fetcher(u.href,{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store',signal}),max);return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw))}
  function assetURL(asset,kind,c){
    if(!sha(asset?.sha256)||typeof asset.url!=='string')throw Error('UNBOUND_CHART_ASSET');
    const u=scoped(asset.url);if(u.pathname!==root.pathname+'original-chart/'+kind)throw Error('WRONG_ASSET_ENDPOINT');
    for(const [key,value]of Object.entries({date:compactDate(c.source_date),symbol:c.symbol,generation:c.generation,input_sha256:c.input_sha256,sha256:asset.sha256}))if(u.searchParams.get(key)!==value)throw Error('ASSET_IDENTITY_CONFLICT');
    return u;
  }
  function invalidate(){rendererBinding=null;if(frame){frame.hidden=true;frame.src='about:blank';}}
  function bind(){if(!container)throw Error('EXPLICIT_RENDERER_CONTAINER_REQUIRED');if(!frame){frame=container.ownerDocument.createElement('iframe');frame.title='同源原式51变量/22绘图';frame.style.width='100%';frame.style.height='1650px';frame.style.border='0';frame.hidden=true;container.appendChild(frame)}return frame}
  const OriginalFullChart={
    bind,
    setStock(adapted){
      const b=rendererBinding,p=adapted?.provenance?.source;
      if(!b||adapted.symbol!==b.context.symbol||adapted.manifest?.formula_sha256!==b.descriptor.formula_sha256
        ||p?.generation_id!==b.context.generation||p?.source_input_sha256!==b.context.input_sha256
        ||adapted.data?.rows?.length!==b.descriptor.rows){++serial;controller?.abort();current=null;invalidate();throw Error('RENDERER_CONTEXT_UNBOUND')}
      const target=bind(),mine=serial;target.hidden=false;
      target.onload=()=>{if(mine!==serial||!rendererBinding||target.hidden)return;const w=target.contentWindow;
        // Only forward the original renderer's chosen date; never recalculate it.
        if(w?.choose&&!w.choose.stockBridgeWrapped){const original=w.choose;const wrapped=function(i){const result=original.apply(this,arguments);const row=w.RESEARCH_PANEL_STATE?.rows?.[i];if(row&&eventTarget){eventTarget.dispatchEvent(new CustomEvent('original-chart-date',{detail:{symbol:b.context.symbol,date:row.trade_date}}))}return result};wrapped.stockBridgeWrapped=true;w.choose=wrapped;}
      };
      target.src=assetURL(b.descriptor.assets.html,'html',b.context).href;
      return {status:'BOUND_ORIGINAL_RENDERER',symbol:b.context.symbol};
    },
    clear(){++serial;controller?.abort();current=null;invalidate()},
    setWindow(value){const w=frame?.contentWindow;if(!rendererBinding||!w?.setOriginalWindow||!w.RESEARCH_PANEL_STATE)throw Error('ORIGINAL_RENDERER_NOT_READY');if(value!=='all'&&(!Number.isSafeInteger(value)||value<1))throw Error('INVALID_RENDERER_WINDOW');w.setOriginalWindow(value==='all'?0:value,w.RESEARCH_PANEL_STATE.rows.length);},
  };
  async function open(value,options={}){
    const mine=++serial;controller?.abort();controller=new AbortController();const signal=controller.signal;invalidate();current=null;
    const active=()=>{if(mine!==serial||signal.aborted)throw Error('STALE_STOCK_CONTEXT')};
    try{
      const c=context(value),requestedGroup=options?.group??c.group,horizon=options?.horizon??c.horizon??'d2',render=options?.render??Boolean(container);
      if((requestedGroup!=null&&!['all','original','nav_smallk','nav_pullback','nav_breakout'].includes(requestedGroup))||!['d2','d5'].includes(horizon))throw Error('INVALID_EVENT_SELECTION');
      const query=new URLSearchParams({date:compactDate(c.source_date),symbol:c.symbol,generation:c.generation,input_sha256:c.input_sha256});
      const detail=await get('daily-product?'+query,signal);active();
      if(detail.status!=='READY'||detail.data_date!==compactDate(c.source_date)||detail.row?.data_date!==detail.data_date||detail.row?.symbol!==c.symbol||detail.source_generation!==c.generation||detail.source_identity?.input_sha256!==c.input_sha256||!sameRef(detail.manifest,detail.manifest)||(c.numeric_manifest&&!sameRef(detail.manifest,c.numeric_manifest)))throw Error('NUMERIC_CONTEXT_CONFLICT');
      for(const key of ['production_allowed','buy_gate_updated','orders_sent'])if(detail[key]!==false)throw Error('NUMERIC_BOUNDARY_CONFLICT');
      if(detail.research_only!==true)throw Error('NUMERIC_BOUNDARY_CONFLICT');
      const ownGroups=typeof detail.row.groups==='string'?detail.row.groups.split('|').filter(Boolean):[];
      if(!ownGroups.length||new Set(ownGroups).size!==ownGroups.length||ownGroups.some(g=>!['original','nav_smallk','nav_pullback','nav_breakout'].includes(g)))throw Error('CURRENT_EVENT_GROUP_UNBOUND');
      const group=requestedGroup&&requestedGroup!=='all'?requestedGroup:ownGroups[0];
      if(!ownGroups.includes(group))throw Error('SELECTED_GROUP_NOT_IN_ACCEPTED_ROW');
      const numeric=detail.manifest;
      const descriptor=await get('original-chart?'+query,signal);active();
      if(descriptor.status!=='READY'||descriptor.symbol!==c.symbol||descriptor.data_date!==detail.data_date||descriptor.source_generation!==c.generation||descriptor.input_sha256!==c.input_sha256||!sameRef(descriptor.product_manifest,numeric)||descriptor.formula_sha256!==FORMULA_SHA||descriptor.values_per_row!==51||descriptor.drawings_per_row!==22)throw Error('CHART_CONTEXT_CONFLICT');
      const projectionURL=assetURL(descriptor.assets.projection,'projection',c);assetURL(descriptor.assets.html,'html',c);
      const raw=await bounded(await fetcher(projectionURL.href,{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store',signal}),32*1024*1024);active();
      const encoding=raw[0]===0x1f&&raw[1]===0x8b?'gzip':'identity';if(encoding==='gzip'&&raw.length>8*1024*1024)throw Error('PROJECTION_TOO_LARGE');
      const projectionReference={projection_url:projectionURL.href,sha256:descriptor.assets.projection.sha256,bytes:raw.length,encoding,row_count:descriptor.rows,formula_sha256:descriptor.formula_sha256};
      // Exact actual byte count, not guessed metadata. The pinned framework
      // verifies SHA/decoded bounds/51+22 on this already fetched buffer, so it
      // performs no second HTTP download.
      const adapted=await loadProjection(projectionReference,{symbol:c.symbol,source_date:c.source_date,generation:c.generation,input_sha256:c.input_sha256},{origin,signal,fetcher:async u=>{if(String(u)!==projectionURL.href)throw Error('PROJECTION_SCOPE_CHANGED');return new Response(raw)}});active();
      const [company,cases]=await Promise.all([get('company-materials?'+query,signal),get('event-cases?'+new URLSearchParams({date:compactDate(c.source_date),symbol:c.symbol,group,horizon}),signal)]);active();
      if(!['PARTIAL_RECEIVED','NOT_MATERIALIZED'].includes(company.status)||company.symbol!==c.symbol||company.data_date!==detail.data_date||(company.status==='PARTIAL_RECEIVED'&&(!sameRef(company.numeric_manifest,numeric)||company.source_generation!==c.generation||company.input_sha256!==c.input_sha256)))throw Error('COMPANY_CONTEXT_CONFLICT');
      if(!['READY','IN_PROGRESS','NOT_MATERIALIZED'].includes(cases.status)||cases.symbol!==c.symbol||cases.data_date!==detail.data_date||(cases.status==='READY'&&(!sameRef(cases.numeric_manifest,numeric)||cases.group!==group||cases.horizon!==horizon||cases.source_generation!==c.generation||cases.source_identity?.input_sha256!==c.input_sha256)))throw Error('EVENT_CONTEXT_CONFLICT');
      for(const item of [descriptor,company,cases]){if(item.research_only!==true||['production_allowed','buy_gate_updated','orders_sent'].some(key=>item[key]!==false))throw Error('STOCK_BOUNDARY_CONFLICT')}
      rendererBinding={context:c,descriptor};
      current={status:'STOCK_INTERFACE_BOUND',context:Object.freeze({...c,group,horizon}),numeric_manifest:numeric,revision:numeric.sha256,detail,descriptor,projectionReference,projection:adapted,
        company:{status:company.status,materials:company.materials??null,source:company.material_ref??null,framework_company_validator:'EXTERNAL_VALIDATOR_REQUIRED'},eventCases:cases,
        observation_date_binding:'HOST_SUPPLIED_NOT_ASSERTED_BY_STOCK_API',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
      if(render)OriginalFullChart.setStock(adapted);return current;
    }catch(error){if(mine===serial){current=null;invalidate()}throw error}
  }
  return {open,OriginalFullChart,get current(){return current},clear(){++serial;controller?.abort();current=null;invalidate()}};
}
