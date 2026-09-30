// Extracted source declarations; review candidate, not production acceptance.
import { canonicalSha256, hasOwn, isNonEmptyString, isSelectionRecord, missingOrExtraFields, parsedTimestamp, validRunId, validSha, validStringList } from "./primitives";
import { LINEAGE_FIELDS, SNAPSHOT_FIELDS, SNAPSHOT_STATUS_SET } from "./schema";
import type { SelectionRecord } from "./types";


export function applySelectionChanges(
  changes: unknown[],
  currentIds: Set<string>,
  candidateIds: Set<string>,
  phase: string,
): { ids: Set<string>; issue: string | null } {
  const next = new Set(currentIds);
  const seen = new Set<string>();
  for (const change of changes) {
    if (!isSelectionRecord(change) || Object.keys(change).length !== 2 || !hasOwn(change, "action") || !hasOwn(change, "candidate_id")) {
      return { ids: next, issue: `${phase} changes 字段不可确认` };
    }
    const action = change.action;
    const candidateId = change.candidate_id;
    if ((action !== "KEEP" && action !== "ADD" && action !== "REMOVE") || !isNonEmptyString(candidateId)) {
      return { ids: next, issue: `${phase} changes 操作不可确认` };
    }
    if (!candidateIds.has(candidateId)) return { ids: next, issue: `${phase} changes 含未知 candidate_id` };
    if (seen.has(candidateId)) return { ids: next, issue: `${phase} changes candidate 重复` };
    seen.add(candidateId);
    if (action === "KEEP" && !next.has(candidateId)) return { ids: next, issue: `${phase} KEEP candidate 不在当前集合` };
    if (action === "ADD") {
      if (next.has(candidateId)) return { ids: next, issue: `${phase} ADD candidate 已在当前集合` };
      next.add(candidateId);
    }
    if (action === "REMOVE") {
      if (!next.has(candidateId)) return { ids: next, issue: `${phase} REMOVE candidate 不在当前集合` };
      next.delete(candidateId);
    }
  }
  return { ids: next, issue: null };
}

export async function validateSelectionSnapshot(
  value: unknown,
  phase: string,
  candidateIds: Set<string>,
): Promise<string | null> {
  if (!isSelectionRecord(value)) return `${phase} snapshot 不是对象`;
  const fieldIssue = missingOrExtraFields(value, SNAPSHOT_FIELDS, SNAPSHOT_FIELDS, `${phase} snapshot`);
  if (fieldIssue) {
    const missing = [...SNAPSHOT_FIELDS].filter((key) => !hasOwn(value, key));
    return missing.length ? `${phase} snapshot 缺少必需字段 ${missing.join(", ")}` : fieldIssue;
  }
  if (value.phase !== phase || typeof value.status !== "string" || !SNAPSHOT_STATUS_SET.has(value.status)) return `${phase} snapshot identity 不可确认`;
  const listIssue = validStringList(value.candidate_ids, `${phase} snapshot candidate_ids`);
  if (listIssue) return listIssue;
  const ids = value.candidate_ids as string[];
  if (ids.some((id) => !candidateIds.has(id))) return `${phase} snapshot 含未知 candidate_id`;
  if (!Array.isArray(value.changes)) return `${phase} snapshot changes 不是数组`;
  const seenChanges = new Set<string>();
  for (const change of value.changes) {
    if (!isSelectionRecord(change) || Object.keys(change).length !== 2 || !isNonEmptyString(change.candidate_id) || (change.action !== "KEEP" && change.action !== "ADD" && change.action !== "REMOVE")) {
      return `${phase} snapshot changes 字段不可确认`;
    }
    if (!candidateIds.has(change.candidate_id) || seenChanges.has(change.candidate_id)) return `${phase} snapshot changes candidate 不可确认`;
    seenChanges.add(change.candidate_id);
  }
  if (value.status !== "READY") {
    if (value.run_id !== null || value.event_at !== null || value.artifact_sha256 !== null || value.freeze_run_id !== null || value.freeze_snapshot_sha256 !== null || value.snapshot_sha256 !== null) {
      return `${phase} 未物化 snapshot 不得携带 identity`;
    }
    if (ids.length || value.changes.length) return `${phase} 未物化 snapshot 不得携带候选或 changes`;
    return null;
  }
  if (!validRunId(value.run_id)) return `${phase} snapshot 缺少有效 run_id`;
  if (!parsedTimestamp(value.event_at)) return `${phase} snapshot 缺少有效 event_at`;
  if (!validSha(value.artifact_sha256)) return `${phase} snapshot 缺少有效 artifact_sha256`;
  if (!validSha(value.snapshot_sha256)) return `${phase} snapshot 缺少有效 snapshot_sha256`;
  const snapshotBody = Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "snapshot_sha256"),
  );
  const calculatedSnapshotSha = await canonicalSha256(snapshotBody);
  if (!calculatedSnapshotSha) return `${phase} snapshot SHA 无法验证`;
  if (value.snapshot_sha256 !== calculatedSnapshotSha) return `${phase} snapshot SHA mismatch`;
  if (phase === "2200" || phase === "0830") {
    if (value.freeze_run_id !== null || value.freeze_snapshot_sha256 !== null) return `${phase} snapshot 不得携带 freeze binding`;
  } else {
    if (!validRunId(value.freeze_run_id) || !validSha(value.freeze_snapshot_sha256)) return `${phase} snapshot 缺少适用 freeze binding`;
  }
  return null;
}

export function validateSelectionLineage(
  value: unknown,
  product: SelectionRecord,
  targetDate: string,
): string | null {
  if (!isSelectionRecord(value)) return "materialized selection 缺少 lineage";
  const fieldIssue = missingOrExtraFields(value, LINEAGE_FIELDS, LINEAGE_FIELDS, "lineage");
  if (fieldIssue) return fieldIssue;
  const runId = product.run_id;
  if (!validRunId(runId) || value.run_id !== runId || value.target_trade_date !== targetDate) return "lineage run/date binding 不一致";
  for (const field of ["artifact_path", "manifest_path", "receipt_path", "current_path"]) {
    if (!isNonEmptyString(value[field]) || !value[field].includes(targetDate)) return `lineage ${field} 不含 target_trade_date`;
  }
  for (const part of ["artifact", "manifest", "receipt"] as const) {
    if (!String(value[`${part}_path`]).includes(runId)) return `lineage ${part}_path 不含 run_id`;
  }
  for (const field of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) {
    if (!validSha(value[field])) return `lineage 字段不完整，${field} 不可确认`;
    const alias = product[field];
    if (!validSha(alias) || alias !== value[field]) return `lineage ${field} 与 top-level SHA alias 不一致`;
  }
  return null;
}

export function validateSelectionObservations(value: unknown, field: "intraday_observations" | "outcomes"): string | null {
  if (!Array.isArray(value) || value.some((item) => !isSelectionRecord(item))) return `${field} 必须是对象数组`;
  for (const item of value) {
    if (field === "intraday_observations" && item.kind !== "APPEND_ONLY") return "intraday observation 必须是 APPEND_ONLY";
    if (field === "outcomes" && item.kind !== "OUTCOME_REFERENCE") return "outcome 必须是 OUTCOME_REFERENCE";
    if (hasOwn(item, "observed_at") && !parsedTimestamp(item.observed_at)) return `${field}.observed_at 不可确认`;
  }
  return null;
}