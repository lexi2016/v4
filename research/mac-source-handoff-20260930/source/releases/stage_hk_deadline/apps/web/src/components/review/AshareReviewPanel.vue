<script setup lang="ts">
import { computed } from "vue";
import type { AShareCloseBoard, AShareCloseModel, AShareCloseRole, AShareRichRow, AShareReview } from "../../contracts/review";

const props = defineProps<{ review: AShareReview }>();
const model = computed<AShareCloseModel>(() => props.review.model_review ?? {});
const modelReady = computed(() => model.value.status === "INDEPENDENT_CLOSE_REVIEW_READY");
const market = computed(() => model.value.market_summary ?? {});
const reviewSurface = computed(() => props.review.review_surface ?? {});
const partialStage = computed(() => reviewSurface.value.tier === "V3_RICH_PARTIAL");

const richReady = computed(() => (
  reviewSurface.value.tier === "V3_RICH_READY"
  || reviewSurface.value.tier === "V3_RICH_PARTIAL"
));
const richMainlines = computed<readonly AShareRichRow[]>(() => props.review.mainlines ?? []);
const richBoards = computed<readonly AShareRichRow[]>(() => props.review.board_rows ?? []);
const layeredRows = computed<readonly AShareRichRow[]>(() => richMainlines.value.length ? richMainlines.value : richBoards.value);
const richPlans = computed<readonly AShareRichRow[]>(() => props.review.prior_plan_rows ?? []);
const richAnchors = computed<readonly AShareRichRow[]>(() => (
  partialStage.value
    ? (props.review.stage_validation_rows ?? [])
    : (props.review.anchor_role_v3_rows ?? [])
));
const richHandoffs = computed<readonly AShareRichRow[]>(() => props.review.intraday_handoff_rows ?? []);
const richTriggers = computed<readonly AShareRichRow[]>(() => {
  if (props.review.trigger_rows?.length) return props.review.trigger_rows;
  return props.review.next_day_trigger_tree ?? [];
});
const richCatalysts = computed<readonly AShareRichRow[]>(() => props.review.catalyst_rows ?? []);
const richSources = computed<readonly AShareRichRow[]>(() => props.review.source_status_rows ?? []);
const richVideoGaps = computed<readonly AShareRichRow[]>(() => props.review.video_gap_rows ?? []);
type FailureRow = Readonly<Record<string, unknown>>;
type ReviewWithFailure = AShareReview & {
  first_failed_layer?: FailureRow;
  failure_chain?: readonly FailureRow[];
  failure_summary?: string;
};
const failureReview = computed(() => props.review as ReviewWithFailure);
const firstFailure = computed(() => failureReview.value.first_failed_layer);
const failureChain = computed<readonly FailureRow[]>(() => failureReview.value.failure_chain ?? []);

function failureValue(row: FailureRow, key: string): string {
  const value = row[key];
  return value === undefined || value === null || value === "" ? "未确认" : String(value);
}

function failureSummary(): string {
  return failureReview.value.failure_summary || "首断点与下游失败链未确认";
}
const shadowRows = computed(() => {
  const pool = model.value.shadow_watch_pool ?? {};
  return [
    ...(pool.core ?? []).map((row) => ({ ...row, bucket: "核心" })),
    ...(pool.conditional ?? []).map((row) => ({ ...row, bucket: "条件观察" })),
    ...(pool.observation_or_risk ?? []).map((row) => ({ ...row, bucket: "风险观察" })),
  ];
});

const LABELS: Record<string, string> = {
  MAINLINE: "主线候选", mainline: "主线", CONFIRMED_MAINLINE: "确认主线",
  PROVISIONAL_MAINLINE: "待验证主线", strong_branch: "强分支", STRONG_BRANCH: "强分支",
  ROTATION_BRANCH: "轮动分支", rotation: "轮动支线", ROTATION_ONLY: "轮动支线", RETURN_FLOW: "回流方向",
  ARBITRAGE: "套利观察", DEFENSIVE_BRANCH: "防守分支", FAILED_OLD_DIRECTION: "失败旧方向",
  RISK_MAINLINE: "风险主线", risk_line: "风险线", leader: "龙头候选",
  capacity_anchor: "容量锚", trend_anchor: "趋势锚", risk_anchor: "风险锚",
  sentiment_anchor: "情绪锚", rear_row: "后排观察", failed_anchor: "失败锚",
  tomorrow_decider: "明日决策票", WATCH_ONLY: "观察分支", SHADOW_ONLY: "影子观察",
  NO_BUY: "不形成买入建议", DATA_BLOCKED: "数据受限", READY: "已就绪", success: "成功",
  PUBLIC_DXX_CATALYST: "公开催化线索", METADATA_ONLY_NO_USABLE_ROWS: "仅元数据，无可用正文",
};

function label(value?: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) return "未确认";
  if (LABELS[text]) return LABELS[text];
  const enumPrefix = text.match(/^(MAINLINE|ROTATION_BRANCH|STRONG_BRANCH|WATCH_ONLY)(?:_|\s|:|$)/)?.[1];
  if (enumPrefix) return LABELS[enumPrefix];
  if (text.startsWith("CANNOT_CONFIRM")) return `未确认：${text.replace(/^CANNOT_CONFIRM[_:]?/, "").replaceAll("_", " ") || "证据不足"}`;
  if (text.startsWith("NOT_MATERIALIZED")) return "尚未物化";
  return text;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => formatValue(item)).filter(Boolean).join("、");
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).map((item) => formatValue(item)).filter(Boolean).join("；");
  if (typeof value === "string") {
    const text = value.trim();
    if (LABELS[text]) return LABELS[text];
    const enumPrefix = text.match(/^(MAINLINE|ROTATION_BRANCH|STRONG_BRANCH|WATCH_ONLY)(?:_|\s|:|$)/)?.[1];
    if (enumPrefix) return LABELS[enumPrefix];
  }
  return value === undefined || value === null || value === "" ? "未确认" : String(value);
}

function richValue(row: AShareRichRow, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && value !== "") return formatValue(value);
  }
  return "未确认";
}

function percent(value?: number) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "未确认";
}

function pct(value?: number) {
  return typeof value === "number" ? `${value.toFixed(2)}%` : "未确认";
}

function boardName(row: AShareCloseBoard | AShareRichRow) {
  return row.canonical_theme ?? row.board_name ?? row.section ?? row.board ?? "未确认方向";
}

function stockName(row: AShareCloseRole | AShareRichRow) {
  return [row.stock_name ?? row.name ?? row.stock, row.stock_code ?? row.code ?? row.symbol].filter(Boolean).join(" ") || "未确认个股";
}

function videoStatus(): string {
  const video = props.review.video ?? {};
  const targetTradeDate = String(video.target_trade_date ?? "");
  const videoTradeDate = String(video.trade_date ?? "");
  const status = String(video.status ?? video.gap_status ?? "");
  if (!targetTradeDate || !videoTradeDate || targetTradeDate !== props.review.trade_date || videoTradeDate !== props.review.trade_date) return "当天视频未锁定";
  if (!status || status.includes("NOT_LOCKED") || status.includes("CANNOT_CONFIRM") || status.includes("NOT_MATERIALIZED")) return "当天视频未锁定";
  return `当天视频：${label(status)}`;
}
</script>

<template>
  <section class="review-a-panel" aria-label="A-share review" data-testid="a-review-rich-surface" :data-surface-tier="reviewSurface.tier" :data-surface-status="reviewSurface.status" :data-surface-trade-date="reviewSurface.trade_date || review.trade_date">
    <div class="section-heading">
      <div><span class="eyebrow">A_SHARE_REVIEW</span><h2>A股复盘</h2></div>
      <p><span>{{ review.headline || review.trade_date }}</span><small> · {{ partialStage ? "阶段证据富复盘 · CANNOT_CONFIRM" : (richReady ? "Review Core 富复盘" : (review.source_role || "未确认")) }}</small></p>
    </div>

    <template v-if="richReady">
      <section class="a-product-first" data-testid="a-product-first">
        <div class="red-frame-title"><span>{{ partialStage ? "V3 富复盘骨架·部分证据" : "正式复盘" }}</span><h2>【{{ partialStage ? "V3 富复盘骨架·部分证据" : "红框正式复盘" }}】{{ review.trade_date }} 看什么</h2></div>
        <p class="product-headline">{{ review.headline || "今日市场结论未确认" }}</p>
        <div class="product-metrics">
          <article><span>市场阶段</span><strong>{{ label(review.market_regime) }}</strong></article>
          <article><span>主线方向</span><strong>{{ layeredRows.filter((row) => !String(richValue(row, "today_role", "role")).includes("风险")).map((row) => boardName(row)).join("、") || "未确认" }}</strong></article>
          <article><span>风险方向</span><strong>{{ label(review.risk_tone) }}</strong></article>
          <article><span>{{ partialStage ? "阶段验证锚" : "明日先看" }}</span><strong>{{ richAnchors.slice(0, 5).map((row) => stockName(row)).join("、") || "未确认" }}</strong></article>
        </div>
        <div class="product-boundary">
          <p><strong>视频状态：</strong>{{ videoStatus() }}</p>
          <p><strong>数据边界：</strong>日线/分钟/开盘代理，未验证盘口队列与封单稳定性；本页为研究复盘，不形成买卖建议。</p>
        </div>
      </section>

      <section v-if="firstFailure" class="review-failure-surface" data-testid="a-first-failure">
        <h3>首断点与下游失败链</h3>
        <p class="review-failure-summary">{{ failureSummary() }}</p>
        <div class="review-table-wrap"><table><thead><tr><th>层</th><th>责任方</th><th>状态</th><th>日期</th><th>失败类型</th><th>receipt/path</th></tr></thead>
          <tbody><tr v-for="(row, index) in failureChain" :key="failureValue(row, 'layer') + '-' + index" data-testid="review-failure-row"><td>{{ failureValue(row, "layer") }}</td><td>{{ failureValue(row, "owner") }}</td><td>{{ failureValue(row, "status") }}</td><td>期望 {{ failureValue(row, "expected_date") }} / 观测 {{ failureValue(row, "observed_date") }}</td><td>{{ failureValue(row, "failure_class") }}</td><td>{{ failureValue(row, "receipt_path") }}<span v-if="row.path"> · {{ failureValue(row, "path") }}</span></td></tr><tr v-if="!failureChain.length"><td colspan="6">CANNOT_CONFIRM · 首断点链未物化。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-prior-plan">
        <h3>【红框一、昨日预案兑现回顾】</h3>
        <div class="review-table-wrap"><table><thead><tr><th>昨日方向</th><th>计划锚点</th><th>开盘兑现</th><th>收盘结果</th><th>明日回写</th></tr></thead>
          <tbody><tr v-for="row in richPlans" :key="String(row.id ?? row.mapped_theme ?? row.planned_anchor)" data-testid="rich-plan-row"><td>{{ richValue(row, "mapped_theme", "theme", "direction") }}</td><td>{{ richValue(row, "planned_anchor", "anchor") }}</td><td>{{ richValue(row, "open_realization") }}</td><td>{{ richValue(row, "close_result") }}</td><td>{{ richValue(row, "tomorrow_scenario", "cannot_confirm") }}</td></tr><tr v-if="!richPlans.length"><td colspan="5">CANNOT_CONFIRM · 昨日正式预案未物化，不用今日强势方向倒推。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-board-coverage">
        <h3>【红框二、全板块覆盖表】</h3>
        <div class="review-table-wrap"><table><thead><tr><th>板块/方向</th><th>今日角色</th><th>本地量价证据</th><th>核心/锚点</th><th>明日触发</th><th>降级/失效</th></tr></thead>
          <tbody><tr v-for="row in richBoards" :key="String(row.id ?? boardName(row))" data-testid="rich-board-row"><td>{{ boardName(row) }}</td><td>{{ label(row.today_role ?? row.role) }}</td><td>{{ richValue(row, "local_evidence", "evidence") }}</td><td>{{ richValue(row, "anchors", "core_or_leader", "capacity_or_risk_anchor") }}</td><td>{{ richValue(row, "next_trigger", "trigger") }}</td><td>{{ richValue(row, "cannot_confirm", "counterevidence") }}</td></tr><tr v-if="!richBoards.length"><td colspan="6">CANNOT_CONFIRM · 全板块正式覆盖表未物化。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-mainlines">
        <h3>【红框三、主线/支线/失败方向分层】</h3>
        <div class="review-table-wrap"><table><thead><tr><th>方向</th><th>分层</th><th>前排/容量</th><th>风险/失败锚</th><th>证据边界</th></tr></thead>
          <tbody><tr v-for="row in layeredRows" :key="`layer-${String(row.id ?? boardName(row))}`" data-testid="rich-mainline-row"><td>{{ boardName(row) }}</td><td>{{ label(row.today_role ?? row.role) }}</td><td>{{ richValue(row, "anchors", "core_or_leader") }}</td><td>{{ richValue(row, "risk_anchor", "failed_anchor", "counterevidence") }}</td><td>{{ richValue(row, "cannot_confirm") }}</td></tr><tr v-if="!layeredRows.length"><td colspan="5">CANNOT_CONFIRM · 正式主线/支线/失败方向尚未物化。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-anchors">
        <h3>【红框四、{{ partialStage ? "阶段验证锚（WATCH_ONLY）" : "核心票/容量锚/后排/风险锚" }}】</h3>
        <p v-if="partialStage" class="review-pending">阶段候选只用于 WATCH_ONLY 验证锚；不升级为正式核心票、容量锚或买入建议。</p>
        <div class="review-table-wrap"><table><thead><tr><th>股票</th><th>所属方向</th><th>角色</th><th>角色依据</th><th>明日强弱</th><th>失效条件</th></tr></thead>
          <tbody><tr v-for="row in richAnchors" :key="String(row.id ?? row.stock ?? row.stock_name ?? row.stock_code)" data-testid="rich-anchor-row"><td>{{ stockName(row) }}</td><td>{{ richValue(row, "theme", "board_name", "board") }}</td><td>{{ label(row.role_type ?? row.primary_role ?? row.role) }}</td><td>{{ richValue(row, "why_this_role", "confirmed_by", "evidence") }}</td><td>{{ richValue(row, "tomorrow_if_strong", "next_day_trigger") }}</td><td>{{ richValue(row, "tomorrow_if_weak", "invalidation", "cannot_confirm") }}</td></tr><tr v-if="!richAnchors.length"><td colspan="6">CANNOT_CONFIRM · 正式核心票角色尚未建立；不把影子观察池升级为正式核心。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-handoff">
        <h3>【红框五、盘中交接】</h3>
        <div class="review-table-wrap"><table><thead><tr><th>方向</th><th>早盘锚</th><th>早盘状态</th><th>午后接棒</th><th>收盘角色</th><th>不能确认</th></tr></thead>
          <tbody><tr v-for="row in richHandoffs" :key="String(row.id ?? row.theme ?? row.direction)"><td>{{ richValue(row, "theme", "direction") }}</td><td>{{ richValue(row, "morning_anchor") }}</td><td>{{ richValue(row, "morning_status") }}</td><td>{{ richValue(row, "afternoon_handoff") }}</td><td>{{ richValue(row, "close_role") }}</td><td>{{ richValue(row, "cannot_confirm") }}</td></tr><tr v-if="!richHandoffs.length"><td colspan="6">CANNOT_CONFIRM · 盘中交接未物化；只保留日线/分钟代理边界。</td></tr></tbody>
        </table></div>
      </section>

      <section class="review-row-section product-section" data-testid="a-rich-section-triggers">
        <h3>【红框六、明日触发器/失效条件】</h3>
        <div class="review-table-wrap"><table><thead><tr><th>方向</th><th>升级条件</th><th>符合预期</th><th>失效条件</th><th>操作标签</th></tr></thead>
          <tbody><tr v-for="row in richTriggers" :key="String(row.id ?? row.direction ?? row.condition)" data-testid="rich-trigger-row"><td>{{ richValue(row, "direction", "condition", "theme") }}</td><td>{{ richValue(row, "upgrade", "upgrade_condition", "need") }}</td><td>{{ richValue(row, "in_line", "normal_behavior", "action") }}</td><td>{{ richValue(row, "invalidation", "invalidation_condition", "reject_if") }}</td><td>仅观察 / 次日验证</td></tr><tr v-if="!richTriggers.length"><td colspan="5">CANNOT_CONFIRM · 次日触发树未物化。</td></tr></tbody>
        </table></div>
      </section>

      <details class="audit-appendix" data-testid="a-audit-appendix">
        <summary>审计与证据附录（视频、催化、SHA、收盘自动链）</summary>
        <section class="review-row-section"><h3>视频差距和改进</h3><p>{{ videoStatus() }}；未跨日期补视频。</p><div class="review-table-wrap"><table><thead><tr><th>项目</th><th>旧版问题</th><th>本次状态</th><th>仍缺</th></tr></thead><tbody><tr v-for="row in richVideoGaps" :key="String(row.id ?? row.row_id)"><td>{{ richValue(row, "gap_type", "项目", "title") }}</td><td>{{ richValue(row, "old_problem", "旧版问题") }}</td><td>{{ richValue(row, "status", "result") }}</td><td>{{ richValue(row, "cannot_confirm", "仍缺") }}</td></tr><tr v-if="!richVideoGaps.length"><td colspan="4">当天视频未锁定；视频差距不写成其他日期的证据。</td></tr></tbody></table></div></section>
        <section class="review-row-section"><h3>研报/资讯催化矩阵</h3><div class="review-table-wrap"><table><thead><tr><th>方向</th><th>催化</th><th>质量</th><th>边界</th></tr></thead><tbody><tr v-for="row in richCatalysts" :key="String(row.id ?? row.direction)"><td>{{ richValue(row, "direction", "theme") }}</td><td>{{ richValue(row, "catalyst", "reason") }}</td><td>{{ label(row.quality) }}</td><td>{{ richValue(row, "boundary", "cannot_confirm") }}</td></tr><tr v-if="!richCatalysts.length"><td colspan="4">催化矩阵未命中；研报只作背景，不替代量价证据。</td></tr></tbody></table></div></section>
        <section class="review-row-section"><h3>数据源与 SHA</h3><p v-for="row in richSources" :key="String(row.id ?? row.source)">{{ richValue(row, "source", "name") }}：{{ label(row.status) }} · {{ richValue(row, "reason", "cannot_confirm") }}</p><p>Review Core run：{{ review.source_run_id || "未确认" }} · bundle SHA：{{ review.review_core_bundle?.bundle_sha256 || review.artifact_sha256 || review.source_sha256 || "未确认" }} · manifest SHA：{{ review.review_core_bundle?.manifest_sha256 || "未确认" }} · receipt SHA：{{ review.review_core_bundle?.receipt_sha256 || "未确认" }}</p><p>production_allowed=false · buy_gate_updated=false · orders_sent=false</p></section>
        <section v-if="review.close_chain" class="review-row-section"><h3>收盘自动链 · V3 图谱顺序</h3><p>{{ label(review.close_chain.status) }} · 缺失节点 {{ review.close_chain.cannot_confirm?.length ?? 0 }}</p><div class="review-table-wrap"><table><thead><tr><th>时点</th><th>节点</th><th>业务</th><th>状态</th><th>证据/原因</th></tr></thead><tbody><tr v-for="row in review.close_chain.nodes ?? []" :key="String(row.task_id)" data-testid="close-chain-row"><td>{{ row.slot }}</td><td>{{ row.task_id }}</td><td>{{ row.label }}</td><td>{{ label(row.status) }}</td><td>{{ row.reason }}</td></tr></tbody></table></div></section>
      </details>
    </template>

    <template v-else>
      <p v-if="!modelReady" class="review-pending" data-testid="a-model-not-materialized">A股完整复盘研究模型尚未物化：{{ label(model.status || "NOT_MATERIALIZED") }}</p>
      <section v-if="review.close_chain" class="review-row-section"><h3>收盘自动链 · V3 图谱顺序</h3><p>{{ label(review.close_chain.status) }} · 缺失节点 {{ review.close_chain.cannot_confirm?.length ?? 0 }}</p><div class="review-table-wrap"><table><thead><tr><th>时点</th><th>节点</th><th>业务</th><th>状态</th><th>证据/原因</th></tr></thead><tbody><tr v-for="row in review.close_chain.nodes ?? []" :key="String(row.task_id)" data-testid="close-chain-row"><td>{{ row.slot }}</td><td>{{ row.task_id }}</td><td>{{ row.label }}</td><td>{{ label(row.status) }}</td><td>{{ row.reason }}</td></tr></tbody></table></div></section>
      <details v-if="modelReady" class="review-model-shell" open data-testid="a-close-model">
        <summary>完整复盘研究模型 · {{ label(model.status) }}</summary>
        <div class="review-metric-grid"><article><span>研究模型</span><strong>{{ model.producer_type }}</strong><small>{{ model.schema_version }}</small></article><article><span>学习假设</span><strong>{{ model.learning_status }}</strong><small>{{ model.model_promotion }}</small></article><article><span>正式泛化</span><strong>{{ model.formal_generalization }}</strong><small>不冒充已推广模型</small></article><article><span>证据截止</span><strong>{{ model.as_of }}</strong><small>{{ model.visibility_stage }}</small></article></div>
        <section class="review-row-section"><h3>本地复盘引擎 · 状态</h3><p>{{ model.semantic_model_status }} · 语义模型调用 {{ model.semantic_model_call_count ?? 0 }} 次 · SHADOW_ONLY={{ model.safety?.SHADOW_ONLY }}</p></section>
        <section class="review-row-section"><h3>本地复盘引擎 · 独立结论</h3><p>{{ market.regime }} · 上涨 {{ market.up_count ?? "-" }} / 下跌 {{ market.down_count ?? "-" }} / 平盘 {{ market.flat_count ?? "-" }} · 市场宽度 {{ percent(market.market_width) }}</p><p>{{ market.boundary }}</p></section>
        <section class="review-row-section"><h3>本地复盘引擎 · 板块判断</h3><div class="review-table-wrap"><table><thead><tr><th>板块</th><th>角色</th><th>中位涨幅</th><th>上涨占比</th><th>反证/降级条件</th><th>次日升级条件</th></tr></thead><tbody><tr v-for="row in model.board_rows ?? []" :key="String(boardName(row))" data-testid="model-board-row"><td>{{ boardName(row) }}</td><td>{{ label(row.board_role) }}</td><td>{{ pct(row.median_pct_change) }}</td><td>{{ percent(row.up_ratio) }}</td><td>{{ row.counterevidence }}</td><td>{{ row.trigger }}</td></tr></tbody></table></div></section>
        <section class="review-row-section"><h3>本地复盘引擎 · 个股角色判断</h3><div class="review-table-wrap"><table><thead><tr><th>股票</th><th>板块</th><th>角色</th><th>收盘涨幅</th><th>独立判断</th><th>失效条件</th></tr></thead><tbody><tr v-for="row in model.anchor_role_rows ?? []" :key="String(row.stock_code ?? row.code)" data-testid="model-role-row"><td>{{ stockName(row) }}</td><td>{{ row.board_name }}</td><td>{{ label(row.primary_role) }}</td><td>{{ pct(row.pct_change) }}</td><td>{{ row.role_explanation }}</td><td>{{ row.invalidation }}</td></tr></tbody></table></div></section>
        <section class="review-row-section"><h3>视频差距审计</h3><p>{{ label(model.target_video_review_status) }}</p></section><section class="review-row-section"><h3>产品层 · 市场总览</h3><p>涨停 {{ market.limit_up_count ?? "-" }} · 跌停 {{ market.limit_down_count ?? "-" }} · 成交额 {{ market.amount_yi ?? "-" }} 亿 · 外围 {{ market.external_environment }}</p></section><section class="review-row-section"><h3>产品层 · 前计划兑现</h3><p>{{ model.previous_plan_realization }}</p></section>
        <section class="review-row-section"><h3>{{ model.shadow_watch_pool?.abstain ? "产品层 · 影子观察池（弱市弃权）" : "产品层 · 影子观察池" }}</h3><p>边界 {{ label(model.shadow_watch_pool?.boundary) }} · 弃权原因 {{ model.shadow_watch_pool?.abstain_reason }}</p><div class="review-table-wrap"><table><thead><tr><th>分层</th><th>股票</th><th>角色</th><th>状态</th></tr></thead><tbody><tr v-for="row in shadowRows" :key="`${row.bucket}:${row.stock_code ?? row.code}`" data-testid="shadow-watch-row"><td>{{ row.bucket }}</td><td>{{ stockName(row) }}</td><td>{{ label(row.primary_role) }}</td><td>{{ label(row.recommendation_status) }}</td></tr><tr v-if="!shadowRows.length"><td colspan="4">弱市弃权；不建立正式核心票。</td></tr></tbody></table></div></section>
      </details>
    </template>
    <section v-if="!richReady" class="review-row-section"><h3>正式核心票</h3><p v-if="!review.core_stocks.length" class="review-pending">正式核心票未建立</p><p v-for="row in review.core_stocks" :key="String(row.id ?? row.code)">{{ row.name ?? row.code }}</p></section>
  </section>
</template>

<style scoped>
.a-product-first { border: 2px solid #b42318; background: #fffafa; padding: 16px; margin: 14px 0; }
.red-frame-title { display: flex; gap: 10px; align-items: baseline; color: #b42318; }
.red-frame-title span { font-size: 12px; font-weight: 800; letter-spacing: .08em; }
.red-frame-title h2 { margin: 0; font-size: 20px; }
.product-headline { font-size: 16px; font-weight: 700; line-height: 1.6; }
.product-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.product-metrics article { border: 1px solid #e5b7b3; background: #fff; padding: 10px; }
.product-metrics span, .product-metrics strong { display: block; }
.product-metrics span { color: #667085; font-size: 12px; }
.product-metrics strong { margin-top: 4px; color: #111827; line-height: 1.45; }
.product-boundary { margin-top: 12px; color: #475467; font-size: 13px; line-height: 1.5; }
.product-boundary p { margin: 4px 0; }
.product-section h3 { color: #344054; }
.audit-appendix { margin-top: 18px; border: 1px solid #d0d5dd; background: #f8fafc; padding: 10px; }
.audit-appendix summary { cursor: pointer; font-weight: 700; color: #475467; }
.review-table-wrap { overflow-x: auto; }
.review-table-wrap table { min-width: 760px; }
</style>
