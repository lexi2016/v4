<script setup lang="ts">
import { reactive } from "vue";
import { useWorkbench } from "./useWorkbench";
import type { Lane, Phase, PlanVersion, StockDecision, USFactorSummary } from "./types";
import { LANES, LANE_LABELS, LANE_STATE_LABELS, JOB_STATE_LABELS, PHASE_LABELS,
  showCount, showText, gapText } from "./types";
import { conditionLabel, decisionLabel, evidenceLink, firstReason, humanTime, labelForLane,
  laneEntries, laneResultLabel, metricLabel, stockTitle, researchRows, readableReason,
  researchSections, researchRisks, detailReasons, detailRisks } from "./display";
import "./workbench.css";

const vm = reactive(useWorkbench());
const panels = [
  { key: "stocks", label: "今日名单" },
  { key: "detail", label: "个股详情" },
  { key: "progress", label: "研究进度" },
  { key: "history", label: "计划历史" },
  { key: "reviews", label: "收盘复盘" }
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
function factorSummaryText(summary: USFactorSummary): string {
  const decisions = summary.factor_decision_counts || {};
  return `固定美股来源 ${showCount(summary.us_source_symbol_count)} 个；已配置代理主题 ${showCount(summary.proxy_source_count)} / ${showCount(summary.expected_proxy_source_count)} 个（核验通过 ${showCount(summary.verified_proxy_source_count)}，未知 ${showCount(summary.unknown_proxy_source_count)}）；目标日港股通范围 ${showCount(summary.eligible_hk_scope_count)} 只；因子唯一港股 ${showCount(summary.unique_factor_stock_count)} 只，路径 ${showCount(summary.factor_path_count)} 条，未知港股 ${showCount(summary.unknown_factor_stock_count)} 只。结果：条件观察 ${showCount(decisions.CONDITIONAL_WATCH)}，未入选 ${showCount(decisions.NOT_SELECTED)}，待核 ${showCount(decisions.UNASSESSED)}。这些数量属于不同范围，不能相加。`;
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
        <input id="mwb-date" v-model="vm.dateInput" inputmode="numeric" maxlength="8"
          pattern="[0-9]{8}" placeholder="YYYYMMDD" aria-describedby="mwb-date-hint" />
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
      <div><span>研究截止</span><strong>{{ humanTime(vm.snapshot?.context.cutoff) }}</strong></div>
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

    <section v-if="vm.panel === 'stocks'" class="mwb-panel" aria-label="今日研究名单">
      <div class="mwb-heading">
        <div><h2>{{ LANE_LABELS[vm.laneFilter] }} · {{ vm.decisionFilter ? decisionLabel(vm.decisionFilter) : '独立港股推荐' }}</h2><p>美股映射与超跌是独立推荐；各自采用该路径已保存结论，同股可出现在两处。</p></div>
        <p v-if="vm.dayLoading" role="status">正在读取保存的研究版本…</p>
      </div>
      <nav class="mwb-tabs" aria-label="独立推荐来源">
        <button v-for="lane in (['US_MAPPING', 'OVERSOLD'] as const)" :key="lane" type="button"
          :class="{ active: vm.laneFilter === lane }" :aria-pressed="vm.laneFilter === lane" @click="vm.switchLane(lane)">
          {{ LANE_LABELS[lane] }}推荐 · 严格入选 {{ showCount(vm.day?.data?.recommendation_counts?.[lane]?.selected) }} / 条件观察 {{ showCount(vm.day?.data?.recommendation_counts?.[lane]?.watch) }}
        </button>
      </nav>

      <div v-if="vm.counts" class="mwb-counts" aria-label="本路径完整研究记录分类计数">
        <div><strong>{{ showCount(vm.counts.selected) }}</strong><span>严格入选</span></div>
        <div><strong>{{ showCount(vm.counts.watch) }}</strong><span>条件观察</span></div>
        <div><strong>{{ showCount(vm.counts.unassessed) }}</strong><span>待评估</span></div>
        <div><strong>{{ showCount(vm.counts.observation_only) }}</strong><span>仅观察</span></div>
        <div><strong>{{ showCount(vm.counts.not_selected) }}</strong><span>未入选</span></div>
      </div>
      <p v-else class="mwb-muted">完整分类计数未知（无已保存计数，不能当作 0）。</p>
      <p v-if="vm.day?.data?.recommendation_projection" class="mwb-muted">本路径保存 {{ vm.day.data.recommendation_projection.row_count }} 条研究记录（计数单位：研究记录）；
        {{ vm.day.data.recommendation_projection.hk_relation_row_count }} 条含港股，涉及 {{ vm.day.data.recommendation_projection.distinct_hk_count }} 只。
        分类数量按完整研究记录计，不受分页影响；默认推荐仅含严格入选和条件观察。无港股关系的来源缺口在下方单独查看。</p>

      <section v-if="vm.day?.data?.us_mapping_summary" class="mwb-panel" aria-label="本版本美股映射">
        <h3>本版本美股映射 · 独立保存结论</h3>
        <p>美股来源标的 {{ vm.day.data.us_mapping_summary.source_symbol_count }} 个，保存来源记录 {{ vm.day.data.us_mapping_summary.source_row_count }} 条；
          港股关系 {{ vm.day.data.us_mapping_summary.relation_row_count }} 条，涉及 {{ vm.day.data.us_mapping_summary.mapped_hk_count }} 只港股。</p>
        <p>按美股来源标的计：严格入选 {{ vm.day.data.us_mapping_summary.source_decision_counts.SELECTED ?? '未知' }}，
          条件观察 {{ vm.day.data.us_mapping_summary.source_decision_counts.CONDITIONAL_WATCH ?? '未知' }}，
          未入选 {{ vm.day.data.us_mapping_summary.source_decision_counts.NOT_SELECTED ?? '未知' }}，
          待核 {{ vm.day.data.us_mapping_summary.source_decision_counts.UNASSESSED ?? '未知' }}。
          美股标的数、研究记录数和港股数是不同计量单位；以上只属于美股映射。</p>
        <p v-if="vm.day.data.us_mapping_summary.mixed_source_count">另有 {{ vm.day.data.us_mapping_summary.mixed_source_count }} 个标的包含不同关系结论，逐条保留如下。</p>
        <article v-if="vm.day.data.us_mapping_summary.factor_summary" class="mwb-factor-summary">
          <h4>美股代理日收益因子 · 事后研究候选</h4>
          <p>{{ factorSummaryText(vm.day.data.us_mapping_summary.factor_summary) }}</p>
          <p>收益会话 {{ vm.day.data.us_mapping_summary.factor_summary.source_session || '未知' }}；目标日 {{ vm.day.data.us_mapping_summary.factor_summary.target_date }}，阶段 {{ PHASE_LABELS[vm.day.data.us_mapping_summary.factor_summary.phase] }}。历史暴露有效期间仍可能未知；本结果未做 PIT 验证，也未验证研究效果。</p>
          <p v-if="vm.day.data.us_mapping_summary.factor_summary.paired_review_gap">审核材料缺口：{{ vm.day.data.us_mapping_summary.factor_summary.paired_review_gap }}</p>
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
              <td>{{ LANE_LABELS[vm.laneFilter] }}<small v-if="stock.us_symbol">美股来源 {{ stock.us_symbol }}</small></td>
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

    <footer class="mwb-footer">
      <span>合同 {{ vm.day?.schema_version || "v4.manager_workbench.v1" }}</span>
      <span>RESEARCH_ONLY={{ showText(vm.day?.RESEARCH_ONLY) }} / production_allowed={{ showText(vm.day?.production_allowed) }}</span>
      <span>buy_gate_updated={{ showText(vm.day?.buy_gate_updated) }} / orders_sent={{ showText(vm.day?.orders_sent) }}</span>
      <span v-if="vm.day?.gaps?.length">外层缺口：{{ vm.day.gaps.map(gapText).join("；") }}</span>
      <span>页面不生产选股判定，不触发交易。</span>
    </footer>
  </main>
</template>
