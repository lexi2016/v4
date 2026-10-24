<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { loadResearchPdfList, loadResearchPdfAnalysis, type ResearchPdfList, type ResearchPdfSummary, type ResearchPdfDetail } from "../../api/research_lane";
import ResearchFeedCard from "./ResearchFeedCard.vue";

const props = defineProps<{ archiveDate: string }>();
const undated = ref(false);
const loading = ref(false);
const error = ref("");
const listing = ref<ResearchPdfList | null>(null);
const rows = ref<ResearchPdfSummary[]>([]);
const selected = ref<ResearchPdfSummary | null>(null);
const detail = ref<ResearchPdfDetail | null>(null);
const detailLoading = ref(false);
const detailError = ref("");
let listRequest = 0;
let detailRequest = 0;
let listAbort: AbortController | undefined;
let detailAbort: AbortController | undefined;
const selectionDate = computed(() => undated.value ? null : props.archiveDate);
const versions = computed(() => selected.value?.versions ?? []);
const scopedLegacy = computed(() => selected.value?.legacy_references?.find(row => row.semantic_review?.endsWith("PASS")));
const selectedGeneration = ref<number | null>(null);
const rowKey = (row: ResearchPdfSummary) => `${row.reference_id}:${row.occurrence.occurrence_id}`;

function clearDetail() {
  detailAbort?.abort();
  detailRequest += 1;
  selected.value = null;
  detail.value = null;
  detailLoading.value = false;
  detailError.value = "";
}
async function readList(more = false) {
  const cursor = more ? listing.value?.next_cursor : null;
  if (more && !cursor) return;
  listAbort?.abort();
  listAbort = new AbortController();
  const request = ++listRequest;
  const date = selectionDate.value;
  loading.value = true;
  error.value = "";
  if (!more) { listing.value = null; rows.value = []; clearDetail(); }
  try {
    const result = await loadResearchPdfList({ researchDate: date }, cursor, { signal: listAbort.signal });
    if (request !== listRequest || date !== selectionDate.value) return;
    listing.value = result;
    rows.value = more ? [...rows.value, ...result.items] : result.items;
  } catch (reason) {
    if (request === listRequest) error.value = reason instanceof Error ? reason.message : "PDF 列表读取失败。";
  } finally {
    if (request === listRequest) loading.value = false;
  }
}
async function openReport(row: ResearchPdfSummary, generation?: number | null) {
  detailAbort?.abort();
  detailAbort = new AbortController();
  const request = ++detailRequest;
  selected.value = row;
  selectedGeneration.value = generation === undefined ? (row.accepted ?? row.latest_generated)?.generation ?? null : generation;
  const legacy = !row.accepted && (generation === null || generation === undefined) ? scopedLegacy.value : undefined;
  if (legacy) selectedGeneration.value = null;
  detail.value = null;
  detailError.value = "";
  if (row.reference_kind !== "LEGACY_REFERENCE" && selectedGeneration.value === null && !legacy) return;
  detailLoading.value = true;
  try {
    const result = await loadResearchPdfAnalysis(legacy ?? row, selectedGeneration.value, { signal: detailAbort.signal });
    if (request === detailRequest && selected.value && rowKey(selected.value) === rowKey(row)) detail.value = result;
  } catch (reason) {
    if (request === detailRequest) detailError.value = reason instanceof Error ? reason.message : "PDF 正文读取失败。";
  } finally {
    if (request === detailRequest) detailLoading.value = false;
  }
}
function changeVersion(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (selected.value) void openReport(selected.value, value === "legacy" ? null : Number(value));
}
watch(() => props.archiveDate, () => { undated.value = false; });
watch(selectionDate, () => void readList(), { immediate: true });
onBeforeUnmount(() => { listRequest += 1; detailRequest += 1; listAbort?.abort(); detailAbort?.abort(); });
</script>

<template>
  <section class="research-pdf-panel" aria-label="PDF 研报阅读区">
    <div class="panel-head">
      <div><h3>PDF 研报</h3><p>按原文注明日期读取；未知日期单列。生成正文与独立内容验收分别显示。</p></div>
      <div class="panel-head-actions">
        <button type="button" :aria-pressed="!undated" @click="undated = false">所选日期 {{ archiveDate }}</button>
        <button type="button" :aria-pressed="undated" @click="undated = true">未注明日期</button>
        <button type="button" :disabled="loading" @click="readList()">刷新 PDF</button>
      </div>
    </div>
    <p class="hourly-meta">{{ undated ? '未注明日期，不从文件名推断' : `原文日期 ${archiveDate}` }} · {{ listing ? `共 ${listing.total_count} 条` : '尚未读取' }}</p>
    <p v-if="error" role="alert" class="research-error">{{ error }}</p>
    <p v-if="loading" role="status">正在读取 PDF 摘要…</p>
    <p v-else-if="listing?.status === 'NOT_MATERIALIZED'" role="status">PDF 分析尚未物化；未执行分析或状态修复。</p>
    <p v-else-if="listing?.status === 'READY_EMPTY'" role="status">此日期没有 PDF 分析记录。</p>
    <div class="research-pdf-layout">
      <div class="research-pdf-list">
        <article v-for="row in rows" :key="rowKey(row)" class="research-pdf-summary" :data-selected="selected && rowKey(selected) === rowKey(row)">
          <button type="button" class="research-pdf-title" @click="openReport(row)">{{ String(row.metadata.title || row.occurrence.original_source_id) }}</button>
          <p class="hourly-meta">文本准备 {{ row.preparation_status }} · 执行 {{ row.execution_status }}</p>
          <p class="hourly-meta">{{ row.accepted ? `已验收 · ${row.accepted.scope}` : row.reference_kind === 'LEGACY_REFERENCE' ? `历史范围 · ${row.semantic_review} · ${row.scope}` : row.latest_generated ? '已生成 · 待独立内容验收' : '尚无分析正文' }}</p>
          <p v-if="row.reason_code || row.latest_execution" class="research-error">{{ row.reason_code || `${row.latest_execution?.status} · ${row.latest_execution?.reason_code}` }}</p>
          <p v-if="row.latest_generated && row.accepted && row.latest_generated.generation !== row.accepted.generation" class="hourly-meta">另有最新待验版本 g{{ row.latest_generated.generation }}</p>
        </article>
        <button v-if="listing?.next_cursor" type="button" :disabled="loading" @click="readList(true)">加载下一页（20 条）</button>
      </div>
      <div class="research-pdf-reader" aria-live="polite">
        <label v-if="versions.length && selected">分析版本
          <select :value="selectedGeneration === null ? 'legacy' : selectedGeneration" @change="changeVersion"><option v-if="scopedLegacy" value="legacy">历史已验范围 · {{ scopedLegacy.scope }}（非全文验收）</option><option v-for="version in versions" :key="version.generation" :value="version.generation">g{{ version.generation }} · {{ version.semantic_review }}{{ version.scope ? ` · ${version.scope}` : '' }}</option></select>
        </label>
        <p v-if="detailLoading" role="status">正在读取固定版本正文…</p>
        <p v-if="detailError" role="alert" class="research-error">{{ detailError }}</p>
        <ResearchFeedCard v-if="detail" :card="{ title: selected?.metadata.title }" :report="detail" />
        <p v-else-if="selected && !detailLoading && !detailError" role="status">尚无可读分析正文。{{ selected.reason_code }}</p>
        <p v-else-if="!selected">选择一份研报阅读正文与引用。</p>
      </div>
    </div>
  </section>
</template>
