import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestManagerAnnouncementAnalysis } from './managerAnnouncementAnalysis.js';

const catalog={status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
  publication_date:'2026-09-29',is_hkex_complete_directory:false,directory_record_count:744,
  directory_page_count:39,manager_announcement_count:234,manager_issuer_count:140,
  catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)};
function payload(verified=true,publicationDate='2026-09-29',basis:'EXPLICIT'|'PREVIOUS_HK_TRADING_SESSION'='PREVIOUS_HK_TRADING_SESSION'){
  const selectedCatalog={...catalog,publication_date:publicationDate};
  const kinds=['COMPLETE_API_BODY','LONG_PDF_KEY_SECTION_READ','TEXT_INSUFFICIENT_UNASSESSED'];
  const records=verified?Array.from({length:234},(_,i)=>({art_code:`AN${String(i).padStart(10,'0')}`,
    analysis_kind:i<207?kinds[0]:i<229?kinds[1]:kinds[2]})):[];
  const manifest={target_trade_date:'20260930',publication_date:publicationDate,
    semantic_catalog_sha256:'432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7',
    body_corpus_sha256:'fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4',
    catalog_run_id:catalog.catalog_run_id,catalog_product_sha256:catalog.catalog_product_sha256,
    verified_inputs:[
      {name:'semantic_catalog',sha256:'432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7',row_count:234},
      {name:'body_corpus',sha256:'fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4',row_count:234},
      {name:'short_additions',sha256:'7ceb46c795daafd99cd66b845367c6857dd450f4386c8e1aa9c625959496d467',row_count:40},
      {name:'long_additions',sha256:'61271fa312c8943bb6160cf02dbe5d65896823a0176070ed1dae5a4a14bd137f',row_count:22},
      {name:'pdf_derivative_index',sha256:'ea4cfdb2ef578c6c3fb39fc3b18ec32a18ef3101fb71852ac212295f3b21a3f9',row_count:22},
    ]};
  return {schema_version:'v4.manager_research.eastmoney_hk_announcement_analysis_read.v1',
    target_trade_date:'20260930',publication_date:publicationDate,
    date_selection_basis:basis,source_catalog:verified?selectedCatalog:{status:'NOT_RUN',readback_status:'NOT_RUN'},
    analysis:verified?{status:'VERIFIED',summary:{directory_records:744,directory_pages:39,
      manager_announcements:234,manager_issuers:140,complete_api_bodies:207,
      long_pdf_focus_reads:22,text_insufficient_unassessed:5},records,
      source_manifest:manifest,source_manifest_sha256:'d'.repeat(64),product_sha256:'e'.repeat(64),
      first_publication_and_cutoff_status:'CANNOT_CONFIRM',novelty_vs_prior_status:'CANNOT_CONFIRM',
      point_in_time_status:'CANNOT_CONFIRM'}:{status:'NOT_IMPORTED',summary:null,records:[]}};
}
function dynamicPayload(){
  const publicationDate='2026-10-06',targetDate='20261007';
  const records=[
    {art_code:'AN202610060001',analysis_kind:'COMPLETE_API_BODY',issuer_codes:[
      {code:'HK.00001',market_code:'116',ann_type:'H'},{code:'HK.00002',market_code:'116',ann_type:'H'}],
      semantic_record_sha256:'3'.repeat(64),body_record_sha256:'4'.repeat(64)},
    {art_code:'AN202610060002',analysis_kind:'COMPLETE_API_BODY',issuer_codes:[
      {code:'HK.00001',market_code:'116',ann_type:'H'}],
      semantic_record_sha256:'5'.repeat(64),body_record_sha256:'6'.repeat(64)},
  ];
  const counts={directory_records:3,directory_pages:2,manager_announcements:2,
    manager_source_identity_associations:3,distinct_manager_source_codes:2,complete_api_bodies:2,
    long_pdf_focus_reads:0,text_insufficient_unassessed:0};
  const catalog={status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
    publication_date:publicationDate,is_hkex_complete_directory:false,directory_record_count:3,
    directory_page_count:2,manager_announcement_count:2,manager_source_identity_association_count:3,
    distinct_manager_source_code_count:2,manager_issuer_count:null,unknown_issuer_count:null,
    issuer_count_status:'CANNOT_CONFIRM',catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)};
  const manifest={target_trade_date:targetDate,publication_date:publicationDate,
    source_scope:'EASTMONEY_HK_DATE_CATALOG',catalog_run_id:catalog.catalog_run_id,
    catalog_product_sha256:catalog.catalog_product_sha256,semantic_catalog_sha256:'c'.repeat(64),
    body_corpus_sha256:'d'.repeat(64),counts,manager_source_identity_association_count:3,
    distinct_manager_source_code_count:2,manager_issuer_count:null,unknown_issuer_count:null,
    issuer_count_status:'CANNOT_CONFIRM',verified_inputs:[
      {name:'semantic_catalog',sha256:'c'.repeat(64),canonical_sha256:'e'.repeat(64),row_count:2},
      {name:'body_corpus',sha256:'d'.repeat(64),canonical_sha256:'f'.repeat(64),row_count:2},
    ]};
  return {schema_version:'v4.manager_research.eastmoney_hk_announcement_analysis_read.v1',
    target_trade_date:targetDate,publication_date:publicationDate,date_selection_basis:'EXPLICIT',
    source_catalog:catalog,analysis:{status:'VERIFIED',summary:{...counts,
      manager_source_identity_association_count:3,distinct_manager_source_code_count:2,
      manager_issuer_count:null,unknown_issuer_count:null,issuer_count_status:'CANNOT_CONFIRM'},
      records,source_manifest:manifest,source_manifest_sha256:'1'.repeat(64),product_sha256:'2'.repeat(64),
      first_publication_and_cutoff_status:'CANNOT_CONFIRM',novelty_vs_prior_status:'CANNOT_CONFIRM',
      point_in_time_status:'CANNOT_CONFIRM'}};
}
afterEach(()=>vi.unstubAllGlobals());

describe('requestManagerAnnouncementAnalysis',()=>{
  it('uses the server HK calendar by default and validates all frozen source identities',async()=>{
    const responseBody=payload();const fetcher=vi.fn(async(url:string)=>{
      expect(url).toContain('date=20260930');expect(url).not.toContain('publication_date=');
      return {ok:true,json:async()=>responseBody};
    });vi.stubGlobal('fetch',fetcher);
    const value=await requestManagerAnnouncementAnalysis('20260930',undefined,new AbortController().signal);
    expect(value.analysis.status).toBe('VERIFIED');expect(fetcher).toHaveBeenCalledOnce();
  });

  it('preserves a missing date as unknown with no success-shaped zero summary',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>payload(false,'2026-09-30','EXPLICIT')})));
    const value=await requestManagerAnnouncementAnalysis('20260930','20260930',new AbortController().signal);
    expect(value.analysis.status).toBe('NOT_IMPORTED');expect(value.analysis.summary).toBeNull();
    expect(value.analysis.records).toEqual([]);
  });

  it('rejects a verified response with a changed source catalog SHA',async()=>{
    const body=payload();
    (body.analysis as {source_manifest:Record<string,unknown>}).source_manifest.catalog_product_sha256='f'.repeat(64);
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    await expect(requestManagerAnnouncementAnalysis('20260930',undefined,new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
  });

  it('rejects non-success HTTP readback and invalid requested dates',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:409})));
    await expect(requestManagerAnnouncementAnalysis('20260930',undefined,new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_HTTP_409');
    await expect(requestManagerAnnouncementAnalysis('20260931',undefined,new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_TARGET_DATE_INVALID');
  });

  it('accepts a dynamic date with separate source-code and association counts',async()=>{
    const body=dynamicPayload();
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    const value=await requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal);
    expect(value.analysis.status).toBe('VERIFIED');
    expect((value.analysis.stock_selection as Record<string,unknown>)?.status).toBe('NOT_ASSESSED');
  });

  it('rejects dynamic date drift, false issuer counts and inconsistent source-code counts',async()=>{
    const dateDrift=dynamicPayload();
    (dateDrift.analysis.source_manifest as Record<string,unknown>).target_trade_date='20261008';
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>dateDrift})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');

    const falseIssuer=dynamicPayload();
    (falseIssuer.analysis.summary as Record<string,unknown>).manager_issuer_count=2;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>falseIssuer})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');

    const wrongCount=dynamicPayload();
    (wrongCount.analysis.source_manifest as Record<string,any>).counts.distinct_manager_source_codes=3;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>wrongCount})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
  });

  it('allows validated supplementary input counts while binding core inputs to article count',async()=>{
    const body=dynamicPayload();
    body.analysis.source_manifest.verified_inputs.push({name:'pdf_derivative_index',
      sha256:'9'.repeat(64),canonical_sha256:'a'.repeat(64),row_count:22});
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    const value=await requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal);
    expect(value.analysis.status).toBe('VERIFIED');

    const negative=dynamicPayload();
    negative.analysis.source_manifest.verified_inputs.push({name:'pdf_derivative_index',
      sha256:'9'.repeat(64),canonical_sha256:'a'.repeat(64),row_count:-1});
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>negative})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');

    const coreMismatch=dynamicPayload();
    coreMismatch.analysis.source_manifest.verified_inputs[0].row_count=1;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>coreMismatch})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
  });

  it('validates dynamic stock-selection totals against distinct source codes',async()=>{
    const body=dynamicPayload(),records=body.analysis.records;
    const decisions=records.map((record,index)=>({art_code:record.art_code,
      issuer_codes:record.issuer_codes.map(item=>item.code),semantic_record_sha256:record.semantic_record_sha256,
      body_record_sha256:record.body_record_sha256,disposition:'NOT_SELECTED',
      reason:`Reviewed reason ${index}`,risk_notes:[]}));
    const sourceBinding={target_trade_date:'20261007',publication_date:'2026-10-06',
      source_scope:'EASTMONEY_HK_DATE_CATALOG',catalog_run_id:body.analysis.source_manifest.catalog_run_id,
      catalog_product_sha256:body.analysis.source_manifest.catalog_product_sha256,
      semantic_catalog_sha256:body.analysis.source_manifest.semantic_catalog_sha256,
      body_corpus_sha256:body.analysis.source_manifest.body_corpus_sha256};
    const selected={schema_version:'v4.manager_research.announcement_stock_selection_read.v1',
      status:'VERIFIED',decision_unit:'ISSUER_CODE',stock_count:2,article_count:2,selected_stock_count:0,
      conditional_watch_count:0,not_selected_stock_count:2,not_assessed_stock_count:0,
      article_decisions:decisions,source_binding:sourceBinding,source_manifest_sha256:body.analysis.source_manifest_sha256,
      product_sha256:body.analysis.product_sha256,base_product_sha256:'7'.repeat(64),
      selection_sha256:'8'.repeat(64),judgment_method:'EXPLICIT_ARTICLE_LEVEL_RESEARCH_DISPOSITION',
      stocks:[
        {stock_code:'HK.00001',stock_name:'Source code HK.00001',status:'NOT_SELECTED',articles:[
          {art_code:records[0].art_code,disposition:'NOT_SELECTED',reason:decisions[0].reason,source_sha256:'9'.repeat(64)},
          {art_code:records[1].art_code,disposition:'NOT_SELECTED',reason:decisions[1].reason,source_sha256:'a'.repeat(64)}],
          selection_reasons:[],not_selected_reasons:[],risk_notes:[]},
        {stock_code:'HK.00002',stock_name:'Source code HK.00002',status:'NOT_SELECTED',articles:[
          {art_code:records[0].art_code,disposition:'NOT_SELECTED',reason:decisions[0].reason,source_sha256:'b'.repeat(64)}],
          selection_reasons:[],not_selected_reasons:[],risk_notes:[]},
      ],gaps:[]};
    (body.analysis as Record<string,unknown>).stock_selection=selected;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    const value=await requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal);
    expect((value.analysis.stock_selection as Record<string,unknown>)?.status).toBe('VERIFIED');
    selected.stock_count=3;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_STOCK_SELECTION_INVALID');
  });
});
