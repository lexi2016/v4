<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { loadTaskStatus } from "../api/runtime";
import type { LogicalWorkloadStatus, TaskStatusResponse } from "../contracts/runtime";
import StageSummaryPanel, { type StageSummary } from "../components/review/StageSummaryPanel.vue";


type TaskStatusViewProps = {
  date: string;
  stageSummary?: StageSummary | null;
  currentStageId?: string | null;
  phaseStatus?: string;
  currentStageLabel?: string;
  selectedARows?: number;
  aSourceRows?: number;
  aCandidateCount?: number;
  selectedHkRows?: number;
  hkCandidateCount?: number;
  referenceMode?: boolean;
  selectedTotalRows?: number;
  dataLevel?: string;
};

const props = defineProps<TaskStatusViewProps>();
const payload = ref<TaskStatusResponse | null>(null);
const loading = ref(false);
const error = ref("");
const executionWarnings = computed(() => (payload.value?.cannot_confirm ?? []).filter((item) => !item.startsWith("GRAPH_TASK_REGISTRATIONS_")));
const graphWarnings = computed(() => (payload.value?.cannot_confirm ?? []).filter((item) => item.startsWith("GRAPH_TASK_REGISTRATIONS_")));
let requestVersion = 0;
let controller: AbortController | null = null;

const statusPriority: Record<string, number> = {
  FAILED: 0,
  DUPLICATE_WORKLOAD_SKIPPED: 1,
  CANNOT_CONFIRM: 2,
  NON_TRADING_DAY: 3,
  NO_ELIGIBLE_WORKLOADS: 3,
  DEFERRED: 4,
  SUCCEEDED: 5,
  DRY_RUN_SELECTED: 5,
};
const logicalRows = computed(() => [...(payload.value?.groups.logical ?? [])].sort(
  (left, right) => (statusPriority[left.status] ?? 2) - (statusPriority[right.status] ?? 2),
));

function duration(row: LogicalWorkloadStatus) {
  return typeof row.duration_ms === "number" ? `${row.duration_ms} ms` : "未记录";
}

async function refresh() {
  const version = ++requestVersion;
  controller?.abort();
  controller = new AbortController();
  payload.value = null;
  error.value = "";
  if (!/^\d{8}$/.test(props.date)) {
    loading.value = false;
    error.value = "任务状态缺少有效交易日。";
    return;
  }
  loading.value = true;
  try {
    const result = await loadTaskStatus(props.date, controller.signal);
    if (version === requestVersion) payload.value = result;
  } catch (caught) {
    if (version === requestVersion && !(caught instanceof DOMException && caught.name === "AbortError")) {
      error.value = "任务状态读取失败，请检查 V4 状态 API。";
    }
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}

watch(() => props.date, refresh, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="task-status-view" aria-label="任务状态">
    <div class="section-heading">
      <div><span class="eyebrow">RUNTIME GOVERNANCE</span><h2>任务状态</h2></div>
      <p>{{ date }} · catalog 与同日 receipt</p>
    </div>
    <StageSummaryPanel
      :summary="stageSummary"
      :current-stage-id="currentStageId"
      :phase-status="phaseStatus"
      :selected-date="date"
      :current-stage-label="currentStageLabel"
      :selected-a-rows="selectedARows"
      :a-source-rows="aSourceRows"
      :a-candidate-count="aCandidateCount"
      :selected-hk-rows="selectedHkRows"
      :hk-candidate-count="hkCandidateCount"
      :reference-mode="referenceMode"
      :selected-total-rows="selectedTotalRows"
      :data-level="dataLevel"
    />
    <p v-if="loading" class="task-message" role="status">正在读取任务状态。</p>
    <p v-else-if="error" class="task-message task-error" role="alert">{{ error }}</p>
    <template v-else-if="payload">
      <div class="task-counts">
        <article><span>逻辑任务</span><strong>{{ payload.logical_workload_count }}</strong></article>
        <article><span>已配置 owner</span><strong>{{ payload.active_owner_count }}</strong></article>
        <article><span>别名</span><strong>{{ payload.alias_count }}</strong></article>
        <article><span>退役 owner</span><strong>{{ payload.retired_owner_count }}</strong></article>
        <article><span>图谱待确认</span><strong>{{ payload.task_registration_count }}</strong></article>
      </div>
      <section class="task-evidence-warning" aria-label="实际调度证据">
        <strong>{{ payload.scheduler_observation?.status || "CANNOT_CONFIRM" }}</strong>
        <p>同日回执：{{ payload.scheduler_observation?.receipt_count ?? "未核验" }} · 当前进程存活：{{ payload.scheduler_observation?.process_status || "CANNOT_CONFIRM" }}</p>
        <p>{{ payload.scheduler_observation?.message || "仅有配置/声明，不构成部署或进程运行证明。" }}</p>
        <p>任务行证据：{{ payload.scheduler_observation?.logical_row_evidence || "DECLARED_ONLY" }} · {{ payload.scheduler_observation?.receipt_namespace || "缺回执根" }}</p>
      </section>
      <div v-if="executionWarnings.length" class="task-evidence-warning" role="alert">
        <strong>CANNOT_CONFIRM · 证据降级</strong>
        <span v-for="item in executionWarnings" :key="item">{{ item }}</span>
      </div>
      <div class="task-workload-list" aria-label="逻辑任务执行状态">
        <article v-for="row in logicalRows" :key="row.workload_id" data-workload-row :class="`task-${row.status.toLowerCase()}`">
          <div><strong>{{ row.workload_id }}</strong><span>{{ row.status }}</span></div>
          <dl>
            <div><dt>最近运行</dt><dd>{{ row.last_run || "未确认" }}</dd></div>
            <div><dt>下次计划</dt><dd>{{ row.next_due || "未配置" }}</dd></div>
            <div><dt>耗时</dt><dd>{{ duration(row) }}</dd></div>
            <div><dt>结果码</dt><dd>{{ row.result_code || "CANNOT_CONFIRM" }}</dd></div>
            <div><dt>新鲜度</dt><dd>{{ row.freshness || "CANNOT_CONFIRM" }}</dd></div>
          </dl>
          <details v-if="row.receipt_path"><summary>查看 receipt</summary><code>{{ row.receipt_path }}</code></details>
        </article>
      </div>
      <details v-if="payload.groups.registrations.length" class="task-registration-panel" aria-label="图谱待确认任务">
        <summary>图谱待确认任务 · 不会执行</summary>
        <p v-for="item in graphWarnings" :key="item">{{ item }}</p>
        <p>这些记录只有冻结图谱身份，没有可证明的执行 owner、命令或市场日期语义。</p>
        <div class="task-registration-list">
          <article v-for="row in payload.groups.registrations" :key="row.graph_task_spec_id" data-registration-row>
            <strong>{{ row.legacy_task_id }}</strong>
            <span>{{ row.status }} · enabled={{ row.enabled }} · execution_allowed={{ row.execution_allowed }}</span>
            <code>{{ row.graph_task_spec_id }}</code>
          </article>
        </div>
      </details>
      <details class="task-diagnostics">
        <summary>身份映射与诊断</summary>
        <section><h3>执行 owner</h3><p v-for="row in payload.groups.active_owners" :key="row.owner_id">{{ row.owner_id }} → {{ row.workload_id }}</p></section>
        <section><h3>别名</h3><p>仅映射，不产生第二次执行</p><p v-for="row in payload.groups.aliases" :key="row.alias">{{ row.alias }} → {{ row.workload_id }}</p></section>
        <section><h3>退役 owner</h3><p v-for="row in payload.groups.retired" :key="row.owner_id">{{ row.owner_id }} → {{ row.replacement_workload_id }}</p></section>
      </details>
      <p class="task-safety">研究边界：只读观察，不下单，不接交易接口。</p>
    </template>
  </section>
</template>
