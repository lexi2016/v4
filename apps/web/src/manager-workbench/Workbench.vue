<script setup lang="ts">
import { reactive } from "vue";
import { useWorkbench } from "./useWorkbench";
import type { Lane, Phase, PlanVersion, StockDecision } from "./types";
import { LANES, LANE_LABELS, LANE_STATE_LABELS, JOB_STATE_LABELS, PHASE_LABELS,
  showCount, showText, gapText } from "./types";
import { decisionLabel, evidenceLink, firstReason, humanTime, labelForLane,
  laneDecision, laneResultLabel, metricLabel } from "./display";
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
function changeLaneBySelect(event: Event): void {
  vm.laneFilter = (event.target as HTMLSelectElement).value as typeof vm.laneFilter;
  vm.applyFilters();
}
function changeJobPhase(event: Event): void {
  vm.runPhase = (event.target as HTMLSelectElement).value as "MANUAL" | "RETROSPECTIVE";
}
function stockLane(stock: StockDecision, lane: Lane) {
  return laneDecision(stock, lane);
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
        <div><h2>今日名单</h2><p>按服务端分类和证据时间排序；不在页面重新评分或合并策略。</p></div>
        <p v-if="vm.dayLoading" role="status">正在读取保存的研究版本…</p>
      </div>

      <div v-if="vm.counts" class="mwb-counts" aria-label="完整名单分类计数">
        <div><strong>{{ showCount(vm.counts.selected) }}</strong><span>严格入选</span></div>
        <div><strong>{{ showCount(vm.counts.watch) }}</strong><span>条件观察</span></div>
        <div><strong>{{ showCount(vm.counts.unassessed) }}</strong><span>待评估</span></div>
        <div><strong>{{ showCount(vm.counts.observation_only) }}</strong><span>仅观察</span></div>
        <div><strong>{{ showCount(vm.counts.not_selected) }}</strong><span>未入选</span></div>
      </div>
      <p v-else class="mwb-muted">完整分类计数未知（无已保存计数，不能当作 0）。</p>

      <form class="mwb-filters" @submit.prevent="vm.applyFilters" aria-label="服务端查询筛选">
        <label>分类
          <select :value="vm.decisionFilter" @change="changeDecisionBySelect">
            <option value="">全部分类</option>
            <option value="SELECTED">严格入选</option>
            <option value="CONDITIONAL_WATCH">条件观察</option>
            <option value="UNASSESSED">待评估</option>
            <option value="OBSERVATION_ONLY">仅观察</option>
            <option value="NOT_SELECTED">未入选</option>
          </select>
        </label>
        <label>研究来源
          <select :value="vm.laneFilter" @change="changeLaneBySelect">
            <option value="">全部路径</option>
            <option v-for="lane in LANES" :key="lane" :value="lane">{{ LANE_LABELS[lane] }}</option>
          </select>
        </label>
        <label class="mwb-search">代码 / 名称
          <input v-model="vm.searchDraft" placeholder="例如 HK.00001" />
        </label>
        <button type="submit">查询</button>
      </form>

      <div v-if="vm.day && !vm.day.data" class="mwb-empty">
        {{ vm.day.state === "NOT_RUN" ? "当日有效，但尚未运行／保存研究版本" : "未提供可展示计划" }}
      </div>
      <div v-else-if="vm.stocks.length === 0 && !vm.dayLoading" class="mwb-empty">
        {{ vm.lanes.some(x => x.state === 'READY_EMPTY') ? "研究已完成且有效空集" : "此筛选或版本暂无名单行" }}
      </div>
      <div v-if="vm.stocks.length" class="mwb-table-wrap">
        <table class="mwb-table mwb-stock-table">
          <thead><tr>
            <th scope="col">股票 / 资格</th><th scope="col">总研究分类</th>
            <th scope="col" class="mwb-wide">公告</th><th scope="col" class="mwb-wide">美股映射</th>
            <th scope="col" class="mwb-wide">超跌</th><th scope="col">理由 / 待确认</th>
            <th scope="col" class="mwb-wide">变化与时间</th><th scope="col">详情</th>
          </tr></thead>
          <tbody>
            <tr v-for="stock in vm.stocks" :key="stock.market + ':' + stock.symbol">
              <td><strong class="mwb-symbol">{{ stock.symbol }}</strong>
                <span>{{ stock.name }}</span>
                <small>资格：{{ stock.connect_eligibility || stock.eligibility_status || "待核验" }}</small>
              </td>
              <td><span class="mwb-decision" :data-decision="stock.decision">{{ decisionLabel(stock.decision) }}</span>
                <small v-if="stockLane(stock, 'STAGE_REFERENCE')">阶段参考 · 观察</small>
                <small v-if="stockLane(stock, 'CLOSE_REFERENCE')">尾盘参考 · 观察</small>
              </td>
              <td class="mwb-wide">{{ laneResultLabel(stock, "ANNOUNCEMENT") }}</td>
              <td class="mwb-wide">{{ laneResultLabel(stock, "US_MAPPING") }}</td>
              <td class="mwb-wide">{{ laneResultLabel(stock, "OVERSOLD") }}</td>
              <td><div class="mwb-main-reason">{{ firstReason(stock) }}</div>
                <small>待确认：{{ stock.conditions?.length ? stock.conditions[0] : "无已记录条件" }}</small>
              </td>
              <td class="mwb-wide"><span>{{ stock.changed || "变化未提供" }}</span>
                <small>{{ humanTime(stock.available_at) }}</small>
              </td>
              <td><button type="button" class="mwb-detail-link"
                :aria-label="'查看 ' + stock.symbol + ' ' + stock.name + ' 详情'"
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
          <span>{{ vm.offset + 1 }}–{{ Math.min(vm.pagination.total, vm.offset + vm.stocks.length) }}</span>
          <button type="button" :disabled="vm.dayLoading || vm.offset + vm.limit >= vm.pagination.total"
            @click="vm.setOffset(vm.offset + vm.limit)">下一页</button>
        </div>
      </div>
    </section>

    <section v-if="vm.panel === 'detail'" class="mwb-panel" aria-label="个股研究详情">
      <div class="mwb-heading"><h2>个股研究详情 · {{ vm.detailSymbol || "未选择" }}</h2>
        <button type="button" class="mwb-quiet" @click="vm.showPanel('stocks')">返回名单</button></div>
      <p v-if="vm.detailLoading" role="status">正在读取同 run_id 详情…</p>
      <p v-if="vm.detailError" class="mwb-alert" role="alert">{{ vm.detailError }}</p>
      <template v-if="vm.detail?.data?.stock">
        <div class="mwb-stock-top">
          <h3>{{ vm.detail.data.stock.symbol }} {{ vm.detail.data.stock.name }}</h3>
          <span class="mwb-decision" :data-decision="vm.detail.data.stock.decision">
            {{ decisionLabel(vm.detail.data.stock.decision) }}
          </span>
          <span>资格：{{ vm.detail.data.stock.connect_eligibility || vm.detail.data.stock.eligibility_status || "待核验" }}</span>
        </div>
        <div class="mwb-detail-grid">
          <article><h3>依据</h3><p v-for="reason in vm.detail.data.stock.reasons" :key="reason">{{ reason }}</p>
            <p v-if="!vm.detail.data.stock.reasons?.length">暂无可核验依据</p></article>
          <article><h3>待确认条件</h3><p v-for="v in vm.detail.data.stock.conditions" :key="v">{{ v }}</p>
            <p v-if="!vm.detail.data.stock.conditions?.length">未提供</p></article>
          <article><h3>失效条件</h3><p v-for="v in vm.detail.data.stock.invalidation_conditions" :key="v">{{ v }}</p>
            <p v-if="!vm.detail.data.stock.invalidation_conditions?.length">未提供</p></article>
          <article><h3>风险</h3><p v-for="v in vm.detail.data.stock.risks" :key="v">{{ v }}</p>
            <p v-if="!vm.detail.data.stock.risks?.length">未提供</p></article>
        </div>
        <h3>各研究路径（不跨路径升级结论）</h3>
        <div class="mwb-lane-grid">
          <article v-for="lane in LANES" :key="lane" class="mwb-lane-card">
            <h4>{{ LANE_LABELS[lane] }}</h4>
            <p>{{ laneResultLabel(vm.detail.data.stock, lane) }}
              <span v-if="lane === 'STAGE_REFERENCE' || lane === 'CLOSE_REFERENCE'"> · 仅观察参考</span></p>
            <template v-if="stockLane(vm.detail.data.stock, lane)">
              <dl v-for="[key, val] in Object.entries(stockLane(vm.detail.data.stock, lane) || {})"
                :key="key" class="mwb-fact">
                <dt>{{ key }}</dt><dd>{{ showText(val) }}</dd>
              </dl>
            </template>
            <p v-else class="mwb-muted">该路径尚未提供研究判定。</p>
          </article>
        </div>
        <details class="mwb-evidence">
          <summary>证据身份、原始引用与校验缺口</summary>
          <p>本行 evidence_ids：{{ vm.detail.data.stock.evidence_ids?.join(", ") || "未提供" }}</p>
          <article v-for="ev in vm.detail.data.evidence_refs || []" :key="ev.evidence_id">
            <strong>{{ ev.evidence_id }} · {{ ev.owner }}</strong>
            <p>来源 {{ ev.source_date || ev.session || "未知" }} · 可用 {{ humanTime(ev.available_at) }} · {{ ev.verification || "CANNOT_CONFIRM" }}</p>
            <p>SHA256 {{ ev.sha256 || "未知" }} · manifest {{ ev.manifest_ref || "未知" }}</p>
            <a v-if="evidenceLink(ev.original_url)" :href="evidenceLink(ev.original_url) || undefined"
              target="_blank" rel="noopener noreferrer">打开原文</a>
          </article>
          <p v-for="gap in vm.detail.data.gaps || []" :key="gapText(gap)">{{ gapText(gap) }}</p>
        </details>
      </template>
      <p v-else-if="!vm.detailLoading && !vm.detailError" class="mwb-muted">从今日名单选择股票；详情只读指定目标日和版本。</p>
    </section>

    <section v-if="vm.panel === 'progress'" class="mwb-panel" aria-label="研究任务进度">
      <div class="mwb-heading"><div><h2>研究进度</h2><p>查看已保存 lane 及后台任务；离开页面不会取消后台任务。</p></div></div>
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
      <p v-else class="mwb-empty">尚无已保存的 lane 进度；未知不代表全部未运行。</p>
      <div class="mwb-task-form">
        <h3>创建研究任务（POST；不会直接提交交易）</h3>
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
      <div v-if="vm.history?.data?.entries?.length" class="mwb-history">
        <article v-for="(entry,i) in vm.history.data.entries" :key="(entry.run_id || entry.original_run_id || i) + ':' + i">
          <div><strong>{{ entry.origin === 'LEGACY' ? "LEGACY · 原样历史" : "NEW · 新计划" }}</strong>
            <span v-if="entry.phase === 'RETROSPECTIVE'" class="mwb-retro">RETROSPECTIVE · 事后回看</span></div>
          <p>{{ entry.target_date }} · {{ entry.phase ? PHASE_LABELS[entry.phase] : "旧阶段未知" }}
            · 记录于 {{ humanTime(entry.recorded_at || entry.generated_at) }}</p>
          <p>原 run：{{ entry.original_run_id || entry.run_id || "未知" }}
            · 原 schema：{{ entry.original_schema || "未知" }}</p>
          <p>原 SHA：{{ entry.original_sha256 || "未知" }} · 校验：{{ entry.verification || "CANNOT_CONFIRM" }}</p>
          <p v-for="gap in entry.gaps || []" :key="gapText(gap)" class="mwb-muted">缺口：{{ gapText(gap) }}</p>
        </article>
      </div>
      <p v-else-if="!vm.historyLoading && !vm.historyError" class="mwb-empty">当日尚无可读取历史或来源未知。</p>
      <p v-for="gap in vm.history?.data?.gaps || []" :key="gapText(gap)" class="mwb-muted">{{ gapText(gap) }}</p>
    </section>

    <section v-if="vm.panel === 'reviews'" class="mwb-panel" aria-label="收盘研究复盘">
      <div class="mwb-heading"><div><h2>收盘复盘 · 完整 Top20 对照</h2>
        <p>统计由 A 引擎生成、B 保存。观察贡献不计入严格入选。</p></div>
        <button type="button" class="mwb-quiet" @click="vm.loadReview">重新读取复盘</button></div>
      <p v-if="vm.reviewLoading" role="status">读取复盘中…</p>
      <p v-if="vm.reviewError" class="mwb-alert" role="alert">{{ vm.reviewError }}</p>
      <template v-if="vm.review?.data">
        <p>榜单日期：{{ vm.review.data.ranking_date || "未知" }} · 模式：{{ vm.review.data.mode || "未知" }}
          · 实际榜单范围：{{ vm.review.data.evaluation_scope_ref || "未知" }}</p>
        <div class="mwb-counts mwb-review-metrics">
          <div><strong>{{ metricLabel(vm.review.data.strict_coverage, vm.review.data.top20?.length === 20) }}</strong><span>严格覆盖率（仅 SELECTED）</span></div>
          <div><strong>{{ metricLabel(vm.review.data.extended_coverage, vm.review.data.top20?.length === 20) }}</strong><span>扩展覆盖率（含条件观察）</span></div>
          <div><strong>{{ showCount(vm.review.data.selection_denominator) }}</strong><span>实际入选名单分母</span></div>
        </div>
        <p v-if="!vm.review.data.top20 || vm.review.data.top20.length !== 20"
          class="mwb-alert" role="status">榜单缺失或不足完整20行，不能宣称完整Top20覆盖率。</p>
        <div v-if="vm.review.data.top20?.length" class="mwb-table-wrap">
          <table class="mwb-table">
            <thead><tr><th scope="col">名次</th><th scope="col">股票</th><th scope="col">实际变化</th>
              <th scope="col">严格命中</th><th scope="col">扩展命中</th>
              <th scope="col">贡献路径</th><th scope="col">漏选原因</th></tr></thead>
            <tbody><tr v-for="(item,i) in vm.review.data.top20" :key="item.symbol + ':' + i">
              <td>{{ item.rank }}</td><td>{{ item.symbol }} {{ item.name || "" }}</td>
              <td>{{ showText(item.actual_change) }}</td>
              <td>{{ item.strict_hit === null || item.strict_hit === undefined ? "未知" : (item.strict_hit ? "是" : "否") }}</td>
              <td>{{ item.extended_hit === null || item.extended_hit === undefined ? "未知" : (item.extended_hit ? "是" : "否") }}</td>
              <td>{{ item.matched_lanes?.map(labelForLane).join("、") || "未提供" }}</td>
              <td>{{ item.missed_reason || "未提供" }}</td>
            </tr></tbody>
          </table>
        </div>
        <div class="mwb-detail-grid">
          <article><h3>策略新增覆盖（服务端结果）</h3>
            <pre>{{ showText(vm.review.data.lane_incremental) }}</pre></article>
          <article><h3>漏选原因（服务端结果）</h3>
            <pre>{{ showText(vm.review.data.missed_reasons) }}</pre></article>
        </div>
        <p v-for="gap in vm.review.data.gaps || []" :key="gapText(gap)" class="mwb-muted">缺口：{{ gapText(gap) }}</p>
      </template>
      <p v-else-if="!vm.reviewLoading && !vm.reviewError" class="mwb-empty">
        尚无同目标日、同计划 run_id 的有效收盘复盘。
      </p>
    </section>

    <footer class="mwb-footer">
      <span>合同 {{ vm.day?.schema_version || "v4.manager_workbench.v1" }}</span>
      <span>research_only={{ showText(vm.day?.research_only) }} / production_allowed={{ showText(vm.day?.production_allowed) }}</span>
      <span>buy_gate_updated={{ showText(vm.day?.buy_gate_updated) }} / orders_sent={{ showText(vm.day?.orders_sent) }}</span>
      <span v-if="vm.day?.gaps?.length">外层缺口：{{ vm.day.gaps.map(gapText).join("；") }}</span>
      <span>页面不生产选股判定，不触发交易。</span>
    </footer>
  </main>
</template>
