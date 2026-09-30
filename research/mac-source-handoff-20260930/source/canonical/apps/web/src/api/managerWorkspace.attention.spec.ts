import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace, type JsonObject, type ManagerWorkspace, type ResearchAttentionCard } from './managerWorkspace';
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
