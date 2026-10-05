/** Read-only, date-bound projection of the reviewed Eastmoney HK analysis. */
export type AnnouncementAnalysisObject = Record<string, unknown>;

export interface ManagerAnnouncementAnalysis extends AnnouncementAnalysisObject {
  schema_version: 'v4.manager_research.eastmoney_hk_announcement_analysis_read.v1';
  target_trade_date: string;
  publication_date: string;
  date_selection_basis: 'EXPLICIT' | 'PREVIOUS_HK_TRADING_SESSION';
  source_catalog: AnnouncementAnalysisObject;
  analysis: AnnouncementAnalysisObject;
}

const object=(value:unknown):value is AnnouncementAnalysisObject=>
  Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
const validDate=(value:string)=>{
  if(!/^\d{8}$/.test(value))return false;
  const year=Number(value.slice(0,4)),month=Number(value.slice(4,6)),day=Number(value.slice(6,8));
  const date=new Date(Date.UTC(year,month-1,day));
  return date.getUTCFullYear()===year&&date.getUTCMonth()+1===month&&date.getUTCDate()===day;
};
const validSha=(value:unknown)=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const expectedInputs:Record<string,{sha256:string;row_count:number}>={
  semantic_catalog:{sha256:'432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7',row_count:234},
  body_corpus:{sha256:'fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4',row_count:234},
  short_additions:{sha256:'7ceb46c795daafd99cd66b845367c6857dd450f4386c8e1aa9c625959496d467',row_count:40},
  long_additions:{sha256:'61271fa312c8943bb6160cf02dbe5d65896823a0176070ed1dae5a4a14bd137f',row_count:22},
  pdf_derivative_index:{sha256:'ea4cfdb2ef578c6c3fb39fc3b18ec32a18ef3101fb71852ac212295f3b21a3f9',row_count:22},
};
function validSourceInputs(value:unknown):boolean{
  if(!Array.isArray(value)||value.length!==Object.keys(expectedInputs).length)return false;
  const seen=new Set<string>();
  return value.every(item=>{
    if(!object(item)||typeof item.name!=='string'||seen.has(item.name))return false;
    seen.add(item.name);const expected=expectedInputs[item.name];
    return Boolean(expected)&&item.sha256===expected.sha256&&item.row_count===expected.row_count;
  })&&seen.size===Object.keys(expectedInputs).length;
}

function validate(raw:unknown,targetDate:string,requestedPublicationDate?:string):ManagerAnnouncementAnalysis{
  if(!object(raw)||raw.schema_version!=='v4.manager_research.eastmoney_hk_announcement_analysis_read.v1'||
      raw.target_trade_date!==targetDate||typeof raw.publication_date!=='string'||
      !/^\d{4}-\d{2}-\d{2}$/.test(raw.publication_date)||
      !['EXPLICIT','PREVIOUS_HK_TRADING_SESSION'].includes(String(raw.date_selection_basis))||
      !object(raw.source_catalog)||!object(raw.analysis))
    throw new Error('ANNOUNCEMENT_ANALYSIS_RESPONSE_IDENTITY_INVALID');
  const publicationToken=raw.publication_date.replaceAll('-','');
  if(!validDate(publicationToken)||(requestedPublicationDate&&publicationToken!==requestedPublicationDate)||
      (requestedPublicationDate&&raw.date_selection_basis!=='EXPLICIT')||
      (!requestedPublicationDate&&raw.date_selection_basis!=='PREVIOUS_HK_TRADING_SESSION'))
    throw new Error('ANNOUNCEMENT_ANALYSIS_RESPONSE_DATE_INVALID');
  const analysis=raw.analysis;
  if(!['NOT_IMPORTED','SOURCE_CATALOG_UNVERIFIED','VERIFIED'].includes(String(analysis.status)))
    throw new Error('ANNOUNCEMENT_ANALYSIS_STATUS_INVALID');
  if(analysis.status==='VERIFIED'){
    const catalog=raw.source_catalog,summary=analysis.summary,manifest=analysis.source_manifest;
    if(catalog.status!=='COMPLETE'||catalog.readback_status!=='VERIFIED'||
        catalog.source_scope!=='EASTMONEY_HK_DATE_CATALOG'||
        catalog.publication_date!==raw.publication_date||catalog.is_hkex_complete_directory!==false||
        catalog.directory_record_count!==744||catalog.directory_page_count!==39||
        catalog.manager_announcement_count!==234||catalog.manager_issuer_count!==140||
        !object(summary)||summary.directory_records!==744||summary.directory_pages!==39||
        summary.manager_announcements!==234||summary.manager_issuers!==140||
        summary.complete_api_bodies!==207||summary.long_pdf_focus_reads!==22||
        summary.text_insufficient_unassessed!==5||!Array.isArray(analysis.records)||analysis.records.length!==234||
        !object(manifest)||manifest.target_trade_date!==targetDate||
        manifest.publication_date!==raw.publication_date||
        manifest.semantic_catalog_sha256!=='432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7'||
        manifest.body_corpus_sha256!=='fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4'||
        manifest.catalog_run_id!==catalog.catalog_run_id||
        manifest.catalog_product_sha256!==catalog.catalog_product_sha256||
        !validSourceInputs(manifest.verified_inputs)||
        analysis.first_publication_and_cutoff_status!=='CANNOT_CONFIRM'||
        analysis.novelty_vs_prior_status!=='CANNOT_CONFIRM'||analysis.point_in_time_status!=='CANNOT_CONFIRM'||
        !validSha(analysis.product_sha256)||!validSha(analysis.source_manifest_sha256))
      throw new Error('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
    const codes=new Set<string>(),counts:Record<string,number>={COMPLETE_API_BODY:0,LONG_PDF_KEY_SECTION_READ:0,TEXT_INSUFFICIENT_UNASSESSED:0};
    for(const row of analysis.records){
      if(!object(row)||typeof row.art_code!=='string'||codes.has(row.art_code)||
          !Object.prototype.hasOwnProperty.call(counts,String(row.analysis_kind)))
        throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
      codes.add(row.art_code);counts[String(row.analysis_kind)]++;
    }
    if(counts.COMPLETE_API_BODY!==207||counts.LONG_PDF_KEY_SECTION_READ!==22||
        counts.TEXT_INSUFFICIENT_UNASSESSED!==5)
      throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_COUNTS_INVALID');
  }else if(analysis.summary!==null||!Array.isArray(analysis.records)||analysis.records.length!==0){
    throw new Error('ANNOUNCEMENT_ANALYSIS_MISSING_MUST_NOT_LOOK_COMPLETE');
  }
  return raw as ManagerAnnouncementAnalysis;
}

/** Omit publicationDate to let the existing HK market calendar choose the previous session. */
export async function requestManagerAnnouncementAnalysis(
  targetDate:string,publicationDate:string|undefined,signal:AbortSignal,
):Promise<ManagerAnnouncementAnalysis>{
  if(!validDate(targetDate))throw new Error('ANNOUNCEMENT_ANALYSIS_TARGET_DATE_INVALID');
  if(publicationDate!==undefined&&!validDate(publicationDate))
    throw new Error('ANNOUNCEMENT_ANALYSIS_PUBLICATION_DATE_INVALID');
  const params=new URLSearchParams({date:targetDate});
  if(publicationDate)params.set('publication_date',publicationDate);
  const response=await fetch(`/api/v4/manager/research/announcements/analysis?${params.toString()}`,{
    method:'GET',signal,credentials:'same-origin',cache:'no-store',
  });
  if(!response.ok)throw new Error(`ANNOUNCEMENT_ANALYSIS_HTTP_${response.status}`);
  let raw:unknown;
  try{raw=await response.json();}catch{throw new Error('ANNOUNCEMENT_ANALYSIS_RESPONSE_JSON_INVALID');}
  return validate(raw,targetDate,publicationDate);
}
