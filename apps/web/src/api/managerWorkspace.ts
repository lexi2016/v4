/** Read-only stock summary, not a ranking / BUY / trading instruction contract. */
import { object, parseWorkspaceResponse, validateAnnouncementReview } from "../contracts/managerWorkspaceValidation";
export { validateAnnouncementObservation, validateAnnouncementReview, validateManagerWorkspace } from "../contracts/managerWorkspaceValidation";
import type { AnnouncementObservation, AnnouncementReview, FormalConnectSelection, IndependentAnnouncementCard, IndependentAnnouncementObservations, JsonObject, ManagerWorkspace, ReboundScreen, ResearchAttention, ResearchAttentionCard, ResearchAttentionDecision, ResearchAttentionState, ResearchExecutionContext, ResearchExecutionTiming, ResearchInputDiagnostics, ResearchReadOnlyFlags, ResearchRunReadback, ResearchScopeDiagnostics, ResearchSelectionDecision, ResearchSelectionDecisionStatus, ResearchSelectionLedger, ResearchTriggerKind, SelectionDiagnostics, UsDailyMappingRun, UsMappingAssessmentState, UsMappingCard, UsMappingDiagnostics, UsMappingResearch, UsMappingSource, UsMarketAttention, UsRelationMaterialInput, UsReviewedMapping, UsSymbolAssessment, UsSymbolRelation, WorkspaceAction, WorkspaceLane, WorkspaceStock, WorkspaceView } from "../contracts/managerWorkspace";
export type { AnnouncementObservation, AnnouncementReview, FormalConnectSelection, IndependentAnnouncementCard, IndependentAnnouncementObservations, JsonObject, ManagerWorkspace, ReboundScreen, ResearchAttention, ResearchAttentionCard, ResearchAttentionDecision, ResearchAttentionState, ResearchExecutionContext, ResearchExecutionTiming, ResearchInputDiagnostics, ResearchReadOnlyFlags, ResearchRunReadback, ResearchScopeDiagnostics, ResearchSelectionDecision, ResearchSelectionDecisionStatus, ResearchSelectionLedger, ResearchTriggerKind, SelectionDiagnostics, UsDailyMappingRun, UsMappingAssessmentState, UsMappingCard, UsMappingDiagnostics, UsMappingResearch, UsMappingSource, UsMarketAttention, UsRelationMaterialInput, UsReviewedMapping, UsSymbolAssessment, UsSymbolRelation, WorkspaceAction, WorkspaceLane, WorkspaceStock, WorkspaceView } from "../contracts/managerWorkspace";
import { normalizedWorkspaceDay, validateDailyChannels, validateWorkspaceDateBindings,
  type DailyChannels, type WorkspaceDateBindings, type WorkspaceRequestDateBindings } from '../manager-selection/dailyChannels';
export type { WorkspaceDateBindings, WorkspaceRequestDateBindings } from '../manager-selection/dailyChannels';









































/** Every rendered action must reference the SAME retained issuer proposition.
 * Theme inference needs both theme and issuer support. Market levels keep their
 * existing strict provenance gate; this is not an alternate quote validator.
 */


/** Read context is a separate time/admission contract, never a cache trust flag. */


/** Read-only exact publication-day review returned by the existing owner GET. */





































// These are the existing Python native-relation roles, not new semantic statuses.





















































export async function requestManagerWorkspace(date: string, signal: AbortSignal, view: WorkspaceView = 'auto', bindings?: WorkspaceRequestDateBindings): Promise<ManagerWorkspace> {
  if (normalizedWorkspaceDay(date) !== date) throw new Error('WORKSPACE_DATE_REQUIRED');
  const query = new URLSearchParams({ date, view });
  if (bindings !== undefined) {
    if (!bindings || typeof bindings !== 'object' || Array.isArray(bindings)) throw new Error('WORKSPACE_DAILY_DATE_BINDING_INVALID');
    for (const key of ['selection_date', 'announcement_date'] as const) {
      if (bindings[key] === undefined) continue;
      const selected = normalizedWorkspaceDay(bindings[key]);
      if (selected === null) throw new Error('WORKSPACE_DAILY_DATE_BINDING_INVALID');
      query.set(key, selected);
    }
  }
  const response = await fetch(`/api/v4/manager/research/workspace?${query}`, {
    method: 'GET', signal, credentials: 'same-origin', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`WORKSPACE_HTTP_${response.status}`);
  const value=await parseWorkspaceResponse(response, date, bindings);
  const read=object(value.read_context); // an old backend cannot silently provide a historical dynamic view
  if ((view==='historical' && read.mode!=='HISTORICAL_AS_OF') ||
      (view==='dynamic' && read.mode!=='CURRENT_DYNAMIC_PREVIEW')) throw new Error('WORKSPACE_VIEW_MISMATCH');
  return value;
}

/** Exact publication-day review through the existing read-only announcement owner route. */
export async function requestManagerAnnouncements(date: string, signal: AbortSignal): Promise<AnnouncementReview> {
  if (!/^\d{8}$/.test(date)) throw new Error('ANNOUNCEMENT_DATE_REQUIRED');
  const response=await fetch(`/api/v4/manager/research/announcements?date=${encodeURIComponent(date)}`,{
    method:'GET',signal,credentials:'same-origin',cache:'no-store',
  });
  if(!response.ok)throw new Error(`ANNOUNCEMENT_HTTP_${response.status}`);
  let raw:unknown;
  try{raw=await response.json();}
  catch(error){if(error instanceof SyntaxError)throw new Error('ANNOUNCEMENT_RESPONSE_JSON_INVALID');throw error;}
  return validateAnnouncementReview(raw,date);
}

/** Explicit selected-publication-day update through the existing bounded owner POST. */
export async function refreshManagerAnnouncements(date: string, signal: AbortSignal): Promise<AnnouncementReview> {
  if (!/^\d{8}$/.test(date)) throw new Error('ANNOUNCEMENT_DATE_REQUIRED');
  const response=await fetch(`/api/v4/manager/research/announcements/refresh?date=${encodeURIComponent(date)}`,{
    method:'POST',signal,credentials:'same-origin',cache:'no-store',
  });
  if(!response.ok)throw new Error(`ANNOUNCEMENT_REFRESH_HTTP_${response.status}`);
  let raw:unknown;
  try{raw=await response.json();}
  catch(error){if(error instanceof SyntaxError)throw new Error('ANNOUNCEMENT_REFRESH_RESPONSE_JSON_INVALID');throw error;}
  return validateAnnouncementReview(raw,date);
}

/** Explicit user action: original owner reuses existing input, never a crawler. */
export async function refreshManagerWorkspace(date: string, signal: AbortSignal,
    bindings?: WorkspaceRequestDateBindings): Promise<ManagerWorkspace> {
  if (!/^\d{8}$/.test(date)) throw new Error('WORKSPACE_DATE_REQUIRED');
  const params = new URLSearchParams({date});
  if (bindings?.selection_date !== undefined) {
    const selection = normalizedWorkspaceDay(bindings.selection_date);
    if (!selection) throw new Error('WORKSPACE_SELECTION_DATE_INVALID');
    params.set('selection_date', selection);
  }
  if (bindings?.announcement_date !== undefined) {
    const announcement = normalizedWorkspaceDay(bindings.announcement_date);
    if (!announcement) throw new Error('WORKSPACE_ANNOUNCEMENT_DATE_INVALID');
    params.set('announcement_date', announcement);
  }
  const response = await fetch(`/api/v4/manager/research/workspace/refresh?${params.toString()}`, {
    method: 'POST', signal, credentials: 'same-origin', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`WORKSPACE_REFRESH_HTTP_${response.status}`);
  return await parseWorkspaceResponse(response, date, bindings);
}
