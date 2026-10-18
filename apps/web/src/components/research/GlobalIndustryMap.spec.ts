import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import GlobalIndustryMap from "./GlobalIndustryMap.vue";
import {
  FUTU_US_NATIVE_BOARD_REGISTRY,
  FUTU_US_NATIVE_BOARD_REGISTRY_SHA256,
  FUTU_US_NATIVE_BOARD_REGISTRY_VERSION,
  GLOBAL_INDUSTRY_MAPPINGS,
  GLOBAL_INDUSTRY_MAPPING_VERSION,
  GLOBAL_INDUSTRY_OFFICIAL_BOARD_MAP,
} from "../../contracts/globalIndustries";

const response = (payload: unknown) => ({ ok: true, json: async () => payload });

function openDisclosure(label: string) {
  const summary = screen.getByText(label).closest("summary");
  if (!summary) throw new Error("Disclosure summary not found: " + label);
  const disclosure = summary.closest("details") as HTMLDetailsElement | null;
  if (!disclosure) throw new Error("Disclosure container not found: " + label);
  if (!disclosure.open) summary.click();
  return disclosure;
}

type FreshnessFixture = {
  state: "RECENT_BOUND_CAPTURE" | "STALE_CLOCK_WINDOW" | "STALE_EXCHANGE_SESSION" | "CANNOT_CONFIRM";
  observed_at: string;
  captured_at: string;
  exchange_calendar_status: string;
  latest_exchange_session_verified: boolean;
  new_capture_performed: false;
  cannot_confirm: string[];
};

type SnapshotOptions = {
  sourceDate?: string;
  status?: "READY" | "PARTIAL" | "CANNOT_CONFIRM";
  providerSessionDates?: string[];
  displayStatus?: "READY" | "PARTIAL" | "STALE" | "CANNOT_CONFIRM";
  freshness?: FreshnessFixture;
};

function recentFreshness(sourceDate: string, observedAt: string): FreshnessFixture {
  const capturedAt = `${sourceDate.slice(0, 4)}-${sourceDate.slice(4, 6)}-${sourceDate.slice(6)}T20:18:00Z`;
  return {
    state: "RECENT_BOUND_CAPTURE",
    observed_at: observedAt,
    captured_at: capturedAt,
    exchange_calendar_status: "CANNOT_CONFIRM",
    latest_exchange_session_verified: false,
    new_capture_performed: false,
    cannot_confirm: [],
  };
}

function snapshot(date: string, options: SnapshotOptions = {}) {
  const sourceDate = options.sourceDate ?? date;
  const status = options.status ?? "PARTIAL";
  const providerSessionDates = options.providerSessionDates ?? [sourceDate];
  const capturedDate = sourceDate || date;
  const updateTime = `${sourceDate.slice(0, 4)}-${sourceDate.slice(4, 6)}-${sourceDate.slice(6)} 16:00:00`;
  return {
    schema_version: "v3_5.global_industries.v2",
    status,
    ...(options.displayStatus ? { display_status: options.displayStatus } : {}),
    ...(options.freshness ? { freshness: options.freshness } : {}),
    target_date: date,
    research_date: date,
    source_date: sourceDate,
    capture_session_date: sourceDate,
    provider: "Futu OpenD",
    legacy_proxy_provider: "Tencent qt.gtimg.cn",
    legacy_proxy_status: "READY",
    provider_session_dates: providerSessionDates,
    provider_session_times: [updateTime],
    capture_phase: "POST_CLOSE",
    captured_at: `${capturedDate.slice(0, 4)}-${capturedDate.slice(4, 6)}-${capturedDate.slice(6)}T20:18:00Z`,
    generated_at: `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}T20:18:01Z`,
    mapping_version: GLOBAL_INDUSTRY_MAPPING_VERSION,
    requested_symbol_count: 24,
    available_symbol_count: status === "CANNOT_CONFIRM" ? 0 : 12,
    requested_board_count: 24,
    available_board_count: status === "CANNOT_CONFIRM" ? 0 : 12,
    proxy_requested_symbol_count: 33,
    proxy_available_symbol_count: 33,
    proxy_provider_session_dates: [sourceDate],
    proxy_provider_session_times: ["16:00:01"],
    source_response_sha256: "d".repeat(64),
    proxy_source_response_sha256: "e".repeat(64),
    quotes: [],
    proxy_quotes: [],
    futu_board_snapshot: {
      schema_version: "v3_5.futu_us_industry_snapshot.v1",
      status,
      provider: "Futu OpenD",
      market: "US",
      timezone: "America/New_York",
      capture_session_date: sourceDate,
      source_response_sha256: "d".repeat(64),
      cannot_confirm: status === "CANNOT_CONFIRM" ? ["FUTU_BOARD_CAPTURE_FAILED"] : ["FUTU_BOARD_MATCH_UNCONFIRMED"],
    },
    relation_evidence: {
      status: "READY",
      evidence_path: "v4/manager_research/us_mapping_relation_evidence_20261011.json",
      evidence_sha256: "a".repeat(64),
      review_path: "v4/manager_research/us_mapping_relation_evidence_review_20261011.json",
      review_sha256: "b".repeat(64),
      reviewed_at: "2026-10-11T10:33:23+08:00",
      reviewer_identity: "fixture",
      limitations: ["Target-date eligibility CANNOT_CONFIRM"],
      cannot_confirm: [],
      target_date_eligibility: "CANNOT_CONFIRM",
    },
    hk_relation_status: "READY",
    a_share_relation_status: "NO_REVIEWED_A_SHARE_RELATION_EVIDENCE",
    a_share_relations: [],
    target_date_eligibility: "CANNOT_CONFIRM",
    rows: GLOBAL_INDUSTRY_MAPPINGS.map((mapping, index) => {
      const futu = GLOBAL_INDUSTRY_OFFICIAL_BOARD_MAP[index];
      const matched = futu.board_name !== null && status !== "CANNOT_CONFIRM";
      const change = mapping.label === "云计算" ? 0.70035 : index % 2 ? -0.25 : 0.25;
      const rowStatus = matched ? "READY" : "CANNOT_CONFIRM";
      const boardName = matched ? futu.board_name : null;
      const relation = mapping.label === "云计算" && matched ? [{
        us_symbol: "NVDA",
        hk_symbol: "HK.00992",
        relationship_type: "NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER",
        direction: "HK_CUSTOMER_OR_INTEGRATOR_OF_US_TECHNOLOGY_PROVIDER",
        sources: [{ url: "https://example.test/source", title: "Evidence", published_at: "2025-10-21" }],
        limitations: ["Target-date eligibility CANNOT_CONFIRM"],
      }] : [];
      return {
        ...mapping,
        proxy_symbols: [...mapping.proxy_symbols],
        available_symbols: [],
        missing_symbols: [],
        requested_symbol_count: 0,
        available_symbol_count: 0,
        coverage: { available: 0, requested: 0 },
        coverage_pct: null,
        metric_kind: "OFFICIAL_BOARD",
        change_pct: matched ? change : null,
        pct_change: matched ? change : null,
        direction: !matched ? "CANNOT_CONFIRM" : change > 0 ? "UP" : "DOWN",
        status: rowStatus,
        quote_session_dates: matched ? [sourceDate] : [],
        quote_session_times: matched ? [updateTime] : [],
        official_board: {
          metric_kind: "OFFICIAL_BOARD",
          market: "US",
          plate_type: futu.plate_type,
          expected_board_name: futu.board_name,
          board_name: boardName,
          board_code: matched ? `US.LIST${2000 + index}` : null,
          update_time: matched ? updateTime : null,
          session_date: matched ? sourceDate : null,
          timezone: "America/New_York",
          last: matched ? 100 + change : null,
          previous_close: matched ? 100 : null,
          change_pct: matched ? change : null,
          plate_valid: matched ? true : null,
          rise_count: matched ? 15 : null,
          fall_count: matched ? 5 : null,
          equal_count: matched ? 0 : null,
          member_count: matched ? 1 : null,
          relation_constituents: relation.length ? ["NVDA"] : [],
          membership_status: matched ? "READY" : "CANNOT_CONFIRM",
          relations: relation,
          relation_status: relation.length ? "READY" : matched ? "NO_REVIEWED_RELATION_INTERSECTION" : "CANNOT_CONFIRM",
          relation_cannot_confirm: [],
          target_date_eligibility: "CANNOT_CONFIRM",
          cannot_confirm: matched ? [] : ["FUTU_BOARD_MATCH_UNCONFIRMED"],
        },
        proxy_reference: {
          metric_kind: mapping.mapping_type.includes("basket") ? "STOCK_BASKET_REFERENCE" : "ETF_REFERENCE",
          provider: "Tencent qt.gtimg.cn",
          mapping_type: mapping.mapping_type,
          proxy_symbols: [...mapping.proxy_symbols],
          available_symbols: [...mapping.proxy_symbols],
          missing_symbols: [],
          requested_symbol_count: mapping.proxy_symbols.length,
          available_symbol_count: mapping.proxy_symbols.length,
          coverage: { available: mapping.proxy_symbols.length, requested: mapping.proxy_symbols.length },
          coverage_pct: 100,
          change_pct: mapping.label === "云计算" ? 2.216066 : 0.35,
          direction: "UP",
          status: "READY",
          quote_session_dates: [sourceDate],
          quote_session_times: ["16:00:01"],
          cannot_confirm: [],
        },
        cannot_confirm: matched ? [] : ["FUTU_BOARD_MATCH_UNCONFIRMED"],
      };
    }),
    cannot_confirm: [],
    artifact: null,
    manifest: null,
    receipt: null,
    write_policy: "read_only",
    recommendation_status: "RESEARCH_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
}

function withNativeBoardSnapshot(value: any, sourceDate: string, readyCount: number = FUTU_US_NATIVE_BOARD_REGISTRY.length) {
  const updateTime = `${sourceDate.slice(0, 4)}-${sourceDate.slice(4, 6)}-${sourceDate.slice(6)} 16:00:00`;
  const rows = FUTU_US_NATIVE_BOARD_REGISTRY.map((identity, index) => {
    const ready = index < readyCount;
    const change = index % 2 === 0 ? 0.25 : -0.25;
    const membershipReady = identity.board_name !== "人工智能";
    return {
      ...identity,
      metric_kind: "OFFICIAL_BOARD",
      market: "US",
      expected_board_name: identity.board_name,
      update_time: ready ? updateTime : null,
      session_date: ready ? sourceDate : null,
      timezone: "America/New_York",
      last: ready ? 100 + change : null,
      previous_close: ready ? 100 : null,
      change_pct: ready ? change : null,
      plate_valid: ready ? true : null,
      rise_count: ready ? 10 : null,
      fall_count: ready ? 8 : null,
      equal_count: ready ? 1 : null,
      membership_status: membershipReady ? "READY" : "CANNOT_CONFIRM",
      member_count: membershipReady ? 2 : null,
      membership_sha256: membershipReady ? "f".repeat(64) : "",
      membership_cannot_confirm: membershipReady ? [] : ["FUTU_BOARD_MEMBERSHIP_FAILED:-1"],
      source_response_sha256: "e".repeat(64),
      status: ready ? "READY" : "CANNOT_CONFIRM",
      cannot_confirm: ready ? [] : ["FUTU_BOARD_SNAPSHOT_NOT_RETURNED"],
    };
  });
  const status = readyCount === FUTU_US_NATIVE_BOARD_REGISTRY.length
    ? "READY"
    : readyCount > 0 ? "PARTIAL" : "CANNOT_CONFIRM";
  value.native_board_snapshot = {
    schema_version: "v3_5.futu_us_native_board_snapshot.v2",
    registry_version: FUTU_US_NATIVE_BOARD_REGISTRY_VERSION,
    registry_sha256: FUTU_US_NATIVE_BOARD_REGISTRY_SHA256,
    provider: "Futu OpenD",
    market: "US",
    timezone: "America/New_York",
    capture_session_date: sourceDate,
    source_response_sha256: "d".repeat(64),
    requested_board_count: FUTU_US_NATIVE_BOARD_REGISTRY.length,
    available_board_count: readyCount,
    status,
    rows,
    cannot_confirm: readyCount === FUTU_US_NATIVE_BOARD_REGISTRY.length ? [] : ["FUTU_BOARD_SNAPSHOT_NOT_RETURNED"],
    membership_cannot_confirm: ["FUTU_BOARD_MEMBERSHIP_FAILED:-1"],
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
  value.native_display_status = status;
  value.native_freshness = { state: "RECENT_BOUND_CAPTURE", cannot_confirm: [] };
  return value;
}

describe("GlobalIndustryMap", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it.each(["STALE", "PARTIAL", "CANNOT_CONFIRM"] as const)("does not rank %s snapshot prices in the top three", async (displayStatus) => {
    const date = "20260908";
    const freshness = recentFreshness(date, "2026-09-09T10:00:00+08:00");
    if (displayStatus === "STALE") freshness.state = "STALE_EXCHANGE_SESSION";
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url === "/api/v3/research/dates"
      ? { market_snapshot_dates: [date] }
      : snapshot(date, { displayStatus, freshness }))));
    render(GlobalIndustryMap, { props: { targetDate: "20260909" } });
    const expectedStatus = displayStatus === "STALE"
      ? "快照偏旧"
      : displayStatus === "PARTIAL" ? "部分确认" : "暂无法确认";
    await screen.findByText(expectedStatus);
    expect(screen.getByText("数据与说明")).toBeTruthy();
    expect(document.querySelector(".us-industry-leaders")).toBeNull();
    const collapsedDetails = [...document.querySelectorAll(".us-industry-explanation, .us-industry-group--pending")] as HTMLDetailsElement[];
    expect(collapsedDetails.every((details) => !details.open)).toBe(true);
    const explanation = openDisclosure("数据与说明");
    expect(explanation.textContent).toContain("官方板块质量");
    expect(explanation.textContent).toContain("PARTIAL");
    expect(screen.queryByText("Leader 1")).toBeNull();
  });

  it("shows PARTIAL quality when a previous-session snapshot has bound freshness metadata", async () => {
    const targetDate = "20260909";
    const sourceDate = "20260908";
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") {
        return response({ market_snapshot_dates: [targetDate] });
      }
      if (url === `/api/v3/research/us-market?research_date=${targetDate}`) {
        return response(snapshot(targetDate, {
          sourceDate,
          status: "PARTIAL",
          displayStatus: "PARTIAL",
          freshness: recentFreshness(sourceDate, "2026-09-09T04:30:00+08:00"),
        }));
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(GlobalIndustryMap, { props: { targetDate } });

    await screen.findByText("部分确认");
    expect(screen.getByText("部分确认")).toBeTruthy();
    expect(screen.queryByText(/目标阶段日 .* 读取快照日 .* 不一致/)).toBeNull();
    const sourceSummary = screen.getByLabelText("来源日期和板块覆盖");
    expect(sourceSummary.textContent).toContain("2026-09-08");
    expect(sourceSummary.textContent).toContain("12/24");
    expect(screen.getByText(/历史快照 · 旧主题口径/)).toBeTruthy();
    expect(screen.getByText(/待匹配主题 12/)).toBeTruthy();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
    expect(screen.queryByLabelText("平盘板块")).toBeNull();
    const pending = screen.getByLabelText("待匹配主题") as HTMLDetailsElement;
    expect(pending.open).toBe(false);
    const visibleRows = [...document.querySelectorAll("[data-theme-row]")] as HTMLDetailsElement[];
    expect(visibleRows.every((row) => !row.open)).toBe(true);
    const firstRowSummary = document.querySelector(".us-industry-group--up [data-theme-row] summary") as HTMLElement;
    expect(firstRowSummary.tagName).toBe("SUMMARY");
    expect(firstRowSummary.tabIndex).toBe(0);
    firstRowSummary.focus();
    expect(document.activeElement).toBe(firstRowSummary);
    firstRowSummary.click();
    expect((firstRowSummary.parentElement as HTMLDetailsElement).open).toBe(true);
    const visibleGroups = [...document.querySelectorAll("[data-theme-map] > [data-theme-group]")];
    expect(visibleGroups.map((group) => group.getAttribute("aria-label")))
      .toEqual(["上涨板块", "下跌板块", "待匹配主题"]);
    const changeValues = [...document.querySelectorAll(".us-industry-group--up [data-theme-row] summary b, .us-industry-group--down [data-theme-row] summary b")]
      .map((element) => element.textContent || "");
    expect(changeValues).toHaveLength(12);
    expect(changeValues.every((value) => /[+-]\d+\.\d{3}%$/.test(value))).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${targetDate}`,
      expect.objectContaining({ cache: "no-store" }),
    );
    pending.querySelector("summary")?.click();
    expect(pending.open).toBe(true);
    expect(screen.getAllByText("待匹配").length).toBeGreaterThan(0);
  });

  it("does not warn when the latest US snapshot is the prior calendar day to the stage target", async () => {
    const stageTargetDate = "20260910";
    const previousSnapshotDate = "20260909";
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") {
        return response({ market_snapshot_dates: [previousSnapshotDate] });
      }
      if (url === `/api/v3/research/us-market?research_date=${previousSnapshotDate}`) {
        return response(snapshot(previousSnapshotDate, {
          sourceDate: previousSnapshotDate,
          status: "PARTIAL",
          displayStatus: "PARTIAL",
          freshness: recentFreshness(previousSnapshotDate, "2026-09-10T04:30:00+08:00"),
        }));
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(GlobalIndustryMap, { props: { targetDate: stageTargetDate } });

    await screen.findByText("部分确认");
    expect(screen.queryByText(/目标阶段日 .* 读取快照日 .* 不一致/)).toBeNull();
    expect(screen.getByLabelText("来源日期和板块覆盖").textContent).toContain("2026-09-09");
  });

  it("uses the Futu board value and keeps the ETF proxy in a separate reference field", async () => {
    const date = "20260807";
    const freshness = recentFreshness(date, "2026-08-08T04:30:00+08:00");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url === "/api/v3/research/dates"
      ? { market_snapshot_dates: [date] }
      : snapshot(date, { displayStatus: "READY", freshness }))));

    render(GlobalIndustryMap, { props: { targetDate: date } });

    await screen.findByText("数据可读");
    expect(screen.getAllByText("+0.700%").length).toBeGreaterThan(0);
    const cloudSummary = [...document.querySelectorAll("[data-theme-row] summary")]
      .find((summary) => summary.textContent?.includes("云计算服务商")) as HTMLElement;
    expect(cloudSummary).toBeTruthy();
    cloudSummary.click();
    const cloudRow = cloudSummary.closest("details") as HTMLDetailsElement;
    const cloudDetail = cloudRow.querySelector(".us-industry-row-detail") as HTMLElement;
    expect(cloudRow.open).toBe(true);
    expect(cloudDetail.textContent).toContain("ETF 独立参考");
    expect(cloudDetail.textContent).toContain("ETF参考 +2.216% · CLOU");
    expect(cloudDetail.textContent).toContain("上涨 15 · 下跌 5 · 平盘 0");
    expect(cloudDetail.textContent).toContain("跨市场关系证据 · READY");
    expect(cloudDetail.textContent).toContain("NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER");
    expect(cloudDetail.querySelector('a[href="https://example.test/source"]')?.textContent)
      .toContain("Evidence（发布 2025-10-21）");
  });

  it("renders the frozen native board registry by official identity without inheriting old references", async () => {
    const date = "20261015";
    const native = withNativeBoardSnapshot(snapshot(date, {
      status: "PARTIAL",
      displayStatus: "PARTIAL",
      freshness: recentFreshness(date, "2026-10-16T04:30:00+08:00"),
    }) as any, date);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url === "/api/v3/research/dates"
      ? { market_snapshot_dates: [date] }
      : native)));

    render(GlobalIndustryMap, { props: { targetDate: date } });

    expect(await screen.findByText("数据可读")).toBeTruthy();
    expect(screen.getByLabelText("来源日期和板块覆盖").textContent).toContain("24/24");
    expect(screen.getByText(/Futu 原生板块口径/)).toBeTruthy();
    expect(screen.queryByText("AI算力")).toBeNull();
    expect(screen.queryByText("CPO")).toBeNull();
    expect(document.querySelectorAll("[data-native-board-row]")).toHaveLength(FUTU_US_NATIVE_BOARD_REGISTRY.length);
    expect(document.querySelector("[data-native-board-row='US.LIST2136']")).toBeTruthy();

    const aiRow = document.querySelector("[data-native-board-row='US.LIST2136']") as HTMLDetailsElement;
    aiRow.querySelector("summary")?.click();
    const detail = aiRow.querySelector(".us-industry-row-detail") as HTMLElement;
    expect(detail.textContent).toContain("人工智能");
    expect(aiRow.querySelector(".us-industry-board-type")?.textContent).toBe("概念");
    expect(detail.textContent).toContain("成员状态");
    expect(detail.textContent).toContain("CANNOT_CONFIRM");
    expect(detail.textContent).toContain("FUTU_BOARD_MEMBERSHIP_FAILED:-1");
    expect(detail.textContent).not.toContain("Tencent");
    expect(detail.textContent).not.toContain("跨市场关系证据");
    expect(screen.queryByText("ETF 独立参考")).toBeNull();
  });

  it("keeps partial native rows pending with their provider failure reason", async () => {
    const date = "20261015";
    const native = withNativeBoardSnapshot(snapshot(date, {
      status: "PARTIAL",
      displayStatus: "PARTIAL",
      freshness: recentFreshness(date, "2026-10-16T04:30:00+08:00"),
    }) as any, date, FUTU_US_NATIVE_BOARD_REGISTRY.length - 1);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url === "/api/v3/research/dates"
      ? { market_snapshot_dates: [date] }
      : native)));

    render(GlobalIndustryMap, { props: { targetDate: date } });

    expect(await screen.findByText("部分确认")).toBeTruthy();
    expect(screen.getByLabelText("数据未确认原生板块").textContent).toContain("数据未确认 1");
    const pendingRow = document.querySelector("[data-native-board-row='US.LIST2003']") as HTMLDetailsElement;
    expect(pendingRow).toBeTruthy();
    pendingRow.querySelector("summary")?.click();
    expect(pendingRow.textContent).toContain("FUTU_BOARD_SNAPSHOT_NOT_RETURNED");
    expect(document.querySelectorAll("[data-native-board-row]")).toHaveLength(FUTU_US_NATIVE_BOARD_REGISTRY.length);
  });

  it("fails closed when a native row code diverges from the frozen registry", async () => {
    const date = "20261015";
    const native = withNativeBoardSnapshot(snapshot(date) as any, date);
    native.native_board_snapshot.rows[0].board_code = "US.LIST9999";
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url === "/api/v3/research/dates"
      ? { market_snapshot_dates: [date] }
      : native)));

    render(GlobalIndustryMap, { props: { targetDate: date } });

    expect(await screen.findByText("Futu 原生板块身份或去重校验失败，已停止展示。"))
      .toBeTruthy();
    expect(document.querySelectorAll("[data-native-board-row]")).toHaveLength(0);
  });

  it("shows a same-date Friday close with explicit recent-capture metadata", async () => {
    const date = "20260807";
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") return response({ market_snapshot_dates: [date] });
      if (url === `/api/v3/research/us-market?research_date=${date}`) {
        return response(snapshot(date, {
          displayStatus: "READY",
          freshness: recentFreshness(date, "2026-08-08T04:30:00+08:00"),
        }));
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(GlobalIndustryMap, { props: { targetDate: date } });

    expect(await screen.findByText("数据可读")).toBeTruthy();
    const explanation = openDisclosure("数据与说明");
    expect(explanation.textContent).toContain("2026-08-07");
    expect(explanation.textContent).toContain("来源场次与原采集时间通过近期时钟核验");
    expect(explanation.textContent).toContain("交易日核验");
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${date}`,
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("fails closed for READY snapshots without freshness metadata while preserving quality", async () => {
    const date = "20260807";
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") return response({ market_snapshot_dates: [date] });
      if (url === `/api/v3/research/us-market?research_date=${date}`) return response(snapshot(date));
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(GlobalIndustryMap, { props: { targetDate: date } });

    expect((await screen.findAllByText("暂无法确认")).length).toBeGreaterThan(0);
    const explanation = openDisclosure("数据与说明");
    expect(explanation.textContent).toContain("2026-08-07");
    expect(explanation.textContent).toContain("无法确认当前新鲜度；历史快照质量不等于当前数据已更新");
    expect(screen.queryByText("近期时钟匹配")).toBeNull();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${date}`,
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("uses the newest materialized market snapshot when the stage target is historical", async () => {
    const stageTargetDate = "20260901";
    const latestSnapshotDate = "20260909";
    const sourceDate = "20260908";
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") {
        return response({
          market_snapshot_dates: ["20260905", latestSnapshotDate, "20260901"],
          research_dates: [stageTargetDate],
        });
      }
      if (url === `/api/v3/research/us-market?research_date=${latestSnapshotDate}`) {
        return response(snapshot(latestSnapshotDate, {
          sourceDate,
          displayStatus: "READY",
          freshness: recentFreshness(sourceDate, "2026-09-09T04:30:00+08:00"),
        }));
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(GlobalIndustryMap, { props: { targetDate: stageTargetDate } });

    await screen.findByText("数据可读");
    expect(await screen.findByText("数据可读")).toBeTruthy();
    expect(screen.getByText("目标阶段日 2026-09-01 与读取快照日 2026-09-09 不一致，请核对日期身份。"))
      .toBeTruthy();
    expect((document.querySelector(".us-industry-explanation") as HTMLDetailsElement).open)
      .toBe(false);
    const explanation = openDisclosure("数据与说明");
    expect(explanation.textContent).toContain("2026-09-01");
    expect(explanation.textContent).toContain("2026-09-09");
    expect(explanation.textContent).toContain("2026-09-08 16:00:00");
    expect(explanation.textContent).toContain("来源场次与原采集时间通过近期时钟核验");
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${latestSnapshotDate}`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${stageTargetDate}`,
      expect.anything(),
    );
  });

  it("retains a 24-row cannot-confirm surface when no exact snapshot date exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ research_dates: [] })));

    render(GlobalIndustryMap, { props: { targetDate: "20260809" } });

    expect(await screen.findByText("没有可用的最新美股市场快照日期。")).toBeTruthy();
    const pending = screen.getByLabelText("待匹配主题") as HTMLDetailsElement;
    expect(pending.open).toBe(false);
    openDisclosure("数据与说明");
    pending.querySelector("summary")?.click();
    const firstPendingRow = pending.querySelector("[data-theme-row]") as HTMLDetailsElement;
    firstPendingRow.querySelector("summary")?.click();
    expect(firstPendingRow.open).toBe(true);
    expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
  });

  it.each(["label", "symbol", "version"])(
    "fails closed for tampered canonical %s data",
    async (field) => {
      const tampered = snapshot("20260808") as any;
      if (field === "label") tampered.rows[0].label = "篡改主题";
      if (field === "symbol") tampered.rows[0].proxy_symbols[0] = "FAKE";
      if (field === "version") tampered.mapping_version = "v3_5.tampered";
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        if (url === "/api/v3/research/dates") {
          return response({ market_snapshot_dates: ["20260808"] });
        }
        if (url === "/api/v3/research/us-market?research_date=20260808") return response(tampered);
        throw new Error(`unexpected URL: ${url}`);
      }));

      render(GlobalIndustryMap, { props: { targetDate: "20260808" } });

      expect(await screen.findByText(/已停止展示。/)).toBeTruthy();
      const pending = screen.getByLabelText("待匹配主题") as HTMLDetailsElement;
      pending.querySelector("summary")?.click();
      const firstPendingRow = pending.querySelector("[data-theme-row]") as HTMLDetailsElement;
      firstPendingRow.querySelector("summary")?.click();
      expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
      expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
      openDisclosure("数据与说明");
      expect(screen.queryByText(/ETF \/ 股票篮子另列为参考/)).toBeNull();
    },
  );

  it("fails closed for unsafe API flags without rendering the static safety note", async () => {
    const tampered = snapshot("20260808") as any;
    tampered.production_allowed = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") {
        return response({ market_snapshot_dates: ["20260808"] });
      }
      if (url === "/api/v3/research/us-market?research_date=20260808") return response(tampered);
      throw new Error(`unexpected URL: ${url}`);
    }));

    render(GlobalIndustryMap, { props: { targetDate: "20260808" } });

    expect(await screen.findByText("美股行情研究安全边界未通过，已停止展示。"))
      .toBeTruthy();
    const pending = screen.getByLabelText("待匹配主题") as HTMLDetailsElement;
    pending.querySelector("summary")?.click();
    const firstPendingRow = pending.querySelector("[data-theme-row]") as HTMLDetailsElement;
    firstPendingRow.querySelector("summary")?.click();
    expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    openDisclosure("数据与说明");
    expect(screen.queryByText(/ETF \/ 股票篮子另列为参考/)).toBeNull();
  });

  it.each([
    ["older", "20260907", ["20260907"]],
    ["future", "20260910", ["20260910"]],
    ["empty", "", []],
    ["mixed", "20260908", ["20260908", "20260909"]],
  ])("fails closed for %s source session identity", async (_case, sourceDate, providerSessionDates) => {
    const targetDate = "20260909";
    const tampered = snapshot(targetDate, {
      sourceDate,
      providerSessionDates,
    }) as any;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v3/research/dates") return response({ market_snapshot_dates: [targetDate] });
      if (url === `/api/v3/research/us-market?research_date=${targetDate}`) return response(tampered);
      throw new Error(`unexpected URL: ${url}`);
    }));

    render(GlobalIndustryMap, { props: { targetDate } });

    expect(await screen.findByText("美股行情来源日期必须唯一且为目标日或前一自然日，已停止展示。"))
      .toBeTruthy();
    expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
  });
});
