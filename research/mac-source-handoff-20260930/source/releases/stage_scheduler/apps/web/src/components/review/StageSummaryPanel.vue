<script setup lang="ts">
import { computed } from "vue";

export type StageSummary = {
  trade_date?: string | null;
  stage_id?: string | null;
  stage_label?: string | null;
  phase_status?: string | null;
  selected_a_rows?: number | null;
  a_source_rows?: number | null;
  a_candidate_count?: number | null;
  selected_hk_rows?: number | null;
  hk_candidate_count?: number | null;
  reference_mode?: boolean | null;
  selected_total_rows?: number | null;
  data_level?: string | null;
};

type StageSummaryProps = {
  summary?: StageSummary | null;
  currentStageId?: string | null;
  phaseStatus?: string | null;
  selectedDate?: string | null;
  currentStageLabel?: string | null;
  selectedARows?: number | null;
  aSourceRows?: number | null;
  aCandidateCount?: number | null;
  selectedHkRows?: number | null;
  hkCandidateCount?: number | null;
  referenceMode?: boolean;
  selectedTotalRows?: number | null;
  dataLevel?: string | null;
};

const props = withDefaults(defineProps<StageSummaryProps>(), {
  phaseStatus: "CANNOT_CONFIRM",
  selectedDate: "",
  currentStageLabel: "",
  referenceMode: false,
  dataLevel: "CANNOT_CONFIRM",
});

const summary = computed<StageSummary>(() => props.summary ?? {
  trade_date: props.selectedDate,
  stage_id: props.currentStageLabel,
  stage_label: props.currentStageLabel,
  phase_status: props.phaseStatus,
  selected_a_rows: props.selectedARows,
  a_source_rows: props.aSourceRows,
  a_candidate_count: props.aCandidateCount,
  selected_hk_rows: props.selectedHkRows,
  hk_candidate_count: props.hkCandidateCount,
  reference_mode: props.referenceMode,
  selected_total_rows: props.selectedTotalRows,
  data_level: props.dataLevel,
});

const identityValid = computed(() => {
  const value = summary.value;
  if (typeof value.trade_date !== "string" || !/^\d{8}$/.test(value.trade_date)) return false;
  if (typeof value.stage_id !== "string" || !value.stage_id.trim()) return false;
  if (typeof value.stage_label !== "string" || !value.stage_label.trim()) return false;
  if (props.selectedDate && value.trade_date !== props.selectedDate) return false;
  if (props.currentStageId && value.stage_id !== props.currentStageId) return false;
  if (props.currentStageLabel && value.stage_label !== props.currentStageLabel) return false;
  return true;
});

function numberText(value: number | null | undefined) {
  return identityValid.value && typeof value === "number" && Number.isFinite(value)
    ? String(value)
    : "—";
}

function text(value: string | null | undefined, fallback = "CANNOT_CONFIRM") {
  return identityValid.value && value ? value : fallback;
}

function dateText(value: string | null | undefined) {
  return identityValid.value && value ? value : "—";
}

function sourceText() {
  if (!identityValid.value) return "—";
  return summary.value.reference_mode === true ? "本地参考快照" : "V3.5 原生输入";
}
</script>

<template>
  <section class="status-grid stage-summary-grid" aria-label="阶段摘要" data-stage-summary>
    <article><span>阶段状态</span><strong>{{ text(summary.phase_status) }}</strong><small>{{ dateText(summary.trade_date) }} / {{ identityValid ? summary.stage_label : "—" }} 阶段</small></article>
    <article><span>A股候选</span><strong>{{ numberText(summary.selected_a_rows) }}</strong><small>source rows {{ numberText(summary.a_source_rows) }}；candidate {{ numberText(summary.a_candidate_count) }}</small></article>
    <article><span>港股通候选</span><strong>{{ numberText(summary.selected_hk_rows) }}</strong><small>candidate {{ numberText(summary.hk_candidate_count) }}；同阶段观察</small></article>
    <article><span>港股通源</span><strong>{{ sourceText() }}</strong><small>运行时不调用旧 V3 服务</small></article>
    <article><span>统一行数</span><strong>{{ numberText(summary.selected_total_rows) }}</strong><small>A股与港股通同阶段合并展示</small></article>
    <article><span>数据级别</span><strong>{{ text(summary.data_level) }}</strong><small>阶段产物驱动，非交易接口</small></article>
    <article><span>执行边界</span><strong>研究边界</strong><small>只读观察，不下单，不接 broker</small></article>
  </section>
</template>
