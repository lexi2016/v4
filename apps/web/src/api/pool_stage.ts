import type { PoolGroup, PoolResponse, StageWorkbench } from "../app_shell/types";
import { assertExactResponseDate, assertExactStagePayload } from "../app_shell/formatters";

export const POOL_PAGE_SIZE = 200;
const STAGE_PAGE_SIZE = 50;
const STAGE_READ_TIMEOUT_MS = 12_000;

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function invalid(label: string, detail: string): never {
  throw new Error(`${label}响应校验失败：${detail}。`);
}

function status(value: unknown, label: string) {
  if (value === undefined) return;
  if (typeof value !== "string" || !/^[A-Z0-9]+(?:_[A-Z0-9]+)*$/.test(value)) {
    invalid(label, "status 必须是有效状态标识");
  }
}

function count(value: unknown, label: string, nullable = false) {
  if (nullable && value === null) return;
  if (value === undefined) return;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    invalid(label, "计数必须是非负整数");
  }
}

function boolean(value: unknown, label: string) {
  if (value !== undefined && typeof value !== "boolean") invalid(label, "标记必须是布尔值");
}

function assertResearchOnlyFlags(
  record: JsonRecord,
  label: string,
  requirements: { researchOnly?: boolean; writePerformed?: boolean; writePolicy?: boolean } = {},
) {
  for (const key of ["production_allowed", "buy_gate_updated", "orders_sent", "write_performed"]) {
    const required = key !== "write_performed" || requirements.writePerformed;
    if (required && typeof record[key] !== "boolean") invalid(label, `缺少布尔型 ${key}`);
    boolean(record[key], label);
    if (record[key] === true) invalid(label, `${key}=true 与只读请求边界冲突`);
  }
  if (requirements.researchOnly && record.RESEARCH_ONLY !== true) {
    invalid(label, "RESEARCH_ONLY 必须为 true");
  } else {
    boolean(record.RESEARCH_ONLY, label);
    if (record.RESEARCH_ONLY === false) invalid(label, "RESEARCH_ONLY=false 与只读请求边界冲突");
  }
  if (requirements.writePolicy && record.write_policy !== "read_only") {
    invalid(label, "write_policy 必须是 read_only");
  }
}

function assertPageEntry(value: unknown, label: string, offset: number, limit: number, actualRows?: number) {
  if (!isRecord(value)) invalid(label, "分页元数据缺失");
  for (const key of ["total_rows", "offset", "limit", "returned_rows"]) {
    if (value[key] === undefined) invalid(label, `缺少 ${key}`);
    count(value[key], label);
  }
  if (typeof value.has_more !== "boolean") invalid(label, "缺少布尔型 has_more");
  if (!Object.prototype.hasOwnProperty.call(value, "next_offset")) invalid(label, "缺少 next_offset");
  boolean(value.complete, label);
  const next = value.next_offset;
  if (next !== null && (typeof next !== "number" || !Number.isSafeInteger(next) || next < 0)) {
    invalid(label, "next_offset 必须是非负整数或 null");
  }
  if (value.offset !== offset || value.limit !== limit) invalid(label, "分页请求与响应 offset/limit 不一致");
  if (actualRows !== undefined && value.returned_rows !== actualRows) {
    invalid(label, `returned_rows=${String(value.returned_rows)} 与实际 ${actualRows} 行不一致`);
  }
  if (typeof value.total_rows === "number" && typeof value.returned_rows === "number") {
    if (value.returned_rows > limit || value.returned_rows > value.total_rows) invalid(label, "返回行数超出 limit 或 total_rows");
    if (typeof value.has_more === "boolean") {
      const expectedHasMore = offset + value.returned_rows < value.total_rows;
      if (value.has_more !== expectedHasMore) invalid(label, "has_more 与 total_rows/returned_rows 不一致");
    }
  }
  if (typeof value.has_more === "boolean" && (value.has_more !== (next !== null))) {
    invalid(label, "has_more 与 next_offset 不一致");
  }
  if (value.has_more === true && next !== offset + limit) invalid(label, "next_offset 不等于下一页 offset");
  if (value.has_more === false && next !== null) invalid(label, "无后续页时 next_offset 必须为 null");
  return value;
}

function assertPageCursor(value: unknown, offset: number, limit: number) {
  if (!isRecord(value)) invalid("D-1 预选池 pagination", "分页元数据缺失");
  if (value.offset !== offset || value.limit !== limit) invalid("D-1 预选池 pagination", "分页请求与响应 offset/limit 不一致");
  if (typeof value.has_more !== "boolean") invalid("D-1 预选池 pagination", "缺少布尔型 has_more");
  if (!Object.prototype.hasOwnProperty.call(value, "next_offset")) invalid("D-1 预选池 pagination", "缺少 next_offset");
  const next = value.next_offset;
  if (next !== null && (typeof next !== "number" || !Number.isSafeInteger(next) || next < 0)) {
    invalid("D-1 预选池 pagination", "next_offset 必须是非负整数或 null");
  }
  if (value.has_more !== (next !== null)) invalid("D-1 预选池 pagination", "has_more 与 next_offset 不一致");
  if (value.has_more === true && next !== offset + limit) invalid("D-1 预选池 pagination", "next_offset 不等于下一页 offset");
  if (value.has_more === false && next !== null) invalid("D-1 预选池 pagination", "无后续页时 next_offset 必须为 null");
  boolean(value.complete, "D-1 预选池 pagination");
  return value;
}

function validatePoolResponse(payload: unknown, requestedDate: string, offset: number): PoolResponse {
  if (isRecord(payload) && !Object.prototype.hasOwnProperty.call(payload, "trade_date")) {
    throw new Error("D-1 预选池日期证据错误：响应缺少 trade_date，未展示该响应。");
  }
  assertExactResponseDate(payload, requestedDate, ["trade_date", "requested_date", "selected_date"], "D-1 预选池");
  if (!isRecord(payload)) invalid("D-1 预选池", "响应不是对象");
  const record = payload;
  status(record.data_status, "D-1 预选池");
  if (typeof record.data_status !== "string") invalid("D-1 预选池", "缺少 data_status");
  assertResearchOnlyFlags(record, "D-1 预选池", { writePolicy: true });

  for (const key of ["rows", "a_all_pool_rows", "unified_rows", "a_source_only_rows"]) {
    const value = record[key];
    if (value !== undefined && (!Array.isArray(value) || value.some((row) => !isRecord(row)))) {
      invalid("D-1 预选池", `${key} 必须是行对象数组`);
    }
  }
  for (const key of ["pool_count", "row_count", "unified_row_count", "a_source_only_row_count", "a_all_pool_row_count"]) {
    count(record[key], "D-1 预选池");
  }
  if (isRecord(record.market_totals)) {
    for (const [market, total] of Object.entries(record.market_totals)) {
      if (market !== "A" && market !== "HK") invalid("D-1 预选池", `market_totals 含非法市场 ${market}`);
      count(total, "D-1 预选池 market_totals");
    }
  } else if (record.market_totals !== undefined) {
    invalid("D-1 预选池", "market_totals 必须是 A/HK 计数对象");
  }

  if (record.pools !== undefined) {
    if (!Array.isArray(record.pools)) invalid("D-1 预选池", "pools 必须是分组数组");
    const groups = record.pools as unknown[];
    const groupIds = new Set<string>();
    for (const [index, item] of groups.entries()) {
      const label = `D-1 预选池 pools[${index}]`;
      if (!isRecord(item) || typeof item.pool_id !== "string" || !item.pool_id.trim()) {
        invalid(label, "缺少 pool_id");
      }
      const group = item as JsonRecord;
      if (groupIds.has(group.pool_id as string)) invalid(label, "pool_id 重复");
      groupIds.add(group.pool_id as string);
      if (group.market !== undefined && group.market !== "A" && group.market !== "HK") {
        invalid(label, `非法 market=${String(group.market)}`);
      }
      status(group.status, label);
      for (const key of ["pool_size", "returned_rows", "page_offset", "page_limit"]) count(group[key], label);
      boolean(group.complete, label);
      boolean(group.has_more, label);
      if (group.rows !== undefined && (!Array.isArray(group.rows) || group.rows.some((row) => !isRecord(row)))) {
        invalid(label, "rows 必须是行对象数组");
      }
      const actualRows = Array.isArray(group.rows) ? group.rows.length : undefined;
      if (actualRows !== undefined && group.returned_rows !== undefined && group.returned_rows !== actualRows) {
        invalid(label, "returned_rows 与当前页 rows 长度不一致");
      }
      if (group.page_offset !== undefined && group.page_offset !== offset) invalid(label, "page_offset 与请求 offset 不一致");
      if (group.page_limit !== undefined && group.page_limit !== POOL_PAGE_SIZE) invalid(label, "page_limit 与请求 limit 不一致");
    }
    if (record.pool_count !== undefined && record.pool_count !== groups.length) {
      invalid("D-1 预选池", "pool_count 与 pools 分组数不一致");
    }
  }

  if (record.pagination !== undefined) {
    if (!isRecord(record.pagination)) invalid("D-1 预选池", "pagination 必须是对象");
    const page = assertPageCursor(record.pagination, offset, POOL_PAGE_SIZE) as JsonRecord;
    const arrayPages = page.arrays;
    if (arrayPages !== undefined && !isRecord(arrayPages)) invalid("D-1 预选池", "pagination.arrays 必须是对象");
    if (isRecord(arrayPages)) {
      for (const key of ["a_all_pool_rows", "a_source_only_rows", "unified_rows"] as const) {
        const array = record[key];
        const pageEntry = arrayPages[key];
        if (pageEntry !== undefined) {
          if (!Array.isArray(array)) invalid("D-1 预选池", `${key} 缺少与分页对照的数组`);
          const checked = assertPageEntry(pageEntry, `D-1 预选池 pagination.arrays.${key}`, offset, POOL_PAGE_SIZE, Array.isArray(array) ? array.length : undefined) as JsonRecord;
          const totalCountKey = key === "a_all_pool_rows" ? "a_all_pool_row_count" : key === "a_source_only_rows" ? "a_source_only_row_count" : "unified_row_count";
          if (typeof record[totalCountKey] === "number" && checked.total_rows !== record[totalCountKey]) {
            invalid("D-1 预选池", `${key} total_rows 与 ${totalCountKey} 不一致`);
          }
        }
      }
    }
    const poolPages = page.pools;
    if (poolPages !== undefined && !isRecord(poolPages)) invalid("D-1 预选池", "pagination.pools 必须是对象");
    if (isRecord(poolPages) && Array.isArray(record.pools)) {
      for (const item of record.pools as PoolGroup[]) {
        const pageEntry = poolPages[item.pool_id];
        if (pageEntry === undefined) continue;
        if (!Array.isArray(item.rows)) invalid("D-1 预选池", `${item.pool_id} 缺少与分页对照的 rows`);
        const checked = assertPageEntry(
          pageEntry,
          `D-1 预选池 pagination.pools.${item.pool_id}`,
          offset,
          POOL_PAGE_SIZE,
          Array.isArray(item.rows) ? item.rows.length : undefined,
        ) as JsonRecord;
        if (item.pool_size !== undefined && checked.total_rows !== item.pool_size) invalid("D-1 预选池", `${item.pool_id} pool_size 与分页总数不一致`);
        if (item.returned_rows !== undefined && checked.returned_rows !== item.returned_rows) invalid("D-1 预选池", `${item.pool_id} returned_rows 与分页计数不一致`);
      }
    }
  }

  return record as unknown as PoolResponse;
}

function validateMarketSummaries(value: unknown) {
  if (value === undefined) return;
  if (!isRecord(value)) invalid("阶段工作台", "markets 必须是市场对象");
  for (const [market, summaryValue] of Object.entries(value)) {
    if (market !== "A" && market !== "HK") invalid("阶段工作台", `markets 含非法市场 ${market}`);
    if (!isRecord(summaryValue)) invalid("阶段工作台", `markets.${market} 必须是对象`);
    for (const key of ["status", "selection_status", "display_mode", "source_status", "data_level"]) {
      status(summaryValue[key], `阶段工作台 markets.${market}.${key}`);
    }
    for (const key of ["candidate_count", "source_rows", "requested_rows", "selected_rows", "observation_count"]) {
      count(summaryValue[key], `阶段工作台 markets.${market}.${key}`, true);
    }
    if (summaryValue.market !== undefined && !["A", "A_SHARE", "HK", "HK_CONNECT"].includes(String(summaryValue.market))) {
      invalid("阶段工作台", `markets.${market}.market 含非法市场 ${String(summaryValue.market)}`);
    }
  }
}

function hasOnlyUnassessedMarketSummaries(value: unknown) {
  if (!isRecord(value)) return false;
  const marketIds = Object.keys(value).sort();
  if (marketIds.length !== 2 || marketIds[0] !== "A" || marketIds[1] !== "HK") return false;
  return marketIds.every((market) => {
    const summary = value[market];
    if (!isRecord(summary)
      || summary.status !== "CANNOT_CONFIRM"
      || (summary.selection_status !== undefined && summary.selection_status !== "CANNOT_CONFIRM")
      || (summary.display_mode !== undefined && summary.display_mode !== "CANNOT_CONFIRM")
      || (summary.candidate_count !== null && summary.candidate_count !== 0)) return false;
    if (["selection_status", "source_status", "data_level"].some((key) =>
      summary[key] !== undefined && summary[key] !== "CANNOT_CONFIRM")) return false;
    if (["source_rows", "requested_rows", "selected_rows", "observation_count", "coverage_ratio"].some((key) =>
      summary[key] !== undefined && summary[key] !== null)) return false;
    if (summary.rows !== undefined && summary.rows !== null
      && (!Array.isArray(summary.rows) || summary.rows.length !== 0)) return false;
    return summary.selection_manifest_receipt_verified === undefined
      || summary.selection_manifest_receipt_verified === false;
  });
}

function hasExactMissingStageReceiptEnvelope(record: JsonRecord, requestedDate: string, stageId: string) {
  const stage = record.stage;
  const executionEvidence = record.execution_evidence;
  const selectionMarkets = record.selection_markets;
  if (!isRecord(stage) || !isRecord(executionEvidence) || !isRecord(selectionMarkets)) return false;
  if (!hasOnlyUnassessedMarketSummaries(record.markets)
    || (record.market_summaries !== undefined && !hasOnlyUnassessedMarketSummaries(record.market_summaries))) return false;
  const markets = Object.entries(selectionMarkets);
  if (markets.length !== 2 || !["A_SHARE", "HK_CONNECT"].every((key) => Object.hasOwn(selectionMarkets, key))) {
    return false;
  }
  const unassessedMarkets = markets.every(([market, value]) => isRecord(value)
    && value.market === market
    && value.status === "CANNOT_CONFIRM"
    && value.selection_status === "CANNOT_CONFIRM"
    && value.selected_rows === null
    && !Object.hasOwn(value, "trade_date")
    && !Object.hasOwn(value, "stage_id")
    && (value.rows === undefined || value.rows === null || (Array.isArray(value.rows) && value.rows.length === 0))
    && (value.selection_manifest_receipt_verified === undefined || value.selection_manifest_receipt_verified === false));
  return record.status === "CANNOT_CONFIRM"
    && stage.stage_id === stageId
    && stage.status === "CANNOT_CONFIRM"
    && stage.display_status === "CANNOT_CONFIRM"
    && executionEvidence.status === "EXECUTION_RECEIPT_MISSING"
    && executionEvidence.trade_date === requestedDate
    && executionEvidence.stage_id === stageId
    && executionEvidence.execution_verified === false
    && executionEvidence.natural_verified === false
    && executionEvidence.write_performed === false
    && Array.isArray(executionEvidence.cannot_confirm)
    && executionEvidence.cannot_confirm.includes("EXACT_DATE_STAGE_RECEIPT_MISSING")
    && unassessedMarkets
    && Array.isArray(record.unified_rows)
    && record.unified_rows.length === 0
    && record.selected_hk_rows === null
    && record.selected_total_rows === null;
}

function validateStageExecutionEvidence(value: unknown) {
  if (!isRecord(value)) invalid("阶段工作台 execution_evidence", "必须是对象");
  status(value.status, "阶段工作台 execution_evidence.status");
  for (const key of ["trade_date", "stage_id"]) {
    if (value[key] !== undefined && typeof value[key] !== "string") {
      invalid("阶段工作台 execution_evidence", `${key} 必须是字符串`);
    }
  }
  for (const key of ["execution_verified", "natural_verified", "write_performed"]) boolean(value[key], "阶段工作台 execution_evidence");
  if (value.cannot_confirm !== undefined
    && (!Array.isArray(value.cannot_confirm) || value.cannot_confirm.some((item) => typeof item !== "string"))) {
    invalid("阶段工作台 execution_evidence", "cannot_confirm 必须是字符串数组");
  }
}

function validateSelectionMarkets(value: unknown, requestedDate: string, stageId: string, allowMissingIdentity = false) {
  if (Array.isArray(value)) {
    if (value.some((market) => market !== "A" && market !== "HK")) {
      invalid("阶段工作台", "selection_markets 数组只允许 A/HK");
    }
    return;
  }
  if (!isRecord(value)) invalid("阶段工作台", "selection_markets 必须是 A/HK 数组或市场结果对象");

  for (const [market, summaryValue] of Object.entries(value)) {
    const label = `阶段工作台 selection_markets.${market}`;
    if (market !== "A_SHARE" && market !== "HK_CONNECT") {
      invalid("阶段工作台", `selection_markets 含非法市场 ${market}`);
    }
    if (!isRecord(summaryValue)) invalid(label, "市场结果必须是对象");
    if (summaryValue.market !== market) invalid(label, "market 与对象键不一致");
    if (summaryValue.trade_date !== requestedDate && !(allowMissingIdentity && summaryValue.trade_date === undefined)) {
      invalid(label, "trade_date 与请求日期不一致");
    }
    if (summaryValue.stage_id !== stageId && !(allowMissingIdentity && summaryValue.stage_id === undefined)) {
      invalid(label, "stage_id 与请求不一致");
    }

    for (const key of ["status", "selection_status"]) {
      if (typeof summaryValue[key] !== "string") invalid(label, `缺少 ${key}`);
      status(summaryValue[key], label);
    }
    for (const key of ["source_status", "research_source_status"]) {
      status(summaryValue[key], label);
    }
    for (const key of ["requested_rows", "source_rows", "selected_rows"]) count(summaryValue[key], label, true);
    const coverage = summaryValue.coverage_ratio;
    if (coverage !== undefined && coverage !== null && (typeof coverage !== "number" || !Number.isFinite(coverage))) {
      invalid(label, "coverage_ratio 必须是有限数字或 null");
    }
    if (summaryValue.rows !== undefined && summaryValue.rows !== null
      && (!Array.isArray(summaryValue.rows) || summaryValue.rows.some((row) => !isRecord(row)))) {
      invalid(label, "rows 必须是行对象数组或 null");
    }
    if (summaryValue.source_evidence !== undefined && summaryValue.source_evidence !== null
      && (!Array.isArray(summaryValue.source_evidence) || summaryValue.source_evidence.some((item) => typeof item !== "string"))) {
      invalid(label, "source_evidence 必须是字符串数组或 null");
    }
    if (summaryValue.cannot_confirm !== undefined && summaryValue.cannot_confirm !== null
      && (!Array.isArray(summaryValue.cannot_confirm)
        || summaryValue.cannot_confirm.some((item) => typeof item !== "string" && !isRecord(item)))) {
      invalid(label, "cannot_confirm 必须是原因数组或 null");
    }
    if (allowMissingIdentity && summaryValue.selection_manifest_receipt_verified === undefined) continue;
    boolean(summaryValue.selection_manifest_receipt_verified, label);
  }
}

function validateStageResponse(payload: unknown, requestedDate: string, stageId: string): StageWorkbench {
  assertExactStagePayload(payload, requestedDate, stageId);
  if (!isRecord(payload)) invalid("阶段工作台", "响应不是对象");
  const record = payload;
  if (record.stage_id !== undefined && record.stage_id !== stageId) invalid("阶段工作台", "stage_id 与请求不一致");
  status(record.status, "阶段工作台");
  assertResearchOnlyFlags(record, "阶段工作台", { researchOnly: true, writePerformed: true });
  if (!isRecord(record.stage)) invalid("阶段工作台", "缺少 stage 对象");
  status(record.stage.status, "阶段工作台 stage.status");
  if (typeof record.stage.display_status !== "string") invalid("阶段工作台", "缺少 stage.display_status");
  if (record.execution_evidence !== undefined) {
    validateStageExecutionEvidence(record.execution_evidence);
    if (isRecord(record.execution_evidence)
      && record.execution_evidence.status === "EXECUTION_RECEIPT_MISSING"
      && (record.execution_evidence.trade_date !== requestedDate || record.execution_evidence.stage_id !== stageId)) {
      invalid("阶段工作台 execution_evidence", "trade_date/stage_id 与请求不一致");
    }
  }
  validateMarketSummaries(record.markets);
  validateMarketSummaries(record.market_summaries);
  const hasMissingExecutionReceipt = isRecord(record.execution_evidence)
    && record.execution_evidence.status === "EXECUTION_RECEIPT_MISSING";
  const exactMissingReceipt = hasExactMissingStageReceiptEnvelope(record, requestedDate, stageId);
  if (hasMissingExecutionReceipt && !exactMissingReceipt) {
    invalid("阶段工作台", "EXECUTION_RECEIPT_MISSING 缺少严格 CANNOT_CONFIRM 市场映射");
  }
  if (record.selection_markets !== undefined) {
    validateSelectionMarkets(
      record.selection_markets,
      requestedDate,
      stageId,
      exactMissingReceipt,
    );
  }
  if (record.selected_a_rows === undefined) invalid("阶段工作台", "缺少 selected_a_rows");
  count(record.selected_a_rows, "阶段工作台");
  for (const key of ["selected_hk_rows", "selected_total_rows"]) count(record[key], "阶段工作台", true);
  if (!Array.isArray(record.unified_rows) || record.unified_rows.some((row) => !isRecord(row))) {
    invalid("阶段工作台", "unified_rows 必须是行对象数组");
  }
  for (const [index, rowValue] of record.unified_rows.entries()) {
    const row = rowValue as JsonRecord;
    if (row.market !== undefined && row.market !== "A" && row.market !== "HK") {
      invalid(`阶段工作台 unified_rows[${index}]`, `非法 market=${String(row.market)}`);
    }
    if (row.trade_date !== undefined && row.trade_date !== requestedDate) {
      invalid(`阶段工作台 unified_rows[${index}]`, "trade_date 与请求不一致");
    }
    if (row.stage_id !== undefined && row.stage_id !== stageId) {
      invalid(`阶段工作台 unified_rows[${index}]`, "stage_id 与请求不一致");
    }
  }
  return record as unknown as StageWorkbench;
}

async function requestJson(url: string, signal?: AbortSignal, timeoutMs?: number) {
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let abortListener: (() => void) | undefined;
  let timedOut = false;
  if (signal) {
    if (signal.aborted) controller.abort(signal.reason);
    else {
      abortListener = () => controller.abort(signal.reason);
      signal.addEventListener("abort", abortListener, { once: true });
    }
  }
  if (timeoutMs !== undefined) {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  try {
    const response = await fetch(url, { signal: controller.signal, ...(timeoutMs !== undefined ? { cache: "no-store" as RequestCache } : {}) });
    if (!response.ok) throw new Error(`request failed (HTTP ${response.status})`);
    return await response.json() as unknown;
  } catch (reason) {
    if (timedOut) throw new Error("阶段工作台读取超时。");
    if (signal?.aborted) throw new DOMException("阶段工作台读取已取消。", "AbortError");
    throw reason;
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    if (abortListener && signal) signal.removeEventListener("abort", abortListener);
  }
}

export async function loadPoolSnapshot(date: string, offset = 0, signal?: AbortSignal): Promise<PoolResponse> {
  if (!/^\d{8}$/.test(date)) throw new Error("D-1 预选池请求日期格式错误。");
  if (!Number.isSafeInteger(offset) || offset < 0) throw new Error("D-1 预选池请求 offset 必须是非负整数。");
  const url = `/api/v3/preselection-pools?date=${encodeURIComponent(date)}&limit=${POOL_PAGE_SIZE}&offset=${offset}`;
  const payload = await requestJson(url, signal);
  return validatePoolResponse(payload, date, offset);
}

export async function loadStageSnapshot(date: string, stageId: string, signal?: AbortSignal): Promise<StageWorkbench> {
  if (!/^\d{8}$/.test(date)) throw new Error("阶段工作台请求日期格式错误。");
  if (!/^[A-Z0-9_]+$/.test(stageId)) throw new Error("阶段工作台请求 stage_id 格式错误。");
  const url = `/api/v3/workbench/stage?date=${encodeURIComponent(date)}&stage=${encodeURIComponent(stageId)}&limit=${STAGE_PAGE_SIZE}`;
  const payload = await requestJson(url, signal, STAGE_READ_TIMEOUT_MS);
  return validateStageResponse(payload, date, stageId);
}
