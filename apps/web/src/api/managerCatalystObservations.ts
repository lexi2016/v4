/** Independent research observations; never a Stage/BUY candidate contract. */
export interface CatalystSource {
  source_id: string; url: string; sha256: string; retrieved_at: string;
  representation: string; retrieval_method: string; verification_reference: string;
}
export interface CatalystCard {
  card_id: string; title: string; symbol: string | null; name: string;
  themes: string[]; published_date: string; published_at: string | null;
  time_precision: string; available_at: string; retrieved_at: string;
  source_url: string; source_refs: CatalystSource[]; evidence_quote: string;
  relationship_type: 'DIRECT' | 'INDUSTRY_INFERENCE' | 'UNMAPPED';
  mapping_reason: string; temporal_classification: string; captured_at_target: boolean;
  volume_condition: 'UNKNOWN'; price_position: 'UNKNOWN'; qualified: false;
  research_role: 'CATALYST_OBSERVATION_ONLY';
}
export interface CatalystObservations {
  schema_version: 'v4.manager_research.catalyst_observations.v1';
  target_trade_date: string; status: 'NOT_MATERIALIZED' | 'EMPTY' | 'READY';
  cards: CatalystCard[]; gaps: string[]; can_refresh: true;
  stage_dependency: false; quote_dependency: false; generated_at: string | null;
  RESEARCH_ONLY: true; production_allowed: false; buy_gate_updated: false; orders_sent: false;
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('CATALYST_OBJECT_INVALID');
  return value as Record<string, unknown>;
}
function safe(value: Record<string, unknown>): void {
  if (value.RESEARCH_ONLY !== true || value.production_allowed !== false || value.buy_gate_updated !== false || value.orders_sent !== false)
    throw new Error('CATALYST_SAFETY_INVALID');
}
function url(value: unknown): void {
  if (typeof value !== 'string') throw new Error('CATALYST_URL_MISSING');
  const u = new URL(value);
  if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password) throw new Error('CATALYST_URL_INVALID');
}
function timestamp(value: unknown): void {
  if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value)))
    throw new Error('CATALYST_TIME_INVALID');
}
export function validateCatalystObservations(raw: unknown, date: string): CatalystObservations {
  const value = object(raw); safe(value);
  if (value.schema_version !== 'v4.manager_research.catalyst_observations.v1' || value.target_trade_date !== date ||
      value.can_refresh !== true || value.stage_dependency !== false || value.quote_dependency !== false ||
      !['READY', 'EMPTY', 'NOT_MATERIALIZED'].includes(String(value.status)) || !Array.isArray(value.cards) || !Array.isArray(value.gaps))
    throw new Error('CATALYST_ENVELOPE_INVALID');
  if (value.gaps.some(x => typeof x !== 'string')) throw new Error('CATALYST_GAPS_INVALID');
  const ids = new Set<string>();
  for (const rawCard of value.cards) {
    const c = object(rawCard); safe(c);
    if (typeof c.card_id !== 'string' || ids.has(c.card_id) || typeof c.title !== 'string' || typeof c.name !== 'string' ||
        (c.symbol !== null && (typeof c.symbol !== 'string' || !/^HK\.\d{5}$/.test(c.symbol))) ||
        c.volume_condition !== 'UNKNOWN' || c.price_position !== 'UNKNOWN' || c.qualified !== false ||
        c.research_role !== 'CATALYST_OBSERVATION_ONLY' || !['DIRECT', 'INDUSTRY_INFERENCE', 'UNMAPPED'].includes(String(c.relationship_type)) ||
        !['POST_HOC_RESEARCH', 'AFTER_CLOSE_RESEARCH', 'CAPTURED_AT_TARGET'].includes(String(c.temporal_classification)) ||
        c.captured_at_target !== (c.temporal_classification === 'CAPTURED_AT_TARGET') || typeof c.mapping_reason !== 'string' ||
        typeof c.published_date !== 'string' || !Array.isArray(c.themes) || c.themes.some(x => typeof x !== 'string') ||
        !Array.isArray(c.source_refs) || c.source_refs.length === 0) throw new Error('CATALYST_CARD_INVALID');
    ids.add(c.card_id); url(c.source_url); timestamp(c.available_at); timestamp(c.retrieved_at);
    if (c.published_at !== null) timestamp(c.published_at);
    for (const rawSource of c.source_refs) {
      const s = object(rawSource); url(s.url); timestamp(s.retrieved_at);
      if (typeof s.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(s.sha256) || typeof s.representation !== 'string')
        throw new Error('CATALYST_SOURCE_INVALID');
    }
  }
  if ((value.status === 'READY') !== (value.cards.length > 0)) throw new Error('CATALYST_STATUS_COUNT_MISMATCH');
  return value as unknown as CatalystObservations;
}
export async function requestCatalystObservations(date: string, refresh: boolean, signal: AbortSignal): Promise<CatalystObservations> {
  if (!/^\d{8}$/.test(date)) throw new Error('CATALYST_DATE_REQUIRED');
  const endpoint = '/api/v4/manager/research/catalyst-observations' + (refresh ? '/refresh' : '');
  const response = await fetch(`${endpoint}?date=${encodeURIComponent(date)}`, {
    method: refresh ? 'POST' : 'GET', signal, credentials: 'same-origin', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`CATALYST_HTTP_${response.status}`);
  return validateCatalystObservations(await response.json(), date);
}
