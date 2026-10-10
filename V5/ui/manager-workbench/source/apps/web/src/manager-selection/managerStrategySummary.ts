const object=(v:unknown):Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{};
const count=(v:unknown)=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0?String(v):'未知';
export function beijingTime(value:unknown):string {
  if(typeof value!=='string'||!/(Z|[+-]\d{2}:\d{2})$/.test(value))return '未知';
  const date=new Date(value);if(!Number.isFinite(date.getTime()))return '未知';
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date)+' 北京时间';
}
/** Each label stays within its own channel; HK_CONNECT never stands for US. */
export function strategySummary(workspace:unknown,channel:'ANNOUNCEMENT'|'OVERSOLD'):string {
  const channels=object(object(workspace).daily_channels).channels;
  const row=Array.isArray(channels)?object(channels.find(v=>object(v).channel===channel)):{};
  const name=channel==='ANNOUNCEMENT'?'公告':'超跌反弹';
  const amount=count(row.candidate_count);
  const states:Record<string,string>={COMPLETED:'已完成研究评估',VALID_EMPTY:'已完成研究评估',READY:'研究结果已读回',READY_EMPTY:'已完成研究评估',PARTIAL:'部分结果，仍有缺口',CANNOT_CONFIRM:'结果待确认',INPUT_MISSING:'输入未齐',FAILED:'读取失败',NOT_RUN:'尚无本次结果'};
  return `${name} · ${states[String(row.status)]||'尚无可确认结果'} · 研究候选 ${amount}${amount==='未知'?'':' 只'}（展开查看）`;
}
