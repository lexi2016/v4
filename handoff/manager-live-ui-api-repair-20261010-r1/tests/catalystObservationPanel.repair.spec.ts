/**
 * Offline mounted-panel regression cases. Inputs below are synthetic and make
 * no claim about an owner run, deployed API, browser bundle or natural session.
 * The real panel, request/response validator and renderers run unchanged; only
 * fetch is replaced. runRepairSuite is usable by a DOM or browser test runner.
 */
import { mountCatalystObservations } from './catalystObservationPanel.js';
import { validateManagerWorkspace, type ManagerWorkspace, type WorkspaceStock } from '../api/managerWorkspace.js';
import type { DailyChannel, DailyChannels, WorkspaceDateBindings } from './dailyChannels.js';

const safe = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false } as const;
const dates: WorkspaceDateBindings = { plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' };
const hash = (letter: string) => letter.repeat(64);
function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
const equal = (actual: unknown, expected: unknown, message: string) =>
  assert(JSON.stringify(actual) === JSON.stringify(expected), `${message}: expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`);

function channels(bindings = dates): DailyChannels {
  return {
    ...safe, schema_version: 'v4.manager_research.daily_channels.v1', date_bindings: { ...bindings }, selection_rules_unchanged: true,
    channels: (['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'] as const).map(channel => ({
      ...safe, channel, owner: `SYNTHETIC_${channel}_OWNER`, status: channel === 'OVERSOLD' ? 'PARTIAL' : 'CANNOT_CONFIRM',
      target_trade_date: bindings.plan_date, selection_date: bindings.selection_date, announcement_date: bindings.announcement_date,
      data_date: channel === 'ANNOUNCEMENT' ? bindings.announcement_date : bindings.selection_date,
      rows: [], candidate_count: channel === 'OVERSOLD' ? 0 : null, pending_count: channel === 'OVERSOLD' ? 693 : null,
      gaps: [channel === 'ANNOUNCEMENT' ? 'ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED' : channel === 'HK_CONNECT' ? 'TARGET_MEMBERSHIP_AUTHORITY_UNVERIFIED' : 'HISTORY_UNIT_SCALE_NOT_PROVEN'],
      dependencies: ['EXISTING_OWNER_ONLY'], run_id: null, generated_at: null, product_sha256: null,
      input_identity: hash('b'), execution_kind: 'READ_ONLY_EXISTING_OWNER_REPLAY', natural_run_verified: false,
      ...(channel === 'ANNOUNCEMENT' ? { product_checks: [], other_product_checks: [] } : {}),
    })),
  };
}

function workspace(bindings = dates): ManagerWorkspace {
  return {
    ...safe, schema_version: 'v4.manager_research.workspace.v1', semantic_version: '20260921.manager-semantic.r3.v1',
    target_trade_date: bindings.plan_date, input_identity: hash('a'), focus_symbols: [], stocks: [], themes: [],
    company_events: [], rejected_relations: [], materials: [], gaps: [],
    lanes: (['STAGE', 'CATALYST', 'CLOSE'] as const).map(lane => ({
      lane, owner: `SYNTHETIC_${lane}`, state: 'NOT_RUN', target_date: bindings.plan_date, stock_count: null,
      last_attempt_at: null, last_success_at: null, run_id: null, execution_kind: 'READ_ONLY', failure_reasons: [],
      next_plan: null, schedule_status: 'UNBOUND', input_coverage: {},
    })),
    summary: { stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0, formal_recommendation_count: 0 },
    briefing: { headline: '', ordering_explanation: '' },
    plan_context: { plan_trade_date: bindings.plan_date, research_cutoff: '2026-10-09T09:20:00+08:00', market_session: '20261008', market_data_verified: false },
    read_context: { mode: 'CURRENT_DYNAMIC_PREVIEW', status: 'VERIFIED_WITH_GAPS', contract: '20260923.workspace-history-read.r1', candidate_count_known: true, as_of: '2026-10-09T09:20:00+08:00' },
    plan_product: { status: 'CURRENT', consumed: true, run_id: 'synthetic-plan', sha256: hash('f'), generated_at: '2026-10-09T08:00:00+08:00', execution_kind: 'MANUAL_REFRESH', original_owner: 'ManagerResearchJobService.refresh_workspace_plan' },
    workspace_plan_attempt: { state: 'PARTIAL', run_id: 'synthetic-plan', target_trade_date: bindings.plan_date, input_identity: hash('a'), execution_kind: 'MANUAL_REFRESH', owner: 'ManagerResearchJobService.refresh_workspace_plan' },
    owner_chain: {}, date_bindings: { ...bindings }, daily_channels: channels(bindings),
  };
}

function rawStocks(count: number): WorkspaceStock[] {
  return Array.from({ length: count }, (_, index) => {
    const symbol = `HK.${String(index + 1).padStart(5, '0')}`;
    return {
      ...safe, stock_key: `HK|${symbol}|${dates.plan_date}`, market: 'HK', symbol, name: `合成原始观察 ${index + 1}`,
      target_date: dates.plan_date, is_focus: false, priority_basis: { group: 'BACKGROUND', evidence_ids: [] },
      lanes: ['STAGE'], themes: [], why_watch: [], attention_priority: 'BACKGROUND', event_group_count: 0, new_catalyst_count: 0,
      evidence: [], material_relations: [], stage_observation: { raw_marker: `retained-row-${index + 1}` }, close_observation: null,
      change: { status: 'UNCHANGED', previous_date: null, reasons: [] },
      plan: { ...safe, actions: [], next_observation: [], invalidation_conditions: [], missing: [], key_risks: [], wait_conditions: [], evidence_ids: [], trigger_price: null, invalidation_price: null },
    };
  });
}

function withMapping(value: ManagerWorkspace, reviewedCount: number | null): ManagerWorkspace {
  value.us_mapping_research = {
    ...safe, schema_version: 'v4.manager_research.us_mapping_research.v1', target_trade_date: value.target_trade_date, reviewed_research: null,
    daily_run: {
      ...safe, schema_version: 'v4.manager_research.us_mapping_daily_run.v1', target_trade_date: value.target_trade_date,
      status: 'VALID_EMPTY', run_id: 'synthetic-daily-mapping', generated_at: '2026-10-09T08:00:00+08:00',
      us_session_date: '20261008', research_cutoff: '2026-10-09T09:20:00+08:00', source_status: 'READY',
      coverage: { reviewed_us_symbol_count: reviewedCount, matched_us_symbol_count: 0, matched_hk_relation_count: 0, configured_us_universe_count: 33, available_us_universe_count: 33, full_market_coverage: false },
      matches: [], gaps: [], source_identity: { payload_sha256: hash('c'), receipt_sha256: hash('d'), manifest_sha256: hash('e') },
    },
  };
  return value;
}

function readyChannels(value: ManagerWorkspace): ManagerWorkspace {
  const announcement = value.daily_channels!.channels[0];
  Object.assign(announcement, {
    status: 'READY', candidate_count: 1, pending_count: 0, gaps: [], run_id: 'synthetic-announcement',
    product_sha256: hash('c'), generated_at: '2026-10-08T22:00:00+08:00', execution_kind: 'OWNER_IMPORT_TIMING_NOT_CLASSIFIED',
    product_checks: [{ status: 'CONSUMED', product_sha256: hash('c'), target_trade_date: dates.plan_date,
      publication_date: dates.announcement_date, evidence_run_id: 'synthetic-announcement', owner_available_at: '2026-10-08T22:00:00+08:00' }],
    rows: [{ symbol: 'HK.00123', name: '合成公告候选', reason: '合成待核事件理由', selection_status: 'SELECTED',
      target_trade_date: dates.plan_date, data_date: dates.announcement_date, run_id: 'synthetic-announcement',
      generated_at: '2026-10-08T22:00:00+08:00', product_sha256: hash('c'),
      source_refs: [{ owner: 'SYNTHETIC_ANNOUNCEMENT_OWNER', payload_sha256: hash('d'), receipt_sha256: hash('e') }] }],
  });
  Object.assign(value.daily_channels!.channels[1], { status: 'READY_EMPTY', candidate_count: 0, pending_count: 0, gaps: [] });
  return value;
}

type RequestRecord = { url: URL; method: string };
type Mounted = { host: HTMLElement; requests: RequestRecord[]; read: () => void; setResponse: (next: ManagerWorkspace) => void; dispose: () => void };
function mount(value: ManagerWorkspace, query = '?date=20261009'): Mounted {
  // A fixture-admission failure is distinct from a mounted behavioral failure.
  validateManagerWorkspace(value, value.target_trade_date);
  const savedFetch = globalThis.fetch;
  const savedUrl = window.location.href;
  let response = value;
  const requests: RequestRecord[] = [];
  window.history.replaceState(null, '', `/manager-selection/${query}`);
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.href);
    requests.push({ url, method: init?.method ?? 'GET' });
    if (url.pathname === '/api/v4/manager/research/workspace' || url.pathname === '/api/v4/manager/research/workspace/refresh')
      return new Response(JSON.stringify(response), { status: 200, headers: { 'content-type': 'application/json' } });
    return new Response('{}', { status: 503, headers: { 'content-type': 'application/json' } });
  }) as typeof fetch;
  const host = document.createElement('div'); document.body.append(host);
  const unmount = mountCatalystObservations(host, value.target_trade_date);
  return {
    host, requests, read: () => { (host.querySelector('button') as HTMLButtonElement).click(); },
    setResponse: next => { response = next; },
    dispose: () => { unmount(); host.remove(); globalThis.fetch = savedFetch; window.history.replaceState(null, '', savedUrl); },
  };
}

async function settled(mounted: Mounted, expected = 'READY'): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt++) {
    if (mounted.host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state') === expected) return;
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  throw new Error(`Panel did not reach ${expected}: ${mounted.host.querySelector('[role="status"]')?.textContent}`);
}
function summary(mounted: Mounted): HTMLElement {
  const node = mounted.host.querySelector<HTMLElement>('[data-daily-channels]');
  assert(node, 'Actual mounted panel must contain the daily three-channel summary');
  return node;
}
function card(mounted: Mounted, id: DailyChannel['channel']): HTMLElement {
  const node = summary(mounted).querySelector<HTMLElement>(`[data-daily-channel="${id}"]`);
  assert(node, `Mounted daily summary must contain ${id}`);
  return node;
}
function visibleText(node: Node): string {
  if (node.nodeType === 3) return node.textContent ?? '';
  if (node instanceof HTMLElement && (node.hidden || node.tagName === 'STYLE')) return '';
  if (node instanceof HTMLElement && node.tagName === 'DETAILS' && !(node as HTMLDetailsElement).open)
    return node.querySelector('summary')?.textContent ?? '';
  return Array.from(node.childNodes).map(visibleText).join(' ');
}
function precedes(host: HTMLElement, earlier: Element, later: Element): boolean {
  const ordered = Array.from(host.querySelectorAll('*'));
  return ordered.indexOf(earlier) < ordered.indexOf(later);
}
function expand(node: HTMLDetailsElement): void {
  node.open = true;
  node.dispatchEvent(new Event('toggle'));
}

export const repairCases: Array<{ name: string; run: () => Promise<void> }> = [
  { name: 'places plan consumption and daily results before historical announcement details', run: async () => {
    const m = mount(workspace());
    try {
      await settled(m);
      const business = m.host.querySelector('.business-status');
      const historical = m.host.querySelector('[aria-label="历史公告解析成果"]');
      assert(business && historical, 'Existing plan status and announcement controls must remain mounted');
      assert(precedes(m.host, business, historical), 'Plan consumption status must precede long historical announcement details');
      assert(precedes(m.host, summary(m), historical), 'Daily results must precede long historical announcement details');
      assert(historical.querySelector('[aria-label="公告日期"]'), 'Existing announcement date control must remain usable');
    } finally { m.dispose(); }
  } },
  { name: 'mounts all three validated channel states, pending and gap reasons before raw observations', run: async () => {
    const value = workspace(); value.stocks = rawStocks(100); value.summary.stock_count = 100;
    const m = mount(value);
    try {
      await settled(m);
      equal(Array.from(summary(m).querySelectorAll('[data-daily-channel]')).map(node => node.getAttribute('data-daily-status')), ['CANNOT_CONFIRM', 'CANNOT_CONFIRM', 'PARTIAL'], 'Three channel states');
      const rendered = visibleText(summary(m));
      for (const expected of ['CANNOT_CONFIRM', 'PARTIAL', '待核 693', 'ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED', 'TARGET_MEMBERSHIP_AUTHORITY_UNVERIFIED', 'HISTORY_UNIT_SCALE_NOT_PROVEN'])
        assert(rendered.includes(expected), `Visible daily summary must show ${expected}`);
      const firstRaw = m.host.querySelector('.decision-stock'); assert(firstRaw, 'Fixture must render real raw observation rows');
      assert(precedes(m.host, summary(m), firstRaw), 'Daily results must precede raw observation rows');
      assert(!summary(m).closest('details'), 'Daily summary must be visible without opening audit details');
    } finally { m.dispose(); }
  } },
  { name: 'renders verified candidate, empty and partial results with run, product and source identity', run: async () => {
    const m = mount(readyChannels(workspace()));
    try {
      await settled(m);
      equal(['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'].map(id => card(m, id as DailyChannel['channel']).dataset.dailyStatus), ['READY', 'READY_EMPTY', 'PARTIAL'], 'Mixed channel states');
      const rendered = visibleText(card(m, 'ANNOUNCEMENT'));
      for (const expected of ['合成公告候选', '合成待核事件理由', '20261008', 'synthetic-announcement', hash('c'), hash('b'), 'SYNTHETIC_ANNOUNCEMENT_OWNER'])
        assert(rendered.includes(expected), `Visible candidate summary must show ${expected}`);
      assert(visibleText(card(m, 'HK_CONNECT')).includes('已核空集'), 'Verified empty must retain its scoped empty state');
    } finally { m.dispose(); }
  } },
  { name: 'uses the same workspace date bindings and forwards explicit dates through GET and refresh', run: async () => {
    const bindings = { plan_date: '20261009', selection_date: '20261008', announcement_date: '20261007' };
    const m = mount(workspace(bindings), '?date=20261006&plan_date=20261009&selection_date=20261008&announcement_date=20261007');
    try {
      await settled(m);
      const get = m.requests.find(request => request.url.pathname.endsWith('/workspace'));
      assert(get, 'Existing workspace GET must run');
      equal(['date', 'selection_date', 'announcement_date'].map(key => get.url.searchParams.get(key)), ['20261009', '20261008', '20261007'], 'Explicit GET date binding');
      equal(summary(m).querySelector('[data-daily-bindings]')?.textContent, '来源/选股日 20261008 · 公告日 20261007 · 计划日 20261009', 'Summary response dates');
      (m.host.querySelectorAll('button')[1] as HTMLButtonElement).click(); await settled(m);
      const post = m.requests.find(request => request.method === 'POST'); assert(post, 'Explicit refresh uses the existing POST');
      equal(['date', 'selection_date', 'announcement_date'].map(key => post.url.searchParams.get(key)), ['20261009', '20261008', '20261007'], 'Explicit refresh date binding');
      equal(m.requests.filter(request => request.url.pathname.endsWith('/workspace')).length, 1, 'Successful refresh must reuse its validated response without a second GET');
    } finally { m.dispose(); }
  } },
  { name: 'keeps independently valid daily channels visible when the saved plan is stale', run: async () => {
    const value = workspace(); value.plan_product = { ...value.plan_product, status: 'STALE_INPUTS_CHANGED', consumed: false };
    const m = mount(value);
    try {
      await settled(m);
      assert(m.host.querySelector('.business-status')?.textContent?.includes('STALE_INPUTS_CHANGED'), 'Stale plan status must stay visible');
      equal(summary(m).querySelectorAll('[data-daily-channel]').length, 3, 'Stale plan must retain independently validated daily channels');
      assert(visibleText(summary(m)).includes('待核 693'), 'Stale plan must retain pending channel diagnostics');
      equal(value.plan_product.consumed, false, 'Rendering must not promote stale plan consumption');
    } finally { m.dispose(); }
  } },
  ...['2026-10-07', ''].map(selectedDate => ({ name: `keeps historical catalog date independent from workspace bindings across reread, refresh and reload (${selectedDate || 'automatic'})`, run: async () => {
    const m = mount(workspace(), '?date=20261009&selection_date=20261009&announcement_date=20261008');
    let reloadQuery = '';
    try {
      await settled(m);
      const catalogDate = m.host.querySelector<HTMLInputElement>('[aria-label="公告日期"]'); assert(catalogDate, 'Existing historical date selector must remain mounted');
      catalogDate.value = selectedDate; catalogDate.dispatchEvent(new Event('change'));
      equal(m.requests.filter(request => request.method === 'POST').length, 0, 'Changing historical catalog date must not generate a plan');
      m.read(); await settled(m);
      const reads = m.requests.filter(request => request.url.pathname.endsWith('/workspace'));
      equal(reads.at(-1)?.url.searchParams.get('announcement_date'), '20261008', 'Historical catalog choice must not change workspace publication binding');
      (m.host.querySelectorAll('button')[1] as HTMLButtonElement).click(); await settled(m);
      equal(m.requests.find(request => request.method === 'POST')?.url.searchParams.get('announcement_date'), '20261008', 'Historical catalog choice must not change refresh plan inputs');
      reloadQuery = window.location.search;
    } finally { m.dispose(); }
    const remounted = mount(workspace(), reloadQuery);
    try {
      await settled(remounted);
      equal(remounted.requests.find(request => request.url.pathname.endsWith('/workspace'))?.url.searchParams.get('announcement_date'), '20261008', 'Reload must preserve the same explicit workspace publication binding');
      equal(remounted.host.querySelector<HTMLInputElement>('[aria-label="公告日期"]')?.value, selectedDate, 'Reload must preserve the independent historical catalog choice');
      assert(summary(remounted).querySelector('[data-daily-bindings]')?.textContent?.includes('公告日 20261008'), 'Reload summary must still use the same workspace response dates');
    } finally { remounted.dispose(); }
  } })),
  ...[1, 20, 64].map(changedCount => ({ name: `shows bounded recorded stale identity components without promoting the plan (${changedCount})`, run: async () => {
    const value = workspace();
    value.plan_product = { ...value.plan_product, status: 'STALE_INPUTS_CHANGED', consumed: false, input_identity_diagnostics: {
      schema_version: 'v4.manager_research.input_identity_diagnostics.v1', status: 'CHANGED', reason: 'RECORDED_COMPONENTS_CHANGED',
      saved_input_identity: hash('c'), current_input_identity: value.input_identity, saved_identity_version: 'synthetic.v1', current_identity_version: 'synthetic.v1',
      changed_component_count: changedCount, truncated: changedCount > 16,
      changed_components: Array.from({ length: Math.min(changedCount, 16) }, (_, index) => ({ component: index === 0 ? 'projection.materials' : `identity.extension_${index}`, saved_sha256: hash('c'), current_sha256: hash('d') })),
    } };
    const m = mount(value);
    try {
      await settled(m);
      const planRow = Array.from(m.host.querySelectorAll('.business-status-row')).find(row => row.querySelector('strong')?.textContent?.startsWith('计划：'));
      assert(planRow, 'Plan status must remain visible');
      const rendered = planRow.textContent ?? '';
      assert(rendered.includes('STALE_INPUTS_CHANGED') && rendered.includes('冻结产物已陈旧'), 'Diagnostics must not relabel stale as CURRENT');
      assert(rendered.includes(`本次输入身份差异：${changedCount} 项`) && rendered.includes('projection.materials'), 'Known compared component must be visible in plan status');
      if (changedCount > 4) assert(!rendered.includes('identity.extension_4') && rendered.includes('来源审计'), 'Plan status must keep a bounded component summary with an audit pointer');
      assert(m.host.querySelector('[role="status"]')?.textContent?.includes('consumed=false'), 'Stale plan consumption must remain explicit before daily results');
    } finally { m.dispose(); }
  } })),
  { name: 'rejects a changed-component total beyond the union of two valid 32-component maps', run: async () => {
    const value = workspace();
    value.plan_product = { ...value.plan_product, status: 'STALE_INPUTS_CHANGED', consumed: false, input_identity_diagnostics: {
      schema_version: 'v4.manager_research.input_identity_diagnostics.v1', status: 'CHANGED', reason: 'RECORDED_COMPONENTS_CHANGED',
      saved_input_identity: hash('c'), current_input_identity: value.input_identity, changed_component_count: 65, truncated: true,
      changed_components: Array.from({ length: 16 }, (_, index) => ({ component: index === 0 ? 'projection.materials' : `identity.extension_${index}`, saved_sha256: hash('c'), current_sha256: hash('d') })),
    } };
    const m = mount(value);
    try {
      await settled(m);
      const planRow = Array.from(m.host.querySelectorAll('.business-status-row')).find(row => row.querySelector('strong')?.textContent?.startsWith('计划：'));
      assert(planRow?.textContent?.includes('本次输入身份差异：CANNOT_CONFIRM'), 'An impossible component total must remain unconfirmed');
      assert(!planRow?.textContent?.includes('projection.materials'), 'An out-of-contract total must not promote supplied component names');
      equal(value.plan_product.consumed, false, 'Invalid diagnostic totals must preserve fail-closed plan consumption');
    } finally { m.dispose(); }
  } },
  ...[false, true].map(mismatchedEvidence => ({ name: `keeps stale identity changed field unconfirmed when component evidence is ${mismatchedEvidence ? 'unbound' : 'missing'}`, run: async () => {
    const value = workspace(); value.plan_product = { ...value.plan_product, status: 'STALE_INPUTS_CHANGED', consumed: false };
    if (mismatchedEvidence) value.plan_product.input_identity_diagnostics = {
      schema_version: 'v4.manager_research.input_identity_diagnostics.v1', status: 'CHANGED', reason: 'RECORDED_COMPONENTS_CHANGED',
      saved_input_identity: hash('c'), current_input_identity: hash('d'), changed_component_count: 1, truncated: false,
      changed_components: [{ component: 'projection.materials', saved_sha256: hash('c'), current_sha256: hash('d') }],
    };
    const m = mount(value);
    try {
      await settled(m);
      const planRow = Array.from(m.host.querySelectorAll('.business-status-row')).find(row => row.querySelector('strong')?.textContent?.startsWith('计划：'));
      assert(planRow?.textContent?.includes('本次输入身份差异：CANNOT_CONFIRM'), 'Missing or unbound evidence must not identify a changed component');
      assert(!planRow?.textContent?.includes('projection.materials'), 'Unbound component claim must not be promoted into the status summary');
      equal(value.plan_product.consumed, false, 'Unknown cause must preserve fail-closed plan consumption');
    } finally { m.dispose(); }
  } })),
  { name: 'clears old channel data when a later valid workspace omits the optional projection', run: async () => {
    const m = mount(readyChannels(workspace()));
    try {
      await settled(m); card(m, 'ANNOUNCEMENT');
      const missing = workspace(); delete missing.daily_channels; m.setResponse(missing); m.read(); await settled(m);
      equal(Array.from(summary(m).querySelectorAll('[data-daily-channel]')).map(node => node.getAttribute('data-daily-status')), ['UNVERIFIED', 'UNVERIFIED', 'UNVERIFIED'], 'Missing projection must be unavailable');
      assert(!summary(m).textContent?.includes('synthetic-announcement'), 'Missing projection must not borrow a previous run');
      assert(!summary(m).textContent?.includes('合成公告候选'), 'Missing projection must not retain previous candidates');
    } finally { m.dispose(); }
  } },
  { name: 'legacy workspace without explicit date bindings displays unavailable channel dates', run: async () => {
    const value = workspace(); delete value.daily_channels; delete value.date_bindings;
    const m = mount(value);
    try {
      await settled(m);
      equal(summary(m).querySelectorAll('[data-daily-status="UNVERIFIED"]').length, 3, 'Legacy response cannot supply verified channels');
      const bindingText = summary(m).querySelector('[data-daily-bindings]')?.textContent ?? '';
      assert(bindingText.includes('未核实'), 'Missing response dates must be explicitly unavailable');
      assert(!bindingText.includes('20261008'), 'Missing binding must not borrow an announcement date');
    } finally { m.dispose(); }
  } },
  { name: 'rejects channel date mismatch and clears previously rendered rows', run: async () => {
    const m = mount(readyChannels(workspace()));
    try {
      await settled(m); card(m, 'ANNOUNCEMENT');
      const invalid = workspace(); invalid.daily_channels!.channels[0].announcement_date = '20261007';
      m.setResponse(invalid); m.read(); await settled(m, 'FAILED');
      equal(summary(m).querySelectorAll('[data-daily-status="UNVERIFIED"]').length, 3, 'Mismatched date must be unavailable');
      assert(!m.host.textContent?.includes('合成公告候选'), 'Source/date failure must clear the old candidate');
      assert(m.host.querySelector('[role="status"]')?.textContent?.includes('校验失败'), 'Existing fail-closed error must remain visible');
    } finally { m.dispose(); }
  } },
  { name: 'rejects a refresh response whose explicit date binding differs from the requested date', run: async () => {
    const m = mount(workspace(), '?date=20261009&selection_date=20261009&announcement_date=20261008');
    try {
      await settled(m); summary(m);
      m.setResponse(workspace({ ...dates, announcement_date: '20261007' }));
      (m.host.querySelectorAll('button')[1] as HTMLButtonElement).click(); await settled(m, 'FAILED');
      equal(summary(m).querySelectorAll('[data-daily-status="UNVERIFIED"]').length, 3, 'Refresh mismatch must be unavailable');
      assert(!summary(m).textContent?.includes('数据日 20261007'), 'Mismatched refresh cannot become visible daily data');
    } finally { m.dispose(); }
  } },
  ...[4, 7, null].map(reviewedCount => ({ name: `labels assessment separately from daily reviewed mapping scope (${reviewedCount ?? 'unknown'})`, run: async () => {
    const m = mount(withMapping(workspace(), reviewedCount));
    try {
      await settled(m);
      const rows = Array.from(m.host.querySelectorAll('.business-status-row'));
      const assessment = rows.find(row => row.querySelector('strong')?.textContent?.startsWith('美股评估/完整度：'));
      assert(assessment, 'Upper US label must state assessment/completeness scope');
      assert(assessment.textContent?.includes('尚未评估'), 'A daily empty result must not promote global assessment');
      const scopeLabel = `每日 US-HK 已审映射（${reviewedCount === null ? '数量未知' : `${reviewedCount} 项`}）`;
      const daily = rows.find(row => row.querySelector('strong')?.textContent?.startsWith(scopeLabel));
      assert(daily, 'Daily mapping must have its own count-scoped adjacent status row');
      equal(rows.indexOf(daily), rows.indexOf(assessment) + 1, 'US scopes must be adjacent');
      assert(daily.textContent?.includes('VALID_EMPTY'), 'Scoped daily status must remain VALID_EMPTY');
      const research = m.host.querySelector('[data-us-mapping-research]'); assert(research, 'Existing mapping result must still render');
      assert(research.querySelector('h4')?.textContent?.includes(scopeLabel), 'Mapping section title must use the dynamic reviewed scope');
      assert(research.textContent?.includes('不代表全市场') && research.textContent?.includes('完整 US 输入'), 'Scoped empty must not assert full US completeness');
      if (reviewedCount !== 4) assert(!research.textContent?.includes('当前4个') && !research.textContent?.includes('4只已审阅'), 'Review count must not be hard coded');
    } finally { m.dispose(); }
  } })),
  { name: 'keeps all 100 raw observations in a default-collapsed audit region after core results', run: async () => {
    const value = workspace(); value.stocks = rawStocks(100); value.summary.stock_count = 100;
    const original = JSON.stringify(value);
    const m = mount(value);
    try {
      await settled(m);
      const audit = m.host.querySelector<HTMLDetailsElement>('details[data-raw-observations]');
      assert(audit, 'Raw rows must be grouped in an expandable audit region');
      equal(audit.open, false, 'Raw audit region must start collapsed');
      const research = m.host.querySelector('[aria-label="证据优先研究"]'); assert(research, 'Core research section must render');
      assert(precedes(m.host, summary(m), audit) && precedes(m.host, research, audit), 'Core results must precede the raw audit region');
      assert(!visibleText(m.host).includes('合成原始观察 100'), 'Raw row list must be collapsed initially');
      expand(audit);
      const background = audit.querySelector<HTMLDetailsElement>('details[data-background]'); if (background) expand(background);
      equal(audit.querySelectorAll('.decision-stock').length, 100, 'All original raw observation rows must remain expandable');
      const last = audit.querySelector<HTMLDetailsElement>('[data-stock-key="HK|HK.00100|20261009"]'); assert(last, 'The hundredth raw row must be preserved');
      expand(last);
      const rawDetail = Array.from(last.querySelectorAll<HTMLDetailsElement>('details')).find(node => node.querySelector('summary')?.textContent === '本股完整可追溯预案与来源分类');
      assert(rawDetail, 'Full raw row payload must remain available'); expand(rawDetail);
      assert(rawDetail.textContent?.includes('retained-row-100'), 'Expanded audit must retain exact last-row source payload');
      equal(JSON.stringify(value), original, 'Rendering must not mutate input rows or safety flags');
      assert(m.host.querySelector('.decision-safety')?.textContent?.includes('未读取仓位、未发订单'), 'Existing safety explanation must remain');
    } finally { m.dispose(); }
  } },
  { name: 'rejects unsafe daily flags through the existing validator before rendering candidates', run: async () => {
    const m = mount(readyChannels(workspace()));
    try {
      await settled(m);
      const unsafe = readyChannels(workspace()); unsafe.daily_channels!.channels[0].buy_gate_updated = true;
      m.setResponse(unsafe); m.read(); await settled(m, 'FAILED');
      assert(!m.host.textContent?.includes('合成公告候选'), 'Unsafe response must clear prior candidate content');
      equal(m.requests.filter(request => request.method === 'POST').length, 0, 'Readback validation must not trigger a producer');
    } finally { m.dispose(); }
  } },
];

export async function runRepairSuite(): Promise<Array<{ name: string; status: 'PASS' | 'FAIL'; error?: string }>> {
  const results: Array<{ name: string; status: 'PASS' | 'FAIL'; error?: string }> = [];
  for (const test of repairCases) {
    try { await test.run(); results.push({ name: test.name, status: 'PASS' }); }
    catch (error) { results.push({ name: test.name, status: 'FAIL', error: error instanceof Error ? error.message : String(error) }); }
  }
  return results;
}
