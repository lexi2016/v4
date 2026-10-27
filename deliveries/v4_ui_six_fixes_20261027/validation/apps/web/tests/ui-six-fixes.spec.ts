import { describe, expect, it, vi, afterEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { poolCountLabel } from "../src/app_shell/formatters";
import { loadStageSnapshot } from "../src/api/pool_stage";
import ResearchFeedCard from "../src/components/research/ResearchFeedCard.vue";
import { loadResearchPdfDocumentDetail } from "../src/api/research_lane";
vi.mock("../src/api/research_lane", () => ({ loadResearchPdfDocumentDetail: vi.fn() }));

describe("six-fix display regressions", () => {
  afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });
  it("distinguishes page remainder, source failure and unknown completion", () => {
    const group = { pool_id: "a_all_pool_summary", pool_size: 482, returned_rows: 200, complete: false, has_more: true };
    expect(poolCountLabel(group)).toBe("当前显示 200 / 共 482 条");
    expect(poolCountLabel({ ...group, status: "CANNOT_CONFIRM" })).toContain("待补齐");
    expect(poolCountLabel({ ...group, has_more: undefined })).toContain("待补齐");
    expect(poolCountLabel({ ...group, returned_rows: 82, complete: true, has_more: false })).not.toContain("待补齐");
    expect(poolCountLabel({ pool_id: "empty", rows: [] })).toBe("未生成/待补齐");
  });
  it("accepts exact HK-only missing receipt and rejects wrong stage markets/date", async () => {
    const summary = { status: "CANNOT_CONFIRM", display_mode: "CANNOT_CONFIRM", candidate_count: null };
    const payload: any = {
      trade_date: "20261027", stage_id: "STAGE_1545_1555", status: "CANNOT_CONFIRM",
      stage: { stage_id: "STAGE_1545_1555", status: "CANNOT_CONFIRM", display_status: "CANNOT_CONFIRM" },
      markets: { HK: summary },
      selection_markets: { HK_CONNECT: { market: "HK_CONNECT", status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM", selected_rows: null, rows: [], selection_manifest_receipt_verified: false } },
      execution_evidence: { trade_date: "20261027", stage_id: "STAGE_1545_1555", status: "EXECUTION_RECEIPT_MISSING", execution_verified: false, natural_verified: false, write_performed: false, cannot_confirm: ["EXACT_DATE_STAGE_RECEIPT_MISSING"] },
      unified_rows: [], selected_a_rows: 0, selected_hk_rows: null, selected_total_rows: null,
      selection_mode: "SHARED_STAGE_CENTER_READ_ONLY", RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false, write_performed: false,
    };
    const response = () => ({ ok: true, status: 200, json: async () => payload });
    vi.stubGlobal("fetch", vi.fn(response));
    expect((await loadStageSnapshot("20261027", "STAGE_1545_1555")).status).toBe("CANNOT_CONFIRM");
    payload.markets.A = summary;
    await expect(loadStageSnapshot("20261027", "STAGE_1545_1555")).rejects.toThrow();
    delete payload.markets.A;
    payload.execution_evidence.trade_date = "20261026";
    await expect(loadStageSnapshot("20261027", "STAGE_1545_1555")).rejects.toThrow();
  });
  it("refreshes only the same PDF card status/progress/time from verified detail", async () => {
    vi.mocked(loadResearchPdfDocumentDetail).mockResolvedValue({ schema_version: "v4.zsxq_pdf_document_detail.v1", document_id: "a".repeat(64), research_date: "20261027", status: "READY", pages: [], receipt: { integrity: "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED" }, processing: { processed_page_count: 18, page_count: 18, ocr_completed_at: "2026-10-27T09:00:52+08:00" } });
    const wrapper = mount(ResearchFeedCard, { props: { card: { kind: "pdf", document_id: "a".repeat(64), research_date: "20261027", status: "PARTIAL", processed_page_count: 8, page_count: 18, can_open_detail: true } } });
    expect(wrapper.text()).toContain("页进度：8 / 18 页");
    await wrapper.get(".pdf-detail-button").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("页进度：18 / 18 页");
    expect(wrapper.text()).toContain("OCR 完成：2026-10-27 09:00:52+08:00");
    expect(wrapper.text()).not.toContain("部分完成");
  });
});
