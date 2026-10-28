// Extracted source declarations; review candidate, not production acceptance.
import { hasOwn, isNonEmptyString, isSelectionRecord, missingOrExtraFields, parsedTimestamp, validRunId, validSha } from "./primitives";
import { CANDIDATE_FIELDS, CANDIDATE_OPTIONAL_FIELDS, EARLY_DRAFT_TYPE, EARLY_SOURCE_REQUIRED_FIELDS, FORMAL_AUTHORITY_FIELDS, MANAGER_DECISION_PROJECTION_FIELDS, MANAGER_DECISION_PROJECTION_ROLES, RESEARCH_SUPPLY_ACCEPTANCE, RESEARCH_SUPPLY_TYPE, SUPPLY_SOURCE_FIELDS } from "./schema";
import type { SelectionRecord } from "./types";


export function validateSelectionSourceRef(value: unknown, sourceDate: string): string | null {
  if (!isSelectionRecord(value)) return "source_ref 不是对象";
  const type = value.type;
  if (type === RESEARCH_SUPPLY_TYPE) {
    const issue = missingOrExtraFields(value, SUPPLY_SOURCE_FIELDS, SUPPLY_SOURCE_FIELDS, "research supply source_ref");
    if (issue) return issue;
    if (!isNonEmptyString(value.path) || !isNonEmptyString(value.supply_receipt_path)) {
      return "research supply source_ref path 不可为空";
    }
    if (!validSha(value.raw_sha256) || !validSha(value.frozen_payload_sha256) || !validSha(value.supply_receipt_sha256)) {
      return "research supply source_ref SHA 不可确认";
    }
    if (typeof value.json_pointer !== "string" || !/^\/frozen_payload\/event_cards\/(?:0|[1-9][0-9]*)$/.test(value.json_pointer)) {
      return "research supply source_ref JSON pointer 不可确认";
    }
    if (value.source_date !== sourceDate) return "research supply source_ref 日期不一致";
    if (!parsedTimestamp(value.source_time)) return "research supply source_ref source_time 不可确认";
    return null;
  }
  if (type !== EARLY_DRAFT_TYPE) return "source_ref type 不是受支持的冻结来源";
  const missing = [...EARLY_SOURCE_REQUIRED_FIELDS].filter((key) => !hasOwn(value, key));
  if (missing.length) return `early draft source_ref 字段不完整，缺少 ${missing.join(", ")}`;
  if (!isNonEmptyString(value.path) || !validSha(value.raw_sha256) || !validSha(value.frozen_payload_sha256)) {
    return "early draft source_ref path 或 SHA 不可确认";
  }
  if (typeof value.json_pointer !== "string" || !/^\/frozen_payload\/event_cards\/(?:0|[1-9][0-9]*)$/.test(value.json_pointer)) {
    return "early draft source_ref JSON pointer 不可确认";
  }
  if (value.source_date !== sourceDate) return "early draft source_ref 日期不一致";
  if (!parsedTimestamp(value.source_time)) return "early draft source_ref source_time 不可确认";
  return null;
}

export function validateManagerDecisionProjection(
  value: unknown,
  sourceDate: string,
  targetDate: string,
  cutoff: Date,
  expectedRunId?: string,
  expectedGeneratedAt?: string,
): string | null {
  if (!isSelectionRecord(value)) return "manager_decision 必须是对象";
  const fieldIssue = missingOrExtraFields(
    value,
    MANAGER_DECISION_PROJECTION_FIELDS,
    MANAGER_DECISION_PROJECTION_FIELDS,
    "manager_decision",
  );
  if (fieldIssue) return fieldIssue;
  if (value.schema_version !== "v3_5.manager_research_decision.v1") {
    return "manager_decision schema_version 不可确认";
  }
  if (value.phase !== "2200") return "manager_decision phase 不可确认";
  if (value.decision_state !== "INITIAL_RESEARCH_DELTA") {
    return "manager_decision decision_state 不可确认";
  }
  if (value.source_date !== sourceDate) return "manager_decision source_date 不一致";
  if (value.target_trade_date !== targetDate) return "manager_decision target_trade_date 不一致";
  if (!validRunId(value.run_id)) return "manager_decision run_id 不可确认";
  if (expectedRunId !== undefined && value.run_id !== expectedRunId) {
    return "manager_decision run_id 与 2200 snapshot 不一致";
  }
  const generated = parsedTimestamp(value.generated_at);
  const projectionCutoff = parsedTimestamp(value.cutoff_at);
  if (!generated || !projectionCutoff) return "manager_decision 时间不可确认";
  if (projectionCutoff.getTime() > generated.getTime()) {
    return "manager_decision cutoff_at 不得晚于 generated_at";
  }
  if (projectionCutoff.getTime() !== cutoff.getTime()) {
    return "manager_decision cutoff_at 与 selection 不一致";
  }
  if (expectedGeneratedAt !== undefined && value.generated_at !== expectedGeneratedAt) {
    return "manager_decision generated_at 与 2200 snapshot 不一致";
  }
  if (!MANAGER_DECISION_PROJECTION_ROLES.has(String(value.role))) {
    return "manager_decision role 不可确认";
  }
  if (!Number.isInteger(value.order) || (value.order as number) < 1 || (value.order as number) > 5) {
    return "manager_decision order 不可确认";
  }
  if (typeof value.reason !== "string" || !value.reason.trim()) return "manager_decision reason 不可确认";
  return null;
}

export function validateSelectionCandidate(
  value: unknown,
  sourceDate: string,
  cutoff: Date,
  targetDate: string,
): string | null {
  if (!isSelectionRecord(value)) return "research candidate 不是对象";
  const fieldIssue = missingOrExtraFields(
    value,
    CANDIDATE_FIELDS,
    new Set([...CANDIDATE_FIELDS, ...CANDIDATE_OPTIONAL_FIELDS]),
    "research candidate",
  );
  if (fieldIssue) return fieldIssue;
  const candidateId = value.candidate_id;
  if (!isNonEmptyString(candidateId)) return "candidate_id 不可为空";
  for (const field of [
    "event_stock_link_id",
    "market",
    "normalized_code",
    "entity_id",
    "event_id",
    "acceptance",
    "eligibility",
    "pit_status",
    "research_status",
    "recommendation_status",
  ]) {
    if (!isNonEmptyString(value[field])) return `candidate ${candidateId} 的 ${field} 不可为空`;
  }
  if (value.research_status !== "RESEARCH_ONLY") return `candidate ${candidateId} research_status 必须是 RESEARCH_ONLY`;
  if (value.recommendation_status !== "RESEARCH_ONLY") return `candidate ${candidateId} recommendation_status 必须是 RESEARCH_ONLY`;
  if (value.eligibility !== "ELIGIBILITY_CANNOT_CONFIRM" && value.eligibility !== "ELIGIBLE") {
    return `candidate ${candidateId} eligibility 不可确认`;
  }
  if (value.pit_status !== "READY" && value.pit_status !== "PIT_FAILED" && value.pit_status !== "CANNOT_CONFIRM") {
    return `candidate ${candidateId} pit_status 不可确认`;
  }
  for (const field of [
    "bucket",
    "catalyst",
    "counterevidence",
    "invalidation",
    "evidence_level",
    "financial_bridge",
    "consensus",
    "overnight_pending",
    "source_status",
    "published_at",
    "source_time",
  ]) {
    if (typeof value[field] !== "string") return `candidate ${candidateId} 的 ${field} 必须是字符串`;
  }
  if (!isSelectionRecord(value.source_metadata)) return `candidate ${candidateId} 缺少 source_metadata`;
  if (value.published_at_aware !== null && !parsedTimestamp(value.published_at_aware)) {
    return `candidate ${candidateId} published_at_aware 不可确认`;
  }
  const sourceTime = parsedTimestamp(value.source_time);
  if (!sourceTime) return `candidate ${candidateId} source_time 不可确认`;
  const refs = value.source_refs;
  if (!Array.isArray(refs) || refs.length === 0) return `candidate ${candidateId} 缺少 source_refs`;
  const sourceTypes = new Set<string>();
  for (const ref of refs) {
    const issue = validateSelectionSourceRef(ref, sourceDate);
    if (issue) return `candidate ${candidateId}: ${issue}`;
    if (isSelectionRecord(ref) && typeof ref.type === "string") sourceTypes.add(ref.type);
  }
  if (sourceTypes.size !== 1) return `candidate ${candidateId} source_ref 类型混用`;
  const expectedAcceptance = sourceTypes.has(RESEARCH_SUPPLY_TYPE)
    ? RESEARCH_SUPPLY_ACCEPTANCE
    : "EARLY_DRAFT_FROZEN_ONLY";
  if (value.acceptance !== expectedAcceptance) return `candidate ${candidateId} acceptance 不是冻结研究来源`;
  const entityId = value.entity_id as string;
  const entityDot = entityId.lastIndexOf(".");
  if (entityDot <= 0 || entityDot === entityId.length - 1) return `candidate ${candidateId} entity_id 不可确认`;
  const entityCode = entityId.slice(0, entityDot);
  const entityMarket = entityId.slice(entityDot + 1);
  if ((value.market as string).toUpperCase() !== entityMarket.toUpperCase()
    || (value.normalized_code as string).toUpperCase() !== entityCode.toUpperCase()) {
    return `candidate ${candidateId} identity 字段不一致`;
  }
  const expectedCandidateId = `${entityMarket.toUpperCase()}.${entityCode.toUpperCase()}|${entityId}`;
  if (candidateId !== expectedCandidateId) return `candidate ${candidateId} identity 不可重建`;
  if (value.event_stock_link_id !== `${value.event_id}|${expectedCandidateId}`) {
    return `candidate ${candidateId} event_stock_link_id 不一致`;
  }
  const routeStatus = value.route_status;
  if (!isSelectionRecord(routeStatus) || Object.keys(routeStatus).length !== 2 || !hasOwn(routeStatus, "R1") || !hasOwn(routeStatus, "R6")) {
    return `candidate ${candidateId} route_status 必须严格分离 R1/R6`;
  }
  if (!isNonEmptyString(routeStatus.R1) || !isNonEmptyString(routeStatus.R6)) return `candidate ${candidateId} route_status 不可确认`;
  if (routeStatus.R6 === "GEMINI_DISCOVERY_UNVERIFIED") return `candidate ${candidateId} R6 不得冒充 Gemini`;
  if (value.gemini_status !== "UNVERIFIED" && value.gemini_status !== "NOT_MATERIALIZED") {
    return `candidate ${candidateId} gemini_status 不可确认`;
  }
  if (value.pit_status === "READY") {
    const publishedAware = parsedTimestamp(value.published_at_aware);
    if (!publishedAware) return `candidate ${candidateId} PIT READY 缺少 published_at_aware`;
    if (publishedAware.getTime() > cutoff.getTime() && sourceTypes.has(EARLY_DRAFT_TYPE)) {
      return `candidate ${candidateId} PIT READY 超过 cutoff`;
    }
  }
  if (hasOwn(value, "manager_decision")) {
    const projectionIssue = validateManagerDecisionProjection(
      value.manager_decision,
      sourceDate,
      targetDate,
      cutoff,
    );
    if (projectionIssue) return `candidate ${candidateId}: ${projectionIssue}`;
  }
  return null;
}

export function validateSelectionFormalAuthority(value: unknown, targetDate: string): string | null {
  if (!isSelectionRecord(value)) return "formal_authority 不是对象";
  const fieldIssue = missingOrExtraFields(value, FORMAL_AUTHORITY_FIELDS, FORMAL_AUTHORITY_FIELDS, "formal_authority");
  if (fieldIssue) return fieldIssue;
  if (value.status !== "READY" && value.status !== "NOT_MATERIALIZED" && value.status !== "STALE" && value.status !== "CANNOT_CONFIRM") {
    return "formal_authority status 不可确认";
  }
  if (value.target_trade_date !== targetDate) return "formal_authority 日期证据不一致";
  if (typeof value.pit_status !== "string" || typeof value.selector_status !== "string") return "formal_authority gates 缺失";
  if (typeof value.research_evidence !== "boolean" || typeof value.manager_decision !== "boolean") return "formal_authority gates 必须是 boolean";
  if (!Array.isArray(value.evidence_refs) || value.evidence_refs.some((ref) => !isSelectionRecord(ref))) return "formal_authority evidence_refs 不可确认";
  if (value.manager_decision_ref !== null && !isSelectionRecord(value.manager_decision_ref)) return "formal_authority manager_decision_ref 不可确认";
  if (value.status === "READY") {
    if (value.pit_status !== "READY" || value.selector_status !== "READY" || value.research_evidence !== true || value.manager_decision !== true) {
      return "formal_authority READY gates 不完整";
    }
    if (!value.evidence_refs.length || !isSelectionRecord(value.manager_decision_ref)) return "formal_authority READY references 不完整";
    if (!validSha(value.source_sha256)) return "formal_authority READY source_sha256 不可确认";
    for (const ref of value.evidence_refs) {
      if (!isNonEmptyString(ref.path) || !validSha(ref.sha256)) return "formal_authority evidence ref path/SHA 不可确认";
    }
    const decisionRef = value.manager_decision_ref;
    if (!isNonEmptyString(decisionRef.path) || !validSha(decisionRef.sha256)) return "formal_authority manager decision ref path/SHA 不可确认";
  } else {
    if (value.source_sha256 !== null && !validSha(value.source_sha256)) return "formal_authority source_sha256 不可确认";
  }
  return null;
}

export function validateSelectionFormalRefs(
  authority: SelectionRecord,
  formalIds: string[],
  sourceDate: string,
  targetDate: string,
): string | null {
  const expectedSourceSha = authority.source_sha256;
  if (!validSha(expectedSourceSha)) return "formal_authority READY source_sha256 不可确认";
  const evidenceRefs = authority.evidence_refs;
  const decisionRef = authority.manager_decision_ref;
  if (!Array.isArray(evidenceRefs) || !evidenceRefs.length || !isSelectionRecord(decisionRef)) {
    return "formal_authority READY references 不完整";
  }
  const authorityRunIds = new Set<string>();
  const validateBindingList = (value: unknown, label: string): string | null => {
    if (!Array.isArray(value) || value.length !== formalIds.length) return `${label} candidate_bindings 不完整`;
    const seen: string[] = [];
    for (const binding of value) {
      if (!isSelectionRecord(binding)
        || !hasOwn(binding, "candidate_id")
        || !hasOwn(binding, "eligibility")
        || !hasOwn(binding, "pit_status")
        || !hasOwn(binding, "source_refs")) return `${label} candidate binding 字段不完整`;
      const candidateId = binding.candidate_id;
      if (typeof candidateId !== "string" || !formalIds.includes(candidateId) || seen.includes(candidateId)) {
        return `${label} candidate binding identity 不一致`;
      }
      if (binding.eligibility !== "ELIGIBLE" || binding.pit_status !== "READY") return `${label} candidate source proof status 不完整`;
      if (!Array.isArray(binding.source_refs) || !binding.source_refs.length) return `${label} candidate source binding refs 缺失`;
      for (const ref of binding.source_refs) {
        const issue = validateSelectionSourceRef(ref, sourceDate);
        if (issue) return `${label}: ${issue}`;
      }
      seen.push(candidateId);
    }
    if (JSON.stringify(seen) !== JSON.stringify(formalIds)) return `${label} candidate binding order 不一致`;
    return null;
  };
  for (const ref of evidenceRefs) {
    if (!isSelectionRecord(ref)) return "formal_authority evidence ref 不是对象";
    for (const field of [
      "schema_version",
      "type",
      "path",
      "sha256",
      "source_sha256",
      "source_date",
      "target_trade_date",
      "run_id",
      "candidate_ids",
      "status",
      "pit_status",
      "candidate_bindings",
    ]) {
      if (!hasOwn(ref, field)) return "formal_authority evidence ref 字段不完整";
    }
    if (ref.schema_version !== "v3_5.selection_formal_evidence.v1" || ref.type !== "EXACT_DATE_PIT") return "formal_authority evidence ref schema/type 不可确认";
    if (!isNonEmptyString(ref.path) || !validSha(ref.sha256) || ref.source_sha256 !== expectedSourceSha) return "formal_authority evidence ref SHA/source binding 不一致";
    if (ref.source_date !== sourceDate || ref.target_trade_date !== targetDate || !validRunId(ref.run_id)) return "formal_authority evidence ref date/run binding 不一致";
    if (!Array.isArray(ref.candidate_ids) || JSON.stringify(ref.candidate_ids) !== JSON.stringify(formalIds) || ref.status !== "READY" || ref.pit_status !== "READY") return "formal_authority evidence ref candidate binding 不一致";
    const bindingIssue = validateBindingList(ref.candidate_bindings, "formal_authority evidence");
    if (bindingIssue) return bindingIssue;
    authorityRunIds.add(ref.run_id);
  }
  const ref = decisionRef;
  for (const field of [
    "schema_version",
    "type",
    "path",
    "sha256",
    "source_sha256",
    "source_date",
    "target_trade_date",
    "run_id",
    "candidate_ids",
    "decision",
    "candidate_bindings",
  ]) {
    if (!hasOwn(ref, field)) return "formal_authority manager decision ref 字段不完整";
  }
  if (ref.schema_version !== "v3_5.selection_manager_decision.v1" || ref.type !== "MANAGER_DECISION") return "formal_authority manager decision ref schema/type 不可确认";
  if (!isNonEmptyString(ref.path) || !validSha(ref.sha256) || ref.source_sha256 !== expectedSourceSha) return "formal_authority manager decision ref SHA/source binding 不一致";
  if (ref.source_date !== sourceDate || ref.target_trade_date !== targetDate || !validRunId(ref.run_id)) return "formal_authority manager decision ref date/run binding 不一致";
  if (!Array.isArray(ref.candidate_ids) || JSON.stringify(ref.candidate_ids) !== JSON.stringify(formalIds) || ref.decision !== true) return "formal_authority manager decision ref candidate binding 不一致";
  const decisionBindingIssue = validateBindingList(ref.candidate_bindings, "formal_authority manager decision");
  if (decisionBindingIssue) return decisionBindingIssue;
  authorityRunIds.add(ref.run_id);
  if (authorityRunIds.size !== 1) return "formal_authority refs 使用冲突的 authority run";
  return null;
}