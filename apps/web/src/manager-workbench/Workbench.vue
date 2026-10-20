<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useWorkbench } from "./useWorkbench";
import { isValidDate } from "./route";
import AnnouncementCandidates from "./AnnouncementCandidates.vue";
import type { HKIndustrySummary, Lane, Phase, PlanVersion, SingleDayMappingPath, SingleDayMappingRow, SingleDayMappingSummary, StockDecision, USFactorSummary, USMappingCatalogRelation } from "./types";
import { projectUSMappingCandidates, projectUSMappingPeerLists, type USPeerListName } from "./us_mapping_stock_lists";
import { LANES, LANE_LABELS, LANE_STATE_LABELS, JOB_STATE_LABELS, PHASE_LABELS,
  showCount as formatCount, showText, gapText } from "./types";
import { conditionLabel, decisionLabel, evidenceLink, firstReason, humanTime, labelForLane,
  laneEntries, laneResultLabel, metricLabel, stockTitle, researchRows, readableReason,
  researchSections, researchRisks, detailReasons, detailRisks, researchCutoff } from "./display";
import "./workbench.css";

const vm = reactive(useWorkbench());
const datePickerValue = computed({
  get: () => isValidDate(vm.dateInput)
    ? `${vm.dateInput.slice(0, 4)}-${vm.dateInput.slice(4, 6)}-${vm.dateInput.slice(6, 8)}`
    : "",
  set: (value: string) => { vm.dateInput = value ? value.replace(/-/g, "") : ""; }
});
function showCount(value: unknown): string {
  return formatCount(typeof value === "number" && Number.isFinite(value) ? value : null);
}
const panels = [
  { key: "stocks", label: "今日名单" },
  { key: "announcements", label: "公告选股" },
  { key: "detail", label: "个股详情" },
  { key: "progress", label: "研究进度" },
  { key: "history", label: "计划历史" },
  { key: "reviews", label: "收盘复盘" },
  { key: "catalog", label: "美股映射资料库" }
] as const;

function changeVersionBySelect(event: Event): void {
  const runId = (event.target as HTMLSelectElement).value;
  const version: PlanVersion | undefined = vm.versions.find(x => x.run_id === runId);
  vm.changeVersion(version?.phase || vm.route.phase, runId);
}
function changePhaseBySelect(event: Event): void {
  vm.changeVersion((event.target as HTMLSelectElement).value as Phase | "");
}
function changeDecisionBySelect(event: Event): void {
  vm.decisionFilter = (event.target as HTMLSelectElement).value as typeof vm.decisionFilter;
  vm.applyFilters();
}
function changeJobPhase(event: Event): void {
  vm.runPhase = (event.target as HTMLSelectElement).value as "MANUAL" | "RETROSPECTIVE";
}
function stockLaneEntries(stock: StockDecision, lane: Lane) {
  return laneEntries(stock, lane);
}
function detailForLane(lane: Lane) {
  return vm.detail?.data?.lane_details?.find(item => item.lane === lane);
}
function factorPaths(row: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(row.factor_paths)
    ? row.factor_paths.filter((path): path is Record<string, unknown> => path !== null && typeof path === "object")
    : [];
}
function supplementalEvidence(path: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(path.supplemental_evidence)
    ? path.supplemental_evidence.filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    : [];
}
function factorPeriod(path: Record<string, unknown>): string {
  return typeof path.fact_effective_from === "string" && typeof path.fact_effective_through === "string"
    ? `${path.fact_effective_from} 至 ${path.fact_effective_through}` : "历史有效期间未知";
}
function industrySummaryText(summary: HKIndustrySummary): string {
  return `港股通范围 ${showCount(summary.scope_count)} 只；身份核验 ${showCount(summary.identity_resolved_count)} 只，身份缺口 ${showCount(summary.identity_gap_count)} 只；有行业分类 ${showCount(summary.classified_count)} 只，已映射到冻结美股主题 ${showCount(summary.mapping_covered_count)} 只，行业已知但未映射 ${showCount(summary.industry_unmapped_count)} 只，分类缺失 ${showCount(summary.classification_missing_count)} 只；待核（UNASSESSED）${showCount(summary.unknown_unique_stock_count)} 只；坏来源行 ${showCount(summary.bad_row_count)} 条；代理收益为正且通过时间门槛的去重候选 ${showCount(summary.triggered_unique_stock_count)} 只。`;
}
function proxyDirectionLabel(value: unknown): string {
  return ({ UPSIDE: "上行代理观察", DOWNSIDE: "下行代理观察", FLAT: "零变动", UNASSESSED: "待核" } as Record<string, string>)[String(value)] || "待核";
}
function proxyReasonLabel(value: unknown): string {
  const code = String(value || "");
  const labels: Record<string, string> = {
    CLASSIFICATION_MISSING: "月度观察范围内没有行业分类",
    CLASSIFICATION_RAW_PROVENANCE_INVALID: "行业分类原始行或响应来源校验缺失",
    INDUSTRY_UNMAPPED_TO_FROZEN_24_PROXY_MAP: "该提供方行业标签尚无已核验的主题映射",
    INDUSTRY_PROXY_THEME_BINDING_INVALID: "行业主题代理绑定无效",
    THEME_PROXY_RETURN_UNASSESSED: "代理收益输入待核",
    THEME_PROXY_OWNER_ROW_MISSING: "缺少代理收益来源行",
    INDUSTRY_THEME_PROXY_MEMBERSHIP_MISMATCH: "代理来源标的与冻结映射不一致",
    INDUSTRY_MAPPING_TYPE_MISMATCH: "行业映射类型不一致",
    THEME_PROXY_RETURN_INVALID: "代理收益格式无效",
    UNASSESSED_IDENTITY: "证券主表身份未核验",
    CLASSIFICATION_ROW_DUPLICATE: "行业来源存在重复记录",
    RETROSPECTIVE_PIT_UNKNOWN: "来源时间不能证明当时可用",
  };
  return labels[code] ? `${labels[code]}（${code}）` : code;
}
function proxyPathReason(path: Record<string, unknown>): string {
  const symbols = Array.isArray(path.proxy_symbols) ? path.proxy_symbols.join("、") : "代理标的未知";
  const raw = typeof path.return_pct === "string" || typeof path.return_pct === "number" ? Number(path.return_pct) : NaN;
  const change = Number.isFinite(raw) ? `${raw > 0 ? "+" : ""}${raw}%` : "收益未知";
  const session = typeof path.source_session === "string" ? path.source_session : "会话未知";
  const conditions = Array.isArray(path.conditions) ? path.conditions.map(proxyReasonLabel).filter(Boolean) : [];
  const reason = conditions.length ? `；待核原因：${conditions.join("、")}` : "";
  return `${showText(path.theme)}（${symbols}）· ${session} 收盘 ${change} · ${proxyDirectionLabel(path.direction)}${reason}`;
}
function directionalStockReason(stock: Record<string, unknown>): string {
  const paths = Array.isArray(stock.proxy_paths)
    ? stock.proxy_paths.filter((path): path is Record<string, unknown> => path !== null && typeof path === "object") : [];
  if (paths.length) return `${showText(stock.source_industry)} → ${paths.map(proxyPathReason).join("；")}`;
  const conditions = Array.isArray(stock.conditions) ? stock.conditions.map(proxyReasonLabel).filter(Boolean) : [];
  return conditions.length ? conditions.join("；") : showText(stock.reason || "行业或代理映射待核");
}
function directionalStocks(key: "upside" | "downside" | "flat" | "unassessed") {
  return vm.day?.data?.us_mapping_summary?.directional_proxy_lists?.lists?.[key] || [];
}
function factorSummaryText(summary: USFactorSummary): string {
  const decisions = summary.factor_decision_counts || {};
  return `固定美股来源 ${showCount(summary.us_source_symbol_count)} 个；已配置代理主题 ${showCount(summary.proxy_source_count)} / ${showCount(summary.expected_proxy_source_count)} 个（核验通过 ${showCount(summary.verified_proxy_source_count)}，未知 ${showCount(summary.unknown_proxy_source_count)}）；目标日港股通范围 ${showCount(summary.eligible_hk_scope_count)} 只；因子唯一港股 ${showCount(summary.unique_factor_stock_count)} 只，路径 ${showCount(summary.factor_path_count)} 条，未知港股 ${showCount(summary.unknown_factor_stock_count)} 只。结果：条件观察 ${showCount(decisions.CONDITIONAL_WATCH)}，未入选 ${showCount(decisions.NOT_SELECTED)}，待核 ${showCount(decisions.UNASSESSED)}。这些数量属于不同范围，不能相加。`;
}
type SingleDayCatalogView = {
  catalog_consumption?: Record<string, unknown>;
  catalog_stock_reconciliation?: Record<string, unknown>;
  manual_quote_scope?: Record<string, unknown>;
  catalog_relation_dispositions?: Record<string, unknown>[];
  catalog_peer_baskets?: Record<string, unknown[]>;
  catalog_candidates?: Record<string, unknown>[];
  sector_proxy_coverage_observations?: Record<string, unknown>[];
  rows?: Record<string, unknown>[];
};
function singleDayCatalogSummary(): SingleDayCatalogView | null {
  const value = vm.day?.data?.us_mapping_summary?.factor_summary?.single_day_mapping;
  return value && typeof value === "object" ? value as SingleDayCatalogView : null;
}
type CatalogStockIdentity = { symbol?: string; name?: string };
function catalogNoRelationStocks(): CatalogStockIdentity[] | null {
  const rows = singleDayCatalogSummary()?.catalog_stock_reconciliation?.no_relation_stocks;
  return Array.isArray(rows) ? rows.filter((row): row is CatalogStockIdentity => row !== null && typeof row === "object") : null;
}
function monthlyPoolExtraSymbols(): string[] | null {
  const symbols = singleDayCatalogSummary()?.catalog_stock_reconciliation?.monthly_pool_not_in_catalog_stock_symbols;
  return Array.isArray(symbols) ? symbols.filter((symbol): symbol is string => typeof symbol === "string") : null;
}
function catalogDispositionRows(): Record<string, unknown>[] {
  const rows = singleDayCatalogSummary()?.catalog_relation_dispositions;
  return Array.isArray(rows) ? rows : [];
}
function singleDayMappingRows(): Record<string, unknown>[] {
  const rows = singleDayCatalogSummary()?.rows;
  return Array.isArray(rows) ? rows : [];
}
function catalogPeerBasketRows(): { symbol: string; basket: Record<string, unknown> }[] {
  const baskets = singleDayCatalogSummary()?.catalog_peer_baskets;
  if (!baskets || typeof baskets !== "object") return [];
  return Object.entries(baskets).flatMap(([symbol, values]) =>
    Array.isArray(values) ? values.map(basket => ({ symbol, basket: basket as Record<string, unknown> })) : []);
}
function singleDaySummary(): SingleDayMappingSummary | null {
  return vm.day?.data?.us_mapping_summary?.factor_summary?.single_day_mapping || null;
}
function fullMappingSectorPolicy(summary: USFactorSummary | null | undefined): string {
  const value = (summary as (USFactorSummary & Record<string, unknown>) | null | undefined)?.full_mapping_sector_policy;
  return typeof value === "string" ? value : "";
}
function singleDayMappingPaths(value: unknown): SingleDayMappingPath[] {
  return Array.isArray(value)
    ? value.filter((path): path is SingleDayMappingPath => path !== null && typeof path === "object")
    : [];
}
const usMappingPeerLists = computed(() => projectUSMappingPeerLists(singleDayCatalogSummary()));
const usMappingCandidateRows = computed(() => projectUSMappingCandidates(singleDayCatalogSummary()));
const usMappingCandidateCountLabel = computed(() => {
  if (!Array.isArray(singleDayCatalogSummary()?.catalog_candidates)) {
    return "研究候选数未知（不等于正式入选）";
  }
  return `研究候选 ${showCount(usMappingCandidateRows.value.length)} 只（不等于正式入选）`;
});
const sectorProxyCoverageRows = computed(() => singleDayCatalogSummary()?.sector_proxy_coverage_observations || []);
function peerRows(direction: USPeerListName) {
  return usMappingPeerLists.value[direction];
}
function candidateRelations(candidate: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(candidate.relations)
    ? candidate.relations.filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    : [];
}
function candidateList(value: unknown): string {
  return Array.isArray(value) ? value.map(showText).join("、") : showText(value);
}
function singleDayRows(decision: SingleDayMappingRow["decision"]): SingleDayMappingRow[] {
  return (singleDaySummary()?.rows || []).filter(row => row.decision === decision);
}
function singleDaySmallRows(): SingleDayMappingRow[] {
  return singleDayRows("OBSERVATION").filter(row => row.mapping_grade === "A" || row.mapping_grade === "B");
}
function singleDayCRows(): SingleDayMappingRow[] {
  return singleDayRows("OBSERVATION").filter(row => row.mapping_grade === "C");
}
function singleDayPathText(path: SingleDayMappingPath): string {
  const proxy = path.proxy_symbols?.length ? path.proxy_symbols.join("+") : path.proxy_symbol || path.us_symbol || "代理未知";
  const value = path.signed_return_pct === null || path.signed_return_pct === undefined
    ? "收益未知" : `${Number(path.signed_return_pct) > 0 ? "+" : ""}${path.signed_return_pct}%`;
  const label = path.relation_type || path.source_industry || path.source_type || "映射类型未知";
  const rationale = [path.research_basis, path.reason, ...(path.gaps || []),
    ...(path.relation_limitations || [])].filter(Boolean).join("；");
  return `${path.grade} · ${label} · ${proxy} ${value} · ${path.status}${rationale ? ` · ${rationale}` : ""}`;
}
function singleDayRowReason(row: SingleDayMappingRow): string {
  return [row.reason, ...(row.reasons || [])].filter((item, index, all) => item && all.indexOf(item) === index).join("；") || "原因未知";
}
function singleDayCount(decision: SingleDayMappingRow["decision"] | "SMALL_MOVE_WATCH" | "C_WATCH"): number | null {
  return singleDaySummary()?.counts?.[decision] ?? null;
}
function catalogRelations(rows: USMappingCatalogRelation[]): USMappingCatalogRelation[] {
  return rows.map(row => vm.catalogRelationDetails[row.relation_id]?.data || row);
}
function sourceValue(value: unknown): string {
  return value === "" || value === null || value === undefined ? "来源未提供" : showText(value);
}
function sourceUrls(value: unknown): string[] {
  let values: unknown = value;
  if (typeof value === "string") {
    try { values = JSON.parse(value); } catch { values = value.split(/\s+/); }
  }
  if (!Array.isArray(values)) values = [values];
  return [...new Set((values as unknown[]).filter((item): item is string => {
    if (typeof item !== "string" || /[\s<>"']/.test(item)) return false;
    try { const url = new URL(item); return ["http:", "https:"].includes(url.protocol) && !!url.hostname && !url.username && !url.password; }
    catch { return false; }
  }))];
}
function researchUseLabel(value: string): string {
  return ({ PENDING_REVIEW: "待核 / 待补证", CONDITIONAL_OBSERVATION: "条件观察（研究设计）",
    BACKGROUND_HISTORICAL: "背景 / 历史", EXCLUDED_CURRENT: "排除现行用途" } as Record<string, string>)[value] || value;
}
function revisionAssessments(value: unknown): [string, unknown][] {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
}
</script>

<template>
  <main class="mwb-shell">
    <header class="mwb-hero">
      <div>
        <p class="mwb-eyebrow">V4 · HK CONNECT / RESEARCH ONLY</p>
        <h1>经理研究工作台</h1>
        <p class="mwb-subtitle">先看股票、依据与变化，再看执行、历史和复盘。A股维持原独立入口。</p>
      </div>
      <div class="mwb-head-meta">
        <span class="mwb-safety">只读研究展示 · 不发单</span>
        <span>{{ vm.readMode }}</span>
      </div>
    </header>

    <section class="mwb-panel mwb-toolbar" aria-label="日期和版本导航">
      <form class="mwb-date" @submit.prevent="vm.changeDate">
        <label for="mwb-date">目标港股日</label>
        <input id="mwb-date" v-model="datePickerValue" type="date" required aria-describedby="mwb-date-hint" />
        <button type="submit">切换日期</button>
        <small id="mwb-date-hint">日期是计划目标日，不是公告或行情来源日</small>
      </form>
      <div class="mwb-selectors">
        <label for="mwb-phase">阶段</label>
        <select id="mwb-phase" :value="vm.route.phase" @change="changePhaseBySelect">
          <option value="">当日最新可用</option>
          <option v-for="phase in (Object.keys(PHASE_LABELS) as Phase[])" :key="phase" :value="phase">
            {{ PHASE_LABELS[phase] }}
          </option>
        </select>
        <label for="mwb-version">计划版本</label>
        <select id="mwb-version" :value="vm.route.runId" @change="changeVersionBySelect">
          <option value="">阶段最新保存版</option>
          <option v-if="vm.route.runId && !vm.versions.some(x => x.run_id === vm.route.runId)"
            :value="vm.route.runId">{{ vm.route.runId }}（固定）</option>
          <option v-for="version in vm.versions" :key="version.run_id" :value="version.run_id">
            {{ PHASE_LABELS[version.phase] }} / {{ version.run_id }}
          </option>
        </select>
        <button type="button" class="mwb-quiet" :disabled="vm.dayLoading || !vm.valid"
          @click="vm.loadDay(true)">刷新读取</button>
      </div>
    </section>

    <p v-if="vm.route.error" class="mwb-alert" role="alert">{{ vm.route.error }}</p>
    <p v-if="vm.hasStale" class="mwb-alert" role="status">
      上次成功读取版（非当前响应）：日期 {{ vm.selectedDate }}，run_id {{ vm.selectedRunId }}。
      本次刷新失败，旧结果仅供对照。
    </p>
    <p v-if="vm.dayError" class="mwb-alert" role="alert">{{ vm.dayError }}</p>

    <section class="mwb-metadata mwb-panel" aria-label="当前计划身份">
      <div><span>当前目标日</span><strong>{{ vm.selectedDate }}</strong></div>
      <div><span>阶段 / 来源</span><strong>{{ vm.snapshot ? PHASE_LABELS[vm.snapshot.context.phase] : "未加载" }}</strong></div>
      <div><span>研究截止</span><strong>{{ humanTime(researchCutoff(vm.snapshot?.context)) }}</strong></div>
      <div><span>实际生成</span><strong>{{ humanTime(vm.snapshot?.generated_at) }}</strong></div>
      <div><span>读取版本</span><strong class="mwb-id">{{ vm.selectedRunId || "无已保存版本" }}</strong></div>
      <div><span>响应状态</span><strong>{{ vm.dayLoading ? "读取中" : (vm.day?.state || "未读取") }}</strong></div>
      <div v-if="vm.snapshot?.context.phase === 'RETROSPECTIVE'" class="mwb-retro">
        RETROSPECTIVE · 事后回看，不能作为当时盘前依据
      </div>
    </section>

    <nav class="mwb-tabs" role="tablist" aria-label="工作台视图">
      <button v-for="tab in panels" :key="tab.key" type="button" role="tab"
        :aria-selected="vm.panel === tab.key" :class="{ active: vm.panel === tab.key }"
        @click="vm.showPanel(tab.key)">{{ tab.label }}</button>
    </nav>

    <AnnouncementCandidates v-if="vm.panel === 'announcements'" :target-date="vm.route.date" />

    <section v-if="vm.panel === 'stocks'" class="mwb-panel" aria-label="今日研究名单">
      <div class="mwb-heading">
        <div><h2 v-if="vm.laneFilter === 'US_MAPPING' && singleDaySummary()">US {{ singleDaySummary()?.source_session || '日期未知' }} → HK {{ singleDaySummary()?.target_date || '日期未知' }} · 单日映射推荐 / 下跌风险</h2><h2 v-else>{{ LANE_LABELS[vm.laneFilter] }} · {{ vm.decisionFilter ? decisionLabel(vm.decisionFilter) : '独立港股推荐' }}</h2><p v-if="vm.laneFilter === 'US_MAPPING' && singleDaySummary()">按固定 A/B/C 主路径展示全量月度观察池；单日代理变化仅为研究观察，目标日资格、历史 PIT 与效果未验证。</p><p v-else>美股映射与超跌是独立推荐；各自采用该路径已保存结论，同股可出现在两处。</p></div>
        <p v-if="vm.dayLoading" role="status">正在读取保存的研究版本…</p>
      </div>
      <nav class="mwb-tabs" aria-label="独立推荐来源">
        <button v-for="lane in (['US_MAPPING', 'OVERSOLD'] as const)" :key="lane" type="button"
          :class="{ active: vm.laneFilter === lane }" :aria-pressed="vm.laneFilter === lane" @click="vm.switchLane(lane)">
          {{ LANE_LABELS[lane] }}推荐 · {{ lane === 'US_MAPPING' && singleDaySummary() ? `固定映射受益判定 ${showCount(singleDayCount('BENEFIT'))} / 固定映射风险判定 ${showCount(singleDayCount('RISK'))}` : `严格入选 ${showCount(vm.day?.data?.recommendation_counts?.[lane]?.selected)} / 条件观察 ${showCount(vm.day?.data?.recommendation_counts?.[lane]?.watch)}` }}
        </button>
      </nav>
      <p v-if="vm.laneFilter === 'US_MAPPING' && !singleDaySummary()" class="mwb-muted">
        当前保存版本没有单日映射结果；不能从旧保存版本推断本次受益或风险名单。
      </p>

      <section v-if="vm.laneFilter === 'US_MAPPING' && singleDaySummary()" class="mwb-research-section" aria-label="单日映射推荐与下跌风险">
        <h3>单日映射推荐 / 下跌风险 · {{ singleDaySummary()?.state }}</h3>
        <p>月度观察池 {{ showCount(singleDaySummary()?.monthly_observed_scope_count) }} 只 · US 来源会话 {{ singleDaySummary()?.source_session || '未知' }} · HK 行情信号会话 {{ singleDaySummary()?.price_session || '未知' }} · HK 目标日 {{ singleDaySummary()?.target_date || '未知' }}。代理变化是固定映射下的同向传导研究假设，效果未验证；正式港股通资格 CANNOT_CONFIRM，历史 PIT 未验证。</p>
        <p>RESEARCH ONLY · 不构成 BUY。候选按当前支持、DATED 弱同行、待核排序；组内先列有正向来源且无反向来源的标的，再列正负分歧、仅负向和零变动 / 未知。正向来源涨幅只作来源强弱并列排序，不是港股收益预测。</p>
        <p v-for="proxy in sectorProxyCoverageRows" :key="String(proxy.source_symbol)">
          代理覆盖 {{ showText(proxy.source_symbol) }} · {{ showText(proxy.source_session) }} · 报价 {{ showText(proxy.quote_status) }}
          {{ proxy.source_return_pct == null ? '涨跌未知' : `${proxy.source_return_pct}%` }} · 映射 {{ showText(proxy.mapping_status) }}
          <span v-if="proxy.mapping_status === 'MAPPING_PENDING'">（映射待补；未构造关系边）</span> · {{ showText(proxy.quote_gap || '') }}
        </p>
        <p class="mwb-muted">{{ usMappingCandidateCountLabel }}</p>
        <div class="mwb-table-wrap"><table class="mwb-table" aria-label="港股去重研究候选表">
          <thead><tr><th>港股 / 观察池</th><th>来源资格 / 排序组</th><th>方向证据 / 美股来源强弱</th><th>风险标记</th><th>关系证据</th></tr></thead>
          <tbody><tr v-for="candidate in usMappingCandidateRows" :key="String(candidate.symbol)">
            <td><strong>{{ showText(candidate.symbol) }} {{ showText(candidate.name) }}</strong><small>{{ candidate.in_monthly_pool ? '在月度观察池' : '目录池外观察' }}</small></td>
            <td>{{ showText(candidate.qualification) }}<small>{{ candidateList(candidate.qualification_groups) }}</small></td>
            <td>{{ showText(candidate.direction_group) }}<small>正向美股来源涨幅 {{ candidate.positive_source_move_strength_pct == null ? '未知' : `${candidate.positive_source_move_strength_pct}%` }}</small></td>
            <td>{{ candidateList(candidate.risk_markers) || '无已核验负向来源；报价或范围仍可能待核' }}</td>
            <td><details><summary>查看 {{ candidateRelations(candidate).length }} 条</summary>
              <ul><li v-for="relation in candidateRelations(candidate)" :key="String(relation.catalog_relation_id)">
                <strong>{{ showText(relation.us_symbol) }} · {{ showText(relation.catalog_candidate_qualification) }}</strong>
                <span>来源会话 {{ showText(relation.source_session) }} · {{ showText(relation.quote_status) }} · 美股来源涨跌 {{ relation.us_source_return_pct == null ? '未知' : `${relation.us_source_return_pct}%` }}</span>
                <span>{{ showText(relation.catalog_relation_id) }} · {{ showText(relation.catalog_disposition) }} · {{ showText(relation.catalog_disposition_reason) }}</span>
                <span>分类 {{ showText(relation.catalog_segment || relation.catalog_research_industry) }} · 事实 {{ showText(relation.catalog_fact) }} · 机制 {{ showText(relation.catalog_mechanism) }}</span>
                <span>风险 {{ showText(relation.catalog_failure) }} · 复核条件 {{ showText(relation.catalog_condition) }}</span>
              </li></ul>
            </details></td>
          </tr></tbody>
        </table></div>
        <p v-if="!usMappingCandidateRows.length" class="mwb-muted">当前已核目录证据没有可展示的港股业务同行候选；不能把缺失关系补成映射边。</p>
        <details><summary>旧版方向列表与固定路径归档</summary>
        <p>固定 A/B/C 映射、固定 primary 与 sign；不择当日最强路径。A/B primary ≥ +1% 为潜在受益，≤ -1% 为下跌风险；小幅变化观察；C 与未映射单独展示，不升级为 A/B。映射政策 {{ singleDaySummary()?.mapping_policy_version }} · SHA {{ singleDaySummary()?.mapping_policy_sha256 }}。</p>
        <p>严格 V1 门槛暂缓，未执行：MA20、5日收益、20日均成交额、Top10 与每主题3只限制均未运行，也未用于截断单日完整名单。</p>
        <section class="mwb-directional-lists" aria-label="已采用美股同行来源观察名单">
          <h3>已采用美股同行来源观察 · {{ showCount(usMappingPeerLists.acceptedRelationCount) }} 条关系</h3>
          <p>来源会话 {{ usMappingPeerLists.sourceSession || singleDaySummary()?.source_session || '未知' }} · 港股目标日 {{ usMappingPeerLists.targetDate || singleDaySummary()?.target_date || '未知' }} · 正向 {{ showCount(usMappingPeerLists.positive.length) }} 条 · 负向 {{ showCount(usMappingPeerLists.negative.length) }} 条 · 零变动 {{ showCount(usMappingPeerLists.flat.length) }} 条 · 待核 {{ showCount(usMappingPeerLists.unknown.length) }} 条 · 同股正负并存 {{ showCount(usMappingPeerLists.mixedStockCount) }} 只。</p>
          <p>下表按已保存且处置为 ADOPTED_BUSINESS_PEER 的关系逐条展示。涨跌仅描述对应美股来源会话的报价方向，不代表港股预期收益、因果结论或 BUY；正式港股通资格 {{ singleDaySummary()?.formal_target_eligibility || 'CANNOT_CONFIRM' }}，历史 PIT 未验证。</p>
          <article class="mwb-direction-card is-upside" aria-label="正向美股来源观察名单">
            <h4>正向美股来源观察 · {{ showCount(peerRows('positive').length) }} 条关系</h4>
            <div v-if="peerRows('positive').length" class="mwb-table-wrap"><table class="mwb-table">
              <thead><tr><th>港股</th><th>美股来源报价</th><th>同行组 / 分类</th><th>映射依据（事实 / 机制）</th><th>风险 / 复核条件</th><th>港股关系方向状态</th></tr></thead>
              <tbody><tr v-for="observation in peerRows('positive')" :key="observation.id">
                <td><strong>{{ observation.hkSymbol }} {{ observation.hkName }}</strong><small>{{ observation.relationId }} · {{ observation.relationType }}</small></td>
                <td><strong>{{ observation.usSymbol }}</strong><span>{{ observation.sourceSession }} 收盘 {{ observation.returnLabel }}</span><small>{{ observation.quoteStatus }}</small></td>
                <td>{{ observation.peerBucket }}<small>{{ observation.catalogSegment || '分类未知' }}</small></td>
                <td><span>事实：{{ observation.catalogFact }}</span><span>机制：{{ observation.catalogMechanism }}</span></td>
                <td><span>风险：{{ observation.catalogFailure }}</span><span>复核条件：{{ observation.catalogCondition }}</span></td>
                <td>{{ observation.stockDirectionLabel }}<small v-if="observation.hasMixedStockDirection">同一港股的正负路径均保留，不合并打分</small></td>
              </tr></tbody>
            </table></div>
            <p v-else class="mwb-muted">当前筛选下没有已核验的正向美股同行来源报价。</p>
          </article>
          <article class="mwb-direction-card is-downside" aria-label="负向美股来源观察名单">
            <h4>负向美股来源观察 · {{ showCount(peerRows('negative').length) }} 条关系</h4>
            <div v-if="peerRows('negative').length" class="mwb-table-wrap"><table class="mwb-table">
              <thead><tr><th>港股</th><th>美股来源报价</th><th>同行组 / 分类</th><th>映射依据（事实 / 机制）</th><th>风险 / 复核条件</th><th>港股关系方向状态</th></tr></thead>
              <tbody><tr v-for="observation in peerRows('negative')" :key="observation.id">
                <td><strong>{{ observation.hkSymbol }} {{ observation.hkName }}</strong><small>{{ observation.relationId }} · {{ observation.relationType }}</small></td>
                <td><strong>{{ observation.usSymbol }}</strong><span>{{ observation.sourceSession }} 收盘 {{ observation.returnLabel }}</span><small>{{ observation.quoteStatus }}</small></td>
                <td>{{ observation.peerBucket }}<small>{{ observation.catalogSegment || '分类未知' }}</small></td>
                <td><span>事实：{{ observation.catalogFact }}</span><span>机制：{{ observation.catalogMechanism }}</span></td>
                <td><span>风险：{{ observation.catalogFailure }}</span><span>复核条件：{{ observation.catalogCondition }}</span></td>
                <td>{{ observation.stockDirectionLabel }}<small v-if="observation.hasMixedStockDirection">同一港股的正负路径均保留，不合并打分</small></td>
              </tr></tbody>
            </table></div>
            <p v-else class="mwb-muted">当前筛选下没有已核验的负向美股同行来源报价。</p>
          </article>
          <details class="mwb-direction-secondary"><summary>零变动美股同行观察 · {{ showCount(peerRows('flat').length) }} 条</summary>
            <div v-if="peerRows('flat').length" class="mwb-table-wrap"><table class="mwb-table"><thead><tr><th>港股 / 关系</th><th>美股来源报价</th><th>映射依据</th><th>风险 / 复核条件</th></tr></thead>
              <tbody><tr v-for="observation in peerRows('flat')" :key="observation.id"><td>{{ observation.hkSymbol }} {{ observation.hkName }} · {{ observation.relationId }}</td><td>{{ observation.usSymbol }} · {{ observation.sourceSession }} · {{ observation.returnLabel }}</td><td>事实：{{ observation.catalogFact }}；机制：{{ observation.catalogMechanism }}</td><td>风险：{{ observation.catalogFailure }}；复核条件：{{ observation.catalogCondition }}</td></tr></tbody>
            </table></div>
            <p v-else class="mwb-muted">当前筛选下没有零变动关系。</p>
          </details>
          <details class="mwb-direction-secondary"><summary>来源报价 / 日期待核 · {{ showCount(peerRows('unknown').length) }} 条</summary>
            <div v-if="peerRows('unknown').length" class="mwb-table-wrap"><table class="mwb-table"><thead><tr><th>港股 / 关系</th><th>美股来源报价</th><th>待核原因</th><th>映射依据</th><th>风险 / 复核条件</th></tr></thead>
              <tbody><tr v-for="observation in peerRows('unknown')" :key="observation.id"><td>{{ observation.hkSymbol }} {{ observation.hkName }} · {{ observation.relationId }}</td><td>{{ observation.usSymbol }} · {{ observation.sourceSession }} · {{ observation.returnLabel }}</td><td>{{ observation.statusDetail }}</td><td>事实：{{ observation.catalogFact }}；机制：{{ observation.catalogMechanism }}</td><td>风险：{{ observation.catalogFailure }}；复核条件：{{ observation.catalogCondition }}</td></tr></tbody>
            </table></div>
            <p v-else class="mwb-muted">当前筛选下没有来源待核关系。</p>
          </details>
        </section>
        <p v-if="singleDaySummary()?.industry_source_date || singleDaySummary()?.industry_source_status">行业来源 {{ singleDaySummary()?.industry_source_status || '未知' }} · 观测日 {{ singleDaySummary()?.industry_source_date || '未知' }} · SHA {{ singleDaySummary()?.industry_source_sha256 || '未知' }}。</p>
        <p v-if="singleDaySummary()?.gaps?.length">映射缺口：{{ singleDaySummary()?.gaps.join('、') }}</p>
        <details open><summary>固定 A/B/C 规则分类：潜在受益判定 · {{ showCount(singleDayCount('BENEFIT')) }} 只</summary>
          <ul><li v-for="stock in singleDayRows('BENEFIT')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · {{ stock.mapping_grade }}</strong><p>主路径 {{ stock.primary_proxy || stock.primary_us_symbol }} · {{ stock.primary_signed_return_pct }}% · {{ stock.primary_relation_type || stock.source_industry || '固定映射' }}；原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        <details open><summary>固定 A/B/C 规则分类：下跌风险判定 · {{ showCount(singleDayCount('RISK')) }} 只</summary>
          <ul><li v-for="stock in singleDayRows('RISK')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · {{ stock.mapping_grade }}</strong><p>主路径 {{ stock.primary_proxy || stock.primary_us_symbol }} · {{ stock.primary_signed_return_pct }}% · {{ stock.primary_relation_type || stock.source_industry || '固定映射' }}；原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        <details><summary>方向冲突 · {{ showCount(singleDayCount('CONFLICT')) }} 只</summary>
          <ul><li v-for="stock in singleDayRows('CONFLICT')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · 主路径 {{ stock.primary_proxy || stock.primary_us_symbol }} {{ stock.primary_signed_return_pct }}%</strong><p>路径保留，不择最强；原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        <details><summary>A/B 小幅观察（绝对值 &lt;1%）· {{ singleDaySmallRows().length }} 只</summary>
          <ul><li v-for="stock in singleDaySmallRows()" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · {{ stock.mapping_grade }}</strong><p>主路径 {{ stock.primary_proxy || stock.primary_us_symbol }} · {{ stock.primary_signed_return_pct }}% · 原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        <details><summary>C 级观察（不升级为 A/B）· {{ singleDayCRows().length }} 只</summary>
          <ul><li v-for="stock in singleDayCRows()" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · C</strong><p>{{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        <details><summary>待核 · {{ showCount(singleDayCount('UNASSESSED')) }} 只</summary>
          <ul><li v-for="stock in singleDayRows('UNASSESSED')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · {{ stock.mapping_grade || 'UNASSESSED' }}</strong><p>{{ stock.source_industry || '行业分类缺失' }}；原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') || '无已固定 A/B/C 路径' }}</small></li></ul>
        </details>
        <details><summary>未映射 · {{ showCount(singleDayCount('UNMAPPED')) }} 只</summary>
          <ul><li v-for="stock in singleDayRows('UNMAPPED')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · 未映射</strong><p>{{ stock.source_industry || '行业分类缺失' }}；原因 {{ singleDayRowReason(stock) }}</p><small>{{ stock.mapping_paths.map(singleDayPathText).join('；') || '无已固定 A/B/C 路径' }}</small></li></ul>
        </details>
        <details v-if="singleDaySummary()?.outside_pool_observations?.length"><summary>月度观察池外关系 · 仅观察 {{ singleDaySummary()?.outside_pool_observations.length }} 只</summary>
          <ul><li v-for="stock in singleDaySummary()?.outside_pool_observations" :key="String(stock.symbol)"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }} · 池外观察</strong><p>不计入698只月度观察池推荐；原因 {{ stock.reason }}</p><small>{{ singleDayMappingPaths(stock.mapping_paths).map(singleDayPathText).join('；') }}</small></li></ul>
        </details>
        </details>
      </section>

      <section v-if="vm.laneFilter === 'US_MAPPING' && !singleDaySummary() && vm.day?.data?.us_mapping_summary?.factor_summary?.industry_summary"
        class="mwb-research-section" aria-label="港股行业宽召回股票漏斗">
        <h3>港股发行人行业 × 美股主题 · 独立宽召回漏斗</h3>
        <p>{{ industrySummaryText(vm.day.data.us_mapping_summary.factor_summary.industry_summary) }}</p>
        <p>分类来源状态 {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.source_status }}；source_asof {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.source_asof || 'UNKNOWN' }}（{{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.source_asof_status || 'UNKNOWN' }}）；实际采集 {{ humanTime(vm.day.data.us_mapping_summary.factor_summary.industry_summary.captured_at) }}；时间状态 {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.temporal_status || 'CANNOT_CONFIRM' }}。历史 PIT 未验证。</p>
        <p>安全主表 {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.security_master_owner || '未知' }} · 会话 {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.security_master_source_date || '未知' }} · 可得 {{ humanTime(vm.day.data.us_mapping_summary.factor_summary.industry_summary.security_master_available_at) }} · SHA {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.security_master_artifact_sha256 || '未知' }}；身份缺口 {{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.identity_gap || '无' }}。</p>
        <p v-if="vm.day.data.us_mapping_summary.factor_summary.industry_summary.source_gap">分类输入缺口：{{ vm.day.data.us_mapping_summary.factor_summary.industry_summary.source_gap }}</p>
        <p>这是按股票去重的行业候选覆盖；待核统计按候选股票代表结论计算，来源记录计数仍按保存的来源研究行计算。</p>
      </section>



      <section v-if="vm.laneFilter === 'US_MAPPING' && !singleDaySummary() && vm.day?.data?.us_mapping_summary?.directional_proxy_lists"
        class="mwb-directional-lists" aria-label="港股行业代理方向观察名单">
        <h3>月度观察港股 × 美股收盘代理方向</h3>
        <p>港股范围 {{ showCount(vm.day.data.us_mapping_summary.directional_proxy_lists.monthly_observed_scope_count) }} 只；美股会话 {{ vm.day.data.us_mapping_summary.directional_proxy_lists.source_session || '未知' }}；月度成员来源日 {{ vm.day.data.us_mapping_summary.directional_proxy_lists.monthly_research_source_date || '未知' }}。目标日资格 {{ vm.day.data.us_mapping_summary.directional_proxy_lists.formal_target_eligibility || 'CANNOT_CONFIRM' }}，历史 PIT 未验证。这是代理当日共振观察，不是价格预测、因果结论或 BUY。</p>
        <p>全量名单取自保存版本的完整 US_MAPPING 行，不受当前推荐分页、筛选或首页 50 行限制。上/下行列表只按已核验的代理收益 &gt; 0 / &lt; 0 生成；零变动与待核单独列示。{{ vm.day.data.us_mapping_summary.directional_proxy_lists.mixed_stock_count || 0 }} 只同时出现相反方向路径并分别列入两边。</p>
        <div class="mwb-direction-grid">
          <article class="mwb-direction-card is-upside" aria-label="上行代理观察名单">
            <h4>上行代理观察 · 已核验收益 &gt; 0 · {{ showCount(vm.day.data.us_mapping_summary.directional_proxy_lists.upside_stock_count) }} 只</h4>
            <ul v-if="directionalStocks('upside').length">
              <li v-for="stock in directionalStocks('upside')" :key="stock.symbol">
                <strong>{{ stock.symbol }} {{ stock.name || '名称未知' }}</strong>
                <p>{{ directionalStockReason(stock) }}</p>
                <small v-if="String(stock.direction_state || '').includes('MIXED')">同一港股存在相反的已核验代理路径；分别展示，不合并打分。</small>
              </li>
            </ul>
            <p v-else class="mwb-muted">本版本没有可确认的正向代理路径。</p>
          </article>
          <article class="mwb-direction-card is-downside" aria-label="下行代理观察名单">
            <h4>下行风险观察 · 已核验收益 &lt; 0 · {{ showCount(vm.day.data.us_mapping_summary.directional_proxy_lists.downside_stock_count) }} 只</h4>
            <ul v-if="directionalStocks('downside').length">
              <li v-for="stock in directionalStocks('downside')" :key="stock.symbol">
                <strong>{{ stock.symbol }} {{ stock.name || '名称未知' }}</strong>
                <p>{{ directionalStockReason(stock) }}</p>
                <small v-if="String(stock.direction_state || '').includes('MIXED')">同一港股存在相反的已核验代理路径；分别展示，不合并打分。</small>
              </li>
            </ul>
            <p v-else class="mwb-muted">本版本没有可确认的负向代理路径；未入选不代表下行。</p>
          </article>
        </div>
        <details class="mwb-direction-secondary">
          <summary>零变动代理路径 · {{ showCount(vm.day.data.us_mapping_summary.directional_proxy_lists.flat_stock_count) }} 只</summary>
          <ul><li v-for="stock in directionalStocks('flat')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }}</strong><p>{{ directionalStockReason(stock) }}</p></li></ul>
        </details>
        <details class="mwb-direction-secondary">
          <summary>行业/代理/身份待核 · {{ showCount(vm.day.data.us_mapping_summary.directional_proxy_lists.unassessed_stock_count) }} 只</summary>
          <ul><li v-for="stock in directionalStocks('unassessed')" :key="stock.symbol"><strong>{{ stock.symbol }} {{ stock.name || '名称未知' }}</strong><p>{{ directionalStockReason(stock) }}</p></li></ul>
        </details>
      </section>

      <details v-if="vm.laneFilter === 'US_MAPPING' && singleDaySummary()"><summary>旧版映射计数与来源档案</summary>
      <div class="mwb-counts" aria-label="单日映射推荐与风险分类计数">
        <div><strong>{{ showCount(singleDayCount('BENEFIT')) }}</strong><span>固定映射受益判定</span></div>
        <div><strong>{{ showCount(singleDayCount('RISK')) }}</strong><span>固定映射风险判定</span></div>
        <div><strong>{{ showCount(singleDayCount('CONFLICT')) }}</strong><span>方向冲突</span></div>
        <div><strong>{{ showCount(singleDayCount('SMALL_MOVE_WATCH')) }}</strong><span>A/B 小幅观察</span></div>
        <div><strong>{{ showCount(singleDayCount('C_WATCH')) }}</strong><span>C 级观察</span></div>
        <div><strong>{{ showCount(singleDayCount('UNMAPPED')) }}</strong><span>未映射</span></div>
        <div><strong>{{ showCount(singleDayCount('UNASSESSED')) }}</strong><span>待核</span></div>
      </div>
      <p v-if="vm.day?.data?.recommendation_projection" class="mwb-muted">本路径保存 {{ vm.day.data.recommendation_projection.row_count }} 条来源研究记录（计数单位：研究记录）；
        {{ vm.day.data.recommendation_projection.hk_relation_row_count }} 条含港股关系记录，涉及 {{ vm.day.data.us_mapping_summary?.mapped_hk_count ?? '未知' }} 只港股；
        全路径去重港股候选池共 {{ vm.day.data.recommendation_projection.candidate_stock_count ?? vm.day.data.recommendation_projection.distinct_hk_count }} 只。
        US_MAPPING 分类计数按去重港股候选股票计算，不受分页影响；默认推荐仅含严格入选和条件观察。无港股关系的来源缺口在下方单独查看。</p>
      <p v-if="vm.laneFilter === 'US_MAPPING' && vm.day?.data?.recommendation_projection?.source_decision_counts" class="mwb-muted">
        美股映射来源记录分类（按行计，不含港股行业候选和目录）：严格入选 {{ showCount(vm.day.data.recommendation_projection.source_decision_counts.selected) }}、
        条件观察 {{ showCount(vm.day.data.recommendation_projection.source_decision_counts.watch) }}、
        待评估 {{ showCount(vm.day.data.recommendation_projection.source_decision_counts.unassessed) }}、
        仅观察 {{ showCount(vm.day.data.recommendation_projection.source_decision_counts.observation_only) }}、
        未入选 {{ showCount(vm.day.data.recommendation_projection.source_decision_counts.not_selected) }}。</p>
      </details>
      <div v-if="!singleDaySummary() && vm.counts" class="mwb-counts" :aria-label="vm.laneFilter === 'US_MAPPING' ? '去重港股候选股票分类计数' : '本路径完整研究记录分类计数'">
        <div><strong>{{ showCount(vm.counts.selected) }}</strong><span>严格入选</span></div>
        <div><strong>{{ showCount(vm.counts.watch) }}</strong><span>条件观察</span></div>
        <div><strong>{{ showCount(vm.counts.unassessed) }}</strong><span>待评估</span></div>
        <div><strong>{{ showCount(vm.counts.observation_only) }}</strong><span>仅观察</span></div>
        <div><strong>{{ showCount(vm.counts.not_selected) }}</strong><span>未入选</span></div>
      </div>
      <p v-else-if="!singleDaySummary()" class="mwb-muted">完整分类计数未知（无已保存计数，不能当作 0）。</p>

      <details v-if="vm.day?.data?.us_mapping_summary"><summary>旧版美股映射汇总与关系档案</summary>
      <section class="mwb-panel" aria-label="本版本美股映射">
        <h3>本版本美股映射 · 独立保存结论</h3>
        <p>美股来源标的 {{ vm.day.data.us_mapping_summary.source_symbol_count }} 个，候选来源记录 {{ vm.day.data.us_mapping_summary.source_row_count }} 条；
          候选港股关系 {{ vm.day.data.us_mapping_summary.relation_row_count }} 条，涉及 {{ vm.day.data.us_mapping_summary.mapped_hk_count }} 只港股。</p>
        <p v-if="vm.day.data.us_mapping_summary.catalog_summary">
          全量关系目录 {{ vm.day.data.us_mapping_summary.catalog_summary.displayed_relation_count ?? vm.day.data.us_mapping_summary.catalog_summary.relation_count ?? '未知' }} 条 / {{ vm.day.data.us_mapping_summary.catalog_summary.stock_count ?? '未知' }} 只，目录状态 {{ vm.day.data.us_mapping_summary.catalog_summary.state || 'CANNOT_CONFIRM' }}；全量逐关系消费见下方，仍独立于普通美股候选计数与合并结论。</p>
        <p>按美股来源标的计：严格入选 {{ vm.day.data.us_mapping_summary.source_decision_counts.SELECTED ?? '未知' }}，
          条件观察 {{ vm.day.data.us_mapping_summary.source_decision_counts.CONDITIONAL_WATCH ?? '未知' }}，
          未入选 {{ vm.day.data.us_mapping_summary.source_decision_counts.NOT_SELECTED ?? '未知' }}，
          待核 {{ vm.day.data.us_mapping_summary.source_decision_counts.UNASSESSED ?? '未知' }}。
          美股标的数、研究记录数和港股数是不同计量单位；以上只属于美股映射。</p>
        <template v-if="vm.day.data.us_mapping_summary.run_contract">
          <p>日常输入合同 {{ vm.day.data.us_mapping_summary.run_contract.state || 'CANNOT_CONFIRM' }} · 模式 {{ vm.day.data.us_mapping_summary.run_contract.mode || '未知' }} · 港股目标日 {{ vm.day.data.us_mapping_summary.run_contract.target_hk_date || '未知' }} · 美股来源会话 {{ vm.day.data.us_mapping_summary.run_contract.us_source_session || '未知' }} · 截止 {{ humanTime(vm.day.data.us_mapping_summary.run_contract.cutoff || null) }}。</p>
          <p>美股输入 {{ vm.day.data.us_mapping_summary.run_contract.owners?.quote?.owner || '未知' }} · 可得 {{ humanTime(vm.day.data.us_mapping_summary.run_contract.owners?.quote?.available_at || null) }} · SHA {{ vm.day.data.us_mapping_summary.run_contract.owners?.quote?.artifact_sha256?.slice(0, 12) || '未知' }}；
            Universe {{ vm.day.data.us_mapping_summary.run_contract.universe?.version || '未知' }}（{{ vm.day.data.us_mapping_summary.run_contract.universe?.symbol_count ?? '未知' }} 个） · SHA {{ vm.day.data.us_mapping_summary.run_contract.universe?.contract_sha256?.slice(0, 12) || '未知' }}；
            Connect 来源 {{ vm.day.data.us_mapping_summary.run_contract.owners?.connect?.source_owner || '未知' }}（来源日 {{ vm.day.data.us_mapping_summary.run_contract.owners?.connect?.source_date || '未知' }}，观测 {{ vm.day.data.us_mapping_summary.run_contract.owners?.connect?.observed_symbol_count ?? '未知' }} 只），目标日资格 {{ vm.day.data.us_mapping_summary.run_contract.owners?.connect?.target_eligibility || 'CANNOT_CONFIRM' }}。
            {{ vm.day.data.us_mapping_summary.run_contract.owners?.connect?.target_gap || '' }}</p>
          <p v-if="vm.day.data.us_mapping_summary.run_contract.gaps?.length">输入合同缺口：{{ vm.day.data.us_mapping_summary.run_contract.gaps.join('、') }}</p>
        </template>
        <p v-if="vm.day.data.us_mapping_summary.mixed_source_count">另有 {{ vm.day.data.us_mapping_summary.mixed_source_count }} 个标的包含不同关系结论，逐条保留如下。</p>
        <article v-if="vm.day.data.us_mapping_summary.factor_summary" class="mwb-factor-summary">
          <h4>{{ fullMappingSectorPolicy(vm.day.data.us_mapping_summary.factor_summary) ? '行业 ETF 宽基基线 · 来源市场观察' : '美股代理日收益因子 · 事后研究候选' }}</h4>
          <p>{{ factorSummaryText(vm.day.data.us_mapping_summary.factor_summary) }}</p>
          <p>收益会话 {{ vm.day.data.us_mapping_summary.factor_summary.source_session || '未知' }}；目标日 {{ vm.day.data.us_mapping_summary.factor_summary.target_date }}，阶段 {{ PHASE_LABELS[vm.day.data.us_mapping_summary.factor_summary.phase] }}。历史暴露有效期间仍可能未知；本结果未做 PIT 验证，也未验证研究效果。</p>
          <p v-if="fullMappingSectorPolicy(vm.day.data.us_mapping_summary.factor_summary)">本批规则：{{ fullMappingSectorPolicy(vm.day.data.us_mapping_summary.factor_summary) }}；来源涨跌幅不会生成港股方向或主选股路径。行业方向仅记录美股来源观察。</p>
          <p v-if="vm.day.data.us_mapping_summary.factor_summary.paired_review_gap">审核材料缺口：{{ vm.day.data.us_mapping_summary.factor_summary.paired_review_gap }}</p>
        </article>
        <article v-if="singleDayCatalogSummary()" class="mwb-factor-summary" aria-label="全量映射关系消费">
          <h4>{{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.catalog_stock_count) }} 只目录公司 / {{ showCount(singleDayCatalogSummary()?.catalog_consumption?.relation_count) }} 条关系的实际消费结果</h4>
          <p>处置状态 {{ showText(singleDayCatalogSummary()?.catalog_consumption?.state) }}；关系 {{ showCount(singleDayCatalogSummary()?.catalog_consumption?.relation_count) }} 条，唯一编号 {{ showCount(singleDayCatalogSummary()?.catalog_consumption?.unique_relation_id_count) }} 个；已绑定来源报价 {{ showCount(singleDayCatalogSummary()?.catalog_consumption?.quoted_relation_count) }} 条，缺报价 {{ showCount(singleDayCatalogSummary()?.catalog_consumption?.missing_quote_relation_count) }} 条。日期 {{ showText(singleDayCatalogSummary()?.manual_quote_scope?.session_date) }}；报价范围 SHA {{ showText(singleDayCatalogSummary()?.manual_quote_scope?.scope_sha256) }}；报价绑定 {{ showText(singleDayCatalogSummary()?.manual_quote_scope?.state) }} {{ showText(singleDayCatalogSummary()?.manual_quote_scope?.gap) }}。</p>
          <p>目录身份 {{ showText(singleDayCatalogSummary()?.catalog_stock_reconciliation?.catalog_stock_identity_state) }}：{{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.catalog_stock_count) }} 只，其中有关系 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.catalog_stock_with_relation_count) }} 只、无关系 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.no_relation_stock_count) }} 只；关系目标共 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.relation_target_stock_count) }} 只。当前月池内 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.in_monthly_pool_stock_count) }} 只 / {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.in_monthly_pool_relation_count) }} 条关系，目录池外 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.outside_monthly_pool_stock_count) }} 只 / {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.outside_monthly_pool_relation_count) }} 条关系；另有月池标的不在目录主表 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.monthly_pool_not_in_catalog_stock_count) }} 只；缺少目标身份 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.target_identity_missing_relation_count) }} 条。</p>
          <details><summary>查看目录中没有关系的 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.no_relation_stock_count) }} 只股票</summary>
            <ul v-if="catalogNoRelationStocks()"><li v-for="stock in catalogNoRelationStocks() || []" :key="stock.symbol || stock.name">{{ showText(stock.symbol) }} {{ showText(stock.name) }}</li></ul>
            <p v-else>目录股票身份清单未提供。</p>
          </details>
          <details><summary>查看月池额外纳入、但不在目录主表中的 {{ showCount(singleDayCatalogSummary()?.catalog_stock_reconciliation?.monthly_pool_not_in_catalog_stock_count) }} 只股票</summary>
            <p>{{ monthlyPoolExtraSymbols()?.join('、') || (monthlyPoolExtraSymbols() ? '无' : '未知') }}</p>
          </details>
          <p>各关系依据原关系类型、原始事实 / 条件、当前适用状态和 recovery 范围逐条给出采用或排除原因。原始方向不会被转成港股收益；美股 peer 收益只作为来源市场观察，不代表港股预测、收益或买入。</p>
          <details><summary>查看 {{ singleDayMappingRows().length }} 只港股的路径、同行覆盖和开盘 / 盘中状态</summary>
            <div class="mwb-table-wrap"><table class="mwb-table">
              <thead><tr><th>港股</th><th>映射路径 / 主要来源</th><th>同行与关系</th><th>开盘反应</th><th>开盘后状态</th></tr></thead>
              <tbody><tr v-for="stock in singleDayMappingRows()" :key="String(stock.symbol)">
                <td>{{ showText(stock.symbol) }} {{ showText(stock.name) }}</td>
                <td>{{ showText(stock.mapping_grade) }} · {{ showText(stock.primary_relation_type || stock.source_industry || stock.reason) }} · {{ showText(stock.primary_proxy || stock.primary_us_symbol) }}</td>
                <td>{{ showCount(Array.isArray(stock.catalog_peer_baskets) ? stock.catalog_peer_baskets.length : null) }} 个同行组；{{ showCount(Array.isArray(stock.catalog_relation_dispositions) ? stock.catalog_relation_dispositions.length : null) }} 条关系；{{ showText(stock.reason) }}</td>
                <td>{{ showText(stock.open_reaction_status) }}</td><td>{{ showText(stock.post_open_status) }} · {{ showText(stock.post_open_reason) }}</td>
              </tr></tbody>
            </table></div>
          </details>
          <details><summary>查看全量 {{ catalogDispositionRows().length }} 条关系的消费、报价与原因</summary>
            <div class="mwb-table-wrap"><table class="mwb-table">
              <thead><tr><th>港股 / 美股</th><th>关系 / 路由</th><th>处置与原因</th><th>原始事实 / 条件 / 方向</th><th>当前范围</th><th>报价</th></tr></thead>
              <tbody><tr v-for="relation in catalogDispositionRows()" :key="String(relation.catalog_relation_id)">
                <td>{{ showText(relation.symbol) }} / {{ showText(relation.us_symbol) }}</td>
                <td>{{ showText(relation.catalog_relation_id) }} · {{ showText(relation.relation_type) }} · {{ showText(relation.route) }}</td>
                <td>{{ showText(relation.catalog_disposition) }} · {{ showText(relation.catalog_disposition_reason) }}</td>
                <td>{{ showText(relation.catalog_fact) }} · 条件：{{ showText(relation.catalog_condition) }} · 原始方向：{{ showText(relation.catalog_direction_raw) }}</td>
                <td>{{ showText(relation.catalog_current_applicability) }} · {{ showText(relation.catalog_fact_verified_scope) }}</td>
                <td>{{ showText(relation.quote_status) }} · {{ relation.us_source_return_pct == null ? '未知' : `${relation.us_source_return_pct}%` }} · {{ showText(relation.quote_missing_reason) }}</td>
              </tr></tbody>
            </table></div>
          </details>
          <details><summary>查看 {{ catalogPeerBasketRows().length }} 个 peer 研究观察</summary>
            <div class="mwb-table-wrap"><table class="mwb-table">
              <thead><tr><th>港股</th><th>关系组</th><th>覆盖</th><th>有效成员 / 等权来源收益</th><th>缺失代码</th><th>解释</th></tr></thead>
              <tbody><tr v-for="(item, index) in catalogPeerBasketRows()" :key="`${item.symbol}:${String(item.basket.peer_bucket)}:${index}`">
                <td>{{ item.symbol }}</td><td>{{ showText(item.basket.peer_bucket) }}</td>
                <td>{{ showText(item.basket.signal_type) }} · {{ showText(item.basket.coverage_state) }} · {{ showCount(item.basket.valid_count) }} / {{ showCount(item.basket.declared_count) }} ({{ item.basket.coverage_fraction == null ? '未知' : `${Math.round(Number(item.basket.coverage_fraction) * 100)}%` }})</td>
                <td>{{ showText(item.basket.source_mean_return_pct) }}% · {{ showText(item.basket.source_move_direction) }} · {{ showText(item.basket.relation_ids) }}</td>
                <td>{{ showText(item.basket.missing_symbols) }}</td><td>{{ showText(item.basket.interpretation) }}</td>
              </tr></tbody>
            </table></div>
          </details>
        </article>
        <details><summary>查看全部美股来源、港股关系与未入选／待核原因</summary>
          <article v-for="group in vm.day.data.us_mapping_summary.groups" :key="group.us_symbol">
            <h4>{{ group.us_symbol }} · {{ group.decisions.map(decisionLabel).join('、') }}</h4>
            <div v-for="(row, idx) in group.rows" :key="idx">
              <p v-if="row.symbol">目标港股：{{ row.symbol }} {{ row.name || '名称未知' }}</p>
              <p>{{ readableReason(row) }}</p>
              <p v-if="row.research_basis">已保存关系依据：{{ row.research_basis }}</p>
              <p v-if="Array.isArray(row.reviewed_assessments)" v-for="(assessment, i) in row.reviewed_assessments" :key="i">{{ assessment.original?.reason }}</p>
              <p v-if="Array.isArray(row.diagnostic_gaps) && row.diagnostic_gaps.includes('TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP')">该目标港股不在本版本港股通资格范围。</p>
            </div>
          </article>
        </details>
      </section>
      </details>
      <p v-else-if="vm.laneFilter === 'US_MAPPING'" class="mwb-muted">本版本未提供美股分路汇总；不能推断美股入选。</p>

      <form class="mwb-filters" @submit.prevent="vm.applyFilters" aria-label="服务端查询筛选">
        <label>分类
          <select :value="vm.decisionFilter" @change="changeDecisionBySelect">
            <option value="">推荐（入选与条件观察）</option>
            <option value="SELECTED">严格入选</option>
            <option value="CONDITIONAL_WATCH">条件观察</option>
            <option value="UNASSESSED">待评估</option>
            <option value="OBSERVATION_ONLY">仅观察</option>
            <option value="NOT_SELECTED">未入选</option>
          </select>
        </label>
        <label class="mwb-search">代码 / 名称
          <input v-model="vm.searchDraft" placeholder="例如 HK.00001" />
        </label>
        <button type="submit">查询</button>
      </form>

      <div v-if="vm.day && (vm.day.state === 'NOT_RUN' || !vm.day.data?.snapshot)" class="mwb-empty">
        {{ vm.day.state === "NOT_RUN" ? "当日有效，但尚未运行／保存研究版本" : "未提供可展示计划" }}
      </div>
      <div v-else-if="vm.stocks.length === 0 && !vm.dayLoading" class="mwb-empty">
        {{ vm.day?.state === 'READY_EMPTY' ? "研究已完成且有效空集" : "此筛选或版本暂无名单行" }}
      </div>
      <div v-if="vm.stocks.length" class="mwb-table-wrap">
        <table class="mwb-table mwb-stock-table">
          <thead><tr>
            <th scope="col">股票 / 资格</th><th scope="col">本路径分类</th>
            <th scope="col">研究来源</th><th scope="col">理由 / 待确认</th>
            <th scope="col" class="mwb-wide">变化与时间</th><th scope="col">详情</th>
          </tr></thead>
          <tbody>
            <tr v-for="stock in vm.stocks" :key="String(stock.row_id || stock.market + ':' + stock.symbol)">
              <td><strong class="mwb-symbol">{{ stock.symbol }}</strong>
                <span>{{ stock.name || '名称未知' }}</span>
                <small v-if="stock.name_source">名称来自本研究版本已校验的证券主表（仅展示补齐）</small>
                <small>资格：{{ stock.membership_status || "待核验" }}</small>
              </td>
              <td><span class="mwb-decision" :data-decision="stock.decision">{{ decisionLabel(stock.decision) }}</span>
              </td>
              <td>{{ LANE_LABELS[vm.laneFilter] }}<small v-if="stock.us_symbol">美股来源 {{ stock.us_symbol }}</small>
                <small v-if="stock.subtype === 'HK_INDUSTRY_PROXY_FACTOR_CANDIDATE'">身份 {{ stock.identity_status || 'UNASSESSED_IDENTITY' }}；行业 {{ stock.source_industry || '分类未知' }} → 主题 {{ stock.theme || '未映射' }}；代理日收益 {{ stock.return_pct ?? '未知' }}% · {{ stock.mapping_type || '映射类型未知' }}</small>
              </td>
              <td><div class="mwb-main-reason">{{ firstReason(stock) }}</div>
                <small>待确认：{{ stock.conditions?.length ? conditionLabel(stock.conditions[0]) : "无已记录条件" }}</small>
              </td>
              <td class="mwb-wide"><span>{{ stock.changed || "变化未提供" }}</span>
                <small>{{ humanTime(stock.available_at) }}</small>
              </td>
              <td><button type="button" class="mwb-detail-link"
                :aria-label="'查看 ' + stockTitle(stock) + ' 详情'"
                @click="vm.openStock(stock)">查看详情</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="vm.pagination" class="mwb-pagination">
        <span>服务端筛选后共 {{ vm.pagination.total }} 行；本页 {{ vm.stocks.length }} 行，
          每页最多 {{ vm.limit }} 行。完整分类计数独立于此分页。</span>
        <div>
          <button type="button" :disabled="vm.offset === 0 || vm.dayLoading"
            @click="vm.setOffset(Math.max(0, vm.offset - vm.limit))">上一页</button>
          <span>{{ vm.stocks.length ? vm.offset + 1 : 0 }}–{{ Math.min(vm.pagination.total, vm.offset + vm.stocks.length) }}</span>
          <button type="button" :disabled="vm.dayLoading || vm.offset + vm.limit >= vm.pagination.total"
            @click="vm.setOffset(vm.offset + vm.limit)">下一页</button>
        </div>
      </div>
    </section>

    <section v-if="vm.panel === 'detail'" class="mwb-panel" aria-label="个股研究详情">
      <div class="mwb-heading"><h2>{{ LANE_LABELS[vm.laneFilter] }} · 个股研究详情 · {{ vm.detailSymbol || "未选择" }}</h2>
        <button type="button" class="mwb-quiet" @click="vm.showPanel('stocks')">返回名单</button></div>
      <p v-if="vm.detailLoading" role="status">正在读取同 run_id 详情…</p>
      <p v-if="vm.detailError" class="mwb-alert" role="alert">{{ vm.detailError }}</p>
      <template v-if="vm.detail?.data?.stock">
        <div class="mwb-stock-top">
          <h3>{{ stockTitle(vm.detail.data.stock) }}</h3>
          <small v-if="vm.detail.data.stock.name_source">名称来自本研究版本已校验的证券主表（仅展示补齐）</small>
          <span class="mwb-decision" :data-decision="vm.detail.data.stock.decision">
            {{ decisionLabel(vm.detail.data.stock.decision) }}
          </span>
          <span>资格：{{ vm.detail.data.stock.membership_status || "待核验" }}</span>
        </div>
        <div class="mwb-detail-grid">
          <article><h3>依据</h3><p v-for="reason in detailReasons(vm.detail.data)" :key="reason">{{ reason }}</p>
            <p v-if="!detailReasons(vm.detail.data).length">暂无可核验依据</p></article>
          <article><h3>待确认条件</h3><p v-for="v in vm.detail.data.stock.conditions" :key="v">{{ conditionLabel(v) }}</p>
            <p v-if="!vm.detail.data.stock.conditions?.length">未提供</p></article>
          <article><h3>失效条件</h3><p v-for="v in vm.detail.data.stock.invalidation_conditions" :key="v">{{ v }}</p>
            <p v-if="!vm.detail.data.stock.invalidation_conditions?.length">未提供</p></article>
          <article><h3>风险</h3><p v-for="v in detailRisks(vm.detail.data)" :key="v">{{ v }}</p>
            <p v-if="!detailRisks(vm.detail.data).length">未提供</p></article>
        </div>
        <h3>本推荐路径的已保存研究依据</h3>
        <div class="mwb-lane-grid">
          <article v-for="lane in [vm.laneFilter]" :key="lane" class="mwb-lane-card">
            <h4>{{ LANE_LABELS[lane] }}</h4>
            <p>{{ laneResultLabel(vm.detail.data.stock, lane) }}</p>
            <div v-for="(row, idx) in researchRows(vm.detail.data.stock, lane, detailForLane(lane))"
              :key="idx" class="mwb-research-record">
              <small v-if="researchRows(vm.detail.data.stock, lane, detailForLane(lane)).length > 1">独立记录 {{ idx + 1 }}</small>
              <p class="mwb-research-reason">{{ readableReason(row) }}</p>
              <section v-for="section in researchSections(row)" :key="section.key" class="mwb-research-section">
                <h5>{{ section.label }}</h5>
                <div v-for="(item, i) in section.items" :key="i">
                  <p v-if="item.claim">{{ item.claim }}</p>
                  <blockquote v-if="item.quote"><small>原文引用</small><p>{{ item.quote }}</p>
                    <cite v-if="item.locator">{{ item.locator }}</cite></blockquote>
                </div>
                <p v-if="!section.items.length" class="mwb-muted">未提供</p>
              </section>
              <section v-if="factorPaths(row).length" class="mwb-research-section">
                <h5>美股代理日收益路径 · 各路径独立判定</h5>
                <article v-for="(path, pathIndex) in factorPaths(row)" :key="pathIndex" class="mwb-factor-path">
                  <p><strong>{{ showText(path.theme) }} · {{ decisionLabel(String(path.decision || 'UNASSESSED')) }}</strong>
                    · 日收益 {{ path.return_pct === null || path.return_pct === undefined ? '未知' : `${showText(path.return_pct)}%` }}</p>
                  <p>代理标的 {{ Array.isArray(path.proxy_symbols) ? path.proxy_symbols.join('、') : '未知' }}；行情会话 {{ showText(path.source_session) }}。</p>
                  <blockquote v-if="path.statement"><small>已审核的原文片段</small><p>{{ showText(path.statement) }}</p></blockquote>
                  <p>该暴露材料的历史有效期间：{{ factorPeriod(path) }}；审核结论：{{ showText(path.review_decision) }}；PIT 未验证，研究效果未验证。</p>
                  <details v-if="supplementalEvidence(path).length">
                    <summary>补充原始出处定位（不代表已接受）</summary>
                    <article v-for="(item, itemIndex) in supplementalEvidence(path)" :key="itemIndex">
                      <p>{{ showText(item.document_title) }} · {{ showText(item.source_owner) }} · 发布日期 {{ showText(item.published_date) }}</p>
                      <p v-if="item.body_excerpt">原文片段：{{ showText(item.body_excerpt) }}</p>
                      <p v-if="item.body_excerpt_hk">港股身份片段：{{ showText(item.body_excerpt_hk) }}</p>
                      <p v-if="item.body_excerpt_a">A股身份片段：{{ showText(item.body_excerpt_a) }}</p>
                      <p>原文位置 {{ showText(item.body_span_chars || item.body_span_chars_hk || item.body_span_chars_a_code) }}；可得时间 {{ showText(item.product_available_at) }}。</p>
                    </article>
                  </details>
                  <p v-for="condition in (Array.isArray(path.conditions) ? path.conditions : [])" :key="String(condition)">待核条件：{{ showText(condition) }}</p>
                </article>
              </section>
              <section v-if="row.subtype === 'HK_INDUSTRY_PROXY_FACTOR_CANDIDATE'" class="mwb-research-section">
                <h5>发行人行业与美股代理主题 · 独立候选</h5>
                <p>身份状态 {{ showText(row.identity_status || 'UNASSESSED_IDENTITY') }}；安全主表 {{ showText(row.security_master_owner) }} · 会话 {{ showText(row.security_master_source_date) }} · artifact SHA {{ showText(row.security_master_artifact_sha256) }}。</p>
                <p>来源行业 {{ showText(row.source_industry) }}；方向路径 {{ directionalStockReason(row) }}；路径状态 {{ showText(row.proxy_directional_state || 'UNASSESSED') }}。</p>
                <p>映射类型 {{ showText(row.mapping_type) }}；分类来源 {{ showText(row.source_id) }} · {{ showText(row.source_owner) }}；来源原始响应 SHA {{ showText(row.source_response_sha256) }}，行 SHA {{ showText(row.source_row_sha256) }}。</p>
                <p>source_asof {{ showText(row.source_asof || 'UNKNOWN') }}；采集时间 {{ humanTime(typeof row.captured_at === 'string' ? row.captured_at : null) }}；时间状态 {{ showText(row.temporal_status) }}；历史 PIT 未验证，研究效果未验证。</p>
                <p v-for="condition in (Array.isArray(row.conditions) ? row.conditions : [])" :key="String(condition)">待核条件：{{ showText(condition) }}</p>
              </section>
              <section class="mwb-research-section"><h5>风险</h5>
                <p v-for="risk in researchRisks(row)" :key="risk">{{ risk }}</p>
                <p v-if="!researchRisks(row).length" class="mwb-muted">未提供</p>
              </section>
              <p v-if="typeof row.original_text === 'string' && row.original_text" class="mwb-original-text">原文引用：{{ row.original_text }}</p>
            </div>
            <p v-if="!researchRows(vm.detail.data.stock, lane, detailForLane(lane)).length" class="mwb-muted">该路径尚未提供研究判定。</p>
          </article>
        </div>
        <details class="mwb-evidence">
          <summary>证据身份、原始引用与校验缺口</summary>
          <p class="mwb-muted">审计原件：保存版本、机器字段、证据身份与校验信息。默认折叠，不参与页面判定。</p>
          <pre class="mwb-audit-json">{{ showText(vm.detail.data) }}</pre>
          <template v-for="source in vm.detail.data.lane_details || []" :key="source.lane">
            <a v-for="ev in (source.evidence_refs || []).filter(ev => evidenceLink(ev.source_url))"
              :key="ev.evidence_id" :href="evidenceLink(ev.source_url) || undefined"
              target="_blank" rel="noopener noreferrer">打开原文</a>
          </template>
        </details>
      </template>
      <p v-else-if="!vm.detailLoading && !vm.detailError" class="mwb-muted">从今日名单选择股票；详情只读指定目标日和版本。</p>
    </section>

    <section v-if="vm.panel === 'progress'" class="mwb-panel" aria-label="研究任务进度">
      <div class="mwb-heading"><div><h2>研究进度</h2><p>查看已保存研究路径及后台任务；离开页面不会取消后台任务。</p></div></div>
      <div v-if="vm.lanes.length" class="mwb-progress-grid">
        <article v-for="lane in vm.lanes" :key="lane.lane" class="mwb-lane-card">
          <h3>{{ labelForLane(lane.lane) }}</h3>
          <p class="mwb-state">{{ LANE_STATE_LABELS[lane.state] || lane.state }}</p>
          <dl><dt>观察</dt><dd>{{ showCount(lane.coverage?.observed_count) }}</dd>
            <dt>已评估</dt><dd>{{ showCount(lane.coverage?.assessed_count) }}</dd>
            <dt>范围总数</dt><dd>{{ showCount(lane.coverage?.scope_count) }}</dd>
            <dt>待评估</dt><dd>{{ showCount(lane.coverage?.unassessed_count) }}</dd></dl>
          <p v-for="gap in lane.gaps || []" :key="gapText(gap)" class="mwb-muted">缺口：{{ gapText(gap) }}</p>
        </article>
      </div>
      <p v-else class="mwb-empty">尚无已保存的研究进度；未知不代表全部未运行。</p>
      <div class="mwb-task-form">
        <h3>创建研究任务（不会直接提交交易）</h3>
        <label for="mwb-run-phase">任务性质</label>
        <select id="mwb-run-phase" :value="vm.runPhase" @change="changeJobPhase">
          <option value="MANUAL">MANUAL · 当前手动研究</option>
          <option value="RETROSPECTIVE">RETROSPECTIVE · 事后回看</option>
        </select>
        <button type="button" :disabled="vm.operationLoading || !vm.valid" @click="vm.createPlan">
          {{ vm.operationLoading ? "正在提交…" : "生成研究计划" }}
        </button>
      </div>
      <p v-if="vm.jobError" class="mwb-alert" role="alert">{{ vm.jobError }}</p>
      <article v-if="vm.job?.data" class="mwb-job">
        <h3>任务 {{ vm.job.data.job_id }}</h3>
        <p>执行状态：{{ JOB_STATE_LABELS[vm.job.data.state] }} · 步骤：{{ vm.job.data.step || "未提供" }}</p>
        <p>已完成 {{ showCount(vm.job.data.completed_count) }} / {{ showCount(vm.job.data.total_count) }}</p>
        <p>最近进展：{{ humanTime(vm.job.data.last_progress_at) }}</p>
        <p v-if="vm.job.data.failure_code" class="mwb-alert">失败：{{ vm.job.data.failure_code }}</p>
        <p v-for="step in vm.job.data.failed_steps || []" :key="step">{{ step }}</p>
        <button type="button" class="mwb-quiet" :disabled="vm.jobLoading" @click="vm.pollJob">重新读取进度</button>
        <button type="button" :disabled="!vm.job.data.retryable || vm.operationLoading" @click="vm.retryJob">
          仅恢复可重试失败步骤
        </button>
        <button v-if="vm.job.data.state === 'SUCCEEDED' || vm.job.data.state === 'PARTIAL'"
          type="button" class="mwb-quiet" @click="vm.viewJobVersion">查看此任务保存版本</button>
      </article>
      <p v-else-if="vm.jobId && vm.jobLoading" role="status">任务已创建，正在读取后台进度…</p>
    </section>

    <section v-if="vm.panel === 'history'" class="mwb-panel" aria-label="计划历史">
      <div class="mwb-heading"><div><h2>计划历史</h2>
        <p>旧计划原样只读；原始记录与后续回看严格区分。</p></div>
        <button type="button" class="mwb-quiet" @click="vm.loadHistory">重新读取历史</button></div>
      <p v-if="vm.historyLoading" role="status">读取历史中…</p>
      <p v-if="vm.historyError" class="mwb-alert" role="alert">{{ vm.historyError }}</p>
      <div v-if="vm.history?.data?.versions?.length" class="mwb-history">
        <article v-for="(entry,i) in vm.history.data.versions" :key="(entry.run_id || entry.original_run_id || i) + ':' + i">
          <div><strong>{{ entry.origin === 'LEGACY' ? "LEGACY · 原样历史" : "NEW · 新计划" }}</strong>
            <span v-if="entry.phase === 'RETROSPECTIVE'" class="mwb-retro">RETROSPECTIVE · 事后回看</span></div>
          <p>{{ entry.target_date || vm.history.data.date }} · {{ entry.phase ? PHASE_LABELS[entry.phase] : "旧阶段未知" }}
            · 记录于 {{ humanTime(entry.recorded_at || entry.generated_at) }}</p>
          <template v-if="entry.origin === 'LEGACY'">
            <p>原 run：{{ entry.original_run_id || "未知" }} · 原 schema：{{ entry.original_schema || "未知" }}</p>
            <p>原 SHA：{{ entry.original_sha256 || "未知" }} · 校验：{{ entry.verification || "CANNOT_CONFIRM" }}</p>
          </template>
          <template v-else>
            <p>计划 run：{{ entry.run_id || "未知" }} · 保存状态：{{ entry.state || "未知" }}</p>
            <p>产品 SHA：{{ entry.product_sha256 || "未知" }} · 输入 SHA：{{ entry.input_sha256 || "未知" }}</p>
          </template>
          <p v-for="gap in entry.gaps || []" :key="gapText(gap)" class="mwb-muted">缺口：{{ gapText(gap) }}</p>
        </article>
      </div>
      <p v-else-if="!vm.historyLoading && !vm.historyError" class="mwb-empty">当日尚无可读取历史或来源未知。</p>
      <p v-for="gap in vm.history?.gaps || []" :key="gapText(gap)" class="mwb-muted">{{ gapText(gap) }}</p>
    </section>

    <section v-if="vm.panel === 'reviews'" class="mwb-panel" aria-label="收盘研究复盘">
      <div class="mwb-heading"><div><h2>收盘复盘 · 完整 Top20 对照</h2>
        <p>读取已保存的研究统计。观察贡献不计入严格入选。</p></div>
        <button type="button" class="mwb-quiet" @click="vm.loadReview">重新读取复盘</button></div>
      <p v-if="vm.reviewLoading" role="status">读取复盘中…</p>
      <p v-if="vm.reviewError" class="mwb-alert" role="alert">{{ vm.reviewError }}</p>
      <template v-if="vm.review?.data">
        <p>榜单日期：{{ vm.review.data.ranking_date || "未知" }} · 模式：{{ vm.review.data.mode || "未知" }}
          · 实际榜单范围：{{ vm.review.data.evaluation_scope_ref || "未知" }}</p>
        <div class="mwb-counts mwb-review-metrics">
          <div><strong>{{ metricLabel(vm.review.data.strict_coverage, vm.review.data.top20_rows?.length === 20) }}</strong><span>严格覆盖率（仅 SELECTED）</span></div>
          <div><strong>{{ metricLabel(vm.review.data.extended_coverage, vm.review.data.top20_rows?.length === 20) }}</strong><span>扩展覆盖率（含条件观察）</span></div>
          <div><strong>{{ showCount(vm.review.data.selected_denominator) }}</strong><span>实际入选名单分母</span></div>
        </div>
        <p v-if="!vm.review.data.top20_rows || vm.review.data.top20_rows.length !== 20"
          class="mwb-alert" role="status">榜单缺失或不足完整20行，不能宣称完整Top20覆盖率。</p>
        <div v-if="vm.review.data.top20_rows?.length" class="mwb-table-wrap">
          <table class="mwb-table">
            <thead><tr><th scope="col">名次</th><th scope="col">股票</th><th scope="col">实际变化</th>
              <th scope="col">严格命中</th><th scope="col">扩展命中</th>
              <th scope="col">计划冻结分类</th><th scope="col">漏选原因</th></tr></thead>
            <tbody><tr v-for="(item,i) in vm.review.data.top20_rows" :key="item.symbol + ':' + i">
              <td>{{ item.rank }}</td><td>{{ item.symbol }} {{ item.name || "" }}</td>
              <td>{{ showText(item.actual_change) }}</td>
              <td>{{ item.strict_hit === null || item.strict_hit === undefined ? "未知" : (item.strict_hit ? "是" : "否") }}</td>
              <td>{{ item.extended_hit === null || item.extended_hit === undefined ? "未知" : (item.extended_hit ? "是" : "否") }}</td>
              <td>{{ item.stock_decision ? decisionLabel(item.stock_decision) : "未知" }}</td>
              <td>{{ item.missed_reason || "未提供" }}</td>
            </tr></tbody>
          </table>
        </div>
        <div class="mwb-detail-grid">
          <article><h3>策略新增覆盖（服务端结果）</h3>
            <pre>{{ showText(vm.review.data.lane_incremental_coverage) }}</pre></article>
          <article><h3>漏选原因（服务端结果）</h3>
            <pre>{{ showText(vm.review.data.uncovered_reasons) }}</pre></article>
        </div>
        <p v-for="gap in vm.review.data.gaps || []" :key="gapText(gap)" class="mwb-muted">缺口：{{ gapText(gap) }}</p>
      </template>
      <p v-else-if="!vm.reviewLoading && !vm.reviewError" class="mwb-empty">
        尚无同目标日、同计划 run_id 的有效收盘复盘。
      </p>
    </section>

    <section v-if="vm.panel === 'catalog'" class="mwb-panel" aria-label="美股映射资料库">
      <div class="mwb-heading">
        <div><h2>美股 → 港股关系资料库</h2>
          <p>读取 2026-10-14 名单快照、旧 700 条历史记录和 2026-10-16 v2r1 逐关系研究投影；这是静态研究资料，不是当日选股结果。</p></div>
        <button type="button" class="mwb-quiet" :disabled="vm.catalogLoading" @click="vm.loadCatalog(0)">重新读取资料</button>
      </div>
      <p class="mwb-alert" role="status">
        目录只通过结构和来源校验。公司事实独立核验仍为待办，预测状态 UNTESTED，历史 PIT NOT_VALIDATED；任何关系都没有预测或选股资格。
      </p>
      <form class="mwb-filters" @submit.prevent="vm.searchCatalog">
        <label class="mwb-search">按港股代码、港股名称、美股资产代码或关系编号查询
          <input v-model="vm.catalogQueryDraft" maxlength="128" placeholder="例如 00001、CVE 或 R001" />
        </label>
        <label>旧 700 历史用途筛选
          <select v-model="vm.catalogResearchUse" @change="vm.searchCatalog">
            <option value="">全部关系</option>
            <option value="PENDING_REVIEW">待核 / 待补证</option>
            <option value="CONDITIONAL_OBSERVATION">条件观察（研究设计）</option>
            <option value="BACKGROUND_HISTORICAL">背景 / 历史</option>
            <option value="EXCLUDED_CURRENT">排除现行用途</option>
          </select>
        </label>
        <button type="submit" :disabled="vm.catalogLoading">查询资料</button>
      </form>
      <p v-if="vm.catalogLoading" role="status">正在读取映射资料…</p>
      <p v-if="vm.catalogError" class="mwb-alert" role="alert">{{ vm.catalogError }}</p>
      <template v-if="vm.catalog?.data">
        <div class="mwb-detail-grid">
          <article><h3>来源身份</h3>
            <p>名单快照：{{ vm.catalog.data.source.membership_snapshot }}；名单 SHA256：{{ vm.catalog.data.source.membership_sha256 }}</p>
            <p>研究包：{{ vm.catalog.data.source.package_name }}；SHA256：{{ vm.catalog.data.source.package_sha256 }}</p>
            <p>ZIP CRC：{{ vm.catalog.data.source.zip_crc }}；清单校验：{{ vm.catalog.data.source.manifest }}；包内文件：{{ vm.catalog.data.source.package_member_count }}</p>
            <p>目录完整性 SHA256：{{ vm.catalog.data.catalog_integrity_sha256 }}</p>
          </article>
          <article><h3>结构覆盖</h3>
            <p>名单 {{ vm.catalog.data.coverage.membership_count }} 只；原始关系 {{ vm.catalog.data.coverage.relation_row_count }} 条；有关系记录 {{ vm.catalog.data.coverage.stocks_with_relations }} 只。</p>
            <p>源文件自报进度：{{ showText(vm.catalog.data.source_claims.main_table_a_progress) }}；源文件自报预测：{{ showText(vm.catalog.data.source_claims.main_table_a_prediction_state) }}。</p>
            <p>旧 997 条关系逐边比较：{{ vm.catalog.data.source_claims.old_matrix_comparison }}；独立事实核验：{{ vm.catalog.data.source_claims.independent_fact_verification }}。</p>
          </article>
        </div>
        <article class="mwb-evidence" aria-label="补证进度">
          <h3>补证记录进度</h3>
          <p>旧 700 历史 overlay SOURCE_REVIEWED：{{ vm.catalog.data.review_progress.source_reviewed_relations }} / 1003 条关系、{{ vm.catalog.data.review_progress.source_reviewed_stocks }} / 667 只股票；旧 overlay 未覆盖 {{ vm.catalog.data.review_progress.unprocessed_relations }} 条关系。</p>
          <p>全部原始关系已有记录：{{ vm.catalog.data.review_progress.all_original_relations_processed_stocks }} 只股票（不表示事实全部通过）。INDEPENDENTLY_VERIFIED：{{ vm.catalog.data.review_progress.independently_verified_relations }} 条；独立核验 {{ vm.catalog.data.review_progress.independent_verification }}。</p>
          <p>旧 700 overlay 研究用途计数：{{ showText(vm.catalog.data.review_progress.research_use_counts) }}。它与 v2r1 的 primary_research_use 是不同字段，不做状态换算。</p>
          <p v-if="vm.catalog.data.review_source">补证包 SHA256：{{ vm.catalog.data.review_source.source_package_sha256 }}；来源生成时间：{{ vm.catalog.data.review_source.source_generated_at_utc }}；revision SHA256：{{ vm.catalog.data.review_source.integrity_sha256 }}。</p>
        </article>
        <article v-if="vm.catalog.data.recovery_v2r1" class="mwb-evidence" aria-label="v2r1 当前恢复状态">
          <h3>2026-10-16 v2r1 当前逐关系状态</h3>
          <p>输入包 SHA256：{{ vm.catalog.data.recovery_v2r1.source_package_sha256 }}；manifest SHA256：{{ vm.catalog.data.recovery_v2r1.source_manifest_sha256 }}；投影 SHA256：{{ vm.catalog.data.recovery_v2r1.overlay_integrity_sha256 }}。</p>
          <p>处理 {{ vm.catalog.data.recovery_v2r1.counts.processed_relations }} / {{ vm.catalog.data.recovery_v2r1.counts.original_relations }} 条原关系；研究范围闭环 {{ vm.catalog.data.recovery_v2r1.counts.research_scope_closed }} 条；排除范围闭环 {{ vm.catalog.data.recovery_v2r1.counts.excluded_scope_closed }} 条；开放 {{ vm.catalog.data.recovery_v2r1.counts.open_relations }} 条。782 条总闭环包含 25 条排除范围记录，不能读作 782 条有效映射或已验证关系。</p>
          <p>名单 {{ vm.catalog.data.recovery_v2r1.counts.snapshot_stocks }} 只；有原始关系 {{ vm.catalog.data.recovery_v2r1.counts.stocks_with_relations }} 只；原始无关系并单独保留 {{ vm.catalog.data.recovery_v2r1.counts.stocks_without_relations }} 只。</p>
          <p>公司事实独立验收 {{ vm.catalog.data.recovery_v2r1.counts.company_independent_acceptance }}；包内全部陈述均未标为已验证；预测 {{ vm.catalog.data.recovery_v2r1.research_safety.prediction_validation }}；历史 PIT {{ vm.catalog.data.recovery_v2r1.research_safety.historical_PIT }}；事件及数据测试 {{ vm.catalog.data.recovery_v2r1.research_safety.event_and_data_tests }}。</p>
          <p>附件路径缺口 {{ vm.catalog.data.recovery_v2r1.evidence_limits.historical_path_gap_occurrences }} 次 / {{ vm.catalog.data.recovery_v2r1.evidence_limits.historical_path_gap_unique_paths }} 个路径；另有已恢复 740 范围内 {{ vm.catalog.data.recovery_v2r1.evidence_limits.separate_restored740_missing_path_sha_pairs }} 组路径 / SHA 和 {{ vm.catalog.data.recovery_v2r1.evidence_limits.separate_restored740_missing_hashes }} 个哈希缺口，范围不同，不相加；A 表仍有 {{ vm.catalog.data.recovery_v2r1.evidence_limits.A_url_occurrences_unattempted }} 个 URL 未尝试。</p>
          <p>研究访问日期不代表 available_at 或事实生效日。旧 700 条历史 overlay（{{ vm.catalog.data.recovery_v2r1.prior_700_history.sha256 }}）仍单独保留，status crosswalk={{ vm.catalog.data.recovery_v2r1.prior_700_history.status_crosswalk }}。</p>
          <details><summary>v2r1 版本优先级与解释边界</summary>
            <p>{{ sourceValue(vm.catalog.data.recovery_v2r1.projection_rule) }}</p>
            <pre>{{ showText(vm.catalog.data.recovery_v2r1.version_precedence) }}</pre>
          </details>
        </article>
        <p class="mwb-muted">本次查询匹配 {{ vm.catalog.data.total }} 只港股。空查询可浏览全部 667 只；当前结果按港股分页，关系筛选只改变匹配展示。</p>
        <article v-for="item in vm.catalog.data.items" :key="item.hk_code" class="mwb-evidence">
          <details open>
            <summary>{{ item.ordinal }} / 667 · {{ item.hk_code }} {{ item.name || "名称未提供" }} · 来源关系 {{ item.relation_count }} 条</summary>
            <p>英文简称：{{ item.english_name || "来源未提供" }} · 研究行业：{{ sourceValue(item.source_record["研究行业"]) }}</p>
            <p><strong>主营：</strong>{{ sourceValue(item.source_record["主营"]) }}</p>
            <p><strong>盈利驱动：</strong>{{ sourceValue(item.source_record["盈利驱动"]) }}</p>
            <p><strong>主要及辅助资产：</strong>{{ sourceValue(item.source_record["主要及辅助资产"]) }}</p>
            <p><strong>关系意义：</strong>{{ sourceValue(item.source_record["关系意义"]) }}</p>
            <p>补证已有记录 {{ item.source_reviewed_relation_count }} 条；未处理 {{ item.unprocessed_relation_count }} 条。</p>
            <p><strong>原表研究进度：</strong>{{ sourceValue(item.source_record["研究进度"]) }}（来源自报；本目录没有把它认作独立验收）</p>
            <div v-if="item.relations.length">
              <article v-for="relation in catalogRelations(item.relations)" :key="relation.source_row" class="mwb-research-record">
                <h4>{{ relation.us_symbol || "美股资产未提供" }} · {{ sourceValue(relation.source_record["type"]) }} · 原始表行 {{ relation.source_row }}</h4>
                <p v-if="relation.recovery_v2r1"><strong>{{ relation.relation_id }} · v2r1 当前闭环：</strong>{{ relation.recovery_v2r1.closure_status }}；当前主要研究用途：{{ sourceValue(relation.recovery_v2r1.primary_research_use) }}；包内交付验收：{{ relation.recovery_v2r1.delivery_acceptance }}。</p>
                <p v-if="relation.recovery_v2r1"><strong>事实范围：</strong>{{ sourceValue(relation.recovery_v2r1.verified_fact_scope) }}；<strong>研究范围闭环依据：</strong>{{ sourceValue(relation.recovery_v2r1.closure_scope) }}</p>
                <p><strong>{{ relation.relation_id }} · 旧 700 历史用途：</strong>{{ researchUseLabel(relation.research_use) }}；旧记录状态 {{ relation.source_review_status }}；独立核验 {{ relation.independent_verification }}。</p>
                <p><strong>分部 / 原始事实：</strong>{{ sourceValue(relation.source_record["segment"]) }}；{{ sourceValue(relation.source_record["fact"]) }}</p>
                <p><strong>传导机制：</strong>{{ sourceValue(relation.source_record["mechanism"]) }}</p>
                <p><strong>触发条件：</strong>{{ sourceValue(relation.source_record["condition"]) }}</p>
                <p><strong>方向与时段：</strong>{{ sourceValue(relation.source_record["direction"]) }}；{{ sourceValue(relation.source_record["timescale"]) }}</p>
                <p><strong>失效条件 / 反例：</strong>{{ sourceValue(relation.source_record["failure"]) }}</p>
                <p><strong>证据强度及原文理由：</strong>{{ sourceValue(relation.source_record["evidence_strength"]) }}；{{ sourceValue(relation.source_record["evidence_reason"]) }}</p>
                <p><strong>信息日期：</strong>{{ sourceValue(relation.source_record["information_date"]) }}</p>
                <p><strong>原始状态：</strong>status={{ sourceValue(relation.source_record["status"]) }}；mapping_status={{ sourceValue(relation.source_record["mapping_status"]) }}；relation_verification={{ sourceValue(relation.source_record["relation_verification"]) }}</p>
                <p><strong>原始候选 / 排除字段：</strong>effective_candidate={{ sourceValue(relation.source_record["effective_candidate"]) }}；current_observation_candidate={{ sourceValue(relation.source_record["current_observation_candidate"]) }}；audit_only={{ sourceValue(relation.source_record["audit_only"]) }}</p>
                <p><strong>原始预测 / 旧边处置：</strong>prediction={{ sourceValue(relation.source_record["prediction"]) }}；old_action={{ sourceValue(relation.source_record["old_action"]) }}；prediction_eligible={{ sourceValue(relation.source_record["prediction_eligible"]) }}；historical_PIT={{ sourceValue(relation.source_record["historical_PIT"]) }}</p>
                <p><strong>目录状态：</strong>事实独立核验 {{ relation.fact_review_status }}；预测资格固定为否；预测 {{ relation.prediction_validation }}；历史 PIT {{ relation.historical_PIT }}。</p>
                <button v-if="(relation.recovery_v2r1 && relation.recovery_v2r1.detail_level !== 'FULL') || (relation.source_review_status === 'SOURCE_REVIEWED' && relation.review_detail_level !== 'FULL')" type="button" class="mwb-quiet"
                  :disabled="vm.catalogRelationDetails[relation.relation_id]?.loading"
                  @click="vm.loadCatalogRelation(relation)">查看完整关系记录 {{ relation.relation_id }}</button>
                <p v-if="relation.source_review_status === 'NOT_PROCESSED'">{{ relation.relation_id }} 不在旧 700 历史补证记录中；v2r1 状态仍单独展示。</p>
                <p v-if="vm.catalogRelationDetails[relation.relation_id]?.loading" role="status">正在读取完整关系记录 {{ relation.relation_id }}…</p>
                <p v-if="vm.catalogRelationDetails[relation.relation_id]?.error" class="mwb-alert" role="alert">{{ relation.relation_id }}：{{ vm.catalogRelationDetails[relation.relation_id]?.error }}</p>
                <p v-if="relation.review_detail_level === 'FULL'">已读取完整关系记录 {{ relation.relation_id }}；来源身份已核对。</p>
                <details v-if="relation.recovery_v2r1">
                  <summary>v2r1 当前用途、范围与缺口</summary>
                  <p><strong>用途理由：</strong>{{ sourceValue(relation.recovery_v2r1.primary_use_reason) }}</p>
                  <p><strong>适用期间：</strong>{{ sourceValue(relation.recovery_v2r1.applicable_period) }}；<strong>研究访问日期与版本：</strong>{{ sourceValue(relation.recovery_v2r1.research_access_date_and_version) }}</p>
                  <p><strong>当前闭环边界：</strong>{{ sourceValue(relation.recovery_v2r1.closure_basis) }}</p>
                  <p><strong>尚存缺口：</strong>{{ sourceValue(relation.recovery_v2r1.remaining_gaps) }}</p>
                  <p><strong>下一关键证据：</strong>{{ sourceValue(relation.recovery_v2r1.next_key_evidence) }}</p>
                  <p><strong>证据 ID：</strong>{{ sourceValue(relation.recovery_v2r1.evidence_ids) }}；effective research SHA256：{{ relation.recovery_v2r1.effective_research_sha256 }}</p>
                  <p>预测 {{ relation.recovery_v2r1.prediction }}；历史 PIT {{ relation.recovery_v2r1.historical_PIT }}；事件及数据测试 {{ relation.recovery_v2r1.event_and_data_tests }}；公司事实独立验收 {{ relation.recovery_v2r1.company_independent_acceptance }}。</p>
                  <details v-if="relation.recovery_v2r1.detail_level === 'FULL' && relation.recovery_v2r1.full_record">
                    <summary>完整 v2r1 有效研究、六层、七字段和来源身份</summary>
                    <pre>{{ showText(relation.recovery_v2r1.full_record) }}</pre>
                  </details>
                </details>
                <details v-if="relation.review_revision">
                  <summary>来源补证 revision、当前缺口与下一证据</summary>
                  <p>以下为来源研究记录与用途投影，保留原始事实；SOURCE_REVIEWED 不等于 INDEPENDENTLY_VERIFIED。</p>
                  <p><strong>来源事实状态：</strong>{{ sourceValue(relation.review_revision.revision.revision_research_fact_state) }}</p>
                  <p><strong>当前适用状态：</strong>{{ sourceValue(relation.review_revision.revision.revision_current_applicability_state) }}</p>
                  <p><strong>研究 / 当前适用核查日期：</strong>{{ sourceValue(relation.review_revision.revision.revision_research_fact_dates) }}；{{ sourceValue(relation.review_revision.revision.revision_current_applicability_checked_dates) }}</p>
                  <p><strong>理由：</strong>{{ sourceValue(relation.review_revision.revision.revision_reason) }}</p>
                  <article v-if="relation.review_revision.source_summary">
                    <h5>来源研究者摘要（未独立验收）</h5>
                    <p><strong>来源建议用途：</strong>{{ sourceValue(relation.review_revision.source_summary.primary_use) }}；{{ sourceValue(relation.review_revision.source_summary.primary_use_reason) }}</p>
                    <p><strong>来源支持的事实范围：</strong>{{ sourceValue(relation.review_revision.source_summary.verified_facts_json) }}</p>
                    <p><strong>使用限制 / 禁止据此推断：</strong>{{ sourceValue(relation.review_revision.source_summary.current_usage_limits_with_addenda_json || relation.review_revision.source_summary.usage_limits_json) }}</p>
                    <p><strong>当前适用缺口：</strong>{{ sourceValue(relation.review_revision.source_summary.current_applicability_gaps_with_addenda_json || relation.review_revision.source_summary.current_applicability_gaps_json) }}</p>
                    <p><strong>下一关键证据：</strong>{{ sourceValue(relation.review_revision.source_summary.current_next_key_evidence_with_addenda_json || relation.review_revision.source_summary.next_key_evidence_json) }}</p>
                  </article>
                  <p v-if="relation.review_revision.revision.revision_additional_research_findings_json"><strong>来源新增研究发现：</strong>{{ sourceValue(relation.review_revision.revision.revision_additional_research_findings_json) }}</p>
                  <p v-if="relation.review_revision.revision.revision_subsequent_research_addenda_json"><strong>来源后续修订 / 冲突说明：</strong>{{ sourceValue(relation.review_revision.revision.revision_subsequent_research_addenda_json) }}</p>
                  <p><strong>当前缺口 / 下一证据：</strong>{{ sourceValue(relation.review_revision.revision.revision_remaining_gaps_json) }}</p>
                  <p v-if="relation.review_detail_level === 'FULL'"><strong>触发设计（未运行）：</strong>{{ sourceValue(relation.review_revision.revision.revision_trigger_design_json) }}</p>
                  <details v-if="relation.review_detail_level === 'FULL'"><summary>逐字段修订与研究层级</summary>
                    <p v-for="[field, assessment] in revisionAssessments(relation.review_revision.revision.revision_field_assessments_json)" :key="field"><strong>{{ field }}：</strong>{{ sourceValue(assessment) }}</p>
                  </details>
                  <details v-if="relation.review_detail_level === 'FULL' && relation.review_revision.revision_json_parse_issues?.length">
                    <summary>原始 JSON 解析问题（来源文本保留）</summary>
                    <article v-for="(issue, index) in relation.review_revision.revision_json_parse_issues" :key="`${issue.field}-${index}`">
                      <p><strong>{{ issue.field }}：</strong>{{ issue.issue }}；{{ issue.error_type }}；原文字符数 {{ issue.raw_characters }}；SHA256 {{ issue.raw_sha256 }}</p>
                      <p><strong>保留的来源原文：</strong>{{ sourceValue(relation.review_revision.revision[issue.field]) }}</p>
                    </article>
                  </details>
                  <details v-if="relation.review_detail_level === 'FULL'"><summary>证据日期、定位、访问结果及边界</summary>
                    <article v-for="(evidence, index) in relation.review_revision.evidence" :key="index">
                      <p>{{ evidence.evidence_id }} · {{ evidence.title }} · {{ evidence.open_status }}</p>
                      <p>发布日期 {{ sourceValue(evidence.published_date) }}；适用期 {{ sourceValue(evidence.applicable_period) }}；访问日期 {{ sourceValue(evidence.accessed_at) }}</p>
                      <p>{{ sourceValue(evidence.locator) }}；{{ sourceValue(evidence.excerpt_or_paraphrase) }}</p>
                      <p><strong>声明的未解决导航引用：</strong>{{ sourceValue(evidence.declared_unresolved_navigation_reference_json) }}</p>
                      <p><strong>证据措辞澄清：</strong>{{ sourceValue(evidence.evidence_wording_clarifications_json) }}</p>
                      <p>不能支持：{{ sourceValue(evidence.does_not_support) }}；缺口：{{ sourceValue(evidence.gaps) }}</p>
                      <a v-for="url in sourceUrls(evidence.url)" :key="url" :href="url" target="_blank" rel="noopener noreferrer">打开补证来源：{{ url }}</a>
                    </article>
                  </details>
                </details>
                <details v-if="relation.review_detail_level === 'FULL'">
                  <summary>完整原始字段与来源研究记录</summary>
                  <p>{{ sourceValue(relation.source_record) }}</p>
                  <p>{{ sourceValue(relation.review_revision) }}</p>
                </details>
                <p><strong>原始 URL：</strong>{{ sourceValue(relation.source_record["url"]) }}</p>
                <p v-for="url in sourceUrls(relation.source_record['url'])" :key="url">
                  <a :href="url" target="_blank" rel="noopener noreferrer">打开来源：{{ url }}</a>
                </p>
              </article>
            </div>
            <p v-else class="mwb-muted">本股在来源主表 B 中没有关系行，仍保留在完整港股名单里。</p>
          </details>
        </article>
        <div v-if="vm.catalog.data.total > vm.catalogLimit" class="mwb-pagination">
          <span>当前 {{ vm.catalog.data.offset + 1 }}–{{ Math.min(vm.catalog.data.offset + vm.catalog.data.items.length, vm.catalog.data.total) }} / {{ vm.catalog.data.total }}</span>
          <div>
            <button type="button" class="mwb-quiet" :disabled="vm.catalogOffset === 0 || vm.catalogLoading" @click="vm.changeCatalogPage(-1)">上一页</button>
            <button type="button" class="mwb-quiet" :disabled="vm.catalogOffset + vm.catalogLimit >= vm.catalog.data.total || vm.catalogLoading" @click="vm.changeCatalogPage(1)">下一页</button>
          </div>
        </div>
        <p v-if="vm.catalogQuery && !vm.catalog.data.items.length" class="mwb-empty">没有找到匹配的港股代码、名称或美股资产。</p>

      </template>
      <p v-else-if="!vm.catalogLoading && !vm.catalogError" class="mwb-empty">点击“美股映射资料库”后浏览完整名单，支持关系编号、资产查询和研究用途筛选。</p>
    </section>

    <footer class="mwb-footer">
      <span>合同 {{ vm.day?.schema_version || "v4.manager_workbench.v1" }}</span>
      <span>RESEARCH_ONLY={{ showText(vm.day?.RESEARCH_ONLY) }} / production_allowed={{ showText(vm.day?.production_allowed) }}</span>
      <span>buy_gate_updated={{ showText(vm.day?.buy_gate_updated) }} / orders_sent={{ showText(vm.day?.orders_sent) }}</span>
      <span v-if="vm.day?.gaps?.length">外层缺口：{{ vm.day.gaps.map(gapText).join("；") }}</span>
      <span>页面不生产选股判定，不触发交易。</span>
    </footer>
  </main>
</template>
