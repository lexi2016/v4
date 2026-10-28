<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { loadGlobalIndustries, loadGlobalIndustryDates } from "../../api/globalIndustries";
import type {
  FutuNativeBoardRow,
  GlobalIndustryResponse,
  GlobalIndustryRow,
} from "../../contracts/globalIndustries";
import {
  FUTU_US_NATIVE_BOARD_REGISTRY,
  FUTU_US_NATIVE_BOARD_REGISTRY_SHA256,
  FUTU_US_NATIVE_BOARD_REGISTRY_VERSION,
  GLOBAL_INDUSTRY_GROUP,
  GLOBAL_INDUSTRY_MAPPINGS,
  GLOBAL_INDUSTRY_MAPPING_VERSION,
  GLOBAL_INDUSTRY_OFFICIAL_BOARD_MAP,
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
  native_freshness?: {
    state?: string;
    cannot_confirm?: string[];
  };
  market_source?: { source_root?: string };
};

const props = defineProps<{ targetDate: string }>();

const mappings = GLOBAL_INDUSTRY_MAPPINGS;
const clockDiagnostic = ref<{ shanghai_time?: string; new_york_time?: string; clock_phase?: string; state?: string } | null>(null);
const clockMessage = computed(() => ({ BEFORE_REGULAR_CLOSE: "纽约时钟尚未到常规16:00收盘点", AFTER_REGULAR_CLOSE: "纽约时钟已过常规16:00收盘点", WEEKEND_CLOCK: "纽约时钟为周末" } as Record<string, string>)[clockDiagnostic.value?.clock_phase || ""] || "市场时钟未确认");

const state = ref<"LOADING" | MarketDisplayStatus | "ERROR">("LOADING");
const payload = ref<MarketViewResponse | null>(null);
const freshnessMessage = computed(() => ({
  RECENT_BOUND_CAPTURE: "来源场次与原采集时间通过近期时钟核验；不是本次更新或自然运行成功回执。",
  STALE_CLOCK_WINDOW: "快照早于最近计划采集时钟：仅作历史展示，不是最新收盘更新。",
  STALE_EXCHANGE_SESSION: "快照早于最新完整交易日，仅作历史展示。",
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
  metric_kind: "OFFICIAL_BOARD",
  official_board: {
    metric_kind: "OFFICIAL_BOARD",
    board_name: null,
    board_code: null,
    update_time: null,
    session_date: null,
    timezone: "America/New_York",
    last: null,
    previous_close: null,
    change_pct: null,
    plate_valid: null,
    rise_count: null,
    fall_count: null,
    equal_count: null,
    relations: [],
    relation_status: "CANNOT_CONFIRM",
    cannot_confirm: ["FUTU_BOARD_SNAPSHOT_MISSING"],
  },
  proxy_reference: {
    metric_kind: mapping.mapping_type.includes("basket") ? "STOCK_BASKET_REFERENCE" : "ETF_REFERENCE",
    provider: "Tencent qt.gtimg.cn",
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
  },
  quote_session_dates: [],
  quote_session_times: [],
  cannot_confirm: ["MARKET_SNAPSHOT_NOT_MATERIALIZED"],
})));

const nativeMode = computed(() => Boolean(payload.value?.native_board_snapshot));
const nativeSnapshot = computed(() => payload.value?.native_board_snapshot ?? null);
function nativeRowForDisplay(board: FutuNativeBoardRow): GlobalIndustryRow {
  const confirmed = board.status === "READY" && typeof board.change_pct === "number";
  const change = confirmed ? board.change_pct : null;
  const direction = change === null ? "CANNOT_CONFIRM" : change > 0 ? "UP" : change < 0 ? "DOWN" : "FLAT";
  return {
    label: board.board_name,
    group: "FUTU_NATIVE_BOARD",
    mapping_type: board.plate_type,
    proxy_symbols: [],
    available_symbols: [],
    missing_symbols: [],
    requested_symbol_count: 0,
    available_symbol_count: 0,
    coverage: { available: 0, requested: 0 },
    coverage_pct: 0,
    change_pct: change,
    pct_change: change,
    direction,
    status: confirmed ? "READY" : "CANNOT_CONFIRM",
    metric_kind: "OFFICIAL_BOARD",
    official_board: {
      metric_kind: "OFFICIAL_BOARD",
      market: "US",
      plate_type: board.plate_type,
      board_name: board.board_name,
      expected_board_name: board.board_name,
      board_code: board.board_code,
      update_time: board.update_time,
      session_date: board.session_date,
      timezone: board.timezone,
      last: board.last,
      previous_close: board.previous_close,
      change_pct: confirmed ? board.change_pct : null,
      plate_valid: board.plate_valid,
      rise_count: board.rise_count,
      fall_count: board.fall_count,
      equal_count: board.equal_count,
      member_count: board.member_count,
      membership_status: board.membership_status,
      membership_cannot_confirm: [...board.membership_cannot_confirm],
      relations: [],
      relation_status: "CANNOT_CONFIRM",
      relation_cannot_confirm: ["NATIVE_BOARD_RELATIONS_NOT_INHERITED"],
      target_date_eligibility: "CANNOT_CONFIRM",
      cannot_confirm: [...board.cannot_confirm],
    },
    proxy_reference: {
      metric_kind: "ETF_REFERENCE",
      provider: "CANNOT_CONFIRM",
      mapping_type: "NATIVE_BOARD_NO_PROXY",
      proxy_symbols: [],
      available_symbols: [],
      missing_symbols: [],
      requested_symbol_count: 0,
      available_symbol_count: 0,
      coverage: { available: 0, requested: 0 },
      coverage_pct: null,
      change_pct: null,
      direction: "CANNOT_CONFIRM",
      status: "CANNOT_CONFIRM",
      quote_session_dates: [],
      quote_session_times: [],
      cannot_confirm: ["NATIVE_BOARD_PROXY_NOT_INHERITED"],
    },
    quote_session_dates: confirmed ? [board.session_date || ""] : [],
    quote_session_times: confirmed && board.update_time ? [board.update_time] : [],
    cannot_confirm: confirmed ? [] : [...board.cannot_confirm],
  };
}
const rows = computed(() => {
  const native = nativeSnapshot.value;
  if (native) return native.rows.map(nativeRowForDisplay);
  return payload.value?.rows?.length === mappings.length ? payload.value.rows : fallbackRows.value;
});
const requestedBoardCount = computed(() => nativeSnapshot.value?.requested_board_count
  ?? payload.value?.requested_board_count
  ?? mappings.length);
const nativeProviderSessionTimes = computed(() => [...new Set(
  (nativeSnapshot.value?.rows || [])
    .filter((row) => row.status === "READY" && row.update_time)
    .map((row) => row.update_time as string),
)].sort());
const numericRows = computed(() => state.value === "READY" ? rows.value.filter((row) => row.status === "READY" && typeof row.change_pct === "number") : []);
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
const marketGroups = computed(() => [
  { key: "up", label: "上涨", rows: risingRows.value },
  ...(flatRows.value.length ? [{ key: "flat", label: "平盘", rows: flatRows.value }] : []),
  { key: "down", label: "下跌", rows: fallingRows.value },
]);
const confirmedBoardCount = computed(() => rows.value.filter(
  (row) => row.status === "READY" && typeof row.change_pct === "number",
).length);
const unmatchedBoardCount = computed(() => Math.max(
  0,
  requestedBoardCount.value - confirmedBoardCount.value,
));

function statusText(value: string) {
  return ({ READY: "数据可读", PARTIAL: "部分确认", STALE: "快照偏旧", CANNOT_CONFIRM: "暂无法确认", LOADING: "读取中", ERROR: "读取失败" } as Record<string, string>)[value] || value;
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

const hasUnexpectedSnapshotDate = computed(() => {
  if (!payload.value || !isCalendarDate(props.targetDate) || !isCalendarDate(researchDate.value)) return false;
  return !isSameOrPreviousCalendarDate(researchDate.value, props.targetDate);
});

function formatChange(value: number | null | undefined) {
  if (typeof value !== "number") return "CANNOT_CONFIRM";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}%`;
}

function breadthText(row: GlobalIndustryRow) {
  const board = row.official_board;
  if (board.plate_valid !== true || board.rise_count === null || board.fall_count === null || board.equal_count === null) {
    return "涨跌平家数 CANNOT_CONFIRM";
  }
  return `上涨 ${board.rise_count} · 下跌 ${board.fall_count} · 平盘 ${board.equal_count}`;
}

function proxyReferenceText(row: GlobalIndustryRow) {
  const proxy = row.proxy_reference;
  const coveragePct = typeof proxy.coverage_pct === "number" && Number.isFinite(proxy.coverage_pct)
    ? proxy.coverage_pct.toFixed(1)
    : "CANNOT_CONFIRM";
  return `${proxy.metric_kind === "ETF_REFERENCE" ? "ETF" : "股票篮子"}参考 ${formatChange(proxy.change_pct)} · ${proxy.proxy_symbols.join(" / ")} · ${proxy.available_symbol_count}/${proxy.requested_symbol_count} (${coveragePct}%)`;
}

function validateNativeBoardSnapshot(value: NonNullable<GlobalIndustryResponse["native_board_snapshot"]>, sourceDate: string) {
  if (
    value.schema_version !== "v3_5.futu_us_native_board_snapshot.v2"
    || value.registry_version !== FUTU_US_NATIVE_BOARD_REGISTRY_VERSION
    || value.registry_sha256 !== FUTU_US_NATIVE_BOARD_REGISTRY_SHA256
    || value.provider !== "Futu OpenD"
    || value.market !== "US"
    || value.timezone !== "America/New_York"
    || value.capture_session_date !== sourceDate
    || value.RESEARCH_ONLY !== true
    || value.production_allowed !== false
    || value.buy_gate_updated !== false
    || value.orders_sent !== false
  ) {
    throw new Error("Futu 原生板块版本、来源或安全边界未通过，已停止展示。");
  }
  const registry = FUTU_US_NATIVE_BOARD_REGISTRY;
  if (
    !Array.isArray(value.rows)
    || value.requested_board_count !== registry.length
    || value.rows.length !== registry.length
    || !Number.isInteger(value.available_board_count)
    || !["READY", "PARTIAL", "CANNOT_CONFIRM"].includes(value.status)
  ) {
    throw new Error("Futu 原生板块覆盖数未通过冻结清单校验，已停止展示。");
  }
  const digestValid = /^[0-9a-f]{64}$/.test(value.source_response_sha256);
  const readyRows = value.rows.filter((row) => row.status === "READY");
  if (
    (!digestValid && !(value.status === "CANNOT_CONFIRM" && readyRows.length === 0 && value.source_response_sha256 === ""))
    || value.available_board_count !== readyRows.length
    || value.status !== (readyRows.length === registry.length ? "READY" : readyRows.length ? "PARTIAL" : "CANNOT_CONFIRM")
  ) {
    throw new Error("Futu 原生板块来源摘要或数量不一致，已停止展示。");
  }
  const codes = new Set<string>();
  value.rows.forEach((row, index) => {
    const identity = registry[index];
    if (
      !identity
      || row.board_id !== identity.board_id
      || row.plate_type !== identity.plate_type
      || row.board_name !== identity.board_name
      || row.board_code !== identity.board_code
      || row.expected_board_name !== identity.board_name
      || row.metric_kind !== "OFFICIAL_BOARD"
      || row.market !== "US"
      || row.timezone !== "America/New_York"
      || codes.has(row.board_code)
    ) {
      throw new Error("Futu 原生板块身份或去重校验失败，已停止展示。");
    }
    codes.add(row.board_code);
    if (!Array.isArray(row.cannot_confirm) || row.cannot_confirm.some((reason) => typeof reason !== "string" || !reason)) {
      throw new Error("Futu 原生板块原因字段无效，已停止展示。");
    }
    if (row.status === "READY") {
      if (
        row.session_date !== sourceDate
        || row.plate_valid !== true
        || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(row.update_time || "")
        || row.update_time?.slice(0, 10).replace(/-/g, "") !== sourceDate
        || typeof row.last !== "number"
        || typeof row.previous_close !== "number"
        || !Number.isFinite(row.last)
        || !Number.isFinite(row.previous_close)
        || row.last <= 0
        || row.previous_close <= 0
        || [row.rise_count, row.fall_count, row.equal_count].some((count) => !Number.isInteger(count) || (count as number) < 0)
        || typeof row.change_pct !== "number"
        || Math.round(((row.last - row.previous_close) / row.previous_close * 100) * 1e6) / 1e6 !== Math.round(row.change_pct * 1e6) / 1e6
      ) {
        throw new Error("Futu 原生板块事实未通过日期、合法性或涨幅校验，已停止展示。");
      }
    } else if (row.status !== "CANNOT_CONFIRM" || row.change_pct !== null || !row.cannot_confirm.length) {
      throw new Error("Futu 原生板块未确认状态字段无效，已停止展示。");
    }
    if (
      !["READY", "CANNOT_CONFIRM"].includes(row.membership_status)
      || !Array.isArray(row.membership_cannot_confirm)
      || (row.membership_status === "READY" && (
        !Number.isInteger(row.member_count)
        || (row.member_count as number) < 0
        || !/^[0-9a-f]{64}$/.test(row.membership_sha256)
        || row.membership_cannot_confirm.length > 0
      ))
      || (row.membership_status === "CANNOT_CONFIRM" && row.membership_cannot_confirm.length === 0)
    ) {
      throw new Error("Futu 原生板块成员状态未通过独立校验，已停止展示。");
    }
  });
}

function validateResponse(value: GlobalIndustryResponse, requestedDate: string) {
  if (
    !isCalendarDate(requestedDate)
    || value.target_date !== requestedDate
    || value.research_date !== requestedDate
  ) {
    throw new Error("美股行情日期身份不匹配，已停止展示。");
  }
  const boardDatesValid = Array.isArray(value.provider_session_dates)
    && value.provider_session_dates.length <= 1
    && (value.provider_session_dates.length === 0 || value.provider_session_dates[0] === value.source_date)
    && (value.status === "CANNOT_CONFIRM" || value.provider_session_dates.length === 1);
  if (!isCalendarDate(value.source_date) || !boardDatesValid || !isSameOrPreviousCalendarDate(value.source_date, requestedDate)) {
    throw new Error("美股行情来源日期必须唯一且为目标日或前一自然日，已停止展示。");
  }
  if (value.capture_phase !== "POST_CLOSE") {
    throw new Error("美股行情不是 POST_CLOSE 收盘后场次，已停止展示。");
  }
  if (
    value.schema_version !== "v3_5.global_industries.v2"
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
  const readyBoardCount = value.rows.filter(
    (row) => row.status === "READY" && typeof row.change_pct === "number",
  ).length;
  if (
    value.requested_board_count !== mappings.length
    || value.available_board_count !== readyBoardCount
  ) {
    throw new Error("Futu 已确认板块数与行状态不一致，已停止展示。");
  }
  const nativeSnapshot = value.native_board_snapshot;
  if (nativeSnapshot) validateNativeBoardSnapshot(nativeSnapshot, value.source_date);
  if (nativeSnapshot && value.native_display_status !== undefined && value.native_display_status !== null
    && !["READY", "PARTIAL", "STALE", "CANNOT_CONFIRM"].includes(value.native_display_status)) {
    throw new Error("Futu 原生板块新鲜度状态无效，已停止展示。");
  }
  if (!nativeSnapshot) value.rows.forEach((row, index) => {
    const mapping = mappings[index];
    const officialMapping = GLOBAL_INDUSTRY_OFFICIAL_BOARD_MAP[index];
    if (
      row.label !== mapping.label
      || row.group !== GLOBAL_INDUSTRY_GROUP
      || row.mapping_type !== mapping.mapping_type
      || JSON.stringify(row.proxy_symbols) !== JSON.stringify(mapping.proxy_symbols)
      || row.metric_kind !== "OFFICIAL_BOARD"
      || row.official_board?.metric_kind !== "OFFICIAL_BOARD"
      || row.official_board?.expected_board_name !== officialMapping.board_name
      || row.official_board?.plate_type !== officialMapping.plate_type
      || !row.proxy_reference
      || JSON.stringify(row.proxy_reference.proxy_symbols) !== JSON.stringify(mapping.proxy_symbols)
      || !["ETF_REFERENCE", "STOCK_BASKET_REFERENCE"].includes(row.proxy_reference.metric_kind)
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
      || row.change_pct !== row.official_board.change_pct
    ) {
      throw new Error("美股行情涨跌值未通过算术校验，已停止展示。");
    }
    const board = row.official_board;
    if (row.status === "READY") {
      if (
        !officialMapping.board_name
        || board.board_name !== officialMapping.board_name
        || !board.board_code?.startsWith("US.")
        || board.plate_valid !== true
        || board.session_date !== value.source_date
        || !board.update_time
        || typeof board.last !== "number"
        || typeof board.previous_close !== "number"
        || board.previous_close <= 0
        || [board.rise_count, board.fall_count, board.equal_count].some((count) => !Number.isInteger(count) || (count as number) < 0)
        || Math.round(((board.last - board.previous_close) / board.previous_close * 100) * 1e6) / 1e6 !== Math.round((board.change_pct as number) * 1e6) / 1e6
      ) {
        throw new Error("Futu 官方板块事实未通过日期、合法性或涨幅校验，已停止展示。");
      }
    } else if (board.change_pct !== null) {
      throw new Error("未确认的官方板块不可携带涨跌幅，已停止展示。");
    }
    if (board.plate_valid !== true && [board.rise_count, board.fall_count, board.equal_count].some((count) => count !== null)) {
      throw new Error("无效板块不能显示涨跌家数，已停止展示。");
    }
  });
  if (
    value.futu_board_snapshot?.capture_session_date !== value.capture_session_date
    || value.futu_board_snapshot?.source_response_sha256 !== value.source_response_sha256
    || value.target_date_eligibility !== "CANNOT_CONFIRM"
    || value.relation_evidence?.target_date_eligibility !== "CANNOT_CONFIRM"
    || value.a_share_relation_status !== "NO_REVIEWED_A_SHARE_RELATION_EVIDENCE"
    || !Array.isArray(value.a_share_relations)
    || value.a_share_relations.length !== 0
  ) {
    throw new Error("Futu 来源或跨市场关系边界未通过校验，已停止展示。");
  }
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
    const display = view.native_board_snapshot ? view.native_display_status : view.display_status;
    const hasFreshness = view.freshness?.new_capture_performed === false
      && ["RECENT_BOUND_CAPTURE", "STALE_CLOCK_WINDOW", "STALE_EXCHANGE_SESSION", "CANNOT_CONFIRM"].includes(view.freshness?.state || "");
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
  <section class="panel global-industry-panel us-industry-panel" aria-label="美股收盘板块涨跌幅">
    <header class="us-industry-heading">
      <div class="us-industry-title">
        <p class="us-industry-eyebrow">{{ nativeMode ? "Futu 原生板块 · 收盘只读" : "美股收盘 · 研究只读" }}</p>
        <h2>美股板块</h2>
      </div>
      <div class="us-industry-actions">
        <span class="us-industry-status" :class="'us-industry-status--' + state.toLowerCase()" role="status">
          {{ statusText(state) }}
        </span>
        <button type="button" :disabled="state === 'LOADING'" @click="refresh">刷新</button>
      </div>
    </header>

    <div v-if="payload" class="us-industry-source" aria-label="来源日期和板块覆盖">
      <span>收盘日 <strong>{{ formatDate(payload.source_date) }}</strong></span>
      <span>已确认 <strong>{{ confirmedBoardCount }}/{{ requestedBoardCount }}</strong></span>
    </div>
    <p v-if="payload && !nativeMode" class="us-industry-message us-industry-legacy-note" role="note">
      历史快照 · 旧主题口径。保留该日原有的 {{ payload.available_board_count }}/{{ payload.requested_board_count }} 数据，不代表新版 Futu 原生板块行情。
    </p>
    <p v-else-if="payload && nativeMode" class="us-industry-message us-industry-native-note" role="note">
      新版 Futu 原生板块口径 · registry {{ nativeSnapshot?.registry_version }} · {{ nativeSnapshot?.registry_sha256 }}
    </p>
    <p v-if="hasUnexpectedSnapshotDate" class="us-industry-message us-industry-date-warning" role="status">
      目标阶段日 {{ formatDate(targetDate) }} 与读取快照日 {{ formatDate(researchDate) }} 不一致，请核对日期身份。
    </p>
    <p v-if="!payload && state === 'LOADING'" class="us-industry-message" role="status">正在读取美股收盘数据…</p>
    <p
      v-if="error"
      class="us-industry-message us-industry-error"
      :role="state === 'ERROR' ? 'alert' : 'status'"
    >{{ error }}</p>

    <section v-if="state !== 'LOADING'" class="us-industry-overview" aria-label="板块涨跌概览">
      <div class="us-industry-overview-item us-industry-overview-up">
        <strong>{{ risingRows.length }}</strong><span>上涨</span>
      </div>
      <div class="us-industry-overview-item us-industry-overview-down">
        <strong>{{ fallingRows.length }}</strong><span>下跌</span>
      </div>
      <div class="us-industry-overview-item us-industry-overview-pending">
        <strong>{{ unmatchedBoardCount }}</strong><span>{{ nativeMode ? "数据未确认" : "待匹配" }}</span>
      </div>
    </section>

    <section v-if="leaders.length" class="us-industry-leaders" aria-label="涨幅前三">
      <h3>涨幅前三</h3>
      <ol>
        <li v-for="(row, index) in leaders" :key="row.label">
          <span>{{ index + 1 }}</span>
          <strong>{{ row.official_board.board_name || row.label }}</strong>
          <b>{{ formatChange(row.change_pct) }}</b>
        </li>
      </ol>
    </section>

    <div v-if="state !== 'LOADING'" class="global-industry-groups us-industry-groups" :aria-label="nativeMode ? 'Futu 原生板块列表' : '历史主题板块列表'" data-theme-map>
      <section
        v-for="group in marketGroups"
        :key="group.key"
        class="global-industry-group us-industry-group"
        :class="'us-industry-group--' + group.key"
        :aria-label="group.label + '板块'"
        :data-theme-group="group.key"
      >
        <h3>{{ group.label }} <span>{{ group.rows.length }}</span></h3>
        <div class="global-industry-row-grid us-industry-row-grid" data-theme-grid>
          <details
            v-for="row in group.rows"
            :key="row.label"
            class="global-industry-row us-industry-row"
            data-theme-row
            :data-native-board-row="nativeMode ? row.official_board.board_code : undefined"
          >
            <summary class="us-industry-row-summary" :class="{ 'us-industry-row-summary--native': nativeMode }">
              <small v-if="nativeMode" class="us-industry-board-type">{{ row.official_board.plate_type === "INDUSTRY" ? "行业" : "概念" }}</small>
              <strong>{{ row.official_board.board_name || row.label }}</strong>
              <b>{{ typeof row.change_pct === "number" ? formatChange(row.change_pct) : nativeMode ? "数据未确认" : "待确认" }}</b>
              <span class="us-industry-row-toggle" aria-hidden="true">＋</span>
            </summary>
            <div class="us-industry-row-detail">
              <dl>
                <div><dt>{{ nativeMode ? "Futu 官方板块" : "研究主题" }}</dt><dd>{{ row.official_board.board_name || row.label }}</dd></div>
                <div v-if="!nativeMode"><dt>官方板块</dt><dd>{{ row.official_board.board_name || "待匹配" }}</dd></div>
                <div><dt>板块代码</dt><dd>{{ row.official_board.board_code || "CANNOT_CONFIRM" }}</dd></div>
                <div><dt>板块类别</dt><dd>{{ row.official_board.plate_type || row.mapping_type }}</dd></div>
                <div><dt>更新时间</dt><dd>{{ row.official_board.update_time || "CANNOT_CONFIRM" }} · {{ row.official_board.timezone }}</dd></div>
                <div><dt>板块涨跌幅</dt><dd>{{ formatChange(row.change_pct) }}</dd></div>
                <div><dt>涨跌平家数</dt><dd>{{ breadthText(row) }}</dd></div>
                <div v-if="nativeMode"><dt>成员状态</dt><dd>{{ row.official_board.membership_status || "CANNOT_CONFIRM" }} · {{ row.official_board.member_count ?? "CANNOT_CONFIRM" }}</dd></div>
                <div v-if="nativeMode && row.official_board.membership_status !== 'READY'"><dt>成员未确认依据</dt><dd>{{ row.official_board.membership_cannot_confirm?.join("；") || "CANNOT_CONFIRM" }}</dd></div>
                <div v-if="nativeMode && row.status !== 'READY'"><dt>数据未确认依据</dt><dd>{{ row.official_board.cannot_confirm.join("；") || "CANNOT_CONFIRM" }}</dd></div>
              </dl>
              <section v-if="!nativeMode" class="us-industry-reference">
                <h4>{{ row.proxy_reference.metric_kind === "ETF_REFERENCE" ? "ETF 独立参考" : "股票篮子独立参考" }}</h4>
                <p>{{ proxyReferenceText(row) }}</p>
                <small>来源：{{ row.proxy_reference.provider }}</small>
              </section>
              <section v-if="!nativeMode" class="us-industry-relations">
                <h4>跨市场关系证据 · {{ row.official_board.relation_status }}</h4>
                <template v-if="row.official_board.relations.length">
                  <article
                    v-for="relation in row.official_board.relations"
                    :key="[relation.us_symbol, relation.hk_symbol, relation.relationship_type].join('-')"
                  >
                    <strong>{{ relation.us_symbol }} → {{ relation.hk_symbol }}</strong>
                    <p>{{ relation.relationship_type }} · {{ relation.direction }} · 可得时间 {{ relation.available_at || "CANNOT_CONFIRM" }}</p>
                    <ul>
                      <li v-for="source in relation.sources" :key="source.url">
                        <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title || source.url }}（发布 {{ source.published_at || "CANNOT_CONFIRM" }}）</a>
                      </li>
                    </ul>
                    <p v-if="relation.limitations.length">限制：{{ relation.limitations.join("；") }}</p>
                  </article>
                </template>
                <p v-else>当前没有可列出的关系记录。</p>
              </section>
            </div>
          </details>
          <p v-if="!group.rows.length" class="us-industry-empty">暂无可确认{{ group.label }}板块。</p>
        </div>
      </section>

      <details
        v-if="unknownRows.length"
        class="global-industry-group us-industry-group us-industry-group--pending global-group-wide"
        :aria-label="nativeMode ? '数据未确认原生板块' : '待匹配主题'"
        data-theme-group="pending"
      >
        <summary class="us-industry-group-summary">
          <strong>{{ nativeMode ? "数据未确认" : "待匹配主题" }} {{ unmatchedBoardCount }}</strong>
          <span>点击展开</span>
        </summary>
        <div class="global-industry-row-grid us-industry-row-grid us-industry-pending-rows" data-theme-grid>
          <details
            v-for="row in unknownRows"
            :key="row.label"
            class="global-industry-row us-industry-row"
            data-theme-row
            :data-native-board-row="nativeMode ? row.official_board.board_code : undefined"
          >
            <summary class="us-industry-row-summary" :class="{ 'us-industry-row-summary--native': nativeMode }">
              <small v-if="nativeMode" class="us-industry-board-type">{{ row.official_board.plate_type === "INDUSTRY" ? "行业" : "概念" }}</small>
              <strong>{{ row.official_board.board_name || row.label }}</strong>
              <b>{{ nativeMode ? "数据未确认" : "待匹配" }}</b>
              <span class="us-industry-row-toggle" aria-hidden="true">＋</span>
            </summary>
            <div class="us-industry-row-detail">
              <dl>
                <div><dt>{{ nativeMode ? "Futu 官方板块" : "研究主题" }}</dt><dd>{{ row.official_board.board_name || row.label }}</dd></div>
                <div><dt>官方板块</dt><dd>{{ row.official_board.board_name || "待匹配" }}</dd></div>
                <div><dt>板块代码</dt><dd>{{ row.official_board.board_code || "CANNOT_CONFIRM" }}</dd></div>
                <div><dt>板块类别</dt><dd>{{ row.official_board.plate_type || row.mapping_type }}</dd></div>
                <div><dt>更新时间</dt><dd>{{ row.official_board.update_time || "CANNOT_CONFIRM" }} · {{ row.official_board.timezone }}</dd></div>
                <div><dt>板块涨跌幅</dt><dd>{{ nativeMode ? "数据未确认" : "暂无已确认数值" }}</dd></div>
                <div><dt>涨跌平家数</dt><dd>{{ breadthText(row) }}</dd></div>
                <div v-if="nativeMode"><dt>数据未确认依据</dt><dd>{{ row.official_board.cannot_confirm.join("；") || "CANNOT_CONFIRM" }}</dd></div>
                <div v-if="nativeMode"><dt>成员状态</dt><dd>{{ row.official_board.membership_status || "CANNOT_CONFIRM" }} · {{ row.official_board.member_count ?? "CANNOT_CONFIRM" }}</dd></div>
                <div v-if="nativeMode"><dt>成员未确认依据</dt><dd>{{ row.official_board.membership_cannot_confirm?.join("；") || "CANNOT_CONFIRM" }}</dd></div>
              </dl>
              <section v-if="!nativeMode" class="us-industry-reference">
                <h4>{{ row.proxy_reference.metric_kind === "ETF_REFERENCE" ? "ETF 独立参考" : "股票篮子独立参考" }}</h4>
                <p>{{ proxyReferenceText(row) }}</p>
                <small>来源：{{ row.proxy_reference.provider }}</small>
              </section>
              <section v-if="!nativeMode" class="us-industry-relations">
                <h4>跨市场关系证据 · {{ row.official_board.relation_status }}</h4>
                <template v-if="row.official_board.relations.length">
                  <article
                    v-for="relation in row.official_board.relations"
                    :key="[relation.us_symbol, relation.hk_symbol, relation.relationship_type].join('-')"
                  >
                    <strong>{{ relation.us_symbol }} → {{ relation.hk_symbol }}</strong>
                    <p>{{ relation.relationship_type }} · {{ relation.direction }} · 可得时间 {{ relation.available_at || "CANNOT_CONFIRM" }}</p>
                    <ul>
                      <li v-for="source in relation.sources" :key="source.url">
                        <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title || source.url }}（发布 {{ source.published_at || "CANNOT_CONFIRM" }}）</a>
                      </li>
                    </ul>
                    <p v-if="relation.limitations.length">限制：{{ relation.limitations.join("；") }}</p>
                  </article>
                </template>
                <p v-else>当前没有可列出的关系记录。</p>
              </section>
            </div>
          </details>
        </div>
      </details>
    </div>

    <details class="us-industry-explanation">
      <summary>数据与说明</summary>
      <div class="us-industry-explanation-body">
        <template v-if="payload">
          <dl>
            <div><dt>目标阶段日</dt><dd>{{ formatDate(targetDate) }}</dd></div>
            <div><dt>读取快照日</dt><dd>{{ formatDate(researchDate) }}</dd></div>
            <div><dt>板块来源日</dt><dd>{{ formatDate(payload.source_date) }}</dd></div>
            <div><dt>官方来源</dt><dd>{{ payload.provider }} · {{ payload.futu_board_snapshot.provider || "CANNOT_CONFIRM" }}</dd></div>
            <div><dt>板块更新时间</dt><dd>{{ (nativeMode ? nativeProviderSessionTimes : payload.provider_session_times).join("、") || "CANNOT_CONFIRM" }} · {{ nativeSnapshot?.timezone || payload.futu_board_snapshot.timezone || "CANNOT_CONFIRM" }}</dd></div>
            <div><dt>场次</dt><dd>{{ payload.capture_phase }} · {{ payload.futu_board_snapshot.capture_session_date || "CANNOT_CONFIRM" }}</dd></div>
            <div><dt>采集时间</dt><dd>{{ payload.captured_at }} · 生成时间 {{ payload.generated_at }}</dd></div>
            <div><dt>新鲜度核验时间</dt><dd>观测 {{ payload.freshness?.observed_at || "CANNOT_CONFIRM" }} · 原采集 {{ payload.freshness?.captured_at || payload.captured_at }}</dd></div>
            <div><dt>数据校验摘要</dt><dd>官方 SHA {{ nativeSnapshot?.source_response_sha256 || payload.source_response_sha256 }} · registry SHA {{ nativeSnapshot?.registry_sha256 || "CANNOT_CONFIRM" }} · 旧参考 SHA {{ payload.proxy_source_response_sha256 || "CANNOT_CONFIRM" }}</dd></div>
            <div><dt>{{ nativeMode ? "原生板块质量" : "旧主题官方板块质量" }}</dt><dd>{{ nativeSnapshot?.status || payload.status }} · {{ nativeSnapshot?.available_board_count ?? payload.available_board_count }}/{{ nativeSnapshot?.requested_board_count ?? payload.requested_board_count }}</dd></div>
            <div><dt>{{ nativeMode ? "旧主题口径快照" : "主题快照质量" }}</dt><dd>{{ payload.futu_board_snapshot.status }} · {{ payload.available_board_count }}/{{ payload.requested_board_count }} · {{ payload.futu_board_snapshot.cannot_confirm.join("；") || "无额外限制" }}</dd></div>
            <div v-if="!nativeMode"><dt>参考行情覆盖</dt><dd>{{ payload.proxy_available_symbol_count }}/{{ payload.proxy_requested_symbol_count }} · {{ payload.legacy_proxy_provider || "CANNOT_CONFIRM" }} · {{ payload.legacy_proxy_status || "CANNOT_CONFIRM" }}</dd></div>
            <div v-if="!nativeMode"><dt>参考更新时间</dt><dd>{{ payload.proxy_provider_session_dates.join("、") || "CANNOT_CONFIRM" }} · {{ payload.proxy_provider_session_times.join("、") || "CANNOT_CONFIRM" }}</dd></div>
            <div v-if="nativeMode"><dt>原生板块新鲜度</dt><dd>{{ payload.native_display_status || "CANNOT_CONFIRM" }} · {{ payload.native_freshness?.state || "CANNOT_CONFIRM" }} · {{ payload.native_freshness?.cannot_confirm?.join("；") || "无额外限制" }}</dd></div>
            <div><dt>整体新鲜度</dt><dd>{{ state }} · {{ freshnessMessage }}</dd></div>
            <div><dt>交易日核验</dt><dd>{{ payload.freshness?.exchange_calendar_status || "CANNOT_CONFIRM" }} · 最新完整交易日未据时钟推算。</dd></div>
            <div v-if="!nativeMode"><dt>关系证据审核</dt><dd>{{ payload.relation_evidence.status }} · {{ payload.relation_evidence.reviewed_at || "CANNOT_CONFIRM" }} · {{ payload.relation_evidence.reviewer_identity || "CANNOT_CONFIRM" }}</dd></div>
            <div v-if="!nativeMode"><dt>关系证据文件</dt><dd>{{ payload.relation_evidence.evidence_path || "CANNOT_CONFIRM" }} · SHA {{ payload.relation_evidence.evidence_sha256 || "CANNOT_CONFIRM" }}</dd></div>
            <div v-if="!nativeMode"><dt>审核文件</dt><dd>{{ payload.relation_evidence.review_path || "CANNOT_CONFIRM" }} · SHA {{ payload.relation_evidence.review_sha256 || "CANNOT_CONFIRM" }}</dd></div>
            <div v-if="!nativeMode"><dt>跨市场关系</dt><dd>港股 {{ payload.hk_relation_status }} · A股 {{ payload.a_share_relation_status }} · 目标日期资格 {{ payload.target_date_eligibility }}</dd></div>
            <div v-else><dt>关系边界</dt><dd>原生板块不自动继承旧主题的腾讯代理或 A/HK 关系。</dd></div>
            <div><dt>刷新方式</dt><dd>本页面只读取既有快照，不触发采集。</dd></div>
          </dl>
          <p v-if="payload.cannot_confirm.length || payload.freshness?.cannot_confirm?.length">
            未确认依据：{{ [...payload.cannot_confirm, ...(payload.freshness?.cannot_confirm || [])].join("；") }}
          </p>
          <p v-if="payload.relation_evidence.limitations.length">
            关系证据限制：{{ payload.relation_evidence.limitations.join("；") }}
          </p>
          <p v-if="payload.relation_evidence.cannot_confirm.length">
            关系证据待确认：{{ payload.relation_evidence.cannot_confirm.join("；") }}
          </p>
        </template>
        <dl v-if="clockDiagnostic">
          <div><dt>上海时钟</dt><dd>{{ clockDiagnostic.shanghai_time || "CANNOT_CONFIRM" }}</dd></div>
          <div><dt>纽约时钟</dt><dd>{{ clockDiagnostic.new_york_time || "CANNOT_CONFIRM" }} · {{ clockMessage }}</dd></div>
          <div><dt>时钟边界</dt><dd>这只是时钟，不是交易所节假日／提前收盘核验；不据此推算上一完整交易日。</dd></div>
        </dl>
        <p v-if="!payload && state !== 'LOADING'">
          暂时没有已验证的美股收盘快照。当前市场尚未收盘不能解释此前已完成场次为何缺失，须核对既有输入与物化链；页面不会抓取或补造。
        </p>
        <p v-if="state !== 'READY'">涨幅前三只在状态为 READY 时生成。当前状态未满足该条件，页面不会按部分、过期或未确认数据生成排名。</p>
          <p v-if="validated && !nativeMode">
          板块涨幅仅使用同一 Futu board 的 last / previous_close；涨跌家数仅在 plate_valid=true 且三项齐全时显示。
          ETF / 股票篮子另列为参考，不参与板块涨跌判断。跨市场关系是已审业务关系证据，不表示收入、因果或目标日期资格。
          RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false。
        </p>
          <p v-else-if="validated && nativeMode">
            板块涨跌幅和涨跌平家数仅来自同一 Futu 原生板块快照；成员状态独立显示。RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false。
          </p>
      </div>
    </details>
  </section>
</template>

<style scoped>
.us-industry-panel {
  --us-blue: #244d6d;
  --us-muted: #687d8f;
  --us-line: #d5e0e8;
  --us-soft: #f4f8fb;
  --us-up: #28714b;
  --us-down: #a34d4d;
  --us-warn: #795b17;
  overflow: hidden;
  color: #294a65;
}

.us-industry-panel *,
.us-industry-panel *::before,
.us-industry-panel *::after { box-sizing: border-box; }

.us-industry-panel :focus-visible {
  outline: 3px solid #2e78a7;
  outline-offset: 3px;
}

.us-industry-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 8px;
}
.us-industry-title { min-width: 0; }
.us-industry-title h2 {
  margin: 0;
  color: var(--us-blue);
  font-size: 20px;
  line-height: 1.25;
  font-weight: 750;
}
.us-industry-eyebrow {
  margin: 0 0 3px;
  color: var(--us-muted);
  font-size: 12px;
  letter-spacing: .04em;
}
.us-industry-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.us-industry-status {
  padding: 5px 9px;
  color: #35627e;
  background: #edf5fa;
  border: 1px solid #a9c6d9;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.2;
  font-weight: 700;
  white-space: nowrap;
}
.us-industry-status--ready {
  color: var(--us-up);
  background: #edf8f1;
  border-color: #9bceb0;
}
.us-industry-status--partial,
.us-industry-status--stale,
.us-industry-status--cannot_confirm {
  color: var(--us-warn);
  background: #fff8dd;
  border-color: #e3cc80;
}
.us-industry-status--error {
  color: #8b3232;
  background: #fff0f0;
  border-color: #dba2a2;
}
.us-industry-actions button {
  min-width: 64px;
  min-height: 44px;
  padding: 7px 12px;
  color: var(--us-blue);
  background: #f8fbfd;
  border: 1px solid #9eb5c8;
  border-radius: 6px;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.us-industry-actions button:hover { background: #eaf4fb; }
.us-industry-actions button:disabled { cursor: wait; opacity: .72; }

.us-industry-source {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  padding: 5px 16px 9px;
  color: var(--us-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.us-industry-source strong { color: var(--us-blue); font-weight: 700; }

.us-industry-message {
  margin: 8px 16px;
  padding: 9px 11px;
  color: #526a7f;
  background: var(--us-soft);
  border-left: 4px solid #5f9ac2;
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.us-industry-error {
  color: #8b3232;
  background: #fff3f3;
  border-left-color: #b85555;
}
.us-industry-date-warning {
  color: #76581a;
  background: #fff9e8;
  border-left-color: #c99b38;
}
.us-industry-legacy-note {
  color: #76581a;
  background: #fff9e8;
  border-left-color: #c99b38;
}
.us-industry-native-note { color: #365c76; }

.us-industry-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
  padding: 4px 16px 10px;
}
.us-industry-overview-item {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  padding: 6px 8px;
  background: var(--us-soft);
  border: 1px solid var(--us-line);
  border-radius: 6px;
}
.us-industry-overview-item strong {
  font-size: 16px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.us-industry-overview-item span { color: #526a7f; font-size: 12px; white-space: nowrap; }
.us-industry-overview-up strong { color: var(--us-up); }
.us-industry-overview-down strong { color: var(--us-down); }
.us-industry-overview-pending strong { color: var(--us-warn); }

.us-industry-leaders {
  margin: 0 16px 8px;
  padding: 8px 10px;
  background: #f7fafc;
  border: 1px solid var(--us-line);
  border-radius: 6px;
}
.us-industry-leaders h3 { margin: 0 0 5px; color: var(--us-blue); font-size: 13px; }
.us-industry-leaders ol {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.us-industry-leaders li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--us-blue);
  font-size: 12px;
}
.us-industry-leaders li > span { color: var(--us-muted); font-variant-numeric: tabular-nums; }
.us-industry-leaders li strong { min-width: 0; overflow-wrap: anywhere; }
.us-industry-leaders li b {
  color: var(--us-up);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.us-industry-panel .global-industry-groups {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  padding: 0 16px 10px;
}
.us-industry-panel .global-industry-group {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
  padding: 8px;
  background: #f5f8fa;
  border: 1px solid var(--us-line);
  border-top: 3px solid #6f9ab9;
  border-radius: 7px;
}
.us-industry-panel .global-industry-group h3 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
  color: #36546d;
  font-size: 14px;
}
.us-industry-panel .global-industry-group h3 span {
  color: var(--us-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.us-industry-group--up { border-top-color: #4f9a70 !important; }
.us-industry-group--up > h3 { color: var(--us-up) !important; }
.us-industry-group--down { border-top-color: #bb6666 !important; }
.us-industry-group--down > h3 { color: #984747 !important; }
.us-industry-group--flat { border-top-color: #8ba8bd !important; }
.us-industry-group--pending { border-top-color: #d0a83c !important; }

.us-industry-panel .global-industry-row-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 5px;
  min-width: 0;
}
.us-industry-panel .global-industry-row {
  display: block;
  min-width: 0;
  padding: 0;
  background: #fff;
  border: 1px solid #d9e3ea;
  border-radius: 5px;
}
.us-industry-row-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 24px;
  align-items: center;
  gap: 8px;
  min-height: 48px;
  padding: 5px 9px;
  cursor: pointer;
  list-style: none;
}
.us-industry-row-summary--native { grid-template-columns: auto minmax(0, 1fr) auto 24px; }
.us-industry-board-type {
  padding: 3px 6px;
  color: #35627e;
  background: #edf5fa;
  border: 1px solid #a9c6d9;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.2;
  white-space: nowrap;
}
.us-industry-row-summary::-webkit-details-marker,
.us-industry-group-summary::-webkit-details-marker,
.us-industry-explanation > summary::-webkit-details-marker { display: none; }
.us-industry-row-summary::marker,
.us-industry-group-summary::marker,
.us-industry-explanation > summary::marker { content: ""; }
.us-industry-panel .us-industry-row-summary strong {
  min-width: 0;
  color: #294a65;
  font-size: 14px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.us-industry-panel .us-industry-row-summary b {
  color: var(--us-up);
  font-size: 14px;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.us-industry-group--down .us-industry-row-summary b { color: var(--us-down); }
.us-industry-group--pending .us-industry-row-summary b { color: var(--us-warn); }
.us-industry-row-toggle {
  display: grid;
  place-items: center;
  width: 24px;
  height: 28px;
  color: var(--us-muted);
  font-size: 18px;
  line-height: 1;
}
.us-industry-row[open] > .us-industry-row-summary,
.us-industry-group--pending[open] > .us-industry-group-summary {
  border-bottom: 1px solid var(--us-line);
}
.us-industry-row[open] > .us-industry-row-summary .us-industry-row-toggle { font-size: 0; }
.us-industry-row[open] > .us-industry-row-summary .us-industry-row-toggle::before {
  content: "−";
  font-size: 18px;
}
.us-industry-panel .global-industry-group > .global-industry-row-grid > p {
  margin: 0;
  color: var(--us-muted);
  font-size: 12px;
}

.us-industry-group-summary,
.us-industry-explanation > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 48px;
  padding: 4px 10px;
  color: #554413;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}
.us-industry-group-summary span { color: var(--us-muted); font-size: 12px; font-weight: 500; }

.us-industry-row-detail { display: grid; gap: 11px; padding: 10px; }
.us-industry-row-detail dl,
.us-industry-explanation-body dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px 14px;
  margin: 0;
}
.us-industry-row-detail dl div,
.us-industry-explanation-body dl div { min-width: 0; }
.us-industry-row-detail dt,
.us-industry-explanation-body dt { margin-bottom: 2px; color: var(--us-muted); font-size: 12px; }
.us-industry-row-detail dd,
.us-industry-explanation-body dd {
  margin: 0;
  color: #294a65;
  font-size: 13px;
  line-height: 1.4;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.us-industry-reference,
.us-industry-relations {
  min-width: 0;
  padding: 9px 10px;
  background: #f6f9fb;
  border: 1px solid #e0e7ed;
  border-radius: 5px;
}
.us-industry-reference h4,
.us-industry-relations h4 { margin: 0 0 4px; color: var(--us-blue); font-size: 13px; }
.us-industry-reference p,
.us-industry-relations p,
.us-industry-relations li,
.us-industry-reference small {
  margin: 0;
  color: #526a7f;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.us-industry-reference small { display: block; margin-top: 3px; }
.us-industry-relations article + article { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--us-line); }
.us-industry-relations article > strong { display: block; margin-bottom: 3px; color: #294a65; font-size: 13px; }
.us-industry-relations ul { margin: 4px 0; padding-left: 18px; }
.us-industry-relations a { color: #1b5f91; text-decoration: underline; text-underline-offset: 2px; }
.us-industry-empty { margin: 0; color: var(--us-muted); font-size: 12px; }

.us-industry-explanation {
  margin: 0 16px 14px;
  background: #f7fafc;
  border: 1px solid var(--us-line);
  border-radius: 6px;
}
.us-industry-explanation > summary { color: var(--us-blue); }
.us-industry-explanation-body {
  display: grid;
  gap: 10px;
  padding: 10px;
  border-top: 1px solid var(--us-line);
}
.us-industry-explanation-body p {
  margin: 0;
  color: #526a7f;
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

@media (min-width: 760px) {
  .us-industry-panel .global-industry-groups { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 480px) {
  .us-industry-heading { align-items: flex-start; padding-right: 12px; padding-left: 12px; }
  .us-industry-source,
  .us-industry-overview { padding-right: 12px; padding-left: 12px; }
  .us-industry-panel .global-industry-groups { padding-right: 12px; padding-left: 12px; }
  .us-industry-explanation { margin-right: 12px; margin-left: 12px; }
  .us-industry-row-detail dl,
  .us-industry-explanation-body dl { grid-template-columns: minmax(0, 1fr); }
  .us-industry-leaders { margin-right: 12px; margin-left: 12px; }
  .us-industry-leaders ol { grid-template-columns: minmax(0, 1fr); }
}
</style>
