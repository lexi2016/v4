import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import AShareTop200Panel from "./AShareTop200Panel.vue";

const NOT_MATERIALIZED_STAGE = { status: "NOT_MATERIALIZED", hit_count: null };

function missingPool(pool_id: string, display_name: string) {
  return {
    pool_id,
    display_name,
    status: "CANNOT_CONFIRM",
    materialized: false,
    partial: false,
    selected_count: null,
    hit_count: null,
    top200_coverage_pct: null,
    selection_hit_rate_pct: null,
  };
}

const MAIN_1103 = {
  pool_id: "a_d1_premarket_pool",
  display_name: "A股 D-1 主预选池",
  status: "V192_CANDIDATE_READY",
  signal_date: "20261102",
  materialized: true,
  partial: false,
  selected_count: 135,
  hit_count: 8,
  top200_coverage_pct: 4.0,
  selection_hit_rate_pct: 5.93,
};

const RESEARCH_1103 = {
  pool_id: "a_share_research_recommendation_pool",
  display_name: "A股研报推荐股票池",
  status: "RESEARCH_RECOMMENDATION_POOL_READY",
  signal_date: "20261102",
  materialized: true,
  partial: false,
  selected_count: 318,
  hit_count: 20,
  top200_coverage_pct: 10.0,
  selection_hit_rate_pct: 6.29,
};

const MAIN_1104 = {
  ...MAIN_1103,
  signal_date: "20261103",
  selected_count: 48,
  hit_count: 1,
  top200_coverage_pct: 0.5,
  selection_hit_rate_pct: 2.08,
};

const RESEARCH_1104 = {
  ...RESEARCH_1103,
  signal_date: "20261104",
  selected_count: 314,
  hit_count: 24,
  top200_coverage_pct: 12.0,
  selection_hit_rate_pct: 7.64,
};

const payload = {
  schema_version: "v4.research.a_share_pool_top200.v1",
  generated_at: "2026-11-04T16:45:00+08:00",
  latest_available_date: "20261104",
  available_dates: ["20261030", "20261102", "20261103", "20261104"],
  window_note: "only dates with A-share product, stage, pool, or official daily evidence are listed.",
  dates: [
    {
      date: "20261029",
      status: "NOT_MATERIALIZED",
      reason: "NO_OFFICIAL_DAILY_PACKAGE",
      stage_coverage: {
        available: 2,
        total: 7,
        missing_stages: ["STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_1445_1500"],
      },
      seven_stage: {
        status: "PARTIAL_STAGE_COVERAGE",
        selected_count: 19,
        hit_count: null,
        top_count: null,
        top200_coverage_pct: null,
        selection_hit_rate_pct: null,
        stages: {},
      },
      a_pool: {
        status: "PARTIAL_POOL_COVERAGE",
        reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
        materialized: true,
        evaluable: false,
        selected_count: 58,
        hit_count: null,
        top_count: null,
        top200_coverage_pct: null,
        selection_hit_rate_pct: null,
        pool_count: 6,
        materialized_pool_count: 1,
        partial_pool_ids: [],
        missing_pool_ids: [
          "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
          "a_share_research_recommendation_pool", "a_share_baimao_research_map",
          "wechat_public_account_v3_preselect",
        ],
        missing_mandatory_pool_ids: [
          "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
          "a_share_research_recommendation_pool",
        ],
        partial_mandatory_pool_ids: [],
        pools: [
          {
            ...MAIN_1103,
            signal_date: "20261028",
            selected_count: 58,
            hit_count: null,
            top200_coverage_pct: null,
            selection_hit_rate_pct: null,
          },
          missingPool("a_d1_fupan_watchlist_pool", "A股 D-1 复盘继续观察池"),
          missingPool("a_d1_stage7_fenshi_review_pool", "A股 D-1 Stage7/分时复盘池"),
          missingPool("a_share_research_recommendation_pool", "A股研报推荐股票池"),
          missingPool("a_share_baimao_research_map", "白毛卡点研究池"),
          missingPool("wechat_public_account_v3_preselect", "公众号股票池"),
        ],
      },
      top200: null,
    },
    {
      date: "20261030",
      status: "PARTIAL",
      reason: "PARTIAL_POOL_OR_STAGE_COVERAGE",
      stage_coverage: {
        available: 3,
        total: 7,
        missing_stages: ["STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945"],
      },
      seven_stage: {
        status: "PARTIAL_STAGE_COVERAGE",
        selected_count: 29,
        hit_count: 7,
        top_count: 200,
        top200_coverage_pct: 3.5,
        selection_hit_rate_pct: 24.14,
        stages: {},
      },
      a_pool: {
        status: "PARTIAL_POOL_COVERAGE",
        reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
        materialized: true,
        evaluable: true,
        selected_count: 531,
        hit_count: 49,
        top_count: 200,
        top200_coverage_pct: 24.5,
        selection_hit_rate_pct: 9.23,
        pool_count: 6,
        materialized_pool_count: 2,
        partial_pool_ids: [],
        missing_pool_ids: [
          "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
          "a_share_baimao_research_map", "wechat_public_account_v3_preselect",
        ],
        missing_mandatory_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        partial_mandatory_pool_ids: [],
        pools: [],
      },
      top200: { top_count: 200, min_change_pct: 3.3967, source: "STORED_TOP200_ARTIFACT" },
    },
    {
      date: "20261102",
      status: "PARTIAL",
      reason: "PARTIAL_POOL_OR_STAGE_COVERAGE",
      stage_coverage: {
        available: 0,
        total: 7,
        missing_stages: [
          "STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945",
          "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500",
        ],
      },
      seven_stage: {
        status: "NOT_MATERIALIZED",
        selected_count: null,
        hit_count: null,
        top_count: 200,
        top200_coverage_pct: null,
        selection_hit_rate_pct: null,
        stages: {},
      },
      a_pool: {
        status: "PARTIAL_POOL_COVERAGE",
        reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
        materialized: true,
        evaluable: true,
        selected_count: 765,
        hit_count: 41,
        top_count: 200,
        top200_coverage_pct: 20.5,
        selection_hit_rate_pct: 5.36,
        pool_count: 6,
        materialized_pool_count: 4,
        partial_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        missing_pool_ids: ["a_share_baimao_research_map", "wechat_public_account_v3_preselect"],
        missing_mandatory_pool_ids: [],
        partial_mandatory_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        pools: [],
      },
      top200: { top_count: 200, min_change_pct: 9.9698, source: "COMPUTED_FROM_OFFICIAL_DAILY_PACKAGE" },
    },
    {
      date: "20261103",
      status: "PARTIAL",
      reason: "PARTIAL_POOL_OR_STAGE_COVERAGE",
      stage_coverage: { available: 6, total: 7, missing_stages: ["STAGE_0925"] },
      seven_stage: {
        status: "PARTIAL_STAGE_COVERAGE",
        selected_count: 49,
        hit_count: 9,
        top_count: 200,
        top200_coverage_pct: 4.5,
        selection_hit_rate_pct: 18.37,
        stages: {
          STAGE_0925: NOT_MATERIALIZED_STAGE,
          STAGE_0930_0935: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 3 },
          STAGE_0935_0940: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 2 },
          STAGE_0940_0945: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 0 },
          STAGE_0945_1030: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 4 },
          STAGE_1300_1315: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 2 },
          STAGE_1445_1500: { status: "READY", row_count: 10, unique_codes: 10, hit_count: 2 },
        },
      },
      a_pool: {
        status: "PARTIAL_POOL_COVERAGE",
        reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
        materialized: true,
        evaluable: true,
        selected_count: 434,
        hit_count: 27,
        top_count: 200,
        top200_coverage_pct: 13.5,
        selection_hit_rate_pct: 6.22,
        pool_count: 6,
        materialized_pool_count: 2,
        partial_pool_ids: [],
        missing_pool_ids: [
          "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
          "a_share_baimao_research_map", "wechat_public_account_v3_preselect",
        ],
        missing_mandatory_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        partial_mandatory_pool_ids: [],
        pools: [
          MAIN_1103,
          missingPool("a_d1_fupan_watchlist_pool", "A股 D-1 复盘继续观察池"),
          missingPool("a_d1_stage7_fenshi_review_pool", "A股 D-1 Stage7/分时复盘池"),
          RESEARCH_1103,
          missingPool("a_share_baimao_research_map", "白毛卡点研究池"),
          missingPool("wechat_public_account_v3_preselect", "公众号股票池"),
        ],
      },
      top200: { top_count: 200, min_change_pct: 4.0119, source: "COMPUTED_FROM_OFFICIAL_DAILY_PACKAGE" },
    },
    {
      date: "20261104",
      status: "PARTIAL",
      reason: "PARTIAL_POOL_OR_STAGE_COVERAGE",
      stage_coverage: { available: 5, total: 7, missing_stages: ["STAGE_0925", "STAGE_1445_1500"] },
      seven_stage: {
        status: "PARTIAL_STAGE_COVERAGE",
        selected_count: 45,
        hit_count: 11,
        top_count: 200,
        top200_coverage_pct: 5.5,
        selection_hit_rate_pct: 24.44,
        stages: {},
      },
      a_pool: {
        status: "PARTIAL_POOL_COVERAGE",
        reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
        materialized: true,
        evaluable: true,
        selected_count: 379,
        hit_count: 24,
        top_count: 200,
        top200_coverage_pct: 12.0,
        selection_hit_rate_pct: 6.33,
        pool_count: 6,
        materialized_pool_count: 4,
        partial_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        missing_pool_ids: ["a_share_baimao_research_map", "wechat_public_account_v3_preselect"],
        missing_mandatory_pool_ids: [],
        partial_mandatory_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
        pools: [
          MAIN_1104,
          {
            ...MAIN_1104,
            pool_id: "a_d1_fupan_watchlist_pool",
            display_name: "A股 D-1 复盘继续观察池",
            status: "FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL",
            partial: true,
            selected_count: 40,
            hit_count: 1,
            selection_hit_rate_pct: 2.5,
          },
          {
            ...MAIN_1104,
            pool_id: "a_d1_stage7_fenshi_review_pool",
            display_name: "A股 D-1 Stage7/分时复盘池",
            status: "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
            partial: true,
            selected_count: 10,
            hit_count: 1,
            selection_hit_rate_pct: 10.0,
          },
          RESEARCH_1104,
          missingPool("a_share_baimao_research_map", "白毛卡点研究池"),
          missingPool("wechat_public_account_v3_preselect", "公众号股票池"),
        ],
      },
      top200: { top_count: 200, min_change_pct: 11.079, source: "COMPUTED_FROM_OFFICIAL_DAILY_PACKAGE" },
    },
  ],
};

function stubFetch(body: unknown = payload) {
  const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AShareTop200Panel", () => {
  it("renders whole-pool, seven-stage and Top200 cards for an exact date", async () => {
    const fetchMock = stubFetch();
    render(AShareTop200Panel, { props: { date: "20261103" } });

    const pool = await screen.findByTestId("a-top200-card-pool");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/top200-hit.json", { cache: "no-store" }));
    expect(pool.textContent).toContain("27/200");
    expect(pool.textContent).toContain("S 434");
    expect(pool.textContent).toContain("13.5%");
    expect(pool.textContent).toContain("6.22%");
    expect(pool.textContent).toContain("2/6 路");
    expect(pool.textContent).toContain("缺 复盘/Stage7/白毛/公众号");

    const seven = screen.getByTestId("a-top200-card-seven");
    expect(seven.textContent).toContain("9/200");
    expect(seven.textContent).toContain("S 49");
    expect(seven.textContent).toContain("4.5%");
    expect(seven.textContent).toContain("18.37%");
    expect(seven.textContent).toContain("6/7");
    expect(seven.textContent).toContain("STAGE_0925");

    const top200 = screen.getByTestId("a-top200-card-top200");
    expect(top200.textContent).toContain("200");
    expect(top200.textContent).toContain("4.0119%");
    expect(top200.textContent).toContain("COMPUTED_FROM_OFFICIAL_DAILY_PACKAGE");

    expect(screen.getAllByTestId("a-top200-date-row")).toHaveLength(5);
    expect(screen.getByTestId("a-top200-panel").textContent).toContain("RESEARCH_ONLY · 不形成买入建议");
    expect(screen.getByTestId("a-top200-panel").textContent).toContain("不使用四组公式名单");
    expect(screen.queryByTestId("a-top200-fallback")).toBeNull();
    expect(screen.queryByTestId("a-top200-card-four")).toBeNull();
  });

  it("renders the union and six per-pool rows, never drawing zeros for a missing pool", async () => {
    stubFetch();
    render(AShareTop200Panel, { props: { date: "20261103" } });

    const union = await screen.findByTestId("a-top200-pool-union");
    expect(union.textContent).toContain("A股所有预选池汇总");
    expect(union.textContent).toContain("434");
    expect(union.textContent).toContain("27/200");
    expect(union.textContent).toContain("13.5%");
    expect(union.textContent).toContain("6.22%");

    const rows = screen.getAllByTestId("a-top200-pool-row");
    expect(rows).toHaveLength(6);
    const main = rows.find((row) => row.textContent?.includes("A股 D-1 主预选池"));
    expect(main).toBeTruthy();
    expect(main!.textContent).toContain("135");
    expect(main!.textContent).toContain("8/200");
    expect(main!.textContent).toContain("4%");
    expect(main!.textContent).toContain("5.93%");

    const research = rows.find((row) => row.textContent?.includes("A股研报推荐股票池"));
    expect(research).toBeTruthy();
    expect(research!.textContent).toContain("318");
    expect(research!.textContent).toContain("20/200");
    expect(research!.textContent).toContain("10%");
    expect(research!.textContent).toContain("6.29%");

    const fupan = rows.find((row) => row.textContent?.includes("复盘继续观察池"));
    expect(fupan).toBeTruthy();
    expect(fupan!.textContent).toContain("未物化");
    expect(fupan!.textContent).not.toContain("0/200");
  });

  it("falls back to latest_available_date when the page date has no entry", async () => {
    stubFetch();
    render(AShareTop200Panel, { props: { date: "20261101" } });

    const fallback = await screen.findByTestId("a-top200-fallback");
    expect(fallback.textContent).toContain("当前页面日期 20261101 无 A 股选股池 Top200 物化");
    expect(fallback.textContent).toContain("latest_available_date 2026-11-04");
    expect(screen.getByTestId("a-top200-card-pool").textContent).toContain("24/200");
  });

  it("does not draw zeros for a date without official Top200", async () => {
    stubFetch();
    render(AShareTop200Panel, { props: { date: "20261029" } });

    const rows = await screen.findAllByTestId("a-top200-date-row");
    const missing = rows.find((row) => row.textContent?.includes("2026-10-29"));
    expect(missing).toBeTruthy();
    expect(missing!.textContent).toContain("未物化");
    expect(missing!.textContent).toContain("无官方日包");
    expect(missing!.textContent).not.toContain("0/200");
    expect(missing!.textContent).not.toContain("0.00%");

    const pool = screen.getByTestId("a-top200-card-pool");
    expect(pool.textContent).toContain("未物化");
    expect(pool.textContent).toContain("S 58");
    expect(pool.textContent).not.toContain("0/200");

    const seven = screen.getByTestId("a-top200-card-seven");
    expect(seven.textContent).toContain("未物化");
    expect(seven.textContent).toContain("2/7");
    expect(seven.textContent).not.toContain("0/200");
  });

  it("keeps the whole-pool metric when seven-stage selection is not materialized", async () => {
    stubFetch();
    render(AShareTop200Panel, { props: { date: "20261102" } });

    const pool = await screen.findByTestId("a-top200-card-pool");
    expect(pool.textContent).toContain("41/200");
    expect(pool.textContent).toContain("S 765");
    expect(pool.textContent).toContain("20.5%");
    expect(pool.textContent).toContain("5.36%");

    const seven = screen.getByTestId("a-top200-card-seven");
    expect(seven.textContent).toContain("未物化");
    expect(seven.textContent).toContain("0/7");
    expect(seven.textContent).not.toContain("0/200");

    const missing = screen.getAllByTestId("a-top200-date-row")
      .find((row) => row.textContent?.includes("2026-11-02"));
    expect(missing).toBeTruthy();
    expect(missing!.textContent).not.toContain("0/200");
  });

  it("renders the selected-date stage table and marks missing stages NOT_MATERIALIZED", async () => {
    stubFetch();
    render(AShareTop200Panel, { props: { date: "20261103" } });

    const rows = await screen.findAllByTestId("a-top200-stage-row");
    expect(rows).toHaveLength(7);
    const missing = rows.find((row) => row.textContent?.includes("STAGE_0925"));
    expect(missing).toBeTruthy();
    expect(missing!.textContent).toContain("NOT_MATERIALIZED");
    expect(missing!.textContent).toContain("未物化");

    const ready = rows.find((row) => row.textContent?.includes("STAGE_0940_0945"));
    expect(ready).toBeTruthy();
    expect(ready!.textContent).toContain("READY");
    expect(ready!.textContent).toContain("10");
    expect(ready!.textContent).toContain("0");
  });

  it("uses the real Top200 count T instead of a hard-coded 200 denominator", async () => {
    const narrowTop = {
      ...payload,
      latest_available_date: "20261103",
      dates: [{
        date: "20261103",
        status: "PARTIAL",
        reason: "PARTIAL_POOL_OR_STAGE_COVERAGE",
        stage_coverage: { available: 6, total: 7, missing_stages: ["STAGE_0925"] },
        seven_stage: {
          status: "PARTIAL_STAGE_COVERAGE",
          selected_count: 49,
          hit_count: 7,
          top_count: 150,
          top200_coverage_pct: 4.67,
          selection_hit_rate_pct: 14.29,
          stages: {},
        },
        a_pool: {
          status: "PARTIAL_POOL_COVERAGE",
          reason: "MISSING_OR_PARTIAL_MANDATORY_POOLS",
          materialized: true,
          evaluable: true,
          selected_count: 434,
          hit_count: 22,
          top_count: 150,
          top200_coverage_pct: 14.67,
          selection_hit_rate_pct: 5.07,
          pool_count: 6,
          materialized_pool_count: 2,
          partial_pool_ids: [],
          missing_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
          missing_mandatory_pool_ids: ["a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool"],
          partial_mandatory_pool_ids: [],
          pools: [],
        },
        top200: { top_count: 150, min_change_pct: 5.0, source: "TEST" },
      }],
    };
    stubFetch(narrowTop);
    render(AShareTop200Panel, { props: { date: "20261103" } });

    const pool = await screen.findByTestId("a-top200-card-pool");
    expect(pool.textContent).toContain("22/150");
    expect(pool.textContent).toContain("14.67%");
    expect(pool.textContent).toContain("5.07%");
    expect(pool.textContent).not.toContain("22/200");

    const seven = screen.getByTestId("a-top200-card-seven");
    expect(seven.textContent).toContain("7/150");
    expect(seven.textContent).toContain("4.67%");
    expect(seven.textContent).toContain("14.29%");
    expect(seven.textContent).not.toContain("7/200");

    const union = screen.getByTestId("a-top200-pool-union");
    expect(union.textContent).toContain("434");
    expect(union.textContent).toContain("22/150");
    expect(union.textContent).toContain("14.67%");

    const dateRow = screen.getByTestId("a-top200-date-row");
    expect(dateRow.textContent).toContain("22/150");
    expect(dateRow.textContent).toContain("7/150");
  });

  it("shows the pool projection failure and six placeholder pools instead of a blank gap", async () => {
    const unavailable = {
      ...payload,
      latest_available_date: "20261103",
      dates: [{
        date: "20261103",
        status: "PARTIAL",
        reason: "POOL_API_UNAVAILABLE",
        stage_coverage: { available: 6, total: 7, missing_stages: ["STAGE_0925"] },
        seven_stage: {
          status: "PARTIAL_STAGE_COVERAGE",
          selected_count: 49,
          hit_count: 9,
          top_count: 200,
          top200_coverage_pct: 4.5,
          selection_hit_rate_pct: 18.37,
          stages: {},
        },
        a_pool: {
          status: "NOT_MATERIALIZED",
          reason: "POOL_API_UNAVAILABLE",
          materialized: false,
          evaluable: false,
          selected_count: null,
          hit_count: null,
          top_count: 200,
          top200_coverage_pct: null,
          selection_hit_rate_pct: null,
          pool_count: 6,
          materialized_pool_count: 0,
          partial_pool_ids: [],
          missing_pool_ids: [
            "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
            "a_share_research_recommendation_pool", "a_share_baimao_research_map",
            "wechat_public_account_v3_preselect",
          ],
          missing_mandatory_pool_ids: [
            "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
            "a_share_research_recommendation_pool",
          ],
          partial_mandatory_pool_ids: [],
          pools: [],
        },
        top200: { top_count: 200, min_change_pct: 4.0119, source: "TEST" },
      }],
    };
    stubFetch(unavailable);
    render(AShareTop200Panel, { props: { date: "20261103" } });

    const pool = await screen.findByTestId("a-top200-card-pool");
    expect(pool.textContent).toContain("池投影不可读");
    expect(pool.textContent).toContain("0/6 路");
    expect(screen.getAllByTestId("a-top200-pool-row")).toHaveLength(6);
    expect(screen.getByTestId("a-top200-pool-union").textContent).toContain("未物化");
    const dateRow = screen.getByTestId("a-top200-date-row");
    expect(dateRow.textContent).toContain("池投影不可读");
  });

  it("emits close from the close button", async () => {
    stubFetch();
    const { emitted } = render(AShareTop200Panel, { props: { date: "20261103" } });
    await screen.findByTestId("a-top200-card-pool");

    await fireEvent.click(screen.getByTestId("a-top200-close"));
    expect(emitted("close")).toHaveLength(1);
  });

  it("shows an error instead of zeros when the static file cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
    render(AShareTop200Panel, { props: { date: "20261103" } });

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("HTTP 503"));
    expect(screen.queryByTestId("a-top200-card-pool")).toBeNull();
  });
});