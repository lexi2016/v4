/** Synthetic contract fixtures only; these are not owner or market receipts. */
export const flags = {
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
};
export const sha = (character) => character.repeat(64);

export function workspaceFixture({ target = '20261009', publication = '20261008', selection = '20261009',
  stale = true, rawCount = 0, reviewedCount = 4 } = {}) {
  const bindings = { plan_date: target, selection_date: selection, announcement_date: publication };
  const cutoff = `${target.slice(0, 4)}-${target.slice(4, 6)}-${target.slice(6, 8)}T09:20:00+08:00`;
  const generated = '2026-10-10T01:00:00+08:00';
  const identity = sha('b');
  const owner = 'ManagerResearchJobService.refresh_workspace_plan';
  const channels = ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'].map((channel) => ({
    ...flags, channel, owner: `SYNTHETIC_${channel}_OWNER`,
    status: channel === 'OVERSOLD' ? 'PARTIAL' : 'CANNOT_CONFIRM',
    target_trade_date: target, selection_date: selection, announcement_date: publication,
    data_date: channel === 'ANNOUNCEMENT' ? publication : selection,
    rows: [], candidate_count: channel === 'OVERSOLD' ? 0 : null,
    pending_count: channel === 'OVERSOLD' ? 693 : null,
    gaps: channel === 'ANNOUNCEMENT' ? ['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED'] :
      channel === 'HK_CONNECT' ? ['TARGET_DATE_MEMBERSHIP_CANNOT_CONFIRM', 'V2_AUTHORITY_NOT_VERIFIED'] :
        ['SCREEN_GAP_695', 'VOLUME_UNIT_SCALE_NOT_PROVEN', 'PROVIDER_FINALITY_NOT_ATTESTED'],
    dependencies: [`SYNTHETIC_${channel}_DEPENDENCY`],
    run_id: null, generated_at: null, product_sha256: null, input_identity: sha('c'),
    execution_kind: 'READ_ONLY_EXISTING_OWNER_REPLAY', natural_run_verified: false,
    ...(channel === 'ANNOUNCEMENT' ? { product_checks: [], other_product_checks: [] } : {}),
  }));
  const stocks = Array.from({ length: rawCount }, (_, index) => {
    const symbol = `HK.${String(index + 1).padStart(5, '0')}`;
    return {
      ...flags, stock_key: `HK|${symbol}|${target}`, market: 'HK', symbol,
      name: `合成原始观察 ${index + 1}`, target_date: target, is_focus: false,
      priority_basis: { group: 'BACKGROUND', evidence_ids: [] }, lanes: ['STAGE'], themes: [],
      why_watch: [`原始观察 ${index + 1} 全量保留`], attention_priority: 'BACKGROUND',
      event_group_count: 0, new_catalyst_count: 0, evidence: [], material_relations: [],
      stage_observation: { rank: index + 1, score: index / 10, raw_marker: `unaltered-${index + 1}` },
      close_observation: null, change: { status: 'UNCHANGED', previous_date: null, reasons: [] },
      plan: { ...flags, next_observation: [], invalidation_conditions: [], missing: [],
        key_risks: [], wait_conditions: [], evidence_ids: [], trigger_price: null,
        invalidation_price: null, actions: [] },
    };
  });
  const materialInput = {
    ...flags, status: 'CANNOT_CONFIRM', complete: false, input_identity: sha('d'),
    relation_use: 'RESEARCH_ONLY_NOT_FORMAL_SELECTION_FOCUS_OR_BUY',
    source_material_record_count: 0, pre_connect_material_card_count: 0,
    post_connect_material_card_count: 0, research_relation_material_card_count: 0,
    connect_rejection_count: 0, target_connect_membership_counts: {}, connect_rejection_reasons: {},
    gaps: ['MATERIAL_INPUT_COMPLETENESS_UNVERIFIED'],
  };
  return {
    ...flags, schema_version: 'v4.manager_research.workspace.v1',
    semantic_version: '20260921.manager-semantic.r3.v1', target_trade_date: target,
    input_identity: identity, date_bindings: bindings, focus_symbols: [], stocks,
    lanes: ['STAGE', 'CATALYST', 'CLOSE'].map((lane) => ({
      lane, owner: `SYNTHETIC_${lane}`, state: 'NOT_RUN', target_date: target,
      stock_count: null, last_attempt_at: null, last_success_at: null, run_id: null,
      execution_kind: 'READ_ONLY', failure_reasons: [], next_plan: null,
      schedule_status: 'UNBOUND', input_coverage: {},
    })),
    themes: [], company_events: [], rejected_relations: [], materials: [], gaps: [],
    summary: { stock_count: stocks.length, relation_count: 0, theme_count: 0,
      reused_material_count: 0, formal_recommendation_count: 0 },
    briefing: { headline: '合成回归用例', ordering_explanation: '' },
    plan_context: { plan_trade_date: target, research_cutoff: cutoff, market_session: publication,
      focus_window_start: `${publication.slice(0, 4)}-${publication.slice(4, 6)}-${publication.slice(6, 8)}T09:20:00+08:00`,
      market_data_verified: false },
    read_context: { mode: 'CURRENT_DYNAMIC_PREVIEW', status: 'VERIFIED_WITH_GAPS',
      contract: '20260923.workspace-history-read.r1', candidate_count_known: true, as_of: cutoff },
    plan_product: { status: stale ? 'STALE_INPUTS_CHANGED' : 'CURRENT', consumed: !stale,
      run_id: 'synthetic-plan-run', sha256: sha('a'), generated_at: generated,
      execution_kind: 'MANUAL_REFRESH', original_owner: owner,
      input_identity_diagnostics: { schema_version: 'v4.manager_research.input_identity_diagnostics.v1',
        input_identity_schema: 'v4.manager_research.input_identity.v2',
        status: stale ? 'CHANGED' : 'MATCH', saved_input_identity: sha('e'), current_input_identity: identity,
        changed_components: stale ? [{ component: 'projection.materials', saved_sha256: sha('e'),
          current_sha256: identity, saved_sources: [{ source_id: 'SYNTHETIC_SOURCE', payload_sha256: sha('f') }],
          current_sources: [{ source_id: 'SYNTHETIC_SOURCE', payload_sha256: sha('1') }] }] : [] } },
    workspace_plan_attempt: { state: 'PARTIAL', run_id: 'synthetic-plan-run', owner,
      execution_kind: 'MANUAL_REFRESH', target_trade_date: target, input_identity: identity },
    owner_chain: {},
    daily_channels: { ...flags, schema_version: 'v4.manager_research.daily_channels.v1',
      date_bindings: bindings, channels, selection_rules_unchanged: true },
    us_market_attention: { ...flags, schema_version: 'v4.manager_research.us_market_bridge.v1',
      target_trade_date: target, research_cutoff: cutoff, status: 'CANNOT_CONFIRM',
      expected_us_session: publication,
      coverage_scope: 'FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
      raw_industry_up: [], raw_individual_up: [], coverage: {}, source_identity: null,
      gaps: ['US_MARKET_SNAPSHOT_NOT_READY'], research_material_input: materialInput,
      mapping_diagnostics: { ...flags, status: 'NOT_EVALUATED', assessment_state: 'NOT_EVALUATED',
        assessment_reasons: ['US_MARKET_SNAPSHOT_NOT_READY'], assessment_reason: null,
        relation_gate: 'TWO_SOURCE_PIT_VERIFIED_REQUIRED', accepted_hk_mapping_count: null,
        material_input: materialInput } },
    us_mapping_research: { ...flags, schema_version: 'v4.manager_research.us_mapping_research.v1',
      target_trade_date: target, reviewed_research: null,
      daily_run: { ...flags, schema_version: 'v4.manager_research.us_mapping_daily_run.v1',
        target_trade_date: target, status: 'VALID_EMPTY', run_id: 'synthetic-us-run',
        generated_at: generated, us_session_date: publication, research_cutoff: cutoff,
        source_status: 'READY', matches: [], gaps: [],
        coverage: { reviewed_us_symbol_count: reviewedCount, matched_us_symbol_count: 0,
          matched_hk_relation_count: 0, configured_us_universe_count: 12,
          available_us_universe_count: 12, full_market_coverage: false },
        source_identity: { payload_sha256: sha('2'), receipt_sha256: sha('3'), manifest_sha256: sha('4') } } },
  };
}

export function readyWorkspaceFixture(options = {}) {
  const value = workspaceFixture({ ...options, stale: false });
  const channels = value.daily_channels.channels;
  for (const channel of channels.slice(1)) {
    Object.assign(channel, { run_id: value.plan_product.run_id, generated_at: value.plan_product.generated_at,
      product_sha256: value.plan_product.sha256, execution_kind: 'MANUAL_REFRESH',
      input_identity: value.input_identity, pending_count: 0, candidate_count: 0, gaps: [] });
  }
  const hk = channels[1];
  hk.status = 'READY'; hk.candidate_count = 1;
  hk.rows = [{ symbol: 'HK.09998', name: '合成港股通候选', reason: '原owner返回的合成研究理由',
    selection_status: 'SELECTED', target_trade_date: value.target_trade_date, data_date: hk.data_date,
    run_id: hk.run_id, generated_at: hk.generated_at, product_sha256: hk.product_sha256,
    source_refs: [{ source_id: 'SYNTHETIC_HK_SOURCE', payload_sha256: sha('5'), receipt_sha256: sha('6') }] }];
  channels[2].status = 'READY_EMPTY';
  const announcement = channels[0];
  Object.assign(announcement, { status: 'READY', candidate_count: 1, pending_count: 0, gaps: [],
    run_id: 'synthetic-announcement-run', generated_at: '2026-10-09T03:00:00+08:00',
    product_sha256: sha('7'), execution_kind: 'OWNER_IMPORT_TIMING_NOT_CLASSIFIED' });
  announcement.product_checks = [{ status: 'CONSUMED', product_sha256: announcement.product_sha256,
    target_trade_date: value.target_trade_date, publication_date: value.date_bindings.announcement_date,
    evidence_run_id: announcement.run_id, owner_available_at: announcement.generated_at,
    source_manifest_sha256: sha('8') }];
  announcement.rows = [{ symbol: 'HK.09999', name: '合成公告候选', reason: '公告原文合成候选理由',
    selection_status: 'SELECTED', target_trade_date: value.target_trade_date,
    data_date: announcement.data_date, run_id: announcement.run_id,
    generated_at: announcement.generated_at, product_sha256: announcement.product_sha256,
    source_manifest_sha256: sha('8'),
    source_refs: [{ source_id: 'SYNTHETIC_ANNOUNCEMENT_SOURCE', payload_sha256: sha('9'), receipt_sha256: sha('0') }] }];
  return value;
}
