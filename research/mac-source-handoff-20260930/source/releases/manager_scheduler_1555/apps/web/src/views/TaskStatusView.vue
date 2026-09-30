<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { loadTaskStatus } from "../api/runtime";
import type { LogicalWorkloadStatus, TaskStatusResponse } from "../contracts/runtime";


const props = defineProps<{ date: string }>();
const payload = ref<TaskStatusResponse | null>(null);
const loading = ref(false);
const error = ref("");
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
    payload.value = await loadTaskStatus(props.date, controller.signal);
  } catch (caught) {
    if (!(caught instanceof DOMException && caught.name === "AbortError")) {
      error.value = "任务状态读取失败，请检查 V3.5 状态 API。";
    }
  } finally {
    loading.value = false;
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
    <p v-if="loading" class="task-message" role="status">正在读取任务状态。</p>
    <p v-else-if="error" class="task-message task-error" role="alert">{{ error }}</p>
    <template v-else-if="payload">
      <div class="task-counts">
        <article><span>逻辑任务</span><strong>{{ payload.logical_workload_count }}</strong></article>
        <article><span>执行 owner</span><strong>{{ payload.active_owner_count }}</strong></article>
        <article><span>别名</span><strong>{{ payload.alias_count }}</strong></article>
        <article><span>退役 owner</span><strong>{{ payload.retired_owner_count }}</strong></article>
        <article><span>图谱待确认</span><strong>{{ payload.task_registration_count }}</strong></article>
      </div>
      <div v-if="payload.cannot_confirm.length" class="task-evidence-warning" role="alert">
        <strong>CANNOT_CONFIRM · 证据降级</strong>
        <span v-for="item in payload.cannot_confirm" :key="item">{{ item }}</span>
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
      <section v-if="payload.groups.registrations.length" class="task-registration-panel" aria-label="图谱待确认任务">
        <h3>图谱待确认任务 · 不会执行</h3>
        <p>这些记录只有冻结图谱身份，没有可证明的执行 owner、命令或市场日期语义。</p>
        <div class="task-registration-list">
          <article v-for="row in payload.groups.registrations" :key="row.graph_task_spec_id" data-registration-row>
            <strong>{{ row.legacy_task_id }}</strong>
            <span>{{ row.status }} · enabled=false · execution_allowed=false</span>
            <code>{{ row.graph_task_spec_id }}</code>
          </article>
        </div>
      </section>
      <details class="task-diagnostics">
        <summary>身份映射与诊断</summary>
        <section><h3>执行 owner</h3><p v-for="row in payload.groups.active_owners" :key="row.owner_id">{{ row.owner_id }} → {{ row.workload_id }}</p></section>
        <section><h3>别名</h3><p>仅映射，不产生第二次执行</p><p v-for="row in payload.groups.aliases" :key="row.alias">{{ row.alias }} → {{ row.workload_id }}</p></section>
        <section><h3>退役 owner</h3><p v-for="row in payload.groups.retired" :key="row.owner_id">{{ row.owner_id }} → {{ row.replacement_workload_id }}</p></section>
      </details>
      <p class="task-safety">production_allowed=false · buy_gate_updated=false · orders_sent=false</p>
    </template>
  </section>
</template>
