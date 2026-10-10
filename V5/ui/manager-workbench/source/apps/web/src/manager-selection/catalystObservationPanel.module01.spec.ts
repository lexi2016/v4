import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountCatalystObservations } from './catalystObservationPanel';
import { testBindings, testFlags, workspaceFixture } from './dailyChannels.testHelper';
import type { JsonObject, ManagerWorkspace } from '../api/managerWorkspace';

// Real API/validator/panel/renderers with synthetic HTTP input only. No product
// functions or original helpers are mocked; no Mac saved-run fixture is used.
const generatedAt = '2026-10-10T03:04:05.123456+00:00';
const cutoff = '2026-10-10T03:03:00+00:00';
const readWorkspace = (bindings = testBindings): ManagerWorkspace => {
  const value = workspaceFixture(bindings);
  (value.plan_context as JsonObject).research_cutoff = cutoff;
  (value.read_context as JsonObject).as_of = cutoff;
  return value;
};
const savedWorkspace = (reason = '本次 POST 的合成原研究理由'): ManagerWorkspace => {
  const value = readWorkspace();
  value.plan_product = { status: 'CURRENT', consumed: true, run_id: '1'.repeat(32),
    sha256: '2'.repeat(64), generated_at: generatedAt, execution_kind: 'MANUAL_REFRESH',
    original_owner: 'ManagerResearchJobService.refresh_workspace_plan' };
  value.workspace_plan_attempt = { ...testFlags, schema_version: 'v4.manager_research.workspace_attempt.v1',
    sha256: '5'.repeat(64), state: 'PARTIAL', target_trade_date: testBindings.plan_date,
    run_id: '1'.repeat(32), input_identity: value.input_identity, execution_kind: 'MANUAL_REFRESH',
    owner: 'ManagerResearchJobService.refresh_workspace_plan', failure_reasons: ['SYNTHETIC_SCOPE_GAP'],
    started_at: '2026-10-10T03:04:00+00:00', finished_at: '2026-10-10T03:04:06+00:00' };
  value.daily_channels!.channels[0].rows[0].reason = reason;
  return value;
};
const historicalWorkspace = (): ManagerWorkspace => {
  const value = workspaceFixture(testBindings);
  value.read_context = { ...(value.read_context as JsonObject), mode: 'HISTORICAL_AS_OF',
    status: 'NOT_MATERIALIZED', candidate_count_known: false };
  value.plan_product = { status: 'NOT_MATERIALIZED', consumed: false };
  return value;
};
const ok = (value: unknown, readOnly = false): Response => new Response(JSON.stringify(value), {
  status: 200, headers: { 'Content-Type': 'application/json', ...(readOnly ? { 'X-V5-Workspace-Access': 'READ_ONLY' } : {}) },
});
const unavailable = (): Response => new Response(JSON.stringify({ status: 'CANNOT_CONFIRM',
  reason_codes: ['MODULE_RESULT_NOT_AVAILABLE'] }), { status: 503 });
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
};
type Request = { url: URL; method: string; signal: AbortSignal | null | undefined };
let dispose: (() => void) | undefined;
const mount = (handler: (request: Request) => Promise<Response> | Response,
  query = '?plan_date=20261008&selection_date=20261006&announcement_date=20261007&view=dynamic') => {
  const requests: Request[] = [];
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = { url: new URL(String(input), 'http://localhost'), method: init?.method ?? 'GET', signal: init?.signal };
    if (!request.url.pathname.includes('/workspace')) return unavailable();
    requests.push(request); return handler(request);
  });
  window.history.replaceState({}, '', `/${query}`);
  const host = document.createElement('div'); document.body.append(host);
  dispose = mountCatalystObservations(host, '20261008');
  const generate = [...host.querySelectorAll('button')].find(node => node.textContent === '用既有材料生成计划')!;
  const panel = host.querySelector<HTMLElement>('.manager-catalyst-observations')!;
  return { host, generate, panel, requests };
};
const ready = async (panel: HTMLElement) => { await waitFor(() => expect(panel.dataset.readState).toBe('READY')); };
const trigger = async (button: HTMLButtonElement) => { await fireEvent.click(button); };
afterEach(() => {
  dispose?.(); dispose = undefined; vi.useRealTimers(); vi.unstubAllGlobals();
  window.history.replaceState({}, '', '/'); document.body.replaceChildren();
});

describe('module 01 generation admission', () => {
  it('keeps V5 read-only after a fully valid response even when payload text claims write access', async () => {
    const value = readWorkspace(); value.workspace_access = 'READ_WRITE';
    const { panel, generate, requests } = mount(() => ok(value, true));
    await ready(panel);
    expect(generate.disabled).toBe(true);
    expect(generate.title).toContain('只读');
    generate.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await Promise.resolve();
    expect(requests.map(request => request.method)).toEqual(['GET']);
  });

  it.each(['first GET failure', 'missing read_context'] as const)('does not enable generation after %s', async kind => {
    const value = readWorkspace(); if (kind === 'missing read_context') delete value.read_context;
    const { panel, generate, requests } = mount(() => kind === 'first GET failure' ? unavailable() : ok(value));
    await waitFor(() => expect(panel.dataset.readState).toBe('FAILED'));
    expect(generate.disabled).toBe(true);
    generate.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await Promise.resolve();
    expect(requests.map(request => request.method)).toEqual(['GET']);
  });

  it('enforces historical read-only at the event handler as well as the button', async () => {
    const { panel, generate, requests } = mount(() => ok(historicalWorkspace()), '?plan_date=20261008');
    await ready(panel);
    expect(generate.disabled).toBe(true);
    generate.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await Promise.resolve();
    expect(requests.map(request => request.method)).toEqual(['GET']);
  });

  it('requires explicit dynamic view before generating for an older target date', async () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-10-10T04:00:00Z'));
    const { panel, generate } = mount(() => ok(readWorkspace()), '?plan_date=20261008');
    await ready(panel);
    expect(generate.disabled).toBe(true);
  });
});

describe('module 01 successful POST consumption', () => {
  it('renders the one validated POST result without borrowing a later GET publication', async () => {
    let reads = 0;
    const { panel, host, generate, requests } = mount(request => request.method === 'POST'
      ? ok(savedWorkspace()) : ok(++reads === 1 ? readWorkspace() : savedWorkspace('另一请求推进 latest 的合成结果')));
    await ready(panel); expect(generate.disabled).toBe(false); await trigger(generate);
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('本次 POST 的合成原研究理由'));
    expect(requests.map(request => request.method)).toEqual(['GET', 'POST']);
    expect(Object.fromEntries(requests[1].url.searchParams)).toEqual({
      date: '20261008', selection_date: '20261006', announcement_date: '20261007',
    });
    expect(host.textContent).not.toContain('另一请求推进 latest');
    expect(panel.dataset.generationState).toBe('VERIFIED');
  });

  it('retains true execution timestamps when explicitly looking back dynamically', async () => {
    const { panel, host, generate } = mount(request => ok(request.method === 'POST' ? savedWorkspace() : readWorkspace()));
    await ready(panel); await trigger(generate);
    await waitFor(() => expect(panel.dataset.generationState).toBe('VERIFIED'));
    const audit = [...host.querySelectorAll('details')].find(node => node.querySelector('summary')?.textContent === '计划日期与冻结/预览的精确时点')!;
    audit.open = true; audit.dispatchEvent(new Event('toggle'));
    const value = JSON.parse(audit.querySelector('pre')!.textContent!);
    expect(value.plan_context.research_cutoff).toBe(cutoff);
    expect(value.plan_product.generated_at).toBe(generatedAt);
    expect(value.plan_product.run_id).toBe('1'.repeat(32));
    expect(host.querySelector('[role="status"]')?.textContent).toContain('现在回看');
    expect(host.querySelector('[role="status"]')?.textContent).not.toContain('当时已知计划');
  });
});

describe('module 01 unknown write outcome and stale responses', () => {
  it.each(['network error', 'HTTP 503', 'wrong date response'] as const)('does not classify %s as a failed owner run or automatically GET/retry POST', async failure => {
    const { panel, host, generate, requests } = mount(request => {
      if (request.method === 'GET') return ok(readWorkspace());
      if (failure === 'network error') throw new TypeError('synthetic connection lost');
      if (failure === 'HTTP 503') return unavailable();
      const value = savedWorkspace(); value.date_bindings!.announcement_date = '20261006';
      return ok(value);
    });
    await ready(panel); await trigger(generate);
    await waitFor(() => expect(panel.dataset.generationState).toBe('CANNOT_CONFIRM'));
    expect(panel.dataset.readState).not.toBe('FAILED');
    expect(host.querySelector('[role="status"]')?.textContent).toContain('生成结果未知');
    expect(host.querySelector('[role="status"]')?.textContent).not.toContain('本次生成失败');
    expect(generate.disabled).toBe(true);
    generate.dispatchEvent(new MouseEvent('click', { bubbles: true })); await Promise.resolve();
    expect(requests.map(request => request.method)).toEqual(['GET', 'POST']);
  });

  it('suppresses a POST that completes after cancellation and reports unknown outcome', async () => {
    const pending = deferred<Response>();
    const { panel, host, generate, requests } = mount(request => request.method === 'POST' ? pending.promise : ok(readWorkspace()));
    await ready(panel); await trigger(generate);
    const cancel = [...host.querySelectorAll('button')].find(node => node.textContent === '取消本次读取')!;
    await trigger(cancel); expect(requests[1].signal?.aborted).toBe(true);
    pending.resolve(ok(savedWorkspace('不应渲染的已取消合成结果')));
    await waitFor(() => expect(panel.dataset.generationState).toBe('CANNOT_CONFIRM'));
    expect(host.textContent).not.toContain('不应渲染的已取消合成结果');
    expect(host.querySelector('[role="status"]')?.textContent).toContain('生成结果未知');
    expect(requests.map(request => request.method)).toEqual(['GET', 'POST']);
  });

  it('keeps the 180-second timeout bounded without declaring an unknown write FAILED', async () => {
    const { panel, host, generate, requests } = mount(request => request.method === 'GET' ? ok(readWorkspace())
      : new Promise<Response>((_resolve, reject) => request.signal!.addEventListener('abort',
        () => reject(new DOMException('synthetic timeout', 'AbortError')), { once: true })));
    await ready(panel); vi.useFakeTimers(); await trigger(generate);
    await vi.advanceTimersByTimeAsync(180_000);
    expect(requests[1].signal?.aborted).toBe(true);
    expect(panel.dataset.generationState).toBe('CANNOT_CONFIRM');
    expect(panel.dataset.readState).not.toBe('FAILED');
    expect(host.querySelector('[role="status"]')?.textContent).toContain('生成结果未知');
    expect(requests.map(request => request.method)).toEqual(['GET', 'POST']);
  });

  it.each(['date', 'view'] as const)('does not render a late POST after changing %s', async change => {
    const pending = deferred<Response>(); let reads = 0;
    const { panel, host, generate, requests } = mount(request => {
      if (request.method === 'POST') return pending.promise;
      if (++reads === 1) return ok(readWorkspace());
      return ok(change === 'date' ? readWorkspace({ ...testBindings, plan_date: '20261009' }) : historicalWorkspace());
    });
    await ready(panel); await trigger(generate);
    if (change === 'date') {
      const input = host.querySelector<HTMLInputElement>('input[aria-label="计划目标日"]')!;
      input.value = '2026-10-09'; await fireEvent.change(input);
    } else {
      const select = host.querySelector<HTMLSelectElement>('select[aria-label="历史或现在回看"]')!;
      select.value = 'auto'; await fireEvent.change(select);
    }
    await ready(panel); expect(requests[1].signal?.aborted).toBe(true);
    pending.resolve(ok(savedWorkspace('不应渲染的旧日期或旧口径合成结果')));
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    expect(host.textContent).not.toContain('不应渲染的旧日期或旧口径合成结果');
    expect(generate.disabled).toBe(true);
    expect(requests.map(request => request.method)).toEqual(['GET', 'POST', 'GET']);
    if (change === 'date') expect(panel.dataset.targetDate).toBe('20261009');
    else expect(host.querySelector('[role="status"]')?.textContent).toContain('当时历史');
  });
});
