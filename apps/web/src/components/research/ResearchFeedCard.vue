<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { loadResearchPdfDocumentDetail, type ResearchPdfDocumentDetail } from "../../api/research_lane";
import { feedCardPresentation, financeOriginalUrl, formatFeedTimestamp, safeExternalUrl, text } from "../../composables/researchFeedPresentation";
import { chipList } from "../../composables/useResearchLane";

const props = defineProps<{ card: Record<string, unknown> }>();
const presentation = computed(() => feedCardPresentation(props.card));
const isPdf = computed(() => text(props.card.kind) === "pdf");
function formatPdfTopicTimestamp(value: unknown): string {
  const raw = text(value);
  const compactOffset = raw.match(/^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)([+-])(\d{2})(\d{2})$/);
  return formatFeedTimestamp(compactOffset ? `${compactOffset[1]}${compactOffset[2]}${compactOffset[3]}:${compactOffset[4]}` : raw);
}
const pdfDetail = ref<ResearchPdfDocumentDetail | null>(null);
const pdfOpen = ref(false);
const pdfLoading = ref(false);
const pdfError = ref("");
const pdfIdentity = computed(() => `${text(props.card.research_date)}:${text(props.card.document_id)}`);
let pdfRequestVersion = 0;

watch(pdfIdentity, () => {
  pdfRequestVersion += 1;
  pdfDetail.value = null;
  pdfOpen.value = false;
  pdfLoading.value = false;
  pdfError.value = "";
});

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function pdfStatusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    READY: "已完成",
    PARTIAL: "部分完成",
    FAILED: "失败",
    PENDING: "待处理",
    CANNOT_CONFIRM: "无法确认",
  };
  const status = text(value).toUpperCase();
  return labels[status] || status || "未评估";
}

async function togglePdfDetail() {
  if (pdfDetail.value) {
    pdfOpen.value = !pdfOpen.value;
    return;
  }
  const documentId = text(props.card.document_id);
  const researchDate = text(props.card.research_date);
  if (!documentId || !researchDate) {
    pdfError.value = "缺少文档 ID 或精确研究日期，无法读取正文。";
    return;
  }
  const requestVersion = ++pdfRequestVersion;
  const requestIdentity = pdfIdentity.value;
  pdfLoading.value = true;
  pdfError.value = "";
  try {
    const detail = await loadResearchPdfDocumentDetail(documentId, researchDate);
    if (requestVersion !== pdfRequestVersion || requestIdentity !== pdfIdentity.value) return;
    pdfDetail.value = detail;
    pdfOpen.value = true;
  } catch (error) {
    if (requestVersion !== pdfRequestVersion || requestIdentity !== pdfIdentity.value) return;
    pdfError.value = error instanceof Error ? error.message : "PDF 正文读取失败。";
  } finally {
    if (requestVersion === pdfRequestVersion && requestIdentity === pdfIdentity.value) {
      pdfLoading.value = false;
    }
  }
}

const originalUrl = computed(() => {
  const card = props.card;
  const isFinance = text(card.source) === "finance"
    || text(card.kind) === "finance"
    || text(card.source_type) === "finance";
  return isFinance ? financeOriginalUrl(card) : safeExternalUrl(card.url);
});
</script>

<template>
  <article class="hourly-feed-card" :class="presentation.categoryClass">
    <div class="hourly-feed-head">
      <div>
        <div class="hourly-feed-title">{{ text(card.title || card.source_title || card.stock_name || card.stock_code) }}</div>
        <div class="hourly-meta">{{ isPdf ? "知识星球 PDF 补充" : presentation.sourceLabel }}</div>
      </div>
      <span v-if="isPdf" class="hourly-source-tag source">{{ pdfStatusLabel(card.status) }}</span>
      <span v-else-if="presentation.showTypeLabel" class="hourly-source-tag source">{{ presentation.typeLabel }}</span>
    </div>
    <template v-if="isPdf">
      <div class="hourly-meta">话题：{{ text(card.topic_title) || "CANNOT_CONFIRM" }} · {{ text(card.group_name) || "来源组未确认" }}</div>
      <div class="hourly-meta">原话题时间：{{ formatPdfTopicTimestamp(card.source_topic_published_at) || "CANNOT_CONFIRM" }} · PDF 发布时间：未知</div>
      <div class="hourly-meta">最近下载：{{ formatFeedTimestamp(card.downloaded_at) || "待处理" }} · OCR 完成：{{ formatFeedTimestamp(card.ocr_completed_at) || "待处理" }} · 延迟处理，非 PIT 补充</div>
      <div class="hourly-meta">页进度：{{ text(card.processed_page_count) || "0" }} / {{ text(card.page_count) || "待确认" }} 页 · 状态：{{ pdfStatusLabel(card.status) }}{{ text(card.reason_code) ? ` · ${text(card.reason_code)}` : "" }}</div>
      <div v-if="card.excerpt" class="hourly-summary">{{ text(card.excerpt) }}</div>
      <div class="hourly-focus-strip">
        <button v-if="card.can_open_detail" type="button" class="hourly-pill pdf-detail-button" :disabled="pdfLoading" @click="togglePdfDetail">
          {{ pdfLoading ? "读取中…" : pdfOpen ? "收起 OCR 正文" : "查看完整 OCR 正文" }}
        </button>
      </div>
      <p v-if="pdfError" class="hourly-meta pdf-error" role="status">{{ pdfError }}</p>
      <section v-if="pdfOpen && pdfDetail" class="pdf-detail" aria-label="PDF OCR 正文">
        <div class="hourly-meta">校验状态：{{ text(record(pdfDetail.receipt).integrity) }} · PDF SHA256 / 页面 SHA256 已核验</div>
        <div class="hourly-meta">PDF 发布时间：未知 · 最近下载：{{ formatFeedTimestamp(record(pdfDetail.processing).downloaded_at) || "CANNOT_CONFIRM" }} · OCR 完成：{{ formatFeedTimestamp(record(pdfDetail.processing).ocr_completed_at) || "CANNOT_CONFIRM" }}</div>
        <div v-if="pdfDetail.last_page_excerpt" class="pdf-last-page"><strong>末页节选</strong><p>{{ text(pdfDetail.last_page_excerpt) }}</p></div>
        <article v-for="page in pdfDetail.pages" :key="text(page.page_number)" class="pdf-page">
          <div class="hourly-meta">第 {{ text(page.page_number) }} 页 · {{ text(page.status) }} · {{ text(page.method) || "识别方法未确认" }}</div>
          <pre>{{ text(page.text) }}</pre>
        </article>
      </section>
    </template>
    <template v-else>
    <p v-if="card.entity_role" class="hourly-meta">原实体：{{ text(card.stock_name) }} {{ text(card.stock_code) }} · {{ text(card.entity_role) }}；角色分类不删除原文。</p>
    <div class="hourly-evidence-times" aria-label="时间证据">
      <span class="hourly-time-label">{{ presentation.fetchedTimeLabel }}</span>
      <span class="hourly-time-label">{{ presentation.publishedTimeLabel }}</span>
    </div>
    <div class="hourly-chips">
      <span v-for="chip in chipList(card)" :key="chip" class="hourly-chip">{{ chip }}</span>
    </div>
    <div class="hourly-summary">{{ text(card.summary || card.evidence_sentence || card.body_excerpt_preview || card.content).slice(0, 240) }}</div>
    <div class="hourly-focus-strip">
      <a v-if="originalUrl" :href="originalUrl" target="_blank" rel="noopener noreferrer" class="hourly-pill">打开原文</a>
    </div>
    </template>
  </article>
</template>
