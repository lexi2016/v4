<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { loadGlobalIndustries, loadGlobalIndustryDates } from "../../api/globalIndustries";
import type {
  GlobalIndustryResponse,
  GlobalIndustryRow,
} from "../../contracts/globalIndustries";
import {
  GLOBAL_INDUSTRY_GROUP,
  GLOBAL_INDUSTRY_MAPPINGS,
  GLOBAL_INDUSTRY_MAPPING_VERSION,
} from "../../contracts/globalIndustries";

// Additive view metadata; the stored market-quality contract remains unchanged.
type MarketDisplayStatus = "READY" | "PARTIAL" | "STALE" | "CANNOT_CONFIRM";
type MarketViewResponse = GlobalIndustryResponse & {
  display_status?: MarketDisplayStatus;
  freshness?: {
    state?: string;
    observed_at?: string;
    captured_at?: string;
    exchange_calendar_status?: string;
    new_capture_performed?: boolean;
    cannot_confirm?: string[];
  };
  market_source?: { source_root?: string };
};

const props = defineProps<{ targetDate: string }>();

const mappings = GLOBAL_INDUSTRY_MAPPINGS;
const configuredProxyCount = new Set(mappings.flatMap((item) => [...item.proxy_symbols])).size;
const clockDiagnostic = ref<{ shanghai_time?: string; new_york_time?: string; clock_phase?: string; state?: string } | null>(null);
const clockMessage = computed(() => ({ BEFORE_REGULAR_CLOSE: "纽约时钟尚未到常规16:00收盘点", AFTER_REGULAR_CLOSE: "纽约时钟已过常规16:00收盘点", WEEKEND_CLOCK: "纽约时钟为周末" } as Record<string, string>)[clockDiagnostic.value?.clock_phase || ""] || "市场时钟未确认");

const state = ref<"LOADING" | MarketDisplayStatus | "ERROR">("LOADING");
const payload = ref<MarketViewResponse | null>(null);
const freshnessMessage = computed(() => ({
  RECENT_BOUND_CAPTURE: "来源场次与原采集时间通过近期时钟核验；不是本次更新或自然运行成功回执。",
  STALE_CLOCK_WINDOW: "快照早于最近计划采集时钟：仅作历史展示，不是最新收盘更新。",
  CANNOT_CONFIRM: "无法确认当前新鲜度；历史快照质量不等于当前数据已更新。",
} as Record<string, string>)[payload.value?.freshness?.state || "CANNOT_CONFIRM"] || "无法确认当前新鲜度。");
const error = ref("");
const researchDate = ref("");
const validated = ref(false);
let requestVersion = 0;
let controller: AbortController | null = null;

const fallbackRows = computed<GlobalIndustryRow[]>(() => mappings.map((mapping) => ({
  label: mapping.label,
  group: mapping.group,
  mapping_type: mapping.mapping_type,
  proxy_symbols: [...mapping.proxy_symbols],
  available_symbols: [],
  missing_symbols: [...mapping.proxy_symbols],
  requested_symbol_count: mapping.proxy_symbols.length,
  available_symbol_count: 0,
  coverage: { available: 0, requested: mapping.proxy_symbols.length },
  coverage_pct: 0,
  change_pct: null,
  direction: "CANNOT_CONFIRM",
  status: "CANNOT_CONFIRM",
  quote_session_dates: [],
  quote_session_times: [],
  cannot_confirm: ["MARKET_SNAPSHOT_NOT_MATERIALIZED"],
})));

const rows = computed(() => payload.value?.rows?.length === 24 ? payload.value.rows : fallbackRows.value);
const numericRows = computed(() => rows.value.filter((row) => typeof row.change_pct === "number"));
const leaders = computed(() => [...numericRows.value].sort(
  (left, right) => (right.change_pct as number) - (left.change_pct as number) || left.label.localeCompare(right.label, "zh-CN"),
).slice(0, 3));
const risingRows = computed(() => [...rows.value].filter((row) => row.direction === "UP").sort(
  (left, right) => (right.change_pct ?? -Infinity) - (left.change_pct ?? -Infinity) || left.label.localeCompare(right.label, "zh-CN"),
));
const flatRows = computed(() => [...rows.value].filter((row) => row.direction === "FLAT").sort(
  (left, right) => Math.abs(left.change_pct ?? 0) - Math.abs(right.change_pct ?? 0) || left.label.localeCompare(right.label, "zh-CN"),
));
const fallingRows = computed(() => [...rows.value].filter((row) => row.direction === "DOWN").sort(
  (left, right) => (right.change_pct ?? 0) - (left.change_pct ?? 0) || left.label.localeCompare(right.label, "zh-CN"),
));
const unknownRows = computed(() => [...rows.value].filter((row) => row.direction === "CANNOT_CONFIRM").sort(
  (left, right) => left.label.localeCompare(right.label, "zh-CN"),
));

function statusText(value: string) {
  return ({ READY: "近期时钟匹配", PARTIAL: "PARTIAL · 质量缺口", STALE: "STALE · 旧快照", CANNOT_CONFIRM: "CANNOT_CONFIRM", LOADING: "读取中", ERROR: "ERROR" } as Record<string, string>)[value] || value;
}

function formatDate(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value || "CANNOT_CONFIRM";
}

function isCalendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const timestamp = Date.UTC(year, month - 1, day);
  const date = new Date(timestamp);
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function isSameOrPreviousCalendarDate(sourceDate: unknown, targetDate: string) {
  if (!isCalendarDate(sourceDate) || !isCalendarDate(targetDate)) return false;
  const sourceTimestamp = Date.UTC(
    Number(sourceDate.slice(0, 4)),
    Number(sourceDate.slice(4, 6)) - 1,
    Number(sourceDate.slice(6, 8)),
  );
  const targetTimestamp = Date.UTC(
    Number(targetDate.slice(0, 4)),
    Number(targetDate.slice(4, 6)) - 1,
    Number(targetDate.slice(6, 8)),
  );
  return targetTimestamp - sourceTimestamp === 0
    || targetTimestamp - sourceTimestamp === 24 * 60 * 60 * 1000;
}

function formatChange(value: number | null | undefined) {
  if (typeof value !== "number") return "CANNOT_CONFIRM";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}%`;
}

function directionText(value: string) {
  return ({ UP: "上涨", FLAT: "平盘", DOWN: "下跌", CANNOT_CONFIRM: "CANNOT_CONFIRM" } as Record<string, string>)[value] || "CANNOT_CONFIRM";
}

function coverageText(row: GlobalIndustryRow) {
  const coveragePct = typeof row.coverage_pct === "number" && Number.isFinite(row.coverage_pct)
    ? row.coverage_pct.toFixed(1)
    : "CANNOT_CONFIRM";
  return `${row.available_symbol_count}/${row.requested_symbol_count} (${coveragePct}%)`;
}

function validateResponse(value: GlobalIndustryResponse, requestedDate: string) {
  if (
    !isCalendarDate(requestedDate)
    || value.target_date !== requestedDate
    || value.research_date !== requestedDate
  ) {
    throw new Error("美股行情日期身份不匹配，已停止展示。");
  }
  if (
    !isCalendarDate(value.source_date)
    || !Array.isArray(value.provider_session_dates)
    || value.provider_session_dates.length !== 1
    || value.provider_session_dates[0] !== value.source_date
    || !isSameOrPreviousCalendarDate(value.source_date, requestedDate)
  ) {
    throw new Error("美股行情来源日期必须唯一且为目标日或前一自然日，已停止展示。");
  }
  if (value.capture_phase !== "POST_CLOSE") {
    throw new Error("美股行情不是 POST_CLOSE 收盘后场次，已停止展示。");
  }
  if (
    value.schema_version !== "v3_5.global_industries.v1"
    || value.mapping_version !== GLOBAL_INDUSTRY_MAPPING_VERSION
    || value.recommendation_status !== "RESEARCH_ONLY"
    || value.RESEARCH_ONLY !== true
    || value.production_allowed !== false
    || value.buy_gate_updated !== false
    || value.orders_sent !== false
  ) {
    throw new Error("美股行情研究安全边界未通过，已停止展示。");
  }
  if (!["READY", "PARTIAL", "CANNOT_CONFIRM"].includes(value.status)) {
    throw new Error("美股行情状态未通过，已停止展示。");
  }
  if (!Array.isArray(value.rows) || value.rows.length !== mappings.length) {
    throw new Error("美股行情主题覆盖不是固定 24 行，已停止展示。");
  }
  value.rows.forEach((row, index) => {
    const mapping = mappings[index];
    if (
      row.label !== mapping.label
      || row.group !== GLOBAL_INDUSTRY_GROUP
      || row.mapping_type !== mapping.mapping_type
      || JSON.stringify(row.proxy_symbols) !== JSON.stringify(mapping.proxy_symbols)
      || row.requested_symbol_count !== mapping.proxy_symbols.length
      || !Array.isArray(row.available_symbols)
      || !Array.isArray(row.missing_symbols)
      || row.available_symbol_count !== row.available_symbols.length
      || row.coverage?.requested !== mapping.proxy_symbols.length
      || row.coverage?.available !== row.available_symbol_count
    ) {
      throw new Error("美股行情固定映射未通过，已停止展示。");
    }
    if (
      !["READY", "PARTIAL", "CANNOT_CONFIRM"].includes(row.status)
      || !["UP", "DOWN", "FLAT", "CANNOT_CONFIRM"].includes(row.direction)
    ) {
      throw new Error("美股行情行状态未通过校验，已停止展示。");
    }
    if (
      typeof row.change_pct === "number" && !Number.isFinite(row.change_pct)
      || row.change_pct !== (row.pct_change ?? row.change_pct)
    ) {
      throw new Error("美股行情涨跌值未通过算术校验，已停止展示。");
    }
  });
}

function selectResearchDate(value: Record<string, unknown>) {
  // The global map represents the newest materialized US close.  Its
  // snapshot directory is the authority; stage targetDate and other date
  // lists describe different lanes and must not silently substitute data.
  const marketSnapshots = Array.isArray(value.market_snapshot_dates)
    ? value.market_snapshot_dates
    : [];
  return marketSnapshots
    .filter((date): date is string => isCalendarDate(date))
    .sort()
    .at(-1) || "";
}

async function refresh() {
  controller?.abort();
  controller = new AbortController();
  const version = ++requestVersion;
  payload.value = null;
  validated.value = false;
  error.value = "";
  researchDate.value = "";
  clockDiagnostic.value = null;
  state.value = "LOADING";
  if (!isCalendarDate(props.targetDate)) {
    state.value = "CANNOT_CONFIRM";
    error.value = "目标阶段日期无效，未读取美股场次。";
    return;
  }
  try {
    const dates = await loadGlobalIndustryDates(controller.signal) as Record<string, unknown>;
    if (version !== requestVersion) return;
    clockDiagnostic.value = (dates.us_close_availability as typeof clockDiagnostic.value) ?? null;
    const selectedSourceDate = selectResearchDate(dates);
    if (!selectedSourceDate) {
      state.value = "CANNOT_CONFIRM";
      error.value = "没有可用的最新美股市场快照日期。";
      return;
    }
    const result = await loadGlobalIndustries(selectedSourceDate, controller.signal);
    validateResponse(result, selectedSourceDate);
    // The stage target may be the next local-market day after the latest
    // completed US session.  Keep both identities visible instead of
    // relabeling the stored close as the target day.
    if (version !== requestVersion) return;
    researchDate.value = result.research_date;
    const view = result as MarketViewResponse;
    payload.value = view;
    validated.value = true;
    // An older backend's READY must not silently become freshness evidence.
    const display = view.display_status;
    const hasFreshness = view.freshness?.new_capture_performed === false
      && ["RECENT_BOUND_CAPTURE", "STALE_CLOCK_WINDOW", "CANNOT_CONFIRM"].includes(view.freshness?.state || "");
    state.value = hasFreshness && display && ["READY", "PARTIAL", "STALE", "CANNOT_CONFIRM"].includes(display)
      ? display : "CANNOT_CONFIRM";
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") return;
    if (version !== requestVersion) return;
    state.value = caught instanceof Error && caught.message.includes("已停止展示")
      ? "CANNOT_CONFIRM"
      : "ERROR";
    error.value = caught instanceof Error ? caught.message : "美股收盘行情读取失败。";
  }
}

watch(() => props.targetDate, refresh, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="panel global-industry-panel" aria-label="美股收盘板块涨跌幅">
    <div class="section-heading global-industry-heading">
      <div>
        <span class="eyebrow">US CLOSE PROXY MAP</span>
        <h2>美股收盘板块涨跌幅（研究只读）</h2>
      </div>
      <div class="global-industry-actions">
        <span class="global-status-badge" :class="`global-status-${state.toLowerCase()}`">{{ statusText(state) }}</span>
        <button type="button" :disabled="state === 'LOADING'" @click="refresh">刷新</button>
      </div>
    </div>
    <div class="global-industry-identity">
      <span>目标阶段日：{{ formatDate(targetDate) }}</span>
      <span>读取快照日：{{ formatDate(researchDate) }}</span>
      <span>美股来源日：{{ formatDate(payload?.source_date || "") }}</span>
      <span>US session：{{ payload?.provider_session_dates?.join("、") || "CANNOT_CONFIRM" }}</span>
      <span>场次：{{ payload?.capture_phase || "CANNOT_CONFIRM" }}</span>
    </div>
    <p v-if="payload" class="global-industry-message" role="status">
      快照质量：{{ payload.status }} · {{ freshnessMessage }}
      交易所节假日／提前收盘及最新完整交易日：{{ payload.freshness?.exchange_calendar_status || "CANNOT_CONFIRM" }}。
      本次刷新只读取，不触发采集。
    </p>
    <p v-if="payload?.cannot_confirm?.length || payload?.freshness?.cannot_confirm?.length" class="global-industry-message" role="status">
      未确认依据：{{ [...(payload?.cannot_confirm || []), ...(payload?.freshness?.cannot_confirm || [])].join("；") }}
    </p>
    <p v-if="payload?.market_source?.source_root" class="global-industry-message">
      美股读取根：{{ payload.market_source.source_root }}
    </p>
    <p v-if="clockDiagnostic" class="global-industry-message" role="status">
      上海时钟：{{ clockDiagnostic.shanghai_time }} · 纽约时钟：{{ clockDiagnostic.new_york_time }} · {{ clockMessage }}。
      这只是时钟，不是交易所节假日/提前收盘核验；不据此推算上一完整交易日。
    </p>
    <p v-if="!researchDate && state !== 'LOADING'" class="global-industry-message">缺少已验证的已完成场次来源。当前市场尚未收盘不能解释此前已完成场次为何缺失，须核对既有输入/物化链；页面不会抓取或补造。</p>
    <p v-if="state === 'LOADING'" class="global-industry-message" role="status">正在读取日期目录和美股收盘场次。</p>
    <p
      v-if="error"
      class="global-industry-message global-industry-error"
      :role="state === 'ERROR' ? 'alert' : 'status'"
    >{{ error }}</p>
    <template v-if="state !== 'LOADING'">
      <div class="global-leader-grid" aria-label="板块涨跌前三">
        <article v-for="(row, index) in leaders" :key="`leader-${row.label}`" class="global-leader-card">
          <span>Leader {{ index + 1 }}</span>
          <strong>{{ row.label }}</strong>
          <b>{{ formatChange(row.change_pct) }}</b>
          <small>{{ directionText(row.direction) }} · {{ coverageText(row) }}</small>
        </article>
        <article v-if="!leaders.length" class="global-leader-card global-leader-empty">
          <strong>CANNOT_CONFIRM</strong><small>当前没有可确认的收盘涨跌值。</small>
        </article>
      </div>
      <div class="global-industry-groups" data-theme-map>
        <section class="global-industry-group global-group-up" aria-label="上涨板块">
          <h3>上涨 <span>{{ risingRows.length }}</span></h3>
          <div class="global-industry-row-grid" data-theme-grid>
            <article v-for="row in risingRows" :key="row.label" class="global-industry-row" data-theme-row>
              <div><strong>{{ row.label }}</strong><small>{{ row.proxy_symbols.join(" / ") }} · {{ row.mapping_type }}</small></div>
              <b>{{ formatChange(row.change_pct) }}</b><span>{{ coverageText(row) }}</span>
            </article>
          </div>
          <p v-if="!risingRows.length">暂无可确认上涨板块。</p>
        </section>
        <section class="global-industry-group global-group-down" aria-label="下跌板块">
          <h3>下跌 <span>{{ fallingRows.length }}</span></h3>
          <div class="global-industry-row-grid" data-theme-grid>
            <article v-for="row in fallingRows" :key="row.label" class="global-industry-row" data-theme-row>
              <div><strong>{{ row.label }}</strong><small>{{ row.proxy_symbols.join(" / ") }} · {{ row.mapping_type }}</small></div>
              <b>{{ formatChange(row.change_pct) }}</b><span>{{ coverageText(row) }}</span>
            </article>
          </div>
          <p v-if="!fallingRows.length">暂无可确认下跌板块。</p>
        </section>
        <section
          v-if="unknownRows.length"
          class="global-industry-group global-group-unknown global-group-wide"
          aria-label="待确认板块"
        >
          <h3>待确认 <span>{{ unknownRows.length }}</span></h3>
          <div class="global-industry-row-grid" data-theme-grid>
            <article v-for="row in unknownRows" :key="row.label" class="global-industry-row" data-theme-row>
              <div><strong>{{ row.label }}</strong><small>{{ row.proxy_symbols.join(" / ") }} · {{ row.mapping_type }}</small></div>
              <b>{{ formatChange(row.change_pct) }}</b><span>{{ coverageText(row) }} · {{ directionText(row.direction) }}</span>
            </article>
          </div>
        </section>
      </div>
      <div class="global-industry-meta">
        <span>provider：{{ payload?.provider || "CANNOT_CONFIRM" }}</span>
        <span>provider session time：{{ payload?.provider_session_times?.join("、") || "CANNOT_CONFIRM" }}</span>
        <span>capture time：{{ payload?.captured_at || "CANNOT_CONFIRM" }}</span>
        <span>coverage：{{ payload ? `${payload.available_symbol_count}/${payload.requested_symbol_count}` : `0/${configuredProxyCount}（配置标的；缺已验证来源）` }}</span>
      </div>
      <p v-if="validated" class="global-industry-note">代理 ETF / 股票篮子仅用于研究观察；change_pct 为当日 close 对 previous_close，篮子按可用成分等权平均。RESEARCH_ONLY=true · production_allowed=false · 不构成预测或交易指令。</p>
    </template>
  </section>
</template>
