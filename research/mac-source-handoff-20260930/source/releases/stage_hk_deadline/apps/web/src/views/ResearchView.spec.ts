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

  it("sorts 全部 by fetched time and keeps missing-time evidence explicit", async () => {
    const timedLane = {
      ...lane(),
      morning_news: {
        status: "GENERATED_SNAPSHOT",
        articles: [
          {
            article_id: "old",
            title: "较早来源",
            fetched_at: "2026-08-04T09:00:00+08:00",
            published_at: "2026-08-04T08:45:00+08:00",
          },
          {
            article_id: "new",
            title: "较新来源",
            collected_at: "2026-08-04T11:00:00+08:00",
            published_at: "2026-08-04T10:55:00+08:00",
          },
          {
            article_id: "fallback",
            title: "首字段无效但可回退来源",
            fetched_at: "not-a-timestamp",
            collected_at: "2026-08-04T10:00:00+08:00",
          },
          {
            article_id: "space-offset",
            title: "空格偏移来源",
            fetched_at: "2026-08-04 09:30:00 +08:00",
          },
          {
            article_id: "naive",
            title: "无时区来源",
            fetched_at: "2026-08-04T09:00:00",
            published_at: "2026-08-04 06:56:40",
          },
          { article_id: "unknown", title: "时间缺失来源" },
          { article_id: "invalid", title: "无效时间来源", fetched_at: "not-a-timestamp" },
        ],
      },
      news_workbench: { schema_version: "x", status: "ok", action_rows: [] },
      zsxq_hourly: { schema_version: "x", status: "ok", topic_count: 0, items: [] },
      ai_news: { item_count: 0, items: [] },
      external_finance: { raw_item_count: 0, overview: [] },
      key_investment_messages: [],
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(timedLane)));

    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    expect((await screen.findAllByText("较新来源")).length).toBeGreaterThan(0);
    const feedList = container.querySelector<HTMLElement>(".hourly-feed-list");
    expect(feedList).toBeTruthy();
    if (!feedList) throw new Error("missing main feed list");
    const cards = Array.from(feedList.children).filter((node) => node.classList.contains("hourly-feed-card"));
    expect(cards.map((card) => card.querySelector(".hourly-feed-title")?.textContent)).toEqual([
      "较新来源",
      "首字段无效但可回退来源",
      "空格偏移来源",
      "较早来源",
      "无效时间来源",
      "无时区来源",
      "时间缺失来源",
    ]);
    expect(cards[0].textContent).toContain("获取时间：2026-08-04 11:00:00+08:00（回退自采集时间；实际抓取时间 CANNOT_CONFIRM）");
    expect(cards[1].textContent).toContain("获取时间：2026-08-04 10:00:00+08:00（回退自采集时间；实际抓取时间 CANNOT_CONFIRM）");
    expect(cards[2].textContent).toContain("获取时间：2026-08-04 09:30:00 +08:00");
    expect(cards[4].textContent).toContain("获取时间：CANNOT_CONFIRM");
    expect(cards[5].textContent).toContain("获取时间：CANNOT_CONFIRM");
    expect(cards[5].textContent).toContain("原文时间：CANNOT_CONFIRM");
    expect(cards[6].textContent).toContain("获取时间：CANNOT_CONFIRM");
    expect(cards[4].textContent).not.toContain("not-a-timestamp");
    expect(cards[5].textContent).not.toContain("2026-08-04T09:00:00");
    expect(cards[6].textContent).not.toContain("2026-08-04T09:00:00");
  });

  it("shows exactly the three exact-date morning articles in the early tab", async () => {
    const morningArticles = [
      { title: "8月27日盘前纪要", url: "https://news.example/morning-brief", source: "韭研公社" },
      { title: "8月27日盘前解读", url: "https://news.example/morning-read", source: "韭研公社" },
      { title: "8月27日开盘必读资讯", url: "https://news.example/morning-open", source: "韭研公社" },
    ];
    const morningLane = {
      ...lane("20260827"),
      morning_news: { status: "GENERATED_SNAPSHOT", articles: morningArticles },
      news_workbench: { schema_version: "x", status: "ok", action_rows: [{ title: "工作台行动行", kind: "article" }] },
      zsxq_hourly: { schema_version: "x", status: "ok", topic_count: 20, items: [{ title: "星球话题", kind: "article" }] },
      ai_news: { item_count: 31, items: [{ title: "AI新闻条目", kind: "article" }] },
      external_finance: { raw_item_count: 5, overview: [{ title: "财经头条", kind: "article" }] },
      key_investment_messages: [{ evidence_text: "重点消息", kind: "article" }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(morningLane)));

    const { container } = render(ResearchView, { props: { archiveDate: "20260827" } });
    await screen.findByText("情报阅读");
    await fireEvent.click(screen.getByRole("button", { name: "早盘" }));

    const feedList = container.querySelector<HTMLElement>(".hourly-feed-list");
    expect(feedList).toBeTruthy();
    if (!feedList) throw new Error("missing main feed list");
    const cards = Array.from(feedList.children).filter((node) => node.classList.contains("hourly-feed-card"));
    expect(cards).toHaveLength(3);
    for (const article of morningArticles) {
      expect(within(feedList).getByText(article.title)).toBeTruthy();
    }
    expect(within(feedList).queryByText("星球话题")).toBeNull();
    expect(within(feedList).queryByText("财经头条")).toBeNull();
    expect(within(feedList).queryByText("AI新闻条目")).toBeNull();
    expect(Array.from(feedList.querySelectorAll<HTMLAnchorElement>("a")).map((link) => link.href)).toEqual(
      morningArticles.map((article) => article.url),
    );
  });

  it("ends loading and shows a typed exact-date placeholder", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      ...lane("20260217"), status: "NOT_MATERIALIZED", reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
    })));

    render(ResearchView, { props: { archiveDate: "20260217" } });

    expect(await screen.findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(screen.getByText("RESEARCH_LANE_SNAPSHOT_NOT_FOUND")).toBeTruthy();
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

  it("only renders safe finance original links and falls back past a dangerous primary URL", async () => {
    const financeLane = lane() as unknown as Record<string, unknown>;
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
    } as Record<string, unknown>;
    vi.stubGlobal("fetch", vi.fn(async () => response(financeLane)));

    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });

    await screen.findAllByText("安全回退");
    const links = Array.from(container.querySelectorAll<HTMLAnchorElement>("a")).map((link) => link.href);
    expect(links).toContain("https://finance.example/fallback");
    expect(links.some((href) => href.includes("generic-must-not-be-used"))).toBe(false);
    expect(links.some((href) => /^(javascript|data|file):/i.test(href))).toBe(false);
    expect(links.some((href) => href.includes("user:pass@"))).toBe(false);
  });
});

describe("0915 research identity boundary", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it("labels latest's real source date without replacing the selected date", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.includes("research_date")
      ? {...lane("20260915"), status:"NOT_MATERIALIZED", reason:"RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
         update_diagnostic: {state:"NOT_DUE", message:"尚未到07:00首个研究时点"}}
      : {...lane("20260914"), endpoint_mode:"LATEST"})));
    const {rerender} = render(ResearchView, {props:{archiveDate:"20260915"}});
    expect(await screen.findByText("RESEARCH_LANE_SNAPSHOT_NOT_FOUND")).toBeTruthy();
    expect(screen.getByText("尚未到07:00首个研究时点")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", {name:"查看 latest"}));
    await waitFor(() => expect(screen.getByTestId("research-date-identity").textContent).toContain("20260914"));
    const banner = screen.getByTestId("research-date-identity").textContent;
    expect(banner).toContain("20260915"); expect(banner).toContain("不是所选日期数据");
    await rerender({archiveDate:"20260911"});
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenLastCalledWith("/api/v3/research/lane?research_date=20260911"));
  });
});
