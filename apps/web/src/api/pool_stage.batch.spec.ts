import { afterEach, describe, expect, it, vi } from "vitest";
import { loadStageTimelineBatch } from "./pool_stage";

const DATE = "20261030";
const STAGES = ["STAGE_0925", "STAGE_0930_0935"];

function summary(stage: string) {
  return {
    trade_date: DATE,
    stage: { stage_id: stage, status: "PARTIAL_WITH_ROWS", display_status: "部分完成" },
    selected_a_rows: 0,
    selected_hk_rows: 10,
    markets: { HK: { status: "PARTIAL_WITH_ROWS", observation_count: 10 } },
  };
}

function envelope(stages: string[] = STAGES) {
  return {
    schema_version: "v4.stage_timeline_batch.v1",
    trade_date: DATE,
    stages: Object.fromEntries(stages.map((stage) => [stage, summary(stage)])),
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

function stubFetch(body: unknown) {
  const mock = vi.fn(async (_input: RequestInfo | URL) => ({ ok: true, json: async () => body }) as Response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadStageTimelineBatch", () => {
  it("requests every stage in a single call", async () => {
    const mock = stubFetch(envelope());

    const result = await loadStageTimelineBatch(DATE, STAGES);

    expect(mock).toHaveBeenCalledTimes(1);
    const url = String(mock.mock.calls[0][0]);
    expect(url).toContain("/api/v4/workbench/stage-batch");
    expect(url).toContain(`date=${DATE}`);
    expect(url).toContain(`stages=${encodeURIComponent(STAGES.join(","))}`);
    expect(Object.keys(result)).toEqual(STAGES);
    expect(result.STAGE_0925.stage.stage_id).toBe("STAGE_0925");
  });

  it("rejects a response for a different date", async () => {
    stubFetch({ ...envelope(), trade_date: "20261029" });

    await expect(loadStageTimelineBatch(DATE, STAGES)).rejects.toThrow(/日期/);
  });

  it("rejects a response that reports a write", async () => {
    stubFetch({ ...envelope(), write_performed: true });

    await expect(loadStageTimelineBatch(DATE, STAGES)).rejects.toThrow(/write_performed/);
  });

  it("rejects an unsupported schema", async () => {
    stubFetch({ ...envelope(), schema_version: "v4.stage_timeline_batch.v0" });

    await expect(loadStageTimelineBatch(DATE, STAGES)).rejects.toThrow(/schema_version/);
  });

  it("skips stages the server could not project", async () => {
    stubFetch({ ...envelope(["STAGE_0925"]) });

    const result = await loadStageTimelineBatch(DATE, STAGES);

    expect(Object.keys(result)).toEqual(["STAGE_0925"]);
  });
});
