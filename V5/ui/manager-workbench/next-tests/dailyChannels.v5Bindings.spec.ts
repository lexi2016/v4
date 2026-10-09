/** Install beside the original dailyChannels.testHelper in the verified UI source.
 * Uses original API validation and mount, with transport fixtures only.
 */
import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountCatalystObservations } from './catalystObservationPanel';
import { workspaceFixture } from './dailyChannels.testHelper';

const ok = (value: unknown) => ({ ok: true, status: 200, json: async () => value }) as Response;
const unavailable = () => ({ ok: false, status: 503,
  json: async () => ({ status: 'CANNOT_CONFIRM', reason_codes: ['MODULE_RESULT_NOT_AVAILABLE'] }) }) as Response;
let dispose: (() => void) | undefined;
afterEach(() => {
  dispose?.(); dispose = undefined; vi.unstubAllGlobals();
  window.history.replaceState({}, '', '/'); document.body.replaceChildren();
});
const mount = () => {
  const host = document.createElement('div'); document.body.append(host);
  dispose = mountCatalystObservations(host, '20261009'); return host;
};

describe('V5 original workspace date intent and truthful unavailable state', () => {
  it('adopts server default dates and rereads the same unbound query without inventing explicit selections', async () => {
    window.history.replaceState({}, '', '/?date=20261009');
    const calls: URL[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (!url.pathname.endsWith('/workspace')) return unavailable();
      calls.push(url);
      // No fabricated response for a query that was never published.
      if (url.searchParams.has('selection_date') || url.searchParams.has('announcement_date')) return unavailable();
      return ok(workspaceFixture({ plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' }));
    }));
    const host = mount();
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('READY'));
    expect(calls).toHaveLength(1);
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('公告日 20261008');
    const reread = [...host.querySelectorAll('button')].find(button => button.textContent === '读取更新')!;
    await fireEvent.click(reread);
    await waitFor(() => expect(calls).toHaveLength(2));
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('READY'));
    for (const call of calls) expect(Object.fromEntries(call.searchParams)).toEqual({ date: '20261009', view: 'auto' });
  });

  it('preserves an explicitly chosen publication date instead of silently adopting a different response', async () => {
    window.history.replaceState({}, '', '/?date=20261009&selection_date=20261009&announcement_date=20261009');
    const calls: URL[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (!url.pathname.endsWith('/workspace')) return unavailable();
      calls.push(url);
      return ok(workspaceFixture({ plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' }));
    }));
    const host = mount();
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED'));
    expect(calls).toHaveLength(1);
    expect(calls[0].searchParams.get('announcement_date')).toBe('20261009');
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
  });

  it('does not describe a missing published response as proven concurrency exhaustion', async () => {
    window.history.replaceState({}, '', '/?date=20261009');
    vi.stubGlobal('fetch', vi.fn(async () => unavailable()));
    const host = mount();
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED'));
    expect(host.textContent).not.toContain('并发上限');
    expect(host.textContent).toMatch(/暂不可用|结果.*未|尚无|未就绪/);
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
  });
});
