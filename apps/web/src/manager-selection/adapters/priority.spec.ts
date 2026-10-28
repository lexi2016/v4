import { describe, expect, it } from "vitest";

import {
  buildManagerPrioritySummary,
  type BuildPriorityInput,
} from "./priority";

function stageRow(overrides: Record<string, unknown> = {}) {
  return {
    code: "HK.00001",
    name: "示例股票",
    rank: 1,
    action_level: "NO_BUY",
    trade_status: "WATCH_ONLY",
    status: "WATCH_ONLY",
    formal_eligible: false,
    source_last_bar_time: "2026-09-07 09:40:00",
    next_validation_time: "09:40:05",
    invalidation_price: 10,
    ...overrides,
  };
}

function fact(label_cn: string, current: string, previous: string, period = "截至六个月 2026年6月30日") {
  return {
    fact_type: "OFFICIAL_FACT",
    fields: {
      label_cn,
      period_label_cn: period,
      values: [
        { column: "2026", raw: current },
        { column: "2025", raw: previous },
      ],
    },
    source_sha256: "a".repeat(64),
  };
}

function researchRow(code: string, facts: unknown[], fields: Record<string, unknown> = {}) {
  return {
    code,
    target_trade_date: "20260907",
    source: {
      published_at: "2026-08-28T20:17+08:00",
      retrieved_at: "2026-09-07T15:17:00+00:00",
      sha256: "b".repeat(64),
    },
    facts,
    ...fields,
  };
}

function build(overrides: Partial<BuildPriorityInput> = {}): ReturnType<typeof buildManagerPrioritySummary> {
  return buildManagerPrioritySummary({
    stageRows: [stageRow()],
    stageStatus: "PARTIAL_WITH_ROWS",
    stageCannotConfirm: ["HK:HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"],
    managerResearchRows: [researchRow("HK.00001", [
      fact("收入", "120", "100"),
      fact("净利润", "20", "10"),
      fact("经营活动现金流量净额", "30", "5"),
    ])],
    managerResearchCutoffAt: "2026-09-07T09:40:00+08:00",
    targetDate: "20260907",
    ...overrides,
  });
}

describe("manager priority adapter", () => {
  it("retains every stage row and counts explicit NO_BUY without upgrading it", () => {
    const summary = build({
      stageRows: [
        stageRow({ code: "HK.00001", rank: 1 }),
        stageRow({ code: "HK.00002", name: "第二只", rank: 2 }),
      ],
      managerResearchRows: [
        researchRow("HK.00001", [fact("净利润", "20", "10"), fact("经营活动现金流量净额", "30", "5")]),
        researchRow("HK.00002", [fact("净利润", "-2", "10"), fact("经营活动现金流量净额", "-4", "5")]),
      ],
    });

    expect(summary.retainedCount).toBe(2);
    expect(summary.counts.NO_BUY).toBe(2);
    expect(summary.counts.BUY).toBe(0);
    expect(summary.rows.map((row) => row.code)).toEqual(["HK.00001", "HK.00002"]);
    expect(summary.rows[0].reason).toContain("执行门为 NO_BUY");
    expect(summary.rows[0].dataTime).toContain("阶段=2026-09-07 09:40:00");
    expect(summary.rows[0].buyConditions).toContain("原阶段验证参考：09:40:05（历史记录，不是已核未来计划）");
    expect(summary.rows[0].invalidationConditions).toContain("阶段失效价位：10");
  });

  it("keeps explicit investment advice separate from the stage execution gate", () => {
    const summary = build({
      stageStatus: "PARTIAL_WITH_ROWS",
      stageCannotConfirm: ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"],
      stageRows: [stageRow({ action_level: "NO_BUY", trade_status: "WATCH_ONLY" })],
      managerResearchRows: [researchRow("HK.00001", [
        fact("净利润", "20", "10"),
        fact("经营活动现金流量净额", "30", "5"),
      ], {
        investment_advice: {
          action: "CONDITIONAL_BUY",
          label_cn: "条件研究意见",
          status: "GENERATED",
          summary: "收入与现金流改善仍待下一期复核。",
          conditions: ["复核下一期同口径现金流"],
          blocking_reasons: ["缺少目标日后续承接"],
        },
      })],
    });

    expect(summary.rows[0].category).toBe("NO_BUY");
    expect(summary.rows[0].executionGate).toBe("NO_BUY");
    expect(summary.rows[0].investmentAdvice.action).toBe("CONDITIONAL_BUY");
    expect(summary.rows[0].investmentAdvice.label).toBe("条件研究意见");
    expect(summary.rows[0].investmentAdvice.conditions).toContain("复核下一期同口径现金流");
    expect(summary.rows[0].investmentAdvice.risks).toContain("缺少目标日后续承接");
    expect(summary.rows[0].reason).toContain("独立研究意见单独展示");
  });

  it("projects v2 advice and gate from the nested research recommendation", () => {
    const summary = build({
      stageRows: [stageRow({ action_level: "NO_BUY", trade_status: "NO_TRADE" })],
      managerResearchRows: [researchRow("HK.00001", [
        fact("净利润", "20", "10"),
        fact("经营活动现金流量净额", "30", "5"),
      ], {
        research_recommendation: {
          investment_advice: {
            action: "WATCH",
            label_cn: "研究观察",
            status: "GENERATED",
            summary: "经营质量改善但缺少估值与报价证据。",
            conditions: ["补充估值与时点报价"],
            invalidation_conditions: ["经营现金流转负"],
          },
          execution_gate: {
            action_level: "NO_BUY",
            trade_status: "NO_TRADE",
            status: "BLOCKED",
          },
          as_of: { target_trade_date: "20260907" },
        },
      })],
    });

    expect(summary.rows[0].category).toBe("NO_BUY");
    expect(summary.rows[0].executionGate).toBe("NO_BUY");
    expect(summary.rows[0].investmentAdvice.action).toBe("WATCH");
    expect(summary.rows[0].investmentAdvice.label).toBe("研究观察");
    expect(summary.rows[0].investmentAdvice.summary).toContain("估值");
    expect(summary.rows[0].investmentAdvice.conditions).toContain("补充估值与时点报价");
    expect(summary.rows[0].investmentAdvice.risks).toContain("经营现金流转负");
  });

  it("rejects a BUY value when formal eligibility or exact stage evidence is unsafe", () => {
    const summary = build({
      stageRows: [stageRow({ action_level: "BUY", formal_eligible: false })],
    });

    expect(summary.rows[0].category).toBe("CANNOT_CONFIRM");
    expect(summary.counts.BUY).toBe(0);
    expect(summary.rows[0].reason).toContain("禁止升级为买入");
  });

  it("uses same-period structured facts only as a WATCH research preference when the recommendation is missing", () => {
    const summary = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [
        fact("收入", "120", "100"),
        fact("净利润", "20", "10"),
        fact("经营活动现金流量净额", "30", "5"),
      ])],
    });

    expect(summary.rows[0].category).toBe("WATCH");
    expect(summary.rows[0].reason).toContain("同报告期研究优先级");
    expect(summary.rows[0].reason).toContain("不代表买入建议");
    expect(summary.rows[0].preference.statutoryProfit.state).toBe("POSITIVE");
    expect(summary.rows[0].preference.operatingCashFlow.state).toBe("POSITIVE");
  });

  it("degrades conflicting facts and keeps a deterministic stage-rank/code fallback", () => {
    const summary = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [
        stageRow({ code: "HK.00002", rank: 2, action_level: undefined, status: undefined, trade_status: undefined }),
        stageRow({ code: "HK.00001", rank: 1, action_level: undefined, status: undefined, trade_status: undefined }),
      ],
      managerResearchRows: [
        researchRow("HK.00002", [fact("净利润", "20", "10"), fact("净利润", "-20", "10"), fact("经营活动现金流量净额", "30", "5")]),
        researchRow("HK.00001", []),
      ],
    });

    expect(summary.rows[0].code).toBe("HK.00001");
    expect(summary.rows[0].category).toBe("CANNOT_CONFIRM");
    expect(summary.rows[1].preference.statutoryProfit.state).toBe("CONFLICT");
    expect(summary.rows[1].reason).toContain("冲突已降级");
    expect(summary.counts.WATCH).toBe(0);
    expect(summary.counts.CANNOT_CONFIRM).toBe(2);
  });

  it("keeps a negative raw value negative under a loss label", () => {
    const summary = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [
        fact("净亏损", "-20", "-10"),
      ])],
    });

    expect(summary.rows[0].preference.statutoryProfit.state).toBe("NEGATIVE");
    expect(summary.rows[0].preference.statutoryProfit.current).toBe(-20);
  });

  it("fails closed when a profit/loss label is ambiguous", () => {
    const summary = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [
        fact("利润/(亏损)", "20", "10"),
      ])],
    });

    expect(summary.rows[0].preference.statutoryProfit.state).toBe("CONFLICT");
    expect(summary.rows[0].category).toBe("CANNOT_CONFIRM");
  });

  it("selects the latest complete explicit report period independent of input order", () => {
    const annual = fact("净利润", "20", "10", "截至年度 2025年12月31日");
    const interim = fact("净利润", "-20", "-10", "截至六个月 2026年6月30日");
    const first = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [annual, interim])],
    });
    const second = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [interim, annual])],
    });

    expect(first.rows[0].preference.period).toBe("截至六个月 2026年6月30日");
    expect(second.rows[0].preference.period).toBe(first.rows[0].preference.period);
    expect(first.rows[0].preference.statutoryProfit).toEqual(second.rows[0].preference.statutoryProfit);
    expect(first.rows[0].preference.statutoryProfit.state).toBe("NEGATIVE");
  });

  it("keeps an unparseable report period as a research evidence gap", () => {
    const summary = build({
      stageStatus: "READY",
      stageCannotConfirm: [],
      stageRows: [stageRow({ action_level: undefined, status: undefined, trade_status: undefined })],
      managerResearchRows: [researchRow("HK.00001", [fact("净利润", "20", "10", "报告期未知")])],
    });

    expect(summary.rows[0].preference.period).toBeNull();
    expect(summary.rows[0].preference.completeness).toBe(0);
    expect(summary.rows[0].preference.summary).toContain("报告期文本不可解析");
    expect(summary.rows[0].category).toBe("CANNOT_CONFIRM");
  });

  it("does not present stage order as research preference when facts are unavailable", () => {
    const summary = build({
      stageStatus: "PARTIAL_WITH_ROWS",
      stageCannotConfirm: ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"],
      stageRows: [
        stageRow({ code: "HK.00001", rank: 1 }),
        stageRow({ code: "HK.00002", name: "第二只", rank: 2 }),
      ],
      managerResearchRows: null,
    });

    expect(summary.retainedCount).toBe(2);
    expect(summary.researchPriorityRows).toHaveLength(0);
    expect(summary.rows.map((row) => row.stageRank)).toEqual([1, 2]);
  });
});
