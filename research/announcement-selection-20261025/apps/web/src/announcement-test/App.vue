<script setup lang="ts">
import AnnouncementCandidates from '../manager-workbench/AnnouncementCandidates.vue';
import TestContextPanel from './TestContextPanel.vue';
import { useAnnouncementTest } from './useAnnouncementTest';
const props = defineProps<{transport?: typeof fetch}>();
const { session, error, loading, revision, refresh, executeCanary } = useAnnouncementTest(props.transport ?? fetch);
</script>
<template>
  <main class="mwb-workbench test-shell">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取隔离上下文…</p>
    <template v-if="session">
      <TestContextPanel :context="session.context" :loading="loading" @refresh="refresh" @execute-canary="executeCanary" />
      <AnnouncementCandidates :key="revision" :target-date="session.context.target_date" :api="session.announcementApi" read-only lock-target-date />
    </template>
  </main>
</template>
<style scoped>
.test-shell { max-width: 1280px; margin: auto; padding: 1.25rem; }
</style>
