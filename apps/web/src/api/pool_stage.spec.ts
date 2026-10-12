import { afterEach, describe, expect, it, vi } from "vitest";

import { loadPoolSnapshot, loadStageSnapshot, POOL_PAGE_SIZE } from "./pool_stage";

const jsonResponse = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload });

function pageEntry(totalRows: number, offset: number, returnedRows: number, limit = POOL_PAGE_SIZE) {
  const hasMore = offset + returnedRows < totalRows;
  return {
    total_rows: totalRows,
    offset,
    limit,
    returned_rows: returnedRows,
    has_more: hasMore,
    next_offset: hasMore ? offset + limit : null,
    complete: !hasMore,
  };
}

function poolPayload(date = "20261012", offset = 0, rows?: unknown[]) {
  const aRows = rows ?? Array.from({ length: offset === 0 ? 200 : 171 }, (_, index) => ({ code: `A.${offset + index}` }));
  const aCount = aRows.length;
  const groupRows = offset === 0 ? Array.from({ length: 120 }, (_, index) => ({ code: `A.P${index}` })) : [];
  const groupEntry = pageEntry(120, offset, groupRows.length);
  return {
    trade_date: date,
    requested_date: date,
    selected_date: date,
    data_status: "PARTIAL_WITH_ROWS",
    daily_readiness_status: "PARTIAL_WITH_ROWS",
    write_policy: "read_only",
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    market_totals: { A: 371, HK: 100 },
    a_all_pool_row_count: 371,
    a_all_pool_complete: offset > 0,
    a_all_pool_rows: aRows,
    pools: [{
      pool_id: "a_d1_premarket_pool",
      market: "A",
      status: "V192_CANDIDATE_READY",
      pool_size: 120,
      returned_rows: groupRows.length,
      page_offset: offset,
      page_limit: POOL_PAGE_SIZE,
      has_more: groupEntry.has_more,
      complete: groupEntry.complete,
      rows: groupRows,
    }],
    pool_count: 1,
    pagination: {
      offset,
      limit: POOL_PAGE_SIZE,
      next_offset: offset + aCount < 371 ? offset + POOL_PAGE_SIZE : null,
      has_more: offset + aCount < 371,
      complete: offset + aCount >= 371,
      arrays: {
        a_all_pool_rows: pageEntry(371, offset, aCount),
      },
      pools: {
        a_d1_premarket_pool: groupEntry,
      },
    },
    rows: [],
    blocking_reasons: [],
  };
}

function stagePayload(date = "20261012", stageId = "STAGE_1545_1555") {
  return {
    trade_date: date,
    stage_id: stageId,
    status: "PARTIAL_WITH_ROWS",
    stage: { stage_id: stageId, status: "PARTIAL_WITH_ROWS", display_status: "阶段材料已读取" },
    markets: {
      HK: { market: "HK_CONNECT", status: "PARTIAL_WITH_ROWS", display_mode: "OBSERVATION_UNVERIFIED", candidate_count: 1 },
    },
    unified_rows: [],
    selected_a_rows: 0,
    selected_hk_rows: 1,
    selected_total_rows: 1,
    selection_markets: ["HK"],
    selection_mode: "SHARED_STAGE_CENTER_READ_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("pool and stage API boundary", () => {
  it("requests the fixed A-pool page and validates the real 200 of 371 page", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(poolPayload()));
    vi.stubGlobal("fetch", fetchMock);

    const result = await loadPoolSnapshot("20261012");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/preselection-pools?date=20261012&limit=200&offset=0",
      expect.objectContaining({ signal: expect.anything() }),
    );
    expect(result.a_all_pool_rows).toHaveLength(200);
    expect(result.a_all_pool_row_count).toBe(371);
    expect(result.pagination?.has_more).toBe(true);
  });

  it("preserves a partial source state when the last page is complete", async () => {
    const payload = poolPayload("20261012", 200);
    const fetchMock = vi.fn(async () => jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    const result = await loadPoolSnapshot("20261012", 200);

    expect(result.a_all_pool_rows).toHaveLength(171);
    expect(result.a_all_pool_complete).toBe(true);
    expect(result.data_status).toBe("PARTIAL_WITH_ROWS");
    expect(result.pools?.[0].status).toBe("V192_CANDIDATE_READY");
    expect(result.pools?.[0].complete).toBe(true);
  });

  it("rejects a missing or mismatched pool trade date before the caller can update state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...poolPayload(), trade_date: "20261011" })));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("日期证据错误");

    const missingDate = poolPayload() as Record<string, unknown>;
    delete missingDate.trade_date;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(missingDate)));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("日期证据错误");
  });

  it("rejects invalid markets and inconsistent page counts while accepting producer status tokens", async () => {
    const badMarket = poolPayload() as any;
    badMarket.pools[0].market = "US";
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(badMarket)));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("非法 market");

    const badCount = poolPayload() as any;
    badCount.pagination.arrays.a_all_pool_rows.returned_rows = 199;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(badCount)));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("实际 200 行不一致");

    const accepted = poolPayload() as any;
    accepted.pools.push({
      pool_id: "hkconnect_d1_top100",
      market: "HK",
      status: "STRICT_0_2_READY",
      pool_size: 100,
      returned_rows: 100,
      rows: Array.from({ length: 100 }, (_, index) => ({ code: `HK.${index}` })),
    });
    accepted.pool_count = 2;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(accepted)));
    await expect(loadPoolSnapshot("20261012")).resolves.toMatchObject({ data_status: "PARTIAL_WITH_ROWS" });
  });

  it("requires explicit safe policy and flags for pool and stage responses", async () => {
    for (const field of ["production_allowed", "buy_gate_updated", "orders_sent"] as const) {
      const missingPoolFlag = poolPayload() as Record<string, unknown>;
      delete missingPoolFlag[field];
      vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(missingPoolFlag)));
      await expect(loadPoolSnapshot("20261012")).rejects.toThrow(`缺少布尔型 ${field}`);
    }

    const missingPoolPolicy = poolPayload() as Record<string, unknown>;
    delete missingPoolPolicy.write_policy;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(missingPoolPolicy)));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("write_policy 必须是 read_only");

    const unsafePoolPolicy = poolPayload() as Record<string, unknown>;
    unsafePoolPolicy.write_policy = "write_enabled";
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(unsafePoolPolicy)));
    await expect(loadPoolSnapshot("20261012")).rejects.toThrow("write_policy 必须是 read_only");

    const missingStageFlag = stagePayload() as Record<string, unknown>;
    delete missingStageFlag.RESEARCH_ONLY;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(missingStageFlag)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("RESEARCH_ONLY 必须为 true");

    const missingStageWriteFlag = stagePayload() as Record<string, unknown>;
    delete missingStageWriteFlag.write_performed;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(missingStageWriteFlag)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("缺少布尔型 write_performed");

    const writableStage = stagePayload() as Record<string, unknown>;
    writableStage.write_performed = true;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(writableStage)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("只读请求边界");
  });

  it("requires exact stage identity, legal A/HK market keys, and a read-only response", async () => {
    const wrongStage = stagePayload() as any;
    wrongStage.stage_id = "STAGE_1540_1545";
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(wrongStage)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("stage_id");

    const wrongMarket = stagePayload() as any;
    wrongMarket.markets.US = { status: "READY" };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(wrongMarket)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("非法市场");

    const writable = stagePayload() as any;
    writable.orders_sent = true;
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(writable)));
    await expect(loadStageSnapshot("20261012", "STAGE_1545_1555")).rejects.toThrow("只读请求边界");
  });

  it("keeps page offset out of stage request input", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(stagePayload()));
    vi.stubGlobal("fetch", fetchMock);

    await loadStageSnapshot("20261012", "STAGE_1545_1555");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20261012&stage=STAGE_1545_1555&limit=50",
      expect.objectContaining({ cache: "no-store", signal: expect.anything() }),
    );
  });
});
