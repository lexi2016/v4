<script setup lang="ts">
defineProps<{ items: Array<string> }>();
</script>

<template>
  <details v-if="items.length" class="review-appendix">
    <summary>技术/不能确认（{{ items.length }}）</summary>
    <div class="review-appendix-body">
      <ul class="review-list">
        <li v-for="(item, index) in items" :key="index">{{ item }}</li>
      </ul>
    </div>
  </details>
</template>
