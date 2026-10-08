import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace, type JsonObject } from '../api/managerWorkspace';
import { readDailyDateBindings, renderDailyChannels, validateDailyChannels } from './dailyChannels';
import { dailyFixture, testBindings, workspaceFixture } from './dailyChannels.testHelper';

describe('daily channel identities and safe display', () => {
  it('keeps the actual panel day separate from all three requested dates', () => {
    const bindings = { plan_date: '20261009', selection_date: '20261005', announcement_date: '20261006' };
    const value = validateDailyChannels(dailyFixture(bindings), bindings);
    const host = document.createElement('section'); renderDailyChannels(host, value, bindings);
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toBe('来源/选股日 20261005 · 公告日 20261006 · 计划日 20261009');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('数据日 20261007');
  });

  it('uses literal text for names and reasons and preserves original row order', () => {
    const value = dailyFixture(); const announcement = value.channels[0];
    announcement.rows = [
      { ...announcement.rows[0], symbol: 'HK.09999', name: '<img src=x onerror="alert(1)">', reason: '<script>window.unsafe=true</script>' },
      { ...announcement.rows[0], symbol: 'HK.00001', name: '原顺序第二名' },
    ]; announcement.candidate_count = 2;
    const before = JSON.stringify(value); const host = document.createElement('section');
    renderDailyChannels(host, validateDailyChannels(value, testBindings), testBindings);
    expect([...host.querySelectorAll('[data-daily-symbol]')].map(node => node.getAttribute('data-daily-symbol'))).toEqual(['HK.09999', 'HK.00001']);
    expect(host.textContent).toContain('<script>window.unsafe=true</script>');
    expect(host.querySelector('img, script')).toBeNull(); expect(host.querySelector('pre')).toBeNull();
    const detail = host.querySelector('details')!; detail.open = true; detail.dispatchEvent(new Event('toggle'));
    expect(detail.querySelector('pre')?.textContent).toContain('<script>window.unsafe=true</script>');
    expect(detail.querySelector('script')).toBeNull(); expect(JSON.stringify(value)).toBe(before);
  });

  it('retains null reason/run as unprovided without rejecting an admitted imported row', () => {
    const value = dailyFixture(); const channel = value.channels[0] as unknown as JsonObject;
    channel.run_id = null; (channel.product_checks as JsonObject[])[0].evidence_run_id = null;
    const row = (channel.rows as JsonObject[])[0]; row.run_id = null; row.reason = null;
    const host = document.createElement('section'); renderDailyChannels(host, validateDailyChannels(value, testBindings), testBindings);
    expect(host.querySelector('[data-daily-symbol]')?.textContent).toContain('选入理由未提供/待核');
    expect(host.querySelector('[data-daily-symbol]')?.textContent).toContain('运行编号 未提供/待核');
  });

  it('binds each imported product to its own run when the channel contains two runs', () => {
    const value = dailyFixture(); const channel = value.channels[0] as unknown as JsonObject;
    const rows = channel.rows as JsonObject[]; const checks = channel.product_checks as JsonObject[];
    rows.push({ ...rows[0], symbol: 'HK.00002', product_sha256: '7'.repeat(64), run_id: 'second-synthetic-import', generated_at: '2026-10-08T07:06:00+08:00' });
    checks.push({ ...checks[0], product_sha256: '7'.repeat(64), evidence_run_id: 'second-synthetic-import', owner_available_at: '2026-10-08T07:06:00+08:00' });
    channel.run_id = null; channel.product_sha256 = null; channel.generated_at = '2026-10-08T07:06:00+08:00'; channel.candidate_count = 2;
    const host = document.createElement('section'); renderDailyChannels(host, validateDailyChannels(value, testBindings), testBindings);
    expect(host.querySelector('[data-daily-symbol="HK.00001"]')?.textContent).toContain('synthetic-import-run');
    expect(host.querySelector('[data-daily-symbol="HK.00002"]')?.textContent).toContain('second-synthetic-import');
    rows[1].run_id = rows[0].run_id;
    expect(() => validateDailyChannels(value, testBindings)).toThrow('WORKSPACE_DAILY_RUN_REFERENCE_INVALID');
  });

  it('requires any declared plan run to match the consumed product and exact attempt', () => {
    const value = workspaceFixture(); const runId = 'synthetic-manual-plan'; const generated = '2026-10-08T07:30:00+08:00';
    value.plan_product = { status: 'CURRENT', consumed: true, original_owner: 'ManagerResearchJobService.refresh_workspace_plan',
      run_id: runId, generated_at: generated, sha256: '8'.repeat(64), execution_kind: 'MANUAL_REFRESH' };
    value.workspace_plan_attempt = { run_id: runId, target_trade_date: testBindings.plan_date, input_identity: value.input_identity,
      owner: 'ManagerResearchJobService.refresh_workspace_plan', state: 'SUCCEEDED', execution_kind: 'MANUAL_REFRESH' };
    const channel = value.daily_channels!.channels[1];
    Object.assign(channel, { run_id: runId, generated_at: generated, product_sha256: '8'.repeat(64), execution_kind: 'MANUAL_REFRESH' });
    expect(validateManagerWorkspace(value, '20261008')).toBe(value);
    const host = document.createElement('section'); renderDailyChannels(host, value.daily_channels, testBindings);
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('手工生成');
    channel.execution_kind = 'SCHEDULED_PREOPEN';
    expect(() => validateManagerWorkspace(value, '20261008')).toThrow('WORKSPACE_DAILY_RUN_REFERENCE_INVALID');
  });

  it('distinguishes an owner-confirmed empty set from unknown coverage', () => {
    const value = dailyFixture(); const announcement = value.channels[0];
    announcement.rows = []; announcement.status = 'READY_EMPTY'; announcement.candidate_count = 0;
    const host = document.createElement('section'); renderDailyChannels(host, validateDailyChannels(value, testBindings), testBindings);
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('已核空集');
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('候选 0 只');
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('候选数量未知');
  });

  it('keeps the legacy date fallback and gives announcement_date precedence over publication_date', () => {
    expect(readDailyDateBindings(new URLSearchParams('date=20261006&plan_date=20261008'), '20261009')).toEqual({
      bindings: { plan_date: '20261008', selection_date: '20261006', announcement_date: '20261006' }, explicit: false,
    });
    expect(readDailyDateBindings(new URLSearchParams('date=20261007&publication_date=20261006&plan_date=20261008'), '20261009')).toEqual({
      bindings: { plan_date: '20261008', selection_date: '20261007', announcement_date: '20261006' }, explicit: true,
    });
    expect(readDailyDateBindings(new URLSearchParams('date=20261006&publication_date=20261005&announcement_date=20261007&plan_date=20261008'), '20261009').bindings.announcement_date).toBe('20261007');
  });
});
