<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, createWorkbenchApi } from "./api";
import type { AnnouncementArticle, AnnouncementFlashData, AnnouncementFlashResumeEligibility,
  AnnouncementPending, AnnouncementStock, Envelope } from "./types";

const props = defineProps<{ targetDate: string }>();
const api = createWorkbenchApi();
const view = ref<Envelope<AnnouncementFlashData> | null>(null);
const mode = ref<"latest" | "history">("latest");
const historyDate = ref(toDateInput(props.targetDate));
const historyTargetDate = ref<string | null>(null);
const loading = ref(false);
const starting = ref(false);
const startingResume = ref(false);
const error = ref("");
const acceptedMessage = ref("");
let sequence = 0;
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let disposed = false;

const data = computed(() => view.value?.data || null);
const latestCaptureProductSha = computed(() => {
  const value = data.value?.incremental?.provenance?.capture_product_sha256;
  return typeof value === "string" && value ? value : null;
});
const resultModeText = computed(() => mode.value === "latest"
  ? "最新已保存结果" : `历史日期 ${historyTargetDate.value || "未选择"}`);
const stocks = computed(() => {
  const captureSha = latestCaptureProductSha.value;
  const ordered = (data.value?.stocks || []).map(stock => ({
    ...stock,
    articles: [...stock.articles].sort((left, right) => {
      const captureOrder = Number(isCurrentCapture(right, captureSha)) - Number(isCurrentCapture(left, captureSha));
      return captureOrder || (right.publication_date || "").localeCompare(left.publication_date || "")
        || left.article_id.localeCompare(right.article_id);
    }),
  }));
  return ordered.sort((left, right) => {
    const captureOrder = Number(right.articles.some(article => isCurrentCapture(article, captureSha)))
      - Number(left.articles.some(article => isCurrentCapture(article, captureSha)));
    const latestDate = (stock: AnnouncementStock) => stock.articles.reduce((latest, article) =>
      article.publication_date && article.publication_date > latest ? article.publication_date : latest, "");
    return captureOrder || latestDate(right).localeCompare(latestDate(left)) || left.symbol.localeCompare(right.symbol);
  });
});
const activeJob = computed(() => data.value?.job || null);
const resumeEligibility = computed(() => data.value?.resume || null);
const isTransportRecovery = computed(() => {
  const eligibility = resumeEligibility.value as
    (AnnouncementFlashResumeEligibility & { transport_recovery?: unknown }) | null;
  return Boolean(eligibility?.transport_recovery);
});
const canResume = computed(() => Boolean(resumeEligibility.value?.eligible
  && resumeEligibility.value.target_date && resumeEligibility.value.source_job_id
  && resumeEligibility.value.source_input_sha256 && resumeEligibility.value.source_progress_sha256
  && resumeEligibility.value.source_queue_state_sha256));
const canResumeCanary = computed(() => canResume.value
  && resumeEligibility.value?.resume_action === "CANARY");
const canResumeContinue = computed(() => canResume.value
  && resumeEligibility.value?.resume_action === "CONTINUE"
  && resumeEligibility.value?.canary_passed === true
  && resumeEligibility.value?.canary_validation?.status === "PASS");
const membership = computed(() => data.value?.membership || null);
const isActive = computed(() => ["QUEUED", "RUNNING", "STOP_REQUESTED"].includes(activeJob.value?.state || ""));
const preprocessing = computed(() => data.value?.preprocessing || null);
const delivery = computed(() => data.value?.daily_delivery || null);
const evidenceSections = [
  ["facts", "事实"], ["changes", "变化"], ["impact", "影响"],
  ["confirmation_conditions", "确认条件"], ["counter_evidence", "反面证据"],
] as const;
const deliveryRows = computed(() => {
  const projection = data.value?.daily_analysis;
  const bound = projection?.delivery_sha256 === data.value?.daily_delivery_binding?.sha256;
  return (delivery.value?.articles || []).map(article => {
    const analysis = bound ? projection?.articles.find(item => item.article_id === article.article_id
      && item.body_sha256 === article.body_sha256 && item.source_sha256 === article.source_sha256) : undefined;
    return { ...article, analysis, evidenceSections: analysis?.reader_output
      ? evidenceSections.map(([field, label]) => ({ field, label, items: analysis.reader_output![field] })) : [] };
  });
});
function evidenceValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
const preparedJob = computed(() => {
  const job = activeJob.value, report = preprocessing.value;
  return job && /^[0-9a-f]{32}$/.test(job.job_id) && report?.job_id === job.job_id
    && report.target_date === job.target_date && report.accounting_closed === true
    && /^[0-9a-f]{64}$/.test(data.value?.preprocessing_binding?.sha256 || "")
    && report.first_article_id && report.execution_manifest[0]?.article_id === report.first_article_id
    && /^[0-9a-f]{64}$/.test(report.execution_manifest[0]?.body_sha256 || "") ? job : null;
});
const identifiedDelivery = computed(() => {
  const saved = delivery.value, binding = data.value?.daily_delivery_binding;
  return saved && /^[0-9a-f]{32}$/.test(saved.job_id) && binding?.job_id === saved.job_id
    && /^[0-9a-f]{64}$/.test(binding.sha256) ? saved : null;
});
const currentDelivery = computed(() => identifiedDelivery.value?.job_id === preparedJob.value?.job_id
  && identifiedDelivery.value?.target_trade_date === preparedJob.value?.target_date
  && identifiedDelivery.value?.preprocessing_report_sha256 === data.value?.preprocessing_binding?.sha256
  ? identifiedDelivery.value : null);
const firstComplete = computed(() => currentDelivery.value?.articles.some(article =>
  article.article_id === preprocessing.value?.first_article_id
  && article.body_sha256 === preprocessing.value?.execution_manifest[0]?.body_sha256 && article.state === "SUCCEEDED") || false);
const canExecuteFirst = computed(() => !isActive.value && preparedJob.value?.state === "PARTIAL"
  && (!delivery.value || Boolean(identifiedDelivery.value && identifiedDelivery.value.job_id !== preparedJob.value.job_id)));
const canExecuteRemaining = computed(() => !isActive.value && preparedJob.value?.state === "PARTIAL"
  && firstComplete.value && currentDelivery.value?.articles.some(article => ["PENDING", "DEFERRED"].includes(article.state)
    && preprocessing.value?.execution_manifest.some(entry => entry.article_id === article.article_id && entry.body_sha256 === article.body_sha256)));
async function stopUpdate(): Promise<void> {
  if (!activeJob.value) return;
  try { await api.stopAnnouncementFlash(activeJob.value.job_id); await load(true); }
  catch (caught) { error.value = readableError(caught); }
}
async function executePrepared(phase: "FIRST" | "CONTINUE"): Promise<void> {
  if (!preparedJob.value || !data.value?.preprocessing_binding || starting.value
    || !(phase === "FIRST" ? canExecuteFirst.value : canExecuteRemaining.value)) return;
  starting.value = true;
  try {
    await api.executePreprocessedAnnouncement(preparedJob.value.job_id, data.value.preprocessing_binding.sha256,
      phase, phase === "CONTINUE" ? data.value.daily_delivery_binding?.sha256 : undefined);
    await load(true);
  } catch (caught) { error.value = readableError(caught); }
  finally { starting.value = false; }
}
const queueCounts = computed(() => activeJob.value?.progress?.queue_counts || {});
const historicalOutcomes = computed(() => {
  const value = data.value?.incremental?.provenance?.historical_outcomes;
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    : [];
});

function readableError(value: unknown): string {
  if (value instanceof ApiError) return `接口 ${value.status || "网络"}：${value.message}`;
  return value instanceof Error ? value.message : "公告选股读取失败";
}
function toDateInput(value: string): string {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : "";
}
function isCurrentCapture(article: AnnouncementArticle, captureSha: string | null): boolean {
  return Boolean(captureSha && Array.isArray(article.source_origins)
    && article.source_origins.some(origin => origin.role === "CAPTURE_WINDOW_PRODUCT_ROW"
      && origin.source_product_sha256 === captureSha));
}
function requestDate(): string | undefined {
  return mode.value === "history" ? historyTargetDate.value || undefined : undefined;
}
function stopTimer(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}
function schedulePoll(): void {
  stopTimer();
  if (disposed || !isActive.value) return;
  timer = setTimeout(() => { void load(true); }, 1800);
}
async function load(preserve = true, targetDate = requestDate()): Promise<void> {
  const ticket = ++sequence;
  controller?.abort();
  const requestController = new AbortController();
  controller = requestController;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.getAnnouncementFlash(targetDate, requestController.signal);
    if (disposed || ticket !== sequence || requestController.signal.aborted) return;
    if (!result.data) throw new ApiError("公告选股响应缺少数据", 502, result.gaps);
    view.value = result;
    if (isActive.value) schedulePoll(); else stopTimer();
  } catch (caught) {
    if (disposed || ticket !== sequence || requestController.signal.aborted) return;
    error.value = readableError(caught);
    if (!preserve) view.value = null;
    if (activeJob.value && isActive.value) schedulePoll();
  } finally {
    if (!disposed && ticket === sequence) loading.value = false;
  }
}
function showLatest(): void {
  mode.value = "latest";
  historyTargetDate.value = null;
  void load(false);
}
function showHistory(): void {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(historyDate.value)) {
    error.value = "请选择有效的历史目标港股日";
    return;
  }
  mode.value = "history";
  historyTargetDate.value = historyDate.value.replace(/-/g, "");
  void load(false, historyTargetDate.value);
}
function onWindowFocus(): void {
  if (mode.value === "latest") void load(true);
}
async function startUpdate(): Promise<void> {
  if (starting.value || isActive.value) return;
  starting.value = true;
  error.value = "";
  acceptedMessage.value = "";
  try {
    const result = await api.startAnnouncementFlashUpdate(props.targetDate);
    if (!result.data?.job_id || result.data.requested_target_date !== props.targetDate) {
      throw new ApiError("增量任务返回的目标日期或任务编号不一致", 502);
    }
    acceptedMessage.value = `已提交公告预处理任务 ${result.data.job_id}，目标日 ${result.data.target_date}；完成后展示报告，模型尚未调用。`;
    mode.value = "latest";
    historyTargetDate.value = null;
    await load(true);
  } catch (caught) {
    error.value = readableError(caught);
  } finally {
    starting.value = false;
  }
}
async function resumeUpdate(resumeAction: "CANARY" | "CONTINUE"): Promise<void> {
  const eligibility = resumeEligibility.value as AnnouncementFlashResumeEligibility | null;
  if (startingResume.value || isActive.value || !eligibility
    || (resumeAction === "CANARY" ? !canResumeCanary.value : !canResumeContinue.value)
    || !eligibility.target_date) return;
  startingResume.value = true;
  error.value = "";
  acceptedMessage.value = "";
  try {
    const result = await api.resumeAnnouncementFlash(eligibility.target_date, eligibility, resumeAction);
    if (!result.data?.job_id || result.data.source_job_id !== eligibility.source_job_id
      || result.data.target_date !== eligibility.target_date
      || result.data.resume_action !== resumeAction) {
      throw new ApiError("续跑任务返回的来源或目标日期不一致", 502);
    }
    acceptedMessage.value = `已提交公告续跑 ${result.data.job_id}，来源任务 ${eligibility.source_job_id}，目标日 ${result.data.target_date}。`;
    mode.value = "latest";
    historyTargetDate.value = null;
    await load(true);
  } catch (caught) {
    error.value = readableError(caught);
  } finally {
    startingResume.value = false;
  }
}
function timeText(value?: string | null): string {
  if (!value) return "未提供";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
function countText(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "未知";
}
function articleStateText(value: string): string {
  return ({ SUCCEEDED: "完整分析已保存", FAILED: "分析失败", PENDING: "待处理", DEFERRED: "延期处理",
    OUTSIDE_WINDOW: "超出来源窗口", MEMBERSHIP_OUT: "范围外", MEMBERSHIP_UNKNOWN: "资格待核实",
    HISTORY_SUCCESS_REUSED: "历史成功复用", HISTORY_RULE_REUSED: "历史规则结果复用",
    OTHER_HISTORY_PRESERVED: "其他历史处理保留", RULE_ARCHIVED: "程序性归档", STRUCTURED_EXTRACTED: "结构化事实提取",
    SOURCE_GAP: "资料待补证", PREPARATION_PENDING: "预处理待补证", USER_STOPPED_EXCLUDED: "本次停止范围排除",
    EXACT_DUPLICATE: "精确重复", MODEL_ORDINARY: "应模型分析：普通", MODEL_LONG: "应模型分析：长文",
    SELECTED_EVENT: "正面经营事件候选", SELECTED_PERFORMANCE: "正面业绩研究候选",
    NOT_SELECTED: "未入选", NOT_ASSESSED: "未评估", CONDITIONAL_WATCH: "条件观察"
  } as Record<string, string>)[value] || value;
}
function jobStateText(value?: string | null): string {
  return ({ QUEUED: "排队中", RUNNING: "运行中", SUCCEEDED: "完成", PARTIAL: "部分完成",
    FAILED: "失败", CANCELLED: "已取消", INTERRUPTED: "中断", STOP_REQUESTED: "停止中（等待在途结果保存）", USER_STOPPED: "用户已停止" } as Record<string, string>)[value || ""] || "未运行";
}
function membershipText(value?: string | null): string {
  return ({ VERIFIED: "权威已核验", CANNOT_CONFIRM: "资格无法确认", IN: "港股通范围内",
    OUT: "不在港股通范围", UNKNOWN: "资格未知" } as Record<string, string>)[value || ""] || "未核验";
}
function pendingStatusText(item: AnnouncementPending): string {
  if (item.queue_status === "PENDING" && item.context_admission === "INPUT_EXCEEDS_CONTEXT"
    && item.execution_admission === "AWAITING_FULL_BODY_CHUNKING") return "正文超长，待完整分块";
  if (item.queue_status === "PENDING" && item.queue_reason === "STOPPED_AFTER_SYSTEM_FAILURE") {
    return "系统停队后尚未运行";
  }
  return item.queue_reason || item.failure_code || "未运行";
}
function pendingStatusReason(item: AnnouncementPending): string | null {
  const reason = item.queue_reason || item.failure_code;
  return reason && reason !== pendingStatusText(item) ? reason : null;
}
function statusRowKey(item: { article_id?: string | null; part_index?: number | null;
  failure_code?: string | null; queue_reason?: string | null }, index: number): string {
  return `${item.article_id || "row"}:${item.part_index ?? "article"}:${item.failure_code || item.queue_reason || "status"}:${index}`;
}
function bodyPartLabel(item: { part_index?: number | null; part_count?: number | null }): string | null {
  return item.part_index == null ? null : `正文分块 ${item.part_index}/${item.part_count ?? "?"}`;
}
function longBodyFailureCount(): number {
  const count = data.value?.counts.long_body_part_failed;
  return typeof count === "number" ? count : data.value?.failures.filter(item => item.part_index != null).length || 0;
}
function longBodyPendingCount(): number {
  const count = data.value?.counts.long_body_part_pending;
  return typeof count === "number" ? count : data.value?.pending.filter(item => item.part_index != null).length || 0;
}
function longBodyCannotConfirmCount(): number {
  const count = data.value?.counts.long_body_part_cannot_confirm;
  return typeof count === "number" ? count : data.value?.pending.filter(item =>
    item.queue_status === "CANNOT_CONFIRM" || item.queue_reason === "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM").length || 0;
}
function otherFailureCount(): number {
  const failedArticles = data.value?.counts.model_failed_articles ?? data.value?.counts.failed ?? 0;
  const failureRows = data.value?.failures.length ?? 0;
  return Math.max(0, failureRows - failedArticles - longBodyFailureCount());
}
function longBodySynthesisPendingCount(): number {
  const count = data.value?.counts.long_body_synthesis_pending;
  return typeof count === "number" ? count : data.value?.pending.filter(item =>
    item.queue_reason?.includes("SYNTHESIS")).length || 0;
}
watch(() => props.targetDate, () => {
  if (mode.value === "latest") {
    historyDate.value = toDateInput(props.targetDate);
    void load(false);
  }
});
onMounted(() => {
  window.addEventListener("focus", onWindowFocus);
  void load(false);
});
onBeforeUnmount(() => {
  disposed = true;
  sequence++;
  window.removeEventListener("focus", onWindowFocus);
  stopTimer();
  controller?.abort();
});
</script>

<template>
  <section class="mwb-panel mwb-announcements" aria-label="公告增量选股">
    <div class="mwb-heading">
      <div>
        <h2>公告选股 · 本地 Qwen3.8 Flash</h2>
        <p>固定结果按公告来源日展示；目标港股日是独立输入，不能由公告发布日期推定。</p>
      </div>
      <button type="button" :disabled="starting || isActive" @click="startUpdate">
        {{ starting ? "正在提交…" : isActive ? "增量任务运行中" : "检查新增公告并预处理" }}
      </button>
      <button v-if="canResumeCanary" type="button" :disabled="startingResume || isActive" @click="resumeUpdate('CANARY')">
        {{ startingResume ? "正在提交…" : isActive ? "公告任务运行中"
          : isTransportRecovery ? "运行失败公告任务 canary（1 个模型请求）" : "运行失败分块 canary（1 个模型请求）" }}
      </button>
      <button v-if="canResumeContinue" type="button" :disabled="startingResume || isActive" @click="resumeUpdate('CONTINUE')">
        {{ startingResume ? "正在提交…" : isActive ? "公告任务运行中"
          : isTransportRecovery ? "继续原队列待处理公告任务" : "继续其余失败和待处理分块" }}
      </button>
      <p v-if="canResume" class="mwb-resume-eligibility">
        <template v-if="resumeEligibility?.resume_action === 'CANARY'">
          <template v-if="isTransportRecovery">
            首次续跑仅验证一个绑定到原失败任务的公告任务；成功并通过保存结果复核后，才开放继续入口。
          </template>
          <template v-else>
            首次续跑仅验证一个固定字段失败分块；成功并通过保存结果复核后，才开放继续入口。
          </template>
        </template>
        <template v-else-if="canResumeContinue">
          <template v-if="isTransportRecovery">
            失败公告任务 canary 已保存并复核通过；继续操作仅处理原队列待处理公告任务，保留已成功和其他失败记录。
          </template>
          <template v-else>
            单个失败分块 canary 已保存并复核通过；继续操作将处理其余合格失败、待处理和可恢复中断分块。
          </template>
        </template>
        <template v-else>
          canary 未通过或验收信息不完整，续跑已停止。
        </template>
      </p>
    </div>

    <section class="mwb-announcement-job" aria-label="公告结果选择">
      <strong>当前列表：{{ resultModeText }}</strong>
      <button type="button" @click="showLatest">查看最新结果</button>
      <label>历史目标港股日 <input v-model="historyDate" type="date" /></label>
      <button type="button" @click="showHistory">按日期查看历史</button>
    </section>

    <p v-if="error" class="mwb-alert" role="alert">{{ error }}。此前已读取结果继续保留。</p>
    <p v-if="acceptedMessage" class="mwb-muted" role="status">{{ acceptedMessage }}</p>
    <p v-if="loading" class="mwb-muted" role="status">正在读取公告选股状态…</p>

    <template v-if="data">
      <section v-if="preprocessing" class="mwb-announcement-job" aria-label="预处理完成报告">
        <h3>预处理完成 · 模型调用前报告</h3>
        <p>来源 {{ preprocessing.source }}；本地截止 {{ timeText(preprocessing.cutoff) }}。</p>
        <p>原始 {{ preprocessing.counts.raw_rows }} 条，精确重复 {{ preprocessing.counts.exact_duplicates }} 条，去重后 {{ preprocessing.counts.unique_articles }} 篇。</p>
        <p>应进入模型 {{ preprocessing.counts.model_required_articles }} 篇：普通 {{ preprocessing.counts.model_ordinary_articles }} 篇，长文 {{ preprocessing.counts.model_long_articles }} 篇；预计 {{ preprocessing.counts.reader_parts }} 个分块、{{ preprocessing.counts.syntheses }} 次综合，共 {{ preprocessing.counts.expected_model_requests }} 次请求。</p>
        <p>本次新增测试子集 {{ preprocessing.counts.bounded_articles }} 篇／最多 {{ preprocessing.counts.bounded_model_requests }} 次请求；延期 {{ preprocessing.counts.deferred_model_articles }} 篇，工作量待补证 {{ preprocessing.counts.workload_unknown_articles }} 篇。</p>
        <dl><template v-for="(count, disposition) in preprocessing.counts.primary_dispositions" :key="disposition">
          <dt>{{ articleStateText(String(disposition)) }}</dt><dd>{{ count }}</dd>
        </template></dl>
        <ul><li v-for="rule in preprocessing.rules_explanation" :key="rule">{{ rule }}</li></ul>
        <button v-if="canExecuteFirst" type="button" :disabled="starting" @click="executePrepared('FIRST')">运行首篇新增公告</button>
        <button v-if="canExecuteRemaining" type="button" :disabled="starting" @click="executePrepared('CONTINUE')">首篇已核验，继续其余未尝试部分</button>
      </section>
      <section v-if="delivery" class="mwb-announcement-job" aria-label="逐篇交付与未完成">
        <h3>逐篇完整结果与未完成清单</h3>
        <p>分块仅作为证据；正文完整且综合通过后才显示文章终态和候选。</p>
        <ul><li v-for="article in deliveryRows" :key="article.article_id + ':' + article.body_sha256">
          <strong>{{ article.title || article.article_id }}</strong>：{{ articleStateText(article.state) }}
          <span v-if="article.disposition"> · {{ articleStateText(article.disposition) }}</span>
          <span v-if="article.parts_total != null">（证据分块 {{ article.parts_complete }}/{{ article.parts_total }}）</span>
          <span v-if="article.reason"> — {{ article.reason }}</span>
          <span v-else-if="article.queue_reason || article.failure_code"> — {{ article.queue_reason || article.failure_code }}</span>
          <details v-if="article.analysis?.analysis_state === 'AVAILABLE' && article.analysis.reader_output"
            :aria-label="'完整分析：' + (article.title || article.article_id)">
            <summary>阅读完整分析</summary>
            <p>已保存的模型分析，供人工复核；完整正文覆盖不代表官方首次发布时间已确认。</p>
            <dl>
              <dt>判断</dt><dd>{{ article.analysis.reader_output.disposition }}</dd>
              <dt>方向</dt><dd>{{ article.analysis.reader_output.direction }}</dd>
              <dt>判断依据</dt><dd>{{ article.analysis.reader_output.selection_basis }}</dd>
              <dt>证据充分性</dt><dd>{{ article.analysis.reader_output.evidence_sufficiency }}</dd>
              <dt>完整理由</dt><dd>{{ article.analysis.reader_output.reason }}</dd>
            </dl>
            <section v-for="group in article.evidenceSections" :key="group.field" :aria-label="group.label">
              <h4>{{ group.label }}</h4>
              <p v-if="!group.items.length">本次保存分析未提供此项。</p>
              <ol v-else><li v-for="(citation, index) in group.items" :key="index">
                <p>{{ citation.claim }}</p>
                <blockquote><pre style="white-space: pre-wrap; overflow-wrap: anywhere">{{ citation.quote }}</pre></blockquote>
                <dl><template v-for="(value, key) in citation" :key="key">
                  <template v-if="key !== 'claim' && key !== 'quote'">
                    <dt>{{ key === 'locator' ? '原文定位（locator）' : key }}</dt><dd>{{ evidenceValue(value) }}</dd>
                  </template>
                </template></dl>
              </li></ol>
            </section>
            <section aria-label="风险与数据限制">
              <h4>风险与数据限制</h4>
              <ul v-if="article.analysis.reader_output.risk_notes.length">
                <li v-for="(note, index) in article.analysis.reader_output.risk_notes" :key="index">{{ note }}</li>
              </ul>
              <p v-else>本次保存分析未提供此项。</p>
            </section>
            <dl style="overflow-wrap: anywhere">
              <dt>来源覆盖</dt><dd>{{ article.source_coverage }}</dd>
              <dt>来源 SHA256</dt><dd>{{ article.analysis.source_sha256 }}</dd>
              <dt>正文 SHA256</dt><dd>{{ article.analysis.body_sha256 }}</dd>
              <dt>已校验结果 SHA256</dt><dd>{{ article.analysis.result_sha256 }}</dd>
              <dt>交付版本 SHA256</dt><dd>{{ data.daily_analysis?.delivery_sha256 }}</dd>
            </dl>
          </details>
          <p v-else-if="article.state === 'SUCCEEDED'" role="status">
            完整分析暂不可读，请保留已保存结果并核对来源绑定。
            <small v-if="article.analysis?.failure_code">{{ article.analysis.failure_code }}</small>
          </p>
        </li></ul>
      </section>
      <button v-if="isActive" type="button" :disabled="activeJob?.state === 'STOP_REQUESTED'" @click="stopUpdate">
        {{ activeJob?.state === 'STOP_REQUESTED' ? '停止中：在途结果保存后结束' : '停止后续公告派发' }}
      </button>
      <div class="mwb-announcement-meta">
        <span>公告来源日：<strong>{{ data.source_date }}</strong></span>
        <span>冻结基线目标港股日：<strong>{{ data.target_trade_date }}</strong></span>
        <span>保存结果更新时间：<strong>{{ timeText(data.updated_at) }}</strong></span>
        <span>模型候选语义复核：<strong>{{ data.review_status || "MODEL_CANDIDATE_UNREVIEWED" }}</strong></span>
      </div>

      <div class="mwb-announcement-counts" aria-label="公告候选与处理状态">
        <div><strong>{{ countText(data.counts.displayed_stocks) }}</strong><span>展示股票（按代码去重）</span></div>
        <div><strong>{{ countText(data.counts.model_succeeded) }}</strong><span>冻结结果已完成文章</span></div>
        <div><strong>{{ countText(data.counts.failed) }}</strong><span>冻结结果失败文章</span></div>
        <div><strong>{{ countText(data.counts.pending) }}</strong><span>冻结结果未运行文章</span></div>
        <div><strong>{{ countText(data.counts.body_gaps) }}</strong><span>正文缺口</span></div>
      </div>

      <section class="mwb-announcement-job" aria-label="目标日港股通资格校验">
        <strong>目标日港股通资格：{{ membershipText(membership?.status) }}</strong>
        <span>目标日 {{ membership?.target_date || data.requested_target_date || "未知" }}</span>
        <span v-if="membership?.cutoff">截止 {{ timeText(membership.cutoff) }}</span>
        <span>权威成员 {{ countText(membership?.member_count) }}</span>
        <span>权威 SHA256 {{ membership?.authority_sha256 || membership?.failure_code || "未提供" }}</span>
        <span v-if="membership?.effective_from && membership?.effective_to">有效期 {{ membership.effective_from }}–{{ membership.effective_to }}</span>
        <span>展示 IN {{ countText(data.counts.membership_eligible_stocks) }} 只 · OUT {{ countText(data.counts.membership_excluded_stocks) }} 只 · UNKNOWN {{ countText(data.counts.membership_unknown_stocks) }} 只</span>
      </section>

      <section v-if="activeJob" class="mwb-announcement-job" aria-label="增量任务进度">
        <strong>增量任务：{{ jobStateText(activeJob.state) }}</strong>
        <span>步骤 {{ activeJob.step || "等待状态" }}</span>
        <span>已处理 {{ countText(activeJob.completed_count) }} / {{ countText(activeJob.total_count) }}</span>
        <span v-for="state in ['SUCCEEDED', 'FAILED', 'PENDING']" :key="state">
          {{ state }} {{ countText(queueCounts[state]) }}
        </span>
        <span v-if="activeJob.failure_code" class="mwb-alert">错误码 {{ activeJob.failure_code }}</span>
        <span v-if="activeJob.last_progress_at">最近进度 {{ timeText(activeJob.last_progress_at) }}</span>
      </section>

      <section v-if="data.incremental" class="mwb-announcement-job" aria-label="最近增量选股结果">
        <strong>最近增量结果：{{ jobStateText(data.incremental.state) }}</strong>
        <span>目标港股日 {{ data.incremental.target_trade_date || "未知" }}</span>
        <span>新建队列 {{ countText(data.incremental.counts.queue?.new_enqueued) }} 篇</span>
        <span>复用冻结成功 {{ countText(data.incremental.counts.queue?.pinned_succeeded_matched) }} 篇</span>
        <span>冻结失败跳过 {{ countText(data.incremental.counts.queue?.pinned_failed_matched) }} 篇</span>
        <span>冻结待处理跳过 {{ countText(data.incremental.counts.queue?.pinned_pending_matched) }} 篇</span>
        <span>复用已复核结果 {{ countText(data.incremental.counts.queue?.reviewed_succeeded_matched) }} 篇</span>
        <span>同次采集重复跳过 {{ countText(data.incremental.counts.queue?.same_capture_duplicates_skipped) }} 篇</span>
        <span>复用此前增量成功 {{ countText(data.incremental.counts.queue?.incremental_succeeded_matched) }} 篇</span>
        <span>此前增量待处理跳过 {{ countText(data.incremental.counts.queue?.incremental_pending_matched) }} 篇</span>
        <span>失败 {{ countText(data.incremental.counts.failed) }} 篇</span>
        <span>待处理 {{ countText(data.incremental.counts.queue_pending) }} 篇</span>
        <span>正文缺口 {{ countText(data.incremental.counts.body_gaps) }} 篇</span>
        <span>完成时间 {{ timeText(data.incremental.updated_at) }}</span>
        <small class="mwb-muted">本次新增候选 {{ countText(data.incremental.counts.new_candidate_stocks) }} 只</small>
      </section>

      <p class="mwb-announcement-safety">研究候选，只供人工复核；不进入正式计划或 BUY 门禁，也不发送订单。</p>
      <p v-if="!stocks.length" class="mwb-empty">当前没有可展示的入选股票；失败、未运行和正文缺口仍按独立状态列出。</p>
      <div v-else class="mwb-table-wrap">
        <table class="mwb-table mwb-announcement-table">
          <thead><tr><th scope="col">港股代码 / 名称</th><th scope="col">公告与日期</th><th scope="col">模型入选理由</th><th scope="col">状态 / 来源校验</th></tr></thead>
          <tbody>
            <tr v-for="stock in stocks" :key="stock.symbol">
              <td><strong class="mwb-symbol">{{ stock.symbol }}</strong><span>{{ stock.name || "名称未知" }}</span></td>
              <td>
                <article v-for="article in stock.articles" :key="article.article_id + article.body_sha256" class="mwb-announcement-article">
                  <strong>{{ article.title }}</strong>
                  <small v-if="isCurrentCapture(article, latestCaptureProductSha)"
                    class="mwb-muted mwb-announcement-current-capture">本次采集</small>
                  <small>{{ article.article_id }} · 公告日 {{ article.publication_date || "未知" }}</small>
                  <small>{{ article.disposition || "入选类型未知" }} · {{ article.direction || "方向未知" }}</small>
                  <details>
                    <summary>来源哈希与定位（{{ article.source_origins.length }} 项）</summary>
                    <small>正文 SHA256 {{ article.body_sha256 }}</small>
                    <small>来源 SHA256 {{ article.source_sha256 }}</small>
                    <ul><li v-for="(origin, index) in article.source_origins" :key="`${origin.role}-${index}`">
                      {{ origin.role }} · {{ origin.source_product_sha256 }} · {{ origin.source_ref }}
                    </li></ul>
                  </details>
                </article>
              </td>
              <td>
                <article v-for="article in stock.articles" :key="article.article_id + article.body_sha256 + '-reason'" class="mwb-announcement-reason">
                  <p>{{ article.reason }}</p>
                  <p v-if="article.selection_basis"><strong>入选依据：</strong>{{ article.selection_basis }}</p>
                  <ul v-if="article.impact?.length"><li v-for="(claim, index) in article.impact" :key="index">{{ claim }}</li></ul>
                </article>
              </td>
              <td>
                <span>{{ stock.review_status }}</span>
                <small>{{ membershipText(stock.membership_status) }}</small>
                <small v-if="stock.reuse_status">{{ stock.reuse_status }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <details class="mwb-announcement-audit">
        <summary>冻结结果处理明细：失败文章 {{ countText(data.counts.model_failed_articles ?? data.counts.failed) }}、正文分块失败 {{ countText(longBodyFailureCount()) }}、其他保留失败记录 {{ countText(otherFailureCount()) }}、待处理文章 {{ countText(data.counts.model_pending_articles ?? data.counts.pending) }}、正文分块待处理 {{ countText(longBodyPendingCount()) }}、正文分块结果无法确认 {{ countText(longBodyCannotConfirmCount()) }}、长文综合待处理 {{ countText(longBodySynthesisPendingCount()) }}、正文缺口 {{ data.gaps.length }}</summary>
        <h3>失败记录（公告文章与正文分块）</h3>
        <p v-if="!data.failures.length" class="mwb-muted">没有记录失败文章。</p>
        <ul><li v-for="(item, index) in data.failures" :key="statusRowKey(item, index)">
          {{ item.symbol || "代码未知" }} · {{ bodyPartLabel(item) || item.title || item.article_id || "文章未知" }} · {{ item.failure_code }}
        </li></ul>
        <h3>未运行 / 待处理</h3>
        <p v-if="!data.pending.length" class="mwb-muted">没有记录未运行文章。</p>
        <ul><li v-for="(item, index) in data.pending" :key="statusRowKey(item, index)">
          {{ item.symbol || "代码待核" }} · {{ bodyPartLabel(item) || item.title || item.article_id || "文章未知" }} · <strong>{{ pendingStatusText(item) }}</strong>
          <small v-if="pendingStatusReason(item)">队列原因：{{ pendingStatusReason(item) }}</small>
        </li></ul>
        <h3>正文与采集缺口</h3>
        <p v-if="!data.gaps.length" class="mwb-muted">没有记录正文缺口。</p>
        <ul><li v-for="(gap, index) in data.gaps" :key="`${gap.code || 'gap'}-${index}`">
          {{ gap.code || "GAP" }} × {{ countText(gap.count) }}：{{ gap.detail || "缺口详情未提供" }}
        </li></ul>
        <p v-if="data.system_stop">系统停队：{{ data.system_stop.failure_code }}；{{ data.system_stop.queue_action }}</p>
        <p v-if="data.incremental?.system_stop">增量系统停队：{{ data.incremental.system_stop.failure_code }}；{{ data.incremental.system_stop.queue_action }}</p>
      </details>
      <details v-if="data.incremental" class="mwb-announcement-audit">
        <summary>最近增量处理明细：失败文章 {{ countText(data.incremental.counts.failed) }}、正文分块失败 {{ countText(data.incremental.counts.queue?.long_body_parts_failed) }}、待处理文章 {{ countText(data.incremental.counts.queue_pending) }}、正文分块待处理 {{ countText(data.incremental.counts.queue?.long_body_parts_pending) }}、正文分块结果无法确认 {{ countText(data.incremental.counts.queue?.long_body_parts_cannot_confirm ?? longBodyCannotConfirmCount()) }}、长文综合待处理 {{ countText(data.incremental.counts.queue?.long_body_synthesis_pending ?? longBodySynthesisPendingCount()) }}、缺口 {{ data.incremental.gaps?.length || 0 }}</summary>
        <h3>增量失败记录（公告文章与正文分块）</h3>
        <p v-if="!data.incremental.failures?.length" class="mwb-muted">最近增量没有记录失败文章。</p>
        <ul><li v-for="(item, index) in data.incremental.failures" :key="statusRowKey(item, index)">
          {{ item.symbol || "代码未知" }} · {{ bodyPartLabel(item) || item.title || item.article_id || "文章未知" }} · {{ item.failure_code }}
        </li></ul>
        <h3>增量未运行 / 待处理</h3>
        <p v-if="!data.incremental.pending?.length" class="mwb-muted">最近增量没有记录待处理文章。</p>
        <ul><li v-for="(item, index) in data.incremental.pending" :key="statusRowKey(item, index)">
          {{ item.symbol || "代码待核" }} · {{ bodyPartLabel(item) || item.title || item.article_id || "文章未知" }} · {{ item.queue_reason || item.failure_code || "未运行" }}
        </li></ul>
        <p v-if="data.incremental.system_stop">增量系统停队：{{ data.incremental.system_stop.failure_code }}；{{ data.incremental.system_stop.queue_action }}</p>
      </details>
      <details v-if="historicalOutcomes.length" class="mwb-announcement-audit">
        <summary>历史公告复用与跳过状态（{{ historicalOutcomes.length }} 篇）</summary>
        <ul><li v-for="(item, index) in historicalOutcomes" :key="`${String(item.article_id || 'article')}-${index}`">
          {{ item.article_id || "文章未知" }} · {{ item.source || "来源未知" }} · {{ item.status || "状态未知" }}
          · {{ item.skip_reason || item.failure_code || item.disposition || "无额外说明" }}
          <template v-if="item.original_source_sha256 || item.current_capture_source_sha256">
            · 历史来源 SHA {{ item.original_source_sha256 || "未知" }} · 本次采集 SHA {{ item.current_capture_source_sha256 || "未知" }}
          </template>
        </li></ul>
      </details>
      <details v-if="data.membership_excluded_stocks?.length || data.membership_unknown_stocks?.length
        || data.membership_excluded_articles?.length || data.membership_unknown_articles?.length"
        class="mwb-announcement-audit">
        <summary>港股通范围外与资格未知：股票 {{ data.membership_excluded_stocks?.length || 0 }} / {{ data.membership_unknown_stocks?.length || 0 }}，文章 {{ data.membership_excluded_articles?.length || 0 }} / {{ data.membership_unknown_articles?.length || 0 }}</summary>
        <h3>范围外股票</h3>
        <ul><li v-for="item in data.membership_excluded_stocks || []" :key="item.symbol">
          {{ item.symbol }} · {{ item.name || "名称未知" }} · {{ item.membership_reason || "OUT" }}
        </li></ul>
        <h3>资格未知股票</h3>
        <ul><li v-for="item in data.membership_unknown_stocks || []" :key="item.symbol">
          {{ item.symbol }} · {{ item.name || "名称未知" }} · {{ item.membership_reason || "UNKNOWN" }}
        </li></ul>
        <h3>范围外或资格未知文章</h3>
        <ul><li v-for="(item, index) in [...(data.membership_excluded_articles || []), ...(data.membership_unknown_articles || [])]"
          :key="`${String(item.article_id || 'article')}-${index}`">
          {{ String(item.symbol || "代码待核") }} · {{ String(item.title || item.article_id || "文章未知") }} · {{ String(item.membership_status || "UNKNOWN") }} · {{ String(item.membership_reason || "资格无法确认") }}
        </li></ul>
      </details>
    </template>
    <p v-else-if="!loading" class="mwb-empty">公告选股状态尚未读取成功。</p>
  </section>
</template>
