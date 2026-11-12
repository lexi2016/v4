<script setup lang="ts">
import type { MachineCardsPayload } from "../../api/research_lane";
import { feedCardKey, text } from "../../composables/useResearchLane";
import ResearchFeedCard from "./ResearchFeedCard.vue";
import ResearchSourceColumns from "./ResearchSourceColumns.vue";
import WechatResearchPanel from "./WechatResearchPanel.vue";

defineProps<{
  feedCards: Array<Record<string, unknown>>;
  feedFilter: string;
  archiveDate: string;
  onFilter: (filter: string) => void;
  emptyMessage?: string;
  columns?: Array<{ name: string; rows: Array<Record<string, unknown>>; emptyMessage?: string }>;
  machineCards?: MachineCardsPayload | null;
  machineCardsLoading?: boolean;
  machineCardsError?: string;
  machineCardItems?: MachineCardsPayload["items"];
}>();

const TABS: Array<{ id: string; label: string }> = [
  { id: "latest", label: "全部" },
  { id: "morning", label: "早盘" },
  { id: "stock", label: "股票" },
  { id: "zsxq", label: "星球" },
  { id: "finance", label: "财经" },
  { id: "ai", label: "AI" },
  { id: "key", label: "重点" },
  { id: "machine", label: "机器研报" },
  { id: "wechat", label: "公众号" },
];

const reviewLabel = (status: string): string => (
  status === "REVIEWED" ? "已人工审核" : status === "NOT_REVIEWED" ? "未人工审核" : "人工审核 CANNOT_CONFIRM"
);
</script>

<template>
  <section class="hourly-feed-pane" aria-label="情报阅读">
    <div class="hourly-feed-toolbar">
      <div><span class="hourly-eyebrow">情报阅读</span><h3>feed · 情报流</h3></div>
      <div v-if="feedFilter === 'latest'" class="hourly-feed-order-note" role="status">全部 · 按获取时间降序；缺失时间显示 CANNOT_CONFIRM</div>
      <div class="hourly-tabs">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          class="hourly-tab"
          :class="{ active: feedFilter === tab.id }"
          :aria-pressed="feedFilter === tab.id"
          data-research-filter
          @click="onFilter(tab.id)"
        >{{ tab.label }}</button>
      </div>
    </div>
    <WechatResearchPanel v-if="feedFilter === 'wechat'" :archive-date="archiveDate" />
    <template v-else-if="feedFilter === 'machine'">
      <p class="research-message machine-feed-note">机器生成 · 未人工审核 · 不进入信号与买点</p>
      <p class="research-message">报告预览为机器原文，不是权威事实，不构成买卖建议。</p>
      <p v-if="machineCardsLoading" class="research-message" role="status">正在读取机器研报卡片。</p>
      <p v-else-if="machineCardsError" class="research-message research-error" role="status">{{ machineCardsError }}</p>
      <div v-else-if="machineCards?.status === 'NOT_MATERIALIZED'" class="research-message research-missing" role="status">
        <strong>NOT_MATERIALIZED</strong>
        <span>该日期暂无机器卡片：机器研报卡片目录尚未生成。</span>
      </div>
      <template v-else>
        <p v-if="machineCards?.truncated" class="research-message" role="status">
          该日期共 {{ machineCards.matched_count }} 张机器卡片，仅展示前 {{ machineCards.max_cards_per_date }} 张（truncated）。
        </p>
        <p v-if="(machineCards?.duplicate_count ?? 0) > 0" class="research-message" role="status">
          另有 {{ machineCards?.duplicate_count }} 份重复分析已按 document_id 合并。
        </p>
        <p v-if="(machineCards?.cannot_confirm_count ?? 0) > 0" class="research-message" role="status">
          另有 {{ machineCards?.cannot_confirm_count }} 张卡片无法确认：{{ machineCards?.cannot_confirm.join(" · ") }}。
        </p>
        <div class="hourly-feed-list">
          <article
            v-for="card in machineCardItems"
            :key="`${card.document_id}-${card.batch_id}`"
            class="hourly-feed-card"
          >
            <header class="hourly-feed-head">
              <div>
                <strong class="hourly-feed-title">{{ card.title }}</strong>
                <div class="hourly-chips">
                  <span class="hourly-chip">{{ card.status }}</span>
                  <span v-if="card.review.origin_status" class="hourly-chip">{{ card.review.origin_status }}</span>
                  <span v-if="card.review.source_review_status" class="hourly-chip">{{ card.review.source_review_status }}</span>
                  <span class="hourly-chip">{{ reviewLabel(card.review.review_status) }}</span>
                </div>
              </div>
            </header>
            <p class="research-message">原始文件名：{{ card.source.original_filename }}</p>
            <pre class="machine-card-preview">{{ card.report.preview }}</pre>
          </article>
          <div v-if="!(machineCardItems?.length ?? 0)" class="empty">该日期暂无机器卡片。</div>
        </div>
      </template>
    </template>
    <template v-else>
      <div class="hourly-feed-list">
        <ResearchFeedCard v-for="(card, index) in feedCards" :key="`${feedCardKey(card, index)}-${index}`" :card="card" />
        <div v-if="!feedCards.length" class="empty">{{ emptyMessage || "当前情报日无 feed 条目。" }}</div>
      </div>
      <ResearchSourceColumns v-if="columns?.length" :columns="columns" />
    </template>
  </section>
</template>

<style scoped>
.machine-card-preview {
  margin: 8px 0 0;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #182026;
  background: #f0f3f2;
  border: 1px solid #d5d9d6;
  border-radius: 6px;
}
</style>
