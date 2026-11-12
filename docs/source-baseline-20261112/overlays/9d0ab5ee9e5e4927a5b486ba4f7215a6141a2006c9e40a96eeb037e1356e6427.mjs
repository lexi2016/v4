const LEGACY_GROUPS={nav_smallk:'导航小K',original:'原公式',nav_pullback:'导航回踩',nav_breakout:'导航突破'};
const SKILL_GROUPS={skill_r2_b1:'B1回调',skill_r2_nana:'异动缩量 / 娜娜',skill_r2_super_b1:'超级B1',skill_r2_sb1:'SB1',skill_r2_b2:'B2确认',skill_r2_b3:'B3 / 长安',skill_r2_parallel:'双枪 / 重炮',skill_r2_rebuild:'双线回踩 / 重建',skill_r2_platform:'平台蓄势'};
export const GROUPS={...LEGACY_GROUPS};
export function configureGroups(day){for(const key of Object.keys(GROUPS))delete GROUPS[key];Object.assign(GROUPS,day?.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?SKILL_GROUPS:LEGACY_GROUPS)}
export const stateLabel=s=>({TRUE:'数值命中',FALSE:'未命中',UNKNOWN:'待核'}[s]??'未提供');
export const displayName=(row,names={})=>row.enriched_display_name||names[row.symbol]||'名称待核';
export function filterStocks(day,{scope='candidates',query='',group='all',names={}}={}){const q=query.trim().toLowerCase(),skill=day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2';return (group==='v192'?(day.v192_group?.rows??[]):day.rows).filter(r=>(group==='v192'||scope==='all'||r.eligible_candidate)&&(!q||`${r.symbol} ${displayName(r,names)}`.toLowerCase().includes(q))&&(group==='all'||group==='v192'||(group==='pending'?(skill?r.r2_pending:Object.values(r.group_states).includes('UNKNOWN')):group==='fifth'?r.in_fifth:group.startsWith('review_')?r.r2_review?.status==='REVIEWED'&&r.r2_review?.decision===({review_keep:'KEEP',review_watch:'WATCH',review_defer:'DEFER'})[group]:r.group_states[group]==='TRUE')))}
export function groupLabels(row){return [...(row.v192_member?['v1.9.2候选']:[]),...Object.entries(GROUPS).filter(([k])=>row.group_states[k]==='TRUE').map(([,label])=>label)]}
export function validateChartMatch(chart,row,day){return chart?.symbol===row.symbol&&chart?.source_date===day.source_date&&chart?.source_generation===day.generation&&chart?.source_input_sha256===day.input_sha256&&chart?.chart_review==='UNKNOWN_NOT_REVIEWED'&&chart?.full_stock_PASS===0}
// The D28 original renderer stores generation/input_sha256 under its source
// names. Check exact original bytes, then adapt those two names in memory only.
export async function loadSkillProjection(ref,expected,{adaptProjection,origin,fetcher=fetch,signal}={}){
 const u=new URL(ref.projection_url,origin),date=expected.source_date.replaceAll('-','');
 const path=`/api/v4/research/workbench/days/${expected.source_date}/skill-r2/assets/${expected.symbol}/projection`;
 if(u.origin!==origin||u.pathname!==path||u.searchParams.get('revision')!==expected.generation||u.searchParams.get('sha256')!==ref.sha256||!/^[a-f0-9]{64}$/.test(ref.sha256)||!['identity','gzip'].includes(ref.encoding)||!Number.isSafeInteger(ref.bytes)||ref.bytes<1||ref.bytes>(ref.encoding==='gzip'?8:32)*1024*1024)throw Error('R2_PROJECTION_REFERENCE');
 async function bounded(response,max){if(!response.ok)throw Error('R2_PROJECTION_HTTP');const reader=response.body.getReader(),parts=[];let n=0;try{for(;;){const {done,value}=await reader.read();if(done)break;n+=value.length;if(n>max){await reader.cancel();throw Error('R2_PROJECTION_SIZE')}parts.push(value)}}finally{reader.releaseLock()}const bytes=new Uint8Array(n);let off=0;for(const p of parts){bytes.set(p,off);off+=p.length}return bytes}
 const raw=await bounded(await fetcher(u.href,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'}),ref.bytes);if(raw.length!==ref.bytes)throw Error('R2_PROJECTION_SIZE');
 const sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');if(sha!==ref.sha256)throw Error('R2_PROJECTION_HASH');
 const bytes=ref.encoding==='gzip'?await bounded(new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))),64*1024*1024):raw;
 const p=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)),source=p?.source;
 if(source?.generation!==expected.generation||source?.input_sha256!==expected.input_sha256||source?.asof!==date||source?.selector_artifact?.sha256!==expected.selector_sha256)throw Error('R2_PROJECTION_SOURCE');
 const mapped={...p,source:{...source,generation_id:source.generation,source_input_sha256:source.input_sha256}};
 return adaptProjection(mapped,{...expected,rows:ref.row_count,formula_sha256:ref.formula_sha256});
}

// Independent model membership never changes the four original group states.
export function validateV192Group(value,day){
 if(value?.schema!=='V4_WORKBENCH_V192_GROUP_V1'||value.group_id!=='v192'||value.source_date!==day.source_date||value.observation_date!==day.observation_date||value.generation!==day.generation||value.input_sha256!==day.input_sha256||value.selector_sha256!==day.source_selector_sha256||value.numeric_manifest?.sha256!==day.numeric_manifest?.sha256||value.numeric_manifest?.path!==day.numeric_manifest?.path||!['READY','READY_EMPTY','PARTIAL','CANNOT_CONFIRM'].includes(value.status)||!Array.isArray(value.rows)||value.rows.length!==value.count||new Set(value.rows.map(row=>row.symbol)).size!==value.count||value.RESEARCH_ONLY!==true||value.historical_PIT!==false||['production_allowed','buy_gate_updated','orders_sent'].some(key=>value[key]!==false)||value.rank_usage_boundary!=='RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY')throw Error('V192_GROUP_IDENTITY_CONFLICT');
 if(value.rows.some(row=>row.v192_member!==true||!/^\d{6}\.(SH|SZ|BJ)$/.test(row.symbol)||!row.group_states||Object.keys(LEGACY_GROUPS).some(key=>!['TRUE','FALSE','UNKNOWN'].includes(row.group_states[key]))||Object.keys(row.history_rates??{}).length))throw Error('V192_ROW_IDENTITY_CONFLICT');
 if(value.status==='CANNOT_CONFIRM'&&value.rows.length)throw Error('V192_UNKNOWN_WITH_ROWS');
 if(['READY','PARTIAL'].includes(value.status)&&!/^[a-f0-9]{64}$/.test(value.source_artifact_sha256??''))throw Error('V192_SOURCE_SHA_MISSING');
 if(value.status==='PARTIAL'){
  const excluded=value.excluded_rows;
  if(!Number.isSafeInteger(value.source_count)||!Number.isSafeInteger(value.valid_count)||!Number.isSafeInteger(value.pending_count)||value.valid_count!==value.count||value.pending_count<=0||value.excluded_count!==value.pending_count||value.source_count!==value.valid_count+value.pending_count||!Array.isArray(excluded)||excluded.length!==value.pending_count||new Set(excluded.map(row=>row.symbol)).size!==excluded.length||excluded.some(row=>!/^\d{6}\.(SH|SZ|BJ)$/.test(row.symbol)||value.rows.some(valid=>valid.symbol===row.symbol)||row.status!=='CANNOT_CONFIRM'||typeof row.reason!=='string'||!row.reason||typeof row.source_checkpoint?.path!=='string'||!row.source_checkpoint.path||!/^[a-f0-9]{64}$/.test(row.source_checkpoint?.sha256??'')))throw Error('V192_PARTIAL_COUNTS_OR_EXCLUSIONS_CONFLICT');
 }
 if(value.status==='READY_EMPTY'&&(value.count!==0||(value.source_count??0)!==0||(value.pending_count??0)!==0))throw Error('V192_EMPTY_WITH_CANDIDATES');
 return value;
}
export function v192Summary(value){
 if(!value)return 'v1.9.2候选来源尚未就绪';
 const source=`信号日 ${value.source_date} → 观察日 ${value.observation_date}`;
 const status=value.status==='CANNOT_CONFIRM'?`来源待核 · 数量未知${value.reason?' · '+value.reason:''}`:value.status==='PARTIAL'?`部分就绪 · 来源 ${value.source_count}只 / 有效 ${value.valid_count}只 / 待核 ${value.pending_count}只；${value.excluded_rows.map(row=>row.symbol+'：'+[row.qualification_reason,row.reason].filter(Boolean).join(' / ')).join('；')}`:value.status==='READY_EMPTY'?'已就绪，本日无候选':`已就绪 · ${value.count}只`;
 return `v1.9.2候选 · ${source} · ${status}。独立模型组；排序分只作复核参考，不能当买入顺序；同定义D+2/D+5统计未接入。`;
}


export function quoteContext(day,row){
 if(!row?.v192_member)return day;
 const ref=day.v192_group?.source_close_reference;
 const bound=ref?.schema==='V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1'&&ref.status==='BOUND_SOURCE_CLOSE'&&ref.source_date===day.source_date&&ref.generation===day.generation&&ref.input_sha256===day.input_sha256&&ref.numeric_manifest?.sha256===day.numeric_manifest?.sha256&&ref.numeric_manifest?.path===day.numeric_manifest?.path&&ref.selector?.sha256===day.source_selector_sha256;
 // Keep the canonical reference object and scope unchanged. A failed model
 // quote binding is missing, never a reference from another date/generation.
 return {...day,source_close_reference:bound?ref:null};
}
