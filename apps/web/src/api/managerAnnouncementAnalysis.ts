/** Read-only, date-bound projection of reviewed HK announcement analysis. */
export type AnnouncementAnalysisObject = Record<string, unknown>;

export interface ManagerAnnouncementAnalysis extends AnnouncementAnalysisObject {
  schema_version: 'v4.manager_research.eastmoney_hk_announcement_analysis_read.v1';
  target_trade_date: string;
  publication_date: string;
  date_selection_basis: 'EXPLICIT' | 'PREVIOUS_HK_TRADING_SESSION' | 'CURRENT_TARGET_PREVIOUS_CALENDAR_DAY';
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
const hkexDirectoryScope='HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1';
const hkexPdfBody='COMPLETE_HKEX_OFFICIAL_PDF_BODY';
const hkexHosts=new Set(['www1.hkexnews.hk','www.hkexnews.hk','sc.hkexnews.hk']);
function trustedUrl(value:unknown,hosts:Set<string>):boolean{
  if(typeof value!=='string')return false;
  try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&hosts.has(url.hostname);}
  catch{return false;}
}
function recordIdentity(raw:unknown):string|null{
  if(!object(raw))return null;
  if(typeof raw.art_code==='string'&&raw.art_code&&raw.source_variant_id===undefined)
    return `art_code:${raw.art_code}`;
  if(raw.art_code===undefined&&typeof raw.source_variant_id==='string'&&
      /^HKEX:\d{5,20}$/.test(raw.source_variant_id))return `source_variant_id:${raw.source_variant_id}`;
  return null;
}
function sourceCodeStats(records:unknown[]):{associations:number;codes:Set<string>;identities:Set<string>}|null{
  let associations=0;const codes=new Set<string>();
  const identities=new Set<string>();
  for(const raw of records){
    const identity=recordIdentity(raw);
    if(!object(raw)||!identity||identities.has(identity)||!Array.isArray(raw.issuer_codes)||raw.issuer_codes.length===0)return null;
    identities.add(identity);
    const rowCodes:string[]=[];
    for(const item of raw.issuer_codes){
      if(!object(item)||typeof item.code!=='string'||!/^HK\.\d{5}$/.test(item.code))return null;
      if(identity.startsWith('art_code:')&&(item.market_code!=='116'||item.ann_type!=='H'))return null;
      rowCodes.push(item.code);
    }
    if(new Set(rowCodes).size!==rowCodes.length)return null;
    if(identity.startsWith('source_variant_id:')){
      const variantId=raw.source_variant_id as string,listing=object(raw.listing_source)?raw.listing_source:{};
      const directoryRef=object(listing.directory_source_ref)?listing.directory_source_ref:{};
      const bodyRef=object(listing.body_source_ref)?listing.body_source_ref:{};
      if(raw.source!=='HKEX_OFFICIAL'||raw.source_scope!==hkexDirectoryScope||
          raw.news_id!==variantId.slice(5)||rowCodes.length!==1||
          !object(listing)||listing.source_variant_id!==variantId||listing.source_scope!==hkexDirectoryScope||
          listing.news_id!==raw.news_id||listing.symbol!==rowCodes[0]||
          raw.connect_eligibility_status!=='ELIGIBLE'||
          !Array.isArray(raw.matched_connect_codes)||raw.matched_connect_codes.length!==1||
          raw.matched_connect_codes[0]!==rowCodes[0]||!validSha(raw.connect_eligibility_identity_sha256)||
          !validSha(raw.semantic_record_sha256)||!validSha(raw.body_record_sha256)||
          !validSha(listing.directory_raw_body_sha256)||!trustedUrl(directoryRef.url,hkexHosts))return null;
      const pages=Array.isArray(raw.body_page_citations)?raw.body_page_citations:[];
      if(raw.analysis_kind===hkexPdfBody&&(raw.body_status!==hkexPdfBody||raw.selection_status!==undefined||
          !trustedUrl(bodyRef.url,hkexHosts)||
          pages.length===0||pages.some(page=>!object(page)||!object(page.source_ref)||
            !trustedUrl(page.source_ref.url,hkexHosts))))return null;
      if(raw.analysis_kind!==hkexPdfBody&&
          (raw.analysis_kind!=='TEXT_INSUFFICIENT_UNASSESSED'||typeof raw.body_status!=='string'||!raw.body_status||
           raw.body_status===hkexPdfBody||
           raw.selection_status!=='NOT_ASSESSED'))return null;
    }
    associations+=rowCodes.length;rowCodes.forEach(code=>codes.add(code));
  }
  return {associations,codes,identities};
}
function validDynamicInputs(value:unknown,manifest:AnnouncementAnalysisObject,articleCount:number,
                            bodyRowCount=articleCount):boolean{
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
    body.sha256===manifest.body_corpus_sha256&&semantic.row_count===articleCount&&body.row_count===bodyRowCount;
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
  const manifest=object(analysis.source_manifest)?analysis.source_manifest:{};
  const multiSource=Array.isArray(manifest.additional_source_scopes)&&
    manifest.additional_source_scopes.includes(hkexDirectoryScope);
  const counts=object(manifest.counts)?manifest.counts:{};
  const additionalScopes=Array.isArray(manifest.additional_source_scopes)?manifest.additional_source_scopes:[];
  const expectedArticleCount=legacy?234:records.length;
  const expectedEastmoneyCount=multiSource
    ?typeof counts.eligible_eastmoney_announcements==='number'?counts.eligible_eastmoney_announcements:-1
    :records.length;
  const expectedHkexCount=multiSource
    ?typeof counts.hkex_official_announcements==='number'?counts.hkex_official_announcements:-1
    :0;
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
  const binding=value.source_binding;
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
  if(multiSource&&(additionalScopes.length!==1||
      additionalScopes[0]!==hkexDirectoryScope||
      counts.eligible_eastmoney_announcements!==expectedEastmoneyCount||
      counts.hkex_official_announcements!==expectedHkexCount||
      counts.combined_eligible_announcements!==expectedArticleCount||
      expectedEastmoneyCount+expectedHkexCount!==expectedArticleCount||
      binding.hkex_directory_readback_sha256!==manifest.hkex_directory_readback_sha256||
      binding.monthly_connect_eligibility_identity_sha256!==manifest.monthly_connect_eligibility_identity_sha256||
      binding.monthly_connect_source_date!==manifest.monthly_connect_source_date||
      !validSha(binding.additional_source_scopes_sha256)||
      !validSha(binding.hkex_directory_readback_sha256)||
      !validSha(binding.monthly_connect_eligibility_identity_sha256)||
      typeof binding.monthly_connect_source_date!=='string'||!/^\d{8}$/.test(binding.monthly_connect_source_date)))return false;
  if(!Array.isArray(analysis.records)||analysis.records.length!==expectedArticleCount)return false;
  const recordByIdentity=new Map<string,AnnouncementAnalysisObject>();
  for(const rawRecord of analysis.records){
    const identity=recordIdentity(rawRecord);
    if(!object(rawRecord)||!identity||recordByIdentity.has(identity)||!Array.isArray(rawRecord.issuer_codes))return false;
    if(identity.startsWith('source_variant_id:')){
      const sourceManifestVariants=object(manifest.hkex_source_variant_sha256s)?manifest.hkex_source_variant_sha256s:{};
      if(!multiSource||rawRecord.analysis_kind!==hkexPdfBody&&rawRecord.analysis_kind!=='TEXT_INSUFFICIENT_UNASSESSED'||
          rawRecord.body_record_sha256!==sourceManifestVariants[rawRecord.source_variant_id as string]||
          rawRecord.selection_status!==(rawRecord.analysis_kind===hkexPdfBody?undefined:'NOT_ASSESSED'))return false;
    }
    recordByIdentity.set(identity,rawRecord);
  }
  const decisionByIdentity=new Map<string,AnnouncementAnalysisObject>();
  for(const rawDecision of value.article_decisions){
    const identity=recordIdentity(rawDecision);
    if(!object(rawDecision)||!identity||decisionByIdentity.has(identity)||
        !Array.isArray(rawDecision.issuer_codes)||rawDecision.issuer_codes.length===0||
        rawDecision.issuer_codes.some(code=>typeof code!=='string'||!code)||
        !validSha(rawDecision.semantic_record_sha256)||!validSha(rawDecision.body_record_sha256)||
        !dispositions.has(String(rawDecision.disposition))||
        typeof rawDecision.reason!=='string'||!rawDecision.reason.trim()||!Array.isArray(rawDecision.risk_notes)||
        rawDecision.risk_notes.some(note=>typeof note!=='string'||!note.trim()))return false;
    const sourceRecord=recordByIdentity.get(identity);
    if(!sourceRecord||!Array.isArray(sourceRecord.issuer_codes)||
        !validSha(sourceRecord.semantic_record_sha256)||!validSha(sourceRecord.body_record_sha256)||
        rawDecision.semantic_record_sha256!==sourceRecord.semantic_record_sha256||
        rawDecision.body_record_sha256!==sourceRecord.body_record_sha256||
        JSON.stringify(rawDecision.issuer_codes)!==JSON.stringify(sourceRecord.issuer_codes.map((issuer:unknown)=>
          object(issuer)?issuer.code:undefined)))return false;
    decisionByIdentity.set(identity,rawDecision);
  }
  if(decisionByIdentity.size!==recordByIdentity.size)return false;
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
      const identity=recordIdentity(article);
      if(!object(article)||!identity)return false;
      const decision=decisionByIdentity.get(identity),sourceRecord=recordByIdentity.get(identity);
      if(!decision||!Array.isArray(decision.issuer_codes)||!decision.issuer_codes.includes(rawStock.stock_code)||
          article.disposition!==decision.disposition||article.reason!==decision.reason||
          !sourceRecord||article.source_sha256!==sourceRecord.semantic_record_sha256||
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
      !['EXPLICIT','PREVIOUS_HK_TRADING_SESSION','CURRENT_TARGET_PREVIOUS_CALENDAR_DAY'].includes(String(raw.date_selection_basis))||
      !object(raw.source_catalog)||!object(raw.analysis))
    throw new Error('ANNOUNCEMENT_ANALYSIS_RESPONSE_IDENTITY_INVALID');
  const publicationToken=raw.publication_date.replaceAll('-','');
  const targetUtc=new Date(Date.UTC(Number(targetDate.slice(0,4)),Number(targetDate.slice(4,6))-1,
    Number(targetDate.slice(6,8))));
  targetUtc.setUTCDate(targetUtc.getUTCDate()-1);
  const previousCalendarDay=`${targetUtc.getUTCFullYear()}${String(targetUtc.getUTCMonth()+1).padStart(2,'0')}${String(targetUtc.getUTCDate()).padStart(2,'0')}`;
  if(!validDate(publicationToken)||(requestedPublicationDate&&publicationToken!==requestedPublicationDate)||
      (requestedPublicationDate&&raw.date_selection_basis!=='EXPLICIT')||
      (raw.date_selection_basis==='CURRENT_TARGET_PREVIOUS_CALENDAR_DAY'&&publicationToken!==previousCalendarDay)||
      (!requestedPublicationDate&&!['PREVIOUS_HK_TRADING_SESSION','CURRENT_TARGET_PREVIOUS_CALENDAR_DAY'].includes(String(raw.date_selection_basis))))
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
      const multiSource=Array.isArray(manifest.additional_source_scopes)&&
        manifest.additional_source_scopes.includes(hkexDirectoryScope);
      const additionalScopes=Array.isArray(manifest.additional_source_scopes)?manifest.additional_source_scopes:[];
      const kindCounts:Record<string,number>={COMPLETE_API_BODY:0,LONG_PDF_KEY_SECTION_READ:0,
        TEXT_INSUFFICIENT_UNASSESSED:0,[hkexPdfBody]:0};
      const identities=new Set<string>(),hkexStatuses:Record<string,number>={};
      for(const row of analysis.records){
        const identity=recordIdentity(row);
        if(!object(row)||!identity||identities.has(identity))throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
        identities.add(identity);
        if(!Object.prototype.hasOwnProperty.call(kindCounts,String(row.analysis_kind)))
          throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
        kindCounts[String(row.analysis_kind)]++;
        if(identity.startsWith('source_variant_id:')){
          const listing=object(row.listing_source)?row.listing_source:{};
          if(!multiSource||listing.publication_date!==raw.publication_date)
            throw new Error('ANNOUNCEMENT_ANALYSIS_HKEX_PUBLICATION_DATE_MISMATCH');
          const bodyStatus=String(row.body_status||'UNKNOWN');
          hkexStatuses[bodyStatus]=(hkexStatuses[bodyStatus]||0)+1;
        }else if(!['COMPLETE_API_BODY','LONG_PDF_KEY_SECTION_READ','TEXT_INSUFFICIENT_UNASSESSED'].includes(String(row.analysis_kind)))
          throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
      }
      const articleCount=analysis.records.length;
      const eastmoneyCount=multiSource
        ?typeof counts.eligible_eastmoney_announcements==='number'?counts.eligible_eastmoney_announcements:-1
        :articleCount;
      const hkexCount=multiSource
        ?typeof counts.hkex_official_announcements==='number'?counts.hkex_official_announcements:-1
        :0;
      const rawManagerCount=typeof catalog.manager_announcement_count==='number'?catalog.manager_announcement_count:-1;
      const sourceAssociations=manifest.manager_source_identity_association_count;
      const sourceCodeCount=manifest.distinct_manager_source_code_count;
      const hkexSha=object(manifest.hkex_source_variant_sha256s)?manifest.hkex_source_variant_sha256s:{};
      const bodyStatusCounts=object(manifest.hkex_body_status_counts)?manifest.hkex_body_status_counts:{};
      const runIds=manifest.hkex_directory_run_ids;
      const unresolved=typeof manifest.hkex_unresolved_document_count==='number'?manifest.hkex_unresolved_document_count:-1;
      const directoryCount=typeof manifest.hkex_directory_document_count==='number'?manifest.hkex_directory_document_count:-1;
      const excluded=typeof manifest.hkex_excluded_document_count==='number'?manifest.hkex_excluded_document_count:-1;
      const expectedHkexCoverage=hkexCount===0?(unresolved>0?'UNASSESSED_SOURCE_IDENTITY_GAPS':'NO_ELIGIBLE_DOCUMENTS'):
        (kindCounts[hkexPdfBody]===hkexCount&&unresolved===0?'COMPLETE':'PARTIAL');
      if(!stats||(articleCount<1&&!multiSource)||
          manifest.source_scope!=='EASTMONEY_HK_DATE_CATALOG'||
          !numeric(catalog.directory_record_count)||!numeric(catalog.directory_page_count)||
          !numeric(rawManagerCount)||eastmoneyCount>rawManagerCount||
          (!multiSource&&rawManagerCount!==articleCount)||
          catalog.manager_source_identity_association_count!==sourceAssociations||
          catalog.distinct_manager_source_code_count!==sourceCodeCount||
          catalog.manager_issuer_count!==null||catalog.unknown_issuer_count!==null||
          catalog.issuer_count_status!=='CANNOT_CONFIRM'||
          counts.directory_records!==catalog.directory_record_count||
          counts.directory_pages!==catalog.directory_page_count||
          counts.manager_announcements!==articleCount||
          counts.manager_source_identity_associations!==sourceAssociations||
          counts.distinct_manager_source_codes!==sourceCodeCount||
          counts.complete_api_bodies!==kindCounts.COMPLETE_API_BODY||
          counts.long_pdf_focus_reads!==kindCounts.LONG_PDF_KEY_SECTION_READ||
          counts.text_insufficient_unassessed!==kindCounts.TEXT_INSUFFICIENT_UNASSESSED||
          manifest.manager_source_identity_association_count!==catalog.manager_source_identity_association_count||
          manifest.distinct_manager_source_code_count!==catalog.distinct_manager_source_code_count||
          manifest.manager_issuer_count!==null||manifest.unknown_issuer_count!==null||
          manifest.issuer_count_status!=='CANNOT_CONFIRM'||
          summary.directory_records!==counts.directory_records||summary.directory_pages!==counts.directory_pages||
          summary.manager_announcements!==articleCount||
          summary.manager_source_identity_associations!==sourceAssociations||
          summary.distinct_manager_source_codes!==sourceCodeCount||
          summary.complete_api_bodies!==kindCounts.COMPLETE_API_BODY||
          summary.long_pdf_focus_reads!==kindCounts.LONG_PDF_KEY_SECTION_READ||
          summary.text_insufficient_unassessed!==kindCounts.TEXT_INSUFFICIENT_UNASSESSED||
          (multiSource&&(summary.eligible_eastmoney_announcements!==eastmoneyCount||
            summary.complete_hkex_pdf_bodies!==kindCounts[hkexPdfBody]))||
          summary.manager_source_identity_association_count!==sourceAssociations||
          summary.distinct_manager_source_code_count!==sourceCodeCount||
          summary.manager_issuer_count!==null||summary.unknown_issuer_count!==null||
          summary.issuer_count_status!=='CANNOT_CONFIRM'||
          (multiSource&&(additionalScopes.length!==1||
            additionalScopes[0]!==hkexDirectoryScope||
            counts.eligible_eastmoney_announcements!==eastmoneyCount||
            counts.hkex_official_announcements!==hkexCount||
            counts.combined_eligible_announcements!==articleCount||eastmoneyCount+hkexCount!==articleCount||
            counts.complete_hkex_pdf_bodies!==kindCounts[hkexPdfBody]||
            !validSha(manifest.hkex_directory_readback_sha256)||!validSha(manifest.monthly_connect_eligibility_identity_sha256)||
            typeof manifest.monthly_connect_source_date!=='string'||!/^\d{8}$/.test(manifest.monthly_connect_source_date)||
            manifest.monthly_connect_source_date.slice(0,6)!==publicationToken.slice(0,6)||
            manifest.connect_eligibility_status!=='VERIFIED_MONTHLY_SNAPSHOT'||
            !numeric(directoryCount)||!numeric(excluded)||!numeric(unresolved)||
            directoryCount!==hkexCount+excluded+unresolved||
            manifest.hkex_eligible_document_count!==hkexCount||manifest.hkex_source_variant_count!==hkexCount||
            manifest.hkex_unresolved_source_identity_gap!==(unresolved>0)||
            manifest.hkex_body_coverage_status!==expectedHkexCoverage||
            !Array.isArray(runIds)||runIds.length===0||runIds.some(runId=>typeof runId!=='string'||!/^[0-9a-f]{32}$/.test(runId))||
            Object.keys(hkexSha).length!==hkexCount||Object.keys(bodyStatusCounts).length!==Object.keys(hkexStatuses).length||
            Object.entries(hkexStatuses).some(([status,count])=>bodyStatusCounts[status]!==count)||
            Object.entries(bodyStatusCounts).some(([status,count])=>hkexStatuses[status]!==count)||
            [...identities].filter(key=>key.startsWith('source_variant_id:')).some(key=>
              hkexSha[key.slice('source_variant_id:'.length)]!==
                (analysis.records as AnnouncementAnalysisObject[]).find(row=>recordIdentity(row)===key)?.body_record_sha256)))||
          !validDynamicInputs(manifest.verified_inputs,manifest,articleCount,eastmoneyCount))
        throw new Error('ANNOUNCEMENT_ANALYSIS_VERIFIED_PAYLOAD_INVALID');
    }
    const counts:Record<string,number>={COMPLETE_API_BODY:0,LONG_PDF_KEY_SECTION_READ:0,
      TEXT_INSUFFICIENT_UNASSESSED:0,[hkexPdfBody]:0};
    const identities=new Set<string>();
    for(const row of analysis.records){
      const identity=recordIdentity(row);
      if(!object(row)||!identity||identities.has(identity)||
          !Object.prototype.hasOwnProperty.call(counts,String(row.analysis_kind)))
        throw new Error('ANNOUNCEMENT_ANALYSIS_RECORD_SET_INVALID');
      identities.add(identity);counts[String(row.analysis_kind)]++;
    }
    if(legacy&&(counts.COMPLETE_API_BODY!==207||counts.LONG_PDF_KEY_SECTION_READ!==22||
        counts.TEXT_INSUFFICIENT_UNASSESSED!==5)||
       !legacy&&object(analysis.source_manifest)&&
        counts[hkexPdfBody]!==((object(analysis.source_manifest.counts)?analysis.source_manifest.counts.complete_hkex_pdf_bodies:0)||0))
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
