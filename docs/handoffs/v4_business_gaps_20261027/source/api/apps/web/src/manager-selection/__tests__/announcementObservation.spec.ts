import { describe, expect, it } from 'vitest';
import { renderAnnouncementObservation } from '../announcementObservation';
import { validateAnnouncementObservation } from '../../api/managerWorkspace';

describe('manager Eastmoney HK announcement lane',()=>{
  it('renders the mirror notice separately with source times and full-PDF identity',()=>{
    const host=document.createElement('section');
    const listRef:any={source:'EASTMONEY_HK',source_key:'list-key',request:{method:'GET',url:'https://np-anotice-stock.eastmoney.com/api/security/ann?ann_type=H&client_source=web&stock_list=00700&page_index=1&page_size=5&sr=-1'},retrieved_at:'2026-09-29T13:09:51.005126+08:00',blob_sha256:'1'.repeat(64),body_sha256:'f3af6054cf4c5d5180dbc6755e84398d0fb3810c487ea50bc163df1265cde62b'};
    const page1Ref:any={source:'EASTMONEY_HK',source_key:'content-page-1',request:{method:'GET',url:'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=AN202609281829962076&client_source=web&page_index=1'},retrieved_at:'2026-09-29T13:10:23.984398+08:00',blob_sha256:'2'.repeat(64),body_sha256:'8557b81422e64ad909a159d38c046cb49e604839d439507d75247759b7ab9244'};
    const page2Ref:any={source:'EASTMONEY_HK',source_key:'content-page-2',request:{method:'GET',url:'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=AN202609281829962076&client_source=web&page_index=2'},retrieved_at:'2026-09-29T13:10:30.000000+08:00',blob_sha256:'3'.repeat(64),body_sha256:'4'.repeat(64)};
    const pdfRef:any={source:'EASTMONEY_HK',source_key:'pdf',request:{method:'GET',url:'https://pdf.dfcfw.com/pdf/H2_AN202609281829962076_1.pdf'},retrieved_at:'2026-09-29T13:10:41.252034+08:00',blob_sha256:'5'.repeat(64),body_sha256:'01999cc0581a4472725abd7c5ef0fa73f80cc93f23a70bfd9e72e81ee8be9121'};
    const doc:any={
      schema_version:'v4.manager_research.eastmoney_hk_document.v2',
      event_id:'a'.repeat(64),symbol:'HK.00700',name:'腾讯控股',title:'翌日披露报表 - 已发行股份变动及股份购回',
      target_trade_date:'20260929',source:'EASTMONEY_HK',source_identity:'EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL',
      market_code:'116',stock_code:'00700',art_code:'AN202609281829962076',
      notice_date:'2026-09-28 00:00:00',display_time:'2026-09-28 18:02:03:396',
      display_time_iso:'2026-09-28T18:02:03.396+08:00',available_at:'2026-09-29T13:10:41.252034+08:00',
      retrieved_at:'2026-09-29T13:10:41.252034+08:00',publication_status:'CANNOT_CONFIRM_FIRST_PUBLICATION',
      hkex_first_publication_verified:false,fresh_catalyst_eligible:false,focus_eligible:false,buy_allowed:false,
      full_pdf_stored:true,body_status:'FULL_CONTENT_API_TEXT_VERIFIED',body_source:'EASTMONEY_CONTENT_API_PAGES',
      body_text:'完整正文第一页\n\n完整正文第二页',body_sha256:'6'.repeat(64),content_page_count:2,
      body_pages:[
        {page_index:1,text:'完整正文第一页',text_sha256:'7'.repeat(64),source_ref:page1Ref},
        {page_index:2,text:'完整正文第二页',text_sha256:'8'.repeat(64),source_ref:page2Ref},
      ],pdf_text_extraction_status:'UNVERIFIED_ENCODING',
      pdf_page_count:8,pdf_bytes:132997,document_sha256:'01999cc0581a4472725abd7c5ef0fa73f80cc93f23a70bfd9e72e81ee8be9121',
      source_url:'https://pdf.dfcfw.com/pdf/H2_AN202609281829962076_1.pdf',
      content_url:'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=AN202609281829962076&client_source=web&page_index=1',
      source_refs:[listRef,page1Ref,page2Ref,pdfRef],RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
    };
    const observation:any={
      schema_version:'v4.manager_research.announcement_observation.v1',target_trade_date:'20260929',
      research_cutoff:'2026-09-29T13:22:00+08:00',prior_session:'20260928',status:'NOT_RUN',count_known:false,
      latest_attempt:null,observations:[],pending_observations:[],official_documents:[],coverage:{},gaps:[],capture_runs:[],
      independent_of_strict_near_focus:true,
      eastmoney_hk_status:'PARTIAL',eastmoney_hk_documents:[doc],RESEARCH_ONLY:true,
      production_allowed:false,buy_gate_updated:false,orders_sent:false,
    };
    const validated=validateAnnouncementObservation(observation,'20260929');
    renderAnnouncementObservation(host,validated);

    expect(host.textContent).toContain('东方财富港股公告（聚合来源；不是 HKEX 官方目录）');
    expect(host.textContent).toContain('HKEX 首次发布时间 CANNOT_CONFIRM');
    expect(host.textContent).toContain('2026-09-28 18:02:03:396');
    expect(host.textContent).toContain('2026-09-29T13:10:41.252034+08:00');
    expect(host.textContent).toContain('正文 2 个内容页');
    expect(host.textContent).toContain('查看完整公告正文（2 页）');
    expect(host.textContent).toContain('完整正文第一页');
    expect(host.textContent).toContain('完整正文第二页');
    expect(host.textContent).toContain('完整PDF 8 页 / 132997 bytes');
    expect(host.querySelector('[data-eastmoney-announcement]')).not.toBeNull();
    expect(host.querySelector('a[href="https://pdf.dfcfw.com/pdf/H2_AN202609281829962076_1.pdf"]')?.textContent)
      .toBe('打开东方财富公告 PDF 原件');
  });
});

describe('canonical announcement observation contracts retained',()=>{
  const safety={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
  const empty=()=>({schema_version:'v4.manager_research.announcement_observation.v1',target_trade_date:'20260924',
    research_cutoff:'2026-09-24T08:00:00+08:00',prior_session:'20260923',status:'NOT_RUN',count_known:false,
    latest_attempt:null,observations:[],pending_observations:[],official_documents:[],capture_runs:[],coverage:{},gaps:[],
    independent_of_strict_near_focus:true,...safety});

  it('does not convert NOT_RUN to zero candidates',()=>{
    const host=document.createElement('section');
    renderAnnouncementObservation(host,validateAnnouncementObservation(empty(),'20260924'));
    expect(host.textContent).toContain('数量未知');
    expect(host.textContent).not.toContain('0只候选');
  });

  it('rejects cross-date and BUY elevation',()=>{
    expect(()=>validateAnnouncementObservation(empty(),'20260923')).toThrow();
    expect(()=>validateAnnouncementObservation({...empty(),orders_sent:true},'20260924')).toThrow();
  });

  it('clears old section when input disappears',()=>{
    const host=document.createElement('section');
    host.textContent='OLD STOCK';
    host.dataset.announcementDate='20260923';
    renderAnnouncementObservation(host,undefined);
    expect(host.dataset.announcementDate).toBeUndefined();
    expect(host.textContent).not.toContain('OLD STOCK');
    expect(host.textContent).toContain('状态未知');
  });
});
