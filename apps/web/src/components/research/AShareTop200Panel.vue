<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type StageEntry = {
  status?: string;
  row_count?: number | null;
  unique_codes?: number | null;
  hit_count?: number | null;
  artifact_relative?: string;
  artifact_sha256?: string;
  run_id?: string;
};

type StageCoverage = {
  available?: number | null;
  total?: number | null;
  missing_stages?: string[];
};

type SevenStage = {
  status?: string;
  selected_count?: number | null;
  hit_count?: number | null;
  top_count?: number | null;
  top200_coverage_pct?: number | null;
  selection_hit_rate_pct?: number | null;
  stages?: Record<string, StageEntry>;
};

type PoolRow = {
  pool_id: string;
  display_name?: string;
  status?: string;
  signal_date?: string | null;
  target_date?: string | null;
  row_count?: number | null;
  materialized?: boolean;
  partial?: boolean;
  selected_count?: number | null;
  hit_count?: number | null;
  top200_coverage_pct?: number | null;
  selection_hit_rate_pct?: number | null;
  source_sha256?: string;
};

type APool = {
  status?: string;
  reason?: string | null;
  materialized?: boolean;
  evaluable?: boolean;
  selected_count?: number | null;
  hit_count?: number | null;
  top_count?: number | null;
  top200_coverage_pct?: number | null;
  selection_hit_rate_pct?: number | null;
  pool_count?: number | null;
  materialized_pool_count?: number | null;
  partial_pool_ids?: string[];
  missing_pool_ids?: string[];
  missing_mandatory_pool_ids?: string[];
  partial_mandatory_pool_ids?: string[];
  pools?: PoolRow[];
};

type Top200Definition = {
  top_count?: number | null;
  min_change_pct?: number | null;
  source?: string;
  source_sha256?: string;
  official_input_sha256?: string | null;
};

type Top200DateEntry = {
  date: string;
  status: string;
  reason?: string | null;
  stage_coverage?: StageCoverage;
  seven_stage?: SevenStage;
  a_pool?: APool;
  top200?: Top200Definition | null;
};

type Top200Payload = {
  schema_version?: string;
  generated_at?: string;
  latest_available_date?: string;
  available_dates?: string[];
  dates?: Top200DateEntry[];
  window_note?: string;
  safety_flags?: Record<string, boolean>;
};

const props = defineProps<{ date: string }>();
const emit = defineEmits<{ close: [] }>();

const STAGES: { id: string; label: string }[] = [
  { id: "STAGE_0925", label: "09:20/09:25 竞价" },
  { id: "STAGE_0930_0935", label: "09:30-09:35" },
  { id: "STAGE_0935_0940", label: "09:35-09:40" },
  { id: "STAGE_0940_0945", label: "09:40-09:45" },
  { id: "STAGE_0945_1030", label: "09:45-10:30" },
  { id: "STAGE_1300_1315", label: "13:00-13:15" },
  { id: "STAGE_1445_1500", label: "14:45-15:00" },
];

const POOL_SHORT_NAMES: Record<string, string> = {
  a_d1_premarket_pool: "主池",
  a_d1_fupan_watchlist_pool: "复盘",
  a_d1_stage7_fenshi_review_pool: "Stage7",
  a_share_research_recommendation_pool: "研报",
  a_share_baimao_research_map: "白毛",
  wechat_public_account_v3_preselect: "公众号",
};

const POOL_DISPLAY_NAMES: Record<string, string> = {
  a_d1_premarket_pool: "A股 D-1 主预选池",
  a_d1_fupan_watchlist_pool: "A股 D-1 复盘继续观察池",
  a_d1_stage7_fenshi_review_pool: "A股 D-1 Stage7/分时复盘池",
  a_share_research_recommendation_pool: "A股研报推荐股票池",
  a_share_baimao_research_map: "白毛卡点研究池",
  wechat_public_account_v3_preselect: "公众号股票池",
};

const A_POOL_ORDER = Object.keys(POOL_DISPLAY_NAMES);

const REASON_LABELS: Record<string, string> = {
  NO_OFFICIAL_DAILY_PACKAGE: "无官方日包",
  NO_A_SHARE_POOL_OR_STAGE_SELECTION: "无 A 股池/阶段选股",
  PARTIAL_POOL_OR_STAGE_COVERAGE: "池或阶段覆盖不完整",
  POOL_API_UNAVAILABLE: "池投影不可读",
  POOL_UNION_EMPTY: "池汇总为空",
  MISSING_OR_PARTIAL_MANDATORY_POOLS: "必备池缺失或部分物化",
};

const payload = ref<Top200Payload | null>(null);
const loading = ref(true);
const error = ref("");

const requestedDate = computed(() => props.date || "");
const dates = computed(() => payload.value?.dates ?? []);
const byDate = computed(() => new Map(dates.value.map((entry) => [entry.date, entry])));
const exactEntry = computed<Top200DateEntry | null>(() => byDate.value.get(requestedDate.value) ?? null);
const latestEntry = computed<Top200DateEntry | null>(() => {
  const latest = payload.value?.latest_available_date;
  if (latest && byDate.value.has(latest)) return byDate.value.get(latest) ?? null;
  return dates.value.at(-1) ?? null;
});
const selectedEntry = computed<Top200DateEntry | null>(() => exactEntry.value ?? latestEntry.value);
const usingFallback = computed(() => exactEntry.value === null && latestEntry.value !== null);
const selectedTopCount = computed<number | null>(() =>
  selectedEntry.value?.top200?.top_count ?? selectedEntry.value?.a_pool?.top_count ?? null,
);

const selectedStageRows = computed(() => {
  const stages = selectedEntry.value?.seven_stage?.stages ?? {};
  const ids = [...STAGES.map((stage) => stage.id), ...Object.keys(stages).filter((id) => !STAGES.some((stage) => stage.id === id))];
  return ids.map((id) => {
    const known = STAGES.find((stage) => stage.id === id);
    return {
      id,
      label: known?.label ?? id,
      entry: stages[id] ?? { status: "NOT_MATERIALIZED", hit_count: null },
    };
  });
});

const poolRows = computed<PoolRow[]>(() => {
  const ap = selectedEntry.value?.a_pool;
  if (!ap) return [];
  const union: PoolRow = {
    pool_id: "a_all_pool_summary",
    display_name: "A股所有预选池汇总",
    status: ap.status,
    materialized: ap.materialized,
    partial: ap.status === "PARTIAL_POOL_COVERAGE",
    selected_count: ap.selected_count,
    hit_count: ap.hit_count,
    top200_coverage_pct: ap.top200_coverage_pct,
    selection_hit_rate_pct: ap.selection_hit_rate_pct,
  };
  const apiPools = ap.pools ?? [];
  const pools = apiPools.length
    ? apiPools
    : (ap.pool_count ?? 0) > 0
      ? A_POOL_ORDER.map((pool_id) => ({
        pool_id,
        display_name: POOL_DISPLAY_NAMES[pool_id],
        status: ap.reason || "NOT_MATERIALIZED",
        materialized: false,
        partial: false,
        selected_count: null,
        hit_count: null,
        top200_coverage_pct: null,
        selection_hit_rate_pct: null,
      }))
      : [];
  return [union, ...pools];
});

const availableDatesText = computed(() => {
  const available = payload.value?.available_dates ?? [];
  return available.length ? available.map(formatDate).join("、") : "无";
});

function isSevenMaterialized(entry: Top200DateEntry | null): boolean {
  return entry?.seven_stage?.status === "READY" || entry?.seven_stage?.status === "PARTIAL_STAGE_COVERAGE";
}

function isAPoolMaterialized(entry: Top200DateEntry | null): boolean {
  return entry?.a_pool?.materialized === true;
}

function formatDate(value?: string | null): string {
  return value && /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : value || "—";
}

function numberText(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function percentText(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${Number(value.toFixed(2))}%` : "—";
}

function rawPercent(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value}%` : "—";
}

function aPoolHit(entry: Top200DateEntry | null): string {
  if (!isAPoolMaterialized(entry)) return "未物化";
  const hit = entry?.a_pool?.hit_count;
  if (typeof hit !== "number") return "未物化";
  const top = entry?.a_pool?.top_count ?? entry?.top200?.top_count;
  return `${hit}/${typeof top === "number" ? top : "缺证"}`;
}

function aPoolSelected(entry: Top200DateEntry | null): string {
  return isAPoolMaterialized(entry) ? numberText(entry?.a_pool?.selected_count) : "未物化";
}

function aPoolCoverage(entry: Top200DateEntry | null): string {
  if (!isAPoolMaterialized(entry)) return "未物化";
  return percentText(entry?.a_pool?.top200_coverage_pct);
}

function aPoolRate(entry: Top200DateEntry | null): string {
  if (!isAPoolMaterialized(entry)) return "未物化";
  return percentText(entry?.a_pool?.selection_hit_rate_pct);
}

function poolCoverageText(ap?: APool): string {
  const total = ap?.pool_count ?? 6;
  const materialized = ap?.materialized_pool_count;
  if (typeof materialized !== "number") return `未物化/${total} 路`;
  return `${materialized}/${total} 路`;
}

function poolGapText(ap?: APool): string {
  if (!ap) return "未物化";
  const missing = (ap.missing_pool_ids ?? []).map((id) => POOL_SHORT_NAMES[id] ?? id);
  const partial = (ap.partial_pool_ids ?? []).map((id) => POOL_SHORT_NAMES[id] ?? id);
  const parts: string[] = [];
  if (ap.reason && ap.reason !== "MISSING_OR_PARTIAL_MANDATORY_POOLS") {
    parts.push(reasonLabel(ap.reason));
  }
  if (missing.length) parts.push(`缺 ${missing.join("/")}`);
  if (partial.length) parts.push(`部分 ${partial.join("/")}`);
  return parts.length ? parts.join(" · ") : "无";
}

function sevenHit(entry: Top200DateEntry | null): string {
  if (!isSevenMaterialized(entry)) return "未物化";
  const seven = entry?.seven_stage;
  if (typeof seven?.hit_count !== "number") return "未物化";
  const top = seven.top_count ?? entry?.top200?.top_count;
  return `${seven.hit_count}/${typeof top === "number" ? top : "缺证"}`;
}

function sevenCount(entry: Top200DateEntry | null, value?: number | null): string {
  return isSevenMaterialized(entry) ? numberText(value) : "未物化";
}

function sevenPercent(entry: Top200DateEntry | null, value?: number | null): string {
  return isSevenMaterialized(entry) ? percentText(value) : "未物化";
}

function coverageText(coverage?: StageCoverage): string {
  const total = coverage?.total ?? 7;
  return typeof coverage?.available === "number" ? `${coverage.available}/${total}` : `未物化/${total}`;
}

function missingStagesText(coverage?: StageCoverage): string {
  const missing = coverage?.missing_stages ?? [];
  return missing.length ? missing.join("、") : "无";
}

function stageStatus(entry: StageEntry): string {
  return entry.status || "NOT_MATERIALIZED";
}

function stageCount(entry: StageEntry, key: "row_count" | "unique_codes" | "hit_count"): string {
  if (stageStatus(entry) !== "READY") return "未物化";
  return numberText(entry[key]);
}

function statusLabel(status?: string): string {
  if (status === "READY") return "已物化";
  if (status === "PARTIAL") return "部分物化";
  if (status === "NOT_MATERIALIZED") return "未物化";
  return status || "未物化";
}

function reasonLabel(reason?: string | null): string {
  return reason ? (REASON_LABELS[reason] ?? reason) : "";
}

function rowGapText(entry: Top200DateEntry): string {
  const parts: string[] = [];
  const add = (value: string) => {
    if (value && !parts.includes(value)) parts.push(value);
  };
  if (entry.reason && entry.reason !== "PARTIAL_POOL_OR_STAGE_COVERAGE") {
    add(reasonLabel(entry.reason));
  }
  if (entry.a_pool?.reason && entry.a_pool.reason !== "MISSING_OR_PARTIAL_MANDATORY_POOLS") {
    add(reasonLabel(entry.a_pool.reason));
  }
  if (entry.a_pool?.materialized) {
    const missing = (entry.a_pool.missing_mandatory_pool_ids ?? []).map((id) => POOL_SHORT_NAMES[id] ?? id);
    const partial = (entry.a_pool.partial_mandatory_pool_ids ?? []).map((id) => POOL_SHORT_NAMES[id] ?? id);
    if (missing.length) add(`缺 ${missing.join("/")}`);
    if (partial.length) add(`部分 ${partial.join("/")}`);
  }
  const available = entry.stage_coverage?.available;
  const total = entry.stage_coverage?.total ?? 7;
  if (typeof available === "number" && available < total) add(`阶段 ${available}/${total}`);
  return parts.join(" · ");
}

function poolStatusLabel(pool: PoolRow): string {
  if (!pool.materialized) return "未物化";
  return pool.partial ? "部分" : "已物化";
}

function poolStatusDetail(pool: PoolRow): string {
  if (!pool.materialized) return pool.status || "CANNOT_CONFIRM";
  return pool.status || (pool.partial ? "PARTIAL" : "READY");
}

function poolSelectedCell(pool: PoolRow): string {
  return pool.materialized ? numberText(pool.selected_count) : "未物化";
}

function poolHitCell(pool: PoolRow): string {
  if (!pool.materialized) return "未物化";
  if (typeof pool.hit_count !== "number") return "未物化";
  return `${pool.hit_count}/${selectedTopCount.value ?? "缺证"}`;
}

function poolCoverageCell(pool: PoolRow): string {
  return pool.materialized ? percentText(pool.top200_coverage_pct) : "—";
}

function poolRateCell(pool: PoolRow): string {
  return pool.materialized ? percentText(pool.selection_hit_rate_pct) : "—";
}

function poolSignalText(pool: PoolRow): string {
  return pool.signal_date ? `signal ${formatDate(pool.signal_date)}` : "";
}

function dateAPoolSelected(row: Top200DateEntry): string {
  return isAPoolMaterialized(row) ? numberText(row.a_pool?.selected_count) : "—";
}

function dateAPoolHit(row: Top200DateEntry): string {
  if (!isAPoolMaterialized(row) || typeof row.a_pool?.hit_count !== "number") return "—";
  const top = row.top200?.top_count ?? row.a_pool.top_count;
  return `${row.a_pool.hit_count}/${typeof top === "number" ? top : "缺证"}`;
}

function dateAPoolCoverage(row: Top200DateEntry): string {
  return isAPoolMaterialized(row) ? percentText(row.a_pool?.top200_coverage_pct) : "—";
}

function dateAPoolRate(row: Top200DateEntry): string {
  return isAPoolMaterialized(row) ? percentText(row.a_pool?.selection_hit_rate_pct) : "—";
}

function dateSevenSelected(row: Top200DateEntry): string {
  return isSevenMaterialized(row) ? numberText(row.seven_stage?.selected_count) : "—";
}

function dateSevenHit(row: Top200DateEntry): string {
  if (!isSevenMaterialized(row) || typeof row.seven_stage?.hit_count !== "number") return "—";
  const top = row.seven_stage.top_count ?? row.top200?.top_count;
  return `${row.seven_stage.hit_count}/${typeof top === "number" ? top : "缺证"}`;
}

function dateSevenRate(row: Top200DateEntry): string {
  return isSevenMaterialized(row) ? percentText(row.seven_stage?.selection_hit_rate_pct) : "—";
}

function statusClass(status?: string): string {
  if (status === "READY") return "status-ready";
  if (status === "PARTIAL") return "status-partial";
  return "status-missing";
}

async function loadTop200() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch("/top200-hit.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`A股选股池 Top200 静态数据读取失败（HTTP ${response.status}）。`);
    const body: unknown = await response.json();
    if (!body || typeof body !== "object" || !Array.isArray((body as { dates?: unknown }).dates)) {
      throw new Error("A股选股池 Top200 静态数据缺少 dates 队列。");
    }
    payload.value = body as Top200Payload;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "A股选股池 Top200 静态数据读取失败。";
  } finally {
    loading.value = false;
  }
}

onMounted(loadTop200);
</script>

<template>
  <section class="panel a-top200-panel" data-testid="a-top200-panel" aria-label="A股选股池与七阶段 Top200 只读统计">
    <div class="section-heading">
      <div>
        <span class="eyebrow">UI_ONLY · READ_ONLY_STATISTICS · RESEARCH_ONLY</span>
        <h2>9A. 15:00 A股收盘：全池 / 七阶段 Top200</h2>
      </div>
      <button class="a-top200-close" type="button" data-testid="a-top200-close" @click="emit('close')">关闭统计</button>
    </div>

    <p v-if="loading" class="review-loading" role="status">正在读取 A 股选股池 Top200 物化统计。</p>
    <p v-else-if="error" class="review-loading error" role="alert">{{ error }}</p>

    <template v-else>
      <p v-if="!selectedEntry" class="review-loading" data-testid="a-top200-empty">
        当前页面日期 {{ requestedDate }} 无 A 股选股池 Top200 物化；静态文件没有可展示的日期队列，不补 0。
      </p>
      <template v-else>
        <p v-if="usingFallback" class="a-top200-fallback" data-testid="a-top200-fallback">
          当前页面日期 {{ requestedDate }} 无 A 股选股池 Top200 物化；以下自动展示 latest_available_date {{ formatDate(selectedEntry.date) }} 的只读统计，不补 0。
        </p>
        <p v-else class="a-top200-selected-date" data-testid="a-top200-selected-date">
          当前展示日期 {{ formatDate(selectedEntry.date) }} · {{ statusLabel(selectedEntry.status) }}<template v-if="selectedEntry.reason"> · {{ reasonLabel(selectedEntry.reason) }}</template>
        </p>

        <div class="review-metric-grid">
          <article data-testid="a-top200-card-pool">
            <span>A股选股池整体（六路预选池去重）</span>
            <strong>{{ aPoolHit(selectedEntry) }}</strong>
            <small>S {{ aPoolSelected(selectedEntry) }} · Top200 覆盖率 {{ aPoolCoverage(selectedEntry) }} · 名单命中率 {{ aPoolRate(selectedEntry) }}</small>
            <small>池覆盖 {{ poolCoverageText(selectedEntry.a_pool) }} · {{ poolGapText(selectedEntry.a_pool) }}</small>
          </article>
          <article data-testid="a-top200-card-seven">
            <span>七阶段盘中并集</span>
            <strong>{{ sevenHit(selectedEntry) }}</strong>
            <small>S {{ sevenCount(selectedEntry, selectedEntry.seven_stage?.selected_count) }} · Top200 覆盖率 {{ sevenPercent(selectedEntry, selectedEntry.seven_stage?.top200_coverage_pct) }} · 名单命中率 {{ sevenPercent(selectedEntry, selectedEntry.seven_stage?.selection_hit_rate_pct) }}</small>
            <small>阶段覆盖 {{ coverageText(selectedEntry.stage_coverage) }} · 缺失阶段：{{ missingStagesText(selectedEntry.stage_coverage) }}</small>
          </article>
          <article data-testid="a-top200-card-top200">
            <span>Top200 口径</span>
            <strong>{{ selectedEntry.top200 ? numberText(selectedEntry.top200.top_count) : "未物化" }}</strong>
            <small>最低涨幅 {{ selectedEntry.top200 ? rawPercent(selectedEntry.top200.min_change_pct) : "未物化" }}</small>
            <small>来源 {{ selectedEntry.top200?.source || "未物化" }}</small>
          </article>
        </div>

        <h3>分池统计（同一交易日）</h3>
        <div class="review-table-wrap a-top200-table-wrap">
          <table class="a-top200-pool-table">
            <thead>
              <tr><th>池</th><th>状态</th><th>S</th><th>H</th><th>Top200 覆盖率</th><th>名单命中率</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="pool in poolRows"
                :key="pool.pool_id"
                :class="{ 'summary-row': pool.pool_id === 'a_all_pool_summary' }"
                :data-testid="pool.pool_id === 'a_all_pool_summary' ? 'a-top200-pool-union' : 'a-top200-pool-row'"
              >
                <td class="a-top200-pool-name">
                  <strong>{{ pool.display_name || pool.pool_id }}</strong>
                  <small>{{ pool.pool_id }}</small>
                  <small v-if="poolSignalText(pool)"> · {{ poolSignalText(pool) }}</small>
                </td>
                <td>
                  <span>{{ poolStatusLabel(pool) }}</span>
                  <small class="a-top200-pool-status-detail"> · {{ poolStatusDetail(pool) }}</small>
                </td>
                <td class="numeric">{{ poolSelectedCell(pool) }}</td>
                <td class="numeric">{{ poolHitCell(pool) }}</td>
                <td class="numeric">{{ poolCoverageCell(pool) }}</td>
                <td class="numeric">{{ poolRateCell(pool) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3>日期队列</h3>
        <div class="review-table-wrap a-top200-table-wrap">
          <table class="a-top200-date-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>全池 S</th>
                <th>全池 H</th>
                <th>全池 Top200 覆盖率</th>
                <th>全池 名单命中率</th>
                <th>7阶段 覆盖</th>
                <th>7阶段 S</th>
                <th>7阶段 H</th>
                <th>7阶段 命中率</th>
                <th>状态 / 缺口</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in dates" :key="row.date" data-testid="a-top200-date-row">
                <td>{{ formatDate(row.date) }}</td>
                <td class="numeric">{{ dateAPoolSelected(row) }}</td>
                <td class="numeric">{{ dateAPoolHit(row) }}</td>
                <td class="numeric">{{ dateAPoolCoverage(row) }}</td>
                <td class="numeric">{{ dateAPoolRate(row) }}</td>
                <td>{{ coverageText(row.stage_coverage) }}</td>
                <td class="numeric">{{ dateSevenSelected(row) }}</td>
                <td class="numeric">{{ dateSevenHit(row) }}</td>
                <td class="numeric">{{ dateSevenRate(row) }}</td>
                <td class="status-cell">
                  <span class="status-pill" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
                  <small v-if="rowGapText(row)">{{ rowGapText(row) }}</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="a-top200-window-note">{{ payload?.window_note }} 有合格输入的日期：{{ availableDatesText }}。</p>

        <h3>选中日期逐阶段明细</h3>
        <div class="review-table-wrap a-top200-table-wrap">
          <table class="a-top200-stage-table">
            <thead>
              <tr><th>stage</th><th>状态</th><th>row_count</th><th>unique_codes</th><th>hit_count</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in selectedStageRows" :key="row.id" data-testid="a-top200-stage-row">
                <td>{{ row.id }}<small> · {{ row.label }}</small></td>
                <td>{{ stageStatus(row.entry) }}</td>
                <td class="numeric">{{ stageCount(row.entry, "row_count") }}</td>
                <td class="numeric">{{ stageCount(row.entry, "unique_codes") }}</td>
                <td class="numeric">{{ stageCount(row.entry, "hit_count") }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="a-top200-boundary">
          <p>RESEARCH_ONLY · 不形成买入建议</p>
          <p>A股选股池整体 = 六路 A 预选池按证券代码去重；分池统计见上表；不使用四组公式名单。</p>
          <p>池为 D-1/盘前预选池，命中按目标日收盘统计；不把事后统计说成事前选股能力。</p>
          <p>七阶段盘中并集与 D-1 预选池是两个口径；缺失池/阶段不补 0。</p>
          <p>production_allowed=false · buy_gate_updated=false · orders_sent=false</p>
        </div>
        <p class="a-top200-meta">
          /top200-hit.json · {{ payload?.schema_version || "schema 未标注" }} · 生成于 {{ payload?.generated_at || "未标注" }}
        </p>
      </template>
    </template>
  </section>
</template>

<style scoped>
.a-top200-close {
  padding: 7px 11px;
  color: #254d71;
  background: #f8fbfd;
  border: 1px solid #9eb5c8;
  border-radius: 5px;
  font-weight: 700;
}
.a-top200-selected-date {
  margin: 14px 18px 0;
  padding: 9px 12px;
  color: #526a7f;
  background: #f1f6f9;
  border-left: 4px solid #5f9ac2;
  font-size: 12px;
}
.a-top200-fallback {
  margin: 14px 18px 0;
  padding: 9px 12px;
  color: #765615;
  background: #fff8dc;
  border: 1px solid #ead18a;
  border-radius: 5px;
  font-size: 12px;
}
.a-top200-panel h3 {
  margin: 18px 18px 8px;
  color: #334f66;
  font-size: 14px;
}
.a-top200-table-wrap {
  margin: 0 18px 8px;
  overflow-x: auto;
}
.a-top200-table-wrap table {
  width: 100%;
  border-collapse: collapse;
}
.a-top200-pool-table { min-width: 760px; }
.a-top200-date-table { min-width: 1080px; }
.a-top200-stage-table { min-width: 720px; }
.a-top200-table-wrap th,
.a-top200-table-wrap td {
  padding: 8px 10px;
  border-bottom: 1px solid #e4ebf0;
  font-size: 12px;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}
.a-top200-table-wrap th {
  color: #526a7f;
  background: #f7fafc;
  font-weight: 700;
  line-height: 1.35;
  white-space: normal;
  word-break: keep-all;
}
.a-top200-table-wrap td.numeric {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.a-top200-table-wrap tr.summary-row {
  background: #f1f6f9;
  font-weight: 700;
}
.a-top200-table-wrap td.status-cell {
  min-width: 240px;
  max-width: 360px;
  white-space: normal;
  line-height: 1.45;
}
.a-top200-table-wrap td.status-cell small {
  display: block;
  color: #718499;
  font-size: 10px;
  white-space: normal;
}
.a-top200-table-wrap td small {
  color: #718499;
  font-size: 10px;
}
.a-top200-pool-name strong,
.a-top200-pool-name small {
  display: block;
}
.a-top200-pool-status-detail {
  color: #718499;
  font-size: 10px;
}
.status-pill {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}
.status-ready { color: #2f6b45; background: #e8f5ec; }
.status-partial { color: #7a5a17; background: #fff4d6; }
.status-missing { color: #7a3d3d; background: #fbeaea; }
.a-top200-window-note {
  margin: 0 18px 8px;
  color: #718499;
  font-size: 11px;
  line-height: 1.5;
}
.a-top200-boundary {
  margin: 16px 18px;
  padding: 10px 12px;
  color: #7a5a17;
  background: #fffaf0;
  border: 1px solid #ead9b6;
  border-radius: 5px;
  font-size: 11px;
  line-height: 1.6;
}
.a-top200-boundary p { margin: 0; }
.a-top200-meta {
  margin: 0 18px 18px;
  color: #7a8b9b;
  font-size: 10px;
  overflow-wrap: anywhere;
}
</style>