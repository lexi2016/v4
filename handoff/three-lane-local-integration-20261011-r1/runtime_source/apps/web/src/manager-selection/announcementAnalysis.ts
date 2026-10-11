/** Readable view for the previously reviewed, date-bound Eastmoney analysis. */
import type { ManagerAnnouncementAnalysis, AnnouncementAnalysisObject } from '../api/managerAnnouncementAnalysis.js';
import { verifiedAnnouncementResearchResult } from './dailyChannels.js';

const text=(value:unknown,fallback='未提供')=>typeof value==='string'&&value?value:
  typeof value==='number'&&Number.isFinite(value)?String(value):fallback;
const object=(value:unknown):AnnouncementAnalysisObject=>
  value&&typeof value==='object'&&!Array.isArray(value)?value as AnnouncementAnalysisObject:{};
const list=(value:unknown):AnnouncementAnalysisObject[]=>
  Array.isArray(value)?value.filter((row):row is AnnouncementAnalysisObject=>Boolean(row)&&typeof row==='object'&&!Array.isArray(row)):[];
const strings=(value:unknown):string[]=>Array.isArray(value)?value.filter((item):item is string=>typeof item==='string'):[];
const issuerNames=(value:unknown)=>Array.isArray(value)?value.map(item=>{
  if(typeof item==='string')return item;
  const issuer=object(item);const code=text(issuer.code,'');const name=text(issuer.name,'');
  return code&&name?`${code} ${name}`:code||name;
}).filter(Boolean).join('、'):'未提供';
const dateToken=(value:string)=>/^\d{4}-\d{2}-\d{2}$/.test(value)?value.replaceAll('-',''):'';
const element=<K extends keyof HTMLElementTagNameMap>(tag:K,content='')=>{
  const node=document.createElement(tag);node.textContent=content;return node;
};
function sourceLink(value:unknown,label:string):HTMLAnchorElement|null{
  if(typeof value!=='string')return null;
  try{
    const url=new URL(value);
    if(url.protocol!=='https:'||url.username||url.password||
        !['np-cnotice-stock.eastmoney.com','np-anotice-stock.eastmoney.com','pdf.dfcfw.com'].includes(url.hostname))return null;
    const link=element('a',label);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';return link;
  }catch{return null;}
}
function details(label:string,value:unknown):HTMLDetailsElement{
  const node=element('details');node.append(element('summary',label));
  const pre=element('pre',JSON.stringify(value,null,2));node.append(pre);return node;
}
const dispositionLabel=(value:unknown)=>{
  const status=text(value,'NOT_ASSESSED');
  return status==='SELECTED_EVENT'?'入选事件研究':status==='SELECTED_PERFORMANCE'?'入选业绩研究':
    status==='CONDITIONAL_WATCH'?'条件观察':status==='NOT_SELECTED'?'本次未入选':
    status==='NOT_ASSESSED'?'未评估':'状态未识别';
};
/** Independent readback gate: a sealed selection alone is NOT a reviewed owner import. */
export function verifiedAnnouncementOwnerSelection(value: unknown): {verified:boolean; reason:string; retrospective:boolean} {
  const root=object(value),analysis=object(root.analysis),selection=object(analysis.stock_selection);
  const chain=object(root.consumption_validation),receipt=object(root.owner_import_receipt);
  const sha=(raw:unknown)=>typeof raw==='string'&&/^[0-9a-f]{64}$/.test(raw);
  const run=(raw:unknown)=>typeof raw==='string'&&/^[0-9a-f]{32}$/.test(raw);
  const fail=(reason:string)=>({verified:false,reason,retrospective:false});
  const target=text(root.target_trade_date,''),publication=text(root.publication_date,'');
  if(analysis.status!=='VERIFIED'||selection.status!=='VERIFIED')return fail('ANNOUNCEMENT_SELECTION_NOT_VERIFIED');
  if(chain.validation_status!=='VERIFIED'||!['VERIFIED','CONSUMED','NOT_CONSUMED_AFTER_CUTOFF'].includes(text(chain.status,'')))
    return fail('ANNOUNCEMENT_OWNER_CHAIN_NOT_VERIFIED');
  if(receipt.status!=='VERIFIED'||receipt.owner!=='ManagerResearchJobService.import_announcement_analysis'||
      !sha(receipt.sha256)||!sha(receipt.product_sha256)||!sha(receipt.source_manifest_sha256)||
      !run(receipt.evidence_run_id)||!sha(receipt.handoff_manifest_sha256)||
      !sha(receipt.agent_judgment_receipt_sha256)||!sha(chain.owner_import_receipt_sha256)||
      !sha(chain.handoff_manifest_sha256)||!sha(chain.agent_judgment_receipt_sha256))
    return fail('ANNOUNCEMENT_OWNER_RECEIPT_UNVERIFIED');
  if(!/^\d{8}$/.test(target)||dateToken(publication)===''||
      chain.target_trade_date!==target||chain.publication_date!==publication||
      receipt.target_trade_date!==target||receipt.publication_date!==publication||
      receipt.sha256!==chain.owner_import_receipt_sha256||
      receipt.product_sha256!==chain.product_sha256||analysis.product_sha256!==chain.product_sha256||
      receipt.source_manifest_sha256!==chain.source_manifest_sha256||
      analysis.source_manifest_sha256!==chain.source_manifest_sha256||
      receipt.evidence_run_id!==chain.evidence_run_id||
      receipt.handoff_manifest_sha256!==chain.handoff_manifest_sha256||
      receipt.agent_judgment_receipt_sha256!==chain.agent_judgment_receipt_sha256||
      selection.product_sha256!==chain.product_sha256||
      selection.source_manifest_sha256!==chain.source_manifest_sha256||
      !sha(selection.selection_sha256)||
      object(selection.source_binding).target_trade_date!==target||
      object(selection.source_binding).publication_date!==publication)
    return fail('ANNOUNCEMENT_OWNER_RUN_OR_SOURCE_SHA_MISMATCH');
  const countKeys=['selected_stock_count','conditional_watch_count','not_selected_stock_count','not_assessed_stock_count'];
  const counts=countKeys.map(key=>selection[key]);
  const stocks=list(selection.stocks),statuses=['SELECTED','CONDITIONAL_WATCH','NOT_SELECTED','NOT_ASSESSED'];
  if(counts.some(count=>typeof count!=='number'||!Number.isSafeInteger(count)||count<0)||
      selection.stock_count!==stocks.length||counts.reduce((sum:number,count)=>sum+(count as number),0)!==stocks.length||
      stocks.some(row=>!statuses.includes(text(row.status,''))||typeof row.stock_code!=='string')||
      countKeys.some((key,index)=>counts[index]!==chain[key]||counts[index]!==stocks.filter(row=>row.status===statuses[index]).length))
    return fail('ANNOUNCEMENT_SELECTION_STOCK_COUNTS_INVALID');
  return {verified:true,reason:'VERIFIED_REGISTERED_OWNER',
    retrospective:chain.status==='NOT_CONSUMED_AFTER_CUTOFF'||chain.consumed!==true};
}

function recordView(row:AnnouncementAnalysisObject,decision?:AnnouncementAnalysisObject,sourceCodeBasis=false):HTMLDetailsElement{
  const article=element('details');article.dataset.announcementAnalysisCode=text(row.art_code,'UNKNOWN');
  const kind=text(row.analysis_kind);
  const kindLabel=kind==='COMPLETE_API_BODY'?'完整内容接口正文':
    kind==='LONG_PDF_KEY_SECTION_READ'?'长 PDF 重点章节回看':
    kind==='TEXT_INSUFFICIENT_UNASSESSED'?'文本不足，未判定':'状态未识别';
  article.append(element('summary',`${text(row.title,'未提供标题')} ｜ ${text(row.art_code)} ｜ ${kindLabel}`));
  article.append(element('p',`研究分类：${text(row.classification)}；证券范围：${text(row.security_scope)}；${sourceCodeBasis?'关联来源股票代码':'关联发行人'}：${issuerNames(row.issuer_codes)}。`));
  if(decision){
    article.append(element('p',`公告研究判定：${dispositionLabel(decision.disposition)}。${text(decision.reason,'未提供逐篇研究理由')}`));
    for(const risk of strings(decision.risk_notes))article.append(element('p',`风险/限制：${risk}`));
  }
  article.append(element('p',`事实摘要：${text(row.factual_summary,'未提供已复核摘要')}。`));
  if(typeof row.why_useful==='string')article.append(element('p',`研究用途：${row.why_useful}`));
  article.append(element('p',`时点边界：首次发布时间/截止 ${text(object(row.date_semantics).first_publication_timestamp,'CANNOT_CONFIRM')}；目标日可用性 ${text(object(row.date_semantics).available_at_for_target_cutoff,'CANNOT_CONFIRM')}；历史 PIT ${text(object(row.cutoff_boundary).status,'CANNOT_CONFIRM')}。这些是事后研究解释。`));
  const listing=object(row.listing_source),listingRef=object(listing.source_ref);
  article.append(element('p',`目录日期：${text(listing.notice_date)}；显示时间：${text(listing.display_time)}；目录页 ${text(listing.page_index,'未知')} / 项 ${text(listing.item_index,'未知')}；原目录正文 SHA：${text(listing.raw_body_sha256)}。`));
  const listingLink=sourceLink(listingRef.url,'打开逐篇目录来源');if(listingLink)article.append(listingLink);
  const quote=typeof row.exact_quote==='string'?row.exact_quote:'';
  if(quote&&!quote.startsWith('CANNOT_CONFIRM'))article.append(element('blockquote',`原文引句：${quote}`));
  else article.append(element('p','原文短引句未核定；保留逐页来源引用与摘要，不补造引文。'));
  if(row.quote_location&&typeof row.quote_location==='object')article.append(element('p',`引文位置：${JSON.stringify(row.quote_location)}。`));
  const bodyPages=list(row.body_page_citations);
  if(bodyPages.length){
    const pages=element('div');pages.append(element('strong',`内容接口页引用（${bodyPages.length}）`));
    for(const page of bodyPages){
      const source=object(page.source_ref),link=sourceLink(source.url,`正文页 ${text(page.page_index,'?')} · SHA ${text(page.text_sha256)}`);
      if(link)pages.append(link,element('span',' '));
    }
    article.append(pages);
  }
  const pdf=object(row.pdf_focus),pdfPages=Array.isArray(pdf.physical_pages_reviewed)?pdf.physical_pages_reviewed:[];
  if(kind==='LONG_PDF_KEY_SECTION_READ'){
    article.append(element('p',`重点阅读的 PDF 物理页：${pdfPages.join('、')||'未提供'}；引文页：${text(pdf.quote_page,'未提供')}；PDF SHA：${text(pdf.sha256)}。这是重点页回看，不代表全文解读。`));
    const pdfLink=sourceLink(pdf.source_url,'打开公告 PDF 原件');if(pdfLink)article.append(pdfLink);
  }else if(kind==='TEXT_INSUFFICIENT_UNASSESSED'){
    article.append(element('p','可读文本不足，维持未判定；不按标题推断公告事项。'));
  }
  const evidence=object(row.evidence);
  if(Object.keys(evidence).length)article.append(details('引文、正文页与原始证据 SHA',evidence));
  return article;
}

function relatedArticleView(article:AnnouncementAnalysisObject,sourceRecords:Map<string,AnnouncementAnalysisObject>):HTMLDetailsElement{
  const node=element('details');node.dataset.announcementSelectionArticle=text(article.art_code,'UNKNOWN');
  node.append(element('summary',`${dispositionLabel(article.disposition)}｜${text(article.title,'未提供标题')}｜${text(article.art_code)}`));
  node.append(element('p',`逐篇研究理由：${text(article.reason,'未提供')}。`));
  node.append(element('p',`来源事实：${text(article.factual_summary,'未提供已复核摘要')}。`));
  node.append(element('p',`证券范围：${text(article.security_scope,'未提供')}；正文类型：${text(article.analysis_kind)}；原始分类：${text(article.classification)}。`));
  for(const risk of strings(article.risk_notes))node.append(element('p',`风险/限制：${risk}`));
  const source=sourceRecords.get(text(article.art_code,''));
  const listing=object(source?.listing_source),listingRef=object(listing.source_ref);
  const listingLink=sourceLink(listingRef.url,'打开相关公告目录来源');if(listingLink)node.append(listingLink);
  for(const page of list(source?.body_page_citations)){
    const ref=object(page.source_ref);const link=sourceLink(ref.url,`打开正文页 ${text(page.page_index,'?')}`);
    if(link)node.append(element('span',' '),link);
  }
  const pdf=object(source?.pdf_focus);const pdfLink=sourceLink(pdf.source_url,'打开公告 PDF 原件');
  if(pdfLink)node.append(element('span',' '),pdfLink);
  return node;
}

function stockView(stock:AnnouncementAnalysisObject,sourceRecords:Map<string,AnnouncementAnalysisObject>,sourceCodeBasis=false):HTMLElement{
  const status=text(stock.status,'NOT_ASSESSED');
  const heading=element('h4',`${text(stock.stock_code)} ${text(stock.stock_name)}｜${status==='SELECTED'?'入选研究名单':
    status==='CONDITIONAL_WATCH'?'条件观察':status==='NOT_ASSESSED'?'未评估':'本次未入选'}`);
  const card=element('article');card.dataset.announcementSelectionStock=text(stock.stock_code,'UNKNOWN');
  card.append(heading);
  if(status==='SELECTED'||status==='CONDITIONAL_WATCH'){
    const reasons=list(stock.selection_reasons);
    for(const reason of reasons){
      const basis=object(reason);card.append(element('p',`${dispositionLabel(basis.disposition)}：${text(basis.reason,'未提供')}。`));
    }
  }
  if(status==='NOT_SELECTED')for(const excluded of list(stock.not_selected_reasons))
    card.append(element('p','未入选理由（'+text(excluded.art_code)+'）：'+text(excluded.reason,'未提供')+'。'));
  if(status==='NOT_ASSESSED')for(const article of list(stock.articles).filter(row=>row.disposition==='NOT_ASSESSED'))
    card.append(element('p','未评估原因（'+text(article.art_code)+'）：'+text(article.reason,'未提供')+'。'));
  for(const risk of strings(stock.risk_notes))card.append(element('p',`风险/限制：${risk}`));
  const related=list(stock.articles);
  const detailsNode=element('details');
  detailsNode.append(element('summary',`相关公告（${related.length}）与逐篇事实依据`));
  for(const article of related)detailsNode.append(relatedArticleView(article,sourceRecords));
  card.append(detailsNode);
  return card;
}

function renderStockSelection(host:HTMLElement,analysis:AnnouncementAnalysisObject|undefined,
                              sourceRecords:Map<string,AnnouncementAnalysisObject>,sourceCodeBasis=false,
                              admission?:{verified:boolean;reason:string;retrospective:boolean},
                              root?:AnnouncementAnalysisObject,researchResultVerified=false):void{
  const section=element('section');section.dataset.announcementStockSelection='true';
  section.append(element('h3','公告选股结果（事后研究）'));
  if(!analysis||analysis.status!=='VERIFIED'||admission?.verified!==true||researchResultVerified!==true){
    const reason=admission?.verified!==true
      ? admission?.reason ?? 'ANNOUNCEMENT_OWNER_CHAIN_NOT_VERIFIED'
      : 'ANNOUNCEMENT_RESEARCH_RESULT_NOT_VERIFIED';
    section.append(element('p','股票研究判定：CANNOT_CONFIRM（'+reason+'）。必须核实原 owner 回执、注册交接、日期、股票行与来源 SHA；不能解释成零只入选，也不沿用其他日期结果。'));
    host.append(section);return;
  }
  const chain=object(root?.consumption_validation),receipt=object(root?.owner_import_receipt);
  const research=object(root?.research_result);
  section.append(element('p','独立原 owner 已核：证据 run '+text(chain.evidence_run_id)+'；产品 SHA '+text(chain.product_sha256)+
    '；导入回执 SHA '+text(receipt.sha256)+'；导入时间 '+text(receipt.available_at)+'。股票回读 '+text(research.status)+
    '；历史 PIT='+String(research.historical_pit_verified)+'，自然运行='+String(research.natural_run_verified)+
    '。'+(admission.retrospective?'仅作事后研究显示，未证明计划日截止时可用，不计入历史 PIT 候选。':'仍须另证首次公开时间、新颖性及历史 PIT。')));
  const raw=object(analysis.stock_selection),status=text(raw.status,'NOT_ASSESSED');
  if(status!=='VERIFIED'){
    section.append(element('p','股票研究判定：NOT_ASSESSED。原公告解析已有读回，但逐篇选股研究判定尚未导入；不把缺失判定显示为候选或零只入选。'));
    host.append(section);return;
  }
  const selected=list(raw.stocks).filter(stock=>stock.status==='SELECTED');
  const watches=list(raw.stocks).filter(stock=>stock.status==='CONDITIONAL_WATCH');
  const notAssessed=list(raw.stocks).filter(stock=>stock.status==='NOT_ASSESSED');
  const excluded=list(raw.stocks).filter(stock=>stock.status==='NOT_SELECTED');
  section.append(element('p',`${sourceCodeBasis?'按目录来源股票代码去重':'按发行人代码去重'}：${text(raw.stock_count)} ${sourceCodeBasis?'个来源代码':'只'}；入选研究 ${text(raw.selected_stock_count)}；条件观察 ${text(raw.conditional_watch_count)}；本次未入选 ${text(raw.not_selected_stock_count)}；未评估 ${text(raw.not_assessed_stock_count)}。未评估与未入选分开。`));
  section.append(element('p',`依据同一日期分析产品的逐篇研究判定。来源绑定：catalog run ${text(object(raw.source_binding).catalog_run_id)}；基础分析 SHA ${text(raw.base_product_sha256)}；选股判定 SHA ${text(raw.selection_sha256)}。这是一组事后研究样本，不是目标日可得信息、历史 PIT、收益排名或 BUY 信号。`));
  const selectedList=element('div');selectedList.setAttribute('aria-label','入选公告研究股票');
  if(selected.length)for(const stock of selected)selectedList.append(stockView(stock,sourceRecords,sourceCodeBasis));
  else selectedList.append(element('p','当前没有已核验的入选研究股票。'));
  section.append(selectedList);
  const watchDetails=element('details');watchDetails.append(element('summary',`条件观察（${watches.length}）`));
  for(const stock of watches)watchDetails.append(stockView(stock,sourceRecords,sourceCodeBasis));
  section.append(watchDetails);
  const auditDetails=element('details');
  auditDetails.append(element('summary',`逐只查看未入选（${excluded.length}）与未评估（${notAssessed.length}）理由`));
  const excludedGroup=element('section');excludedGroup.append(element('h4','本次未入选'));
  for(const stock of excluded)excludedGroup.append(stockView(stock,sourceRecords,sourceCodeBasis));
  const unknownGroup=element('section');unknownGroup.append(element('h4','未评估'));
  for(const stock of notAssessed)unknownGroup.append(stockView(stock,sourceRecords,sourceCodeBasis));
  auditDetails.append(excludedGroup,unknownGroup);section.append(auditDetails);
  host.append(section);
}

export function renderAnnouncementAnalysis(
  host:HTMLElement,
  value:ManagerAnnouncementAnalysis|undefined,
  selectedPublicationDate:string|undefined,
  failure:string|undefined,
  onDateChange:(publicationDate:string|undefined)=>void,
):void{
  host.replaceChildren(element('h3','历史公告解析成果（Eastmoney HK 日期目录）'));
  host.setAttribute('aria-label','历史公告解析成果');
  const label=element('label','公告日期：'),input=element('input');input.type='date';input.setAttribute('aria-label','公告日期');
  const displayDate=selectedPublicationDate||(value?dateToken(value.publication_date):'');
  input.value=displayDate?`${displayDate.slice(0,4)}-${displayDate.slice(4,6)}-${displayDate.slice(6,8)}`:'';
  input.addEventListener('change',()=>onDateChange(input.value?dateToken(input.value)||undefined:undefined));
  label.append(input,element('small','留空时按计划日前一 HK 交易日读取；日期选择独立于计划日。'));
  host.append(label);
  if(!value){
    const status=element('p',failure?`公告解析结果未能读回；覆盖数量未知（${failure}）。`:'正在读取公告解析结果；覆盖数量未知。');
    status.setAttribute('role','status');host.append(status);
    renderStockSelection(host,undefined,new Map());return;
  }
  const catalog=value.source_catalog,analysis=value.analysis;
  const statusName=analysis.status==='VERIFIED'?'已读回复核后的离线派生解读':
    analysis.status==='NOT_IMPORTED'?'尚未导入该日期的解析结果':
    '目录或派生结果未通过读回校验';
  const status=element('p',`${value.publication_date}（${value.date_selection_basis==='PREVIOUS_HK_TRADING_SESSION'?'计划日前一 HK 交易日':'手动选择'}）｜${statusName}`);
  status.setAttribute('role','status');host.append(status);
  if(catalog.status==='COMPLETE'&&catalog.readback_status==='VERIFIED'){
    const sourceCodeBasis=catalog.issuer_count_status==='CANNOT_CONFIRM'&&
      typeof catalog.distinct_manager_source_code_count==='number';
    const identitySummary=sourceCodeBasis
      ?`经理样本 ${text(catalog.manager_announcement_count)} 篇 / ${text(catalog.distinct_manager_source_code_count)} 个不同来源股票代码；${text(catalog.manager_source_identity_association_count)} 个来源代码关联；发行人数量 CANNOT_CONFIRM。`
      :`经理样本 ${text(catalog.manager_announcement_count)} 篇 / ${text(catalog.manager_issuer_count)} 个发行人。`;
    host.append(element('p',`目录 ${text(catalog.source_scope)}：${text(catalog.directory_record_count)} 条 / ${text(catalog.directory_page_count)} 页；${identitySummary}目录 run ${text(catalog.catalog_run_id)}；目录 SHA ${text(catalog.catalog_product_sha256)}。`));
  }else{
    host.append(element('p',`所选公告日期的目录尚无可核验读回（${text(catalog.status)} / ${text(catalog.readback_status)}）；数量未知，不显示为 0 条。`));
  }
  const admission=verifiedAnnouncementOwnerSelection(value);
  const researchResult=object((value as unknown as AnnouncementAnalysisObject).research_result);
  const researchResultVerified=verifiedAnnouncementResearchResult(researchResult,{
    plan_date:value.target_trade_date,selection_date:value.target_trade_date,
    announcement_date:value.publication_date,
  });
  const sourceRecords=new Map(list(analysis.records).map(record=>[text(record.art_code,''),record]));
  const selectionProjection=object(analysis.stock_selection);
  const decisionsByArticle=new Map((admission.verified&&researchResultVerified?list(selectionProjection.article_decisions):[])
    .map(decision=>[text(decision.art_code,''),decision]));
  const sourceCodeBasis=object(analysis.source_manifest).issuer_count_status==='CANNOT_CONFIRM';
  renderStockSelection(host,analysis,sourceRecords,sourceCodeBasis,admission,object(value),researchResultVerified);
  if(analysis.status==='VERIFIED'){
    const summary=object(analysis.summary);
    host.append(element('p',`${text(summary.complete_api_bodies)} 篇完整内容接口正文；${text(summary.long_pdf_focus_reads)} 篇长 PDF 重点章节回看；${text(summary.text_insufficient_unassessed)} 篇文本不足、未判定。`),
      element('p','来源为 Eastmoney 港股日期目录；不是 HKEX 官方目录全量认定。首次发布时间与截止、新颖性、历史 PIT 均为 CANNOT_CONFIRM。离线解读只作事后研究参考。'));
    if(typeof analysis.interpretation_boundary==='string')host.append(element('p',analysis.interpretation_boundary));
    const records=list(analysis.records),items=element('details');items.dataset.announcementAnalysisRecords='true';
    items.append(element('summary',`查看全部 ${records.length} 篇逐条内容与出处`));
    for(const record of records)items.append(recordView(record,decisionsByArticle.get(text(record.art_code,'')),sourceCodeBasis));
    host.append(items,details('目录/语料/解析产品来源 SHA 与导入清单',{
      source_manifest:analysis.source_manifest,source_manifest_sha256:analysis.source_manifest_sha256,
      product_sha256:analysis.product_sha256,gaps:analysis.gaps,
    }));
  }else{
    const gaps=Array.isArray(analysis.gaps)?analysis.gaps.join('；'):'解析缺口未提供';
    host.append(element('p',`所选日期没有已校验的完整解析产物；不能解释为零公告或零解析。缺口：${gaps}。`));
  }
}
