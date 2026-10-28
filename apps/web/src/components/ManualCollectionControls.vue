<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { collectionTerminal, readCollection, startCollection } from "../api/manualCollection";
import type { CollectionJob, CollectionTarget } from "../api/manualCollection";

const props = defineProps<{ date: string; target: CollectionTarget; stageId?: string }>();
const emit = defineEmits<{ completed: [job: CollectionJob] }>();
const job = ref<CollectionJob | null>(null);
const busy = ref(false);
const error = ref("");
const pending = ref(false);
const supported = computed(() => props.target === "HK_CLOSE" || props.stageId === "STAGE_1545_1555");
const label = computed(() => props.target === "HK_CLOSE" ? "港股通收盘" : "阶段8（15:45–15:55）");
const statuses: Record<string, string> = {
  PENDING: "已登记", RUNNING: "执行中", READY: "已补齐", REUSED: "已复用",
  SNAPSHOT_CAPTURED: "快照已采集，选股未生成", PARTIAL: "已有产出，仍有缺口", CANNOT_CONFIRM: "未确认补齐",
};
let version = 0;
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let releaseWait: (() => void) | undefined;

function stop() {
  version += 1;
  controller?.abort();
  clearTimeout(timer);
  releaseWait?.();
  releaseWait = undefined;
  busy.value = false;
}
watch(() => [props.date, props.target, props.stageId], () => {
  stop(); job.value = null; error.value = ""; pending.value = false;
});
onBeforeUnmount(stop);

async function run(resume = false) {
  if (busy.value || !props.date || !supported.value) return;
  const request = { date: props.date, target: props.target,
    ...(props.target === "HK_STAGE" ? { stage_id: props.stageId } : {}) };
  const current = ++version;
  controller = new AbortController();
  const signal = controller.signal;
  busy.value = true; error.value = ""; pending.value = false;
  const accept = (value: CollectionJob) => {
    if (value.trade_date !== request.date || value.target !== request.target ||
        (value.stage_id || undefined) !== request.stage_id) throw new Error("补采回执的日期或阶段与请求不一致。");
    job.value = value;
  };
  try {
    const initial = resume && job.value
      ? await readCollection(job.value.job_id, signal) : await startCollection(request, signal);
    if (version !== current) return;
    accept(initial);
    // Thirty seconds of bounded observation; the server's owned task continues.
    for (let count = 0; count < 20 && !collectionTerminal(job.value!.status); count += 1) {
      await new Promise<void>((resolve) => { releaseWait = resolve; timer = setTimeout(resolve, 1500); });
      releaseWait = undefined;
      if (version !== current) return;
      const next = await readCollection(initial.job_id, signal);
      if (version !== current) return;
      accept(next);
    }
    if (!collectionTerminal(job.value!.status)) pending.value = true;
    else if (["READY", "REUSED", "SNAPSHOT_CAPTURED", "PARTIAL"].includes(job.value!.status)) {
      emit("completed", job.value!);
    }
  } catch (reason) {
    if (version === current) error.value = reason instanceof Error ? reason.message : "补采未通过。";
  } finally {
    if (version === current) busy.value = false;
  }
}
</script>

<template>
  <section class="manual-collection" :aria-label="`${label}补采集`">
    <button type="button" :disabled="busy || !date || !supported || pending" @click="run()">
      {{ busy ? "补采执行中…" : "补采集" }}
    </button>
    <span>{{ date }} · {{ label }}</span>
    <p v-if="!supported">该阶段尚未接入受控补采；本入口仅支持港股阶段8。</p>
    <template v-if="job">
      <p role="status">{{ statuses[job.status] || job.status }} · {{ job.step }} · {{ job.message }}</p>
      <p v-if="job.result.universe_count !== undefined">收盘覆盖：{{ job.result.same_date_row_count ?? 0 }} / {{ job.result.universe_count }}；复盘：{{ job.result.review_status || '尚未生成' }}</p>
      <p v-if="job.result.selection_status">历史观察：{{ job.result.selection_status }}；选股 {{ job.result.selected_rows ?? 0 }} 行；原自然阶段回执保持。</p>
      <p v-if="job.result.backfill_run_id">补采编号：{{ job.result.backfill_run_id }}</p>
      <p v-if="job.result.missing_stages?.length">仍缺阶段：{{ job.result.missing_stages.join('、') }}</p>
      <p v-if="job.cannot_confirm.length">原因：{{ job.cannot_confirm.join('；') }}</p>
    </template>
    <p v-if="pending">任务仍在执行，已停止自动查询。<button type="button" :disabled="busy" @click="run(true)">查看进度</button></p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.manual-collection { margin-block: 0.75rem; padding: 0.75rem; border: 1px solid #53617a; border-radius: 0.5rem; }
.manual-collection > span { margin-left: 0.75rem; }
.manual-collection p { margin: 0.4rem 0; overflow-wrap: anywhere; }
</style>
