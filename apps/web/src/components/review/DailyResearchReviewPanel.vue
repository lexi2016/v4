<script setup lang="ts">
import { computed } from "vue";

import type { DailyResearchReview, DailyResearchReviewSection, IntradayResearchReview } from "../../contracts/review";

type Row = Readonly<Record<string, unknown>>;

const props = defineProps<{ review?: DailyResearchReview; intraday?: IntradayResearchReview; date?: string; generating?: boolean; generationMessage?: string }>();
const emit = defineEmits<{ generate: [] }>();

const currentReview = computed(() => props.review);
const ready = computed(() => currentReview.value?.status === "READY");
const status = computed(() => currentReview.value?.status || "CANNOT_CONFIRM");
const gaps = computed(() => currentReview.value?.cannot_confirm ?? []);

function record(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Row
    : {};
}

function records(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function value(value: unknown): string {
  if (value === undefined || value === null || value === "") return "未确认";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "未确认";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? `${value.length} 条` : "0 条";
  return json(value);
}

function entries(section: DailyResearchReviewSection | undefined, excluded: readonly string[] = []) {
  const omit = new Set(excluded);
  return Object.entries(section ?? {}).filter(([key]) => !omit.has(key));
}

function field(section: DailyResearchReviewSection | undefined, key: string): unknown {
  return section?.[key];
}

function json(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) || "未确认";
  } catch {
    return "未确认";
  }
}

function isComplex(value: unknown): boolean {
  return Array.isArray(value) || Boolean(value && typeof value === "object");
}

function summary(input: unknown): string {
  if (Array.isArray(input)) return `${input.length} 条 · 展开完整内容`;
  if (input && typeof input === "object") return `${Object.keys(input).length} 个字段 · 展开完整内容`;
  return value(input);
}

function fieldCount(value: unknown): number {
  return value && typeof value === "object" ? Object.keys(value).length : 0;
}

const feedbackOrder = computed(() =>
  (Array.isArray(currentReview.value?.feedback_matrix?.order)
    ? currentReview.value?.feedback_matrix?.order
    : []).map(String),
);
const feedbackRows = computed(() => Object.entries(record(currentReview.value?.feedback_matrix?.matrix)));
const feedbackDetails = computed(() => records(currentReview.value?.feedback_matrix?.details));
const promotionTiers = computed(() => Object.entries(record(currentReview.value?.promotion?.tiers)));
const themeRows = computed(() => records(currentReview.value?.theme_tree?.themes));
const eventRows = computed(() => records(currentReview.value?.event_ledger?.events));
const eventCategories = computed(() => [
  { key: "loss_events", label: "亏损事件", rows: records(currentReview.value?.event_ledger?.loss_events) },
  { key: "gain_events", label: "赚钱事件", rows: records(currentReview.value?.event_ledger?.gain_events) },
  { key: "split_events", label: "反复开板事件", rows: records(currentReview.value?.event_ledger?.split_events) },
]);

function matrixCell(row: unknown, key: string): string {
  return value(record(row)[key]);
}

function themeMembers(row: Row): string {
  const members = records(row.members);
  return members.length ? `${members.length} 个成员` : "未确认";
}

function memberKey(row: Row, index: number): string {
  return `${value(row.code)}-${value(row.name)}-${index}`;
}
</script>

<template>
  <section class="daily-research-review-panel" aria-label="daily research review" data-testid="daily-research-review-panel">
    <div class="section-heading">
      <div><span class="eyebrow">DAILY_RESEARCH_REVIEW</span><h2>每日研究复盘</h2></div>
      <p>{{ currentReview?.target_date || currentReview?.trade_date || "未确认日期" }} · {{ status }} · 只读</p>
    </div>

    <div v-if="date" class="daily-research-review-meta">
      <button type="button" :disabled="generating" @click="emit('generate')">生成所选日期复盘</button>
      <span v-if="generating" role="status">所选日期正在生成；请勿重复提交。</span>
      <span v-if="generationMessage" role="status">{{ generationMessage }}</span>
    </div>

    <section class="daily-research-review-section" data-testid="intraday-research">
      <h3>竞价与盘中客观路径</h3>
      <p>六时点：09:25、09:35、10:00、11:30、14:00、15:00。缺失时点不以当前行情回填。</p>
      <p v-if="intraday?.missing_slots?.length">缺失：{{ intraday.missing_slots.join("、") }}</p>
      <p v-if="!intraday?.slots?.length">所选日期盘中快照未确认。</p>
      <div v-else class="daily-research-review-table-wrap">
        <table><thead><tr><th>时点</th><th>前日池 / 已报价</th><th>覆盖率</th><th>均涨幅</th><th>中位涨幅</th><th>高开 / 红盘率</th><th>跌幅≤−5%</th><th>采集时间 / 漂移</th></tr></thead>
          <tbody><tr v-for="snap in intraday.slots" :key="snap.slot">
            <td>{{ snap.slot }}</td><td>{{ snap.expected_sample }} / {{ snap.sample }}</td>
            <td>{{ snap.coverage_rate === null ? "未确认" : `${(snap.coverage_rate * 100).toFixed(1)}%` }}</td>
            <td>{{ snap.avg }}%</td><td>{{ snap.median }}%</td>
            <td>{{ snap.slot === "09:25" ? "高开率" : "红盘率" }} {{ (snap.up_rate * 100).toFixed(1) }}%</td>
            <td>{{ snap.deep_loss_5 }}</td><td>{{ snap.captured_at }} / {{ snap.drift_minutes }}分钟</td>
          </tr></tbody>
        </table>
        <details v-for="snap in intraday.slots" :key="`detail-${snap.slot}`">
          <summary>{{ snap.slot }} 盘面家数、分板位及最高标客观读数（完整）</summary>
          <pre>{{ json({ live: snap.live, by_tier: snap.by_tier, top_boards: snap.top_boards, top_board_level: snap.top_board_level }) }}</pre>
        </details>
        <details><summary>09:25 竞价与昨晚验证条件（完整）</summary><pre>{{ json(intraday.auction) }}</pre></details>
        <details><summary>来源与本地证据校验范围</summary><pre>{{ json(intraday.evidence) }}</pre></details>
      </div>
      <p>哈希校验不等于供应商事实取证；池日期来自请求或批准缓存的声明，报价日期来自原始行情时间戳。</p>
      <p v-for="gap in (intraday?.cannot_confirm ?? [])" :key="gap">{{ gap }}</p>
    </section>

    <div v-if="!ready" class="daily-research-review-missing" data-testid="daily-research-review-missing">
      <strong>研究复盘证据未确认</strong>
      <span v-for="item in (gaps.length ? gaps : ['DAILY_RESEARCH_REVIEW_NOT_AVAILABLE'])" :key="item">{{ item }}</span>
      <small>只读取请求日期的 dated JSON；未使用 latest.json，生成仅通过上方按钮显式触发。</small>
    </div>

    <template v-else>
      <div class="daily-research-review-meta" data-testid="daily-research-review-meta">
        <span>source_role={{ currentReview?.source_role || "CANNOT_CONFIRM" }}</span>
        <span>data_as_of={{ currentReview?.data_as_of || "CANNOT_CONFIRM" }}</span>
        <span>artifact_sha256={{ currentReview?.source_artifact_sha256 || "CANNOT_CONFIRM" }}</span>
      </div>
      <div v-if="gaps.length" class="daily-research-review-warning" data-testid="daily-research-review-generation-gap">
        <strong>持续生成责任</strong>
        <span v-for="item in gaps" :key="item">{{ item }}</span>
        <small>复盘由用户手动生成；来源声明仍为 DECLARED_ONLY，不代表独立事实取证，也不启动日复盘定时任务。</small>
      </div>

      <section class="daily-research-review-section" data-testid="daily-research-review-focus">
        <div class="daily-research-review-section-heading"><h3>昨日复盘重点</h3><span>完整字段 {{ fieldCount(currentReview?.focus) }}</span></div>
        <dl class="daily-research-review-kv daily-research-review-kv-wide">
          <div v-for="[key, item] in entries(currentReview?.focus)" :key="key">
            <dt>{{ key }}</dt>
            <dd>
              <details v-if="isComplex(item)">
                <summary>{{ summary(item) }}</summary>
                <pre>{{ json(item) }}</pre>
              </details>
              <template v-else>{{ value(item) }}</template>
            </dd>
          </div>
          <div v-if="!entries(currentReview?.focus).length"><dt>focus</dt><dd>CANNOT_CONFIRM</dd></div>
        </dl>
        <details class="daily-research-review-full-view">
          <summary>查看复盘重点完整 JSON</summary>
          <pre>{{ json(currentReview?.focus) }}</pre>
        </details>
      </section>

      <section class="daily-research-review-section" data-testid="daily-research-market-breadth">
        <div class="daily-research-review-section-heading"><h3>市场广度</h3><span>{{ value(field(currentReview?.market_breadth, "date")) }} · 完整字段 {{ fieldCount(currentReview?.market_breadth) }}</span></div>
        <div class="daily-research-review-metrics">
          <article><span>上涨</span><strong>{{ value(field(currentReview?.market_breadth, "up")) }}</strong></article>
          <article><span>下跌</span><strong>{{ value(field(currentReview?.market_breadth, "down")) }}</strong></article>
          <article><span>平盘</span><strong>{{ value(field(currentReview?.market_breadth, "flat")) }}</strong></article>
          <article><span>成交额（亿）</span><strong>{{ value(field(currentReview?.market_breadth, "amount_yi")) }}</strong></article>
          <article><span>样本总数</span><strong>{{ value(field(currentReview?.market_breadth, "universe")) }}</strong></article>
          <article><span>口径</span><strong>{{ value(field(currentReview?.market_breadth, "up_down_scope")) }}</strong></article>
        </div>
        <dl class="daily-research-review-kv">
          <div v-for="[key, item] in entries(currentReview?.market_breadth, ['date', 'up', 'down', 'flat', 'amount_yi', 'universe', 'up_down_scope'])" :key="key">
            <dt>{{ key }}</dt>
            <dd>
              <details v-if="isComplex(item)">
                <summary>{{ summary(item) }}</summary>
                <pre>{{ json(item) }}</pre>
              </details>
              <template v-else>{{ value(item) }}</template>
            </dd>
          </div>
        </dl>
        <details class="daily-research-review-full-view">
          <summary>查看市场广度完整 JSON</summary>
          <pre>{{ json(currentReview?.market_breadth) }}</pre>
        </details>
      </section>

      <section class="daily-research-review-section" data-testid="daily-research-feedback-matrix">
        <div class="daily-research-review-section-heading"><h3>昨日强势反馈矩阵</h3><span>{{ value(field(currentReview?.feedback_matrix, "prev_date")) }} · 覆盖 {{ value(field(currentReview?.feedback_matrix, "coverage")) }} · 明细 {{ feedbackDetails.length }} 条</span></div>
        <div class="daily-research-review-table-wrap">
          <table>
            <thead><tr><th>昨日梯队</th><th v-for="column in feedbackOrder" :key="column">{{ column }}</th></tr></thead>
            <tbody>
              <tr v-for="[tier, row] in feedbackRows" :key="tier">
                <td>{{ tier }}</td><td v-for="column in feedbackOrder" :key="`${tier}-${column}`">{{ matrixCell(row, column) }}</td>
              </tr>
              <tr v-if="!feedbackRows.length"><td :colspan="Math.max(feedbackOrder.length + 1, 2)">CANNOT_CONFIRM · 反馈矩阵未物化。</td></tr>
            </tbody>
          </table>
        </div>
        <div class="daily-research-review-table-wrap" v-if="feedbackDetails.length">
          <table>
            <thead><tr><th>代码</th><th>名称</th><th>昨日梯队</th><th>结果</th><th>涨跌</th><th>行业</th><th>板位</th><th>完整字段</th></tr></thead>
            <tbody><tr v-for="(row, index) in feedbackDetails" :key="`${value(row.code)}-${value(row.name)}-${index}`"><td>{{ value(row.code) }}</td><td>{{ value(row.name) }}</td><td>{{ value(row.prev_tier) }}</td><td>{{ value(row.result) }}</td><td>{{ value(row.ret) }}</td><td>{{ value(row.sector) }}</td><td>{{ value(row.board) }}</td><td><details><summary>展开</summary><pre>{{ json(row) }}</pre></details></td></tr></tbody>
          </table>
        </div>
        <p v-else class="daily-research-review-empty">CANNOT_CONFIRM · 反馈明细未物化。</p>
        <details class="daily-research-review-full-view">
          <summary>查看反馈矩阵完整 JSON（矩阵、明细与备注）</summary>
          <pre>{{ json(currentReview?.feedback_matrix) }}</pre>
        </details>
      </section>

      <section class="daily-research-review-section" data-testid="daily-research-money-loss-effect">
        <div class="daily-research-review-section-heading"><h3>赚钱效应 / 亏钱效应</h3><span>{{ value(field(currentReview?.money_effect, "prev_date")) }}</span></div>
        <div class="daily-research-review-card-grid">
          <article><span>赚钱效应均值</span><strong>{{ value(field(currentReview?.money_effect, "avg")) }}</strong><small>中位数 {{ value(field(currentReview?.money_effect, "median")) }}</small></article>
          <article><span>赚钱效应正收益率</span><strong>{{ value(field(currentReview?.money_effect, "positive_rate")) }}</strong><small>样本 {{ value(field(currentReview?.money_effect, "sample")) }}</small></article>
          <article><span>跌超5%数量</span><strong>{{ value(field(currentReview?.loss_effect, "deep_loss_5_count")) }}</strong><small>比例 {{ value(field(currentReview?.loss_effect, "deep_loss_5_rate")) }}</small></article>
          <article><span>跌超7%数量</span><strong>{{ value(field(currentReview?.loss_effect, "deep_loss_7_count")) }}</strong><small>最差 {{ value(field(currentReview?.loss_effect, "worst")) }}</small></article>
          <article><span>跌停数量</span><strong>{{ value(field(currentReview?.loss_effect, "limit_down_count")) }}</strong><small>市场口径 {{ value(field(currentReview?.loss_effect, "market_limit_down")) }}</small></article>
          <article><span>覆盖率</span><strong>{{ value(field(currentReview?.loss_effect, "coverage_rate")) }}</strong><small>{{ value(field(currentReview?.loss_effect, "note")) }}</small></article>
        </div>
        <details class="daily-research-review-full-view">
          <summary>查看赚钱效应与亏钱效应完整 JSON</summary>
          <pre>{{ json({ money_effect: currentReview?.money_effect, loss_effect: currentReview?.loss_effect }) }}</pre>
        </details>
      </section>

      <section class="daily-research-review-section" data-testid="daily-research-promotion-ladder">
        <div class="daily-research-review-section-heading"><h3>晋级梯队</h3><span>最高 {{ value(field(currentReview?.ladder_gap, "highest")) }} 板</span></div>
        <div class="daily-research-review-card-grid">
          <article><span>整体晋级</span><strong>{{ value(record(record(currentReview?.promotion).overall).promoted) }} / {{ value(record(record(currentReview?.promotion).overall).base) }}</strong><small>晋级率 {{ value(record(record(currentReview?.promotion).overall).rate) }}</small></article>
          <article><span>梯队连续</span><strong>{{ value(field(currentReview?.ladder_gap, "continuous")) }}</strong><small>缺口 {{ value(field(currentReview?.ladder_gap, "gaps")) }}</small></article>
          <article><span>涨停总数</span><strong>{{ value(field(currentReview?.promotion, "limit_up_count")) }}</strong><small>昨日 {{ value(field(currentReview?.promotion, "prev_limit_up_count")) }}</small></article>
        </div>
        <div class="daily-research-review-table-wrap">
          <table>
            <thead><tr><th>梯队</th><th>基数</th><th>晋级</th><th>晋级率</th></tr></thead>
            <tbody><tr v-for="[tier, row] in promotionTiers" :key="tier"><td>{{ tier }}</td><td>{{ value(record(row).base) }}</td><td>{{ value(record(row).promoted) }}</td><td>{{ value(record(row).rate) }}</td></tr><tr v-if="!promotionTiers.length"><td colspan="4">CANNOT_CONFIRM · 晋级梯队未物化。</td></tr></tbody>
          </table>
        </div>
        <details class="daily-research-review-full-view">
          <summary>查看晋级梯队与缺口完整 JSON</summary>
          <pre>{{ json({ promotion: currentReview?.promotion, ladder_gap: currentReview?.ladder_gap }) }}</pre>
        </details>
      </section>

      <section class="daily-research-review-section" data-testid="daily-research-theme-event-tree">
        <div class="daily-research-review-section-heading"><h3>题材事件树</h3><span>覆盖 {{ value(field(currentReview?.theme_tree, "coverage_rate")) }} · 题材 {{ themeRows.length }} 条 · 事件 {{ value(field(currentReview?.event_ledger, "count")) }} 条</span></div>
        <div class="daily-research-review-table-wrap">
          <table>
            <thead><tr><th>题材</th><th>涨停</th><th>首板</th><th>连板</th><th>最高</th><th>炸板</th><th>状态</th><th>成员</th><th>完整字段</th></tr></thead>
            <tbody><tr v-for="(row, index) in themeRows" :key="`${value(row.tag)}-${index}`"><td>{{ value(row.tag) }}</td><td>{{ value(row.limit_up) }}</td><td>{{ value(row.first_boards) }}</td><td>{{ value(row.consec_boards) }}</td><td>{{ value(row.highest) }}</td><td>{{ value(row.broken) }}</td><td>{{ value(row.state) }}</td><td>
              <details v-if="records(row.members).length">
                <summary>{{ themeMembers(row) }} · 展开</summary>
                <ol class="daily-research-review-members"><li v-for="(member, memberIndex) in records(row.members)" :key="memberKey(member, memberIndex)"><span>{{ value(member.code) }} · {{ value(member.name) }} · {{ value(member.label) }}</span><details><summary>完整成员字段</summary><pre>{{ json(member) }}</pre></details></li></ol>
              </details>
              <template v-else>未确认</template>
            </td><td><details><summary>展开</summary><pre>{{ json(row) }}</pre></details></td></tr><tr v-if="!themeRows.length"><td colspan="9">CANNOT_CONFIRM · 题材树未物化。</td></tr></tbody>
          </table>
        </div>
        <div class="daily-research-review-table-wrap">
          <table>
            <thead><tr><th>代码</th><th>名称</th><th>题材</th><th>板位</th><th>板数</th><th>涨跌</th><th>首次封板</th><th>最后封板</th><th>炸板次数</th><th>换手</th><th>昨日板数</th><th>行业</th><th>事件说明</th><th>完整字段</th></tr></thead>
            <tbody><tr v-for="(row, index) in eventRows" :key="`${value(row.code)}-${value(row.tag)}-${index}`"><td>{{ value(row.code) }}</td><td>{{ value(row.name) }}</td><td>{{ value(row.tag) }}</td><td>{{ value(row.board) }}</td><td>{{ value(row.boards) }}</td><td>{{ value(row.ret) }}</td><td>{{ value(row.first_seal) }}</td><td>{{ value(row.last_seal) }}</td><td>{{ value(row.broken_times) }}</td><td>{{ value(row.turnover) }}</td><td>{{ value(row.prev_boards) }}</td><td>{{ value(row.sector) }}</td><td>{{ value(row.note) }}</td><td><details><summary>展开</summary><pre>{{ json(row) }}</pre></details></td></tr><tr v-if="!eventRows.length"><td colspan="14">CANNOT_CONFIRM · 事件台账未物化。</td></tr></tbody>
          </table>
        </div>
        <div class="daily-research-review-category-grid" data-testid="daily-research-event-categories">
          <details v-for="category in eventCategories" :key="category.key" class="daily-research-review-category">
            <summary>{{ category.label }} · {{ category.rows.length }} 条 · 展开完整列表</summary>
            <pre>{{ json(category.rows) }}</pre>
          </details>
        </div>
        <details class="daily-research-review-full-view">
          <summary>查看题材树与事件台账完整 JSON</summary>
          <pre>{{ json({ theme_tree: currentReview?.theme_tree, event_ledger: currentReview?.event_ledger }) }}</pre>
        </details>
      </section>

      <details class="daily-research-review-source">
        <summary>来源与生成边界</summary>
        <p>source_path={{ currentReview?.source_path || "CANNOT_CONFIRM" }}</p>
        <p>generation_status={{ currentReview?.generation_status || "CANNOT_CONFIRM" }} · owner={{ currentReview?.generation?.owner || "CANNOT_CONFIRM" }}</p>
        <p>仅展示外部 dated JSON 的事实字段；本页不生成新复盘、不修改共享数据、不更新 BUY gate。</p>
      </details>
    </template>
  </section>
</template>

<style scoped>
.daily-research-review-panel { margin-top: 18px; border: 1px solid #c8d3dd; background: #fff; border-radius: 8px; overflow: hidden; }
.daily-research-review-panel > .section-heading { margin: 0; }
.daily-research-review-missing, .daily-research-review-warning { display: flex; flex-wrap: wrap; gap: 7px; margin: 15px 18px; padding: 12px; color: #765615; background: #fff8dc; border: 1px solid #ead18a; border-radius: 5px; font-size: 11px; }
.daily-research-review-missing strong, .daily-research-review-warning strong { width: 100%; color: #644b14; font-size: 13px; }
.daily-research-review-missing span, .daily-research-review-warning span { padding: 3px 7px; background: #fff; border: 1px solid #e4d4a2; border-radius: 999px; }
.daily-research-review-missing small, .daily-research-review-warning small { width: 100%; line-height: 1.5; }
.daily-research-review-meta { display: flex; flex-wrap: wrap; gap: 5px 14px; margin: 12px 18px; padding: 8px 10px; color: #647b8e; background: #f5f8fa; border: 1px solid #d7e0e8; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; overflow-wrap: anywhere; }
.daily-research-review-section { margin: 15px 18px; border: 1px solid #d2dce5; border-radius: 7px; overflow: hidden; }
.daily-research-review-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 11px 13px; background: #f4f7fa; border-bottom: 1px solid #d2dce5; }
.daily-research-review-section-heading h3 { margin: 0; color: #2c4b65; font-size: 14px; }
.daily-research-review-section-heading span { color: #718499; font-size: 10px; }
.daily-research-review-metrics, .daily-research-review-card-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; padding: 12px; }
.daily-research-review-card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.daily-research-review-metrics article, .daily-research-review-card-grid article { min-width: 0; padding: 9px; background: #f8fafc; border: 1px solid #e0e7ed; border-radius: 5px; }
.daily-research-review-metrics span, .daily-research-review-card-grid span, .daily-research-review-card-grid small { display: block; color: #718499; font-size: 10px; }
.daily-research-review-metrics strong, .daily-research-review-card-grid strong { display: block; margin-top: 5px; overflow-wrap: anywhere; color: #215477; font-size: 17px; line-height: 1.35; }
.daily-research-review-card-grid small { margin-top: 4px; line-height: 1.4; overflow-wrap: anywhere; }
.daily-research-review-kv { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0 12px 12px; }
.daily-research-review-kv div { min-width: 0; padding: 7px 9px; background: #fff; border: 1px solid #e0e7ed; border-radius: 4px; }
.daily-research-review-kv dt { color: #7b8b99; font-size: 10px; }
.daily-research-review-kv dd { margin: 4px 0 0; overflow-wrap: anywhere; color: #526a7f; font-size: 10px; }
.daily-research-review-kv-wide { grid-template-columns: repeat(3, minmax(0, 1fr)); padding-top: 12px; }
.daily-research-review-kv details, .daily-research-review-table-wrap details, .daily-research-review-category details { max-width: 100%; }
.daily-research-review-kv summary, .daily-research-review-table-wrap summary, .daily-research-review-category summary, .daily-research-review-full-view summary { cursor: pointer; color: #36546d; font-weight: 700; white-space: normal; }
.daily-research-review-kv pre, .daily-research-review-table-wrap pre, .daily-research-review-category pre, .daily-research-review-full-view pre { max-height: 360px; margin: 7px 0 0; padding: 8px; overflow: auto; color: #465d70; background: #f6f8fa; border: 1px solid #dbe3e9; font: 10px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; text-align: left; white-space: pre-wrap; overflow-wrap: anywhere; }
.daily-research-review-full-view { margin: 0 12px 12px; padding: 8px 10px; color: #526a7f; background: #f8fafc; border: 1px solid #d2dce5; font-size: 10px; }
.daily-research-review-members { min-width: 230px; margin: 6px 0 0; padding: 7px 7px 7px 25px; color: #526a7f; background: #f8fafc; border: 1px solid #dbe3e9; }
.daily-research-review-members li { padding: 4px 0; line-height: 1.4; }
.daily-research-review-members details { margin-top: 3px; }
.daily-research-review-category-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 12px; }
.daily-research-review-category { min-width: 0; padding: 9px; color: #526a7f; background: #f8fafc; border: 1px solid #dbe3e9; font-size: 10px; }
.daily-research-review-category pre { max-height: 300px; }
.daily-research-review-empty { margin: 10px 12px; color: #8a6b2c; font-size: 11px; }
.daily-research-review-table-wrap { overflow-x: auto; }
.daily-research-review-table-wrap table { width: 100%; min-width: 680px; border-collapse: collapse; font-size: 10px; }
.daily-research-review-table-wrap th, .daily-research-review-table-wrap td { padding: 8px 9px; text-align: left; border-bottom: 1px solid #e1e8ee; white-space: nowrap; }
.daily-research-review-table-wrap th { color: #425d75; background: #eef4f8; }
.daily-research-review-table-wrap td { color: #526a7f; }
.daily-research-review-source { margin: 15px 18px 18px; padding: 9px 11px; color: #526a7f; background: #f5f8fa; border: 1px solid #d2dce5; font-size: 10px; }
.daily-research-review-source summary { cursor: pointer; color: #36546d; font-weight: 700; }
.daily-research-review-source p { margin: 7px 0 0; overflow-wrap: anywhere; line-height: 1.5; }
@media (max-width: 900px) {
  .daily-research-review-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .daily-research-review-kv { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .daily-research-review-kv-wide, .daily-research-review-category-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .daily-research-review-kv-wide, .daily-research-review-category-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
