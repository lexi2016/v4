const LEGACY_GROUPS={nav_smallk:'导航小K',original:'原公式',nav_pullback:'导航回踩',nav_breakout:'导航突破'};
const SKILL_GROUPS={skill_r2_b1:'B1回调',skill_r2_nana:'异动缩量 / 娜娜',skill_r2_super_b1:'超级B1',skill_r2_sb1:'SB1',skill_r2_b2:'B2确认',skill_r2_b3:'B3 / 长安',skill_r2_parallel:'双枪 / 重炮',skill_r2_rebuild:'双线回踩 / 重建',skill_r2_platform:'平台蓄势'};
export const GROUPS={...LEGACY_GROUPS};
export function configureGroups(day){for(const key of Object.keys(GROUPS))delete GROUPS[key];Object.assign(GROUPS,day?.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?SKILL_GROUPS:LEGACY_GROUPS)}
export const stateLabel=s=>({TRUE:'数值命中',FALSE:'未命中',UNKNOWN:'待核'}[s]??'未提供');
export const displayName=(row,names={})=>row.enriched_display_name||names[row.symbol]||'名称待核';
export function filterStocks(day,{scope='candidates',query='',group='all',names={}}={}){const q=query.trim().toLowerCase(),skill=day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2';return day.rows.filter(r=>(scope==='all'||r.eligible_candidate)&&(!q||`${r.symbol} ${displayName(r,names)}`.toLowerCase().includes(q))&&(group==='all'||(group==='pending'?(skill?r.r2_pending:Object.values(r.group_states).includes('UNKNOWN')):group==='fifth'?r.in_fifth:group.startsWith('review_')?r.r2_review?.status==='REVIEWED'&&r.r2_review?.decision===({review_keep:'KEEP',review_watch:'WATCH',review_defer:'DEFER'})[group]:r.group_states[group]==='TRUE')))}
export function groupLabels(row){return Object.entries(GROUPS).filter(([k])=>row.group_states[k]==='TRUE').map(([,label])=>label)}
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
