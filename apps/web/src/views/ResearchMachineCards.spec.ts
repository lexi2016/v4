import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import ResearchView from "./ResearchView.vue";
import { feedFetchTimeLabel, feedPublishedTimeLabel } from "../composables/useResearchLane";

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

const response = (payload: unknown) => ({
  ok: true,
  headers: { get: () => "application/json" },
  json: async () => payload,
});
const wechatListing = () => ({
  RESEARCH_ONLY: true,
  WATCH_ONLY: true,
  NO_BUY_GATE: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  schema_version: "v4.wechat_materials.stage_a.v1",
  status: "NOT_CONFIGURED",
  query: { date: "20260804", date_basis: "article", q: "", limit: 20 },
  timezone: "Asia/Shanghai",
  items: [],
  total: 0,
  returned: 0,
  next_cursor: null,
  index_revision: null,
});
const wechatMaterial = () => ({
  RESEARCH_ONLY: true,
  WATCH_ONLY: true,
  NO_BUY_GATE: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  record_id: "c".repeat(64),
  article: {
    article_id: null, title: "公众号归档报告", account: null, biz: null, url: null,
    article_date: "20260804", published_at: null, metadata_origin: "IMPORT_RECEIPT",
  },
  identity: {
    package_id: "legacy-report-only", source_run_id: "run-1", input_digest: null,
    return_id: null, receipt_sha256: "a".repeat(64), package_sha256: "b".repeat(64),
    package_sha256_status: "VERIFIED", manifest_sha256: null,
  },
  states: {
    archive: "REPORT_ONLY_ARCHIVED", input_binding: "VERIFIED_LEGACY_URL_DATE_AND_SHA_ONLY",
    structure: "MISSING", research_review: "NOT_EVALUATED_STAGE_A",
  },
  receipt_claims: {
    archive: "REPORT_ONLY_ARCHIVED", structure: "MISSING", input_binding_valid: false,
    semantic_research_accepted: false, independent_review_scope: [],
  },
  received_at: "2026-08-04T16:20:03+08:00", indexed_at: "2026-08-04T16:21:00+08:00",
  available_at: null, missing_artifacts: ["coverage.csv", "mentions.csv", "unmapped.csv", "summary.json"],
  cannot_confirm: ["STRUCTURED_ARTIFACTS_MISSING"], source_status: "NOT_REGISTERED",
  origin: "USER_PROVIDED_CHAT_RETURN", archive_owner: "WECHAT_LOCAL_ARCHIVE", write_policy: "READ_ONLY",
});
const wechatReadyListing = () => ({
  ...wechatListing(), status: "READY", query: { date: "20260804", date_basis: "article", q: "", limit: 20 },
  items: [wechatMaterial()], total: 1, returned: 1,
});
const wechatDetail = () => ({
  ...wechatListing(), status: "READY", material: wechatMaterial(),
  report: { status: "READABLE", content: "# 公众号归档全文\n\n仅供研究阅读。" },
  artifacts: [{ artifact_id: "report", filename: "report.md", sha256: "d".repeat(64), bytes: 32, kind: "CHAT_RETURN", status: "HASH_MATCH" }],
});
const machineCards = (researchDate = "20260804", items: unknown[] = [], duplicateCount = 0) => ({
  schema_version: "v4.pdf_research.machine_cards.v1",
  status: items.length ? "READY" : "READY_EMPTY",
  research_date: researchDate,
  card_count: items.length,
  matched_count: items.length,
  duplicate_count: duplicateCount,
  cannot_confirm_count: 0,
  cannot_confirm: [],
  cannot_confirm_document_ids: [],
  unresolved_document_ids: [],
  truncated: false,
  max_cards_per_date: 200,
  preview_max_chars: 4000,
  source_index_used: false,
  items,
  research_only: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});
const machineCard = () => ({
  document_id: "a".repeat(64),
  research_date: "20260804",
  status: "SUCCEEDED",
  batch_id: "batch-001",
  superseded_batch_ids: [],
  title: "机器研报标题",
  title_source: "PDF_FILENAME_STEM",
  source: {
    source_group_name: null,
    source_group_status: "CANNOT_CONFIRM_INGESTION_INDEX_NOT_LINKED",
    original_filename: "机器研报标题.pdf",
    source_directory: "示例群",
    source_relative_path: "知识星球/2026年8月4日/机器研报标题.pdf",
    source_pdf_path: "/外置/知识星球/2026年8月4日/机器研报标题.pdf",
  },
  review: {
    origin_status: "MODEL_GENERATED",
    source_review_status: "SOURCE_REVIEW_PENDING",
    user_acceptance_status: "NOT_ACCEPTED",
    review_status: "NOT_REVIEWED",
    human_reviewed: false,
    user_accepted: false,
  },
  report: {
    path: `batches/batch-001/documents/${"a".repeat(64)}/report.md`,
    receipt_path: `batches/batch-001/documents/${"a".repeat(64)}/receipt.json`,
    sha256: "b".repeat(64),
    bytes: 123,
    preview: "机器生成正文预览，仅供研究。",
    preview_max_chars: 4000,
  },
  machine_generated: true,
  read_only: true,
  research_only: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
});
const machineCardsForUrl = (url: string, items: unknown[] = [], duplicateCount = 0) => {
  const researchDate = /research_date=(\d{8})/.exec(url)?.[1] ?? "20260804";
  return machineCards(researchDate, items, duplicateCount);
};
const stockClues = (
  researchDate = "20260804",
  items: unknown[] = [],
  genericFiltered: unknown[] = [],
  weakItems: unknown[] = [],
) => {
  const confirmed = items.length;
  return {
    schema_version: "v4.research.stock_clues.v1",
    status: confirmed ? "READY" : "READY_EMPTY",
    research_date: researchDate,
    card_count: items.length + weakItems.length,
    scanned_card_count: items.length + weakItems.length,
    skipped_card_count: 0,
    stock_count: items.length + weakItems.length,
    confirmed_stock_count: confirmed,
    weak_only_stock_count: weakItems.length,
    corpus_report_count: 101,
    corpus_fingerprint: "c".repeat(64),
    corpus_cutoff_date: researchDate,
    corpus_version: "v4.research.stock_clues.link_corpus.v2",
    corpus_cache_status: "HIT",
    generic_filtered: genericFiltered,
    weak_items: weakItems,
    clue_limit: 50,
    name_map_status: "READY",
    name_map_path: "/tmp/selector_ready.parquet",
    name_map_trade_date: "20261023",
    truncated_report_count: 0,
    cannot_confirm: [],
    items,
    research_only: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
};
const stockClue = () => ({
  ts_code: "600001.SH",
  name: "测试股份",
  document_count: 3,
  weak_document_count: 0,
  link_probability: 0.875,
  confirm_reasons: ["CODE", "CONTEXT"],
  document_titles: ["报告一", "<b>报告二</b>", "报告三", "报告四"],
  matched_by: "BOTH",
  first_seen_date: "20260804",
  last_seen_date: "20260804",
});
const stockCluesForUrl = (
  url: string,
  items: unknown[] = [],
  genericFiltered: unknown[] = [],
  weakItems: unknown[] = [],
) => {
  const researchDate = /research_date=(\d{8})/.exec(url)?.[1] ?? "20260804";
  return stockClues(researchDate, items, genericFiltered, weakItems);
};
const stubResearchFetch = (
  payload: unknown,
  machineItems: unknown[] = [],
  stockClueItems: unknown[] = [],
  duplicateCount = 0,
) => vi.stubGlobal("fetch", vi.fn(async (url: string) => response(
  url.includes("/api/v4/research/machine-cards")
    ? machineCardsForUrl(url, machineItems, duplicateCount)
    : url.includes("/api/v4/research/stock-clues")
      ? stockCluesForUrl(url, stockClueItems)
      : url.includes("/api/v4/research/wechat/materials") ? wechatListing() : payload,
)));

const highVolumeFilterLane = () => {
  const stockRows = Array.from({ length: 46 }, (_, index) => ({
    stock_code: `600${String(index + 1).padStart(3, "0")}`,
    stock_name: `股票筛选样本${index + 1}`,
  }));
  const zsxqItems = Array.from({ length: 46 }, (_, index) => ({
    article_id: `filter-zsxq-${index + 1}`,
    title: `星球筛选样本${index + 1}`,
  }));
  return {
    ...lane("20261012"),
    morning_news: { status: "READY", articles: [] },
    news_workbench: { schema_version: "x", status: "ok", action_rows: stockRows },
    zsxq_hourly: { schema_version: "x", status: "ok", topic_count: zsxqItems.length, items: zsxqItems },
    ai_news: { status: "READY_EMPTY", item_count: 0, items: [] },
    external_finance: { raw_item_count: 0, overview: [] },
    key_investment_messages: [],
  };
};

const statusCellValue = (statusStrip: HTMLElement, label: string): string | undefined => {
  const cell = Array.from(statusStrip.querySelectorAll<HTMLElement>(".hourly-status-cell"))
    .find((candidate) => candidate.querySelector(".hourly-label")?.textContent?.trim() === label);
  return cell?.querySelector("strong")?.textContent?.trim();
};

describe("exact-active ResearchView machine cards and clues", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it("renders machine cards inside the existing feed pane machine tab", async () => {
    stubResearchFetch(lane(), [machineCard()]);

    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");
    await fireEvent.click(screen.getByRole("button", { name: "机器研报" }));

    const tabLabels = Array.from(document.querySelectorAll("[data-research-filter]"))
      .map((tab) => tab.textContent?.trim());
    expect(tabLabels.indexOf("机器研报")).toBeLessThan(tabLabels.indexOf("公众号"));

    const pane = screen.getByRole("region", { name: "情报阅读" });
    expect(screen.getByRole("button", { name: "机器研报" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(pane).getByText("机器生成 · 未人工审核 · 不进入信号与买点")).toBeTruthy();
    expect(await within(pane).findByText("机器研报标题")).toBeTruthy();
    expect(within(pane).getByText("原始文件名：机器研报标题.pdf")).toBeTruthy();
    expect(within(pane).getByText("SUCCEEDED")).toBeTruthy();
    expect(within(pane).getByText("MODEL_GENERATED")).toBeTruthy();
    expect(within(pane).getByText("未人工审核")).toBeTruthy();
    expect(within(pane).getByText("机器生成正文预览，仅供研究。")).toBeTruthy();
  });

  it("shows the duplicate merge notice for deduplicated machine cards", async () => {
    stubResearchFetch(lane(), [machineCard()], [], 2);

    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");
    await fireEvent.click(screen.getByRole("button", { name: "机器研报" }));

    const pane = screen.getByRole("region", { name: "情报阅读" });
    expect(await within(pane).findByText("另有 2 份重复分析已按 document_id 合并。")).toBeTruthy();
  });

  it("shows an explicit empty state when machine cards are not materialized", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(
      url.includes("/api/v4/research/machine-cards")
        ? { ...machineCardsForUrl(url), status: "NOT_MATERIALIZED", cannot_confirm: ["PDF_RESEARCH_NOT_MATERIALIZED"] }
        : url.includes("/api/v4/research/stock-clues")
          ? stockCluesForUrl(url)
          : url.includes("/api/v4/research/wechat/materials") ? wechatListing() : lane(),
    )));

    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");
    await fireEvent.click(screen.getByRole("button", { name: "机器研报" }));

    const pane = screen.getByRole("region", { name: "情报阅读" });
    expect(await within(pane).findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(within(pane).getByText(/该日期暂无机器卡片/)).toBeTruthy();
    const statusStrip = screen.getByRole("region", { name: "研报状态条" });
    expect(statusCellValue(statusStrip, "机器研报")).toBe("NOT_MATERIALIZED");
  });

  it("appends confirmed machine clues after the untouched stock mainline", async () => {
    const laneWithMainline = {
      ...lane(),
      stock_research_daily: [
        { stock_code: "600970", stock_name: "中材国际", report_subject_eligible: true, evidence_level: "L2_MEDIUM" },
        { stock_code: "600971", stock_name: "第二主线", report_subject_eligible: true, evidence_level: "L1_WEAK" },
      ],
    };
    const fiveDocuments = {
      ...stockClue(),
      ts_code: "600002.SZ",
      name: "五份股份",
      document_count: 5,
      document_titles: ["五份报告一", "五份报告二"],
    };
    stubResearchFetch(laneWithMainline, [], [stockClue(), fiveDocuments]);

    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("研报提及 ×5")).toBeTruthy();

    const stockPane = container.querySelector<HTMLElement>(".hourly-priority-pane");
    expect(stockPane).toBeTruthy();
    if (!stockPane) throw new Error("missing stock pane");
    const mainline = stockPane.querySelector<HTMLElement>(".hourly-impact-list");
    expect(mainline).toBeTruthy();
    if (!mainline) throw new Error("missing stock mainline");
    const cards = Array.from(mainline.querySelectorAll<HTMLElement>(".hourly-impact-card"));
    expect(cards.map((card) => card.querySelector(".hourly-impact-title")?.textContent?.trim())).toEqual([
      "中材国际 600970",
      "第二主线 600971",
      "五份股份 600002.SZ",
      "测试股份 600001.SH",
    ]);
    // Original lane rows keep their own rendering and never gain the clue badge.
    expect(cards[0].querySelector(".machine-clue-badge")).toBeNull();
    expect(cards[1].querySelector(".machine-clue-badge")).toBeNull();
    // Clue rows carry the required badge, source tag, first-title reason, and up to three literal titles.
    expect(cards[2].querySelector(".machine-clue-badge")?.textContent?.trim()).toBe("研报提及 ×5");
    expect(cards[3].querySelector(".machine-clue-badge")?.textContent?.trim()).toBe("研报提及 ×3");
    expect(cards[3].querySelector(".hourly-source-tag")?.textContent?.trim()).toBe("机器研报线索");
    expect(cards[3].querySelector(".hourly-impact-reason")?.textContent?.trim()).toBe("报告一");
    expect(Array.from(cards[3].querySelectorAll(".machine-clue-titles .stock-timeline-body"))
      .map((node) => node.textContent?.trim())).toEqual(["报告一", "<b>报告二</b>", "报告三"]);
    expect(cards[3].textContent).not.toContain("报告四");
    expect(cards[3].querySelector(".machine-clue-titles b")).toBeNull();
    expect(stockPane.textContent).toContain("按文本确定性解析，含券商署名已剔除；仅为线索，不是推荐，不进入信号与买点。");
  });

  it("shows machine card and confirmed clue counts in the existing status strip", async () => {
    stubResearchFetch(lane(), [machineCard()], [stockClue()]);

    render(ResearchView, { props: { archiveDate: "20260804" } });

    const statusStrip = await screen.findByRole("region", { name: "研报状态条" });
    await waitFor(() => expect(statusCellValue(statusStrip, "机器研报")).toBe("1"));
    await waitFor(() => expect(statusCellValue(statusStrip, "研报线索")).toBe("1"));
  });

  it("binds auxiliary V4 reads to the resolved latest lane date", async () => {
    const machineRequests: string[] = [];
    const clueRequests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v4/research/machine-cards")) {
        machineRequests.push(url);
        return response(machineCardsForUrl(url));
      }
      if (url.includes("/api/v4/research/stock-clues")) {
        clueRequests.push(url);
        return response(stockCluesForUrl(url));
      }
      if (url.includes("/api/v4/research/wechat/materials")) return response(wechatListing());
      if (url.includes("/api/v4/research/lane?research_date=20260804")) return response(lane("20260804"));
      if (url.includes("/api/v4/research/lane")) return response(lane("20260805"));
      return response(lane("20260804"));
    }));

    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");
    await fireEvent.click(screen.getByRole("button", { name: "查看 latest" }));

    await waitFor(() => {
      expect(machineRequests.at(-1)).toContain("/api/v4/research/machine-cards?research_date=20260805");
      expect(clueRequests.at(-1)).toContain("/api/v4/research/stock-clues?research_date=20260805");
    });
  });

  it("ignores stale auxiliary responses after latest resolves to a different source date", async () => {
    let resolveOldCards: ((value: ReturnType<typeof response>) => void) | undefined;
    let resolveOldClues: ((value: ReturnType<typeof response>) => void) | undefined;
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/api/v4/research/machine-cards")) {
        if (url.includes("research_date=20260804")) {
          return new Promise<ReturnType<typeof response>>((resolve) => { resolveOldCards = resolve; });
        }
        return Promise.resolve(response(machineCardsForUrl(url)));
      }
      if (url.includes("/api/v4/research/stock-clues")) {
        if (url.includes("research_date=20260804")) {
          return new Promise<ReturnType<typeof response>>((resolve) => { resolveOldClues = resolve; });
        }
        return Promise.resolve(response(stockCluesForUrl(url)));
      }
      if (url.includes("/api/v4/research/wechat/materials")) return Promise.resolve(response(wechatListing()));
      if (url.includes("/api/v4/research/lane?research_date=20260804")) return Promise.resolve(response(lane("20260804")));
      if (url.includes("/api/v4/research/lane")) return Promise.resolve(response(lane("20260805")));
      return Promise.resolve(response(lane("20260804")));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");
    await waitFor(() => expect(resolveOldCards).toBeTypeOf("function"));
    await waitFor(() => expect(resolveOldClues).toBeTypeOf("function"));
    await fireEvent.click(screen.getByRole("button", { name: "查看 latest" }));

    const statusStrip = await screen.findByRole("region", { name: "研报状态条" });
    await waitFor(() => {
      expect(statusCellValue(statusStrip, "机器研报")).toBe("0");
      expect(statusCellValue(statusStrip, "研报线索")).toBe("0");
    });

    resolveOldCards?.(response(machineCardsForUrl("/api/v4/research/machine-cards?research_date=20260804", [machineCard()])));
    resolveOldClues?.(response(stockCluesForUrl("/api/v4/research/stock-clues?research_date=20260804", [stockClue()])));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(statusCellValue(statusStrip, "机器研报")).toBe("0");
    expect(statusCellValue(statusStrip, "研报线索")).toBe("0");
  });

  it("does not show auxiliary failures or missing data as zero", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/api/v4/research/machine-cards")) throw new Error("machine endpoint unavailable");
      if (url.includes("/api/v4/research/stock-clues")) throw new Error("network down");
      if (url.includes("/api/v4/research/wechat/materials")) return response(wechatListing());
      if (url.includes("/api/v4/research/lane")) return response(lane("20260804"));
      return response(lane("20260804"));
    }));

    render(ResearchView, { props: { archiveDate: "20260804" } });
    const statusStrip = await screen.findByRole("region", { name: "研报状态条" });
    await waitFor(() => {
      expect(statusCellValue(statusStrip, "机器研报")).toBe("CANNOT_CONFIRM");
      expect(statusCellValue(statusStrip, "研报线索")).toBe("CANNOT_CONFIRM");
    });
  });

  it("does not render standalone machine-card or stock-clue sections under the desk", async () => {
    stubResearchFetch(lane(), [machineCard()], [stockClue()]);

    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("研报提及 ×3")).toBeTruthy();

    expect(screen.queryByRole("region", { name: "机器研报卡片（只读）" })).toBeNull();
    expect(screen.queryByRole("region", { name: "研报股票线索（只读）" })).toBeNull();
    expect(container.querySelector(".machine-cards-section")).toBeNull();
    expect(container.querySelector(".stock-clues-section")).toBeNull();
  });

  it("keeps the frozen 25-stock lookup separate from the current 191-row research lane", async () => {
    const rows = Array.from({ length: 191 }, (_, index) => ({
      stock_code: `OTHER-${index + 1}`,
      stock_name: `未改写队列-${index + 1}`,
      research_score: 100 - index,
      evidence_count: 1,
      evidence_level: "L2_MEDIUM",
      themes: ["测试"],
      report_subject_eligible: true,
    }));
    const position = {
      schema_version: "v4.research.zero_to_history_high_position.v1",
      status: "READY",
      ts_code: "000156.SZ",
      stock_name: "华数传媒",
      asof: "20261023",
      source_asof: "20261023",
      field: "zero_to_history_high_position_pct",
      zero_to_history_high_position_pct: 12.644526445264452,
      basis: "QFQ_ASOF",
      formula: "100 * close_D / max(high_t for t<=D)",
      metric_kind: "PRICE_INTERVAL_ZERO_TO_HISTORY_PCT; not empirical CDF",
      history_scope: "FULL_AVAILABLE_ACCEPTED_SAME_VINTAGE_PREFIX; NOT_CERTIFIED_LISTING_HISTORY",
      summary: "不是经验分位；未认证为上市全历史。",
      source: {
        artifact: "25_ZERO_FLOOR_HIGH_POSITION.csv",
        sha256: "d8d61cc9583eea726c4c2f3b4d0705b2caf4af62d74ffa59eebec243688944b7",
        binding_sha256: "a5e48f4d933b9ba43b1b33834be08c64c6e49bada24df1efea479b9e1ca273ed",
        generation: "f3c4ce582565e4fb431766fd51c02233654e7d384240b7279154ea32691d7104",
        asof: "20261023",
      },
      cannot_confirm: [],
      write_policy: "read_only",
      RESEARCH_ONLY: true,
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const lanePayload = {
      ...lane("20261027"),
      stock_research_daily: rows,
    };
    const fetchMock = vi.fn(async (url: string) => (
      response(url.includes("zero-to-history-high-position") ? position
        : url.includes("/machine-cards") ? machineCardsForUrl(url)
        : url.includes("/stock-clues") ? stockCluesForUrl(url)
        : lanePayload)
    ));
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(ResearchView, { props: { archiveDate: "20261027" } });
    await screen.findByText("8 主线");
    expect(lanePayload.stock_research_daily).toHaveLength(191);
    expect(container.textContent).toContain("未改写队列-8");
    expect(fetchMock.mock.calls.filter(([url]) => url.includes("/lane"))).toHaveLength(1);

    await fireEvent.click(screen.getByRole("button", { name: "读取冻结值" }));
    expect(await screen.findByText("12.644526445264452%")).toBeTruthy();
    expect(screen.getByText("8 主线")).toBeTruthy();
    expect(lanePayload.stock_research_daily).toHaveLength(191);
    expect(lanePayload.stock_research_daily).toEqual(rows);
    expect(lanePayload.stock_research_daily.every((row) => !("zero_to_history_high_position_pct" in row))).toBe(true);
    expect(container.textContent).toContain("源日期：2026-10-23");
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v4/research/lane?research_date=20261027");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/research/zero-to-history-high-position?ts_code=000156.SZ&asof=20261023",
    );
  });

  it("shows the one repair SOP as uncached escaped text at the top-level control", async () => {
    const sopContent = "# 单股修复 SOP\n<script>must stay text</script>";
    const sop = {
      schema_version: "v4.research.single_stock_repair_sop.v1",
      status: "READY",
      content_type: "text/markdown; charset=utf-8",
      content: sopContent,
      source: {
        path: "/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/SOP_SINGLE_STOCK_REPAIR.md",
        sha256: "a".repeat(64),
        size_bytes: sopContent.length,
      },
      cannot_confirm: [],
      write_policy: "read_only",
      RESEARCH_ONLY: true,
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string) => (
      response(url.includes("single-stock-repair-sop") ? sop
        : url.includes("/machine-cards") ? machineCardsForUrl(url)
        : url.includes("/stock-clues") ? stockCluesForUrl(url)
        : lane())
    ));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findAllByText("中材国际");

    await fireEvent.click(screen.getByRole("button", { name: "研究面板更新 SOP" }));
    await waitFor(() => expect(container.querySelector(".repair-sop-content")?.textContent).toContain(sopContent));

    const sopText = container.querySelector(".repair-sop-content");
    expect(sopText?.querySelector("script")).toBeNull();
    expect(container.textContent).toContain(sop.source.path);
    expect(container.textContent).toContain(sop.source.sha256);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v4/research/lane?research_date=20260804");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v4/research/single-stock-repair-sop",
      { cache: "no-store" },
    );
  });

  it("does not start auxiliary reads until a lane date is actually bound", async () => {
    let resolveLane: ((value: ReturnType<typeof response>) => void) | undefined;
    const fetchMock = vi.fn((url: string) => url.includes("/lane")
      ? new Promise<ReturnType<typeof response>>((resolve) => { resolveLane = resolve; })
      : Promise.resolve(response(url.includes("/machine-cards") ? machineCardsForUrl(url) : stockCluesForUrl(url))));
    vi.stubGlobal("fetch", fetchMock);
    render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("正在读取研报决策台。")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveLane?.(response(lane()));
    const strip = await screen.findByRole("region", { name: "研报状态条" });
    await waitFor(() => expect(statusCellValue(strip, "研报线索")).toBe("0"));
  });

  it("keeps machine reports readable when the same-date lane is not materialized", async () => {
    stubResearchFetch({ ...lane(), status: "NOT_MATERIALIZED", reason: "LANE_MISSING" }, [machineCard()]);
    render(ResearchView, { props: { archiveDate: "20260804" } });
    await screen.findByText("LANE_MISSING");
    await fireEvent.click(screen.getByRole("button", { name: "机器研报" }));
    expect(await screen.findByText("机器研报标题")).toBeTruthy();
    expect(screen.getByRole("button", { name: "读取冻结值" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "研究面板更新 SOP" })).toBeTruthy();
  });

  it("consumes the independent aggregate beyond the machine-card display cap", async () => {
    const capped = { ...machineCards("20260804", [machineCard()]), matched_count: 201, truncated: true, max_cards_per_date: 1 };
    const aggregate = { ...stockClues("20260804", [stockClue()]), card_count: 201, scanned_card_count: 201 };
    const fetchMock = vi.fn(async (url: string) => response(url.includes("/machine-cards") ? capped
      : url.includes("/stock-clues") ? aggregate : lane()));
    vi.stubGlobal("fetch", fetchMock);
    render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("研报提及 ×3")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v4/research/stock-clues?research_date=20260804&limit=50", { cache: "no-store", signal: undefined });
    await fireEvent.click(screen.getByRole("button", { name: "机器研报" }));
    expect(await screen.findByText(/该日期共 201 张机器卡片/)).toBeTruthy();
  });

  it.each([0, 1])("marks code-only clue coverage incomplete when confirmed count is %s", async (confirmed) => {
    const fallback = {
      ...stockClues("20260804", confirmed ? [{ ...stockClue(), link_probability: null, confirm_reasons: ["CODE"] }] : []),
      name_map_status: "CANNOT_CONFIRM", name_map_trade_date: "",
      corpus_cache_status: "CANNOT_CONFIRM", corpus_report_count: 0, corpus_fingerprint: "",
      cannot_confirm: ["NAME_MAP_UNAVAILABLE", "CORPUS_UNAVAILABLE"],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.includes("/machine-cards") ? machineCardsForUrl(url)
      : url.includes("/stock-clues") ? fallback : lane())));
    render(ResearchView, { props: { archiveDate: "20260804" } });
    const strip = await screen.findByRole("region", { name: "研报状态条" });
    await waitFor(() => expect(statusCellValue(strip, "研报线索")).toBe(confirmed ? "1 · 来源不完整" : "来源不完整"));
    expect(statusCellValue(strip, "研报线索")).not.toBe("0");
  });

  it("deduplicates equivalent A-share clues while retaining lane authority and HK identities", async () => {
    const authoritative = [
      { stock_code: "600970", stock_name: "权威沪股", source: "LANE_SOURCE", report_subject_eligible: true },
      { stock_code: "00001", market: "HK", stock_name: "权威港股", source: "HK_SOURCE", report_subject_eligible: true },
    ];
    const clues = [
      { ...stockClue(), ts_code: "600970.SH", name: "重复沪股线索" },
      { ...stockClue(), ts_code: "00001.HK", name: "重复港股线索" },
      { ...stockClue(), ts_code: "000001.SZ", name: "独立深股线索" },
    ];
    const payload = { ...lane(), stock_research_daily: authoritative };
    stubResearchFetch(payload, [], clues);
    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("独立深股线索 000001.SZ")).toBeTruthy();
    const cards = Array.from(container.querySelectorAll(".hourly-priority-pane .hourly-impact-card"));
    expect(cards.map((card) => card.querySelector(".hourly-impact-title")?.textContent?.trim())).toEqual([
      "权威沪股 600970", "权威港股 00001", "独立深股线索 000001.SZ",
    ]);
    expect(cards[0].querySelector(".machine-clue-badge")).toBeNull();
    expect(cards[1].querySelector(".machine-clue-badge")).toBeNull();
    expect(container.textContent).not.toContain("重复沪股线索");
    expect(container.textContent).not.toContain("重复港股线索");
    expect(payload.stock_research_daily).toEqual(authoritative);
  });

  it("shows accepted exact-date clues beside a missing lane without binding date-less latest", async () => {
    const missingLane = { ...lane(), status: "NOT_MATERIALIZED", reason: "LANE_MISSING", stock_research_daily: [] };
    const fetchMock = vi.fn(async (url: string) => response(url.includes("/machine-cards") ? machineCardsForUrl(url)
      : url.includes("/stock-clues") ? stockCluesForUrl(url, [stockClue()])
      : url.includes("/lane?") ? missingLane
      : { ...missingLane, endpoint_mode: "LATEST", research_date: "", reason: "NO_RESEARCH_ARCHIVE_LATEST" }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(ResearchView, { props: { archiveDate: "20260804" } });
    expect(await screen.findByText("研报提及 ×3")).toBeTruthy();
    expect(container.querySelector(".hourly-priority-pane")?.textContent).toContain("测试股份 600001.SH");
    expect(screen.getByText("LANE_MISSING")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "查看 latest" }));
    expect((await screen.findByRole("alert")).textContent).toContain("响应缺少 research_date");
    expect(screen.queryByText("研报提及 ×3")).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => url.includes("/stock-clues"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => url.includes("/machine-cards"))).toHaveLength(1);
  });
});
