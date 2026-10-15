import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";

import { loadResearchPdfDocumentDetail, type ResearchPdfDocumentDetail } from "../../api/research_lane";
import ResearchFeedCard from "./ResearchFeedCard.vue";

vi.mock("../../api/research_lane", () => ({
  loadResearchPdfDocumentDetail: vi.fn(),
}));

const firstDocumentId = "a".repeat(64);
const secondDocumentId = "b".repeat(64);

function card(documentId: string, researchDate: string) {
  return {
    kind: "pdf",
    title: "同标题 PDF",
    status: "READY",
    can_open_detail: true,
    document_id: documentId,
    research_date: researchDate,
    source_topic_published_at: "2026-10-15T12:00:00+08:00",
  };
}

function detail(documentId: string, researchDate: string, body: string): ResearchPdfDocumentDetail {
  return {
    schema_version: "v4.zsxq_pdf_document_detail.v1",
    document_id: documentId,
    research_date: researchDate,
    status: "READY",
    receipt: { integrity: "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED" },
    processing: { downloaded_at: "2026-10-15T12:00:01+08:00", ocr_completed_at: "2026-10-15T12:00:02+08:00" },
    last_page_excerpt: body,
    pages: [{ page_number: 1, status: "OCR_OK", method: "test", text: body }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("ResearchFeedCard PDF detail identity", () => {
  afterEach(() => vi.clearAllMocks());

  it("shows processed and total pages for partial progress and completed PDFs", () => {
    const wrapper = mount(ResearchFeedCard, {
      props: {
        card: { ...card(firstDocumentId, "20261015"), status: "PARTIAL", processed_page_count: 1, page_count: 2 },
      },
    });
    expect(wrapper.text()).toContain("页进度：1 / 2 页");

    return wrapper.setProps({
      card: { ...card(firstDocumentId, "20261015"), status: "READY", processed_page_count: 2, page_count: 2 },
    }).then(() => {
      expect(wrapper.text()).toContain("页进度：2 / 2 页");
    });
  });

  it("clears cached OCR detail when an identically titled card changes date and document", async () => {
    const loadDetail = vi.mocked(loadResearchPdfDocumentDetail);
    loadDetail
      .mockResolvedValueOnce(detail(firstDocumentId, "20261015", "旧日期正文"))
      .mockResolvedValueOnce(detail(secondDocumentId, "20261016", "新日期正文"));
    const wrapper = mount(ResearchFeedCard, { props: { card: card(firstDocumentId, "20261015") } });

    await wrapper.get(".pdf-detail-button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("旧日期正文");

    await wrapper.setProps({ card: card(secondDocumentId, "20261016") });
    expect(wrapper.text()).not.toContain("旧日期正文");
    await wrapper.get(".pdf-detail-button").trigger("click");
    await flushPromises();

    expect(loadDetail).toHaveBeenNthCalledWith(1, firstDocumentId, "20261015");
    expect(loadDetail).toHaveBeenNthCalledWith(2, secondDocumentId, "20261016");
    expect(wrapper.text()).toContain("新日期正文");
  });

  it("ignores a detail response that returns after the card identity changes", async () => {
    const loadDetail = vi.mocked(loadResearchPdfDocumentDetail);
    const oldRequest = deferred<ResearchPdfDocumentDetail>();
    const newRequest = deferred<ResearchPdfDocumentDetail>();
    loadDetail.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise);
    const wrapper = mount(ResearchFeedCard, { props: { card: card(firstDocumentId, "20261015") } });

    await wrapper.get(".pdf-detail-button").trigger("click");
    await wrapper.setProps({ card: card(secondDocumentId, "20261016") });
    await wrapper.get(".pdf-detail-button").trigger("click");
    newRequest.resolve(detail(secondDocumentId, "20261016", "当前日期正文"));
    await flushPromises();
    expect(wrapper.text()).toContain("当前日期正文");

    oldRequest.resolve(detail(firstDocumentId, "20261015", "迟到的旧日期正文"));
    await flushPromises();
    expect(wrapper.text()).toContain("当前日期正文");
    expect(wrapper.text()).not.toContain("迟到的旧日期正文");
  });
});
