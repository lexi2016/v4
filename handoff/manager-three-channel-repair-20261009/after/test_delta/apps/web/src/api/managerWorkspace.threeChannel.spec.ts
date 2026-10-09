import { afterEach, describe, expect, it, vi } from 'vitest';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { requestManagerWorkspace, validateManagerWorkspace, type JsonObject } from './managerWorkspace';
import { screeningStatus } from '../manager-selection/adapters/workspaceDecision';
import { renderDailyChannels } from '../manager-selection/dailyChannels';
import { workspaceFixture, testFlags } from '../manager-selection/dailyChannels.testHelper';

// Synthetic contract regression. No live source, API or browser is contacted.
const countFields = ['input_candidate_count', 'history_complete_count', 'history_pending_count',
  'strict_count', 'near_candidate_count', 'near_count', 'selected_count', 'panel_row_count', 'panel_code_count'];
const bindings = { plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' };
function unknownScreen(): JsonObject {
  return { ...testFlags, schema_version: 'v4.manager_research.rebound_v3_screen.v1',
    rule_version: '20260923_REBOUND_TWO_GATE_V1', target_trade_date: '20261009',
    verified_session: '20261009', status: 'CANNOT_CONFIRM', main_screen_ready: false,
    cards: [], strict: [], near: [], pending: [], input_identity: null, authority: null,
    coverage: { counts_known: false, ...Object.fromEntries(countFields.map(key => [key, null])) },
    gaps: ['SCREEN_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING'],
    data_context: { market_session: '20261009', screen_phase: 'POST_CLOSE_COMPLETED_SESSION',
      security_master_read: { status: 'CANNOT_CONFIRM', reason_code: 'HK_SECURITY_MASTER_EXACT_DATE_ENTRY_MISSING',
        requested_trade_date: '20261009', validation_stage: 'INDEX_ENTRY', latest_json_sha256: 'e'.repeat(64),
        entry_count: 1, latest_entry_date: '20261008', requested_entry_present: false } },
  };
}
function envelope(screen: JsonObject = unknownScreen()): JsonObject {
  const value = workspaceFixture(bindings) as unknown as JsonObject;
  value.market_screen = screen;
  value.plan_context = { ...(value.plan_context as JsonObject), plan_trade_date: '20261009',
    research_cutoff: '2026-10-09T17:23:00+08:00', market_session: '20261008' };
  value.read_context = { ...(value.read_context as JsonObject), as_of: '2026-10-09T17:23:00+08:00' };
  return value;
}

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); });

describe('three-channel exact-date screen unavailable contract', () => {
  it('accepts unknown counts without calling them a successful zero and preserves other channels', async () => {
    const value = envelope();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => value })));
    const result = await requestManagerWorkspace('20261009', new AbortController().signal, 'dynamic', bindings);
    expect(result.market_screen?.coverage.selected_count).toBeNull();
    expect(result.market_screen?.coverage.counts_known).toBe(false);
    expect(screeningStatus(result.market_screen)).toEqual({ complete: false,
      label: '筛选未完成 · 数量未知（不是扫描后零候选）' });
    const host = document.createElement('div'); document.body.append(host);
    renderDailyChannels(host, result.daily_channels, result.date_bindings!);
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('HK.00001');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('未知');
  });

  it.each([
    ['status-ready', (screen: JsonObject) => { screen.status = 'READY'; }],
    ['screen-ready', (screen: JsonObject) => { screen.main_screen_ready = true; }],
    ['claims-input-identity', (screen: JsonObject) => { screen.input_identity = 'a'.repeat(64); }],
    ['claims-zero', (screen: JsonObject) => { (screen.coverage as JsonObject).selected_count = 0; }],
    ['claims-input-count', (screen: JsonObject) => { (screen.coverage as JsonObject).input_candidate_count = 3; }],
    ['missing-count', (screen: JsonObject) => { delete (screen.coverage as JsonObject).panel_row_count; }],
    ['string-known', (screen: JsonObject) => { (screen.coverage as JsonObject).counts_known = 'false'; }],
    ['pending-row', (screen: JsonObject) => { screen.pending = [{}]; }],
  ])('rejects an unavailable DTO that makes an unsupported claim: %s', (_label, mutate) => {
    const screen = unknownScreen(); mutate(screen);
    expect(() => validateManagerWorkspace(envelope(screen), '20261009')).toThrow();
  });

  it('preserves a verified-input legitimate zero and rejects null counts in that branch', () => {
    const screen = unknownScreen();
    Object.assign(screen, { status: 'READY', main_screen_ready: true, input_identity: 'b'.repeat(64), gaps: [] });
    screen.coverage = { counts_known: true, ...Object.fromEntries(countFields.map(key => [key, 0])) };
    expect(() => validateManagerWorkspace(envelope(screen), '20261009')).not.toThrow();
    (screen.coverage as JsonObject).selected_count = null;
    expect(() => validateManagerWorkspace(envelope(screen), '20261009')).toThrow();
  });

  it('retains compatibility with the older numeric unavailable DTO', () => {
    const screen = unknownScreen();
    screen.coverage = Object.fromEntries(countFields.map(key => [key, 0]));
    expect(() => validateManagerWorkspace(envelope(screen), '20261009')).not.toThrow();
    expect(screeningStatus(screen as never).complete).toBe(false);
  });

  it.each(['hk_missing', 'hk_valid'])('accepts the actual Python reader DTO for %s', fixture => {
    const root = process.env.V4_TEST_SOURCE_ROOT || resolve(process.cwd(), '../..');
    const raw = execFileSync(process.env.V4_TEST_PYTHON || 'python3',
      [resolve(root, 'tests/manager_three_channel_ui_fixture.py'), '--fixture', fixture],
      { cwd: root, encoding: 'utf8', timeout: 30_000,
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
    const result = JSON.parse(raw) as JsonObject;
    expect(result.scope).toBe('SYNTHETIC_ACTUAL_READER_DTO');
    expect(result.owner_module).toBe(resolve(root, 'upstreams/v3_shared_data/shared_data/hk_security_master.py'));
    const screen = result.market_screen as JsonObject;
    expect(() => validateManagerWorkspace(envelope(screen), '20261009')).not.toThrow();
    const coverage = screen.coverage as JsonObject;
    if (fixture === 'hk_missing') {
      expect(screen.status).toBe('CANNOT_CONFIRM');
      expect(coverage.selected_count).toBeNull();
      expect(screeningStatus(screen as never).complete).toBe(false);
    } else {
      expect(screen.status).toBe('READY_WITH_GAPS');
      expect(coverage.input_candidate_count).toBe(1);
      expect(coverage.history_pending_count).toBe(1);
      expect((screen.pending as JsonObject[])[0].volume_unit_status).toBe('NOT_PROVEN');
    }
  });
});
