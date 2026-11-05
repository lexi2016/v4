// Local support for a date-certified official daily archive. No source time is
// invented: intraday validity remains entirely owned by the fixed framework.
import * as original from './dot/src/observation-view.mjs';
export * from './dot/src/observation-view.mjs';
export const STATUS_ZH={...original.STATUS_ZH,OFFICIAL_DAILY_ARCHIVE:'官方日包收盘归档（源精确时刻未知）'};
const numeric=v=>typeof v==='number'&&Number.isFinite(v);
export function rowValidity(row,snapshot,metric,now=new Date().toISOString()){
 if(row?.capture_kind!=='OFFICIAL_DAILY_ARCHIVE')return original.rowValidity(row,snapshot,metric,now);
 const key=metric==='volume'?'comparable_volume_shares':metric==='price'?'price':metric==='amount'?'amount_source':'change_percent_source';
 const valid=snapshot?.capture_kind==='OFFICIAL_DAILY_ARCHIVE'&&/^[a-f0-9]{64}$/.test(snapshot.daily_contract_sha256??'')&&row.status==='DATED_DAILY_ARCHIVE'&&row.source_date===snapshot.observation_date&&row.source_asof===null&&row.source_asof_precision==='DATE_ONLY'&&row.currency==='CNY'&&numeric(row[key])&&Date.parse(row.observed_at_upper_bound)<=Date.parse(now)&&snapshot.observation_date<=original.shanghaiParts(now)?.date&&(metric!=='volume'||row.volume_rank_eligible===true)&&(metric!=='percent'||row.percent_change_rank_eligible===true);
 return {valid,state:valid?'OFFICIAL_DAILY_ARCHIVE':'CAPTURE_INVALID',value:valid?row[key]:null};
}
const collator=new Intl.Collator('zh-Hans-CN-u-co-pinyin',{numeric:true,sensitivity:'base'});
export function sortStocks(rows,options={}){
 if(options.snapshot?.capture_kind!=='OFFICIAL_DAILY_ARCHIVE')return original.sortStocks(rows,options);
 const mode=options.mode??'original_groups';if(mode==='original_groups')return [...rows];
 const name=mode.startsWith('name_'),metric=mode.startsWith('price_')?'price':mode.startsWith('amount_')?'amount':mode.startsWith('cumulative')?'volume':'percent',direction=mode.endsWith('_asc')?1:-1,by=new Map(options.snapshot.rows.map(r=>[r.symbol,r]));
 return rows.map((row,index)=>{const value=options.names?.[row.symbol]??row.enriched_display_name;return {row,index,rank:name?{valid:typeof value==='string'&&value.trim()!==''&&value!=='名称待核',value}:rowValidity(by.get(row.symbol),options.snapshot,metric,options.now)}}).sort((a,b)=>Number(b.rank.valid)-Number(a.rank.valid)||(a.rank.valid&&b.rank.valid?(name?collator.compare(a.rank.value,b.rank.value):a.rank.value-b.rank.value)*direction:0)||a.index-b.index).map(x=>x.row);
}

// A separate display role. Never pass these references to intraday rowValidity.
export function displayQuote(stock,day,snapshot,now=new Date().toISOString()){
 const observed=snapshot?.source_date===day?.source_date&&snapshot?.observation_date===day?.observation_date?snapshot.rows?.find(r=>r.symbol===stock.symbol):null;
 const metrics=['price','percent','amount'];
 const validity=Object.fromEntries(metrics.map(metric=>[metric,rowValidity(observed,snapshot,metric,now)]));
 if(metrics.some(metric=>validity[metric].valid))return {row:observed,validity,role:'OBSERVATION',label:`${day.observation_date} 观察快照`};
 const ref=day?.source_close_reference,r=ref?.rows?.[stock.symbol],today=original.shanghaiParts(now)?.date;
 const bound=ref?.schema==='V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1'&&ref.status==='BOUND_SOURCE_CLOSE'&&ref.quote_role==='SOURCE_DATE_CLOSE_REFERENCE'&&ref.source_date===day.source_date&&ref.source_date<day.observation_date&&ref.source_date<=today&&ref.generation===day.generation&&ref.input_sha256===day.input_sha256&&ref.numeric_manifest?.sha256===day.numeric_manifest?.sha256&&/^[a-f0-9]{64}$/.test(ref.selector?.sha256??'')&&ref.source_asof===null&&ref.source_asof_precision==='DATE_ONLY'&&ref.currency==='CNY'&&ref.price_basis==='QFQ_ASOF_'+day.source_date.replaceAll('-','')&&ref.amount_basis==='RAW_TURNOVER'&&ref.RESEARCH_ONLY===true&&['production_allowed','buy_gate_updated','orders_sent'].every(k=>ref[k]===false)&&r?.symbol===stock.symbol;
 if(!bound)return {row:observed,validity,role:'UNKNOWN',label:'报价待核'};
 const keys={price:'price',percent:'change_percent_source',amount:'amount_source'};
 return {row:{...r,currency:ref.currency,source_asof:null},role:'SOURCE_DATE_CLOSE_REFERENCE',label:`${ref.source_date} 收盘参考`,validity:Object.fromEntries(metrics.map(metric=>{const value=r[keys[metric]],valid=numeric(value)&&(metric==='percent'||(metric==='price'?value>0:value>=0));return [metric,{valid,state:valid?'SOURCE_DATE_CLOSE_REFERENCE':'MISSING',value:valid?value:null}]}))};
}
export function sortDisplayStocks(rows,options={}){
 const {day,snapshot,mode='original_groups',now=new Date().toISOString()}=options;
 if(mode==='original_groups'||mode.startsWith('name_')||mode.startsWith('cumulative'))return sortStocks(rows,options);
 const metric=mode.startsWith('price_')?'price':mode.startsWith('amount_')?'amount':mode.startsWith('percent_change_')?'percent':null;
 if(!metric)return [...rows];
 const direction=mode.endsWith('_asc')?1:-1;
 return rows.map((row,index)=>{const quote=displayQuote(row,day,snapshot,now),rank=quote.validity[metric];return {row,index,rank,bucket:rank.valid?(quote.role==='OBSERVATION'?0:1):2}}).sort((a,b)=>a.bucket-b.bucket||(a.rank.valid&&b.rank.valid?(a.rank.value-b.rank.value)*direction:0)||a.index-b.index).map(x=>x.row);
}
