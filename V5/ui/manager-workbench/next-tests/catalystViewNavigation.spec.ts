/** Regression for the Mac-observed dynamic -> auto browser refresh failure. */
import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountCatalystObservations } from './catalystObservationPanel';

let dispose: (() => void) | undefined;
afterEach(() => {
  dispose?.(); dispose = undefined; vi.unstubAllGlobals();
  window.history.replaceState({}, '', '/'); document.body.replaceChildren();
});
const setup = () => {
  const reads: URL[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.endsWith('/workspace')) reads.push(url);
    return { ok: false, status: 503, json: async () => ({ reason_codes: ['MODULE_RESULT_NOT_AVAILABLE'] }) } as Response;
  }));
  const mount = () => {
    const host = document.createElement('div'); document.body.append(host);
    dispose = mountCatalystObservations(host, '20261008'); return host;
  };
  return { reads, mount };
};
const selector = (host: HTMLElement) => host.querySelector<HTMLSelectElement>('[aria-label="历史或现在回看"]')!;
const settled = (host: HTMLElement) => waitFor(() => expect(host.querySelector('[data-read-state]')?.getAttribute('data-read-state')).toBe('FAILED'));

describe('workspace view URL navigation', () => {
  it('retains dynamic and explicit dates across a fresh mount without showing fabricated auto results', async () => {
    window.history.replaceState({ retained: true }, '', '/?date=20261008&plan_date=20261008&selection_date=20261008&announcement_date=20261007&view=dynamic#research');
    const { reads, mount } = setup();
    let host = mount(); await settled(host);
    expect(selector(host).value).toBe('dynamic');
    dispose?.(); host = mount(); await settled(host);
    expect(reads).toHaveLength(2);
    for (const read of reads) expect(Object.fromEntries(read.searchParams)).toEqual({ date: '20261008', view: 'dynamic', selection_date: '20261008', announcement_date: '20261007' });
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
  });

  it.each(['auto', 'unknown', 'DYNAMIC', ''])('only admits the existing view whitelist: %s', async raw => {
    window.history.replaceState({}, '', `/?date=20261008&view=${raw}`);
    const { reads, mount } = setup(); const host = mount(); await settled(host);
    expect(selector(host).value).toBe('auto');
    expect(Object.fromEntries(reads[0].searchParams)).toEqual({ date: '20261008', view: 'auto' });
  });

  it('persists a view choice, preserves unrelated URL state, and follows back and forward without binding server defaults', async () => {
    window.history.replaceState({ retained: true }, '', '/?date=20261008&plan_date=20261008&extra=keep#research');
    const { reads, mount } = setup(); const host = mount(); await settled(host);
    await fireEvent.update(selector(host), 'dynamic'); await settled(host);
    expect(new URL(window.location.href).searchParams.get('view')).toBe('dynamic');
    expect(window.location.hash).toBe('#research');
    expect(window.history.state).toEqual({ retained: true });
    expect(new URL(window.location.href).searchParams.get('extra')).toBe('keep');
    window.history.back();
    await waitFor(() => expect(reads).toHaveLength(3)); await settled(host);
    expect(selector(host).value).toBe('auto');
    window.history.forward();
    await waitFor(() => expect(reads).toHaveLength(4)); await settled(host);
    expect(selector(host).value).toBe('dynamic');
    expect(reads.map(read => Object.fromEntries(read.searchParams))).toEqual([
      { date: '20261008', view: 'auto' }, { date: '20261008', view: 'dynamic' },
      { date: '20261008', view: 'auto' }, { date: '20261008', view: 'dynamic' },
    ]);
    dispose?.(); dispose = undefined;
    window.history.back();
    await waitFor(() => expect(new URL(window.location.href).searchParams.get('view')).toBeNull());
    expect(reads).toHaveLength(4);
  });

  it('restores explicit dates and clears explicit intent when navigating back to an unbound URL', async () => {
    window.history.replaceState({}, '', '/?date=20261008&view=dynamic');
    const { reads, mount } = setup(); const host = mount(); await settled(host);
    window.history.pushState({}, '', '/?date=20261006&plan_date=20261009&selection_date=20261007&announcement_date=20261006&view=auto');
    window.dispatchEvent(new PopStateEvent('popstate')); await settled(host);
    expect(Object.fromEntries(reads[1].searchParams)).toEqual({ date: '20261009', view: 'auto', selection_date: '20261007', announcement_date: '20261006' });
    expect(host.querySelector<HTMLInputElement>('[aria-label="计划目标日"]')!.value).toBe('2026-10-09');
    window.history.back();
    await waitFor(() => expect(reads).toHaveLength(3)); await settled(host);
    expect(Object.fromEntries(reads[2].searchParams)).toEqual({ date: '20261008', view: 'dynamic' });
    expect(host.querySelector<HTMLInputElement>('[aria-label="计划目标日"]')!.value).toBe('2026-10-08');
  });
});
