<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, createWorkbenchApi } from "./api";
import type { AnnouncementFlashData, AnnouncementPending, Envelope } from "./types";

const props = defineProps<{ targetDate: string }>();
const api = createWorkbenchApi();
const view = ref<Envelope<AnnouncementFlashData> | null>(null);
const loading = ref(false);
const starting = ref(false);
const error = ref("");
const acceptedMessage = ref("");
let sequence = 0;
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let disposed = false;

const data = computed(() => view.value?.data || null);
const stocks = computed(() => data.value?.stocks || []);
const activeJob = computed(() => data.value?.job || null);
const isActive = computed(() => activeJob.value?.state === "QUEUED" || activeJob.value?.state === "RUNNING");
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
function stopTimer(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}
function schedulePoll(): void {
  stopTimer();
  if (disposed || !isActive.value) return;
  timer = setTimeout(() => { void load(true); }, 1800);
}
async function load(preserve = true): Promise<void> {
  const ticket = ++sequence;
  controller?.abort();
  const requestController = new AbortController();
  controller = requestController;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.getAnnouncementFlash(props.targetDate, requestController.signal);
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
    acceptedMessage.value = `已提交公告增量任务 ${result.data.job_id}，目标日 ${result.data.target_date}。`;
    await load(true);
  } catch (caught) {
    error.value = readableError(caught);
  } finally {
    starting.value = false;
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
function jobStateText(value?: string | null): string {
  return ({ QUEUED: "排队中", RUNNING: "运行中", SUCCEEDED: "完成", PARTIAL: "部分完成",
    FAILED: "失败", CANCELLED: "已取消", INTERRUPTED: "中断" } as Record<string, string>)[value || ""] || "未运行";
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
watch(() => props.targetDate, () => { void load(false); });
onMounted(() => { void load(false); });
onBeforeUnmount(() => {
  disposed = true;
  sequence++;
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
        {{ starting ? "正在提交…" : isActive ? "增量任务运行中" : "采集新增公告并增量选股" }}
      </button>
    </div>

    <p v-if="error" class="mwb-alert" role="alert">{{ error }}。此前已读取结果继续保留。</p>
    <p v-if="acceptedMessage" class="mwb-muted" role="status">{{ acceptedMessage }}</p>
    <p v-if="loading" class="mwb-muted" role="status">正在读取公告选股状态…</p>

    <template v-if="data">
      <div class="mwb-announcement-meta">
        <span>公告来源日：<strong>{{ data.source_date }}</strong></span>
        <span>目标港股日：<strong>{{ data.target_trade_date }}</strong></span>
        <span>来源更新：<strong>{{ timeText(data.updated_at) }}</strong></span>
        <span>模型候选语义复核：<strong>{{ data.review_status || "MODEL_CANDIDATE_UNREVIEWED" }}</strong></span>
      </div>

      <div class="mwb-announcement-counts" aria-label="公告候选与处理状态">
        <div><strong>{{ countText(data.counts.displayed_stocks) }}</strong><span>展示股票（按代码去重）</span></div>
        <div><strong>{{ countText(data.counts.model_succeeded) }}</strong><span>冻结结果已完成文章</span></div>
        <div><strong>{{ countText(data.counts.failed) }}</strong><span>冻结结果失败文章</span></div>
        <div><strong>{{ countText(data.counts.pending) }}</strong><span>冻结结果未运行文章</span></div>
        <div><strong>{{ countText(data.counts.body_gaps) }}</strong><span>正文缺口</span></div>
      </div>

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
        <span>本次新增候选 {{ countText(data.incremental.counts.new_candidate_stocks) }} 只</span>
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
                <article v-for="article in stock.articles" :key="article.article_id" class="mwb-announcement-article">
                  <strong>{{ article.title }}</strong>
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
                <article v-for="article in stock.articles" :key="article.article_id + '-reason'" class="mwb-announcement-reason">
                  <p>{{ article.reason }}</p>
                  <p v-if="article.selection_basis"><strong>入选依据：</strong>{{ article.selection_basis }}</p>
                  <ul v-if="article.impact?.length"><li v-for="(claim, index) in article.impact" :key="index">{{ claim }}</li></ul>
                </article>
              </td>
              <td>
                <span>{{ stock.review_status }}</span>
                <small v-if="stock.reuse_status">{{ stock.reuse_status }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <details class="mwb-announcement-audit">
        <summary>冻结结果处理明细：失败 {{ data.failures.length }}、未运行 {{ data.pending.length }}、正文缺口 {{ data.gaps.length }}</summary>
        <h3>失败文章</h3>
        <p v-if="!data.failures.length" class="mwb-muted">没有记录失败文章。</p>
        <ul><li v-for="item in data.failures" :key="item.article_id || item.failure_code">
          {{ item.symbol || "代码未知" }} · {{ item.title || item.article_id || "文章未知" }} · {{ item.failure_code }}
        </li></ul>
        <h3>未运行 / 待处理</h3>
        <p v-if="!data.pending.length" class="mwb-muted">没有记录未运行文章。</p>
        <ul><li v-for="item in data.pending" :key="item.article_id || item.queue_reason || 'pending-item'">
          {{ item.symbol || "代码待核" }} · {{ item.title || item.article_id || "文章未知" }} · <strong>{{ pendingStatusText(item) }}</strong>
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
        <summary>最近增量处理明细：失败 {{ data.incremental.failures?.length || 0 }}、待处理 {{ data.incremental.pending?.length || 0 }}、缺口 {{ data.incremental.gaps?.length || 0 }}</summary>
        <h3>增量失败文章</h3>
        <p v-if="!data.incremental.failures?.length" class="mwb-muted">最近增量没有记录失败文章。</p>
        <ul><li v-for="item in data.incremental.failures" :key="item.article_id || item.failure_code">
          {{ item.symbol || "代码未知" }} · {{ item.title || item.article_id || "文章未知" }} · {{ item.failure_code }}
        </li></ul>
        <h3>增量未运行 / 待处理</h3>
        <p v-if="!data.incremental.pending?.length" class="mwb-muted">最近增量没有记录待处理文章。</p>
        <ul><li v-for="(item, index) in data.incremental.pending" :key="item.article_id || item.queue_reason || `pending-${index}`">
          {{ item.symbol || "代码待核" }} · {{ item.title || item.article_id || "文章未知" }} · {{ item.queue_reason || item.failure_code || "未运行" }}
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
    </template>
    <p v-else-if="!loading" class="mwb-empty">公告选股状态尚未读取成功。</p>
  </section>
</template>
