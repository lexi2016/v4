// Sort already materialized descriptive rates. Zero is valid; unknown stays last.
export const RATE_GROUPS=['nav_smallk','original','nav_pullback','nav_breakout'];
export function historyRate(row,group,horizon){
 const selected=RATE_GROUPS.includes(group)?group:RATE_GROUPS.find(g=>row.group_states?.[g]==='TRUE');
 const value=row.history_rates?.[selected]?.[horizon];
 const valid=Number.isSafeInteger(value?.valid)&&value.valid>0&&typeof value.positive_fraction==='number'&&Number.isFinite(value.positive_fraction)&&value.positive_fraction>=0&&value.positive_fraction<=1;
 return {group:selected,value:valid?value.positive_fraction:null,n:value?.valid??null,not_matured:value?.not_matured??null,valid};
}
export function rateLabel(row,group,horizon){const r=historyRate(row,group,horizon);return r.valid?`${(r.value*100).toFixed(1)}% · n=${r.n}`:r.n===0?`未成熟/无有效 · n=0`:'— · n=?';}
export function sortHistoryRates(rows,group,mode){const horizon=mode.slice(0,2),direction=mode.endsWith('_asc')?1:-1;return rows.map((row,index)=>({row,index,rank:historyRate(row,group,horizon)})).sort((a,b)=>Number(b.rank.valid)-Number(a.rank.valid)||(a.rank.valid&&b.rank.valid?(a.rank.value-b.rank.value)*direction:0)||a.index-b.index).map(x=>x.row);}
