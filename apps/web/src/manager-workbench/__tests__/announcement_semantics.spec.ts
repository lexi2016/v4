/**
 * Issue #41 real-browser regression.
 * Shape derives from A announcement.py:_analyze_one (the semantic dict is
 * nested inside one lane_decisions.ANNOUNCEMENT record) and B api.py:read_stock
 * (stock + lane_details[].rows/evidence_refs). Content below is synthetic;
 * this is NOT a capture of real announcements or a Mac browser receipt.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { firstReason, researchReasons, researchRisks, stockAccessibleName } from "../display";
import type { StockDecision } from "../types";

const semantic = {
  disposition: "NOT_SELECTED",
  selection_basis: "NOT_SELECTED",
  direction: "NEUTRAL",
  evidence_sufficiency: "VERIFIED_EXISTING_FACTS",
  reason: "已披露的项目尚无新增订单确认证据",
  risk_notes: ["现有订单交付进度存在不确定性", "潜在合同变动可能影响交付"],
  facts: [{ claim: "公司已披露一份项目进展", quote: "项目进展已公告", locator: "公告正文第2段" }],
  changes: [{ claim: "本次披露补充实施节点", quote: "更新实施时间表", locator: "公告正文第3段" }],
  impact: [{ claim: "目前未给出新增收入量化依据", quote: "收益影响仍待确认", locator: "公告正文第4段" }],
  confirmation_conditions: [{ claim: "后续披露新增订单凭据", quote: "后续进展另行公告", locator: "公告正文第5段" }],
  counter_evidence: [{ claim: "业绩影响尚不能确定", quote: "不构成业绩承诺", locator: "公告正文第6段" }],
  source_sha256: "b".repeat(64), body_sha256: "c".repeat(64),
  reader_execution_id: "reader-1", reviewer_execution_id: "reviewer-1"
};
const announcementRow = {
  market: "HK_CONNECT", symbol: "HK.00081", name: null,
  decision: "NOT_SELECTED", reason: "ANNOUNCEMENT_NOT_SELECTED",
  conditions: ["后续披露新增订单凭据"], invalidation_conditions: [],
  risks: [], evidence_ids: ["body-081"],
  semantic, article_id: "HKEX:12345678"
};
const stock: StockDecision = {
  market: "HK_CONNECT", symbol: "HK.00081", name: null, decision: "UNASSESSED",
  // A merge uses status codes here; these are NOT the human research reason.
  reasons: ["ANNOUNCEMENT_NOT_SELECTED"],
  conditions: ["后续披露新增订单凭据"], invalidation_conditions: [],
  risks: [], evidence_ids: ["body-081"], membership_status: "UNKNOWN",
  lane_decisions: { ANNOUNCEMENT: [announcementRow] }
};
const sampleDay = {
  snapshot: { context: { market: "HK_CONNECT", target_date: "20261013", phase: "PREOPEN",
    cutoff: "2026-10-13T09:25:00+08:00" }, run_id: "sample-run" },
  stocks: [stock],
  counts: { selected: 0, watch: 0, unassessed: 1, observation_only: 0, not_selected: 0 },
  pagination: { total: 1, offset: 0, limit: 50 },
  versions: [{ phase: "PREOPEN", run_id: "sample-run" }]
};
const bDetail = {
  plan_run_id: "sample-run", stock,
  lane_details: [{
    lane: "ANNOUNCEMENT", rows: [announcementRow],
    evidence_refs: [{
      evidence_id: "body-081", role: "announcement_body", owner: "official-feed",
      available_at: "2026-10-13T08:01:00+08:00",
      source_url: "https://example.org/official-announcement", verification: "VERIFIED",
      sha256: "b".repeat(64)
    }]
  }]
};
function httpPayload(data: unknown) {
  return { schema_version: "v4.manager_workbench.v1", state: "READY", data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}
function fetchWire() {
  const spy = vi.fn(async (url: string | URL) => new Response(
    JSON.stringify(httpPayload(String(url).includes("/stocks/") ? bDetail : sampleDay)),
    { status: 200, headers: { "content-type": "application/json" } }
  ));
  vi.stubGlobal("fetch", spy);
  return spy;
}

describe("B-shaped announcement semantic display / Mac browser findings", () => {
  beforeEach(() => window.history.replaceState(null, "", "?date=20261013"));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("does not expose literal null or undefined in accessible stock labels when B name is null", async () => {
    fetchWire();
    render(Workbench);
    const button = await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    expect(button.getAttribute("aria-label")).toBe("查看 HK.00081 详情");
    expect(button.getAttribute("aria-label")).not.toContain("null");
    await fireEvent.click(button);
    expect(screen.getByRole("heading", { name: "HK.00081" })).toBeTruthy();
    expect(stockAccessibleName(stock)).toBe("HK.00081");
  });

  it("shows actual saved semantic.reason rather than A status code as primary research basis", async () => {
    fetchWire();
    render(Workbench);
    await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    expect(firstReason(stock)).toContain(semantic.reason);
    expect(firstReason(stock)).not.toContain("ANNOUNCEMENT_NOT_SELECTED");
    expect(researchReasons(stock)).toEqual([{ lane: "ANNOUNCEMENT", text: semantic.reason }]);
    await fireEvent.click(screen.getByRole("button", { name: "查看 HK.00081 详情" }));
    expect(screen.getByText(semantic.reason)).toBeTruthy();
    expect(screen.getByText("待评估")).toBeTruthy(); // preserves server UNASSESSED, no promotion
    expect(screen.queryByText("ANNOUNCEMENT_NOT_SELECTED")).toBeNull(); // raw code in folded audit only
  });

  it("renders facts, genuine changes, impact, conditions and counter-evidence with original quotes/locators", async () => {
    fetchWire();
    render(Workbench);
    const button = await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    await fireEvent.click(button);
    for (const field of ["事实与原文", "相对变化", "经营影响", "确认条件", "反证与限制"]) {
      expect(screen.getByText(field)).toBeTruthy();
    }
    for (const field of [semantic.facts[0], semantic.changes[0], semantic.impact[0],
      semantic.confirmation_conditions[0], semantic.counter_evidence[0]]) {
      expect(screen.getAllByText(field.claim).length).toBeGreaterThan(0);
      expect(screen.getByText(field.quote)).toBeTruthy();
      expect(screen.getAllByText("原文位置：" + field.locator).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole("link", { name: "查看原始公告资料" }).getAttribute("href"))
      .toBe("https://example.org/official-announcement");
  });

  it("surfaces BOTH semantic risk_notes even when stock.risks is empty, without manufacturing a new verdict", async () => {
    fetchWire();
    render(Workbench);
    await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    await fireEvent.click(screen.getByRole("button", { name: "查看 HK.00081 详情" }));
    const riskCard = screen.getByRole("heading", { name: "风险" }).closest("article");
    expect(riskCard).not.toBeNull();
    const withinRisk = within(riskCard as HTMLElement);
    expect(withinRisk.getByText(semantic.risk_notes[0])).toBeTruthy();
    expect(withinRisk.getByText(semantic.risk_notes[1])).toBeTruthy();
    expect(withinRisk.queryByText("未提供")).toBeNull();
    expect(researchRisks(stock).map(x => x.text)).toEqual(semantic.risk_notes);
    expect(screen.getByText("待评估")).toBeTruthy(); // no upgrade based on a positive phrase
  });

  it("raw JSON and duplicate saved rows are initially folded away, but remain inspectable", async () => {
    fetchWire();
    render(Workbench);
    await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    await fireEvent.click(screen.getByRole("button", { name: "查看 HK.00081 详情" }));
    const auditSummary = screen.getByText("原始研究字段（审计）");
    const audit = auditSummary.closest("details") as HTMLDetailsElement;
    expect(audit).not.toBeNull();
    expect(audit.open).toBe(false);
    expect(audit.querySelectorAll("pre").length).toBeGreaterThan(0);
    await fireEvent.click(auditSummary);
    expect(audit.open).toBe(true);
    expect(audit.textContent).toContain("ANNOUNCEMENT_NOT_SELECTED");
    const sourceSummary = within(audit).getByText("保存的原始来源行");
    expect((sourceSummary.closest("details") as HTMLDetailsElement).open).toBe(false);
  });

  it("does not translate a machine-only status into invented research prose", () => {
    const withoutSemantic = { ...stock, lane_decisions: {
      ANNOUNCEMENT: [{ decision: "NOT_SELECTED" as const, reason: "ANNOUNCEMENT_NOT_SELECTED" }]
    } };
    expect(researchReasons(withoutSemantic)).toEqual([]);
    expect(firstReason(withoutSemantic)).toBe("未提供具体研究理由");
  });

  it("uses ordinary business wording outside the folded audit and retains five original views", async () => {
    fetchWire();
    render(Workbench);
    await screen.findByRole("button", { name: "查看 HK.00081 详情" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(5);
    await fireEvent.click(screen.getByRole("button", { name: "查看 HK.00081 详情" }));
    expect(screen.getByText("各类研究依据")).toBeTruthy();
    expect(screen.queryByText(/A引擎|B原始记录|POST/)).toBeNull();
    expect(screen.getByText("仅供核对的原始字段、模型与来源记录均已收起。")).toBeTruthy();
  });
});
