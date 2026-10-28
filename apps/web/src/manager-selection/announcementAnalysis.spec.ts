import { describe, expect, it, vi } from 'vitest';
import type { ManagerAnnouncementAnalysis } from '../api/managerAnnouncementAnalysis.js';
import { renderAnnouncementAnalysis, renderAnnouncementPreopenWindow } from './announcementAnalysis.js';

const row=(index:number,kind:string)=>({art_code:`AN20260929${String(index).padStart(6,'0')}`,
  title:`Reviewed notice ${index}`,analysis_kind:kind,classification:'BUSINESS_EVENT',
  factual_summary:`Reviewed summary ${index}`,security_scope:'Issuer shares',issuer_codes:[{code:'HK.00001',name:'Issuer'}],
  date_semantics:{first_publication_timestamp:'CANNOT_CONFIRM',available_at_for_target_cutoff:'CANNOT_CONFIRM'},
  cutoff_boundary:'CANNOT_CONFIRM',listing_source:{notice_date:'2026-09-29',display_time:'2026-09-29 09:00:00',
    page_index:1,item_index:index,raw_body_sha256:'a'.repeat(64),source_ref:{url:'https://np-anotice-stock.eastmoney.com/api/security/ann?page_index=1'}},
  exact_quote:'Sample verified quote',body_page_citations:[{page_index:1,text_sha256:'b'.repeat(64),
    source_ref:{url:'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=sample&page_index=1'}}],
  pdf_focus:{source_url:'https://pdf.dfcfw.com/pdf/sample.pdf',sha256:'c'.repeat(64),
    physical_pages_reviewed:kind==='LONG_PDF_KEY_SECTION_READ'?[2,4]:[],quote_page:2,derivative:{derivative_sha256:'d'.repeat(64)}},
  evidence:{exact_excerpt:'Sample source-linked excerpt'}});
function verified():ManagerAnnouncementAnalysis{
  const kinds=['COMPLETE_API_BODY','LONG_PDF_KEY_SECTION_READ','TEXT_INSUFFICIENT_UNASSESSED'];
  const records=Array.from({length:234},(_,i)=>row(i,i<207?kinds[0]:i<229?kinds[1]:kinds[2]));
  return {schema_version:'v4.manager_research.eastmoney_hk_announcement_analysis_read.v1',
    target_trade_date:'20260930',publication_date:'2026-09-29',date_selection_basis:'PREVIOUS_HK_TRADING_SESSION',
    source_catalog:{status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
      directory_record_count:744,directory_page_count:39,manager_announcement_count:234,
      manager_issuer_count:140,catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)},
    analysis:{status:'VERIFIED',summary:{complete_api_bodies:207,long_pdf_focus_reads:22,
      text_insufficient_unassessed:5},records,first_publication_and_cutoff_status:'CANNOT_CONFIRM',
      novelty_vs_prior_status:'CANNOT_CONFIRM',point_in_time_status:'CANNOT_CONFIRM',
      interpretation_boundary:'Retrospective research only; no PIT or BUY use.',source_manifest:{},
      source_manifest_sha256:'c'.repeat(64),product_sha256:'d'.repeat(64),gaps:[]}} as unknown as ManagerAnnouncementAnalysis;
}

function attachVerifiedOwnerReadback(value:ManagerAnnouncementAnalysis,selection:Record<string,unknown>):void{
  const root=value as unknown as Record<string,unknown>;
  const analysis=value.analysis as Record<string,unknown>;
  const stocks=Array.isArray(selection.stocks)?selection.stocks as Record<string,unknown>[]:[];
  const productSha=String(analysis.product_sha256),manifestSha=String(analysis.source_manifest_sha256);
  const selectionSha='4'.repeat(64),receiptSha='5'.repeat(64),handoffSha='6'.repeat(64);
  const judgmentSha='7'.repeat(64),evidenceRun='8'.repeat(32);
  const target=value.target_trade_date,publication=value.publication_date;
  const selected=Number(selection.selected_stock_count)||0,watch=Number(selection.conditional_watch_count)||0;
  const excluded=Number(selection.not_selected_stock_count)||0,unassessed=Number(selection.not_assessed_stock_count)||0;
  const existingBinding=selection.source_binding&&typeof selection.source_binding==='object'&&
    !Array.isArray(selection.source_binding)?selection.source_binding as Record<string,unknown>:{};
  selection.product_sha256=productSha;selection.source_manifest_sha256=manifestSha;selection.selection_sha256=selectionSha;
  selection.source_binding={...existingBinding,target_trade_date:target,publication_date:publication};
  analysis.stock_selection=selection;
  const chain={validation_status:'VERIFIED',status:'NOT_CONSUMED_AFTER_CUTOFF',consumed:false,
    target_trade_date:target,publication_date:publication,evidence_run_id:evidenceRun,
    product_sha256:productSha,source_manifest_sha256:manifestSha,owner_import_receipt_sha256:receiptSha,
    handoff_manifest_sha256:handoffSha,agent_judgment_receipt_sha256:judgmentSha,
    selected_stock_count:selected,conditional_watch_count:watch,not_selected_stock_count:excluded,
    not_assessed_stock_count:unassessed};
  root.consumption_validation=chain;
  root.owner_import_receipt={status:'VERIFIED',owner:'ManagerResearchJobService.import_announcement_analysis',
    sha256:receiptSha,product_sha256:productSha,source_manifest_sha256:manifestSha,evidence_run_id:evidenceRun,
    target_trade_date:target,publication_date:publication,handoff_manifest_sha256:handoffSha,
    agent_judgment_receipt_sha256:judgmentSha,available_at:'2026-10-12T12:00:00Z'};
  root.research_result={schema_version:'v4.manager_research.announcement_research_result.v1',
    target_trade_date:target,publication_date:publication,owner:'ManagerResearchJobService.import_announcement_analysis',
    validation_status:'VERIFIED',historical_pit_verified:false,natural_run_verified:false,RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,status:'RETROSPECTIVE_RESEARCH_ONLY',
    consumed_at_cutoff:false,cutoff_status:'NOT_REQUESTED',plan_cutoff:null,product_sha256:productSha,
    selection_sha256:selectionSha,source_manifest_sha256:manifestSha,
    catalog_product_sha256:String(value.source_catalog.catalog_product_sha256),owner_import_receipt_sha256:receiptSha,
    handoff_manifest_sha256:handoffSha,evidence_run_id:evidenceRun,catalog_run_id:String(value.source_catalog.catalog_run_id),
    owner_available_at:'2026-10-12T12:00:00Z',latest_source_or_review_at:'2026-10-12T12:00:00Z',
    stock_count:stocks.length,selected_stock_count:selected,conditional_watch_count:watch,
    not_selected_stock_count:excluded,not_assessed_stock_count:unassessed,
    stocks:stocks.map(stock=>({stock_code:stock.stock_code,status:stock.status,target_trade_date:target,
      publication_date:publication,evidence_run_id:evidenceRun,product_sha256:productSha,
      selection_sha256:selectionSha,owner_import_receipt_sha256:receiptSha}))};
}

describe('renderAnnouncementAnalysis',()=>{
  it('foregrounds reviewed retrospective positives while keeping watch, risk and actual eligibility separate',()=>{
    const host=document.createElement('section'),value=verified();
    const candidate=(id:string,disposition:string,direction:string)=>({
      publication_date:'2026-10-09',source_identity:{kind:'art_code',id},source:'EASTMONEY',title:`Notice ${id}`,
      issuer_codes:[{code:'HK.00001',name:'Issuer'}],classification:'BUSINESS_EVENT',
      factual_summary:'A reviewed source-linked fact.',why_useful:'A bounded research reason.',event_status_assessment:null,
      analysis_kind:'COMPLETE_API_BODY',body_status:null,semantic_record_sha256:'a'.repeat(64),
      source_record_sha256:'b'.repeat(64),body_text_sha256:'c'.repeat(64),publication_time:null,
      publication_time_basis:'CANNOT_CONFIRM',disposition,selection_basis:'EXPLICIT_REVIEW',direction,
      evidence_sufficiency:disposition==='NOT_ASSESSED'?'INSUFFICIENT_EXISTING_FACTS':'VERIFIED_EXISTING_FACTS',
      reason:`Reviewed reason for ${id}.`,risk_notes:['A material limitation remains.'],supporting_exact_quote:null,
      source_refs:[{url:'https://np-anotice-stock.eastmoney.com/api/ann?id=AN20261009000001',blob_sha256:null,body_sha256:'d'.repeat(64)}],
      retrospective_status:'SOURCE_PUBLISHED_IN_WINDOW',source_record_validation:'PASS',
    });
    const candidates=[candidate('AN20261009000001','SELECTED_EVENT','POSITIVE'),
      candidate('AN20261009000002','CONDITIONAL_WATCH','MIXED'),
      candidate('AN20261009000003','NOT_SELECTED','NEGATIVE'),
      candidate('AN20261009000004','NOT_ASSESSED','UNKNOWN')];
    value.preopen_window_readback={status:'VERIFIED',window_start:'2026-10-09T00:00:00+08:00',
      as_of:'2026-10-12T09:20:00+08:00',registered_fingerprint_sha256:'e'.repeat(64),input_fingerprint_sha256:'f'.repeat(64),
      coverage:{status:'PARTIAL',expected_dates:['20261009','20261010','20261011','20261012'],
        covered_dates:['20261009','20261012'],missing_dates:['20261010','20261011'],missing_date_count:2},
      retrospective_research:{status:'PARTIAL',candidate_count:4,positive_candidate_count:1,candidates,
        pending_count:1,pending_queue:[{publication_date:'2026-10-12',
          source_identity:{kind:'source_variant_id',id:'HKEX:12345678'},reason_codes:['SOURCE_CONTENT_NOT_ASSESSED']}]},
      actual_preopen:{status:'CANNOT_CONFIRM',positive_candidate_count:null,positive_candidates:[],
        candidate_evaluations:[],gaps:['QUALIFICATION_AT_CUTOFF_CANNOT_CONFIRM']}} as never;

    renderAnnouncementPreopenWindow(host,value,undefined);
    expect(host.textContent).toContain('正向事件与业绩研究（1）');
    expect(host.querySelectorAll('[data-preopen-candidate="positive"]')).toHaveLength(1);
    expect(host.querySelector('[data-preopen-watch]')?.textContent).toContain('条件观察 WATCH（1）');
    expect(host.querySelector('[data-preopen-risk]')?.textContent).toContain('负向事实与风险 RISK（1）');
    expect(host.querySelector('[data-preopen-other]')?.textContent).toContain('未入选、未评估或方向未定（1）');
    expect((host.querySelector('[data-preopen-watch]') as HTMLDetailsElement)?.open).toBe(false);
    expect((host.querySelector('[data-preopen-other]') as HTMLDetailsElement)?.open).toBe(false);
    expect(host.textContent).toContain('缺失 2 日（20261010、20261011）');
    expect(host.textContent).toContain('实际盘前资格 CANNOT_CONFIRM');
    expect(host.textContent).toContain('事后正向研究候选 1 条');
    expect(host.textContent).not.toContain('/Users/');
    expect(host.querySelector<HTMLAnchorElement>('a[href^="https://np-anotice-stock.eastmoney.com/"]')?.rel)
      .toContain('noopener');
  });

  it('shows frozen totals, PIT gaps, date selection and all item citations',()=>{
    const host=document.createElement('section'),onDate=vi.fn();
    renderAnnouncementAnalysis(host,verified(),undefined,undefined,onDate);
    expect(host.textContent).toContain('744 条 / 39 页');
    expect(host.textContent).toContain('207 篇完整内容接口正文');
    expect(host.textContent).toContain('22 篇长 PDF 重点章节回看');
    expect(host.textContent).toContain('5 篇文本不足、未判定');
    expect(host.textContent).toContain('首次发布时间与截止、新颖性、历史 PIT 均为 CANNOT_CONFIRM');
    expect(host.textContent).toContain('Eastmoney 港股日期目录');
    const input=host.querySelector<HTMLInputElement>('input[type="date"]');
    expect(input?.value).toBe('2026-09-29');
    input!.value='2026-09-30';input!.dispatchEvent(new Event('change'));
    expect(onDate).toHaveBeenCalledWith('20260930');
    const list=host.querySelector<HTMLDetailsElement>('details[data-announcement-analysis-records="true"]');
    expect(list?.querySelectorAll('details[data-announcement-analysis-code]')).toHaveLength(234);
    const first=list?.querySelector('details[data-announcement-analysis-code]');
    expect(first?.textContent).toContain('事实摘要：Reviewed summary 0');
    expect(first?.textContent).toContain('关联发行人：HK.00001 Issuer');
    expect(first?.textContent).not.toContain('[object Object]');
    expect(first?.querySelector('a[href^="https://np-anotice-stock.eastmoney.com/"]')?.textContent)
      .toContain('打开逐篇目录来源');
    expect(first?.querySelector('a[href^="https://np-cnotice-stock.eastmoney.com/"]')?.textContent)
      .toContain('正文页 1');
  });

  it('keeps a missing analysis visibly unknown instead of rendering zero results',()=>{
    const host=document.createElement('section');
    const value=verified();value.analysis={status:'NOT_IMPORTED',summary:null,records:[],gaps:['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED']} as never;
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).toContain('尚未导入该日期的解析结果');
    expect(host.textContent).toContain('不能解释为零公告或零解析');
    expect(host.textContent).not.toContain('0 篇完整内容接口正文');
  });

  it('redacts local registered-window input paths from the daily audit detail',()=>{
    const host=document.createElement('section'),value=verified();
    value.analysis.source_manifest={preopen_window:{input_refs:[{path:'/Users/private/semantic.json'},
      {local_path:'/Users/private/body.json',sha256:'a'.repeat(64)}],registered_binding:{uri:'file:///Users/private/draft.json'},
      registered_fingerprint_sha256:'b'.repeat(64)}};
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).not.toContain('/Users/private');
    expect(host.textContent).not.toContain('file:///');
    expect(host.textContent).toContain('registered_fingerprint_sha256');
  });

  it('shows stock-deduped research selections and explicit exclusion reasons',()=>{
    const host=document.createElement('section'),value=verified();
    const selectedArticle={art_code:'AN20260929000000',title:'Reviewed event',
      analysis_kind:'COMPLETE_API_BODY',classification:'BUSINESS_EVENT',security_scope:'Issuer shares',
      disposition:'SELECTED_EVENT',reason:'列入事件研究：披露了具体产品进展。',
      factual_summary:'产品取得监管节点。',risk_notes:['仍处早期阶段。'],source_sha256:'a'.repeat(64)};
    const excludedArticle={art_code:'AN20260929000001',title:'Routine notice',
      analysis_kind:'COMPLETE_API_BODY',classification:'ROUTINE',security_scope:'Issuer shares',
      disposition:'NOT_SELECTED',reason:'仅为程序通知，没有经营进展。',
      factual_summary:'更新了联系人。',risk_notes:[],source_sha256:'b'.repeat(64)};
    value.analysis.stock_selection={status:'VERIFIED',decision_unit:'ISSUER_CODE',stock_count:2,article_count:234,
      selected_stock_count:1,conditional_watch_count:0,not_selected_stock_count:1,not_assessed_stock_count:0,
      base_product_sha256:'c'.repeat(64),selection_sha256:'d'.repeat(64),
      source_binding:{catalog_run_id:'run-1'},article_decisions:[
        {art_code:selectedArticle.art_code,disposition:'SELECTED_EVENT',reason:selectedArticle.reason},
        {art_code:excludedArticle.art_code,disposition:'NOT_SELECTED',reason:excludedArticle.reason}],
      stocks:[
        {stock_code:'HK.00001',stock_name:'Selected issuer',status:'SELECTED',article_count:1,
          selection_reasons:[{art_code:selectedArticle.art_code,disposition:'SELECTED_EVENT',reason:selectedArticle.reason}],
          risk_notes:['仍处早期阶段。'],not_selected_reasons:[],articles:[selectedArticle]},
        {stock_code:'HK.00002',stock_name:'Excluded issuer',status:'NOT_SELECTED',article_count:1,
          selection_reasons:[],risk_notes:[],not_selected_reasons:[{art_code:excludedArticle.art_code,
            reason:excludedArticle.reason}],articles:[excludedArticle]},
      ],gaps:[]};
    attachVerifiedOwnerReadback(value,value.analysis.stock_selection as unknown as Record<string,unknown>);
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).toContain('公告选股结果（事后研究）');
    expect(host.textContent).toContain('按发行人代码去重：2 只');
    expect(host.textContent).toContain('HK.00001 Selected issuer｜入选研究名单');
    expect(host.textContent).toContain('列入事件研究：披露了具体产品进展。');
    expect(host.textContent).toContain('风险/限制：仍处早期阶段。');
    expect(host.textContent).toContain('本次未入选');
    expect(host.textContent).toContain('仅为程序通知，没有经营进展。');
    expect(host.querySelectorAll('[data-announcement-selection-stock]')).toHaveLength(2);
  });

  it('does not turn a verified analysis without selection judgments into zero stocks',()=>{
    const host=document.createElement('section'),value=verified();
    value.analysis.stock_selection={status:'NOT_ASSESSED',stock_count:null};
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).toContain('股票研究判定：CANNOT_CONFIRM');
    expect(host.textContent).toContain('公告分析产品中的股票研究判定：NOT_ASSESSED');
    expect(host.textContent).toContain('原 owner 导入读回尚未核实');
  });

  it('labels dynamic source-code counts without claiming a verified issuer count',()=>{
    const host=document.createElement('section'),value=verified();
    const sourceRows=[
      {...row(1000,'COMPLETE_API_BODY'),art_code:'AN202610060001',issuer_codes:[
        {code:'HK.00001',name:'Fixture One',market_code:'116',ann_type:'H'},
        {code:'HK.00002',name:'Fixture Two',market_code:'116',ann_type:'H'}]},
      {...row(1001,'COMPLETE_API_BODY'),art_code:'AN202610060002',issuer_codes:[
        {code:'HK.00001',name:'Fixture One',market_code:'116',ann_type:'H'}]},
    ];
    value.target_trade_date='20261007';value.publication_date='2026-10-06';value.date_selection_basis='EXPLICIT';
    value.source_catalog={status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
      publication_date:'2026-10-06',is_hkex_complete_directory:false,directory_record_count:3,
      directory_page_count:2,manager_announcement_count:2,manager_source_identity_association_count:3,
      distinct_manager_source_code_count:2,manager_issuer_count:null,unknown_issuer_count:null,
      issuer_count_status:'CANNOT_CONFIRM',catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)};
    value.analysis={...value.analysis,target_trade_date:'20261007',publication_date:'2026-10-06',
      summary:{complete_api_bodies:2,long_pdf_focus_reads:0,text_insufficient_unassessed:0},records:sourceRows,
      source_manifest:{issuer_count_status:'CANNOT_CONFIRM'},stock_selection:{status:'NOT_ASSESSED'}} as never;
    renderAnnouncementAnalysis(host,value,'20261006',undefined,()=>{});
    expect(host.textContent).toContain('2 个不同来源股票代码');
    expect(host.textContent).toContain('3 个来源代码关联');
    expect(host.textContent).toContain('发行人数量 CANNOT_CONFIRM');
    expect(host.textContent).toContain('关联来源股票代码：HK.00001 Fixture One、HK.00002 Fixture Two');
    expect(host.textContent).not.toContain('2 个发行人');
    expect(host.textContent).not.toContain('关联发行人：HK.00001');
  });

  it('renders source-bound HKEX variants, full-day coverage and calendar-day basis separately',()=>{
    const host=document.createElement('section'),value=verified();
    const publication='2026-10-11',target='20261012',sourceVariantId='HKEX:12345678';
    const eastmoney=[
      {...row(1001,'COMPLETE_API_BODY'),art_code:'AN202610110001',title:'Eastmoney one',issuer_codes:[
        {code:'HK.00001',name:'Fixture One',market_code:'116',ann_type:'H'}],
        semantic_record_sha256:'1'.repeat(64),body_record_sha256:'2'.repeat(64)},
      {...row(1002,'COMPLETE_API_BODY'),art_code:'AN202610110002',title:'Eastmoney two',issuer_codes:[
        {code:'HK.00002',name:'Fixture Two',market_code:'116',ann_type:'H'}],
        semantic_record_sha256:'3'.repeat(64),body_record_sha256:'4'.repeat(64)},
    ];
    const official={source_variant_id:sourceVariantId,source:'HKEX_OFFICIAL',source_scope:'HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1',
      news_id:'12345678',title:'Official issuer announcement',analysis_kind:'COMPLETE_HKEX_OFFICIAL_PDF_BODY',
      body_status:'COMPLETE_HKEX_OFFICIAL_PDF_BODY',classification:'BUSINESS_EVENT',security_scope:'Issuer shares',
      factual_summary:'Officially filed fact summary.',issuer_codes:[{code:'HK.00001',name:'Fixture One'}],
      connect_eligibility_status:'ELIGIBLE',matched_connect_codes:['HK.00001'],
      connect_eligibility_identity_sha256:'a'.repeat(64),
      date_semantics:{first_publication_timestamp:'CANNOT_CONFIRM',available_at_for_target_cutoff:'CANNOT_CONFIRM'},
      cutoff_boundary:{status:'CANNOT_CONFIRM'},body_page_citations:[{page_index:1,text_sha256:'b'.repeat(64),
        source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1011/202610110001.pdf'}}],
      listing_source:{source_variant_id:sourceVariantId,source_scope:'HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1',news_id:'12345678',
        publication_date:publication,symbol:'HK.00001',directory_raw_body_sha256:'c'.repeat(64),
        directory_source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1011/index.html'},
        body_source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1011/202610110001.pdf'}},
      semantic_record_sha256:'d'.repeat(64),body_record_sha256:'e'.repeat(64)};
    value.target_trade_date=target;value.publication_date=publication;
    value.date_selection_basis='CURRENT_TARGET_PREVIOUS_CALENDAR_DAY';
    value.source_catalog={status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
      publication_date:publication,is_hkex_complete_directory:false,directory_record_count:18,directory_page_count:3,
      manager_announcement_count:2,manager_source_identity_association_count:2,distinct_manager_source_code_count:2,
      manager_issuer_count:null,unknown_issuer_count:null,issuer_count_status:'CANNOT_CONFIRM',
      catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)};
    const counts={directory_records:18,directory_pages:3,manager_announcements:3,
      manager_source_identity_associations:2,distinct_manager_source_codes:2,complete_api_bodies:2,
      long_pdf_focus_reads:0,text_insufficient_unassessed:0,eligible_eastmoney_announcements:2,
      hkex_official_announcements:1,combined_eligible_announcements:3,complete_hkex_pdf_bodies:1};
    value.analysis={status:'VERIFIED',target_trade_date:target,publication_date:publication,
      summary:{...counts,complete_hkex_pdf_bodies:1},records:[...eastmoney,official],
      source_manifest:{...counts,source_scope:'EASTMONEY_HK_DATE_CATALOG',additional_source_scopes:['HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1'],
        hkex_directory_readback_sha256:'9'.repeat(64),monthly_connect_eligibility_identity_sha256:'a'.repeat(64),
        hkex_directory_document_count:2,hkex_eligible_document_count:1,hkex_excluded_document_count:1,
        hkex_unresolved_document_count:0,hkex_body_coverage_status:'PARTIAL',monthly_connect_source_date:'20261001',
        hkex_cross_source_link_status:'NOT_ASSESSED',issuer_count_status:'CANNOT_CONFIRM'},
      first_publication_and_cutoff_status:'CANNOT_CONFIRM',novelty_vs_prior_status:'CANNOT_CONFIRM',
      point_in_time_status:'CANNOT_CONFIRM',source_manifest_sha256:'c'.repeat(64),product_sha256:'d'.repeat(64)} as never;
    const analysis=value.analysis as Record<string,unknown>;
    const records=analysis.records as Record<string,unknown>[];
    const decisions=records.map((record,index)=>({
      ...(typeof record.source_variant_id==='string'?{source_variant_id:record.source_variant_id}:{art_code:record.art_code}),
      issuer_codes:(record.issuer_codes as Record<string,unknown>[]).map(item=>item.code),
      semantic_record_sha256:record.semantic_record_sha256,body_record_sha256:record.body_record_sha256,
      disposition:index===2?'SELECTED_EVENT':'NOT_SELECTED',reason:index===2?'Reviewed official event':'Routine notice',
      risk_notes:[]}));
    const article=(index:number)=>({...decisions[index],source_sha256:records[index].semantic_record_sha256,
      title:records[index].title,factual_summary:records[index].factual_summary,
      security_scope:records[index].security_scope,analysis_kind:records[index].analysis_kind,
      classification:records[index].classification});
    const sourceBinding={target_trade_date:target,publication_date:publication,
      hkex_directory_readback_sha256:'9'.repeat(64),monthly_connect_eligibility_identity_sha256:'a'.repeat(64),
      monthly_connect_source_date:'20261001',additional_source_scopes_sha256:'b'.repeat(64)};
    const stockSelection={status:'VERIFIED',stock_count:2,article_count:3,selected_stock_count:1,
      conditional_watch_count:0,not_selected_stock_count:1,not_assessed_stock_count:0,
      source_binding:sourceBinding,article_decisions:decisions,
      stocks:[
        {stock_code:'HK.00001',stock_name:'Fixture One',status:'SELECTED',articles:[article(0),article(2)],
          selection_reasons:[{disposition:'SELECTED_EVENT',reason:'Reviewed official event'}],not_selected_reasons:[],risk_notes:[]},
        {stock_code:'HK.00002',stock_name:'Fixture Two',status:'NOT_SELECTED',articles:[article(1)],
          selection_reasons:[],not_selected_reasons:[{art_code:'AN202610110002',reason:'Routine notice'}],risk_notes:[]},
      ]};
    attachVerifiedOwnerReadback(value,stockSelection);
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).toContain('当前计划日的前一日历日');
    expect(host.textContent).toContain('HKEX 当日官方目录 2 篇');
    expect(host.textContent).toContain('Connect 月度资格筛后 1 篇，排除 1 篇，来源身份未解决 0 篇');
    expect(host.textContent).toContain('月度 Connect 快照来源日 20261001');
    expect(host.textContent).toContain('HKEX:12345678');
    const record=host.querySelector<HTMLDetailsElement>('details[data-announcement-analysis-source-variant="HKEX:12345678"]');
    expect(record?.textContent).toContain('HKEX 官方 PDF 正文已采集');
    expect(record?.textContent).toContain('HKEX 公告编号：12345678');
    expect(record?.querySelector('a[href^="https://www1.hkexnews.hk/"]')?.textContent)
      .toContain('打开 HKEX 官方当日目录');
    expect(record?.querySelector('a[href^="https://www1.hkexnews.hk/"][href$=".pdf"]')?.textContent)
      .toContain('打开 HKEX 官方 PDF 原件');
    const selected=host.querySelector<HTMLElement>('[data-announcement-selection-stock="HK.00001"]');
    expect(selected?.textContent).toContain('入选研究名单');
    expect(selected?.querySelector('[data-announcement-selection-source-variant="HKEX:12345678"]')?.textContent)
      .toContain('HKEX:12345678');

    const gapValue=structuredClone(value),gapHost=document.createElement('section');
    const gapAnalysis=gapValue.analysis as Record<string,any>;
    const gapRecord=(gapAnalysis.records as Record<string,any>[]).find(row=>row.source_variant_id==='HKEX:12345678')!;
    gapRecord.analysis_kind='TEXT_INSUFFICIENT_UNASSESSED';gapRecord.selection_status='NOT_ASSESSED';
    gapAnalysis.summary.text_insufficient_unassessed=1;gapAnalysis.summary.complete_hkex_pdf_bodies=0;
    gapAnalysis.source_manifest.hkex_body_coverage_status='PARTIAL';
    const gapSelection=gapAnalysis.stock_selection as Record<string,any>;
    gapSelection.selected_stock_count=0;gapSelection.not_selected_stock_count=1;gapSelection.not_assessed_stock_count=1;
    const gapDecision=gapSelection.article_decisions.find((row:Record<string,any>)=>row.source_variant_id==='HKEX:12345678');
    gapDecision.disposition='NOT_ASSESSED';gapDecision.reason='Body captured; semantic content remains insufficient.';
    const gapStock=gapSelection.stocks.find((row:Record<string,any>)=>row.stock_code==='HK.00001');
    gapStock.status='NOT_ASSESSED';gapStock.selection_reasons=[];
    const gapStockArticle=gapStock.articles.find((row:Record<string,any>)=>row.source_variant_id==='HKEX:12345678');
    gapStockArticle.disposition='NOT_ASSESSED';gapStockArticle.reason=gapDecision.reason;
    attachVerifiedOwnerReadback(gapValue,gapSelection);
    renderAnnouncementAnalysis(gapHost,gapValue,undefined,undefined,()=>{});
    const semanticGap=gapHost.querySelector<HTMLDetailsElement>('details[data-announcement-analysis-source-variant="HKEX:12345678"]');
    expect(semanticGap?.textContent).toContain('文本不足，未判定');
    expect(semanticGap?.textContent).toContain('HKEX PDF 采集状态：COMPLETE_HKEX_OFFICIAL_PDF_BODY');
    expect(gapHost.textContent).toContain('未评估');
  });
});
