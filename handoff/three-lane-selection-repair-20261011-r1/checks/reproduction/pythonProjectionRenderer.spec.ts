/** Reviewer-only synthetic Python output through the unchanged TypeScript DTO and DOM. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, expect, it } from 'vitest';
import { validateDailyChannels, renderDailyChannels } from './dailyChannels';

const envelope = JSON.parse(readFileSync(resolve(process.cwd(), 'projection_cases.json'), 'utf8'));
const cases = envelope.cases;
const baseline = cases.find((item: any) => item.missing === null);
const channel = (item: any, id: string) => item.daily.channels.find((row: any) => row.channel === id);
const source = (host: HTMLElement, id: string) => host.querySelector<HTMLElement>(`[data-daily-channel="${id}"]`)!;
const symbols = (host: HTMLElement, id: string) => [...source(host, id).querySelectorAll<HTMLElement>('[data-daily-symbol]')].map(row => row.dataset.dailySymbol);
function mount(item: any) {
  expect(envelope.scope).toBe('SYNTHETIC_PYTHON_TO_TYPESCRIPT_READ_BOUNDARY_ONLY');
  expect(envelope.real_owner_executed).toBe(false);
  expect(envelope.real_api_called).toBe(false);
  expect(envelope.natural_run_accepted).toBe(false);
  const admitted = validateDailyChannels(item.daily, item.workspace.date_bindings, item.workspace);
  expect(admitted).toEqual(item.daily);
  const host = document.createElement('section'); document.body.append(host);
  renderDailyChannels(host, admitted, item.workspace.date_bindings);
  expect(host.textContent).not.toContain('三路结果合同未通过校验');
  return host;
}
function readDetails(host: HTMLElement, id: string) {
  const details = source(host, id).querySelector<HTMLDetailsElement>('details')!;
  details.open = true; details.dispatchEvent(new Event('toggle'));
  return JSON.parse(details.querySelector('pre')!.textContent!);
}
afterEach(() => document.body.replaceChildren());

it('renders all three actual Python projections, preserving Stage order and per-stock original reasons', () => {
  const host = mount(baseline);
  expect(symbols(host, 'HK_CONNECT')).toEqual(['HK.00002', 'HK.00001']);
  expect(symbols(host, 'HK_CONNECT')).not.toContain('HK.00999');
  expect(symbols(host, 'OVERSOLD')).toEqual(['HK.00001', 'HK.00002']);
  expect(symbols(host, 'ANNOUNCEMENT')).toEqual(['HK.00003']);
  for (const id of ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD']) {
    const original = channel(baseline, id);
    const node = source(host, id);
    expect(node.dataset.dailyStatus).toBe(original.status);
    expect(node.textContent).toContain(`候选 ${original.candidate_count} 只`);
    for (const row of original.rows) expect(node.textContent).toContain(row.reason);
    expect(node.textContent).toContain('自然时段运行验收：CANNOT_CONFIRM');
    expect(original.natural_run_verified).toBe(false);
    expect(readDetails(host, id)).toEqual(original);
  }
  const hk = readDetails(host, 'HK_CONNECT');
  expect(hk.rows.map((row: any) => row.rank)).toEqual([2, 1]);
  expect(hk.rows.map((row: any) => row.order)).toEqual([1, 2]);
  expect(hk.run_id).toBeNull();
  expect(hk.rows[0].source_refs[0].run_id).toBe('run-' + 'b'.repeat(24));
  expect(hk.rows[0].source_refs[0].payload_sha256).toBe('e'.repeat(64));
  expect(hk.rows[0].source_refs[0].receipt_sha256).toBe('1'.repeat(64));
  expect(source(host, 'HK_CONNECT').querySelector('pre')!.textContent).toContain('e'.repeat(64));
  const oversold = readDetails(host, 'OVERSOLD');
  expect(oversold.run_id).toBeNull();
  expect(oversold.rows[0].source_refs).toEqual(baseline.workspace.market_screen.strict[0].source_refs);
  expect(oversold.rows[0].research_priority.priority_rank).toBe(1);
  expect(source(host, 'OVERSOLD').querySelector('pre')!.textContent).toContain('/owner/panel.json');
  const announcement = readDetails(host, 'ANNOUNCEMENT');
  const consumed = announcement.product_checks.find((row: any) => row.status === 'CONSUMED');
  expect(announcement.rows[0].run_id).toBe(consumed.evidence_run_id);
  expect(announcement.rows[0].product_sha256).toBe(consumed.product_sha256);
  expect(announcement.rows[0].source_manifest_sha256).toBe(consumed.source_manifest_sha256);
  expect(source(host, 'ANNOUNCEMENT').textContent).toContain('运行编号 ' + consumed.evidence_run_id);
  expect(source(host, 'ANNOUNCEMENT').textContent).toContain('产物 SHA256 ' + consumed.product_sha256);
  expect(source(host, 'ANNOUNCEMENT').querySelector('pre')!.textContent).toContain('7'.repeat(64));
});

it.each(cases.filter((item: any) => item.missing !== null))('keeps other legal channels when Python reports $id, without displaying unknown as zero', (item: any) => {
  const host = mount(item);
  const missing = source(host, item.missing);
  expect(missing.dataset.dailyStatus).toBe('CANNOT_CONFIRM');
  expect(missing.textContent).toContain('候选数量未知');
  expect(missing.textContent).toContain('待核数量未知');
  expect(missing.textContent).not.toContain('候选 0 只');
  expect(missing.textContent).not.toContain('待核 0');
  expect(missing.textContent).not.toContain('原 owner 已核空集');
  expect(symbols(host, item.missing)).toEqual([]);
  for (const id of ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'].filter(id => id !== item.missing)) {
    const original = channel(baseline, id);
    expect(channel(item, id)).toEqual(original);
    expect(symbols(host, id)).toEqual(original.rows.map((row: any) => row.symbol));
    expect(readDetails(host, id)).toEqual(original);
  }
});
