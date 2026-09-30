import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import ResearchView from "./ResearchView.vue";

const lane = (researchDate = "20260804") => ({
  schema_version: "v3_5.research_lane.v1",
  status: "READY",
  endpoint_mode: "EXACT",
  research_date: researchDate,
  write_policy: "read_only",
  recommendation_status: "RESEARCH_ONLY",
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  research_quality_summary: { raw_item_count: 3, research_item_count: 2, stock_evidence_count: 1, stock_daily_count: 1, l2_medium_count: 1 },
  stock_research_daily: [
    { stock_code: "600970", stock_name: "中材国际", research_score: 100, evidence_count: 2, evidence_level: "L2_MEDIUM", themes: ["一带一路"] },
  ],
  stock_research_timeline: [
    { evidence_id: "e1", stock_code: "600970", stock_name: "中材国际", event_time: "2026-08-04T09:02:39", evidence_level: "L2_MEDIUM", evidence_sentence: "中材国际中标海外项目" },
  ],
  morning_news: { status: "GENERATED_SNAPSHOT", articles: [{ title: "早盘要闻", stock_name: "中材国际", stock_code: "600970", summary: "早盘摘要" }] },
  news_workbench: { schema_version: "x", status: "ok", action_rows: [{ stock_code: "600970", title: "工作台行动行" }] },
  zsxq_hourly: { schema_version: "x", status: "ok", topic_count: 20, items: [{ title: "星球话题" }] },
  ai_news: { item_count: 31, items: [{ title: "AI新闻条目", stock_code: "600970" }] },
  external_finance: { raw_item_count: 5, overview: [{ title: "财经头条" }] },
  key_investment_messages: [{ stock_code: "600970", evidence_text: "重点消息" }],
  cannot_confirm: ["LEGACY_NAIVE_TIMESTAMP_ASSUMED_ASIA_SHANGHAI"],
});

const response = (payload: unknown) => ({ ok: true, json: async () => payload });

describe("ResearchView (research lane)", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads only the selected exact research date", async () => {
    const fetchMock = vi.fn(async () => response(lane()));
    vi.stubGlobal("fetch", fetchMock);

    render(ResearchView, { props: { archiveDate: "20260804" } });

    expect((await screen.findAllByText("中材国际")).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260804");
    expect(screen.getByText(/股票研报/)).toBeTruthy();
    expect(screen.getByText("LEGACY_NAIVE_TIMESTAMP_ASSUMED_ASIA_SHANGHAI")).toBeTruthy();
  });

  it("rejects an exact research response whose date evidence is wrong", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(lane("20260803"))));

    render(ResearchView, { props: { archiveDate: "20260804" } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByText("中材国际")).toBeNull();
  });

  it("rejects an exact research response with missing date evidence", async () => {
    const missingDate = { ...lane() } as Record<string, unknown>;
    delete missingDate.research_date;
    vi.stubGlobal("fetch", vi.fn(async () => response(missingDate)));

    render(ResearchView, { props: { archiveDate: "20260804" } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByText("中材国际")).toBeNull();
  });

  it("renders the three-column desk and status strip", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(lane())));
    render(ResearchView, { props: { archiveDate: "20260804" } });

    expect((await screen.findAllByText("股票层")).length).toBeGreaterThan(0);
    expect(screen.getByText("情报阅读")).toBeTruthy();
    expect(screen.getByText("来源状态")).toBeTruthy();
    expect((await screen.findAllByText("知识星球")).length).toBeGreaterThan(0);
  });

  it("uses latest only after an explicit click", async () => {
    const latest = { ...lane("20260804"), endpoint_mode: "LATEST" };
    const fetchMock = vi.fn(async (url: string) => response(url.includes("research_date") ? lane() : latest));
    vi.stubGlobal("fetch", fetchMock);
    render(ResearchView, { props: { archiveDate: "20260804" } });
    expect((await screen.findAllByText("中材国际")).length).toBeGreaterThan(0);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByRole("button", { name: "查看 latest" }));
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith("/api/v3/research/lane"));
  });

  it("filters feed cards via the tabs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(lane())));
    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");

    await fireEvent.click(screen.getByRole("button", { name: "星球" }));
    expect((await screen.findAllByText("星球话题")).length).toBeGreaterThan(0);
  });

  it("uses the verified Chinese finance fields, retains the English title, and never falls back to url", async () => {
    const details = Array.from({ length: 7 }, (_, index) => ({
      source: "external_finance",
      title: index === 0 ? "English original title" : `English detail ${index}`,
      title_zh: index === 0 ? "已有中文标题" : `已有中文标题 ${index}`,
      summary: index === 0 ? "English original summary" : `English detail summary ${index}`,
      summary_zh: index === 0 ? "已有中文摘要" : `已有中文摘要 ${index}`,
      translation_status: "READY",
      original_url: index === 0 ? "https://publisher.example/original" : `https://publisher.example/${index}`,
      source_url: index === 0 ? "https://publisher.example/source" : `https://publisher.example/source-${index}`,
      url: `https://legacy.example/wrong-${index}`,
    }));
    const localized = {
      ...lane(),
      external_finance: {
        raw_item_count: details.length,
        overview: [{
          source: "external_finance", title: "旧概览不应替代详情", summary: "旧概览摘要",
        }],
        details,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(localized)));

    render(ResearchView, { props: { archiveDate: "20260804" } });

    await screen.findByText("情报阅读");
    await fireEvent.click(screen.getByRole("button", { name: "财经" }));
    expect((await screen.findAllByText("已有中文标题")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("已有中文摘要")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/English original title/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("旧概览不应替代详情")).toBeNull();
    expect(screen.getByText(`${details.length} 原始 · ${details.length} 已验证`)).toBeTruthy();
    const links = await screen.findAllByRole("link", { name: "打开原文" });
    expect(links.length).toBeGreaterThanOrEqual(details.length);
    expect(links.some((link) => link.getAttribute("href") === "https://publisher.example/original")).toBe(true);
    expect(links.every((link) => link.getAttribute("href")?.startsWith("https://publisher.example/"))).toBe(true);
    expect(links.some((link) => link.getAttribute("href") === "https://publisher.example/source")).toBe(false);
    expect(links.some((link) => link.getAttribute("href")?.includes("legacy.example"))).toBe(false);

    const financeColumn = Array.from(document.querySelectorAll<HTMLElement>(".hourly-source-column"))
      .find((column) => within(column).queryByRole("heading", { name: "外部财经" }));
    expect(financeColumn).toBeTruthy();
    expect(financeColumn?.querySelectorAll(".hourly-feed-card.source")).toHaveLength(details.length);
  });

  it("sanitizes each finance URL and fails closed without a generic url fallback", async () => {
    const financeLane = structuredClone(lane()) as Record<string, unknown>;
    financeLane.external_finance = {
      overview: [
        {
          title: "安全回退",
          original_url: "javascript:alert(1)",
          source_url: "https://finance.example/fallback",
          url: "https://finance.example/generic-must-not-be-used",
        },
        {
          title: "危险全部拒绝",
          original_url: "data:text/html,blocked",
          source_url: "file:///tmp/blocked",
          url: "https://finance.example/generic-must-not-be-used-either",
        },
        {
          title: "凭证拒绝",
          original_url: "https://user:pass@finance.example/private",
          source_url: "/relative",
          url: "https://finance.example/generic-must-not-be-used-last",
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(financeLane)));

    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("安全回退");

    const hrefs = Array.from(container.querySelectorAll<HTMLAnchorElement>("a")).map((link) => link.href);
    expect(hrefs.some((href) => href === "https://finance.example/fallback")).toBe(true);
    expect(hrefs.some((href) => href.startsWith("javascript:"))).toBe(false);
    expect(hrefs.some((href) => href.startsWith("data:"))).toBe(false);
    expect(hrefs.some((href) => href.startsWith("file:"))).toBe(false);
    expect(hrefs.some((href) => href.includes("user:pass@"))).toBe(false);
    expect(hrefs.some((href) => href.includes("generic-must-not-be-used"))).toBe(false);
  });

  it("does not present a stock code as a missing stock name", async () => {
    const missingName = {
      ...lane(),
      stock_research_daily: [{ stock_code: "600970", research_score: 100, evidence_count: 1 }],
      stock_research_timeline: [{ stock_code: "600970", event_time: "2026-08-04T09:02:39", evidence_sentence: "证据" }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(missingName)));

    render(ResearchView, { props: { archiveDate: "20260804" } });

    expect((await screen.findAllByText("股票名称不可确认")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^600970$/)).toBeNull();
  });

  it("ends loading and shows a typed exact-date placeholder", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      ...lane("20260217"), status: "NOT_MATERIALIZED", reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
    })));

    render(ResearchView, { props: { archiveDate: "20260217" } });

    expect(await screen.findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(screen.getByText("RESEARCH_LANE_SNAPSHOT_NOT_FOUND")).toBeTruthy();
  });
});
