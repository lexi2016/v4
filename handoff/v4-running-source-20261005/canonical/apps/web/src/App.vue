<script setup lang="ts">


import TaskStatusView from "./views/TaskStatusView.vue";
import ReviewView from "./views/ReviewView.vue";
import ResearchView from "./views/ResearchView.vue";
import GlobalIndustryMap from "./components/research/GlobalIndustryMap.vue";
import WechatMentionPool from "./components/research/WechatMentionPool.vue";
import { useAppShell } from "./app_shell/useAppShell";
const {
  stageDefinitions,
  closingTimeline,
  poolRows,
  poolEvidenceReason,
  poolEvidenceDetails,
  poolRowCode,
  poolRowName,
  poolRowSource,
  poolRowSourceLane,
  poolCountLabel,
  poolRowSignalDate,
  formatPercent,
  formatDateInput,
  evidenceValue,
  rowCode,
  rowName,
  rowRank,
  aShareChangePct,
  rowSupport,
  rowPressure,
  rowInvalidation,
  rowNextEvidence,
  rowScore,
  qualityScore,
  stageCountText,
  stageMarketCountText,
  hkChangeLabel,
  rowMissingFields,
  hitTop20,
  reviewClassification,
  selectedDate,
  pool,
  loading,
  loadError,
  selectedStage,
  stageWorkbench,
  stageLoading,
  stageError,
  stageRunStatus,
  navigationStatus,
  taskStatusActive,
  researchActive,
  researchArchiveEntry,
  closeReviewActive,
  reviewFocus,
  reviewTitle,
  runtimeLabel,
  closeReviewLoading,
  closeReviewError,
  closeReviewPayload,
  isHkObservationOnlyDate,
  nextFutureTargetDate,
  nextHkTargetDate,
  selectedDateContext,
  dateInputMin,
  dateInputMax,
  dateInputTitle,
  currentStageDefinition,
  isPreopenStage,
  aRows,
  hkRows,
  canLoadWechatMentions,
  collapsedPools,
  preselectionGroups,
  togglePool,
  isWechatPool,
  isBaimaoPool,
  isCompactResearchPool,
  referenceMode,
  v11OpeningFilter,
  stageSummary,
  aSummary,
  showAStageEvidenceGap,
  closeReview,
  modelMetric,
  stageUnionMetric,
  closeReviewEvidenceLabel,
  reviewEvidenceGaps,
  hkChangeValue,
  hkScoreLabel,
  showNavigationStatus,
  openTaskStatus,
  openResearch,
  openManagerSelection,
  scrollToPool,
  openNextFutureTargetPool,
  openNextHkTargetPool,
  timelineStageStatus,
  timelineStageCounts,
  loadStage,
  loadCloseReview,
  ensureStage,
  onDateInputChange,
} = useAppShell();
</script>

<template>
  <main class="dashboard-shell">
    <header class="page-header">
      <div>
        <h1>V4 阶段选股</h1>
        <p>阶段选股只读取同一 date + stage 的 A股与港股通阶段工作台；只读观察，不打开 BUY gate，不接交易接口，不生成 live order。</p>
      </div>
      <span class="runtime-badge">{{ runtimeLabel }}</span>
    </header>

    <section class="control-panel" aria-label="页面控制">
      <label>{{ researchActive ? "研究自然日" : "交易日" }}
        <input
          type="date"
          aria-label="交易日（日历选择）"
          :value="formatDateInput(selectedDate)"
          :min="dateInputMin"
          :max="dateInputMax"
          :title="dateInputTitle"
          @change="onDateInputChange"
        />
      </label>
      <button
        v-if="nextFutureTargetDate"
        type="button"
        data-testid="next-future-target-pool"
        @click="openNextFutureTargetPool"
      >查看次日预选池：{{ formatDateInput(nextFutureTargetDate) }}</button>
      <button
        v-if="nextHkTargetDate"
        type="button"
        data-testid="next-hk-observation-target-pool"
        @click="openNextHkTargetPool"
      >查看下一港股开市日预选池：{{ formatDateInput(nextHkTargetDate) }}</button>
      <label>阶段
        <select v-model="selectedStage" aria-label="阶段" @change="loadStage()">
          <option v-for="stage in stageDefinitions" :key="stage.id" :value="stage.id">{{ stage.label }}</option>
        </select>
      </label>
      <button type="button" :disabled="stageLoading || closeReviewLoading" @click="closeReviewActive ? loadCloseReview(reviewFocus, true) : loadStage()">刷新快照</button>
      <span class="runtime-state">{{ researchActive ? "研究入口按自然日导航；阶段入口按A股或港股开市日导航" : "V4 · A/HK按各自市场日历导航；回执不代表进程存活，运行状态见任务页" }}</span>
    </section>
    <small v-if="selectedDate" class="selected-date-context" data-testid="selected-date-context">{{ selectedDateContext }}</small>
    <p v-if="isHkObservationOnlyDate" class="navigation-status hk-observation-status" role="status">
      港股开市 · 港股通/南向暂停，仅作研究观察。若使用最近有效且可追溯的既有标的池，会保留其原始目标日、信号日与 SHA；无有效池则 CANNOT_CONFIRM。A 股仍按 A 股日历独立处理，BUY gate 不变。
    </p>

    <nav class="entry-nav" aria-label="功能入口">
      <button :class="{ active: !taskStatusActive && !researchActive && !closeReviewActive }" type="button" @click="loadStage()">阶段选股</button>
      <button type="button" @click="scrollToPool()">D-1 预选池</button>
      <button :class="{ active: researchActive }" type="button" @click="openResearch()">研报决策台</button>
      <button type="button" @click="openManagerSelection()">经理选股工作台</button>
      <button :class="{ active: taskStatusActive }" type="button" @click="openTaskStatus()">任务状态</button>
      <button :class="{ active: closeReviewActive && reviewFocus === 'A' }" :aria-pressed="closeReviewActive && reviewFocus === 'A'" type="button" @click="loadCloseReview('A')">A股复盘</button>
      <button class="entry-nav-link" :class="{ active: closeReviewActive && reviewFocus === 'research' }" :aria-pressed="closeReviewActive && reviewFocus === 'research'" type="button" @click="loadCloseReview('research')">研究复盘</button>
      <a class="entry-nav-link" href="http://127.0.0.1:8910/a-share/review" target="_blank" rel="noopener noreferrer">原版 Vibe · 8910</a>
    </nav>
    <p v-if="navigationStatus" class="navigation-status" role="status">{{ navigationStatus }}</p>

    <TaskStatusView
      v-if="taskStatusActive"
      :date="selectedDate"
      :stage-summary="stageSummary"
      :current-stage-id="selectedStage"
    />
    <ResearchView
      v-else-if="researchActive"
      :archive-date="selectedDate"
      :initial-feed-filter="researchArchiveEntry ? 'wechat' : 'latest'"
    />
    <template v-else>

    <GlobalIndustryMap v-if="!closeReviewActive" :target-date="selectedDate" />

    <section v-if="!closeReviewActive" class="panel timeline-panel" aria-label="七阶段上下文">
      <div class="section-heading">
        <div><span class="eyebrow">阶段分组主视图</span><h2>七阶段上下文 v2</h2></div>
        <p>{{ selectedDate }} · {{ currentStageDefinition.label }} · A股 {{ stageCountText(stageWorkbench?.selected_a_rows) }} / 港股 {{ stageMarketCountText(stageWorkbench?.markets?.HK, stageWorkbench?.selected_hk_rows) }}</p>
      </div>
      <div class="timeline-grid">
        <button
          v-for="stage in stageDefinitions" :key="stage.id" type="button"
          :class="{ current: !closeReviewActive && selectedStage === stage.id }" @click="loadStage(stage.id)"
        >
          <b>{{ stage.timeline }}</b>
          <span>{{ timelineStageStatus(stage.id) }}</span>
          <small>{{ timelineStageCounts(stage.id) }}</small>
        </button>
        <button
          v-for="(label, index) in closingTimeline" :key="label" type="button"
          :class="{ current: index === 0 && closeReviewActive }"
          @click="index === 0 ? loadCloseReview('HK') : showNavigationStatus(label)"
        >
          <b>{{ label }}</b>
            <span>{{ index === 0 && closeReviewActive ? "已加载指定日期复盘" : (index < 3 ? "复盘入口保留" : "未到验收批次") }}</span>
          <small>{{ index === 0 ? (closeReviewActive ? `${selectedDate} · 只读` : "点击加载只读收盘复盘") : "当前不冒充完成" }}</small>
        </button>
      </div>
    </section>

    <section v-if="!closeReviewActive" class="panel stage-panel">
      <div class="section-heading">
        <div><span class="eyebrow">当前阶段</span><h2>{{ currentStageDefinition.label }} 阶段</h2></div>
        <p v-if="stageWorkbench">{{ stageWorkbench.stage.status }} · {{ stageWorkbench.stage.window || currentStageDefinition.label }}</p>
      </div>
      <div class="stage-actions">
        <button type="button" :disabled="stageLoading || !selectedDate" @click="ensureStage(false)">运行 / 恢复当前阶段</button>
        <button type="button" :disabled="stageLoading || !selectedDate" @click="ensureStage(true)">强制重新物化</button>
        <span v-if="referenceMode" class="reference-label">参考快照 · WATCH_ONLY</span>
        <span v-if="stageRunStatus">最近运行：{{ stageRunStatus }}</span>
      </div>
      <section class="stage-lineage-panel" aria-label="阶段运行血缘">
        <strong>阶段运行血缘</strong>
        <div v-if="stageWorkbench?.stage_lineage" class="stage-lineage-grid">
          <article v-if="stageWorkbench.stage_lineage.natural" class="stage-lineage-card">
            <b>{{ stageWorkbench.stage_lineage.natural.label || "ORIGINAL_NATURAL_RUN" }}</b>
            <span>status={{ stageWorkbench.stage_lineage.natural.status || "CANNOT_CONFIRM" }}</span>
            <span>origin={{ stageWorkbench.stage_lineage.natural.origin || "ORIGINAL_NATURAL_RUN" }}</span>
            <span>receipt_sha256</span><code>{{ stageWorkbench.stage_lineage.natural.receipt_sha256 || "CANNOT_CONFIRM" }}</code>
            <span>write={{ stageWorkbench.stage_lineage.natural.write_performed === true ? "true" : "false" }}</span>
          </article>
          <article v-if="stageWorkbench.stage_lineage.recovery" class="stage-lineage-card">
            <b>{{ stageWorkbench.stage_lineage.recovery.label || "CONTROLLED_RECOVERY" }}</b>
            <span>status={{ stageWorkbench.stage_lineage.recovery.status || "CANNOT_CONFIRM" }}</span>
            <span>origin={{ stageWorkbench.stage_lineage.recovery.origin || "CONTROLLED_RECOVERY" }}</span>
            <span>receipt_sha256</span>
            <code v-if="stageWorkbench.stage_lineage.recovery.receipt_sha256">{{ stageWorkbench.stage_lineage.recovery.receipt_sha256 }}</code>
            <template v-else-if="stageWorkbench.stage_lineage.recovery.receipt_sha256_by_market">
              <code v-for="(sha, market) in stageWorkbench.stage_lineage.recovery.receipt_sha256_by_market" :key="market">{{ market }}={{ sha }}</code>
            </template>
            <code v-else>CANNOT_CONFIRM</code>
            <span>write={{ stageWorkbench.stage_lineage.recovery.write_performed === true ? "true" : "false" }}</span>
          </article>
        </div>
        <p v-else class="evidence-gap">CANNOT_CONFIRM：当前响应未提供可验证的 natural/recovery receipt 血缘。</p>
        <p v-if="stageWorkbench?.stage_lineage?.cannot_confirm?.length" class="evidence-gap">
          {{ stageWorkbench.stage_lineage.cannot_confirm.join("、") }}
        </p>
      </section>
      <div v-if="v11OpeningFilter" class="model-contract" aria-label="竞价二筛模型">
        <strong>v1.1 竞价二筛</strong>
        <span>v1.1 A股适配器，不是港股精确公式</span>
        <code>{{ v11OpeningFilter.model_id }}</code>
        <small>
          <span>港股 {{ v11OpeningFilter.markets?.HK?.refresh_time || "09:20" }} 刷新 · A股 {{ v11OpeningFilter.markets?.A?.refresh_time || "09:25" }} 刷新</span>
          · 上游预选 {{ aSummary.requested_rows ?? "不可确认" }} / 同截点证据 {{ aSummary.source_rows ?? "不可确认" }} / 阶段候选 {{ aSummary.candidate_count ?? "不可确认" }} / 入选 {{ stageWorkbench?.selected_a_rows ?? "不可确认" }}
        </small>
      </div>
      <p v-if="v11OpeningFilter && showAStageEvidenceGap" class="evidence-note">A股股票仍保留在独立 D-1 池；没有伪造阶段候选。</p>
      <p v-if="stageLoading" role="status">正在读取 {{ selectedDate }} / {{ selectedStage }}。</p>
      <p v-else-if="stageError" role="alert">{{ stageError }}</p>
      <p v-else-if="stageWorkbench" class="stage-display-status">{{ stageWorkbench.stage.display_status }}</p>

      <div class="market-columns">
        <section class="market-column" aria-label="A股候选">
          <div class="market-title"><h3>A股</h3><span>{{ stageCountText(stageWorkbench?.selected_a_rows) }} 条</span></div>
          <p v-if="stageWorkbench?.markets?.A?.selection_mode === 'BACKFILL'" class="evidence-note">
            历史回补 BACKFILL · {{ stageWorkbench?.markets?.A?.backfill_run_ids?.join("、") || stageWorkbench?.markets?.A?.backfill_run_id || "run id CANNOT_CONFIRM" }} · selection {{ stageWorkbench?.markets?.A?.selection_manifest_receipt_verified ? "manifest/receipt 已验证" : "manifest/receipt CANNOT_CONFIRM" }} · runner receipt {{ stageWorkbench?.markets?.A?.runner_receipt_verified ? "已验证" : "CANNOT_CONFIRM" }}
          </p>
          <p v-if="stageWorkbench?.markets?.A?.cannot_confirm?.includes('BACKFILL_NAMESPACE_CONFLICT')" class="evidence-gap">BACKFILL_NAMESPACE_CONFLICT：多个回补批次的优先级无法确认。</p>
          <div v-if="!aRows.length" class="empty-card">
            <strong>A股无主表候选</strong>
            <span>{{ currentStageDefinition.label }} 阶段 · source rows {{ stageCountText(aSummary.source_rows) }} / requested {{ stageCountText(aSummary.requested_rows ?? aSummary.source_rows) }}</span>
            <p>{{ stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
          </div>
          <article v-for="row in aRows" :key="rowCode(row)" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ rowName(row) }}</strong><span>{{ rowCode(row) }} · 排名 {{ rowRank(row) }}</span></div><b>{{ row.stage_display_decision || "观察" }}</b></div>
            <dl>
              <div><dt>涨幅</dt><dd>{{ formatPercent(aShareChangePct(row)) }}</dd></div>
              <div><dt>阶段分</dt><dd>{{ rowScore(row) }}</dd></div>
              <div><dt>新闻分</dt><dd>{{ qualityScore(row.news_quality_score) }}</dd></div>
              <div><dt>研报分</dt><dd>{{ qualityScore(row.research_quality_score) }}</dd></div>
              <div><dt>支撑位</dt><dd>{{ evidenceValue(rowSupport(row)) }}</dd></div>
              <div><dt>压力位</dt><dd>{{ evidenceValue(rowPressure(row)) }}</dd></div>
              <div><dt>失效位</dt><dd>{{ evidenceValue(rowInvalidation(row)) }}</dd></div>
              <div><dt>{{ row.next_validation_time ? "下次" : "数据截止" }}</dt><dd>{{ rowNextEvidence(row) || "当前阶段未提供验证时间" }}</dd></div>
            </dl>
          </article>
        </section>
        <section class="market-column" :aria-label="stageWorkbench?.markets?.HK?.display_mode === 'OBSERVATION_UNVERIFIED' ? '港股通观察行' : '港股通候选'">
          <div class="market-title"><h3>{{ stageWorkbench?.markets?.HK?.display_mode === "OBSERVATION_UNVERIFIED" ? "港股通观察行" : `港股通${isPreopenStage ? "09:20二筛" : "二筛"}` }}</h3><span>{{ stageMarketCountText(stageWorkbench?.markets?.HK, stageWorkbench?.selected_hk_rows) }}<template v-if="!['CANNOT_CONFIRM', 'OBSERVATION_UNVERIFIED', 'READY_EMPTY'].includes(stageWorkbench?.markets?.HK?.display_mode || '')"> 条</template></span></div>
          <p v-if="stageWorkbench?.markets?.HK?.display_mode === 'OBSERVATION_UNVERIFIED'" class="evidence-note">未验证原因：{{ stageWorkbench.markets.HK.display_reasons?.join("、") || "SelectionStore 或执行绑定不足" }}</p>
          <p v-if="stageWorkbench?.markets?.HK?.selection_mode === 'BACKFILL'" class="evidence-note">
            历史回补 BACKFILL · {{ stageWorkbench?.markets?.HK?.backfill_run_ids?.join("、") || stageWorkbench?.markets?.HK?.backfill_run_id || "run id CANNOT_CONFIRM" }} · selection {{ stageWorkbench?.markets?.HK?.selection_manifest_receipt_verified ? "manifest/receipt 已验证" : "manifest/receipt CANNOT_CONFIRM" }} · runner receipt {{ stageWorkbench?.markets?.HK?.runner_receipt_verified ? "已验证" : "CANNOT_CONFIRM" }}
          </p>
          <p v-if="stageWorkbench?.markets?.HK?.cannot_confirm?.includes('BACKFILL_NAMESPACE_CONFLICT')" class="evidence-gap">BACKFILL_NAMESPACE_CONFLICT：多个回补批次的优先级无法确认。</p>
          <div v-if="stageWorkbench && !hkRows.length" class="empty-card">
            <strong>{{ stageWorkbench.markets?.HK?.display_mode === "CANNOT_CONFIRM" ? "待确认/缺少正式产物" : stageWorkbench.markets?.HK?.display_mode === "READY_EMPTY" ? "正式结果为空（READY_EMPTY）" : stageWorkbench.markets?.HK?.display_mode === "OBSERVATION_UNVERIFIED" ? "观察数据未验证" : "港股通该阶段无可确认候选" }}</strong><p>{{ stageWorkbench.markets?.HK?.display_mode === "CANNOT_CONFIRM" ? stageWorkbench.markets.HK.display_reasons?.join("、") || stageWorkbench.markets.HK.cannot_confirm?.join("、") || "缺少正式 SelectionStore 产物" : stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
          </div>
          <p v-if="isPreopenStage && hkRows.length" class="evidence-note">09:20阶段只做初筛；支撑/压力/失效位从09:30后阶段生成。</p>
          <article v-for="row in hkRows" :key="rowCode(row)" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ rowName(row) }}</strong><span>{{ rowCode(row) }} · 排名 {{ rowRank(row) }}</span></div><b>{{ ['CANNOT_CONFIRM', 'OBSERVATION_UNVERIFIED'].includes(stageWorkbench?.markets?.HK?.display_mode || '') ? "观察 · 未验证" : row.stage_display_decision || "观察" }}</b></div>
            <dl>
              <div><dt>{{ hkChangeLabel(row) }}</dt><dd>{{ hkChangeValue(row) }}</dd></div>
              <div><dt>{{ hkScoreLabel(row) }}</dt><dd>{{ rowScore(row) }}</dd></div>
              <div v-if="isPreopenStage && typeof row.current_change_pct === 'number'"><dt>快照涨幅</dt><dd>{{ formatPercent(row.current_change_pct) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>支撑位</dt><dd>{{ evidenceValue(row.support_primary_price) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>压力位</dt><dd>{{ evidenceValue(row.pressure_price) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>失效位</dt><dd>{{ evidenceValue(row.invalidation_price) }}</dd></div>
              <div><dt>下次</dt><dd>{{ row.next_validation_time || "当前阶段未提供验证时间" }}</dd></div>
            </dl>
            <p v-if="!isPreopenStage && rowMissingFields(row).length" class="evidence-gap">待补字段：{{ rowMissingFields(row).join("、") }}</p>
          </article>
        </section>
      </div>
    </section>

    <section v-else class="review-panel" :aria-label="reviewFocus === 'HK' ? '16:08 港股通收盘复盘' : reviewTitle">
      <div class="section-heading">
        <div><span class="eyebrow">EXACT_DATE_REVIEW</span><h2>{{ reviewTitle }}</h2></div>
        <p>{{ closeReview.trade_date || closeReviewPayload?.trade_date || selectedDate }} · 只读，不回填 BUY gate</p>
      </div>
      <p v-if="closeReviewLoading" class="review-loading" role="status">正在读取 {{ selectedDate }} 的{{ reviewTitle }}。</p>
      <p v-else-if="closeReviewError" class="review-loading error" role="alert">{{ closeReviewError }}</p>
      <ReviewView v-else-if="closeReviewPayload" :payload="closeReviewPayload" :focus="reviewFocus" />
      <template v-else>
        <div class="review-status-line">
          <strong>{{ closeReview.status || "REFERENCE_NOT_IMPORTED" }}</strong>
          <span>{{ closeReview.primary_kpi || "全港股通收盘涨幅Top20覆盖率" }}</span>
          <small>{{ closeReviewEvidenceLabel }} · production_allowed=false · orders_sent=false</small>
        </div>
        <div class="review-metric-grid">
          <article><span>0.2 模型</span><strong>{{ hitTop20(modelMetric) }}</strong><small>入选 {{ modelMetric.selected_count ?? "不可用" }} · 覆盖 {{ modelMetric.coverage_pct ?? "不可用" }}%</small></article>
          <article><span>七阶段并集</span><strong>{{ hitTop20(stageUnionMetric) }}</strong><small>入选 {{ stageUnionMetric.selected_count ?? "不可用" }} · 覆盖 {{ stageUnionMetric.coverage_pct ?? "不可用" }}%</small></article>
          <article><span>收盘 Top20</span><strong>{{ closeReview.row_counts?.close_top20 ?? closeReview.close_top20?.length ?? 0 }}</strong><small>第一 KPI 的真实收盘标签</small></article>
          <article><span>阶段证据行</span><strong>{{ closeReview.row_counts?.stage_rows ?? 0 }}</strong><small>仅同日七阶段，不跨日回填</small></article>
        </div>
        <div v-if="reviewEvidenceGaps.length" class="review-warning">
          <strong>证据边界</strong>
          <span v-for="item in reviewEvidenceGaps" :key="item">{{ item }}</span>
        </div>
        <div class="review-table-wrap">
          <table>
            <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>0.2</th><th>阶段并集</th><th>归因</th></tr></thead>
            <tbody>
              <tr v-for="row in closeReview.top20_attribution ?? []" :key="row.code">
                <td>{{ row.rank ?? "-" }}</td><td>{{ row.code || "-" }}</td><td>{{ row.name || "-" }}</td>
                <td>{{ formatPercent(row.pct_chg_close) }}</td>
                <td>{{ row.model_0_2_hit ? "命中" : "未命中" }}</td>
                <td>{{ row.stage_union_hit ? "命中" : "未命中" }}</td>
                <td>{{ reviewClassification(row.classification) }}</td>
              </tr>
              <tr v-if="!(closeReview.top20_attribution?.length)"><td colspan="7">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <section id="unifiedPreselectPanel" class="panel pool-panel" aria-label="统一预选池">
      <div class="section-heading"><div><span class="eyebrow">D-1 数据</span><h2>D-1 预选池</h2></div><p>{{ pool?.data_status || "等待读取" }}</p></div>
      <p v-if="loading" role="status">正在读取 {{ selectedDate }} 的 D-1 预选池。</p>
      <p v-else-if="loadError" role="alert">{{ loadError }}</p>
      <div v-else id="preselectGroups" class="independent-pool-grid">
        <section v-for="group in preselectionGroups" :id="group.domId" :key="group.pool_id" class="market-column" :aria-label="group.display_name || group.pool_id">
          <div class="market-title">
            <h3>{{ group.display_name || group.pool_id }}</h3>
            <span>{{ poolCountLabel(group) }}</span>
            <button type="button" :aria-expanded="!collapsedPools[group.pool_id]" @click="togglePool(group.pool_id)">
              {{ collapsedPools[group.pool_id] ? "展开" : "收起" }}
            </button>
          </div>
          <p v-if="group.pool_id === 'a_all_pool_summary'" class="preview-note">只要汇总池有股票即可进行阶段选股，无需所有子池齐全。</p>
          <p v-if="group.status" class="preview-note"><strong>{{ group.status }}</strong><span v-if="poolEvidenceReason(group)"> · {{ poolEvidenceReason(group) }}</span></p>
          <details v-if="group.cannot_confirm?.length || group.source_path" class="preview-note">
            <summary>来源与更新缺口（不阻断其他有效池）</summary>
            <p>所选目标日：{{ selectedDate }} · producer：{{ group.producer_id || "未确认" }}</p>
            <p>来源路径：{{ group.source_path || "未提供可核验来源路径" }}</p>
            <p v-for="(item, index) in poolEvidenceDetails(group)" :key="index">{{ typeof item === "string" ? item : item.reason || item.description || "CANNOT_CONFIRM" }}</p>
            <p v-if="['a_d1_fupan_watchlist_pool', 'a_d1_stage7_fenshi_review_pool'].includes(group.pool_id)">应消费前一交易日收盘/Stage原始证据，经既有17:30/18:00预选池链物化；缺输入不复制旧目标日行，也不手改status。恢复步骤见本机缺口清单。</p>
            <p v-if="group.pool_id === 'wechat_public_account_v3_preselect'">既有公众号同步计划09:01/20:01；须核对文章发布日、effective_date、原始输入与回执，空列表不代表已更新。</p>
            <p v-if="group.pool_id === 'a_share_baimao_research_map'">白毛池依赖已发布observations及精确日期映射；当前更新时刻未取证，不以latest名称代替日期验证。</p>
          </details>
          <p v-if="!collapsedPools[group.pool_id] && isWechatPool(group) && !poolRows(group).length" class="evidence-note">
            公众号旧池未生成/待补齐；报告与全文提及尚未接入阶段候选，不把 mentions 直接当候选或评分。
          </p>
          <p v-if="isWechatPool(group) && poolRows(group).length" class="preview-note">
            公众号旧池行仅供来源核对；报告与全文提及不直接进入阶段候选或评分。
          </p>
          <p v-if="!collapsedPools[group.pool_id] && isBaimaoPool(group) && !poolRows(group).length" class="evidence-note">
            白毛卡点研究映射暂无已核验行；不生成候选或评分，保留原池边界。
          </p>
          <button
            v-if="isWechatPool(group)"
            type="button"
            class="pool-entry-button"
            data-testid="open-wechat-archive"
            @click="openResearch(true)"
          >打开公众号研究归档</button>
          <WechatMentionPool
            v-if="isWechatPool(group) && canLoadWechatMentions && !collapsedPools[group.pool_id]"
            :article-date="selectedDate"
            @open-report="openResearch(true)"
          />
          <p v-if="!collapsedPools[group.pool_id] && !isCompactResearchPool(group)" class="review-table-scroll-hint">
            <span>横向滚动查看完整字段</span><strong>池评分列在右侧 →</strong>
          </p>
          <div
            v-if="!collapsedPools[group.pool_id] && !isCompactResearchPool(group)"
            class="review-table-wrap"
            tabindex="0"
            role="region"
            :aria-label="`${group.display_name || group.pool_id} 表格，可键盘聚焦并横向滚动查看池评分列`"
          >
            <table>
              <thead><tr><th>池内排名</th><th>代码</th><th>名称</th><th>来源/状态</th><th>信号日</th><th>池评分</th></tr></thead>
              <tbody>
                <tr v-for="row in poolRows(group)" :key="`${group.pool_id}-${poolRowCode(row)}-${row.pool_rank ?? 0}`">
                  <td>{{ row.pool_rank ?? "-" }}</td><td>{{ poolRowCode(row) }}</td><td>{{ poolRowName(row) }}</td>
                  <td :title="poolRowSourceLane(row)">{{ poolRowSource(row, group) }}</td><td>{{ poolRowSignalDate(row) }}</td><td>{{ row.pool_score ?? "-" }}</td>
                </tr>
                <tr v-if="!poolRows(group).length"><td colspan="6">该池当前无可确认行；保留原池边界，不与其他池合并。</td></tr>
              </tbody>
            </table>
          </div>
        </section>
        <p v-if="!preselectionGroups.length">该交易日没有可确认的独立 D-1 池。</p>
      </div>
    </section>
    </template>
  </main>
</template>
