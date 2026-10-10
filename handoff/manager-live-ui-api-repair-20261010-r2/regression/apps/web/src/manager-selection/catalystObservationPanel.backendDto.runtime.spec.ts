import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { validateManagerWorkspace, type ManagerWorkspace } from '../api/managerWorkspace';
import { mountCatalystObservations } from './catalystObservationPanel';

// Generate using tests/test_manager_semantic_identity_20261010.py with
// TASK1_BACKEND_FIXTURE_ROOT, then set V4_BACKEND_UI_FIXTURE_ROOT to that directory.
// Complete actual router/service DTOs are replayed unchanged; no live owner data.
const fixtureRoot = process.env.V4_BACKEND_UI_FIXTURE_ROOT;
let dispose: (() => void) | undefined;
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); document.body.replaceChildren(); window.history.replaceState({}, '', '/'); });

describe.skipIf(!fixtureRoot)('actual Python router/service DTO through normal validator and panel mount', () => {
  it.each([
    ['manifest_only_match', '20261009', 'CURRENT', 'MATCH'],
    ['materialized_catalyst_manifest_only_match', '20261009', 'CURRENT', 'MATCH'],
    ['consumed_content_changed', '20261009', 'STALE_INPUTS_CHANGED', 'CHANGED'],
    ['consumed_availability_rejected', '20261009', 'STALE_INPUTS_CHANGED', 'CHANGED'],
    ['legacy_missing_components', '20261009', 'STALE_INPUTS_CHANGED', 'CANNOT_CONFIRM'],
    ['date_bindings_changed', '20261008', 'STALE_INPUTS_CHANGED', 'CHANGED'],
  ])('preserves %s receipt status and source evidence without reshaping the DTO', async (name, selection, planStatus, diagnosticStatus) => {
    const raw = JSON.parse(readFileSync(resolve(fixtureRoot!, name + '.json'), 'utf8')) as ManagerWorkspace;
    const original = JSON.stringify(raw);
    expect(validateManagerWorkspace(raw, '20261009', { selection_date: selection, announcement_date: '20261008' })).toBe(raw);
    window.history.replaceState({}, '', `/?date=${selection}&plan_date=20261009&announcement_date=20261008`);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?')
      ? { ok: true, status: 200, json: async () => raw } as Response : { ok: false, status: 503 } as Response));
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261009');
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('READY'));
    expect(host.querySelectorAll('[data-daily-channel]')).toHaveLength(3);
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain(`来源/选股日 ${selection} · 公告日 20261008 · 计划日 20261009`);
    const business = host.querySelector('[aria-label="业务闭环状态"]')!;
    expect(business.textContent).toContain(planStatus);
    const diagnostic = business.querySelector('[data-plan-input-diagnostic]')!;
    expect(diagnostic.textContent).toContain(diagnosticStatus);
    if (name === 'manifest_only_match' || name === 'materialized_catalyst_manifest_only_match') {
      expect(diagnostic.querySelector('[data-first-identity-change]')).toBeNull();
      expect(diagnostic.textContent).toContain('仅 provenance；不作为陈旧原因');
      expect(raw.plan_product?.consumed).toBe(true);
    } else {
      expect(raw.plan_product?.consumed).toBe(false);
      if (name === 'legacy_missing_components') {
        expect(diagnostic.textContent).toContain('SAVED_COMPONENT_METADATA_MISSING');
        expect(diagnostic.textContent).toContain('不能定位');
      } else {
        const first = diagnostic.querySelector('[data-first-identity-change]')!;
        expect(first.closest('details')).toBeNull();
        if (name === 'date_bindings_changed') expect(first.textContent).toContain('date_bindings');
        else {
          expect(first.textContent).toContain('V35_RESEARCH_DATA_ROOT');
          expect(first.textContent).toContain('20261008');
          expect(first.textContent).toContain('research/archives/20261008.json');
        }
        const complete = diagnostic.querySelector('details[data-identity-changes]') as HTMLDetailsElement;
        expect(complete.open).toBe(false); await fireEvent.click(complete.querySelector('summary')!);
        await waitFor(() => expect(complete.textContent).toContain('outer.workspace_projection'));
      }
    }
    expect(JSON.stringify(raw)).toBe(original);
    expect(raw.RESEARCH_ONLY).toBe(true); expect(raw.production_allowed).toBe(false);
    expect(raw.buy_gate_updated).toBe(false); expect(raw.orders_sent).toBe(false);
  });
});
