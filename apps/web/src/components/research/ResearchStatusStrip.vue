<script setup lang="ts">
import { num } from "../../composables/useResearchLane";
import type { ResearchLane } from "../../api/research_lane";

const props = defineProps<{
  payload: ResearchLane;
  stockMainlineLength: number;
  stockTimelineLength: number;
  wechatArticleCount: number;
  onWechat: () => void;
}>();

const quality = (props.payload.research_quality_summary ?? {}) as Record<string, unknown>;
const zsxq = (props.payload.zsxq_hourly ?? {}) as Record<string, unknown>;
const ai = (props.payload.ai_news ?? {}) as Record<string, unknown>;
const finance = (props.payload.external_finance ?? {}) as Record<string, unknown>;
const ocr = (props.payload.ocr_ingestion ?? {}) as Record<string, unknown>;
const hourly = (props.payload.hourly_research ?? {}) as Record<string, unknown>;
const keyMessages = Array.isArray(props.payload.key_investment_messages)
  ? props.payload.key_investment_messages as Array<unknown>
  : null;
const ocrStatus = String(ocr.status ?? "").trim().toUpperCase();
const ocrCountsAvailable = Number.isInteger(ocr.done_count) && Number.isInteger(ocr.failed_count);
const ocrDisplay = (() => {
  const statusLabels: Record<string, string> = {
    READY: "已完成",
    PARTIAL: "部分完成",
    INCOMPLETE: "未完成",
    NOT_ASSESSED: "未评估",
    NOT_MATERIALIZED: "未生成",
    CANNOT_CONFIRM: "无法确认",
    UNKNOWN: "未知",
  };
  const statusLabel = statusLabels[ocrStatus] ?? ocrStatus;
  const unavailableStatuses = ["NOT_ASSESSED", "NOT_MATERIALIZED", "CANNOT_CONFIRM", "UNKNOWN"];
  if (unavailableStatuses.includes(ocrStatus)) return statusLabel;
  if (ocrCountsAvailable) {
    const counts = `${num(ocr.done_count)}/${num(ocr.failed_count)}`;
    return statusLabel ? `${statusLabel} · ${counts}` : counts;
  }
  return statusLabel || "未评估";
})();
</script>

<template>
  <section class="hourly-status-strip" aria-label="研报状态条">
    <div class="hourly-status-cell"><span class="hourly-label">本小时新增</span><strong>{{ num(quality.new_item_count) }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">知识星球</span><strong>{{ num(zsxq.topic_count ?? zsxq.zsxq_topic_count_0800_0900) }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">OCR</span><strong>{{ ocrDisplay }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">外部财经</span><strong>{{ num(finance.raw_item_count) }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">AI新闻</span><strong>{{ num(ai.item_count) }}</strong></div>
    <button type="button" class="hourly-status-cell hourly-status-button" data-wechat-entry="view" @click="onWechat">
      <span class="hourly-label">公众号归档/查看</span><strong>查看</strong><small>小时情报 {{ wechatArticleCount }} 条</small>
    </button>
    <div class="hourly-status-cell"><span class="hourly-label">股票主线</span><strong>{{ stockMainlineLength }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">直接事件</span><strong>{{ stockTimelineLength }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">重点消息</span><strong>{{ keyMessages === null ? "未评估" : keyMessages.length }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">小时线</span><strong>{{ num(hourly.slot_count) }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">BUY gate</span><strong class="hourly-safe">只读</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">live order</span><strong class="hourly-safe">无</strong></div>
  </section>
</template>
