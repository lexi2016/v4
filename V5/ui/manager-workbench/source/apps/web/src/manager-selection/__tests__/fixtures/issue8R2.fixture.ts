/** Exact retained owner observations inside a SYNTHETIC R1-shaped envelope.
 * This is not a full GET replay, live source read, or natural-slot verification. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
interface OwnerObservation { symbol:string; [key:string]:unknown; }
function readOwnerObservations(): OwnerObservation[] {
  const path=process.env.V5_ISSUE8R2_OBSERVATIONS || resolve(process.cwd(),'src/manager-selection/__tests__/fixtures/issue8R2.ownerObservations.json');
  const value:unknown=JSON.parse(readFileSync(path,'utf8'));
  if(!Array.isArray(value)||value.some(row=>!row||typeof row!=='object'||typeof row.symbol!=='string'))
    throw new Error('ORIGINAL_ISSUE8R2_OBSERVATIONS_INVALID');
  return value as OwnerObservation[];
}
export const safety={RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
export const date='20261002';
export const gap='HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_V2_ARTIFACT_MISSING';
export function fixture(): any {
  const calendar={status:'NOT_APPLICABLE',reason:'HK_CONNECT_NON_TRADING_DAY',target_trade_date:date,
    calendar_owner:'contracts.trading_calendar',calendar_sha256:'9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb',
    hk_securities_state:'FULL_TRADING_DAY',hk_connect_state:'NON_TRADING_DAY'};
  const formal={status:'NOT_APPLICABLE',reason:'HK_CONNECT_NON_TRADING_DAY',target_trade_date:date,
    candidate_count:0,membership_status:'CANNOT_CONFIRM',calendar,qualified:false,buy_allowed:false,...safety};
  const cards=structuredClone(readOwnerObservations()).map(row=>({...row,
    observation_role:'EXISTING_OFFICIAL_STATEMENT_NOT_CONNECT_SELECTION',
    assertion:'SOURCE_STATEMENT_NOT_PRICE_PREDICTION_OR_BUY',qualified:false,buy_allowed:false,
    target_connect_membership:{status:'CANNOT_CONFIRM',target_trade_date:date,authority_identity:null,reason:gap}}));
  const attention={schema_version:'v4.manager_research.research_attention.v1',target_trade_date:date,
    research_cutoff:'2026-10-03T15:56:47.663674+08:00',status:'READY_WITH_GAPS',
    priority_name:'EVIDENCE_STATE_RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK',
    ordering_basis:'EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS',
    freshness:{effective_start:'2026-09-29T16:10:00+08:00'},
    config:{version:'20260927.research-attention.evidence-state-v2',status:'PROPOSAL_ONLY',display_limit:30},
    cards:[],coverage:{},gaps:[gap,'ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID','NO_SUBJECT_BOUND_BUSINESS_OR_US_RELATION'],
    input_identity:'a'.repeat(64),strict_near_unchanged:true,existing_focus_rank_unchanged:true,stage_unchanged:true,...safety,
    observation_only:{status:'OBSERVED_WITH_RESTRICTIONS',cards,rejections:[],card_count:cards.length,
      symbol_count:new Set(cards.map(row=>row.symbol)).size,scored_attention_input:false,formal_selection_input:false,universe_exhaustive:false,...safety},
    input_diagnostics:{scope:{announcements:{status:'CANNOT_CONFIRM',target_trade_date:date,membership_identity:null,
      counts:{official_documents:{input:2,admitted:0,rejected:2}},rejection_reasons:{TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED:2},
      gaps:[gap],count_basis:'PER_INPUT_LIST_NOT_UNIQUE_SECURITIES',formal_selection:structuredClone(formal)}},
      official_announcements:{status:'PARTIAL',coverage:{observed_document_count:12,queried_issuer_count:8,
        native_master_count:10,all_official_announcements_captured:false},gaps:['SYNTHETIC_PARTIAL_COVERAGE']},
      eastmoney_selection:{status:'PARTIAL',document_count:0,exhaustive:false,gaps:['EASTMONEY_HK_DISPLAY_TIME_OUTSIDE_CONSUMER_WINDOW']},
      us_relations:{status:'PARTIAL',assessment_state:'INSUFFICIENT',material_complete:false,
        acquisition_field_location:'CANNOT_CONFIRM_WITHOUT_ORIGINAL_OWNER_ROW',gaps:['ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:fixture']}}};
  return {schema_version:'v4.manager_research.workspace.v1',semantic_version:'20260921.manager-semantic.r3.v1',
    target_trade_date:date,input_identity:'b'.repeat(64),stocks:[],focus_symbols:[],company_events:[],rejected_relations:[],
    briefing:{},themes:[],materials:[],gaps:[gap],
    lanes:['STAGE','CATALYST','CLOSE'].map(lane=>({lane,owner:'synthetic',state:'UNVERIFIED',target_date:date,
      stock_count:null,last_attempt_at:null,last_success_at:null,next_plan:null,failure_reasons:[]})),
    summary:{stock_count:0,relation_count:0,theme_count:0,reused_material_count:0,formal_recommendation_count:0},
    research_attention:attention,selection_diagnostics:{schema_version:'v4.manager_research.selection_diagnostics.v1',
      target_trade_date:date,status:'PARTIAL',formal_selection:formal,
      membership:{status:'CANNOT_CONFIRM',target_trade_date:date,identity:null,codes:[],gaps:[gap],...safety},
      candidate_scope:'RESEARCH_RELATIONS_NOT_FORMAL_CONNECT_SELECTION',candidates:[],candidate_count:0,gaps:[gap],...safety},...safety};
}
