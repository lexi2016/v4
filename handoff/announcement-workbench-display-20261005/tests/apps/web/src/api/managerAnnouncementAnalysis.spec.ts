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
});
