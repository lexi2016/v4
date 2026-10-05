<script setup lang="ts">
import { feedCardKey, text } from "../../composables/useResearchLane";
import ResearchFeedCard from "./ResearchFeedCard.vue";
import ResearchSourceColumns from "./ResearchSourceColumns.vue";
import WechatResearchPanel from "./WechatResearchPanel.vue";

defineProps<{
  feedCards: Array<Record<string, unknown>>;
  feedFilter: string;
  archiveDate: string;
  onFilter: (filter: string) => void;
  columns?: Array<{ name: string; rows: Array<Record<string, unknown>> }>;
}>();

const TABS: Array<{ id: string; label: string }> = [
  { id: "latest", label: "全部" },
  { id: "morning", label: "早盘" },
  { id: "stock", label: "股票" },
  { id: "zsxq", label: "星球" },
  { id: "finance", label: "财经" },
  { id: "ai", label: "AI" },
  { id: "key", label: "重点" },
  { id: "wechat", label: "公众号" },
];
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
    <template v-else>
      <div class="hourly-feed-list">
        <ResearchFeedCard v-for="(card, index) in feedCards" :key="`${feedCardKey(card, index)}-${index}`" :card="card" />
        <div v-if="!feedCards.length" class="empty">当前情报日无 feed 条目。</div>
      </div>
      <ResearchSourceColumns v-if="columns?.length" :columns="columns" />
    </template>
  </section>
</template>
