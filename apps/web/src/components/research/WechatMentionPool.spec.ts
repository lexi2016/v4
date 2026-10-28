import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";

import WechatMentionPool from "./WechatMentionPool.vue";

const recordId = "a".repeat(64);
const material = {
  RESEARCH_ONLY: true, WATCH_ONLY: true, NO_BUY_GATE: true,
  production_allowed: false, buy_gate_updated: false, orders_sent: false,
  record_id: recordId,
  article: { article_id: "article", title: "风言风语信息更新 9.20", account: "信息等价权", biz: null,
    url: null, article_date: "20260920", published_at: "2026-09-20T22:48:17+08:00", metadata_origin: "BOUND_FROZEN_MANIFEST" },
  identity: { package_id: "package", source_run_id: "run", input_digest: "d".repeat(64), return_id: "return",
    receipt_sha256: "b".repeat(64), package_sha256: "c".repeat(64), package_sha256_status: "VERIFIED", manifest_sha256: "e".repeat(64) },
  states: { archive: "REPORT_AND_STRUCTURED_ARCHIVED", input_binding: "RECEIPT_BOUND", structure: "COMPLETE", research_review: "NOT_EVALUATED_STAGE_A" },
  receipt_claims: { archive: "REPORT_AND_STRUCTURED_ARCHIVED", structure: "COMPLETE", input_binding_valid: true,
    semantic_research_accepted: false, independent_review_scope: [] },
  received_at: "2026-09-21T00:00:20+08:00", indexed_at: "2026-09-20T16:15:36+00:00", available_at: null,
  missing_artifacts: [], cannot_confirm: ["RESEARCH_NOT_INDEPENDENTLY_VERIFIED"], source_status: "BOUND_MANIFEST_REGISTERED",
  origin: "USER_PROVIDED_CHAT_RETURN", archive_owner: "WECHAT_LOCAL_ARCHIVE", write_policy: "READ_ONLY",
};
const mention = (market: "A" | "BJ" | "HK", code: string) => ({
  market, code, name: "示例公司", entity_id: `ISSUER_${code.replace(".", "_")}`, entity_ids: [`ISSUER_${code.replace(".", "_")}`],
  mapping_status: "IDENTITY_REFERENCE_RESOLVED", mapping_statuses: ["IDENTITY_REFERENCE_RESOLVED"],
  source_named_or_derived: "SOURCE_NAMED", source_named_or_derived_values: ["SOURCE_NAMED"],
  listing_origin: "NAME_RESOLVED", listing_origins: ["NAME_RESOLVED"], source_count: 1,
  source_indexes: ["IMAGE001"], source_index_count: 1, source_names: ["示例来源"],
  claim_context: "券商署名/原文提及，不是推荐", claim_contexts: ["券商署名/原文提及，不是推荐"],
});
const response = (date: string, market: "A" | "BJ" | "HK", items = [mention(market, "600000.SH")], next_cursor: string | null = null) => ({
  schema_version: "v4.wechat_mentions.stage_a.v1", status: "READY", query: { record_id: null, date, date_basis: "article", market, q: "", limit: 50 },
  date_basis: "article", article_date: date, timezone: "Asia/Shanghai", record_id: null, record_ids: [recordId], material, materials: [material],
  items, rows: items, total: next_cursor ? 2 : items.length, returned: items.length, next_cursor, counts: {
    rows: 4, listings: 3, issuers: 3, market_rows: { A: 2, BJ: 1, HK: 1 }, market_listings: { A: 1, BJ: 1, HK: 1 },
    source_named_rows: 4, source_named_listings: 3, source_named_entities: 3, supplemental_listing_rows: 1,
  }, market_totals: { A: 1, BJ: 1, HK: 1 }, provenance: [{ record_id: recordId, artifact_id: "mentions", filename: "mentions.csv", sha256: "f".repeat(64), bytes: 100, status: "HASH_MATCH" }],
  summary_status: "PARTIAL_WITH_UNREADABLE", cannot_confirm: ["ISSUER_MAPPING_NOT_INDEPENDENTLY_VERIFIED"], index_revision: "rev",
  RESEARCH_ONLY: true, WATCH_ONLY: true, NO_BUY_GATE: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
});

const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });

describe("WechatMentionPool", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the exact article-date archive with market tabs and provenance", async () => {
    const duplicateListing = {
      ...mention("A", "688361.SH"),
      mapping_status: "IDENTITY_SOURCE_CODE_VISUALLY_CHECKED",
      mapping_statuses: ["IDENTITY_SOURCE_CODE_VISUALLY_CHECKED", "IDENTITY_REFERENCE_RESOLVED"],
      listing_origin: "SOURCE_CODE",
      listing_origins: ["SOURCE_CODE", "NAME_RESOLVED"],
    };
    const fetch = vi.fn(async () => jsonResponse(response("20260920", "A", [duplicateListing])));
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(WechatMentionPool, { props: { articleDate: "20260920" } });
    await flushPromises();
    expect(wrapper.get('[data-testid="wechat-mention-pool"]').text()).toContain("公众号全文提及");
    expect(wrapper.text()).toContain("文章日 20260920");
    expect(wrapper.text()).toContain("PARTIAL_WITH_UNREADABLE");
    expect(wrapper.text()).toContain("IMAGE001");
    expect(wrapper.text()).toContain("券商署名/原文提及，不是推荐");
    expect(wrapper.text()).toContain("IDENTITY_SOURCE_CODE_VISUALLY_CHECKED");
    expect(wrapper.text()).toContain("IDENTITY_REFERENCE_RESOLVED");
    expect(wrapper.get('[data-testid="wechat-mention-market-A"]').attributes("aria-pressed")).toBe("true");
    expect(wrapper.get('[data-testid="wechat-mention-market-BJ"]').text()).toContain("1");
    const firstUrl = String((fetch.mock.calls as unknown[][])[0][0]);
    expect(firstUrl).toContain("date=20260920");
    expect(firstUrl).toContain("market=A");
  });

  it("switches market and paginates without adding score or rank", async () => {
    const fetch = vi.fn(async (url: string) => url.includes("market=BJ")
      ? jsonResponse(response("20260920", "BJ", [mention("BJ", "920001.BJ")]))
      : jsonResponse(response("20260920", "A", [mention("A", "600000.SH")], "next")));
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(WechatMentionPool, { props: { articleDate: "20260920" } });
    await flushPromises();
    expect(wrapper.find("thead").text()).not.toContain("评分");
    expect(wrapper.find("thead").text()).not.toContain("排名");
    await wrapper.get('[data-testid="wechat-mention-market-BJ"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("920001.BJ");
    await wrapper.get('[data-testid="wechat-mention-market-A"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="wechat-mention-next"]').trigger("click");
    await flushPromises();
    expect(fetch.mock.calls.some(([url]) => String(url).includes("cursor=next"))).toBe(true);
  });

  it("clears a prior date and emits report navigation", async () => {
    const fetch = vi.fn(async (url: string) => jsonResponse(response(url.includes("20260917") ? "20260917" : "20260920", "A")));
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(WechatMentionPool, { props: { articleDate: "20260920" } });
    await flushPromises();
    await wrapper.setProps({ articleDate: "20260917" });
    expect(wrapper.find(".mention-table-wrap").exists()).toBe(false);
    await flushPromises();
    expect(wrapper.text()).toContain("20260917");
    await wrapper.get('[data-testid="wechat-mention-open-report"]').trigger("click");
    expect(wrapper.emitted("open-report")).toHaveLength(1);
  });
});
