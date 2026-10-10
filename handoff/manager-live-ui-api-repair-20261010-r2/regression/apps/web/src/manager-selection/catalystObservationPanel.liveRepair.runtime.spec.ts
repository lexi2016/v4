import { fireEvent, waitFor } from '@testing-library/vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountCatalystObservations } from './catalystObservationPanel';
import { validateManagerWorkspace, type JsonObject, type ManagerWorkspace } from '../api/managerWorkspace';
import { workspaceFixture, testFlags } from './dailyChannels.testHelper';

// Only HTTP is replaced. The production request/parser/validator and actual panel mount run unchanged.
const bindings = { plan_date: '20261009', selection_date: '20261009', announcement_date: '20261008' };
let dispose: (() => void) | undefined;
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); document.body.replaceChildren(); window.history.replaceState({}, '', '/'); });
function fixture(): ManagerWorkspace {
  const value = workspaceFixture(bindings);
  value.plan_product = { status: 'STALE_INPUTS_CHANGED', consumed: false };
  value.us_mapping_research = {
    ...testFlags, schema_version: 'v4.manager_research.us_mapping_research.v1', target_trade_date: '20261009',
    reviewed_research: null, daily_run: { ...testFlags,
      schema_version: 'v4.manager_research.us_mapping_daily_run.v1', target_trade_date: '20261009',
      us_session_date: '20261008', status: 'VALID_EMPTY', source_status: 'READY', run_id: 'synthetic-local-us-run',
      research_cutoff: '2026-10-09T23:59:59+08:00', generated_at: '2026-10-10T10:00:00+08:00',
      source_identity: { payload_sha256: '1'.repeat(64), receipt_sha256: '2'.repeat(64), manifest_sha256: '3'.repeat(64) },
      coverage: { reviewed_us_symbol_count: 4, matched_us_symbol_count: 0, matched_hk_relation_count: 0,
        configured_us_universe_count: 33, available_us_universe_count: 33, full_market_coverage: false },
      matches: [], gaps: [],
    },
  } as unknown as ManagerWorkspace['us_mapping_research'];
  value.close_recapture_evidence = { status: 'PARTIAL', target_trade_date: '20261009', source_trade_date: '20261009',
    capture_mode: 'LATE_OBSERVATION', observation_type: 'PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION',
    candidate_overlay: { count: 201, rows: Array.from({ length: 201 }, (_, index) => ({
      symbol: `HK.${String(index + 1).padStart(5, '0')}`, name: `合成原始观察${index + 1}`,
      source_trade_date: '20261009', observed_at: '2026-10-09T15:55:00+08:00',
      available_at: '2026-10-09T23:10:00+08:00', candidate_status: 'OBSERVATION_ONLY',
      source_refs: [{ payload_sha256: '4'.repeat(64), receipt_sha256: '5'.repeat(64), path: `synthetic/row-${index + 1}` }],
    })) } };
  return value;
}
async function mount(raw: ManagerWorkspace = fixture(), query = 'date=20261009&plan_date=20261009&announcement_date=20261008', refreshed: ManagerWorkspace = raw) {
  window.history.replaceState({}, '', '/manager-selection/?' + query);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace')
    ? { ok: true, status: 200, json: async () => String(input).includes('/workspace/refresh?') ? refreshed : raw } as Response
    : { ok: false, status: 503 } as Response));
  const host = document.createElement('div'); document.body.append(host);
  dispose = mountCatalystObservations(host, '20261009');
  await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toMatch(/READY|FAILED/));
  return host;
}
function precedes(left: Element, right: Element) { expect(left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); }

describe('current fused manager panel repair through validated HTTP mount', () => {
  // Break caught: omitting renderDailyChannels from panel render makes valid API channels invisible.
  it('renders all three channels from one validated workspace even when the saved plan is stale', async () => {
    const raw = fixture(); expect(() => validateManagerWorkspace(raw, '20261009')).not.toThrow();
    const host = await mount(raw);
    expect(host.querySelectorAll('[data-daily-channel]')).toHaveLength(3);
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('来源/选股日 20261009 · 公告日 20261008 · 计划日 20261009');
    const announcement = host.querySelector('[data-daily-channel="ANNOUNCEMENT"]');
    expect(announcement?.getAttribute('data-daily-status')).toBe('READY');
    expect(announcement?.textContent).toContain('synthetic-import-run');
    expect(announcement?.textContent).toContain('产物 SHA-256 ' + 'b'.repeat(64));
    expect(announcement?.textContent).toContain('原研究理由：已审阅的扩产事件。');
    expect(announcement?.textContent).toContain('数据日 20261008');
    expect(announcement?.closest('details')).toBeNull();
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('候选数量未知');
    expect(host.querySelector('[data-daily-channel="HK_CONNECT"]')?.textContent).toContain('TARGET_HK_UNIVERSE_V2_UNVERIFIED');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.getAttribute('data-daily-status')).toBe('PARTIAL');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('待核 2');
    expect(host.querySelector('[data-daily-channel="OVERSOLD"]')?.textContent).toContain('VOLUME_UNIT_NOT_PROVEN');
    expect(host.textContent).toContain('STALE_INPUTS_CHANGED');
  });
  // Break caught: raw close rows placed before results or dropped/truncated to improve first-screen appearance.
  it('places plan and core research before a collapsed audit containing every original observation row', async () => {
    const raw = fixture(), before = JSON.stringify(raw); const host = await mount(raw);
    const audit = host.querySelector('details[data-raw-observation-audit]') as HTMLDetailsElement;
    expect(audit).not.toBeNull(); expect(audit.open).toBe(false);
    precedes(host.querySelector('[aria-label="业务闭环状态"]')!, host.querySelector('[data-daily-channels]')!);
    precedes(host.querySelector('[data-daily-channels]')!, audit);
    precedes(host.querySelector('[aria-label="证据优先研究"]')!, audit);
    await fireEvent.click(audit.querySelector(':scope > summary')!);
    expect(audit.open).toBe(true);
    expect(audit.querySelectorAll('.manager-close-recapture-candidate')).toHaveLength(201);
    expect(audit.textContent).toContain('合成原始观察201');
    const last = [...audit.querySelectorAll('.manager-close-recapture-candidate')].at(-1)!;
    const source = last.querySelector('details') as HTMLDetailsElement;
    await fireEvent.click(source.querySelector('summary')!);
    await waitFor(() => expect(source.querySelector('pre')?.textContent).toContain('synthetic/row-201'));
    expect(JSON.stringify(raw)).toBe(before);
  });
  // Break caught: a broad US label can conflate NOT_EVALUATED input assessment with local VALID_EMPTY.
  it('labels US input assessment separately from four reviewed daily US-HK relations', async () => {
    const host = await mount();
    expect(host.querySelector('[aria-label="业务闭环状态"]')?.textContent).toContain('美股输入评估／完整度：尚未评估');
    const mapping = host.querySelector('[data-us-mapping-research]');
    expect(mapping?.querySelector('h4')?.textContent).toContain('每日 US-HK 已审映射');
    expect(mapping?.textContent).toContain('4 个已审关系');
    expect(mapping?.textContent).toContain('VALID_EMPTY');
    expect(mapping?.textContent).toContain('不代表全市场');
    expect(mapping?.textContent).toContain('2026-10-09');
  });
  it.each(['channel-date', 'channel-safety', 'workspace-safety'])('rejects malformed %s through normal request validation and clears cards', async kind => {
    const raw = fixture(); const channel = raw.daily_channels!.channels[1];
    if (kind === 'channel-date') channel.target_trade_date = '20261008';
    if (kind === 'channel-safety') channel.orders_sent = true;
    if (kind === 'workspace-safety') raw.orders_sent = true;
    const host = await mount(raw);
    expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED');
    expect(host.textContent).toContain('合同校验失败');
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
    expect(host.querySelectorAll('.manager-close-recapture-candidate')).toHaveLength(0);
  });
  it('keeps older optional DTOs readable while displaying unknown channel counts', async () => {
    const raw = fixture(); delete raw.daily_channels; delete raw.date_bindings;
    const host = await mount(raw);
    expect(host.querySelectorAll('[data-daily-channel]')).toHaveLength(3);
    for (const card of host.querySelectorAll('[data-daily-channel]')) {
      expect(card.textContent).toContain('候选数量未知'); expect(card.textContent).toContain('尚未提供三路结果合同');
    }
  });
  // Break caught: a self-consistent response from another selected publication day is admitted without request binding.
  it('rejects a response whose publication binding differs from the explicit selected publication day', async () => {
    const raw = workspaceFixture({ ...bindings, announcement_date: '20261007' });
    const host = await mount(raw);
    expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED');
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
    expect(host.textContent).toContain('合同校验失败');
  });
  it('keeps the prior-publication service default when only the Stage/source date is supplied', async () => {
    const host = await mount(fixture(), 'date=20261009&plan_date=20261009');
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('公告日 20261008');
    expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('数据日 20261008');
  });
  it('rejects a response whose source/selection day differs from the URL Stage/source day', async () => {
    const raw = workspaceFixture({ ...bindings, selection_date: '20261008' });
    const host = await mount(raw);
    expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED');
    expect(host.querySelector('[data-daily-symbol]')).toBeNull();
  });
  it('uses selected canonical GET readback after manual generation rather than rendering its POST preview', async () => {
    const raw = fixture(), postPreview = structuredClone(raw), host = await mount(raw, undefined, postPreview);
    raw.daily_channels!.channels[0].rows[0].reason = '合成 canonical GET 最新读回';
    const button = [...host.querySelectorAll('button')].find(node => node.textContent === '用既有材料生成计划')!;
    await fireEvent.click(button);
    await waitFor(() => expect(host.querySelector('[data-daily-channel="ANNOUNCEMENT"]')?.textContent).toContain('合成 canonical GET 最新读回'));
    expect(host.querySelector('[data-daily-bindings]')?.textContent).toContain('公告日 20261008');
  });
  it('does not admit a late bound response after the user cancels the active read', async () => {
    window.history.replaceState({}, '', '/?date=20261009&announcement_date=20261008');
    let resolveRead!: (value: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/workspace?')
      ? new Promise<Response>(resolve => { resolveRead = resolve; }) : { ok: false, status: 503 } as Response));
    const host = document.createElement('div'); document.body.append(host); dispose = mountCatalystObservations(host, '20261009');
    const cancel = [...host.querySelectorAll('button')].find(node => node.textContent === '取消本次读取')!;
    await fireEvent.click(cancel);
    resolveRead({ ok: true, status: 200, json: async () => fixture() } as Response);
    await waitFor(() => expect(host.querySelector('.manager-catalyst-observations')?.getAttribute('data-read-state')).toBe('FAILED'));
    expect(host.querySelector('[data-daily-symbol]')).toBeNull(); expect(host.textContent).toContain('已取消本次读取');
  });
  it('shows the first changed source with saved/current SHA while keeping the complete component list expandable', async () => {
    const raw = fixture(); raw.plan_product!.input_identity_diagnostic = {
      schema_version: 'v4.manager_input_identity_diagnostic.v1', status: 'CHANGED',
      saved_input_identity: '6'.repeat(64), current_input_identity: 'a'.repeat(64), reason_codes: ['INPUT_COMPONENTS_CHANGED'],
      changed_components: [
        { component_id: 'semantic:a', change: 'CHANGED', saved_sha256: '8'.repeat(64), current_sha256: '9'.repeat(64),
          source: { source_id: 'synthetic-consumed-source', source_date: '20261008', source_root_sha256: 'a'.repeat(64),
            payload_path: 'synthetic/consumed.json', receipt_path: 'synthetic/receipt.json', slot: '', mode: 'REPLAY' } },
        { component_id: 'semantic:b', change: 'REMOVED', saved_sha256: 'b'.repeat(64), current_sha256: null },
      ], provenance_changes: [],
    };
    const host = await mount(raw), diagnostic = host.querySelector('[data-plan-input-diagnostic]');
    expect(diagnostic?.textContent).toContain('CHANGED');
    const visible = diagnostic?.querySelector('[data-first-identity-change]');
    expect(visible?.textContent).toContain('synthetic-consumed-source'); expect(visible?.textContent).toContain('20261008');
    expect(visible?.textContent).toContain('synthetic/consumed.json'); expect(visible?.textContent).toContain('8'.repeat(64));
    expect(visible?.textContent).toContain('9'.repeat(64)); expect(visible?.closest('details')).toBeNull();
    const complete = diagnostic?.querySelector('details[data-identity-changes]') as HTMLDetailsElement;
    expect(complete.open).toBe(false); await fireEvent.click(complete.querySelector('summary')!);
    await waitFor(() => expect(complete.textContent).toContain('semantic:b'));
    expect(complete.textContent).toContain('REMOVED');
    expect(host.textContent).toContain('STALE_INPUTS_CHANGED');
  });
  it('labels manifest-only diagnostics as provenance and does not promote them to a stale reason', async () => {
    const raw = fixture(); raw.plan_product!.input_identity_diagnostic = {
      schema_version: 'v4.manager_input_identity_diagnostic.v1', status: 'MATCH',
      saved_input_identity: 'a'.repeat(64), current_input_identity: 'a'.repeat(64), reason_codes: [], changed_components: [],
      provenance_changes: [{ component_id: 'semantic:a', saved_manifest_sha256: 'a'.repeat(64), current_manifest_sha256: 'b'.repeat(64),
        source: { source_id: '<img src=x onerror=alert(1)>', source_date: '20261008', payload_path: 'synthetic/consumed.json',
          source_root_sha256: 'c'.repeat(64), receipt_path: 'synthetic/receipt.json', slot: '', mode: 'REPLAY' } }],
    };
    const host = await mount(raw), diagnostic = host.querySelector('[data-plan-input-diagnostic]');
    expect(diagnostic?.textContent).toContain('MATCH'); expect(diagnostic?.textContent).toContain('仅 provenance');
    expect(diagnostic?.textContent).toContain('不作为陈旧原因'); expect(diagnostic?.querySelector('[data-first-identity-change]')).toBeNull();
    const provenance = diagnostic?.querySelector('details[data-identity-provenance]') as HTMLDetailsElement;
    await fireEvent.click(provenance.querySelector('summary')!);
    await waitFor(() => expect(provenance.textContent).toContain('<img src=x onerror=alert(1)>'));
    expect(provenance.querySelector('img')).toBeNull();
    expect(provenance.textContent).toContain('a'.repeat(64)); expect(provenance.textContent).toContain('b'.repeat(64));
  });
  it('keeps unavailable identity-difference evidence explicitly CANNOT_CONFIRM and supports older DTOs', async () => {
    const raw = fixture(); raw.plan_product!.input_identity_diagnostic = {
      schema_version: 'v4.manager_input_identity_diagnostic.v1', status: 'CANNOT_CONFIRM', saved_input_identity: null,
      current_input_identity: 'a'.repeat(64), reason_codes: ['SAVED_COMPONENTS_UNVERIFIABLE'], changed_components: [], provenance_changes: [],
    };
    const host = await mount(raw), diagnostic = host.querySelector('[data-plan-input-diagnostic]');
    expect(diagnostic?.textContent).toContain('CANNOT_CONFIRM'); expect(diagnostic?.textContent).toContain('SAVED_COMPONENTS_UNVERIFIABLE');
    expect(diagnostic?.textContent).toContain('不能定位'); expect(diagnostic?.querySelector('[data-first-identity-change]')).toBeNull();
  });
});
