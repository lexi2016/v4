import { afterEach, describe, expect, it, vi } from 'vitest';
import { ANNOUNCEMENT_PREOPEN_WINDOW, requestManagerAnnouncementAnalysis } from './managerAnnouncementAnalysis.js';

const catalog={status:'COMPLETE',readback_status:'VERIFIED',source_scope:'EASTMONEY_HK_DATE_CATALOG',
  publication_date:'2026-09-29',is_hkex_complete_directory:false,directory_record_count:744,
  directory_page_count:39,manager_announcement_count:234,manager_issuer_count:140,
  catalog_run_id:'a'.repeat(32),catalog_product_sha256:'b'.repeat(64)};
function payload(verified=true,publicationDate='2026-09-29',
  basis:'EXPLICIT'|'PREVIOUS_HK_TRADING_SESSION'|'CURRENT_TARGET_PREVIOUS_CALENDAR_DAY'='PREVIOUS_HK_TRADING_SESSION',
  targetDate='20260930'){
  const selectedCatalog={...catalog,publication_date:publicationDate};
  const kinds=['COMPLETE_API_BODY','LONG_PDF_KEY_SECTION_READ','TEXT_INSUFFICIENT_UNASSESSED'];
  const records=verified?Array.from({length:234},(_,i)=>({art_code:`AN${String(i).padStart(10,'0')}`,
    analysis_kind:i<207?kinds[0]:i<229?kinds[1]:kinds[2]})):[];
  const manifest={target_trade_date:targetDate,publication_date:publicationDate,
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
    target_trade_date:targetDate,publication_date:publicationDate,
    date_selection_basis:basis,source_catalog:verified?selectedCatalog:{status:'NOT_RUN',readback_status:'NOT_RUN'},
    analysis:verified?{status:'VERIFIED',summary:{directory_records:744,directory_pages:39,
      manager_announcements:234,manager_issuers:140,complete_api_bodies:207,
      long_pdf_focus_reads:22,text_insufficient_unassessed:5},records,
      source_manifest:manifest,source_manifest_sha256:'d'.repeat(64),product_sha256:'e'.repeat(64),
      first_publication_and_cutoff_status:'CANNOT_CONFIRM',novelty_vs_prior_status:'CANNOT_CONFIRM',
      point_in_time_status:'CANNOT_CONFIRM'}:{status:'NOT_IMPORTED',summary:null,records:[]}};
}
function preopenPayload(){
  const body=payload(true,'2026-10-12','EXPLICIT','20261012') as unknown as Record<string,any>;
  const coverage={status:'PARTIAL',expected_dates:['20261009','20261010','20261011','20261012'],
    covered_dates:['20261009','20261012'],missing_dates:['20261010','20261011'],missing_date_count:2};
  const candidate={publication_date:'2026-10-09',source_identity:{kind:'art_code',id:'AN20261009000001'},
    source:'EASTMONEY',title:'Reviewed event',issuer_codes:[{code:'HK.00001',name:'Issuer'}],
    classification:'BUSINESS_EVENT',factual_summary:'An explicit product milestone was disclosed.',
    why_useful:'It changes the issuer product timeline.',event_status_assessment:null,
    analysis_kind:'COMPLETE_API_BODY',body_status:null,semantic_record_sha256:'a'.repeat(64),
    source_record_sha256:'b'.repeat(64),body_text_sha256:'c'.repeat(64),publication_time:'2026-10-09T10:00:00+08:00',
    publication_time_basis:'OFFICIAL_SOURCE_TIMESTAMP',disposition:'SELECTED_EVENT',selection_basis:'EXPLICIT_REVIEW',
    direction:'POSITIVE',evidence_sufficiency:'VERIFIED_EXISTING_FACTS',reason:'Reviewed concrete event.',risk_notes:['Commercial effect remains unconfirmed.'],
    supporting_exact_quote:'A short exact source quote.',source_refs:[{url:'https://np-anotice-stock.eastmoney.com/api/ann?id=AN20261009000001',
      blob_sha256:null,body_sha256:'d'.repeat(64)}],retrospective_status:'SOURCE_PUBLISHED_IN_WINDOW',source_record_validation:'PASS'};
  const retrospective={status:'PARTIAL',candidate_count:1,positive_candidate_count:1,candidates:[candidate],
    pending_count:1,pending_queue:[{publication_date:'2026-10-12',source_identity:{kind:'source_variant_id',id:'HKEX:12345678'},
      reason_codes:['QUALIFICATION_AT_CUTOFF_CANNOT_CONFIRM']}]};
  const actual={status:'CANNOT_CONFIRM',positive_candidate_count:null,positive_candidates:[],
    candidate_evaluations:[{publication_date:'2026-10-09',source_identity:candidate.source_identity,
      source_record_sha256:candidate.source_record_sha256,status:'CANNOT_CONFIRM',reason_codes:['OWNER_IMPORT_AFTER_CUTOFF']}],
    gaps:['QUALIFICATION_AT_CUTOFF_CANNOT_CONFIRM']};
  const binding={target_trade_date:'20261012',source_semantic_catalog_sha256:'e'.repeat(64),
    source_body_corpus_file_sha256:'f'.repeat(64),draft_analysis_product_sha256:'1'.repeat(64),
    draft_source_manifest_sha256:'2'.repeat(64)};
  const artifact={schema_version:'v4.manager_research.announcement_preopen_window.v1',target_trade_date:'20261012',
    window_start:ANNOUNCEMENT_PREOPEN_WINDOW.windowStart,as_of:ANNOUNCEMENT_PREOPEN_WINDOW.asOf,
    input_fingerprint_sha256:'3'.repeat(64),registered_fingerprint_sha256:'4'.repeat(64),registered_binding:binding,
    coverage,retrospective_research:retrospective,actual_preopen:actual};
  body.analysis.source_manifest.preopen_window=artifact;
  body.preopen_window_readback={status:'VERIFIED',window_start:artifact.window_start,as_of:artifact.as_of,
    registered_fingerprint_sha256:artifact.registered_fingerprint_sha256,
    input_fingerprint_sha256:artifact.input_fingerprint_sha256,coverage,retrospective_research:retrospective,actual_preopen:actual};
  return body;
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
function multiSourcePayload(){
  const body=dynamicPayload() as unknown as {source_catalog:Record<string,any>;analysis:Record<string,any>};
  const {source_catalog:catalog,analysis}=body,manifest=analysis.source_manifest as Record<string,any>;
  const records=analysis.records as Record<string,any>[];
  const variantId='HKEX:12345678',bodySha='7'.repeat(64),semanticSha='8'.repeat(64);
  const official={source_variant_id:variantId,source:'HKEX_OFFICIAL',source_scope:'HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1',
    news_id:'12345678',title:'Official notice',analysis_kind:'COMPLETE_HKEX_OFFICIAL_PDF_BODY',
    body_status:'COMPLETE_HKEX_OFFICIAL_PDF_BODY',issuer_codes:[{code:'HK.00001',name:'Fixture One'}],
    matched_connect_codes:['HK.00001'],connect_eligibility_status:'ELIGIBLE',
    connect_eligibility_identity_sha256:'9'.repeat(64),semantic_record_sha256:semanticSha,body_record_sha256:bodySha,
    listing_source:{source_variant_id:variantId,source_scope:'HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1',news_id:'12345678',
      symbol:'HK.00001',directory_source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1006/202610060001.pdf'},
      directory_raw_body_sha256:'f'.repeat(64),
      publication_date:'2026-10-06',
      body_source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1006/202610060001.pdf'}},
    body_page_citations:[{page_index:1,text_sha256:'a'.repeat(64),
      source_ref:{url:'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1006/202610060001.pdf'}}]};
  records.push(official);
  const counts=manifest.counts as Record<string,number>;
  Object.assign(counts,{manager_announcements:3,eligible_eastmoney_announcements:2,
    hkex_official_announcements:1,combined_eligible_announcements:3,complete_hkex_pdf_bodies:1});
  const summary=analysis.summary as Record<string,unknown>;
  Object.assign(summary,{...counts,manager_source_identity_association_count:3,distinct_manager_source_code_count:2,
    manager_issuer_count:null,unknown_issuer_count:null,issuer_count_status:'CANNOT_CONFIRM'});
  manifest.additional_source_scopes=['HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1'];
  manifest.verified_inputs[0].row_count=3;
  Object.assign(manifest,{manager_issuer_count:null,unknown_issuer_count:null,issuer_count_status:'CANNOT_CONFIRM',
    hkex_directory_readback_sha256:'b'.repeat(64),hkex_directory_run_ids:['c'.repeat(32)],
    hkex_directory_document_count:1,hkex_eligible_document_count:1,hkex_excluded_document_count:0,
    hkex_unresolved_document_count:0,hkex_source_variant_count:1,hkex_source_variant_sha256s:{[variantId]:bodySha},
    hkex_body_status_counts:{COMPLETE_HKEX_OFFICIAL_PDF_BODY:1},hkex_body_coverage_status:'COMPLETE',
    hkex_unresolved_source_identity_gap:false,hkex_cross_source_link_status:'NOT_ASSESSED',
    monthly_connect_eligibility_identity_sha256:'d'.repeat(64),monthly_connect_source_date:'20261001',
    monthly_connect_code_count:698,connect_eligibility_status:'VERIFIED_MONTHLY_SNAPSHOT'});
  const decisions=records.map((record,index)=>({...(record.source_variant_id
      ?{source_variant_id:record.source_variant_id}:{art_code:record.art_code}),
    issuer_codes:record.issuer_codes.map((item:Record<string,unknown>)=>item.code),
    semantic_record_sha256:record.semantic_record_sha256,body_record_sha256:record.body_record_sha256,
    disposition:'NOT_SELECTED',reason:`Reviewed disposition ${index}`,risk_notes:[]}));
  const stockCodes=[...new Set(records.flatMap(record=>record.issuer_codes.map((item:Record<string,unknown>)=>item.code)))];
  const stocks=stockCodes.map(stockCode=>{
    const articles=records.flatMap((record,index)=>decisions[index].issuer_codes.includes(stockCode)?[{
      ...(record.source_variant_id?{source_variant_id:record.source_variant_id}:{art_code:record.art_code}),
      disposition:'NOT_SELECTED',reason:decisions[index].reason,source_sha256:record.semantic_record_sha256,
    }]:[]);
    return {stock_code:stockCode,stock_name:`Source code ${stockCode}`,status:'NOT_SELECTED',articles,
      selection_reasons:[],not_selected_reasons:[],risk_notes:[]};
  });
  const sourceBinding={target_trade_date:'20261007',publication_date:'2026-10-06',
    source_scope:'EASTMONEY_HK_DATE_CATALOG',catalog_run_id:catalog.catalog_run_id,
    catalog_product_sha256:catalog.catalog_product_sha256,semantic_catalog_sha256:manifest.semantic_catalog_sha256,
    body_corpus_sha256:manifest.body_corpus_sha256,hkex_directory_readback_sha256:manifest.hkex_directory_readback_sha256,
    monthly_connect_eligibility_identity_sha256:manifest.monthly_connect_eligibility_identity_sha256,
    monthly_connect_source_date:manifest.monthly_connect_source_date,additional_source_scopes_sha256:'e'.repeat(64)};
  analysis.stock_selection={schema_version:'v4.manager_research.announcement_stock_selection_read.v1',
    status:'VERIFIED',decision_unit:'ISSUER_CODE',stock_count:2,article_count:3,selected_stock_count:0,
    conditional_watch_count:0,not_selected_stock_count:2,not_assessed_stock_count:0,article_decisions:decisions,
    stocks,source_binding:sourceBinding,source_manifest_sha256:analysis.source_manifest_sha256,product_sha256:analysis.product_sha256,
    base_product_sha256:'f'.repeat(64),selection_sha256:'1'.repeat(64),
    judgment_method:'EXPLICIT_ARTICLE_LEVEL_RESEARCH_DISPOSITION',gaps:[]};
  return body;
}
afterEach(()=>vi.unstubAllGlobals());

describe('requestManagerAnnouncementAnalysis',()=>{
  it('requests the exact 09:20 window and validates its registered projection separately from actual eligibility',async()=>{
    const body=preopenPayload();
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
      const parsed=new URL(url,'https://v4.local');
      expect(parsed.searchParams.get('window_start')).toBe(ANNOUNCEMENT_PREOPEN_WINDOW.windowStart);
      expect(parsed.searchParams.get('as_of')).toBe(ANNOUNCEMENT_PREOPEN_WINDOW.asOf);
      expect(parsed.searchParams.get('publication_date')).toBe('20261012');
      return {ok:true,json:async()=>body};
    }));
    const value=await requestManagerAnnouncementAnalysis('20261012','20261012',new AbortController().signal,
      {windowStart:ANNOUNCEMENT_PREOPEN_WINDOW.windowStart,asOf:ANNOUNCEMENT_PREOPEN_WINDOW.asOf});
    expect(value.preopen_window_readback?.status).toBe('VERIFIED');
    expect(value.preopen_window_readback?.retrospective_research?.positive_candidate_count).toBe(1);
    expect(value.preopen_window_readback?.actual_preopen?.status).toBe('CANNOT_CONFIRM');

    body.preopen_window_readback.retrospective_research.candidate_count=0;
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    await expect(requestManagerAnnouncementAnalysis('20261012','20261012',new AbortController().signal,
      {windowStart:ANNOUNCEMENT_PREOPEN_WINDOW.windowStart,asOf:ANNOUNCEMENT_PREOPEN_WINDOW.asOf}))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_PREOPEN_WINDOW_READBACK_INVALID');
  });

  it('uses the server HK calendar by default and validates all frozen source identities',async()=>{
    const responseBody=payload();const fetcher=vi.fn(async(url:string)=>{
      expect(url).toContain('date=20260930');expect(url).not.toContain('publication_date=');
      return {ok:true,json:async()=>responseBody};
    });vi.stubGlobal('fetch',fetcher);
    const value=await requestManagerAnnouncementAnalysis('20260930',undefined,new AbortController().signal);
    expect(value.analysis.status).toBe('VERIFIED');expect(fetcher).toHaveBeenCalledOnce();
  });

  it('accepts and validates the current-target previous calendar-day default',async()=>{
    const responseBody=payload(true,'2026-10-11','CURRENT_TARGET_PREVIOUS_CALENDAR_DAY','20261012');
    const fetcher=vi.fn(async(url:string)=>{
      expect(url).toContain('date=20261012');expect(url).not.toContain('publication_date=');
      return {ok:true,json:async()=>responseBody};
    });vi.stubGlobal('fetch',fetcher);
    const value=await requestManagerAnnouncementAnalysis('20261012',undefined,new AbortController().signal);
    expect(value.publication_date).toBe('2026-10-11');
    expect(value.date_selection_basis).toBe('CURRENT_TARGET_PREVIOUS_CALENDAR_DAY');

    responseBody.publication_date='2026-10-09';
    const mismatched=responseBody as unknown as {
      source_catalog:Record<string,unknown>;
      analysis:{source_manifest:Record<string,unknown>};
    };
    mismatched.source_catalog.publication_date='2026-10-09';
    mismatched.analysis.source_manifest.publication_date='2026-10-09';
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>responseBody})));
    await expect(requestManagerAnnouncementAnalysis('20261012',undefined,new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_RESPONSE_DATE_INVALID');
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
          {art_code:records[0].art_code,disposition:'NOT_SELECTED',reason:decisions[0].reason,source_sha256:records[0].semantic_record_sha256},
          {art_code:records[1].art_code,disposition:'NOT_SELECTED',reason:decisions[1].reason,source_sha256:records[1].semantic_record_sha256}],
          selection_reasons:[],not_selected_reasons:[],risk_notes:[]},
        {stock_code:'HK.00002',stock_name:'Source code HK.00002',status:'NOT_SELECTED',articles:[
          {art_code:records[0].art_code,disposition:'NOT_SELECTED',reason:decisions[0].reason,source_sha256:records[0].semantic_record_sha256}],
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

  it('keeps a mixed HKEX source_variant_id through selection and rejects an art_code cross-join',async()=>{
    const body=multiSourcePayload();
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    const value=await requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal);
    expect((value.analysis.records as Record<string,unknown>[]).some(row=>row.source_variant_id==='HKEX:12345678')).toBe(true);
    expect((value.analysis.stock_selection as Record<string,any>).article_decisions.some((row:Record<string,unknown>)=>
      row.source_variant_id==='HKEX:12345678'&&row.art_code===undefined)).toBe(true);

    const fakeJoin=multiSourcePayload();
    const fake=fakeJoin.analysis.stock_selection.article_decisions.find((row:Record<string,unknown>)=>
      row.source_variant_id==='HKEX:12345678');
    fake.art_code='AN202610060099';
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>fakeJoin})));
    await expect(requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal))
      .rejects.toThrow('ANNOUNCEMENT_ANALYSIS_STOCK_SELECTION_INVALID');
  });

  it('accepts a captured HKEX body whose semantic record remains explicitly unassessed',async()=>{
    const body=multiSourcePayload();
    const analysis=body.analysis as Record<string,any>,manifest=analysis.source_manifest as Record<string,any>;
    const record=(analysis.records as Record<string,any>[]).find(row=>row.source_variant_id==='HKEX:12345678')!;
    record.analysis_kind='TEXT_INSUFFICIENT_UNASSESSED';record.selection_status='NOT_ASSESSED';
    const counts=manifest.counts as Record<string,number>;
    counts.text_insufficient_unassessed=1;counts.complete_hkex_pdf_bodies=0;
    const summary=analysis.summary as Record<string,number>;
    summary.text_insufficient_unassessed=1;summary.complete_hkex_pdf_bodies=0;
    manifest.hkex_body_coverage_status='PARTIAL';
    const selection=analysis.stock_selection as Record<string,any>;
    selection.not_selected_stock_count=1;selection.not_assessed_stock_count=1;
    selection.article_decisions.find((row:Record<string,any>)=>row.source_variant_id==='HKEX:12345678').disposition='NOT_ASSESSED';
    selection.stocks[0].status='NOT_ASSESSED';
    selection.stocks[0].articles.find((row:Record<string,any>)=>row.source_variant_id==='HKEX:12345678').disposition='NOT_ASSESSED';
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>body})));
    const value=await requestManagerAnnouncementAnalysis('20261007','20261006',new AbortController().signal);
    expect(value.analysis.status).toBe('VERIFIED');
    const accepted=(value.analysis.records as Record<string,any>[]).find(row=>row.source_variant_id==='HKEX:12345678');
    expect(accepted?.analysis_kind).toBe('TEXT_INSUFFICIENT_UNASSESSED');
    expect(accepted?.body_status).toBe('COMPLETE_HKEX_OFFICIAL_PDF_BODY');
  });
});
