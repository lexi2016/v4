<script setup lang="ts">
import type { TestContext } from './api';
defineProps<{context: TestContext; loading: boolean}>();
defineEmits<{ refresh: []; executeCanary: [] }>();
</script>
<template>
  <section class="mwb-panel test-context" aria-label="隔离测试上下文">
    <h1>公告选股 · 隔离测试</h1>
    <p>{{ context.evidence_kind }} · {{ context.mode }}。测试结果与正式运行证据分别保留。</p>
    <dl>
      <dt>测试运行</dt><dd>{{ context.test_run_id }}</dd><dt>目标日</dt><dd>{{ context.target_date }}</dd>
      <dt>来源 manifest SHA</dt><dd>{{ context.source_manifest_sha256 }}</dd>
      <dt>只读材料根</dt><dd>{{ context.read_only_material_roots }}</dd>
      <dt>独立状态根</dt><dd>{{ context.independent_state_root }}</dd>
      <dt>候选代码身份</dt><dd>{{ context.code_identity }}</dd>
      <dt>配置身份</dt><dd>{{ context.config_identity }}</dd><dt>模型身份</dt><dd>{{ context.model_identity }}</dd>
    </dl>
    <button type="button" :disabled="loading" @click="$emit('refresh')">刷新只读上下文</button>
    <button v-if="context.mode === 'canary' && context.canary_allowed" type="button" :disabled="loading" @click="$emit('executeCanary')">显式执行冻结单篇 canary</button>
    <p v-else>真实执行入口未启用；须有单篇 manifest 和后续授权。</p>
  </section>
</template>
<style scoped>
.test-context { overflow-wrap: anywhere; }
.test-context dd { margin-bottom: .5rem; }
</style>
