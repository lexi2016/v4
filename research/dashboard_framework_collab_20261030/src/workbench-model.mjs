export const GROUPS={nav_smallk:'导航小K',original:'原公式',nav_pullback:'导航回踩',nav_breakout:'导航突破'};
export const stateLabel=s=>({TRUE:'数值命中',FALSE:'未命中',UNKNOWN:'待核'}[s]??'未提供');
export const displayName=(row,names={})=>row.enriched_display_name||names[row.symbol]||'名称待核';
export function filterStocks(day,{scope='candidates',query='',group='all',names={}}={}){const q=query.trim().toLowerCase();return day.rows.filter(r=>(scope==='all'||r.eligible_candidate)&&(!q||`${r.symbol} ${displayName(r,names)}`.toLowerCase().includes(q))&&(group==='all'||(group==='pending'?Object.values(r.group_states).includes('UNKNOWN'):group==='fifth'?r.in_fifth:r.group_states[group]==='TRUE')))}
export function groupLabels(row){return Object.entries(GROUPS).filter(([k])=>row.group_states[k]==='TRUE').map(([,label])=>label)}
export function validateChartMatch(chart,row,day){return chart?.symbol===row.symbol&&chart?.source_date===day.source_date&&chart?.source_generation===day.generation&&chart?.source_input_sha256===day.input_sha256&&chart?.chart_review==='UNKNOWN_NOT_REVIEWED'&&chart?.full_stock_PASS===0}
