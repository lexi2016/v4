import { afterEach, describe, expect, it, vi } from 'vitest';
import { refreshManagerWorkspace, validateManagerWorkspace, type JsonObject } from './managerWorkspace';
import { testBindings, testFlags, workspaceFixture } from '../manager-selection/dailyChannels.testHelper';

// Portable synthetic contract tests. This is not the Mac saved-run fixture and
// does not replace managerWorkspace.currentRecovery.spec.ts.
const savedWorkspace = (extension = true) => {
  const value = workspaceFixture(testBindings, extension);
  value.plan_product = { status: 'CURRENT', consumed: true, run_id: '1'.repeat(32),
    sha256: '2'.repeat(64), generated_at: '2026-10-10T03:04:05.123456+00:00',
    execution_kind: 'MANUAL_REFRESH', original_owner: 'ManagerResearchJobService.refresh_workspace_plan' };
  value.workspace_plan_attempt = { ...testFlags, schema_version: 'v4.manager_research.workspace_attempt.v1',
    sha256: '5'.repeat(64), state: 'PARTIAL', target_trade_date: testBindings.plan_date,
    run_id: '1'.repeat(32), input_identity: value.input_identity, execution_kind: 'MANUAL_REFRESH',
    owner: 'ManagerResearchJobService.refresh_workspace_plan', failure_reasons: ['SYNTHETIC_SCOPE_GAP'],
    started_at: '2026-10-10T03:04:00+00:00', finished_at: '2026-10-10T03:04:06+00:00' };
  return value;
};
const ok = (value: unknown): Response => new Response(JSON.stringify(value), {
  status: 200, headers: { 'Content-Type': 'application/json' },
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('module 01 original POST contract admission', () => {
  it('sends independent selected days on the existing POST and consumes the full valid response', async () => {
    const calls: { url: URL; method: string | undefined }[] = [];
    const value = savedWorkspace();
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: new URL(String(input), 'http://localhost'), method: init?.method });
      return ok(value);
    });
    const result = await refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal,
      { selection_date: '2026-10-06', announcement_date: '2026-10-07' });
    expect(result.plan_product).toEqual(value.plan_product);
    expect(calls.map(call => [call.url.pathname, call.method])).toEqual([
      ['/api/v4/manager/research/workspace/refresh', 'POST'],
    ]);
    expect(Object.fromEntries(calls[0].url.searchParams)).toEqual({
      date: '20261008', selection_date: '20261006', announcement_date: '20261007',
    });
  });

  it('rejects a successful POST body for another requested publication day', async () => {
    vi.stubGlobal('fetch', async () => ok(savedWorkspace()));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal,
      { selection_date: '20261006', announcement_date: '20261006' }))
      .rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
  });

  it('rejects a missing response binding when a selected-day request requires one', async () => {
    vi.stubGlobal('fetch', async () => ok(savedWorkspace(false)));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal,
      { selection_date: '20261006', announcement_date: '20261007' }))
      .rejects.toThrow('WORKSPACE_DAILY_DATE_BINDING_INVALID');
  });

  it('does not let the full validator bypass explicit bindings when the optional projection is absent', () => {
    expect(() => validateManagerWorkspace(savedWorkspace(false), testBindings.plan_date,
      { announcement_date: '20261007' })).toThrow('WORKSPACE_DAILY_DATE_BINDING_INVALID');
  });

  it('rejects an impossible plan day before sending any POST', async () => {
    let requests = 0;
    vi.stubGlobal('fetch', async () => { requests++; return ok(savedWorkspace()); });
    await expect(refreshManagerWorkspace('20260230', new AbortController().signal))
      .rejects.toThrow('WORKSPACE_DATE_REQUIRED');
    expect(requests).toBe(0);
  });

  it('preserves the existing two-argument POST for a complete legacy result without date projection', async () => {
    const value = savedWorkspace(false);
    vi.stubGlobal('fetch', async () => ok(value));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal))
      .resolves.toEqual(value);
  });

  it.each([
    ['missing terminal', (value: JsonObject) => { delete value.workspace_plan_attempt; }],
    ['another run terminal', (value: JsonObject) => { (value.workspace_plan_attempt as JsonObject).run_id = '3'.repeat(32); }],
    ['running rather than terminal', (value: JsonObject) => { (value.workspace_plan_attempt as JsonObject).state = 'RUNNING'; }],
    ['different input identity', (value: JsonObject) => { (value.workspace_plan_attempt as JsonObject).input_identity = '4'.repeat(64); }],
    ['unconsumed product', (value: JsonObject) => { (value.plan_product as JsonObject).consumed = false; }],
  ])('does not declare a successful POST from %s', async (_name, mutate) => {
    const value = savedWorkspace(false); mutate(value);
    vi.stubGlobal('fetch', async () => ok(value));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal))
      .rejects.toThrow(/WORKSPACE_REFRESH_(?:PRODUCT|TERMINAL)_INVALID/);
  });

  it('keeps the original safety validator on a POST with matching dates and terminal', async () => {
    const value = savedWorkspace(); value.orders_sent = true;
    vi.stubGlobal('fetch', async () => ok(value));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal, testBindings))
      .rejects.toThrow('WORKSPACE_SAFETY_INVALID');
  });

  it.each([
    ['missing schema', { schema_version: undefined }],
    ['different schema', { schema_version: 'workspace_attempt.v0' }],
    ['missing terminal SHA', { sha256: undefined }],
    ['malformed terminal SHA', { sha256: 'not-a-sha256' }],
    ['missing start', { started_at: undefined }],
    ['start without timezone', { started_at: '2026-10-10T03:04:00' }],
    ['missing finish', { finished_at: undefined }],
    ['finish without timezone', { finished_at: '2026-10-10T03:04:06' }],
    ['finish before start', { finished_at: '2026-10-10T03:03:59+00:00' }],
    ['product before start', { started_at: '2026-10-10T03:04:05.500000+00:00' }],
    ['product after finish', { finished_at: '2026-10-10T03:04:05.100000+00:00' }],
    ['missing failure reasons', { failure_reasons: undefined }],
    ['partial without a recorded gap', { failure_reasons: [] }],
    ['success with partial failure reasons', { state: 'SUCCEEDED' }],
  ])('rejects an incomplete terminal envelope: %s', async (_name, fields) => {
    const value = savedWorkspace(false);
    Object.assign(value.workspace_plan_attempt as JsonObject, fields);
    vi.stubGlobal('fetch', async () => ok(value));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal))
      .rejects.toThrow('WORKSPACE_REFRESH_TERMINAL_INVALID');
  });

  it('rejects a matching but unrecognized product and terminal execution kind', async () => {
    const value = savedWorkspace(false);
    (value.plan_product as JsonObject).execution_kind = 'UNKNOWN_KIND';
    (value.workspace_plan_attempt as JsonObject).execution_kind = 'UNKNOWN_KIND';
    vi.stubGlobal('fetch', async () => ok(value));
    await expect(refreshManagerWorkspace(testBindings.plan_date, new AbortController().signal))
      .rejects.toThrow('WORKSPACE_REFRESH_TERMINAL_INVALID');
  });
});
