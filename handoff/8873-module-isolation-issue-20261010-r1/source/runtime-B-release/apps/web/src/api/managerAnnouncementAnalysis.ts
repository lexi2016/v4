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

const noSelectionAssessment=()=>({
  schema_version:'v4.manager_research.announcement_stock_selection_read.v1',
  status:'NOT_ASSESSED',decision_unit:'ISSUER_CODE',stock_count:null,
  selected_stock_count:null,conditional_watch_count:null,not_selected_stock_count:null,
  not_assessed_stock_count:null,stocks:[],article_decisions:[],
  gaps:['ANNOUNCEMENT_SELECTION_NOT_ASSESSED'],
});

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

const legacySemanticSha='432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7';
const legacyBodySha='fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4';
const isLegacyManifest=(value:unknown)=>object(value)&&value.semantic_catalog_sha256===legacySemanticSha&&
  value.body_corpus_sha256===legacyBodySha;
function sourceCodeStats(records:unknown[]):{associations:number;codes:Set<string>}|null{
  let associations=0;const codes=new Set<string>();
  for(const raw of records){
    if(!object(raw)||!Array.isArray(raw.issuer_codes)||raw.issuer_codes.length===0)return null;
    const rowCodes:string[]=[];
    for(const item of raw.issuer_codes){
      if(!object(item)||typeof item.code!=='string'||!item.code||item.market_code!=='116'||item.ann_type!=='H')return null;
      rowCodes.push(item.code);
    }
    if(new Set(rowCodes).size!==rowCodes.length)return null;
    associations+=rowCodes.length;rowCodes.forEach(code=>codes.add(code));
  }
  return {associations,codes};
}
function validDynamicInputs(value:unknown,manifest:AnnouncementAnalysisObject,articleCount:number):boolean{
  if(!Array.isArray(value)||value.length<2)return false;
  const byName=new Map<string,AnnouncementAnalysisObject>();
  for(const raw of value){
    if(!object(raw)||typeof raw.name!=='string'||!raw.name||byName.has(raw.name)||
        !validSha(raw.sha256)||!validSha(raw.canonical_sha256)||
        typeof raw.row_count!=='number'||!Number.isInteger(raw.row_count)||raw.row_count<0||
        'path' in raw||'local_path' in raw||'uri' in raw)return false;
    byName.set(raw.name,raw);
  }
  const semantic=byName.get('semantic_catalog'),body=byName.get('body_corpus');
  if(!semantic||!body)return false;
  return semantic.sha256===manifest.semantic_catalog_sha256&&
    body.sha256===manifest.body_corpus_sha256&&semantic.row_count===articleCount&&body.row_count===articleCount;
}

const dispositions=new Set(['SELECTED_EVENT','SELECTED_PERFORMANCE','CONDITIONAL_WATCH','NOT_SELECTED','NOT_ASSESSED']);
function validStockSelection(value:unknown,analysis:AnnouncementAnalysisObject,targetDate:string):boolean{
  if(!object(value)||value.schema_version!=='v4.manager_research.announcement_stock_selection_read.v1'||
      value.decision_unit!=='ISSUER_CODE')return false;
  if(value.status==='NOT_ASSESSED')
    return value.stock_count===null&&value.selected_stock_count===null&&
      value.conditional_watch_count===null&&value.not_selected_stock_count===null&&
      value.not_assessed_stock_count===null&&Array.isArray(value.stocks)&&value.stocks.length===0&&
      Array.isArray(value.article_decisions)&&value.article_decisions.length===0;
  const records=Array.isArray(analysis.records)?analysis.records:[];
  const legacy=isLegacyManifest(analysis.source_manifest);
  const sourceStats=legacy?null:sourceCodeStats(records);
  const expectedStockCount=legacy?140:(sourceStats?.codes.size??-1);
  const expectedArticleCount=legacy?234:records.length;
  if(value.status!=='VERIFIED'||expectedStockCount<0||value.stock_count!==expectedStockCount||
      typeof value.selected_stock_count!=='number'||!Number.isInteger(value.selected_stock_count)||
      typeof value.conditional_watch_count!=='number'||!Number.isInteger(value.conditional_watch_count)||
      typeof value.not_selected_stock_count!=='number'||!Number.isInteger(value.not_selected_stock_count)||
      typeof value.not_assessed_stock_count!=='number'||!Number.isInteger(value.not_assessed_stock_count)||
      value.selected_stock_count+value.conditional_watch_count+value.not_selected_stock_count+
        value.not_assessed_stock_count!==expectedStockCount||value.article_count!==expectedArticleCount||
      !Array.isArray(value.stocks)||value.stocks.length!==expectedStockCount||
      !Array.isArray(value.article_decisions)||value.article_decisions.length!==expectedArticleCount||
      !object(value.source_binding)||!object(analysis.source_manifest))return false;
  const manifest=analysis.source_manifest,binding=value.source_binding;
  if(binding.target_trade_date!==targetDate||
      binding.publication_date!==manifest.publication_date||
      binding.source_scope!=='EASTMONEY_HK_DATE_CATALOG'||
      binding.catalog_run_id!==manifest.catalog_run_id||
      binding.catalog_product_sha256!==manifest.catalog_product_sha256||
      binding.semantic_catalog_sha256!==manifest.semantic_catalog_sha256||
      binding.body_corpus_sha256!==manifest.body_corpus_sha256||
      value.source_manifest_sha256!==analysis.source_manifest_sha256||
      value.product_sha256!==analysis.product_sha256||
      !validSha(value.base_product_sha256)||!validSha(value.selection_sha256)||
      !['EXPLICIT_ARTICLE_LEVEL_RESEARCH_DISPOSITION'].includes(String(value.judgment_method)))return false;
  if(!Array.isArray(analysis.records)||analysis.records.length!==expectedArticleCount)return false;
  const recordByCode=new Map<string,AnnouncementAnalysisObject>();
  for(const rawRecord of analysis.records){
    if(!object(rawRecord)||typeof rawRecord.art_code!=='string'||recordByCode.has(rawRecord.art_code)||
        !Array.isArray(rawRecord.issuer_codes))return false;
    recordByCode.set(rawRecord.art_code,rawRecord);
  }
  const decisionByCode=new Map<string,AnnouncementAnalysisObject>();
  for(const rawDecision of value.article_decisions){
    if(!object(rawDecision)||typeof rawDecision.art_code!=='string'||decisionByCode.has(rawDecision.art_code)||
        !Array.isArray(rawDecision.issuer_codes)||rawDecision.issuer_codes.length===0||
        rawDecision.issuer_codes.some(code=>typeof code!=='string'||!code)||
        !validSha(rawDecision.semantic_record_sha256)||!validSha(rawDecision.body_record_sha256)||
        !dispositions.has(String(rawDecision.disposition))||
        typeof rawDecision.reason!=='string'||!rawDecision.reason.trim()||!Array.isArray(rawDecision.risk_notes)||
        rawDecision.risk_notes.some(note=>typeof note!=='string'||!note.trim()))return false;
    const sourceRecord=recordByCode.get(rawDecision.art_code);
    if(!sourceRecord||!Array.isArray(sourceRecord.issuer_codes)||
        !validSha(sourceRecord.semantic_record_sha256)||!validSha(sourceRecord.body_record_sha256)||
        rawDecision.semantic_record_sha256!==sourceRecord.semantic_record_sha256||
        rawDecision.body_record_sha256!==sourceRecord.body_record_sha256||
        JSON.stringify(rawDecision.issuer_codes)!==JSON.stringify(sourceRecord.issuer_codes.map((issuer:unknown)=>
          object(issuer)?issuer.code:undefined)))return false;
    decisionByCode.set(rawDecision.art_code,rawDecision);
  }
  if(decisionByCode.size!==recordByCode.size)return false;
  const stocksSeen=new Set<string>();
  let selectedCount=0,watchCount=0,notSelectedCount=0,notAssessedCount=0;
  for(const rawStock of value.stocks){
    if(!object(rawStock)||typeof rawStock.stock_code!=='string'||!rawStock.stock_code||
        stocksSeen.has(rawStock.stock_code)||typeof rawStock.stock_name!=='string'||
        !Array.isArray(rawStock.articles)||rawStock.articles.length===0||
        !Array.isArray(rawStock.selection_reasons)||!Array.isArray(rawStock.not_selected_reasons)||
        !Array.isArray(rawStock.risk_notes))return false;
    stocksSeen.add(rawStock.stock_code);
    const articleDispositions=new Set<string>();
    for(const article of rawStock.articles){
      if(!object(article)||typeof article.art_code!=='string')return false;
      const decision=decisionByCode.get(article.art_code);
      if(!decision||!Array.isArray(decision.issuer_codes)||!decision.issuer_codes.includes(rawStock.stock_code)||
          article.disposition!==decision.disposition||article.reason!==decision.reason||
          !validSha(article.source_sha256))return false;
      articleDispositions.add(String(article.disposition));
    }
    const status=articleDispositions.has('SELECTED_EVENT')||articleDispositions.has('SELECTED_PERFORMANCE')?'SELECTED':
      articleDispositions.has('CONDITIONAL_WATCH')?'CONDITIONAL_WATCH':
      articleDispositions.has('NOT_ASSESSED')?'NOT_ASSESSED':'NOT_SELECTED';
    if(rawStock.status!==status)return false;
    if(status==='SELECTED')selectedCount++;
    else if(status==='CONDITIONAL_WATCH')watchCount++;
    else if(status==='NOT_ASSESSED')notAssessedCount++;
    else notSelectedCount++;
  }
  return stocksSeen.size===expectedStockCount&&selectedCount===value.selected_stock_count&&
    watchCount===value.conditional_watch_count&&notSelectedCount===value.not_selected_stock_count&&
    notAssessedCount===value.not_assessed_stock_count;
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
    if(!object(summary)||!object(manifest)||!Array.isArray(analysis.records)||
        catalog.status!=='COMPLETE'||catalog.readback_status!=='VERIFIED'||
        catalog.source_scope!=='EASTMONEY_HK_DATE_CATALOG'||
        catalog.publication_date!==raw.publication_date||catalog.is_hkex_complete_directory!==false||
        manifest.target_trade_date!==targetDate||manifest.publication_date!==raw.publication_date||
        manifest.catalog_run_id!==catalog.catalog_run_id||
        manifest.catalog_product_sha256!==catalog.catalog_product_sha256||
        analysis.first_publication_and_cutoff_status!=='CANNOT_CONFIRM'||
        analysis.novelty_vs_prior_status!=='CANNOT_CONFIRM'||analysis.point_in_time_status!=='CANNOT_CONFIRM'||
        !validSha(analysis.product_sha256)||!validSha(analysis.source_manifest_sha256))
      throw new Error('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
    const legacy=isLegacyManifest(manifest);
    if(legacy){
      if(catalog.directory_record_count!==744||catalog.directory_page_count!==39||
          catalog.manager_announcement_count!==234||catalog.manager_issuer_count!==140||
          summary.directory_records!==744||summary.directory_pages!==39||
          summary.manager_announcements!==234||summary.manager_issuers!==140||
          summary.complete_api_bodies!==207||summary.long_pdf_focus_reads!==22||
          summary.text_insufficient_unassessed!==5||analysis.records.length!==234||
          !validSourceInputs(manifest.verified_inputs))
        throw new Error('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
    }else{
      const counts=object(manifest.counts)?manifest.counts:{};
      const stats=sourceCodeStats(analysis.records);
      const numeric=(value:unknown)=>typeof value==='number'&&Number.isInteger(value)&&value>=0;
      const kindCounts={COMPLETE_API_BODY:0,LONG_PDF_KEY_SECTION_READ:0,TEXT_INSUFFICIENT_UNASSESSED:0};
      for(const row of analysis.records){
        if(object(row)&&Object.prototype.hasOwnProperty.call(kindCounts,String(row.analysis_kind)))
          kindCounts[String(row.analysis_kind) as keyof typeof kindCounts]++;
      }
      const articleCount=analysis.records.length;
      if(!stats||articleCount<1||
          manifest.source_scope!=='EASTMONEY_HK_DATE_CATALOG'||
          !numeric(catalog.directory_record_count)||!numeric(catalog.directory_page_count)||
          catalog.manager_announcement_count!==articleCount||
          catalog.manager_source_identity_association_count!==stats.associations||
          catalog.distinct_manager_source_code_count!==stats.codes.size||
          catalog.manager_issuer_count!==null||catalog.unknown_issuer_count!==null||
          catalog.issuer_count_status!=='CANNOT_CONFIRM'||
          counts.directory_records!==catalog.directory_record_count||
          counts.directory_pages!==catalog.directory_page_count||
          counts.manager_announcements!==articleCount||
          counts.manager_source_identity_associations!==stats.associations||
          counts.distinct_manager_source_codes!==stats.codes.size||
          counts.complete_api_bodies!==kindCounts.COMPLETE_API_BODY||
          counts.long_pdf_focus_reads!==kindCounts.LONG_PDF_KEY_SECTION_READ||
          counts.text_insufficient_unassessed!==kindCounts.TEXT_INSUFFICIENT_UNASSESSED||
          manifest.manager_source_identity_association_count!==stats.associations||
          manifest.distinct_manager_source_code_count!==stats.codes.size||
          manifest.manager_issuer_count!==null||manifest.unknown_issuer_count!==null||
          manifest.issuer_count_status!=='CANNOT_CONFIRM'||
          summary.directory_records!==counts.directory_records||summary.directory_pages!==counts.directory_pages||
          summary.manager_announcements!==articleCount||
          summary.manager_source_identity_associations!==stats.associations||
          summary.distinct_manager_source_codes!==stats.codes.size||
          summary.complete_api_bodies!==kindCounts.COMPLETE_API_BODY||
          summary.long_pdf_focus_reads!==kindCounts.LONG_PDF_KEY_SECTION_READ||
          summary.text_insufficient_unassessed!==kindCounts.TEXT_INSUFFICIENT_UNASSESSED||
          summary.manager_source_identity_association_count!==stats.associations||
          summary.distinct_manager_source_code_count!==stats.codes.size||
          summary.manager_issuer_count!==null||summary.unknown_issuer_count!==null||
          summary.issuer_count_status!=='CANNOT_CONFIRM'||
          !validDynamicInputs(manifest.verified_inputs,manifest,articleCount))
        throw new Error('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
    }
    const codes=new Set<string>(),counts:Record<string,number>={COMPLETE_API_BODY:0,LONG_PDF_KEY_SECTION_READ:0,TEXT_INSUFFICIENT_UNASSESSED:0};
    for(const row of analysis.records){
      if(!object(row)||typeof row.art_code!=='string'||codes.has(row.art_code)||
          !Object.prototype.hasOwnProperty.call(counts,String(row.analysis_kind)))
        throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
      codes.add(row.art_code);counts[String(row.analysis_kind)]++;
    }
    if(legacy&&(counts.COMPLETE_API_BODY!==207||counts.LONG_PDF_KEY_SECTION_READ!==22||
        counts.TEXT_INSUFFICIENT_UNASSESSED!==5))
      throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_COUNTS_INVALID');
  }else if(analysis.summary!==null||!Array.isArray(analysis.records)||analysis.records.length!==0){
    throw new Error('ANNOUNCEMENT_ANALYSIS_MISSING_MUST_NOT_LOOK_COMPLETE');
  }
  if(analysis.status==='VERIFIED'){
    const selection=analysis.stock_selection===undefined?noSelectionAssessment():analysis.stock_selection;
    if(!validStockSelection(selection,analysis,targetDate))
      throw new Error('ANNOUNCEMENT_ANALYSIS_STOCK_SELECTION_INVALID');
    analysis.stock_selection=selection;
  }else{
    const selection=analysis.stock_selection===undefined?noSelectionAssessment():analysis.stock_selection;
    if(!validStockSelection(selection,analysis,targetDate))
      throw new Error('ANNOUNCEMENT_ANALYSIS_STOCK_SELECTION_INVALID');
    analysis.stock_selection=selection;
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
