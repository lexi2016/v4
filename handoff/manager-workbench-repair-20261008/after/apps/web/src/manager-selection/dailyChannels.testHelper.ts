/** Synthetic contract data only: no account, source body, or live market data. */
import type { ManagerWorkspace } from '../api/managerWorkspace';

export const testFlags = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
export const testBindings = { plan_date: '20261008', selection_date: '20261006', announcement_date: '20261007' };

export function dailyFixture(bindings = testBindings) {
  const base = (channel: string) => ({
    ...testFlags, channel, owner: `SYNTHETIC_${channel}`, target_trade_date: bindings.plan_date,
    selection_date: bindings.selection_date, announcement_date: bindings.announcement_date,
    rows: [] as Record<string, unknown>[], candidate_count: null as number | null,
    pending_count: null as number | null, gaps: [] as string[], dependencies: ['SYNTHETIC_OWNER'],
    status: 'CANNOT_CONFIRM', run_id: null as string | null, generated_at: null as string | null,
    product_sha256: null as string | null, input_identity: null as string | null,
    data_date: '20261007', execution_kind: 'READ_ONLY_EXISTING_OWNER_REPLAY', natural_run_verified: false,
  });
  const announcement = {
    ...base('ANNOUNCEMENT'), status: 'READY', candidate_count: 1, watch_count: 0,
    data_date: bindings.announcement_date, run_id: 'synthetic-import-run',
    generated_at: '2026-10-08T07:05:00+08:00', product_sha256: 'b'.repeat(64), input_identity: 'c'.repeat(64),
    execution_kind: 'OWNER_IMPORT_TIMING_NOT_CLASSIFIED',
    product_checks: [{ status: 'CONSUMED', target_trade_date: bindings.plan_date,
      publication_date: bindings.announcement_date, product_sha256: 'b'.repeat(64),
      source_manifest_sha256: 'd'.repeat(64), evidence_run_id: 'synthetic-import-run',
      owner_available_at: '2026-10-08T07:05:00+08:00' }], other_product_checks: [],
    rows: [{ symbol: 'HK.00001', name: '合成公告公司', reason: '原研究理由：已审阅的扩产事件。',
      selection_status: 'SELECTED', data_date: bindings.announcement_date,
      target_trade_date: bindings.plan_date, run_id: 'synthetic-import-run',
      generated_at: '2026-10-08T07:05:00+08:00', product_sha256: 'b'.repeat(64),
      source_manifest_sha256: 'd'.repeat(64), source_refs: [{ title: '合成公告标题', source_sha256: 'e'.repeat(64) }] }],
  };
  const connect = { ...base('HK_CONNECT'), gaps: ['TARGET_HK_UNIVERSE_V2_UNVERIFIED'], authority: null };
  const oversold = { ...base('OVERSOLD'), status: 'PARTIAL', pending_count: 2, watch_count: 0,
    input_identity: 'f'.repeat(64), gaps: ['VOLUME_UNIT_NOT_PROVEN'], authority: null,
    data_context: { market_session: '20261007', screen_phase: 'PREOPEN_COMPLETED_SESSION' } };
  return { ...testFlags, schema_version: 'v4.manager_research.daily_channels.v1',
    date_bindings: { ...bindings }, channels: [announcement, connect, oversold], selection_rules_unchanged: true };
}

export function workspaceFixture(bindings = testBindings, extension = true): ManagerWorkspace {
  const value = {
    ...testFlags, input_identity: 'a'.repeat(64), target_trade_date: bindings.plan_date,
    schema_version: 'v4.manager_research.workspace.v1', semantic_version: '20260921.manager-semantic.r3.v1',
    focus_symbols: [], stocks: [], themes: [], company_events: [], rejected_relations: [], materials: [], gaps: [],
    lanes: ['STAGE', 'CATALYST', 'CLOSE'].map(lane => ({ lane, owner: `SYNTHETIC_${lane}`,
      state: 'NOT_RUN', target_date: bindings.plan_date, stock_count: null,
      last_attempt_at: null, last_success_at: null, run_id: null, execution_kind: 'READ_ONLY',
      failure_reasons: [], next_plan: null, schedule_status: 'UNBOUND', input_coverage: {} })),
    summary: { stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0, formal_recommendation_count: 0 },
    briefing: { headline: '', ordering_explanation: '' },
    plan_context: { plan_trade_date: bindings.plan_date, research_cutoff: '2026-10-08T08:00:00+08:00',
      focus_window_start: '2026-10-07T16:10:00+08:00', market_session: '20261007', market_data_verified: false },
    plan_product: { status: 'DYNAMIC_PREVIEW', consumed: false }, workspace_plan_attempt: {}, owner_chain: {},
    read_context: { mode: 'CURRENT_DYNAMIC_PREVIEW', status: 'VERIFIED', candidate_count_known: true,
      as_of: '2026-10-08T08:00:00+08:00', contract: '20260923.workspace-history-read.r1' },
    ...(extension ? { date_bindings: { ...bindings }, daily_channels: dailyFixture(bindings) } : {}),
  };
  return value as unknown as ManagerWorkspace;
}
