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
