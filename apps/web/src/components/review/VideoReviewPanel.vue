<script setup lang="ts">
import { computed } from "vue";
import { videoReviewView } from "./videoReview";

const props = defineProps<{
  tradeDate: string;
  video?: unknown;
  gapRows?: unknown;
  learningRows?: unknown;
}>();
const view = computed(() => videoReviewView(props.tradeDate, props.video, props.gapRows, props.learningRows));
</script>

<template>
  <section class="video-review" aria-label="视频复盘" data-testid="video-review-panel">
    <header class="video-heading">
      <div><span class="video-eyebrow">来源与逐条证据</span><h3 class="video-title">视频复盘</h3></div>
      <span class="video-badge" data-testid="video-lock-status">{{ view.summary }}</span>
    </header>
    <div class="video-source">
      <p class="video-source-title" data-testid="video-source-title">{{ view.title }}</p>
      <p class="video-source-line">
        <a v-if="view.url" :href="view.url" target="_blank" rel="noopener noreferrer" data-testid="video-source-link">查看原视频 · {{ view.bv }}</a>
        <span v-else>原视频链接未提供</span>
      </p>
      <p class="video-source-line">目标日期：{{ tradeDate || "未提供" }} · {{ view.dateMessage }}</p>
      <dl class="video-metadata">
        <div><dt>来源记录</dt><dd>{{ view.sourceStatus }}</dd></div>
        <div><dt>采集状态</dt><dd>{{ view.captureStatus }}</dd></div>
        <div><dt>转写状态</dt><dd data-testid="video-asr-status">{{ view.asrStatus }}</dd></div>
        <div><dt>转写段数（来源记录）</dt><dd data-testid="video-segment-count">{{ view.segments }}</dd></div>
        <div><dt>转写可用性</dt><dd>{{ view.usable }}</dd></div>
        <div><dt>逐条对照状态</dt><dd>{{ view.gapStatus }}</dd></div>
        <div><dt>本页对照与学习记录</dt><dd>{{ view.rows.length }} 条</dd></div>
      </dl>
      <details v-if="view.artifacts.length" class="video-artifacts">
        <summary>来源工件 · {{ view.artifacts.length }} 项</summary>
        <p v-for="(artifact, index) in view.artifacts" :key="index" class="video-source-line">{{ artifact.kind }}：{{ artifact.path || "未提供路径" }}<span v-if="artifact.sha"> · SHA-256：{{ artifact.sha }}</span></p>
      </details>
    </div>
    <p v-if="view.pending" class="video-notice" data-testid="video-pending">ASR 待复核：转写、股票名与时间段尚不能作为已确认内容，不能据此判定结论通过。</p>
    <p class="video-boundary">逐条记录展示来源字段。关键词命中、材料存在和本地已有输出均不代表已完成语义分析；市场独立复盘与视频证据分别判断。</p>
    <p v-if="view.cannotConfirm" class="video-notice">来源仍缺：{{ view.cannotConfirm }}</p>
    <details v-if="view.transcript.length" class="video-transcript" data-testid="video-transcript">
      <summary class="video-transcript-summary">原始转写（待复核） · 已提取 {{ view.transcript.length }} 段，展开查看全文</summary>
      <p class="video-boundary">以下为原始 ASR，尚未校订，不代表观点提炼或分析完成。时间点来自转写分段，口播内容仍待复核。</p>
      <p v-if="view.contentMessage" class="video-boundary">{{ view.contentMessage }}</p>
      <ol class="video-transcript-list">
        <li v-for="segment in view.transcript" :key="segment.key" class="video-transcript-segment" data-testid="video-transcript-segment">
          <a :href="segment.url" target="_blank" rel="noopener noreferrer" class="video-segment-time">{{ segment.time }} · 待复核</a>
          <p class="video-text">{{ segment.text }}</p>
        </li>
      </ol>
      <p class="video-boundary">转写来源：{{ view.contentSource }}</p>
    </details>
    <p v-else-if="view.canShow" class="video-boundary" data-testid="video-transcript-missing">可读转写正文未提供；转写段数不等于正文已提取或内容已确认。</p>
    <p v-if="view.contentCannotConfirm" class="video-notice">转写正文仍缺：{{ view.contentCannotConfirm }}</p>

    <div v-if="view.rows.length" class="video-evidence-list">
      <article v-for="(row, index) in view.rows" :key="row.key" class="video-evidence" data-testid="video-evidence-row">
        <header class="video-row-heading"><h4 class="video-item">{{ index + 1 }}. {{ row.item }}</h4><span class="video-row-kind">{{ row.kind }}</span></header>
        <div class="video-comparison">
          <div class="video-comparison-cell"><h5 class="video-field-label">视频观点 / 框架</h5><p class="video-text">{{ row.point }}</p></div>
          <div class="video-comparison-cell"><h5 class="video-field-label">本地复盘对照</h5><p class="video-text">{{ row.local }}</p></div>
        </div>
        <p class="video-text"><strong>缺口：</strong>{{ row.gap }} · <strong>记录状态：</strong>{{ row.status }}</p>
        <blockquote v-if="row.quote" class="video-quote"><span class="video-field-label">原句（来源字段，校订状态见转写记录）</span>{{ row.quote }}</blockquote>
        <p v-if="row.snippet" class="video-text"><strong>证据片段（未校订）：</strong>{{ row.snippet }}</p>
        <p v-if="row.impact" class="video-text"><strong>影响 / 改进方向：</strong>{{ row.impact }}</p>
        <p v-if="row.cannotConfirm" class="video-notice"><strong>仍待确认：</strong>{{ row.cannotConfirm }}</p>
        <footer class="video-row-footer">
          <a v-if="row.timeUrl" :href="row.timeUrl" target="_blank" rel="noopener noreferrer" data-testid="video-timestamp-link">原视频 {{ row.time }}{{ view.pending ? "（待复核）" : "" }}</a>
          <span v-else>{{ row.time }}</span>
          <span v-if="row.evidence" class="video-evidence-path">证据路径：{{ row.evidence }}</span>
        </footer>
      </article>
    </div>
    <p v-else class="video-empty" data-testid="video-evidence-empty">{{ view.canShow ? "当天视频尚未提供可展示的逐条对照或学习记录；采集与转写状态见上方。" : "缺少同日可核对的视频来源，逐条对照与学习记录暂不展示。" }}</p>
    <p class="video-safety">仅供研究 · production_allowed=false · buy_gate_updated=false · orders_sent=false</p>
  </section>
</template>

<style scoped>
.video-review { min-width: 0; max-width: 100%; box-sizing: border-box; margin: 18px 0; padding: 20px; border: 1px solid #d0d5dd; border-radius: 12px; background: #fff; color: #344054; overflow-wrap: anywhere; }
.video-heading, .video-row-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 10px; }
.video-eyebrow, .video-row-kind { color: #667085; font-size: 12px; }
.video-title { margin: 4px 0 0; font-size: 20px; color: #101828; }
.video-badge { padding: 5px 9px; background: #f2f4f7; border-radius: 6px; font-size: 13px; }
.video-source { margin-top: 16px; padding: 14px; border-radius: 8px; background: #f8fafc; }
.video-source-title { margin: 0 0 8px; font-size: 16px; font-weight: 700; }
.video-source-line { margin: 6px 0; font-size: 13px; line-height: 1.6; }
.video-artifacts { margin-top: 14px; font-size: 12px; }
.video-artifacts summary { cursor: pointer; color: #475467; }
.video-metadata { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 16px 0 0; }
.video-metadata > div { min-width: 0; }
.video-metadata dt, .video-field-label { color: #667085; font-size: 12px; font-weight: 600; }
.video-metadata dd { margin: 5px 0 0; font-size: 14px; line-height: 1.6; }
.video-notice, .video-empty { padding: 10px 12px; border-left: 3px solid #d9a441; background: #fffaeb; color: #7a4b05; font-size: 13px; line-height: 1.7; }
.video-boundary, .video-safety { color: #667085; font-size: 12px; line-height: 1.7; }
.video-evidence-list { display: grid; gap: 14px; margin-top: 16px; }
.video-transcript { min-width: 0; margin: 16px 0; padding: 12px; border: 1px solid #d0d5dd; border-radius: 8px; }
.video-transcript-summary { cursor: pointer; font-size: 14px; font-weight: 600; line-height: 1.7; }
.video-transcript-list { margin: 14px 0; padding-left: 20px; }
.video-transcript-segment { min-width: 0; margin: 12px 0; padding: 0 0 12px; border-bottom: 1px solid #eaecf0; }
.video-segment-time { font-size: 12px; }
.video-evidence { min-width: 0; padding: 16px; border: 1px solid #e4e7ec; border-radius: 8px; }
.video-item { margin: 0; color: #101828; font-size: 15px; }
.video-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 14px 0; }
.video-comparison-cell { min-width: 0; }
.video-field-label { display: block; margin: 0 0 6px; }
.video-text { margin: 7px 0; white-space: pre-wrap; font-size: 14px; line-height: 1.75; }
.video-quote { margin: 12px 0; padding: 10px 14px; border-left: 3px solid #98a2b3; background: #f9fafb; white-space: pre-wrap; font-size: 14px; line-height: 1.75; }
.video-row-footer { display: flex; flex-direction: column; gap: 7px; margin-top: 12px; font-size: 12px; line-height: 1.6; color: #667085; }
.video-evidence-path { white-space: pre-wrap; }
.video-review a { color: #175cd3; text-decoration: underline; }
.video-review a:focus-visible { outline: 2px solid #175cd3; outline-offset: 3px; }
.video-safety { margin-bottom: 0; }
@media (max-width: 600px) {
  .video-review { padding: 12px; }
  .video-metadata { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .video-comparison { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .video-evidence { padding: 12px; }
}
</style>
