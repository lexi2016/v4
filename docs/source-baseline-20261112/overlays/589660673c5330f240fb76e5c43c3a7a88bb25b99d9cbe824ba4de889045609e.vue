<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { loadResearchLane, loadResearchLaneLatest, type ResearchLane } from "../api/research_lane";
import {
  loadPosition25Exact,
  POSITION25_ASOF,
  POSITION25_CODES,
  type Position25Result,
} from "../api/position25";
import {
  loadSingleStockRepairSop,
  type SingleStockRepairSopResult,
} from "../api/singleStockRepairSop";
import { useResearchState } from "../composables/useResearchLane";
import ResearchStatusStrip from "../components/research/ResearchStatusStrip.vue";
import ResearchImpactList from "../components/research/ResearchImpactList.vue";
import ResearchFeedPane from "../components/research/ResearchFeedPane.vue";
import ResearchSourceColumns from "../components/research/ResearchSourceColumns.vue";
import ResearchContextPane from "../components/research/ResearchContextPane.vue";
import ResearchAppendix from "../components/research/ResearchAppendix.vue";
import "../styles/v3-research-lane.css";

const props = defineProps<{ archiveDate: string }>();

const payload = ref<ResearchLane | null>(null);
const loading = ref(false);
const error = ref("");
let requestVersion = 0;
const feedFilter = ref("latest");
const morningFilter = ref("all");
const position25Symbol = ref<string>(POSITION25_CODES[0]);
const position25Loading = ref(false);
const position25Error = ref("");
const position25Result = ref<Position25Result | null>(null);
const repairSopOpen = ref(false);
const repairSopLoading = ref(false);
const repairSopError = ref("");
const repairSopResult = ref<SingleStockRepairSopResult | null>(null);

const {
  stockMainline,
  stockTimeline,
  feedCards,
  sourceColumns,
  timelineRows,
  cannotItems,
  quality,
} = useResearchState(payload, feedFilter);

const wechatArticleCount = computed(() => {
  const morning = payload.value?.morning_news as Record<string, unknown> | undefined;
  return (morning?.articles as Array<unknown> | undefined)?.length ?? 0;
});

function validateResearchDate(result: ResearchLane, expectedDate?: string) {
  const actualDate = result?.research_date;
  if (typeof actualDate !== "string" || !actualDate) {
    throw new Error("研报决策台日期证据错误：响应缺少 research_date，未展示该响应。");
  }
  if (expectedDate && actualDate !== expectedDate) {
    throw new Error(`研报决策台日期证据错误：响应 research_date=${actualDate}，请求=${expectedDate}，未展示该响应。`);
  }
}

async function run(loader: () => Promise<ResearchLane>, expectedDate?: string) {
  const version = ++requestVersion;
  loading.value = true;
  error.value = "";
  payload.value = null;
  try {
    const result = await loader();
    validateResearchDate(result, expectedDate);
    if (version === requestVersion) payload.value = result;
  } catch (reason) {
    if (version === requestVersion) {
      error.value = reason instanceof Error ? reason.message : "研报决策台读取失败；未用其他日期替代。";
    }
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}

function loadExact() {
  if (!props.archiveDate) return;
  void run(() => loadResearchLane(props.archiveDate), props.archiveDate);
}

function loadLatest() {
  void run(loadResearchLaneLatest);
}

function scrollToWechat() {
  document.querySelector("#researchWechatSource")?.scrollIntoView({ behavior: "smooth" });
}

async function loadPosition25() {
  position25Loading.value = true;
  position25Error.value = "";
  position25Result.value = null;
  try {
    position25Result.value = await loadPosition25Exact(position25Symbol.value, POSITION25_ASOF);
  } catch (reason) {
    position25Error.value = reason instanceof Error
      ? reason.message
      : "CANNOT_CONFIRM：冻结位置字段读取失败；没有使用其他日期或数据源。";
  } finally {
    position25Loading.value = false;
  }
}

async function toggleRepairSop() {
  repairSopOpen.value = !repairSopOpen.value;
  if (!repairSopOpen.value) return;

  repairSopLoading.value = true;
  repairSopError.value = "";
  repairSopResult.value = null;
  try {
    repairSopResult.value = await loadSingleStockRepairSop();
  } catch (reason) {
    repairSopError.value = reason instanceof Error
      ? reason.message
      : "CANNOT_CONFIRM：研究面板更新 SOP 读取失败。";
  } finally {
    repairSopLoading.value = false;
  }
}

watch(() => props.archiveDate, loadExact, { immediate: true });
</script>

<template>
  <section class="research-view" role="region" aria-label="研报决策台">
    <div class="panel-head">
      <div>
        <h2>研报决策台</h2>
        <p id="researchSubtitle">研报、早盘新闻、公众号统一在此读取；只用于研究解释，不打开 BUY gate。</p>
      </div>
      <div class="panel-head-actions">
        <button type="button" class="secondary" :disabled="loading || !archiveDate" @click="loadExact">按所选日期</button>
        <button type="button" class="secondary" :disabled="loading" @click="loadLatest">查看 latest</button>
        <button type="button" class="secondary" @click="scrollToWechat">定位公众号</button>
        <button
          type="button"
          class="secondary"
          aria-controls="singleStockRepairSop"
          :aria-expanded="repairSopOpen"
          :disabled="repairSopLoading"
          @click="toggleRepairSop"
        >
          {{ repairSopLoading ? "读取 SOP 中…" : repairSopOpen ? "收起研究面板更新 SOP" : "研究面板更新 SOP" }}
        </button>
        <span class="badge readonly">只读研究</span>
      </div>
    </div>

    <section
      v-if="repairSopOpen"
      id="singleStockRepairSop"
      class="research-message repair-sop-card"
      aria-label="研究面板更新 SOP"
    >
      <strong>研究面板更新 SOP</strong>
      <p v-if="repairSopLoading" role="status">正在读取唯一 SOP 原文。</p>
      <p v-else-if="repairSopError" role="alert">CANNOT_CONFIRM：{{ repairSopError }}</p>
      <p v-else-if="repairSopResult?.status === 'CANNOT_CONFIRM'" role="status">
        CANNOT_CONFIRM：{{ repairSopResult.cannot_confirm.join("；") }} · {{ repairSopResult.source.path }}
      </p>
      <template v-else-if="repairSopResult?.status === 'READY'">
        <p class="repair-sop-source">
          唯一原文：{{ repairSopResult.source.path }} · SHA256 {{ repairSopResult.source.sha256 }}
        </p>
        <pre class="repair-sop-content">{{ repairSopResult.content }}</pre>
      </template>
    </section>

    <p v-if="loading" class="research-message" role="status">正在读取研报决策台。</p>
    <p v-else-if="error" class="research-message research-error" role="alert">{{ error }}</p>
    <div v-else-if="payload?.status === 'NOT_MATERIALIZED'" class="research-message research-missing" role="status">
      <strong>NOT_MATERIALIZED</strong>
      <span>{{ payload.reason }}</span>
    </div>

    <template v-else-if="payload">
      <section class="hourly-desk" id="hourlyInvestmentDesk" aria-label="研报决策台三栏">
        <ResearchStatusStrip
          :payload="payload"
          :stock-mainline-length="stockMainline.length"
          :stock-timeline-length="stockTimeline.length"
          :wechat-article-count="wechatArticleCount"
          :on-wechat="scrollToWechat"
        />

        <section class="hourly-desk-grid">
          <ResearchImpactList :rows="stockMainline" />

          <ResearchFeedPane
            :feed-cards="feedCards"
            :feed-filter="feedFilter"
            :on-filter="(f: string) => (feedFilter = f)"
            :columns="sourceColumns"
          />

          <ResearchContextPane :timeline-rows="timelineRows" :quality="quality" />
        </section>

        <ResearchAppendix :items="cannotItems" />
      </section>
    </template>

    <section class="research-message position25-card" aria-label="已审25股历史区间位置">
      <div class="position25-heading">
        <strong>已审25股：0至历史最高价区间位置</strong>
        <span class="badge readonly">只读冻结值</span>
      </div>
      <p class="position25-disclaimer">
        源日期：2026-10-23；版本：f3c4ce58；基准：QFQ_ASOF。此数值不是经验分位；范围为同一版本的完整可得接受前缀，不代表已认证的上市全历史。
      </p>
      <div class="position25-controls">
        <label for="position25Symbol">证券代码</label>
        <select id="position25Symbol" v-model="position25Symbol" :disabled="position25Loading">
          <option v-for="code in POSITION25_CODES" :key="code" :value="code">{{ code }}</option>
        </select>
        <button type="button" class="secondary" :disabled="position25Loading" @click="loadPosition25">
          {{ position25Loading ? "读取中…" : "读取冻结值" }}
        </button>
      </div>
      <p v-if="position25Error" class="position25-result position25-error" role="alert">CANNOT_CONFIRM：{{ position25Error }}</p>
      <p v-else-if="position25Result?.status === 'CANNOT_CONFIRM'" class="position25-result position25-error" role="status">
        CANNOT_CONFIRM：{{ position25Result.cannot_confirm.join("；") }}
      </p>
      <div v-else-if="position25Result?.status === 'READY'" class="position25-result" role="status">
        <strong>{{ position25Result.stock_name }}（{{ position25Result.ts_code }}）</strong>
        <span class="position25-value">{{ position25Result.zero_to_history_high_position_pct }}%</span>
        <span>源日期 {{ position25Result.source.asof }} · {{ position25Result.basis }} · {{ position25Result.source.generation }}</span>
        <span>来源 {{ position25Result.source.artifact }} · SHA256 {{ position25Result.source.sha256 }}</span>
      </div>
    </section>
  </section>
</template>

<style scoped>
.position25-card { border: 1px solid #d5e0e8; border-radius: 6px; }
.position25-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.position25-disclaimer { margin: 0; }
.position25-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.position25-controls select { min-height: 34px; padding: 4px 8px; }
.position25-result { display: grid; gap: 4px; margin: 0; overflow-wrap: anywhere; }
.position25-result.position25-error { color: #8b3232; }
.position25-value { font-size: 20px; font-weight: 700; color: #173f5f; }
.repair-sop-card { border: 1px solid #b9cbd8; border-radius: 6px; }
.repair-sop-source { margin: 0; overflow-wrap: anywhere; }
.repair-sop-content {
  max-height: 65vh;
  overflow: auto;
  margin: 0;
  padding: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f7f9fb;
  color: inherit;
  font: inherit;
}
</style>
