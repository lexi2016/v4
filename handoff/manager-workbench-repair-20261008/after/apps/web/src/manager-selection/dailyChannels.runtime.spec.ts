import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestManagerWorkspace, validateManagerWorkspace, type JsonObject } from '../api/managerWorkspace';
import { mountCatalystObservations } from './catalystObservationPanel';
import { testBindings, workspaceFixture } from './dailyChannels.testHelper';

const ok = (value: unknown) => ({ ok: true, status: 200, json: async () => value }) as Response;
const noAnnouncements = () => ({ ok: false, status: 503 }) as Response;
let dispose: (() => void) | undefined;
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); document.body.replaceChildren(); });

describe('daily channel query and payload boundary', () => {
  it('sends plan, selection and publication days independently on the canonical GET', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(workspaceFixture())); vi.stubGlobal('fetch', fetchMock);
    await requestManagerWorkspace('20261008', new AbortController().signal, 'auto',
      { selection_date: '20261006', announcement_date: '20261007' });
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(Object.fromEntries(url.searchParams)).toEqual({ date: '20261008', view: 'auto', selection_date: '20261006', announcement_date: '20261007' });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'GET', cache: 'no-store', credentials: 'same-origin' });
  });

  it('rejects a response for a different selected publication day', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok(workspaceFixture())));
    await expect(requestManagerWorkspace('20261008', new AbortController().signal, 'auto',
      { selection_date: '20261006', announcement_date: '20261006' })).rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
  });

  it('preserves legacy workspace parsing when the optional extension is absent', () => {
    const value = workspaceFixture(testBindings, false);
    expect(validateManagerWorkspace(value, '20261008')).toBe(value);
  });

  it.each([
    ['wrong schema', (d: JsonObject) => { d.schema_version = 'v4.manager_research.daily_channels.v0'; }],
    ['unsafe extension', (d: JsonObject) => { d.orders_sent = true; }],
    ['duplicate channels', (d: JsonObject) => { (d.channels as JsonObject[])[1].channel = 'ANNOUNCEMENT'; }],
    ['unknown as zero', (d: JsonObject) => { (d.channels as JsonObject[])[1].candidate_count = 0; }],
    ['negative count', (d: JsonObject) => { (d.channels as JsonObject[])[0].candidate_count = -1; }],
    ['invalid symbol', (d: JsonObject) => { ((d.channels as JsonObject[])[0].rows as JsonObject[])[0].symbol = 'HK.00000'; }],
    ['mismatched row date', (d: JsonObject) => { ((d.channels as JsonObject[])[0].rows as JsonObject[])[0].data_date = '20261006'; }],
    ['unbound row run', (d: JsonObject) => { ((d.channels as JsonObject[])[0].rows as JsonObject[])[0].run_id = 'different-run'; }],
    ['timezone missing', (d: JsonObject) => { (d.channels as JsonObject[])[0].generated_at = '2026-10-08T07:05:00'; }],
    ['invalid calendar date', (d: JsonObject) => { (d.date_bindings as JsonObject).announcement_date = '20260230'; }],
    ['false natural acceptance', (d: JsonObject) => { (d.channels as JsonObject[])[0].natural_run_verified = true; }],
  ])('rejects %s before the new first-screen view is admitted', (_name, mutate) => {
    const value = workspaceFixture(); mutate(value.daily_channels as unknown as JsonObject);
    expect(() => validateManagerWorkspace(value, '20261008')).toThrow(/WORKSPACE_DAILY_/);
  });
});

describe('first-screen independent research channels', () => {
  it.each([
    ['publication_date=20261006', '20261006'],
    ['publication_date=20261006&announcement_date=20261007', '20261007'],
  ])('binds the publication alias deterministically through the actual GET: %s', async (query, publication) => {
    window.history.replaceState({}, '', `/?date=20261007&plan_date=20261008&${query}`);
    const bindings = { ...testBindings, selection_date: '20261007', announcement_date: publication };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?') ? ok(workspaceFixture(bindings)) : noAnnouncements());
    vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('HK.00001'));
    const url = String(fetchMock.mock.calls.find(call => String(call[0]).includes('/workspace?'))![0]);
    expect(new URL(url, 'http://localhost').searchParams.get('announcement_date')).toBe(publication);
    expect(fetchMock.mock.calls.some(call => String(call[0]) === `/api/v4/manager/research/announcements?date=${publication}`)).toBe(true);
  });

  it('rebinds one legacy default GET when a new backend returns different display/publication dates', async () => {
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (!url.pathname.endsWith('/workspace')) return noAnnouncements();
      return ok(workspaceFixture({ plan_date: url.searchParams.get('date')!,
        selection_date: url.searchParams.get('selection_date') ?? '20261008',
        announcement_date: url.searchParams.get('announcement_date') ?? '20261007' }));
    }); vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('HK.00001'));
    const reads = fetchMock.mock.calls.filter(call => String(call[0]).includes('/workspace?'));
    expect(reads).toHaveLength(2);
    expect(String(reads[1][0])).toContain('selection_date=20261006');
    expect(String(reads[1][0])).toContain('announcement_date=20261006');
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('公告日 20261006');
  });

  it('renders stock, original reason, data date, run and status without expanding diagnostics', async () => {
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008&announcement_date=20261007');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?') ? ok(workspaceFixture()) : noAnnouncements());
    vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')).not.toBeNull());
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('原研究理由：已审阅的扩产事件。'));
    const announcement = host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')!;
    expect(announcement.textContent).toContain('HK.00001'); expect(announcement.textContent).toContain('20261007');
    expect(announcement.textContent).toContain('synthetic-import-run'); expect(announcement.closest('details')).toBeNull();
    expect(host.querySelectorAll('[data-daily-channel]')).toHaveLength(3);
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('候选数量未知');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('候选数量未知');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('待核 2');
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).not.toContain('0 只');
    expect(host.querySelector('[data-daily-channels] pre')).toBeNull();
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('来源/选股日 20261006');
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('公告日 20261007');
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('计划日 20261008');
    const get = fetchMock.mock.calls.map(call => String(call[0])).find(url => url.includes('/workspace?'))!;
    expect(new URL(get, 'http://localhost').searchParams.get('announcement_date')).toBe('20261007');
    expect(fetchMock.mock.calls.some(call => String(call[0]) === '/api/v4/manager/research/announcements?date=20261007')).toBe(true);
  });

  it('shows three unverified channels for an older workspace instead of inferring zero counts', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?') ? ok(workspaceFixture(testBindings, false)) : noAnnouncements()));
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    await waitFor(() => expect(host.querySelectorAll('[data-daily-channel]')).toHaveLength(3));
    for (const channel of host.querySelectorAll('[data-daily-channel]')) {
      expect(channel.textContent).toContain('候选数量未知'); expect(channel.textContent).toContain('尚未提供三路结果合同');
    }
  });

  it('reloads the selected canonical GET after manual generation and does not claim a scheduled run', async () => {
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008&announcement_date=20261007');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/workspace/refresh?')) return ok(workspaceFixture(testBindings, false));
      return String(input).includes('/workspace?') ? ok(workspaceFixture()) : noAnnouncements();
    }); vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    const button = [...host.querySelectorAll('button')].find(node => node.textContent === '用既有材料生成计划')!;
    await waitFor(() => expect(button.disabled).toBe(false)); await fireEvent.click(button);
    await waitFor(() => expect(fetchMock.mock.calls.filter(call => String(call[0]).includes('/workspace?'))).toHaveLength(2));
    const workspaceCalls = fetchMock.mock.calls.filter(call => String(call[0]).includes('/workspace'));
    expect(workspaceCalls.map(call => call[1]?.method)).toEqual(['GET', 'POST', 'GET']);
    expect(String(workspaceCalls[2][0])).toContain('announcement_date=20261007');
    expect(host.querySelector('[data-daily-channels]')?.textContent).not.toContain('自然运行已验收');
    expect(host.querySelector('[data-daily-channels]')?.textContent).not.toContain('定时运行已完成');
  });

  it('aborts the older plan request and never lets its late response replace selected bindings', async () => {
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008&announcement_date=20261007');
    let resolveOld!: (value: Response) => void; let oldSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (!url.pathname.endsWith('/workspace')) return noAnnouncements();
      if (url.searchParams.get('date') === '20261008') { oldSignal = init?.signal as AbortSignal; return new Promise<Response>(resolve => { resolveOld = resolve; }); }
      return ok(workspaceFixture({ ...testBindings, plan_date: '20261009' }));
    }); vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    const dateInput = host.querySelector('input[aria-label="计划目标日"]') as HTMLInputElement;
    dateInput.value = '2026-10-09'; await fireEvent.change(dateInput);
    await waitFor(() => expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('计划日 20261009'));
    expect(oldSignal?.aborted).toBe(true); resolveOld(ok(workspaceFixture()));
    await Promise.resolve(); await Promise.resolve();
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('计划日 20261009');
    expect(new URL(window.location.href).searchParams.get('date')).toBe('20261006');
    expect(new URL(window.location.href).searchParams.get('announcement_date')).toBe('20261007');
  });

  it('keeps cancellation effective while the one-time legacy binding read is pending', async () => {
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008');
    let resolveBound!: (value: Response) => void; let boundSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      if (!url.pathname.endsWith('/workspace')) return noAnnouncements();
      if (!url.searchParams.has('selection_date')) return ok(workspaceFixture({ ...testBindings, selection_date: '20261008' }));
      boundSignal = init?.signal as AbortSignal;
      return new Promise<Response>(resolve => { resolveBound = resolve; });
    }); vi.stubGlobal('fetch', fetchMock);
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261008');
    await waitFor(() => expect(boundSignal).toBeDefined());
    const cancel = [...host.querySelectorAll('button')].find(node => node.textContent === '取消本次读取')!;
    await fireEvent.click(cancel); expect(boundSignal?.aborted).toBe(true);
    resolveBound(ok(workspaceFixture({ ...testBindings, announcement_date: '20261006' })));
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED'));
    expect(host.textContent).toContain('已取消本次读取');
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
  });
});
