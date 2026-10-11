/** Synthetic contracts through the real validator/DOM, not live 8873 evidence. */
import { expect, it } from 'vitest';
import { renderDailyChannels, validateDailyChannels } from './dailyChannels';
import { dailyFixture, testBindings, workspaceFixture } from './dailyChannels.testHelper';
import { validateManagerWorkspace } from '../api/managerWorkspace';
import applicantWorkspace from './fixtures/three_lane_r2/frontend_H5354_workspace.json';
import retrospectiveWorkspace from './fixtures/three_lane_r2/frontend_retrospective_workspace.json';

it.each([['applicant',applicantWorkspace],['retrospective',retrospectiveWorkspace]])(
  'admits the independently captured full original-owner API %s response and renders its real summary', (_name, raw) => {
    const value = validateManagerWorkspace(raw, '20261008');
    const host = document.createElement('section'); renderDailyChannels(host, value.daily_channels, value.date_bindings);
    const shown = host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')!;
    if (_name === 'applicant') {
      expect(shown.textContent).toContain('H5354');
      expect(shown.textContent).toContain('候选数量未知');
      expect(shown.textContent).not.toContain('已核空集');
    } else {
      expect(shown.textContent).toContain('候选 1 只');
      expect(shown.textContent).toContain(raw.daily_channels.channels[0].product_sha256);
    }
  });

it('binds archived lane to the exact product attempt and leaves later failed status visible', () => {
  const value = workspaceFixture(); const id = 'a'.repeat(32); const generated = '2026-10-08T07:30:00+08:00';
  value.plan_product = { status:'CURRENT', consumed:true, original_owner:'ManagerResearchJobService.refresh_workspace_plan',
    run_id:id, sha256:'8'.repeat(64), generated_at:generated, execution_kind:'MANUAL_REFRESH' };
  value.workspace_plan_attempt = { run_id:'b'.repeat(32), state:'FAILED', failure_reasons:['LATER_FAILURE'] };
  const exactAttempt = { run_id:id, target_trade_date:testBindings.plan_date,
    input_identity:value.input_identity, owner:'ManagerResearchJobService.refresh_workspace_plan',
    state:'SUCCEEDED_EMPTY', execution_kind:'MANUAL_REFRESH' };
  value.workspace_plan_product_attempt = exactAttempt;
  const channel = value.daily_channels!.channels[2];
  Object.assign(channel, {status:'READY_EMPTY', rows:[], candidate_count:0, pending_count:0,
    input_identity:'9'.repeat(64), run_id:id, generated_at:generated, product_sha256:'8'.repeat(64), execution_kind:'MANUAL_REFRESH'});
  expect(validateDailyChannels(value.daily_channels, testBindings, value)).toBe(value.daily_channels);
  expect(value.workspace_plan_attempt.state).toBe('FAILED');
  exactAttempt.run_id = 'c'.repeat(32);
  expect(() => validateDailyChannels(value.daily_channels, testBindings, value)).toThrow('WORKSPACE_DAILY_RUN_REFERENCE_INVALID');
});

it('rejects an unarchived oversold successful zero', () => {
  const value = dailyFixture();
  Object.assign(value.channels[2], {status:'READY_EMPTY', rows:[], candidate_count:0, pending_count:0, input_identity:'9'.repeat(64)});
  expect(() => validateDailyChannels(value, testBindings)).toThrow('WORKSPACE_DAILY_EMPTY_ARCHIVE_REQUIRED');
});

it('shows unmapped original announcement identity and retained risks without inventing a ticker', () => {
  const value = validateDailyChannels(dailyFixture(), testBindings); const channel = value.channels[0];
  channel.status='PARTIAL'; channel.gaps=['ANNOUNCEMENT_SOURCE_SYMBOL_UNMAPPED'];
  channel.rows[0].risk_notes=['原始退市风险'];
  channel.unmapped_references=[{stock_code:'H5354', stock_name:'源公司', research_status:'SELECTED',
    risk_notes:['未映射公司的原始退市风险 <script>literal</script>'], product_sha256:channel.product_sha256}];
  const host=document.createElement('section'); renderDailyChannels(host, value, testBindings);
  expect(host.textContent).toContain('H5354');
  expect(host.textContent).toContain('原始退市风险');
  expect(host.textContent).toContain('未映射公司的原始退市风险 <script>literal</script>');
  expect(host.querySelector('script')).toBeNull();
  expect(host.textContent).toContain('未映射源代码');
  expect(host.querySelector('[data-daily-symbol="HK.05354"]')).toBeNull();
});
