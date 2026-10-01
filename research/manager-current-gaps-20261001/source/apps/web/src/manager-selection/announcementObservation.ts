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
  host.replaceChildren(element('h3','公告来源独立研究观察（不改变两条件名单或重点排名）'));
  host.setAttribute('aria-label','公告来源独立研究观察');
  if(!value){delete host.dataset.announcementDate;host.append(element('p','公告输入未提供，状态未知；不是0候选。'));return;}
  host.dataset.announcementDate=value.target_trade_date;
  const status=element('p',`${value.target_trade_date} ｜ HKEX目录：${stateNames[value.status] || raw(value.status)} ｜ ${value.count_known?'HKEX只统计已观察记录，覆盖尚未证明穷尽':'HKEX数量未知，不是已扫描后的0候选'}。`);
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
  host.append(all);
  const eastDocs=value.eastmoney_hk_documents||[];
  const eastStatus=raw(value.eastmoney_hk_status||'NOT_RUN');
  host.append(element('h4','东方财富港股公告（聚合来源；不是 HKEX 官方目录）'));
  host.append(element('p',`Eastmoney HK 状态：${eastStatus}；当前截止前读回 ${eastDocs.length} 条逐篇公告，正文来自已校验的完整内容接口页，附件PDF另行保留。该来源的公告日期/显示时间按原样展示；HKEX 首次发布时间 CANNOT_CONFIRM。`));
  for(const doc of eastDocs){
    const article=element('article');article.dataset.eastmoneyAnnouncement=String(doc.event_id);
    article.append(element('h5',`${raw(doc.symbol)} ${raw(doc.name)} ｜ ${raw(doc.title)}`));
    article.append(element('p',`Eastmoney notice_date：${raw(doc.notice_date)}；display_time：${raw(doc.display_time)}；本地可用时间：${raw(doc.available_at)}。这些是来源字段/取得时间，不代表 HKEX 首次发布时间。`));
    article.append(element('p',`market_code=${raw(doc.market_code)}；stock_code=${raw(doc.stock_code)}；公告编号=${raw(doc.art_code)}；正文 ${number(doc.content_page_count)} 个内容页，${number(String(doc.body_text||'').length)} 个字符；正文 SHA-256 ${raw(doc.body_sha256)}。完整PDF ${number(doc.pdf_page_count)} 页 / ${number(doc.pdf_bytes)} bytes；PDF SHA-256 ${raw(doc.document_sha256)}。PDF文字提取编码未核，正文使用逐页内容接口原文。`));
    const body=element('details');body.dataset.eastmoneyBody=String(doc.event_id);
    body.append(element('summary',`查看完整公告正文（${number(doc.content_page_count)} 页）`));
    for(const page of (Array.isArray(doc.body_pages)?doc.body_pages:[]) as JsonObject[]){
      const pageSection=element('section');pageSection.dataset.eastmoneyBodyPage=String(page.page_index);
      pageSection.append(element('h6',`正文第 ${number(page.page_index)} 页`),element('pre',raw(page.text)));
      body.append(pageSection);
    }
    article.append(body);
    try{
      const url=new URL(String(doc.source_url));
      if(url.protocol==='https:'&&url.hostname==='pdf.dfcfw.com'&&!url.username&&!url.password){
        const link=element('a','打开东方财富公告 PDF 原件');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';article.append(link);
      }
    }catch{article.append(element('p','东方财富PDF链接未核。'));}
    article.append(technical('Eastmoney目录、内容与完整PDF原始引用',doc));host.append(article);
  }
  if(!eastDocs.length)host.append(element('p',eastStatus==='NOT_RUN'?'Eastmoney 港股公告源尚未运行；不能据此断言没有公告。':'当前截止前没有可读回的Eastmoney逐篇公告；查看运行状态和缺口。'));
  host.append(technical('Eastmoney状态、尝试与未解缺口',{capture:value.eastmoney_hk_capture,attempt:value.eastmoney_hk_attempt,gaps:value.eastmoney_hk_gaps}),
    technical('HKEX各轮窗口和未解缺口',{capture_runs:value.capture_runs,gaps:value.gaps}));
}
