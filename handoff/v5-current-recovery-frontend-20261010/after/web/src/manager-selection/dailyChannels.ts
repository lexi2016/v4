/** Read-only projection of the existing owners' decisions. No selection or ranking rules live here. */
type RecordValue = Record<string, unknown>;
export interface WorkspaceDateBindings {
  plan_date: string; selection_date: string; announcement_date: string;
}
export interface WorkspaceRequestDateBindings {
  selection_date?: string; announcement_date?: string;
}
export type DailyChannelId = 'ANNOUNCEMENT' | 'HK_CONNECT' | 'OVERSOLD';
export type DailyChannelStatus = 'READY' | 'READY_EMPTY' | 'PARTIAL' | 'CANNOT_CONFIRM';
export interface DailyChannelRow extends RecordValue {
  symbol: string; name: string; reason: string | null;
  selection_status: 'SELECTED' | 'CONDITIONAL_WATCH' | 'NEAR_CONDITION';
  target_trade_date: string; data_date: string | null; run_id: string | null;
  generated_at: string | null; product_sha256: string | null; source_refs: RecordValue[];
}
export interface DailyChannel extends RecordValue {
  channel: DailyChannelId; owner: string; status: DailyChannelStatus;
  target_trade_date: string; selection_date: string; announcement_date: string;
  data_date: string | null; rows: DailyChannelRow[]; candidate_count: number | null;
  pending_count: number | null; watch_count?: number; gaps: string[]; dependencies: string[];
  run_id: string | null; generated_at: string | null; product_sha256: string | null;
  input_identity: string | null; execution_kind: string; natural_run_verified: false;
}
export interface DailyChannels extends RecordValue {
  schema_version: 'v4.manager_research.daily_channels.v1';
  date_bindings: WorkspaceDateBindings; channels: DailyChannel[]; selection_rules_unchanged: true;
}

const channelIds: DailyChannelId[] = ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'];
const channelNames: Record<DailyChannelId, string> = { ANNOUNCEMENT: '公告研究', HK_CONNECT: '港股通研究', OVERSOLD: '超跌反弹' };
const statusNames: Record<DailyChannelStatus, string> = { READY: '结果已核', READY_EMPTY: '已核空集', PARTIAL: '部分结果，仍有待核', CANNOT_CONFIRM: '尚未核实' };
const executionNames: Record<string, string> = {
  READ_ONLY_EXISTING_OWNER_REPLAY: '只读回放，生成运行未核实',
  OWNER_IMPORT_TIMING_NOT_CLASSIFIED: '原公告 owner 导入，触发方式未分类',
  MANUAL_REFRESH: '手工生成', SCHEDULED_PREOPEN: '原 owner 记录：盘前定时',
  SCHEDULED_MORNING: '原 owner 记录：早间定时', SCHEDULED_REFRESH: '原 owner 记录：定时刷新',
};
function fail(code: string): never { throw new Error(`WORKSPACE_DAILY_${code}`); }
const object = (raw: unknown): RecordValue => raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as RecordValue : fail('OBJECT_INVALID');
const records = (raw: unknown): RecordValue[] => Array.isArray(raw) ? raw.map(object) : fail('ROWS_INVALID');
const nonempty = (raw: unknown): raw is string => typeof raw === 'string' && raw.trim().length > 0;
const strings = (raw: unknown): raw is string[] => Array.isArray(raw) && raw.every(nonempty);
const safe = (row: RecordValue): void => {
  if (row.RESEARCH_ONLY !== true || row.production_allowed !== false || row.buy_gate_updated !== false || row.orders_sent !== false) fail('SAFETY_INVALID');
};
const count = (raw: unknown): raw is number => typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= 0;
const hash = (raw: unknown): boolean => raw === null || typeof raw === 'string' && /^[0-9a-f]{64}$/.test(raw);
const run = (raw: unknown): boolean => raw === null || typeof raw === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$/.test(raw);
const timestamp = (raw: unknown): boolean => raw === null || typeof raw === 'string' &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) &&
  normalizedWorkspaceDay(raw.slice(0, 10)) !== null && Number.isFinite(Date.parse(raw));

/** Accept compact or ISO day input, but reject rollover dates such as February 30. */
export function normalizedWorkspaceDay(raw: unknown): string | null {
  if (typeof raw !== 'string' || !/^(?:\d{8}|\d{4}-\d{2}-\d{2})$/.test(raw)) return null;
  const value = raw.replace(/-/g, '');
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  const time = Date.parse(`${iso}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === iso ? value : null;
}

/** The legacy date remains a display/source day and publication fallback, never a plan-date override. */
export function readDailyDateBindings(params: URLSearchParams, initialDate: string): { bindings: WorkspaceDateBindings; explicit: boolean } {
  const initial = normalizedWorkspaceDay(initialDate);
  if (!initial) fail('DATE_BINDING_INVALID');
  const legacy = normalizedWorkspaceDay(params.get('date'));
  const selection = normalizedWorkspaceDay(params.get('selection_date'));
  // announcement_date is canonical when both aliases are supplied. The
  // frozen handoff also exposes publication_date for the same calendar day.
  const announcement = normalizedWorkspaceDay(params.get('announcement_date')) ?? normalizedWorkspaceDay(params.get('publication_date'));
  return { bindings: {
    plan_date: normalizedWorkspaceDay(params.get('plan_date')) ?? initial,
    selection_date: selection ?? legacy ?? initial,
    announcement_date: announcement ?? legacy ?? initial,
  }, explicit: selection !== null || announcement !== null };
}

export function validateWorkspaceDateBindings(raw: unknown, planDate: string, expected?: WorkspaceRequestDateBindings): WorkspaceDateBindings {
  const value = object(raw);
  for (const key of ['plan_date', 'selection_date', 'announcement_date'])
    if (typeof value[key] !== 'string' || normalizedWorkspaceDay(value[key]) !== value[key]) fail('DATE_BINDING_INVALID');
  if (value.plan_date !== planDate ||
      expected?.selection_date !== undefined && value.selection_date !== normalizedWorkspaceDay(expected.selection_date) ||
      expected?.announcement_date !== undefined && value.announcement_date !== normalizedWorkspaceDay(expected.announcement_date)) fail('DATE_BINDING_MISMATCH');
  return value as unknown as WorkspaceDateBindings;
}

export function sameDailyDateBindings(raw: unknown, expected: WorkspaceDateBindings): boolean {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false;
  const value = raw as RecordValue;
  return value.plan_date === expected.plan_date && value.selection_date === expected.selection_date && value.announcement_date === expected.announcement_date;
}

function validatePlanRun(channel: RecordValue, workspace: RecordValue): void {
  if (channel.run_id === null) return;
  const product = object(workspace.plan_product); const attempt = object(workspace.workspace_plan_attempt);
  // A recovered plan is valid here only after the workspace read context
  // proves this is the current auto/dynamic view, never a historical plan.
  const recovery = product.status === 'CURRENT_RECOVERY' && (() => {
    const rawRead = workspace.read_context;
    if (!rawRead || typeof rawRead !== 'object' || Array.isArray(rawRead)) return false;
    const read = rawRead as RecordValue;
    const readAt = typeof read.read_as_of === 'string' ? Date.parse(read.read_as_of) : NaN;
    const generatedAt = typeof product.generated_at === 'string' ? Date.parse(product.generated_at) : NaN;
    return read.mode === 'CURRENT_RECOVERY' &&
      read.contract === '20260923.workspace-history-read.r1' &&
      read.v5_contract === 'v5.manager_current_recovery.v1' &&
      read.requested_view === 'auto' && read.owner_view === 'dynamic' &&
      read.historical_eligible === false &&
      ['VERIFIED', 'VERIFIED_WITH_GAPS'].includes(String(read.status)) &&
      Number.isFinite(readAt) && Number.isFinite(generatedAt) && readAt >= generatedAt &&
      product.owner_status === 'CURRENT' && product.consumed === true && product.historical_eligible === false;
  })();
  if ((!['CURRENT', 'ALREADY_MATERIALIZED', 'PRESERVED_SCHEDULED_PREOPEN'].includes(String(product.status)) && !recovery) || product.consumed !== true ||
      product.original_owner !== 'ManagerResearchJobService.refresh_workspace_plan' ||
      product.run_id !== channel.run_id || attempt.run_id !== channel.run_id || product.sha256 !== channel.product_sha256 ||
      product.generated_at !== channel.generated_at || product.execution_kind !== channel.execution_kind || attempt.execution_kind !== channel.execution_kind ||
      attempt.target_trade_date !== channel.target_trade_date || attempt.input_identity !== workspace.input_identity ||
      attempt.owner !== 'ManagerResearchJobService.refresh_workspace_plan' || !['SUCCEEDED', 'SUCCEEDED_EMPTY', 'PARTIAL'].includes(String(attempt.state))) fail('RUN_REFERENCE_INVALID');
}

/** Schema and identity admission only; the backend remains the membership, price, volume and selection authority. */
export function validateDailyChannels(raw: unknown, expected: WorkspaceDateBindings, workspace?: RecordValue): DailyChannels {
  const value = object(raw); safe(value);
  if (value.schema_version !== 'v4.manager_research.daily_channels.v1' || value.selection_rules_unchanged !== true) fail('SCHEMA_INVALID');
  validateWorkspaceDateBindings(value.date_bindings, expected.plan_date, expected);
  const channels = records(value.channels); const seen = new Set<string>();
  if (channels.length !== channelIds.length) fail('CHANNELS_INVALID');
  for (const channel of channels) {
    safe(channel);
    const id = channel.channel as DailyChannelId;
    if (!channelIds.includes(id) || seen.has(id) || !nonempty(channel.owner) ||
        !['READY', 'READY_EMPTY', 'PARTIAL', 'CANNOT_CONFIRM'].includes(String(channel.status)) ||
        channel.target_trade_date !== expected.plan_date || channel.selection_date !== expected.selection_date ||
        channel.announcement_date !== expected.announcement_date || channel.natural_run_verified !== false ||
        !strings(channel.gaps) || !strings(channel.dependencies) ||
        !Object.hasOwn(executionNames, String(channel.execution_kind))) fail('CHANNEL_INVALID');
    seen.add(id);
    if (channel.data_date !== null && normalizedWorkspaceDay(channel.data_date) !== channel.data_date ||
        id === 'ANNOUNCEMENT' && channel.data_date !== expected.announcement_date ||
        channel.data_date !== null && id !== 'ANNOUNCEMENT' && String(channel.data_date) > expected.plan_date ||
        !hash(channel.input_identity) || !hash(channel.product_sha256) || !run(channel.run_id) || !timestamp(channel.generated_at)) fail('IDENTITY_INVALID');
    if (channel.candidate_count !== null && !count(channel.candidate_count) ||
        channel.pending_count !== null && !count(channel.pending_count) ||
        channel.watch_count !== undefined && !count(channel.watch_count)) fail('COUNT_INVALID');
    if (channel.run_id !== null && (channel.product_sha256 === null || channel.generated_at === null) ||
        channel.execution_kind === 'READ_ONLY_EXISTING_OWNER_REPLAY' &&
          (channel.run_id !== null || channel.product_sha256 !== null || channel.generated_at !== null) ||
        id !== 'ANNOUNCEMENT' && channel.execution_kind !== 'READ_ONLY_EXISTING_OWNER_REPLAY' && channel.run_id === null) fail('RUN_REFERENCE_INVALID');
    const checks = id === 'ANNOUNCEMENT' ? records(channel.product_checks) : [];
    if (id === 'ANNOUNCEMENT') records(channel.other_product_checks);
    const consumed = checks.filter(check => check.status === 'CONSUMED');
    const rows = records(channel.rows); const rowIds = new Set<string>();
    for (const row of rows) {
      const allowed = id === 'ANNOUNCEMENT' ? ['SELECTED', 'CONDITIONAL_WATCH'] : id === 'OVERSOLD' ? ['SELECTED', 'NEAR_CONDITION'] : ['SELECTED'];
      if (typeof row.symbol !== 'string' || !/^HK\.(?!00000)\d{5}$/.test(row.symbol) || !nonempty(row.name) ||
          row.reason !== null && !nonempty(row.reason) || !allowed.includes(String(row.selection_status)) ||
          row.target_trade_date !== expected.plan_date || row.data_date !== channel.data_date ||
          !run(row.run_id) || !timestamp(row.generated_at) || !hash(row.product_sha256) ||
          row.source_manifest_sha256 !== undefined && !hash(row.source_manifest_sha256)) fail('ROW_INVALID');
      const rowId = id === 'ANNOUNCEMENT' ? `${row.symbol}|${row.product_sha256}|${row.selection_status}` : row.symbol;
      if (rowIds.has(rowId)) fail('ROW_DUPLICATE'); rowIds.add(rowId);
      for (const ref of records(row.source_refs)) {
        if (Object.values(ref).some(item => item !== null && typeof item !== 'string' && typeof item !== 'boolean' && !(typeof item === 'number' && Number.isFinite(item)))) fail('SOURCE_REFERENCE_INVALID');
        for (const [key, item] of Object.entries(ref)) {
          if ((key === 'sha256' || key.endsWith('_sha256')) && !hash(item) || (key === 'run_id' || key === 'evidence_run_id') && !run(item)) fail('SOURCE_REFERENCE_INVALID');
        }
      }
      if (id === 'ANNOUNCEMENT') {
        const source = consumed.find(check => check.product_sha256 === row.product_sha256);
        if (!source || row.product_sha256 === null || source.target_trade_date !== expected.plan_date ||
            normalizedWorkspaceDay(source.publication_date) !== expected.announcement_date ||
            (source.evidence_run_id ?? null) !== row.run_id ||
            (source.owner_available_at || source.reviewed_at || null) !== row.generated_at ||
            (source.source_manifest_sha256 ?? null) !== (row.source_manifest_sha256 ?? null)) fail('RUN_REFERENCE_INVALID');
      } else if (row.run_id !== channel.run_id || row.generated_at !== channel.generated_at || row.product_sha256 !== channel.product_sha256) fail('RUN_REFERENCE_INVALID');
    }
    if (id === 'ANNOUNCEMENT' && channel.run_id !== null) {
      if (consumed.length !== 1 || consumed[0].product_sha256 !== channel.product_sha256 ||
          consumed[0].evidence_run_id !== channel.run_id ||
          (consumed[0].owner_available_at || consumed[0].reviewed_at || null) !== channel.generated_at) fail('RUN_REFERENCE_INVALID');
    } else if (id !== 'ANNOUNCEMENT' && workspace) validatePlanRun(channel, workspace);
    const selected = rows.filter(row => row.selection_status === 'SELECTED').length;
    const watched = rows.length - selected;
    if (channel.candidate_count !== null && channel.candidate_count !== selected ||
        channel.watch_count !== undefined && channel.watch_count !== watched ||
        channel.status === 'CANNOT_CONFIRM' && (rows.length !== 0 || channel.candidate_count !== null) ||
        channel.status === 'READY_EMPTY' && (rows.length !== 0 || channel.candidate_count !== 0) ||
        channel.status === 'READY' && (rows.length === 0 || channel.candidate_count === null) ||
        ['READY', 'READY_EMPTY'].includes(String(channel.status)) && channel.input_identity === null) fail('COUNT_OR_STATUS_INVALID');
  }
  return value as unknown as DailyChannels;
}

const element = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = ''): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
};
const diagnosticDetails = (value: unknown): HTMLDetailsElement => {
  const node = element('details'); node.append(element('summary', '来源、运行与缺件详情'));
  let loaded = false;
  node.addEventListener('toggle', () => { if (node.open && !loaded) { loaded = true; node.append(element('pre', JSON.stringify(value, null, 2))); } });
  return node;
};

/** First-screen stock/reason/date/run view; strings are always text nodes, including diagnostics. */
export function renderDailyChannels(host: HTMLElement, raw: DailyChannels | undefined, bindings: WorkspaceDateBindings): void {
  host.dataset.dailyChannels = 'true'; host.setAttribute('aria-label', '每日三路研究结果');
  const heading = element('h3', '每日三路研究结果');
  const dates = element('p', `来源/选股日 ${bindings.selection_date} · 公告日 ${bindings.announcement_date} · 计划日 ${bindings.plan_date}`);
  dates.dataset.dailyBindings = 'true';
  const grid = element('div', '', 'manager-daily-grid');
  const style = element('style', '.manager-daily-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px}.manager-daily-grid>article{margin:0;min-width:0}.manager-daily-grid h4,.manager-daily-grid h5{margin:0 0 8px}.manager-daily-grid p{margin:7px 0}.manager-daily-rows{padding-left:20px;max-height:440px;overflow:auto}.manager-daily-rows li{margin:12px 0;overflow-wrap:anywhere}.manager-daily-meta{font-size:.9em;color:#4c5b68}');
  host.replaceChildren(style, heading, dates, element('p', '来源/选股日用于展示；港股通资格仍核对计划日的权威输入。'), grid);
  let value: DailyChannels | undefined; let failure = '尚未提供三路结果合同';
  if (raw !== undefined) {
    try { value = validateDailyChannels(raw, bindings); }
    catch (error) { failure = `三路结果合同未通过校验：${error instanceof Error ? error.message : 'WORKSPACE_DAILY_INVALID'}`; }
  }
  for (const id of channelIds) {
    const channel = value?.channels.find(item => item.channel === id);
    const article = element('article'); article.dataset.dailyChannel = id; article.dataset.dailyStatus = channel?.status ?? 'UNVERIFIED';
    article.append(element('h4', channelNames[id]), element('strong', channel ? statusNames[channel.status] : '尚未核实'));
    const candidateText = channel?.candidate_count !== null && channel?.candidate_count !== undefined ? `候选 ${channel.candidate_count} 只` : '候选数量未知';
    const pendingText = channel?.pending_count !== null && channel?.pending_count !== undefined ? `待核 ${channel.pending_count}` : '待核数量未知';
    article.append(element('p', `${candidateText}${channel?.watch_count !== undefined ? ` · 观察 ${channel.watch_count}` : ''} · ${pendingText}`));
    article.append(element('p', `数据日 ${channel?.data_date ?? '未核实'}`, 'manager-daily-meta'));
    article.append(element('p', `运行编号 ${channel?.run_id ?? '未提供/待核'} · ${channel ? executionNames[channel.execution_kind] : '生成运行未核实'}`, 'manager-daily-meta'));
    if (channel?.generated_at) article.append(element('p', `产物时间 ${channel.generated_at}`, 'manager-daily-meta'));
    if (channel?.rows.length) {
      const list = element('ol', '', 'manager-daily-rows');
      for (const row of channel.rows) {
        const item = element('li'); item.dataset.dailySymbol = row.symbol;
        item.append(element('h5', `${row.name} · ${row.symbol}`),
          element('p', row.selection_status === 'SELECTED' ? '研究候选' : row.selection_status === 'NEAR_CONDITION' ? '接近条件观察' : '条件观察'),
          element('p', row.reason ?? '选入理由未提供/待核'),
          element('p', `数据日 ${row.data_date ?? '未核实'} · 运行编号 ${row.run_id ?? '未提供/待核'}`, 'manager-daily-meta'));
        list.append(item);
      }
      article.append(list);
    } else article.append(element('p', channel?.status === 'READY_EMPTY' ? '原 owner 已核空集。' : channel ? '当前没有可展示的已核候选，待核记录见详情。' : failure));
    article.append(element('p', '自然时段运行验收：未核实。', 'manager-daily-meta'), diagnosticDetails(channel ?? { status: 'UNVERIFIED', reason: failure, date_bindings: bindings }));
    grid.append(article);
  }
  host.append(element('p', '仅研究 · 未更新 BUY 准入 · 未发订单。', 'manager-daily-meta'));
}
