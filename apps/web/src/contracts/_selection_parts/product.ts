// Extracted source declarations; review candidate, not production acceptance.
import { validateManagerDecisionProjection, validateSelectionCandidate, validateSelectionFormalAuthority, validateSelectionFormalRefs, validateSelectionSourceRef } from "./evidence";
import { hasOwn, isNonEmptyString, isSelectionRecord, missingOrExtraFields, parsedTimestamp, sameWireValue, validRunId, validSelectionDate, validSha, validStringList } from "./primitives";
import { COUNTS_FIELDS, ORIGIN_SET, PHASE_SET, PRODUCT_OPTIONAL_FIELDS, PRODUCT_REQUIRED_FIELDS, PRODUCT_STATUS_SET, RESEARCH_SUPPLY_ACCEPTANCE, RESEARCH_SUPPLY_TYPE, SELECTION_PASS_SIGNAL, SELECTION_PHASES, SELECTION_SCHEMA_VERSION, SELECTION_TIMEZONE, SELECTION_WORKFLOW_NAME } from "./schema";
import { applySelectionChanges, validateSelectionLineage, validateSelectionObservations, validateSelectionSnapshot } from "./snapshots";
import type { SelectionRecord } from "./types";


/**
 * Validate a response from the exact-date selection API.
 *
 * This is a consumer-side fail-closed check.  It returns a human-readable
 * issue for the UI instead of throwing, and never changes the response.
 */
export async function validateSelectionProduct(value: unknown, targetDate: string): Promise<string | null> {
  if (!isSelectionRecord(value)) return "selection response 不是对象";
  const fieldIssue = missingOrExtraFields(value, PRODUCT_REQUIRED_FIELDS, new Set([...PRODUCT_REQUIRED_FIELDS, ...PRODUCT_OPTIONAL_FIELDS]), "selection response");
  if (fieldIssue) return fieldIssue;
  if (value.schema_version !== SELECTION_SCHEMA_VERSION) return `schema_version 不是 ${SELECTION_SCHEMA_VERSION}`;
  if (value.contract_id !== SELECTION_SCHEMA_VERSION) return "contract_id 不匹配 selection research product";
  if (value.workflow_name !== SELECTION_WORKFLOW_NAME) return "workflow_name 不匹配 selection research product";
  if (value.pass_signal !== SELECTION_PASS_SIGNAL) return "pass_signal 不匹配 selection research product";
  if (value.endpoint_mode !== "EXACT") return "endpoint_mode 不是 EXACT";
  if (value.timezone !== SELECTION_TIMEZONE) return "timezone 不是 Asia/Shanghai";
  if (value.target_trade_date !== targetDate || !validSelectionDate(value.target_trade_date)) return "target_trade_date 与请求不一致";
  if (value.requested_date !== targetDate || !validSelectionDate(value.requested_date)) return "requested_date 与请求不一致";
  if (typeof value.status !== "string" || !PRODUCT_STATUS_SET.has(value.status)) return "status 不在 selection contract 中";
  if (value.RESEARCH_ONLY !== true || value.production_allowed !== false || value.buy_gate_updated !== false || value.orders_sent !== false) {
    return "安全四旗未满足只读边界";
  }
  const candidates = value.research_candidates;
  if (!Array.isArray(candidates)) return "research_candidates 不是数组";
  const status = value.status as string;
  const materialized = status !== "NOT_MATERIALIZED" && status !== "CANNOT_CONFIRM";
  if (materialized) {
    if (!validSelectionDate(value.source_date)) return "materialized 产品必须提供有效 source_date";
    if (!validRunId(value.run_id)) return "materialized 产品必须提供 run_id";
    if (!ORIGIN_SET.has(String(value.origin))) return "materialized 产品 origin 不可确认";
    const generated = parsedTimestamp(value.generated_at);
    const cutoff = parsedTimestamp(value.cutoff_at);
    if (!generated || !cutoff) return "materialized 产品必须提供 generated_at/cutoff_at";
    if (cutoff.getTime() > generated.getTime()) return "materialized 产品 cutoff_at 不得晚于 generated_at";
    if (value.acceptance !== RESEARCH_SUPPLY_ACCEPTANCE && value.acceptance !== "EARLY_DRAFT_FROZEN_ONLY") return "materialized 产品 acceptance 不可确认";
    if (status === "READY" && !candidates.length) return "READY 产品必须包含研究候选";
  } else if (value.source_date !== null || value.run_id !== null || value.origin !== null || value.generated_at !== null || value.cutoff_at !== null) {
    return `${status} 响应不得携带 materialized identity`;
  }
  const formal = value.formal_shortlist;
  if (!Array.isArray(formal) || formal.some((id) => typeof id !== "string" || !id) || JSON.stringify(formal) !== JSON.stringify([...new Set(formal)].sort())) {
    return "formal_shortlist 不是排序且唯一的字符串数组";
  }
  const candidateIds: string[] = [];
  for (const candidate of candidates) {
    const issue = validateSelectionCandidate(
      candidate,
      String(value.source_date || ""),
      parsedTimestamp(value.cutoff_at) || new Date(0),
      targetDate,
    );
    if (issue) return issue;
    if (!isSelectionRecord(candidate) || typeof candidate.candidate_id !== "string") return "research_candidates 含无效 candidate_id";
    if (candidateIds.includes(candidate.candidate_id)) return "research_candidates 含重复 candidate_id";
    candidateIds.push(candidate.candidate_id);
  }
  if (JSON.stringify(candidateIds) !== JSON.stringify([...candidateIds].sort())) return "research_candidates 必须按 candidate_id 排序";
  const candidateIdSet = new Set(candidateIds);
  if (formal.some((id) => !candidateIdSet.has(id))) return "formal_shortlist 含未知 candidate_id";
  if (!validSelectionDate(value.source_date) && value.status !== "NOT_MATERIALIZED" && value.status !== "CANNOT_CONFIRM") return "source_date 不是有效日期";
  const counts = value.counts;
  if (!isSelectionRecord(counts)) return "counts 不是对象";
  const countsIssue = missingOrExtraFields(counts, COUNTS_FIELDS, COUNTS_FIELDS, "counts");
  if (countsIssue) return countsIssue;
  const expectedCounts = {
    research_candidates: candidates.length,
    formal_shortlist: formal.length,
    snapshots: SELECTION_PHASES.length,
    intraday_observations: Array.isArray(value.intraday_observations) ? value.intraday_observations.length : -1,
    outcomes: Array.isArray(value.outcomes) ? value.outcomes.length : -1,
  };
  for (const key of Object.keys(expectedCounts) as Array<keyof typeof expectedCounts>) {
    if (typeof counts[key] !== "number" || !Number.isInteger(counts[key]) || counts[key] < 0 || counts[key] !== expectedCounts[key]) {
      return key === "research_candidates" ? "counts.research_candidates 与数组长度不一致" : `counts.${key} 与数组长度不一致`;
    }
  }
  const observationIssue = validateSelectionObservations(value.intraday_observations, "intraday_observations");
  if (observationIssue) return observationIssue;
  const outcomeIssue = validateSelectionObservations(value.outcomes, "outcomes");
  if (outcomeIssue) return outcomeIssue;
  const formalAuthorityIssue = validateSelectionFormalAuthority(value.formal_authority, targetDate);
  if (formalAuthorityIssue) return formalAuthorityIssue;
  const formalAuthority = value.formal_authority as SelectionRecord;
  const snapshots = value.snapshots;
  if (!isSelectionRecord(snapshots) || Object.keys(snapshots).length !== SELECTION_PHASES.length || Object.keys(snapshots).some((phase) => !PHASE_SET.has(phase))) {
    return "snapshots 未完整覆盖 2200/0830/0935/1620";
  }
  for (const phase of SELECTION_PHASES) {
    const issue = await validateSelectionSnapshot(snapshots[phase], phase, candidateIdSet);
    if (issue) return issue;
  }
  const snapshotsByPhase = snapshots as SelectionRecord;
  const snapshot2200 = snapshotsByPhase["2200"] as SelectionRecord;
  const snapshot0830 = snapshotsByPhase["0830"] as SelectionRecord;
  const snapshot0935 = snapshotsByPhase["0935"] as SelectionRecord;
  const snapshot1620 = snapshotsByPhase["1620"] as SelectionRecord;
  if (snapshot2200.status === "READY" && (snapshot2200.changes as unknown[]).length) return "2200 READY snapshot 初始阶段不得携带 changes";
  const sourceTypes = new Set<string>();
  for (const candidate of candidates) {
    for (const ref of (candidate as SelectionRecord).source_refs as unknown[]) {
      if (isSelectionRecord(ref) && typeof ref.type === "string") sourceTypes.add(ref.type);
    }
  }
  if (sourceTypes.size > 1) return "selection product source_ref 类型混用";
  const supplyProduct = sourceTypes.has(RESEARCH_SUPPLY_TYPE);
  if (candidates.length && value.acceptance !== (supplyProduct ? RESEARCH_SUPPLY_ACCEPTANCE : "EARLY_DRAFT_FROZEN_ONLY")) return "selection product acceptance 与来源类型不一致";
  const managerDecisionRef = value.manager_decision_ref;
  if (managerDecisionRef !== null && managerDecisionRef !== undefined) {
    if (!supplyProduct || !isSelectionRecord(managerDecisionRef) || Object.keys(managerDecisionRef).length !== 2 || !isNonEmptyString(managerDecisionRef.path) || !validSha(managerDecisionRef.raw_sha256)) {
      return "manager_decision_ref 不是严格的 ref";
    }
  }
  if (supplyProduct && snapshot2200.status === "READY" && managerDecisionRef === null || supplyProduct && snapshot2200.status === "READY" && managerDecisionRef === undefined) return "research supply 2200 缺少 manager_decision_ref";
  if (supplyProduct && snapshot2200.status !== "READY" && managerDecisionRef !== null && managerDecisionRef !== undefined) return "research supply manager_decision_ref 没有 2200 snapshot 依据";
  const projectedCandidates = candidates.filter((candidate) =>
    isSelectionRecord(candidate) && hasOwn(candidate, "manager_decision"));
  if (projectedCandidates.length) {
    if (managerDecisionRef === null || managerDecisionRef === undefined) {
      return "manager_decision projection 缺少严格 ref";
    }
    if (snapshot2200.status !== "READY") {
      return "manager_decision projection 需要 READY 的 2200 snapshot";
    }
    if (!isSelectionRecord(managerDecisionRef)
      || snapshot2200.artifact_sha256 !== managerDecisionRef.raw_sha256) {
      return "manager_decision projection ref 与 2200 snapshot 不一致";
    }
    const projectedIds = projectedCandidates
      .map((candidate) => (candidate as SelectionRecord).candidate_id)
      .filter((id): id is string => typeof id === "string");
    if (!sameWireValue(projectedIds.sort(), [...(snapshot2200.candidate_ids as string[])].sort())) {
      return "manager_decision projection 与 2200 snapshot 候选集合不一致";
    }
    const selectionCutoff = parsedTimestamp(value.cutoff_at);
    if (!selectionCutoff) return "manager_decision projection cutoff 不可确认";
    const roleOrders: Record<"CORE" | "CONDITIONAL", number[]> = {
      CORE: [],
      CONDITIONAL: [],
    };
    for (const candidate of projectedCandidates) {
      const projection = (candidate as SelectionRecord).manager_decision;
      const issue = validateManagerDecisionProjection(
        projection,
        String(value.source_date),
        targetDate,
        selectionCutoff,
        String(snapshot2200.run_id),
        String(snapshot2200.event_at),
      );
      if (issue) return `manager_decision projection 不可确认：${issue}`;
      const typedProjection = projection as SelectionRecord;
      roleOrders[typedProjection.role as "CORE" | "CONDITIONAL"].push(
        typedProjection.order as number,
      );
    }
    for (const role of ["CORE", "CONDITIONAL"] as const) {
      const orders = roleOrders[role].sort((left, right) => left - right);
      if (orders.length > 5 || orders.some((order, index) => order !== index + 1)) {
        return `manager_decision projection ${role} role/order 不连续或超过上限`;
      }
    }
  }
  if (snapshot0830.status === "READY") {
    if (snapshot2200.status !== "READY") return "0830 READY 依赖 READY 的 2200";
    const applied = applySelectionChanges(snapshot0830.changes as unknown[], new Set(snapshot2200.candidate_ids as string[]), candidateIdSet, "0830");
    if (applied.issue) return applied.issue;
    if (JSON.stringify([...applied.ids].sort()) !== JSON.stringify(snapshot0830.candidate_ids)) return "0830 changes 与候选集合不一致";
  }
  for (const [phase, snapshot] of [["0935", snapshot0935], ["1620", snapshot1620]] as Array<[string, SelectionRecord]>) {
    if (snapshot.status !== "READY") continue;
    if (snapshot0830.status !== "READY") return `${phase} READY 依赖 READY 的 0830`;
    if (snapshot.freeze_run_id !== snapshot0830.run_id || snapshot.freeze_snapshot_sha256 !== snapshot0830.snapshot_sha256) return `${phase} freeze binding 与 0830 不一致`;
    const applied = applySelectionChanges(snapshot.changes as unknown[], new Set(snapshot0830.candidate_ids as string[]), candidateIdSet, phase);
    if (applied.issue) return applied.issue;
    if ([...applied.ids].sort().join("\n") !== (snapshot.candidate_ids as string[]).join("\n")) return `${phase} changes 与候选集合不一致`;
    if ((snapshot.changes as Array<SelectionRecord>).some((change) => change.action === "REMOVE" || (change.action === "KEEP" && !(snapshot0830.candidate_ids as string[]).includes(change.candidate_id as string)) || (change.action === "ADD" && (snapshot0830.candidate_ids as string[]).includes(change.candidate_id as string)))) return `${phase} changes 改写 0830 freeze`;
    if ([...(new Set(snapshot.candidate_ids as string[]))].sort().join("\n") !== [...(new Set(snapshot0830.candidate_ids as string[]))].sort().join("\n")) return `${phase} 改变 0830 frozen membership`;
  }
  if (snapshot0935.status === "READY" && !(value.intraday_observations as SelectionRecord[]).some((item) => item.kind === "APPEND_ONLY" && item.freeze_run_id === snapshot0830.run_id && item.freeze_snapshot_sha256 === snapshot0830.snapshot_sha256)) return "0935 READY 缺少绑定 0830 的 append-only observation";
  if (snapshot1620.status === "READY" && !(value.outcomes as SelectionRecord[]).some((item) => item.kind === "OUTCOME_REFERENCE" && item.freeze_run_id === snapshot0830.run_id && item.freeze_snapshot_sha256 === snapshot0830.snapshot_sha256)) return "1620 READY 缺少绑定 0830 的 outcome";
  const refs = value.source_refs;
  if (!Array.isArray(refs)) return "source_refs 不是数组";
  for (const ref of refs) {
    const issue = validateSelectionSourceRef(ref, validSelectionDate(value.source_date) ? value.source_date : "");
    if (issue) return issue;
  }
  const flattenedRefs = candidates.flatMap((candidate) => (candidate as SelectionRecord).source_refs as unknown[]);
  if (!sameWireValue(refs, flattenedRefs)) return "source_refs 与 candidates 不一致";
  if (materialized) {
    if (!candidates.length) return "READY 产品必须包含研究候选";
    const lineageIssue = validateSelectionLineage(value.lineage, value, targetDate);
    if (lineageIssue) return lineageIssue;
    for (const alias of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) {
      if (!validSha(value[alias])) return `lineage 字段不完整，缺少 ${alias}`;
    }
  } else {
    if (value.source_date !== null || value.run_id !== null || value.origin !== null || value.generated_at !== null || value.cutoff_at !== null) return `${status} 响应不得携带 materialized identity`;
    if (value.acceptance !== "NOT_MATERIALIZED" || candidates.length || formal.length || refs.length) return `${status} 响应必须保持空研究账本`;
    if (value.lineage !== null) return `${status} 响应不得携带 lineage`;
    for (const alias of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) if (hasOwn(value, alias)) return `${status} 响应不得携带 ${alias}`;
    if (managerDecisionRef !== null && managerDecisionRef !== undefined) return `${status} 响应不得携带 manager_decision_ref`;
    if (!["2200", "0830", "0935", "1620"].every((phase) => (snapshotsByPhase[phase] as SelectionRecord).status !== "READY")) return `${status} 响应不得声明 READY snapshot`;
    if (status === "CANNOT_CONFIRM" && !isNonEmptyString(value.first_failed_layer)) return "CANNOT_CONFIRM 响应必须声明 first_failed_layer";
    if (!isNonEmptyString(value.first_failed_layer)) return `${status} 响应必须声明 first_failed_layer`;
  }
  const routeStatus = value.route_status;
  if (!isSelectionRecord(routeStatus) || Object.keys(routeStatus).length !== 4 || !["R1", "R2", "R6", "GEMINI"].every((key) => isNonEmptyString(routeStatus[key]))) return "route_status 必须严格分离 R1/R2/R6/GEMINI";
  if (routeStatus.R6 === "GEMINI_DISCOVERY_UNVERIFIED") return "selection R6 不得冒充 Gemini";
  if (value.gemini_status !== "UNVERIFIED" && value.gemini_status !== "NOT_MATERIALIZED") return "Gemini status 不可确认";
  if (routeStatus.GEMINI !== value.gemini_status) return "Gemini route/status 不一致";
  const cannotIssue = validStringList(value.cannot_confirm, "cannot_confirm");
  if (cannotIssue) return cannotIssue;
  const cannotConfirm = value.cannot_confirm as string[];
  if (!isNonEmptyString(value.first_failed_layer) && cannotConfirm.length) return "cannot_confirm 缺少 first_failed_layer";
  const gaps = new Set<string>();
  for (const phase of SELECTION_PHASES) {
    if ((snapshotsByPhase[phase] as SelectionRecord).status !== "READY") gaps.add(supplyProduct && phase === "2200" ? "SUPPLY_2200_DECISION_NOT_MATERIALIZED" : `SNAPSHOT_${phase}_NOT_MATERIALIZED`);
  }
  if (!formal.length || formalAuthority.status !== "READY") gaps.add("FORMAL_AUTHORITY_NOT_MATERIALIZED");
  if (candidates.some((candidate) => (candidate as SelectionRecord).pit_status !== "READY")) gaps.add("CANDIDATE_PIT_NOT_CONFIRMED");
  if (materialized) {
    const actualGaps = cannotConfirm;
    const expectedGaps = [...gaps].sort();
    if (JSON.stringify(actualGaps) !== JSON.stringify(expectedGaps)) return "selection cannot_confirm gaps 不一致";
    const expectedFirst = expectedGaps[0] || null;
    if (value.first_failed_layer !== expectedFirst) return "selection first_failed_layer 不一致";
    const anyReady = SELECTION_PHASES.some((phase) => (snapshotsByPhase[phase] as SelectionRecord).status === "READY");
    const expectedStatus = anyReady ? (expectedGaps.length ? "READY_WITH_DECLARED_GAPS" : "READY") : (supplyProduct ? "RESEARCH_SUPPLY_IMPORTED" : "EARLY_DRAFT_IMPORTED");
    if (status !== expectedStatus) return `status 与 materialized phases 不一致，期望 ${expectedStatus}`;
    if (status === "READY" && (formalAuthority.status !== "READY" || !formal.length || expectedGaps.length)) return "READY 产品必须完成 formal authority 与全部阶段";
  } else {
    if (status !== "NOT_MATERIALIZED" && status !== "CANNOT_CONFIRM") return "空研究账本必须是 NOT_MATERIALIZED 或 CANNOT_CONFIRM";
  }
  if (formal.length) {
    if (formalAuthority.status !== "READY") return "formal_shortlist 缺少 READY authority";
    const byId = new Map(candidates.map((candidate) => [String((candidate as SelectionRecord).candidate_id), candidate as SelectionRecord]));
    for (const id of formal) {
      const candidate = byId.get(id);
      if (!candidate || candidate.eligibility !== "ELIGIBLE" || candidate.pit_status !== "READY") return "formal_shortlist candidate gate 不完整";
    }
    const formalRefsIssue = validateSelectionFormalRefs(formalAuthority, formal, String(value.source_date), targetDate);
    if (formalRefsIssue) return formalRefsIssue;
  }
  return null;
}