import { cleanup, fireEvent, render, screen, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Workbench from "../Workbench.vue";
import { SCHEMA_VERSION } from "../types";
import type { DayData, Envelope } from "../types";
import { projectUSMappingPeerLists } from "../us_mapping_stock_lists";

type PeerFixture = {
  baskets: Record<string, Record<string, unknown>[]>;
  relations: Record<string, unknown>[];
  rows: Record<string, unknown>[];
};

const SESSION = "20261016";

function sampleDay(overrides: Partial<DayData>): DayData {
  return {
    snapshot: {
      context: { market: "HK_CONNECT", target_date: "20261020", phase: "RETROSPECTIVE", cutoff: null },
      run_id: "peer-list-run"
    },
    stocks: [], counts: null, pagination: { total: 1, offset: 0, limit: 50 },
    ...overrides
  };
}

function wrapped<T>(data: T): Envelope<T> {
  return {
    schema_version: SCHEMA_VERSION, state: "READY", data, gaps: null,
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false
  };
}

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

function relation(id: string, usSymbol: string, returnPct: string | null, overrides: Record<string, unknown> = {}) {
  return {
    catalog_relation_id: id,
    catalog_disposition: "ADOPTED_BUSINESS_PEER",
    relation_type: "BUSINESS_PEER",
    source_session: SESSION,
    quote_status: "VERIFIED",
    us_symbol: usSymbol,
    us_source_return_pct: returnPct,
    quote: { symbol: usSymbol, session_date: SESSION },
    catalog_fact: `fact for ${id}`,
    catalog_mechanism: `mechanism for ${id}`,
    catalog_failure: `risk for ${id}`,
    catalog_condition: `condition for ${id}`,
    ...overrides
  };
}

function basket(peerBucket: string, relationId: string, usSymbol: string, returnPct: string | null,
  overrides: Record<string, unknown> = {}) {
  const members = returnPct === null ? [] : [{ symbol: usSymbol, return_pct: returnPct, relation_ids: [relationId] }];
  return {
    route: "SUBINDUSTRY_BUSINESS_PEER",
    peer_bucket: peerBucket,
    coverage_state: returnPct === null ? "NO_COVERAGE" : "READY",
    relation_ids: [relationId],
    members,
    ...overrides
  };
}

function peerFixture(): PeerFixture {
  return {
    baskets: {
      "HK.00297": [
        basket("phosphate and potash", "R-MOS", "MOS", "-0.686016"),
        basket("potash supply", "R-NTR", "NTR", "2.414487")
      ],
      "HK.00506": [basket("beverages and distribution", "R-PEP", "PEP", "2.422496")],
      "HK.00522": [basket("semiconductor assembly", "R-KLIC", "KLIC", "-5.322095")],
      "HK.03000": [basket("flat peer", "R-FLAT", "FLAT", "0")],
      "HK.03100": [basket("missing quote", "R-MISSING", "MISS", null)],
      "HK.03200": [basket("unverified quote", "R-UNVERIFIED", "UNV", "0.8")],
      "HK.09999": [basket("conditional route", "R-CONDITIONAL", "COND", "50")]
    },
    relations: [
      relation("R-MOS", "MOS", "-0.686016"),
      relation("R-NTR", "NTR", "2.414487"),
      relation("R-PEP", "PEP", "2.422496", { catalog_segment: "饮料销量/渠道" }),
      relation("R-KLIC", "KLIC", "-5.322095"),
      relation("R-FLAT", "FLAT", "0"),
      relation("R-MISSING", "MISS", null, { quote_status: "MISSING_OR_UNVERIFIED" }),
      relation("R-UNVERIFIED", "UNV", "0.8", { quote_status: "MISSING_OR_UNVERIFIED" }),
      relation("R-CONDITIONAL", "COND", "50", { catalog_disposition: "ADOPTED_CONDITIONAL_ROUTE" })
    ],
    rows: [
      { symbol: "HK.00297", name: "中化化肥" },
      { symbol: "HK.00506", name: "中国食品" },
      { symbol: "HK.00522", name: "ASMPT" }
    ]
  };
}

describe("US mapping peer stock lists", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261020"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("separates verified source moves, preserves mixed relations, and keeps quote gaps pending", () => {
    const fixture = peerFixture();
    const lists = projectUSMappingPeerLists({
      source_session: SESSION,
      target_date: "target-session",
      formal_target_eligibility: "CANNOT_CONFIRM",
      rows: fixture.rows,
      catalog_peer_baskets: fixture.baskets,
      catalog_relation_dispositions: fixture.relations
    });

    expect(lists.acceptedRelationCount).toBe(7);
    expect(lists.positive.map(row => row.hkSymbol)).toEqual(["HK.00297", "HK.00506"]);
    expect(lists.negative.map(row => row.hkSymbol)).toEqual(["HK.00297", "HK.00522"]);
    expect(lists.flat.map(row => row.hkSymbol)).toEqual(["HK.03000"]);
    expect(lists.unknown.map(row => row.hkSymbol)).toEqual(["HK.03100", "HK.03200"]);
    expect(lists.mixedStockCount).toBe(1);
    expect(lists.positive[0].stockDirectionLabel).toBe("同一港股正负同行观察并存");
    expect(lists.negative[0].hasMixedStockDirection).toBe(true);
    expect(lists.positive[1].consumerRetail).toBe(true);
    expect(lists.negative[1].hkName).toBe("ASMPT");
    expect(lists.positive[1].catalogFact).toBe("fact for R-PEP");
    expect(lists.positive[1].catalogFailure).toBe("risk for R-PEP");
    expect(lists.positive[1].catalogCondition).toBe("condition for R-PEP");
    expect(lists.unknown[1].returnPct).toBeNull();
    expect(lists.unknown[1].returnLabel).toContain("待核");
    expect(lists.observations.some(row => row.hkSymbol === "HK.09999")).toBe(false);
    expect(lists.formalTargetEligibility).toBe("CANNOT_CONFIRM");
  });

  it("uses conservative evidence fallbacks and does not infer direction when sessions disagree", () => {
    const lists = projectUSMappingPeerLists({
      source_session: SESSION,
      catalog_peer_baskets: {
        "HK.04000": [basket("peer", "R-MISMATCH", "MISMATCH", "1.25")]
      },
      catalog_relation_dispositions: [relation("R-MISMATCH", "MISMATCH", "1.25", {
        quote: { symbol: "MISMATCH", session_date: "20261015" },
        catalog_fact: "", catalog_mechanism: "", catalog_failure: "", catalog_condition: ""
      })]
    });

    expect(lists.unknown).toHaveLength(1);
    expect(lists.unknown[0].returnPct).toBeNull();
    expect(lists.unknown[0].statusDetail).toContain("不一致");
    expect(lists.unknown[0].catalogFact).toContain("需补证");
    expect(lists.unknown[0].catalogFailure).toContain("保持待核");
    expect(lists.formalTargetEligibility).toBe("CANNOT_CONFIRM");
  });

  it("keeps verified returns pending when peer coverage is absent", () => {
    const missingCoverage = basket("peer", "R-NO-COVERAGE-STATE", "PEER", "1.25");
    delete missingCoverage.coverage_state;
    const lists = projectUSMappingPeerLists({
      source_session: SESSION,
      catalog_peer_baskets: { "HK.04010": [missingCoverage] },
      catalog_relation_dispositions: [relation("R-NO-COVERAGE-STATE", "PEER", "1.25")]
    });

    expect(lists.positive).toHaveLength(0);
    expect(lists.unknown).toHaveLength(1);
    expect(lists.unknown[0].returnPct).toBeNull();
    expect(lists.unknown[0].statusDetail).toContain("同行组状态缺失");
  });

  it("keeps returns pending without valid quote-session and source-session evidence", () => {
    const noSessionRelation = relation("R-NO-SESSION", "UNDATED", "1.25", {
      source_session: "",
      quote: { symbol: "UNDATED" }
    });
    const noSessionLists = projectUSMappingPeerLists({
      catalog_peer_baskets: {
        "HK.04020": [basket("peer", "R-NO-SESSION", "UNDATED", "1.25")]
      },
      catalog_relation_dispositions: [noSessionRelation]
    });

    expect(noSessionLists.positive).toHaveLength(0);
    expect(noSessionLists.unknown).toHaveLength(1);
    expect(noSessionLists.unknown[0].sourceSession).toBe("日期未知");
    expect(noSessionLists.unknown[0].statusDetail).toContain("会话日期证据缺失");

    const invalidSessionLists = projectUSMappingPeerLists({
      source_session: SESSION,
      catalog_peer_baskets: {
        "HK.04030": [basket("peer", "R-INVALID-SESSION", "INVALID", "1.25")]
      },
      catalog_relation_dispositions: [relation("R-INVALID-SESSION", "INVALID", "1.25", {
        quote: { symbol: "INVALID", session_date: "20260230" }
      })]
    });
    expect(invalidSessionLists.positive).toHaveLength(0);
    expect(invalidSessionLists.unknown[0].statusDetail).toContain("会话日期格式无效");
  });

  it("renders full positive and negative peer lists before the separate fixed-map counts", async () => {
    const fixture = peerFixture();
    const singleDay = {
      display_only: true,
      state: "PARTIAL",
      rules_version: "US_HK_SINGLE_DAY_MAPPING_TEST",
      mapping_policy_version: "FIXED_MAPPING_TEST",
      mapping_policy_sha256: "test-sha",
      target_date: "20261020",
      price_session: "price-session",
      source_session: SESSION,
      monthly_observed_scope_count: 3,
      formal_target_eligibility: "CANNOT_CONFIRM",
      counts: { BENEFIT: 0, RISK: 0, CONFLICT: 0, OBSERVATION: 0, UNMAPPED: 0, UNASSESSED: 0,
        SMALL_MOVE_WATCH: 0, C_WATCH: 0 },
      rows: fixture.rows,
      outside_pool_observations: [],
      benefit_rows: [], risk_rows: [], conflict_rows: [], observation_rows: [], unmapped_rows: [], unassessed_rows: [],
      gaps: [], strict_v1_status: "PAUSED_NOT_EXECUTED", deferred_gates: [], historical_pit_verified: false,
      research_effectiveness: "UNVERIFIED",
      catalog_peer_baskets: fixture.baskets,
      catalog_relation_dispositions: fixture.relations
    };
    const factorSummary = {
      display_only: true,
      rules_version: "US_DAILY_RETURN_FACTOR_TEST",
      target_date: "20261020",
      phase: "RETROSPECTIVE",
      us_source_symbol_count: 0,
      proxy_source_count: 0,
      expected_proxy_source_count: 0,
      verified_proxy_source_count: 0,
      unknown_proxy_source_count: 0,
      eligible_hk_scope_count: 3,
      unique_factor_stock_count: 0,
      factor_path_count: 0,
      unknown_factor_stock_count: 0,
      registry_fact_count: 0,
      paired_review_available: true,
      source_session: SESSION,
      historical_pit_verified: false,
      combined_source_and_stock_count: null,
      single_day_mapping: singleDay
    };
    const mappingSummary = {
      display_only: true,
      plan_run_id: "peer-list-run",
      source_symbol_count: 0,
      source_row_count: 0,
      relation_row_count: 0,
      mapped_hk_count: 0,
      source_decision_counts: {},
      mixed_source_count: 0,
      coverage: { scope_count: 0, observed_count: 0, assessed_count: 0, unassessed_count: 0 },
      groups: [],
      factor_summary: factorSummary
    } as unknown as NonNullable<DayData["us_mapping_summary"]>;
    const day = sampleDay({ us_mapping_summary: mappingSummary });
    vi.stubGlobal("fetch", vi.fn(async () => response(wrapped(day))));

    render(Workbench);
    const peerLists = await screen.findByRole("region", { name: "已采用美股同行来源观察名单" });
    const peerListQuery = within(peerLists);
    const positiveList = peerListQuery.getByRole("article", { name: "正向美股来源观察名单" });
    const negativeList = peerListQuery.getByRole("article", { name: "负向美股来源观察名单" });
    expect(within(positiveList).getByText("HK.00297 中化化肥")).toBeTruthy();
    expect(within(positiveList).getByText("HK.00506 中国食品")).toBeTruthy();
    expect(within(negativeList).getByText("HK.00297 中化化肥")).toBeTruthy();
    expect(within(negativeList).getByText("HK.00522 ASMPT")).toBeTruthy();
    expect(within(positiveList).getByText(/2\.422496%/)).toBeTruthy();
    expect(within(positiveList).getByText("风险：risk for R-PEP")).toBeTruthy();
    expect(screen.getByRole("button", { name: /固定映射受益判定 0/ })).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: /消费与零售/ }));
    expect(peerListQuery.getByText("HK.00506 中国食品")).toBeTruthy();
    expect(peerListQuery.queryByText("HK.00297 中化化肥")).toBeNull();
    expect(peerListQuery.queryByText("HK.00522 ASMPT")).toBeNull();
  });
});
