import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loadResearchDay,
  loadResearchLane,
  loadResearchLaneLatest,
  loadResearchPdfList,
  loadResearchPdfAnalysis,
  type ResearchPdfSummary,
} from "./research_lane";

const response = (payload: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: vi.fn(async () => payload),
}) as unknown as Response;

const readyLane = () => ({
  schema_version: "v3_5.research_lane.v1",
  status: "READY",
  endpoint_mode: "EXACT",
  research_date: "20260804",
  lane_status: "READY",
  daily_archive_status: "READY",
  cannot_confirm: [],
  write_policy: "read_only",
  recommendation_status: "RESEARCH_ONLY",
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  stock_research_daily: [],
  stock_research_timeline: [],
  research_pool_bridge: [],
  key_investment_messages: [],
  research_quality_summary: {},
  morning_news: {},
  zsxq_hourly: {},
  external_finance: {},
  ai_news: {},
  news_workbench: {},
  hourly_research: {},
});

describe("PDF summary and immutable detail adapter", () => {
  afterEach(() => vi.unstubAllGlobals());
  const row = (): ResearchPdfSummary => ({ analysis_id: "a".repeat(64), reference_id: "a".repeat(64), reference_kind: "ANALYSIS",
    occurrence: { namespace: "test", original_source_id: "fixture", occurrence_id: "b".repeat(64) }, metadata: {}, research_date: "20261023", pdf_sha256: "c".repeat(64),
    versions: [{ analysis_id: "a".repeat(64), generation: 0, result_sha256: "d".repeat(64), generated_at: "", validation_status: "PASS", semantic_review: "PENDING_INDEPENDENT_REVIEW", scope: null }],
    accepted: null, latest_generated: null, preparation_status: "COMPLETE", execution_status: "GENERATED", reason_code: null });
  it("requests date/undated explicitly with abort and no-store, rejects date substitution", async () => {
    const controller = new AbortController();
    const payload = { schema_version: "v4.pdf_research.list.v1", status: "READY", research_date: "20261023", date_mode: "EXACT", items: [row()], total_count: 1, next_cursor: null };
    const fetcher = vi.fn(async (_url: string, _options?: RequestInit) => response(payload)); vi.stubGlobal("fetch", fetcher);
    await loadResearchPdfList({ researchDate: "20261023" }, "cursor", { signal: controller.signal });
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/v3/research/pdf-research?research_date=20261023&cursor=cursor");
    expect(fetcher.mock.calls[0]?.[1]).toEqual({ cache: "no-store", signal: controller.signal });
    await expect(loadResearchPdfList({ researchDate: null })).rejects.toThrow("日期或来源身份");
    expect(fetcher.mock.calls[1]?.[0]).toBe("/api/v3/research/pdf-research?undated=true");
  });
  it("rejects wrong occurrence or immutable result SHA in lazy detail", async () => {
    const selected = row();
    const payload = { ...selected, schema_version: "v4.pdf_research.detail.v1", generation: 0, result_sha256: "e".repeat(64), body_sha256: "f".repeat(64), body_markdown: "fixture", cards: [] };
    vi.stubGlobal("fetch", vi.fn(async () => response(payload)));
    await expect(loadResearchPdfAnalysis(selected, 0)).rejects.toThrow("固定版本校验失败");
    payload.result_sha256 = "d".repeat(64); payload.occurrence = { ...selected.occurrence, occurrence_id: "e".repeat(64) };
    await expect(loadResearchPdfAnalysis(selected, 0)).rejects.toThrow("固定版本校验失败");
  });
});

describe("research lane JSON transport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shares the strict no-store request policy across lane and day products", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(readyLane()))
      .mockResolvedValueOnce(response({
        schema_version: "v3_5.research_day_product.v1",
        status: "NOT_MATERIALIZED",
        authoritative: true,
        endpoint_mode: "EXACT",
        resolved_date: "20260804",
        cannot_confirm: [],
        write_policy: "read_only",
        recommendation_status: "RESEARCH_ONLY",
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadResearchLane("20260804", { signal: controller.signal })).resolves.toMatchObject({
      endpoint_mode: "EXACT",
      research_date: "20260804",
    });
    await expect(loadResearchDay("20260804", { signal: controller.signal })).resolves.toMatchObject({
      endpoint_mode: "EXACT",
      resolved_date: "20260804",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1,
      "/api/v3/research/lane?research_date=20260804",
      { cache: "no-store", signal: controller.signal },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      "/api/v3/research/day?archive_date=20260804",
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("keeps legacy exact/latest calls unbound to the strict validator and request options", async () => {
    const legacyPayload = { status: "READY", research_date: "20260804", producer_extension: true };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(legacyPayload))
      .mockResolvedValueOnce(response(legacyPayload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadResearchLane("20260804")).resolves.toEqual(legacyPayload);
    await expect(loadResearchLaneLatest()).resolves.toEqual(legacyPayload);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v3/research/lane?research_date=20260804");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v3/research/lane");
  });

  it("retains strict transport errors and the legacy raw JSON rejection", async () => {
    const parseError = new SyntaxError("bad JSON");
    const invalidJsonResponse = {
      ok: true,
      status: 200,
      json: vi.fn().mockRejectedValue(parseError),
    } as unknown as Response;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({}, false, 503))
      .mockResolvedValueOnce(invalidJsonResponse)
      .mockResolvedValueOnce(invalidJsonResponse);
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadResearchLane("20260804", {})).rejects.toMatchObject({
      name: "ResearchLaneRequestError",
      kind: "HTTP_NON_2XX",
      status: 503,
    });
    await expect(loadResearchLane("20260804", {})).rejects.toMatchObject({
      name: "ResearchLaneRequestError",
      kind: "INVALID_RESPONSE",
      message: "research lane response is not valid JSON",
    });
    await expect(loadResearchLaneLatest()).rejects.toBe(parseError);
  });
});
