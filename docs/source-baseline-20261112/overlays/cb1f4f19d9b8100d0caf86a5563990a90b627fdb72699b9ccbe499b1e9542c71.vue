<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { generateReview, loadReview } from "../api/review";
import AshareReviewPanel from "../components/review/AshareReviewPanel.vue";
import DailyResearchReviewPanel from "../components/review/DailyResearchReviewPanel.vue";
import HkCloseReviewPanel from "../components/review/HkCloseReviewPanel.vue";
import ReviewEvidencePanel from "../components/review/ReviewEvidencePanel.vue";
import type { ReviewEnvelope } from "../contracts/review";

const props = defineProps<{ payload: ReviewEnvelope; focus?: "A" | "HK" | "research" }>();
const focusRoot = ref<HTMLElement | null>(null);
const sections = computed(() => {
  const first = props.focus || "HK";
  return [first, ...(["HK", "A", "research"] as const).filter((name) => name !== first)];
});
watch(() => props.focus, async () => {
  await nextTick();
  focusRoot.value?.focus({ preventScroll: true });
  focusRoot.value?.scrollIntoView?.({ block: "start" });
}, { immediate: true });
const refreshed = ref<ReviewEnvelope>();
const current = computed<ReviewEnvelope>(() => {
  const value = refreshed.value;
  return value && value.trade_date === props.payload.trade_date ? value : props.payload;
});
const generating = ref(false);
const message = ref("");
watch(() => props.payload, () => { refreshed.value = undefined; message.value = ""; });

async function generateSelectedDate() {
  if (generating.value) return;
  const date = props.payload.trade_date;
  generating.value = true;
  message.value = "";
  try {
    await generateReview(date);
    const value = await loadReview(date);
    if (props.payload.trade_date === date && value.trade_date === date) {
      refreshed.value = value;
      message.value = "所选日期复盘已刷新。";
    }
  } catch (error) {
    if (props.payload.trade_date === date) message.value = error instanceof Error ? error.message : "生成状态未确认。";
  } finally {
    generating.value = false;
  }
}
</script>

<template>
  <section ref="focusRoot" tabindex="-1" class="review-view panel" aria-label="exact-date review" :data-review-focus="focus || 'HK'">
    <div class="section-heading"><div><span class="eyebrow">EXACT_DATE_REVIEW</span><h2>收盘复盘</h2></div><p>{{ current.trade_date }} · 研究模式</p></div>
    <p v-if="current.market_reviews.A.status === 'NOT_MATERIALIZED'" class="review-loading">该交易日复盘尚未生成</p>
    <p>各复盘共享精确日期读取接口，入口只改变内容定位；原版 Vibe 完整功能继续由8910提供。</p>
    <div v-for="section in sections" :key="section" :data-review-section="section">
      <template v-if="section === 'HK'">
        <p class="review-slot-banner" data-testid="hk-close-1610">16:10 港股市场正式收盘复盘</p>
        <HkCloseReviewPanel :review="current.market_reviews.HK" />
      </template>
      <AshareReviewPanel v-else-if="section === 'A'" :review="current.market_reviews.A" />
      <DailyResearchReviewPanel v-else :review="current.research_review" :intraday="current.intraday_research" :date="current.trade_date"
        :generating="generating" :generation-message="message" @generate="generateSelectedDate" />
    </div>
    <ReviewEvidencePanel :review="current.market_reviews.A" :production-allowed="current.production_allowed" :buy-gate-updated="current.buy_gate_updated" :orders-sent="current.orders_sent" />
  </section>
</template>
