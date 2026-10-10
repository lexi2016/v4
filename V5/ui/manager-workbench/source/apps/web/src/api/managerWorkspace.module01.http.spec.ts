import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isManagerWorkspaceReadOnly, requestManagerWorkspace, validateManagerWorkspace } from './managerWorkspace';

// The file is produced by tests/module01_export_http.py using the original
// owner, immutable store, actual module API and gateway. It is never the Mac
// 392-decision fixture. Without that explicit artifact this suite is NOT_RUN.
const path = process.env.V5_MODULE01_HTTP_RECEIPT;
afterEach(() => { vi.unstubAllGlobals(); });

describe.skipIf(!path)('module 01 actual HTTP DTO through complete frontend admission', () => {
  const receipt = path ? JSON.parse(readFileSync(path, 'utf8')) : null;

  it('keeps both real HTTP surfaces identical and binds the complete saved-run DTO', () => {
    expect(receipt.fixture_kind).toBe('SYNTHETIC_ORIGINAL_OWNER_INPUTS');
    expect(receipt.real_392_reused).toBe(false);
    expect(receipt.http_get_before_after_bytes_equal).toBe(true);
    expect(receipt.local_servers_closed).toBe(true);
    expect(receipt.responses.map((row: { surface: string }) => row.surface)).toEqual(['module', 'gateway']);
    for (const row of receipt.responses) {
      expect(row.status).toBe(200);
      expect(row.headers['X-V5-Workspace-Access']).toBe('READ_ONLY');
      // Do not simplify the validator or insert missing fields into its input.
      const value = validateManagerWorkspace(row.body, receipt.request.target_date);
      expect(value.plan_product).toMatchObject({ run_id: receipt.manager_run,
        sha256: receipt.manager_plan_sha256, consumed: true });
      expect(value.workspace_plan_attempt).toMatchObject({ run_id: receipt.manager_run });
      expect(value.production_allowed).toBe(false);
      expect(value.orders_sent).toBe(false);
      const announcement = value.daily_channels?.channels.find(channel => channel.channel === 'ANNOUNCEMENT');
      expect(announcement?.candidate_count).toBe(1);
      expect(announcement?.watch_count).toBe(1);
      expect(announcement?.pending_count).toBe(1);
      expect(announcement?.rows.map(row => row.symbol)).toEqual(['HK.00001', 'HK.00002']);
      expect(announcement?.rows.every(row => row.source_refs.length > 0)).toBe(true);
    }
    expect(receipt.responses[0].body_sha256).toBe(receipt.responses[1].body_sha256);
  });

  it('runs the real fetch response path once with the captured gateway body and headers', async () => {
    const gateway = receipt.responses[1];
    let calls = 0;
    vi.stubGlobal('fetch', async () => {
      calls++;
      return new Response(JSON.stringify(gateway.body), { status: gateway.status, headers: gateway.headers });
    });
    const value = await requestManagerWorkspace(receipt.request.target_date, new AbortController().signal, 'auto');
    expect(calls).toBe(1);
    expect(value.plan_product).toMatchObject({ run_id: receipt.manager_run });
    expect(value.workspace_plan_attempt).toMatchObject({ run_id: receipt.manager_run });
    expect(isManagerWorkspaceReadOnly(value)).toBe(true);
  });

  it('rejects wrong publication binding against the captured complete DTO', () => {
    expect(() => validateManagerWorkspace(receipt.responses[1].body, receipt.request.target_date,
      { announcement_date: '20261007' })).toThrow(/WORKSPACE_DAILY_DATE_BINDING_MISMATCH/);
  });
});
