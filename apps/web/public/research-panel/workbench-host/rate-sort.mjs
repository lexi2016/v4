// Display and order the materialized same-group historical counts.
export const RATE_GROUPS=['nav_smallk','original','nav_pullback','nav_breakout'];
export const RATE_GROUP_LABELS={nav_smallk:'小K',original:'原式',nav_pullback:'回踩',nav_breakout:'突破'};
export const MIN_RATE_RANK_SAMPLE=5;
export const isRateSort=mode=>/^d[25]_(asc|desc)$/.test(mode);
export const permitsRateSort=(group,ruleset)=>RATE_GROUPS.includes(group)&&ruleset!=='ZGE_SKILL_DAILY_CANDIDATES_R2';

const count=value=>Number.isSafeInteger(value)&&value>=0?value:null;

export function historyRate(row,group,horizon){
 const value=RATE_GROUPS.includes(group)&&row.group_states?.[group]==='TRUE'?row.history_rates?.[group]?.[horizon]:null;
 const unknown={group,positive:null,n:null,not_matured:null,invalid_matured:null,value:null};
 if(!value)return unknown;
 const n=count(value.valid),positive=count(value.positive),not_matured=count(value.not_matured),total=count(value.total);
 if((n!==null&&positive!==null&&positive>n)||(total!==null&&n!==null&&n>total)
    ||(total!==null&&not_matured!==null&&not_matured>total)
    ||(total!==null&&n!==null&&not_matured!==null&&n+not_matured>total))return unknown;
 const invalid_matured=total!==null&&n!==null&&not_matured!==null?total-n-not_matured:null;
 const fraction=value.positive_fraction;
 const valid=n>0&&positive!==null&&Number.isFinite(fraction)&&fraction>=0&&fraction<=1&&Math.abs(fraction-positive/n)<1e-8;
 return {group,positive,n,not_matured,invalid_matured,value:valid?fraction:null};
}

export function historyRateGroups(row,group){
 const groups=RATE_GROUPS.includes(group)?[group]:RATE_GROUPS;
 return groups.filter(key=>row.group_states?.[key]==='TRUE');
}

export function rateLabel(rate){
 const {positive,n,not_matured,invalid_matured,value}=rate;
 const ratio=`${positive??'待核'}/${n??'待核'}`;
 let summary;
 if(value!==null)summary=`${(value*100).toFixed(1)}% · ${ratio}`;
 else if(n===0)summary=`${ratio} 无有效样本`;
 else summary=`${ratio} · 比率待核`;
 const counts=[`未成熟 ${not_matured??'待核'}`,`已到期无效 ${invalid_matured??'待核'}`];
 const lowSample=n>0&&n<MIN_RATE_RANK_SAMPLE;
 return {summary,counts,lowSample};
}

export function historyRateNote(day,group){
 const cutoff=day?`统计截止 ${day.source_date} 收盘 · 观察 ${day.observation_date}`:'统计截止待核';
 if(!day)return cutoff;
 if(group==='v192')return cutoff+'。v1.9.2 同定义统计未接入。';
 if(day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2')return cutoff+'。R2 同定义统计未物化。';
 if(!permitsRateSort(group,day.ruleset_id))return cutoff+'。D+2 / D+5 显示正收益 / 有效样本。选择分组后可排序。';
 return cutoff+`。排序分组 ${RATE_GROUP_LABELS[group]}。正收益 / 有效样本。有效 ≥${MIN_RATE_RANK_SAMPLE} 按比率，1–${MIN_RATE_RANK_SAMPLE-1} 按样本数。`;
}

function rankBucket(rate){
 if(rate.value!==null&&rate.n>=MIN_RATE_RANK_SAMPLE)return 0;
 if(rate.n>0&&rate.n<MIN_RATE_RANK_SAMPLE)return 1;
 return rate.n===0?2:3;
}

export function sortHistoryRates(rows,group,mode){
 if(!RATE_GROUPS.includes(group)||!isRateSort(mode))return rows;
 const horizon=mode.slice(0,2),direction=mode.endsWith('_asc')?1:-1;
 return rows.map((row,index)=>{
  const rate=historyRate(row,group,horizon);
  return {row,index,rate,bucket:rankBucket(rate)};
 }).sort((a,b)=>a.bucket-b.bucket
    ||(a.bucket===0?(a.rate.value-b.rate.value)*direction||b.rate.n-a.rate.n:0)
    ||(a.bucket===1?b.rate.n-a.rate.n:0)
    ||a.index-b.index).map(item=>item.row);
}
