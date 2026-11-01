/**
 * Projection helpers for the manager selection view.
 *
 * Pure functions and constants only: nothing here reads component state or
 * writes a binding, so the view keeps the reactive wiring and this module
 * keeps formatting and projection.
 */

import { FUTU_US_NATIVE_BOARD_REGISTRY, FUTU_US_NATIVE_BOARD_REGISTRY_SHA256, FUTU_US_NATIVE_BOARD_REGISTRY_VERSION, FutuNativeBoardRow, GLOBAL_INDUSTRY_MAPPINGS, GlobalIndustryResponse, GlobalIndustryRow } from "../../contracts/globalIndustries";



// Additive view metadata; the stored market-quality contract remains unchanged.
export type MarketDisplayStatus = "READY" | "PARTIAL" | "STALE" | "CANNOT_CONFIRM";


export type MarketViewResponse = GlobalIndustryResponse & {
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



export const mappings = GLOBAL_INDUSTRY_MAPPINGS;


export function nativeRowForDisplay(board: FutuNativeBoardRow): GlobalIndustryRow {
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



export function statusText(value: string) {
  return ({ READY: "数据可读", PARTIAL: "部分确认", STALE: "快照偏旧", CANNOT_CONFIRM: "暂无法确认", LOADING: "读取中", ERROR: "读取失败" } as Record<string, string>)[value] || value;
}



export function formatDate(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value || "CANNOT_CONFIRM";
}



export function isCalendarDate(value: unknown): value is string {
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



export function isSameOrPreviousCalendarDate(sourceDate: unknown, targetDate: string) {
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



export function formatChange(value: number | null | undefined) {
  if (typeof value !== "number") return "CANNOT_CONFIRM";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}%`;
}



export function breadthText(row: GlobalIndustryRow) {
  const board = row.official_board;
  if (board.plate_valid !== true || board.rise_count === null || board.fall_count === null || board.equal_count === null) {
    return "涨跌平家数 CANNOT_CONFIRM";
  }
  return `上涨 ${board.rise_count} · 下跌 ${board.fall_count} · 平盘 ${board.equal_count}`;
}



export function proxyReferenceText(row: GlobalIndustryRow) {
  const proxy = row.proxy_reference;
  const coveragePct = typeof proxy.coverage_pct === "number" && Number.isFinite(proxy.coverage_pct)
    ? proxy.coverage_pct.toFixed(1)
    : "CANNOT_CONFIRM";
  return `${proxy.metric_kind === "ETF_REFERENCE" ? "ETF" : "股票篮子"}参考 ${formatChange(proxy.change_pct)} · ${proxy.proxy_symbols.join(" / ")} · ${proxy.available_symbol_count}/${proxy.requested_symbol_count} (${coveragePct}%)`;
}



export function validateNativeBoardSnapshot(value: NonNullable<GlobalIndustryResponse["native_board_snapshot"]>, sourceDate: string) {
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



export function selectResearchDate(value: Record<string, unknown>) {
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
