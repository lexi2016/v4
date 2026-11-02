// Local support for a date-certified official daily archive. No source time is
// invented: intraday validity remains entirely owned by the fixed framework.
import * as original from './dot/src/observation-view.mjs';
export * from './dot/src/observation-view.mjs';
export const STATUS_ZH={...original.STATUS_ZH,OFFICIAL_DAILY_ARCHIVE:'官方日包收盘归档（源精确时刻未知）',SOURCE_ERROR:'观察报价源不可用'};
const numeric=v=>typeof v==='number'&&Number.isFinite(v);
export function rowValidity(row,snapshot,metric,now=new Date().toISOString()){
 if(row?.status==='SOURCE_ERROR'&&snapshot&&/^[a-f0-9]{64}$/.test(snapshot.daily_contract_sha256??''))
  return {valid:false,state:'SOURCE_ERROR',value:null};
 if(row?.capture_kind!=='OFFICIAL_DAILY_ARCHIVE')return original.rowValidity(row,snapshot,metric,now);
 const key=metric==='volume'?'comparable_volume_shares':metric==='price'?'price':metric==='amount'?'amount_source':'change_percent_source';
 const valid=snapshot?.capture_kind==='OFFICIAL_DAILY_ARCHIVE'&&/^[a-f0-9]{64}$/.test(snapshot.daily_contract_sha256??'')&&row.status==='DATED_DAILY_ARCHIVE'&&row.source_date===snapshot.observation_date&&row.source_asof===null&&row.source_asof_precision==='DATE_ONLY'&&row.currency==='CNY'&&numeric(row[key])&&Date.parse(row.observed_at_upper_bound)<=Date.parse(now)&&snapshot.observation_date<=original.shanghaiParts(now)?.date&&(metric!=='volume'||row.volume_rank_eligible===true)&&(metric!=='percent'||row.percent_change_rank_eligible===true);
 return {valid,state:valid?'OFFICIAL_DAILY_ARCHIVE':'CAPTURE_INVALID',value:valid?row[key]:null};
}

export const ARCHIVE_REASON_ZH={ARCHIVE_SOURCE_FLAGS_UNCONFIRMED:'归档来源身份待核',ARCHIVE_COVERAGE_UNAVAILABLE:'归档覆盖待核',
 ARCHIVE_DUPLICATE_IDENTITY:'归档代码重复待核',ARCHIVE_COVERAGE_MISSING:'归档投影未接入，不等同原行情缺失',
 ARCHIVE_IDENTITY_CONFLICT:'归档名称身份冲突',CANDIDATE_NAME_CONFLICT:'名单与归档名称不一致',
 ARCHIVE_DATE_CONFLICT:'归档日期身份不符',ARCHIVE_PRICE_UNAVAILABLE:'归档价格状态待核'};

export function validateSourceDayArchive(archive,day,artifactRef){
 const sha=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
 if(!archive)return null;
 if(archive.schema!=='V4_WORKBENCH_SOURCE_DAY_ARCHIVE_V1'||archive.source_date!==day.source_date||
  archive.source_time!=='UNKNOWN_DATE_ONLY'||archive.generation!==day.generation||archive.input_sha256!==day.input_sha256||
  archive.numeric_manifest?.sha256!==day.numeric_manifest?.sha256||archive.numeric_manifest?.path!==day.numeric_manifest?.path||
  !sha(archive.artifact?.sha256)||typeof archive.artifact?.path!=='string'||!archive.artifact.path.startsWith('/')||archive.artifact.sha256!==artifactRef?.sha256||
  archive.artifact.path!==artifactRef?.path||archive.historical_PIT!==false||archive.RESEARCH_ONLY!==true||
  ['production_allowed','buy_gate_updated','orders_sent'].some(k=>archive[k]!==false))throw Error('SOURCE_DAY_ARCHIVE_BINDING');
 const expected=new Map(day.rows.map(row=>[row.symbol,row.enriched_display_name??null])),seen=new Set();
 if(!Array.isArray(archive.rows)||archive.rows.length!==expected.size||expected.size!==day.rows.length)throw Error('SOURCE_DAY_ARCHIVE_SCOPE');
 for(const row of archive.rows){
  if(!expected.has(row.symbol)||seen.has(row.symbol)||row.candidate_name!==expected.get(row.symbol)||row.source_date!==day.source_date||row.currency!=='CNY'||
   !['READY','PARTIAL','UNKNOWN'].includes(row.status))throw Error('SOURCE_DAY_ARCHIVE_IDENTITY');
  if(row.status!=='UNKNOWN'&&(row.archive_identity_status!=='EXACT_CODE_NAME'||row.archive_name!==row.candidate_name||
    row.directory_name!==row.archive_name))throw Error('SOURCE_DAY_ARCHIVE_NAME_IDENTITY');
  seen.add(row.symbol);
  const fields=[row.price,row.change_percent_source,row.amount_source];
  if(fields.some(value=>value!==null&&!numeric(value))||row.price!==null&&row.price<=0||row.amount_source!==null&&row.amount_source<0||
   row.status==='READY'&&fields.some(value=>value===null)||row.status==='UNKNOWN'&&(fields.some(value=>value!==null)||typeof row.reason!=='string')||
   row.status==='PARTIAL'&&fields.every(value=>value!==null))throw Error('SOURCE_DAY_ARCHIVE_VALUE');
 }
 return archive;
}

export function archiveRowValidity(row,archive,metric){
 const key=metric==='price'?'price':metric==='amount'?'amount_source':metric==='percent'?'change_percent_source':null;
 const valid=key!==null&&row?.source_date===archive?.source_date&&['READY','PARTIAL'].includes(row?.status)&&
  row.currency==='CNY'&&numeric(row[key])&&(metric!=='price'||row.price>0)&&(metric!=='amount'||row.amount_source>=0);
 return {valid,state:valid?'SOURCE_DAY_ARCHIVE':row?.reason??'MISSING',value:valid?row[key]:null};
}

export function listQuoteSource(snapshot,archive,now=new Date().toISOString()){
 const live=(snapshot?.rows??[]).some(row=>['price','percent','amount'].some(metric=>rowValidity(row,snapshot,metric,now).valid));
 return live||!archive?'OBSERVATION':'SOURCE_DAY_ARCHIVE';
}

export function hasBoundTargetDayStock(meta,day,symbol){
 if(!day||typeof day.source_date!=='string')return false;
 return meta?.symbol===symbol&&meta.status==='READY_FOR_RESEARCH_REVIEW'&&meta.source_date===day.source_date&&
  meta.generation===day.generation&&meta.input_sha256===day.input_sha256&&String(meta.last_date)===day.source_date.replaceAll('-','')&&
  typeof day.numeric_manifest?.path==='string'&&day.numeric_manifest.path.startsWith('/')&&/^[a-f0-9]{64}$/.test(day.numeric_manifest?.sha256??'')&&
  meta.numeric_manifest?.path===day.numeric_manifest.path&&meta.numeric_manifest?.sha256===day.numeric_manifest.sha256&&
  meta.chart_status==='READY'&&meta.historical_PIT===false&&meta.RESEARCH_ONLY===true&&
  ['production_allowed','buy_gate_updated','orders_sent'].every(key=>meta[key]===false)&&/^[a-f0-9]{64}$/.test(meta.assets?.html?.sha256??'');
}

export function sortSourceDayArchive(rows,{archive,mode='original_groups',names={}}={}){
 if(mode==='original_groups')return [...rows];
 if(mode.startsWith('name_'))return original.sortStocks(rows,{mode,names});
 const metric=mode.startsWith('price_')?'price':mode.startsWith('amount_')?'amount':mode.startsWith('percent_change_')?'percent':null;
 if(!metric)return [...rows];
 const by=new Map((archive?.rows??[]).map(row=>[row.symbol,row])),direction=mode.endsWith('_asc')?1:-1;
 return rows.map((row,index)=>({row,index,rank:archiveRowValidity(by.get(row.symbol),archive,metric)}))
  .sort((a,b)=>Number(b.rank.valid)-Number(a.rank.valid)||(a.rank.valid&&b.rank.valid?(a.rank.value-b.rank.value)*direction:0)||a.index-b.index)
  .map(item=>item.row);
}
const collator=new Intl.Collator('zh-Hans-CN-u-co-pinyin',{numeric:true,sensitivity:'base'});
export function sortStocks(rows,options={}){
 if(options.snapshot?.capture_kind!=='OFFICIAL_DAILY_ARCHIVE')return original.sortStocks(rows,options);
 const mode=options.mode??'original_groups';if(mode==='original_groups')return [...rows];
 const name=mode.startsWith('name_'),metric=mode.startsWith('price_')?'price':mode.startsWith('amount_')?'amount':mode.startsWith('cumulative')?'volume':'percent',direction=mode.endsWith('_asc')?1:-1,by=new Map(options.snapshot.rows.map(r=>[r.symbol,r]));
 return rows.map((row,index)=>{const value=options.names?.[row.symbol]??row.enriched_display_name;return {row,index,rank:name?{valid:typeof value==='string'&&value.trim()!==''&&value!=='名称待核',value}:rowValidity(by.get(row.symbol),options.snapshot,metric,options.now)}}).sort((a,b)=>Number(b.rank.valid)-Number(a.rank.valid)||(a.rank.valid&&b.rank.valid?(name?collator.compare(a.rank.value,b.rank.value):a.rank.value-b.rank.value)*direction:0)||a.index-b.index).map(x=>x.row);
}
