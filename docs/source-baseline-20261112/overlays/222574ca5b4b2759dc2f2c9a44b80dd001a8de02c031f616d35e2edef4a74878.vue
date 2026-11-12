<script setup lang="ts">
import AshareReviewPanel from "../components/review/AshareReviewPanel.vue";
import HkCloseReviewPanel from "../components/review/HkCloseReviewPanel.vue";
import ReviewEvidencePanel from "../components/review/ReviewEvidencePanel.vue";
import type { ReviewEnvelope } from "../contracts/review";

defineProps<{ payload: ReviewEnvelope }>();
</script>

<template>
  <section class="review-view panel" aria-label="exact-date review">
    <div class="section-heading"><div><span class="eyebrow">EXACT_DATE_REVIEW</span><h2>收盘复盘</h2></div><p>{{ payload.trade_date }} · 只读</p></div>
    <p v-if="payload.market_reviews.A.status === 'NOT_MATERIALIZED'" class="review-loading">该交易日复盘尚未生成</p>
    <AshareReviewPanel :review="payload.market_reviews.A" />
    <HkCloseReviewPanel :review="payload.market_reviews.HK" />
    <ReviewEvidencePanel :review="payload.market_reviews.A" :production-allowed="payload.production_allowed" :buy-gate-updated="payload.buy_gate_updated" :orders-sent="payload.orders_sent" />
  </section>
</template>
