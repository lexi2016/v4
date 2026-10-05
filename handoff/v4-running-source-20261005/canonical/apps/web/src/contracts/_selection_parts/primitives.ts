// Extracted source declarations; review candidate, not production acceptance.
import { RUN_ID_PATTERN, SHA256_PATTERN } from "./schema";
import type { SelectionRecord } from "./types";


export function isSelectionRecord(value: unknown): value is SelectionRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function hasOwn(value: SelectionRecord, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function validSelectionDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

export function validSha(value: unknown): value is string {
  return typeof value === "string" && SHA256_PATTERN.test(value);
}

export function validRunId(value: unknown): value is string {
  return typeof value === "string" && RUN_ID_PATTERN.test(value);
}

export function parsedTimestamp(value: unknown): Date | null {
  if (typeof value !== "string" || !value) return null;
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? new Date(milliseconds) : null;
}

export function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  if (!isSelectionRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalValue(value[key])]),
  );
}

export function sameWireValue(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(canonicalValue(left)) === JSON.stringify(canonicalValue(right));
  } catch {
    return false;
  }
}

export function canonicalJson(value: unknown): string | null {
  try {
    const serialized = JSON.stringify(canonicalValue(value));
    return typeof serialized === "string" ? serialized : null;
  } catch {
    return null;
  }
}

export async function canonicalSha256(value: unknown): Promise<string | null> {
  const serialized = canonicalJson(value);
  const cryptoApi = globalThis.crypto;
  if (!serialized || !cryptoApi?.subtle || typeof TextEncoder === "undefined") return null;
  try {
    const digest = await cryptoApi.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(serialized),
    );
    return [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}

export function missingOrExtraFields(
  value: SelectionRecord,
  required: Set<string>,
  allowed: Set<string>,
  label: string,
): string | null {
  const missing = [...required].filter((key) => !hasOwn(value, key));
  if (missing.length) return `${label} 字段不完整，缺少 ${missing.join(", ")}`;
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  if (extra.length) return `${label} 包含未允许 wire 字段: ${extra.join(", ")}`;
  return null;
}

export function validStringList(value: unknown, label: string): string | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    return `${label} 必须是字符串数组`;
  }
  const values = value as string[];
  if (values.some((item) => !item)) return `${label} 含空字符串`;
  if (JSON.stringify(values) !== JSON.stringify([...new Set(values)].sort())) {
    return `${label} 必须排序且唯一`;
  }
  return null;
}