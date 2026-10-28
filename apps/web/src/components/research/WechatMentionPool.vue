<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import {
  loadWechatMentions,
  type MentionMarket,
  type WechatMentionList,
} from '../../api/wechat_research';

const props = defineProps<{ articleDate: string }>();
const emit = defineEmits<{ (event: 'open-report'): void }>();

const markets: Array<{ id: MentionMarket; label: string }> = [
  { id: 'A', label: 'A股' },
  { id: 'BJ', label: '北交所' },
  { id: 'HK', label: '港股' },
];
const market = ref<MentionMarket>('A');
const searchText = ref('');
const response = ref<WechatMentionList | null>(null);
const loading = ref(false);
const error = ref('');
let requestVersion = 0;
let controller: AbortController | null = null;

const counts = computed(() => response.value?.counts);
const rows = computed(() => response.value?.items ?? []);
const marketCount = (value: MentionMarket) => counts.value?.market_listings?.[value] ?? 0;
const marketRows = (value: MentionMarket) => counts.value?.market_rows?.[value] ?? 0;

function clearPage() {
  response.value = null;
  error.value = '';
}

async function loadPage(cursor?: string | null) {
  requestVersion += 1;
  const version = requestVersion;
  controller?.abort();
  controller = new AbortController();
  clearPage();
  if (!props.articleDate) return;
  loading.value = true;
  try {
    const result = await loadWechatMentions({
      date: props.articleDate,
      market: market.value,
      q: searchText.value,
      cursor,
      limit: 50,
    }, controller.signal);
    if (version === requestVersion) response.value = result;
  } catch (reason) {
    if (version === requestVersion) {
      error.value = reason instanceof Error && reason.name === 'AbortError'
        ? '公众号全文提及读取已取消；旧日期数据已清空。'
        : reason instanceof Error ? reason.message : '公众号全文提及读取失败；未回退其他日期或版本。';
    }
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}

function selectMarket(value: MentionMarket) {
  if (market.value === value) return;
  market.value = value;
  void loadPage();
}

function search() {
  void loadPage();
}

function nextPage() {
  if (response.value?.next_cursor) void loadPage(response.value.next_cursor);
}

watch(() => props.articleDate, () => {
  market.value = 'A';
  searchText.value = '';
  void loadPage();
}, { immediate: true });

onBeforeUnmount(() => {
  requestVersion += 1;
  controller?.abort();
});
</script>

<template>
  <section class="wechat-mention-pool" aria-label="公众号全文提及" data-testid="wechat-mention-pool">
    <header class="mention-heading">
      <div>
        <span class="mention-eyebrow">ARCHIVED ARTICLE MENTIONS · STAGE A READ ONLY</span>
        <h4>公众号全文提及</h4>
        <p>文章日 {{ articleDate || '未选择' }} 的原始 mentions.csv；按市场和上市代码去重展示。</p>
      </div>
      <button type="button" class="mention-report-button" data-testid="wechat-mention-open-report" @click="emit('open-report')">
        打开原报告
      </button>
    </header>

    <p class="mention-boundary">
      这是文章日归档事实，不是 PIT 阶段可用时间；全文提及包含券商 / 机构署名，不能当作推荐、评分、阶段候选或交易输入。
      发行人和证券代码未由独立主表复核，保留原始 mapping_status；安全边界：RESEARCH_ONLY · WATCH_ONLY · NO_BUY_GATE。
    </p>

    <form class="mention-controls" @submit.prevent="search">
      <label>搜索来源、名称、代码或上下文
        <input v-model="searchText" type="search" maxlength="500" placeholder="不排序，只筛选原始证据" data-testid="wechat-mention-search">
      </label>
      <button type="submit" :disabled="loading">查询</button>
    </form>

    <p v-if="loading" class="mention-message" role="status" data-testid="wechat-mention-loading">正在核对 mentions.csv 原字节并读取文章日归档。</p>
    <p v-else-if="error" class="mention-message mention-error" role="alert" data-testid="wechat-mention-error">{{ error }}</p>
    <template v-else-if="response">
      <div class="mention-summary">
        <span>当前页 {{ response.returned }} / 匹配 {{ response.total }} 个上市代码</span>
        <span v-if="counts">原始 {{ counts.rows }} 行 · {{ counts.issuers }} 个发行人 · source_named {{ counts.source_named_entities ?? counts.source_named_rows }} · supplemental {{ counts.supplemental_listing_rows }}</span>
        <span v-if="response.summary_status">结构状态：{{ response.summary_status }}</span>
      </div>
      <div v-if="response.cannot_confirm.length" class="mention-gaps" role="status">
        <strong>保留的证据边界：</strong>{{ response.cannot_confirm.join('、') }}
      </div>

      <nav class="mention-markets" aria-label="公众号提及市场分组">
        <button
          v-for="item in markets"
          :key="item.id"
          type="button"
          :class="{ active: market === item.id }"
          :aria-pressed="market === item.id"
          :data-testid="`wechat-mention-market-${item.id}`"
          @click="selectMarket(item.id)"
        >{{ item.label }} <span>{{ marketCount(item.id) }}</span><small>（原始 {{ marketRows(item.id) }} 行）</small></button>
      </nav>

      <p v-if="response.status === 'NOT_CONFIGURED'" class="mention-message" data-testid="wechat-mention-unconfigured">NOT_CONFIGURED：未配置公众号归档根目录，不代表没有文章。</p>
      <p v-else-if="response.status === 'NOT_INDEXED'" class="mention-message" data-testid="wechat-mention-not-indexed">NOT_INDEXED：该文章日没有已登记的 Stage A 归档。</p>
      <p v-else-if="response.status === 'MISSING'" class="mention-message" data-testid="wechat-mention-missing">REPORT_ONLY：当前版本缺少 mentions.csv；原报告仍可从上方入口阅读，未用旧版本补齐。</p>
      <template v-else>
        <div class="mention-provenance" v-for="item in response.provenance" :key="`${item.record_id}-${item.sha256}`">
          <span>原件 {{ item.filename }} · {{ item.status }} · {{ item.bytes }} bytes</span>
          <code>{{ item.sha256 }}</code>
        </div>
        <div class="mention-table-wrap">
          <table>
            <thead>
              <tr><th>代码</th><th>名称</th><th>原始映射</th><th>出处类型</th><th>来源次数 / 图片数</th><th>source_index / context</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in rows" :key="`${item.market}-${item.code}`">
                <td><strong>{{ item.code }}</strong><br><small>{{ item.market }}</small></td>
                <td>{{ item.name }}</td>
                <td :title="item.mapping_statuses.join('、')">
                  <span v-for="status in item.mapping_statuses" :key="status" class="mention-mapping-status">{{ status }}</span>
                </td>
                <td>
                  <span>{{ item.source_named_or_derived }}</span>
                  <span v-if="item.listing_origin === 'SUPPLEMENTAL_LISTING'" class="mention-supplemental">补充上市线</span>
                </td>
                <td>{{ item.source_count }} / {{ item.source_index_count }}</td>
                <td>
                  <details>
                    <summary>{{ item.source_indexes.join('、') }}</summary>
                    <p v-if="item.source_names.length"><strong>来源名称：</strong>{{ item.source_names.join('、') }}</p>
                    <p v-for="context in item.claim_contexts" :key="context"><strong>上下文：</strong>{{ context }}</p>
                  </details>
                </td>
              </tr>
              <tr v-if="!rows.length"><td colspan="6">当前市场或搜索条件没有匹配的原始提及。</td></tr>
            </tbody>
          </table>
        </div>
        <div class="mention-pagination">
          <span>总数 {{ response.total }}；分页读取，不截断为固定 Top200。</span>
          <button type="button" :disabled="!response.next_cursor || loading" data-testid="wechat-mention-next" @click="nextPage">下一页</button>
        </div>
      </template>
    </template>
    <p v-else class="mention-message" role="status">请选择文章日。</p>
  </section>
</template>

<style scoped>
.wechat-mention-pool { margin-top: 14px; padding: 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc; color: #172033; }
.mention-heading, .mention-summary, .mention-controls, .mention-markets, .mention-pagination { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.mention-heading { justify-content: space-between; gap: 16px; }
.mention-eyebrow { color: #64748b; font-size: 11px; letter-spacing: .08em; }
h4 { margin: 4px 0; }
p { margin: 7px 0; line-height: 1.5; }
.mention-boundary, .mention-message, .mention-gaps { font-size: 12px; color: #475569; }
.mention-gaps { padding: 8px; border-left: 3px solid #d97706; background: #fffbeb; }
.mention-controls { margin: 10px 0; }
.mention-controls label { display: flex; flex-direction: column; gap: 4px; min-width: min(420px, 100%); }
input, button { font: inherit; }
input, button { padding: 7px 10px; border: 1px solid #94a3b8; border-radius: 5px; background: #fff; color: #172033; }
button { cursor: pointer; }
button:disabled { cursor: default; opacity: .5; }
button:focus-visible { outline: 3px solid #2563eb; outline-offset: 2px; }
.mention-report-button { white-space: nowrap; }
.mention-markets { margin: 10px 0; }
.mention-markets button.active { border-color: #174fac; background: #e0ecff; }
.mention-markets small { color: #64748b; }
.mention-provenance { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; font-size: 12px; color: #475569; }
.mention-provenance code { overflow-wrap: anywhere; }
.mention-table-wrap { overflow-x: auto; border: 1px solid #cbd5e1; background: #fff; }
table { width: 100%; min-width: 920px; border-collapse: collapse; font-size: 12px; }
th, td { padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }
th { color: #475569; background: #f1f5f9; font-weight: 600; }
td:nth-child(3) { max-width: 300px; }
.mention-mapping-status { display: block; }
td:nth-child(6) { min-width: 260px; }
td p { max-width: 520px; overflow-wrap: anywhere; }
summary { cursor: pointer; color: #174fac; }
.mention-supplemental { display: block; margin-top: 4px; color: #9a3412; }
.mention-pagination { justify-content: space-between; margin-top: 10px; font-size: 12px; color: #475569; }
.mention-error { color: #991b1b; }
@media (max-width: 800px) { .wechat-mention-pool { padding: 10px; } .mention-heading { align-items: flex-start; } }
</style>
