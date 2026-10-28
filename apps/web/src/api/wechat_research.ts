/** Stage A only: exact archive references, not research candidates or trading data. */
const BASE = '/api/v3/research/wechat/materials';
const SCHEMA = 'v4.wechat_materials.stage_a.v1';
const MENTIONS_SCHEMA = 'v4.wechat_mentions.stage_a.v1';
const SHA = /^[0-9a-f]{64}$/;
export type DateBasis = 'article' | 'received';
type Safety = { RESEARCH_ONLY: true; WATCH_ONLY: true; NO_BUY_GATE: true;
  production_allowed: false; buy_gate_updated: false; orders_sent: false };
export interface WechatMaterial extends Safety {
  record_id: string;
  article: { article_id: string | null; title: string | null; account: string | null;
    biz: string | null; url: string | null; article_date: string | null;
    published_at: string | null; metadata_origin: string };
  identity: { package_id: string | null; source_run_id: string | null; input_digest: string | null;
    return_id: string | null; receipt_sha256: string; package_sha256: string | null;
    package_sha256_status: string; manifest_sha256: string | null };
  states: { archive: string; input_binding: string; structure: string; research_review: string };
  receipt_claims: { archive: string; structure: string; input_binding_valid: boolean;
    semantic_research_accepted: boolean; independent_review_scope: string[] };
  received_at: string | null; indexed_at: string; available_at: null;
  missing_artifacts: string[]; cannot_confirm: string[];
  source_status: string; origin: string; archive_owner: string; write_policy: string;
}
export interface WechatArtifact {
  artifact_id: string; filename: string; sha256: string; bytes: number;
  kind: 'CHAT_RETURN' | 'FROZEN_INPUT'; status: string;
}
export interface WechatList extends Safety {
  schema_version: typeof SCHEMA; status: 'READY' | 'NOT_CONFIGURED' | 'NOT_INDEXED';
  query: { date: string | null; date_basis: DateBasis; q: string; limit: number };
  timezone: 'Asia/Shanghai'; items: WechatMaterial[]; total: number; returned: number;
  next_cursor: string | null; index_revision: string | null;
}
export interface WechatDetail extends Safety {
  schema_version: typeof SCHEMA; status: 'READY' | 'PARTIAL' | 'QUARANTINED';
  material: WechatMaterial; report: { status: string; content: string | null };
  artifacts: WechatArtifact[];
}
export type MaterialQuery = { date?: string | null; date_basis?: DateBasis; q?: string;
  cursor?: string | null; limit?: number };
export type MentionMarket = 'A' | 'BJ' | 'HK';
export interface WechatMention {
  market: MentionMarket; code: string; name: string; entity_id: string; entity_ids: string[];
  mapping_status: string; mapping_statuses: string[];
  source_named_or_derived: string; source_named_or_derived_values: string[];
  listing_origin: string; listing_origins: string[]; source_count: number;
  source_indexes: string[]; source_index_count: number; source_names: string[];
  claim_context: string; claim_contexts: string[];
}
export interface WechatMentionCounts {
  rows: number; listings: number; issuers: number;
  market_rows: Record<MentionMarket, number>; market_listings: Record<MentionMarket, number>;
  source_named_rows: number; source_named_listings?: number; source_named_entities?: number;
  supplemental_listing_rows: number;
}
export interface WechatMentionProvenance {
  record_id: string; artifact_id: 'mentions'; filename: string; sha256: string;
  bytes: number; status: string;
}
export interface WechatMentionList extends Safety {
  schema_version: typeof MENTIONS_SCHEMA;
  status: 'READY' | 'MISSING' | 'NOT_CONFIGURED' | 'NOT_INDEXED';
  query: { record_id: string | null; date: string | null; date_basis: 'article'; market: MentionMarket | null; q: string; limit: number };
  date_basis: 'article'; article_date: string | null; timezone: 'Asia/Shanghai';
  record_id: string | null; record_ids: string[]; material: WechatMaterial | null; materials: WechatMaterial[];
  items: WechatMention[]; rows: WechatMention[]; total: number; returned: number;
  next_cursor: string | null; counts: WechatMentionCounts | null; market_totals?: Record<MentionMarket, number>;
  provenance: WechatMentionProvenance[]; summary_status: string | string[];
  missing_artifacts?: string[]; cannot_confirm: string[]; index_revision?: string;
}
function fail(): never { throw new Error('公众号响应合同或版本不一致；未展示该响应。'); }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
  return value as Record<string, unknown>;
}
function strings(value: unknown): boolean { return Array.isArray(value) && value.every(x => typeof x === 'string'); }
function nullable(value: unknown): boolean { return value === null || typeof value === 'string'; }
function checkSafety(value: Record<string, unknown>): void {
  if (value.RESEARCH_ONLY !== true || value.WATCH_ONLY !== true || value.NO_BUY_GATE !== true ||
    value.production_allowed !== false || value.buy_gate_updated !== false || value.orders_sent !== false) fail();
}
function checkMaterial(value: unknown): WechatMaterial {
  const v = object(value); checkSafety(v);
  if (typeof v.record_id !== 'string' || !SHA.test(v.record_id) || v.available_at !== null ||
    !nullable(v.received_at) || typeof v.indexed_at !== 'string' || !strings(v.missing_artifacts) || !strings(v.cannot_confirm)) fail();
  const article = object(v.article), identity = object(v.identity), states = object(v.states), claims = object(v.receipt_claims);
  for (const key of ['article_id','title','account','biz','url','article_date','published_at']) if (!nullable(article[key])) fail();
  for (const key of ['package_id','source_run_id','input_digest','return_id','package_sha256','manifest_sha256']) if (!nullable(identity[key])) fail();
  if (typeof identity.receipt_sha256 !== 'string' || !SHA.test(identity.receipt_sha256)) fail();
  for (const key of ['archive','input_binding','structure','research_review']) if (typeof states[key] !== 'string') fail();
  if (!strings(claims.independent_review_scope)) fail();
  return value as WechatMaterial;
}
/** Original article link only. Report links/images remain inert text. */
export function safeArticleUrl(value: unknown): string {
  if (typeof value !== 'string' || /[\s\\\u0000-\u001f\u007f]/.test(value)) return '';
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && url.hostname === 'mp.weixin.qq.com' &&
      !url.username && !url.password ? value : '';
  } catch { return ''; }
}
export function wechatArtifactUrl(recordId: string, artifactId: string): string {
  if (!SHA.test(recordId) || !/^(report|coverage|mentions|unmapped|summary|source_[A-Z0-9_]+)$/.test(artifactId)) fail();
  return `${BASE}/${recordId}/artifacts/${encodeURIComponent(artifactId)}`;
}
async function fetchJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw new DOMException('已取消', 'AbortError');
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, 30000);
  try {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('公众号接口未返回 JSON；请确认当前运行版本，未使用旧页面替代。');
    }
    const body: unknown = await response.json();
    if (!response.ok) {
      const detail = object(body).detail;
      const code = detail && typeof detail === 'object' ? (detail as Record<string, unknown>).code : null;
      throw new Error(`公众号读取失败：${typeof code === 'string' ? code : `HTTP ${response.status}`}；未回退其他版本。`);
    }
    return body;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}
export async function loadWechatMaterials(query: MaterialQuery, signal?: AbortSignal): Promise<WechatList> {
  const expected = { date: query.date || null, date_basis: query.date_basis || 'article',
    q: (query.q || '').trim(), limit: query.limit ?? 20 };
  const params = new URLSearchParams({ date_basis: expected.date_basis, q: expected.q, limit: String(expected.limit) });
  if (expected.date) params.set('date', expected.date);
  if (query.cursor) params.set('cursor', query.cursor);
  const body = object(await fetchJson(`${BASE}?${params}`, signal)); checkSafety(body);
  const actual = object(body.query);
  if (body.schema_version !== SCHEMA || !['READY','NOT_CONFIGURED','NOT_INDEXED'].includes(String(body.status)) ||
    body.timezone !== 'Asia/Shanghai' || Object.entries(expected).some(([k,v]) => actual[k] !== v) ||
    !Array.isArray(body.items) || !Number.isSafeInteger(body.total) || !Number.isSafeInteger(body.returned) ||
    body.returned !== body.items.length || Number(body.total) < body.items.length || body.items.length > expected.limit ||
    !nullable(body.next_cursor) || !nullable(body.index_revision)) fail();
  const items = body.items.map(checkMaterial);
  if (new Set(items.map(x => x.record_id)).size !== items.length) fail();
  return body as unknown as WechatList;
}
export async function loadWechatMaterial(recordId: string, signal?: AbortSignal): Promise<WechatDetail> {
  if (!SHA.test(recordId)) fail();
  const body = object(await fetchJson(`${BASE}/${recordId}`, signal)); checkSafety(body);
  const material = checkMaterial(body.material), report = object(body.report);
  if (body.schema_version !== SCHEMA || !['READY','PARTIAL','QUARANTINED'].includes(String(body.status)) ||
    material.record_id !== recordId || typeof report.status !== 'string' || !nullable(report.content) || !Array.isArray(body.artifacts)) fail();
  for (const item of body.artifacts) {
    const a = object(item);
    if (typeof a.artifact_id !== 'string' || typeof a.filename !== 'string' || typeof a.sha256 !== 'string' ||
      !SHA.test(a.sha256) || !Number.isSafeInteger(a.bytes) || Number(a.bytes) < 0 || typeof a.status !== 'string') fail();
    wechatArtifactUrl(recordId, a.artifact_id);
  }
  if (body.status === 'QUARANTINED' && report.content !== null) fail();
  return body as unknown as WechatDetail;
}

function checkMention(value: unknown): WechatMention {
  const v = object(value);
  const sourceCount = Number(v.source_count);
  const sourceIndexCount = Number(v.source_index_count);
  const sourceIndexes = v.source_indexes;
  if (!['A', 'BJ', 'HK'].includes(String(v.market)) || typeof v.code !== 'string' ||
    typeof v.name !== 'string' || typeof v.entity_id !== 'string' || !strings(v.entity_ids) ||
    typeof v.mapping_status !== 'string' || !strings(v.mapping_statuses) ||
    typeof v.source_named_or_derived !== 'string' || !strings(v.source_named_or_derived_values) ||
    typeof v.listing_origin !== 'string' || !strings(v.listing_origins) ||
    !Number.isSafeInteger(sourceCount) || sourceCount < 1 ||
    !strings(sourceIndexes) || !Number.isSafeInteger(sourceIndexCount) || sourceIndexCount < 1 ||
    !strings(v.source_names) || typeof v.claim_context !== 'string' || !strings(v.claim_contexts) ||
    Object.keys(v).some(key => ['rank', 'score', 'pool_score', 'recommendation_status'].includes(key))) fail();
  if (sourceIndexCount !== (sourceIndexes as string[]).length || sourceCount < sourceIndexCount) fail();
  return value as WechatMention;
}

function checkMentionCounts(value: unknown): WechatMentionCounts {
  const v = object(value);
  const marketRows = object(v.market_rows), marketListings = object(v.market_listings);
  for (const market of ['A', 'BJ', 'HK']) {
    if (!Number.isSafeInteger(marketRows[market]) || !Number.isSafeInteger(marketListings[market]) ||
      Number(marketRows[market]) < 0 || Number(marketListings[market]) < 0) fail();
  }
  for (const key of ['rows', 'listings', 'issuers', 'source_named_rows', 'source_named_listings',
    'source_named_entities', 'supplemental_listing_rows']) {
    if (!Number.isSafeInteger(v[key]) || Number(v[key]) < 0) fail();
  }
  return value as WechatMentionCounts;
}

function checkMentionProvenance(value: unknown): WechatMentionProvenance {
  const v = object(value);
  if (typeof v.record_id !== 'string' || !SHA.test(v.record_id) || v.artifact_id !== 'mentions' ||
    typeof v.filename !== 'string' || typeof v.sha256 !== 'string' || !SHA.test(v.sha256) ||
    !Number.isSafeInteger(v.bytes) || Number(v.bytes) < 1 || typeof v.status !== 'string') fail();
  return value as WechatMentionProvenance;
}

export type MentionQuery = { date: string; market?: MentionMarket | null; q?: string;
  cursor?: string | null; limit?: number };
export async function loadWechatMentions(query: MentionQuery, signal?: AbortSignal): Promise<WechatMentionList> {
  const expected = { record_id: null, date: query.date, date_basis: 'article' as const,
    market: query.market || null, q: (query.q || '').trim(), limit: query.limit ?? 50 };
  const params = new URLSearchParams({ date: expected.date, date_basis: expected.date_basis,
    q: expected.q, limit: String(expected.limit) });
  if (expected.market) params.set('market', expected.market);
  if (query.cursor) params.set('cursor', query.cursor);
  const body = object(await fetchJson(`${BASE}/mentions?${params}`, signal)); checkSafety(body);
  const actual = object(body.query);
  if (body.schema_version !== MENTIONS_SCHEMA ||
    !['READY', 'MISSING', 'NOT_CONFIGURED', 'NOT_INDEXED'].includes(String(body.status)) ||
    body.date_basis !== 'article' || body.timezone !== 'Asia/Shanghai' ||
    Object.entries(expected).some(([key, value]) => actual[key] !== value) ||
    !Array.isArray(body.items) || !Array.isArray(body.rows) || body.rows.length !== body.items.length ||
    !Number.isSafeInteger(body.total) || !Number.isSafeInteger(body.returned) ||
    body.returned !== body.items.length || Number(body.total) < body.items.length ||
    body.items.length > expected.limit || !nullable(body.next_cursor) ||
    !nullable(body.article_date) || !strings(body.record_ids) || !Array.isArray(body.materials) ||
    !Array.isArray(body.provenance) || !strings(body.cannot_confirm) || !nullable(body.summary_status) &&
      !Array.isArray(body.summary_status)) fail();
  if (body.record_id !== null && (typeof body.record_id !== 'string' || !SHA.test(body.record_id))) fail();
  if (body.material !== null) checkMaterial(body.material);
  for (const material of body.materials) checkMaterial(material);
  for (const item of body.items) checkMention(item);
  for (const item of body.provenance) checkMentionProvenance(item);
  if (body.counts !== null) checkMentionCounts(body.counts);
  return body as unknown as WechatMentionList;
}
