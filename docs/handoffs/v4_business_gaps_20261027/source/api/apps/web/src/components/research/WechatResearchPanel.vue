<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import {
  loadWechatMaterial, loadWechatMaterials, safeArticleUrl, wechatArtifactUrl,
  type DateBasis, type WechatDetail, type WechatList,
} from '../../api/wechat_research';

const props = defineProps<{ archiveDate: string }>();
const dateBasis = ref<DateBasis>('article');
const allDates = ref(false);
const searchText = ref('');
const list = ref<WechatList | null>(null);
const detail = ref<WechatDetail | null>(null);
const loading = ref(false);
const detailLoading = ref(false);
const error = ref('');
const detailError = ref('');
let listVersion = 0;
let detailVersion = 0;
let listController: AbortController | null = null;
let detailController: AbortController | null = null;

function resetDetail() {
  detailVersion += 1;
  detailController?.abort();
  detail.value = null;
  detailError.value = '';
  detailLoading.value = false;
}
async function loadPage(cursor?: string | null) {
  const version = ++listVersion;
  listController?.abort();
  const controller = new AbortController();
  listController = controller;
  list.value = null;
  error.value = '';
  resetDetail();
  if (!allDates.value && !props.archiveDate) {
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const response = await loadWechatMaterials({
      date: allDates.value ? null : props.archiveDate,
      date_basis: dateBasis.value, q: searchText.value, cursor,
    }, controller.signal);
    if (version === listVersion) list.value = response;
  } catch (reason) {
    if (version === listVersion) {
      error.value = reason instanceof Error && reason.name === 'AbortError'
        ? '公众号请求已取消或超时；旧数据已清空，可重试。'
        : reason instanceof Error ? reason.message : '公众号读取失败；未回退旧版本。';
    }
  } finally {
    if (version === listVersion) loading.value = false;
  }
}
async function selectRecord(recordId: string) {
  const version = ++detailVersion;
  detailController?.abort();
  const controller = new AbortController();
  detailController = controller;
  detail.value = null;
  detailError.value = '';
  detailLoading.value = true;
  try {
    const response = await loadWechatMaterial(recordId, controller.signal);
    if (version === detailVersion) detail.value = response;
  } catch (reason) {
    if (version === detailVersion) {
      detailError.value = reason instanceof Error && reason.name === 'AbortError'
        ? '报告读取已取消或超时；未展示旧报告。'
        : reason instanceof Error ? reason.message : '报告读取失败。';
    }
  } finally {
    if (version === detailVersion) detailLoading.value = false;
  }
}
watch(() => [props.archiveDate, dateBasis.value, allDates.value], () => void loadPage(), { immediate: true });
onBeforeUnmount(() => {
  listVersion += 1;
  detailVersion += 1;
  listController?.abort();
  detailController?.abort();
});
</script>

<template>
  <section id="wechatResearchArchive" class="wechat-archive" aria-label="公众号研究归档">
    <header class="wechat-heading">
      <div>
        <h3>公众号研究归档</h3>
        <p>查看原报告与来源版本。全文提及、研究候选和阶段选股不由本区生成。</p>
      </div>
      <span class="wechat-badge">RESEARCH_ONLY · WATCH_ONLY · NO_BUY_GATE</span>
    </header>
    <form class="wechat-controls" @submit.prevent="loadPage()">
      <label>日期口径
        <select v-model="dateBasis" data-testid="wechat-date-basis">
          <option value="article">文章日</option><option value="received">本地接收日</option>
        </select>
      </label>
      <label><input v-model="allDates" type="checkbox" data-testid="wechat-all-dates"> 全日期</label>
      <label class="wechat-search">查询
        <input v-model="searchText" type="search" maxlength="500" placeholder="标题、公众号、原链接或版本身份" data-testid="wechat-search">
      </label>
      <button type="submit" :disabled="loading">查询 / 刷新</button>
    </form>
    <p class="wechat-note">所选日期：{{ allDates ? '全日期' : archiveDate || '未选择' }}；
      本地接收时间不是文章发布时间，也不是研究可用时间。阶段 A 的 available_at 不作补推。</p>
    <p v-if="loading" role="status" data-testid="wechat-loading">正在读取公众号资料，旧卡片已清空。</p>
    <p v-else-if="error" role="alert" data-testid="wechat-error">{{ error }}</p>
    <p v-else-if="!list" role="status">请选择日期，或勾选全日期。</p>
    <p v-else-if="list.status === 'NOT_CONFIGURED'" role="status" data-testid="wechat-unconfigured">
      NOT_CONFIGURED：尚未配置公众号原始归档根目录；不代表已经导入或没有文章。
    </p>
    <p v-else-if="list.status === 'NOT_INDEXED'" role="status" data-testid="wechat-not-indexed">
      NOT_INDEXED：尚未显式登记归档 receipt；本页面不会自动扫描、导入或补造数据。
    </p>
    <p v-else-if="list.total === 0" role="status" data-testid="wechat-empty">
      当前查询未匹配已索引资料；可切换文章日 / 接收日或全日期。不会回退到其他日期。
    </p>
    <template v-else>
      <div class="wechat-pagination" v-if="list">
        <span data-testid="wechat-count">匹配 {{ list.total }} 个归档版本，本页 {{ list.returned }} 个。</span>
        <button type="button" @click="loadPage()">首页</button>
        <button type="button" :disabled="!list.next_cursor" @click="loadPage(list.next_cursor)" data-testid="wechat-next">下一页</button>
      </div>
      <div class="wechat-layout wechat-layout--reading">
        <div class="wechat-list">
          <article v-for="item in list?.items" :key="item.record_id" class="wechat-card" data-testid="wechat-card">
            <h4>{{ item.article.title || '标题未确认' }}</h4>
            <p>公众号：{{ item.article.account || '未确认（原 receipt 未提供）' }}</p>
            <p>文章日：{{ item.article.article_date || '未确认' }}<br>
              真实发布时间：{{ item.article.published_at || '未确认，不能由文章日补齐' }}<br>
              本地接收：{{ item.received_at || '未确认' }}</p>
            <dl class="wechat-states">
              <dt>归档</dt><dd>{{ item.states.archive }}</dd>
              <dt>输入绑定</dt><dd>{{ item.states.input_binding }}</dd>
              <dt>结构核验</dt><dd>{{ item.states.structure }}</dd>
              <dt>研究核验</dt><dd>{{ item.states.research_review }}</dd>
            </dl>
            <p class="wechat-note">绑定 / 结构来自本地导入 receipt；本次展示不重复作语义验收。</p>
            <p>缺失附件：{{ item.missing_artifacts.join('、') || '无缺失声明；不等于研究已验' }}</p>
            <p>资料包：<code>{{ item.identity.package_id || '未提供' }}</code><br>
              回传 ID：<code>{{ item.identity.return_id || '旧格式未提供；以本记录及 receipt 区分版本' }}</code><br>
              记录：<code>{{ item.record_id }}</code></p>
            <a v-if="safeArticleUrl(item.article.url)" :href="safeArticleUrl(item.article.url)" target="_blank" rel="noopener noreferrer">打开微信原文</a>
            <button type="button" @click="selectRecord(item.record_id)" data-testid="wechat-open-report">阅读此版本</button>
          </article>
        </div>
        <div class="wechat-detail" aria-label="公众号报告版本详情">
          <p v-if="detailLoading" role="status" data-testid="wechat-detail-loading">正在核对原件哈希并读取该版本。</p>
          <p v-else-if="detailError" role="alert" data-testid="wechat-detail-error">{{ detailError }}</p>
          <template v-else-if="detail">
            <h4>{{ detail.material.article.title || '原报告' }}</h4>
            <p>当前读取：{{ detail.status }} · 原报告：{{ detail.report.status }}</p>
            <details class="wechat-identity-details" data-testid="wechat-identity-details">
              <summary>身份与来源核验（展开查看版本、SHA、时间和可用性）</summary>
              <dl class="wechat-identity">
                <dt>source run</dt><dd>{{ detail.material.identity.source_run_id || '未提供' }}</dd>
                <dt>package ID</dt><dd>{{ detail.material.identity.package_id || '未提供' }}</dd>
                <dt>input digest</dt><dd>{{ detail.material.identity.input_digest || '未绑定；未借用新版材料' }}</dd>
                <dt>return ID</dt><dd>{{ detail.material.identity.return_id || '旧格式未提供' }}</dd>
                <dt>receipt SHA-256</dt><dd>{{ detail.material.identity.receipt_sha256 }}</dd>
                <dt>ZIP SHA-256</dt><dd>{{ detail.material.identity.package_sha256 || '未提供' }}（导入 receipt 声明）</dd>
                <dt>图清单 SHA-256</dt><dd>{{ detail.material.identity.manifest_sha256 || '未提供' }}</dd>
                <dt>索引登记时间</dt><dd>{{ detail.material.indexed_at }}</dd>
                <dt>研究 available_at</dt><dd>{{ detail.material.available_at || '未建立；不能当历史选股依据' }}</dd>
                <dt>来源访问</dt><dd>{{ detail.material.source_status }}</dd>
              </dl>
            </details>
            <details open class="wechat-gaps">
              <summary>缺失与未确认事项（{{ detail.material.cannot_confirm.length }}）</summary>
              <ul><li v-for="reason in detail.material.cannot_confirm" :key="reason">{{ reason }}</li></ul>
              <p>独立研究复核未在本阶段执行；原报告中的结论和引文不因展示而获认可。</p>
            </details>
            <details class="wechat-artifacts">
              <summary>来源 / 附件（{{ detail.artifacts.length }}）</summary>
              <p>CHAT_RETURN 为回传原件；FROZEN_INPUT 为同 input_digest 的冻结输入。NOT_RECHECKED 表示尚未打开；点击时核验原字节。</p>
              <ul>
                <li v-for="artifact in detail.artifacts" :key="artifact.artifact_id">
                  <strong>{{ artifact.filename }}</strong> · {{ artifact.kind }} · {{ artifact.status }} · {{ artifact.bytes }} bytes<br>
                  <code>{{ artifact.sha256 }}</code><br>
                  <a v-if="['HASH_MATCH','NOT_RECHECKED'].includes(artifact.status)" :href="wechatArtifactUrl(detail.material.record_id, artifact.artifact_id)" download>读取原字节附件</a>
                </li>
              </ul>
            </details>
            <p class="wechat-note">报告按安全纯文本展示，保留 Markdown 原文；不执行 HTML，不加载其中的图片或附件路径。</p>
            <pre v-if="detail.report.content !== null" class="wechat-report" data-testid="wechat-report">{{ detail.report.content }}</pre>
            <p v-else role="alert" data-testid="wechat-report-unavailable">该版本原报告当前不可读取：{{ detail.report.status }}。未使用缓存或其他版本替代。</p>
          </template>
          <p v-else>选择一条归档版本阅读。旧格式报告可见，不补造全文提及、事件或候选。</p>
        </div>
      </div>
    </template>
    <footer class="wechat-note">本地原始归档为唯一原件；V4 只读引用。production_allowed=false · buy_gate_updated=false · orders_sent=false</footer>
  </section>
</template>

<style scoped>
.wechat-archive { border: 1px solid #cbd5e1; border-radius: 10px; padding: 18px; margin: 18px 0; background: #f8fafc; color: #172033; }
.wechat-heading, .wechat-controls, .wechat-pagination { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.wechat-heading { justify-content: space-between; }
h3, h4 { margin: 0 0 8px; }
p { margin: 8px 0; line-height: 1.55; }
.wechat-badge { font-size: 12px; padding: 6px; border: 1px solid #cbd5e1; border-radius: 6px; }
.wechat-controls { margin-top: 12px; }
.wechat-controls label { display: flex; align-items: center; gap: 6px; }
.wechat-search { flex: 1; min-width: 200px; }
.wechat-search input { width: 100%; }
input, select, button { font: inherit; }
input[type=search], select, button { padding: 7px 10px; border: 1px solid #94a3b8; border-radius: 5px; background: #fff; color: #172033; }
button { cursor: pointer; }
button:disabled { cursor: default; opacity: .5; }
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid #2563eb; outline-offset: 2px; }
a { color: #174fac; overflow-wrap: anywhere; }
.wechat-layout { display: flex; flex-direction: column; align-items: stretch; gap: 16px; margin-top: 12px; min-width: 0; }
.wechat-list, .wechat-detail { width: 100%; min-width: 0; box-sizing: border-box; }
.wechat-card { width: 100%; box-sizing: border-box; padding: 14px; margin-bottom: 12px; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; overflow-wrap: anywhere; }
.wechat-card button { margin: 8px; }
.wechat-states, .wechat-identity { display: grid; grid-template-columns: minmax(85px, auto) minmax(0, 1fr); gap: 6px 12px; font-size: 13px; }
dd { margin: 0; overflow-wrap: anywhere; }
dt { color: #475569; }
code { font-size: 12px; overflow-wrap: anywhere; }
.wechat-note { font-size: 12px; color: #475569; }
.wechat-detail { background: #fff; padding: 16px; border: 1px solid #cbd5e1; border-radius: 6px; }
.wechat-identity-details { margin: 12px 0; padding: 10px; border: 1px solid #e2e8f0; border-radius: 6px; background: #f8fafc; overflow-wrap: anywhere; }
.wechat-identity-details > summary { font-weight: 600; }
.wechat-report { max-width: 100%; box-sizing: border-box; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.8 system-ui, sans-serif; margin: 16px 0; }
.wechat-gaps, .wechat-artifacts { padding: 10px; margin: 12px 0; background: #f1f5f9; overflow-wrap: anywhere; }
summary { cursor: pointer; }
li { margin: 6px 0; line-height: 1.6; }
[role=alert] { color: #991b1b; overflow-wrap: anywhere; }
@media (max-width: 800px) { .wechat-archive { padding: 12px; } .wechat-identity { grid-template-columns: 1fr; } }
</style>
