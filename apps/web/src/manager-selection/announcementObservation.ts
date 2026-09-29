/** Existing manager page's independent official lane. No fetches or ranking. */
import type { AnnouncementObservation, JsonObject } from '../api/managerWorkspace.js';
const stateNames: Record<string,string>={NOT_RUN:'未运行',RUNNING:'运行中（进程存活未核）',FAILED:'最近尝试失败',
  READBACK_FAILED:'来源读回失败',PARTIAL:'部分覆盖',SUCCEEDED:'本次已完成',SUCCEEDED_EMPTY:'本次观察结果为空'};
const raw=(v:unknown)=>typeof v==='string'?v:'UNKNOWN / 未提供';
const number=(v:unknown)=>typeof v==='number' && Number.isFinite(v)?String(v):'未知';
const element=<K extends keyof HTMLElementTagNameMap>(tag:K,text='')=>{
  const node=document.createElement(tag);node.textContent=text;return node;
};
function technical(label:string,value:unknown):HTMLDetailsElement{
  const details=element('details');details.append(element('summary',label));let loaded=false;
  details.addEventListener('toggle',()=>{if(details.open&&!loaded){loaded=true;details.append(element('pre',JSON.stringify(value,null,2)));}});
  return details;
}
function source(doc:JsonObject):HTMLDetailsElement{
  const details=element('details');details.dataset.announcementSource=String(doc.event_id);
  const unread=doc.body_status!=='BODY_PARSED';
  details.append(element('summary',`${raw(doc.title)} ｜ ${unread?'正文待读/未完成，不作利好事实':'已解析原文，仍需研究判断'}`));
  let loaded=false;
  details.addEventListener('toggle',()=>{
    if(!details.open||loaded)return;loaded=true;
    details.append(element('p',`发布：${raw(doc.published_at)}；目录可见/取得：${raw(doc.available_at)}；正文/记录取得：${raw(doc.retrieved_at)}。保留原始时区。`));
    try{
      const u=new URL(String(doc.source_url));
      if(u.protocol==='https:' && !u.username && !u.password){
        const link=element('a','打开官方原公告');link.href=u.href;link.target='_blank';link.rel='noopener noreferrer';details.append(link);
      }
    }catch{details.append(element('p','来源链接未核'));}
    details.append(element('p',`查询 cutoff：${raw(doc.query_cutoff)}；正文 SHA：${raw(doc.document_sha256)}；正文状态：${raw(doc.body_status)}。`));
    for(const claim of (doc.body_claims || []) as JsonObject[]){
      const support=(claim.support || {}) as JsonObject;
      if(claim.research_note)details.append(element('p',`研究观察条件：${raw(claim.research_note)}`));
      details.append(element('p',`原文命题：${raw(claim.disposition)}；不推定价格影响。`),element('blockquote',raw(support.quote)));
    }
    if(unread)details.append(element('p',`待读原因：${raw(doc.body_reason)}。目录标题不是已证实的利好/利空结论。`));
    details.append(technical('原件引用、run/revision 与校验 SHA',doc));
  });
  return details;
}
export function renderAnnouncementObservation(host:HTMLElement,value:AnnouncementObservation|undefined):void{
  host.replaceChildren(element('h3','官方公告独立研究观察（不改变两条件名单或重点排名）'));
  host.setAttribute('aria-label','官方公告独立研究观察');
  if(!value){delete host.dataset.announcementDate;host.append(element('p','公告输入未提供，状态未知；不是0候选。'));return;}
  host.dataset.announcementDate=value.target_trade_date;
  const status=element('p',`${value.target_trade_date} ｜ ${stateNames[value.status] || raw(value.status)} ｜ ${value.count_known?'只统计已观察记录，覆盖尚未证明穷尽':'数量未知，不是已扫描后的0候选'}。`);
  status.setAttribute('role','status');host.append(status);
  host.append(element('p',`读取截止：${value.research_cutoff}；超跌参考完整交易日：${value.prior_session}。盘中量价 UNKNOWN，等待独立确认；不等于买入判断。`));
  const attempt=value.latest_attempt;
  host.append(element('p',attempt?`最近尝试：${raw(attempt.started_at)} → ${raw(attempt.finished_at)}；${raw(attempt.state)}；${raw(attempt.execution_kind)}。`:'无原 owner 尝试记录，不能推定自动运行已成功。'));
  if(attempt)host.append(technical('最近尝试、失败原因与请求预算',attempt));
  const coverage=value.coverage;
  host.append(element('p',`发行人范围 ${number(coverage.native_master_count)}；已尝试查询 ${number(coverage.queried_issuer_count)}（有效目录响应 ${number(coverage.successfully_observed_issuer_count)}）；未尝试 ${Array.isArray(coverage.pending_issuers)?coverage.pending_issuers.length:'未知'}。`),
    element('p',`目录服务端翻页穷尽：${raw(coverage.directory_exhaustion)}；排队正文 ${number(coverage.pending_document_count)}。未查询、失败与零公告不同。`));
  host.append(technical('逐发行人查询截止、待查与失败覆盖',coverage));
  const groups=new Map<string,JsonObject[]>();
  for(const row of [...value.observations,...value.pending_observations]){
    const key=String(row.symbol);const list=groups.get(key)||[];list.push(row);groups.set(key,list);
  }
  for(const [symbol,rows] of groups){
    const article=element('article');article.dataset.announcementSymbol=symbol;
    article.append(element('h4',`${symbol} ${raw(rows[0].name)}`));
    const verified=rows.some(r=>r.observation_status==='PRIOR_OVERSOLD_OFFICIAL_OBSERVATION');
    article.append(element('p',verified?'此前完整日超跌 + 今天官方公告已观察；与当日放量是否成立分开。':'此前超跌证据尚未核齐，保留公告研究，不标成已满足超跌。'));
    for(const row of rows)article.append(source(row));
    article.append(technical('此前超跌来源与独立量价 UNKNOWN',rows.map(r=>({prior_session:r.prior_session,prior_oversold_evidence:r.prior_oversold_evidence,
      screen_input_identity:r.screen_input_identity,screen_authority:r.screen_authority,intraday_price_volume:r.intraday_price_volume}))));
    host.append(article);
  }
  if(!groups.size)host.append(element('p',value.count_known?'已读范围内暂无可标注的“此前超跌＋今日公告”记录；未读范围未知。':'尚不能判断是否存在“此前超跌＋今日公告”。'));
  const all=element('details');all.append(element('summary',`全部已观察官方文档（${value.official_documents.length}，不是全市场公告总数）`));
  for(const doc of value.official_documents)all.append(element('h4',`${raw(doc.symbol)} ${raw(doc.name)}`),source(doc));
  host.append(all,technical('各轮窗口和未解缺口',{capture_runs:value.capture_runs,gaps:value.gaps}));
}
