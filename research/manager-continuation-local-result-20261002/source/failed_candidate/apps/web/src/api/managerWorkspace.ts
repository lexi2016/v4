/** Read-only stock summary, not a ranking / BUY / trading instruction contract. */
export type JsonObject = Record<string, unknown>;
export interface WorkspaceLane extends JsonObject {
  lane: 'STAGE' | 'CATALYST' | 'CLOSE'; owner: string; state: string; target_date: string;
  stock_count: number | null; last_attempt_at: string | null; last_success_at: string | null;
  run_id: string | null; execution_kind: string; failure_reasons: string[];
  next_plan: JsonObject | null; schedule_status: string; input_coverage: JsonObject;
}
export interface WorkspaceAction extends JsonObject {
  action_id: string; type: string; text: string; evidence_ids: string[];
  proposition_ids: string[]; supporting_quotes: JsonObject[]; assertion_type: string;
}
export interface WorkspaceStock extends JsonObject {
  is_focus: boolean; priority_basis: JsonObject;
  stock_key: string; market: 'HK'; symbol: string; name: string; target_date: string;
  lanes: string[]; themes: string[]; why_watch: string[]; attention_priority: string;
  event_group_count: number; new_catalyst_count: number; evidence: JsonObject[]; material_relations: JsonObject[];
  stage_observation: JsonObject | null; close_observation: JsonObject | null;
  change: {status: string; previous_date: string | null; reasons: string[]};
  plan: {next_observation: string[]; invalidation_conditions: string[]; missing: string[];
         trigger_price: number | null; invalidation_price: number | null;
         price_provenance?: JsonObject | null; key_risks?: string[]; wait_conditions?: string[];
         evidence_ids?: string[]; criteria?: JsonObject; actions: WorkspaceAction[]};
}
export interface ReboundScreen extends JsonObject {
  schema_version: 'v4.manager_research.rebound_v3_screen.v1'; rule_version: string;
  target_trade_date: string; verified_session: string; status: 'READY' | 'READY_WITH_GAPS' | 'CANNOT_CONFIRM';
  cards: JsonObject[]; strict: JsonObject[]; near: JsonObject[]; pending: JsonObject[];
  gaps: string[]; coverage: JsonObject; input_identity: string | null; authority: JsonObject | null;
  main_screen_ready: boolean; longlist_target?: number;
}
export interface UsMarketAttention extends JsonObject {
  schema_version: 'v4.manager_research.us_market_bridge.v1'; target_trade_date: string;
  research_cutoff: string; status: string; expected_us_session: string | null;
  coverage_scope: string; selection_semantics?: string; selection_threshold_pct?: number; raw_industry_up: JsonObject[]; raw_individual_up: JsonObject[];
  coverage: JsonObject; source_identity: JsonObject | null; gaps: string[];
}
export type ResearchAttentionState =
  | 'COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION'
  | 'COMPANY_EVIDENCE_WAIT_MARKET'
  | 'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE'
  | 'CONTEXT_ONLY'
  | 'INSUFFICIENT';
export interface ResearchAttentionDecision extends JsonObject {
  schema_version: 'v4.manager_research.attention_decision.v1';
  version: '20260927.evidence-state-triage.proposal-v1';
  status: 'PROPOSAL_ONLY'; state: ResearchAttentionState; group_label: string; group_order: number;
  summary: string; next_check: string; invalidation: string; why_now_readable: string[];
  company_evidence_strength: number; market_confirmation_strength: number; context_strength: number;
  research_priority_key: [number, number, number, number, number, number];
  formal_rank_writeback: false; stage_writeback: false; buy_gate_writeback: false;
}
export interface ResearchAttentionCard extends JsonObject {
  symbol: string; name: string; research_attention_score: number; research_attention_band: string;
  qualified_lane_count: number; qualified_lanes: string[]; why_now: string[]; score_components?: JsonObject[]; missing: string[];
  screen_classification: string | null; original_screen_rank: number | null; evidence: JsonObject[];
  decision?: ResearchAttentionDecision; freshest_published_at?: string | null; freshest_acquired_at?: string | null;
}
export interface ResearchAttention extends JsonObject {
  schema_version: 'v4.manager_research.research_attention.v1'; target_trade_date: string;
  research_cutoff: string; status: string; priority_name: string; config: JsonObject;
  cards: ResearchAttentionCard[]; coverage: JsonObject; gaps: string[]; input_identity: string; ordering_basis?: string;
}
export interface ManagerWorkspace extends JsonObject {
  semantic_version: '20260921.manager-semantic.r3.v1'; focus_symbols: string[];
  briefing: JsonObject; company_events: JsonObject[]; rejected_relations: JsonObject[];
  schema_version: 'v4.manager_research.workspace.v1'; target_trade_date: string;
  input_identity: string; stocks: WorkspaceStock[]; lanes: WorkspaceLane[];
  themes: JsonObject[]; materials: JsonObject[]; gaps: string[];
  summary: {stock_count: number; relation_count: number; theme_count: number; reused_material_count: number; formal_recommendation_count: 0};
  market_screen?: ReboundScreen; market_screen_evidence?: JsonObject;
  us_market_attention?: UsMarketAttention; research_attention?: ResearchAttention;
}
function object(value: unknown): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('WORKSPACE_OBJECT_INVALID');
  return value as JsonObject;
}
function safe(row: JsonObject): void {
  if (row.RESEARCH_ONLY !== true || row.production_allowed !== false || row.buy_gate_updated !== false || row.orders_sent !== false)
    throw new Error('WORKSPACE_SAFETY_INVALID');
}
function strings(value: unknown): asserts value is string[] {
  if (!Array.isArray(value) || value.some(v => typeof v !== 'string')) throw new Error('WORKSPACE_TEXT_LIST_INVALID');
}
function records(value: unknown): asserts value is JsonObject[] {
  if (!Array.isArray(value)) throw new Error('WORKSPACE_RECORDS_INVALID');
  value.forEach(object);
}
function count(value: unknown): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('WORKSPACE_COUNT_INVALID');
}
/** Every rendered action must reference the SAME retained issuer proposition.
 * Theme inference needs both theme and issuer support. Market levels keep their
 * existing strict provenance gate; this is not an alternate quote validator.
 */
function validateActions(stock: JsonObject, value: JsonObject): void {
  const plan=object(stock.plan); records(plan.actions); records(stock.evidence);
  const props: JsonObject[]=[];
  for(const e of stock.evidence){
    if(e.semantic_version!=='20260921.manager-semantic.r3.v1' || e.semantic_status!=='ACCEPTED')
      throw new Error('WORKSPACE_EVIDENCE_SEMANTIC_INVALID');
    records(e.propositions); props.push(...e.propositions);
  }
  const themeProps: JsonObject[]=[];records(value.themes);
  for(const t of value.themes){records(t.evidence);themeProps.push(...t.evidence);}
  const matches=(q:JsonObject,p:JsonObject)=>['evidence_id','proposition_id','quote','source_field','start','end'].every(k=>q[k]===p[k]);
  const texts=new Set<string>(); const ids=new Set<string>();
  for(const a of plan.actions){
    if(typeof a.action_id!=='string' || ids.has(a.action_id) || !['WATCH','WAIT','NO_CHASE','INVALIDATE'].includes(String(a.type)) ||
       typeof a.text!=='string' || !a.text || a.orders_sent!==false)throw new Error('WORKSPACE_ACTION_INVALID');
    ids.add(a.action_id);texts.add(a.text);strings(a.evidence_ids);strings(a.proposition_ids);records(a.supporting_quotes);
    if(!a.evidence_ids.length || !a.proposition_ids.length || !a.supporting_quotes.length)throw new Error('WORKSPACE_ACTION_UNBOUND');
    let issuer=false,theme=false;
    for(const q of a.supporting_quotes){
      if(typeof q.evidence_id!=='string' || !a.evidence_ids.includes(q.evidence_id) ||
         typeof q.proposition_id!=='string' || !a.proposition_ids.includes(q.proposition_id) ||
         typeof q.quote!=='string' || !q.quote || !Number.isInteger(q.start) || !Number.isInteger(q.end) ||
         Number(q.start)<0 || Number(q.end)<=Number(q.start))throw new Error('WORKSPACE_ACTION_SUPPORT_INVALID');
      if(q.support_kind==='THEME_PROPOSITION'){
        if(q.symbol!==null || a.assertion_type!=='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT' || !themeProps.some(p=>matches(q,p)))
          throw new Error('WORKSPACE_ACTION_THEME_UNBOUND');
        theme=true;
      }else if(q.support_kind==='VERIFIED_MARKET_FIELDS'){
        const provenance=object(plan.price_provenance);const inputs=object(provenance.inputs);
        const quoted=object(JSON.parse(q.quote));records(q.source_refs);records(provenance.source_refs);const priceRefs=provenance.source_refs;
        if(q.symbol!==stock.symbol || quoted.symbol!==stock.symbol || quoted.session_date!==provenance.session_date ||
           quoted.close!==inputs.close || quoted.low!==inputs.low || q.source_field!=='verified_market_fields' ||
           q.source_refs.length===0 || q.source_refs.some(r=>!priceRefs.some(p=>p.payload_sha256===r.payload_sha256)))
          throw new Error('WORKSPACE_ACTION_MARKET_UNBOUND');
        issuer=true;
      }else{
        if(q.symbol!==stock.symbol || !props.some(p=>p.symbol===stock.symbol && matches(q,p)))
          throw new Error('WORKSPACE_ACTION_ISSUER_UNBOUND');
        issuer=true;
      }
    }
    if(!issuer || (a.assertion_type==='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT' && !theme))
      throw new Error('WORKSPACE_ACTION_INFERENCE_INCOMPLETE');
  }
  for(const key of ['next_observation','wait_conditions','key_risks','invalidation_conditions']){
    strings(plan[key]);if(plan[key].some(t=>!texts.has(t)))throw new Error('WORKSPACE_ACTION_VISIBLE_TEXT_UNBOUND');
  }
}
export type WorkspaceView = 'auto' | 'historical' | 'dynamic';
/** Read context is a separate time/admission contract, never a cache trust flag. */
function validateReadContext(value: JsonObject): void {
  if (value.read_context === undefined) return; // legacy POST/caller compatibility, not GET admission
  const read = object(value.read_context); const ctx = object(value.plan_context);
  const status = String(read.status); const historical = read.mode === 'HISTORICAL_AS_OF';
  if (!['HISTORICAL_AS_OF','CURRENT_DYNAMIC_PREVIEW'].includes(String(read.mode)) ||
      !['VERIFIED','VERIFIED_WITH_GAPS','NOT_MATERIALIZED','SOURCE_FAILED'].includes(status) ||
      read.contract !== '20260923.workspace-history-read.r1' || typeof read.candidate_count_known !== 'boolean' ||
      typeof read.as_of !== 'string' || read.as_of !== ctx.research_cutoff ||
      ctx.plan_trade_date !== value.target_trade_date || !Number.isFinite(Date.parse(read.as_of)))
    throw new Error('WORKSPACE_READ_CONTEXT_INVALID');
  const stocks=value.stocks as JsonObject[];
  if (['NOT_MATERIALIZED','SOURCE_FAILED'].includes(status)) {
    if (stocks.length || read.candidate_count_known !== false || object(value.plan_product).consumed !== false)
      throw new Error('WORKSPACE_UNAVAILABLE_NOT_EMPTY_SUCCESS');
    return;
  }
  if (!historical) return;
  const product=object(value.plan_product); const cutoff=Date.parse(read.as_of);
  if (product.status !== 'CURRENT' || product.consumed !== true)
    throw new Error('WORKSPACE_HISTORY_PLAN_NOT_CONSUMED');
  const known=(raw:unknown)=>typeof raw==='string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(raw) &&
    Number.isFinite(Date.parse(raw)) && Date.parse(raw)<=cutoff;
  for (const material of value.materials as JsonObject[])
    if (!['published_at','available_at','retrieved_at'].every(k=>known(material[k])))
      throw new Error('WORKSPACE_HISTORY_MATERIAL_PIT_INVALID');
  for (const stock of stocks) {
    for (const e of stock.evidence as JsonObject[])
      if (!known(e.published_at) || !known(e.retrieved_at) || (e.available_at!=null && !known(e.available_at)))
        throw new Error('WORKSPACE_HISTORY_EVIDENCE_PIT_INVALID');
    for (const key of ['stage_observation','close_observation']) {
      if (stock[key]!=null) {
        const observation=object(stock[key]);
        if (!known(observation.available_at || observation.captured_at)) throw new Error('WORKSPACE_HISTORY_OBSERVATION_PIT_INVALID');
      }
    }
  }
}
export interface AnnouncementObservation extends JsonObject {
  schema_version: 'v4.manager_research.announcement_observation.v1'; target_trade_date: string;
  research_cutoff: string; prior_session: string; status: string; count_known: boolean;
  latest_attempt: JsonObject | null; observations: JsonObject[]; pending_observations: JsonObject[];
  official_documents: JsonObject[]; coverage: JsonObject; gaps: string[]; capture_runs: JsonObject[];
  eastmoney_hk_status?: string; eastmoney_hk_documents?: JsonObject[];
  eastmoney_hk_capture?: JsonObject | null; eastmoney_hk_attempt?: JsonObject | null; eastmoney_hk_gaps?: string[];
}
function announcementTime(raw: unknown): number {
  if(typeof raw!=='string' || !/(Z|[+-]\d{2}:\d{2})$/.test(raw) || !Number.isFinite(Date.parse(raw)))
    throw new Error('ANNOUNCEMENT_EXPLICIT_TIME_REQUIRED');
  return Date.parse(raw);
}
function officialUrl(raw: unknown): void {
  if(typeof raw!=='string')throw new Error('ANNOUNCEMENT_SOURCE_URL_INVALID');
  const u=new URL(raw);
  if(u.protocol!=='https:' || u.username || u.password ||
      !(u.hostname==='hkexnews.hk' || u.hostname.endsWith('.hkexnews.hk') ||
        u.hostname==='hkex.com.hk' || u.hostname.endsWith('.hkex.com.hk')))
    throw new Error('ANNOUNCEMENT_SOURCE_URL_INVALID');
}
function eastmoneyUrl(raw: unknown, kind: 'list' | 'content' | 'pdf'): void {
  if(typeof raw!=='string')throw new Error('EASTMONEY_HK_SOURCE_URL_INVALID');
  const u=new URL(raw);
  const validHost=kind==='list'?u.hostname==='np-anotice-stock.eastmoney.com':
    kind==='content'?u.hostname==='np-cnotice-stock.eastmoney.com':u.hostname==='pdf.dfcfw.com';
  const validPath=kind==='list'?u.pathname==='/api/security/ann':
    kind==='content'?u.pathname==='/api/content/ann':/^\/pdf\/H2_AN[A-Z0-9]{8,32}_1\.pdf$/.test(u.pathname);
  if(u.protocol!=='https:'||u.username||u.password||!validHost||!validPath)
    throw new Error('EASTMONEY_HK_SOURCE_URL_INVALID');
}
function validateEastmoneyDocuments(eastmoneyDocs: JsonObject[], date: string, cutoff: number): void {
  const eastIds=new Set<string>();
  for(const doc of eastmoneyDocs){
    safe(doc);
    const stock=String(doc.stock_code||'');
    if(doc.schema_version!=='v4.manager_research.eastmoney_hk_document.v2'||doc.source!=='EASTMONEY_HK'||
        doc.source_identity!=='EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL'||doc.market_code!=='116'||!/^\d{5}$/.test(stock)||
        doc.symbol!=='HK.'+stock||!/^AN[A-Z0-9]{8,32}$/.test(String(doc.art_code||''))||
        !/^[0-9a-f]{64}$/.test(String(doc.event_id))||eastIds.has(String(doc.event_id))||
        typeof doc.title!=='string'||!doc.title||doc.target_trade_date!==date||
        typeof doc.notice_date!=='string'||!/^\d{4}-\d{2}-\d{2} 00:00:00$/.test(doc.notice_date)||
        typeof doc.display_time!=='string'||!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3}$/.test(doc.display_time)||
        Object.prototype.hasOwnProperty.call(doc,'published_at')||doc.publication_status!=='CANNOT_CONFIRM_FIRST_PUBLICATION'||
        doc.hkex_first_publication_verified!==false||doc.fresh_catalyst_eligible!==false||
        doc.focus_eligible!==false||doc.buy_allowed!==false||doc.full_pdf_stored!==true||
        doc.body_status!=='FULL_CONTENT_API_TEXT_VERIFIED'||doc.body_source!=='EASTMONEY_CONTENT_API_PAGES'||
        doc.pdf_text_extraction_status!=='UNVERIFIED_ENCODING'||typeof doc.body_text!=='string'||!doc.body_text.trim()||
        !/^[0-9a-f]{64}$/.test(String(doc.body_sha256)))
      throw new Error('EASTMONEY_HK_DOCUMENT_IDENTITY_INVALID');
    eastIds.add(String(doc.event_id));
    const available=announcementTime(doc.available_at);announcementTime(doc.retrieved_at);
    const displayed=announcementTime(doc.display_time_iso);
    if(available>cutoff||displayed>cutoff||doc.retrieved_at!==doc.available_at)
      throw new Error('EASTMONEY_HK_DOCUMENT_TIME_INVALID');
    eastmoneyUrl(doc.source_url,'pdf');eastmoneyUrl(doc.content_url,'content');
    if(!/^[0-9a-f]{64}$/.test(String(doc.document_sha256))||
        !Number.isSafeInteger(doc.pdf_bytes)||Number(doc.pdf_bytes)<1||
        !Number.isSafeInteger(doc.pdf_page_count)||Number(doc.pdf_page_count)<1)
      throw new Error('EASTMONEY_HK_FULL_PDF_INVALID');
    const pageCount=doc.content_page_count;
    const bodyPages=doc.body_pages;
    if(!Number.isSafeInteger(pageCount)||Number(pageCount)<1||Number(pageCount)>20||
        !Array.isArray(bodyPages)||bodyPages.length!==pageCount||!Array.isArray(doc.source_refs)||
        doc.source_refs.length!==pageCount+2)
      throw new Error('EASTMONEY_HK_CONTENT_PAGES_INVALID');
    let bodyCharacters=0;const pageTexts:string[]=[];
    for(let index=0;index<bodyPages.length;index++){
      const page=object(bodyPages[index]);
      const ref=object(doc.source_refs[index+1]);
      const pageRef=object(page.source_ref);
      const refRequest=object(ref.request),pageRequest=object(pageRef.request);
      if(page.page_index!==index+1||typeof page.text!=='string'||!page.text.trim()||
          !/^[0-9a-f]{64}$/.test(String(page.text_sha256))||
          pageRef.source_key!==ref.source_key||pageRef.blob_sha256!==ref.blob_sha256||
          pageRef.body_sha256!==ref.body_sha256||pageRequest.url!==refRequest.url||
          (index===0&&pageRequest.url!==doc.content_url))
        throw new Error('EASTMONEY_HK_CONTENT_PAGE_LOCATOR_INVALID');
      const contentRequest=new URL(String(refRequest.url));
      if(contentRequest.searchParams.get('art_code')!==doc.art_code||
          contentRequest.searchParams.get('page_index')!==String(index+1))
        throw new Error('EASTMONEY_HK_CONTENT_PAGE_REQUEST_INVALID');
      bodyCharacters+=page.text.length;pageTexts.push(page.text);
    }
    if(bodyCharacters>120000||pageTexts.join('\n\n')!==doc.body_text)
      throw new Error('EASTMONEY_HK_CONTENT_BODY_INVALID');
    records(doc.source_refs);
    if(doc.source_refs.length!==Number(pageCount)+2||!doc.source_refs.some(ref=>{
      const request=object(ref.request);return ref.body_sha256===doc.document_sha256&&request.url===doc.source_url;
    }))
      throw new Error('EASTMONEY_HK_PDF_RAW_REFERENCE_MISSING');
    for(const ref of doc.source_refs){
      const request=object(ref.request);
      // The persisted MaterialStore raw-reference contract carries source_key,
      // request and body/blob hashes; it does not carry a normalized `source`
      // label. Origin is established by the strict Eastmoney host/path check
      // below, while a present source label must still agree.
      if((ref.source!==undefined&&ref.source!=='EASTMONEY_HK')||request.method!=='GET'||
          !/^[0-9a-f]{64}$/.test(String(ref.blob_sha256))||!/^[0-9a-f]{64}$/.test(String(ref.body_sha256))||
          announcementTime(ref.retrieved_at)>cutoff)throw new Error('EASTMONEY_HK_RAW_REFERENCE_INVALID');
      const host=new URL(String(request.url)).hostname;
      eastmoneyUrl(request.url,host==='np-anotice-stock.eastmoney.com'?'list':
        host==='np-cnotice-stock.eastmoney.com'?'content':'pdf');
    }
    const listUrl=new URL(String(object(doc.source_refs[0].request).url));
    const contentUrl=new URL(String(object(doc.source_refs[1].request).url));
    const pdfRef=object(doc.source_refs[Number(pageCount)+1]);
    if(listUrl.searchParams.get('stock_list')!==stock||listUrl.searchParams.get('ann_type')!=='H'||
        listUrl.searchParams.get('page_index')!=='1'||contentUrl.searchParams.get('art_code')!==doc.art_code||
        contentUrl.searchParams.get('page_index')!=='1'||object(pdfRef.request).url!==doc.source_url)
      throw new Error('EASTMONEY_HK_REQUEST_SCOPE_INVALID');
  }
}

export function validateAnnouncementObservation(raw: unknown, date: string): AnnouncementObservation {
  const value=object(raw);safe(value);
  if(value.schema_version!=='v4.manager_research.announcement_observation.v1' || value.target_trade_date!==date ||
      value.independent_of_strict_near_focus!==true || typeof value.count_known!=='boolean' ||
      !/^\d{8}$/.test(String(value.prior_session)) || String(value.prior_session)>=date ||
      !['NOT_RUN','RUNNING','FAILED','READBACK_FAILED','PARTIAL','SUCCEEDED','SUCCEEDED_EMPTY'].includes(String(value.status)))
    throw new Error('ANNOUNCEMENT_LANE_IDENTITY_INVALID');
  const cutoff=announcementTime(value.research_cutoff);
  records(value.observations);records(value.pending_observations);records(value.official_documents);records(value.capture_runs);
  const eastmoneyDocs=value.eastmoney_hk_documents===undefined?[]:value.eastmoney_hk_documents;
  records(eastmoneyDocs);
  if(value.eastmoney_hk_gaps!==undefined)strings(value.eastmoney_hk_gaps);
  if(value.eastmoney_hk_status!==undefined && !['NOT_RUN','RUNNING','FAILED','READBACK_FAILED','PARTIAL'].includes(String(value.eastmoney_hk_status)))
    throw new Error('EASTMONEY_HK_STATUS_INVALID');
  object(value.coverage);strings(value.gaps);
  if(['NOT_RUN','READBACK_FAILED'].includes(String(value.status)) && (value.count_known || value.official_documents.length || value.observations.length))
    throw new Error('ANNOUNCEMENT_UNKNOWN_MASQUERADING_AS_KNOWN');
  const ids=new Set<string>();
  for(const doc of value.official_documents){
    safe(doc);
    if(!/^HK\.\d{5}$/.test(String(doc.symbol)) || !/^[0-9a-f]{64}$/.test(String(doc.event_id)) ||
        ids.has(String(doc.event_id)) || typeof doc.title!=='string' || !doc.title)
      throw new Error('ANNOUNCEMENT_DOCUMENT_IDENTITY_INVALID');
    ids.add(String(doc.event_id));officialUrl(doc.source_url);
    const p=announcementTime(doc.published_at),r=announcementTime(doc.retrieved_at),a=announcementTime(doc.available_at);
    if(p>cutoff || r>cutoff || a>cutoff || p>r || p>a)throw new Error('ANNOUNCEMENT_DOCUMENT_TIME_INVALID');
    if(!['FAILED','BODY_PARSED','BODY_UNREADABLE','BODY_UNREAD'].includes(String(doc.body_status)))throw new Error('ANNOUNCEMENT_BODY_STATUS_INVALID');
    records(doc.source_refs);if(!doc.source_refs.length)throw new Error('ANNOUNCEMENT_RAW_REFERENCE_MISSING');
    for(const ref of doc.source_refs){
      if(!/^[0-9a-f]{64}$/.test(String(ref.blob_sha256)) || !/^[0-9a-f]{64}$/.test(String(ref.body_sha256)) ||
          typeof ref.source_key!=='string')throw new Error('ANNOUNCEMENT_RAW_REFERENCE_INVALID');
      officialUrl(object(ref.request).url);
      if(announcementTime(ref.retrieved_at)>cutoff)throw new Error('ANNOUNCEMENT_RAW_AFTER_CUTOFF');
    }
    if(doc.body_status==='BODY_PARSED' && (!/^[0-9a-f]{64}$/.test(String(doc.document_sha256)) ||
        !doc.source_refs.some(r=>r.body_sha256===doc.document_sha256)))throw new Error('ANNOUNCEMENT_PARSED_BODY_UNBOUND');
  }
  validateEastmoneyDocuments(eastmoneyDocs, date, cutoff);
  if(eastmoneyDocs.length && ['NOT_RUN','FAILED','READBACK_FAILED'].includes(String(value.eastmoney_hk_status)))
    throw new Error('EASTMONEY_HK_DOCUMENTS_WITHOUT_SUCCESSFUL_READBACK');
  for(const row of [...value.observations,...value.pending_observations]){
    safe(row);
    const original=value.official_documents.find(d=>d.event_id===row.event_id);
    if(!original || ['symbol','source_url','published_at','document_sha256'].some(k=>original[k]!==row[k]) ||
        row.focus_eligible!==false || row.buy_allowed!==false || row.prior_session!==value.prior_session ||
        object(row.intraday_price_volume).status!=='UNKNOWN')throw new Error('ANNOUNCEMENT_OBSERVATION_UNBOUND');
  }
  if(value.latest_attempt!==null){
    const attempt=object(value.latest_attempt);safe(attempt);
    if(attempt.target_trade_date!==date || attempt.owner!=='ManagerResearchJobService.refresh_announcements' ||
        !['MANUAL_REFRESH','SCHEDULED_REFRESH'].includes(String(attempt.execution_kind)))throw new Error('ANNOUNCEMENT_ATTEMPT_IDENTITY_INVALID');
    const start=announcementTime(attempt.started_at);
    if(attempt.state!=='RUNNING' && announcementTime(attempt.finished_at)<start)throw new Error('ANNOUNCEMENT_ATTEMPT_TIME_INVALID');
    strings(attempt.failure_reasons);
  }
  return value as unknown as AnnouncementObservation;
}

function validateUsMarketAttention(raw: unknown, date: string): UsMarketAttention {
  const value=object(raw);safe(value);strings(value.gaps);records(value.raw_industry_up);records(value.raw_individual_up);object(value.coverage);
  if(value.schema_version!=='v4.manager_research.us_market_bridge.v1' || value.target_trade_date!==date ||
      !['READY','PARTIAL','CANNOT_CONFIRM','INPUT_MISSING','SOURCE_FAILED'].includes(String(value.status)) ||
      value.coverage_scope!=='FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET' ||
      (value.expected_us_session!==null && !/^\d{8}$/.test(String(value.expected_us_session))))
    throw new Error('WORKSPACE_US_MARKET_IDENTITY_INVALID');
  if(value.source_identity!==null){const id=object(value.source_identity);if(id.status==='VERIFIED'){
    for(const key of ['payload_sha256','receipt_sha256','manifest_sha256'])if(typeof id[key]!=='string'||!/^[0-9a-f]{64}$/.test(String(id[key])))throw new Error('WORKSPACE_US_MARKET_LINEAGE_INVALID');
  }}
  return value as unknown as UsMarketAttention;
}
const LEGACY_RESEARCH_ATTENTION_PRIORITY = 'RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK';
const EVIDENCE_STATE_RESEARCH_ATTENTION_PRIORITY = 'EVIDENCE_STATE_RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK';
const EVIDENCE_STATE_RESEARCH_ATTENTION_ORDERING = 'EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS';
const RESEARCH_ATTENTION_STATES: Record<string, {groupOrder: number; label: string}> = {
  COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION: {groupOrder: 0, label: '公司证据 + 市场确认'},
  COMPANY_EVIDENCE_WAIT_MARKET: {groupOrder: 1, label: '公司证据，待市场确认'},
  MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE: {groupOrder: 2, label: '市场结构先行，缺公司级原因'},
  CONTEXT_ONLY: {groupOrder: 3, label: '产业/海外背景'},
  INSUFFICIENT: {groupOrder: 4, label: '证据不足'},
};
const RESEARCH_ATTENTION_LANES = [
  'OFFICIAL_ANNOUNCEMENT', 'COMPANY_MATERIAL', 'STRICT_NEAR_SCREEN',
  'TREND_CONTINUATION', 'US_INDIVIDUAL_MAPPING', 'US_INDUSTRY_MAPPING',
];
const RESEARCH_ATTENTION_LANE_LABELS: Record<string, string> = {
  OFFICIAL_ANNOUNCEMENT: '公司公告/官方披露',
  COMPANY_MATERIAL: '公司特异材料',
  STRICT_NEAR_SCREEN: '既有量价筛选',
  TREND_CONTINUATION: '趋势延续',
  US_INDIVIDUAL_MAPPING: '已核美股个股映射',
  US_INDUSTRY_MAPPING: '已核美股行业映射',
};

function explicitTimestamp(raw: unknown): number | null {
  if (typeof raw !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || !Number.isFinite(Date.parse(raw))) return null;
  return Date.parse(raw);
}

function sessionDay(raw: unknown): string | null {
  const value = typeof raw === 'number' && Number.isSafeInteger(raw) ? String(raw) : raw;
  if (typeof value !== 'string' || !/^\d{8}$/.test(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (year < 1900 || parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day)
    return null;
  return value;
}

const COMPANY_OWNER_ACQUISITION_FIELDS = ['available_at','retrieved_at','first_seen_at','collected_at'];
const COMPANY_ALL_ACQUISITION_FIELDS = [...COMPANY_OWNER_ACQUISITION_FIELDS,'archive_recorded_at'];
const RELATION_ACQUISITION_FIELDS = [
  'issuer_available_at','issuer_retrieved_at','available_at','retrieved_at','first_seen_at','collected_at',
];

function isJsonObject(value: unknown): value is JsonObject {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function timestampByWindow(value: unknown, start: number, cutoff: number): number | null {
  const parsed = explicitTimestamp(value);
  return parsed !== null && parsed >= start && parsed <= cutoff ? parsed : null;
}

function hasPersistedAcquisition(
  row: JsonObject, ownerFields: string[], allFields: string[], start: number, cutoff: number,
): boolean {
  let ownerClockSeen = false;
  for (const field of allFields) {
    const value = row[field];
    if (value === undefined || value === null || value === '') continue;
    const parsed = timestampByWindow(value, start, cutoff);
    if (parsed === null) return false;
    if (ownerFields.includes(field)) ownerClockSeen = true;
  }
  return ownerClockSeen;
}

// These are the existing Python native-relation roles, not new semantic statuses.
const MIRROR_TIME_BASIS = 'MIRROR_DISPLAY_TIME_NOT_HKEX_FIRST_PUBLICATION';
const sha256Value = (value: unknown): boolean => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
function verifiedNativeRefs(value: unknown): value is JsonObject[] {
  return nonEmptyObjectRecords(value) && value.every(ref => ref.status === 'VERIFIED' && sha256Value(ref.payload_sha256));
}
function validMirrorCompanyEvidence(row: JsonObject, start: number, cutoff: number, date: string): boolean {
  if (row.semantic_status !== 'ACCEPTED' || row.source_kind !== 'EASTMONEY_HK_ANNOUNCEMENT_BODY' ||
      row.source !== 'EASTMONEY_HK' || row.source_identity !== 'EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL' ||
      row.temporal_role !== 'CURRENT_WINDOW_MIRROR_OBSERVATION' || row.time_basis !== MIRROR_TIME_BASIS ||
      row.published_at !== null || row.hkex_first_publication_verified !== false ||
      row.publication_status !== 'CANNOT_CONFIRM_FIRST_PUBLICATION' || row.fresh_catalyst_eligible !== false ||
      row.buy_allowed !== false || !isJsonObject(row.owner_document) || !isJsonObject(row.owner_capture) ||
      !isJsonObject(row.original_source_row) || !verifiedNativeRefs(row.source_refs)) return false;
  const doc = row.owner_document, capture = row.owner_capture;
  // Reuse the ordinary announcement-document validator, including raw refs/pages.
  try { validateEastmoneyDocuments([doc], date, cutoff); } catch { return false; }
  const seen = explicitTimestamp(row.mirror_observed_at), acquired = explicitTimestamp(row.available_at);
  if (seen === null || acquired === null || !(start < seen && seen <= acquired && acquired <= cutoff) ||
      row.retrieved_at !== row.available_at || row.mirror_observed_at !== doc.display_time_iso ||
      row.available_at !== doc.available_at || row.symbol !== doc.symbol || row.issuer_code !== doc.symbol ||
      row.document_issuer_symbol !== doc.symbol || row.body_sha256 !== doc.body_sha256 ||
      row.document_sha256 !== doc.document_sha256 || row.art_code !== doc.art_code ||
      row.original_source_row.body_text !== doc.body_text || capture.source !== 'EASTMONEY_HK' ||
      capture.readback_status !== 'VERIFIED' || !sha256Value(capture.sha256) ||
      !/^[0-9a-f]{32}$/.test(String(capture.run_id)) || !Array.isArray(doc.source_refs) ||
      doc.source_refs.length !== row.source_refs.length) return false;
  return row.source_refs.every((ref,index) => {
    const raw = (doc.source_refs as JsonObject[])[index];
    return ref.representation === 'MATERIALSTORE_HTTP_RESPONSE_ENVELOPE' &&
      ref.verification_owner === 'workspace_announcements._check_eastmoney_sources' &&
      ref.payload_sha256 === raw.blob_sha256 && ref.response_body_sha256 === raw.body_sha256 &&
      ref.retrieved_at === raw.retrieved_at && isJsonObject(ref.raw_source_ref) &&
      ref.raw_source_ref.blob_sha256 === raw.blob_sha256 && ref.raw_source_ref.body_sha256 === raw.body_sha256;
  });
}
function validNativeRelation(row: JsonObject, start: number, cutoff: number): boolean {
  const relation = row.hk_relation as JsonObject;
  if (relation.semantic_status !== 'ACCEPTED' || relation.basis !== 'NATIVE_ISSUER_SUBJECT_ACTION_SOURCE_SPAN' ||
      relation.effect_scope !== 'ISSUER_CLAIM_NOT_PRICE_CONFIRMATION' ||
      !['SOURCE_STATEMENT','REPORTED_CLAIM'].includes(String(relation.claim_status)) ||
      relation.research_only !== true || relation.not_a_beneficiary_or_buy_assertion !== true ||
      relation.is_new_catalyst !== false || !/^HK\.(?!00000)\d{5}$/.test(String(relation.symbol)) ||
      typeof relation.issuer_quote !== 'string' || !relation.issuer_quote.trim() ||
      typeof relation.source_field !== 'string' || !relation.source_field ||
      !Number.isSafeInteger(relation.start) || !Number.isSafeInteger(relation.end) ||
      Number(relation.start) < 0 || Number(relation.end) <= Number(relation.start) ||
      !isJsonObject(relation.identity_source) || relation.identity_source.status !== 'OWNER_VERIFIED' ||
      !sha256Value(relation.identity_source.artifact_sha256) || !verifiedNativeRefs(relation.source_refs) ||
      !isJsonObject(row.source_identity) ||
      relation.source_refs.some(ref => ref.payload_sha256 === (row.source_identity as JsonObject).payload_sha256)) return false;
  const mirror = relation.issuer_time_basis === MIRROR_TIME_BASIS;
  if ((!mirror && relation.issuer_time_basis !== 'ORIGINAL_SOURCE_PUBLICATION') ||
      relation.issuer_published_at !== relation.published_at ||
      relation.issuer_retrieved_at !== relation.retrieved_at || relation.issuer_available_at !== relation.available_at ||
      (mirror && relation.published_at !== null)) return false;
  const published = explicitTimestamp(mirror ? relation.issuer_mirror_observed_at : relation.published_at);
  const retrieved = explicitTimestamp(relation.retrieved_at), acquired = explicitTimestamp(relation.available_at);
  const joint = explicitTimestamp(row.available_at);
  if (published === null || retrieved === null || acquired === null || joint === null ||
      !(published <= retrieved && retrieved <= acquired && acquired <= joint && joint <= cutoff)) return false;
  for (const field of ['first_seen_at','collected_at','archive_recorded_at']) {
    const value = relation[field];
    if (value === undefined || value === null || value === '') continue;
    const clock = explicitTimestamp(value);
    if (clock === null || clock > cutoff) return false;
  }
  if (mirror && relation.source_refs.some(ref => ref.representation !== 'MATERIALSTORE_HTTP_RESPONSE_ENVELOPE' ||
      ref.verification_owner !== 'workspace_announcements._check_eastmoney_sources' ||
      !isJsonObject(ref.raw_source_ref) || ref.payload_sha256 !== ref.raw_source_ref.blob_sha256 ||
      ref.response_body_sha256 !== ref.raw_source_ref.body_sha256)) return false;
  if (relation.relation_temporal_role === 'CURRENT_WINDOW_RELATION_EVIDENCE') {
    return relation.standing_validity === null && (mirror ? published > start : published >= start) &&
      (mirror || hasPersistedAcquisition(relation,COMPANY_OWNER_ACQUISITION_FIELDS,COMPANY_ALL_ACQUISITION_FIELDS,start,cutoff));
  }
  if (relation.relation_temporal_role !== 'STANDING_RELATION_NOT_NEW_CATALYST' ||
      relation.claim_status !== 'SOURCE_STATEMENT' || !isJsonObject(relation.standing_validity)) return false;
  const validity = relation.standing_validity;
  const begin = explicitTimestamp(validity.valid_from), end = explicitTimestamp(validity.valid_until);
  const confirmed = explicitTimestamp(validity.confirmed_at);
  // Body/quote SHA computations are rechecked by the Python source-owner gate.
  // This consumer verifies the serialized contract/refs and actual cutoff, never
  // treats an old relationship as a publication inside the current short window.
  return validity.schema_version === 'v4.manager_research.business_relation_validity.v1' && validity.status === 'ACTIVE' &&
    validity.issuer_symbol === relation.symbol &&
    validity.validity_basis === 'ORIGINAL_SOURCE_OWNER_EXPLICIT_REVIEW_PERIOD_NOT_NEW_CAPTURE' &&
    ['body_sha256','quote_sha256','source_payload_sha256'].every(key => sha256Value(validity[key])) &&
    validity.source_field === relation.source_field && validity.start === relation.start && validity.end === relation.end &&
    relation.source_refs.some(ref => ref.payload_sha256 === validity.source_payload_sha256) &&
    begin !== null && end !== null && confirmed !== null && begin <= confirmed && published <= confirmed &&
    confirmed <= acquired && cutoff < end && end - begin <= 366 * 86400000;
}

function validCompanyEvidence(row: JsonObject, start: number, cutoff: number, date: string): boolean {
  if (row.evidence_class === 'VERIFIED_MIRROR_COMPANY_MATERIAL_NOT_HKEX_FIRST_PUBLICATION')
    return validMirrorCompanyEvidence(row, start, cutoff, date);
  if (row.evidence_class !== 'VERIFIED_COMPANY_SPECIFIC_MATERIAL' ||
      row.semantic_status !== 'ACCEPTED' || row.temporal_role !== 'NEW_PLAN_PUBLICATION' ||
      timestampByWindow(row.published_at, start, cutoff) === null ||
      !hasPersistedAcquisition(row, COMPANY_OWNER_ACQUISITION_FIELDS, COMPANY_ALL_ACQUISITION_FIELDS, start, cutoff))
    return false;
  if (row.merged_provenance !== undefined) {
    if (!Array.isArray(row.merged_provenance) || !row.merged_provenance.length ||
        row.merged_provenance.some(trace => !isJsonObject(trace) ||
          !hasPersistedAcquisition(trace, COMPANY_OWNER_ACQUISITION_FIELDS, COMPANY_ALL_ACQUISITION_FIELDS, start, cutoff)))
      return false;
  }
  return true;
}

function validOfficialEvidence(row: JsonObject, start: number, cutoff: number): boolean {
  const parsed = row.body_status === 'BODY_PARSED';
  const allowedBody = ['FAILED','BODY_PARSED','BODY_UNREADABLE','BODY_UNREAD'].includes(String(row.body_status));
  const refs = row.source_refs;
  if (!allowedBody || row.evidence_class !== (parsed ? 'OFFICIAL_PARSED_DOCUMENT' : 'OFFICIAL_DIRECTORY_ONLY') ||
      timestampByWindow(row.published_at, start, cutoff) === null || !Array.isArray(refs) || !refs.length ||
      refs.some(ref => !isJsonObject(ref) || !/^[0-9a-f]{64}$/.test(String(ref.blob_sha256)) ||
        !/^[0-9a-f]{64}$/.test(String(ref.body_sha256)) || typeof ref.source_key !== 'string' ||
        (ref.retrieved_at !== undefined && ref.retrieved_at !== null && ref.retrieved_at !== '' &&
          timestampByWindow(ref.retrieved_at, start, cutoff) === null)))
    return false;
  let acquisitionSeen = false;
  for (const field of ['available_at','retrieved_at']) {
    const value = row[field];
    if (value === undefined || value === null || value === '') continue;
    const parsedTime = timestampByWindow(value, start, cutoff);
    const published = explicitTimestamp(row.published_at);
    if (parsedTime === null || published === null || parsedTime < published) return false;
    acquisitionSeen = true;
  }
  if (!acquisitionSeen) return false;
  if (parsed && (!/^[0-9a-f]{64}$/.test(String(row.document_sha256)) ||
      !refs.some(ref => isJsonObject(ref) && ref.body_sha256 === row.document_sha256))) return false;
  return true;
}

function validUsSourceIdentity(value: unknown): boolean {
  if (!isJsonObject(value) || value.status !== 'VERIFIED') return false;
  return ['payload_sha256','receipt_sha256','manifest_sha256']
    .every(field => typeof value[field] === 'string' && /^[0-9a-f]{64}$/.test(String(value[field])));
}

function nonEmptyObjectRecords(value: unknown): value is JsonObject[] {
  return Array.isArray(value) && value.length > 0 && value.every(isJsonObject);
}

function validTrendEvidence(row: JsonObject, screenSession: string | null): boolean {
  return row.evidence_class === 'VERIFIED_SCREEN_HISTORY_TREND' && screenSession !== null &&
    sessionDay(row.verified_session) === screenSession &&
    typeof row.recent_3_session_return_pct === 'number' && Number.isFinite(row.recent_3_session_return_pct) && row.recent_3_session_return_pct > 0 &&
    typeof row.recent_5_session_return_pct === 'number' && Number.isFinite(row.recent_5_session_return_pct) && row.recent_5_session_return_pct > 0 &&
    nonEmptyObjectRecords(row.source_refs) && row.source_refs.every(ref =>
      typeof ref.owner === 'string' && !!ref.owner.trim() &&
      typeof ref.payload_path === 'string' && !!ref.payload_path.trim() &&
      /^[0-9a-f]{64}$/.test(String(ref.payload_sha256)) &&
      typeof ref.manifest_path === 'string' && !!ref.manifest_path.trim() &&
      /^[0-9a-f]{64}$/.test(String(ref.manifest_sha256)));
}

function validUsIndustryMapping(row: JsonObject, start: number, cutoff: number): boolean {
  if (row.evidence_class !== 'VERIFIED_US_INDUSTRY_WITH_HK_ISSUER_RELATION' ||
      !validUsSourceIdentity(row.source_identity) || timestampByWindow(row.us_captured_at, start, cutoff) === null ||
      timestampByWindow(row.available_at, start, cutoff) === null || !isJsonObject(row.us_mover) ||
      !['READY','PARTIAL'].includes(String(row.us_mover.status)) ||
      row.us_mover.instrument_classification !== 'INDUSTRY_PROXY_NOT_FULL_MARKET_SECURITY_SCREEN' ||
      typeof row.us_mover.label !== 'string' || !row.us_mover.label.trim() || !isJsonObject(row.hk_relation))
    return false;
  const relation = row.hk_relation;
  if (relation.relation_origin === 'NATIVE_MATERIAL_PROPOSITION')
    return relation.relationship_type === 'INDUSTRY_INFERENCE' && row.issuer_published_at === relation.issuer_published_at &&
      validNativeRelation(row,start,cutoff);
  return relation.relationship_type === 'INDUSTRY_INFERENCE' &&
    typeof relation.issuer_quote === 'string' && !!relation.issuer_quote.trim() &&
    nonEmptyObjectRecords(relation.source_refs) &&
    timestampByWindow(relation.issuer_published_at, start, cutoff) !== null &&
    hasPersistedAcquisition(relation, RELATION_ACQUISITION_FIELDS, [...RELATION_ACQUISITION_FIELDS, 'archive_recorded_at'], start, cutoff);
}

function relatedUsSymbols(relation: JsonObject): Set<string> {
  const symbols = new Set<string>();
  const add = (value: unknown): void => {
    const rows = typeof value === 'string' ? [value] : Array.isArray(value) ? value : [];
    for (const row of rows) if (typeof row === 'string' && row.trim()) symbols.add(row.trim().toUpperCase());
  };
  add(relation.related_us_symbols); add(relation.us_symbols);
  if (isJsonObject(relation.identity_pair_basis)) {
    add(relation.identity_pair_basis.related_us_symbols);
    add(relation.identity_pair_basis.us_symbols);
    add(relation.identity_pair_basis.us_symbol);
  }
  return symbols;
}

function validUsIndividualMapping(row: JsonObject, start: number, cutoff: number): boolean {
  if (row.evidence_class !== 'VERIFIED_US_INDIVIDUAL_WITH_STRUCTURED_HK_RELATION' ||
      !validUsSourceIdentity(row.source_identity) || timestampByWindow(row.us_captured_at, start, cutoff) === null ||
      timestampByWindow(row.available_at, start, cutoff) === null || !isJsonObject(row.us_mover) ||
      row.us_mover.instrument_classification !== 'CONFIGURED_US_SYMBOL_NOT_FULL_MARKET_SCREEN' ||
      typeof row.us_mover.symbol !== 'string' || !row.us_mover.symbol.trim() || !isJsonObject(row.hk_relation))
    return false;
  const relation = row.hk_relation;
  if (relation.relation_origin === 'NATIVE_MATERIAL_PROPOSITION')
    return relation.relationship_type === 'EXPLICIT_US_ISSUER_RELATION' && row.published_at === relation.published_at &&
      relatedUsSymbols(relation).has(String(row.us_mover.symbol).trim().toUpperCase()) && validNativeRelation(row,start,cutoff);
  const published = timestampByWindow(relation.published_at, start, cutoff);
  return relation.semantic_status === 'ACCEPTED' && nonEmptyObjectRecords(relation.source_refs) &&
    published !== null && row.published_at === relation.published_at &&
    relatedUsSymbols(relation).has(String(row.us_mover.symbol).trim().toUpperCase()) &&
    hasPersistedAcquisition(relation, COMPANY_OWNER_ACQUISITION_FIELDS, COMPANY_ALL_ACQUISITION_FIELDS, start, cutoff);
}

function validateAttentionLaneEvidence(
  card: JsonObject, lanes: string[], start: number | null, cutoff: number | null, screenSession: string | null,
): {
  companyStrength: number; marketStrength: number; contextStrength: number;
} {
  if (start === null || cutoff === null) throw new Error('attention window');
  const evidence = card.evidence as JsonObject[];
  if (evidence.some(row => isJsonObject(row.hk_relation) &&
      row.hk_relation.relation_origin === 'NATIVE_MATERIAL_PROPOSITION' && row.hk_relation.symbol !== card.symbol))
    throw new Error('native relation issuer mismatch');
  if (evidence.some(row => typeof row.evidence_lane !== 'string' ||
      !RESEARCH_ATTENTION_LANES.includes(row.evidence_lane) || !lanes.includes(row.evidence_lane)))
    throw new Error('evidence lane mismatch');
  const rowsFor = (lane: string): JsonObject[] => evidence.filter(row => row.evidence_lane === lane);
  const validateClaim = (lane: string, valid: (row: JsonObject) => boolean): JsonObject[] => {
    if (!lanes.includes(lane)) return [];
    const rows = rowsFor(lane);
    if (!rows.length || rows.some(row => !valid(row))) throw new Error('lane evidence invalid');
    return rows;
  };

  const officialRows = validateClaim('OFFICIAL_ANNOUNCEMENT', row => validOfficialEvidence(row, start, cutoff));
  validateClaim('COMPANY_MATERIAL', row => validCompanyEvidence(row, start, cutoff, date));
  const individualRows = validateClaim('US_INDIVIDUAL_MAPPING', row => validUsIndividualMapping(row, start, cutoff));
  const industryRows = validateClaim('US_INDUSTRY_MAPPING', row => validUsIndustryMapping(row, start, cutoff));
  const trendRows = validateClaim('TREND_CONTINUATION', row => validTrendEvidence(row, screenSession));

  const companyStrength = officialRows.length
    ? (officialRows.some(row => row.evidence_lane === 'OFFICIAL_ANNOUNCEMENT' &&
      row.evidence_class === 'OFFICIAL_PARSED_DOCUMENT' && row.body_status === 'BODY_PARSED') ? 3 : 2)
    : lanes.includes('COMPANY_MATERIAL') ? 1 : 0;
  const classification = card.screen_classification;
  const marketStrength = classification === 'STRICT_REBOUND' ? 3
    : classification === 'NEAR_CONDITION' ? 2 : trendRows.length ? 1 : 0;
  const contextStrength = individualRows.length ? 2 : industryRows.length ? 1 : 0;
  return { companyStrength, marketStrength, contextStrength };
}

function validateAttentionDecision(
  raw: unknown, card: JsonObject, start: number | null, cutoff: number | null, screenSession: string | null,
): ResearchAttentionDecision {
  try {
    const decision = object(raw);
    const state = decision.state;
    if (decision.schema_version !== 'v4.manager_research.attention_decision.v1' ||
        decision.version !== '20260927.evidence-state-triage.proposal-v1' ||
        decision.status !== 'PROPOSAL_ONLY' || typeof state !== 'string' ||
        !Object.prototype.hasOwnProperty.call(RESEARCH_ATTENTION_STATES, state))
      throw new Error('decision identity');
    const contract = RESEARCH_ATTENTION_STATES[state];
    if (decision.group_order !== contract.groupOrder || decision.group_label !== contract.label ||
        typeof decision.summary !== 'string' || !decision.summary.trim() ||
        typeof decision.next_check !== 'string' || !decision.next_check.trim() ||
        typeof decision.invalidation !== 'string' || !decision.invalidation.trim())
      throw new Error('decision explanation');
    strings(decision.why_now_readable);
    const strength = (value: unknown, max: number): value is number =>
      typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
    if (!strength(decision.company_evidence_strength, 3) ||
        !strength(decision.market_confirmation_strength, 3) ||
        !strength(decision.context_strength, 2))
      throw new Error('decision strengths');
    const lanes = card.qualified_lanes as string[];
    if (lanes.some(lane => !RESEARCH_ATTENTION_LANES.includes(lane)) || new Set(lanes).size !== lanes.length ||
        card.qualified_lane_count !== lanes.length)
      throw new Error('decision lanes');
    const hasMarketScreenLane = lanes.includes('STRICT_NEAR_SCREEN');
    const classification = card.screen_classification;
    const hasScreenClassification = classification === 'STRICT_REBOUND' || classification === 'NEAR_CONDITION';
    if ((classification !== null && !hasScreenClassification) || hasMarketScreenLane !== hasScreenClassification)
      throw new Error('decision screen mapping');
    const laneEvidence = validateAttentionLaneEvidence(card, lanes, start, cutoff, screenSession);
    const expectedCompanyStrength = laneEvidence.companyStrength;
    const expectedMarketStrength = laneEvidence.marketStrength;
    const expectedContextStrength = laneEvidence.contextStrength;
    if (decision.company_evidence_strength !== expectedCompanyStrength ||
        decision.market_confirmation_strength !== expectedMarketStrength ||
        decision.context_strength !== expectedContextStrength)
      throw new Error('decision evidence mapping');
    const stateMatchesEvidence =
      (state === 'COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION' && expectedCompanyStrength > 0 && expectedMarketStrength > 0) ||
      (state === 'COMPANY_EVIDENCE_WAIT_MARKET' && expectedCompanyStrength > 0 && expectedMarketStrength === 0) ||
      (state === 'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE' && expectedCompanyStrength === 0 && expectedMarketStrength > 0) ||
      (state === 'CONTEXT_ONLY' && expectedCompanyStrength === 0 && expectedMarketStrength === 0 && expectedContextStrength > 0) ||
      (state === 'INSUFFICIENT' && expectedCompanyStrength === 0 && expectedMarketStrength === 0 && expectedContextStrength === 0);
    if (!stateMatchesEvidence) throw new Error('decision state evidence');
    if (decision.formal_rank_writeback !== false || decision.stage_writeback !== false || decision.buy_gate_writeback !== false)
      throw new Error('decision writeback');
    const key = decision.research_priority_key;
    const expectedKey = [
      contract.groupOrder,
      -Number(card.research_attention_score),
      -Number(decision.company_evidence_strength),
      -Number(decision.market_confirmation_strength),
      -Number(decision.context_strength),
      -Number(card.qualified_lane_count),
    ];
    if (!Array.isArray(key) || key.length !== expectedKey.length ||
        key.some((value, index) => !Number.isSafeInteger(value) || value !== expectedKey[index]))
      throw new Error('decision priority key');
    const expectedReasons = RESEARCH_ATTENTION_LANES.filter(lane => lanes.includes(lane))
      .map(lane => RESEARCH_ATTENTION_LANE_LABELS[lane]);
    if (JSON.stringify(decision.why_now_readable) !== JSON.stringify(expectedReasons))
      throw new Error('decision readable evidence');
    for (const field of ['freshest_published_at','freshest_acquired_at']) {
      const value = card[field];
      if (!(value === null || (typeof value === 'string' && value.trim() && Number.isFinite(Date.parse(value)))))
        throw new Error('decision evidence clocks');
    }
    return decision as unknown as ResearchAttentionDecision;
  } catch {
    throw new Error('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');
  }
}

function validateResearchAttention(raw: unknown, date: string, screenSession: string | null): ResearchAttention {
  const value=object(raw);safe(value);records(value.cards);object(value.coverage);object(value.config);strings(value.gaps);
  if(value.schema_version!=='v4.manager_research.research_attention.v1' || value.target_trade_date!==date ||
      typeof value.input_identity!=='string'||!/^[0-9a-f]{64}$/.test(value.input_identity) ||
      value.strict_near_unchanged!==true || value.existing_focus_rank_unchanged!==true || value.stage_unchanged!==true)
    throw new Error('WORKSPACE_RESEARCH_ATTENTION_IDENTITY_INVALID');
  const legacyOrder = value.priority_name === LEGACY_RESEARCH_ATTENTION_PRIORITY;
  const evidenceStateOrder = value.priority_name === EVIDENCE_STATE_RESEARCH_ATTENTION_PRIORITY;
  if (!legacyOrder && !evidenceStateOrder) throw new Error('WORKSPACE_RESEARCH_ATTENTION_PRIORITY_INVALID');
  if (evidenceStateOrder && value.ordering_basis !== EVIDENCE_STATE_RESEARCH_ATTENTION_ORDERING)
    throw new Error('WORKSPACE_RESEARCH_ATTENTION_ORDERING_INVALID');
  const seen=new Set<string>();let previousCard: ResearchAttentionCard | undefined;
  const cutoff=explicitTimestamp(value.research_cutoff);
  const freshness=evidenceStateOrder ? object(value.freshness) : {};
  const start=explicitTimestamp(freshness.effective_start);
  if (evidenceStateOrder && (cutoff === null || start === null || start > cutoff))
    throw new Error('WORKSPACE_RESEARCH_ATTENTION_CUTOFF_INVALID');
  const timestampForOrder=(raw: unknown): number => {
    if (raw === null) return Number.NEGATIVE_INFINITY;
    const parsed=explicitTimestamp(raw);
    if (parsed === null || start === null || cutoff === null || parsed < start || parsed > cutoff)
      throw new Error('WORKSPACE_RESEARCH_ATTENTION_TIME_INVALID');
    return parsed;
  };
  const publicationForOrder=(card: JsonObject): number => {
    const raw=card.freshest_published_at, parsed=explicitTimestamp(raw);
    // Preserve the original publication clock of an admitted standing relation.
    // Only that source-bound clock may precede this attention window; acquired
    // ordering clocks still obey the current US/issuer joint evidence window.
    if (parsed!==null && start!==null && cutoff!==null && parsed<start &&
        (card.evidence as JsonObject[]).some(row=>isJsonObject(row.hk_relation) &&
          row.hk_relation.relation_origin==='NATIVE_MATERIAL_PROPOSITION' &&
          row.hk_relation.relation_temporal_role==='STANDING_RELATION_NOT_NEW_CATALYST' &&
          row.hk_relation.issuer_published_at===raw && validNativeRelation(row,start,cutoff))) return parsed;
    return timestampForOrder(raw);
  };
  const comparePriorityKey=(left: number[], right: number[]): number => {
    for(let index=0;index<left.length;index++) if(left[index]!==right[index]) return left[index]-right[index];
    return 0;
  };
  for(const card of value.cards){
    if(typeof card.symbol!=='string'||!/^HK\.(?!00000)\d{5}$/.test(card.symbol)||seen.has(card.symbol)||typeof card.name!=='string')throw new Error('WORKSPACE_RESEARCH_ATTENTION_CARD_INVALID');
    seen.add(card.symbol);count(card.research_attention_score);count(card.qualified_lane_count);strings(card.qualified_lanes);strings(card.why_now);strings(card.missing);records(card.evidence);
    if(card.research_attention_score>100 ||
       !['IMMEDIATE_RESEARCH','HIGH_RESEARCH','NORMAL_RESEARCH','BACKGROUND_RESEARCH','UNVERIFIED'].includes(String(card.research_attention_band)) ||
       ![null,'STRICT_REBOUND','NEAR_CONDITION'].includes(card.screen_classification as null|string) ||
       (card.original_screen_rank!==null && (!Number.isSafeInteger(card.original_screen_rank)||Number(card.original_screen_rank)<1)))
      throw new Error('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
    safe(card);
    if (legacyOrder) {
      const trendRows = card.evidence.filter(row => row.evidence_lane === 'TREND_CONTINUATION');
      const claimsTrend = card.qualified_lanes.includes('TREND_CONTINUATION');
      if (claimsTrend !== (trendRows.length > 0) || trendRows.some(row => !validTrendEvidence(row, screenSession)))
        throw new Error('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
      if (previousCard && card.research_attention_score > previousCard.research_attention_score)
        throw new Error('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
    } else {
      const decision=validateAttentionDecision(card.decision,card,start,cutoff,screenSession);
      if (previousCard) {
        const previousDecision=previousCard.decision as ResearchAttentionDecision;
        const currentKey=decision.research_priority_key;
        const previousKey=previousDecision.research_priority_key;
        let order=comparePriorityKey(currentKey,previousKey);
        if(order===0){
          const currentAcquired=timestampForOrder(card.freshest_acquired_at);
          const previousAcquired=timestampForOrder(previousCard.freshest_acquired_at);
          order=previousAcquired-currentAcquired;
          if(order===0){
            const currentPublished=publicationForOrder(card);
            const previousPublished=publicationForOrder(previousCard);
            order=previousPublished-currentPublished;
            if(order===0){
              const currentRank=card.original_screen_rank===null?Number.POSITIVE_INFINITY:Number(card.original_screen_rank);
              const previousRank=previousCard.original_screen_rank===null?Number.POSITIVE_INFINITY:Number(previousCard.original_screen_rank);
              order=currentRank-previousRank || card.symbol.localeCompare(previousCard.symbol);
            }
          }
        }
        if(order<0)throw new Error('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
      } else {
        timestampForOrder(card.freshest_acquired_at);
        publicationForOrder(card);
      }
    }
    previousCard=card as unknown as ResearchAttentionCard;
  }
  return value as unknown as ResearchAttention;
}

export function validateManagerWorkspace(raw: unknown, date: string): ManagerWorkspace {
  const value = object(raw); safe(value);
  if(value.announcement_observation!==undefined)validateAnnouncementObservation(value.announcement_observation,date);
  if(value.us_market_attention!==undefined)validateUsMarketAttention(value.us_market_attention,date);
  if (value.schema_version !== 'v4.manager_research.workspace.v1' || value.target_trade_date !== date ||
      typeof value.input_identity !== 'string' || !/^[0-9a-f]{64}$/.test(value.input_identity)) throw new Error('WORKSPACE_IDENTITY_INVALID');
  records(value.stocks); records(value.lanes); records(value.themes); records(value.materials); strings(value.gaps);
  if(value.semantic_version!=='20260921.manager-semantic.r3.v1')throw new Error('WORKSPACE_SEMANTIC_RECOMPUTE_REQUIRED');
  strings(value.focus_symbols); records(value.company_events); records(value.rejected_relations);object(value.briefing);
  if(new Set(value.focus_symbols).size!==value.focus_symbols.length)throw new Error('WORKSPACE_FOCUS_DUPLICATE');
  const keys = new Set<string>();
  for (const stock of value.stocks) {
    safe(stock);
    if (stock.market !== 'HK' || typeof stock.symbol !== 'string' || !/^HK\.(?!00000)\d{5}$/.test(stock.symbol) ||
        stock.target_date !== date || stock.stock_key !== `HK|${stock.symbol}|${date}` || keys.has(String(stock.stock_key)) ||
        typeof stock.name !== 'string') throw new Error('WORKSPACE_STOCK_IDENTITY_INVALID');
    if(typeof stock.is_focus!=='boolean' || stock.is_focus!==value.focus_symbols.includes(stock.symbol))
      throw new Error('WORKSPACE_FOCUS_UNJUSTIFIED');
    const priority=object(stock.priority_basis);strings(priority.evidence_ids);
    if(stock.is_focus && (!priority.evidence_ids.length || !['DIRECT_COMPANY_EVENT','COMPANY_RESEARCH','INDUSTRY_INFERENCE'].includes(String(priority.group))))
      throw new Error('WORKSPACE_FOCUS_NO_EVIDENCE');
    keys.add(String(stock.stock_key)); strings(stock.lanes); strings(stock.themes); strings(stock.why_watch);
    records(stock.evidence); records(stock.material_relations); count(stock.event_group_count); count(stock.new_catalyst_count);
    if (stock.new_catalyst_count > stock.event_group_count) throw new Error('WORKSPACE_EVENT_COUNT_INVALID');
    const change = object(stock.change); strings(change.reasons);
    const plan = object(stock.plan); safe(plan); strings(plan.next_observation); strings(plan.invalidation_conditions); strings(plan.missing);
    for (const key of ['key_risks','wait_conditions','evidence_ids']) if (plan[key] !== undefined) strings(plan[key]);
    if (plan.trigger_price !== null || plan.invalidation_price !== null) {
      const positive=(v: unknown): v is number => typeof v==='number' && Number.isFinite(v) && v>0;
      const price=object(plan.price_provenance); const inputs=object(price.inputs); const ctx=object(value.plan_context);
      records(price.source_refs);
      if (!positive(plan.trigger_price) || (plan.invalidation_price!==null && !positive(plan.invalidation_price)) ||
          price.verification!=='OWNER_VERIFIED' || price.currency!=='HKD' ||
          !['RAW','UNADJUSTED'].includes(String(price.price_basis)) || price.session_kind!=='FULL_DAY_CLOSE' ||
          price.symbol!==stock.symbol || price.session_date!==ctx.market_session || ctx.plan_trade_date!==date ||
          ctx.market_data_verified!==true || typeof price.session_date!=='string' || !/^\d{8}$/.test(price.session_date) || price.session_date>=date ||
          price.rule_id!=='RECLAIM_VERIFIED_SESSION_CLOSE' || price.trigger_formula!=='close' ||
          !positive(inputs.close) || plan.trigger_price!==inputs.close ||
          (plan.invalidation_price!==null && (price.invalidation_formula!=='low' || !positive(inputs.low) || plan.invalidation_price!==inputs.low || inputs.low>inputs.close)) ||
          price.source_refs.length===0 || price.source_refs.some(r=>typeof r.payload_sha256!=='string' || !/^[0-9a-f]{64}$/.test(r.payload_sha256)))
        throw new Error('WORKSPACE_PRICE_PROVENANCE_INVALID');
    }
    validateActions(stock,value);
  }
  const validatedStocks=value.stocks;
  if(value.focus_symbols.some(symbol=>!validatedStocks.some(s=>s.symbol===symbol)))throw new Error('WORKSPACE_FOCUS_UNKNOWN_STOCK');
  const lanes = new Set<string>();
  for (const lane of value.lanes) {
    if (!['STAGE','CATALYST','CLOSE'].includes(String(lane.lane)) || lanes.has(String(lane.lane)) || lane.target_date !== date ||
        !['NOT_RUN','RUNNING','FAILED','PARTIAL','UNVERIFIED','SUCCEEDED','SUCCEEDED_EMPTY'].includes(String(lane.state)) ||
        typeof lane.owner !== 'string') throw new Error('WORKSPACE_LANE_INVALID');
    lanes.add(String(lane.lane)); strings(lane.failure_reasons);
    if (lane.stock_count !== null) count(lane.stock_count);
    if (lane.next_plan !== null) {
      const plan = object(lane.next_plan);
      if (plan.verification !== 'OWNER_VERIFIED' || !plan.owner || !plan.run_id || typeof plan.next_at !== 'string') throw new Error('WORKSPACE_SCHEDULE_UNVERIFIED');
    }
  }
  if (lanes.size !== 3) throw new Error('WORKSPACE_LANES_MISSING');
  const summary = object(value.summary);
  for (const k of ['stock_count','relation_count','theme_count','reused_material_count','formal_recommendation_count']) count(summary[k]);
  if (summary.stock_count !== value.stocks.length || summary.formal_recommendation_count !== 0) throw new Error('WORKSPACE_SUMMARY_INVALID');
  let verifiedScreenSession: string | null = null;
  if (value.market_screen !== undefined) {
    const screen = object(value.market_screen); strings(screen.gaps);
    verifiedScreenSession = sessionDay(screen.verified_session);
    if (screen.schema_version !== 'v4.manager_research.rebound_v3_screen.v1' ||
        typeof screen.rule_version !== 'string' || screen.target_trade_date !== date ||
        verifiedScreenSession === null || verifiedScreenSession > date ||
        !['READY','READY_WITH_GAPS','CANNOT_CONFIRM'].includes(String(screen.status)) ||
        typeof screen.main_screen_ready !== 'boolean' || screen.RESEARCH_ONLY !== true ||
        screen.production_allowed !== false || screen.buy_gate_updated !== false || screen.orders_sent !== false ||
        (screen.input_identity !== null && (typeof screen.input_identity !== 'string' || !/^[0-9a-f]{64}$/.test(screen.input_identity))))
      throw new Error('WORKSPACE_SCREEN_IDENTITY_INVALID');
    // The prior frozen four-condition artifact must not render under the new
    // two-condition explanation. TEST_* rule ids remain usable by UI fixtures.
    if (screen.rule_version === '20260921_REBOUND_V3') throw new Error('WORKSPACE_SCREEN_RULE_STALE');
    records(screen.cards); records(screen.strict); records(screen.near); records(screen.pending);
    const coverage = object(screen.coverage);
    const inputCount = coverage.input_candidate_count ?? coverage.amount_gate_candidate_count;
    const nearCount = coverage.near_count ?? coverage.near_selected_count;
    count(inputCount); count(coverage.history_complete_count); count(coverage.history_pending_count);
    count(coverage.strict_count); count(coverage.near_candidate_count); count(nearCount); count(coverage.selected_count);
    if (coverage.selected_count !== screen.cards.length || coverage.strict_count !== screen.strict.length ||
        nearCount !== screen.near.length || coverage.near_candidate_count !== nearCount ||
        coverage.history_pending_count !== screen.pending.length ||
        inputCount !== coverage.history_complete_count + coverage.history_pending_count ||
        coverage.selected_count !== coverage.strict_count + nearCount)
      throw new Error('WORKSPACE_SCREEN_COUNT_INVALID');
    for (const card of screen.cards) {
      if (!['STRICT_REBOUND','NEAR_CONDITION'].includes(String(card.classification)) ||
          typeof card.code !== 'string' || !/^HK\.(?!00000)\d{5}$/.test(card.code) || typeof card.name !== 'string' ||
          String(card.target_monday) !== date || card.qualification_status !== 'RESEARCH_ONLY_CANDIDATE')
        throw new Error('WORKSPACE_SCREEN_CARD_INVALID');
    }
    for (const card of screen.pending) {
      if (typeof card.code !== 'string' || !/^HK\.(?!00000)\d{5}$/.test(card.code) ||
          typeof card.name !== 'string' || String(card.target_monday) !== date ||
          card.qualification_status !== 'RESEARCH_ONLY_CANDIDATE' || card.history_status !== 'PARTIAL_UNKNOWN' ||
          typeof card.history_unknown_reasons !== 'string' || !card.history_unknown_reasons)
        throw new Error('WORKSPACE_SCREEN_PENDING_CARD_INVALID');
    }
  }
  if(value.research_attention!==undefined)validateResearchAttention(value.research_attention,date,verifiedScreenSession);
  validateReadContext(value);
  return value as unknown as ManagerWorkspace;
}
async function parseWorkspaceResponse(response: Response, date: string): Promise<ManagerWorkspace> {
  let raw: unknown;
  try { raw=await response.json(); }
  catch(error) {
    if(error instanceof SyntaxError)throw new Error('WORKSPACE_RESPONSE_JSON_INVALID');
    throw error; // actual transport/body-read failures remain distinguishable
  }
  return validateManagerWorkspace(raw,date);
}
export async function requestManagerWorkspace(date: string, signal: AbortSignal, view: WorkspaceView = 'auto'): Promise<ManagerWorkspace> {
  if (!/^\d{8}$/.test(date)) throw new Error('WORKSPACE_DATE_REQUIRED');
  const response = await fetch(`/api/v4/manager/research/workspace?date=${encodeURIComponent(date)}&view=${encodeURIComponent(view)}`, {
    method: 'GET', signal, credentials: 'same-origin', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`WORKSPACE_HTTP_${response.status}`);
  const value=await parseWorkspaceResponse(response, date);
  const read=object(value.read_context); // an old backend cannot silently provide a historical dynamic view
  if ((view==='historical' && read.mode!=='HISTORICAL_AS_OF') ||
      (view==='dynamic' && read.mode!=='CURRENT_DYNAMIC_PREVIEW')) throw new Error('WORKSPACE_VIEW_MISMATCH');
  return value;
}

/** Explicit user action: original owner reuses existing input, never a crawler. */
export async function refreshManagerWorkspace(date: string, signal: AbortSignal): Promise<ManagerWorkspace> {
  if (!/^\d{8}$/.test(date)) throw new Error('WORKSPACE_DATE_REQUIRED');
  const response = await fetch(`/api/v4/manager/research/workspace/refresh?date=${encodeURIComponent(date)}`, {
    method: 'POST', signal, credentials: 'same-origin', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`WORKSPACE_REFRESH_HTTP_${response.status}`);
  return await parseWorkspaceResponse(response, date);
}
