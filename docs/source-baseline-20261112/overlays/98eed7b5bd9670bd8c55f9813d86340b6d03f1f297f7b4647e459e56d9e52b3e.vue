<script setup lang="ts">
import { text } from "../../composables/useResearchLane";
import ResearchFeedCard from "./ResearchFeedCard.vue";
import ResearchSourceColumns from "./ResearchSourceColumns.vue";

defineProps<{
  feedCards: Array<Record<string, unknown>>;
  feedFilter: string;
  onFilter: (filter: string) => void;
  columns?: Array<{ name: string; rows: Array<Record<string, unknown>> }>;
}>();

const TABS: Array<{ id: string; label: string }> = [
  { id: "latest", label: "全部" },
  { id: "stock", label: "股票" },
  { id: "zsxq", label: "星球" },
  { id: "finance", label: "财经" },
  { id: "ai", label: "AI" },
  { id: "key", label: "重点" },
];
</script>

<template>
  <section class="hourly-feed-pane" aria-label="情报阅读">
    <div class="hourly-feed-toolbar">
      <div><span class="hourly-eyebrow">情报阅读</span><h3>feed · 情报流</h3></div>
      <div class="hourly-tabs">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          class="hourly-tab"
          :class="{ active: feedFilter === tab.id }"
          data-research-filter
          @click="onFilter(tab.id)"
        >{{ tab.label }}</button>
      </div>
    </div>
    <div class="hourly-feed-list">
      <ResearchFeedCard v-for="card in feedCards" :key="text(card.article_id || card.evidence_id || card.item_id || card.id)" :card="card" />
      <div v-if="!feedCards.length" class="empty">当前情报日无 feed 条目。</div>
    </div>
    <ResearchSourceColumns v-if="columns?.length" :columns="columns" />
  </section>
</template>
