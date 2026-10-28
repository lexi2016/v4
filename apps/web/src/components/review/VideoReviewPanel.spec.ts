import { cleanup, render, screen, within } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";
import VideoReviewPanel from "./VideoReviewPanel.vue";
import AshareReviewPanel from "./AshareReviewPanel.vue";

const tradeDate = "20261022";
const bv = "BV1WFnU6cE5r";
const video = {
  bv_id: bv, title: "10.22 复盘来源标题", trade_date: tradeDate, target_trade_date: tradeDate,
  date_scope: "SAME_DAY_FUPAN", discovery_status: "TARGET_BV_LOCKED", capture_status: "CAPTURED",
  asr_status: "ASR_REVIEW_REQUIRED", status: "ASR_REVIEW_REQUIRED", asr_segment_count: 56,
  gap_row_count: 0, gap_status: "VIDEO_GAP_AUDIT_EMPTY",
  cannot_confirm: ["ASR transcript spot-check remains required", "ASR transcript is not usable"],
};
const gap = {
  row_id: "G001", bv_id: bv, timestamp: "ASR_RAW_NO_TIMESTAMP", title_or_segment: "来源标题",
  item: "指数量能与风险状态", video_question_or_framework: "视频出现/可能出现 `指数,放量` 这一类复盘问题。",
  current_local_review_behavior: "本地已有 market_rows=1 行，可承接视频问题。",
  gap_type: "NO_ACTION", impact: "保留观察证据，时间段仍待复核。",
  decision: "LOCAL_REVIEW_HAS_OUTPUT", evidence_path: "/local/review/20261022/gap.json",
  cannot_confirm: "股票名和时间段待复核",
};
const review = {
  trade_date: tradeDate, headline: "独立市场复盘", big_picture: [], mainlines: [], core_stocks: [],
  observation_pool: [], next_day_trigger_tree: [], quality_gate: [], cannot_confirm: [],
  video, video_gap_rows: [gap], video_learning_rows: [], production_allowed: false,
  buy_gate_updated: false, orders_sent: false,
} as const;

describe("visible video review evidence", () => {
  afterEach(cleanup);

  it("distinguishes a locked captured source from empty gap output and unusable ASR", () => {
    render(VideoReviewPanel, { props: { tradeDate, video } });
    expect(screen.getByTestId("video-lock-status").textContent).toBe("目标视频已锁定");
    expect(screen.getByText("已采集")).toBeTruthy();
    expect(screen.getByTestId("video-asr-status").textContent).toBe("转写待复核");
    expect(screen.getByTestId("video-segment-count").textContent).toBe("56");
    expect(screen.getByText("不可用于结论")).toBeTruthy();
    expect(screen.getByTestId("video-pending").textContent).toContain("不能据此判定结论通过");
    expect(screen.getByTestId("video-evidence-empty").textContent).toContain("尚未提供可展示的逐条对照");
    expect(screen.queryByText("当天视频未锁定")).toBeNull();
    expect(screen.getByTestId("video-source-link").getAttribute("href")).toBe(`https://www.bilibili.com/video/${bv}`);
  });

  it("renders real framework/local/impact fields without promoting keyword presence into completed analysis", () => {
    render(VideoReviewPanel, { props: { tradeDate, video, gapRows: [gap], learningRows: [{ item: "学习条目", video_framework: "学习框架", local_review_answer: "本地回答", quote: "原始引用句", timestamp: "01:02" }] } });
    const rows = screen.getAllByTestId("video-evidence-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain(gap.video_question_or_framework);
    expect(rows[0].textContent).toContain(gap.current_local_review_behavior);
    expect(rows[0].textContent).toContain(gap.impact);
    expect(rows[0].textContent).toContain("本地已有输出（未验证语义一致）");
    expect(within(rows[0]).queryByRole("link")).toBeNull();
    expect(rows[1].textContent).toContain("原始引用句");
    expect(screen.getByTestId("video-timestamp-link").getAttribute("href")).toBe(`https://www.bilibili.com/video/${bv}?t=62`);
    expect(screen.getByTestId("video-timestamp-link").textContent).toContain("待复核");
    expect(screen.getByText(/关键词命中、材料存在和本地已有输出均不代表已完成语义分析/)).toBeTruthy();
  });

  it("is visible outside the rich surface and replaces only the old video appendix table", async () => {
    const { rerender } = render(AshareReviewPanel, { props: { review } });
    expect(screen.getByTestId("video-review-panel").closest("details")).toBeNull();
    expect(screen.queryByTestId("a-product-first")).toBeNull();
    await rerender({ review: { ...review, catalyst_rows: [{ direction: "催化方向", catalyst: "已有催化" }], review_surface: { tier: "V3_RICH_READY" } } });
    expect(screen.getAllByTestId("video-review-panel")).toHaveLength(1);
    expect(screen.queryByText("视频差距和改进")).toBeNull();
    expect(screen.getByTestId("a-audit-appendix").textContent).toContain("已有催化");
    expect(screen.getByText(/production_allowed=false · buy_gate_updated=false · orders_sent=false/, { selector: ".video-safety" })).toBeTruthy();
  });

  it("isolates stale source metadata, gap and learning rows after a date switch", async () => {
    const { rerender } = render(VideoReviewPanel, { props: { tradeDate, video, gapRows: [gap], learningRows: [{ item: "旧学习内容" }] } });
    await rerender({ tradeDate: "20261023" });
    expect(screen.queryByTestId("video-source-link")).toBeNull();
    expect(screen.queryByTestId("video-evidence-row")).toBeNull();
    expect(screen.queryByText(video.title)).toBeNull();
    expect(screen.queryByText("旧学习内容")).toBeNull();
    expect(screen.getByTestId("video-segment-count").textContent).toBe("未提供");
    expect(screen.getByText(/来源日期缺失或不一致/)).toBeTruthy();
  });

  it("keeps hostile text escaped and generates links only from validated BV and time", () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { container } = render(VideoReviewPanel, { props: {
      tradeDate, video: { ...video, title: hostile, url: "javascript:alert(1)", artifact_refs: [{ kind: "raw", path: "file:///private/secret" }] },
      gapRows: [{ ...gap, quote: hostile, evidence_path: "javascript:alert(1)", timestamp: "00:12", url: "https://evil.test" }],
    } });
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(hostile);
    expect(container.querySelectorAll("a")).toHaveLength(2);
    for (const link of container.querySelectorAll("a")) {
      expect(link.href).toMatch(new RegExp(`^https://www\\.bilibili\\.com/video/${bv}(\\?t=12)?$`));
      expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    }
  });

  it("shows missing source and unknown counts without crashing on malformed collections", () => {
    render(VideoReviewPanel, { props: { tradeDate, video: null, gapRows: "bad", learningRows: {} } });
    expect(screen.getByTestId("video-lock-status").textContent).toBe("当天视频未锁定");
    expect(screen.getByTestId("video-segment-count").textContent).toBe("未提供");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("exposes all 56 raw segments in a collapsed full transcript with explicit unverified time links", () => {
    const sha = "a".repeat(64);
    const segments = Array.from({ length: 56 }, (_, index) => ({
      segment_id: `segment-${index}`, start_seconds: index * 10 + .25, end_seconds: index * 10 + 9.75,
      text: `未经校订的原始转写第 ${index + 1} 段`, evidence_status: "ASR_UNVERIFIED", source_sha256: sha,
    }));
    render(VideoReviewPanel, { props: { tradeDate, video: {
      ...video, transcript_segments: segments, content_status: "RAW_ASR_AVAILABLE",
      content_quality: { status: "ASR_UNVERIFIED", segment_count: 56, message: "已提取，待复核" },
      content_source: { path: "review/20261022/asr/segments.csv", sha256: sha },
    } } });
    const transcript = screen.getByTestId("video-transcript");
    expect(transcript.hasAttribute("open")).toBe(false);
    expect(transcript.querySelector("summary")?.textContent).toContain("已提取 56 段");
    expect(screen.getAllByTestId("video-transcript-segment")).toHaveLength(56);
    expect(screen.getByText("未经校订的原始转写第 56 段")).toBeTruthy();
    expect(within(transcript).getAllByRole("link", { hidden: true })[0].getAttribute("href")).toBe(`https://www.bilibili.com/video/${bv}?t=0`);
    expect(transcript.textContent).toContain("不代表观点提炼或分析完成");
    expect(screen.getByTestId("video-pending")).toBeTruthy();
  });

  it("withholds the whole transcript if any segment contradicts its SHA, scope, evidence status or timestamps", () => {
    const sha = "b".repeat(64);
    const segment = { segment_id: "s", start_seconds: 1.5, end_seconds: 3.5, text: "可读原句", evidence_status: "ASR_UNVERIFIED", source_sha256: sha };
    render(VideoReviewPanel, { props: { tradeDate, video: {
      ...video, asr_segment_count: 8, content_status: "RAW_ASR_AVAILABLE", content_source: { path: "segments.csv", sha256: sha },
      content_quality: { status: "ASR_UNVERIFIED", segment_count: 8 },
      transcript_segments: [segment, { ...segment, text: "错误SHA", source_sha256: "c".repeat(64) },
        { ...segment, text: "异日段", trade_date: "20261021" }, { ...segment, text: "错误结束时间", end_seconds: .5 },
        { ...segment, text: "非法时间", start_seconds: Infinity }, { ...segment, text: "异BV段", bv_id: "BV1gR8e6bETL" },
        { ...segment, text: "错误证据级别", evidence_status: "CONFIRMED" }, null],
    } } });
    expect(screen.queryByTestId("video-transcript")).toBeNull();
    expect(screen.queryByTestId("video-transcript-segment")).toBeNull();
    expect(screen.queryByText("可读原句")).toBeNull();
    expect(screen.queryByText("错误SHA")).toBeNull();
    expect(screen.getByText(/转写正文仍缺/).textContent).toContain("第 2 段：来源 SHA 与全文来源不一致");
    expect(screen.getByText(/转写正文仍缺/).textContent).toContain("第 3 段：日期或 BV 与当天来源不一致");
  });

  it("does not call one returned segment a full transcript when both source declarations claim 56", () => {
    const sha = "a".repeat(64);
    render(VideoReviewPanel, { props: { tradeDate, video: {
      ...video, content_status: "RAW_ASR_AVAILABLE", content_source: { path: "segments.csv", sha256: sha },
      content_quality: { status: "ASR_UNVERIFIED", segment_count: 56 },
      transcript_segments: [{ segment_id: "s", start_seconds: 0, end_seconds: 2, text: "部分文本不能称全文", evidence_status: "ASR_UNVERIFIED", source_sha256: sha }],
    } } });
    expect(screen.getByTestId("video-segment-count").textContent).toBe("56");
    expect(screen.queryByTestId("video-transcript")).toBeNull();
    expect(screen.queryByText("部分文本不能称全文")).toBeNull();
    expect(screen.getByText(/转写正文仍缺/).textContent).toContain("来源声明段数 56 与正文实际 1 段不一致");
    expect(screen.getByText(/转写正文仍缺/).textContent).toContain("正文质量记录段数 56 与正文实际 1 段不一致");
  });

  it.each([
    { content_status: "CANNOT_CONFIRM", content_source: { sha256: "a".repeat(64) } },
    { content_status: undefined, content_source: { sha256: "a".repeat(64) } },
    { content_status: "RAW_ASR_AVAILABLE", content_source: { sha256: "wrong" } },
  ])("withholds raw transcript without a valid content receipt: %j", (content) => {
    render(VideoReviewPanel, { props: { tradeDate, video: {
      ...video, ...content, transcript_segments: [{ segment_id: "s", start_seconds: 0, end_seconds: 2, text: "未核对文本", evidence_status: "ASR_UNVERIFIED", source_sha256: "a".repeat(64) }],
    } } });
    expect(screen.queryByTestId("video-transcript")).toBeNull();
    expect(screen.queryByText("未核对文本")).toBeNull();
  });
});
