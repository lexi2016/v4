<script setup lang="ts">
import { computed } from "vue";

import { researchStatusPresentation } from "../../composables/useResearchLane";
import type { ResearchLane } from "../../api/research_lane";

const props = defineProps<{
  payload: ResearchLane;
  stockMainlineLength: number;
  stockTimelineLength: number;
  wechatArticleCount: number;
  onWechat: () => void;
}>();

const presentation = computed(() => researchStatusPresentation(props.payload, {
  wechatArticleCount: props.wechatArticleCount,
  stockMainlineLength: props.stockMainlineLength,
  stockTimelineLength: props.stockTimelineLength,
}));
</script>

<template>
  <section class="hourly-status-strip" aria-label="研报状态条">
    <div class="hourly-status-cell"><span class="hourly-label">本小时新增</span><strong>{{ presentation.newItemCount }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">知识星球</span><strong>{{ presentation.zsxqTopicCount }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">OCR</span><strong>{{ presentation.ocr }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">外部财经</span><strong>{{ presentation.externalFinanceCount }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">AI新闻</span><strong>{{ presentation.aiNewsCount }}</strong></div>
    <button type="button" class="hourly-status-cell hourly-status-button" data-wechat-entry="view" @click="onWechat">
      <span class="hourly-label">公众号归档/查看</span><strong>查看</strong><small>小时情报 {{ presentation.wechatArticleCount }} 条</small>
    </button>
    <div class="hourly-status-cell"><span class="hourly-label">股票主线</span><strong>{{ presentation.stockMainlineLength }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">直接事件</span><strong>{{ presentation.stockTimelineLength }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">重点消息</span><strong>{{ presentation.keyMessagesCount }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">小时线</span><strong>{{ presentation.hourlySlotCount }}</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">BUY gate</span><strong class="hourly-safe">只读</strong></div>
    <div class="hourly-status-cell"><span class="hourly-label">live order</span><strong class="hourly-safe">无</strong></div>
  </section>
</template>
