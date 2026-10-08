import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestManagerWorkspace, validateManagerWorkspace, type JsonObject, type ManagerWorkspace, type ResearchAttentionCard, type UsMappingResearch } from './managerWorkspace';
import { renderResearchAttention } from '../manager-selection/researchAttention';

const flags = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
const date = '20260925';

function trendSourceRefs(): JsonObject[] {
  return [{
    owner: 'SIMULATED_SCREEN_HISTORY', payload_path: 'screen_history/verified_session.json',
    payload_sha256: 'a'.repeat(64), manifest_path: 'screen_history/manifest.json',
    manifest_sha256: 'b'.repeat(64),
  }];
}

function marketScreen(session: string = date, tradeDate: string = date): JsonObject {
  return {
    ...flags, schema_version: 'v4.manager_research.rebound_v3_screen.v1',
    rule_version: 'TEST_R5_TREND_BOUNDARY', target_trade_date: tradeDate,
    verified_session: session, status: 'CANNOT_CONFIRM', cards: [], strict: [], near: [], pending: [],
    gaps: [], coverage: {
      input_candidate_count: 0, history_complete_count: 0, history_pending_count: 0,
      strict_count: 0, near_candidate_count: 0, near_count: 0, selected_count: 0,
    }, input_identity: null, authority: null, main_screen_ready: false,
  };
}

const laneLabels: Record<string, string> = {
  OFFICIAL_ANNOUNCEMENT: '公司公告/官方披露', COMPANY_MATERIAL: '公司特异材料',
  STRICT_NEAR_SCREEN: '既有量价筛选', TREND_CONTINUATION: '趋势延续',
  US_INDIVIDUAL_MAPPING: '已核美股个股映射', US_INDUSTRY_MAPPING: '已核美股行业映射',
};

function sourceIdentity(): JsonObject {
  return { status: 'VERIFIED', payload_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), manifest_sha256: 'c'.repeat(64) };
}

function companyEvidence(published: string | null = '2026-09-25T09:00:00+08:00', acquired: string | null = '2026-09-25T09:15:00+08:00'): JsonObject {
  const sourceRef = { status: 'VERIFIED', payload_sha256: 'd'.repeat(64), source_id: 'SIMULATED_OWNER' };
  const trace = { first_seen_at: acquired, collected_at: acquired, available_at: null, retrieved_at: null, archive_recorded_at: null, source_refs: [sourceRef] };
  return {
    evidence_lane: 'COMPANY_MATERIAL', evidence_class: 'VERIFIED_COMPANY_SPECIFIC_MATERIAL',
    semantic_status: 'ACCEPTED', temporal_role: 'NEW_PLAN_PUBLICATION',
    body_status: 'BODY_PARSED',
    published_at: published, first_seen_at: acquired, collected_at: acquired,
    available_at: null, retrieved_at: null, archive_recorded_at: null, acquired_at: acquired,
    source_refs: [sourceRef], merged_provenance: [trace], provenance_count: 1,
  };
}

function officialEvidence(bodyStatus: string = 'BODY_PARSED', acquired: string | null = '2026-09-25T09:15:00+08:00'): JsonObject {
  const bodySha = 'e'.repeat(64);
  const sourceRef = { blob_sha256: 'f'.repeat(64), body_sha256: bodySha, source_key: 'SIMULATED_OFFICIAL', retrieved_at: acquired };
  return {
    evidence_lane: 'OFFICIAL_ANNOUNCEMENT',
    evidence_class: bodyStatus === 'BODY_PARSED' ? 'OFFICIAL_PARSED_DOCUMENT' : 'OFFICIAL_DIRECTORY_ONLY',
    body_status: bodyStatus, published_at: '2026-09-25T09:00:00+08:00',
    available_at: acquired, retrieved_at: acquired, source_refs: [sourceRef],
    ...(bodyStatus === 'BODY_PARSED' ? { document_sha256: bodySha } : {}),
  };
}

function usIndustryEvidence(captured: string | null = '2026-09-25T09:30:00+08:00', relationAcquired: string | null = '2026-09-25T08:05:00+08:00'): JsonObject {
  return {
    evidence_lane: 'US_INDUSTRY_MAPPING', evidence_class: 'VERIFIED_US_INDUSTRY_WITH_HK_ISSUER_RELATION',
    us_mover: { label: '机器人', status: 'READY', instrument_classification: 'INDUSTRY_PROXY_NOT_FULL_MARKET_SECURITY_SCREEN' },
    hk_relation: {
      relationship_type: 'INDUSTRY_INFERENCE', issuer_quote: '公司披露了相关业务事实。',
      source_refs: [{ status: 'VERIFIED' }], issuer_published_at: '2026-09-25T08:00:00+08:00',
      issuer_available_at: relationAcquired,
    },
    issuer_published_at: '2026-09-25T08:00:00+08:00',
    available_at: captured, us_captured_at: captured, source_identity: sourceIdentity(),
  };
}

function usIndividualEvidence(captured: string | null = '2026-09-25T09:30:00+08:00', relationAcquired: string | null = '2026-09-25T08:05:00+08:00'): JsonObject {
  return {
    evidence_lane: 'US_INDIVIDUAL_MAPPING', evidence_class: 'VERIFIED_US_INDIVIDUAL_WITH_STRUCTURED_HK_RELATION',
    us_mover: { symbol: 'NVDA', instrument_classification: 'CONFIGURED_US_SYMBOL_NOT_FULL_MARKET_SCREEN' },
    hk_relation: {
      semantic_status: 'ACCEPTED', related_us_symbols: ['NVDA'], source_refs: [{ status: 'VERIFIED' }],
      published_at: '2026-09-25T08:00:00+08:00', available_at: relationAcquired,
    },
    published_at: '2026-09-25T08:00:00+08:00', available_at: captured,
    us_captured_at: captured, source_identity: sourceIdentity(),
  };
}

function decision(state: string, group: number, score: number, company: number, market: number, context: number, lanes: string[], label: string): JsonObject {
  return {
    schema_version: 'v4.manager_research.attention_decision.v1',
    version: '20260927.evidence-state-triage.proposal-v1',
    status: 'PROPOSAL_ONLY', state, group_label: label, group_order: group,
    summary: 'Research summary.', next_check: 'Check the next evidence.', invalidation: 'Withdraw when invalidated.',
    why_now_readable: ['OFFICIAL_ANNOUNCEMENT','COMPANY_MATERIAL','STRICT_NEAR_SCREEN','TREND_CONTINUATION','US_INDIVIDUAL_MAPPING','US_INDUSTRY_MAPPING']
      .filter(lane => lanes.includes(lane)).map(lane => laneLabels[lane]),
    company_evidence_strength: company, market_confirmation_strength: market, context_strength: context,
    research_priority_key: [group, -score, -company, -market, -context, -lanes.length],
    formal_rank_writeback: false, stage_writeback: false, buy_gate_writeback: false,
  };
}

function card(options: {
  symbol: string; score: number; state?: string; group?: number; label?: string;
  lanes?: string[]; classification?: string | null; company?: number; market?: number; context?: number;
  acquired?: string | null; published?: string | null; rank?: number | null;
  evidence?: JsonObject[];
}): JsonObject {
  const lanes = options.lanes ?? ['COMPANY_MATERIAL'];
  const classification = options.classification ?? null;
  const evidence = options.evidence ?? lanes.flatMap(lane => {
    if (lane === 'COMPANY_MATERIAL') return [companyEvidence(options.published, options.acquired)];
    if (lane === 'OFFICIAL_ANNOUNCEMENT') return [officialEvidence()];
    if (lane === 'US_INDUSTRY_MAPPING') return [usIndustryEvidence()];
    if (lane === 'US_INDIVIDUAL_MAPPING') return [usIndividualEvidence()];
    if (lane === 'TREND_CONTINUATION') return [{
      evidence_lane: lane, evidence_class: 'VERIFIED_SCREEN_HISTORY_TREND',
      recent_3_session_return_pct: 1, recent_5_session_return_pct: 2,
      verified_session: date, source_refs: trendSourceRefs(),
    }];
    return [];
  });
  const officialParsed = evidence.some(row => row.evidence_lane === 'OFFICIAL_ANNOUNCEMENT' &&
    row.evidence_class === 'OFFICIAL_PARSED_DOCUMENT' && row.body_status === 'BODY_PARSED');
  const company = options.company ?? (lanes.includes('OFFICIAL_ANNOUNCEMENT') ? (officialParsed ? 3 : 2) : lanes.includes('COMPANY_MATERIAL') ? 1 : 0);
  const market = options.market ?? (classification === 'STRICT_REBOUND' ? 3 : classification === 'NEAR_CONDITION' ? 2 : lanes.includes('TREND_CONTINUATION') ? 1 : 0);
  const context = options.context ?? (lanes.includes('US_INDIVIDUAL_MAPPING') ? 2 : lanes.includes('US_INDUSTRY_MAPPING') ? 1 : 0);
  const defaultState = company && market ? 'COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION'
    : company ? 'COMPANY_EVIDENCE_WAIT_MARKET' : market ? 'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE'
      : context ? 'CONTEXT_ONLY' : 'INSUFFICIENT';
  const defaultGroup = ['COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION','COMPANY_EVIDENCE_WAIT_MARKET','MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE','CONTEXT_ONLY','INSUFFICIENT'].indexOf(defaultState);
  const defaultLabel = ['公司证据 + 市场确认','公司证据，待市场确认','市场结构先行，缺公司级原因','产业/海外背景','证据不足'][defaultGroup];
  const state = options.state ?? defaultState;
  const group = options.group ?? defaultGroup;
  const label = options.label ?? defaultLabel;
  const defaultPublished = evidence.flatMap(row => [row.published_at ?? row.issuer_published_at])
    .filter((value): value is string => typeof value === 'string').sort().at(-1) ?? null;
  const defaultAcquired = evidence.flatMap(row => [row.acquired_at, row.available_at, row.us_captured_at, row.first_seen_at, row.collected_at])
    .filter((value): value is string => typeof value === 'string').sort().at(-1) ?? null;
  const published = options.published === undefined ? defaultPublished : options.published;
  const acquired = options.acquired === undefined ? defaultAcquired : options.acquired;
  return {
    symbol: options.symbol, name: options.symbol, research_attention_score: options.score,
    research_attention_band: 'NORMAL_RESEARCH', qualified_lane_count: lanes.length, qualified_lanes: lanes,
    why_now: ['existing proposal score'], missing: [], screen_classification: classification,
    original_screen_rank: options.rank ?? null, evidence, ...flags,
    freshest_published_at: published, freshest_acquired_at: acquired,
    decision: decision(state, group, options.score, company, market, context, lanes, label),
  };
}

function attention(cards: JsonObject[]): JsonObject {
  return {
    schema_version: 'v4.manager_research.research_attention.v1', target_trade_date: date,
    research_cutoff: '2026-09-25T09:40:00+08:00', status: 'READY_WITH_GAPS',
    priority_name: 'EVIDENCE_STATE_RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK',
    ordering_basis: 'EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS',
    freshness: { effective_start: '2026-09-20T09:40:00+08:00', status: 'PROPOSAL_ONLY' },
    config: { version: '20260927.research-attention.evidence-state-v2', status: 'PROPOSAL_ONLY' },
    cards, coverage: {}, gaps: [], input_identity: 'a'.repeat(64),
    strict_near_unchanged: true, existing_focus_rank_unchanged: true, stage_unchanged: true,
    ...flags,
  };
}

function workspace(researchAttention: JsonObject, screenSession: string = date, tradeDate: string = date): ManagerWorkspace {
  const lane = (name: 'STAGE' | 'CATALYST' | 'CLOSE') => ({
    lane: name, owner: `SIMULATED_${name}`, state: 'NOT_RUN', target_date: tradeDate,
    stock_count: null, last_attempt_at: null, last_success_at: null, run_id: null,
    execution_kind: 'READ_ONLY', failure_reasons: [], next_plan: null,
    schedule_status: 'UNBOUND', input_coverage: {},
  });
  return {
    ...flags, schema_version: 'v4.manager_research.workspace.v1',
    semantic_version: '20260921.manager-semantic.r3.v1', target_trade_date: tradeDate,
    input_identity: 'b'.repeat(64), focus_symbols: [], briefing: {}, company_events: [],
    rejected_relations: [], stocks: [], lanes: [lane('STAGE'), lane('CATALYST'), lane('CLOSE')],
    themes: [], materials: [], gaps: [], summary: {
      stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0,
      formal_recommendation_count: 0,
    }, market_screen: marketScreen(screenSession, tradeDate), research_attention: researchAttention,
  } as unknown as ManagerWorkspace;
}

function usRelationDiagnostics(state:string,accepted:number|null,complete:boolean):JsonObject{
  const cardCount=complete||state==='INSUFFICIENT'||state==='ASSESSED_WITH_RELATIONS'?1:0;
  const materialInput:JsonObject={...flags,status:complete?'READY':'CANNOT_CONFIRM',complete,
    source_material_record_count:cardCount,pre_connect_material_card_count:cardCount,
    post_connect_material_card_count:cardCount,research_relation_material_card_count:cardCount,
    connect_rejection_count:0,target_connect_scope_status:'OWNER_VERIFIED',
    target_connect_membership_counts:{},connect_rejection_reasons:{},gaps:complete?[]:['US_MARKET_SNAPSHOT_NOT_READY'],
    input_identity:'c'.repeat(64),relation_use:'RESEARCH_ONLY_NOT_FORMAL_SELECTION_FOCUS_OR_BUY'};
  return {...flags,status:'COMPUTED_BY_RELATION_LAYER',source_material_card_count:cardCount,
    candidate_relation_count:state==='ASSESSED_WITH_RELATIONS'?1:0,mapping_eligible:complete,
    accepted_hk_mapping_count:accepted,assessment_state:state,assessment_reason:null,assessment_reasons:[],
    relation_gate:'TWO_SOURCE_PIT_VERIFIED_REQUIRED',material_input:materialInput};
}

function newContractCards(): JsonObject[] {
  return [
    card({ symbol: 'HK.01001', score: 24 }),
    card({
      symbol: 'HK.01002', score: 95, state: 'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE', group: 2,
      label: '市场结构先行，缺公司级原因', lanes: ['STRICT_NEAR_SCREEN'], classification: 'STRICT_REBOUND',
      company: 0, market: 3, rank: 1,
    }),
  ];
}

describe('Manager workspace evidence-state API contract', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('accepts a NOT_RUN owner projection through requestManagerWorkspace only when unknown coverage is explicit null', async () => {
    const targetDate = '20261001';
    const targetAttention = attention([]);
    targetAttention.target_trade_date = targetDate;
    targetAttention.research_cutoff = '2026-10-01T09:27:30+08:00';
    const targetWorkspace = workspace(targetAttention, targetDate, targetDate);
    targetWorkspace.plan_context = { plan_trade_date: targetDate, research_cutoff: targetAttention.research_cutoff };
    targetWorkspace.plan_product = { consumed: false };
    targetWorkspace.read_context = { mode: 'CURRENT_DYNAMIC_PREVIEW', status: 'SOURCE_FAILED',
      contract: '20260923.workspace-history-read.r1', candidate_count_known: false,
      as_of: targetAttention.research_cutoff };
    const mapping = {
      ...flags, schema_version: 'v4.manager_research.us_mapping_research.v1', target_trade_date: targetDate,
      daily_run: {
        ...flags, schema_version: 'v4.manager_research.us_mapping_daily_run.v1', status: 'NOT_RUN',
        target_trade_date: targetDate, run_id: null, generated_at: null, us_session_date: null, research_cutoff: null,
        coverage: { reviewed_us_symbol_count: 4, matched_us_symbol_count: null, matched_hk_relation_count: null,
          configured_us_universe_count: null, available_us_universe_count: null, full_market_coverage: false },
        matches: [], gaps: ['DAILY_MAPPING_NOT_MATERIALIZED'], source_identity: null,
      },
      reviewed_research: null,
    } as unknown as NonNullable<ManagerWorkspace['us_mapping_research']>;
    targetWorkspace.us_mapping_research = mapping;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => targetWorkspace } as Response)));

    const loaded = await requestManagerWorkspace(targetDate, new AbortController().signal);
    expect(loaded.us_mapping_research?.daily_run.coverage.available_us_universe_count).toBeNull();

    const coverage = { ...mapping.daily_run.coverage } as JsonObject;
    delete coverage.available_us_universe_count;
    const missingField = { ...targetWorkspace, us_mapping_research: {
      ...mapping, daily_run: { ...mapping.daily_run, coverage },
    } } as unknown as JsonObject;
    expect(() => validateManagerWorkspace(missingField, targetDate)).toThrow('WORKSPACE_COUNT_INVALID');
  });

  it('renders persisted daily US mapping fields for the matching target date without borrowing the retrospective seed', () => {
    const targetDate = '20260925';
    const targetWorkspace = workspace(attention([]), targetDate, targetDate);
    targetWorkspace.us_mapping_research = {
      schema_version: 'v4.manager_research.us_mapping_research.v1', target_trade_date: targetDate,
      daily_run: {
        ...flags, schema_version: 'v4.manager_research.us_mapping_daily_run.v1', status: 'COMPLETED',
        target_trade_date: targetDate, run_id: 'daily-run-1', generated_at: '2026-09-25T01:27:30Z',
        us_session_date: '20260924', research_cutoff: '2026-09-25T09:27:30+08:00', source_status: 'READY',
        source_identity: { payload_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), manifest_sha256: 'c'.repeat(64) },
        coverage: { reviewed_us_symbol_count: 4, matched_us_symbol_count: 1, matched_hk_relation_count: 1,
          configured_us_universe_count: 33, available_us_universe_count: 33, full_market_coverage: false },
        matches: [{ us_symbol: 'LITE', change_pct: 5.662528, session_date: '20260924', hk_symbol: 'HK.06166', research_priority: 'PRIORITY',
          hk_name: '剑桥科技（CIG Shanghai）', relationship_type: 'PRODUCT_PEER',
          reason: '高速数通光收发器产品同业映射。', maturity: '800G模块已大批量出货。',
          limitations: ['同业映射，不是客户/供应关系'], official_sources: [{ title: '公司中期报告',
            url: 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0903/2026090300698.pdf', published_at: '2026-09-03' }],
          target_date_eligibility: 'CANNOT_CONFIRM' }],
        gaps: [],
      },
      reviewed_research: null,
      ...flags,
    } as unknown as ManagerWorkspace['us_mapping_research'];

    const validated = validateManagerWorkspace(targetWorkspace, targetDate);
    const host = document.createElement('div');
    renderResearchAttention(host, validated.research_attention, undefined, undefined, validated.us_mapping_research);

    expect(host.textContent).toContain('LITE +5.662528%');
    expect(host.textContent).toContain('06166 剑桥科技（CIG Shanghai）');
    expect((host.querySelector('.us-mapping-table a') as HTMLAnchorElement | null)?.rel).toBe('noopener noreferrer');
    expect(host.textContent).toContain('PRIORITY · 优先核验');
    expect(host.querySelector('[data-reviewed-us-mapping]')).toBeNull();
    expect(host.textContent).not.toContain('20260930 已审阅回顾');
  });

  it('labels the retrospective target date, US source session, review date, and explicit priority versus watch tiers', () => {
    const targetDate = '20260930';
    const five = [
      ['HK.06166', '06166', '剑桥科技', 'PRIORITY', 'LITE'],
      ['HK.06088', '06088', '鸿腾精密', 'PRIORITY', 'AVGO'],
      ['HK.00763', '00763', '中兴通讯', 'PRIORITY', 'CIEN'],
      ['HK.06869', '06869', '长飞光纤光缆', 'WATCH', '未指定单只美股驱动或涨幅'],
      ['HK.01729', '01729', '汇聚科技', 'WATCH', '未指定单只美股驱动或涨幅'],
    ] as const;
    const mapping = {
      ...flags, schema_version: 'v4.manager_research.us_mapping_research.v1', target_trade_date: targetDate,
      daily_run: { ...flags, schema_version: 'v4.manager_research.us_mapping_daily_run.v1', status: 'NOT_RUN',
        target_trade_date: targetDate, run_id: null, generated_at: null, us_session_date: null, research_cutoff: null,
        coverage: { reviewed_us_symbol_count: 4, matched_us_symbol_count: null, matched_hk_relation_count: null,
          configured_us_universe_count: null, available_us_universe_count: null, full_market_coverage: false },
        matches: [], gaps: ['DAILY_MAPPING_NOT_MATERIALIZED'], source_identity: null },
      reviewed_research: { ...flags, schema_version: 'v4.manager_research.us_mapping_reviewed.v1',
        target_trade_date: targetDate, us_session_date: '20260929', status: 'REVIEWED_RETROSPECTIVE_RESEARCH',
        reviewed_at: '2026-10-05', artifact_sha256: 'd'.repeat(64), report: { sha256: 'e'.repeat(64) },
        source_scope: { requested_us_symbols: 33, original_workspace_plan_status: 'SOURCE_FAILED',
          original_us_owner_lineage_status: 'CANNOT_CONFIRM', original_plan_consumed_these_relations: false,
          target_date_eligibility: 'CANNOT_CONFIRM', pit_status: 'CANNOT_CONFIRM' },
        cards: five.map(([hk_symbol, hk_code, hk_name, research_priority, symbol]) => ({
          hk_symbol, hk_code, hk_name, research_priority,
          us_symbols: symbol.startsWith('未指定') ? [] : [symbol], daily_match_symbols: [],
          us_moves: symbol.startsWith('未指定') ? [] : [{ symbol, change_pct: 1.25 }],
          theme_label: symbol.startsWith('未指定') ? symbol : undefined,
          relationship_type: 'PRODUCT_PEER', reason: '已审阅关系摘要。', maturity: '已披露产品阶段。',
          limitations: [], published_at: '2026-09-03', target_date_eligibility: 'CANNOT_CONFIRM',
          official_sources: [{ title: '官方报告', url: 'https://example.com/report', published_at: '2026-09-03' }],
        })),
      },
    } as unknown as UsMappingResearch;
    const targetAttention=attention([]);
    targetAttention.target_trade_date=targetDate;
    targetAttention.research_cutoff='2026-09-30T09:27:30+08:00';
    const targetWorkspace=workspace(targetAttention,targetDate,targetDate);
    targetWorkspace.us_mapping_research=mapping;
    const validated=validateManagerWorkspace(targetWorkspace,targetDate);
    const host = document.createElement('div');
    renderResearchAttention(host, validated.research_attention, undefined, undefined, validated.us_mapping_research);
    expect(host.textContent).toContain('港股目标日 2026-09-30 / 美股来源时段 2026-09-29 / 审阅于 2026-10-05');
    expect(host.querySelectorAll('.us-mapping-table tbody tr')).toHaveLength(5);
    expect(host.querySelectorAll('.us-mapping-table tbody tr td:first-child')[0].textContent).toContain('PRIORITY');
    expect(host.querySelectorAll('.us-mapping-table tbody tr td:first-child')[4].textContent).toContain('WATCH');
    expect(host.textContent).toContain('事后研究；原盘前计划未消费这些关系');
    expect(validated.us_mapping_research?.reviewed_research?.us_session_date).toBe('20260929');
  });

  it('validates the four US mapping assessment states and nullable count contract',()=>{
    for(const [state,count,complete] of [
      ['NOT_EVALUATED',null,false],['INSUFFICIENT',null,false],
      ['ASSESSED_ZERO',0,true],['ASSESSED_WITH_RELATIONS',1,true],
    ] as const){
      const payload=attention([]);payload.us_mapping_diagnostics=usRelationDiagnostics(state,count,complete);
      expect(validateManagerWorkspace(workspace(payload),date).research_attention?.us_mapping_diagnostics?.assessment_state).toBe(state);
    }
    const topLevel=attention([]);const diagnostics=usRelationDiagnostics('NOT_EVALUATED',null,false);
    topLevel.us_mapping_diagnostics=diagnostics;
    const value=workspace(topLevel);
    value.us_market_attention={...flags,schema_version:'v4.manager_research.us_market_bridge.v1',
      target_trade_date:date,research_cutoff:'2026-09-25T09:40:00+08:00',status:'CANNOT_CONFIRM',
      expected_us_session:null,coverage_scope:'FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
      raw_industry_up:[],raw_individual_up:[],coverage:{},source_identity:null,gaps:[],
      research_material_input:diagnostics.material_input as any,mapping_diagnostics:diagnostics as any};
    expect(validateManagerWorkspace(value,date).us_market_attention?.mapping_diagnostics?.assessment_state).toBe('NOT_EVALUATED');
    const falseZero=attention([]);falseZero.us_mapping_diagnostics=usRelationDiagnostics('NOT_EVALUATED',0,false);
    expect(()=>validateManagerWorkspace(workspace(falseZero),date)).toThrow('WORKSPACE_US_RELATION_UNEVALUATED_COUNT_INVALID');
    const missingZero=attention([]);missingZero.us_mapping_diagnostics=usRelationDiagnostics('ASSESSED_ZERO',null,true);
    expect(()=>validateManagerWorkspace(workspace(missingZero),date)).toThrow('WORKSPACE_US_RELATION_ZERO_COUNT_INVALID');
  });

  it('accepts a valid cross-group score increase and makes the validated cards renderable', () => {
    const validated = validateManagerWorkspace(workspace(attention(newContractCards())), date);
    expect(validated.research_attention?.cards.map(row => row.research_attention_score)).toEqual([24, 95]);
    expect(validated.research_attention?.cards[1].freshest_acquired_at).toBeNull();
    expect(validated.research_attention?.cards[1].freshest_published_at).toBeNull();

    const host = document.createElement('div');
    renderResearchAttention(host, validated.research_attention);
    expect(host.querySelectorAll('.research-attention-card')).toHaveLength(2);
    expect(host.textContent).toContain('下一步核什么：Check the next evidence.');
    expect(host.textContent).toContain('什么时候降级/撤销：Withdraw when invalidated.');
  });

  it('rejects score increases within the same evidence group', () => {
    const cards = [card({ symbol: 'HK.01001', score: 20 }), card({ symbol: 'HK.01002', score: 30 })];
    expect(() => validateManagerWorkspace(workspace(attention(cards)), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
  });

  it('rejects an unknown state, illegal group mapping, and a decision missing required explanation fields', () => {
    const invalidState = newContractCards();
    (invalidState[0].decision as JsonObject).state = 'BUY';
    expect(() => validateManagerWorkspace(workspace(attention(invalidState)), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const invalidGroup = newContractCards();
    (invalidGroup[0].decision as JsonObject).group_order = 4;
    expect(() => validateManagerWorkspace(workspace(attention(invalidGroup)), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const malformed = newContractCards();
    delete (malformed[0].decision as JsonObject).invalidation;
    expect(() => validateManagerWorkspace(workspace(attention(malformed)), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');
  });

  it('accepts the legacy contract only with its original global score order', () => {
    const oldAttention: JsonObject = {
      ...attention([
        { symbol: 'HK.01001', name: 'first', research_attention_score: 58, research_attention_band: 'IMMEDIATE_RESEARCH',
          qualified_lane_count: 1, qualified_lanes: ['COMPANY_MATERIAL'], why_now: [], missing: [],
          screen_classification: null, original_screen_rank: null, evidence: [], ...flags },
        { symbol: 'HK.01002', name: 'second', research_attention_score: 44, research_attention_band: 'HIGH_RESEARCH',
          qualified_lane_count: 1, qualified_lanes: ['COMPANY_MATERIAL'], why_now: [], missing: [],
          screen_classification: null, original_screen_rank: null, evidence: [], ...flags },
      ]),
      priority_name: 'RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK',
    };
    delete oldAttention.ordering_basis;
    delete oldAttention.freshness;
    const validated = validateManagerWorkspace(workspace(oldAttention), date);
    expect(validated.research_attention?.cards.map(row => row.research_attention_score)).toEqual([58, 44]);
  });

  it('keeps legacy score ordering while rejecting unbound legacy trend evidence', () => {
    const validLegacy: JsonObject = {
      ...attention([card({ symbol: 'HK.01030', score: 30, lanes: ['TREND_CONTINUATION'] })]),
      priority_name: 'RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK',
    };
    delete validLegacy.ordering_basis;
    delete validLegacy.freshness;
    const validated = validateManagerWorkspace(workspace(validLegacy), date);
    expect(validated.research_attention?.cards.map(row => row.research_attention_score)).toEqual([30]);

    const malformed: JsonObject = {
      ...validLegacy,
      cards: (validLegacy.cards as JsonObject[]).map(row => ({
        ...row, evidence: (row.evidence as JsonObject[]).map(evidence => ({ ...evidence, source_refs: [] })),
      })),
    };
    expect(() => validateManagerWorkspace(workspace(malformed), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_ORDER_INVALID');
  });

  it('rejects unknown priorities and preserved safety / screen / stage flags when false', () => {
    const unknown = attention(newContractCards());
    unknown.priority_name = 'UNKNOWN_PRIORITY';
    expect(() => validateManagerWorkspace(workspace(unknown), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_PRIORITY_INVALID');

    const forbiddenFields: Array<[string, unknown]> = [
      ['RESEARCH_ONLY', false], ['production_allowed', true], ['buy_gate_updated', true], ['orders_sent', true],
      ['strict_near_unchanged', false], ['existing_focus_rank_unchanged', false], ['stage_unchanged', false],
    ];
    for (const [key, value] of forbiddenFields) {
      const invalid = attention(newContractCards());
      invalid[key] = value;
      expect(() => validateManagerWorkspace(workspace(invalid), date), key).toThrow();
    }
  });

  it('requires cutoff-bound acquisition evidence from every claimed company, official, and US lane', () => {
    const missingCompanyAcquisition = card({ symbol: 'HK.01011', score: 30, acquired: null });
    expect(() => validateManagerWorkspace(workspace(attention([missingCompanyAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const aggregateCannotReplaceCompanyAcquisition = card({
      symbol: 'HK.01017', score: 30, acquired: '2026-09-25T09:15:00+08:00',
      evidence: [companyEvidence('2026-09-25T09:00:00+08:00', null)],
    });
    expect(() => validateManagerWorkspace(workspace(attention([aggregateCannotReplaceCompanyAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const lateCompanyAcquisition = card({ symbol: 'HK.01012', score: 30, acquired: '2026-09-25T09:41:00+08:00' });
    expect(() => validateManagerWorkspace(workspace(attention([lateCompanyAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const staleCompanyAcquisition = card({
      symbol: 'HK.01018', score: 30, acquired: '2026-09-19T09:15:00+08:00',
      evidence: [companyEvidence('2026-09-19T09:00:00+08:00', '2026-09-19T09:15:00+08:00')],
    });
    expect(() => validateManagerWorkspace(workspace(attention([staleCompanyAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const emptyCompanyEvidence = card({
      symbol: 'HK.01019', score: 30, lanes: ['COMPANY_MATERIAL'], company: 1,
      evidence: [],
    });
    expect(() => validateManagerWorkspace(workspace(attention([emptyCompanyEvidence])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const wrongLaneOfficialClaim = card({
      symbol: 'HK.01013', score: 30, lanes: ['OFFICIAL_ANNOUNCEMENT'], company: 2,
      evidence: [companyEvidence()],
    });
    expect(() => validateManagerWorkspace(workspace(attention([wrongLaneOfficialClaim])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const officialWithoutAcquisition = card({
      symbol: 'HK.01014', score: 30, lanes: ['OFFICIAL_ANNOUNCEMENT'], company: 2,
      evidence: [officialEvidence('BODY_UNREADABLE', null)],
    });
    expect(() => validateManagerWorkspace(workspace(attention([officialWithoutAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const officialBodyDigestMismatch = card({
      symbol: 'HK.01020', score: 30, lanes: ['OFFICIAL_ANNOUNCEMENT'], company: 3,
      evidence: [{ ...officialEvidence(), document_sha256: 'a'.repeat(64) }],
    });
    expect(() => validateManagerWorkspace(workspace(attention([officialBodyDigestMismatch])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const missingUsCapture = card({
      symbol: 'HK.01015', score: 30, lanes: ['US_INDUSTRY_MAPPING'],
      evidence: [usIndustryEvidence(null)],
    });
    expect(() => validateManagerWorkspace(workspace(attention([missingUsCapture])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const lateUsRelationAcquisition = card({
      symbol: 'HK.01016', score: 30, lanes: ['US_INDIVIDUAL_MAPPING'],
      evidence: [usIndividualEvidence('2026-09-25T09:30:00+08:00', '2026-09-25T09:41:00+08:00')],
    });
    expect(() => validateManagerWorkspace(workspace(attention([lateUsRelationAcquisition])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');
  });

  it('accepts real same-lane official and US mapping evidence and keeps company parsing out of official strength', () => {
    const mixed = card({
      symbol: 'HK.01021', score: 30,
      lanes: ['OFFICIAL_ANNOUNCEMENT','COMPANY_MATERIAL'], company: 2,
      evidence: [officialEvidence('BODY_UNREADABLE'), companyEvidence()],
    });
    const acceptedMixed = validateManagerWorkspace(workspace(attention([mixed])), date);
    expect(acceptedMixed.research_attention?.cards[0].decision?.company_evidence_strength).toBe(2);

    const misattributed = card({
      symbol: 'HK.01022', score: 30,
      lanes: ['OFFICIAL_ANNOUNCEMENT','COMPANY_MATERIAL'], company: 3,
      evidence: [officialEvidence('BODY_UNREADABLE'), companyEvidence()],
    });
    expect(() => validateManagerWorkspace(workspace(attention([misattributed])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const individual = card({ symbol: 'HK.01023', score: 40, lanes: ['US_INDIVIDUAL_MAPPING'] });
    const industry = card({ symbol: 'HK.01024', score: 30, lanes: ['US_INDUSTRY_MAPPING'] });
    const validatedMappings = validateManagerWorkspace(workspace(attention([individual, industry])), date);
    expect(validatedMappings.research_attention?.cards.map(row => row.decision?.context_strength)).toEqual([2, 1]);
  });

  it('binds trend continuation to the validated screen session and non-empty valid source references', () => {
    const matching = card({ symbol: 'HK.01031', score: 30, lanes: ['TREND_CONTINUATION'] });
    const valid = validateManagerWorkspace(workspace(attention([matching])), date);
    expect(valid.research_attention?.cards[0].decision?.market_confirmation_strength).toBe(1);

    const future = card({ symbol: 'HK.01032', score: 30, lanes: ['TREND_CONTINUATION'] });
    (future.evidence as JsonObject[])[0].verified_session = '20991231';
    expect(() => validateManagerWorkspace(workspace(attention([future])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const mismatched = card({ symbol: 'HK.01033', score: 30, lanes: ['TREND_CONTINUATION'] });
    (mismatched.evidence as JsonObject[])[0].verified_session = '20260924';
    expect(() => validateManagerWorkspace(workspace(attention([mismatched])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const emptyRefs = card({ symbol: 'HK.01034', score: 30, lanes: ['TREND_CONTINUATION'] });
    (emptyRefs.evidence as JsonObject[])[0].source_refs = [];
    expect(() => validateManagerWorkspace(workspace(attention([emptyRefs])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const malformedRefs = card({ symbol: 'HK.01035', score: 30, lanes: ['TREND_CONTINUATION'] });
    (malformedRefs.evidence as JsonObject[])[0].source_refs = [{ ...trendSourceRefs()[0], payload_sha256: 'invalid' }];
    expect(() => validateManagerWorkspace(workspace(attention([malformedRefs])), date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const missingScreen = workspace(attention([matching]));
    delete missingScreen.market_screen;
    expect(() => validateManagerWorkspace(missingScreen, date))
      .toThrow('WORKSPACE_RESEARCH_ATTENTION_DECISION_INVALID');

    const futureScreen = card({ symbol: 'HK.01036', score: 30, lanes: ['TREND_CONTINUATION'] });
    (futureScreen.evidence as JsonObject[])[0].verified_session = '20991231';
    expect(() => validateManagerWorkspace(workspace(attention([futureScreen]), '20991231'), date))
      .toThrow('WORKSPACE_SCREEN_IDENTITY_INVALID');
  });
});
