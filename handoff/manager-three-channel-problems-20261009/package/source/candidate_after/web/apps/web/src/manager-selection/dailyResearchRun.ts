/** First-screen read-only projection for the original daily research owners.
 * This module formats owner DTOs only: it creates no selection, ranking, or
 * US-to-HK membership rules.
 */
import type { JsonObject, ManagerWorkspace, ResearchExecutionContext, UsDailyMappingRun } from '../api/managerWorkspace.js';
import type { WorkspaceDateBindings } from './dailyChannels.js';

export type DailyResearchBindings = WorkspaceDateBindings;
export type PlanReadbackState = 'VERIFIED_SAVED' | 'NOT_MATERIALIZED' | 'READBACK_UNVERIFIED';

export interface PlanReadbackProjection {
  status: PlanReadbackState;
  statusLabel: string;
  targetDate: string;
  runId: string | null;
  sha256: string | null;
  generatedAt: string | null;
  readAt: string | null;
  executionLabel: string;
  latestAttempt: JsonObject | null;
  reason: string | null;
}

export interface UsDailyProjection {
  status: string;
  statusLabel: string;
  targetDate: string;
  usSessionDate: string | null;
  researchCutoff: string | null;
  matchedCount: number | null;
  coverageLabel: string;
  executionLabel: string;
  rows: JsonObject[];
  runId: string | null;
  artifactSha256: string | null;
  readbackStatus: string;
  readAt: string | null;
  owner: string | null;
  executionContext: ResearchExecutionContext | null;
  sourceIdentity: JsonObject | null;
  gaps: string[];
}

export interface DailyResearchSummary {
  plan: PlanReadbackProjection;
  us: UsDailyProjection;
}

const object = (raw: unknown): JsonObject => raw && typeof raw === 'object' && !Array.isArray(raw)
  ? raw as JsonObject : {};
const array = (raw: unknown): JsonObject[] => Array.isArray(raw)
  ? raw.filter(row => !!row && typeof row === 'object' && !Array.isArray(row)) as JsonObject[] : [];
const valueText = (raw: unknown, fallback = '未提供'): string =>
  typeof raw === 'string' && raw.trim() ? raw : fallback;
const dayText = (raw: unknown): string => typeof raw === 'string' && /^\d{8}$/.test(raw)
  ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : valueText(raw);
const countText = (raw: unknown): string => typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= 0
  ? String(raw) : '未知';
const isHash = (raw: unknown): raw is string => typeof raw === 'string' && /^[0-9a-f]{64}$/.test(raw);
const isRun = (raw: unknown): raw is string => typeof raw === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$/.test(raw);
const isAwareTime = (raw: unknown): raw is string => typeof raw === 'string' &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) &&
  Number.isFinite(Date.parse(raw));
const epoch = (raw: unknown): number | null => isAwareTime(raw) ? Date.parse(raw) : null;

const planStatuses: Record<string, string> = {
  CURRENT: '当前读取与已保存计划一致',
  ALREADY_MATERIALIZED: '原计划产物已存在并重新核验',
  PRESERVED_SCHEDULED_PREOPEN: '保留原盘前计划产物',
  NOT_MATERIALIZED: '目标日没有已保存计划产物',
  STALE_INPUTS_CHANGED: '来源已变化，保存计划不再对应当前输入',
  PLAN_AFTER_READ_CUTOFF: '保存计划晚于本次读取截止时点',
  OWNER_ATTEMPT_UNVERIFIED: '原 owner 尝试回执未核验',
  READBACK_FAILED: '保存计划读回失败',
};
const usStatuses: Record<string, string> = {
  NOT_RUN: '尚无日常映射运行', FAILED: '日常映射运行失败', INPUT_MISSING: '日常映射输入缺失',
  CANNOT_CONFIRM: '日常映射状态未确认', PARTIAL: '日常映射部分完成', COMPLETED: '日常映射已完成',
  VALID_EMPTY: '来源已核，当前关系范围内为零匹配',
};

export function researchExecutionLabel(raw: unknown): string {
  const context = object(raw) as Partial<ResearchExecutionContext>;
  const trigger = context.trigger_kind;
  const timing = context.timing;
  if (timing === 'RETROSPECTIVE') return '事后回看；按当前原始证据读数，不能标作盘前已知。';
  if (trigger === 'SCHEDULED' && timing === 'ON_TIME')
    return '原 owner 记录：调度触发、按时执行；自然时段验收未核实。';
  if (trigger === 'SCHEDULED' && timing === 'LATE_CATCHUP') return '调度晚到续跑；自然时段验收未核实。';
  if (trigger === 'MANUAL' && timing === 'LATE_CATCHUP') return '人工晚到补算；自然时段验收未核实。';
  if (trigger === 'MANUAL') return '原 owner 记录：人工触发；不表示自然时段执行。';
  if (trigger === 'SCHEDULED') return '原 owner 记录：调度触发，执行时段未分类；自然时段验收未核实。';
  return '原 owner 未提供可核验的触发方式或执行时段。';
}

function verifiedPlanAttempt(workspace: JsonObject, product: JsonObject, readback: JsonObject | null): boolean {
  const date = String(workspace.target_trade_date || '');
  const runId = product.run_id;
  const sha = product.sha256;
  const input = workspace.input_identity;
  const generatedAt = epoch(product.generated_at);
  const attempt = object(workspace.workspace_plan_attempt);
  const productReadback = readback ?? object(product.run_readback);
  const productStatuses = ['CURRENT', 'ALREADY_MATERIALIZED', 'PRESERVED_SCHEDULED_PREOPEN'];
  if (!productStatuses.includes(String(product.status)) || product.consumed !== true ||
      product.original_owner !== 'ManagerResearchJobService.refresh_workspace_plan' ||
      !isRun(runId) || !isHash(sha) || !isAwareTime(product.generated_at) ||
      productReadback.status !== 'VERIFIED' || productReadback.target_trade_date !== date ||
      productReadback.run_id !== runId || productReadback.artifact_sha256 !== sha ||
      productReadback.input_identity !== input || productReadback.owner !== 'ManagerResearchJobService.refresh_workspace_plan' ||
      !isAwareTime(productReadback.read_at) || !isRun(productReadback.owner_attempt_run_id) ||
      productReadback.owner_attempt_run_id !== runId || !isHash(productReadback.owner_attempt_sha256) ||
      !['SUCCEEDED', 'SUCCEEDED_EMPTY', 'PARTIAL'].includes(String(productReadback.owner_attempt_state)) ||
      !isAwareTime(productReadback.owner_finished_at)) return false;
  const readAt = epoch(productReadback.read_at);
  const finishedAt = epoch(productReadback.owner_finished_at);
  if (generatedAt === null || readAt === null || finishedAt === null || readAt < generatedAt || finishedAt < generatedAt)
    return false;
  if (isRun(attempt.run_id) && attempt.run_id === runId) {
    return attempt.target_trade_date === date && attempt.input_identity === input &&
      attempt.owner === 'ManagerResearchJobService.refresh_workspace_plan' &&
      attempt.sha256 === productReadback.owner_attempt_sha256 &&
      ['SUCCEEDED', 'SUCCEEDED_EMPTY', 'PARTIAL'].includes(String(attempt.state));
  }
  // The exact sealed same-run owner attempt may be summarized by the backend
  // readback even when latest.json points to a different later attempt.
  return true;
}

export function projectPlanReadback(workspaceRaw: unknown, bindings: DailyResearchBindings): PlanReadbackProjection {
  const workspace = object(workspaceRaw);
  const product = object(workspace.plan_product);
  const readback = product.run_readback && typeof product.run_readback === 'object'
    ? object(product.run_readback) : null;
  const latest = workspace.workspace_plan_attempt && typeof workspace.workspace_plan_attempt === 'object'
    ? object(workspace.workspace_plan_attempt) : null;
  const status = String(product.status || 'NOT_MATERIALIZED');
  const target = bindings.plan_date;
  let projectionStatus: PlanReadbackState = 'READBACK_UNVERIFIED';
  if (workspace.target_trade_date === target && workspace.plan_product !== undefined &&
      (status === 'NOT_MATERIALIZED' || status === 'DYNAMIC_PREVIEW' && product.consumed === false))
    projectionStatus = 'NOT_MATERIALIZED';
  else if (workspace.target_trade_date === target && verifiedPlanAttempt(workspace, product, readback))
    projectionStatus = 'VERIFIED_SAVED';
  const readAt = readback && isAwareTime(readback.read_at) ? readback.read_at : null;
  const kind = product.execution_kind;
  const context = product.execution_context;
  const result: PlanReadbackProjection = {
    status: projectionStatus,
    statusLabel: projectionStatus === 'VERIFIED_SAVED'
      ? '保存产物已读回核验'
      : projectionStatus === 'NOT_MATERIALIZED'
        ? '目标日没有已保存计划产物'
        : planStatuses[status] || '保存产物返回，但与原 owner 回执未能核对',
    targetDate: target,
    runId: isRun(product.run_id) ? product.run_id : null,
    sha256: isHash(product.sha256) ? product.sha256 : null,
    generatedAt: isAwareTime(product.generated_at) ? product.generated_at : null,
    readAt,
    executionLabel: context ? researchExecutionLabel(context) : kind === 'SCHEDULED_PREOPEN'
      ? '原 owner 记录盘前计划类型；自然时段验收仍未核实。'
      : kind === 'MANUAL_REFRESH' ? '原 owner 记录人工计划刷新；不表示自然时段执行。'
        : '原计划触发/执行信息未提供。',
    latestAttempt: latest,
    reason: typeof product.reason === 'string' ? product.reason : null,
  };
  return result;
}

function usProjection(daily: UsDailyMappingRun | undefined, bindings: DailyResearchBindings): UsDailyProjection {
  const run = (daily || {}) as unknown as JsonObject;
  const coverage = object(run.coverage);
  const readback = object(run.run_readback);
  const execution = run.execution_context && typeof run.execution_context === 'object'
    ? run.execution_context as ResearchExecutionContext : null;
  const matchedCount = typeof coverage.matched_hk_relation_count === 'number' &&
      Number.isSafeInteger(coverage.matched_hk_relation_count) && coverage.matched_hk_relation_count >= 0
    ? coverage.matched_hk_relation_count : null;
  return {
    status: typeof run.status === 'string' ? run.status : 'CANNOT_CONFIRM',
    statusLabel: usStatuses[String(run.status)] || '日常映射状态未确认',
    targetDate: bindings.plan_date,
    usSessionDate: typeof run.us_session_date === 'string' ? run.us_session_date : null,
    researchCutoff: typeof run.research_cutoff === 'string' ? run.research_cutoff : null,
    matchedCount,
    coverageLabel: `已审阅关系范围 ${countText(coverage.reviewed_us_symbol_count)} 个；配置美股范围 ${countText(coverage.configured_us_universe_count)} 只；可用美股范围 ${countText(coverage.available_us_universe_count)} 只；匹配港股关系 ${countText(coverage.matched_hk_relation_count)} 条；匹配美股 ${countText(coverage.matched_us_symbol_count)} 只。此来源不代表全市场。`,
    executionLabel: researchExecutionLabel(execution),
    rows: array(run.matches),
    runId: isRun(run.run_id) ? run.run_id : null,
    artifactSha256: isHash(run.artifact_sha256) ? run.artifact_sha256 : null,
    readbackStatus: String(readback.status || 'CANNOT_CONFIRM'),
    readAt: isAwareTime(readback.read_at) ? readback.read_at : null,
    owner: typeof readback.owner === 'string' ? readback.owner : null,
    executionContext: execution,
    sourceIdentity: run.source_identity && typeof run.source_identity === 'object'
      ? object(run.source_identity) : null,
    gaps: Array.isArray(run.gaps) ? run.gaps.filter((gap): gap is string => typeof gap === 'string') : [],
  };
}

export function projectDailyResearchSummary(workspaceRaw: unknown, bindings: DailyResearchBindings): DailyResearchSummary {
  const workspace = object(workspaceRaw);
  const mapping = object(workspace.us_mapping_research);
  const candidate = mapping.daily_run && typeof mapping.daily_run === 'object'
    ? mapping.daily_run as unknown as UsDailyMappingRun : undefined;
  const datesMatch = workspace.target_trade_date === bindings.plan_date &&
    mapping.target_trade_date === bindings.plan_date && candidate?.target_trade_date === bindings.plan_date;
  const daily = datesMatch ? candidate : undefined;
  return { plan: projectPlanReadback(workspace, bindings), us: usProjection(daily, bindings) };
}

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, content = '', className = ''): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag); node.textContent = content; node.className = className; return node;
};
const dateLabel = (raw: unknown): string => typeof raw === 'string' && /^\d{8}$/.test(raw)
  ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : valueText(raw);

function identityDetails(title: string, value: unknown): HTMLElement {
  const details = el('details'); details.append(el('summary', title));
  const pre = el('pre', JSON.stringify(value ?? {}, null, 2));
  details.append(pre); return details;
}

function renderPlan(host: HTMLElement, workspace: JsonObject, summary: PlanReadbackProjection): void {
  const box = el('section'); box.dataset.planReadback = ''; box.setAttribute('aria-label', '计划保存产物读回');
  box.append(el('h4', '计划保存状态'), el('p', `${summary.targetDate} · ${summary.statusLabel}`));
  if (summary.runId) box.append(el('p', `保存运行 ${summary.runId} · 生成于 ${summary.generatedAt || '时点未核'} · 读回于 ${summary.readAt || '时点未核'}`));
  if (summary.sha256) box.append(el('p', `保存产物 SHA256 ${summary.sha256}`));
  box.append(el('p', summary.executionLabel));
  if (summary.latestAttempt) {
    const attempt = summary.latestAttempt;
    const failed = attempt.state === 'FAILED';
    box.append(el('p', failed
      ? `最近尝试失败（${valueText(attempt.run_id)}）：${Array.isArray(attempt.failure_reasons) ? attempt.failure_reasons.join('；') : '失败原因未提供'}。该状态与上方已保存产物分开。`
      : `最近尝试 ${valueText(attempt.state, '状态未提供')} · ${valueText(attempt.run_id)}。`));
  }
  box.append(identityDetails('计划 owner、同一 immutable run 的尝试回执与当前读回详情', {
    product: object(workspace.plan_product),
    exact_run_readback: object(object(workspace.plan_product).run_readback),
    latest_attempt: summary.latestAttempt,
  }));
  host.append(box);
}

function renderUs(host: HTMLElement, summary: UsDailyProjection): void {
  const box = el('section'); box.dataset.usDailyRun = ''; box.setAttribute('aria-label', '美股到港股业务关系日常映射');
  box.append(el('h4', '美股 → 港股业务关系日常映射（独立于港股通资格）'));
  box.append(el('p', `${summary.statusLabel} · 目标港股日 ${dateLabel(summary.targetDate)} · 美股来源日 ${dateLabel(summary.usSessionDate)} · 来源 cutoff ${summary.researchCutoff || '未提供'}`));
  box.append(el('p', summary.coverageLabel), el('p', summary.executionLabel));
  box.append(el('p', `日常运行 ${summary.runId || '未提供'} · owner读回 ${summary.readbackStatus} · 读回时点 ${summary.readAt || '未提供'}`));
  if (summary.status === 'VALID_EMPTY' && summary.matchedCount === 0)
    box.append(el('p', '来源读取和回读已核；在该有限已审关系范围内评估为零匹配。'));
  else if (summary.matchedCount === null)
    box.append(el('p', '匹配数量未知；不能把当前空行解释为零匹配。'));
  if (summary.rows.length) {
    for (const row of summary.rows) {
      const article = el('article', '', 'us-daily-match');
      article.dataset.usSymbol = valueText(row.us_symbol, '');
      article.append(el('h5', `${valueText(row.us_symbol, '美股代码未提供')} → ${valueText(row.hk_symbol, '港股代码未提供')} ${valueText(row.hk_name)}`),
        el('p', `原关系理由：${valueText(row.reason, '原理由未提供/待核')}`),
        el('p', `原关系类型 ${valueText(row.relationship_type)} · 状态 ${valueText(row.maturity)} · 美股来源日 ${dateLabel(row.session_date)} · 目标日资格 ${valueText(row.target_date_eligibility)}`));
      for (const limitation of Array.isArray(row.limitations) ? row.limitations : [])
        if (typeof limitation === 'string') article.append(el('p', `限制：${limitation}`));
      article.append(identityDetails('该关系行的来源引用', {
        run_id: summary.runId,
        artifact_sha256: summary.artifactSha256,
        relationship_artifact_sha256: row.reviewed_relation_artifact_sha256,
        source_identity: summary.sourceIdentity,
        official_sources: row.official_sources,
        target_date_eligibility: row.target_date_eligibility,
      }));
      box.append(article);
    }
  }
  if (summary.gaps.length) {
    const details = el('details'); details.append(el('summary', `日常映射缺口（${summary.gaps.length}）`));
    for (const gap of summary.gaps) details.append(el('p', gap));
    box.append(details);
  }
  box.append(identityDetails('US daily owner execution context 与 run readback', {
    execution_context: summary.executionContext,
    run_id: summary.runId,
    artifact_sha256: summary.artifactSha256,
    owner: summary.owner,
    readback_status: summary.readbackStatus,
    read_at: summary.readAt,
    natural_run_verified: summary.executionContext?.natural_run_verified ?? null,
    run_readback: {
      status: summary.readbackStatus, owner: summary.owner, read_at: summary.readAt,
      target_trade_date: summary.targetDate, run_id: summary.runId, artifact_sha256: summary.artifactSha256,
    },
  }));
  host.append(box);
}

/** Render owner readbacks as literal text; never merge or reorder their rows. */
export function renderDailyResearchRun(host: HTMLElement, workspaceRaw: ManagerWorkspace | JsonObject | unknown,
  bindings: DailyResearchBindings): void {
  host.replaceChildren();
  const workspace = object(workspaceRaw);
  const summary = projectDailyResearchSummary(workspace, bindings);
  const section = el('section'); section.dataset.dailyResearchRun = '';
  section.setAttribute('aria-label', '每日研究结果与保存计划回执');
  renderPlan(section, workspace, summary.plan);
  renderUs(section, summary.us);
  host.append(section);
}

/** Full page cache admission is bound to every explicit display date and view. */
export function mayKeepWorkspaceResult(args: {
  current: ManagerWorkspace | null;
  loadedBindings: WorkspaceDateBindings | null;
  loadedView: 'auto' | 'dynamic' | null;
  requestedBindings: WorkspaceDateBindings;
  requestedView: 'auto' | 'dynamic';
}): boolean {
  const read = object(args.current?.read_context);
  const sameBindings = !!args.loadedBindings &&
    args.loadedBindings.plan_date === args.requestedBindings.plan_date &&
    args.loadedBindings.selection_date === args.requestedBindings.selection_date &&
    args.loadedBindings.announcement_date === args.requestedBindings.announcement_date;
  return !!args.current && sameBindings && args.loadedView === args.requestedView &&
    ['VERIFIED', 'VERIFIED_WITH_GAPS'].includes(String(read.status));
}

export function workspaceRequestStillCurrent(args: {
  disposed: boolean;
  currentSequence: number;
  requestSequence: number;
  requestedBindings: WorkspaceDateBindings;
  currentBindings: WorkspaceDateBindings;
  requestedView: 'auto' | 'dynamic';
  currentView: 'auto' | 'dynamic';
}): boolean {
  return !args.disposed && args.currentSequence === args.requestSequence &&
    args.requestedView === args.currentView &&
    args.requestedBindings.plan_date === args.currentBindings.plan_date &&
    args.requestedBindings.selection_date === args.currentBindings.selection_date &&
    args.requestedBindings.announcement_date === args.currentBindings.announcement_date;
}
