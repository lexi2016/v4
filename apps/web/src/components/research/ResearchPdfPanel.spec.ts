import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadResearchPdfList, loadResearchPdfAnalysis, type ResearchPdfSummary, type ResearchPdfList, type ResearchPdfDetail } from "../../api/research_lane";
import ResearchPdfPanel from "./ResearchPdfPanel.vue";

vi.mock("../../api/research_lane", () => ({ loadResearchPdfList: vi.fn(), loadResearchPdfAnalysis: vi.fn(), loadResearchPdfDocumentDetail: vi.fn() }));
function summary(date: string | null = "20261023", title = "测试研报"): ResearchPdfSummary {
  const version = { analysis_id: "a".repeat(64), generation: 0, result_sha256: "b".repeat(64), generated_at: "2026-10-24", validation_status: "PASS", semantic_review: "PENDING_INDEPENDENT_REVIEW", scope: null };
  return { analysis_id: version.analysis_id, reference_id: version.analysis_id, reference_kind: "ANALYSIS", occurrence: { namespace: "test", original_source_id: title, occurrence_id: "c".repeat(64) }, metadata: { title }, research_date: date, pdf_sha256: "d".repeat(64), versions: [version], accepted: null, latest_generated: version, preparation_status: "COMPLETE", execution_status: "GENERATED", reason_code: null };
}
function list(row: ResearchPdfSummary, cursor: string | null = null): ResearchPdfList {
  return { schema_version: "v4.pdf_research.list.v1", status: "READY", research_date: row.research_date, date_mode: row.research_date ? "EXACT" : "UNDATED", date_basis: "source_document_date", items: [row], total_count: cursor ? 21 : 1, next_cursor: cursor, snapshot_sha256: "e".repeat(64) };
}
function detail(row: ResearchPdfSummary, body = "待验正文"): ResearchPdfDetail {
  return { ...row, schema_version: "v4.pdf_research.detail.v1", generation: 0, result_sha256: "b".repeat(64), body_sha256: "f".repeat(64), body_markdown: body, cards: [{ facts: [{ claim: "事实", evidence: [{ page_number: 2, quote: "原文", evidence_id: "证据ID" }] }], forecasts: [{ claim: "预测" }], related_entities: [{ name: "主体", role: "研究对象" }], risks: [{ claim: "风险" }] }], review: null };
}
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
afterEach(() => vi.resetAllMocks());

describe("PDF report reading", () => {
  it("reads pending body lazily and renders escaped text plus evidence and SHA", async () => {
    const row = summary(); vi.mocked(loadResearchPdfList).mockResolvedValue(list(row));
    vi.mocked(loadResearchPdfAnalysis).mockResolvedValue(detail(row, "待验正文 <script>unsafe</script>"));
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises();
    expect(loadResearchPdfAnalysis).not.toHaveBeenCalled();
    await wrapper.get(".research-pdf-title").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("待验正文"); expect(wrapper.text()).toContain("待独立内容验收");
    expect(wrapper.find("script").exists()).toBe(false); expect(wrapper.text()).toContain("证据ID");
    expect(wrapper.text()).toContain("b".repeat(64)); expect(wrapper.text()).toContain("预测");
  });
  it("prefers accepted, makes latest pending selectable and retains failure reason", async () => {
    const row = summary(); row.accepted = { ...row.versions[0]!, semantic_review: "ACCEPTED", scope: "FULL_ANALYSIS" };
    row.latest_generated = { ...row.versions[0]!, generation: 1 }; row.versions = [row.accepted, row.latest_generated];
    row.latest_execution = { status: "FAILED", reason_code: "SOURCE_INVALID" };
    vi.mocked(loadResearchPdfList).mockResolvedValue(list(row)); vi.mocked(loadResearchPdfAnalysis).mockResolvedValue(detail(row));
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises();
    await wrapper.get(".research-pdf-title").trigger("click"); await flushPromises();
    expect(vi.mocked(loadResearchPdfAnalysis).mock.calls[0]?.[1]).toBe(0);
    await wrapper.get("select").setValue("1"); await flushPromises();
    expect(vi.mocked(loadResearchPdfAnalysis).mock.calls[1]?.[1]).toBe(1); expect(wrapper.text()).toContain("SOURCE_INVALID");
  });
  it("discards old date list and detail responses even if abort is ignored", async () => {
    const oldList = deferred<ResearchPdfList>(); const oldDetail = deferred<ResearchPdfDetail>();
    const a = summary(), b = summary("20261024", "新日期研报");
    vi.mocked(loadResearchPdfList).mockResolvedValueOnce(list(a)).mockReturnValueOnce(oldList.promise).mockResolvedValueOnce(list(b));
    vi.mocked(loadResearchPdfAnalysis).mockReturnValueOnce(oldDetail.promise);
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises();
    await wrapper.get(".research-pdf-title").trigger("click");
    await wrapper.get(".panel-head-actions button:last-child").trigger("click");
    await wrapper.setProps({ archiveDate: "20261024" }); await flushPromises();
    oldList.resolve(list(a)); oldDetail.resolve(detail(a, "旧正文")); await flushPromises();
    expect(wrapper.text()).toContain("新日期研报"); expect(wrapper.text()).not.toContain("旧正文");
  });
  it("uses explicit undated filter and cursor, resets selection on refresh", async () => {
    const row = summary(); vi.mocked(loadResearchPdfList).mockResolvedValueOnce(list(row, "cursor"))
      .mockResolvedValueOnce(list(summary("20261023", "下一页"))).mockResolvedValueOnce(list(summary(null, "未知日期")));
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises();
    await wrapper.findAll("button").find(b => b.text().includes("下一页"))!.trigger("click"); await flushPromises();
    expect(vi.mocked(loadResearchPdfList).mock.calls[1]?.[1]).toBe("cursor"); expect(wrapper.text()).toContain("下一页");
    await wrapper.findAll("button").find(b => b.text() === "未注明日期")!.trigger("click"); await flushPromises();
    expect(vi.mocked(loadResearchPdfList).mock.calls[2]?.[0]).toEqual({ researchDate: null }); expect(wrapper.text()).toContain("未知日期");
  });
  it("prefers real scoped legacy reference without promoting it and can select new pending", async () => {
    const row = summary(null);
    const legacy: ResearchPdfSummary = { ...summary(null), analysis_id: null, reference_id: "e".repeat(64), reference_kind: "LEGACY_REFERENCE", versions: [], latest_generated: null, semantic_review: "SOURCE_CONSTRAINED_DERIVED_CARD_PASS", scope: "ONE_FACT_ONLY" };
    row.legacy_references = [legacy];
    vi.mocked(loadResearchPdfList).mockResolvedValue(list(row));
    vi.mocked(loadResearchPdfAnalysis).mockResolvedValue({ ...detail(legacy), generation: null, body_markdown: "真实旧范围正文" });
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises();
    await wrapper.get(".research-pdf-title").trigger("click"); await flushPromises();
    expect(vi.mocked(loadResearchPdfAnalysis).mock.calls[0]?.slice(0,2)).toEqual([legacy, null]);
    expect(wrapper.text()).toContain("非全文验收");
    await wrapper.get("select").setValue("0");await flushPromises();
    expect(vi.mocked(loadResearchPdfAnalysis).mock.calls[1]?.slice(0,2)).toEqual([row, 0]);
  });
  it("keeps missing, empty and read errors distinct", async () => {
    const empty = { ...list(summary()), items: [], total_count: 0, status: "NOT_MATERIALIZED" as const };
    vi.mocked(loadResearchPdfList).mockResolvedValueOnce(empty).mockResolvedValueOnce({ ...empty, status: "READY_EMPTY" }).mockRejectedValueOnce(new Error("SHA mismatch"));
    const wrapper = mount(ResearchPdfPanel, { props: { archiveDate: "20261023" } }); await flushPromises(); expect(wrapper.text()).toContain("尚未物化");
    await wrapper.setProps({ archiveDate: "20261024" }); await flushPromises(); expect(wrapper.text()).toContain("没有 PDF 分析记录");
    await wrapper.setProps({ archiveDate: "20261025" }); await flushPromises(); expect(wrapper.get('[role="alert"]').text()).toContain("SHA mismatch");
  });
});
