import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loadResearchDay,
  loadResearchLane,
  loadResearchLaneLatest,
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
