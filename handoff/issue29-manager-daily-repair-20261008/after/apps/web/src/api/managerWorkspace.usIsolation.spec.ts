import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestManagerWorkspace, validateManagerWorkspace, type JsonObject } from './managerWorkspace';
import { renderDailyChannels } from '../manager-selection/dailyChannels';
import { workspaceFixture } from '../manager-selection/dailyChannels.testHelper';

// The provider failure is synthetic; the DTO is produced by the real Python
// manager owner and parsed by the unchanged, frozen Mac TypeScript validator.
// Vitest is invoked from apps/web, like the existing frontend regressions.
const projectRoot = process.env.V4_TEST_SOURCE_ROOT || resolve(process.cwd(), '../..');
const fixture = resolve(projectRoot, 'tests/test_manager_us_mapping_isolation_20261008.py');
const python = process.env.V4_TEST_PYTHON || 'python3';
const values = new Map<string, JsonObject>();
function ownerValue(date: string, kind: string): JsonObject {
  const key = `${date}|${kind}`;
  if (!values.has(key)) {
    const text = execFileSync(python, [fixture, '--fixture', date, kind], {
      cwd: projectRoot, encoding: 'utf8', timeout: 20_000, maxBuffer: 2 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: `${projectRoot}:${projectRoot}/upstreams` },
    });
    values.set(key, JSON.parse(text) as JsonObject);
  }
  return structuredClone(values.get(key)!);
}
const response = (value: unknown) => ({ ok: true, status: 200, json: async () => value }) as Response;
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren(); window.history.replaceState({}, '', '/');
});

describe('Issue 29 original US reader isolation across Python and Mac API contracts', () => {
  it.each([
    ['20260930', 'missing_module'], ['20260930', 'reader_failed'],
    ['20261008', 'missing_module'], ['20261008', 'reader_failed'],
  ])('keeps a %s workspace parseable when the US reader is %s', (date, kind) => {
    const value = ownerValue(date, kind);
    expect(() => validateManagerWorkspace(value, date)).not.toThrow();
    const mapping = value.us_mapping_research as JsonObject;
    expect((mapping.daily_run as JsonObject).status).toBe('CANNOT_CONFIRM');
    expect(((mapping.daily_run as JsonObject).coverage as JsonObject).matched_hk_relation_count).toBeNull();
  });

  it('keeps the original announcement row visible through the real request and first-screen renderer', async () => {
    const value = workspaceFixture();
    value.us_mapping_research = ownerValue('20261008', 'reader_failed').us_mapping_research as never;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?')
      ? response(value) : ({ ok: false, status: 503 } as Response));
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState({}, '', '/?date=20261006&plan_date=20261008&announcement_date=20261007');
    const parsed = await requestManagerWorkspace('20261008', new AbortController().signal, 'auto',
      { selection_date: '20261006', announcement_date: '20261007' });
    expect(parsed.us_mapping_research?.daily_run.status).toBe('CANNOT_CONFIRM');
    const host = document.createElement('div'); document.body.append(host);
    renderDailyChannels(host, parsed.daily_channels, parsed.date_bindings!);
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('HK.00001');
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('原研究理由：已审阅的扩产事件。');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')).not.toBeNull();
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('候选数量未知');
    expect(host.textContent).not.toContain('WORKSPACE_RESEARCH_US_MAPPING');
  });

  it('still rejects a wrong-day US field and a forged zero-result status', () => {
    const wrongDay = ownerValue('20261008', 'reader_failed');
    (wrongDay.us_mapping_research as JsonObject).target_trade_date = '20260930';
    expect(() => validateManagerWorkspace(wrongDay, '20261008')).toThrow();
    const falseZero = ownerValue('20261008', 'reader_failed');
    ((falseZero.us_mapping_research as JsonObject).daily_run as JsonObject).status = 'VALID_EMPTY';
    expect(() => validateManagerWorkspace(falseZero, '20261008')).toThrow();
  });
});
