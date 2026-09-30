import { MANAGER_STAGE_ID, MANAGER_STAGE_MARKET } from "../contracts/managerStageSelection";

export type ManagerResearchRecord = Readonly<Record<string, unknown>>;

/** Raw, source-bound cards exposed by the bounded material reader. */
export type ManagerResearchReaderMaterial = ManagerResearchRecord & {
  id?: string;
  code?: string;
  canonical_symbol?: string;
  name?: string;
  title?: string;
  content_excerpt?: string | null;
  content_is_excerpt?: boolean;
  published_at?: string;
  published_date?: string;
  collected_at?: string;
  queried_at?: string;
  source_name?: string | null;
  source_url?: string | null;
  url?: string | null;
  source_count?: number;
  source_attributions?: readonly ManagerResearchRecord[];
};

export type ManagerResearchReaderBundle = ManagerResearchRecord & {
  schema?: string;
  status?: string;
  code?: string;
  target_date?: string | null;
  materials?: readonly ManagerResearchReaderMaterial[];
  company_news?: readonly ManagerResearchReaderMaterial[];
  background?: readonly ManagerResearchReaderMaterial[];
};

export type ManagerResearchRow = ManagerResearchRecord & {
  code: string;
  target_trade_date: string;
};

export type ManagerResearchProduct = ManagerResearchRecord & {
  target_trade_date: string;
  stage_id: string;
  market: string;
  rows: readonly ManagerResearchRow[];
};

export type ManagerResearchResponse = ManagerResearchRecord & {
  target_trade_date: string;
  stage_id: string;
  market: string;
  product: ManagerResearchProduct | null;
};

export type ManagerResearchJob = ManagerResearchRecord & {
  job_id?: string;
  status?: string;
};

export type ManagerResearchRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type ManagerResearchErrorKind =
  | "NETWORK_REJECTED"
  | "HTTP_NON_2XX"
  | "INVALID_RESPONSE";

export class ManagerResearchRequestError extends Error {
  readonly kind: ManagerResearchErrorKind;
  readonly status?: number;

  constructor(kind: ManagerResearchErrorKind, message: string, status?: number, cause?: unknown) {
    super(message, { cause });
    this.name = "ManagerResearchRequestError";
    this.kind = kind;
    this.status = status;
  }
}

const MANAGER_RESEARCH_SCHEMA = "v4.manager_research.product.v1";
const NULL_PRODUCT_STATUSES = new Set([
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
  "QUEUED",
  "RUNNING",
  "FAILED",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(record: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function isGregorianDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  if (month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = month === 2
    ? leap ? 29 : 28
    : [4, 6, 9, 11].includes(month) ? 30 : 31;
  return day <= days;
}

function invalidResponse(message: string): never {
  throw new Error(message);
}

function requireSafetyFlags(value: Record<string, unknown>, label: string): void {
  if (value.RESEARCH_ONLY !== true) invalidResponse(`${label} RESEARCH_ONLY must be true`);
  for (const field of ["production_allowed", "buy_gate_updated", "orders_sent"] as const) {
    if (value[field] !== false) invalidResponse(`${label} ${field} must be false`);
  }
}

function readerDate(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const compact = value.trim().slice(0, 10).replaceAll("-", "");
  return isGregorianDate(compact) ? compact : undefined;
}

function isValidReaderHttpUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim() || /\s/.test(value)) return false;
  if (!/^https?:\/\/[^/\s]/i.test(value.trim())) return false;
  try {
    const parsed = new URL(value.trim());
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

function validateOptionalReaderUrl(value: unknown, label: string): void {
  if (value === undefined || value === null || value === "") return;
  if (!isValidReaderHttpUrl(value)) invalidResponse(`${label} must be a valid http/https URL`);
}

function validateReaderMaterial(value: unknown, rowCode: string, expectedDate: string): void {
  if (!isRecord(value)) invalidResponse("manager research reader material must be an object");
  if (value.code !== undefined && value.code !== rowCode) {
    invalidResponse("manager research reader material code does not match its row");
  }
  const published = value.published_date === undefined ? undefined : readerDate(value.published_date);
  if (value.published_date !== undefined && !published) {
    invalidResponse("manager research reader material published_date is invalid");
  }
  if (published && published > expectedDate) {
    invalidResponse("manager research reader material is newer than the requested date");
  }
  if (value.source_count !== undefined
    && (typeof value.source_count !== "number" || !Number.isInteger(value.source_count) || value.source_count < 1)) {
    invalidResponse("manager research reader material source_count is invalid");
  }
  validateOptionalReaderUrl(value.source_url, "manager research reader material source_url");
  validateOptionalReaderUrl(value.url, "manager research reader material url");
  if (value.source_attributions !== undefined
    && (!Array.isArray(value.source_attributions) || !value.source_attributions.every(isRecord))) {
    invalidResponse("manager research reader material source_attributions are invalid");
  }
  if (Array.isArray(value.source_attributions)) {
    value.source_attributions.forEach((attribution, index) => {
      validateOptionalReaderUrl(attribution.url, `manager research reader attribution ${index} url`);
    });
  }
}

function validateReaderProjection(product: Record<string, unknown>, expectedDate: string): void {
  const coverage = product.reader_coverage;
  if (coverage !== undefined) {
    if (!isRecord(coverage)) invalidResponse("manager research reader_coverage must be an object");
    for (const key of ["requested_candidates", "ready_candidates", "partial_candidates", "error_candidates", "material_count"] as const) {
      if (coverage[key] !== undefined
        && (typeof coverage[key] !== "number" || !Number.isInteger(coverage[key]) || coverage[key] < 0)) {
        invalidResponse(`manager research reader_coverage ${key} is invalid`);
      }
    }
  }
  for (const rawRow of product.rows as readonly unknown[]) {
    if (!isRecord(rawRow)) continue;
    const rowCode = typeof rawRow.code === "string" ? rawRow.code : "";
    const catalyst = rawRow.catalyst_result;
    if (!isRecord(catalyst)) continue;
    for (const eventsKey of ["events", "historical_events", "current_events"] as const) {
      const events = catalyst[eventsKey];
      if (events === undefined) continue;
      if (!Array.isArray(events) || !events.every(isRecord)) {
        invalidResponse(`manager research ${eventsKey} are invalid`);
      }
      events.forEach((event, index) => {
        validateOptionalReaderUrl(event.source_url, `manager research ${eventsKey}[${index}] source_url`);
      });
    }
    for (const key of ["reader_bundle"] as const) {
      const bundle = catalyst[key];
      if (bundle !== undefined && !isRecord(bundle)) invalidResponse(`manager research ${key} must be an object`);
      if (!isRecord(bundle)) continue;
      if (bundle.code !== undefined && bundle.code !== rowCode) invalidResponse("manager research reader bundle code does not match its row");
      for (const materialsKey of ["materials", "company_news", "background", "reader_materials"] as const) {
        const materials = bundle[materialsKey];
        if (materials !== undefined && (!Array.isArray(materials) || !materials.every((item) => {
          try {
            validateReaderMaterial(item, rowCode, expectedDate);
            return true;
          } catch {
            return false;
          }
        }))) {
          invalidResponse(`manager research reader ${materialsKey} are invalid`);
        }
      }
    }
    const attached = catalyst.reader_materials;
    if (attached !== undefined && (!Array.isArray(attached) || !attached.every((item) => {
      try {
        validateReaderMaterial(item, rowCode, expectedDate);
        return true;
      } catch {
        return false;
      }
    }))) {
      invalidResponse("manager research reader_materials are invalid");
    }
  }
}

/** Validate an exact V4 manager-research response before it reaches the view. */
export function validateManagerResearchResponse(
  value: unknown,
  expectedDate?: string,
): ManagerResearchResponse {
  if (!isRecord(value)) invalidResponse("manager research response must be an object");
  if (hasOwn(value, "error")) invalidResponse("manager research response contains a top-level error");
  if (value.schema_version !== MANAGER_RESEARCH_SCHEMA) {
    invalidResponse("manager research schema_version is invalid");
  }
  if (value.stage_id !== MANAGER_STAGE_ID) {
    invalidResponse("manager research stage_id must be STAGE_0935_0940");
  }
  if (value.market !== MANAGER_STAGE_MARKET) {
    invalidResponse("manager research market must be HK_CONNECT");
  }
  if (!isGregorianDate(value.target_trade_date)) {
    invalidResponse("manager research target_trade_date is invalid");
  }
  if (expectedDate !== undefined) {
    if (!isGregorianDate(expectedDate) || value.target_trade_date !== expectedDate) {
      invalidResponse("manager research target_trade_date does not match the request");
    }
  }
  const status = value.status;
  if (typeof status !== "string" || !status.trim()) {
    invalidResponse("manager research response status is missing");
  }
  const product = value.product;
  if (product === null) {
    if (!NULL_PRODUCT_STATUSES.has(status)) {
      invalidResponse("manager research null product status is invalid");
    }
  } else {
    if (!isRecord(product)) invalidResponse("manager research product is missing");
    if (product.schema_version !== MANAGER_RESEARCH_SCHEMA) {
      invalidResponse("manager research product schema_version is invalid");
    }
    if (!isGregorianDate(product.target_trade_date) || product.target_trade_date !== value.target_trade_date) {
      invalidResponse("manager research product target_trade_date does not match the response");
    }
    if (expectedDate !== undefined && product.target_trade_date !== expectedDate) {
      invalidResponse("manager research product target_trade_date does not match the request");
    }
    if (!Array.isArray(product.rows) || !product.rows.every(isRecord)) {
      invalidResponse("manager research product rows must be an array of objects");
    }
    if (product.stage_id !== MANAGER_STAGE_ID) {
      invalidResponse("manager research product stage_id must be STAGE_0935_0940");
    }
    if (product.market !== MANAGER_STAGE_MARKET) {
      invalidResponse("manager research product market must be HK_CONNECT");
    }
    if (product.stage_id !== value.stage_id || product.market !== value.market) {
      invalidResponse("manager research product stage/market does not match the response");
    }
  }
  requireSafetyFlags(value, "manager research response");
  if (product !== null) {
    requireSafetyFlags(product, "manager research product");
    const productRows = product.rows;
    if (!Array.isArray(productRows) || !productRows.every(isRecord)) {
      invalidResponse("manager research product rows must be an array of objects");
    }
    for (const row of productRows) {
      if (typeof row.code !== "string" || !row.code.trim()) invalidResponse("manager research row code is missing");
      if (row.target_trade_date !== product.target_trade_date) {
        invalidResponse("manager research row target_trade_date does not match the product");
      }
      if (row.facts !== undefined && (!Array.isArray(row.facts) || !row.facts.every(isRecord))) {
        invalidResponse("manager research row facts must be an array of objects");
      }
      if (row.source !== undefined && !isRecord(row.source)) {
        invalidResponse("manager research row source must be an object");
      }
      // V2 rows carry the research opinion and execution gate together under
      // research_recommendation.  Keep this optional for the legacy product
      // envelope, but reject a partially shaped v2 object before it reaches
      // the view; the adapter must never infer an opinion from a malformed
      // wrapper.
      if (row.research_recommendation !== undefined) {
        if (!isRecord(row.research_recommendation)) {
          invalidResponse("manager research row research_recommendation must be an object");
        }
        if (!isRecord(row.research_recommendation.investment_advice)) {
          invalidResponse("manager research row investment_advice must be an object");
        }
        if (!isRecord(row.research_recommendation.execution_gate)) {
          invalidResponse("manager research row execution_gate must be an object");
        }
        const asOf = row.research_recommendation.as_of;
        if (asOf !== undefined) {
          if (!isRecord(asOf)) {
            invalidResponse("manager research row recommendation as_of must be an object");
          }
          if (!isGregorianDate(asOf.target_trade_date)
            || asOf.target_trade_date !== value.target_trade_date
            || asOf.target_trade_date !== product.target_trade_date
            || (expectedDate !== undefined && asOf.target_trade_date !== expectedDate)) {
            invalidResponse("manager research row recommendation as_of target_trade_date does not match the request");
          }
        }
      }
    }
    validateReaderProjection(product, value.target_trade_date);
  }
  return value as ManagerResearchResponse;
}

async function load(
  date: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  const url = `/api/v4/manager/research?date=${encodeURIComponent(date)}`;
  let response: Response;
  try {
    response = await fetch(
      url,
      options ? { cache: "no-store", signal: options.signal } : { cache: "no-store" },
    );
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "NETWORK_REJECTED",
      "manager research network request rejected",
      undefined,
      reason,
    );
  }
  if (!response.ok) {
    throw new ManagerResearchRequestError(
      "HTTP_NON_2XX",
      `manager research request failed (HTTP ${response.status})`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "INVALID_RESPONSE",
      "manager research response is not valid JSON",
      undefined,
      reason,
    );
  }
  try {
    return validateManagerResearchResponse(payload, date);
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "manager research response shape is invalid",
      undefined,
      reason,
    );
  }
}

async function requestJson(
  url: string,
  date: string,
  options: RequestInit,
): Promise<ManagerResearchResponse> {
  let response: Response;
  try {
    response = await fetch(url, options);
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "NETWORK_REJECTED",
      "manager research network request rejected",
      undefined,
      reason,
    );
  }
  if (!response.ok) {
    throw new ManagerResearchRequestError(
      "HTTP_NON_2XX",
      `manager research request failed (HTTP ${response.status})`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "INVALID_RESPONSE",
      "manager research response is not valid JSON",
      undefined,
      reason,
    );
  }
  try {
    return validateManagerResearchResponse(payload, date);
  } catch (reason) {
    throw new ManagerResearchRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "manager research response shape is invalid",
      undefined,
      reason,
    );
  }
}

export function loadManagerResearchExact(
  date: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  return load(date, options);
}

/** Start at most one server-owned exact-date materialization job. */
export function ensureManagerResearchExact(
  date: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  const requestInit: RequestInit = { method: "POST", cache: "no-store" };
  if (options?.signal) requestInit.signal = options.signal;
  return requestJson(
    `/api/v4/manager/research/ensure?date=${encodeURIComponent(date)}`,
    date,
    requestInit,
  );
}

/** Refresh bounded catalyst evidence for the same exact product. */
export function refreshManagerResearchEventsExact(
  date: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  const requestInit: RequestInit = { method: "POST", cache: "no-store" };
  if (options?.signal) requestInit.signal = options.signal;
  return requestJson(
    `/api/v4/manager/research/events?date=${encodeURIComponent(date)}`,
    date,
    requestInit,
  );
}

/** Read the exact-date job state without creating another job. */
export function loadManagerResearchStatusExact(
  date: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  const requestInit: RequestInit = { cache: "no-store" };
  if (options?.signal) requestInit.signal = options.signal;
  return requestJson(
    `/api/v4/manager/research/status?date=${encodeURIComponent(date)}`,
    date,
    requestInit,
  );
}

/** Consume one existing job by id; the server still binds the result to date. */
export function loadManagerResearchJobExact(
  date: string,
  jobId: string,
  options?: ManagerResearchRequestOptions,
): Promise<ManagerResearchResponse> {
  if (!jobId.trim()) {
    return Promise.reject(new ManagerResearchRequestError(
      "INVALID_RESPONSE",
      "manager research job id is missing",
    ));
  }
  const requestInit: RequestInit = { cache: "no-store" };
  if (options?.signal) requestInit.signal = options.signal;
  return requestJson(
    `/api/v4/manager/research/jobs/${encodeURIComponent(jobId)}?date=${encodeURIComponent(date)}`,
    date,
    requestInit,
  );
}

export const MANAGER_RESEARCH_SCHEMA_VERSION = MANAGER_RESEARCH_SCHEMA;
