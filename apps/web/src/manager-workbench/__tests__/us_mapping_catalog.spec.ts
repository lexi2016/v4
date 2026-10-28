import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";

function envelope<T>(data: T, state = "READY"): Record<string, unknown> {
  return {
    schema_version: "v4.manager_workbench.v1", state, data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false
  };
}
function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("source-bound US-to-HK research catalog", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261013"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("loads only on demand, searches an asset, and displays raw status and safety limits", async () => {
    const day = {
      snapshot: null, stocks: [], counts: null,
      pagination: { total: 0, offset: 0, limit: 50 }, versions: []
    };
    const recoveryFullRecord = {
      relation_id: "R001", source_original_fields: { 关系编号: "R001", code: "00001", asset_code: "CVE" },
      effective_summary: { closure_status: "OPEN", primary_research_use: "股权与共同资产敞口研究" },
      effective_research: { relation_id: "R001", evidence_ids: ["B2L1_R001_E01"], research_layers: { FACT_VERIFIED_SCOPE: {} } },
      six_layers: [{ layer: "FACT_VERIFIED_SCOPE" }], field_assessments: [{ source_field: "fact" }]
    };
    const recoveryRelation = {
      detail_level: "FULL", relation_id: "R001", closure_status: "OPEN",
      primary_research_use: "股权与共同资产敞口研究", primary_use_reason: "存在报告期联营敞口",
      verified_fact_scope: ["仅按报告期判断"], applicable_period: "2026H1",
      closure_scope: "当前权益比例尚未闭环", closure_basis: "仍缺当前持股数量",
      remaining_gaps: ["当前权益比例待核"], next_key_evidence: ["最新投资附注"],
      research_access_date_and_version: "2026-10-15; access date only",
      effective_research_file: "recovered_mapping_20261016/current/R001.json",
      effective_research_sha256: "b".repeat(64), evidence_ids: ["B2L1_R001_E01"],
      delivery_acceptance: "PASS_RESTORED_BASELINE", prediction: "UNTESTED",
      historical_PIT: "NOT_VALIDATED", event_and_data_tests: "NOT_RUN",
      company_independent_acceptance: 0, full_record: recoveryFullRecord
    };
    const relation = {
      review_detail_level: "FULL",
      relation_id: "R001", source_review_status: "SOURCE_REVIEWED", independent_verification: "NOT_RUN",
      research_use: "PENDING_REVIEW",
      review_revision: { revision: { revision_research_fact_state: "VERIFIED_DATED_ASSOCIATE_FACT",
        revision_current_applicability_state: "PENDING_CURRENT_OWNERSHIP_AND_WEIGHT",
        revision_subsequent_research_addenda_json: [{ revision: "Delaware正文与IL索引冲突未获解释" }],
        revision_failure_checks_json: "原始未闭合的 failure-check 文本，保留原样",
        revision_remaining_gaps_json: ["当前权益比例待核"], revision_research_fact_dates: ["2026-10-15 UTC"] },
        revision_json_parse_issues: [{ field: "revision_failure_checks_json", issue: "INVALID_JSON_PRESERVED_AS_SOURCE_TEXT",
          error_type: "JSONDecodeError", raw_sha256: "257bc433eded097eddc4290c61a934ff63a94b9e1b1252f21eef774f09c7f625", raw_characters: 28 }],
        source_summary: { primary_use: "来源研究用途示例", primary_use_reason: "保留边界", verified_facts_json: ["来源支持范围"],
          usage_limits_json: "旧使用限制", next_key_evidence_json: "旧下一证据",
          current_usage_limits_with_addenda_json: ["州注册冲突限制；SFD是WH ADR、87%为当前精确值"],
          current_next_key_evidence_with_addenda_json: ["待官方更正索引或解释"],
          current_applicability_gaps_json: ["旧缺口仍保留"] },
        evidence: [{ evidence_id: "E1", title: "补证一", open_status: "OPENED_BODY", published_date: "2026-08-13",
          url: "https://example.com/revision", does_not_support: "价格预测",
          declared_unresolved_navigation_reference_json: "[{\"reference\":\"R1\"}]",
          evidence_wording_clarifications_json: "[{\"term\":\"适用期\",\"clarification\":\"仅按披露期解释\"}]" }] },
      recovery_v2r1: recoveryRelation,
      source_row: 1, hk_code: "00001", us_symbol: "CVE",
      source_record: {
        type: "OWNERSHIP", segment: "联营投资", fact: "公司材料列明应占利润",
        mechanism: "盈利与股权价值可影响投资收益", condition: "以正式盈利和权益变化为触发",
        direction: "不预设当日方向", timescale: "消息日至数季",
        failure: "业务分部抵消；持股变化；市场流动性",
        evidence_strength: "HIGH", evidence_reason: "来源包中的明确关系陈述",
        information_date: "2026-08-13", status: "HISTORICAL_ONLY",
        mapping_status: "REVIEWED_WEAK_MAPPING", relation_verification: "VERIFIED_SCOPE_WITH_GAPS",
        effective_candidate: "False", current_observation_candidate: "False", audit_only: "True",
        prediction: "UNTESTED", old_action: "NOT_RUN", prediction_eligible: "False",
        historical_PIT: "NOT_VALIDATED", url: JSON.stringify(["https://example.com/primary-evidence", "https://example.com/second", "javascript:alert(1)", "https://user:password@example.com/secret"])
      },
      fact_review_status: "PENDING", prediction_eligible: false,
      prediction_validation: "UNTESTED", historical_PIT: "NOT_VALIDATED"
    };
    const catalogData = {
      research_use: "",
      recovery_v2r1: {
        source_package_sha256: "48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4",
        source_manifest_sha256: "c".repeat(64), overlay_integrity_sha256: "d".repeat(64),
        counts: { snapshot_stocks: 667, original_relations: 1003, processed_relations: 1003,
          closure_status_counts: { CLOSED_RESEARCH_SCOPE: 757, CLOSED_EXCLUDED_SCOPE: 25, OPEN: 221 },
          research_scope_closed: 757, excluded_scope_closed: 25, closed_total_including_exclusions: 782,
          open_relations: 221, stocks_with_relations: 649, stocks_without_relations: 18, company_independent_acceptance: 0 },
        research_safety: { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false,
          orders_sent: false, fact_validation: "INDEPENDENT_ACCEPTANCE_0", prediction_validation: "UNTESTED",
          historical_PIT: "NOT_VALIDATED", event_and_data_tests: "NOT_RUN", semantic_mapping_validity: "CANNOT_CONFIRM" },
        evidence_limits: { historical_path_gap_occurrences: 227, historical_path_gap_unique_paths: 218,
          separate_restored740_missing_path_sha_pairs: 404, separate_restored740_missing_hashes: 388,
          gap_scopes_additive: false, A_url_occurrences_unattempted: 62, available_at: "ABSENT",
          access_dates_are_available_at: false, access_date_interpretation: "Research access dates do not establish fact effective dates or available_at.",
          all_statements_verified: false },
        prior_700_history: { sha256: "e".repeat(64), record_count: 700,
          source_package_sha256: "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0",
          retained_as_separate_history: true, status_crosswalk: "NOT_ESTABLISHED" },
        version_precedence: { version: "current v2r1" }, projection_rule: "Keep v2r1 and legacy states separate."
      },
      review_progress: { source_reviewed_relations: 700, unprocessed_relations: 303, source_reviewed_stocks: 378,
        all_original_relations_processed_stocks: 378, independently_verified_relations: 0,
        independent_verification: "NOT_RUN", research_use_counts: { PENDING_REVIEW: 985 } },
      review_source: { source_package_sha256: "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0", source_generated_at_utc: "2026-10-15T14:36:36.647452+00:00", integrity_sha256: "dc2884635d43fea1f828366fddd22dc17f5de0b3625dc63cb93fb5415adb9a34" },
      catalog_id: "us_hk_667_20261015_from_20261014_membership",
      catalog_state: "STRUCTURE_VALID_ONLY",
      catalog_integrity_sha256: "a".repeat(64),
      source: {
        package_name: "逐股审核_001-667_实际研究结果.zip",
        package_sha256: "dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d",
        membership_snapshot: "2026-10-14", membership_sha256: "9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c",
        zip_crc: "PASS", manifest: "PASS", package_member_count: 15
      },
      coverage: { membership_count: 667, relation_row_count: 1003, stocks_with_relations: 649 },
      source_claims: {
        main_table_a_progress: { REVIEWED: 667 },
        main_table_a_prediction_state: { UNTESTED: 667 },
        old_matrix_comparison: "NOT_RUN", independent_fact_verification: "PENDING"
      },
      safety: {
        RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false,
        orders_sent: false, prediction_validation: "UNTESTED", historical_PIT: "NOT_VALIDATED"
      },
      query: "CVE", total: 1, offset: 0, limit: 25,
      items: [{
        ordinal: 1, hk_code: "00001", name: "长和", english_name: "CKH HOLDINGS",
        source_record: {
          "研究行业": "综合企业", "主营": "港口、零售、基建、电讯及投资",
          "盈利驱动": "分部盈利、投资收益与资产处置", "主要及辅助资产": "CVE",
          "关系意义": "仅为研究线索", "研究进度": "REVIEWED"
        },
        relation_count: 1, source_reviewed_relation_count: 1, unprocessed_relation_count: 0, relations: [relation]
      }]
    };
    let detailRequests = 0;
    let releaseStaleDetail: ((value: Response) => void) | null = null;
    const spy = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      if (url.includes("/mapping-catalog")) {
        const query = new URL(url, "http://localhost").searchParams.get("q") || "";
        const params = new URL(url, "http://localhost").searchParams;
        const offset = Number(params.get("offset") || 0);
        const explicitDetail = query === "R001";
        const exactUnprocessed = query === "R700";
        const summaryRelation = { ...relation, review_detail_level: "SUMMARY",
          recovery_v2r1: { ...relation.recovery_v2r1, detail_level: "SUMMARY", full_record: undefined },
          review_revision: { ...relation.review_revision, evidence: undefined, revision_json_parse_issues: undefined } };
        const unprocessedRelation = { ...relation, relation_id: "R700", source_review_status: "NOT_PROCESSED",
          review_detail_level: "FULL", recovery_v2r1: { ...recoveryRelation, relation_id: "R700",
            full_record: { ...recoveryFullRecord, relation_id: "R700" } }, review_revision: null };
        const data = { ...catalogData, query, offset, research_use: params.get("research_use") || "",
          total: query ? 1 : 667, items: catalogData.items.map(item => ({ ...item, ordinal: offset + 1,
            source_reviewed_relation_count: exactUnprocessed ? 0 : item.source_reviewed_relation_count,
            unprocessed_relation_count: exactUnprocessed ? 1 : item.unprocessed_relation_count,
            relations: [exactUnprocessed ? unprocessedRelation : explicitDetail ? relation : summaryRelation] })) };
        if (explicitDetail) {
          detailRequests++;
          if (detailRequests === 1) return new Response(JSON.stringify({ detail: "补证读取失败示例" }), { status: 503 });
          if (detailRequests === 2) return new Promise<Response>(resolve => { releaseStaleDetail = resolve; });
          if (detailRequests === 3) return response(envelope({ ...data,
            items: data.items.map(item => ({ ...item, relations: [{ ...relation, relation_id: "R999" }] }))
          }, "STRUCTURE_VALID"));
        }
        return response(envelope(data, "STRUCTURE_VALID"));
      }
      return response(envelope(day, "NOT_RUN"));
    });
    vi.stubGlobal("fetch", spy);

    render(Workbench);
    await screen.findByText(/未读取|NOT_RUN/);
    expect(spy.mock.calls.some(([input]) => String(input).includes("/mapping-catalog"))).toBe(false);

    await fireEvent.click(screen.getByRole("tab", { name: "美股映射资料库" }));
    await screen.findByText(/ZIP CRC：PASS；清单校验：PASS；包内文件：15/);
    expect(screen.getByText(/预测状态 UNTESTED/)).toBeTruthy();
    expect(screen.getByText(/旧 700 历史 overlay SOURCE_REVIEWED：700 \/ 1003 条关系、378 \/ 667 只股票；旧 overlay 未覆盖 303 条关系/)).toBeTruthy();
    expect(screen.getByText(/研究范围闭环 757 条；排除范围闭环 25 条；开放 221 条/)).toBeTruthy();
    expect(screen.getByText(/782 条总闭环包含 25 条排除范围记录/)).toBeTruthy();
    expect(screen.getByText((_, element) => element?.tagName === "P" &&
      element.textContent?.includes("R001 · v2r1 当前闭环：OPEN") === true)).toBeTruthy();
    expect(screen.getByText(/全部原始关系已有记录：378 只股票/)).toBeTruthy();
    expect(screen.getByText(/INDEPENDENTLY_VERIFIED：0 条/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "打开补证来源：https://example.com/revision" })).toBeNull();
    expect(detailRequests).toBe(0);
    await fireEvent.click(screen.getByRole("button", { name: "查看完整关系记录 R001" }));
    await screen.findByText(/R001：.*补证读取失败示例/);
    expect(screen.getAllByText(/当前权益比例待核/).length).toBeGreaterThanOrEqual(2);
    await fireEvent.click(screen.getByRole("button", { name: "查看完整关系记录 R001" }));
    await screen.findByText(/正在读取完整关系记录 R001/);
    await fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText(/当前 26–26 \/ 667/);
    expect(spy.mock.calls.some(([input]) => String(input).includes("offset=25"))).toBe(true);
    expect(releaseStaleDetail).not.toBeNull();
    releaseStaleDetail!(response(envelope({ ...catalogData, query: "R001", offset: 0, total: 1 }, "STRUCTURE_VALID")));
    await waitFor(() => { expect(screen.queryByText(/已读取完整关系记录 R001/)).toBeNull(); });
    expect(screen.queryByRole("link", { name: "打开补证来源：https://example.com/revision" })).toBeNull();
    await fireEvent.update(screen.getByRole("combobox", { name: "旧 700 历史用途筛选" }), "PENDING_REVIEW");
    await screen.findByText(/当前 1–1 \/ 667/);
    expect(spy.mock.calls.some(([input]) => String(input).includes("research_use=PENDING_REVIEW"))).toBe(true);

    await fireEvent.update(screen.getByRole("textbox", { name: /按港股代码、港股名称、美股资产代码或关系编号查询/ }), "CVE");
    await fireEvent.click(screen.getByRole("button", { name: "查询资料" }));
    await screen.findByText(/CVE · OWNERSHIP · 原始表行 1/);
    expect(screen.getByText(/盈利与股权价值可影响投资收益/)).toBeTruthy();
    expect(screen.getByText(/以正式盈利和权益变化为触发/)).toBeTruthy();
    expect(screen.getByText(/业务分部抵消；持股变化；市场流动性/)).toBeTruthy();
    expect(screen.getByText(/status=HISTORICAL_ONLY/)).toBeTruthy();
    expect(screen.getByText(/current_observation_candidate=False；audit_only=True/)).toBeTruthy();
    expect(screen.getByText(/事实独立核验 PENDING；预测资格固定为否；预测 UNTESTED；历史 PIT NOT_VALIDATED/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /打开来源：https:\/\/example.com\/primary-evidence/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开来源：https://example.com/second" }).getAttribute("href")).toBe("https://example.com/second");
    expect(screen.queryByRole("link", { name: /javascript:|password/ })).toBeNull();
    expect(screen.getAllByText(/当前权益比例待核/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/州注册冲突限制/)).toBeTruthy();
    expect(screen.getByText(/使用限制 \/ 禁止据此推断：/)).toBeTruthy();
    expect(screen.getByText(/待官方更正索引或解释/)).toBeTruthy();
    expect(screen.getByText(/Delaware正文与IL索引冲突未获解释/)).toBeTruthy();
    expect(screen.queryByText(/声明的未解决导航引用：/)).toBeNull();
    expect(screen.queryByText(/原始未闭合的 failure-check 文本/)).toBeNull();
    expect(screen.queryByRole("link", { name: "打开补证来源：https://example.com/revision" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "查看完整关系记录 R001" }));
    await screen.findByText(/R001：.*关系身份、来源或安全状态不一致/);
    expect(screen.queryByText(/已读取完整关系记录 R001/)).toBeNull();
    expect(screen.queryByRole("link", { name: "打开补证来源：https://example.com/revision" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "查看完整关系记录 R001" }));
    await screen.findByText(/已读取完整关系记录 R001/);
    expect(screen.getByText(/完整 v2r1 有效研究、六层、七字段和来源身份/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开补证来源：https://example.com/revision" })).toBeTruthy();
    expect(screen.getByText(/声明的未解决导航引用：/)).toBeTruthy();
    expect(screen.getByText(/声明的未解决导航引用：/).parentElement?.textContent).toContain("R1");
    expect(screen.getByText(/证据措辞澄清：/)).toBeTruthy();
    expect(screen.getByText(/证据措辞澄清：/).parentElement?.textContent).toContain("仅按披露期解释");
    const parseIssueDetails = screen.getByText(/原始 JSON 解析问题/).parentElement;
    expect(parseIssueDetails?.textContent).toContain("INVALID_JSON_PRESERVED_AS_SOURCE_TEXT");
    expect(parseIssueDetails?.textContent).toContain("原始未闭合的 failure-check 文本");
    await fireEvent.update(screen.getByRole("textbox", { name: /按港股代码、港股名称、美股资产代码或关系编号查询/ }), "R001");
    await fireEvent.click(screen.getByRole("button", { name: "查询资料" }));
    await screen.findByText((_, element) => element?.tagName === "P" &&
      element.textContent?.includes("R001 · 旧 700 历史用途") === true);
    expect(spy.mock.calls.some(([input]) => String(input).includes("q=R001"))).toBe(true);
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
    await fireEvent.update(screen.getByRole("textbox", { name: /按港股代码、港股名称、美股资产代码或关系编号查询/ }), "R700");
    await fireEvent.click(screen.getByRole("button", { name: "查询资料" }));
    await screen.findByText((_, element) => element?.tagName === "P" &&
      element.textContent?.includes("R700 · 旧 700 历史用途") === true);
    expect(screen.getByText(/R700 不在旧 700 历史补证记录中/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "查看完整关系记录 R700" })).toBeNull();
    expect(screen.queryByText(/已读取完整关系记录 R700/)).toBeTruthy();
  });
});
