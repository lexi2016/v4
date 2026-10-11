/** Synthetic HTTP bodies through the real API validator and DOM; no live owner claim. */
import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, expect, it, vi } from 'vitest';
import { mountCatalystObservations } from './catalystObservationPanel';
import { refreshManagerWorkspace } from '../api/managerWorkspace';

const date = '20261009';
const disposers: Array<() => void> = [];
const initialUrl = window.location.href;
const flags = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };

function body(params: URLSearchParams, identity = 'a') {
  return { ...flags, schema_version: 'v4.manager_research.workspace.v1', target_trade_date: date,
    semantic_version: '20260921.manager-semantic.r3.v1', input_identity: identity.repeat(64),
    date_bindings: { plan_date: date, selection_date: params.get('selection_date') ?? date,
      announcement_date: params.get('announcement_date') ?? '20261008' },
    stocks: [], focus_symbols: [], themes: [], materials: [], company_events: [], rejected_relations: [],
    gaps: ['SYNTHETIC_NO_OWNER_EXECUTION'],
    lanes: ['STAGE', 'CATALYST', 'CLOSE'].map(lane => ({ lane, owner: `SYNTHETIC_${lane}`,
      state: 'NOT_RUN', target_date: date, stock_count: null, last_attempt_at: null, last_success_at: null,
      run_id: null, execution_kind: 'READ_ONLY', failure_reasons: [], next_plan: null,
      schedule_status: 'UNBOUND', input_coverage: {} })),
    summary: { stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0, formal_recommendation_count: 0 },
    briefing: { headline: '', ordering_explanation: '' }, owner_chain: {},
    plan_context: { plan_trade_date: date, research_cutoff: '2026-10-09T10:00:00+08:00',
      market_session: '20261008', market_data_verified: false },
    plan_product: { status: 'NOT_MATERIALIZED', consumed: false }, workspace_plan_attempt: { state: 'NOT_RUN' },
    read_context: { mode: 'CURRENT_DYNAMIC_PREVIEW', status: 'VERIFIED_WITH_GAPS',
      contract: '20260923.workspace-history-read.r1', candidate_count_known: false,
      as_of: '2026-10-09T10:00:00+08:00' },
  };
}
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
const urlOf = (raw: unknown) => new URL(String(raw), window.location.origin);
const isWorkspace = (url: URL) => /^\/api\/v4\/manager\/research\/workspace(?:\/refresh)?$/.test(url.pathname);
function installFetch(handler?: (url: URL, init?: RequestInit) => Response | Promise<Response>) {
  const calls: Array<{ url: URL; init?: RequestInit }> = [];
  vi.stubGlobal('fetch', vi.fn((raw: unknown, init?: RequestInit) => {
    const url = urlOf(raw); calls.push({ url, init });
    if (isWorkspace(url)) return Promise.resolve(handler ? handler(url, init) : response(body(url.searchParams)));
    // Missing announcement input remains an explicit failed read. The date
    // selector is still real and must bind the independent workspace request.
    return Promise.resolve(new Response('', { status: 503 }));
  }));
  return calls;
}
function mount(query: string) {
  window.history.replaceState({}, '', `/manager-selection/?${query}#three-lanes`);
  const host = document.createElement('div'); document.body.append(host);
  const dispose = mountCatalystObservations(host, date); disposers.push(dispose);
  return { host, dispose, panel: () => host.querySelector<HTMLElement>('.manager-catalyst-observations')! };
}
async function ready(panel: () => HTMLElement) {
  await waitFor(() => expect(panel().dataset.readState).toBe('READY'));
}
afterEach(() => {
  while (disposers.length) disposers.pop()!();
  vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.replaceChildren();
  window.history.replaceState({}, '', initialUrl);
});

it('initializes the URL view and normalized aliases and binds both real reads', async () => {
  const calls = installFetch();
  const ui = mount(`plan_date=${date}&selection_date=20261008&publication_date=2026-10-07&view=dynamic`);
  await ready(ui.panel);
  const get = calls.find(call => isWorkspace(call.url))!.url;
  expect(get.searchParams.get('view')).toBe('dynamic');
  expect(get.searchParams.get('selection_date')).toBe('20261008');
  expect(get.searchParams.get('announcement_date')).toBe('20261007');
  expect(ui.host.querySelector<HTMLSelectElement>('[aria-label="历史或现在回看"]')!.value).toBe('dynamic');
  expect(calls.find(call => call.url.pathname.endsWith('/announcements/analysis'))!.url.searchParams.get('publication_date')).toBe('20261007');
});

it('keeps the original previous-session default and gives the canonical announcement date priority', async () => {
  const calls = installFetch();
  const first = mount(`date=${date}&plan_date=${date}`); await ready(first.panel);
  expect(calls.find(call => isWorkspace(call.url))!.url.searchParams.has('announcement_date')).toBe(false);
  expect(calls.find(call => call.url.pathname.endsWith('/announcements/analysis'))!.url.searchParams.has('publication_date')).toBe(false);
  first.dispose(); calls.length = 0;
  const second = mount(`plan_date=${date}&announcement_date=20261006&publication_date=20261007`); await ready(second.panel);
  expect(calls.find(call => isWorkspace(call.url))!.url.searchParams.get('announcement_date')).toBe('20261006');
});

it('clears the previous binding immediately and ignores the older response that arrives last', async () => {
  let finishOld: (value: Response) => void = () => { throw new Error('old request missing'); };
  const calls = installFetch(url => {
    const selected = url.searchParams.get('announcement_date');
    if (selected === '20261007') return new Promise<Response>(resolve => { finishOld = resolve; });
    return response(body(url.searchParams, selected === '20261006' ? 'c' : 'a'));
  });
  const ui = mount(`plan_date=${date}&announcement_date=20261008&view=dynamic`); await ready(ui.panel);
  await fireEvent.change(ui.host.querySelector('[aria-label="公告日期"]')!, { target: { value: '2026-10-07' } });
  expect(ui.panel().dataset.inputIdentity).toBeUndefined();
  expect(ui.host.textContent).not.toContain(`公告日 20261008`);
  await fireEvent.change(ui.host.querySelector('[aria-label="公告日期"]')!, { target: { value: '2026-10-06' } });
  await ready(ui.panel); expect(ui.panel().dataset.inputIdentity).toBe('c'.repeat(64));
  finishOld(response(body(new URLSearchParams({ announcement_date: '20261007' }), 'b')));
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(ui.panel().dataset.inputIdentity).toBe('c'.repeat(64));
  expect(new URL(window.location.href).searchParams.get('announcement_date')).toBe('20261006');
  expect(calls.filter(call => isWorkspace(call.url))).toHaveLength(3);
  expect(calls.filter(call => call.url.pathname.endsWith('/announcements/analysis'))).toHaveLength(3);
});

it('persists dynamic view and all date bindings across a remount', async () => {
  const calls = installFetch();
  const ui = mount(`plan_date=${date}&selection_date=20261008&announcement_date=20261007`); await ready(ui.panel);
  await fireEvent.change(ui.host.querySelector('[aria-label="历史或现在回看"]')!, { target: { value: 'dynamic' } });
  await ready(ui.panel);
  const params = new URL(window.location.href).searchParams;
  expect(params.get('view')).toBe('dynamic'); expect(window.location.hash).toBe('#three-lanes');
  ui.dispose();
  const again = mount(params.toString()); await ready(again.panel);
  expect(again.host.querySelector<HTMLSelectElement>('[aria-label="历史或现在回看"]')!.value).toBe('dynamic');
  const last = calls.filter(call => isWorkspace(call.url)).at(-1)!.url.searchParams;
  expect(last.get('view')).toBe('dynamic'); expect(last.get('announcement_date')).toBe('20261007');
});

it('passes identical bindings to the original POST and reuses its response once', async () => {
  const calls = installFetch();
  const ui = mount(`plan_date=${date}&selection_date=20261008&announcement_date=20261007&view=dynamic`); await ready(ui.panel);
  const refresh = [...ui.host.querySelectorAll('button')].find(button => button.textContent === '用既有材料生成计划')!;
  await fireEvent.click(refresh); await ready(ui.panel);
  const workspaceCalls = calls.filter(call => isWorkspace(call.url));
  expect(workspaceCalls).toHaveLength(2);
  expect(workspaceCalls[1].init?.method).toBe('POST');
  expect(workspaceCalls[1].url.searchParams.get('selection_date')).toBe('20261008');
  expect(workspaceCalls[1].url.searchParams.get('announcement_date')).toBe('20261007');
});

it('rejects a POST response with mismatched or omitted requested date bindings', async () => {
  installFetch(url => response(body(new URLSearchParams({ announcement_date: '20261008' }))));
  await expect(refreshManagerWorkspace(date, new AbortController().signal, { announcement_date: '20261007' }))
    .rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
  installFetch(url => { const value: Record<string, unknown> = body(url.searchParams); delete value.date_bindings; return response(value); });
  await expect(refreshManagerWorkspace(date, new AbortController().signal, { announcement_date: '20261007' }))
    .rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_INVALID');
});

it('keeps a qualified prior preview only for the same complete binding when transport fails', async () => {
  let failed = false;
  installFetch(url => { if (failed) return Promise.reject(new TypeError('synthetic transport failure')); return response(body(url.searchParams)); });
  const ui = mount(`plan_date=${date}&announcement_date=20261008&view=dynamic`); await ready(ui.panel);
  failed = true;
  await fireEvent.click([...ui.host.querySelectorAll('button')].find(button => button.textContent === '读取更新')!);
  await waitFor(() => expect(ui.panel().dataset.readState).toBe('STALE'));
  expect(ui.panel().dataset.inputIdentity).toBe('a'.repeat(64));
  await fireEvent.change(ui.host.querySelector('[aria-label="公告日期"]')!, { target: { value: '2026-10-07' } });
  await waitFor(() => expect(ui.panel().dataset.readState).toBe('FAILED'));
  expect(ui.panel().dataset.inputIdentity).toBeUndefined();
  expect(ui.host.textContent).not.toContain('公告日 20261008');
});

it('does not render a cancelled read even if the transport returns success later', async () => {
  let finish: (value: Response) => void = () => { throw new Error('pending request missing'); };
  let pending = false; let signal: AbortSignal | undefined;
  installFetch((url, init) => {
    if (!pending) return response(body(url.searchParams));
    signal = init?.signal ?? undefined;
    return new Promise<Response>(resolve => { finish = resolve; });
  });
  const ui = mount(`plan_date=${date}&announcement_date=20261008&view=dynamic`); await ready(ui.panel);
  pending = true;
  await fireEvent.click([...ui.host.querySelectorAll('button')].find(button => button.textContent === '读取更新')!);
  await fireEvent.click([...ui.host.querySelectorAll('button')].find(button => button.textContent === '取消本次读取')!);
  expect(signal?.aborted).toBe(true);
  finish(response(body(new URLSearchParams({ announcement_date: '20261008' }), 'b')));
  await waitFor(() => expect(ui.panel().dataset.readState).toBe('STALE'));
  expect(ui.panel().dataset.inputIdentity).toBe('a'.repeat(64));
  expect(ui.host.textContent).toContain('已取消本次读取');
});
