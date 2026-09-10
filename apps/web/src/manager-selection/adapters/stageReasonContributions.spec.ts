import { describe, expect, it } from "vitest";

import {
  STAGE_REASON_CONTRIBUTION_KEYS,
  buildStageReasonContributions,
  type StageReasonContributions,
} from "./stageReasonContributions";

const exactRef = (type: string, code = "HK.02718") => ({
  type,
  code,
  source_date: "20260903",
  target_trade_date: "20260904",
  sha256: "a".repeat(64),
});

const stageRow = {
  code: "HK.02718",
  name: "示例标的",
  target_trade_date: "20260904",
  rank: 1,
  d1_rank: 5,
  d1_prob_active: 0.6837,
  pct_chg: 8.43,
  stage_window_change_pct: 0.47,
  stage_score: 57,
  d1_source_refs: [exactRef("HK_D1_TOP100")],
  stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
};

const exactLane = {
  schema_version: "v3_5.research_lane.v1",
  status: "READY",
  research_date: "20260904",
  endpoint_mode: "EXACT",
  external_finance: {
    status: "READY",
    items: [{ title: "US market background", source_date: "20260904" }],
  },
  morning_news: {
    status: "READY",
    articles: [{ title: "market sentiment background", published_at: "2026-09-04T08:00:00+08:00" }],
  },
} as const;

describe("stage reason contribution adapter", () => {
  it("returns five fixed contributions and keeps the 02718 semantics human-readable", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: exactLane,
    });

    expect(Object.keys(contributions)).toEqual([...STAGE_REASON_CONTRIBUTION_KEYS]);
    expect(contributions.d1.status).toBe("JOINED");
    expect(contributions.d1.human_text).toContain("D1第5位");
    expect(contributions.d1.human_text).toContain("prob_active 排序分");
    expect(contributions.d1.human_text).toContain("0.684");
    expect(contributions.d1.human_text).toContain("仅用于入池排序");
    expect(contributions.stage_market.status).toBe("JOINED");
    expect(contributions.stage_market.human_text).toContain("+8.43%");
    expect(contributions.stage_market.human_text).toContain("+0.47%");
    expect(contributions.stage_market.human_text).toContain("阶段排序分57");
    expect(contributions.us_finance.status).toBe("AVAILABLE_NOT_JOINED");
    expect(contributions.hkex_notice.status).toBe("UPSTREAM_MISSING");
    expect(contributions.sentiment.status).toBe("AVAILABLE_NOT_JOINED");
    for (const key of STAGE_REASON_CONTRIBUTION_KEYS) {
      expect(contributions[key].human_text).toEqual(expect.any(String));
      expect(contributions[key].refs).toEqual(expect.any(Array));
    }
  });

  it("does not infer an individual join from a matching title or from an inexact ref", () => {
    const contributions = buildStageReasonContributions({
      row: {
        ...stageRow,
        stage_source_refs: [{ ...exactRef("HK_STAGE_0935_0940"), target_trade_date: "20260903" }],
      },
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: {
          status: "READY",
          items: [{ title: "02718 market background", source_date: "20260904" }],
        },
      },
    });

    expect(contributions.stage_market.status).toBe("CANNOT_CONFIRM");
    expect(contributions.us_finance.status).toBe("AVAILABLE_NOT_JOINED");
    expect(contributions.us_finance.human_text).not.toContain("已绑定");
  });

  it("keeps request failure distinct from an exact lane with missing upstream sources", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: null,
    });

    expect(contributions.us_finance.status).toBe("CANNOT_CONFIRM");
    expect(contributions.hkex_notice.status).toBe("CANNOT_CONFIRM");
    expect(contributions.sentiment.status).toBe("CANNOT_CONFIRM");
  });

  it("treats zero and empty backend source shapes as upstream missing", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: { status: "READY", items: [], count: 0 },
        morning_news: { status: "READY", articles: [], item_count: 0 },
        hkex_notice: { status: "READY", events: [], raw_item_count: 0 },
      },
    });

    expect(contributions.us_finance.status).toBe("UPSTREAM_MISSING");
    expect(contributions.hkex_notice.status).toBe("UPSTREAM_MISSING");
    expect(contributions.sentiment.status).toBe("UPSTREAM_MISSING");
  });

  it("requires a per-stock locator and never promotes an envelope ref to a row join", () => {
    const contributions = buildStageReasonContributions({
      row: {
        ...stageRow,
        d1_source_refs: [{ target_trade_date: "20260904", status: "READY" }],
        stage_source_refs: [],
      },
      targetDate: "20260904",
      stageSelection: {
        source_refs: [exactRef("GLOBAL_STAGE")],
        markets: { HK: { source_ref: exactRef("NESTED_MARKET") } },
      },
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
    expect(contributions.stage_market.status).toBe("CANNOT_CONFIRM");
  });

  it("rejects conflicting aliases and bare tickers, while ah_mapping remains non-identity data", () => {
    const conflicting = buildStageReasonContributions({
      row: {
        ...stageRow,
        code: "HK.02718",
        symbol: "HK.02719",
        d1_source_refs: [exactRef("HK_D1_TOP100")],
        stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
      },
      targetDate: "20260904",
      researchLane: exactLane,
    });
    expect(conflicting.d1.status).toBe("CANNOT_CONFIRM");
    expect(conflicting.stage_market.status).toBe("CANNOT_CONFIRM");

    const bareTicker = buildStageReasonContributions({
      row: {
        ...stageRow,
        code: "02718",
        d1_source_refs: [exactRef("HK_D1_TOP100")],
        stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
      },
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: {
          status: "READY",
          items: [{ code: "02718", source_refs: [exactRef("US_FINANCE")] }],
        },
      },
    });
    expect(bareTicker.d1.status).toBe("CANNOT_CONFIRM");
    expect(bareTicker.stage_market.status).toBe("CANNOT_CONFIRM");
    expect(bareTicker.us_finance.status).toBe("CANNOT_CONFIRM");

    const ahMappingOnly = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: {
          status: "READY",
          items: [{ title: "02718 A/H股票复核", ah_mapping: ["A/H股票复核"] }],
        },
      },
    });
    expect(ahMappingOnly.us_finance.status).toBe("AVAILABLE_NOT_JOINED");
  });

  it("preserves two-digit and three-digit D1 ranks instead of trimming zeroes", () => {
    for (const rank of [10, 20, 100]) {
      const contributions = buildStageReasonContributions({
        row: { ...stageRow, d1_rank: rank },
        targetDate: "20260904",
      });
      expect(contributions.d1.human_text).toContain(`D1第${rank}位`);
      expect(contributions.d1.human_text).not.toContain(`D1第${String(rank).replace(/0+$/, "")}位`);
    }
  });

  it("keeps d1_score neutral and cannot call it a prob_active score", () => {
    const { d1_prob_active: _ignored, ...rowWithoutActiveScore } = stageRow;
    const contributions = buildStageReasonContributions({
      row: {
        ...rowWithoutActiveScore,
        d1_score: 0.6837,
      },
      targetDate: "20260904",
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
    expect(contributions.d1.human_text).toContain("D1排序分约0.684");
    expect(contributions.d1.human_text).not.toContain("prob_active 排序分约0.684");
  });

  it("does not choose between inconsistent d1_prob_active and prob_active fields", () => {
    const contributions = buildStageReasonContributions({
      row: {
        ...stageRow,
        d1_prob_active: 0.6837,
        prob_active: 0.7012,
        d1_source_refs: [exactRef("HK_D1_TOP100")],
      },
      targetDate: "20260904",
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
    expect(contributions.d1.human_text).toContain("prob_active 排序分=CANNOT_CONFIRM");
  });

  it("never treats an explanatory string as a D1 source reference", () => {
    const contributions = buildStageReasonContributions({
      row: {
        ...stageRow,
        d1_source_refs: ["HK.02718 2026-09-04"],
      },
      targetDate: "20260904",
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
  });

  it("rejects a stale row date even when its source ref names the requested date", () => {
    const contributions = buildStageReasonContributions({
      row: {
        ...stageRow,
        target_trade_date: "20260903",
        d1_source_refs: [exactRef("HK_D1_TOP100")],
        stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
      },
      targetDate: "20260904",
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
    expect(contributions.stage_market.status).toBe("CANNOT_CONFIRM");
  });

  it("does not join failed lanes or failed source refs", () => {
    const laneFailed = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: {
          status: "FAILED",
          items: [{
            code: "HK.02718",
            target_trade_date: "20260904",
            source_refs: [exactRef("US_FINANCE")],
          }],
        },
      },
    });
    expect(laneFailed.us_finance.status).toBe("CANNOT_CONFIRM");

    const refFailed = buildStageReasonContributions({
      row: {
        ...stageRow,
        d1_source_refs: [{ ...exactRef("HK_D1_TOP100"), status: "FAILED" }],
      },
      targetDate: "20260904",
    });
    expect(refFailed.d1.status).toBe("CANNOT_CONFIRM");
  });

  it("fails closed when the stage row itself reports any known failure status", () => {
    for (const status of ["FAILED", "ERROR", "CANNOT_CONFIRM", "INVALID", "REJECTED", "ABORTED", "TIMEOUT"]) {
      const contributions = buildStageReasonContributions({
        row: {
          ...stageRow,
          status,
          d1_source_refs: [exactRef("HK_D1_TOP100")],
          stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
        },
        targetDate: "20260904",
      });
      expect(contributions.d1.status, status).toBe("CANNOT_CONFIRM");
      expect(contributions.stage_market.status, status).toBe("CANNOT_CONFIRM");
    }
  });

  it("fails closed when an exact lane individual row reports a failure status", () => {
    const sources = [
      ["external_finance", "FAILED"],
      ["hkex_notice", "ERROR"],
      ["morning_news", "CANNOT_CONFIRM"],
    ] as const;
    for (const [sourceKey, status] of sources) {
      const contributions = buildStageReasonContributions({
        row: stageRow,
        targetDate: "20260904",
        researchLane: {
          ...exactLane,
          [sourceKey]: {
            status: "READY",
            items: [{
              code: "HK.02718",
              target_trade_date: "20260904",
              status,
              source_refs: [exactRef(sourceKey)],
            }],
          },
        },
      });
      const key = sourceKey === "external_finance"
        ? "us_finance"
        : sourceKey === "hkex_notice" ? "hkex_notice" : "sentiment";
      expect(contributions[key].status, sourceKey).toBe("CANNOT_CONFIRM");
    }
  });

  it("keeps missing or non-materialized stage and D1 rows upstream-missing", () => {
    for (const status of ["MISSING", "NOT_MATERIALIZED"]) {
      const contributions = buildStageReasonContributions({
        row: {
          ...stageRow,
          status,
          target_trade_date: "20260904",
          d1_source_refs: [exactRef("HK_D1_TOP100")],
          stage_source_refs: [exactRef("HK_STAGE_0935_0940")],
        },
        targetDate: "20260904",
      });
      expect(contributions.d1.status, status).toBe("UPSTREAM_MISSING");
      expect(contributions.stage_market.status, status).toBe("UPSTREAM_MISSING");
    }
  });

  it("requires the stage row target date even when source references are exact", () => {
    const { target_trade_date: _targetDate, ...missingDateRow } = stageRow;
    const contributions = buildStageReasonContributions({
      row: missingDateRow,
      targetDate: "20260904",
    });

    expect(contributions.d1.status).toBe("CANNOT_CONFIRM");
    expect(contributions.stage_market.status).toBe("CANNOT_CONFIRM");
  });

  it("shows V4 HKEX acquisition and parse state without claiming a historical stage join", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260907",
      managerResearchState: "READY",
      managerResearch: {
        schema_version: "v4.manager_research.product.v1",
        target_trade_date: "20260907",
        stage_id: "STAGE_0935_0940",
        market: "HK_CONNECT",
        provider_id: "v4.hkex.official_titlesearch.v1",
        historical_system_available: false,
        rows: [{
          code: "HK.02718",
          target_trade_date: "20260907",
          status: "CANNOT_CONFIRM",
          source_status: "CANNOT_CONFIRM",
          source_reason: "PDF_NO_STRUCTURED_FACTS",
          historical_system_available: false,
          source: {
            document_title: "2026 INTERIM REPORT",
            provider_id: "v4.hkex.official_titlesearch.v1",
            published_at: "2026-09-03T16:31+08:00",
            retrieved_at: "2026-09-07T03:07:04+00:00",
            source_url: "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0903/2026090300698.pdf",
          },
          facts: [],
        }],
      },
    });

    expect(contributions.hkex_notice.status).toBe("CANNOT_CONFIRM");
    expect(contributions.hkex_notice.human_text).toContain("官方材料已采集");
    expect(contributions.hkex_notice.human_text).toContain("PDF_NO_STRUCTURED_FACTS");
    expect(contributions.hkex_notice.human_text).toContain("不能标记JOINED");
    expect(contributions.hkex_notice.details?.[0]).toMatchObject({
      title: "2026 INTERIM REPORT",
      source: "v4.hkex.official_titlesearch.v1",
      source_url: "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0903/2026090300698.pdf",
    });
  });

  it("keeps parsed V4 facts available while retaining the no-stage-receipt boundary", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260907",
      managerResearchState: "READY",
      managerResearch: {
        target_trade_date: "20260907",
        stage_id: "STAGE_0935_0940",
        market: "HK_CONNECT",
        rows: [{
          code: "HK.02718",
          market: "HK_CONNECT",
          target_trade_date: "20260907",
          source_status: "READY",
          source: { document_title: "公告标题", provider_id: "HKEX" },
          facts: [{ statement_cn: "公告事实", locator: "PDF page 12" }],
        }],
      },
    });

    expect(contributions.hkex_notice.status).toBe("AVAILABLE_NOT_JOINED");
    expect(contributions.hkex_notice.details).toEqual([
      { title: "公告事实", source: "PDF page 12" },
    ]);
    expect(contributions.hkex_notice.human_text).toContain("未提供09:40阶段消费回执");
  });

  it("keeps every known V4 failure status fail-closed across row and nested source fields", () => {
    const statuses = ["ERROR", "INVALID", "REJECTED", "ABORTED", "TIMEOUT", "FAILED"];
    for (const status of statuses) {
      for (const placement of ["row", "source_status", "source"] as const) {
        const row: Record<string, unknown> = {
          code: "HK.02718",
          market: "HK_CONNECT",
          target_trade_date: "20260907",
          source_status: "READY",
          source: { document_title: "公告标题", provider_id: "HKEX", status: "READY" },
          facts: [{ statement_cn: "公告事实", locator: "PDF page 12" }],
        };
        if (placement === "row") row.status = status;
        if (placement === "source_status") row.source_status = status;
        if (placement === "source") row.source = { ...row.source as Record<string, unknown>, status };
        const contributions = buildStageReasonContributions({
          row: stageRow,
          targetDate: "20260907",
          managerResearchState: "READY",
          managerResearch: {
            target_trade_date: "20260907",
            stage_id: "STAGE_0935_0940",
            market: "HK_CONNECT",
            rows: [row],
          },
        });
        expect(contributions.hkex_notice.status, `${placement}=${status}`).toBe("CANNOT_CONFIRM");
      }
    }
  });

  it("rejects missing or wrong direct V4 stage and market scope", () => {
    for (const scope of [
      {},
      { stage_id: "STAGE_0830", market: "HK_CONNECT" },
      { stage_id: "STAGE_0935_0940", market: "A_SHARE" },
    ]) {
      const contributions = buildStageReasonContributions({
        row: stageRow,
        targetDate: "20260907",
        managerResearchState: "READY",
        managerResearch: {
          target_trade_date: "20260907",
          rows: [{
            code: "HK.02718",
            market: "HK_CONNECT",
            target_trade_date: "20260907",
            source_status: "READY",
            source: { document_title: "公告标题", provider_id: "HKEX" },
            facts: [{ statement_cn: "公告事实", locator: "PDF page 12" }],
          }],
          ...scope,
        },
      });
      expect(contributions.hkex_notice.status).toBe("CANNOT_CONFIRM");
    }
  });

  it("marks duplicate exact-code V4 rows as ambiguous rather than upstream missing", () => {
    const row = {
      code: "HK.06166",
      market: "HK_CONNECT",
      target_trade_date: "20260907",
      source_status: "READY",
      source: { document_title: "公告标题", provider_id: "HKEX" },
      facts: [{ statement_cn: "公告事实", locator: "PDF page 12" }],
    };
    const contributions = buildStageReasonContributions({
      row: { ...stageRow, code: "HK.06166" },
      targetDate: "20260907",
      managerResearchState: "READY",
      managerResearch: {
        target_trade_date: "20260907",
        stage_id: "STAGE_0935_0940",
        market: "HK_CONNECT",
        rows: [row, { ...row, source: { document_title: "另一公告", provider_id: "HKEX" } }],
      },
    });

    expect(contributions.hkex_notice.status).toBe("CANNOT_CONFIRM");
    expect(contributions.hkex_notice.human_text).toContain("多个 HK.06166");
  });

  it("projects morning_news articles and preserves the exact 09:40 boundary", () => {
    const make = (source: Record<string, unknown>) => buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        morning_news: { status: "READY", ...source },
      },
    }).sentiment;

    const article = { id: "news-1", title: "早盘资讯", source_name: "新闻源", published_at: "2026-09-04T08:00:00+08:00" };
    const exact = make({ articles: [article], latest_slot: "09:40", source_generated_at: "2026-09-04T09:40:00+08:00" });
    expect(exact.details).toHaveLength(1);
    expect(exact.metadata?.later_than_stage).toBe(false);
    expect(exact.human_text).not.toContain("后续补充");

    const unpadded = make({ articles: [article], latest_slot: "9:00", source_generated_at: "2026-09-04T09:00:00+08:00" });
    expect(unpadded.metadata?.later_than_stage).toBe(false);
    expect(unpadded.human_text).not.toContain("后续补充");
  });

  it("deduplicates US background and marks later zsxq items as supplements", () => {
    const contributions = buildStageReasonContributions({
      row: stageRow,
      targetDate: "20260904",
      researchLane: {
        ...exactLane,
        external_finance: {
          status: "READY",
          item_count: 2,
          raw_item_count: 3,
          items: [
            { id: "us-1", title: "US article", source_name: "RSS", published_at: "2026-09-03T21:00:00Z", url: "https://example.com/us" },
            { id: "us-1", title: "US article duplicate", source_name: "RSS", published_at: "2026-09-03T21:00:00Z", url: "https://example.com/us" },
          ],
        },
        zsxq_hourly: {
          status: "READY",
          item_count: 1,
          latest_slot: "1100",
          source_generated_at: "2026-09-04T11:00:00+08:00",
          items: [{ id: "zsxq-1", title: "盘中补充", source_name: "知识星球", first_seen_at: "2026-09-04T11:00:00+08:00" }],
        },
      },
    });

    expect(contributions.us_finance.details).toHaveLength(1);
    expect(contributions.us_finance.human_text).toContain("原始3条");
    expect(contributions.us_finance.human_text).toContain("不是实时美股报价");
    expect(contributions.sentiment.details).toHaveLength(1);
    expect(contributions.sentiment.human_text).toContain("晚于09:40");
    expect(contributions.sentiment.human_text).toContain("后续补充");
  });
});

const _typeCheck: StageReasonContributions | null = null;
void _typeCheck;
