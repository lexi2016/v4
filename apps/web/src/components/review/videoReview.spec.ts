import { describe, expect, it } from "vitest";
import { timestampSeconds, videoBv, videoReviewView } from "./videoReview";

const date = "20261022";
const bv = "BV1WFnU6cE5r";
const source = { trade_date: date, target_trade_date: date, bv_id: bv, discovery_status: "TARGET_BV_LOCKED" };

describe("video evidence projection boundaries", () => {
  it.each([undefined, null, [], "wrong", {}, { ...source, trade_date: undefined }, { ...source, target_trade_date: "20261021" }])("isolates gaps and learning when parent date is missing or different: %j", (video) => {
    const view = videoReviewView(date, video, [{ item: "旧记录" }], [{ item: "旧学习" }]);
    expect(view.canShow).toBe(false);
    expect(view.rows).toHaveLength(0);
    expect(view.url).toBe("");
  });

  it("inherits exact parent scope only for rows without contradictory dates or BV", () => {
    const view = videoReviewView(date, source, [
      { item: "无行日期，继承父级" },
      { item: "同日", trade_date: date, bv_id: bv },
      { item: "异日", trade_date: "20261021" },
      { item: "异日目标", target_trade_date: "20261021" },
      { item: "异日复盘", review_date: "20261021" },
      { item: "异BV", bv_id: "BV1gR8e6bETL" },
      { item: "错型日期", trade_date: [] },
      { item: "错型BV", bv_id: {} }, null, 0, "row", [],
    ], [{ item: "学习同日", bv_id: bv }, { item: "学习异日", trade_date: "20261021" }]);
    expect(view.rows.map((row) => row.item)).toEqual(["无行日期，继承父级", "同日", "学习同日"]);
  });

  it.each(["javascript:alert(1)", `${bv}?t=2`, `https://evil.test/${bv}`, `${bv}/../../x`, `${bv}\n`, "bv1WFnU6cE5r", "BV0000000000", "BV1WFnU6cE5rX"])("rejects malformed video identity %s", (value) => {
    expect(videoBv(value)).toBe("");
    expect(videoReviewView(date, { ...source, bv_id: value }, [{ item: "隐藏" }], []).rows).toHaveLength(0);
  });

  it("keeps unknown counts unknown and preserves true zero", () => {
    expect(videoReviewView(date, source, [], []).segments).toBe("未提供");
    for (const count of [-1, 1.5, "56", NaN, Infinity, null, {}, true]) {
      expect(videoReviewView(date, { ...source, asr_segment_count: count }, [], []).segments).toBe("未提供");
    }
    expect(videoReviewView(date, { ...source, asr_segment_count: 0 }, [], []).segments).toBe("0");
  });

  it("retains pending status even when a separate decision says local output exists", () => {
    const view = videoReviewView(date, source, [{ decision: "LOCAL_REVIEW_HAS_OUTPUT", status: "ASR_REVIEW_REQUIRED" }], []);
    expect(view.pending).toBe(true);
    expect(view.rows[0].status).toContain("未验证语义一致");
    expect(view.rows[0].status).toContain("转写待复核");
  });

  it("does not link artifact paths and filters contradictory artifact scope", () => {
    const view = videoReviewView(date, { ...source, artifact_refs: [
      { path: "review/20261022/runs/x/asr", sha256: "a".repeat(64) },
      { path: "review/20261021/runs/old/asr" },
      { path: "media/current", bv_id: "BV1gR8e6bETL" },
      { path: "review/20261022/runs/x", source_path: "/asr/cache/run_20261023.json" },
    ] }, [], []);
    expect(view.artifacts).toHaveLength(2);
    expect(view.artifacts[0].sha).toBe("a".repeat(64));
  });

  it.each([null, {}, "bad", [null, 1, [], "bad"]])("tolerates malformed row collections %j", (rows) => {
    expect(videoReviewView(date, source, rows, rows).rows).toEqual([]);
  });
});

describe("timestamp links use explicit valid timestamps only", () => {
  it.each([[0, 0], [62, 62], ["0", 0], ["01:02", 62], ["90:00", 5400], ["1:02:03", 3723], ["00:59:59", 3599]])("accepts %j", (input, expected) => {
    expect(timestampSeconds(input)).toBe(expected);
  });
  it.each([undefined, null, "", "ASR_RAW_NO_TIMESTAMP", "00:60", "1:60:00", "1:02:60", "1:2", "1:02:3", "-1", -1, 1.5, "00:01-00:05", "javascript:12", true, {}, Infinity, Number.MAX_SAFE_INTEGER + 1])("rejects %j", (input) => {
    expect(timestampSeconds(input)).toBeNull();
  });
});

describe("full transcript atomic validation", () => {
  const sha = "d".repeat(64);
  const segment = { segment_id: "s", start_seconds: 0, end_seconds: 2, text: "完整原句", evidence_status: "ASR_UNVERIFIED", source_sha256: sha };
  const rawSource = { ...source, asr_segment_count: 1, content_status: "RAW_ASR_AVAILABLE",
    content_source: { path: "segments.csv", sha256: sha }, content_quality: { status: "ASR_UNVERIFIED", segment_count: 1 }, transcript_segments: [segment] };

  it("accepts a complete transcript with dates and BV inherited from its verified parent", () => {
    const view = videoReviewView(date, rawSource, [], []);
    expect(view.transcript).toHaveLength(1);
    expect(view.contentCannotConfirm).toBe("");
  });

  it.each([
    [{ asr_segment_count: 56 }, "来源声明段数 56 与正文实际 1 段不一致"],
    [{ content_quality: { status: "ASR_UNVERIFIED", segment_count: 56 } }, "正文质量记录段数 56 与正文实际 1 段不一致"],
    [{ asr_segment_count: undefined }, "来源声明段数未提供或无效"],
    [{ content_quality: { status: "ASR_UNVERIFIED" } }, "正文质量记录段数未提供或无效"],
    [{ content_quality: { status: "CONFIRMED", segment_count: 1 } }, "全文证据状态不符合原始转写合同"],
    [{ transcript_segments: null }, "全文分段列表未提供或结构无效"],
  ])("rejects inconsistent or missing full-transcript declarations %j", (change, reason) => {
    const view = videoReviewView(date, { ...rawSource, ...change }, [], []);
    expect(view.transcript).toEqual([]);
    expect(view.contentCannotConfirm).toContain(reason);
  });

  it.each([
    [null, "分段结构无效"],
    [{ ...segment, source_sha256: "e".repeat(64) }, "来源 SHA 与全文来源不一致"],
    [{ ...segment, evidence_status: "CONFIRMED" }, "证据状态不符合原始转写合同"],
    [{ ...segment, start_seconds: Infinity }, "分段时间无效"],
    [{ ...segment, end_seconds: -1 }, "分段时间无效"],
    [{ ...segment, trade_date: "20261021" }, "日期或 BV 与当天来源不一致"],
    [{ ...segment, bv_id: "BV1gR8e6bETL" }, "日期或 BV 与当天来源不一致"],
    [{ ...segment, text: " " }, "缺少转写正文"],
  ])("rejects the whole transcript instead of filtering a bad row: %j", (invalid, reason) => {
    const view = videoReviewView(date, { ...rawSource, asr_segment_count: 2,
      content_quality: { status: "ASR_UNVERIFIED", segment_count: 2 }, transcript_segments: [segment, invalid] }, [], []);
    expect(view.transcript).toEqual([]);
    expect(view.contentCannotConfirm).toContain(`第 2 段：${reason}`);
  });
});
