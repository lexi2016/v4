import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import GlobalIndustryMap from "./GlobalIndustryMap.vue";
import {
  GLOBAL_INDUSTRY_MAPPINGS,
  GLOBAL_INDUSTRY_MAPPING_VERSION,
} from "../../contracts/globalIndustries";

const response = (payload: unknown) => ({ ok: true, json: async () => payload });

type FreshnessFixture = {
  state: "RECENT_BOUND_CAPTURE" | "STALE_CLOCK_WINDOW" | "CANNOT_CONFIRM";
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
  const status = options.status ?? "READY";
  const providerSessionDates = options.providerSessionDates ?? [sourceDate];
  const capturedDate = sourceDate || date;
  return {
    schema_version: "v3_5.global_industries.v1",
    status,
    ...(options.displayStatus ? { display_status: options.displayStatus } : {}),
    ...(options.freshness ? { freshness: options.freshness } : {}),
    target_date: date,
    research_date: date,
    source_date: sourceDate,
    provider: "Tencent qt.gtimg.cn",
    provider_session_dates: providerSessionDates,
    provider_session_times: ["16:18:00-04:00"],
    capture_phase: "POST_CLOSE",
    captured_at: `${capturedDate.slice(0, 4)}-${capturedDate.slice(4, 6)}-${capturedDate.slice(6)}T20:18:00Z`,
    generated_at: `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}T20:18:01Z`,
    mapping_version: GLOBAL_INDUSTRY_MAPPING_VERSION,
    requested_symbol_count: 33,
    available_symbol_count: 33,
    rows: GLOBAL_INDUSTRY_MAPPINGS.map((mapping, index) => ({
      ...mapping,
      proxy_symbols: [...mapping.proxy_symbols],
      available_symbols: [...mapping.proxy_symbols],
      missing_symbols: [],
      requested_symbol_count: mapping.proxy_symbols.length,
      available_symbol_count: mapping.proxy_symbols.length,
      coverage: { available: mapping.proxy_symbols.length, requested: mapping.proxy_symbols.length },
      coverage_pct: 100,
      change_pct: Number(((index - 8) / 10).toFixed(3)),
      direction: index < 8 ? "UP" : index < 16 ? "FLAT" : "DOWN",
      status,
      quote_session_dates: [sourceDate],
      quote_session_times: ["16:18:00-04:00"],
      cannot_confirm: [],
    })),
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

describe("GlobalIndustryMap", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
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

    expect(await screen.findByText("AI算力")).toBeTruthy();
    expect(screen.getByText("目标阶段日：2026-09-09")).toBeTruthy();
    expect(screen.getByText("读取快照日：2026-09-09")).toBeTruthy();
    expect(screen.getByText("美股来源日：2026-09-08")).toBeTruthy();
    expect(screen.getByText("PARTIAL · 质量缺口")).toBeTruthy();
    expect(screen.getByText(/快照质量：PARTIAL · 来源场次与原采集时间通过近期时钟核验/)).toBeTruthy();
    expect(screen.getByText(/交易所节假日／提前收盘及最新完整交易日：CANNOT_CONFIRM/)).toBeTruthy();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(16);
    expect(screen.queryByLabelText("平盘板块")).toBeNull();
    expect(screen.queryByLabelText("待确认板块")).toBeNull();
    const visibleGroups = [...document.querySelectorAll("[data-theme-map] > .global-industry-group")];
    expect(visibleGroups.map((group) => group.getAttribute("aria-label")))
      .toEqual(["上涨板块", "下跌板块"]);
    expect(visibleGroups.every((group) => !group.classList.contains("global-group-wide"))).toBe(true);
    const changeValues = [...document.querySelectorAll("[data-theme-row] b")]
      .map((element) => element.textContent || "");
    expect(changeValues).toHaveLength(16);
    expect(changeValues.every((value) => /[+-]\d+\.\d{3}%$/.test(value))).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v3/research/us-market?research_date=${targetDate}`,
      expect.objectContaining({ cache: "no-store" }),
    );
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

    expect(await screen.findByText("近期时钟匹配")).toBeTruthy();
    expect(screen.getByText("目标阶段日：2026-08-07")).toBeTruthy();
    expect(screen.getByText("读取快照日：2026-08-07")).toBeTruthy();
    expect(screen.getByText("美股来源日：2026-08-07")).toBeTruthy();
    expect(screen.getByText(/快照质量：READY · 来源场次与原采集时间通过近期时钟核验/)).toBeTruthy();
    expect(screen.getByText(/交易所节假日／提前收盘及最新完整交易日：CANNOT_CONFIRM/)).toBeTruthy();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(16);
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

    expect(await screen.findByText("CANNOT_CONFIRM")).toBeTruthy();
    expect(screen.getByText("读取快照日：2026-08-07")).toBeTruthy();
    expect(screen.getByText(/快照质量：READY · 无法确认当前新鲜度；历史快照质量不等于当前数据已更新/)).toBeTruthy();
    expect(screen.queryByText("近期时钟匹配")).toBeNull();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(16);
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

    expect(await screen.findByText("AI算力")).toBeTruthy();
    expect(screen.getByText("目标阶段日：2026-09-01")).toBeTruthy();
    expect(screen.getByText("读取快照日：2026-09-09")).toBeTruthy();
    expect(screen.getByText("美股来源日：2026-09-08")).toBeTruthy();
    expect(screen.getByText("US session：20260908")).toBeTruthy();
    expect(await screen.findByText("近期时钟匹配")).toBeTruthy();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(16);
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
      expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
      expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
      expect(screen.queryByText(/代理 ETF \/ 股票篮子仅用于研究观察/)).toBeNull();
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
    expect(screen.getAllByText("CANNOT_CONFIRM").length).toBeGreaterThan(0);
    expect(screen.queryByText(/代理 ETF \/ 股票篮子仅用于研究观察/)).toBeNull();
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
