import { describe, expect, it, vi } from 'vitest';
import type { ManagerAnnouncementAnalysis } from '../api/managerAnnouncementAnalysis.js';
import { renderAnnouncementAnalysis } from './announcementAnalysis.js';

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

describe('renderAnnouncementAnalysis',()=>{
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
    renderAnnouncementAnalysis(host,value,undefined,undefined,()=>{});
    expect(host.textContent).toContain('股票研究判定：NOT_ASSESSED');
    expect(host.textContent).toContain('不把缺失判定显示为候选或零只入选');
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
});
