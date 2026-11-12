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
  EXISTING_STAGE_SELECTION_READBACK: '原 Stage 已保存产物，执行与可用时间待核',
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

/** Only explicit source choices go to the API; its original calendar owns defaults. */
export function workspaceRequestDateBindings(params: URLSearchParams): WorkspaceRequestDateBindings {
  const result: WorkspaceRequestDateBindings = {};
  const choices = { selection_date: params.get('selection_date'),
    announcement_date: params.get('announcement_date') ?? params.get('publication_date') };
  for (const key of ['selection_date', 'announcement_date'] as const) {
    if (choices[key] === null) continue;
    const day = normalizedWorkspaceDay(choices[key]);
    if (day === null) fail('DATE_BINDING_INVALID');
    result[key] = day;
  }
  return result;
}

/** Validate the separate reviewed announcement readback before displaying its stock rows.
 * This result is research-only and cannot be promoted into a plan by this UI gate.
 */
export function verifiedAnnouncementResearchResult(raw: unknown, expected: WorkspaceDateBindings): boolean {
  try {
    const value = object(raw);
    const planDate = normalizedWorkspaceDay(expected?.plan_date);
    const selectionDate = normalizedWorkspaceDay(expected?.selection_date);
    const announcementDate = normalizedWorkspaceDay(expected?.announcement_date);
    if (!planDate || !selectionDate || !announcementDate ||
        value.schema_version !== 'v4.manager_research.announcement_research_result.v1' ||
        value.target_trade_date !== planDate ||
        normalizedWorkspaceDay(value.publication_date) !== announcementDate ||
        value.owner !== 'ManagerResearchJobService.import_announcement_analysis' ||
        value.validation_status !== 'VERIFIED' ||
        value.historical_pit_verified !== false || value.natural_run_verified !== false ||
        value.RESEARCH_ONLY !== true || value.production_allowed !== false ||
        value.buy_gate_updated !== false || value.orders_sent !== false) return false;
    const consumed = value.consumed_at_cutoff === true;
    if ((value.status === 'CONSUMED_AT_CUTOFF') !== consumed ||
        !['CONSUMED_AT_CUTOFF', 'RETROSPECTIVE_RESEARCH_ONLY'].includes(String(value.status)) ||
        consumed && value.cutoff_status !== 'SATISFIED' ||
        !consumed && value.cutoff_status !== 'NOT_REQUESTED' && value.cutoff_status !== 'AFTER_CUTOFF') return false;
    if (value.plan_cutoff !== null && !timestamp(value.plan_cutoff)) return false;
    if (value.plan_cutoff === null && value.cutoff_status !== 'NOT_REQUESTED') return false;
    for (const key of ['product_sha256', 'selection_sha256', 'source_manifest_sha256',
      'catalog_product_sha256', 'owner_import_receipt_sha256', 'handoff_manifest_sha256']) {
      if (typeof value[key] !== 'string' || !/^[0-9a-f]{64}$/.test(value[key] as string)) return false;
    }
    if (!run(value.evidence_run_id) || value.evidence_run_id === null ||
        !run(value.catalog_run_id) || value.catalog_run_id === null ||
        typeof value.owner_available_at !== 'string' || !timestamp(value.owner_available_at) ||
        typeof value.latest_source_or_review_at !== 'string' || !timestamp(value.latest_source_or_review_at)) return false;
    const rows = records(value.stocks);
    const fields = ['selected_stock_count', 'conditional_watch_count',
      'not_selected_stock_count', 'not_assessed_stock_count'] as const;
    if (!count(value.stock_count) || value.stock_count !== rows.length ||
        fields.some(field => !count(value[field])) ||
        fields.reduce((sum, field) => sum + (value[field] as number), 0) !== rows.length) return false;
    const statusByField = {
      selected_stock_count: 'SELECTED',
      conditional_watch_count: 'CONDITIONAL_WATCH',
      not_selected_stock_count: 'NOT_SELECTED',
      not_assessed_stock_count: 'NOT_ASSESSED',
    } as const;
    const seen = new Set<string>();
    for (const row of rows) {
      const code = row.stock_code;
      if (!nonempty(code) || seen.has(code) ||
          !Object.values(statusByField).includes(row.status as typeof statusByField[keyof typeof statusByField]) ||
          row.target_trade_date !== planDate ||
          normalizedWorkspaceDay(row.publication_date) !== announcementDate ||
          row.evidence_run_id !== value.evidence_run_id ||
          row.product_sha256 !== value.product_sha256 ||
          row.selection_sha256 !== value.selection_sha256 ||
          row.owner_import_receipt_sha256 !== value.owner_import_receipt_sha256) return false;
      seen.add(code);
    }
    return fields.every(field => rows.filter(row => row.status === statusByField[field]).length === value[field]);
  } catch {
    return false;
  }
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
  const product = object(workspace.plan_product);
  const attempt = object(workspace.workspace_plan_product_attempt ?? workspace.workspace_plan_attempt);
  if (!['CURRENT', 'ALREADY_MATERIALIZED', 'PRESERVED_SCHEDULED_PREOPEN'].includes(String(product.status)) || product.consumed !== true ||
      product.original_owner !== 'ManagerResearchJobService.refresh_workspace_plan' ||
      product.run_id !== channel.run_id || attempt.run_id !== channel.run_id || product.sha256 !== channel.product_sha256 ||
      product.generated_at !== channel.generated_at || product.execution_kind !== channel.execution_kind || attempt.execution_kind !== channel.execution_kind ||
      attempt.target_trade_date !== channel.target_trade_date || attempt.input_identity !== workspace.input_identity ||
      attempt.owner !== 'ManagerResearchJobService.refresh_workspace_plan' || !['SUCCEEDED', 'SUCCEEDED_EMPTY', 'PARTIAL'].includes(String(attempt.state))) fail('RUN_REFERENCE_INVALID');
}

function validateStageRun(channel: RecordValue, workspace?: RecordValue): void {
  if (channel.run_id === null) return;
  const source = object(channel.source_result);
  const evidence = typeof source.source_evidence === 'string' ? [source.source_evidence]
    : Array.isArray(source.source_evidence) ? source.source_evidence.filter(nonempty) : [];
  if (source.backfill_run_id || ['selection_mode=BACKFILL', 'recovery_mode=HISTORICAL_BACKFILL',
    'HISTORICAL_BACKFILL', 'substitute_kind=HK_0930_0935_FOR_HK_0925'].some(marker => evidence.includes(marker))) fail('STAGE_REFERENCE_INVALID');
  if (channel.execution_kind !== 'EXISTING_STAGE_SELECTION_READBACK' || channel.status !== 'PARTIAL' ||
      channel.generated_at !== null || source.market !== 'HK_CONNECT' ||
      source.trade_date !== channel.target_trade_date || source.stage_id !== channel.stage_id ||
      source.selection_manifest_receipt_verified !== true || source.run_id !== channel.run_id ||
      source.selection_run_id !== channel.run_id || source.selection_manifest_sha256 !== channel.product_sha256 ||
      source.raw_artifact_sha256 !== channel.input_identity ||
      source.selection_receipt_sha256 !== channel.selection_receipt_sha256 ||
      source.selection_artifact_sha256 !== channel.selection_artifact_sha256 ||
      !hash(source.selection_receipt_sha256) || source.selection_receipt_sha256 === null ||
      !hash(source.selection_artifact_sha256) || source.selection_artifact_sha256 === null ||
      source.selection_mode === 'BACKFILL') fail('STAGE_REFERENCE_INVALID');
  const authority = object(channel.authority);
  if (!strings(authority.codes)) fail('STAGE_REFERENCE_INVALID');
  if (workspace) {
    if (workspace.read_context !== undefined && object(workspace.read_context).mode === 'HISTORICAL_AS_OF') fail('STAGE_REFERENCE_INVALID');
    const original = object(workspace.stage_selection_readback);
    const market = object(object(original.markets).HK_CONNECT);
    if (original.trade_date !== channel.target_trade_date || original.stage_id !== channel.stage_id ||
        original.response_source !== 'SHARED_STAGE_CENTER' ||
        JSON.stringify(market) !== JSON.stringify(source) ||
        JSON.stringify(object(workspace.selection_diagnostics).membership) !== JSON.stringify(authority)) fail('STAGE_REFERENCE_INVALID');
  }
  const nativeRows = records(source.rows);
  if (source.selected_rows !== nativeRows.length) fail('STAGE_REFERENCE_INVALID');
  // Verify the backend's existing membership projection in full. A subset
  // check would admit an accidental UI cap, reordering, or fabricated zero.
  const canonical = (raw: unknown): string => {
    const match = typeof raw === 'string' && /^(?:HK\.)?(\d{1,5})(?:\.HK)?$/.exec(raw.trim().toUpperCase());
    return match && Number(match[1]) > 0 ? `HK.${match[1].padStart(5, '0')}` : fail('STAGE_REFERENCE_INVALID');
  };
  const allowed = new Set(authority.codes);
  const expected = nativeRows.filter(native => allowed.has(canonical(native.code)));
  const rows = records(channel.rows);
  if (rows.length !== expected.length || channel.candidate_count !== (rows.length || null)) fail('STAGE_REFERENCE_INVALID');
  const expectedRef = { owner: 'SelectionStore', run_id: channel.run_id,
    manifest_sha256: channel.product_sha256, artifact_sha256: source.selection_artifact_sha256,
    receipt_sha256: source.selection_receipt_sha256, source_sha256: source.raw_artifact_sha256 };
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index]; const native = expected[index]; const symbol = canonical(native.code);
    const evidence = typeof native.lane_evidence === 'string' ? [native.lane_evidence]
      : Array.isArray(native.lane_evidence) ? native.lane_evidence : [];
    const reason = evidence.filter(nonempty).join('；') || null;
    const refs = records(row.source_refs);
    if (row.symbol !== symbol || row.name !== (native.name || native.stock_name || symbol) || row.reason !== reason ||
        JSON.stringify(row.lane_evidence) !== JSON.stringify(native.lane_evidence ?? null) ||
        ['rank', 'order', 'formal_eligible', 'action_level', 'trade_status', 'source_mode']
          .some(key => (native[key] ?? null) !== row[key]) || refs.length !== 1 ||
        Object.keys(refs[0]).length !== Object.keys(expectedRef).length ||
        Object.entries(expectedRef).some(([key, expectedValue]) => refs[0][key] !== expectedValue)) fail('STAGE_REFERENCE_INVALID');
  }
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
    if (channel.run_id !== null && (channel.product_sha256 === null || id !== 'HK_CONNECT' && channel.generated_at === null) ||
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
    } else if (id === 'HK_CONNECT') validateStageRun(channel, workspace);
    else if (id === 'OVERSOLD' && workspace) validatePlanRun(channel, workspace);
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
export function renderDailyChannels(host: HTMLElement, raw: DailyChannels | undefined, bindings?: WorkspaceDateBindings): void {
  host.dataset.dailyChannels = 'true'; host.setAttribute('aria-label', '每日三路研究结果');
  const heading = element('h3', '每日三路研究结果');
  const dates = element('p', bindings
    ? `来源/选股日 ${bindings.selection_date} · 公告日 ${bindings.announcement_date} · 计划日 ${bindings.plan_date}`
    : '三路日期绑定未提供 · CANNOT_CONFIRM');
  dates.dataset.dailyBindings = 'true';
  const grid = element('div', '', 'manager-daily-grid');
  const style = element('style', '.manager-daily-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:12px}.manager-daily-grid>article{margin:0;min-width:0}.manager-daily-grid h4,.manager-daily-grid h5{margin:0 0 8px}.manager-daily-grid p{margin:7px 0}.manager-daily-rows{padding-left:20px;max-height:440px;overflow:auto}.manager-daily-rows li{margin:12px 0;overflow-wrap:anywhere}.manager-daily-meta{font-size:.9em;color:#4c5b68}');
  host.replaceChildren(style, heading, dates, element('p', '来源/选股日用于展示；港股通资格仍核对计划日的权威输入。'), grid);
  let value: DailyChannels | undefined; let failure = '尚未提供三路结果合同';
  if (raw !== undefined) {
    try { if (!bindings) fail('DATE_BINDING_INVALID'); value = validateDailyChannels(raw, bindings); }
    catch (error) { failure = `三路结果合同未通过校验：${error instanceof Error ? error.message : 'WORKSPACE_DAILY_INVALID'}`; }
  }
  for (const id of channelIds) {
    const channel = value?.channels.find(item => item.channel === id);
    const article = element('article'); article.dataset.dailyChannel = id; article.dataset.dailyStatus = channel?.status ?? 'CANNOT_CONFIRM';
    article.append(element('h4', `${id} · ${channelNames[id]}`),
      element('strong', `${channel?.status ?? 'CANNOT_CONFIRM'} · ${channel ? statusNames[channel.status] : '尚未核实'}`));
    const candidateText = channel?.candidate_count !== null && channel?.candidate_count !== undefined ? `候选 ${channel.candidate_count} 只` : '候选数量未知';
    const pendingText = channel?.pending_count !== null && channel?.pending_count !== undefined ? `待核 ${channel.pending_count}` : '待核数量未知';
    article.append(element('p', `${candidateText}${channel?.watch_count !== undefined ? ` · 观察 ${channel.watch_count}` : ''} · ${pendingText}`));
    article.append(element('p', `数据日 ${channel?.data_date ?? '未核实'}`, 'manager-daily-meta'));
    article.append(element('p', `原 owner ${channel?.owner ?? 'CANNOT_CONFIRM'}`, 'manager-daily-meta'));
    article.append(element('p', `运行编号 ${channel?.run_id ?? '未提供/待核'} · ${channel ? executionNames[channel.execution_kind] : '生成运行未核实'}`, 'manager-daily-meta'));
    article.append(element('p', `产物 SHA256 ${channel?.product_sha256 ?? 'CANNOT_CONFIRM'} · 输入身份 ${channel?.input_identity ?? 'CANNOT_CONFIRM'}`, 'manager-daily-meta'));
    if (channel?.generated_at) article.append(element('p', `产物时间 ${channel.generated_at}`, 'manager-daily-meta'));
    if (channel) {
      const shownGaps = channel.gaps.slice(0, 3);
      article.append(element('p', `缺口 ${channel.gaps.length} 项${shownGaps.length ? `：${shownGaps.join('；')}` : '；状态仍按原 owner 结果显示'}${channel.gaps.length > shownGaps.length ? '；其余缺口完整保留在来源详情' : ''}`));
    }
    if (channel?.rows.length) {
      const list = element('ol', '', 'manager-daily-rows');
      for (const row of channel.rows) {
        const item = element('li'); item.dataset.dailySymbol = row.symbol;
        item.append(element('h5', `${row.name} · ${row.symbol}`),
          element('p', row.selection_status === 'SELECTED' ? '研究候选' : row.selection_status === 'NEAR_CONDITION' ? '接近条件观察' : '条件观察'),
          element('p', row.reason ?? '选入理由未提供/待核'),
          element('p', `数据日 ${row.data_date ?? '未核实'} · 运行编号 ${row.run_id ?? '未提供/待核'}`, 'manager-daily-meta'),
          element('p', `产物 SHA256 ${row.product_sha256 ?? 'CANNOT_CONFIRM'} · 来源引用 ${row.source_refs.length} 项（完整保留在来源详情）`, 'manager-daily-meta'));
        list.append(item);
      }
      article.append(list);
    } else article.append(element('p', channel?.status === 'READY_EMPTY' ? '原 owner 已核空集。' : channel ? '当前没有可展示的已核候选，待核记录见详情。' : failure));
    article.append(element('p', '自然时段运行验收：CANNOT_CONFIRM（未核实）。', 'manager-daily-meta'), diagnosticDetails(channel ?? { status: 'CANNOT_CONFIRM', reason: failure, date_bindings: bindings }));
    grid.append(article);
  }
  host.append(element('p', '仅研究 · 未更新 BUY 准入 · 未发订单。', 'manager-daily-meta'));
}
