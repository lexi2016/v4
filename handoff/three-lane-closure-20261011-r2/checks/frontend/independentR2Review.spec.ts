/** Independent reviewer synthetic boundary probes; no candidate source edits. */
import { expect, it } from 'vitest';
import { renderDailyChannels, validateDailyChannels } from '../src/manager-selection/dailyChannels';
import { testBindings, workspaceFixture } from '../src/manager-selection/dailyChannels.testHelper';
import { validateManagerWorkspace } from '../src/api/managerWorkspace';
import applicantWorkspace from '../src/manager-selection/fixtures/three_lane_r2/frontend_H5354_workspace.json';

function archive() {
  const value = workspaceFixture();
  const id = 'a'.repeat(32); const generated = '2026-10-08T07:30:00+08:00';
  value.plan_product = { status: 'CURRENT', consumed: true,
    original_owner: 'ManagerResearchJobService.refresh_workspace_plan', run_id: id,
    sha256: '8'.repeat(64), generated_at: generated, execution_kind: 'MANUAL_REFRESH' };
  const exact = { run_id: id, target_trade_date: testBindings.plan_date,
    input_identity: value.input_identity, owner: 'ManagerResearchJobService.refresh_workspace_plan',
    state: 'SUCCEEDED_EMPTY', execution_kind: 'MANUAL_REFRESH' };
  value.workspace_plan_product_attempt = { ...exact };
  value.workspace_plan_attempt = { ...exact };
  Object.assign(value.daily_channels!.channels[2], { status: 'READY_EMPTY', rows: [],
    candidate_count: 0, pending_count: 0, input_identity: '9'.repeat(64), run_id: id,
    generated_at: generated, product_sha256: '8'.repeat(64), execution_kind: 'MANUAL_REFRESH' });
  return value;
}

it.each([
  ['run_id', 'b'.repeat(32)], ['target_trade_date', '20261009'],
  ['input_identity', 'e'.repeat(64)], ['owner', 'DIFFERENT_OWNER'],
  ['state', 'FAILED'], ['execution_kind', 'SCHEDULED_PREOPEN'],
])('does not fall back to matching latest when exact attempt has wrong %s', (key, replacement) => {
  const value = archive();
  (value.workspace_plan_product_attempt as Record<string, unknown>)[key] = replacement;
  expect(() => validateDailyChannels(value.daily_channels, testBindings, value)).toThrow('WORKSPACE_DAILY_RUN_REFERENCE_INVALID');
});

it('retains the legacy latest-attempt fallback only when exact field is absent', () => {
  const value = archive(); delete value.workspace_plan_product_attempt;
  expect(validateDailyChannels(value.daily_channels, testBindings, value)).toBe(value.daily_channels);
});

it('does not treat explicit null exact attempt as an absent legacy field', () => {
  const value = archive(); value.workspace_plan_product_attempt = null;
  expect(() => validateDailyChannels(value.daily_channels, testBindings, value)).toThrow('WORKSPACE_DAILY_OBJECT_INVALID');
});

it('rejects channel product SHA disagreement even with matching exact attempt', () => {
  const value = archive(); value.plan_product.sha256 = '7'.repeat(64);
  expect(() => validateDailyChannels(value.daily_channels, testBindings, value)).toThrow('WORKSPACE_DAILY_RUN_REFERENCE_INVALID');
});

it('keeps a later failed latest attempt intact while admitting the exact archived result', () => {
  const value = archive(); value.workspace_plan_attempt = {run_id: 'f'.repeat(32), state: 'FAILED'};
  const before = JSON.stringify(value);
  expect(validateDailyChannels(value.daily_channels, testBindings, value)).toBe(value.daily_channels);
  expect(JSON.stringify(value)).toBe(before);
});

it('renders retained risk notes of an unmapped source on the first screen', () => {
  const raw = structuredClone(applicantWorkspace);
  const channel = raw.daily_channels.channels.find(row => row.channel === 'ANNOUNCEMENT')!;
  (channel.unmapped_references![0].risk_notes as string[]).push('独立审查：未映射源退市风险');
  const value = validateManagerWorkspace(raw, '20261008');
  const host = document.createElement('section'); renderDailyChannels(host, value.daily_channels, value.date_bindings);
  const announcement = host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')!;
  expect(announcement.textContent).toContain('H5354');
  expect(announcement.querySelector('[data-daily-symbol="HK.05354"]')).toBeNull();
  expect(announcement.textContent).toContain('独立审查：未映射源退市风险');
});
